import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main


@pytest.fixture(scope="module")
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


def test_admin_api_requisicao_exposes_matrix_scope(client):
    allowed_name = "AAC API Scope Permitida"
    blocked_name = "AAC API Scope Bloqueada"
    email = "admin.api.scope@teste.local"
    matricula = "MAT-API-SCOPE-001"

    with main.app.app_context():
        conn = main.get_db_connection()
        main.ensure_matrizes_atividades_table(conn)
        main.ensure_matriz_atividade_links_table(conn)
        main.ensure_turmas_matriz_schema(conn)

        curso = conn.execute("SELECT id, codigo FROM cursos ORDER BY id LIMIT 1").fetchone()
        assert curso is not None
        turma_codigo = main.gerar_codigo_turma(curso["codigo"], 89)

        conn.execute("DELETE FROM requisicoes WHERE aluno_id IN (SELECT id FROM alunos WHERE matricula = ?)", (matricula,))
        conn.execute("DELETE FROM alunos WHERE matricula = ?", (matricula,))
        conn.execute("DELETE FROM usuarios WHERE email = ?", (email,))
        conn.execute("DELETE FROM turmas WHERE codigo = ?", (turma_codigo,))
        conn.execute("DELETE FROM atividades WHERE nome IN (?, ?)", (allowed_name, blocked_name))
        conn.execute("DELETE FROM matrizes_atividades WHERE nome = ?", ("Matriz API Scope",))

        allowed_id = conn.execute(
            """
            INSERT INTO atividades (
                grupo, nome, limite_horas, tipo_atividade, tem_limitacao, tipo_limitacao,
                limite_horas_total, limite_horas_semestral, documentos_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            ("3 - Grupo API Scope", allowed_name, None, "Acadêmica Complementar", 0, None, None, None, None),
        ).fetchone()["id"]
        blocked_id = conn.execute(
            """
            INSERT INTO atividades (
                grupo, nome, limite_horas, tipo_atividade, tem_limitacao, tipo_limitacao,
                limite_horas_total, limite_horas_semestral, documentos_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            ("3 - Grupo API Scope", blocked_name, None, "Acadêmica Complementar", 0, None, None, None, None),
        ).fetchone()["id"]
        matriz_id = conn.execute(
            """
            INSERT INTO matrizes_atividades (
                curso_id, nome, versao, status, data_inicio_vigencia,
                horas_aac_obrigatorias, horas_extensao_obrigatorias, descricao
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (curso["id"], "Matriz API Scope", "2027.1", "vigente", "2027-01-01", 160, 80, "Teste api scope"),
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
            (turma_codigo, None, None, "Noite", "Ativa", 89, curso["id"], matriz_id, 2027, 1, 2030, 2, turma_codigo),
        ).fetchone()["id"]
        usuario_id = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo) VALUES (?, ?, ?, ?) RETURNING id",
            ("Aluno API Scope", email, main.hash_password("aluno123"), "aluno"),
        ).fetchone()["id"]
        aluno_id = conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status) VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
            (usuario_id, "Aluno API Scope", matricula, email, turma_id, "Ativo"),
        ).fetchone()["id"]
        req_id = conn.execute(
            """
            INSERT INTO requisicoes (
                aluno_id, atividade_id, data_solicitacao, data_evento, horas_solicitadas,
                nome_evento, status, horas_deferidas, observacao, arquivo_comprovante,
                data_processamento, admin_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (aluno_id, blocked_id, "2027-05-10 10:00:00", "2027-05-10", 4, "Evento api", "Pendente", None, None, None, None, None),
        ).fetchone()["id"]
        conn.commit()

    _login_admin(client)

    response = client.get(f"/admin/api/requisicao/{req_id}")
    assert response.status_code == 200
    data = response.get_json()
    assert data is not None
    assert data["atividade_id"] == blocked_id
    assert data["allowed_activity_ids"] == [allowed_id]
    assert data["current_activity_allowed"] is False
    assert data["matriz_scope"] is not None
    assert "Matriz API Scope" in data["matriz_scope"]["label"]