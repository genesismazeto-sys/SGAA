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


def test_admin_atividade_description_persists_on_create_and_edit(client):
    nome = "AAC Descricao Persistencia Teste"
    descricao_inicial = "Descricao adicional inicial"
    descricao_editada = "Descricao adicional editada"

    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("DELETE FROM atividades WHERE nome = ?", (nome,))
        conn.commit()

    _login_admin(client)

    create_response = client.post(
        "/admin/adicionar_atividade",
        data={
            "tipo_atividade": "Acadêmica Complementar",
            "grupo": "7 - Grupo Descricao Teste",
            "nome": nome,
            "descricao": descricao_inicial,
            "tem_limitacao": "0",
            "tipo_limitacao": "",
            "limite_horas_total": "",
            "limite_horas_semestral": "",
            "documentos_json": "",
        },
        follow_redirects=False,
    )
    assert create_response.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        atividade = conn.execute(
            "SELECT id, descricao FROM atividades WHERE nome = ?",
            (nome,),
        ).fetchone()
        assert atividade is not None
        assert atividade["descricao"] == descricao_inicial
        atividade_id = atividade["id"]

    edit_response = client.post(
        f"/admin/editar_atividade/{atividade_id}",
        data={
            "tipo_atividade": "Acadêmica Complementar",
            "grupo": "7 - Grupo Descricao Teste",
            "nome": nome,
            "descricao": descricao_editada,
            "tem_limitacao": "0",
            "tipo_limitacao": "",
            "limite_horas_total": "",
            "limite_horas_semestral": "",
            "documentos_json": "",
        },
        follow_redirects=False,
    )
    assert edit_response.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        atividade = conn.execute(
            "SELECT descricao FROM atividades WHERE id = ?",
            (atividade_id,),
        ).fetchone()
        conn.execute("DELETE FROM atividades WHERE id = ?", (atividade_id,))
        conn.commit()

        assert atividade is not None
        assert atividade["descricao"] == descricao_editada