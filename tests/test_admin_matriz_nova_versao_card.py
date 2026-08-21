from __future__ import annotations

import main
from tests.canonical_matrix_test_support import current_version_id, login_admin, seed_matrix_graph
from tests.versioned_test_support import isolated_versioned_app_env


def test_card_menu_and_post_relink_exact_existing_version(tmp_path):
    with isolated_versioned_app_env(tmp_path, "card-relink.db") as env:
        with main.app.app_context():
            seed = seed_matrix_graph(main.get_db_connection(), name="Card relink")
        login_admin(env["client"])
        page = env["client"].get(f'/admin/editar_matriz/{seed["matrix_id"]}?tab=aac')
        assert page.status_code == 200
        assert "v1" in page.get_data(as_text=True)
        response = env["client"].post(
            f'/admin/matrizes/{seed["matrix_id"]}/atividades/{seed["v1"]}/nova-versao',
            data={"versao_id": str(seed["v2"]), "active_tab": "aac"},
        )
        assert response.status_code == 302
        with main.app.app_context():
            assert current_version_id(main.get_db_connection(), seed) == seed["v2"]


def test_card_relink_rejects_inactive_and_cross_base_versions(tmp_path):
    with isolated_versioned_app_env(tmp_path, "card-reject.db") as env:
        with main.app.app_context():
            conn = main.get_db_connection()
            seed = seed_matrix_graph(conn, name="Card reject")
            other = seed_matrix_graph(conn, name="Other base")
        login_admin(env["client"])
        endpoint = f'/admin/matrizes/{seed["matrix_id"]}/atividades/{seed["v1"]}/nova-versao'
        env["client"].post(endpoint, data={"versao_id": str(seed["v3_inactive"]), "active_tab": "aac"})
        env["client"].post(endpoint, data={"versao_id": str(other["v1"]), "active_tab": "aac"})
        with main.app.app_context():
            assert current_version_id(main.get_db_connection(), seed) == seed["v1"]


def test_card_relink_is_noop_when_same_version_selected(tmp_path):
    with isolated_versioned_app_env(tmp_path, "card-noop.db") as env:
        with main.app.app_context():
            seed = seed_matrix_graph(main.get_db_connection(), name="Card noop")
        login_admin(env["client"])
        response = env["client"].post(
            f'/admin/matrizes/{seed["matrix_id"]}/atividades/{seed["v1"]}/nova-versao',
            data={"versao_id": str(seed["v1"]), "active_tab": "aac"},
            follow_redirects=True,
        )
        assert "já está vinculada" in response.get_data(as_text=True)
