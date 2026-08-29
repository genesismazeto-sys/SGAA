from __future__ import annotations

import main
from tests.canonical_matrix_test_support import current_version_id, login_admin, seed_matrix_graph
from tests.versioned_test_support import isolated_versioned_app_env


def test_version_page_lists_base_and_active_choices(tmp_path):
    with isolated_versioned_app_env(tmp_path, "version-page.db") as env:
        with main.app.app_context():
            seed = seed_matrix_graph(main.get_db_connection(), name="Version page")
        login_admin(env["client"])
        response = env["client"].get(f'/admin/matrizes/{seed["matrix_id"]}/versoes')
        html = response.get_data(as_text=True)
        assert response.status_code == 200
        assert "Version page activity" in html
        assert "v2" in html
        assert "v3" not in html


def test_define_and_remove_mutate_only_canonical_item(tmp_path):
    with isolated_versioned_app_env(tmp_path, "define-remove.db") as env:
        with main.app.app_context():
            seed = seed_matrix_graph(main.get_db_connection(), name="Define remove")
        login_admin(env["client"])
        env["client"].post(
            f'/admin/matrizes/{seed["matrix_id"]}/versoes/definir',
            data={"base_id": seed["base_id"], "versao_id": seed["v2"]},
        )
        with main.app.app_context():
            assert current_version_id(main.get_db_connection(), seed) == seed["v2"]
        env["client"].post(
            f'/admin/matrizes/{seed["matrix_id"]}/versoes/remover',
            data={"base_id": seed["base_id"]},
        )
        with main.app.app_context():
            assert current_version_id(main.get_db_connection(), seed) is None


def test_define_rejects_wrong_base_inactive_and_out_of_scope(tmp_path):
    with isolated_versioned_app_env(tmp_path, "define-reject.db") as env:
        with main.app.app_context():
            conn = main.get_db_connection()
            seed = seed_matrix_graph(conn, name="Define reject")
            other = seed_matrix_graph(conn, name="Unrelated base")
        login_admin(env["client"])
        endpoint = f'/admin/matrizes/{seed["matrix_id"]}/versoes/definir'
        for base_id, version_id in (
            (seed["base_id"], seed["v3_inactive"]),
            (seed["base_id"], other["v1"]),
            (other["base_id"], other["v1"]),
        ):
            env["client"].post(endpoint, data={"base_id": base_id, "versao_id": version_id})
        with main.app.app_context():
            assert current_version_id(main.get_db_connection(), seed) == seed["v1"]
