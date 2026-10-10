"""prod-1 v14 -> v15: canonical business-document custody.

WHAT CHANGES
    ``provider = 'supabase'`` becomes legal on ``requisicao_arquivos`` (the
    custody triggers are replaced) and on ``admin_arquivos`` (the table is
    rebuilt: its provider domain is a column CHECK).  See
    ``app.prod1_document_custody_ddl``.

WHAT DOES NOT CHANGE
    Every row, id, value and AUTOINCREMENT counter; every legacy custody
    verdict; every other table, index and trigger.  Nothing is backfilled and
    no row changes provider.

HOW
    The same statements the bootstrap executes, inside one ``BEGIN
    IMMEDIATE`` transaction with foreign-key enforcement OFF (the ARQUIVOS
    rebuild drops a parent table of ``storage_upload_intents``; with
    enforcement ON its implicit DELETE would cascade).  All rows are digested
    before and after, the ``admin_arquivos`` high-water mark is restored, and
    ``integrity_check``, ``foreign_key_check`` and the v15 head digest are
    checked before COMMIT.  Any failure rolls back schema, data,
    ``user_version`` and ``schema_migrations`` together.  A database already
    at v15 is never passed here: the bootstrap only calls this for
    ``user_version`` 14.
"""

from __future__ import annotations

import sqlite3

from app.prod1_document_custody_ddl import (
    ARQUIVOS_V15_SCRATCH_TABLE,
    DOCUMENT_CUSTODY_V15_DETAILS_JSON,
    DOCUMENT_CUSTODY_V15_STATEMENTS,
)
from app.prod1_storage_v14 import _columns, _data_digest, _sequences, _table_names


def migrate_prod1_v14_to_v15(conn: sqlite3.Connection) -> dict[str, object]:
    from app.prod1_schema import (
        BASELINE_MARKER,
        CANONICAL_DOCUMENT_CUSTODY_MARKER,
        SCHEMA_EPOCH,
        Prod1SchemaError,
        _validate_prod1_v14_schema,
        _validate_prod1_v15_schema,
    )

    if conn.in_transaction:
        raise Prod1SchemaError("prod-1/v15 migration requires a clean connection")
    _validate_prod1_v14_schema(conn)
    foreign_keys_enabled = bool(conn.execute("PRAGMA foreign_keys").fetchone()[0])
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        conn.execute("BEGIN IMMEDIATE")
        tables = _table_names(conn)
        if ARQUIVOS_V15_SCRATCH_TABLE in tables:
            raise Prod1SchemaError("prod-1/v15 scratch table already exists on a v14 database")
        columns_before = {table: _columns(conn, table) for table in tables if table != "schema_migrations"}
        data_before = _data_digest(conn, columns_before)
        sequences_before = _sequences(conn)

        for statement in DOCUMENT_CUSTODY_V15_STATEMENTS:
            conn.execute(statement)
        conn.execute("DELETE FROM main.sqlite_sequence WHERE name='admin_arquivos'")
        for name, seq in sequences_before:
            if name == "admin_arquivos":
                conn.execute("INSERT INTO main.sqlite_sequence(name,seq) VALUES(?,?)", (name, seq))
        conn.execute(
            "INSERT INTO schema_migrations(version,name,schema_epoch,details_json) VALUES(?,?,?,?)",
            (15, CANONICAL_DOCUMENT_CUSTODY_MARKER, SCHEMA_EPOCH, DOCUMENT_CUSTODY_V15_DETAILS_JSON),
        )
        conn.execute("PRAGMA user_version=15")

        if {table: _columns(conn, table) for table in columns_before} != columns_before:
            raise Prod1SchemaError("prod-1/v15 migration changed a column list")
        if _data_digest(conn, columns_before) != data_before:
            raise Prod1SchemaError("prod-1/v15 migration changed existing rows")
        if _sequences(conn) != sequences_before:
            raise Prod1SchemaError("prod-1/v15 migration changed AUTOINCREMENT counters")
        if conn.execute(
            "SELECT (SELECT count(*) FROM main.requisicao_arquivos WHERE provider='supabase')"
            " + (SELECT count(*) FROM main.admin_arquivos WHERE provider='supabase')"
        ).fetchone()[0]:
            raise Prod1SchemaError("prod-1/v15 migration backfilled a canonical provider")
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise Prod1SchemaError("prod-1/v15 integrity check failed")
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise Prod1SchemaError(f"prod-1/v15 foreign key violations: {violations!r}")
        _validate_prod1_v15_schema(conn)
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute(f"PRAGMA foreign_keys={'ON' if foreign_keys_enabled else 'OFF'}")

    _validate_prod1_v15_schema(conn)
    return {
        "schema_epoch": SCHEMA_EPOCH,
        "schema_version": 15,
        "baseline_marker": BASELINE_MARKER,
        "table_count": len(_table_names(conn)),
        "canonical_provider": "supabase",
        "rows_preserved": {table: rows for table, (rows, _digest) in data_before.items()},
    }


__all__ = ["migrate_prod1_v14_to_v15"]
