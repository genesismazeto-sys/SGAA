import re

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


def test_turma_delete_refusal_reaches_ajax_caller_with_reason(tmp_path):
    """Exclusão pela listagem é fetch(): a recusa precisa de status próprio.

    Respondendo 302, o fetch seguia até a listagem e lia 200 OK, o flash ia
    embora no corpo descartado e a turma apenas "não sumia", sem aviso nenhum.
    """
    with isolated_versioned_app_env(tmp_path, "turma-delete-ajax.db") as env:
        login_admin(env["client"])
        with main.app.app_context():
            conn = main.get_db_connection()
            turma_id = conn.execute(
                """INSERT INTO turmas
                     (nome,turno,status,numero,curso_id,ano_inicio,semestre_inicio,codigo)
                     VALUES ('Delete test','Noite','Ativa',77,1,2026,1,'PPA-T77') RETURNING id"""
            ).fetchone()["id"]
            usuario_id = conn.execute(
                "INSERT INTO usuarios(nome,email,senha,tipo) VALUES('Vinculado','vinc@ex.com','x','aluno') RETURNING id"
            ).fetchone()["id"]
            conn.execute(
                "INSERT INTO alunos(usuario_id,nome,email,matricula,turma_id,status)"
                " VALUES(?,'Vinculado','vinc@ex.com','V001',?,'Ativo')",
                (usuario_id, turma_id),
            )
            conn.commit()

        refused = env["client"].post(
            f"/admin/deletar_turma/{turma_id}",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert refused.status_code == 409
        payload = refused.get_json()
        assert payload["ok"] is False
        assert "alunos vinculados" in payload["error"]
        with main.app.app_context():
            assert main.get_db_connection().execute(
                "SELECT 1 FROM turmas WHERE id=?", (turma_id,)
            ).fetchone() is not None

        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute("UPDATE alunos SET turma_id=NULL WHERE turma_id=?", (turma_id,))
            conn.commit()

        deleted = env["client"].post(
            f"/admin/deletar_turma/{turma_id}",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert deleted.status_code == 200
        assert deleted.get_json() == {"ok": True, "deleted": turma_id}
        with main.app.app_context():
            assert main.get_db_connection().execute(
                "SELECT 1 FROM turmas WHERE id=?", (turma_id,)
            ).fetchone() is None


def test_turma_delete_refusal_without_ajax_keeps_flash_and_redirect(tmp_path):
    """O caminho de navegação normal continua flash + redirect, como era."""
    with isolated_versioned_app_env(tmp_path, "turma-delete-plain.db") as env:
        login_admin(env["client"])
        with main.app.app_context():
            conn = main.get_db_connection()
            turma_id = conn.execute(
                """INSERT INTO turmas
                     (nome,turno,status,numero,curso_id,ano_inicio,semestre_inicio,codigo)
                     VALUES ('Delete plain','Noite','Ativa',78,1,2026,1,'PPA-T78') RETURNING id"""
            ).fetchone()["id"]
            usuario_id = conn.execute(
                "INSERT INTO usuarios(nome,email,senha,tipo) VALUES('Plain','plain@ex.com','x','aluno') RETURNING id"
            ).fetchone()["id"]
            conn.execute(
                "INSERT INTO alunos(usuario_id,nome,email,matricula,turma_id,status)"
                " VALUES(?,'Plain','plain@ex.com','P001',?,'Ativo')",
                (usuario_id, turma_id),
            )
            conn.commit()

        response = env["client"].post(f"/admin/deletar_turma/{turma_id}", follow_redirects=False)
        assert response.status_code == 302
        with env["client"].session_transaction() as session_state:
            assert session_state.get("_flashes") == [
                ("error", "Não é possível excluir: há alunos vinculados a esta turma.")
            ]


def _period_ui_assertions(html):
    """Label acentuado e semestre exibido como 1S/2S, com value 1/2 intacto."""
    assert "Início/fim" in html
    assert "Inicio/Fim" not in html
    assert re.search(r'value="1"[^>]*>\s*1S\s*<', html), "opção 1 deve exibir 1S"
    assert re.search(r'value="2"[^>]*>\s*2S\s*<', html), "opção 2 deve exibir 2S"
    assert 'name="semestre_inicio"' in html


def test_add_turma_period_ui_label_and_semester_display(tmp_path):
    with isolated_versioned_app_env(tmp_path, "turma-period-add.db") as env:
        login_admin(env["client"])
        response = env["client"].get("/admin/adicionar_turma")
        assert response.status_code == 200
        _period_ui_assertions(response.get_data(as_text=True))


def test_edit_turma_period_ui_label_and_semester_display(tmp_path):
    with isolated_versioned_app_env(tmp_path, "turma-period-edit.db") as env:
        login_admin(env["client"])
        response = env["client"].get("/admin/editar_turma/1")
        assert response.status_code == 200
        _period_ui_assertions(response.get_data(as_text=True))


def test_turma_save_does_not_rehash_existing_student_passwords(tmp_path):
    """Salvar a Turma não pode gerar hash novo para aluno que já existe.

    O hash PBKDF2 é o custo dominante da gravação; cobrá-lo de alunos
    preexistentes seria desperdício puro e ainda trocaria credencial de quem
    não mudou. Conta as chamadas reais ao werkzeug, cobrindo tanto o caminho
    serial quanto o lote paralelo.
    """
    import werkzeug.security

    with isolated_versioned_app_env(tmp_path, "turma-rehash.db") as env:
        login_admin(env["client"])
        original = werkzeug.security.generate_password_hash
        calls = []

        def counting(*args, **kwargs):
            calls.append(1)
            return original(*args, **kwargs)

        werkzeug.security.generate_password_hash = counting
        try:
            novo = _turma_payload(
                number=41,
                course_id=1,
                student={
                    "nome": "Aluno Persistente",
                    "email": "persistente@ex.com",
                    "matricula": "PS0001",
                },
            )
            created = env["client"].post(
                "/admin/adicionar_turma", data=novo, follow_redirects=False
            )
            assert created.status_code == 302
            assert len(calls) == 1, "aluno novo custa exatamente 1 hash"

            with main.app.app_context():
                conn = main.get_db_connection()
                turma_id = conn.execute(
                    "SELECT id FROM turmas WHERE numero=41"
                ).fetchone()["id"]
                senha_antes = conn.execute(
                    "SELECT senha FROM usuarios WHERE email=?", ("persistente@ex.com",)
                ).fetchone()["senha"]

            calls.clear()
            resave = env["client"].post(
                f"/admin/editar_turma/{turma_id}",
                data=_turma_payload(
                    number=41,
                    course_id=1,
                    student={
                        "nome": "Aluno Persistente",
                        "email": "persistente@ex.com",
                        "matricula": "PS0001",
                    },
                ),
                follow_redirects=False,
            )
            assert resave.status_code == 302
            assert calls == [], "aluno já existente não pode ser re-hasheado"

            with main.app.app_context():
                senha_depois = main.get_db_connection().execute(
                    "SELECT senha FROM usuarios WHERE email=?", ("persistente@ex.com",)
                ).fetchone()["senha"]
            assert senha_depois == senha_antes
        finally:
            werkzeug.security.generate_password_hash = original
