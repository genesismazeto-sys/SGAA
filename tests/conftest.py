import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest


TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
TEST_DATABASE = os.path.join(TESTS_DIR, ".pytest_app_database.db")
PROJECT_ROOT = Path(TESTS_DIR).parent
PYTEST_RUNTIME_ROOT = Path(tempfile.mkdtemp(prefix="sgaa_pytest_runtime_"))
PYTEST_RUNTIME_DOCUMENTOS = PYTEST_RUNTIME_ROOT / "documentos_alunos"
PYTEST_RUNTIME_LOCAL_BACKUPS = PYTEST_RUNTIME_ROOT / "backups" / "local"
PYTEST_RUNTIME_CLOUD_BACKUPS = PYTEST_RUNTIME_ROOT / "backups" / "cloud"
for _path in (PYTEST_RUNTIME_DOCUMENTOS, PYTEST_RUNTIME_LOCAL_BACKUPS, PYTEST_RUNTIME_CLOUD_BACKUPS):
    _path.mkdir(parents=True, exist_ok=True)


# Set environment BEFORE main.py is imported by any test module.
os.environ["APP_DATABASE"] = TEST_DATABASE
os.environ.setdefault("APP_ENV", "testing")
os.environ.setdefault("APP_BOOTSTRAP_DEFAULT_ADMIN", "1")
os.environ.setdefault("APP_BOOTSTRAP_ADMIN_PASSWORD", "admin123")
os.environ.setdefault("DISABLE_CSRF", "1")
os.environ.setdefault("APP_DOCUMENTOS_ALUNOS_FOLDER", str(PYTEST_RUNTIME_DOCUMENTOS))
os.environ.setdefault("APP_LOCAL_BACKUP_DIR", str(PYTEST_RUNTIME_LOCAL_BACKUPS))
os.environ.setdefault("APP_CLOUD_BACKUP_DIR", str(PYTEST_RUNTIME_CLOUD_BACKUPS))
os.environ.setdefault(
    "APP_SECRET_KEY",
    "test-secret-key-for-pytest-only-do-not-use-anywhere-else-1234567890",
)


def _cleanup_root_output_artifacts() -> None:
    # Safety guard: cleanup only in the dedicated clean baseline workspace.
    if PROJECT_ROOT.name != "SGAA_clean_baseline":
        return
    for name in ("backups", "logs", "uploads", "documentos_alunos"):
        target = PROJECT_ROOT / name
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)


@pytest.fixture(autouse=True)
def _isolate_real_log_writes(tmp_path_factory, monkeypatch):
    # When SGAA_VERSIONED_RESOLVER_SHADOW_READ is enabled, logger writes may land
    # in logs/app.log and logs/versioned_shadow_reads.log. Keep these writes in
    # per-test temp paths and keep upload/docs/backup runtime paths isolated too.
    main_module = sys.modules.get("main")
    if main_module is None:
        import main as main_module

    runtime_dir = tmp_path_factory.mktemp("isolated_runtime")
    temp_upload_dir = runtime_dir / "uploads"
    temp_documents_dir = runtime_dir / "documentos_alunos"
    temp_local_backup_dir = runtime_dir / "backups" / "local"
    temp_cloud_backup_dir = runtime_dir / "backups" / "cloud"
    for path in (temp_upload_dir, temp_documents_dir, temp_local_backup_dir, temp_cloud_backup_dir):
        path.mkdir(parents=True, exist_ok=True)

    log_dir = tmp_path_factory.mktemp("isolated_logs")
    dedicated_log = os.path.join(str(log_dir), "versioned_shadow_reads.log")
    monkeypatch.setattr(
        main_module,
        "_versioned_shadow_read_dedicated_log_path",
        lambda: dedicated_log,
    )

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

    monkeypatch.setenv("APP_DOCUMENTOS_ALUNOS_FOLDER", str(temp_documents_dir))
    monkeypatch.setenv("APP_LOCAL_BACKUP_DIR", str(temp_local_backup_dir))
    monkeypatch.setenv("APP_CLOUD_BACKUP_DIR", str(temp_cloud_backup_dir))
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
        try:
            temp_handler.close()
        except Exception:
            pass


def pytest_sessionstart(session):
    _cleanup_root_output_artifacts()
    if os.path.exists(TEST_DATABASE):
        os.remove(TEST_DATABASE)


def pytest_sessionfinish(session, exitstatus):
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
                    except Exception:
                        pass
                    try:
                        lg.removeHandler(handler)
                    except Exception:
                        pass
        try:
            with main_module.app.app_context():
                db = getattr(main_module.g, "db", None)
                if db is not None:
                    db.close()
                    main_module.g.pop("db", None)
        except Exception:
            pass

    if os.path.exists(TEST_DATABASE):
        try:
            os.remove(TEST_DATABASE)
        except OSError:
            pass

    _cleanup_root_output_artifacts()
    try:
        shutil.rmtree(PYTEST_RUNTIME_ROOT, ignore_errors=True)
    except Exception:
        pass
