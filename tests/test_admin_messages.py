import os
import sys

import pytest


BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main
from utils.messages import (
    frontend_message_templates,
    list_editable_messages,
    message_key_for_default,
    resolve_user_message,
)


@pytest.fixture(scope="module")
def client():
    app = main.app
    with app.app_context():
        main.init_db()
    with app.test_client() as client:
        yield client


def _login_admin(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["user_type"] = "admin"
        sess["user_name"] = "Administrador"


def test_admin_messages_page_lists_backend_and_frontend_messages(client):
    _login_admin(client)

    response = client.get("/admin/mensagens")
    assert response.status_code == 200

    html = response.get_data(as_text=True)
    assert "Mensagens" in html
    assert "Aluno não encontrado." in html
    assert "Tem certeza que deseja excluir o aluno selecionado?" in html
    assert "Tem certeza que deseja excluir os {value_1} alunos selecionados?" in html
    assert "excluir aluno" in html


def test_admin_messages_generate_flow_headers_for_backend_and_frontend(client):
    _login_admin(client)

    with main.app.app_context():
        conn = main.get_db_connection()
        messages = list_editable_messages(conn)

    by_default = {item["default_text"]: item for item in messages}

    backend = by_default.get("Erro ao criar curso: {value_1}")
    assert backend is not None
    assert backend["display_area"] == "Cursos"
    assert backend["display_flow"] == "Criar curso"
    assert backend["display_state"] == "erro"
    assert backend["display_title"] == "Cursos > criar curso > erro"

    frontend = by_default.get("Tem certeza que deseja excluir o aluno selecionado?")
    assert frontend is not None
    assert frontend["display_flow"] == "Excluir aluno"
    assert frontend["display_state"] == "confirmação"
    assert frontend["display_title"].endswith(" > excluir aluno > confirmação")


def test_admin_messages_can_override_static_and_dynamic_templates(client):
    _login_admin(client)

    static_default = "Aluno não encontrado."
    dynamic_default = "Erro ao criar curso: {value_1}"
    static_key = message_key_for_default(static_default)
    dynamic_key = message_key_for_default(dynamic_default)

    with main.app.app_context():
        conn = main.get_db_connection()
        keys = {item["key"] for item in list_editable_messages(conn)}
        assert static_key in keys
        assert dynamic_key in keys

    save_static = client.post(
        "/admin/mensagens/salvar",
        data={"message_key": static_key, "message_text": "Aluno ainda não foi localizado."},
        follow_redirects=False,
    )
    assert save_static.status_code in (302, 303)

    save_dynamic = client.post(
        "/admin/mensagens/salvar",
        data={"message_key": dynamic_key, "message_text": "Falha ao criar curso. Detalhe: {value_1}"},
        follow_redirects=False,
    )
    assert save_dynamic.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        assert resolve_user_message(static_default, conn=conn) == "Aluno ainda não foi localizado."
        assert resolve_user_message("Erro ao criar curso: código duplicado", conn=conn) == "Falha ao criar curso. Detalhe: código duplicado"

        frontend_templates = frontend_message_templates(conn)
        assert frontend_templates["Tem certeza que deseja excluir o aluno selecionado?"] == "Tem certeza que deseja excluir o aluno selecionado?"

    reset_static = client.post(f"/admin/mensagens/{static_key}/reset", follow_redirects=False)
    reset_dynamic = client.post(f"/admin/mensagens/{dynamic_key}/reset", follow_redirects=False)
    assert reset_static.status_code in (302, 303)
    assert reset_dynamic.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        assert resolve_user_message(static_default, conn=conn) == static_default
        assert resolve_user_message("Erro ao criar curso: código duplicado", conn=conn) == "Erro ao criar curso: código duplicado"


def test_admin_messages_override_updates_rendered_ui_for_helper_generated_flash(client):
    _login_admin(client)

    default_text = "Informe o nome da matriz."
    override_text = "Defina um nome para a matriz antes de continuar."
    message_key = message_key_for_default(default_text)

    with main.app.app_context():
        conn = main.get_db_connection()
        keys = {item["key"] for item in list_editable_messages(conn)}
        assert message_key in keys
        course_row = conn.execute("SELECT id FROM cursos ORDER BY id LIMIT 1").fetchone()
        assert course_row is not None
        course_id = course_row["id"]

    save_override = client.post(
        "/admin/mensagens/salvar",
        data={"message_key": message_key, "message_text": override_text},
        follow_redirects=False,
    )
    assert save_override.status_code in (302, 303)

    response = client.post(
        "/admin/adicionar_matriz",
        data={
            "curso_id": course_id,
            "nome": "",
            "versao": "2026.1",
            "status": "rascunho",
            "horas_aac_obrigatorias": 0,
            "horas_extensao_obrigatorias": 0,
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert override_text in html
    assert default_text not in html

    reset_override = client.post(f"/admin/mensagens/{message_key}/reset", follow_redirects=False)
    assert reset_override.status_code in (302, 303)

    reverted = client.post(
        "/admin/adicionar_matriz",
        data={
            "curso_id": course_id,
            "nome": "",
            "versao": "2026.1",
            "status": "rascunho",
            "horas_aac_obrigatorias": 0,
            "horas_extensao_obrigatorias": 0,
        },
        follow_redirects=True,
    )
    assert reverted.status_code == 200
    reverted_html = reverted.get_data(as_text=True)
    assert default_text in reverted_html