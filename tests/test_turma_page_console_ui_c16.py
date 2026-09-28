"""UI-C16: the Turma page must not throw ``sortFieldBtn is not defined``.

The page wires its sort menu through the shared ``initToolbarSortMenu()``
(``static/js/toolbar-filters.js``), whose ``sortFieldBtn``/``sortMenu`` are local
to that function and which already closes the menu on outside click and on
Escape. Two page-local document listeners, left over from an older page-local
sort implementation, still referenced those names, so every click and every
keypress on ``/admin/turma/<id>`` raised ``ReferenceError``. They are removed;
the shared owner keeps both behaviours.

The browser half records uncaught errors through a script installed before the
page's own scripts and skips where the Chromium harness is unavailable.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "admin_detalhes_turma.html"


def test_turma_script_declares_every_sort_menu_reference_it_uses():
    text = TEMPLATE.read_text(encoding="utf-8")
    script = "\n".join(re.findall(r"<script>(.*?)</script>", text, re.S))
    for name in ("sortFieldBtn", "sortMenu"):
        uses = re.findall(r"\b%s\b" % name, script)
        declared = re.findall(r"\b(?:const|let|var)\s+(?:\{[^}]*\b%s\b[^}]*\}|%s)\b" % (name, name), script)
        assert not uses or declared, f"{name} is used on the Turma page but never declared there"
    assert "initToolbarSortMenu" in script and "buttonSelector: '#sort-field'" in script


cdp = pytest.importorskip("tests.cdp_browser_support")
BINARY = cdp.find_chromium()


@pytest.mark.skipif(BINARY is None, reason="no Chromium binary for the browser harness")
def test_turma_page_runs_without_uncaught_errors_and_sort_menu_still_closes(tmp_path):
    import main
    from tests.test_aluno_turma_header_ui_c06 import _actor, _login, _seed
    from tests.versioned_test_support import isolated_versioned_app_env

    with isolated_versioned_app_env(tmp_path, "ui-c16.db") as env:
        ids = _seed()
        client = env["client"]
        _login(client, _actor("admin_total"))
        session = cdp.BrowserSession(client, BINARY)
        try:
            session.call("Page.enable")
            session.call(
                "Page.addScriptToEvaluateOnNewDocument",
                {"source": "window.__uncaught = []; window.addEventListener('error', (e) => window.__uncaught.push(String(e.message)));"},
            )
            session.goto(f"/admin/turma/{ids['turma']}?return_to=/admin/turmas")

            def errors():
                return json.loads(session.evaluate("JSON.stringify(window.__uncaught || [])"))

            def menu_hidden():
                return session.evaluate("document.getElementById('sort-menu').hidden")

            assert errors() == []

            # The shared owner still opens and closes the sort menu.
            session.evaluate("document.getElementById('sort-field').click(); true")
            session.pump(0.2)
            assert menu_hidden() is False
            session.evaluate("document.querySelector('.detail-header__title').click(); true")
            session.pump(0.2)
            assert menu_hidden() is True

            session.evaluate("document.getElementById('sort-field').click(); true")
            session.pump(0.2)
            session.evaluate("document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); true")
            session.pump(0.2)
            assert menu_hidden() is True

            # Arbitrary clicks and keypresses anywhere on the page stay clean.
            session.evaluate(
                "document.body.click(); document.dispatchEvent(new KeyboardEvent('keydown', { key: 'a', bubbles: true })); true"
            )
            session.pump(0.2)
            assert errors() == [], errors()

            # The rest of the page initialised: icons rendered, row actions bar wired.
            assert session.evaluate("document.querySelectorAll('svg.lucide').length") > 0
            session.evaluate(
                "document.querySelector('#turma-detalhes-list .impresso-card[role=listitem]')"
                ".dispatchEvent(new MouseEvent('mouseover', { bubbles: true })); true"
            )
            session.pump(0.2)
            assert session.evaluate("!!document.querySelector('#pedido-actions-float [data-action=\"view\"]')")
            assert errors() == [], errors()
        finally:
            session.close()
