"""Requisições floating action bar: the bar must be correct on FIRST paint.

Reported defect: on /admin/requisicoes the floating bar sometimes appeared too
far to the right, with Excluir hanging outside the row's right border, and then
"snapped back" on its own without the user fixing anything.

Proven cause (ordering, not timing): the hover handler measured the bar with
`positionFor()` while "Enviar e-mail" was still hidden -- `applyBatchMode()` had
just hidden it, because with nothing selected `allSelectedPending([])` is false
-- and only AFTERWARDS did `updatePrimaryActionFor()` un-hide it for a pending
row.  `positionFor` pins `left = rowRight - width`, so the extra button (26px
button + 4px flex gap) extended the bar 30px past the row's right border.  Any
later `positionFor` -- the selection sync on click, scroll, resize, or hovering
another row -- re-measured at the real width and the bar "self-corrected".

These tests therefore assert the FIRST visible state, and separately that a
second, independent sync changes nothing.  A steady-state-only assertion would
have passed against the defect.

Two layers:

* Static  -- the authoritative sequence (content -> measure/position -> reveal)
  is expressed in the template, so the ordering cannot silently regress.
* Geometry -- `tests/js/requisicoes_floating_bar_harness.js` executes the real
  extracted script under node and reports measured rectangles.  Skipped when
  node is unavailable; the static layer still runs.

Limitation: the repo has no browser automation and no node_modules (and jsdom
performs no layout, so it would report offsetWidth 0 regardless).  The harness
models bar width from the contract in static/css/components/actions-float.css,
which it parses rather than hardcodes; `test_width_contract_matches_css` pins
the same constants here so a CSS change invalidating the model is caught.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = PROJECT_ROOT / "templates" / "admin_requisicoes.html"
HARNESS = PROJECT_ROOT / "tests" / "js" / "requisicoes_floating_bar_harness.js"
TEMPLATE = TEMPLATE_PATH.read_text(encoding="utf-8")
CSS = (PROJECT_ROOT / "static" / "css" / "components" / "actions-float.css").read_text(
    encoding="utf-8"
)


# ===================== 1. authoritative sequence (static) =====================


def _strip_comments(block: str) -> str:
    return "\n".join(re.sub(r"//.*$", "", line) for line in block.splitlines())


def _show_body() -> str:
    return _strip_comments(TEMPLATE.split("function show(){")[1].split("}")[0])


def _hover_handler() -> str:
    block = TEMPLATE.split("scrollWrap?.addEventListener('mouseover'")[1]
    return _strip_comments(block.split("});")[0])


def test_show_is_the_authoritative_positioning_step():
    """Measurement/positioning happens inside show(), after all content changes.

    This is what makes the defect structurally impossible rather than merely
    absent: no caller can reveal the bar without it being positioned at its
    final width first.
    """
    body = _show_body()
    assert "positionFor(currentCard)" in body
    order = body.index("positionFor(currentCard)"), body.index("classList.add('is-visible')")
    assert order[0] < order[1], "the bar must be positioned BEFORE it is revealed"


def test_hover_does_not_position_before_the_content_is_final():
    """The regression itself: positionFor() ran before updatePrimaryActionFor().

    `updatePrimaryActionFor` is the last thing that can change the bar's width
    (it toggles Editar and Enviar e-mail), so no measurement may precede it.
    """
    handler = _hover_handler()
    assert "updatePrimaryActionFor(currentCard);" in handler
    assert "show();" in handler
    idx_update = handler.index("updatePrimaryActionFor(currentCard);")
    idx_show = handler.index("show();")
    assert idx_update < idx_show

    stale = [
        m.start()
        for m in re.finditer(r"positionFor\(", handler)
        if m.start() < idx_update
    ]
    assert not stale, (
        "positionFor() must not run before updatePrimaryActionFor(): that is the "
        "stale measurement that let the bar overflow the row on first paint"
    )


def test_no_arbitrary_delay_papers_over_the_ordering():
    """The fix is ordering, not a timer racing the layout."""
    handler = _hover_handler()
    assert "setTimeout" not in handler
    assert "requestAnimationFrame" not in _show_body()
    assert "setTimeout" not in _show_body()


def test_no_invented_inset_or_magic_viewport_values():
    block = _strip_comments(
        TEMPLATE.split("function positionFor(card)")[1].split("\n    }")[0]
    )
    assert "INSET" not in block
    assert "margin" not in block
    # No hardcoded viewport widths.
    assert not re.search(r"\b(?:19|14|13|12|10)\d\d\b", block)


def test_width_contract_matches_css():
    """Pins the constants the geometry harness models.

    The harness parses these from actions-float.css; asserting them here means a
    CSS change that invalidates the model fails loudly instead of silently
    making the geometry tests meaningless.
    """
    assert "--pedido-float-btn: 26px" in CSS
    assert "display: flex; gap: 4px" in CSS
    assert "padding: 4px 6px; border: 1px solid var(--border-strong)" in CSS
    # The bar is never display:none, so it is measurable while hidden -- the
    # measurement itself was never the problem, its ORDERING was.
    assert "opacity: 0; pointer-events: none" in CSS
    assert "display:none" not in CSS.split(".is-visible")[0].split("#pedido-actions-float.pedido-actions-float{")[1]
    # Icon swap cannot change width: <i> and <svg> are sized identically.
    assert "#pedido-actions-float .act-btn i," in CSS
    assert "width:16px; height:16px; flex:0 0 16px;" in CSS


# ========================= 2. measured geometry (node) ========================


@pytest.fixture(scope="module")
def harness() -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is unavailable; the static ordering contract still runs")
    proc = subprocess.run(
        [node, str(HARNESS), str(PROJECT_ROOT)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, f"harness failed:\n{proc.stderr}"
    return json.loads(proc.stdout)["scenarios"]


def _assert_contained(geometry: dict, label: str) -> None:
    assert geometry["visible"], f"{label}: bar must be visible"
    assert geometry["left"] >= geometry["rowLeft"], (
        f"{label}: bar crosses the row's LEFT border "
        f"(bar.left={geometry['left']} < row.left={geometry['rowLeft']})"
    )
    assert geometry["right"] <= geometry["rowRight"], (
        f"{label}: bar crosses the row's RIGHT border "
        f"(bar.right={geometry['right']} > row.right={geometry['rowRight']}, "
        f"overflow={geometry['rightOverflow']}px, buttons={geometry['buttons']})"
    )


def test_hover_first_paint_is_contained_without_a_second_sync(harness):
    """THE regression. Pre-fix: first=1330 vs row right=1300 (30px overflow)."""
    s = harness["hover_pending_first_paint"]
    _assert_contained(s["first"], "first paint on hover")
    assert "delete" in s["first"]["buttons"]
    assert "email" in s["first"]["buttons"], "pending row must offer Enviar e-mail"


def test_hover_first_paint_needs_no_self_correction(harness):
    """Nothing may move when a later, independent sync runs.

    Pre-fix this pair was 30px -> 0px: exactly the "first wrong, second right"
    signature the user observed.  A steady-state-only test saw only the 0px.
    """
    s = harness["hover_pending_first_paint"]
    assert s["first"]["left"] == s["afterSecondSync"]["left"], (
        "the bar moved on a second sync: it was positioned at a stale width "
        f"({s['first']['left']} -> {s['afterSecondSync']['left']})"
    )
    assert s["first"]["right"] == s["afterSecondSync"]["right"]


def test_bar_is_measured_at_its_final_width(harness):
    """Every positioning must use the width the bar actually ends up with."""
    s = harness["hover_pending_first_paint"]
    assert s["positions"], "the bar was never positioned"
    for entry in s["positions"]:
        assert entry["measuredWidth"] == s["finalWidth"], (
            "positionFor() measured a width that later changed: "
            f"{entry['measuredWidth']} != {s['finalWidth']} (buttons at measure "
            f"time: {entry['buttons']})"
        )


def test_hover_first_paint_is_flush_for_a_non_pending_row(harness):
    """Same ordering defect, opposite sign: the bar used to be measured 30px too
    wide and left a gap instead of overflowing."""
    s = harness["hover_non_pending_first_paint"]
    _assert_contained(s["first"], "first paint on a processed row")
    assert s["first"]["right"] == s["first"]["rowRight"], "must be flush, zero gap"
    assert "email" not in s["first"]["buttons"]


def test_selection_first_paint_is_contained_and_stable(harness):
    s = harness["select_first_paint"]
    _assert_contained(s["first"], "first paint on select")
    assert s["first"]["left"] == s["afterResize"]["left"], "resize must not correct it"


def test_switching_selection_is_correct_on_the_first_state(harness):
    s = harness["switch_selection_first_paint"]
    _assert_contained(s["onRow2"], "selected processed row")
    _assert_contained(s["onRow1"], "switched to pending row")
    assert s["onRow1"]["left"] == s["afterScroll"]["left"], "scroll must not correct it"


def test_clear_then_hover_then_select_is_correct_throughout(harness):
    s = harness["clear_then_hover_then_select"]
    assert not s["cleared"]["visible"], "clearing the selection must hide the bar"
    _assert_contained(s["hovered"], "re-hover after clearing")
    _assert_contained(s["selected"], "re-select after clearing")
    assert s["hovered"]["left"] == s["selected"]["left"]


# ================= 3. subpixel containment (fractional geometry) =============
#
# `barRect.right <= rowRect.right` has no tolerance exemption, so it must hold
# for FRACTIONAL boundaries too -- a CSS grid row almost never ends on a whole
# pixel.  Two independent quantization hazards were present:
#
#   1. `Math.round(boundRight - barW)` rounded UP whenever frac(boundRight) >=
#      0.5, putting the bar up to 0.5px past the row's right border.  (Note it
#      rounds DOWN below 0.5, so e.g. 1300.4 alone does not expose it; the sweep
#      below covers the whole band.)
#   2. `bar.offsetWidth` is rounded to an integer, so a bar whose real width is
#      160.4 was positioned as if it were 160 wide and overflowed by 0.4px --
#      independently of the row edge.
#
# Both are fixed by exact subpixel arithmetic: getBoundingClientRect().width and
# no rounding.  No inset, no padding, no extra leftward shift.


def test_positioning_uses_exact_subpixel_arithmetic():
    """Static guard: neither quantization step may come back."""
    code = _strip_comments(
        TEMPLATE.split("function positionFor(card)")[1].split("\n    }")[0]
    )
    assert "bar.style.left = (boundRight - barW) + 'px';" in code
    assert "Math.round(boundRight" not in code, (
        "rounding the horizontal position can place the bar past the row's edge"
    )
    assert "const barW = bar.getBoundingClientRect().width" in code, (
        "offsetWidth is integer-rounded and cannot express the exact bar width"
    )
    # Still zero inset: the formula is a bare subtraction.
    assert not re.search(r"boundRight\s*-\s*barW\s*[-+]\s*\d", code)


def test_fractional_row_boundary_is_never_crossed(harness):
    """Swept across the whole fractional band, on the FIRST visible state.

    Pre-fix, every frac >= 0.5 overflowed (max 0.5px at frac == 0.5).
    """
    entries = harness["fractional_row_boundary"]
    assert entries, "fractional sweep produced no data"
    violations = [
        e for e in entries if e["right"] > e["rowRight"] or e["left"] < e["rowLeft"]
    ]
    assert not violations, "bar crossed a fractional row border:\n" + "\n".join(
        f"  frac={e['frac']} {e['mode']}: bar.right={e['right']} > "
        f"row.right={e['rowRight']} (overflow={e['rightOverflow']}px)"
        for e in violations
    )
    # Covers the band on both sides of the old rounding threshold.
    assert {e["frac"] for e in entries} >= {0.25, 0.4, 0.5, 0.6, 0.75}
    assert {e["mode"] for e in entries} == {"hover", "select"}


def test_fractional_row_boundary_is_exactly_flush(harness):
    """Containment must not be bought with a leftward nudge.

    The brief forbids moving the bar farther left than required, so the right
    edges must COINCIDE, not merely be ordered.
    """
    for e in harness["fractional_row_boundary"]:
        assert e["right"] == pytest.approx(e["rowRight"], abs=1e-9), (
            f"frac={e['frac']} {e['mode']}: bar.right={e['right']} is not flush "
            f"with row.right={e['rowRight']}"
        )


def test_fractional_bar_width_is_not_quantized_by_offsetwidth(harness):
    """A fractional bar width must not be read through integer offsetWidth."""
    entries = harness["fractional_bar_width"]
    assert entries
    fractional = [e for e in entries if e["width"] != e["offsetWidth"]]
    assert fractional, "sweep never produced a bar whose exact width is fractional"
    violations = [e for e in entries if e["right"] > e["rowRight"]]
    assert not violations, "integer-rounded width pushed the bar past the row:\n" + "\n".join(
        f"  exactWidth={e['width']} offsetWidth={e['offsetWidth']} "
        f"bar.right={e['right']} > row.right={e['rowRight']}"
        for e in violations
    )
    for e in entries:
        assert e["right"] == pytest.approx(e["rowRight"], abs=1e-9)


def test_horizontal_scroll_clamp_also_respects_a_fractional_bound(harness):
    """The wrap's right edge is the bound for a horizontally scrolled row."""
    entries = harness["fractional_wrap_clamp"]
    assert entries
    for e in entries:
        assert e["right"] <= e["wrapRight"], (
            f"bar.right={e['right']} crossed the visible bound {e['wrapRight']}"
        )
        assert e["right"] == pytest.approx(e["wrapRight"], abs=1e-9)


# ============== 4. preserved behaviour (ownership / batch / count) ============


def test_selection_still_owns_the_bar_against_hover(harness):
    """Hovering another row must not move or retarget a selection-owned bar."""
    s = harness["selection_owns_bar_against_hover"]
    assert s["before"]["left"] == s["afterHoveringOther"]["left"]
    assert s["before"]["buttons"] == s["afterHoveringOther"]["buttons"]


def test_batch_mode_hides_single_row_actions_and_shows_the_count(harness):
    s = harness["batch_mode"]
    assert s["countHidden"] is False
    assert s["countText"] == "2"
    assert s["emailHidden"] is False, "both rows have a pending e-mail"
    assert s["geometry"]["buttons"] == ["selection-count", "email"]
    _assert_contained(s["geometry"], "batch mode")


def test_batch_email_requires_every_selected_row_to_be_pending(harness):
    s = harness["batch_mode_mixed_email_eligibility"]
    assert s["countHidden"] is False
    assert s["countText"] == "2"
    assert s["emailHidden"] is True, "a partial batch must not offer Enviar e-mail"
    _assert_contained(s["geometry"], "mixed batch")


def test_no_empty_count_bubble_when_the_batch_collapses(harness):
    s = harness["empty_count_bubble_after_batch_collapses"]
    assert s["countHidden"] is True
    assert s["countText"] == ""
    assert "selection-count" not in s["geometry"]["buttons"]
    _assert_contained(s["geometry"], "single selection after a batch")
