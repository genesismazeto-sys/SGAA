"""The Status column of the request lists stays in view, in a real Chromium (O2).

A list keeps its minimum width and scrolls sideways inside its own box
(Design System §2.7). The administrator's Requisições list is 1267px wide, so
from 1440px down its last column -- Status -- sat past the box's right edge
until the user scrolled; the student's list likewise. The shared status-column
contract now pins the status cell to that edge (and, on the administrator's
list, the e-mail flag beside it): every pill is in view at every width and
scroll position, nothing else runs past the viewport, and where the list fits
the cell is where it always was.

Served by a live local server on an isolated database with fictitious data
(the harness of tests/test_activity_documentation_admin_browser.py).
"""
from __future__ import annotations

import main
from tests.canonical_matrix_test_support import login_admin
from tests.canonical_request_test_support import create_admin_request, login_student
from tests.test_activity_documentation_admin_browser import (
    BINARY,
    Session,
    browser_only,
    workspace,  # noqa: F401  (pytest fixture)
)

ADMIN_LIST = "#requisicoes-scroll-container"
STUDENT_LIST = ".impressoes-cards-scroll.imp-areq"

GEOMETRY_JS = r"""
((sel, frac) => {
  const s = document.querySelector(sel);
  s.scrollLeft = Math.floor((s.scrollWidth - s.clientWidth) * frac);
  const sr = s.getBoundingClientRect();
  const left = sr.left + s.clientLeft, right = left + s.clientWidth;
  const inside = el => { const b = el.getBoundingClientRect(); return b.left >= left - 0.5 && b.right <= right + 0.5; };
  const rows = Array.from(s.querySelectorAll('.impresso-card'));
  const app = document.querySelector('.app-main');
  const pairs = rows.map(row => {
    const st = row.querySelector('.status-col'), em = row.querySelector('.req-email-cell');
    const sb = st.getBoundingClientRect(), eb = em ? em.getBoundingClientRect() : null;
    return {status: [sb.left, sb.right], email: eb && [eb.left, eb.right]};
  });
  const cell = s.querySelector('.impresso-card:not(.header) .status-col');
  const flag = s.querySelector('.impresso-card:not(.header) .req-email-cell');
  // The pinned group's leading cell carries the fade: the flag on the
  // administrator's list, the status cell elsewhere.
  const lead = flag || cell;
  return {
    box: s.clientWidth, list: s.scrollWidth, right,
    rows: rows.length,
    labels: rows.map(r => r.querySelector('.status-col').textContent.trim()),
    labelsInside: rows.filter(r => inside(r.querySelector('.status-col > *') || r.querySelector('.status-col'))).length,
    icons: s.querySelectorAll('.req-email-pending').length,
    iconsInside: Array.from(s.querySelectorAll('.req-email-pending')).filter(inside).length,
    iconLefts: Array.from(s.querySelectorAll('.req-email-pending')).map(i => i.getBoundingClientRect().left),
    pairs,
    cellMasks: [cell, flag].filter(Boolean).map(c => getComputedStyle(c).maskImage),
    fadeMask: getComputedStyle(lead, '::after').maskImage,
    pageOverflow: Math.max(document.documentElement.scrollWidth - document.documentElement.clientWidth,
                           app.scrollWidth - app.clientWidth),
  };
})(%s, %s)
"""


def _viewport(session, width, height):
    phone = width < 768
    session.call("Emulation.setDeviceMetricsOverride",
                 {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": phone})
    session.call("Emulation.setTouchEmulationEnabled", {"enabled": phone, "maxTouchPoints": 5 if phone else 1})
    session.pump(0.3)


def _geometry(session, selector, frac):
    return session.evaluate(GEOMETRY_JS % (repr(selector), frac))


def _seed_requests(client):
    """Three requests: the longest label (Deferida Parcialmente), a decision that
    still awaits its e-mail, and a pending one."""
    ids = [create_admin_request(client, name=f"O2 lista {n}")[1]["id"] for n in range(3)]
    for req_id, fields in zip(ids, ({"status": "Deferida Parcialmente", "horas_deferidas": "1", "observacao": "Parcial."},
                                    {"status": "Deferida"})):
        assert client.post(f"/admin/processar_requisicao/{req_id}", data=fields).status_code == 302
    return ids


def _assert_in_view(geo, *, width, frac):
    where = (width, frac)
    assert geo["labelsInside"] == geo["rows"], (where, geo)
    assert geo["iconsInside"] == geo["icons"], (where, geo)
    assert geo["pageOverflow"] <= 0, (where, geo)
    # A pinned cell's own content is never masked (a masked cell loses its
    # subpixel antialiasing); only the fade pseudo-element is.
    assert set(geo["cellMasks"]) == {"none"} and geo["fadeMask"] != "none", (where, geo)


@browser_only
def test_the_administrator_sees_every_status_at_every_width(workspace):
    client = workspace["client"]
    login_admin(client)
    _seed_requests(client)
    session = Session(client, BINARY, workspace["downloads"], workspace["base_url"])
    try:
        for width, height in ((1920, 1080), (1440, 900), (1024, 768), (768, 1024), (390, 844), (320, 640)):
            _viewport(session, width, height)
            session.goto("/admin/requisicoes")
            session.pump(0.3)
            for frac in (0, 0.5, 1):
                geo = _geometry(session, ADMIN_LIST, frac)
                assert "Deferida Parcialmente" in geo["labels"] and geo["icons"] == 2, geo
                _assert_in_view(geo, width=width, frac=frac)
                if width == 1920:
                    # The list fits: nothing is pinned, the cells are where they were.
                    assert geo["list"] == geo["box"], geo
                    continue
                assert geo["list"] > geo["box"], (width, geo)
                for pair in geo["pairs"]:
                    status_left, status_right = pair["status"]
                    email_left, email_right = pair["email"]
                    assert abs(status_right - geo["right"]) < 0.5 or frac == 1, (width, frac, pair)
                    # Flag and status are adjacent: the status cell's 13px reach
                    # over the 12px gap meets the flag, no sliver between them.
                    assert status_left - 13 <= email_right <= status_left - 11.5, (width, frac, pair)
                # The flag sits on whole pixels while pinned (its strokes stay sharp).
                if frac < 1:
                    assert all(abs(x - round(x)) < 0.01 for x in geo["iconLefts"]), (width, geo["iconLefts"])
        assert session.evaluate("window.__errors || []") == []
    finally:
        session.close()


@browser_only
def test_the_student_sees_every_status_at_every_width(workspace):
    client = workspace["client"]
    login_admin(client)
    _seed_requests(client)
    login_student(client)
    session = Session(client, BINARY, workspace["downloads"], workspace["base_url"])
    try:
        for width, height in ((1920, 1080), (1440, 900), (768, 1024), (390, 844), (320, 640)):
            _viewport(session, width, height)
            session.goto("/aluno/requisicoes")
            session.pump(0.3)
            for frac in (0, 0.5, 1):
                geo = _geometry(session, STUDENT_LIST, frac)
                assert "Deferida Parcialmente" in geo["labels"], geo
                _assert_in_view(geo, width=width, frac=frac)
            if width < 1920:
                assert geo["list"] > geo["box"], (width, geo)
        # The student list now uses the shared track: the same width as the
        # administrator's, which reserves "Deferida Parcialmente".
        widths = session.evaluate(
            "Array.from(document.querySelectorAll('.imp-areq .status-col')).map(c => c.getBoundingClientRect().width)")
        assert len(set(round(w, 1) for w in widths)) == 1, widths
    finally:
        session.close()
