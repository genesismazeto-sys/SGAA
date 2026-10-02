import hashlib
import logging
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


# ---- Runtime root (created unconditionally before any module import) ----
PYTEST_RUNTIME_ROOT = Path(tempfile.mkdtemp(prefix="sgaa_pytest_runtime_"))
_SESSION_TOKEN = secrets.token_hex(16)
_SESSION_MARKER = PYTEST_RUNTIME_ROOT / f".sgaa_session_{_SESSION_TOKEN}"
_SESSION_MARKER.write_text(_SESSION_TOKEN)

# Route all runtime paths into PYTEST_RUNTIME_ROOT unconditionally.
os.environ["APP_DATABASE"] = str(PYTEST_RUNTIME_ROOT / ".pytest_app_database.db")
os.environ["APP_UPLOAD_FOLDER"] = str(PYTEST_RUNTIME_ROOT / "uploads")
os.environ["APP_DOCUMENTOS_ALUNOS_FOLDER"] = str(PYTEST_RUNTIME_ROOT / "documentos_alunos")
os.environ["APP_LOCAL_BACKUP_DIR"] = str(PYTEST_RUNTIME_ROOT / "backups" / "local")
os.environ["APP_CLOUD_BACKUP_DIR"] = str(PYTEST_RUNTIME_ROOT / "backups" / "cloud")
os.environ["APP_LOG_DIR"] = str(PYTEST_RUNTIME_ROOT / "logs")

os.environ.setdefault("APP_ENV", "testing")
os.environ.setdefault("APP_BOOTSTRAP_DEFAULT_ADMIN", "1")
os.environ.setdefault("APP_BOOTSTRAP_ADMIN_PASSWORD", "admin123")
os.environ.setdefault("DISABLE_CSRF", "1")
os.environ.setdefault(
    "APP_SECRET_KEY",
    "test-secret-key-for-pytest-only-do-not-use-anywhere-else-1234567890",
)

# Root administrator identity and break-glass credential are configuration.
# Assigned (not setdefault) so a developer's .env or shell can never leak the
# real values into a test run: main's load_dotenv never overrides a set value.
from werkzeug.security import generate_password_hash  # noqa: E402

from tests.root_admin_test_config import (  # noqa: E402
    TEST_ROOT_ADMIN_EMAIL,
    TEST_ROOT_MASTER_KEY,
)

os.environ["APP_BOOTSTRAP_ADMIN_EMAIL"] = TEST_ROOT_ADMIN_EMAIL
os.environ["APP_ROOT_MASTER_KEY_HASH"] = generate_password_hash(
    TEST_ROOT_MASTER_KEY, method="pbkdf2:sha256:600000"
)

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = Path(TESTS_DIR).parent
PROJECT_ROOT_PATH = PROJECT_ROOT


# ---- Canonical project-root baseline (captured before any test writes) ----

_CANONICAL_SCOPES: list[tuple[str, bool]] = [
    ("database.db", True),
    ("database.db-wal", True),
    ("database.db-shm", True),
    ("uploads", False),
    ("documentos_alunos", False),
    ("backups", False),
    ("logs", False),
]
# Pytest owns .pytest_cache and may hold active, unreadable temporary files
# there while this manifest is evaluated.  It is intentionally excluded from
# project/runtime custody; every real runtime scope above remains protected.

# SQLite sidecars of the canonical database.  They appear and disappear around
# ordinary opens -- a read-only open can leave a zero-length -wal and a -shm
# behind, and a read-write open that writes nothing deletes both on clean
# close -- so their *presence* is not evidence of a mutation.  Only committed
# frames in the WAL are; a WAL that holds them is an uncheckpointed canonical
# write and is never tolerated (see _wal_has_committed_frames).  The -shm file
# is a coordination index that stores no database content of its own, so its
# bytes are never compared; it can never hide what the WAL comparison catches.
_WAL_SCOPE = "database.db-wal"
_SHM_SCOPE = "database.db-shm"
_WAL_HEADER_BYTES = 32
_WAL_FRAME_HEADER_BYTES = 24
_WAL_MAGICS = (0x377F0682, 0x377F0683)


def _wal_has_committed_frames(wal_path) -> bool:
    """True when the WAL file holds at least one committed frame.

    The ``database size after commit`` field of a frame header is non-zero
    exactly on commit frames, so a WAL with only a header (<= 32 bytes) or
    only uncommitted frames carries no logical database change.  Anything
    unreadable or not shaped like a WAL is treated as suspicious, never as
    benign.
    """
    try:
        size = os.path.getsize(wal_path)
        if size <= _WAL_HEADER_BYTES:
            return False
        with open(wal_path, "rb") as handle:
            header = handle.read(_WAL_HEADER_BYTES)
            if len(header) < _WAL_HEADER_BYTES:
                return False
            magic = int.from_bytes(header[0:4], "big")
            if magic not in _WAL_MAGICS:
                return True
            page_size = int.from_bytes(header[8:12], "big")
            if page_size == 1:
                page_size = 65536
            if page_size < 512 or page_size > 65536:
                return True
            offset = _WAL_HEADER_BYTES
            while offset + _WAL_FRAME_HEADER_BYTES <= size:
                handle.seek(offset)
                frame_header = handle.read(_WAL_FRAME_HEADER_BYTES)
                committed_size = int.from_bytes(frame_header[4:8], "big")
                if committed_size != 0:
                    return True
                offset += _WAL_FRAME_HEADER_BYTES + page_size
            return False
    except OSError:
        return True

# Known external writer, not pytest: the installed UI-C13 Windows scheduled
# task ("SGAA - Backup automatico") appends to <repo>/logs/backup-automatico.log
# every five minutes and rotates it (app.backup.automatic.configure_run_log:
# RotatingFileHandler, backupCount=3), independently of any test run -- pytest
# itself logs under PYTEST_RUNTIME_ROOT.  Only that file family is left out of
# the byte comparison; its identity (name -> inode) is still recorded, and the
# logs/ directory's own mtime is forgiven only when that identity changed (the
# task created or rotated its file).  Every other entry -- app.log, any new file
# or directory -- is compared exactly as before.
_EXTERNAL_WRITER_FILES: dict[str, frozenset[str]] = {
    "logs": frozenset(
        ["backup-automatico.log"] + [f"backup-automatico.log.{n}" for n in range(1, 4)]
    ),
}


def _compute_manifest(root):
    root = Path(root)
    manifest: dict[str, dict] = {}
    for scope_path, is_file in _CANONICAL_SCOPES:
        target = root / scope_path
        entry: dict = {"exists": target.exists()}
        if not target.exists():
            manifest[scope_path] = entry
            continue
        st = target.stat()
        entry["mtime_ns"] = st.st_mtime_ns
        if is_file or target.is_file():
            entry["type"] = "file"
            entry["size"] = st.st_size
            entry["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
            if scope_path == _WAL_SCOPE:
                entry["committed_write"] = _wal_has_committed_frames(target)
        elif target.is_dir():
            entry["type"] = "dir"
            external = _EXTERNAL_WRITER_FILES.get(scope_path, frozenset())
            identity: dict[str, int] = {}
            children: dict[str, dict] = {}
            for dirpath, dirnames, filenames in sorted(os.walk(str(target))):
                for dn in sorted(dirnames):
                    dpath = os.path.join(dirpath, dn)
                    rel = os.path.relpath(dpath, str(target)).replace(os.sep, "/")
                    d_st = os.stat(dpath)
                    children[rel] = {"type": "dir", "mtime_ns": d_st.st_mtime_ns}
                for fn in sorted(filenames):
                    fpath = os.path.join(dirpath, fn)
                    rel = os.path.relpath(fpath, str(target)).replace(os.sep, "/")
                    if rel in external:
                        identity[rel] = os.stat(fpath).st_ino
                        continue
                    f_st = os.stat(fpath)
                    with open(fpath, "rb") as fh_c:
                        data = fh_c.read()
                    children[rel] = {
                        "type": "file",
                        "size": f_st.st_size,
                        "mtime_ns": f_st.st_mtime_ns,
                        "sha256": hashlib.sha256(data).hexdigest(),
                    }
            entry["children"] = children
            if external:
                entry["external_writer"] = identity
        manifest[scope_path] = entry
    return manifest


_CANONICAL_BASELINE = _compute_manifest(PROJECT_ROOT)


def _custody_view(manifest, rotated_scopes):
    """The manifest as compared: external-writer identity is evidence, not state."""
    view = {}
    for scope, entry in manifest.items():
        entry = {k: v for k, v in entry.items() if k != "external_writer"}
        if scope in rotated_scopes:
            entry.pop("mtime_ns", None)
            # The writer's first run may create the directory itself; one that
            # holds nothing but the writer's own files counts as absent.
            if entry.get("type") == "dir" and not entry.get("children"):
                entry = {"exists": False}
        view[scope] = entry
    return view


def _sidecar_difference_is_benign(scope, after):
    """True when this sidecar delta cannot hide a canonical write.

    - ``-shm`` is a coordination index; it stores no database content.  A WAL
      that does hold content is compared -- and failed -- on its own scope.
    - ``-wal`` is benign when it is gone (any committed frame would have
      changed ``database.db``, compared separately) or when it holds no
      committed frame.  A WAL with committed frames is an uncheckpointed
      canonical write and is never benign.
    """
    if scope == _SHM_SCOPE:
        return True
    if scope == _WAL_SCOPE:
        if not after.get("exists"):
            return True
        if not after.get("committed_write"):
            return True
    return False


def _custody_differences(before_manifest, after_manifest):
    """Scopes whose custody changed between two manifests, as report lines."""
    rotated = {
        scope
        for scope in _EXTERNAL_WRITER_FILES
        if (before_manifest.get(scope) or {}).get("external_writer")
        != (after_manifest.get(scope) or {}).get("external_writer")
    }
    before_view = _custody_view(before_manifest, rotated)
    after_view = _custody_view(after_manifest, rotated)
    diffs = []
    for key in sorted(before_view):
        before = before_view[key]
        after = after_view.get(key)
        if before == after:
            continue
        if _sidecar_difference_is_benign(key, after or {}):
            continue
        report = f"  {key}:\n    before={before}\n    after ={after}"
        if key == _WAL_SCOPE and (after or {}).get("committed_write"):
            report += (
                "\n    -> uncheckpointed canonical write: the WAL holds committed"
                " frames; a read-only open leaves at most a zero-length WAL."
            )
        diffs.append(report)
    return diffs


# ---- External-writer diagnosis (actionable custody failures) --------------
#
# The canonical runtime and its launcher own logs/app.log and database.db; the
# automatic backup scheduler (Windows task) owns only its run log, which is
# the single narrow exemption.  When a failure happens, name the writer class
# and the required pre-suite state instead of only printing a diff.

_OPERATIONAL_WRITERS = (
    (
        "app.backup.sync",
        "automatic backup scheduler (run-log family is the only exempt path;"
        " canonical database access is read-only)",
    ),
    (
        "app.startup_preflight",
        "startup preflight (writes logs/app.log through the runtime logger)",
    ),
    ("main.py", "canonical SGAA runtime (writes logs/app.log and database.db)"),
    ("run_acceptance.bat", "acceptance runtime launcher (uses its own APP_DATABASE)"),
    ("run.bat", "canonical SGAA launcher"),
)

_RUNTIME_PORT = 5000


def _runtime_port_active(port=_RUNTIME_PORT, timeout=0.25):
    """True when something is listening on SGAA's single application port."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def _probe_operational_processes():
    """(pid, command line) for live processes; Windows-only, failure path only."""
    if os.name != "nt":
        return []
    script = (
        "$OutputEncoding=[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
        "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine } | "
        "ForEach-Object { $_.ProcessId.ToString() + \"`t\" + ($_.CommandLine -replace '\\s+', ' ') }"
    )
    try:
        completed = subprocess.run(
            [
                "powershell",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                script,
            ],
            capture_output=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    processes = []
    for raw in completed.stdout.decode("utf-8", errors="replace").splitlines():
        pid, _, cmdline = raw.partition("\t")
        pid = pid.strip()
        cmdline = cmdline.strip()
        if pid and cmdline:
            processes.append((pid, cmdline))
    return processes


def _describe_operational_processes(processes):
    described = []
    for pid, cmdline in processes:
        for token, label in _OPERATIONAL_WRITERS:
            if token in cmdline:
                described.append(f"  pid {pid}: {label}")
                described.append(f"    {cmdline}")
                break
    return described


def _custody_failure_message(before_manifest, after_manifest, *, process_probe=None, port_probe=None):
    """The full, actionable teardown report; empty string when custody holds."""
    diffs = _custody_differences(before_manifest, after_manifest)
    if not diffs:
        return ""
    scopes = {line.split(":", 1)[0].strip() for line in diffs}
    lines = ["Project root changed during test execution:", *diffs]
    lines.append("")
    lines.append("External writer diagnosis:")
    if "logs" in scopes:
        lines.append(
            "  logs/app.log and its rotations are written by the canonical SGAA"
            " runtime (run.bat / python main.py) and by its startup preflight;"
            " pytest routes every APP_* path, including APP_LOG_DIR, into its own"
            " temporary runtime root, so a test can never be the writer."
        )
        lines.append(
            "  The automatic backup scheduler may run during pytest; only its"
            " run-log family (backup-automatico.log and rotations) is exempt,"
            " accepted by file identity rather than broad *.log matching."
        )
    if scopes & {"database.db", _WAL_SCOPE, _SHM_SCOPE}:
        lines.append(
            "  Canonical business data changed. A pytest run must never tolerate"
            " this; the exemption above cannot hide it and is not extended here."
        )
    if _WAL_SCOPE in scopes:
        lines.append(
            "  A database.db-wal with committed frames is an uncheckpointed"
            " canonical write, not a transient sidecar."
        )
    lines.append(
        "  Supported full-suite state: stop the canonical SGAA runtime before"
        " `python -m pytest -q`; the automatic backup scheduler may stay enabled."
    )
    report_port = port_probe or _runtime_port_active
    lines.append(
        "  Port 5000 now: "
        + ("LISTENING (a runtime appears active)" if report_port() else "free")
        + "."
    )
    report_processes = process_probe or _probe_operational_processes
    active = _describe_operational_processes(report_processes())
    if active:
        lines.append("  Operational processes detected now:")
        lines.extend(active)
    else:
        lines.append(
            "  No operational writer process detected now; one was active during"
            " the run and has exited. Inspect the tail of logs/app.log and the"
            " automatic backup task history."
        )
    return "\n".join(lines)


def assert_canonical_root_unchanged():
    message = _custody_failure_message(
        _CANONICAL_BASELINE, _compute_manifest(PROJECT_ROOT)
    )
    if message:
        raise AssertionError(message)


# ---- Ownership-proved runtime root cleanup ----


def _remove_owned_runtime_root(root, marker_token):
    # Check symlink on original path BEFORE resolution (finding 1)
    original_root = os.path.abspath(str(root))
    if os.path.islink(original_root):
        raise RuntimeError(f"Refusing to remove symlink owned root: {original_root}")
    root = os.path.realpath(original_root)
    if not os.path.isdir(root):
        return
    parent = os.path.realpath(os.path.dirname(root))
    system_temp = os.path.realpath(tempfile.gettempdir())
    if os.path.normcase(parent) != os.path.normcase(system_temp):
        raise RuntimeError(
            f"Refusing to remove {root}: parent {parent} != system temp {system_temp}"
        )
    basename = os.path.basename(root)
    if not basename.startswith("sgaa_pytest_runtime_"):
        raise RuntimeError(
            f"Refusing to remove {root}: basename does not start with 'sgaa_pytest_runtime_'"
        )
    marker_path = os.path.join(root, f".sgaa_session_{marker_token}")
    if not os.path.exists(marker_path):
        raise RuntimeError(
            f"Refusing to remove {root}: marker .sgaa_session_{marker_token} not found"
        )
    if os.path.islink(marker_path):
        raise RuntimeError(
            f"Refusing to remove {root}: marker is a symlink"
        )
    if not os.path.isfile(marker_path):
        raise RuntimeError(
            f"Refusing to remove {root}: marker is not a regular file"
        )
    with open(marker_path, "r", encoding="utf-8") as fh_m:
        actual = fh_m.read()
    if actual != marker_token:
        raise RuntimeError(
            f"Refusing to remove {root}: marker text mismatch"
        )
    shutil.rmtree(root)


# ---- Per-test log isolation (under owned session root, finding 4) ----


@pytest.fixture(autouse=True)
def _isolate_real_log_writes(monkeypatch):
    main_module = sys.modules.get("main")
    if main_module is None:
        import main as main_module

    per_test = PYTEST_RUNTIME_ROOT / "per_test" / secrets.token_hex(8)
    per_test.mkdir(parents=True, exist_ok=True)
    temp_upload_dir = per_test / "uploads"
    temp_documents_dir = per_test / "documentos_alunos"
    temp_local_backup_dir = per_test / "backups" / "local"
    temp_cloud_backup_dir = per_test / "backups" / "cloud"
    for path in (temp_upload_dir, temp_documents_dir, temp_local_backup_dir, temp_cloud_backup_dir):
        path.mkdir(parents=True, exist_ok=True)

    log_dir = per_test / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    temp_app_log = os.path.join(str(log_dir), "app.log")
    temp_handler = logging.FileHandler(temp_app_log, encoding="utf-8", delay=True)
    flask_app = getattr(main_module, "app", None)
    candidate_loggers = [logging.getLogger(), main_module.logger]
    if flask_app is not None:
        candidate_loggers.append(flask_app.logger)

    original_upload_folder = main_module.app.config.get("UPLOAD_FOLDER")
    original_documents_folder = main_module.app.config.get("DOCUMENTOS_ALUNOS_FOLDER")
    original_local_backup_dir = main_module.app.config.get("LOCAL_BACKUP_DIR")
    original_cloud_backup_dir = main_module.app.config.get("CLOUD_BACKUP_DIR")

    monkeypatch.setenv("APP_UPLOAD_FOLDER", str(temp_upload_dir))
    monkeypatch.setenv("APP_DOCUMENTOS_ALUNOS_FOLDER", str(temp_documents_dir))
    monkeypatch.setenv("APP_LOCAL_BACKUP_DIR", str(temp_local_backup_dir))
    monkeypatch.setenv("APP_CLOUD_BACKUP_DIR", str(temp_cloud_backup_dir))
    monkeypatch.setenv("APP_LOG_DIR", str(log_dir))
    main_module.app.config["UPLOAD_FOLDER"] = str(temp_upload_dir)
    main_module.app.config["DOCUMENTOS_ALUNOS_FOLDER"] = str(temp_documents_dir)
    main_module.app.config["LOCAL_BACKUP_DIR"] = str(temp_local_backup_dir)
    main_module.app.config["CLOUD_BACKUP_DIR"] = str(temp_cloud_backup_dir)

    restore = []
    seen_ids = set()
    for lg in candidate_loggers:
        if lg is None or id(lg) in seen_ids:
            continue
        seen_ids.add(id(lg))
        original_handlers = list(lg.handlers)
        if any(isinstance(h, logging.FileHandler) for h in original_handlers):
            kept = [h for h in original_handlers if not isinstance(h, logging.FileHandler)]
            lg.handlers = kept + [temp_handler]
            restore.append((lg, original_handlers))

    try:
        yield
    finally:
        for lg, original_handlers in restore:
            lg.handlers = original_handlers
        main_module.app.config["UPLOAD_FOLDER"] = original_upload_folder
        main_module.app.config["DOCUMENTOS_ALUNOS_FOLDER"] = original_documents_folder
        main_module.app.config["LOCAL_BACKUP_DIR"] = original_local_backup_dir
        main_module.app.config["CLOUD_BACKUP_DIR"] = original_cloud_backup_dir
        temp_handler.close()


# ---- Canonical pytest session database bootstrap (C4 Phase-C harness repair) ----

# C4 closed the request-time lazy creation of mensagens_editaveis (F2), so the
# table exists only after the canonical init_db bootstrap.  The shared pytest
# runtime DB must therefore pass through init_db exactly once per session, after
# APP_DATABASE redirection is final and before any test can dispatch a request
# through main.app.  The bootstrap targets app.db.init_db directly (the
# canonical DB initializer) so the main.init_db caller ratchet stays at 75 and
# no request-time lazy repair is ever needed.
@pytest.fixture(scope="session", autouse=True)
def _bootstrap_session_database():
    import app.db as app_db
    import main

    runtime_db = Path(os.environ["APP_DATABASE"]).resolve()
    assert runtime_db.is_relative_to(PYTEST_RUNTIME_ROOT.resolve()), (
        f"session bootstrap must target the pytest runtime root only: {runtime_db}"
    )
    with main.app.app_context():
        app_db.init_db()
    yield


# ---- Session hooks ----


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    """Route pytest's own cache under the session-owned runtime root."""
    config._inicache["cache_dir"] = str(PYTEST_RUNTIME_ROOT / ".pytest_cache")
    if _runtime_port_active():
        config.issue_config_time_warning(
            UserWarning(
                "Port 5000 is LISTENING: the canonical SGAA runtime appears"
                " active. The supported full-suite state requires it stopped"
                " before `python -m pytest -q` (it writes logs/app.log and"
                " database.db); the automatic backup scheduler may stay enabled."
            ),
            stacklevel=1,
        )


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    """Collect all mandatory teardown errors, always attempt root cleanup (finding 3)."""
    errors: list[Exception] = []

    main_module = sys.modules.get("main")
    if main_module is not None:
        candidate_loggers = [logging.getLogger(), getattr(main_module, "logger", None)]
        app_obj = getattr(main_module, "app", None)
        if app_obj is not None:
            candidate_loggers.append(getattr(app_obj, "logger", None))
        seen = set()
        for lg in candidate_loggers:
            if lg is None or id(lg) in seen:
                continue
            seen.add(id(lg))
            for handler in list(lg.handlers):
                if isinstance(handler, logging.FileHandler):
                    try:
                        handler.close()
                    except Exception as exc:
                        errors.append(exc)
                    try:
                        lg.removeHandler(handler)
                    except Exception as exc:
                        errors.append(exc)
        if hasattr(main_module, "app") and hasattr(main_module.app, "app_context"):
            try:
                with main_module.app.app_context():
                    g_mod = getattr(main_module, "g", None)
                    if g_mod is not None:
                        db = getattr(g_mod, "db", None)
                        if db is not None:
                            db.close()
                            g_mod.pop("db", None)
            except Exception as exc:
                errors.append(exc)

    try:
        assert_canonical_root_unchanged()
    except Exception as exc:
        errors.append(exc)

    try:
        _remove_owned_runtime_root(PYTEST_RUNTIME_ROOT, _SESSION_TOKEN)
    except Exception as exc:
        errors.append(exc)

    if errors:
        if len(errors) == 1:
            raise errors[0]
        raise ExceptionGroup("pytest_sessionfinish errors", errors)


# ---- pytest options ----


def pytest_addoption(parser):
    csrf_group = parser.getgroup("csrf-snapshots")
    csrf_group.addoption(
        "--update-csrf-snapshots",
        action="store_true",
        default=False,
        help="Update CSRF inventory canonical snapshots (shadow_off / shadow_on)",
    )
    visual_group = parser.getgroup("visual-regression")
    visual_group.addoption(
        "--visual",
        action="store_true",
        default=False,
        help=(
            "Run the design-system visual regression gate (needs Playwright and a "
            "downloaded browser; minutes, not seconds). Skipped by default."
        ),
    )
