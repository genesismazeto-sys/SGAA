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

THE POLICY THE ADMINISTRATOR SETS
    The backup and retention policy is a product setting the administrator edits on the Banco de
    dados page (``validate_policy`` / ``save_policy``), stored in the product's backup settings
    (``configuracoes_backup``, keys ``pg_*``): how often the database is backed up (its RPO), how
    often the object set is taken, how many generations each directory keeps, how often a restore
    is tested.  ``ops_backup`` reads it from the database it backs up and rotates by it; the posture
    judges every status and due date against it.  While a cutover opening exists the database
    cadence may not exceed the one the opening recorded (the ledger's C14 cadence).

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
from datetime import datetime, timedelta, timezone

from app import hosting

#: UD10 / runbook section E: nightly Layer-2, weekly object set, two generations, off-platform copy.
DEFAULT_CADENCE_HOURS = 24
OBJECT_CADENCE_HOURS = 7 * 24
MIN_GENERATIONS = 2
#: A generation older than this multiple of the cadence is late (the cutover ledger's tolerance).
CADENCE_TOLERANCE = 1.5
RECENT_LIMIT = 5

#: The administrable policy: setting key -> (minimum, maximum, default, label).
POLICY_FIELDS = {
    "pg_backup_cadence_hours": (1, 24, DEFAULT_CADENCE_HOURS, "a frequência do backup do banco (horas)"),
    "pg_object_cadence_days": (1, 7, OBJECT_CADENCE_HOURS // 24, "a frequência dos arquivos do armazenamento (dias)"),
    "pg_retention_generations": (MIN_GENERATIONS, 30, MIN_GENERATIONS, "as gerações mantidas"),
    "pg_restore_test_days": (7, 90, 30, "o intervalo da restauração de teste (dias)"),
}
POLICY_SELECT_SQL = (
    "SELECT chave, valor, atualizado_em FROM configuracoes_backup WHERE chave IN ("
    + ", ".join(f"'{key}'" for key in POLICY_FIELDS) + ")"
)

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


class PolicyError(ValueError):
    """A policy value the administrator typed is refused (the message is shown as is)."""


class PostureError(Exception):
    """A record cannot be published (a fixed code; never a value)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# ---------------------------------------------------------------------------
# the policy (set by the administrator, read by the runs and the page)
# ---------------------------------------------------------------------------


def default_policy() -> dict:
    return {key: spec[2] for key, spec in POLICY_FIELDS.items()}


def _bounded(key, raw):
    minimum, maximum, _default, _label = POLICY_FIELDS[key]
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return value if minimum <= value <= maximum else None


def policy_from_rows(rows) -> dict:
    """The policy from stored ``(chave, valor, atualizado_em)`` rows: any value missing or out of bounds
    is its default; ``configured`` and ``updated_at`` (the newest change, as stored) are added."""
    policy, updated, configured = default_policy(), None, False
    for row in rows:
        key, raw, changed = row[0], row[1], row[2]
        value = _bounded(key, raw) if key in POLICY_FIELDS else None
        if value is not None:
            policy[key], configured = value, True
            if changed and (updated is None or str(changed) > updated):
                updated = str(changed)
    return dict(policy, configured=configured, updated_at=updated)


def read_policy(raw) -> dict:
    """The stored policy of the database behind ``raw`` (a psycopg connection), read in a savepoint:
    a database without the settings table, or any refusal, yields the defaults and never disturbs the
    caller's transaction."""
    from psycopg.rows import tuple_row

    try:
        with raw.transaction(), raw.cursor(row_factory=tuple_row) as cursor:
            rows = cursor.execute(POLICY_SELECT_SQL).fetchall()
    except Exception:
        rows = []
    return policy_from_rows(rows)


def validate_policy(form, *, ceiling_hours: int | None = None) -> dict:
    """The administrator's form, validated: every field an integer within its bounds, and the database
    cadence not above the ceiling an open cutover recorded.  Raises ``PolicyError`` (shown as is)."""
    policy = {}
    for key, (minimum, maximum, _default, label) in POLICY_FIELDS.items():
        value = _bounded(key, form.get(key))
        if value is None:
            raise PolicyError(f"Valor inválido para {label}: informe um número inteiro de {minimum} a {maximum}.")
        policy[key] = value
    if ceiling_hours is not None and policy["pg_backup_cadence_hours"] > ceiling_hours:
        raise PolicyError(
            f"A frequência do backup do banco não pode passar de {ceiling_hours} h enquanto a janela da virada estiver aberta."
        )
    return policy


def save_policy(conn, policy: dict) -> None:
    """Store a validated policy in the product's backup settings (the caller commits)."""
    from app.sql_dialect import current_utc_text

    for key in POLICY_FIELDS:
        conn.execute(
            f"INSERT INTO configuracoes_backup (chave, valor, atualizado_em) VALUES (?, ?, {current_utc_text(conn)})"
            f" ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor, atualizado_em = {current_utc_text(conn)}",
            (key, str(int(policy[key]))),
        )


def opening_ceiling(raw) -> int | None:
    """The database cadence an open cutover recorded for THIS database, else ``None`` (a psycopg connection)."""
    from psycopg.rows import tuple_row

    try:
        with raw.transaction(), raw.cursor(row_factory=tuple_row) as cursor:
            identity = hosting.source_identity_sha256(hosting.database_source(raw))
            hours, source = _cadence(cursor, identity)
    except Exception:
        return None
    return hours if source == "OPENING" else None


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
            ceiling, ceiling_source = _cadence(cursor, identity)
            stored = cursor.execute(SELECT_SQL).fetchall() if cursor.execute(EXISTS_SQL).fetchone()[0] else []
        policy = read_policy(raw)
        return summarize(stored, identity=identity, policy=policy,
                         ceiling_hours=ceiling if ceiling_source == "OPENING" else None, now=now)
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


def _due(moment, hours):
    return moment + timedelta(hours=hours) if moment is not None else None


def summarize(stored, *, identity, policy: dict | None = None, ceiling_hours: int | None = None,
              now: datetime) -> dict:
    """The posture from the stored ``(entry, annotation)`` rows, judged against the administrator's
    policy (pure; the page's reading).  An open cutover's recorded cadence is a ceiling."""
    policy = dict(default_policy(), **(policy or {}))
    cadence_hours = policy["pg_backup_cadence_hours"]
    if ceiling_hours is not None and ceiling_hours < cadence_hours:
        cadence_hours = ceiling_hours
    object_hours = policy["pg_object_cadence_days"] * 24
    restore_hours = policy["pg_restore_test_days"] * 24
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
        "policy": policy,
        "ceiling_hours": ceiling_hours,
        "cadence_hours": cadence_hours,
        "rpo_hours": cadence_hours,
        "object_cadence_hours": object_hours,
        "restore_test_days": policy["pg_restore_test_days"],
        "retention_generations": policy["pg_retention_generations"],
        "min_generations": MIN_GENERATIONS,
        "database_status": _status(latest, now, cadence_hours),
        "objects_status": _status(latest_objects, now, object_hours),
        "validation_status": "NONE" if validation is None else (
            "CURRENT" if (now - validation["at"]).total_seconds() <= restore_hours * 3600 else "LATE"),
        "latest_generation_at": latest,
        "latest_object_set_at": latest_objects,
        "next_generation_due": _due(latest, cadence_hours),
        "next_object_set_due": _due(latest_objects, object_hours),
        "next_restore_test_due": _due(validation["at"] if validation else None, restore_hours),
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
    "CADENCE_TOLERANCE", "DEFAULT_CADENCE_HOURS", "MIN_GENERATIONS", "OBJECT_CADENCE_HOURS", "POLICY_FIELDS",
    "PolicyError", "PostureError", "default_policy", "opening_ceiling", "policy_from_rows", "publish", "read",
    "read_policy",
    "run_record", "save_policy", "summarize", "validate_policy",
]
