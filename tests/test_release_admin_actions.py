import main
from tests.canonical_matrix_test_support import login_admin
from tests.canonical_request_test_support import create_admin_request
from tests.versioned_test_support import isolated_versioned_app_env


def test_admin_total_can_execute_canonical_request_action(tmp_path):
    with isolated_versioned_app_env(tmp_path, "release-actions.db") as env:
        login_admin(env["client"])
        _, row = create_admin_request(env["client"], name="Release action", version_id=29)
        response = env["client"].post(f'/admin/processar_requisicao/{row["id"]}', data={"status": "Indeferida"})
        assert response.status_code == 302
        with main.app.app_context():
            assert main.get_db_connection().execute("SELECT status FROM requisicoes WHERE id=?", (row["id"],)).fetchone()[0] == "Indeferida"
