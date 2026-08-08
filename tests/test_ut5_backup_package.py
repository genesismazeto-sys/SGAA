"""UT-5 RED contract — app/backup package extraction (backup orchestration
ownership, canonical database-path resolution, CLI, and request/app-context
boundaries).

This file proves, BEFORE implementation, the FUTURE app/backup architecture:

  D. app.backup / app.backup.orchestrator exist and own the canonical
     backup/settings symbols currently defined in main.py; main no longer
     defines their bodies (compatibility aliases, where main still exposes
     the name, must be identity re-exports of the orchestrator objects).
  E. the manual "Banco de Dados" backup route
     (POST /admin/banco-dados/backup) is intercepted by patching the
     EXECUTED lookup in app.backup.orchestrator -- it must not bypass the
     new owner via a stale main-owned implementation.
  F. `python -m app.backup.sync` runs as an isolated CLI: app-context only
     (no request context), touches only APP_*-isolated paths under
     tmp_path, and never mutates the canonical database.db.
  G. app/backup production sources resolve app.db.DATABASE at CALL TIME
     (never `from app.db import DATABASE` at import time), so rebinding
     app.db.DATABASE after import is observed by the next orchestrator call.
  H. the orchestration API requires an app context (RuntimeError outside
     one) but does not require a request context.

Every test below imports app.backup / app.backup.orchestrator INSIDE the
test function body (never at module level), so collection succeeds even
though the package does not exist yet at RED. At RED stage, every test in
this file is expected to fail (import error, AssertionError, or non-zero
subprocess exit) because app.backup does not exist. No dummy/stub
app/backup module is created to make these pass early -- that would silently
weaken the RED proof.
"""
from __future__ import annotations

import ast
import hashlib
import inspect
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_DATABASE = PROJECT_ROOT / "database.db"

# Backup-settings keys that decide where the application writes, and whether it
# is allowed to talk to anything off-box. Every isolated database copy used by
# this file has these rewritten before the code under test observes them.
_WRITABLE_DESTINATION_KEYS = ("local_backup_dir", "cloud_backup_dir")
_PROVIDER_DISABLING_SETTINGS = {
    "external_backup_enabled": "0",
    "external_backup_url": "",
    "external_backup_token": "",
    "gdrive_enabled": "0",
    "gdrive_access_token": "",
    "gdrive_refresh_token": "",
    "onedrive_enabled": "0",
    "onedrive_access_token": "",
    "onedrive_refresh_token": "",
}


def _read_backup_destinations(database_path: Path) -> dict[str, str]:
    """Absolute writable backup destinations persisted in ``database_path``."""
    conn = sqlite3.connect(str(database_path))
    try:
        rows = conn.execute(
            "SELECT chave, valor FROM configuracoes_backup WHERE chave IN (?, ?)",
            _WRITABLE_DESTINATION_KEYS,
        ).fetchall()
    finally:
        conn.close()
    return {str(k): str(v) for k, v in rows if str(v or "").strip()}


def _quarantine_backup_settings(
    database_path: Path, *, local_dir: Path, cloud_dir: Path
) -> dict[str, str]:
    """Rewrite an isolated database copy so every writable backup destination
    resolves under the caller's ``tmp_path`` and no provider can be contacted.

    Rationale (UT-5 A4). The canonical ``database.db`` legitimately stores
    absolute backup directories pointing at a real, out-of-tree location, and
    DB-stored settings correctly take precedence over runtime defaults --
    ``_database_backup_locations`` and ``_maybe_sync_database_snapshot`` both
    resolve ``settings[...] or current_app.config[...]``. A bare
    ``shutil.copy2`` of the canonical database therefore *inherits* those
    out-of-tree destinations, and ``APP_LOCAL_BACKUP_DIR`` /
    ``APP_CLOUD_BACKUP_DIR`` never get a chance to win. That is precisely how
    the previous CLI test wrote real snapshots outside ``tmp_path`` while still
    reporting green.

    Production semantics are deliberately left intact -- the isolated *fixture*
    is what gets normalised to satisfy them. Returns the exact settings applied.
    """
    applied = dict(_PROVIDER_DISABLING_SETTINGS)
    applied["local_backup_dir"] = str(local_dir)
    applied["cloud_backup_dir"] = str(cloud_dir)
    applied["cloud_sync_interval_seconds"] = "0"

    conn = sqlite3.connect(str(database_path))
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS configuracoes_backup (
                chave TEXT PRIMARY KEY,
                valor TEXT NOT NULL,
                atualizado_em TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO configuracoes_backup (chave, valor, atualizado_em)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor,
                                             atualizado_em = datetime('now')
            """,
            sorted(applied.items()),
        )
        conn.commit()
    finally:
        conn.close()
    return applied


def _directory_snapshot(directory: Path) -> dict[str, int]:
    """Recursive ``relative path -> size`` map, or ``{}`` when absent."""
    if not directory.is_dir():
        return {}
    return {
        str(path.relative_to(directory)): path.stat().st_size
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }

# Canonical symbols that must be solely defined (bodies) by
# app.backup.orchestrator after UT-5. Main may still expose some of these
# names as identity re-exports for backward compatibility.
CANONICAL_ORCHESTRATOR_SYMBOLS = (
    "_maybe_sync_database_snapshot",
    "_run_retention_cleanup",
    "_maybe_upload_to_drives",
    "_upload_snapshot_if_external_enabled",
    "_get_runtime_backup_settings",
    "_database_backup_locations",
    "get_retention_policy",
    "get_drive_settings",
    "_save_drive_config",
    "_resolve_allowed_backup_manifest_path",
)


def _canonical_database_fingerprint() -> tuple[int, str]:
    data = CANONICAL_DATABASE.read_bytes()
    return len(data), hashlib.sha256(data).hexdigest()


def _top_level_function_names(module) -> set[str]:
    tree = ast.parse(inspect.getsource(module))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


# ═══════════════════════════════════════════════════════════════════
# D. app.backup / app.backup.orchestrator ownership
# ═══════════════════════════════════════════════════════════════════


def test_app_backup_package_is_importable():
    import app.backup  # noqa: F401


def test_app_backup_orchestrator_module_is_importable():
    import app.backup.orchestrator  # noqa: F401


def test_orchestrator_owns_canonical_backup_symbol_bodies():
    from app.backup import orchestrator

    orchestrator_bodies = _top_level_function_names(orchestrator)
    missing = set(CANONICAL_ORCHESTRATOR_SYMBOLS) - orchestrator_bodies
    assert not missing, (
        f"app.backup.orchestrator does not define bodies for: {sorted(missing)}; "
        "UT-5 expects it to be the sole canonical owner"
    )


def test_main_no_longer_defines_canonical_backup_symbol_bodies():
    import main

    main_path = Path(main.__file__)
    tree = ast.parse(main_path.read_text(encoding="utf-8"), filename=str(main_path))
    main_bodies = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    present = set(CANONICAL_ORCHESTRATOR_SYMBOLS) & main_bodies
    assert not present, (
        f"main.py still defines the body for {sorted(present)}; UT-5 expects "
        "app.backup.orchestrator to be the sole owner (main may keep an "
        "identity re-export, but must not keep the implementation)"
    )


def test_main_compatibility_aliases_are_identical_to_orchestrator_objects():
    """Where main still exposes one of these names post-UT-5 (for backward
    compatibility with other call sites/tests), it must be the exact same
    object as the orchestrator's -- not a re-implementation or a wrapper
    that merely forwards, which would let the two silently diverge.
    """
    import main
    from app.backup import orchestrator

    for name in CANONICAL_ORCHESTRATOR_SYMBOLS:
        if hasattr(main, name):
            assert getattr(main, name) is getattr(orchestrator, name), (
                f"main.{name} is not an identity re-export of "
                f"app.backup.orchestrator.{name}"
            )


# ═══════════════════════════════════════════════════════════════════
# E. manual "Banco de Dados" UI route must use the new canonical owner
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
def isolated_admin_client(tmp_path):
    """Logged-in admin client whose *effective* backup settings resolve only
    under this test's ``tmp_path``, regardless of sibling execution order.

    Order-independence contract (UT-5 A2/A3)
    ----------------------------------------
    ``configuracoes_backup`` rows are DB-backed and legitimately take precedence
    over runtime configuration: database bootstrap runs
    ``ensure_backup_settings_schema()``, which ends in
    ``_apply_backup_settings_to_app()`` and replays the persisted rows onto
    ``main.app.config``.

    An earlier version of this fixture bootstrapped the *session-shared* test
    database and installed this test's paths *before* that bootstrap, so the
    bootstrap immediately overwrote them with whatever a sibling test had
    persisted -- and it then fed those already-clobbered ``app.config`` values
    back into ``save_backup_settings()``, persisting a *sibling's* ``tmp_path``.
    Since ``POST /admin/banco-dados/backup`` resolves its local snapshot
    directory from the DB-backed settings, the snapshot landed in the other
    test's ``tmp_path`` and the assertions became order-dependent.

    The corrected sequence is:

      1. enter ``tests.versioned_test_support.isolated_versioned_app_env`` --
         the project's canonical isolated application environment. It owns the
         database bootstrap (so this file adds no new ``main.init_db`` caller to
         the Phase-3 compatibility manifest), rebinds ``main.DATABASE`` /
         ``app.db.DATABASE`` to a private database under this test's
         ``tmp_path``, and restores every binding it touched on exit. Because
         the database is private, no sibling's ``configuracoes_backup`` rows can
         be observed here and none of this test's rows can leak out;
      2. only then install this test's ``LOCAL_BACKUP_DIR`` /
         ``CLOUD_BACKUP_DIR``;
      3. rewrite the DB-backed settings from the explicit ``tmp_path`` values
         (never re-read from ``app.config``), so the settings that actually win
         also point at this test's ``tmp_path``;
      4. restore every ``app.config`` key touched here on teardown, so nothing
         leaks into later tests -- notably
         ``tests/test_admin_database_backups.py``.

    Production semantics are untouched; the fixture adapts to them.
    """
    import main
    from tests.versioned_test_support import isolated_versioned_app_env

    local_dir = tmp_path / "local"
    cloud_dir = tmp_path / "cloud"
    local_dir.mkdir(parents=True, exist_ok=True)
    cloud_dir.mkdir(parents=True, exist_ok=True)

    guarded_config_keys = (
        "TESTING",
        "LOCAL_BACKUP_DIR",
        "CLOUD_BACKUP_DIR",
        "CLOUD_SYNC_INTERVAL_SECONDS",
        "EXTERNAL_BACKUP_URL",
        "EXTERNAL_BACKUP_TOKEN",
        "EXTERNAL_BACKUP_ENABLED",
    )

    # 1. Canonical isolated + initialised application environment. Its bootstrap
    #    is the step that replays persisted backup settings onto app.config, so
    #    it must complete before step 2.
    with isolated_versioned_app_env(tmp_path, "ut5_backup_isolated.db"):
        original_config = {key: main.app.config.get(key) for key in guarded_config_keys}

        # 2. Install this test's runtime paths.
        main.app.config["TESTING"] = True
        main.app.config["LOCAL_BACKUP_DIR"] = str(local_dir)
        main.app.config["CLOUD_BACKUP_DIR"] = str(cloud_dir)
        main.app.config["CLOUD_SYNC_INTERVAL_SECONDS"] = 0

        # 3. Make the DB-backed settings -- which take precedence -- agree, from
        #    the explicit tmp_path values rather than from the just-overwritten
        #    config.
        persisted = {
            "local_backup_dir": str(local_dir),
            "cloud_backup_dir": str(cloud_dir),
            "cloud_sync_interval_seconds": "0",
            "external_backup_url": "",
            "external_backup_token": "",
            "external_backup_enabled": "0",
        }
        with main.app.app_context():
            conn = main.get_db_connection()
            main.save_backup_settings(conn, persisted)
            conn.commit()

        client = main.app.test_client()
        login_response = client.post(
            "/login",
            data={"email": "admin@ej.edu.br", "senha": "admin123"},
            follow_redirects=False,
        )
        assert login_response.status_code in (302, 303), (
            "test bootstrap admin login failed; cannot exercise the manual "
            f"backup route (status={login_response.status_code})"
        )

        try:
            yield client
        finally:
            # 4. Restore the runtime config. The backup-settings rows need no
            #    restoration: they live in this test's private database, which
            #    isolated_versioned_app_env discards with its tmp_path.
            for key, value in original_config.items():
                main.app.config[key] = value


def test_manual_backup_route_is_intercepted_at_orchestrator_owner(
    tmp_path, monkeypatch, isolated_admin_client
):
    """UT-5 RED: patching app.backup.orchestrator's canonical sync lookup
    must intercept POST /admin/banco-dados/backup. Proves the route calls
    through the new owner rather than a stale main-owned implementation
    that would silently keep working after extraction.
    """
    from app.backup import orchestrator

    calls = []

    def _spy_sync(*args, **kwargs):
        calls.append(("sync", args, kwargs))
        return {"ok": True, "skipped": True, "reason": "ut5-red-spy"}

    monkeypatch.setattr(orchestrator, "_maybe_sync_database_snapshot", _spy_sync)

    client = isolated_admin_client
    response = client.post("/admin/banco-dados/backup", follow_redirects=False)
    assert response.status_code in (302, 303)
    assert calls, (
        "POST /admin/banco-dados/backup did not invoke "
        "app.backup.orchestrator._maybe_sync_database_snapshot; route is "
        "bypassing the new canonical owner"
    )


def test_manual_backup_route_upload_receives_expected_local_snapshot_path(
    tmp_path, monkeypatch, isolated_admin_client
):
    """UT-5 RED: the manual route's drive-upload step must still receive the
    freshly created LOCAL snapshot's database_path (not e.g. a stale path,
    the cloud snapshot's path, or nothing) once drive upload also routes
    through app.backup.orchestrator.
    """
    from app.backup import orchestrator

    received_paths = []

    def _spy_upload_to_drives(snapshot_path, *args, **kwargs):
        received_paths.append(snapshot_path)
        return None

    monkeypatch.setattr(orchestrator, "_maybe_upload_to_drives", _spy_upload_to_drives)
    monkeypatch.setattr(
        orchestrator,
        "_maybe_sync_database_snapshot",
        lambda *a, **k: {"ok": True, "skipped": True, "reason": "ut5-red-spy"},
    )

    client = isolated_admin_client
    client.post("/admin/banco-dados/backup", follow_redirects=False)

    local_snapshots_dir = tmp_path / "local" / "snapshots"
    assert local_snapshots_dir.is_dir(), "manual backup route did not create a local snapshot"
    local_db_files = sorted(local_snapshots_dir.glob("*.db"))
    # Exactly one, and it belongs to THIS test's tmp_path: the sibling manual
    # test must not have persisted its own directory into the shared settings.
    assert len(local_db_files) == 1, local_db_files

    assert received_paths, "app.backup.orchestrator._maybe_upload_to_drives was not called"
    assert Path(received_paths[0]).resolve() == local_db_files[0].resolve(), (
        f"drive upload received {received_paths[0]!r}, expected the local "
        f"snapshot {local_db_files[0]!r}"
    )


# ═══════════════════════════════════════════════════════════════════
# F. CLI — python -m app.backup.sync
# ═══════════════════════════════════════════════════════════════════


def test_cli_backup_sync_runs_isolated_with_app_context_only(tmp_path):
    isolated_db = tmp_path / "isolated_app_database.db"
    shutil.copy2(CANONICAL_DATABASE, isolated_db)

    local_backup_dir = tmp_path / "backups" / "local"
    cloud_backup_dir = tmp_path / "backups" / "cloud"
    uploads_dir = tmp_path / "uploads"
    documents_dir = tmp_path / "documentos_alunos"
    log_dir = tmp_path / "logs"
    for directory in (local_backup_dir, cloud_backup_dir, uploads_dir, documents_dir, log_dir):
        directory.mkdir(parents=True, exist_ok=True)

    # The copy inherits the canonical database's DB-backed backup destinations,
    # which point OUTSIDE the test root. Because DB-stored settings correctly
    # take precedence over the APP_* runtime defaults, leaving them in place is
    # what let the previous version of this test create real snapshots outside
    # tmp_path and still pass. Capture those inherited destinations first so we
    # can prove the subprocess never writes there, then quarantine the copy.
    inherited_destinations = _read_backup_destinations(isolated_db)
    legacy_before = {
        raw: _directory_snapshot(Path(raw)) for raw in inherited_destinations.values()
    }
    quarantined = _quarantine_backup_settings(
        isolated_db, local_dir=local_backup_dir, cloud_dir=cloud_backup_dir
    )

    # (C) every writable backup destination the subprocess can resolve from the
    #     isolated database is beneath tmp_path -- asserted before it runs.
    for key in _WRITABLE_DESTINATION_KEYS:
        Path(quarantined[key]).resolve().relative_to(tmp_path.resolve())
    assert _read_backup_destinations(isolated_db) == {
        key: quarantined[key] for key in _WRITABLE_DESTINATION_KEYS
    }
    # (E) no real cloud provider can be contacted: external upload and both
    #     drive providers are disabled with their credentials cleared.
    for key, expected_value in _PROVIDER_DISABLING_SETTINGS.items():
        assert quarantined[key] == expected_value

    env = os.environ.copy()
    env.update(
        APP_DATABASE=str(isolated_db),
        APP_UPLOAD_FOLDER=str(uploads_dir),
        APP_DOCUMENTOS_ALUNOS_FOLDER=str(documents_dir),
        APP_LOCAL_BACKUP_DIR=str(local_backup_dir),
        APP_CLOUD_BACKUP_DIR=str(cloud_backup_dir),
        APP_LOG_DIR=str(log_dir),
        APP_BOOTSTRAP_DEFAULT_ADMIN="0",
        DISABLE_CSRF="1",
        APP_SECRET_KEY="ut5-cli-isolated-secret-do-not-use-elsewhere",
        EXTERNAL_BACKUP_ENABLED="0",
    )

    before_size, before_hash = _canonical_database_fingerprint()

    result = subprocess.run(
        [sys.executable, "-B", "-m", "app.backup.sync"],
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    after_size, after_hash = _canonical_database_fingerprint()
    # (D) canonical database.db size/hash unchanged.
    assert (after_size, after_hash) == (before_size, before_hash), (
        "canonical database.db was mutated by the CLI run: "
        f"before=({before_size}, {before_hash}) after=({after_size}, {after_hash})"
    )

    assert result.returncode == 0, (
        "python -m app.backup.sync did not exit 0 under isolated APP_* paths "
        f"(UT-5 RED expected at current HEAD: module absent). "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )

    # (F) nothing was produced in the legacy, out-of-root backup destinations.
    #     This is the assertion the previous false-green version lacked.
    for raw_destination, before_listing in legacy_before.items():
        assert _directory_snapshot(Path(raw_destination)) == before_listing, (
            "isolated CLI run wrote into the out-of-root backup destination "
            f"{raw_destination!r} inherited from the canonical database; the "
            "isolated fixture failed to contain it"
        )

    # (A) the run really produced snapshots, and every one of them -- manifest
    #     and database alike -- is beneath tmp_path.
    produced_manifests = sorted(tmp_path.rglob("*.json"))
    assert produced_manifests, (
        "isolated CLI run produced no snapshot manifest under tmp_path; the "
        "backup cycle did not actually execute, so containment is unproven. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    for manifest_path in produced_manifests:
        manifest_path.resolve().relative_to(tmp_path.resolve())
        with open(manifest_path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        # (B) the manifest identifies the isolated APP_DATABASE as its source.
        source_path = manifest.get("source_database_path")
        assert source_path, f"manifest {manifest_path} has no source_database_path"
        assert Path(source_path).resolve() == isolated_db.resolve(), (
            f"manifest {manifest_path} source_database_path={source_path!r} "
            f"does not identify the isolated APP_DATABASE {isolated_db}"
        )
        # (A) the snapshot the manifest points at is itself beneath tmp_path.
        Path(str(manifest["database_path"])).resolve().relative_to(tmp_path.resolve())

    produced_dbs = [p for p in tmp_path.rglob("*.db") if p.resolve() != isolated_db.resolve()]
    assert produced_dbs, "isolated CLI run produced no snapshot database under tmp_path"
    for produced_db in produced_dbs:
        produced_db.resolve().relative_to(tmp_path.resolve())


# ═══════════════════════════════════════════════════════════════════
# G. call-time database lookup (no import-time freeze)
# ═══════════════════════════════════════════════════════════════════


def test_backup_package_sources_do_not_freeze_database_path_at_import_time():
    backup_pkg_dir = PROJECT_ROOT / "app" / "backup"
    if not backup_pkg_dir.is_dir():
        pytest.fail(
            "UT-5 RED: app/backup/ does not exist yet. Once created, its "
            "sources must resolve app.db.DATABASE at CALL TIME -- never via "
            "`from app.db import DATABASE` at import time (that would freeze "
            "the path main.py froze today and defeat rebinding)."
        )

    offending = []
    for py_file in sorted(backup_pkg_dir.rglob("*.py")):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "app.db":
                for alias in node.names:
                    if alias.name == "DATABASE":
                        offending.append(str(py_file.relative_to(PROJECT_ROOT)))
    assert not offending, (
        f"call-time DATABASE lookup violated by import-time binding in: {offending}"
    )


def test_orchestrator_resolves_database_path_at_call_time_not_import_time(tmp_path, monkeypatch):
    import main
    from app import db as app_db
    from app.backup import orchestrator

    isolated_db = tmp_path / "call_time_isolated.db"
    shutil.copy2(CANONICAL_DATABASE, isolated_db)
    monkeypatch.setattr(app_db, "DATABASE", str(isolated_db))

    cloud_dir = tmp_path / "cloud"
    local_dir = tmp_path / "local"
    cloud_dir.mkdir()
    local_dir.mkdir()
    # Setting app.config alone is not containment: this call forces a real
    # snapshot, and the orchestrator resolves its destination as
    # `settings["cloud_backup_dir"] or current_app.config[...]` -- so the
    # canonical copy's out-of-root destination would win and the snapshot would
    # land outside tmp_path while this test still passed.
    _quarantine_backup_settings(isolated_db, local_dir=local_dir, cloud_dir=cloud_dir)

    original_cloud_dir = main.app.config.get("CLOUD_BACKUP_DIR")
    original_local_dir = main.app.config.get("LOCAL_BACKUP_DIR")
    main.app.config["CLOUD_BACKUP_DIR"] = str(cloud_dir)
    try:
        with main.app.app_context():
            result = orchestrator._maybe_sync_database_snapshot(force=True)
    finally:
        main.app.config["CLOUD_BACKUP_DIR"] = original_cloud_dir
        main.app.config["LOCAL_BACKUP_DIR"] = original_local_dir

    snapshot = (result or {}).get("snapshot") or {}
    source_path = snapshot.get("source_database_path")
    assert source_path, f"orchestrator call reported no source database path: {result}"
    assert Path(source_path).resolve() == isolated_db.resolve(), (
        "orchestrator used a stale/import-time DATABASE path instead of the "
        f"call-time rebound app.db.DATABASE: got {source_path!r}, "
        f"expected {isolated_db}"
    )
    # The snapshot this call produced stays inside the test root.
    Path(str(snapshot["database_path"])).resolve().relative_to(tmp_path.resolve())


# ═══════════════════════════════════════════════════════════════════
# H. app-context required, request context not required
# ═══════════════════════════════════════════════════════════════════


def test_orchestrator_requires_app_context_but_not_request_context(tmp_path, monkeypatch):
    import main
    from app import db as app_db
    from app.backup import orchestrator

    with pytest.raises(RuntimeError):
        orchestrator._maybe_sync_database_snapshot(force=False)

    isolated_db = tmp_path / "app_context_only.db"
    shutil.copy2(CANONICAL_DATABASE, isolated_db)
    monkeypatch.setattr(app_db, "DATABASE", str(isolated_db))
    # Same containment reason as the call-time test: the canonical copy carries
    # out-of-root backup destinations that outrank app.config.
    _quarantine_backup_settings(
        isolated_db, local_dir=tmp_path / "local", cloud_dir=tmp_path / "cloud"
    )

    original_cloud_dir = main.app.config.get("CLOUD_BACKUP_DIR")
    original_local_dir = main.app.config.get("LOCAL_BACKUP_DIR")
    main.app.config["CLOUD_BACKUP_DIR"] = ""
    try:
        with main.app.app_context():
            from flask import request

            assert not request
            result = orchestrator._maybe_sync_database_snapshot(force=False)
    finally:
        main.app.config["CLOUD_BACKUP_DIR"] = original_cloud_dir
        main.app.config["LOCAL_BACKUP_DIR"] = original_local_dir

    assert isinstance(result, dict)
