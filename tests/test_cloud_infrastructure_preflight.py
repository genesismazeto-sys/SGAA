"""Machine-local cloud/OAuth infrastructure contract.

Covers the P0 repair:

* the canonical startup preflight auto-creates the machine-local
  token-encryption key and reuses it across restarts;
* an already encrypted ``cloud_accounts`` token whose key is unrecoverable is
  never destroyed and never silently re-encrypted — it becomes
  reconnect-required and a normal reconnect replaces it transactionally;
* Activity CRUD is independent of Google Drive;
* user-facing cloud failures carry no cryptography or manual-setup text.

Every test that exercises the DPAPI store redirects
``machine_secrets.get_machine_secrets_path`` at a ``tmp_path`` and replaces the
DPAPI primitives, so the real ``%LOCALAPPDATA%\\SGAA\\secrets`` store of the
developer running pytest is never read for content nor written.
"""

from __future__ import annotations

import ast
import json
import sqlite3
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from flask import Flask

import main
from app import cloud_config, cloud_connections, machine_secrets, startup_preflight
from app.services import token_encryption
from app.storage import google_connection
from tests.versioned_test_support import isolated_versioned_app_env


PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Text that must never reach an ordinary user through any cloud failure.
FORBIDDEN_UI_TERMS = (
    "Chave de criptografia",
    "criptografia OAuth",
    "configure_cloud_oauth",
    "TOKEN_ENCRYPTION_KEY",
    "Fernet",
    "cryptography",
    "pip install",
    "python -c",
    "DPAPI",
)


def _isolate_store(monkeypatch, tmp_path, *, name="cloud-oauth.dpapi"):
    """Point the machine store at tmp_path and stub the DPAPI primitives."""
    store_path = tmp_path / name
    monkeypatch.delenv("TOKEN_ENCRYPTION_KEY", raising=False)
    monkeypatch.setattr(machine_secrets, "get_machine_secrets_path", lambda: str(store_path))
    monkeypatch.setattr(machine_secrets, "_protect_bytes", lambda value: b"p:" + value[::-1])
    monkeypatch.setattr(
        machine_secrets, "_unprotect_bytes", lambda value: value[len(b"p:") :][::-1]
    )
    return store_path


# --------------------------------------------------------------------------
# A/B. Canonical bootstrap + startup preflight
# --------------------------------------------------------------------------


def test_fresh_machine_bootstraps_the_key_automatically(tmp_path, monkeypatch):
    store_path = _isolate_store(monkeypatch, tmp_path)
    assert not store_path.exists()

    result = startup_preflight.run_startup_preflight()

    assert result["status"] == machine_secrets.INFRASTRUCTURE_CREATED
    assert store_path.is_file()
    key = machine_secrets.get_machine_token_encryption_key(create=False)
    assert key
    Fernet(key.encode("utf-8"))  # the generated key is a usable Fernet key


def test_restart_reuses_the_same_key(tmp_path, monkeypatch):
    _isolate_store(monkeypatch, tmp_path)

    first = startup_preflight.run_startup_preflight()
    key_after_first = machine_secrets.get_machine_token_encryption_key(create=False)
    second = startup_preflight.run_startup_preflight()
    third = startup_preflight.run_startup_preflight()
    key_after_third = machine_secrets.get_machine_token_encryption_key(create=False)

    assert first["status"] == machine_secrets.INFRASTRUCTURE_CREATED
    assert second["status"] == machine_secrets.INFRASTRUCTURE_REUSED
    assert third["status"] == machine_secrets.INFRASTRUCTURE_REUSED
    assert key_after_first == key_after_third


def test_preflight_preserves_a_preexisting_environment_key(tmp_path, monkeypatch):
    store_path = _isolate_store(monkeypatch, tmp_path)
    legacy_key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", legacy_key)

    result = startup_preflight.run_startup_preflight()

    assert result["status"] == machine_secrets.INFRASTRUCTURE_ENVIRONMENT
    assert not store_path.exists()
    assert token_encryption.get_token_encryption_key() == legacy_key


def test_preflight_degrades_without_raising_when_store_cannot_be_written(
    tmp_path, monkeypatch
):
    _isolate_store(monkeypatch, tmp_path)

    def _refuse(payload, *, path=None):
        raise machine_secrets.MachineSecretsError(
            "O armazenamento seguro desta maquina nao pode ser preparado agora.",
            debug_detail="stub de teste",
        )

    monkeypatch.setattr(machine_secrets, "save_machine_secrets", _refuse)

    result = startup_preflight.run_startup_preflight()

    assert result["status"] == startup_preflight.PREFLIGHT_DEGRADED
    assert startup_preflight.main() == 0


def test_preflight_runs_outside_import_and_request_paths():
    """The bootstrap must never fire during pytest, create_app or a request."""
    def _creates_machine_secrets(node: ast.AST) -> bool:
        if not isinstance(node, ast.Call):
            return False
        name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
        if name == "ensure_machine_secret_infrastructure":
            return True
        if name != "get_machine_token_encryption_key":
            return False
        return any(
            keyword.arg == "create"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value is True
            for keyword in node.keywords
        )

    preflight_users = []
    for path in sorted((PROJECT_ROOT / "app").rglob("*.py")):
        if path.name in {"startup_preflight.py", "machine_secrets.py"}:
            continue  # the preflight and the store itself are the owners
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        if any(_creates_machine_secrets(node) for node in ast.walk(tree)):
            preflight_users.append(str(path.relative_to(PROJECT_ROOT)))
    assert preflight_users == [], (
        "machine-secret creation must stay behind app.startup_preflight; "
        f"unexpected callers: {preflight_users}"
    )

    tree = ast.parse((PROJECT_ROOT / "main.py").read_text(encoding="utf-8-sig"))
    guarded = [
        node
        for node in tree.body
        if isinstance(node, ast.If)
        and "run_startup_preflight" in ast.dump(node)
        and "__main__" in ast.dump(node.test)
    ]
    assert len(guarded) == 1, (
        "main.py must call run_startup_preflight only inside its "
        '`if __name__ == "__main__"` block'
    )


def test_launchers_delegate_preflight_to_application_code():
    for launcher in ("run.bat", "run2.bat"):
        source = (PROJECT_ROOT / launcher).read_text(encoding="utf-8-sig")
        assert "-m app.startup_preflight" in source, launcher
        for forbidden in ("Fernet", "generate_key", "TOKEN_ENCRYPTION_KEY"):
            assert forbidden not in source, f"{launcher} must not implement crypto"


def test_fernet_generation_has_exactly_one_owner():
    source = (PROJECT_ROOT / "app" / "machine_secrets.py").read_text(encoding="utf-8-sig")
    assert source.count("Fernet.generate_key()") == 1
    for path in sorted(PROJECT_ROOT.glob("*.py")):
        assert "Fernet.generate_key()" not in path.read_text(encoding="utf-8-sig")


# --------------------------------------------------------------------------
# C. Existing encrypted token whose key is gone
# --------------------------------------------------------------------------


def _cloud_fixture(monkeypatch, key: str):
    app = Flask(__name__)
    app.config.update(TESTING=True, APP_ENV="testing")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", key)
    monkeypatch.setattr(
        cloud_connections,
        "get_application_credential_status",
        lambda provider: {"provider": provider, "configured": True, "source": "test"},
    )
    monkeypatch.setattr(cloud_connections, "ensure_cloud_backup_schema", lambda conn: None)
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
    return app, conn


def test_unrecoverable_key_never_destroys_the_stored_token(monkeypatch):
    old_key = Fernet.generate_key().decode("ascii")
    app, conn = _cloud_fixture(monkeypatch, old_key)
    with app.app_context():
        cloud_connections.set_active_cloud_account(
            conn,
            "google",
            "admin@example.com",
            json.dumps({"token": "a", "refresh_token": "durable-refresh"}),
        )
        conn.commit()
    stored_before = conn.execute(
        "SELECT token_json FROM cloud_accounts WHERE active = 1"
    ).fetchone()[0]

    # The machine now holds a different key: the old token cannot be opened.
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    with app.app_context():
        account = cloud_connections.get_active_cloud_account(conn, "google")
        with pytest.raises(cloud_connections.CloudConnectionError) as captured:
            cloud_connections.get_authenticated_access_token(conn, "google")

    assert account["token_json_available"] is False
    assert captured.value.debug_code == "AUTH_RECONNECT_REQUIRED"
    stored_after = conn.execute(
        "SELECT token_json FROM cloud_accounts WHERE active = 1"
    ).fetchone()[0]
    assert stored_after == stored_before
    assert stored_after.startswith("fernet:")
    for term in FORBIDDEN_UI_TERMS:
        assert term not in str(captured.value)
        assert term not in account["token_json_error"]


def test_reconnect_replaces_the_obsolete_token_transactionally(monkeypatch):
    old_key = Fernet.generate_key().decode("ascii")
    app, conn = _cloud_fixture(monkeypatch, old_key)
    with app.app_context():
        cloud_connections.set_active_cloud_account(
            conn, "google", "admin@example.com", json.dumps({"token": "old"})
        )
        conn.commit()
    obsolete = conn.execute("SELECT token_json FROM cloud_accounts").fetchone()[0]

    new_key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", new_key)
    with app.app_context():
        cloud_connections.set_active_cloud_account(
            conn, "google", "admin@example.com", json.dumps({"token": "reconnected"})
        )
        conn.commit()
        account = cloud_connections.get_active_cloud_account(conn, "google")

    assert json.loads(account["token_json"])["token"] == "reconnected"
    assert account["token_json_available"] is True
    rows = conn.execute(
        "SELECT token_json, active FROM cloud_accounts ORDER BY id"
    ).fetchall()
    assert len(rows) == 2
    assert rows[0]["token_json"] == obsolete, "the obsolete token was overwritten"
    assert rows[0]["active"] == 0
    assert rows[1]["active"] == 1


def test_token_update_refuses_to_write_an_empty_authorization(monkeypatch):
    key = Fernet.generate_key().decode("ascii")
    app, conn = _cloud_fixture(monkeypatch, key)
    with app.app_context():
        cloud_connections.set_active_cloud_account(
            conn, "google", "admin@example.com", json.dumps({"token": "durable"})
        )
        conn.commit()
        stored_before = conn.execute(
            "SELECT token_json FROM cloud_accounts WHERE active = 1"
        ).fetchone()[0]

        with pytest.raises(cloud_connections.CloudConnectionError) as captured:
            cloud_connections.update_cloud_account_token(
                conn, account_id=1, token_json=""
            )

    assert captured.value.debug_code == "TOKEN_WRITE_REFUSED_EMPTY"
    assert (
        conn.execute("SELECT token_json FROM cloud_accounts WHERE id = 1").fetchone()[0]
        == stored_before
    )


# --------------------------------------------------------------------------
# E. Sanitized error model
# --------------------------------------------------------------------------


def test_missing_key_error_is_an_actionable_product_message(tmp_path, monkeypatch):
    _isolate_store(monkeypatch, tmp_path)

    with pytest.raises(token_encryption.TokenEncryptionConfigError) as captured:
        token_encryption.validate_token_encryption_configuration(env="development")

    message = str(captured.value)
    for term in FORBIDDEN_UI_TERMS:
        assert term not in message
    assert "Reconectar" in message
    assert "Banco de Dados" in message
    # the technical cause stays available for developers
    assert captured.value.debug_detail
    assert captured.value.debug_detail != message


def test_undecryptable_token_error_is_an_actionable_product_message(monkeypatch):
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    blob = token_encryption.encrypt_token_json_for_storage("{}", env="testing")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))

    with pytest.raises(token_encryption.TokenEncryptionConfigError) as captured:
        token_encryption.decrypt_token_json_from_storage(blob, env="testing")

    for term in FORBIDDEN_UI_TERMS:
        assert term not in str(captured.value)
    assert captured.value.debug_detail


def test_machine_secret_errors_are_sanitized(monkeypatch):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    with pytest.raises(machine_secrets.MachineSecretsError) as captured:
        machine_secrets.get_machine_secrets_path()
    for term in FORBIDDEN_UI_TERMS:
        assert term not in str(captured.value)
    assert captured.value.debug_detail


def test_no_module_emits_manual_setup_instructions_to_the_ui():
    for relative in (
        "app/services/token_encryption.py",
        "app/machine_secrets.py",
        "app/cloud_config.py",
        "app/cloud_connections.py",
    ):
        source = (PROJECT_ROOT / relative).read_text(encoding="utf-8-sig")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            text = node.value
            if "configure_cloud_oauth" in text or "Fernet.generate_key" in text:
                pytest.fail(f"{relative} still carries manual-setup text: {text!r}")


# --------------------------------------------------------------------------
# D. Activity CRUD is independent of Google Drive
# --------------------------------------------------------------------------


def test_activity_crud_never_resolves_google_storage(tmp_path, monkeypatch):
    """A normal Activity create/edit/save performs no Drive access at all."""
    calls: list[str] = []

    with isolated_versioned_app_env(tmp_path, "activity-drive-independence.db") as env:
        _isolate_store(monkeypatch, tmp_path, name="activity-store.dpapi")

        def _trace(module, name):
            original = getattr(module, name)

            def wrapper(*args, **kwargs):
                calls.append(f"{module.__name__}.{name}")
                return original(*args, **kwargs)

            monkeypatch.setattr(module, name, wrapper)

        for module, name in (
            (token_encryption, "get_token_encryption_key"),
            (token_encryption, "validate_token_encryption_configuration"),
            (token_encryption, "decrypt_token_json_from_storage"),
            (token_encryption, "encrypt_token_json_for_storage"),
            (cloud_config, "get_application_credential_status"),
            (cloud_connections, "get_authenticated_access_token"),
            (cloud_connections, "get_active_cloud_account"),
            (google_connection, "resolve_google_managed_storage"),
        ):
            _trace(module, name)

        # An unusable, already encrypted Google authorization is present, which
        # is exactly the state that used to make cloud code fail loudly.
        with main.app.app_context():
            conn = main.get_db_connection()
            from app.db import ensure_cloud_backup_schema

            ensure_cloud_backup_schema(conn)
            conn.execute("DELETE FROM cloud_accounts")
            conn.execute(
                """
                INSERT INTO cloud_accounts
                    (provider, account_email, token_json, connected_at, updated_at, active)
                VALUES ('google', 'admin@example.com', ?, datetime('now'), datetime('now'), 1)
                """,
                ("fernet:" + "g" * 600,),
            )
            conn.commit()

        client = env["client"]
        with client.session_transaction() as session:
            session.update(user_id=1, user_type="admin", user_name="Administrador")

        version_form = {
            "nome_conceito": "Visitas técnicas ou culturais",
            "descricao": "independência de Drive",
            "grupo": "1 - Eventos",
            "tipo_limitacao": "",
            "limite_valor": "",
            "ch_por_evento_mode": "disabled",
            "observacoes_aluno": "a",
            "observacoes_admin": "b",
        }
        exchanges = [
            ("GET", "/admin/atividades", None),
            ("GET", "/admin/adicionar_atividade", None),
            (
                "POST",
                "/admin/adicionar_atividade",
                {
                    "tipo_atividade": "Acadêmica Complementar",
                    "grupo": "1 - Eventos",
                    "nome": "Atividade sem Drive",
                    "descricao": "criada offline",
                    "tipo_limitacao": "",
                    "limite_valor": "",
                    "ch_por_evento_mode": "disabled",
                    "observacoes": "",
                },
            ),
            ("GET", "/admin/catalogo-versoes/1", None),
            ("GET", "/admin/catalogo-versoes/1/nova-versao", None),
            ("POST", "/admin/catalogo-versoes/1/nova-versao", version_form),
            ("GET", "/admin/catalogo-versoes/1/versoes/1/editar", None),
            ("POST", "/admin/catalogo-versoes/1/versoes/1/editar", version_form),
            ("POST", "/admin/catalogo-versoes/1/versoes/1/ativar", None),
        ]
        for method, url, data in exchanges:
            send = client.post if method == "POST" else client.get
            response = send(url, data=data, follow_redirects=True)
            assert response.status_code == 200, f"{method} {url}"
            body = response.get_data(as_text=True)
            for term in FORBIDDEN_UI_TERMS:
                assert term not in body, f"{method} {url} leaked {term!r}"

        assert calls == [], f"Activity CRUD reached cloud code: {sorted(set(calls))}"

        with main.app.app_context():
            conn = main.get_db_connection()
            created = conn.execute(
                "SELECT COUNT(*) FROM atividade_base WHERE nome_conceito = ?",
                ("Atividade sem Drive",),
            ).fetchone()[0]
        assert created == 1, "the Activity was not persisted while Google was unusable"
