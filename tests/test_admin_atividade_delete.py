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
    # Fechar o app_context após init_db garante que g.db seja fechado
    # antes de ceder o controle ao teste, evitando 'database is locked'
    # no cleanup que abre uma conexão de escrita concorrente.
    with app.app_context():
        main.init_db()
    yield app.test_client()


def _login_admin(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["user_type"] = "admin"
        sess["user_name"] = "Administrador"


def test_admin_deletar_atividade_remove_links_and_activity(client):
    activity_name = "AAC Delete Matrix Link Test"
    matrix_name = "Matriz Delete Matrix Link Test"

    with main.app.app_context():
        conn = main.get_db_connection()
        main.ensure_matrizes_atividades_table(conn)
        main.ensure_matriz_atividade_links_table(conn)

        curso = conn.execute("SELECT id FROM cursos ORDER BY id LIMIT 1").fetchone()
        assert curso is not None

        conn.execute("DELETE FROM matrizes_atividades WHERE nome = ?", (matrix_name,))
        conn.execute("DELETE FROM atividades WHERE nome = ?", (activity_name,))

        atividade_id = conn.execute(
            """
            INSERT INTO atividades (
                grupo, nome, limite_horas, tipo_atividade, tem_limitacao, tipo_limitacao,
                limite_horas_total, limite_horas_semestral, documentos_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            ("9 - Grupo Delete Test", activity_name, None, "Acadêmica Complementar", 0, None, None, None, None),
        ).fetchone()["id"]
        matriz_id = conn.execute(
            """
            INSERT INTO matrizes_atividades (
                curso_id, nome, versao, status, data_inicio_vigencia,
                horas_aac_obrigatorias, horas_extensao_obrigatorias, descricao
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (curso["id"], matrix_name, "2027.1", "vigente", "2027-01-01", 160, 80, "Teste delete atividade"),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO matrizes_atividades_itens (matriz_id, atividade_id) VALUES (?, ?)",
            (matriz_id, atividade_id),
        )
        conn.commit()

    _login_admin(client)

    response = client.post(f"/admin/deletar_atividade/{atividade_id}", follow_redirects=False)
    assert response.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        atividade = conn.execute("SELECT id FROM atividades WHERE id = ?", (atividade_id,)).fetchone()
        link = conn.execute(
            "SELECT id FROM matrizes_atividades_itens WHERE matriz_id = ? AND atividade_id = ?",
            (matriz_id, atividade_id),
        ).fetchone()
        matriz = conn.execute("SELECT id FROM matrizes_atividades WHERE id = ?", (matriz_id,)).fetchone()
        conn.execute("DELETE FROM matrizes_atividades WHERE id = ?", (matriz_id,))
        conn.commit()

        assert atividade is None
        assert link is None
        assert matriz is not None


def test_admin_deletar_atividade_blocks_when_requisicoes_exist(client):
    activity_name = "AAC Delete With Requisicao Test"
    email = "delete.atividade.requisicao@teste.local"
    matricula = "MAT-DELETE-ATIV-001"
    matrix_name = "Matriz Delete With Requisicao Test"

    with main.app.app_context():
        conn = main.get_db_connection()
        main.ensure_matrizes_atividades_table(conn)
        main.ensure_matriz_atividade_links_table(conn)
        main.ensure_turmas_matriz_schema(conn)

        curso = conn.execute("SELECT id, codigo FROM cursos ORDER BY id LIMIT 1").fetchone()
        assert curso is not None
        turma_codigo = main.gerar_codigo_turma(curso["codigo"], 91)

        conn.execute("DELETE FROM requisicoes WHERE aluno_id IN (SELECT id FROM alunos WHERE matricula = ?)", (matricula,))
        conn.execute("DELETE FROM alunos WHERE matricula = ?", (matricula,))
        conn.execute("DELETE FROM usuarios WHERE email = ?", (email,))
        conn.execute("DELETE FROM turmas WHERE codigo = ?", (turma_codigo,))
        conn.execute("DELETE FROM matrizes_atividades WHERE nome = ?", (matrix_name,))
        conn.execute("DELETE FROM atividades WHERE nome = ?", (activity_name,))

        atividade_id = conn.execute(
            """
            INSERT INTO atividades (
                grupo, nome, limite_horas, tipo_atividade, tem_limitacao, tipo_limitacao,
                limite_horas_total, limite_horas_semestral, documentos_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            ("9 - Grupo Delete Test", activity_name, None, "Acadêmica Complementar", 0, None, None, None, None),
        ).fetchone()["id"]
        matriz_id = conn.execute(
            """
            INSERT INTO matrizes_atividades (
                curso_id, nome, versao, status, data_inicio_vigencia,
                horas_aac_obrigatorias, horas_extensao_obrigatorias, descricao
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (curso["id"], matrix_name, "2027.1", "vigente", "2027-01-01", 160, 80, "Teste bloqueio delete atividade"),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO matrizes_atividades_itens (matriz_id, atividade_id) VALUES (?, ?)",
            (matriz_id, atividade_id),
        )
        turma_id = conn.execute(
            """
            INSERT INTO turmas (
                nome, ano, semestre, turno, status, numero, curso_id, matriz_id,
                ano_inicio, semestre_inicio, ano_fim, semestre_fim, codigo
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (turma_codigo, None, None, "Noite", "Ativa", 91, curso["id"], matriz_id, 2027, 1, 2030, 2, turma_codigo),
        ).fetchone()["id"]
        usuario_id = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo) VALUES (?, ?, ?, ?) RETURNING id",
            ("Aluno Delete Atividade", email, main.hash_password("aluno123"), "aluno"),
        ).fetchone()["id"]
        aluno_id = conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status) VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
            (usuario_id, "Aluno Delete Atividade", matricula, email, turma_id, "Ativo"),
        ).fetchone()["id"]
        conn.execute(
            """
            INSERT INTO requisicoes (
                aluno_id, atividade_id, data_solicitacao, data_evento, horas_solicitadas,
                nome_evento, status, horas_deferidas, observacao, arquivo_comprovante,
                data_processamento, admin_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (aluno_id, atividade_id, "2027-05-10 10:00:00", "2027-05-10", 4, "Evento delete", "Pendente", None, None, None, None, None),
        )
        conn.commit()

    _login_admin(client)

    response = client.post(f"/admin/deletar_atividade/{atividade_id}", follow_redirects=True)
    assert response.status_code == 200
    assert "Não é possível excluir a atividade porque ela está vinculada a 1 requisição." in response.get_data(as_text=True)

    with main.app.app_context():
        conn = main.get_db_connection()
        atividade = conn.execute("SELECT id FROM atividades WHERE id = ?", (atividade_id,)).fetchone()
        requisicoes = conn.execute("SELECT COUNT(*) FROM requisicoes WHERE atividade_id = ?", (atividade_id,)).fetchone()[0]
        conn.execute("DELETE FROM requisicoes WHERE atividade_id = ?", (atividade_id,))
        conn.execute("DELETE FROM alunos WHERE id = ?", (aluno_id,))
        conn.execute("DELETE FROM usuarios WHERE id = ?", (usuario_id,))
        conn.execute("DELETE FROM turmas WHERE id = ?", (turma_id,))
        conn.execute("DELETE FROM matrizes_atividades WHERE id = ?", (matriz_id,))
        conn.execute("DELETE FROM atividades WHERE id = ?", (atividade_id,))
        conn.commit()

        assert atividade is not None
        assert requisicoes == 1