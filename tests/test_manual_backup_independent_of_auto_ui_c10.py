"""UI-C10: manual backup is independent of automatic-backup participation.

Two concepts share each provider card:

* "Incluir no backup automático" -- whether the provider takes part in the
  automatic cycle. Its only reader is ``orchestrator._maybe_upload_to_drives``,
  which skips providers whose ``<prefix>_enabled`` flag is off.
* "Enviar backup agora" -- an immediate upload through the provider's own
  endpoint. It depends only on the provider being connected and usable.

The reported coupling was the switch itself: it shipped permanently disabled
under the tooltip "Disponível quando o backup automático for ativado.", a
condition no screen could satisfy, sitting beside the manual button. These
tests pin both halves for both providers so neither can drift back.
"""

from __future__ import annotations

import re

import pytest

import main
from app import machine_secrets
from app.backup import orchestrator
from app.views.admin import banco_dados as banco_dados_view
from tests.session_support import stamp_auth_version


GOOGLE_SECRET = "google-application-secret-never-rendered"
ONEDRIVE_SECRET = "onedrive-application-secret-never-rendered"
STALE_TOOLTIP = "Disponível quando o backup automático for ativado."

PROVIDERS = {
    "google": {
        "prefix": "gdrive",
        "card_index": 0,
        "upload_url": "/admin/backup/google/upload",
        "backup_form": "gdrive-backup-now",
        "not_connected_flash": "Nenhuma conta Google conectada",
    },
    "onedrive": {
        "prefix": "onedrive",
        "card_index": 1,
        "upload_url": "/admin/backup/onedrive/upload",
        "backup_form": "onedrive-backup-now",
        "not_connected_flash": "Nenhuma conta OneDrive conectada",
    },
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
    monkeypatch.setattr(machine_secrets, "get_machine_secrets_path", lambda: str(store_path))
    monkeypatch.setattr(machine_secrets, "_protect_bytes", lambda value: b"p:" + value[::-1])
    monkeypatch.setattr(
        machine_secrets, "_unprotect_bytes", lambda value: value[len(b"p:") :][::-1]
    )
    machine_secrets.update_machine_oauth_configuration(
        provider="google",
        values={"client_id": "google-client-id", "client_secret": GOOGLE_SECRET},
        public_base_url=None,
    )
    machine_secrets.update_machine_oauth_configuration(
        provider="onedrive",
        values={
            "client_id": "onedrive-client-id",
            "client_secret": ONEDRIVE_SECRET,
            "tenant_id": "tenant-uuid",
        },
        public_base_url=None,
    )
    return store_path


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
def reset_flags():
    _set_drive_settings({"gdrive_enabled": "0", "onedrive_enabled": "0"})
    yield
    _set_drive_settings({"gdrive_enabled": "0", "onedrive_enabled": "0"})


def _authorize(monkeypatch, *providers, token_available=True):
    """Present authorized accounts without minting real tokens."""
    accounts = {
        provider: {
            "id": 1,
            "account_email": f"dono+{provider}@example.invalid",
            "token_json_available": token_available,
            "token_json_error": "" if token_available else "Token indisponivel.",
        }
        for provider in providers
    }
    monkeypatch.setattr(
        banco_dados_view, "_get_active_cloud_account", lambda conn, provider: accounts.get(provider)
    )


@pytest.fixture()
def upload_spy(tmp_path, monkeypatch):
    """Stub the manual path below the endpoint: no real zip, no network."""
    calls: list[str] = []
    artifact = tmp_path / "sgaa-backup.zip"
    artifact.write_bytes(b"PK")

    monkeypatch.setattr(
        banco_dados_view,
        "create_sqlite_backup_zip",
        lambda _db: {"zip_path": str(artifact), "file_name": artifact.name, "file_size": 2},
    )
    monkeypatch.setattr(banco_dados_view, "cleanup_backup_artifacts", lambda _artifacts: None)
    monkeypatch.setattr(banco_dados_view, "_require_cloud_token_encryption_ready", lambda: None)

    def _upload(conn, provider, **_kwargs):
        calls.append(provider)
        return {"account_email": f"dono+{provider}@example.invalid"}

    monkeypatch.setattr(banco_dados_view._cloud_connections, "upload_backup_zip", _upload)
    return calls


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _set_drive_settings(values: dict[str, str]) -> None:
    with main.app.app_context():
        conn = main.get_db_connection()
        banco_dados_view._save_drive_config(conn, values)
        conn.commit()


def _read_flag(prefix: str) -> str:
    with main.app.app_context():
        conn = main.get_db_connection()
        return orchestrator.get_drive_settings(conn)[f"{prefix}_enabled"]


def _card(page: str, provider: str) -> str:
    cards = page.split('<section class="db-provider-card">')[1:]
    if len(cards) < 2:
        pytest.skip("OneDrive card is not enabled in this configuration")
    return cards[PROVIDERS[provider]["card_index"]]


def _footer(card: str) -> str:
    return card.split('class="db-provider-config-footer"', 1)[1].split("</form>", 1)[0]


def _manual_button(card: str) -> str:
    match = re.search(
        r"<button\b[^>]*>(?:(?!</button>).)*Enviar backup agora", _footer(card), re.S
    )
    assert match, "the card lost its 'Enviar backup agora' button"
    return match.group(0).split(">", 1)[0]


def _auto_switch(card: str, prefix: str) -> str:
    match = re.search(rf'<input type="checkbox" name="{prefix}_enabled"[^>]*>', card)
    assert match, "the card lost its automatic-backup switch"
    return match.group(0)


def _page(client) -> str:
    return client.get("/admin/banco-dados").get_data(as_text=True)


def _card_payload(provider: str, **overrides) -> dict:
    if provider == "google":
        payload = {
            "provider": "google",
            "action": "save_credentials",
            "app_public_base_url": "http://localhost:5000",
            "client_id": "google-client-id",
            "client_secret": "",
            "gdrive_dest_folder": "Backups/sistema",
        }
    else:
        payload = {
            "provider": "onedrive",
            "action": "save_credentials",
            "app_public_base_url": "http://localhost:5000",
            "client_id": "onedrive-client-id",
            "client_secret": "",
            "tenant_id": "tenant-uuid",
        }
    payload.update(overrides)
    return payload


# ==========================================================================
# Cases 1-2: connected + AUTO OFF / ON -> button enabled, endpoint uploads
# ==========================================================================


@pytest.mark.parametrize("provider", sorted(PROVIDERS))
@pytest.mark.parametrize("auto_flag", ["0", "1"])
def test_connected_provider_offers_manual_backup_whatever_the_switch(
    provider, auto_flag, machine_store, admin_client, reset_flags, monkeypatch
):
    spec = PROVIDERS[provider]
    _authorize(monkeypatch, "google", "onedrive")
    _set_drive_settings({f"{spec['prefix']}_enabled": auto_flag})

    card = _card(_page(admin_client), provider)
    button = _manual_button(card)

    assert "disabled" not in button
    assert 'type="submit"' in button
    assert f'form="{spec["backup_form"]}"' in button
    assert f'id="{spec["backup_form"]}"' in card
    assert ("checked" in _auto_switch(card, spec["prefix"])) is (auto_flag == "1")


@pytest.mark.parametrize("provider", sorted(PROVIDERS))
@pytest.mark.parametrize("auto_flag", ["0", "1"])
def test_manual_endpoint_uploads_whatever_the_switch(
    provider, auto_flag, machine_store, admin_client, reset_flags, upload_spy, monkeypatch
):
    spec = PROVIDERS[provider]
    _authorize(monkeypatch, provider)
    _set_drive_settings({f"{spec['prefix']}_enabled": auto_flag})

    response = admin_client.post(spec["upload_url"], follow_redirects=False)

    assert response.status_code in (302, 303)
    assert upload_spy == [provider]
    # The manual path never rewrites the participation flag.
    assert _read_flag(spec["prefix"]) == auto_flag


# ==========================================================================
# Case 3: unavailable / deauthorized -> refused for an availability reason
# ==========================================================================


@pytest.mark.parametrize("provider", sorted(PROVIDERS))
def test_disconnected_provider_refuses_manual_backup_for_availability(
    provider, machine_store, admin_client, reset_flags, upload_spy, monkeypatch
):
    spec = PROVIDERS[provider]
    _authorize(monkeypatch)  # no active account for either provider
    _set_drive_settings({f"{spec['prefix']}_enabled": "1"})

    card = _card(_page(admin_client), provider)
    button = _manual_button(card)
    assert "disabled" in button
    assert "Conecte o" in button
    assert STALE_TOOLTIP not in button
    assert f'id="{spec["backup_form"]}"' not in card

    response = admin_client.post(spec["upload_url"], follow_redirects=True)
    assert spec["not_connected_flash"] in response.get_data(as_text=True)
    assert upload_spy == []


@pytest.mark.parametrize("provider", sorted(PROVIDERS))
def test_unreadable_authorization_refuses_manual_backup(
    provider, machine_store, admin_client, reset_flags, upload_spy, monkeypatch
):
    spec = PROVIDERS[provider]
    _authorize(monkeypatch, provider, token_available=False)

    assert "disabled" in _manual_button(_card(_page(admin_client), provider))

    response = admin_client.post(spec["upload_url"], follow_redirects=True)
    assert "Token indisponivel." in response.get_data(as_text=True)
    assert upload_spy == []


# ==========================================================================
# Cases 4-5: the automatic cycle still honours the switch
# ==========================================================================


@pytest.fixture()
def automatic_cycle_spy(monkeypatch):
    uploads: list[str] = []
    monkeypatch.setattr(
        orchestrator._cloud_connections,
        "get_authenticated_access_token",
        lambda conn, provider: ("access-token", f"dono+{provider}@example.invalid"),
    )
    monkeypatch.setattr(orchestrator._cd, "google_upload", lambda *a, **k: uploads.append("google"))
    monkeypatch.setattr(
        orchestrator._cd, "onedrive_upload", lambda *a, **k: uploads.append("onedrive")
    )
    monkeypatch.setattr(orchestrator._cd, "apply_retention_to_drive", lambda *a, **k: None)
    return uploads


def _run_automatic_upload(tmp_path) -> None:
    snapshot = tmp_path / "snapshot.db"
    snapshot.write_bytes(b"")
    with main.app.app_context():
        conn = main.get_db_connection()
        orchestrator._maybe_upload_to_drives(str(snapshot), conn=conn)


@pytest.mark.parametrize("provider", sorted(PROVIDERS))
def test_automatic_cycle_excludes_a_provider_whose_switch_is_off(
    provider, tmp_path, reset_flags, automatic_cycle_spy
):
    other = "onedrive" if provider == "google" else "google"
    _set_drive_settings(
        {
            f"{PROVIDERS[provider]['prefix']}_enabled": "0",
            f"{PROVIDERS[other]['prefix']}_enabled": "0",
        }
    )
    _run_automatic_upload(tmp_path)
    assert automatic_cycle_spy == []


@pytest.mark.parametrize("provider", sorted(PROVIDERS))
def test_automatic_cycle_includes_exactly_the_providers_switched_on(
    provider, tmp_path, reset_flags, automatic_cycle_spy
):
    other = "onedrive" if provider == "google" else "google"
    _set_drive_settings(
        {
            f"{PROVIDERS[provider]['prefix']}_enabled": "1",
            f"{PROVIDERS[other]['prefix']}_enabled": "0",
        }
    )
    _run_automatic_upload(tmp_path)
    assert automatic_cycle_spy == [provider]


# ==========================================================================
# The switch itself: editable, no stale tooltip, saved through the card
# ==========================================================================


def test_stale_automatic_backup_tooltip_is_gone(machine_store, admin_client, monkeypatch):
    _authorize(monkeypatch, "google", "onedrive")
    page = _page(admin_client)
    assert STALE_TOOLTIP not in page
    for provider, spec in PROVIDERS.items():
        card = _card(page, provider)
        switch = _auto_switch(card, spec["prefix"])
        assert "disabled" not in switch
        assert "is-disabled" not in _footer(card)
        assert f'name="{spec["prefix"]}_enabled_submitted" value="1"' in card


@pytest.mark.parametrize("provider", sorted(PROVIDERS))
def test_toggling_the_switch_never_changes_manual_availability(
    provider, machine_store, admin_client, reset_flags, monkeypatch
):
    spec = PROVIDERS[provider]
    _authorize(monkeypatch, "google", "onedrive")

    seen = []
    for checked in (True, False, True):
        overrides = {f"{spec['prefix']}_enabled_submitted": "1"}
        if checked:
            overrides[f"{spec['prefix']}_enabled"] = "1"
        admin_client.post(
            "/admin/banco-dados/drive-settings",
            data=_card_payload(provider, **overrides),
            follow_redirects=False,
        )
        assert _read_flag(spec["prefix"]) == ("1" if checked else "0")
        seen.append(_manual_button(_card(_page(admin_client), provider)))

    assert all("disabled" not in button for button in seen)
    assert len(set(seen)) == 1


@pytest.mark.parametrize("provider", sorted(PROVIDERS))
def test_card_save_without_the_marker_still_preserves_the_flag(
    provider, machine_store, admin_client, reset_flags
):
    """Unchanged save semantics: only a card that declares the switch writes it."""
    prefix = PROVIDERS[provider]["prefix"]
    _set_drive_settings({f"{prefix}_enabled": "1"})

    admin_client.post(
        "/admin/banco-dados/drive-settings",
        data=_card_payload(provider),
        follow_redirects=False,
    )

    assert _read_flag(prefix) == "1"
