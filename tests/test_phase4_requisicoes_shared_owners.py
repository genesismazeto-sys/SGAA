from __future__ import annotations

import ast
import inspect
import os
from pathlib import Path
import sqlite3
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAIN_PATH = PROJECT_ROOT / "main.py"
ALUNO_PATH = PROJECT_ROOT / "app" / "views" / "aluno.py"
SETTINGS_PATH = PROJECT_ROOT / "app" / "settings.py"
REQUISITIONS_PATH = PROJECT_ROOT / "app" / "requisitions.py"
MATRIX_SCOPE_PATH = PROJECT_ROOT / "app" / "matrix_scope.py"
CONFIGURACOES_PATH = PROJECT_ROOT / "app" / "views" / "admin" / "configuracoes.py"
REQUISICOES_VIEW_PATH = PROJECT_ROOT / "app" / "views" / "admin" / "requisicoes.py"
CONTRACT_PATH = PROJECT_ROOT / "docs" / "refactor" / "PHASE4_REQUISICOES_SHARED_OWNER_CONTRACT.md"

SETTINGS_HELPERS = {
    "_normalize_optional_iso_date",
    "get_app_settings",
    "get_response_time_settings",
    "save_app_settings",
    "reset_response_time_metrics",
    "save_return_response_settings",
    "get_horas_settings",
    "save_horas_settings",
}
MATRIX_SCOPE_HELPERS = {
    "_matriz_option_label",
    "_matriz_status_label",
    "get_effective_matriz_for_turma",
    "get_allowed_activity_version_ids_for_turma_matrix",
    "is_activity_version_allowed_for_turma_matrix",
}
REQUISITION_HELPERS = {"auto_indefer_devolvidas"}
REQUISICOES_ROUTE_NAMES = {
    "admin_importar_requisicoes",
    "admin_requisicoes",
    "admin_nova_requisicao",
    "admin_editar_requisicao",
    "admin_excluir_requisicao",
    "admin_detalhes_requisicao",
    "admin_api_requisicao",
    "admin_api_aluno_requisicao_scope",
    "admin_processar_requisicao",
}
SETTINGS_MESSAGE_KEYS = {
    "msg_3cfd9280a4d6da6f",
    "msg_4613bb9b498e92ef",
    "msg_6206a00ba4a5f008",
    "msg_88ab2789659bfd66",
    "msg_ab39ea13f2a09d09",
    "msg_df3076ae3d104b97",
}


def _top_level_functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _imports_from(path: Path, module_name: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    return {
        alias.asname or alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == module_name
        for alias in node.names
    }


def test_b41_neutral_modules_import_without_importing_main():
    code = (
        "import importlib, sys; "
        "assert 'main' not in sys.modules; "
        "[importlib.import_module(name) for name in "
        "('app.settings', 'app.requisitions', 'app.matrix_scope')]; "
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


def test_b41_has_single_neutral_defining_owners_and_identity_compatibility_exports():
    import main
    from app import matrix_scope, requisitions, settings
    from app.views.admin import configuracoes

    assert SETTINGS_HELPERS <= _top_level_functions(SETTINGS_PATH)
    assert MATRIX_SCOPE_HELPERS <= _top_level_functions(MATRIX_SCOPE_PATH)
    assert REQUISITION_HELPERS <= _top_level_functions(REQUISITIONS_PATH)

    assert not (SETTINGS_HELPERS | MATRIX_SCOPE_HELPERS | REQUISITION_HELPERS) & _top_level_functions(MAIN_PATH)
    assert not SETTINGS_HELPERS & _top_level_functions(CONFIGURACOES_PATH)

    for name in SETTINGS_HELPERS:
        assert getattr(main, name) is getattr(settings, name)
        assert getattr(configuracoes, name) is getattr(settings, name)
    for name in MATRIX_SCOPE_HELPERS:
        assert getattr(main, name) is getattr(matrix_scope, name)
    for name in REQUISITION_HELPERS:
        assert getattr(main, name) is getattr(requisitions, name)


def test_b41_main_and_configuracoes_import_from_neutral_owners():
    assert SETTINGS_HELPERS <= _imports_from(MAIN_PATH, "app.settings")
    assert SETTINGS_HELPERS <= _imports_from(CONFIGURACOES_PATH, "app.settings")
    assert MATRIX_SCOPE_HELPERS <= _imports_from(MAIN_PATH, "app.matrix_scope")
    assert REQUISITION_HELPERS <= _imports_from(MAIN_PATH, "app.requisitions")

    for path in (SETTINGS_PATH, REQUISITIONS_PATH, MATRIX_SCOPE_PATH):
        source = path.read_text(encoding="utf-8")
        assert "import main" not in source
        assert "app.views" not in source


def test_b41_aluno_consumes_matrix_scope_directly_and_drops_only_that_lazy_edge():
    source = ALUNO_PATH.read_text(encoding="utf-8")
    assert "get_effective_matriz_for_turma" in _imports_from(ALUNO_PATH, "app.matrix_scope")
    tree = ast.parse(source, filename=str(ALUNO_PATH))
    helper = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_get_main_helpers"
    )
    mapping = next(node.value for node in ast.walk(helper) if isinstance(node, ast.Return))
    assert isinstance(mapping, ast.Dict)
    lazy_keys = {key.value for key in mapping.keys if isinstance(key, ast.Constant)}
    assert lazy_keys == {
        "get_student_request_update_alert",
        "mark_student_request_updates_seen",
    }


def test_b42_requisicoes_routes_moved_to_canonical_view_and_reexported_identically():
    import main
    from app.views.admin import requisicoes

    assert REQUISICOES_VIEW_PATH.exists()
    assert not REQUISICOES_ROUTE_NAMES & _top_level_functions(MAIN_PATH)
    for name in REQUISICOES_ROUTE_NAMES:
        assert getattr(main, name) is getattr(requisicoes, name)
        view_func = main.app.view_functions[name]
        assert view_func is getattr(requisicoes, name)
        assert view_func.__module__ == "app.views.admin.requisicoes"


def test_auto_indefer_preserves_helper_owned_commit_boundary():
    from app.prod1_schema import bootstrap_prod1_schema
    from app.requisitions import auto_indefer_devolvidas
    from app.settings import save_return_response_settings
    from tests.versioned_test_support import seed_reference_versioned_dataset

    class TrackingConnection(sqlite3.Connection):
        commit_count = 0

        def commit(self):
            self.commit_count += 1
            return super().commit()

    conn = sqlite3.connect(":memory:", factory=TrackingConnection)
    conn.row_factory = sqlite3.Row
    try:
        bootstrap_prod1_schema(conn)
        seed_reference_versioned_dataset(conn)
        save_return_response_settings(
            conn,
            {"return_response_days": "7", "auto_indefer_devolvida": "1"},
        )
        conn.execute(
            """
            INSERT INTO requisicoes (
                id, aluno_id, atividade_versao_id, data_solicitacao, data_evento,
                horas_solicitadas, nome_evento, status, observacao,
                data_processamento, regra_snapshot_json
            ) VALUES (
                1, NULL, 29, date('now', '-8 days'), date('now', '-8 days'),
                1, 'Auto indefer prod-1', 'Devolvida', '', datetime('now', '-8 days'),
                '{}'
            )
            """
        )
        conn.commit()
        conn.commit_count = 0

        assert auto_indefer_devolvidas(conn) == 1
        assert conn.commit_count == 1
        row = conn.execute("SELECT status, observacao FROM requisicoes WHERE id = 1").fetchone()
        assert row["status"] == "Indeferida"
        assert "7 dias expirado" in row["observacao"]

        assert auto_indefer_devolvidas(conn) == 0
        assert conn.commit_count == 1
    finally:
        conn.close()


def test_settings_messages_remain_in_catalog_under_neutral_owner():
    from utils import messages

    messages._message_catalog.cache_clear()
    catalog = messages._message_catalog()
    assert len(catalog) == 545
    for key in SETTINGS_MESSAGE_KEYS:
        usages = catalog[key]["usages"]
        assert usages
        assert all(usage["source_path"] == "app/settings.py" for usage in usages)


def test_neutral_write_helpers_remain_caller_owned_except_legacy_auto_indefer_commit():
    from app import requisitions, settings

    for name in SETTINGS_HELPERS - {"_normalize_optional_iso_date", "get_app_settings", "get_response_time_settings", "get_horas_settings"}:
        source = inspect.getsource(getattr(settings, name)).upper()
        assert ".COMMIT(" not in source
        assert ".ROLLBACK(" not in source
    auto_source = inspect.getsource(requisitions.auto_indefer_devolvidas).upper()
    assert auto_source.count(".COMMIT(") == 1
    assert ".ROLLBACK(" not in auto_source
