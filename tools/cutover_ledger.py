# coding: utf-8
"""Cutover evidence ledger -- operator tool, never imported by ``app/``.

WHY THIS EXISTS
    The production cutover is a sequence of gated, partly irreversible states
    (``docs/specs/MP-3-production-integration.md`` section 3.3).  This tool is
    its memory and its referee, not its hands: it validates that a state may
    be entered, that the evidence for it is complete and VALUE-FREE, that every
    gate it needs was granted, and that the identities carried from state to
    state (frozen source, prepared copy, reference digest, deployed commit,
    opening fingerprint) never change.  Where the SPEC forbids trusting the
    operator's word the ledger OBSERVES for itself or consumes a receipt that a
    governed tool produced while it acted (MP-3 A15, A16, A17):

    * the PROD database only through a verified connection (``tools/prod_source``:
      TLS verified against the pinned provider CA, no hidden routing input), whose
      identity must be the one the ledger itself qualified at GP1 (``qualify``,
      cross-checked against the project's own storage API);
    * the public address and every deployment address without any credential
      (``tools/hosted_smoke`` probes), and the platform's own record of every
      deployment (``tools/vercel_provider``);
    * the backups only as the receipts ``tools/ops_backup`` produces while it takes
      them from the verified source, re-verified from disk; restore drills only as
      the receipts of the drill that ran them.

    Two writes to PROD are the ledger's own, both bounded and reversible under GO:
    the opening authorization (written with the reference, revoked by ``close``) and
    the write barrier (``close`` applies it, ``resume`` lifts it).  Only the code the
    ledger currently authorizes may admit (A19 R3 M2): a later authorization, a
    product-contract amendment (``amend --contract-ref``) and ``supersede`` revoke every
    other code of the reference in the same transaction as their own marker, and ``resume``
    restores only the current one.

    A ledger file and a PROD transaction cannot commit atomically, so every act whose effect is a
    PROD transaction (the reference, an authorization, a product-contract amendment, a supersession)
    is written first as an entry that takes effect only with its ``outcome`` (A19 R3 rereview R2):
    its PROD transaction records the entry's hash in ``sgaa_cutover.operations``, then the ledger
    appends COMMITTED -- or ABORTED when PROD provably did not commit.  When the COMMIT's answer is
    lost the act stays unresolved, and every other act is refused until ``reconcile`` has read the
    marker (after waiting for that transaction to end) and recorded the outcome.  The ledger
    therefore never names a code PROD does not authorize, and nothing that lets users in happens
    while it cannot know.

    The platform acts follow the same rule (A19 rereview of 1245bf2, M1/M2): ``deploy_audit`` holds the
    ledger (``holding``) from its precheck through the provider call to the record, so no other act can
    interleave; a deployment is reserved first (a ``deployment_attempt``, which consumes its GF1 before
    anything is uploaded) and a promotion is written before the alias moves; an upload or a promotion
    whose outcome is unknown stays unresolved until ``reconcile`` has observed the platform.  Not seeing
    a provider act never proves it did not happen (rereview of 2fdeee6, M1/M2): a promotion is ABORTED
    only once its deployment can never be served; an open upload closed without its deployment leaves
    its code never authorized, so a late copy of it admits no one.

    Admission is bound to a DEPLOYMENT, not only to a code (rereview of b83b5fc, SPEC A19 (17)): an open
    process admits users only while PROD holds both the authorization of its code and an admission of
    its own platform deployment (``VERCEL_DEPLOYMENT_ID``), which the ledger writes for one recorded
    deployment -- ``admit-deployment`` before the point of no return, ``authorize-code`` for a forward
    fix.  A late, duplicate, superseded or unnamed deployment is admitted by nothing.  Every provider
    observation is bound to the recorded project (and a promotion's to its recorded address); a
    promotion is sent only when it changes what the address serves; ``resume`` is a two-phase act.

WHAT IT STORES
    One append-only JSON-lines file, ``ledger.jsonl``, in a directory outside
    the repository.  Every entry carries the SHA-256 of the previous entry, so
    an edited, reordered or removed entry breaks the chain.  The chain is an
    integrity check against accident, not authenticity: it cannot detect the
    removal of the LAST entries, so every command prints the new ``head`` and
    every later command takes ``--expect-head`` (the runbook makes it
    mandatory): a truncated tail is then refused.  Entries hold counts,
    classes, digests, opaque identifiers and fixed codes only; any other value is
    refused before it is written.  A grant is the operator's record of the user's
    message: the ledger cannot verify the user.

COMMANDS
    init           create the ledger (the directory must not hold one)
    grant          record that the user granted a gate (an opaque reference only)
    qualify        at C0 with GP0/GP1: prove through a verified connection that DATABASE_URL is
                   the PROD project's database (the tenant the provider authenticated, the cluster)
                   and that the project's storage API lists exactly the buckets that database holds;
                   record that identity -- every later observation must be this database
    advance        enter the next state with its evidence (never C12: see ``open``)
    amend          before the PONR: record a reviewed amendment whose commit only ADDS the public
                   compliance pages (``static/compliance/``); its code becomes the candidate every
                   later deployment and the public address must run.  With ``--contract-ref`` (A19),
                   at C12: a product-contract amendment under its GC1 grant
    reference      at C11, with GO granted, once: observe that every deployment of the production
                   project is recorded and CLOSED and that no opening was ever authorized, prove the
                   pre-opening generation current, take the reference fingerprint live, and write the
                   opening authorization for the candidate's code into PROD with the entry
    open           observe that the public address serves the recorded open deployment of that code,
                   that it admits users and announces THAT reference, that the authorization stands
                   and no barrier is in force; then enter C12 from the reference
    close          from the opening (C12, or C11 once a reference exists): revoke the opening
                   authorization and apply the write barrier (the database role every writer uses
                   defaults to read-only; every session started before it is ended); verified live
    rollback       record a rollback; refused once the point of no return is recorded.  From the
                   opening only with the barrier observed in force, quiescence observed and the
                   current fingerprint taken live twice, a quiescence interval apart, equal to each
                   other and either equal to the reference or different only by the fixed
                   derived-write classes, acknowledged exactly
    resume         after a refused rollback: re-prove the newest generation (within the cadence, on disk and
                   off-platform) and that every deployment is recorded, then lift the barrier and restore
                   the authorization
    supersede      at C12 or after the PONR: revoke in PROD every authorization of the opening reference
                   whose code is not the one the ledger currently authorizes (none after a product-contract
                   amendment until its GC2) -- a narrowing act, no gate (A19 R3 M2)
    authorize-code after the point of no return, for a recorded forward-fix deployment (GF1):
                   authorize its code under the same opening reference.  With ``--contract-ref`` (A19),
                   at C12: re-open the amended candidate's recorded open deployment under its GC2 grant
    admit-deployment before the point of no return: admit users at one recorded open deployment of the
                   authorized code (its own platform identity), in a PROD transaction (A19 (17))
    reconcile      resolve an act whose outcome is unknown: for a PROD transaction read its marker in PROD; an
                   upload stays unresolved until ``--abandon-upload`` (ABANDONED; no unrecorded deployment may
                   exist); for a promotion observe the alias
                   (ABORTED only once its deployment is removed or failed) -- then record COMMITTED or
                   ABORTED (A19 R3 rereview R2; rereview of 1245bf2 M1/M2; rereview of 2fdeee6 M1/M2)
    attest-ponr    once, for a declared C13 recorded before restores left a commit marker: bind it forward
                   to the safety copy that restore left in PROD (A19 R3 rereview R1); nothing is rewritten
    status         current state, granted gates, head, chain verdict
    verify         chain verdict and head only

    Backups, restore drills and deployments are recorded by the tools that perform them
    (``ops_backup --ledger-dir``, ``ops_backup drill``, ``deploy_audit deploy`` / ``promote``),
    never typed.

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
from contextlib import contextmanager, nullcontext
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
ENTRY_TYPES = frozenset({
    "init", "advance", "grant", "amendment", "rollback", "reference", "backup", "qualification", "deployment",
    "promotion", "barrier", "restore", "authorization", "supersession", "outcome", "attestation",
    "deployment_attempt", "admission",
})
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
    "GD1", "GD2", "GG1", "GG2", "GO", "GX1", "GF1", "GC1", "GC2",
})
# A forward-fix deployment after the point of no return: the one deployment action that remains.  It is
# granted once per deployment (a distinct reference each time) and only after the PONR is recorded.
FORWARD_FIX_GATE = "GF1"
# Before the point of no return, after the opening (C12; SPEC A19): GC1 grants ONE product-contract
# amendment of the candidate (any deployed file may change; the user's message names what it restores);
# GC2 grants ONE re-opening of that amended code under the same opening reference.  Each grant is
# consumed by one act and a distinct reference is needed for the next; neither exists after the PONR.
CONTRACT_AMENDMENT_GATE = "GC1"
CONTRACT_REOPEN_GATE = "GC2"
CONTRACT_GATES = frozenset({CONTRACT_AMENDMENT_GATE, CONTRACT_REOPEN_GATE})
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
#: Business writes the contract declares to be the PONR even when they leave the fingerprint equal to the
#: opening's (SPEC A19 (12)/(13)): the administrator's "Recuperar banco de dados" replaces every register,
#: so it is the PONR although a restore of the opening's own content moves no digest.  Any other write
#: class is recorded only on a fingerprint delta.
DECLARED_PONR_WRITE_CLASSES = frozenset({"ADMIN_RESTORE"})
#: A restore's safety copy is made inside the restore's own request: the web function's maximum duration.
RESTORE_REQUEST_SECONDS = 300
#: The ledger's own marker of each PROD transaction it runs (A19 R3 rereview R2).  The table exists,
#: committed, before any act's transaction starts, so ``reconcile`` can always wait on it.
OPERATIONS_DDL = (
    "CREATE TABLE IF NOT EXISTS sgaa_cutover.operations ("
    " entry_hash text PRIMARY KEY, recorded_at timestamptz NOT NULL DEFAULT now())",
    "REVOKE ALL ON sgaa_cutover.operations FROM PUBLIC",
)
OPERATIONS_EXISTS_SQL = "SELECT to_regclass('sgaa_cutover.operations') IS NOT NULL"
#: Longer than any act's own transaction can stay open (``Observer._transact`` bounds it at 20 s): an act
#: still running is waited for, never guessed.
RECONCILE_LOCK_SECONDS = 60
#: The only files a pre-PONR amendment may add: the public compliance pages (SPEC A18).
COMPLIANCE_PREFIX = "static/compliance/"
# Deployments the platform will never serve again; every other one must be one the ledger recorded.
TERMINAL_DEPLOYMENT_STATES = frozenset({"ERROR", "CANCELED", "DELETED"})

_KEY = re.compile(r"[a-z][a-z0-9_]{0,48}")
_LEAF = re.compile(r"[A-Za-z0-9_.:+-]{0,80}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_HEX40 = re.compile(r"[0-9a-f]{40}")
_CLASS = re.compile(r"[A-Z][A-Z0-9_]{0,63}")
_REF = re.compile(r"[A-Za-z0-9_.:+-]{1,64}")
_STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_DEPLOYMENT_ID = re.compile(r"dpl_[A-Za-z0-9]{8,64}")


class Refused(Exception):
    def __init__(self, code: str, detail: str = "", *, head: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail
        self.head = head  # set only by an act refused after it wrote its own entries: the head it moved to


class CommitUncertain(Exception):
    """A PROD transaction's COMMIT was sent and its answer never arrived: it may or may not have committed."""


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


def _deployment_id(value) -> bool:
    return isinstance(value, str) and bool(_DEPLOYMENT_ID.fullmatch(value))


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


# Per state: required evidence keys and the predicate each value must satisfy.  What the ledger observes
# or a governed tool recorded (the qualified database, the baseline and its restore drill, the deployment,
# the promoted address, the window's restore drill) is never typed: the evidence names it and the ledger
# finds it in its own entries.
_SCHEMA = {
    # ``prod_project_sha256``: the PROD project GP0 names (sha256 of its reference); every data-API proof binds to it.
    "C0": {"commit": _hex40, "runbook_sha256": _hex64, "rehearsal_index_sha256": _hex64,
           "review_verdict": _equals("PASS"), "prod_project_sha256": _hex64},
    # The database itself is proven by ``qualify`` (a ``qualification`` entry), not by typed evidence.
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
    # The baseline is a ``backup`` entry of kind BASELINE recorded at C7 and its drill a ``restore`` entry.
    "C8": {"reference_digest": _hex64, "census_equal": _true, "baseline_manifest_sha256": _hex64,
           "object_set_digest": _hex64, "admin_bootstrap": lambda v: v in {"NOT_NEEDED", "DONE"}},
    # The deployment is a ``deployment`` entry ``deploy_audit deploy`` recorded (export re-proven, the
    # platform's own file list equal to it, the running code observed); admission only the operator's.
    "C9": {"commit": _hex40, "deployment_id": _deployment_id, "readiness": _equals("READY"),
           "scheduler_front": _equals("DISABLED"), "admission": _equals("CLOSED")},
    # ``public_host_sha256``: the public address the smoke ran on (its report prints it); it must be the
    # address ``deploy_audit promote`` recorded, and every later observation of the ledger probes it.
    "C10": {"smoke": _equals("PASS"), "write_set_ok": _true, "admission": _equals("CLOSED"),
            "data_api_project_sha256": _hex64, "public_host_sha256": _hex64},
    "C11": {"account_key_match": _true, "mirror_passes": lambda v: _nonneg(v) and v >= 1,
            "reconciliation_required": _zero, "scheduler_front": _equals("ENABLED"),
            "admission": _equals("CLOSED")},
    # Written only by ``open``: every value is the ledger's own observation or the reference's.
    "C12": {"reference_fingerprint_sha256": _hex64, "database_identity_sha256": _hex64, "opened_at": _stamp,
            "admission": _equals("OPEN"), "pre_open_backup_manifest_sha256": _hex64,
            "backup_cadence_hours": lambda v: _int(v) and 1 <= v <= 24, "rpo_hours": lambda v: _int(v) and v >= 1,
            "opening_bound": _true, "reference_age_seconds": _nonneg, "code_sha256": _hex64,
            "deployment_id": _deployment_id, "opening_authorized": _true},
    "C13": {"write_class": lambda v: isinstance(v, str) and bool(_CLASS.fullmatch(v)),
            "detected_at": _stamp, "current_fingerprint_sha256": _hex64, "adjudicated_by_operator": _true},
    # A declared PONR (``DECLARED_PONR_WRITE_CLASSES``) also names the restore's commit marker and the
    # safety copy it names; ``advance`` finds both in PROD (A19 R3, rereview R1).
    "C13_DECLARED": {"safety_copy_manifest_sha256": _hex64, "restore_operation_sha256": _hex64},
    # The restore validation is a ``restore`` entry of the drill that ran it.
    "C14": {"restore_validated_manifest_sha256": _hex64, "unresolved_reconciliation": _zero},
}


# ---------------------------------------------------------------------------
# the chain
# ---------------------------------------------------------------------------


def _canonical(entry: dict) -> bytes:
    return hosting.ledger_canonical(entry)


def _entry_hash(body: dict) -> str:
    return hosting.ledger_entry_hash(body)


def _now() -> str:
    return _CLOCK().strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(stamp: str) -> datetime:
    return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _parse_or_none(stamp) -> datetime | None:
    try:
        return _parse(stamp)
    except (TypeError, ValueError):
        return None


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
        raw = (Path(directory) / LEDGER_FILE).read_text(encoding="ascii")
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
    directory = Path(directory)
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


@contextmanager
def holding(directory: Path):
    """Hold the ledger across an act a tool performs outside it (``deploy_audit``: precheck, provider call,
    record): no other ledger act can interleave (rereview of 1245bf2, M1).  The ledger functions the tool
    calls inside take ``held=True``."""
    with _locked(directory):
        yield


def _lock(directory: Path, held: bool):
    return nullcontext() if held else _locked(directory)


def _check_head(entries: list[dict], expected: str | None) -> None:
    if expected is not None and expected != _head(entries):
        raise Refused("HEAD_MISMATCH", "the ledger does not end where the operator last saw it")
    _require_resolved(entries)


def _unresolved(entries: list[dict]) -> dict | None:
    """The act whose PROD outcome the ledger does not know yet (an ``outcome_required`` entry no
    ``outcome`` resolves), else ``None``."""
    resolved = {e["of"] for e in entries if e["type"] == "outcome"}
    resolved |= {e["attempt"] for e in entries if e["type"] == "deployment" and e.get("attempt")}
    return next((e for e in entries if e.get("outcome_required") is True and e["hash"] not in resolved), None)


def _require_resolved(entries: list[dict]) -> None:
    if _unresolved(entries) is not None:
        raise Refused("OPERATION_UNRESOLVED", "a PROD transaction's outcome is unknown: run `reconcile` first")


def _prepare(entries: list[dict], body: dict) -> dict:
    """The next entry, hashed, not yet written.  Nothing follows an unresolved act but its outcome (or, for
    a deployment attempt, the deployment that resolves it)."""
    pending = _unresolved(entries)
    if pending is not None and body.get("type") != "outcome" \
            and not (body.get("type") == "deployment" and body.get("attempt") == pending["hash"]):
        raise Refused("OPERATION_UNRESOLVED", "an act's outcome is unknown: run `reconcile` first")
    entry = {"seq": len(entries) + 1, "prev": _head(entries), "at": _now(), **body}
    _check_value_free({key: value for key, value in entry.items() if key != "evidence"})
    entry["hash"] = _entry_hash(entry)
    return entry


def _write(directory: Path, entry: dict) -> dict:
    line = json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    with open(Path(directory) / LEDGER_FILE, "a", encoding="ascii", newline="\n") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())
    return entry


def _append(directory: Path, entries: list[dict], body: dict) -> dict:
    return _write(directory, _prepare(entries, body))


def _commit_act(directory: Path, entries: list[dict], body: dict, act) -> dict:
    """Run an act whose effect is a PROD transaction (A19 R3 rereview R2).

    The entry is written first, marked ``outcome_required``; ``act(entry)`` runs the PROD transaction,
    which records the entry's hash in ``sgaa_cutover.operations``; then the outcome is appended.  Only a
    ``Refused`` -- which the acts raise exclusively before their COMMIT is sent (``Observer._transact``)
    -- is a proven non-commit: ABORTED, and the refusal goes on.  Anything else (the COMMIT's answer
    lost, an interruption, a failure after the COMMIT) leaves the act unresolved -- ``reconcile``
    decides.  Returns the entry (the ledger's head is then its outcome).
    """
    entry = _write(directory, _prepare(entries, {**body, "outcome_required": True}))
    written = [*entries, entry]
    try:
        act(entry)
    except Refused as refusal:
        aborted = _append(directory, written, {"type": "outcome", "of": entry["hash"], "result": "ABORTED",
                                               "resolved_by": "REFUSED"})
        refusal.head = aborted["hash"]
        raise
    except BaseException:
        raise Refused("OPERATION_UNRESOLVED", "PROD's outcome is unknown: run `reconcile`",
                      head=entry["hash"]) from None
    _append(directory, written, {"type": "outcome", "of": entry["hash"], "result": "COMMITTED",
                                 "resolved_by": "ACKNOWLEDGED"})
    return entry


def _summary(entries: list[dict]) -> dict:
    """The derived position: current state, rollbacks, grants, carried evidence, recorded facts."""
    state = None
    granted: dict[str, str] = {}
    rolled_back = False
    carried: dict[str, object] = {}
    entered: dict[str, dict] = {}
    reference = None  # the latest reference taken in the current state
    opening_reference = None  # the reference entry C12 was opened from
    backups: list[dict] = []
    collected = {"qualification": None, "deployments": [], "promotions": [], "barriers": [], "restores": [],
                 "authorizations": [], "grants": [], "amendments": [], "supersessions": [], "attestations": [],
                 "attempts": [], "admissions": []}
    # An act whose PROD transaction did not commit, or whose outcome is still unknown, has no effect.
    committed = {e["of"] for e in entries if e["type"] == "outcome" and e["result"] == "COMMITTED"}
    committed |= {e["attempt"] for e in entries if e["type"] == "deployment" and e.get("attempt")}
    for entry in entries:
        if entry["type"] == "deployment_attempt":
            collected["attempts"].append(entry)  # every attempt consumed its GF1, whatever its outcome
            continue
        if entry.get("outcome_required") is True and entry["hash"] not in committed:
            continue
        kind = entry["type"]
        if kind == "advance":
            state = entry["state"]
            rolled_back = False
            carried[entry["state"]] = entry["evidence"]
            entered[entry["state"]] = entry
            if state == OPENING_STATE and reference is not None:
                opening_reference = reference
            reference = None
        elif kind == "grant":
            granted[entry["gate"]] = entry["ref"]
            collected["grants"].append(entry)
        elif kind == "rollback":
            rolled_back = True
        elif kind == "reference":
            reference = entry
        elif kind == "backup":
            backups.append(entry)
        elif kind == "qualification":
            collected["qualification"] = entry
        elif kind == "deployment":
            collected["deployments"].append(entry)
        elif kind == "promotion":
            collected["promotions"].append(entry)
        elif kind == "barrier":
            collected["barriers"].append(entry)
        elif kind == "restore":
            collected["restores"].append(entry)
        elif kind == "authorization":
            collected["authorizations"].append(entry)
        elif kind == "amendment":
            collected["amendments"].append(entry)
        elif kind == "supersession":
            collected["supersessions"].append(entry)
        elif kind == "attestation":
            collected["attestations"].append(entry)
        elif kind == "admission":
            collected["admissions"].append(entry)
    # An open upload whose answer was lost and that was closed without its deployment (ABANDONED; before
    # d0fbba7's rereview, reconciled) may still appear: its code is never authorized (rereview of 2fdeee6, M2).
    unproven = {e["of"] for e in entries if e["type"] == "outcome"
                and (e["resolved_by"] == "RECONCILED" or e["result"] == "ABANDONED")}
    collected["unproven_codes"] = {a["code_sha256"] for a in collected["attempts"]
                                   if a["admission"] == "OPEN" and a["hash"] in unproven}
    return {"state": state, "granted": granted, "rolled_back": rolled_back, "evidence": carried,
            "entered": entered, "reference": reference, "backups": backups,
            "opening_reference": opening_reference, "any_reference": reference or opening_reference, **collected}


def _evidence_of(summary: dict, state: str) -> dict:
    return summary["evidence"].get(state) or {}


def _next_state(current):
    if current is None:
        return STATES[0]
    return STATES[STATES.index(current) + 1] if current != STATES[-1] else None


def _generations(summary: dict) -> list[dict]:
    return [b for b in summary["backups"] if b["kind"] == "GENERATION"]


def _baseline(summary: dict):
    found = [b for b in summary["backups"] if b["kind"] == "BASELINE"]
    return found[-1] if found else None


def _deployment(summary: dict, deployment_id: str):
    found = [d for d in summary["deployments"] if d["deployment_id"] == deployment_id]
    return found[-1] if found else None


def _restored(summary: dict, backup: dict) -> bool:
    return any(r["manifest_sha256"] == backup["manifest_sha256"] and r["seq"] > backup["seq"]
               for r in summary["restores"])


def _barrier_applied(summary: dict) -> dict | None:
    """The barrier currently in force by the ledger's own record (the latest barrier entry is APPLIED)."""
    if summary["barriers"] and summary["barriers"][-1]["action"] == "APPLIED":
        return summary["barriers"][-1]
    return None


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
    if state == "C8":
        _check_baseline(summary, evidence)
    if state == "C9":
        _check_dark_deployment(summary, evidence)
    if state == "C1":
        if summary["qualification"] is None:
            raise Refused("QUALIFICATION_REQUIRED", "`qualify` proves the PROD database before C1")
        if evidence["data_api_project_sha256"] != _evidence_of(summary, "C0").get("prod_project_sha256"):
            raise Refused("DATA_API_NOT_THE_PROD_PROJECT", "the data-API proof names another project than GP0's")
    if state == "C10":
        if evidence["data_api_project_sha256"] != _evidence_of(summary, "C1").get("data_api_project_sha256"):
            raise Refused("DATA_API_PROJECT_CHANGED", "the data-API proof names another project than C1's")
        _check_promoted_address(summary, evidence)
    if state == "C13" and evidence["write_class"] not in DECLARED_PONR_WRITE_CLASSES             and evidence["current_fingerprint_sha256"] == _evidence_of(summary, "C12").get(
        "reference_fingerprint_sha256"
    ):
        raise Refused("NO_FINGERPRINT_DELTA", "a business write changes the fingerprint; this one equals the opening")
    if state == "C14":
        _check_window(summary, evidence)


def _check_baseline(summary: dict, evidence: dict) -> None:
    """C8: the baseline was taken by the governed backup after C7 and restore-drilled by the drill."""
    baseline = _baseline(summary)
    if baseline is None or baseline["seq"] < summary["entered"]["C7"]["seq"]:
        raise Refused("BASELINE_REQUIRED", "`ops_backup --baseline --ledger-dir` at C7 records the baseline")
    if evidence["baseline_manifest_sha256"] != baseline["manifest_sha256"] or \
            evidence["object_set_digest"] != baseline["object_set_digest"]:
        raise Refused("BASELINE_NOT_THE_RECORDED_ONE")
    if not _restored(summary, baseline):
        raise Refused("BASELINE_RESTORE_REQUIRED", "`ops_backup drill` restores the baseline into scratch first")


def _check_dark_deployment(summary: dict, evidence: dict) -> None:
    """C9: the deployment ``deploy_audit deploy`` recorded after C8, admitting only the operator."""
    deployment = _deployment(summary, evidence["deployment_id"])
    if deployment is None or deployment["seq"] < summary["entered"]["C8"]["seq"]:
        raise Refused("DEPLOYMENT_NOT_RECORDED", "`deploy_audit deploy --ledger-dir` records the deployment")
    if evidence["commit"] != _evidence_of(summary, "C0").get("commit") or deployment["commit"] != evidence["commit"]:
        raise Refused("COMMIT_NOT_THE_REHEARSED_ONE")
    if deployment["admission"] != "OPERATOR":
        raise Refused("DEPLOYMENT_NOT_CLOSED")


def _effective_commit(summary: dict) -> str | None:
    """The commit a pre-PONR deployment must run: the latest recorded amendment's, else C0's."""
    amendments = summary["amendments"]
    if amendments:
        return amendments[-1]["commit"]
    return _evidence_of(summary, "C0").get("commit")


def _authorized_code(summary: dict):
    """The one code that may admit users under the opening reference now (A19 R3 M2), else ``None``.

    The reference's own code; a product-contract amendment (GC1) withdraws it -- the amended code
    admits no one until its GC2 -- and each later authorization (GC2, or a forward fix) replaces it.
    """
    reference = summary["any_reference"]
    if reference is None:
        return None
    code = reference["code_sha256"]
    events = [a for a in summary["amendments"] if "contract_ref" in a and a["seq"] > reference["seq"]]
    events += [a for a in summary["authorizations"] if a["seq"] > reference["seq"]]
    for event in sorted(events, key=lambda item: item["seq"]):
        code = event["code_sha256"] if event["type"] == "authorization" else None
    return code


def _candidate_code(summary: dict):
    """The code every pre-PONR deployment and the public address must run: the latest recorded
    amendment's (A18), else the deployment C9 recorded."""
    amendments = summary["amendments"]
    if amendments:
        return amendments[-1]["code_sha256"]
    deployment_id = _evidence_of(summary, "C9").get("deployment_id")
    deployment = _deployment(summary, deployment_id) if deployment_id else None
    return deployment["code_sha256"] if deployment else None


def _check_promoted_address(summary: dict, evidence: dict) -> None:
    """C10: the address the smoke proved is the one ``deploy_audit promote`` pointed at the candidate."""
    promotions = [p for p in summary["promotions"] if p["seq"] > summary["entered"]["C9"]["seq"]]
    if not promotions or promotions[-1]["public_host_sha256"] != evidence["public_host_sha256"]:
        raise Refused("PUBLIC_ADDRESS_NOT_PROMOTED", "promote the smoked deployment with `deploy_audit promote`")
    deployment = _deployment(summary, promotions[-1]["deployment_id"])
    if deployment is None or deployment["code_sha256"] != _candidate_code(summary):
        raise Refused("PUBLIC_ADDRESS_NOT_THE_CANDIDATE")


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
    generations = _generations(summary)
    database_times = sorted({_parse(b["generation_at"]) for b in generations})
    anchor = [t for t in database_times if t <= start]
    if not _gaps_within(database_times, max(anchor) if anchor else start, now, cadence * CADENCE_TOLERANCE):
        raise Refused("BACKUP_CADENCE_BROKEN", "a Layer-2 generation is missing from the window")
    object_times = [_parse(b["generation_at"]) for b in generations if b["object_set_name"] != "NONE"]
    anchor = [t for t in object_times if t <= start]
    if not _gaps_within(object_times, max(anchor) if anchor else start, now, OBJECT_CADENCE_HOURS * CADENCE_TOLERANCE):
        raise Refused("OBJECT_CADENCE_BROKEN", "an object set is missing from the window")
    in_window = [b for b in generations if _parse(b["generation_at"]) > ponr_at and b["object_set_name"] != "NONE"]
    validated = [b for b in in_window if b["manifest_sha256"] == evidence["restore_validated_manifest_sha256"]]
    if not validated:
        raise Refused("RESTORE_VALIDATION_NOT_A_WINDOW_GENERATION")
    if not _restored(summary, validated[-1]):
        raise Refused("RESTORE_RECEIPT_REQUIRED", "`ops_backup drill` restores that generation into scratch")


def advance(directory: Path, state: str, evidence: dict, *, expect_head: str | None = None,
            observer: Observer | None = None) -> dict:
    if state == OPENING_STATE:
        raise Refused("OPENING_NEEDS_THE_OPEN_COMMAND", "C12 is entered by `open`, from an observed reference")
    with _locked(directory):
        entries = read_ledger(directory)
        _check_head(entries, expect_head)
        if state == PONR_STATE and evidence.get("write_class") in DECLARED_PONR_WRITE_CLASSES:
            _require_declared_restore(_summary(entries), evidence, observer or Observer())
        return _advance_locked(directory, entries, state, evidence)


def _require_declared_restore(summary: dict, evidence: dict, observer: "Observer") -> None:
    """A declared PONR (an administrator's restore) is recorded only on proof that the restore COMMITTED
    (A19 R3 rereview R1): the commit marker ``app.backup.pg_restore`` writes in the very transaction that
    replaced the registers -- intact, of this database, naming the declared safety copy, completed between
    the opening and the declared moment -- and that safety copy's own receipt in PROD, made after the
    opening and before the completion, sent to a drive.  A backup receipt alone proves no restore."""
    from app.backup import pg_restore

    reference = summary["opening_reference"]
    opened = _parse_or_none(_evidence_of(summary, OPENING_STATE).get("opened_at"))
    detected = _parse_or_none(evidence.get("detected_at"))
    manifest, operation = evidence.get("safety_copy_manifest_sha256"), evidence.get("restore_operation_sha256")
    if reference is None or opened is None or detected is None or not _hex64(manifest) or not _hex64(operation):
        raise Refused("EVIDENCE_INVALID", "safety_copy_manifest_sha256, restore_operation_sha256")
    identity = _production_database(summary, observer)
    if identity != reference["database_identity_sha256"]:
        raise Refused("DATABASE_NOT_THE_REFERENCE")
    marker = observer.restore_marker(operation, identity)
    completed = _parse_or_none(marker.get("completed_at")) if pg_restore.marker_intact(marker) else None
    if completed is None or marker["hash"] != operation or marker["source_identity_sha256"] != identity \
            or marker["safety_copy_manifest_sha256"] != manifest or not opened <= completed <= detected:
        raise Refused("DECLARED_RESTORE_NOT_FOUND",
                      "no commit marker of a restore of this database with that safety copy, completed between "
                      "the opening and the declared moment")
    receipt = next((r for r in observer.snapshot_receipts(identity) if r["manifest_sha256"] == manifest), None)
    made = _parse_or_none(receipt["generation_at"]) if receipt else None
    if made is None or not receipt["destinations"] or not opened <= made <= completed:
        raise Refused("DECLARED_RESTORE_NOT_FOUND", "the safety copy the marker names is not recorded in PROD")


def _needs_attestation(summary: dict) -> bool:
    """A declared C13 recorded before restores left a commit marker, not yet attested (rereview R1): no
    code is authorized after it until its restore is bound to what PROD shows."""
    c13 = summary["entered"].get(PONR_STATE)
    evidence = c13["evidence"] if c13 else {}
    return bool(c13) and evidence.get("write_class") in DECLARED_PONR_WRITE_CLASSES \
        and "restore_operation_sha256" not in evidence \
        and not any(a["of_hash"] == c13["hash"] for a in summary["attestations"])


def attest_ponr(directory: Path, *, expect_head: str | None = None, observer: Observer | None = None) -> dict:
    """Bind, forward, a declared C13 recorded before restores left a commit marker (A19 R3 rereview R1).

    That C13 stays as written.  The attestation records what PROD shows of that restore: the one snapshot
    receipt of this database, sent to a drive, made within the restore's own request (from the declared
    moment, ``RESTORE_REQUEST_SECONDS``) -- its safety copy -- and carries forward the digest the C13
    evidence named, which is the file that was restored.  The commit itself is the operator's
    adjudication of the application's log (``pg_restore_done`` is logged only after the COMMIT was
    acknowledged); the attestation says so and that no marker exists.  Once per C13.
    """
    observer = observer or Observer()
    with _locked(directory):
        entries = read_ledger(directory)
        _check_head(entries, expect_head)
        summary = _summary(entries)
        c13 = summary["entered"].get(PONR_STATE)
        evidence = c13["evidence"] if c13 else {}
        if c13 is None or evidence.get("write_class") not in DECLARED_PONR_WRITE_CLASSES \
                or "restore_operation_sha256" in evidence:
            raise Refused("NOTHING_TO_ATTEST", "only a declared C13 recorded before the restore's commit marker")
        if any(a["of_hash"] == c13["hash"] for a in summary["attestations"]):
            raise Refused("ALREADY_ATTESTED")
        reference = summary["opening_reference"]
        identity = _production_database(summary, observer)
        if identity != reference["database_identity_sha256"]:
            raise Refused("DATABASE_NOT_THE_REFERENCE")
        detected = _parse(evidence["detected_at"])
        window = []
        for receipt in observer.snapshot_receipts(identity):
            made = _parse_or_none(receipt["generation_at"])
            if receipt["destinations"] and made is not None and \
                    detected <= made <= detected + timedelta(seconds=RESTORE_REQUEST_SECONDS):
                window.append(receipt)
        if not window:
            raise Refused("SAFETY_COPY_NOT_FOUND", "no snapshot of this database was sent within the restore's request")
        if len(window) > 1:
            raise Refused("SAFETY_COPY_AMBIGUOUS", "more than one snapshot was sent within the restore's request")
        return _append(directory, entries, {
            "type": "attestation", "of_state": PONR_STATE, "of_hash": c13["hash"],
            "basis": "PRE_MARKER_ADMIN_RESTORE", "commit_marker": "ABSENT",
            "commit_evidence": "OPERATOR_ADJUDICATED_APP_LOG",
            "safety_copy_manifest_sha256": window[0]["manifest_sha256"], "safety_copy_at": window[0]["generation_at"],
            "restored_manifest_sha256": evidence["safety_copy_manifest_sha256"], "database_identity_sha256": identity,
        })


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
    schema = dict(_SCHEMA[state])
    if state == PONR_STATE and evidence.get("write_class") in DECLARED_PONR_WRITE_CLASSES:
        schema.update(_SCHEMA["C13_DECLARED"])
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
        if gate in CONTRACT_GATES:
            if current is None or STATES.index(current) >= STATES.index(PONR_STATE):
                raise Refused("GATE_ONLY_BEFORE_PONR", "a product-contract amendment exists only before the PONR")
            if summary["rolled_back"]:
                raise Refused("ROLLED_BACK")
            if summary["any_reference"] is None:
                raise Refused("CONTRACT_GATE_BEFORE_THE_REFERENCE",
                              "before the reference the candidate is amended by `amend` alone (A18)")
            if current != OPENING_STATE:
                raise Refused("OUT_OF_ORDER", "a product-contract amendment and its re-opening follow the opening (C12)")
            if any(e["type"] == "grant" and e["gate"] == gate and e["ref"] == ref for e in entries):
                raise Refused("GATE_ALREADY_GRANTED")
            return _append(directory, entries, {"type": "grant", "gate": gate, "ref": ref})
        if gate in summary["granted"]:
            raise Refused("GATE_ALREADY_GRANTED")
        return _append(directory, entries, {"type": "grant", "gate": gate, "ref": ref})


def amend(directory: Path, commit: str, ref: str, *, expect_head: str | None = None,
          repo: Path | None = None, contract_ref: str | None = None, observer: Observer | None = None) -> dict:
    """Record a reviewed amendment before the PONR: a commit that only ADDS the public compliance pages.

    The amendment supersedes the candidate for every later pre-PONR step (deployment, promotion,
    reference, opening): its runtime code identity becomes the one every deployment must run.  The
    guards are not lifted -- the amendment must descend from the effective commit, and the deployed
    files it changes are exactly the added pages under ``COMPLIANCE_PREFIX`` and nothing else.

    With ``contract_ref`` (SPEC A19) it is a product-contract amendment: after the opening (C12) and
    before the PONR, under the unused GC1 grant of that reference, the commit may change any deployed
    file (it must change at least one).  It still descends from the effective commit, and its code
    admits no one until a GC2 re-opening authorizes it under the same opening reference.  In the same
    PROD transaction as its entry it revokes every authorization of the reference (A19 R3 M2): the
    superseded code admits no one from then on, and a code already authorized is refused (a revert
    would otherwise re-open without GC2).
    """
    from tools import deploy_audit

    repo = Path(repo) if repo is not None else _repository_root()
    try:
        resolved = deploy_audit._resolve_commit(commit, repo)
    except deploy_audit.Refused:
        raise Refused("COMMIT_NOT_FOUND") from None
    if not _REF.fullmatch(ref or ""):
        raise Refused("REFERENCE_NOT_OPAQUE", "the reference is a short code, never a quotation")
    with _locked(directory):
        entries = read_ledger(directory)
        _check_head(entries, expect_head)
        summary = _summary(entries)
        if summary["rolled_back"]:
            raise Refused("ROLLED_BACK")
        state = summary["state"]
        if state is None or STATES.index(state) < STATES.index("C8"):
            raise Refused("OUT_OF_ORDER", "an amendment follows C8")
        if STATES.index(state) >= STATES.index(PONR_STATE):
            raise Refused("AMENDMENT_AFTER_PONR", "an amendment exists only before the point of no return")
        previous = _effective_commit(summary)
        if not previous or resolved == previous:
            raise Refused("AMENDMENT_NOT_NEW", "the amendment is a new commit on top of the effective one")
        ancestry = deploy_audit._git(repo, "merge-base", "--is-ancestor", previous, resolved)
        if ancestry.returncode != 0:
            raise Refused("AMENDMENT_NOT_DESCENDANT", "the amendment descends from the effective commit")
        try:
            old_files = {path: blob for path, blob in deploy_audit._committed_blobs(previous, repo).items()
                         if deploy_audit._allowed(path)}
            new_files = {path: blob for path, blob in deploy_audit._committed_blobs(resolved, repo).items()
                         if deploy_audit._allowed(path)}
        except deploy_audit.Refused as refusal:
            raise Refused(refusal.code) from None
        changed = sorted(path for path in old_files if old_files[path] != new_files.get(path))
        if contract_ref is not None:
            if summary["any_reference"] is None:
                raise Refused("CONTRACT_GATE_BEFORE_THE_REFERENCE",
                              "before the reference the candidate is amended by `amend` alone (A18)")
            if state != OPENING_STATE:
                raise Refused("OUT_OF_ORDER", "a product-contract amendment follows the opening (C12)")
            _unused_contract_grant(summary, CONTRACT_AMENDMENT_GATE, contract_ref, "amendments")
            if not changed and not (set(new_files) - set(old_files)):
                raise Refused("AMENDMENT_EMPTY", "the amendment changes at least one deployed file")
            code = hosting.code_sha256(new_files)
            reference = summary["opening_reference"]
            if code in {reference["code_sha256"], *(a["code_sha256"] for a in summary["authorizations"])}:
                raise Refused("AMENDMENT_CODE_ALREADY_AUTHORIZED",
                              "an amendment never brings back a code that was authorized before")
            observer = observer or Observer()
            identity = _production_database(summary, observer)
            if identity != reference["database_identity_sha256"]:
                raise Refused("DATABASE_NOT_THE_REFERENCE")
            return _commit_act(directory, entries, {
                "type": "amendment", "amends": previous, "commit": resolved, "code_sha256": code, "ref": ref,
                "contract_ref": contract_ref, "authorizations": "SUPERSEDED",
            }, lambda entry: observer.supersede(reference["hash"], None, entry))
        if changed:
            raise Refused("AMENDMENT_CHANGES_DEPLOYED_FILES",
                          "the amendment only adds files; it never changes or removes one")
        added = sorted(set(new_files) - set(old_files))
        if not added:
            raise Refused("AMENDMENT_EMPTY", "the amendment adds the public compliance pages")
        if any(not path.startswith(COMPLIANCE_PREFIX) for path in added):
            raise Refused("AMENDMENT_FILE_OUTSIDE_COMPLIANCE", f"only {COMPLIANCE_PREFIX} may be added")
        code = hosting.code_sha256(new_files)
        return _append(directory, entries, {"type": "amendment", "amends": previous, "commit": resolved,
                                            "code_sha256": code, "ref": ref})


def _unused_contract_grant(summary: dict, gate: str, ref, consumers: str) -> None:
    """A GC1/GC2 grant with this reference exists and no amendment / authorization consumed it yet."""
    if not any(g["gate"] == gate and g["ref"] == ref for g in summary["grants"]):
        raise Refused("GATE_NOT_GRANTED", gate)
    if any(item.get("contract_ref") == ref for item in summary[consumers]):
        raise Refused("GATE_ALREADY_USED", f"{gate} {ref} was consumed; each act needs its own grant")


# ---------------------------------------------------------------------------
# the ledger's eyes
# ---------------------------------------------------------------------------


_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class Observer:
    """The ledger's eyes: public addresses (no credential), the PROD database, the platform, the backups.

    ``base_url``: the public address of the deployment.  The database is ``DATABASE_URL`` (the
    session-pooler address of the PROD project), always opened through ``tools/prod_source``: TLS
    verified against the pinned provider CA, no hidden routing input (``source_connector`` replaces
    it only in the tests, with a disposable local server).  ``provider``: the platform's record of the
    production project's deployments (``tools/vercel_provider.VercelCli``).  Every answer is a fixed
    code, a count, an opaque identifier or a digest.
    """

    def __init__(self, base_url: str | None = None, *, allow_insecure: bool = False,
                 database_url: str | None = None, scheduler_url: str | None = None,
                 source_connector=None, provider=None, environ=None) -> None:
        self.base_url = base_url
        self.allow_insecure = allow_insecure
        self.database_url = database_url
        # On the platform the scheduler front answers at the same public address (a rewrite to its own
        # function); a rehearsal that serves it separately names its address here.
        self.scheduler_url = scheduler_url
        self.source_connector = source_connector
        self.provider = provider
        self.environ = environ

    # -- public addresses ----------------------------------------------------

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

    def admission(self, url: str | None = None) -> str:
        from tools import hosted_smoke

        try:
            address = self._checked(url) if url else self._require_base()
            return hosted_smoke.probe_admission(address, allow_insecure=self.allow_insecure)
        except hosted_smoke.Refused as refusal:
            raise Refused(refusal.code) from None
        except OSError:
            return "unknown"

    def code(self, url: str | None = None) -> str:
        """The code identity a deployment announces (``X-SGAA-Code``; '' when none)."""
        from tools import hosted_smoke

        try:
            address = self._checked(url) if url else self._require_base()
            return hosted_smoke.probe_code(address, allow_insecure=self.allow_insecure)
        except hosted_smoke.Refused as refusal:
            raise Refused(refusal.code) from None
        except OSError:
            return ""

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

    def public_host(self) -> str:
        from urllib.parse import urlsplit

        return (urlsplit(self._require_base()).hostname or "").lower()

    def scheduler_front(self) -> str:
        from tools import hosted_smoke

        try:
            address = self._checked(self.scheduler_url) if self.scheduler_url else self._require_base()
            return hosted_smoke.probe_scheduler_front(address, allow_insecure=self.allow_insecure)
        except hosted_smoke.Refused as refusal:
            raise Refused(refusal.code) from None
        except OSError:
            return "unknown"

    # -- the platform ----------------------------------------------------------

    def _platform(self):
        if self.provider is None:
            raise Refused("PROVIDER_REQUIRED", "name the production project (--vercel-team, --vercel-project)")
        return self.provider

    def provider_project_sha256(self) -> str:
        return hashlib.sha256(self._platform().project_id.encode("utf-8")).hexdigest()

    def provider_deployments(self) -> list[dict]:
        """Every deployment the platform holds for the production project: id, url, state."""
        from tools import vercel_provider

        try:
            return self._platform().deployments()
        except vercel_provider.Refused as refusal:
            raise Refused(refusal.code) from None

    def alias_deployment(self) -> str:
        """The deployment the public address serves, as the platform resolves it."""
        from tools import vercel_provider

        try:
            return self._platform().alias_target(self.public_host())
        except vercel_provider.Refused as refusal:
            raise Refused(refusal.code) from None

    def deployment_files_sha256(self, deployment_id: str) -> str:
        from tools import vercel_provider

        try:
            return vercel_provider.files_sha256(self._platform().files(deployment_id))
        except vercel_provider.Refused as refusal:
            raise Refused(refusal.code) from None

    # -- the PROD database, verified ----------------------------------------------

    @contextmanager
    def _connection(self):
        from tools import prod_source

        url = self.database_url if self.database_url is not None else os.environ.get("DATABASE_URL")
        try:
            conn = (self.source_connector or prod_source.connect)(url)
        except prod_source.Refused as refusal:
            raise Refused(refusal.code) from None
        except Refused:
            raise
        except Exception:
            raise Refused("DATABASE_UNREACHABLE") from None
        try:
            yield conn
        finally:
            conn.close()

    def source(self):
        """What the verified connection proves (``tools/prod_source.VerifiedSource``)."""
        from tools import prod_source

        with self._connection() as conn:
            try:
                return prod_source.observe(conn)
            except prod_source.Refused as refusal:
                raise Refused(refusal.code) from None

    def database_identity(self) -> str:
        return self.source().identity

    def store_project_sha256(self) -> str:
        from tools import prod_source

        try:
            return prod_source.store_project_sha256(self.environ)
        except prod_source.Refused as refusal:
            raise Refused(refusal.code) from None

    def store_buckets(self) -> frozenset:
        from tools import prod_source

        try:
            return prod_source.store_buckets(self.environ)
        except prod_source.Refused as refusal:
            raise Refused(refusal.code) from None

    def database_buckets(self) -> frozenset:
        from tools import prod_source

        with self._connection() as conn:
            try:
                return prod_source.database_buckets(conn)
            except prod_source.Refused as refusal:
                raise Refused(refusal.code) from None

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

    # -- the opening authorization (written by the ledger, read by every open deployment) --------

    def opening_rows(self) -> int:
        with self._connection() as conn:
            if not conn.execute(hosting.OPENING_EXISTS_SQL).fetchone()[0]:
                return 0
            return int(conn.execute(hosting.OPENING_ROWS_SQL).fetchone()[0])

    def _transact(self, entry: dict, statements):
        """Run ``statements(conn)`` and record ``entry``'s hash in ``sgaa_cutover.operations`` in ONE PROD
        transaction (A19 R3 rereview R2).  Raises ``Refused`` only when PROD provably did not commit (no
        COMMIT was sent), ``CommitUncertain`` when the COMMIT was sent and its answer never came.

        The marker is the transaction's FIRST statement: from then on the act holds the operations table,
        so ``reconcile`` waits for it; the transaction is bounded below ``RECONCILE_LOCK_SECONDS``."""
        with self._connection() as conn:
            committing = False
            try:
                conn.execute("SET default_transaction_read_only = off")
                with conn.transaction():  # committed before the act: `reconcile` can always wait on the table
                    for statement in (*hosting.OPENING_DDL, *hosting.ADMISSION_DDL, *OPERATIONS_DDL):
                        conn.execute(statement)
                with conn.transaction():
                    conn.execute("SET LOCAL statement_timeout = '20s'")
                    conn.execute("SET LOCAL idle_in_transaction_session_timeout = '20s'")
                    conn.execute("INSERT INTO sgaa_cutover.operations (entry_hash) VALUES (%s)", (entry["hash"],))
                    result = statements(conn)
                    committing = True  # leaving the block sends COMMIT
            except Refused:
                raise
            except BaseException:
                if committing:
                    raise CommitUncertain() from None
                raise Refused("PROD_TRANSACTION_FAILED", "PROD did not commit; nothing changed") from None
            return result

    def authorize(self, reference_sha256: str, code_sha256: str, entry: dict, *, first: bool) -> None:
        """Insert the authorization (the entry itself, which the application verifies) in the act's PROD
        transaction (``_transact``).  ``first``: the opening's own authorization -- refused when any
        authorization already exists (a stale or premature one)."""
        text = json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=True)

        def statements(conn):
            if first and int(conn.execute(hosting.OPENING_ROWS_SQL).fetchone()[0]):
                raise Refused("OPENING_AUTHORIZATION_EXISTS", "an opening was authorized before this reference")
            conn.execute(hosting.OPENING_INSERT_SQL, (reference_sha256, code_sha256, text))
            if not first:  # the new code replaces every other one of the reference (A19 R3 M2)
                conn.execute(hosting.OPENING_SUPERSEDE_SQL, (reference_sha256, code_sha256))
            if entry.get("deployment_id"):  # and admits its one recorded deployment (A19 (17))
                conn.execute(hosting.ADMISSION_INSERT_SQL, (reference_sha256, entry["deployment_id"], text))

        self._transact(entry, statements)

    def admit(self, reference_sha256: str, deployment_id: str, entry: dict) -> None:
        """Admit users at one recorded deployment (the entry itself, which the application verifies) in the
        act's PROD transaction (``_transact``; A19 (17))."""
        text = json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        self._transact(entry, lambda conn: conn.execute(hosting.ADMISSION_INSERT_SQL,
                                                        (reference_sha256, deployment_id, text)))

    def supersede(self, reference_sha256: str, keep_code: str | None, entry: dict) -> int:
        """Revoke every authorization of the reference except ``keep_code`` (all when ``None``) in the act's
        PROD transaction (``_transact``); the number of rows revoked."""
        return self._transact(entry, lambda conn: int(
            conn.execute(hosting.OPENING_SUPERSEDE_SQL, (reference_sha256, keep_code or "")).rowcount or 0))

    def operation_committed(self, entry_hash: str) -> bool:
        """Whether the act ``entry_hash`` committed in PROD.  Waits (``RECONCILE_LOCK_SECONDS``) until no act's
        transaction holds the operations table, so an act still running is never read as aborted."""
        with self._connection() as conn:
            try:  # read-only is enough (SHARE is allowed there): it also runs under the write barrier
                with conn.transaction():
                    if not conn.execute(OPERATIONS_EXISTS_SQL).fetchone()[0]:
                        return False  # created, committed, before any act: no act ever reached PROD
                    conn.execute(f"SET LOCAL lock_timeout = '{RECONCILE_LOCK_SECONDS}s'")
                    conn.execute("LOCK TABLE sgaa_cutover.operations IN SHARE MODE")
                    return bool(conn.execute("SELECT EXISTS (SELECT 1 FROM sgaa_cutover.operations"
                                             " WHERE entry_hash = %s)", (entry_hash,)).fetchone()[0])
            except Refused:
                raise
            except Exception:
                raise Refused("RECONCILE_UNDECIDED", "PROD could not be read; run `reconcile` again") from None

    def snapshot_receipts(self, identity: str) -> list[dict]:
        """Every intact "Gerar backup agora" receipt of this database in PROD's ``sgaa_ops.backup_records``:
        ``manifest_sha256``, ``generation_at``, ``destinations`` (the drives that received it)."""
        from app.backup import pg_posture

        with self._connection() as conn:
            if not conn.execute(pg_posture.EXISTS_SQL).fetchone()[0]:
                return []
            rows = conn.execute(pg_posture.SELECT_SQL).fetchall()
        found = []
        for text, _note in rows:
            try:
                entry = json.loads(text)
            except (TypeError, ValueError):
                continue
            if pg_posture._intact(entry) and entry.get("kind") == pg_posture.SNAPSHOT_KIND \
                    and entry.get("source_identity_sha256") == identity and _hex64(entry.get("manifest_sha256")):
                destinations = entry.get("destinations") if isinstance(entry.get("destinations"), list) else []
                found.append({"manifest_sha256": entry["manifest_sha256"], "generation_at": entry.get("generation_at"),
                              "destinations": [d for d in destinations if d in ("google", "onedrive")]})
        return found

    def restore_marker(self, marker_sha256: str, identity: str) -> dict | None:
        """The commit marker ``marker_sha256`` "Recuperar banco de dados" left in PROD, else ``None`` (the
        ledger re-verifies its integrity and every field it relies on)."""
        from app.backup import pg_restore

        with self._connection() as conn:
            if not conn.execute(pg_restore.MARKER_EXISTS_SQL).fetchone()[0]:
                return None
            row = conn.execute(pg_restore.MARKER_BY_HASH_SQL, (marker_sha256,)).fetchone()
        try:
            return json.loads(row[0]) if row else None
        except (TypeError, ValueError):
            return None

    def authorization_valid(self, reference_sha256: str, code_sha256: str, project_sha256: str,
                            deployment_id: str | None = None) -> bool:
        """Whether the PROD database authorizes an open deployment of this code -- the app's own test; with
        ``deployment_id``, whether it admits users at that deployment (both rows, as the application reads)."""
        with self._connection() as conn:
            if not conn.execute(hosting.OPENING_EXISTS_SQL).fetchone()[0]:
                return False
            row = conn.execute(hosting.OPENING_SELECT_SQL, (reference_sha256, code_sha256)).fetchone()
            admitted = None
            if deployment_id is not None and conn.execute(hosting.ADMISSION_EXISTS_SQL).fetchone()[0]:
                admitted = conn.execute(hosting.ADMISSION_SELECT_SQL, (reference_sha256, deployment_id)).fetchone()
            identity = hosting.source_identity_sha256(hosting.database_source(conn))
        authorized = row is not None and hosting.opening_entry_authorizes(
            row[0], reference=reference_sha256, database_identity=identity, code=code_sha256, project=project_sha256)
        if deployment_id is None:
            return authorized
        return authorized and admitted is not None and hosting.deployment_entry_admits(
            admitted[0], reference=reference_sha256, database_identity=identity, code=code_sha256,
            project=project_sha256, deployment=deployment_id)

    # -- the write barrier ----------------------------------------------------------

    @staticmethod
    def _role_statement(conn, action: str):
        from psycopg import sql

        role, database = conn.execute("SELECT current_user, current_database()").fetchone()
        return sql.SQL("ALTER ROLE {} IN DATABASE {} " + action).format(sql.Identifier(role), sql.Identifier(database))

    @staticmethod
    def _end_sessions_before(conn, moment) -> int:
        """End every session of the writers' role older than ``moment`` -- this one last.

        A pooler reuses server sessions across clients (observed on the provider's session pooler,
        MP-3 A17): a role default applies only to sessions started after it, so every older session,
        the one running this statement included, must end or the pool would hand it out again.
        """
        import psycopg

        ended = int(conn.execute(
            "SELECT count(*) FROM (SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
            " WHERE usename = current_user AND datname = current_database() AND pid <> pg_backend_pid()"
            " AND backend_type = 'client backend' AND backend_start < %s) ended", (moment,)).fetchone()[0])
        try:
            conn.execute("SELECT pg_terminate_backend(pg_backend_pid())")
        except psycopg.Error:
            pass  # this session ended, as intended
        return ended + 1

    def apply_barrier(self) -> dict:
        """Revoke the authorization, make the writers' role read-only by default, end every older session."""
        with self._connection() as conn:
            conn.execute("SET default_transaction_read_only = off")
            with conn.transaction():
                if conn.execute(hosting.OPENING_EXISTS_SQL).fetchone()[0]:
                    conn.execute(hosting.OPENING_REVOKE_SQL)
                conn.execute(self._role_statement(conn, "SET default_transaction_read_only = on"))
            barrier_at = conn.execute("SELECT clock_timestamp()").fetchone()[0]
            terminated = self._end_sessions_before(conn, barrier_at)
        return {"barrier_at": barrier_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                "terminated": terminated}

    def barrier_state(self, barrier_at: str) -> dict:
        """Read in a fresh session: the role default it got, a write it cannot make, older sessions left
        (this one included: a pooled session from before the barrier is no fresh session)."""
        import psycopg

        moment = datetime.strptime(barrier_at, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
        with self._connection() as conn:
            fresh_read_only = str(conn.execute("SHOW transaction_read_only").fetchone()[0]) == "on"
            setting = bool(conn.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_db_role_setting s JOIN pg_database d ON d.oid = s.setdatabase"
                " WHERE d.datname = current_database() AND s.setrole = (SELECT oid FROM pg_roles"
                " WHERE rolname = current_user) AND 'default_transaction_read_only=on' = ANY (s.setconfig))"
            ).fetchone()[0])
            older = 0
            for _attempt in range(10):  # a terminated backend leaves pg_stat_activity within moments
                older = int(conn.execute(
                    "SELECT count(*) FROM pg_stat_activity WHERE usename = current_user"
                    " AND datname = current_database() AND backend_type = 'client backend'"
                    " AND backend_start < %s", (moment,)).fetchone()[0])
                if not older:
                    break
                time.sleep(0.5)
            open_rows = 0
            if conn.execute(hosting.OPENING_EXISTS_SQL).fetchone()[0]:
                open_rows = int(conn.execute(
                    "SELECT count(*) FROM sgaa_cutover.opening WHERE revoked_at IS NULL").fetchone()[0])
            try:
                conn.execute("CREATE TEMP TABLE sgaa_barrier_probe (x integer)")
                write_refused = False
            except psycopg.errors.ReadOnlySqlTransaction:
                write_refused = True
        return {"setting": setting, "fresh_read_only": fresh_read_only, "write_refused": write_refused,
                "older_sessions": older, "authorizations_in_force": open_rows}

    def lift_barrier(self, reference_sha256: str, code_sha256: str | None, entry: dict) -> None:
        """Reset the role default and restore the authorization of ``code_sha256`` only (the code the ledger
        currently authorizes; none when ``None``) in the act's PROD transaction (``_transact``: its marker
        commits with them; rereview of b83b5fc, M4), then end every session that started read-only.

        Ending those sessions follows the COMMIT: any failure there is ``CommitUncertain`` (never a
        refusal, which would read as "not committed"), and ``reconcile`` finds the marker."""
        def statements(conn):
            conn.execute(self._role_statement(conn, "RESET default_transaction_read_only"))
            if code_sha256:
                conn.execute(hosting.OPENING_RESTORE_CODE_SQL, (reference_sha256, code_sha256))

        self._transact(entry, statements)
        try:
            with self._connection() as conn:
                lifted_at = conn.execute("SELECT clock_timestamp()").fetchone()[0]
                self._end_sessions_before(conn, lifted_at)
        except BaseException:
            raise CommitUncertain() from None

    def writable(self) -> bool:
        """Whether a fresh session of the writers' role may write (no barrier in force)."""
        with self._connection() as conn:
            return str(conn.execute("SHOW transaction_read_only").fetchone()[0]) == "off"


# ---------------------------------------------------------------------------
# what the ledger requires of what it observes
# ---------------------------------------------------------------------------


def _production_database(summary: dict, observer: Observer) -> str:
    """The live database's canonical identity, proven to be THE database qualified at GP1 (and, once a
    reference exists, the reference's).  Never a typed value: it is read through a verified connection."""
    qualification = summary["qualification"]
    if qualification is None:
        raise Refused("QUALIFICATION_REQUIRED", "`qualify` proves the PROD database first")
    live = observer.source()
    if live.project_sha256 != _evidence_of(summary, "C0").get("prod_project_sha256"):
        # A consistent wrong database (DEV, another project) is refused here.
        raise Refused("DATABASE_NOT_THE_PROD_PROJECT", "DATABASE_URL is not the PROD project's database")
    if live.identity != qualification["database_identity_sha256"]:
        raise Refused("DATABASE_NOT_THE_QUALIFIED_ONE", "the database is not the one qualified at GP1")
    anchor = summary["any_reference"]
    if anchor and live.identity != anchor["database_identity_sha256"]:
        raise Refused("DATABASE_NOT_THE_REFERENCE", "the database is not the one the reference was taken from")
    return live.identity


def _check_generation_sources(summary: dict, generation: dict, identity: str) -> None:
    """The generation's Layer-2 set and object set name THIS database (and the PROD store) as their source."""
    if hosting.source_identity_sha256(generation.get("database_source")) != identity:
        raise Refused("BACKUP_NOT_FROM_THE_PROD_DATABASE", "the Layer-2 set was taken from another database")
    if generation.get("object_set"):
        source = generation.get("object_source") if isinstance(generation.get("object_source"), dict) else {}
        store = hosting.supabase_project_ref(source.get("store_host"))
        if hosting.source_identity_sha256(source.get("database")) != identity or store is None or \
                hosting.project_sha256(store) != _evidence_of(summary, "C0").get("prod_project_sha256"):
            raise Refused("OBJECT_SET_NOT_FROM_THE_PROD_PROJECT",
                          "the object set was read from another database or another project's store")


def _require_the_deployment(summary: dict, observer: Observer) -> None:
    """Every observation probes the public address the smoke proved at C10, not some other deployment."""
    if observer.host_sha256() != _evidence_of(summary, "C10").get("public_host_sha256"):
        raise Refused("ADDRESS_NOT_THE_DEPLOYMENT", "probe the public address recorded at C10")


def _recorded_project(summary: dict):
    """The production project, as the ledger recorded it: its deployments', else its first attempt's."""
    if summary["deployments"]:
        return summary["deployments"][0]["vercel_project_sha256"]
    attempts = [a for a in summary["attempts"] if a.get("vercel_project_sha256")]
    return attempts[0]["vercel_project_sha256"] if attempts else None


def _require_provider_project(summary: dict, observer: Observer) -> str:
    """Every provider observation is of the recorded project (rereview of b83b5fc, M3): another project's
    empty list, alias or missing deployment proves nothing about production."""
    project = _recorded_project(summary)
    if project is None or observer.provider_project_sha256() != project:
        raise Refused("PROVIDER_NOT_THE_PROJECT", "name the production project the deployments were recorded in")
    return project


def _require_closed_everywhere(summary: dict, observer: Observer) -> None:
    """No deployment of the production project can have admitted anyone (the reference's precondition).

    The platform's own list: every deployment it may still serve must be one the governed deploy
    recorded, recorded as admitting only the operator, and observed CLOSED at its own address running
    the code recorded for it.  The public address must serve the candidate.
    """
    for deployment in observer.provider_deployments():
        if deployment["state"] in TERMINAL_DEPLOYMENT_STATES:
            continue
        recorded = _deployment(summary, deployment["id"])
        if recorded is None:
            raise Refused("UNRECORDED_DEPLOYMENT", "a deployment the ledger never recorded may have admitted users")
        if recorded["admission"] != "OPERATOR":
            raise Refused("DEPLOYMENT_OPENED_BEFORE_THE_REFERENCE")
        if deployment["state"] != "READY":
            continue
        if observer.admission(deployment["url"]) != "closed":
            raise Refused("DEPLOYMENT_NOT_CLOSED", "every deployment address must refuse users before the reference")
        if observer.code(deployment["url"]) != recorded["code_sha256"]:
            raise Refused("DEPLOYMENT_CODE_CHANGED")
    serving = _deployment(summary, observer.alias_deployment())
    if serving is None or serving["code_sha256"] != _candidate_code(summary):
        raise Refused("ALIAS_NOT_THE_CANDIDATE", "the public address must serve a recorded deployment of the candidate")


def _require_open_pending(summary: dict, *, allow_reference: bool) -> None:
    if summary["rolled_back"]:
        raise Refused("ROLLED_BACK", "a rolled-back cutover is not continued; start a new ledger")
    if summary["state"] != "C11":
        raise Refused("OUT_OF_ORDER", "the opening follows C11")
    if "GO" not in summary["granted"]:
        raise Refused("GATE_NOT_GRANTED", "GO")
    if not allow_reference and summary["reference"] is None:
        raise Refused("REFERENCE_REQUIRED", "take the reference with `reference` first")


def _require_pending_opening(summary: dict) -> dict:
    """C12, or C11 once a reference exists (users may already be admitted): the reference entry."""
    current = summary["state"]
    if summary["rolled_back"]:
        raise Refused("ROLLED_BACK")
    if current is not None and STATES.index(current) >= STATES.index(PONR_STATE):
        raise Refused("PONR_RECORDED", "after the point of no return the cutover is forward-fix only")
    if current == OPENING_STATE:
        return summary["opening_reference"]
    if current == "C11" and summary["reference"] is not None:
        return summary["reference"]
    raise Refused("NOT_OPENED", "the barrier serves the opening (C12, or C11 once a reference exists)")


def _require_barrier(summary: dict, observer: Observer) -> dict:
    """The barrier the ledger applied is in force, observed in a fresh session."""
    applied = _barrier_applied(summary)
    if applied is None:
        raise Refused("BARRIER_REQUIRED", "`close` applies the write barrier before the rollback proof")
    state = observer.barrier_state(applied["barrier_at"])
    if not (state["setting"] and state["fresh_read_only"] and state["write_refused"]):
        raise Refused("BARRIER_NOT_IN_FORCE", "a fresh session of the writers' role can write")
    if state["older_sessions"]:
        raise Refused("BARRIER_NOT_IN_FORCE", "a session started before the barrier is still connected")
    if state["authorizations_in_force"]:
        raise Refused("BARRIER_NOT_IN_FORCE", "an opening authorization is in force again")
    return applied


# ---------------------------------------------------------------------------
# the qualification (GP1)
# ---------------------------------------------------------------------------


def qualify(directory: Path, *, expect_head: str | None = None, observer: Observer | None = None) -> dict:
    """C0 -> (C1): the PROD database, proven through a verified connection and the project's own API."""
    from tools import prod_source

    observer = observer or Observer()
    with _locked(directory):
        entries = read_ledger(directory)
        _check_head(entries, expect_head)
        summary = _summary(entries)
        if summary["rolled_back"]:
            raise Refused("ROLLED_BACK")
        if summary["state"] != "C0":
            raise Refused("OUT_OF_ORDER", "the PROD database is qualified at C0, before C1")
        missing = [gate for gate in ("GP0", "GP1") if gate not in summary["granted"]]
        if missing:
            raise Refused("GATE_NOT_GRANTED", ",".join(missing))
        if summary["qualification"] is not None:
            raise Refused("QUALIFICATION_ALREADY_RECORDED")
        project = _evidence_of(summary, "C0")["prod_project_sha256"]
        live = observer.source()
        if live.project_sha256 != project:
            raise Refused("DATABASE_NOT_THE_PROD_PROJECT", "DATABASE_URL is not the PROD project's database")
        if observer.store_project_sha256() != project:
            raise Refused("STORE_NOT_THE_PROD_PROJECT", "SUPABASE_URL names another project than GP0's")
        listed, held = observer.store_buckets(), observer.database_buckets()
        if not listed:
            raise Refused("NO_BUCKET_TO_COMPARE", "create the private bucket (GP1) before the qualification")
        if listed != held:
            raise Refused("STORE_NOT_THE_DATABASES_PROJECT",
                          "the project's storage API and the database do not hold the same buckets")
        return _append(directory, entries, {
            "type": "qualification", "database_identity_sha256": live.identity, "project_sha256": project,
            "store_project_sha256": project, "buckets_compared": len(listed), "tls": "VERIFIED",
            "ca_sha256": prod_source.PINNED_CA_SHA256,
        })


# ---------------------------------------------------------------------------
# receipts of the governed tools: backups, restore drills, deployments, promotions
# ---------------------------------------------------------------------------

_BACKUP_KINDS = frozenset({"GENERATION", "BASELINE"})


def _backup_window(summary: dict, kind: str) -> None:
    state = summary["state"]
    if summary["rolled_back"]:
        raise Refused("ROLLED_BACK")
    if kind == "BASELINE":
        if state != "C7":
            raise Refused("OUT_OF_ORDER", "the cutover baseline is taken at C7 (GB1)")
        if "GB1" not in summary["granted"]:
            raise Refused("GATE_NOT_GRANTED", "GB1")
        if _baseline(summary) is not None:
            raise Refused("BASELINE_ALREADY_RECORDED")
        return
    if state is None or STATES.index(state) < STATES.index("C11") or state == STATES[-1]:
        raise Refused("OUT_OF_ORDER", "backups are recorded from C11 until the window closes")


def backup_preconditions(directory: Path, kind: str) -> dict:
    """What the governed backup must hold before it starts: the qualified identity and the PROD project."""
    if kind not in _BACKUP_KINDS:
        raise Refused("BACKUP_KIND_INVALID")
    entries = read_ledger(directory)
    _require_resolved(entries)  # it could not be recorded: refused before the run, not after it
    summary = _summary(entries)
    _backup_window(summary, kind)
    if summary["qualification"] is None:
        raise Refused("QUALIFICATION_REQUIRED")
    return {"database_identity_sha256": summary["qualification"]["database_identity_sha256"],
            "prod_project_sha256": _evidence_of(summary, "C0")["prod_project_sha256"]}


def record_generation(directory: Path, receipt: dict, root: Path, off_platform: Path, *,
                      observer: Observer | None = None) -> dict:
    """Record the generation a governed ``ops_backup`` run just took (its receipt), re-verified from disk.

    The receipt's identity was observed live through the verified connection before and after the run;
    it must be the qualified (and reference) database now as well, every artifact on disk must be the
    one the run produced (Layer-2 manifest and dump, object set manifest and digest), and its time lies
    inside the run.  No typed or file-borne provenance is ever accepted.
    """
    observer = observer or Observer()
    kind = receipt.get("kind")
    if kind not in _BACKUP_KINDS:
        raise Refused("BACKUP_KIND_INVALID")
    with _locked(directory):
        entries = read_ledger(directory)
        summary = _summary(entries)
        _backup_window(summary, kind)
        identity = _production_database(summary, observer)
        if receipt.get("source_identity_sha256") != identity or receipt.get("source_identity_after_sha256") != identity:
            raise Refused("BACKUP_NOT_FROM_THE_PROD_DATABASE", "the run did not read the qualified database throughout")
        project = _evidence_of(summary, "C0")["prod_project_sha256"]
        if receipt.get("object_set") and receipt.get("store_project_sha256") != project:
            raise Refused("OBJECT_SET_NOT_FROM_THE_PROD_PROJECT")
        if kind == "BASELINE" and not receipt.get("object_set"):
            raise Refused("BASELINE_NEEDS_OBJECTS")
        try:
            started, finished = _parse(receipt["run_started_at"]), _parse(receipt["run_finished_at"])
            generation_at = _parse(receipt["generation_at"])
        except (KeyError, TypeError, ValueError):
            raise Refused("BACKUP_TIME_INVALID") from None
        if not started <= generation_at <= finished or finished > _CLOCK() + timedelta(minutes=5):
            raise Refused("BACKUP_TIME_INVALID", "the generation is not dated inside its own run")
        if any(b["manifest_sha256"] == receipt.get("manifest_sha256") for b in summary["backups"]):
            raise Refused("BACKUP_ALREADY_RECORDED", "each generation counts once; take a new one")
        generations = _generations(summary)
        if kind == "GENERATION" and generations and \
                generation_at <= max(_parse(b["generation_at"]) for b in generations):
            raise Refused("BACKUP_OLDER_THAN_RECORDED", "the generation is not newer than one already recorded")
        on_disk = observer.backup(Path(root), Path(off_platform), against_database=False)
        produced = (receipt.get("manifest_sha256"), receipt.get("dump_sha256"), receipt.get("object_set"),
                    receipt.get("object_set_digest"), receipt.get("object_manifest_sha256"))
        found = (on_disk["manifest_sha256"], on_disk["dump_sha256"], on_disk["object_set"],
                 on_disk["object_set_digest"], on_disk["object_manifest_sha256"])
        if produced != found:
            raise Refused("BACKUP_NOT_THE_RUNS_OUTPUT", "the artifacts on disk are not the ones this run produced")
        _check_generation_sources(summary, on_disk, identity)
        return _append(directory, entries, {
            "type": "backup", "kind": kind, "manifest_sha256": on_disk["manifest_sha256"],
            "dump_sha256": on_disk["dump_sha256"], "source_identity_sha256": identity,
            "store_project_sha256": project if on_disk["object_set"] else "NONE",
            "generation_at": generation_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "object_set_name": on_disk["object_set"] or "NONE",
            "object_set_digest": on_disk["object_set_digest"] or "NONE",
            "object_manifest_sha256": on_disk["object_manifest_sha256"] or "NONE",
            "off_platform": "VERIFIED", "provenance": "LIVE_RUN",
            "run_seconds": int((finished - started).total_seconds()),
        })


def record_restore(directory: Path, receipt: dict) -> dict:
    """Record a restore drill ``ops_backup drill`` just ran, bound to a recorded generation and a scratch target."""
    with _locked(directory):
        entries = read_ledger(directory)
        summary = _summary(entries)
        if summary["rolled_back"]:
            raise Refused("ROLLED_BACK")
        generation = [b for b in summary["backups"] if b["manifest_sha256"] == receipt.get("manifest_sha256")]
        if not generation:
            raise Refused("RESTORE_NOT_OF_A_RECORDED_GENERATION")
        generation = generation[-1]
        if (receipt.get("dump_sha256"), receipt.get("source_identity_sha256")) != (
                generation["dump_sha256"], generation["source_identity_sha256"]):
            raise Refused("RESTORE_SOURCE_MISMATCH", "the restored set is not the recorded generation")
        if generation["object_set_name"] == "NONE" or receipt.get("object_set_digest") != generation["object_set_digest"] \
                or receipt.get("object_set") != "VERIFIED" or receipt.get("objects_cover_restored_rows") is not True:
            raise Refused("RESTORE_OBJECT_SET_NOT_VERIFIED")
        if receipt.get("restored") != "VERIFIED" or not _int(receipt.get("tables_verified")) or \
                receipt["tables_verified"] < 1:
            raise Refused("RESTORE_NOT_VERIFIED")
        if summary["qualification"] is None:
            raise Refused("QUALIFICATION_REQUIRED")
        target = receipt.get("target_identity_sha256")
        if not _hex64(target) or target == summary["qualification"]["database_identity_sha256"]:
            raise Refused("RESTORE_TARGET_IS_PROD")
        if receipt.get("target_scratch") is not True:
            raise Refused("RESTORE_TARGET_NOT_SCRATCH")
        if receipt.get("target_major") != _evidence_of(summary, "C1").get("pg_major"):
            raise Refused("RESTORE_TARGET_NOT_THE_PROD_MAJOR")
        return _append(directory, entries, {
            "type": "restore", "manifest_sha256": generation["manifest_sha256"],
            "dump_sha256": generation["dump_sha256"], "source_identity_sha256": generation["source_identity_sha256"],
            "object_set_digest": generation["object_set_digest"], "target_identity_sha256": target,
            "target_major": receipt["target_major"], "tables_verified": receipt["tables_verified"],
            "objects_verified": int(receipt.get("objects_verified") or 0), "restored": "VERIFIED",
            "object_set": "VERIFIED",
        })


_DEPLOYMENT_KEYS = ("deployment_id", "url_sha256", "vercel_project_sha256", "commit", "deploy_tree_sha256",
                    "code_sha256", "files_sha256", "admission", "opening_reference", "forward_fix_ref",
                    "observed_admission", "aliased", "attempt", "observed_deployment_id")
_ATTEMPT_KEYS = ("commit", "code_sha256", "admission", "opening_reference", "forward_fix_ref",
                 "vercel_project_sha256")


def deployment_preconditions(directory: Path, *, commit: str, admission: str, opening_reference: str | None,
                             forward_fix_ref: str | None, code: str | None = None) -> None:
    """Refuse a deployment before anything is uploaded (``record_deployment`` re-checks it all); with
    ``code`` (known once the export is built), also what depends on it."""
    entries = read_ledger(directory)
    _require_resolved(entries)
    _deployment_rules(_summary(entries), commit=commit, admission=admission, opening_reference=opening_reference,
                      forward_fix_ref=forward_fix_ref, code=code)


def _deployment_rules(summary: dict, *, commit, admission, opening_reference, forward_fix_ref, code=None,
                      attempt: str | None = None) -> None:
    state = summary["state"]
    if summary["rolled_back"]:
        raise Refused("ROLLED_BACK")
    if state is None or STATES.index(state) < STATES.index("C8"):
        raise Refused("OUT_OF_ORDER", "the production deployment follows C8")
    if "GD1" not in summary["granted"]:
        raise Refused("GATE_NOT_GRANTED", "GD1")
    after_ponr = STATES.index(state) >= STATES.index(PONR_STATE)
    if after_ponr and forward_fix_ref in (None, "NONE"):
        # Every deployment after the PONR is a forward fix with its own GF1, whatever its commit (rereview R7).
        raise Refused("FORWARD_FIX_GATE_REQUIRED", "after the PONR every deployment needs its own GF1 grant")
    if forward_fix_ref not in (None, "NONE"):
        grants = [g["ref"] for g in summary["grants"] if g["gate"] == FORWARD_FIX_GATE]
        # consumed by a recorded deployment or by any attempt -- whatever its outcome -- but the one resolving
        used = {d["forward_fix_ref"] for d in summary["deployments"]}
        used |= {a["forward_fix_ref"] for a in summary["attempts"] if a["hash"] != attempt}
        if not after_ponr or forward_fix_ref not in grants or forward_fix_ref in used:
            raise Refused("FORWARD_FIX_GATE_REQUIRED", "a forward fix needs its own GF1 grant, after the PONR")
    elif commit != _effective_commit(summary):
        raise Refused("COMMIT_NOT_THE_REHEARSED_ONE",
                      "before a forward fix only the reviewed commit, or its recorded amendment, is deployed")
    if admission not in ("OPERATOR", "OPEN"):
        raise Refused("ADMISSION_INVALID")
    if admission == "OPEN":
        reference = summary["any_reference"]
        if reference is None or opening_reference != reference["hash"]:
            raise Refused("OPEN_WITHOUT_THE_REFERENCE", "an open deployment carries the recorded opening reference")
        if _barrier_applied(summary) is not None:
            raise Refused("BARRIER_APPLIED", "`resume` lifts the barrier before production is opened again")
        if code is not None and code in summary["unproven_codes"] and code != _authorized_code(summary):
            raise Refused("CODE_OF_AN_UNPROVEN_UPLOAD", "that code is never authorized: deploy another commit")
        if code is not None and code == _authorized_code(summary):
            if after_ponr:
                # It would admit users at its own address the moment it is up, before the ledger has recorded
                # it: after the PONR an open deployment always carries a code still to be authorized
                # (`authorize-code` sweeps the platform first).  Rereview of 1245bf2, M2.
                raise Refused("AUTHORIZED_CODE_NOT_REDEPLOYED_OPEN",
                              "after the PONR a code that is already authorized is redeployed operator-only")
            # an open deployment of the authorized code admits users at its own address once it is up
            _require_fresh(summary, reference)
    elif opening_reference not in (None, "NONE"):
        raise Refused("ADMISSION_INVALID", "an operator deployment carries no opening reference")


def _verified_times(summary: dict) -> tuple[list[datetime], list[datetime]]:
    """When verified generations (and object sets) were made, by the ledger's record: the generations
    it recorded and the ones a re-opening re-verified on disk (after C14 nothing else is recorded)."""
    database = [_parse(b["generation_at"]) for b in _generations(summary)]
    objects = [_parse(b["generation_at"]) for b in _generations(summary) if b["object_set_name"] != "NONE"]
    for authorization in summary["authorizations"]:
        for key, found in (("reopening_generation_at", database), ("reopening_objects_at", objects)):
            moment = _parse_or_none(authorization.get(key))
            if moment is not None:
                found.append(moment)
    return database, objects


def _require_fresh(summary: dict, reference: dict) -> None:
    """Before an act that lets users in (A19 R3 rereview R5): the newest verified generation within the
    cadence the reference recorded and the newest object set within its own."""
    database, objects = _verified_times(summary)
    cadence_hours = int(reference["backup_cadence_hours"])
    now = _CLOCK()
    if not database or not objects or now - max(database) > timedelta(hours=cadence_hours * CADENCE_TOLERANCE) \
            or now - max(objects) > timedelta(hours=OBJECT_CADENCE_HOURS * CADENCE_TOLERANCE):
        raise Refused("BACKUP_TOO_OLD_TO_OPEN", "record a new generation with objects first")


def recorded_deployment(directory: Path, deployment_id: str) -> dict:
    """The ``deployment`` entry ``deploy_audit deploy`` recorded for ``deployment_id`` (refused when none),
    refused too when it may not be promoted now (``_promotion_rules``)."""
    entries = read_ledger(directory)
    _require_resolved(entries)
    summary = _summary(entries)
    found = _deployment(summary, deployment_id)
    if found is None:
        raise Refused("DEPLOYMENT_NOT_RECORDED")
    _promotion_rules(summary, found)
    return found


def _promotion_rules(summary: dict, deployment: dict) -> None:
    """An open deployment reaches the public address only while its code is the one the ledger currently
    authorizes (A19 R3 M2): never a superseded code, never an amended one before its GC2."""
    if deployment["admission"] == "OPEN" and deployment["code_sha256"] != _authorized_code(summary):
        raise Refused("OPEN_DEPLOYMENT_NOT_AUTHORIZED", "only the code the ledger currently authorizes is promoted open")
    if deployment["admission"] == "OPEN":  # the public address lets users in (rereview R5)
        _require_fresh(summary, summary["any_reference"])
        if _barrier_applied(summary) is not None:  # rereview of b83b5fc, M4 (defence in depth)
            raise Refused("BARRIER_APPLIED", "`resume` lifts the barrier before an open deployment is promoted")
        if not _admitted(summary, deployment["deployment_id"]):
            raise Refused("DEPLOYMENT_NOT_ADMITTED", "admit the deployment (`admit-deployment`, `authorize-code`) first")


def begin_deployment(directory: Path, *, commit: str, admission: str, opening_reference: str | None,
                     forward_fix_ref: str | None, code: str, vercel_project_sha256: str,
                     held: bool = False) -> dict:
    """Reserve a deployment before anything is uploaded (rereview of 1245bf2, M2): every rule is checked
    with its code and a ``deployment_attempt`` is written, which consumes its GF1 at once.  The attempt is
    resolved by the ``deployment`` entry that records its upload, by ABORTED once the upload is removed, or
    by ``reconcile``; until then every other act is refused."""
    if not _hex64(code) or not _hex64(vercel_project_sha256):
        raise Refused("DEPLOYMENT_RECEIPT_INVALID", "code_sha256, vercel_project_sha256")
    with _lock(directory, held):
        entries = read_ledger(directory)
        _require_resolved(entries)
        summary = _summary(entries)
        _deployment_rules(summary, commit=commit, admission=admission, opening_reference=opening_reference,
                          forward_fix_ref=forward_fix_ref, code=code)
        recorded = _recorded_project(summary)
        if recorded is not None and vercel_project_sha256 != recorded:
            raise Refused("DEPLOYMENT_PROJECT_CHANGED", "every deployment goes to the one production project")
        return _append(directory, entries, {
            "type": "deployment_attempt", "commit": commit, "code_sha256": code, "admission": admission,
            "opening_reference": opening_reference or "NONE", "forward_fix_ref": forward_fix_ref or "NONE",
            "vercel_project_sha256": vercel_project_sha256, "outcome_required": True,
        })


def abort_attempt(directory: Path, attempt_sha256: str, *, held: bool = False) -> dict:
    """The attempt's upload was removed from the platform (or never made): ABORTED; its GF1 stays used."""
    with _lock(directory, held):
        entries = read_ledger(directory)
        pending = _unresolved(entries)
        if pending is None or pending["hash"] != attempt_sha256 or pending["type"] != "deployment_attempt":
            raise Refused("NOT_THE_UNRESOLVED_ATTEMPT")
        return _append(directory, entries, {"type": "outcome", "of": attempt_sha256, "result": "ABORTED",
                                            "resolved_by": "REMOVED"})


def record_deployment(directory: Path, receipt: dict, *, held: bool = False) -> dict:
    """Record a deployment ``deploy_audit deploy`` just made and verified against the platform's record: the
    upload of the unresolved attempt it names (``begin_deployment``), which it resolves."""
    with _lock(directory, held):
        entries = read_ledger(directory)
        summary = _summary(entries)
        if set(receipt) != set(_DEPLOYMENT_KEYS):
            raise Refused("DEPLOYMENT_RECEIPT_INVALID")
        pending = _unresolved(entries)
        if pending is None or pending["hash"] != receipt["attempt"] or pending["type"] != "deployment_attempt" \
                or any(pending[key] != receipt[key] for key in _ATTEMPT_KEYS):
            raise Refused("DEPLOYMENT_NOT_THE_ATTEMPT", "a deployment is recorded only as its reserved attempt")
        _deployment_rules(summary, commit=receipt["commit"], admission=receipt["admission"],
                          opening_reference=receipt["opening_reference"], forward_fix_ref=receipt["forward_fix_ref"],
                          code=receipt["code_sha256"], attempt=receipt["attempt"])
        if not _deployment_id(receipt["deployment_id"]) or _deployment(summary, receipt["deployment_id"]):
            raise Refused("DEPLOYMENT_RECEIPT_INVALID", "a deployment is recorded once")
        if summary["deployments"] and receipt["vercel_project_sha256"] != summary["deployments"][0]["vercel_project_sha256"]:
            raise Refused("DEPLOYMENT_PROJECT_CHANGED", "every deployment goes to the one production project")
        if receipt["admission"] == "OPERATOR" and receipt["observed_admission"] != "CLOSED":
            raise Refused("DEPLOYMENT_NOT_CLOSED", "an operator deployment must refuse users at its own address")
        if receipt["observed_deployment_id"] != receipt["deployment_id"]:
            # Admission binds the platform's own name for the process (A19 (17)): proven before it is recorded.
            raise Refused("DEPLOYMENT_IDENTITY_NOT_OBSERVED", "the deployment must name itself as the platform does")
        candidate = _candidate_code(summary)
        if receipt["forward_fix_ref"] == "NONE" and candidate is not None and receipt["code_sha256"] != candidate:
            raise Refused("DEPLOYMENT_CODE_CHANGED", "the same commit must run the same code")
        for key in ("url_sha256", "vercel_project_sha256", "deploy_tree_sha256", "code_sha256", "files_sha256"):
            if not _hex64(receipt[key]):
                raise Refused("DEPLOYMENT_RECEIPT_INVALID", key)
        return _append(directory, entries, {"type": "deployment", **receipt})


def begin_promotion(directory: Path, deployment_id: str, public_host_sha256: str, *, serving: str | None,
                    held: bool = False) -> dict:
    """Write the promotion BEFORE the public address is moved (rereview of 1245bf2, M1): every rule is
    checked now, and the entry takes effect only once ``complete_promotion`` (or ``reconcile``) has observed
    the address serving it; until then every other act is refused."""
    with _lock(directory, held):
        entries = read_ledger(directory)
        _require_resolved(entries)
        summary = _summary(entries)
        if summary["rolled_back"]:
            raise Refused("ROLLED_BACK")
        deployment = _deployment(summary, deployment_id or "")
        if deployment is None:
            raise Refused("DEPLOYMENT_NOT_RECORDED")
        _promotion_rules(summary, deployment)
        if not _hex64(public_host_sha256):
            raise Refused("ALIAS_NOT_THE_DEPLOYMENT")
        if serving == deployment_id:
            # A request that changes nothing cannot be told apart from its own effect, and could still apply
            # after a later promotion (rereview of b83b5fc, M2): it is never sent.
            raise Refused("PROMOTION_NOT_A_CHANGE", "the address already serves that deployment")
        return _append(directory, entries, {"type": "promotion", "deployment_id": deployment_id,
                                            "public_host_sha256": public_host_sha256,
                                            "serving_before": serving or "NONE", "outcome_required": True})


def complete_promotion(directory: Path, promotion_sha256: str, receipt: dict, *, held: bool = False) -> dict:
    """The address now serves the promoted deployment, as the platform and the address itself report it:
    COMMITTED.  Anything else leaves the promotion unresolved for ``reconcile``."""
    with _lock(directory, held):
        entries = read_ledger(directory)
        pending = _unresolved(entries)
        if pending is None or pending["hash"] != promotion_sha256 or pending["type"] != "promotion":
            raise Refused("NOT_THE_UNRESOLVED_PROMOTION")
        deployment = _deployment(_summary(entries), pending["deployment_id"])
        if receipt.get("files_sha256") != deployment["files_sha256"] or \
                receipt.get("observed_code") != deployment["code_sha256"]:
            raise Refused("DEPLOYMENT_NOT_THE_RECORDED_ONE", "the promotion stays unresolved: run `reconcile`")
        if receipt.get("alias_deployment_id") != deployment["deployment_id"] or \
                receipt.get("public_host_sha256") != pending["public_host_sha256"]:
            raise Refused("ALIAS_NOT_THE_DEPLOYMENT", "the promotion stays unresolved: run `reconcile`")
        _append(directory, entries, {"type": "outcome", "of": promotion_sha256, "result": "COMMITTED",
                                     "resolved_by": "OBSERVED"})
        return pending


# ---------------------------------------------------------------------------
# the opening
# ---------------------------------------------------------------------------


def take_reference(directory: Path, out: Path, root: Path, off_platform: Path, *, cadence_hours: int,
                   expect_head: str | None = None, observer: Observer | None = None) -> dict:
    """The C12 reference, taken by the ledger itself while admission is still CLOSED everywhere, and the
    opening authorization for the candidate's code, written into PROD with the reference entry."""
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
        project = _require_provider_project(summary, observer)
        if observer.admission() != "closed":
            raise Refused("ADMISSION_NOT_CLOSED", "the reference is taken before anyone but the operator is admitted")
        if observer.scheduler_front() != "enabled":
            # The production deployment carries CRON_SECRET since GD2 (C11); an address whose front is
            # disabled is an older deployment, and probing it would prove nothing about production.
            raise Refused("SCHEDULER_FRONT_NOT_ENABLED", "probe the production deployment (CRON_SECRET set at C11)")
        _require_closed_everywhere(summary, observer)
        identity = _production_database(summary, observer)
        if observer.opening_rows():
            # Only the reference writes an authorization: one already there was made before it.
            raise Refused("OPENING_AUTHORIZATION_EXISTS", "an opening was authorized before this reference")
        entered_c11 = summary["entered"]["C11"]
        recorded = [b for b in _generations(summary) if b["seq"] > entered_c11["seq"]
                    and _parse(b["generation_at"]) >= _parse(entered_c11["at"])]
        if not recorded or recorded[-1]["object_set_name"] == "NONE":
            raise Refused("PRE_OPEN_BACKUP_REQUIRED", "a verified generation with objects, recorded after C11")
        generation = observer.backup(Path(root), Path(off_platform), against_database=True)
        if (generation["manifest_sha256"], generation["dump_sha256"], generation["object_set"],
                generation["object_set_digest"]) != (recorded[-1]["manifest_sha256"], recorded[-1]["dump_sha256"],
                                                     recorded[-1]["object_set_name"], recorded[-1]["object_set_digest"]):
            raise Refused("BACKUP_NOT_THE_RECORDED_ONE")
        _check_generation_sources(summary, generation, identity)
        fingerprint = observer.fingerprint()
        if not observer.backup_matches(generation["manifest_path"], fingerprint):
            raise Refused("BACKUP_NOT_CURRENT", "the pre-opening backup does not hold the current business state")
        document = dict(fingerprint, taken_at=_now())
        pg_fingerprint.validate(document)
        code = _candidate_code(summary)
        out.write_text(json.dumps(document, sort_keys=True), encoding="ascii", newline="\n")

        def authorize(entry):
            try:
                observer.authorize(entry["hash"], code, entry, first=True)
            except Refused:
                out.unlink(missing_ok=True)  # aborted: no reference was taken
                raise

        # The reference takes effect only with its authorization committed in PROD (its outcome).
        return _commit_act(directory, entries, {
            "type": "reference", "reference_fingerprint_sha256": fingerprint["fingerprint_sha256"],
            "database_identity_sha256": identity, "admission": "CLOSED",
            "pre_open_backup_manifest_sha256": generation["manifest_sha256"],
            "backup_cadence_hours": cadence_hours, "rpo_hours": cadence_hours,
            "code_sha256": code, "vercel_project_sha256": project,
        }, authorize)


def open_admission(directory: Path, *, expect_head: str | None = None, observer: Observer | None = None) -> dict:
    """Enter C12: the public address serves the recorded open deployment, authorized and observed OPEN."""
    observer = observer or Observer()
    with _locked(directory):
        entries = read_ledger(directory)
        _check_head(entries, expect_head)
        summary = _summary(entries)
        _require_open_pending(summary, allow_reference=False)
        reference = summary["reference"]
        _require_the_deployment(summary, observer)
        project = _require_provider_project(summary, observer)
        serving = _deployment(summary, observer.alias_deployment())
        if serving is None or serving["admission"] != "OPEN" or serving["opening_reference"] != reference["hash"] \
                or serving["code_sha256"] != reference["code_sha256"]:
            raise Refused("ALIAS_NOT_THE_AUTHORIZED_DEPLOYMENT",
                          "the public address must serve the recorded open deployment of the candidate")
        if observer.deployment_files_sha256(serving["deployment_id"]) != serving["files_sha256"]:
            raise Refused("DEPLOYMENT_NOT_THE_RECORDED_ONE")
        if _barrier_applied(summary) is not None or not observer.writable():
            raise Refused("BARRIER_IN_FORCE", "`resume` lifts the barrier before production is opened again")
        if not observer.authorization_valid(reference["hash"], reference["code_sha256"], project,
                                            serving["deployment_id"]):
            raise Refused("OPENING_NOT_AUTHORIZED", "the PROD database holds no valid admission for this opening")
        if observer.admission() != "open":
            raise Refused("ADMISSION_NOT_OPEN")
        if observer.opening_tag() != hosting.opening_tag(reference["hash"]):
            # The open deployment must have been lifted with THIS reference entry's hash
            # (SGAA_OPENING_REFERENCE): unknowable before the entry exists and unique to this ledger.
            raise Refused("OPENING_NOT_BOUND_TO_THE_REFERENCE")
        if observer.code() != reference["code_sha256"]:
            raise Refused("DEPLOYMENT_CODE_CHANGED")
        _require_fresh(summary, reference)  # observed again: the cadence starts at the opening
        evidence = {
            "reference_fingerprint_sha256": reference["reference_fingerprint_sha256"],
            "database_identity_sha256": reference["database_identity_sha256"],
            "opened_at": _now(), "admission": "OPEN",
            "pre_open_backup_manifest_sha256": reference["pre_open_backup_manifest_sha256"],
            "backup_cadence_hours": reference["backup_cadence_hours"], "rpo_hours": reference["rpo_hours"],
            "opening_bound": True,
            "reference_age_seconds": int((_CLOCK() - _parse(reference["at"])).total_seconds()),
            "code_sha256": reference["code_sha256"], "deployment_id": serving["deployment_id"],
            "opening_authorized": True,
        }
        return _advance_locked(directory, entries, OPENING_STATE, evidence)


# ---------------------------------------------------------------------------
# closing, rolling back, resuming
# ---------------------------------------------------------------------------


def close(directory: Path, *, expect_head: str | None = None, observer: Observer | None = None) -> dict:
    """Revoke the opening authorization and apply the write barrier, then prove it in a fresh session."""
    observer = observer or Observer()
    with _locked(directory):
        entries = read_ledger(directory)
        _check_head(entries, expect_head)
        summary = _summary(entries)
        reference = _require_pending_opening(summary)
        if "GO" not in summary["granted"]:
            raise Refused("GATE_NOT_GRANTED", "GO")
        if _barrier_applied(summary) is not None:
            raise Refused("BARRIER_ALREADY_APPLIED")
        identity = _production_database(summary, observer)
        if identity != reference["database_identity_sha256"]:
            raise Refused("DATABASE_NOT_THE_REFERENCE")
        applied = observer.apply_barrier()
        body = {"type": "barrier", "action": "APPLIED", "barrier_at": applied["barrier_at"],
                "terminated_sessions": applied["terminated"], "database_identity_sha256": identity,
                "authorization": "REVOKED"}
        _require_barrier({**summary, "barriers": [*summary["barriers"], body]}, observer)
        return _append(directory, entries, body)


def resume(directory: Path, *, expect_head: str | None = None, observer: Observer | None = None,
           backup_root=None, off_platform=None) -> dict:
    """After a refused rollback: lift the barrier and restore the authorization (production goes forward).

    It lets users back in, so it first re-proves what the opening proved (A19 R3 rereview R5): every
    deployment the platform may serve is recorded, and the newest recorded generation, with objects, is
    within the cadence and found intact on disk and off-platform (the business state moved on: a
    refused rollback is exactly that, so it need not hold the current state).
    """
    observer = observer or Observer()
    with _locked(directory):
        entries = read_ledger(directory)
        _check_head(entries, expect_head)
        summary = _summary(entries)
        reference = _require_pending_opening(summary)
        identity = _production_database(summary, observer)
        # The ledger's record, or the database itself (a `close` that applied the barrier and then failed
        # its own verification wrote no entry, and its barrier must still be liftable).
        if _barrier_applied(summary) is None and observer.writable():
            raise Refused("BARRIER_NOT_APPLIED")
        _require_every_deployment_recorded(summary, observer)
        _require_reopening_backup(summary, observer, backup_root, off_platform, identity, require_current=False,
                                  reference=reference)
        current = _authorized_code(summary)
        # Written first; it takes effect with its PROD transaction (the marker commits with the lift), and a
        # lost answer leaves it to `reconcile` with every other act refused (rereview of b83b5fc, M4).
        entry = _commit_act(directory, entries, {
            "type": "barrier", "action": "LIFTED", "database_identity_sha256": identity,
            "authorization": "RESTORED" if current else "NONE",
        }, lambda entry: observer.lift_barrier(reference["hash"], current, entry))
    try:
        writable = observer.writable()
    except Refused as refusal:  # the lift is recorded: the operator binds the next command to the new head
        refusal.head = _head(read_ledger(directory))
        raise
    if not writable:  # recorded (the lift committed), yet a fresh session cannot write: say so
        raise Refused("BARRIER_STILL_IN_FORCE", "a fresh session still cannot write: `close`, then `resume`",
                      head=_head(read_ledger(directory)))
    return entry


def _admitted(summary: dict, deployment_id: str) -> bool:
    """Whether the ledger admitted users at that deployment: an ``admission`` or an ``authorization`` naming it."""
    return any(e.get("deployment_id") == deployment_id for e in (*summary["admissions"], *summary["authorizations"]))


def admit_deployment(directory: Path, deployment_id: str, *, expect_head: str | None = None,
                     observer: Observer | None = None) -> dict:
    """Before the point of no return: admit users at ONE recorded open deployment of the authorized code
    (rereview of b83b5fc, SPEC A19 (17)).

    The code's authorization alone admits no one: the application also needs PROD's admission of its own
    platform deployment.  Written for a deployment the governed deploy recorded (its platform identity
    observed), in the recorded project, holding the recorded files, under the opening reference; fresh
    backups first.  After the PONR a forward fix is admitted by its own ``authorize-code``.
    """
    observer = observer or Observer()
    with _locked(directory):
        entries = read_ledger(directory)
        _check_head(entries, expect_head)
        summary = _summary(entries)
        reference = _require_pending_opening(summary)
        if _barrier_applied(summary) is not None:
            raise Refused("BARRIER_APPLIED", "`resume` lifts the barrier before production is opened again")
        deployment = _deployment(summary, deployment_id)
        if deployment is None or deployment["admission"] != "OPEN" or deployment["forward_fix_ref"] != "NONE" \
                or deployment["opening_reference"] != reference["hash"]:
            raise Refused("NOT_AN_OPEN_DEPLOYMENT_OF_THE_REFERENCE")
        if deployment["code_sha256"] != _authorized_code(summary):
            raise Refused("OPEN_DEPLOYMENT_NOT_AUTHORIZED", "only the code the ledger currently authorizes is admitted")
        if _admitted(summary, deployment_id):
            raise Refused("DEPLOYMENT_ALREADY_ADMITTED")
        _require_fresh(summary, reference)
        identity = _production_database(summary, observer)
        if not observer.writable():  # a barrier `close` applied but could not record
            raise Refused("BARRIER_IN_FORCE", "`resume` lifts the barrier before production is opened again")
        project = _require_provider_project(summary, observer)
        if observer.deployment_files_sha256(deployment_id) != deployment["files_sha256"]:
            raise Refused("DEPLOYMENT_NOT_THE_RECORDED_ONE")
        return _commit_act(directory, entries, {
            "type": "admission", "opening_reference": reference["hash"], "deployment_id": deployment_id,
            "code_sha256": deployment["code_sha256"], "database_identity_sha256": identity,
            "vercel_project_sha256": project,
        }, lambda entry: observer.admit(reference["hash"], deployment_id, entry))


def _quiescent(observer: Observer) -> None:
    if observer.admission() != "closed":
        raise Refused("ADMISSION_STILL_OPEN", "stop admitting users before the proof")
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

    From C12 -- or C11 once a reference was taken, when users may already be admitted -- the write
    barrier must be in force (``close``): no session of the writers' role can write, whatever address
    or trigger reaches the database, and none started before it is left.  The ledger observes that in a
    fresh session before each fingerprint and again before the entry is written; it also observes the
    public address closed, the scheduler front disabled and no external trigger.  It then takes the
    current fingerprint live twice, ``QUIESCENCE_SECONDS`` apart.  The two must agree; the current one
    must equal the reference, or differ only by the fixed derived-write classes of ``pg_fingerprint``,
    verified row by row, which the operator must name exactly.  Anything else is a business write: no
    rollback, record the point of no return (C13).  The barrier stays: nothing lifts it after a
    recorded rollback.
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
        identity = _production_database(summary, observer)
        if identity != reference_entry["database_identity_sha256"]:
            raise Refused("DATABASE_NOT_THE_REFERENCE", "the database is not the one the reference was taken from")
        _require_barrier(summary, observer)
        _quiescent(observer)
        first = observer.classify(reference)
        _SLEEP(QUIESCENCE_SECONDS)
        _require_barrier(summary, observer)
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
        _require_barrier(summary, observer)  # nothing can have been written between the proof and the record
        return _append(directory, entries, {
            "type": "rollback", "from_state": current, "reason": reason, "quiescence": "PROVEN",
            "barrier": "VERIFIED", "current_fingerprint_sha256": verdict["current"]["fingerprint_sha256"],
            "derived_classes": verdict["derived_classes"],
        })


def _require_reopening_backup(summary: dict, observer: Observer, backup_root, off_platform, identity, *,
                              require_current: bool, reference: dict | None = None) -> dict:
    """A re-opening re-proves what the opening proved (A19 R3 M6): the newest recorded generation, with
    an object set, within the cadence the reference recorded (and the object set within its own), found
    intact on disk and in the off-platform copy, made from PROD -- and, before the PONR, holding the
    current business state.  Returns ``{"manifest_sha256", "generation_at", "objects_at"}``."""
    if backup_root is None or off_platform is None:
        raise Refused("BACKUP_ROOTS_REQUIRED", "a re-opening re-verifies the newest generation (--backup-root, --off-platform)")
    reference = reference or summary["opening_reference"]
    cadence_hours = int(reference["backup_cadence_hours"])
    if summary["state"] == STATES[-1]:
        # After the window closed the ledger records no generation (C14): the newest one on disk, made
        # from PROD and re-verified with its off-platform copy, must itself be within the cadence -- and its
        # object set within its own, by the set's own creation time (rereview R6).
        generation = observer.backup(Path(backup_root), Path(off_platform), against_database=True)
        made = _parse_or_none(generation.get("created_at"))
        objects_made = _parse_or_none(generation.get("object_created_at"))
        if not generation.get("object_set") or made is None or objects_made is None \
                or _CLOCK() - made > timedelta(hours=cadence_hours * CADENCE_TOLERANCE) \
                or _CLOCK() - objects_made > timedelta(hours=OBJECT_CADENCE_HOURS * CADENCE_TOLERANCE):
            raise Refused("BACKUP_TOO_OLD_TO_OPEN", "run a new generation with objects before re-opening")
        _check_generation_sources(summary, generation, identity)
        return {"manifest_sha256": generation["manifest_sha256"], "generation_at": generation["created_at"],
                "objects_at": generation["object_created_at"]}
    generations = _generations(summary)
    if not generations:
        raise Refused("PRE_OPEN_BACKUP_REQUIRED")
    newest = max(generations, key=lambda b: _parse(b["generation_at"]))
    object_sets = [b["generation_at"] for b in generations if b["object_set_name"] != "NONE"]
    if newest["object_set_name"] == "NONE" or not object_sets \
            or _CLOCK() - _parse(newest["generation_at"]) > timedelta(hours=cadence_hours * CADENCE_TOLERANCE) \
            or _CLOCK() - max(_parse(t) for t in object_sets) > timedelta(hours=OBJECT_CADENCE_HOURS * CADENCE_TOLERANCE):
        raise Refused("BACKUP_TOO_OLD_TO_OPEN", "record a new generation with objects before re-opening")
    generation = observer.backup(Path(backup_root), Path(off_platform), against_database=True)
    if (generation["manifest_sha256"], generation["dump_sha256"], generation["object_set"],
            generation["object_set_digest"]) != (newest["manifest_sha256"], newest["dump_sha256"],
                                                 newest["object_set_name"], newest["object_set_digest"]):
        raise Refused("BACKUP_NOT_THE_RECORDED_ONE")
    _check_generation_sources(summary, generation, identity)
    if require_current and not observer.backup_matches(generation["manifest_path"], observer.fingerprint()):
        raise Refused("BACKUP_NOT_CURRENT", "the newest backup does not hold the current business state")
    return {"manifest_sha256": newest["manifest_sha256"], "generation_at": newest["generation_at"],
            "objects_at": max(object_sets, key=_parse)}


def _require_every_deployment_recorded(summary: dict, observer: Observer) -> None:
    """No deployment the ledger never recorded may still be served when users are let back in."""
    _require_provider_project(summary, observer)
    for deployment in observer.provider_deployments():
        if deployment["state"] in TERMINAL_DEPLOYMENT_STATES:
            continue
        if _deployment(summary, deployment["id"]) is None:
            raise Refused("UNRECORDED_DEPLOYMENT", "a deployment the ledger never recorded may admit users")


def _require_deployment_gone(summary: dict, observer: Observer, deployment_id: str) -> None:
    """The platform no longer holds the deployment, or holds it failed or removed: no promotion can land."""
    _require_provider_project(summary, observer)
    for deployment in observer.provider_deployments():
        if deployment["id"] == deployment_id and deployment["state"] not in TERMINAL_DEPLOYMENT_STATES:
            raise Refused("PROMOTION_PENDING", "the platform may still apply it: `reconcile` again once it has, "
                          "or remove the deployment (`vercel remove`) and `reconcile`; never promote it again")


def supersede(directory: Path, *, expect_head: str | None = None, observer: Observer | None = None) -> dict:
    """Revoke in PROD every authorization of the opening reference whose code is not the one the ledger
    currently authorizes (A19 R3 M2).  Narrowing only: it admits no one, so it needs no gate."""
    observer = observer or Observer()
    with _locked(directory):
        entries = read_ledger(directory)
        _check_head(entries, expect_head)
        summary = _summary(entries)
        if summary["rolled_back"]:
            raise Refused("ROLLED_BACK")
        reference = summary["opening_reference"]
        if reference is None:
            raise Refused("OUT_OF_ORDER", "a supersession follows the opening")
        identity = _production_database(summary, observer)
        if identity != reference["database_identity_sha256"]:
            raise Refused("DATABASE_NOT_THE_REFERENCE")
        keep = _authorized_code(summary)
        return _commit_act(directory, entries, {
            "type": "supersession", "opening_reference": reference["hash"], "kept_code_sha256": keep or "NONE",
            "database_identity_sha256": identity,
        }, lambda entry: observer.supersede(reference["hash"], keep, entry))


def authorize_code(directory: Path, deployment_id: str, *, expect_head: str | None = None,
                   observer: Observer | None = None, contract_ref: str | None = None,
                   backup_root=None, off_platform=None) -> dict:
    """After the PONR: authorize a recorded forward-fix deployment's code under the opening reference.

    With ``contract_ref`` (SPEC A19), before the PONR: the GC2 re-opening of a product-contract
    amendment -- its recorded open deployment's code authorized under the same opening reference.
    """
    observer = observer or Observer()
    if contract_ref is not None:
        return _authorize_contract_code(directory, deployment_id, contract_ref, expect_head=expect_head,
                                        observer=observer, backup_root=backup_root, off_platform=off_platform)
    with _locked(directory):
        entries = read_ledger(directory)
        _check_head(entries, expect_head)
        summary = _summary(entries)
        if summary["rolled_back"]:
            raise Refused("ROLLED_BACK")
        if summary["state"] is None or STATES.index(summary["state"]) < STATES.index(PONR_STATE):
            raise Refused("GATE_ONLY_AFTER_PONR", "before the PONR only the candidate's code is authorized")
        deployment = _deployment(summary, deployment_id)
        reference = summary["opening_reference"]
        if deployment is None or deployment["forward_fix_ref"] == "NONE" or deployment["admission"] != "OPEN" \
                or deployment["opening_reference"] != reference["hash"]:
            raise Refused("NOT_A_RECORDED_FORWARD_FIX")
        if deployment["code_sha256"] in {reference["code_sha256"], *(a["code_sha256"] for a in summary["authorizations"])}:
            raise Refused("CODE_ALREADY_AUTHORIZED")
        if deployment["code_sha256"] in summary["unproven_codes"]:
            raise Refused("CODE_OF_AN_UNPROVEN_UPLOAD", "an upload of that code may still appear unrecorded")
        if _needs_attestation(summary):
            raise Refused("PONR_NOT_ATTESTED", "`attest-ponr` binds the declared C13 to its restore first")
        identity = _production_database(summary, observer)
        _require_every_deployment_recorded(summary, observer)
        backup = _require_reopening_backup(summary, observer, backup_root, off_platform, identity,
                                           require_current=False)
        return _commit_act(directory, entries, {
            "type": "authorization", "opening_reference": reference["hash"], "code_sha256": deployment["code_sha256"],
            "database_identity_sha256": identity, "vercel_project_sha256": deployment["vercel_project_sha256"],
            "deployment_id": deployment_id, "forward_fix_ref": deployment["forward_fix_ref"],
            "reopening_backup_manifest_sha256": backup["manifest_sha256"],
            "reopening_generation_at": backup["generation_at"], "reopening_objects_at": backup["objects_at"],
        }, lambda entry: observer.authorize(reference["hash"], deployment["code_sha256"], entry, first=False))


def _authorize_contract_code(directory: Path, deployment_id: str, contract_ref: str, *, expect_head,
                             observer, backup_root=None, off_platform=None) -> dict:
    with _locked(directory):
        entries = read_ledger(directory)
        _check_head(entries, expect_head)
        summary = _summary(entries)
        if summary["rolled_back"]:
            raise Refused("ROLLED_BACK")
        if summary["state"] != OPENING_STATE:
            raise Refused("OUT_OF_ORDER", "a re-opening of an amended candidate happens at C12, before the PONR")
        if _barrier_applied(summary) is not None:
            raise Refused("BARRIER_APPLIED", "`resume` lifts the barrier before production is opened again")
        _unused_contract_grant(summary, CONTRACT_REOPEN_GATE, contract_ref, "authorizations")
        reference = summary["opening_reference"]
        amendments = summary["amendments"]
        if not amendments or "contract_ref" not in amendments[-1] or amendments[-1]["seq"] < reference["seq"]:
            raise Refused("NO_CONTRACT_AMENDMENT", "the candidate is not a product-contract amendment (GC1)")
        deployment = _deployment(summary, deployment_id)
        if deployment is None or deployment["forward_fix_ref"] != "NONE" or deployment["admission"] != "OPEN" \
                or deployment["opening_reference"] != reference["hash"] \
                or deployment["seq"] < amendments[-1]["seq"]:
            raise Refused("NOT_A_RECORDED_REOPENING", "deploy the amended candidate open under the reference first")
        if deployment["code_sha256"] != _candidate_code(summary) or deployment["commit"] != _effective_commit(summary):
            raise Refused("DEPLOYMENT_CODE_CHANGED", "only the amended candidate's code is re-opened")
        if deployment["code_sha256"] in {reference["code_sha256"], *(a["code_sha256"] for a in summary["authorizations"])}:
            raise Refused("CODE_ALREADY_AUTHORIZED")
        if deployment["code_sha256"] in summary["unproven_codes"]:
            raise Refused("CODE_OF_AN_UNPROVEN_UPLOAD", "an upload of that code may still appear unrecorded")
        identity = _production_database(summary, observer)
        if not observer.writable():  # a barrier `close` applied but could not record
            raise Refused("BARRIER_IN_FORCE", "`resume` lifts the barrier before production is opened again")
        _require_every_deployment_recorded(summary, observer)
        backup = _require_reopening_backup(summary, observer, backup_root, off_platform, identity,
                                           require_current=True)
        return _commit_act(directory, entries, {
            "type": "authorization", "opening_reference": reference["hash"], "code_sha256": deployment["code_sha256"],
            "database_identity_sha256": identity, "vercel_project_sha256": deployment["vercel_project_sha256"],
            "deployment_id": deployment_id, "forward_fix_ref": "NONE", "contract_ref": contract_ref,
            "reopening_backup_manifest_sha256": backup["manifest_sha256"],
            "reopening_generation_at": backup["generation_at"], "reopening_objects_at": backup["objects_at"],
        }, lambda entry: observer.authorize(reference["hash"], deployment["code_sha256"], entry, first=False))


def reconcile(directory: Path, *, expect_head: str | None = None, observer: Observer | None = None,
              abandon_upload: bool = False) -> dict:
    """Resolve the act whose PROD outcome is unknown (A19 R3 rereview R2): read in PROD whether its
    transaction committed (its marker), after waiting for any act still running, and record the outcome.

    ABORTED is recorded only on proof.  An upload that never returned its deployment's identity has none:
    an empty listing proves nothing (rereview of d0fbba7).  It stays unresolved -- every act refused --
    until the operator explicitly abandons it (``abandon_upload``): ABANDONED, not ABORTED.  That is safe
    because a late copy of it is never recordable, so never admitted (A19 (17)); its GF1 and its code
    stay spent (16).  It is refused while the platform holds any deployment the ledger never recorded."""
    observer = observer or Observer()
    with _locked(directory):
        entries = read_ledger(directory)
        if expect_head is not None and expect_head != _head(entries):
            raise Refused("HEAD_MISMATCH", "the ledger does not end where the operator last saw it")
        pending = _unresolved(entries)
        if pending is None:
            raise Refused("NOTHING_TO_RECONCILE")
        summary = _summary(entries)
        if abandon_upload and pending["type"] != "deployment_attempt":
            raise Refused("NOT_AN_UPLOAD", "only an upload whose outcome is unknown is abandoned")
        if pending["type"] == "deployment_attempt":
            # Its upload, if the platform made it, is a deployment the ledger never recorded: it must be removed
            # (it is never recorded late) before the attempt is closed.  Not seeing it proves nothing.
            _require_every_deployment_recorded(summary, observer)
            if not abandon_upload:
                raise Refused("UPLOAD_OUTCOME_UNPROVEN", "nothing proves the upload failed: wait and `reconcile`, "
                              "or abandon it explicitly (`reconcile --abandon-upload`)")
            return _append(directory, entries, {"type": "outcome", "of": pending["hash"], "result": "ABANDONED",
                                                "resolved_by": "OPERATOR"})
        elif pending["type"] == "promotion":
            # Observed in the recorded project at the recorded address only (rereview of b83b5fc, M3).  A
            # promotion is sent only when it changes what the address serves (M2): the address serving its
            # deployment is then this request's own effect.
            _require_provider_project(summary, observer)
            if observer.host_sha256() != pending["public_host_sha256"]:
                raise Refused("ADDRESS_NOT_THE_PROMOTION", "observe the public address the promotion was sent for")
            committed = observer.alias_deployment() == pending["deployment_id"]
            if not committed:
                # An unchanged address proves nothing: the platform may still apply a promotion it accepted
                # (rereview of 2fdeee6, M1).  ABORTED only once its deployment can never be served.
                _require_deployment_gone(summary, observer, pending["deployment_id"])
        else:
            _production_database(summary, observer)
            committed = observer.operation_committed(pending["hash"])
        return _append(directory, entries, {"type": "outcome", "of": pending["hash"],
                                            "result": "COMMITTED" if committed else "ABORTED",
                                            "resolved_by": "RECONCILED"})


def init(directory: Path) -> dict:
    with _locked(directory):
        if (Path(directory) / LEDGER_FILE).exists():
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
        "qualified": summary["qualification"] is not None,
        "barrier": summary["barriers"][-1]["action"] if summary["barriers"] else "NONE",
        "unresolved_operation": (_unresolved(entries) or {}).get("hash"),
        # The value SGAA_OPENING_REFERENCE carries (also after a refused rollback, to re-open).
        "opening_reference": _opening_reference(summary),
    }


def _opening_reference(summary: dict):
    if summary["state"] == "C11" and summary["reference"] is not None:
        return summary["reference"]["hash"]
    if summary["state"] is not None and STATES.index(summary["state"]) >= STATES.index(OPENING_STATE):
        return summary["opening_reference"]["hash"] if summary["opening_reference"] else None
    return None


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


def _provider(args):
    team, project = getattr(args, "vercel_team", None), getattr(args, "vercel_project", None)
    if not (team and project):
        return None
    from tools import vercel_provider

    return vercel_provider.VercelCli(team_id=team, project_id=project)


def main(argv=None, *, out=None, err=None) -> int:
    out = out or sys.stdout
    err = err or sys.stderr
    parser = argparse.ArgumentParser(prog="cutover_ledger", allow_abbrev=False)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "status", "verify"):
        commands.add_parser(name, allow_abbrev=False).add_argument("--ledger-dir", required=True)
    bound = ("grant", "advance", "amend", "qualify", "rollback", "reference", "open", "close", "resume",
             "authorize-code", "supersede", "reconcile", "attest-ponr", "admit-deployment")
    for name in bound:
        sub = commands.add_parser(name, allow_abbrev=False)
        sub.add_argument("--ledger-dir", required=True)
        sub.add_argument("--expect-head", default=None,
                         help="the head printed by the previous command; refuses a truncated ledger")
        if name == "reconcile":
            sub.add_argument("--abandon-upload", action="store_true",
                             help="close an upload whose outcome is unknown as ABANDONED (never ABORTED)")
        if name in {"rollback", "reference", "open", "reconcile"}:
            sub.add_argument("--base-url", default=None, help="the public address, probed without any credential")
            sub.add_argument("--allow-insecure", action="store_true", help="tests only: accept http")
        if name in {"reference", "open", "authorize-code", "resume", "reconcile", "admit-deployment"}:
            sub.add_argument("--vercel-team", default=None, help="the team id of the production project")
            sub.add_argument("--vercel-project", default=None, help="the production project's id")
        if name == "resume":
            sub.add_argument("--backup-root", default=None, help="the ops_backup primary directory (re-verified)")
            sub.add_argument("--off-platform", default=None, help="the ops_backup off-platform directory")
        if name == "reference":
            sub.add_argument("--backup-root", required=True, help="the ops_backup primary directory")
            sub.add_argument("--off-platform", required=True, help="the ops_backup off-platform directory")
        if name == "grant":
            sub.add_argument("--gate", required=True)
            sub.add_argument("--ref", required=True)
        elif name == "advance":
            sub.add_argument("--state", required=True)
            sub.add_argument("--evidence", required=True, help="a JSON file of value-free evidence")
        elif name == "amend":
            sub.add_argument("--commit", required=True, help="the amendment commit (the pages on top)")
            sub.add_argument("--ref", required=True, help="an opaque code of the user's message")
            sub.add_argument("--contract-ref", default=None,
                             help="A19: the GC1 grant's reference (a product-contract amendment at C12)")
        elif name == "reference":
            sub.add_argument("--out", required=True, help="a new file in the custody directory")
            sub.add_argument("--backup-cadence-hours", required=True, type=int)
        elif name == "rollback":
            sub.add_argument("--reason", required=True, help="a fixed code, e.g. SMOKE_FAILED")
            sub.add_argument("--reference", default=None, help="from the opening: the reference fingerprint file")
            sub.add_argument("--derived-class", action="append", default=None,
                             help="from the opening: each derived-write class the ledger observed, named exactly")
        elif name == "admit-deployment":
            sub.add_argument("--deployment", required=True, help="the recorded open deployment id")
        elif name == "authorize-code":
            sub.add_argument("--deployment", required=True, help="the recorded forward-fix deployment id")
            sub.add_argument("--contract-ref", default=None,
                             help="A19, before the PONR: the GC2 grant's reference (re-open the amended candidate)")
            sub.add_argument("--backup-root", default=None, help="the ops_backup primary directory (re-verified)")
            sub.add_argument("--off-platform", default=None, help="the ops_backup off-platform directory")
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
        observer = Observer(getattr(args, "base_url", None), allow_insecure=getattr(args, "allow_insecure", False),
                            provider=_provider(args))
        if args.command == "init":
            result = init(directory)
        elif args.command == "grant":
            result = grant(directory, args.gate, args.ref, expect_head=args.expect_head)
        elif args.command == "amend":
            result = amend(directory, args.commit, args.ref, expect_head=args.expect_head,
                           contract_ref=args.contract_ref, observer=observer if args.contract_ref else None)
        elif args.command == "advance":
            result = advance(directory, args.state, _load_evidence(args.evidence), expect_head=args.expect_head,
                             observer=observer)
        elif args.command == "qualify":
            result = qualify(directory, expect_head=args.expect_head, observer=observer)
        elif args.command == "reference":
            result = take_reference(directory, Path(args.out), Path(args.backup_root), Path(args.off_platform),
                                    cadence_hours=args.backup_cadence_hours, expect_head=args.expect_head,
                                    observer=observer)
        elif args.command == "open":
            result = open_admission(directory, expect_head=args.expect_head, observer=observer)
        elif args.command == "close":
            result = close(directory, expect_head=args.expect_head, observer=observer)
        elif args.command == "resume":
            result = resume(directory, expect_head=args.expect_head, observer=observer, backup_root=args.backup_root,
                            off_platform=args.off_platform)
        elif args.command == "reconcile":
            result = reconcile(directory, expect_head=args.expect_head, observer=observer,
                               abandon_upload=args.abandon_upload)
        elif args.command == "attest-ponr":
            result = attest_ponr(directory, expect_head=args.expect_head, observer=observer)
        elif args.command == "supersede":
            result = supersede(directory, expect_head=args.expect_head, observer=observer)
        elif args.command == "rollback":
            result = rollback(directory, args.reason, expect_head=args.expect_head, observer=observer,
                              reference_path=args.reference, derived_classes=args.derived_class)
        elif args.command == "authorize-code":
            result = authorize_code(directory, args.deployment, expect_head=args.expect_head, observer=observer,
                                    contract_ref=args.contract_ref, backup_root=args.backup_root,
                                    off_platform=args.off_platform)
        elif args.command == "admit-deployment":
            result = admit_deployment(directory, args.deployment, expect_head=args.expect_head, observer=observer)
        elif args.command == "status":
            result = status(directory)
        else:
            result = {"chain": "OK", "head": _head(read_ledger(directory))}
    except Refused as refusal:
        err.write(f"cutover-ledger: refused: {refusal.code}\n")
        if refusal.head:  # the act wrote its own entries before it was refused: the next command binds to them
            err.write(f"cutover-ledger: head: {refusal.head}\n")
        return 1
    if "hash" in result:  # an appended entry: print the ledger's new head (an act's outcome follows its entry)
        result = {**result, "head": _head(read_ledger(directory))}
    json.dump(result, out, sort_keys=True)
    out.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
