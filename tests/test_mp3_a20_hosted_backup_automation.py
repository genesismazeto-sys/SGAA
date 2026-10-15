# coding: utf-8
"""MP-3 A20: the scheduled hosted backup (``app.backup.hosted_backup`` + the scheduler route).

The unit lanes run everywhere: the endpoint's auth/contract shapes, the due-ness decision against
the policy and the receipts, the object archive's seal/naming/refusals, and the pure retention
rules.  The real-PostgreSQL lanes need ``SGAA_PG_TEST_URL`` (REAL-PG EVIDENCE: ABSENT otherwise):
a full scheduled pass produces a verified snapshot and a sealed object set shipped to every
connected drive, records the receipt the page reads, prunes by the policy, and the manual route and
the scheduled pass never run together.  Each test names the defect it would catch.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import unittest.mock
import zipfile
from types import SimpleNamespace

import pytest
from werkzeug.test import Client

from app.backup import hosted_backup, object_sets, pg_posture
from app.storage import scheduler

SECRET = "c" * 40
SENTINEL = "SENTINEL-A20-EXCEPTION-0123456789"
PG_URL = os.environ.get("SGAA_PG_TEST_URL", "").strip()

needs_pg = pytest.mark.skipif(not PG_URL, reason="SGAA_PG_TEST_URL is not configured -- REAL-PG EVIDENCE: ABSENT")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


class _Conn:
    raw_connection = object()

    def commit(self):
        pass


@pytest.fixture
def front(monkeypatch):
    monkeypatch.setenv("CRON_SECRET", SECRET)
    monkeypatch.setattr(scheduler, "_app", None)
    return SimpleNamespace(client=Client(scheduler.application), headers={"Authorization": f"Bearer {SECRET}"},
                           path=scheduler.ROUTE_BACKUP)


@pytest.fixture
def env(monkeypatch):
    """The pass with every boundary scripted; ``_deliver``, the posture reads and the wake clock are fakes."""
    state = SimpleNamespace(deliveries=[], deliver_result=None, posture=None, raises=None,
                            unlocks=[], locks=[True], deliver_kwargs=None, policy_error=None,
                            wake_max=86400)
    monkeypatch.setattr(hosted_backup, "get_db_connection", lambda: _Conn())

    def lock(_conn):
        taken = state.locks.pop(0) if state.locks else True
        return "HOLDER" if taken else None

    monkeypatch.setattr(hosted_backup, "backup_lock", lock)
    monkeypatch.setattr(hosted_backup, "backup_unlock", lambda _conn, _holder: state.unlocks.append(1))
    monkeypatch.setattr(pg_posture, "read", lambda raw, now=None: state.posture)
    monkeypatch.setattr(hosted_backup, "note_wake", lambda raw, now: state.wake_max)

    def read_policy(raw, strict=False):
        # M3: the pass reads the policy strictly; the fake reproduces the same contract
        if state.policy_error == "invalid":
            raise pg_posture.PolicyError("POLICY_VALUE_INVALID")
        if state.policy_error == "unreadable":
            raise RuntimeError("policy unreadable")
        base = dict((state.posture or {}).get("policy") or pg_posture.default_policy())
        base.pop("invalid", None)
        return base

    monkeypatch.setattr(pg_posture, "read_policy", read_policy)

    def deliver(*, prune, with_objects, store=None, build_objects=None):
        state.deliveries.append({"prune": prune, "with_objects": with_objects})
        if state.raises is not None:
            raise state.raises
        return state.deliver_result

    monkeypatch.setattr(hosted_backup, "_deliver", deliver)
    return state


def _posture(*, cadence=24, object_days=7, latest_hours=None, latest_objects_hours=None, invalid=None, state="EMPTY"):
    now = datetime.datetime.now(datetime.timezone.utc)

    def at(hours):
        return None if hours is None else now - datetime.timedelta(hours=hours)

    return {
        "state": state, "cadence_hours": cadence,
        "policy": {"pg_database_cadence_hours": cadence, "pg_object_cadence_days": object_days,
                   "pg_retention_generations": 2, "pg_restore_test_days": 30,
                   "invalid": list(invalid or [])},
        "latest_generation_at": at(latest_hours), "latest_object_set_at": at(latest_objects_hours),
    }


def _delivered(*, sent=("google",), manifest="a" * 64, set_error=None, objects_failed=(),
               delivery_complete=True):
    return {"targets": list(sent), "sent": list(sent) if manifest is not None else None, "failed": [],
            "registers_failed": [], "objects_failed": list(objects_failed), "manifest": manifest,
            "delivery_complete": delivery_complete, "set_error": set_error, "object_set_name": None,
            "object_set_digest": None, "object_manifest_sha256": None,
            "object_files": {"google": "objects-1"}}


# ---------------------------------------------------------------------------
# the endpoint contract (the front the platform wakes)
# ---------------------------------------------------------------------------


def test_the_backup_route_is_disabled_without_the_secret(front, monkeypatch):
    monkeypatch.delenv("CRON_SECRET", raising=False)
    called = []
    monkeypatch.setattr(hosted_backup, "run_backup_pass", lambda **k: called.append(1) or {})
    assert front.client.get(front.path, headers=front.headers).status_code == 404
    assert called == []


@pytest.mark.parametrize("path", [scheduler.ROUTE_MIRROR + "/backup", scheduler.ROUTE_BACKUP + "/x", "/internal/scheduler/backups"])
def test_no_other_path_answers_the_backup_route(front, monkeypatch, path):
    called = []
    monkeypatch.setattr(hosted_backup, "run_backup_pass", lambda **k: called.append(1) or {})
    assert front.client.get(path, headers=front.headers).status_code == 404
    assert called == []


def test_a_wrong_bearer_is_a_401_before_the_pass(front, monkeypatch):
    called = []
    monkeypatch.setattr(hosted_backup, "run_backup_pass", lambda **k: called.append(1) or {})
    response = front.client.post(front.path, headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 401 and called == []
    assert SECRET not in response.get_data(as_text=True)


def test_other_methods_are_refused(front):
    assert front.client.put(front.path, headers=front.headers).status_code == 405


@pytest.mark.parametrize("code,status", [
    (hosted_backup.RESULT_OK, 200), (hosted_backup.RESULT_NOT_DUE, 200), (hosted_backup.RESULT_SKIPPED_BUSY, 200),
    (hosted_backup.RESULT_POLICY_INVALID, 503), (hosted_backup.RESULT_DATABASE_UNREADABLE, 503),
    (hosted_backup.RESULT_NO_DRIVE, 503), (hosted_backup.RESULT_SNAPSHOT_FAILED, 503),
    (hosted_backup.RESULT_SNAPSHOT_NOT_RECORDED, 503), ("SET_TOO_MANY_OBJECTS", 503),
])
def test_the_pass_result_maps_to_the_http_contract(front, monkeypatch, code, status):
    monkeypatch.setattr(hosted_backup, "run_backup_pass", lambda **k: {"result_code": code})
    response = front.client.post(front.path, headers=front.headers)
    assert response.status_code == status
    body = response.get_json()
    assert body["command"] == "backup" and body["result_code"] == code


def test_an_unexpected_failure_is_a_500_with_a_fixed_code(front, monkeypatch, caplog):
    monkeypatch.setattr(scheduler, "_build_app", lambda: __import__("flask").Flask("scheduler-a20"))

    def boom(**_k):
        raise RuntimeError(f"provider said {SENTINEL} {SECRET}")

    monkeypatch.setattr(hosted_backup, "run_backup_pass", boom)
    response = front.client.post(front.path, headers=front.headers)
    assert response.status_code == 500
    assert response.get_json() == {"command": "backup", "result_code": "SCHEDULER_JOB_FAILED"}
    assert SENTINEL not in response.get_data(as_text=True) and SENTINEL not in caplog.text


# ---------------------------------------------------------------------------
# the decision: policy-driven, cadence-agnostic, fail-closed
# ---------------------------------------------------------------------------


def test_nothing_due_is_a_no_op_that_never_delivers(env):
    env.wake_max = 900  # a 15-minute waker under a 24 h policy: threshold 23 h 45 min
    env.posture = _posture(latest_hours=1, latest_objects_hours=2)
    report = hosted_backup.run_backup_pass()
    assert report["result_code"] == hosted_backup.RESULT_NOT_DUE
    assert env.deliveries == [] and env.unlocks == [1]


def test_a_first_run_backs_up_database_and_objects(env):
    env.posture = _posture(latest_hours=None, latest_objects_hours=None)
    env.deliver_result = _delivered()
    report = hosted_backup.run_backup_pass()
    assert report["result_code"] == hosted_backup.RESULT_OK and report["action"] == "SNAPSHOT+OBJECTS"
    assert env.deliveries == [{"prune": True, "with_objects": True}]


def test_a_database_only_cadence_never_takes_the_object_set(env):
    env.posture = _posture(cadence=6, latest_hours=7, latest_objects_hours=1)  # objects fresh
    env.deliver_result = _delivered()
    report = hosted_backup.run_backup_pass()
    assert report["result_code"] == hosted_backup.RESULT_OK and report["action"] == "SNAPSHOT"
    assert env.deliveries == [{"prune": True, "with_objects": False}]


def test_the_object_cadence_alone_still_ships_a_fresh_database_copy(env):
    env.posture = _posture(cadence=24, object_days=1, latest_hours=1, latest_objects_hours=25)
    env.deliver_result = _delivered()
    report = hosted_backup.run_backup_pass()
    assert report["result_code"] == hosted_backup.RESULT_OK and report["action"] == "SNAPSHOT+OBJECTS"
    assert env.deliveries == [{"prune": True, "with_objects": True}]


def test_a_wake_runs_when_the_deadline_could_not_be_met_by_the_next_expected_wake(env):
    """M4/A6/A7: the decision uses the maximum demonstrated inter-wake spacing; a wake at exactly
    `cadence - wake_max` runs -- the next wake could arrive at that spacing and miss the deadline
    (the old guard inside the threshold skipped it, and a delayed wake then stretched the gap)."""
    env.deliver_result = _delivered()
    env.wake_max = 6 * 3600  # a 6-hourly waker under a 24 h policy: threshold 18 h
    env.posture = _posture(latest_hours=17, latest_objects_hours=17)
    assert hosted_backup.run_backup_pass()["result_code"] == hosted_backup.RESULT_NOT_DUE
    env.posture = _posture(latest_hours=18, latest_objects_hours=18)  # the edge: runs
    assert hosted_backup.run_backup_pass()["result_code"] == hosted_backup.RESULT_OK
    env.posture = _posture(latest_hours=19, latest_objects_hours=19)
    assert hosted_backup.run_backup_pass()["result_code"] == hosted_backup.RESULT_OK
    # a daily waker: the deadline could never be met by the next daily wake, so every wake runs
    env.wake_max = 86400
    env.posture = _posture(latest_hours=1, latest_objects_hours=1)
    assert hosted_backup.run_backup_pass()["result_code"] == hosted_backup.RESULT_OK


def test_a_47_hour_gap_cannot_happen_under_a_24_hour_policy(env):
    """M4: consecutive daily wakes keep running (~23 h gaps, never ~47 h), and a generation whose
    phase sits later than the wake -- a manual at 07:00 vs a 04:47 cron -- runs at that same wake."""
    env.deliver_result = _delivered()
    env.posture = _posture(latest_hours=None, latest_objects_hours=None)
    assert hosted_backup.run_backup_pass()["result_code"] == hosted_backup.RESULT_OK
    for hours in (23, 46):  # each wake arrives 1 h before the nominal cadence
        env.posture = _posture(latest_hours=hours, latest_objects_hours=hours)
        assert hosted_backup.run_backup_pass()["result_code"] == hosted_backup.RESULT_OK
    # the reviewer's sequence: a manual generation 21 h 47 min before the daily wake
    env.posture = _posture(latest_hours=21.78, latest_objects_hours=21.78)
    assert hosted_backup.run_backup_pass()["result_code"] == hosted_backup.RESULT_OK


def test_a_one_hour_policy_runs_at_the_last_wake_before_the_deadline(env):
    """M4/A6: with a 15-minute waker at a 1 h policy the threshold is 45 min and the edge wake runs
    (the next expected wake could be late), so runs are 45-60 min apart -- never past the cadence,
    never per wake."""
    env.deliver_result = _delivered()
    env.wake_max = 900
    env.posture = _posture(cadence=1, latest_hours=0.67, latest_objects_hours=1)  # 40 min: not due
    assert hosted_backup.run_backup_pass()["result_code"] == hosted_backup.RESULT_NOT_DUE
    env.posture = _posture(cadence=1, latest_hours=0.75, latest_objects_hours=1)  # 45 min: the edge
    assert hosted_backup.run_backup_pass()["result_code"] == hosted_backup.RESULT_OK
    env.posture = _posture(cadence=1, latest_hours=0.84, latest_objects_hours=1)  # ~50 min: due
    assert hosted_backup.run_backup_pass()["result_code"] == hosted_backup.RESULT_OK


def test_a_dense_waker_never_lets_a_gap_exceed_the_cadence(env):
    """A7/RPO: over a week of adversarial wakes -- the daily cron at 04:00/04:59 alternating plus
    6-hourly trigger wakes -- every gap between consecutive generations stays at or under the 24 h
    cadence.  The retained window and the decision are the real ones; the ladder of D4 bounds the
    RPO (a lone daily cron cannot: its spacing is the bound -- see the real-PG lanes)."""
    env.deliver_result = _delivered()
    base = datetime.datetime(2026, 10, 1, tzinfo=datetime.timezone.utc)
    wakes = []
    for day in range(6):
        wakes.append(base + datetime.timedelta(days=day, hours=4, minutes=59 if day % 2 else 0))
        for hour in (6, 12, 18):
            wakes.append(base + datetime.timedelta(days=day, hours=hour))
        if day < 5:
            wakes.append(base + datetime.timedelta(days=day + 1, hours=0))
    wakes = sorted(set(wakes))
    history = []
    last_generation = None
    previous_wake = None
    gaps = []
    for wake in wakes:
        interval = None if previous_wake is None else int((wake - previous_wake).total_seconds())
        if interval is not None and interval < hosted_backup.WAKE_MIN_SECONDS:
            interval = None  # a duplicate delivery is not a spacing
        history = hosted_backup._next_history(history, interval)
        env.wake_max = hosted_backup._wake_max(history)
        age = None if last_generation is None else (wake - last_generation).total_seconds() / 3600.0
        object_age = None if last_generation is None else (wake - wakes[0]).total_seconds() / 3600.0
        env.posture = _posture(latest_hours=age, latest_objects_hours=object_age)
        if hosted_backup.run_backup_pass()["result_code"] == hosted_backup.RESULT_OK:
            if last_generation is not None:
                gaps.append(wake - last_generation)
            last_generation = wake
        previous_wake = wake
    assert gaps and all(gap <= datetime.timedelta(hours=24) for gap in gaps)
    assert max(gaps) >= datetime.timedelta(hours=18)  # runs near the deadline, not on every wake


def test_the_retained_window_rolls_a_long_spacing_out():
    """A7: the window keeps the last `WAKE_HISTORY` spacings -- a transition (a source enabled or
    disabled) rolls out of it, and a duplicate never enters it."""
    history = [24 * 3600]
    for _ in range(hosted_backup.WAKE_HISTORY):
        history = hosted_backup._next_history(history, 6 * 3600)
    assert len(history) == hosted_backup.WAKE_HISTORY
    assert hosted_backup._wake_max(history) == 6 * 3600
    assert hosted_backup._next_history(history, None) == history  # a duplicate adds nothing
    assert hosted_backup._wake_max([]) == hosted_backup.DEFAULT_WAKE_SECONDS
    assert hosted_backup._next_history([], None) == []


def _simulate_gaps(wakes, cadence_hours, *, manual_at=None):
    """Drive the REAL A7 helpers over a wake schedule; return the gaps between consecutive runs.

    A wake whose run is interrupted or fails never advances the clock (M1/A3) and is covered by the
    real-PostgreSQL partial-delivery lanes; this sweep models the scheduling contract itself.
    """
    generation = manual_at
    history = []
    recorded = None
    gaps = []
    for wake in wakes:
        interval = None if recorded is None else int((wake - recorded).total_seconds())
        if interval is not None and interval < hosted_backup.WAKE_MIN_SECONDS:
            interval = None
        elif interval is not None:
            interval = min(interval, hosted_backup.WAKE_MAX_SECONDS)
        history = hosted_backup._next_history(history, interval)
        recorded = wake
        wake_max = hosted_backup._wake_max(history)
        age = None if generation is None else (wake - generation).total_seconds()
        if age is None or hosted_backup._due_seconds(age, cadence_hours * 3600, wake_max):
            if generation is not None:
                gaps.append(wake - generation)
            generation = wake
    return gaps


def test_the_scheduling_contract_holds_across_adversarial_topologies():
    """A7 adversarial sweep: mixed daily + sub-daily sources, duplicates and a manual at an
    arbitrary time, over every cadence 1-24 h and several trigger periods.  The gap between
    consecutive generations never exceeds the cadence (exact) or the cadence plus the jitter record
    (jittered), and a waker at or under a quarter of the cadence never runs per wake.
    """
    import random

    base = datetime.datetime(2026, 10, 1, tzinfo=datetime.timezone.utc)
    for cadence in (1, 2, 4, 6, 12, 24):
        for period_minutes in (15, 30, 60, 180, 360):
            if period_minutes * 60 > cadence * 3600:
                continue  # a waker sparser than the cadence cannot guarantee it (the documented mode)
            period = datetime.timedelta(minutes=period_minutes)
            wakes = []
            moment = base
            while moment < base + datetime.timedelta(days=3):
                wakes.append(moment)
                moment += period
            for day in range(3):
                wakes.append(base + datetime.timedelta(days=day, hours=4, minutes=47))  # the daily cron
            wakes.append(base + datetime.timedelta(days=1, hours=6, seconds=30))  # a duplicate delivery
            wakes.sort()
            manual = base + datetime.timedelta(hours=10, minutes=13)
            exact = _simulate_gaps(wakes, cadence, manual_at=manual)
            assert exact and max(exact) <= datetime.timedelta(hours=cadence)
            if period_minutes * 4 <= cadence * 60:  # the recommended density: never per wake
                assert len(exact) <= len(wakes) // 2 + 1
            rng = random.Random(cadence * 1000 + period_minutes)
            jittered = sorted(w + datetime.timedelta(seconds=rng.randint(-60, 60)) for w in wakes)
            jittered_gaps = _simulate_gaps(jittered, cadence, manual_at=manual)
            assert jittered_gaps and max(jittered_gaps) <= datetime.timedelta(hours=cadence, minutes=2)


def test_an_invalid_policy_refuses_and_delivers_nothing(env):
    """M3: the strict read refuses a partial or invalid stored policy; nothing runs."""
    env.policy_error = "invalid"
    env.posture = _posture(latest_hours=None)
    report = hosted_backup.run_backup_pass()
    assert report["result_code"] == hosted_backup.RESULT_POLICY_INVALID
    assert env.deliveries == []


def test_an_unreadable_policy_is_never_replaced_with_defaults(env):
    """M3: a policy that cannot be read refuses the run instead of silently using the defaults."""
    env.policy_error = "unreadable"
    env.posture = _posture(latest_hours=None)
    report = hosted_backup.run_backup_pass()
    assert report["result_code"] == hosted_backup.RESULT_POLICY_UNREADABLE
    assert env.deliveries == []


def test_an_unreadable_posture_refuses_and_delivers_nothing(env):
    env.posture = {"state": "UNREADABLE"}
    report = hosted_backup.run_backup_pass()
    assert report["result_code"] == hosted_backup.RESULT_DATABASE_UNREADABLE
    assert env.deliveries == []


def test_the_lock_is_released_even_when_delivery_raises(env):
    env.posture = _posture(latest_hours=None, latest_objects_hours=None)
    env.raises = RuntimeError("boom")
    with pytest.raises(RuntimeError):
        hosted_backup.run_backup_pass()
    assert env.unlocks == [1]  # the next wake can run


def test_a_busy_lock_reports_skipped_busy_without_touching_the_database(env):
    env.locks = [False]
    report = hosted_backup.run_backup_pass()
    assert report["result_code"] == hosted_backup.RESULT_SKIPPED_BUSY
    assert env.deliveries == [] and env.unlocks == []


@pytest.mark.parametrize("result,code", [
    (dict(_delivered(), manifest=None), hosted_backup.RESULT_SNAPSHOT_NOT_RECORDED),
    (dict(_delivered(), sent=[]), hosted_backup.RESULT_NO_DRIVE),
    (dict(_delivered(), sent=None), hosted_backup.RESULT_SNAPSHOT_FAILED),
    (dict(_delivered(), delivery_complete=False, failed=["OneDrive"]),
     hosted_backup.RESULT_DELIVERY_INCOMPLETE),
])
def test_partial_delivery_failures_map_to_their_codes(env, result, code):
    env.posture = _posture(latest_hours=None, latest_objects_hours=None)
    env.deliver_result = result
    report = hosted_backup.run_backup_pass()
    assert report["result_code"] == code


def test_a_failed_object_set_publishes_nothing_and_names_the_code(env):
    env.posture = _posture(latest_hours=None, latest_objects_hours=None)
    env.deliver_result = _delivered(set_error="SET_TOO_MANY_OBJECTS")
    report = hosted_backup.run_backup_pass()
    assert report["result_code"] == "SET_TOO_MANY_OBJECTS" and report["action"] == "NONE"


# ---------------------------------------------------------------------------
# the object archive: sealed, named, refused loudly when it cannot be built
# ---------------------------------------------------------------------------


def _sealed_set(tmp_path, *, result_code="OK", objects_digest="ab" * 32):
    """A faithful stand-in of ``object_backup.backup``'s success artefact."""
    from pathlib import Path as _Path

    def fake_backup(conn, store, destination, *, label="", repo_root=None):
        shard = _Path(destination, "objects", "ab")
        shard.mkdir(parents=True, exist_ok=False)
        _Path(destination, "MANIFEST.json").write_bytes(json.dumps({"format": 1}).encode())
        (shard / "abcd").write_bytes(b"object-bytes")
        return SimpleNamespace(result_code=result_code, objects_digest=objects_digest)

    return fake_backup, tmp_path


def test_the_object_archive_is_named_for_this_installation_and_sealed(monkeypatch, tmp_path):
    from app.storage import object_backup

    fake_backup, _ = _sealed_set(tmp_path)
    monkeypatch.setattr(object_backup, "backup", fake_backup)
    built = object_sets.build_objects_archive(
        None, str(tmp_path), {"generation_at": "2026-10-13T10:00:00Z", "source_identity_sha256": "a" * 64},
        store=object())
    assert built["code"] is None
    name = os.path.basename(built["archive"])
    assert hosted_backup.OBJECTS_ARCHIVE_NAME.fullmatch(name), name
    assert name.startswith("sgaa-pg-objetos-20261013T100000Z-aaaaaaaaaaaa")
    assert built["set_name"] == "20261013T100000Z-hosted"
    assert built["report"].objects_digest == "ab" * 32
    assert built["manifest_sha256"] == hashlib.sha256(b'{"format": 1}').hexdigest()
    with zipfile.ZipFile(built["archive"]) as archive:
        assert set(archive.namelist()) >= {"MANIFEST.json", "objects/ab/abcd"}


@pytest.mark.parametrize("code", ["TOO_MANY_OBJECTS", "INSUFFICIENT_SPACE", "UNREADABLE_OBJECTS"])
def test_a_set_that_does_not_verify_is_never_shipped(monkeypatch, tmp_path, code):
    from app.storage import object_backup

    fake_backup, _ = _sealed_set(tmp_path, result_code=code)
    monkeypatch.setattr(object_backup, "backup", fake_backup)
    built = object_sets.build_objects_archive(
        None, str(tmp_path), {"generation_at": "2026-10-13T10:00:00Z", "source_identity_sha256": "a" * 64},
        store=object())
    assert built["archive"] is None and built["code"] == f"SET_{code}"


def test_an_unreachable_store_is_a_fixed_code_not_an_exception(monkeypatch, tmp_path):
    from app.storage import object_backup

    def broken_store():
        raise RuntimeError("no store")

    monkeypatch.setattr(object_sets, "_canonical_store", broken_store)
    built = object_sets.build_objects_archive(
        None, str(tmp_path), {"generation_at": "2026-10-13T10:00:00Z", "source_identity_sha256": "a" * 64})
    assert built["archive"] is None and built["code"] == "SET_RUNTIMEERROR"


# ---------------------------------------------------------------------------
# the real delivery: a set that reaches no drive is never claimed as protection
# ---------------------------------------------------------------------------


def _deliver_env(monkeypatch, tmp_path, *, upload_objects_ok=True, providers=("google",), fail=()):
    """The real ``_deliver`` with every boundary scripted (no database, no provider)."""
    from pathlib import Path

    from app import cloud_drives
    from app.backup import pg_snapshot

    calls = {"uploads": [], "published": [], "deleted": []}
    monkeypatch.setattr(hosted_backup, "get_db_connection", lambda: _Conn())
    monkeypatch.setattr(hosted_backup, "active_cloud_account", lambda conn, provider: provider in providers)
    monkeypatch.setattr(hosted_backup, "cloud_drive_folder_setting",
                        lambda conn, provider: {"folder_id": "F", "drive_id": ""})
    monkeypatch.setattr(hosted_backup, "_save_drive_config", lambda conn, updates: None)
    monkeypatch.setattr(hosted_backup.pg_posture, "read_policy",
                        lambda raw, strict=False: {"pg_database_cadence_hours": 24, "pg_object_cadence_days": 7,
                                                   "pg_retention_generations": 2, "pg_restore_test_days": 30})
    monkeypatch.setattr(hosted_backup.pg_posture, "publish",
                        lambda raw, entries, **k: calls["published"].extend(entries) or {"published": 1})

    def create(directory, **_kwargs):
        db, csv_file = Path(directory) / "snap.db", Path(directory) / "regs.zip"
        db.write_bytes(b"db")
        csv_file.write_bytes(b"zip")
        return {"path": str(db), "file_name": "sgaa-pg-snapshot-20261013T100000Z-aaaaaaaaaaaa-00000001.db",
                "registers_path": str(csv_file),
                "registers_file_name": "sgaa-registros-20261013T100000Z-aaaaaaaaaaaa-00000001.zip",
                "sha256": "e" * 64, "generation_at": "2026-10-13T10:00:00Z",
                "source_identity_sha256": "a" * 64}

    monkeypatch.setattr(pg_snapshot, "create", create)

    def upload(conn, provider, *, zip_path, file_name, folder_name, folder_id=None, drive_id=None, replace=True):
        assert replace is False
        calls["uploads"].append((provider, file_name))
        if provider in fail or (file_name.startswith(hosted_backup.OBJECTS_ARCHIVE_PREFIX) and not upload_objects_ok):
            raise RuntimeError("upload refused")
        return {"file_id": f"{provider}-{len(calls['uploads'])}", "folder_id": folder_id or "default"}

    monkeypatch.setattr(hosted_backup._cloud_connections, "upload_backup_zip", upload)
    monkeypatch.setattr(hosted_backup._cloud_connections, "get_authenticated_access_token",
                        lambda conn, provider: ("tok", "x"))
    monkeypatch.setattr(cloud_drives, "google_list_folder_files", lambda token, folder, prefix: [])
    monkeypatch.setattr(cloud_drives, "google_delete_file", lambda token, file_id: calls["deleted"].append(file_id))
    return calls


def _builder(tmp_path, code=None):
    def build(conn, scratch, snapshot, *, store=None):
        if code is not None:
            return {"archive": None, "report": None, "manifest_sha256": None, "set_name": None, "code": code}
        archive = tmp_path / "sgaa-pg-objetos-20261013T100000Z-aaaaaaaaaaaa-0000000000000001.zip"
        archive.write_bytes(b"zip")
        return {"archive": str(archive), "report": SimpleNamespace(objects_digest="ab" * 32),
                "manifest_sha256": "cd" * 32, "set_name": "20261013T100000Z-hosted", "code": None}

    return build


def test_a_set_that_cannot_reach_a_drive_is_never_claimed_as_object_protection(monkeypatch, tmp_path):
    calls = _deliver_env(monkeypatch, tmp_path, upload_objects_ok=False)
    result = hosted_backup._deliver(prune=False, with_objects=True, build_objects=_builder(tmp_path))
    assert result["object_files"] == {} and result["objects_failed"] == ["Google Drive"]
    [receipt] = calls["published"]
    assert receipt["object_set_name"] == "NONE" and "object_files" not in receipt
    assert result["manifest"] == "e" * 64  # the database copy is still recorded (its own layer)


def test_a_partial_delivery_is_recorded_incomplete_and_owns_its_files(monkeypatch, tmp_path):
    """M1: one connected drive missing the snapshot -> the receipt is recorded with complete=False
    (so retention owns the files it delivered) and never counts as protection."""
    calls = _deliver_env(monkeypatch, tmp_path, providers=("google", "onedrive"), fail=("onedrive",))
    result = hosted_backup._deliver(prune=False, with_objects=False)
    assert result["delivery_complete"] is False
    assert result["sent"] == ["google"] and result["failed"] == ["OneDrive"]
    [receipt] = calls["published"]
    assert receipt["complete"] is False and receipt["destinations"] == ["google"]
    assert result["manifest"] == "e" * 64  # recorded (owns its files) but marked incomplete


def test_only_complete_receipts_advance_the_clocks():
    """M1 read side: the page and the schedule count complete receipts only."""
    from app import hosting as _hosting

    now = datetime.datetime.now(datetime.timezone.utc)
    complete_at = now - datetime.timedelta(hours=50)

    def receipt(hours_ago, complete):
        moment = now - datetime.timedelta(hours=hours_ago)
        at = moment.strftime("%Y-%m-%dT%H:%M:%SZ")
        body = {"type": "backup", "kind": "SNAPSHOT", "at": at, "generation_at": at,
                "manifest_sha256": "%064x" % (int(hours_ago) + 1), "dump_sha256": "d" * 64,
                "source_identity_sha256": "a" * 64, "object_set_name": "NONE", "object_set_digest": "NONE",
                "object_manifest_sha256": "NONE", "off_platform": "VERIFIED", "provenance": "HOSTED_RUN",
                "run_seconds": 1, "complete": complete}
        return dict(body, hash=_hosting.ledger_entry_hash(body))

    rows = [(json.dumps(receipt(50, True), sort_keys=True), None),
            (json.dumps(receipt(1, False), sort_keys=True), None)]
    posture = pg_posture.summarize(rows, identity="a" * 64, now=now)
    assert abs((posture["latest_generation_at"] - complete_at).total_seconds()) < 5
    assert posture["database_status"] == "LATE"  # 50 h > 36 h: the fresh partial did not refresh it
    assert posture["recent"][0]["complete"] is False and posture["recent"][1]["complete"] is True


def test_a_partial_delivery_retries_until_complete(monkeypatch, tmp_path):
    """M1: the pass refuses the incomplete wake (503 code) while the receipt records the truth."""
    calls = _deliver_env(monkeypatch, tmp_path, upload_objects_ok=False)
    monkeypatch.setattr(hosted_backup, "backup_lock", lambda conn: "H")
    monkeypatch.setattr(hosted_backup, "backup_unlock", lambda conn, holder: None)
    monkeypatch.setattr(hosted_backup, "note_wake", lambda raw, now: hosted_backup.DEFAULT_WAKE_SECONDS)
    monkeypatch.setattr(hosted_backup.pg_posture, "read",
                        lambda raw, now=None: _posture(latest_hours=None, latest_objects_hours=None))
    report = hosted_backup.run_backup_pass(build_objects=_builder(tmp_path))
    assert report["result_code"] == hosted_backup.RESULT_DELIVERY_INCOMPLETE
    assert report["objects_failed"] == ["Google Drive"]
    [receipt] = calls["published"]
    assert receipt["complete"] is False and receipt["object_set_name"] == "NONE"  # set not claimed


def test_a_folder_setting_failure_is_a_partial_delivery_not_a_crash(monkeypatch, tmp_path):
    calls = _deliver_env(monkeypatch, tmp_path, providers=("google", "onedrive"))
    monkeypatch.setattr(hosted_backup, "cloud_drive_folder_setting",
                        lambda conn, provider: (_ for _ in ()).throw(RuntimeError("db read failed"))
                        if provider == "onedrive" else {"folder_id": "F", "drive_id": ""})
    result = hosted_backup._deliver(prune=False, with_objects=False)
    assert result["delivery_complete"] is False and result["failed"] == ["OneDrive"]
    assert calls["published"] and calls["published"][0]["complete"] is False


def test_a_refused_object_set_stops_the_pass_before_any_upload_or_receipt(monkeypatch, tmp_path):
    calls = _deliver_env(monkeypatch, tmp_path)
    result = hosted_backup._deliver(prune=False, with_objects=True,
                                    build_objects=_builder(tmp_path, code="SET_TOO_MANY_OBJECTS"))
    assert result["set_error"] == "SET_TOO_MANY_OBJECTS"
    assert calls["uploads"] == [] and calls["published"] == []


def test_no_connected_drive_is_no_drive_not_a_failed_snapshot(monkeypatch, tmp_path):
    calls = _deliver_env(monkeypatch, tmp_path)
    monkeypatch.setattr(hosted_backup, "active_cloud_account", lambda conn, provider: None)
    result = hosted_backup._deliver(prune=False, with_objects=False)
    assert result["targets"] == [] and result["sent"] == [] and result["manifest"] is None
    assert calls["uploads"] == []


# ---------------------------------------------------------------------------
# retention: the object archives are a third kind, and only owned files are deleted
# ---------------------------------------------------------------------------


def _prune_fakes(monkeypatch, *, owned, listed, deleted, complete=None):
    from app import cloud_drives

    complete_set = set(owned if complete is None else complete)

    def owned_files(raw, complete=None):
        if complete is None:
            return set(owned)
        return set(complete_set) if complete else set(owned) - complete_set

    monkeypatch.setattr(hosted_backup.pg_posture, "owned_files", owned_files)
    monkeypatch.setattr(hosted_backup._cloud_connections, "get_authenticated_access_token",
                        lambda conn, provider: ("tok", "x"))
    monkeypatch.setattr(cloud_drives, "google_list_folder_files", lambda token, folder, prefix: [
        f for f in listed if str(f["name"]).startswith(prefix)])
    monkeypatch.setattr(cloud_drives, "google_delete_file", lambda token, file_id: deleted.append(file_id))


def test_complete_generations_and_partial_runs_rotate_separately(monkeypatch):
    """M1 retention: a partial pressure never deletes a complete generation; each class keeps N."""
    listed = [
        {"id": "c1", "name": "sgaa-pg-snapshot-20261001T000000Z.db"},
        {"id": "c2", "name": "sgaa-pg-snapshot-20261002T000000Z.db"},
        {"id": "c3", "name": "sgaa-pg-snapshot-20261003T000000Z.db"},
        {"id": "p1", "name": "sgaa-pg-snapshot-20261004T000000Z.db"},
        {"id": "p2", "name": "sgaa-pg-snapshot-20261005T000000Z.db"},
        {"id": "p3", "name": "sgaa-pg-snapshot-20261006T000000Z.db"},
    ]
    deleted = []
    _prune_fakes(monkeypatch,
                 owned={("google", "", name) for name in ("c1", "c2", "c3", "p1", "p2", "p3")},
                 listed=listed, deleted=deleted,
                 complete={("google", "", name) for name in ("c1", "c2", "c3")})
    hosted_backup.prune_owned(_Conn(), object(), ["google"], {"google": ("F", None, "")}, 2,
                              registers_skip=[])
    assert sorted(deleted) == ["c1", "p1"]


def test_owned_object_archives_are_pruned_by_the_policy_to_the_newest_keep(monkeypatch):
    listed = [
        {"id": "obj-1", "name": "sgaa-pg-objetos-20261001T000000Z-aaaaaaaaaaaa-0000000000000001.zip"},
        {"id": "obj-2", "name": "sgaa-pg-objetos-20261011T000000Z-aaaaaaaaaaaa-0000000000000002.zip"},
        {"id": "obj-3", "name": "sgaa-pg-objetos-20261012T000000Z-aaaaaaaaaaaa-0000000000000003.zip"},
        {"id": "foreign", "name": "sgaa-pg-objetos-20261010T000000Z-aaaaaaaaaaaa-0000000000000004.zip"},
        {"id": "legacy", "name": "sgaa_backup_legacy.db"},
    ]
    owned = {("google", "", "obj-1"), ("google", "", "obj-2"), ("google", "", "obj-3")}
    deleted = []
    _prune_fakes(monkeypatch, owned=owned, listed=listed, deleted=deleted)
    hosted_backup.prune_owned(_Conn(), object(), ["google"], {"google": ("F", None, "")}, 2, registers_skip=[])
    # keep the newest two owned archives; the oldest owned goes, the foreign same-shaped file never does
    assert deleted == ["obj-1"]


def test_no_owned_object_archive_means_nothing_is_deleted(monkeypatch):
    from app import cloud_drives

    deleted = []
    monkeypatch.setattr(hosted_backup.pg_posture, "owned_files", lambda raw: {("google", "", "snap-1")})
    monkeypatch.setattr(hosted_backup._cloud_connections, "get_authenticated_access_token",
                        lambda conn, provider: ("tok", "x"))
    monkeypatch.setattr(cloud_drives, "google_list_folder_files",
                        lambda token, folder, prefix: [
                            {"id": "obj-9", "name": "sgaa-pg-objetos-20261001T000000Z-aaaaaaaaaaaa-0000000000000009.zip"}]
                        if prefix == hosted_backup.OBJECTS_ARCHIVE_PREFIX else [])
    monkeypatch.setattr(cloud_drives, "google_delete_file", lambda token, file_id: deleted.append(file_id))
    hosted_backup.prune_owned(_Conn(), object(), ["google"], {"google": ("F", None, "")}, 2, registers_skip=[])
    assert deleted == []  # the object-shaped file is not owned by this database's receipts


# ---------------------------------------------------------------------------
# receipts: the object files are owned, shown and intact
# ---------------------------------------------------------------------------


def test_the_receipt_carries_the_object_files_and_the_ownership_reads_them(monkeypatch):
    from app import hosting

    source = {"database": "db", "user": "u", "login_user": "u", "host": "h", "port": "5432",
              "system_identifier": "1"}
    identity = hosting.source_identity_sha256(source)
    receipt = pg_posture.run_record(
        generation_at="2026-10-13T10:00:00Z", manifest_sha256="a" * 64, dump_sha256="b" * 64,
        source_identity_sha256=identity, object_set_name="20261013T100000Z-hosted",
        object_set_digest="d" * 64, object_manifest_sha256="e" * 64, run_seconds=1, at="2026-10-13T10:00:00Z",
        kind=pg_posture.SNAPSHOT_KIND, provenance=pg_posture.HOSTED_PROVENANCE, destinations=("google",),
        files={"google": "snap-1"}, exports={"google": "csv-1"}, drives={},
        object_files={"google": "obj-1"})
    assert receipt["object_files"] == {"google": "obj-1"}
    assert pg_posture._intact(receipt)
    # the ownership read (retention's only deletion source) picks the object files up too
    monkeypatch.setattr(hosting, "database_source", lambda conn: dict(source))
    rows = [(json.dumps(receipt, sort_keys=True), None)]
    owned = pg_posture.owned_files(_FakeRaw(rows))
    assert ("google", "", "obj-1") in owned and ("google", "", "snap-1") in owned


class _FakeCursor:
    def __init__(self, raw):
        self._raw = raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._raw.last_sql = sql
        return self

    def fetchall(self):
        return list(self._raw.rows)

    def fetchone(self):
        return (True,) if self._raw.last_sql == pg_posture.EXISTS_SQL else None


class _FakeRaw:
    """The minimum psycopg surface ``pg_posture.owned_files`` reads (rows only, no server)."""

    def __init__(self, rows):
        self.rows, self.last_sql = rows, None
        self.info = SimpleNamespace(user="u", host="h", port=5432, dbname="db")

    def transaction(self):
        import contextlib

        return contextlib.nullcontext()

    def cursor(self, row_factory=None):
        return _FakeCursor(self)


# ---------------------------------------------------------------------------
# real PostgreSQL: the full scheduled pass, end to end
# ---------------------------------------------------------------------------


from tests.mp2_pg_support import Registry, adapter, raw_connection, seed_admin  # noqa: E402
from tests.storage_mp1_support import BUCKET, insert_object  # noqa: E402
from tests.canonical_store_fake import InMemoryObjectStore  # noqa: E402

PDF = b"%PDF-1.4\n" + b"0123456789abcdef" * 32


@pytest.fixture(scope="module")
def pg_registry():
    if not PG_URL:
        pytest.skip("SGAA_PG_TEST_URL is not configured")
    registry = Registry("a20host")
    try:
        registry.provision_template()
        yield registry
    finally:
        assert registry.close() == 0


class _FakeDrive:
    """A minimal drive double: uploads land in a per-provider listing; deletes write through it."""

    def __init__(self):
        self.remote = {"google": [], "onedrive": []}
        self.deleted = []
        self.fail_for = set()  # providers whose next upload raises (M1 partial-delivery lanes)

    def upload(self, conn, provider, *, zip_path, file_name, folder_name, folder_id=None, drive_id=None, replace=True):
        assert replace is False  # never replaces an existing file (A19 R8 / A20)
        assert os.path.exists(zip_path)
        if provider in self.fail_for:
            raise RuntimeError("upload refused")
        file_id = f"{provider}-{len(self.remote[provider]) + 1}"
        self.remote[provider].append({"id": file_id, "name": file_name})
        return {"file_id": file_id, "folder_id": folder_id or "default-folder",
                "drive_id": "drive-1" if provider == "onedrive" else ""}


@pytest.fixture
def production(tmp_path, pg_registry, monkeypatch):
    """One disposable PostgreSQL database served by the real application, with scripted drives."""
    from app import cloud_drives
    from app.db import close_db_connection
    import main

    name, url = pg_registry.create(template=pg_registry.template)
    patcher = pytest.MonkeyPatch()
    patcher.setattr("app.db.DATABASE_URL", url)
    patcher.setitem(main.app.config, "TESTING", True)
    conn = adapter(url)
    try:
        seed_admin(conn)
        ids = []
        store = InMemoryObjectStore()
        for index, content in enumerate((PDF, PDF + b"2")):
            key = f"comprovantes/2026/10/a20-{index}-{'x' * 30}"
            ids.append(insert_object(conn, key=key, content=content, mime="application/pdf"))
            store.objects[(BUCKET, key)] = (content, "application/pdf")
        conn.commit()
    finally:
        conn.close()

    drive = _FakeDrive()
    monkeypatch.setattr(hosted_backup, "active_cloud_account",
                        lambda c, provider: {"account_email": "x@example.invalid"} if provider == "google" else None)
    monkeypatch.setattr(hosted_backup, "cloud_drive_folder_setting",
                        lambda c, provider: {"folder_id": "chosen-folder", "drive_id": ""})
    # the scheduler service resolves the canonical store from its environment; in the lane it is the
    # in-memory double (the same seam the object-backup suites use)
    monkeypatch.setattr(object_sets, "_canonical_store", lambda: store)
    monkeypatch.setattr(hosted_backup._cloud_connections, "upload_backup_zip", drive.upload)
    monkeypatch.setattr(hosted_backup._cloud_connections, "get_authenticated_access_token",
                        lambda c, provider: ("tok", "x"))
    monkeypatch.setattr(cloud_drives, "google_list_folder_files",
                        lambda token, folder, prefix: [f for f in drive.remote["google"] if f["name"].startswith(prefix)])

    def _delete(token, file_id):
        # mirror the provider: a deleted file leaves the listing
        drive.deleted.append(file_id)
        drive.remote["google"] = [f for f in drive.remote["google"] if f["id"] != file_id]

    monkeypatch.setattr(cloud_drives, "google_delete_file", _delete)
    monkeypatch.setattr(cloud_drives, "onedrive_list_folder_children",
                        lambda token, folder_id, drive_id, folder_path: [])
    monkeypatch.setattr(cloud_drives, "onedrive_delete_item",
                        lambda token, item_id, drive_id=None: drive.deleted.append(item_id))
    monkeypatch.setattr(scheduler, "_app", None)
    monkeypatch.setattr(scheduler, "_build_app", lambda: main.app)
    try:
        yield SimpleNamespace(url=url, app=main.app, drive=drive, store=store, ids=ids, registry=pg_registry)
    finally:
        with main.app.app_context():
            close_db_connection(None)
        patcher.undo()


def _set_policy(env, **values):
    conn = adapter(env.url)
    try:
        for key, value in values.items():
            conn.execute("INSERT INTO configuracoes_backup (chave, valor, atualizado_em) VALUES (?, ?, '2026-10-13 00:00:00')"
                         " ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor", (f"pg_{key}", str(value)))
        conn.commit()
    finally:
        conn.close()


def _posture_of(env):
    raw = raw_connection(env.url, autocommit=True)
    try:
        return pg_posture.read(raw)
    finally:
        raw.close()


def _public_counts(url):
    conn = raw_connection(url, autocommit=True)
    try:
        tables = [row[0] for row in conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename").fetchall()]
        return {table: conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0] for table in tables}
    finally:
        conn.close()


@needs_pg
def test_a_scheduled_wake_ships_a_verified_snapshot_and_a_sealed_set_and_records_the_receipt(production):
    """AC2/AC3: the full automatic pass on real PostgreSQL, with the page's own reading."""
    env = production
    _set_policy(env, database_cadence_hours=24, object_cadence_days=7, retention_generations=2,
                restore_test_days=30)
    before = _public_counts(env.url)
    with env.app.app_context():
        report = hosted_backup.run_backup_pass(store=env.store, build_objects=object_sets.build_objects_archive)
    assert report["result_code"] == hosted_backup.RESULT_OK
    assert report["action"] == "SNAPSHOT+OBJECTS" and report["sent"] == ["google"]
    # the pass writes `sgaa_ops` (receipts, outside public) and the target-side settings keys only:
    # no business table changes (configuracoes_backup records the upload clock/policy, as the manual
    # button did; the R8 route lane excludes the same settings table)
    after = _public_counts(env.url)
    assert {table: n for table, n in after.items() if table not in ("cloud_drive_settings", "configuracoes_backup")} == \
        {table: n for table, n in before.items() if table not in ("cloud_drive_settings", "configuracoes_backup")}
    names = [item["name"] for item in env.drive.remote["google"]]
    assert sum(name.startswith("sgaa-pg-snapshot-") for name in names) == 1
    assert sum(name.startswith("sgaa-registros-") for name in names) == 1
    assert sum(name.startswith(hosted_backup.OBJECTS_ARCHIVE_PREFIX) for name in names) == 1
    posture = _posture_of(env)
    assert posture["state"] == "RECORDED"
    assert posture["latest_generation_at"] is not None and posture["latest_object_set_at"] is not None
    check = adapter(env.url)
    try:
        rows = check.execute("SELECT entry, annotation FROM sgaa_ops.backup_records").fetchall()
    finally:
        check.close()
    assert len(rows) == 1
    entry = json.loads(rows[0]["entry"])
    assert entry["object_set_name"].endswith("-hosted") and entry["kind"] == "SNAPSHOT"
    assert entry["object_set_digest"] != "NONE" and "object_files" in entry and "google" in entry["object_files"]
    # a second wake right after is a no-op: nothing due
    with env.app.app_context():
        again = hosted_backup.run_backup_pass(store=env.store, build_objects=object_sets.build_objects_archive)
    assert again["result_code"] == hosted_backup.RESULT_NOT_DUE
    assert len(env.drive.remote["google"]) == 3  # no new files


@needs_pg
def test_the_scheduler_front_wakes_the_full_pass_with_the_injected_object_builder(production, monkeypatch):
    """AC2/AC6: the platform's wake path itself -- bearer, dispatch, due-ness, objects, receipt."""
    env = production
    _set_policy(env, database_cadence_hours=24, object_cadence_days=7, retention_generations=2,
                restore_test_days=30)
    monkeypatch.setenv("CRON_SECRET", SECRET)
    client = Client(scheduler.application)
    response = client.post(scheduler.ROUTE_BACKUP, headers={"Authorization": f"Bearer {SECRET}"})
    assert response.status_code == 200
    body = response.get_json()
    assert body["command"] == "backup" and body["result_code"] == "OK"
    assert body["action"] == "SNAPSHOT+OBJECTS" and body["sent"] == ["google"]
    names = [item["name"] for item in env.drive.remote["google"]]
    assert sum(name.startswith(hosted_backup.OBJECTS_ARCHIVE_PREFIX) for name in names) == 1
    assert _posture_of(env)["state"] == "RECORDED"
    # a second wake answers NOT_DUE over the same path
    again = client.post(scheduler.ROUTE_BACKUP, headers={"Authorization": f"Bearer {SECRET}"})
    assert again.status_code == 200 and again.get_json()["result_code"] == "NOT_DUE"


@needs_pg
def test_the_receipt_makes_the_banco_de_dados_page_show_the_generation_without_any_manual_call(production):
    """AC2: the page reads what the pass published; no manual route is called."""
    env = production
    _set_policy(env, database_cadence_hours=24, object_cadence_days=7, retention_generations=2,
                restore_test_days=30)
    with env.app.app_context():
        assert hosted_backup.run_backup_pass(store=env.store, build_objects=object_sets.build_objects_archive)["result_code"] == hosted_backup.RESULT_OK
    client = env.app.test_client()
    assert client.post("/login", data={"email": "mp2.admin@example.test",
                                       "senha": "mp2-senha-admin-sintetica"}).status_code == 302
    page = client.get("/admin/banco-dados").get_data(as_text=True)
    assert "Gerações registradas" in page and "Em dia" in page
    assert "Incluídos" in page and "Backup agora" in page
    assert "nenhuma geração registrada" not in page


@needs_pg
def test_a_full_backup_survives_the_restore_path_the_admin_page_offers(production, tmp_path):
    """AC1: the exact snapshot the pass ships (same creator) restores through the qualified Path-B
    reader into an empty database and the restored business fingerprint equals the source's."""
    import sqlite3

    from app import pg_migrate_from_sqlite as pathb
    from app import pg_schema
    from app.backup import pg_snapshot
    from tools import pg_fingerprint

    env = production
    with env.app.app_context():
        snap = pg_snapshot.create(str(tmp_path))
    lite = sqlite3.connect(snap["path"])
    try:
        assert lite.execute("PRAGMA user_version").fetchone()[0] == 16
        assert lite.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert lite.execute("SELECT count(*) FROM storage_objects").fetchone()[0] == len(env.ids)
    finally:
        lite.close()
    name, target_url = env.registry.create()
    try:
        target = raw_connection(target_url)
        pg_schema.provision_pg_schema(target)
        target.commit()
        target.close()
        pathb.migrate(snap["path"], snap["sha256"], database_url=target_url, apply=True)
        source_raw = raw_connection(env.url, autocommit=True)
        target_raw = raw_connection(target_url, autocommit=True)
        try:
            assert pg_fingerprint.snapshot(target_raw)["fingerprint_sha256"] == \
                pg_fingerprint.snapshot(source_raw)["fingerprint_sha256"]
        finally:
            source_raw.close()
            target_raw.close()
    finally:
        env.registry.drop(name)


@needs_pg
def test_retention_prunes_each_kind_to_the_policy_and_keeps_the_newest(production):
    """AC4: three generations under keep=2 rotate the OLDEST one out of every kind, both real."""
    import contextlib
    import unittest.mock

    env = production
    _set_policy(env, database_cadence_hours=24, object_cadence_days=1, retention_generations=2,
                restore_test_days=30)
    from app.backup import pg_snapshot

    real = hosted_backup.datetime

    @contextlib.contextmanager
    def _time_jump(hours):
        class _Now(real.datetime):
            @classmethod
            def now(cls, tz=None):
                return real.datetime.now(tz) + real.timedelta(hours=hours)

        shim = type("_Shim", (), {"timedelta": real.timedelta, "timezone": real.timezone, "datetime": _Now})
        # both clocks advance: the wake decision (hosted_backup) and the snapshot's own stamp, which
        # names the files and therefore decides the "newest" order retention prunes by
        with unittest.mock.patch.object(hosted_backup, "datetime", shim), \
                unittest.mock.patch.object(pg_snapshot, "datetime", _Now):
            yield

    with env.app.app_context():
        assert hosted_backup.run_backup_pass(store=env.store, build_objects=object_sets.build_objects_archive)["result_code"] == hosted_backup.RESULT_OK
    first = [item["id"] for item in env.drive.remote["google"]]
    for hours in (25, 50):  # each jump past the 24h cadence makes the next wake due
        with _time_jump(hours):
            with env.app.app_context():
                assert hosted_backup.run_backup_pass(store=env.store, build_objects=object_sets.build_objects_archive)["result_code"] == hosted_backup.RESULT_OK
    assert set(env.drive.deleted) == set(first)  # keep=2: the oldest generation pruned, kind by kind
    names = [item["name"] for item in env.drive.remote["google"]]
    assert len(names) == 6
    assert sum(name.startswith("sgaa-pg-snapshot-") for name in names) == 2
    assert sum(name.startswith("sgaa-registros-") for name in names) == 2
    assert sum(name.startswith(hosted_backup.OBJECTS_ARCHIVE_PREFIX) for name in names) == 2


@needs_pg
def test_the_lock_is_committed_and_visible_to_other_backends_immediately(production):
    """M2/F2: even when the request connection is inside an ambient transaction, the lease is
    committed on its own -- another backend sees it while the protected run is in flight, and it
    disappears the moment the run releases it."""
    env = production
    worker = adapter(env.url)                 # a request-style connection with an ambient transaction
    observer = raw_connection(env.url, autocommit=True)
    try:
        worker.execute("SELECT 1")            # the auth hooks read first: an ambient transaction is open
        holder = hosted_backup.backup_lock(worker)
        assert holder and holder != hosted_backup.LOCK_HOLDER_LOCAL
        seen = observer.execute("SELECT holder FROM sgaa_ops.backup_lock WHERE lock_key = 1").fetchone()
        assert seen and seen[0] == holder     # visible to another backend WHILE the run is in flight
        hosted_backup.backup_unlock(worker, holder)
        assert observer.execute("SELECT count(*) FROM sgaa_ops.backup_lock").fetchone()[0] == 0
    finally:
        worker.close()
        observer.close()


def test_run_ddl_retries_once_when_a_concurrent_first_use_races_the_catalog():
    """F3: two processes creating the control schema at once: one loses the catalog race even with
    IF NOT EXISTS; the helper retries once and the second attempt finds the objects committed."""
    attempts = []

    class Racey:
        def transaction(self):
            import contextlib

            return contextlib.nullcontext()

        def execute(self, sql):
            attempts.append(sql)
            if len(attempts) == 1:
                raise RuntimeError("tuple concurrently updated")

    pg_posture.run_ddl(Racey(), ("CREATE SCHEMA IF NOT EXISTS sgaa_ops",))
    assert len(attempts) == 2


def test_the_lock_lease_outlives_the_platform_function_limit():
    """The scheduler function is killed at 300 s; the lease must not expire under a live run."""
    assert hosted_backup.LOCK_LEASE_SECONDS >= 2 * 300


class _ScheduleRaw:
    """The minimum psycopg surface ``note_wake`` reads and writes (no server)."""

    def __init__(self):
        self.row = None

    def transaction(self):
        import contextlib

        return contextlib.nullcontext()

    def execute(self, sql, params=None):
        if sql == hosted_backup.SCHEDULE_SELECT_SQL:
            self._pending = "select"
        elif sql == hosted_backup.SCHEDULE_INSERT_SQL:
            self.row = (params[0], params[1], list(params[2]))
        elif sql == hosted_backup.SCHEDULE_UPDATE_SQL:
            self.row = (params[0], params[1], list(params[2]))
        return self

    def fetchone(self):
        return self.row if getattr(self, "_pending", None) == "select" else None


def test_note_wake_keeps_the_maximum_of_the_retained_spacings():
    """A7: the first wake stores the daily floor; later wakes append the elapsed spacing (clamped,
    a sub-minute one being a duplicate delivery) and the decision reads the window's MAXIMUM -- a
    short interleaved gap can never lower it."""
    raw = _ScheduleRaw()
    t0 = datetime.datetime(2026, 10, 1, 6, 0, tzinfo=datetime.timezone.utc)
    assert hosted_backup.note_wake(raw, t0) == hosted_backup.DEFAULT_WAKE_SECONDS
    assert hosted_backup.DEFAULT_WAKE_SECONDS == 86400
    assert hosted_backup.note_wake(raw, t0 + datetime.timedelta(hours=23)) == 23 * 3600
    # a short interleaved gap must not lower the maximum (the R3 round 3 finding)
    assert hosted_backup.note_wake(raw, t0 + datetime.timedelta(hours=23, minutes=7)) == 23 * 3600
    # a duplicate delivery adds nothing
    assert hosted_backup.note_wake(raw, t0 + datetime.timedelta(hours=23, minutes=7, seconds=30)) == 23 * 3600
    assert hosted_backup.note_wake(raw, t0 + datetime.timedelta(days=20)) == hosted_backup.WAKE_MAX_SECONDS
    assert (hosted_backup.WAKE_MIN_SECONDS, hosted_backup.WAKE_MAX_SECONDS) == (60, 7 * 24 * 3600)


@needs_pg
def test_the_lock_row_is_shared_with_the_manual_route_and_never_sticks(production):
    """M2: a held, unexpired lease refuses the pass (SKIPPED_BUSY) and the manual button (busy
    message); an expired lease is stolen, and a released run leaves no false-busy row."""
    env = production
    _set_policy(env, database_cadence_hours=24, object_cadence_days=7, retention_generations=2,
                restore_test_days=30)
    holder = raw_connection(env.url, autocommit=True)
    try:
        for statement in hosted_backup.LOCK_DDL:
            holder.execute(statement)
        holder.execute("INSERT INTO sgaa_ops.backup_lock (lock_key, holder, expires_at)"
                       " VALUES (1, 'held', now() + interval '5 minutes')")
        with env.app.app_context():
            assert hosted_backup.run_backup_pass(store=env.store, build_objects=object_sets.build_objects_archive)["result_code"] == hosted_backup.RESULT_SKIPPED_BUSY
        client = env.app.test_client()
        assert client.post("/login", data={"email": "mp2.admin@example.test",
                                           "senha": "mp2-senha-admin-sintetica"}).status_code == 302
        client.post("/admin/banco-dados/backup")
        with client.session_transaction() as session:
            flashes = list(session.pop("_flashes", []))
        assert any("Outro backup está em andamento" in message for _category, message in flashes)
        # an expired lease is stolen: a killed run can never leave a persistent false-busy state
        holder.execute("UPDATE sgaa_ops.backup_lock SET expires_at = now() - interval '1 second'")
        with env.app.app_context():
            assert hosted_backup.run_backup_pass(store=env.store, build_objects=object_sets.build_objects_archive)["result_code"] == hosted_backup.RESULT_OK
        assert holder.execute("SELECT count(*) FROM sgaa_ops.backup_lock").fetchone()[0] == 0
    finally:
        holder.close()


@needs_pg
def test_the_lock_lease_steal_and_release_are_holder_safe(production):
    """M2: a steal never releases the thief; a stale release deletes nothing."""
    env = production
    first_conn, second_conn = adapter(env.url), adapter(env.url)
    try:
        first = hosted_backup.backup_lock(first_conn)
        assert first and first != hosted_backup.LOCK_HOLDER_LOCAL
        assert hosted_backup.backup_lock(second_conn) is None  # a fresh lease refuses
        second_conn.raw_connection.execute(
            "UPDATE sgaa_ops.backup_lock SET expires_at = now() - interval '1 second'")
        second_conn.raw_connection.commit()
        second = hosted_backup.backup_lock(second_conn)
        assert second and second != first  # the expired lease is stolen
        hosted_backup.backup_unlock(first_conn, first)  # the stale holder releases nothing
        row = second_conn.execute("SELECT holder FROM sgaa_ops.backup_lock WHERE lock_key = 1").fetchone()
        assert row and row[0] == second
        hosted_backup.backup_unlock(second_conn, second)
        assert second_conn.execute("SELECT count(*) FROM sgaa_ops.backup_lock").fetchone()[0] == 0
    finally:
        first_conn.close()
        second_conn.close()


@needs_pg
def test_a_partial_delivery_never_advances_the_protection_clock_and_retries(production, monkeypatch):
    """M1: with one connected drive failing, nothing is recorded (the page stays without a
    generation); once the drive recovers, the next wake completes and records."""
    env = production
    _set_policy(env, database_cadence_hours=24, object_cadence_days=7, retention_generations=2,
                restore_test_days=30)
    monkeypatch.setattr(hosted_backup, "active_cloud_account",
                        lambda c, provider: {"account_email": "x@example.invalid"}
                        if provider in ("google", "onedrive") else None)
    env.drive.fail_for = {"onedrive"}
    with env.app.app_context():
        report = hosted_backup.run_backup_pass(store=env.store, build_objects=object_sets.build_objects_archive)
    assert report["result_code"] == hosted_backup.RESULT_DELIVERY_INCOMPLETE
    assert report["failed"] == ["OneDrive"]
    posture = _posture_of(env)
    assert posture["state"] == "RECORDED" and posture["latest_generation_at"] is None  # clock untouched
    assert posture["recent"][0]["complete"] is False
    assert env.drive.remote["google"]  # the copy that landed stays (owned by the partial receipt)
    env.drive.fail_for = set()
    with env.app.app_context():
        again = hosted_backup.run_backup_pass(store=env.store, build_objects=object_sets.build_objects_archive)
    assert again["result_code"] == hosted_backup.RESULT_OK and again["action"] == "SNAPSHOT+OBJECTS"
    assert set(again["sent"]) == {"google", "onedrive"}
    assert _posture_of(env)["latest_generation_at"] is not None


@needs_pg
def test_a_manual_partial_never_satisfies_the_scheduled_cadence(production, monkeypatch):
    """M1/F1 mixed history: a partial manual run records its truth but does not advance the
    protection clock, so the scheduled wake still runs and completes the delivery."""
    env = production
    _set_policy(env, database_cadence_hours=24, object_cadence_days=7, retention_generations=2,
                restore_test_days=30)
    monkeypatch.setattr(hosted_backup, "active_cloud_account",
                        lambda c, provider: {"account_email": "x@example.invalid"}
                        if provider in ("google", "onedrive") else None)
    env.drive.fail_for = {"onedrive"}
    with env.app.app_context():
        targets, sent, failed, registers_failed, manifest = hosted_backup.send_snapshot()  # manual path
    assert targets == ["google", "onedrive"] and sent == ["google"] and failed == ["OneDrive"]
    assert manifest  # recorded with the truth
    posture = _posture_of(env)
    assert posture["latest_generation_at"] is None and posture["recent"][0]["complete"] is False
    env.drive.fail_for = set()
    with env.app.app_context():
        report = hosted_backup.run_backup_pass(store=env.store, build_objects=object_sets.build_objects_archive)
    assert report["result_code"] == hosted_backup.RESULT_OK
    assert _posture_of(env)["latest_generation_at"] is not None


def _clock_at(day, hour, minute):
    """A fixed UTC clock for the wake/snapshot shims (October 2026)."""
    real = hosted_backup.datetime

    class _Now(real.datetime):
        @classmethod
        def now(cls, tz=None):
            return real.datetime(2026, 10, day, hour, minute, 0, tzinfo=real.timezone.utc)

    shim = type("_Shim", (), {"timedelta": real.timedelta, "timezone": real.timezone, "datetime": _Now})
    return shim, _Now


def _run_at(env, day, hour, minute, call):
    from app.backup import pg_snapshot

    shim, now_cls = _clock_at(day, hour, minute)
    with unittest.mock.patch.object(hosted_backup, "datetime", shim), \
            unittest.mock.patch.object(pg_snapshot, "datetime", now_cls):
        with env.app.app_context():
            return call()


@needs_pg
def test_the_reviewer_sequence_a_manual_at_0700_then_the_0447_wake_runs(production):
    """M4 discriminating lane: Day1 06:00 scheduled, Day1 07:00 complete manual, Day2 04:47 wake.
    At 692cedd this wake was NOT_DUE and the next ran Day3 04:47 -- a 45 h 47 min gap.  With the
    deadline rule (the deadline falls before the next expected wake) it runs at Day2 04:47."""
    env = production
    _set_policy(env, database_cadence_hours=24, object_cadence_days=7, retention_generations=2,
                restore_test_days=30)
    first = _run_at(env, 1, 6, 0,
                    lambda: hosted_backup.run_backup_pass(store=env.store,
                                                          build_objects=object_sets.build_objects_archive))
    assert first["result_code"] == hosted_backup.RESULT_OK
    manual = _run_at(env, 1, 7, 0, lambda: hosted_backup.send_snapshot())
    assert manual[1] == ["google"]  # the complete manual generation
    posture = _posture_of(env)
    assert posture["latest_generation_at"].strftime("%Y-%m-%dT%H:%M:%SZ") == "2026-10-01T07:00:00Z"
    day2 = _run_at(env, 2, 4, 47,
                   lambda: hosted_backup.run_backup_pass(store=env.store,
                                                         build_objects=object_sets.build_objects_archive))
    assert day2["result_code"] == hosted_backup.RESULT_OK  # THE discriminator (was NOT_DUE)
    posture = _posture_of(env)
    assert posture["latest_generation_at"].strftime("%Y-%m-%dT%H:%M:%SZ") == "2026-10-02T04:47:00Z"


@needs_pg
def test_the_deadline_edge_wake_runs_so_a_delayed_wake_cannot_stretch_the_gap(production):
    """A6 discriminating lane: Day1 00:00 generation, 6-hourly wakes.  At Day1 18:00 the age (18 h)
    equals `cadence - interval` (24 h - 6 h): the old threshold (18 h 01 m, the guard inside the
    deadline test) skipped it, and a 1-minute-delayed Day2 00:01 wake then ran -- a 24 h 01 min gap
    (reproduced on db72ce2).  The deadline test is now `age >= cadence - interval` with no guard in
    the threshold, so the edge wake runs (an 18 h gap) and the delayed wake is a no-op."""
    env = production
    _set_policy(env, database_cadence_hours=24, object_cadence_days=7, retention_generations=2,
                restore_test_days=30)
    run = lambda: hosted_backup.run_backup_pass(store=env.store,  # noqa: E731
                                                build_objects=object_sets.build_objects_archive)
    codes = [
        _run_at(env, 1, 0, 0, run)["result_code"],
        _run_at(env, 1, 6, 0, run)["result_code"],
        _run_at(env, 1, 12, 0, run)["result_code"],
        _run_at(env, 1, 18, 0, run)["result_code"],   # the edge: must run
        _run_at(env, 2, 0, 1, run)["result_code"],    # the delayed wake: must be a no-op
    ]
    assert codes == ["OK", "NOT_DUE", "NOT_DUE", "OK", "NOT_DUE"]
    posture = _posture_of(env)
    assert posture["latest_generation_at"].strftime("%Y-%m-%dT%H:%M:%SZ") == "2026-10-01T18:00:00Z"


@needs_pg
def test_the_reviewer_sequence_interleaved_triggers_never_stretch_the_gap(production):
    """R3 round 3 (A7) discriminating lane: a complete manual at Day1 10:00, the six-hourly trigger
    and the daily cron (04:47).  Under the last-interval rule (23d10b7) the short interleaved gap
    (04:47 -> 06:00, 1 h 13 min) inflated the threshold: Day2 04:47 and 06:00 answered NOT_DUE and
    Day2 12:00 ran -- 26 h between complete generations.  Under the maximum-demonstrated-spacing
    rule the 04:47 wake runs (age 18 h 47 min >= 24 h - 6 h) and the gap stays under the cadence."""
    env = production
    _set_policy(env, database_cadence_hours=24, object_cadence_days=7, retention_generations=2,
                restore_test_days=30)
    run = lambda: hosted_backup.run_backup_pass(store=env.store,  # noqa: E731
                                                build_objects=object_sets.build_objects_archive)
    codes = [
        _run_at(env, 1, 0, 0, run)["result_code"],      # the first wake (no receipts) -> a generation
        _run_at(env, 1, 6, 0, run)["result_code"],
    ]
    manual = _run_at(env, 1, 10, 0, lambda: hosted_backup.send_snapshot())
    assert manual[1] == ["google"]  # the complete manual generation
    codes += [
        _run_at(env, 1, 12, 0, run)["result_code"],
        _run_at(env, 1, 18, 0, run)["result_code"],
        _run_at(env, 2, 0, 0, run)["result_code"],
        _run_at(env, 2, 4, 47, run)["result_code"],     # the cron: must run
        _run_at(env, 2, 6, 0, run)["result_code"],      # the interleaved short gap: must not run
        _run_at(env, 2, 12, 0, run)["result_code"],
    ]
    assert codes == ["OK", "NOT_DUE", "NOT_DUE", "NOT_DUE", "NOT_DUE", "OK", "NOT_DUE", "NOT_DUE"]
    posture = _posture_of(env)
    assert posture["latest_generation_at"].strftime("%Y-%m-%dT%H:%M:%SZ") == "2026-10-02T04:47:00Z"


@needs_pg
def test_the_wake_interval_is_learned_on_real_postgresql(production):
    """M4: the schedule row stores the daily floor, learns the observed interval, and keeps it on a
    duplicate delivery."""
    env = production
    _set_policy(env, database_cadence_hours=24, object_cadence_days=7, retention_generations=2,
                restore_test_days=30)

    def schedule():
        conn = raw_connection(env.url, autocommit=True)
        try:
            return conn.execute("SELECT last_interval_seconds FROM sgaa_ops.backup_schedule"
                                " WHERE schedule_key = 1").fetchone()[0]
        finally:
            conn.close()

    first = _run_at(env, 1, 6, 0,
                    lambda: hosted_backup.run_backup_pass(store=env.store,
                                                          build_objects=object_sets.build_objects_archive))
    assert first["result_code"] == hosted_backup.RESULT_OK and schedule() == hosted_backup.DEFAULT_WAKE_SECONDS
    second = _run_at(env, 2, 5, 0,
                     lambda: hosted_backup.run_backup_pass(store=env.store,
                                                           build_objects=object_sets.build_objects_archive))
    assert second["result_code"] == hosted_backup.RESULT_OK and schedule() == 23 * 3600
    duplicate = _run_at(env, 2, 5, 0,  # 30 s later: a duplicate delivery, not an interval
                        lambda: hosted_backup.run_backup_pass(store=env.store,
                                                              build_objects=object_sets.build_objects_archive))
    assert duplicate["result_code"] == hosted_backup.RESULT_NOT_DUE and schedule() == 23 * 3600


@needs_pg
def test_the_daily_cron_alone_bounds_the_gap_by_its_own_spacing(production):
    """M4/RPO (A5): the platform fires the daily cron inside its hour, so consecutive wakes can be
    24 h 59 min apart (04:00 then 04:59).  The deadline rule runs at every such wake -- no skip --
    but no decision rule can compress a waker's spacing: with the daily cron alone the bound is the
    spacing itself (up to cadence + the platform's in-hour precision).  The wake ladder (D4) is the
    coverage; the ladder lane shows every gap at or under the cadence."""
    env = production
    _set_policy(env, database_cadence_hours=24, object_cadence_days=7, retention_generations=2,
                restore_test_days=30)
    generations = []
    for day, hour, minute in ((1, 4, 0), (2, 4, 59), (3, 4, 0), (4, 4, 59)):
        report = _run_at(env, day, hour, minute,
                         lambda: hosted_backup.run_backup_pass(
                             store=env.store, build_objects=object_sets.build_objects_archive))
        assert report["result_code"] == hosted_backup.RESULT_OK  # every wake runs: never a skip
        generations.append(_posture_of(env)["latest_generation_at"])
    assert [g.strftime("%Y-%m-%dT%H:%M:%SZ") for g in generations] == [
        "2026-10-01T04:00:00Z", "2026-10-02T04:59:00Z", "2026-10-03T04:00:00Z", "2026-10-04T04:59:00Z"]
    gaps = [later - earlier for earlier, later in zip(generations, generations[1:])]
    assert gaps == [datetime.timedelta(hours=24, minutes=59), datetime.timedelta(hours=23, minutes=1),
                    datetime.timedelta(hours=24, minutes=59)]
    assert max(gaps) > datetime.timedelta(hours=24)  # the concrete limitation: the waker is the bound


@needs_pg
def test_the_wake_ladder_bounds_every_gap_under_the_cadence(production):
    """M4/RPO (A5): the ladder of D4 -- the daily cron with its worst-case 04:00/04:59 jitter plus
    the free Supabase Cron/pg_net trigger at 6 h -- keeps every gap between consecutive generations
    at or under the 24 h cadence: the trigger's dense wakes let the deadline rule run before the
    deadline, which the lone daily cron cannot do."""
    env = production
    _set_policy(env, database_cadence_hours=24, object_cadence_days=7, retention_generations=2,
                restore_test_days=30)
    base = datetime.datetime(2026, 10, 1, tzinfo=datetime.timezone.utc)
    wakes = []
    for day in range(3):
        wakes.append(base + datetime.timedelta(days=day, hours=4, minutes=59 if day % 2 else 0))
        for hour in (6, 12, 18):
            wakes.append(base + datetime.timedelta(days=day, hours=hour))
        wakes.append(base + datetime.timedelta(days=day + 1, hours=0))
    wakes = sorted(set(wakes))
    generations = []
    for wake in wakes:
        report = _run_at(env, wake.day, wake.hour, wake.minute,
                         lambda: hosted_backup.run_backup_pass(
                             store=env.store, build_objects=object_sets.build_objects_archive))
        if report["result_code"] == hosted_backup.RESULT_OK:
            generations.append(_posture_of(env)["latest_generation_at"])
    assert len(generations) == 4 and len(generations) < len(wakes)  # not on every wake
    gaps = [later - earlier for earlier, later in zip(generations, generations[1:])]
    assert all(gap <= datetime.timedelta(hours=24) for gap in gaps)
    assert max(gaps) >= datetime.timedelta(hours=20)  # runs near the deadline


@needs_pg
def test_an_unverifiable_policy_refuses_the_scheduled_run(production):
    """M3: a partial stored policy refuses the wake; nothing is uploaded and nothing recorded."""
    env = production
    _set_policy(env, database_cadence_hours=24, object_cadence_days=7, retention_generations=2,
                restore_test_days=30)
    conn = adapter(env.url)
    try:
        conn.execute("DELETE FROM configuracoes_backup WHERE chave = 'pg_object_cadence_days'")
        conn.commit()
    finally:
        conn.close()
    with env.app.app_context():
        report = hosted_backup.run_backup_pass(store=env.store, build_objects=object_sets.build_objects_archive)
    assert report["result_code"] == hosted_backup.RESULT_POLICY_INVALID
    assert env.drive.remote["google"] == [] and _posture_of(env)["state"] == "EMPTY"
    _set_policy(env, object_cadence_days=7)
    with env.app.app_context():
        assert hosted_backup.run_backup_pass(
            store=env.store, build_objects=object_sets.build_objects_archive)["result_code"] == hosted_backup.RESULT_OK


@needs_pg
def test_the_set_archive_round_trips_to_a_verified_set(production, tmp_path):
    """AC3: the shipped archive unzips into a set ``verify-backup`` accepts, byte for byte."""
    import shutil

    from app.storage import object_backup

    env = production
    snapshot = {"generation_at": "2026-10-13T10:00:00Z", "source_identity_sha256": "a" * 64}
    conn = adapter(env.url)
    try:
        built = object_sets.build_objects_archive(conn, str(tmp_path), snapshot, store=env.store)
        conn.rollback()
    finally:
        conn.close()
    assert built["code"] is None, built
    unpacked = tmp_path / "unpacked"
    with zipfile.ZipFile(built["archive"]) as archive:
        archive.extractall(unpacked)
    report = object_backup.verify_set(str(unpacked))
    assert report.ok and report.objects == len(env.ids)
    assert report.objects_digest == built["report"].objects_digest
    assert "MANIFEST.json" in {p.name for p in unpacked.iterdir()}


@needs_pg
def test_the_cadence_and_the_policy_come_from_the_administrator(production):
    """AC5/AC6: a cadence of 24h holds for a day; a 1h cadence makes the next wake due."""
    env = production
    _set_policy(env, database_cadence_hours=24, object_cadence_days=7, retention_generations=2,
                restore_test_days=30)
    with env.app.app_context():
        assert hosted_backup.run_backup_pass(store=env.store, build_objects=object_sets.build_objects_archive)["result_code"] == hosted_backup.RESULT_OK
        assert hosted_backup.run_backup_pass(store=env.store, build_objects=object_sets.build_objects_archive)["result_code"] == hosted_backup.RESULT_NOT_DUE
    _set_policy(env, database_cadence_hours=1)
    real = hosted_backup.datetime

    class _Shim:
        timedelta = real.timedelta
        timezone = real.timezone

        class datetime(real.datetime):
            @classmethod
            def now(cls, tz=None):
                return real.datetime.now(tz) + real.timedelta(hours=1, minutes=1)

    import unittest.mock

    with unittest.mock.patch.object(hosted_backup, "datetime", _Shim):
        with env.app.app_context():
            assert hosted_backup.run_backup_pass(store=env.store, build_objects=object_sets.build_objects_archive)["result_code"] == hosted_backup.RESULT_OK
    assert sum(name.startswith("sgaa-pg-snapshot-") for name in
               [item["name"] for item in env.drive.remote["google"]]) == 2
