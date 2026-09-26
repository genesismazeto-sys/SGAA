"""Three reported UI regressions, one lane each.

A. **Ver versão** navigated with a generic ``← Voltar`` centred under the form,
   instead of the contextual page-level Back action the activity-detail page
   already uses. The destination is the version's parent activity, so the label
   must be that activity's name, resolved from the page's own data.

B. **Reportes** rendered ``Ações`` stranded in the middle of the toolbar. The
   toolbar is ``justify-content:space-between``; every other SGAA toolbar gives
   it exactly two children (``.filters``, ``.actions``). Commit a8382dd added
   ``Novo reporte`` AFTER ``</div>`` of ``.actions``, making a third child --
   and space-between centres the middle one.

C. **Banco de dados** stretched the two provider cards to a common height and
   then let the shorter one (OneDrive, one configuration field fewer) share the
   surplus between all of its sections, so its content drifted down relative to
   Google Drive's.
"""

from __future__ import annotations

import os
import re
import sys
import uuid
from html.parser import HTMLParser
from pathlib import Path

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main  # noqa: E402
from tests.session_support import stamp_auth_version  # noqa: E402

ROOT = Path(BASE)
VERSION_FORM = ROOT / "templates" / "admin_catalogo_versao_form.html"
VERSION_DETAIL = ROOT / "templates" / "admin_catalogo_versao_detalhe.html"
HEADER_MACRO = ROOT / "templates" / "components" / "detail_header.html"
HEADER_CSS = ROOT / "static" / "css" / "components" / "detail-header.css"
REPORTES = ROOT / "templates" / "admin_reportes.html"
BANCO = ROOT / "templates" / "admin_banco_dados.html"

# Toolbars that were never reported and therefore define the accepted shape.
REFERENCE_TOOLBARS = ("admin_alertas", "admin_alunos", "admin_atividades")


@pytest.fixture()
def client():
    with main.app.app_context():
        main.init_db()
        yield main.app.test_client()


def _login_admin(test_client):
    with test_client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["user_type"] = "admin"
        sess["user_name"] = "Administrador"
        sess["access_level"] = "admin_total"
        stamp_auth_version(sess)


# ==========================================================================
# A. Ver versão -- contextual Back action in the header
# ==========================================================================


def _seed_version(test_client) -> dict:
    """One atividade_base with one immutable (read-only) version."""
    token = uuid.uuid4().hex[:8]
    nome = f"Conferências {token}"
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "INSERT INTO atividade_base (nome_conceito, descricao, status) VALUES (?,?,?)",
            (nome, "Descrição", "ativo"),
        )
        base_id = conn.execute(
            "SELECT id FROM atividade_base WHERE nome_conceito=?", (nome,)
        ).fetchone()["id"]
        cursor = conn.execute(
            "INSERT INTO atividade_versao (atividade_base_id, eixo, grupo, status, "
            "ch_por_evento, numero_versao) VALUES (?,?,?,?,?,?)",
            (base_id, "AAC", "1 - Grupo", "ativa", None, 1),
        )
        versao_id = cursor.lastrowid
        conn.commit()
    return {"base_id": base_id, "versao_id": versao_id, "nome": nome}


@pytest.fixture()
def version_page(client):
    _login_admin(client)
    seed = _seed_version(client)
    response = client.get(
        f"/admin/catalogo-versoes/{seed['base_id']}/versoes/{seed['versao_id']}/editar"
    )
    assert response.status_code == 200, response.status_code
    seed["html"] = response.get_data(as_text=True)
    return seed


def test_the_centred_footer_back_button_is_gone(version_page):
    """The rejected control: a generic 'Voltar' isolated below the form."""
    html = version_page["html"]
    assert ">Voltar</span>" not in html, "the generic footer Voltar is still rendered"
    assert not re.search(
        r'<div class="form-actions center">\s*<a class="btn"[^>]*>\s*'
        r'<i class="lucide" data-lucide="arrow-left">',
        html,
    ), "a centred footer back action survives"

    # As markup and as a selector -- not as the word in a comment.
    template = VERSION_FORM.read_text(encoding="utf-8")
    assert 'class="version-form-heading"' not in template, (
        "the page-local heading copy of .detail-header is back in the markup"
    )
    assert not re.search(r"^\s*\.version-form-heading[\s{,]", template, re.M), (
        "a rule for the retired local heading was added back"
    )
    assert 'class="version-form-heading"' not in html


def test_back_action_reuses_the_activity_detail_header_pattern(version_page):
    """Same component, same classes, same icon, same side -- not a new style."""
    html = version_page["html"]
    header = re.search(r'<header class="detail-header">(.*?)</header>', html, re.S)
    assert header, "the version page does not render the shared detail header"
    body = header.group(1)

    back = re.search(r'<a class="btn detail-header__back"[^>]*>.*?</a>', body, re.S)
    assert back, "no shared back action in the header"
    assert 'data-lucide="arrow-left"' in back.group(0)
    # Title first, back action second: the component's own ordering contract.
    assert body.index("detail-header__title") < body.index("detail-header__back")

    # Byte-for-byte the same anatomy the reference page emits.
    macro = HEADER_MACRO.read_text(encoding="utf-8")
    assert 'class="btn detail-header__back"' in macro
    reference = VERSION_DETAIL.read_text(encoding="utf-8")
    assert "from 'components/detail_header.html' import detail_header" in reference
    assert (
        "from 'components/detail_header.html' import detail_header"
        in VERSION_FORM.read_text(encoding="utf-8")
    ), "the version form hand-rolls the header instead of importing the macro"


def test_back_label_is_the_real_parent_activity_and_targets_its_page(version_page):
    """The label is resolved data, never a hardcoded word."""
    html = version_page["html"]
    back = re.search(r'<a class="btn detail-header__back"(.*?)</a>', html, re.S).group(1)

    assert version_page["nome"] in back, (
        f"the back action does not name the parent activity: {back!r}"
    )
    assert ">Voltar<" not in back
    # The destination is the parent activity's version-list page -- the same
    # page the version detail is reached from.
    expected = f'href="/admin/catalogo-versoes/{version_page["base_id"]}"'
    assert expected in back, back
    with main.app.test_request_context():
        from flask import url_for

        assert url_for(
            "admin_catalogo_versao_detalhe", base_id=version_page["base_id"]
        ) in back

    template = VERSION_FORM.read_text(encoding="utf-8")
    assert "base.nome_conceito" in template, "the label is not resolved from data"
    assert "Conferências" not in template, "the label was hardcoded"


def test_there_is_exactly_one_back_action_on_the_page(version_page):
    html = version_page["html"]
    assert html.count("detail-header__back") == 1
    assert html.count('data-lucide="arrow-left"') == 1


def test_the_title_row_slot_keeps_the_status_pill_beside_the_title(version_page):
    """The repair must not drop the status pill that lived in the old heading."""
    html = version_page["html"]
    row = re.search(
        r'<div class="detail-header__title-row">(.*?)</div>', html, re.S
    )
    assert row, "the shared header has no title row"
    assert "main-title detail-header__title" in row.group(1)
    assert "status-pill" in row.group(1), "the status pill left the title row"

    css = HEADER_CSS.read_text(encoding="utf-8")
    rule = re.search(r"\.detail-header__title-row\{(.*?)\}", css, re.S)
    assert rule, ".detail-header__title-row must be owned by the component"
    assert "display:flex" in rule.group(1)
    assert "flex-wrap:wrap" in rule.group(1), (
        "the title row must wrap rather than push the back action out of its column"
    )


def test_editable_mode_keeps_its_form_actions(version_page, client):
    """Only the read-only footer lost a control; Salvar/Cancelar are untouched."""
    template = VERSION_FORM.read_text(encoding="utf-8")
    assert 'id="btn-salvar-versao"' in template
    assert ">Cancelar</a>" in template
    assert '{% if not readonly %}' in template


# ==========================================================================
# B. Reportes toolbar -- Ações back in its group
# ==========================================================================


VOID = frozenset({"input", "img", "br", "hr", "meta", "link", "source", "i"})


class _ToolbarParser(HTMLParser):
    """Direct children of the first .toolbar, and of its .actions group.

    Depth is the nesting level *inside* the toolbar: the toolbar's own direct
    children are seen at depth 0 and only then does the counter advance.
    """

    def __init__(self):
        super().__init__()
        self.children = []
        self.action_children = []
        self._depth = None          # None until the toolbar opens
        self._actions_depth = None  # depth at which .actions was found

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs, opens=False)

    def handle_starttag(self, tag, attrs, opens=True):
        attributes = {k: (v or "") for k, v in attrs}
        classes = set((attributes.get("class") or "").split())

        if self._depth is None:
            if "toolbar" in classes:
                self._depth = 0
            return

        entry = (tag, attributes.get("class", ""), attributes.get("id", ""))
        if self._depth == 0:
            self.children.append(entry)
        if self._actions_depth is not None and self._depth == self._actions_depth + 1:
            self.action_children.append(entry)
        if self._depth == 0 and "actions" in classes and self._actions_depth is None:
            self._actions_depth = 0

        if opens and tag not in VOID:
            self._depth += 1

    def handle_endtag(self, tag):
        if self._depth is None or tag in VOID:
            return
        self._depth -= 1
        if self._depth < 0:  # the toolbar itself closed
            self._depth = None


def _toolbar(html: str) -> _ToolbarParser:
    parser = _ToolbarParser()
    parser.feed(html)
    return parser


@pytest.fixture()
def reportes_html(client):
    _login_admin(client)
    response = client.get("/admin/reportes")
    assert response.status_code == 200, response.status_code
    return response.get_data(as_text=True)


def test_toolbar_has_the_two_children_space_between_expects(reportes_html):
    """Three children + space-between is exactly what centred 'Ações'."""
    children = [(tag, cls) for tag, cls, _id in _toolbar(reportes_html).children]
    classes = [cls for _tag, cls in children]
    assert classes == ["filters", "actions"], (
        "the Reportes toolbar still has a stray third child, which "
        f"justify-content:space-between renders in the middle: {children}"
    )


def test_novo_reporte_is_grouped_with_acoes(reportes_html):
    parser = _toolbar(reportes_html)
    ids = [_id for _tag, _cls, _id in parser.action_children]
    classes = [cls for _tag, cls, _id in parser.action_children]

    assert "toolbar-actions-shell" in classes, "the Ações shell left .actions"
    assert "btn-novo-reporte" in ids, (
        "Novo reporte is not inside .actions, so Ações is left alone in the "
        f"middle of the toolbar: {parser.action_children}"
    )
    # Order is part of the accepted pattern: menu first, primary action last.
    assert classes.index("toolbar-actions-shell") < ids.index("btn-novo-reporte")


def test_the_grouping_matches_every_unreported_toolbar():
    """The authoritative shape, read off the pages nobody complained about."""
    for name in REFERENCE_TOOLBARS:
        html = (ROOT / "templates" / f"{name}.html").read_text(encoding="utf-8")
        parser = _toolbar(html)
        classes = [cls for _tag, cls, _id in parser.children]
        assert classes == ["filters", "actions"], (name, classes)
        assert any(
            "toolbar-actions-shell" in cls or "btn" in cls
            for _tag, cls, _id in parser.action_children
        ), name


def test_the_repair_uses_normal_flex_grouping_only():
    """No absolute positioning, spacers, offsets or magic pixels."""
    template = REPORTES.read_text(encoding="utf-8")
    style = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", template, re.S | re.I))
    toolbar_rules = [
        line.strip()
        for line in style.splitlines()
        if "toolbar" in line and ("{" in line)
    ]
    for rule in toolbar_rules:
        assert "position:absolute" not in rule.replace(" ", ""), rule
        assert "margin-left:auto" not in rule.replace(" ", ""), rule
        assert "%" not in rule.split("{", 1)[1], rule
    assert "toolbar-spacer" not in template
    assert 'class="spacer"' not in template


def test_toolbar_stays_grouped_at_narrower_widths():
    """B3: the wrap contract is container-relative and covers .actions itself.

    With Novo reporte inside .actions, a narrow track wraps the group as a
    unit; as a third toolbar child it could take its own row and leave Ações
    centred again.
    """
    css = (ROOT / "static/css/modern-style.css").read_text(encoding="utf-8")
    wrap = re.search(
        r"\.app-main \.toolbar,\s*\.app-main \.toolbar \.filters,\s*"
        r"\.app-main \.toolbar \.actions\{(.*?)\}",
        css,
        re.S,
    )
    assert wrap, "the shared toolbar wrap contract disappeared"
    assert "flex-wrap:wrap" in wrap.group(1)
    assert "row-gap" in wrap.group(1)
    # No page-local breakpoint may re-split the group on this page.
    template = REPORTES.read_text(encoding="utf-8")
    style = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", template, re.S | re.I))
    assert not re.search(r"@media[^{]*\{[^}]*\.toolbar\b", style), (
        "Reportes adds a local toolbar breakpoint instead of using the shared wrap"
    )


# ==========================================================================
# C. Provider cards -- surplus height only before the footer
# ==========================================================================


@pytest.fixture(scope="module")
def banco_css() -> str:
    template = BANCO.read_text(encoding="utf-8")
    return "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", template, re.S | re.I))


def _rule(css: str, selector: str) -> str:
    match = re.search(re.escape(selector) + r"\{(.*?)\}", css, re.S)
    assert match, f"missing rule: {selector}"
    return match.group(1)


def test_the_card_no_longer_distributes_surplus_between_its_sections(banco_css):
    """The cause: an auto-row grid stretched by the outer 2-column grid."""
    card = _rule(banco_css, ".db-provider-card")
    assert "display:flex" in card, (
        "the card is a grid again; its auto-sized rows share the stretched "
        "height equally and every OneDrive section drifts down"
    )
    assert "flex-direction:column" in card
    # A flex column does not stretch children along the main axis, so nothing
    # in the body can absorb height by accident.
    assert "justify-content" not in card, (
        "justify-content on the card would redistribute the surplus again"
    )


def test_the_surplus_lands_immediately_before_the_footer(banco_css):
    config = _rule(banco_css, ".db-provider-config")
    assert "flex:1 1 auto" in config.replace(" ", " "), (
        "the configuration block must be the one block that absorbs the card's "
        f"spare height: {config}"
    )
    assert "display:flex" in config and "flex-direction:column" in config

    footer = _rule(banco_css, ".db-provider-config-footer")
    assert "margin-top:auto" in footer, (
        "the footer/divider is not pinned to the bottom, so the blank space "
        "would sit below it instead of above it"
    )
    assert "border-top" in footer, "the divider moved out of the footer"


def test_no_spacer_hack_and_no_provider_specific_geometry(banco_css):
    """Proof the fix is structural, not padded."""
    template = BANCO.read_text(encoding="utf-8")
    for forbidden in ("db-spacer", "db-provider-spacer", 'class="spacer"'):
        assert forbidden not in template, forbidden

    # No provider-scoped layout override may exist for either card.
    offenders = [
        line.strip()
        for line in banco_css.splitlines()
        if re.search(r"(onedrive|gdrive|google)", line, re.I)
        and re.search(r"(margin|height|padding|top)\s*:", line)
    ]
    assert not offenders, f"provider-specific geometry was added: {offenders}"

    card = _rule(banco_css, ".db-provider-card")
    assert "min-height" not in card and "height:" not in card, (
        "the cards must not be given a fixed height"
    )


def test_both_cards_expose_the_same_section_order(client):
    """Alignment is only meaningful if the two cards have the same rhythm."""
    _login_admin(client)
    response = client.get("/admin/banco-dados")
    assert response.status_code == 200, response.status_code
    html = response.get_data(as_text=True)

    cards = re.findall(
        r'<section class="db-provider-card">(.*?)</section>', html, re.S
    )
    if len(cards) < 2:
        pytest.skip("OneDrive card is not enabled in this configuration")

    order = [
        [
            name
            for name in re.findall(
                r'class="(db-provider-head|db-provider-meta|db-provider-actions'
                r'|db-provider-config|db-provider-config-footer)[" ]',
                card,
            )
        ]
        for card in cards[:2]
    ]
    assert order[0] == order[1], f"the two cards differ structurally: {order}"
    # And APP_PUBLIC_BASE_URL is the first configuration field on both, which is
    # what makes "it must align" a well-formed requirement.
    for card in cards[:2]:
        config = card.split('class="db-provider-config"', 1)[1]
        first_field = re.search(r'<label for="([^"]+)"', config)
        assert first_field and first_field.group(1).endswith("app_public_base_url"), (
            f"APP_PUBLIC_BASE_URL is not the first configuration field: "
            f"{first_field.group(1) if first_field else None}"
        )
