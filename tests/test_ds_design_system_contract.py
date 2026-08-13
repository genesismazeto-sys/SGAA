"""Design System structural contract gates.

These tests protect the *architecture* of the visual layer, not its formatting.
They deliberately avoid freezing CSS text: a gate that fails when someone
reformats a rule is noise, and noise gets disabled.

What is enforced here:

ASSET       every design-system stylesheet a template links actually exists.
FOUNDATION  every page loads foundation/tokens.css, and loads it first.
OWNERSHIP   a global token is defined in exactly one place: tokens.css.
CONSISTENCY no token resolves to two different values on the same page.
PURITY      tokens.css declares tokens only — no visual rules.
RATCHET     the amount of CSS living inside templates may shrink, never grow.

The heavy cascade-equivalence proof used during migrations lives in
``tools/ds_css.py`` (``--compare``); it is a developer gate, not a unit test,
because it needs a before/after pair.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools import ds_css as ds  # noqa: E402

TOKENS_CSS = "static/css/foundation/tokens.css"
GLOBAL_CSS = "static/css/modern-style.css"


@pytest.fixture(scope="module")
def pages() -> list[Path]:
    found = ds.page_templates()
    assert found, "no page templates resolved — the analyser lost sight of the templates"
    return found


# ---------------------------------------------------------------- ASSET

def test_every_referenced_stylesheet_exists(pages):
    """A linked stylesheet that does not exist is a silent 404 in production."""
    missing = [
        (ds.rel_path(page), source.ident)
        for page in pages
        for source in ds.page_sources(page)
        if source.missing
    ]
    assert not missing, f"templates link stylesheets that do not exist: {missing}"


# ----------------------------------------------------------- FOUNDATION

def test_every_page_loads_the_token_foundation_first(pages):
    """Guards the load-order contract *and* guards against analyser blindness.

    If a refactor hides stylesheet loading behind something ``ds_css`` cannot
    resolve, this test fails loudly instead of the cascade gate silently
    comparing two empty stylesheets.
    """
    offenders = []
    for page in pages:
        idents = [s.ident for s in ds.page_sources(page)]
        if TOKENS_CSS not in idents:
            offenders.append((ds.rel_path(page), "does not load tokens.css", idents))
            continue
        if GLOBAL_CSS in idents and idents.index(TOKENS_CSS) > idents.index(GLOBAL_CSS):
            offenders.append((ds.rel_path(page), "loads tokens.css after modern-style.css", idents))
    assert not offenders, f"foundation load-order contract violated: {offenders}"


def test_no_template_is_invisible_to_the_analyser():
    """Every ``{% extends %}`` must be statically resolvable.

    A template whose parent cannot be resolved is silently treated as a
    non-page: it disappears from the cascade gate, from the token-ownership
    gate and from any inventory built on ``page_templates()``. That is exactly
    how ``aluno_reportar.html`` — which extends
    ``base_template|default("base_aluno.html")`` — escaped the DS-3 consumer
    inventory and briefly lost its raised button.
    """
    offenders = ds.templates_with_unresolvable_extends()
    assert not offenders, (
        "templates whose parent the analyser cannot resolve (they would be "
        f"skipped by every static gate): {offenders}"
    )


def test_analyser_sees_every_full_document_template():
    """Guards the page count itself against silent shrinkage."""
    full_documents = {
        ds.rel_path(p)
        for p in ds.TEMPLATES_DIR.rglob("*.html")
        if "<head" in p.read_text(encoding="utf-8", errors="replace").lower()
        or ds.parent_template_name(p.read_text(encoding="utf-8", errors="replace"))
    }
    seen = {ds.rel_path(p) for p in pages_cached()}
    missed = sorted(full_documents - seen)
    assert not missed, f"templates that render a document but resolve to no CSS: {missed}"


def pages_cached():
    if not hasattr(pages_cached, "_v"):
        pages_cached._v = ds.page_templates()
    return pages_cached._v


# ------------------------------------------------------------ OWNERSHIP

# Tokens still declared at :root outside tokens.css. This list may only shrink.
# --card-gap is template-owned and has no global definition; the two nudge
# tokens are redundant re-declarations with values identical to tokens.css and
# are removed when those templates are repatriated.
KNOWN_ROOT_TOKEN_OWNERSHIP_EXCEPTIONS = {
    "--btn-icon-nudge-y",
    "--btn-text-nudge-y",
    "--card-gap",
}


def _root_token_sources(pages) -> dict[str, set[str]]:
    sources: dict[str, set[str]] = {}
    for page in pages:
        for decl in ds.page_stream(page):
            if decl.context or decl.selector != ":root" or not decl.prop.startswith("--"):
                continue
            sources.setdefault(decl.prop, set()).add(decl.source)
    return sources


def test_global_tokens_have_exactly_one_owner(pages):
    """No global token may be re-declared at :root outside tokens.css."""
    violations = {
        token: sorted(srcs)
        for token, srcs in _root_token_sources(pages).items()
        if len(srcs) > 1 and token not in KNOWN_ROOT_TOKEN_OWNERSHIP_EXCEPTIONS
    }
    assert not violations, (
        "tokens defined at :root in more than one file (global tokens belong in "
        f"{TOKENS_CSS}): {violations}"
    )


def test_ownership_exception_list_does_not_grow(pages):
    """The allowlist is a ratchet: entries may be removed, never added."""
    actual = {
        token
        for token, srcs in _root_token_sources(pages).items()
        if len(srcs) > 1
    }
    unexpected = actual - KNOWN_ROOT_TOKEN_OWNERSHIP_EXCEPTIONS
    assert not unexpected, f"new :root token ownership violations: {sorted(unexpected)}"


# ----------------------------------------------------------- CONSISTENCY

def test_no_token_resolves_to_two_values_on_one_page(pages):
    """Two competing :root definitions with different values is a real defect."""
    conflicts = []
    for page in pages:
        values: dict[str, set[str]] = {}
        for decl in ds.page_stream(page):
            if decl.context or decl.selector != ":root" or not decl.prop.startswith("--"):
                continue
            values.setdefault(decl.prop, set()).add(decl.value)
        for token, vals in values.items():
            if len(vals) > 1:
                conflicts.append((ds.rel_path(page), token, sorted(vals)))
    assert not conflicts, f"conflicting :root token values: {conflicts}"


# --------------------------------------------------------------- PURITY

def test_tokens_file_declares_tokens_only():
    """tokens.css is a contract file: :root custom properties and nothing else."""
    path = PROJECT_ROOT / TOKENS_CSS
    assert path.exists(), f"{TOKENS_CSS} is missing"
    decls = ds.parse_declarations(path.read_text(encoding="utf-8"), TOKENS_CSS)
    assert decls, "tokens.css parsed to zero declarations"

    bad_selectors = sorted({d.selector for d in decls if d.selector != ":root" or d.context})
    assert not bad_selectors, f"tokens.css must only use :root, found: {bad_selectors}"

    bad_props = sorted({d.prop for d in decls if not d.prop.startswith("--")})
    assert not bad_props, f"tokens.css must only declare custom properties, found: {bad_props}"


# -------------------------------------------------------------- RATCHET

TEMPLATES_DIR = PROJECT_ROOT / "templates"

# Current volume of CSS still living inside templates. These are ceilings:
# migration phases lower them. Raising one means CSS moved the wrong way.
MAX_TEMPLATES_WITH_STYLE_BLOCKS = 42
MAX_STATIC_INLINE_STYLE_ATTRS = 198


def _template_texts():
    for path in sorted(TEMPLATES_DIR.rglob("*.html")):
        yield path, path.read_text(encoding="utf-8", errors="replace")


def test_templates_with_style_blocks_does_not_grow():
    count = sum(
        1 for _path, text in _template_texts() if re.search(r"<style\b", text, re.I)
    )
    assert count <= MAX_TEMPLATES_WITH_STYLE_BLOCKS, (
        f"{count} templates contain <style> blocks, ceiling is "
        f"{MAX_TEMPLATES_WITH_STYLE_BLOCKS}. New CSS belongs in a stylesheet with a "
        "named owner, not in a template."
    )


def test_static_inline_style_attributes_do_not_grow():
    count = 0
    for _path, text in _template_texts():
        for match in re.finditer(r'style="([^"]*)"', text):
            value = match.group(1)
            if "{{" not in value and "{%" not in value:
                count += 1
    assert count <= MAX_STATIC_INLINE_STYLE_ATTRS, (
        f"{count} static style=\"\" attributes, ceiling is "
        f"{MAX_STATIC_INLINE_STYLE_ATTRS}. A static inline style has no owner and "
        "cannot be themed — use a component class."
    )
