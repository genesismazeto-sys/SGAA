# coding: utf-8
"""The PostgreSQL backup posture the administrator sees (MP-3 SPEC A19).

WHY THIS EXISTS
    On PostgreSQL the database is protected by the operator's governed Layer-2 generations,
    object-byte sets, an off-platform copy and restore drills (``tools/ops_backup.py``,
    ``docs/PG_BACKUP_RESTORE_RUNBOOK.md`` section E); the Free plans add no provider backup.
    Those runs happen on the operator's machine, so without this module the hosted product
    could not say whether the database is protected.  This module is the single owner of the
    posture: the policy (cadence, RPO, retention), the projection the governed runs publish
    into the database they back up, and the reading the Banco de dados page renders.

ONE SOURCE OF TRUTH
    Nothing here decides or records a backup.  The record stays where it is made: the cutover
    ledger's ``backup`` and ``restore`` entries (hash-chained, written only from the receipts of
    governed runs) and, outside the ledger's window, the receipt of an ``ops_backup`` run.  The
    run that made the record publishes the SAME entry, verbatim, into ``sgaa_ops.backup_records``
    of the database it backed up (``publish``).  The page re-derives each entry's own hash and
    shows only intact entries that name THIS database (its live identity, ``app.hosting``); an
    altered, foreign or hand-made row is ignored and counted, never shown as protection.

    The control schema is outside ``public`` (like ``sgaa_cutover``): no Layer-2 set, business
    fingerprint or schema contract includes it, and publishing never changes a business table.

VALUES
    Digests, times, counts and fixed codes only; never a path, host, credential or datum.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from app import hosting

#: UD10 / runbook section E: nightly Layer-2, weekly object set, two generations, off-platform copy.
DEFAULT_CADENCE_HOURS = 24
OBJECT_CADENCE_HOURS = 7 * 24
MIN_GENERATIONS = 2
#: A generation older than this multiple of the cadence is late (the cutover ledger's tolerance).
CADENCE_TOLERANCE = 1.5
RECENT_LIMIT = 5

SCHEMA = "sgaa_ops"
DDL = (
    "CREATE SCHEMA IF NOT EXISTS sgaa_ops",
    "REVOKE ALL ON SCHEMA sgaa_ops FROM PUBLIC",
    "CREATE TABLE IF NOT EXISTS sgaa_ops.backup_records ("
    " entry_hash text PRIMARY KEY, entry_type text NOT NULL, entry text NOT NULL,"
    " annotation text, published_at timestamptz NOT NULL DEFAULT now())",
    "REVOKE ALL ON sgaa_ops.backup_records FROM PUBLIC",
)
EXISTS_SQL = "SELECT to_regclass('sgaa_ops.backup_records') IS NOT NULL"
INSERT_SQL = (
    "INSERT INTO sgaa_ops.backup_records (entry_hash, entry_type, entry, annotation) VALUES (%s, %s, %s, %s)"
    " ON CONFLICT (entry_hash) DO NOTHING"
)
SELECT_SQL = "SELECT entry, annotation FROM sgaa_ops.backup_records"
PUBLISHED_HASHES_SQL = "SELECT entry_hash FROM sgaa_ops.backup_records"

#: Entry types the posture reads: a generation (``backup``) and a restore validation (``restore``).
BACKUP_TYPE = "backup"
RESTORE_TYPE = "restore"
_TYPES = frozenset({BACKUP_TYPE, RESTORE_TYPE})
#: An ``ops_backup`` run outside the ledger's window carries this provenance instead of ``LIVE_RUN``.
RUN_PROVENANCE = "OPERATOR_RUN"


class PostureError(Exception):
    """A record cannot be published (a fixed code; never a value)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# ---------------------------------------------------------------------------
# the projection (written by the run that made the record)
# ---------------------------------------------------------------------------


def run_record(*, generation_at: str, manifest_sha256: str, dump_sha256: str, source_identity_sha256: str,
               object_set_name: str | None, object_set_digest: str | None, object_manifest_sha256: str | None,
               run_seconds: int, at: str) -> dict:
    """The self-hashed receipt of an ``ops_backup`` run outside the ledger's window (same shape as the
    ledger's ``backup`` entry, provenance ``OPERATOR_RUN``, no chain)."""
    body = {
        "type": BACKUP_TYPE, "kind": "GENERATION", "at": at, "generation_at": generation_at,
        "manifest_sha256": manifest_sha256, "dump_sha256": dump_sha256,
        "source_identity_sha256": source_identity_sha256,
        "object_set_name": object_set_name or "NONE", "object_set_digest": object_set_digest or "NONE",
        "object_manifest_sha256": object_manifest_sha256 or "NONE",
        "off_platform": "VERIFIED", "provenance": RUN_PROVENANCE, "run_seconds": int(run_seconds),
    }
    return dict(body, hash=hosting.ledger_entry_hash(body))


def _intact(entry) -> bool:
    if not isinstance(entry, dict) or entry.get("type") not in _TYPES:
        return False
    body = dict(entry)
    claimed = body.pop("hash", None)
    try:
        return isinstance(claimed, str) and hosting.ledger_entry_hash(body) == claimed
    except (TypeError, ValueError):
        return False


def publish(conn, entries, *, annotations: dict | None = None) -> dict:
    """Publish intact ``backup``/``restore`` entries verbatim, once each, in one transaction.

    ``conn`` is a psycopg connection to the database the entries describe (the run's own source).
    ``annotations`` maps an entry hash to the value-free retention the run that made it observed
    (generations kept in each directory); an entry published before keeps what it has.
    Returns ``{"published": n, "already": m}``.
    """
    rows = []
    for entry in entries:
        if not _intact(entry):
            raise PostureError("RECORD_NOT_INTACT")
        rows.append(entry)
    annotations = annotations or {}
    with conn.transaction():
        for statement in DDL:
            conn.execute(statement)
        present = {row[0] for row in conn.execute(PUBLISHED_HASHES_SQL).fetchall()}
        published = 0
        for entry in rows:
            if entry["hash"] in present:
                continue
            text = json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
            note = annotations.get(entry["hash"])
            note = json.dumps(note, sort_keys=True, separators=(",", ":")) if note else None
            conn.execute(INSERT_SQL, (entry["hash"], entry["type"], text, note))
            present.add(entry["hash"])
            published += 1
    return {"published": published, "already": len(rows) - published}


# ---------------------------------------------------------------------------
# the reading (the Banco de dados page)
# ---------------------------------------------------------------------------


def _parse(moment) -> datetime | None:
    try:
        return datetime.strptime(str(moment), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _cadence(cursor, identity) -> tuple[int, str]:
    """The cadence recorded at the opening (the ledger's reference entry in ``sgaa_cutover.opening``,
    naming this database), else the policy default."""
    try:
        if not cursor.execute(hosting.OPENING_EXISTS_SQL).fetchone()[0]:
            return DEFAULT_CADENCE_HOURS, "POLICY"
        for (text,) in cursor.execute("SELECT entry FROM sgaa_cutover.opening").fetchall():
            entry = json.loads(text)
            body = dict(entry)
            claimed = body.pop("hash", None)
            if entry.get("type") == "reference" and hosting.ledger_entry_hash(body) == claimed \
                    and identity and entry.get("database_identity_sha256") == identity:
                hours = entry.get("backup_cadence_hours")
                if isinstance(hours, int) and 1 <= hours <= 24:
                    return hours, "OPENING"
    except (TypeError, ValueError, AttributeError):
        pass
    return DEFAULT_CADENCE_HOURS, "POLICY"


def _status(latest: datetime | None, now: datetime, cadence_hours: int) -> str:
    if latest is None:
        return "NONE"
    age_hours = (now - latest).total_seconds() / 3600
    return "CURRENT" if age_hours <= cadence_hours * CADENCE_TOLERANCE else "LATE"


def read(raw, *, now: datetime | None = None) -> dict:
    """The posture of the database behind ``raw`` (a psycopg connection), value-free.

    Reads in a savepoint so a refusal never disturbs the caller's transaction; any failure is the
    ``UNREADABLE`` posture, never an exception.
    """
    from psycopg.rows import tuple_row

    now = now or datetime.now(timezone.utc)
    try:
        with raw.transaction(), raw.cursor(row_factory=tuple_row) as cursor:
            identity = hosting.source_identity_sha256(hosting.database_source(raw))
            cadence, cadence_source = _cadence(cursor, identity)
            stored = cursor.execute(SELECT_SQL).fetchall() if cursor.execute(EXISTS_SQL).fetchone()[0] else []
        return summarize(stored, identity=identity, cadence_hours=cadence, cadence_source=cadence_source, now=now)
    except Exception:
        return {"state": "UNREADABLE"}


def _count(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 10_000


def _retention(note):
    """The retention a run observed, only in its exact shape (else nothing is claimed)."""
    try:
        value = json.loads(note) if note else None
        kept = value["kept"]
        if set(value) == {"generations_policy", "kept"} and _count(value["generations_policy"]) \
                and set(kept) == {"primary", "off_platform"} \
                and all(set(kept[d]) == {"database", "objects"} and _count(kept[d]["database"])
                        and _count(kept[d]["objects"]) for d in kept):
            return value
    except (TypeError, ValueError, KeyError, AttributeError):
        pass
    return None


def _well_formed(entry) -> bool:
    """The fields the posture reads, in the shapes the tools write (a hand-made row is never shown)."""
    digest = entry.get("manifest_sha256")
    if not (isinstance(digest, str) and len(digest) == 64):
        return False
    if entry["type"] == BACKUP_TYPE:
        return _parse(entry.get("generation_at")) is not None and isinstance(entry.get("object_set_name"), str)
    return _parse(entry.get("at")) is not None and _count(entry.get("tables_verified")) \
        and _count(entry.get("objects_verified"))


def summarize(stored, *, identity, cadence_hours: int, cadence_source: str, now: datetime) -> dict:
    """The posture from the stored ``(entry, annotation)`` rows (pure; the page's reading)."""
    generations, validations, ignored = [], [], 0
    for text, note in stored:
        try:
            entry = json.loads(text)
        except (TypeError, ValueError):
            ignored += 1
            continue
        if not _intact(entry) or not identity or entry.get("source_identity_sha256") != identity \
                or not _well_formed(entry):
            ignored += 1
            continue
        if entry["type"] == BACKUP_TYPE:
            generations.append((_parse(entry["generation_at"]), entry, note))
        else:
            validations.append((_parse(entry["at"]), entry))
    generations.sort(key=lambda item: item[0], reverse=True)
    validations.sort(key=lambda item: item[0], reverse=True)
    with_objects = [g for g in generations if g[1].get("object_set_name") not in (None, "NONE")]
    by_manifest = {g[1]["manifest_sha256"]: g[0] for g in generations}
    latest = generations[0][0] if generations else None
    latest_objects = with_objects[0][0] if with_objects else None
    # Only the newest generation's own observation: an older run's counts are never shown as current.
    retention = _retention(generations[0][2]) if generations else None
    validation = None
    if validations:
        moment, entry = validations[0]
        validation = {
            "at": moment, "generation_at": by_manifest.get(entry.get("manifest_sha256")),
            "tables_verified": int(entry.get("tables_verified") or 0),
            "objects_verified": int(entry.get("objects_verified") or 0),
        }
    return {
        "state": "RECORDED" if generations else "EMPTY",
        "cadence_hours": cadence_hours,
        "cadence_source": cadence_source,
        "rpo_hours": cadence_hours,
        "object_cadence_hours": OBJECT_CADENCE_HOURS,
        "min_generations": MIN_GENERATIONS,
        "database_status": _status(latest, now, cadence_hours),
        "objects_status": _status(latest_objects, now, OBJECT_CADENCE_HOURS),
        "latest_generation_at": latest,
        "latest_object_set_at": latest_objects,
        "validation": validation,
        "retention": retention,
        "recent": [
            {"generation_at": moment, "baseline": entry.get("kind") == "BASELINE",
             "objects": entry.get("object_set_name") not in (None, "NONE"),
             "off_platform": entry.get("off_platform") == "VERIFIED",
             "governed": entry.get("provenance") == "LIVE_RUN",
             "manifest_short": str(entry.get("manifest_sha256") or "")[:12]}
            for moment, entry, _note in generations[:RECENT_LIMIT]
        ],
        "generations_recorded": len(generations),
        "ignored": ignored,
    }


__all__ = [
    "CADENCE_TOLERANCE", "DEFAULT_CADENCE_HOURS", "MIN_GENERATIONS", "OBJECT_CADENCE_HOURS", "PostureError",
    "publish", "read", "run_record", "summarize",
]
