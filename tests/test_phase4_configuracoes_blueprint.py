from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest
from flask import Flask, request, url_for


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAIN_PATH = PROJECT_ROOT / "main.py"
ADMIN_PACKAGE = PROJECT_ROOT / "app" / "views" / "admin"
BUSINESS_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}

ROUTE_MATRIX = (
    ("/admin/configuracoes", "admin_configuracoes", ("GET",)),
    (
        "/admin/configuracoes/horas-padrao",
        "admin_configuracoes_horas_padrao_salvar",
        ("POST",),
    ),
    (
        "/admin/configuracoes/prazo-adequacao",
        "admin_configuracoes_prazo_adequacao_salvar",
        ("POST",),
    ),
    (
        "/admin/configuracoes/tempo-resposta",
        "admin_configuracoes_tempo_resposta_salvar",
        ("POST",),
    ),
    (
        "/admin/configuracoes/tempo-resposta/reset",
        "admin_configuracoes_tempo_resposta_resetar",
        ("POST",),
    ),
    ("/admin/mensagens", "admin_mensagens", ("GET",)),
    ("/admin/mensagens/salvar", "admin_mensagens_salvar", ("POST",)),
    (
        "/admin/mensagens/<message_key>/reset",
        "admin_mensagens_resetar",
        ("POST",),
    ),
)

ROUTE_NAMES = tuple(endpoint for _, endpoint, _ in ROUTE_MATRIX)
HELPER_NAMES = (
    "_normalize_optional_iso_date",
    "get_app_settings",
    "get_response_time_settings",
    "save_app_settings",
    "reset_response_time_metrics",
    "save_return_response_settings",
    "get_horas_settings",
    "save_horas_settings",
)
MOVED_MESSAGE_DEFAULTS = {
    "msg_1512537062fba35b": "Mensagem restaurada para o padrão.",
    "msg_3cfd9280a4d6da6f": "A meta de tempo de resposta deve ser um número inteiro maior ou igual a zero.",
    "msg_4613bb9b498e92ef": "O prazo de adequação deve ser um número inteiro maior ou igual a zero.",
    "msg_5879a82c23a3af1d": "Mensagem atualizada com sucesso.",
    "msg_6206a00ba4a5f008": "Informe uma data válida no formato AAAA-MM-DD.",
    "msg_74033fbada2d1875": "Apuração do tempo de resposta reiniciada a partir de hoje.",
    "msg_88ab2789659bfd66": "O valor de horas deve ser um número inteiro maior ou igual a zero.",
    "msg_a654861c60ded518": "Padrão de horas atualizado com sucesso.",
    "msg_ab39ea13f2a09d09": "O início da apuração não pode estar no futuro.",
    "msg_bfee99afcc4ef021": "Configurações de tempo de resposta atualizadas com sucesso.",
    "msg_df3076ae3d104b97": "Informe uma data válida.",
    "msg_e00429f0684f4079": "Prazo de adequação de solicitações devolvidas atualizado com sucesso.",
}
SETTINGS_MESSAGE_KEYS = {
    "msg_3cfd9280a4d6da6f",
    "msg_4613bb9b498e92ef",
    "msg_6206a00ba4a5f008",
    "msg_88ab2789659bfd66",
    "msg_ab39ea13f2a09d09",
    "msg_df3076ae3d104b97",
}
RBAC_MATRIX = {
    "admin_configuracoes": ("configuracoes", "view"),
    "admin_configuracoes_horas_padrao_salvar": ("configuracoes", "edit"),
    "admin_configuracoes_prazo_adequacao_salvar": ("configuracoes", "edit"),
    "admin_configuracoes_tempo_resposta_salvar": ("configuracoes", "edit"),
    "admin_configuracoes_tempo_resposta_resetar": ("configuracoes", "full"),
    "admin_mensagens": ("mensagens", "view"),
    "admin_mensagens_salvar": ("mensagens", "edit"),
    "admin_mensagens_resetar": ("mensagens", "full"),
}


def _canonical_module():
    from app.views.admin import configuracoes

    return configuracoes


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
    from app import create_app

    return create_app(
        register_presets_blueprint=False,
        register_aluno_blueprint=False,
        **kwargs,
    )


def _admin_session(client):
    with client.session_transaction() as session:
        session["user_id"] = 1
        session["user_type"] = "admin"
        session["user_name"] = "Phase 4 B1"
        session["access_level"] = "admin_total"


def _access_context(configuracoes_scope="none", mensagens_scope="none"):
    return {
        "is_admin": True,
        "access_level": "phase4-test",
        "overrides": {},
        "effective_scopes": {
            "configuracoes": configuracoes_scope,
            "mensagens": mensagens_scope,
        },
        "scope_groups": [],
    }


def test_module_import_isolated_from_main_database_filesystem_and_network(tmp_path):
    runtime = tmp_path / "isolated-import"
    code = r'''
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
import app.views.admin.configuracoes as module
assert "main" not in sys.modules
assert module.__name__ == "app.views.admin.configuracoes"
after = sorted(path.name for path in root.iterdir())
assert before == after == []
assert not Path(os.environ["APP_DATABASE"]).exists()
print(json.dumps({"main_imported": False, "filesystem_delta": [], "database_created": False}))
'''
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
            "APP_SECRET_KEY": "phase4-import-test-secret-key-000000000000",
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
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {
        "main_imported": False,
        "filesystem_delta": [],
        "database_created": False,
    }


def test_exactly_eight_immutable_route_specs_match_legacy_matrix():
    module = _canonical_module()
    specs = module.LEGACY_ROUTE_SPECS

    assert isinstance(specs, tuple)
    assert len(specs) == 8
    assert tuple((spec.rule, spec.endpoint, spec.methods) for spec in specs) == ROUTE_MATRIX
    with pytest.raises((AttributeError, TypeError)):
        specs[0].endpoint = "changed"


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
    assert {spec.view_func for spec in module.LEGACY_ROUTE_SPECS} == {
        getattr(module, name) for name in ROUTE_NAMES
    }


def test_factory_registers_legacy_routes_by_default_and_supports_opt_out():
    default_app = _factory()
    opt_out_app = _factory(register_admin_configuracoes_blueprint=False)

    assert _route_tuples(default_app) == set(ROUTE_MATRIX)
    assert _live_moved_rules(opt_out_app) == []


def test_two_independent_factory_apps_each_register_each_route_once():
    first = _factory()
    second = _factory()

    assert _route_tuples(first) == set(ROUTE_MATRIX)
    assert _route_tuples(second) == set(ROUTE_MATRIX)
    assert len(_live_moved_rules(first)) == len(_live_moved_rules(second)) == 8
    assert first is not second


def test_duplicate_blueprint_registration_fails_explicitly():
    from app.views.admin import LegacyRouteRegistrationError, register_legacy_blueprint

    module = _canonical_module()
    app = _factory()

    with pytest.raises(LegacyRouteRegistrationError, match="already registered"):
        register_legacy_blueprint(app, module.bp_admin_configuracoes)
    assert len(_live_moved_rules(app)) == 8


@pytest.mark.parametrize("collision_kind", ["endpoint", "rule_method"])
def test_route_collision_fails_before_any_legacy_route_mutation(collision_kind):
    from app.views.admin import LegacyRouteRegistrationError, register_legacy_blueprint

    module = _canonical_module()
    app = _factory(register_admin_configuracoes_blueprint=False)
    if collision_kind == "endpoint":
        app.add_url_rule("/unrelated", endpoint="admin_configuracoes", view_func=lambda: "x")
    else:
        app.add_url_rule(
            "/admin/configuracoes",
            endpoint="phase4_collision",
            view_func=lambda: "x",
            methods=["GET"],
        )

    with pytest.raises(LegacyRouteRegistrationError, match="collision"):
        register_legacy_blueprint(app, module.bp_admin_configuracoes)
    moved_rules = {rule for rule, _, _ in ROUTE_MATRIX}
    assert not any(rule.rule in moved_rules for rule in _live_moved_rules(app))


def test_no_namespaced_endpoint_alias_or_duplicate_rule_exists():
    app = _factory()
    moved = _live_moved_rules(app)

    assert len(moved) == 8
    assert not any(rule.endpoint.startswith("admin_configuracoes_blueprint.") for rule in app.url_map.iter_rules())
    assert not any("." in rule.endpoint for rule in moved)
    assert len({rule.rule for rule in moved}) == 8
    for expected_rule, expected_endpoint, expected_methods in ROUTE_MATRIX:
        matches = [
            rule
            for rule in app.url_map.iter_rules()
            if rule.rule == expected_rule
            and tuple(sorted(set(rule.methods or ()) & BUSINESS_METHODS)) == expected_methods
        ]
        assert [rule.endpoint for rule in matches] == [expected_endpoint]


def test_legacy_url_for_and_request_endpoint_behavior():
    app = _factory()

    with app.test_request_context():
        for rule, endpoint, _ in ROUTE_MATRIX:
            values = {"message_key": "sample"} if "<message_key>" in rule else {}
            assert url_for(endpoint, **values) == rule.replace("<message_key>", "sample")

    for rule, endpoint, methods in ROUTE_MATRIX:
        path = rule.replace("<message_key>", "sample")
        with app.test_request_context(path, method=methods[0]):
            assert request.endpoint == endpoint


def test_main_compatibility_exports_are_identity_imports_and_app_uses_canonical_views():
    import main
    from app import settings

    module = _canonical_module()
    for name in ROUTE_NAMES:
        assert getattr(main, name) is getattr(module, name)
    for name in HELPER_NAMES:
        assert getattr(main, name) is getattr(settings, name)
        assert getattr(module, name) is getattr(settings, name)
    for name in ROUTE_NAMES:
        assert main.app.view_functions[name] is getattr(module, name)
        assert main.app.view_functions[name].__module__ == module.__name__


def test_main_no_longer_defines_moved_bodies_or_route_decorators():
    tree = ast.parse(MAIN_PATH.read_text(encoding="utf-8-sig"))
    defined = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert not (set(ROUTE_NAMES) | set(HELPER_NAMES)) & defined

    route_imports = [
        alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        and node.module == "app.views.admin.configuracoes"
        for alias in node.names
    ]
    helper_imports = [
        alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        and node.module == "app.settings"
        for alias in node.names
    ]
    assert set(ROUTE_NAMES) <= set(route_imports)
    assert set(HELPER_NAMES) <= set(helper_imports)

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            assert not (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and isinstance(decorator.func.value, ast.Name)
                and decorator.func.value.id == "app"
                and decorator.func.attr == "route"
                and decorator.args
                and isinstance(decorator.args[0], ast.Constant)
                and str(decorator.args[0].value).startswith(
                    ("/admin/configuracoes", "/admin/mensagens")
                )
            )


def test_rbac_requirements_remain_exact():
    from app.auth import get_admin_permission_requirement

    for _, endpoint, methods in ROUTE_MATRIX:
        assert len(methods) == 1
        assert get_admin_permission_requirement(endpoint, methods[0]) == RBAC_MATRIX[endpoint]


def test_view_edit_and_full_scope_denials_remain_ranked():
    from app.auth import permission_scope_satisfies

    assert permission_scope_satisfies("view", "view")
    assert not permission_scope_satisfies("view", "edit")
    assert not permission_scope_satisfies("view", "full")
    assert permission_scope_satisfies("edit", "view")
    assert permission_scope_satisfies("edit", "edit")
    assert not permission_scope_satisfies("edit", "full")
    assert permission_scope_satisfies("full", "view")
    assert permission_scope_satisfies("full", "edit")
    assert permission_scope_satisfies("full", "full")


@pytest.mark.parametrize(
    ("path", "scope", "expected_required"),
    [
        ("/admin/configuracoes", "none", "view"),
        ("/admin/configuracoes/tempo-resposta", "view", "edit"),
        ("/admin/configuracoes/tempo-resposta/reset", "edit", "full"),
    ],
)
def test_browser_and_ajax_denial_contracts_remain_unchanged(
    monkeypatch, path, scope, expected_required
):
    import main
    from app.web import authz_gate

    # UT-3: the before_request gate moved to app.web.authz_gate and resolves the
    # access-context helper through that module's globals, so the stub has to be
    # installed there (main only re-exports the gate for registration).
    monkeypatch.setattr(
        authz_gate,
        "_get_current_admin_access_context",
        lambda force_reload=False: _access_context(configuracoes_scope=scope),
    )
    monkeypatch.setitem(main.app.config, "WTF_CSRF_ENABLED", False)
    method = "GET" if path == "/admin/configuracoes" else "POST"

    browser = main.app.test_client()
    _admin_session(browser)
    browser_response = browser.open(path, method=method, follow_redirects=False)
    assert browser_response.status_code == 302
    assert browser_response.headers["Location"].endswith("/admin/dashboard")

    ajax = main.app.test_client()
    _admin_session(ajax)
    ajax_response = ajax.open(
        path,
        method=method,
        headers={"X-Requested-With": "XMLHttpRequest"},
        follow_redirects=False,
    )
    assert ajax_response.status_code == 403
    assert ajax_response.get_json() == {
        "ok": False,
        "error": "forbidden",
        "resource": "configuracoes",
        "required_scope": expected_required,
        "message": ajax_response.get_json()["message"],
    }


def test_post_csrf_behavior_remains_enforced(monkeypatch):
    import main
    from app.web import authz_gate

    # UT-3: see test_browser_and_ajax_denial_contracts_remain_unchanged.
    monkeypatch.setattr(
        authz_gate,
        "_get_current_admin_access_context",
        lambda force_reload=False: _access_context(configuracoes_scope="full"),
    )
    monkeypatch.setitem(main.app.config, "WTF_CSRF_ENABLED", True)
    client = main.app.test_client()
    _admin_session(client)

    response = client.post(
        "/admin/configuracoes/tempo-resposta",
        data={"response_goal_days": "5", "response_metrics_reset_at": ""},
        follow_redirects=False,
    )
    assert response.status_code == 400


def test_settings_helpers_preserve_persistence_and_normalization():
    module = _canonical_module()
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        module.save_app_settings(
            conn,
            {"response_goal_days": "7", "response_metrics_reset_at": ""},
        )
        module.save_return_response_settings(
            conn,
            {"return_response_days": "3", "auto_indefer_devolvida": "on"},
        )
        module.save_horas_settings(
            conn,
            {"horas_padrao_academica": "9", "horas_padrao_extensao": "11"},
        )
        response = module.get_response_time_settings(conn)
        horas = module.get_horas_settings(conn)
        assert response["response_goal_days"] == 7
        assert response["return_response_days"] == 3
        assert response["auto_indefer_devolvida"] is True
        assert horas == {"horas_padrao_academica": 9, "horas_padrao_extensao": 11}

        reset = module.reset_response_time_metrics(conn)
        assert reset["response_metrics_reset_at"]
        assert module.get_response_time_settings(conn)["response_metrics_reset_at"] == reset[
            "response_metrics_reset_at"
        ]
    finally:
        conn.close()


def test_message_save_and_reset_routes_preserve_persistence(monkeypatch):
    import main
    from app.web import authz_gate
    from utils.messages import message_key_for_default, resolve_user_message

    module = _canonical_module()
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    default = "Aluno não encontrado."
    key = message_key_for_default(default)
    override = "Aluno não localizado pelo teste da Fase 4."
    monkeypatch.setattr(module, "get_db_connection", lambda: conn)
    # UT-3: see test_browser_and_ajax_denial_contracts_remain_unchanged.
    monkeypatch.setattr(
        authz_gate,
        "_get_current_admin_access_context",
        lambda force_reload=False: _access_context(mensagens_scope="full"),
    )
    monkeypatch.setitem(main.app.config, "WTF_CSRF_ENABLED", False)
    client = main.app.test_client()
    _admin_session(client)
    try:
        saved = client.post(
            "/admin/mensagens/salvar",
            data={"message_key": key, "message_text": override},
            follow_redirects=False,
        )
        assert saved.status_code in (302, 303)
        assert saved.headers["Location"].endswith("/admin/mensagens")
        assert resolve_user_message(default, conn=conn) == override

        reset = client.post(f"/admin/mensagens/{key}/reset", follow_redirects=False)
        assert reset.status_code in (302, 303)
        assert reset.headers["Location"].endswith("/admin/mensagens")
        assert resolve_user_message(default, conn=conn) == default
    finally:
        conn.close()


def test_admin_package_has_no_main_import_or_dynamic_equivalent():
    assert ADMIN_PACKAGE.is_dir()
    sources = list(ADMIN_PACKAGE.glob("*.py"))
    assert {path.name for path in sources} == {
        "__init__.py",
        "acesso.py",
        "alunos_turmas_cursos.py",
        "atividades.py",
        "banco_dados.py",
        "configuracoes.py",
        "matrizes.py",
        "requisicoes.py",
        "versioning.py",
    }

    for path in sources:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        assert "import main" not in source
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(alias.name != "main" for alias in node.names)
            if isinstance(node, ast.ImportFrom):
                assert node.module != "main"
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"__import__", "eval", "exec"}
        assert "sys.modules" not in source
        assert "importlib" not in source


def test_backend_message_inventory_recurses_deterministically_without_duplicates():
    from utils import messages as messages_module

    paths = messages_module._iter_backend_files()
    relative_paths = [path.relative_to(PROJECT_ROOT).as_posix() for path in paths]

    assert relative_paths == sorted(relative_paths)
    assert len(relative_paths) == len(set(relative_paths))
    assert "main.py" in relative_paths
    assert "app/auth.py" in relative_paths
    assert "app/db_maintenance.py" in relative_paths
    assert "app/settings.py" in relative_paths
    assert "app/uploads.py" in relative_paths
    assert "app/views/admin/atividades.py" in relative_paths
    assert "app/views/admin/configuracoes.py" in relative_paths
    assert all(path.endswith(".py") for path in relative_paths)
    assert all("__pycache__" not in Path(path).parts for path in relative_paths)
    assert all(
        path in {
            "main.py",
            "app/academics.py",
            "app/auth.py",
            "app/db_maintenance.py",
            "app/requisitions.py",
            "app/settings.py",
            "app/uploads.py",
            # UT-3: canonical owners of the message sinks moved out of main.py
            # (_admin_access_denied_response -> authz_gate,
            # handle_large_upload -> errors).  app/web/context.py is absent on
            # purpose: it forwards an already-resolved catalog and owns no sink.
            "app/web/authz_gate.py",
            "app/web/errors.py",
        }
        or path.startswith("app/views/")
        for path in relative_paths
    )


def test_moved_message_catalog_entries_keep_keys_defaults_and_canonical_usage_owner():
    from utils import messages as messages_module

    messages_module._message_catalog.cache_clear()
    catalog = messages_module._message_catalog()

    assert len(catalog) == 536
    assert {
        key: catalog[key]["default_text"] for key in MOVED_MESSAGE_DEFAULTS
    } == MOVED_MESSAGE_DEFAULTS
    for key in MOVED_MESSAGE_DEFAULTS:
        usages = catalog[key]["usages"]
        assert usages
        expected_owner = (
            "app/settings.py"
            if key in SETTINGS_MESSAGE_KEYS
            else "app/views/admin/configuracoes.py"
        )
        assert all(
            usage["source_path"] == expected_owner
            for usage in usages
        )
