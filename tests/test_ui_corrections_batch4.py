"""UI corrections, batch 4: student Painel action and Progress subtitle.

1. Painel: a standard primary "Nova requisição" action (.btn.primary, Lucide
   plus) at the far right of the title row, centred on the "Painel" h1, linking
   to the existing new-request route. The h1 keeps its typography and block
   margins, so the alert banner / summary below it does not move; on a narrow
   track the action wraps below the title without clipping.
2. (Progress badge removal: tests/test_progress_event_date_note.py.)
3. (Shared select picker: tests/test_ds_select_picker.py.)
4. Progress subtitle: the 72ch cap is gone. The heading takes every pixel the
   two summary cards leave free, so the subtitle wraps only when the sentence
   genuinely does not fit; the cards keep their natural size and stay right
   aligned instead of being squeezed. No .main-title change, no nowrap.
"""
from __future__ import annotations

import json
import re

import pytest

import main
from tests.canonical_request_test_support import student_identity
from tests.cdp_browser_support import BrowserSession, find_chromium
from tests.session_support import stamp_auth_version
from tests.versioned_test_support import isolated_versioned_app_env

CHROMIUM = find_chromium()
browser = pytest.mark.skipif(CHROMIUM is None, reason="no headless Chromium available")
SUBTITLE = ("Acompanhe por atividade o catalogo disponivel, as horas validadas por semestre ate o periodo "
            "atual e o total acumulado.")


@pytest.fixture()
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "ui-batch4.db") as value:
        identity = student_identity()
        with value["client"].session_transaction() as session:
            session.clear()
            session.update(user_id=identity["usuario_id"], user_type="aluno", user_name="Aluno")
            stamp_auth_version(session)
        yield value


def _session(client, width):
    session = BrowserSession(client, CHROMIUM)
    session.call("Emulation.setDeviceMetricsOverride",
                 {"width": width, "height": 900, "deviceScaleFactor": 1, "mobile": False})
    return session


# ---------------------------------------------------------------- 1. Painel


def test_painel_title_row_carries_the_primary_new_request_action(env):
    html = env["client"].get("/aluno/dashboard").get_data(as_text=True)
    head = re.search(r'<div class="aluno-dashboard-head">(.*?)</div>', html, re.S)
    assert head, "title row missing"
    assert re.search(r'<h1 class="main-title">Painel</h1>', head.group(1))
    action = re.search(r'<a class="btn primary" href="([^"]+)">(.*?)</a>', head.group(1), re.S)
    assert action and action.group(1) == "/aluno/nova_requisicao"
    assert '<i class="lucide" data-lucide="plus" aria-hidden="true"></i>' in action.group(2)
    assert '<span class="btn-label">Nova requisição</span>' in action.group(2)
    assert html.count("<h1") == 1
    # The link reaches the existing new-request form.
    page = env["client"].get(action.group(1))
    assert page.status_code == 200 and "Nova Requisição" in page.get_data(as_text=True)


TITLE_ROW = """JSON.stringify((() => {
  const box = el => el.getBoundingClientRect();
  const row = document.querySelector('.aluno-dashboard-head'), h1 = row.querySelector('h1'), btn = row.querySelector('.btn.primary');
  const next = row.nextElementSibling, hs = getComputedStyle(h1);
  const center = el => box(el).top + box(el).height / 2;
  return {h1: [box(h1).left, box(h1).top, box(h1).height], font: [hs.fontSize, hs.fontWeight],
    rowMarginTop: parseFloat(getComputedStyle(row).marginTop), gapBelow: box(next).top - box(row).bottom,
    centred: center(btn) - center(h1), right: box(row).right - box(btn).right, rowWidth: box(row).width,
    trackRight: box(document.querySelector('.app-track')).right - parseFloat(getComputedStyle(document.querySelector('.app-track')).paddingRight),
    btnRight: box(btn).right, btnTop: box(btn).top, h1Bottom: box(h1).bottom, btnH: box(btn).height,
    clipped: btn.scrollWidth > btn.clientWidth + 1, docOverflow: document.documentElement.scrollWidth > innerWidth};
})())"""


@browser
@pytest.mark.parametrize("width", [1440, 1024, 768, 640])
def test_action_sits_at_the_far_right_centred_on_the_unmoved_title(env, width):
    session = _session(env["client"], width)
    try:
        session.goto("/aluno/dashboard")
        row = json.loads(session.evaluate(TITLE_ROW))
    finally:
        session.close()
    assert row["font"] == ["24px", "600"]
    assert abs(row["rowMarginTop"] - 24 * 0.67) < 0.01  # the h1's own UA top margin, carried by the row
    assert abs(row["gapBelow"] - 48) < 0.01  # .main-title's spacing before the alerts / summary
    assert abs(row["centred"]) <= 0.5 and abs(row["right"]) <= 0.5
    assert abs(row["btnRight"] - row["trackRight"]) <= 0.5
    assert not row["clipped"] and not row["docOverflow"]


@browser
def test_on_a_narrow_track_the_action_wraps_below_the_title(env):
    session = _session(env["client"], 1440)
    try:
        session.goto("/aluno/dashboard")
        session.evaluate("document.querySelector('.aluno-dashboard-head').style.width = '180px'; true")
        row = json.loads(session.evaluate(TITLE_ROW))
    finally:
        session.close()
    assert row["btnTop"] >= row["h1Bottom"] + 11.5  # next line, one 12px row gap
    assert row["btnRight"] <= row["trackRight"] and not row["clipped"]


# ------------------------------------------------------- 4. Progress subtitle

HEADER = """JSON.stringify((() => {
  const box = el => el.getBoundingClientRect();
  const lines = el => { const r = document.createRange(); r.selectNodeContents(el);
    return new Set(Array.from(r.getClientRects()).map(x => Math.round(x.top))).size; };
  const sub = document.querySelector('.progresso-subtitle'), title = document.querySelector('.progresso-title');
  const sum = document.querySelector('.progresso-summary'), head = document.querySelector('.progresso-header');
  const probe = sub.cloneNode(true); probe.style.cssText = 'position:absolute;visibility:hidden;white-space:nowrap;width:auto';
  document.body.appendChild(probe); const fullText = box(probe).width; probe.remove();
  const cards = Array.from(document.querySelectorAll('.progresso-summary-card')).map(c => box(c).width);
  const natural = (() => { const c = sum.cloneNode(true); c.style.cssText = 'position:absolute;visibility:hidden;width:max-content';
    document.body.appendChild(c); const w = Array.from(c.children).map(x => box(x).width); c.remove(); return w; })();
  const row = getComputedStyle(head).flexDirection === 'row';
  return {text: sub.textContent.trim(), lines: lines(sub), titleLines: lines(title), fullText,
    room: row ? box(sum).left - parseFloat(getComputedStyle(head).columnGap) - box(sub).left : box(head).width,
    subRight: box(sub).right, sumLeft: box(sum).left, sumRight: box(sum).right, headRight: box(head).right,
    cards, natural, row, maxWidth: getComputedStyle(sub).maxWidth, whiteSpace: getComputedStyle(sub).whiteSpace,
    docOverflow: document.documentElement.scrollWidth > innerWidth};
})())"""


@browser
@pytest.mark.parametrize("width", [1920, 1600, 1440, 1366, 1280, 1024, 768, 640])
def test_subtitle_uses_the_free_width_and_wraps_only_when_it_must(env, width):
    session = _session(env["client"], width)
    try:
        session.goto("/aluno/progresso")
        header = json.loads(session.evaluate(HEADER))
    finally:
        session.close()
    assert header["text"] == SUBTITLE
    assert header["maxWidth"] == "none" and header["whiteSpace"] == "normal"
    assert header["titleLines"] == 1 and not header["docOverflow"]
    fits = header["fullText"] <= header["room"] + 0.5
    assert (header["lines"] == 1) == fits, header
    if header["row"]:
        # The cards keep their natural width, stay right aligned, and nothing overlaps them.
        assert all(abs(a - b) <= 0.5 for a, b in zip(header["cards"], header["natural"])), header
        assert abs(header["sumRight"] - header["headRight"]) <= 0.5
        assert header["subRight"] <= header["sumLeft"] - 23.5
    if width >= 1440:
        assert header["lines"] == 1, header  # the whole sentence fits on desktop
