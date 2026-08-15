from __future__ import annotations

import ast
from copy import deepcopy
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
ADMIN_PACKAGE = PROJECT_ROOT / "app" / "views" / "admin"
REQUISICOES_VIEW_PATH = ADMIN_PACKAGE / "requisicoes.py"
ARTIFACTS_DIR = PROJECT_ROOT / "tests" / "_artifacts"
ROUTE_INVENTORY_PATH = ARTIFACTS_DIR / "route_inventory_baseline.json"
CSRF_OFF_PATH = ARTIFACTS_DIR / "csrf_inventory_shadow_off.json"
CSRF_ON_PATH = ARTIFACTS_DIR / "csrf_inventory_shadow_on.json"
B4_2_BASELINE_COMMIT = "c587098152e97d125f41a2d26f2f414c10ae5676"

BUSINESS_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}

ROUTE_MATRIX = (
    ("/admin/importar_requisicoes", "admin_importar_requisicoes", ("GET", "POST")),
    ("/admin/requisicoes", "admin_requisicoes", ("GET",)),
    ("/admin/requisicoes/nova", "admin_nova_requisicao", ("GET", "POST")),
    ("/admin/requisicoes/<int:req_id>/editar", "admin_editar_requisicao", ("POST",)),
    ("/admin/requisicoes/<int:req_id>/excluir", "admin_excluir_requisicao", ("POST",)),
    ("/admin/requisicao/<int:req_id>", "admin_detalhes_requisicao", ("GET",)),
    ("/admin/api/requisicao/<int:req_id>", "admin_api_requisicao", ("GET",)),
    (
        "/admin/api/aluno/<int:aluno_id>/requisicao-scope",
        "admin_api_aluno_requisicao_scope",
        ("GET",),
    ),
    ("/admin/processar_requisicao/<int:req_id>", "admin_processar_requisicao", ("GET", "POST")),
)
ROUTE_NAMES = tuple(endpoint for _, endpoint, _ in ROUTE_MATRIX)

HELPER_NAMES = (
    "_normalize_requisicao_data_evento",
    "_get_admin_requisicao_scope_for_aluno",
    "_list_admin_requisicao_alunos",
    "_append_requisicao_arquivos",
)
CONSTANT_NAMES = ("ALLOWED_EXCEL",)

RBAC_MATRIX = {
    "admin_importar_requisicoes": ("requisicoes", "full"),
    "admin_requisicoes": ("requisicoes", "view"),
    "admin_nova_requisicao": ("requisicoes", "edit"),
    "admin_editar_requisicao": ("requisicoes", "edit"),
    "admin_excluir_requisicao": ("requisicoes", "full"),
    "admin_detalhes_requisicao": ("requisicoes", "view"),
    "admin_api_requisicao": ("requisicoes", "view"),
    "admin_api_aluno_requisicao_scope": ("requisicoes", "view"),
    "admin_processar_requisicao": ("requisicoes", "edit"),
}

RBAC_SCOPE_COUNTS = {"view": 4, "edit": 5, "full": 3}

CSRF_MUTATING_PAIRS = {
    "/admin/importar_requisicoes": "admin_importar_requisicoes",
    "/admin/requisicoes/<int:req_id>/editar": "admin_editar_requisicao",
    "/admin/requisicoes/<int:req_id>/excluir": "admin_excluir_requisicao",
    "/admin/requisicoes/nova": "admin_nova_requisicao",
    "/admin/processar_requisicao/<int:req_id>": "admin_processar_requisicao",
}

# PHASE 4-B5-R1: the 8 Matrizes POST handlers extracted to app.views.admin.matrizes.
# They appear as additional owner-only deltas in the regenerated CSRF snapshots.
MATRIZES_MUTATING_PAIRS = {
    "/admin/adicionar_matriz": "admin_adicionar_matriz",
    "/admin/editar_matriz/<int:matriz_id>": "admin_editar_matriz",
    "/admin/matrizes/excluir": "admin_excluir_matrizes",
    "/admin/matrizes/<int:matriz_id>/excluir": "admin_excluir_matriz",
    "/admin/matrizes/<int:matriz_id>/atividades/nova/<string:active_tab>": "admin_matriz_nova_atividade",
    "/admin/matrizes/<int:matriz_id>/atividades/<int:atividade_id>/nova-versao": "admin_matriz_nova_versao_card",
    "/admin/matrizes/<int:matriz_id>/versoes/definir": "admin_matriz_versoes_definir",
    "/admin/matrizes/<int:matriz_id>/versoes/remover": "admin_matriz_versoes_remover",
}

# PHASE 4-B6: the 11 Alunos/Turmas/Cursos POST handlers extracted to
# app.views.admin.alunos_turmas_cursos.  They appear as additional owner-only
# deltas in the regenerated CSRF snapshots.
B6_MUTATING_PAIRS = {
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

# B6 statuses include the two documented exception buckets used by the
# B6 cohort (admin_alterar_status_alunos is "not_applicable_documented").
B6_ALLOWED_CSRF_STATUSES = {
    "ok_rendered_form_token",
    "ok_dynamic_form_token",
    "ok_specific_regression_test",
    "ok_fetch_token",
    "ok_api_csrf_contract",
    "not_applicable_documented",
    "ok_logout_or_safe_exception",
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

# UT-11: the 3 Alertas POST handlers extracted to app.views.admin.alertas.
# They appear as additional owner-only deltas in the regenerated CSRF
# snapshots (main -> app.views.admin.alertas).
ALERTAS_MUTATING_PAIRS = {
    "/admin/alertas/salvar": "admin_salvar_alerta",
    "/admin/alertas/<int:alerta_id>/alternar": "admin_alternar_alerta",
    "/admin/alertas/<int:alerta_id>/deletar": "admin_deletar_alerta",
}

# UT-12: the 2 Reportes POST handlers extracted to app.views.admin.reportes.
# They appear as additional owner-only deltas in the regenerated CSRF
# snapshots (main -> app.views.admin.reportes).
REPORTES_MUTATING_PAIRS = {
    "/admin/reportes/<int:reporte_id>/status": "admin_reportes_atualizar_status",
    "/admin/reportes/<int:reporte_id>/deletar": "admin_reportes_deletar",
}

# UT-14: the Meus Dados POST handler extracted to app.views.admin.meus_dados.
# It appears as one additional owner-only delta in the regenerated CSRF
# snapshots (main -> app.views.admin.meus_dados).
MEUS_DADOS_MUTATING_PAIRS = {
    "/admin/meus_dados": "admin_meus_dados",
}

C1_COURSE_DETAIL_PAGE_PATH = "/admin/cursos/2"
C1_ARQUIVOS_PAGE_PATH = "/admin/arquivos?edit_arquivo=1"
C1_STATUS_COUNTS_OLD = {
    "ok_dynamic_form_token": 14,
    "ok_rendered_form_token": 54,
}
C1_STATUS_COUNTS_NEW = {
    "ok_dynamic_form_token": 13,
    "ok_rendered_form_token": 55,
}
C1_ARQUIVOS_EDIT_ROUTE = "/admin/arquivos/<int:arquivo_id>/editar"
C1_ARQUIVOS_DELETE_ROUTE = "/admin/arquivos/<int:arquivo_id>/deletar"
C1_ARQUIVOS_ADICIONAR_ROUTE = "/admin/arquivos/adicionar"
C1_ARQUIVOS_EDIT_EVIDENCE = [
    {
        "action": "/admin/arquivos/1/editar",
        "kind": "rendered_form",
        "page": "/admin/arquivos?edit_arquivo",
        "token_count": 1,
    },
    {
        "action": "/admin/arquivos/0/editar",
        "kind": "dynamic_form",
        "page": "/admin/arquivos?edit_arquivo",
        "token_mode": "helper_or_hidden",
    },
]
C1_ARQUIVOS_DELETE_EVIDENCE = [
    {
        "action": "/admin/arquivos/1/deletar",
        "attr": "data-delete-url",
        "kind": "dynamic_form",
        "page": "/admin/arquivos?edit_arquivo",
        "token_mode": "helper_or_hidden",
    },
    {
        "action": "/admin/arquivos/0/deletar",
        "kind": "dynamic_form",
        "page": "/admin/arquivos?edit_arquivo",
        "token_mode": "helper_or_hidden",
    },
]
C1_ARQUIVOS_EDIT_TOKEN_COUNTS = [
    {
        "action": "/admin/arquivos/1/editar",
        "page": "/admin/arquivos?edit_arquivo",
        "token_counts": [1],
    }
]
C1_ARQUIVOS_ROUTES = frozenset(
    {C1_ARQUIVOS_EDIT_ROUTE, C1_ARQUIVOS_DELETE_ROUTE}
)


def _assert_c1_status_change(old_entry, new_entry, path):
    assert old_entry.get("path") == new_entry.get("path") == path
    old_identity = {k: v for k, v in old_entry.items() if k != "status_code"}
    new_identity = {k: v for k, v in new_entry.items() if k != "status_code"}
    assert old_identity == new_identity
    assert old_entry.get("status_code") == 500
    assert new_entry.get("status_code") == 200


def _assert_c1_reconciled_summary(old_summary, new_summary):
    assert set(old_summary) == set(new_summary) == {
        "total_mutating_routes",
        "status_counts",
        "high_risk_routes",
        "page_statuses",
    }
    assert old_summary["total_mutating_routes"] == new_summary["total_mutating_routes"]
    assert old_summary["high_risk_routes"] == new_summary["high_risk_routes"]

    old_counts = old_summary["status_counts"]
    new_counts = new_summary["status_counts"]
    assert set(old_counts) == set(new_counts)
    for status, old_value in C1_STATUS_COUNTS_OLD.items():
        assert old_counts.get(status) == old_value
        assert new_counts.get(status) == C1_STATUS_COUNTS_NEW[status]
    for status in set(old_counts) - set(C1_STATUS_COUNTS_OLD):
        assert old_counts[status] == new_counts[status]

    old_pages = old_summary["page_statuses"]
    new_pages = new_summary["page_statuses"]
    assert len(old_pages) == len(new_pages)
    old_paths = [page.get("path") for page in old_pages]
    new_paths = [page.get("path") for page in new_pages]
    assert old_paths == new_paths
    page_deltas = [
        (old_page, new_page)
        for old_page, new_page in zip(old_pages, new_pages)
        if old_page != new_page
    ]
    expected_paths = {
        C1_COURSE_DETAIL_PAGE_PATH,
        C1_ARQUIVOS_PAGE_PATH,
    }
    assert sorted(page[0].get("path") for page in page_deltas) == sorted(
        expected_paths
    )
    for expected_path in expected_paths:
        matches = [
            pair for pair in page_deltas if pair[0].get("path") == expected_path
        ]
        assert len(matches) == 1
        _assert_c1_status_change(*matches[0], expected_path)


def _without_owner(row):
    return {key: value for key, value in row.items() if key != "view_function"}


def _assert_c1_archivos_rows(old_rows, new_rows):
    assert len(old_rows) == len(new_rows)
    old_routes = [row.get("route") for row in old_rows]
    new_routes = [row.get("route") for row in new_rows]
    assert old_routes == new_routes
    assert len(old_routes) == len(set(old_routes))
    old_by_route = {row["route"]: row for row in old_rows}
    new_by_route = {row["route"]: row for row in new_rows}
    assert C1_ARQUIVOS_ROUTES <= set(old_by_route) == set(new_by_route)

    old_delete = old_by_route[C1_ARQUIVOS_DELETE_ROUTE]
    new_delete = new_by_route[C1_ARQUIVOS_DELETE_ROUTE]
    assert len(old_delete["evidence"]) == 2
    assert len(new_delete["evidence"]) == 4
    assert new_delete["evidence"] == old_delete["evidence"] + C1_ARQUIVOS_DELETE_EVIDENCE
    for key in old_delete:
        if key not in {"view_function", "evidence"}:
            assert old_delete[key] == new_delete[key]

    old_edit = old_by_route[C1_ARQUIVOS_EDIT_ROUTE]
    new_edit = new_by_route[C1_ARQUIVOS_EDIT_ROUTE]
    assert old_edit["csrf_in_html"] is None
    assert new_edit["csrf_in_html"] is True
    assert len(old_edit["evidence"]) == 1
    assert len(new_edit["evidence"]) == 3
    assert new_edit["evidence"] == old_edit["evidence"] + C1_ARQUIVOS_EDIT_EVIDENCE
    assert old_edit["has_post_form"] is False
    assert new_edit["has_post_form"] is True
    assert old_edit["status"] == "ok_dynamic_form_token"
    assert new_edit["status"] == "ok_rendered_form_token"
    assert old_edit["token_counts_per_form"] == []
    assert new_edit["token_counts_per_form"] == C1_ARQUIVOS_EDIT_TOKEN_COUNTS
    for key in old_edit:
        if key not in {
            "view_function",
            "csrf_in_html",
            "evidence",
            "has_post_form",
            "status",
            "token_counts_per_form",
        }:
            assert old_edit[key] == new_edit[key]

    assert _without_owner(old_by_route[C1_ARQUIVOS_ADICIONAR_ROUTE]) == _without_owner(
        new_by_route[C1_ARQUIVOS_ADICIONAR_ROUTE]
    )

    normalized_rows = []
    for old_row, new_row in zip(old_rows, new_rows):
        normalized = dict(new_row)
        if old_row["route"] == C1_ARQUIVOS_DELETE_ROUTE:
            normalized["evidence"] = old_row["evidence"]
        elif old_row["route"] == C1_ARQUIVOS_EDIT_ROUTE:
            for key in (
                "csrf_in_html",
                "evidence",
                "has_post_form",
                "status",
                "token_counts_per_form",
            ):
                normalized[key] = old_row[key]
        assert _without_owner(old_row) == _without_owner(normalized)
        normalized_rows.append(normalized)
    return normalized_rows


def _assert_historical_partition_arithmetic(deltas_by_route, expected_total, expected_routes):
    assert len(deltas_by_route) == expected_total
    assert set(deltas_by_route) == set(expected_routes)


def _assert_c1_adversarial_controls(
    old_rows,
    new_rows,
    old_summary,
    new_summary,
    deltas_by_route,
    expected_total,
    expected_routes,
):
    for invalid_token_count in (0, 2):
        mutated_rows = deepcopy(new_rows)
        mutated_edit = next(
            row for row in mutated_rows if row["route"] == C1_ARQUIVOS_EDIT_ROUTE
        )
        rendered = next(
            evidence
            for evidence in mutated_edit["evidence"]
            if evidence.get("kind") == "rendered_form"
        )
        rendered["token_count"] = invalid_token_count
        with pytest.raises(AssertionError):
            _assert_c1_archivos_rows(old_rows, mutated_rows)

    mutated_rows = deepcopy(new_rows)
    unrelated = next(
        row for row in mutated_rows if row["route"] not in C1_ARQUIVOS_ROUTES
    )
    unrelated["evidence"] = list(unrelated["evidence"]) + [
        {"kind": "dynamic_form", "page": "/synthetic-unrelated"}
    ]
    with pytest.raises(AssertionError):
        _assert_c1_archivos_rows(old_rows, mutated_rows)

    mutated_rows = deepcopy(new_rows)
    adicionar = next(
        row for row in mutated_rows if row["route"] == C1_ARQUIVOS_ADICIONAR_ROUTE
    )
    adicionar["evidence"] = list(adicionar["evidence"]) + [
        {"kind": "dynamic_form", "page": "/admin/arquivos?edit_arquivo"}
    ]
    with pytest.raises(AssertionError):
        _assert_c1_archivos_rows(old_rows, mutated_rows)

    mutated_summary = deepcopy(new_summary)
    mutated_summary["status_counts"]["ok_fetch_token"] += 1
    with pytest.raises(AssertionError):
        _assert_c1_reconciled_summary(old_summary, mutated_summary)

    mutated_summary = deepcopy(new_summary)
    mutated_summary["high_risk_routes"] += 1
    with pytest.raises(AssertionError):
        _assert_c1_reconciled_summary(old_summary, mutated_summary)

    mutated_summary = deepcopy(new_summary)
    course_page = next(
        page
        for page in mutated_summary["page_statuses"]
        if page["path"] == C1_COURSE_DETAIL_PAGE_PATH
    )
    course_page["status_code"] = 500
    with pytest.raises(AssertionError):
        _assert_c1_reconciled_summary(old_summary, mutated_summary)

    mutated_summary = deepcopy(new_summary)
    course_page = next(
        page
        for page in mutated_summary["page_statuses"]
        if page["path"] == C1_COURSE_DETAIL_PAGE_PATH
    )
    course_page["path"] = "/admin/cursos/999"
    with pytest.raises(AssertionError):
        _assert_c1_reconciled_summary(old_summary, mutated_summary)

    mutated_partition = dict(deltas_by_route)
    mutated_partition.pop(next(iter(mutated_partition)))
    with pytest.raises(AssertionError):
        _assert_historical_partition_arithmetic(
            mutated_partition, expected_total, expected_routes
        )


def _canonical_module():
    from app.views.admin import requisicoes

    return requisicoes


def _factory(**kwargs):
    return create_app(
        register_presets_blueprint=False,
        register_aluno_blueprint=False,
        **kwargs,
    )


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


def _materialize_rule(rule: str, req_id: int = 1, aluno_id: int = 1) -> str:
    return rule.replace("<int:req_id>", str(req_id)).replace(
        "<int:aluno_id>", str(aluno_id)
    )


# =====================================================================
# Contrato estrutural exato
# =====================================================================


def test_b42_contract_is_exactly_nine_specs_and_twelve_rule_method_pairs():
    assert len(ROUTE_MATRIX) == 9
    assert len(ROUTE_NAMES) == len(set(ROUTE_NAMES)) == 9
    assert sum(len(methods) for _, _, methods in ROUTE_MATRIX) == 12
    pairs = {(rule, method) for rule, _, methods in ROUTE_MATRIX for method in methods}
    assert len(pairs) == 12
    assert all(method in BUSINESS_METHODS for _, _, methods in ROUTE_MATRIX for method in methods)
    assert all(rule.startswith("/admin/") for rule, _, _ in ROUTE_MATRIX)


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
import app.views.admin.requisicoes as module
assert "main" not in sys.modules
assert module.__name__ == "app.views.admin.requisicoes"
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


def test_exactly_nine_immutable_route_specs_match_legacy_matrix():
    module = _canonical_module()
    specs = module.LEGACY_ROUTE_SPECS

    assert isinstance(specs, tuple)
    assert len(specs) == 9
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
    assert "@bp" not in source
    assert {spec.view_func for spec in module.LEGACY_ROUTE_SPECS} == {
        getattr(module, name) for name in ROUTE_NAMES
    }


# =====================================================================
# Factory / registro
# =====================================================================


def test_factory_registers_legacy_routes_by_default_and_supports_opt_out():
    default_app = _factory()
    opt_out_app = _factory(register_admin_requisicoes_blueprint=False)

    assert _route_tuples(default_app) == set(ROUTE_MATRIX)
    assert _live_moved_rules(opt_out_app) == []


def test_two_independent_factory_apps_each_register_each_route_once():
    first = _factory()
    second = _factory()

    assert _route_tuples(first) == set(ROUTE_MATRIX)
    assert _route_tuples(second) == set(ROUTE_MATRIX)
    assert len(_live_moved_rules(first)) == len(_live_moved_rules(second)) == 9
    assert first is not second


def test_duplicate_blueprint_registration_fails_explicitly():
    module = _canonical_module()
    app = _factory()

    with pytest.raises(LegacyRouteRegistrationError, match="already registered"):
        register_legacy_blueprint(app, module.bp_admin_requisicoes)
    assert len(_live_moved_rules(app)) == 9


@pytest.mark.parametrize("collision_kind", ["endpoint", "rule_method"])
def test_route_collision_fails_before_any_legacy_route_mutation(collision_kind):
    module = _canonical_module()
    app = _factory(register_admin_requisicoes_blueprint=False)
    if collision_kind == "endpoint":
        app.add_url_rule(
            "/unrelated",
            endpoint="admin_importar_requisicoes",
            view_func=lambda: "x",
        )
    else:
        app.add_url_rule(
            "/admin/requisicoes",
            endpoint="phase4_b42_collision",
            view_func=lambda: "x",
            methods=["GET"],
        )

    with pytest.raises(LegacyRouteRegistrationError, match="collision"):
        register_legacy_blueprint(app, module.bp_admin_requisicoes)
    moved_rules = {rule for rule, _, _ in ROUTE_MATRIX}
    assert not any(rule.rule in moved_rules for rule in _live_moved_rules(app))


def test_no_namespaced_endpoint_alias_or_duplicate_rule_exists():
    app = _factory()
    moved = _live_moved_rules(app)

    assert len(moved) == 9
    assert not any(
        rule.endpoint.startswith("admin_requisicoes_blueprint.")
        for rule in app.url_map.iter_rules()
    )
    assert not any("." in rule.endpoint for rule in moved)
    assert len({rule.rule for rule in moved}) == 9
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
            values = {}
            if "<int:req_id>" in rule:
                values["req_id"] = 1
            if "<int:aluno_id>" in rule:
                values["aluno_id"] = 1
            assert url_for(endpoint, **values) == _materialize_rule(rule)

    for rule, endpoint, methods in ROUTE_MATRIX:
        path = _materialize_rule(rule)
        with app.test_request_context(path, method=methods[0]):
            assert request.endpoint == endpoint


# =====================================================================
# Exports de compatibilidade em main
# =====================================================================


def test_main_compatibility_exports_are_identity_imports_and_app_uses_canonical_views():
    import main

    module = _canonical_module()
    for name in ROUTE_NAMES + HELPER_NAMES:
        assert getattr(main, name) is getattr(module, name)
    assert main.ALLOWED_EXCEL is module.ALLOWED_EXCEL
    for name in ROUTE_NAMES:
        assert main.app.view_functions[name] is getattr(module, name)
        assert main.app.view_functions[name].__module__ == module.__name__


def test_main_no_longer_defines_moved_bodies_or_route_decorators():
    moved = set(ROUTE_NAMES) | set(HELPER_NAMES)
    assert not (moved & _top_level_functions(MAIN_PATH))
    assert not set(CONSTANT_NAMES) & _top_level_assignments(MAIN_PATH)
    assert set(ROUTE_NAMES) | set(HELPER_NAMES) <= _imports_from(
        MAIN_PATH, "app.views.admin.requisicoes"
    )
    assert set(CONSTANT_NAMES) <= _imports_from(MAIN_PATH, "app.views.admin.requisicoes")
    source = MAIN_PATH.read_text(encoding="utf-8")
    for rule, _, _ in ROUTE_MATRIX:
        assert f'app.route("{rule}"' not in source
        assert f"app.route('{rule}'" not in source


# =====================================================================
# RBAC
# =====================================================================


def test_rbac_requirements_remain_exact_for_twelve_pairs():
    for _, endpoint, methods in ROUTE_MATRIX:
        for method in methods:
            assert get_admin_permission_requirement(endpoint, method) == RBAC_MATRIX[endpoint]


def test_rbac_scope_counts_remain_exact_4_view_5_edit_3_full():
    from collections import Counter

    counts: Counter = Counter()
    for _, endpoint, methods in ROUTE_MATRIX:
        for method in methods:
            resource, scope = get_admin_permission_requirement(endpoint, method)
            assert resource == "requisicoes"
            counts[scope] += 1
    assert dict(counts) == RBAC_SCOPE_COUNTS


# =====================================================================
# CSRF dos 5 handlers mutantes + prova estática dos 5 deltas owner-only
# =====================================================================


def test_csrf_snapshots_prove_exactly_five_owner_only_deltas_when_regenerated():
    import subprocess

    for snapshot_path in (CSRF_OFF_PATH, CSRF_ON_PATH):
        assert snapshot_path.is_file(), f"missing CSRF snapshot: {snapshot_path}"
        relative = snapshot_path.relative_to(PROJECT_ROOT).as_posix()
        old_result = subprocess.run(
            ["git", "show", f"{B4_2_BASELINE_COMMIT}:{relative}"],
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
        assert [row["route"] for row in old_rows] == [row["route"] for row in new_rows]

        old_summary = old_snapshot["summary"]
        new_summary = new_snapshot["summary"]
        _assert_c1_reconciled_summary(old_summary, new_summary)

        reconciled_rows = _assert_c1_archivos_rows(old_rows, new_rows)
        deltas = [
            pair for pair in zip(old_rows, reconciled_rows) if pair[0] != pair[1]
        ]
        # PHASE 4-B5-R1: the same snapshot regenerated after the Matrizes
        # extraction gains exactly 8 additional owner-only deltas (main ->
        # app.views.admin.matrizes).  PHASE 4-B6: the Alunos/Turmas/Cursos
        # extraction adds exactly 11 owner-only deltas (main ->
        # app.views.admin.alunos_turmas_cursos).  UT-8: the Banco de Dados
        # extraction adds exactly 11 more owner-only deltas (main ->
        # app.views.admin.banco_dados).  UT-9: the Acesso extraction adds
        # exactly 5 more owner-only deltas (main -> app.views.admin.acesso).
        # UT-10: the Arquivos extraction adds exactly 3 more owner-only deltas
        # (main -> app.views.admin.arquivos).  UT-11: the Alertas extraction
        # adds exactly 3 more owner-only deltas (main ->
        # app.views.admin.alertas).  UT-12: the Reportes extraction adds
        # exactly 2 more owner-only deltas (main ->
        # app.views.admin.reportes).  UT-14: the Meus Dados extraction adds
        # exactly 1 more owner-only delta (main ->
        # app.views.admin.meus_dados).
        # The historical 5 requisicoes deltas remain owner-only and unchanged.
        # 49 = 5 requisicoes + 8 Matrizes + 11 B6 + 11 UT-8 + 5 UT-9 + 3 UT-10
        # + 3 UT-11 + 2 UT-12 + 1 UT-14, exhaustively partitioned with no
        # uncategorized delta.
        deltas_by_route = {
            new_row["route"]: (old_row, new_row) for old_row, new_row in deltas
        }
        requisicoes_routes = set(CSRF_MUTATING_PAIRS)
        matrizes_routes = set(MATRIZES_MUTATING_PAIRS)
        b6_routes = set(B6_MUTATING_PAIRS)
        banco_dados_routes = set(BANCO_DADOS_MUTATING_PAIRS)
        acesso_routes = set(ACESSO_MUTATING_PAIRS)
        arquivos_routes = set(ARQUIVOS_MUTATING_PAIRS)
        alertas_routes = set(ALERTAS_MUTATING_PAIRS)
        reportes_routes = set(REPORTES_MUTATING_PAIRS)
        meus_dados_routes = set(MEUS_DADOS_MUTATING_PAIRS)
        assert len(requisicoes_routes) == 5
        assert len(matrizes_routes) == 8
        assert len(b6_routes) == 11
        assert len(banco_dados_routes) == 11
        assert len(acesso_routes) == 5
        assert len(arquivos_routes) == 3
        assert len(alertas_routes) == 3
        assert len(reportes_routes) == 2
        assert len(meus_dados_routes) == 1
        assert not (requisicoes_routes & matrizes_routes)
        assert not (requisicoes_routes & b6_routes)
        assert not (requisicoes_routes & banco_dados_routes)
        assert not (requisicoes_routes & acesso_routes)
        assert not (requisicoes_routes & arquivos_routes)
        assert not (requisicoes_routes & alertas_routes)
        assert not (requisicoes_routes & reportes_routes)
        assert not (requisicoes_routes & meus_dados_routes)
        assert not (matrizes_routes & b6_routes)
        assert not (matrizes_routes & banco_dados_routes)
        assert not (matrizes_routes & acesso_routes)
        assert not (matrizes_routes & arquivos_routes)
        assert not (matrizes_routes & alertas_routes)
        assert not (matrizes_routes & reportes_routes)
        assert not (matrizes_routes & meus_dados_routes)
        assert not (b6_routes & banco_dados_routes)
        assert not (b6_routes & acesso_routes)
        assert not (b6_routes & arquivos_routes)
        assert not (b6_routes & alertas_routes)
        assert not (b6_routes & reportes_routes)
        assert not (b6_routes & meus_dados_routes)
        assert not (banco_dados_routes & acesso_routes)
        assert not (banco_dados_routes & arquivos_routes)
        assert not (banco_dados_routes & alertas_routes)
        assert not (banco_dados_routes & reportes_routes)
        assert not (banco_dados_routes & meus_dados_routes)
        assert not (acesso_routes & arquivos_routes)
        assert not (acesso_routes & alertas_routes)
        assert not (acesso_routes & reportes_routes)
        assert not (acesso_routes & meus_dados_routes)
        assert not (arquivos_routes & alertas_routes)
        assert not (arquivos_routes & reportes_routes)
        assert not (arquivos_routes & meus_dados_routes)
        assert not (alertas_routes & reportes_routes)
        assert not (alertas_routes & meus_dados_routes)
        assert not (reportes_routes & meus_dados_routes)
        historical_routes = (
            requisicoes_routes | matrizes_routes | b6_routes | banco_dados_routes
            | acesso_routes | arquivos_routes | alertas_routes | reportes_routes
            | meus_dados_routes
        )
        _assert_historical_partition_arithmetic(deltas_by_route, 49, historical_routes)
        _assert_c1_adversarial_controls(
            old_rows,
            new_rows,
            old_summary,
            new_summary,
            deltas_by_route,
            49,
            historical_routes,
        )

        requisicoes_deltas = [
            pair
            for route, pair in deltas_by_route.items()
            if route in requisicoes_routes
        ]
        matrizes_deltas = [
            pair for route, pair in deltas_by_route.items() if route in matrizes_routes
        ]
        b6_deltas = [pair for route, pair in deltas_by_route.items() if route in b6_routes]
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
        alertas_deltas = [
            pair
            for route, pair in deltas_by_route.items()
            if route in alertas_routes
        ]
        reportes_deltas = [
            pair
            for route, pair in deltas_by_route.items()
            if route in reportes_routes
        ]
        meus_dados_deltas = [
            pair
            for route, pair in deltas_by_route.items()
            if route in meus_dados_routes
        ]
        assert len(requisicoes_deltas) == 5
        assert len(matrizes_deltas) == 8
        assert len(b6_deltas) == 11
        assert len(banco_dados_deltas) == 11
        assert len(acesso_deltas) == 5
        assert len(arquivos_deltas) == 3
        assert len(alertas_deltas) == 3
        assert len(reportes_deltas) == 2
        assert len(meus_dados_deltas) == 1

        for old_row, new_row in requisicoes_deltas:
            expected_func = CSRF_MUTATING_PAIRS[new_row["route"]]
            assert old_row["view_function"] == f"main.{expected_func}"
            assert (
                new_row["view_function"]
                == f"app.views.admin.requisicoes.{expected_func}"
            )
            assert new_row["method"] == "POST"
            assert new_row["status"] in {
                "ok_rendered_form_token",
                "ok_dynamic_form_token",
                "ok_specific_regression_test",
                "ok_fetch_token",
                "ok_api_csrf_contract",
            }
            old_other = {k: v for k, v in old_row.items() if k != "view_function"}
            new_other = {k: v for k, v in new_row.items() if k != "view_function"}
            assert old_other == new_other

        for old_row, new_row in matrizes_deltas:
            expected_func = MATRIZES_MUTATING_PAIRS[new_row["route"]]
            assert old_row["view_function"] == f"main.{expected_func}"
            assert (
                new_row["view_function"]
                == f"app.views.admin.matrizes.{expected_func}"
            )
            assert new_row["method"] == "POST"
            assert new_row["status"] in {
                "ok_rendered_form_token",
                "ok_dynamic_form_token",
                "ok_specific_regression_test",
                "ok_fetch_token",
                "ok_api_csrf_contract",
            }
            old_other = {k: v for k, v in old_row.items() if k != "view_function"}
            new_other = {k: v for k, v in new_row.items() if k != "view_function"}
            assert old_other == new_other

        for old_row, new_row in b6_deltas:
            expected_func = B6_MUTATING_PAIRS[new_row["route"]]
            assert old_row["view_function"] == f"main.{expected_func}"
            assert (
                new_row["view_function"]
                == f"app.views.admin.alunos_turmas_cursos.{expected_func}"
            )
            assert new_row["method"] == "POST"
            assert new_row["status"] in B6_ALLOWED_CSRF_STATUSES
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
            assert new_row["status"] in {
                "ok_rendered_form_token",
                "ok_dynamic_form_token",
                "ok_specific_regression_test",
                "ok_fetch_token",
                "ok_api_csrf_contract",
            }
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
            assert new_row["status"] in {
                "ok_rendered_form_token",
                "ok_dynamic_form_token",
                "ok_specific_regression_test",
                "ok_fetch_token",
                "ok_api_csrf_contract",
            }
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
            assert new_row["status"] in {
                "ok_rendered_form_token",
                "ok_dynamic_form_token",
                "ok_specific_regression_test",
                "ok_fetch_token",
                "ok_api_csrf_contract",
            }
            old_other = {k: v for k, v in old_row.items() if k != "view_function"}
            new_other = {k: v for k, v in new_row.items() if k != "view_function"}
            assert old_other == new_other

        for old_row, new_row in alertas_deltas:
            expected_func = ALERTAS_MUTATING_PAIRS[new_row["route"]]
            assert old_row["view_function"] == f"main.{expected_func}"
            assert (
                new_row["view_function"]
                == f"app.views.admin.alertas.{expected_func}"
            )
            assert new_row["method"] == "POST"
            assert new_row["status"] in {
                "ok_rendered_form_token",
                "ok_dynamic_form_token",
                "ok_specific_regression_test",
                "ok_fetch_token",
                "ok_api_csrf_contract",
            }
            old_other = {k: v for k, v in old_row.items() if k != "view_function"}
            new_other = {k: v for k, v in new_row.items() if k != "view_function"}
            assert old_other == new_other

        for old_row, new_row in reportes_deltas:
            expected_func = REPORTES_MUTATING_PAIRS[new_row["route"]]
            assert old_row["view_function"] == f"main.{expected_func}"
            assert (
                new_row["view_function"]
                == f"app.views.admin.reportes.{expected_func}"
            )
            assert new_row["method"] == "POST"
            assert new_row["status"] in {
                "ok_rendered_form_token",
                "ok_dynamic_form_token",
                "ok_specific_regression_test",
                "ok_fetch_token",
                "ok_api_csrf_contract",
            }
            old_other = {k: v for k, v in old_row.items() if k != "view_function"}
            new_other = {k: v for k, v in new_row.items() if k != "view_function"}
            assert old_other == new_other

        for old_row, new_row in meus_dados_deltas:
            expected_func = MEUS_DADOS_MUTATING_PAIRS[new_row["route"]]
            assert old_row["view_function"] == f"main.{expected_func}"
            assert (
                new_row["view_function"]
                == f"app.views.admin.meus_dados.{expected_func}"
            )
            assert new_row["method"] == "POST"
            assert new_row["status"] in {
                "ok_rendered_form_token",
                "ok_dynamic_form_token",
                "ok_specific_regression_test",
                "ok_fetch_token",
                "ok_api_csrf_contract",
            }
            old_other = {k: v for k, v in old_row.items() if k != "view_function"}
            new_other = {k: v for k, v in new_row.items() if k != "view_function"}
            assert old_other == new_other


# =====================================================================
# Route inventory / catálogo / owners / fronteiras
# =====================================================================


def test_route_inventory_baseline_is_byte_identical_and_keeps_131_130_counts():
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


def test_admin_package_has_no_main_import_or_dynamic_equivalent():
    sources = list(ADMIN_PACKAGE.glob("*.py"))
    assert sources

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


def test_b1_b2_b3_b41_shared_owners_remain_intact():
    import main
    from app import matrix_scope, requisitions, settings, uploads, activity_catalog
    from app.views.admin import atividades, configuracoes

    settings_helpers = (
        "_normalize_optional_iso_date",
        "get_app_settings",
        "get_response_time_settings",
        "save_app_settings",
        "reset_response_time_metrics",
        "save_return_response_settings",
        "get_horas_settings",
        "save_horas_settings",
    )
    matrix_helpers = (
        "MATRIZ_STATUS_META",
        "_matriz_option_label",
        "_matriz_status_label",
        "get_allowed_activity_ids_for_turma_matrix",
        "get_effective_matriz_for_turma",
        "is_activity_allowed_for_turma_matrix",
    )
    catalog_helpers = (
        "get_atividade_base",
        "get_atividade_base_list",
        "get_atividade_versao_by_id",
        "get_next_numero_versao",
        "parse_documentos_json",
    )
    upload_helpers = ("_allowed", "_unique_filename", "save_upload")

    for name in settings_helpers:
        assert getattr(main, name) is getattr(settings, name)
        assert getattr(configuracoes, name) is getattr(settings, name)
    for name in matrix_helpers:
        assert getattr(main, name) is getattr(matrix_scope, name)
    assert main.auto_indefer_devolvidas is requisitions.auto_indefer_devolvidas
    for name in catalog_helpers:
        assert getattr(main, name) is getattr(activity_catalog, name)
        assert getattr(atividades, name) is getattr(activity_catalog, name)
    for name in upload_helpers:
        assert getattr(main, name) is getattr(uploads, name)
    for name in ("admin_atividades", "admin_editar_atividade", "admin_catalogo_versoes"):
        assert getattr(main, name) is getattr(atividades, name)


def test_no_matriz_aluno_route_was_moved_and_dashboard_ownership_state_aware():
    import importlib
    import main

    # PHASE 4-B5-R1: the Matrizes handlers moved to app.views.admin.matrizes;
    # the remaining legacy endpoints stay in main.
    for endpoint in ("admin_matrizes", "admin_matriz_versoes"):
        assert endpoint in main.app.view_functions
        assert main.app.view_functions[endpoint].__module__ == "app.views.admin.matrizes"

    # UT-13 seam: only the Dashboard clause is state-aware; the neighbor
    # admin_meus_dados stays main-owned in both states.
    dashboard_path = PROJECT_ROOT / "app" / "views" / "admin" / "dashboard.py"
    if dashboard_path.exists():
        dashboard = importlib.import_module("app.views.admin.dashboard")
        assert main.app.view_functions["admin_dashboard"].__module__ == (
            "app.views.admin.dashboard"
        )
        assert main.app.view_functions["admin_dashboard"] is dashboard.admin_dashboard, (
            "live admin_dashboard must identity-match the dashboard target"
        )
    else:
        assert main.app.view_functions["admin_dashboard"].__module__ == "main"
    # UT-14 seam: meus_dados ownership is state-aware on the real target
    # availability (absent -> main; present -> app.views.admin.meus_dados).
    meus_dados_path = PROJECT_ROOT / "app" / "views" / "admin" / "meus_dados.py"
    expected_meus_dados_owner = (
        "app.views.admin.meus_dados" if meus_dados_path.exists() else "main"
    )
    assert (
        main.app.view_functions["admin_meus_dados"].__module__
        == expected_meus_dados_owner
    )

    for endpoint in (
        "aluno.aluno_dashboard",
        "aluno.aluno_minhas_requisicoes",
        "aluno.aluno_nova_requisicao",
        "aluno.aluno_requisicao_detalhe",
    ):
        assert endpoint in main.app.view_functions
        assert main.app.view_functions[endpoint].__module__ == "app.views.aluno"
