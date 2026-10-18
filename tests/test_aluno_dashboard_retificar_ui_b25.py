"""UI-B25: the student dashboard says "Para Retificar", not "Para Corrigir".

Copy only: the two card headings over the retifiable requests. Which requests
appear is no longer UI-B25's 30-day Indeferida rule: they are the Devolvida
requests inside the configured return deadline (default 7 days), each with its
Retificar action; an Indeferida request is final and never listed
(tests/test_request_rectification_flow.py owns that contract).
"""
from __future__ import annotations

import datetime
import re

import pytest

import main
from tests.canonical_request_test_support import create_admin_request, login_admin, login_student
from tests.versioned_test_support import isolated_versioned_app_env


@pytest.fixture
def client(tmp_path):
    with isolated_versioned_app_env(tmp_path, "ui-b25.db") as env:
        yield env["client"]


def _block(html: str, title: str) -> str:
    match = re.search(
        r"<span>" + re.escape(title) + r"</span>(.*?)</section>", html, re.S
    )
    assert match, f"card {title!r} is gone"
    return match.group(1)


def test_dashboard_headings_say_para_retificar(client):
    login_student(client)
    html = client.get("/aluno/dashboard").get_data(as_text=True)
    assert "Para Retificar - Acadêmicas Complementares" in html
    assert "Para Retificar - Extensão Universitária" in html
    assert "Para Corrigir" not in html and "para corrigir" not in html.lower()


def test_retifiable_request_count_list_and_link(client):
    login_admin(client)
    _response, created = create_admin_request(client, name="Retificar B25")
    _response, rejected = create_admin_request(client, name="Indeferida B25")
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "UPDATE requisicoes SET status='Devolvida', data_processamento=? WHERE id=?",
            (now, created["id"]),
        )
        conn.execute(
            "UPDATE requisicoes SET status='Indeferida', data_processamento=? WHERE id=?",
            (now, rejected["id"]),
        )
        conn.commit()
    with client.session_transaction() as session:
        session.clear()
    login_student(client)
    html = client.get("/aluno/dashboard").get_data(as_text=True)

    kpi = re.search(r'<span class="value">(\d+)</span>\s*<span class="label"><i class="lucide" data-lucide="edit"></i>Corrigíveis</span>', html)
    assert kpi and kpi.group(1) == "1"
    academic = _block(html, "Para Retificar - Acadêmicas Complementares")
    extension = _block(html, "Para Retificar - Extensão Universitária")
    assert academic.count('class="retificar-item"') == 1
    assert ">7/7<" in academic
    assert f'href="/aluno/requisicoes/{created["id"]}?edit=1"' in academic
    assert f'/aluno/requisicoes/{rejected["id"]}?edit=1' not in html
    assert "Nenhuma requisição corrigível de extensão." in extension
    for block in (academic, extension):
        assert 'href="/aluno/requisicoes"' in block
