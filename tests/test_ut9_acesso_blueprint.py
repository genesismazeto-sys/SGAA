"""UT-9 RED — Acesso cohort extraction contract.

Future canonical owner: ``app/views/admin/acesso.py``.

Authoritative relocated-symbol manifest (9 symbols):
- 6 routes (LegacyRouteSpec-preserving);
- 3 cohort-exclusive helpers;
- 0 cohort-exclusive constants.

This file contains exactly 26 collected tests:
- tests ``test_red_a``..``test_red_n`` are FUTURE ARCHITECTURAL CONTRACT
  assertions; while the target module is absent they fail with plain
  AssertionError only (no ImportError / ModuleNotFoundError / AttributeError /
  TypeError / fixture or collection error);
- tests ``test_green_1``..``test_green_12`` characterize CURRENT behavior and
  detector quality that implementation is forbidden to change.

Collection-safety rule: the future module is imported only through a guarded
loader after its file existence is established; sentinels are used instead of
exception-based RED signals. No parametrization changes the collected count.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import secrets
import sqlite3
import sys
from pathlib import Path

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from app import db as app_db_module
from app.auth import get_admin_permission_requirement
from tests.conftest import PYTEST_RUNTIME_ROOT

import main


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TARGET_PATH = PROJECT_ROOT / "app" / "views" / "admin" / "acesso.py"
TARGET_REL = "app/views/admin/acesso.py"
TARGET_MODULE_NAME = "app.views.admin.acesso"
MAIN_PATH = PROJECT_ROOT / "main.py"
CREATE_APP_PATH = PROJECT_ROOT / "app" / "__init__.py"
BUSINESS_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}

FROZEN_ENTRY_AUTH_SHA256 = (
    "f5aac76c78252cd9c3d48ae3d1a438a1fdc2bc008d12dd60c9bab336e26b51ce"
)

ROUTE_NAMES = (
    "admin_acesso",
    "admin_acesso_salvar_senhas_default",
    "admin_acesso_salvar",
    "admin_acesso_resetar_senha",
    "admin_acesso_definir_senha",
    "admin_acesso_deletar",
)

HELPER_NAMES = (
    "_persist_user_access_overrides",
    "_parse_access_overrides_from_form",
    "_turma_label_by_id",
)

CONSTANT_NAMES: tuple[str, ...] = ()

MOVED_SYMBOLS = ROUTE_NAMES + HELPER_NAMES + CONSTANT_NAMES

ROUTE_MATRIX = (
    ("/admin/acesso", "admin_acesso", ("GET",)),
    ("/admin/acesso/senhas-default", "admin_acesso_salvar_senhas_default", ("POST",)),
    ("/admin/acesso/salvar", "admin_acesso_salvar", ("POST",)),
    ("/admin/acesso/<int:usuario_id>/resetar-senha", "admin_acesso_resetar_senha", ("POST",)),
    ("/admin/acesso/definir-senha", "admin_acesso_definir_senha", ("POST",)),
    ("/admin/acesso/<int:usuario_id>/deletar", "admin_acesso_deletar", ("POST",)),
)

EXPECTED_PAIRS = frozenset(
    (rule, endpoint, methods) for rule, endpoint, methods in ROUTE_MATRIX
)

RBAC_MATRIX = {
    "admin_acesso": ("acesso", "view"),
    "admin_acesso_salvar_senhas_default": ("acesso", "full"),
    "admin_acesso_salvar": ("acesso", "full"),
    "admin_acesso_resetar_senha": ("acesso", "full"),
    "admin_acesso_definir_senha": ("acesso", "full"),
    "admin_acesso_deletar": ("acesso", "full"),
}

COHORT_RULE_PREFIXES = ("/admin/acesso",)

FIVE_POST_URLS = (
    "/admin/acesso/senhas-default",
    "/admin/acesso/salvar",
    "/admin/acesso/1/resetar-senha",
    "/admin/acesso/definir-senha",
    "/admin/acesso/1/deletar",
)

ACCESSO_POST_ROUTE_ENDPOINTS = {
    "/admin/acesso/senhas-default": "admin_acesso_salvar_senhas_default",
    "/admin/acesso/salvar": "admin_acesso_salvar",
    "/admin/acesso/<int:usuario_id>/resetar-senha": "admin_acesso_resetar_senha",
    "/admin/acesso/definir-senha": "admin_acesso_definir_senha",
    "/admin/acesso/<int:usuario_id>/deletar": "admin_acesso_deletar",
}

FROZEN_ACCESSO_ROW_SHAPE = {
    "/admin/acesso/senhas-default": {
        "csrf_in_html": True,
        "evidence": [
            {
                "action": "/admin/acesso/senhas-default",
                "kind": "rendered_form",
                "page": "/admin/acesso",
                "token_count": 1,
            }
        ],
        "fetch_sends_token": None,
        "has_dynamic_form": False,
        "has_fetch_post": False,
        "has_post_form": True,
        "method": "POST",
        "notes": [],
        "requires_login": "admin",
        "risk": [],
        "route": "/admin/acesso/senhas-default",
        "status": "ok_rendered_form_token",
        "template_related": [],
        "token_counts_per_form": [
            {
                "action": "/admin/acesso/senhas-default",
                "page": "/admin/acesso",
                "token_counts": [1],
            }
        ],
    },
    "/admin/acesso/salvar": {
        "csrf_in_html": True,
        "evidence": [
            {
                "action": "/admin/acesso/salvar",
                "kind": "rendered_form",
                "page": "/admin/acesso",
                "token_count": 1,
            }
        ],
        "fetch_sends_token": None,
        "has_dynamic_form": False,
        "has_fetch_post": False,
        "has_post_form": True,
        "method": "POST",
        "notes": [],
        "requires_login": "admin",
        "risk": [],
        "route": "/admin/acesso/salvar",
        "status": "ok_rendered_form_token",
        "template_related": [],
        "token_counts_per_form": [
            {
                "action": "/admin/acesso/salvar",
                "page": "/admin/acesso",
                "token_counts": [1],
            }
        ],
    },
    "/admin/acesso/<int:usuario_id>/resetar-senha": {
        "csrf_in_html": None,
        "evidence": [
            {
                "action": "/admin/acesso/2/resetar-senha",
                "attr": "data-reset-url",
                "kind": "dynamic_form",
                "page": "/admin/acesso",
                "token_mode": "helper_or_hidden",
            },
            {
                "action": "/admin/acesso/1/resetar-senha",
                "attr": "data-reset-url",
                "kind": "dynamic_form",
                "page": "/admin/acesso",
                "token_mode": "helper_or_hidden",
            },
            {
                "action": "/admin/acesso/3/resetar-senha",
                "attr": "data-reset-url",
                "kind": "dynamic_form",
                "page": "/admin/acesso",
                "token_mode": "helper_or_hidden",
            },
        ],
        "fetch_sends_token": None,
        "has_dynamic_form": True,
        "has_fetch_post": False,
        "has_post_form": False,
        "method": "POST",
        "notes": [],
        "requires_login": "admin",
        "risk": [],
        "route": "/admin/acesso/<int:usuario_id>/resetar-senha",
        "status": "ok_dynamic_form_token",
        "template_related": [],
        "token_counts_per_form": [],
    },
    "/admin/acesso/definir-senha": {
        "csrf_in_html": True,
        "evidence": [
            {
                "action": "/admin/acesso/definir-senha",
                "kind": "rendered_form",
                "page": "/admin/acesso",
                "token_count": 1,
            },
            {
                "action": "/admin/acesso/definir-senha",
                "kind": "fetch",
                "page": "/admin/acesso",
                "token_mode": "inline_hint",
            },
        ],
        "fetch_sends_token": True,
        "has_dynamic_form": False,
        "has_fetch_post": True,
        "has_post_form": True,
        "method": "POST",
        "notes": [],
        "requires_login": "admin",
        "risk": [],
        "route": "/admin/acesso/definir-senha",
        "status": "ok_rendered_form_token",
        "template_related": [],
        "token_counts_per_form": [
            {
                "action": "/admin/acesso/definir-senha",
                "page": "/admin/acesso",
                "token_counts": [1],
            }
        ],
    },
    "/admin/acesso/<int:usuario_id>/deletar": {
        "csrf_in_html": None,
        "evidence": [
            {
                "action": "/admin/acesso/1/deletar",
                "attr": "data-delete-url",
                "kind": "dynamic_form",
                "page": "/admin/acesso",
                "token_mode": "helper_or_hidden",
            },
            {
                "action": "/admin/acesso/3/deletar",
                "attr": "data-delete-url",
                "kind": "dynamic_form",
                "page": "/admin/acesso",
                "token_mode": "helper_or_hidden",
            },
        ],
        "fetch_sends_token": None,
        "has_dynamic_form": True,
        "has_fetch_post": False,
        "has_post_form": False,
        "method": "POST",
        "notes": [],
        "requires_login": "admin",
        "risk": [],
        "route": "/admin/acesso/<int:usuario_id>/deletar",
        "status": "ok_dynamic_form_token",
        "template_related": [],
        "token_counts_per_form": [],
    },
}


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
    sub_root = Path(str(PYTEST_RUNTIME_ROOT)).resolve() / f"ut9-red-{secrets.token_hex(6)}"
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
# RED — future architectural contract (A..N)
# ===========================================================================


def test_red_a_target_module_file_exists():
    assert TARGET_PATH.exists(), (
        "app/views/admin/acesso.py does not exist yet; UT-9 must create it"
    )


def test_red_b_target_owns_exact_nine_symbols_zero_constants():
    target = _target_module()
    assert target is not None, "acesso module absent; 9-symbol ownership contract unsatisfiable"

    source = Path(target.__file__).read_text(encoding="utf-8")
    top_level = _top_level_defs(source)
    assigned = _top_level_assignments(source)

    assert top_level == set(ROUTE_NAMES) | set(HELPER_NAMES), (
        f"target top-level functions must be exactly the 9 moved callables; "
        f"missing={sorted((set(ROUTE_NAMES) | set(HELPER_NAMES)) - top_level)} "
        f"extra={sorted(top_level - (set(ROUTE_NAMES) | set(HELPER_NAMES)))}"
    )
    assert not (set(CONSTANT_NAMES) - assigned), (
        "the Acesso cohort moves zero constants; none may be defined or "
        "redefined inside the target"
    )


def test_red_c_six_routes_admin_decorated_no_route_decorators():
    target = _target_module()
    assert target is not None, "acesso module absent; route-ownership contract unsatisfiable"

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


def test_red_d_exactly_six_specs_six_pairs_frozen_matrix():
    target = _target_module()
    assert target is not None, "acesso module absent; LegacyRouteSpec contract unsatisfiable"

    specs = getattr(target, "LEGACY_ROUTE_SPECS", None)
    assert isinstance(specs, tuple), "target must expose an immutable LEGACY_ROUTE_SPECS tuple"
    assert len(specs) == 6, f"expected 6 LegacyRouteSpecs, got {len(specs)}"

    encoded = {(spec.rule, spec.endpoint, spec.methods) for spec in specs}
    assert encoded == EXPECTED_PAIRS, (
        f"spec set mismatch: missing={sorted(EXPECTED_PAIRS - encoded)} "
        f"extra={sorted(encoded - EXPECTED_PAIRS)}"
    )
    assert sum(len(spec.methods) for spec in specs) == 6, (
        "specs must represent exactly 6 endpoint/method pairs"
    )
    assert {spec.view_func for spec in specs} == {
        getattr(target, name) for name in ROUTE_NAMES
    }, "every spec must reference the target-owned route function"
    assert all("." not in spec.endpoint for spec in specs), (
        "no namespaced endpoint allowed"
    )


def test_red_e_spec_endpoints_resolve_one_view_five_full():
    target = _target_module()
    assert target is not None, "acesso module absent; RBAC-from-specs contract unsatisfiable"

    specs = getattr(target, "LEGACY_ROUTE_SPECS", None)
    assert isinstance(specs, tuple) and len(specs) == 6, (
        "RBAC derivation requires the frozen six LegacyRouteSpecs"
    )

    scope_counts = {"view": 0, "full": 0}
    for spec in specs:
        for method in spec.methods:
            requirement = get_admin_permission_requirement(spec.endpoint, method)
            assert requirement is not None, (
                f"{spec.endpoint} {method} must resolve a requirement"
            )
            resource, scope = requirement
            assert resource == "acesso", (
                f"{spec.endpoint} must be governed by the acesso resource, got {resource}"
            )
            assert scope in scope_counts, f"unexpected scope {scope} for {spec.endpoint}"
            scope_counts[scope] += 1
    assert scope_counts == {"view": 1, "full": 5}, (
        "frozen endpoint identities must derive exactly 1 view / 5 full, "
        f"got {scope_counts}"
    )
    assert get_admin_permission_requirement("admin_acesso", "GET") == ("acesso", "view"), (
        "admin_acesso GET must resolve to (acesso, view)"
    )


def test_red_f_main_has_no_local_ownership_and_no_cohort_route_decorators():
    source = MAIN_PATH.read_text(encoding="utf-8")
    defined = _top_level_defs(source)

    assert not (set(ROUTE_NAMES) | set(HELPER_NAMES)) & defined, (
        "main.py must no longer locally define moved callables: "
        f"{sorted((set(ROUTE_NAMES) | set(HELPER_NAMES)) & defined)}"
    )
    assert _cohort_route_decorators(source) == [], (
        "main.py must no longer register any Acesso @app.route decorator"
    )


def test_red_g_main_facade_nine_of_nine_identity_no_wrappers():
    target = _target_module()
    assert target is not None, "acesso module absent; main compatibility contract unsatisfiable"

    for name in MOVED_SYMBOLS:
        assert hasattr(main, name), f"main.{name} missing from the compatibility facade"
        assert getattr(main, name) is getattr(target, name), (
            f"main.{name} must be the identical object exported by acesso "
            "(identity re-export, no wrapper)"
        )


def test_red_h_target_has_no_main_backedge():
    target = _target_module()
    assert target is not None, "acesso module absent; no-back-edge contract unsatisfiable"

    source = Path(target.__file__).read_text(encoding="utf-8")
    edges = _main_back_edges(source)
    assert edges == [], (
        "target must not import main (including dynamic-import equivalents): "
        f"{edges}"
    )


def test_red_i_factory_declares_keyword_and_single_registration_path():
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
    assert "register_admin_acesso_blueprint" in kw_pairs, (
        "create_app must accept register_admin_acesso_blueprint"
    )
    default = kw_pairs["register_admin_acesso_blueprint"]
    assert isinstance(default, ast.Constant) and default.value is True, (
        "register_admin_acesso_blueprint must default to True"
    )

    registration_calls = [
        call
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "register_legacy_blueprint"
        and any(
            isinstance(arg, ast.Name) and arg.id == "bp_admin_acesso"
            for arg in call.args
        )
    ]
    assert len(registration_calls) == 1, (
        "create_app must register bp_admin_acesso exactly once through "
        "register_legacy_blueprint"
    )


def test_red_j_factory_default_registers_six_opt_out_registers_none():
    import inspect

    from app import create_app

    signature = inspect.signature(create_app)
    param = signature.parameters.get("register_admin_acesso_blueprint")
    assert param is not None, (
        "factory parameter missing; default/opt-out contract unsatisfiable"
    )
    assert param.default is True, (
        "factory parameter must default to True"
    )

    default_app = create_app(
        register_presets_blueprint=False,
        register_aluno_blueprint=False,
    )
    opt_out_app = create_app(
        register_presets_blueprint=False,
        register_aluno_blueprint=False,
        register_admin_acesso_blueprint=False,
    )

    default_rules = {
        (rule.rule, rule.endpoint) for rule in default_app.url_map.iter_rules()
    }
    assert _cohort_rules(default_app) == EXPECTED_PAIRS, (
        "default factory must register exactly the 6 frozen routes / 6 pairs"
    )
    assert _cohort_rules(opt_out_app) == frozenset(), (
        "opt-out factory must register none of the 6 cohort endpoints"
    )
    assert not any(
        rule.endpoint.startswith("admin_acesso_blueprint.") or "." in rule.endpoint
        for rule in default_app.url_map.iter_rules()
        if rule.endpoint in ROUTE_NAMES
    ), "no namespaced endpoint variant may exist"
    assert len(default_rules) > 0, "default factory sanity check"


def test_red_k_csrf_snapshots_show_exactly_five_acesso_owner_only_deltas():
    snapshot_dir = PROJECT_ROOT / "tests" / "_artifacts"
    for suffix in ("shadow_off", "shadow_on"):
        snapshot_path = snapshot_dir / f"csrf_inventory_{suffix}.json"
        assert snapshot_path.exists(), (
            f"canonical CSRF snapshot missing: {snapshot_path.name}"
        )
        report = json.loads(snapshot_path.read_text(encoding="utf-8"))
        rows = report["rows"]
        assert len(rows) == 78, (
            "known cumulative current snapshot contract: 78 mutating rows "
            f"per snapshot, got {len(rows)}"
        )

        partition = [
            row for row in rows if row["route"] in ACCESSO_POST_ROUTE_ENDPOINTS
        ]
        assert len(partition) == 5, (
            "exactly five Acesso POST rows per snapshot, "
            f"got {len(partition)} in {suffix}"
        )

        for row in partition:
            endpoint = ACCESSO_POST_ROUTE_ENDPOINTS[row["route"]]
            expected_owner = f"app.views.admin.acesso.{endpoint}"
            assert row["view_function"] == expected_owner, (
                f"Acesso owner delta unsatisfied in {suffix}: route={row['route']} "
                f"observed={row['view_function']!r} expected={expected_owner!r} "
                "(currently main.<function>, must become "
                "app.views.admin.acesso.<function>)"
            )
            shape = dict(row)
            shape.pop("view_function")
            assert shape == FROZEN_ACCESSO_ROW_SHAPE[row["route"]], (
                f"only view_function may change for Acesso partition row "
                f"{row['route']} in {suffix}"
            )

        unrelated = [
            row["route"]
            for row in rows
            if "admin_acesso" in row["view_function"]
            and row["route"] not in ACCESSO_POST_ROUTE_ENDPOINTS
        ]
        assert unrelated == [], (
            f"owner delta must be confined to the five Acesso rows: {unrelated}"
        )


def test_red_l_message_scanner_covers_target_module():
    from utils import messages

    catalog = messages._message_catalog()
    assert len(catalog) == 539, (
        "message catalog count must remain 539 through the extraction; "
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
        "app/views/admin/acesso.py must be inside backend message-scanner "
        "coverage once created"
    )


def test_red_m_admin_acesso_resolves_load_context_from_target_globals():
    import inspect

    from app import admin_access

    target = _target_module()
    assert target is not None, (
        "acesso module absent; load-context resolution contract unsatisfiable"
    )

    view = inspect.unwrap(target.admin_acesso)
    assert view.__module__ == TARGET_MODULE_NAME, (
        "admin_acesso function module owner must be app.views.admin.acesso, "
        f"got {view.__module__!r}"
    )
    loader = view.__globals__.get("_load_admin_access_context")
    assert loader is admin_access._load_admin_access_context, (
        "admin_acesso must resolve the canonical "
        "app.admin_access._load_admin_access_context from its own globals"
    )


def test_red_n_blueprint_identity_and_dotless_live_endpoints():
    target = _target_module()
    assert target is not None, "acesso module absent; blueprint identity contract unsatisfiable"

    blueprint = getattr(target, "bp_admin_acesso", None)
    assert blueprint is not None, "target must expose bp_admin_acesso"
    assert blueprint.name == "admin_acesso_blueprint", (
        f"blueprint name must be admin_acesso_blueprint, got {blueprint.name!r}"
    )

    live = {
        rule.endpoint: main.app.view_functions[rule.endpoint]
        for rule in main.app.url_map.iter_rules()
        if rule.endpoint in ROUTE_NAMES
    }
    assert len(live) == 6, "exactly six live Acesso endpoints required"
    for name in ROUTE_NAMES:
        assert live[name] is getattr(target, name), (
            f"live endpoint {name} must identity-match the target callable"
        )

    namespaced = [
        endpoint
        for endpoint in main.app.view_functions
        if endpoint.startswith("admin_acesso_blueprint.")
    ]
    assert namespaced == [], (
        f"no admin_acesso_blueprint.* namespaced endpoint may exist: {namespaced}"
    )


# ===========================================================================
# GREEN — current behavior / detector quality characterization
# ===========================================================================


def test_green_1_detector_self_control():
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

    synthetic_backedge = (
        "import main\n"
        "from main import app\n"
        "import importlib\n"
        "x = importlib.import_module('main')\n"
        "y = __import__('main')\n"
        "z = sys.modules['main']\n"
    )
    edges = _main_back_edges(synthetic_backedge)
    kinds = {kind for kind, _, _ in edges}
    assert {
        "import",
        "from",
        "dynamic-import",
        "__import__",
        "sys.modules",
    } <= kinds, (
        "back-edge detector must flag plain import, from import, "
        "importlib.import_module('main'), __import__('main') and "
        f"sys.modules['main']; detected={sorted(kinds)}"
    )
    assert _main_back_edges("def f():\n    return 1\n") == [], (
        "back-edge detector must stay silent on a clean source"
    )


def test_green_2_live_route_matrix_six_routes_six_pairs():
    rules = [
        rule
        for rule in main.app.url_map.iter_rules()
        if rule.endpoint in ROUTE_NAMES
    ]
    assert len(rules) == 6, f"expected 6 live cohort rules, got {len(rules)}"
    assert _cohort_rules(main.app) == EXPECTED_PAIRS, (
        "live url_map must match the frozen 6-pair matrix"
    )


def test_green_3_rbac_exact_match_wins_and_prefix_exactness():
    assert get_admin_permission_requirement("admin_acesso", "GET") == ("acesso", "view"), (
        "admin_acesso GET must resolve to (acesso, view)"
    )
    assert get_admin_permission_requirement("admin_acesso", "POST") == ("acesso", "view"), (
        "exact admin_acesso match must win over prefix semantics even for POST"
    )

    for endpoint, (resource, scope) in RBAC_MATRIX.items():
        if endpoint == "admin_acesso":
            continue
        assert get_admin_permission_requirement(endpoint, "POST") == (resource, scope), (
            f"{endpoint} must satisfy the admin_acesso prefix behavior as {scope}"
        )

    live_endpoints = {
        rule.endpoint
        for rule in main.app.url_map.iter_rules()
        if rule.endpoint.startswith("admin_acesso")
    }
    assert live_endpoints == set(ROUTE_NAMES), (
        "exactly the six frozen admin_acesso* endpoints must be live; "
        f"no unrelated endpoint admitted; got {sorted(live_endpoints)}"
    )


def test_green_4_auth_byte_identical_to_ut9_entry():
    data = (PROJECT_ROOT / "app" / "auth.py").read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    assert digest == FROZEN_ENTRY_AUTH_SHA256, (
        "app/auth.py must remain byte-identical to the UT-9 ENTRY frozen "
        f"hash {FROZEN_ENTRY_AUTH_SHA256}; got {digest}"
    )


def test_green_5_admin_access_still_exactly_five_helpers():
    import app.admin_access as admin_access_module

    source = Path(admin_access_module.__file__).read_text(encoding="utf-8")
    top_level = _top_level_defs(source)
    assert top_level == {
        "_fetch_user_access_overrides",
        "_build_access_scope_groups_for_level",
        "_load_admin_access_context",
        "_get_current_admin_access_context",
        "_admin_can",
    }, f"app/admin_access.py must keep exactly the five canonical helpers; got {top_level}"

    for name in ("_persist_user_access_overrides", "_parse_access_overrides_from_form"):
        assert getattr(admin_access_module, name, None) is None, (
            f"{name} must remain absent from app/admin_access.py"
        )


def test_green_6_csrf_governance_five_posts_400_get_redirects():
    tree = ast.parse(CREATE_APP_PATH.read_text(encoding="utf-8"))
    exempt_targets = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and isinstance(node.value.func.value, ast.Name)
            and node.value.func.value.id == "csrf"
            and node.value.func.attr == "exempt"
            and node.value.args
        ):
            exempt_targets.append(ast.unparse(node.value.args[0]))
    assert len(exempt_targets) == 1, f"expected exactly one csrf.exempt, got {exempt_targets}"
    assert "login" in exempt_targets[0] and "core_views" in exempt_targets[0], (
        "the single exemption must remain the login view; no Acesso csrf "
        "exemption may exist"
    )

    app = main.app
    original_csrf = app.config.get("WTF_CSRF_ENABLED")
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        for url in FIVE_POST_URLS:
            response = app.test_client().post(url)
            assert response.status_code == 400, (
                f"unsafe Acesso method {url} must be CSRF-governed (400 "
                f"without token), got {response.status_code}"
            )
        response = app.test_client().get("/admin/acesso")
        assert response.status_code in (302, 303), (
            "Acesso GET must remain outside CSRF and redirect "
            f"unauthenticated, got {response.status_code}"
        )
    finally:
        if original_csrf is None:
            app.config.pop("WTF_CSRF_ENABLED", None)
        else:
            app.config["WTF_CSRF_ENABLED"] = original_csrf


def test_green_7_password_writes_hashed_configured_default_and_admin123_fallback(isolated_env):
    client, _ = isolated_env
    _login(client)

    configured = "ut9-configurada-X9"
    save_defaults = client.post(
        "/admin/acesso/senhas-default",
        data={
            "default_admin_total": "admin123",
            "default_consultivo": "consultivo123",
            "default_administrativo": "admin123",
            "default_usuario": configured,
            "default_usuario_teste": "teste123",
        },
        follow_redirects=False,
    )
    assert save_defaults.status_code in (302, 303)

    create_explicit = client.post(
        "/admin/acesso/salvar",
        data={
            "nome": "UT9 Senha Explicita",
            "email": "ut9.senha.explicita@ej.edu.br",
            "nivel_acesso": "consultivo",
            "senha": "explicita-UT9-456",
        },
        follow_redirects=False,
    )
    assert create_explicit.status_code in (302, 303)

    create_configured = client.post(
        "/admin/acesso/salvar",
        data={
            "nome": "UT9 Senha Configurada",
            "email": "ut9.senha.configurada@ej.edu.br",
            "nivel_acesso": "usuario",
            "senha": "",
            "matricula": "UT9-MAT-CONF-1",
        },
        follow_redirects=False,
    )
    assert create_configured.status_code in (302, 303)

    create_fallback = client.post(
        "/admin/acesso/salvar",
        data={
            "nome": "UT9 Senha Fallback",
            "email": "ut9.senha.fallback@ej.edu.br",
            "nivel_acesso": "administrativo",
            "senha": "",
        },
        follow_redirects=False,
    )
    assert create_fallback.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        explicit = conn.execute(
            "SELECT senha FROM usuarios WHERE email = ?",
            ("ut9.senha.explicita@ej.edu.br",),
        ).fetchone()
        configured_row = conn.execute(
            "SELECT senha FROM usuarios WHERE email = ?",
            ("ut9.senha.configurada@ej.edu.br",),
        ).fetchone()
        fallback = conn.execute(
            "SELECT senha FROM usuarios WHERE email = ?",
            ("ut9.senha.fallback@ej.edu.br",),
        ).fetchone()

    assert explicit is not None, "explicit-password user must exist"
    assert explicit["senha"] != "explicita-UT9-456", (
        "plaintext password must never be written to usuarios.senha"
    )
    assert main.check_password(explicit["senha"], "explicita-UT9-456"), (
        "explicit password must verify against its stored hash"
    )

    assert configured_row is not None, "configured-default user must exist"
    assert configured_row["senha"] != configured, (
        "configured default password must not be stored in plaintext"
    )
    assert main.check_password(configured_row["senha"], configured), (
        "configured default must be hashed when written for a new user"
    )

    assert fallback is not None, "fallback-default user must exist"
    assert fallback["senha"] != "admin123", (
        "admin123 fallback must not be stored in plaintext"
    )
    assert main.check_password(fallback["senha"], "admin123"), (
        "the well-known admin123 default must apply when no custom default "
        "is configured for the level"
    )


def test_green_8_duplicate_email_matricula_and_override_persistence(isolated_env):
    client, _ = isolated_env
    _login(client)

    first = client.post(
        "/admin/acesso/salvar",
        data={
            "nome": "UT9 Email Um",
            "email": "ut9.dup@ej.edu.br",
            "nivel_acesso": "consultivo",
            "senha": "",
        },
        follow_redirects=False,
    )
    assert first.status_code in (302, 303)

    second = client.post(
        "/admin/acesso/salvar",
        data={
            "nome": "UT9 Email Dois",
            "email": "ut9.dup@ej.edu.br",
            "nivel_acesso": "consultivo",
            "senha": "",
        },
        follow_redirects=True,
    )
    assert second.status_code == 200
    assert "Já existe um usuário com este e-mail." in second.get_data(as_text=True), (
        "duplicate e-mail must be rejected with the canonical flash"
    )

    with main.app.app_context():
        conn = main.get_db_connection()
        count = conn.execute(
            "SELECT COUNT(*) AS total FROM usuarios WHERE email = ?",
            ("ut9.dup@ej.edu.br",),
        ).fetchone()["total"]
    assert count == 1, "duplicate e-mail must not create a second usuario"

    turma_nome = f"UT9 Turma {secrets.token_hex(4)}"
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "INSERT INTO turmas (nome) VALUES (?)",
            (turma_nome,),
        )
        turma_id = conn.execute(
            "SELECT id FROM turmas WHERE nome = ?",
            (turma_nome,),
        ).fetchone()["id"]
        conn.commit()

    aluno_um = client.post(
        "/admin/acesso/salvar",
        data={
            "nome": "UT9 Aluno Um",
            "email": "ut9.aluno.um@ej.edu.br",
            "nivel_acesso": "usuario",
            "senha": "",
            "matricula": "UT9-DUP-1",
            "turma_id": str(turma_id),
        },
        follow_redirects=False,
    )
    assert aluno_um.status_code in (302, 303)

    aluno_dois = client.post(
        "/admin/acesso/salvar",
        data={
            "nome": "UT9 Aluno Dois",
            "email": "ut9.aluno.dois@ej.edu.br",
            "nivel_acesso": "usuario",
            "senha": "",
            "matricula": "UT9-DUP-1",
            "turma_id": str(turma_id),
        },
        follow_redirects=True,
    )
    assert aluno_dois.status_code == 200
    assert "Já existe um aluno com esta matrícula." in aluno_dois.get_data(as_text=True), (
        "duplicate matricula must be rejected with the canonical flash"
    )

    with main.app.app_context():
        conn = main.get_db_connection()
        rolled_back = conn.execute(
            "SELECT 1 FROM usuarios WHERE email = ?",
            ("ut9.aluno.dois@ej.edu.br",),
        ).fetchone()
        aluno_count = conn.execute(
            "SELECT COUNT(*) AS total FROM alunos WHERE matricula = ?",
            ("UT9-DUP-1",),
        ).fetchone()["total"]
    assert rolled_back is None, "duplicate-matricula save must roll back the usuario"
    assert aluno_count == 1, "duplicate matricula must not duplicate the aluno"

    override_save = client.post(
        "/admin/acesso/salvar",
        data={
            "nome": "UT9 Overrides",
            "email": "ut9.overrides@ej.edu.br",
            "nivel_acesso": "consultivo",
            "senha": "",
            "scope_requisicoes": "edit",
            "scope_banco_dados": "view",
            "scope_alertas": "inherit",
        },
        follow_redirects=False,
    )
    assert override_save.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        override_user = conn.execute(
            "SELECT id FROM usuarios WHERE email = ?",
            ("ut9.overrides@ej.edu.br",),
        ).fetchone()
        override_id = override_user["id"]
        rows = conn.execute(
            "SELECT recurso, escopo FROM usuarios_permissoes_acesso WHERE usuario_id = ? ORDER BY recurso",
            (override_id,),
        ).fetchall()
    assert {(row["recurso"], row["escopo"]) for row in rows} == {
        ("requisicoes", "edit"),
        ("banco_dados", "view"),
    }, "overrides differing from the level default must persist; inherit must not"

    update_overrides = client.post(
        "/admin/acesso/salvar",
        data={
            "usuario_id": str(override_id),
            "nome": "UT9 Overrides",
            "email": "ut9.overrides@ej.edu.br",
            "nivel_acesso": "consultivo",
            "senha": "",
            "scope_requisicoes": "view",
        },
        follow_redirects=False,
    )
    assert update_overrides.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        remaining = conn.execute(
            "SELECT recurso FROM usuarios_permissoes_acesso WHERE usuario_id = ?",
            (override_id,),
        ).fetchall()
    assert remaining == [], (
        "overrides equal to the level default must be pruned on save"
    )


def test_green_9_reset_and_ajax_batch_password_branches(isolated_env):
    client, _ = isolated_env
    _login(client)

    create_target = client.post(
        "/admin/acesso/salvar",
        data={
            "nome": "UT9 Reset Alvo",
            "email": "ut9.reset.alvo@ej.edu.br",
            "nivel_acesso": "usuario",
            "senha": "",
            "matricula": "UT9-RESET-1",
        },
        follow_redirects=False,
    )
    assert create_target.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        target = conn.execute(
            "SELECT id, senha FROM usuarios WHERE email = ?",
            ("ut9.reset.alvo@ej.edu.br",),
        ).fetchone()
        target_id = target["id"]
    assert main.check_password(target["senha"], "aluno123"), (
        "usuario-level default seed must be hashed for the new user"
    )

    reset = client.post(
        f"/admin/acesso/{target_id}/resetar-senha",
        follow_redirects=False,
    )
    assert reset.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        after_reset = conn.execute(
            "SELECT senha FROM usuarios WHERE id = ?",
            (target_id,),
        ).fetchone()
    assert main.check_password(after_reset["senha"], "aluno123"), (
        "resetar-senha must rewrite the level default password hashed"
    )

    ajax_headers = {"X-Requested-With": "XMLHttpRequest"}

    batch_ok = client.post(
        "/admin/acesso/definir-senha",
        headers=ajax_headers,
        data={"usuario_ids": [str(target_id)], "nova_senha": "ut9-nova-senha-42"},
    )
    assert batch_ok.status_code == 200
    payload = batch_ok.get_json()
    assert payload["ok"] is True and payload["updated"] == 1

    with main.app.app_context():
        conn = main.get_db_connection()
        after_batch = conn.execute(
            "SELECT senha FROM usuarios WHERE id = ?",
            (target_id,),
        ).fetchone()
    assert main.check_password(after_batch["senha"], "ut9-nova-senha-42"), (
        "ajax batch define must apply the new password hashed"
    )

    missing_users = client.post(
        "/admin/acesso/definir-senha",
        headers=ajax_headers,
        data={"usuario_ids": [], "nova_senha": "ut9-x"},
    )
    assert missing_users.status_code == 400
    assert missing_users.get_json()["error"] == "missing-users", (
        "ajax batch without users must answer 400 missing-users"
    )

    missing_password = client.post(
        "/admin/acesso/definir-senha",
        headers=ajax_headers,
        data={"usuario_ids": [str(target_id)], "nova_senha": ""},
    )
    assert missing_password.status_code == 400
    assert missing_password.get_json()["error"] == "missing-password", (
        "ajax batch without password must answer 400 missing-password"
    )

    not_found = client.post(
        "/admin/acesso/definir-senha",
        headers=ajax_headers,
        data={"usuario_ids": ["999999"], "nova_senha": "ut9-x"},
    )
    assert not_found.status_code == 404
    assert not_found.get_json()["error"] == "not-found", (
        "ajax batch with unknown ids must answer 404 not-found"
    )


def test_green_10_self_demotion_session_and_self_delete_guard(isolated_env):
    client, _ = isolated_env
    _login(client)

    with main.app.app_context():
        conn = main.get_db_connection()
        admin = conn.execute(
            "SELECT id, nome, email FROM usuarios WHERE email = ?",
            ("admin_total@ej.edu.br",),
        ).fetchone()
        admin_id = admin["id"]
        admin_email = admin["email"]

    self_delete = client.post(
        f"/admin/acesso/{admin_id}/deletar",
        follow_redirects=True,
    )
    assert self_delete.status_code == 200
    assert "Você não pode excluir o próprio acesso." in self_delete.get_data(as_text=True), (
        "self-delete must be refused with the canonical flash"
    )

    with main.app.app_context():
        conn = main.get_db_connection()
        still_present = conn.execute(
            "SELECT 1 FROM usuarios WHERE id = ?",
            (admin_id,),
        ).fetchone()
    assert still_present is not None, "self-delete must not remove the own usuario"

    demote = client.post(
        "/admin/acesso/salvar",
        data={
            "usuario_id": str(admin_id),
            "nome": "Admin Total",
            "email": admin_email,
            "nivel_acesso": "usuario",
            "senha": "",
            "matricula": "UT9-SELF-1",
        },
        follow_redirects=False,
    )
    assert demote.status_code in (302, 303)
    assert demote.headers.get("Location", "").endswith("/login"), (
        "self-demotion to a student profile must clear the session and "
        "redirect to login"
    )

    follow_up = client.get("/admin/acesso", follow_redirects=False)
    assert follow_up.status_code in (302, 303)
    assert follow_up.headers.get("Location", "").endswith("/login"), (
        "after self-demotion the cleared session must not reach admin areas"
    )


def test_green_11_delete_cascade_resequencing_and_integrityerror_rollback(isolated_env, monkeypatch):
    client, _ = isolated_env
    _login(client)

    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "INSERT INTO turmas (nome, codigo) VALUES (?, ?)",
            (f"UT9 Turma {secrets.token_hex(4)}", "UT9-RED"),
        )
        turma_id = conn.execute(
            "SELECT id FROM turmas WHERE codigo = 'UT9-RED'"
        ).fetchone()["id"]
        conn.commit()

    for nome, matricula, email in (
        ("UT9 Aluno Um", "UT9-M-1", "ut9.aluno.um@ej.edu.br"),
        ("UT9 Aluno Dois", "UT9-M-2", "ut9.aluno.dois@ej.edu.br"),
    ):
        created = client.post(
            "/admin/acesso/salvar",
            data={
                "nome": nome,
                "email": email,
                "nivel_acesso": "usuario",
                "senha": "",
                "matricula": matricula,
                "turma_id": str(turma_id),
            },
            follow_redirects=False,
        )
        assert created.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        target = conn.execute(
            "SELECT id FROM usuarios WHERE email = ?",
            ("ut9.aluno.um@ej.edu.br",),
        ).fetchone()
        target_id = target["id"]
        initial = conn.execute(
            "SELECT matricula FROM alunos WHERE turma_id = ? ORDER BY matricula",
            (turma_id,),
        ).fetchall()
    assert {row["matricula"] for row in initial} == {
        "UT9-RED.001",
        "UT9-RED.002",
    }, "aluno creation must resequence matriculas for the turma"

    delete = client.post(
        f"/admin/acesso/{target_id}/deletar",
        follow_redirects=False,
    )
    assert delete.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        removed_user = conn.execute(
            "SELECT 1 FROM usuarios WHERE id = ?",
            (target_id,),
        ).fetchone()
        removed_aluno = conn.execute(
            "SELECT 1 FROM alunos WHERE usuario_id = ?",
            (target_id,),
        ).fetchone()
        remaining = conn.execute(
            "SELECT matricula FROM alunos WHERE turma_id = ? ORDER BY matricula",
            (turma_id,),
        ).fetchall()
    assert removed_user is None, "deleting the acesso must cascade to usuarios"
    assert removed_aluno is None, "deleting the acesso must cascade to alunos"
    assert [row["matricula"] for row in remaining] == ["UT9-RED.001"], (
        "remaining aluno matriculas must be resequenced after deletion"
    )

    import app.views.admin.acesso as acesso_module

    real_get = acesso_module.get_db_connection

    class _FlakyConnectionProxy:
        def __init__(self, real_conn):
            object.__setattr__(self, "_real_conn", real_conn)

        def execute(self, sql, *args, **kwargs):
            if isinstance(sql, str) and "DELETE FROM usuarios" in sql:
                raise sqlite3.IntegrityError("ut9-red simulated FK violation")
            return object.__getattribute__(self, "_real_conn").execute(sql, *args, **kwargs)

        def __getattr__(self, name):
            return getattr(object.__getattribute__(self, "_real_conn"), name)

    def flaky_get():
        return _FlakyConnectionProxy(real_get())

    monkeypatch.setattr(acesso_module, "get_db_connection", flaky_get)

    with main.app.app_context():
        conn = main.get_db_connection()
        survivor = conn.execute(
            "SELECT id FROM usuarios WHERE email = ?",
            ("ut9.aluno.dois@ej.edu.br",),
        ).fetchone()
        survivor_id = survivor["id"]

    blocked = client.post(
        f"/admin/acesso/{survivor_id}/deletar",
        follow_redirects=True,
    )
    assert blocked.status_code == 200
    assert "Não foi possível excluir o acesso" in blocked.get_data(as_text=True), (
        "IntegrityError during delete must surface the canonical rollback flash"
    )

    with main.app.app_context():
        conn = main.get_db_connection()
        still_user = conn.execute(
            "SELECT 1 FROM usuarios WHERE id = ?",
            (survivor_id,),
        ).fetchone()
        still_aluno = conn.execute(
            "SELECT 1 FROM alunos WHERE usuario_id = ?",
            (survivor_id,),
        ).fetchone()
    assert still_user is not None, "IntegrityError path must roll back the usuario delete"
    assert still_aluno is not None, "IntegrityError path must roll back the aluno delete"


def test_green_12_message_catalog_536_and_views_recursive_coverage():
    from utils import messages

    assert len(messages._message_catalog()) == 539, (
        "current catalog baseline must be 539"
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
