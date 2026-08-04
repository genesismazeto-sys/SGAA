from __future__ import annotations

import ast
import json
import logging
import os
from pathlib import Path
import subprocess
import sys

import pytest
from flask import request, url_for


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAIN_PATH = PROJECT_ROOT / "main.py"
ALUNO_PATH = PROJECT_ROOT / "app" / "views" / "aluno.py"
VERSIONING_PACKAGE = PROJECT_ROOT / "app" / "versioning"
ADMIN_VERSIONING_PATH = PROJECT_ROOT / "app" / "views" / "admin" / "versioning.py"
HANDOFF_PATH = PROJECT_ROOT / "AGENT_HANDOFF.md"
PROJECT_STATE_PATH = PROJECT_ROOT / "PROJECT_STATE.md"
DOCUMENTATION_INDEX_PATH = PROJECT_ROOT / "docs" / "DOCUMENTATION_INDEX.md"
MASTER_PLAN_PATH = PROJECT_ROOT / "docs" / "mapeamento" / "05_avaliacao_refactor.md"
ARCHITECTURE_LEDGER_PATH = (
    PROJECT_ROOT / "docs" / "refactor" / "ARCHITECTURE_REFACTOR_LEDGER.md"
)
VERSIONING_CONTRACT_PATH = (
    PROJECT_ROOT / "docs" / "refactor" / "PHASE4_VERSIONING_SUBSYSTEM_CONTRACT.md"
)
BUSINESS_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}

ROUTE_MATRIX = (
    (
        "/admin/diagnostico/atividades-versionadas",
        "admin_diagnostico_atividades_versionadas",
        ("GET",),
    ),
    (
        "/admin/diagnostico/atividades-versionadas/view",
        "admin_diagnostico_atividades_versionadas_view",
        ("GET",),
    ),
    (
        "/admin/diagnostico/versioned-shadow-reads",
        "admin_diagnostico_versioned_shadow_reads",
        ("GET",),
    ),
)
ROUTE_NAMES = tuple(endpoint for _, endpoint, _ in ROUTE_MATRIX)
SERVICE_OWNERS = {
    "resolver_versao_por_aluno": "app.versioning.resolver",
    "maybe_write_versioned_requisicao_snapshot": "app.versioning.snapshots",
    "maybe_run_versioned_resolver_shadow_read": "app.versioning.shadow_reads",
    "is_versioned_resolver_shadow_read_enabled": "app.versioning.shadow_reads",
    "is_versioned_requisicao_snapshot_display_enabled": "app.versioning.snapshots",
    "is_versioned_requisicao_snapshot_write_enabled": "app.versioning.snapshots",
}
REMAINING_ALUNO_MAIN_HELPERS = {
    "ensure_admin_arquivos_table",
    "get_admin_arquivo",
    "get_student_request_update_alert",
    "list_active_admin_alertas",
    "mark_student_request_updates_seen",
}


def _factory(**kwargs):
    from app import create_app

    return create_app(
        register_presets_blueprint=False,
        register_aluno_blueprint=False,
        register_admin_configuracoes_blueprint=False,
        **kwargs,
    )


def _route_tuples(app):
    return {
        (
            rule.rule,
            rule.endpoint,
            tuple(sorted(set(rule.methods or ()) & BUSINESS_METHODS)),
        )
        for rule in app.url_map.iter_rules()
        if rule.endpoint in ROUTE_NAMES
    }


def _top_level_functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_phase4_b2_current_governance_records_external_acceptance():
    handoff = HANDOFF_PATH.read_text(encoding="utf-8").split(
        "## Historical state — PHASE 4-B2", 1
    )[1].split("## Historical state — PHASE 4-B1", 1)[0]
    project_state = PROJECT_STATE_PATH.read_text(encoding="utf-8").split(
        "## Historical authoritative state — PHASE 4-B2", 1
    )[1].split("## Historical authoritative state — PHASE 4-B1", 1)[0]
    documentation_index = DOCUMENTATION_INDEX_PATH.read_text(encoding="utf-8").split(
        "- Accepted technical commits:", 1
    )[0]
    master_plan = MASTER_PLAN_PATH.read_text(encoding="utf-8").split(
        "### Fase 4 —", 1
    )[1].split("### Fase 5 —", 1)[0]
    ledger_lines = ARCHITECTURE_LEDGER_PATH.read_text(encoding="utf-8").splitlines()
    ledger = "\n".join(
        line
        for line in ledger_lines
        if line.startswith(("| PHASE4-B2 |", "| Fase 4 |", "| Fase 5 |", "| Fase 6 |"))
    )
    contract = VERSIONING_CONTRACT_PATH.read_text(encoding="utf-8")
    current_records = (
        handoff,
        project_state,
        documentation_index,
        master_plan,
        ledger,
        contract,
    )

    accepted_commit = "17e468ad938e873e1f9e9c303808ad31b9f3806b"
    for record in current_records:
        assert "PHASE 4-B2" in record or "PHASE4-B2" in record
        assert "CLOSED / ACCEPTED" in record
        assert accepted_commit in record
        assert "post-publication" in record.lower()
        assert "complete" in record.lower()

    current_text = "\n".join(current_records).lower()
    for stale_claim in (
        "stage is pending",
        "staging is pending",
        "commit is pending",
        "push is pending",
        "review addendum is pending",
    ):
        assert stale_claim not in current_text

    assert "PHASE 4" in handoff and "OPEN / INCREMENTAL IMPLEMENTATION" in handoff
    assert "PHASE 4-B3: NOT AUTHORIZED" in current_text.upper()
    assert "PHASE 5: NOT AUTHORIZED" in current_text.upper()
    assert "PHASE 6: NOT AUTHORIZED" in current_text.upper()
    assert "MIGRATION V4: PROHIBITED" in current_text.upper()
    assert "PHASE 4-B4.2 CLOSED / ACCEPTED" in master_plan
    assert "PHASE 4-B3 — CLOSED / ACCEPTED" in master_plan
    assert "- [x] `app/views/admin/matrizes.py`" in master_plan
    assert "prerequisite versioning extraction" in " ".join(master_plan.split())


def test_versioning_package_import_isolated_from_main_and_side_effects(tmp_path):
    runtime = tmp_path / "isolated-versioning-import"
    code = r'''
import json
import logging
import os
from pathlib import Path
import socket
import sqlite3
import sys

root = Path(os.environ["PHASE4_B2_IMPORT_ROOT"])
root.mkdir()

def forbidden(*args, **kwargs):
    raise AssertionError("import-time side effect")

sqlite3.connect = forbidden
socket.create_connection = forbidden
socket.socket.connect = forbidden
before = sorted(path.name for path in root.iterdir())
logger = logging.getLogger("main")
handler_count_before = len(logger.handlers)
assert "main" not in sys.modules
import app.versioning as versioning
import app.views.admin.versioning as admin_versioning
assert "main" not in sys.modules
after = sorted(path.name for path in root.iterdir())
assert before == after == []
assert not Path(os.environ["APP_DATABASE"]).exists()
assert len(logger.handlers) == handler_count_before
print(json.dumps({
    "main_imported": False,
    "filesystem_delta": [],
    "database_created": False,
    "handler_delta": 0,
    "service_module": versioning.resolver_versao_por_aluno.__module__,
    "view_module": admin_versioning.admin_diagnostico_atividades_versionadas.__module__,
}))
'''
    environment = os.environ.copy()
    environment.update(
        {
            "PHASE4_B2_IMPORT_ROOT": str(runtime),
            "APP_DATABASE": str(runtime / "never-created.sqlite3"),
            "APP_UPLOAD_FOLDER": str(runtime / "uploads"),
            "APP_DOCUMENTOS_ALUNOS_FOLDER": str(runtime / "documentos"),
            "APP_LOG_DIR": str(runtime / "logs"),
            "APP_ENV": "testing",
            "APP_SECRET_KEY": "phase4-b2-import-test-secret-key-000000000000",
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
        "handler_delta": 0,
        "service_module": "app.versioning.resolver",
        "view_module": "app.views.admin.versioning",
    }


def test_canonical_service_owners_and_main_identity_exports():
    import importlib
    import main

    for name, module_name in SERVICE_OWNERS.items():
        module = importlib.import_module(module_name)
        owner = getattr(module, name)
        assert owner.__module__ == module_name
        assert getattr(main, name) is owner

    views = importlib.import_module("app.views.admin.versioning")
    for name in ROUTE_NAMES:
        owner = getattr(views, name)
        assert owner.__module__ == views.__name__
        assert getattr(main, name) is owner
        assert main.app.view_functions[name] is owner


def test_versioning_loggers_reuse_configured_main_logger_without_duplicates():
    import main
    from app.versioning import shadow_reads, snapshots
    from app.views.admin import versioning

    assert shadow_reads.logger is snapshots.logger is versioning.logger is main.logger
    assert main.logger.level == logging.INFO
    assert main.logger.propagate is True


def test_shadow_read_default_log_paths_preserve_repository_root_contract():
    expected_logs_dir = PROJECT_ROOT / "logs"
    expected_dedicated = expected_logs_dir / "versioned_shadow_reads.log"
    expected_fallback = expected_logs_dir / "app.log"
    environment = os.environ.copy()
    environment.pop("APP_LOG_DIR", None)
    environment.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1"})
    code = r'''
import json
from app.versioning import shadow_reads

print(json.dumps({
    "project_root": str(shadow_reads.PROJECT_ROOT),
    "dedicated": shadow_reads._versioned_shadow_read_dedicated_log_path(),
    "candidates": shadow_reads._collect_versioned_shadow_read_log_paths(),
    "logger_name": shadow_reads.logger.name,
    "handler_count": len(shadow_reads.logger.handlers),
}))
'''
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
    payload = json.loads(result.stdout)
    assert Path(payload["project_root"]) == PROJECT_ROOT
    assert Path(payload["dedicated"]) == expected_dedicated
    assert str(expected_fallback.resolve()) in payload["candidates"]
    assert payload["logger_name"] == "main"
    assert payload["handler_count"] == 0


def test_shadow_read_app_log_dir_and_file_handler_candidates_remain_equivalent(
    tmp_path,
):
    runtime_logs = tmp_path / "runtime" / "logs"
    handler_app_log = runtime_logs / "app.log"
    environment = os.environ.copy()
    environment.update(
        {
            "APP_LOG_DIR": str(runtime_logs),
            "PHASE4_B2_HANDLER_APP_LOG": str(handler_app_log),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUTF8": "1",
        }
    )
    code = r'''
import json
import logging
import os
from app.versioning import shadow_reads

handler = logging.Handler()
handler.baseFilename = os.environ["PHASE4_B2_HANDLER_APP_LOG"]
shadow_reads.logger.addHandler(handler)
try:
    print(json.dumps({
        "dedicated": shadow_reads._versioned_shadow_read_dedicated_log_path(),
        "candidates": shadow_reads._collect_versioned_shadow_read_log_paths(),
        "logger_name": shadow_reads.logger.name,
    }))
finally:
    shadow_reads.logger.removeHandler(handler)
    handler.close()
'''
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
    payload = json.loads(result.stdout)
    dedicated = runtime_logs / "versioned_shadow_reads.log"
    assert Path(payload["dedicated"]) == dedicated
    assert payload["candidates"][0] == str(dedicated.resolve())
    assert str(handler_app_log.resolve()) in payload["candidates"]
    assert str(handler_app_log.resolve()) + ".1" in payload["candidates"]
    assert payload["logger_name"] == "main"


def test_shadow_read_event_representation_and_dedup_identity_remain_compatible():
    from app.versioning import shadow_reads

    event_line = shadow_reads._build_versioned_shadow_read_event_line(
        origin="aluno_create",
        req_id=17,
        aluno_id=23,
        atividade_id_legacy=5,
        status="resolved",
        atividade_versao_id=31,
        codigo_normativo="AAC-rev6",
        eixo="AAC",
        warnings=["legacy_scope"],
        reason="ok",
        timestamp="2026-08-01T12:34:56.123456",
    )
    assert event_line == (
        "event=versioned_resolver_shadow_read origin=aluno_create req_id=17 "
        "aluno_id=23 atividade_id_legacy=5 status=resolved atividade_versao_id=31 "
        'codigo_normativo=AAC-rev6 eixo=AAC warnings=["legacy_scope"] reason=ok '
        "timestamp=2026-08-01T12:34:56.123456"
    )
    event = shadow_reads._parse_versioned_shadow_read_event_line(event_line)
    assert event is not None
    assert shadow_reads._shadow_read_event_dedup_key(event) == (
        "aluno_create",
        17,
        23,
        5,
        "resolved",
        31,
        "AAC-rev6",
        "AAC",
        "ok",
    )


def test_main_has_no_moved_bodies_or_diagnostic_route_decorators():
    moved = set(SERVICE_OWNERS) | set(ROUTE_NAMES)
    assert not moved & _top_level_functions(MAIN_PATH)

    source = MAIN_PATH.read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
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
            assert not str(decorator.args[0].value).startswith("/admin/diagnostico/atividades-versionadas")
            assert str(decorator.args[0].value) != "/admin/diagnostico/versioned-shadow-reads"


def test_exact_three_immutable_legacy_route_specs_and_no_bp_routes():
    from app.views.admin import versioning

    specs = versioning.LEGACY_ROUTE_SPECS
    assert isinstance(specs, tuple)
    assert tuple((spec.rule, spec.endpoint, spec.methods) for spec in specs) == ROUTE_MATRIX
    assert {spec.view_func for spec in specs} == {
        getattr(versioning, name) for name in ROUTE_NAMES
    }
    with pytest.raises((AttributeError, TypeError)):
        specs[0].endpoint = "changed"

    tree = ast.parse(ADMIN_VERSIONING_PATH.read_text(encoding="utf-8"))
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for name in ROUTE_NAMES:
        assert {ast.unparse(item) for item in functions[name].decorator_list} == {"admin_required"}
    assert "@bp_admin_versioning.route" not in ADMIN_VERSIONING_PATH.read_text(encoding="utf-8")


def test_factory_default_opt_out_independence_and_collision_atomicity():
    from app.views.admin import LegacyRouteRegistrationError, register_legacy_blueprint
    from app.views.admin.versioning import bp_admin_versioning

    default_app = _factory()
    opt_out_app = _factory(register_admin_versioning_blueprint=False)
    second_app = _factory()

    assert _route_tuples(default_app) == set(ROUTE_MATRIX)
    assert _route_tuples(second_app) == set(ROUTE_MATRIX)
    assert len(_route_tuples(default_app)) == len(_route_tuples(second_app)) == 3
    assert _route_tuples(opt_out_app) == set()

    collision_app = _factory(register_admin_versioning_blueprint=False)
    collision_app.add_url_rule(
        "/unrelated",
        endpoint=ROUTE_NAMES[1],
        view_func=lambda: "collision",
        methods=["GET"],
    )
    before_collision = {
        (rule.rule, rule.endpoint, tuple(sorted(rule.methods or ())))
        for rule in collision_app.url_map.iter_rules()
    }
    with pytest.raises(LegacyRouteRegistrationError, match="collision"):
        register_legacy_blueprint(collision_app, bp_admin_versioning)
    after_collision = {
        (rule.rule, rule.endpoint, tuple(sorted(rule.methods or ())))
        for rule in collision_app.url_map.iter_rules()
    }
    assert after_collision == before_collision


def test_legacy_url_for_request_endpoint_and_no_namespace_alias():
    app = _factory()
    for rule, endpoint, methods in ROUTE_MATRIX:
        with app.test_request_context(rule, method=methods[0]):
            assert url_for(endpoint) == rule
            assert request.endpoint == endpoint
    assert not any(
        rule.endpoint.startswith("admin_versioning_blueprint.")
        for rule in app.url_map.iter_rules()
    )
    assert not any("." in endpoint for endpoint in ROUTE_NAMES)


def test_exact_rbac_requirements_remain_unchanged():
    from app.auth import get_admin_permission_requirement

    assert get_admin_permission_requirement(ROUTE_NAMES[0], "GET") == ("atividades", "view")
    assert get_admin_permission_requirement(ROUTE_NAMES[1], "GET") == ("atividades", "view")
    assert get_admin_permission_requirement(ROUTE_NAMES[2], "GET") == ("banco_dados", "view")


def test_all_versioning_flags_default_off(monkeypatch):
    from app.versioning import (
        is_versioned_requisicao_snapshot_display_enabled,
        is_versioned_requisicao_snapshot_write_enabled,
        is_versioned_resolver_shadow_read_enabled,
    )

    for name in (
        "SGAA_VERSIONED_RESOLVER_SHADOW_READ",
        "SGAA_VERSIONED_REQUISICAO_SNAPSHOT_DISPLAY",
        "SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE",
    ):
        monkeypatch.delenv(name, raising=False)
    assert is_versioned_resolver_shadow_read_enabled() is False
    assert is_versioned_requisicao_snapshot_display_enabled() is False
    assert is_versioned_requisicao_snapshot_write_enabled() is False


def test_aluno_direct_imports_and_exact_remaining_lazy_main_dependencies():
    source = ALUNO_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "app.versioning"
        for alias in node.names
    }
    assert {
        "maybe_run_versioned_resolver_shadow_read",
        "maybe_write_versioned_requisicao_snapshot",
    } <= imported

    helper = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_get_main_helpers"
    )
    returned = next(node.value for node in ast.walk(helper) if isinstance(node, ast.Return))
    assert isinstance(returned, ast.Dict)
    keys = {key.value for key in returned.keys if isinstance(key, ast.Constant)}
    assert keys == REMAINING_ALUNO_MAIN_HELPERS
    assert "main.maybe_run_versioned_resolver_shadow_read" not in source
    assert "main.maybe_write_versioned_requisicao_snapshot" not in source


def test_versioning_modules_never_import_main_or_own_forbidden_domains():
    expected = {"__init__.py", "resolver.py", "snapshots.py", "shadow_reads.py"}
    paths = sorted(VERSIONING_PACKAGE.glob("*.py"))
    assert {path.name for path in paths} == expected
    paths.append(ADMIN_VERSIONING_PATH)

    forbidden_definitions = {
        "admin_catalogo_atividades",
        "admin_catalogo_atividade_nova",
        "admin_catalogo_atividade_editar",
        "admin_matrizes",
        "admin_requisicoes",
        "ensure_atividade_versioning_schema",
    }
    for path in paths:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        assert "import main" not in source
        assert not forbidden_definitions & {
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(alias.name != "main" for alias in node.names)
            if isinstance(node, ast.ImportFrom):
                assert node.module != "main"
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"__import__", "eval", "exec"}
        assert "CREATE TABLE" not in source
        assert "ALTER TABLE" not in source
        assert "SCHEMA_VERSION" not in source
        if path.name in {"snapshots.py", "shadow_reads.py"}:
            assert ".commit(" not in source
            assert ".rollback(" not in source
