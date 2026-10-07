"""prod-1 v12 -> v13: database-backed application images.

WHAT CHANGES
    Three new, empty one-to-one side tables -- ``usuarios_foto``,
    ``alunos_foto`` and ``reportes_captura`` -- see ``app.prod1_images_ddl``.
    From v13 on, a new profile photo or report screenshot is stored as a row
    there, never as a file under an upload root.

WHAT DOES NOT CHANGE
    Every existing table, row, index, trigger and AUTOINCREMENT counter. The
    legacy path columns (``usuarios.foto_perfil``, ``alunos.foto_perfil``,
    ``reportes.screenshot_filename``) keep their values: files they reference
    are still served through the narrowly scoped legacy fallback until the
    one-shot importer (``python -m app.image_import``) moves them into the new
    tables. Nothing is backfilled here.

HOW
    Purely additive: ``CREATE TABLE`` x3 from the same statements the
    bootstrap executes, the marker row and ``user_version``, then every
    pre-existing table's rows, the counters, ``integrity_check``,
    ``foreign_key_check`` and the head digest are checked before COMMIT.
"""

from __future__ import annotations

import hashlib
import sqlite3

from app.prod1_images_ddl import IMAGES_V13_TABLE_SQL, IMAGES_V13_TABLES


_V13_DETAILS_JSON = (
    '{"schema_epoch":"prod-1","image_storage":"database",'
    '"tables":["usuarios_foto","alunos_foto","reportes_captura"],'
    '"legacy_columns":["usuarios.foto_perfil","alunos.foto_perfil","reportes.screenshot_filename"],'
    '"backfill":"none_one_shot_importer"}'
)


def _table_names(conn: sqlite3.Connection) -> list[str]:
    return sorted(
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM main.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    )


def _data_digest(conn: sqlite3.Connection, tables: list[str]) -> dict[str, tuple[int, str]]:
    """``{table: (rows, sha256)}`` over every row of the given tables, in rowid order."""
    digests = {}
    for table in tables:
        digest = hashlib.sha256()
        count = 0
        for row in conn.execute(f'SELECT * FROM main."{table}" ORDER BY rowid').fetchall():
            digest.update(repr(tuple(row)).encode("utf-8"))
            digest.update(b"\n")
            count += 1
        digests[table] = (count, digest.hexdigest())
    return digests


def _sequences(conn: sqlite3.Connection) -> list[tuple]:
    return [tuple(row) for row in conn.execute("SELECT name,seq FROM main.sqlite_sequence ORDER BY name")]


def migrate_prod1_v12_to_v13(conn: sqlite3.Connection) -> dict[str, object]:
    from app.prod1_schema import (
        IMAGE_STORAGE_MARKER,
        SCHEMA_EPOCH,
        Prod1SchemaError,
        _validate_prod1_v12_schema,
        validate_prod1_schema,
    )

    if conn.in_transaction:
        raise Prod1SchemaError("prod-1/v13 migration requires a clean connection")
    _validate_prod1_v12_schema(conn)

    try:
        conn.execute("BEGIN IMMEDIATE")
        existing = [name for name in _table_names(conn) if name != "schema_migrations"]
        if set(existing) & set(IMAGES_V13_TABLES):
            raise Prod1SchemaError("prod-1/v13 image tables already exist on a v12 database")
        data_before = _data_digest(conn, existing)
        sequences_before = _sequences(conn)

        for statement in IMAGES_V13_TABLE_SQL:
            conn.execute(statement)
        conn.execute(
            "INSERT INTO schema_migrations(version,name,schema_epoch,details_json)"
            " VALUES(?,?,?,?)",
            (13, IMAGE_STORAGE_MARKER, SCHEMA_EPOCH, _V13_DETAILS_JSON),
        )
        conn.execute("PRAGMA user_version=13")

        if _data_digest(conn, existing) != data_before:
            raise Prod1SchemaError("prod-1/v13 migration changed existing rows")
        if _sequences(conn) != sequences_before:
            raise Prod1SchemaError("prod-1/v13 migration changed AUTOINCREMENT counters")
        for table in IMAGES_V13_TABLES:
            if conn.execute(f"SELECT count(*) FROM main.{table}").fetchone()[0]:
                raise Prod1SchemaError(f"prod-1/v13 migration backfilled {table}")
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise Prod1SchemaError("prod-1/v13 integrity check failed")
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise Prod1SchemaError(f"prod-1/v13 foreign key violations: {violations!r}")
        validate_prod1_schema(conn)
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise

    status = validate_prod1_schema(conn)
    return {
        **status,
        "image_storage": "database",
        "rows_preserved": {table: rows for table, (rows, _digest) in data_before.items()},
    }


__all__ = ["migrate_prod1_v12_to_v13"]
