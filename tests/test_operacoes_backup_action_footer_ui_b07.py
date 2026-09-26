"""UI-B07: the generic "Gerar backup agora" belongs in the Operações footer.

The rejected placement put the action on the card's explanatory row, pinned to
the right of the lead sentence by a page-local `.db-card-lead` flex wrapper::

    [ Operações ]
    Use o backup manual para criar um snapshot…   [ Gerar backup agora ]
    ────────────────────────────────────────────
    Recuperar banco de dados …

The accepted shape puts it at the bottom of the whole surface, using the footer
contract this page already owns and that was accepted on the "Destinos de
backup" and "Política de retenção" cards::

    .db-card form > .db-actions{ justify-content:flex-end;
                                 padding-top:10px;
                                 border-top:1px solid #edf2f7; }

so the markup is a plain `.db-actions` row as the last child of a card form. No
new class, no backup-specific footer style, no wrapper left behind.

This is a placement change only: endpoint, method, CSRF, RBAC gate, icon and
label are the same bytes that used to sit on the lead row.

Not to be confused with the provider-specific "Enviar backup agora" actions on
the Google Drive / OneDrive cards, which are a different action family and are
covered by tests/test_cloud_provider_card_symmetry_ui_b07.py.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import main
from tests.session_support import stamp_auth_version

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = PROJECT_ROOT / "templates" / "admin_banco_dados.html"

LABEL = "Gerar backup agora"
ENDPOINT = "/admin/banco-dados/backup"


@pytest.fixture(scope="module")
def template() -> str:
    return TEMPLATE_PATH.read_text(encoding="utf-8-sig")


@pytest.fixture(scope="module")
def css(template) -> str:
    return "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", template, re.S | re.I))


@pytest.fixture()
def admin_client():
    with main.app.app_context():
        main.init_db()
        client = main.app.test_client()
    with client.session_transaction() as session:
        session["user_id"] = 1
        session["user_type"] = "admin"
        session["user_name"] = "Administrador"
        session["access_level"] = "admin_total"
        stamp_auth_version(session)
    return client


@pytest.fixture()
def page(admin_client) -> str:
    response = admin_client.get("/admin/banco-dados")
    assert response.status_code == 200, response.status_code
    return response.get_data(as_text=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _operacoes(page: str) -> str:
    """The Operações <article>, closed by balancing its own <article> tags."""
    marker = page.index(">Operações<")
    start = page.rindex("<article", 0, marker)
    cursor = page.index(">", start) + 1
    depth = 1
    for token in re.finditer(r"<article\b|</article>", page[cursor:]):
        depth += 1 if token.group(0) != "</article>" else -1
        if depth == 0:
            return page[cursor : cursor + token.start()]
    raise AssertionError("unbalanced Operações article")


def _lead(article: str) -> str:
    """Everything from the card head down to the first subsection."""
    after_head = article.split("</div>", 1)[1]
    return after_head.split('<div class="db-subsection">', 1)[0]


def _footer(article: str) -> str:
    return article[article.rindex('<div class="db-actions">') :]


# ==========================================================================
# 1. The action: exactly one, and it is not on the explanatory row
# ==========================================================================


def test_the_generic_backup_action_occurs_exactly_once(page):
    assert page.count(LABEL) == 1, (
        f"{LABEL!r} must exist once on the page, not {page.count(LABEL)}"
    )
    assert _operacoes(page).count(LABEL) == 1
    # It was moved, not duplicated: one POST target for this endpoint too.
    assert page.count(f'action="{ENDPOINT}"') == 1


def test_the_action_is_not_in_the_upper_explanatory_row(page):
    """The exact rejected placement."""
    lead = _lead(_operacoes(page))
    assert LABEL not in lead, "the rejected upper placement is still rendered"
    assert ENDPOINT not in lead


def test_the_explanatory_row_carries_no_action_control_at_all(page):
    """§3: not the button, not an empty wrapper, not a blank row."""
    lead = _lead(_operacoes(page))
    assert "<button" not in lead, lead
    assert "<form" not in lead, lead
    assert "db-actions" not in lead, "an empty action wrapper was left behind"
    assert 'class="btn' not in lead
    # What remains is the paragraph, flowing normally across the body.
    paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", lead, re.S)
    assert len(paragraphs) == 1, paragraphs
    assert "Use o backup manual" in paragraphs[0]


def test_the_lead_flex_wrapper_is_gone_from_markup_and_css(template, css, page):
    """It existed only to pin the button right of the sentence."""
    markup = re.sub(r"\{#.*?#\}", "", template, flags=re.S)
    assert "db-card-lead" not in markup, "the upper-action wrapper survives"
    assert "db-card-lead" not in css, "dead CSS for the retired wrapper"
    assert "db-card-lead" not in page


# ==========================================================================
# 2. The footer: shared contract, bottom of the surface
# ==========================================================================


def test_the_action_is_the_last_thing_in_the_operacoes_card(page):
    article = _operacoes(page)
    assert LABEL in _footer(article)
    # Nothing of the recovery subsection comes after it.
    assert "db-subsection" not in _footer(article)
    assert article.index("db-subsection") < article.rindex('<div class="db-actions">')


def test_the_footer_uses_the_shared_card_action_contract(page, css):
    """Reused, not reinvented: the selector already styled two other cards."""
    article = _operacoes(page)
    footer_form = re.search(
        r'<form method="post" action="' + re.escape(ENDPOINT) + r'">(.*?)</form>',
        article,
        re.S,
    )
    assert footer_form, "the backup form is not the card-level footer form"
    # .db-actions must be a DIRECT child of that form for the rule to apply.
    assert re.match(
        r'\s*<input type="hidden" name="csrf_token"[^>]*>\s*<div class="db-actions">',
        footer_form.group(1),
    ), footer_form.group(1)

    rule = re.search(r"\.db-card form > \.db-actions\{(.*?)\}", css, re.S)
    assert rule, "the shared card action contract disappeared"
    declarations = re.sub(r"\s+", "", rule.group(1))
    assert "justify-content:flex-end" in declarations
    assert "border-top:1pxsolid" in declarations


def test_no_backup_specific_footer_style_was_added(css, template):
    """§4: reuse the shared classes; invent nothing for this one button."""
    for invented in (
        "db-card-footer",
        "db-operations-footer",
        "db-backup-footer",
        "db-operacoes-footer",
    ):
        assert invented not in css, invented
        assert invented not in template, invented
    # And no inline geometry on the moved action.
    article_source = template.split("{# ────────── Operações ────────── #}", 1)[1]
    footer_source = article_source.split('<div class="db-actions">', 1)[1].split(
        "</div>", 1
    )[0]
    assert "style=" not in footer_source


# ==========================================================================
# 3. Placement only -- the action itself is untouched
# ==========================================================================


def test_endpoint_method_csrf_icon_and_label_are_unchanged(page):
    article = _operacoes(page)
    form = re.search(
        r'<form method="post" action="' + re.escape(ENDPOINT) + r'">(.*?)</form>',
        article,
        re.S,
    )
    assert form, "endpoint or method changed"
    assert 'name="csrf_token"' in form.group(1)
    button = re.search(r"<button([^>]*)>(.*?)</button>", form.group(1), re.S)
    assert button, form.group(1)
    assert 'type="submit"' in button.group(1)
    assert 'class="btn primary"' in button.group(1)
    assert 'data-lucide="database"' in button.group(2)
    assert LABEL in button.group(2)


def test_the_rbac_gate_still_wraps_the_action(template):
    """The same `banco_dados:edit` gate, now around the footer instead of the row.

    `banco_dados` is `none` for every built-in profile except `admin_total`
    (``PROFILE_RESOURCE_SCOPES`` in ``app/auth.py``), so no built-in profile can
    reach this page and still be denied the action -- the gate is asserted where
    it lives rather than through a second rendered profile.
    """
    source = template.split("{# ────────── Operações ────────── #}", 1)[1].split(
        "</article>", 1
    )[0]
    gate = "{% if auth_can('banco_dados', 'edit') %}"
    assert source.count(gate) == 1, "the action gained or lost a permission gate"
    body = source[source.index(gate) :]
    assert body.index(LABEL) < body.index("{% endif %}"), (
        "the action escaped its permission gate"
    )
    # And the endpoint itself is still gated server-side at banco_dados:edit.
    auth = (PROJECT_ROOT / "app" / "auth.py").read_text(encoding="utf-8")
    assert re.search(
        r'endpoint == "admin_banco_dados_backup":\s*\n\s*return _permission\('
        r'"banco_dados", "edit"\)',
        auth,
    ), "the server-side permission for the backup endpoint changed"


# ==========================================================================
# 4. Blast radius
# ==========================================================================


def test_the_recovery_subsection_is_untouched(page):
    article = _operacoes(page)
    # Bounded at the footer: the card-level action form is not part of it.
    subsection = article.split('<div class="db-subsection">', 1)[1].split(
        f'<form method="post" action="{ENDPOINT}">', 1
    )[0]
    assert "Recuperar banco de dados" in subsection
    assert 'action="/admin/banco-dados/restaurar/upload"' in subsection
    assert 'id="restore-upload-form"' in subsection
    assert 'name="backup_file"' in subsection
    assert "db-recovery-row" in subsection
    # Its own controls keep their own row layout, not the footer's.
    assert "Carregar arquivo" in subsection
    for form in re.findall(r"<form[^>]*>(.*?)</form>", subsection, re.S):
        assert '<div class="db-actions">' not in form, (
            "a recovery form was given the card footer row"
        )


def test_the_provider_backup_actions_were_not_touched(page):
    """§6: a different action family, moved in the previous lane. Left alone."""
    assert page.count("Enviar backup agora") == 2
    cards = [
        card.split("</section>", 1)[0]
        for card in page.split('<section class="db-provider-card">')[1:3]
    ]
    assert len(cards) == 2
    for card in cards:
        # Still exactly one, still in the provider footer, still not the
        # generic action.
        assert card.count("Enviar backup agora") == 1
        footer = card.split('class="db-provider-config-footer"', 1)[1]
        assert "Enviar backup agora" in footer
        assert LABEL not in card
    # The two upload endpoints are untouched and never reached the generic card.
    assert ENDPOINT not in "".join(cards)
