"""The dashboards' KPI cards fit a phone, in a real Chromium (O3).

`.kpi-grid` drops from four columns to two at a 791px track (F-6B), but two
columns of at least 180px with a 24px gap need 384px and every phone track is
narrower (288px at 320, 358 at 390): the second column ran past the content
column on the student Painel and the administrator's dashboard, and the page
scrolled sideways. At a track of 383px or less the cards now stack in one
column; from 384 up nothing changed.

Served by a live local server on an isolated database with fictitious data
(the harness of tests/test_activity_documentation_admin_browser.py).
"""
from __future__ import annotations

from tests.canonical_matrix_test_support import login_admin
from tests.canonical_request_test_support import create_admin_request, login_student
from tests.test_activity_documentation_admin_browser import (
    BINARY,
    Session,
    browser_only,
    workspace,  # noqa: F401  (pytest fixture)
)

FIT_JS = r"""
(() => {
  const vw = document.documentElement.clientWidth;
  const main = document.querySelector('.app-main');
  const track = document.querySelector('.app-track').getBoundingClientRect();
  const grid = document.querySelector('.kpi-grid');
  const visible = el => { const s = getComputedStyle(el); return s.display !== 'none' && s.visibility !== 'hidden'; };
  const loose = [];
  for (const el of main.querySelectorAll('*')) {
    if (!visible(el)) continue;
    const b = el.getBoundingClientRect();
    if (!b.width || (b.right <= track.right + 0.5 && b.left >= track.left - 0.5)) continue;
    let p = el.parentElement, scrolled = false;
    for (; p && p !== main; p = p.parentElement) {
      if (['auto', 'scroll', 'hidden', 'clip'].includes(getComputedStyle(p).overflowX)) { scrolled = true; break; }
    }
    if (!scrolled) loose.push(el.className.toString().slice(0, 60));
  }
  const cards = Array.from(grid.children).filter(visible).map(c => c.getBoundingClientRect());
  return {
    track: track.width,
    columns: getComputedStyle(grid).gridTemplateColumns.split(' ').length,
    cards: cards.length,
    cardsInside: cards.filter(c => c.left >= track.left - 0.5 && c.right <= track.right + 0.5).length,
    loose,
    docOverflow: document.documentElement.scrollWidth - vw,
    mainOverflow: main.scrollWidth - main.clientWidth,
  };
})()
"""


def _viewport(session, width, height):
    phone = width < 768
    session.call("Emulation.setDeviceMetricsOverride",
                 {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": phone})
    session.call("Emulation.setTouchEmulationEnabled", {"enabled": phone, "maxTouchPoints": 5 if phone else 1})
    session.pump(0.3)


def _assert_dashboard_fits(session, path):
    expected = {320: 1, 360: 1, 390: 1, 430: 2, 768: 2, 1440: 4}
    for width, height in ((320, 640), (360, 740), (390, 844), (430, 932), (768, 1024), (1440, 900)):
        _viewport(session, width, height)
        session.goto(path)
        # Measure the settled page: fonts in, then a few frames for the
        # container query to follow the emulated width.
        session.wait_for("document.fonts ? document.fonts.status === 'loaded' : true")
        session.pump(0.5)
        fit = session.evaluate(FIT_JS)
        where = (path, width, fit)
        assert fit["columns"] == expected[width], where
        assert fit["cards"] >= 4 and fit["cardsInside"] == fit["cards"], where
        assert fit["loose"] == [], where
        assert fit["docOverflow"] <= 0 and fit["mainOverflow"] <= 0, where
    assert session.evaluate("window.__errors || []") == []


@browser_only
def test_the_student_painel_fits_a_phone(workspace):
    client = workspace["client"]
    login_admin(client)
    create_admin_request(client, name="O3 painel")
    login_student(client)
    session = Session(client, BINARY, workspace["downloads"], workspace["base_url"])
    try:
        _assert_dashboard_fits(session, "/aluno/dashboard")
    finally:
        session.close()


@browser_only
def test_the_administrator_dashboard_fits_a_phone(workspace):
    client = workspace["client"]
    login_admin(client)
    session = Session(client, BINARY, workspace["downloads"], workspace["base_url"])
    try:
        _assert_dashboard_fits(session, "/admin/dashboard")
    finally:
        session.close()
