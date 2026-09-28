"""UI-B14: ordinary form fields share one border-radius owner -- ``var(--radius)``.

Audit result (2026-09-28): every field frame -- ``.field-card`` (which draws the
frame for carded input/select/textarea/date/number), a bare ``select.control``,
``.field input/select/textarea``, the toolbar select and input group, and the
page-local field rules -- resolves to ``var(--radius)``; a headless-Chromium
probe of eight representative surfaces measured 4px for every control. This
guard keeps it that way. Pills, switches, swatches, chips and buttons are out of
scope (DS-PILL-RADIUS is a separate, deferred decision).
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODERN = (ROOT / "static" / "css" / "modern-style.css").read_text(encoding="utf-8")


def _rule(selector_regex: str) -> str:
    match = re.search(selector_regex + r"\s*\{([^}]*)\}", MODERN)
    assert match, selector_regex
    return match.group(1)


def test_shared_field_frames_use_the_radius_token():
    for selector in (
        r"(?m)^\.field-card",
        r"\.field input,\.field select,\.field textarea",
        r"(?m)^\.app-main \.toolbar \.filters select",
        r"(?m)^\.app-main \.toolbar \.filters \.input-group",
    ):
        assert "border-radius:var(--radius)" in _rule(selector).replace(" ", ""), selector
    assert "select.control{ border-radius:var(--radius); }" in MODERN


def test_no_template_gives_a_form_field_a_hard_coded_radius():
    offenders = []
    for path in (ROOT / "templates").rglob("*.html"):
        for style in re.findall(r"<style[^>]*>(.*?)</style>", path.read_text(encoding="utf-8"), re.S):
            for selector, body in re.findall(r"([^{}]+)\{([^}]*)\}", style):
                field = re.search(r"(^|[\s,>])(select|textarea|input(\[[^\]]*\])?|\.control)\b", selector)
                radius = re.search(r"border-radius\s*:\s*([^;]+)", body)
                if field and radius and "var(--radius)" not in radius.group(1) and "chip" not in selector:
                    offenders.append(f"{path.name}: {selector.strip()} -> {radius.group(1).strip()}")
    assert offenders == [], offenders
