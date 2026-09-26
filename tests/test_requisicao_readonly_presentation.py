"""Requisição modal: one read-only presentation for every non-editable field.

The reported defect, stated precisely: the Novo/Ver Requisição modal expresses a
single state -- "shown, not editable" -- through two different native
attributes, because only ``<input>`` has ``readonly``. ``setFormEditable`` marks
inputs ``readonly`` and everything else ``disabled``. The design system paints
those two attributes differently *on purpose* (``readonly`` = shown but not
editable, ``disabled`` = not applicable), so half the form came out on
``--field-readonly-bg`` with secondary text and the other half on
``--field-disabled-bg`` with a dead border, a greyed chip and tertiary text.

The repair keeps every native attribute exactly where it was -- a disabled
select stays disabled and stays out of the submission -- and declares the
*intent* with ``aria-readonly="true"``, the marker the accepted read-only
surfaces already use (Ver Aluno, admin_matriz_form). ``components/form.css``
then resolves that pairing to the read-only paint.

Two fields on this surface were not controls at all: Escopo and the empty
Comprovantes state were ``<div class="control">`` carrying a static inline
``style``. They now use the accepted Ver Aluno static-value pattern -- a
read-only input with an ``aria-label`` and no ``name``, so nothing new becomes
submittable.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from tests.canonical_request_test_support import login_admin
from tests.versioned_test_support import isolated_versioned_app_env

ROOT = Path(__file__).resolve().parents[1]
FORM_CSS = ROOT / "static" / "css" / "components" / "form.css"
TEMPLATE = ROOT / "templates" / "admin_requisicoes.html"

READONLY_BG = "background:var(--field-readonly-bg)"

# The two card selectors that must both resolve to the read-only paint: one for
# the native attribute, one for the declared-intent pairing. Pinned verbatim so
# the resolution model further down cannot silently drift from the stylesheet.
READONLY_CARD_NATIVE = (
    ".field-card:has(.control[readonly])"
    ":not(:has(.control:not([readonly]):not(:disabled)))"
)
READONLY_CARD_DECLARED = (
    '.field-card:has(.control:disabled[aria-readonly="true"])'
    ":not(:has(.control:not([readonly]):not(:disabled)))"
)
DISABLED_EXCLUSION = ':not(:has(.control:disabled[aria-readonly="true"]))'

VOID_TAGS = frozenset(
    {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }
)
CONTROL_TAGS = frozenset({"input", "select", "textarea"})


# --------------------------------------------------------------------------
# 1. The shared contract
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def css() -> str:
    return FORM_CSS.read_text(encoding="utf-8")


def test_both_native_states_resolve_to_one_read_only_paint(css):
    """One background token, reached from ``readonly`` and from the pairing."""
    for selector in (READONLY_CARD_NATIVE, READONLY_CARD_DECLARED):
        assert selector in css, f"missing read-only card selector: {selector}"
        body = css.split(selector, 1)[1].split("{", 1)[1].split("}", 1)[0]
        assert READONLY_BG in body, f"{selector} does not paint the read-only bg"

    control = css.split('.field-card .control:disabled[aria-readonly="true"]{', 1)
    assert len(control) == 2, "the declared-read-only control has no text rule"
    body = control[1].split("}", 1)[0]
    # Same token the native read-only control uses -- not a second grey.
    assert "color:var(--text-secondary)" in body
    assert "-webkit-text-fill-color:var(--text-secondary)" in body


def test_the_disabled_paint_yields_to_a_declared_read_only_control(css):
    """Otherwise both card rules match and only the border/shadow leaks.

    UI-B10 added a second, region-level guard in front of ``:has()`` on these
    same two rules, so they are matched on the ``:has(.control:disabled)``
    fragment rather than on the start of the line. The contract asserted here
    -- the control-level exclusion this file's repair depends on -- is
    unchanged, and ``tests/test_ver_versao_readonly_presentation.py`` owns the
    region-level one.
    """
    disabled_rules = [
        line
        for line in css.splitlines()
        if line.startswith(".field-card") and ":has(.control:disabled)" in line
    ]
    assert len(disabled_rules) == 2, disabled_rules
    for rule in disabled_rules:
        assert DISABLED_EXCLUSION in rule, (
            "a disabled-paint rule can still reach a control that declares "
            f"read-only intent: {rule}"
        )


def test_no_new_shade_and_no_local_override_was_introduced(css):
    """The repair may only reuse tokens, and may not be re-stated on the page."""
    added = css.split("DISABLED-BUT-READ-ONLY", 1)[1]
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", added), "a raw colour was added"
    assert "opacity" not in added, "an opacity fix was added"

    page = TEMPLATE.read_text(encoding="utf-8")
    style_blocks = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", page, re.S | re.I))
    offenders = [
        line.strip()
        for line in style_blocks.splitlines()
        if re.search(r"(readonly|:disabled)", line) and "field-card" in line
    ]
    assert not offenders, f"the page re-states the read-only contract: {offenders}"


def test_a_plain_disabled_control_still_means_not_applicable(css):
    """The extension is opt-in; it must not repaint every disabled control."""
    assert ".field-card .control:disabled{" in css
    body = css.split(".field-card .control:disabled{", 1)[1].split("}", 1)[0]
    assert "color:var(--text-tertiary)" in body
    assert "cursor:not-allowed" in body


# --------------------------------------------------------------------------
# 2. The shipped transition
# --------------------------------------------------------------------------


def test_view_mode_declares_read_only_on_everything_it_disables():
    """The native state is unchanged; only the marker is added."""
    page = TEMPLATE.read_text(encoding="utf-8")
    loop = re.search(
        r"form\.querySelectorAll\('input, select, textarea'\)\.forEach\(el=>\{(.*?)\n        \}\);",
        page,
        re.S,
    )
    assert loop, "the editability loop disappeared"
    body = loop.group(1)

    # Unchanged semantics: the same two attributes, assigned the same way.
    assert "if (el.tagName === 'INPUT' && !isFile) el.readOnly = true;" in body
    assert "if (isFile || el.tagName !== 'INPUT') el.disabled = true;" in body

    # ...plus the declaration of what the disabling means. Asserted on the
    # non-editable branch specifically: the edit branch also marks the locked
    # Aluno select, so a whole-body substring check passes on a reverted file.
    assert _view_mode_declares_readonly(), (
        "the non-editable branch no longer declares aria-readonly, so its "
        "disabled selects/textarea fall back to the 'not applicable' paint "
        "while its readonly inputs keep the read-only one"
    )
    editable_branch = body.split("if (isCreate || isEdit){", 1)[1].split("return;", 1)[0]
    assert "el.removeAttribute('aria-readonly');" in editable_branch, (
        "the marker is never cleared, so an editable form would keep claiming "
        "to be read-only"
    )


def test_controls_re_enabled_for_processing_drop_the_marker():
    """Justificativa/horas become genuinely editable inside a read-only form."""
    page = TEMPLATE.read_text(encoding="utf-8")
    prepare = re.search(r"function preparePanelFor\(act\)\{(.*?)\n    \}", page, re.S)
    assert prepare, "preparePanelFor disappeared"
    body = prepare.group(1)
    for control in ("justSel", "justEl", "horasEl"):
        enabled = re.search(rf"{control}\.disabled = false;", body)
        assert enabled, f"{control} is no longer re-enabled for processing"
        assert f"{control}.removeAttribute('aria-readonly')" in body, (
            f"{control} is editable but still declares read-only"
        )


# --------------------------------------------------------------------------
# 3. Rendered proof
# --------------------------------------------------------------------------


class _Card:
    def __init__(self, label):
        self.label = label
        self.controls = []  # (tag, attrs)


class _FormParser(HTMLParser):
    """Collect every .field-card in the modal form and its form controls."""

    def __init__(self):
        super().__init__()
        self.cards = []
        self._label = None
        self._in_label = False
        self._text = []
        self._card = None
        self._depth = 0

    def handle_data(self, data):
        if self._in_label:
            self._text.append(data)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs, opens=False)

    def handle_starttag(self, tag, attrs, opens=True):
        attributes = {k: (v if v is not None else "") for k, v in attrs}
        classes = set((attributes.get("class") or "").split())

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


def _modal_form(html: str) -> str:
    start = html.index('<form id="req-form"')
    return html[start : html.index("</form>", start)]


@pytest.fixture(scope="module")
def modal_html(tmp_path_factory) -> str:
    tmp_path = tmp_path_factory.mktemp("req-readonly")
    with isolated_versioned_app_env(tmp_path, "req-readonly-presentation.db") as env:
        login_admin(env["client"])
        response = env["client"].get("/admin/requisicoes")
        assert response.status_code == 200, response.status_code
        return _modal_form(response.get_data(as_text=True))


def _view_mode_declares_readonly() -> bool:
    """Read the marker out of the shipped loop instead of assuming it.

    Without this the resolution test below would keep passing against a
    template that had dropped the repair entirely.
    """
    page = TEMPLATE.read_text(encoding="utf-8")
    loop = re.search(
        r"form\.querySelectorAll\('input, select, textarea'\)\.forEach\(el=>\{(.*?)\n        \}\);",
        page,
        re.S,
    )
    assert loop, "the editability loop disappeared"
    # The non-editable branch only -- the edit branch also calls setAttribute
    # (for the locked Aluno select), so anything coarser reports a false pass.
    branch = loop.group(1).split("el.readOnly = true;", 1)
    assert len(branch) == 2, "the non-editable branch disappeared"
    return "el.setAttribute('aria-readonly', 'true');" in branch[1]


def _enter_view_mode(cards):
    """Replay the shipped view-mode transition on the parsed markup."""
    declares = _view_mode_declares_readonly()
    for card in cards:
        for tag, attributes in card.controls:
            if attributes.get("type") == "hidden":
                continue
            is_file = attributes.get("type") == "file"
            if tag == "input" and not is_file:
                attributes["readonly"] = ""
            else:
                attributes["disabled"] = ""
            if declares:
                attributes["aria-readonly"] = "true"
    return cards


def _resolve(card):
    """Which DS card rule wins, per the selectors pinned at the top."""
    controls = [
        attributes
        for _tag, attributes in card.controls
        if attributes.get("type") != "hidden"
    ]
    if not controls:
        return None

    def editable(attributes):
        return "readonly" not in attributes and "disabled" not in attributes

    def declared(attributes):
        return (
            "disabled" in attributes and attributes.get("aria-readonly") == "true"
        )

    nothing_editable = not any(editable(a) for a in controls)
    if nothing_editable and (
        any("readonly" in a for a in controls) or any(declared(a) for a in controls)
    ):
        return "readonly"
    if (
        all("disabled" in a for a in controls)
        and not any(declared(a) for a in controls)
    ):
        return "disabled"
    return "default"


def test_escopo_and_empty_attachments_are_ds_controls_not_styled_divs(modal_html):
    """Both were <div class="control" style="...">: no DS state, inline colour."""
    scope = re.search(r'<input[^>]*id="m_scope_hint"[^>]*>', modal_html)
    assert scope, "Escopo is not a DS control"
    scope_tag = scope.group(0)
    assert "readonly" in scope_tag and 'aria-readonly="true"' in scope_tag
    assert "style=" not in scope_tag
    # Static value, never submittable -- the Ver Aluno rule.
    assert "name=" not in scope_tag
    assert 'aria-label="Escopo"' in scope_tag

    page = TEMPLATE.read_text(encoding="utf-8")
    empty_state = re.search(
        r'<input class="control" type="text" readonly aria-readonly="true" '
        r'aria-label="Comprovantes"[^>]*>',
        page,
    )
    assert empty_state, "the empty Comprovantes state is not a DS read-only control"

    # No control on THIS surface may paint its own visual state. Scoped to the
    # requisição form and its JS-rendered rows (#req-presets-modal is a
    # different modal), and to the properties this defect is about: the
    # auto-grow textareas' inline `height` is layout the JS owns, not paint.
    anexos = re.search(r"function renderAnexos\(anexos\)\{(.*?)\n    \}", page, re.S)
    assert anexos, "renderAnexos disappeared"
    paint = re.compile(r"\b(color|background|border)")
    for region in (modal_html, anexos.group(1)):
        painted = [
            tag
            for tag in re.findall(r"<(?:input|select|textarea|div)[^>]*>", region)
            if "control" in tag
            and paint.search(re.search(r'style="([^"]*)"', tag).group(1) if 'style="' in tag else "")
        ]
        assert not painted, f"a .control still paints itself inline: {painted}"

    # ...and the JS must not reintroduce one imperatively either.
    assert "scopeHint.style.color" not in page, (
        "the Escopo hint is back to setting its colour inline instead of using "
        "the DS invalid contract"
    )


def test_every_non_editable_field_resolves_to_the_same_read_only_paint(modal_html):
    parser = _FormParser()
    parser.feed(modal_html)
    cards = [card for card in parser.cards if card.controls]
    assert len(cards) >= 8, [card.label for card in cards]

    resolved = {
        card.label: _resolve(card) for card in _enter_view_mode(cards)
    }
    wrong = {label: state for label, state in resolved.items() if state != "readonly"}
    assert not wrong, (
        "these fields do not land on the shared read-only paint in view mode: "
        f"{wrong}"
    )

    # The fields the defect report named, present and accounted for.
    for label in ("Aluno", "Escopo", "Tipo", "Grupo", "Atividade", "Nome do evento"):
        assert label in resolved, sorted(resolved)


def test_editable_mode_stays_visually_distinct(modal_html):
    """Create/edit must not inherit the read-only paint."""
    parser = _FormParser()
    parser.feed(modal_html)
    cards = [card for card in parser.cards if card.controls]

    # As rendered, before any mode is applied, only Escopo reads as read-only:
    # it is the one field that is never editable in any mode.
    readonly_cards = sorted(
        card.label for card in cards if _resolve(card) == "readonly"
    )
    assert readonly_cards == ["Escopo"], readonly_cards
    assert not [card.label for card in cards if _resolve(card) == "disabled"]

    # Grupo pairs an editable <select> with a read-only description. The DS
    # guard deliberately leaves that card in its normal state -- greying it
    # would grey the still-interactive select with it.
    grupo = next(card for card in cards if card.label == "Grupo")
    assert len(grupo.controls) >= 2
    assert _resolve(grupo) == "default"
