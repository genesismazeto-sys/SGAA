# coding: utf-8
"""MP-3 slices 5 and the R3 remediation: the cutover evidence ledger (``tools/cutover_ledger.py``).

The ledger is the cutover's memory and referee: order, gates, value-free evidence, carried
identities, the hash chain, the head binding and the point of no return.  Where the SPEC forbids
trusting the operator's word -- the opening (C12), a rollback from it, the backups that must exist
before it and through the window -- the ledger observes for itself through an ``Observer``; here a
scripted one stands in for the public address, the database and the backup directories, and a
scripted clock for time.  Each test names the defect it would catch.
"""

from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import hosting
from tests.mp3_ledger_support import ALL_GATES, COMMIT, GOOD, H, OTHER_COMMIT
from tests.mp3_ledger_support import manifest_digest as _manifest
from tools import cutover_ledger as ledger
from tools import pg_fingerprint as fp

_TABLES = {"alunos": {"rows": 1, "sha256": "d" * 64, "columns": ["id"], "row_hashes": {"1": ["h"]}}}
REFERENCE = {"format": fp.FORMAT, "tables": _TABLES, "fingerprint_sha256": fp._digest_of(_TABLES)}
_CHANGED = {"alunos": {"rows": 1, "sha256": "e" * 64, "columns": ["id"], "row_hashes": {"1": ["i"]}}}
CHANGED = {"format": fp.FORMAT, "tables": _CHANGED, "fingerprint_sha256": fp._digest_of(_CHANGED)}
IDENTITY = H["j"]


class FakeObserver:
    """Scripted eyes: the admission and scheduler state, external jobs, identity, fingerprints, backups."""

    def __init__(self):
        self.admission_state = "closed"
        self.scheduler = "enabled"  # production after GD2; a rollback disables it first
        self.jobs = 0
        self.identity = IDENTITY
        self.current = REFERENCE
        self.verdicts: list[dict] = []
        self.generation = {"database_set": "sgaa-pg-x-auto-scheduled", "manifest_sha256": _manifest(0),
                           "manifest_path": "unused", "object_set": "20261101T000000Z-auto-weekly",
                           "object_set_digest": H["g"]}
        self.matches = True
        self.backup_calls: list[bool] = []
        self.host = H["m"]  # the public address proven at C10
        self.tag = ""  # set to the reference entry's tag once the deployment is lifted with it
        self._made = 0

    def admission(self):
        return self.admission_state

    def scheduler_front(self):
        return self.scheduler

    def external_trigger_jobs(self):
        return self.jobs

    def database_identity(self):
        return self.identity

    def fingerprint(self):
        return self.current

    def classify(self, reference):
        if self.verdicts:
            return self.verdicts.pop(0)
        return {"identical": True, "derived_classes": [], "refusal": None, "current": reference}

    def host_sha256(self):
        return self.host

    def opening_tag(self):
        return self.tag

    def backup(self, root, off_platform, *, against_database):
        self.backup_calls.append(against_database)
        generation = dict(self.generation)
        if "created_at" not in generation:  # made just now (a second apart, so each is newer)
            self._made += 1
            generation["created_at"] = (ledger._CLOCK() + timedelta(seconds=self._made)).strftime("%Y-%m-%dT%H:%M:%SZ")
        return generation

    def backup_matches(self, manifest_path, fingerprint):
        return self.matches


_CLOCK_STATE: dict = {}


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    global _CLOCK_STATE
    state = {"now": datetime(2026, 11, 1, 8, 0, 0, tzinfo=timezone.utc), "slept": []}
    _CLOCK_STATE = state

    def sleep(seconds):
        state["slept"].append(seconds)
        state["now"] += timedelta(seconds=seconds)

    monkeypatch.setattr(ledger, "_CLOCK", lambda: state["now"])
    monkeypatch.setattr(ledger, "_SLEEP", sleep)
    return state


@pytest.fixture
def directory(tmp_path):
    path = tmp_path / "cutover-ledger"
    ledger.init(path)
    return path


@pytest.fixture
def observer():
    return FakeObserver()


def _grant_all(directory, gates=ALL_GATES):
    for index, gate in enumerate(gates):
        ledger.grant(directory, gate, f"user-msg-{index}")


def _reference_file(directory, name="reference.json"):
    return directory.parent / name


def _open(directory, observer):
    """C11 -> C12 the only way: a post-C11 backup, the reference while closed, then open."""
    _set_clock(ledger._CLOCK() + timedelta(minutes=1))  # the generation is made after C11
    ledger.record_backup(directory, directory.parent, directory.parent, observer=observer)
    taken = ledger.take_reference(directory, _reference_file(directory), directory.parent, directory.parent,
                                  cadence_hours=24, observer=observer)
    _lift(observer, taken)
    return ledger.open_admission(directory, observer=observer)


def _lift(observer, taken):
    """GO: SGAA_ADMISSION=open and SGAA_OPENING_REFERENCE = the reference entry's hash, redeployed."""
    observer.admission_state = "open"
    observer.tag = hosting.opening_tag(taken["hash"])


def _drive(directory, upto, overrides=None, observer=None):
    """Advance through every state up to and including ``upto``."""
    overrides = overrides or {}
    observer = observer or FakeObserver()
    for state in ledger.STATES[: ledger.STATES.index(upto) + 1]:
        if state == "C12":
            _open(directory, observer)
            continue
        if state == "C13":
            _set_clock(ledger._CLOCK() + timedelta(hours=1))  # a business write some time after the opening
        if state == "C14":
            _window(directory, observer, days=30)
        evidence = dict(GOOD[state])
        evidence.update(overrides.get(state, {}))
        ledger.advance(directory, state, evidence)
    return observer


def _window(directory, observer, days, *, every_hours=24, objects_every_days=7, skip=()):
    """Let ``days`` pass after C13, one recorded generation every ``every_hours`` (objects weekly)."""
    clock = ledger._CLOCK
    start = clock()
    for step in range(1, days * 24 // every_hours + 1):
        moment = start + timedelta(hours=step * every_hours)
        _set_clock(moment)
        day = step * every_hours // 24
        if day in skip:
            continue
        observer.generation = dict(observer.generation, manifest_sha256=_manifest(day),
                                   object_set=f"week-{day // objects_every_days}")
        ledger.record_backup(directory, directory.parent, directory.parent, observer=observer)
    _set_clock(start + timedelta(days=days, minutes=1))


def _set_clock(moment):
    _CLOCK_STATE["now"] = moment


def _code(call, *args, **kwargs):
    with pytest.raises(ledger.Refused) as caught:
        call(*args, **kwargs)
    return caught.value.code


# ---- order, gates and evidence ------------------------------------------------------------------


def test_a_clean_cutover_runs_c0_to_c14_and_status_reports_the_position(directory):
    _grant_all(directory)
    _drive(directory, "C14")
    status = ledger.status(directory)
    assert status["state"] == "C14" and status["state_name"] == "WINDOW_CLOSED"
    assert status["ponr_recorded"] is True and status["next_state"] is None and status["chain"] == "OK"


def test_the_first_state_must_be_c0_and_no_state_can_be_skipped(directory):
    _grant_all(directory)
    assert _code(ledger.advance, directory, "C1", GOOD["C1"]) == "OUT_OF_ORDER"
    ledger.advance(directory, "C0", GOOD["C0"])
    assert _code(ledger.advance, directory, "C3", GOOD["C3"]) == "OUT_OF_ORDER"
    assert _code(ledger.advance, directory, "C0", GOOD["C0"]) == "OUT_OF_ORDER"
    assert _code(ledger.advance, directory, "C99", {}) == "UNKNOWN_STATE"


def test_a_state_is_refused_until_every_gate_it_needs_is_granted(directory):
    ledger.advance(directory, "C0", GOOD["C0"])
    assert _code(ledger.advance, directory, "C1", GOOD["C1"]) == "GATE_NOT_GRANTED"
    ledger.grant(directory, "GP0", "m1")
    ledger.grant(directory, "GP1", "m2")
    assert _code(ledger.advance, directory, "C1", GOOD["C1"]) == "GATE_NOT_GRANTED"  # GP2 still missing
    ledger.grant(directory, "GP2", "m3")
    assert ledger.advance(directory, "C1", GOOD["C1"])["state"] == "C1"


def test_a_gate_is_granted_once_and_only_a_known_gate_with_an_opaque_reference(directory):
    ledger.grant(directory, "GR0", "m1")
    assert _code(ledger.grant, directory, "GR0", "m2") == "GATE_ALREADY_GRANTED"
    assert _code(ledger.grant, directory, "GZ9", "m3") == "UNKNOWN_GATE"
    assert _code(ledger.grant, directory, "GR1", "the user said go ahead") == "REFERENCE_NOT_OPAQUE"
    assert _code(ledger.grant, directory, "GR1", "") == "REFERENCE_NOT_OPAQUE"


@pytest.mark.parametrize(
    "evidence",
    [
        {**GOOD["C2"], "census": {"NOTE": "student Maria Silva"}},   # a name
        {**GOOD["C2"], "census": {"NOTE": "maria@example.org"}},     # an address
        {**GOOD["C2"], "census": {"NOTE": "C:\\Users\\someone\\x"}},  # a path
        {**GOOD["C2"], "census": {"NOTE": "https://example.org/x"}},  # a URL
        {**GOOD["C2"], "census": {"deep": {"a": {"b": {"c": 1}}}}},   # nesting
        {**GOOD["C2"], "census": {"bad key": 1}},
        {**GOOD["C2"], "census": {"X": 1.5}},
        {**GOOD["C2"], "census": {"X": None}},
    ],
)
def test_evidence_that_is_not_value_free_is_refused_before_anything_is_written(directory, evidence):
    _grant_all(directory)
    _drive(directory, "C1")
    before = (directory / ledger.LEDGER_FILE).read_text()
    assert _code(ledger.advance, directory, "C2", evidence).startswith("EVIDENCE_")
    assert (directory / ledger.LEDGER_FILE).read_text() == before


# One value per key that its predicate must refuse; together with GOOD this pins every predicate.
BAD = {
    "C0": {"commit": "abc", "runbook_sha256": "xyz", "rehearsal_index_sha256": H["a"][:-1], "review_verdict": "FAIL",
           "prod_project_sha256": "uckadhcwfknklmdktuyi"},
    "C1": {"pg_major": 14, "schema_current": False, "rows": 3, "objects": 1, "data_api_toggle_off": False,
           "data_api_override": "SKIPPED", "data_api_probe": "SERVED", "data_api_project_sha256": "nope",
           "api_exposure_clean": False, "capacity_ok": False},
    "C2": {"database_bytes": -1, "document_bytes": "1", "census": {}},
    "C3": {"source_size": 0, "source_sha256": "nope", "wal_bytes": 12},
    "C4": {"source_sha256": "nope", "prepared_sha256": "nope", "integrity_ok": False, "fk_violations": 1,
           "schema_version": 15, "accepted_exceptions": "none", "accepted_by_user": False},
    "C5": {"prepared_sha256": "nope", "converged_rows": -4, "unconverged": [{"class": "lower", "count": 1}],
           "legacy_bytes_touched": 1},
    "C6": {"prepared_sha256": "nope", "reference_digest": "nope", "verdict": "DIRTY"},
    "C7": {"prepared_sha256": "nope", "pathb_exit": 1, "commit_resolved_by_inspection": "yes",
           "commit_outcome": "UNKNOWN"},
    "C8": {"reference_digest": "nope", "census_equal": False, "baseline_manifest_sha256": "nope",
           "object_set_digest": "nope", "restore_drill": "FAILED", "verify_backup": "FAILED",
           "admin_bootstrap": "MAYBE"},
    "C9": {"commit": "nope", "readiness": "NOT_READY", "bundle_audit": "FINDINGS", "deploy_verify": "DIFFERS",
           "deploy_tree_sha256": "nope", "scheduler_front": "ENABLED", "admission": "OPEN"},
    "C10": {"smoke": "FAIL", "write_set_ok": False, "admission": "OPEN", "data_api_project_sha256": "nope",
            "public_host_sha256": "nope"},
    "C11": {"account_key_match": False, "mirror_passes": 0, "reconciliation_required": 2,
            "scheduler_front": "DISABLED", "admission": "OPEN"},
    "C13": {"write_class": "a request", "detected_at": "later", "current_fingerprint_sha256": "nope",
            "adjudicated_by_operator": False},
    "C14": {"restore_validated_manifest_sha256": "nope", "restore_drill": "SKIPPED", "unresolved_reconciliation": 1,
            "object_set_verified": False},
}


@pytest.mark.parametrize("state", [s for s in ledger.STATES if s != "C12"])
def test_every_evidence_predicate_refuses_a_bad_value_and_a_missing_key(directory, state):
    assert set(BAD[state]) == set(GOOD[state]), "the table must cover every key"
    _grant_all(directory)
    observer = FakeObserver()
    if state != "C0":
        _drive(directory, ledger.STATES[ledger.STATES.index(state) - 1], observer=observer)
    if state == "C14":
        _window(directory, observer, days=30)
    for key, bad in BAD[state].items():
        refused = _code(ledger.advance, directory, state, {**GOOD[state], key: bad})
        assert refused.startswith("EVIDENCE_"), (state, key, refused)
        missing = {k: v for k, v in GOOD[state].items() if k != key}
        assert _code(ledger.advance, directory, state, missing) == "EVIDENCE_INVALID", (state, key)
    assert _code(ledger.advance, directory, state, {**GOOD[state], "extra_note": "x"}) == "EVIDENCE_UNEXPECTED_KEY"
    ledger.advance(directory, state, GOOD[state])  # the good evidence is accepted after every refusal


def test_booleans_are_never_accepted_where_a_number_is_required(directory):
    _grant_all(directory)
    _drive(directory, "C0")
    assert _code(ledger.advance, directory, "C1", {**GOOD["C1"], "rows": False}) == "EVIDENCE_INVALID"
    assert _code(ledger.advance, directory, "C1", {**GOOD["C1"], "pg_major": True}) == "EVIDENCE_INVALID"


def test_the_frozen_source_identity_cannot_change_between_c3_and_c4(directory):
    _grant_all(directory)
    _drive(directory, "C3")
    assert _code(ledger.advance, directory, "C4", {**GOOD["C4"], "source_sha256": H["h"]}) == "SOURCE_IDENTITY_CHANGED"


def test_the_prepared_copy_identity_is_carried_through_c5_c6_c7(directory):
    _grant_all(directory)
    _drive(directory, "C4")
    assert _code(ledger.advance, directory, "C5", {**GOOD["C5"], "prepared_sha256": H["h"]}) == "PREPARED_IDENTITY_CHANGED"
    ledger.advance(directory, "C5", GOOD["C5"])
    assert _code(ledger.advance, directory, "C6", {**GOOD["C6"], "prepared_sha256": H["h"]}) == "PREPARED_IDENTITY_CHANGED"
    ledger.advance(directory, "C6", GOOD["C6"])
    assert _code(ledger.advance, directory, "C7", {**GOOD["C7"], "prepared_sha256": H["a"]}) == "PREPARED_IDENTITY_CHANGED"


@pytest.mark.parametrize(
    "unconverged",
    [
        [],                                                              # fewer than accepted
        [{"class": "TRASHED_LEGACY", "count": 3}],                       # more of an accepted class
        [{"class": "TRASHED_LEGACY", "count": 2}, {"class": "FAILED_LEGACY", "count": 1}],  # a new class
        [{"class": "OTHER_CLASS", "count": 2}],                          # a different class
    ],
)
def test_only_the_exact_exceptions_the_user_accepted_at_c4_may_remain_unconverged(directory, unconverged):
    _grant_all(directory)
    _drive(directory, "C4")
    assert _code(ledger.advance, directory, "C5", {**GOOD["C5"], "unconverged": unconverged}) == \
        "UNCONVERGED_ROWS_NOT_ACCEPTED"


def test_a_commit_uncertain_pathb_exit_needs_the_inspection_to_be_stated(directory):
    _grant_all(directory)
    _drive(directory, "C6")
    uncertain = {**GOOD["C7"], "pathb_exit": 3, "commit_resolved_by_inspection": False}
    assert _code(ledger.advance, directory, "C7", uncertain) == "COMMIT_UNCERTAIN_NOT_RESOLVED"
    resolved = {**GOOD["C7"], "pathb_exit": 3, "commit_resolved_by_inspection": True}
    assert ledger.advance(directory, "C7", resolved)["state"] == "C7"


def test_the_target_must_reproduce_the_converged_sources_reference_digest(directory):
    _grant_all(directory)
    _drive(directory, "C7")
    assert _code(ledger.advance, directory, "C8", {**GOOD["C8"], "reference_digest": H["h"]}) == "REFERENCE_DIGEST_MISMATCH"
    assert ledger.advance(directory, "C8", GOOD["C8"])["state"] == "C8"


def test_an_administrator_bootstrap_needs_its_own_gate(directory):
    _grant_all(directory)
    _drive(directory, "C7")
    done = {**GOOD["C8"], "admin_bootstrap": "DONE"}
    assert _code(ledger.advance, directory, "C8", done) == "GATE_NOT_GRANTED"
    ledger.grant(directory, "GP3", "m-bootstrap")
    assert ledger.advance(directory, "C8", done)["state"] == "C8"


def test_the_deployed_commit_must_be_the_rehearsed_commit(directory):
    _grant_all(directory)
    _drive(directory, "C8")
    assert _code(ledger.advance, directory, "C9", {**GOOD["C9"], "commit": OTHER_COMMIT}) == \
        "COMMIT_NOT_THE_REHEARSED_ONE"


def test_the_data_api_proof_at_c1_must_name_the_prod_project_gp0_named(directory):
    _grant_all(directory)
    _drive(directory, "C0")
    assert _code(ledger.advance, directory, "C1", {**GOOD["C1"], "data_api_project_sha256": H["a"]}) == \
        "DATA_API_NOT_THE_PROD_PROJECT"
    assert ledger.advance(directory, "C1", GOOD["C1"])["state"] == "C1"


def test_the_smokes_data_api_proof_must_name_the_project_qualified_at_c1(directory):
    _grant_all(directory)
    _drive(directory, "C9")
    assert _code(ledger.advance, directory, "C10", {**GOOD["C10"], "data_api_project_sha256": H["a"]}) == \
        "DATA_API_PROJECT_CHANGED"
    assert ledger.advance(directory, "C10", GOOD["C10"])["state"] == "C10"


def test_a_gate_does_not_cover_a_state_it_is_not_listed_for(directory):
    # GO opens users (C12); having it must not let C11 (mirror) be entered without its own gates.
    ledger.grant(directory, "GO", "m1")
    assert ledger.STATE_GATES["C11"] == ("GG1", "GG2", "GD2") and "GO" not in ledger.STATE_GATES["C11"]
    assert [s for s in ledger.STATES if "GO" in ledger.STATE_GATES[s]] == ["C12"]


# ---- admission: closed until GO, and GO is the only opening (finding 1) -------------------------


def test_admission_is_closed_in_every_state_before_the_opening_and_c12_is_never_typed(directory):
    _grant_all(directory)
    for state in ("C9", "C10", "C11"):
        assert ledger._SCHEMA[state]["admission"]("CLOSED") and not ledger._SCHEMA[state]["admission"]("OPEN")
    _drive(directory, "C11")
    typed = {"reference_fingerprint_sha256": H["h"], "database_identity_sha256": IDENTITY,
             "opened_at": "2026-11-01T09:00:00Z", "admission": "OPEN", "pre_open_backup_manifest_sha256": H["a"],
             "backup_cadence_hours": 24, "rpo_hours": 24}
    assert _code(ledger.advance, directory, "C12", typed) == "OPENING_NEEDS_THE_OPEN_COMMAND"


def test_the_opening_needs_go_a_reference_taken_while_closed_and_admission_observed_open(directory, observer):
    _grant_all(directory, ALL_GATES[:-1])  # everything but GO
    _drive(directory, "C11", observer=observer)
    ledger.record_backup(directory, directory.parent, directory.parent, observer=observer)
    assert _code(ledger.take_reference, directory, _reference_file(directory), directory.parent, directory.parent,
                 cadence_hours=24, observer=observer) == "GATE_NOT_GRANTED"
    ledger.grant(directory, "GO", "m-go")
    assert _code(ledger.open_admission, directory, observer=observer) == "REFERENCE_REQUIRED"
    observer.admission_state = "open"  # users already admitted: too late for a reference
    assert _code(ledger.take_reference, directory, _reference_file(directory), directory.parent, directory.parent,
                 cadence_hours=24, observer=observer) == "ADMISSION_NOT_CLOSED"
    observer.admission_state = "closed"
    entry = ledger.take_reference(directory, _reference_file(directory), directory.parent, directory.parent,
                                  cadence_hours=24, observer=observer)
    assert entry["type"] == "reference" and entry["admission"] == "CLOSED"
    assert entry["reference_fingerprint_sha256"] == REFERENCE["fingerprint_sha256"]
    written = json.loads(_reference_file(directory).read_text())
    assert fp.validate(written)["fingerprint_sha256"] == REFERENCE["fingerprint_sha256"] and written["taken_at"]
    assert _code(ledger.open_admission, directory, observer=observer) == "ADMISSION_NOT_OPEN"  # not lifted yet
    _lift(observer, entry)
    opened = ledger.open_admission(directory, observer=observer)
    assert opened["state"] == "C12"
    assert opened["evidence"]["reference_fingerprint_sha256"] == REFERENCE["fingerprint_sha256"]
    assert opened["evidence"]["admission"] == "OPEN" and opened["evidence"]["backup_cadence_hours"] == 24


def test_one_reference_per_opening_whatever_its_age_and_the_lift_must_carry_it(directory, observer, clock):
    _grant_all(directory)
    _drive(directory, "C11", observer=observer)
    ledger.record_backup(directory, directory.parent, directory.parent, observer=observer)
    taken = ledger.take_reference(directory, _reference_file(directory), directory.parent, directory.parent,
                                  cadence_hours=24, observer=observer)
    # A second reference would re-baseline whatever users wrote after a premature lift.
    assert _code(ledger.take_reference, directory, _reference_file(directory, "second.json"), directory.parent,
                 directory.parent, cadence_hours=24, observer=observer) == "REFERENCE_ALREADY_TAKEN"
    observer.admission_state = "open"
    # Lifted with another value, with none, or with the fingerprint digest (computable in advance by a
    # snapshot): only the reference entry's hash, which exists once the ledger recorded it, binds.
    for announced in (hosting.opening_tag(H["a"]), "", hosting.opening_tag(REFERENCE["fingerprint_sha256"])):
        observer.tag = announced
        assert _code(ledger.open_admission, directory, observer=observer) == "OPENING_NOT_BOUND_TO_THE_REFERENCE"
    observer.tag = hosting.opening_tag(taken["hash"])
    clock["now"] += timedelta(hours=3)  # a late lift is still after the reference: no dead end
    opened = ledger.open_admission(directory, observer=observer)
    assert opened["evidence"]["opening_bound"] is True and opened["evidence"]["reference_age_seconds"] == 3 * 3600


def test_the_reference_is_taken_at_the_production_deployment_whose_scheduler_front_is_enabled(directory, observer):
    """An older deployment (no CRON_SECRET) answers closed for ever; probing it would prove nothing."""
    _grant_all(directory)
    _drive(directory, "C11", observer=observer)
    ledger.record_backup(directory, directory.parent, directory.parent, observer=observer)
    observer.scheduler = "disabled"
    assert _code(ledger.take_reference, directory, _reference_file(directory), directory.parent, directory.parent,
                 cadence_hours=24, observer=observer) == "SCHEDULER_FRONT_NOT_ENABLED"


def test_the_opening_needs_a_generation_within_the_cadence(directory, observer, clock):
    _grant_all(directory)
    _drive(directory, "C11", observer=observer)
    ledger.record_backup(directory, directory.parent, directory.parent, observer=observer)
    taken = ledger.take_reference(directory, _reference_file(directory), directory.parent, directory.parent,
                                  cadence_hours=24, observer=observer)
    _lift(observer, taken)
    clock["now"] += timedelta(hours=37)  # longer than 1.5 x 24 h since the pre-opening generation
    assert _code(ledger.open_admission, directory, observer=observer) == "BACKUP_TOO_OLD_TO_OPEN"
    observer.generation = dict(observer.generation, manifest_sha256=_manifest(7))
    ledger.record_backup(directory, directory.parent, directory.parent, observer=observer)  # still allowed at C11
    assert ledger.open_admission(directory, observer=observer)["state"] == "C12"


def test_plain_http_is_observed_only_on_the_loopback():
    for url in ("http://sgaa.example.test", "http://10.0.0.5:8080"):
        observer = ledger.Observer(url, allow_insecure=True)
        for probe in (observer.admission, observer.scheduler_front, observer.opening_tag):
            with pytest.raises(ledger.Refused) as caught:
                probe()
            assert caught.value.code == "INSECURE_ONLY_ON_LOOPBACK"
    assert ledger.Observer("http://127.0.0.1:1", allow_insecure=True)._require_base() == "http://127.0.0.1:1"
    with pytest.raises(ledger.Refused):
        ledger.Observer("http://127.0.0.1:1", allow_insecure=True,
                        scheduler_url="http://sgaa.example.test").scheduler_front()


def test_every_observation_probes_the_public_address_proven_at_c10(directory, observer):
    _grant_all(directory)
    _drive(directory, "C11", observer=observer)
    ledger.record_backup(directory, directory.parent, directory.parent, observer=observer)
    take = (ledger.take_reference, directory, _reference_file(directory), directory.parent, directory.parent)
    observer.host = H["a"]
    assert _code(*take, cadence_hours=24, observer=observer) == "ADDRESS_NOT_THE_DEPLOYMENT"
    observer.host = H["m"]
    taken = ledger.take_reference(*take[1:], cadence_hours=24, observer=observer)
    _lift(observer, taken)
    observer.host = H["a"]
    assert _code(ledger.open_admission, directory, observer=observer) == "ADDRESS_NOT_THE_DEPLOYMENT"
    observer.host = H["m"]
    ledger.open_admission(directory, observer=observer)
    observer.admission_state, observer.scheduler = "closed", "disabled"
    observer.host = H["a"]  # another, closed deployment would fake the quiescence of the open one
    assert _code(ledger.rollback, directory, "OPERATOR_STOP", observer=observer,
                 reference_path=str(_reference_file(directory))) == "ADDRESS_NOT_THE_DEPLOYMENT"


def test_each_generation_is_recorded_once_and_by_its_own_time(directory, observer, clock):
    _grant_all(directory)
    _drive(directory, "C11", observer=observer)
    record = (ledger.record_backup, directory, directory.parent, directory.parent)
    ledger.record_backup(*record[1:], observer=observer)
    assert _code(*record, observer=observer) == "BACKUP_ALREADY_RECORDED"  # re-recording would fake the cadence
    stamp = lambda moment: moment.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    observer.generation = dict(observer.generation, manifest_sha256=_manifest(5),
                               created_at=stamp(clock["now"] - timedelta(days=1)))
    assert _code(*record, observer=observer) == "BACKUP_OLDER_THAN_RECORDED"
    for bad in (stamp(clock["now"] + timedelta(hours=1)), "yesterday", None):
        observer.generation = dict(observer.generation, created_at=bad)
        assert _code(*record, observer=observer) == "BACKUP_TIME_INVALID"


def test_the_pre_opening_generation_must_be_made_after_c11(directory, observer, clock):
    _grant_all(directory)
    _drive(directory, "C10", observer=observer)
    made_before = (clock["now"] - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ledger.advance(directory, "C11", GOOD["C11"])
    observer.generation = dict(observer.generation, created_at=made_before)
    ledger.record_backup(directory, directory.parent, directory.parent, observer=observer)  # recorded after C11
    assert _code(ledger.take_reference, directory, _reference_file(directory), directory.parent, directory.parent,
                 cadence_hours=24, observer=observer) == "PRE_OPEN_BACKUP_REQUIRED"


def test_the_command_line_runs_as_a_script_from_anywhere(tmp_path):
    """The runbook runs `python tools/cutover_ledger.py`: its observing commands must import their tools."""
    import subprocess
    import sys

    directory = tmp_path / "ledger"
    ledger.init(directory)
    _grant_all(directory)
    for state in ledger.STATES[: ledger.STATES.index("C11") + 1]:
        ledger.advance(directory, state, GOOD[state])
    done = subprocess.run(
        [sys.executable, str(Path(ledger.__file__)), "record-backup", "--ledger-dir", str(directory),
         "--expect-head", ledger.status(directory)["head"], "--backup-root", str(tmp_path / "none"),
         "--off-platform", str(tmp_path / "off")],
        cwd=tmp_path, capture_output=True, text=True, timeout=180)
    assert done.returncode == 1 and "BACKUP_NO_GENERATION" in done.stderr, done.stderr[-400:]


def test_the_reference_and_the_opening_follow_c11_only_and_never_a_rollback(directory, observer):
    _grant_all(directory)
    _drive(directory, "C10", observer=observer)
    take = (ledger.take_reference, directory, _reference_file(directory), directory.parent, directory.parent)
    assert _code(*take, cadence_hours=24, observer=observer) == "OUT_OF_ORDER"
    assert _code(ledger.open_admission, directory, observer=observer) == "OUT_OF_ORDER"
    ledger.advance(directory, "C11", GOOD["C11"])
    ledger.record_backup(directory, directory.parent, directory.parent, observer=observer)
    ledger.rollback(directory, "OPERATOR_STOP")  # before any reference: a plain record
    assert _code(*take, cadence_hours=24, observer=observer) == "ROLLED_BACK"
    assert _code(ledger.open_admission, directory, observer=observer) == "ROLLED_BACK"


# ---- backup before opening and through the window (finding 4) -----------------------------------


def test_backups_are_recorded_from_c11_only_and_never_after_a_rollback(directory, observer):
    _grant_all(directory)
    _drive(directory, "C10", observer=observer)
    assert _code(ledger.record_backup, directory, directory.parent, directory.parent,
                 observer=observer) == "OUT_OF_ORDER"
    ledger.advance(directory, "C11", GOOD["C11"])
    entry = ledger.record_backup(directory, directory.parent, directory.parent, observer=observer)
    assert entry["type"] == "backup" and entry["off_platform"] == "VERIFIED"
    assert entry["manifest_sha256"] == _manifest(0) and observer.backup_calls == [False]
    ledger.rollback(directory, "OPERATOR_STOP")
    assert _code(ledger.record_backup, directory, directory.parent, directory.parent, observer=observer) == "ROLLED_BACK"


def test_the_reference_needs_a_post_c11_backup_with_objects_proven_current_against_the_live_database(
        directory, observer):
    _grant_all(directory)
    _drive(directory, "C11", observer=observer)
    take = (ledger.take_reference, directory, _reference_file(directory), directory.parent, directory.parent)
    assert _code(*take, cadence_hours=24, observer=observer) == "PRE_OPEN_BACKUP_REQUIRED"
    observer.generation = dict(observer.generation, object_set=None, object_set_digest=None)
    ledger.record_backup(directory, directory.parent, directory.parent, observer=observer)
    assert _code(*take, cadence_hours=24, observer=observer) == "PRE_OPEN_BACKUP_REQUIRED"  # no object set
    observer.generation = dict(observer.generation, manifest_sha256=_manifest(1),
                               object_set="20261101T000000Z-auto-weekly", object_set_digest=H["g"])
    ledger.record_backup(directory, directory.parent, directory.parent, observer=observer)
    observer.generation = dict(observer.generation, manifest_sha256=_manifest(99))  # a newer, unrecorded one
    assert _code(*take, cadence_hours=24, observer=observer) == "BACKUP_NOT_THE_RECORDED_ONE"
    observer.generation = dict(observer.generation, manifest_sha256=_manifest(1))
    observer.matches = False
    assert _code(*take, cadence_hours=24, observer=observer) == "BACKUP_NOT_CURRENT"
    observer.matches = True
    for bad in (0, 25, True):
        assert _code(*take, cadence_hours=bad, observer=observer) == "CADENCE_INVALID"
    entry = ledger.take_reference(*take[1:], cadence_hours=24, observer=observer)
    assert entry["pre_open_backup_manifest_sha256"] == _manifest(1) and entry["rpo_hours"] == 24
    assert observer.backup_calls[-1] is True  # the object set was compared with the live rows


def test_the_reference_file_is_new_and_outside_the_repository(directory, observer):
    _grant_all(directory)
    _drive(directory, "C11", observer=observer)
    ledger.record_backup(directory, directory.parent, directory.parent, observer=observer)
    inside = Path(ledger.__file__).resolve().parents[1] / "reference-should-not-exist.json"
    assert _code(ledger.take_reference, directory, inside, directory.parent, directory.parent, cadence_hours=24,
                 observer=observer) == "OUTPUT_INSIDE_REPOSITORY"
    existing = _reference_file(directory, "existing.json")
    existing.write_text("{}")
    assert _code(ledger.take_reference, directory, existing, directory.parent, directory.parent, cadence_hours=24,
                 observer=observer) == "OUTPUT_EXISTS"
    assert not inside.exists()


def test_the_window_closes_only_after_ud4_days_from_the_ponr(directory, observer):
    _grant_all(directory)
    _drive(directory, "C13", observer=observer)
    _window(directory, observer, days=29)
    assert _code(ledger.advance, directory, "C14", {**GOOD["C14"], "restore_validated_manifest_sha256": _manifest(29)}) \
        == "WINDOW_NOT_ELAPSED"


@pytest.mark.parametrize("skip,code", [
    ((10, 11), "BACKUP_CADENCE_BROKEN"),        # two nightly generations missing in the window
    ((), None),
])
def test_the_backup_cadence_must_hold_over_the_whole_window(directory, observer, skip, code):
    _grant_all(directory)
    _drive(directory, "C13", observer=observer)
    _window(directory, observer, days=30, skip=skip)
    if code:
        assert _code(ledger.advance, directory, "C14", GOOD["C14"]) == code
    else:
        assert ledger.advance(directory, "C14", GOOD["C14"])["state"] == "C14"


@pytest.mark.parametrize("missing,code", [
    ((1, 2, 3), "BACKUP_CADENCE_BROKEN"),   # a gap between the opening and the PONR, made up before C13
    ((), None),
])
def test_the_cadence_counts_from_the_opening_not_only_from_the_ponr(directory, observer, missing, code):
    _grant_all(directory)
    _drive(directory, "C12", observer=observer)
    opened = ledger._CLOCK()
    for day in range(1, 11):
        if day in missing:
            continue
        _set_clock(opened + timedelta(days=day))
        observer.generation = dict(observer.generation, manifest_sha256=_manifest(100 + day),
                                   object_set=f"open-week-{day // 7}")
        ledger.record_backup(directory, directory.parent, directory.parent, observer=observer)
    ledger.advance(directory, "C13", GOOD["C13"])
    _window(directory, observer, days=30)
    if code:
        assert _code(ledger.advance, directory, "C14", GOOD["C14"]) == code
    else:
        assert ledger.advance(directory, "C14", GOOD["C14"])["state"] == "C14"


def test_the_window_is_counted_from_the_ponr_not_from_the_opening(directory, observer):
    _grant_all(directory)
    _drive(directory, "C12", observer=observer)
    opened = ledger._CLOCK()
    for day in range(1, 6):  # five days pending, the cadence held
        _set_clock(opened + timedelta(days=day))
        observer.generation = dict(observer.generation, manifest_sha256=_manifest(200 + day))
        ledger.record_backup(directory, directory.parent, directory.parent, observer=observer)
    ledger.advance(directory, "C13", GOOD["C13"])
    _window(directory, observer, days=29)  # 34 days after the opening, 29 after the PONR
    assert _code(ledger.advance, directory, "C14", {**GOOD["C14"], "restore_validated_manifest_sha256": _manifest(29)}) \
        == "WINDOW_NOT_ELAPSED"


def _stamp(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_the_cadence_is_measured_by_when_generations_were_made_not_when_they_were_recorded(directory, observer):
    _grant_all(directory)
    _drive(directory, "C13", observer=observer)
    start = ledger._CLOCK()
    for day in range(1, 31):  # recorded daily, but all made within the first hour (a burst passed off as a cadence)
        _set_clock(start + timedelta(days=day))
        observer.generation = dict(observer.generation, manifest_sha256=_manifest(300 + day),
                                   object_set=f"burst-{day // 7}", created_at=_stamp(start + timedelta(minutes=day)))
        ledger.record_backup(directory, directory.parent, directory.parent, observer=observer)
    _set_clock(start + timedelta(days=30, minutes=1))
    validated = {**GOOD["C14"], "restore_validated_manifest_sha256": _manifest(330)}
    assert _code(ledger.advance, directory, "C14", validated) == "BACKUP_CADENCE_BROKEN"


def test_a_generation_made_before_the_ponr_is_not_a_window_generation_whenever_it_was_recorded(directory, observer):
    _grant_all(directory)
    _drive(directory, "C13", observer=observer)  # the PONR an hour after the opening
    ponr = ledger._CLOCK()
    _set_clock(ponr + timedelta(hours=1))
    observer.generation = dict(observer.generation, manifest_sha256=_manifest(400),
                               created_at=_stamp(ponr - timedelta(minutes=30)))  # made before C13, recorded after
    ledger.record_backup(directory, directory.parent, directory.parent, observer=observer)
    observer.generation = {k: v for k, v in observer.generation.items() if k != "created_at"}
    _window(directory, observer, days=30)
    validated = {**GOOD["C14"], "restore_validated_manifest_sha256": _manifest(400)}
    assert _code(ledger.advance, directory, "C14", validated) == "RESTORE_VALIDATION_NOT_A_WINDOW_GENERATION"


def test_the_object_sets_must_be_taken_weekly_through_the_window(directory, observer):
    _grant_all(directory)
    _drive(directory, "C13", observer=observer)
    _window(directory, observer, days=30, objects_every_days=12)
    assert _code(ledger.advance, directory, "C14", GOOD["C14"]) == "OBJECT_CADENCE_BROKEN"


def test_the_restore_drill_must_be_of_a_generation_recorded_inside_the_window(directory, observer):
    _grant_all(directory)
    _drive(directory, "C13", observer=observer)
    _window(directory, observer, days=30)
    before_ponr = {**GOOD["C14"], "restore_validated_manifest_sha256": _manifest(0)}
    assert _code(ledger.advance, directory, "C14", before_ponr) == "RESTORE_VALIDATION_NOT_A_WINDOW_GENERATION"


# ---- rollback ---------------------------------------------------------------------------------------


def test_rollback_is_recorded_before_the_point_of_no_return_and_ends_the_cutover(directory):
    _grant_all(directory)
    _drive(directory, "C11")
    entry = ledger.rollback(directory, "SMOKE_REGRESSION")
    assert entry["from_state"] == "C11"
    assert ledger.status(directory)["rolled_back"] is True
    assert _code(ledger.advance, directory, "C13", GOOD["C13"]) == "ROLLED_BACK"
    assert _code(ledger.rollback, directory, "AGAIN") == "ALREADY_ROLLED_BACK"


@pytest.mark.parametrize("state", ledger.STATES[: ledger.STATES.index("C12")])
def test_a_rollback_is_recorded_from_every_state_before_the_opening(directory, state):
    _grant_all(directory)
    _drive(directory, state)
    entry = ledger.rollback(directory, "OPERATOR_STOP")
    assert entry["from_state"] == state
    summary = ledger.status(directory)
    assert summary["rolled_back"] is True and summary["state"] == state and summary["ponr_recorded"] is False
    following = ledger.STATES[ledger.STATES.index(state) + 1]
    if following != "C12":
        assert _code(ledger.advance, directory, following, GOOD[following]) == "ROLLED_BACK"
    assert ledger.read_ledger(directory)[-1]["type"] == "rollback"  # and the chain still verifies on read


def _opened(directory, observer):
    _grant_all(directory)
    _drive(directory, "C12", observer=observer)
    observer.admission_state = "closed"  # the operator stopped admitting users and redeployed
    observer.scheduler = "disabled"  # and removed CRON_SECRET
    return str(_reference_file(directory))


def test_a_rollback_from_the_opening_with_nothing_changed_is_recorded_after_observed_quiescence(
        directory, observer, clock):
    reference = _opened(directory, observer)
    entry = ledger.rollback(directory, "OPERATOR_STOP", observer=observer, reference_path=reference)
    assert entry["from_state"] == "C12" and entry["quiescence"] == "PROVEN" and entry["derived_classes"] == []
    assert entry["current_fingerprint_sha256"] == REFERENCE["fingerprint_sha256"]
    assert clock["slept"] == [ledger.QUIESCENCE_SECONDS]


@pytest.mark.parametrize("setup,code", [
    (lambda o: setattr(o, "admission_state", "open"), "ADMISSION_STILL_OPEN"),
    (lambda o: setattr(o, "admission_state", "unknown"), "ADMISSION_STILL_OPEN"),
    (lambda o: setattr(o, "scheduler", "enabled"), "SCHEDULER_STILL_ENABLED"),
    (lambda o: setattr(o, "scheduler", "unknown"), "SCHEDULER_STILL_ENABLED"),
    (lambda o: setattr(o, "jobs", 1), "EXTERNAL_TRIGGER_ACTIVE"),
    (lambda o: setattr(o, "jobs", -1), "QUIESCENCE_UNVERIFIABLE"),
    (lambda o: setattr(o, "identity", H["a"]), "DATABASE_NOT_THE_REFERENCE"),
])
def test_a_rollback_from_the_opening_refuses_until_production_is_proven_quiescent(directory, observer, setup, code):
    reference = _opened(directory, observer)
    setup(observer)
    before = (directory / ledger.LEDGER_FILE).read_text()
    assert _code(ledger.rollback, directory, "OPERATOR_STOP", observer=observer, reference_path=reference) == code
    assert (directory / ledger.LEDGER_FILE).read_text() == before


def test_a_rollback_from_the_opening_needs_the_observer_and_the_reference_file_the_ledger_recorded(
        directory, observer):
    reference = _opened(directory, observer)
    assert _code(ledger.rollback, directory, "STOP") == "QUIESCENCE_PROOF_REQUIRED"
    assert _code(ledger.rollback, directory, "STOP", observer=observer) == "QUIESCENCE_PROOF_REQUIRED"
    other = _reference_file(directory, "other.json")
    other.write_text(json.dumps(CHANGED))
    assert _code(ledger.rollback, directory, "STOP", observer=observer, reference_path=str(other)) == \
        "REFERENCE_FILE_MISMATCH"
    tampered = json.loads(Path(reference).read_text())
    tampered["tables"]["alunos"]["rows"] = 9
    other.write_text(json.dumps(tampered))
    assert _code(ledger.rollback, directory, "STOP", observer=observer, reference_path=str(other)) == "REFERENCE_INVALID"
    other.write_text("not json")
    assert _code(ledger.rollback, directory, "STOP", observer=observer, reference_path=str(other)) == \
        "REFERENCE_UNREADABLE"


def test_a_database_still_changing_between_the_two_observations_is_not_quiescent(directory, observer):
    reference = _opened(directory, observer)
    observer.verdicts = [
        {"identical": True, "derived_classes": [], "refusal": None, "current": REFERENCE},
        {"identical": False, "derived_classes": [], "refusal": "NOT_A_DERIVED_TABLE", "current": CHANGED},
    ]
    assert _code(ledger.rollback, directory, "STOP", observer=observer, reference_path=reference) == \
        "QUIESCENCE_NOT_PROVEN"


def test_any_change_the_fixed_classes_do_not_explain_refuses_the_rollback(directory, observer):
    reference = _opened(directory, observer)
    verdict = {"identical": False, "derived_classes": [], "refusal": "ROWS_ADDED_OR_REMOVED", "current": CHANGED}
    observer.verdicts = [verdict, dict(verdict)]
    assert _code(ledger.rollback, directory, "STOP", observer=observer, reference_path=reference,
                 derived_classes=["REQUISICOES_STUDENT_SEEN"]) == "FINGERPRINT_CHANGED"
    assert ledger.status(directory)["rolled_back"] is False


@pytest.mark.parametrize("acknowledged", [
    None, [], ["REQUISICOES_AUTO_REJECTION"],
    ["REQUISICOES_AUTO_REJECTION", "REQUISICOES_STUDENT_SEEN", "USUARIO_CREDENCIAIS"],
])
def test_derived_classes_must_be_acknowledged_exactly_as_observed(directory, observer, acknowledged):
    reference = _opened(directory, observer)
    observed = ["REQUISICOES_AUTO_REJECTION", "REQUISICOES_STUDENT_SEEN"]
    verdict = {"identical": False, "derived_classes": observed, "refusal": None, "current": CHANGED}
    observer.verdicts = [verdict, dict(verdict)]
    assert _code(ledger.rollback, directory, "STOP", observer=observer, reference_path=reference,
                 derived_classes=acknowledged) == "DERIVED_CLASSES_NOT_ACKNOWLEDGED"


def test_observed_derived_classes_acknowledged_exactly_allow_the_rollback_and_are_recorded(directory, observer):
    reference = _opened(directory, observer)
    observed = ["REQUISICOES_AUTO_REJECTION"]
    verdict = {"identical": False, "derived_classes": observed, "refusal": None, "current": CHANGED}
    observer.verdicts = [verdict, dict(verdict)]
    entry = ledger.rollback(directory, "STOP", observer=observer, reference_path=reference,
                            derived_classes=["REQUISICOES_AUTO_REJECTION", "REQUISICOES_AUTO_REJECTION"])
    assert entry["derived_classes"] == observed and entry["current_fingerprint_sha256"] == CHANGED["fingerprint_sha256"]


def test_once_a_reference_is_taken_a_rollback_from_c11_is_treated_as_from_the_opening(directory, observer):
    _grant_all(directory)
    _drive(directory, "C11", observer=observer)
    ledger.record_backup(directory, directory.parent, directory.parent, observer=observer)
    ledger.take_reference(directory, _reference_file(directory), directory.parent, directory.parent,
                          cadence_hours=24, observer=observer)
    # The admission control may already be lifted although `open` was not recorded: users may be in.
    assert _code(ledger.rollback, directory, "STOP") == "QUIESCENCE_PROOF_REQUIRED"
    observer.scheduler = "disabled"
    entry = ledger.rollback(directory, "STOP", observer=observer, reference_path=str(_reference_file(directory)))
    assert entry["from_state"] == "C11" and entry["quiescence"] == "PROVEN"


def test_after_the_ponr_is_recorded_rollback_is_refused(directory, observer):
    _grant_all(directory)
    _drive(directory, "C13", observer=observer)
    assert ledger.status(directory)["ponr_recorded"] is True
    assert _code(ledger.rollback, directory, "CHANGED_MIND", observer=observer,
                 reference_path=str(_reference_file(directory))) == "PONR_RECORDED"


def test_a_rollback_reason_is_a_fixed_code(directory):
    assert _code(ledger.rollback, directory, "because the smoke test failed") == "REASON_NOT_A_CODE"


def test_the_ponr_needs_a_fingerprint_that_differs_from_the_opening_and_a_write_class(directory):
    _grant_all(directory)
    _drive(directory, "C12")
    same = {**GOOD["C13"], "current_fingerprint_sha256": REFERENCE["fingerprint_sha256"]}
    assert _code(ledger.advance, directory, "C13", same) == "NO_FINGERPRINT_DELTA"
    assert _code(ledger.advance, directory, "C13", {**GOOD["C13"], "write_class": "a request"}) == \
        "EVIDENCE_NOT_VALUE_FREE"
    assert _code(ledger.advance, directory, "C13", {**GOOD["C13"], "write_class": "request"}) == "EVIDENCE_INVALID"


@pytest.mark.parametrize("gate", sorted(ledger.PRE_PONR_ONLY_GATES - set(ALL_GATES)))
def test_gates_that_act_on_prod_or_the_source_cannot_be_granted_after_the_ponr(directory, gate):
    _grant_all(directory)
    _drive(directory, "C13")
    assert _code(ledger.grant, directory, gate, "late") == "GATE_NOT_AVAILABLE_AFTER_PONR"


def test_a_gate_not_acting_on_prod_may_still_be_granted_after_the_ponr(directory):
    _grant_all(directory)
    _drive(directory, "C13")
    assert ledger.grant(directory, "GA2", "late")["gate"] == "GA2"


def test_a_forward_fix_deployment_gate_exists_only_after_the_ponr_and_is_repeatable(directory):
    _grant_all(directory)
    _drive(directory, "C12")
    assert _code(ledger.grant, directory, "GF1", "m-fix-1") == "GATE_ONLY_AFTER_PONR"
    ledger.advance(directory, "C13", GOOD["C13"])
    ledger.grant(directory, "GF1", "m-fix-1")
    assert _code(ledger.grant, directory, "GF1", "m-fix-1") == "GATE_ALREADY_GRANTED"  # one message, one use
    ledger.grant(directory, "GF1", "m-fix-2")  # a second forward-fix deployment is a second message
    assert _code(ledger.grant, directory, "GD1", "m-late") == "GATE_NOT_AVAILABLE_AFTER_PONR"


# ---- the chain and the head --------------------------------------------------------------------------


def test_an_edited_entry_breaks_the_chain(directory):
    _grant_all(directory)
    _drive(directory, "C2")
    path = directory / ledger.LEDGER_FILE
    lines = path.read_text().splitlines()
    index = next(i for i, line in enumerate(lines) if '"state":"C1"' in line)
    lines[index] = lines[index].replace('"pg_major":17', '"pg_major":15')
    path.write_text("\n".join(lines) + "\n")
    assert _code(ledger.read_ledger, directory) == "LEDGER_CHAIN_BROKEN"
    assert _code(ledger.advance, directory, "C3", GOOD["C3"]) == "LEDGER_CHAIN_BROKEN"


def test_a_removed_or_reordered_entry_breaks_the_chain(directory):
    _grant_all(directory)
    _drive(directory, "C1")
    path = directory / ledger.LEDGER_FILE
    lines = path.read_text().splitlines()
    path.write_text("\n".join(lines[:2] + lines[3:]) + "\n")  # drop one entry
    assert _code(ledger.read_ledger, directory) == "LEDGER_CHAIN_BROKEN"
    path.write_text("\n".join([lines[0], lines[2], lines[1]] + lines[3:]) + "\n")  # swap two
    assert _code(ledger.read_ledger, directory) == "LEDGER_CHAIN_BROKEN"


def test_a_self_consistent_forged_entry_that_does_not_follow_its_predecessor_is_refused(directory):
    """seq and hash alone are not the chain: an entry rewritten with a valid hash but a wrong
    ``prev`` (an edit followed by a recomputed digest) must still break it."""
    _grant_all(directory)
    _drive(directory, "C1")
    path = directory / ledger.LEDGER_FILE
    lines = path.read_text().splitlines()
    forged = json.loads(lines[2])
    forged.pop("hash")
    forged["prev"] = "0" * 64
    forged["hash"] = ledger._entry_hash({k: v for k, v in forged.items() if k != "hash"})
    lines[2] = json.dumps(forged, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n")
    assert _code(ledger.read_ledger, directory) == "LEDGER_CHAIN_BROKEN"


def test_a_truncated_tail_is_caught_by_the_head_the_operator_last_saw(directory, observer):
    """The chain cannot see the removal of the last entries; the head binding can."""
    _grant_all(directory)
    _drive(directory, "C13", observer=observer)
    seen = ledger.status(directory)["head"]
    path = directory / ledger.LEDGER_FILE
    lines = path.read_text().splitlines()
    path.write_text("\n".join(lines[:-1]) + "\n")  # the PONR record is gone: the chain still verifies
    assert ledger.status(directory)["state"] == "C12" and ledger.status(directory)["chain"] == "OK"
    assert _code(ledger.rollback, directory, "CHANGED_MIND", expect_head=seen, observer=observer,
                 reference_path=str(_reference_file(directory))) == "HEAD_MISMATCH"
    assert _code(ledger.advance, directory, "C13", GOOD["C13"], expect_head=seen) == "HEAD_MISMATCH"
    assert _code(ledger.grant, directory, "GA2", "m", expect_head=seen) == "HEAD_MISMATCH"


def test_the_head_printed_by_each_command_binds_the_next(directory):
    entry = ledger.grant(directory, "GR0", "m1")
    head = entry["hash"]
    ledger.grant(directory, "GR1", "m2", expect_head=head)
    assert _code(ledger.grant, directory, "GR2", "m3", expect_head=head) == "HEAD_MISMATCH"  # stale head


def test_a_second_writer_is_refused_not_allowed_to_fork_the_chain(directory):
    (directory / ledger.LOCK_FILE).write_text("")
    assert _code(ledger.grant, directory, "GR0", "m1") == "LEDGER_BUSY"
    assert _code(ledger.advance, directory, "C0", GOOD["C0"]) == "LEDGER_BUSY"
    (directory / ledger.LOCK_FILE).unlink()
    assert ledger.grant(directory, "GR0", "m1")["gate"] == "GR0"
    assert not (directory / ledger.LOCK_FILE).exists()  # released after a command, also after a refusal
    assert _code(ledger.grant, directory, "GR0", "m2") == "GATE_ALREADY_GRANTED"
    assert not (directory / ledger.LOCK_FILE).exists()


def test_the_ledger_refuses_to_live_inside_the_repository_and_not_to_be_recreated(tmp_path):
    inside = Path(ledger.__file__).resolve().parents[1] / "tmp-ledger-should-not-exist"
    assert _code(ledger._ledger_dir, str(inside), must_exist=False) == "LEDGER_INSIDE_REPOSITORY"
    assert not inside.exists()
    directory = tmp_path / "l"
    ledger.init(directory)
    assert _code(ledger.init, directory) == "LEDGER_EXISTS"


def test_evidence_limits_have_their_own_codes_and_nothing_is_written(directory):
    _grant_all(directory)
    _drive(directory, "C1")
    before = (directory / ledger.LEDGER_FILE).read_text()
    cases = {
        "EVIDENCE_TOO_DEEP": {**GOOD["C2"], "census": {"deep": {"a": {"b": {"c": 1}}}}},
        "EVIDENCE_TOO_LARGE": {**GOOD["C2"], "census": {f"K{i}": 1 for i in range(65)}},   # one object too wide
        "EVIDENCE_TOO_LARGE_BYTES": {**GOOD["C2"], "census": {f"K{i}": 10**200 for i in range(60)}},  # too many bytes
    }
    for name, evidence in cases.items():
        assert _code(ledger.advance, directory, "C2", evidence) == name.replace("_BYTES", ""), name
    ledger.advance(directory, "C2", GOOD["C2"])
    ledger.advance(directory, "C3", GOOD["C3"])
    wide_list = {**GOOD["C4"], "accepted_exceptions": [{"class": f"C{i}", "count": 1} for i in range(65)]}
    before = (directory / ledger.LEDGER_FILE).read_text()
    assert _code(ledger.advance, directory, "C4", wide_list) == "EVIDENCE_TOO_LARGE"
    assert (directory / ledger.LEDGER_FILE).read_text() == before


def test_a_directory_without_a_ledger_is_missing_not_empty(tmp_path):
    assert _code(ledger._ledger_dir, str(tmp_path / "never-initialised"), must_exist=True) == "LEDGER_MISSING"
    (tmp_path / "empty").mkdir()
    assert _code(ledger._ledger_dir, str(tmp_path / "empty"), must_exist=True) == "LEDGER_MISSING"
    assert ledger._ledger_dir(str(tmp_path / "empty"), must_exist=False) == (tmp_path / "empty").resolve()


def test_a_class_name_may_be_as_long_as_the_longest_census_class_and_no_longer():
    longest = "REQUISICAO_ARQUIVOS_LOCAL_LEGACY_REPLACEMENT_CLEANUP_PENDING"
    assert len(longest) == 60 and ledger._CLASS.fullmatch(longest)
    assert ledger._CLASS.fullmatch("A" * 64) and not ledger._CLASS.fullmatch("A" * 65)


def test_an_evidence_file_that_is_not_one_json_object_is_refused_with_its_own_code(tmp_path):
    path = tmp_path / "evidence.json"
    assert _code(ledger._load_evidence, str(path)) == "EVIDENCE_UNREADABLE"  # missing
    path.write_text("{ not json", encoding="utf-8")
    assert _code(ledger._load_evidence, str(path)) == "EVIDENCE_UNREADABLE"
    path.write_bytes(b"\xff\xfe\x00\x00")
    assert _code(ledger._load_evidence, str(path)) == "EVIDENCE_UNREADABLE"
    for document in ("[1, 2]", '"text"', "3", "null"):
        path.write_text(document, encoding="utf-8")
        assert _code(ledger._load_evidence, str(path)) == "EVIDENCE_NOT_AN_OBJECT", document
    path.write_text('{"a": 1}', encoding="utf-8")
    assert ledger._load_evidence(str(path)) == {"a": 1}


def test_a_ledger_file_that_cannot_be_read_or_has_a_line_that_is_no_entry_is_refused(directory):
    ledger_file = directory / ledger.LEDGER_FILE
    ledger_file.write_bytes("\u00e7\n".encode("utf-8"))  # not ASCII: the chain is ASCII by construction
    assert _code(ledger.read_ledger, directory) == "LEDGER_UNREADABLE"
    ledger_file.write_text("not a json line\n", encoding="ascii")
    assert _code(ledger.read_ledger, directory) == "LEDGER_CHAIN_BROKEN"
    ledger_file.write_text("[1]\n", encoding="ascii")
    assert _code(ledger.read_ledger, directory) == "LEDGER_CHAIN_BROKEN"


def test_a_ledger_line_with_no_known_type_is_a_broken_chain_not_a_crash(directory):
    """The line is self-consistent (a forged but well-chained entry); only its type is unknown."""
    body = {"seq": 2, "prev": ledger._head(ledger.read_ledger(directory)), "at": "2026-11-01T00:00:00Z",
            "type": "mystery"}
    body["hash"] = ledger._entry_hash(body)
    with open(directory / ledger.LEDGER_FILE, "a", encoding="ascii") as handle:
        handle.write(json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n")
    assert _code(ledger.read_ledger, directory) == "LEDGER_CHAIN_BROKEN"


# ---- the command line -------------------------------------------------------------------------------


def _cli(args, *, ok=True):
    out, err = io.StringIO(), io.StringIO()
    code = ledger.main(args, out=out, err=err)
    assert (code == 0) is ok, err.getvalue()
    return out.getvalue(), err.getvalue()


def test_the_command_line_binds_commands_to_the_head_and_never_echoes_evidence(tmp_path):
    ledger_dir = str(tmp_path / "cli-ledger")
    out, err = io.StringIO(), io.StringIO()
    assert ledger.main(["init", "--ledger-dir", ledger_dir], out=out, err=err) == 0
    head = json.loads(out.getvalue())["head"]
    evidence = tmp_path / "e.json"
    evidence.write_text(json.dumps({**GOOD["C0"], "commit": "not-a-commit"}))
    err = io.StringIO()
    assert ledger.main(["advance", "--ledger-dir", ledger_dir, "--state", "C0", "--evidence", str(evidence),
                        "--expect-head", head], out=io.StringIO(), err=err) == 1
    assert err.getvalue().strip() == "cutover-ledger: refused: EVIDENCE_INVALID"
    assert "not-a-commit" not in err.getvalue()
    evidence.write_text(json.dumps(GOOD["C0"]))
    err = io.StringIO()
    assert ledger.main(["advance", "--ledger-dir", ledger_dir, "--state", "C0", "--evidence", str(evidence),
                        "--expect-head", "0" * 64], out=io.StringIO(), err=err) == 1
    assert "HEAD_MISMATCH" in err.getvalue()
    out = io.StringIO()
    assert ledger.main(["advance", "--ledger-dir", ledger_dir, "--state", "C0", "--evidence", str(evidence),
                        "--expect-head", head], out=out, err=io.StringIO()) == 0
    new_head = json.loads(out.getvalue())["head"]
    out = io.StringIO()
    assert ledger.main(["status", "--ledger-dir", ledger_dir], out=out, err=io.StringIO()) == 0
    status = json.loads(out.getvalue())
    assert status["state"] == "C0" and status["head"] == new_head
    assert ledger.main(["advance", "--ledger-dir", ledger_dir], out=io.StringIO(), err=io.StringIO()) == 2
    assert ledger.main(["status", "--ledger-dir", str(tmp_path / "missing")], out=io.StringIO(),
                       err=io.StringIO()) == 1


def test_the_command_line_will_not_act_without_the_head_it_last_saw(tmp_path):
    ledger_dir = str(tmp_path / "cli-head")
    out, _ = _cli(["init", "--ledger-dir", ledger_dir])
    head = json.loads(out)["head"]
    evidence = tmp_path / "e.json"
    evidence.write_text(json.dumps(GOOD["C0"]))
    for args in (
        ["grant", "--ledger-dir", ledger_dir, "--gate", "GP0", "--ref", "m1"],
        ["advance", "--ledger-dir", ledger_dir, "--state", "C0", "--evidence", str(evidence)],
        ["rollback", "--ledger-dir", ledger_dir, "--reason", "STOP"],
        ["record-backup", "--ledger-dir", ledger_dir, "--backup-root", str(tmp_path), "--off-platform", str(tmp_path)],
        ["reference", "--ledger-dir", ledger_dir, "--backup-root", str(tmp_path), "--off-platform", str(tmp_path),
         "--out", str(tmp_path / "r.json"), "--backup-cadence-hours", "24"],
        ["open", "--ledger-dir", ledger_dir],
    ):
        _, err = _cli(args, ok=False)
        assert err.strip() == "cutover-ledger: refused: HEAD_REQUIRED", args[0]
    _cli(["grant", "--ledger-dir", ledger_dir, "--gate", "GP0", "--ref", "m1", "--expect-head", head])


def test_the_command_line_cannot_type_the_opening_and_cannot_roll_back_from_it_without_the_proof(tmp_path):
    directory = tmp_path / "cli-open"
    ledger.init(directory)
    _grant_all(directory)
    _drive(directory, "C12")
    head = ledger.status(directory)["head"]
    evidence = tmp_path / "c12.json"
    evidence.write_text(json.dumps({"opened_at": "2026-11-01T09:00:00Z"}))
    _, err = _cli(["rollback", "--ledger-dir", str(directory), "--reason", "STOP", "--expect-head", head], ok=False)
    assert "QUIESCENCE_PROOF_REQUIRED" in err


def test_the_cli_refuses_to_type_c12(tmp_path):
    directory = tmp_path / "cli-c12"
    ledger.init(directory)
    _grant_all(directory)
    _drive(directory, "C11")
    head = ledger.status(directory)["head"]
    evidence = tmp_path / "c12.json"
    evidence.write_text(json.dumps({"opened_at": "2026-11-01T09:00:00Z"}))
    _, err = _cli(["advance", "--ledger-dir", str(directory), "--state", "C12", "--evidence", str(evidence),
                   "--expect-head", head], ok=False)
    assert "OPENING_NEEDS_THE_OPEN_COMMAND" in err
