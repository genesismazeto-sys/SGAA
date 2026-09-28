"""UI-B11 category A: raw colours that duplicate an existing DS token by value
*and* role now reference the token (zero visual change).

39 occurrences across 19 owners were converted (see
``docs/backlog/UI_B11_RAW_COLOUR_AUDIT.md``): card/panel surfaces ->
``--surface``, muted/empty-state text -> ``--text-secondary``, field fills ->
``--field-bg``, selection/hover accent -> ``--accent-blue``, ``.btn.primary:hover``
-> ``--btn-primary-strong``, focus outlines -> ``--focus-ring-color``.

Category B/C/E findings (including the Alertas swatch outline ``#0f5b99``, the
colour-dot hairline and the border-only white swatch) are deliberately left
literal. The product-wide raw-colour count may only shrink.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOKENS = (ROOT / "static/css/foundation/tokens.css").read_text(encoding="utf-8")

# Measured after the category-A pass (audit baseline was 498).
MAX_RAW_COLOURS = 459

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


def test_alertas_user_colour_findings_stay_literal():
    """Category B/C, not A: data colours and the missing control-selected token."""
    alertas = _read("templates/admin_alertas.html")
    assert "outline:3px solid #0f5b99" in _rule(alertas, ".palette-swatch.is-selected")
    assert "rgba(0,0,0,.12)" in _rule(alertas, ".alerta-color-dot")
    assert "background:#fff" in _rule(alertas, ".alerta-color-swatch.border-only")
