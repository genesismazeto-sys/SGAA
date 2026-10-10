# coding: utf-8
"""Cutover evidence ledger -- operator tool, never imported by ``app/``.

WHY THIS EXISTS
    The production cutover is a sequence of gated, partly irreversible states
    (``docs/specs/MP-3-production-integration.md`` section 3.3).  This tool is
    its memory and its referee, not its hands: it validates that a state may
    be entered, that the evidence for it is complete and VALUE-FREE, that every
    gate it needs was granted, and that the identities carried from state to
    state (frozen source, prepared copy, reference digest, deployed commit,
    opening fingerprint) never change.  It executes nothing and talks to no
    database or provider.

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
    init      create the ledger (the directory must not hold one)
    grant     record that the user granted a gate (an opaque reference only)
    advance   enter the next state with its evidence
    rollback  record a rollback; refused once the point of no return is
              recorded, and from C12 only with the current fingerprint equal
              to the opening reference (proof that nothing was written)
    status    current state, granted gates, head, chain verdict
    verify    chain verdict and head only

Exit codes: 0 done, 1 refused (code on stderr), 2 usage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

LEDGER_FILE = "ledger.jsonl"
LOCK_FILE = ".ledger.lock"
MAX_EVIDENCE_BYTES = 8192

STATES = (
    "C0", "C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C10", "C11", "C12", "C13", "C14",
)
ENTRY_TYPES = frozenset({"init", "advance", "grant", "rollback"})
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
    "C0": {"commit": _hex40, "runbook_sha256": _hex64, "rehearsal_index_sha256": _hex64,
           "review_verdict": _equals("PASS")},
    "C1": {"pg_major": lambda v: _int(v) and v >= 15, "schema_current": _true, "rows": _zero, "objects": _zero,
           "data_api_toggle_off": _true, "data_api_probe": _equals("NOT_SERVED"),
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
    "C9": {"commit": _hex40, "readiness": _equals("READY"), "bundle_audit": _equals("CLEAN"),
           "scheduler_front": _equals("DISABLED")},
    "C10": {"smoke": _equals("PASS"), "write_set_ok": _true},
    "C11": {"account_key_match": _true, "mirror_passes": lambda v: _nonneg(v) and v >= 1,
            "reconciliation_required": _zero, "scheduler_front": _equals("ENABLED")},
    "C12": {"reference_fingerprint_sha256": _hex64, "opened_at": _stamp},
    "C13": {"write_class": lambda v: isinstance(v, str) and bool(_CLASS.fullmatch(v)),
            "detected_at": _stamp, "current_fingerprint_sha256": _hex64, "adjudicated_by_operator": _true},
    "C14": {"window_days": lambda v: _int(v) and v >= 1, "second_generation_restore": _equals("OK"),
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
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
    for entry in entries:
        kind = entry["type"]
        if kind == "advance":
            state = entry["state"]
            rolled_back = False
            carried[entry["state"]] = entry["evidence"]
        elif kind == "grant":
            granted[entry["gate"]] = entry["ref"]
        elif kind == "rollback":
            rolled_back = True
    return {"state": state, "granted": granted, "rolled_back": rolled_back, "evidence": carried}


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
    if state == "C13" and evidence["current_fingerprint_sha256"] == _evidence_of(summary, "C12").get(
        "reference_fingerprint_sha256"
    ):
        raise Refused("NO_FINGERPRINT_DELTA", "a business write changes the fingerprint; this one equals the opening")


def advance(directory: Path, state: str, evidence: dict, *, expect_head: str | None = None) -> dict:
    with _locked(directory):
        entries = read_ledger(directory)
        _check_head(entries, expect_head)
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


def rollback(directory: Path, reason: str, *, expect_head: str | None = None,
             current_fingerprint: str | None = None, derived_classes: list[str] | None = None) -> dict:
    """Record the rollback.  From C12 it needs the current business fingerprint: equal to the opening's,
    or -- when a known derived write (a re-hash, a derived rejection) changed it -- accompanied by the
    operator's explicit, recorded adjudication naming the changed tables or classes."""
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
        if current == "C12":
            reference = _evidence_of(summary, "C12").get("reference_fingerprint_sha256")
            if current_fingerprint is None or not _HEX64.fullmatch(current_fingerprint):
                raise Refused("FINGERPRINT_REQUIRED", "from C12 a rollback needs the current fingerprint")
            if current_fingerprint != reference:
                classes = sorted(set(derived_classes or ()))
                if not classes or len(classes) > 16 or not all(_CLASS.fullmatch(c or "") for c in classes):
                    raise Refused("FINGERPRINT_CHANGED", "a business table changed since the opening: "
                                  "record the PONR, or adjudicate the change as derived by naming its classes")
                return _append(directory, entries, {
                    "type": "rollback", "from_state": current, "reason": reason,
                    "adjudicated_derived_classes": classes, "current_fingerprint_sha256": current_fingerprint,
                })
        return _append(directory, entries, {"type": "rollback", "from_state": current or "NONE", "reason": reason})


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


def _snapshot_digest(path: str, directory: Path) -> str:
    """The fingerprint digest of a snapshot FILE: a valid, untampered snapshot taken after the last entry."""
    from tools import pg_fingerprint

    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        pg_fingerprint.validate(document)
    except (OSError, ValueError):
        raise Refused("SNAPSHOT_UNREADABLE") from None
    except pg_fingerprint.Refused:
        raise Refused("SNAPSHOT_INVALID") from None
    # The time the snapshot tool wrote into the file (a copy keeps it, so an old reference cannot pass).
    taken_at = document.get("taken_at")
    if not isinstance(taken_at, str) or not _STAMP.fullmatch(taken_at):
        raise Refused("SNAPSHOT_STALE", "the snapshot carries no time of its own; take a new one")
    entries = read_ledger(directory)
    if entries and taken_at < entries[-1]["at"]:  # fixed-width UTC stamps order as text
        raise Refused("SNAPSHOT_STALE", "take the snapshot after the last ledger entry")
    return document["fingerprint_sha256"]


def main(argv=None, *, out=None, err=None) -> int:
    out = out or sys.stdout
    err = err or sys.stderr
    parser = argparse.ArgumentParser(prog="cutover_ledger", allow_abbrev=False)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "status", "verify"):
        commands.add_parser(name, allow_abbrev=False).add_argument("--ledger-dir", required=True)
    for name in ("grant", "advance", "rollback"):
        sub = commands.add_parser(name, allow_abbrev=False)
        sub.add_argument("--ledger-dir", required=True)
        sub.add_argument("--expect-head", default=None,
                         help="the head printed by the previous command; refuses a truncated ledger")
        if name == "grant":
            sub.add_argument("--gate", required=True)
            sub.add_argument("--ref", required=True)
        elif name == "advance":
            sub.add_argument("--state", required=True)
            sub.add_argument("--evidence", required=True, help="a JSON file of value-free evidence")
        else:
            sub.add_argument("--reason", required=True, help="a fixed code, e.g. SMOKE_FAILED")
            sub.add_argument("--current-snapshot", default=None,
                             help="from C12: a fingerprint snapshot file taken after the last entry "
                                  "(its digest must equal the opening's)")
            sub.add_argument("--derived-class", action="append", default=None,
                             help="from C12: adjudicate a changed fingerprint as a known derived write; "
                                  "repeat for each changed table (recorded in the ledger)")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 2
    if args.command in {"grant", "advance", "rollback"} and not args.expect_head:
        # The head printed by the previous command is what makes a truncated or replaced ledger visible.
        err.write("cutover-ledger: refused: HEAD_REQUIRED\n")
        return 1
    try:
        directory = _ledger_dir(args.ledger_dir, must_exist=args.command != "init")
        if args.command == "init":
            result = init(directory)
        elif args.command == "grant":
            result = grant(directory, args.gate, args.ref, expect_head=args.expect_head)
        elif args.command == "advance":
            result = advance(directory, args.state, _load_evidence(args.evidence), expect_head=args.expect_head)
        elif args.command == "rollback":
            fingerprint = _snapshot_digest(args.current_snapshot, directory) if args.current_snapshot else None
            result = rollback(directory, args.reason, expect_head=args.expect_head,
                              current_fingerprint=fingerprint, derived_classes=args.derived_class)
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
