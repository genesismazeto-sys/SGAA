# coding: utf-8
""""Gerar backup agora" under PostgreSQL: a verified snapshot sent to the connected cloud drives (MP-3 A19).

WHY THIS EXISTS
    The product's manual backup took a consistent snapshot of the database, sent it to the
    connected Google Drive / OneDrive folder and applied retention there.  Under PostgreSQL the
    page refused it.  This module restores the same capability for the hosted database without a
    native client: it copies every application table, inside ONE repeatable-read read-only
    transaction, into a file in the product's own snapshot format (a schema-v16 SQLite database,
    ``app.prod1_schema``), and proves the copy table by table with the cutover's own row digests
    (``app.pg_migrate_from_sqlite``: the same normalization the PONR fingerprint uses).  The file is
    what the workstation runtime restores directly, and what the qualified Path-B tool loads into
    an empty PostgreSQL.

    It is not the operator's governed Layer-2 generation (``tools/ops_backup.py``), which stays the
    cutover's counted backup; it is the administrator's on-demand copy, recorded in the same posture.

SAFETY
    Read-only on the database.  In the cloud folder it only ever deletes files whose name starts
    with ``SNAPSHOT_PREFIX`` (the legacy SQLite backups that may share the folder are never touched),
    keeping the newest ``keep`` of them.
"""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app import hosting
from app import pg_migrate_from_sqlite as pathb
from app import prod1_schema

SNAPSHOT_PREFIX = "sgaa-pg-snapshot-"
SNAPSHOT_SUFFIX = ".db"
#: Exactly the names ``create`` writes: a renamed or hand-made copy is never pruned.
SNAPSHOT_NAME = re.compile(r"sgaa-pg-snapshot-\d{8}T\d{6}Z\.db")


class SnapshotError(Exception):
    """The snapshot could not be made or proven (a fixed code; never a value)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sqlite_value(value):
    return bytes(value) if isinstance(value, memoryview) else value


def _application_connection():
    """A new connection to the application's PostgreSQL database, from the one owner of its address."""
    from app import db as app_db

    return app_db._connect_postgres().raw_connection


def _autoincrement(lite, table) -> bool:
    row = lite.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone()
    return bool(row and "AUTOINCREMENT" in str(row[0]).upper())


def create(directory, *, now: datetime | None = None, connect=None) -> dict:
    """Write and prove a snapshot of the application's PostgreSQL database in ``directory``.

    ``connect()`` returns a new psycopg connection (default: the application's own, ``app.db``).

    Returns ``{"path", "file_name", "sha256", "size", "generation_at", "tables", "rows",
    "source_identity_sha256"}``; raises ``SnapshotError`` when the copy cannot be proven equal.
    """
    now = now or datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    path = Path(directory) / f"{SNAPSHOT_PREFIX}{stamp}{SNAPSHOT_SUFFIX}"
    if path.exists():
        raise SnapshotError("SNAPSHOT_EXISTS")
    source = (connect or _application_connection)()
    source.autocommit = True  # the snapshot is one explicit repeatable-read, read-only transaction
    lite = sqlite3.connect(str(path))
    try:
        lite.executescript(prod1_schema.PROD1_SCHEMA_SQL)
        lite.execute("PRAGMA foreign_keys = OFF")
        tables = pathb.load_order()
        source.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
        try:
            identity = hosting.source_identity_sha256(hosting.database_source(source))
            copied = {}
            for table in tables:
                rows = [tuple(_sqlite_value(v) for v in row) for row in pathb.read_target_rows(source, table)]
                columns = pathb._columns(table)
                lite.execute(f"DELETE FROM {table}")  # the schema script seeds some tables
                if rows:
                    marks = ", ".join("?" for _ in columns)
                    lite.executemany(f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({marks})", rows)
                copied[table] = rows
            # The next-id counters travel too: a restore never re-issues the id of a deleted row.
            for table in tables:
                column = pathb._identity_column(table)
                if column is None:
                    continue
                sequence = source.execute("SELECT pg_get_serial_sequence(%s, %s)", (table, column)).fetchone()[0]
                if not sequence:
                    continue
                last, called = source.execute(f"SELECT last_value, is_called FROM {sequence}").fetchone()
                issued = int(last) if called else int(last) - 1
                if lite.execute("SELECT 1 FROM sqlite_sequence WHERE name = ?", (table,)).fetchone():
                    lite.execute("UPDATE sqlite_sequence SET seq = max(seq, ?) WHERE name = ?", (issued, table))
                elif issued > 0 and _autoincrement(lite, table):
                    lite.execute("INSERT INTO sqlite_sequence(name, seq) VALUES (?, ?)", (table, issued))
        finally:
            source.execute("ROLLBACK")
        lite.commit()
        # The proof: every table of the file equals the snapshot it was copied from, row by row.
        for table, rows in copied.items():
            written = pathb.read_target_rows(lite, table)
            if pathb.table_digest(table, pathb.normalize_rows(table, written)) != \
                    pathb.table_digest(table, pathb.normalize_rows(table, rows)):
                raise SnapshotError("SNAPSHOT_TABLE_DIFFERS")
        if lite.execute("PRAGMA foreign_key_check").fetchall():
            raise SnapshotError("SNAPSHOT_FOREIGN_KEYS")
        if lite.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise SnapshotError("SNAPSHOT_INTEGRITY")
        if int(lite.execute("PRAGMA user_version").fetchone()[0]) != 16:
            raise SnapshotError("SNAPSHOT_VERSION")
    except BaseException:
        lite.close()
        path.unlink(missing_ok=True)
        raise
    finally:
        source.close()
    lite.close()
    if identity is None:
        path.unlink(missing_ok=True)
        raise SnapshotError("DATABASE_IDENTITY_UNPROVEN")
    return {
        "path": str(path), "file_name": path.name, "sha256": _sha256(path), "size": os.path.getsize(path),
        "generation_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "tables": len(copied),
        "rows": sum(len(rows) for rows in copied.values()), "source_identity_sha256": identity,
    }


def prune(listed: list[dict], keep: int, delete) -> list[str]:
    """Delete all but the newest ``keep`` snapshots among ``listed`` (``{"id", "name", "_ts"}``).

    Only names carrying ``SNAPSHOT_PREFIX`` are candidates; anything else in the folder is never
    deleted.  The newest is decided by the stamp in the name (the provider's dates are ignored).
    """
    ours = sorted((item for item in listed
                   if SNAPSHOT_NAME.fullmatch(str(item.get("name") or "")) and item.get("id")),
                  key=lambda item: item["name"], reverse=True)
    removed = []
    for item in ours[max(int(keep), 1):]:
        delete(item["id"])
        removed.append(item["name"])
    return removed


__all__ = ["SNAPSHOT_NAME", "SNAPSHOT_PREFIX", "SnapshotError", "create", "prune"]
