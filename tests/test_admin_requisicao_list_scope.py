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


def test_admin_requisicoes_marks_items_outside_turma_matrix(client):
    allowed_name = "AAC Lista Scope Permitida"
    blocked_name = "AAC Lista Scope Bloqueada"
    email = "admin.list.scope@teste.local"
    matricula = "MAT-LISTA-SCOPE-001"
    matriz_nome = "Matriz Lista Scope"

    with main.app.app_context():
        conn = main.get_db_connection()
        main.ensure_matrizes_atividades_table(conn)
        main.ensure_matriz_atividade_links_table(conn)
        main.ensure_turmas_matriz_schema(conn)

        curso = conn.execute("SELECT id, codigo FROM cursos ORDER BY id LIMIT 1").fetchone()
        assert curso is not None
        turma_codigo = main.gerar_codigo_turma(curso["codigo"], 93)

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
            ("6 - Grupo Lista Scope", allowed_name, None, "Acadêmica Complementar", 0, None, None, None, None),
        ).fetchone()["id"]
        blocked_id = conn.execute(
            """
            INSERT INTO atividades (
                grupo, nome, limite_horas, tipo_atividade, tem_limitacao, tipo_limitacao,
                limite_horas_total, limite_horas_semestral, documentos_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            ("6 - Grupo Lista Scope", blocked_name, None, "Acadêmica Complementar", 0, None, None, None, None),
        ).fetchone()["id"]
        matriz_id = conn.execute(
            """
            INSERT INTO matrizes_atividades (
                curso_id, nome, versao, status, data_inicio_vigencia,
                horas_aac_obrigatorias, horas_extensao_obrigatorias, descricao
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (curso["id"], matriz_nome, "2029.1", "vigente", "2029-01-01", 160, 80, "Teste lista scope"),
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
            (turma_codigo, None, None, "Noite", "Ativa", 93, curso["id"], matriz_id, 2029, 1, 2032, 2, turma_codigo),
        ).fetchone()["id"]
        usuario_id = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo) VALUES (?, ?, ?, ?) RETURNING id",
            ("Aluno Lista Scope", email, main.hash_password("aluno123"), "aluno"),
        ).fetchone()["id"]
        aluno_id = conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status) VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
            (usuario_id, "Aluno Lista Scope", matricula, email, turma_id, "Ativo"),
        ).fetchone()["id"]
        conn.execute(
            """
            INSERT INTO requisicoes (
                aluno_id, atividade_id, data_solicitacao, data_evento, horas_solicitadas,
                nome_evento, status, horas_deferidas, observacao, arquivo_comprovante,
                data_processamento, admin_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (aluno_id, blocked_id, "2029-05-10 10:00:00", "2029-05-10", 4, "Evento lista", "Pendente", None, None, None, None, None),
        )
        conn.commit()

    _login_admin(client)

    response = client.get("/admin/requisicoes")
    assert response.status_code == 200
    html = response.data.decode("utf-8")
    assert "Fora da matriz" in html
    assert 'data-matrix-scope-issue="1"' in html


def test_admin_requisicoes_filter_schema_and_typed_filters(client):
    atividade_a = "Atividade Req Filtro Tipado A"
    atividade_b = "Atividade Req Filtro Tipado B"
    email = "admin.requisicoes.filtro@teste.local"
    matricula = "REQ-FLT-001"

    with main.app.app_context():
        conn = main.get_db_connection()
        main.ensure_turmas_matriz_schema(conn)

        curso = conn.execute("SELECT id, codigo FROM cursos ORDER BY id LIMIT 1").fetchone()
        assert curso is not None
        turma_codigo = main.gerar_codigo_turma(curso["codigo"], 94)

        conn.execute(
            "DELETE FROM requisicao_arquivos WHERE requisicao_id IN (SELECT id FROM requisicoes WHERE aluno_id IN (SELECT id FROM alunos WHERE matricula = ?))",
            (matricula,),
        )
        conn.execute("DELETE FROM requisicoes WHERE aluno_id IN (SELECT id FROM alunos WHERE matricula = ?)", (matricula,))
        conn.execute("DELETE FROM alunos WHERE matricula = ?", (matricula,))
        conn.execute("DELETE FROM usuarios WHERE email = ?", (email,))
        conn.execute("DELETE FROM turmas WHERE codigo = ?", (turma_codigo,))
        conn.execute("DELETE FROM atividades WHERE nome IN (?, ?)", (atividade_a, atividade_b))

        atividade_a_id = conn.execute(
            """
            INSERT INTO atividades (
                grupo, nome, limite_horas, tipo_atividade, tem_limitacao, tipo_limitacao,
                limite_horas_total, limite_horas_semestral, documentos_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            ("7 - Grupo Req Filtro", atividade_a, None, "Acadêmica Complementar", 0, None, None, None, None),
        ).fetchone()["id"]
        atividade_b_id = conn.execute(
            """
            INSERT INTO atividades (
                grupo, nome, limite_horas, tipo_atividade, tem_limitacao, tipo_limitacao,
                limite_horas_total, limite_horas_semestral, documentos_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            ("7 - Grupo Req Filtro", atividade_b, None, "Acadêmica Complementar", 0, None, None, None, None),
        ).fetchone()["id"]
        turma_id = conn.execute(
            """
            INSERT INTO turmas (
                nome, ano, semestre, turno, status, numero, curso_id, matriz_id,
                ano_inicio, semestre_inicio, ano_fim, semestre_fim, codigo
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (turma_codigo, None, None, "Noite", "Ativa", 94, curso["id"], None, 2031, 1, 2034, 2, turma_codigo),
        ).fetchone()["id"]
        usuario_id = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo) VALUES (?, ?, ?, ?) RETURNING id",
            ("Aluno Req Filtro", email, main.hash_password("aluno123"), "aluno"),
        ).fetchone()["id"]
        aluno_id = conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status) VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
            (usuario_id, "Aluno Req Filtro", matricula, email, turma_id, "Ativo"),
        ).fetchone()["id"]

        req_a_id = conn.execute(
            """
            INSERT INTO requisicoes (
                aluno_id, atividade_id, data_solicitacao, data_evento, horas_solicitadas,
                nome_evento, status, horas_deferidas, observacao, arquivo_comprovante,
                data_processamento, admin_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (
                aluno_id,
                atividade_a_id,
                "2031-03-10 10:00:00",
                "2031-03-09",
                8,
                "Evento Req Filtro A",
                "Deferida",
                8,
                "Filtro A",
                None,
                "2031-03-12 09:30:00",
                1,
            ),
        ).fetchone()["id"]
        req_b_id = conn.execute(
            """
            INSERT INTO requisicoes (
                aluno_id, atividade_id, data_solicitacao, data_evento, horas_solicitadas,
                nome_evento, status, horas_deferidas, observacao, arquivo_comprovante,
                data_processamento, admin_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (
                aluno_id,
                atividade_b_id,
                "2031-04-10 10:00:00",
                "2031-04-09",
                4,
                "Evento Req Filtro B",
                "Pendente",
                None,
                "Filtro B",
                None,
                None,
                None,
            ),
        ).fetchone()["id"]
        conn.commit()

    _login_admin(client)

    response = client.get(
        "/admin/requisicoes",
        query_string={
            "data_solicitacao_min": "2031-03-01",
            "data_solicitacao_max": "2031-03-31",
            "data_processamento_min": "2031-03-01",
            "data_processamento_max": "2031-03-31",
            "processamento": "com_data",
            "aluno": "Aluno Req Filtro",
            "turma": turma_codigo,
            "tipo": "Acadêmica Complementar",
            "grupo": "7 - Grupo Req Filtro",
            "atividade": atividade_a,
            "status": "deferida",
        },
    )
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert '"param": "data_solicitacao"' in html
    assert '"param": "data_processamento"' in html
    assert '"param": "processamento"' in html
    assert '"param": "aluno"' in html
    assert '"type": "date_range"' in html
    assert '"type": "multi_select"' in html

    assert f'data-req-id="{req_a_id}"' in html
    assert f'data-req-id="{req_b_id}"' not in html
