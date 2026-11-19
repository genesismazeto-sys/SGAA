"""Atomic SQLite v18 -> v19 migration: the two document-template tables.

Purely additive (``app.prod1_document_templates_ddl``): every existing row,
table and AUTOINCREMENT counter is proven unchanged before the commit.
"""
from __future__ import annotations

from app.prod1_document_templates_ddl import (
    DOCUMENT_TEMPLATES_V19_MARKER_SQL,
    DOCUMENT_TEMPLATES_V19_STATEMENTS,
)
from app.prod1_storage_v14 import _columns, _data_digest, _sequences, _table_names


def migrate_prod1_v18_to_v19(conn):
    from app.prod1_schema import Prod1SchemaError, _validate_prod1_v18_schema, validate_prod1_schema

    if conn.in_transaction:
        raise Prod1SchemaError("prod-1/v19 migration requires a clean connection")
    _validate_prod1_v18_schema(conn)
    try:
        conn.execute("BEGIN IMMEDIATE")
        columns = {t: _columns(conn, t) for t in _table_names(conn) if t != "schema_migrations"}
        before, sequences = _data_digest(conn, columns), _sequences(conn)
        for statement in DOCUMENT_TEMPLATES_V19_STATEMENTS:
            conn.execute(statement)
        conn.execute(DOCUMENT_TEMPLATES_V19_MARKER_SQL)
        conn.execute("PRAGMA user_version=19")
        if _data_digest(conn, columns) != before or _sequences(conn) != sequences:
            raise Prod1SchemaError("prod-1/v19 migration changed existing rows or counters")
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise Prod1SchemaError("prod-1/v19 integrity check failed")
        validate_prod1_schema(conn)
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    return {**validate_prod1_schema(conn), "document_templates": "enabled", "backfill": "none"}
