"""Student experience UI corrections, batch 1.

1. The student sidebar reads Painel, Requisições, Progresso, Arquivos, then the
   rest, each link keeping its route, icon and active-state semantics.
2. The "Nome do evento" guidance carries the owner-approved text, and both
   guidance notes are justified (every line but the last reaches the right edge).
3. Empty upload feedback (the direct-upload list and its status line, both live
   regions) holds no form rows open: Comprovantes -> Observação is one row-gap,
   and while an upload is listed the feedback sits pulled up under its card.
4. The Atividade select. A native popup is placed by the browser (one wider
   than the room to the right of the select is right-aligned to it, far to
   the left of the field). Where the customizable select exists, the same
   <select> opens a CSS picker anchored to the field: measured OPEN, it spans
   the card, opens next to it, wraps long names and stays in the viewport;
   mouse, keyboard (Enter / arrows / Escape), focus, filtering, edit-mode
   selection and submission are the native element's. With the feature
   absent the @supports block is skipped and the native control renders with
   the same geometry. Always pinned: the select fills its card with no
   transformed or zoomed ancestor.
5. Progress shows "Tempo padrão" (the version's ch_por_evento) between Grupo and
   Limite: catalogue rows read the matrix version, history-only rows read the
   frozen snapshot, an undefined value shows "-", and nothing it adds changes a
   progress calculation.
"""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from urllib.parse import parse_qs

import pytest

import main
from app.views.aluno import _build_aluno_progresso_payload
from tests.canonical_request_documents_support import (
    INTENT_IDS_FIELD,
    SUBMISSION_FIELD,
    canonical_documents,
    form_submission,
    upload_verified,
)
from tests.canonical_request_test_support import create_admin_request, login_admin, student_identity
from tests.cdp_browser_support import BrowserSession, find_chromium
from tests.session_support import stamp_auth_version
from tests.test_comprovantes_google_drive import PDF, PNG, FakeStorage
from tests.versioned_test_support import isolated_versioned_app_env

NOME_GUIDANCE = (
    "Informe o nome exatamente como consta no comprovante — não o nome genérico da atividade como "
    "aparece no Regulamento. Ex.: para uma requisição palestra, informe o título da palestra; para "
    "horas de voo, o curso ao qual as horas se referem; para cursos, o nome do curso como consta no "
    "certificado. Divergências podem resultar em indeferimento sumário."
)
LONG_NAME = (
    "Participação como ouvinte em congressos, seminários, simpósios, jornadas, fóruns, "
    "encontros e conferências de caráter acadêmico, científico ou profissional"
)
CHROMIUM = find_chromium()
browser = pytest.mark.skipif(CHROMIUM is None, reason="no headless Chromium available")


@pytest.fixture
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "ui-batch1.db") as environment:
        original = main.app.extensions.get("comprovante_storage")
        main.app.extensions["comprovante_storage"] = FakeStorage()
        try:
            with canonical_documents(main.app) as canonical:
                yield {**environment, "canonical": canonical}
        finally:
            if original is None:
                main.app.extensions.pop("comprovante_storage", None)
            else:
                main.app.extensions["comprovante_storage"] = original


def _sql(query, params=()):
    with main.app.app_context():
        conn = main.get_db_connection()
        rows = conn.execute(query, params).fetchall()
        conn.commit()
        return rows


def _as_student(env):
    identity = student_identity()
    with env["client"].session_transaction() as session:
        session.clear()
        session.update(user_id=identity["usuario_id"], user_type="aluno", user_name="Aluno")
        stamp_auth_version(session)
    return identity


def _matrix_versions(identity):
    return {row[0] for row in _sql(
        """SELECT item.atividade_versao_id FROM alunos a JOIN turmas t ON t.id=a.turma_id
             JOIN matriz_atividade_versao_item item ON item.matriz_id=t.matriz_id WHERE a.id=?""",
        (identity["aluno_id"],))}


def _pending_with_files(env):
    identity = _as_student(env)
    version = sorted(_matrix_versions(identity))[0]
    submission = form_submission(env["client"], "/aluno/nova-requisicao")
    intents = [upload_verified(env["client"], env["canonical"], submission, data, name)
               for data, name in ((PDF, "a.pdf"), (PNG, "b.png"))]
    env["client"].post("/aluno/nova-requisicao", data={
        "atividade_versao_id": str(version), "nome_evento": "Edicao batch1", "data_evento": "2026-09-06",
        "horas_solicitadas": "2", SUBMISSION_FIELD: submission, INTENT_IDS_FIELD: intents,
    })
    return _sql("SELECT id, atividade_versao_id FROM requisicoes WHERE nome_evento='Edicao batch1'")[0]


class _Table(HTMLParser):
    """Header texts and per-row cell texts of the first .table-progresso."""

    def __init__(self):
        super().__init__()
        self.inside, self.cell, self.heads, self.rows = False, None, [], []

    def handle_starttag(self, tag, attrs):
        if tag == "table" and "table-progresso" in (dict(attrs).get("class") or ""):
            self.inside = True
        elif self.inside and tag == "tr":
            self.rows.append([])
        elif self.inside and tag in ("th", "td"):
            self.cell = []

    def handle_endtag(self, tag):
        if tag == "table":
            self.inside = False
        elif self.inside and tag in ("th", "td") and self.cell is not None:
            text = " ".join("".join(self.cell).split())
            (self.heads if tag == "th" else self.rows[-1]).append(text)
            self.cell = None

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)


def _progress_table(client):
    parser = _Table()
    parser.feed(client.get("/aluno/progresso").get_data(as_text=True))
    rows = [dict(zip(parser.heads, row)) for row in parser.rows if row]
    return parser.heads, {row["Atividade"]: row for row in rows}


# ------------------------------------------------------------------ 1. sidebar


def _sidebar(html):
    nav = html.split('aria-label="Menu do aluno"', 1)[1].split("</nav>", 1)[0]
    links = re.findall(r'<a\s+class="sidebar-link ?([^"]*)"\s+href="([^"]+)"\s*(aria-current="page")?\s*>\s*'
                       r'<i class="lucide" data-lucide="([^"]+)" aria-hidden="true"></i>\s*<span>([^<]+)</span>', nav)
    return [(label, href, icon, cls.strip() == "active", bool(current)) for cls, href, current, icon, label in links]


def test_sidebar_order_routes_icons_and_active_state(env):
    _as_student(env)
    expected = [
        ("Painel", "/aluno/dashboard", "home"),
        ("Requisições", "/aluno/requisicoes", "inbox"),
        ("Progresso", "/aluno/progresso", "chart-column"),
        ("Arquivos", "/aluno/arquivos", "folder-open"),
        ("Reportar", "/aluno/reportar", "bug"),
        ("Meus dados", "/aluno/meus_dados", "user"),
    ]
    for label, path, _icon in expected:
        response = env["client"].get(path)
        assert response.status_code == 200, path
        links = _sidebar(response.get_data(as_text=True))
        assert [link[:3] for link in links] == expected, path
        # Exactly the current page is active, with class and aria-current together.
        assert [(link[0], link[3], link[4]) for link in links if link[3] or link[4]] == [(label, True, True)], path


# ----------------------------------------------------------------- 2. guidance


def test_nome_evento_guidance_carries_the_approved_text_on_editable_forms_only(env):
    request_id, _version = _pending_with_files(env)
    for url in ("/aluno/nova-requisicao", f"/aluno/requisicoes/{request_id}?edit=1"):
        html = re.sub(r"\s+", " ", env["client"].get(url).get_data(as_text=True))
        assert f'id="nome-evento-orientacao"><i class="lucide" data-lucide="info" aria-hidden="true"></i><span>{NOME_GUIDANCE}</span>' in html, url
        assert "atividade no regulamento. Ex.: em uma palestra" not in html
    assert "orientacao" not in env["client"].get(f"/aluno/requisicoes/{request_id}?view=1").get_data(as_text=True)


# --------------------------------------------------------------- browser layer

GEOMETRY = """JSON.stringify((() => {
  const grid = document.querySelector('.form-cards-narrow');
  const card = document.querySelector('[data-upload-card]').closest('.form-row');
  const obs = document.querySelector('textarea[name=observacao]').closest('.form-row');
  const list = document.querySelector('[data-direct-upload-list]');
  const status = document.querySelector('[data-direct-upload-status]');
  const box = el => el.getBoundingClientRect();
  return {
    rowGap: parseFloat(getComputedStyle(grid).rowGap),
    gap: box(obs).top - box(card).bottom,
    listItems: list.querySelectorAll('li').length,
    status: status.textContent,
    cardToList: box(list).top - box(card).bottom,
    listToStatus: box(status).top - box(list).bottom,
    statusToObs: box(obs).top - box(status).bottom,
    liveRegionsRendered: [list, status].every(el => getComputedStyle(el).display !== 'none'),
    liveRegionsKept: list.getAttribute('aria-live') === 'polite' && status.getAttribute('role') === 'status',
    docOverflow: document.documentElement.scrollWidth > innerWidth,
  };
})())"""


def _session(env, width=1440):
    session = BrowserSession(env["client"], CHROMIUM)
    session.call("Emulation.setDeviceMetricsOverride",
                 {"width": width, "height": 900, "deviceScaleFactor": 1, "mobile": False})
    return session


def _geometry(session):
    return json.loads(session.evaluate(GEOMETRY))


@browser
@pytest.mark.parametrize("width", [1440, 640])
def test_guidance_is_justified_and_labels_stay_single_line(env, width):
    _as_student(env)
    session = _session(env, width)
    try:
        session.goto("/aluno/nova-requisicao")
        lines = json.loads(session.evaluate("""JSON.stringify(['nome-evento-orientacao','data-evento-orientacao'].map(id => {
          const span = document.getElementById(id).querySelector('span');
          const range = document.createRange(); range.selectNodeContents(span);
          const tops = new Map();
          for (const r of range.getClientRects()) {
            const key = Math.round(r.top);
            tops.set(key, Math.max(tops.get(key) || 0, r.right));
          }
          return {align: getComputedStyle(span).textAlign, right: span.getBoundingClientRect().right,
                  lineRights: Array.from(tops.entries()).sort((a, b) => a[0] - b[0]).map(e => e[1])};
        }))"""))
        for note in lines:
            assert note["align"] == "justify"
            assert len(note["lineRights"]) >= 2
            # Justified: every line but the last ends flush with the box; the last does not stretch.
            assert all(abs(right - note["right"]) <= 1 for right in note["lineRights"][:-1]), note
            assert note["lineRights"][-1] < note["right"] - 1, note
        labels = json.loads(session.evaluate(
            "JSON.stringify(Array.from(document.querySelectorAll('.form-cards-narrow .row-label'))"
            ".map(l => ({t: l.textContent.trim(), lines: new Set(Array.from((() => { const r = document.createRange();"
            " r.selectNodeContents(l); return r.getClientRects(); })()).map(x => Math.round(x.top))).size})))"))
        assert labels and all(label["lines"] == 1 for label in labels), labels
    finally:
        session.close()


@browser
@pytest.mark.parametrize("width", [1440, 640])
def test_empty_upload_feedback_holds_no_row_open_and_returns_while_uploading(env, width, tmp_path):
    _as_student(env)
    pick = tmp_path / "comprovante.pdf"
    pick.write_bytes(PDF)
    session = _session(env, width)
    try:
        session.goto("/aluno/nova-requisicao")
        empty = _geometry(session)
        assert empty["listItems"] == 0 and empty["status"] == ""
        assert abs(empty["gap"] - empty["rowGap"]) < 0.5, empty
        assert empty["liveRegionsRendered"] and empty["liveRegionsKept"] and not empty["docOverflow"]

        node = session.call("Runtime.evaluate", {"expression": "document.getElementById('comprovantes_files')"})
        session.call("DOM.setFileInputFiles", {"files": [str(pick)], "objectId": node["result"]["objectId"]})
        session.wait_for("document.querySelectorAll('[data-direct-upload-list] li').length === 1")
        busy = _geometry(session)
        # The harness blocks the provider host, so the upload never resolves: feedback stays visible.
        assert busy["status"] == "Aguarde a conclusão do envio dos comprovantes.", busy
        pulled = empty["rowGap"] / 2
        assert abs(busy["cardToList"] - pulled) < 0.5 and abs(busy["listToStatus"] - pulled) < 0.5, busy
        assert abs(busy["statusToObs"] - busy["rowGap"]) < 0.5, busy
        assert session.evaluate("document.querySelector('form[data-direct-upload] button[type=submit]').disabled") is True

        session.evaluate("(() => { const b = document.querySelectorAll('[data-direct-upload-list] li button');"
                         " b[b.length - 1].click(); return true; })()")
        after = _geometry(session)
        assert after["listItems"] == 0 and after["status"] == ""
        assert abs(after["gap"] - after["rowGap"]) < 0.5, after
    finally:
        session.close()


@browser
def test_edit_mode_lists_stored_files_under_the_card_and_closes_up_when_all_are_removed(env):
    request_id, _version = _pending_with_files(env)
    session = _session(env)
    try:
        session.goto(f"/aluno/requisicoes/{request_id}?edit=1")
        state = json.loads(session.evaluate("""JSON.stringify((() => {
          const card = document.querySelector('[data-upload-card]').closest('.form-row');
          const obs = document.querySelector('textarea[name=observacao]').closest('.form-row');
          const stored = document.getElementById('comprovantes-list');
          return {names: Array.from(stored.querySelectorAll('.file-list-name')).map(a => a.textContent),
                  cardToStored: stored.getBoundingClientRect().top - card.getBoundingClientRect().bottom,
                  storedToObs: obs.getBoundingClientRect().top - stored.getBoundingClientRect().bottom};
        })())"""))
        assert state["names"] == ["a.pdf", "b.png"]
        assert abs(state["cardToStored"] - 6) < 0.5 and abs(state["storedToObs"] - 12) < 0.5, state
        for name in ("a.pdf", "b.png"):
            session.click(f'#comprovantes-list .file-list-remove[aria-label="Remover comprovante {name}"]')
        closed = _geometry(session)
        assert session.evaluate("document.getElementById('comprovantes-list').hidden") is True
        assert session.evaluate("document.querySelectorAll('input[name=remover_comprovantes]').length") == 2
        assert abs(closed["gap"] - closed["rowGap"]) < 0.5, closed
    finally:
        session.close()


# ---------------------------------------------------------------- 4. dropdown

ACTIVITY = """JSON.stringify((() => {
  const select = document.getElementById('atividade_versao_id_select');
  const card = document.getElementById('atividade_card');
  const chip = card.querySelector('.field-chip');
  const visible = Array.from(select.options).filter(o => !o.hidden && o.getAttribute('data-placeholder') !== '1');
  const transformed = [];
  for (let el = select; el; el = el.parentElement) {
    const cs = getComputedStyle(el);
    if (cs.transform !== 'none' || (cs.zoom && cs.zoom !== '1')) transformed.push(el.tagName + '.' + el.className);
  }
  const s = select.getBoundingClientRect(), c = card.getBoundingClientRect();
  return {value: select.value, disabled: select.disabled, transformed,
          selectLeftToChip: s.left - chip.getBoundingClientRect().right, selectRightToCard: c.right - s.right,
          visible: visible.map(o => ({id: o.value, text: o.text, tipo: o.dataset.tipo, grupo: o.dataset.grupo}))};
})())"""


def _choose(session, tipo, grupo):
    session.evaluate(
        "(() => { const t = document.getElementById('tipo_atividade_select'); t.value = %s; t.dispatchEvent(new Event('change'));"
        " const n = document.getElementById('grupo_num'); n.value = %s; n.dispatchEvent(new Event('change')); return true; })()"
        % (json.dumps(tipo), json.dumps(grupo)))
    return json.loads(session.evaluate(ACTIVITY))


@browser
@pytest.mark.parametrize("width", [1440, 640])
def test_activity_select_fills_its_card_filters_and_keeps_full_names(env, width):
    identity = _as_student(env)
    base = _sql("SELECT atividade_base_id FROM atividade_versao WHERE id=31")[0][0]
    _sql("UPDATE atividade_base SET nome_conceito=? WHERE id=?", (LONG_NAME, base))
    assert 31 in _matrix_versions(identity)
    session = _session(env, width)
    try:
        session.goto("/aluno/nova-requisicao")
        aac = _choose(session, "Acadêmica Complementar", "1")
        assert aac["transformed"] == [] and not aac["disabled"]
        # The anchor the native popup is placed against is the whole visible control area.
        assert abs(aac["selectLeftToChip"]) <= 1 and 0 <= aac["selectRightToCard"] <= 1.5, aac
        assert aac["visible"] and all(o["tipo"] == "Acadêmica Complementar" and o["grupo"].startswith("1 - ") for o in aac["visible"])
        assert LONG_NAME in [o["text"] for o in aac["visible"]]
        aeu = _choose(session, "Extensão Universitária", "2")
        assert aeu["visible"] and all(o["tipo"] == "Extensão Universitária" and o["grupo"].startswith("2 - ") for o in aeu["visible"])
        assert LONG_NAME not in [o["text"] for o in aeu["visible"]]
        assert not session.evaluate("document.documentElement.scrollWidth > innerWidth")

        # Keyboard steps through the visible options only. The customizable
        # select's model: an arrow opens the list on the current option, the
        # next one moves, Enter commits (the native model is pinned by the
        # fallback test below).
        start = aeu["value"]
        session.evaluate("document.getElementById('atividade_versao_id_select').focus(); true")
        _key(session, "ArrowDown", "ArrowDown", 40)
        assert _picker(session)["open"] is True
        _key(session, "ArrowDown", "ArrowDown", 40)
        _key(session, "Enter", "Enter", 13, "\r")
        moved = json.loads(session.evaluate(ACTIVITY))
        ids = [o["id"] for o in aeu["visible"]]
        assert moved["value"] in ids and ids.index(moved["value"]) == ids.index(start) + 1, (start, moved["value"], ids)
    finally:
        session.close()


@browser
def test_edit_mode_keeps_the_stored_activity_selected_and_visible(env):
    request_id, version = _pending_with_files(env)
    session = _session(env)
    try:
        session.goto(f"/aluno/requisicoes/{request_id}?edit=1")
        state = json.loads(session.evaluate(ACTIVITY))
        assert state["value"] == str(version) and str(version) in [o["id"] for o in state["visible"]]
        assert session.evaluate("document.getElementById('nome-evento-orientacao') !== null")
    finally:
        session.close()


# ------------------------------------------------- 4b. the open picker (base-select)

# Painted bounds of the OPEN picker: every point it covers hit-tests to the
# select (the picker is its pseudo-element), so a scan outside the closed card
# finds the box the student actually sees -- no pseudo-element API needed.
PICKER = """JSON.stringify((() => {
  const s = document.getElementById('atividade_versao_id_select');
  const card = document.getElementById('atividade_card').getBoundingClientRect();
  const hit = (x, y) => { const e = document.elementFromPoint(x, y); return !!e && (e === s || s.contains(e)); };
  const cx = card.left + card.width / 2;
  const below = hit(cx, card.bottom + 10), above = hit(cx, card.top - 10);
  let t = null, b = null;
  if (below) { for (let y = Math.ceil(card.bottom) + 1; y < innerHeight; y++) { if (hit(cx, y)) { if (t === null) t = y; b = y + 1; } else if (t !== null) break; } }
  if (above) { for (let y = Math.floor(card.top) - 1; y >= 0; y--) { if (hit(cx, y)) { if (b === null) b = y + 1; t = y; } else if (b !== null) break; } }
  let l = null, r = null;
  if (t !== null) { const my = (t + b) / 2; for (let x = 0; x < innerWidth; x++) if (hit(x, my)) { if (l === null) l = x; r = x + 1; } }
  const shown = Array.from(s.options).filter(o => getComputedStyle(o).display !== 'none');
  const long = shown.find(o => o.text.length > 100);
  const lr = long && long.getBoundingClientRect();
  return {open: s.matches(':open'), value: s.value, below, above,
          picker: t === null ? null : {l, r, t, b},
          card: {l: card.left, r: card.right, t: card.top, b: card.bottom}, vw: innerWidth, vh: innerHeight,
          shown: shown.filter(o => o.dataset.placeholder !== '1').map(o => ({id: o.value, tipo: o.dataset.tipo, grupo: o.dataset.grupo})),
          long: long ? {l: lr.left, r: lr.right, lines: Math.round(lr.height / parseFloat(getComputedStyle(long).lineHeight))} : null,
          active: document.activeElement === s ? 'select' : (s.contains(document.activeElement) ? 'option:' + document.activeElement.value : 'other')};
})())"""


def _key(session, key, code, vk, text=None):
    down = {"type": "keyDown" if text else "rawKeyDown", "key": key, "code": code, "windowsVirtualKeyCode": vk}
    if text:
        down["text"] = text
    session.call("Input.dispatchKeyEvent", down)
    session.call("Input.dispatchKeyEvent", {"type": "keyUp", "key": key, "code": code, "windowsVirtualKeyCode": vk})
    session.pump(0.25)


def _picker(session):
    return json.loads(session.evaluate(PICKER))


def _open(session):
    session.click("#atividade_versao_id_select")
    session.pump(0.3)
    state = _picker(session)
    assert state["open"], state
    return state


def _long_activity(identity):
    base = _sql("SELECT atividade_base_id FROM atividade_versao WHERE id=31")[0][0]
    _sql("UPDATE atividade_base SET nome_conceito=? WHERE id=?", (LONG_NAME, base))
    assert 31 in _matrix_versions(identity)


def _neutralize_enhancement(session):
    # Exactly what a browser without the customizable select does with this
    # page: the @supports condition of the shared picker (UI batch 4 moved it
    # to components/select.css) is false, so the whole block is skipped.
    session.response_rewrites["/static/css/components/select.css"] = lambda body: body.replace(
        b"@supports (appearance: base-select)", b"@supports (appearance: sgaa-unsupported-probe)")


@browser
@pytest.mark.parametrize("width,height", [(1440, 900), (768, 900), (640, 900), (1440, 460)])
def test_open_picker_spans_the_field_wraps_long_names_and_stays_in_the_viewport(env, width, height):
    identity = _as_student(env)
    _long_activity(identity)
    session = BrowserSession(env["client"], CHROMIUM)
    session.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False})
    try:
        session.goto("/aluno/nova-requisicao")
        assert session.evaluate("getComputedStyle(document.getElementById('atividade_versao_id_select')).appearance") == "base-select"
        _choose(session, "Acadêmica Complementar", "1")
        session.evaluate("document.getElementById('atividade_versao_id_select').scrollIntoView({block: 'center'}); true")
        state = _open(session)
        card, box = state["card"], state["picker"]
        assert box is not None, state
        # Aligned with the field: same left and right edges as the card, not displaced.
        assert abs(box["l"] - card["l"]) <= 1 and abs(box["r"] - card["r"]) <= 1, state
        # Next to the field (below, or flipped above when there is no room) and fully on screen.
        if state["below"]:
            assert 0 <= box["t"] - card["b"] <= 8, state
        else:
            assert state["above"] and 0 <= card["t"] - box["b"] <= 8, state
        assert box["t"] >= 0 and box["b"] <= state["vh"] and box["l"] >= 0 and box["r"] <= state["vw"], state
        # The regulation-length name wraps inside the picker instead of widening it.
        assert state["long"]["lines"] >= 2 and box["l"] <= state["long"]["l"] and state["long"]["r"] <= box["r"], state
        assert state["shown"] and all(o["tipo"] == "Acadêmica Complementar" and o["grupo"].startswith("1 - ") for o in state["shown"])
        _key(session, "Escape", "Escape", 27)
        assert _picker(session)["open"] is False

        # Filtering still drives what the picker lists.
        _choose(session, "Extensão Universitária", "2")
        state = _open(session)
        assert state["shown"] and all(o["tipo"] == "Extensão Universitária" and o["grupo"].startswith("2 - ") for o in state["shown"])
        assert state["long"] is None
    finally:
        session.close()


@browser
def test_picker_mouse_choice_fires_change_and_is_what_the_form_submits(env):
    identity = _as_student(env)
    session = _session(env)
    try:
        session.goto("/aluno/nova-requisicao")
        _choose(session, "Acadêmica Complementar", "1")
        _open(session)
        target = session.evaluate(
            "(() => { const s = document.getElementById('atividade_versao_id_select');"
            " const o = Array.from(s.options).find(o => !o.hidden && o.dataset.defaultHours && o.value !== s.value);"
            " o.scrollIntoView({block: 'nearest'}); return {id: o.value, hours: o.dataset.defaultHours}; })()")
        session.pump(0.2)
        session.click(f'#atividade_versao_id_select option[value="{target["id"]}"]')
        session.pump(0.3)
        state = _picker(session)
        assert state["open"] is False and state["value"] == target["id"] and state["active"] == "select", state
        # The page's own change handler ran: the suggested hours were applied.
        assert session.evaluate("document.querySelector('[name=horas_solicitadas]').value") == target["hours"]

        session.requests.clear()
        session.evaluate(
            "(() => { const f = document.getElementById('atividade_versao_id_select').form;"
            " f.querySelector('[name=nome_evento]').value = 'Escolha pelo picker';"
            " f.querySelector('[name=data_evento]').value = '2026-09-06'; f.requestSubmit(); return true; })()")
        session.pump(1.5)
        posts = [body for method, path, body in session.requests if method == "POST" and path == "/aluno/nova-requisicao"]
        assert len(posts) == 1 and parse_qs(posts[0])["atividade_versao_id"] == [target["id"]]
        stored = _sql("SELECT atividade_versao_id FROM requisicoes WHERE nome_evento='Escolha pelo picker' AND aluno_id=?",
                      (identity["aluno_id"],))
        assert [row[0] for row in stored] == [int(target["id"])]
    finally:
        session.close()


@browser
def test_picker_keyboard_enter_arrows_escape_and_focus(env):
    _as_student(env)
    session = _session(env)
    try:
        session.goto("/aluno/nova-requisicao")
        _choose(session, "Acadêmica Complementar", "1")
        visible = [o["id"] for o in json.loads(session.evaluate(ACTIVITY))["visible"]]
        start = session.evaluate("document.getElementById('atividade_versao_id_select').value")
        session.evaluate("document.getElementById('atividade_versao_id_select').focus(); true")

        _key(session, "Enter", "Enter", 13, "\r")
        state = _picker(session)
        assert state["open"] and state["active"] == f"option:{start}", state
        _key(session, "ArrowDown", "ArrowDown", 40)
        assert _picker(session)["active"] == f"option:{visible[visible.index(start) + 1]}"
        _key(session, "Escape", "Escape", 27)
        state = _picker(session)
        assert state["open"] is False and state["value"] == start and state["active"] == "select", state

        _key(session, "Enter", "Enter", 13, "\r")
        for _ in range(len(visible) + 3):  # past the end: focus never leaves the filtered options
            _key(session, "ArrowDown", "ArrowDown", 40)
            assert _picker(session)["active"].removeprefix("option:") in visible
        _key(session, "ArrowUp", "ArrowUp", 38)
        _key(session, "Enter", "Enter", 13, "\r")
        state = _picker(session)
        assert state["open"] is False and state["value"] == visible[-2] and state["active"] == "select", state
    finally:
        session.close()


@browser
def test_edit_mode_picker_opens_on_the_stored_activity(env):
    request_id, version = _pending_with_files(env)
    session = _session(env)
    try:
        session.goto(f"/aluno/requisicoes/{request_id}?edit=1")
        state = _open(session)
        assert state["value"] == str(version) and state["active"] == f"option:{version}", state
        checked = session.evaluate(
            "(() => { const o = document.querySelector('#atividade_versao_id_select option:checked');"
            " const r = o.getBoundingClientRect(); return {id: o.value, h: r.height, x: r.left + 2, y: r.top + r.height / 2,"
            " hit: document.elementFromPoint(r.left + 2, r.top + r.height / 2) === o}; })()")
        assert checked["id"] == str(version) and checked["hit"] is True, checked
    finally:
        session.close()


@browser
def test_without_the_feature_the_native_select_keeps_its_geometry_and_behaviour(env):
    _as_student(env)
    geometry = {}
    for mode in ("enhanced", "native"):
        session = _session(env)
        if mode == "native":
            _neutralize_enhancement(session)
        try:
            session.goto("/aluno/nova-requisicao")
            _choose(session, "Acadêmica Complementar", "1")
            geometry[mode] = json.loads(session.evaluate(
                "JSON.stringify((() => { const s = document.getElementById('atividade_versao_id_select');"
                " const c = document.getElementById('atividade_card'); const r = e => { const b = e.getBoundingClientRect();"
                " return [b.left, b.top, b.width, b.height]; }; return {appearance: getComputedStyle(s).appearance,"
                " select: r(s), card: r(c)}; })())"))
            if mode == "native":
                visible = [o["id"] for o in json.loads(session.evaluate(ACTIVITY))["visible"]]
                start = session.evaluate("document.getElementById('atividade_versao_id_select').value")
                session.evaluate("document.getElementById('atividade_versao_id_select').focus(); true")
                _key(session, "ArrowDown", "ArrowDown", 40)
                assert session.evaluate("document.getElementById('atividade_versao_id_select').value") == visible[visible.index(start) + 1]
        finally:
            session.close()
    assert geometry["enhanced"]["appearance"] == "base-select" and geometry["native"]["appearance"] == "auto"
    assert geometry["enhanced"]["select"] == geometry["native"]["select"]
    assert geometry["enhanced"]["card"] == geometry["native"]["card"]


def test_both_shells_load_design_system_css_under_one_bumped_asset_version(env):
    login_admin(env["client"])
    admin = env["client"].get("/admin/dashboard").get_data(as_text=True)
    _as_student(env)
    aluno = env["client"].get("/aluno/nova-requisicao").get_data(as_text=True)
    versions = {page: set(re.findall(r'/static/css/[\w/.-]+\.css\?v=([\w.-]+)', html)) for page, html in (("admin", admin), ("aluno", aluno))}
    # One version for every stylesheet in both shells, and not the one that
    # predates batch 1's CSS -- a returning browser must fetch the new files.
    assert len(versions["admin"]) == 1 and versions["admin"] == versions["aluno"], versions
    assert versions["aluno"] != {"20260516-tooltip-dark-v1"}


# ---------------------------------------------------------------- 5. progress


def test_progress_shows_tempo_padrao_between_grupo_and_limite(env):
    identity = _as_student(env)
    versions = sorted(_matrix_versions(identity))
    with_value, without_value = versions[0], versions[1]
    _sql("UPDATE atividade_versao SET ch_por_evento=1.5, limite_total=40, limite_semestre=NULL WHERE id=?", (with_value,))
    _sql("UPDATE atividade_versao SET ch_por_evento=NULL WHERE id=?", (without_value,))
    names = dict(_sql("""SELECT v.id, b.nome_conceito FROM atividade_versao v
                           JOIN atividade_base b ON b.id=v.atividade_base_id WHERE v.id IN (?,?)""",
                      (with_value, without_value)))
    heads, rows = _progress_table(env["client"])
    assert heads[:4] == ["Atividade", "Grupo", "Tempo padrão", "Limite"] and heads[-1] == "Total"
    assert all(len(row) == len(heads) for row in rows.values())
    assert rows[names[with_value]]["Tempo padrão"] == "1,5h"
    assert rows[names[with_value]]["Limite"] == "40h total"
    assert rows[names[without_value]]["Tempo padrão"] == "-"
    payload = env["client"].get("/aluno/progresso?format=json").get_json()
    by_id = {item["atividade_id"]: item for item in payload["atividades"]}
    assert by_id[with_value]["tempo_padrao"] == "1,5h" and by_id[without_value]["tempo_padrao"] == "-"


def test_history_only_rows_read_the_frozen_snapshot_value(env):
    identity = _as_student(env)
    old = _sql("""SELECT v.*, b.nome_conceito FROM atividade_versao v
                    JOIN atividade_base b ON b.id=v.atividade_base_id WHERE v.id=1""")[0]
    assert 1 not in _matrix_versions(identity)
    snapshot = {
        "atividade_base_id": old["atividade_base_id"], "atividade_versao_id": 1,
        "atividade_versao_numero": old["numero_versao"], "eixo": old["eixo"], "matriz_id_efetiva": 1,
        "schema_version": "prod-1-request-v2", "ch_por_evento": 7.5,
        "limite_semestre": old["limite_semestre"], "limite_total": old["limite_total"],
        "nome_exibivel": old["nome_conceito"], "tipo_atividade": "Acadêmica Complementar",
        "grupo": old["grupo"], "documentos_json": old["documentos_json"] or "[]",
    }
    _sql("""INSERT INTO requisicoes(aluno_id,atividade_versao_id,data_solicitacao,data_evento,
                                    horas_solicitadas,status,horas_deferidas,regra_snapshot_json,nome_evento)
            VALUES(?,1,'2026-01-01','2026-01-01',2,'Deferida',2,?,'Historico batch1')""",
         (identity["aluno_id"], json.dumps(snapshot)))
    # The live version row disagrees; the student's history must not follow it.
    _sql("UPDATE atividade_versao SET ch_por_evento=99 WHERE id=1")
    with main.app.app_context():
        payload = _build_aluno_progresso_payload(main.get_db_connection(), identity["usuario_id"])
    history = [item for item in payload["atividades"] if item["atividade_id"] == 1]
    assert len(history) == 1 and history[0]["tempo_padrao"] == "7,5h" and history[0]["total"] == 2


def test_tempo_padrao_changes_no_progress_calculation_and_writes_nothing(env):
    login_admin(env["client"])
    _response, row = create_admin_request(env["client"], "Batch1 approved", version_id=29)
    env["client"].post(f"/admin/processar_requisicao/{row['id']}",
                       data={"status": "Deferida", "horas_deferidas": "4", "observacao": "ok"})
    identity = _as_student(env)

    def snapshot():
        with main.app.app_context():
            payload = _build_aluno_progresso_payload(main.get_db_connection(), identity["usuario_id"])
        return {item["atividade_id"]: {k: v for k, v in item.items() if k != "tempo_padrao"}
                for item in payload["atividades"]}, payload["semestres"]

    before_rows = _sql("SELECT * FROM requisicoes ORDER BY id")
    baseline = snapshot()
    _sql("UPDATE atividade_versao SET ch_por_evento=CASE WHEN ch_por_evento IS NULL THEN 3 ELSE NULL END")
    assert snapshot() == baseline
    assert baseline[0][29]["total"] == 4
    assert env["client"].get("/aluno/progresso").status_code == 200
    assert [tuple(r) for r in _sql("SELECT * FROM requisicoes ORDER BY id")] == [tuple(r) for r in before_rows]


@browser
@pytest.mark.parametrize("width", [1440, 640])
def test_progress_columns_stay_aligned_and_scroll_inside_their_shell(env, width):
    _as_student(env)
    session = _session(env, width)
    try:
        session.goto("/aluno/progresso")
        table = json.loads(session.evaluate("""JSON.stringify((() => {
          const t = document.querySelector('.table-progresso');
          const heads = Array.from(t.tHead.rows[0].cells);
          const shell = document.querySelector('.progresso-table-shell');
          const column = i => Array.from(t.tBodies[0].rows).map(r => r.cells[i].getBoundingClientRect());
          const misaligned = heads.flatMap((th, i) => column(i).filter(c =>
            Math.abs(c.left - th.getBoundingClientRect().left) > 0.5 || Math.abs(c.width - th.getBoundingClientRect().width) > 0.5)).length;
          return {heads: heads.map(th => th.textContent.trim()), misaligned,
                  widths: heads.map(th => th.getBoundingClientRect().width),
                  docOverflow: document.documentElement.scrollWidth > innerWidth,
                  shellScrolls: shell.scrollWidth > shell.clientWidth};
        })())"""))
        assert table["heads"][1:4] == ["Grupo", "Tempo padrão", "Limite"]
        assert table["misaligned"] == 0
        assert table["widths"][2] >= 92 and table["widths"][3] >= 92, table["widths"]
        assert not table["docOverflow"]
        if width == 640:
            assert table["shellScrolls"]
    finally:
        session.close()
