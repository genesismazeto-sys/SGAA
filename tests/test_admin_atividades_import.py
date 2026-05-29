import io
import os
import re
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


def test_admin_atividades_import_preview_and_confirm(client):
    nome_novo = "Atividade CSV Teste Nova"
    nome_existente = "Atividade CSV Teste Existente"

    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("DELETE FROM atividades WHERE nome IN (?, ?)", (nome_novo, nome_existente))
        conn.execute(
            """
            INSERT INTO atividades (
                grupo,
                nome,
                limite_horas,
                tipo_atividade,
                tem_limitacao,
                tipo_limitacao,
                limite_horas_total,
                limite_horas_semestral,
                documentos_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("1 - Grupo Inicial", nome_existente, None, "Acadêmica Complementar", 0, "total", None, None, None),
        )
        conn.commit()

    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["user_type"] = "admin"
        sess["user_name"] = "Administrador"

    csv_content = "\n".join(
        [
            "nome;tipo_atividade;grupo_numero;grupo_descricao;tem_limitacao;tipo_limitacao;limite_horas_total;limite_horas_semestral",
            f"{nome_novo};Acadêmica Complementar;7;Grupo Novo;sim;total;12;",
            f"{nome_existente};Extensão Universitária;8;Grupo Atualizado;sim;semestral;;15",
        ]
    )

    response = client.post(
        "/admin/atividades/importar/preview",
        data={
            "mode": "upsert",
            "csv_arquivo": (io.BytesIO(csv_content.encode("utf-8")), "atividades.csv"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Confirmar importação" in html
    match = re.search(r'name="preview_key" value="([^"]+)"', html)
    assert match is not None

    confirm = client.post(
        "/admin/atividades/importar/confirmar",
        data={"preview_key": match.group(1)},
        follow_redirects=False,
    )
    assert confirm.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        nova = conn.execute(
            "SELECT grupo, tipo_atividade, tem_limitacao, tipo_limitacao, limite_horas_total FROM atividades WHERE nome = ?",
            (nome_novo,),
        ).fetchone()
        existente = conn.execute(
            "SELECT grupo, tipo_atividade, tem_limitacao, tipo_limitacao, limite_horas_semestral FROM atividades WHERE nome = ?",
            (nome_existente,),
        ).fetchone()

        assert nova is not None
        assert nova["grupo"] == "7 - Grupo Novo"
        assert nova["tipo_atividade"] == "Acadêmica Complementar"
        assert nova["tem_limitacao"] == 1
        assert nova["tipo_limitacao"] == "total"
        assert nova["limite_horas_total"] == 12

        assert existente is not None
        assert existente["grupo"] == "8 - Grupo Atualizado"
        assert existente["tipo_atividade"] == "Extensão Universitária"
        assert existente["tem_limitacao"] == 1
        assert existente["tipo_limitacao"] == "semestral"
        assert existente["limite_horas_semestral"] == 15

        conn.execute("DELETE FROM atividades WHERE nome IN (?, ?)", (nome_novo, nome_existente))
        conn.execute(
            "DELETE FROM grupos_def WHERE (tipo_atividade = ? AND numero IN (?, ?)) OR (tipo_atividade = ? AND numero IN (?, ?))",
            ("Acadêmica Complementar", 7, 8, "Extensão Universitária", 7, 8),
        )
        conn.commit()