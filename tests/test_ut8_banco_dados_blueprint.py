"""UT-8 RED — Banco de Dados cohort extraction contract.

Future canonical owner: ``app/views/admin/banco_dados.py``.

Authoritative relocated-symbol manifest (46 symbols):
- 20 routes (LegacyRouteSpec-preserving);
- 24 cohort-exclusive helpers;
- 2 cohort-exclusive constants.

This file contains exactly 20 collected tests:
- tests ``test_red_a``..``test_red_j`` are FUTURE ARCHITECTURAL CONTRACT
  assertions; while the target module is absent they fail with plain
  AssertionError only (no ImportError / ModuleNotFoundError / AttributeError);
- tests ``test_green_1``..``test_green_10`` characterize CURRENT behavior and
  detector quality that implementation is forbidden to change.

Collection-safety rule: the future module is imported only through a guarded
loader after its file existence is established; sentinels are used instead of
exception-based RED signals.
"""

from __future__ import annotations

import ast
import os
import secrets
import sys
from pathlib import Path

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from app import db as app_db_module
from tests.conftest import PYTEST_RUNTIME_ROOT

import main


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TARGET_PATH = PROJECT_ROOT / "app" / "views" / "admin" / "banco_dados.py"
TARGET_REL = "app/views/admin/banco_dados.py"
TARGET_MODULE_NAME = "app.views.admin.banco_dados"
MAIN_PATH = PROJECT_ROOT / "main.py"
CREATE_APP_PATH = PROJECT_ROOT / "app" / "__init__.py"
BUSINESS_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}

ROUTE_NAMES = (
    "admin_banco_dados",
    "admin_backup_google_connect",
    "google_callback",
    "admin_backup_google_upload",
    "admin_backup_onedrive_connect",
    "onedrive_callback",
    "admin_backup_onedrive_upload",
    "admin_backup_cloud_folders",
    "admin_backup_cloud_folder",
    "admin_banco_dados_configuracoes",
    "admin_banco_dados_retencao",
    "admin_banco_dados_oauth_start",
    "auth_callback",
    "admin_banco_dados_oauth_disconnect",
    "admin_banco_dados_drive_settings",
    "admin_banco_dados_backup",
    "admin_banco_dados_download",
    "admin_banco_dados_excluir",
    "admin_banco_dados_restaurar",
    "admin_banco_dados_restaurar_upload",
)

HELPER_NAMES = (
    "_normalize_backup_directory",
    "save_backup_settings",
    "save_retention_policy",
    "_normalize_cloud_folder_provider",
    "_save_cloud_drive_folder_setting",
    "_get_cloud_drive_folder_setting",
    "_extract_oauth_scopes",
    "_set_active_cloud_account",
    "_get_active_cloud_account",
    "_require_cloud_token_encryption_ready",
    "_update_cloud_account_token",
    "_record_backup_log",
    "_list_backup_logs",
    "_format_drive_timestamp",
    "_build_database_admin_context",
    "_maybe_redirect_to_oauth_callback_host",
    "_clear_legacy_oauth_session",
    "_resolve_onedrive_redirect_uri",
    "_resolve_google_redirect_uri",
    "_onedrive_connect_diagnostics",
    "_build_oauth_redirect_context",
    "_get_cloud_folder_account",
    "_get_current_schema_status_for_restore",
    "_restore_database_from_source",
)

CONSTANT_NAMES = (
    "_RETENTION_INTERVAL_OPTIONS",
    "_CLOUD_FOLDER_PROVIDERS",
)

MOVED_SYMBOLS = ROUTE_NAMES + HELPER_NAMES + CONSTANT_NAMES

ROUTE_MATRIX = (
    ("/admin/banco-dados", "admin_banco_dados", ("GET",)),
    ("/admin/backup/google/connect", "admin_backup_google_connect", ("GET",)),
    ("/google/callback", "google_callback", ("GET",)),
    ("/admin/backup/google/upload", "admin_backup_google_upload", ("POST",)),
    ("/admin/backup/onedrive/connect", "admin_backup_onedrive_connect", ("GET",)),
    ("/onedrive/callback", "onedrive_callback", ("GET",)),
    ("/admin/backup/onedrive/upload", "admin_backup_onedrive_upload", ("POST",)),
    ("/admin/backup/cloud-folders/<provider>", "admin_backup_cloud_folders", ("GET",)),
    ("/admin/backup/cloud-folder/<provider>", "admin_backup_cloud_folder", ("GET", "POST")),
    ("/admin/banco-dados/configuracoes", "admin_banco_dados_configuracoes", ("POST",)),
    ("/admin/banco-dados/retencao", "admin_banco_dados_retencao", ("POST",)),
    ("/admin/banco-dados/oauth/start", "admin_banco_dados_oauth_start", ("GET",)),
    ("/auth/callback", "auth_callback", ("GET",)),
    ("/admin/banco-dados/oauth/disconnect", "admin_banco_dados_oauth_disconnect", ("POST",)),
    ("/admin/banco-dados/drive-settings", "admin_banco_dados_drive_settings", ("POST",)),
    ("/admin/banco-dados/backup", "admin_banco_dados_backup", ("POST",)),
    ("/admin/banco-dados/download", "admin_banco_dados_download", ("GET",)),
    ("/admin/banco-dados/excluir", "admin_banco_dados_excluir", ("POST",)),
    ("/admin/banco-dados/restaurar", "admin_banco_dados_restaurar", ("POST",)),
    ("/admin/banco-dados/restaurar/upload", "admin_banco_dados_restaurar_upload", ("POST",)),
)

EXPECTED_PAIRS = frozenset(
    (rule, endpoint, methods) for rule, endpoint, methods in ROUTE_MATRIX
)

RBAC_MATRIX = {
    "admin_banco_dados": ("banco_dados", "view"),
    "admin_backup_google_connect": ("banco_dados", "edit"),
    "google_callback": ("banco_dados", "edit"),
    "admin_backup_google_upload": ("banco_dados", "edit"),
    "admin_backup_onedrive_connect": ("banco_dados", "edit"),
    "onedrive_callback": ("banco_dados", "edit"),
    "admin_backup_onedrive_upload": ("banco_dados", "edit"),
    "admin_backup_cloud_folders": ("banco_dados", "edit"),
    "admin_backup_cloud_folder": ("banco_dados", "edit"),
    "admin_banco_dados_configuracoes": ("banco_dados", "edit"),
    "admin_banco_dados_retencao": ("banco_dados", "edit"),
    "admin_banco_dados_oauth_start": ("banco_dados", "edit"),
    "auth_callback": ("banco_dados", "edit"),
    "admin_banco_dados_oauth_disconnect": ("banco_dados", "edit"),
    "admin_banco_dados_drive_settings": ("banco_dados", "edit"),
    "admin_banco_dados_backup": ("banco_dados", "edit"),
    "admin_banco_dados_download": ("banco_dados", "view"),
    "admin_banco_dados_excluir": ("banco_dados", "full"),
    "admin_banco_dados_restaurar": ("banco_dados", "full"),
    "admin_banco_dados_restaurar_upload": ("banco_dados", "full"),
}

COHORT_RULE_PREFIXES = (
    "/admin/banco-dados",
    "/admin/backup",
    "/google/callback",
    "/onedrive/callback",
    "/auth/callback",
)


# ---------------------------------------------------------------------------
# Guarded loaders / AST scanners (detector self-control lives in green test 1)
# ---------------------------------------------------------------------------


def _target_module():
    """Return the future module, or None while its file does not exist.

    The import is performed only after file existence is established, so a
    missing target yields None (asserted by callers) instead of an
    ImportError-based RED signal.
    """
    if not TARGET_PATH.exists():
        return None
    import importlib

    return importlib.import_module(TARGET_MODULE_NAME)


def _top_level_defs(source: str) -> set[str]:
    tree = ast.parse(source)
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _top_level_assignments(source: str) -> set[str]:
    tree = ast.parse(source)
    names = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _top_level_import_sources(source: str) -> set[str]:
    tree = ast.parse(source)
    sources = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            sources.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            sources.add(node.module or "")
    return sources


def _cohort_route_decorators(source: str) -> list[str]:
    tree = ast.parse(source)
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and isinstance(decorator.func.value, ast.Name)
                and decorator.func.value.id == "app"
                and decorator.func.attr == "route"
                and decorator.args
                and isinstance(decorator.args[0], ast.Constant)
            ):
                continue
            rule = str(decorator.args[0].value)
            if rule.startswith(COHORT_RULE_PREFIXES):
                hits.append(rule)
    return hits


def _route_decorator_calls(source: str) -> list[str]:
    tree = ast.parse(source)
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute):
                if decorator.func.attr == "route":
                    hits.append(ast.unparse(decorator))
    return hits


def _main_back_edges(source: str) -> list[tuple[str, str, int]]:
    tree = ast.parse(source)
    edges: list[tuple[str, str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "main" or alias.name.startswith("main."):
                    edges.append(("import", alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.module and (node.module == "main" or node.module.startswith("main.")):
                edges.append(("from", node.module, node.lineno))
        elif isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id in {"importlib", "import_module"}
            ):
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and str(arg.value) == "main":
                        edges.append(("dynamic-import", "main", node.lineno))
            if (
                isinstance(func, ast.Name)
                and func.id == "__import__"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and str(node.args[0].value) == "main"
            ):
                edges.append(("__import__", "main", node.lineno))
        elif isinstance(node, ast.Subscript):
            value = node.value
            if (
                isinstance(value, ast.Attribute)
                and isinstance(value.value, ast.Name)
                and value.value.id == "sys"
                and value.attr == "modules"
                and isinstance(node.slice, ast.Constant)
                and str(node.slice.value) == "main"
            ):
                edges.append(("sys.modules", "main", node.lineno))
    return edges


def _cohort_rules(app):
    return {
        (
            rule.rule,
            rule.endpoint,
            tuple(sorted(set(rule.methods or ()) & BUSINESS_METHODS)),
        )
        for rule in app.url_map.iter_rules()
        if rule.endpoint in ROUTE_NAMES
    }


# ---------------------------------------------------------------------------
# Isolated runtime fixture (never touches canonical database.db)
# ---------------------------------------------------------------------------


@pytest.fixture()
def isolated_env(monkeypatch):
    sub_root = Path(str(PYTEST_RUNTIME_ROOT)).resolve() / f"ut8-red-{secrets.token_hex(6)}"
    sub_root.mkdir(parents=True, exist_ok=True)
    sub_root.resolve().relative_to(PYTEST_RUNTIME_ROOT.resolve())

    temp_database = sub_root / "test.db"
    temp_uploads = sub_root / "uploads"
    temp_documents = sub_root / "documentos_alunos"
    temp_local_backup = sub_root / "backups" / "local"
    temp_cloud_backup = sub_root / "backups" / "cloud"
    temp_logs = sub_root / "logs"

    for directory in (
        temp_uploads,
        temp_documents,
        temp_local_backup,
        temp_cloud_backup,
        temp_logs,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    app = main.app
    guarded_keys = (
        "TESTING",
        "DATABASE_PATH",
        "UPLOAD_FOLDER",
        "DOCUMENTOS_ALUNOS_FOLDER",
        "LOCAL_BACKUP_DIR",
        "CLOUD_BACKUP_DIR",
        "CLOUD_SYNC_INTERVAL_SECONDS",
        "EXTERNAL_BACKUP_ENABLED",
        "BOOTSTRAP_DEFAULT_ADMIN",
    )
    original_config = {key: app.config.get(key) for key in guarded_keys}
    original_main_db = main.DATABASE
    original_app_db = app_db_module.DATABASE

    monkeypatch.setenv("APP_DATABASE", str(temp_database))
    monkeypatch.setenv("APP_UPLOAD_FOLDER", str(temp_uploads))
    monkeypatch.setenv("APP_DOCUMENTOS_ALUNOS_FOLDER", str(temp_documents))
    monkeypatch.setenv("APP_LOCAL_BACKUP_DIR", str(temp_local_backup))
    monkeypatch.setenv("APP_CLOUD_BACKUP_DIR", str(temp_cloud_backup))
    monkeypatch.setenv("APP_LOG_DIR", str(temp_logs))
    monkeypatch.setenv("APP_BOOTSTRAP_DEFAULT_ADMIN", "0")

    monkeypatch.setattr(main, "DATABASE", str(temp_database))
    monkeypatch.setattr(app_db_module, "DATABASE", str(temp_database))

    app.config["TESTING"] = True
    app.config["DATABASE_PATH"] = str(temp_database)
    app.config["UPLOAD_FOLDER"] = str(temp_uploads)
    app.config["DOCUMENTOS_ALUNOS_FOLDER"] = str(temp_documents)
    app.config["LOCAL_BACKUP_DIR"] = str(temp_local_backup)
    app.config["CLOUD_BACKUP_DIR"] = str(temp_cloud_backup)
    app.config["CLOUD_SYNC_INTERVAL_SECONDS"] = 0
    app.config["EXTERNAL_BACKUP_ENABLED"] = False
    app.config["BOOTSTRAP_DEFAULT_ADMIN"] = False

    with app.app_context():
        main.close_db_connection(None)
        main.init_db()

    with app.app_context():
        conn = main.get_db_connection()
        admin_password = main.hash_password("admin123")
        conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?)",
            ("Admin Total", "admin_total@ej.edu.br", admin_password, "admin", "admin_total"),
        )
        conn.execute("DELETE FROM configuracoes_backup")
        main.save_backup_settings(
            conn,
            {
                "local_backup_dir": str(temp_local_backup),
                "cloud_backup_dir": str(temp_cloud_backup),
                "cloud_sync_interval_seconds": "0",
                "external_backup_url": "",
                "external_backup_token": "",
                "external_backup_enabled": "0",
            },
        )
        conn.execute(
            "INSERT OR REPLACE INTO configuracoes_backup (chave, valor) VALUES (?, ?)",
            ("gdrive_enabled", "0"),
        )
        conn.execute(
            "INSERT OR REPLACE INTO configuracoes_backup (chave, valor) VALUES (?, ?)",
            ("onedrive_enabled", "0"),
        )
        conn.commit()

    client = app.test_client()

    try:
        yield client, sub_root
    finally:
        with app.app_context():
            main.close_db_connection(None)
        for key, value in original_config.items():
            if value is None:
                app.config.pop(key, None)
            else:
                app.config[key] = value
        main.DATABASE = original_main_db
        app_db_module.DATABASE = original_app_db


def _login(client) -> None:
    response = client.post(
        "/login",
        data={"email": "admin_total@ej.edu.br", "senha": "admin123"},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)


# ===========================================================================
# RED — future architectural contract (A..J)
# ===========================================================================


def test_red_a_target_module_file_exists():
    assert TARGET_PATH.exists(), (
        "app/views/admin/banco_dados.py does not exist yet; UT-8 must create it"
    )


def test_red_b_target_owns_exact_46_symbol_set_with_categories():
    target = _target_module()
    assert target is not None, "banco_dados module absent; 46-symbol ownership contract unsatisfiable"

    source = Path(target.__file__).read_text(encoding="utf-8")
    top_level = _top_level_defs(source)
    assigned = _top_level_assignments(source)

    assert top_level == set(ROUTE_NAMES) | set(HELPER_NAMES), (
        f"target top-level functions must be exactly the 44 moved callables; "
        f"missing={sorted((set(ROUTE_NAMES) | set(HELPER_NAMES)) - top_level)} "
        f"extra={sorted(top_level - (set(ROUTE_NAMES) | set(HELPER_NAMES)))}"
    )
    assert set(CONSTANT_NAMES) <= assigned, (
        f"target must own constants {set(CONSTANT_NAMES)}; missing="
        f"{sorted(set(CONSTANT_NAMES) - assigned)}"
    )


def test_red_c_target_owns_exactly_20_route_functions_admin_decorated():
    target = _target_module()
    assert target is not None, "banco_dados module absent; route-ownership contract unsatisfiable"

    source = Path(target.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert set(ROUTE_NAMES) <= set(functions)
    for name in ROUTE_NAMES:
        decorators = {ast.unparse(item) for item in functions[name].decorator_list}
        assert decorators == {"admin_required"}, (
            f"route {name} decorators must be exactly {{admin_required}}, got {decorators}"
        )
    assert _route_decorator_calls(source) == [], (
        "target must not contain any @app.route / @bp.route decorators; "
        "routes register through LegacyRouteSpec"
    )


def test_red_d_exactly_20_legacy_route_specs_21_pairs_frozen_matrix():
    target = _target_module()
    assert target is not None, "banco_dados module absent; LegacyRouteSpec contract unsatisfiable"

    specs = getattr(target, "LEGACY_ROUTE_SPECS", None)
    assert isinstance(specs, tuple), "target must expose an immutable LEGACY_ROUTE_SPECS tuple"
    assert len(specs) == 20, f"expected 20 LegacyRouteSpecs, got {len(specs)}"

    encoded = {(spec.rule, spec.endpoint, spec.methods) for spec in specs}
    assert encoded == EXPECTED_PAIRS, (
        f"spec set mismatch: missing={sorted(EXPECTED_PAIRS - encoded)} "
        f"extra={sorted(encoded - EXPECTED_PAIRS)}"
    )
    assert sum(len(spec.methods) for spec in specs) == 21, (
        "specs must represent exactly 21 endpoint/method pairs"
    )
    assert {spec.view_func for spec in specs} == {
        getattr(target, name) for name in ROUTE_NAMES
    }, "every spec must reference the target-owned route function"
    assert all("." not in spec.endpoint for spec in specs), (
        "no namespaced endpoint allowed"
    )


def test_red_e_main_no_longer_defines_moved_bodies_or_owns_constants():
    source = MAIN_PATH.read_text(encoding="utf-8")
    defined = _top_level_defs(source)
    assigned = _top_level_assignments(source)

    assert not (set(ROUTE_NAMES) | set(HELPER_NAMES)) & defined, (
        "main.py must no longer locally define moved callables: "
        f"{sorted((set(ROUTE_NAMES) | set(HELPER_NAMES)) & defined)}"
    )
    assert not set(CONSTANT_NAMES) & assigned, (
        "main.py must no longer locally own moved constants: "
        f"{sorted(set(CONSTANT_NAMES) & assigned)}"
    )
    assert _cohort_route_decorators(source) == [], (
        "main.py must no longer register any cohort @app.route decorator"
    )


def test_red_f_main_compatibility_facade_full_46_identity_no_wrappers():
    target = _target_module()
    assert target is not None, "banco_dados module absent; main compatibility contract unsatisfiable"

    for name in MOVED_SYMBOLS:
        assert hasattr(main, name), f"main.{name} missing from the compatibility facade"
        assert getattr(main, name) is getattr(target, name), (
            f"main.{name} must be the identical object exported by banco_dados "
            "(identity re-export, no wrapper)"
        )


def test_red_g_target_has_no_main_backedge():
    target = _target_module()
    assert target is not None, "banco_dados module absent; no-back-edge contract unsatisfiable"

    source = Path(target.__file__).read_text(encoding="utf-8")
    edges = _main_back_edges(source)
    assert edges == [], (
        "target must not import main (including dynamic-import equivalents): "
        f"{edges}"
    )


def test_red_h_create_app_factory_keyword_and_registration_present():
    tree = ast.parse(CREATE_APP_PATH.read_text(encoding="utf-8"))
    create_app = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "create_app"
    )

    kw_pairs = {
        arg.arg: default
        for arg, default in zip(create_app.args.kwonlyargs, create_app.args.kw_defaults)
    }
    assert "register_admin_banco_dados_blueprint" in kw_pairs, (
        "create_app must accept register_admin_banco_dados_blueprint"
    )
    default = kw_pairs["register_admin_banco_dados_blueprint"]
    assert isinstance(default, ast.Constant) and default.value is True, (
        "register_admin_banco_dados_blueprint must default to True"
    )

    registration_calls = [
        call
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "register_legacy_blueprint"
    ]
    assert any(
        any(
            isinstance(arg, ast.Name) and arg.id == "bp_admin_banco_dados"
            for arg in call.args
        )
        for call in registration_calls
    ), "create_app body must register bp_admin_banco_dados via register_legacy_blueprint"


def test_red_i_factory_default_registers_20_and_opt_out_registers_none():
    import inspect

    from app import create_app

    signature = inspect.signature(create_app)
    assert "register_admin_banco_dados_blueprint" in signature.parameters, (
        "factory parameter missing; default/opt-out contract unsatisfiable"
    )
    assert signature.parameters["register_admin_banco_dados_blueprint"].default is True, (
        "factory parameter must default to True"
    )

    default_app = create_app(
        register_presets_blueprint=False,
        register_aluno_blueprint=False,
    )
    opt_out_app = create_app(
        register_presets_blueprint=False,
        register_aluno_blueprint=False,
        register_admin_banco_dados_blueprint=False,
    )

    default_rules = {
        (rule.rule, rule.endpoint) for rule in default_app.url_map.iter_rules()
    }
    assert _cohort_rules(default_app) == EXPECTED_PAIRS, (
        "default factory must register exactly the 20 frozen routes / 21 pairs"
    )
    assert _cohort_rules(opt_out_app) == frozenset(), (
        "opt-out factory must register none of the 20 cohort endpoints"
    )
    assert not any(
        rule.endpoint.startswith("banco_dados_blueprint.") or "." in rule.endpoint
        for rule in default_app.url_map.iter_rules()
        if rule.endpoint in ROUTE_NAMES
    ), "no namespaced endpoint variant may exist"
    assert len(default_rules) > 0, "default factory sanity check"


def test_red_j_target_is_scanned_and_catalog_remains_536():
    from utils import messages

    catalog = messages._message_catalog()
    assert len(catalog) == 536, (
        "message catalog count must match the canonical baseline; "
        f"got {len(catalog)}"
    )

    backend_paths = {
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in messages._iter_backend_files()
    }
    views_files = {
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in (PROJECT_ROOT / "app" / "views").rglob("*.py")
        if "__pycache__" not in path.relative_to(PROJECT_ROOT).parts
    }
    assert views_files <= backend_paths, (
        "scanner self-control: every app/views/**/*.py must be in "
        "_iter_backend_files(); uncovered="
        f"{sorted(views_files - backend_paths)}"
    )
    assert TARGET_REL in backend_paths, (
        "app/views/admin/banco_dados.py must be inside backend message-scanner "
        "coverage once created"
    )


# ===========================================================================
# GREEN — current behavior / detector quality characterization
# ===========================================================================


def test_green_1_detector_self_control_top_level_vs_nested_and_import_sources():
    nested_source = "def outer():\n    def inner():\n        return 1\n"
    assert _top_level_defs(nested_source) == {"outer"}, (
        "top-level scanner must not count nested defs"
    )

    import_source = (
        "import os\n"
        "from app.auth import admin_required\n"
        "import app.cloud_drives as _cd\n"
    )
    sources = _top_level_import_sources(import_source)
    assert {"os", "app.auth", "app.cloud_drives"} <= sources, (
        "import-source scanner must distinguish plain and from-import sources"
    )

    dynamic_source = "import importlib\nmodule = importlib.import_module('main')\n"
    assert "main" not in _top_level_import_sources(dynamic_source), (
        "import-source scanner must not report dynamic importlib calls as "
        "top-level import sources"
    )

    init_source = CREATE_APP_PATH.read_text(encoding="utf-8")
    assert "app.views.admin" in _top_level_import_sources(init_source), (
        "production observation: app/__init__.py top-level imports must include "
        "app.views.admin"
    )


def test_green_2_live_route_matrix_20_routes_21_pairs():
    rules = [
        rule
        for rule in main.app.url_map.iter_rules()
        if rule.endpoint in ROUTE_NAMES
    ]
    assert len(rules) == 20, f"expected 20 live cohort rules, got {len(rules)}"
    assert _cohort_rules(main.app) == EXPECTED_PAIRS, (
        "live url_map must match the frozen 21-pair matrix"
    )


def test_green_3_live_rbac_requirements_2_view_16_edit_3_full():
    from app.auth import get_admin_permission_requirement

    for rule, endpoint, methods in ROUTE_MATRIX:
        for method in methods:
            assert get_admin_permission_requirement(endpoint, method) == RBAC_MATRIX[endpoint], (
                f"{endpoint} {method} requirement must stay "
                f"{RBAC_MATRIX[endpoint]}"
            )

    scope_counts = {"view": 0, "edit": 0, "full": 0}
    for rule, endpoint, methods in ROUTE_MATRIX:
        for method in methods:
            scope_counts[RBAC_MATRIX[endpoint][1]] += 1
    assert scope_counts == {"view": 2, "edit": 16, "full": 3}, (
        f"RBAC split must remain 2 view / 16 edit / 3 full, got {scope_counts}"
    )


def test_green_5_google_oauth_state_rejection_is_seam_free(isolated_env):
    client, _ = isolated_env
    _login(client)

    with client.session_transaction() as session:
        session["google_oauth_state"] = "expected-red-state"

    mismatched = client.get(
        "/google/callback?state=attacker-state&code=stolen-code",
        follow_redirects=False,
    )
    assert mismatched.status_code in (302, 303)
    assert mismatched.headers.get("Location") == "/admin/banco-dados", (
        "state mismatch must reject toward the banco-dados screen"
    )

    no_code = client.get("/google/callback?state=expected-red-state", follow_redirects=False)
    assert no_code.status_code in (302, 303)

    denied = client.get(
        "/google/callback?error=access_denied&error_description=app+in+test+mode",
        follow_redirects=False,
    )
    assert denied.status_code in (302, 303)
    assert denied.headers.get("Location") == "/admin/banco-dados"


def test_green_6_onedrive_oauth_rejection_paths_are_seam_free(isolated_env):
    client, _ = isolated_env
    _login(client)

    with client.session_transaction() as session:
        session["onedrive_oauth_state"] = "expected-red-state"

    mismatched = client.get(
        "/onedrive/callback?state=other-state&code=stolen-code",
        follow_redirects=False,
    )
    assert mismatched.status_code in (302, 303)
    assert mismatched.headers.get("Location") == "/admin/banco-dados", (
        "state mismatch must reject toward the banco-dados screen"
    )

    no_code = client.get("/onedrive/callback?state=expected-red-state", follow_redirects=False)
    assert no_code.status_code in (302, 303)

    denied = client.get("/onedrive/callback?error=access_denied", follow_redirects=False)
    assert denied.status_code in (302, 303)
    assert denied.headers.get("Location") == "/admin/banco-dados"


def test_green_7_cloud_folder_provider_contract_fails_closed_without_network(isolated_env):
    client, _ = isolated_env
    _login(client)

    google_unconnected = client.get("/admin/backup/cloud-folders/google")
    assert google_unconnected.status_code == 400
    payload = google_unconnected.get_json()
    assert payload["ok"] is False
    assert "Conecte o Google Drive" in payload["message"]

    onedrive_unconnected = client.get("/admin/backup/cloud-folders/onedrive")
    assert onedrive_unconnected.status_code == 400
    assert onedrive_unconnected.get_json()["ok"] is False

    invalid_provider = client.get("/admin/backup/cloud-folders/dropbox")
    assert invalid_provider.status_code == 400
    assert invalid_provider.get_json()["message"] == "Provedor inválido."

    folder_setting = client.get("/admin/backup/cloud-folder/google")
    assert folder_setting.status_code == 200
    setting = folder_setting.get_json()
    assert setting["ok"] is True
    assert setting["provider"] == "google"
    assert setting["folder_id"] == ""


def test_green_8_manual_backup_intercepted_at_orchestrator_seam_no_network(isolated_env, monkeypatch):
    from app.backup import orchestrator as backup_orchestrator

    client, sub_root = isolated_env
    _login(client)

    calls = []

    def _spy_sync(*args, **kwargs):
        calls.append(("sync", args, kwargs))
        return {"ok": True, "skipped": True, "reason": "ut8-red-spy"}

    def _spy_external(*args, **kwargs):
        calls.append(("external", args, kwargs))
        return {"ok": False, "skipped": True, "reason": "ut8-red-spy"}

    def _spy_retention(*args, **kwargs):
        calls.append(("retention", args, kwargs))
        return {"deleted": [], "errors": []}

    def _spy_drives(snapshot_path, *args, **kwargs):
        calls.append(("drives", snapshot_path, args, kwargs))
        return None

    monkeypatch.setattr(backup_orchestrator, "_maybe_sync_database_snapshot", _spy_sync)
    monkeypatch.setattr(
        backup_orchestrator, "_upload_snapshot_if_external_enabled", _spy_external
    )
    monkeypatch.setattr(backup_orchestrator, "_run_retention_cleanup", _spy_retention)
    monkeypatch.setattr(backup_orchestrator, "_maybe_upload_to_drives", _spy_drives)

    response = client.post("/admin/banco-dados/backup", follow_redirects=False)
    assert response.status_code in (302, 303)
    assert response.headers.get("Location") == "/admin/banco-dados"

    snapshots_dir = sub_root / "backups" / "local" / "snapshots"
    assert snapshots_dir.is_dir()
    db_files = sorted(snapshots_dir.glob("*.db"))
    json_files = sorted(snapshots_dir.glob("*.json"))
    assert len(db_files) == 1, f"expected 1 local snapshot .db, got {len(db_files)}"
    assert len(json_files) == 1, f"expected 1 local snapshot .json, got {len(json_files)}"

    sync_calls = [entry for entry in calls if entry[0] == "sync"]
    retention_calls = [entry for entry in calls if entry[0] == "retention"]
    drives_calls = [entry for entry in calls if entry[0] == "drives"]
    assert sync_calls, "orchestrator sync must be invoked by the manual backup route"
    assert retention_calls, "orchestrator retention cleanup must be invoked"
    assert drives_calls, "orchestrator drive upload must be invoked"
    assert Path(drives_calls[0][1]).resolve() == db_files[0].resolve(), (
        "drive upload must receive the freshly created local snapshot path"
    )


def test_green_10_message_catalog_536_and_views_recursive_coverage():
    from utils import messages

    assert len(messages._message_catalog()) == 536, (
        "current catalog baseline must be 541"
    )

    backend_paths = {
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in messages._iter_backend_files()
    }
    views_files = {
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in (PROJECT_ROOT / "app" / "views").rglob("*.py")
        if "__pycache__" not in path.relative_to(PROJECT_ROOT).parts
    }
    assert views_files <= backend_paths, (
        "scanner must recursively cover every app/views/**/*.py file: "
        f"uncovered={sorted(views_files - backend_paths)}"
    )
    assert "app/views/admin/configuracoes.py" in backend_paths, (
        "sanity: an existing admin view module must be inside scanner coverage"
    )
