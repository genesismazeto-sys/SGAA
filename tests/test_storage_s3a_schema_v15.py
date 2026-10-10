# coding: utf-8
"""STORAGE S3-A RED: prod-1/v15 canonical business-row custody (SQLite authority).

S3-A attaches NEW comprovantes to canonical storage objects.  The published
v14 custody triggers only know ``provider IN ('local_legacy','google')``, so a
canonical row is illegal today (and a canonical ARQUIVOS row has no legal
encoding at all).  v15 must add ``provider = 'supabase'`` to BOTH business
tables without disturbing any legacy verdict:

    * ``supabase`` => ``storage_object_id`` NOT NULL, no Google locator, no
      Drive delete bookkeeping, full custody metadata, and only the canonical
      statuses (``active``; request removal keeps ``trashed`` evidence);
    * pending / uploaded / failed upload state belongs to
      ``storage_upload_intents``, never to a half-created business row;
    * ``storage_object_id`` NOT NULL does NOT imply ``supabase``: legacy rows
      carrying a canonical reference stay legal exactly as S2 / Path-B /
      Layer-2 published them (S3 writes ``supabase`` as an APPLICATION rule);
    * ARQUIVOS legacy residue reuses the existing ``prior_provider`` /
      ``prior_locator`` pair on an ``active`` canonical row, meaning "legacy
      residue preserved for S5" -- never cleanup pending: no
      ``cleanup_started_at``, never ``replacement_cleanup_pending``, which keeps
      its Google / legacy meaning (schema only -- S3-A does not switch ARQUIVOS).

Path-B / Layer-2: a canonical source migrates without any Google credential
prerequisite; the S2 table policies stay exactly as published.

RED: every ``provider='supabase'`` acceptance vector, the version gate and the
Path-B / Layer-2 v15 nodes fail today; the legacy vectors and policy nodes are
GREEN controls that must stay green.
"""

from __future__ import annotations

import hashlib
import sqlite3

import pytest

from app import pg_schema
from app import prod1_schema
from app.prod1_schema import bootstrap_prod1_schema
from tests.storage_s3a_support import (
    ADMIN_ROW_CASES,
    NEW_OBJECT,
    REQUEST_ROW_CASES,
    canonical_request_row,
    insert_sql,
    materialize,
    object_row_for,
)

SEED_SQL = """
INSERT INTO usuarios(id,nome,email,senha,tipo) VALUES(1,'Admin','s3a@x.test','x','admin');
INSERT INTO usuarios(id,nome,email,senha,tipo) VALUES(2,'Aluno','s3b@x.test','x','aluno');
INSERT INTO atividade_base(id,nome_conceito) VALUES(1,'Conceito');
INSERT INTO atividade_versao(id,atividade_base_id,eixo) VALUES(1,1,'AAC');
INSERT INTO requisicoes(id,atividade_versao_id,data_solicitacao,data_evento,horas_solicitadas,status,
                        regra_snapshot_json) VALUES(1,1,'2026-01-01','2026-01-01',1,'Pendente','{}');
"""


def _seeded(path=":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys=ON")
    bootstrap_prod1_schema(conn)
    conn.executescript(SEED_SQL)
    conn.commit()
    return conn


def _verdict(conn, table, row, index) -> tuple[bool, str | None]:
    """Insert ``row`` (with a fresh storage object when asked) inside a savepoint."""
    conn.execute("SAVEPOINT probe")
    try:
        object_id = None
        if any(value is NEW_OBJECT for value in row.values()):
            sql, params = insert_sql("storage_objects", object_row_for(f"{table[:3]}{index:029d}"))
            object_id = conn.execute(sql + " RETURNING id", params).fetchone()[0]
        sql, params = insert_sql(table, materialize(row, object_id))
        conn.execute(sql, params)
        return True, None
    except sqlite3.IntegrityError as exc:
        return False, str(exc)
    finally:
        conn.execute("ROLLBACK TO SAVEPOINT probe")
        conn.execute("RELEASE SAVEPOINT probe")


# --- version gate ------------------------------------------------------------------


def test_v15_keeps_its_v14_migration_and_the_authorities_move_together_to_v16():
    """MP-2 moved the head to v16 on both authorities; v15 and its migration stay published."""
    assert prod1_schema.SCHEMA_VERSION == pg_schema.PG_SCHEMA_VERSION == 16
    migrate = getattr(prod1_schema, "migrate_prod1_v14_to_v15", None)
    assert callable(migrate), "v15 needs an additive v14 -> v15 migration"


# --- business-row constraint vectors -----------------------------------------------


@pytest.mark.parametrize(
    ("label", "row", "accepted"), REQUEST_ROW_CASES, ids=[c[0] for c in REQUEST_ROW_CASES]
)
def test_requisicao_arquivos_v15_custody_vector(label, row, accepted):
    conn = _seeded()
    try:
        index = [c[0] for c in REQUEST_ROW_CASES].index(label)
        ok, error = _verdict(conn, "requisicao_arquivos", row, index)
        assert ok is accepted, (label, error)
    finally:
        conn.close()


@pytest.mark.parametrize(
    ("label", "row", "accepted"), ADMIN_ROW_CASES, ids=[c[0] for c in ADMIN_ROW_CASES]
)
def test_admin_arquivos_v15_schema_only_custody_vector(label, row, accepted):
    """Representability only: S3-A switches NO ARQUIVOS route."""
    conn = _seeded()
    try:
        index = [c[0] for c in ADMIN_ROW_CASES].index(label)
        ok, error = _verdict(conn, "admin_arquivos", row, index)
        assert ok is accepted, (label, error)
    finally:
        conn.close()


def test_canonical_row_needs_no_drive_account_credential_or_mirror_binding():
    """Legal with ``cloud_accounts`` empty and the object still mirror-pending."""
    conn = _seeded()
    try:
        assert conn.execute("SELECT count(*) FROM cloud_accounts").fetchone()[0] == 0
        sql, params = insert_sql("storage_objects", object_row_for("c" * 32))
        object_id = conn.execute(sql + " RETURNING id", params).fetchone()[0]
        sql, params = insert_sql("requisicao_arquivos", materialize(canonical_request_row(), object_id))
        conn.execute(sql, params)
        mirror = conn.execute(
            "SELECT lifecycle_state,drive_sync_state,drive_account_key,drive_file_id FROM storage_objects"
        ).fetchone()
        assert mirror == ("active", "pending", None, None)
    finally:
        conn.close()


def test_one_canonical_object_still_has_one_business_owner():
    """The v14 one-owner index, re-asserted for CANONICAL rows (needs v15 to insert one)."""
    conn = _seeded()
    try:
        sql, params = insert_sql("storage_objects", object_row_for("d" * 32))
        object_id = conn.execute(sql + " RETURNING id", params).fetchone()[0]
        first = materialize(canonical_request_row(), object_id)
        conn.execute(*insert_sql("requisicao_arquivos", first))
        second = dict(first, operation_key="other-op:1:cccccccccccccccc")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(*insert_sql("requisicao_arquivos", second))
    finally:
        conn.close()


# --- Path-B / Layer-2 --------------------------------------------------------------


def test_published_s2_table_policies_are_unchanged_by_v15():
    """GREEN control: v15 adds no new migration or backup policy."""
    from app.pg_migrate_from_sqlite import (
        MIGRATE_EXACT,
        OMIT_EPHEMERAL,
        RECREATE_TARGET_SIDE,
        SOURCE_TABLE_POLICIES,
    )
    from tools.pg_backup import SCHEMA_ONLY_TABLE_POLICIES

    assert SOURCE_TABLE_POLICIES["requisicao_arquivos"].policy == MIGRATE_EXACT
    assert SOURCE_TABLE_POLICIES["admin_arquivos"].policy == MIGRATE_EXACT
    assert SOURCE_TABLE_POLICIES["storage_objects"].policy == MIGRATE_EXACT
    assert SOURCE_TABLE_POLICIES["storage_upload_intents"].policy == OMIT_EPHEMERAL
    assert SOURCE_TABLE_POLICIES["storage_worker_status"].policy == RECREATE_TARGET_SIDE
    # v16 adds two more ephemeral schema-only tables; the two published here are unchanged.
    assert {k: v for k, v in SCHEMA_ONLY_TABLE_POLICIES.items() if k.startswith("storage_")} == {
        "storage_upload_intents": "EPHEMERAL_OMITTED",
        "storage_worker_status": "TARGET_SIDE_RECREATED",
    }


def _canonical_source(tmp_path):
    """A v15 source: one canonical request row and NO credential row.

    (Path-B refuses ``local_legacy`` request rows by design -- no copy contract
    -- so the legacy-row preservation stays proven by the published Path-B
    suite; this source isolates the canonical row.)
    """
    path = tmp_path / "s3a-pathb-source.db"
    conn = _seeded(path)
    try:
        sql, params = insert_sql("storage_objects", object_row_for("e" * 32))
        object_id = conn.execute(sql + " RETURNING id", params).fetchone()[0]
        conn.execute(*insert_sql("requisicao_arquivos", {**materialize(canonical_request_row(), object_id),
                                                         "id": 8}))
        conn.commit()
    finally:
        conn.close()
    return path, object_id


def test_path_b_reads_a_canonical_source_exactly_without_a_google_prerequisite(tmp_path):
    from app import pg_migrate_from_sqlite as path_b

    path, object_id = _canonical_source(tmp_path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    snapshot = path_b.read_source(path, digest)
    columns = path_b._columns("requisicao_arquivos")
    rows = {row[columns.index("id")]: row for row in snapshot.rows["requisicao_arquivos"]}
    canonical = rows[8]
    assert canonical[columns.index("provider")] == "supabase"
    assert canonical[columns.index("storage_object_id")] == object_id
    assert canonical[columns.index("storage_status")] == "active"
    assert snapshot.rows["cloud_accounts"] == []
    assert path_b.GOOGLE_DRIVE_RECONNECT_REQUIRED not in path_b._prerequisites(snapshot, [])


def test_layer2_census_carries_the_canonical_reference(tmp_path):
    from tools.pg_backup import _storage_census

    path, object_id = _canonical_source(tmp_path)
    conn = sqlite3.connect(str(path))
    try:
        census = _storage_census(conn)
    finally:
        conn.close()
    assert census["objects"] == 1
    assert census["business_references"] == {"requisicao_arquivos": 1, "admin_arquivos": 0}
    assert census["by_drive_sync_state"] == {"pending": 1}
    assert census["by_lifecycle_state"] == {"active": 1}
    expected = hashlib.sha256(f"requisicao_arquivos:8:{object_id}\n".encode()).hexdigest()
    assert census["business_references_digest"] == expected
