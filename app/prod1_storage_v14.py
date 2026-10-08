"""prod-1 v13 -> v14: canonical-storage infrastructure (additive).

WHAT CHANGES
    Three new, empty tables -- ``storage_objects``, ``storage_upload_intents``
    and ``storage_worker_status`` -- plus a nullable ``storage_object_id``
    column (FK -> ``storage_objects``, partial UNIQUE, cross-table exclusive)
    on ``requisicao_arquivos`` and ``admin_arquivos``, and a nullable
    ``cloud_accounts.provider_account_key`` (logical Google-account identity;
    never derived from an e-mail, so every existing row keeps NULL).  See
    ``app.prod1_storage_ddl``.

WHAT DOES NOT CHANGE
    Every existing row, value, index, trigger and AUTOINCREMENT counter.  The
    Google / local custody columns and their triggers stay authoritative; the
    new column is NULL on every existing row and nothing writes it in v14.
    Nothing is backfilled.

HOW
    The same statements the bootstrap executes, inside one ``BEGIN
    IMMEDIATE`` transaction: the pre-existing tables' rows are digested before
    and after (the two altered tables compared on their pre-existing columns),
    the counters, ``integrity_check``, ``foreign_key_check`` and the v14 head
    digest are checked before COMMIT.  A database already at v14 is never
    passed here: the bootstrap only calls this for ``user_version`` 13.
"""

from __future__ import annotations

import hashlib
import sqlite3

from app.prod1_storage_ddl import (
    STORAGE_OBJECT_REFERENCE_TABLES,
    STORAGE_V14_STATEMENTS,
    STORAGE_V14_TABLES,
)


_V14_DETAILS_JSON = (
    '{"schema_epoch":"prod-1","canonical_storage":"supabase","drive":"async_mirror",'
    '"tables":["storage_objects","storage_upload_intents","storage_worker_status"],'
    '"columns":["requisicao_arquivos.storage_object_id","admin_arquivos.storage_object_id"],'
    '"backfill":"none","runtime_switch":"none"}'
)


def _table_names(conn: sqlite3.Connection) -> list[str]:
    return sorted(
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM main.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    )


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in conn.execute(f'PRAGMA main.table_info("{table}")').fetchall()]


def _data_digest(conn: sqlite3.Connection, columns_by_table: dict[str, list[str]]) -> dict[str, tuple[int, str]]:
    """``{table: (rows, sha256)}`` over the given columns, in rowid order."""
    digests = {}
    for table, columns in columns_by_table.items():
        column_list = ",".join(f'"{name}"' for name in columns)
        digest = hashlib.sha256()
        count = 0
        for row in conn.execute(f'SELECT {column_list} FROM main."{table}" ORDER BY rowid').fetchall():
            digest.update(repr(tuple(row)).encode("utf-8"))
            digest.update(b"\n")
            count += 1
        digests[table] = (count, digest.hexdigest())
    return digests


def _sequences(conn: sqlite3.Connection) -> list[tuple]:
    return [tuple(row) for row in conn.execute("SELECT name,seq FROM main.sqlite_sequence ORDER BY name")]


def migrate_prod1_v13_to_v14(conn: sqlite3.Connection) -> dict[str, object]:
    from app.prod1_schema import (
        CANONICAL_STORAGE_MARKER,
        SCHEMA_EPOCH,
        Prod1SchemaError,
        _validate_prod1_v13_schema,
        validate_prod1_schema,
    )

    if conn.in_transaction:
        raise Prod1SchemaError("prod-1/v14 migration requires a clean connection")
    _validate_prod1_v13_schema(conn)

    try:
        conn.execute("BEGIN IMMEDIATE")
        existing = [name for name in _table_names(conn) if name != "schema_migrations"]
        if set(existing) & set(STORAGE_V14_TABLES):
            raise Prod1SchemaError("prod-1/v14 storage tables already exist on a v13 database")
        columns_before = {table: _columns(conn, table) for table in existing}
        for table in STORAGE_OBJECT_REFERENCE_TABLES:
            if "storage_object_id" in columns_before[table]:
                raise Prod1SchemaError(f"prod-1/v14 column already exists on {table}")
        if "provider_account_key" in columns_before["cloud_accounts"]:
            raise Prod1SchemaError("prod-1/v14 column already exists on cloud_accounts")
        data_before = _data_digest(conn, columns_before)
        sequences_before = _sequences(conn)

        for statement in STORAGE_V14_STATEMENTS:
            conn.execute(statement)
        conn.execute(
            "INSERT INTO schema_migrations(version,name,schema_epoch,details_json)"
            " VALUES(?,?,?,?)",
            (14, CANONICAL_STORAGE_MARKER, SCHEMA_EPOCH, _V14_DETAILS_JSON),
        )
        conn.execute("PRAGMA user_version=14")

        if _data_digest(conn, columns_before) != data_before:
            raise Prod1SchemaError("prod-1/v14 migration changed existing rows")
        if _sequences(conn) != sequences_before:
            raise Prod1SchemaError("prod-1/v14 migration changed AUTOINCREMENT counters")
        for table in STORAGE_V14_TABLES:
            if conn.execute(f"SELECT count(*) FROM main.{table}").fetchone()[0]:
                raise Prod1SchemaError(f"prod-1/v14 migration backfilled {table}")
        for table in STORAGE_OBJECT_REFERENCE_TABLES:
            if conn.execute(
                f"SELECT count(*) FROM main.{table} WHERE storage_object_id IS NOT NULL"
            ).fetchone()[0]:
                raise Prod1SchemaError(f"prod-1/v14 migration backfilled {table}.storage_object_id")
        if conn.execute(
            "SELECT count(*) FROM main.cloud_accounts WHERE provider_account_key IS NOT NULL"
        ).fetchone()[0]:
            raise Prod1SchemaError("prod-1/v14 migration backfilled cloud_accounts.provider_account_key")
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise Prod1SchemaError("prod-1/v14 integrity check failed")
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise Prod1SchemaError(f"prod-1/v14 foreign key violations: {violations!r}")
        validate_prod1_schema(conn)
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise

    status = validate_prod1_schema(conn)
    return {
        **status,
        "canonical_storage": "supabase",
        "rows_preserved": {table: rows for table, (rows, _digest) in data_before.items()},
    }


__all__ = ["migrate_prod1_v13_to_v14"]
