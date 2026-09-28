"""Session custody tolerates exactly one known external writer.

``tests/conftest.py`` fingerprints the real workspace runtime scopes
(``database.db``, ``uploads``, ``documentos_alunos``, ``backups``, ``logs``) before
any test runs and asserts them unchanged at session finish -- the proof that no
test leaks into the developer's workspace (pytest routes every ``APP_*`` runtime
path, including ``APP_LOG_DIR``, into its own temp root).

The installed UI-C13 Windows scheduled task appends to
``<repo>/logs/backup-automatico.log`` every five minutes and rotates it,
independently of pytest. Only that file family is left out of the byte
comparison; its identity is recorded instead, and the ``logs/`` directory's own
mtime is forgiven only when that identity changed (the task created or rotated
its file). Everything else in ``logs/`` -- ``app.log``, any new file -- is
compared exactly as before. No test touches the real scheduler or the real
operational log: every scenario below runs on a disposable root.
"""

from __future__ import annotations

import inspect
import os
import re
import time
from pathlib import Path

import pytest

from tests import conftest
from tests.conftest import _compute_manifest, _custody_differences

FAMILY = "backup-automatico.log"


@pytest.fixture
def root(tmp_path):
    (tmp_path / "database.db").write_bytes(b"sqlite")
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "app.log").write_text("app line\n", encoding="utf-8")
    (logs / FAMILY).write_text("wake 1\n", encoding="utf-8")
    time.sleep(0.05)
    return tmp_path


def _append(path: Path, text: str) -> None:
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(text)


def _rotate(logs: Path) -> None:
    """What RotatingFileHandler(backupCount=3).doRollover does."""
    for n in (2, 1):
        source = logs / f"{FAMILY}.{n}"
        if source.exists():
            os.replace(source, logs / f"{FAMILY}.{n + 1}")
    os.replace(logs / FAMILY, logs / f"{FAMILY}.1")
    (logs / FAMILY).write_text("fresh after rollover\n", encoding="utf-8")


# ------------------------------------------------------------------ A: tolerated


def test_a_scheduler_appends_do_not_trip_the_guard(root):
    before = _compute_manifest(root)
    for wake in range(3):
        _append(root / "logs" / FAMILY, f"wake {wake}\n")
    assert _custody_differences(before, _compute_manifest(root)) == []


def test_a_without_the_exclusion_the_same_append_is_caught(root, monkeypatch):
    """Control: the exclusion -- nothing else -- is what tolerates the scheduler's append."""
    monkeypatch.setattr(conftest, "_EXTERNAL_WRITER_FILES", {})
    before = _compute_manifest(root)
    _append(root / "logs" / FAMILY, "wake\n")
    diffs = _custody_differences(before, _compute_manifest(root))
    assert len(diffs) == 1 and FAMILY in diffs[0]


def test_a_scheduler_rotation_does_not_trip_the_guard(root):
    before = _compute_manifest(root)
    time.sleep(0.05)
    _rotate(root / "logs")
    _rotate(root / "logs")
    after = _compute_manifest(root)
    assert after["logs"]["mtime_ns"] != before["logs"]["mtime_ns"]  # the rotation really moved the dir mtime
    assert _custody_differences(before, after) == []


def test_a_scheduler_first_run_may_create_the_logs_directory(tmp_path):
    (tmp_path / "database.db").write_bytes(b"sqlite")
    before = _compute_manifest(tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / FAMILY).write_text("first wake\n", encoding="utf-8")
    assert _custody_differences(before, _compute_manifest(tmp_path)) == []


# ------------------------------------------------------------------ B: other logs still protected


def test_b_a_change_to_app_log_is_still_caught(root):
    before = _compute_manifest(root)
    _append(root / "logs" / FAMILY, "wake\n")
    _append(root / "logs" / "app.log", "leaked by a test\n")
    diffs = _custody_differences(before, _compute_manifest(root))
    assert len(diffs) == 1 and diffs[0].startswith("  logs:") and "app.log" in diffs[0]


def test_b_a_change_to_app_log_is_caught_even_during_a_rotation(root):
    before = _compute_manifest(root)
    time.sleep(0.05)
    _rotate(root / "logs")
    _append(root / "logs" / "app.log", "leaked by a test\n")
    assert _custody_differences(before, _compute_manifest(root))


def test_b_the_other_scopes_are_untouched_by_the_exclusion(root):
    before = _compute_manifest(root)
    (root / "database.db").write_bytes(b"sqlite changed")
    diffs = _custody_differences(before, _compute_manifest(root))
    assert len(diffs) == 1 and diffs[0].startswith("  database.db:")


# ------------------------------------------------------------------ C: new/unexpected entries still caught


@pytest.mark.parametrize(
    "name",
    ["unexpected.log", f"{FAMILY}.bak", f"{FAMILY}.4", f"other-{FAMILY}", "sub/leak.log"],
)
def test_c_a_new_file_in_logs_is_still_caught(root, name):
    before = _compute_manifest(root)
    target = root / "logs" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("unexpected\n", encoding="utf-8")
    _append(root / "logs" / FAMILY, "wake\n")
    diffs = _custody_differences(before, _compute_manifest(root))
    assert len(diffs) == 1 and diffs[0].startswith("  logs:")


def test_c_a_transient_file_is_still_caught_by_the_directory_mtime(root):
    """Previous contract: created-and-deleted still moves logs/'s own mtime."""
    before = _compute_manifest(root)
    time.sleep(0.05)
    transient = root / "logs" / "transient.log"
    transient.write_text("x", encoding="utf-8")
    transient.unlink()
    _append(root / "logs" / FAMILY, "wake\n")  # an append is not a rotation: no mtime amnesty
    after = _compute_manifest(root)
    assert after["logs"]["mtime_ns"] != before["logs"]["mtime_ns"]
    assert _custody_differences(before, after)


# ------------------------------------------------------------------ D: no scheduler handling at all


def test_d_the_guard_never_touches_the_real_scheduler_or_its_log():
    source = inspect.getsource(conftest)
    for forbidden in ("schtasks", "ScheduledTask", "task_scheduler", "Disable-", "Enable-"):
        assert forbidden not in source, forbidden
    # The real baseline simply leaves the scheduler's file out of the byte comparison.
    real_logs = conftest._CANONICAL_BASELINE.get("logs") or {}
    if real_logs.get("exists"):
        assert not any(name.startswith(FAMILY) for name in real_logs.get("children", {}))


def test_d_the_excluded_family_is_exactly_the_scheduler_run_log_and_its_rotations():
    from app.backup import automatic

    assert automatic.RUN_LOG_FILENAME == FAMILY
    backup_count = int(re.search(r"backupCount=(\d+)", inspect.getsource(automatic.configure_run_log)).group(1))
    expected = {FAMILY} | {f"{FAMILY}.{n}" for n in range(1, backup_count + 1)}
    assert conftest._EXTERNAL_WRITER_FILES == {"logs": frozenset(expected)}
