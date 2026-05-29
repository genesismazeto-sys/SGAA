import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from app import db as app_db_module
import main


@pytest.fixture()
def isolated_client(tmp_path):
    app = main.app
    temp_database = tmp_path / "release_admin_crud.db"

    original_database = main.DATABASE
    original_env_database = os.environ.get("APP_DATABASE")
    original_config_database_path = app.config.get("DATABASE_PATH")

    os.environ["APP_DATABASE"] = str(temp_database)
    main.DATABASE = str(temp_database)
    app_db_module.DATABASE = str(temp_database)
    app.config["DATABASE_PATH"] = str(temp_database)
    app.config["TESTING"] = True

    with app.app_context():
        try:
            main.close_db_connection(None)
        except Exception:
            pass
        main.init_db()

    client = app.test_client()

    try:
        yield client
    finally:
        with app.app_context():
            try:
                main.close_db_connection(None)
            except Exception:
                pass

        main.DATABASE = original_database
        app_db_module.DATABASE = original_database
        if original_config_database_path is None:
            app.config.pop("DATABASE_PATH", None)
        else:
            app.config["DATABASE_PATH"] = original_config_database_path

        if original_env_database is None:
            os.environ.pop("APP_DATABASE", None)
        else:
            os.environ["APP_DATABASE"] = original_env_database


def _login_admin(client):
    response = client.post(
        "/login",
        data={"email": "admin@ej.edu.br", "senha": "admin123"},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)


def _create_course_via_route(client, *, nome, codigo, duracao_periodos=8, status="ativo"):
    response = client.post(
        "/admin/cursos/adicionar",
        data={
            "nome": nome,
            "codigo": codigo,
            "duracao_periodos": str(duracao_periodos),
            "status": status,
        },
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        row = conn.execute(
            "SELECT id, nome, codigo, duracao_periodos, status FROM cursos WHERE codigo = ?",
            (codigo,),
        ).fetchone()

    assert row is not None
    return row


def _create_matrix_for_course(curso_id, *, nome, versao="2026.1"):
    with main.app.app_context():
        conn = main.get_db_connection()
        main.ensure_matrizes_atividades_table(conn)
        matrix_id = conn.execute(
            """
            INSERT INTO matrizes_atividades (
                curso_id, nome, versao, status, data_inicio_vigencia,
                horas_aac_obrigatorias, horas_extensao_obrigatorias, descricao
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (
                curso_id,
                nome,
                versao,
                "vigente",
                "2026-01-01",
                160,
                80,
                "Matriz para teste de release",
            ),
        ).fetchone()["id"]
        conn.commit()
    return matrix_id


def _create_support_turma_for_aluno(curso_codigo="REL-ALUNO-CURSO"):
    with main.app.app_context():
        conn = main.get_db_connection()
        main.ensure_turmas_matriz_schema(conn)
        main.ensure_matrizes_atividades_table(conn)

        conn.execute(
            "INSERT INTO cursos (nome, codigo, duracao_periodos, status) VALUES (?, ?, ?, ?)",
            ("Curso Base Aluno", curso_codigo, 8, "ativo"),
        )
        curso_id = conn.execute(
            "SELECT id FROM cursos WHERE codigo = ?",
            (curso_codigo,),
        ).fetchone()["id"]

        matriz_id = conn.execute(
            """
            INSERT INTO matrizes_atividades (
                curso_id, nome, versao, status, data_inicio_vigencia,
                horas_aac_obrigatorias, horas_extensao_obrigatorias, descricao
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (
                curso_id,
                "Matriz Base Aluno",
                "2026.2",
                "vigente",
                "2026-07-01",
                120,
                60,
                "Matriz base para aluno",
            ),
        ).fetchone()["id"]

        turma_codigo = main.gerar_codigo_turma(curso_codigo, 1)
        turma_id = conn.execute(
            """
            INSERT INTO turmas (
                nome, ano, semestre, turno, status, numero, curso_id, matriz_id,
                ano_inicio, semestre_inicio, ano_fim, semestre_fim, codigo
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (
                turma_codigo,
                None,
                None,
                "Manha",
                "Ativa",
                1,
                curso_id,
                matriz_id,
                2026,
                1,
                2029,
                2,
                turma_codigo,
            ),
        ).fetchone()["id"]
        conn.commit()

    return turma_id


def test_release_admin_curso_crud_happy_path(isolated_client):
    client = isolated_client
    _login_admin(client)

    curso = _create_course_via_route(
        client,
        nome="Curso Release CRUD",
        codigo="REL-CURSO-CRUD",
        duracao_periodos=8,
        status="ativo",
    )
    curso_id = curso["id"]

    list_response = client.get("/admin/cursos")
    assert list_response.status_code == 200
    list_html = list_response.get_data(as_text=True)
    assert "Curso Release CRUD" in list_html

    edit_response = client.post(
        f"/admin/cursos/{curso_id}/editar",
        data={
            "nome": "Curso Release CRUD Editado",
            "codigo": "REL-CURSO-EDIT",
            "duracao_periodos": "10",
            "status": "inativo",
        },
        follow_redirects=False,
    )
    assert edit_response.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        edited = conn.execute(
            "SELECT nome, codigo, duracao_periodos, status FROM cursos WHERE id = ?",
            (curso_id,),
        ).fetchone()
    assert edited is not None
    assert edited["nome"] == "Curso Release CRUD Editado"
    assert edited["codigo"] == "REL-CURSO-EDIT"
    assert int(edited["duracao_periodos"]) == 10
    assert edited["status"] == "inativo"

    delete_response = client.post(f"/admin/deletar_curso/{curso_id}", follow_redirects=False)
    assert delete_response.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        deleted = conn.execute("SELECT id FROM cursos WHERE id = ?", (curso_id,)).fetchone()
    assert deleted is None


def test_release_admin_turma_crud_happy_path(isolated_client):
    client = isolated_client
    _login_admin(client)

    curso = _create_course_via_route(
        client,
        nome="Curso Release Turma",
        codigo="REL-TURMA-CURSO",
        duracao_periodos=8,
        status="ativo",
    )
    curso_id = curso["id"]
    matriz_id = _create_matrix_for_course(curso_id, nome="Matriz Release Turma")

    create_response = client.post(
        "/admin/adicionar_turma",
        data={
            "curso_id": str(curso_id),
            "matriz_id": str(matriz_id),
            "ano_inicio": "2026",
            "semestre_inicio": "1",
            "ano_fim": "2029",
            "semestre_fim": "2",
            "turno": "Noite",
            "status": "Ativa",
            "numero_turma": "11",
        },
        follow_redirects=False,
    )
    assert create_response.status_code in (302, 303)

    turma_codigo = main.gerar_codigo_turma("REL-TURMA-CURSO", 11)
    with main.app.app_context():
        conn = main.get_db_connection()
        turma = conn.execute(
            "SELECT id, codigo, numero, turno, status, curso_id, matriz_id FROM turmas WHERE codigo = ?",
            (turma_codigo,),
        ).fetchone()
    assert turma is not None
    turma_id = turma["id"]
    assert turma["curso_id"] == curso_id
    assert turma["matriz_id"] == matriz_id

    edit_response = client.post(
        f"/admin/editar_turma/{turma_id}",
        data={
            "curso_id": str(curso_id),
            "matriz_id": str(matriz_id),
            "ano_inicio": "2026",
            "semestre_inicio": "1",
            "ano_fim": "2030",
            "semestre_fim": "1",
            "turno": "Integral",
            "status": "Inativa",
            "numero_turma": "12",
        },
        follow_redirects=False,
    )
    assert edit_response.status_code in (302, 303)

    turma_codigo_editado = main.gerar_codigo_turma("REL-TURMA-CURSO", 12)
    with main.app.app_context():
        conn = main.get_db_connection()
        turma_editada = conn.execute(
            "SELECT codigo, numero, turno, status, ano_fim, semestre_fim FROM turmas WHERE id = ?",
            (turma_id,),
        ).fetchone()
    assert turma_editada is not None
    assert turma_editada["codigo"] == turma_codigo_editado
    assert int(turma_editada["numero"]) == 12
    assert turma_editada["turno"] == "Integral"
    assert turma_editada["status"] == "Inativa"
    assert int(turma_editada["ano_fim"]) == 2030
    assert int(turma_editada["semestre_fim"]) == 1

    delete_response = client.post(f"/admin/deletar_turma/{turma_id}", follow_redirects=False)
    assert delete_response.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        deleted = conn.execute("SELECT id FROM turmas WHERE id = ?", (turma_id,)).fetchone()
    assert deleted is None


def test_release_admin_aluno_crud_happy_path(isolated_client):
    client = isolated_client
    _login_admin(client)

    turma_id = _create_support_turma_for_aluno()
    email = "release.aluno.crud@teste.local"

    create_response = client.post(
        "/admin/adicionar_aluno",
        data={
            "nome": "Aluno Release CRUD",
            "email": email,
            "senha": "abc12345",
            "matricula": "REL-ALUNO-001",
            "turma_id": str(turma_id),
            "status": "Ativo",
        },
        follow_redirects=False,
    )
    assert create_response.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        usuario = conn.execute(
            "SELECT id, nome, email, tipo FROM usuarios WHERE email = ?",
            (email,),
        ).fetchone()
        assert usuario is not None
        usuario_id = usuario["id"]
        aluno = conn.execute(
            "SELECT usuario_id, nome, matricula, email, turma_id, status FROM alunos WHERE usuario_id = ?",
            (usuario_id,),
        ).fetchone()

    assert usuario["tipo"] == "aluno"
    assert aluno is not None
    assert aluno["turma_id"] == turma_id
    assert aluno["status"] == "Ativo"

    edit_response = client.post(
        f"/admin/editar_aluno/{usuario_id}",
        data={
            "nome": "Aluno Release CRUD Editado",
            "email": email,
            "matricula": "REL-ALUNO-EDIT",
            "turma_id": str(turma_id),
            "status": "Inativo",
            "senha": "",
        },
        follow_redirects=False,
    )
    assert edit_response.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        usuario_editado = conn.execute(
            "SELECT nome, email FROM usuarios WHERE id = ?",
            (usuario_id,),
        ).fetchone()
        aluno_editado = conn.execute(
            "SELECT nome, matricula, status, turma_id FROM alunos WHERE usuario_id = ?",
            (usuario_id,),
        ).fetchone()

    assert usuario_editado is not None
    assert usuario_editado["nome"] == "Aluno Release CRUD Editado"
    assert aluno_editado is not None
    assert aluno_editado["matricula"]
    assert aluno_editado["status"] == "Inativo"
    assert aluno_editado["turma_id"] == turma_id

    delete_response = client.post(f"/admin/deletar_aluno/{usuario_id}", follow_redirects=False)
    assert delete_response.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        aluno_deleted = conn.execute("SELECT id FROM alunos WHERE usuario_id = ?", (usuario_id,)).fetchone()
        usuario_deleted = conn.execute("SELECT id FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()

    assert aluno_deleted is None
    assert usuario_deleted is None


def test_release_admin_atividade_crud_happy_path(isolated_client):
    client = isolated_client
    _login_admin(client)

    nome = "Atividade Release CRUD"
    nome_editado = "Atividade Release CRUD Editada"

    create_response = client.post(
        "/admin/adicionar_atividade",
        data={
            "tipo_atividade": "Acadêmica Complementar",
            "grupo": "1 - Grupo Release",
            "nome": nome,
            "descricao": "Atividade criada no release test",
            "tem_limitacao": "0",
        },
        follow_redirects=False,
    )
    assert create_response.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        atividade = conn.execute(
            "SELECT id, grupo, nome, descricao, tipo_atividade FROM atividades WHERE nome = ?",
            (nome,),
        ).fetchone()
    assert atividade is not None
    atividade_id = atividade["id"]
    assert atividade["tipo_atividade"] == "Acadêmica Complementar"

    edit_response = client.post(
        f"/admin/editar_atividade/{atividade_id}",
        data={
            "tipo_atividade": "Acadêmica Complementar",
            "grupo": "2 - Grupo Release",
            "nome": nome_editado,
            "descricao": "Atividade editada no release test",
            "tem_limitacao": "0",
        },
        follow_redirects=False,
    )
    assert edit_response.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        atividade_editada = conn.execute(
            "SELECT grupo, nome, descricao FROM atividades WHERE id = ?",
            (atividade_id,),
        ).fetchone()
    assert atividade_editada is not None
    assert atividade_editada["nome"] == nome_editado
    assert atividade_editada["grupo"] == "2 - Grupo Release"

    delete_response = client.post(f"/admin/deletar_atividade/{atividade_id}", follow_redirects=False)
    assert delete_response.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        deleted = conn.execute("SELECT id FROM atividades WHERE id = ?", (atividade_id,)).fetchone()
    assert deleted is None
