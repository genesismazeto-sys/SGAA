"""The standalone Matrix-version surface is physically retired."""
from __future__ import annotations

from pathlib import Path

import main
from tests.canonical_matrix_test_support import login_admin
from tests.versioned_test_support import isolated_versioned_app_env


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RETIRED_ENDPOINTS = {
    "admin_matriz_versoes",
    "admin_matriz_versoes_definir",
    "admin_matriz_versoes_remover",
}
RETIRED_RULES = {
    "/admin/matrizes/<int:matriz_id>/versoes",
    "/admin/matrizes/<int:matriz_id>/versoes/definir",
    "/admin/matrizes/<int:matriz_id>/versoes/remover",
}


def test_retired_matrix_version_urls_return_404(tmp_path):
    with isolated_versioned_app_env(tmp_path, "retired-matrix-versions.db") as env:
        login_admin(env["client"])
        assert env["client"].get("/admin/matrizes/1/versoes").status_code == 404
        assert env["client"].post("/admin/matrizes/1/versoes/definir").status_code == 404
        assert env["client"].post("/admin/matrizes/1/versoes/remover").status_code == 404


def test_retired_routes_are_absent_from_the_application():
    endpoints = {rule.endpoint for rule in main.app.url_map.iter_rules()}
    rules = {rule.rule for rule in main.app.url_map.iter_rules()}
    assert RETIRED_ENDPOINTS.isdisjoint(endpoints)
    assert RETIRED_RULES.isdisjoint(rules)


def test_standalone_template_and_navigation_are_absent():
    assert not (PROJECT_ROOT / "templates" / "admin_matriz_versoes.html").exists()
    form = (PROJECT_ROOT / "templates" / "admin_matriz_form.html").read_text(
        encoding="utf-8"
    )
    assert "admin_matriz_versoes" not in form
    assert ">Versões<" not in form


def test_no_live_production_reference_to_retired_surface_survives():
    paths = [PROJECT_ROOT / "main.py"]
    for root in (PROJECT_ROOT / "app", PROJECT_ROOT / "templates", PROJECT_ROOT / "static"):
        paths.extend(path for path in root.rglob("*") if path.suffix in {".py", ".html", ".js", ".css"})

    retired_markers = RETIRED_ENDPOINTS | RETIRED_RULES
    hits = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for marker in retired_markers:
            if marker in text:
                hits.append(f"{path.relative_to(PROJECT_ROOT)}: {marker}")
    assert hits == []


def test_matrix_composition_has_no_activity_creation_affordance(tmp_path):
    with isolated_versioned_app_env(tmp_path, "no-inline-activity-creator.db") as env:
        login_admin(env["client"])
        for tab in ("aac", "aea"):
            response = env["client"].get(f"/admin/editar_matriz/1?tab={tab}")
            assert response.status_code == 200
            html = response.get_data(as_text=True)
            assert "+ Nova atividade" not in html
            assert "matriz-new-activity-modal" not in html
            assert "matriz-new-activity-form" not in html
            assert "data-open-new-activity-modal" not in html

        assert env["client"].post(
            "/admin/matrizes/1/atividades/nova/aac"
        ).status_code == 404
        assert env["client"].post(
            "/admin/matrizes/1/atividades/nova/aea"
        ).status_code == 404
