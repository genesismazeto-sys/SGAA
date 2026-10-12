# coding: utf-8
"""MP-3 slice 5 and the R3 remediations (A15, A16, A17): the cutover evidence ledger (``tools/cutover_ledger.py``).

The ledger is the cutover's memory and referee: order, gates, value-free evidence, carried
identities, the hash chain, the head binding and the point of no return.  Where the SPEC forbids
trusting the operator's word it observes for itself through an ``Observer`` -- the verified PROD
source, the public and deployment addresses, the platform's record, the write barrier, the opening
authorization -- or consumes the receipt a governed tool produced while it acted (backups, restore
drills, deployments, promotions).  Here a scripted observer (``tests.mp3_ledger_support``) stands in
for all of them and a scripted clock for time.  Each test names the defect it would catch.
"""

from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import hosting
from tests import mp3_ledger_support as ls
from tests.mp3_ledger_support import (ALL_GATES, BASELINE_DUMP, BASELINE_MANIFEST, BASELINE_OBJECTS, CHANGED, CODE,
                                      DEPLOYMENT, GOOD, H, IDENTITY, LIFT, OTHER_CODE, OTHER_COMMIT, OTHER_REF,
                                      PLATFORM_PROJECT, PROD_REF, PROJECT, REFERENCE, SOURCE, FakeObserver)
from tests.mp3_ledger_support import manifest_digest as _manifest
from tools import cutover_ledger as ledger
from tools import pg_fingerprint as fp


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    return ls.install_clock(monkeypatch, datetime(2026, 11, 1, 8, 0, 0, tzinfo=timezone.utc))


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


def _drive(directory, upto, overrides=None, observer=None):
    return ls.drive(directory, upto, observer or FakeObserver(), overrides)


def _reference_file(directory, name="reference.json"):
    return ls.reference_file(directory, name)


def _code(call, *args, **kwargs):
    with pytest.raises(ledger.Refused) as caught:
        call(*args, **kwargs)
    return caught.value.code


def _ledger_bytes(directory):
    return (directory / ledger.LEDGER_FILE).read_text()


def _at_c11_with_generation(directory, observer):
    _grant_all(directory)
    _drive(directory, "C11", observer=observer)
    ls.set_clock(ledger._CLOCK() + timedelta(minutes=1))
    ls.record(directory, observer)


# ---- order, gates and evidence ------------------------------------------------------------------


def test_a_clean_cutover_runs_c0_to_c14_and_status_reports_the_position(directory):
    _grant_all(directory)
    _drive(directory, "C14")
    status = ledger.status(directory)
    assert status["state"] == "C14" and status["state_name"] == "WINDOW_CLOSED"
    assert status["chain"] == "OK" and status["next_state"] is None
    assert status["ponr_recorded"] is True and status["rolled_back"] is False and status["qualified"] is True
    types = [entry["type"] for entry in ledger.read_ledger(directory)]
    for kind in ("qualification", "deployment", "promotion", "reference", "backup", "restore"):
        assert kind in types, kind


def test_the_first_state_must_be_c0_and_no_state_can_be_skipped(directory):
    _grant_all(directory)
    assert _code(ledger.advance, directory, "C1", GOOD["C1"]) == "OUT_OF_ORDER"
    ledger.advance(directory, "C0", GOOD["C0"])
    assert _code(ledger.advance, directory, "C2", GOOD["C2"]) == "OUT_OF_ORDER"
    assert _code(ledger.advance, directory, "C9", GOOD["C9"]) == "OUT_OF_ORDER"
    assert _code(ledger.advance, directory, "NOPE", {}) == "UNKNOWN_STATE"


def test_a_state_is_refused_until_every_gate_it_needs_is_granted(directory):
    observer = FakeObserver()
    ledger.advance(directory, "C0", GOOD["C0"])
    ledger.grant(directory, "GP0", "m0")
    ledger.grant(directory, "GP1", "m1")
    ledger.qualify(directory, observer=observer)
    assert _code(ledger.advance, directory, "C1", GOOD["C1"]) == "GATE_NOT_GRANTED"
    ledger.grant(directory, "GP2", "m2")
    ledger.advance(directory, "C1", GOOD["C1"])
    assert _code(ledger.advance, directory, "C2", GOOD["C2"]) == "GATE_NOT_GRANTED"


def test_a_gate_is_granted_once_and_only_a_known_gate_with_an_opaque_reference(directory):
    ledger.grant(directory, "GR0", "msg-2026-10-10")
    assert _code(ledger.grant, directory, "GR0", "msg-2") == "GATE_ALREADY_GRANTED"
    assert _code(ledger.grant, directory, "GZ9", "x") == "UNKNOWN_GATE"
    assert _code(ledger.grant, directory, "GR1", "the user said: go ahead") == "REFERENCE_NOT_OPAQUE"
    assert _code(ledger.grant, directory, "GR1", "") == "REFERENCE_NOT_OPAQUE"


@pytest.mark.parametrize("evidence", [
    {**GOOD["C0"], "commit": "the commit on main"},
    {**GOOD["C0"], "review_verdict": "aluno@escola.br"},
    {**GOOD["C0"], "rehearsal_index_sha256": 1.5},
    {**GOOD["C0"], "path": "C:\\Users\\x"},
])
def test_evidence_that_is_not_value_free_is_refused_before_anything_is_written(directory, evidence):
    before = _ledger_bytes(directory)
    with pytest.raises(ledger.Refused):
        ledger.advance(directory, "C0", evidence)
    assert _ledger_bytes(directory) == before


BAD = {
    "C0": {"review_verdict": "FAIL", "prod_project_sha256": "x"},
    "C1": {"rows": 5, "schema_current": False, "pg_major": 14, "data_api_toggle_off": False,
           "data_api_override": "SKIPPED", "data_api_probe": "SERVED", "data_api_project_sha256": "x",
           "api_exposure_clean": False, "capacity_ok": False},
    "C2": {"census": {}},
    "C3": {"wal_bytes": 1, "source_size": 0},
    "C4": {"schema_version": 15, "fk_violations": 3, "accepted_exceptions": [{"class": "lower"}]},
    "C5": {"legacy_bytes_touched": 1},
    "C6": {"verdict": "DIRTY"},
    "C7": {"pathb_exit": 4, "commit_outcome": "UNKNOWN"},
    "C8": {"census_equal": False, "admin_bootstrap": "SKIPPED", "baseline_manifest_sha256": "x"},
    "C9": {"readiness": "BLOCKED", "deployment_id": "not-a-deployment", "scheduler_front": "ENABLED",
           "admission": "OPEN"},
    "C10": {"smoke": "FAIL", "write_set_ok": False, "admission": "OPEN", "public_host_sha256": "x"},
    "C11": {"mirror_passes": 0, "reconciliation_required": 1, "scheduler_front": "DISABLED", "admission": "OPEN"},
    "C13": {"detected_at": "yesterday", "adjudicated_by_operator": False},
    "C14": {"unresolved_reconciliation": 1, "restore_validated_manifest_sha256": "x"},
}


@pytest.mark.parametrize("state", sorted(BAD, key=lambda s: int(s[1:])))
def test_every_evidence_predicate_refuses_a_bad_value_and_a_missing_key(directory, state):
    _grant_all(directory)
    observer = FakeObserver()
    if state != "C0":
        _drive(directory, ledger.STATES[ledger.STATES.index(state) - 1], observer=observer)
    for key, bad in BAD[state].items():
        assert _code(ledger.advance, directory, state, {**GOOD[state], key: bad}) == "EVIDENCE_INVALID", key
        missing = {k: v for k, v in GOOD[state].items() if k != key}
        assert _code(ledger.advance, directory, state, missing) == "EVIDENCE_INVALID", key
    assert _code(ledger.advance, directory, state, {**GOOD[state], "extra": 1}) == "EVIDENCE_UNEXPECTED_KEY"


def test_booleans_are_never_accepted_where_a_number_is_required(directory):
    _grant_all(directory)
    _drive(directory, "C1")
    assert _code(ledger.advance, directory, "C2", {**GOOD["C2"], "database_bytes": True}) == "EVIDENCE_INVALID"
    assert _code(ledger.advance, directory, "C2", {**GOOD["C2"], "census": {"X": True}}) == "EVIDENCE_INVALID"


def test_the_frozen_source_identity_cannot_change_between_c3_and_c4(directory):
    _grant_all(directory)
    _drive(directory, "C3")
    assert _code(ledger.advance, directory, "C4", {**GOOD["C4"], "source_sha256": H["f"]}) == "SOURCE_IDENTITY_CHANGED"


def test_the_prepared_copy_identity_is_carried_through_c5_c6_c7(directory):
    _grant_all(directory)
    _drive(directory, "C4")
    assert _code(ledger.advance, directory, "C5", {**GOOD["C5"], "prepared_sha256": H["a"]}) == "PREPARED_IDENTITY_CHANGED"
    ledger.advance(directory, "C5", GOOD["C5"])
    assert _code(ledger.advance, directory, "C6", {**GOOD["C6"], "prepared_sha256": H["a"]}) == "PREPARED_IDENTITY_CHANGED"
    ledger.advance(directory, "C6", GOOD["C6"])
    assert _code(ledger.advance, directory, "C7", {**GOOD["C7"], "prepared_sha256": H["a"]}) == "PREPARED_IDENTITY_CHANGED"


@pytest.mark.parametrize("unconverged", [
    [],
    [{"class": "TRASHED_LEGACY", "count": 3}],
    [{"class": "TRASHED_LEGACY", "count": 2}, {"class": "UNSUPPORTED_MIME", "count": 1}],
])
def test_only_the_exact_exceptions_the_user_accepted_at_c4_may_remain_unconverged(directory, unconverged):
    _grant_all(directory)
    _drive(directory, "C4")
    assert _code(ledger.advance, directory, "C5", {**GOOD["C5"], "unconverged": unconverged}) == \
        "UNCONVERGED_ROWS_NOT_ACCEPTED"


def test_a_commit_uncertain_pathb_exit_needs_the_inspection_to_be_stated(directory):
    _grant_all(directory)
    _drive(directory, "C6")
    assert _code(ledger.advance, directory, "C7", {**GOOD["C7"], "pathb_exit": 3}) == "COMMIT_UNCERTAIN_NOT_RESOLVED"
    entry = ledger.advance(directory, "C7", {**GOOD["C7"], "pathb_exit": 3, "commit_resolved_by_inspection": True})
    assert entry["state"] == "C7"


def test_the_target_must_reproduce_the_converged_sources_reference_digest(directory):
    observer = FakeObserver()
    _grant_all(directory)
    _drive(directory, "C7", observer=observer)
    ls.baseline(directory, observer)
    assert _code(ledger.advance, directory, "C8", {**GOOD["C8"], "reference_digest": H["a"]}) == \
        "REFERENCE_DIGEST_MISMATCH"


def test_an_administrator_bootstrap_needs_its_own_gate(directory):
    observer = FakeObserver()
    _grant_all(directory)
    _drive(directory, "C7", observer=observer)
    ls.baseline(directory, observer)
    assert _code(ledger.advance, directory, "C8", {**GOOD["C8"], "admin_bootstrap": "DONE"}) == "GATE_NOT_GRANTED"
    ledger.grant(directory, "GP3", "m-gp3")
    assert ledger.advance(directory, "C8", {**GOOD["C8"], "admin_bootstrap": "DONE"})["state"] == "C8"


def test_the_data_api_proof_at_c1_must_name_the_prod_project_gp0_named(directory):
    _grant_all(directory)
    _drive(directory, "C0")
    ledger.qualify(directory, observer=FakeObserver())
    other = hosting.project_sha256(OTHER_REF)
    assert _code(ledger.advance, directory, "C1", {**GOOD["C1"], "data_api_project_sha256": other}) == \
        "DATA_API_NOT_THE_PROD_PROJECT"


def test_the_smokes_data_api_proof_must_name_the_project_qualified_at_c1(directory):
    observer = FakeObserver()
    _grant_all(directory)
    _drive(directory, "C9", observer=observer)
    ls.promote(directory, observer)
    assert _code(ledger.advance, directory, "C10", {**GOOD["C10"], "data_api_project_sha256": H["a"]}) == \
        "DATA_API_PROJECT_CHANGED"


def test_a_gate_does_not_cover_a_state_it_is_not_listed_for(directory):
    observer = FakeObserver()
    for gate in ("GP0", "GP1", "GP2", "GR0"):
        ledger.grant(directory, gate, f"m-{gate}")
    ledger.advance(directory, "C0", GOOD["C0"])
    ledger.qualify(directory, observer=observer)
    ledger.advance(directory, "C1", GOOD["C1"])
    ledger.advance(directory, "C2", GOOD["C2"])
    assert _code(ledger.advance, directory, "C3", GOOD["C3"]) == "GATE_NOT_GRANTED"  # GR0 is not GR1


def test_admission_is_closed_in_every_state_before_the_opening_and_c12_is_never_typed(directory):
    _grant_all(directory)
    for state in ("C9", "C10", "C11"):
        assert ledger._SCHEMA[state]["admission"]("CLOSED") and not ledger._SCHEMA[state]["admission"]("OPEN")
    _drive(directory, "C11")
    typed = {"reference_fingerprint_sha256": H["h"], "database_identity_sha256": IDENTITY,
             "opened_at": "2026-11-01T09:00:00Z", "admission": "OPEN", "pre_open_backup_manifest_sha256": H["a"],
             "backup_cadence_hours": 24, "rpo_hours": 24}
    assert _code(ledger.advance, directory, "C12", typed) == "OPENING_NEEDS_THE_OPEN_COMMAND"


# ---- the PROD database: qualified through a verified connection (A17 finding 3) ------------------------


FOREIGN_CLUSTER = dict(SOURCE, system_identifier="7400000000000000009")  # another server
SCRATCH = dict(SOURCE, host="127.0.0.1", port="5432", login_user="sgaa", user="sgaa")  # a workstation / scratch
DEV = dict(SOURCE, login_user="postgres." + OTHER_REF)  # another project behind the same regional pooler


def test_the_qualification_is_the_ledgers_own_observation_and_c1_needs_it(directory, observer):
    _grant_all(directory)
    ledger.advance(directory, "C0", GOOD["C0"])
    assert _code(ledger.advance, directory, "C1", GOOD["C1"]) == "QUALIFICATION_REQUIRED"
    entry = ledger.qualify(directory, observer=observer)
    assert entry["database_identity_sha256"] == IDENTITY and entry["tls"] == "VERIFIED"
    assert entry["buckets_compared"] == 1 and entry["project_sha256"] == PROJECT
    assert _code(ledger.qualify, directory, observer=observer) == "QUALIFICATION_ALREADY_RECORDED"
    assert ledger.advance(directory, "C1", GOOD["C1"])["state"] == "C1"
    assert _code(ledger.qualify, directory, observer=observer) == "OUT_OF_ORDER"


@pytest.mark.parametrize("setup,code", [
    (lambda o: setattr(o, "facts", DEV), "DATABASE_NOT_THE_PROD_PROJECT"),
    (lambda o: setattr(o, "facts", SCRATCH), "SOURCE_NO_TENANT"),
    (lambda o: setattr(o, "facts", dict(SOURCE, system_identifier=None)), "DATABASE_IDENTITY_UNPROVEN"),
    (lambda o: setattr(o, "store_project", hosting.project_sha256(OTHER_REF)), "STORE_NOT_THE_PROD_PROJECT"),
    (lambda o: setattr(o, "api_buckets", frozenset()), "NO_BUCKET_TO_COMPARE"),
    # Another project's database behind a verified connection holds other buckets than the project's API lists.
    (lambda o: setattr(o, "db_buckets", frozenset({("sgaa-documentos", "2026-09-30T00:00:00")})),
     "STORE_NOT_THE_DATABASES_PROJECT"),
])
def test_the_qualification_refuses_any_database_the_prod_project_does_not_vouch_for(directory, observer, setup, code):
    _grant_all(directory)
    ledger.advance(directory, "C0", GOOD["C0"])
    setup(observer)
    before = _ledger_bytes(directory)
    assert _code(ledger.qualify, directory, observer=observer) == code
    assert _ledger_bytes(directory) == before


def test_the_qualification_needs_gp0_and_gp1(directory, observer):
    ledger.advance(directory, "C0", GOOD["C0"])
    ledger.grant(directory, "GP0", "m0")
    assert _code(ledger.qualify, directory, observer=observer) == "GATE_NOT_GRANTED"


def test_every_later_observation_must_be_the_qualified_database(directory, observer):
    """Another cluster of the same project (a restored or recreated database) is not the qualified one."""
    _grant_all(directory)
    _drive(directory, "C11", observer=observer)
    observer.facts = FOREIGN_CLUSTER
    assert _code(ls.record, directory, observer) == "DATABASE_NOT_THE_QUALIFIED_ONE"
    observer.facts = DEV
    assert _code(ls.record, directory, observer) == "DATABASE_NOT_THE_PROD_PROJECT"


# ---- deployments: recorded by the governed deploy, bound to what the platform received (A17 finding 5) ----


def test_a_deployment_is_recorded_only_after_c8_with_gd1_and_only_the_reviewed_commit(directory, observer):
    _grant_all(directory, [g for g in ALL_GATES if g != "GD1"])
    _drive(directory, "C7", observer=observer)
    assert _code(ls.deploy, directory, observer) == "OUT_OF_ORDER"
    ls.baseline(directory, observer)
    ledger.advance(directory, "C8", GOOD["C8"])
    assert _code(ls.deploy, directory, observer) == "GATE_NOT_GRANTED"
    ledger.grant(directory, "GD1", "m-gd1")
    assert _code(ls.deploy, directory, observer, commit=OTHER_COMMIT) == "COMMIT_NOT_THE_REHEARSED_ONE"
    assert _code(ls.deploy, directory, observer, observed_admission="OPEN") == "DEPLOYMENT_NOT_CLOSED"
    assert _code(ls.deploy, directory, observer, admission="OPEN", opening_reference=H["a"]) == \
        "OPEN_WITHOUT_THE_REFERENCE"
    assert _code(ls.deploy, directory, observer, opening_reference=H["a"]) == "ADMISSION_INVALID"
    assert _code(ledger.record_deployment, directory, {"deployment_id": DEPLOYMENT}) == "DEPLOYMENT_RECEIPT_INVALID"
    ls.deploy(directory, observer)
    assert _code(ls.deploy, directory, observer) == "DEPLOYMENT_RECEIPT_INVALID"  # a deployment is recorded once
    assert _code(ls.deploy, directory, observer, "dpl_" + "C" * 24, vercel_project_sha256=H["a"]) == \
        "DEPLOYMENT_PROJECT_CHANGED"


def test_c9_names_a_recorded_operator_deployment_of_the_reviewed_commit(directory, observer):
    _grant_all(directory)
    _drive(directory, "C8", observer=observer)
    assert _code(ledger.advance, directory, "C9", GOOD["C9"]) == "DEPLOYMENT_NOT_RECORDED"
    ls.deploy(directory, observer)
    assert _code(ledger.advance, directory, "C9", {**GOOD["C9"], "commit": OTHER_COMMIT}) == \
        "COMMIT_NOT_THE_REHEARSED_ONE"
    assert ledger.advance(directory, "C9", GOOD["C9"])["state"] == "C9"


def test_the_same_commit_must_run_the_same_code_in_every_later_deployment(directory, observer):
    _grant_all(directory)
    _drive(directory, "C9", observer=observer)
    assert _code(ls.deploy, directory, observer, "dpl_" + "C" * 24, code=OTHER_CODE) == "DEPLOYMENT_CODE_CHANGED"


# ---- the compliance amendment (A18): one reviewed commit on top, only public pages added -------------

_COMPLIANCE_PAGES = ("index.html", "privacidade.html", "termos.html")


@pytest.fixture
def amendment_repo(tmp_path):
    """A real repository: the candidate commit, then well-formed and malformed amendments on top."""
    import subprocess

    repo = tmp_path / "amendment-repo"
    repo.mkdir()

    def run(*arguments):
        return subprocess.run(["git", "-C", str(repo), *arguments], capture_output=True, text=True, check=True)

    def commit(message):
        run("commit", "-qm", message)
        return run("rev-parse", "HEAD").stdout.strip()

    run("init", "-q")
    run("config", "user.name", "test")
    run("config", "user.email", "test@example.invalid")
    (repo / "static" / "css").mkdir(parents=True)
    (repo / "main.py").write_text("app = None\n", encoding="utf-8")
    (repo / "static" / "css" / "app.css").write_text("body{}\n", encoding="utf-8")
    run("add", ".")
    base = commit("base")
    # the well-formed amendment: the three compliance pages, added
    (repo / "static" / "compliance").mkdir()
    for name in _COMPLIANCE_PAGES:
        (repo / "static" / "compliance" / name).write_text("<html></html>\n", encoding="utf-8")
    run("add", ".")
    amended = commit("pages")
    # it changes a deployed file
    run("checkout", "-q", "-b", "changes", base)
    (repo / "static" / "css" / "app.css").write_text("body{color:red}\n", encoding="utf-8")
    run("add", ".")
    changes_css = commit("changes-css")
    # it adds a deployed file outside the compliance prefix
    run("checkout", "-q", "-b", "outside", base)
    (repo / "static" / "other.html").write_text("<html></html>\n", encoding="utf-8")
    run("add", ".")
    outside = commit("outside")
    # it only touches files the deployment does not carry
    run("checkout", "-q", "-b", "docs-only", base)
    (repo / "docs").mkdir()
    (repo / "docs" / "note.md").write_text("note\n", encoding="utf-8")
    run("add", ".")
    docs_only = commit("docs-only")
    # it does not descend from the effective commit (an unrelated root commit in the same repository)
    tree = subprocess.run(["git", "-C", str(repo), "mktree"], input=b"", capture_output=True, check=True)
    fork = subprocess.run(["git", "-C", str(repo), "commit-tree", tree.stdout.decode().strip(), "-m", "fork"],
                          capture_output=True, text=True, check=True).stdout.strip()
    return {"repo": repo, "base": base, "amended": amended, "changes_css": changes_css,
            "outside": outside, "docs_only": docs_only, "fork": fork}


def _to_c9_with_the_repo_commit(directory, observer, base):
    """C0..C9 where C0's commit is a real commit of the injected repository."""
    _grant_all(directory)
    _drive(directory, "C8", overrides={"C0": {"commit": base}}, observer=observer)
    ls.deploy(directory, observer, commit=base)
    ledger.advance(directory, "C9", {**GOOD["C9"], "commit": base})


def test_an_amendment_that_only_adds_compliance_pages_supersedes_the_candidate(directory, observer,
                                                                               amendment_repo):
    from tools import deploy_audit as da

    base, amended, repo = amendment_repo["base"], amendment_repo["amended"], amendment_repo["repo"]
    _to_c9_with_the_repo_commit(directory, observer, base)
    amended_dpl = "dpl_" + "W" * 24
    assert _code(ls.deploy, directory, observer, amended_dpl, commit=amended) == "COMMIT_NOT_THE_REHEARSED_ONE"
    entry = ledger.amend(directory, amended, "U-AMEND-1", repo=repo)
    assert entry["type"] == "amendment" and entry["amends"] == base and entry["commit"] == amended
    files = {path: blob for path, blob in da._committed_blobs(amended, repo).items() if da._allowed(path)}
    assert entry["code_sha256"] == hosting.code_sha256(files)
    assert ledger.status(directory)["state"] == "C9"  # the amendment does not advance a state
    assert _code(ls.deploy, directory, observer, amended_dpl, commit=base) == "COMMIT_NOT_THE_REHEARSED_ONE"
    assert _code(ls.deploy, directory, observer, amended_dpl, commit=amended,
                 code=OTHER_CODE) == "DEPLOYMENT_CODE_CHANGED"
    ls.deploy(directory, observer, amended_dpl, commit=amended, code=entry["code_sha256"])
    ls.promote(directory, observer, amended_dpl)
    assert ledger.advance(directory, "C10", GOOD["C10"])["state"] == "C10"


def test_amendments_refuse_anything_but_appended_compliance_pages(directory, observer, amendment_repo):
    repo = amendment_repo["repo"]
    _to_c9_with_the_repo_commit(directory, observer, amendment_repo["base"])
    amended = amendment_repo["amended"]
    assert _code(ledger.amend, directory, amended, "not a reference!", repo=repo) == "REFERENCE_NOT_OPAQUE"
    assert _code(ledger.amend, directory, amendment_repo["base"], "U-2", repo=repo) == "AMENDMENT_NOT_NEW"
    assert _code(ledger.amend, directory, amendment_repo["changes_css"], "U-3",
                 repo=repo) == "AMENDMENT_CHANGES_DEPLOYED_FILES"
    assert _code(ledger.amend, directory, amendment_repo["outside"], "U-4",
                 repo=repo) == "AMENDMENT_FILE_OUTSIDE_COMPLIANCE"
    assert _code(ledger.amend, directory, amendment_repo["docs_only"], "U-5", repo=repo) == "AMENDMENT_EMPTY"
    assert _code(ledger.amend, directory, amendment_repo["fork"], "U-6", repo=repo) == "AMENDMENT_NOT_DESCENDANT"
    ledger.amend(directory, amended, "U-AMEND-2", repo=repo)  # the well-formed one is accepted once
    assert _code(ledger.amend, directory, amended, "U-7", repo=repo) == "AMENDMENT_NOT_NEW"


def test_an_amendment_is_refused_after_the_point_of_no_return(directory, amendment_repo):
    _grant_all(directory)
    _drive(directory, "C13")
    assert _code(ledger.amend, directory, amendment_repo["amended"], "U-late",
                 repo=amendment_repo["repo"]) == "AMENDMENT_AFTER_PONR"


# ---- the product-contract amendment (A19): after the reference, before the PONR, GC1 then GC2 ---------


def _commit_on_top(repo, parent, path, text):
    import subprocess

    def run(*arguments):
        return subprocess.run(["git", "-C", str(repo), *arguments], capture_output=True, text=True, check=True)

    run("checkout", "-q", "-B", "on-top-" + parent[:8], parent)
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text(text, encoding="utf-8")
    run("add", ".")
    run("commit", "-qm", "on top")
    return run("rev-parse", "HEAD").stdout.strip()


def _to_c12_with_the_repo_commit(directory, observer, base):
    """C0..C12 where the candidate (C0, C9, the lift) is a real commit of the injected repository."""
    _to_c9_with_the_repo_commit(directory, observer, base)
    ls.promote(directory, observer)
    ledger.advance(directory, "C10", GOOD["C10"])
    ledger.advance(directory, "C11", GOOD["C11"])
    ls.set_clock(ledger._CLOCK() + timedelta(minutes=1))
    ls.record(directory, observer)
    taken = ls.take(directory, observer)
    ls.deploy(directory, observer, LIFT, admission="OPEN", opening_reference=taken["hash"], commit=base)
    ls.promote(directory, observer, LIFT)
    observer.admission_state = "open"
    observer.tag = hosting.opening_tag(taken["hash"])
    assert ledger.open_admission(directory, observer=observer)["state"] == "C12"
    return taken


def test_a_product_contract_amendment_needs_its_own_gc1_after_the_reference_and_before_the_ponr(
        directory, observer, amendment_repo):
    repo, base, changes = amendment_repo["repo"], amendment_repo["base"], amendment_repo["changes_css"]
    _to_c9_with_the_repo_commit(directory, observer, base)
    # before the reference the candidate is amended by `amend` alone (A18): no contract gate exists yet
    assert _code(ledger.grant, directory, "GC1", "U-GC1-early") == "CONTRACT_GATE_BEFORE_THE_REFERENCE"
    assert _code(ledger.amend, directory, changes, "U-A19", repo=repo,
                 contract_ref="U-GC1-early") == "CONTRACT_GATE_BEFORE_THE_REFERENCE"
    ls.promote(directory, observer)
    ledger.advance(directory, "C10", GOOD["C10"])
    ledger.advance(directory, "C11", GOOD["C11"])
    ls.set_clock(ledger._CLOCK() + timedelta(minutes=1))
    ls.record(directory, observer)
    taken = ls.take(directory, observer)
    ls.deploy(directory, observer, LIFT, admission="OPEN", opening_reference=taken["hash"], commit=base)
    ls.promote(directory, observer, LIFT)
    observer.admission_state, observer.tag = "open", hosting.opening_tag(taken["hash"])
    ledger.open_admission(directory, observer=observer)
    # the A18 path keeps its guard: without GC1 a changed deployed file is refused
    assert _code(ledger.amend, directory, changes, "U-A19", repo=repo) == "AMENDMENT_CHANGES_DEPLOYED_FILES"
    assert _code(ledger.amend, directory, changes, "U-A19", repo=repo, contract_ref="U-GC1", observer=observer) == "GATE_NOT_GRANTED"
    ledger.grant(directory, "GC1", "U-GC1")
    assert _code(ledger.grant, directory, "GC1", "U-GC1") == "GATE_ALREADY_GRANTED"  # one message, one use
    assert _code(ledger.amend, directory, amendment_repo["docs_only"], "U-A19", repo=repo,
                 contract_ref="U-GC1", observer=observer) == "AMENDMENT_EMPTY"
    assert _code(ledger.amend, directory, amendment_repo["fork"], "U-A19", repo=repo,
                 contract_ref="U-GC1", observer=observer) == "AMENDMENT_NOT_DESCENDANT"
    assert _code(ledger.amend, directory, base, "U-A19", repo=repo, contract_ref="U-GC1", observer=observer) == "AMENDMENT_NOT_NEW"
    entry = ledger.amend(directory, changes, "U-A19", repo=repo, contract_ref="U-GC1", observer=observer)
    assert entry["contract_ref"] == "U-GC1" and entry["amends"] == base and entry["commit"] == changes
    status = ledger.status(directory)
    assert status["state"] == "C12" and status["opening_reference"] == taken["hash"]  # nothing else moves
    second = _commit_on_top(repo, changes, "static/css/app.css", "body{color:blue}\n")
    assert _code(ledger.amend, directory, second, "U-A19b", repo=repo, contract_ref="U-GC1", observer=observer) == "GATE_ALREADY_USED"
    ledger.grant(directory, "GC1", "U-GC1b")
    assert ledger.amend(directory, second, "U-A19b", repo=repo, contract_ref="U-GC1b", observer=observer)["amends"] == changes


def test_the_amended_candidate_reopens_only_under_its_own_gc2_and_its_own_authorization(
        directory, observer, amendment_repo):
    repo, base, changes = amendment_repo["repo"], amendment_repo["base"], amendment_repo["changes_css"]
    taken = _to_c12_with_the_repo_commit(directory, observer, base)
    reference = taken["hash"]
    ledger.grant(directory, "GC1", "U-GC1")
    amended = ledger.amend(directory, changes, "U-A19", repo=repo, contract_ref="U-GC1", observer=observer)
    code = amended["code_sha256"]
    # the old candidate is no longer deployable, the new one only with its own code
    assert _code(ls.deploy, directory, observer, "dpl_" + "J" * 24, commit=base) == "COMMIT_NOT_THE_REHEARSED_ONE"
    assert _code(ls.deploy, directory, observer, "dpl_" + "J" * 24, commit=changes,
                 code=OTHER_CODE) == "DEPLOYMENT_CODE_CHANGED"
    paused = "dpl_" + "K" * 24
    ls.deploy(directory, observer, paused, commit=changes, code=code)  # the operator-only proof deployment
    reopened = "dpl_" + "R" * 24
    ls.deploy(directory, observer, reopened, admission="OPEN", opening_reference=reference, commit=changes,
              code=code, observed_admission="CLOSED")
    assert not observer.authorization_valid(reference, code, PLATFORM_PROJECT)  # admits no one yet
    assert _code(ledger.authorize_code, directory, reopened, observer=observer, backup_root=directory.parent, off_platform=directory.parent) == "GATE_ONLY_AFTER_PONR"
    assert _code(ledger.authorize_code, directory, reopened, observer=observer, backup_root=directory.parent, off_platform=directory.parent,
                 contract_ref="U-GC2") == "GATE_NOT_GRANTED"
    ledger.grant(directory, "GC2", "U-GC2")
    assert _code(ledger.authorize_code, directory, LIFT, observer=observer, backup_root=directory.parent, off_platform=directory.parent,
                 contract_ref="U-GC2") == "NOT_A_RECORDED_REOPENING"  # the old open deployment
    assert _code(ledger.authorize_code, directory, paused, observer=observer, backup_root=directory.parent, off_platform=directory.parent,
                 contract_ref="U-GC2") == "NOT_A_RECORDED_REOPENING"  # an operator deployment
    entry = ledger.authorize_code(directory, reopened, observer=observer, backup_root=directory.parent, off_platform=directory.parent, contract_ref="U-GC2")
    assert entry["type"] == "authorization" and entry["opening_reference"] == reference
    assert entry["contract_ref"] == "U-GC2" and entry["forward_fix_ref"] == "NONE" and entry["code_sha256"] == code
    assert observer.authorization_valid(reference, code, PLATFORM_PROJECT)
    # the application accepts it exactly as it accepts the reference's own authorization
    assert hosting.opening_entry_authorizes(json.dumps(entry), reference=reference, database_identity=IDENTITY,
                                            code=code, project=PLATFORM_PROJECT)
    assert _code(ledger.authorize_code, directory, reopened, observer=observer, backup_root=directory.parent, off_platform=directory.parent,
                 contract_ref="U-GC2") == "GATE_ALREADY_USED"
    ledger.grant(directory, "GC2", "U-GC2b")
    assert _code(ledger.authorize_code, directory, reopened, observer=observer, backup_root=directory.parent, off_platform=directory.parent,
                 contract_ref="U-GC2b") == "CODE_ALREADY_AUTHORIZED"
    assert ledger.status(directory)["state"] == "C12"  # the PONR is still the first business write


def test_an_amendment_supersedes_the_earlier_code_at_once_and_never_brings_it_back(
        directory, observer, amendment_repo, monkeypatch):
    """A19 R3 M2: after a GC1 amendment the superseded code admits no one, in PROD and at promotion."""
    repo, base, changes = amendment_repo["repo"], amendment_repo["base"], amendment_repo["changes_css"]
    taken = _to_c12_with_the_repo_commit(directory, observer, base)
    reference, old_code = taken["hash"], taken["code_sha256"]
    assert observer.authorization_valid(reference, old_code, PLATFORM_PROJECT)
    ledger.grant(directory, "GC1", "U-GC1")
    amended = ledger.amend(directory, changes, "U-A19", repo=repo, contract_ref="U-GC1", observer=observer)
    assert amended["authorizations"] == "SUPERSEDED"
    assert not observer.authorization_valid(reference, old_code, PLATFORM_PROJECT)  # in the same transaction
    # the old open deployment can no longer be promoted back to the public address
    assert _code(ledger.recorded_deployment, directory, LIFT) == "OPEN_DEPLOYMENT_NOT_AUTHORIZED"
    # a revert to an authorized code is refused (it would re-open without GC2)
    ledger.grant(directory, "GC1", "U-GC1-revert")
    revert = _commit_on_top(repo, changes, "static/css/app.css", "body{}\n")
    monkeypatch.setattr(ledger.hosting, "code_sha256", lambda files: old_code)
    assert _code(ledger.amend, directory, revert, "U-A19r", repo=repo, contract_ref="U-GC1-revert",
                 observer=observer) == "AMENDMENT_CODE_ALREADY_AUTHORIZED"


def test_a_reopening_reproves_a_fresh_verified_backup_and_supersedes_every_other_code(
        directory, observer, amendment_repo):
    """A19 R3 M6: GC2 re-proves what the opening proved; its authorization is then the only one."""
    repo, base, changes = amendment_repo["repo"], amendment_repo["base"], amendment_repo["changes_css"]
    taken = _to_c12_with_the_repo_commit(directory, observer, base)
    reference = taken["hash"]
    ledger.grant(directory, "GC1", "U-GC1")
    code = ledger.amend(directory, changes, "U-A19", repo=repo, contract_ref="U-GC1", observer=observer)["code_sha256"]
    reopened = "dpl_" + "R" * 24
    ls.deploy(directory, observer, reopened, admission="OPEN", opening_reference=reference, commit=changes,
              code=code, observed_admission="CLOSED")
    ledger.grant(directory, "GC2", "U-GC2")
    roots = {"backup_root": directory.parent, "off_platform": directory.parent}

    def gc2(**overrides):
        return ledger.authorize_code(directory, reopened, observer=observer, contract_ref="U-GC2",
                                     **dict(roots, **overrides))

    assert _code(gc2, backup_root=None) == "BACKUP_ROOTS_REQUIRED"
    observer.matches = False
    assert _code(gc2) == "BACKUP_NOT_CURRENT"  # the backup does not hold the current business state
    observer.matches = True
    on_disk = observer.generation
    observer.generation = dict(on_disk, dump_sha256="0" * 64)
    assert _code(gc2) == "BACKUP_NOT_THE_RECORDED_ONE"
    observer.generation = on_disk
    observer.platform["dpl_" + "Z" * 24] = {"url": "https://stray.example.invalid", "state": "READY", "files": "x"}
    assert _code(gc2) == "UNRECORDED_DEPLOYMENT"  # a deployment made outside the governed deploy
    del observer.platform["dpl_" + "Z" * 24]
    later = ledger._CLOCK()
    ls.set_clock(later + timedelta(days=20))
    assert _code(gc2) == "BACKUP_TOO_OLD_TO_OPEN"
    ls.set_clock(later)
    entry = gc2()
    assert entry["reopening_backup_manifest_sha256"] == observer.generation["manifest_sha256"]
    assert observer.authorization_valid(reference, code, PLATFORM_PROJECT)
    assert not observer.authorization_valid(reference, taken["code_sha256"], PLATFORM_PROJECT)
    assert ledger.recorded_deployment(directory, reopened)["code_sha256"] == code  # promotable now


def test_supersede_revokes_every_code_the_ledger_does_not_authorize(directory, observer):
    """A19 R3 M2: a narrowing act at C12 or after the PONR; it never admits anyone."""
    _grant_all(directory)
    _drive(directory, "C12", observer=observer)
    taken = ledger._summary(ledger.read_ledger(directory))["opening_reference"]
    observer.rows.append({"reference": taken["hash"], "code": OTHER_CODE, "revoked": False, "entry": "{}"})
    entry = ledger.supersede(directory, observer=observer)
    assert entry["type"] == "supersession" and entry["kept_code_sha256"] == taken["code_sha256"]
    assert [row["code"] for row in observer.rows if not row["revoked"]] == [taken["code_sha256"]]


def test_contract_gates_follow_the_opening_not_only_the_reference(directory, observer):
    # At C11 a reference exists but no lift: an amended candidate could not be opened by `open` (it
    # requires the reference's code) nor re-opened (GC2 needs C12), so neither gate is granted there.
    _at_c11_with_generation(directory, observer)
    ls.take(directory, observer)
    assert _code(ledger.grant, directory, "GC1", "U-GC1-c11") == "OUT_OF_ORDER"
    assert _code(ledger.grant, directory, "GC2", "U-GC2-c11") == "OUT_OF_ORDER"


def test_a_reopening_refuses_without_an_amendment_and_under_the_barrier(directory, observer):
    _grant_all(directory)
    _drive(directory, "C12", observer=observer)
    ledger.grant(directory, "GC2", "U-GC2")
    assert _code(ledger.authorize_code, directory, LIFT, observer=observer, backup_root=directory.parent, off_platform=directory.parent,
                 contract_ref="U-GC2") == "NO_CONTRACT_AMENDMENT"
    observer.admission_state, observer.scheduler = "closed", "disabled"
    ledger.close(directory, observer=observer)
    assert _code(ledger.authorize_code, directory, LIFT, observer=observer, backup_root=directory.parent, off_platform=directory.parent, contract_ref="U-GC2") == "BARRIER_APPLIED"


def test_a_reopening_refuses_under_a_barrier_close_applied_but_could_not_record(
        directory, observer, amendment_repo):
    repo, base, changes = amendment_repo["repo"], amendment_repo["base"], amendment_repo["changes_css"]
    taken = _to_c12_with_the_repo_commit(directory, observer, base)
    ledger.grant(directory, "GC1", "U-GC1")
    code = ledger.amend(directory, changes, "U-A19", repo=repo, contract_ref="U-GC1", observer=observer)["code_sha256"]
    reopened = "dpl_" + "R" * 24
    ls.deploy(directory, observer, reopened, admission="OPEN", opening_reference=taken["hash"], commit=changes,
              code=code, observed_admission="CLOSED")
    ledger.grant(directory, "GC2", "U-GC2")
    observer.barrier = {"setting": True}  # the role default is read-only, but no barrier entry exists
    assert _code(ledger.authorize_code, directory, reopened, observer=observer, backup_root=directory.parent, off_platform=directory.parent,
                 contract_ref="U-GC2") == "BARRIER_IN_FORCE"
    assert not observer.authorization_valid(taken["hash"], code, PLATFORM_PROJECT)


def test_contract_gates_never_exist_after_the_ponr(directory):
    _grant_all(directory)
    _drive(directory, "C13")
    assert _code(ledger.grant, directory, "GC1", "U-late") == "GATE_ONLY_BEFORE_PONR"
    assert _code(ledger.grant, directory, "GC2", "U-late") == "GATE_ONLY_BEFORE_PONR"


def test_the_smoked_address_must_be_the_one_promoted_to_the_candidate(directory, observer):
    _grant_all(directory)
    _drive(directory, "C9", observer=observer)
    assert _code(ledger.advance, directory, "C10", GOOD["C10"]) == "PUBLIC_ADDRESS_NOT_PROMOTED"
    ls.promote(directory, observer, host=H["a"])
    assert _code(ledger.advance, directory, "C10", GOOD["C10"]) == "PUBLIC_ADDRESS_NOT_PROMOTED"
    ls.promote(directory, observer)
    assert ledger.advance(directory, "C10", GOOD["C10"])["state"] == "C10"


def test_a_promotion_is_recorded_only_for_the_recorded_deployment_the_platform_resolves(directory, observer):
    _grant_all(directory)
    _drive(directory, "C9", observer=observer)
    base = {"deployment_id": DEPLOYMENT, "public_host_sha256": H["m"], "alias_deployment_id": DEPLOYMENT,
            "files_sha256": ls.FILES, "observed_code": CODE}
    assert _code(ledger.record_promotion, directory, {**base, "deployment_id": "dpl_" + "Z" * 24}) == \
        "DEPLOYMENT_NOT_RECORDED"
    assert _code(ledger.record_promotion, directory, {**base, "files_sha256": H["a"]}) == \
        "DEPLOYMENT_NOT_THE_RECORDED_ONE"
    assert _code(ledger.record_promotion, directory, {**base, "observed_code": OTHER_CODE}) == \
        "DEPLOYMENT_NOT_THE_RECORDED_ONE"
    assert _code(ledger.record_promotion, directory, {**base, "alias_deployment_id": "dpl_" + "Z" * 24}) == \
        "ALIAS_NOT_THE_DEPLOYMENT"
    assert ledger.record_promotion(directory, base)["type"] == "promotion"


# ---- the opening: the reference, the authorization, the lift (A15, A17 finding 1) ------------------------


def test_the_opening_needs_go_a_reference_taken_while_closed_and_admission_observed_open(directory, observer):
    _grant_all(directory, ALL_GATES[:-1])  # everything but GO
    _drive(directory, "C11", observer=observer)
    ls.record(directory, observer)
    assert _code(ls.take, directory, observer) == "GATE_NOT_GRANTED"
    ledger.grant(directory, "GO", "m-go")
    assert _code(ledger.open_admission, directory, observer=observer) == "REFERENCE_REQUIRED"
    observer.admission_state = "open"  # users already admitted: too late for a reference
    assert _code(ls.take, directory, observer) == "ADMISSION_NOT_CLOSED"
    observer.admission_state = "closed"
    entry = ls.take(directory, observer)
    assert entry["type"] == "reference" and entry["admission"] == "CLOSED"
    assert entry["reference_fingerprint_sha256"] == REFERENCE["fingerprint_sha256"]
    assert entry["code_sha256"] == CODE and entry["vercel_project_sha256"] == PLATFORM_PROJECT
    written = json.loads(_reference_file(directory).read_text())
    assert fp.validate(written)["fingerprint_sha256"] == REFERENCE["fingerprint_sha256"] and written["taken_at"]
    assert _code(ledger.open_admission, directory, observer=observer) == "ALIAS_NOT_THE_AUTHORIZED_DEPLOYMENT"
    ls.lift(directory, observer, entry)
    opened = ledger.open_admission(directory, observer=observer)
    assert opened["state"] == "C12"
    assert opened["evidence"]["reference_fingerprint_sha256"] == REFERENCE["fingerprint_sha256"]
    assert opened["evidence"]["admission"] == "OPEN" and opened["evidence"]["backup_cadence_hours"] == 24
    assert opened["evidence"]["opening_authorized"] is True and opened["evidence"]["deployment_id"] == LIFT


def test_the_reference_writes_one_authorization_that_is_the_entry_itself(directory, observer):
    _at_c11_with_generation(directory, observer)
    taken = ls.take(directory, observer)
    assert len(observer.rows) == 1 and observer.rows[0]["reference"] == taken["hash"]
    stored = observer.rows[0]["entry"]
    # The application's own test: the stored entry hashes to the reference and names this database,
    # the candidate's code and the platform project -- and nothing else passes.
    good = dict(reference=taken["hash"], database_identity=IDENTITY, code=CODE, project=PLATFORM_PROJECT)
    assert hosting.opening_entry_authorizes(stored, **good)
    for change in ({"reference": H["a"]}, {"database_identity": H["b"]}, {"code": OTHER_CODE},
                   {"project": H["c"]}, {"project": None}):
        assert not hosting.opening_entry_authorizes(stored, **{**good, **change}), change
    forged = json.loads(stored)
    forged["backup_cadence_hours"] = 12  # edited: no longer the recorded entry
    assert not hosting.opening_entry_authorizes(json.dumps(forged), **good)
    assert ledger.read_ledger(directory)[-1]["hash"] == taken["hash"]


def test_a_failed_ledger_write_leaves_no_authorization(directory, observer, monkeypatch):
    _at_c11_with_generation(directory, observer)

    def broken(_directory, _entry):
        raise OSError("disk full")

    monkeypatch.setattr(ledger, "_write", broken)
    with pytest.raises(OSError):
        ls.take(directory, observer)
    assert observer.rows == [] and ledger.status(directory)["opening_reference"] is None


@pytest.mark.parametrize("setup,code", [
    # A deployment the governed deploy never recorded may have admitted users.
    (lambda d, o: o.platform.update({"dpl_" + "U" * 24: {"url": "https://u.example.test", "state": "READY",
                                                         "files": H["a"], "admission": "closed", "code": CODE}}),
     "UNRECORDED_DEPLOYMENT"),
    (lambda d, o: o.platform.update({"dpl_" + "Q" * 24: {"url": "https://q.example.test", "state": "BUILDING",
                                                         "files": H["a"], "admission": "unknown", "code": ""}}),
     "UNRECORDED_DEPLOYMENT"),
    # A recorded deployment that admits users at its own address, whatever the public address says.
    (lambda d, o: o.platform[DEPLOYMENT].update(admission="open"), "DEPLOYMENT_NOT_CLOSED"),
    (lambda d, o: o.platform[DEPLOYMENT].update(admission="unknown"), "DEPLOYMENT_NOT_CLOSED"),
    (lambda d, o: o.platform[DEPLOYMENT].update(code=OTHER_CODE), "DEPLOYMENT_CODE_CHANGED"),
    (lambda d, o: setattr(o, "alias", "dpl_" + "Z" * 24), "ALIAS_NOT_THE_CANDIDATE"),
    # An authorization already in PROD was made before this reference (a premature or stale opening).
    (lambda d, o: o.rows.append({"reference": H["a"], "code": CODE, "revoked": False, "entry": "{}"}),
     "OPENING_AUTHORIZATION_EXISTS"),
    (lambda d, o: o.rows.append({"reference": H["a"], "code": CODE, "revoked": True, "entry": "{}"}),
     "OPENING_AUTHORIZATION_EXISTS"),
    (lambda d, o: setattr(o, "project_id", "prj_" + "O" * 28), "PROVIDER_NOT_THE_PROJECT"),
])
def test_the_reference_refuses_on_any_observable_sign_that_production_could_have_opened(
        directory, observer, setup, code):
    _at_c11_with_generation(directory, observer)
    setup(directory, observer)
    before = _ledger_bytes(directory)
    assert _code(ls.take, directory, observer) == code
    assert _ledger_bytes(directory) == before and not _reference_file(directory).exists()


def test_failed_or_cancelled_deployments_are_not_servable_and_do_not_block_the_reference(directory, observer):
    _at_c11_with_generation(directory, observer)
    observer.platform["dpl_" + "E" * 24] = {"url": "https://e.example.test", "state": "ERROR", "files": H["a"],
                                            "admission": "unknown", "code": ""}
    assert ls.take(directory, observer)["type"] == "reference"


def test_one_reference_per_opening_whatever_its_age_and_the_lift_must_carry_it(directory, observer, clock):
    _at_c11_with_generation(directory, observer)
    taken = ls.take(directory, observer)
    # A second reference would re-baseline whatever users wrote after a premature lift.
    assert _code(ls.take, directory, observer, "second.json") == "REFERENCE_ALREADY_TAKEN"
    ls.lift(directory, observer, taken)
    # Lifted with another value, with none, or with the fingerprint digest: only the entry's hash binds.
    for announced in (hosting.opening_tag(H["a"]), "", hosting.opening_tag(REFERENCE["fingerprint_sha256"])):
        observer.tag = announced
        assert _code(ledger.open_admission, directory, observer=observer) == "OPENING_NOT_BOUND_TO_THE_REFERENCE"
    observer.tag = hosting.opening_tag(taken["hash"])
    clock["now"] += timedelta(hours=3)  # a late lift is still after the reference: no dead end
    opened = ledger.open_admission(directory, observer=observer)
    assert opened["evidence"]["opening_bound"] is True and opened["evidence"]["reference_age_seconds"] == 3 * 3600


@pytest.mark.parametrize("setup,code", [
    (lambda o, t: setattr(o, "alias", DEPLOYMENT), "ALIAS_NOT_THE_AUTHORIZED_DEPLOYMENT"),  # still the operator one
    (lambda o, t: o.platform[LIFT].update(files=H["a"]), "DEPLOYMENT_NOT_THE_RECORDED_ONE"),
    (lambda o, t: o.rows[0].update(revoked=True), "OPENING_NOT_AUTHORIZED"),
    (lambda o, t: o.rows.clear(), "OPENING_NOT_AUTHORIZED"),
    # The authorization names the database the reference was taken from: read from another one, it is none.
    (lambda o, t: setattr(o, "facts", dict(SOURCE, database="other")), "OPENING_NOT_AUTHORIZED"),
    (lambda o, t: setattr(o, "code_seen", OTHER_CODE), "DEPLOYMENT_CODE_CHANGED"),
    (lambda o, t: setattr(o, "admission_state", "closed"), "ADMISSION_NOT_OPEN"),
])
def test_the_opening_is_recorded_only_for_the_authorized_recorded_open_deployment(directory, observer, setup, code):
    _at_c11_with_generation(directory, observer)
    taken = ls.take(directory, observer)
    ls.lift(directory, observer, taken)
    setup(observer, taken)
    before = _ledger_bytes(directory)
    assert _code(ledger.open_admission, directory, observer=observer) == code
    assert _ledger_bytes(directory) == before


def test_an_open_deployment_carries_the_recorded_reference_and_nothing_else(directory, observer):
    _at_c11_with_generation(directory, observer)
    taken = ls.take(directory, observer)
    assert _code(ls.deploy, directory, observer, LIFT, admission="OPEN", opening_reference=H["a"]) == \
        "OPEN_WITHOUT_THE_REFERENCE"
    assert _code(ls.deploy, directory, observer, LIFT, admission="OPEN", opening_reference=taken["hash"],
                 code=OTHER_CODE) == "DEPLOYMENT_CODE_CHANGED"
    assert ls.deploy(directory, observer, LIFT, admission="OPEN", opening_reference=taken["hash"])["admission"] == "OPEN"


def test_the_reference_is_taken_at_the_production_deployment_whose_scheduler_front_is_enabled(directory, observer):
    """An older deployment (no CRON_SECRET) answers closed for ever; probing it would prove nothing."""
    _at_c11_with_generation(directory, observer)
    observer.scheduler = "disabled"
    assert _code(ls.take, directory, observer) == "SCHEDULER_FRONT_NOT_ENABLED"


def test_the_opening_needs_a_generation_within_the_cadence(directory, observer, clock):
    _at_c11_with_generation(directory, observer)
    taken = ls.take(directory, observer)
    ls.lift(directory, observer, taken)
    clock["now"] += timedelta(hours=37)  # longer than 1.5 x 24 h since the pre-opening generation
    assert _code(ledger.open_admission, directory, observer=observer) == "BACKUP_TOO_OLD_TO_OPEN"
    observer.generation = ls.generation(7, objects=None)
    ls.record(directory, observer)  # still allowed at C11
    assert ledger.open_admission(directory, observer=observer)["state"] == "C12"


def test_the_opening_needs_an_object_set_within_its_weekly_cadence(directory, observer, clock):
    _at_c11_with_generation(directory, observer)
    taken = ls.take(directory, observer)
    ls.lift(directory, observer, taken)
    for day in range(1, 12):  # fresh Layer-2 every day, but no new object set for 11 days
        clock["now"] += timedelta(days=1)
        observer.generation = ls.generation(500 + day, objects=None)
        ls.record(directory, observer)
    assert _code(ledger.open_admission, directory, observer=observer) == "BACKUP_TOO_OLD_TO_OPEN"
    clock["now"] += timedelta(minutes=1)
    observer.generation = ls.generation(600, objects="fresh-objects")
    ls.record(directory, observer)
    assert ledger.open_admission(directory, observer=observer)["state"] == "C12"


def test_status_names_the_opening_reference_to_set_and_to_restore(directory, observer):
    _at_c11_with_generation(directory, observer)
    assert ledger.status(directory)["opening_reference"] is None
    taken = ls.take(directory, observer)
    assert ledger.status(directory)["opening_reference"] == taken["hash"]
    ls.lift(directory, observer, taken)
    ledger.open_admission(directory, observer=observer)
    assert ledger.status(directory)["opening_reference"] == taken["hash"]  # still the one to restore after C12
    ledger.advance(directory, "C13", GOOD["C13"])
    assert ledger.status(directory)["opening_reference"] == taken["hash"]


def test_plain_http_is_observed_only_on_the_loopback():
    for url in ("http://sgaa.example.test", "http://10.0.0.5:8080"):
        observer = ledger.Observer(url, allow_insecure=True)
        for probe in (observer.admission, observer.scheduler_front, observer.opening_tag, observer.code):
            with pytest.raises(ledger.Refused) as caught:
                probe()
            assert caught.value.code == "INSECURE_ONLY_ON_LOOPBACK"
    assert ledger.Observer("http://127.0.0.1:1", allow_insecure=True)._require_base() == "http://127.0.0.1:1"
    with pytest.raises(ledger.Refused):
        ledger.Observer("http://127.0.0.1:1", allow_insecure=True,
                        scheduler_url="http://sgaa.example.test").scheduler_front()
    with pytest.raises(ledger.Refused):  # a deployment address is held to the same rule
        ledger.Observer("http://127.0.0.1:1", allow_insecure=True).admission("http://sgaa.example.test")


def test_every_observation_probes_the_public_address_proven_at_c10(directory, observer):
    _at_c11_with_generation(directory, observer)
    observer.host = H["a"]
    assert _code(ls.take, directory, observer) == "ADDRESS_NOT_THE_DEPLOYMENT"
    observer.host = H["m"]
    taken = ls.take(directory, observer)
    ls.lift(directory, observer, taken)
    observer.host = H["a"]
    assert _code(ledger.open_admission, directory, observer=observer) == "ADDRESS_NOT_THE_DEPLOYMENT"
    observer.host = H["m"]
    ledger.open_admission(directory, observer=observer)
    ledger.close(directory, observer=observer)
    observer.admission_state, observer.scheduler = "closed", "disabled"
    observer.host = H["a"]  # another, closed deployment would fake the quiescence of the open one
    assert _code(ledger.rollback, directory, "OPERATOR_STOP", observer=observer,
                 reference_path=str(_reference_file(directory))) == "ADDRESS_NOT_THE_DEPLOYMENT"


def test_the_reference_and_the_opening_follow_c11_only_and_never_a_rollback(directory, observer):
    _grant_all(directory)
    _drive(directory, "C10", observer=observer)
    assert _code(ls.take, directory, observer) == "OUT_OF_ORDER"
    assert _code(ledger.open_admission, directory, observer=observer) == "OUT_OF_ORDER"
    ledger.advance(directory, "C11", GOOD["C11"])
    ls.record(directory, observer)
    ledger.rollback(directory, "OPERATOR_STOP")  # before any reference: a plain record
    assert _code(ls.take, directory, observer) == "ROLLED_BACK"
    assert _code(ledger.open_admission, directory, observer=observer) == "ROLLED_BACK"


def test_the_reference_file_is_new_and_outside_the_repository(directory, observer):
    _at_c11_with_generation(directory, observer)
    inside = Path(ledger.__file__).resolve().parents[1] / "reference-should-not-exist.json"
    assert _code(ledger.take_reference, directory, inside, directory.parent, directory.parent, cadence_hours=24,
                 observer=observer) == "OUTPUT_INSIDE_REPOSITORY"
    existing = _reference_file(directory, "existing.json")
    existing.write_text("{}")
    assert _code(ledger.take_reference, directory, existing, directory.parent, directory.parent, cadence_hours=24,
                 observer=observer) == "OUTPUT_EXISTS"
    assert not inside.exists()


# ---- backups: receipts of the governed run, never a manifest's word (A16, A17 finding 4) ------------------


def test_backups_are_recorded_from_c11_only_and_never_after_a_rollback(directory, observer):
    _grant_all(directory)
    _drive(directory, "C10", observer=observer)
    assert _code(ls.record, directory, observer) == "OUT_OF_ORDER"
    ledger.advance(directory, "C11", GOOD["C11"])
    entry = ls.record(directory, observer)
    assert entry["type"] == "backup" and entry["kind"] == "GENERATION" and entry["provenance"] == "LIVE_RUN"
    assert entry["manifest_sha256"] == _manifest(0) and entry["dump_sha256"] == ls.dump_digest(_manifest(0))
    assert entry["source_identity_sha256"] == IDENTITY and entry["store_project_sha256"] == PROJECT
    ledger.rollback(directory, "OPERATOR_STOP")
    assert _code(ls.record, directory, observer) == "ROLLED_BACK"


def test_each_generation_is_recorded_once_and_dated_inside_its_own_run(directory, observer, clock):
    _grant_all(directory)
    _drive(directory, "C11", observer=observer)
    ls.record(directory, observer)
    assert _code(ls.record, directory, observer) == "BACKUP_ALREADY_RECORDED"  # re-recording would fake the cadence
    observer.generation = ls.generation(5)
    assert _code(ls.record, directory, observer, made=clock["now"] - timedelta(days=1)) == "BACKUP_OLDER_THAN_RECORDED"
    for bad in ({"generation_at": "2026-10-01T00:00:00Z"}, {"run_finished_at": "yesterday"},
                {"run_started_at": None}, {"generation_at": "2027-01-01T00:00:00Z",
                                           "run_finished_at": "2027-01-01T00:01:00Z"}):
        assert _code(ls.record, directory, observer, **bad) == "BACKUP_TIME_INVALID", bad


@pytest.mark.parametrize("overrides,code", [
    # The run observed another database before or after its steps (or none at all).
    ({"source_identity_sha256": H["a"]}, "BACKUP_NOT_FROM_THE_PROD_DATABASE"),
    ({"source_identity_after_sha256": H["a"]}, "BACKUP_NOT_FROM_THE_PROD_DATABASE"),
    ({"source_identity_after_sha256": None}, "BACKUP_NOT_FROM_THE_PROD_DATABASE"),
    ({"store_project_sha256": hosting.project_sha256(OTHER_REF)}, "OBJECT_SET_NOT_FROM_THE_PROD_PROJECT"),
    ({"store_project_sha256": None}, "OBJECT_SET_NOT_FROM_THE_PROD_PROJECT"),
    # Whatever is on disk must be what the run produced: a swapped, resealed or foreign set is not.
    ({"manifest_sha256": H["a"]}, "BACKUP_NOT_THE_RUNS_OUTPUT"),
    ({"dump_sha256": H["a"]}, "BACKUP_NOT_THE_RUNS_OUTPUT"),
    ({"object_set": "another-set"}, "BACKUP_NOT_THE_RUNS_OUTPUT"),
    ({"object_set_digest": H["a"]}, "BACKUP_NOT_THE_RUNS_OUTPUT"),
    ({"object_manifest_sha256": H["a"]}, "BACKUP_NOT_THE_RUNS_OUTPUT"),
    ({"kind": "SNAPSHOT"}, "BACKUP_KIND_INVALID"),
])
def test_a_receipt_that_does_not_bind_this_run_to_the_live_prod_source_is_refused(directory, observer, overrides, code):
    _grant_all(directory)
    _drive(directory, "C11", observer=observer)
    before = _ledger_bytes(directory)
    assert _code(ls.record, directory, observer, **overrides) == code
    assert _ledger_bytes(directory) == before


@pytest.mark.parametrize("change,code", [
    ({"database_source": FOREIGN_CLUSTER}, "BACKUP_NOT_FROM_THE_PROD_DATABASE"),
    ({"database_source": dict(SOURCE, database="scratch")}, "BACKUP_NOT_FROM_THE_PROD_DATABASE"),
    ({"database_source": DEV}, "BACKUP_NOT_FROM_THE_PROD_DATABASE"),
    ({"database_source": SCRATCH}, "BACKUP_NOT_FROM_THE_PROD_DATABASE"),
    ({"database_source": None}, "BACKUP_NOT_FROM_THE_PROD_DATABASE"),
    ({"object_source": {"database": FOREIGN_CLUSTER, "store_host": PROD_REF + ".supabase.co"}},
     "OBJECT_SET_NOT_FROM_THE_PROD_PROJECT"),
    ({"object_source": {"database": SOURCE, "store_host": OTHER_REF + ".supabase.co"}},
     "OBJECT_SET_NOT_FROM_THE_PROD_PROJECT"),
    ({"object_source": None}, "OBJECT_SET_NOT_FROM_THE_PROD_PROJECT"),
])
def test_a_mixed_or_foreign_generation_on_disk_is_refused_even_with_a_good_receipt(directory, observer, change, code):
    """The receipt and the disk agree on the digests, but the sets name another source: still refused."""
    _grant_all(directory)
    _drive(directory, "C11", observer=observer)
    observer.generation = dict(observer.generation, **change)
    before = _ledger_bytes(directory)
    assert _code(ls.record, directory, observer) == code
    assert _ledger_bytes(directory) == before


def test_there_is_no_command_that_records_a_backup_from_disk(tmp_path):
    """Provenance is established while a backup is taken: nothing records a set found on disk."""
    ledger_dir = str(tmp_path / "cli")
    ledger.main(["init", "--ledger-dir", ledger_dir], out=io.StringIO(), err=io.StringIO())
    assert ledger.main(["record-backup", "--ledger-dir", ledger_dir, "--expect-head", "0" * 64,
                        "--backup-root", str(tmp_path), "--off-platform", str(tmp_path)],
                       out=io.StringIO(), err=io.StringIO()) == 2
    assert not hasattr(ledger, "record_backup")


def test_the_pre_opening_generation_must_be_made_after_c11(directory, observer, clock):
    _grant_all(directory)
    _drive(directory, "C10", observer=observer)
    made_before = clock["now"] - timedelta(hours=1)
    ledger.advance(directory, "C11", GOOD["C11"])
    ls.record(directory, observer, made=made_before)  # recorded after C11, made before it
    assert _code(ls.take, directory, observer) == "PRE_OPEN_BACKUP_REQUIRED"


def test_the_reference_needs_a_post_c11_generation_with_objects_proven_current_against_the_live_database(
        directory, observer):
    _grant_all(directory)
    _drive(directory, "C11", observer=observer)
    assert _code(ls.take, directory, observer) == "PRE_OPEN_BACKUP_REQUIRED"
    observer.generation = ls.generation(0, objects=None)
    ls.record(directory, observer)
    assert _code(ls.take, directory, observer) == "PRE_OPEN_BACKUP_REQUIRED"  # no object set
    ls.set_clock(ledger._CLOCK() + timedelta(minutes=1))
    observer.generation = ls.generation(1)
    ls.record(directory, observer)
    observer.generation = ls.generation(99)  # a newer, unrecorded one
    assert _code(ls.take, directory, observer) == "BACKUP_NOT_THE_RECORDED_ONE"
    observer.generation = dict(ls.generation(1), dump_sha256=H["a"])  # the dump replaced after recording
    assert _code(ls.take, directory, observer) == "BACKUP_NOT_THE_RECORDED_ONE"
    observer.generation = ls.generation(1)
    observer.matches = False
    assert _code(ls.take, directory, observer) == "BACKUP_NOT_CURRENT"
    observer.matches = True
    for bad in (0, 25, True):
        assert _code(ledger.take_reference, directory, _reference_file(directory), directory.parent,
                     directory.parent, cadence_hours=bad, observer=observer) == "CADENCE_INVALID"
    entry = ls.take(directory, observer)
    assert entry["pre_open_backup_manifest_sha256"] == _manifest(1) and entry["rpo_hours"] == 24
    assert observer.backup_calls[-1] is True  # the object set was compared with the live rows


def test_the_reference_is_bound_to_the_prod_database_its_backup_came_from(directory, observer):
    _at_c11_with_generation(directory, observer)
    observer.facts = DEV  # DATABASE_URL now names another project
    assert _code(ls.take, directory, observer) == "DATABASE_NOT_THE_PROD_PROJECT"
    observer.facts = dict(SOURCE, database="other")  # the PROD project's server, another database
    assert _code(ls.take, directory, observer) == "DATABASE_NOT_THE_QUALIFIED_ONE"
    observer.facts = dict(SOURCE)
    taken = ls.take(directory, observer)
    assert taken["database_identity_sha256"] == IDENTITY


# ---- the baseline and the restore drills: receipts, not typed OK (A17 finding 6) ---------------------------


def test_c8_needs_the_recorded_baseline_and_its_recorded_restore_drill(directory, observer):
    _grant_all(directory)
    _drive(directory, "C7", observer=observer)
    assert _code(ledger.advance, directory, "C8", GOOD["C8"]) == "BASELINE_REQUIRED"
    saved = observer.generation
    observer.generation = dict(ls.generation(-1, objects="20261020T000000Z-cutover-baseline",
                                             object_digest=BASELINE_OBJECTS),
                               manifest_sha256=BASELINE_MANIFEST, dump_sha256=BASELINE_DUMP)
    ls.record(directory, observer, kind="BASELINE")
    observer.generation = saved
    assert _code(ledger.advance, directory, "C8", GOOD["C8"]) == "BASELINE_RESTORE_REQUIRED"
    assert _code(ledger.advance, directory, "C8", {**GOOD["C8"], "baseline_manifest_sha256": H["a"]}) == \
        "BASELINE_NOT_THE_RECORDED_ONE"
    assert _code(ledger.advance, directory, "C8", {**GOOD["C8"], "object_set_digest": H["a"]}) == \
        "BASELINE_NOT_THE_RECORDED_ONE"
    ledger.record_restore(directory, ls.drill_receipt(BASELINE_MANIFEST, dump=BASELINE_DUMP, objects=BASELINE_OBJECTS))
    for typed in ("restore_drill", "verify_backup"):  # the old typed fields are no evidence any more
        assert _code(ledger.advance, directory, "C8", {**GOOD["C8"], typed: "OK"}) == "EVIDENCE_UNEXPECTED_KEY"
    assert ledger.advance(directory, "C8", GOOD["C8"])["state"] == "C8"


def test_the_baseline_is_taken_at_c7_under_gb1_once_and_with_objects(directory, observer):
    _grant_all(directory, [g for g in ALL_GATES if g != "GB1"])
    _drive(directory, "C6", observer=observer)
    assert _code(ls.record, directory, observer, kind="BASELINE") == "OUT_OF_ORDER"
    ledger.advance(directory, "C7", GOOD["C7"])
    assert _code(ls.record, directory, observer, kind="BASELINE") == "GATE_NOT_GRANTED"
    ledger.grant(directory, "GB1", "m-gb1")
    assert _code(ls.record, directory, observer, kind="GENERATION") == "OUT_OF_ORDER"
    observer.generation = ls.generation(-2, objects=None)
    assert _code(ls.record, directory, observer, kind="BASELINE") == "BASELINE_NEEDS_OBJECTS"
    observer.generation = ls.generation(-3)
    ls.record(directory, observer, kind="BASELINE")
    observer.generation = ls.generation(-4)
    assert _code(ls.record, directory, observer, kind="BASELINE") == "BASELINE_ALREADY_RECORDED"


@pytest.mark.parametrize("overrides,code", [
    ({"generation": H["a"]}, "RESTORE_NOT_OF_A_RECORDED_GENERATION"),
    ({"dump_sha256": H["a"]}, "RESTORE_SOURCE_MISMATCH"),
    ({"source_identity_sha256": H["a"]}, "RESTORE_SOURCE_MISMATCH"),
    ({"object_set_digest": H["a"]}, "RESTORE_OBJECT_SET_NOT_VERIFIED"),
    ({"object_set": "SKIPPED"}, "RESTORE_OBJECT_SET_NOT_VERIFIED"),
    ({"objects_cover_restored_rows": False}, "RESTORE_OBJECT_SET_NOT_VERIFIED"),
    ({"restored": "PARTIAL"}, "RESTORE_NOT_VERIFIED"),
    ({"tables_verified": 0}, "RESTORE_NOT_VERIFIED"),
    ({"tables_verified": True}, "RESTORE_NOT_VERIFIED"),
    ({"target_identity_sha256": IDENTITY}, "RESTORE_TARGET_IS_PROD"),
    ({"target_identity_sha256": None}, "RESTORE_TARGET_IS_PROD"),
    ({"target_scratch": False}, "RESTORE_TARGET_NOT_SCRATCH"),
    ({"target_major": 15}, "RESTORE_TARGET_NOT_THE_PROD_MAJOR"),
])
def test_a_restore_receipt_must_bind_the_recorded_generation_its_source_a_scratch_target_and_both_verifications(
        directory, observer, overrides, code):
    _grant_all(directory)
    _drive(directory, "C11", observer=observer)
    ls.record(directory, observer)
    before = _ledger_bytes(directory)
    manifest = overrides.pop("generation", _manifest(0))
    assert _code(ledger.record_restore, directory, ls.drill_receipt(manifest, **overrides)) == code
    assert _ledger_bytes(directory) == before


def test_a_generation_without_an_object_set_cannot_be_restore_validated(directory, observer):
    _grant_all(directory)
    _drive(directory, "C11", observer=observer)
    observer.generation = ls.generation(0, objects=None)
    ls.record(directory, observer)
    assert _code(ledger.record_restore, directory, ls.drill_receipt(_manifest(0))) == "RESTORE_OBJECT_SET_NOT_VERIFIED"


def test_c14_needs_a_restore_receipt_of_a_window_generation(directory, observer):
    _grant_all(directory)
    _drive(directory, "C13", observer=observer)
    ls.window(directory, observer, days=30, drill=False)
    assert _code(ledger.advance, directory, "C14", GOOD["C14"]) == "RESTORE_RECEIPT_REQUIRED"
    for typed in ("restore_drill", "object_set_verified"):
        assert _code(ledger.advance, directory, "C14", {**GOOD["C14"], typed: "OK"}) == "EVIDENCE_UNEXPECTED_KEY"
    # A drill of another generation (the pre-opening one) does not validate this one.
    ledger.record_restore(directory, ls.drill_receipt(_manifest(0)))
    assert _code(ledger.advance, directory, "C14", GOOD["C14"]) == "RESTORE_RECEIPT_REQUIRED"
    ledger.record_restore(directory, ls.drill_receipt(_manifest(28), objects=__import__("hashlib").sha256(
        b"day-28").hexdigest()))
    assert ledger.advance(directory, "C14", GOOD["C14"])["state"] == "C14"


# ---- the window (A15) ----------------------------------------------------------------------------------


def test_the_window_closes_only_after_ud4_days_from_the_ponr(directory, observer):
    _grant_all(directory)
    _drive(directory, "C13", observer=observer)
    ls.window(directory, observer, days=29)
    assert _code(ledger.advance, directory, "C14", GOOD["C14"]) == "WINDOW_NOT_ELAPSED"


@pytest.mark.parametrize("skip,code", [
    ((10, 11), "BACKUP_CADENCE_BROKEN"),        # two nightly generations missing in the window
    ((), None),
])
def test_the_backup_cadence_must_hold_over_the_whole_window(directory, observer, skip, code):
    _grant_all(directory)
    _drive(directory, "C13", observer=observer)
    ls.window(directory, observer, days=30, skip=skip)
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
        ls.set_clock(opened + timedelta(days=day))
        observer.generation = ls.generation(100 + day, objects=f"open-{day}" if day % 7 == 0 else None)
        ls.record(directory, observer)
    ledger.advance(directory, "C13", GOOD["C13"])
    ls.window(directory, observer, days=30)
    if code:
        assert _code(ledger.advance, directory, "C14", GOOD["C14"]) == code
    else:
        assert ledger.advance(directory, "C14", GOOD["C14"])["state"] == "C14"


def test_the_window_is_counted_from_the_ponr_not_from_the_opening(directory, observer):
    _grant_all(directory)
    _drive(directory, "C12", observer=observer)
    opened = ledger._CLOCK()
    for day in range(1, 6):  # five days pending, the cadence held
        ls.set_clock(opened + timedelta(days=day))
        observer.generation = ls.generation(200 + day, objects=None)
        ls.record(directory, observer)
    ledger.advance(directory, "C13", GOOD["C13"])
    ls.window(directory, observer, days=29)  # 34 days after the opening, 29 after the PONR
    assert _code(ledger.advance, directory, "C14", GOOD["C14"]) == "WINDOW_NOT_ELAPSED"


def test_the_cadence_is_measured_by_when_generations_were_made_not_when_they_were_recorded(directory, observer):
    """A run's time is its own window: a generation made long before cannot be recorded as made now."""
    _grant_all(directory)
    _drive(directory, "C13", observer=observer)
    start = ledger._CLOCK()
    ls.set_clock(start + timedelta(days=1))
    observer.generation = ls.generation(301)
    made = start + timedelta(minutes=5)
    assert _code(ls.record, directory, observer, generation_at=ls._stamp(made),
                 run_started_at=ls._stamp(start + timedelta(days=1, minutes=-1))) == "BACKUP_TIME_INVALID"


def test_a_generation_made_before_the_ponr_is_not_a_window_generation(directory, observer):
    _grant_all(directory)
    _drive(directory, "C13", observer=observer)  # the PONR an hour after the opening
    ponr = ledger._CLOCK()
    observer.generation = ls.generation(400)
    ls.record(directory, observer, made=ponr - timedelta(minutes=30))  # made (and run) before C13
    ls.window(directory, observer, days=30)
    validated = {**GOOD["C14"], "restore_validated_manifest_sha256": _manifest(400)}
    ledger.record_restore(directory, ls.drill_receipt(_manifest(400)))
    assert _code(ledger.advance, directory, "C14", validated) == "RESTORE_VALIDATION_NOT_A_WINDOW_GENERATION"


def test_foreign_generations_never_fill_the_cadence_or_the_restore_validation(directory, observer):
    _grant_all(directory)
    _drive(directory, "C13", observer=observer)
    start = ledger._CLOCK()
    for day in range(2, 31, 2):  # PROD generations every 48 h: the 24 h cadence is broken ...
        ls.set_clock(start + timedelta(days=day))
        observer.generation = ls.generation(800 + day, objects=f"wk-{day}" if day % 6 == 0 else None)
        ls.record(directory, observer)
        # ... and foreign ones in between would mend it, if they counted.
        ls.set_clock(start + timedelta(days=day, hours=24))
        saved = observer.generation
        observer.generation = dict(ls.generation(900 + day), database_source=FOREIGN_CLUSTER)
        assert _code(ls.record, directory, observer) == "BACKUP_NOT_FROM_THE_PROD_DATABASE"
        observer.generation = saved
    ls.set_clock(start + timedelta(days=31, minutes=1))
    assert _code(ledger.record_restore, directory, ls.drill_receipt(_manifest(930))) == \
        "RESTORE_NOT_OF_A_RECORDED_GENERATION"
    assert _code(ledger.advance, directory, "C14", {**GOOD["C14"], "restore_validated_manifest_sha256": _manifest(830)}) \
        == "BACKUP_CADENCE_BROKEN"


def test_the_object_sets_must_be_taken_weekly_through_the_window(directory, observer):
    _grant_all(directory)
    _drive(directory, "C13", observer=observer)
    ls.window(directory, observer, days=30, objects_every_days=12)
    validated = {**GOOD["C14"], "restore_validated_manifest_sha256": _manifest(24)}
    assert _code(ledger.advance, directory, "C14", validated) == "OBJECT_CADENCE_BROKEN"


# ---- closing: the write barrier (A17 finding 2) -----------------------------------------------------------


def _opened(directory, observer):
    _grant_all(directory)
    _drive(directory, "C12", observer=observer)
    observer.admission_state = "closed"  # the authorization is revoked: every deployment answers closed
    observer.scheduler = "disabled"  # and CRON_SECRET was removed
    return str(_reference_file(directory))


def test_close_revokes_the_authorization_and_applies_the_barrier_proven_in_a_fresh_session(directory, observer):
    reference = _opened(directory, observer)
    assert _code(ledger.rollback, directory, "OPERATOR_STOP", observer=observer, reference_path=reference) == \
        "BARRIER_REQUIRED"
    entry = ledger.close(directory, observer=observer)
    assert entry["type"] == "barrier" and entry["action"] == "APPLIED" and entry["authorization"] == "REVOKED"
    assert entry["terminated_sessions"] == 2 and all(row["revoked"] for row in observer.rows)
    assert ledger.status(directory)["barrier"] == "APPLIED"
    assert _code(ledger.close, directory, observer=observer) == "BARRIER_ALREADY_APPLIED"


@pytest.mark.parametrize("broken", [
    {"setting": False}, {"fresh_read_only": False}, {"write_refused": False}, {"older_sessions": 1},
    {"authorizations_in_force": 1},
])
def test_a_barrier_that_does_not_hold_in_a_fresh_session_is_not_recorded(directory, observer, broken, monkeypatch):
    _opened(directory, observer)
    real = observer.apply_barrier

    def weak():
        result = real()
        observer.barrier.update(broken)
        return result

    monkeypatch.setattr(observer, "apply_barrier", weak)
    before = _ledger_bytes(directory)
    assert _code(ledger.close, directory, observer=observer) == "BARRIER_NOT_IN_FORCE"
    assert _ledger_bytes(directory) == before


def test_close_serves_the_opening_only(directory, observer):
    _grant_all(directory)
    _drive(directory, "C11", observer=observer)
    assert _code(ledger.close, directory, observer=observer) == "NOT_OPENED"  # no reference yet: nothing to close
    _drive_ponr = FakeObserver()
    other = directory.parent / "after-ponr"
    ledger.init(other)
    _grant_all(other)
    ls.drive(other, "C13", _drive_ponr)
    assert _code(ledger.close, other, observer=_drive_ponr) == "PONR_RECORDED"


@pytest.mark.parametrize("when", [0, 1, 2])
def test_the_rollback_proof_rechecks_the_barrier_before_each_fingerprint_and_before_the_record(
        directory, observer, when, monkeypatch):
    reference = _opened(directory, observer)
    ledger.close(directory, observer=observer)
    real = observer.barrier_state
    calls = {"n": 0}

    def lapsing(barrier_at):
        state = real(barrier_at)
        if calls["n"] == when:
            state["fresh_read_only"] = False  # someone reset the role default
        calls["n"] += 1
        return state

    monkeypatch.setattr(observer, "barrier_state", lapsing)
    before = _ledger_bytes(directory)
    assert _code(ledger.rollback, directory, "OPERATOR_STOP", observer=observer, reference_path=reference) == \
        "BARRIER_NOT_IN_FORCE"
    assert _ledger_bytes(directory) == before


def test_a_rollback_from_the_opening_with_nothing_changed_is_recorded_after_the_barrier_and_quiescence(
        directory, observer, clock):
    reference = _opened(directory, observer)
    ledger.close(directory, observer=observer)
    entry = ledger.rollback(directory, "OPERATOR_STOP", observer=observer, reference_path=reference)
    assert entry["from_state"] == "C12" and entry["quiescence"] == "PROVEN" and entry["barrier"] == "VERIFIED"
    assert entry["current_fingerprint_sha256"] == REFERENCE["fingerprint_sha256"] and entry["derived_classes"] == []
    assert clock["slept"] == [ledger.QUIESCENCE_SECONDS]
    # The barrier stays: nothing lifts it after a recorded rollback, and production is never reopened.
    assert _code(ledger.resume, directory, observer=observer) == "ROLLED_BACK"
    assert observer.barrier is not None


def test_resume_lifts_the_barrier_and_restores_the_authorization_after_a_refused_rollback(directory, observer):
    reference = _opened(directory, observer)
    ledger.close(directory, observer=observer)
    verdict = {"identical": False, "derived_classes": [], "refusal": "ROWS_ADDED_OR_REMOVED", "current": CHANGED}
    observer.verdicts = [verdict, dict(verdict)]
    assert _code(ledger.rollback, directory, "STOP", observer=observer, reference_path=reference) == \
        "FINGERPRINT_CHANGED"
    assert observer.barrier is not None  # a refused rollback leaves production closed (fail closed)
    entry = ledger.resume(directory, observer=observer)
    assert entry["action"] == "LIFTED" and entry["authorization"] == "RESTORED"
    assert observer.barrier is None and not any(row["revoked"] for row in observer.rows)
    assert _code(ledger.resume, directory, observer=observer) == "BARRIER_NOT_APPLIED"
    ledger.advance(directory, "C13", GOOD["C13"])


def test_resume_lifts_a_barrier_close_applied_but_could_not_record(directory, observer):
    _opened(directory, observer)
    observer.apply_barrier()  # applied, then `close` refused its own verification: no entry
    assert ledger.status(directory)["barrier"] == "NONE"
    assert ledger.resume(directory, observer=observer)["action"] == "LIFTED"


def test_resume_refuses_when_a_fresh_session_still_cannot_write(directory, observer):
    _opened(directory, observer)
    ledger.close(directory, observer=observer)
    observer.lift_works = False
    assert _code(ledger.resume, directory, observer=observer) == "BARRIER_STILL_IN_FORCE"


def test_production_is_never_reopened_or_redeployed_open_under_the_barrier(directory, observer):
    _grant_all(directory)
    _drive(directory, "C11", observer=observer)
    ls.record(directory, observer)
    taken = ls.take(directory, observer)
    ledger.close(directory, observer=observer)  # C11 with a reference: users may already be in
    assert _code(ls.deploy, directory, observer, LIFT, admission="OPEN", opening_reference=taken["hash"]) == \
        "BARRIER_APPLIED"
    ledger.resume(directory, observer=observer)
    ls.lift(directory, observer, taken)
    observer.barrier = {"setting": True}  # applied outside the ledger: a fresh session cannot write
    assert _code(ledger.open_admission, directory, observer=observer) == "BARRIER_IN_FORCE"


# ---- rollback (A15) -----------------------------------------------------------------------------------------


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
    observer = FakeObserver()
    _drive(directory, state, observer=observer)
    entry = ledger.rollback(directory, "OPERATOR_STOP")
    assert entry["from_state"] == state
    summary = ledger.status(directory)
    assert summary["rolled_back"] is True and summary["state"] == state and summary["ponr_recorded"] is False
    following = ledger.STATES[ledger.STATES.index(state) + 1]
    if following != "C12":
        assert _code(ledger.advance, directory, following, GOOD[following]) == "ROLLED_BACK"
    assert ledger.read_ledger(directory)[-1]["type"] == "rollback"  # and the chain still verifies on read


@pytest.mark.parametrize("setup,code", [
    (lambda o: setattr(o, "admission_state", "open"), "ADMISSION_STILL_OPEN"),
    (lambda o: setattr(o, "admission_state", "unknown"), "ADMISSION_STILL_OPEN"),
    (lambda o: setattr(o, "scheduler", "enabled"), "SCHEDULER_STILL_ENABLED"),
    (lambda o: setattr(o, "scheduler", "unknown"), "SCHEDULER_STILL_ENABLED"),
    (lambda o: setattr(o, "jobs", 1), "EXTERNAL_TRIGGER_ACTIVE"),
    (lambda o: setattr(o, "jobs", -1), "QUIESCENCE_UNVERIFIABLE"),
    (lambda o: setattr(o, "facts", dict(SOURCE, system_identifier="7400000000000000002")),
     "DATABASE_NOT_THE_QUALIFIED_ONE"),
])
def test_a_rollback_from_the_opening_refuses_until_production_is_proven_quiescent(directory, observer, setup, code):
    reference = _opened(directory, observer)
    ledger.close(directory, observer=observer)
    setup(observer)
    before = _ledger_bytes(directory)
    assert _code(ledger.rollback, directory, "OPERATOR_STOP", observer=observer, reference_path=reference) == code
    assert _ledger_bytes(directory) == before


def test_a_rollback_from_the_opening_needs_the_observer_and_the_reference_file_the_ledger_recorded(
        directory, observer):
    reference = _opened(directory, observer)
    ledger.close(directory, observer=observer)
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
    ledger.close(directory, observer=observer)
    observer.verdicts = [
        {"identical": True, "derived_classes": [], "refusal": None, "current": REFERENCE},
        {"identical": False, "derived_classes": [], "refusal": "NOT_A_DERIVED_TABLE", "current": CHANGED},
    ]
    assert _code(ledger.rollback, directory, "STOP", observer=observer, reference_path=reference) == \
        "QUIESCENCE_NOT_PROVEN"


def test_any_change_the_fixed_classes_do_not_explain_refuses_the_rollback(directory, observer):
    reference = _opened(directory, observer)
    ledger.close(directory, observer=observer)
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
    ledger.close(directory, observer=observer)
    observed = ["REQUISICOES_AUTO_REJECTION", "REQUISICOES_STUDENT_SEEN"]
    verdict = {"identical": False, "derived_classes": observed, "refusal": None, "current": CHANGED}
    observer.verdicts = [verdict, dict(verdict)]
    assert _code(ledger.rollback, directory, "STOP", observer=observer, reference_path=reference,
                 derived_classes=acknowledged) == "DERIVED_CLASSES_NOT_ACKNOWLEDGED"


def test_observed_derived_classes_acknowledged_exactly_allow_the_rollback_and_are_recorded(directory, observer):
    reference = _opened(directory, observer)
    ledger.close(directory, observer=observer)
    observed = ["REQUISICOES_AUTO_REJECTION"]
    verdict = {"identical": False, "derived_classes": observed, "refusal": None, "current": CHANGED}
    observer.verdicts = [verdict, dict(verdict)]
    entry = ledger.rollback(directory, "STOP", observer=observer, reference_path=reference,
                            derived_classes=["REQUISICOES_AUTO_REJECTION", "REQUISICOES_AUTO_REJECTION"])
    assert entry["derived_classes"] == observed and entry["current_fingerprint_sha256"] == CHANGED["fingerprint_sha256"]


def test_once_a_reference_is_taken_a_rollback_from_c11_is_treated_as_from_the_opening(directory, observer):
    _at_c11_with_generation(directory, observer)
    ls.take(directory, observer)
    # The admission control may already be lifted although `open` was not recorded: users may be in.
    assert _code(ledger.rollback, directory, "STOP") == "QUIESCENCE_PROOF_REQUIRED"
    observer.scheduler = "disabled"
    assert _code(ledger.rollback, directory, "STOP", observer=observer,
                 reference_path=str(_reference_file(directory))) == "BARRIER_REQUIRED"
    ledger.close(directory, observer=observer)
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


def test_a_declared_restore_is_the_ponr_even_when_it_restores_the_opening_content(directory, observer):
    """SPEC A19 (13): the administrator's restore is the PONR; restoring the opening's own content moves no
    digest, so it is recorded on the restore's own trace in PROD: its safety copy's snapshot receipt."""
    _grant_all(directory)
    _drive(directory, "C12", observer=observer)
    opened = ledger._summary(ledger.read_ledger(directory))["evidence"]["C12"]["opened_at"]
    same = {**GOOD["C13"], "current_fingerprint_sha256": REFERENCE["fingerprint_sha256"],
            "detected_at": "2099-01-01T00:00:00Z"}
    assert _code(ledger.advance, directory, "C13", {**same, "write_class": "REQUISICOES"}) == "NO_FINGERPRINT_DELTA"
    declared = {**same, "write_class": "ADMIN_RESTORE", "safety_copy_manifest_sha256": "c" * 64}
    assert _code(ledger.advance, directory, "C13", {**same, "write_class": "ADMIN_RESTORE"},
                 observer=observer) == "EVIDENCE_INVALID"  # the safety copy is named
    assert _code(ledger.advance, directory, "C13", declared, observer=observer) == "DECLARED_RESTORE_NOT_FOUND"
    observer.snapshot_receipts = {"c" * 64: "2000-01-01T00:00:00Z"}  # before the opening: not this restore
    assert _code(ledger.advance, directory, "C13", declared, observer=observer) == "DECLARED_RESTORE_NOT_FOUND"
    observer.snapshot_receipts = {"c" * 64: opened}
    entry = ledger.advance(directory, "C13", declared, observer=observer)
    assert entry["state"] == "C13" and ledger.status(directory)["ponr_recorded"] is True
    assert _code(ledger.rollback, directory, "SMOKE_FAILED") == "PONR_RECORDED"  # forward-fix only from here


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


def test_a_forward_fix_runs_new_code_only_under_its_own_gate_and_its_own_authorization(directory, observer):
    _grant_all(directory)
    _drive(directory, "C13", observer=observer)
    reference = ledger.status(directory)["opening_reference"]
    fix = "dpl_" + "F" * 24
    assert _code(ls.deploy, directory, observer, fix, admission="OPEN", opening_reference=reference,
                 commit=OTHER_COMMIT, code=OTHER_CODE) == "COMMIT_NOT_THE_REHEARSED_ONE"
    assert _code(ls.deploy, directory, observer, fix, admission="OPEN", opening_reference=reference,
                 commit=OTHER_COMMIT, code=OTHER_CODE, forward_fix_ref="m-fix-1") == "FORWARD_FIX_GATE_REQUIRED"
    ledger.grant(directory, "GF1", "m-fix-1")
    ls.deploy(directory, observer, fix, admission="OPEN", opening_reference=reference, commit=OTHER_COMMIT,
              code=OTHER_CODE, forward_fix_ref="m-fix-1", observed_admission="CLOSED")
    assert _code(ls.deploy, directory, observer, "dpl_" + "G" * 24, admission="OPEN", opening_reference=reference,
                 commit=OTHER_COMMIT, code=OTHER_CODE, forward_fix_ref="m-fix-1") == "FORWARD_FIX_GATE_REQUIRED"
    assert not observer.authorization_valid(reference, OTHER_CODE, PLATFORM_PROJECT)  # not open until authorized
    assert _code(ledger.authorize_code, directory, LIFT, observer=observer, backup_root=directory.parent, off_platform=directory.parent) == "NOT_A_RECORDED_FORWARD_FIX"
    entry = ledger.authorize_code(directory, fix, observer=observer, backup_root=directory.parent, off_platform=directory.parent)
    assert entry["type"] == "authorization" and entry["opening_reference"] == reference
    assert observer.authorization_valid(reference, OTHER_CODE, PLATFORM_PROJECT)
    assert _code(ledger.authorize_code, directory, fix, observer=observer, backup_root=directory.parent, off_platform=directory.parent) == "CODE_ALREADY_AUTHORIZED"


def test_a_forward_fix_after_the_window_closed_reverifies_the_newest_generation_on_disk(directory, observer, clock):
    """After C14 the ledger records no generation: the newest one on disk must itself be within the cadence."""
    _grant_all(directory)
    _drive(directory, "C14", observer=observer)
    reference = ledger.status(directory)["opening_reference"]
    ls.set_clock(ledger._CLOCK() + timedelta(days=3))
    fix = "dpl_" + "F" * 24
    ledger.grant(directory, "GF1", "m-fix-late")
    ls.deploy(directory, observer, fix, admission="OPEN", opening_reference=reference, commit=OTHER_COMMIT,
              code=OTHER_CODE, forward_fix_ref="m-fix-late", observed_admission="CLOSED")
    roots = {"backup_root": directory.parent, "off_platform": directory.parent}
    observer.generation = dict(observer.generation, created_at=None)
    assert _code(ledger.authorize_code, directory, fix, observer=observer, **roots) == "BACKUP_TOO_OLD_TO_OPEN"
    stale = (ledger._CLOCK() - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    observer.generation = dict(observer.generation, created_at=stale)
    assert _code(ledger.authorize_code, directory, fix, observer=observer, **roots) == "BACKUP_TOO_OLD_TO_OPEN"
    observer.generation = dict(ls.generation(9), created_at=ledger._CLOCK().strftime("%Y-%m-%dT%H:%M:%SZ"))
    assert ledger.authorize_code(directory, fix, observer=observer, **roots)["code_sha256"] == OTHER_CODE


def test_authorize_code_takes_the_provider_ids_its_deployment_sweep_needs(directory, capsys):
    """R2 B1: the command line accepts --vercel-team/--vercel-project (refused here on the ledger, not on usage)."""
    _grant_all(directory)
    _drive(directory, "C13")
    head = ledger.status(directory)["head"]
    code = ledger.main(["authorize-code", "--ledger-dir", str(directory), "--expect-head", head,
                        "--deployment", "dpl_" + "F" * 24, "--vercel-team", "team_" + "x" * 12,
                        "--vercel-project", "prj_" + "x" * 12,
                        "--backup-root", str(directory.parent), "--off-platform", str(directory.parent)])
    assert code == 1 and "NOT_A_RECORDED_FORWARD_FIX" in capsys.readouterr().err


def test_no_code_is_authorized_after_the_reference_before_the_ponr(directory, observer):
    _grant_all(directory)
    _drive(directory, "C12", observer=observer)
    assert _code(ledger.authorize_code, directory, LIFT, observer=observer, backup_root=directory.parent, off_platform=directory.parent) == "GATE_ONLY_AFTER_PONR"


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


def test_the_ledgers_hash_is_the_one_the_application_recomputes(directory):
    entry = ledger.grant(directory, "GR0", "m1")
    body = {key: value for key, value in entry.items() if key != "hash"}
    assert hosting.ledger_entry_hash(body) == entry["hash"] == ledger._entry_hash(body)


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
    assert _code(ledger.close, directory, expect_head=seen, observer=observer) == "HEAD_MISMATCH"


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
    before = _ledger_bytes(directory)
    assert _code(ledger.advance, directory, "C4", wide_list) == "EVIDENCE_TOO_LARGE"
    assert _ledger_bytes(directory) == before


def test_a_receipt_carrying_free_text_is_refused_before_anything_is_written(directory, observer):
    _grant_all(directory)
    _drive(directory, "C8", observer=observer)
    before = _ledger_bytes(directory)
    assert _code(ls.deploy, directory, observer, forward_fix_ref="NONE", aliased="the alias was moved") == \
        "EVIDENCE_NOT_VALUE_FREE"
    assert _ledger_bytes(directory) == before


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
        ["qualify", "--ledger-dir", ledger_dir],
        ["rollback", "--ledger-dir", ledger_dir, "--reason", "STOP"],
        ["reference", "--ledger-dir", ledger_dir, "--backup-root", str(tmp_path), "--off-platform", str(tmp_path),
         "--out", str(tmp_path / "r.json"), "--backup-cadence-hours", "24"],
        ["open", "--ledger-dir", ledger_dir],
        ["close", "--ledger-dir", ledger_dir],
        ["resume", "--ledger-dir", ledger_dir],
        ["authorize-code", "--ledger-dir", ledger_dir, "--deployment", DEPLOYMENT],
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


def test_the_command_line_reaches_the_prod_database_only_through_the_verified_source(tmp_path, monkeypatch):
    """`qualify` opens DATABASE_URL through tools/prod_source: a routing variable or a scratch URL is refused."""
    directory = tmp_path / "cli-source"
    ledger.init(directory)
    _grant_all(directory)
    ledger.advance(directory, "C0", GOOD["C0"])
    head = ledger.status(directory)["head"]
    monkeypatch.setenv("DATABASE_URL", "postgresql://sgaa@127.0.0.1:5432/scratch")
    _, err = _cli(["qualify", "--ledger-dir", str(directory), "--expect-head", head], ok=False)
    assert err.strip() == "cutover-ledger: refused: SOURCE_NOT_THE_SESSION_POOLER"
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres.%s@aws-0-us-east-1.pooler.supabase.com:5432/postgres"
                       % PROD_REF)
    monkeypatch.setenv("PGHOSTADDR", "127.0.0.1")
    _, err = _cli(["qualify", "--ledger-dir", str(directory), "--expect-head", head], ok=False)
    assert err.strip() == "cutover-ledger: refused: SOURCE_ENV_ROUTING"


def test_the_command_line_runs_as_a_script_from_anywhere(tmp_path):
    """The runbook runs `python tools/cutover_ledger.py`: its observing commands must import their tools."""
    import subprocess
    import sys

    directory = tmp_path / "ledger"
    ledger.init(directory)
    _grant_all(directory)
    ledger.advance(directory, "C0", GOOD["C0"])
    done = subprocess.run(
        [sys.executable, str(Path(ledger.__file__)), "qualify", "--ledger-dir", str(directory),
         "--expect-head", ledger.status(directory)["head"]],
        cwd=tmp_path, capture_output=True, text=True, timeout=180,
        env={k: v for k, v in __import__("os").environ.items() if k != "DATABASE_URL"})
    # It imports its tools and reaches its own refusal: no database to prove production from.
    assert done.returncode == 1 and done.stderr.startswith("cutover-ledger: refused: SOURCE_REQUIRED"), done.stderr[-400:]
