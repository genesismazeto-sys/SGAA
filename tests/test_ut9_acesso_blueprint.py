import main
from tests.canonical_matrix_test_support import login_admin
from tests.versioned_test_support import isolated_versioned_app_env


def test_access_page_reads_complete_prod1_identity_graph(tmp_path):
    with isolated_versioned_app_env(tmp_path, "access-page.db") as env:
        login_admin(env["client"])
        response = env["client"].get("/admin/acesso")
        assert response.status_code == 200
        assert "Acesso" in response.get_data(as_text=True)


def test_access_student_identity_uses_turma_id_only(tmp_path):
    with isolated_versioned_app_env(tmp_path, "access-save.db") as env:
        login_admin(env["client"])
        with main.app.app_context():
            columns = {row["name"] for row in main.get_db_connection().execute("PRAGMA table_info(alunos)")}
            assert "turma_id" in columns
            assert "turma" not in columns
        html = env["client"].get("/admin/acesso").get_data(as_text=True)
        assert 'name="turma_id"' in html


def test_access_save_rejects_duplicate_email_atomically(tmp_path):
    with isolated_versioned_app_env(tmp_path, "access-duplicate.db") as env:
        login_admin(env["client"])
        with main.app.app_context():
            email = main.get_db_connection().execute("SELECT email FROM usuarios ORDER BY id LIMIT 1").fetchone()[0]
            before = main.get_db_connection().execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]
        env["client"].post("/admin/acesso/salvar", data={
            "nome": "Duplicate", "email": email, "nivel_acesso": "admin_total", "senha": "x",
        })
        with main.app.app_context():
            assert main.get_db_connection().execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == before
