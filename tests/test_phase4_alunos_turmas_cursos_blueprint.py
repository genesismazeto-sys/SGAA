"""PHASE 4-B6 — Alunos/Turmas/Cursos legacy blueprint contract (RED-only).

RED-only mission: the canonical owner ``app.views.admin.alunos_turmas_cursos``
does not exist yet.  This module codifies the full B6 contract that production
must honour after extraction, and in the current (RED) baseline it must fail
only because that resource is absent — never because of a collection/syntax
error in this test module.

Contract covered here (GREEN targets):

  1. canonical module/blueprint/spec tuple: ``app.views.admin.alunos_turmas_cursos``,
     ``bp_admin_alunos_turmas_cursos`` (blueprint name
     ``admin_alunos_turmas_cursos_blueprint``) and immutable ``LEGACY_ROUTE_SPECS``;
  2. exact route cohort: 17 endpoints / 24 rule-method pairs, no extra;
  3. exact 10 private helpers (no 11th); ``periodo_corrente`` stays main-local
     and is never aliased into the module;
  4. ``@admin_required`` preserved on every handler; no ``@bp.route``, namespace
     aliases, duplicate routes, wrappers, ``import main``, dynamic import or
     ``sys.modules`` bridge;
  5. factory default registration and explicit opt-out removing exactly B6;
     independent app isolation; endpoint/rule collision atomicity;
  6. ``main`` identity re-exports for all 27 moved symbols with zero local
     bodies/decorators; direct consumption of the accepted neutral owners
     ``app.academics`` (3), ``app.user_accounts`` (5), ``app.web.request`` (1);
     zero app-to-main edge;
  7. helper and handler moved-body AST equivalence to git baseline ``cab4c61``
     (decorators ignored only where appropriate, never bodies); handler bodies
     are equivalent modulo removal of ``@app.route`` and exactly the R1 dead
     keyword deletions; the exact ten helper bodies remain literally
     AST-equivalent;
  8. ``periodo_corrente`` body unchanged against ``cab4c61`` and still main-local;
     ``_build_admin_dashboard_turma_cards`` still resolves/calls it; the exact
     three moved handlers carry no ``periodo_corrente`` reference and no
     template in ``templates/**`` contains the token;
  9. RBAC exact VIEW 6 / EDIT 13 / FULL 5 for all 24 pairs;
 10. route inventory 20814 bytes, SHA256
     ``6e32148cd1988d5e405c9d11bdbda285359f72d5fc7eca8bd5ef8da9b83049fa`` and
      live URL contract unchanged; message catalog exactly 536; final CSRF
      snapshots differ from baseline ``cab4c61`` by exactly 27 POST owner-only
      deltas in each shadow: 11 B6 (main ->
      app.views.admin.alunos_turmas_cursos) + 11 UT-8 Banco de Dados (main ->
      app.views.admin.banco_dados) + 5 UT-9 Acesso (main ->
      app.views.admin.acesso), same row totals, equal summaries, no
      non-owner delta); protected excluded routes remain outside the cohort;
      ``auth.py`` static baseline unchanged.

All DB work is confined to temporary/in-memory SQLite.  The institutional
database is never opened and no network is used.
"""
from __future__ import annotations

import ast
import hashlib
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from flask import request, url_for

from app import create_app
from app.auth import get_admin_permission_requirement
from app.views.admin import LegacyRouteRegistrationError, register_legacy_blueprint


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAIN_PATH = PROJECT_ROOT / "main.py"
AUTH_PATH = PROJECT_ROOT / "app" / "auth.py"
ADMIN_PACKAGE = PROJECT_ROOT / "app" / "views" / "admin"
MODULE_PATH = ADMIN_PACKAGE / "alunos_turmas_cursos.py"

ARTIFACTS_DIR = PROJECT_ROOT / "tests" / "_artifacts"
ROUTE_INVENTORY_PATH = ARTIFACTS_DIR / "route_inventory_baseline.json"
CSRF_OFF_PATH = ARTIFACTS_DIR / "csrf_inventory_shadow_off.json"
CSRF_ON_PATH = ARTIFACTS_DIR / "csrf_inventory_shadow_on.json"

BASELINE_COMMIT = "cab4c61bdf7a1eef361a80f426dda558b11e9201"

MODULE_NAME = "app.views.admin.alunos_turmas_cursos"
BLUEPRINT_NAME = "admin_alunos_turmas_cursos_blueprint"
BLUEPRINT_FLAG = "register_admin_alunos_turmas_cursos_blueprint"
BLUEPRINT_VAR = "bp_admin_alunos_turmas_cursos"

# R1 supervisor correction: exactly these three moved handlers drop the dead
# ``periodo_corrente=periodo_corrente`` render_template keyword during
# extraction. No fourth handler is normalized.
R1_KW_DELETIONS = {
    "admin_detalhes_curso": "periodo_corrente",
    "admin_turmas": "periodo_corrente",
    "admin_detalhes_turma": "periodo_corrente",
}

TEMPLATES_DIR = PROJECT_ROOT / "templates"

ROUTE_INVENTORY_BYTES = 20814
ROUTE_INVENTORY_SHA256 = "6e32148cd1988d5e405c9d11bdbda285359f72d5fc7eca8bd5ef8da9b83049fa"

BUSINESS_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}

ROUTE_MATRIX = (
    ("/admin/cursos", "admin_cursos", ("GET",)),
    ("/admin/cursos/adicionar", "admin_adicionar_curso", ("GET", "POST")),
    ("/admin/cursos/<int:curso_id>/editar", "admin_editar_curso", ("GET", "POST")),
    ("/admin/cursos/<int:curso_id>", "admin_detalhes_curso", ("GET",)),
    ("/admin/cursos/<int:curso_id>/visualizar", "admin_visualizar_curso", ("GET",)),
    ("/admin/deletar_curso/<int:curso_id>", "admin_deletar_curso", ("POST",)),
    ("/admin/alunos", "admin_alunos", ("GET",)),
    ("/admin/adicionar_aluno", "admin_adicionar_aluno", ("GET", "POST")),
    ("/admin/editar_aluno/<int:usuario_id>", "admin_editar_aluno", ("GET", "POST")),
    ("/admin/deletar_aluno/<int:usuario_id>", "admin_deletar_aluno", ("POST",)),
    ("/admin/alterar_status_alunos", "admin_alterar_status_alunos", ("POST",)),
    ("/admin/turmas", "admin_turmas", ("GET",)),
    ("/admin/adicionar_turma", "admin_adicionar_turma", ("GET", "POST")),
    ("/admin/editar_turma/<int:turma_id>", "admin_editar_turma", ("GET", "POST")),
    ("/admin/deletar_turma/<int:turma_id>", "admin_deletar_turma", ("POST",)),
    ("/admin/turma/<int:turma_id>", "admin_detalhes_turma", ("GET",)),
    ("/admin/turmas/importar", "admin_turmas_importar", ("GET", "POST")),
)
ROUTE_NAMES = tuple(endpoint for _, endpoint, _ in ROUTE_MATRIX)

HELPER_NAMES = (
    "resolve_existing_aluno_by_identifiers",
    "_matrizes_by_curso",
    "_resolve_turma_matriz_id",
    "_periodo_label_for_turma_row",
    "_turma_effective_matriz_label",
    "validar_codigo_curso",
    "semestre_atual_hoje",
    "proximo_numero_turma_por_curso",
    "curso_mais_populoso_id",
    "_safe_return_to_target",
)
MOVED_SYMBOLS = tuple(ROUTE_NAMES) + tuple(HELPER_NAMES)

ACADEMICS_OWNED = {
    "build_turma_aluno_matricula",
    "resequence_turma_aluno_matriculas",
    "resequence_turma_aluno_matriculas_for_ids",
}
USER_ACCOUNTS_OWNED = {
    "_access_defaults_map",
    "_default_password_for_user_type",
    "create_usuario_with_default_access",
    "create_usuario_with_default_password",
    "normalize_usuario_access_for_user_type",
}
WEB_REQUEST_OWNED = {
    "_is_ajax_request",
}

RBAC_MATRIX = {
    "admin_cursos": ("cursos", "view"),
    "admin_adicionar_curso": ("cursos", "edit"),
    "admin_editar_curso": ("cursos", "edit"),
    "admin_detalhes_curso": ("cursos", "view"),
    "admin_visualizar_curso": ("cursos", "view"),
    "admin_deletar_curso": ("cursos", "full"),
    "admin_alunos": ("alunos", "view"),
    "admin_adicionar_aluno": ("alunos", "edit"),
    "admin_editar_aluno": ("alunos", "edit"),
    "admin_deletar_aluno": ("alunos", "full"),
    "admin_alterar_status_alunos": ("alunos", "edit"),
    "admin_turmas": ("turmas", "view"),
    "admin_adicionar_turma": ("turmas", "edit"),
    "admin_editar_turma": ("turmas", "edit"),
    "admin_deletar_turma": ("turmas", "full"),
    "admin_detalhes_turma": ("turmas", "view"),
    "admin_turmas_importar": ("turmas", "full"),
}
RBAC_SCOPE_COUNTS = {"view": 6, "edit": 13, "full": 5}

CSRF_MUTATING_PAIRS = {
    "/admin/cursos/adicionar": "admin_adicionar_curso",
    "/admin/cursos/<int:curso_id>/editar": "admin_editar_curso",
    "/admin/deletar_curso/<int:curso_id>": "admin_deletar_curso",
    "/admin/adicionar_aluno": "admin_adicionar_aluno",
    "/admin/editar_aluno/<int:usuario_id>": "admin_editar_aluno",
    "/admin/deletar_aluno/<int:usuario_id>": "admin_deletar_aluno",
    "/admin/alterar_status_alunos": "admin_alterar_status_alunos",
    "/admin/adicionar_turma": "admin_adicionar_turma",
    "/admin/editar_turma/<int:turma_id>": "admin_editar_turma",
    "/admin/deletar_turma/<int:turma_id>": "admin_deletar_turma",
    "/admin/turmas/importar": "admin_turmas_importar",
}

# UT-8: the 11 Banco de Dados POST handlers extracted to
# app.views.admin.banco_dados.  They appear as additional owner-only deltas in
# the regenerated CSRF snapshots (main -> app.views.admin.banco_dados).
BANCO_DADOS_MUTATING_PAIRS = {
    "/admin/backup/cloud-folder/<provider>": "admin_backup_cloud_folder",
    "/admin/backup/google/upload": "admin_backup_google_upload",
    "/admin/backup/onedrive/upload": "admin_backup_onedrive_upload",
    "/admin/banco-dados/backup": "admin_banco_dados_backup",
    "/admin/banco-dados/configuracoes": "admin_banco_dados_configuracoes",
    "/admin/banco-dados/drive-settings": "admin_banco_dados_drive_settings",
    "/admin/banco-dados/excluir": "admin_banco_dados_excluir",
    "/admin/banco-dados/oauth/disconnect": "admin_banco_dados_oauth_disconnect",
    "/admin/banco-dados/restaurar": "admin_banco_dados_restaurar",
    "/admin/banco-dados/restaurar/upload": "admin_banco_dados_restaurar_upload",
    "/admin/banco-dados/retencao": "admin_banco_dados_retencao",
}

# UT-9: the 5 Acesso POST handlers extracted to app.views.admin.acesso.  They
# appear as additional owner-only deltas in the regenerated CSRF snapshots
# (main -> app.views.admin.acesso).
ACESSO_MUTATING_PAIRS = {
    "/admin/acesso/<int:usuario_id>/deletar": "admin_acesso_deletar",
    "/admin/acesso/<int:usuario_id>/resetar-senha": "admin_acesso_resetar_senha",
    "/admin/acesso/definir-senha": "admin_acesso_definir_senha",
    "/admin/acesso/salvar": "admin_acesso_salvar",
    "/admin/acesso/senhas-default": "admin_acesso_salvar_senhas_default",
}

# UT-10: the 3 Arquivos POST handlers extracted to app.views.admin.arquivos.
# They appear as additional owner-only deltas in the regenerated CSRF
# snapshots (main -> app.views.admin.arquivos).
ARQUIVOS_MUTATING_PAIRS = {
    "/admin/arquivos/adicionar": "admin_adicionar_arquivo",
    "/admin/arquivos/<int:arquivo_id>/editar": "admin_editar_arquivo",
    "/admin/arquivos/<int:arquivo_id>/deletar": "admin_deletar_arquivo",
}

EXCLUDED_ENDPOINTS = {"admin_api_aluno_requisicao_scope"}
ALLOWED_CSRF_STATUSES = {
    "ok_rendered_form_token",
    "ok_dynamic_form_token",
    "ok_specific_regression_test",
    "ok_fetch_token",
    "ok_api_csrf_contract",
    "not_applicable_documented",
    "ok_logout_or_safe_exception",
}


# ---------------------------------------------------------------------------
# AST / helper utilities
# ---------------------------------------------------------------------------


def _canonical_module():
    try:
        from app.views.admin import alunos_turmas_cursos

        return alunos_turmas_cursos
    except ImportError:
        pytest.fail(
            "canonical owner module app.views.admin.alunos_turmas_cursos is missing "
            "(PHASE 4-B6 extraction not performed)"
        )


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


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


def _function_body_dump(tree: ast.Module, name: str) -> str | None:
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            wrapped = ast.Module(body=list(node.body), type_ignores=[])
            return ast.dump(wrapped, include_attributes=False)
    return None


def _drop_render_template_kwarg(tree: ast.Module, name: str, kwarg: str) -> str:
    """R1 normalization: baseline handler body with the named dead
    render_template keyword deleted (only the R1-corrected handlers use this)."""
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            cloned = ast.Module(body=[node], type_ignores=[])
            for inner in ast.walk(cloned):
                if not isinstance(inner, ast.Call):
                    continue
                if not isinstance(inner.func, ast.Name) or inner.func.id != "render_template":
                    continue
                inner.keywords = [
                    keyword
                    for keyword in inner.keywords
                    if not (isinstance(keyword.arg, str) and keyword.arg == kwarg)
                ]
            wrapped = ast.Module(body=list(node.body), type_ignores=[])
            return ast.dump(wrapped, include_attributes=False)
    return None


def _baseline_main_source() -> str:
    result = subprocess.run(
        ["git", "show", f"{BASELINE_COMMIT}:main.py"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=PROJECT_ROOT,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def _baseline_main_tree() -> ast.Module:
    return ast.parse(_baseline_main_source(), filename="main.py@cab4c61")


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


def _require_b6_factory_switch():
    assert (
        BLUEPRINT_FLAG in inspect.signature(create_app).parameters
    ), f"PHASE 4-B6 factory opt-out switch {BLUEPRINT_FLAG} missing"


def _materialize_rule(rule: str) -> str:
    return (
        rule.replace("<int:curso_id>", "1")
        .replace("<int:usuario_id>", "1")
        .replace("<int:turma_id>", "1")
    )


def _rule_values(rule: str) -> dict[str, int]:
    values: dict[str, int] = {}
    if "<int:curso_id>" in rule:
        values["curso_id"] = 1
    if "<int:usuario_id>" in rule:
        values["usuario_id"] = 1
    if "<int:turma_id>" in rule:
        values["turma_id"] = 1
    return values


# ---------------------------------------------------------------------------
# 1. Canonical module / blueprint / spec tuple
# ---------------------------------------------------------------------------


def test_canonical_owner_module_blueprint_and_spec_triple():
    module = _canonical_module()
    assert module.__name__ == MODULE_NAME
    blueprint = getattr(module, BLUEPRINT_VAR)
    assert blueprint.name == BLUEPRINT_NAME
    specs = module.LEGACY_ROUTE_SPECS
    assert isinstance(specs, tuple)
    assert len(specs) == 17
    assert tuple((spec.rule, spec.endpoint, spec.methods) for spec in specs) == ROUTE_MATRIX
    with pytest.raises((AttributeError, TypeError)):
        specs[0].endpoint = "changed"


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
import app.views.admin.alunos_turmas_cursos as module
assert "main" not in sys.modules
assert module.__name__ == "app.views.admin.alunos_turmas_cursos"
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
            "APP_SECRET_KEY": "phase4-b6-import-test-secret-key-000000000000",
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


def test_route_specs_exactly_17_endpoints_and_24_pairs_with_no_extra():
    module = _canonical_module()
    specs = module.LEGACY_ROUTE_SPECS
    assert len(specs) == 17
    assert len({spec.endpoint for spec in specs}) == 17
    pairs = {(spec.rule, method) for spec in specs for method in spec.methods}
    assert len(pairs) == 24
    assert sum(len(spec.methods) for spec in specs) == 24
    assert {spec.endpoint for spec in specs} == set(ROUTE_NAMES)
    assert not (set(ROUTE_NAMES) & EXCLUDED_ENDPOINTS)
    assert all(rule.startswith("/admin/") for rule, _, _ in ROUTE_MATRIX)
    assert not any(rule.startswith("/aluno/") for rule, _, _ in ROUTE_MATRIX)


def test_route_functions_are_admin_required_and_specs_reference_them():
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
    assert {spec.view_func for spec in module.LEGACY_ROUTE_SPECS} == {
        getattr(module, name) for name in ROUTE_NAMES
    }
    from app.auth import admin_required as auth_admin_required

    assert module.admin_required is auth_admin_required


def test_exactly_ten_helpers_and_no_eleventh():
    module = _canonical_module()
    module_functions = _top_level_functions(Path(module.__file__))
    assert len(HELPER_NAMES) == 10
    assert set(HELPER_NAMES) <= module_functions
    assert "periodo_corrente" not in module_functions
    assert "periodo_corrente" not in _imports_from(MAIN_PATH, MODULE_NAME)


# ---------------------------------------------------------------------------
# 2. Factory registration / opt-out / isolation / collisions
# ---------------------------------------------------------------------------


def test_factory_signature_exposes_exact_b6_registration_switch():
    _require_b6_factory_switch()
    param = inspect.signature(create_app).parameters[BLUEPRINT_FLAG]
    assert param.default is True
    assert param.kind is inspect.Parameter.KEYWORD_ONLY


def test_factory_registers_legacy_routes_by_default_and_supports_opt_out():
    _require_b6_factory_switch()
    default_app = _factory()
    opt_out_app = _factory(**{BLUEPRINT_FLAG: False})

    assert _route_tuples(default_app) == set(ROUTE_MATRIX)
    assert _live_moved_rules(opt_out_app) == []
    assert not any(
        rule.rule in {item[0] for item in ROUTE_MATRIX}
        for rule in opt_out_app.url_map.iter_rules()
    )


def test_two_independent_factory_apps_each_register_each_route_once():
    first = _factory()
    second = _factory()

    assert _route_tuples(first) == set(ROUTE_MATRIX)
    assert _route_tuples(second) == set(ROUTE_MATRIX)
    assert len(_live_moved_rules(first)) == len(_live_moved_rules(second)) == 17
    assert first is not second


def test_duplicate_blueprint_registration_fails_explicitly():
    module = _canonical_module()
    app = _factory()

    with pytest.raises(LegacyRouteRegistrationError, match="already registered"):
        register_legacy_blueprint(app, getattr(module, BLUEPRINT_VAR))
    assert len(_live_moved_rules(app)) == 17


@pytest.mark.parametrize("collision_kind", ["endpoint", "rule_method"])
def test_route_collision_fails_before_any_legacy_route_mutation(collision_kind):
    _require_b6_factory_switch()
    module = _canonical_module()
    app = _factory(**{BLUEPRINT_FLAG: False})
    if collision_kind == "endpoint":
        app.add_url_rule(
            "/unrelated",
            endpoint="admin_cursos",
            view_func=lambda: "x",
        )
    else:
        app.add_url_rule(
            "/admin/cursos",
            endpoint="phase4_b6_collision",
            view_func=lambda: "x",
            methods=["GET"],
        )

    with pytest.raises(LegacyRouteRegistrationError, match="collision"):
        register_legacy_blueprint(app, getattr(module, BLUEPRINT_VAR))
    moved_rules = {rule for rule, _, _ in ROUTE_MATRIX}
    assert not any(rule.rule in moved_rules for rule in _live_moved_rules(app))


def test_no_namespaced_endpoint_alias_or_duplicate_rule_exists():
    app = _factory()
    moved = _live_moved_rules(app)

    assert len(moved) == 17
    assert not any(
        rule.endpoint.startswith(f"{BLUEPRINT_NAME}.") for rule in app.url_map.iter_rules()
    )
    assert not any("." in rule.endpoint for rule in moved)
    assert len({rule.rule for rule in moved}) == 17
    for expected_rule, expected_endpoint, expected_methods in ROUTE_MATRIX:
        matches = [
            rule
            for rule in app.url_map.iter_rules()
            if rule.rule == expected_rule
            and tuple(sorted(set(rule.methods or ()) & BUSINESS_METHODS)) == expected_methods
        ]
        assert [rule.endpoint for rule in matches] == [expected_endpoint]


def test_legacy_url_for_and_request_endpoint_behavior():
    _require_b6_factory_switch()
    app = _factory()

    with app.test_request_context():
        for rule, endpoint, _ in ROUTE_MATRIX:
            assert url_for(endpoint, **_rule_values(rule)) == _materialize_rule(rule)

    for rule, endpoint, methods in ROUTE_MATRIX:
        path = _materialize_rule(rule)
        with app.test_request_context(path, method=methods[0]):
            assert request.endpoint == endpoint


# ---------------------------------------------------------------------------
# 3. RBAC
# ---------------------------------------------------------------------------


def test_rbac_requirements_remain_exact_for_all_24_pairs():
    for _, endpoint, methods in ROUTE_MATRIX:
        for method in methods:
            assert get_admin_permission_requirement(endpoint, method) == RBAC_MATRIX[endpoint]


def test_rbac_scope_counts_remain_exact_view6_edit13_full5():
    from collections import Counter

    counts: Counter = Counter()
    for _, endpoint, methods in ROUTE_MATRIX:
        for method in methods:
            requirement = get_admin_permission_requirement(endpoint, method)
            assert requirement is not None, f"unmapped RBAC for {endpoint} {method}"
            counts[requirement[1]] += 1
    assert dict(counts) == RBAC_SCOPE_COUNTS


# ---------------------------------------------------------------------------
# 4/5. main identity re-exports + zero local bodies/decorators
# ---------------------------------------------------------------------------


def test_main_compatibility_exports_are_identity_imports_and_app_uses_canonical_views():
    import main

    module = _canonical_module()
    assert len(MOVED_SYMBOLS) == 27
    assert len(set(MOVED_SYMBOLS)) == 27
    for name in MOVED_SYMBOLS:
        assert getattr(main, name) is getattr(module, name)
    for name in ROUTE_NAMES:
        assert main.app.view_functions[name] is getattr(module, name)
        assert main.app.view_functions[name].__module__ == MODULE_NAME


def test_main_no_longer_defines_moved_bodies_or_route_decorators():
    import main

    moved = set(ROUTE_NAMES) | set(HELPER_NAMES)
    assert not (moved & _top_level_functions(MAIN_PATH))
    assert moved <= _imports_from(MAIN_PATH, MODULE_NAME)
    source = MAIN_PATH.read_text(encoding="utf-8")
    for rule, _, _ in ROUTE_MATRIX:
        assert f'app.route("{rule}"' not in source
        assert f"app.route('{rule}'" not in source


# ---------------------------------------------------------------------------
# 6. Accepted neutral owners, zero app-to-main edge
# ---------------------------------------------------------------------------


def test_module_directly_consumes_accepted_neutral_owners():
    from app import academics, user_accounts
    from app.web import request as web_request

    module = _canonical_module()
    owners = {
        name: academics for name in ACADEMICS_OWNED
    }
    owners.update({name: user_accounts for name in USER_ACCOUNTS_OWNED})
    owners.update({name: web_request for name in WEB_REQUEST_OWNED})
    assert len(owners) == 9

    for name, owner in owners.items():
        assert getattr(module, name) is getattr(owner, name)

    module_path = Path(module.__file__)
    assert ACADEMICS_OWNED <= _imports_from(module_path, "app.academics")
    assert USER_ACCOUNTS_OWNED <= _imports_from(module_path, "app.user_accounts")
    assert WEB_REQUEST_OWNED <= _imports_from(module_path, "app.web.request")

    source = module_path.read_text(encoding="utf-8")
    assert "import main" not in source
    assert "sys.modules" not in source
    assert "importlib" not in source


# ---------------------------------------------------------------------------
# 7/8. Moved-body AST equivalence to cab4c61; periodo_corrente main-local
# ---------------------------------------------------------------------------


def test_moved_handler_and_helper_bodies_ast_equivalent_to_baseline():
    baseline_tree = _baseline_main_tree()
    module = _canonical_module()
    module_tree = ast.parse(
        Path(module.__file__).read_text(encoding="utf-8"),
        filename=str(module.__file__),
    )
    for name in MOVED_SYMBOLS:
        baseline_body = _function_body_dump(baseline_tree, name)
        module_body = _function_body_dump(module_tree, name)
        assert baseline_body is not None, f"baseline main.py has no function {name}"
        assert module_body is not None, f"module has no function {name}"
        if name in R1_KW_DELETIONS:
            expected = _drop_render_template_kwarg(
                baseline_tree, name, R1_KW_DELETIONS[name]
            )
            assert expected == module_body, (
                f"moved body differs from baseline beyond the R1 keyword "
                f"deletion for {name}"
            )
        else:
            assert module_body == baseline_body, f"moved body differs from baseline for {name}"


def _count_render_template_kwargs(tree: ast.Module, name: str, kwarg: str) -> int:
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return sum(
                1
                for inner in ast.walk(node)
                if isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Name)
                and inner.func.id == "render_template"
                and any(
                    isinstance(keyword.arg, str) and keyword.arg == kwarg
                    for keyword in inner.keywords
                )
            )
    return 0


def test_r1_three_dead_keywords_removed_exactly_and_no_fourth():
    module = _canonical_module()
    module_source = Path(module.__file__).read_text(encoding="utf-8")
    module_tree = ast.parse(module_source, filename=str(module.__file__))
    baseline_tree = _baseline_main_tree()

    assert len(R1_KW_DELETIONS) == 3
    assert set(R1_KW_DELETIONS) == {
        "admin_detalhes_curso",
        "admin_turmas",
        "admin_detalhes_turma",
    }

    for name, kwarg in R1_KW_DELETIONS.items():
        assert _count_render_template_kwargs(baseline_tree, name, kwarg) == 1, name
        assert _count_render_template_kwargs(module_tree, name, kwarg) == 0, name
        node = next(
            node
            for node in module_tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        )
        assert "periodo_corrente" not in ast.unparse(node), name

    assert "periodo_corrente" not in module_source
    assert _count_render_template_kwargs(module_tree, "admin_visualizar_curso", "periodo_corrente") == 0

    # The exact ten helper bodies remain literally AST-equivalent (no R1 kwarg).
    for name in HELPER_NAMES:
        assert _function_body_dump(module_tree, name) == _function_body_dump(
            baseline_tree, name
        ), f"helper body drift for {name}"


def test_periodo_corrente_unchanged_against_baseline_and_still_main_local():
    baseline_tree = _baseline_main_tree()
    current_tree = _tree(MAIN_PATH)

    assert _function_body_dump(current_tree, "periodo_corrente") == _function_body_dump(
        baseline_tree, "periodo_corrente"
    )
    assert "periodo_corrente" in _top_level_functions(MAIN_PATH)

    module = _canonical_module()
    assert "periodo_corrente" not in _top_level_functions(Path(module.__file__))
    assert "periodo_corrente" not in _imports_from(MAIN_PATH, MODULE_NAME)


def test_build_admin_dashboard_turma_cards_still_resolves_and_calls_periodo_corrente():
    baseline_tree = _baseline_main_tree()
    current_tree = _tree(MAIN_PATH)

    assert "periodo_corrente" in _top_level_functions(MAIN_PATH)
    assert "_build_admin_dashboard_turma_cards" in _top_level_functions(MAIN_PATH)
    assert _function_body_dump(
        current_tree, "_build_admin_dashboard_turma_cards"
    ) == _function_body_dump(baseline_tree, "_build_admin_dashboard_turma_cards")

    import main

    source = inspect.getsource(main._build_admin_dashboard_turma_cards)
    assert "periodo_corrente(" in source
    module = _canonical_module()
    assert "periodo_corrente" not in _top_level_functions(Path(module.__file__))
    assert "periodo_corrente" not in _imports_from(MAIN_PATH, MODULE_NAME)


def test_no_template_references_periodo_corrente():
    assert TEMPLATES_DIR.is_dir()
    matches = []
    for path in TEMPLATES_DIR.rglob("*"):
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "periodo_corrente" in content:
            matches.append(path.relative_to(PROJECT_ROOT).as_posix())
    assert matches == []


# ---------------------------------------------------------------------------
# 9/10. Route inventory, catalog, CSRF snapshots, auth static baseline
# ---------------------------------------------------------------------------


def test_route_inventory_baseline_is_byte_identical_and_live_url_contract_unchanged():
    import main

    raw = ROUTE_INVENTORY_PATH.read_bytes()
    assert len(raw) == ROUTE_INVENTORY_BYTES
    assert hashlib.sha256(raw).hexdigest() == ROUTE_INVENTORY_SHA256

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


def test_csrf_snapshots_prove_exactly_eleven_b6_owner_only_deltas_when_extracted():
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
        deltas_by_route = {
            new_row["route"]: (old_row, new_row) for old_row, new_row in deltas
        }
        # UT-8: the snapshot regenerated after the Banco de Dados extraction
        # gains exactly 11 additional owner-only deltas (main ->
        # app.views.admin.banco_dados).  UT-9: the Acesso extraction adds
        # exactly 5 more owner-only deltas (main -> app.views.admin.acesso).
        # UT-10: the Arquivos extraction adds exactly 3 more owner-only deltas
        # (main -> app.views.admin.arquivos).
        # The historical 11 B6 deltas remain owner-only and unchanged.
        # 30 = 11 B6 + 11 UT-8 + 5 UT-9 + 3 UT-10, exhaustively partitioned
        # with no uncategorized delta.
        b6_routes = set(CSRF_MUTATING_PAIRS)
        banco_dados_routes = set(BANCO_DADOS_MUTATING_PAIRS)
        acesso_routes = set(ACESSO_MUTATING_PAIRS)
        arquivos_routes = set(ARQUIVOS_MUTATING_PAIRS)
        assert len(b6_routes) == 11
        assert len(banco_dados_routes) == 11
        assert len(acesso_routes) == 5
        assert len(arquivos_routes) == 3
        assert not (b6_routes & banco_dados_routes)
        assert not (b6_routes & acesso_routes)
        assert not (b6_routes & arquivos_routes)
        assert not (banco_dados_routes & acesso_routes)
        assert not (banco_dados_routes & arquivos_routes)
        assert not (acesso_routes & arquivos_routes)
        assert len(deltas_by_route) == 30
        assert set(deltas_by_route) == (
            b6_routes | banco_dados_routes | acesso_routes | arquivos_routes
        )

        b6_deltas = [
            pair for route, pair in deltas_by_route.items() if route in b6_routes
        ]
        banco_dados_deltas = [
            pair
            for route, pair in deltas_by_route.items()
            if route in banco_dados_routes
        ]
        acesso_deltas = [
            pair for route, pair in deltas_by_route.items() if route in acesso_routes
        ]
        arquivos_deltas = [
            pair
            for route, pair in deltas_by_route.items()
            if route in arquivos_routes
        ]
        assert len(b6_deltas) == 11
        assert len(banco_dados_deltas) == 11
        assert len(acesso_deltas) == 5
        assert len(arquivos_deltas) == 3

        for old_row, new_row in b6_deltas:
            expected_func = CSRF_MUTATING_PAIRS[new_row["route"]]
            assert old_row["view_function"] == f"main.{expected_func}"
            assert new_row["view_function"] == f"{MODULE_NAME}.{expected_func}"
            assert new_row["method"] == "POST"
            assert new_row["status"] in ALLOWED_CSRF_STATUSES
            old_other = {k: v for k, v in old_row.items() if k != "view_function"}
            new_other = {k: v for k, v in new_row.items() if k != "view_function"}
            assert old_other == new_other

        for old_row, new_row in banco_dados_deltas:
            expected_func = BANCO_DADOS_MUTATING_PAIRS[new_row["route"]]
            assert old_row["view_function"] == f"main.{expected_func}"
            assert (
                new_row["view_function"]
                == f"app.views.admin.banco_dados.{expected_func}"
            )
            assert new_row["method"] == "POST"
            assert new_row["status"] in ALLOWED_CSRF_STATUSES
            old_other = {k: v for k, v in old_row.items() if k != "view_function"}
            new_other = {k: v for k, v in new_row.items() if k != "view_function"}
            assert old_other == new_other

        for old_row, new_row in acesso_deltas:
            expected_func = ACESSO_MUTATING_PAIRS[new_row["route"]]
            assert old_row["view_function"] == f"main.{expected_func}"
            assert (
                new_row["view_function"]
                == f"app.views.admin.acesso.{expected_func}"
            )
            assert new_row["method"] == "POST"
            assert new_row["status"] in ALLOWED_CSRF_STATUSES
            old_other = {k: v for k, v in old_row.items() if k != "view_function"}
            new_other = {k: v for k, v in new_row.items() if k != "view_function"}
            assert old_other == new_other

        for old_row, new_row in arquivos_deltas:
            expected_func = ARQUIVOS_MUTATING_PAIRS[new_row["route"]]
            assert old_row["view_function"] == f"main.{expected_func}"
            assert (
                new_row["view_function"]
                == f"app.views.admin.arquivos.{expected_func}"
            )
            assert new_row["method"] == "POST"
            assert new_row["status"] in ALLOWED_CSRF_STATUSES
            old_other = {k: v for k, v in old_row.items() if k != "view_function"}
            new_other = {k: v for k, v in new_row.items() if k != "view_function"}
            assert old_other == new_other


def test_protected_excluded_routes_remain_outside_cohort():
    assert "admin_api_aluno_requisicao_scope" not in set(ROUTE_NAMES)
    assert "/admin/api/aluno/<int:aluno_id>/requisicao-scope" not in {
        rule for rule, _, _ in ROUTE_MATRIX
    }
    assert not any(rule.startswith("/aluno/") for rule, _, _ in ROUTE_MATRIX)


def test_auth_static_baseline_unchanged_against_cab4c61():
    result = subprocess.run(
        ["git", "show", f"{BASELINE_COMMIT}:app/auth.py"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=PROJECT_ROOT,
    )
    assert result.returncode == 0, result.stderr
    baseline = result.stdout.replace("\r\n", "\n")
    current = AUTH_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert baseline == current
