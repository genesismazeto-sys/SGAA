# coding: utf-8
"""MP-2 slice 3: prod-1/v16 ephemeral-state schema (SQLite authority, PostgreSQL contract).

v16 adds two empty, ephemeral tables.  The proofs: a fresh v16 equals a v15
database migrated forward (same physical digest), the migration preserves
every row and rolls back whole on failure, each constraint refuses what it
guards, and the PostgreSQL contract states the same table set and rules.
"""

from __future__ import annotations

import sqlite3

import pytest

from app import pg_schema, prod1_schema
from app.prod1_ephemeral_state_ddl import (
    AUTH_THROTTLE_SCOPES,
    EPHEMERAL_STATE_V16_TABLES,
    IMPORT_PREVIEW_PAYLOAD_MAX_BYTES,
)
from app.prod1_schema import (
    Prod1SchemaError,
    _physical_schema_digest,
    bootstrap_prod1_schema,
    canonical_prod1_pre_v16_object_sql,
    validate_prod1_schema,
)
from tests.prod1_v15_support import revert_prod1_v15_to_v14
from tests.prod1_v16_support import revert_prod1_v16_to_v15

DIGEST = "ab" * 32
STAMP = "2026-10-09 12:00:00"


def _fresh(path=":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys=ON")
    bootstrap_prod1_schema(conn)
    return conn


def _seed(conn) -> None:
    conn.executescript(
        "INSERT INTO usuarios(id,nome,email,senha,tipo) VALUES(1,'Admin','v16@x.test','x','admin');"
        "INSERT INTO usuarios(id,nome,email,senha,tipo) VALUES(2,'Aluno','v16b@x.test','x','aluno');"
        "INSERT INTO atividade_base(id,nome_conceito) VALUES(1,'Conceito');"
    )
    conn.commit()


def _refused(conn, sql, params=()) -> bool:
    conn.execute("SAVEPOINT probe")
    try:
        conn.execute(sql, params)
        return False
    except sqlite3.IntegrityError:
        return True
    finally:
        conn.execute("ROLLBACK TO SAVEPOINT probe")
        conn.execute("RELEASE SAVEPOINT probe")


# --- version gate -----------------------------------------------------------------


def test_v16_is_the_head_on_both_authorities():
    assert prod1_schema.SCHEMA_VERSION == 16 == pg_schema.PG_SCHEMA_VERSION
    assert callable(getattr(prod1_schema, "migrate_prod1_v15_to_v16", None))


def test_a_fresh_database_is_v16_with_both_tables_empty_and_marked():
    conn = _fresh()
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 16
        assert validate_prod1_schema(conn)["schema_version"] == 16
        row = conn.execute("SELECT name, schema_epoch FROM schema_migrations WHERE version=16").fetchone()
        assert tuple(row) == ("ephemeral_state", "prod-1")
        for table in EPHEMERAL_STATE_V16_TABLES:
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        assert {"idx_auth_throttle_events_lookup", "idx_auth_throttle_events_expiry",
                "idx_admin_import_previews_expiry"} <= names
    finally:
        conn.close()


# --- migration --------------------------------------------------------------------


def _v15_copy():
    conn = _fresh()
    _seed(conn)
    revert_prod1_v16_to_v15(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 15
    return conn


def test_a_v15_database_migrates_to_the_same_physical_schema_as_a_fresh_v16():
    migrated = _v15_copy()
    fresh = _fresh()
    try:
        result = prod1_schema.bootstrap_prod1_schema(migrated)
        assert result["schema_version"] == 16 and result["ephemeral_state"] == "database"
        assert _physical_schema_digest(migrated) == _physical_schema_digest(fresh)
        assert migrated.execute("SELECT count(*) FROM usuarios").fetchone()[0] == 2
        assert migrated.execute("SELECT count(*) FROM atividade_base").fetchone()[0] == 1
    finally:
        migrated.close()
        fresh.close()


def test_the_frozen_v15_predecessor_is_recognised_and_a_tampered_one_is_not():
    conn = _v15_copy()
    try:
        prod1_schema._validate_prod1_v15_schema(conn)
        conn.execute("CREATE TABLE sneaky(x)")
        with pytest.raises(Prod1SchemaError):
            prod1_schema._validate_prod1_v15_schema(conn)
        with pytest.raises(Prod1SchemaError):
            prod1_schema.migrate_prod1_v15_to_v16(conn)
    finally:
        conn.close()


def test_a_v14_database_reaches_v16_through_the_whole_chain():
    conn = _fresh()
    try:
        _seed(conn)
        revert_prod1_v15_to_v14(conn)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 14
        assert bootstrap_prod1_schema(conn)["schema_version"] == 16
        assert _physical_schema_digest(conn) == _physical_schema_digest(_fresh())
    finally:
        conn.close()


def test_a_failed_migration_rolls_back_schema_data_and_version(monkeypatch):
    import app.prod1_ephemeral_state_v16 as migration

    conn = _v15_copy()
    try:
        before = _physical_schema_digest(conn)
        monkeypatch.setattr(
            migration, "EPHEMERAL_STATE_V16_STATEMENTS",
            migration.EPHEMERAL_STATE_V16_STATEMENTS[:1] + ("CREATE TABLE definitely not sql",),
        )
        with pytest.raises(sqlite3.Error):
            prod1_schema.migrate_prod1_v15_to_v16(conn)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 15
        assert _physical_schema_digest(conn) == before
        assert not conn.in_transaction
        assert conn.execute("SELECT count(*) FROM schema_migrations WHERE version=16").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM usuarios").fetchone()[0] == 2
    finally:
        conn.close()


def test_a_migration_that_finds_the_tables_already_present_refuses():
    conn = _v15_copy()
    try:
        conn.execute("CREATE TABLE auth_throttle_events(x)")
        conn.commit()
        with pytest.raises(Prod1SchemaError):
            prod1_schema.migrate_prod1_v15_to_v16(conn)
    finally:
        conn.close()


def test_the_pre_v16_probe_returns_v15_objects_only():
    assert "CREATE TABLE usuarios" in canonical_prod1_pre_v16_object_sql("table", "usuarios")
    with pytest.raises(Exception):
        canonical_prod1_pre_v16_object_sql("table", "auth_throttle_events")


# --- constraints ------------------------------------------------------------------


def _throttle_row(**override):
    row = {"scope": "login_ip", "key_digest": DIGEST, "occurred_at": STAMP}
    row.update(override)
    return row


def _insert_throttle(row):
    return ("INSERT INTO auth_throttle_events(scope,key_digest,occurred_at) VALUES(?,?,?)",
            (row["scope"], row["key_digest"], row["occurred_at"]))


@pytest.mark.parametrize("scope", AUTH_THROTTLE_SCOPES)
def test_every_declared_scope_is_accepted(scope):
    conn = _fresh()
    try:
        sql, params = _insert_throttle(_throttle_row(scope=scope))
        assert _refused(conn, sql, params) is False
    finally:
        conn.close()


@pytest.mark.parametrize(
    "override",
    [
        {"scope": "other"},
        {"scope": ""},
        {"key_digest": "AB" * 32},
        {"key_digest": "ab" * 31},
        {"key_digest": "ab" * 33},
        {"key_digest": "g" * 64},
        {"occurred_at": "2026-10-09T12:00:00"},
        {"occurred_at": "2026-13-45 99:99:99"},
        {"occurred_at": "2026-10-09 24:00:00"},
        {"occurred_at": None},
    ],
)
def test_throttle_constraints_refuse_malformed_rows(override):
    conn = _fresh()
    try:
        sql, params = _insert_throttle(_throttle_row(**override))
        assert _refused(conn, sql, params) is True
    finally:
        conn.close()


def _insert_preview(**override):
    row = {"token_digest": DIGEST, "usuario_id": 1, "payload": "{}", "created_at": STAMP,
           "expires_at": "2026-10-09 13:00:00"}
    row.update(override)
    return ("INSERT INTO admin_import_previews(token_digest,usuario_id,payload,created_at,expires_at)"
            " VALUES(?,?,?,?,?)",
            (row["token_digest"], row["usuario_id"], row["payload"], row["created_at"], row["expires_at"]))


def test_a_valid_preview_is_accepted_and_each_rule_refuses_its_violation():
    conn = _fresh()
    try:
        _seed(conn)
        assert _refused(conn, *_insert_preview()) is False
        for override in (
            {"token_digest": "xyz"},
            {"usuario_id": 99},
            {"usuario_id": None},
            {"payload": ""},
            {"payload": "x"},
            {"payload": "y" * (IMPORT_PREVIEW_PAYLOAD_MAX_BYTES + 1)},
            {"created_at": "bad"},
            {"expires_at": "2026-10-09 12:00:00"},
            {"expires_at": "2026-10-09 11:00:00"},
        ):
            assert _refused(conn, *_insert_preview(**override)) is True, override
    finally:
        conn.close()


def test_a_preview_belongs_to_its_administrator_and_dies_with_the_account():
    conn = _fresh()
    try:
        _seed(conn)
        conn.execute(*_insert_preview())
        conn.execute(*_insert_preview(token_digest="cd" * 32, usuario_id=2))
        assert _refused(conn, *_insert_preview()) is True  # the token digest is unique
        conn.execute("DELETE FROM usuarios WHERE id=1")
        remaining = conn.execute("SELECT usuario_id FROM admin_import_previews").fetchall()
        assert [r[0] for r in remaining] == [2]
    finally:
        conn.close()


# --- PostgreSQL contract ----------------------------------------------------------


def test_the_postgresql_contract_lists_the_same_tables_and_rules():
    for table in EPHEMERAL_STATE_V16_TABLES:
        assert table in pg_schema.PG_APPLICATION_TABLES
        assert table in pg_schema.PG_TABLE_SPECS
    sqlite_tables = set(prod1_schema.EXPECTED_TABLES)
    pg_tables = set(pg_schema.PG_APPLICATION_TABLES)
    assert sqlite_tables == pg_tables
    pg_scope_rule = next(c for c in pg_schema.PG_TABLE_SPECS["auth_throttle_events"]["checks"]
                         if c["name"] == "ck_auth_throttle_events_scope")["expression"]
    for scope in AUTH_THROTTLE_SCOPES:
        assert f"'{scope}'" in pg_scope_rule
    seed = {version: name for version, name, _details in pg_schema.PG_SCHEMA_MIGRATIONS_SEED}
    assert seed[16] == "ephemeral_state"
    index_names = set(pg_schema.PG_EXPLICIT_INDEXES)
    assert {"idx_auth_throttle_events_lookup", "idx_auth_throttle_events_expiry",
            "idx_admin_import_previews_expiry"} <= index_names


# --- Path-B and Layer-2 policy ----------------------------------------------------


def test_path_b_never_migrates_and_layer2_archives_schema_only_for_both_tables():
    from app import pg_migrate_from_sqlite as path_b
    from tools import pg_backup

    for table in EPHEMERAL_STATE_V16_TABLES:
        assert path_b.SOURCE_TABLE_POLICIES[table].policy == path_b.OMIT_EPHEMERAL
        assert table not in path_b.migrated_tables()
        assert pg_backup.SCHEMA_ONLY_TABLE_POLICIES[table] == "EPHEMERAL_OMITTED"
        assert f"--exclude-table-data=public.{table}" in pg_backup.PG_DUMP_OPTIONS
    # control: a business table of the same schema is still migrated exactly
    assert path_b.SOURCE_TABLE_POLICIES["usuarios"].policy == path_b.MIGRATE_EXACT
    assert "usuarios" in path_b.migrated_tables()
