# coding: utf-8
"""STORAGE S3-A RED on real PostgreSQL (opt-in, ``SGAA_PG_TEST_URL``).

Without ``SGAA_PG_TEST_URL`` the module skips (REAL-PG EVIDENCE: ABSENT).  One
template database (prefix ``sgaa_s3a_test_<run>_``) is provisioned through
``app.pg_schema``; every node works on its own ``CREATE DATABASE ... TEMPLATE``
clone, dropped at teardown together with the template.

RED (needs v15):
    * the PostgreSQL authority is at v15 and its business-row custody verdicts
      equal the SQLite vectors (``tests/storage_s3a_support.py``);
    * request INSERT + intent consume + canonical attach commit or roll back
      as ONE PostgreSQL transaction.
GREEN controls (S2 primitives S3-A builds on; must stay green):
    * two concurrent finalizers of one intent serialize on the row lock and
      the loser observes ``verified`` (the basis of idempotent finalize);
    * two concurrent issuers of one operation get the same single intent.
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
from app.storage import upload_intents as intents  # noqa: E402
from app.storage.custody_common import CustodyError  # noqa: E402
from tests.storage_s3a_support import (  # noqa: E402
    ADMIN_ROW_CASES,
    BUCKET,
    NEW_OBJECT,
    PDF,
    REQUEST_ROW_CASES,
    SUBMISSION_ID,
    TS,
    UPLOAD_SLOTS,
    canonical_request_row,
    insert_sql,
    materialize,
    object_row_for,
    operation_id,
    sha256,
)

RUN_PREFIX = f"sgaa_s3a_test_{secrets.token_hex(4)}_"
PROTECTED_DATABASES = frozenset({"postgres", "template0", "template1", "sgaa_qual"})

SEED_SQL = (
    "INSERT INTO usuarios(id,nome,email,senha,tipo) VALUES(1,'Admin','s3a1@x.test','x','admin')",
    "INSERT INTO usuarios(id,nome,email,senha,tipo) VALUES(2,'Aluno','s3a2@x.test','x','aluno')",
    "INSERT INTO usuario_credenciais(usuario_id,estado,auth_version,atualizado_em,acesso_ativo) "
    "VALUES(1,'personal',1,'2026-01-01 00:00:00',1)",
    "INSERT INTO usuario_credenciais(usuario_id,estado,auth_version,atualizado_em,acesso_ativo) "
    "VALUES(2,'personal',1,'2026-01-01 00:00:00',1)",
    "INSERT INTO atividade_base(id,nome_conceito) VALUES(1,'Conceito')",
    "INSERT INTO atividade_versao(id,atividade_base_id,eixo) VALUES(1,1,'AAC')",
    "INSERT INTO requisicoes(id,atividade_versao_id,data_solicitacao,data_evento,horas_solicitadas,status,"
    "regra_snapshot_json) VALUES(1,1,'2026-01-01','2026-01-01',1,'Pendente','{}')",
)
REQUEST_INSERT = (
    "INSERT INTO requisicoes(atividade_versao_id,data_solicitacao,data_evento,horas_solicitadas,status,"
    "regra_snapshot_json) VALUES(1,'2026-01-01','2026-01-01',1,'Pendente','{}') RETURNING id"
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
            for table in ("usuarios", "atividade_base", "atividade_versao", "requisicoes"):
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


def _pg_verdict(conn, table, row, index):
    conn.execute("SAVEPOINT probe")
    try:
        object_id = None
        if any(value is NEW_OBJECT for value in row.values()):
            sql, params = insert_sql("storage_objects", object_row_for(f"{table[:3]}{index:029d}"), "%s")
            object_id = conn.execute(sql + " RETURNING id", params).fetchone()[0]
        conn.execute(*insert_sql(table, materialize(row, object_id), "%s"))
        return None
    except psycopg.Error as exc:
        return exc.sqlstate
    finally:
        conn.execute("ROLLBACK TO SAVEPOINT probe")
        conn.execute("RELEASE SAVEPOINT probe")


def test_pg_authority_is_v15(db):
    conn = _raw(db)
    try:
        assert pg_schema.PG_SCHEMA_VERSION == 16
        assert pg_schema.validate_pg_schema(conn)["schema_version"] == 16
    finally:
        conn.close()


@pytest.mark.parametrize(
    ("table", "cases"),
    [("requisicao_arquivos", REQUEST_ROW_CASES), ("admin_arquivos", ADMIN_ROW_CASES)],
    ids=["requisicao_arquivos", "admin_arquivos"],
)
def test_pg_business_custody_verdicts_equal_the_sqlite_vectors(db, table, cases):
    conn = _raw(db)
    try:
        observed, expected = {}, {}
        for index, (label, row, accepted) in enumerate(cases):
            state = _pg_verdict(conn, table, row, index)
            observed[label] = state is None
            expected[label] = accepted
            if state is not None:
                assert state in ("23514", "23502", "23503", "23505", pg_schema.PG_BUSINESS_RULE_SQLSTATE), (
                    label, state)
        assert {k for k in expected if observed[k] != expected[k]} == set()
    finally:
        conn.rollback()
        conn.close()


def _verified_intent(url, *, operation=operation_id(SUBMISSION_ID, UPLOAD_SLOTS[0]), content=PDF,
                     requisicao_id=None):
    setup = _adapter(url)
    try:
        with write_transaction(setup):
            issued = intents.issue_intent(
                setup, actor_user_id=2, purpose="comprovante", operation_id=operation, bucket=BUCKET,
                declared_mime_type="application/pdf", declared_size_bytes=len(content),
                declared_sha256=sha256(content), now=TS, original_filename="p.pdf", requisicao_id=requisicao_id,
                ttl_seconds=7200,
            )
        with write_transaction(setup):
            intents.mark_verified(setup, intent_id=issued.id, actor_user_id=2, observed_size_bytes=len(content),
                                  observed_sha256=sha256(content), now=TS)
        return issued
    finally:
        setup.close()


def _attach(conn, issued, *, fail=False):
    """One S3-A submit transaction: request INSERT + consume + canonical attach."""
    with write_transaction(conn):
        request_id = conn.execute(REQUEST_INSERT).fetchone()[0]
        _intent, object_id = intents.consume_intent(
            conn, intent_id=issued.id, actor_user_id=2, purpose="comprovante",
            operation_id=issued.operation_id, now=TS,
        )
        row = materialize(canonical_request_row(requisicao_id=request_id, operation_key=issued.operation_id,
                                                sha256=issued.declared_sha256,
                                                size_bytes=issued.declared_size_bytes), object_id)
        conn.execute(*insert_sql("requisicao_arquivos", row))
        if fail:
            raise RuntimeError("injected fault after attach")
    return request_id


def _census(url):
    observer = _raw(url, autocommit=True)
    try:
        return tuple(observer.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                     for t in ("requisicoes", "requisicao_arquivos", "storage_objects"))
    finally:
        observer.close()


def test_pg_request_insert_consume_and_attach_are_one_transaction(db):
    issued = _verified_intent(db)
    before = _census(db)
    conn = _adapter(db)
    try:
        with pytest.raises(RuntimeError):
            _attach(conn, issued, fail=True)
        assert _census(db) == before
        observer = _raw(db, autocommit=True)
        try:
            assert observer.execute("SELECT state FROM storage_upload_intents WHERE id=%s",
                                    (issued.id,)).fetchone()[0] == "verified"
        finally:
            observer.close()
        request_id = _attach(conn, issued)
    finally:
        conn.close()
    observer = _raw(db, autocommit=True)
    try:
        assert _census(db) == (before[0] + 1, before[1] + 1, before[2] + 1)
        provider, object_id = observer.execute(
            "SELECT provider,storage_object_id FROM requisicao_arquivos WHERE requisicao_id=%s", (request_id,)
        ).fetchone()
        assert provider == "supabase" and object_id is not None
        assert observer.execute("SELECT drive_sync_state,drive_account_key FROM storage_objects WHERE id=%s",
                                (object_id,)).fetchone() == ("pending", None)
    finally:
        observer.close()


# --- concurrency GREEN controls --------------------------------------------------


def _backend_pid(conn):
    return conn.execute("SELECT pg_backend_pid()").fetchone()[0]


def _wait_until_lock_waiting(url, pid, timeout=20.0):
    observer = _raw(url, autocommit=True)
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            row = observer.execute(
                "SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s", (pid,)
            ).fetchone()
            if row and row[0] == "Lock":
                return
            time.sleep(0.02)
        raise AssertionError("the second session never waited on the row lock")
    finally:
        observer.close()


def _in_thread(function):
    outcome = {}

    def run():
        try:
            outcome["value"] = function()
        except Exception as exc:  # captured for the assertion
            outcome["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, outcome


def test_pg_concurrent_finalizers_serialize_and_the_loser_observes_verified(db):
    setup = _adapter(db)
    try:
        with write_transaction(setup):
            issued = intents.issue_intent(
                setup, actor_user_id=2, purpose="comprovante",
                operation_id=operation_id(SUBMISSION_ID, UPLOAD_SLOTS[1]), bucket=BUCKET,
                declared_mime_type="application/pdf", declared_size_bytes=len(PDF), declared_sha256=sha256(PDF),
                now=TS, ttl_seconds=7200,
            )
    finally:
        setup.close()
    verify = dict(intent_id=issued.id, actor_user_id=2, observed_size_bytes=len(PDF),
                  observed_sha256=sha256(PDF), now=TS)
    winner, loser = _adapter(db), _adapter(db)
    try:
        loser_pid = _backend_pid(loser)
        loser.commit()
        with write_transaction(winner):
            intents.mark_verified(winner, **verify)

            def losing():
                with write_transaction(loser):
                    return intents.mark_verified(loser, **verify)

            thread, outcome = _in_thread(losing)
            _wait_until_lock_waiting(db, loser_pid)
        thread.join(30)
        assert not thread.is_alive()
        # The primitive refuses the second transition; S3-A finalize maps exactly
        # this (state already 'verified', same intent) to an idempotent success.
        assert isinstance(outcome.get("error"), CustodyError)
        assert outcome["error"].code == intents.INTENT_STATE_INVALID
        observer = _raw(db, autocommit=True)
        try:
            assert observer.execute("SELECT state FROM storage_upload_intents WHERE id=%s",
                                    (issued.id,)).fetchone()[0] == "verified"
        finally:
            observer.close()
    finally:
        winner.close()
        loser.close()


def test_pg_concurrent_issuers_of_one_operation_get_one_intent(db):
    issue = dict(actor_user_id=2, purpose="comprovante",
                 operation_id=operation_id(SUBMISSION_ID, UPLOAD_SLOTS[2]), bucket=BUCKET,
                 declared_mime_type="application/pdf", declared_size_bytes=len(PDF), declared_sha256=sha256(PDF),
                 now=TS, ttl_seconds=7200)
    winner, loser = _adapter(db), _adapter(db)
    try:
        loser_pid = _backend_pid(loser)
        loser.commit()
        with write_transaction(winner):
            first = intents.issue_intent(winner, **issue)

            def losing():
                with write_transaction(loser):
                    return intents.issue_intent(loser, **issue)

            thread, outcome = _in_thread(losing)
            _wait_until_lock_waiting(db, loser_pid)
        thread.join(30)
        assert not thread.is_alive() and "error" not in outcome, outcome.get("error")
        assert outcome["value"].id == first.id
        observer = _raw(db, autocommit=True)
        try:
            assert observer.execute("SELECT count(*) FROM storage_upload_intents").fetchone()[0] == 1
        finally:
            observer.close()
    finally:
        winner.close()
        loser.close()
