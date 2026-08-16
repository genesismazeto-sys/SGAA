import io
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main


@pytest.fixture()
def client():
    app = main.app
    with app.app_context():
        main.init_db()
        yield app.test_client()


def _login_admin(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["user_type"] = "admin"
        sess["user_name"] = "Administrador"


def test_admin_api_aluno_requisicao_scope_exposes_matrix_scope(client):
    allowed_name = "AAC Admin Scope Permitida"
    email = "admin.scope.aluno@teste.local"
    matricula = "MAT-ADMIN-SCOPE-001"
    matriz_nome = "Matriz Admin Scope Aluno"

    with main.app.app_context():
        conn = main.get_db_connection()
        main.ensure_matrizes_atividades_table(conn)
        main.ensure_matriz_atividade_links_table(conn)
        main.ensure_turmas_matriz_schema(conn)

        curso = conn.execute("SELECT id, codigo FROM cursos ORDER BY id LIMIT 1").fetchone()
        assert curso is not None
        turma_codigo = main.gerar_codigo_turma(curso["codigo"], 91)

        conn.execute(
            "DELETE FROM requisicao_arquivos WHERE requisicao_id IN (SELECT id FROM requisicoes WHERE aluno_id IN (SELECT id FROM alunos WHERE matricula = ?))",
            (matricula,),
        )
        conn.execute("DELETE FROM requisicoes WHERE aluno_id IN (SELECT id FROM alunos WHERE matricula = ?)", (matricula,))
        conn.execute("DELETE FROM alunos WHERE matricula = ?", (matricula,))
        conn.execute("DELETE FROM usuarios WHERE email = ?", (email,))
        conn.execute("DELETE FROM turmas WHERE codigo = ?", (turma_codigo,))
        conn.execute("DELETE FROM atividades WHERE nome = ?", (allowed_name,))
        conn.execute("DELETE FROM matrizes_atividades WHERE nome = ?", (matriz_nome,))

        allowed_id = conn.execute(
            """
            INSERT INTO atividades (
                grupo, nome, limite_horas, tipo_atividade, tem_limitacao, tipo_limitacao,
                limite_horas_total, limite_horas_semestral, documentos_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            ("4 - Grupo Admin Scope", allowed_name, None, "Acadêmica Complementar", 0, None, None, None, None),
        ).fetchone()["id"]
        matriz_id = conn.execute(
            """
            INSERT INTO matrizes_atividades (
                curso_id, nome, versao, status, data_inicio_vigencia,
                horas_aac_obrigatorias, horas_extensao_obrigatorias, descricao
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (curso["id"], matriz_nome, "2028.1", "vigente", "2028-01-01", 150, 80, "Teste admin scope aluno"),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO matrizes_atividades_itens (matriz_id, atividade_id) VALUES (?, ?)",
            (matriz_id, allowed_id),
        )
        turma_id = conn.execute(
            """
            INSERT INTO turmas (
                nome, ano, semestre, turno, status, numero, curso_id, matriz_id,
                ano_inicio, semestre_inicio, ano_fim, semestre_fim, codigo
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (turma_codigo, None, None, "Noite", "Ativa", 91, curso["id"], matriz_id, 2028, 1, 2031, 2, turma_codigo),
        ).fetchone()["id"]
        usuario_id = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo) VALUES (?, ?, ?, ?) RETURNING id",
            ("Aluno Scope Admin", email, main.hash_password("aluno123"), "aluno"),
        ).fetchone()["id"]
        aluno_id = conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status) VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
            (usuario_id, "Aluno Scope Admin", matricula, email, turma_id, "Ativo"),
        ).fetchone()["id"]
        conn.commit()

    _login_admin(client)

    response = client.get(f"/admin/api/aluno/{aluno_id}/requisicao-scope")
    assert response.status_code == 200
    data = response.get_json()
    assert data is not None
    assert data["aluno_id"] == aluno_id
    assert data["allowed_activity_ids"] == [allowed_id]
    assert data["matriz_scope"] is not None
    assert matriz_nome in data["matriz_scope"]["label"]


def test_admin_create_requisicao_respects_matrix_scope_and_saves_attachment(client):
    allowed_name = "AAC Admin Create Permitida"
    blocked_name = "AAC Admin Create Bloqueada"
    email = "admin.create.req@teste.local"
    matricula = "MAT-ADMIN-CREATE-001"
    matriz_nome = "Matriz Admin Create"

    with main.app.app_context():
        conn = main.get_db_connection()
        main.ensure_matrizes_atividades_table(conn)
        main.ensure_matriz_atividade_links_table(conn)
        main.ensure_turmas_matriz_schema(conn)

        curso = conn.execute("SELECT id, codigo FROM cursos ORDER BY id LIMIT 1").fetchone()
        assert curso is not None
        turma_codigo = main.gerar_codigo_turma(curso["codigo"], 92)

        conn.execute(
            "DELETE FROM requisicao_arquivos WHERE requisicao_id IN (SELECT id FROM requisicoes WHERE aluno_id IN (SELECT id FROM alunos WHERE matricula = ?))",
            (matricula,),
        )
        conn.execute("DELETE FROM requisicoes WHERE aluno_id IN (SELECT id FROM alunos WHERE matricula = ?)", (matricula,))
        conn.execute("DELETE FROM alunos WHERE matricula = ?", (matricula,))
        conn.execute("DELETE FROM usuarios WHERE email = ?", (email,))
        conn.execute("DELETE FROM turmas WHERE codigo = ?", (turma_codigo,))
        conn.execute("DELETE FROM atividades WHERE nome IN (?, ?)", (allowed_name, blocked_name))
        conn.execute("DELETE FROM matrizes_atividades WHERE nome = ?", (matriz_nome,))

        allowed_id = conn.execute(
            """
            INSERT INTO atividades (
                grupo, nome, limite_horas, tipo_atividade, tem_limitacao, tipo_limitacao,
                limite_horas_total, limite_horas_semestral, documentos_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            ("5 - Grupo Admin Create", allowed_name, None, "Acadêmica Complementar", 0, None, None, None, None),
        ).fetchone()["id"]
        blocked_id = conn.execute(
            """
            INSERT INTO atividades (
                grupo, nome, limite_horas, tipo_atividade, tem_limitacao, tipo_limitacao,
                limite_horas_total, limite_horas_semestral, documentos_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            ("5 - Grupo Admin Create", blocked_name, None, "Acadêmica Complementar", 0, None, None, None, None),
        ).fetchone()["id"]
        matriz_id = conn.execute(
            """
            INSERT INTO matrizes_atividades (
                curso_id, nome, versao, status, data_inicio_vigencia,
                horas_aac_obrigatorias, horas_extensao_obrigatorias, descricao
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (curso["id"], matriz_nome, "2028.2", "vigente", "2028-08-01", 160, 90, "Teste admin create"),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO matrizes_atividades_itens (matriz_id, atividade_id) VALUES (?, ?)",
            (matriz_id, allowed_id),
        )
        norma_id = conn.execute(
            """
            INSERT INTO norma_atividade (codigo, eixo, revisao, nome, status)
            VALUES (?, 'AAC', ?, ?, 'ativa')
            RETURNING id
            """,
            ("ADMIN-CREATE-AAC", "fc10", "Norma admin create"),
        ).fetchone()["id"]
        base_id = conn.execute(
            """
            INSERT INTO atividade_base (nome_conceito, descricao, status)
            VALUES (?, ?, 'ativo')
            RETURNING id
            """,
            ("Base Admin Create", "Base para o teste de criação admin"),
        ).fetchone()["id"]
        version_id = conn.execute(
            """
            INSERT INTO atividade_versao (
                atividade_base_id, norma_id, codigo_normativo, eixo, grupo,
                ch_por_evento, observacao_aluno, observacao_admin,
                vigencia_inicio, vigencia_fim, numero_versao, status
            ) VALUES (?, ?, ?, 'AAC', ?, ?, ?, ?, ?, ?, 1, 'ativa')
            RETURNING id
            """,
            (
                base_id,
                norma_id,
                "ADMIN-CREATE-AAC",
                "5 - Grupo Admin Create",
                6,
                "Obs aluno",
                "Obs admin",
                "2028-01-01",
                "2028-12-31",
            ),
        ).fetchone()["id"]
        conn.execute("INSERT INTO matriz_norma (matriz_id, norma_id) VALUES (?, ?)", (matriz_id, norma_id))
        conn.execute(
            "INSERT INTO atividade_legacy_map (atividade_id_legacy, atividade_base_id, status) VALUES (?, ?, 'mapeada')",
            (allowed_id, base_id),
        )
        conn.execute(
            "INSERT INTO matriz_atividade_versao_item (matriz_id, atividade_versao_id) VALUES (?, ?)",
            (matriz_id, version_id),
        )
        turma_id = conn.execute(
            """
            INSERT INTO turmas (
                nome, ano, semestre, turno, status, numero, curso_id, matriz_id,
                ano_inicio, semestre_inicio, ano_fim, semestre_fim, codigo
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (turma_codigo, None, None, "Noite", "Ativa", 92, curso["id"], matriz_id, 2028, 2, 2032, 1, turma_codigo),
        ).fetchone()["id"]
        usuario_id = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo) VALUES (?, ?, ?, ?) RETURNING id",
            ("Aluno Create Admin", email, main.hash_password("aluno123"), "aluno"),
        ).fetchone()["id"]
        aluno_id = conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status) VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
            (usuario_id, "Aluno Create Admin", matricula, email, turma_id, "Ativo"),
        ).fetchone()["id"]
        conn.commit()

    _login_admin(client)

    blocked_response = client.post(
        "/admin/requisicoes/nova",
        data={
            "aluno_id": str(aluno_id),
            "tipo_atividade": "Acadêmica Complementar",
            "grupo": "5 - Grupo Admin Create",
            "atividade_id": str(blocked_id),
            "nome_evento": "Evento bloqueado",
            "horas_solicitadas": "4",
            "data_evento": "2028-09-10",
            "observacao": "Nao deve criar",
        },
        follow_redirects=False,
    )
    assert blocked_response.status_code == 302
    assert "/admin/requisicoes?open_new=1" in blocked_response.headers["Location"]

    with main.app.app_context():
        conn = main.get_db_connection()
        blocked_count = conn.execute(
            "SELECT COUNT(*) FROM requisicoes WHERE aluno_id = ? AND nome_evento = ?",
            (aluno_id, "Evento bloqueado"),
        ).fetchone()[0]
        assert blocked_count == 0

    allowed_response = client.post(
        "/admin/requisicoes/nova",
        data={
            "aluno_id": str(aluno_id),
            "tipo_atividade": "Acadêmica Complementar",
            "grupo": "5 - Grupo Admin Create",
            "atividade_id": str(allowed_id),
            "nome_evento": "Evento permitido",
            "horas_solicitadas": "6",
            "data_evento": "2028-09-12",
            "observacao": "Criado pelo admin",
            "comprovantes_files": (io.BytesIO(b"conteudo-pdf"), "comprovante.pdf"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert allowed_response.status_code == 302
    assert allowed_response.headers["Location"].endswith("/admin/requisicoes")

    with main.app.app_context():
        conn = main.get_db_connection()
        req = conn.execute(
            "SELECT id, status, arquivo_comprovante, observacao FROM requisicoes WHERE aluno_id = ? AND nome_evento = ? ORDER BY id DESC LIMIT 1",
            (aluno_id, "Evento permitido"),
        ).fetchone()
        assert req is not None
        assert req["status"] == "Pendente"
        assert req["observacao"] == "Criado pelo admin"
        assert req["arquivo_comprovante"]
        anexos_count = conn.execute(
            "SELECT COUNT(*) FROM requisicao_arquivos WHERE requisicao_id = ?",
            (req["id"],),
        ).fetchone()[0]
        assert anexos_count == 1
        req_id = req["id"]

    blocked_edit_response = client.post(
        f"/admin/requisicoes/{req_id}/editar",
        data={
            "atividade_id": str(blocked_id),
            "nome_evento": "Evento permitido",
            "horas_solicitadas": "6",
            "data_evento": "2028-09-12",
            "observacao": "Tentativa bloqueada",
        },
        follow_redirects=False,
    )
    assert blocked_edit_response.status_code == 302
    assert "open_edit=1" in blocked_edit_response.headers["Location"]

    with main.app.app_context():
        conn = main.get_db_connection()
        same_req = conn.execute(
            "SELECT atividade_id, observacao FROM requisicoes WHERE id = ?",
            (req_id,),
        ).fetchone()
        assert same_req is not None
        assert same_req["atividade_id"] == allowed_id
        assert same_req["observacao"] == "Criado pelo admin"

    edit_response = client.post(
        f"/admin/requisicoes/{req_id}/editar",
        data={
            "atividade_id": str(allowed_id),
            "nome_evento": "Evento atualizado pelo admin",
            "horas_solicitadas": "8",
            "data_evento": "2028-09-20",
            "observacao": "Atualizado pelo admin",
            "comprovantes_files": (io.BytesIO(b"novo-conteudo"), "comprovante-2.pdf"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert edit_response.status_code == 302
    assert edit_response.headers["Location"].endswith("/admin/requisicoes")

    with main.app.app_context():
        conn = main.get_db_connection()
        updated_req = conn.execute(
            "SELECT atividade_id, nome_evento, horas_solicitadas, data_evento, observacao FROM requisicoes WHERE id = ?",
            (req_id,),
        ).fetchone()
        assert updated_req is not None
        assert updated_req["atividade_id"] == allowed_id
        assert updated_req["nome_evento"] == "Evento atualizado pelo admin"
        assert float(updated_req["horas_solicitadas"]) == 8.0
        assert updated_req["data_evento"] == "2028-09-20"
        assert updated_req["observacao"] == "Atualizado pelo admin"
        anexos_count = conn.execute(
            "SELECT COUNT(*) FROM requisicao_arquivos WHERE requisicao_id = ?",
            (req_id,),
        ).fetchone()[0]
        assert anexos_count == 2
