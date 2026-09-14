"""Google Picker configuration is owned by the machine-local store.

The OAuth migration moved Google's ``client_id``/``client_secret`` into the
DPAPI-protected machine store but left the two Picker values --
``GOOGLE_PICKER_API_KEY`` and ``GOOGLE_APP_ID`` -- resolved straight from
``os.environ`` by the Banco de Dados view.  A Google account could therefore
report "Conectado" while "Selecionar pasta" was permanently unusable, because
nothing in the product could supply those two values any more.

These tests pin the completed model: one authoritative resolver
(``cloud_config.get_google_picker_config``) with the machine store first and the
legacy environment second, one save action (the existing Google card), and a
Picker API key that reaches the page only where the Picker runtime needs it.

Isolation mirrors ``test_cloud_credentials_product_recovery``: the store path,
``LOCALAPPDATA`` and the DPAPI primitives are all redirected, so the developer's
real ``%LOCALAPPDATA%\\SGAA\\secrets`` store is never read for content nor
written.  No test ever asserts a real credential.
"""

from __future__ import annotations

import ast
import logging
import re
from pathlib import Path

import pytest

import main
from app import cloud_config, cloud_credentials, machine_secrets
from app.views.admin import banco_dados as banco_dados_view


PROJECT_ROOT = Path(__file__).resolve().parent.parent
VIEW_PATH = PROJECT_ROOT / "app" / "views" / "admin" / "banco_dados.py"

DRIVE_SETTINGS_URL = "/admin/banco-dados/drive-settings"

# Synthetic throughout: never a real Google key.
GOOGLE_SECRET = "google-application-secret-never-rendered"
STORED_PICKER_KEY = "stored-picker-api-key-never-rendered"
ENV_PICKER_KEY = "environment-picker-api-key-never-rendered"
STORED_APP_ID = "111122223333"
ENV_APP_ID = "999988887777"


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
        "GOOGLE_PICKER_API_KEY",
        "GOOGLE_APP_ID",
        "GOOGLE_REDIRECT_URI",
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


def _seed(provider: str, values: dict[str, str]):
    machine_secrets.update_machine_oauth_configuration(
        provider=provider, values=values, public_base_url=None
    )


def _stored(provider: str) -> dict[str, str]:
    payload = machine_secrets.load_machine_secrets()
    return dict(payload.get("providers", {}).get(provider) or {})


def _post(client, data, *, follow=True):
    return client.post(DRIVE_SETTINGS_URL, data=data, follow_redirects=follow)


def _seed_google_credentials():
    _seed("google", {"client_id": "google-client-id", "client_secret": GOOGLE_SECRET})


def _connect_google(monkeypatch):
    """Present a connected Google account without minting a real token."""
    account = {
        "account_email": "dono@ej.edu.br",
        "token_json_available": True,
    }
    monkeypatch.setattr(
        banco_dados_view,
        "_get_active_cloud_account",
        lambda conn, provider: account if provider == "google" else None,
    )


def _context():
    with main.app.app_context():
        conn = main.get_db_connection()
        return banco_dados_view._build_database_admin_context(conn)


def _rendered_form_values(page: str) -> list[str]:
    return re.findall(r'value="([^"]*)"', page)


# ---------------------------------------------------------------------------
# 1-2. Resolution order: machine store first, legacy environment second
# ---------------------------------------------------------------------------


def test_stored_picker_values_override_the_legacy_environment(
    machine_store, monkeypatch
):
    monkeypatch.setenv("GOOGLE_PICKER_API_KEY", ENV_PICKER_KEY)
    monkeypatch.setenv("GOOGLE_APP_ID", ENV_APP_ID)
    _seed(
        "google",
        {
            "client_id": "google-client-id",
            "client_secret": GOOGLE_SECRET,
            "picker_api_key": STORED_PICKER_KEY,
            "app_id": STORED_APP_ID,
        },
    )

    resolved = cloud_config.get_google_picker_config()

    assert resolved["api_key"] == STORED_PICKER_KEY
    assert resolved["app_id"] == STORED_APP_ID
    assert resolved["configured"] is True
    assert resolved["source"] == "MACHINE_LOCAL_DPAPI"


def test_environment_remains_the_fallback_when_the_store_has_no_picker_values(
    machine_store, monkeypatch
):
    monkeypatch.setenv("GOOGLE_PICKER_API_KEY", ENV_PICKER_KEY)
    monkeypatch.setenv("GOOGLE_APP_ID", ENV_APP_ID)
    _seed_google_credentials()

    resolved = cloud_config.get_google_picker_config()

    assert resolved["api_key"] == ENV_PICKER_KEY
    assert resolved["app_id"] == ENV_APP_ID
    assert resolved["configured"] is True
    assert resolved["source"] == "ENVIRONMENT"


def test_absent_everywhere_is_reported_as_unconfigured(machine_store):
    _seed_google_credentials()

    resolved = cloud_config.get_google_picker_config()

    assert resolved == {
        "api_key": "",
        "app_id": "",
        "configured": False,
        "source": "ABSENT",
    }


def test_an_unreadable_store_fails_closed_instead_of_falling_back_to_the_environment(
    machine_store, monkeypatch
):
    """The regression this whole change exists to prevent, in reverse.

    A store that cannot be opened must not silently hand the Picker an
    environment key belonging to a different installation.
    """
    monkeypatch.setenv("GOOGLE_PICKER_API_KEY", ENV_PICKER_KEY)
    monkeypatch.setenv("GOOGLE_APP_ID", ENV_APP_ID)
    _seed_google_credentials()

    def _refuse(_payload):
        raise machine_secrets.MachineSecretsError("indisponível", debug_detail="teste")

    monkeypatch.setattr(machine_secrets, "_unprotect_bytes", _refuse)

    assert cloud_config.get_google_picker_config() == {
        "api_key": "",
        "app_id": "",
        "configured": False,
        "source": "ERROR",
    }


# ---------------------------------------------------------------------------
# 3-5. Save semantics of the single Google card action
# ---------------------------------------------------------------------------


def test_blank_picker_api_key_submission_preserves_the_stored_key(
    machine_store, admin_client
):
    _seed(
        "google",
        {
            "client_id": "google-client-id",
            "client_secret": GOOGLE_SECRET,
            "picker_api_key": STORED_PICKER_KEY,
            "app_id": STORED_APP_ID,
        },
    )

    response = _post(
        admin_client,
        {
            "provider": "google",
            "action": "save_credentials",
            "client_id": "google-client-id",
            "client_secret": "",
            "picker_api_key": "",
            "app_id": STORED_APP_ID,
        },
    )

    assert "Credenciais do Google Drive salvas" in response.get_data(as_text=True)
    stored = _stored("google")
    assert stored["picker_api_key"] == STORED_PICKER_KEY
    assert stored["client_secret"] == GOOGLE_SECRET


def test_blank_picker_key_is_omitted_from_the_write_rather_than_sent_as_empty(
    machine_store, monkeypatch
):
    _seed(
        "google",
        {
            "client_id": "c",
            "client_secret": GOOGLE_SECRET,
            "picker_api_key": STORED_PICKER_KEY,
        },
    )
    submitted: list[dict] = []
    monkeypatch.setattr(
        cloud_credentials,
        "update_machine_oauth_configuration",
        lambda **kwargs: submitted.append(kwargs),
    )

    cloud_credentials.save_application_credentials(
        provider="google",
        client_id="c",
        client_secret="",
        picker_api_key="   ",
        app_id=STORED_APP_ID,
    )

    assert submitted[0]["values"] == {"client_id": "c", "app_id": STORED_APP_ID}
    assert "picker_api_key" not in submitted[0]["values"]


def test_a_card_that_does_not_represent_the_picker_fields_leaves_them_untouched(
    machine_store, admin_client
):
    """A credentials-only POST keeps exactly its former semantics."""
    _seed(
        "google",
        {
            "client_id": "google-client-id",
            "client_secret": GOOGLE_SECRET,
            "picker_api_key": STORED_PICKER_KEY,
            "app_id": STORED_APP_ID,
        },
    )

    _post(
        admin_client,
        {
            "provider": "google",
            "action": "save_credentials",
            "client_id": "rotated-client",
            "client_secret": "",
        },
    )

    stored = _stored("google")
    assert stored["client_id"] == "rotated-client"
    assert stored["picker_api_key"] == STORED_PICKER_KEY
    assert stored["app_id"] == STORED_APP_ID


def test_google_app_id_persists_through_the_google_card_save(
    machine_store, admin_client
):
    _seed_google_credentials()

    _post(
        admin_client,
        {
            "provider": "google",
            "action": "save_credentials",
            "client_id": "google-client-id",
            "client_secret": "",
            "picker_api_key": STORED_PICKER_KEY,
            "app_id": STORED_APP_ID,
        },
    )

    assert _stored("google")["app_id"] == STORED_APP_ID
    # And it survives the round trip back into the form.
    page = admin_client.get("/admin/banco-dados").get_data(as_text=True)
    assert f'value="{STORED_APP_ID}"' in page


def test_google_save_does_not_alter_onedrive_configuration(machine_store, admin_client):
    _seed_google_credentials()
    onedrive_before = {
        "client_id": "onedrive-client-id",
        "client_secret": "onedrive-secret-never-rendered",
        "tenant_id": "tenant-uuid",
    }
    _seed("onedrive", onedrive_before)

    _post(
        admin_client,
        {
            "provider": "google",
            "action": "save_credentials",
            "client_id": "google-client-id",
            "client_secret": "",
            "picker_api_key": STORED_PICKER_KEY,
            "app_id": STORED_APP_ID,
        },
    )

    assert _stored("onedrive") == onedrive_before


def test_an_invalid_app_id_leaves_the_google_configuration_unchanged(
    machine_store, admin_client
):
    """No half-write: a rejected field must not land a partial update."""
    before = {
        "client_id": "google-client-id",
        "client_secret": GOOGLE_SECRET,
        "picker_api_key": STORED_PICKER_KEY,
        "app_id": STORED_APP_ID,
    }
    _seed("google", before)

    response = _post(
        admin_client,
        {
            "provider": "google",
            "action": "save_credentials",
            "client_id": "rotated-client",
            "client_secret": "",
            "picker_api_key": "a-brand-new-picker-key",
            "app_id": "1111 2222",  # whitespace is not an identifier
        },
    )

    assert "ID do aplicativo" in response.get_data(as_text=True)
    assert _stored("google") == before


def test_picker_fields_are_refused_on_the_onedrive_card(machine_store):
    _seed("onedrive", {"client_id": "c", "client_secret": "s", "tenant_id": "t"})

    with pytest.raises(cloud_credentials.CloudCredentialsError):
        cloud_credentials.save_application_credentials(
            provider="onedrive",
            client_id="c",
            client_secret="",
            tenant_id="t",
            app_id=STORED_APP_ID,
        )


def test_a_cleared_app_id_box_clears_the_stored_identifier(machine_store, admin_client):
    _seed(
        "google",
        {
            "client_id": "google-client-id",
            "client_secret": GOOGLE_SECRET,
            "picker_api_key": STORED_PICKER_KEY,
            "app_id": STORED_APP_ID,
        },
    )

    _post(
        admin_client,
        {
            "provider": "google",
            "action": "save_credentials",
            "client_id": "google-client-id",
            "client_secret": "",
            "picker_api_key": "",
            "app_id": "",
        },
    )

    stored = _stored("google")
    assert stored["app_id"] == ""
    # Clearing a rendered identifier must not touch the write-only key.
    assert stored["picker_api_key"] == STORED_PICKER_KEY


# ---------------------------------------------------------------------------
# 6. The Picker API key is never rendered, logged or flashed
# ---------------------------------------------------------------------------


def test_the_picker_api_key_never_reaches_a_form_value_a_flash_or_a_log(
    machine_store, admin_client, caplog
):
    _seed_google_credentials()

    with caplog.at_level(logging.DEBUG):
        response = _post(
            admin_client,
            {
                "provider": "google",
                "action": "save_credentials",
                "client_id": "google-client-id",
                "client_secret": "",
                "picker_api_key": STORED_PICKER_KEY,
                "app_id": STORED_APP_ID,
            },
        )

    assert STORED_PICKER_KEY not in caplog.text

    page = response.get_data(as_text=True)
    # The flash confirming the save must not echo the key.
    flash_region = page[: page.find("db-provider-config")] if "db-provider-config" in page else page
    assert STORED_PICKER_KEY not in flash_region
    # No input on the page is prefilled with it.
    assert STORED_PICKER_KEY not in _rendered_form_values(page)
    # It is not operational data either.
    with main.app.app_context():
        database_path = main.app.config["DATABASE_PATH"]
    assert STORED_PICKER_KEY.encode("utf-8") not in Path(database_path).read_bytes()
    assert STORED_PICKER_KEY.encode("utf-8") not in machine_store.read_bytes()


def test_the_picker_key_input_is_always_rendered_empty(machine_store, admin_client):
    _seed(
        "google",
        {
            "client_id": "google-client-id",
            "client_secret": GOOGLE_SECRET,
            "picker_api_key": STORED_PICKER_KEY,
            "app_id": STORED_APP_ID,
        },
    )

    page = admin_client.get("/admin/banco-dados").get_data(as_text=True)

    field = re.search(r'<input id="google_picker_api_key"[^>]*>', page)
    assert field is not None, "the Google card must expose a Picker API key field"
    assert 'type="password"' in field.group(0)
    assert 'value=""' in field.group(0)
    assert STORED_PICKER_KEY not in _rendered_form_values(page)


# ---------------------------------------------------------------------------
# 7-9. Picker runtime state
# ---------------------------------------------------------------------------


def test_google_picker_configured_becomes_true_from_a_dpapi_backed_configuration(
    machine_store
):
    _seed(
        "google",
        {
            "client_id": "google-client-id",
            "client_secret": GOOGLE_SECRET,
            "picker_api_key": STORED_PICKER_KEY,
            "app_id": STORED_APP_ID,
        },
    )

    context = _context()

    assert context["google_picker_configured"] is True
    assert context["google_picker_config_source"] == "MACHINE_LOCAL_DPAPI"
    assert context["google_app_id"] == STORED_APP_ID
    assert context["google_picker_api_key_present"] is True


def test_connected_google_without_picker_config_is_explicit_about_it(
    machine_store, monkeypatch, admin_client
):
    """Connected must stop implying the folder selector is usable."""
    _seed_google_credentials()
    _connect_google(monkeypatch)

    context = _context()
    assert context["gdrive_connected"] is True
    assert context["google_picker_configured"] is False
    assert context["google_picker_config_source"] == "ABSENT"
    assert context["google_picker_api_key_present"] is False

    page = admin_client.get("/admin/banco-dados").get_data(as_text=True)
    assert "data-google-picker-missing" in page
    assert "Seleção de pasta indisponível" in page
    assert 'data-google-picker-configured="false"' in page


def test_the_picker_runtime_receives_the_resolved_values_when_configured(
    machine_store, monkeypatch, admin_client
):
    _seed(
        "google",
        {
            "client_id": "google-client-id",
            "client_secret": GOOGLE_SECRET,
            "picker_api_key": STORED_PICKER_KEY,
            "app_id": STORED_APP_ID,
        },
    )
    _connect_google(monkeypatch)

    page = admin_client.get("/admin/banco-dados").get_data(as_text=True)

    assert f'apiKey: "{STORED_PICKER_KEY}"' in page
    assert f'appId: "{STORED_APP_ID}"' in page
    assert 'clientId: "google-client-id"' in page
    assert "configured: true" in page
    assert 'data-google-picker-configured="true"' in page
    # The key reaches the Picker runtime and nothing else on the page.
    assert page.count(STORED_PICKER_KEY) == 1
    assert "data-google-picker-missing" not in page


def test_environment_only_picker_values_still_drive_the_runtime(
    machine_store, monkeypatch, admin_client
):
    """Legacy installs keep working without editing anything."""
    monkeypatch.setenv("GOOGLE_PICKER_API_KEY", ENV_PICKER_KEY)
    monkeypatch.setenv("GOOGLE_APP_ID", ENV_APP_ID)
    _seed_google_credentials()
    _connect_google(monkeypatch)

    page = admin_client.get("/admin/banco-dados").get_data(as_text=True)

    assert f'apiKey: "{ENV_PICKER_KEY}"' in page
    assert f'appId: "{ENV_APP_ID}"' in page
    assert 'data-google-picker-configured="true"' in page


# ---------------------------------------------------------------------------
# Ownership: the view no longer owns the resolution
# ---------------------------------------------------------------------------


def test_the_view_never_reads_the_picker_variables_from_the_environment():
    """The root cause, pinned.

    ``os.environ``/``os.getenv`` reads of the two Picker variables inside the
    Banco de Dados view are what made a connected Google account unusable once
    configuration moved into the machine store.  The resolver is the only owner.
    """
    tree = ast.parse(VIEW_PATH.read_text(encoding="utf-8"))
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if node.value in {"GOOGLE_PICKER_API_KEY", "GOOGLE_APP_ID"}:
            offenders.append((node.value, node.lineno))

    assert offenders == [], (
        "app/views/admin/banco_dados.py must resolve Picker configuration through "
        f"cloud_config.get_google_picker_config, not the environment: {offenders}"
    )


def test_the_picker_resolver_is_the_single_authoritative_owner():
    source = (PROJECT_ROOT / "app" / "cloud_config.py").read_text(encoding="utf-8")
    assert "GOOGLE_PICKER_API_KEY" in source
    assert "GOOGLE_APP_ID" in source
    # Exactly one module-level resolver, reachable by the view and by tests.
    assert hasattr(cloud_config, "get_google_picker_config")
