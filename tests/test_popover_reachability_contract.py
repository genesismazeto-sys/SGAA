"""Popover reachability and sort focus visibility (F-7).

Why this file exists
--------------------
The visual gate cannot pin either of these. Both are *behaviours*, not resting
appearances: one only manifests after the user scrolls ``.app-main`` and opens a
menu whose bottom edge would fall past the viewport, the other only exists while
a control holds keyboard focus. A screenshot catalogue rendered at load time
sees neither.

What F-7 fixes, and why the previous deferral no longer holds
-------------------------------------------------------------
The responsive milestone deferred vertical popover clamping on the stated
premise that "an overrun bottom edge still scrolls with ``.app-main``, so it
stays reachable". Measurement falsified that premise:

* ``.app-layout`` is ``height:100vh`` and ``.app-main`` owns the scroll, so
  ``window.scrollY`` is 0 and the document never scrolls. ``openPopover`` writes
  ``window.scrollY + rect.bottom + 6`` into a ``position:absolute`` element whose
  containing block is the initial containing block — which is viewport-anchored.
  ``openMenu`` writes viewport coordinates into a ``position:fixed`` element.
  Either way the popover is pinned to the SCREEN while its anchor scrolls away.
* Scrolling ``.app-main`` by 120px on /admin/acesso moved the button by -120px
  and the popover by 0px: the anchor gap grew from 6px to 126px and the bottom
  overflow was unchanged.
* In the only path that reaches the control at these widths — scroll the toolbar
  into view first — ``.app-main`` is already at its maximum scroll, so there is
  no remaining scroll to spend.

The controls left off screen were ``#filter-apply``, ``#filter-clear-all`` and
the destructive ``access-action-*`` items: applying a filter and deleting rows.

The sort control pair suppresses its own focus indicator (``outline:0`` plus
``box-shadow:none``) and sits inside an ``.input-group`` whose ``overflow:hidden``
leaves exactly 1px of slack, so nothing drawn outside the button can survive.
Measured focused presentation was byte-identical to resting on every one of the
four id families.

Opt-in for the same reasons as the other browser contracts: Playwright plus a
browser download, and keeping the canonical suite count stable.

    python -m pytest tests/test_popover_reachability_contract.py --visual
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# The margin the horizontal clamp has always used, and the one the vertical
# clamp adopts. Stated here so a change to either breaks the test rather than
# silently sliding the contract.
POPOVER_EDGE_MARGIN = 12
# The gap between a popover and its anchor when no clamp binds.
ANCHOR_GAP = 6
# Sub-pixel rounding slack. Both openers round to integers.
EPSILON = 1.0

# Every live sort-control family. The ids differ per page; the structure does
# not. A fix that only covers #sort-field is not a fix.
SORT_FAMILIES = [
    # name,              route,              role,    group,                            field,                      toggle
    ("canonical", "/admin/alunos", "admin", "#grp-ordenar", "#sort-field", "#sort-toggle"),
    ("acesso", "/admin/acesso", "admin", "#grp-ordenar-acesso", "#sort-acesso", "#sort-acesso-toggle"),
    ("admin-arquivos", "/admin/arquivos", "admin", "#grp-ordenar-admin-arquivos",
     "#sort-admin-arquivos", "#sort-admin-arquivos-toggle"),
    ("aluno-arquivos", "/aluno/arquivos", "aluno", "#grp-ordenar-aluno-arquivos",
     "#sort-aluno-arquivos", "#sort-aluno-arquivos-toggle"),
]

# The reachability cases. /admin/acesso is the only consumer that renders a long
# preamble above its toolbar (five profile cards plus the default-password
# panel), which is what pushes an opened popover past the bottom edge. 1440x900
# is the harness's own viewport and 1366x768 is the commonest laptop.
#
# Both scroll states are covered, because they are different defects and they
# peak on different popovers. Unscrolled, the toolbar is still on screen at these
# heights and a user can click it directly: that is where the FILTER popover
# overruns hardest (+105px at 1366x768, taking #filter-apply with it). Scrolled,
# the toolbar has moved up but .app-main is at its maximum, so there is no scroll
# left to spend: that is where SORT and ACTIONS overrun with nothing to recover
# them.
REACHABILITY_CASES = [
    # name, path, role, viewport, button, menu, scroll_toolbar_first
    ("acesso-sort-1440", "/admin/acesso", "admin", (1440, 900), "#sort-acesso", "#sort-menu", True),
    ("acesso-sort-1440-unscrolled", "/admin/acesso", "admin", (1440, 900),
     "#sort-acesso", "#sort-menu", False),
    ("acesso-sort-1366", "/admin/acesso", "admin", (1366, 768), "#sort-acesso", "#sort-menu", True),
    ("acesso-sort-1366-unscrolled", "/admin/acesso", "admin", (1366, 768),
     "#sort-acesso", "#sort-menu", False),
    ("acesso-filter-1366", "/admin/acesso", "admin", (1366, 768),
     "#filter-btn", "#filter-menu", True),
    ("acesso-filter-1366-unscrolled", "/admin/acesso", "admin", (1366, 768),
     "#filter-btn", "#filter-menu", False),
    ("acesso-filter-1280-unscrolled", "/admin/acesso", "admin", (1280, 800),
     "#filter-btn", "#filter-menu", False),
    ("acesso-actions-1440", "/admin/acesso", "admin", (1440, 900),
     "#btn-acesso-actions", "#access-actions-menu", True),
    ("acesso-actions-1440-unscrolled", "/admin/acesso", "admin", (1440, 900),
     "#btn-acesso-actions", "#access-actions-menu", False),
    ("acesso-actions-1366", "/admin/acesso", "admin", (1366, 768),
     "#btn-acesso-actions", "#access-actions-menu", True),
    ("acesso-actions-1366-unscrolled", "/admin/acesso", "admin", (1366, 768),
     "#btn-acesso-actions", "#access-actions-menu", False),
]

# Every actions-menu consumer in the application.
#
# Eight of them are driven by initToolbarSelectionActionsMenu. The other four
# predate it and each carried its own byte-identical copy of the clamp -- with a
# hidden-width fallback of 190 (acesso, matrizes) or 200 (reportes, requisicoes)
# that always won, because a display:none element measures 0. Those four are why
# this list exists: a fix applied only to the shared helper would have left the
# defect on /admin/acesso, which is the one page where it is user-visible.
ACTIONS_MENUS = [
    # name, route, role, button, menu, owner
    ("alunos", "/admin/alunos", "admin", "#btn-alunos-actions", "#alunos-actions-menu", "shared"),
    ("alertas", "/admin/alertas", "admin", "#btn-alertas-actions", "#alertas-actions-menu", "shared"),
    ("arquivos", "/admin/arquivos", "admin", "#btn-arquivos-actions", "#arquivos-actions-menu", "shared"),
    ("atividades", "/admin/atividades", "admin", "#btn-atividades-actions",
     "#atividades-actions-menu", "shared"),
    ("cursos", "/admin/cursos", "admin", "#btn-cursos-actions", "#cursos-actions-menu", "shared"),
    ("turmas", "/admin/turmas", "admin", "#btn-turmas-actions", "#turmas-actions-menu", "shared"),
    ("aluno-req", "/aluno/requisicoes", "aluno", "#btn-aluno-req-actions",
     "#aluno-req-actions-menu", "shared"),
    ("acesso", "/admin/acesso", "admin", "#btn-acesso-actions", "#access-actions-menu", "page-local"),
    ("matrizes", "/admin/matrizes", "admin", "#btn-matrizes-actions",
     "#matrizes-actions-menu", "page-local"),
    ("reportes", "/admin/reportes", "admin", "#btn-reportes-actions",
     "#reportes-actions-menu", "page-local"),
    ("requisicoes", "/admin/requisicoes", "admin", "#btn-req-actions",
     "#req-actions-menu", "page-local"),
]

# Consumers whose popovers must NOT move: nothing about them overruns, so the
# vertical clamp must be inert and the 6px anchor gap must survive untouched.
NON_BINDING_CASES = [
    ("alunos-sort", "/admin/alunos", "admin", "#sort-field", "#sort-menu"),
    ("alunos-filter", "/admin/alunos", "admin", "#filter-btn", "#filter-menu"),
    ("alunos-actions", "/admin/alunos", "admin", "#btn-alunos-actions", "#alunos-actions-menu"),
    ("requisicoes-sort", "/admin/requisicoes", "admin", "#sort-field", "#sort-menu"),
    ("requisicoes-filter", "/admin/requisicoes", "admin", "#filter-btn", "#filter-menu"),
    ("requisicoes-actions", "/admin/requisicoes", "admin", "#btn-req-actions", "#req-actions-menu"),
    ("matrizes-actions", "/admin/matrizes", "admin", "#btn-matrizes-actions",
     "#matrizes-actions-menu"),
    ("reportes-actions", "/admin/reportes", "admin", "#btn-reportes-actions",
     "#reportes-actions-menu"),
    ("arquivos-sort", "/admin/arquivos", "admin", "#sort-admin-arquivos", "#sort-menu"),
]

SCROLL_CASES = [
    ("acesso-sort", "/admin/acesso", "admin", "#sort-acesso", "#sort-menu"),
    ("acesso-filter", "/admin/acesso", "admin", "#filter-btn", "#filter-menu"),
    ("acesso-actions", "/admin/acesso", "admin", "#btn-acesso-actions", "#access-actions-menu"),
]


# --------------------------------------------------------------------- probes

SCROLL_TOOLBAR_INTO_VIEW = """
() => {
  const main = document.querySelector('.app-main');
  const toolbar = document.querySelector('.app-track .toolbar');
  if (!main || !toolbar) throw new Error('no .app-main/.toolbar');
  main.scrollTop += toolbar.getBoundingClientRect().top
                  - main.getBoundingClientRect().top - 24;
  return {scrollTop: main.scrollTop, maxScroll: main.scrollHeight - main.clientHeight};
}
"""

POPOVER_GEOMETRY = """
(sel) => {
  const btn = document.querySelector(sel.button);
  const menu = document.querySelector(sel.menu);
  const main = document.querySelector('.app-main');
  if (!btn || !menu) return {missing: true};
  if (menu.hidden) return {closed: true};
  const b = btn.getBoundingClientRect();
  const m = menu.getBoundingClientRect();
  const controls = [...menu.querySelectorAll('button, input, a[href], select, textarea')]
    .filter(el => {
      const cs = getComputedStyle(el);
      return cs.display !== 'none' && cs.visibility !== 'hidden';
    })
    .map(el => {
      const r = el.getBoundingClientRect();
      return {
        id: el.id || (el.className || '').toString().split(' ')[0],
        top: r.top, bottom: r.bottom, left: r.left, right: r.right,
        outsideViewport: r.bottom > window.innerHeight || r.top < 0
                      || r.right > window.innerWidth || r.left < 0,
      };
    });
  return {
    button: {top: b.top, bottom: b.bottom, left: b.left, right: b.right},
    menu: {top: m.top, bottom: m.bottom, left: m.left, right: m.right,
           width: m.width, height: m.height},
    anchorGap: m.top - b.bottom,
    overflowBottom: Math.max(0, m.bottom - window.innerHeight),
    overflowRight: Math.max(0, m.right - window.innerWidth),
    overflowTop: Math.max(0, -m.top),
    marginBottom: window.innerHeight - m.bottom,
    marginRight: window.innerWidth - m.right,
    viewport: {w: window.innerWidth, h: window.innerHeight},
    position: getComputedStyle(menu).position,
    mainScrollTop: main ? main.scrollTop : null,
    mainRoomBelow: main ? (main.scrollHeight - main.clientHeight - main.scrollTop) : null,
    controlsOutsideViewport: controls.filter(c => c.outsideViewport).map(c => c.id),
    controlCount: controls.length,
  };
}
"""

SCROLL_APP_MAIN = """
(px) => {
  const main = document.querySelector('.app-main');
  const before = main.scrollTop;
  main.scrollTop = before + px;
  return {before, after: main.scrollTop,
          moved: main.scrollTop - before,
          maxScroll: main.scrollHeight - main.clientHeight};
}
"""

AFTER_SCROLL = """
(sel) => {
  const btn = document.querySelector(sel.button);
  const menu = document.querySelector(sel.menu);
  const b = btn.getBoundingClientRect();
  const m = menu.getBoundingClientRect();
  return {
    open: !menu.hidden,
    ariaExpanded: btn.getAttribute('aria-expanded'),
    anchorGap: m.top - b.bottom,
    menuTop: m.top, buttonTop: b.top,
  };
}
"""

# Focus presentation of one element, plus whether whatever it draws survives the
# clipping ancestors between it and the viewport.
FOCUS_PRESENTATION = """
(selector) => {
  const el = document.querySelector(selector);
  if (!el) return {missing: true};
  const cs = getComputedStyle(el);
  const r = el.getBoundingClientRect();
  const outlineWidth = parseFloat(cs.outlineWidth) || 0;
  const outlineOffset = parseFloat(cs.outlineOffset) || 0;
  // The band the outline actually paints. A negative offset draws it INSIDE the
  // border box, which is the only place an overflow:hidden parent cannot reach.
  const outlineOuter = {
    top: r.top - outlineOffset - outlineWidth,
    bottom: r.bottom + outlineOffset + outlineWidth,
    left: r.left - outlineOffset - outlineWidth,
    right: r.right + outlineOffset + outlineWidth,
  };
  let clippedBy = null;
  let p = el.parentElement;
  while (p && !clippedBy) {
    const pcs = getComputedStyle(p);
    const clips = ['hidden', 'auto', 'scroll', 'clip'];
    if (clips.includes(pcs.overflowX) || clips.includes(pcs.overflowY)) {
      const pr = p.getBoundingClientRect();
      if (outlineOuter.top < pr.top - 0.5 || outlineOuter.bottom > pr.bottom + 0.5
          || outlineOuter.left < pr.left - 0.5 || outlineOuter.right > pr.right + 0.5) {
        clippedBy = (p.id ? '#' + p.id : p.tagName.toLowerCase())
                  + ' overflow:' + pcs.overflowX + '/' + pcs.overflowY;
      }
    }
    p = p.parentElement;
  }
  return {
    focused: document.activeElement === el,
    focusVisible: el.matches(':focus-visible'),
    outlineStyle: cs.outlineStyle,
    outlineWidth: cs.outlineWidth,
    outlineColor: cs.outlineColor,
    outlineOffset: cs.outlineOffset,
    boxShadow: cs.boxShadow,
    borderColor: cs.borderTopColor,
    background: cs.backgroundColor,
    paintsSomething: (outlineWidth > 0 && cs.outlineStyle !== 'none') || cs.boxShadow !== 'none',
    clippedBy,
  };
}
"""

TAB_TO = """
(args) => {
  const target = document.querySelector(args.selector);
  if (!target) return {missing: true};
  return {found: document.activeElement === target,
          active: document.activeElement ? (document.activeElement.id || document.activeElement.tagName) : null};
}
"""


def _tab_until(page, selector: str, limit: int = 60) -> bool:
    """Reach `selector` the way a keyboard user does, so :focus-visible applies.

    Calling .focus() would move focus without arming :focus-visible in Chromium,
    and the whole point of this test is the keyboard path.
    """
    page.evaluate("() => { if (document.activeElement && document.activeElement.blur) "
                  "document.activeElement.blur(); }")
    for _ in range(limit):
        page.keyboard.press("Tab")
        reached = page.evaluate(
            "(s) => { const t = document.querySelector(s); return !!t && document.activeElement === t; }",
            selector,
        )
        if reached:
            return True
    return False


# -------------------------------------------------------------------- fixture

@pytest.fixture(scope="module")
def browser_page(request):
    if not request.config.getoption("--visual"):
        pytest.skip("browser contract test is opt-in; pass --visual to run it")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("playwright is not installed (python -m pip install playwright)")

    from tools.visual.catalogue import login
    from tools.visual.harness import (
        ADMIN_EMAIL,
        ADMIN_PASSWORD,
        ALUNO_EMAIL,
        ALUNO_PASSWORD,
        AppServer,
        _install_determinism,
    )

    server = AppServer()
    server.start()
    playwright = sync_playwright().start()
    browser = playwright.chromium.launch()
    context = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
    _install_determinism(context)
    page = context.new_page()

    def finalise():
        context.close()
        browser.close()
        playwright.stop()
        server.stop()

    request.addfinalizer(finalise)

    def goto(path: str, role: str, viewport: tuple[int, int] = (1440, 900)):
        if getattr(goto, "role", None) != role:
            if role == "admin":
                login(page, server.base_url, ADMIN_EMAIL, ADMIN_PASSWORD)
            else:
                login(page, server.base_url, ALUNO_EMAIL, ALUNO_PASSWORD)
            goto.role = role
        page.set_viewport_size({"width": viewport[0], "height": viewport[1]})
        page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle")
        # No animation anywhere in this codebase, but pin it anyway so a future
        # transition cannot make these measurements timing-dependent.
        page.add_style_tag(content="*,*::before,*::after{transition:none !important;"
                                   "animation:none !important;}")
        page.wait_for_timeout(80)
        return page

    goto.page = page
    return goto


def _open(page, button: str, menu: str):
    page.evaluate("() => { document.querySelectorAll('.popover').forEach(p => { p.hidden = true; }); }")
    page.wait_for_timeout(40)
    page.click(button)
    page.wait_for_timeout(160)
    return page.evaluate(POPOVER_GEOMETRY, {"button": button, "menu": menu})


# Invoke the shared opener the page itself calls. Used where a page's own click
# handler is gated behind data the demo seed does not produce.
OPEN_VIA_OWNER = """
(sel) => {
  const helpers = window.createToolbarQueryHelpers && window.createToolbarQueryHelpers();
  if (!helpers || typeof helpers.openFixedMenu !== 'function') return {unavailable: true};
  const btn = document.querySelector(sel.button);
  const menu = document.querySelector(sel.menu);
  if (!btn || !menu) return {missing: true};
  helpers.openFixedMenu(btn, menu);
  return {opened: true};
}
"""


def _open_or_position(page, button: str, menu: str):
    """Open a menu, falling back to the shared opener when the page gates it.

    Five of the eleven actions menus sit behind ``initToolbarRowSelection``,
    which returns undefined when a list renders zero rows — and the demo seed
    produces no rows for those five. That gate predates F-7 (it is at
    HEAD:templates/admin_requisicoes.html:734) and is not something this phase
    changes, but skipping those consumers would leave five of eleven unverified.

    So where the page's own click cannot fire, the shared opener is invoked
    directly. That is not a stand-in: since F-7 every one of these menus — the
    eight driven by initToolbarSelectionActionsMenu and the four page-local ones
    — reaches the viewport through exactly this function. The geometry contract
    under test is therefore exercised on the page's real markup and viewport.
    """
    geom = _open(page, button, menu)
    if not geom.get("closed"):
        return geom, "click"
    result = page.evaluate(OPEN_VIA_OWNER, {"button": button, "menu": menu})
    if result.get("unavailable") or result.get("missing"):
        return geom, "unavailable"
    page.wait_for_timeout(120)
    return page.evaluate(POPOVER_GEOMETRY, {"button": button, "menu": menu}), "owner"


# ---------------------------------------------------------------------- tests

@pytest.mark.visual
@pytest.mark.parametrize("name,path,role,viewport,button,menu,scroll_first", REACHABILITY_CASES)
def test_opened_popover_stays_inside_the_viewport(browser_page, name, path, role, viewport,
                                                  button, menu, scroll_first):
    """Every actionable control in an opened popover must be on screen.

    This is the defect in its user-visible form: on /admin/acesso the toolbar
    sits below a long preamble. Opening a popover there used to push
    #filter-apply, #filter-clear-all and the destructive access-action-* items
    past the bottom edge, with no scroll left to spend and no coordinate
    coupling that would let one help.
    """
    page = browser_page(path, role, viewport)
    if scroll_first:
        scrolled = page.evaluate(SCROLL_TOOLBAR_INTO_VIEW)
    else:
        scrolled = page.evaluate(
            """() => { const m = document.querySelector('.app-main'); m.scrollTop = 0;
                       return {scrollTop: 0, maxScroll: m.scrollHeight - m.clientHeight}; }"""
        )
    page.wait_for_timeout(80)
    geom = _open(page, button, menu)

    assert not geom.get("missing"), f"{name}: {button}/{menu} not present on {path}"
    assert not geom.get("closed"), f"{name}: the popover did not open"
    assert geom["controlCount"] > 0, f"{name}: popover rendered no actionable controls"

    assert geom["overflowBottom"] == 0, (
        f"{name}: popover bottom is {geom['overflowBottom']:.0f}px past the viewport "
        f"({geom['menu']['bottom']:.0f} vs {geom['viewport']['h']}). .app-main has "
        f"{scrolled['maxScroll'] - scrolled['scrollTop']:.0f}px of scroll left, and the "
        "popover is pinned to the viewport anyway, so this is unreachable, not merely "
        "off screen."
    )
    assert geom["marginBottom"] >= POPOVER_EDGE_MARGIN - EPSILON, (
        f"{name}: popover sits {geom['marginBottom']:.1f}px from the bottom edge; the "
        f"contract is {POPOVER_EDGE_MARGIN}px."
    )
    assert geom["controlsOutsideViewport"] == [], (
        f"{name}: {len(geom['controlsOutsideViewport'])} popover controls are outside the "
        f"viewport: {geom['controlsOutsideViewport']}"
    )


@pytest.mark.visual
@pytest.mark.parametrize("name,path,role,button,menu", NON_BINDING_CASES)
def test_resting_geometry_is_untouched_where_no_clamp_binds(browser_page, name, path, role,
                                                            button, menu):
    """Where nothing overruns, F-7 must be invisible.

    The vertical clamp is only allowed to move a popover that would otherwise
    leave the viewport. Everywhere else the 6px anchor gap and the horizontal
    position established by F-6A2 must survive byte for byte.
    """
    page = browser_page(path, role, (1440, 900))
    geom, how = _open_or_position(page, button, menu)
    assert how != "unavailable", f"{name}: neither the page nor the shared opener could open it"
    assert not geom.get("missing") and not geom.get("closed"), f"{name}: popover did not open"

    assert abs(geom["anchorGap"] - ANCHOR_GAP) <= EPSILON, (
        f"{name}: anchor gap is {geom['anchorGap']:.1f}px, not {ANCHOR_GAP}px. The vertical "
        "clamp has moved a popover that had no reason to move."
    )
    assert geom["overflowBottom"] == 0 and geom["overflowRight"] == 0, (
        f"{name}: popover overruns the viewport (bottom +{geom['overflowBottom']:.0f}, "
        f"right +{geom['overflowRight']:.0f}) at 1440x900, where it always fitted."
    )
    assert geom["controlsOutsideViewport"] == [], (
        f"{name}: controls outside the viewport: {geom['controlsOutsideViewport']}"
    )


@pytest.mark.visual
@pytest.mark.parametrize("name,path,role,button,menu", SCROLL_CASES)
def test_popover_never_detaches_from_its_anchor_on_app_main_scroll(browser_page, name, path,
                                                                   role, button, menu):
    """A popover must never be left floating away from the button that owns it.

    Measured before F-7: scrolling .app-main by 120px moved the button -120px and
    the sort/actions popovers 0px, so the 6px gap became 126px and the popover
    hovered over unrelated content while still claiming aria-expanded="true".
    The filter popover already closed on captured scroll; the accepted contract
    is that all three behave the same way.
    """
    page = browser_page(path, role, (1366, 768))
    geom = _open(page, button, menu)
    assert not geom.get("missing") and not geom.get("closed"), f"{name}: popover did not open"

    room = geom["mainRoomBelow"] or 0
    if room < 20:
        # Make room: start from the top so there is something to scroll through.
        page.evaluate("() => { document.querySelector('.app-main').scrollTop = 0; }")
        page.wait_for_timeout(60)
        geom = _open(page, button, menu)
        room = geom["mainRoomBelow"] or 0
    if room < 20:
        pytest.skip(f"{name}: .app-main cannot scroll on this page/viewport")

    moved = page.evaluate(SCROLL_APP_MAIN, min(120, int(room)))
    page.wait_for_timeout(160)
    after = page.evaluate(AFTER_SCROLL, {"button": button, "menu": menu})

    assert moved["moved"] > 0, f"{name}: .app-main did not actually scroll; test is vacuous"
    if after["open"]:
        assert abs(after["anchorGap"] - ANCHOR_GAP) <= EPSILON, (
            f"{name}: popover stayed open after a {moved['moved']:.0f}px .app-main scroll but "
            f"its anchor gap is {after['anchorGap']:.1f}px instead of {ANCHOR_GAP}px — it has "
            "detached from its button and is floating over unrelated content."
        )
    else:
        assert after["ariaExpanded"] == "false", (
            f"{name}: popover closed on scroll but aria-expanded is "
            f"{after['ariaExpanded']!r}; assistive technology still believes it is open."
        )


@pytest.mark.visual
@pytest.mark.parametrize("name,path,role,group,field,toggle", SORT_FAMILIES)
def test_sort_controls_show_a_visible_keyboard_focus_indicator(browser_page, name, path, role,
                                                               group, field, toggle):
    """Both sort controls must present differently when focused from the keyboard.

    Measured before F-7 on all four id families: focused presentation was
    identical to resting — outline:none/0px, box-shadow:none, unchanged border
    and background — because each family sets `outline:0` and `box-shadow:none`
    unconditionally. The `.input-group:has(> input, > select):focus-within`
    rescue that saves the search box cannot match these groups: they contain only
    buttons.
    """
    page = browser_page(path, role, (1440, 900))

    for selector in (field, toggle):
        assert page.locator(selector).count(), f"{name}: {selector} missing on {path}"

        resting = page.evaluate(FOCUS_PRESENTATION, selector)
        assert not resting.get("missing")

        assert _tab_until(page, selector), (
            f"{name}: could not reach {selector} by keyboard within 60 tabs"
        )
        focused = page.evaluate(FOCUS_PRESENTATION, selector)

        assert focused["focused"], f"{name}: {selector} did not take focus"
        assert focused["focusVisible"], (
            f"{name}: {selector} is focused but does not match :focus-visible after a real "
            "Tab press; the test would prove nothing."
        )
        assert focused["paintsSomething"], (
            f"{name}: {selector} paints no focus indicator at all "
            f"(outline {focused['outlineStyle']}/{focused['outlineWidth']}, "
            f"box-shadow {focused['boxShadow']})."
        )
        changed = any(
            focused[k] != resting[k]
            for k in ("outlineStyle", "outlineWidth", "outlineColor", "boxShadow",
                      "borderColor", "background")
        )
        assert changed, (
            f"{name}: {selector} looks exactly the same focused as at rest — "
            f"outline {focused['outlineStyle']}/{focused['outlineWidth']}, "
            f"box-shadow {focused['boxShadow']}, border {focused['borderColor']}. "
            "A keyboard user cannot see where they are."
        )
        assert focused["clippedBy"] is None, (
            f"{name}: {selector}'s focus indicator is clipped away by {focused['clippedBy']}. "
            "The group reserves 1px of slack, so anything drawn outside the button is "
            "invisible; the indicator has to be drawn inside it."
        )
        # The resting state is not F-7's to change.
        assert resting["boxShadow"] == "none" and resting["outlineStyle"] in ("none", "auto"), (
            f"{name}: {selector} carries a resting indicator "
            f"(box-shadow {resting['boxShadow']}, outline {resting['outlineStyle']}); "
            "F-7 must not alter resting appearance."
        )


@pytest.mark.visual
@pytest.mark.parametrize("name,path,role,button,menu,owner", ACTIONS_MENUS)
def test_actions_menu_clamps_against_its_real_width(browser_page, name, path, role,
                                                    button, menu, owner):
    """Every actions menu must clamp against the width it actually renders at.

    Each opener read `offsetWidth` while the menu was still `display:none`, so it
    measured 0 and resolved to its hardcoded fallback — 190 in the shared helper,
    acesso and matrizes, 200 in reportes and requisicoes. Real rendered widths
    are 212-395px, which is why these menus came to rest flush against the
    viewport's right edge: 0px of margin where the clamp intends 12px.

    Parametrised over all eleven consumers because four of them are page-local
    copies. A fix that only reached the shared helper would still leave those
    four measuring a hidden element.
    """
    page = browser_page(path, role, (1440, 900))
    if not page.locator(button).count():
        pytest.skip(f"{name}: {button} not rendered on {path}")
    geom, how = _open_or_position(page, button, menu)
    assert how != "unavailable", (
        f"{name} ({owner}): the shared opener is not reachable on this page, so the "
        "menu has no owner at all"
    )
    assert not geom.get("closed"), f"{name} ({owner}): menu did not open via {how}"
    assert not geom.get("missing"), f"{name}: {button}/{menu} not present"

    assert geom["menu"]["width"] > 0, f"{name}: menu measured 0 wide"
    assert geom["overflowRight"] == 0, (
        f"{name} ({owner}): actions menu runs {geom['overflowRight']:.0f}px past the "
        "right edge"
    )
    assert geom["overflowBottom"] == 0, (
        f"{name} ({owner}): actions menu runs {geom['overflowBottom']:.0f}px past the "
        "bottom edge"
    )
    # The clamp only binds when the anchor is far enough right. Where it binds,
    # the margin is the contract; where it does not, the menu stays on its button
    # and the margin is whatever the layout gives.
    clamp_binds = geom["marginRight"] < geom["viewport"]["w"] * 0.5
    if clamp_binds:
        assert geom["marginRight"] >= POPOVER_EDGE_MARGIN - EPSILON, (
            f"{name} ({owner}): menu sits {geom['marginRight']:.1f}px from the right edge. "
            f"The clamp intends {POPOVER_EDGE_MARGIN}px; a smaller number means it was "
            "computed against the hidden-width fallback rather than the real width."
        )
