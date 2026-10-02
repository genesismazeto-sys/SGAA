"""Session custody tolerates exactly one known external writer.

``tests/conftest.py`` fingerprints the real workspace runtime scopes
(``database.db`` and its SQLite sidecars, ``uploads``, ``documentos_alunos``,
``backups``, ``logs``) before any test runs and asserts them unchanged at
session finish -- the proof that no test leaks into the developer's workspace
(pytest routes every ``APP_*`` runtime path, including ``APP_LOG_DIR``, into its
own temp root).

The installed UI-C13 Windows scheduled task appends to
``<repo>/logs/backup-automatico.log`` every five minutes and rotates it,
independently of pytest. Only that file family is left out of the byte
comparison; its identity is recorded instead, and the ``logs/`` directory's own
mtime is forgiven only when that identity changed (the task created or rotated
its file). Everything else in ``logs/`` -- ``app.log``, any new file -- is
compared exactly as before. No test touches the real scheduler or the real
operational log: every scenario below runs on a disposable root.

Sidecar policy: a zero-length ``-wal`` and a ``-shm`` left by an ordinary open
are benign (a read-only open can leave exactly those behind); a ``-wal`` that
holds committed frames is an uncheckpointed canonical write and fails. The
runtime writer that owns the real ``logs/app.log`` (``main.py``'s rotating
handler) is reproduced in a disposable root, and a custody failure names it.
"""

from __future__ import annotations

import inspect
import os
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests import conftest
from tests.conftest import _compute_manifest, _custody_differences

FAMILY = "backup-automatico.log"
WAL_SCOPE = "database.db-wal"


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


# ------------------------------------------------------------------ E: WAL/SHM


def _synthetic_wal(*, committed: bool) -> bytes:
    """A valid-looking WAL: header + two frames; only commit frames carry a db size."""
    page_size = 4096
    header = bytearray(32)
    header[0:4] = (0x377F0682).to_bytes(4, "big")
    header[4:8] = (3007000).to_bytes(4, "big")
    header[8:12] = page_size.to_bytes(4, "big")
    frames = bytearray()
    for index, db_size in enumerate((0, 2 if committed else 0)):
        frame = bytearray(24)
        frame[0:4] = (index + 1).to_bytes(4, "big")
        frame[4:8] = db_size.to_bytes(4, "big")
        frames += frame + bytes(page_size)
    return bytes(header + frames)


def test_e_committed_frame_detection_matches_the_real_sqlite_wal(root):
    (root / "database.db").unlink()
    writer = sqlite3.connect(root / "database.db")
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("CREATE TABLE t(x)")
        writer.commit()
        assert conftest._wal_has_committed_frames(root / WAL_SCOPE) is True
    finally:
        writer.close()


def test_e_a_zero_length_wal_and_shm_are_benign_sidecars(root):
    before = _compute_manifest(root)
    (root / WAL_SCOPE).write_bytes(b"")
    (root / "database.db-shm").write_bytes(bytes(32768))
    assert _custody_differences(before, _compute_manifest(root)) == []


def test_e_a_synthetic_uncommitted_wal_is_benign(root):
    before = _compute_manifest(root)
    (root / WAL_SCOPE).write_bytes(_synthetic_wal(committed=False))
    (root / "database.db-shm").write_bytes(bytes(32768))
    assert _custody_differences(before, _compute_manifest(root)) == []


def test_e_a_synthetic_committed_wal_is_caught(root):
    before = _compute_manifest(root)
    (root / WAL_SCOPE).write_bytes(_synthetic_wal(committed=True))
    after = _compute_manifest(root)
    assert after[WAL_SCOPE]["committed_write"] is True
    diffs = _custody_differences(before, after)
    assert len(diffs) == 1 and diffs[0].startswith(f"  {WAL_SCOPE}:")


def test_e_a_committed_wal_failure_message_explains_uncheckpointed_write(root):
    before = _compute_manifest(root)
    (root / WAL_SCOPE).write_bytes(_synthetic_wal(committed=True))
    message = conftest._custody_failure_message(
        before,
        _compute_manifest(root),
        process_probe=lambda: [],
        port_probe=lambda: False,
    )
    assert "uncheckpointed canonical write" in message
    assert WAL_SCOPE in message


def test_e_a_real_committed_wal_is_caught_while_the_writer_is_open(root):
    (root / "database.db").unlink()
    seed = sqlite3.connect(root / "database.db")
    seed.execute("CREATE TABLE base(x)")
    seed.commit()
    seed.close()
    before = _compute_manifest(root)
    writer = sqlite3.connect(root / "database.db")
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("PRAGMA wal_autocheckpoint=0")
    writer.execute("INSERT INTO base VALUES (1)")
    writer.commit()
    try:
        after = _compute_manifest(root)
        assert (root / WAL_SCOPE).stat().st_size > 32
        assert after[WAL_SCOPE]["committed_write"] is True
        assert any(diff.startswith(f"  {WAL_SCOPE}:") for diff in _custody_differences(before, after))
    finally:
        writer.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows read-only open leaves the sidecars")
def test_e_a_real_readonly_open_leaves_only_benign_sidecars(root):
    (root / "database.db").unlink()
    seed = sqlite3.connect(root / "database.db")
    seed.execute("PRAGMA journal_mode=WAL")
    seed.execute("CREATE TABLE t(x)")
    seed.commit()
    seed.close()
    before = _compute_manifest(root)
    conn = sqlite3.connect(f"file:{(root / 'database.db').as_posix()}?mode=ro", uri=True)
    try:
        conn.execute("PRAGMA user_version").fetchone()
    finally:
        conn.close()
    after = _compute_manifest(root)
    wal = after[WAL_SCOPE]
    if wal.get("exists"):
        assert wal["size"] == 0
        assert wal["committed_write"] is False
    assert _custody_differences(before, after) == []


def test_e_a_disappearing_benign_sidecar_is_benign(root):
    (root / WAL_SCOPE).write_bytes(b"")
    (root / "database.db-shm").write_bytes(bytes(32768))
    before = _compute_manifest(root)
    (root / WAL_SCOPE).unlink()
    (root / "database.db-shm").unlink()
    assert _custody_differences(before, _compute_manifest(root)) == []


def test_e_a_non_wal_payload_in_the_wal_slot_is_never_benign(root):
    before = _compute_manifest(root)
    (root / WAL_SCOPE).write_bytes(b"not-a-wal" * 64)
    after = _compute_manifest(root)
    assert after[WAL_SCOPE]["committed_write"] is True
    assert _custody_differences(before, after)


# ------------------------------------------------- F: app.log stays protected


def test_f_the_real_runtime_writer_appends_app_log_in_a_disposable_root(tmp_path):
    """Controlled reproduction of the historical failure: the runtime's own writer."""
    disposable = tmp_path / "runtime_root"
    (disposable / "logs").mkdir(parents=True)
    (disposable / "uploads").mkdir()
    (disposable / "documentos_alunos").mkdir()
    (disposable / "backups").mkdir()
    (disposable / "database.db").write_bytes(b"sqlite")
    before = _compute_manifest(disposable)
    code = (
        "import logging\n"
        "import main\n"
        "main.logger.info('external runtime write')\n"
        "for handler in list(logging.getLogger('main').handlers):\n"
        "    handler.flush()\n"
    )
    env = {
        **os.environ,
        "APP_ENV": "testing",
        "APP_DATABASE": str(disposable / "runtime.db"),
        "APP_LOG_DIR": str(disposable / "logs"),
        "APP_UPLOAD_FOLDER": str(disposable / "uploads"),
        "APP_DOCUMENTOS_ALUNOS_FOLDER": str(disposable / "documentos_alunos"),
        "APP_LOCAL_BACKUP_DIR": str(disposable / "backups" / "local"),
        "APP_CLOUD_BACKUP_DIR": str(disposable / "backups" / "cloud"),
    }
    completed = subprocess.run(
        [sys.executable, "-B", "-c", code],
        capture_output=True,
        timeout=180,
        cwd=str(conftest.PROJECT_ROOT),
        env=env,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    app_log = disposable / "logs" / "app.log"
    assert app_log.exists() and "external runtime write" in app_log.read_text(encoding="utf-8")
    diffs = _custody_differences(before, _compute_manifest(disposable))
    assert len(diffs) == 1 and diffs[0].startswith("  logs:") and "app.log" in diffs[0]


def test_f_an_app_log_failure_names_the_writer_and_the_supported_state(root):
    before = _compute_manifest(root)
    _append(root / "logs" / "app.log", "written by a runtime outside pytest\n")
    message = conftest._custody_failure_message(
        before,
        _compute_manifest(root),
        process_probe=lambda: [("4242", r'"C:\Python\python.exe" main.py')],
        port_probe=lambda: True,
    )
    assert "app.log" in message
    assert "canonical SGAA runtime" in message
    assert "pid 4242" in message
    assert "main.py" in message
    assert "Port 5000 now: LISTENING" in message
    assert "backup-automatico.log" in message
    assert "python -m pytest -q" in message


def test_f_an_app_log_failure_without_a_live_writer_still_explains_what_to_stop(root):
    before = _compute_manifest(root)
    _append(root / "logs" / "app.log", "exited runtime line\n")
    message = conftest._custody_failure_message(
        before,
        _compute_manifest(root),
        process_probe=lambda: [],
        port_probe=lambda: False,
    )
    assert "No operational writer process detected now" in message
    assert "logs/app.log" in message


def test_f_no_probe_runs_when_custody_holds(root):
    before = _compute_manifest(root)

    def _must_not_run(*_args, **_kwargs):
        raise AssertionError("probes must only run after a diff")

    assert (
        conftest._custody_failure_message(
            before, before, process_probe=_must_not_run, port_probe=_must_not_run
        )
        == ""
    )


def test_f_a_scheduler_append_cannot_hide_a_database_change(root):
    before = _compute_manifest(root)
    _append(root / "logs" / FAMILY, "wake\n")
    (root / "database.db").write_bytes(b"sqlite changed by a writer")
    diffs = _custody_differences(before, _compute_manifest(root))
    assert len(diffs) == 1 and diffs[0].startswith("  database.db:")


# ------------------------------------------------- G: isolation by design


def test_g_writes_under_the_pytest_runtime_root_stay_outside_custody():
    runtime_root = Path(conftest.PYTEST_RUNTIME_ROOT).resolve()
    project_root = Path(conftest.PROJECT_ROOT).resolve()
    assert not runtime_root.is_relative_to(project_root)
    probe = runtime_root / "custody_isolation_probe.tmp"
    probe.write_bytes(b"test-owned runtime data")
    try:
        assert _custody_differences(
            conftest._CANONICAL_BASELINE, _compute_manifest(conftest.PROJECT_ROOT)
        ) == []
    finally:
        probe.unlink(missing_ok=True)
