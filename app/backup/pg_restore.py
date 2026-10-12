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

THE COMMIT MARKER
    The same transaction writes one self-hashed marker into ``sgaa_ops.restore_operations`` (the
    control schema outside ``public``, ``app.backup.pg_posture``): the operation, this database, the
    file restored, the safety copy's digest and the completion time.  It exists exactly when the
    replacement committed.  It is what proves a restore happened (the cutover ledger records an
    unchanged-fingerprint point of no return only on it), and it resolves a COMMIT whose answer was
    lost: a fresh connection waits for the restore's transaction to end and reads whether its marker
    is there -- committed, rolled back, or, when even that cannot be read, uncertain, which is never
    reported as "nothing changed".
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from types import SimpleNamespace

from app import hosting
from app import pg_migrate_from_sqlite as pathb
from app.backup import pg_posture

MARKER_TYPE = "admin_restore"
MARKER_DDL = (
    *pg_posture.SCHEMA_DDL,
    "CREATE TABLE IF NOT EXISTS sgaa_ops.restore_operations ("
    " operation_id text PRIMARY KEY, entry_hash text NOT NULL UNIQUE, entry text NOT NULL,"
    " recorded_at timestamptz NOT NULL DEFAULT clock_timestamp())",
    "REVOKE ALL ON sgaa_ops.restore_operations FROM PUBLIC",
)
MARKER_EXISTS_SQL = "SELECT to_regclass('sgaa_ops.restore_operations') IS NOT NULL"
MARKER_SELECT_SQL = "SELECT entry FROM sgaa_ops.restore_operations"
MARKER_BY_OPERATION_SQL = "SELECT entry FROM sgaa_ops.restore_operations WHERE operation_id = %s"
MARKER_BY_HASH_SQL = "SELECT entry FROM sgaa_ops.restore_operations WHERE entry_hash = %s"
_MARKER_INSERT_SQL = "INSERT INTO sgaa_ops.restore_operations (operation_id, entry_hash, entry) VALUES (%s, %s, %s)"
_UTC_NOW_SQL = "SELECT to_char(clock_timestamp() AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"')"
#: Longer than the restore's own idle bound (55 s): a transaction still open is waited for, never guessed.
RESOLVE_LOCK_SECONDS = 60
_HEX64 = re.compile(r"[0-9a-f]{64}")
_STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")

_ROLLED_BACK = "a recuperação foi desfeita por um erro do banco; nada foi alterado."
_UNCERTAIN = ("não foi possível confirmar se a recuperação foi aplicada, porque a resposta do banco se perdeu. "
              "Não repita a recuperação antes de conferir os dados atuais.")


#: The one code that does not mean "nothing was changed": the restore may have committed.
OUTCOME_UNCERTAIN = "RESTORE_OUTCOME_UNCERTAIN"


class RestoreError(Exception):
    """The snapshot was not restored (``message`` is shown to the administrator).  Every code means nothing
    was changed, except ``OUTCOME_UNCERTAIN``: the outcome could not be established (``operation_id`` then
    names the operation whose marker decides it)."""

    def __init__(self, code: str, message: str, *, operation_id: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.operation_id = operation_id


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


def marker_entry(*, operation_id: str, source_identity_sha256: str, restored_sha256: str,
                 safety_copy_manifest_sha256: str, completed_at: str, tables: int, rows: int) -> dict:
    """The self-hashed commit marker of one restore (value-free: digests, a stamp, counts)."""
    body = {"type": MARKER_TYPE, "operation_id": operation_id, "source_identity_sha256": source_identity_sha256,
            "restored_sha256": restored_sha256, "safety_copy_manifest_sha256": safety_copy_manifest_sha256,
            "completed_at": completed_at, "tables": int(tables), "rows": int(rows)}
    return dict(body, hash=hosting.ledger_entry_hash(body))


def marker_intact(entry) -> bool:
    """A marker in exactly the shape ``marker_entry`` writes, whose hash re-derives."""
    if not isinstance(entry, dict) or entry.get("type") != MARKER_TYPE:
        return False
    body = dict(entry)
    claimed = body.pop("hash", None)
    shapes = (set(body) == {"type", "operation_id", "source_identity_sha256", "restored_sha256",
                            "safety_copy_manifest_sha256", "completed_at", "tables", "rows"}
              and isinstance(body["operation_id"], str) and bool(re.fullmatch(r"[0-9a-f]{32}", body["operation_id"]))
              and all(isinstance(body[key], str) and _HEX64.fullmatch(body[key])
                      for key in ("source_identity_sha256", "restored_sha256", "safety_copy_manifest_sha256"))
              and isinstance(body["completed_at"], str) and bool(_STAMP.fullmatch(body["completed_at"]))
              and all(isinstance(body[key], int) and not isinstance(body[key], bool) and body[key] >= 0
                      for key in ("tables", "rows")))
    try:
        return shapes and isinstance(claimed, str) and hosting.ledger_entry_hash(body) == claimed
    except (TypeError, ValueError):
        return False


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

    ``before()`` runs once the registers are locked against writes and returns the SHA-256 of the safety
    copy of the current database once it reached at least one drive (and its receipt was recorded);
    anything else changes nothing.  Returns ``{"tables", "rows", "operation_id", "marker_sha256",
    "outcome"}``: ``outcome`` is ``COMMITTED``, or ``COMMITTED_CONFIRMED`` when the COMMIT's answer was
    lost and the marker proved it.
    """
    from app.backup import pg_snapshot

    registers, cleared = _tables()
    connect = connect or pg_snapshot._application_connection
    operation_id = secrets.token_hex(16)
    try:
        conn = connect()
        conn.autocommit = True
    except Exception:
        raise RestoreError("DATABASE_UNREACHABLE", "o banco não pôde ser aberto para a recuperação; nada foi alterado.") from None
    report = SimpleNamespace(self_references_restored={})
    committing, outcome = False, "COMMITTED"
    try:
        # the marker's table first, in its own short transaction: the restore's own transaction only inserts
        with conn.transaction():
            for statement in MARKER_DDL:
                conn.execute(statement)
        with conn.transaction():
            # bounded: a request the platform stops never leaves the registers locked for long (the
            # idle bound covers the safety copy's upload, inside the function's own time limit)
            conn.execute("SET LOCAL lock_timeout = '10s'")
            conn.execute("SET LOCAL statement_timeout = '30s'")
            conn.execute("SET LOCAL idle_in_transaction_session_timeout = '55s'")
            # 1. no write from here on (reads go on: the safety copy reads them)
            conn.execute(f"LOCK TABLE {', '.join(cleared)} IN EXCLUSIVE MODE")
            safety = before()
            if not (isinstance(safety, str) and _HEX64.fullmatch(safety)):
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
            identity = hosting.source_identity_sha256(hosting.database_source(conn))
            if identity is None:
                raise RestoreError("DATABASE_IDENTITY_UNPROVEN", "o banco não pôde ser identificado; nada foi alterado.")
            marker = marker_entry(operation_id=operation_id, source_identity_sha256=identity,
                                  restored_sha256=snapshot.sha256, safety_copy_manifest_sha256=safety,
                                  completed_at=conn.execute(_UTC_NOW_SQL).fetchone()[0], tables=len(registers),
                                  rows=sum(len(snapshot.rows[t]) for t in registers))
            conn.execute(_MARKER_INSERT_SQL, (operation_id, marker["hash"],
                                              json.dumps(marker, sort_keys=True, separators=(",", ":"))))
            committing = True  # leaving the block sends COMMIT: from here on the outcome is PostgreSQL's
    except RestoreError:
        raise
    except Exception as exc:
        if not committing:  # no COMMIT was sent: PostgreSQL never commits such a transaction
            raise RestoreError(type(exc).__name__.upper(), _ROLLED_BACK) from None
        found = _committed_marker(connect, operation_id, cleared[0])
        if found is None:
            raise RestoreError("RESTORE_ROLLED_BACK", _ROLLED_BACK) from None
        if found["hash"] != marker["hash"]:
            raise RestoreError(OUTCOME_UNCERTAIN, _UNCERTAIN, operation_id=operation_id) from None
        outcome = "COMMITTED_CONFIRMED"
    finally:
        conn.close()
    return {"tables": marker["tables"], "rows": marker["rows"], "operation_id": operation_id,
            "marker_sha256": marker["hash"], "outcome": outcome}


def _committed_marker(connect, operation_id: str, locked_table: str):
    """After a COMMIT whose answer was lost: wait, on a fresh connection, until the restore's transaction
    has ended (its ACCESS EXCLUSIVE lock on ``locked_table`` is released whatever the outcome), then read
    its marker.  ``None``: it rolled back.  Anything that cannot be read is ``RESTORE_OUTCOME_UNCERTAIN``."""
    try:
        fresh = connect()
        fresh.autocommit = True
    except Exception:
        raise RestoreError(OUTCOME_UNCERTAIN, _UNCERTAIN, operation_id=operation_id) from None
    try:
        with fresh.transaction():
            fresh.execute(f"SET LOCAL lock_timeout = '{RESOLVE_LOCK_SECONDS}s'")
            fresh.execute(f"LOCK TABLE {locked_table} IN ACCESS SHARE MODE")
            row = None
            if fresh.execute(MARKER_EXISTS_SQL).fetchone()[0]:
                row = fresh.execute(MARKER_BY_OPERATION_SQL, (operation_id,)).fetchone()
    except Exception:
        raise RestoreError(OUTCOME_UNCERTAIN, _UNCERTAIN, operation_id=operation_id) from None
    finally:
        fresh.close()
    if row is None:
        return None
    try:
        entry = json.loads(row[0])
    except (TypeError, ValueError):
        entry = None
    if not marker_intact(entry):
        raise RestoreError(OUTCOME_UNCERTAIN, _UNCERTAIN, operation_id=operation_id)
    return entry


__all__ = ["MARKER_BY_HASH_SQL", "MARKER_EXISTS_SQL", "MARKER_SELECT_SQL", "MARKER_TYPE", "OUTCOME_UNCERTAIN",
           "RestoreError",
           "marker_entry", "marker_intact", "read", "restore"]
