"""UI-B06 -- Admin > Acesso, the "Novo acesso" button typography.

Reported: the button looked like it used different typography from the other
SGAA list CTAs.

It did, and the cause was not on the Acesso page. The shared `.btn` contract
owned `font-size`, `font-weight` and `line-height` but **not** `font-family`,
and a `<button>` does not inherit font-family from its ancestors -- the UA
stylesheet supplies its own for form controls. So one class rendered in two
typefaces depending only on the element carrying it:

    <a class="btn">      -> --font-sans (Inter), inherited from body
    <button class="btn"> -> whatever the UA picks for form controls

"Novo acesso" is a `<button>`; the CTAs it sits beside in the product (Alunos,
Cursos, Turmas, Matrizes, Requisições, Atividades, …) are anchors.

Fix: `font-family:inherit` on `.btn`, in the component owner. No page-local
rule, no Acesso-specific typography, no magic padding.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main  # noqa: E402
from tests.session_support import stamp_auth_version  # noqa: E402

ROOT = Path(BASE)
GLOBAL_CSS = ROOT / "static" / "css" / "modern-style.css"
LIST_CSS = ROOT / "static" / "css" / "components" / "list-cards.css"
ACESSO = ROOT / "templates" / "admin_acesso.html"

# The CTA population this button belongs to: every list toolbar "Novo/Adicionar".
ANCHOR_CTA_PAGES = (
    "admin_alunos",
    "admin_atividades",
    "admin_cursos",
    "admin_matrizes",
    "admin_requisicoes",
    "admin_turmas",
    "admin_detalhes_turma",
)
BUTTON_CTA_PAGES = ("admin_acesso", "admin_alertas", "admin_arquivos")

TYPOGRAPHY = ("font-family", "font-size", "font-weight", "line-height",
              "letter-spacing", "text-transform")


@pytest.fixture(scope="module")
def client():
    with main.app.app_context():
        main.init_db()
    with main.app.test_client() as test_client:
        yield test_client


@pytest.fixture(scope="module")
def acesso_html(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["user_type"] = "admin"
        sess["user_name"] = "Administrador"
        sess["access_level"] = "admin_total"
        stamp_auth_version(sess)
    response = client.get("/admin/acesso")
    assert response.status_code == 200, response.status_code
    return response.get_data(as_text=True)


def _btn_rule(css):
    match = re.search(r"\n\.btn\{(.*?)\n\}", css, re.S)
    assert match, ".btn lost its owner"
    return match.group(1)


def _declarations(block):
    body = re.sub(r"/\*.*?\*/", "", block, flags=re.S)
    return {
        d.split(":", 1)[0].strip(): d.split(":", 1)[1].strip()
        for d in body.split(";")
        if ":" in d
    }


def test_the_button_markup_is_unchanged(acesso_html):
    """UI-B06 is typography only: position, label and behaviour stay put."""
    button = re.search(
        r'<button class="([^"]*)" type="button" id="btn-acesso-adicionar">(.*?)</button>',
        acesso_html,
        re.S,
    )
    assert button, "the Novo acesso button is gone or was restructured"
    classes, inner = button.groups()
    assert classes.split() == ["btn", "btn-nova-alinhado"], classes
    assert 'class="btn-icon btn-icon-plus' in inner
    assert '<span class="btn-label">Novo acesso</span>' in inner


def test_btn_owns_font_family_so_the_element_no_longer_decides_it():
    """The defect and the fix, in the component owner."""
    declarations = _declarations(_btn_rule(GLOBAL_CSS.read_text(encoding="utf-8")))
    assert declarations.get("font-family") == "inherit", (
        "`.btn` does not own font-family, so <button class='btn'> falls back to "
        "the UA form-control font while <a class='btn'> inherits --font-sans"
    )
    # The rest of the contract is untouched.
    assert declarations["font-size"] == "var(--font-size-base)"
    assert declarations["font-weight"] == "400"
    assert declarations["line-height"] == "1"


def test_no_page_local_typography_override_on_acesso(acesso_html):
    """Nothing on the page may restate button typography."""
    style = "\n".join(
        re.findall(r"<style[^>]*>(.*?)</style>", ACESSO.read_text(encoding="utf-8"), re.S | re.I)
    )
    offenders = [
        line.strip()
        for line in style.splitlines()
        if ".btn" in line.split("{")[0]
        and any(prop in line for prop in TYPOGRAPHY)
    ]
    assert not offenders, f"Acesso restates button typography locally: {offenders}"

    # And the button carries no inline style either.
    button = re.search(r'<button[^>]*id="btn-acesso-adicionar"[^>]*>', acesso_html)
    assert button and "style=" not in button.group(0), button.group(0)


def test_every_list_cta_now_resolves_to_one_typography_contract():
    """Anchors and buttons must stop rendering the same class two ways."""
    for name in ANCHOR_CTA_PAGES:
        source = (ROOT / "templates" / f"{name}.html").read_text(encoding="utf-8")
        assert re.search(r'<a [^>]*class="btn[^"]*btn-nova-alinhado', source), name
    for name in BUTTON_CTA_PAGES:
        source = (ROOT / "templates" / f"{name}.html").read_text(encoding="utf-8")
        assert re.search(r'<button class="btn[^"]*btn-nova-alinhado', source), name

    # Both populations resolve font-family through the same declaration: there
    # is exactly one, and it is on .btn.
    css = GLOBAL_CSS.read_text(encoding="utf-8")
    rules_only = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    families = re.findall(r"([^{}]*)\{[^}]*font-family[^}]*\}", rules_only)
    btn_owners = [sel.strip() for sel in families if ".btn" in sel]
    assert btn_owners == [".btn"], btn_owners


def test_the_shared_geometry_that_already_agreed_is_not_touched():
    """Height/size/gap were never the defect; they must stay as they were."""
    toolbar = re.search(
        r"\.toolbar \.filters \.btn,\s*\.toolbar \.actions \.btn,\s*"
        r"\.toolbar \.filters select \{([^}]*)\}",
        LIST_CSS.read_text(encoding="utf-8"),
        re.S,
    )
    assert toolbar, "the shared toolbar button rule disappeared"
    assert "font-size:13px" in toolbar.group(1)
    assert "height:calc(var(--btn-h) - 2px)" in toolbar.group(1)

    declarations = _declarations(_btn_rule(GLOBAL_CSS.read_text(encoding="utf-8")))
    assert declarations["height"] == "var(--btn-h)"
    assert declarations["padding"] == "0 var(--btn-px)"
    assert declarations["gap"] == "var(--btn-gap)"


def test_no_letter_spacing_or_text_transform_reaches_any_button():
    """Two properties the report named; neither is set on a button anywhere."""
    for path in (GLOBAL_CSS, LIST_CSS, ACESSO):
        text = path.read_text(encoding="utf-8")
        rules_only = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        for prop in ("letter-spacing", "text-transform"):
            for selector in re.findall(r"([^{}]*)\{[^}]*" + prop + r"[^}]*\}", rules_only):
                assert ".btn" not in selector, f"{path.name}: {selector.strip()} sets {prop}"
