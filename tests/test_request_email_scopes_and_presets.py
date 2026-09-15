"""Delegated Microsoft scope ownership, preset model and secret hygiene."""

from __future__ import annotations

import json

import pytest

# `app` must be imported before `services.onedrive_service`: the package graph
# resolves the cloud-connection cycle in that order (see tests/test_cloud_oauth_recovery.py).
from app.services.mail_service import sanitize_provider_error
from services import onedrive_service as onedrive
from tests.request_email_support import install_email_preset, new_v7_connection


# --- canonical delegated scopes -------------------------------------------

def test_mail_send_added_to_canonical_scopes():
    assert "Mail.Send" in onedrive.SCOPES


def test_existing_scopes_preserved():
    assert "User.Read" in onedrive.SCOPES
    assert "Files.ReadWrite" in onedrive.SCOPES


def test_no_reserved_offline_access_in_msal_scopes():
    """MSAL adds reserved scopes itself; listing them breaks the auth request."""
    lowered = {scope.lower() for scope in onedrive.SCOPES}
    assert "offline_access" not in lowered
    assert "openid" not in lowered
    assert "profile" not in lowered


def test_scope_list_has_no_duplicates():
    assert len(onedrive.SCOPES) == len(set(onedrive.SCOPES))


def test_legacy_cloud_drives_scope_remains_untouched():
    """The sibling raw-OAuth string has no importers; it stays as-is.

    Documented deliberately: changing dead code would be a behaviour change
    with no live consumer, and `offline_access` is in fact correct for a raw
    authorize URL, unlike the MSAL list above.
    """
    import app.cloud_drives as cloud_drives

    assert cloud_drives._ONEDRIVE_SCOPE == "Files.ReadWrite offline_access User.Read"


# --- reconnect-required detection -----------------------------------------

def test_token_without_mail_send_requires_reconnect():
    token_json = json.dumps({"msal_cache": "{}", "scopes": ["User.Read", "Files.ReadWrite"]})
    assert onedrive.token_grants_mail_send(token_json) is False


def test_token_with_mail_send_is_accepted():
    token_json = json.dumps({"msal_cache": "{}", "scopes": onedrive.SCOPES})
    assert onedrive.token_grants_mail_send(token_json) is True


def test_send_mail_refuses_without_mail_send_scope():
    token_json = json.dumps({"msal_cache": "{}", "scopes": ["User.Read"]})
    with pytest.raises(onedrive.OneDriveServiceError) as excinfo:
        onedrive.send_mail(
            token_json=token_json, to_address="a@b.com", subject="s", body_text="b"
        )
    assert "Reconecte" in str(excinfo.value)


# --- secret hygiene --------------------------------------------------------

@pytest.mark.parametrize(
    "hostile",
    [
        "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9verylongtokenvalue",
        "access_token=abc123",
        "refresh_token leaked",
        "client_secret=shhh",
    ],
)
def test_sanitized_errors_never_carry_secrets(hostile):
    cleaned = sanitize_provider_error(hostile)
    for needle in ("Bearer", "access_token", "refresh_token", "client_secret", "eyJ"):
        assert needle not in cleaned


def test_long_opaque_values_are_redacted():
    cleaned = sanitize_provider_error("Falha no envio " + "A" * 60)
    assert "[redacted]" in cleaned


def test_outbox_stores_no_token_columns():
    conn = new_v7_connection()
    for table in ("email_envios", "requisicao_email_eventos"):
        cols = {row[1].lower() for row in conn.execute(f"PRAGMA table_info({table})")}
        for forbidden in ("token", "access_token", "refresh_token", "secret", "bearer"):
            assert not any(forbidden in col for col in cols), (table, cols)


# --- preset model ----------------------------------------------------------

def test_titulo_remains_internal_label_and_assunto_is_the_subject():
    conn = new_v7_connection()
    install_email_preset(
        conn, titulo="Modelo interno", assunto="Resultado das suas requisições"
    )
    row = conn.execute(
        "SELECT titulo,assunto FROM configuracoes_presets WHERE tipo='emails'"
    ).fetchone()
    assert row["titulo"] == "Modelo interno"
    assert row["assunto"] == "Resultado das suas requisições"


def test_default_preset_lookup_is_explicit():
    from presets_api import get_default_email_preset

    conn = new_v7_connection()
    install_email_preset(conn, preset_id=1, titulo="Nao padrao", is_default=0)
    install_email_preset(conn, preset_id=2, titulo="O padrao", is_default=1)

    chosen = get_default_email_preset(conn)
    assert chosen["titulo"] == "O padrao"
    assert chosen["id"] == 2


def test_missing_default_raises_instead_of_guessing():
    from presets_api import DefaultEmailPresetError, get_default_email_preset

    conn = new_v7_connection()
    install_email_preset(conn, preset_id=1, titulo="Sem padrao", is_default=0)
    install_email_preset(conn, preset_id=2, titulo="Tambem nao", is_default=0)

    with pytest.raises(DefaultEmailPresetError):
        get_default_email_preset(conn)


def test_sanitizer_keeps_email_fields_and_rejects_unknown_placeholder():
    from presets_api import _sanitize_presets

    payload = {
        "respostas": [{"id": 1, "titulo": "J", "texto": "texto"}],
        "emails": [
            {
                "id": 1,
                "titulo": "Modelo",
                "texto": "{saudacao} {requisicoes}",
                "assunto": "Resultado {aluno.primeironome}",
                "is_default": True,
            }
        ],
    }
    cleaned = _sanitize_presets(payload)
    assert cleaned["emails"][0]["assunto"] == "Resultado {aluno.primeironome}"
    assert cleaned["emails"][0]["is_default"] == 1
    # Justificativas keep their historical shape exactly.
    assert set(cleaned["respostas"][0]) == {"id", "titulo", "texto"}

    payload["emails"][0]["texto"] = "Olá {aluno.sobrenome}"
    with pytest.raises(ValueError):
        _sanitize_presets(payload)


def test_sanitizer_rejects_block_placeholder_in_subject():
    from presets_api import _sanitize_presets

    with pytest.raises(ValueError):
        _sanitize_presets({
            "respostas": [],
            "emails": [{"id": 1, "titulo": "M", "texto": "ok", "assunto": "{requisicoes}"}],
        })


def test_sanitizer_rejects_two_defaults():
    from presets_api import _sanitize_presets

    with pytest.raises(ValueError):
        _sanitize_presets({
            "respostas": [],
            "emails": [
                {"id": 1, "titulo": "A", "texto": "", "assunto": "", "is_default": True},
                {"id": 2, "titulo": "B", "texto": "", "assunto": "", "is_default": True},
            ],
        })
