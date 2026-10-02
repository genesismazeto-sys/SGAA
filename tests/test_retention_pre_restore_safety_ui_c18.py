"""UI-C18 residual: normal retention never removes the current restore's undo point.

A database restore first writes a ``pre-restore-safety`` snapshot into the local
series. ``apply_retention_policy`` exempted only ``manual-backup``, and keeps
the *newest* snapshot of each bucket, so the first scheduled automatic backup
after a restore (same 2 h bucket) deleted the undo point.

Contract now (``app.db_maintenance.apply_retention_policy``):

* the newest ``pre-restore-safety`` snapshot is never in the delete list
  (UI-C18; bounded by UI-C21 to exactly this one, see the UI-C21 file);
* it still occupies its bucket exactly as before, so every other snapshot is
  kept or thinned exactly as the previous policy decided (proven against a
  verbatim copy of the previous algorithm);
* the ``manual-backup`` exemption is unchanged.

Remote provider retention is untouched: providers never receive a
``pre-restore-safety`` snapshot (a restore uploads a separate ``post-restore``
copy; scheduled cycles upload their own ``auto-backup``).
"""

from __future__ import annotations

import datetime
import itertools
import json
import os
from pathlib import Path

import pytest

from app.backup import automatic
from app.db_maintenance import apply_retention_policy
from tests.test_backup_destination_outcomes_ui_c11_c12 import (  # noqa: F401  (fixtures)
    admin_client,
    backup_env,
    events,
)

UTC = datetime.timezone.utc
DEFAULT_POLICY = [
    {"period_hours": 24, "interval_hours": 2.0, "slots": 12},
    {"period_hours": 168, "interval_hours": 24.0, "slots": 7},
    {"period_hours": 672, "interval_hours": 168.0, "slots": 4},
    {"period_hours": 8760, "interval_hours": 730.0, "slots": 12},
]


def _snap(age: datetime.timedelta, reason: str, name: str) -> dict:
    created = (datetime.datetime.now(UTC) - age).replace(microsecond=0)
    return {
        "manifest_path": f"/backups/snapshots/{name}.json",
        "created_at": created.isoformat().replace("+00:00", "Z"),
        "reason": reason,
        "origin": "local",
    }


def _previous_policy(snapshots: list[dict], policy: list[dict]) -> list[str]:
    """``apply_retention_policy`` exactly as it was before this repair."""
    now = datetime.datetime.now(UTC)
    parsed = []
    for snap in snapshots:
        try:
            dt = datetime.datetime.fromisoformat((snap.get("created_at") or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        parsed.append({**snap, "_dt": dt})
    parsed.sort(key=lambda x: x["_dt"], reverse=True)
    kept: set[str] = set()
    for window in policy:
        period_h, interval_h, slots = float(window["period_hours"]), float(window["interval_hours"]), int(window["slots"])
        if interval_h <= 0 or slots <= 0:
            continue
        cutoff = now - datetime.timedelta(hours=period_h)
        buckets: dict[int, dict] = {}
        for snap in parsed:
            if snap.get("reason") == "manual-backup" or snap["_dt"] < cutoff:
                continue
            buckets.setdefault(int((now - snap["_dt"]).total_seconds() / 3600.0 / interval_h), snap)
        for i, (_, snap) in enumerate(sorted(buckets.items())):
            if i >= slots:
                break
            if snap.get("manifest_path"):
                kept.add(snap["manifest_path"])
    return [
        s["manifest_path"]
        for s in parsed
        if s.get("manifest_path") and s.get("reason") != "manual-backup" and s["manifest_path"] not in kept
    ]


# ------------------------------------------------------------------ A-E, unit


def test_safety_snapshot_survives_later_automatic_snapshots_in_its_bucket():
    safety = _snap(datetime.timedelta(minutes=40), "pre-restore-safety", "safety")          # A
    later = [_snap(datetime.timedelta(minutes=m), "auto-backup", f"auto-{m}") for m in (25, 10, 1)]  # B
    deleted = apply_retention_policy([safety, *later], DEFAULT_POLICY)                         # C
    assert safety["manifest_path"] not in deleted                                              # D
    # E: the competing automatic snapshots are still thinned: newest kept, the rest go.
    assert sorted(deleted) == sorted([later[0]["manifest_path"], later[1]["manifest_path"]])


def test_newest_safety_snapshot_is_never_deleted_even_outside_every_window():
    ancient = _snap(datetime.timedelta(days=500), "pre-restore-safety", "ancient-safety")
    auto = _snap(datetime.timedelta(days=500), "auto-backup", "ancient-auto")
    assert apply_retention_policy([ancient, auto], DEFAULT_POLICY) == [auto["manifest_path"]]


def test_newest_safety_snapshot_still_occupies_its_bucket_as_before():
    """The safety snapshot keeps its bucket: an older automatic one there goes, as it always did."""
    older_auto = _snap(datetime.timedelta(minutes=50), "auto-backup", "older-auto")
    safety = _snap(datetime.timedelta(minutes=5), "pre-restore-safety", "safety")
    assert apply_retention_policy([safety, older_auto], DEFAULT_POLICY) == [older_auto["manifest_path"]]


def test_manual_backup_exemption_is_unchanged():
    manual = _snap(datetime.timedelta(minutes=5), "manual-backup", "manual")
    safety = _snap(datetime.timedelta(minutes=15), "pre-restore-safety", "safety")
    autos = [_snap(datetime.timedelta(minutes=m), "auto-backup", f"auto-{m}") for m in (20, 30)]
    deleted = apply_retention_policy([manual, safety, *autos], DEFAULT_POLICY)
    assert manual["manifest_path"] not in deleted and safety["manifest_path"] not in deleted
    # The safety snapshot is the newest non-manual one in the bucket, so it holds the
    # bucket and both older automatic snapshots go -- exactly what the old policy did.
    assert sorted(deleted) == sorted(a["manifest_path"] for a in autos)
    assert sorted(deleted) == sorted(_previous_policy([manual, safety, *autos], DEFAULT_POLICY))
    ancient_manual = _snap(datetime.timedelta(days=500), "manual-backup", "ancient-manual")
    assert apply_retention_policy([ancient_manual], DEFAULT_POLICY) == []


AGES = [datetime.timedelta(minutes=m) for m in (1, 50, 130, 300)] + [
    datetime.timedelta(hours=h) for h in (30, 200, 1000, 10000)
]


@pytest.mark.parametrize("safety_positions", [(), (0,), (1,), (2, 5), (3, 7)])
@pytest.mark.parametrize("policy", [DEFAULT_POLICY, [{"period_hours": 24, "interval_hours": 2, "slots": 1}]])
def test_only_the_newest_safety_is_pinned(safety_positions, policy):
    """UI-C21: ordinary snapshots keep the previous decision; only the newest safety is pinned."""
    reasons = ["auto-backup", "manual-backup", "auto-sync", "post-restore"]
    for combo in itertools.islice(itertools.product(reasons, repeat=len(AGES)), 0, None, 257):
        snaps = [
            _snap(age, "pre-restore-safety" if i in safety_positions else reason, f"s{i}")
            for i, (age, reason) in enumerate(zip(AGES, combo))
        ]
        now_deleted = apply_retention_policy(snaps, policy)
        before = _previous_policy(snaps, policy)
        safeties = [s for s in snaps if s["reason"] == "pre-restore-safety"]
        pinned = max(
            safeties,
            key=lambda s: (s["created_at"], os.path.basename(s["manifest_path"])),
            default=None,
        )
        pinned_path = pinned["manifest_path"] if pinned else None
        assert pinned_path not in now_deleted, combo
        assert now_deleted == [p for p in before if p != pinned_path], (combo, safety_positions)
        non_safety = {s["manifest_path"] for s in snaps if s["reason"] != "pre-restore-safety"}
        assert [p for p in now_deleted if p in non_safety] == [p for p in before if p in non_safety], (
            combo,
            safety_positions,
        )


# ------------------------------------------------ end-to-end: restore -> scheduled cycle


def _manifests(directory: Path) -> dict[str, str]:
    return {
        path.name: json.load(open(path, encoding="utf-8")).get("reason")
        for path in (directory / "snapshots").glob("*.json")
    }


def test_the_first_scheduled_backup_after_a_restore_keeps_the_undo_point(backup_env, admin_client, events):
    import app.db as app_db
    from app.db_maintenance import create_database_snapshot

    backup_env.configure(cloud_folder=False, google=False, onedrive=False)
    with backup_env.main.app.app_context():
        earlier_auto = create_database_snapshot(app_db.DATABASE, str(backup_env.local_dir), reason="auto-backup", origin="local")
        source = create_database_snapshot(app_db.DATABASE, str(backup_env.local_dir), reason="manual-backup", origin="local")
    response = admin_client.post("/admin/banco-dados/restaurar", data={"manifest_path": source["manifest_path"]})
    assert response.status_code in (302, 303)
    safety = [name for name, reason in _manifests(backup_env.local_dir).items() if reason == "pre-restore-safety"]
    assert len(safety) == 1

    with backup_env.main.app.app_context():
        outcome = automatic.run_automatic_cycle(trigger="scheduled")
    assert outcome["ran"] is True

    after = _manifests(backup_env.local_dir)
    assert safety[0] in after, "the restore's undo point was pruned by the scheduled backup"
    assert Path(source["manifest_path"]).name in after  # manual exemption unchanged
    assert Path(earlier_auto["manifest_path"]).name not in after  # ordinary thinning unchanged
    assert list(after.values()).count("auto-backup") == 1  # the new automatic snapshot is the bucket's keeper
