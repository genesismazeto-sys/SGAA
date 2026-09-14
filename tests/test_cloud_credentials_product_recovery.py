"""Product recovery of the cloud application credentials from Banco de Dados.

An administrator must be able to configure the Google and OneDrive *application*
credentials, and the shared public OAuth address, as a normal product action on
the existing ``POST /admin/banco-dados/drive-settings`` endpoint -- with no new
route, no manual command, and no exposure of key material.

Every test that touches the DPAPI store redirects
``machine_secrets.get_machine_secrets_path`` at a ``tmp_path`` and replaces the
DPAPI primitives, so the real ``%LOCALAPPDATA%\\SGAA\\secrets`` store of the
developer running pytest is never read for content nor written.  ``LOCALAPPDATA``
itself is redirected too, so even an unpatched code path cannot reach it.
"""

from __future__ import annotations

import ast
import base64
import json
import logging
import sqlite3
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

import main
from app import cloud_config, cloud_credentials, machine_secrets
from app.backup import get_drive_settings
from app.services import token_encryption
from app.views.admin import banco_dados as banco_dados_view


PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = PROJECT_ROOT / "templates" / "admin_banco_dados.html"
CREDENTIALS_MODULE_PATH = PROJECT_ROOT / "app" / "cloud_credentials.py"

DRIVE_SETTINGS_URL = "/admin/banco-dados/drive-settings"

GOOGLE_SECRET = "google-application-secret-never-rendered"
ONEDRIVE_SECRET = "onedrive-application-secret-never-rendered"

# Text an ordinary administrator must never be shown by this surface.
FORBIDDEN_UI_TERMS = (
    "configure_cloud_oauth",
    "TOKEN_ENCRYPTION_KEY",
    "Fernet",
    "cryptography",
    "pip install",
    "python -c",
    "python -m",
    "DPAPI",
)

# ``MACHINE_LOCAL_DPAPI`` is an internal status enum the template compares
# against and never prints, so the source-level sweep excludes that one token.
# The rendered-page sweep keeps it: what an administrator sees must be clean.
FORBIDDEN_TEMPLATE_TERMS = tuple(
    term for term in FORBIDDEN_UI_TERMS if term != "DPAPI"
)


# ---------------------------------------------------------------------------
# Isolation
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
        "GOOGLE_REDIRECT_URI",
        "MS_CLIENT_ID",
        "MS_CLIENT_SECRET",
        "MS_TENANT_ID",
        "MS_REDIRECT_URI",
        "ONEDRIVE_CLIENT_ID",
        "ONEDRIVE_TENANT_ID",
    ):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setattr(
        machine_secrets, "get_machine_secrets_path", lambda: str(store_path)
    )
    # Reversible stand-ins for CryptProtectData / CryptUnprotectData: the store
    # stays opaque on disk without requiring the running Windows account.
    monkeypatch.setattr(machine_secrets, "_protect_bytes", lambda value: b"p:" + value[::-1])
    monkeypatch.setattr(
        machine_secrets, "_unprotect_bytes", lambda value: value[len(b"p:") :][::-1]
    )
    return store_path


@pytest.fixture()
def admin_client():
    client = main.app.test_client()
    response = client.post(
        "/login",
        data={"email": "admin@ej.edu.br", "senha": "admin123"},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    return client


def _seed(provider: str, values: dict[str, str], *, public_base_url: str | None = None):
    machine_secrets.update_machine_oauth_configuration(
        provider=provider, values=values, public_base_url=public_base_url
    )


def _stored(provider: str) -> dict[str, str]:
    payload = machine_secrets.load_machine_secrets()
    return dict(payload.get("providers", {}).get(provider) or {})


def _runtime() -> dict[str, str]:
    return dict(machine_secrets.load_machine_secrets().get("runtime") or {})


def _post(client, data, *, follow=True):
    return client.post(DRIVE_SETTINGS_URL, data=data, follow_redirects=follow)


def _set_drive_settings(values: dict[str, str]) -> None:
    with main.app.app_context():
        conn = main.get_db_connection()
        banco_dados_view._save_drive_config(conn, values)
        conn.commit()


def _read_drive_settings() -> dict[str, str]:
    with main.app.app_context():
        conn = main.get_db_connection()
        return dict(get_drive_settings(conn))


# ---------------------------------------------------------------------------
# 1-2. Provider credential saves
# ---------------------------------------------------------------------------


def test_google_credential_save_persists_only_to_the_machine_store(
    machine_store, admin_client
):
    response = _post(
        admin_client,
        {
            "provider": "google",
            "action": "save_credentials",
            "client_id": "google-client-id",
            "client_secret": GOOGLE_SECRET,
        },
    )

    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "Credenciais do Google Drive salvas com segurança nesta máquina." in page

    assert _stored("google") == {
        "client_id": "google-client-id",
        "client_secret": GOOGLE_SECRET,
    }
    assert cloud_config.get_application_credential_status("google") == {
        "provider": "google",
        "configured": True,
        "source": "MACHINE_LOCAL_DPAPI",
    }

    # The credential never becomes operational data.
    assert GOOGLE_SECRET.encode("utf-8") not in machine_store.read_bytes()
    with main.app.app_context():
        database_path = main.app.config["DATABASE_PATH"]
    assert GOOGLE_SECRET.encode("utf-8") not in Path(database_path).read_bytes()


def test_onedrive_credential_save_requires_and_persists_the_tenant(
    machine_store, admin_client
):
    incomplete = _post(
        admin_client,
        {
            "provider": "onedrive",
            "action": "save_credentials",
            "client_id": "onedrive-client-id",
            "client_secret": ONEDRIVE_SECRET,
            "tenant_id": "",
        },
    )
    assert "ID do diretório (tenant)" in incomplete.get_data(as_text=True)
    assert _stored("onedrive") == {}

    response = _post(
        admin_client,
        {
            "provider": "onedrive",
            "action": "save_credentials",
            "client_id": "onedrive-client-id",
            "client_secret": ONEDRIVE_SECRET,
            "tenant_id": "tenant-uuid",
        },
    )

    assert "Credenciais do OneDrive salvas com segurança nesta máquina." in (
        response.get_data(as_text=True)
    )
    assert _stored("onedrive") == {
        "client_id": "onedrive-client-id",
        "client_secret": ONEDRIVE_SECRET,
        "tenant_id": "tenant-uuid",
    }


# ---------------------------------------------------------------------------
# 3. Blank secret preserves the stored one
# ---------------------------------------------------------------------------


def test_blank_client_secret_preserves_the_stored_secret(machine_store, admin_client):
    _seed("google", {"client_id": "original-client", "client_secret": GOOGLE_SECRET})

    response = _post(
        admin_client,
        {
            "provider": "google",
            "action": "save_credentials",
            "client_id": "rotated-client",
            "client_secret": "",
        },
    )

    assert "Credenciais do Google Drive salvas" in response.get_data(as_text=True)
    stored = _stored("google")
    assert stored["client_id"] == "rotated-client"
    assert stored["client_secret"] == GOOGLE_SECRET


def test_blank_secret_is_omitted_rather_than_submitted_as_empty(monkeypatch, machine_store):
    _seed("google", {"client_id": "c", "client_secret": GOOGLE_SECRET})
    submitted: list[dict] = []
    monkeypatch.setattr(
        cloud_credentials,
        "update_machine_oauth_configuration",
        lambda **kwargs: submitted.append(kwargs),
    )

    cloud_credentials.save_application_credentials(
        provider="google", client_id="c", client_secret="   "
    )

    assert submitted == [
        {
            "provider": "google",
            "values": {"client_id": "c"},
            "public_base_url": None,
        }
    ]
    assert "client_secret" not in submitted[0]["values"]


def test_blank_secret_without_a_stored_one_is_refused(machine_store):
    with pytest.raises(cloud_credentials.CloudCredentialsError) as captured:
        cloud_credentials.save_application_credentials(
            provider="google", client_id="c", client_secret=""
        )
    assert "chave secreta" in str(captured.value)
    assert _stored("google") == {}


# ---------------------------------------------------------------------------
# 4. The secret is never rendered
# ---------------------------------------------------------------------------


def test_stored_client_secret_is_never_rendered_into_the_page(
    machine_store, admin_client
):
    _seed("google", {"client_id": "google-client-id", "client_secret": GOOGLE_SECRET})
    _seed(
        "onedrive",
        {
            "client_id": "onedrive-client-id",
            "client_secret": ONEDRIVE_SECRET,
            "tenant_id": "tenant-uuid",
        },
    )

    page = admin_client.get("/admin/banco-dados").get_data(as_text=True)

    assert GOOGLE_SECRET not in page
    assert ONEDRIVE_SECRET not in page
    # The identifiers may be prefilled; the secrets are always empty inputs.
    assert 'value="google-client-id"' in page
    assert 'value="tenant-uuid"' in page
    assert 'id="google_client_secret" type="password" name="client_secret" value=""' in page
    assert 'id="onedrive_client_secret" type="password" name="client_secret" value=""' in page


# ---------------------------------------------------------------------------
# 5. Provider isolation
# ---------------------------------------------------------------------------


def test_provider_saves_cannot_modify_the_other_provider(machine_store, admin_client):
    _seed("google", {"client_id": "google-client-id", "client_secret": GOOGLE_SECRET})
    _seed(
        "onedrive",
        {
            "client_id": "onedrive-client-id",
            "client_secret": ONEDRIVE_SECRET,
            "tenant_id": "tenant-uuid",
        },
    )
    google_before = _stored("google")
    onedrive_before = _stored("onedrive")

    _post(
        admin_client,
        {
            "provider": "google",
            "action": "save_credentials",
            "client_id": "google-rotated",
            "client_secret": "google-rotated-secret",
        },
    )
    assert _stored("onedrive") == onedrive_before

    _post(
        admin_client,
        {
            "provider": "onedrive",
            "action": "save_credentials",
            "client_id": "onedrive-rotated",
            "client_secret": "onedrive-rotated-secret",
            "tenant_id": "tenant-rotated",
        },
    )
    assert _stored("google") == {
        "client_id": "google-rotated",
        "client_secret": "google-rotated-secret",
    }
    assert google_before["client_secret"] == GOOGLE_SECRET


# ---------------------------------------------------------------------------
# 6. The shared public address is independent
# ---------------------------------------------------------------------------


def test_public_base_url_saves_without_touching_provider_credentials(
    machine_store, admin_client
):
    _seed("google", {"client_id": "google-client-id", "client_secret": GOOGLE_SECRET})
    _seed(
        "onedrive",
        {
            "client_id": "onedrive-client-id",
            "client_secret": ONEDRIVE_SECRET,
            "tenant_id": "tenant-uuid",
        },
    )
    google_before = _stored("google")
    onedrive_before = _stored("onedrive")

    response = _post(
        admin_client,
        {
            "action": "save_public_base_url",
            "app_public_base_url": "https://sgaa.example.br/",
        },
    )

    assert "Endereço público OAuth salvo." in response.get_data(as_text=True)
    assert _runtime()["public_base_url"] == "https://sgaa.example.br"
    assert cloud_config.get_public_base_url_setting() == "https://sgaa.example.br"
    assert _stored("google") == google_before
    assert _stored("onedrive") == onedrive_before


def test_provider_credential_save_does_not_erase_the_public_base_url(
    machine_store, admin_client
):
    _seed("google", {"client_id": "c", "client_secret": GOOGLE_SECRET},
          public_base_url="https://sgaa.example.br")
    assert _runtime()["public_base_url"] == "https://sgaa.example.br"

    _post(
        admin_client,
        {
            "provider": "google",
            "action": "save_credentials",
            "client_id": "c2",
            "client_secret": "",
        },
    )

    assert _runtime()["public_base_url"] == "https://sgaa.example.br"


def test_invalid_public_base_url_is_refused_without_writing(machine_store, admin_client):
    _seed("google", {"client_id": "c", "client_secret": GOOGLE_SECRET},
          public_base_url="https://sgaa.example.br")

    for candidate in ("", "not-a-url", "http://remote.example", "https://x.example/path"):
        response = _post(
            admin_client,
            {"action": "save_public_base_url", "app_public_base_url": candidate},
        )
        assert response.status_code == 200
        assert _runtime()["public_base_url"] == "https://sgaa.example.br"


# ---------------------------------------------------------------------------
# 7. The credential actions return before the destination-settings tail
# ---------------------------------------------------------------------------


def test_credential_actions_leave_destination_settings_untouched(
    machine_store, admin_client
):
    _set_drive_settings(
        {
            "gdrive_dest_folder": "Backups/preservado",
            "gdrive_enabled": "1",
            "onedrive_dest_folder": "OneDrive/preservado",
            "onedrive_enabled": "1",
        }
    )
    before = _read_drive_settings()

    for payload in (
        {
            "provider": "google",
            "action": "save_credentials",
            "client_id": "google-client-id",
            "client_secret": GOOGLE_SECRET,
        },
        {
            "provider": "onedrive",
            "action": "save_credentials",
            "client_id": "onedrive-client-id",
            "client_secret": ONEDRIVE_SECRET,
            "tenant_id": "tenant-uuid",
        },
        {
            "action": "save_public_base_url",
            "app_public_base_url": "http://localhost:5000",
        },
    ):
        _post(admin_client, payload)
        after = _read_drive_settings()
        for key in (
            "gdrive_dest_folder",
            "gdrive_enabled",
            "onedrive_dest_folder",
            "onedrive_enabled",
        ):
            assert after[key] == before[key], f"{payload.get('action')} changed {key}"

    # The destination tail itself is untouched by this increment.
    tail = _post(
        admin_client,
        {"provider": "google", "gdrive_dest_folder": "Backups/novo", "gdrive_enabled": "1"},
    )
    assert "Configurações de destino em nuvem salvas." in tail.get_data(as_text=True)
    assert _read_drive_settings()["gdrive_dest_folder"] == "Backups/novo"


# ---------------------------------------------------------------------------
# 7b. The provider card saves its whole editable configuration in one POST
# ---------------------------------------------------------------------------


def _google_card_payload(**overrides) -> dict:
    payload = {
        "provider": "google",
        "action": "save_credentials",
        "app_public_base_url": "http://localhost:5000",
        "client_id": "google-client-id",
        "client_secret": GOOGLE_SECRET,
        "gdrive_dest_folder": "Backups/sistema",
    }
    payload.update(overrides)
    return payload


def test_card_save_writes_credentials_and_the_shared_address_together(
    machine_store, admin_client
):
    response = _post(
        admin_client,
        _google_card_payload(app_public_base_url="https://sgaa.example.br/"),
    )

    assert "Credenciais do Google Drive salvas" in response.get_data(as_text=True)
    assert _stored("google") == {
        "client_id": "google-client-id",
        "client_secret": GOOGLE_SECRET,
    }
    assert _runtime()["public_base_url"] == "https://sgaa.example.br"
    assert _read_drive_settings()["gdrive_dest_folder"] == "Backups/sistema"


def test_either_card_updates_the_one_shared_address_without_the_other_provider(
    machine_store, admin_client
):
    _seed("google", {"client_id": "google-client-id", "client_secret": GOOGLE_SECRET})
    _seed(
        "onedrive",
        {
            "client_id": "onedrive-client-id",
            "client_secret": ONEDRIVE_SECRET,
            "tenant_id": "tenant-uuid",
        },
    )
    onedrive_before = _stored("onedrive")

    _post(admin_client, _google_card_payload(app_public_base_url="https://from-google.example.br"))
    assert _runtime()["public_base_url"] == "https://from-google.example.br"
    assert _stored("onedrive") == onedrive_before

    google_before = _stored("google")
    _post(
        admin_client,
        {
            "provider": "onedrive",
            "action": "save_credentials",
            "app_public_base_url": "https://from-onedrive.example.br",
            "client_id": "onedrive-client-id",
            "client_secret": "",
            "tenant_id": "tenant-uuid",
        },
    )
    assert _runtime()["public_base_url"] == "https://from-onedrive.example.br"
    assert _stored("google") == google_before
    # Still one canonical value, not a per-provider copy.
    assert cloud_config.get_public_base_url_setting() == "https://from-onedrive.example.br"


def test_card_save_with_a_blank_secret_still_preserves_the_stored_one(
    machine_store, admin_client
):
    _seed("google", {"client_id": "original", "client_secret": GOOGLE_SECRET},
          public_base_url="http://localhost:5000")

    _post(admin_client, _google_card_payload(client_id="rotated", client_secret=""))

    assert _stored("google") == {
        "client_id": "rotated",
        "client_secret": GOOGLE_SECRET,
    }


def test_card_save_with_an_invalid_address_writes_nothing(machine_store, admin_client):
    _seed("google", {"client_id": "original", "client_secret": GOOGLE_SECRET},
          public_base_url="https://sgaa.example.br")
    before = _stored("google")

    response = _post(
        admin_client,
        _google_card_payload(
            client_id="rotated",
            client_secret="rotated-secret",
            app_public_base_url="https://x.example/path",
        ),
    )

    assert response.status_code == 200
    assert "Credenciais do Google Drive salvas" not in response.get_data(as_text=True)
    assert _stored("google") == before
    assert _runtime()["public_base_url"] == "https://sgaa.example.br"


def test_card_save_preserves_the_non_editable_automatic_backup_flag(
    machine_store, admin_client
):
    """The switch is not editable yet, so a card save must not reset it to 0."""
    _set_drive_settings({"gdrive_enabled": "1", "gdrive_dest_folder": "Backups/preservado"})

    _post(admin_client, _google_card_payload(gdrive_dest_folder="Backups/preservado"))

    settings = _read_drive_settings()
    assert settings["gdrive_enabled"] == "1"
    assert settings["gdrive_dest_folder"] == "Backups/preservado"


def test_card_save_writes_the_flag_only_when_the_card_declares_it_editable(
    machine_store, admin_client
):
    _set_drive_settings({"gdrive_enabled": "1"})

    # Declared editable and unchecked -> the decision is honoured.
    _post(
        admin_client,
        _google_card_payload(gdrive_enabled_submitted="1"),
    )
    assert _read_drive_settings()["gdrive_enabled"] == "0"

    _post(
        admin_client,
        _google_card_payload(gdrive_enabled_submitted="1", gdrive_enabled="1"),
    )
    assert _read_drive_settings()["gdrive_enabled"] == "1"


def test_card_save_never_resets_a_folder_it_did_not_carry(machine_store, admin_client):
    _set_drive_settings({"gdrive_dest_folder": "Backups/escolhido"})

    _post(admin_client, _google_card_payload(gdrive_dest_folder="   "))

    assert _read_drive_settings()["gdrive_dest_folder"] == "Backups/escolhido"


# ---------------------------------------------------------------------------
# 8. Missing store is a normal first-configuration flow
# ---------------------------------------------------------------------------


def test_missing_store_is_created_by_a_normal_first_save(machine_store, admin_client):
    assert not machine_store.exists()

    page = admin_client.get("/admin/banco-dados").get_data(as_text=True)
    assert page.count('value="save_credentials"') == 2
    assert "Credenciais do aplicativo: ausentes" in page

    response = _post(
        admin_client,
        {
            "provider": "google",
            "action": "save_credentials",
            "client_id": "google-client-id",
            "client_secret": GOOGLE_SECRET,
        },
    )

    assert "Credenciais do Google Drive salvas" in response.get_data(as_text=True)
    assert machine_store.is_file()


def test_public_base_url_first_creates_a_store_that_is_never_keyless(
    machine_store, admin_client
):
    """Recovery order is the administrator's: address first is legitimate.

    Store invariant: if a store exists after a normal product operation, the
    canonical token-encryption infrastructure exists with it.  A keyless store
    is not a state this product may leave behind.
    """
    assert not machine_store.exists()

    response = _post(
        admin_client,
        {"action": "save_public_base_url", "app_public_base_url": "http://localhost:5000"},
    )

    assert "Endereço público OAuth salvo." in response.get_data(as_text=True)
    assert machine_store.is_file()
    payload = machine_secrets.load_machine_secrets()
    assert payload["runtime"]["public_base_url"] == "http://localhost:5000"
    assert payload["providers"] == {}
    key = payload["runtime"]["token_encryption_key"]
    assert key
    Fernet(key.encode("utf-8"))  # a usable key, minted by the canonical owner

    # The following credential save reuses that key rather than re-minting.
    _post(
        admin_client,
        {
            "provider": "google",
            "action": "save_credentials",
            "client_id": "google-client-id",
            "client_secret": GOOGLE_SECRET,
        },
    )
    after = machine_secrets.load_machine_secrets()
    assert after["runtime"]["token_encryption_key"] == key
    assert after["runtime"]["public_base_url"] == "http://localhost:5000"


def test_address_save_preserves_an_existing_key_and_provider_credentials(
    machine_store, admin_client
):
    _seed("google", {"client_id": "google-client-id", "client_secret": GOOGLE_SECRET})
    _seed(
        "onedrive",
        {
            "client_id": "onedrive-client-id",
            "client_secret": ONEDRIVE_SECRET,
            "tenant_id": "tenant-uuid",
        },
    )
    before = machine_secrets.load_machine_secrets()
    key_before = before["runtime"]["token_encryption_key"]
    assert key_before

    _post(
        admin_client,
        {"action": "save_public_base_url", "app_public_base_url": "https://sgaa.example.br"},
    )

    after = machine_secrets.load_machine_secrets()
    assert after["runtime"]["token_encryption_key"] == key_before
    assert after["providers"] == before["providers"]
    assert after["runtime"]["public_base_url"] == "https://sgaa.example.br"


def test_address_save_defers_to_an_environment_supplied_key(
    machine_store, admin_client, monkeypatch
):
    """A legacy env key is authoritative; the store must not shadow it."""
    legacy = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", legacy)
    assert not machine_store.exists()

    _post(
        admin_client,
        {"action": "save_public_base_url", "app_public_base_url": "http://localhost:5000"},
    )

    payload = machine_secrets.load_machine_secrets()
    assert payload["runtime"]["public_base_url"] == "http://localhost:5000"
    assert "token_encryption_key" not in payload["runtime"]
    assert token_encryption.get_token_encryption_key() == legacy


def test_machine_secret_creation_stays_behind_the_canonical_preflight():
    """This module makes the bootstrap run; it never mints a key itself."""
    source = CREDENTIALS_MODULE_PATH.read_text(encoding="utf-8-sig")
    tree = ast.parse(source)

    called = {
        getattr(node.func, "attr", None) or getattr(node.func, "id", None)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    assert "run_startup_preflight" in called
    assert "ensure_machine_secret_infrastructure" not in called
    assert "get_machine_token_encryption_key" not in called
    assert "generate_token_encryption_key" not in called
    assert "Fernet" not in source


# ---------------------------------------------------------------------------
# 9-10. An existing but unopenable store fails closed and is never repaired
# ---------------------------------------------------------------------------


def _corrupt_store(store_path: Path) -> bytes:
    store_path.parent.mkdir(parents=True, exist_ok=True)
    original = b"this-is-not-a-valid-store-payload-\x00\xff"
    store_path.write_bytes(original)
    return original


def _foreign_account_store(store_path: Path, monkeypatch) -> bytes:
    """A well-formed store that the current Windows account cannot open."""
    store_path.parent.mkdir(parents=True, exist_ok=True)
    original = base64.b64encode(b"protected-by-another-windows-account")
    store_path.write_bytes(original)

    def _refuse(payload: bytes) -> bytes:
        raise machine_secrets.MachineSecretsError(
            "As conexoes de nuvem desta instalacao pertencem a outra conta Windows. "
            "Entre com a conta Windows usada na instalacao ou reconecte o provedor.",
            debug_detail="CryptUnprotectData falhou para a conta Windows atual",
        )

    monkeypatch.setattr(machine_secrets, "_unprotect_bytes", _refuse)
    return original


@pytest.mark.parametrize("flavour", ["corrupt", "foreign-windows-account"])
def test_unopenable_store_fails_closed_and_is_left_byte_identical(
    machine_store, admin_client, monkeypatch, flavour
):
    if flavour == "corrupt":
        original = _corrupt_store(machine_store)
    else:
        original = _foreign_account_store(machine_store, monkeypatch)
    mtime_before = machine_store.stat().st_mtime_ns

    for payload in (
        {
            "provider": "google",
            "action": "save_credentials",
            "client_id": "google-client-id",
            "client_secret": GOOGLE_SECRET,
        },
        {
            "provider": "onedrive",
            "action": "save_credentials",
            "client_id": "onedrive-client-id",
            "client_secret": ONEDRIVE_SECRET,
            "tenant_id": "tenant-uuid",
        },
        {
            "action": "save_public_base_url",
            "app_public_base_url": "http://localhost:5000",
        },
    ):
        response = _post(admin_client, payload)
        assert response.status_code == 200
        body = response.get_data(as_text=True)
        assert "Credenciais do Google Drive salvas" not in body
        assert "Credenciais do OneDrive salvas" not in body
        assert "Endereço público OAuth salvo." not in body
        for term in FORBIDDEN_UI_TERMS:
            assert term not in body, f"{payload.get('action')} leaked {term!r}"

    # Nothing was deleted, renamed, overwritten, recreated or re-keyed.
    assert machine_store.read_bytes() == original
    assert machine_store.stat().st_mtime_ns == mtime_before
    assert sorted(p.name for p in machine_store.parent.iterdir()) == [machine_store.name]


def test_unopenable_store_renders_a_sanitized_product_state(
    machine_store, admin_client, monkeypatch
):
    _foreign_account_store(machine_store, monkeypatch)

    response = admin_client.get("/admin/banco-dados")

    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "O armazenamento seguro desta máquina não pôde ser aberto." in page
    assert "Nada foi apagado" in page
    assert 'value="save_credentials"' not in page
    for term in FORBIDDEN_UI_TERMS:
        assert term not in page


def test_credential_module_has_no_store_reinitialization_branch():
    """There must be no `except MachineSecretsError: delete/recreate` anywhere."""
    tree = ast.parse(CREDENTIALS_MODULE_PATH.read_text(encoding="utf-8-sig"))
    destructive = {
        "remove",
        "unlink",
        "rename",
        "replace",
        "rmtree",
        "truncate",
        "generate_token_encryption_key",
        "save_machine_secrets",
        "update_machine_oauth_configuration",
    }

    handlers = [
        node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler)
    ]
    assert handlers, "the module must still translate store failures"
    for handler in handlers:
        for node in ast.walk(handler):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            assert name not in destructive, (
                f"except-handler at line {handler.lineno} performs {name!r}: an "
                "unopenable store must never be repaired or rewritten"
            )

    source = CREDENTIALS_MODULE_PATH.read_text(encoding="utf-8-sig")
    for forbidden in ("os.remove", "os.unlink", "os.rename", "shutil.", "Fernet"):
        assert forbidden not in source


# ---------------------------------------------------------------------------
# 11. No submitted secret reaches the response, the flash text or a log
# ---------------------------------------------------------------------------


def test_submitted_secret_never_reaches_response_flash_or_log(
    machine_store, admin_client, caplog
):
    probe = "submitted-secret-probe-9c1f"

    with caplog.at_level(logging.DEBUG):
        ok = _post(
            admin_client,
            {
                "provider": "google",
                "action": "save_credentials",
                "client_id": "google-client-id",
                "client_secret": probe,
            },
        )
        # ...and again on a rejected save, where an error message is produced.
        rejected = _post(
            admin_client,
            {
                "provider": "onedrive",
                "action": "save_credentials",
                "client_id": "",
                "client_secret": probe,
                "tenant_id": "",
            },
        )

    assert probe not in ok.get_data(as_text=True)
    assert probe not in rejected.get_data(as_text=True)
    assert probe not in caplog.text
    assert not any(probe in str(record.args or "") for record in caplog.records)
    assert _stored("google")["client_secret"] == probe


# ---------------------------------------------------------------------------
# 12-13. The ordinary UI: no manual setup, four provider actions intact
# ---------------------------------------------------------------------------


def test_ordinary_ui_carries_no_manual_setup_instruction(machine_store, admin_client):
    template = TEMPLATE_PATH.read_text(encoding="utf-8-sig")
    for term in FORBIDDEN_TEMPLATE_TERMS:
        assert term not in template, f"template carries {term!r}"

    page = admin_client.get("/admin/banco-dados").get_data(as_text=True)
    for term in FORBIDDEN_UI_TERMS:
        assert term not in page, f"rendered page carries {term!r}"
    assert "Deixe em branco para manter a chave atual." in page
    # The separate technical OAuth panel and its manual-setup prose are gone:
    # the provider cards are now the whole configuration surface.
    for retired in (
        "Configuração técnica OAuth",
        "Cadastre este callback no Google Cloud.",
        "Google callback:",
        "OneDrive callback:",
        "Depois de salvar as credenciais",
        "Endereço público do sistema",
        "Situação atual:",
    ):
        assert retired not in page, f"retired technical text survives: {retired!r}"
    # The hint about preserving the stored secret is helper text, never a
    # placeholder rendered inside the password input.
    assert "Manter a atual" not in page


def test_each_provider_card_owns_its_whole_configuration_form():
    """One card, one non-nested form, one Salvar -- and no panel beside them."""
    template = TEMPLATE_PATH.read_text(encoding="utf-8-sig")

    for retired in ("db-oauth-meta", "db-oauth-config", "save_public_base_url"):
        assert retired not in template, f"template still carries {retired!r}"

    cards = template.split('<section class="db-provider-card">')[1:]
    assert len(cards) == 2
    assert template.count('<div class="db-provider-secondary">') == 2

    for card, prefix in zip(cards, ("gdrive", "onedrive")):
        actions, marker, tail = card.partition(
            '<form method="post" action="{{ url_for(\'admin_banco_dados_drive_settings\') }}"'
            ' class="db-provider-config">'
        )
        assert marker, f"{prefix} card must own a configuration form"

        # The pinned provider actions still come first and stay credential-free.
        assert '<div class="db-provider-secondary">' in actions
        assert "save_credentials" not in actions
        assert 'name="client_id"' not in actions
        assert 'name="app_public_base_url"' not in actions

        config_form = tail.split("</form>", 1)[0]
        assert 'name="csrf_token" value="{{ csrf_token() }}"' in config_form
        assert config_form.count('name="action" value="save_credentials"') == 1
        assert f'name="provider" value="{"google" if prefix == "gdrive" else "onedrive"}"' in (
            config_form
        )
        # Everything the card represents travels in that one submission.
        for field in ("app_public_base_url", "client_id", "client_secret"):
            assert f'name="{field}"' in config_form, f"{prefix} card lost {field}"
        assert f'name="{prefix}_dest_folder"' in config_form
        assert f'name="{prefix}_enabled"' in config_form
        # Exactly one Salvar, and no nested form.
        assert config_form.count("<form") == 0
        assert config_form.count('type="submit"') == 1
        assert config_form.count("db-provider-config-footer") == 1

    google_form, onedrive_form = (
        card.split('class="db-provider-config">', 1)[1].split("</form>", 1)[0]
        for card in cards
    )
    assert 'name="tenant_id"' not in google_form
    assert 'name="tenant_id"' in onedrive_form


def test_both_cards_report_their_own_credential_source(machine_store, admin_client):
    """Symmetric cards: each reports its own state, neither hardcodes it."""
    _seed("google", {"client_id": "g", "client_secret": GOOGLE_SECRET})

    page = admin_client.get("/admin/banco-dados").get_data(as_text=True)

    cards = page.split('<section class="db-provider-card">')[1:]
    assert len(cards) == 2
    google_card, onedrive_card = cards
    # Google is configured, OneDrive is not -- the same line, different truth.
    assert (
        "Credenciais do aplicativo: configuração segura desta máquina" in google_card
    )
    assert "Credenciais do aplicativo: ausentes" in onedrive_card

    _seed(
        "onedrive",
        {
            "client_id": "onedrive-client-id",
            "client_secret": ONEDRIVE_SECRET,
            "tenant_id": "tenant-uuid",
        },
    )
    onedrive_card = admin_client.get("/admin/banco-dados").get_data(as_text=True).split(
        '<section class="db-provider-card">'
    )[2]
    assert (
        "Credenciais do aplicativo: configuração segura desta máquina" in onedrive_card
    )


def test_both_cards_render_one_canonical_public_base_url(machine_store, admin_client):
    """The shared address may appear twice; it is still a single value."""
    _seed("google", {"client_id": "g", "client_secret": GOOGLE_SECRET},
          public_base_url="https://sgaa.example.br")

    page = admin_client.get("/admin/banco-dados").get_data(as_text=True)

    for element_id in ("google_app_public_base_url", "onedrive_app_public_base_url"):
        assert (
            f'id="{element_id}" class="db-path-input" type="url" '
            'name="app_public_base_url" value="https://sgaa.example.br"'
        ) in page, f"{element_id} does not render the canonical address"


def test_reconnect_remains_a_separate_action_after_configuring(
    machine_store, admin_client
):
    _seed("google", {"client_id": "google-client-id", "client_secret": GOOGLE_SECRET})

    page = admin_client.get("/admin/banco-dados").get_data(as_text=True)

    assert 'href="/admin/backup/google/connect"' in page
    assert 'href="/admin/backup/onedrive/connect"' not in page or "Conectar" in page
    # Connect stays a link outside the configuration form, so a card save can
    # never double as an authorization.
    template = TEMPLATE_PATH.read_text(encoding="utf-8-sig")
    for card in template.split('<section class="db-provider-card">')[1:]:
        config_form = card.split('class="db-provider-config">', 1)[1].split(
            "</form>", 1
        )[0]
        assert "connect" not in config_form
        assert "oauth_disconnect" not in config_form
        assert "cloud-folder" not in config_form
        assert "test_connection" not in config_form
    # Saving credentials alone must not fabricate an authorization.
    with main.app.app_context():
        conn = main.get_db_connection()
        from app.db import ensure_cloud_backup_schema

        ensure_cloud_backup_schema(conn)
        active = conn.execute(
            "SELECT COUNT(*) FROM cloud_accounts WHERE provider = 'google' AND active = 1"
        ).fetchone()[0]
    assert active == 0


# ---------------------------------------------------------------------------
# 14. Activity CRUD is independent of cloud availability
# ---------------------------------------------------------------------------


def test_activity_crud_survives_an_unopenable_machine_store(
    machine_store, admin_client, monkeypatch
):
    _foreign_account_store(machine_store, monkeypatch)

    listing = admin_client.get("/admin/atividades")
    creator = admin_client.get("/admin/adicionar_atividade")
    created = admin_client.post(
        "/admin/adicionar_atividade",
        data={
            "tipo_atividade": "Acadêmica Complementar",
            "grupo": "1 - Eventos",
            "nome": "Atividade independente de nuvem",
            "descricao": "criada com o armazenamento seguro indisponível",
            "tipo_limitacao": "",
            "limite_valor": "",
            "ch_por_evento_mode": "disabled",
            "observacoes": "",
        },
        follow_redirects=True,
    )

    for response in (listing, creator, created):
        assert response.status_code == 200
        body = response.get_data(as_text=True)
        for term in FORBIDDEN_UI_TERMS:
            assert term not in body

    with main.app.app_context():
        conn = main.get_db_connection()
        assert conn.execute(
            "SELECT COUNT(*) FROM atividade_base WHERE nome_conceito = ?",
            ("Atividade independente de nuvem",),
        ).fetchone()[0] == 1


# ---------------------------------------------------------------------------
# Route / RBAC / CSRF surface is unchanged
# ---------------------------------------------------------------------------


def test_no_new_route_rbac_or_csrf_surface_was_added():
    from app.auth import get_admin_permission_requirement
    from tests.canonical_baseline_support import (
        assert_csrf_snapshot_matches_canonical_baseline,
        assert_live_route_surface_matches_canonical_baseline,
        load_csrf_snapshot,
        CSRF_OFF_ARTIFACT,
    )

    assert_live_route_surface_matches_canonical_baseline(
        context="cloud credential recovery"
    )
    assert_csrf_snapshot_matches_canonical_baseline(
        load_csrf_snapshot(CSRF_OFF_ARTIFACT), context="cloud credential recovery"
    )
    assert get_admin_permission_requirement(
        "admin_banco_dados_drive_settings", "POST"
    ) == ("banco_dados", "edit")
