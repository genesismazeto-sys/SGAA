import main
from tests.canonical_matrix_test_support import login_admin
from tests.versioned_test_support import isolated_versioned_app_env


def test_activity_catalog_version_links_use_exact_base_and_version_ids(tmp_path):
    with isolated_versioned_app_env(tmp_path, "activity-menu.db") as env:
        login_admin(env["client"])
        response = env["client"].get("/admin/atividades")
        html = response.get_data(as_text=True)
        assert response.status_code == 200
        assert "atividade" in html.lower()
        assert 'data-action="nova-versao"' in html
        assert 'data-action="ver-versoes"' in html
        assert "/admin/catalogo-versoes/0/nova-versao" in html
        assert "/admin/catalogo-versoes/0" in html
        assert 'href="/admin/adicionar_atividade"' in html
        with main.app.app_context():
            assert main.get_db_connection().execute("SELECT COUNT(*) FROM atividade_versao").fetchone()[0] > 0
