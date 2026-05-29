import os
import sys

import pytest
from flask import render_template

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


def test_admin_matrizes_page_includes_csrf_for_dynamic_delete_forms(client):
    _login_admin(client)

    response = client.get("/admin/matrizes")
    assert response.status_code == 200

    html = response.get_data(as_text=True)
    assert '<meta name="csrf-token"' in html
    assert "const csrfToken = document.querySelector('meta[name=\"csrf-token\"]')" in html
    assert html.count("appendCsrfToken(form);") >= 2


def test_invalid_request_page_uses_standard_card_actions():
    with main.app.test_request_context("/admin/matrizes", headers={"Referer": "/admin/matrizes"}):
        html = render_template("400.html", mensagem="Mensagem de validação")

    assert "request-error-card" in html
    assert "request-error-title" in html
    assert "Abrir tela anterior" in html
    assert 'href="/admin/matrizes"' in html
    assert 'href="/"' in html