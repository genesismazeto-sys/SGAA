"""prod-1 v16 -> v17: request reclassification while the request is editable.

WHAT CHANGES
    ``trg_requisicoes_snapshot_immutable`` is replaced: a ``Pendente`` or
    ``Devolvida`` request may change its activity version and rule snapshot
    together.  See ``app.prod1_request_reclassification_ddl``.

WHAT DOES NOT CHANGE
    Every row, value, column, table, index, other trigger and AUTOINCREMENT
    counter.  Nothing is backfilled; a decided request stays frozen exactly
    as in v16.

HOW
    The same statements the bootstrap executes, inside one ``BEGIN
    IMMEDIATE`` transaction: every table's rows are digested before and
    after, the counters, ``integrity_check``, ``foreign_key_check`` and the
    v17 head digest are checked before COMMIT.  A database already at v17 is
    never passed here: the bootstrap only calls this for ``user_version`` 16.
"""

from __future__ import annotations

import sqlite3

from app.prod1_request_reclassification_ddl import (
    REQUEST_RECLASSIFICATION_V17_DETAILS_JSON,
    REQUEST_RECLASSIFICATION_V17_STATEMENTS,
)
from app.prod1_storage_v14 import _columns, _data_digest, _sequences, _table_names


def migrate_prod1_v16_to_v17(conn: sqlite3.Connection) -> dict[str, object]:
    from app.prod1_schema import (
        BASELINE_MARKER,
        REQUEST_RECLASSIFICATION_MARKER,
        SCHEMA_EPOCH,
        Prod1SchemaError,
        _validate_prod1_v16_schema,
        _validate_prod1_v17_schema,
    )

    if conn.in_transaction:
        raise Prod1SchemaError("prod-1/v17 migration requires a clean connection")
    _validate_prod1_v16_schema(conn)

    try:
        conn.execute("BEGIN IMMEDIATE")
        tables = [name for name in _table_names(conn) if name != "schema_migrations"]
        columns_before = {table: _columns(conn, table) for table in tables}
        data_before = _data_digest(conn, columns_before)
        sequences_before = _sequences(conn)

        for statement in REQUEST_RECLASSIFICATION_V17_STATEMENTS:
            conn.execute(statement)
        conn.execute(
            "INSERT INTO schema_migrations(version,name,schema_epoch,details_json) VALUES(?,?,?,?)",
            (17, REQUEST_RECLASSIFICATION_MARKER, SCHEMA_EPOCH, REQUEST_RECLASSIFICATION_V17_DETAILS_JSON),
        )
        conn.execute("PRAGMA user_version=17")

        if {table: _columns(conn, table) for table in columns_before} != columns_before:
            raise Prod1SchemaError("prod-1/v17 migration changed a column list")
        if _data_digest(conn, columns_before) != data_before:
            raise Prod1SchemaError("prod-1/v17 migration changed existing rows")
        if _sequences(conn) != sequences_before:
            raise Prod1SchemaError("prod-1/v17 migration changed AUTOINCREMENT counters")
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise Prod1SchemaError("prod-1/v17 integrity check failed")
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise Prod1SchemaError(f"prod-1/v17 foreign key violations: {violations!r}")
        _validate_prod1_v17_schema(conn)
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise

    _validate_prod1_v17_schema(conn)
    status = {"schema_epoch": SCHEMA_EPOCH, "schema_version": 17,
              "baseline_marker": BASELINE_MARKER, "table_count": len(_table_names(conn))}
    return {
        **status,
        "request_reclassification": "pending_or_returned",
        "rows_preserved": {table: rows for table, (rows, _digest) in data_before.items()},
    }


__all__ = ["migrate_prod1_v16_to_v17"]
