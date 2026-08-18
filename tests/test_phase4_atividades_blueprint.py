from __future__ import annotations

import ast
import importlib
import inspect
import io
import os
from pathlib import Path
import subprocess
import sys

import pytest

from flask import Flask
from werkzeug.datastructures import FileStorage

from app import create_app
from app.auth import get_admin_permission_requirement
from app.views.admin import LegacyRouteRegistrationError


ROOT = Path(__file__).resolve().parents[1]
MAIN_PATH = ROOT / "main.py"
APP_PATH = ROOT / "app" / "__init__.py"
VIEW_PATH = ROOT / "app" / "views" / "admin" / "atividades.py"
CATALOG_PATH = ROOT / "app" / "activity_catalog.py"
UPLOADS_PATH = ROOT / "app" / "uploads.py"
CONTRACT_PATH = ROOT / "docs" / "refactor" / "PHASE4_ATIVIDADES_BLUEPRINT_CONTRACT.md"
HANDOFF_PATH = ROOT / "AGENT_HANDOFF.md"
STATE_PATH = ROOT / "PROJECT_STATE.md"
INDEX_PATH = ROOT / "docs" / "DOCUMENTATION_INDEX.md"
PLAN_PATH = ROOT / "docs" / "mapeamento" / "05_avaliacao_refactor.md"
LEDGER_PATH = ROOT / "docs" / "refactor" / "ARCHITECTURE_REFACTOR_LEDGER.md"

ROUTE_MATRIX = (
    ("/admin/atividades", "admin_atividades", ("GET",)),
    ("/admin/atividades/academicas", "admin_atividades_academicas", ("GET",)),
    ("/admin/atividades/extensao", "admin_atividades_extensao", ("GET",)),
    ("/admin/adicionar_atividade", "admin_adicionar_atividade", ("GET", "POST")),
    ("/admin/editar_atividade/<int:atividade_id>", "admin_editar_atividade", ("GET", "POST")),
    ("/admin/deletar_atividade/<int:atividade_id>", "admin_deletar_atividade", ("POST",)),
    ("/admin/atividades/importar/preview", "admin_atividades_importar_preview", ("GET", "POST")),
    ("/admin/atividades/importar/confirmar", "admin_atividades_importar_confirmar", ("POST",)),
    ("/admin/grupos/renomear", "admin_grupos_renomear", ("POST",)),
    ("/admin/grupos/excluir", "admin_grupos_excluir", ("POST",)),
    ("/admin/catalogo-versoes", "admin_catalogo_versoes", ("GET",)),
    ("/admin/catalogo-versoes/<int:base_id>", "admin_catalogo_versao_detalhe", ("GET",)),
    ("/admin/normas-atividade", "admin_normas_atividade", ("GET",)),
    ("/admin/mapeamento-legado", "admin_mapeamento_legado", ("GET",)),
    ("/admin/catalogo-versoes/nova-base", "admin_catalogo_nova_base", ("GET", "POST")),
    ("/admin/normas-atividade/nova", "admin_norma_nova", ("GET", "POST")),
    ("/admin/catalogo-versoes/<int:base_id>/nova-versao", "admin_catalogo_nova_versao", ("GET", "POST")),
    (
        "/admin/catalogo-versoes/<int:base_id>/versoes/<int:versao_id>/editar",
        "admin_catalogo_editar_versao",
        ("GET", "POST"),
    ),
    (
        "/admin/catalogo-versoes/<int:base_id>/versoes/<int:versao_id>/ativar",
        "admin_catalogo_ativar_versao",
        ("POST",),
    ),
    (
        "/admin/catalogo-versoes/<int:base_id>/versoes/<int:versao_id>/inativar",
        "admin_catalogo_inativar_versao",
        ("POST",),
    ),
    (
        "/admin/catalogo-versoes/<int:base_id>/versoes/<int:versao_id>/descontinuar",
        "admin_catalogo_descontinuar_versao",
        ("POST",),
    ),
    (
        "/admin/catalogo-versoes/<int:base_id>/versoes/<int:versao_id>/substituir",
        "admin_catalogo_substituir_versao",
        ("POST",),
    ),
)
ROUTE_NAMES = tuple(endpoint for _, endpoint, _ in ROUTE_MATRIX)

CATALOG_HELPERS = (
    "parse_documentos_json",
    "_normalize_atividade_grupo",
    "get_atividade_base_list",
    "get_atividade_base",
    "get_versoes_por_base",
    "get_norma_list",
    "get_norma_by_id",
    "get_versoes_da_base_por_eixo",
    "get_next_numero_versao",
    "get_atividade_versao_by_id",
    "get_atividade_versao_usage_counts",
    "get_atividade_transicoes_por_base",
    "get_legacy_map_list",
)
VIEW_HELPERS = (
    "_normalize_import_header_name",
    "_canonicalize_tipo_atividade",
    "_canonicalize_tipo_limitacao",
    "_parse_csv_boolean",
    "_parse_optional_positive_int",
    "_build_grupo_label",
    "_format_preview_limitacao",
    "_ensure_grupos_def_table",
    "_upsert_grupo_definition",
    "_atividades_import_preview_dir",
    "_atividades_import_preview_path",
    "_store_atividades_import_preview",
    "_load_atividades_import_preview",
    "_delete_atividades_import_preview",
    "_delete_upload_relpath",
    "_build_atividades_import_preview",
)
UPLOAD_HELPERS = ("_allowed", "_unique_filename", "save_upload")

EXPECTED_PERMISSIONS = {
    "admin_atividades": ("atividades", "view"),
    "admin_atividades_academicas": ("atividades", "view"),
    "admin_atividades_extensao": ("atividades", "view"),
    "admin_adicionar_atividade": ("atividades", "edit"),
    "admin_editar_atividade": ("atividades", "edit"),
    "admin_deletar_atividade": ("atividades", "full"),
    "admin_atividades_importar_preview": ("atividades", "full"),
    "admin_atividades_importar_confirmar": ("atividades", "full"),
    "admin_grupos_renomear": ("atividades", "full"),
    "admin_grupos_excluir": ("atividades", "full"),
    "admin_catalogo_versoes": ("atividades", "view"),
    "admin_catalogo_versao_detalhe": ("atividades", "view"),
    "admin_normas_atividade": ("atividades", "view"),
    "admin_mapeamento_legado": ("atividades", "view"),
    "admin_catalogo_nova_base": ("atividades", "edit"),
    "admin_norma_nova": ("atividades", "edit"),
    "admin_catalogo_nova_versao": ("atividades", "edit"),
    "admin_catalogo_editar_versao": ("atividades", "edit"),
    "admin_catalogo_ativar_versao": ("atividades", "edit"),
    "admin_catalogo_inativar_versao": ("atividades", "edit"),
    "admin_catalogo_descontinuar_versao": ("atividades", "edit"),
    "admin_catalogo_substituir_versao": ("atividades", "edit"),
}

EXCLUDED_ENDPOINTS = {
    "admin_matrizes",
    "admin_requisicoes",
    "admin_alunos",
    "admin_turmas",
    "admin_cursos",
    "admin_arquivos",
    "admin_alertas",
    "admin_reportes",
    "admin_banco_dados",
    "admin_acesso",
    "admin_meus_dados",
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


def _live_rules(app):
    result = []
    for rule in app.url_map.iter_rules():
        if rule.endpoint not in ROUTE_NAMES:
            continue
        methods = tuple(method for method in ("GET", "POST", "PUT", "PATCH", "DELETE") if method in rule.methods)
        result.append((rule.rule, rule.endpoint, methods))
    return tuple(result)


def test_b3_contract_declares_exact_22_endpoints_and_29_governed_combinations():
    assert len(ROUTE_MATRIX) == 22
    assert len(ROUTE_NAMES) == len(set(ROUTE_NAMES)) == 22
    assert sum(len(methods) for _, _, methods in ROUTE_MATRIX) == 29
    assert not (set(ROUTE_NAMES) & EXCLUDED_ENDPOINTS)


def test_b3_artifacts_exist_and_contract_records_scope():
    for path in (VIEW_PATH, CATALOG_PATH, CONTRACT_PATH):
        assert path.is_file(), f"missing B3 artifact: {path.relative_to(ROOT)}"
    contract = CONTRACT_PATH.read_text(encoding="utf-8")
    for token in ("22 endpoints", "29 governed route/method combinations", "activity_catalog", "Matrizes", "Requisições"):
        assert token in contract


def test_blueprint_specs_are_exact_and_have_no_twenty_third_endpoint():
    views = importlib.import_module("app.views.admin.atividades")
    assert views.bp_admin_atividades.name == "admin_atividades_blueprint"
    assert tuple((spec.rule, spec.endpoint, spec.methods) for spec in views.LEGACY_ROUTE_SPECS) == ROUTE_MATRIX
    assert len(views.LEGACY_ROUTE_SPECS) == 22
    assert {spec.view_func for spec in views.LEGACY_ROUTE_SPECS} == {
        getattr(views, name) for name in ROUTE_NAMES
    }


def test_blueprint_uses_global_legacy_endpoints_and_preserves_factory_registration():
    app = create_app(
        register_presets_blueprint=False,
        register_aluno_blueprint=False,
        register_admin_configuracoes_blueprint=False,
        register_admin_versioning_blueprint=False,
    )
    assert _live_rules(app) == ROUTE_MATRIX
    assert all("." not in endpoint for endpoint in ROUTE_NAMES)
    disabled = create_app(
        register_presets_blueprint=False,
        register_aluno_blueprint=False,
        register_admin_configuracoes_blueprint=False,
        register_admin_versioning_blueprint=False,
        register_admin_atividades_blueprint=False,
    )
    assert not _live_rules(disabled)


def test_route_owners_preserve_only_admin_required_decorator():
    functions = {
        node.name: node
        for node in _tree(VIEW_PATH).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert set(ROUTE_NAMES) <= set(functions)
    for name in ROUTE_NAMES:
        assert {ast.unparse(item) for item in functions[name].decorator_list} == {"admin_required"}
    assert "@bp_admin_atividades.route" not in VIEW_PATH.read_text(encoding="utf-8")


def test_main_preserves_route_and_helper_compatibility_exports_by_identity():
    main = importlib.import_module("main")
    views = importlib.import_module("app.views.admin.atividades")
    catalog = importlib.import_module("app.activity_catalog")
    uploads = importlib.import_module("app.uploads")
    for name in ROUTE_NAMES + VIEW_HELPERS:
        assert getattr(main, name) is getattr(views, name)
    assert main.ATIVIDADES_IMPORT_REQUIRED_HEADERS is views.ATIVIDADES_IMPORT_REQUIRED_HEADERS
    for name in CATALOG_HELPERS:
        assert getattr(main, name) is getattr(catalog, name)
    for name in UPLOAD_HELPERS:
        assert getattr(main, name) is getattr(uploads, name)
    assert main.ALLOWED_CSV is uploads.ALLOWED_CSV
    for name in ROUTE_NAMES:
        assert main.app.view_functions[name] is getattr(views, name)
        assert main.app.view_functions[name].__module__ == views.__name__


def test_main_has_no_moved_bodies_or_route_decorators():
    moved = set(ROUTE_NAMES) | set(VIEW_HELPERS) | set(CATALOG_HELPERS) | set(UPLOAD_HELPERS)
    assert not (moved & _top_level_functions(MAIN_PATH))
    assert "ATIVIDADES_IMPORT_REQUIRED_HEADERS" not in _top_level_assignments(MAIN_PATH)
    assert set(ROUTE_NAMES) | set(VIEW_HELPERS) <= _imports_from(MAIN_PATH, "app.views.admin.atividades")
    assert set(CATALOG_HELPERS) <= _imports_from(MAIN_PATH, "app.activity_catalog")
    assert set(UPLOAD_HELPERS) | {"ALLOWED_CSV"} <= _imports_from(MAIN_PATH, "app.uploads")
    source = MAIN_PATH.read_text(encoding="utf-8")
    for rule, _, _ in ROUTE_MATRIX:
        assert f'app.route("{rule}"' not in source
        assert f"app.route('{rule}'" not in source


def test_shared_activity_catalog_is_independent_of_view_and_main_owners():
    source = CATALOG_PATH.read_text(encoding="utf-8")
    assert set(CATALOG_HELPERS) <= _top_level_functions(CATALOG_PATH)
    assert "import main" not in source
    assert "app.views" not in source
    views_source = VIEW_PATH.read_text(encoding="utf-8")
    assert "import main" not in views_source
    assert not (set(CATALOG_HELPERS) & _top_level_functions(VIEW_PATH))
    assert set(CATALOG_HELPERS) & _imports_from(VIEW_PATH, "app.activity_catalog")


def test_shared_catalog_preserves_future_main_consumers_without_view_dependency():
    source = MAIN_PATH.read_text(encoding="utf-8")
    assert "from app.views.admin.atividades import" in source
    assert "from app.activity_catalog import" in source
    for name in ("get_atividade_base", "get_atividade_versao_by_id", "get_next_numero_versao", "_normalize_atividade_grupo", "parse_documentos_json"):
        assert name in _imports_from(MAIN_PATH, "app.activity_catalog")
    main_functions = _top_level_functions(MAIN_PATH)
    assert "admin_matriz_versoes" in _imports_from(MAIN_PATH, "app.views.admin.matrizes")
    assert "admin_matriz_versoes" not in main_functions
    assert "admin_requisicoes" not in main_functions
    assert "admin_requisicoes" in _imports_from(
        MAIN_PATH, "app.views.admin.requisicoes"
    )


def test_upload_filesystem_helper_has_neutral_shared_owner():
    uploads_source = UPLOADS_PATH.read_text(encoding="utf-8")
    assert set(UPLOAD_HELPERS) <= _top_level_functions(UPLOADS_PATH)
    assert "current_app" in uploads_source
    assert "import main" not in uploads_source


def test_save_upload_uses_current_app_root_sanitizes_filename_and_contains_path(tmp_path):
    uploads = importlib.import_module("app.uploads")
    upload_root = tmp_path / "configured-upload-root"
    app = Flask("b3-upload-owner")
    app.config["UPLOAD_FOLDER"] = str(upload_root)
    storage = FileStorage(
        stream=io.BytesIO(b"csv payload"),
        filename="../../Atividades Teste.CSV",
    )

    with app.app_context():
        rel_path = uploads.save_upload(
            storage,
            uploads.ALLOWED_CSV,
            prefix="../../preview",
            subdir="atividades_imports",
        )

    destination = (upload_root / rel_path).resolve()
    assert destination.is_file()
    assert destination.read_bytes() == b"csv payload"
    assert upload_root.resolve() in destination.parents
    assert ".." not in rel_path
    assert " " not in destination.name
    assert destination.suffix == ".CSV"


def test_save_upload_rejects_escape_before_filesystem_mutation(tmp_path):
    uploads = importlib.import_module("app.uploads")
    upload_root = tmp_path / "upload-root"
    app = Flask("b3-upload-containment")
    app.config["UPLOAD_FOLDER"] = str(upload_root)
    storage = FileStorage(stream=io.BytesIO(b"payload"), filename="valid.csv")

    with app.app_context(), pytest.raises(ValueError, match="Caminho de upload inválido"):
        uploads.save_upload(
            storage,
            uploads.ALLOWED_CSV,
            subdir="../outside-upload-root",
        )

    assert not upload_root.exists()
    assert not (tmp_path / "outside-upload-root").exists()


def test_save_upload_keeps_extension_error_default_and_message_catalog_owner(tmp_path):
    uploads = importlib.import_module("app.uploads")
    messages = importlib.import_module("utils.messages")
    app = Flask("b3-upload-extension")
    app.config["UPLOAD_FOLDER"] = str(tmp_path / "uploads")
    storage = FileStorage(stream=io.BytesIO(b"payload"), filename="invalid.exe")

    with app.app_context(), pytest.raises(
        ValueError,
        match="^Extensão de arquivo não permitida\\.$",
    ):
        uploads.save_upload(storage, uploads.ALLOWED_CSV)

    messages._message_catalog.cache_clear()
    catalog = messages._message_catalog()
    key = messages.message_key_for_default("Extensão de arquivo não permitida.")
    assert catalog[key]["default_text"] == "Extensão de arquivo não permitida."
    assert any(
        usage["source_path"] == "app/uploads.py"
        and usage["source_function"] == "save_upload"
        for usage in catalog[key]["usages"]
    )
    assert not (tmp_path / "uploads").exists()


def test_upload_owner_import_has_no_filesystem_mutation(tmp_path):
    before = tuple(tmp_path.rglob("*"))
    result = subprocess.run(
        [sys.executable, "-B", "-c", "import app.uploads"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": os.pathsep.join(
                (str(ROOT), os.environ.get("PYTHONPATH", ""))
            ),
        },
    )
    assert result.returncode == 0, result.stderr
    assert tuple(tmp_path.rglob("*")) == before


def test_csv_import_preview_preserves_error_and_orphan_cleanup(monkeypatch):
    views = importlib.import_module("app.views.admin.atividades")
    app = Flask("b3-csv-cleanup")
    app.secret_key = "test-only"
    app.config["UPLOAD_FOLDER"] = "unused"
    rendered = object()
    flashes = []

    monkeypatch.setattr(views, "render_template", lambda *args, **kwargs: rendered)
    monkeypatch.setattr(views, "flash", lambda message, category: flashes.append((message, category)))
    monkeypatch.setattr(views, "save_upload", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("invalid")))
    monkeypatch.setattr(views, "_build_atividades_import_preview", lambda *args: pytest.fail("preview must not run"))
    handler = inspect.unwrap(views.admin_atividades_importar_preview)
    with app.test_request_context(
        "/admin/atividades/importar/preview",
        method="POST",
        data={"csv_arquivo": (io.BytesIO(b"invalid"), "invalid.txt")},
    ):
        assert handler() is rendered
    assert flashes == [("Envie um arquivo CSV válido.", "error")]

    deleted = []
    monkeypatch.setattr(views, "save_upload", lambda *args, **kwargs: "atividades_imports/preview.csv")
    monkeypatch.setattr(views, "_build_atividades_import_preview", lambda *args: ({"ok": False}, None))
    monkeypatch.setattr(views, "_delete_upload_relpath", deleted.append)
    with app.test_request_context(
        "/admin/atividades/importar/preview",
        method="POST",
        data={"csv_arquivo": (io.BytesIO(b"invalid headers"), "invalid.csv")},
    ):
        assert handler() is rendered
    assert deleted == ["atividades_imports/preview.csv"]


def test_rbac_contract_is_unchanged_for_all_29_combinations():
    for _, endpoint, methods in ROUTE_MATRIX:
        for method in methods:
            assert get_admin_permission_requirement(endpoint, method) == EXPECTED_PERMISSIONS[endpoint]


def test_factory_registration_remains_fail_closed_on_endpoint_collision():
    views = importlib.import_module("app.views.admin.atividades")
    app = create_app(
        register_presets_blueprint=False,
        register_aluno_blueprint=False,
        register_admin_configuracoes_blueprint=False,
        register_admin_versioning_blueprint=False,
        register_admin_atividades_blueprint=False,
    )
    app.add_url_rule("/unrelated", endpoint=ROUTE_NAMES[0], view_func=lambda: "collision")
    with pytest.raises(LegacyRouteRegistrationError, match="endpoint collision"):
        app.register_blueprint(views.bp_admin_atividades)


def test_new_b3_modules_import_without_importing_main():
    module_names = ("app.activity_catalog", "app.views.admin.atividades")
    code = (
        "import importlib, sys; "
        "assert 'main' not in sys.modules; "
        f"[importlib.import_module(name) for name in {module_names!r}]; "
        "assert 'main' not in sys.modules"
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", code],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 0, result.stderr


def test_factory_signature_exposes_explicit_b3_registration_switch():
    signature = inspect.signature(create_app)
    parameter = signature.parameters["register_admin_atividades_blueprint"]
    assert parameter.default is True
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
