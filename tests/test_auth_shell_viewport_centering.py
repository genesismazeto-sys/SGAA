"""The shared authentication shell centres its card in the viewport.

`login.html`, `forgot_password.html` and `set_password.html` do not extend
`base.html`. Between `<body>` and `.login-card` there is exactly one layout
owner -- `<main class="login-page">` -- so if that element does not claim the
usable viewport height, nothing above the card does, the card shrink-wraps at
the top of the page, and the whole empty remainder lands below it. That was
the defect: `.login-page` set only `width`, `max-width` and `padding`, and the
card's horizontal `margin:0 auto` was the only centring in the stack.

These assertions are structural on purpose. They pin the CONTRACT (which owner
centres, by what mechanism, with what overflow behaviour) rather than rendered
coordinates, so they run browser-free in the canonical suite. The two
properties worth restating, because a future edit can satisfy "centred" while
breaking either one:

  VIEWPORT, NOT WRAPPER -- the shell centres against the viewport via
  `min-height`. A rigid `height:100vh` would clip a card taller than the
  screen, so `height` is forbidden here.

  AUTO MARGINS, NOT align-items -- both centre a card that fits; only auto
  margins stay reachable when it does not. Auto margins resolve to 0 once free
  space goes negative, so an overflowing card starts at the container's
  padding edge and the page scrolls normally. `align-items:center` splits the
  overflow evenly and pushes the top of the card above the scroll origin,
  where it cannot be reached.
"""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
GLOBAL_CSS = PROJECT_ROOT / "static" / "css" / "modern-style.css"
CSS_ROOT = PROJECT_ROOT / "static" / "css"

# Every public surface that renders on the shared auth shell.
AUTH_TEMPLATES = ("login.html", "forgot_password.html", "set_password.html")

# Offsets that fake centring instead of expressing it. Any of these inside the
# shell's own rules means someone nudged the card by hand.
FORBIDDEN_OFFSETS = ("margin-top", "margin-bottom", "transform", "translate", "position")


def _rule_body(css: str, selector: str) -> str:
    """Return the declaration block of the single top-level rule for `selector`."""
    pattern = r"(?m)^" + re.escape(selector) + r"\s*\{([^}]*)\}"
    matches = re.findall(pattern, css)
    assert matches, f"{selector} rule is missing from modern-style.css"
    assert len(matches) == 1, (
        f"{selector} is declared {len(matches)} times. The auth shell has one "
        "owner; a second rule is where a surface-specific override would hide."
    )
    return matches[0]


def _declarations(body: str) -> list[tuple[str, str]]:
    """(property, value) pairs in source order -- duplicates preserved."""
    return [
        (prop, value.strip())
        for prop, value in re.findall(r"([\w-]+)\s*:\s*([^;]+);", body)
    ]


def test_auth_shell_claims_the_viewport_and_centres_the_card():
    """`.login-page` expresses genuine viewport centring, not a wrapper's."""
    body = _rule_body(GLOBAL_CSS.read_text(encoding="utf-8"), ".login-page")
    declarations = _declarations(body)
    values = dict(declarations)

    assert values.get("display") == "flex", (
        ".login-page must be a flex container -- that is what lets the card's "
        f"auto margins absorb the free space. display is {values.get('display')!r}."
    )

    min_heights = [value for prop, value in declarations if prop == "min-height"]
    assert min_heights, (
        ".login-page has no min-height, so <main> shrink-wraps the card and the "
        "card lands at the top of the page. This is the original defect."
    )
    assert "100dvh" in min_heights, (
        "the shell must size to the dynamic viewport (100dvh), the unit this "
        f"project already uses for viewport-bound boxes. Found {min_heights}."
    )
    assert min_heights.index("100vh") < min_heights.index("100dvh"), (
        "100vh must come first as the fallback; a browser without dvh support "
        "needs to land on it, and a browser with support overrides it."
    )

    assert "height" not in values, (
        f"height:{values.get('height')} is rigid -- a card taller than the "
        "viewport would be clipped with no way to scroll to the rest. The "
        "shell must size with min-height."
    )


def test_auth_shell_centres_with_auto_margins_not_align_items():
    """The overflow-safe centring mechanism, stated as a contract."""
    css = GLOBAL_CSS.read_text(encoding="utf-8")
    page = dict(_declarations(_rule_body(css, ".login-page")))
    card = dict(_declarations(_rule_body(css, ".login-card")))

    assert card.get("margin") == "auto", (
        f"the card centres via margin:auto; found margin:{card.get('margin')!r}. "
        "margin:0 auto centres horizontally only and leaves the card at the top."
    )

    for clipping_property in ("align-items", "place-items", "place-content"):
        assert clipping_property not in page, (
            f"{clipping_property}:{page[clipping_property]} centres the card by "
            "splitting any overflow evenly, which puts the top of a tall card "
            "above the scroll origin. Auto margins on .login-card already "
            "centre it and degrade safely instead."
        )
    assert page.get("justify-content") != "center", (
        "justify-content:center has the same unreachable-edge failure mode as "
        "align-items:center. The card's auto margins handle both axes."
    )


def test_auth_shell_reserves_vertical_padding_for_short_viewports():
    """Safe padding, so an overflowing card never sits flush against the edge."""
    page = dict(_declarations(_rule_body(GLOBAL_CSS.read_text(encoding="utf-8"), ".login-page")))
    padding = page.get("padding")
    assert padding, ".login-page lost its padding"

    tracks = padding.split()
    vertical = tracks[0]
    horizontal = tracks[1] if len(tracks) > 1 else tracks[0]
    assert vertical.endswith("px") and int(vertical[:-2]) > 0, (
        f"vertical padding is {vertical!r}. With zero vertical padding an "
        "overflowing card touches the top edge of the viewport."
    )
    assert horizontal == "16px", (
        f"horizontal padding changed to {horizontal!r}. The centring repair "
        "must not alter the card's gutter on narrow screens."
    )


def test_auth_shell_carries_no_hand_tuned_offset():
    """No magic number anywhere in the shell's own two rules."""
    css = GLOBAL_CSS.read_text(encoding="utf-8")
    for selector in (".login-page", ".login-card"):
        body = _rule_body(css, selector)
        # Strip comments: the rules document what they deliberately avoid.
        declarations = _declarations(re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL))
        for prop, value in declarations:
            assert prop not in FORBIDDEN_OFFSETS, (
                f"{selector} declares {prop}:{value}. Vertical placement is the "
                "flex container's job; a hand-tuned offset here is the kind of "
                "fix that holds at one viewport and drifts at every other."
            )
            assert "translateY" not in value


def test_card_keeps_its_horizontal_centring_and_geometry():
    """The repair is vertical only -- the card itself is untouched."""
    card = dict(_declarations(_rule_body(GLOBAL_CSS.read_text(encoding="utf-8"), ".login-card")))
    assert card.get("max-width") == "400px"
    assert card.get("width") == "100%"
    assert card.get("padding") == "24px"
    assert card.get("text-align") == "center"
    assert card.get("border-radius") == "var(--radius)"
    assert card.get("background") == "var(--surface)"
    assert card.get("border") == "1px solid var(--border-strong)"
    assert card.get("box-shadow") == "0 8px 20px rgba(0,0,0,.1)"


def test_every_auth_surface_shares_the_one_centring_contract():
    """Login, recovery and set-password inherit the fix; none overrides it."""
    for name in AUTH_TEMPLATES:
        source = (PROJECT_ROOT / name.join(("templates/", ""))).read_text(encoding="utf-8")
        assert '<main class="login-page">' in source, (
            f"{name} must render the shared auth shell so it inherits the "
            "centring contract rather than growing a parallel one"
        )
        assert '<div class="login-card">' in source
        assert "style=" not in source.split("</head>", 1)[-1], (
            f"{name} carries an inline style in its body; the shell's geometry "
            "has a single owner in modern-style.css"
        )

    # No stylesheet may re-open the shell to move one surface on its own.
    for stylesheet in sorted(CSS_ROOT.rglob("*.css")):
        css = stylesheet.read_text(encoding="utf-8")
        for selector in re.findall(r"(?m)^([^@{}/\n][^{}\n]*)\{", css):
            if "login-page" not in selector and "login-card" not in selector:
                continue
            owned = stylesheet == GLOBAL_CSS and selector.strip() in {
                ".login-page",
                ".login-card",
            }
            assert owned, (
                f"{stylesheet.relative_to(PROJECT_ROOT)} declares {selector.strip()!r}. "
                "The auth shell is owned by .login-page/.login-card in "
                "modern-style.css; a second rule splits the contract."
            )
