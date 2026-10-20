"""Atomic SQLite v17 -> v18 CHECK expansion; all rows and counters preserved."""
from __future__ import annotations

from app.prod1_return_notifications_ddl import (
    RETURN_NOTIFICATIONS_V18_MARKER_SQL,
    RETURN_NOTIFICATIONS_V18_STATEMENTS,
)
from app.prod1_storage_v14 import _columns, _data_digest, _sequences, _table_names


def migrate_prod1_v17_to_v18(conn):
    from app.prod1_schema import Prod1SchemaError, _validate_prod1_v17_schema, validate_prod1_schema

    if conn.in_transaction:
        raise Prod1SchemaError("prod-1/v18 migration requires a clean connection")
    _validate_prod1_v17_schema(conn)
    try:
        conn.execute("BEGIN IMMEDIATE")
        columns = {t: _columns(conn, t) for t in _table_names(conn) if t != "schema_migrations"}
        before, sequences = _data_digest(conn, columns), _sequences(conn)
        for statement in RETURN_NOTIFICATIONS_V18_STATEMENTS:
            conn.execute(statement)
        conn.execute("DELETE FROM sqlite_sequence WHERE name='requisicao_email_eventos'")
        for name, seq in sequences:
            if name == "requisicao_email_eventos":
                conn.execute("INSERT INTO sqlite_sequence(name,seq) VALUES(?,?)", (name, seq))
        conn.execute(RETURN_NOTIFICATIONS_V18_MARKER_SQL)
        conn.execute("PRAGMA user_version=18")
        if _data_digest(conn, columns) != before or _sequences(conn) != sequences:
            raise Prod1SchemaError("prod-1/v18 migration changed existing rows or counters")
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise Prod1SchemaError("prod-1/v18 integrity check failed")
        validate_prod1_schema(conn)
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    return {**validate_prod1_schema(conn), "return_notifications": "enabled", "backfill": "none"}
