# coding: utf-8
"""PostgreSQL-readiness Unit 5-E: unsupported maintenance-operations boundary.

The backup/restore subsystem is SQLite-file specific (``sqlite3`` backup API,
``database.db`` snapshots, ZIP packaging, ``os.replace`` restore).  Under a
configured PostgreSQL backend it has no engine boundary today: a stale SQLite
file at ``app.db.DATABASE`` is snapshotted, packaged, uploaded and "restored"
while PostgreSQL is untouched, and every path reports success.

U5-E does NOT add PostgreSQL-native backup/restore.  It requires ONE canonical
capability boundary owned by the backup subsystem:

* the active backend is classified by the canonical configured-engine authority
  (``app.db.database_backend``, driven by ``app.db.DATABASE_URL``) -- never by
  re-parsing ``DATABASE_URL`` per caller, by the presence of a ``.db`` file, by
  the importability of ``psycopg``, or by opening any database;
* under PostgreSQL every SQLite file backup/restore entrypoint refuses BEFORE
  any ``sqlite3.connect``, snapshot, ZIP, upload, ``os.replace`` or ``init_db``
  and never reports success (flash category, return value or exit code);
* SQLite behaviour is unchanged.

Harness
-------
The configured backend is switched by setting ``app.db.DATABASE_URL`` to a
PostgreSQL URL (the process environment is NOT touched).  No server exists:
``app.db._connect_postgres`` is replaced by a stand-in that opens a private
SQLite COPY of the database, so request plumbing (auth, page rendering) keeps
working.  The ORIGINAL file at ``app.db.DATABASE`` is therefore the stale
SQLite database a real PostgreSQL deployment would leave behind, and every
``sqlite3.connect`` made by production code is recorded by a spy (the stand-in
uses the unpatched function, so the spy sees backup-subsystem SQLite I/O only).

Discrimination: in both arms the stale ``.db`` file exists and ``psycopg`` is
importable, so neither can stand in for the engine decision; a third arm sets
``DATABASE_URL`` only in ``os.environ`` (not the canonical module value) and
must behave as SQLite.  No network, no real PostgreSQL, canonical
``database.db`` never referenced.
"""
from __future__ import annotations

import ast
import hashlib
import logging
import os
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import url2pathname

import pytest

from app import db as app_db
from app.backup import automatic, orchestrator, sync, task_scheduler
from app.db_maintenance import create_database_snapshot
from app.text import register_human_text_sql
from app.views.admin import banco_dados as banco_dados_view
from tests.test_backup_destination_outcomes_ui_c11_c12 import (  # noqa: F401  (fixtures)
    admin_client,
    backup_env,
    events,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

#: A syntactically valid PostgreSQL URL on a reserved, unresolvable host.  It
#: is never connected to: ``_connect_postgres`` is replaced by the stand-in.
PG_URL = "postgresql://u5e:never@u5e-no-server.invalid:5432/sgaa"

_ORIGINAL_SQLITE_CONNECT = sqlite3.connect

BACKUP_SUCCESS_FLASH = "Backup local criado"
RESTORE_SUCCESS_FLASH = "Banco restaurado com sucesso"

#: Exit codes already documented by ``app.backup.sync``.  An unsupported
#: backend is none of them: not success, not a crash, not startup, not busy.
_EXISTING_EXIT_CODES = {
    sync.EXIT_OK,
    sync.EXIT_RUNTIME_FAILURE,
    sync.EXIT_STARTUP_FAILURE,
    sync.EXIT_BUSY,
}

#: Modules that call into SQLite file backup/restore.  The capability decision
#: may live in at most one of them (or in a dedicated owner); none may parse
#: the URL or import the driver itself.
_BACKUP_FAMILY = (
    "app/backup/__init__.py",
    "app/backup/automatic.py",
    "app/backup/lock.py",
    "app/backup/orchestrator.py",
    "app/backup/sync.py",
    "app/backup/task_scheduler.py",
    "app/views/admin/banco_dados.py",
    "app/services/backup_service.py",
)


# ---------------------------------------------------------------------------
# harness
# ---------------------------------------------------------------------------


def _normalized_target(target) -> str:
    text = os.fspath(target) if not isinstance(target, str) else target
    if text.startswith("file:"):
        text = url2pathname(urlsplit(text).path)
        if os.name == "nt" and len(text) > 2 and text[0] in "\\/" and text[2] == ":":
            text = text[1:]
    return os.path.normcase(os.path.abspath(text))


class _SqliteSpy:
    def __init__(self):
        self.calls: list[str] = []

    def __call__(self, database, *args, **kwargs):
        self.calls.append(_normalized_target(database))
        return _ORIGINAL_SQLITE_CONNECT(database, *args, **kwargs)


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    for suffix in ("", "-wal"):
        candidate = Path(str(path) + suffix)
        digest.update(suffix.encode() + b"\x00")
        if candidate.exists():
            digest.update(candidate.read_bytes())
    return digest.hexdigest()


def _checkpoint(path: Path) -> None:
    conn = _ORIGINAL_SQLITE_CONNECT(str(path))
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()


class _PostgresBackend:
    """Switches the configured backend to PostgreSQL around a stale SQLite file."""

    def __init__(self, env, monkeypatch, tmp_path):
        self.env = env
        self.monkeypatch = monkeypatch
        self.tmp_path = tmp_path
        self.stale = Path(app_db.DATABASE)
        self.standin = tmp_path / "pg_stand_in.db"
        self.pg_connects = 0
        self.spy = _SqliteSpy()
        self.stale_digest = None
        self.artifacts_before = None
        self.active = False

    def _connect_postgres(self):
        self.pg_connects += 1
        conn = _ORIGINAL_SQLITE_CONNECT(str(self.standin), timeout=30.0)
        conn.row_factory = sqlite3.Row
        register_human_text_sql(conn)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def artifact_files(self) -> set[str]:
        excluded = {self.stale.name, self.standin.name}
        found = set()
        for path in self.tmp_path.rglob("*"):
            if not path.is_file():
                continue
            family = path.name.split("-wal")[0].split("-shm")[0].split("-journal")[0]
            if family in excluded:
                continue
            found.add(str(path))
        return found

    def activate(self, *, stale_mutation=None) -> "_PostgresBackend":
        with self.env.main.app.app_context():
            self.env.main.close_db_connection(None)
        _checkpoint(self.stale)
        source = _ORIGINAL_SQLITE_CONNECT(str(self.stale))
        target = _ORIGINAL_SQLITE_CONNECT(str(self.standin))
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        if stale_mutation is not None:
            conn = _ORIGINAL_SQLITE_CONNECT(str(self.stale))
            conn.row_factory = sqlite3.Row
            try:
                stale_mutation(conn)
                conn.commit()
            finally:
                conn.close()
            _checkpoint(self.stale)
        self.stale_digest = _file_digest(self.stale)
        self.artifacts_before = self.artifact_files()
        self.monkeypatch.setattr(app_db, "DATABASE_URL", PG_URL)
        self.monkeypatch.setattr(app_db, "_connect_postgres", self._connect_postgres)
        self.monkeypatch.setattr(sqlite3, "connect", self.spy)
        self.pg_connects = 0
        self.active = True
        assert app_db.database_backend() == "postgres"
        return self

    # -- assertions -------------------------------------------------------

    def assert_no_sqlite_io(self):
        assert self.spy.calls == [], (
            "SQLite I/O under a PostgreSQL backend (refusal must come first): "
            f"{self.spy.calls!r}"
        )

    def assert_stale_untouched(self):
        assert _file_digest(self.stale) == self.stale_digest, (
            "the stale SQLite database.db was modified under a PostgreSQL backend"
        )

    def assert_no_new_artifacts(self):
        created = sorted(self.artifact_files() - self.artifacts_before)
        assert created == [], f"backup artifacts created under PostgreSQL: {created!r}"


@pytest.fixture
def pg_backend(backup_env, admin_client, monkeypatch, tmp_path):
    return _PostgresBackend(backup_env, monkeypatch, tmp_path)


@pytest.fixture(autouse=True)
def _no_windows_task_query(monkeypatch):
    monkeypatch.setattr(task_scheduler, "query_task", lambda: None)


@pytest.fixture
def init_db_spy(monkeypatch):
    calls: list[str] = []

    def spy(*_args, **_kwargs):
        calls.append("init_db")

    monkeypatch.setattr(banco_dados_view, "init_db", spy)
    return calls


@pytest.fixture
def drive_spy(tmp_path, monkeypatch):
    """Authorized provider accounts plus recorders below the endpoints."""
    calls = {"zip": [], "upload": []}
    artifact = tmp_path / "u5e-backup.zip"
    artifact.write_bytes(b"PK")

    def fake_zip(database_path):
        calls["zip"].append(str(database_path))
        return {"zip_path": str(artifact), "file_name": artifact.name, "file_size": 2}

    def fake_upload(conn, provider, **_kwargs):
        calls["upload"].append(provider)
        return {"account_email": f"dono+{provider}@example.invalid"}

    accounts = {
        provider: {
            "id": 1,
            "account_email": f"dono+{provider}@example.invalid",
            "token_json_available": True,
            "token_json_error": "",
        }
        for provider in ("google", "onedrive")
    }
    monkeypatch.setattr(banco_dados_view, "create_sqlite_backup_zip", fake_zip)
    monkeypatch.setattr(banco_dados_view, "cleanup_backup_artifacts", lambda _artifacts: None)
    monkeypatch.setattr(banco_dados_view, "_require_cloud_token_encryption_ready", lambda: None)
    monkeypatch.setattr(banco_dados_view._cloud_connections, "upload_backup_zip", fake_upload)
    monkeypatch.setattr(
        banco_dados_view, "_get_active_cloud_account", lambda conn, provider: accounts.get(provider)
    )
    return calls


def _clear_flashes(client):
    with client.session_transaction() as session:
        session.pop("_flashes", None)


def _flashes(client) -> list[tuple[str, str]]:
    with client.session_transaction() as session:
        return list(session.get("_flashes", []))


def _request(call):
    try:
        return call(), None
    except Exception as exc:  # the RED records unhandled failures as findings
        return None, exc


def _assert_handled_redirect(response, exc):
    assert exc is None, f"the request was not handled deliberately: {exc!r}"
    assert response.status_code in (302, 303), response.status_code


def _assert_unsupported_flash(flashes):
    assert flashes, "no user-visible outcome was reported"
    assert all(category != "success" for category, _message in flashes), flashes
    assert any("postgresql" in str(message).lower() for _category, message in flashes), (
        f"no PostgreSQL-unsupported indication was flashed: {flashes!r}"
    )


def _source_snapshot(env) -> dict:
    with env.main.app.app_context():
        return create_database_snapshot(
            app_db.DATABASE, str(env.local_dir), reason="manual-backup", origin="local"
        )


def _assert_cycle_not_successful(call):
    """A refused cycle may raise a deliberate exception or return a non-success.

    It must never return a created snapshot / ``ran`` outcome, and an escaping
    exception must not be a raw SQLite/OS failure or a busy-lock signal.
    """
    from app.backup.lock import BackupCycleBusy

    try:
        result = call()
    except (sqlite3.Error, OSError, BackupCycleBusy) as exc:
        pytest.fail(f"refusal surfaced as an incidental failure, not a boundary: {exc!r}")
    except Exception:
        return
    assert not (isinstance(result, dict) and result.get("snapshot")), result
    assert not (isinstance(result, dict) and result.get("ran")), result


# ===========================================================================
# 1. manual backup (WEB_POST /admin/banco-dados/backup)
# ===========================================================================


def test_pg_manual_backup_refuses_before_any_sqlite_io(backup_env, admin_client, events, pg_backend):
    backup_env.configure(cloud_folder=True, google=True, onedrive=True)
    pg_backend.activate()
    _clear_flashes(admin_client)

    response, exc = _request(lambda: admin_client.post("/admin/banco-dados/backup"))

    pg_backend.assert_no_sqlite_io()
    pg_backend.assert_stale_untouched()
    pg_backend.assert_no_new_artifacts()
    assert events.uploads == [] and "folder" not in events.log
    _assert_handled_redirect(response, exc)
    flashes = _flashes(admin_client)
    assert not any(BACKUP_SUCCESS_FLASH in str(message) for _c, message in flashes), flashes
    _assert_unsupported_flash(flashes)


# ===========================================================================
# 2. restore (WEB_POST /admin/banco-dados/restaurar and /restaurar/upload)
# ===========================================================================


def test_pg_restore_from_snapshot_refuses_before_replacing_database(
    backup_env, admin_client, events, pg_backend, init_db_spy
):
    backup_env.configure(cloud_folder=True, google=True, onedrive=True)
    snapshot = _source_snapshot(backup_env)
    source_digest = _file_digest(Path(snapshot["database_path"]))
    pg_backend.activate()
    _clear_flashes(admin_client)

    response, exc = _request(
        lambda: admin_client.post(
            "/admin/banco-dados/restaurar", data={"manifest_path": snapshot["manifest_path"]}
        )
    )

    pg_backend.assert_no_sqlite_io()
    pg_backend.assert_stale_untouched()
    pg_backend.assert_no_new_artifacts()
    assert init_db_spy == [], "init_db must not manufacture a restore success"
    assert events.uploads == [] and "folder" not in events.log
    assert _file_digest(Path(snapshot["database_path"])) == source_digest
    _assert_handled_redirect(response, exc)
    flashes = _flashes(admin_client)
    assert not any(RESTORE_SUCCESS_FLASH in str(message) for _c, message in flashes), flashes
    _assert_unsupported_flash(flashes)


def test_pg_uploaded_restore_refuses_before_extraction_or_replacement(
    backup_env, admin_client, events, pg_backend, init_db_spy
):
    backup_env.configure(cloud_folder=True, google=True, onedrive=True)
    snapshot = _source_snapshot(backup_env)
    payload = Path(snapshot["database_path"]).read_bytes()
    pg_backend.activate()
    _clear_flashes(admin_client)

    import io

    response, exc = _request(
        lambda: admin_client.post(
            "/admin/banco-dados/restaurar/upload",
            data={"backup_file": (io.BytesIO(payload), "backup.db")},
            content_type="multipart/form-data",
        )
    )

    pg_backend.assert_no_sqlite_io()
    pg_backend.assert_stale_untouched()
    pg_backend.assert_no_new_artifacts()
    assert init_db_spy == []
    assert events.uploads == [] and "folder" not in events.log
    _assert_handled_redirect(response, exc)
    flashes = _flashes(admin_client)
    assert not any(RESTORE_SUCCESS_FLASH in str(message) for _c, message in flashes), flashes
    _assert_unsupported_flash(flashes)


# ===========================================================================
# 3. Google Drive / OneDrive manual ZIP upload (WEB_POST)
# ===========================================================================


@pytest.mark.parametrize(
    "provider, url",
    [("google", "/admin/backup/google/upload"), ("onedrive", "/admin/backup/onedrive/upload")],
)
def test_pg_drive_upload_refuses_before_zip_or_upload(
    backup_env, admin_client, pg_backend, drive_spy, provider, url
):
    backup_env.configure(cloud_folder=False, google=False, onedrive=False)
    pg_backend.activate()
    _clear_flashes(admin_client)

    response, exc = _request(lambda: admin_client.post(url))

    assert drive_spy["zip"] == [], "a SQLite backup ZIP was packaged under PostgreSQL"
    assert drive_spy["upload"] == [], f"{provider} upload was called under PostgreSQL"
    pg_backend.assert_no_sqlite_io()
    pg_backend.assert_stale_untouched()
    _assert_handled_redirect(response, exc)
    _assert_unsupported_flash(_flashes(admin_client))


# ===========================================================================
# 4. automatic / scheduled cycle (AUTOMATIC/SCHEDULED + INTERNAL_OWNER)
# ===========================================================================


def test_pg_run_backup_cycle_is_unsupported(backup_env, events, pg_backend, caplog):
    backup_env.configure(cloud_folder=True, google=True, onedrive=True)
    pg_backend.activate()
    caplog.set_level(logging.INFO, logger="main")

    with backup_env.main.app.app_context():
        _assert_cycle_not_successful(lambda: orchestrator.run_backup_cycle(force=True))

    pg_backend.assert_no_sqlite_io()
    assert pg_backend.pg_connects == 0, "classification must not open PostgreSQL"
    pg_backend.assert_stale_untouched()
    pg_backend.assert_no_new_artifacts()
    assert events.uploads == [] and "folder" not in events.log
    assert "Snapshot de banco criado" not in caplog.text


@pytest.mark.parametrize("trigger", ["scheduled", "cli"])
def test_pg_run_automatic_cycle_is_unsupported(backup_env, events, pg_backend, caplog, trigger):
    backup_env.configure(cloud_folder=True, google=True, onedrive=True)
    pg_backend.activate()
    caplog.set_level(logging.INFO, logger="main")

    with backup_env.main.app.app_context():
        _assert_cycle_not_successful(lambda: automatic.run_automatic_cycle(trigger=trigger))

    pg_backend.assert_no_sqlite_io()
    assert pg_backend.pg_connects == 0, "classification must not open PostgreSQL"
    pg_backend.assert_stale_untouched()
    pg_backend.assert_no_new_artifacts()
    assert events.uploads == [] and "folder" not in events.log
    assert "Snapshot de banco criado" not in caplog.text
    assert "executando o ciclo" not in caplog.text


# ===========================================================================
# 5. CLI ``python -m app.backup.sync`` (CLI)
# ===========================================================================


@pytest.mark.parametrize("argv", [[], ["--scheduled"]])
def test_pg_sync_cli_exits_with_distinct_unsupported_code(
    backup_env, events, pg_backend, monkeypatch, caplog, argv
):
    backup_env.configure(cloud_folder=True, google=True, onedrive=True)
    monkeypatch.setattr(sync, "create_app", lambda: backup_env.main.app)
    monkeypatch.setattr(sync, "_configure_cli_logging", lambda: None)
    pg_backend.activate()
    caplog.set_level(logging.INFO, logger="main")

    code = sync.main(argv)

    pg_backend.assert_no_sqlite_io()
    pg_backend.assert_stale_untouched()
    pg_backend.assert_no_new_artifacts()
    assert events.uploads == [] and "folder" not in events.log
    assert code not in _EXISTING_EXIT_CODES, (
        f"unsupported backend must have its own non-zero exit code, got {code!r}"
    )
    assert isinstance(code, int) and code != 0
    assert "postgresql" in caplog.text.lower(), "no PostgreSQL diagnostic was logged"
    assert "Ciclo de backup concluído" not in caplog.text


# ===========================================================================
# 6. runtime-settings SQLite fallback (INTERNAL_OWNER)
# ===========================================================================


def _stale_settings_sentinel(tmp_path):
    sentinel_dir = tmp_path / "STALE_SQLITE_SETTINGS_SENTINEL"

    def mutate(conn):
        banco_dados_view.save_backup_settings(
            conn,
            {
                "local_backup_dir": str(sentinel_dir),
                "cloud_backup_dir": "",
                "cloud_sync_interval_seconds": "0",
                "external_backup_url": "",
                "external_backup_token": "",
                "external_backup_enabled": "0",
            },
        )

    return sentinel_dir, mutate


def test_pg_runtime_settings_never_fall_back_to_stale_sqlite(backup_env, pg_backend, tmp_path):
    backup_env.configure(cloud_folder=False, google=False, onedrive=False)
    sentinel_dir, mutate = _stale_settings_sentinel(tmp_path)
    pg_backend.activate(stale_mutation=mutate)

    with backup_env.main.app.app_context():
        try:
            settings = orchestrator._get_runtime_backup_settings()
        except sqlite3.Error as exc:
            pytest.fail(f"settings fallback still opened SQLite: {exc!r}")
        except Exception:
            settings = None

    pg_backend.assert_no_sqlite_io()
    pg_backend.assert_stale_untouched()
    if settings is not None:
        assert str(sentinel_dir) not in str(settings.get("local_backup_dir") or ""), (
            "PostgreSQL configuration inherited the stale SQLite backup settings"
        )


@pytest.mark.parametrize(
    "method, url",
    [
        ("get", "/admin/banco-dados/download?manifest_path=nao-existe.json"),
        ("post", "/admin/banco-dados/excluir"),
    ],
)
def test_pg_snapshot_file_routes_do_not_read_stale_sqlite_settings(
    backup_env, admin_client, pg_backend, method, url
):
    backup_env.configure(cloud_folder=False, google=False, onedrive=False)
    pg_backend.activate()

    if method == "get":
        response, exc = _request(lambda: admin_client.get(url))
    else:
        response, exc = _request(
            lambda: admin_client.post(url, data={"manifest_path": "nao-existe.json"})
        )

    pg_backend.assert_no_sqlite_io()
    pg_backend.assert_stale_untouched()
    assert exc is None, exc


# ===========================================================================
# 7. admin GET page (WEB_GET /admin/banco-dados)
# ===========================================================================


def test_pg_admin_page_shows_sqlite_backup_restore_unavailable(backup_env, admin_client, pg_backend):
    backup_env.configure(cloud_folder=False, google=False, onedrive=False)
    pg_backend.activate()

    response, exc = _request(lambda: admin_client.get("/admin/banco-dados"))

    assert exc is None, exc
    assert response.status_code == 200
    pg_backend.assert_no_sqlite_io()
    assert "postgresql" in response.get_data(as_text=True).lower(), (
        "the page gives no indication that SQLite backup/restore is unavailable"
    )


# ===========================================================================
# 8. SQLite green controls (behaviour unchanged; same harness, no switch)
# ===========================================================================


def test_sqlite_control_manual_backup_still_succeeds(backup_env, admin_client, events):
    backup_env.configure(cloud_folder=False, google=False, onedrive=False)
    _clear_flashes(admin_client)
    response = admin_client.post("/admin/banco-dados/backup")
    assert response.status_code in (302, 303)
    flashes = _flashes(admin_client)
    assert any(BACKUP_SUCCESS_FLASH in str(message) for _c, message in flashes), flashes
    assert list((backup_env.local_dir / "snapshots").glob("*.db"))


def test_sqlite_control_restore_still_succeeds(backup_env, admin_client, events):
    backup_env.configure(cloud_folder=False, google=False, onedrive=False)
    snapshot = _source_snapshot(backup_env)
    _clear_flashes(admin_client)
    response = admin_client.post(
        "/admin/banco-dados/restaurar", data={"manifest_path": snapshot["manifest_path"]}
    )
    assert response.status_code in (302, 303)
    assert _flashes(admin_client)[-1][0] == "success"


def test_sqlite_control_backup_cycle_and_cli_still_run(backup_env, events, monkeypatch):
    backup_env.configure(cloud_folder=False, google=False, onedrive=False)
    with backup_env.main.app.app_context():
        result = orchestrator.run_backup_cycle(force=True)
    assert result["snapshot"]["database_path"]
    monkeypatch.setattr(sync, "create_app", lambda: backup_env.main.app)
    monkeypatch.setattr(sync, "_configure_cli_logging", lambda: None)
    assert sync.main([]) == sync.EXIT_OK


def test_sqlite_control_settings_fallback_reads_the_sqlite_file(backup_env):
    backup_env.configure(cloud_folder=False, google=False, onedrive=False)
    with backup_env.main.app.app_context():
        settings = orchestrator._get_runtime_backup_settings()
    assert settings["local_backup_dir"] == str(backup_env.local_dir)


def test_sqlite_control_admin_page_has_no_postgresql_notice(backup_env, admin_client):
    response = admin_client.get("/admin/banco-dados")
    assert response.status_code == 200
    assert "postgresql" not in response.get_data(as_text=True).lower()


# ===========================================================================
# 9. engine-authority discrimination and ownership
# ===========================================================================


def test_environment_url_alone_does_not_select_postgres(backup_env, admin_client, events, monkeypatch):
    """Only the canonical configured value decides; ``os.environ`` re-parsing
    by a backup caller would wrongly refuse here."""
    backup_env.configure(cloud_folder=False, google=False, onedrive=False)
    monkeypatch.setenv("DATABASE_URL", PG_URL)
    assert app_db.database_backend() == "sqlite"
    _clear_flashes(admin_client)
    response = admin_client.post("/admin/banco-dados/backup")
    assert response.status_code in (302, 303)
    flashes = _flashes(admin_client)
    assert any(BACKUP_SUCCESS_FLASH in str(message) for _c, message in flashes), flashes


def _module_source(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def _names_and_strings(relative: str) -> tuple[set[str], list[str]]:
    tree = ast.parse(_module_source(relative))
    names: set[str] = set()
    strings: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.alias):
            names.add(node.name.split(".")[-1])
            names.add(node.name)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            strings.append(node.value)
    return names, strings


def test_backup_family_never_parses_the_url_or_imports_the_driver():
    for relative in _BACKUP_FAMILY:
        names, strings = _names_and_strings(relative)
        assert "DATABASE_URL" not in names, f"{relative} reads DATABASE_URL itself"
        assert "psycopg" not in names, f"{relative} imports the PostgreSQL driver"
        for value in strings:
            lowered = value.lower()
            assert "postgres://" not in lowered and "postgresql://" not in lowered, (
                f"{relative} parses a PostgreSQL URL itself"
            )
            assert "DATABASE_URL" not in value, f"{relative} reads DATABASE_URL by name"


def test_backup_capability_decision_has_at_most_one_owner():
    owners = [
        relative
        for relative in _BACKUP_FAMILY
        if {"database_backend", "database_engine"} & _names_and_strings(relative)[0]
    ]
    assert len(owners) <= 1, (
        "every backup caller invents its own backend condition instead of one "
        f"capability owner: {owners!r}"
    )
