"""Student Progress: the event-date note, and no "limites aplicados" badge.

* The "N limites aplicados" chip (final review) is withdrawn (UI batch 4): a
  count of CONFIGURED limits beside the AAC/AEU chips reads as a count of
  limits REACHED. Nothing replaces it; the AAC/AEU chips, the Limite column,
  the red cells and every limit calculation are untouched.
* Note -- the DS `.form-note` with the Lucide `info` icon under the section
  description, stating that semester limits follow the event date.
Neither changes a progress calculation, the red cells or the JSON payload.
"""
from __future__ import annotations

import json
import re

import pytest

import main
from tests.canonical_request_test_support import create_admin_request, login_admin, student_identity
from tests.cdp_browser_support import BrowserSession, find_chromium
from tests.session_support import stamp_auth_version
from tests.versioned_test_support import isolated_versioned_app_env

NOTE = ("Limites por semestre são contados pelo semestre da <strong>data do evento</strong>, "
        "não pela data de envio da requisição.")
CHROMIUM = find_chromium()
browser = pytest.mark.skipif(CHROMIUM is None, reason="no headless Chromium available")


@pytest.fixture()
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "progress-note.db") as value:
        yield value


def _sql(query, params=()):
    with main.app.app_context():
        conn = main.get_db_connection()
        rows = conn.execute(query, params).fetchall()
        conn.commit()
        return rows


def _as_student(client):
    identity = student_identity()
    with client.session_transaction() as session:
        session.clear()
        session.update(user_id=identity["usuario_id"], user_type="aluno", user_name="Aluno")
        stamp_auth_version(session)
    return identity


def _versions(identity):
    return sorted(row[0] for row in _sql(
        """SELECT item.atividade_versao_id FROM alunos a JOIN turmas t ON t.id=a.turma_id
             JOIN matriz_atividade_versao_item item ON item.matriz_id=t.matriz_id WHERE a.id=?""",
        (identity["aluno_id"],)))


def _limits(*rules):
    """Clear every limit, then apply (version_id, semester, total) rules."""
    _sql("UPDATE atividade_versao SET limite_semestre=NULL, limite_total=NULL")
    for version_id, semestre, total in rules:
        _sql("UPDATE atividade_versao SET limite_semestre=?, limite_total=? WHERE id=?",
             (semestre, total, version_id))


def _chips(html):
    head = html.split('<div class="cfg-chips"', 1)[1].split("</div>", 1)[0]
    return re.findall(r'<span class="([^"]+)">([^<]+)</span>', head)


def _page(client, query=""):
    return client.get(f"/aluno/progresso{query}").get_data(as_text=True)


def test_no_limits_badge_whatever_the_configured_limits(env):
    client = env["client"]
    identity = _as_student(client)
    versions = _versions(identity)
    for rules in ((), ((versions[0], 20, None),), ((versions[0], 10, 40), (versions[1], None, 100))):
        _limits(*rules)
        for query in ("", "?tipo=extensao"):
            html = _page(client, query)
            # The AAC/AEU counts stay exactly as they were, and nothing joins them.
            assert _chips(html) == [("cfg-chip is-active progresso-type-count", "AAC: 26 atividades"),
                                    ("cfg-chip is-active progresso-type-count", "AEU: 5 atividades")]
            assert "limite aplicado" not in html and "limites aplicados" not in html


def test_reached_limit_keeps_its_red_cell_and_adds_no_indicator(env):
    client = env["client"]
    identity = _as_student(client)
    versions = _versions(identity)
    _limits((versions[0], 2, None), (versions[1], None, 100))
    login_admin(client)
    _, row = create_admin_request(client, "Limit reached", version_id=versions[0])
    client.post(f"/admin/processar_requisicao/{row['id']}", data={"status": "Deferida Parcialmente",
                                                                  "horas_deferidas": "2", "observacao": "ok"})
    _as_student(client)
    html = _page(client)
    assert "progresso-limitado" in html  # the red cell still marks the reached limit
    assert [text for _, text in _chips(html)] == ["AAC: 26 atividades", "AEU: 5 atividades"]
    assert "limites aplicados" not in html and "limite aplicado" not in html


def test_progress_view_no_longer_computes_a_limits_count():
    source = open("app/views/aluno.py", encoding="utf-8").read()
    template = open("templates/aluno_progresso.html", encoding="utf-8").read()
    assert "limites_aplicados" not in source and "limites_aplicados" not in template


def test_progress_json_payload_gains_no_field(env):
    client = env["client"]
    _as_student(client)
    payload = client.get("/aluno/progresso?format=json").get_json()
    assert set(payload) == {"semestres", "atividades", "has_extensao_na_matriz", "has_aac_visivel",
                            "has_extensao_visivel"}
    assert all("limites_aplicados" not in key for item in payload["atividades"] for key in item)


def test_note_is_a_ds_form_note_under_the_description_on_both_types(env):
    client = env["client"]
    _as_student(client)
    for query in ("", "?tipo=extensao"):
        header = _page(client, query).split('<div class="progresso-type-header">', 1)[1]
        header = header.split('<div class="progresso-table-shell">', 1)[0]
        assert re.search(
            r'<p class="progresso-type-text">[^<]+</p>\s*'
            r'<div class="form-note progresso-type-note"><i class="lucide" data-lucide="info" aria-hidden="true"></i>'
            r'<span>' + re.escape(NOTE) + r'</span></div>\s*</div>', header), query
    template = open("templates/aluno_progresso.html", encoding="utf-8").read()
    # Spacing/alignment only: no colour, font or border of its own.
    rules = re.findall(r"\.progresso-type-note[^{]*\{([^}]*)\}", template)
    assert rules and not re.search(r"color|font|border|background", " ".join(rules))


def _session(client, width):
    session = BrowserSession(client, CHROMIUM)
    session.call("Emulation.setDeviceMetricsOverride",
                 {"width": width, "height": 900, "deviceScaleFactor": 1, "mobile": False})
    return session


GEOMETRY = """JSON.stringify((() => {
  const box = el => el.getBoundingClientRect();
  const card = box(document.querySelector('.progresso-block'));
  const note = document.querySelector('.progresso-type-note');
  const desc = document.querySelector('.progresso-type-text');
  const icon = note.querySelector('svg');
  const cols = () => Array.from(document.querySelector('.table-progresso').tHead.rows[0].cells).map(c => c.getBoundingClientRect().width);
  const withNote = cols();
  note.style.display = 'none'; const withoutNote = cols(); note.style.display = '';
  const ns = getComputedStyle(note), ds = getComputedStyle(desc);
  return {chips: Array.from(document.querySelectorAll('.cfg-chips .cfg-chip')).map(c => c.textContent.trim()),
    noteInside: box(note).left >= card.left && box(note).right <= card.right + 0.5,
    gap: box(note).top - box(desc).bottom, iconTop: box(icon).top - box(note).top, iconW: box(icon).width,
    noteFont: parseFloat(ns.fontSize), descFont: parseFloat(ds.fontSize), noteWeight: ns.fontWeight,
    colsEqual: JSON.stringify(withNote) === JSON.stringify(withoutNote),
    docOverflow: document.documentElement.scrollWidth > innerWidth};
})())"""


@browser
@pytest.mark.parametrize("width", [1440, 768, 640])
def test_note_fits_and_leaves_the_table_alone(env, width):
    client = env["client"]
    identity = _as_student(client)
    versions = _versions(identity)
    _limits((versions[0], 20, None), (versions[1], None, 100), (versions[2], 10, 40))
    session = _session(client, width)
    try:
        session.goto("/aluno/progresso")
        geometry = json.loads(session.evaluate(GEOMETRY))
    finally:
        session.close()
    assert geometry["chips"] == ["AAC: 26 atividades", "AEU: 5 atividades"]
    assert geometry["noteInside"] and not geometry["docOverflow"]
    assert abs(geometry["gap"] - 6) < 0.5
    assert abs(geometry["iconTop"] - 1) < 0.5 and geometry["iconW"] == 16  # icon on the first line
    assert geometry["noteFont"] < geometry["descFont"] and geometry["noteWeight"] == "400"
    assert geometry["colsEqual"]
