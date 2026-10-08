"""UI-B26: every "Anexar" upload card is keyboard accessible.

Defect: the shared primitive hid the card's real ``<input type="file">`` with
``display:none`` (modern-style.css, plus copies in form.css and three page
<style> blocks). A display:none control is out of the tab order, and the
visible "Anexar" chip is a ``<div>``, so the picker opened only through each
page's mouse click handler. A ``required`` file input could not even show its
validation bubble.

Fix (native first, one owner): the input stays in the card, visually hidden
but focusable. It is the card's ONE keyboard target -- Tab reaches it, Enter
and Space open the browser picker natively, the card shows the standard
``.field-card:focus-within`` ring, and nothing else in the card is tabbable.
Mouse clicks still go through the page scripts, which ignore clicks whose
target is the input itself (so keyboard activation never opens it twice).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import main
from tests.canonical_request_documents_support import canonical_documents
from tests.canonical_request_test_support import login_student
from tests.cdp_browser_support import BrowserSession, find_chromium
from tests.test_comprovantes_google_drive import PDF, PNG, FakeStorage
from tests.versioned_test_support import isolated_versioned_app_env

ROOT = Path(__file__).resolve().parents[1]
PROTECTED = {
    "templates/admin_adicionar_turma.html",
    "templates/admin_editar_turma.html",
    "templates/admin_importar_turma.html",
    "templates/admin_turma_alunos.html",
    "templates/partials/admin_importar_turma_form.html",
}


# ------------------------------------------------------------------ static


def test_no_stylesheet_or_template_takes_the_card_input_out_of_the_tab_order():
    offenders = []
    sources = list((ROOT / "templates").rglob("*.html")) + list((ROOT / "static" / "css").rglob("*.css"))
    for path in sources:
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"([^{}]*\.file-input[^{}]*)\{([^}]*)\}", text):
            if re.search(r"display\s*:\s*none|visibility\s*:\s*hidden", match.group(2)):
                offenders.append(f"{path.relative_to(ROOT).as_posix()}: {match.group(1).strip()}")
    assert offenders == []


def test_the_shared_primitive_hides_visually_but_keeps_focus():
    css = (ROOT / "static/css/modern-style.css").read_text(encoding="utf-8")
    rule = re.search(r"\n\.field-card\.file-card \.file-input\{(.*?)\}", css, re.S)
    assert rule, "the shared file-card input primitive is gone"
    body = rule.group(1)
    assert "clip:rect(0, 0, 0, 0)" in body and "position:absolute" in body
    assert "display" not in body


def test_every_card_input_has_an_accessible_name():
    unnamed = []
    for path in (ROOT / "templates").rglob("*.html"):
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        for tag in re.findall(r'<input class="file-input"[^>]*>', text):
            if "aria-label=" in tag:
                continue
            ident = re.search(r'id="([^"]+)"', tag)
            if ident and f'for="{ident.group(1)}"' in text:
                continue
            unnamed.append(f"{rel}: {tag[:80]}")
    assert unnamed == []
    assert not any(p in PROTECTED for p in unnamed)


# ----------------------------------------------------------------- browser

CHROMIUM = find_chromium()
browser = pytest.mark.skipif(CHROMIUM is None, reason="no headless Chromium available")


class RecordingSession(BrowserSession):
    """BrowserSession that also keeps CDP events (file chooser openings)."""

    def __init__(self, client, binary):
        self.events: list[dict] = []
        super().__init__(client, binary)

    def _read_one(self, timeout):
        raw = self._ws.recv(timeout)
        if raw is None:
            return
        message = json.loads(raw)
        if "id" in message:
            self._responses[message["id"]] = message
        elif message.get("method") == "Fetch.requestPaused":
            self._serve(message["params"])
        else:
            self.events.append(message)

    def key(self, key, code, vk, text=None):
        down = {"type": "keyDown", "key": key, "code": code, "windowsVirtualKeyCode": vk}
        if text:
            down["text"] = text
        self.call("Input.dispatchKeyEvent", down)
        self.call("Input.dispatchKeyEvent", {"type": "keyUp", "key": key, "code": code, "windowsVirtualKeyCode": vk})
        self.pump(0.2)

    def tab(self):
        self.key("Tab", "Tab", 9)

    def choosers(self):
        return [e["params"] for e in self.events if e.get("method") == "Page.fileChooserOpened"]

    def active(self):
        return self.evaluate(
            "(() => { const a = document.activeElement; return a ? (a.id || a.getAttribute('aria-label') || a.tagName) : null; })()"
        )

    def ax(self, selector):
        node = self.call("Runtime.evaluate", {"expression": f"document.querySelector({json.dumps(selector)})"})
        tree = self.call("Accessibility.getPartialAXTree", {"objectId": node["result"]["objectId"], "fetchRelatives": False})
        top = tree["nodes"][0]
        return top["role"]["value"], top.get("name", {}).get("value")


@pytest.fixture
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "ui-b26.db") as environment:
        storage = FakeStorage()
        original = main.app.extensions.get("comprovante_storage")
        main.app.extensions["comprovante_storage"] = storage
        try:
            login_student(environment["client"])
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
    (folder / "a.pdf").write_bytes(PDF)
    (folder / "b.png").write_bytes(PNG)
    return folder


def _session(env):
    session = RecordingSession(env["client"], CHROMIUM)
    session.call("Page.setInterceptFileChooserDialog", {"enabled": True})
    return session


@browser
def test_keyboard_reaches_and_opens_anexar_on_nova_requisicao(env, picks):
    session = _session(env)
    try:
        session.goto("/aluno/nova-requisicao")
        session.evaluate("document.querySelector('[name=data_evento]').focus(); true")
        # Chromium tabs through the date input's day/month/year segments first.
        for _ in range(4):
            session.tab()
            if session.evaluate("document.activeElement.name") != "data_evento":
                break
        assert session.active() == "comprovantes_files", "the next stop after the date must be the upload control"

        role, name = session.ax("#comprovantes_files")
        assert role == "button" and name == "Comprovantes"
        ring = session.evaluate(
            "(() => { const c = document.querySelector('[data-upload-card]');"
            " const s = getComputedStyle(c); return {within: c.matches(':focus-within'), shadow: s.boxShadow}; })()"
        )
        assert ring["within"] is True and ring["shadow"] not in ("", "none"), ring

        session.key(" ", "Space", 32, " ")
        session.key("Enter", "Enter", 13, "\r")
        modes = [chooser["mode"] for chooser in session.choosers()]
        assert modes == ["selectMultiple", "selectMultiple"], modes

        # One focus stop: the next Tab leaves the card for the observação field.
        session.tab()
        assert session.evaluate("document.activeElement.name") == "observacao"

        # After picking, Tab walks the remove buttons; Enter removes one file.
        # (STORAGE S3-A: picked files are listed by direct-upload.js, one
        # stable row per file whose remove button is named for its file.)
        node = session.call("Runtime.evaluate", {"expression": "document.getElementById('comprovantes_files')"})
        session.call("DOM.setFileInputFiles", {"files": [str(picks / "a.pdf"), str(picks / "b.png")], "objectId": node["result"]["objectId"]})
        session.pump(0.3)
        session.evaluate("document.getElementById('comprovantes_files').focus(); true")
        session.tab()
        assert session.active() == "Remover comprovante a.pdf"
        session.tab()
        assert session.active() == "Remover comprovante b.png"
        session.key("Enter", "Enter", 13, "\r")
        names = session.evaluate(
            "JSON.stringify(Array.from(document.querySelectorAll('[data-direct-upload-list] li > span'))"
            ".map(s => s.textContent.split(' \u2014 ')[0]))"
        )
        assert json.loads(names) == ["a.pdf"]
    finally:
        session.close()


@browser
def test_mouse_flow_on_the_card_still_opens_the_picker_once(env):
    session = _session(env)
    try:
        session.goto("/aluno/nova-requisicao")
        session.click("[data-upload-card] .chip-right")
        session.pump(0.3)
        session.click("[data-upload-card] [data-file-name]")
        session.pump(0.3)
        assert len(session.choosers()) == 2
    finally:
        session.close()


@browser
def test_reportar_screenshot_card_is_reachable_too(env):
    session = _session(env)
    try:
        session.goto("/aluno/reportar")
        session.evaluate("document.querySelector('[name=titulo]').focus(); true")
        session.tab()
        assert session.active() == "captura_tela"
        assert session.ax("#captura_tela") == ("button", "Captura de tela")
        session.key(" ", "Space", 32, " ")
        assert [chooser["mode"] for chooser in session.choosers()] == ["selectSingle"]
        tabbable = session.evaluate(
            "Array.from(document.querySelectorAll('[data-upload-card] *')).filter(e => e.tabIndex >= 0 && e.id !== 'captura_tela').length"
        )
        assert tabbable == 0, "the card must expose exactly one keyboard target"
    finally:
        session.close()
