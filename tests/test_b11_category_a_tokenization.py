"""UI-B11 raw-colour cohorts: literals that share an exact value and role with a
Design System token now reference the token (zero visual change), plus the
value-preserving semantic tokens this phase introduced.

First category-A cohort (2026-09-28, 39 occurrences): card/panel surfaces ->
``--surface``, muted/empty-state text -> ``--text-secondary``, field fills ->
``--field-bg``, selection/hover accent -> ``--accent-blue``, ``.btn.primary:hover``
-> ``--btn-primary-strong``, focus outlines -> ``--focus-ring-color``.

Second cohort (2026-09-29, 28 occurrences): white fills that restate the
button/card surface layer; the computed "Fim" card -> ``--field-readonly-bg``;
the Cursos pills -> the shared status-pill properties; inert ``var()``
fallbacks on tokens tokens.css always defines were dropped.

Third cohort — missing semantic tokens (2026-10-02, 430 -> 291): the absent
families become global tokens in ``foundation/tokens.css`` at their EXACT
current values, and every occurrence whose semantic role is unambiguous adopts
them:

* ``--surface-subtle`` / ``--hover-bg`` — subtle fills and hover fills
  (table headers, chip backgrounds, menu/filter hovers);
* ``--field-chip-bg`` — the resting file-card trailing chip;
* ``--divider`` / ``--divider-soft`` — hairlines and soft dividers;
* ``--text-on-brand`` — white ink on brand/dark fills;
* ``--control-selected`` — the Alertas selected swatch and the toggle switch;
* ``--info-bg/-text/-border`` and ``--danger-text/-bg/-border`` — the generic
  status families (field validation keeps its own ``--field-invalid-*``);
* ``--shadow-card`` / ``--shadow-modal`` / ``--backdrop`` — the repeated
  application elevation and scrim values, kept whole (colour + geometry);
* the shared ``--status-*`` palette, promoted from the byte-identical
  ``.badge.status-pill`` and ``admin_banco_dados`` ``.db-badge`` copies; the
  four dead ``.db-provider-head .db-badge`` fallbacks were removed.

The phantom references ``var(--danger, #b91c1c)``, ``var(--surface-alt,
#f8fafc)`` and ``var(--surface-2, #f2f2f2)`` resolve to real tokens.

Everything else is deliberately left literal (component-local, content colour,
or waiting for a visual-convergence decision), including the zinc/slate
families, the warning/success variants, the chart ramp, the colour ramps inside
gradients, the file-card chip ink ``#000``, the Requisições decision-button
palette in the JS-injected stylesheet, and the Alertas user colours.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOKENS = (ROOT / "static/css/foundation/tokens.css").read_text(encoding="utf-8")

# Measured after the third cohort (audit baseline was 498; cohorts: 459, 430).
MAX_RAW_COLOURS = 291

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
    pairs = (
        ("--text-secondary", "#6b7280"),
        ("--btn-primary-strong", "#002244"),
        ("--focus-ring-color", "rgba(37,99,235,.35)"),
        # Third cohort: every occurrence of these values is now a token reference.
        ("--control-selected", "#0f5b99"),
        ("--info-bg", "#eff6ff"),
        ("--info-text", "#1d4ed8"),
        ("--info-border", "#bfdbfe"),
        ("--danger-text", "#b91c1c"),
        ("--danger-bg", "#fef2f2"),
        ("--danger-border", "#fecaca"),
        ("--field-chip-bg", "#f2f2f2"),
        ("--divider-soft", "rgba(15,23,42,.08)"),
        ("--backdrop", "rgba(2,6,23,.45)"),
        ("--status-positive-bg", "#e9f5e7"),
        ("--status-positive-border", "#b9d7b5"),
        ("--status-positive-text", "#1f5a3c"),
        ("--status-positive-dot", "#3e835a"),
        ("--status-neutral-bg", "#eef1f4"),
        ("--status-neutral-border", "#c4ced8"),
        ("--status-neutral-text", "#3a4755"),
        ("--status-neutral-dot", "#667585"),
        ("--status-caution-bg", "#faeed5"),
        ("--status-caution-border", "#e3c17b"),
        ("--status-caution-text", "#7b4b12"),
        ("--status-caution-dot", "#c5801f"),
        ("--status-negative-bg", "#f9e3e6"),
        ("--status-negative-border", "#e3b0b8"),
        ("--status-negative-text", "#8d2431"),
        ("--status-negative-dot", "#cb4859"),
        ("--status-info-bg", "#e4eff9"),
        ("--status-info-border", "#b5d0e7"),
        ("--status-info-text", "#1d5a83"),
        ("--status-info-dot", "#3e7fb0"),
    )
    for token, raw in pairs:
        assert f"{token}:{raw}" in TOKENS.replace(" ", ""), (token, raw)
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
    """tokens.css loads first on every page, so such a fallback never renders and silently drifts."""
    defined = set(re.findall(r"(--[\w-]+)\s*:", TOKENS))
    offenders = [
        (str(path.relative_to(ROOT)), token)
        for path, text in _product_colour_sites()
        for token in re.findall(rf"var\(\s*(--[\w-]+)\s*,\s*(?:{_HEX}|(?:rgba?|hsla?)\()", text)
        if token in defined
    ]
    assert offenders == [], offenders


def test_no_phantom_token_references_remain():
    """The tokens the code referenced before they existed now resolve to real values."""
    for phantom in ("var(--danger,", "var(--danger ", "var(--surface-alt,", "var(--surface-2,"):
        offenders = [str(path.relative_to(ROOT)) for path, text in _product_colour_sites() if phantom in text.replace("\n", "")]
        assert offenders == [], (phantom, offenders)
    assert "--danger-text:#b91c1c" in TOKENS.replace(" ", "")
    assert "--field-chip-bg:#f2f2f2" in TOKENS.replace(" ", "")
    assert "--hover-bg:#f8fafc" in TOKENS.replace(" ", "")


def test_info_and_danger_families_are_used_at_their_current_values():
    modern = _read("static/css/modern-style.css")
    assert "color:var(--info-text)" in _rule(modern, ".login-feedback-info")
    assert "color:var(--danger-text)" in _rule(modern, ".login-feedback-error")
    assert "background:var(--danger-bg)" in _rule(modern, ".table-progresso td.progresso-limitado")
    assert "background:var(--danger-bg)" in _rule(_read("templates/admin_diagnostico_atividades_versionadas_view.html"), ".diag-alert")
    assert "border:1px solid var(--danger-border)" in _rule(_read("templates/admin_requisicoes.html"), ".req-email-warnings")
    grupos = _read("templates/admin_atividades.html")
    assert "background:var(--info-bg); border-color:var(--info-border);" in _rule(grupos, "#grupos-modal .menu-item.is-selected")
    presets = _read("templates/admin_requisicoes.html")
    assert "background:var(--info-bg); border-color:var(--info-border); color:var(--info-text);" in _rule(presets, ".presets-ph:hover")


def test_subtle_hover_divider_on_brand_and_control_tokens_are_used():
    cards = _read("static/css/components/list-cards.css")
    assert "background:var(--hover-bg)" in _rule(cards, ".menu-item:hover")
    assert "border-top:1px solid var(--divider)" in _rule(cards, ".check-row")
    assert "background:var(--hover-bg)" in _rule(_read("static/css/components/actions-float.css"), "#pedido-actions-float .act-btn:hover").replace(" ", "")
    assert "background:var(--field-chip-bg)" in _rule(_read("static/css/components/form.css"), ".import-modal-form .field-card.file-card .chip-right")
    assert "--toggle-switch-active:var(--control-selected)" in _read("static/css/components/form.css").replace(" ", "")
    assert "var(--text-on-brand)" in _rule(_read("static/css/modern-style.css"), ".btn.primary")
    assert "color:var(--text-on-brand)" in _read("templates/base.html").replace(" ", "")
    assert "background:var(--surface-subtle)" in _rule(_read("templates/admin_reportes.html"), ".reporte-modal-desc")


def test_shared_elevation_and_backdrop_keep_the_whole_value():
    assert "--shadow-card:0 1px 2px rgba(15,23,42,.04), 0 1px 3px rgba(15,23,42,.06)" in TOKENS
    assert "--shadow-modal:0 10px 30px rgba(2,6,23,.25)" in TOKENS
    assert "box-shadow:var(--shadow-card)" in _rule(_read("templates/admin_acesso.html"), ".access-default-card")
    assert "box-shadow:var(--shadow-modal)" in _rule(_read("static/css/components/modal.css"), ".modal-card")
    assert "background:var(--backdrop)" in _rule(_read("static/css/components/modal.css"), ".modal-overlay")
    assert "background: var(--backdrop)" in _rule(_read("templates/admin_matriz_form.html"), ".matriz-modal-overlay")


def test_status_palette_has_one_global_owner():
    modern = _read("static/css/modern-style.css")
    for state in ("positive", "neutral", "caution", "negative", "info"):
        body = _rule(modern, f".badge.status-pill.status-{state}")
        for part in ("bg", "border", "text", "dot"):
            assert f"--status-pill-{part}:var(--status-{state}-{part})" in body, (state, part)
    banco = _read("templates/admin_banco_dados.html")
    for state, klass in (("positive", ".local"), ("caution", ".warning"), ("neutral", ":not(.local):not(.warning)")):
        body = _rule(banco, f".db-provider-head .db-badge{klass}")
        for part in ("bg", "border", "text", "dot"):
            assert f"--status-pill-{part}:var(--status-{state}-{part})" in body, (state, part)
    base = _rule(banco, ".db-provider-head .db-badge")
    for prop, var in (("border", "border"), ("background", "bg"), ("color", "text")):
        assert f"var(--status-pill-{var})" in base, prop
        assert f"var(--status-pill-{var}," not in base.replace(" ", ""), prop
    assert "var(--status-pill-dot)" in _rule(banco, ".db-provider-head .db-badge::before")


def test_alertas_user_colour_findings_stay_literal():
    """Data colours stay content-local; the selected-swatch outline is the shared control token."""
    alertas = _read("templates/admin_alertas.html")
    assert "outline:3px solid var(--control-selected)" in _rule(alertas, ".palette-swatch.is-selected")
    assert "rgba(0,0,0,.12)" in _rule(alertas, ".alerta-color-dot")
    assert "background:#fff" in _rule(alertas, ".alerta-color-swatch.border-only")
