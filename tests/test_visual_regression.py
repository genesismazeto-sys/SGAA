"""Visual regression gate.

Renders the catalogue in a real browser and compares against the versioned
baselines in ``tests/visual/baseline``.

This is **opt-in**:

    python -m pytest tests/test_visual_regression.py --visual

It is skipped by default because it needs Playwright plus a downloaded browser,
it takes minutes rather than seconds, and its baselines are machine-specific
(webfonts are blocked for determinism, so text falls back to a system font).
Keeping it out of the default run also keeps the canonical suite count stable.

Setup:

    python -m pip install playwright
    python -m playwright install chromium

Regenerating baselines is a deliberate act — it re-approves the current
appearance:

    python -m tools.visual.harness

On failure a diff image is written next to the baselines under ``_diff/``,
with changed pixels in red.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

BASELINE_DIR = PROJECT_ROOT / "tests" / "visual" / "baseline"
DIFF_DIR = PROJECT_ROOT / "tests" / "visual" / "_diff"

# Tolerance, and the evidence for it.
#
# Repeated captures from the same process are byte-identical. Across separate
# processes the compositor occasionally rounds an edge pixel differently: two
# pages showed 5 and 7 differing pixels out of 1,296,000, every one of them a
# delta of exactly 1 in a single channel, confined to 2px-wide bounding boxes on
# rounded borders.
#
# So: allow a ±1 rounding wobble per channel, but allow *no* pixel to differ by
# more than that. A single pixel changing by 2 fails the gate. This is far
# stricter than the usual percentage-of-pixels threshold, which would let a
# small element change completely as long as it was small enough.
CHANNEL_TOLERANCE = 1
MAX_DIFFERING_PIXEL_RATIO = 0.0


def _requirements_missing() -> str | None:
    try:
        import playwright  # noqa: F401
    except ImportError:
        return "playwright is not installed (python -m pip install playwright)"
    if not BASELINE_DIR.exists() or not any(BASELINE_DIR.glob("*.png")):
        return f"no baselines in {BASELINE_DIR} (run python -m tools.visual.harness)"
    return None


@pytest.fixture(scope="module")
def captured(request) -> Path:
    if not request.config.getoption("--visual"):
        pytest.skip("visual regression is opt-in; pass --visual to run it")
    reason = _requirements_missing()
    if reason:
        pytest.skip(reason)

    from tools.visual.harness import capture_isolated

    out = Path(tempfile.mkdtemp(prefix="sgaa_visual_run_"))
    request.addfinalizer(lambda: shutil.rmtree(out, ignore_errors=True))
    written = capture_isolated(out)
    assert written, "the harness captured no screenshots"
    return out


def _baseline_names() -> list[str]:
    if not BASELINE_DIR.exists():
        return []
    return sorted(p.stem for p in BASELINE_DIR.glob("*.png"))


@pytest.mark.visual
@pytest.mark.parametrize("name", _baseline_names() or ["__no_baselines__"])
def test_page_matches_baseline(captured: Path, name: str):
    from tools.visual.imagediff import SizeMismatch, compare, write_png

    baseline = BASELINE_DIR / f"{name}.png"
    candidate = captured / f"{name}.png"
    assert candidate.exists(), (
        f"{name}: the harness produced no screenshot this run — the page may be "
        "erroring. Run `python -m tools.visual.harness --only " + name + "` to see why."
    )

    try:
        differing, total, diff, (width, height) = compare(
            baseline, candidate, channel_tolerance=CHANNEL_TOLERANCE
        )
    except SizeMismatch as exc:
        DIFF_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy(candidate, DIFF_DIR / f"{name}.actual.png")
        pytest.fail(f"{name}: layout size changed — {exc}. Actual saved to {DIFF_DIR}")

    ratio = differing / total if total else 0.0
    if ratio > MAX_DIFFERING_PIXEL_RATIO:
        DIFF_DIR.mkdir(parents=True, exist_ok=True)
        if diff is not None:
            write_png(DIFF_DIR / f"{name}.diff.png", width, height, diff)
        shutil.copy(candidate, DIFF_DIR / f"{name}.actual.png")
        pytest.fail(
            f"{name}: {differing} of {total} pixels differ ({ratio:.4%}). "
            f"Diff and actual written to {DIFF_DIR}. If this change is intended, "
            f"re-approve it with `python -m tools.visual.harness`."
        )
