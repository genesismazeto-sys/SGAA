import main
from tests.canonical_request_test_support import create_admin_request, login_admin, login_student
from tests.versioned_test_support import isolated_versioned_app_env


def test_login_and_primary_pages_smoke(tmp_path):
    with isolated_versioned_app_env(tmp_path, "phase0-pages.db") as env:
        login_student(env["client"])
        assert env["client"].get("/aluno/dashboard").status_code == 200
        login_admin(env["client"])
        assert env["client"].get("/admin/dashboard").status_code == 200


def test_request_create_and_process_smoke(tmp_path):
    with isolated_versioned_app_env(tmp_path, "phase0-request.db") as env:
        login_admin(env["client"])
        response, row = create_admin_request(env["client"], name="Phase0 canonical", version_id=29)
        assert response.status_code == 302
        assert env["client"].post(f'/admin/processar_requisicao/{row["id"]}', data={"status": "Deferida"}).status_code == 302
        with main.app.app_context():
            assert main.get_db_connection().execute("SELECT status FROM requisicoes WHERE id=?", (row["id"],)).fetchone()[0] == "Deferida"
