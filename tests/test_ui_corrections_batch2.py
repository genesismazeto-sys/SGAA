"""UI corrections, batch 2.

1. Direct-upload rows (static/js/direct-upload.js) on every consuming surface
   -- Nova/Editar requisição, the student request detail, the Requisições
   modal and the admin Arquivos modal. "Tentar novamente" was a text .btn that
   the DS icon-button rule squeezed into a 30px box, and "Remover" was text in
   the 24px .file-list-remove box: both overflowed, and the row's three
   children landed on the wrong grid tracks. Now each row is icon | name |
   controls, the controls are 24px Lucide icon buttons named for their file
   (with the DS tooltip naming the action), an error's message wraps instead
   of being cut off, and keyboard focus survives retry and removal.
2. Suggested hours on the student form. Verified as working for activity,
   Tipo and Grupo changes, edit load, validation recovery and read-only; one
   defect fixed: switching to an activity WITHOUT ch_por_evento erased hours
   the student had typed (or the stored hours in edit mode) with nothing put
   in their place. A stale suggestion is still cleared.
3. Decision buttons (Indeferir / Deferir Parcialmente / Deferir and the
   post-decision trio) are owned by modern-style.css: ordinary .btn geometry,
   --status-* colours, and an explicit aria-pressed selected state, in the
   Requisições modal and on the standalone Processar page. Reopening the
   modal after closing it mid-confirmation no longer shows only the
   previously chosen button. Processing semantics and partial-hours
   validation are unchanged.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import parse_qs

import pytest

import main
from tests.canonical_request_documents_support import canonical_documents
from tests.canonical_request_test_support import create_admin_request, login_admin, student_identity
from tests.cdp_browser_support import BrowserSession, find_chromium
from tests.session_support import stamp_auth_version
from tests.test_comprovantes_google_drive import PDF, FakeStorage
from tests.versioned_test_support import isolated_versioned_app_env

ROOT = Path(__file__).resolve().parents[1]
CHROMIUM = find_chromium()
browser = pytest.mark.skipif(CHROMIUM is None, reason="no headless Chromium available")
LONG_FILE = "comprovante-de-participacao-no-congresso-brasileiro-de-aviacao-civil-2026-certificado-final.pdf"


@pytest.fixture
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "ui-batch2.db") as environment:
        original = main.app.extensions.get("comprovante_storage")
        main.app.extensions["comprovante_storage"] = FakeStorage()
        try:
            with canonical_documents(main.app):
                yield environment
        finally:
            if original is None:
                main.app.extensions.pop("comprovante_storage", None)
            else:
                main.app.extensions["comprovante_storage"] = original


@pytest.fixture
def picks(tmp_path):
    folder = tmp_path / "picks"
    folder.mkdir()
    (folder / "bad.txt").write_bytes(b"not a document")
    (folder / "a.pdf").write_bytes(PDF)
    (folder / LONG_FILE).write_bytes(PDF)
    return folder


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


def _session(client, width=1440):
    session = BrowserSession(client, CHROMIUM)
    session.call("Emulation.setDeviceMetricsOverride",
                 {"width": width, "height": 900, "deviceScaleFactor": 1, "mobile": False})
    return session


def _key(session, key, code, vk, text=None, modifiers=0):
    down = {"type": "keyDown" if text else "rawKeyDown", "key": key, "code": code,
            "windowsVirtualKeyCode": vk, "modifiers": modifiers}
    if text:
        down["text"] = text
    session.call("Input.dispatchKeyEvent", down)
    session.call("Input.dispatchKeyEvent", {**down, "type": "keyUp"})
    session.pump(0.2)


def _tab(session):
    _key(session, "Tab", "Tab", 9)


def _enter(session):
    _key(session, "Enter", "Enter", 13, "\r")


def _active(session):
    return session.evaluate("(() => { const a = document.activeElement;"
                            " return a ? (a.getAttribute('aria-label') || a.id || a.tagName) : null; })()")


def _pick(session, selector, files):
    node = session.call("Runtime.evaluate", {"expression": f"document.querySelector({json.dumps(selector)})"})
    session.call("DOM.setFileInputFiles", {"files": [str(f) for f in files], "objectId": node["result"]["objectId"]})
    session.pump(0.4)


# =================================================== 1. direct-upload row controls

ROWS = """JSON.stringify(Array.from(document.querySelectorAll('[data-direct-upload-list] li')).map(li => {
  const r = li.getBoundingClientRect();
  const name = li.querySelector('.file-list-name');
  const range = document.createRange(); range.selectNodeContents(name);
  return {
    state: li.dataset.state,
    kids: Array.from(li.children).map(k => (k.getAttribute('class') || '').split(' ')[0]),
    name: name.textContent,
    clipped: name.scrollWidth > name.clientWidth + 1,
    lines: new Set(Array.from(range.getClientRects()).map(x => Math.round(x.top))).size,
    nameColor: getComputedStyle(name).color,
    overflow: li.scrollWidth > li.clientWidth + 1,
    buttons: Array.from(li.querySelectorAll('button')).map(b => {
      const br = b.getBoundingClientRect();
      return {label: b.getAttribute('aria-label'), tip: b.dataset.uiTooltip, shown: getComputedStyle(b).display !== 'none',
              w: br.width, h: br.height, text: b.textContent.trim(),
              icon: !!b.querySelector('svg.lucide[aria-hidden="true"]'),
              inside: br.left >= r.left - 0.5 && br.right <= r.right + 0.5 && br.top >= r.top - 0.5 && br.bottom <= r.bottom + 0.5,
              centred: Math.abs((br.top + br.bottom) / 2 - (r.top + r.bottom) / 2) <= 0.5};
    }),
  };
}))"""

# The first issue request fails as a network error once; the retry goes through.
FAIL_ONCE = """(() => { const real = window.fetch; window.__failOnce = true;
  window.fetch = function(url){ if (window.__failOnce && String(url).indexOf('/storage/upload-intents') === 0) {
    window.__failOnce = false; return Promise.reject(new TypeError('offline')); } return real.apply(this, arguments); };
  return true; })()"""

SURFACES = {
    "student_new": ("aluno", "/aluno/nova-requisicao", None, "#comprovantes_files", "Remover comprovante"),
    "student_detail": ("aluno", "/aluno/requisicoes/{pending}", None,
                       "form[data-direct-upload] input[type=file]", "Remover comprovante"),
    "admin_requisicoes": ("admin", "/admin/requisicoes", "window.__openAdminNewReqModal()",
                          "#m_comprovantes_files", "Remover comprovante"),
    "admin_arquivos": ("admin", "/admin/arquivos", "document.getElementById('btn-admin-arquivos-adicionar').click()",
                       "#admin-arquivo-input", "Remover arquivo"),
}


def _open_surface(env, surface, width):
    who, path, opener, selector, remove_label = SURFACES[surface]
    client = env["client"]
    login_admin(client)
    _response, pending = create_admin_request(client, "Batch2 pendente")
    if who == "aluno":
        _as_student(client)
    session = _session(client, width)
    ready = "document.readyState === 'complete'" + (" && !!window.__openAdminNewReqModal" if opener and "Req" in opener else "")
    session.goto(path.format(pending=pending["id"]), ready)
    if opener:
        session.evaluate(opener + "; true")
        session.pump(0.8)
    return session, selector, remove_label


def _assert_rows_fit(rows):
    for row in rows:
        assert row["kids"] == ["lucide", "file-list-name", "file-list-actions"], row
        assert not row["overflow"] and not row["clipped"], row
        shown = [b for b in row["buttons"] if b["shown"]]
        # Icon-only 24px controls, inside the row and centred on it, no text spilling out.
        assert all(b["w"] == 24 and b["h"] == 24 and b["inside"] and b["centred"] and b["icon"] and b["text"] == ""
                   for b in shown), row
        labels = [b["label"].split(" ", 2)[:2] for b in shown]
        # Retry exists only while the file is in error.
        assert (["Tentar", "novamente"] in labels) == (row["state"] == "error"), row


@browser
@pytest.mark.parametrize("surface,width", [
    ("student_new", 1440), ("student_new", 640), ("student_detail", 1440),
    ("admin_requisicoes", 1440), ("admin_requisicoes", 768), ("admin_arquivos", 1440),
])
def test_upload_rows_fit_their_controls_and_show_errors_on_every_surface(env, picks, surface, width):
    session, selector, remove_label = _open_surface(env, surface, width)
    try:
        session.evaluate(FAIL_ONCE)
        if surface == "admin_arquivos":  # one file per operation
            _pick(session, selector, [picks / "bad.txt"])
            expected = ["bad.txt"]
        else:
            _pick(session, selector, [picks / LONG_FILE])
            _pick(session, selector, [picks / "bad.txt", picks / "a.pdf"])
            expected = [LONG_FILE, "bad.txt", "a.pdf"]
        session.pump(0.4)
        rows = json.loads(session.evaluate(ROWS))
        assert [row["name"].split(" — ")[0] for row in rows] == expected
        _assert_rows_fit(rows)
        errors = [row for row in rows if row["state"] == "error"]
        assert errors and all(row["nameColor"] == "rgb(185, 28, 28)" for row in errors)  # --danger-text
        assert "Envie somente arquivos PDF, PNG ou JPEG." in next(r["name"] for r in rows if r["name"].startswith("bad.txt"))
        if surface != "admin_arquivos":
            assert rows[0]["name"].endswith("Falha de rede ao preparar o envio.") and rows[0]["lines"] >= 2, rows[0]
        for row in rows:
            name = row["name"].split(" — ")[0]
            labels = {b["label"]: b["tip"] for b in row["buttons"]}
            assert labels[f"{remove_label} {name}"] == remove_label
            assert labels[f"Tentar novamente {name}"] == "Tentar novamente"
        assert not session.evaluate("document.documentElement.scrollWidth > innerWidth")
    finally:
        session.close()


@browser
def test_upload_row_keyboard_retry_and_removal_keep_focus_in_the_list(env, picks):
    session, selector, _label = _open_surface(env, "student_new", 1440)
    try:
        session.evaluate(FAIL_ONCE)
        _pick(session, selector, [picks / "a.pdf"])          # network failure -> error
        _pick(session, selector, [picks / "bad.txt"])        # invalid type -> error
        session.evaluate(f"document.querySelector({json.dumps(selector)}).focus(); true")
        order = []
        for _ in range(4):
            _tab(session)
            order.append(_active(session))
        assert order == ["Tentar novamente a.pdf", "Remover comprovante a.pdf",
                         "Tentar novamente bad.txt", "Remover comprovante bad.txt"]
        # The DS tooltip names the action on keyboard focus.
        session.evaluate("document.querySelector('[aria-label=\"Tentar novamente a.pdf\"]').focus(); true")
        session.pump(0.2)
        assert session.evaluate("(() => { const t = document.getElementById('ui-tooltip-root');"
                                " return t && !t.hidden ? t.textContent : null; })()") == "Tentar novamente"
        # Retry: the upload restarts, the retry button hides, focus stays on the row.
        _enter(session)
        rows = json.loads(session.evaluate(ROWS))
        assert rows[0]["state"] != "error" and not rows[0]["buttons"][0]["shown"]
        assert _active(session) == "Remover comprovante a.pdf"
        # A retry that fails again keeps focus on Tentar novamente.
        session.evaluate("document.querySelector('[aria-label=\"Tentar novamente bad.txt\"]').focus(); true")
        _enter(session)
        assert _active(session) == "Tentar novamente bad.txt"
        # Removal moves focus to the row that took its place, then back to the upload control.
        session.evaluate("document.querySelector('[aria-label=\"Remover comprovante a.pdf\"]').focus(); true")
        _enter(session)
        assert _active(session) == "Remover comprovante bad.txt"
        _enter(session)
        assert json.loads(session.evaluate(ROWS)) == []
        assert session.evaluate("document.activeElement.id") == "comprovantes_files"
        assert session.evaluate("document.querySelector('form[data-direct-upload] button[type=submit]').disabled") is False
    finally:
        session.close()


@browser
def test_upload_row_mouse_retry_and_remove(env, picks):
    session, selector, _label = _open_surface(env, "admin_requisicoes", 1440)
    try:
        session.evaluate(FAIL_ONCE)
        _pick(session, selector, [picks / "a.pdf"])
        assert json.loads(session.evaluate(ROWS))[0]["state"] == "error"
        session.click('[aria-label="Tentar novamente a.pdf"]')
        session.pump(0.4)
        intents = [p for m, p, _b in session.requests if m == "POST" and p == "/storage/upload-intents"]
        assert len(intents) == 1, "the retry issued the upload intent the failed attempt never reached"
        assert json.loads(session.evaluate(ROWS))[0]["state"] != "error"
        session.click('[aria-label="Remover comprovante a.pdf"]')
        session.pump(0.2)
        assert json.loads(session.evaluate(ROWS)) == []
        # A mouse removal is not turned into a focus ring on the upload card.
        assert session.evaluate("document.activeElement.id") != "m_comprovantes_files"
        assert session.evaluate("document.querySelector('#req-form [data-upload-card]').matches(':focus-within')") is False
    finally:
        session.close()


def test_changed_assets_are_served_under_a_new_version_in_both_shells(env):
    client = env["client"]
    login_admin(client)
    admin = client.get("/admin/requisicoes").get_data(as_text=True)
    _as_student(client)
    aluno = client.get("/aluno/nova-requisicao").get_data(as_text=True)
    pattern = r'/static/(?:css/[\w/.-]+\.css|js/direct-upload\.js)\?v=([\w.-]+)'
    versions = {page: set(re.findall(pattern, html)) for page, html in (("admin", admin), ("aluno", aluno))}
    # form.css, modern-style.css and direct-upload.js changed: a returning
    # browser must not keep batch 1's cached copies.
    assert len(versions["admin"]) == 1 and versions["admin"] == versions["aluno"], versions
    assert versions["aluno"].isdisjoint({"20260516-tooltip-dark-v1", "20261016-ui-batch1-v1"}), versions
    assert "js/direct-upload.js?v=" in admin and "js/direct-upload.js?v=" in aluno


def test_upload_client_has_no_text_buttons_and_hides_retry_semantically():
    source = (ROOT / "static/js/direct-upload.js").read_text(encoding="utf-8")
    assert "textContent = 'Tentar novamente'" not in source and "textContent = 'Remover'" not in source
    assert "btn btn-secondary btn-sm" not in source
    assert "entry.retryButton.hidden = entry.state !== 'error'" in source
    css = (ROOT / "static/css/components/form.css").read_text(encoding="utf-8")
    assert ".file-list-action[hidden]{ display:none; }" in css


# ===================================================== 2. suggested hours

STATE = """JSON.stringify((() => { const a = document.getElementById('atividade_versao_id_select');
  const h = document.querySelector('[name=horas_solicitadas]');
  return {activity: a ? a.value : null, hours: h.value, readOnly: h.readOnly}; })())"""


def _state(session):
    return json.loads(session.evaluate(STATE))


def _change(session, selector, value):
    session.evaluate("(() => { const e = document.querySelector(%s); e.value = %s;"
                     " e.dispatchEvent(new Event('change', {bubbles: true})); return true; })()"
                     % (json.dumps(selector), json.dumps(value)))


def _type_hours(session, value):
    session.evaluate("(() => { const h = document.querySelector('[name=horas_solicitadas]'); h.focus(); h.select(); return true; })()")
    session.call("Input.insertText", {"text": value})
    session.pump(0.1)


@pytest.fixture
def hours_page(env):
    identity = _as_student(env["client"])
    session = _session(env["client"])
    try:
        session.goto("/aluno/nova-requisicao")
        options = json.loads(session.evaluate(
            "JSON.stringify(Array.from(document.getElementById('atividade_versao_id_select').options)"
            ".filter(o => o.dataset.tipo === 'Acadêmica Complementar' && /^1 - /.test(o.dataset.grupo || ''))"
            ".map(o => [o.value, o.dataset.defaultHours]))"))
        with_default = [o for o in options if o[1]]
        without = [o for o in options if not o[1]]
        assert len({d for _v, d in with_default}) >= 2 and len(without) >= 2, options
        yield session, identity, with_default, without
    finally:
        session.close()


@browser
def test_suggested_hours_follow_the_activity_and_never_erase_typed_hours(hours_page):
    session, _identity, with_default, without = hours_page
    first = next(o for o in with_default)
    second = next(o for o in with_default if o[1] != first[1])
    _change(session, "#tipo_atividade_select", "Acadêmica Complementar")
    _change(session, "#grupo_num", "1")
    _change(session, "#atividade_versao_id_select", first[0])
    assert _state(session)["hours"] == first[1]
    _change(session, "#atividade_versao_id_select", second[0])
    assert _state(session)["hours"] == second[1]
    # A stale suggestion is cleared when the new activity has none ...
    _change(session, "#atividade_versao_id_select", without[0][0])
    assert _state(session)["hours"] == ""
    # ... but hours the student typed are kept when nothing replaces them (the defect).
    _type_hours(session, "7.5")
    _change(session, "#atividade_versao_id_select", without[1][0])
    assert _state(session) == {"activity": without[1][0], "hours": "7.5", "readOnly": False}
    # An edited suggestion is the student's value too.
    _change(session, "#atividade_versao_id_select", first[0])
    _type_hours(session, "2.25")
    _change(session, "#atividade_versao_id_select", without[0][0])
    assert _state(session)["hours"] == "2.25"
    # A new suggestion still replaces the field: the hours belong to the new activity.
    _change(session, "#atividade_versao_id_select", second[0])
    assert _state(session)["hours"] == second[1]
    # Tipo / Grupo changes clear the activity; a suggestion goes with it, typed hours stay.
    _change(session, "#grupo_num", "")
    assert _state(session) == {"activity": "", "hours": "", "readOnly": False}
    _change(session, "#grupo_num", "1")
    _type_hours(session, "4")
    _change(session, "#tipo_atividade_select", "Extensão Universitária")
    assert _state(session)["activity"] == "" and _state(session)["hours"] == "4"


def _post_form(session, fields):
    session.evaluate("""(() => { const f = document.createElement('form'); f.method = 'post'; f.action = '/aluno/nova-requisicao';
      Object.entries(%s).forEach(([n, v]) => { const i = document.createElement('input'); i.type = 'hidden'; i.name = n; i.value = v; f.appendChild(i); });
      document.body.appendChild(f); f.submit(); return true; })()""" % json.dumps(fields))
    session.pump(0.8)
    session.wait_for("document.readyState === 'complete' && !!document.querySelector('[name=horas_solicitadas]')")


@browser
def test_validation_recovery_keeps_the_typed_hours(hours_page):
    session, _identity, with_default, _without = hours_page
    base = {"nome_evento": "Recuperacao b2", "data_evento": "2026-09-01", "horas_solicitadas": "3.25"}
    # No activity: the form returns with Tipo/Grupo and the typed hours, not a suggestion.
    _post_form(session, {**base, "tipo_atividade": "Acadêmica Complementar", "grupo": "1", "atividade_versao_id": ""})
    assert "Selecione uma atividade válida." in session.evaluate("document.body.textContent")
    assert _state(session)["hours"] == "3.25"
    # An activity that contradicts the Tipo: the activity is dropped, the hours stay.
    _post_form(session, {**base, "tipo_atividade": "Extensão Universitária", "grupo": "1",
                         "atividade_versao_id": with_default[0][0]})
    assert _state(session) == {"activity": "", "hours": "3.25", "readOnly": False}
    assert _sql("SELECT COUNT(*) FROM requisicoes WHERE nome_evento='Recuperacao b2'")[0][0] == 0


@browser
def test_edit_mode_keeps_stored_hours_and_read_only_mode_is_inert(hours_page):
    session, identity, with_default, without = hours_page
    _change(session, "#tipo_atividade_select", "Acadêmica Complementar")
    _change(session, "#grupo_num", "1")
    _change(session, "#atividade_versao_id_select", with_default[0][0])
    _type_hours(session, "9.5")
    session.evaluate("(() => { const f = document.getElementById('atividade_versao_id_select').form;"
                     " f.querySelector('[name=nome_evento]').value = 'Editavel b2';"
                     " f.querySelector('[name=data_evento]').value = '2026-09-02'; f.requestSubmit(); return true; })()")
    session.pump(1.5)
    (request_id, stored), = _sql("SELECT id, horas_solicitadas FROM requisicoes WHERE nome_evento='Editavel b2' AND aluno_id=?",
                                 (identity["aluno_id"],))
    assert stored == 9.5
    session.goto(f"/aluno/requisicoes/{request_id}?edit=1")
    assert _state(session) == {"activity": with_default[0][0], "hours": "9.5", "readOnly": False}
    # The stored hours are not erased by an activity without a suggestion (the defect) ...
    _change(session, "#atividade_versao_id_select", without[0][0])
    assert _state(session)["hours"] == "9.5"
    # ... and a suggestion still applies.
    _change(session, "#atividade_versao_id_select", with_default[0][0])
    assert _state(session)["hours"] == with_default[0][1]

    session.goto(f"/aluno/requisicoes/{request_id}?view=1")
    assert _state(session) == {"activity": None, "hours": "9.5", "readOnly": True}
    _change(session, "#tipo_atividade_select", "Extensão Universitária")
    assert _state(session)["hours"] == "9.5"


# ================================================= 3. decision buttons

DECISIONS = """JSON.stringify(Array.from(document.querySelectorAll(%s)).filter(b => getComputedStyle(b).display !== 'none').map(b => {
  const r = b.getBoundingClientRect(), cs = getComputedStyle(b), i = b.querySelector('svg, .lucide'), l = b.querySelector('.btn-label');
  const ir = i.getBoundingClientRect(), lr = l.getBoundingClientRect();
  const token = t => { const d = document.createElement('div'); d.style.color = 'var(' + t + ')'; document.body.appendChild(d);
                       const c = getComputedStyle(d).color; d.remove(); return c; };
  const family = b.classList.contains('btn-indeferir') ? 'negative' : b.classList.contains('btn-parcial') ? 'caution' : 'positive';
  return {label: l.textContent, action: b.dataset.action || b.dataset.processStatus, pressed: b.getAttribute('aria-pressed'),
    h: r.height, top: Math.round(r.top), radius: cs.borderTopLeftRadius, pad: cs.paddingLeft + ' ' + cs.paddingRight,
    color: cs.color, bg: cs.backgroundColor, edge: cs.borderTopColor, edgeWidth: cs.borderTopWidth,
    ink: token('--status-' + family + '-text'), dot: token('--status-' + family + '-dot'),
    icon: ir.width, iconGap: +(lr.left - ir.right).toFixed(2), iconCy: +((ir.top + ir.bottom) / 2 - (r.top + r.bottom) / 2).toFixed(2)};
}))"""
REFERENCE = """JSON.stringify((() => { const b = document.querySelector(%s), cs = getComputedStyle(b), r = b.getBoundingClientRect();
  const i = b.querySelector('svg, .lucide').getBoundingClientRect(), l = b.querySelector('.btn-label').getBoundingClientRect();
  return {h: r.height, radius: cs.borderTopLeftRadius, pad: cs.paddingLeft + ' ' + cs.paddingRight, icon: i.width,
          iconGap: +(l.left - i.right).toFixed(2), iconCy: +((i.top + i.bottom) / 2 - (r.top + r.bottom) / 2).toFixed(2)}; })())"""
WHITE = "rgb(255, 255, 255)"


def _decisions(session, selector):
    # Park the pointer away from the buttons: a hovered one is tinted, not idle.
    session.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": 1, "y": 1})
    session.pump(0.25)
    return json.loads(session.evaluate(DECISIONS % json.dumps(selector)))


def _assert_standard_geometry(buttons, reference):
    assert buttons
    for b in buttons:
        # Ordinary .btn geometry: the same box, corner, padding, icon size, gap and nudge as a plain .btn.
        assert {k: b[k] for k in reference} == reference, (b, reference)
    assert len({b["top"] for b in buttons}) == 1


def _assert_idle(b):
    assert b["pressed"] == "false" and b["bg"] == WHITE and b["color"] == b["ink"] and b["edge"] == b["dot"], b


def _assert_selected(b):
    assert b["pressed"] == "true" and b["bg"] == b["ink"] and b["edge"] == b["ink"] and b["color"] == WHITE, b


@pytest.fixture
def process_modal(env):
    client = env["client"]
    login_admin(client)
    _r, first = create_admin_request(client, "Decisao b2 um")
    _r, second = create_admin_request(client, "Decisao b2 dois")
    session = _session(client)
    try:
        session.goto("/admin/requisicoes", "document.readyState === 'complete' && !!window.__openExistingReqModal")
        yield session, first["id"], second["id"]
    finally:
        session.close()


def _open_process(session, request_id):
    session.evaluate(f"window.__openExistingReqModal('{request_id}', 'process')")
    session.wait_for("(() => { const m = document.getElementById('req-modal');"
                     f" return !m.hidden && m.dataset.reqId === '{request_id}' && !document.getElementById('m_footer_process_row').hidden; }})()")


@browser
def test_modal_decision_buttons_geometry_colour_and_selection(process_modal):
    session, first, second = process_modal
    _open_process(session, first)
    row = "#m_footer_process_row button[data-action]"
    idle = _decisions(session, row)
    assert [b["label"] for b in idle] == ["Indeferir", "Deferir Parcialmente", "Deferir"]
    _assert_standard_geometry(idle, json.loads(session.evaluate(REFERENCE % json.dumps("#m_footer_back"))))
    for b in idle:
        _assert_idle(b)

    session.click("#m_footer_process_row [data-action=deferir_parte]")
    session.pump(0.4)
    chosen = _decisions(session, "#m_footer_actions button[data-action]")
    assert [b["label"] for b in chosen] == ["Deferir Parcialmente"]
    _assert_selected(chosen[0])
    assert session.evaluate("document.getElementById('m_proc_horas_row').hidden") is False
    assert session.evaluate("document.activeElement.id") == "m_horas_deferidas"

    # Cancelar restores the idle trio.
    session.click("#m_footer_cancel")
    session.pump(0.3)
    for b in _decisions(session, row):
        _assert_idle(b)

    # Closing mid-confirmation and opening another request starts clean (the defect).
    session.click("#m_footer_process_row [data-action=indeferir]")
    session.pump(0.3)
    session.evaluate("document.getElementById('req-modal-close').click(); true")
    session.wait_for("document.getElementById('req-modal').hidden")
    _open_process(session, second)
    again = _decisions(session, row)
    assert [b["label"] for b in again] == ["Indeferir", "Deferir Parcialmente", "Deferir"]
    for b in again:
        _assert_idle(b)
    assert session.evaluate("document.getElementById('m_footer_confirm_row').hidden") is True

    # Keyboard: focus shows the ring, Enter selects.
    session.evaluate("document.querySelector('#m_footer_process_row [data-action=deferir]').focus(); true")
    _key(session, "Shift", "ShiftLeft", 16)  # make the programmatic focus keyboard-modality
    ring = session.evaluate("(() => { const cs = getComputedStyle(document.activeElement);"
                            " return cs.outlineStyle + ' ' + cs.outlineWidth; })()")
    assert ring == "solid 2px", ring
    _enter(session)
    selected = _decisions(session, "#m_footer_actions button[data-action]")
    assert [b["label"] for b in selected] == ["Deferir"]
    _assert_selected(selected[0])


@browser
def test_modal_partial_hours_validation_and_submission_are_unchanged(process_modal):
    session, first, _second = process_modal
    _open_process(session, first)
    session.click("#m_footer_process_row [data-action=deferir_parte]")
    session.pump(0.3)
    session.requests.clear()
    session.click("#m_footer_confirm")
    session.pump(0.5)
    # No hours: nothing is sent; the hours field is offered again.
    assert [p for m, p, _b in session.requests if m == "POST"] == []
    assert session.evaluate("document.activeElement.id") == "m_horas_deferidas"
    session.evaluate("document.getElementById('m_horas_deferidas').value = '1'; true")
    session.click("#m_footer_confirm")
    session.pump(0.5)
    # Hours but no justification: still nothing.
    assert [p for m, p, _b in session.requests if m == "POST"] == []
    session.evaluate("document.getElementById('m_justificativa').value = 'Parcial por limite'; true")
    session.click("#m_footer_confirm")
    session.pump(1.5)
    posts = [(p, parse_qs(b)) for m, p, b in session.requests if m == "POST"]
    (shown,), = _sql("SELECT atividade_versao_id FROM requisicoes WHERE id=?", (first,))
    # The decision also names the classification the modal showed (MP-3 A22).
    assert posts == [(f"/admin/processar_requisicao/{first}",
                      {"status": ["Deferida Parcialmente"], "atividade_versao_id_registrada": [str(shown)],
                       "horas_deferidas": ["1"], "observacao": ["Parcial por limite"]})]
    (status, hours), = _sql("SELECT status, horas_deferidas FROM requisicoes WHERE id=?", (first,))
    assert (status, hours) == ("Deferida Parcialmente", 1)


@browser
def test_standalone_processar_page_uses_the_same_decision_buttons(env):
    client = env["client"]
    login_admin(client)
    _r, row = create_admin_request(client, "Decisao b2 pagina")
    session = _session(client)
    try:
        session.goto(f"/admin/processar_requisicao/{row['id']}")
        buttons = ".process-action-buttons .btn"
        idle = _decisions(session, buttons)
        assert [b["label"] for b in idle] == ["Deferir", "Deferir Parcialmente", "Indeferir"]
        # This page has no other icon .btn to compare with: the modal-measured .btn values
        # (the icon centred on the button: the former -0.75px nudge put it above the capitals).
        _assert_standard_geometry(idle, {"h": 32, "radius": "4px", "pad": "10px 10px", "icon": 15,
                                         "iconGap": 6, "iconCy": 0})
        for b in idle:
            _assert_idle(b)

        state = "JSON.stringify({status: document.getElementById('status-hidden').value," \
                " shown: document.getElementById('horas-label').style.display !== 'none'," \
                " required: document.getElementById('horas-deferidas').required," \
                " disabled: document.getElementById('horas-deferidas').disabled," \
                " hours: document.getElementById('horas-deferidas').value})"
        session.click(".process-action-buttons [data-process-status='Deferida Parcialmente']")
        session.pump(0.2)
        pressed = {b["label"]: b["pressed"] for b in _decisions(session, buttons)}
        assert pressed == {"Deferir": "false", "Deferir Parcialmente": "true", "Indeferir": "false"}
        _assert_selected(next(b for b in _decisions(session, buttons) if b["pressed"] == "true"))
        assert json.loads(session.evaluate(state)) == {"status": "Deferida Parcialmente", "shown": True,
                                                       "required": True, "disabled": False, "hours": ""}
        session.evaluate("document.getElementById('horas-deferidas').value = '2'; true")
        session.click(".process-action-buttons [data-process-status='Deferida']")
        session.pump(0.2)
        assert json.loads(session.evaluate(state)) == {"status": "Deferida", "shown": False,
                                                       "required": False, "disabled": True, "hours": ""}
        session.click(".process-action-buttons [data-process-status='Deferida Parcialmente']")
        session.evaluate("document.getElementById('horas-deferidas').value = '2';"
                         " document.querySelector('textarea[name=observacao]').value = 'Parcial';"
                         " document.querySelector('.process-form-actions [type=submit]').click(); true")
        session.pump(1.5)
        (status, hours), = _sql("SELECT status, horas_deferidas FROM requisicoes WHERE id=?", (row["id"],))
        assert (status, hours) == ("Deferida Parcialmente", 2)
    finally:
        session.close()


def test_decision_buttons_are_owned_by_the_button_contract_with_status_tokens():
    page = (ROOT / "templates/admin_requisicoes.html").read_text(encoding="utf-8")
    injected = page.split("const style = document.createElement('style');", 1)[1].split("document.head.appendChild(style);", 1)[0]
    assert not re.search(r"\.btn-(action-ghost|indeferir|parcial|deferir)\s*[{:]", injected)
    assert not re.search(r"#B8534C|#9C7132|#5C9A7F", page, re.I)
    css = (ROOT / "static/css/modern-style.css").read_text(encoding="utf-8")
    block = css.split("/* Decision buttons", 1)[1].split("/* Disabled", 1)[0]
    rules = re.sub(r"/\*.*?\*/", "", block, flags=re.S)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", rules), "decision colours come from --status-* tokens only"
    assert '[aria-pressed="true"]' in rules
    for family in ("negative", "caution", "positive"):
        assert f"--status-{family}-text" in rules and f"--status-{family}-dot" in rules
    # Six decision buttons, each a toggle that starts unpressed.
    assert len(re.findall(r'data-role="process-action" aria-pressed="false"', page)) == 6
    standalone = (ROOT / "templates/admin_processar_requisicao.html").read_text(encoding="utf-8")
    assert standalone.count('aria-pressed="false"') == 3 and "classList.add('primary')" not in standalone
