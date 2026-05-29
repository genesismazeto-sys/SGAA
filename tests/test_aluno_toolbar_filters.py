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
    with app.test_client() as client:
        yield client


def _login_aluno(client, usuario_id: int, nome: str):
    with client.session_transaction() as sess:
        sess["user_id"] = usuario_id
        sess["user_type"] = "aluno"
        sess["user_name"] = nome


def test_aluno_arquivos_filter_schema_and_typed_filters(client):
    email = "aluno.arquivos.filtro@teste.local"
    matricula = "ARQ-FLT-001"
    titulo_a = "Arquivo Aluno Filtro Tipado A"
    titulo_b = "Arquivo Aluno Filtro Tipado B"

    with main.app.app_context():
        conn = main.get_db_connection()
        main.ensure_admin_arquivos_table(conn)

        conn.execute("DELETE FROM admin_arquivos WHERE titulo IN (?, ?)", (titulo_a, titulo_b))
        conn.execute("DELETE FROM alunos WHERE matricula = ?", (matricula,))
        conn.execute("DELETE FROM usuarios WHERE email = ?", (email,))

        usuario_id = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo) VALUES (?, ?, ?, ?) RETURNING id",
            ("Aluno Filtro Arquivos", email, main.hash_password("aluno123"), "aluno"),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, status) VALUES (?, ?, ?, ?, ?)",
            (usuario_id, "Aluno Filtro Arquivos", matricula, email, "Ativo"),
        )

        conn.execute(
            """
            INSERT INTO admin_arquivos (titulo, descricao, filename, original_filename, visivel, criado_em)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                titulo_a,
                "Descricao aluno alfa",
                "admin_arquivos/aluno_filtro_a.pdf",
                "aluno-filtro-a.pdf",
                1,
                "2032-01-10 10:00:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO admin_arquivos (titulo, descricao, filename, original_filename, visivel, criado_em)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                titulo_b,
                "Descricao aluno beta",
                "admin_arquivos/aluno_filtro_b.png",
                "aluno-filtro-b.png",
                1,
                "2032-02-15 10:00:00",
            ),
        )
        conn.commit()

    _login_aluno(client, usuario_id, "Aluno Filtro Arquivos")

    response = client.get(
        "/aluno/arquivos",
        query_string={
            "titulo": "Tipado A",
            "descricao": "alfa",
            "tipo": "PDF",
            "data_upload_min": "2032-01-01",
            "data_upload_max": "2032-01-31",
        },
    )
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert '"param": "titulo"' in html
    assert '"param": "descricao"' in html
    assert '"param": "data_upload"' in html
    assert '"param": "tipo"' in html
    assert '"type": "text_contains"' in html
    assert '"type": "date_range"' in html
    assert '"type": "multi_select"' in html

    assert titulo_a in html
    assert titulo_b not in html


def test_aluno_requisicoes_filter_schema_and_typed_filters(client):
    email = "aluno.requisicoes.filtro@teste.local"
    matricula = "REQ-ALUNO-FLT-001"
    atividade_a = "Atividade Aluno Filtro Tipado A"
    atividade_b = "Atividade Aluno Filtro Tipado B"

    with main.app.app_context():
        conn = main.get_db_connection()

        conn.execute(
            "DELETE FROM requisicao_arquivos WHERE requisicao_id IN (SELECT id FROM requisicoes WHERE aluno_id IN (SELECT id FROM alunos WHERE matricula = ?))",
            (matricula,),
        )
        conn.execute("DELETE FROM requisicoes WHERE aluno_id IN (SELECT id FROM alunos WHERE matricula = ?)", (matricula,))
        conn.execute("DELETE FROM atividades WHERE nome IN (?, ?)", (atividade_a, atividade_b))
        conn.execute("DELETE FROM alunos WHERE matricula = ?", (matricula,))
        conn.execute("DELETE FROM usuarios WHERE email = ?", (email,))

        atividade_a_id = conn.execute(
            """
            INSERT INTO atividades (
                grupo, nome, limite_horas, tipo_atividade, tem_limitacao, tipo_limitacao,
                limite_horas_total, limite_horas_semestral, documentos_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            ("8 - Grupo Aluno Filtro", atividade_a, None, "Acadêmica Complementar", 0, None, None, None, None),
        ).fetchone()["id"]
        atividade_b_id = conn.execute(
            """
            INSERT INTO atividades (
                grupo, nome, limite_horas, tipo_atividade, tem_limitacao, tipo_limitacao,
                limite_horas_total, limite_horas_semestral, documentos_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            ("8 - Grupo Aluno Filtro", atividade_b, None, "Acadêmica Complementar", 0, None, None, None, None),
        ).fetchone()["id"]

        usuario_id = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo) VALUES (?, ?, ?, ?) RETURNING id",
            ("Aluno Filtro Requisicoes", email, main.hash_password("aluno123"), "aluno"),
        ).fetchone()["id"]
        aluno_id = conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, status) VALUES (?, ?, ?, ?, ?) RETURNING id",
            (usuario_id, "Aluno Filtro Requisicoes", matricula, email, "Ativo"),
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
                "2032-03-18 10:00:00",
                "2032-03-15",
                12,
                "Evento Aluno Filtro A",
                "Deferida",
                10,
                "Filtro A",
                None,
                "2032-03-20 11:00:00",
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
                "2032-05-18 10:00:00",
                "2032-05-10",
                3,
                "Evento Aluno Filtro B",
                "Pendente",
                0,
                "Filtro B",
                None,
                None,
                None,
            ),
        ).fetchone()["id"]
        conn.commit()

    _login_aluno(client, usuario_id, "Aluno Filtro Requisicoes")

    response = client.get(
        "/aluno/requisicoes",
        query_string={
            "data_evento_min": "2032-03-01",
            "data_evento_max": "2032-03-31",
            "data_processamento_min": "2032-03-01",
            "data_processamento_max": "2032-03-31",
            "horas_solicitadas_min": "10",
            "horas_deferidas_min": "8",
            "processamento": "com_data",
            "tipo": "Acadêmica Complementar",
            "grupo": "8 - Grupo Aluno Filtro",
            "atividade": atividade_a,
            "status": "Deferida",
        },
    )
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert '"param": "data_evento"' in html
    assert '"param": "data_processamento"' in html
    assert '"param": "horas_solicitadas"' in html
    assert '"param": "horas_deferidas"' in html
    assert '"param": "processamento"' in html
    assert '"type": "date_range"' in html
    assert '"type": "number_range"' in html
    assert '"type": "multi_select"' in html

    assert f'data-req-id="{req_a_id}"' in html
    assert f'data-req-id="{req_b_id}"' not in html
