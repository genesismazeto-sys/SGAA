"""UI-B48 — the floating row bar is chrome: it paints below menus and dialogs.

RED on the pre-correction tree: the bar carried `z-index: 1200`, above every
`.popover` (1000) and `.modal-overlay` (40), so an open menu's lower items and a
dialog's scrim had the bar on top. GREEN after `components/actions-float.css`
puts it at 20, below the shared overlay owners and above the sticky header.

The static guards always run. The browser lanes need a Chromium binary and
reuse the UI-B47/B49 live-server harness with an isolated SQLite database;
screenshots are opt-in through `SGAA_EVIDENCE_DIR` and stay outside the
repository.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FLOAT_CSS = ROOT / "static" / "css" / "components" / "actions-float.css"
MODAL_CSS = ROOT / "static" / "css" / "components" / "modal.css"
LIST_CSS = ROOT / "static" / "css" / "components" / "list-cards.css"

BAR_PAGES = {
    "admin_acesso", "admin_alertas", "admin_alunos", "admin_arquivos",
    "admin_atividades", "admin_catalogo_versao_detalhe", "admin_cursos",
    "admin_detalhes_turma", "admin_matrizes", "admin_reportes",
    "admin_requisicoes", "admin_turmas", "aluno_arquivos",
    "aluno_minhas_requisicoes",
}


def _z_index(path: Path, selector: str) -> int:
    text = path.read_text(encoding="utf-8")
    start = text.index(selector)
    block = text[start:text.index("}", start)]
    match = re.search(r"z-index\s*:\s*(\d+)", block)
    assert match, (path.name, selector, block)
    return int(match.group(1))


def test_the_bar_paints_below_the_shared_overlay_owners():
    bar = _z_index(FLOAT_CSS, "#pedido-actions-float.pedido-actions-float{")
    modal = _z_index(MODAL_CSS, ".modal-overlay{")
    popover = _z_index(LIST_CSS, ".popover{")
    # Above the sticky table header (5), below the navigation (29/30), the modal
    # (40) and every popover (1000). The exact value is the component's contract.
    assert 5 < bar < modal < popover, (bar, modal, popover)
    assert "Stacking contract" in FLOAT_CSS.read_text(encoding="utf-8")


def test_every_floating_bar_page_links_the_shared_owner():
    found = set()
    for path in sorted((ROOT / "templates").glob("*.html")):
        text = path.read_text(encoding="utf-8")
        if not re.search(r"bar\.id\s*=\s*['\"]pedido-actions-float['\"]", text):
            continue
        found.add(path.stem)
        assert "css/components/actions-float.css" in text, path.name
        # No page may own the bar's layer again (UI-B48).
        assert not re.search(r"#pedido-actions-float[^{]*\{[^}]*z-index", text), path.name
    assert found == BAR_PAGES


try:  # the static guards above must not be skipped when Chromium is absent
    from tests import cdp_browser_support as cdp

    BINARY = cdp.find_chromium()
except Exception:  # pragma: no cover - environment without the harness
    BINARY = None

browser_only = pytest.mark.skipif(BINARY is None, reason="no Chromium binary for the browser harness")

if BINARY:
    from tests.canonical_matrix_test_support import login_admin
    from tests.test_activity_documentation_admin_browser import (
        EVIDENCE,
        Session,
        workspace,  # noqa: F401  (pytest fixture)
    )
else:  # pragma: no cover - the browser tests are skipped
    EVIDENCE = None
    Session = None

MEASURE = r"""
(() => {
  const bar = document.querySelector('#pedido-actions-float');
  const overlay = document.querySelector(%s);
  if (!bar || !overlay) return {error: 'missing bar or overlay'};
  const bs = getComputedStyle(bar), os = getComputedStyle(overlay);
  const br = bar.getBoundingClientRect(), or = overlay.getBoundingClientRect();
  const x = Math.max(0, Math.min(innerWidth - 1, br.left + br.width / 2));
  const y = Math.max(0, Math.min(innerHeight - 1, br.top + br.height / 2));
  const hit = document.elementFromPoint(x, y);
  const overlap = !(br.right <= or.left || or.right <= br.left || br.bottom <= or.top || or.bottom <= br.top);
  return {
    barZ: parseInt(bs.zIndex, 10) || 0, overlayZ: parseInt(os.zIndex, 10) || 0, overlayHidden: overlay.hidden,
    barVisible: bar.classList.contains('is-visible'),
    bar: {x: Math.round(br.x), y: Math.round(br.y), w: Math.round(br.width), h: Math.round(br.height)},
    overlay: {x: Math.round(or.x), y: Math.round(or.y), w: Math.round(or.width), h: Math.round(or.height)},
    overlap,
    point: {x: Math.round(x), y: Math.round(y)},
    hit: hit ? (hit.id || (typeof hit.className === 'string' ? hit.className : hit.tagName)) : null,
    hitIsBar: !!(hit && hit.closest('#pedido-actions-float')),
    hitIsOverlay: !!(hit && hit.closest(%s)),
  };
})()
"""

BAR_HIT = r"""
(() => {
  const bar = document.querySelector('#pedido-actions-float');
  const r = bar.getBoundingClientRect();
  const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
  return {visible: bar.classList.contains('is-visible'),
          hitIsBar: !!(hit && hit.closest('#pedido-actions-float')),
          hit: hit ? (hit.id || (typeof hit.className === 'string' ? hit.className : hit.tagName)) : null};
})()
"""


def _open(session, path, width, height):
    session.call(
        "Emulation.setDeviceMetricsOverride",
        {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": width < 720},
    )
    session.goto(path)
    session.evaluate(
        "window.__errors = []; window.addEventListener('error', e => window.__errors.push(String(e.message)));"
        " window.confirm = () => true; true"
    )
    if EVIDENCE:
        session.wait_for("document.fonts ? document.fonts.status === 'loaded' : true")


def _show_bar(session, card_selector):
    visible = session.evaluate(
        "(() => { const c = document.querySelector(%s);"
        " if (!c) return false; c.dispatchEvent(new MouseEvent('mouseover', {bubbles:true}));"
        " return document.querySelector('#pedido-actions-float')?.classList.contains('is-visible'); })()"
        % json.dumps(card_selector)
    )
    session.pump(0.2)
    assert visible, card_selector


def _capture(session, name):
    if EVIDENCE:
        session.capture_viewport(name)


def _no_js_errors(session):
    assert session.evaluate("window.__errors") == []


@browser_only
@pytest.mark.parametrize("width,height", [(1440, 900), (390, 844)])
def test_a_modal_backdrop_and_dialog_cover_the_bar(workspace, width, height):
    login_admin(workspace["client"])
    session = Session(workspace["client"], BINARY, workspace["downloads"], workspace["base_url"])
    try:
        _open(session, "/admin/acesso", width, height)
        session.wait_for(
            "document.querySelector('#pedido-actions-float') &&"
            " document.querySelectorAll('#acesso-scroll-container .impresso-card:not(.header)').length"
        )
        session.evaluate(
            "(() => { const c = document.querySelector('#acesso-scroll-container .impresso-card:not(.header)');"
            " c.scrollIntoView({block:'center'}); return true; })()"
        )
        session.pump(0.2)
        _show_bar(session, "#acesso-scroll-container .impresso-card:not(.header)")
        # The bar's own edit action opens the shared dialog while the pointer is
        # still on the bar: the real trigger of the defect.
        session.evaluate("document.querySelector('#pedido-actions-float [data-action=\"edit\"]').click(); true")
        session.wait_for("!document.querySelector('#access-modal').hidden")
        result = session.evaluate(MEASURE % (json.dumps("#access-modal"), json.dumps("#access-modal")))
        assert result["barZ"] < result["overlayZ"], result
        assert result["hitIsBar"] is False, result
        assert result["hitIsOverlay"] is True, result
        _capture(session, f"ui-b48-modal-{width}")

        # Closing restores the page: the bar can be shown and is the hit target.
        session.click_in_view("#access-modal-cancel")
        session.wait_for("document.querySelector('#access-modal').hidden")
        session.evaluate(
            "(() => { const c = document.querySelector('#acesso-scroll-container .impresso-card:not(.header)');"
            " c.scrollIntoView({block:'center'}); return true; })()"
        )
        session.pump(0.2)
        _show_bar(session, "#acesso-scroll-container .impresso-card:not(.header)")
        restored = session.evaluate(BAR_HIT)
        assert restored["visible"] is True, restored
        assert restored["hitIsBar"] is True, restored
        _no_js_errors(session)
    finally:
        session.close()


@browser_only
@pytest.mark.parametrize("width,height", [(1440, 900), (390, 844)])
def test_an_open_menu_paints_above_the_floating_bar(workspace, width, height):
    login_admin(workspace["client"])
    session = Session(workspace["client"], BINARY, workspace["downloads"], workspace["base_url"])
    try:
        _open(session, "/admin/alunos", width, height)
        session.wait_for("document.querySelectorAll('#alunos-list .impresso-card:not(.header)').length")
        session.evaluate(
            "(() => { const c = document.querySelector('#alunos-list .impresso-card:not(.header)');"
            " c.scrollIntoView({block:'start'}); return true; })()"
        )
        session.pump(0.2)
        _show_bar(session, "#alunos-list .impresso-card:not(.header)")
        session.evaluate("document.querySelector('#btn-alunos-actions').click(); true")
        session.wait_for("!document.querySelector('#alunos-actions-menu').hidden")
        session.evaluate("document.querySelector('#pedido-actions-float').classList.add('is-visible'); true")
        result = session.evaluate(MEASURE % (json.dumps("#alunos-actions-menu"), json.dumps("#alunos-actions-menu")))
        assert result["overlap"] is True, result
        assert result["overlayZ"] > result["barZ"], result
        assert result["hitIsBar"] is False, result
        assert result["hitIsOverlay"] is True, result
        _capture(session, f"ui-b48-menu-{width}")

        # Closing the menu leaves the bar usable.
        session.evaluate("document.querySelector('#btn-alunos-actions').click(); true")
        session.wait_for("document.querySelector('#alunos-actions-menu').hidden")
        _show_bar(session, "#alunos-list .impresso-card:not(.header)")
        restored = session.evaluate(BAR_HIT)
        assert restored["visible"] is True, restored
        assert restored["hitIsBar"] is True, restored
        _no_js_errors(session)
    finally:
        session.close()
