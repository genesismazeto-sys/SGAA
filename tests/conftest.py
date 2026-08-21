import hashlib
import logging
import os
import secrets
import shutil
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

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = Path(TESTS_DIR).parent
PROJECT_ROOT_PATH = PROJECT_ROOT


# ---- Canonical project-root baseline (captured before any test writes) ----

_CANONICAL_SCOPES: list[tuple[str, bool]] = [
    ("database.db", True),
    ("uploads", False),
    ("documentos_alunos", False),
    ("backups", False),
    ("logs", False),
]
# Pytest owns .pytest_cache and may hold active, unreadable temporary files
# there while this manifest is evaluated.  It is intentionally excluded from
# project/runtime custody; every real runtime scope above remains protected.


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
        elif target.is_dir():
            entry["type"] = "dir"
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
        manifest[scope_path] = entry
    return manifest


_CANONICAL_BASELINE = _compute_manifest(PROJECT_ROOT)


def assert_canonical_root_unchanged():
    current = _compute_manifest(PROJECT_ROOT)
    if current != _CANONICAL_BASELINE:
        diffs = []
        for key in sorted(_CANONICAL_BASELINE):
            before = _CANONICAL_BASELINE[key]
            after = current.get(key)
            if before != after:
                diffs.append(f"  {key}:\n    before={before}\n    after ={after}")
        raise AssertionError(
            "Project root changed during test execution:\n" + "\n".join(diffs)
        )


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
