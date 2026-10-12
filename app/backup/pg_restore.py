# coding: utf-8
""""Recuperar banco de dados" under PostgreSQL: replace the registers with a snapshot (MP-3 A19).

WHY THIS EXISTS
    The product's restore replaced the database with a chosen snapshot after saving a safety copy.
    Under PostgreSQL the page refused it.  This module restores the capability for the hosted
    database: the snapshot (the product's own format, a schema-v16 SQLite file -- what "Gerar backup
    agora" writes) is verified by the qualified Path-B reader (``app.pg_migrate_from_sqlite``:
    version, integrity, foreign keys, the exact table and column contract, the storage
    preconditions), then, in ONE transaction holding every register table exclusively, the
    registers are replaced and proven equal to the file row by row, with the domain checks clean.
    Anything that does not prove rolls the whole transaction back: the database is then exactly as
    it was.

WHAT IT REPLACES
    The registers (Path-B's ``MIGRATE_EXACT`` tables) and the short-lived state that points at them
    (single-use links, upload intents, throttle windows, import previews), which is cleared.  The
    installation's own configuration -- the connected cloud accounts, the backup settings, the
    destination folders, the schema record -- is kept: it belongs to this installation, not to the
    snapshot.  Identity counters never move back: an id issued after the snapshot is never issued
    again.

The caller makes the safety copy first (``app.views.admin.banco_dados``); this module never runs
without one being sent.
"""
from __future__ import annotations

import hashlib
from types import SimpleNamespace

from app import pg_migrate_from_sqlite as pathb


class RestoreError(Exception):
    """The snapshot cannot be restored; nothing was changed (``message`` is shown to the administrator)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _sha256(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tables():
    order = pathb.load_order()
    registers = [t for t in order if pathb.SOURCE_TABLE_POLICIES[t].policy == pathb.MIGRATE_EXACT]
    cleared = [t for t in order if pathb.SOURCE_TABLE_POLICIES[t].policy in (pathb.MIGRATE_EXACT,
                                                                              pathb.OMIT_EPHEMERAL)]
    return registers, cleared


def read(path):
    """The verified snapshot (Path-B's reader), or ``RestoreError``."""
    try:
        return pathb.read_source(str(path), _sha256(path))
    except pathb.MigrationRefused as refusal:
        raise RestoreError(refusal.code, "o arquivo não é um backup do banco do SGAA válido "
                                         f"({refusal.code}).") from None
    except Exception:
        raise RestoreError("SNAPSHOT_UNREADABLE", "o arquivo não pôde ser lido como backup do banco.") from None


def restore(snapshot, *, connect=None) -> dict:
    """Replace the registers with ``snapshot`` (from ``read``) in one transaction, proven, or change nothing."""
    from app.backup import pg_snapshot

    registers, cleared = _tables()
    conn = (connect or pg_snapshot._application_connection)()
    conn.autocommit = True
    report = SimpleNamespace(self_references_restored={})
    try:
        with conn.transaction():
            conn.execute("SET LOCAL lock_timeout = '15s'")
            for table in cleared:  # nothing else reads or writes them until the commit
                conn.execute(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE")
            next_ids = {table: pathb.next_identity_value(conn, table)
                        for table in registers if pathb._identity_column(table)}
            for table in reversed(cleared):
                conn.execute(f"DELETE FROM {table}")
            for table in registers:
                pathb._load_table(conn, table, snapshot.rows[table], report)
            for table, issued_next in next_ids.items():
                column = pathb._identity_column(table)
                position = pathb._columns(table).index(column)
                high = max([snapshot.sequences.get(table, 0)]
                           + [int(row[position]) for row in snapshot.rows[table]])
                conn.execute(f"ALTER TABLE {table} ALTER COLUMN {column} RESTART WITH {max(issued_next, high + 1)}")
            for table in registers:
                written = pathb.normalize_rows(table, pathb.read_target_rows(conn, table))
                if pathb.compare_rows(table, pathb.normalize_rows(table, snapshot.rows[table]), written):
                    raise RestoreError("RESTORE_TABLE_DIFFERS",
                                       f"a tabela {table} não ficou igual ao backup; nada foi alterado.")
            broken = sorted(name for name, count in pathb.run_domain_checks(conn).items() if count)
            if broken:
                raise RestoreError("RESTORE_DOMAIN_CHECK_FAILED",
                                   f"o backup não passou nas verificações do domínio ({', '.join(broken)}); "
                                   "nada foi alterado.")
    except RestoreError:
        raise
    except Exception as exc:
        raise RestoreError(type(exc).__name__.upper(),
                           "a recuperação foi desfeita por um erro do banco; nada foi alterado.") from None
    finally:
        conn.close()
    return {"tables": len(registers), "rows": sum(len(snapshot.rows[t]) for t in registers)}


__all__ = ["RestoreError", "read", "restore"]
