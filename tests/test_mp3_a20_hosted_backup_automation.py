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
    """The pass with every boundary scripted; ``_deliver`` and the posture reads are fakes the test sets."""
    state = SimpleNamespace(deliveries=[], deliver_result=None, posture=None, raises=None,
                            unlocks=[], locks=[True], deliver_kwargs=None, policy_error=None)
    monkeypatch.setattr(hosted_backup, "get_db_connection", lambda: _Conn())

    def lock(_conn):
        taken = state.locks.pop(0) if state.locks else True
        return "HOLDER" if taken else None

    monkeypatch.setattr(hosted_backup, "backup_lock", lock)
    monkeypatch.setattr(hosted_backup, "backup_unlock", lambda _conn, _holder: state.unlocks.append(1))
    monkeypatch.setattr(pg_posture, "read", lambda raw, now=None: state.posture)

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

    def deliver(*, prune, with_objects, store=None, build_objects=None, require_complete=False):
        state.deliveries.append({"prune": prune, "with_objects": with_objects,
                                 "require_complete": require_complete})
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
    env.posture = _posture(latest_hours=1, latest_objects_hours=2)
    report = hosted_backup.run_backup_pass()
    assert report["result_code"] == hosted_backup.RESULT_NOT_DUE
    assert env.deliveries == [] and env.unlocks == [1]


def test_a_first_run_backs_up_database_and_objects(env):
    env.posture = _posture(latest_hours=None, latest_objects_hours=None)
    env.deliver_result = _delivered()
    report = hosted_backup.run_backup_pass()
    assert report["result_code"] == hosted_backup.RESULT_OK and report["action"] == "SNAPSHOT+OBJECTS"
    assert env.deliveries == [{"prune": True, "with_objects": True, "require_complete": True}]


def test_a_database_only_cadence_never_takes_the_object_set(env):
    env.posture = _posture(cadence=6, latest_hours=7, latest_objects_hours=1)  # objects fresh
    env.deliver_result = _delivered()
    report = hosted_backup.run_backup_pass()
    assert report["result_code"] == hosted_backup.RESULT_OK and report["action"] == "SNAPSHOT"
    assert env.deliveries == [{"prune": True, "with_objects": False, "require_complete": True}]


def test_the_object_cadence_alone_still_ships_a_fresh_database_copy(env):
    env.posture = _posture(cadence=24, object_days=1, latest_hours=1, latest_objects_hours=25)
    env.deliver_result = _delivered()
    report = hosted_backup.run_backup_pass()
    assert report["result_code"] == hosted_backup.RESULT_OK and report["action"] == "SNAPSHOT+OBJECTS"
    assert env.deliveries == [{"prune": True, "with_objects": True, "require_complete": True}]


def test_the_due_window_absorbs_platform_jitter_without_skipping_a_day(env):
    """M4: a 24 h policy with a daily wake that fires up to an hour early still runs the next day."""
    env.deliver_result = _delivered()
    env.posture = _posture(latest_hours=23, latest_objects_hours=23)  # inside the window (22.5 h)
    assert hosted_backup.run_backup_pass()["result_code"] == hosted_backup.RESULT_OK
    env.posture = _posture(latest_hours=22, latest_objects_hours=22)  # outside it: no double run
    assert hosted_backup.run_backup_pass()["result_code"] == hosted_backup.RESULT_NOT_DUE
    assert hosted_backup._due_grace_seconds(24) == 5400
    assert hosted_backup._due_grace_seconds(1) == 900
    assert hosted_backup._due_grace_seconds(168) == 5400


def test_a_47_hour_gap_cannot_happen_under_a_24_hour_policy(env):
    """M4: wakes firing an hour early on consecutive days keep running (~23 h gaps, never ~47 h)."""
    env.deliver_result = _delivered()
    env.posture = _posture(latest_hours=None, latest_objects_hours=None)
    assert hosted_backup.run_backup_pass()["result_code"] == hosted_backup.RESULT_OK
    for hours in (23, 46):  # each wake arrives 1 h before the nominal cadence
        env.posture = _posture(latest_hours=hours, latest_objects_hours=hours)
        assert hosted_backup.run_backup_pass()["result_code"] == hosted_backup.RESULT_OK


def test_a_one_hour_policy_runs_near_hourly_and_never_every_wake(env):
    """M4: the 15-minute window at a 1 h cadence keeps sub-daily runs on cadence, not per wake."""
    env.deliver_result = _delivered()
    env.posture = _posture(cadence=1, latest_hours=0.67, latest_objects_hours=1)  # 40 min: not due
    assert hosted_backup.run_backup_pass()["result_code"] == hosted_backup.RESULT_NOT_DUE
    env.posture = _posture(cadence=1, latest_hours=0.8, latest_objects_hours=1)  # 48 min: due
    assert hosted_backup.run_backup_pass()["result_code"] == hosted_backup.RESULT_OK


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


def test_a_scheduled_run_claims_nothing_until_every_drive_has_every_artifact(monkeypatch, tmp_path):
    """M1: one connected drive missing the snapshot -> no receipt, no advanced clock."""
    calls = _deliver_env(monkeypatch, tmp_path, providers=("google", "onedrive"), fail=("onedrive",))
    result = hosted_backup._deliver(prune=False, with_objects=False, require_complete=True)
    assert result["delivery_complete"] is False and result["manifest"] is None
    assert result["sent"] == ["google"] and result["failed"] == ["OneDrive"]
    assert calls["published"] == []


def test_the_manual_contract_still_publishes_what_landed(monkeypatch, tmp_path):
    """A19 preserved: the manual button publishes the partial delivery and names the missing copy."""
    calls = _deliver_env(monkeypatch, tmp_path, providers=("google", "onedrive"), fail=("onedrive",))
    result = hosted_backup._deliver(prune=False, with_objects=False)
    assert result["delivery_complete"] is False
    [receipt] = calls["published"]
    assert receipt["destinations"] == ["google"] and result["manifest"] == "e" * 64


def test_the_pass_refuses_a_partial_delivery_through_the_real_deliver(monkeypatch, tmp_path):
    """M1: the object archive reaching no drive refuses the pass; nothing is recorded."""
    calls = _deliver_env(monkeypatch, tmp_path, upload_objects_ok=False)
    monkeypatch.setattr(hosted_backup, "backup_lock", lambda conn: "H")
    monkeypatch.setattr(hosted_backup, "backup_unlock", lambda conn, holder: None)
    monkeypatch.setattr(hosted_backup.pg_posture, "read",
                        lambda raw, now=None: _posture(latest_hours=None, latest_objects_hours=None))
    report = hosted_backup.run_backup_pass(build_objects=_builder(tmp_path))
    assert report["result_code"] == hosted_backup.RESULT_DELIVERY_INCOMPLETE
    assert report["action"] == "NONE" and report["objects_failed"] == ["Google Drive"]
    assert calls["published"] == []  # the protection clock did not advance


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


def _prune_fakes(monkeypatch, *, owned, listed, deleted):
    from app import cloud_drives

    monkeypatch.setattr(hosted_backup.pg_posture, "owned_files", lambda raw: set(owned))
    monkeypatch.setattr(hosted_backup._cloud_connections, "get_authenticated_access_token",
                        lambda conn, provider: ("tok", "x"))
    monkeypatch.setattr(cloud_drives, "google_list_folder_files", lambda token, folder, prefix: [
        f for f in listed if str(f["name"]).startswith(prefix)])
    monkeypatch.setattr(cloud_drives, "google_delete_file", lambda token, file_id: deleted.append(file_id))


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
    assert _posture_of(env)["state"] == "EMPTY"  # no receipt: the clock did not advance
    assert env.drive.remote["google"]  # the copy that landed stays (inert until claimed)
    env.drive.fail_for = set()
    with env.app.app_context():
        again = hosted_backup.run_backup_pass(store=env.store, build_objects=object_sets.build_objects_archive)
    assert again["result_code"] == hosted_backup.RESULT_OK and again["action"] == "SNAPSHOT+OBJECTS"
    assert set(again["sent"]) == {"google", "onedrive"}
    assert _posture_of(env)["state"] == "RECORDED"


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
