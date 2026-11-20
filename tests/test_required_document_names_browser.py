"""A required proof's name is readable while it is edited, in a real Chromium (O4).

A proof name may take 60 characters (REQUIRED_DOCUMENT_MAX_LENGTH), about 420px
on one line. The field of the version form is 144px wide at 768 and 230px at
390, so most of a long name was hidden inside it. At rest, and in a frozen
version, the field keeps the approved one line; while it is being edited it
opens to the whole name, justified with its last line start-aligned, and it
closes again when the focus leaves it. The value is still one line of data
(Enter adds no break, a pasted break becomes a space, the limit holds), the
row label stays on one line and nothing runs past the viewport.

Served by a live local server on an isolated database with fictitious data
(the harness of tests/test_activity_documentation_admin_browser.py).
"""
from __future__ import annotations

from app.activity_documentation import REQUIRED_DOCUMENT_MAX_LENGTH
from tests.canonical_matrix_test_support import login_admin
from tests.test_activity_documentation_admin_browser import (
    BINARY,
    Session,
    _draft_version,
    _open,
    _stored,
    _submit_and_wait,
    browser_only,
    workspace,  # noqa: F401  (pytest fixture)
)

#: 60 characters each, written as a coordinator would.
LONG = (
    "Certificado de participação, com carga horária e assinaturas",
    "Declaração da instituição promotora, com carga horária total",
)
SHORT = "Cópia do ingresso"
FIELD = "#documentos-exigidos-list [name=documentos_exigidos]"

STATE_JS = r"""
(() => {
  const fields = Array.from(document.querySelectorAll('#documentos-exigidos-list [name=documentos_exigidos]'));
  const label = document.getElementById('documentos-exigidos-label');
  const range = document.createRange(); range.selectNodeContents(label);
  const main = document.querySelector('.app-main');
  return {
    fields: fields.map(f => {
      const s = getComputedStyle(f);
      return {value: f.value, height: f.clientHeight, hiddenY: f.scrollHeight - f.clientHeight,
              hiddenX: f.scrollWidth - f.clientWidth, wrap: s.whiteSpace, align: s.textAlign,
              last: s.textAlignLast, focused: f === document.activeElement};
    }),
    labelLines: new Set(Array.from(range.getClientRects()).filter(r => r.width > 0.5).map(r => Math.round(r.top))).size,
    pageOverflow: Math.max(document.documentElement.scrollWidth - document.documentElement.clientWidth,
                           main.scrollWidth - main.clientWidth),
  };
})()
"""


def _viewport(session, width, height):
    phone = width < 768
    session.call("Emulation.setDeviceMetricsOverride",
                 {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": phone})
    session.pump(0.4)


def _add(session, text):
    session.click_in_view("[data-doc-add]")
    session.evaluate(
        "(() => { const f = document.querySelector('#documentos-exigidos-list li:last-child [name=documentos_exigidos]');"
        " f.focus(); document.execCommand('insertText', false, %r); return true; })()" % text
    )


def _press(session, selector, hold=0.0):
    """Press and release where ``selector`` is now, without scrolling first; ``hold`` seconds between."""
    box = session.evaluate(
        "(() => { const r = document.querySelector(%r).getBoundingClientRect();"
        " return {x: r.left + r.width / 2, y: r.top + r.height / 2}; })()" % selector
    )
    for kind, buttons in (("mousePressed", 1), ("mouseReleased", 0)):
        session.call("Input.dispatchMouseEvent", {"type": kind, "x": box["x"], "y": box["y"],
                                                  "button": "left", "buttons": buttons, "clickCount": 1})
        if kind == "mousePressed" and hold:
            session.pump(hold)
    session.pump(0.3)


def _leave(session):
    session.evaluate("document.activeElement && document.activeElement.blur(); true")
    session.pump(0.2)


@browser_only
def test_a_long_name_stays_one_line_at_rest_and_opens_whole_while_edited(workspace):
    assert all(len(name) == REQUIRED_DOCUMENT_MAX_LENGTH for name in LONG)
    base_id, version_id = _draft_version()
    login_admin(workspace["client"])
    session = Session(workspace["client"], BINARY, workspace["downloads"], workspace["base_url"])
    try:
        _open(session, f"/admin/catalogo-versoes/{base_id}/versoes/{version_id}/editar")
        for name in (*LONG, SHORT):
            _add(session, name)
        # One line of data: a typed break and a pasted one never reach the value,
        # and the limit still holds.
        _add(session, "Lista de\npresença")
        _add(session, "X" * (REQUIRED_DOCUMENT_MAX_LENGTH + 5))
        values = session.evaluate(f"Array.from(document.querySelectorAll({FIELD!r})).map(f => f.value)")
        assert values[:4] == [*LONG, SHORT, "Lista de presença"]
        assert len(values[4]) == REQUIRED_DOCUMENT_MAX_LENGTH
        session.evaluate(f"document.querySelectorAll({FIELD!r})[4].closest('li').querySelector('[data-doc-remove]').click(); true")

        for width, height in ((1440, 900), (768, 1024), (390, 844)):
            _viewport(session, width, height)
            _leave(session)
            rest = session.evaluate(STATE_JS)
            assert rest["labelLines"] == 1 and rest["pageOverflow"] <= 0, (width, rest)
            one_line = {f["height"] for f in rest["fields"]}
            # At rest every field is the approved single line, long name or short.
            assert len(one_line) == 1 and all(f["wrap"] == "nowrap" for f in rest["fields"]), (width, rest)

            session.evaluate(f"document.querySelectorAll({FIELD!r})[1].focus(); true")
            session.pump(0.2)
            edit = session.evaluate(STATE_JS)
            opened = edit["fields"][1]
            assert opened["focused"] and opened["hiddenY"] <= 0 and opened["hiddenX"] <= 0, (width, edit)
            assert (opened["wrap"], opened["align"], opened["last"]) == ("pre-wrap", "justify", "start"), (width, edit)
            if width < 1440:
                assert opened["height"] > one_line.pop(), (width, edit)
            # Only the field being edited opens.
            assert all(f["wrap"] == "nowrap" for i, f in enumerate(edit["fields"]) if i != 1), (width, edit)
            assert edit["pageOverflow"] <= 0, (width, edit)

        _leave(session)
        _submit_and_wait(session, "#btn-salvar-versao")
        assert _stored(version_id)[0] == [*LONG, SHORT, "Lista de presença"]
        assert session.evaluate("window.__errors") == []
    finally:
        session.close()


@browser_only
def test_a_press_that_closes_an_open_name_still_clicks(workspace):
    """Leaving an open field shrinks its row; a button pressed below it must
    still receive its click (the field closes only after the press ends)."""
    base_id, version_id = _draft_version()
    login_admin(workspace["client"])
    session = Session(workspace["client"], BINARY, workspace["downloads"], workspace["base_url"])
    try:
        _open(session, f"/admin/catalogo-versoes/{base_id}/versoes/{version_id}/editar")
        _viewport(session, 768, 1024)
        _add(session, LONG[0])
        # A quick click, and a button held down longer than the 1 s fallback.
        for count, hold in ((2, 0.0), (3, 0.0), (4, 1.4)):
            # The section at the top of the viewport, as a user reaches it; the
            # press lands where the button is while the name above is open.
            session.evaluate("document.getElementById('documentacao-exigida').scrollIntoView({block: 'start'}); true")
            session.evaluate(f"document.querySelector({FIELD!r}).focus(); true")
            session.pump(0.3)
            assert session.evaluate(f"document.querySelector({FIELD!r}).clientHeight") > 40
            _press(session, "[data-doc-add]", hold)
            assert session.evaluate(f"document.querySelectorAll({FIELD!r}).length") == count, hold
        assert session.evaluate("window.__errors") == []
    finally:
        session.close()


def _tap(session, selector):
    """A finger tap where ``selector`` is now. On touch Chromium sends pointerup
    before the mousedown that moves the focus -- the order that lost the click."""
    box = session.evaluate(
        "(() => { const r = document.querySelector(%r).getBoundingClientRect();"
        " return {x: r.left + r.width / 2, y: r.top + r.height / 2}; })()" % selector
    )
    session.call("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": box["x"], "y": box["y"]}]})
    session.pump(0.05)
    session.call("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
    session.pump(0.6)


@browser_only
def test_a_tap_that_closes_an_open_name_still_clicks(workspace):
    base_id, version_id = _draft_version()
    login_admin(workspace["client"])
    session = Session(workspace["client"], BINARY, workspace["downloads"], workspace["base_url"])
    try:
        _open(session, f"/admin/catalogo-versoes/{base_id}/versoes/{version_id}/editar")
        for width, height in ((390, 844), (768, 1024)):
            session.call("Emulation.setDeviceMetricsOverride",
                         {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": width < 768})
            session.call("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 5})
            session.pump(0.4)
            if not session.evaluate(f"document.querySelectorAll({FIELD!r}).length"):
                _add(session, LONG[0])
            for _ in range(2):
                before = session.evaluate(f"document.querySelectorAll({FIELD!r}).length")
                session.evaluate("document.getElementById('documentacao-exigida').scrollIntoView({block: 'start'}); true")
                session.evaluate(f"document.querySelector({FIELD!r}).focus(); true")
                session.pump(0.3)
                assert session.evaluate(f"document.querySelector({FIELD!r}).clientHeight") > 40, width
                _tap(session, "[data-doc-add]")
                assert session.evaluate(f"document.querySelectorAll({FIELD!r}).length") == before + 1, width
        assert session.evaluate("window.__errors") == []
    finally:
        session.close()


def _enter(session):
    for kind in ("keyDown", "keyUp"):
        session.call("Input.dispatchKeyEvent", {"type": kind, "key": "Enter", "code": "Enter",
                                                "windowsVirtualKeyCode": 13, "text": "\r" if kind == "keyDown" else ""})
    session.pump(0.4)


@browser_only
def test_enter_in_a_name_adds_no_break_and_saves_as_the_input_did(workspace):
    base_id, version_id = _draft_version()
    edit_url = f"/admin/catalogo-versoes/{base_id}/versoes/{version_id}/editar"
    login_admin(workspace["client"])
    session = Session(workspace["client"], BINARY, workspace["downloads"], workspace["base_url"])
    try:
        _open(session, edit_url)
        _add(session, SHORT)
        _submit_and_wait(session, "#btn-salvar-versao")
        _open(session, edit_url)
        # Nothing changed: the save button is disabled, so Enter does nothing at
        # all -- no line break and no submission.
        session.evaluate(
            "window.__submits = 0; window.__count = e => { window.__submits++; e.preventDefault(); };"
            " document.getElementById('btn-salvar-versao').form.addEventListener('submit', window.__count); true")
        session.evaluate(f"document.querySelector({FIELD!r}).focus(); true")
        _enter(session)
        assert session.evaluate("window.__submits") == 0
        session.evaluate("document.getElementById('btn-salvar-versao').form.removeEventListener('submit', window.__count); true")
        assert session.evaluate(f"document.querySelector({FIELD!r}).value") == SHORT
        assert session.evaluate("location.pathname") == edit_url
        # A change enables it: Enter saves the form, as the single-line input did.
        session.evaluate("window.__leaving = true; true")
        session.evaluate(
            f"(() => {{ const f = document.querySelector({FIELD!r}); f.focus();"
            f" f.setSelectionRange(f.value.length, f.value.length);"
            f" document.execCommand('insertText', false, ' (cópia)'); return true; }})()")
        _enter(session)
        session.wait_for("!window.__leaving && document.readyState === 'complete'", timeout=20)
        assert _stored(version_id)[0] == [SHORT + " (cópia)"]
    finally:
        session.close()
