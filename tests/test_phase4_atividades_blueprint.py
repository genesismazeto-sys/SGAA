"""Canonical activity blueprint ownership after prod-1 elimination."""
import main
from app.views.admin import atividades as views


#: The activity surface by endpoint: the catalogue, its import and groups, the versioned
#: catalogue, and the four DOCX fill-in template routes of each version (schema v19).
CANONICAL_ACTIVITY_ENDPOINTS = frozenset({
    "admin_atividades", "admin_atividades_academicas", "admin_atividades_extensao",
    "admin_adicionar_atividade", "admin_editar_atividade", "admin_deletar_atividade",
    "admin_atividades_importar_preview", "admin_atividades_importar_confirmar",
    "admin_grupos_renomear", "admin_grupos_excluir",
    "admin_catalogo_versao_detalhe", "admin_catalogo_nova_base", "admin_catalogo_nova_versao",
    "admin_catalogo_editar_versao", "admin_catalogo_visualizar_versao", "admin_catalogo_ativar_versao",
    "admin_catalogo_inativar_versao", "admin_catalogo_descontinuar_versao", "admin_catalogo_excluir_versao",
    "admin_catalogo_substituir_versao",
    "admin_catalogo_adicionar_modelo", "admin_catalogo_atualizar_modelo", "admin_catalogo_retirar_modelo",
    "admin_catalogo_baixar_modelo",
})


def test_activity_blueprint_owns_exact_canonical_surface():
    endpoints = [spec.endpoint for spec in views.LEGACY_ROUTE_SPECS]
    rules = [rule for rule in main.app.url_map.iter_rules() if rule.endpoint in set(endpoints)]
    assert set(endpoints) == CANONICAL_ACTIVITY_ENDPOINTS
    assert len(endpoints) == len(CANONICAL_ACTIVITY_ENDPOINTS)
    assert sorted(rule.endpoint for rule in rules) == sorted(CANONICAL_ACTIVITY_ENDPOINTS)
    assert not any("mapeamento-legado" in rule.rule for rule in rules)


def test_activity_catalog_has_no_removed_mapping_helper():
    import app.activity_catalog as catalog

    assert not hasattr(catalog, "get_legacy_map_list")
    assert not hasattr(main, "get_legacy_map_list")


def test_activity_routes_are_registered_once():
    endpoints = [spec.endpoint for spec in views.LEGACY_ROUTE_SPECS]
    assert len(endpoints) == len(set(endpoints))
    assert all(endpoint in main.app.view_functions for endpoint in endpoints)
