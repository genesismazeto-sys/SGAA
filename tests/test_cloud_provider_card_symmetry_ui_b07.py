"""UI-B07 / reopened UI-A03: Google Drive and OneDrive cards, row for row.

The rejected screenshot showed the Google card carrying one metadata row the
OneDrive card did not have --

    Seleção de pasta: configuração segura desta máquina

-- so Google reached the common actions one text row later than OneDrive.

Tracing it: that row rendered ``google_picker_config_source``, which
``cloud_config.get_google_picker_config`` derives from the SAME machine-store
record (``providers.google``) that ``gdrive_config_source`` reports one row
above it.  Both rows therefore printed the identical custody sentence about the
identical blob.  It was redundant implementation detail, not a second concept,
and OneDrive had no equivalent to render because its folder browser
(``/admin/backup/cloud-folders/onedrive``) runs on the OAuth token it already
holds.  Resolution: **Case B** -- the row is gone from Google rather than
invented for OneDrive.

What survives is the *failure* state: the Picker needs an API key and an App ID
of its own, so when they are missing the card must still say the folder selector
is unusable.  That is an actionable problem, not metadata, so it renders in the
state-driven note region the two cards already share with "Último upload" /
"Falha" -- never as a common metadata row.

Second half of the ticket: "Enviar backup agora" was rejected inside the card
body and now lives in the footer beside Salvar, bound to its own POST target
with the HTML ``form`` attribute because forms cannot nest.  Endpoint, method,
CSRF, provider, icon, label and disabled behaviour are unchanged.

None of it may be bought with a spacer, a blank row or a fixed height.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import main
from app import machine_secrets
from app.views.admin import banco_dados as banco_dados_view
from tests.root_admin_test_config import TEST_ROOT_ADMIN_EMAIL
from tests.session_support import stamp_auth_version

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = PROJECT_ROOT / "templates" / "admin_banco_dados.html"

GOOGLE_SECRET = "google-application-secret-never-rendered"
ONEDRIVE_SECRET = "onedrive-application-secret-never-rendered"

PROVIDERS = (
    ("gdrive", "google", "/admin/backup/google/upload"),
    ("onedrive", "onedrive", "/admin/backup/onedrive/upload"),
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
def machine_store(tmp_path, monkeypatch):
    """A disposable machine-secret store, fully detached from the real one."""
    local_app_data = tmp_path / "LocalAppData"
    store_path = local_app_data / "SGAA" / "secrets" / "cloud-oauth.dpapi"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    for variable in (
        "TOKEN_ENCRYPTION_KEY",
        "APP_PUBLIC_BASE_URL",
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_PICKER_API_KEY",
        "GOOGLE_APP_ID",
        "MS_CLIENT_ID",
        "MS_CLIENT_SECRET",
        "MS_TENANT_ID",
        "ONEDRIVE_CLIENT_ID",
        "ONEDRIVE_TENANT_ID",
    ):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setattr(
        machine_secrets, "get_machine_secrets_path", lambda: str(store_path)
    )
    monkeypatch.setattr(
        machine_secrets, "_protect_bytes", lambda value: b"p:" + value[::-1]
    )
    monkeypatch.setattr(
        machine_secrets, "_unprotect_bytes", lambda value: value[len(b"p:") :][::-1]
    )
    return store_path


def _seed_google(**extra):
    machine_secrets.update_machine_oauth_configuration(
        provider="google",
        values={
            "client_id": "google-client-id",
            "client_secret": GOOGLE_SECRET,
            **extra,
        },
        public_base_url=None,
    )


def _seed_onedrive():
    machine_secrets.update_machine_oauth_configuration(
        provider="onedrive",
        values={
            "client_id": "onedrive-client-id",
            "client_secret": ONEDRIVE_SECRET,
            "tenant_id": "tenant-uuid",
        },
        public_base_url=None,
    )


def _authorize(monkeypatch, *providers):
    """Present authorized accounts without minting real tokens."""
    accounts = {
        provider: {
            "account_email": f"dono+{provider}@ej.edu.br",
            "token_json_available": True,
        }
        for provider in providers
    }
    monkeypatch.setattr(
        banco_dados_view,
        "_get_active_cloud_account",
        lambda conn, provider: accounts.get(provider),
    )


@pytest.fixture()
def connected_google_without_picker(machine_store, monkeypatch):
    """Google authorized, Picker values absent -- the one asymmetric state."""
    _seed_google()
    _seed_onedrive()
    _authorize(monkeypatch, "google")


@pytest.fixture()
def both_providers_connected(machine_store, monkeypatch):
    """The steady state the rejected screenshot was taken in."""
    _seed_google(picker_api_key="stored-picker-api-key-never-rendered", app_id="111122223333")
    _seed_onedrive()
    _authorize(monkeypatch, "google", "onedrive")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cards(page: str) -> list[str]:
    cards = page.split('<section class="db-provider-card">')[1:]
    if len(cards) < 2:
        pytest.skip("OneDrive card is not enabled in this configuration")
    return cards[:2]


def _body(card: str) -> str:
    """Everything above the footer: head + meta + notes + actions."""
    return card.split('class="db-provider-config-footer"')[0]


def _footer(card: str) -> str:
    return card.split('class="db-provider-config-footer"', 1)[1].split("</form>", 1)[0]


def _meta_block(card: str) -> str:
    """The .db-provider-meta element, closed by balancing its own <div>s."""
    opening = '<div class="db-provider-meta">'
    start = card.find(opening)
    assert start != -1, "the card lost its .db-provider-meta block"
    cursor = start + len(opening)
    depth = 1
    for token in re.finditer(r"<div\b|</div>", card[cursor:]):
        depth += 1 if token.group(0) != "</div>" else -1
        if depth == 0:
            return card[cursor : cursor + token.start()]
    raise AssertionError("unbalanced .db-provider-meta block")


def _meta_rows(card: str) -> list[str]:
    return re.findall(
        r'<div class="db-provider-line[^"]*"[^>]*>(.*?)</div>', _meta_block(card), re.S
    )


def _text(fragment: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", fragment).split())


def _rule(css: str, selector: str) -> str:
    match = re.search(re.escape(selector) + r"\{(.*?)\}", css, re.S)
    assert match, f"missing rule: {selector}"
    return match.group(1)


# ==========================================================================
# 1. Every metadata line has an explicit, traceable source
# ==========================================================================


def test_each_metadata_row_names_the_state_it_renders(
    both_providers_connected, admin_client
):
    """No row may exist that does not print a value the card actually holds."""
    page = admin_client.get("/admin/banco-dados").get_data(as_text=True)
    google, onedrive = _cards(page)

    for card in (google, onedrive):
        rows = _meta_rows(card)
        assert len(rows) == 3, [_text(row) for row in rows]

        account, folder, credentials = rows
        # 1. account -- the connected identity, or why there is none.
        assert _text(account), "the account row renders nothing"
        # 2. folder -- the live destination path, with its own icon and tooltip.
        assert 'data-lucide="folder"' in folder
        assert "db-path-ellipsis" in folder and "data-ptip=" in folder
        # 3. credential custody -- <prefix>_config_source, one sentence.
        assert _text(credentials).startswith("Credenciais do aplicativo:")
        assert _text(credentials).split(":", 1)[1].strip() in {
            "configuração segura desta máquina",
            "ambiente legado",
            "ausentes",
        }


def test_the_credential_row_is_bound_to_each_provider_own_source(template):
    """Same sentence, two independent truths -- neither card hardcodes it."""
    cards = template.split('<section class="db-provider-card">')[1:]
    assert len(cards) == 2
    for card, variable in zip(cards, ("gdrive_config_source", "onedrive_config_source")):
        meta = _meta_block(card)
        assert meta.count("Credenciais do aplicativo:") == 1
        assert variable in meta, f"the custody row is not driven by {variable}"
        # Literal copy only; the truth comes from the context variable.
        assert "MACHINE_LOCAL_DPAPI" in meta and "ENVIRONMENT" in meta


# ==========================================================================
# 2. The rejected row is gone, and was not replaced by an empty one
# ==========================================================================


def test_the_redundant_picker_custody_row_is_gone(
    template, both_providers_connected, admin_client
):
    """Case B: it restated the credential row for the same stored record."""
    markup = re.sub(r"\{#.*?#\}", "", template, flags=re.S)
    assert "Seleção de pasta: " not in markup, (
        "the Picker custody row is back; it prints the custody of the same "
        "machine-store record the row above it already reports"
    )
    # The value it rendered is still resolved by the view -- it simply stops
    # being copy, so nothing in the template consumes it any more.
    assert "google_picker_config_source" not in markup

    page = admin_client.get("/admin/banco-dados").get_data(as_text=True)
    google, _ = _cards(page)
    assert "Seleção de pasta: " not in google


def test_no_blank_or_spacer_row_was_introduced(
    template, both_providers_connected, admin_client
):
    """§3: visual symmetry had to follow semantic symmetry."""
    for forbidden in (
        "db-spacer",
        "db-provider-spacer",
        'class="spacer"',
        "&nbsp;",
        "&#160;",
    ):
        assert forbidden not in template, forbidden

    page = admin_client.get("/admin/banco-dados").get_data(as_text=True)
    for card in _cards(page):
        for row in _meta_rows(card):
            assert _text(row), f"an empty metadata row was rendered: {row!r}"


def test_both_cards_render_the_same_metadata_structure(
    both_providers_connected, admin_client
):
    """The requirement the screenshot failed: row for row, same shape."""
    page = admin_client.get("/admin/banco-dados").get_data(as_text=True)
    google, onedrive = _cards(page)

    def shape(card: str) -> list[str]:
        return re.findall(
            r'<div class="(db-provider-line[^"]*)"', _meta_block(card)
        )

    assert shape(google) == shape(onedrive), (
        "the two cards still differ in metadata rows: "
        f"{shape(google)} vs {shape(onedrive)}"
    )
    # One card may not reach the common action area a row earlier than the
    # other, which is exactly what the rejected screenshot showed.
    assert len(shape(google)) == len(shape(onedrive)) == 3


# ==========================================================================
# 3. The one genuinely Google-specific message is a note, not a row
# ==========================================================================


def test_the_picker_failure_is_a_note_and_never_a_metadata_row(
    connected_google_without_picker, admin_client
):
    """Case C treatment for the part that IS provider-specific.

    OneDrive browses folders with the OAuth token it already holds, so it has no
    second credential that can go missing. Google's Picker does. That asymmetry
    is real -- but it is a problem state, so it may not sit in the common
    metadata block and push the shared rows down.
    """
    page = admin_client.get("/admin/banco-dados").get_data(as_text=True)
    google, onedrive = _cards(page)

    assert "data-google-picker-missing" in google
    assert "Seleção de pasta indisponível" in google
    # It is a note in the shared state-driven region...
    assert re.search(
        r'<p class="db-provider-note is-warning"[^>]*data-google-picker-missing',
        google,
    ), "the Picker warning is not rendered as a provider note"
    # ...and the common metadata block is still three rows on BOTH cards.
    assert len(_meta_rows(google)) == 3
    assert len(_meta_rows(onedrive)) == 3
    assert "data-google-picker-missing" not in "".join(_meta_rows(google))


def test_the_warning_never_renders_once_the_picker_is_configured(
    both_providers_connected, admin_client
):
    page = admin_client.get("/admin/banco-dados").get_data(as_text=True)
    assert "data-google-picker-missing" not in page
    # Scoped to the card: the Picker runtime keeps its own error string in the
    # page script, which is a different, untouched surface.
    google, _ = _cards(page)
    assert "Seleção de pasta indisponível" not in _body(google)


def test_the_warning_colour_reuses_the_card_existing_warning_token(css):
    """No new colour was introduced for the relocated message."""
    rule = re.search(
        r"([^{}]*\.db-provider-note\.is-warning\s*)\{([^}]*)\}", css, re.S
    )
    assert rule, "the note warning has no rule"
    assert ".db-provider-line.is-warning" in rule.group(1), (
        "the note does not share the card's existing warning declaration"
    )
    assert "color:#92400e" in rule.group(2).replace(" ", "")


# ==========================================================================
# 4. Backup-now: exactly once, in the footer
# ==========================================================================


def test_backup_now_appears_exactly_once_per_provider(
    both_providers_connected, admin_client
):
    page = admin_client.get("/admin/banco-dados").get_data(as_text=True)
    for card in _cards(page):
        assert card.count("Enviar backup agora") == 1
    # And the page-level "Gerar backup agora" in Operações is a different,
    # untouched action -- the cards did not grow a second one.
    assert page.count("Enviar backup agora") == 2


def test_backup_now_is_in_the_footer_and_not_in_the_card_body(
    both_providers_connected, admin_client
):
    page = admin_client.get("/admin/banco-dados").get_data(as_text=True)
    for card in _cards(page):
        assert "Enviar backup agora" not in _body(card), (
            "the rejected in-body backup action is back"
        )
        footer = _footer(card)
        assert "Enviar backup agora" in footer
        assert "db-provider-footer-actions" in footer
        # It sits beside Salvar, in that order, inside one action group.
        group = footer.split('class="db-provider-footer-actions"', 1)[1]
        assert group.index("Enviar backup agora") < group.index("Salvar")


def test_the_retired_body_action_wrapper_is_gone(template, css):
    assert "db-provider-primary" not in template, (
        "the upper-body primary action slot survives"
    )
    assert "db-provider-primary" not in css, "dead CSS for the retired slot"


def test_backup_now_keeps_its_endpoint_method_csrf_and_provider(
    both_providers_connected, admin_client
):
    """§6: only the position changed."""
    page = admin_client.get("/admin/banco-dados").get_data(as_text=True)
    for card, (prefix, _provider, endpoint) in zip(_cards(page), PROVIDERS):
        target = re.search(
            r'<form id="' + prefix + r'-backup-now" class="db-provider-post-target"'
            r' method="post" action="([^"]+)">(.*?)</form>',
            card,
            re.S,
        )
        assert target, f"{prefix} lost its backup POST target"
        assert target.group(1) == endpoint
        assert 'name="csrf_token"' in target.group(2)

        button = re.search(
            r'<button type="submit" form="' + prefix + r'-backup-now"[^>]*>(.*?)</button>',
            _footer(card),
            re.S,
        )
        assert button, f"{prefix} footer button is not bound to its POST target"
        assert 'data-lucide="upload-cloud"' in button.group(1)
        assert "Enviar backup agora" in button.group(1)


def test_a_disconnected_provider_still_shows_the_action_disabled(
    machine_store, admin_client
):
    """Nothing is configured: the button stays, inert, exactly as before."""
    page = admin_client.get("/admin/banco-dados").get_data(as_text=True)
    for card, (prefix, _provider, _endpoint) in zip(_cards(page), PROVIDERS):
        footer = _footer(card)
        assert "Enviar backup agora" in footer
        button = re.search(
            r"<button[^>]*>(?:(?!</button>).)*Enviar backup agora", footer, re.S
        )
        assert button, footer
        assert "disabled" in button.group(0)
        assert 'aria-disabled="true"' in button.group(0)
        assert f'id="{prefix}-backup-now"' not in card, (
            "an unusable POST target was emitted for a disconnected provider"
        )


def test_the_footer_action_is_declared_once_for_both_cards(template):
    """One macro, two call sites: the action cannot drift between providers."""
    assert template.count("{% macro provider_backup_now_button(") == 1
    assert template.count("{% macro provider_backup_now_target(") == 1
    assert template.count("{{ provider_backup_now_target(") == 2
    # Two footers per card are mutually exclusive branches (with / without the
    # credential form), so the macro is called twice per provider in source and
    # exactly once per provider at render time -- proven above.
    assert template.count("{{ provider_backup_now_button(") == 4


def test_the_save_action_still_owns_the_credential_form(admin_client):
    """Salvar remains the only submit bound to the credential form itself."""
    page = admin_client.get("/admin/banco-dados").get_data(as_text=True)
    for card in _cards(page):
        config = card.split('class="db-provider-config">', 1)[1].split("</form>", 1)[0]
        own = [
            button
            for button in re.findall(r"<button[^>]*type=\"submit\"[^>]*>", config)
            if "form=" not in button
        ]
        assert len(own) == 1, own
        assert config.count('name="action" value="save_credentials"') == 1


# ==========================================================================
# 5. Alignment contract (UI-A03 regression guard)
# ==========================================================================


def test_app_public_base_url_is_still_the_first_comparable_config_row(
    both_providers_connected, admin_client
):
    page = admin_client.get("/admin/banco-dados").get_data(as_text=True)
    for card in _cards(page):
        config = card.split('class="db-provider-config">', 1)[1]
        first = re.search(r'<label for="([^"]+)"', config)
        assert first and first.group(1).endswith("app_public_base_url"), (
            first.group(1) if first else None
        )


def test_the_common_regions_appear_in_the_same_order_on_both_cards(
    both_providers_connected, admin_client
):
    page = admin_client.get("/admin/banco-dados").get_data(as_text=True)
    google, onedrive = _cards(page)

    def regions(card: str) -> list[str]:
        return re.findall(
            r'class="(db-provider-head|db-provider-meta|db-provider-actions'
            r'|db-provider-secondary|db-provider-config|db-provider-config-footer'
            r'|db-provider-footer-actions)[" ]',
            card,
        )

    assert regions(google) == regions(onedrive), (
        f"{regions(google)} vs {regions(onedrive)}"
    )


def test_spare_height_can_only_land_between_the_last_field_and_the_footer(css):
    """The shorter card finishes earlier; the gap stays where it was accepted."""
    config = _rule(css, ".db-provider-config")
    assert "flex:1 1 auto" in config.replace("  ", " ")
    footer = _rule(css, ".db-provider-config-footer")
    assert "margin-top:auto" in footer
    assert "border-top" in footer

    card = _rule(css, ".db-provider-card")
    assert "display:flex" in card and "flex-direction:column" in card
    assert "justify-content" not in card, (
        "justify-content would redistribute the surplus across the card again"
    )


def test_no_fixed_height_and_no_provider_specific_geometry(css, template):
    card = _rule(css, ".db-provider-card")
    assert "min-height" not in card and "height:" not in card

    # `line-height` is typography, not geometry -- only a box height is a hack.
    box_height = re.compile(r"(?<!line-)(?<!-)\bheight\s*:")
    for selector in (".db-provider-meta", ".db-provider-line", ".db-provider-note"):
        rule = _rule(css, selector)
        assert not box_height.search(rule), f"{selector} was given a height: {rule}"

    footer_actions = _rule(css, ".db-provider-footer-actions")
    assert not box_height.search(footer_actions)
    assert "%" not in footer_actions

    offenders = [
        line.strip()
        for line in css.splitlines()
        if re.search(r"(onedrive|gdrive|google)", line, re.I)
        and re.search(r"(margin|height|padding|top)\s*:", line)
    ]
    assert not offenders, f"provider-specific geometry was added: {offenders}"

    # The POST target is not a layout participant, so it cannot pad anything.
    assert "display:none" in _rule(css, ".db-provider-post-target")


def test_the_page_carries_no_inline_geometry_on_the_new_markup(template):
    """No local spacer component and no inline style on the moved action."""
    for macro in ("provider_backup_now_button", "provider_backup_now_target"):
        block = template.split("{% macro " + macro + "(", 1)[1].split(
            "{% endmacro %}", 1
        )[0]
        assert "style=" not in block, f"{macro} carries inline geometry"
