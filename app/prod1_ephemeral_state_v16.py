"""prod-1 v15 -> v16: ephemeral cross-request state (additive).

WHAT CHANGES
    Two new, empty tables -- ``auth_throttle_events`` and
    ``admin_import_previews`` -- and their indexes.  See
    ``app.prod1_ephemeral_state_ddl``.

WHAT DOES NOT CHANGE
    Every existing row, value, column, index, trigger and AUTOINCREMENT
    counter.  Nothing is backfilled and nothing in a local (single-process)
    runtime reads the throttle table.

HOW
    The same statements the bootstrap executes, inside one ``BEGIN
    IMMEDIATE`` transaction: the pre-existing tables' rows are digested before
    and after, the counters, ``integrity_check``, ``foreign_key_check`` and
    the v16 head digest are checked before COMMIT.  A database already at v16
    is never passed here: the bootstrap only calls this for ``user_version``
    15.
"""

from __future__ import annotations

import sqlite3

from app.prod1_ephemeral_state_ddl import (
    EPHEMERAL_STATE_V16_DETAILS_JSON,
    EPHEMERAL_STATE_V16_STATEMENTS,
    EPHEMERAL_STATE_V16_TABLES,
)
from app.prod1_storage_v14 import _columns, _data_digest, _sequences, _table_names


def migrate_prod1_v15_to_v16(conn: sqlite3.Connection) -> dict[str, object]:
    from app.prod1_schema import (
        EPHEMERAL_STATE_MARKER,
        SCHEMA_EPOCH,
        Prod1SchemaError,
        _validate_prod1_v15_schema,
        validate_prod1_schema,
    )

    if conn.in_transaction:
        raise Prod1SchemaError("prod-1/v16 migration requires a clean connection")
    _validate_prod1_v15_schema(conn)

    try:
        conn.execute("BEGIN IMMEDIATE")
        existing = [name for name in _table_names(conn) if name != "schema_migrations"]
        if set(existing) & set(EPHEMERAL_STATE_V16_TABLES):
            raise Prod1SchemaError("prod-1/v16 ephemeral-state tables already exist on a v15 database")
        columns_before = {table: _columns(conn, table) for table in existing}
        data_before = _data_digest(conn, columns_before)
        sequences_before = _sequences(conn)

        for statement in EPHEMERAL_STATE_V16_STATEMENTS:
            conn.execute(statement)
        conn.execute(
            "INSERT INTO schema_migrations(version,name,schema_epoch,details_json) VALUES(?,?,?,?)",
            (16, EPHEMERAL_STATE_MARKER, SCHEMA_EPOCH, EPHEMERAL_STATE_V16_DETAILS_JSON),
        )
        conn.execute("PRAGMA user_version=16")

        if {table: _columns(conn, table) for table in columns_before} != columns_before:
            raise Prod1SchemaError("prod-1/v16 migration changed a column list")
        if _data_digest(conn, columns_before) != data_before:
            raise Prod1SchemaError("prod-1/v16 migration changed existing rows")
        if _sequences(conn) != sequences_before:
            raise Prod1SchemaError("prod-1/v16 migration changed AUTOINCREMENT counters")
        for table in EPHEMERAL_STATE_V16_TABLES:
            if conn.execute(f"SELECT count(*) FROM main.{table}").fetchone()[0]:
                raise Prod1SchemaError(f"prod-1/v16 migration backfilled {table}")
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise Prod1SchemaError("prod-1/v16 integrity check failed")
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise Prod1SchemaError(f"prod-1/v16 foreign key violations: {violations!r}")
        validate_prod1_schema(conn)
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise

    status = validate_prod1_schema(conn)
    return {
        **status,
        "ephemeral_state": "database",
        "rows_preserved": {table: rows for table, (rows, _digest) in data_before.items()},
    }


__all__ = ["migrate_prod1_v15_to_v16"]
