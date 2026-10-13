# coding: utf-8
"""MP-3 SPEC A19 (17): the rereview of b83b5fc (M1-M4), reproduced first and kept as tests.

Admission is bound to a platform DEPLOYMENT, not only to a code: an open process admits users only while
PROD holds the authorization of its code AND an admission of its own deployment (``VERCEL_DEPLOYMENT_ID``)
that the ledger wrote for one recorded deployment.  The application's own admission hook runs here (a
Flask application with the real gate); the ledger and its control flow are real; PROD, the platform and
the addresses are scripted (``tests/mp3_ledger_support.FakeObserver``).

Adapted from the independent reviewer's probes (each failed on b83b5fc).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app import hosting
from tests import mp3_ledger_support as ls
from tools import cutover_ledger as ledger


@pytest.fixture
def position(tmp_path, monkeypatch):
    """A ledger at C12: the reference taken, the lift deployment recorded, admitted and promoted."""
    ls.install_clock(monkeypatch, datetime(2026, 11, 1, 8, tzinfo=timezone.utc))
    directory = tmp_path / "ledger"
    ledger.init(directory)
    for index, gate in enumerate(ls.ALL_GATES):
        ledger.grant(directory, gate, f"independent-{index}")
    observer = ls.FakeObserver()
    ls.drive(directory, "C12", observer)
    return directory, observer


def _code(call, *args, **kwargs):
    with pytest.raises(ledger.Refused) as caught:
        call(*args, **kwargs)
    return caught.value.code


def _gate(observer, monkeypatch, *, reference, code, deployment):
    """The status the REAL admission hook answers on ``/login`` for a process running ``code`` at
    ``deployment`` (``None``: the platform did not name it), reading PROD's rows as the application does."""
    from flask import Flask

    from app import db as app_db
    from app.web import admission_gate as gate

    class Connection:
        def execute(self, sql, params):
            if sql == hosting.OPENING_SELECT_SQL:
                row = next((r for r in observer.rows if not r["revoked"] and (r["reference"], r["code"]) == params), None)
            else:
                assert sql == hosting.ADMISSION_SELECT_SQL
                row = next((r for r in observer.admissions if (r["reference"], r["deployment"]) == params), None)
            return SimpleNamespace(fetchone=lambda: (row["entry"],) if row else None)

        def rollback(self):
            pass

    monkeypatch.setattr(app_db, "get_db_connection", lambda: SimpleNamespace(raw_connection=Connection()))
    monkeypatch.setattr(hosting, "database_source", lambda raw: dict(observer.facts))
    monkeypatch.setattr(gate, "_runtime_code", lambda: code)
    app = Flask("deployment-admission")
    app.config["IS_PRODUCTION"] = True
    environ = {"SGAA_ADMISSION": "open", "SGAA_OPENING_REFERENCE": reference, "VERCEL_PROJECT_ID": ls.PROJECT_ID}
    if deployment is not None:
        environ["VERCEL_DEPLOYMENT_ID"] = deployment
    gate.install(app, environ)
    app.add_url_rule("/login", view_func=lambda: "admitted")
    response = app.test_client().get("/login")
    # it names itself as the platform named it; a missing or malformed name is never announced
    assert response.headers.get(hosting.DEPLOYMENT_HEADER) == hosting.deployment_id(environ)
    return response.status_code


# ---- M1: a late, duplicate, superseded or unnamed deployment never inherits an authorization ------------


def test_m1_a_late_upload_of_the_authorized_code_is_never_admitted(position, monkeypatch):
    """The reviewer's probe: at C12 an open upload of the authorized code loses its answer, is abandoned
    while nothing is visible, and appears later.  The code is authorized, the late deployment is
    not admitted: closed.  Positive control: the admitted lift deployment, same code, same rows."""
    directory, observer = position
    reference = ledger.status(directory)["opening_reference"]
    ledger.begin_deployment(directory, commit=ls.COMMIT, admission="OPEN", opening_reference=reference,
                            forward_fix_ref=None, code=ls.CODE, vercel_project_sha256=ls.PLATFORM_PROJECT)
    assert _code(ledger.reconcile, directory, observer=observer) == "UPLOAD_OUTCOME_UNPROVEN"  # nothing visible proves nothing
    assert ledger.reconcile(directory, observer=observer, abandon_upload=True)["result"] == "ABANDONED"  # the operator abandons it
    late = "dpl_" + "U" * 24
    observer.platform[late] = {"url": "https://late.invalid", "state": "READY", "files": ls.FILES,
                               "admission": "open", "code": ls.CODE}  # it appears now
    assert observer.authorization_valid(reference, ls.CODE, ls.PLATFORM_PROJECT)  # the CODE is authorized
    assert _gate(observer, monkeypatch, reference=reference, code=ls.CODE, deployment=late) == 503
    assert _gate(observer, monkeypatch, reference=reference, code=ls.CODE, deployment=ls.LIFT) == 200
    assert _code(ledger.admit_deployment, directory, late, observer=observer) == "NOT_AN_OPEN_DEPLOYMENT_OF_THE_REFERENCE"


def test_m1_a_recorded_duplicate_is_closed_until_the_ledger_admits_it(position, monkeypatch):
    directory, observer = position
    reference = ledger.status(directory)["opening_reference"]
    twin = "dpl_" + "T" * 24
    ls.deploy(directory, observer, twin, admission="OPEN", opening_reference=reference)  # recorded, same code
    assert _gate(observer, monkeypatch, reference=reference, code=ls.CODE, deployment=twin) == 503
    with pytest.raises(ledger.Refused) as caught:  # nor is it promoted before it is admitted
        ledger.begin_promotion(directory, twin, ls.PUBLIC_HOST, serving=observer.alias)
    assert caught.value.code == "DEPLOYMENT_NOT_ADMITTED"
    entry = ledger.admit_deployment(directory, twin, observer=observer)
    assert entry["type"] == "admission" and entry["deployment_id"] == twin
    assert _gate(observer, monkeypatch, reference=reference, code=ls.CODE, deployment=twin) == 200
    assert _code(ledger.admit_deployment, directory, twin, observer=observer) == "DEPLOYMENT_ALREADY_ADMITTED"


def test_m1_a_process_the_platform_did_not_name_is_never_admitted(position, monkeypatch):
    directory, observer = position
    reference = ledger.status(directory)["opening_reference"]
    assert _gate(observer, monkeypatch, reference=reference, code=ls.CODE, deployment=None) == 503
    assert _gate(observer, monkeypatch, reference=reference, code=ls.CODE, deployment="not-a-deployment") == 503


def test_m1_a_superseded_deployment_is_closed_and_a_forward_fix_admits_only_its_own(position, monkeypatch):
    """After the PONR `authorize-code` authorizes the fix's code AND admits its one recorded deployment; the
    earlier code (the lift) is superseded; a duplicate of the fix's code stays closed."""
    directory, observer = position
    ls.set_clock(ledger._CLOCK() + timedelta(hours=1))
    ledger.advance(directory, "C13", ls.GOOD["C13"])
    reference = ledger.status(directory)["opening_reference"]
    fix, twin = "dpl_" + "F" * 24, "dpl_" + "W" * 24
    for deployment_id, gate_ref in ((fix, "m-fix"), (twin, "m-twin")):
        ledger.grant(directory, "GF1", gate_ref)
        ls.deploy(directory, observer, deployment_id, admission="OPEN", opening_reference=reference,
                  commit=ls.OTHER_COMMIT, code=ls.OTHER_CODE, forward_fix_ref=gate_ref, observed_admission="CLOSED")
    roots = {"backup_root": directory.parent, "off_platform": directory.parent}
    entry = ledger.authorize_code(directory, fix, observer=observer, **roots)
    assert entry["deployment_id"] == fix
    assert _gate(observer, monkeypatch, reference=reference, code=ls.OTHER_CODE, deployment=fix) == 200
    assert _gate(observer, monkeypatch, reference=reference, code=ls.OTHER_CODE, deployment=twin) == 503
    assert _gate(observer, monkeypatch, reference=reference, code=ls.CODE, deployment=ls.LIFT) == 503  # superseded
    assert _code(ledger.admit_deployment, directory, twin, observer=observer) == "PONR_RECORDED"


def test_m1_admission_is_written_only_for_a_recorded_open_deployment_of_the_authorized_code(position):
    directory, observer = position
    reference = ledger.status(directory)["opening_reference"]
    other = "dpl_" + "K" * 24
    ls.deploy(directory, observer, other)  # operator-only
    assert _code(ledger.admit_deployment, directory, other, observer=observer) == "NOT_AN_OPEN_DEPLOYMENT_OF_THE_REFERENCE"
    assert _code(ledger.admit_deployment, directory, "dpl_" + "Z" * 24, observer=observer) == \
        "NOT_AN_OPEN_DEPLOYMENT_OF_THE_REFERENCE"
    twin = "dpl_" + "T" * 24
    ls.deploy(directory, observer, twin, admission="OPEN", opening_reference=reference)
    observer.platform[twin] = dict(observer.platform[twin], files="0" * 64)  # the platform now holds other files
    assert _code(ledger.admit_deployment, directory, twin, observer=observer) == "DEPLOYMENT_NOT_THE_RECORDED_ONE"
    observer.platform[twin]["files"] = ls.FILES
    observer.project_id = "prj_" + "W" * 28  # another project's view
    assert _code(ledger.admit_deployment, directory, twin, observer=observer) == "PROVIDER_NOT_THE_PROJECT"
    observer.project_id = ls.PROJECT_ID
    ledger.close(directory, observer=observer)
    assert _code(ledger.admit_deployment, directory, twin, observer=observer) == "BARRIER_APPLIED"


def test_m1_a_deployment_is_recorded_only_once_it_names_itself_as_the_platform_does(position):
    directory, observer = position
    receipt = ls.reserve_and_receipt(directory, "dpl_" + "N" * 24, observed_deployment_id="")
    assert _code(ls.record_or_abort, directory, receipt) == "DEPLOYMENT_IDENTITY_NOT_OBSERVED"
    receipt = ls.reserve_and_receipt(directory, "dpl_" + "N" * 24, observed_deployment_id="dpl_" + "M" * 24)
    assert _code(ls.record_or_abort, directory, receipt) == "DEPLOYMENT_IDENTITY_NOT_OBSERVED"


def test_m1_the_deployment_entry_admits_only_its_own_named_deployment():
    body = {"seq": 9, "prev": "0" * 64, "at": "2026-11-01T00:00:00Z", "type": "admission",
            "opening_reference": "5" * 64, "deployment_id": ls.LIFT, "code_sha256": ls.CODE,
            "database_identity_sha256": ls.IDENTITY, "vercel_project_sha256": ls.PLATFORM_PROJECT}
    import json

    def text(**changes):
        entry = dict(body, **changes)
        return json.dumps(dict(entry, hash=hosting.ledger_entry_hash(entry)))

    facts = dict(reference="5" * 64, database_identity=ls.IDENTITY, code=ls.CODE, project=ls.PLATFORM_PROJECT)
    assert hosting.deployment_entry_admits(text(), deployment=ls.LIFT, **facts)
    assert not hosting.deployment_entry_admits(text(), deployment="dpl_" + "U" * 24, **facts)
    assert not hosting.deployment_entry_admits(text(), deployment=None, **facts)
    assert not hosting.deployment_entry_admits(text(type="reference"), deployment=ls.LIFT, **facts)
    assert not hosting.deployment_entry_admits(text(code_sha256=ls.OTHER_CODE), deployment=ls.LIFT, **facts)
    assert not hosting.deployment_entry_admits(text(opening_reference="4" * 64), deployment=ls.LIFT, **facts)
    tampered = json.loads(text())
    tampered["deployment_id"] = "dpl_" + "U" * 24
    assert not hosting.deployment_entry_admits(json.dumps(tampered), deployment="dpl_" + "U" * 24, **facts)


# ---- M2: a promotion is sent only when it changes what the address serves -------------------------------


def test_m2_a_promotion_to_the_deployment_already_served_is_never_sent(position):
    """The reviewer's probe: the address serves the lift; a repeat promotion to it could still apply after a
    later promotion, and its own effect is indistinguishable from the current state."""
    directory, observer = position
    assert observer.alias == ls.LIFT
    assert _code(ledger.begin_promotion, directory, ls.LIFT, ls.PUBLIC_HOST, serving=observer.alias) == \
        "PROMOTION_NOT_A_CHANGE"
    assert ledger.status(directory)["unresolved_operation"] is None  # nothing written, nothing sent
    later = ls.promote(directory, observer, ls.DEPLOYMENT)  # a change: from the lift to the operator deployment
    assert ledger.read_ledger(directory)[-2]["serving_before"] == ls.LIFT and later["deployment_id"] == ls.DEPLOYMENT


def test_m2_the_deploy_tool_never_sends_a_promotion_that_changes_nothing(position, monkeypatch):
    from tools import deploy_audit as da, hosted_smoke, vercel_provider as vp

    directory, observer = position
    sent = []

    class Provider:
        project_id = ls.PROJECT_ID

        def deployment(self, identity):
            return {"state": "READY"}

        def files(self, identity):
            return {"app/synthetic.py": "a" * 40}

        def alias_target(self, host):
            return ls.LIFT

        def promote(self, identity):
            sent.append(identity)

    monkeypatch.setattr(vp, "files_sha256", lambda files: ls.FILES)
    monkeypatch.setattr(hosted_smoke, "host_digest", lambda address: ls.PUBLIC_HOST)
    with pytest.raises(da.Refused) as caught:
        da.promote(ls.LIFT, ledger_dir=directory, provider=Provider(), public_url="https://synthetic.invalid")
    assert caught.value.code == "LEDGER_PROMOTION_NOT_A_CHANGE" and sent == []


# ---- M3: every provider observation in the recorded project, at the recorded address --------------------


def test_m3_another_project_never_resolves_a_pending_promotion(position):
    """The reviewer's probe: both scope inputs of another project; refused, the promotion stays pending."""
    directory, _actual = position
    intent = ledger.begin_promotion(directory, ls.DEPLOYMENT, ls.PUBLIC_HOST, serving=ls.LIFT)

    class OtherProject:
        project_id = "prj_" + "W" * 28

        def deployments(self):
            return []

        def alias_target(self, host):
            return "dpl_" + "Z" * 24

    wrong = ledger.Observer(base_url="https://wrong.invalid", provider=OtherProject())
    assert _code(ledger.reconcile, directory, observer=wrong) == "PROVIDER_NOT_THE_PROJECT"
    assert ledger.status(directory)["unresolved_operation"] == intent["hash"]


def test_m3_another_address_never_resolves_a_pending_promotion(position):
    directory, actual = position
    intent = ledger.begin_promotion(directory, ls.DEPLOYMENT, ls.PUBLIC_HOST, serving=ls.LIFT)
    actual.host = ls.H["a"]  # the right project, another public address
    del actual.platform[ls.DEPLOYMENT]  # (which would otherwise "prove" it can never land)
    assert _code(ledger.reconcile, directory, observer=actual) == "ADDRESS_NOT_THE_PROMOTION"
    assert ledger.status(directory)["unresolved_operation"] == intent["hash"]


def test_m3_resume_sweeps_only_the_recorded_project(position):
    """The reviewer's probe: resume given another project's (empty) list would lift the barrier while the
    actual project holds an unrecorded deployment of the authorized code."""
    directory, actual = position
    reference = ledger.status(directory)["opening_reference"]
    ledger.close(directory, observer=actual)
    late = "dpl_" + "V" * 24
    actual.platform[late] = {"url": "https://late.invalid", "state": "READY", "files": ls.FILES,
                             "admission": "open", "code": ls.CODE}

    class OtherProject:
        project_id = "prj_" + "W" * 28

        def deployments(self):
            return []

    class WrongSweep(ledger.Observer):
        def source(self):
            return actual.source()

        def writable(self):
            return actual.writable()

        def backup(self, *args, **kwargs):
            return actual.backup(*args, **kwargs)

        def lift_barrier(self, *args):
            return actual.lift_barrier(*args)

    roots = {"backup_root": directory.parent, "off_platform": directory.parent}
    assert _code(ledger.resume, directory, observer=WrongSweep(provider=OtherProject()), **roots) == \
        "PROVIDER_NOT_THE_PROJECT"
    assert not actual.authorization_valid(reference, ls.CODE, ls.PLATFORM_PROJECT)
    assert _code(ledger.resume, directory, observer=actual, **roots) == "UNRECORDED_DEPLOYMENT"  # the actual sweep


def test_m3_authorize_code_sweeps_only_the_recorded_project(position):
    directory, observer = position
    ls.set_clock(ledger._CLOCK() + timedelta(hours=1))
    ledger.advance(directory, "C13", ls.GOOD["C13"])
    reference = ledger.status(directory)["opening_reference"]
    fix = "dpl_" + "F" * 24
    ledger.grant(directory, "GF1", "m-fix")
    ls.deploy(directory, observer, fix, admission="OPEN", opening_reference=reference, commit=ls.OTHER_COMMIT,
              code=ls.OTHER_CODE, forward_fix_ref="m-fix", observed_admission="CLOSED")
    observer.project_id = "prj_" + "W" * 28
    assert _code(ledger.authorize_code, directory, fix, observer=observer, backup_root=directory.parent,
                 off_platform=directory.parent) == "PROVIDER_NOT_THE_PROJECT"


def test_m3_an_attempt_belongs_to_the_recorded_project(position):
    directory, observer = position
    reference = ledger.status(directory)["opening_reference"]
    assert _code(ledger.begin_deployment, directory, commit=ls.COMMIT, admission="OPERATOR", opening_reference=None,
                 forward_fix_ref=None, code=ls.CODE, vercel_project_sha256="9" * 64) == "DEPLOYMENT_PROJECT_CHANGED"
    ledger.begin_deployment(directory, commit=ls.COMMIT, admission="OPEN", opening_reference=reference,
                            forward_fix_ref=None, code=ls.CODE, vercel_project_sha256=ls.PLATFORM_PROJECT)
    observer.project_id = "prj_" + "W" * 28
    assert _code(ledger.reconcile, directory, observer=observer) == "PROVIDER_NOT_THE_PROJECT"


# ---- M4: resume is a two-phase act ------------------------------------------------------------------------


def test_m4_a_lost_lift_answer_blocks_every_act_until_reconciled(position):
    """The reviewer's probe: PROD commits the lift, its answer is lost.  Every later act is refused (an open
    promotion included) until `reconcile` reads the lift's marker: COMMITTED."""
    directory, observer = position
    ledger.close(directory, observer=observer)
    observer.commit_fault = "lost_ack"
    roots = {"backup_root": directory.parent, "off_platform": directory.parent}
    assert _code(ledger.resume, directory, observer=observer, **roots) == "OPERATION_UNRESOLVED"
    observer.commit_fault = None
    pending = ledger.status(directory)["unresolved_operation"]
    assert pending is not None
    assert _code(ledger.begin_promotion, directory, ls.DEPLOYMENT, ls.PUBLIC_HOST, serving=ls.LIFT) == \
        "OPERATION_UNRESOLVED"
    assert _code(ledger.admit_deployment, directory, ls.LIFT, observer=observer) == "OPERATION_UNRESOLVED"
    outcome = ledger.reconcile(directory, observer=observer)
    assert (outcome["of"], outcome["result"]) == (pending, "COMMITTED")
    assert ledger.status(directory)["barrier"] == "LIFTED"


def test_m4_a_lift_prod_rolled_back_leaves_the_barrier_and_no_open_promotion(position):
    directory, observer = position
    ledger.close(directory, observer=observer)
    observer.commit_fault = "rolled_back"
    roots = {"backup_root": directory.parent, "off_platform": directory.parent}
    assert _code(ledger.resume, directory, observer=observer, **roots) == "PROD_TRANSACTION_FAILED"
    observer.commit_fault = None
    assert ledger.status(directory)["barrier"] == "APPLIED" and ledger.status(directory)["unresolved_operation"] is None
    observer.alias = ls.DEPLOYMENT  # (the address serves the operator deployment)
    assert _code(ledger.begin_promotion, directory, ls.LIFT, ls.PUBLIC_HOST, serving=observer.alias) == "BARRIER_APPLIED"


def test_m4_ending_the_older_sessions_after_the_lift_commit_is_never_read_as_not_committed(monkeypatch):
    """`Observer.lift_barrier`: the lift and its marker committed; a failure while ending the older sessions
    (even a refusal while connecting) is an unknown outcome, never a refusal (which reads as ABORTED)."""
    from contextlib import contextmanager

    observer = ledger.Observer()
    committed = []
    monkeypatch.setattr(observer, "_transact", lambda entry, statements: committed.append(entry["hash"]))

    @contextmanager
    def refused_connection():
        raise ledger.Refused("SOURCE_UNREACHABLE")
        yield  # pragma: no cover

    monkeypatch.setattr(observer, "_connection", refused_connection)
    with pytest.raises(ledger.CommitUncertain):
        observer.lift_barrier("5" * 64, ls.CODE, {"hash": "e" * 64})
    assert committed == ["e" * 64]


def test_m1_admission_refuses_a_barrier_close_applied_but_could_not_record(position):
    directory, observer = position
    reference = ledger.status(directory)["opening_reference"]
    twin = "dpl_" + "T" * 24
    ls.deploy(directory, observer, twin, admission="OPEN", opening_reference=reference)
    observer.barrier = {"setting": True}  # applied in PROD, never recorded
    assert _code(ledger.admit_deployment, directory, twin, observer=observer) == "BARRIER_IN_FORCE"


def test_m4_resume_names_the_head_it_moved_to_when_its_last_check_cannot_read(position, monkeypatch):
    directory, observer = position
    ledger.close(directory, observer=observer)

    def writable():  # read only after the lift (the barrier is recorded): the database cannot be read
        raise ledger.Refused("DATABASE_UNREACHABLE")

    monkeypatch.setattr(observer, "writable", writable)
    with pytest.raises(ledger.Refused) as caught:
        ledger.resume(directory, observer=observer, backup_root=directory.parent, off_platform=directory.parent)
    assert caught.value.code == "DATABASE_UNREACHABLE"
    assert caught.value.head == ledger.status(directory)["head"] and ledger.status(directory)["barrier"] == "LIFTED"


# ---- the rereview of d0fbba7 (invariant 3): an unseen upload is never recorded ABORTED -----------------------


def test_inv3_an_upload_whose_outcome_is_unknown_is_never_recorded_aborted_and_blocks_until_abandoned(
        position, monkeypatch):
    """The reviewer's scenario: an open upload's accepted answer is lost and the platform lists only recorded
    deployments.  `reconcile` must not record ABORTED (nothing proves the upload failed) and every act stays
    blocked; only the operator's explicit abandonment closes it -- ABANDONED, not ABORTED: its GF1 and its
    code stay spent, and a late copy, never recordable, is never admitted."""
    directory, observer = position
    reference = ledger.status(directory)["opening_reference"]
    attempt = ledger.begin_deployment(directory, commit=ls.COMMIT, admission="OPEN", opening_reference=reference,
                                      forward_fix_ref=None, code=ls.CODE, vercel_project_sha256=ls.PLATFORM_PROJECT)
    assert _code(ledger.reconcile, directory, observer=observer) == "UPLOAD_OUTCOME_UNPROVEN"
    assert ledger.status(directory)["unresolved_operation"] == attempt["hash"]
    observer.alias = ls.DEPLOYMENT
    assert _code(ledger.begin_promotion, directory, ls.LIFT, ls.PUBLIC_HOST, serving=observer.alias) == \
        "OPERATION_UNRESOLVED"
    late = "dpl_" + "U" * 24
    observer.platform[late] = {"url": "https://late.invalid", "state": "READY", "files": ls.FILES,
                               "admission": "open", "code": ls.CODE}  # it appears: remove it before abandoning
    assert _code(ledger.reconcile, directory, observer=observer, abandon_upload=True) == "UNRECORDED_DEPLOYMENT"
    del observer.platform[late]
    outcome = ledger.reconcile(directory, observer=observer, abandon_upload=True)
    assert (outcome["of"], outcome["result"], outcome["resolved_by"]) == (attempt["hash"], "ABANDONED", "OPERATOR")
    assert ledger.status(directory)["unresolved_operation"] is None
    assert ls.CODE in ledger._summary(ledger.read_ledger(directory))["unproven_codes"]
    observer.platform[late] = {"url": "https://late.invalid", "state": "READY", "files": ls.FILES,
                               "admission": "open", "code": ls.CODE}  # another copy appears even later
    assert _gate(observer, monkeypatch, reference=reference, code=ls.CODE, deployment=late) == 503
    assert _code(ledger.admit_deployment, directory, late, observer=observer) == "NOT_AN_OPEN_DEPLOYMENT_OF_THE_REFERENCE"


def test_inv3_abandonment_is_only_for_an_upload(position):
    directory, observer = position
    observer.commit_fault = "lost_ack"
    assert _code(ledger.supersede, directory, observer=observer) == "OPERATION_UNRESOLVED"
    observer.commit_fault = None
    assert _code(ledger.reconcile, directory, observer=observer, abandon_upload=True) == "NOT_AN_UPLOAD"
    assert ledger.reconcile(directory, observer=observer)["result"] == "COMMITTED"  # read from its marker
    assert _code(ledger.reconcile, directory, observer=observer, abandon_upload=True) == "NOTHING_TO_RECONCILE"


def test_inv3_the_command_line_abandons_only_on_the_explicit_flag(position):
    import io

    directory, _observer = position
    reference = ledger.status(directory)["opening_reference"]
    ledger.begin_deployment(directory, commit=ls.COMMIT, admission="OPEN", opening_reference=reference,
                            forward_fix_ref=None, code=ls.CODE, vercel_project_sha256=ls.PLATFORM_PROJECT)
    head = ledger.status(directory)["head"]
    err = io.StringIO()  # parsed, then refused on the provider it must sweep first (none named here)
    assert ledger.main(["reconcile", "--ledger-dir", str(directory), "--expect-head", head, "--abandon-upload"],
                       out=io.StringIO(), err=err) == 1
    assert err.getvalue().strip() == "cutover-ledger: refused: PROVIDER_REQUIRED"
    assert ledger.status(directory)["unresolved_operation"] is not None
