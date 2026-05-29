"""Unit tests for apply_retention_policy in app.db_maintenance."""
import datetime
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from app.db_maintenance import apply_retention_policy

UTC = datetime.timezone.utc


def _snap(created_at: datetime.datetime, reason: str = "auto-sync", idx: int = 0) -> dict:
    ts = created_at.strftime("%Y%m%d-%H%M%S")
    mp = f"/backups/snapshots/db-{ts}-{idx:04d}.json"
    return {
        "manifest_path": mp,
        "created_at": created_at.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "reason": reason,
        "origin": "local",
    }


def _policy(period_hours: float, interval_hours: float, slots: int) -> list[dict]:
    return [{"period_hours": period_hours, "interval_hours": interval_hours, "slots": slots}]


# ---------------------------------------------------------------------------
# empty window
# ---------------------------------------------------------------------------

def test_empty_snapshots_returns_nothing():
    policy = _policy(24, 2, 12)
    assert apply_retention_policy([], policy) == []


def test_all_snapshots_outside_window_are_deleted():
    now = datetime.datetime.now(UTC)
    snaps = [_snap(now - datetime.timedelta(hours=50), idx=i) for i in range(3)]
    result = apply_retention_policy(snaps, _policy(24, 2, 12))
    assert sorted(result) == sorted(s["manifest_path"] for s in snaps)


# ---------------------------------------------------------------------------
# exact slots — nothing gets deleted
# ---------------------------------------------------------------------------

def test_exact_slots_keeps_all():
    now = datetime.datetime.now(UTC)
    # 3 snapshots, each in its own 2h bucket within last 24h, slots=3
    snaps = [
        _snap(now - datetime.timedelta(hours=1), idx=0),   # bucket 0
        _snap(now - datetime.timedelta(hours=3), idx=1),   # bucket 1
        _snap(now - datetime.timedelta(hours=5), idx=2),   # bucket 2
    ]
    result = apply_retention_policy(snaps, _policy(24, 2, 3))
    assert result == []


# ---------------------------------------------------------------------------
# overflow — oldest buckets get dropped
# ---------------------------------------------------------------------------

def test_overflow_drops_oldest_buckets():
    now = datetime.datetime.now(UTC)
    # 4 unique buckets (2h each), but only 2 slots
    snaps = [
        _snap(now - datetime.timedelta(hours=1), idx=0),   # bucket 0 → kept
        _snap(now - datetime.timedelta(hours=3), idx=1),   # bucket 1 → kept
        _snap(now - datetime.timedelta(hours=5), idx=2),   # bucket 2 → deleted (overflow)
        _snap(now - datetime.timedelta(hours=7), idx=3),   # bucket 3 → deleted (overflow)
    ]
    result = apply_retention_policy(snaps, _policy(24, 2, slots=2))
    deleted_paths = set(result)
    assert snaps[0]["manifest_path"] not in deleted_paths
    assert snaps[1]["manifest_path"] not in deleted_paths
    assert snaps[2]["manifest_path"] in deleted_paths
    assert snaps[3]["manifest_path"] in deleted_paths


def test_multiple_snaps_same_bucket_keeps_newest():
    now = datetime.datetime.now(UTC)
    # Two snapshots in bucket 0 (within first 2h); only the newer one should be kept
    newer = _snap(now - datetime.timedelta(minutes=30), idx=0)
    older = _snap(now - datetime.timedelta(hours=1, minutes=30), idx=1)
    result = apply_retention_policy([newer, older], _policy(24, 2, slots=1))
    assert newer["manifest_path"] not in result
    assert older["manifest_path"] in result


# ---------------------------------------------------------------------------
# manual-backup protection
# ---------------------------------------------------------------------------

def test_manual_backup_never_deleted():
    now = datetime.datetime.now(UTC)
    # A manual-backup outside all windows must NOT be deleted
    manual = _snap(now - datetime.timedelta(days=365), reason="manual-backup", idx=0)
    auto = _snap(now - datetime.timedelta(days=365), reason="auto-sync", idx=1)
    result = apply_retention_policy([manual, auto], _policy(24, 2, 12))
    assert manual["manifest_path"] not in result
    assert auto["manifest_path"] in result


def test_manual_backup_inside_window_never_deleted():
    now = datetime.datetime.now(UTC)
    manual = _snap(now - datetime.timedelta(hours=1), reason="manual-backup", idx=0)
    # Even if the slot limit would force a deletion, manual is protected
    extras = [_snap(now - datetime.timedelta(hours=2 * i + 1), idx=i + 1) for i in range(20)]
    all_snaps = [manual] + extras
    result = apply_retention_policy(all_snaps, _policy(24, 2, slots=1))
    assert manual["manifest_path"] not in result


def test_manual_backup_does_not_steal_bucket_slot():
    """A manual-backup in bucket 0 must not prevent auto snapshots in bucket 0 from being kept."""
    now = datetime.datetime.now(UTC)
    manual = _snap(now - datetime.timedelta(minutes=10), reason="manual-backup", idx=0)
    auto = _snap(now - datetime.timedelta(minutes=30), reason="auto-sync", idx=1)
    # Both in bucket 0 (2h window), 1 slot. Manual must not consume the slot.
    result = apply_retention_policy([manual, auto], _policy(24, 2, slots=1))
    assert manual["manifest_path"] not in result
    assert auto["manifest_path"] not in result


# ---------------------------------------------------------------------------
# multi-window GFS: snapshot kept by ANY window survives
# ---------------------------------------------------------------------------

def test_snapshot_kept_by_second_window_survives():
    now = datetime.datetime.now(UTC)
    # This snapshot is 48h old — outside the 24h window but inside the 7d window
    old_snap = _snap(now - datetime.timedelta(hours=48), idx=0)
    policy = [
        {"period_hours": 24, "interval_hours": 2, "slots": 12},
        {"period_hours": 168, "interval_hours": 24, "slots": 7},
    ]
    result = apply_retention_policy([old_snap], policy)
    assert old_snap["manifest_path"] not in result


def test_snapshot_outside_all_windows_deleted():
    now = datetime.datetime.now(UTC)
    very_old = _snap(now - datetime.timedelta(days=400), idx=0)
    policy = [
        {"period_hours": 24, "interval_hours": 2, "slots": 12},
        {"period_hours": 168, "interval_hours": 24, "slots": 7},
        {"period_hours": 672, "interval_hours": 168, "slots": 4},
        {"period_hours": 8760, "interval_hours": 730, "slots": 12},
    ]
    result = apply_retention_policy([very_old], policy)
    assert very_old["manifest_path"] in result


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------

def test_invalid_created_at_is_skipped():
    bad = {"manifest_path": "/x/y.json", "created_at": "not-a-date", "reason": "auto-sync"}
    result = apply_retention_policy([bad], _policy(24, 2, 12))
    assert result == []


def test_zero_interval_window_is_skipped():
    now = datetime.datetime.now(UTC)
    snap = _snap(now - datetime.timedelta(hours=1), idx=0)
    # interval_hours=0 should not crash and should not keep or delete
    result = apply_retention_policy([snap], _policy(24, 0, 12))
    # With no valid window, snapshot is not kept → should be deleted
    assert snap["manifest_path"] in result


def test_missing_manifest_path_is_skipped():
    now = datetime.datetime.now(UTC)
    bad = {"manifest_path": "", "created_at": (now - datetime.timedelta(hours=50)).isoformat(), "reason": "auto-sync"}
    result = apply_retention_policy([bad], _policy(24, 2, 12))
    assert result == []
