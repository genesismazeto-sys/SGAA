"""UI-B11 category A: raw colours that duplicate an existing DS token by value
*and* role now reference the token (zero visual change).

39 occurrences across 19 owners were converted (see
``docs/backlog/UI_B11_RAW_COLOUR_AUDIT.md``): card/panel surfaces ->
``--surface``, muted/empty-state text -> ``--text-secondary``, field fills ->
``--field-bg``, selection/hover accent -> ``--accent-blue``, ``.btn.primary:hover``
-> ``--btn-primary-strong``, focus outlines -> ``--focus-ring-color``.

Second cohort (2026-09-29, 28 occurrences, zero visual change): white fills
that restate the button/card surface layer -> ``--surface`` (skip link,
sidebar hover/active, avatar frame, ``.icon-btn.danger``, the Banco de Dados
folder close button, the Atividades/Requisições mini-toolbar buttons); the
computed "Fim" card ``.field-card.is-off`` -> ``--field-readonly-bg``; the
Cursos pills that restated the shared status palette -> the status-pill
component's own ``--status-pill-*`` properties; and inert ``var()`` fallbacks
on tokens that tokens.css always defines were dropped.

Everything else is deliberately left literal (component-local, content colour,
or waiting for a semantic-token decision), including the Alertas swatch outline
``#0f5b99``, the colour-dot hairline and the border-only white swatch. The
product-wide raw-colour count may only shrink.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOKENS = (ROOT / "static/css/foundation/tokens.css").read_text(encoding="utf-8")

# Measured after the second category-A cohort (audit baseline was 498, first pass 459).
MAX_RAW_COLOURS = 430

_HEX = r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b"
_COLOUR = re.compile(rf"({_HEX}|(?:rgba?|hsla?)\([^)]*\))")


def _product_colour_sites():
    """Same scope as the audit: CSS (minus tokens.css), JS, template <style> and style=""."""
    for path in sorted((ROOT / "static/css").rglob("*.css")):
        if path.name != "tokens.css":
            yield path, re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
    for path in sorted((ROOT / "static/js").rglob("*.js")):
        yield path, path.read_text(encoding="utf-8")
    for path in sorted((ROOT / "templates").rglob("*.html")):
        text = path.read_text(encoding="utf-8")
        chunks = [re.sub(r"/\*.*?\*/", "", block, flags=re.S) for block in re.findall(r"<style[^>]*>(.*?)</style>", text, re.S | re.I)]
        chunks += re.findall(r'style="([^"]*)"', text)
        yield path, "\n".join(chunks)


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _rule(source: str, selector: str) -> str:
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", source)
    assert match, selector
    return match.group(1)


def test_the_raw_colour_count_only_shrinks():
    total = sum(len(_COLOUR.findall(text)) for _path, text in _product_colour_sites())
    assert total <= MAX_RAW_COLOURS, f"{total} raw colours in product UI code, ceiling {MAX_RAW_COLOURS}"


def test_fully_tokenized_values_survive_only_in_the_token_owner():
    for raw, token in (("#6b7280", "--text-secondary"), ("#002244", "--btn-primary-strong"), ("rgba(37,99,235,.35)", "--focus-ring-color")):
        assert f"{token}:{raw}" in TOKENS.replace(" ", "")
        offenders = [str(path.relative_to(ROOT)) for path, text in _product_colour_sites() if raw in text.replace(" ", "").lower()]
        assert offenders == [], (raw, offenders)


def test_surfaces_use_the_surface_token():
    sites = {
        "templates/admin_banco_dados.html": (".db-card", ".db-provider-card", ".db-folder-modal-panel", ".db-folder-item"),
        "templates/admin_acesso.html": (".access-default-card", ".access-policy-summary", ".access-scope-card"),
        "templates/admin_turmas.html": (".import-help-code", ".import-help-note"),
        "templates/admin_atividades.html": (".import-help-code",),
        "templates/admin_importar_atividades.html": (".import-help-code",),
        "templates/admin_dashboard.html": (".dashboard-empty-state",),
        "templates/admin_diagnostico_atividades_versionadas_view.html": (".diag-card",),
    }
    for rel, selectors in sites.items():
        source = _read(rel)
        for selector in selectors:
            body = _rule(source, selector)
            assert re.search(r"background\s*:\s*var\(--surface\)", body), (rel, selector)


def test_field_fills_accent_primary_hover_and_focus_use_their_tokens():
    modern = _read("static/css/modern-style.css")
    assert "background:var(--field-bg)" in _rule(modern, ".progresso-type-select")
    assert "background:var(--field-bg)" in _rule(modern, ".field input,.field select,.field textarea")
    assert _rule(modern, ".btn.primary:hover").strip() == "background:var(--btn-primary-strong); border-color:var(--btn-primary-strong);"
    assert "background:var(--field-bg)" in _rule(_read("templates/admin_atividades.html"), "#grupos-modal .presets-col-right input.control")
    assert "background:var(--field-bg)" in _rule(_read("templates/admin_acesso.html"), ".access-scope-card select")
    assert "background:var(--field-bg)" in _rule(_read("templates/admin_requisicoes.html"), "#req-presets-modal .presets-col-right textarea.control")
    cards = _read("static/css/components/list-cards.css")
    assert "border-color:var(--accent-blue)" in _rule(cards, "#sort-menu .menu-item.selected")
    assert "border-color:var(--accent-blue)" in _rule(cards, ".impresso-card:hover:not(.selected)")
    assert "color:var(--text-secondary)" in _rule(cards, ".cell .muted")
    assert "color:var(--accent-blue) !important" in _read("templates/aluno_minhas_requisicoes.html")
    for rel in ("templates/admin_dashboard.html", "templates/aluno_dashboard.html"):
        assert "outline:2px solid var(--focus-ring-color);" in _read(rel), rel


def test_surface_layer_fills_use_the_surface_token():
    """White that restates the button/card surface (``.btn`` and ``.icon-btn`` already own it)."""
    modern = _read("static/css/modern-style.css")
    for selector in (".sr-only-focusable:focus", ".sidebar-link:hover", '.sidebar-link[data-active="true"]',
                     ".sidebar-link.active:hover", "#avatar-box", ".icon-btn.danger"):
        assert re.search(r"background\s*:\s*var\(--surface\)", _rule(modern, selector)), selector
    assert "background:var(--surface)" in _rule(_read("templates/admin_banco_dados.html"), ".db-folder-btn-close")
    for rel, prefix in (("templates/admin_atividades.html", "#grupos-modal .actions-mini #grp-"),
                        ("templates/admin_requisicoes.html", "#req-presets-modal .actions-mini #preset-")):
        source = _read(rel)
        for selector in (prefix + "add", prefix + "del:hover"):
            assert "background:var(--surface)" in _rule(source, selector), (rel, selector)


def test_computed_field_card_and_cursos_pills_use_their_owners():
    modern = _read("static/css/modern-style.css")
    assert "background:var(--field-readonly-bg)" in _rule(modern, ".field-card.is-off")
    cards = _read("static/css/components/list-cards.css")
    for state in ("positive", "negative"):
        body = _rule(cards, f".imp-cursos .badge.status-pill.status-{state}")
        assert body.strip() == ("color:var(--status-pill-text) !important; background-color:var(--status-pill-bg) !important;"
                                " border-color:var(--status-pill-border) !important;"), state


def test_no_colour_fallback_on_a_token_that_tokens_css_always_defines():
    """tokens.css loads first on every page, so such a fallback never renders and silently drifts.

    Fallbacks on tokens tokens.css does NOT define (``--danger``, ``--surface-alt``,
    ``--surface-2``, the status-pill component properties) are what renders and stay.
    """
    defined = set(re.findall(r"(--[\w-]+)\s*:", TOKENS))
    offenders = [
        (str(path.relative_to(ROOT)), token)
        for path, text in _product_colour_sites()
        for token in re.findall(rf"var\(\s*(--[\w-]+)\s*,\s*(?:{_HEX}|(?:rgba?|hsla?)\()", text)
        if token in defined
    ]
    assert offenders == [], offenders


def test_alertas_user_colour_findings_stay_literal():
    """Category B/C, not A: data colours and the missing control-selected token."""
    alertas = _read("templates/admin_alertas.html")
    assert "outline:3px solid #0f5b99" in _rule(alertas, ".palette-swatch.is-selected")
    assert "rgba(0,0,0,.12)" in _rule(alertas, ".alerta-color-dot")
    assert "background:#fff" in _rule(alertas, ".alerta-color-swatch.border-only")
