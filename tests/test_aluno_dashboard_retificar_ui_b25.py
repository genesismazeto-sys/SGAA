"""UI-B25: the student dashboard says "Para Retificar", not "Para Corrigir".

Copy only: the two card headings over the retifiable requests (Indeferida,
processed less than 30 days ago). Which requests appear, their count, the
days-remaining bars and the link to Minhas requisições are unchanged.
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


def test_retifiable_request_count_list_and_link_are_unchanged(client):
    login_admin(client)
    _response, created = create_admin_request(client, name="Retificar B25")
    today = datetime.date.today().strftime("%Y-%m-%d")
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "UPDATE requisicoes SET status='Indeferida', data_processamento=? WHERE id=?",
            (today, created["id"]),
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
    assert academic.count('class="corrigir-right-item"') == 1
    assert ">30/30<" in academic
    assert "Nenhuma requisição corrigível de extensão." in extension
    for block in (academic, extension):
        assert 'href="/aluno/requisicoes"' in block
