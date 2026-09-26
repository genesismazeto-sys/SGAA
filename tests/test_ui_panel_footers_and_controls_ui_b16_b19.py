"""UI-B16..UI-B19 — panel footers, standalone select radius, add-student label.

The Design-System panel footer is the one the Configurações cards and the
Acesso "Senhas padrão" panel already use: a full-bleed
``1px solid var(--border-strong)`` divider over ``11px 16px`` of padding.

* UI-B16 Banco de dados: Operações, Política de retenção and Destinos e
  sincronização (settings footer + the provider cards' footers) adopt it.
* UI-B17 Ver versão: a ``select.control`` outside a ``.field-card`` takes the
  shared ``var(--radius)`` instead of the browser's own corner.
* UI-B18 Mensagens: every message card gains the footer divider.
* UI-B19 Adicionar aluno: the "Foto" row label is gone; its catalog key
  retires through the governed ledger.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests import canonical_baseline_support as governance


ROOT = Path(__file__).resolve().parents[1]
FOOTER_BORDER = "1px solid var(--border-strong)"


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8-sig")


def _rule(source: str, selector: str) -> dict[str, str]:
    """Declarations of the first rule whose selector is exactly ``selector``."""
    css = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    match = re.search(rf"(?m)^\s*{re.escape(selector)}\s*\{{([^}}]*)\}}", css)
    assert match, selector
    declarations: dict[str, str] = {}
    for chunk in match.group(1).split(";"):
        if ":" in chunk:
            prop, value = chunk.split(":", 1)
            declarations[prop.strip()] = " ".join(value.split())
    return declarations


# ------------------------------------------------------------------ UI-B16


def test_banco_card_footer_is_the_design_system_footer():
    source = _read("templates/admin_banco_dados.html")
    footer = _rule(source, ".db-card form > .db-actions")
    assert footer == {
        "justify-content": "flex-end",
        "margin": "16px -16px -16px",
        "padding": "11px 16px",
        "border-top": FOOTER_BORDER,
    }
    # The full-bleed margins are exactly the card's own padding.
    assert _rule(source, ".db-card")["padding"] == "16px"
    assert "#edf2f7" not in source


def test_banco_destinos_footer_and_provider_separator_do_not_stack():
    source = _read("templates/admin_banco_dados.html")
    assert _rule(source, ".db-card > form:has(+ .db-drive-sep) > .db-actions") == {
        "margin-bottom": "0"
    }
    assert _rule(source, ".db-card > form + .db-drive-sep") == {"margin-top": "0"}
    # The selectors above only hold if the Destinos settings form is followed
    # directly by the separator.
    destinos = source.split("{# ────────── Destinos e sincronização ────────── #}", 1)[1]
    destinos = destinos.split("{# ────────── Operações ────────── #}", 1)[0]
    assert re.search(
        r'<div class="db-actions">.*?Salvar destinos.*?</div>\s*</form>\s*'
        r"\{% else %\}.*?\{% endif %\}\s*<div class=\"db-drive-sep\"></div>",
        destinos,
        re.S,
    )


def test_banco_three_sections_each_end_in_one_footer_form():
    source = _read("templates/admin_banco_dados.html")
    sections = {
        "Operações": "Gerar backup agora",
        "Política de retenção": "Salvar política",
        "Destinos e sincronização": "Salvar destinos",
    }
    for label, action in sections.items():
        start = source.index(f'<span class="db-section-label">{label}</span>')
        article = source[start: source.index("</article>", start)]
        assert re.search(
            r'<div class="db-actions">(?:(?!</div>).)*' + re.escape(action),
            article,
            re.S,
        ), label
        footer = article.split('<div class="db-actions">')[-1].split("</form>", 1)[0]
        assert "style=" not in footer, label


def test_banco_provider_card_footer_follows_the_same_contract():
    source = _read("templates/admin_banco_dados.html")
    footer = _rule(source, ".db-provider-config-footer")
    assert footer["border-top"] == FOOTER_BORDER
    assert footer["padding"] == "11px 16px"
    assert footer["margin"] == "0 -16px -16px"
    # Declared after the shorthand, so it still pins the footer to the bottom.
    assert footer["margin-top"] == "auto"
    assert list(footer).index("margin") < list(footer).index("margin-top")
    assert _rule(source, ".db-provider-card")["padding"] == "16px"


# ------------------------------------------------------------------ UI-B17


def test_standalone_select_control_takes_the_shared_radius():
    css = _read("static/css/modern-style.css")
    assert _rule(css, "select.control") == {"border-radius": "var(--radius)"}
    tokens = _read("static/css/foundation/tokens.css")
    assert re.search(r"--radius:\s*4px\s*;", tokens)
    # No second radius token was introduced for it.
    assert re.findall(r"--[a-z-]*radius[a-z-]*\s*:", tokens) == ["--radius:"]


def test_versao_switcher_does_not_restate_select_geometry():
    source = _read("templates/admin_catalogo_versao_form.html")
    local = _rule(source, ".versao-switcher .control")
    assert "border-radius" not in local and "border" not in local
    assert '<select id="versao-switcher" class="control"' in source


# ------------------------------------------------------------------ UI-B18


def test_message_card_footer_has_the_design_system_divider():
    source = _read("templates/admin_mensagens.html")
    actions = _rule(source, ".message-actions")
    assert actions["border-top"] == FOOTER_BORDER
    assert actions["padding"] == "11px 16px"
    # Full-bleed through the body's own 12px 16px padding.
    assert actions["margin"] == "4px -16px -12px"
    assert _rule(source, ".message-card-body")["padding"] == "12px 16px"
    assert _rule(source, ".message-card")["overflow"] == "hidden"


def test_message_actions_close_the_card_body():
    source = _read("templates/admin_mensagens.html")
    assert re.search(
        r'<div class="message-actions">.*?</div>\s*</form>\s*</div><!-- /\.message-card-body -->\s*</article>',
        source,
        re.S,
    )


# ------------------------------------------------------------------ UI-B19


def test_add_student_avatar_row_has_no_foto_label():
    source = _read("templates/admin_adicionar_aluno.html")
    assert 'user_message("Foto")' not in source
    row = source.split("<!-- Avatar -->", 1)[1].split('<div id="avatar-wrap">', 1)[0]
    assert "row-label" not in row and "<label" not in row
    # The avatar keeps its accessible name and every control.
    for kept in (
        "user_message('Foto do aluno')",
        'id="btn-avatar-adicionar"',
        'id="btn-avatar-editar"',
        'id="btn-avatar-remover"',
    ):
        assert kept in source, kept


def test_foto_catalog_key_retired_through_the_ledger():
    from utils.messages import message_key_for_default

    key = message_key_for_default("Foto")
    assert governance.UIB19_PHOTO_LABEL_RETIRED_KEYS == {key}
    assert governance.UIB19_PHOTO_LABEL_KEYS == frozenset()
    catalog = governance.canonical_message_catalog()
    assert key not in catalog
    assert governance.CATALOG_LEDGER[-1][1] == -1
    governance.assert_catalog_matches_canonical_baseline(catalog, context="UI-B19")
