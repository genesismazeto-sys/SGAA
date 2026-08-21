import ast
import importlib
import inspect
import os
import sqlite3
import subprocess
import sys

from pathlib import Path

import pytest
from flask import Flask


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import main
from app import db as app_db
from app import db_maintenance
from app.prod1_schema import bootstrap_prod1_schema
from app.views.admin import banco_dados as banco_dados_module

backup_settings = importlib.import_module("app.backup_settings")


@pytest.fixture(autouse=True)
def _restore_backup_settings_runtime_app_binding():
    original_app = backup_settings._runtime_backup_settings_app
    try:
        yield
    finally:
        backup_settings._runtime_backup_settings_app = original_app


MOVED_RUNTIME_NAMES = (
    "_backup_settings_defaults",
    "_apply_backup_settings_to_app",
    "ensure_backup_settings_schema",
    "get_backup_settings",
)
RUNTIME_COMPONENT_NAMES = (
    "bind_backup_settings_runtime_app",
    "seed_backup_settings_default_data",
    "normalize_legacy_backup_sync_interval",
    "read_backup_settings",
)
EXACT_DEFAULTS = {
    "local_backup_dir": "C:/runtime/local",
    "cloud_backup_dir": "C:/runtime/cloud",
    "cloud_sync_interval_seconds": "900",
    "external_backup_url": "https://backup.example.test/upload",
    "external_backup_token": "runtime-token",
    "external_backup_enabled": "1",
}



def _memory_connection():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    bootstrap_prod1_schema(conn)
    return conn


def _runtime_app():
    app = Flask("backup-settings-tests")
    app.config.update(
        LOCAL_BACKUP_DIR="C:/runtime/local",
        CLOUD_BACKUP_DIR="C:/runtime/cloud",
        CLOUD_SYNC_INTERVAL_SECONDS=900,
        EXTERNAL_BACKUP_URL="https://backup.example.test/upload",
        EXTERNAL_BACKUP_TOKEN="runtime-token",
        EXTERNAL_BACKUP_ENABLED=True,
    )
    backup_settings.bind_backup_settings_runtime_app(app)
    return app


def _table_rows(conn):
    return {
        row["chave"]: row["valor"]
        for row in conn.execute(
            "SELECT chave, valor FROM configuracoes_backup ORDER BY chave"
        ).fetchall()
    }


def _top_level_function_names(module):
    tree = ast.parse(inspect.getsource(module))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }



def _direct_call_scopes(module, called_name):
    tree = ast.parse(inspect.getsource(module))
    scopes = []
    for function in (node for node in tree.body if isinstance(node, ast.FunctionDef)):
        if any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == called_name
            for node in ast.walk(function)
        ):
            scopes.append(function.name)
    return tuple(scopes)


def _assert_no_transaction_ownership(function):
    source = inspect.getsource(function)
    lowered = source.lower()
    assert ".commit(" not in lowered
    assert ".rollback(" not in lowered
    assert "savepoint" not in lowered
    assert "begin;" not in lowered
    assert "commit;" not in lowered


def test_sole_defining_ownership_and_compatibility_identities():
    main_names = _top_level_function_names(main)
    app_db_names = _top_level_function_names(app_db)
    maintenance_names = _top_level_function_names(db_maintenance)
    runtime_names = _top_level_function_names(backup_settings)

    assert not (set(MOVED_RUNTIME_NAMES) & main_names)
    assert not (set(MOVED_RUNTIME_NAMES) & app_db_names)
    assert not (set(MOVED_RUNTIME_NAMES) & maintenance_names)
    assert set(MOVED_RUNTIME_NAMES) <= runtime_names
    assert set(RUNTIME_COMPONENT_NAMES) <= runtime_names

    assert "ensure_backup_settings_structural_schema" in maintenance_names
    assert "ensure_backup_settings_structural_schema" not in runtime_names
    assert "ensure_backup_settings_structural_schema" not in main_names
    assert "ensure_backup_settings_structural_schema" not in app_db_names

    for name in MOVED_RUNTIME_NAMES:
        assert getattr(main, name) is getattr(backup_settings, name)
    assert app_db.ensure_backup_settings_schema is backup_settings.ensure_backup_settings_schema


def test_runtime_modules_import_without_main_or_database_creation(tmp_path):
    database_path = tmp_path / "must-not-exist.db"
    code = (
        "import sys; "
        "assert 'main' not in sys.modules; "
        "import app.db_maintenance; "
        "import app.backup_settings; "
        "assert 'main' not in sys.modules"
    )
    env = os.environ.copy()
    env["APP_DATABASE"] = str(database_path)
    result = subprocess.run(
        [sys.executable, "-B", "-c", code],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert not database_path.exists()


def test_zero_lazy_bridge_and_explicit_bootstrap_binding_position():
    assert not hasattr(app_db, "_get_main_db_helpers")
    assert not hasattr(app_db, "_init_db_impl")

    init_source = inspect.getsource(app_db.init_db)
    assert "bind_backup_settings_runtime_app(runtime_app)" in init_source
    assert init_source.count("ensure_backup_settings_schema(conn)") == 1
    assert init_source.index("bind_backup_settings_runtime_app(runtime_app)") < init_source.index(
        "conn = get_db_connection()"
    )
    assert init_source.index("apply_early_schema_migrations(conn") < init_source.index(
        "ensure_backup_settings_schema(conn)"
    )
    assert "CREATE TABLE" not in init_source.upper()


def test_complete_one_argument_caller_and_application_context_contract():
    # UT-5 ownership correction: `_save_drive_config` is no longer a main-owned
    # body, so it can no longer appear as a main-local direct-call scope. The
    # pre-UT-5 expectation below listed it alongside the two genuinely
    # main-retained callers, which directly contradicts the UT-5 assertions that
    # main must NOT define `_save_drive_config`
    # (see test_cloud_retention_restore_and_runtime_consumers_remain_in_main).
    # The caller contract is corrected, not retired: the one-argument
    # `ensure_backup_settings_schema(conn)` call shape is still proved for every
    # remaining main-owned caller, and the `_save_drive_config` caller proof
    # simply moves to its new canonical owner below.
    assert _direct_call_scopes(main, "ensure_backup_settings_schema") == ()
    assert _direct_call_scopes(banco_dados_module, "ensure_backup_settings_schema") == (
        "save_backup_settings",
        "save_retention_policy",
    )
    assert _direct_call_scopes(app_db, "ensure_backup_settings_schema") == (
        "init_db",
    )

    # The retired main-local scope must reappear at the canonical owner -- the
    # call is relocated, never dropped -- and main's compatibility surface must
    # be an identity alias rather than a divergent re-implementation.
    from app.backup import orchestrator as backup_orchestrator

    assert _direct_call_scopes(
        backup_orchestrator, "ensure_backup_settings_schema"
    ) == ("_save_drive_config",)
    assert "_save_drive_config" in _top_level_function_names(backup_orchestrator)
    assert "_save_drive_config" not in _top_level_function_names(main)
    assert main._save_drive_config is backup_orchestrator._save_drive_config

    runtime_source = inspect.getsource(backup_settings)
    assert "current_app" not in runtime_source
    assert "import main" not in runtime_source
    app = _runtime_app()
    conn = _memory_connection()
    backup_settings._runtime_backup_settings_app = None
    with pytest.raises(RuntimeError, match="runtime app has not been bound"):
        backup_settings.ensure_backup_settings_schema(conn)
    backup_settings.bind_backup_settings_runtime_app(app)
    backup_settings.ensure_backup_settings_schema(conn)


def test_bound_main_app_wins_over_distinct_current_app_and_preserves_legacy_normalization():
    bound_app = _runtime_app()
    active_app = Flask("distinct-current-app")
    active_app.config.update(
        LOCAL_BACKUP_DIR="C:/wrong/local",
        CLOUD_BACKUP_DIR="C:/wrong/cloud",
        CLOUD_SYNC_INTERVAL_SECONDS=123,
        EXTERNAL_BACKUP_URL="https://wrong.example.test",
        EXTERNAL_BACKUP_TOKEN="wrong-token",
        EXTERNAL_BACKUP_ENABLED=False,
    )
    active_before = dict(active_app.config)
    conn = _memory_connection()
    db_maintenance.ensure_backup_settings_structural_schema(conn)
    conn.execute(
        "INSERT INTO configuracoes_backup (chave, valor) VALUES (?, ?)",
        ("cloud_sync_interval_seconds", " 300 "),
    )

    with active_app.app_context():
        backup_settings.ensure_backup_settings_schema(conn)

    assert _table_rows(conn) == EXACT_DEFAULTS
    assert {
        "local_backup_dir": str(bound_app.config["LOCAL_BACKUP_DIR"]),
        "cloud_backup_dir": str(bound_app.config["CLOUD_BACKUP_DIR"]),
        "cloud_sync_interval_seconds": str(
            bound_app.config["CLOUD_SYNC_INTERVAL_SECONDS"]
        ),
        "external_backup_url": str(bound_app.config["EXTERNAL_BACKUP_URL"]),
        "external_backup_token": str(bound_app.config["EXTERNAL_BACKUP_TOKEN"]),
        "external_backup_enabled": (
            "1" if bound_app.config["EXTERNAL_BACKUP_ENABLED"] else "0"
        ),
    } == EXACT_DEFAULTS
    assert dict(active_app.config) == active_before


def test_main_binds_its_exact_module_app_without_an_import_cycle(tmp_path):
    database_path = tmp_path / "binding-import.db"
    code = (
        "import main; "
        "import app.backup_settings as settings; "
        "assert settings._runtime_backup_settings_app is main.app"
    )
    env = os.environ.copy()
    env.update(
        APP_DATABASE=str(database_path),
        APP_UPLOAD_FOLDER=str(tmp_path / "uploads"),
        APP_DOCUMENTOS_ALUNOS_FOLDER=str(tmp_path / "documents"),
        APP_LOCAL_BACKUP_DIR=str(tmp_path / "backups" / "local"),
        APP_CLOUD_BACKUP_DIR=str(tmp_path / "backups" / "cloud"),
        APP_LOG_DIR=str(tmp_path / "logs"),
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", code],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert not database_path.exists()


def test_structural_helper_exact_schema_idempotence_and_neutrality():
    conn = _memory_connection()
    traced = []
    conn.set_trace_callback(traced.append)

    db_maintenance.ensure_backup_settings_structural_schema(conn)
    db_maintenance.ensure_backup_settings_structural_schema(conn)

    columns = [
        (row["name"], row["type"], row["notnull"], row["dflt_value"], row["pk"])
        for row in conn.execute("PRAGMA table_info(configuracoes_backup)").fetchall()
    ]
    assert columns == [
        ("chave", "TEXT", 0, None, 1),
        ("valor", "TEXT", 1, None, 0),
        ("atualizado_em", "TEXT", 1, "datetime('now')", 0),
    ]
    table_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'configuracoes_backup'"
    ).fetchone()["sql"]
    assert "chave TEXT PRIMARY KEY" in table_sql
    assert "valor TEXT NOT NULL" in table_sql
    assert "atualizado_em TEXT NOT NULL DEFAULT (datetime('now'))" in table_sql
    assert not conn.in_transaction

    mutating_sql = "\n".join(traced).upper()
    assert "INSERT " not in mutating_sql
    assert "UPDATE " not in mutating_sql
    assert "DELETE " not in mutating_sql
    _assert_no_transaction_ownership(
        db_maintenance.ensure_backup_settings_structural_schema
    )


def test_structural_helper_never_reads_flask_configuration():
    conn = _memory_connection()
    db_maintenance.ensure_backup_settings_structural_schema(conn)
    assert conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'configuracoes_backup'"
    ).fetchone()[0] == 1


def test_runtime_derived_defaults_exact_sources_and_conversions():
    app = _runtime_app()
    with app.app_context():
        assert backup_settings._backup_settings_defaults() == EXACT_DEFAULTS

        app.config.update(
            LOCAL_BACKUP_DIR=None,
            CLOUD_BACKUP_DIR="",
            CLOUD_SYNC_INTERVAL_SECONDS=0,
            EXTERNAL_BACKUP_URL=None,
            EXTERNAL_BACKUP_TOKEN="",
            EXTERNAL_BACKUP_ENABLED=False,
        )
        assert backup_settings._backup_settings_defaults() == {
            "local_backup_dir": "",
            "cloud_backup_dir": "",
            "cloud_sync_interval_seconds": "600",
            "external_backup_url": "",
            "external_backup_token": "",
            "external_backup_enabled": "0",
        }


def test_default_seeding_exact_rows_is_idempotent_and_has_no_ddl():
    conn = _memory_connection()
    db_maintenance.ensure_backup_settings_structural_schema(conn)
    traced = []
    conn.set_trace_callback(traced.append)

    backup_settings.seed_backup_settings_default_data(conn, EXACT_DEFAULTS)
    conn.execute(
        "UPDATE configuracoes_backup SET valor = 'custom' WHERE chave = 'local_backup_dir'"
    )
    backup_settings.seed_backup_settings_default_data(conn, EXACT_DEFAULTS)

    expected = dict(EXACT_DEFAULTS)
    expected["local_backup_dir"] = "custom"
    assert _table_rows(conn) == expected
    assert not any(key.startswith("retention_") for key in _table_rows(conn))
    assert not any(key.startswith(("gdrive_", "onedrive_")) for key in _table_rows(conn))
    assert "CREATE TABLE" not in "\n".join(traced).upper()


def test_legacy_normalization_only_stripped_literal_300_and_updates_timestamp():
    conn = _memory_connection()
    db_maintenance.ensure_backup_settings_structural_schema(conn)
    conn.execute(
        "INSERT INTO configuracoes_backup (chave, valor, atualizado_em) VALUES (?, ?, ?)",
        ("cloud_sync_interval_seconds", " 300 ", "2000-01-01 00:00:00"),
    )
    backup_settings.normalize_legacy_backup_sync_interval(conn, EXACT_DEFAULTS)
    row = conn.execute(
        "SELECT valor, atualizado_em FROM configuracoes_backup WHERE chave = 'cloud_sync_interval_seconds'"
    ).fetchone()
    assert row["valor"] == "900"
    assert row["atualizado_em"] != "2000-01-01 00:00:00"

    for value in ("", "0", "299", "0300", "300.0", "600", "invalid"):
        conn.execute(
            "UPDATE configuracoes_backup SET valor = ?, atualizado_em = '2000-01-01 00:00:00' WHERE chave = 'cloud_sync_interval_seconds'",
            (value,),
        )
        backup_settings.normalize_legacy_backup_sync_interval(conn, EXACT_DEFAULTS)
        preserved = conn.execute(
            "SELECT valor, atualizado_em FROM configuracoes_backup WHERE chave = 'cloud_sync_interval_seconds'"
        ).fetchone()
        assert (preserved["valor"], preserved["atualizado_em"]) == (
            value,
            "2000-01-01 00:00:00",
        )


def test_legacy_normalization_has_no_ddl_or_runtime_mutation():
    app = _runtime_app()
    conn = _memory_connection()
    db_maintenance.ensure_backup_settings_structural_schema(conn)
    conn.execute(
        "INSERT INTO configuracoes_backup (chave, valor) VALUES ('cloud_sync_interval_seconds', '300')"
    )
    traced = []
    conn.set_trace_callback(traced.append)
    before = dict(app.config)
    backup_settings.normalize_legacy_backup_sync_interval(conn, EXACT_DEFAULTS)
    assert dict(app.config) == before
    assert "CREATE TABLE" not in "\n".join(traced).upper()


def test_read_merge_preserves_defaults_overrides_unknown_keys_and_strings():
    conn = _memory_connection()
    db_maintenance.ensure_backup_settings_structural_schema(conn)
    assert backup_settings.read_backup_settings(conn, EXACT_DEFAULTS) == EXACT_DEFAULTS

    conn.executemany(
        "INSERT INTO configuracoes_backup (chave, valor) VALUES (?, ?)",
        (("local_backup_dir", "persisted"), ("unknown_key", "42")),
    )
    merged = backup_settings.read_backup_settings(conn, EXACT_DEFAULTS)
    assert merged["local_backup_dir"] == "persisted"
    assert merged["unknown_key"] == "42"
    assert set(EXACT_DEFAULTS) <= set(merged)
    assert all(isinstance(value, str) for value in merged.values())


def test_public_get_settings_resolves_defaults_once_and_merges(monkeypatch):
    conn = object()
    calls = []
    monkeypatch.setattr(
        backup_settings,
        "_backup_settings_defaults",
        lambda: calls.append("defaults") or EXACT_DEFAULTS,
    )
    monkeypatch.setattr(
        backup_settings,
        "read_backup_settings",
        lambda actual_conn, defaults: calls.append(("read", actual_conn, defaults))
        or {"merged": "yes"},
    )
    assert backup_settings.get_backup_settings(conn) == {"merged": "yes"}
    assert calls == ["defaults", ("read", conn, EXACT_DEFAULTS)]


@pytest.mark.parametrize(
    ("raw", "expected"),
    (("15", 15), ("-8", 0), ("", 600), ("invalid", 600), (None, 600)),
)
def test_runtime_application_interval_coercion(raw, expected):
    app = _runtime_app()
    settings = dict(EXACT_DEFAULTS, cloud_sync_interval_seconds=raw)
    with app.app_context():
        backup_settings._apply_backup_settings_to_app(settings)
        assert app.config["CLOUD_SYNC_INTERVAL_SECONDS"] == expected


def test_runtime_application_exact_path_url_token_and_blank_rules():
    app = _runtime_app()
    with app.app_context():
        backup_settings._apply_backup_settings_to_app(
            {
                "local_backup_dir": "",
                "cloud_backup_dir": "",
                "cloud_sync_interval_seconds": "60",
                "external_backup_url": "",
                "external_backup_token": "",
                "external_backup_enabled": "0",
            }
        )
        assert app.config["LOCAL_BACKUP_DIR"] == "C:/runtime/local"
        assert app.config["CLOUD_BACKUP_DIR"] == ""
        assert app.config["EXTERNAL_BACKUP_URL"] == ""
        assert app.config["EXTERNAL_BACKUP_TOKEN"] == ""
        assert app.config["EXTERNAL_BACKUP_ENABLED"] is False


@pytest.mark.parametrize(
    ("raw", "expected"),
    (
        ("1", True),
        ("true", True),
        ("True", True),
        ("TRUE", False),
        ("on", False),
        ("yes", False),
        ("0", False),
        ("", False),
        (None, False),
    ),
)
def test_runtime_application_exact_enabled_interpretation(raw, expected):
    app = _runtime_app()
    with app.app_context():
        backup_settings._apply_backup_settings_to_app(
            dict(EXACT_DEFAULTS, external_backup_enabled=raw)
        )
        assert app.config["EXTERNAL_BACKUP_ENABLED"] is expected


def test_orchestrator_exact_component_order(monkeypatch):
    conn = object()
    settings = {"merged": "settings"}
    calls = []

    monkeypatch.setattr(
        backup_settings,
        "ensure_backup_settings_structural_schema",
        lambda actual: calls.append(("structural", actual)),
    )
    monkeypatch.setattr(
        backup_settings,
        "_backup_settings_defaults",
        lambda: calls.append(("defaults",)) or EXACT_DEFAULTS,
    )
    monkeypatch.setattr(
        backup_settings,
        "seed_backup_settings_default_data",
        lambda actual, defaults: calls.append(("seed", actual, defaults)),
    )
    monkeypatch.setattr(
        backup_settings,
        "normalize_legacy_backup_sync_interval",
        lambda actual, defaults: calls.append(("normalize", actual, defaults)),
    )
    monkeypatch.setattr(
        backup_settings,
        "read_backup_settings",
        lambda actual, defaults: calls.append(("read", actual, defaults)) or settings,
    )
    monkeypatch.setattr(
        backup_settings,
        "_apply_backup_settings_to_app",
        lambda actual: calls.append(("apply", actual)),
    )

    backup_settings.ensure_backup_settings_schema(conn)
    assert calls == [
        ("structural", conn),
        ("defaults",),
        ("seed", conn, EXACT_DEFAULTS),
        ("normalize", conn, EXACT_DEFAULTS),
        ("read", conn, EXACT_DEFAULTS),
        ("apply", settings),
    ]


def test_success_transaction_matrix_clean_outer_repeat_and_caller_rollback():
    app = _runtime_app()

    clean = _memory_connection()
    with app.app_context():
        backup_settings.ensure_backup_settings_schema(clean)
        assert clean.in_transaction
        assert _table_rows(clean) == EXACT_DEFAULTS
        backup_settings.ensure_backup_settings_schema(clean)
        assert _table_rows(clean) == EXACT_DEFAULTS
        clean.rollback()
        assert not clean.in_transaction
        assert _table_rows(clean) == {}

    outer = _memory_connection()
    outer.execute("BEGIN")
    with app.app_context():
        backup_settings.ensure_backup_settings_schema(outer)
        assert outer.in_transaction
        outer.rollback()
        assert not outer.in_transaction
        assert outer.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='configuracoes_backup'"
        ).fetchone()[0] == 1


def test_failure_before_any_dml_propagates_without_transaction_or_runtime_effect(monkeypatch):
    app = _runtime_app()
    conn = _memory_connection()
    before = dict(app.config)
    error = RuntimeError("structural-failure")
    monkeypatch.setattr(
        backup_settings,
        "ensure_backup_settings_structural_schema",
        lambda _conn: (_ for _ in ()).throw(error),
    )
    with app.app_context(), pytest.raises(RuntimeError) as caught:
        backup_settings.ensure_backup_settings_schema(conn)
    assert caught.value is error
    assert not conn.in_transaction
    assert dict(app.config) == before


def test_failure_during_seed_preserves_partial_caller_owned_work(monkeypatch):
    app = _runtime_app()
    conn = _memory_connection()
    before = dict(app.config)
    error = RuntimeError("seed-failure")

    def failing_seed(actual_conn, defaults):
        actual_conn.execute(
            "INSERT INTO configuracoes_backup (chave, valor) VALUES (?, ?)",
            next(iter(defaults.items())),
        )
        raise error

    monkeypatch.setattr(backup_settings, "seed_backup_settings_default_data", failing_seed)
    with app.app_context(), pytest.raises(RuntimeError) as caught:
        backup_settings.ensure_backup_settings_schema(conn)
    assert caught.value is error
    assert conn.in_transaction
    assert len(_table_rows(conn)) == 1
    assert dict(app.config) == before


def test_failure_during_legacy_normalization_preserves_seeded_work(monkeypatch):
    app = _runtime_app()
    conn = _memory_connection()
    before = dict(app.config)
    error = RuntimeError("normalize-failure")
    monkeypatch.setattr(
        backup_settings,
        "normalize_legacy_backup_sync_interval",
        lambda *_args: (_ for _ in ()).throw(error),
    )
    with app.app_context(), pytest.raises(RuntimeError) as caught:
        backup_settings.ensure_backup_settings_schema(conn)
    assert caught.value is error
    assert conn.in_transaction
    assert _table_rows(conn) == EXACT_DEFAULTS
    assert dict(app.config) == before


def test_failure_during_settings_read_preserves_seeded_work(monkeypatch):
    app = _runtime_app()
    conn = _memory_connection()
    before = dict(app.config)
    error = RuntimeError("read-failure")
    monkeypatch.setattr(
        backup_settings,
        "read_backup_settings",
        lambda *_args: (_ for _ in ()).throw(error),
    )
    with app.app_context(), pytest.raises(RuntimeError) as caught:
        backup_settings.ensure_backup_settings_schema(conn)
    assert caught.value is error
    assert conn.in_transaction
    assert _table_rows(conn) == EXACT_DEFAULTS
    assert dict(app.config) == before


def test_failure_during_runtime_apply_preserves_database_and_partial_runtime_effect(monkeypatch):
    app = _runtime_app()
    conn = _memory_connection()
    error = RuntimeError("apply-failure")

    def failing_apply(settings):
        app.config["LOCAL_BACKUP_DIR"] = settings["local_backup_dir"]
        raise error

    monkeypatch.setattr(backup_settings, "_apply_backup_settings_to_app", failing_apply)
    with app.app_context(), pytest.raises(RuntimeError) as caught:
        backup_settings.ensure_backup_settings_schema(conn)
    assert caught.value is error
    assert conn.in_transaction
    assert _table_rows(conn) == EXACT_DEFAULTS
    assert app.config["LOCAL_BACKUP_DIR"] == EXACT_DEFAULTS["local_backup_dir"]


def test_all_extracted_components_remain_transaction_neutral():
    for function in (
        db_maintenance.ensure_backup_settings_structural_schema,
        backup_settings.seed_backup_settings_default_data,
        backup_settings.normalize_legacy_backup_sync_interval,
        backup_settings.read_backup_settings,
        backup_settings._apply_backup_settings_to_app,
        backup_settings.ensure_backup_settings_schema,
        backup_settings.get_backup_settings,
    ):
        _assert_no_transaction_ownership(function)


def test_runtime_orchestrator_has_no_directory_network_cloud_or_oauth_effects():
    source = inspect.getsource(backup_settings.ensure_backup_settings_schema)
    forbidden = (
        "makedirs",
        "mkdir",
        "requests",
        "upload",
        "snapshot",
        "restore",
        "delete",
        "oauth",
        "google",
        "onedrive",
    )
    assert not any(fragment in source.lower() for fragment in forbidden)



# UT-5 retargets this control's ownership split: get_retention_policy,
# _save_drive_config, _get_runtime_backup_settings and _maybe_upload_to_drives
# move from main to app.backup.orchestrator (see tests/test_ut5_backup_package.py
# for the full canonical-symbol list). UT-8 relocates save_backup_settings,
# save_retention_policy and _restore_database_from_source to
# app/views/admin/banco_dados.py; main re-exports each by identity only. No
# ownership assertion is deleted -- the previously main-retained subset is
# asserted on its new canonical owner and its main presence becomes an identity
# facade, while the future-orchestrator-owned subset stays asserted absent from
# main and present as bodies on app.backup.orchestrator.
FUTURE_ORCHESTRATOR_OWNED_NAMES = frozenset(
    {
        "get_retention_policy",
        "_save_drive_config",
        "_get_runtime_backup_settings",
        "_maybe_upload_to_drives",
    }
)


def test_cloud_retention_restore_and_runtime_consumers_remain_in_main():
    main_names = _top_level_function_names(main)
    banco_dados_names = _top_level_function_names(banco_dados_module)
    assert {
        "save_backup_settings",
        "save_retention_policy",
        "_restore_database_from_source",
    } <= banco_dados_names, (
        "app/views/admin/banco_dados.py must own the backup-settings consumer "
        "bodies relocated from main"
    )
    assert not (
        {
            "save_backup_settings",
            "save_retention_policy",
            "_restore_database_from_source",
        }
        & main_names
    ), "main must no longer locally define the relocated banco_dados helpers"
    assert main.save_backup_settings is banco_dados_module.save_backup_settings
    assert main.save_retention_policy is banco_dados_module.save_retention_policy
    assert main._restore_database_from_source is banco_dados_module._restore_database_from_source

    still_in_main = FUTURE_ORCHESTRATOR_OWNED_NAMES & main_names
    assert not still_in_main, (
        f"UT-5 expects {sorted(FUTURE_ORCHESTRATOR_OWNED_NAMES)} to move to "
        f"app.backup.orchestrator; still main-owned: {sorted(still_in_main)}"
    )

    from app.backup import orchestrator as backup_orchestrator

    orchestrator_names = _top_level_function_names(backup_orchestrator)
    assert FUTURE_ORCHESTRATOR_OWNED_NAMES <= orchestrator_names, (
        f"app.backup.orchestrator missing bodies for: "
        f"{sorted(FUTURE_ORCHESTRATOR_OWNED_NAMES - orchestrator_names)}"
    )

    assert "ensure_cloud_backup_schema" not in main_names
    assert main.ensure_cloud_backup_schema is app_db.ensure_cloud_backup_schema

    runtime_source = inspect.getsource(backup_settings).lower()
    for table in ("cloud_accounts", "backup_logs", "cloud_drive_settings"):
        assert table not in runtime_source
    assert "encrypt_token" not in runtime_source
    assert "decrypt_token" not in runtime_source
