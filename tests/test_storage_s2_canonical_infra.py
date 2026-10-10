# coding: utf-8
"""STORAGE S2 (prod-1/v14): canonical-storage infrastructure, no runtime switch.

A. SQLite authority: fresh v14, additive v13 -> v14 (rows, counters, digest),
   rollback, reversibility, the shared constraint vector, business FK +
   exclusivity, the intent transition trigger, old custody triggers intact.
B. Domain primitives on SQLite: upload intents (binding, idempotency,
   verification, single consumption, expiry, sweep) and the Drive-mirror
   outbox (claim, fenced completion, retry / pending / reconciliation,
   lease loss and reclaim, worker health) -- time is passed explicitly.
C. Canonical object store: the in-memory fake and the Supabase adapter
   against a mocked HTTP boundary (URLs, headers, parsing, caps, timeouts,
   status mapping, secret sanitization) and lazy configuration.
D. Static guards: PostgreSQL regex bounds, SQLite/PG parity of the v14
   objects, dormancy (no route, no startup import, no Supabase variable).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
import requests

from app import pg_schema
from app.db import write_transaction
from app.prod1_schema import (
    _PROD1_V13_SIGNATURE_SHA256,
    _PROD1_V14_SIGNATURE_SHA256,
    _PROD1_V16_SIGNATURE_SHA256,
    CANONICAL_STORAGE_MARKER,
    PROD1_SCHEMA_SQL,
    SCHEMA_VERSION,
    Prod1SchemaError,
    _physical_schema_digest,
    _validate_prod1_v13_schema,
    bootstrap_prod1_schema,
    migrate_prod1_v13_to_v14,
    validate_prod1_schema,
)
from app.prod1_storage_ddl import STORAGE_V14_TABLES
from app.prod1_storage_v14 import _V14_DETAILS_JSON
from app.storage import mirror_outbox as outbox
from app.storage import upload_intents as intents
from app.storage.custody_common import CustodyError, sanitize_error_code
from app.storage.object_store import CanonicalStoreError, verify_object
from app.storage.supabase_store import SupabaseObjectStore, SupabaseStorageConfig
from tests.canonical_store_fake import InMemoryObjectStore
from tests.prod1_v14_support import revert_prod1_v14_to_v13
from tests.prod1_v15_support import revert_prod1_v15_to_v14
from tests.storage_s2_support import (
    ACCOUNT_KEY,
    BUCKET,
    OTHER_ACCOUNT_KEY,
    INTENT_CASES,
    LATER,
    OBJECT_CASES,
    TS,
    WORKER_CASES,
    insert_sql,
    intent_row,
    object_row,
    worker_row,
)

ROOT = Path(__file__).resolve().parents[1]
SHA_A = hashlib.sha256(b"documento A").hexdigest()


def _head() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    bootstrap_prod1_schema(conn)
    return conn


def _seeded() -> sqlite3.Connection:
    """v14 head with the parents every vector row may reference (ids 1/2)."""
    conn = _head()
    conn.executescript(
        """
        INSERT INTO usuarios(id,nome,email,senha,tipo) VALUES(1,'Admin','a@x.test','x','admin');
        INSERT INTO usuarios(id,nome,email,senha,tipo) VALUES(2,'Aluno','b@x.test','x','aluno');
        INSERT INTO cloud_accounts(id,provider,token_json) VALUES(1,'google','{}');
        INSERT INTO atividade_base(id,nome_conceito) VALUES(1,'Conceito');
        INSERT INTO atividade_versao(id,atividade_base_id,eixo) VALUES(1,1,'AAC');
        INSERT INTO requisicoes(id,atividade_versao_id,data_solicitacao,data_evento,horas_solicitadas,status,
                                regra_snapshot_json) VALUES(1,1,'2026-01-01','2026-01-01',1,'Pendente','{}');
        INSERT INTO requisicao_arquivos(id,requisicao_id,filename) VALUES(1,1,'legacy.pdf');
        INSERT INTO requisicao_arquivos(id,requisicao_id,filename) VALUES(2,1,'legacy2.pdf');
        INSERT INTO admin_arquivos(id,titulo,filename) VALUES(1,'Manual','manual.pdf');
        """
    )
    conn.commit()
    return conn


def _insert(conn, table, row):
    sql, params = insert_sql(table, row)
    return conn.execute(sql + " RETURNING rowid", params).fetchone()[0]


def _dump(conn) -> dict:
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    return {t: conn.execute(f'SELECT * FROM "{t}" ORDER BY rowid').fetchall() for t in tables} | {
        "sqlite_sequence": conn.execute("SELECT name,seq FROM sqlite_sequence ORDER BY name").fetchall()
    }


# --- A. SQLite authority ------------------------------------------------------------


def test_fresh_bootstrap_carries_v14_with_empty_storage_objects():
    """The v15 head (STORAGE S3-A) still carries the v14 storage contract unchanged."""
    conn = _head()
    status = validate_prod1_schema(conn)
    assert SCHEMA_VERSION == status["schema_version"] == 16 and status["table_count"] == 38
    assert _physical_schema_digest(conn) == _PROD1_V16_SIGNATURE_SHA256
    assert conn.execute("SELECT name,details_json FROM schema_migrations WHERE version=14").fetchone() == (
        CANONICAL_STORAGE_MARKER, _V14_DETAILS_JSON
    )
    assert _V14_DETAILS_JSON in PROD1_SCHEMA_SQL
    for table in STORAGE_V14_TABLES:
        assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    for table in ("requisicao_arquivos", "admin_arquivos"):
        columns = {r[1]: r for r in conn.execute(f"PRAGMA table_info({table})")}
        assert columns["storage_object_id"][3] == 0  # nullable
        [fk] = [r for r in conn.execute(f"PRAGMA foreign_key_list({table})") if r[3] == "storage_object_id"]
        assert (fk[2], fk[4], fk[6]) == ("storage_objects", "id", "RESTRICT")


def _v13_with_rows() -> sqlite3.Connection:
    conn = _seeded()
    conn.execute(
        "UPDATE requisicao_arquivos SET provider='google',remote_file_id='r1',remote_parent_id='p1',"
        "original_filename='a.pdf',mime_type='application/pdf',size_bytes=10,sha256=?,uploaded_at=?,"
        "uploader_user_id=1,operation_key='op-1',storage_status='active' WHERE id=1",
        ("c" * 64, TS),
    )
    conn.execute("DELETE FROM requisicao_arquivos WHERE id=2")  # the freed id must never be reused
    conn.commit()
    revert_prod1_v14_to_v13(conn)
    _validate_prod1_v13_schema(conn)
    return conn


def test_v13_to_v14_is_additive_and_matches_the_fresh_head():
    """v14 is now the frozen predecessor: v13 -> v14 equals the head reverted to v14."""
    conn = _v13_with_rows()
    before = _dump(conn)
    status = migrate_prod1_v13_to_v14(conn)
    assert status["schema_version"] == 14 and status["canonical_storage"] == "supabase"
    frozen_v14 = _head()
    revert_prod1_v15_to_v14(frozen_v14)
    assert _physical_schema_digest(conn) == _physical_schema_digest(frozen_v14) == _PROD1_V14_SIGNATURE_SHA256
    after = _dump(conn)
    for table, rows in before.items():
        if table in ("requisicao_arquivos", "admin_arquivos", "cloud_accounts"):
            assert [r[:-1] for r in after[table]] == rows and all(r[-1] is None for r in after[table])
        elif table == "schema_migrations":
            assert after[table][:13] == rows and len(after[table]) == 14
        else:
            assert after[table] == rows, table
    new_id = conn.execute(
        "INSERT INTO requisicao_arquivos(requisicao_id,filename) VALUES(1,'n.pdf') RETURNING id"
    ).fetchone()[0]
    assert new_id == 3


def test_v14_dispatch_is_idempotent_and_refuses_non_v13():
    conn = _v13_with_rows()
    first = bootstrap_prod1_schema(conn)  # migrates v13 -> v14 -> v15 (the v15 report)
    snapshot = _dump(conn)
    assert first["schema_version"] == 16
    assert bootstrap_prod1_schema(conn) == validate_prod1_schema(conn)  # second call: validate only
    assert _dump(conn) == snapshot
    with pytest.raises(Prod1SchemaError, match="prod-1/v13"):
        migrate_prod1_v13_to_v14(conn)


def test_a_failed_v14_migration_leaves_v13_untouched(monkeypatch):
    conn = _v13_with_rows()
    before = _dump(conn)
    import app.prod1_schema as prod1_schema

    def _boom(_conn):
        raise Prod1SchemaError("injected failure after the v14 objects were created")

    # The v14 migration validates against the frozen v14 contract (not the moving head).
    monkeypatch.setattr(prod1_schema, "_validate_prod1_v14_schema", _boom)
    with pytest.raises(Prod1SchemaError, match="injected"):
        migrate_prod1_v13_to_v14(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 13
    assert _physical_schema_digest(conn) == _PROD1_V13_SIGNATURE_SHA256
    assert _dump(conn) == before


def test_v14_is_reversible_to_the_frozen_v13_contract():
    conn = _v13_with_rows()
    before = _dump(conn)
    migrate_prod1_v13_to_v14(conn)
    revert_prod1_v14_to_v13(conn)
    _validate_prod1_v13_schema(conn)
    assert _dump(conn) == before


def _accepted(conn, table, row) -> bool:
    conn.execute("SAVEPOINT probe")
    try:
        _insert(conn, table, row)
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.execute("ROLLBACK TO probe")
        conn.execute("RELEASE probe")


@pytest.mark.parametrize("label,overrides,accepted", OBJECT_CASES, ids=[c[0] for c in OBJECT_CASES])
def test_storage_objects_constraint_vector(label, overrides, accepted):
    assert _accepted(_seeded(), "storage_objects", object_row(**overrides)) is accepted


@pytest.mark.parametrize("label,overrides,accepted", INTENT_CASES, ids=[c[0] for c in INTENT_CASES])
def test_storage_upload_intents_constraint_vector(label, overrides, accepted):
    conn = _seeded()
    _insert(conn, "storage_objects", object_row())
    assert _accepted(conn, "storage_upload_intents", intent_row(**overrides)) is accepted


@pytest.mark.parametrize("label,overrides,accepted", WORKER_CASES, ids=[c[0] for c in WORKER_CASES])
def test_storage_worker_status_constraint_vector(label, overrides, accepted):
    assert _accepted(_seeded(), "storage_worker_status", worker_row(**overrides)) is accepted


def test_bucket_key_unique_and_business_reference_is_exclusive_and_restricting():
    conn = _seeded()
    object_id = _insert(conn, "storage_objects", object_row())
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        _insert(conn, "storage_objects", object_row(sha256="b" * 64))
    conn.execute("UPDATE requisicao_arquivos SET storage_object_id=? WHERE id=1", (object_id,))
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        conn.execute("UPDATE requisicao_arquivos SET storage_object_id=? WHERE id=2", (object_id,))
    with pytest.raises(sqlite3.IntegrityError, match="already owned by another business file"):
        conn.execute("UPDATE admin_arquivos SET storage_object_id=? WHERE id=1", (object_id,))
    with pytest.raises(sqlite3.IntegrityError, match="already owned by another business file"):
        conn.execute("INSERT INTO admin_arquivos(titulo,filename,storage_object_id) VALUES('x','x.pdf',?)",
                     (object_id,))
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        conn.execute("UPDATE admin_arquivos SET storage_object_id=999 WHERE id=1")
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        conn.execute("DELETE FROM storage_objects WHERE id=?", (object_id,))
    # The v4/v5 custody triggers neither reject nor need the new column.
    conn.execute(
        "UPDATE requisicao_arquivos SET provider='google',remote_file_id='r9',remote_parent_id='p9',"
        "original_filename='a.pdf',mime_type='application/pdf',size_bytes=10,sha256=?,uploaded_at=?,"
        "uploader_user_id=1,operation_key='op-9',storage_status='active' WHERE id=1",
        ("c" * 64, TS),
    )
    with pytest.raises(sqlite3.IntegrityError, match="invalid comprovante custody metadata"):
        conn.execute("UPDATE requisicao_arquivos SET size_bytes=NULL WHERE id=1")


def test_intent_trigger_allows_only_forward_transitions_and_freezes_terminal_rows():
    conn = _seeded()
    object_id = _insert(conn, "storage_objects", object_row(storage_key=intent_row()["storage_key"]))
    _insert(conn, "storage_upload_intents", intent_row())
    refused = "invalid storage upload intent transition"
    for statement in (
        "UPDATE storage_upload_intents SET storage_key='comprovantes/x'",
        "UPDATE storage_upload_intents SET actor_user_id=2",
        "UPDATE storage_upload_intents SET operation_id='other'",
        "UPDATE storage_upload_intents SET declared_sha256='" + "d" * 64 + "'",
        "UPDATE storage_upload_intents SET expires_at='2099-01-01 00:00:00'",
        f"UPDATE storage_upload_intents SET state='consumed',verified_at='{TS}',consumed_at='{TS}',"
        f"storage_object_id={object_id}",  # issued -> consumed skips verification
    ):
        with pytest.raises(sqlite3.IntegrityError, match=refused):
            conn.execute(statement)
    conn.execute(f"UPDATE storage_upload_intents SET state='verified',verified_at='{TS}'")
    conn.execute(f"UPDATE storage_upload_intents SET state='consumed',consumed_at='{TS}',"
                 f"storage_object_id={object_id}")
    for statement in (
        "UPDATE storage_upload_intents SET state='expired',consumed_at=NULL,storage_object_id=NULL",
        "UPDATE storage_upload_intents SET consumed_at='2026-01-02 04:00:00'",
    ):
        with pytest.raises(sqlite3.IntegrityError, match=refused):
            conn.execute(statement)
    conn.execute("UPDATE storage_upload_intents SET sweep_after='2026-02-01 00:00:00'")  # audit metadata


# --- B. domain primitives -----------------------------------------------------------


def _issue(conn, **overrides):
    values = dict(
        actor_user_id=2, purpose="comprovante", operation_id="batch-1:0:abcd", bucket=BUCKET,
        declared_mime_type="application/pdf", declared_size_bytes=11, declared_sha256=SHA_A, now=TS,
        original_filename="comprovante.pdf",
    )
    values.update(overrides)
    with write_transaction(conn):
        return intents.issue_intent(conn, **values)


def _code(callable_, *args, **kwargs) -> str:
    with pytest.raises(CustodyError) as caught:
        callable_(*args, **kwargs)
    return caught.value.code


def test_intent_issue_is_server_located_unpredictable_and_idempotent():
    conn = _seeded()
    issued = _issue(conn)
    assert re.fullmatch(r"[0-9a-f]{32}", issued.id)
    assert re.fullmatch(r"comprovantes/2026/01/[0-9a-f]{32}", issued.storage_key)
    assert issued.storage_key.rsplit("/", 1)[1] != issued.id and issued.storage_bucket == BUCKET
    assert (issued.state, issued.expires_at, issued.sweep_after) == (
        "issued", "2026-01-02 03:19:05", "2026-01-03 03:19:05"
    )
    assert _issue(conn) == issued  # same operation + declaration: replay
    other = _issue(conn, operation_id="batch-1:1:abcd")
    assert other.id != issued.id and other.storage_key != issued.storage_key
    with write_transaction(conn):
        assert _code(intents.issue_intent, conn, actor_user_id=2, purpose="comprovante",
                     operation_id="batch-1:0:abcd", bucket=BUCKET, declared_mime_type="application/pdf",
                     declared_size_bytes=12, declared_sha256=SHA_A, now=TS) == intents.INTENT_OPERATION_CONFLICT
    # The browser never chooses a locator: the API has no key parameter.
    import inspect

    assert "storage_key" not in inspect.signature(intents.issue_intent).parameters
    assert "key" not in inspect.signature(intents.issue_intent).parameters
    for bad in (dict(purpose="avatar"), dict(declared_mime_type="image/webp"),
                dict(declared_size_bytes=16 * 1024 * 1024 + 1), dict(declared_sha256=SHA_A.upper()),
                dict(operation_id="has space"), dict(admin_arquivo_id=1), dict(ttl_seconds=3 * 3600)):
        with pytest.raises(ValueError):
            _issue(conn, **{"operation_id": "batch-x", **bad})
    # No secret, URL or token column exists to hold one.
    columns = {r[1] for r in conn.execute("PRAGMA table_info(storage_upload_intents)")}
    assert not {c for c in columns if "token" in c or "url" in c or "secret" in c}


def test_verify_and_consume_create_exactly_one_object_once():
    conn = _seeded()
    issued = _issue(conn)
    with write_transaction(conn):
        assert _code(intents.mark_verified, conn, intent_id=issued.id, actor_user_id=1, observed_size_bytes=11,
                     observed_sha256=SHA_A, now=TS) == intents.INTENT_NOT_FOUND
    with write_transaction(conn):
        assert _code(intents.consume_intent, conn, intent_id=issued.id, actor_user_id=2,
                     purpose="comprovante", operation_id=issued.operation_id, now=TS) == intents.INTENT_STATE_INVALID
    with write_transaction(conn):
        verified = intents.mark_verified(conn, intent_id=issued.id, actor_user_id=2, observed_size_bytes=11,
                                         observed_sha256=SHA_A, now="2026-01-02 03:05:00")
    assert (verified.state, verified.verified_at) == ("verified", "2026-01-02 03:05:00")
    with write_transaction(conn):
        assert _code(intents.consume_intent, conn, intent_id=issued.id, actor_user_id=2,
                     purpose="comprovante", operation_id="other-op", now=TS) == intents.INTENT_BINDING_MISMATCH
    with write_transaction(conn):
        consumed, object_id = intents.consume_intent(conn, intent_id=issued.id, actor_user_id=2,
                                                     purpose="comprovante", operation_id=issued.operation_id,
                                                     now="2026-01-02 03:06:00")
    assert (consumed.state, consumed.storage_object_id, consumed.consumed_at) == (
        "consumed", object_id, "2026-01-02 03:06:00"
    )
    row = conn.execute(
        "SELECT storage_backend,storage_bucket,storage_key,sha256,size_bytes,mime_type,uploader_user_id,origin,"
        "content_verified_at,lifecycle_state,drive_sync_state FROM storage_objects WHERE id=?", (object_id,)
    ).fetchone()
    assert row == ("supabase", BUCKET, issued.storage_key, SHA_A, 11, "application/pdf", 2, "direct_upload",
                   "2026-01-02 03:05:00", "active", "pending")
    with write_transaction(conn):
        assert _code(intents.consume_intent, conn, intent_id=issued.id, actor_user_id=2, purpose="comprovante",
                     operation_id=issued.operation_id, now=TS) == intents.INTENT_STATE_INVALID
    assert conn.execute("SELECT count(*) FROM storage_objects").fetchone()[0] == 1
    # A terminal operation cannot be re-issued.
    with pytest.raises(CustodyError) as caught:
        _issue(conn)
    assert caught.value.code == intents.INTENT_OPERATION_CONFLICT


def test_integrity_mismatch_rejects_and_expiry_is_enforced_and_swept():
    conn = _seeded()
    mismatch = _issue(conn, operation_id="op-mismatch")
    with write_transaction(conn):
        rejected = intents.mark_verified(conn, intent_id=mismatch.id, actor_user_id=2, observed_size_bytes=11,
                                         observed_sha256="0" * 64, now=TS)
    assert (rejected.state, rejected.rejection_code) == ("rejected", "STORAGE_INTEGRITY_MISMATCH")
    late = _issue(conn, operation_id="op-late")
    with write_transaction(conn):
        assert _code(intents.mark_verified, conn, intent_id=late.id, actor_user_id=2, observed_size_bytes=11,
                     observed_sha256=SHA_A, now=late.expires_at) == intents.INTENT_EXPIRED
    live = _issue(conn, operation_id="op-live")
    with write_transaction(conn):
        intents.mark_verified(conn, intent_id=live.id, actor_user_id=2, observed_size_bytes=11,
                              observed_sha256=SHA_A, now=TS)
    with write_transaction(conn):
        assert _code(intents.consume_intent, conn, intent_id=live.id, actor_user_id=2, purpose="comprovante",
                     operation_id="op-live", now=live.expires_at) == intents.INTENT_EXPIRED
    assert intents.count_nonterminal_intents(conn) == 2
    with write_transaction(conn):
        assert intents.expire_intents(conn, now=late.expires_at) == 2
    assert intents.count_nonterminal_intents(conn) == 0
    with write_transaction(conn):
        rejected_again = intents.reject_intent
        assert _code(rejected_again, conn, intent_id=late.id, rejection_code="X", now=TS) == \
            intents.INTENT_STATE_INVALID
    with write_transaction(conn):
        assert intents.sweep_intents(conn, now="2026-01-03 03:19:04") == 0
        assert intents.sweep_intents(conn, now="2026-01-03 03:19:05") == 3
    assert conn.execute("SELECT count(*) FROM storage_upload_intents").fetchone()[0] == 0


def test_reject_sanitizes_its_code_and_writers_need_a_transaction():
    conn = _seeded()
    issued = _issue(conn)
    with write_transaction(conn):
        result = intents.reject_intent(conn, intent_id=issued.id, rejection_code="Traceback: C:\\x a@b", now=TS)
    assert result.rejection_code == "UNCLASSIFIED_ERROR"
    assert sanitize_error_code("DRIVE_QUOTA") == "DRIVE_QUOTA"
    for bad in ("drive quota", "X" * 65, "", None, "token=abc", "DRIVE_QUOTA\n"):
        assert sanitize_error_code(bad) == "UNCLASSIFIED_ERROR"
    assert _code(intents.expire_intents, conn, now=TS) == "WRITE_TRANSACTION_REQUIRED"
    assert _code(outbox.claim_due_mirror_work, conn, limit=1, worker_token="a" * 32, now=TS) == \
        "WRITE_TRANSACTION_REQUIRED"


def _objects(conn, count, **overrides):
    ids = []
    for index in range(count):
        ids.append(_insert(conn, "storage_objects",
                           object_row(storage_key=f"comprovantes/2026/01/{index:032x}", **overrides)))
    conn.commit()
    return ids


def _claim(conn, token, now, limit=10, lease_seconds=300):
    with write_transaction(conn):
        return outbox.claim_due_mirror_work(conn, limit=limit, worker_token=token, now=now,
                                            lease_seconds=lease_seconds)


def test_outbox_claim_is_bounded_and_never_double_claims_a_live_lease():
    conn = _seeded()
    ids = _objects(conn, 3)
    _objects_retired = _insert(conn, "storage_objects", object_row(
        storage_key="comprovantes/2026/01/retired", lifecycle_state="retired", retired_at=TS))
    conn.commit()
    first = _claim(conn, "a" * 32, TS, limit=2)
    assert [w.object_id for w in first] == ids[:2]
    assert all((w.generation, w.lease_token, w.lease_expires_at) == (1, "a" * 32, "2026-01-02 03:09:05")
               for w in first)
    second = _claim(conn, "b" * 32, TS)
    assert [w.object_id for w in second] == [ids[2]]  # never the leased ones, never the retired one
    assert _claim(conn, "c" * 32, "2026-01-02 03:09:04") == []
    assert conn.execute("SELECT drive_sync_state FROM storage_objects WHERE id=?",
                        (_objects_retired,)).fetchone()[0] == "pending"
    with pytest.raises(ValueError):
        _claim(conn, "a" * 32, TS, limit=outbox.MAX_CLAIM_BATCH + 1)
    with pytest.raises(ValueError):
        _claim(conn, "not-a-token", TS)


def test_completion_is_fenced_by_token_generation_state_and_live_lease():
    conn = _seeded()
    [object_id] = _objects(conn, 1)
    [work] = _claim(conn, "a" * 32, TS)
    synced = dict(object_id=object_id, drive_file_id="drv-1", drive_parent_id="parent-1", drive_account_key=ACCOUNT_KEY)
    with write_transaction(conn):
        assert _code(outbox.complete_synced, conn, lease_token="b" * 32, generation=work.generation,
                     now=TS, **synced) == outbox.MIRROR_LEASE_LOST
    with write_transaction(conn):
        assert _code(outbox.complete_synced, conn, lease_token=work.lease_token, generation=work.generation + 1,
                     now=TS, **synced) == outbox.MIRROR_LEASE_LOST
    with write_transaction(conn):
        assert _code(outbox.complete_synced, conn, lease_token=work.lease_token, generation=work.generation,
                     now=work.lease_expires_at, **synced) == outbox.MIRROR_LEASE_LOST
    # Expired: another worker reclaims (generation 2); the first can never write.
    [again] = _claim(conn, "d" * 32, work.lease_expires_at)
    assert (again.object_id, again.generation) == (object_id, 2)
    with write_transaction(conn):
        assert _code(outbox.complete_synced, conn, lease_token=work.lease_token, generation=work.generation,
                     now=TS, **synced) == outbox.MIRROR_LEASE_LOST
    with write_transaction(conn):
        outbox.complete_synced(conn, lease_token=again.lease_token, generation=again.generation,
                               now="2026-01-02 03:10:00", **synced)
    row = conn.execute(
        "SELECT drive_sync_state,drive_file_id,drive_account_key,drive_synced_at,lease_token,lease_expires_at,"
        "drive_attempts FROM storage_objects WHERE id=?", (object_id,)).fetchone()
    assert row == ("synced", "drv-1", ACCOUNT_KEY, "2026-01-02 03:10:00", None, None, 2)
    assert _claim(conn, "e" * 32, "2030-01-01 00:00:00") == []  # synced is not due


def test_bound_drive_account_is_never_substituted_and_has_no_credential_fk():
    conn = _seeded()
    fresh_id, bound_id = _objects(conn, 2)
    conn.execute("UPDATE storage_objects SET drive_sync_state='retry', drive_last_error_code='DRIVE_QUOTA', "
                 "drive_next_attempt_at=?, drive_account_key=? WHERE id=?", (TS, ACCOUNT_KEY, bound_id))
    conn.commit()
    works = {w.object_id: w for w in _claim(conn, "a" * 32, TS)}
    assert (works[fresh_id].drive_account_key, works[bound_id].drive_account_key) == (None, ACCOUNT_KEY)
    base = dict(drive_file_id="drv-9", drive_parent_id=None, now=TS, lease_token="a" * 32)
    with write_transaction(conn):
        assert _code(outbox.complete_synced, conn, object_id=bound_id, generation=works[bound_id].generation,
                     drive_account_key=OTHER_ACCOUNT_KEY, **base) == outbox.DRIVE_ACCOUNT_MISMATCH
    with write_transaction(conn):
        outbox.complete_synced(conn, object_id=bound_id, generation=works[bound_id].generation,
                               drive_account_key=ACCOUNT_KEY, **base)
        outbox.complete_synced(conn, object_id=fresh_id, generation=works[fresh_id].generation,
                               drive_account_key=OTHER_ACCOUNT_KEY, **{**base, "drive_file_id": "drv-8"})
    assert dict(conn.execute("SELECT id, drive_account_key FROM storage_objects")) == {
        fresh_id: OTHER_ACCOUNT_KEY, bound_id: ACCOUNT_KEY}
    for value in (OTHER_ACCOUNT_KEY, None):
        with pytest.raises(sqlite3.IntegrityError, match="Drive account is already bound"):
            conn.execute("UPDATE storage_objects SET drive_account_key=? WHERE id=?", (value, bound_id))
    conn.rollback()
    with pytest.raises(ValueError):
        with write_transaction(conn):
            outbox.complete_synced(conn, object_id=fresh_id, generation=1, drive_account_key="1", **base)
    # Logical identity only: no foreign key reaches a credential row.
    assert not [r for r in conn.execute("PRAGMA foreign_key_list(storage_objects)") if r[2] == "cloud_accounts"]
    assert not [fk for fk in pg_schema.PG_TABLE_SPECS["storage_objects"]["foreign_keys"]
                if fk["references_table"] == "cloud_accounts"]
    # Deleting every credential row leaves the mirror identity intact.
    conn.execute("DELETE FROM cloud_accounts")
    assert conn.execute("SELECT count(*) FROM storage_objects WHERE drive_account_key IS NOT NULL").fetchone()[0] == 2


def test_retry_pending_reconciliation_and_lease_release():
    conn = _seeded()
    retry_id, pending_id, reconcile_id, expired_id = _objects(conn, 4)
    works = {w.object_id: w for w in _claim(conn, "a" * 32, TS)}
    with write_transaction(conn):
        outbox.mark_retry(conn, object_id=retry_id, lease_token="a" * 32, generation=works[retry_id].generation,
                          error_code="DRIVE_QUOTA", next_attempt_at="2026-01-02 04:00:00", now=TS)
        outbox.mark_pending_disconnected(conn, object_id=pending_id, lease_token="a" * 32,
                                         generation=works[pending_id].generation,
                                         next_attempt_at="2026-01-02 05:00:00", now=TS)
        outbox.mark_reconciliation_required(conn, object_id=reconcile_id, lease_token="a" * 32,
                                            generation=works[reconcile_id].generation,
                                            error_code="drive said: 409 at C:\\x", now=TS)
    states = dict(conn.execute(
        "SELECT id, drive_sync_state || ':' || COALESCE(drive_last_error_code,'') FROM storage_objects"))
    assert states[retry_id] == "retry:DRIVE_QUOTA"
    assert states[pending_id] == "pending:DRIVE_NOT_CONNECTED"
    assert states[reconcile_id] == "reconciliation_required:UNCLASSIFIED_ERROR"
    with write_transaction(conn):
        assert outbox.release_expired_leases(conn, now="2026-01-02 03:09:04", limit=10) == 0
        assert outbox.release_expired_leases(conn, now="2026-01-02 03:09:05", limit=10) == 1
    assert conn.execute("SELECT drive_sync_state,drive_last_error_code,lease_token FROM storage_objects WHERE id=?",
                        (expired_id,)).fetchone() == ("retry", "LEASE_EXPIRED", None)
    due = lambda now: sorted(w.object_id for w in _claim(conn, "f" * 32, now))  # noqa: E731
    assert due("2026-01-02 03:59:59") == [expired_id]
    # 05:00: retry and pending are due again, the 03:59:59 lease has also
    # expired (reclaimed), and reconciliation_required is never auto-claimed.
    assert due("2026-01-02 05:00:00") == [retry_id, pending_id, expired_id]
    assert conn.execute("SELECT drive_sync_state FROM storage_objects WHERE id=?",
                        (reconcile_id,)).fetchone()[0] == "reconciliation_required"


def test_retire_and_worker_health_are_state_only():
    conn = _seeded()
    [object_id] = _objects(conn, 1)
    with write_transaction(conn):
        outbox.retire_object(conn, object_id=object_id, now=LATER)
    assert conn.execute("SELECT lifecycle_state,retired_at,purge_after FROM storage_objects").fetchone() == (
        "retired", LATER, None
    )
    with write_transaction(conn):
        assert _code(outbox.retire_object, conn, object_id=object_id, now=LATER) == "STORAGE_OBJECT_NOT_ACTIVE"
    assert outbox.read_worker_status(conn) is None
    with write_transaction(conn):
        assert _code(outbox.record_worker_finished, conn, now=TS, result_code="OK", claimed=0, synced=0,
                     retried=0) == "WORKER_NOT_STARTED"
    with write_transaction(conn):
        outbox.record_worker_started(conn, now=TS)
        outbox.record_worker_finished(conn, now=LATER, result_code="boom: C:\\secret", claimed=3, synced=2,
                                      retried=1)
    assert outbox.read_worker_status(conn) == {
        "last_started_at": TS, "last_finished_at": LATER, "last_result_code": "UNCLASSIFIED_ERROR",
        "last_claimed_count": 3, "last_synced_count": 2, "last_retry_count": 1,
    }
    with write_transaction(conn):
        outbox.record_worker_started(conn, now="2026-01-02 05:00:00")
    assert outbox.read_worker_status(conn)["last_finished_at"] is None
    assert conn.execute("SELECT count(*) FROM storage_worker_status").fetchone()[0] == 1
    # No purge exists anywhere in the outbox API.
    assert not [name for name in dir(outbox) if "purge" in name.lower() or "delete" in name.lower()]


# --- C. canonical object store ------------------------------------------------------


def test_fake_store_signed_upload_flow_is_immutable_and_verifiable():
    store = InMemoryObjectStore()
    key = "comprovantes/2026/01/" + "a" * 32
    signed = store.create_signed_upload(BUCKET, key)
    assert signed.token not in repr(signed) and signed.url not in repr(signed)
    store.complete_signed_upload(signed.token, b"documento A", mime_type="application/pdf")
    with pytest.raises(CanonicalStoreError) as caught:
        store.complete_signed_upload(signed.token, b"other", mime_type="application/pdf")
    # S3-A: like the service, the capability stays valid until it expires, but a
    # reuse can never overwrite the taken key (upsert is false) ...
    assert caught.value.code == "STORAGE_ALREADY_EXISTS"
    store.expire_signed_uploads()
    with pytest.raises(CanonicalStoreError) as caught:
        store.complete_signed_upload(signed.token, b"other", mime_type="application/pdf")
    assert caught.value.code == "STORAGE_INVALID_LOCATOR"  # ... and an expired one is refused
    assert store.read(BUCKET, key, max_bytes=16) == b"documento A"
    for action in (lambda: store.create_signed_upload(BUCKET, key),
                   lambda: store.upload(BUCKET, key, b"other", mime_type="application/pdf")):
        with pytest.raises(CanonicalStoreError) as caught:
            action()
        assert caught.value.code == "STORAGE_ALREADY_EXISTS"
    verified = verify_object(store, BUCKET, key, expected_size=11, expected_sha256=SHA_A, max_bytes=16)
    assert (verified.size_bytes, verified.sha256, verified.mime_type) == (11, SHA_A, "application/pdf")
    for size, digest, code in ((11, "0" * 64, "STORAGE_INTEGRITY_MISMATCH"), (12, SHA_A, "STORAGE_INTEGRITY_MISMATCH"),
                               (11, SHA_A, None)):
        if code:
            with pytest.raises(CanonicalStoreError) as caught:
                verify_object(store, BUCKET, key, expected_size=size, expected_sha256=digest, max_bytes=16)
            assert caught.value.code == code
    with pytest.raises(CanonicalStoreError) as caught:
        store.read(BUCKET, key, max_bytes=10)
    assert caught.value.code == "STORAGE_OBJECT_TOO_LARGE"
    assert store.create_signed_download(BUCKET, key, expires_in=60).url
    store.fail_next("STORAGE_PROVIDER_UNAVAILABLE")
    with pytest.raises(CanonicalStoreError) as caught:
        store.stat(BUCKET, key)
    assert caught.value.code == "STORAGE_PROVIDER_UNAVAILABLE" and caught.value.retryable
    store.delete(BUCKET, key)
    assert not store.object_exists(BUCKET, key)
    for action in (lambda: store.delete(BUCKET, key), lambda: store.stat(BUCKET, key),
                   lambda: store.read(BUCKET, key, max_bytes=16)):
        with pytest.raises(CanonicalStoreError) as caught:
            action()
        assert caught.value.code == "STORAGE_OBJECT_MISSING"
    with pytest.raises(CanonicalStoreError) as caught:
        store.create_signed_upload(BUCKET, "../escape")
    assert caught.value.code == "STORAGE_INVALID_LOCATOR"


SECRET = "sb_secret_TESTONLY_never_printed_123"
URL = "https://abcdefgh.supabase.co"
KEY = "comprovantes/2026/01/" + "a" * 32


class _Response:
    def __init__(self, status=200, body=None, headers=None, chunks=None, text=None):
        self.status_code = status
        self._body = body
        self._text = text
        self.headers = headers or {}
        self._chunks = chunks or []
        self.closed = False

    def json(self):
        if self._text is not None:
            return json.loads(self._text)
        if self._body is None:
            raise ValueError("no json")
        return self._body

    def iter_content(self, chunk_size):
        yield from self._chunks

    def close(self):
        self.closed = True


class _Session:
    def __init__(self, *responses, error=None):
        self.responses = list(responses)
        self.error = error
        self.requests = []

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        if self.error is not None:
            raise self.error
        return self.responses.pop(0)


def _store(*responses, error=None):
    session = _Session(*responses, error=error)
    config = SupabaseStorageConfig(url=URL, bucket=BUCKET, secret_key=SECRET)
    return SupabaseObjectStore(config, session=session), session


def _store_error(store_call) -> CanonicalStoreError:
    with pytest.raises(CanonicalStoreError) as caught:
        store_call()
    text = str(caught.value) + repr(caught.value)
    assert SECRET not in text and "token=" not in text and "provider-body" not in text
    return caught.value


def test_adapter_signed_upload_url_headers_and_parsing():
    signed_path = f"/object/upload/sign/{BUCKET}/{KEY}?token=tok123"
    store, session = _store(_Response(200, {"url": signed_path, "token": "tok123"}))
    signed = store.create_signed_upload(BUCKET, KEY)
    method, url, kwargs = session.requests[0]
    assert (method, url) == ("POST", f"{URL}/storage/v1/object/upload/sign/{BUCKET}/{KEY}")
    # S3-A: an sb_secret_ key is a backend API key -- never a Bearer token.
    assert kwargs["headers"] == {"apikey": SECRET, "x-upsert": "false"}
    assert kwargs["timeout"] == (5.0, 30.0) and kwargs["allow_redirects"] is False
    assert (signed.url, signed.token) == (f"{URL}/storage/v1{signed_path}", "tok123")
    assert "tok123" not in repr(signed) and SECRET not in repr(store)
    for body in ({"url": "https://evil.example/object/upload/sign/x?token=t"},
                 {"url": f"/object/upload/sign/{BUCKET}/other?token=t"},
                 {"url": f"/object/upload/sign/{BUCKET}/{KEY}"},
                 {"url": signed_path, "token": "different"}, {}, []):
        store, _session = _store(_Response(200, body))
        assert _store_error(lambda: store.create_signed_upload(BUCKET, KEY)).code == "STORAGE_INVALID_RESPONSE"
    store, _session = _store(_Response(200, text="not json provider-body"))
    assert _store_error(lambda: store.create_signed_upload(BUCKET, KEY)).code == "STORAGE_INVALID_RESPONSE"


def test_adapter_signed_download_stat_read_upload_delete():
    store, session = _store(_Response(200, {"signedURL": f"/object/sign/{BUCKET}/{KEY}?token=dl"}))
    signed = store.create_signed_download(BUCKET, KEY, expires_in=60, download_name="Comprovante 1.pdf")
    assert session.requests[0][2]["json"] == {"expiresIn": 60}
    assert signed.url == f"{URL}/storage/v1/object/sign/{BUCKET}/{KEY}?token=dl&download=Comprovante%201.pdf"
    with pytest.raises(ValueError):
        store.create_signed_download(BUCKET, KEY, expires_in=3601)

    store, session = _store(_Response(200, headers={"Content-Length": "11", "Content-Type": "application/pdf; x=1"}))
    stat = store.stat(BUCKET, KEY)
    assert (session.requests[0][0], session.requests[0][1]) == (
        "HEAD", f"{URL}/storage/v1/object/authenticated/{BUCKET}/{KEY}")
    assert (stat.size_bytes, stat.mime_type) == (11, "application/pdf")
    for response in (_Response(400), _Response(404)):
        store, _session = _store(response)
        assert store.object_exists(BUCKET, KEY) is False
    store, _session = _store(_Response(200, headers={}))
    assert _store_error(lambda: store.stat(BUCKET, KEY)).code == "STORAGE_INVALID_RESPONSE"

    store, session = _store(_Response(200, headers={"Content-Length": "11"}, chunks=[b"documento", b" A"]))
    assert store.read(BUCKET, KEY, max_bytes=11) == b"documento A"
    assert session.requests[0][2]["stream"] is True
    store, _session = _store(_Response(200, headers={"Content-Length": "999"}))
    assert _store_error(lambda: store.read(BUCKET, KEY, max_bytes=11)).code == "STORAGE_OBJECT_TOO_LARGE"
    lying = _Response(200, headers={}, chunks=[b"x" * 8, b"x" * 8])
    store, _session = _store(lying)
    assert _store_error(lambda: store.read(BUCKET, KEY, max_bytes=11)).code == "STORAGE_OBJECT_TOO_LARGE"
    assert lying.closed

    store, session = _store(_Response(200, {"Key": f"{BUCKET}/{KEY}", "Id": "x"}))
    assert store.upload(BUCKET, KEY, b"abc", mime_type="application/pdf").size_bytes == 3
    method, url, kwargs = session.requests[0]
    assert (method, url, kwargs["headers"]["x-upsert"], kwargs["data"]) == (
        "POST", f"{URL}/storage/v1/object/{BUCKET}/{KEY}", "false", b"abc")
    for response in (_Response(409), _Response(400, {"statusCode": "409", "error": "Duplicate"})):
        store, _session = _store(response)
        assert _store_error(lambda: store.upload(BUCKET, KEY, b"abc", mime_type="application/pdf")).code == \
            "STORAGE_ALREADY_EXISTS"

    store, session = _store(_Response(200, [{"name": KEY}]))
    store.delete(BUCKET, KEY)
    assert session.requests[0][:2] == ("DELETE", f"{URL}/storage/v1/object/{BUCKET}/{KEY}")
    store, _session = _store(_Response(400, {"statusCode": "404", "message": "provider-body"}))
    assert _store_error(lambda: store.delete(BUCKET, KEY)).code == "STORAGE_OBJECT_MISSING"


@pytest.mark.parametrize("response,code", [
    (_Response(401, {"message": "provider-body"}), "STORAGE_AUTH_FAILURE"),
    (_Response(400, {"statusCode": "403", "message": "provider-body"}), "STORAGE_AUTH_FAILURE"),
    (_Response(413), "STORAGE_OBJECT_TOO_LARGE"),
    (_Response(429), "STORAGE_PROVIDER_UNAVAILABLE"),
    (_Response(503, text="provider-body"), "STORAGE_PROVIDER_UNAVAILABLE"),
    (_Response(302, headers={"Location": "https://elsewhere.example"}), "STORAGE_INVALID_RESPONSE"),
    (_Response(422, {"message": "provider-body"}), "STORAGE_INVALID_RESPONSE"),
])
def test_adapter_status_mapping_is_sanitized(response, code):
    store, _session = _store(response)
    error = _store_error(lambda: store.create_signed_download(BUCKET, KEY, expires_in=60))
    assert error.code == code and error.retryable is (code == "STORAGE_PROVIDER_UNAVAILABLE")


@pytest.mark.parametrize("exc", [requests.Timeout("t " + SECRET), requests.ConnectionError("c " + SECRET)])
def test_adapter_transport_failures_are_unavailable_and_never_echo(exc):
    store, _session = _store(error=exc)
    error = _store_error(lambda: store.stat(BUCKET, KEY))
    assert error.code == "STORAGE_PROVIDER_UNAVAILABLE" and error.__cause__ is None


def test_adapter_refuses_bad_locators_before_any_request():
    store, session = _store()
    for bucket, key in ((BUCKET, "../x"), (BUCKET, "/abs"), (BUCKET, "a b"), ("Bucket", KEY), (BUCKET, "k" * 257),
                        (BUCKET, KEY + "\n"), (BUCKET + "\n", KEY)):
        assert _store_error(lambda: store.stat(bucket, key)).code == "STORAGE_INVALID_LOCATOR"
    assert session.requests == []


def test_configuration_is_lazy_named_and_secret_free():
    with pytest.raises(CanonicalStoreError) as caught:
        SupabaseStorageConfig.from_environment({})
    assert caught.value.code == "STORAGE_CONFIG_MISSING"
    assert caught.value.detail == "SUPABASE_URL,SUPABASE_SECRET_KEY,SGAA_STORAGE_BUCKET"
    good = {"SUPABASE_URL": URL + "/", "SUPABASE_SECRET_KEY": SECRET, "SGAA_STORAGE_BUCKET": BUCKET}
    config = SupabaseStorageConfig.from_environment(good)
    assert (config.url, config.bucket) == (URL, BUCKET) and SECRET not in repr(config)
    assert SupabaseStorageConfig.from_environment({**good, "SUPABASE_URL": "http://127.0.0.1:54321"}).url
    for bad_url in ("http://abcdefgh.supabase.co", "https://user:pw@x.supabase.co", "https://x.supabase.co/rest",
                    "https://x.supabase.co?a=1", "ftp://x"):
        with pytest.raises(CanonicalStoreError) as caught:
            SupabaseStorageConfig.from_environment({**good, "SUPABASE_URL": bad_url})
        assert caught.value.detail == "SUPABASE_URL" and "pw" not in str(caught.value)
    with pytest.raises(CanonicalStoreError) as caught:
        SupabaseStorageConfig.from_environment({**good, "SGAA_STORAGE_BUCKET": "Public Bucket"})
    assert caught.value.detail == "SGAA_STORAGE_BUCKET"


# --- D. static guards ---------------------------------------------------------------


def test_pg_regex_bounds_stay_within_the_are_limit():
    """PostgreSQL AREs reject a {m,n} bound above 255 -- only when a row is checked."""
    expressions = [check["expression"] for spec in pg_schema.PG_TABLE_SPECS.values() for check in spec["checks"]]
    from app.pg_migrate_from_sqlite import DOMAIN_CHECKS

    expressions += list(DOMAIN_CHECKS.values())
    bounds = [int(n) for text in expressions for pair in re.findall(r"\{(\d+)(?:,(\d+))?\}", text) for n in pair if n]
    assert bounds and max(bounds) <= 255


def test_v14_objects_have_the_same_shape_on_both_engines():
    conn = _head()
    for table in STORAGE_V14_TABLES + ("requisicao_arquivos", "admin_arquivos"):
        sqlite_columns = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
        assert sqlite_columns == [c["name"] for c in pg_schema.PG_TABLE_SPECS[table]["columns"]], table
    v14_indexes = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL AND "
        "(tbl_name LIKE 'storage_%' OR name LIKE '%storage_object')")}
    assert v14_indexes == {n for n, s in pg_schema.PG_EXPLICIT_INDEXES.items()
                           if s["table"].startswith("storage_") or n.endswith("storage_object")}
    sqlite_triggers = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    assert sqlite_triggers == {t["name"] for t in pg_schema.PG_TRIGGERS}
    for table in STORAGE_V14_TABLES:
        assert {c["name"] for c in pg_schema.PG_TABLE_SPECS[table]["checks"]}  # every table is constrained


def test_s3a_activates_only_request_documents_and_needs_no_startup_configuration():
    """S2 shipped the primitives dormant; S3-A wires them into the REQUEST documents only.

    ARQUIVOS stays on Google Drive (S3-B), no mirror worker runs (S4), and the
    application still starts without any Supabase configuration -- the store is
    built lazily on first use, never at startup.
    """
    for path in (ROOT / "app" / "views" / "admin" / "arquivos.py", ROOT / "app" / "arquivos.py",
                 ROOT / "app" / "admin_files.py", ROOT / "templates" / "admin_arquivos.html"):
        text = path.read_text(encoding="utf-8", errors="replace")
        for marker in ("upload_intents", "mirror_outbox", "supabase_store", "object_store",
                       "request_documents", "canonical_object_store", "storage_objects"):
            assert marker not in text, (path.name, marker)
    for path in list((ROOT / "app" / "views").rglob("*.py")) + [ROOT / "app" / "__init__.py", ROOT / "main.py"]:
        text = path.read_text(encoding="utf-8", errors="replace")
        assert "claim_due_mirror_work" not in text and "complete_synced" not in text, path.name
    env = {k: v for k, v in os.environ.items()
           if k not in ("SUPABASE_URL", "SUPABASE_SECRET_KEY", "SGAA_STORAGE_BUCKET")}
    probe = (
        "import main, app.storage.supabase_store as s; "
        "assert main.app is not None; "
        "assert main.app.extensions.get('canonical_object_store') is None; "
        "assert 'supabase' not in main.app.config['CONTENT_SECURITY_POLICY']; "
        "print('STARTED')"
    )
    completed = subprocess.run([sys.executable, "-c", probe], cwd=ROOT, env=env, capture_output=True,
                               text=True, timeout=120)
    assert completed.returncode == 0, completed.stderr[-2000:]
    assert completed.stdout.strip().endswith("STARTED")
