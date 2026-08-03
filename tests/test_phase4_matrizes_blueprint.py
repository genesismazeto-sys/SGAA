"""PHASE 4-B5-R1 — Matrizes legacy blueprint contract.

RED-only mission: the canonical owner ``app.views.admin.matrizes`` does not
exist yet.  This module codifies the full B5 contract that production must
honour after extraction, and in the current (RED) baseline it must fail only
because that resource is absent — never because of a collection/syntax error
in this test module.

The contract covered here (GREEN targets):

  1. isolated import of ``app.views.admin.matrizes`` (no main / DB / FS / net);
  2. exact ``LEGACY_ROUTE_SPECS``: 10 endpoints, 12 rule/method pairs, no 11th;
  3. exact RBAC for every route/method combination;
  4. no ``@bp.route``, no namespaced alias, no duplicates, no main/dynamic import;
  5. global legacy ``request.endpoint`` and ``url_for`` preserved;
  6. factory default / opt-out, independent apps, atomic endpoint and
     rule/method collisions;
  7. ``main`` identities for the 10 handlers and 21 helpers;
  8. ``admin_editar_matriz`` / ``admin_matriz_nova_atividade`` keep the B5-P
     ``app.admin_access`` owner;
  9. route-inventory baseline byte-identical, message catalog == 536, CSRF
     snapshots show exactly 8 owner-only deltas each, canonical SQLite never
     opened;
  10. ``_get_grupos_atividade`` and ``_get_matriz_active_norma_ids`` remain
      absent from ``main`` and from the new module.

All DB work is confined to temporary/in-memory SQLite.  The institutional
database is never opened and no network is used.
"""
from __future__ import annotations

import ast
import importlib
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from flask import Flask, request, url_for

from app import create_app
from app.auth import get_admin_permission_requirement
from app.views.admin import LegacyRouteRegistrationError, register_legacy_blueprint


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAIN_PATH = PROJECT_ROOT / "main.py"
APP_PATH = PROJECT_ROOT / "app" / "__init__.py"
ADMIN_PACKAGE = PROJECT_ROOT / "app" / "views" / "admin"
MATRIZES_VIEW_PATH = ADMIN_PACKAGE / "matrizes.py"
BUSINESS_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
BASELINE_COMMIT = "ef874b9d14b02656a0f26ea885024a280d49682e"

ARTIFACTS_DIR = PROJECT_ROOT / "tests" / "_artifacts"
ROUTE_INVENTORY_PATH = ARTIFACTS_DIR / "route_inventory_baseline.json"
CSRF_OFF_PATH = ARTIFACTS_DIR / "csrf_inventory_shadow_off.json"
CSRF_ON_PATH = ARTIFACTS_DIR / "csrf_inventory_shadow_on.json"

ROUTE_MATRIX = (
    ("/admin/matrizes", "admin_matrizes", ("GET",)),
    ("/admin/adicionar_matriz", "admin_adicionar_matriz", ("GET", "POST")),
    ("/admin/editar_matriz/<int:matriz_id>", "admin_editar_matriz", ("GET", "POST")),
    ("/admin/matrizes/excluir", "admin_excluir_matrizes", ("POST",)),
    ("/admin/matrizes/<int:matriz_id>/excluir", "admin_excluir_matriz", ("POST",)),
    (
        "/admin/matrizes/<int:matriz_id>/atividades/nova/<string:active_tab>",
        "admin_matriz_nova_atividade",
        ("POST",),
    ),
    (
        "/admin/matrizes/<int:matriz_id>/atividades/<int:atividade_id>/nova-versao",
        "admin_matriz_nova_versao_card",
        ("POST",),
    ),
    ("/admin/matrizes/<int:matriz_id>/versoes", "admin_matriz_versoes", ("GET",)),
    (
        "/admin/matrizes/<int:matriz_id>/versoes/definir",
        "admin_matriz_versoes_definir",
        ("POST",),
    ),
    (
        "/admin/matrizes/<int:matriz_id>/versoes/remover",
        "admin_matriz_versoes_remover",
        ("POST",),
    ),
)
ROUTE_NAMES = tuple(endpoint for _, endpoint, _ in ROUTE_MATRIX)

HELPER_NAMES = (
    "get_bases_escopo_matriz",
    "get_versoes_ativas_por_base_na_matriz",
    "get_vinculo_versao_da_matriz",
    "_set_versao_da_matriz_para_base",
    "_remover_versao_da_matriz_para_base",
    "get_card_version_menu_data",
    "_matriz_status_badge_type",
    "_matriz_vigencia_label",
    "_matriz_activity_type_for_tab",
    "_matriz_axis_for_tab",
    "_get_grupos_por_tipo",
    "_get_matriz_active_normas_for_axis",
    "_build_matriz_new_activity_modal_context",
    "_matriz_transfer_meta",
    "_matriz_activity_rule_summary",
    "_matriz_transfer_lists",
    "_matriz_counts",
    "_render_matriz_form",
    "_matriz_payload_from_request",
    "_ensure_default_versao_link",
    "_save_matriz_activity_links",
)

RBAC_MATRIX = {
    "admin_matrizes": ("matrizes", "view"),
    "admin_adicionar_matriz": ("matrizes", "edit"),
    "admin_editar_matriz": ("matrizes", "view"),  # GET; POST is edit — see below
    "admin_excluir_matrizes": ("matrizes", "full"),
    "admin_excluir_matriz": ("matrizes", "full"),
    "admin_matriz_versoes": ("matrizes", "view"),
    "admin_matriz_nova_atividade": ("matrizes", "edit"),
    "admin_matriz_nova_versao_card": ("matrizes", "edit"),
    "admin_matriz_versoes_definir": ("matrizes", "edit"),
    "admin_matriz_versoes_remover": ("matrizes", "edit"),
}
# admin_editar_matriz is GET=view / POST=edit.
RBAC_EDITAR_MATRIZ_PAIR = (("GET", ("matrizes", "view")), ("POST", ("matrizes", "edit")))
RBAC_SCOPE_COUNTS = {"view": 3, "edit": 7, "full": 2}

# 8 POST-handlers that are the only mutating Matrizes routes (owner-only CSRF).
CSRF_MUTATING_PAIRS = {
    "/admin/adicionar_matriz": "admin_adicionar_matriz",
    "/admin/editar_matriz/<int:matriz_id>": "admin_editar_matriz",
    "/admin/matrizes/excluir": "admin_excluir_matrizes",
    "/admin/matrizes/<int:matriz_id>/excluir": "admin_excluir_matriz",
    "/admin/matrizes/<int:matriz_id>/atividades/nova/<string:active_tab>": "admin_matriz_nova_atividade",
    "/admin/matrizes/<int:matriz_id>/atividades/<int:atividade_id>/nova-versao": "admin_matriz_nova_versao_card",
    "/admin/matrizes/<int:matriz_id>/versoes/definir": "admin_matriz_versoes_definir",
    "/admin/matrizes/<int:matriz_id>/versoes/remover": "admin_matriz_versoes_remover",
}

ALLOWED_CSRF_STATUSES = {
    "ok_rendered_form_token",
    "ok_dynamic_form_token",
    "ok_specific_regression_test",
    "ok_fetch_token",
    "ok_api_csrf_contract",
}

BLUEPRINT_NAME = "admin_matrizes_blueprint"
BLUEPRINT_FLAG = "register_admin_matrizes_blueprint"
BLUEPRINT_VAR = "bp_admin_matrizes"

# Two void helper names that must never be defined in main nor in the module.
VOID_HELPER_NAMES = {"_get_grupos_atividade", "_get_matriz_active_norma_ids"}


# ---------------------------------------------------------------------------
# AST / route helpers
# ---------------------------------------------------------------------------


def _canonical_module():
    from app.views.admin import matrizes

    return matrizes


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))


def _top_level_functions(path: Path) -> set[str]:
    return {
        node.name
        for node in _tree(path).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _top_level_assignments(path: Path) -> set[str]:
    result: set[str] = set()
    for node in _tree(path).body:
        if isinstance(node, ast.Assign):
            result.update(
                target.id for target in node.targets if isinstance(target, ast.Name)
            )
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            result.add(node.target.id)
    return result


def _imports_from(path: Path, module_name: str) -> set[str]:
    result: set[str] = set()
    for node in _tree(path).body:
        if isinstance(node, ast.ImportFrom) and node.module == module_name:
            result.update(alias.asname or alias.name for alias in node.names)
    return result


def _live_moved_rules(app):
    return [rule for rule in app.url_map.iter_rules() if rule.endpoint in ROUTE_NAMES]


def _route_tuples(app):
    return {
        (
            rule.rule,
            rule.endpoint,
            tuple(sorted(set(rule.methods or ()) & BUSINESS_METHODS)),
        )
        for rule in _live_moved_rules(app)
    }


def _factory(**kwargs):
    return create_app(
        register_presets_blueprint=False,
        register_aluno_blueprint=False,
        register_admin_configuracoes_blueprint=False,
        register_admin_versioning_blueprint=False,
        **kwargs,
    )


def _materialize_rule(rule: str, matriz_id: int = 1, atividade_id: int = 1, active_tab: str = "academicas") -> str:
    return (
        rule.replace("<int:matriz_id>", str(matriz_id))
        .replace("<int:atividade_id>", str(atividade_id))
        .replace("<string:active_tab>", active_tab)
    )


# ---------------------------------------------------------------------------
# 1. Isolated import
# ---------------------------------------------------------------------------


def test_module_import_isolated_from_main_database_filesystem_and_network(tmp_path):
    runtime = tmp_path / "isolated-import"
    code = r"""
import json
import os
from pathlib import Path
import socket
import sqlite3
import sys

root = Path(os.environ["PHASE4_IMPORT_ROOT"])
root.mkdir()

def forbidden(*args, **kwargs):
    raise AssertionError("import-time side effect")

sqlite3.connect = forbidden
socket.create_connection = forbidden
socket.socket.connect = forbidden
before = sorted(path.name for path in root.iterdir())
assert "main" not in sys.modules
import app.views.admin.matrizes as module
assert "main" not in sys.modules
assert module.__name__ == "app.views.admin.matrizes"
after = sorted(path.name for path in root.iterdir())
assert before == after == []

assert not Path(os.environ["APP_DATABASE"]).exists()
print(json.dumps({"main_imported": False, "filesystem_delta": [], "database_created": False}))
"""
    environment = os.environ.copy()
    environment.update(
        {
            "PHASE4_IMPORT_ROOT": str(runtime),
            "APP_DATABASE": str(runtime / "never-created.sqlite3"),
            "APP_UPLOAD_FOLDER": str(runtime / "uploads"),
            "APP_DOCUMENTOS_ALUNOS_FOLDER": str(runtime / "documentos"),
            "APP_LOG_DIR": str(runtime / "logs"),
            "APP_LOCAL_BACKUP_DIR": str(runtime / "backups" / "local"),
            "APP_CLOUD_BACKUP_DIR": str(runtime / "backups" / "cloud"),
            "APP_ENV": "testing",
            "APP_SECRET_KEY": "phase4-matrizes-import-test-secret-key-000000000000",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUTF8": "1",
        }
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", code],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {
        "main_imported": False,
        "filesystem_delta": [],
        "database_created": False,
    }


def test_canonical_owner_path_exists():
    assert MATRIZES_VIEW_PATH.is_file(), f"missing canonical owner: {MATRIZES_VIEW_PATH}"


# ---------------------------------------------------------------------------
# 1. Exact LEGACY_ROUTE_SPECS: 10 endpoints, 12 pairs, no 11th endpoint
# ---------------------------------------------------------------------------


def test_exactly_ten_route_specs_and_twelve_rule_method_pairs_match_legacy_matrix():
    module = _canonical_module()
    specs = module.LEGACY_ROUTE_SPECS

    assert isinstance(specs, tuple)
    assert len(specs) == 10
    assert tuple((spec.rule, spec.endpoint, spec.methods) for spec in specs) == ROUTE_MATRIX
    assert {spec.endpoint for spec in specs} == set(ROUTE_NAMES) == set(ROUTE_NAMES)
    assert len(ROUTE_NAMES) == 10
    pairs = {(spec.rule, method) for spec in specs for method in spec.methods}
    assert len(pairs) == 12
    assert {spec.view_func for spec in specs} == {
        getattr(module, name) for name in ROUTE_NAMES
    }


def test_route_specs_are_immutable():
    module = _canonical_module()
    specs = module.LEGACY_ROUTE_SPECS
    with pytest.raises((AttributeError, TypeError)):
        specs[0].endpoint = "changed"


def test_no_eleventh_endpoint_in_catalog():
    module = _canonical_module()
    assert len(module.LEGACY_ROUTE_SPECS) == 10
    assert len({spec.endpoint for spec in module.LEGACY_ROUTE_SPECS}) == 10


# ---------------------------------------------------------------------------
# 4. No @bp.route / namespaced alias / duplicates / dynamic imports
# ---------------------------------------------------------------------------


def test_route_functions_are_admin_decorated_and_specs_reference_them():
    module = _canonical_module()
    source = Path(module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert set(ROUTE_NAMES) <= set(functions)
    for name in ROUTE_NAMES:
        decorators = {ast.unparse(item) for item in functions[name].decorator_list}
        assert decorators == {"admin_required"}
    assert "@bp" not in source
    assert f"@{BLUEPRINT_VAR}.route" not in source
    assert "sys.modules" not in source
    assert "importlib" not in source
    assert "import main" not in source


# ---------------------------------------------------------------------------
# 2/4. Factory registration: default / opt-out / independence / collisions
# ---------------------------------------------------------------------------


def test_factory_registers_legacy_routes_by_default_and_supports_opt_out():
    default_app = _factory()
    opt_out_app = _factory(**{BLUEPRINT_FLAG: False})

    assert _route_tuples(default_app) == set(ROUTE_MATRIX)
    assert _live_moved_rules(opt_out_app) == []


def test_factory_signature_exposes_exact_matrizes_registration_switch():
    sig = inspect.signature(create_app)
    param = sig.parameters[BLUEPRINT_FLAG]
    assert param.default is True
    assert param.kind is inspect.Parameter.KEYWORD_ONLY


def test_two_independent_factory_apps_each_register_each_route_once():
    first = _factory()
    second = _factory()

    assert _route_tuples(first) == set(ROUTE_MATRIX)
    assert _route_tuples(second) == set(ROUTE_MATRIX)
    assert len(_live_moved_rules(first)) == len(_live_moved_rules(second)) == 10
    assert first is not second


def test_duplicate_blueprint_registration_fails_explicitly():
    module = _canonical_module()
    app = _factory()

    with pytest.raises(LegacyRouteRegistrationError, match="already registered"):
        register_legacy_blueprint(app, module.bp_admin_matrizes)
    assert len(_live_moved_rules(app)) == 10


@pytest.mark.parametrize("collision_kind", ["endpoint", "rule_method"])
def test_route_collision_fails_before_any_legacy_route_mutation(collision_kind):
    module = _canonical_module()
    app = _factory(**{BLUEPRINT_FLAG: False})
    if collision_kind == "endpoint":
        app.add_url_rule(
            "/unrelated",
            endpoint="admin_matrizes",
            view_func=lambda: "x",
        )
    else:
        app.add_url_rule(
            "/admin/matrizes",
            endpoint="phase4_matrices_collision",
            view_func=lambda: "x",
            methods=["GET"],
        )

    with pytest.raises(LegacyRouteRegistrationError, match="collision"):
        register_legacy_blueprint(app, module.bp_admin_matrizes)
    moved_rules = {rule for rule, _, _ in ROUTE_MATRIX}
    assert not any(rule.rule in moved_rules for rule in _live_moved_rules(app))


def test_no_namespaced_endpoint_alias_or_duplicate_rule_exists():
    app = _factory()
    moved = _live_moved_rules(app)

    assert len(moved) == 10
    assert not any(
        rule.endpoint.startswith(f"{BLUEPRINT_VAR}.") for rule in app.url_map.iter_rules()
    )
    assert not any("." in rule.endpoint for rule in moved)
    assert len({rule.rule for rule in moved}) == 10
    for expected_rule, expected_endpoint, expected_methods in ROUTE_MATRIX:
        matches = [
            rule
            for rule in app.url_map.iter_rules()
            if rule.rule == expected_rule
            and tuple(sorted(set(rule.methods or ()) & BUSINESS_METHODS)) == expected_methods
        ]
        assert [rule.endpoint for rule in matches] == [expected_endpoint]


# ---------------------------------------------------------------------------
# 4/5. Global legacy endpoint preservation (request.endpoint / url_for)
# ---------------------------------------------------------------------------


def test_legacy_url_for_and_request_endpoint_behavior():
    app = _factory()

    with app.test_request_context():
        for rule, endpoint, _ in ROUTE_MATRIX:
            values = _rule_values(rule)
            assert url_for(endpoint, **values) == _matriz_rule_materialize(rule, values)

    for rule, endpoint, methods in ROUTE_MATRIX:
        path = _materialize_rule(rule)
        with app.test_request_context(path, method=methods[0]):
            assert request.endpoint == endpoint


def _rule_values(rule: str) -> dict[str, object]:
    values: dict[str, object] = {}
    if "matriz_id" in rule:
        values["matriz_id"] = 1
    if "atividade_id" in rule:
        values["atividade_id"] = 1
    if "active_tab" in rule:
        values["active_tab"] = "academicas"
    return values


def _matriz_rule_materialize(rule: str, values: dict[str, object]) -> str:
    out = rule
    if "matriz_id" in values:
        out = out.replace("<int:matriz_id>", str(values["matriz_id"]))
    if "atividade_id" in values:
        out = out.replace("<int:atividade_id>", str(values["atividade_id"]))
    if "active_tab" in values:
        out = out.replace("<string:active_tab>", str(values["active_tab"]))
    return out


# ---------------------------------------------------------------------------
# 3. Exact RBAC
# ---------------------------------------------------------------------------


def test_rbac_requirements_remain_exact_for_twelve_pairs():
    for _, endpoint, methods in ROUTE_MATRIX:
        for method in methods:
            expected = _expected_requirement(endpoint, method)
            assert get_admin_permission_requirement(endpoint, method) == expected


def test_rbac_scope_counts_remain_exact():
    from collections import Counter

    counts: Counter = Counter()
    for _, endpoint, methods in ROUTE_MATRIX:
        for method in methods:
            resource, scope = _expected_requirement(endpoint, method)
            assert resource == "matrizes"
            counts[scope] += 1
    assert dict(counts) == RBAC_SCOPE_COUNTS


def _expected_requirement(endpoint: str, method: str):
    if endpoint == "admin_editar_matriz":
        return dict(RBAC_EDITAR_MATRIZ_METHOD_PAIRS)[method]
    return RBAC_MATRIX[endpoint]


# admin_editar_matriz: GET=view, POST=edit
RBAC_EDITAR_MATRIZ_METHOD_PAIRS = (("GET", ("matrizes", "view")), ("POST", ("matrizes", "edit")))


# ---------------------------------------------------------------------------
# 7/10. main identity-exports + absence of moved bodies
# ---------------------------------------------------------------------------


def test_main_compatibility_exports_are_identity_imports_and_app_uses_canonical_views():
    import main

    module = _canonical_module()
    for name in ROUTE_NAMES + HELPER_NAMES:
        assert getattr(main, name) is getattr(module, name)
    for name in ROUTE_NAMES:
        assert main.app.view_functions[name] is getattr(module, name)
        assert main.app.view_functions[name].__module__ == module.__name__


def test_main_no_longer_defines_moved_bodies_or_route_decorators_and_reexports():
    import main

    moved = set(ROUTE_NAMES) | set(HELPER_NAMES)
    assert not (moved & _top_level_functions(MAIN_PATH))
    assert set(ROUTE_NAMES) | set(HELPER_NAMES) <= _imports_from(
        MAIN_PATH, "app.views.admin.matrizes"
    )
    source = MAIN_PATH.read_text(encoding="utf-8")
    source_sig = MAIN_PATH.read_text(encoding="utf-8-sig")
    for rule, _, _ in ROUTE_MATRIX:
        assert f'app.route("{rule}"' not in source
        assert f"app.route('{rule}'" not in source
    assert "main" in main.__name__


def test_void_helper_names_absent_from_main_and_module():
    import main

    assert not VOID_HELPER_NAMES & _top_level_functions(MAIN_PATH)
    module = _canonical_module()
    assert not VOID_HELPER_NAMES & _top_level_functions(Path(module.__file__))
    assert not VOID_HELPER_NAMES & _imports_from(MAIN_PATH, "app.views.admin.matrizes")


# ---------------------------------------------------------------------------
# 8. B5-P owner preserved on the two access consumers
# ---------------------------------------------------------------------------


def test_admin_access_owner_preserved_in_matrizes_access_consumers():
    import main
    from app import admin_access

    module = _canonical_module()
    for consumer in ("admin_editar_matriz", "admin_matriz_nova_atividade"):
        func = inspect.unwrap(getattr(module, consumer))
        assert func.__module__ == module.__name__
        for helper in ("_get_current_admin_access_context", "_admin_can"):
            assert func.__globals__[helper] is getattr(admin_access, helper)


# ---------------------------------------------------------------------------
# 9. Route inventory byte-identical + catalog 536 + CSRF 8 owner-only deltas
# ---------------------------------------------------------------------------


def test_route_inventory_baseline_is_byte_identical_and_counts_131_130():
    import main

    raw = ROUTE_INVENTORY_PATH.read_bytes()
    data = json.loads(raw.decode("utf-8"))
    assert data["schema_version"] == 1
    assert data["generated_from"] == "main.app.url_map"
    routes = data["routes"]
    assert len(routes) == 131
    assert len({entry["rule"] for entry in routes}) == 130
    non_static = [entry for entry in routes if entry["rule"] != "/static/<path:filename>"]
    assert len(non_static) == 130

    baseline_triples = {
        (entry["rule"], entry["endpoint"], tuple(entry["methods"])) for entry in routes
    }
    live_triples = {
        (rule.rule, rule.endpoint, tuple(sorted(set(rule.methods or ()) & BUSINESS_METHODS)))
        for rule in main.app.url_map.iter_rules()
        if set(rule.methods or ()) & BUSINESS_METHODS
    }
    assert live_triples == baseline_triples
    assert ROUTE_INVENTORY_PATH.read_bytes() == raw


def test_message_catalog_count_remains_536():
    from utils import messages

    messages._message_catalog.cache_clear()
    catalog = messages._message_catalog()
    assert len(catalog) == 536


def test_canonical_sqlite_never_opened_during_isolated_flow(tmp_path):
    runtime = tmp_path / "canonical-not-touched"
    code = r"""
import json
import os
from pathlib import Path
import sqlite3
import socket
import sys

root = Path(os.environ["PHASE4_MATRIZ_IMPORT_ROOT"])
root.mkdir()

def forbidden(*args, **kwargs):
    raise AssertionError("import-time side effect")

sqlite3.connect = forbidden
socket.create_connection = forbidden
socket.socket.connect = forbidden

import app.views.admin as admin_pkg
import app.views.admin.matrizes as module

assert not Path(os.environ["APP_DATABASE"]).exists()
assert "main" not in sys.modules
print(json.dumps({"ok": True, "module": module.__name__}))
"""
    environment = os.environ.copy()
    environment.update(
        {
            "PHASE4_MATRIZ_IMPORT_ROOT": str(runtime),
            "APP_DATABASE": str(runtime / "never-created.sqlite3"),
            "APP_UPLOAD_FOLDER": str(runtime / "uploads"),
            "APP_DOCUMENTOS_ALUNOS_FOLDER": str(runtime / "documentos"),
            "APP_LOG_DIR": str(runtime / "logs"),
            "APP_LOCAL_BACKUP_DIR": str(runtime / "backups" / "local"),
            "APP_CLOUD_BACKUP_DIR": str(runtime / "backups" / "cloud"),
            "APP_ENV": "testing",
            "APP_SECRET_KEY": "phase4-matrizes-import-test-secret-key-000000000000",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUTF8": "1",
        }
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", code],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["ok"] is True


def test_csrf_snapshots_prove_exactly_eight_owner_only_deltas_when_extracted():
    for snapshot_path in (CSRF_OFF_PATH, CSRF_ON_PATH):
        assert snapshot_path.is_file(), f"missing CSRF snapshot: {snapshot_path}"
        relative = snapshot_path.relative_to(PROJECT_ROOT).as_posix()
        old_result = subprocess.run(
            ["git", "show", f"{BASELINE_COMMIT}:{relative}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=PROJECT_ROOT,
        )
        assert old_result.returncode == 0, old_result.stderr
        old_snapshot = json.loads(old_result.stdout)
        new_snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))

        old_rows = old_snapshot["rows"]
        new_rows = new_snapshot["rows"]
        assert len(old_rows) == len(new_rows) == 78
        assert old_snapshot["summary"] == new_snapshot["summary"]
        assert [row["route"] for row in old_rows] == [row["route"] for row in new_rows]

        deltas = [pair for pair in zip(old_rows, new_rows) if pair[0] != pair[1]]
        assert len(deltas) == 8
        assert {new_row["route"] for _, new_row in deltas} == set(CSRF_MUTATING_PAIRS)

        for old_row, new_row in deltas:
            expected_func = CSRF_MUTATING_PAIRS[new_row["route"]]
            assert old_row["view_function"] == f"main.{expected_func}"
            assert new_row["view_function"] == f"app.views.admin.matrizes.{expected_func}"
            assert new_row["method"] == "POST"
            assert new_row["status"] in ALLOWED_CSRF_STATUSES
            old_other = {k: v for k, v in old_row.items() if k != "view_function"}
            new_other = {k: v for k, v in new_row.items() if k != "view_function"}
            assert old_other == new_other