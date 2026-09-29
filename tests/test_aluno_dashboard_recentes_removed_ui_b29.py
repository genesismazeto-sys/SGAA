"""UI-B29: the broken "Requisições Recentes" dashboard blocks are gone.

Product decision (2026-09-28): remove, do not rebuild. The two blocks never
rendered data since the repository's first commit (the page set
``cols_acad``/``cols_ext``, ``components/list_table.html`` reads ``cols``);
wiring them exposed an unfinished layout, "Deferidas (h)" showing requested
hours for Pendente requests, and raw status text. Minhas requisições stays the
authoritative list and the dashboard keeps linking to it.

Removed: the two <section>s, their page-local ``.recentes-table`` CSS and the
view data that existed only for them (``requisicoes_recentes``,
``requisicoes_recentes_acad``, ``requisicoes_recentes_ext``). Kept: every other
card and ``components/list_table.html`` (a DS table component).
"""
from __future__ import annotations

import datetime
import json
import re

import pytest
from flask import template_rendered

import main
from tests.canonical_request_test_support import login_student
from tests.cdp_browser_support import find_chromium
from tests.session_support import stamp_auth_version
from tests.versioned_test_support import isolated_versioned_app_env

AAC = "Acadêmica Complementar"
AEU = "Extensão Universitária"


@pytest.fixture
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "ui-b29.db") as environment:
        yield environment


def _student():
    with main.app.app_context():
        return dict(main.get_db_connection().execute(
            """SELECT a.id,a.usuario_id,t.matriz_id FROM alunos a
                 JOIN usuarios u ON u.id=a.usuario_id JOIN turmas t ON t.id=a.turma_id
                WHERE u.tipo='aluno' ORDER BY a.id LIMIT 1"""
        ).fetchone())


def _seed_one_of_each(client):
    """One Acadêmica (Pendente) and one Extensão request (Indeferida today),
    created through the real student route."""
    student = _student()
    with client.session_transaction() as session:
        session.clear()
        session.update(user_id=student["usuario_id"], user_type="aluno")
        stamp_auth_version(session)
    with main.app.app_context():
        conn = main.get_db_connection()
        versions = {
            eixo: dict(conn.execute(
                """SELECT v.id, v.grupo FROM matriz_atividade_versao_item item
                     JOIN atividade_versao v ON v.id=item.atividade_versao_id
                    WHERE item.matriz_id=? AND v.eixo=? AND v.status='ativa' ORDER BY v.id LIMIT 1""",
                (student["matriz_id"], eixo),
            ).fetchone())
            for eixo in ("AAC", "AEU")
        }
    for eixo, tipo in (("AAC", AAC), ("AEU", AEU)):
        response = client.post("/aluno/nova-requisicao", data={
            "tipo_atividade": tipo, "grupo": versions[eixo]["grupo"],
            "atividade_versao_id": str(versions[eixo]["id"]), "nome_evento": f"B29 {eixo}",
            "data_evento": "2026-08-20", "horas_solicitadas": "4",
            "comprovantes_operation_id": f"b29-{eixo}",
        }, content_type="multipart/form-data")
        assert response.status_code == 302
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "UPDATE requisicoes SET status='Indeferida', data_processamento=? WHERE nome_evento='B29 AEU'",
            (datetime.date.today().strftime("%Y-%m-%d"),),
        )
        conn.commit()


def _dashboard(client):
    captured = []

    def record(_sender, template, context, **_extra):
        if template.name == "aluno_dashboard.html":
            captured.append(set(context))

    template_rendered.connect(record, main.app)
    try:
        html = client.get("/aluno/dashboard").get_data(as_text=True)
    finally:
        template_rendered.disconnect(record, main.app)
    assert captured, "the dashboard template did not render"
    return html, captured[0]


def test_the_recent_request_blocks_and_their_data_are_gone(env):
    client = env["client"]
    _seed_one_of_each(client)
    html, context = _dashboard(client)
    assert "Requisições Recentes" not in html
    assert "recentes-table" not in html and "<table" not in html
    assert "Nenhum item encontrado." not in html
    assert not {key for key in context if key.startswith("requisicoes_recentes")}
    template = (main.app.root_path + "/../templates/aluno_dashboard.html")
    source = open(template, encoding="utf-8").read()
    assert "cols_acad" not in source and "cols_ext" not in source and "list_table" not in source


def test_every_surviving_card_and_count_is_unchanged(env):
    client = env["client"]
    _seed_one_of_each(client)
    html, _context = _dashboard(client)
    summary = dict(
        (label, int(value))
        for value, label in re.findall(
            r'<span class="value">(\d+)</span>\s*<span class="label"><i class="lucide" data-lucide="[^"]+"></i>([^<]+)</span>',
            html,
        )
    )
    assert summary == {"Total de requisições": 2, "Deferidas": 0, "Indeferidas": 1, "Pendentes": 1, "Corrigíveis": 1}
    for heading in (
        "Para Retificar - Acadêmicas Complementares", "Para Retificar - Extensão Universitária",
        "Limitações - Acadêmicas Complementares", "Limitações - Extensão Universitária",
    ):
        assert heading in html, heading
    extension = html.split("Para Retificar - Extensão Universitária", 1)[1].split("</section>", 1)[0]
    assert extension.count('class="corrigir-right-item"') == 1
    assert 'href="/aluno/requisicoes"' in html
    listing = client.get("/aluno/requisicoes")
    assert listing.status_code == 200
    page = listing.get_data(as_text=True)
    assert page.count('role="listitem"') == 2
    tipos = re.findall(r'<div class="cell left ellipsis">(Acadêmica Complementar|Extensão Universitária)</div>', page)
    assert sorted(tipos) == [AAC, AEU]


# ---------------------------------------------------------------- browser

CHROMIUM = find_chromium()


@pytest.mark.skipif(CHROMIUM is None, reason="no headless Chromium available")
@pytest.mark.parametrize("width,columns", [(1280, 2), (820, 1)])
def test_dashboard_grid_has_no_orphan_and_no_script_error(env, width, columns):
    from tests.test_file_upload_keyboard_ui_b26 import RecordingSession

    client = env["client"]
    _seed_one_of_each(client)
    session = RecordingSession(client, CHROMIUM)
    try:
        session.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": 1200, "deviceScaleFactor": 1, "mobile": False})
        session.goto("/aluno/dashboard")
        session.pump(0.5)
        grid = json.loads(session.evaluate("""JSON.stringify((() => {
          const grid = document.querySelector('.content-grid');
          const cards = Array.from(grid.children);
          const lefts = [...new Set(cards.map(c => Math.round(c.getBoundingClientRect().left)))];
          return {cards: cards.length, columns: lefts.length,
                  headings: cards.map(c => c.querySelector('.content-block-header').textContent.trim().replace(/\\s+/g, ' '))};
        })())"""))
    finally:
        session.close()
    assert grid["cards"] == 4 and grid["columns"] == columns
    assert [h.split(" - ")[0] for h in grid["headings"]] == ["Para Retificar", "Para Retificar", "Limitações", "Limitações"]
    errors = [
        event for event in session.events
        if event.get("method") == "Runtime.exceptionThrown"
        or (event.get("method") == "Runtime.consoleAPICalled" and event["params"].get("type") == "error")
    ]
    assert errors == []
