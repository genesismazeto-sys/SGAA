"""UI-C21 residual: the pre-restore-safety series is bounded, not exempt forever.

UI-C18 pinned the undo point of the most recent restore out of retention.
Keeping that exact snapshot safe is the invariant; keeping **every** safety
snapshot forever was the residual -- the series would grow without bound.

UI-C21 bounds it with the retention configuration that already exists:

* the newest ``pre-restore-safety`` snapshot is never deleted, even when it is
  outside every window or loses its bucket -- it is the undo point of the most
  recent restore;
* every other ``pre-restore-safety`` snapshot takes exactly the decision the
  ordinary GFS windows already made for it (each still occupies its bucket as
  before), so an old undo point is thinned like any other snapshot;
* ``manual-backup`` remains fully exempt.

No new setting and no invented count/age: the windows the administrator
already configures in "Política de retenção" own the bound. ``reason`` plus
``created_at`` (manifest file name breaking same-second ties, the same order
``_run_retention_cleanup`` uses) is all the metadata needed.

Remote provider retention is untouched: safety snapshots are created only in
the local series and are never uploaded.
"""

from __future__ import annotations

import datetime
import json
import sqlite3
from pathlib import Path

from app.backup import automatic
from app.db_maintenance import apply_retention_policy, create_database_snapshot
from tests.test_backup_destination_outcomes_ui_c11_c12 import (  # noqa: F401  (fixtures)
    admin_client,
    backup_env,
    events,
)
from tests.test_retention_pre_restore_safety_ui_c18 import (  # noqa: F401  (test helpers)
    DEFAULT_POLICY,
    _previous_policy,
    _snap,
)

# ------------------------------------------------------------------ unit


def test_newest_safety_survives_every_window_while_older_ones_are_thinned():
    newest = _snap(datetime.timedelta(days=500), "pre-restore-safety", "newest-safety")
    older = _snap(datetime.timedelta(days=600), "pre-restore-safety", "older-safety")
    auto = _snap(datetime.timedelta(days=500), "auto-backup", "auto")
    deleted = apply_retention_policy([newest, older, auto], DEFAULT_POLICY)
    assert sorted(deleted) == sorted([older["manifest_path"], auto["manifest_path"]])


def test_older_safety_losing_its_bucket_is_thinned_like_any_snapshot():
    older = _snap(datetime.timedelta(minutes=50), "pre-restore-safety", "older-safety")
    newest = _snap(datetime.timedelta(minutes=40), "pre-restore-safety", "newest-safety")
    later = [_snap(datetime.timedelta(minutes=m), "auto-backup", f"auto-{m}") for m in (25, 10, 1)]
    deleted = apply_retention_policy([older, newest, *later], DEFAULT_POLICY)
    assert newest["manifest_path"] not in deleted
    assert older["manifest_path"] in deleted


def test_ordinary_snapshots_keep_the_previous_decision_with_safety_present():
    snaps = [
        _snap(datetime.timedelta(minutes=50), "pre-restore-safety", "older-safety"),
        _snap(datetime.timedelta(minutes=40), "pre-restore-safety", "newest-safety"),
        _snap(datetime.timedelta(minutes=30), "auto-backup", "auto-30m"),
        _snap(datetime.timedelta(minutes=5), "manual-backup", "manual"),
        _snap(datetime.timedelta(hours=30), "auto-sync", "sync-30h"),
        _snap(datetime.timedelta(days=400), "post-restore", "restore-old"),
    ]
    deleted = apply_retention_policy(snaps, DEFAULT_POLICY)
    before = _previous_policy(snaps, DEFAULT_POLICY)
    pinned = "/backups/snapshots/newest-safety.json"
    assert pinned not in deleted
    assert deleted == [p for p in before if p != pinned]


def test_same_second_safety_tie_is_broken_like_the_cleanup_order():
    created = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=500)).replace(microsecond=0)
    iso = created.isoformat().replace("+00:00", "Z")
    first_alphabetical = {
        "manifest_path": "/backups/snapshots/safety-a.json",
        "created_at": iso,
        "reason": "pre-restore-safety",
        "origin": "local",
    }
    newest = {
        "manifest_path": "/backups/snapshots/safety-z.json",
        "created_at": iso,
        "reason": "pre-restore-safety",
        "origin": "local",
    }
    assert apply_retention_policy([first_alphabetical, newest], DEFAULT_POLICY) == [
        first_alphabetical["manifest_path"]
    ]


def test_series_without_safety_is_decided_exactly_as_the_previous_policy():
    snaps = [
        _snap(datetime.timedelta(minutes=1), "auto-backup", "a1"),
        _snap(datetime.timedelta(minutes=130), "auto-backup", "a2"),
        _snap(datetime.timedelta(hours=30), "auto-sync", "s1"),
        _snap(datetime.timedelta(hours=200), "post-restore", "p1"),
        _snap(datetime.timedelta(hours=1000), "auto-backup", "a3"),
        _snap(datetime.timedelta(hours=10000), "auto-backup", "a4"),
        _snap(datetime.timedelta(days=500), "manual-backup", "m1"),
    ]
    assert apply_retention_policy(snaps, DEFAULT_POLICY) == _previous_policy(snaps, DEFAULT_POLICY)


# ------------------------------------------------------- end-to-end (disposable DB)


def _safety_records(directory: Path) -> list[tuple[str, dict]]:
    records = []
    for path in (directory / "snapshots").glob("*.json"):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest.get("reason") == "pre-restore-safety":
            records.append((path.name, manifest))
    return records


def _local_reasons(directory: Path) -> list[str]:
    return sorted(
        json.loads(path.read_text(encoding="utf-8")).get("reason")
        for path in (directory / "snapshots").glob("*.json")
    )


def _restore(env, client, source) -> None:
    response = client.post(
        "/admin/banco-dados/restaurar",
        data={"manifest_path": source["manifest_path"]},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)


def _database_ok(env) -> bool:
    import app.db as app_db

    return sqlite3.connect(app_db.DATABASE).execute("PRAGMA quick_check").fetchone()[0] == "ok"


def test_repeated_restores_keep_only_the_latest_undo_point(backup_env, admin_client, events):
    import app.db as app_db

    backup_env.configure(cloud_folder=False, google=False, onedrive=False)
    with backup_env.main.app.app_context():
        source = create_database_snapshot(
            app_db.DATABASE, str(backup_env.local_dir), reason="manual-backup", origin="local"
        )

    _restore(backup_env, admin_client, source)
    first = _safety_records(backup_env.local_dir)
    assert len(first) == 1

    _restore(backup_env, admin_client, source)
    second = {name for name, _manifest in _safety_records(backup_env.local_dir)}
    assert first[0][0] not in second, "the older undo point is thinned once a newer restore exists"
    assert len(second) == 1

    with backup_env.main.app.app_context():
        outcome = automatic.run_automatic_cycle(trigger="scheduled")
    assert outcome["ran"] is True

    after = {name for name, _manifest in _safety_records(backup_env.local_dir)}
    assert second == after, "the scheduled cycle must not prune the latest undo point"
    assert Path(source["manifest_path"]).name in {
        path.name for path in (backup_env.local_dir / "snapshots").glob("*.json")
    }
    assert _database_ok(backup_env)


def test_failed_restore_keeps_the_original_database_and_a_truthful_safety_snapshot(
    backup_env, admin_client, events, monkeypatch
):
    import app.db as app_db
    import app.views.admin.banco_dados as view

    backup_env.configure(cloud_folder=False, google=True, onedrive=True)
    with backup_env.main.app.app_context():
        source = create_database_snapshot(
            app_db.DATABASE, str(backup_env.local_dir), reason="manual-backup", origin="local"
        )
        before = automatic.database_content_digest(app_db.DATABASE)

    def failing_restore(*_a, **_k):
        raise sqlite3.DatabaseError("arquivo corrompido")

    monkeypatch.setattr(view, "restore_database_snapshot", failing_restore)
    with open(source["database_path"], "rb") as handle:
        response = admin_client.post(
            "/admin/banco-dados/restaurar/upload",
            data={"backup_file": (handle, "backup.db")},
            content_type="multipart/form-data",
        )
    assert response.status_code in (302, 303)
    with admin_client.session_transaction() as session:
        assert session.get("_flashes")[-1][0] == "error"
    assert events.uploads == [], "a failed restore must not reach any provider"
    assert automatic.database_content_digest(app_db.DATABASE) == before, "the original database is untouched"

    safety = _safety_records(backup_env.local_dir)
    assert len(safety) == 1
    assert automatic.database_content_digest(safety[0][1]["database_path"]) == before, (
        "the safety snapshot is the pre-restore database"
    )

    with backup_env.main.app.app_context():
        outcome = automatic.run_automatic_cycle(trigger="scheduled")
    assert outcome["ran"] is True
    assert {name for name, _manifest in _safety_records(backup_env.local_dir)} == {safety[0][0]}, (
        "ordinary retention must preserve the undo point"
    )
    assert _database_ok(backup_env)


def test_safety_snapshots_stay_out_of_the_cloud_series(backup_env, admin_client, events):
    import app.db as app_db

    backup_env.configure(cloud_folder=True, google=True, onedrive=True)
    with backup_env.main.app.app_context():
        source = create_database_snapshot(
            app_db.DATABASE, str(backup_env.local_dir), reason="manual-backup", origin="local"
        )
    _restore(backup_env, admin_client, source)

    assert "pre-restore-safety" in _local_reasons(backup_env.local_dir)
    cloud_reasons = sorted(
        json.loads(path.read_text(encoding="utf-8")).get("reason")
        for path in (backup_env.cloud_dir / "snapshots").glob("*.json")
    )
    assert cloud_reasons == ["forced-sync"], cloud_reasons
    safety_dbs = {Path(manifest["database_path"]).name for _name, manifest in _safety_records(backup_env.local_dir)}
    assert safety_dbs
    for _provider, path in events.uploads:
        assert Path(path).name not in safety_dbs
