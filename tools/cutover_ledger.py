# coding: utf-8
"""Cutover evidence ledger -- operator tool, never imported by ``app/``.

WHY THIS EXISTS
    The production cutover is a sequence of gated, partly irreversible states
    (``docs/specs/MP-3-production-integration.md`` section 3.3).  This tool is
    its memory and its referee, not its hands: it validates that a state may
    be entered, that the evidence for it is complete and VALUE-FREE, that every
    gate it needs was granted, and that the identities carried from state to
    state (frozen source, prepared copy, reference digest, deployed commit,
    opening fingerprint) never change.  It writes nothing but its own file.
    Where the SPEC forbids trusting the operator's word (the opening, a
    rollback from it, the backups that must exist before and after it) the
    ledger OBSERVES for itself, read-only: the public address without any
    credential (``tools/hosted_smoke`` probes), the database in one read-only
    snapshot (``tools/pg_fingerprint``) and the backup directories
    (``tools/ops_backup.verify_generation``).

WHAT IT STORES
    One append-only JSON-lines file, ``ledger.jsonl``, in a directory outside
    the repository.  Every entry carries the SHA-256 of the previous entry, so
    an edited, reordered or removed entry breaks the chain.  The chain is an
    integrity check against accident, not authenticity: it cannot detect the
    removal of the LAST entries, so every command prints the new ``head`` and
    every later command takes ``--expect-head`` (the runbook makes it
    mandatory): a truncated tail is then refused.  Entries hold counts,
    classes, digests and fixed codes only; any other value is refused before
    it is written.  A grant is the operator's record of the user's message: the
    ledger cannot verify the user.

COMMANDS
    init           create the ledger (the directory must not hold one)
    grant          record that the user granted a gate (an opaque reference only)
    advance        enter the next state with its evidence (never C12: see ``open``)
    record-backup  verify the newest backup generation from disk and record it once,
                   by its own creation time (C11 onward; ``ops_backup --ledger-dir``
                   calls it after every run)
    reference      at C11, with GO granted, once: observe at C10's public address
                   that admission is CLOSED, prove the pre-opening backup (made after
                   C11) current against the live database, take the reference
                   fingerprint live, write it out and print its digest
    open           observe that admission is OPEN at that address and that the
                   deployment announces the tag of THAT reference entry's hash (it was
                   lifted with SGAA_OPENING_REFERENCE = that hash, which exists only once
                   the reference is recorded), then enter C12 from the reference
    rollback       record a rollback; refused once the point of no return is
                   recorded.  From the opening (C12, or C11 once a reference was
                   taken) only with quiescence OBSERVED -- admission closed, the
                   scheduler front disabled, no external trigger -- and the current
                   fingerprint taken live twice, a quiescence interval apart, equal
                   to each other and either equal to the reference or different
                   only by the fixed derived-write classes, acknowledged exactly
    status         current state, granted gates, head, chain verdict
    verify         chain verdict and head only

Exit codes: 0 done, 1 refused (code on stderr), 2 usage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Run as ``python tools/cutover_ledger.py``: the repository root must be importable (``app``, ``tools``).
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app import hosting  # noqa: E402

LEDGER_FILE = "ledger.jsonl"
LOCK_FILE = ".ledger.lock"
MAX_EVIDENCE_BYTES = 8192

STATES = (
    "C0", "C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C10", "C11", "C12", "C13", "C14",
)
ENTRY_TYPES = frozenset({"init", "advance", "grant", "rollback", "reference", "backup"})
#: UD4: the rollback window W, counted from the point of no return (C13) to its closing (C14).
ROLLBACK_WINDOW_DAYS = 30
#: Before a rollback from the opening is trusted, two live fingerprints this far apart must agree:
#: longer than the longest request a deployment can still be serving (maxDuration 300 s).
QUIESCENCE_SECONDS = 330
#: Backup cadence (UD10): the Layer-2 cadence is declared at the reference (1..24 hours); object sets weekly.
OBJECT_CADENCE_HOURS = 7 * 24
CADENCE_TOLERANCE = 1.5
#: Injectable for the tests; the command line uses the real clock and sleep.
_CLOCK = lambda: datetime.now(timezone.utc)  # noqa: E731
_SLEEP = time.sleep
STATE_NAMES = {
    "C0": "REHEARSED", "C1": "PROD_QUALIFIED", "C2": "SNAPSHOT_CENSUSED", "C3": "SOURCE_FROZEN",
    "C4": "SOURCE_PREPARED", "C5": "CONVERGED", "C6": "SOURCE_CROSS_CHECKED", "C7": "TARGET_LOADED",
    "C8": "TARGET_VERIFIED", "C9": "DEPLOYED_DARK", "C10": "SMOKED", "C11": "MIRROR_PROVEN",
    "C12": "OPEN_PONR_PENDING", "C13": "PONR_RECORDED", "C14": "WINDOW_CLOSED",
}
GATES = frozenset({
    "GA1", "GA2", "GA4", "GP0", "GP1", "GP2", "GP3", "GR0", "GR1", "GR2", "GR3", "GB1",
    "GD1", "GD2", "GG1", "GG2", "GO", "GX1", "GF1",
})
# A forward-fix deployment after the point of no return: the one deployment action that remains.  It is
# granted once per deployment (a distinct reference each time) and only after the PONR is recorded.
FORWARD_FIX_GATE = "GF1"
# The gates that must have been granted before a state is entered.  A gate is valid
# for the states listed here and for nothing else (SPEC invariant P4).
STATE_GATES = {
    "C0": (), "C1": ("GP0", "GP1", "GP2"), "C2": ("GR0",), "C3": ("GR1",), "C4": ("GR1",),
    "C5": ("GR2",), "C6": ("GR2",), "C7": ("GR3",), "C8": ("GB1",), "C9": ("GD1",), "C10": (),
    "C11": ("GG1", "GG2", "GD2"), "C12": ("GO",), "C13": (), "C14": (),
}
# The first state a rollback is no longer allowed from, and the gates that act on PROD or on the
# source and therefore cannot be granted once it is recorded (SPEC section 10.2: "before PONR").
PONR_STATE = "C13"
OPENING_STATE = "C12"
PRE_PONR_ONLY_GATES = frozenset({"GP1", "GP2", "GP3", "GR0", "GR1", "GR2", "GR3", "GX1", "GD1"})

_KEY = re.compile(r"[a-z][a-z0-9_]{0,48}")
_LEAF = re.compile(r"[A-Za-z0-9_.:+-]{0,80}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_HEX40 = re.compile(r"[0-9a-f]{40}")
_CLASS = re.compile(r"[A-Z][A-Z0-9_]{0,63}")
_REF = re.compile(r"[A-Za-z0-9_.:+-]{1,64}")
_STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


class Refused(Exception):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


# ---------------------------------------------------------------------------
# value-free evidence
# ---------------------------------------------------------------------------


def _check_value_free(value, depth: int = 0) -> None:
    """Counts, flags, digests, classes and fixed codes only; nothing free-form."""
    if depth > 3:
        raise Refused("EVIDENCE_TOO_DEEP")
    if isinstance(value, bool) or isinstance(value, int):
        return
    if isinstance(value, str):
        if not _LEAF.fullmatch(value):
            raise Refused("EVIDENCE_NOT_VALUE_FREE", "a string value is not a fixed code, digest or timestamp")
        return
    if isinstance(value, list):
        if len(value) > 64:
            raise Refused("EVIDENCE_TOO_LARGE")
        for item in value:
            _check_value_free(item, depth + 1)
        return
    if isinstance(value, dict):
        if len(value) > 64:
            raise Refused("EVIDENCE_TOO_LARGE")
        for key, item in value.items():
            if not isinstance(key, str) or not (_KEY.fullmatch(key) or _CLASS.fullmatch(key)):
                raise Refused("EVIDENCE_NOT_VALUE_FREE", "a key is not a plain identifier")
            _check_value_free(item, depth + 1)
        return
    raise Refused("EVIDENCE_NOT_VALUE_FREE", "only integers, flags, strings, lists and objects are allowed")


def _int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _hex64(value) -> bool:
    return isinstance(value, str) and bool(_HEX64.fullmatch(value))


def _hex40(value) -> bool:
    return isinstance(value, str) and bool(_HEX40.fullmatch(value))


def _nonneg(value) -> bool:
    return _int(value) and value >= 0


def _zero(value) -> bool:
    return _int(value) and value == 0


def _true(value) -> bool:
    return value is True


def _stamp(value) -> bool:
    return isinstance(value, str) and bool(_STAMP.fullmatch(value))


def _equals(expected):
    return lambda value: isinstance(value, str) and value == expected


def _census(value) -> bool:
    return (
        isinstance(value, dict) and bool(value)
        and all(isinstance(k, str) and _nonneg(v) for k, v in value.items())
    )


def _exceptions(value) -> bool:
    return (
        isinstance(value, list)
        and all(
            isinstance(item, dict) and set(item) == {"class", "count"}
            and isinstance(item["class"], str) and bool(_CLASS.fullmatch(item["class"]))
            and _nonneg(item["count"])
            for item in value
        )
        and len({item["class"] for item in value}) == len(value)
    )


def _exceptions_key(value):
    return sorted((item["class"], item["count"]) for item in value)


# Per state: required evidence keys and the predicate each value must satisfy.
_SCHEMA = {
    # ``prod_project_sha256``: the PROD project GP0 names (sha256 of its reference); every data-API proof binds to it.
    "C0": {"commit": _hex40, "runbook_sha256": _hex64, "rehearsal_index_sha256": _hex64,
           "review_verdict": _equals("PASS"), "prod_project_sha256": _hex64},
    "C1": {"pg_major": lambda v: _int(v) and v >= 15, "schema_current": _true, "rows": _zero, "objects": _zero,
           "data_api_toggle_off": _true, "data_api_override": _equals("APPLIED"),
           "data_api_probe": _equals("NOT_SERVED"), "data_api_project_sha256": _hex64,
           "api_exposure_clean": _true, "capacity_ok": _true},
    "C2": {"database_bytes": _nonneg, "document_bytes": _nonneg, "census": _census},
    "C3": {"source_size": lambda v: _int(v) and v > 0, "source_sha256": _hex64, "wal_bytes": _zero},
    "C4": {"source_sha256": _hex64, "prepared_sha256": _hex64, "integrity_ok": _true, "fk_violations": _zero,
           "schema_version": lambda v: _int(v) and v == 16, "accepted_exceptions": _exceptions,
           "accepted_by_user": _true},
    "C5": {"prepared_sha256": _hex64, "converged_rows": _nonneg, "unconverged": _exceptions,
           "legacy_bytes_touched": _zero},
    "C6": {"prepared_sha256": _hex64, "reference_digest": _hex64, "verdict": _equals("CLEAN")},
    # Exit 3 (commit uncertain) is resolved by inspecting the target; the operator says so explicitly.
    "C7": {"prepared_sha256": _hex64, "pathb_exit": lambda v: _int(v) and v in (0, 3),
           "commit_resolved_by_inspection": lambda v: isinstance(v, bool),
           "commit_outcome": _equals("COMMITTED")},
    "C8": {"reference_digest": _hex64, "census_equal": _true, "baseline_manifest_sha256": _hex64,
           "object_set_digest": _hex64, "restore_drill": _equals("OK"), "verify_backup": _equals("OK"),
           "admin_bootstrap": lambda v: v in {"NOT_NEEDED", "DONE"}},
    # The deployment admits only the operator from C9 to C11 (app.web.admission_gate); the tree that was
    # uploaded is the reviewed export, re-proven immediately before the upload (deploy_audit verify).
    "C9": {"commit": _hex40, "readiness": _equals("READY"), "bundle_audit": _equals("CLEAN"),
           "deploy_verify": _equals("IDENTICAL"), "deploy_tree_sha256": _hex64,
           "scheduler_front": _equals("DISABLED"), "admission": _equals("CLOSED")},
    # ``public_host_sha256``: the public address the smoke ran on (its report prints it); every later
    # observation of the ledger (reference, open, rollback) must probe that host.
    "C10": {"smoke": _equals("PASS"), "write_set_ok": _true, "admission": _equals("CLOSED"),
            "data_api_project_sha256": _hex64, "public_host_sha256": _hex64},
    "C11": {"account_key_match": _true, "mirror_passes": lambda v: _nonneg(v) and v >= 1,
            "reconciliation_required": _zero, "scheduler_front": _equals("ENABLED"),
            "admission": _equals("CLOSED")},
    # Written only by ``open``: every value is the ledger's own observation or the reference's.
    "C12": {"reference_fingerprint_sha256": _hex64, "database_identity_sha256": _hex64, "opened_at": _stamp,
            "admission": _equals("OPEN"), "pre_open_backup_manifest_sha256": _hex64,
            "backup_cadence_hours": lambda v: _int(v) and 1 <= v <= 24, "rpo_hours": lambda v: _int(v) and v >= 1,
            "opening_bound": _true, "reference_age_seconds": _nonneg},
    "C13": {"write_class": lambda v: isinstance(v, str) and bool(_CLASS.fullmatch(v)),
            "detected_at": _stamp, "current_fingerprint_sha256": _hex64, "adjudicated_by_operator": _true},
    "C14": {"restore_validated_manifest_sha256": _hex64, "restore_drill": _equals("OK"),
            "unresolved_reconciliation": _zero, "object_set_verified": _true},
}


# ---------------------------------------------------------------------------
# the chain
# ---------------------------------------------------------------------------


def _canonical(entry: dict) -> bytes:
    return json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _entry_hash(body: dict) -> str:
    return hashlib.sha256(_canonical(body)).hexdigest()


def _now() -> str:
    return _CLOCK().strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(stamp: str) -> datetime:
    return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _ledger_dir(path: str, *, must_exist: bool) -> Path:
    directory = Path(path)
    resolved = directory.resolve()
    root = _repository_root().resolve()
    if resolved == root or root in resolved.parents:
        raise Refused("LEDGER_INSIDE_REPOSITORY", "the ledger holds cutover evidence and lives outside the repository")
    if must_exist and not (resolved / LEDGER_FILE).is_file():
        raise Refused("LEDGER_MISSING")
    return resolved


def read_ledger(directory: Path) -> list[dict]:
    """Every entry, with the chain verified; a broken chain is refused."""
    entries: list[dict] = []
    previous = "0" * 64
    try:
        raw = (directory / LEDGER_FILE).read_text(encoding="ascii")
    except (OSError, UnicodeDecodeError):
        raise Refused("LEDGER_UNREADABLE") from None
    for number, line in enumerate(raw.splitlines(), 1):
        try:
            entry = json.loads(line)
            claimed = entry.pop("hash")
        except (ValueError, KeyError, AttributeError, TypeError):
            raise Refused("LEDGER_CHAIN_BROKEN", f"entry {number} is not a ledger entry") from None
        if entry.get("seq") != number or entry.get("prev") != previous or _entry_hash(entry) != claimed:
            raise Refused("LEDGER_CHAIN_BROKEN", f"entry {number} does not follow the chain")
        if entry.get("type") not in ENTRY_TYPES:
            raise Refused("LEDGER_CHAIN_BROKEN", f"entry {number} has no known type")
        entry["hash"] = claimed
        entries.append(entry)
        previous = claimed
    return entries


def _head(entries: list[dict]) -> str:
    return entries[-1]["hash"] if entries else "0" * 64


@contextmanager
def _locked(directory: Path):
    """One writer at a time: two concurrent appends would fork the chain."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / LOCK_FILE
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise Refused("LEDGER_BUSY", "another command holds the ledger; remove .ledger.lock only if none runs") from None
    os.close(descriptor)
    try:
        yield
    finally:
        try:
            path.unlink()
        except OSError:
            pass


def _check_head(entries: list[dict], expected: str | None) -> None:
    if expected is not None and expected != _head(entries):
        raise Refused("HEAD_MISMATCH", "the ledger does not end where the operator last saw it")


def _append(directory: Path, entries: list[dict], body: dict) -> dict:
    entry = {"seq": len(entries) + 1, "prev": _head(entries), "at": _now(), **body}
    entry["hash"] = _entry_hash(entry)
    line = json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    with open(directory / LEDGER_FILE, "a", encoding="ascii", newline="\n") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())
    return entry


def _summary(entries: list[dict]) -> dict:
    """The derived position: current state, rollbacks, grants, carried evidence."""
    state = None
    granted: dict[str, str] = {}
    rolled_back = False
    carried: dict[str, object] = {}
    entered: dict[str, dict] = {}
    reference = None  # the latest reference taken in the current state
    backups: list[dict] = []
    for entry in entries:
        kind = entry["type"]
        if kind == "advance":
            state = entry["state"]
            rolled_back = False
            carried[entry["state"]] = entry["evidence"]
            entered[entry["state"]] = entry
            reference = None
        elif kind == "grant":
            granted[entry["gate"]] = entry["ref"]
        elif kind == "rollback":
            rolled_back = True
        elif kind == "reference":
            reference = entry
        elif kind == "backup":
            backups.append(entry)
    return {"state": state, "granted": granted, "rolled_back": rolled_back, "evidence": carried,
            "entered": entered, "reference": reference, "backups": backups}


def _evidence_of(summary: dict, state: str) -> dict:
    return summary["evidence"].get(state) or {}


def _next_state(current):
    if current is None:
        return STATES[0]
    return STATES[STATES.index(current) + 1] if current != STATES[-1] else None


def _check_carried_identities(state: str, evidence: dict, summary: dict) -> None:
    """Identities must not drift between states."""
    frozen = _evidence_of(summary, "C3").get("source_sha256")
    prepared = _evidence_of(summary, "C4").get("prepared_sha256")
    if state == "C4" and evidence["source_sha256"] != frozen:
        raise Refused("SOURCE_IDENTITY_CHANGED")
    if state in {"C5", "C6", "C7"} and evidence["prepared_sha256"] != prepared:
        raise Refused("PREPARED_IDENTITY_CHANGED")
    if state == "C5":
        accepted = _evidence_of(summary, "C4")["accepted_exceptions"]
        if _exceptions_key(evidence["unconverged"]) != _exceptions_key(accepted):
            raise Refused("UNCONVERGED_ROWS_NOT_ACCEPTED", "the unconverged classes and counts differ from those accepted at C4")
    if state == "C7" and evidence["pathb_exit"] == 3 and evidence["commit_resolved_by_inspection"] is not True:
        raise Refused("COMMIT_UNCERTAIN_NOT_RESOLVED", "exit 3 is resolved by inspecting the target")
    if state == "C8" and evidence["reference_digest"] != _evidence_of(summary, "C6").get("reference_digest"):
        raise Refused("REFERENCE_DIGEST_MISMATCH", "the target does not reproduce the converged source")
    if state == "C8" and evidence["admin_bootstrap"] == "DONE" and "GP3" not in summary["granted"]:
        raise Refused("GATE_NOT_GRANTED", "GP3")
    if state == "C9" and evidence["commit"] != _evidence_of(summary, "C0").get("commit"):
        raise Refused("COMMIT_NOT_THE_REHEARSED_ONE")
    if state == "C1" and evidence["data_api_project_sha256"] != _evidence_of(summary, "C0").get(
        "prod_project_sha256"
    ):
        raise Refused("DATA_API_NOT_THE_PROD_PROJECT", "the data-API proof names another project than GP0's")
    if state == "C10" and evidence["data_api_project_sha256"] != _evidence_of(summary, "C1").get(
        "data_api_project_sha256"
    ):
        raise Refused("DATA_API_PROJECT_CHANGED", "the data-API proof names another project than C1's")
    if state == "C13" and evidence["current_fingerprint_sha256"] == _evidence_of(summary, "C12").get(
        "reference_fingerprint_sha256"
    ):
        raise Refused("NO_FINGERPRINT_DELTA", "a business write changes the fingerprint; this one equals the opening")
    if state == "C14":
        _check_window(summary, evidence)


def _gaps_within(times: list[datetime], start: datetime, end: datetime, hours: float) -> bool:
    """Every interval of [start, end] is shorter than ``hours`` between consecutive recorded times."""
    points = [start] + sorted(t for t in times if start < t <= end) + [end]
    limit = timedelta(hours=hours)
    return all(later - earlier <= limit for earlier, later in zip(points, points[1:]))


def _check_window(summary: dict, evidence: dict) -> None:
    """C14: UD4's window elapsed since C13; the cadence held from the opening (C12) to now; the drill in the window."""
    now = _CLOCK()
    ponr_at = _parse(summary["entered"]["C13"]["at"])
    if now - ponr_at < timedelta(days=ROLLBACK_WINDOW_DAYS):
        raise Refused("WINDOW_NOT_ELAPSED", f"the rollback window is {ROLLBACK_WINDOW_DAYS} days from C13")
    # The pre-open generation (recorded before C12) anchors both cadences.
    start = _parse(summary["entered"]["C12"]["at"])
    cadence = int(_evidence_of(summary, "C12")["backup_cadence_hours"])
    database_times = sorted({_parse(b["generation_at"]) for b in summary["backups"]})
    anchor = [t for t in database_times if t <= start]
    if not _gaps_within(database_times, max(anchor) if anchor else start, now, cadence * CADENCE_TOLERANCE):
        raise Refused("BACKUP_CADENCE_BROKEN", "a Layer-2 generation is missing from the window")
    object_times, seen = [], set()
    for backup in summary["backups"]:
        if backup["object_set_name"] != "NONE" and backup["object_set_name"] not in seen:
            seen.add(backup["object_set_name"])
            object_times.append(_parse(backup["generation_at"]))
    anchor = [t for t in object_times if t <= start]
    if not _gaps_within(object_times, max(anchor) if anchor else start, now, OBJECT_CADENCE_HOURS * CADENCE_TOLERANCE):
        raise Refused("OBJECT_CADENCE_BROKEN", "an object set is missing from the window")
    in_window = {b["manifest_sha256"] for b in summary["backups"] if _parse(b["generation_at"]) > ponr_at}
    if evidence["restore_validated_manifest_sha256"] not in in_window:
        raise Refused("RESTORE_VALIDATION_NOT_A_WINDOW_GENERATION")


def advance(directory: Path, state: str, evidence: dict, *, expect_head: str | None = None) -> dict:
    if state == OPENING_STATE:
        raise Refused("OPENING_NEEDS_THE_OPEN_COMMAND", "C12 is entered by `open`, from an observed reference")
    with _locked(directory):
        entries = read_ledger(directory)
        _check_head(entries, expect_head)
        return _advance_locked(directory, entries, state, evidence)


def _advance_locked(directory: Path, entries: list[dict], state: str, evidence: dict) -> dict:
    summary = _summary(entries)
    if state not in STATES:
        raise Refused("UNKNOWN_STATE")
    if summary["rolled_back"]:
        raise Refused("ROLLED_BACK", "a rolled-back cutover is not continued; start a new ledger")
    expected = _next_state(summary["state"])
    if expected is None or state != expected:
        raise Refused("OUT_OF_ORDER", f"the next state is {expected}")
    missing = [gate for gate in STATE_GATES[state] if gate not in summary["granted"]]
    if missing:
        raise Refused("GATE_NOT_GRANTED", ",".join(missing))
    _check_value_free(evidence)
    if len(json.dumps(evidence, sort_keys=True)) > MAX_EVIDENCE_BYTES:
        raise Refused("EVIDENCE_TOO_LARGE")
    schema = _SCHEMA[state]
    for key, predicate in schema.items():
        if key not in evidence or not predicate(evidence[key]):
            raise Refused("EVIDENCE_INVALID", key)
    unexpected = sorted(set(evidence) - set(schema))
    if unexpected:
        raise Refused("EVIDENCE_UNEXPECTED_KEY", unexpected[0])
    _check_carried_identities(state, evidence, summary)
    return _append(directory, entries, {"type": "advance", "state": state, "evidence": evidence})


def grant(directory: Path, gate: str, ref: str, *, expect_head: str | None = None) -> dict:
    with _locked(directory):
        entries = read_ledger(directory)
        _check_head(entries, expect_head)
        if gate not in GATES:
            raise Refused("UNKNOWN_GATE")
        if not _REF.fullmatch(ref or ""):
            raise Refused("REFERENCE_NOT_OPAQUE", "the reference is a short code, never a quotation")
        summary = _summary(entries)
        current = summary["state"]
        if gate in PRE_PONR_ONLY_GATES and current is not None and STATES.index(current) >= STATES.index(PONR_STATE):
            raise Refused("GATE_NOT_AVAILABLE_AFTER_PONR", "this gate acts on the source or on PROD and is pre-PONR only")
        if gate == FORWARD_FIX_GATE:
            if current is None or STATES.index(current) < STATES.index(PONR_STATE):
                raise Refused("GATE_ONLY_AFTER_PONR", "a forward-fix deployment exists only after the PONR is recorded")
            if any(e["type"] == "grant" and e["gate"] == gate and e["ref"] == ref for e in entries):
                raise Refused("GATE_ALREADY_GRANTED")
            return _append(directory, entries, {"type": "grant", "gate": gate, "ref": ref})
        if gate in summary["granted"]:
            raise Refused("GATE_ALREADY_GRANTED")
        return _append(directory, entries, {"type": "grant", "gate": gate, "ref": ref})


_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class Observer:
    """The ledger's read-only eyes: the public address (no credential), the database, the backups.

    ``base_url``: the public address of the deployment.  The database is ``DATABASE_URL`` (direct
    or session mode: one snapshot transaction; the transaction pooler is refused).  Every answer is
    a fixed code, a count or a digest.
    """

    def __init__(self, base_url: str | None = None, *, allow_insecure: bool = False,
                 database_url: str | None = None, scheduler_url: str | None = None) -> None:
        self.base_url = base_url
        self.allow_insecure = allow_insecure
        self.database_url = database_url
        # On the platform the scheduler front answers at the same public address (a rewrite to its own
        # function); a rehearsal that serves it separately names its address here.
        self.scheduler_url = scheduler_url

    def _require_base(self) -> str:
        if not self.base_url:
            raise Refused("BASE_URL_REQUIRED")
        return self._checked(self.base_url)

    def _checked(self, url: str) -> str:
        """Plain http is for the tests' loopback servers only: a production probe is https."""
        from urllib.parse import urlsplit

        if self.allow_insecure and (urlsplit(url).hostname or "") not in _LOOPBACK_HOSTS:
            raise Refused("INSECURE_ONLY_ON_LOOPBACK")
        return url

    def admission(self) -> str:
        from tools import hosted_smoke

        try:
            return hosted_smoke.probe_admission(self._require_base(), allow_insecure=self.allow_insecure)
        except hosted_smoke.Refused as refusal:
            raise Refused(refusal.code) from None
        except OSError:
            return "unknown"

    def opening_tag(self) -> str:
        from tools import hosted_smoke

        try:
            return hosted_smoke.probe_opening_tag(self._require_base(), allow_insecure=self.allow_insecure)
        except hosted_smoke.Refused as refusal:
            raise Refused(refusal.code) from None
        except OSError:
            return ""

    def host_sha256(self) -> str:
        from tools import hosted_smoke

        return hosted_smoke.host_digest(self._require_base())

    def scheduler_front(self) -> str:
        from tools import hosted_smoke

        try:
            address = self._checked(self.scheduler_url) if self.scheduler_url else self._require_base()
            return hosted_smoke.probe_scheduler_front(address, allow_insecure=self.allow_insecure)
        except hosted_smoke.Refused as refusal:
            raise Refused(refusal.code) from None
        except OSError:
            return "unknown"

    @contextmanager
    def _connection(self):
        from tools import pg_backup

        try:
            url = pg_backup.require_url(self.database_url, "DATABASE_URL")
            conn = pg_backup.connect(url)
        except pg_backup.BackupToolError as exc:
            raise Refused(exc.code) from None
        except Exception:
            raise Refused("DATABASE_UNREACHABLE") from None
        try:
            yield conn
        finally:
            conn.close()

    def database_identity(self) -> str:
        from tools import pg_fingerprint

        with self._connection() as conn:
            return pg_fingerprint.database_identity_sha256(conn)

    def fingerprint(self) -> dict:
        from tools import pg_fingerprint

        with self._connection() as conn:
            return pg_fingerprint.snapshot(conn)

    def classify(self, reference: dict) -> dict:
        from tools import pg_fingerprint

        with self._connection() as conn:
            return pg_fingerprint.classify(conn, reference)

    def external_trigger_jobs(self) -> int:
        """Active ``pg_cron`` jobs (the free external trigger); -1 when they cannot be read."""
        with self._connection() as conn:
            try:
                if conn.execute("SELECT to_regclass('cron.job')").fetchone()[0] is None:
                    return 0
                return int(conn.execute("SELECT count(*) FROM cron.job WHERE active").fetchone()[0])
            except Exception:
                return -1

    def backup(self, root: Path, off_platform: Path, *, against_database: bool) -> dict:
        from tools import ops_backup

        try:
            if not against_database:
                return ops_backup.verify_generation(root, off_platform)
            with self._connection() as conn:
                return ops_backup.verify_generation(root, off_platform, conn=conn)
        except ops_backup.Refused as refusal:
            raise Refused(f"BACKUP_{refusal.code}") from None

    def backup_matches(self, manifest_path: str, fingerprint: dict) -> bool:
        """The Layer-2 set holds exactly the business state of ``fingerprint`` (table digests)."""
        from tools import pg_fingerprint

        try:
            manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
            recorded = manifest["tables"]
        except (OSError, ValueError, KeyError, TypeError):
            return False
        for table, entry in fingerprint["tables"].items():
            stored = recorded.get(table) if isinstance(recorded, dict) else None
            if not isinstance(stored, dict) or stored.get("rows") != entry["rows"]:
                return False
            if table not in pg_fingerprint.EXCLUDED_COLUMNS and stored.get("sha256") != entry["sha256"]:
                return False
        return True


def _require_the_deployment(summary: dict, observer: Observer) -> None:
    """Every observation probes the public address the smoke proved at C10, not some other deployment."""
    if observer.host_sha256() != _evidence_of(summary, "C10").get("public_host_sha256"):
        raise Refused("ADDRESS_NOT_THE_DEPLOYMENT", "probe the public address recorded at C10")


def _require_open_pending(summary: dict, *, allow_reference: bool) -> None:
    if summary["rolled_back"]:
        raise Refused("ROLLED_BACK", "a rolled-back cutover is not continued; start a new ledger")
    if summary["state"] != "C11":
        raise Refused("OUT_OF_ORDER", "the opening follows C11")
    if "GO" not in summary["granted"]:
        raise Refused("GATE_NOT_GRANTED", "GO")
    if not allow_reference and summary["reference"] is None:
        raise Refused("REFERENCE_REQUIRED", "take the reference with `reference` first")


def record_backup(directory: Path, root: Path, off_platform: Path, *, expect_head: str | None = None,
                  observer: Observer | None = None) -> dict:
    """Verify the newest backup generation from disk and record it (C11 onward, until C14)."""
    observer = observer or Observer()
    with _locked(directory):
        entries = read_ledger(directory)
        _check_head(entries, expect_head)
        summary = _summary(entries)
        if summary["rolled_back"]:
            raise Refused("ROLLED_BACK")
        state = summary["state"]
        if state is None or STATES.index(state) < STATES.index("C11") or state == STATES[-1]:
            raise Refused("OUT_OF_ORDER", "backups are recorded from C11 until the window closes")
        generation = observer.backup(Path(root), Path(off_platform), against_database=False)
        if any(b["manifest_sha256"] == generation["manifest_sha256"] for b in summary["backups"]):
            raise Refused("BACKUP_ALREADY_RECORDED", "each generation counts once; take a new one")
        try:
            generation_at = _parse(generation["created_at"])
        except (KeyError, TypeError, ValueError):
            raise Refused("BACKUP_TIME_INVALID") from None
        if generation_at > _CLOCK() + timedelta(minutes=5):
            raise Refused("BACKUP_TIME_INVALID", "the generation is dated in the future")
        if summary["backups"] and generation_at <= max(_parse(b["generation_at"]) for b in summary["backups"]):
            raise Refused("BACKUP_OLDER_THAN_RECORDED", "the generation is not newer than one already recorded")
        return _append(directory, entries, {
            "type": "backup", "manifest_sha256": generation["manifest_sha256"],
            "generation_at": generation_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "object_set_name": generation["object_set"] or "NONE",
            "object_set_digest": generation["object_set_digest"] or "NONE",
            "off_platform": "VERIFIED",
        })


def take_reference(directory: Path, out: Path, root: Path, off_platform: Path, *, cadence_hours: int,
                   expect_head: str | None = None, observer: Observer | None = None) -> dict:
    """The C12 reference, taken by the ledger itself while admission is still CLOSED."""
    from tools import pg_fingerprint

    observer = observer or Observer()
    out = Path(out)
    if not _int(cadence_hours) or not 1 <= cadence_hours <= 24:
        raise Refused("CADENCE_INVALID", "the Layer-2 cadence is 1 to 24 hours (UD10: nightly)")
    resolved = out.resolve()
    if resolved == _repository_root().resolve() or _repository_root().resolve() in resolved.parents:
        raise Refused("OUTPUT_INSIDE_REPOSITORY")
    if out.exists():
        raise Refused("OUTPUT_EXISTS")
    with _locked(directory):
        entries = read_ledger(directory)
        _check_head(entries, expect_head)
        summary = _summary(entries)
        _require_open_pending(summary, allow_reference=True)
        if summary["reference"] is not None:
            # A second reference would re-baseline whatever happened after the first (users admitted
            # by a premature lift included): the opening uses the one reference, whatever its age.
            raise Refused("REFERENCE_ALREADY_TAKEN", "lift with the recorded reference; a new one is never taken")
        _require_the_deployment(summary, observer)
        if observer.admission() != "closed":
            raise Refused("ADMISSION_NOT_CLOSED", "the reference is taken before anyone but the operator is admitted")
        if observer.scheduler_front() != "enabled":
            # The production deployment carries CRON_SECRET since GD2 (C11); an address whose front is
            # disabled is an older deployment, and probing it would prove nothing about production.
            raise Refused("SCHEDULER_FRONT_NOT_ENABLED", "probe the production deployment (CRON_SECRET set at C11)")
        entered_c11 = summary["entered"]["C11"]
        recorded = [b for b in summary["backups"] if b["seq"] > entered_c11["seq"]
                    and _parse(b["generation_at"]) >= _parse(entered_c11["at"])]
        if not recorded or recorded[-1]["object_set_name"] == "NONE":
            raise Refused("PRE_OPEN_BACKUP_REQUIRED", "a verified generation with objects, recorded after C11")
        generation = observer.backup(Path(root), Path(off_platform), against_database=True)
        if generation["manifest_sha256"] != recorded[-1]["manifest_sha256"] or \
                generation["object_set"] != recorded[-1]["object_set_name"]:
            raise Refused("BACKUP_NOT_THE_RECORDED_ONE")
        fingerprint = observer.fingerprint()
        if not observer.backup_matches(generation["manifest_path"], fingerprint):
            raise Refused("BACKUP_NOT_CURRENT", "the pre-opening backup does not hold the current business state")
        identity = observer.database_identity()
        document = dict(fingerprint, taken_at=_now())
        pg_fingerprint.validate(document)
        out.write_text(json.dumps(document, sort_keys=True), encoding="ascii", newline="\n")
        return _append(directory, entries, {
            "type": "reference", "reference_fingerprint_sha256": fingerprint["fingerprint_sha256"],
            "database_identity_sha256": identity, "admission": "CLOSED",
            "pre_open_backup_manifest_sha256": generation["manifest_sha256"],
            "backup_cadence_hours": cadence_hours, "rpo_hours": cadence_hours,
        })


def open_admission(directory: Path, *, expect_head: str | None = None, observer: Observer | None = None) -> dict:
    """Enter C12: the reference is fresh and admission is now observed OPEN."""
    observer = observer or Observer()
    with _locked(directory):
        entries = read_ledger(directory)
        _check_head(entries, expect_head)
        summary = _summary(entries)
        _require_open_pending(summary, allow_reference=False)
        reference = summary["reference"]
        _require_the_deployment(summary, observer)
        if observer.admission() != "open":
            raise Refused("ADMISSION_NOT_OPEN")
        if observer.opening_tag() != hosting.opening_tag(reference["hash"]):
            # The open deployment must have been lifted with THIS reference entry's hash
            # (SGAA_OPENING_REFERENCE): unknowable before the entry exists and unique to this ledger.
            raise Refused("OPENING_NOT_BOUND_TO_THE_REFERENCE")
        cadence_hours = int(reference["backup_cadence_hours"])
        newest = max(_parse(b["generation_at"]) for b in summary["backups"])
        if _CLOCK() - newest > timedelta(hours=cadence_hours * CADENCE_TOLERANCE):
            raise Refused("BACKUP_TOO_OLD_TO_OPEN", "record a new generation first: the cadence starts at the opening")
        evidence = {
            "reference_fingerprint_sha256": reference["reference_fingerprint_sha256"],
            "database_identity_sha256": reference["database_identity_sha256"],
            "opened_at": _now(), "admission": "OPEN",
            "pre_open_backup_manifest_sha256": reference["pre_open_backup_manifest_sha256"],
            "backup_cadence_hours": reference["backup_cadence_hours"], "rpo_hours": reference["rpo_hours"],
            "opening_bound": True,
            "reference_age_seconds": int((_CLOCK() - _parse(reference["at"])).total_seconds()),
        }
        return _advance_locked(directory, entries, OPENING_STATE, evidence)


def _quiescent(observer: Observer) -> None:
    if observer.admission() != "closed":
        raise Refused("ADMISSION_STILL_OPEN", "stop admitting users (SGAA_ADMISSION=operator) before the proof")
    if observer.scheduler_front() != "disabled":
        raise Refused("SCHEDULER_STILL_ENABLED", "remove CRON_SECRET and redeploy before the proof")
    jobs = observer.external_trigger_jobs()
    if jobs < 0:
        raise Refused("QUIESCENCE_UNVERIFIABLE", "the external trigger cannot be read")
    if jobs:
        raise Refused("EXTERNAL_TRIGGER_ACTIVE", "unschedule the external trigger before the proof")


def rollback(directory: Path, reason: str, *, expect_head: str | None = None, observer: Observer | None = None,
             reference_path: str | None = None, derived_classes: list[str] | None = None) -> dict:
    """Record the rollback.  Before the opening, a record.  From the opening, only on observed proof.

    From C12 -- or C11 once a reference was taken, when users may already be admitted -- the ledger
    itself observes quiescence (admission closed, scheduler front disabled, no external trigger), then
    takes the current fingerprint live twice, ``QUIESCENCE_SECONDS`` apart.  The two must agree; the
    current one must equal the reference, or differ only by the fixed derived-write classes of
    ``pg_fingerprint``, verified row by row, which the operator must name exactly.  Anything else is a
    business write: no rollback, record the point of no return (C13).
    """
    with _locked(directory):
        entries = read_ledger(directory)
        _check_head(entries, expect_head)
        summary = _summary(entries)
        if not _CLASS.fullmatch(reason or ""):
            raise Refused("REASON_NOT_A_CODE")
        current = summary["state"]
        if current is not None and STATES.index(current) >= STATES.index(PONR_STATE):
            raise Refused("PONR_RECORDED", "after the point of no return the cutover is forward-fix only")
        if summary["rolled_back"]:
            raise Refused("ALREADY_ROLLED_BACK")
        if current == OPENING_STATE:
            reference_entry = _evidence_of(summary, OPENING_STATE)
        elif current == "C11" and summary["reference"] is not None:
            reference_entry = summary["reference"]
        else:
            return _append(directory, entries, {"type": "rollback", "from_state": current or "NONE", "reason": reason})
        if observer is None or not reference_path:
            raise Refused("QUIESCENCE_PROOF_REQUIRED", "from the opening the ledger observes the rollback itself")
        from tools import pg_fingerprint

        try:
            reference = pg_fingerprint.validate(json.loads(Path(reference_path).read_text(encoding="utf-8")))
        except (OSError, ValueError):
            raise Refused("REFERENCE_UNREADABLE") from None
        except pg_fingerprint.Refused:
            raise Refused("REFERENCE_INVALID") from None
        if reference["fingerprint_sha256"] != reference_entry["reference_fingerprint_sha256"]:
            raise Refused("REFERENCE_FILE_MISMATCH", "not the reference the ledger recorded")
        _require_the_deployment(summary, observer)
        _quiescent(observer)
        if observer.database_identity() != reference_entry["database_identity_sha256"]:
            raise Refused("DATABASE_NOT_THE_REFERENCE", "the database is not the one the reference was taken from")
        first = observer.classify(reference)
        _SLEEP(QUIESCENCE_SECONDS)
        _quiescent(observer)
        verdict = observer.classify(reference)
        if first["current"]["fingerprint_sha256"] != verdict["current"]["fingerprint_sha256"]:
            raise Refused("QUIESCENCE_NOT_PROVEN", "the database still changed; repeat once it is quiescent")
        if verdict["refusal"]:
            raise Refused("FINGERPRINT_CHANGED", f"{verdict['refusal']}: record the point of no return (C13)")
        acknowledged = sorted(set(derived_classes or ()))
        if acknowledged != verdict["derived_classes"]:
            raise Refused("DERIVED_CLASSES_NOT_ACKNOWLEDGED",
                          "name exactly the derived classes the ledger observed: " + ",".join(verdict["derived_classes"]))
        return _append(directory, entries, {
            "type": "rollback", "from_state": current, "reason": reason, "quiescence": "PROVEN",
            "current_fingerprint_sha256": verdict["current"]["fingerprint_sha256"],
            "derived_classes": verdict["derived_classes"],
        })


def init(directory: Path) -> dict:
    with _locked(directory):
        if (directory / LEDGER_FILE).exists():
            raise Refused("LEDGER_EXISTS")
        return _append(directory, [], {"type": "init"})


def status(directory: Path) -> dict:
    entries = read_ledger(directory)
    summary = _summary(entries)
    state = summary["state"]
    nxt = _next_state(state)
    return {
        "entries": len(entries),
        "chain": "OK",
        "head": _head(entries),
        "state": state,
        "state_name": STATE_NAMES.get(state) if state else None,
        "next_state": nxt,
        "next_gates_missing": [g for g in STATE_GATES.get(nxt, ()) if g not in summary["granted"]] if nxt else [],
        "granted": sorted(summary["granted"]),
        "rolled_back": summary["rolled_back"],
        "ponr_recorded": bool(state and STATES.index(state) >= STATES.index(PONR_STATE)),
    }


# ---------------------------------------------------------------------------
# command line
# ---------------------------------------------------------------------------


def _load_evidence(path: str) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise Refused("EVIDENCE_UNREADABLE") from None
    if not isinstance(data, dict):
        raise Refused("EVIDENCE_NOT_AN_OBJECT")
    return data


def main(argv=None, *, out=None, err=None) -> int:
    out = out or sys.stdout
    err = err or sys.stderr
    parser = argparse.ArgumentParser(prog="cutover_ledger", allow_abbrev=False)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "status", "verify"):
        commands.add_parser(name, allow_abbrev=False).add_argument("--ledger-dir", required=True)
    bound = ("grant", "advance", "rollback", "record-backup", "reference", "open")
    for name in bound:
        sub = commands.add_parser(name, allow_abbrev=False)
        sub.add_argument("--ledger-dir", required=True)
        sub.add_argument("--expect-head", default=None,
                         help="the head printed by the previous command; refuses a truncated ledger")
        if name in {"rollback", "reference", "open"}:
            sub.add_argument("--base-url", default=None, help="the public address, probed without any credential")
            sub.add_argument("--allow-insecure", action="store_true", help="tests only: accept http")
        if name in {"record-backup", "reference"}:
            sub.add_argument("--backup-root", required=True, help="the ops_backup primary directory")
            sub.add_argument("--off-platform", required=True, help="the ops_backup off-platform directory")
        if name == "grant":
            sub.add_argument("--gate", required=True)
            sub.add_argument("--ref", required=True)
        elif name == "advance":
            sub.add_argument("--state", required=True)
            sub.add_argument("--evidence", required=True, help="a JSON file of value-free evidence")
        elif name == "reference":
            sub.add_argument("--out", required=True, help="a new file in the custody directory")
            sub.add_argument("--backup-cadence-hours", required=True, type=int)
        elif name == "rollback":
            sub.add_argument("--reason", required=True, help="a fixed code, e.g. SMOKE_FAILED")
            sub.add_argument("--reference", default=None, help="from the opening: the reference fingerprint file")
            sub.add_argument("--derived-class", action="append", default=None,
                             help="from the opening: each derived-write class the ledger observed, named exactly")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 2
    if args.command in bound and not args.expect_head:
        # The head printed by the previous command is what makes a truncated or replaced ledger visible.
        err.write("cutover-ledger: refused: HEAD_REQUIRED\n")
        return 1
    try:
        directory = _ledger_dir(args.ledger_dir, must_exist=args.command != "init")
        observer = Observer(getattr(args, "base_url", None), allow_insecure=getattr(args, "allow_insecure", False))
        if args.command == "init":
            result = init(directory)
        elif args.command == "grant":
            result = grant(directory, args.gate, args.ref, expect_head=args.expect_head)
        elif args.command == "advance":
            result = advance(directory, args.state, _load_evidence(args.evidence), expect_head=args.expect_head)
        elif args.command == "record-backup":
            result = record_backup(directory, Path(args.backup_root), Path(args.off_platform),
                                   expect_head=args.expect_head, observer=observer)
        elif args.command == "reference":
            result = take_reference(directory, Path(args.out), Path(args.backup_root), Path(args.off_platform),
                                    cadence_hours=args.backup_cadence_hours, expect_head=args.expect_head,
                                    observer=observer)
        elif args.command == "open":
            result = open_admission(directory, expect_head=args.expect_head, observer=observer)
        elif args.command == "rollback":
            result = rollback(directory, args.reason, expect_head=args.expect_head, observer=observer,
                              reference_path=args.reference, derived_classes=args.derived_class)
        elif args.command == "status":
            result = status(directory)
        else:
            result = {"chain": "OK", "head": _head(read_ledger(directory))}
    except Refused as refusal:
        err.write(f"cutover-ledger: refused: {refusal.code}\n")
        return 1
    if "hash" in result:  # an appended entry: print the new head so the next command can bind to it
        result = {**result, "head": result["hash"]}
    json.dump(result, out, sort_keys=True)
    out.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
