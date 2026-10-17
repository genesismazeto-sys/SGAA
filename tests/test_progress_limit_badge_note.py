"""Student Progress: limit badge and event-date note (final review, items 2-3).

* Badge -- "N limites aplicados" beside the AAC/AEU chips counts the limits
  CONFIGURED on the activities those chips count: one per semester limit and
  one per total limit, i.e. the entries of each row's "Limite" column. It is
  never a count of limits reached; it is hidden when no listed activity has a
  limit. It reuses the card's existing neutral `.cfg-chip`.
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
    with isolated_versioned_app_env(tmp_path, "progress-badge.db") as value:
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


def test_badge_counts_configured_limits_with_singular_and_plural(env):
    client = env["client"]
    identity = _as_student(client)
    versions = _versions(identity)

    _limits()
    assert [text for _, text in _chips(_page(client))] == ["AAC: 26 atividades", "AEU: 5 atividades"]

    _limits((versions[0], 20, None))
    assert _chips(_page(client))[0] == ("cfg-chip", "1 limite aplicado")

    # One activity with both a semester and a total limit is two limits.
    _limits((versions[0], 10, 40))
    assert _chips(_page(client))[0] == ("cfg-chip", "2 limites aplicados")

    _limits((versions[0], 20, None), (versions[1], None, 100), (versions[2], 10, 40))
    chips = _chips(_page(client))
    assert chips[0] == ("cfg-chip", "4 limites aplicados")
    # Same chip owner as the neighbours, neutral variant: no new visual system.
    assert [cls for cls, _ in chips[1:]] == ["cfg-chip is-active progresso-type-count"] * 2


def test_badge_is_the_limite_column_not_the_limits_reached(env):
    client = env["client"]
    identity = _as_student(client)
    versions = _versions(identity)
    _limits((versions[0], 2, None), (versions[1], None, 100))
    before = _chips(_page(client))[0]

    login_admin(client)
    _, row = create_admin_request(client, "Badge reached", version_id=versions[0])
    client.post(f"/admin/processar_requisicao/{row['id']}", data={"status": "Deferida Parcialmente",
                                                                  "horas_deferidas": "2", "observacao": "ok"})
    _as_student(client)
    html = _page(client)
    assert "progresso-limitado" in html  # the limit is now reached (red cell)...
    assert _chips(html)[0] == before == ("cfg-chip", "2 limites aplicados")  # ...the count is not

    payload = client.get("/aluno/progresso?format=json").get_json()
    configured = sum((a["limite_horas_semestral"] is not None) + (a["limite_horas_total"] is not None)
                     for a in payload["atividades"] if a["tem_limitacao"])
    limite_cells = sum(len([part for part in a["limite"].split("; ") if part != "-"]) for a in payload["atividades"])
    assert configured == limite_cells == 2


def test_badge_spans_both_types_like_the_counts_beside_it(env):
    client = env["client"]
    identity = _as_student(client)
    aeu = [row[0] for row in _sql(
        "SELECT v.id FROM atividade_versao v WHERE v.eixo<>'AAC' AND v.id IN (%s)"
        % ",".join(str(v) for v in _versions(identity)))]
    aac = [v for v in _versions(identity) if v not in aeu]
    _limits((aac[0], 20, None), (aeu[0], None, 30))
    for query in ("", "?tipo=extensao"):
        assert _chips(_page(client, query))[0] == ("cfg-chip", "2 limites aplicados")


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
  const lines = el => { const r = document.createRange(); r.selectNodeContents(el);
    return new Set(Array.from(r.getClientRects()).map(x => Math.round(x.top))).size; };
  const card = box(document.querySelector('.progresso-block'));
  const badge = document.querySelector('.cfg-chips .cfg-chip');
  const note = document.querySelector('.progresso-type-note');
  const desc = document.querySelector('.progresso-type-text');
  const icon = note.querySelector('svg');
  const cols = () => Array.from(document.querySelector('.table-progresso').tHead.rows[0].cells).map(c => c.getBoundingClientRect().width);
  const withNote = cols();
  note.style.display = 'none'; const withoutNote = cols(); note.style.display = '';
  const ns = getComputedStyle(note), ds = getComputedStyle(desc);
  return {badge: badge.textContent.trim(), badgeLines: lines(badge), badgeClipped: badge.scrollWidth > badge.clientWidth + 1,
    badgeInside: box(badge).right <= card.right + 0.5,
    noteInside: box(note).left >= card.left && box(note).right <= card.right + 0.5,
    gap: box(note).top - box(desc).bottom, iconTop: box(icon).top - box(note).top, iconW: box(icon).width,
    noteFont: parseFloat(ns.fontSize), descFont: parseFloat(ds.fontSize), noteWeight: ns.fontWeight,
    colsEqual: JSON.stringify(withNote) === JSON.stringify(withoutNote),
    docOverflow: document.documentElement.scrollWidth > innerWidth};
})())"""


@browser
@pytest.mark.parametrize("width", [1440, 768, 640])
def test_badge_and_note_fit_and_leave_the_table_alone(env, width):
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
    assert geometry["badge"] == "4 limites aplicados"
    assert geometry["badgeLines"] == 1 and not geometry["badgeClipped"] and geometry["badgeInside"]
    assert geometry["noteInside"] and not geometry["docOverflow"]
    assert abs(geometry["gap"] - 6) < 0.5
    assert abs(geometry["iconTop"] - 1) < 0.5 and geometry["iconW"] == 16  # icon on the first line
    assert geometry["noteFont"] < geometry["descFont"] and geometry["noteWeight"] == "400"
    assert geometry["colsEqual"]
