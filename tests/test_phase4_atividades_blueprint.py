"""Canonical activity blueprint ownership after prod-1 elimination."""
import main
from app.views.admin import atividades as views


def test_activity_blueprint_owns_exact_canonical_surface():
    rules = [rule for rule in main.app.url_map.iter_rules() if rule.endpoint in {spec.endpoint for spec in views.LEGACY_ROUTE_SPECS}]
    assert len(views.LEGACY_ROUTE_SPECS) == 21
    assert len(rules) == 21
    assert not any("mapeamento-legado" in rule.rule for rule in rules)


def test_activity_catalog_has_no_removed_mapping_helper():
    import app.activity_catalog as catalog

    assert not hasattr(catalog, "get_legacy_map_list")
    assert not hasattr(main, "get_legacy_map_list")


def test_activity_routes_are_registered_once():
    endpoints = [spec.endpoint for spec in views.LEGACY_ROUTE_SPECS]
    assert len(endpoints) == len(set(endpoints))
    assert all(endpoint in main.app.view_functions for endpoint in endpoints)
