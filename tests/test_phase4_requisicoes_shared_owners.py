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
    "get_allowed_activity_ids_for_turma_matrix",
    "is_activity_allowed_for_turma_matrix",
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
        "ensure_admin_arquivos_table",
        "get_admin_arquivo",
        "get_student_request_update_alert",
        "list_active_admin_alertas",
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
    from app.requisitions import auto_indefer_devolvidas
    from app.settings import save_return_response_settings

    class TrackingConnection(sqlite3.Connection):
        commit_count = 0

        def commit(self):
            self.commit_count += 1
            return super().commit()

    conn = sqlite3.connect(":memory:", factory=TrackingConnection)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            """
            CREATE TABLE requisicoes (
                id INTEGER PRIMARY KEY,
                status TEXT,
                observacao TEXT,
                data_processamento TEXT
            )
            """
        )
        save_return_response_settings(
            conn,
            {"return_response_days": "7", "auto_indefer_devolvida": "1"},
        )
        conn.execute(
            "INSERT INTO requisicoes VALUES (1, 'Devolvida', '', datetime('now', '-8 days'))"
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
    assert len(catalog) == 536
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


def test_b41_governance_records_exact_scope_and_preserves_later_prohibitions():
    documents = {
        "handoff": (PROJECT_ROOT / "AGENT_HANDOFF.md").read_text(encoding="utf-8"),
        "state": (PROJECT_ROOT / "PROJECT_STATE.md").read_text(encoding="utf-8"),
        "index": (PROJECT_ROOT / "docs" / "DOCUMENTATION_INDEX.md").read_text(encoding="utf-8"),
        "plan": (PROJECT_ROOT / "docs" / "mapeamento" / "05_avaliacao_refactor.md").read_text(encoding="utf-8"),
        "ledger": (PROJECT_ROOT / "docs" / "refactor" / "ARCHITECTURE_REFACTOR_LEDGER.md").read_text(encoding="utf-8"),
        "contract": CONTRACT_PATH.read_text(encoding="utf-8"),
    }
    for name, text in documents.items():
        assert "PHASE 4-B4.1" in text or "PHASE4-B4.1" in text, name

    current = "\n".join(
        (
            documents["handoff"].split("## Historical state", 1)[0],
            documents["state"].split("## Historical authoritative state", 1)[0],
        )
    ).upper()
    assert "PHASE 4-B4.2: CLOSED / ACCEPTED" in current
    assert "PHASE 4-B5-P: IMPLEMENTED / AWAITING SUPERVISOR REVIEW" in current
    assert "PHASE 4: OPEN / INCREMENTAL IMPLEMENTATION" in current
    assert "PHASE 5" in current and "NOT AUTHORIZED" in current
    assert "PHASE 6" in current and "NOT AUTHORIZED" in current
    assert "MIGRATION V4" in current and "PROHIBITED" in current
    assert "- [x] `app/views/admin/requisicoes.py`" in documents["plan"]
    for path in ("app/settings.py", "app/requisitions.py", "app/matrix_scope.py"):
        assert path in documents["contract"]

    accepted_b41_commit = "c587098152e97d125f41a2d26f2f414c10ae5676"
    accepted_paths = {
        "handoff": PROJECT_ROOT / "AGENT_HANDOFF.md",
        "state": PROJECT_ROOT / "PROJECT_STATE.md",
        "index": PROJECT_ROOT / "docs" / "DOCUMENTATION_INDEX.md",
        "plan": PROJECT_ROOT / "docs" / "mapeamento" / "05_avaliacao_refactor.md",
        "ledger": PROJECT_ROOT / "docs" / "refactor" / "ARCHITECTURE_REFACTOR_LEDGER.md",
        "contract": CONTRACT_PATH,
    }
    accepted_documents = {}
    for name, path in accepted_paths.items():
        relative = path.relative_to(PROJECT_ROOT).as_posix()
        result = subprocess.run(
            ["git", "show", f"{accepted_b41_commit}:{relative}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=PROJECT_ROOT,
        )
        assert result.returncode == 0, result.stderr
        accepted_documents[name] = result.stdout

    accepted_b41_slices = {
        "handoff": accepted_documents["handoff"].split("## Historical state", 1)[0],
        "state": accepted_documents["state"].split("## Historical authoritative state", 1)[0],
        "index": accepted_documents["index"].split("- **PHASE 4-B4.1:**", 1)[1].split("- Accepted technical commits:", 1)[0],
        "plan": accepted_documents["plan"].split("- [x] PHASE 4-B4.1", 1)[1].split("### Fase 5", 1)[0],
        "ledger": next(
            line
            for line in accepted_documents["ledger"].splitlines()
            if line.startswith("| PHASE4-B4.1 |")
        ),
        "contract": accepted_documents["contract"],
    }
    accepted_b41 = "\n".join(accepted_b41_slices.values())
    upper = accepted_b41.upper()

    assert "PHASE 4-B4-A: CLOSED / ACCEPTED" in upper
    assert "PHASE 4-B4.1: CLOSED / ACCEPTED" in upper or "PHASE4-B4.1 |" in upper
    assert "73EBF0DC34681E74E778759AF476E1CD2F981444" in upper
    assert "PUBLICATION: COMPLETE" in upper
    assert "POST-PUBLICATION VERIFICATION: COMPLETE" in upper
    assert "PHASE 4: OPEN / INCREMENTAL IMPLEMENTATION" in upper
    assert "PHASE 4-B4.2: NOT AUTHORIZED" in upper
    assert "PHASE 5: NOT AUTHORIZED" in upper
    assert "PHASE 6: NOT AUTHORIZED" in upper
    assert "MIGRATION V4: PROHIBITED" in upper
    assert "- [ ] `APP/VIEWS/ADMIN/REQUISICOES.PY`" in upper
    assert "EXACT 9 REQUISICOES ROUTES REMAIN IN MAIN.PY" in upper
    assert "B2 ESTABLISHED SIX" in upper
    for key in (
        "ensure_admin_arquivos_table",
        "get_admin_arquivo",
        "get_student_request_update_alert",
        "list_active_admin_alertas",
        "mark_student_request_updates_seen",
    ):
        assert key in accepted_b41

    forbidden_current_tokens = (
        "awaiting supervisor review",
        "review pending",
        "staging pending",
        "commit pending",
        "push pending",
        "publication pending",
    )
    lowered = accepted_b41.lower()
    for token in forbidden_current_tokens:
        assert token not in lowered
