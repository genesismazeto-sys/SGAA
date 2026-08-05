from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAIN_PATH = PROJECT_ROOT / "main.py"
ALUNO_PATH = PROJECT_ROOT / "app" / "views" / "aluno.py"
DB_MAINTENANCE_PATH = PROJECT_ROOT / "app" / "db_maintenance.py"
ADMIN_FILES_PATH = PROJECT_ROOT / "app" / "admin_files.py"
ADMIN_ALERTS_PATH = PROJECT_ROOT / "app" / "admin_alerts.py"

ENTRY_BASELINE_SHA = "b6d6e2295e2beeba046cfe1f4c1614f667261ad2"

B7P_SHARED_SYMBOLS = {
    "ensure_admin_arquivos_table",
    "ensure_admin_alertas_table",
    "get_admin_arquivo",
    "list_active_admin_alertas",
}

DB_MAINTENANCE_OWNED = {"ensure_admin_arquivos_table", "ensure_admin_alertas_table"}
ADMIN_FILES_OWNED = {"get_admin_arquivo"}
ADMIN_ALERTS_OWNED = {"list_active_admin_alertas"}

ARQUIVOS_ALERTAS_REPORTES_ROUTE_NAMES = {
    "admin_arquivos",
    "admin_adicionar_arquivo",
    "admin_editar_arquivo",
    "admin_visualizar_arquivo",
    "admin_deletar_arquivo",
    "admin_reportes",
    "admin_reportes_atualizar_status",
    "admin_reportes_deletar",
    "admin_alertas",
    "admin_salvar_alerta",
    "admin_alternar_alerta",
    "admin_deletar_alerta",
}

EXPECTED_ALUNO_LAZY_KEYS_POST_B7P = {
    "get_student_request_update_alert",
    "mark_student_request_updates_seen",
}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _baseline_text(rel_path: str) -> str:
    result = subprocess.run(
        ["git", "show", f"{ENTRY_BASELINE_SHA}:{rel_path}"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def _top_level_functions(path: Path) -> set[str]:
    tree = ast.parse(_read_text(path), filename=str(path))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _imports_from(path: Path, module_name: str) -> set[str]:
    tree = ast.parse(_read_text(path), filename=str(path))
    return {
        alias.asname or alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == module_name
        for alias in node.names
    }


def _find_function(source: str, name: str) -> ast.FunctionDef:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"function {name!r} not found")


def _dump_body(func: ast.FunctionDef) -> str:
    return "\n".join(ast.dump(stmt, annotate_fields=True) for stmt in func.body)


def _lazy_return_keys(function) -> set[str]:
    import inspect

    tree = ast.parse(inspect.getsource(function))
    returns = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)
    ]
    assert len(returns) == 1
    return {
        key.value
        for key in returns[0].value.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }


def test_b7p_canonical_owner_modules_exist_and_own_exact_symbols():
    assert DB_MAINTENANCE_PATH.exists()
    assert ADMIN_FILES_PATH.exists(), "app/admin_files.py must exist after B7-P"
    assert ADMIN_ALERTS_PATH.exists(), "app/admin_alerts.py must exist after B7-P"

    db_maintenance_functions = _top_level_functions(DB_MAINTENANCE_PATH)
    admin_files_functions = _top_level_functions(ADMIN_FILES_PATH)
    admin_alerts_functions = _top_level_functions(ADMIN_ALERTS_PATH)

    assert DB_MAINTENANCE_OWNED <= db_maintenance_functions
    assert admin_files_functions == ADMIN_FILES_OWNED
    assert admin_alerts_functions == ADMIN_ALERTS_OWNED


def test_b7p_main_has_zero_local_bodies_for_the_four_symbols():
    main_functions = _top_level_functions(MAIN_PATH)
    assert not (B7P_SHARED_SYMBOLS & main_functions)


def test_b7p_main_identity_reexports_canonical_owners():
    import main
    from app import admin_alerts, admin_files, db_maintenance

    assert main.ensure_admin_arquivos_table is db_maintenance.ensure_admin_arquivos_table
    assert main.ensure_admin_alertas_table is db_maintenance.ensure_admin_alertas_table
    assert main.get_admin_arquivo is admin_files.get_admin_arquivo
    assert main.list_active_admin_alertas is admin_alerts.list_active_admin_alertas


def test_b7p_neutral_owners_import_without_importing_main():
    code = (
        "import importlib, sys; "
        "assert 'main' not in sys.modules; "
        "[importlib.import_module(name) for name in "
        "('app.db_maintenance', 'app.admin_files', 'app.admin_alerts')]; "
        "assert 'main' not in sys.modules"
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", code],
        cwd=PROJECT_ROOT,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    for path in (DB_MAINTENANCE_PATH, ADMIN_FILES_PATH, ADMIN_ALERTS_PATH):
        source = _read_text(path)
        assert "import main" not in source


def test_b7p_body_equivalence_against_entry_baseline():
    baseline_main = _baseline_text("main.py")

    baseline_ensure_arquivos = _find_function(baseline_main, "ensure_admin_arquivos_table")
    baseline_get_arquivo = _find_function(baseline_main, "get_admin_arquivo")
    baseline_ensure_alertas = _find_function(baseline_main, "ensure_admin_alertas_table")
    baseline_list_alertas = _find_function(baseline_main, "list_active_admin_alertas")

    current_ensure_arquivos = _find_function(_read_text(DB_MAINTENANCE_PATH), "ensure_admin_arquivos_table")
    current_ensure_alertas = _find_function(_read_text(DB_MAINTENANCE_PATH), "ensure_admin_alertas_table")
    current_get_arquivo = _find_function(_read_text(ADMIN_FILES_PATH), "get_admin_arquivo")
    current_list_alertas = _find_function(_read_text(ADMIN_ALERTS_PATH), "list_active_admin_alertas")

    assert _dump_body(baseline_ensure_arquivos) == _dump_body(current_ensure_arquivos)
    assert _dump_body(baseline_ensure_alertas) == _dump_body(current_ensure_alertas)
    assert _dump_body(baseline_get_arquivo) == _dump_body(current_get_arquivo)
    assert _dump_body(baseline_list_alertas) == _dump_body(current_list_alertas)

    assert ast.dump(baseline_ensure_arquivos.args) == ast.dump(current_ensure_arquivos.args)
    assert ast.dump(baseline_ensure_alertas.args) == ast.dump(current_ensure_alertas.args)
    assert ast.dump(baseline_get_arquivo.args) == ast.dump(current_get_arquivo.args)
    assert ast.dump(baseline_list_alertas.args) == ast.dump(current_list_alertas.args)


def test_b7p_aluno_consumes_three_b7_symbols_directly():
    assert "ensure_admin_arquivos_table" in _imports_from(ALUNO_PATH, "app.db_maintenance")
    assert "get_admin_arquivo" in _imports_from(ALUNO_PATH, "app.admin_files")
    assert "list_active_admin_alertas" in _imports_from(ALUNO_PATH, "app.admin_alerts")


def test_b7p_aluno_lazy_map_reduced_to_exactly_two_requisicoes_keys():
    from app.views import aluno as aluno_views

    lazy_keys = _lazy_return_keys(aluno_views._get_main_helpers)
    assert lazy_keys == EXPECTED_ALUNO_LAZY_KEYS_POST_B7P


def test_b7p_zero_route_movement_all_twelve_handlers_remain_main_local():
    main_functions = _top_level_functions(MAIN_PATH)
    assert ARQUIVOS_ALERTAS_REPORTES_ROUTE_NAMES <= main_functions


def test_b7p_uploaded_file_unchanged_from_entry_baseline():
    baseline_main = _baseline_text("main.py")
    baseline_uploaded_file = _find_function(baseline_main, "uploaded_file")
    current_uploaded_file = _find_function(_read_text(MAIN_PATH), "uploaded_file")
    assert _dump_body(baseline_uploaded_file) == _dump_body(current_uploaded_file)
    assert ast.dump(baseline_uploaded_file.args) == ast.dump(current_uploaded_file.args)


def test_b7p_admin_dashboard_unchanged_from_entry_baseline():
    baseline_main = _baseline_text("main.py")
    baseline_dashboard = _find_function(baseline_main, "admin_dashboard")
    current_dashboard = _find_function(_read_text(MAIN_PATH), "admin_dashboard")
    assert _dump_body(baseline_dashboard) == _dump_body(current_dashboard)
    assert ast.dump(baseline_dashboard.args) == ast.dump(current_dashboard.args)


def test_b7p_reportes_ownership_unchanged():
    db_maintenance_functions = _top_level_functions(DB_MAINTENANCE_PATH)
    assert "ensure_reportes_table" in db_maintenance_functions

    import main
    from app import db_maintenance, reporting

    assert main.ensure_reportes_table is db_maintenance.ensure_reportes_table
    assert main.REPORTE_CATEGORY_OPTIONS is reporting.REPORTE_CATEGORY_OPTIONS
