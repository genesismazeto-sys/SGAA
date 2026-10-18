"""UI corrections, batch 3: administrative form alignment.

1. Upload labels. In the Requisições and Arquivos modals the direct-upload
   feedback (file list + status line) sat inside the upload card's .form-row.
   .row-label is absolutely positioned and centred on its row, so every
   attachment row re-centred "Comprovantes" / "Arquivo" further below its
   field (measured +12.5px with nothing listed, +83.6px with four files), and
   the gap to the next field varied (37px / 24.5px). The feedback is now the
   row's next sibling in the form grid -- the form.css FILE LIST contract the
   student surfaces already follow -- so the label is centred on the card in
   every state (stacked above it below 720px), the list spans the card's
   edges 6px under it, and the next field is one 12px row-gap away. In the
   Requisições modal the feedback hides with the upload row outside
   Criar/Editar (.form-note gained the [hidden] rule .file-list already had).
2. Standalone Processar: "Horas deferidas" uses the DS field structure (the
   modal's: label column, compact field card, timer chip, .control) with the
   same name/type/step/min, visibility, required and disabled behaviour.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import parse_qs

import pytest

import main
from tests.canonical_request_documents_support import canonical_documents
from tests.canonical_request_test_support import create_admin_request, login_admin
from tests.cdp_browser_support import BrowserSession, find_chromium
from tests.test_comprovantes_google_drive import PDF, PNG, FakeStorage
from tests.versioned_test_support import isolated_versioned_app_env

ROOT = Path(__file__).resolve().parents[1]
CHROMIUM = find_chromium()
browser = pytest.mark.skipif(CHROMIUM is None, reason="no headless Chromium available")
LONG_FILE = "comprovante-de-participacao-no-congresso-brasileiro-de-aviacao-civil-2026-certificado-final.pdf"


@pytest.fixture
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "ui-batch3.db") as environment:
        original = main.app.extensions.get("comprovante_storage")
        main.app.extensions["comprovante_storage"] = FakeStorage()
        try:
            with canonical_documents(main.app):
                login_admin(environment["client"])
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
    (folder / "b.png").write_bytes(PNG)
    (folder / LONG_FILE).write_bytes(PDF)
    return folder


def _sql(query, params=()):
    with main.app.app_context():
        conn = main.get_db_connection()
        rows = conn.execute(query, params).fetchall()
        conn.commit()
        return rows


def _session(client, width):
    session = BrowserSession(client, CHROMIUM)
    session.call("Emulation.setDeviceMetricsOverride",
                 {"width": width, "height": 900, "deviceScaleFactor": 1, "mobile": False})
    return session


def _pick(session, selector, files):
    node = session.call("Runtime.evaluate", {"expression": f"document.querySelector({json.dumps(selector)})"})
    session.call("DOM.setFileInputFiles", {"files": [str(f) for f in files], "objectId": node["result"]["objectId"]})
    session.pump(0.5)


def _key(session, key, code, vk, text=None, modifiers=0):
    down = {"type": "keyDown" if text else "rawKeyDown", "key": key, "code": code,
            "windowsVirtualKeyCode": vk, "modifiers": modifiers}
    if text:
        down["text"] = text
    session.call("Input.dispatchKeyEvent", down)
    session.call("Input.dispatchKeyEvent", {**down, "type": "keyUp"})
    session.pump(0.2)


# ============================================================ 1. upload labels

# tus stand-in: 'hang' keeps an upload in progress, 'ok' completes it, and the
# finalize call answers verified -- so uploading, failed and completed rows
# can all be listed without a storage provider.
STUB = """(() => { window.__tusMode = 'hang';
  window.tus.Upload = function(file, opts){ this.start = () => { if (window.__tusMode === 'ok')
    setTimeout(() => { opts.onProgress(1, 1); opts.onSuccess(); }, 30); }; };
  const real = window.fetch;
  window.fetch = function(url){ if (/\\/finalize$/.test(String(url)))
    return Promise.resolve(new Response(JSON.stringify({state: 'verified'}), {status: 200, headers: {'Content-Type': 'application/json'}}));
    return real.apply(this, arguments); };
  return true; })()"""

MEASURE = """JSON.stringify((() => {
  const input = document.querySelector(%s);
  const row = input.closest('.form-row'), label = row.querySelector(':scope > .row-label');
  const card = input.closest('[data-upload-card],[data-file-card]');
  const list = input.form.querySelector('[data-direct-upload-list]'), status = input.form.querySelector('[data-direct-upload-status]');
  const next = document.querySelector(%s).closest('.form-row');
  const grid = parseFloat(getComputedStyle(row.parentElement).rowGap);
  const box = e => e.getBoundingClientRect();
  const range = document.createRange(); range.selectNodeContents(label);
  const shown = [card, list, status].filter(e => box(e).height > 0 && getComputedStyle(e).position !== 'absolute');
  const lb = box(label), cb = box(card), lsb = box(list);
  const items = Array.from(list.querySelectorAll('li'));
  return {states: items.map(li => li.dataset.state), rowGap: grid,
    feedbackInRow: !!(list.closest('.form-row') || status.closest('.form-row')),
    stacked: getComputedStyle(label).position === 'static',
    labelToCardCentre: (lb.top + lb.bottom) / 2 - (cb.top + cb.bottom) / 2,
    labelBottomToCardTop: cb.top - lb.bottom,
    labelLines: new Set(Array.from(range.getClientRects()).map(x => Math.round(x.top))).size,
    list: items.length ? {left: lsb.left - cb.left, right: lsb.right - cb.right, gap: lsb.top - cb.bottom} : null,
    gapToNext: box(next).top - box(shown[shown.length - 1]).bottom,
    overflow: document.documentElement.scrollWidth > innerWidth || items.some(li => li.scrollWidth > li.clientWidth + 1)};
})())"""

MODALS = {
    "requisicoes": ("/admin/requisicoes", "#m_comprovantes_files", "#req-form textarea[name=observacao]"),
    "arquivos": ("/admin/arquivos", "#admin-arquivo-input", "#admin-arquivo-titulo"),
}


def _open_modal(session, name):
    path, selector, _next = MODALS[name]
    if name == "requisicoes":
        session.goto(path, "document.readyState === 'complete' && !!window.__openAdminNewReqModal")
        session.evaluate(STUB)
        session.evaluate("window.__openAdminNewReqModal(); true")
    else:
        session.goto(path)
        session.evaluate(STUB)
    return selector


def _visible(selector):
    return ("(() => document.querySelector(%s).closest('[data-upload-card],[data-file-card]')"
            ".getBoundingClientRect().height > 0)()" % json.dumps(selector))


def _assert_label_holds(state, width):
    assert not state["feedbackInRow"], state
    assert state["labelLines"] == 1 and not state["overflow"], state
    if width > 720:
        # Label column: centred on the upload card, whatever is listed under it.
        assert not state["stacked"] and abs(state["labelToCardCentre"]) <= 0.5, state
    else:
        # Stacked contract: the label sits right above its card.
        assert state["stacked"] and 0 <= state["labelBottomToCardTop"] <= 4.5, state
    if state["list"]:
        assert abs(state["list"]["left"]) <= 0.5 and abs(state["list"]["right"]) <= 0.5, state
        assert abs(state["list"]["gap"] - state["rowGap"] / 2) <= 0.5, state
    # The next field is one form row-gap below the last visible part of the upload section.
    assert abs(state["gapToNext"] - state["rowGap"]) <= 0.5, state


@browser
@pytest.mark.parametrize("width", [1440, 768, 640])
def test_requisicoes_comprovantes_label_stays_on_its_field_as_attachments_change(env, picks, width):
    session = _session(env["client"], width)
    _path, selector, nxt = MODALS["requisicoes"]
    try:
        _open_modal(session, "requisicoes")
        session.wait_for(_visible(selector))
        session.pump(0.3)
        measure = lambda: json.loads(session.evaluate(MEASURE % (json.dumps(selector), json.dumps(nxt))))
        trail = [measure()]
        _pick(session, selector, [picks / "a.pdf"])
        trail.append(measure())
        _pick(session, selector, [picks / "bad.txt", picks / LONG_FILE])
        trail.append(measure())
        session.evaluate("window.__tusMode = 'ok'; true")
        _pick(session, selector, [picks / "b.png"])
        session.pump(0.5)
        trail.append(measure())
        while session.evaluate("document.querySelectorAll('[data-direct-upload-list] li').length"):
            session.evaluate("document.querySelector('[data-direct-upload-list] .file-list-remove').click(); true")
            session.pump(0.2)
        trail.append(measure())
        assert [t["states"] for t in trail] == [
            [], ["uploading"], ["uploading", "error", "uploading"],
            ["uploading", "error", "uploading", "verified"], []]
        for state in trail:
            _assert_label_holds(state, width)
        # Relative to its card the label never moves by even a fraction of a pixel.
        key = "labelToCardCentre" if width > 720 else "labelBottomToCardTop"
        assert max(t[key] for t in trail) - min(t[key] for t in trail) <= 0.05, trail
    finally:
        session.close()


@browser
@pytest.mark.parametrize("width", [1440, 768, 640])
def test_arquivos_label_stays_on_its_field_as_the_file_changes(env, picks, width):
    session = _session(env["client"], width)
    _path, selector, nxt = MODALS["arquivos"]
    try:
        _open_modal(session, "arquivos")
        # The modal opens on the first pick (Adicionar opens the file chooser).
        _pick(session, selector, [picks / "a.pdf"])
        session.wait_for(_visible(selector))
        measure = lambda: json.loads(session.evaluate(MEASURE % (json.dumps(selector), json.dumps(nxt))))
        trail = [measure()]
        _pick(session, selector, [picks / "bad.txt"])
        trail.append(measure())
        session.evaluate("window.__tusMode = 'ok'; true")
        _pick(session, selector, [picks / "b.png"])
        session.pump(0.5)
        trail.append(measure())
        session.evaluate("document.querySelector('[data-direct-upload-list] .file-list-remove').click(); true")
        session.pump(0.2)
        trail.append(measure())
        assert [t["states"] for t in trail] == [["uploading"], ["error"], ["verified"], []]
        for state in trail:
            _assert_label_holds(state, width)
        key = "labelToCardCentre" if width > 720 else "labelBottomToCardTop"
        assert max(t[key] for t in trail) - min(t[key] for t in trail) <= 0.05, trail
    finally:
        session.close()


@browser
def test_requisicoes_upload_feedback_hides_with_its_row_outside_criar_editar(env, picks):
    _response, row = create_admin_request(env["client"], "Batch3 pendente")
    session = _session(env["client"], 1440)
    _path, selector, _nxt = MODALS["requisicoes"]
    feedback = ("JSON.stringify(Array.from(document.querySelectorAll('#req-form [data-upload-feedback]'))"
                ".map(e => ({hidden: e.hidden, display: getComputedStyle(e).display})))")
    try:
        _open_modal(session, "requisicoes")
        session.wait_for(_visible(selector))
        _pick(session, selector, [picks / "a.pdf"])
        shown = json.loads(session.evaluate(feedback))
        assert len(shown) == 2 and all(not e["hidden"] and e["display"] != "none" for e in shown), shown
        session.evaluate("document.getElementById('req-modal-close').click(); true")
        session.wait_for("document.getElementById('req-modal').hidden")
        for mode in ("view", "process"):
            session.evaluate(f"window.__openExistingReqModal('{row['id']}', '{mode}')")
            session.wait_for(f"document.getElementById('req-modal').getAttribute('data-mode') === '{mode}'")
            session.pump(0.4)
            assert session.evaluate("document.getElementById('m_upload_row').hidden") is True
            hidden = json.loads(session.evaluate(feedback))
            assert all(e["hidden"] and e["display"] == "none" for e in hidden), (mode, hidden)
            session.evaluate("document.getElementById('req-modal-close').click(); true")
            session.wait_for("document.getElementById('req-modal').hidden")
        session.evaluate("window.__openAdminNewReqModal(); true")
        session.wait_for(_visible(selector))
        assert all(not e["hidden"] for e in json.loads(session.evaluate(feedback)))
    finally:
        session.close()


def test_both_admin_modals_keep_upload_feedback_out_of_the_label_row():
    for page, row_marker in (("admin_requisicoes.html", 'id="m_upload_row"'),
                             ("admin_arquivos.html", 'id="admin-arquivo-input"')):
        source = (ROOT / "templates" / page).read_text(encoding="utf-8")
        start = source.rindex('<div class="form-row"', 0, source.index(row_marker) + 1)
        # Balance the row's <div>s: the feedback list must come after it closes.
        depth, pos = 0, start
        for match in re.finditer(r"<(/?)div\b", source[start:]):
            depth += -1 if match.group(1) else 1
            if depth == 0:
                pos = start + match.end()
                break
        row = source[start:pos]
        assert "data-direct-upload-list" not in row and "data-direct-upload-status" not in row, page
        after = source[pos:pos + 900]
        assert after.index("data-direct-upload-list") < after.index("data-direct-upload-status"), page
    assert "direct-upload-feedback" not in (ROOT / "templates/admin_requisicoes.html").read_text(encoding="utf-8")


def test_form_note_hidden_rule_changes_no_existing_consumer():
    css = (ROOT / "static/css/components/form.css").read_text(encoding="utf-8")
    assert re.search(r"\.file-list\[hidden\],\s*\.form-note\[hidden\]\{ display:none; \}", css)
    # Before batch 3 no template rendered a hidden .form-note and no script hid one
    # (a hidden .form-note would have stayed visible: .form-note is display:flex).
    # The only consumer of the new rule is the Requisições upload status line.
    hidden_notes = []
    for path in (ROOT / "templates").rglob("*.html"):
        for tag in re.findall(r"<[a-z]+\b[^>]*\bform-note\b[^>]*>", path.read_text(encoding="utf-8")):
            if re.search(r"\shidden(\s|>|=)", tag):
                hidden_notes.append((path.name, tag))
    assert hidden_notes == []
    togglers = [p.name for p in (ROOT / "templates").rglob("*.html") if "[data-upload-feedback]" in p.read_text(encoding="utf-8")]
    assert togglers == ["admin_requisicoes.html"]
    assert not any("form-note" in p.read_text(encoding="utf-8") for p in (ROOT / "static/js").rglob("*.js"))


# ================================================ 2. standalone Processar hours

HOURS = """JSON.stringify((() => {
  const input = document.getElementById('horas-deferidas'), wrap = document.getElementById('horas-label');
  const row = input.closest('.form-row'), label = row && row.querySelector(':scope > .row-label');
  const card = input.closest('.field-card'), chip = card && card.querySelector(':scope > .field-chip');
  const box = e => e.getBoundingClientRect();
  const range = document.createRange(); range.selectNodeContents(label);
  const buttons = document.querySelector('.process-action-buttons'), obs = document.querySelector('textarea[name=observacao]').closest('label');
  return {status: document.getElementById('status-hidden').value, shown: getComputedStyle(wrap).display !== 'none',
    required: input.required, disabled: input.disabled, value: input.value,
    attrs: [input.name, input.type, input.step, input.min, input.className],
    structure: [wrap.classList.contains('form-cards-narrow'), !!row, !!label && label.htmlFor === 'horas-deferidas',
                !!card && card.classList.contains('is-compact'), !!chip && !!chip.querySelector('svg.lucide-timer, [data-lucide=timer]')],
    label: label.textContent.trim(), labelLines: new Set(Array.from(range.getClientRects()).map(x => Math.round(x.top))).size,
    marker: getComputedStyle(label, '::after').content,
    stacked: getComputedStyle(label).position === 'static',
    labelToCardCentre: (box(label).top + box(label).bottom) / 2 - (box(card).top + box(card).bottom) / 2,
    labelBottomToCardTop: box(card).top - box(label).bottom,
    cardHeight: box(card).height, chipWidth: box(chip).width,
    above: (wrap.getBoundingClientRect().height ? box(row).top : 0) - box(buttons).bottom,
    below: box(obs).top - box(card).bottom,
    overflow: document.documentElement.scrollWidth > innerWidth};
})())"""


def _hours(session):
    return json.loads(session.evaluate(HOURS))


def _choose(session, status):
    session.click(f".process-action-buttons [data-process-status='{status}']")
    session.pump(0.2)


@browser
@pytest.mark.parametrize("width", [1440, 768, 640])
def test_standalone_hours_field_uses_the_ds_field_in_every_decision_state(env, width):
    _response, row = create_admin_request(env["client"], "Batch3 standalone")
    session = _session(env["client"], width)
    try:
        session.goto(f"/admin/processar_requisicao/{row['id']}")
        idle = _hours(session)
        assert idle["shown"] is False and idle["required"] is False
        assert idle["attrs"] == ["horas_deferidas", "number", "0.01", "0", "control"]
        assert idle["structure"] == [True, True, True, True, True]

        _choose(session, "Deferida Parcialmente")
        partial = _hours(session)
        assert (partial["status"], partial["shown"], partial["required"], partial["disabled"]) == (
            "Deferida Parcialmente", True, True, False)
        assert partial["label"] == "Horas deferidas" and partial["labelLines"] == 1
        assert partial["marker"] not in ("none", "normal", ""), "the DS required marker shows on the label"
        assert partial["cardHeight"] == 32 and partial["chipWidth"] == 40 and not partial["overflow"]
        if width > 720:
            assert not partial["stacked"] and abs(partial["labelToCardCentre"]) <= 0.5, partial
        else:
            assert partial["stacked"] and 0 <= partial["labelBottomToCardTop"] <= 4.5, partial
        # The DS 12px row rhythm on both sides of the field.
        assert abs(partial["above"] - 12) <= 0.5 and abs(partial["below"] - 12) <= 0.5, partial

        session.evaluate("document.getElementById('horas-deferidas').value = '2'; true")
        for status in ("Deferida", "Indeferida"):
            _choose(session, status)
            other = _hours(session)
            assert (other["status"], other["shown"], other["required"], other["disabled"], other["value"]) == (
                status, False, False, True, ""), other
    finally:
        session.close()


@browser
def test_standalone_partial_needs_its_hours_and_the_other_decisions_still_submit(env):
    client = env["client"]
    _r, partial_row = create_admin_request(client, "Batch3 parcial")
    _r, full_row = create_admin_request(client, "Batch3 deferida")
    _r, rejected_row = create_admin_request(client, "Batch3 indeferida")
    session = _session(client, 1440)
    try:
        session.goto(f"/admin/processar_requisicao/{partial_row['id']}")
        _choose(session, "Deferida Parcialmente")
        session.requests.clear()
        session.click(".process-form-actions [type=submit]")
        session.pump(0.6)
        # The browser refuses the submit: the required hours are missing.
        assert [p for m, p, _b in session.requests if m == "POST"] == []
        assert session.evaluate("document.getElementById('horas-deferidas').validity.valueMissing") is True
        assert session.evaluate("document.activeElement.id") == "horas-deferidas"
        assert session.evaluate("document.querySelector('#horas-label .field-card').matches(':focus-within')") is True
        # Keyboard: type the hours where focus already is and submit with Enter.
        session.call("Input.insertText", {"text": "1.5"})
        _key(session, "Enter", "Enter", 13, "\r")
        session.pump(1.0)
        posts = [parse_qs(b) for m, p, b in session.requests if m == "POST"]
        assert len(posts) == 1 and posts[0]["status"] == ["Deferida Parcialmente"] and posts[0]["horas_deferidas"] == ["1.5"]
        assert tuple(_sql("SELECT status, horas_deferidas FROM requisicoes WHERE id=?", (partial_row["id"],))[0]) == (
            "Deferida Parcialmente", 1.5)

        for row, status in ((full_row, "Deferida"), (rejected_row, "Indeferida")):
            session.goto(f"/admin/processar_requisicao/{row['id']}")
            # Keyboard selection of the decision: focus the button, Enter.
            session.evaluate(f"document.querySelector(\".process-action-buttons [data-process-status='{status}']\").focus(); true")
            _key(session, "Enter", "Enter", 13, "\r")
            assert session.evaluate("document.activeElement.getAttribute('aria-pressed')") == "true"
            session.requests.clear()
            session.click(".process-form-actions [type=submit]")
            session.pump(1.0)
            if status == "Indeferida":
                # Indeferir first asks: correction or definitive rejection
                # (tests/test_request_rectification_flow.py); nothing is sent yet.
                assert [p for m, p, _b in session.requests if m == "POST"] == []
                session.wait_for("!document.getElementById('rejection-decision-dialog').hidden")
                session.click("#rejection-decision-dialog [data-rejection-choice='Indeferida']")
                session.pump(1.0)
            posts = [parse_qs(b) for m, p, b in session.requests if m == "POST"]
            assert len(posts) == 1 and posts[0]["status"] == [status] and "horas_deferidas" not in posts[0], posts
            assert _sql("SELECT status FROM requisicoes WHERE id=?", (row["id"],))[0][0] == status
    finally:
        session.close()


def test_form_css_change_is_served_under_a_new_asset_version():
    versions = {re.search(r"static_asset_version = '([^']+)'", (ROOT / "templates" / page).read_text(encoding="utf-8")).group(1)
                for page in ("base.html", "base_aluno.html")}
    assert len(versions) == 1 and versions.isdisjoint({"20261016-ui-batch1-v1", "20261016-ui-batch2-v1"}), versions


def test_server_still_refuses_a_partial_decision_without_hours(env):
    _r, row = create_admin_request(env["client"], "Batch3 servidor")
    env["client"].post(f"/admin/processar_requisicao/{row['id']}",
                       data={"status": "Deferida Parcialmente", "observacao": "sem horas"})
    assert _sql("SELECT status FROM requisicoes WHERE id=?", (row["id"],))[0][0] == "Pendente"
