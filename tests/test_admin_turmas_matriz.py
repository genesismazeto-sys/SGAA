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
        assert 'name="matriz_id" id="matriz_id" required' not in html
        assert "Sem matriz" in html
        assert 'name="ano_inicio"' in html
        assert 'name="semestre_inicio"' in html


def test_turma_detail_displays_explicit_matrix(tmp_path):
    with isolated_versioned_app_env(tmp_path, "turma-detail.db") as env:
        login_admin(env["client"])
        response = env["client"].get("/admin/turma/1")
        assert response.status_code == 200
        assert "Matriz PPA" in response.get_data(as_text=True)


def _turma_payload(*, number, course_id, matrix_marker=None, student=None):
    payload = {
        "curso_id": str(course_id),
        "numero_turma": str(number),
        "ano_inicio": "2026",
        "semestre_inicio": "1",
        "ano_fim": "2029",
        "semestre_fim": "2",
        "turno": "Manhã",
        "status": "Ativa",
    }
    if matrix_marker is not None:
        payload["matriz_id"] = str(matrix_marker)
    if student:
        payload.update(
            {
                "aluno_nome[]": student["nome"],
                "aluno_email[]": student["email"],
                "aluno_matricula[]": student["matricula"],
                "aluno_situacao[]": "ATIVO",
                "aluno_importado[]": "0",
            }
        )
    return payload


def test_turma_can_be_created_without_matrix_and_existing_default_can_be_cleared(tmp_path):
    with isolated_versioned_app_env(tmp_path, "turma-optional-matrix.db") as env:
        login_admin(env["client"])
        with main.app.app_context():
            course_id = main.get_db_connection().execute(
                "SELECT curso_id FROM turmas WHERE id=1"
            ).fetchone()[0]
        created = env["client"].post(
            "/admin/adicionar_turma",
            data=_turma_payload(number=90, course_id=course_id),
            follow_redirects=False,
        )
        assert created.status_code == 302
        with env["client"].session_transaction() as session_state:
            assert session_state.get("_flashes") == [("success", "Turma criada com sucesso.")]
        with main.app.app_context():
            conn = main.get_db_connection()
            turma = conn.execute("SELECT * FROM turmas WHERE codigo='PPA-T90'").fetchone()
            assert turma["matriz_id"] is None
            turma_id = turma["id"]
            conn.execute("UPDATE turmas SET matriz_id=1 WHERE id=?", (turma_id,))
            conn.commit()

        edited = env["client"].post(
            f"/admin/editar_turma/{turma_id}",
            data=_turma_payload(number=90, course_id=course_id, matrix_marker=""),
            follow_redirects=False,
        )
        assert edited.status_code == 302
        with main.app.app_context():
            assert main.get_db_connection().execute(
                "SELECT matriz_id FROM turmas WHERE id=?", (turma_id,)
            ).fetchone()["matriz_id"] is None


def test_turma_default_change_does_not_cascade_and_cross_course_matrix_is_rejected(tmp_path):
    with isolated_versioned_app_env(tmp_path, "turma-default-no-cascade.db") as env:
        login_admin(env["client"])
        student = {
            "nome": "Aluno Base Versionado",
            "email": "aluno.base.versionado@example.com",
            "matricula": "PPA.TESTE.0001",
        }
        with main.app.app_context():
            course_id = main.get_db_connection().execute(
                "SELECT curso_id FROM turmas WHERE id=2"
            ).fetchone()[0]
        changed = env["client"].post(
            "/admin/editar_turma/2",
            data=_turma_payload(number=11, course_id=course_id, matrix_marker=1, student=student),
            follow_redirects=False,
        )
        assert changed.status_code == 302
        with env["client"].session_transaction() as session_state:
            assert session_state.get("_flashes") == [("success", "Turma atualizada com sucesso.")]
        with main.app.app_context():
            conn = main.get_db_connection()
            assert conn.execute("SELECT matriz_id FROM turmas WHERE id=2").fetchone()[0] == 1
            assert conn.execute("SELECT matriz_id FROM alunos WHERE email=?", (student["email"],)).fetchone()[0] == 2
            other_course = conn.execute(
                "INSERT INTO cursos(nome,codigo,duracao_periodos) VALUES('Other','OTH',8)"
            ).lastrowid
            other_matrix = conn.execute(
                "INSERT INTO matrizes_atividades(curso_id,nome) VALUES(?,'Other matrix')",
                (other_course,),
            ).lastrowid
            conn.commit()

        rejected = env["client"].post(
            "/admin/adicionar_turma",
            data=_turma_payload(number=91, course_id=course_id, matrix_marker=other_matrix),
            follow_redirects=False,
        )
        assert rejected.status_code == 302
        with main.app.app_context():
            assert main.get_db_connection().execute(
                "SELECT 1 FROM turmas WHERE codigo='PPA-T91'"
            ).fetchone() is None
