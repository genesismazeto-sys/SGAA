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
    (single-use links, upload intents, throttle windows, import previews, the legacy backup log), which
    is cleared.  The
    installation's own configuration -- the connected cloud accounts, the backup settings, the
    destination folders, the schema record -- is kept: it belongs to this installation, not to the
    snapshot.  Identity counters never move back: an id issued after the snapshot is never issued
    again.

The safety copy is made INSIDE the restore's window (``before``): the register tables are first
locked against every write (EXCLUSIVE: reads go on), then the caller's ``before`` makes and sends the
copy of the current database -- which therefore holds every write that will ever precede the
replacement -- and only if it reached a drive is the lock raised to ACCESS EXCLUSIVE and the registers
replaced.  No write can fall between the copy and the replacement (A19 R3 M3).
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


def read(path, *, expected_sha256: str | None = None):
    """The verified snapshot (Path-B's reader), or ``RestoreError``.

    ``expected_sha256`` is the generation the administrator chose: a file that is not exactly it
    (a partial download, a file revised on the drive) is refused.
    """
    try:
        actual = _sha256(path)
    except OSError:
        raise RestoreError("SNAPSHOT_UNREADABLE", "o arquivo não pôde ser lido como backup do banco.") from None
    if expected_sha256 is not None and actual != expected_sha256:
        raise RestoreError("SNAPSHOT_NOT_THE_GENERATION",
                           "o arquivo obtido não corresponde ao backup selecionado; nada foi alterado.")
    try:
        return pathb.read_source(str(path), actual, storage_preconditions=False)
    except pathb.MigrationRefused as refusal:
        raise RestoreError(refusal.code, "o arquivo não é um backup do banco do SGAA válido "
                                         f"({refusal.code}).") from None
    except Exception:
        raise RestoreError("SNAPSHOT_UNREADABLE", "o arquivo não pôde ser lido como backup do banco.") from None


def restore(snapshot, *, before, connect=None) -> dict:
    """Replace the registers with ``snapshot`` (from ``read``) in one transaction, proven, or change nothing.

    ``before()`` runs once the registers are locked against writes and must return truthy when the
    safety copy of the current database reached at least one drive; otherwise nothing is changed.
    """
    from app.backup import pg_snapshot

    registers, cleared = _tables()
    try:
        conn = (connect or pg_snapshot._application_connection)()
        conn.autocommit = True
    except Exception:
        raise RestoreError("DATABASE_UNREACHABLE", "o banco não pôde ser aberto para a recuperação; nada foi alterado.") from None
    report = SimpleNamespace(self_references_restored={})
    try:
        with conn.transaction():
            # bounded: a request the platform stops never leaves the registers locked for long (the
            # idle bound covers the safety copy's upload, inside the function's own time limit)
            conn.execute("SET LOCAL lock_timeout = '10s'")
            conn.execute("SET LOCAL statement_timeout = '30s'")
            conn.execute("SET LOCAL idle_in_transaction_session_timeout = '55s'")
            # 1. no write from here on (reads go on: the safety copy reads them)
            conn.execute(f"LOCK TABLE {', '.join(cleared)} IN EXCLUSIVE MODE")
            if not before():
                raise RestoreError("SAFETY_COPY_NOT_SENT",
                                   "a cópia de segurança da base atual não pôde ser enviada para nenhuma conta em "
                                   "nuvem; nada foi alterado.")
            # 2. nothing else reads or writes them until the commit
            conn.execute(f"LOCK TABLE {', '.join(cleared)} IN ACCESS EXCLUSIVE MODE")
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
