# coding: utf-8
"""MP-3 slice 5: the cutover evidence ledger (``tools/cutover_ledger.py``) -- no database.

The ledger is the cutover's memory and referee: order, gates, value-free
evidence, carried identities, the hash chain, the head binding and the point of
no return.  Each test names the defect it would catch; the module is exercised
through the public functions and the command line.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from tools import cutover_ledger as ledger

H = {"a": "a" * 64, "b": "b" * 64, "c": "c" * 64, "d": "d" * 64, "e": "e" * 64, "f": "f" * 64,
     "g": "1" * 64, "h": "2" * 64, "i": "3" * 64}  # distinct 64-hex digests
COMMIT = "c" * 40
OTHER_COMMIT = "d" * 40
OPENED = "2026-11-01T09:00:00Z"

# Evidence a clean cutover would carry, state by state.
GOOD = {
    "C0": {"commit": COMMIT, "runbook_sha256": H["a"], "rehearsal_index_sha256": H["b"], "review_verdict": "PASS"},
    "C1": {"pg_major": 17, "schema_current": True, "rows": 0, "objects": 0, "data_api_toggle_off": True,
           "data_api_probe": "NOT_SERVED", "api_exposure_clean": True, "capacity_ok": True},
    "C2": {"database_bytes": 1000, "document_bytes": 2000, "census": {"GOOGLE_ROWS": 4, "LOCAL_ROWS": 2}},
    "C3": {"source_size": 4096, "source_sha256": H["c"], "wal_bytes": 0},
    "C4": {"source_sha256": H["c"], "prepared_sha256": H["d"], "integrity_ok": True, "fk_violations": 0,
           "schema_version": 16, "accepted_exceptions": [{"class": "TRASHED_LEGACY", "count": 2}],
           "accepted_by_user": True},
    "C5": {"prepared_sha256": H["d"], "converged_rows": 40, "unconverged": [{"class": "TRASHED_LEGACY", "count": 2}],
           "legacy_bytes_touched": 0},
    "C6": {"prepared_sha256": H["d"], "reference_digest": H["e"], "verdict": "CLEAN"},
    "C7": {"prepared_sha256": H["d"], "pathb_exit": 0, "commit_resolved_by_inspection": False,
           "commit_outcome": "COMMITTED"},
    "C8": {"reference_digest": H["e"], "census_equal": True, "baseline_manifest_sha256": H["f"],
           "object_set_digest": H["g"], "restore_drill": "OK", "verify_backup": "OK",
           "admin_bootstrap": "NOT_NEEDED"},
    "C9": {"commit": COMMIT, "readiness": "READY", "bundle_audit": "CLEAN", "scheduler_front": "DISABLED"},
    "C10": {"smoke": "PASS", "write_set_ok": True},
    "C11": {"account_key_match": True, "mirror_passes": 2, "reconciliation_required": 0,
            "scheduler_front": "ENABLED"},
    "C12": {"reference_fingerprint_sha256": H["h"], "opened_at": OPENED},
    "C13": {"write_class": "REQUISICOES", "detected_at": "2026-11-01T10:30:00Z",
            "current_fingerprint_sha256": H["i"], "adjudicated_by_operator": True},
    "C14": {"window_days": 30, "second_generation_restore": "OK", "unresolved_reconciliation": 0,
            "object_set_verified": True},
}
# Gates in the order a cutover needs them (GP3 only when the bootstrap runs).
ALL_GATES = ["GP0", "GP1", "GP2", "GR0", "GR1", "GR2", "GR3", "GB1", "GD1", "GG1", "GG2", "GD2", "GO"]


@pytest.fixture
def directory(tmp_path):
    path = tmp_path / "cutover-ledger"
    ledger.init(path)
    return path


def _grant_all(directory, gates=ALL_GATES):
    for index, gate in enumerate(gates):
        ledger.grant(directory, gate, f"user-msg-{index}")


def _drive(directory, upto, overrides=None):
    """Advance through every state up to and including ``upto``."""
    overrides = overrides or {}
    for state in ledger.STATES[: ledger.STATES.index(upto) + 1]:
        evidence = dict(GOOD[state])
        evidence.update(overrides.get(state, {}))
        ledger.advance(directory, state, evidence)


def _code(call, *args, **kwargs):
    with pytest.raises(ledger.Refused) as caught:
        call(*args, **kwargs)
    return caught.value.code


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
    "C0": {"commit": "abc", "runbook_sha256": "xyz", "rehearsal_index_sha256": H["a"][:-1], "review_verdict": "FAIL"},
    "C1": {"pg_major": 14, "schema_current": False, "rows": 3, "objects": 1, "data_api_toggle_off": False,
           "data_api_probe": "SERVED", "api_exposure_clean": False, "capacity_ok": False},
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
    "C9": {"commit": "nope", "readiness": "NOT_READY", "bundle_audit": "FINDINGS", "scheduler_front": "ENABLED"},
    "C10": {"smoke": "FAIL", "write_set_ok": False},
    "C11": {"account_key_match": False, "mirror_passes": 0, "reconciliation_required": 2, "scheduler_front": "DISABLED"},
    "C12": {"reference_fingerprint_sha256": "nope", "opened_at": "yesterday"},
    "C13": {"write_class": "a request", "detected_at": "later", "current_fingerprint_sha256": "nope",
            "adjudicated_by_operator": False},
    "C14": {"window_days": 0, "second_generation_restore": "SKIPPED", "unresolved_reconciliation": 1,
            "object_set_verified": False},
}


@pytest.mark.parametrize("state", ledger.STATES)
def test_every_evidence_predicate_refuses_a_bad_value_and_a_missing_key(directory, state):
    assert set(BAD[state]) == set(GOOD[state]), "the table must cover every key"
    _grant_all(directory)
    if state != "C0":
        _drive(directory, ledger.STATES[ledger.STATES.index(state) - 1])
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


def test_a_gate_does_not_cover_a_state_it_is_not_listed_for(directory):
    # GO opens users (C12); having it must not let C11 (mirror) be entered without its own gates.
    ledger.grant(directory, "GO", "m1")
    assert ledger.STATE_GATES["C11"] == ("GG1", "GG2", "GD2") and "GO" not in ledger.STATE_GATES["C11"]
    assert [s for s in ledger.STATES if "GO" in ledger.STATE_GATES[s]] == ["C12"]


def test_rollback_is_recorded_before_the_point_of_no_return_and_ends_the_cutover(directory):
    _grant_all(directory)
    _drive(directory, "C11")
    entry = ledger.rollback(directory, "SMOKE_REGRESSION")
    assert entry["from_state"] == "C11"
    assert ledger.status(directory)["rolled_back"] is True
    assert _code(ledger.advance, directory, "C12", GOOD["C12"]) == "ROLLED_BACK"
    assert _code(ledger.rollback, directory, "AGAIN") == "ALREADY_ROLLED_BACK"


def test_a_rollback_from_the_opening_needs_proof_that_no_business_table_changed(directory):
    _grant_all(directory)
    _drive(directory, "C12")
    assert _code(ledger.rollback, directory, "CHANGED_MIND") == "FINGERPRINT_REQUIRED"
    assert _code(ledger.rollback, directory, "CHANGED_MIND", current_fingerprint="nope") == "FINGERPRINT_REQUIRED"
    assert _code(ledger.rollback, directory, "CHANGED_MIND", current_fingerprint=H["i"]) == "FINGERPRINT_CHANGED"
    entry = ledger.rollback(directory, "CHANGED_MIND", current_fingerprint=H["h"])  # equals the opening's
    assert entry["from_state"] == "C12"


def test_after_the_ponr_is_recorded_rollback_is_refused(directory):
    _grant_all(directory)
    _drive(directory, "C13")
    assert ledger.status(directory)["ponr_recorded"] is True
    assert _code(ledger.rollback, directory, "CHANGED_MIND", current_fingerprint=H["h"]) == "PONR_RECORDED"


def test_a_rollback_reason_is_a_fixed_code(directory):
    assert _code(ledger.rollback, directory, "because the smoke test failed") == "REASON_NOT_A_CODE"


def test_the_ponr_needs_a_fingerprint_that_differs_from_the_opening_and_a_write_class(directory):
    _grant_all(directory)
    _drive(directory, "C12")
    same = {**GOOD["C13"], "current_fingerprint_sha256": H["h"]}
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


def test_a_truncated_tail_is_caught_by_the_head_the_operator_last_saw(directory):
    """The chain cannot see the removal of the last entries; the head binding can."""
    _grant_all(directory)
    _drive(directory, "C13")
    seen = ledger.status(directory)["head"]
    path = directory / ledger.LEDGER_FILE
    lines = path.read_text().splitlines()
    path.write_text("\n".join(lines[:-1]) + "\n")  # the PONR record is gone: the chain still verifies
    assert ledger.status(directory)["state"] == "C12" and ledger.status(directory)["chain"] == "OK"
    assert _code(ledger.rollback, directory, "CHANGED_MIND", expect_head=seen,
                 current_fingerprint=H["h"]) == "HEAD_MISMATCH"
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


@pytest.mark.parametrize("state", ledger.STATES[: ledger.STATES.index("C13")])
def test_a_rollback_is_recorded_from_every_state_before_the_ponr_and_never_after(directory, state):
    _grant_all(directory)
    _drive(directory, state)
    extra = {"current_fingerprint": H["h"]} if state == "C12" else {}
    entry = ledger.rollback(directory, "OPERATOR_STOP", **extra)
    assert entry["from_state"] == state
    summary = ledger.status(directory)
    assert summary["rolled_back"] is True and summary["state"] == state and summary["ponr_recorded"] is False
    following = ledger.STATES[ledger.STATES.index(state) + 1]
    assert _code(ledger.advance, directory, following, GOOD[following]) == "ROLLED_BACK"
    assert ledger.read_ledger(directory)[-1]["type"] == "rollback"  # and the chain still verifies on read


# ---- review hardening: adjudicated rollback, snapshot proof, mandatory head, forward-fix gate ---------


def test_a_rollback_from_the_opening_may_adjudicate_a_known_derived_write_and_records_it(directory):
    _grant_all(directory)
    _drive(directory, "C12")
    changed = "e" * 64
    assert _code(ledger.rollback, directory, "STOP", current_fingerprint=changed) == "FINGERPRINT_CHANGED"
    for bad in ([], ["lower"], ["BAD CLASS"], [f"T{i}" for i in range(17)]):
        assert _code(ledger.rollback, directory, "STOP", current_fingerprint=changed,
                     derived_classes=bad) == "FINGERPRINT_CHANGED"
    entry = ledger.rollback(directory, "STOP", current_fingerprint=changed,
                            derived_classes=["USUARIO_CREDENCIAIS", "REQUISICOES", "REQUISICOES"])
    assert entry["adjudicated_derived_classes"] == ["REQUISICOES", "USUARIO_CREDENCIAIS"]
    assert entry["current_fingerprint_sha256"] == changed
    assert ledger.status(directory)["rolled_back"] is True


def test_a_class_name_may_be_as_long_as_the_longest_census_class_and_no_longer():
    longest = "REQUISICAO_ARQUIVOS_LOCAL_LEGACY_REPLACEMENT_CLEANUP_PENDING"
    assert len(longest) == 60 and ledger._CLASS.fullmatch(longest)
    assert ledger._CLASS.fullmatch("A" * 64) and not ledger._CLASS.fullmatch("A" * 65)


def _cli(args, *, ok=True):
    out, err = io.StringIO(), io.StringIO()
    code = ledger.main(args, out=out, err=err)
    assert (code == 0) is ok, err.getvalue()
    return out.getvalue(), err.getvalue()


def test_the_command_line_will_not_grant_advance_or_roll_back_without_the_head_it_last_saw(tmp_path):
    ledger_dir = str(tmp_path / "cli-head")
    out, _ = _cli(["init", "--ledger-dir", ledger_dir])
    head = json.loads(out)["head"]
    _, err = _cli(["grant", "--ledger-dir", ledger_dir, "--gate", "GP0", "--ref", "m1"], ok=False)
    assert err.strip() == "cutover-ledger: refused: HEAD_REQUIRED"
    evidence = tmp_path / "e.json"
    evidence.write_text(json.dumps(GOOD["C0"]))
    _, err = _cli(["advance", "--ledger-dir", ledger_dir, "--state", "C0", "--evidence", str(evidence)], ok=False)
    assert "HEAD_REQUIRED" in err
    _, err = _cli(["rollback", "--ledger-dir", ledger_dir, "--reason", "STOP"], ok=False)
    assert "HEAD_REQUIRED" in err
    _cli(["grant", "--ledger-dir", ledger_dir, "--gate", "GP0", "--ref", "m1", "--expect-head", head])


def _snapshot_file(tmp_path, name, tables, taken_at="2099-01-01T00:00:00Z"):
    from tools import pg_fingerprint as fp

    path = tmp_path / name
    document = {"format": fp.FORMAT, "tables": tables, "fingerprint_sha256": fp._digest_of(tables)}
    if taken_at is not None:
        document["taken_at"] = taken_at
    path.write_text(json.dumps(document), encoding="ascii")
    return path


def test_the_command_line_takes_the_rollback_proof_from_a_valid_fresh_snapshot_file(tmp_path):
    import os
    import time

    from tools import pg_fingerprint as fp

    ledger_dir = tmp_path / "cli-proof"
    ledger.init(ledger_dir)
    _grant_all(ledger_dir)
    tables = {"alunos": {"rows": 1, "sha256": "d" * 64, "columns": ["id"], "row_hashes": {"1": ["h"]}}}
    reference = fp._digest_of(tables)
    _drive(ledger_dir, "C11")
    ledger.advance(ledger_dir, "C12", {**GOOD["C12"], "reference_fingerprint_sha256": reference})
    head = ledger.status(ledger_dir)["head"]
    base = ["rollback", "--ledger-dir", str(ledger_dir), "--reason", "STOP", "--expect-head", head]
    # a file that is not a snapshot, a tampered one and a stale one are refused before anything is written
    junk = tmp_path / "junk.json"
    junk.write_text("not json")
    assert "SNAPSHOT_UNREADABLE" in _cli([*base, "--current-snapshot", str(junk)], ok=False)[1]
    tampered = _snapshot_file(tmp_path, "tampered.json", tables)
    document = json.loads(tampered.read_text())
    document["tables"]["alunos"]["rows"] = 2
    tampered.write_text(json.dumps(document))
    assert "SNAPSHOT_INVALID" in _cli([*base, "--current-snapshot", str(tampered)], ok=False)[1]
    stale = _snapshot_file(tmp_path, "stale.json", tables, taken_at="2020-01-01T00:00:00Z")
    assert "SNAPSHOT_STALE" in _cli([*base, "--current-snapshot", str(stale)], ok=False)[1]
    undated = _snapshot_file(tmp_path, "undated.json", tables, taken_at=None)
    assert "SNAPSHOT_STALE" in _cli([*base, "--current-snapshot", str(undated)], ok=False)[1]
    # A copy of an old snapshot keeps the time written into it: a new file mtime does not make it fresh.
    copy = tmp_path / "copy.json"
    copy.write_bytes(stale.read_bytes())
    os.utime(copy, None)
    assert "SNAPSHOT_STALE" in _cli([*base, "--current-snapshot", str(copy)], ok=False)[1]
    good = _snapshot_file(tmp_path, "good.json", tables)
    out, _ = _cli([*base, "--current-snapshot", str(good)])
    assert json.loads(out)["from_state"] == "C12"


def test_a_forward_fix_deployment_gate_exists_only_after_the_ponr_and_is_repeatable(directory):
    _grant_all(directory)
    _drive(directory, "C12")
    assert _code(ledger.grant, directory, "GF1", "m-fix-1") == "GATE_ONLY_AFTER_PONR"
    ledger.advance(directory, "C13", GOOD["C13"])
    ledger.grant(directory, "GF1", "m-fix-1")
    assert _code(ledger.grant, directory, "GF1", "m-fix-1") == "GATE_ALREADY_GRANTED"  # one message, one use
    ledger.grant(directory, "GF1", "m-fix-2")  # a second forward-fix deployment is a second message
    assert _code(ledger.grant, directory, "GD1", "m-late") == "GATE_NOT_AVAILABLE_AFTER_PONR"


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
