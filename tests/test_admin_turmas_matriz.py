import main
from tests.canonical_matrix_test_support import login_admin
from tests.versioned_test_support import isolated_versioned_app_env


def test_turma_edit_form_uses_explicit_matrix_and_canonical_period(tmp_path):
    with isolated_versioned_app_env(tmp_path, "turma-edit.db") as env:
        with main.app.app_context():
            conn = main.get_db_connection()
            turma_id = conn.execute(
                """INSERT INTO turmas
                     (nome,turno,status,numero,curso_id,ano_inicio,semestre_inicio,codigo,matriz_id)
                     VALUES ('Edit test','Manhã','Ativa',99,1,2025,1,'PPA-0099',1) RETURNING id"""
            ).fetchone()["id"]
            conn.commit()
        login_admin(env["client"])
        response = env["client"].get(f"/admin/editar_turma/{turma_id}")
        html = response.get_data(as_text=True)
        assert response.status_code == 200
        assert 'name="matriz_id"' in html
        assert 'name="ano_inicio"' in html
        assert 'name="semestre_inicio"' in html


def test_turma_detail_displays_explicit_matrix(tmp_path):
    with isolated_versioned_app_env(tmp_path, "turma-detail.db") as env:
        login_admin(env["client"])
        response = env["client"].get("/admin/turma/1")
        assert response.status_code == 200
        assert "Matriz PPA" in response.get_data(as_text=True)
