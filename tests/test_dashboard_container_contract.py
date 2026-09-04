"""Dashboard container-query contract (F-6B).

The visual gate cannot pin this on its own. It injects ``scrollbar-width:none``
for determinism, which removes the ``scrollbar-gutter:stable both-edges``
reservation on ``.app-main`` and makes the content track 30px wider than a
Windows or Linux user actually gets. So the harness renders one platform's
geometry, while the defect this phase fixed spans two: four KPI columns stop
fitting at a 1126px viewport with classic scrollbars and at 1096 with overlay
ones. A screenshot at a fixed viewport can only ever pin one of those.

These tests sidestep the question entirely by setting the QUERY CONTAINER's
inline size directly and asserting the column count that results. The viewport
stays at 1440 throughout — wide enough that the ``@supports not`` viewport
fallback is inactive — so a passing test proves the layout is driven by the
track and not by the window, which is the whole point of F-6B.

The boundary is arithmetic, not taste:

    4 columns x 180px minimum + 3 gaps x 24px = 792px

so 792 must still be four columns and 791 must already be two.

Opt-in, like the visual gate, for the same reasons: Playwright plus a browser
download, and keeping the canonical suite count stable.

    python -m pytest tests/test_dashboard_container_contract.py --visual
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 4 * 180 + 3 * 24. Stated here so a change to either number breaks the test
# rather than silently sliding the breakpoint.
KPI_COLUMN_MIN = 180
KPI_GAP = 24
KPI_COLUMNS = 4
FOUR_COLUMN_MIN_TRACK = KPI_COLUMNS * KPI_COLUMN_MIN + (KPI_COLUMNS - 1) * KPI_GAP  # 792
GLOBAL_CSS = PROJECT_ROOT / "static" / "css" / "modern-style.css"
ALUNO_DASHBOARD = PROJECT_ROOT / "templates" / "aluno_dashboard.html"

# Grids that must follow the track, and the page each is reachable on.
TRACK_DRIVEN_GRIDS = [
    ("kpi-grid-admin", "/admin/dashboard", ".kpi-grid", "admin"),
    ("kpi-grid-aluno", "/aluno/dashboard", ".kpi-grid", "aluno"),
    ("turma-row-kpis", "/admin/dashboard", ".dashboard-turma-row-kpis", "admin"),
]

# Pin the container's inline size directly so the assertions exercise the
# container-query contract independently of the shell's available width.
FORCE_TRACK_WIDTH = """
.app-track{{ width:{width}px !important; max-width:{width}px !important; }}
"""


def test_global_track_css_is_uncapped_named_container():
    """The global owner keeps the width and container-query contract."""
    css = GLOBAL_CSS.read_text(encoding="utf-8")
    match = re.search(r"(?m)^\.app-track\s*\{([^}]*)\}", css)
    assert match, "global .app-track rule is missing"
    declarations = dict(
        re.findall(r"(?m)^\s*([\w-]+)\s*:\s*([^;]+);", match.group(1))
    )
    assert declarations.get("width") == "100%"
    assert "max-width" not in declarations
    assert "margin" not in declarations
    assert declarations.get("min-width") == "0"
    assert declarations.get("container-type") == "inline-size"
    assert declarations.get("container-name") == "track"


def test_student_dashboard_progress_uses_the_shared_design_system_component():
    template = ALUNO_DASHBOARD.read_text(encoding="utf-8")
    css = GLOBAL_CSS.read_text(encoding="utf-8")

    assert 'class="dashboard-total-progress"' in template
    assert template.count('class="progress-meta-value') >= 5
    assert template.count('class="progress-bar"') >= 5
    assert "document.querySelectorAll('.progress[data-pct]')" in template

    for legacy_fragment in (
        "resume-total-bar",
        "limit-bar",
        'class="limit-pct"',
        "linear-gradient(90deg,#8359ff",
        "linear-gradient(90deg,#4da4ff",
    ):
        assert legacy_fragment not in template

    assert re.search(r"\.progress-bar\s*\{[^}]*background:var\(--brand\)", css)
    assert re.search(
        r"\.progress-meta-value\s*\{[^}]*font-size:var\(--font-size-small\)"
        r"[^}]*font-weight:600[^}]*font-variant-numeric:tabular-nums",
        css,
        re.DOTALL,
    )

COUNT_COLUMNS = """
(selector) => {
  const el = document.querySelector('.app-track ' + selector);
  if (!el) return {missing: true};
  const track = document.querySelector('.app-track');
  const cols = getComputedStyle(el).gridTemplateColumns;
  return {
    columns: cols === 'none' ? null : cols.trim().split(/\\s+/).length,
    trackWidth: Math.round(track.getBoundingClientRect().width),
    // A .kpi-card must never spill out of its own grid box again.
    selfOverflow: el.scrollWidth - el.clientWidth,
  };
}
"""


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
    # 1440 on purpose: the @supports-not viewport fallback only fires at or
    # below 1125, so anything these tests observe is the container's doing.
    context = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
    _install_determinism(context)
    page = context.new_page()

    def finalise():
        context.close()
        browser.close()
        playwright.stop()
        server.stop()

    request.addfinalizer(finalise)

    def goto(path: str, role: str, css: str | None = None):
        if getattr(goto, "role", None) != role:
            if role == "admin":
                login(page, server.base_url, ADMIN_EMAIL, ADMIN_PASSWORD)
            else:
                login(page, server.base_url, ALUNO_EMAIL, ALUNO_PASSWORD)
            goto.role = role
        page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle")
        if css:
            page.add_style_tag(content=css)
        page.wait_for_timeout(80)
        return page

    return goto


@pytest.mark.visual
@pytest.mark.parametrize("name,path,selector,role", TRACK_DRIVEN_GRIDS)
def test_four_columns_at_the_exact_minimum_track(browser_page, name, path, selector, role):
    """792px of track is the narrowest that still fits four columns."""
    page = browser_page(path, role, FORCE_TRACK_WIDTH.format(width=FOUR_COLUMN_MIN_TRACK))
    result = page.evaluate(COUNT_COLUMNS, selector)
    assert not result.get("missing"), f"{name}: {selector} did not render on {path}"
    assert result["trackWidth"] == FOUR_COLUMN_MIN_TRACK, (
        f"{name}: the query container is {result['trackWidth']}px, not "
        f"{FOUR_COLUMN_MIN_TRACK}px — the test is not measuring what it claims"
    )
    assert result["columns"] == 4, (
        f"{name}: {result['columns']} columns at a {FOUR_COLUMN_MIN_TRACK}px track. "
        "Four columns fit exactly here; dropping to two this early wastes width."
    )
    assert result["selfOverflow"] == 0, (
        f"{name}: grid overflows its own box by {result['selfOverflow']}px at the "
        "width where four columns are supposed to fit exactly."
    )


@pytest.mark.visual
@pytest.mark.parametrize("name,path,selector,role", TRACK_DRIVEN_GRIDS)
def test_two_columns_one_pixel_below_the_minimum_track(browser_page, name, path, selector, role):
    """791px is one pixel too narrow, and the grid must already have reflowed.

    This is the assertion that would have caught the original defect: the
    viewport is 1440, so any rule keyed to the window is inactive. Only a
    container-relative rule can pass.
    """
    width = FOUR_COLUMN_MIN_TRACK - 1
    page = browser_page(path, role, FORCE_TRACK_WIDTH.format(width=width))
    result = page.evaluate(COUNT_COLUMNS, selector)
    assert not result.get("missing"), f"{name}: {selector} did not render on {path}"
    assert result["trackWidth"] == width
    assert result["columns"] == 2, (
        f"{name}: {result['columns']} columns at a {width}px track. Four columns "
        f"need {FOUR_COLUMN_MIN_TRACK}px, so this is the band where they used to "
        "overflow silently."
    )
    assert result["selfOverflow"] == 0, (
        f"{name}: grid overflows its own box by {result['selfOverflow']}px at {width}px."
    )


@pytest.mark.visual
@pytest.mark.parametrize("viewport_width", [1920, 1440, 1366])
def test_global_track_uses_available_app_main_width(browser_page, viewport_width):
    """The global track must expand with .app-main instead of stopping at 1200px."""
    page = browser_page("/admin/atividades", "admin")
    page.set_viewport_size({"width": viewport_width, "height": 900})
    page.reload(wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(80)

    result = page.evaluate(
        """() => {
            const main = document.querySelector('.app-main');
            const track = document.querySelector('.app-track');
            if (!main || !track) return {missing: true};
            const mainStyle = getComputedStyle(main);
            const trackStyle = getComputedStyle(track);
            const available = main.clientWidth
                - parseFloat(mainStyle.paddingLeft)
                - parseFloat(mainStyle.paddingRight);
            return {
                viewportWidth: window.innerWidth,
                trackWidth: Math.round(track.getBoundingClientRect().width),
                availableWidth: Math.round(available),
                maxWidth: trackStyle.maxWidth,
                containerType: trackStyle.containerType,
                containerName: trackStyle.containerName,
            };
        }"""
    )
    assert not result.get("missing"), ".app-main/.app-track did not render"
    assert result["trackWidth"] == result["availableWidth"], (
        f"at {viewport_width}px, .app-track is {result['trackWidth']}px but the "
        f"available .app-main content width is {result['availableWidth']}px"
    )
    assert result["maxWidth"] == "none", (
        f"at {viewport_width}px, .app-track still has max-width={result['maxWidth']}"
    )
    assert result["containerType"] == "inline-size"
    assert result["containerName"] == "track"


@pytest.mark.visual
def test_container_does_not_capture_absolute_positioning(browser_page):
    """`container-type` must not turn .app-track into a containing block.

    Two shipped contracts depend on it not doing so: the F-5D reserved label
    gutter positions .row-label absolutely to the LEFT of the form, and the
    F-6A2 popover clamp writes viewport coordinates into an absolutely
    positioned menu. If .app-track ever became their containing block both
    would shift by the track's own offset, silently.
    """
    page = browser_page("/admin/dashboard", "admin")
    result = page.evaluate(
        """() => {
            const track = document.querySelector('.app-track');
            const probe = document.createElement('div');
            probe.style.cssText = 'position:absolute;left:0;top:0;width:10px;height:10px;';
            track.appendChild(probe);
            const probeLeft = probe.getBoundingClientRect().left;
            const trackLeft = track.getBoundingClientRect().left;
            probe.remove();
            return {probeLeft: Math.round(probeLeft), trackLeft: Math.round(trackLeft)};
        }"""
    )
    assert result["trackLeft"] > 0, "the track should be inset by the sidebar; test setup is wrong"
    assert result["probeLeft"] == 0, (
        "an absolutely positioned child of .app-track resolved against the track "
        f"(x={result['probeLeft']}) instead of the viewport. container-type has "
        "become a containing block and F-5D labels plus F-6A2 popovers have moved."
    )
