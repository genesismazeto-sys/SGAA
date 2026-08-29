import main
from tests.canonical_matrix_test_support import login_admin
from tests.versioned_test_support import isolated_versioned_app_env


def test_release_matrix_crud_uses_canonical_schema(tmp_path):
    with isolated_versioned_app_env(tmp_path, "release-crud.db") as env:
        login_admin(env["client"])
        response = env["client"].post("/admin/adicionar_matriz", data={
            "curso_id": 1, "nome": "Release CRUD", "status": "rascunho",
            "horas_aac_obrigatorias": 10, "horas_extensao_obrigatorias": 5,
        })
        assert response.status_code == 302
        with main.app.app_context():
            conn = main.get_db_connection()
            matrix_id = conn.execute("SELECT id FROM matrizes_atividades WHERE nome='Release CRUD'").fetchone()["id"]
        assert env["client"].post(f"/admin/matrizes/{matrix_id}/excluir").status_code == 302


def test_release_activity_catalog_crud_surface_is_available(tmp_path):
    with isolated_versioned_app_env(tmp_path, "release-activity.db") as env:
        login_admin(env["client"])
        assert env["client"].get("/admin/atividades").status_code == 200
        assert env["client"].get("/admin/editar_atividade/29").status_code == 200
