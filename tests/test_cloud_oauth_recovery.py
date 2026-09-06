import json
import logging
import sqlite3

import pytest
from cryptography.fernet import Fernet
from flask import Flask
from google.auth.exceptions import RefreshError, TransportError

from app import cloud_config, cloud_connections, machine_secrets
from app.oauth_log_filter import OAuthQueryRedactionFilter
from app.backup import orchestrator
from app.services import google_drive_service
from services import oauth_config, onedrive_service
from tools import configure_cloud_oauth


def test_machine_local_store_is_atomic_and_does_not_contain_plaintext_secret(tmp_path, monkeypatch):
    store_path = tmp_path / "cloud-oauth.dpapi"
    monkeypatch.setattr(machine_secrets, "get_machine_secrets_path", lambda: str(store_path))
    monkeypatch.setattr(machine_secrets, "_protect_bytes", lambda value: b"protected:" + value[::-1])
    monkeypatch.setattr(
        machine_secrets,
        "_unprotect_bytes",
        lambda value: value[len(b"protected:") :][::-1],
    )

    machine_secrets.update_machine_oauth_configuration(
        provider="google",
        values={"client_id": "client-id", "client_secret": "never-print-this-secret"},
        public_base_url="http://localhost:5000",
    )

    stored_bytes = store_path.read_bytes()
    assert b"never-print-this-secret" not in stored_bytes
    payload = machine_secrets.load_machine_secrets()
    assert payload["providers"]["google"]["client_secret"] == "never-print-this-secret"
    assert payload["runtime"]["token_encryption_key"]


def test_machine_local_configuration_precedes_legacy_environment(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "legacy-client")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "legacy-secret")
    monkeypatch.setattr(
        cloud_config,
        "_stored_payload",
        lambda: {
            "runtime": {"public_base_url": "https://sgaa.example"},
            "providers": {
                "google": {"client_id": "machine-client", "client_secret": "machine-secret"}
            },
        },
    )

    config = cloud_config.get_google_oauth_config()
    assert config["client_id"] == "machine-client"
    assert config["client_secret"] == "machine-secret"
    assert cloud_config.get_public_base_url_setting() == "https://sgaa.example"
    assert cloud_config.get_application_credential_status("google") == {
        "provider": "google",
        "configured": True,
        "source": "MACHINE_LOCAL_DPAPI",
    }


def test_google_configuration_is_independent_of_deferred_onedrive(monkeypatch):
    monkeypatch.setattr(
        cloud_config,
        "_stored_payload",
        lambda: {
            "runtime": {"public_base_url": "http://localhost:5000"},
            "providers": {
                "google": {
                    "client_id": "google-client",
                    "client_secret": "google-secret",
                }
            },
        },
    )

    assert cloud_config.get_application_credential_status("google")["configured"] is True
    assert cloud_config.get_application_credential_status("onedrive") == {
        "provider": "onedrive",
        "configured": False,
        "source": "ABSENT",
    }


def test_configuration_utility_google_only_does_not_report_onedrive(
    monkeypatch, capsys
):
    configured = []
    monkeypatch.setattr(configure_cloud_oauth, "_configure", configured.append)
    monkeypatch.setattr(
        configure_cloud_oauth,
        "get_application_credential_status",
        lambda provider: {
            "provider": provider,
            "configured": provider == "google",
            "source": "MACHINE_LOCAL_DPAPI" if provider == "google" else "ABSENT",
        },
    )
    monkeypatch.setattr(
        configure_cloud_oauth.sys,
        "argv",
        ["configure_cloud_oauth.py", "--provider", "google"],
    )

    assert configure_cloud_oauth.main() == 0
    output = capsys.readouterr().out
    assert configured == ["google"]
    assert "Google Drive: PRESENT" in output
    assert "OneDrive" not in output


def test_machine_credential_rotation_preserves_other_provider(tmp_path, monkeypatch):
    store_path = tmp_path / "cloud-oauth.dpapi"
    monkeypatch.setattr(machine_secrets, "get_machine_secrets_path", lambda: str(store_path))
    monkeypatch.setattr(machine_secrets, "_protect_bytes", lambda value: value[::-1])
    monkeypatch.setattr(machine_secrets, "_unprotect_bytes", lambda value: value[::-1])
    machine_secrets.update_machine_oauth_configuration(
        provider="onedrive",
        values={"client_id": "one-client", "client_secret": "one-secret", "tenant_id": "tenant"},
        public_base_url="https://sgaa.example",
    )
    machine_secrets.update_machine_oauth_configuration(
        provider="google",
        values={"client_id": "google-client", "client_secret": "google-secret"},
        public_base_url="https://sgaa.example",
    )
    machine_secrets.update_machine_oauth_configuration(
        provider="google",
        values={"client_id": "rotated-client", "client_secret": "rotated-secret"},
    )
    payload = machine_secrets.load_machine_secrets()
    assert payload["providers"]["google"]["client_id"] == "rotated-client"
    assert payload["providers"]["onedrive"]["client_id"] == "one-client"


def test_callback_urls_come_from_machine_local_runtime_configuration(monkeypatch):
    monkeypatch.setattr(oauth_config, "get_public_base_url_setting", lambda: "https://sgaa.example")
    assert oauth_config.get_google_redirect_uri() == "https://sgaa.example/google/callback"
    assert oauth_config.get_onedrive_redirect_uri() == "https://sgaa.example/onedrive/callback"


def test_google_start_and_callback_bind_the_same_pkce_verifier(monkeypatch):
    calls = []

    class FakeCredentials:
        token = "access-value"
        refresh_token = "refresh-value"
        token_uri = "https://oauth2.googleapis.com/token"
        scopes = ["scope-a"]
        expiry = None

    class FakeFlow:
        code_verifier = "pkce-verifier"
        credentials = FakeCredentials()

        @classmethod
        def from_client_config(cls, config, scopes, **kwargs):
            calls.append(kwargs)
            return cls()

        def authorization_url(self, **kwargs):
            return "https://accounts.example/authorize", "provider-state"

        def fetch_token(self, *, code):
            assert code == "callback-code"

    monkeypatch.setattr(
        google_drive_service,
        "_import_google_dependencies",
        lambda: (object, object, FakeFlow, object, object),
    )
    monkeypatch.setattr(google_drive_service, "_build_client_config", lambda redirect_uri: {"web": {}})
    monkeypatch.setattr(google_drive_service, "_get_scopes", lambda: ["scope-a"])
    monkeypatch.setattr(google_drive_service, "get_redirect_uri", lambda default_uri=None: "http://localhost:5000/google/callback")
    monkeypatch.setattr(google_drive_service, "_fetch_email", lambda credentials: "admin@example.com")

    auth_url, state, verifier = google_drive_service.create_authorization_url(
        state="local-state", is_debug=False
    )
    token_json, identity = google_drive_service.exchange_code_for_token(
        code="callback-code", code_verifier=verifier, is_debug=False
    )

    assert auth_url == "https://accounts.example/authorize"
    assert state == "provider-state"
    assert verifier == "pkce-verifier"
    assert calls[0]["autogenerate_code_verifier"] is True
    assert calls[1]["code_verifier"] == "pkce-verifier"
    assert identity == "admin@example.com"
    payload = json.loads(token_json)
    assert payload["refresh_token"] == "refresh-value"
    assert "client_id" not in payload
    assert "client_secret" not in payload


def test_google_invalid_client_error_is_actionable_without_secret_detail(monkeypatch):
    class InvalidClientError(Exception):
        pass

    class FakeFlow:
        @classmethod
        def from_client_config(cls, config, scopes, **kwargs):
            return cls()

        def fetch_token(self, *, code):
            raise InvalidClientError("provider detail must remain hidden")

    monkeypatch.setattr(
        google_drive_service,
        "_import_google_dependencies",
        lambda: (object, object, FakeFlow, object, object),
    )
    monkeypatch.setattr(google_drive_service, "_build_client_config", lambda redirect_uri: {"web": {}})
    monkeypatch.setattr(google_drive_service, "_get_scopes", lambda: ["scope-a"])
    monkeypatch.setattr(
        google_drive_service,
        "get_redirect_uri",
        lambda default_uri=None: "http://localhost:5000/google/callback",
    )

    with pytest.raises(google_drive_service.GoogleDriveServiceError) as captured:
        google_drive_service.exchange_code_for_token(
            code="callback-code", code_verifier="verifier", is_debug=False
        )

    assert captured.value.debug_code == "APPLICATION_CREDENTIALS_INVALID"
    assert "provider detail" not in str(captured.value)


def test_google_refresh_serialization_preserves_refresh_token_without_rotation():
    class Credentials:
        token = "new-access"
        refresh_token = None
        token_uri = "https://oauth2.googleapis.com/token"
        scopes = ["scope-a"]
        expiry = None

    payload = google_drive_service._serialize_credentials(
        Credentials(), previous_payload={"refresh_token": "existing-refresh"}
    )
    assert payload["refresh_token"] == "existing-refresh"
    assert "client_secret" not in payload


def test_onedrive_uses_msal_pkce_flow_for_start_and_callback(monkeypatch):
    class Cache:
        def serialize(self):
            return "serialized-cache"

    class App:
        def initiate_auth_code_flow(self, **kwargs):
            assert kwargs["state"] == "state-value"
            return {"auth_uri": "https://login.example/authorize", "code_verifier": "verifier"}

        def acquire_token_by_auth_code_flow(self, flow, response):
            assert flow["code_verifier"] == "verifier"
            assert response["code"] == "callback-code"
            return {"access_token": "access-value"}

    monkeypatch.setattr(onedrive_service, "_load_config", lambda: object())
    monkeypatch.setattr(onedrive_service, "_new_cache", lambda serialized="": Cache())
    monkeypatch.setattr(onedrive_service, "_build_app", lambda config, cache: App())
    monkeypatch.setattr(onedrive_service, "get_ms_redirect_uri", lambda: "http://localhost:5000/onedrive/callback")
    monkeypatch.setattr(onedrive_service, "fetch_account_email", lambda token: "admin@example.com")

    auth_url, flow = onedrive_service.create_authorization_url(state="state-value")
    token_json, identity = onedrive_service.exchange_code_for_token(
        auth_response={"code": "callback-code", "state": "state-value"}, auth_flow=flow
    )

    assert auth_url == "https://login.example/authorize"
    assert identity == "admin@example.com"
    payload = json.loads(token_json)
    assert payload["msal_cache"] == "serialized-cache"
    assert "access_token" not in payload
    assert "client_secret" not in payload


def test_onedrive_silent_refresh_persists_rotated_msal_cache(monkeypatch):
    class Cache:
        def serialize(self):
            return "rotated-cache"

    class App:
        def get_accounts(self):
            return [{"username": "admin@example.com"}]

        def acquire_token_silent_with_error(self, scopes, *, account):
            return {"access_token": "renewed-access"}

    monkeypatch.setattr(onedrive_service, "_load_config", lambda: object())
    monkeypatch.setattr(onedrive_service, "_new_cache", lambda serialized="": Cache())
    monkeypatch.setattr(onedrive_service, "_build_app", lambda config, cache: App())

    access_token, updated_json, identity = onedrive_service.acquire_access_token(
        token_json=json.dumps(
            {"msal_cache": "existing-cache", "account_email": "admin@example.com"}
        )
    )

    assert access_token == "renewed-access"
    assert identity == "admin@example.com"
    assert json.loads(updated_json)["msal_cache"] == "rotated-cache"


def _cloud_connection_fixture(monkeypatch):
    app = Flask(__name__)
    app.config.update(TESTING=True, APP_ENV="testing")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    monkeypatch.setattr(
        cloud_connections,
        "get_application_credential_status",
        lambda provider: {"provider": provider, "configured": True, "source": "test"},
    )
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE cloud_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT NOT NULL,
            account_email TEXT,
            token_json TEXT NOT NULL,
            connected_at TEXT,
            updated_at TEXT,
            active INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    monkeypatch.setattr(cloud_connections, "ensure_cloud_backup_schema", lambda conn: None)
    return app, conn


def _install_google_refresh_stub(
    monkeypatch,
    *,
    failure: Exception | None = None,
    refreshed_refresh_token: str | None = None,
):
    class Credentials:
        expired = True

        def __init__(self, **kwargs):
            self.token = kwargs.get("token")
            self.refresh_token = kwargs.get("refresh_token")
            self.token_uri = kwargs.get("token_uri")
            self.scopes = kwargs.get("scopes")
            self.expiry = kwargs.get("expiry")

        def refresh(self, request):
            if failure is not None:
                raise failure
            self.token = "new-access"
            self.refresh_token = refreshed_refresh_token
            self.expiry = None

    class Request:
        pass

    monkeypatch.setattr(
        google_drive_service,
        "_import_google_dependencies",
        lambda: (Credentials, Request, object, object, object),
    )
    monkeypatch.setattr(
        google_drive_service,
        "get_google_oauth_config",
        lambda: {
            "client_id": "test-client",
            "client_secret": "test-secret",
            "scopes": "scope-a",
        },
    )
    monkeypatch.setattr(
        google_drive_service, "_fetch_email", lambda credentials: "admin@example.com"
    )
    monkeypatch.setattr(
        cloud_connections,
        "acquire_google_access_token",
        google_drive_service.acquire_access_token,
    )


def test_canonical_connection_persists_rotated_token_atomically(monkeypatch):
    app, conn = _cloud_connection_fixture(monkeypatch)
    original = json.dumps({"token": "old-access", "refresh_token": "old-refresh"})
    rotated = json.dumps({"token": "new-access", "refresh_token": "new-refresh"})
    with app.app_context():
        cloud_connections.set_active_cloud_account(conn, "google", "old@example.com", original)
        conn.commit()
        monkeypatch.setattr(
            cloud_connections,
            "acquire_google_access_token",
            lambda **kwargs: ("new-access", rotated, "new@example.com"),
        )

        token, identity = cloud_connections.get_authenticated_access_token(conn, "google")
        account = cloud_connections.get_active_cloud_account(conn, "google")

    assert token == "new-access"
    assert identity == "new@example.com"
    assert json.loads(account["token_json"])["refresh_token"] == "new-refresh"
    raw = conn.execute("SELECT token_json FROM cloud_accounts WHERE active = 1").fetchone()[0]
    assert "new-refresh" not in raw


def test_invalid_refresh_authorization_marks_account_for_reconnect(monkeypatch):
    app, conn = _cloud_connection_fixture(monkeypatch)
    with app.app_context():
        cloud_connections.set_active_cloud_account(
            conn,
            "google",
            "admin@example.com",
            json.dumps({"token": "expired", "refresh_token": "revoked"}),
        )
        conn.commit()
        stored_before = conn.execute(
            "SELECT token_json FROM cloud_accounts WHERE active = 1"
        ).fetchone()[0]
        _install_google_refresh_stub(
            monkeypatch,
            failure=RefreshError(
                "invalid grant",
                {"error": "invalid_grant", "error_description": "revoked"},
            ),
        )
        with pytest.raises(cloud_connections.CloudConnectionError) as captured:
            cloud_connections.get_authenticated_access_token(conn, "google")

    assert captured.value.debug_code == "AUTH_RECONNECT_REQUIRED"
    assert conn.execute("SELECT COUNT(*) FROM cloud_accounts WHERE active = 1").fetchone()[0] == 0
    assert cloud_connections.get_latest_cloud_account(conn, "google")["account_email"] == "admin@example.com"
    assert conn.execute("SELECT token_json FROM cloud_accounts").fetchone()[0] == stored_before


def test_invalid_client_refresh_failure_preserves_durable_authorization(monkeypatch):
    app, conn = _cloud_connection_fixture(monkeypatch)
    with app.app_context():
        cloud_connections.set_active_cloud_account(
            conn,
            "google",
            "admin@example.com",
            json.dumps({"token": "expired", "refresh_token": "still-valid"}),
        )
        conn.commit()
        _install_google_refresh_stub(
            monkeypatch,
            failure=RefreshError(
                "invalid client",
                {"error": "invalid_client", "error_description": "bad app credentials"},
            ),
        )
        with pytest.raises(cloud_connections.CloudConnectionError) as captured:
            cloud_connections.get_authenticated_access_token(conn, "google")

    assert captured.value.debug_code == "APPLICATION_CREDENTIALS_INVALID"
    assert conn.execute(
        "SELECT COUNT(*) FROM cloud_accounts WHERE active = 1"
    ).fetchone()[0] == 1


@pytest.mark.parametrize(
    "failure",
    [
        TransportError("network unavailable"),
        TransportError("request timed out"),
        RefreshError(
            "provider temporarily unavailable",
            {"error": "temporarily_unavailable"},
            retryable=True,
        ),
    ],
    ids=["network", "timeout", "provider-5xx"],
)
def test_transient_refresh_failure_preserves_active_authorization(
    monkeypatch, failure
):
    app, conn = _cloud_connection_fixture(monkeypatch)
    with app.app_context():
        cloud_connections.set_active_cloud_account(
            conn,
            "google",
            "admin@example.com",
            json.dumps({"token": "expired", "refresh_token": "still-valid"}),
        )
        conn.commit()
        stored_before = conn.execute(
            "SELECT token_json FROM cloud_accounts WHERE active = 1"
        ).fetchone()[0]
        _install_google_refresh_stub(monkeypatch, failure=failure)

        with pytest.raises(cloud_connections.CloudConnectionError) as captured:
            cloud_connections.get_authenticated_access_token(conn, "google")

        account = cloud_connections.get_active_cloud_account(conn, "google")
        stored_after = conn.execute(
            "SELECT token_json FROM cloud_accounts WHERE active = 1"
        ).fetchone()[0]

    assert captured.value.debug_code == "AUTH_TEMPORARY_FAILURE"
    assert "Reconecte" not in str(captured.value)
    assert account is not None
    assert account["active"] == 1
    assert stored_after == stored_before


@pytest.mark.parametrize(
    ("refreshed_refresh_token", "expected_refresh_token"),
    [(None, "existing-refresh"), ("rotated-refresh", "rotated-refresh")],
    ids=["preserved", "rotated"],
)
def test_successful_refresh_persists_preserved_or_rotated_refresh_token(
    monkeypatch, refreshed_refresh_token, expected_refresh_token
):
    app, conn = _cloud_connection_fixture(monkeypatch)
    with app.app_context():
        cloud_connections.set_active_cloud_account(
            conn,
            "google",
            "admin@example.com",
            json.dumps({"token": "expired", "refresh_token": "existing-refresh"}),
        )
        conn.commit()
        _install_google_refresh_stub(
            monkeypatch, refreshed_refresh_token=refreshed_refresh_token
        )

        token, identity = cloud_connections.get_authenticated_access_token(conn, "google")
        account = cloud_connections.get_active_cloud_account(conn, "google")

    assert token == "new-access"
    assert identity == "admin@example.com"
    assert account["active"] == 1
    assert json.loads(account["token_json"])["refresh_token"] == expected_refresh_token
    raw = conn.execute("SELECT token_json FROM cloud_accounts WHERE active = 1").fetchone()[0]
    assert expected_refresh_token not in raw


def test_invalid_onedrive_cache_marks_account_for_reconnect(monkeypatch):
    app, conn = _cloud_connection_fixture(monkeypatch)
    with app.app_context():
        cloud_connections.set_active_cloud_account(
            conn,
            "onedrive",
            "admin@example.com",
            json.dumps({"msal_cache": "invalid"}),
        )
        conn.commit()

        def invalid(**kwargs):
            raise onedrive_service.OneDriveServiceError(
                "safe failure", debug_code="AUTH_RECONNECT_REQUIRED"
            )

        monkeypatch.setattr(cloud_connections, "acquire_onedrive_access_token", invalid)
        with pytest.raises(cloud_connections.CloudConnectionError) as captured:
            cloud_connections.get_authenticated_access_token(conn, "onedrive")

    assert captured.value.debug_code == "AUTH_RECONNECT_REQUIRED"
    assert conn.execute("SELECT COUNT(*) FROM cloud_accounts WHERE active = 1").fetchone()[0] == 0
    assert cloud_connections.get_latest_cloud_account(conn, "onedrive")["account_email"] == "admin@example.com"


def test_missing_application_credentials_fail_before_provider_network(monkeypatch):
    app, conn = _cloud_connection_fixture(monkeypatch)
    monkeypatch.setattr(
        cloud_connections,
        "get_application_credential_status",
        lambda provider: {"provider": provider, "configured": False, "source": "ABSENT"},
    )
    with app.app_context(), pytest.raises(cloud_connections.CloudConnectionError) as captured:
        cloud_connections.get_authenticated_access_token(conn, "google")
    assert captured.value.debug_code == "APPLICATION_CREDENTIALS_MISSING"


def test_disconnect_deactivates_authorization_and_revokes_google_best_effort(monkeypatch):
    app, conn = _cloud_connection_fixture(monkeypatch)
    revoked = []
    with app.app_context():
        cloud_connections.set_active_cloud_account(
            conn,
            "google",
            "admin@example.com",
            json.dumps({"token": "access", "refresh_token": "refresh"}),
        )
        conn.commit()
        monkeypatch.setattr(
            cloud_connections.low_level_cloud,
            "google_revoke",
            lambda token: revoked.append(token),
        )
        cloud_connections.disconnect_cloud_account(conn, "google")
        conn.commit()
    assert revoked == ["refresh"]
    assert conn.execute("SELECT COUNT(*) FROM cloud_accounts WHERE active = 1").fetchone()[0] == 0


def test_health_check_reads_identity_without_creating_files(monkeypatch):
    app, conn = _cloud_connection_fixture(monkeypatch)
    with app.app_context():
        cloud_connections.set_active_cloud_account(
            conn,
            "onedrive",
            "old@example.com",
            json.dumps({"msal_cache": "cache"}),
        )
        conn.commit()
        monkeypatch.setattr(
            cloud_connections,
            "get_authenticated_access_token",
            lambda conn, provider: ("access", "old@example.com"),
        )
        monkeypatch.setattr(
            cloud_connections.low_level_cloud,
            "onedrive_userinfo",
            lambda token: {"userPrincipalName": "current@example.com"},
        )
        result = cloud_connections.test_connection(conn, "onedrive")
        active = cloud_connections.get_active_cloud_account(conn, "onedrive")
    assert result == {
        "provider": "onedrive",
        "status": "connected",
        "account_email": "current@example.com",
    }
    assert active["account_email"] == "current@example.com"


def test_backup_uses_canonical_connection_without_legacy_access_token(monkeypatch):
    calls = []

    class Conn:
        def commit(self):
            calls.append("commit")

    monkeypatch.setattr(
        orchestrator,
        "get_drive_settings",
        lambda conn: {
            "gdrive_enabled": "1",
            "gdrive_dest_folder": "Backups/sistema",
            "gdrive_access_token": "",
            "onedrive_enabled": "0",
        },
    )
    monkeypatch.setattr(orchestrator, "get_retention_policy", lambda conn: {})
    monkeypatch.setattr(orchestrator, "_build_retention_policy_windows", lambda settings: [])
    monkeypatch.setattr(
        orchestrator._cloud_connections,
        "get_authenticated_access_token",
        lambda conn, provider: ("canonical-access", "admin@example.com"),
    )
    monkeypatch.setattr(
        orchestrator._cd,
        "google_upload",
        lambda token, path, folder: calls.append((token, path, folder)),
    )
    monkeypatch.setattr(orchestrator._cd, "apply_retention_to_drive", lambda *args, **kwargs: {})
    monkeypatch.setattr(orchestrator, "_save_drive_config", lambda conn, updates: calls.append(updates))

    orchestrator._maybe_upload_to_drives("snapshot.db", conn=Conn())

    assert ("canonical-access", "snapshot.db", "Backups/sistema") in calls


def test_folder_listing_uses_canonical_connection_layer(monkeypatch):
    monkeypatch.setattr(
        cloud_connections,
        "get_authenticated_access_token",
        lambda conn, provider: ("canonical-access", "admin@example.com"),
    )
    monkeypatch.setattr(
        cloud_connections,
        "list_google_folders_with_access_token",
        lambda **kwargs: {
            "parent_id": kwargs["parent_id"],
            "folders": [{"id": "folder-id", "name": "Folder"}],
        },
    )

    result = cloud_connections.list_folders(object(), "google", parent_id="root")

    assert result == {
        "parent_id": "root",
        "folders": [{"id": "folder-id", "name": "Folder"}],
        "account_email": "admin@example.com",
    }


def test_health_action_reuses_existing_csrf_and_rbac_protected_post_route():
    source = open("app/views/admin/banco_dados.py", encoding="utf-8-sig").read()
    template = open("templates/admin_banco_dados.html", encoding="utf-8-sig").read()
    assert 'request.form.get("action")' in source
    assert template.count('value="test_connection"') == 1
    assert template.count("Testar conexão") >= 2
    assert "csrf_token" in template
    assert 'f"Conexão com {label} validada"' in source
    assert 'f"Conexao com {label} validada"' not in source


def test_admin_cloud_ui_keeps_google_active_and_onedrive_visible_but_deferred():
    template = open("templates/admin_banco_dados.html", encoding="utf-8-sig").read()
    view_source = open("app/views/admin/banco_dados.py", encoding="utf-8-sig").read()
    assert "<h3>Google Drive</h3>" in template
    assert '"onedrive_ui_enabled": True' in view_source
    assert "{% if onedrive_ui_enabled %}\n      {# OneDrive #}" in template
    assert "<h3>OneDrive</h3>" in template
    assert template.count("onedrive_connection_status == 'not_configured'") >= 2
    assert "Não configurado" in template
    assert "<strong>OneDrive:</strong>" in template
    assert "Configuração Microsoft adiada" in template
    assert "Disponível após configurar as credenciais Microsoft desta máquina" in template
    assert template.count('<div class="db-provider-secondary">') == 2
    assert ".db-provider-secondary.is-balanced" not in template
    assert "grid-template-columns:repeat(2, minmax(0, 1fr));" in template
    assert "align-content:start;" in template
    assert template.count(".db-provider-secondary{ grid-template-columns:1fr; }") == 2
    assert 'title="OneDrive não está configurado"' in template
    assert "<strong>OneDrive callback:</strong>" in template
    assert "tools/configure_cloud_oauth.py --provider google" in template
    assert "tools/configure_cloud_oauth.py --provider both" not in template


def test_user_facing_paths_do_not_log_or_store_application_secrets():
    google_source = open("app/services/google_drive_service.py", encoding="utf-8-sig").read()
    view_source = open("app/views/admin/banco_dados.py", encoding="utf-8-sig").read()
    assert '"client_secret": credentials.client_secret' not in google_source
    assert "Falha ao trocar code OAuth por token: {exc}" not in google_source
    assert "access_token=%s" not in view_source
    assert "refresh_token=%s" not in view_source


def test_oauth_callback_access_log_redacts_authorization_code():
    record = logging.LogRecord(
        "werkzeug",
        logging.INFO,
        __file__,
        1,
        'GET /google/callback?state=sensitive-state&code=sensitive-value&scope=email HTTP/1.1',
        (),
        None,
    )

    assert OAuthQueryRedactionFilter().filter(record) is True
    rendered = record.getMessage()
    assert "sensitive-value" not in rendered
    assert "sensitive-state" not in rendered
    assert "code=[REDACTED]" in rendered
    assert "state=[REDACTED]" in rendered
