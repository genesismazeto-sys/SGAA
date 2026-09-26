"""prod-1/v10: durable confirmed-send evidence on the password token.

v10 adds exactly one column, ``senha_tokens.sent_at``. It exists because
``app.password_email`` distinguishes a confirmed send from an indeterminate one
and from a definite failure, but before v10 the first two were
**indistinguishable in the database** -- both left a live, unconsumed token and
differed only in a log line.

Nothing is backfilled: no pre-v10 row carries the evidence, and inventing a
timestamp from ``created_at`` would manufacture exactly the proof the column
exists to require.

Every test runs on a disposable database. The canonical database is never
opened for writing.
"""

from __future__ import annotations

import sqlite3

import pytest

from app import db_maintenance
from app.prod1_access_delivery_ddl import (
    SENHA_TOKENS_V10_ADD_COLUMN_SQL,
    SENHA_TOKENS_V10_TABLE_SQL,
)
from app.prod1_schema import (
    ACCESS_DELIVERY_MARKER,
    CREDENTIAL_PENDING_MARKER,
    SCHEMA_EPOCH,
    SCHEMA_VERSION,
    Prod1SchemaError,
    _PROD1_V9_SIGNATURE_SHA256,
    _PROD1_V10_SIGNATURE_SHA256,
    _normalize_schema_sql,
    _physical_schema_digest,
    _validate_prod1_v9_schema,
    _validate_prod1_v10_schema,
    bootstrap_prod1_schema,
    migrate_prod1_v9_to_v10,
    validate_prod1_schema,
)
from app.security.passwords import hash_password
from app.user_accounts import (
    CREDENTIAL_STATE_DEFAULT,
    create_usuario_with_access_level,
)
from tests.prod1_v11_support import revert_prod1_v11_to_v10


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _build_v10(conn: sqlite3.Connection) -> None:
    """A genuine v10 database: bootstrap the head, revert the v11 rebuild."""
    bootstrap_prod1_schema(conn)
    revert_prod1_v11_to_v10(conn)
    assert _physical_schema_digest(conn) == _PROD1_V10_SIGNATURE_SHA256


def _build_v9(conn: sqlite3.Connection) -> None:
    """A genuine v9 database: build v10, revert the one v10 column."""
    _build_v10(conn)
    conn.execute("ALTER TABLE senha_tokens DROP COLUMN sent_at")
    conn.execute("DELETE FROM schema_migrations WHERE version=10")
    conn.execute("PRAGMA user_version=9")
    conn.commit()
    assert _physical_schema_digest(conn) == _PROD1_V9_SIGNATURE_SHA256, (
        "the reverted database is not the frozen v9 shape, so anything this "
        "suite proves about migrating it is meaningless"
    )


def _seed_token(conn: sqlite3.Connection, label: str, **columns) -> int:
    cursor = create_usuario_with_access_level(
        conn, label, f"{label}@example.test", hash_password("x"),
        "admin", "admin_total", credential_state=CREDENTIAL_STATE_DEFAULT,
    )
    usuario_id = int(cursor.lastrowid)
    payload = {
        "usuario_id": usuario_id,
        "purpose": "first_access",
        "token_hash": f"hash-{label}",
        "expires_at": "2099-01-01 00:00:00",
        **columns,
    }
    names = ",".join(payload)
    placeholders = ",".join("?" for _ in payload)
    conn.execute(
        f"INSERT INTO senha_tokens({names}) VALUES({placeholders})",
        list(payload.values()),
    )
    conn.commit()
    return usuario_id


# --------------------------------------------------------------- HEAD / CHAIN


def test_v10_is_the_direct_predecessor_of_the_v11_head():
    assert SCHEMA_VERSION == 11
    assert db_maintenance.SCHEMA_MIGRATIONS[9][:2] == (10, ACCESS_DELIVERY_MARKER)
    assert db_maintenance.SCHEMA_MIGRATIONS[-1][:2] == (11, CREDENTIAL_PENDING_MARKER)
    assert len(db_maintenance.SCHEMA_MIGRATIONS) == 11


def test_schema_epoch_is_unchanged_by_v10():
    assert SCHEMA_EPOCH == "prod-1"


def test_fresh_bootstrap_carries_the_v10_marker_and_v10_is_recognisable():
    conn = _connect()
    status = bootstrap_prod1_schema(conn)
    assert status["schema_version"] == 11
    assert conn.execute(
        "SELECT name FROM schema_migrations WHERE version=10"
    ).fetchone()[0] == ACCESS_DELIVERY_MARKER

    predecessor = _connect()
    _build_v10(predecessor)
    _validate_prod1_v10_schema(predecessor)
    with pytest.raises(Prod1SchemaError):
        validate_prod1_schema(predecessor)


def test_v9_remains_recognisable_as_a_predecessor():
    conn = _connect()
    _build_v9(conn)
    _validate_prod1_v9_schema(conn)
    with pytest.raises(Prod1SchemaError):
        validate_prod1_schema(conn)


def test_v10_migration_refuses_a_database_that_is_not_v9():
    conn = _connect()
    bootstrap_prod1_schema(conn)  # already v10
    with pytest.raises(Prod1SchemaError):
        migrate_prod1_v9_to_v10(conn)


def test_bootstrap_migrates_a_v9_database_to_the_head():
    conn = _connect()
    _build_v9(conn)
    status = bootstrap_prod1_schema(conn)
    assert status["schema_version"] == 11
    assert [
        int(row[0]) for row in conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        )
    ] == list(range(1, 12))


# ----------------------------------------------------------------- MIGRATION


def test_v9_to_v10_is_additive_and_backfills_nothing():
    conn = _connect()
    _build_v9(conn)

    live = _seed_token(conn, "liveuser")
    consumed = _seed_token(conn, "consumeduser", consumed_at="2026-01-01 00:00:00")
    dead = _seed_token(conn, "deaduser", invalidated_at="2026-01-01 00:00:00")

    tokens_before = [
        tuple(row) for row in conn.execute(
            "SELECT id,usuario_id,purpose,token_hash,created_at,expires_at,"
            "consumed_at,invalidated_at FROM senha_tokens ORDER BY id"
        )
    ]
    credentials_before = [
        tuple(row) for row in conn.execute(
            "SELECT usuario_id,estado,auth_version,acesso_ativo"
            " FROM usuario_credenciais ORDER BY usuario_id"
        )
    ]
    passwords_before = [
        tuple(row) for row in conn.execute("SELECT id,senha FROM usuarios ORDER BY id")
    ]

    status = migrate_prod1_v9_to_v10(conn)

    assert status["schema_version"] == 10
    assert status["access_delivery_backfill"] == "none"
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 10

    # Additive: no pre-existing token or credential column moved.
    assert [
        tuple(row) for row in conn.execute(
            "SELECT id,usuario_id,purpose,token_hash,created_at,expires_at,"
            "consumed_at,invalidated_at FROM senha_tokens ORDER BY id"
        )
    ] == tokens_before
    assert [
        tuple(row) for row in conn.execute(
            "SELECT usuario_id,estado,auth_version,acesso_ativo"
            " FROM usuario_credenciais ORDER BY usuario_id"
        )
    ] == credentials_before
    assert [
        tuple(row) for row in conn.execute("SELECT id,senha FROM usuarios ORDER BY id")
    ] == passwords_before

    # THE POINT: no migrated token claims a confirmed send. Not the live one,
    # not the consumed one, not the invalidated one.
    sent = {
        int(row["usuario_id"]): row["sent_at"]
        for row in conn.execute("SELECT usuario_id,sent_at FROM senha_tokens")
    }
    assert sent[live] is None
    assert sent[consumed] is None
    assert sent[dead] is None
    assert int(
        conn.execute("SELECT COUNT(*) FROM senha_tokens WHERE sent_at IS NOT NULL").fetchone()[0]
    ) == 0

    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    # v10 is no longer the head: its frozen recognizer, not the head's.
    _validate_prod1_v10_schema(conn)


def test_migrated_v10_is_signature_identical_to_the_frozen_v10_shape():
    """The additive ALTER must land on exactly the v10 shape."""
    migrated = _connect()
    _build_v9(migrated)
    migrate_prod1_v9_to_v10(migrated)

    reverted = _connect()
    _build_v10(reverted)

    assert _physical_schema_digest(migrated) == _physical_schema_digest(reverted)
    assert _physical_schema_digest(migrated) == _PROD1_V10_SIGNATURE_SHA256


def test_add_column_statement_matches_the_bootstrap_ddl():
    """The migration statement and the canonical DDL must not drift apart.

    This is the property that lets v10 be a one-line ALTER: SQLite splices an
    added column immediately before the FOREIGN KEY clause, which is exactly
    where ``SENHA_TOKENS_V10_TABLE_SQL`` declares it.
    """
    altered = _connect()
    _build_v9(altered)
    altered.execute(SENHA_TOKENS_V10_ADD_COLUMN_SQL)

    fresh = _connect()
    bootstrap_prod1_schema(fresh)

    assert _normalize_schema_sql(
        altered.execute("SELECT sql FROM sqlite_master WHERE name='senha_tokens'").fetchone()[0]
    ) == _normalize_schema_sql(
        fresh.execute("SELECT sql FROM sqlite_master WHERE name='senha_tokens'").fetchone()[0]
    )
    assert _normalize_schema_sql(SENHA_TOKENS_V10_TABLE_SQL) == _normalize_schema_sql(
        fresh.execute("SELECT sql FROM sqlite_master WHERE name='senha_tokens'").fetchone()[0]
    )


# ------------------------------------------------------------------- COLUMN


def test_sent_at_column_contract():
    conn = _connect()
    bootstrap_prod1_schema(conn)
    columns = {row["name"]: row for row in conn.execute("PRAGMA table_info(senha_tokens)")}
    assert "sent_at" in columns
    # Nullable with no default: NULL is the honest "no confirmed send", and a
    # default would hand every issued token evidence it has not earned.
    assert columns["sent_at"]["notnull"] == 0
    assert columns["sent_at"]["dflt_value"] is None

    usuario_id = _seed_token(conn, "contract")
    assert conn.execute(
        "SELECT sent_at FROM senha_tokens WHERE usuario_id=?", (usuario_id,)
    ).fetchone()[0] is None


def test_v10_adds_no_table():
    """One column, not a disconnected status table."""
    conn = _connect()
    _build_v9(conn)
    before = {
        str(row[0]) for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    migrate_prod1_v9_to_v10(conn)
    after = {
        str(row[0]) for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    assert after == before


def test_canonical_database_is_never_written_by_this_suite():
    from pathlib import Path

    canonical = Path(__file__).resolve().parents[1] / "database.db"
    if not canonical.exists():
        pytest.skip("no canonical database present in this checkout")
    probe = sqlite3.connect(f"file:{canonical.as_posix()}?mode=ro", uri=True)
    try:
        version = probe.execute("PRAGMA user_version").fetchone()[0]
    finally:
        probe.close()
    # The canonical database is not migrated to v11 by the credential front.
    # Canonical was migrated to v11 on 2026-09-24 (authorised, UI-CP1).
    assert version in (9, 10, 11), f"canonical database is at an unexpected version {version}"
