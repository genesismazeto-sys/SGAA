# coding: utf-8
"""STORAGE S2 (prod-1/v14) on real PostgreSQL: E-PG1 constraints, E-PG2 concurrency.

Runs only with ``SGAA_PG_TEST_URL`` (a role with CREATE DATABASE); otherwise the
module skips (REAL-PG EVIDENCE: ABSENT).  One template database (prefix
``sgaa_s2st_test_<run>_``) is provisioned through ``app.pg_schema`` and seeded;
every node works on its own ``CREATE DATABASE ... TEMPLATE`` clone, dropped at
teardown together with the template.

E-PG1: the same constraint vectors as the SQLite suite
(``tests/storage_s2_support.py``), business FK / exclusivity / RESTRICT, the
intent transition trigger (SQLSTATE SG001) and the primitives through the
runtime connection adapter.

E-PG2: two connections claiming with ``FOR UPDATE SKIP LOCKED`` never take the
same row and never wait; an expired lease is reclaimed and the stale worker
cannot complete; two consumers of one intent and two binders of one object
serialize (the loser is proven to be WAITING via ``pg_stat_activity`` before the
winner commits -- no sleep is used as a correctness proof).
"""
from __future__ import annotations

import os
import secrets
import threading
import time
from urllib.parse import urlsplit, urlunsplit

import pytest

PG_URL = os.environ.get("SGAA_PG_TEST_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not PG_URL, reason="SGAA_PG_TEST_URL is not configured -- REAL-PG EVIDENCE: ABSENT"
)

psycopg = pytest.importorskip("psycopg")

from app import pg_schema  # noqa: E402
from app.db import _PostgresConnectionAdapter, write_transaction  # noqa: E402
from app.pg_migrate_from_sqlite import run_domain_checks  # noqa: E402
from app.storage import mirror_outbox as outbox  # noqa: E402
from app.storage import upload_intents as intents  # noqa: E402
from app.storage.custody_common import CustodyError  # noqa: E402
from tests.storage_s2_support import (  # noqa: E402
    ACCOUNT_KEY,
    BUCKET,
    OTHER_ACCOUNT_KEY,
    INTENT_CASES,
    OBJECT_CASES,
    TS,
    WORKER_CASES,
    insert_sql,
    intent_row,
    object_row,
    worker_row,
)

RUN_PREFIX = f"sgaa_s2st_test_{secrets.token_hex(4)}_"
PROTECTED_DATABASES = frozenset({"postgres", "template0", "template1", "sgaa_qual"})
SHA = "e" * 64

SEED_SQL = (
    "INSERT INTO usuarios(id,nome,email,senha,tipo) VALUES(1,'Admin','s2a@x.test','x','admin')",
    "INSERT INTO usuarios(id,nome,email,senha,tipo) VALUES(2,'Aluno','s2b@x.test','x','aluno')",
    "INSERT INTO usuario_credenciais(usuario_id,estado,auth_version,atualizado_em,acesso_ativo) "
    "VALUES(1,'personal',1,'2026-01-01 00:00:00',1)",
    "INSERT INTO usuario_credenciais(usuario_id,estado,auth_version,atualizado_em,acesso_ativo) "
    "VALUES(2,'personal',1,'2026-01-01 00:00:00',1)",
    "INSERT INTO cloud_accounts(id,provider,token_json) VALUES(1,'google','{}')",
    "INSERT INTO atividade_base(id,nome_conceito) VALUES(1,'Conceito')",
    "INSERT INTO atividade_versao(id,atividade_base_id,eixo) VALUES(1,1,'AAC')",
    "INSERT INTO requisicoes(id,atividade_versao_id,data_solicitacao,data_evento,horas_solicitadas,status,"
    "regra_snapshot_json) VALUES(1,1,'2026-01-01','2026-01-01',1,'Pendente','{}')",
    "INSERT INTO requisicao_arquivos(id,requisicao_id,filename) VALUES(1,1,'a.pdf')",
    "INSERT INTO requisicao_arquivos(id,requisicao_id,filename) VALUES(2,1,'b.pdf')",
    "INSERT INTO admin_arquivos(id,titulo,filename) VALUES(1,'Manual','m.pdf')",
)


def _url(database):
    parts = urlsplit(PG_URL)
    return urlunsplit((parts.scheme, parts.netloc, "/" + database, "connect_timeout=10", ""))


def _raw(url, *, autocommit=False):
    return psycopg.connect(url, prepare_threshold=None, autocommit=autocommit, connect_timeout=10)


def _adapter(url):
    raw = _raw(url)
    raw.isolation_level = psycopg.IsolationLevel.READ_COMMITTED
    return _PostgresConnectionAdapter(raw)


class _Registry:
    def __init__(self):
        self.admin = _raw(PG_URL, autocommit=True)
        self.created = []
        self.template = None

    def create(self, template=None):
        name = f"{RUN_PREFIX}{secrets.token_hex(3)}"
        assert name.startswith(RUN_PREFIX) and name not in PROTECTED_DATABASES
        suffix = f' TEMPLATE "{template}"' if template else ""
        self.admin.execute(f'CREATE DATABASE "{name}"{suffix}')
        self.created.append(name)
        return name, _url(name)

    def drop(self, name):
        assert name.startswith(RUN_PREFIX) and name not in PROTECTED_DATABASES
        try:
            self.admin.execute(f'DROP DATABASE IF EXISTS "{name}"')
        except psycopg.errors.ObjectInUse:
            self.admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        self.created.remove(name)

    def close(self):
        for name in reversed(list(self.created)):
            try:
                self.drop(name)
            except Exception:  # pragma: no cover - teardown best effort, reported by leftover census
                pass
        self.admin.close()


@pytest.fixture(scope="module")
def registry():
    registry = _Registry()
    try:
        template, url = registry.create()
        conn = _raw(url)
        try:
            pg_schema.provision_pg_schema(conn)
            for statement in SEED_SQL:
                conn.execute(statement)
            for table in ("usuarios", "cloud_accounts", "atividade_base", "atividade_versao", "requisicoes",
                          "requisicao_arquivos", "admin_arquivos"):
                conn.execute(f"ALTER TABLE {table} ALTER COLUMN id RESTART WITH 100")
            conn.commit()
        finally:
            conn.close()
        registry.template = template
        yield registry
    finally:
        registry.close()
    leftovers = _raw(PG_URL, autocommit=True)
    try:
        assert leftovers.execute(
            "SELECT count(*) FROM pg_database WHERE datname LIKE %s", (RUN_PREFIX + "%",)
        ).fetchone()[0] == 0
    finally:
        leftovers.close()


@pytest.fixture
def db(registry):
    name, url = registry.create(template=registry.template)
    yield url
    registry.drop(name)


def _sqlstate(conn, sql, params=(), *, keep=False):
    """SQLSTATE of ``sql`` (None when accepted); undone unless ``keep``."""
    conn.execute("SAVEPOINT probe")
    try:
        conn.execute(sql, params)
        if not keep:
            conn.execute("ROLLBACK TO SAVEPOINT probe")
        return None
    except psycopg.Error as exc:
        conn.execute("ROLLBACK TO SAVEPOINT probe")
        return exc.sqlstate
    finally:
        conn.execute("RELEASE SAVEPOINT probe")


# --- E-PG1 ---------------------------------------------------------------------------


def test_fresh_v14_authority_validates_and_is_empty(db):
    conn = _raw(db)
    try:
        status = pg_schema.validate_pg_schema(conn)
        assert (status["schema_version"], status["trigger_count"]) == (14, 17)
        assert [tuple(r) for r in conn.execute(
            "SELECT version, name FROM schema_migrations WHERE version = 14").fetchall()] == [(14, "canonical_storage")]
        for table in ("storage_objects", "storage_upload_intents", "storage_worker_status"):
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
        assert not any(run_domain_checks(conn).values())
    finally:
        conn.close()


def test_constraint_vectors_match_sqlite(db):
    conn = _raw(db)
    try:
        sql, params = insert_sql("storage_objects", object_row(), "%s")
        assert conn.execute(sql + " RETURNING id", params).fetchone()[0] == 1
        outcomes = {}
        for table, cases, build in (
            ("storage_objects", OBJECT_CASES,
             lambda o: object_row(**{"storage_key": "comprovantes/x/" + "f" * 8, **o})),
            ("storage_upload_intents", INTENT_CASES, lambda o: intent_row(**o)),
            ("storage_worker_status", WORKER_CASES, lambda o: worker_row(**o)),
        ):
            for label, overrides, accepted in cases:
                row = build(overrides)
                state = _sqlstate(conn, *insert_sql(table, row, "%s"))
                outcomes[(table, label)] = (state is None, state)
                assert (state is None) is accepted, (table, label, state)
                if state is not None:
                    assert state in ("23514", "23502", "23503", "23505"), (table, label, state)
    finally:
        conn.rollback()
        conn.close()


def test_business_reference_fk_exclusivity_restrict_and_intent_trigger(db):
    conn = _raw(db)
    try:
        sql, params = insert_sql("storage_objects", object_row(storage_key=intent_row()["storage_key"],
                                                               sha256=intent_row()["declared_sha256"]), "%s")
        object_id = conn.execute(sql + " RETURNING id", params).fetchone()[0]
        conn.execute("UPDATE requisicao_arquivos SET storage_object_id = %s WHERE id = 1", (object_id,))
        assert _sqlstate(conn, "UPDATE requisicao_arquivos SET storage_object_id = %s WHERE id = 2",
                         (object_id,)) == "23505"
        assert _sqlstate(conn, "UPDATE admin_arquivos SET storage_object_id = %s WHERE id = 1",
                         (object_id,)) == pg_schema.PG_BUSINESS_RULE_SQLSTATE
        assert _sqlstate(conn, "INSERT INTO admin_arquivos(titulo, filename, storage_object_id) "
                               "VALUES ('x', 'x.pdf', %s)", (object_id,)) == pg_schema.PG_BUSINESS_RULE_SQLSTATE
        assert _sqlstate(conn, "UPDATE admin_arquivos SET storage_object_id = 999 WHERE id = 1") == "23503"
        assert _sqlstate(conn, "DELETE FROM storage_objects WHERE id = %s", (object_id,)) == "23503"
        # Existing custody trigger still governs the Google columns, unaware of the FK.
        assert _sqlstate(conn, "UPDATE requisicao_arquivos SET provider = 'dropbox' WHERE id = 1") == \
            pg_schema.PG_BUSINESS_RULE_SQLSTATE

        conn.execute(*insert_sql("storage_upload_intents", intent_row(), "%s"))
        for statement in (
            "UPDATE storage_upload_intents SET storage_key = 'comprovantes/x'",
            "UPDATE storage_upload_intents SET actor_user_id = 2",
            f"UPDATE storage_upload_intents SET state = 'consumed', verified_at = '{TS}', consumed_at = '{TS}', "
            f"storage_object_id = {object_id}",
        ):
            assert _sqlstate(conn, statement) == pg_schema.PG_BUSINESS_RULE_SQLSTATE, statement
        conn.execute(f"UPDATE storage_upload_intents SET state = 'verified', verified_at = '{TS}'")
        conn.execute(f"UPDATE storage_upload_intents SET state = 'consumed', consumed_at = '{TS}', "
                     f"storage_object_id = {object_id}")
        assert _sqlstate(conn, "UPDATE storage_upload_intents SET state = 'expired', consumed_at = NULL, "
                               "storage_object_id = NULL") == pg_schema.PG_BUSINESS_RULE_SQLSTATE
        conn.execute("UPDATE storage_upload_intents SET sweep_after = '2026-02-01 00:00:00'")
        assert not any(run_domain_checks(conn).values())
        # The domain checks see a cross-table owner even if a trigger were bypassed.
        conn.execute("ALTER TABLE admin_arquivos DISABLE TRIGGER trg_admin_arquivos_storage_object_update")
        conn.execute("UPDATE admin_arquivos SET storage_object_id = %s WHERE id = 1", (object_id,))
        assert run_domain_checks(conn)["storage_objects_shared_by_business_rows"] == 1
    finally:
        conn.rollback()
        conn.close()


def test_intent_lifecycle_through_the_runtime_adapter(db):
    conn = _adapter(db)
    try:
        with write_transaction(conn):
            issued = intents.issue_intent(
                conn, actor_user_id=2, purpose="comprovante", operation_id="op-pg", bucket=BUCKET,
                declared_mime_type="application/pdf", declared_size_bytes=10, declared_sha256=SHA, now=TS,
                requisicao_id=1)
        with write_transaction(conn):
            assert intents.issue_intent(
                conn, actor_user_id=2, purpose="comprovante", operation_id="op-pg", bucket=BUCKET,
                declared_mime_type="application/pdf", declared_size_bytes=10, declared_sha256=SHA, now=TS,
                requisicao_id=1) == issued
        with write_transaction(conn):
            intents.mark_verified(conn, intent_id=issued.id, actor_user_id=2, observed_size_bytes=10,
                                  observed_sha256=SHA, now=TS)
        with write_transaction(conn):
            consumed, object_id = intents.consume_intent(conn, intent_id=issued.id, actor_user_id=2,
                                                         purpose="comprovante", operation_id="op-pg", now=TS)
        assert consumed.state == "consumed" and consumed.storage_object_id == object_id
        with write_transaction(conn):
            assert intents.expire_intents(conn, now="2099-01-01 00:00:00") == 0
            assert intents.sweep_intents(conn, now="2099-01-01 00:00:00") == 1
        assert not any(run_domain_checks(conn.raw_connection).values())
    finally:
        conn.close()


def _seed_objects(url, count):
    conn = _raw(url)
    try:
        ids = []
        for index in range(count):
            sql, params = insert_sql("storage_objects", object_row(storage_key=f"comprovantes/2026/01/{index:032x}"),
                                     "%s")
            ids.append(conn.execute(sql + " RETURNING id", params).fetchone()[0])
        conn.commit()
        return ids
    finally:
        conn.close()


def test_retry_pending_reconciliation_on_postgres(db):
    retry_id, pending_id, reconcile_id = _seed_objects(db, 3)
    conn = _adapter(db)
    try:
        with write_transaction(conn):
            works = {w.object_id: w for w in outbox.claim_due_mirror_work(conn, limit=10, worker_token="a" * 32,
                                                                          now=TS)}
        with write_transaction(conn):
            outbox.mark_retry(conn, object_id=retry_id, lease_token="a" * 32, generation=works[retry_id].generation,
                              error_code="DRIVE_QUOTA", next_attempt_at="2026-01-02 04:00:00", now=TS)
            outbox.mark_pending_disconnected(conn, object_id=pending_id, lease_token="a" * 32,
                                             generation=works[pending_id].generation,
                                             next_attempt_at="2026-01-02 05:00:00", now=TS)
            outbox.mark_reconciliation_required(conn, object_id=reconcile_id, lease_token="a" * 32,
                                                generation=works[reconcile_id].generation,
                                                error_code="DRIVE_CONFLICT", now=TS)
        with write_transaction(conn):
            due = [w.object_id for w in outbox.claim_due_mirror_work(conn, limit=10, worker_token="b" * 32,
                                                                     now="2026-01-02 04:00:00")]
        assert due == [retry_id]
        with write_transaction(conn):
            outbox.record_worker_started(conn, now=TS)
            outbox.record_worker_finished(conn, now="2026-01-02 03:05:00", result_code="OK", claimed=3,
                                          synced=0, retried=1)
        assert outbox.read_worker_status(conn)["last_result_code"] == "OK"
        assert not any(run_domain_checks(conn.raw_connection).values())
    finally:
        conn.close()


# --- E-PG2 ---------------------------------------------------------------------------


def _backend_pid(conn) -> int:
    return int(conn.execute("SELECT pg_backend_pid()").fetchone()[0])


def _wait_until_lock_waiting(url, pid, deadline_seconds=15.0) -> None:
    """Poll pg_stat_activity until ``pid`` is waiting on a lock (state, not timing)."""
    observer = _raw(url, autocommit=True)
    try:
        deadline = time.monotonic() + deadline_seconds
        while time.monotonic() < deadline:
            row = observer.execute(
                "SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s", (pid,)
            ).fetchone()
            if row and row[0] == "Lock":
                return
            time.sleep(0.02)
        raise AssertionError("the second session never reached a lock wait")
    finally:
        observer.close()


def test_two_claimers_skip_locked_rows_without_waiting(db):
    ids = _seed_objects(db, 4)
    first, second = _adapter(db), _adapter(db)
    try:
        first.execute("SET lock_timeout = '2s'")
        second.execute("SET lock_timeout = '2s'")
        first.commit(), second.commit()
        with write_transaction(first):
            mine = outbox.claim_due_mirror_work(first, limit=2, worker_token="a" * 32, now=TS)
            # ``first`` still holds its row locks (uncommitted).  ``second`` must
            # neither wait (lock_timeout would raise) nor take the same rows.
            with write_transaction(second):
                theirs = outbox.claim_due_mirror_work(second, limit=10, worker_token="b" * 32, now=TS)
        mine_ids, theirs_ids = [w.object_id for w in mine], [w.object_id for w in theirs]
        assert mine_ids == ids[:2] and theirs_ids == ids[2:]
        assert not set(mine_ids) & set(theirs_ids)
        # A third claimer finds nothing due: every lease is live.
        with write_transaction(second):
            assert outbox.claim_due_mirror_work(second, limit=10, worker_token="c" * 32, now=TS) == []
        observer = _raw(db, autocommit=True)
        try:
            assert [tuple(r) for r in observer.execute(
                "SELECT lease_token, drive_generation FROM storage_objects ORDER BY id").fetchall()] == [
                ("a" * 32, 1), ("a" * 32, 1), ("b" * 32, 1), ("b" * 32, 1)]
        finally:
            observer.close()
    finally:
        first.close()
        second.close()


def test_expired_lease_is_reclaimed_and_the_stale_worker_cannot_complete(db):
    [object_id] = _seed_objects(db, 1)
    stale, fresh = _adapter(db), _adapter(db)
    try:
        with write_transaction(stale):
            [old] = outbox.claim_due_mirror_work(stale, limit=1, worker_token="a" * 32, now=TS, lease_seconds=60)
        expired = old.lease_expires_at
        with write_transaction(fresh):
            [new] = outbox.claim_due_mirror_work(fresh, limit=1, worker_token="b" * 32, now=expired)
        assert (new.object_id, new.generation) == (object_id, old.generation + 1)
        synced = dict(object_id=object_id, drive_file_id="drv-1", drive_parent_id=None, drive_account_key=ACCOUNT_KEY)
        for token, generation in (("a" * 32, old.generation), ("b" * 32, old.generation), ("a" * 32, new.generation)):
            with pytest.raises(CustodyError) as caught:
                with write_transaction(stale):
                    outbox.complete_synced(stale, lease_token=token, generation=generation, now=TS, **synced)
            assert caught.value.code == outbox.MIRROR_LEASE_LOST
        with write_transaction(fresh):
            outbox.complete_synced(fresh, lease_token="b" * 32, generation=new.generation,
                                   now="2026-01-02 03:06:00", **synced)
        # The stale worker's later retry/reconciliation attempts are fenced out too.
        for action in (
            lambda c: outbox.mark_retry(c, object_id=object_id, lease_token="a" * 32, generation=old.generation,
                                        error_code="X", next_attempt_at=TS, now=TS),
            lambda c: outbox.mark_reconciliation_required(c, object_id=object_id, lease_token="a" * 32,
                                                          generation=old.generation, error_code="X", now=TS),
        ):
            with pytest.raises(CustodyError):
                with write_transaction(stale):
                    action(stale)
        row = stale.execute("SELECT drive_sync_state, drive_file_id, lease_token FROM storage_objects").fetchone()
        assert tuple(row) == ("synced", "drv-1", None)
        stale.rollback()
    finally:
        stale.close()
        fresh.close()


def test_bound_account_key_is_immutable_and_independent_of_credential_rows(db):
    [object_id] = _seed_objects(db, 1)
    conn = _raw(db)
    try:
        conn.execute("UPDATE storage_objects SET drive_account_key = %s WHERE id = %s", (ACCOUNT_KEY, object_id))
        assert _sqlstate(conn, "UPDATE storage_objects SET drive_account_key = %s WHERE id = %s",
                         (OTHER_ACCOUNT_KEY, object_id)) == pg_schema.PG_BUSINESS_RULE_SQLSTATE
        assert _sqlstate(conn, "UPDATE storage_objects SET drive_account_key = NULL WHERE id = %s",
                         (object_id,)) == pg_schema.PG_BUSINESS_RULE_SQLSTATE
        # The format CHECK guards an unbound row (a bound one is refused first by the trigger).
        sql, params = insert_sql("storage_objects", object_row(storage_key="comprovantes/fmt/" + "c" * 8,
                                                               drive_account_key=ACCOUNT_KEY.upper()), "%s")
        assert _sqlstate(conn, sql, params) == "23514"
        assert _sqlstate(conn, "UPDATE cloud_accounts SET provider_account_key = 'x' WHERE id = 1") == "23514"
        conn.execute("UPDATE cloud_accounts SET provider_account_key = %s WHERE id = 1", (ACCOUNT_KEY,))
        assert conn.execute(
            "SELECT count(*) FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid "
            "JOIN pg_class r ON r.oid = c.confrelid WHERE c.contype = 'f' AND t.relname = 'storage_objects' "
            "AND r.relname = 'cloud_accounts'").fetchone()[0] == 0
        conn.execute("DELETE FROM cloud_accounts")  # credential rows are environment state
        assert conn.execute("SELECT drive_account_key FROM storage_objects").fetchone()[0] == ACCOUNT_KEY
        assert not any(run_domain_checks(conn).values())
    finally:
        conn.rollback()
        conn.close()


def test_release_expired_leases_skips_rows_another_session_holds(db):
    held_id, free_id = _seed_objects(db, 2)
    conn = _adapter(db)
    try:
        with write_transaction(conn):
            outbox.claim_due_mirror_work(conn, limit=2, worker_token="a" * 32, now=TS, lease_seconds=60)
    finally:
        conn.close()
    holder, releaser = _raw(db), _adapter(db)
    try:
        holder.execute("SELECT id FROM storage_objects WHERE id = %s FOR UPDATE", (held_id,))
        releaser.execute("SET lock_timeout = '2s'")
        releaser.commit()
        with write_transaction(releaser):
            assert outbox.release_expired_leases(releaser, now="2026-01-02 03:05:05", limit=10) == 1
        holder.rollback()
        rows = dict(releaser.execute("SELECT id, drive_sync_state FROM storage_objects").fetchall())
        assert rows == {held_id: "syncing", free_id: "retry"}
        releaser.rollback()
    finally:
        holder.close()
        releaser.close()


def _in_thread(target):
    outcome = {}

    def run():
        try:
            outcome["value"] = target()
        except BaseException as exc:  # pragma: no cover - surfaced through outcome
            outcome["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, outcome


def test_two_consumers_of_one_intent_serialize_and_only_one_object_exists(db):
    setup = _adapter(db)
    try:
        with write_transaction(setup):
            issued = intents.issue_intent(
                setup, actor_user_id=2, purpose="comprovante", operation_id="op-race", bucket=BUCKET,
                declared_mime_type="application/pdf", declared_size_bytes=10, declared_sha256=SHA, now=TS)
        with write_transaction(setup):
            intents.mark_verified(setup, intent_id=issued.id, actor_user_id=2, observed_size_bytes=10,
                                  observed_sha256=SHA, now=TS)
    finally:
        setup.close()
    winner, loser = _adapter(db), _adapter(db)
    consume = dict(intent_id=issued.id, actor_user_id=2, purpose="comprovante", operation_id="op-race", now=TS)
    try:
        loser_pid = _backend_pid(loser)
        loser.commit()
        with write_transaction(winner):
            _intent, object_id = intents.consume_intent(winner, **consume)

            def losing():
                with write_transaction(loser):
                    return intents.consume_intent(loser, **consume)

            thread, outcome = _in_thread(losing)
            _wait_until_lock_waiting(db, loser_pid)
        thread.join(30)
        assert not thread.is_alive()
        assert isinstance(outcome.get("error"), CustodyError)
        assert outcome["error"].code == intents.INTENT_STATE_INVALID
        observer = _raw(db, autocommit=True)
        try:
            assert observer.execute("SELECT count(*) FROM storage_objects").fetchone()[0] == 1
            assert observer.execute("SELECT storage_object_id FROM storage_upload_intents").fetchone()[0] == object_id
        finally:
            observer.close()
    finally:
        winner.close()
        loser.close()


def test_two_binders_of_one_object_serialize_and_the_second_owner_is_refused(db):
    [object_id] = _seed_objects(db, 1)
    winner, loser = _raw(db), _raw(db)
    try:
        loser_pid = _backend_pid(loser)
        loser.commit()
        winner.execute("UPDATE requisicao_arquivos SET storage_object_id = %s WHERE id = 1", (object_id,))

        def losing():
            try:
                loser.execute("UPDATE admin_arquivos SET storage_object_id = %s WHERE id = 1", (object_id,))
                loser.commit()
                return None
            except psycopg.Error as exc:
                loser.rollback()
                return exc.sqlstate

        thread, outcome = _in_thread(losing)
        _wait_until_lock_waiting(db, loser_pid)
        winner.commit()
        thread.join(30)
        assert not thread.is_alive()
        assert outcome.get("value") == pg_schema.PG_BUSINESS_RULE_SQLSTATE
        observer = _raw(db, autocommit=True)
        try:
            assert not any(run_domain_checks(observer).values())
            assert observer.execute("SELECT storage_object_id FROM admin_arquivos WHERE id = 1").fetchone()[0] is None
        finally:
            observer.close()
    finally:
        winner.close()
        loser.close()
