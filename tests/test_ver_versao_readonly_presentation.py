"""Ver versão: a read-only *region* resolves to the shared read-only paint.

UI-B10. The defect, stated precisely: ``admin_catalogo_versao_form.html`` and
``admin_editar_atividade.html`` do not disable their controls one at a time.
They wrap the whole form in the element HTML provides for a view mode::

    <fieldset class="form-fieldset" disabled aria-readonly="true">

``disabled`` on a ``<fieldset>`` is *inherited*: every descendant control
matches ``:disabled`` without carrying the attribute — and therefore without
carrying any marker of its own. The read-only contract landed by UI-H03 keys on
the control (``.field-card .control:disabled[aria-readonly="true"]``), so it
matched nothing at all on these two pages and the whole form fell through to the
"not applicable" disabled paint: ``--field-disabled-bg``, a dead
``--field-disabled-border``, no card shadow, a ``--border-strong`` chip and
``--text-tertiary`` glyphs — while the *same semantic state* on Ver Aluno and
Ver Requisição resolved to ``--field-readonly-bg`` / ``--text-secondary``.

The repair teaches the shared contract the fieldset-level declaration, and is
scoped to the pairing rather than to ``fieldset[disabled]`` alone: a disabled
fieldset with no ``aria-readonly`` still means "not applicable" and still looks
it, exactly like a disabled control with no marker.

Semantics are untouched — the fieldset stays disabled, its controls stay
unfocusable and stay out of the submission. Only the paint moves.
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

import main
from tests.session_support import stamp_auth_version

ROOT = Path(__file__).resolve().parents[1]
FORM_CSS = ROOT / "static" / "css" / "components" / "form.css"
VERSAO_TEMPLATE = ROOT / "templates" / "admin_catalogo_versao_form.html"
ATIVIDADE_TEMPLATE = ROOT / "templates" / "admin_editar_atividade.html"

READONLY_BG = "background:var(--field-readonly-bg)"

# ---------------------------------------------------------------------------
# The selectors this file reasons about, pinned verbatim. The resolution model
# further down is only trustworthy while these are the rules that ship, so every
# one of them is asserted present before any card is resolved.
# ---------------------------------------------------------------------------

# The region marker. Deliberately the PAIRING, never fieldset[disabled] alone.
REGION = 'fieldset[disabled][aria-readonly="true"]'

# New in UI-B10 — the fieldset-level read-only declaration.
REGION_CARD = (
    f"{REGION} .field-card:has(.control:disabled)"
    ":not(:has(.control:not([readonly]):not(:disabled)))"
)
REGION_CONTROL = f"{REGION} .field-card .control:disabled"

# The guard added to the "not applicable" rules so they yield inside a region.
# :where() is load-bearing: it contributes NO specificity, so the two disabled
# rules keep the exact weight they had and only their reach changes.
REGION_EXCLUSION = f':not(:where({REGION} *))'

# UI-H03, must survive byte-identical: Ver Requisição and Ver Aluno resolve
# through these and nothing in UI-B10 may move them.
READONLY_CARD_NATIVE = (
    ".field-card:has(.control[readonly])"
    ":not(:has(.control:not([readonly]):not(:disabled)))"
)
READONLY_CARD_DECLARED = (
    '.field-card:has(.control:disabled[aria-readonly="true"])'
    ":not(:has(.control:not([readonly]):not(:disabled)))"
)
CONTROL_DECLARED = '.field-card .control:disabled[aria-readonly="true"]'

VOID_TAGS = frozenset(
    {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }
)
CONTROL_TAGS = frozenset({"input", "select", "textarea"})


@pytest.fixture(scope="module")
def css() -> str:
    return FORM_CSS.read_text(encoding="utf-8")


def _rules_only(css: str) -> str:
    """The stylesheet with every /* comment */ removed.

    This file makes assertions of the form "no rule anywhere does X". Prose in
    the block comments -- which quote the very selectors being discussed -- is
    not a rule and must not be read as one.
    """
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _region_block(css: str) -> str:
    """Exactly the two rules UI-B10 adds, banner included, nothing after."""
    start = css.rindex("READ-ONLY REGION")
    end = css.index("}", css.index(REGION_CONTROL, start)) + 1
    return css[start:end]


# ---------------------------------------------------------------------------
# 1. The shared contract
# ---------------------------------------------------------------------------


def test_a_read_only_region_resolves_to_the_shared_read_only_tokens(css):
    """One token family, reached from the fieldset as well as the control."""
    assert REGION_CARD in css, "the read-only region card rule is missing"
    body = css.split(REGION_CARD, 1)[1].split("{", 1)[1].split("}", 1)[0]
    assert READONLY_BG in body, (
        "the region paints something other than the shared read-only bg"
    )

    assert REGION_CONTROL in css, "the read-only region control rule is missing"
    body = css.split(REGION_CONTROL + "{", 1)[1].split("}", 1)[0]
    # The same two declarations the accepted surfaces already resolve to --
    # not a second grey, and not a page-local one.
    assert "color:var(--text-secondary)" in body
    assert "-webkit-text-fill-color:var(--text-secondary)" in body
    assert "cursor:default" in body


def test_the_region_restates_nothing_the_base_card_already_owns(css):
    """Border, shadow and chip must FALL BACK, not be re-declared.

    Restating --border-strong / --shadow-sm here would be a second copy of the
    .field-card primitive that can drift from it silently. The exclusion on the
    disabled rules is what makes the fallback possible.
    """
    body = css.split(REGION_CARD, 1)[1].split("{", 1)[1].split("}", 1)[0]
    for property_name in ("border", "box-shadow", "color"):
        assert property_name not in body, (
            f"the region rule re-declares {property_name!r}; it should inherit "
            "the untouched .field-card primitive instead"
        )


def test_the_not_applicable_paint_yields_inside_a_read_only_region(css):
    """Both disabled card rules must carry the region guard."""
    disabled_rules = [
        line
        for line in css.splitlines()
        if line.startswith(".field-card:not(:where(fieldset")
        or line.startswith(".field-card:has(.control:disabled)")
    ]
    assert len(disabled_rules) == 2, disabled_rules
    for rule in disabled_rules:
        assert REGION_EXCLUSION in rule, (
            "the 'not applicable' paint still reaches a control inside a "
            f"declared read-only region: {rule}"
        )


def test_the_region_guard_carries_no_specificity(css):
    """:where() keeps Ver Aluno / Ver Requisição arithmetically untouched.

    If the guard were a bare :not(fieldset[...] *) it would add (0,2,1) to both
    disabled rules. Nothing on those two surfaces competes today, but the whole
    point of UI-B10 is that one semantic state has one resolution, so the repair
    must not silently reweight a rule the accepted surfaces depend on.
    """
    for rule in css.splitlines():
        if REGION_EXCLUSION not in rule:
            continue
        assert f":not(:where({REGION} *))" in rule, (
            f"the region guard is not :where()-wrapped: {rule}"
        )


def test_a_plain_disabled_fieldset_still_means_not_applicable(css):
    """The extension is opt-in on the PAIRING, exactly like the control one."""
    for selector in (REGION_CARD, REGION_CONTROL, REGION_EXCLUSION):
        assert 'fieldset[disabled][aria-readonly="true"]' in selector
    # No rule anywhere may key on the bare disabled fieldset.
    bare = [
        line
        for line in _rules_only(css).splitlines()
        if "fieldset[disabled]" in line
        and 'fieldset[disabled][aria-readonly="true"]' not in line
    ]
    assert not bare, f"a rule keys on a bare disabled fieldset: {bare}"

    # ...and a disabled control outside a region is unchanged.
    assert ".field-card .control:disabled{" in css
    body = css.split(".field-card .control:disabled{", 1)[1].split("}", 1)[0]
    assert "color:var(--text-tertiary)" in body
    assert "cursor:not-allowed" in body


def test_ui_h03_resolution_is_byte_identical(css):
    """Ver Aluno / Ver Requisição must not regress: same selectors, same paint."""
    for selector in (READONLY_CARD_NATIVE, READONLY_CARD_DECLARED):
        assert selector in css, f"UI-H03 selector disappeared: {selector}"
        body = css.split(selector, 1)[1].split("{", 1)[1].split("}", 1)[0]
        assert READONLY_BG in body

    assert CONTROL_DECLARED + "{" in css
    body = css.split(CONTROL_DECLARED + "{", 1)[1].split("}", 1)[0]
    assert "color:var(--text-secondary)" in body
    assert "-webkit-text-fill-color:var(--text-secondary)" in body

    # The native read-only control rule, untouched.
    assert ".field-card .control[readonly]{" in css
    body = css.split(".field-card .control[readonly]{", 1)[1].split("}", 1)[0]
    assert "color:var(--text-secondary)" in body


def test_no_raw_colour_and_no_opacity_hack_was_added(css):
    """The repair may only reuse existing tokens."""
    assert "READ-ONLY REGION" in css, "the READ-ONLY REGION block is missing"
    added = _region_block(css)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", added), "a raw colour was added"
    assert not re.search(r"\b(rgb|rgba|hsl|hsla)\(", added), "a raw colour was added"
    assert "opacity" not in added, "an opacity hack was added"

    # Every colour-ish declaration in the new block must be a var().
    for declaration in re.findall(r"[\w-]+:[^;{}]+;", added):
        name, value = declaration.split(":", 1)
        if re.search(r"color|background|border", name):
            assert "var(--" in value, f"untokenized declaration: {declaration.strip()}"


@pytest.mark.parametrize("template", [VERSAO_TEMPLATE, ATIVIDADE_TEMPLATE])
def test_the_page_does_not_restate_the_read_only_contract(template):
    """No page-local gray, no 'version readonly' colour, no local override."""
    page = template.read_text(encoding="utf-8")
    style_blocks = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", page, re.S | re.I))
    offenders = [
        line.strip()
        for line in style_blocks.splitlines()
        if re.search(r"(readonly|:disabled|\[disabled\])", line)
        and re.search(r"(color|background|border)", line)
    ]
    assert not offenders, f"the page paints the read-only state itself: {offenders}"


# ---------------------------------------------------------------------------
# 2. Compound halves
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("template", [VERSAO_TEMPLATE, ATIVIDADE_TEMPLATE])
def test_the_off_chunk_dimming_does_not_split_a_compound_card_in_a_view(template):
    """`.is-off-chunk` is an EDITING affordance; in a view it only splits a card.

    The JS marks the waiting half of a compound control (the hours input while
    Limitação is "Nenhuma", the Grupo pair for Extensão) with opacity .55. In
    read-only mode nothing is waiting, so that left one half of the card lighter
    than the other -- the same one-state-two-treatments defect, expressed with
    opacity instead of a token. The dimming is cancelled inside the region; the
    value itself ("Nenhuma" / "Sem sugestão" / "NA") still carries the meaning.
    """
    page = template.read_text(encoding="utf-8")
    assert ".is-off-chunk{ opacity:.55; pointer-events:none; }" in page, (
        "the off-chunk affordance moved; re-check the cancellation below"
    )
    assert (
        '.form-fieldset[disabled][aria-readonly="true"] .is-off-chunk{ opacity:1; }'
        in page
    ), "a compound card in the read-only view still has a dimmed half"

    # pointer-events:none is deliberately NOT cancelled -- only paint moves.
    cancel = page.split(
        '.form-fieldset[disabled][aria-readonly="true"] .is-off-chunk{', 1
    )[1].split("}", 1)[0]
    assert "pointer-events" not in cancel


# ---------------------------------------------------------------------------
# 3. Rendered proof
# ---------------------------------------------------------------------------


class _Card:
    def __init__(self, label: str | None):
        self.label = label
        self.controls: list[tuple[str, dict]] = []


class _FormParser(HTMLParser):
    """Collect each .field-card inside the form and the controls it holds.

    Also records whether the enclosing <fieldset> declares a read-only region,
    which is the whole point: the marker is on an ancestor, not on the control.
    """

    def __init__(self):
        super().__init__()
        self.cards: list[_Card] = []
        self.region = False
        self.fieldset_attrs: dict | None = None
        self._label: str | None = None
        self._in_label = False
        self._text: list[str] = []
        self._card: _Card | None = None
        self._depth = 0

    def handle_data(self, data):
        if self._in_label:
            self._text.append(data)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs, opens=False)

    def handle_starttag(self, tag, attrs, opens=True):
        attributes = {k: (v if v is not None else "") for k, v in attrs}
        classes = set((attributes.get("class") or "").split())

        if tag == "fieldset":
            self.fieldset_attrs = attributes
            self.region = (
                "disabled" in attributes
                and attributes.get("aria-readonly") == "true"
            )
            return

        if tag == "label" and "row-label" in classes:
            self._in_label = True
            self._text = []
            return

        if self._card is None:
            if "field-card" in classes:
                self._card = _Card(self._label)
                self._depth = 0
            return

        if tag in CONTROL_TAGS and "control" in classes:
            self._card.controls.append((tag, attributes))
        if opens and tag not in VOID_TAGS:
            self._depth += 1

    def handle_endtag(self, tag):
        if tag == "label" and self._in_label:
            self._in_label = False
            self._label = "".join(self._text).strip()
            return
        if self._card is None:
            return
        if self._depth == 0:
            self.cards.append(self._card)
            self._card = None
        else:
            self._depth -= 1


def _parse(html: str) -> _FormParser:
    start = html.index('<form action=')
    parser = _FormParser()
    parser.feed(html[start : html.index("</form>", start)])
    return parser


def _visible(card: _Card) -> list[dict]:
    return [a for _tag, a in card.controls if a.get("type") != "hidden"]


def _actually_disabled(attributes: dict, region: bool) -> bool:
    """:disabled is the *actually disabled* state, which a fieldset inherits."""
    return region or "disabled" in attributes


class _Shipped:
    """Which of the rules modelled below are actually in the stylesheet.

    Read from disk rather than assumed, so that reverting the repair fails the
    RENDERED tests too. Without this the resolution model would keep reporting
    "read-only" for a page whose stylesheet no longer contains the rule that
    makes it so.
    """

    def __init__(self, css: str):
        self.region_card = REGION_CARD in css
        self.region_control = REGION_CONTROL + "{" in css
        rules = _rules_only(css)
        self.disabled_yields = all(
            REGION_EXCLUSION in line
            for line in rules.splitlines()
            if line.startswith(".field-card") and ":has(.control:disabled)" in line
            and "--field-disabled" in rules.split(line, 1)[1].split("}", 1)[0]
        )


SHIPPED = _Shipped(FORM_CSS.read_text(encoding="utf-8"))


def _card_paint(card: _Card, region: bool) -> str | None:
    """How the whole card resolves, by the specificities pinned above.

        REGION_CARD              (0,8,1)  bg                        <- new
        READONLY_CARD_DECLARED   (0,8,0)  bg
        DISABLED_CARD            (0,8,0)  bg + border + box-shadow + chip
        READONLY_CARD_NATIVE     (0,6,0)  bg

    Returns ``"split"`` when the read-only background wins but the disabled
    rule still matches, because that rule also owns the border, the shadow and
    the chip: the card would come out half read-only and half not-applicable.
    That is the state "Versão anterior" was actually in before this repair, and
    the reason the fix is an exclusion rather than a higher-specificity
    override.
    """
    controls = _visible(card)
    if not controls:
        return None

    disabled = [_actually_disabled(a, region) for a in controls]
    declared = [
        d and a.get("aria-readonly") == "true" for a, d in zip(controls, disabled)
    ]
    # :not(:has(.control:not([readonly]):not(:disabled)))
    nothing_editable = not any(
        not d and "readonly" not in a for a, d in zip(controls, disabled)
    )
    # :not(:has(.control:not(:disabled)))
    all_disabled = all(disabled)

    disabled_rule = (
        any(disabled)
        and all_disabled
        and not any(declared)
        and not (region and SHIPPED.disabled_yields)
    )

    matched: list[tuple[tuple[int, int, int], str]] = []
    if SHIPPED.region_card and region and any(disabled) and nothing_editable:
        matched.append(((0, 8, 1), "readonly"))
    if any(declared) and nothing_editable:
        matched.append(((0, 8, 0), "readonly"))
    if disabled_rule:
        matched.append(((0, 8, 0), "disabled"))
    if any("readonly" in a for a in controls) and nothing_editable:
        matched.append(((0, 6, 0), "readonly"))

    if not matched:
        return "default"
    background = max(matched)[1]
    if background == "readonly" and disabled_rule:
        return "split"
    return background


def _control_text(attributes: dict, region: bool) -> str:
    """Which token reaches the glyphs.

        REGION_CONTROL           (0,5,1) --text-secondary   <- new
        CONTROL_DECLARED         (0,3,0) --text-secondary
        .control[readonly]       (0,2,0) --text-secondary   (later in file)
        .control:disabled        (0,2,0) --text-tertiary
    """
    disabled = _actually_disabled(attributes, region)
    matched: list[tuple[tuple[int, int, int], int, str]] = []
    if SHIPPED.region_control and region and disabled:
        matched.append(((0, 5, 1), 4, "secondary"))
    if disabled and attributes.get("aria-readonly") == "true":
        matched.append(((0, 3, 0), 3, "secondary"))
    if "readonly" in attributes:
        matched.append(((0, 2, 0), 2, "secondary"))
    if disabled:
        matched.append(((0, 2, 0), 1, "tertiary"))
    if not matched:
        return "primary"
    return max(matched)[2]


@pytest.fixture()
def client():
    app = main.app
    with app.app_context():
        main.init_db()
        yield app.test_client()


def _login_admin(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["user_type"] = "admin"
        sess["user_name"] = "Administrador"
        stamp_auth_version(sess)


def _seed_versao(status: str = "rascunho") -> tuple[int, int]:
    token = uuid.uuid4().hex[:8]
    with main.app.app_context():
        conn = main.get_db_connection()
        nome = f"Base UI-B10 {token}"
        conn.execute(
            "INSERT INTO atividade_base (nome_conceito, descricao, status)"
            " VALUES (?, ?, ?)",
            (nome, "Descrição UI-B10", "ativo"),
        )
        base_id = conn.execute(
            "SELECT id FROM atividade_base WHERE nome_conceito = ?", (nome,)
        ).fetchone()["id"]
        cur = conn.execute(
            """
            INSERT INTO atividade_versao (
                atividade_base_id, eixo, grupo, status,
                ch_por_evento, numero_versao
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (base_id, "AAC", "3 - Monitoria", status, None, 1),
        )
        versao_id = cur.lastrowid
        conn.commit()
    return base_id, versao_id


def _editar_url(base_id: int, versao_id: int) -> str:
    return f"/admin/catalogo-versoes/{base_id}/versoes/{versao_id}/editar"


@pytest.fixture()
def ver_versao(client) -> _FormParser:
    _login_admin(client)
    base_id, versao_id = _seed_versao()
    response = client.get(_editar_url(base_id, versao_id) + "?view=1")
    assert response.status_code == 200, response.status_code
    return _parse(response.get_data(as_text=True))


# The eight fields the user named. Matched on the rendered .row-label so a
# renamed or dropped row fails here rather than silently reducing coverage.
VER_VERSAO_FIELDS = (
    "Tipo",
    "Grupo (nº/descrição)",
    "Nome",
    "Descrição",
    "Limitação / Tempo limite",
    "Carga horária por evento",
    "Observações",
    "Versão anterior",
)


def test_ver_versao_declares_the_region_on_the_fieldset(ver_versao):
    """The marker is on the ancestor -- no control carries one of its own."""
    assert ver_versao.region, "Ver versão no longer declares a read-only region"
    for card in ver_versao.cards:
        for _tag, attributes in card.controls:
            assert "aria-readonly" not in attributes, (
                "a control now carries the marker itself; this test proves the "
                "FIELDSET-level resolution and would stop doing so"
            )


def test_ver_versao_renders_every_field_the_user_named(ver_versao):
    labels = [card.label for card in ver_versao.cards]
    assert labels == list(VER_VERSAO_FIELDS), labels


def test_every_ver_versao_field_resolves_to_the_read_only_paint(ver_versao):
    """The defect: all eight resolved to the 'not applicable' paint instead."""
    resolved = {
        card.label: _card_paint(card, ver_versao.region) for card in ver_versao.cards
    }
    assert resolved == {label: "readonly" for label in VER_VERSAO_FIELDS}, resolved


def test_every_ver_versao_control_resolves_to_the_read_only_text_token(ver_versao):
    for card in ver_versao.cards:
        for attributes in _visible(card):
            assert _control_text(attributes, ver_versao.region) == "secondary", (
                f"{card.label}: a control still paints --text-tertiary"
            )


def test_no_compound_card_has_one_treatment_per_half(ver_versao):
    """Grupo, Limitação and Carga horária each hold two sub-controls."""
    compound = [card for card in ver_versao.cards if len(_visible(card)) > 1]
    assert {card.label for card in compound} == {
        "Grupo (nº/descrição)",
        "Limitação / Tempo limite",
        "Carga horária por evento",
    }, [card.label for card in compound]

    for card in compound:
        tokens = {
            _control_text(attributes, ver_versao.region)
            for attributes in _visible(card)
        }
        assert tokens == {"secondary"}, f"{card.label} paints two text tokens: {tokens}"


def test_versao_anterior_is_read_only_on_both_of_its_attributes(ver_versao):
    """It is the one control that is `readonly` AND inherits `disabled`.

    Before the repair its card collected the disabled background while its text
    collected the read-only token -- a single field split across both paints.
    """
    card = next(c for c in ver_versao.cards if c.label == "Versão anterior")
    attributes = _visible(card)[0]
    assert "readonly" in attributes
    assert _actually_disabled(attributes, ver_versao.region)
    assert _card_paint(card, ver_versao.region) == "readonly"
    assert _control_text(attributes, ver_versao.region) == "secondary"


def test_a_truly_disabled_control_outside_a_region_stays_disabled(client):
    """Editable mode: `tipo_locked` is genuinely not-applicable and looks it.

    This is the regression that matters for §6 -- the shared fix must not
    repaint an inapplicable field as read-only. The very same select, on the
    very same page, resolves differently once the region is gone.
    """
    _login_admin(client)
    base_id, versao_id = _seed_versao(status="rascunho")
    response = client.get(_editar_url(base_id, versao_id))
    assert response.status_code == 200, response.status_code
    parsed = _parse(response.get_data(as_text=True))

    assert not parsed.region, "the editable form must not declare a region"
    tipo = next(card for card in parsed.cards if card.label == "Tipo")
    attributes = _visible(tipo)[0]
    assert "disabled" in attributes, "tipo_locked no longer disables the select"
    assert _card_paint(tipo, parsed.region) == "disabled"
    assert _control_text(attributes, parsed.region) == "tertiary"

    # ...and its editable siblings are untouched.
    nome = next(card for card in parsed.cards if card.label == "Nome")
    assert _card_paint(nome, parsed.region) == "default"
