"""UI-B26 residuals: the Turma import trigger and the Banco de dados restore picker.

UI-B26 made the shared ``.field-card.file-card`` primitive keyboard reachable:
the real file input stays in the card, visually hidden but focusable, and is
the card's single keyboard target. Two recordings were left open:

* ``admin_turma_alunos.html`` kept the old ``<label class="btn">`` over a
  ``display:none`` input -- mouse-only -- and was deliberately deferred until
  the student-import candidate landed. It has; the live Turma import surfaces
  published with it use a real button trigger over the hidden input.
* the Banco de dados restore card disabled its own chooser once a file was
  chosen: the page script bailed out on ``.has-file`` and the chip was
  ``pointer-events:none``, so the mouse could not reopen or replace the
  selection even though the keyboard still could.

These guards pin the accepted behaviour: one real focusable trigger, mouse and
keyboard both open/reopen the picker, the chosen filename stays visible, and
choosing a file alone submits and mutates nothing.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tests.cdp_browser_support import find_chromium
from tests.root_admin_test_config import TEST_ROOT_ADMIN_EMAIL
from tests.test_file_upload_keyboard_ui_b26 import RecordingSession
from tests.versioned_test_support import isolated_versioned_app_env

ROOT = Path(__file__).resolve().parents[1]
TURMA_TEMPLATE = ROOT / "templates" / "admin_turma_alunos.html"
DB_TEMPLATE = ROOT / "templates" / "admin_banco_dados.html"

CHROMIUM = find_chromium()
browser = pytest.mark.skipif(CHROMIUM is None, reason="no headless Chromium available")


# ------------------------------------------------------------------ static


def test_turma_alunos_import_uses_a_real_focusable_trigger():
    text = TURMA_TEMPLATE.read_text(encoding="utf-8")

    assert '<label for="csv2"' not in text, (
        "the mouse-only label over a display:none input is back; the page must "
        "reuse the published Turma import trigger (real button + hidden input)"
    )

    input_tag = re.search(r'<input[^>]*id="csv2"[^>]*>', text)
    assert input_tag, "the Turma import file input is gone"
    assert "display:none" not in input_tag.group(0)
    assert re.search(r"\bhidden\b", input_tag.group(0)), "the input stays hidden behind a real trigger"

    trigger = re.search(r'<button[^>]*id="btn-importar-csv"[^>]*>', text)
    assert trigger, "the Turma import needs a real, focusable button trigger"
    assert 'type="button"' in trigger.group(0)
    assert ".click()" in text and 'id="csv2"' in text


def test_db_restore_card_does_not_lock_the_picker_after_a_file_is_chosen():
    text = DB_TEMPLATE.read_text(encoding="utf-8")

    assert "pointer-events:none" not in text, "the selected chip must stay clickable"
    assert 'card.classList.contains("has-file")' not in text
    assert 'chip.setAttribute("aria-disabled"' not in text


# ----------------------------------------------------------------- browser


@pytest.fixture
def admin_env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "ui-b26-residuals.db") as environment:
        response = environment["client"].post(
            "/login",
            data={"email": TEST_ROOT_ADMIN_EMAIL, "senha": "admin123"},
            follow_redirects=False,
        )
        assert response.status_code in (302, 303), response.status_code
        yield environment


@browser
def test_db_restore_picker_reopens_by_mouse_and_keyboard(admin_env, tmp_path):
    picked = tmp_path / "backup.zip"
    picked.write_bytes(b"UI-B26 residual probe; never submitted")

    session = RecordingSession(admin_env["client"], CHROMIUM)
    try:
        session.call("Page.setInterceptFileChooserDialog", {"enabled": True})
        session.goto("/admin/banco-dados")

        input_sel = json.dumps("[data-db-upload-card] input.file-input")
        node = session.call("Runtime.evaluate", {"expression": f"document.querySelector({input_sel})"})
        session.call(
            "DOM.setFileInputFiles",
            {"files": [str(picked)], "objectId": node["result"]["objectId"]},
        )
        session.pump(0.3)

        state = session.evaluate(
            "(() => { const c = document.querySelector('[data-db-upload-card]');"
            " const chip = c.querySelector('.chip-right');"
            " return { name: c.querySelector('[data-file-name]').textContent,"
            " hasFile: c.classList.contains('has-file'),"
            " chipAria: chip.getAttribute('aria-disabled'),"
            " tabbable: Array.from(c.querySelectorAll('*')).filter(e => e.tabIndex >= 0).length }; })()"
        )
        assert state["name"] == "backup.zip"
        assert state["hasFile"] is True
        assert state["chipAria"] is None
        assert state["tabbable"] == 1, "the card must keep exactly one keyboard target"

        # Mouse: the chip and the card reopen/replace the selection.
        session.evaluate("document.querySelector('[data-db-upload-card]').scrollIntoView({ block: 'center' }); true")
        session.pump(0.2)
        session.click("[data-db-upload-card] .chip-right")
        session.pump(0.3)
        assert len(session.choosers()) == 1, "mouse click must reopen the chosen file"
        session.click("[data-db-upload-card] [data-file-name]")
        session.pump(0.3)
        assert len(session.choosers()) == 2, "the card keeps opening the picker after a choice"

        # Keyboard: the real input is focusable and reopens natively.
        session.evaluate(f"document.querySelector({input_sel}).focus(); true")
        assert session.evaluate("document.activeElement.id") == "backup_file"
        session.key(" ", "Space", 32, " ")
        session.pump(0.3)
        assert len(session.choosers()) == 3, "Space must reopen the picker from the focused input"

        # Choosing a file never mutates anything: no POST happened at all.
        assert [request for request in session.requests if request[0] != "GET"] == []
        assert session.evaluate(
            "document.querySelector('[data-db-upload-card] [data-file-name]').textContent"
        ) == "backup.zip"
    finally:
        session.close()
