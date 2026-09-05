from __future__ import annotations

from pathlib import Path

import pytest

import main
from tests.canonical_matrix_test_support import login_admin
from tests.versioned_test_support import isolated_versioned_app_env


@pytest.fixture()
def retirement_env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "version-catalog-retirement.db") as env:
        login_admin(env["client"])
        yield env


def _first_version_ids() -> tuple[int, int]:
    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT atividade_base_id, id FROM atividade_versao ORDER BY id LIMIT 1"
        ).fetchone()
    assert row is not None
    return int(row["atividade_base_id"]), int(row["id"])


def test_standalone_index_route_endpoint_and_template_are_retired(retirement_env):
    response = retirement_env["client"].get("/admin/catalogo-versoes")

    assert response.status_code == 404
    assert "admin_catalogo_versoes" not in main.app.view_functions
    assert not any(rule.rule == "/admin/catalogo-versoes" for rule in main.app.url_map.iter_rules())
    assert not (Path(main.app.root_path).parent / "templates" / "admin_catalogo_versoes.html").exists()


def test_activity_list_keeps_exact_version_management_navigation(retirement_env):
    response = retirement_env["client"].get("/admin/atividades")
    rendered = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'href="/admin/adicionar_atividade"' in rendered
    assert 'data-action="view"' in rendered
    assert 'data-action="edit"' in rendered
    assert 'data-action="nova-versao"' in rendered
    assert 'data-action="ver-versoes"' in rendered
    assert "/admin/catalogo-versoes/0/nova-versao" in rendered
    assert "/admin/catalogo-versoes/0" in rendered


def test_version_detail_and_exact_source_form_remain_reachable(retirement_env):
    base_id, version_id = _first_version_ids()
    detail = retirement_env["client"].get(f"/admin/catalogo-versoes/{base_id}")
    create = retirement_env["client"].get(
        f"/admin/catalogo-versoes/{base_id}/nova-versao?from={version_id}"
    )

    assert detail.status_code == 200
    rendered_detail = detail.get_data(as_text=True)
    assert 'href="/admin/atividades"' in rendered_detail
    assert '<span class="btn-label">Atividades</span>' in rendered_detail
    assert "Catálogo de versões" not in rendered_detail
    assert create.status_code == 200
    assert f'<option value="{version_id}" selected>' in create.get_data(as_text=True)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/admin/catalogo-versoes/999999"),
        ("GET", "/admin/catalogo-versoes/999999/nova-versao"),
        ("GET", "/admin/catalogo-versoes/999999/versoes/999999/editar"),
        ("POST", "/admin/catalogo-versoes/999999/versoes/999999/ativar"),
        ("POST", "/admin/catalogo-versoes/999999/versoes/999999/inativar"),
        ("POST", "/admin/catalogo-versoes/999999/versoes/999999/descontinuar"),
        ("POST", "/admin/catalogo-versoes/999999/versoes/999999/substituir"),
    ],
)
def test_missing_base_fallbacks_return_to_canonical_activity_list(
    retirement_env, method, path
):
    response = retirement_env["client"].open(path, method=method)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/admin/atividades")
