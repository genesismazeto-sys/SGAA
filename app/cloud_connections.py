"""Authoritative OAuth connection lifecycle for SGAA cloud providers.

Storage features consume this module for an authenticated provider token.  They
do not own refresh, reconnect, account identity, or token persistence.
"""

from __future__ import annotations

import json
import os
import datetime
from typing import Any

from flask import current_app

import app.cloud_drives as low_level_cloud
from app.cloud_account_identity import (
    AccountIdentityError,
    google_account_key,
    require_provider_account_key,
)
from app.cloud_config import get_application_credential_status, get_onedrive_oauth_config
from app.db import ensure_cloud_backup_schema
from app.sql_dialect import current_utc_text
from app.services.google_drive_service import (
    GoogleDriveServiceError,
    acquire_access_token as acquire_google_access_token,
    refresh_access_token as refresh_google_access_token,
    list_google_folders_with_access_token,
    upload_zip_backup_with_access_token as upload_google_with_access_token,
)
from app.services.token_encryption import (
    TokenEncryptionConfigError,
    TokenEncryptionError,
    decrypt_token_json_from_storage,
    encrypt_token_json_for_storage,
)
from services.onedrive_service import (
    OneDriveServiceError,
    acquire_access_token as acquire_onedrive_access_token,
    list_onedrive_folders_with_access_token,
    upload_zip_backup_with_access_token as upload_onedrive_with_access_token,
)


PROVIDERS = {"google", "onedrive"}


class CloudConnectionError(RuntimeError):
    def __init__(self, message: str, *, debug_code: str = ""):
        super().__init__(message)
        self.debug_code = debug_code


def normalize_provider(provider: str) -> str:
    normalized = str(provider or "").strip().lower()
    if normalized not in PROVIDERS:
        raise ValueError("Provedor invalido.")
    return normalized


def _runtime_env() -> str:
    return str(current_app.config.get("APP_ENV") or os.getenv("APP_ENV") or "development")


def set_active_cloud_account(
    conn,
    provider: str,
    account_email: str,
    token_json: str,
    *,
    provider_account_key: str | None = None,
) -> None:
    """Insert the new active connection row (a reconnect always inserts).

    ``provider_account_key`` is the LOGICAL provider-account identity
    (``app.cloud_account_identity``); the row id only identifies this
    credential instance.  The Google connect flow always supplies it
    (``exchange_code_for_token`` refuses a connect without one); ``None``
    remains valid for a row whose identity was never established.
    """
    normalized = normalize_provider(provider)
    if provider_account_key is not None:
        if normalized != "google":
            raise CloudConnectionError(
                "Identidade de conta nao suportada.", debug_code="ACCOUNT_IDENTITY_PROVIDER_UNSUPPORTED"
            )
        try:
            require_provider_account_key(provider_account_key)
        except AccountIdentityError as exc:
            raise CloudConnectionError("Identidade de conta invalida.", debug_code=exc.code) from None
    ensure_cloud_backup_schema(conn)
    encrypted = encrypt_token_json_for_storage(token_json, env=_runtime_env())
    conn.execute(
        f"UPDATE cloud_accounts SET active = 0, updated_at = {current_utc_text(conn)} WHERE provider = ? AND active = 1",
        (normalized,),
    )
    conn.execute(
        f"""
        INSERT INTO cloud_accounts (provider, account_email, token_json, connected_at, updated_at, active,
                                    provider_account_key)
        VALUES (?, ?, ?, {current_utc_text(conn)}, {current_utc_text(conn)}, 1, ?)
        """,
        (normalized, (account_email or "").strip() or None, encrypted, provider_account_key),
    )


def resolve_active_account_id_by_key(conn, provider: str, provider_account_key: str) -> int | None:
    """The active connection row of one LOGICAL provider account, or ``None``.

    ``None`` means the mirror's account is disconnected / unavailable -- never
    a reason to doubt the canonical object.  Two active rows for one logical
    account cannot be ordered meaningfully: refuse instead of choosing.
    """
    normalized = normalize_provider(provider)
    try:
        require_provider_account_key(provider_account_key)
    except AccountIdentityError as exc:
        raise CloudConnectionError("Identidade de conta invalida.", debug_code=exc.code) from None
    rows = conn.execute(
        "SELECT id FROM cloud_accounts WHERE provider = ? AND provider_account_key = ? AND active = 1",
        (normalized, provider_account_key),
    ).fetchall()
    if len(rows) > 1:
        raise CloudConnectionError(
            "Mais de uma conexao ativa para a mesma conta. Reconecte a conta.",
            debug_code="ACCOUNT_IDENTITY_AMBIGUOUS",
        )
    return int(rows[0][0]) if rows else None


def get_active_cloud_account(conn, provider: str) -> dict[str, Any] | None:
    normalized = normalize_provider(provider)
    ensure_cloud_backup_schema(conn)
    row = conn.execute(
        """
        SELECT id, provider, account_email, token_json, connected_at, updated_at, active,
               provider_account_key
          FROM cloud_accounts
         WHERE provider = ? AND active = 1
      ORDER BY id DESC
         LIMIT 1
        """,
        (normalized,),
    ).fetchone()
    if not row:
        return None
    payload = dict(row)
    try:
        payload["token_json"] = decrypt_token_json_from_storage(
            str(payload.get("token_json") or ""), env=_runtime_env()
        )
        payload["token_json_available"] = True
        payload["token_json_error"] = ""
    except TokenEncryptionError as exc:
        payload["token_json"] = ""
        payload["token_json_available"] = False
        payload["token_json_error"] = str(exc)
    return payload


def get_latest_cloud_account(conn, provider: str) -> dict[str, Any] | None:
    normalized = normalize_provider(provider)
    ensure_cloud_backup_schema(conn)
    row = conn.execute(
        """
        SELECT id, provider, account_email, connected_at, updated_at, active
          FROM cloud_accounts
         WHERE provider = ?
      ORDER BY id DESC
         LIMIT 1
        """,
        (normalized,),
    ).fetchone()
    return dict(row) if row else None


def update_cloud_account_token(
    conn,
    *,
    account_id: int,
    token_json: str,
    account_email: str | None = None,
) -> None:
    # Custody invariant: a stored authorization is never replaced by an empty
    # one.  When the machine-local key cannot open an existing token the
    # decrypted value is "", and overwriting the row would destroy the only
    # copy of an authorization that a reconnect could still replace cleanly.
    if not str(token_json or "").strip():
        raise CloudConnectionError(
            "A conexão de nuvem precisa ser refeita nesta máquina. Use Reconectar.",
            debug_code="TOKEN_WRITE_REFUSED_EMPTY",
        )
    encrypted = encrypt_token_json_for_storage(token_json, env=_runtime_env())
    if account_email is None:
        conn.execute(
            f"UPDATE cloud_accounts SET token_json = ?, updated_at = {current_utc_text(conn)} WHERE id = ?",
            (encrypted, int(account_id)),
        )
    else:
        conn.execute(
            f"UPDATE cloud_accounts SET token_json = ?, account_email = ?, updated_at = {current_utc_text(conn)} WHERE id = ?",
            (encrypted, (account_email or "").strip() or None, int(account_id)),
        )


def _deactivate_account(conn, account_id: int) -> None:
    conn.execute(
        f"UPDATE cloud_accounts SET active = 0, updated_at = {current_utc_text(conn)} WHERE id = ?",
        (int(account_id),),
    )


def _reconnect_error(provider: str) -> str:
    return (
        "A autorizacao do Google Drive precisa ser renovada. Use Reconectar."
        if provider == "google"
        else "A autorizacao do OneDrive precisa ser renovada. Use Reconectar."
    )


def _legacy_onedrive_access_token(
    account: dict[str, Any], payload: dict[str, Any]
) -> tuple[str, str, str]:
    access_token = str(payload.get("access_token") or "").strip()
    refresh_token = str(payload.get("refresh_token") or "").strip()
    expires_at = str(payload.get("expires_at") or "").strip()
    if low_level_cloud.is_token_expired(expires_at):
        config = get_onedrive_oauth_config()
        if not refresh_token or not config["client_id"]:
            raise OneDriveServiceError(
                "Token expirado e sem refresh valido. Reconecte o OneDrive.",
                debug_code="AUTH_RECONNECT_REQUIRED",
            )
        refreshed = low_level_cloud.onedrive_refresh(config["client_id"], refresh_token)
        access_token = str(refreshed.get("access_token") or "").strip()
        if not access_token:
            raise OneDriveServiceError(
                "Falha ao renovar a autorizacao OneDrive.",
                debug_code="AUTH_RECONNECT_REQUIRED",
            )
        payload["refresh_token"] = str(refreshed.get("refresh_token") or refresh_token).strip()
        payload["access_token"] = access_token
        payload["expires_at"] = low_level_cloud.token_expires_at(
            int(refreshed.get("expires_in") or 3600)
        )
        payload["updated_at"] = (
            datetime.datetime.now(datetime.timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
    if not access_token:
        raise OneDriveServiceError(
            "Autorizacao OneDrive invalida. Reconecte o provedor.",
            debug_code="AUTH_RECONNECT_REQUIRED",
        )
    account_email = str(payload.get("account_email") or account.get("account_email") or "").strip()
    return access_token, json.dumps(payload, ensure_ascii=False), account_email


def _acquire_provider_token(
    provider: str, account: dict[str, Any], token_json: str
) -> tuple[str, str, str]:
    if provider == "google":
        return acquire_google_access_token(token_json=token_json)
    try:
        payload = json.loads(token_json or "{}")
    except json.JSONDecodeError:
        payload = {}
    if isinstance(payload, dict) and payload.get("mode") == "legacy_pkce":
        return _legacy_onedrive_access_token(account, payload)
    return acquire_onedrive_access_token(token_json=token_json)


def _mark_reconnect_and_raise(conn, provider: str, account_id: int, cause=None):
    _deactivate_account(conn, account_id)
    conn.commit()
    error = CloudConnectionError(
        _reconnect_error(provider), debug_code="AUTH_RECONNECT_REQUIRED"
    )
    if cause is not None:
        raise error from cause
    raise error


def get_authenticated_access_token(conn, provider: str) -> tuple[str, str]:
    normalized = normalize_provider(provider)
    credential_status = get_application_credential_status(normalized)
    if not credential_status["configured"]:
        raise CloudConnectionError(
            "Credenciais do aplicativo nao configuradas nesta maquina.",
            debug_code="APPLICATION_CREDENTIALS_MISSING",
        )
    account = get_active_cloud_account(conn, normalized)
    if not account:
        raise CloudConnectionError(_reconnect_error(normalized), debug_code="AUTH_RECONNECT_REQUIRED")
    if not account.get("token_json_available", True):
        raise CloudConnectionError(_reconnect_error(normalized), debug_code="AUTH_RECONNECT_REQUIRED")
    original_token_json = str(account.get("token_json") or "")
    try:
        access_token, updated_token_json, account_email = _acquire_provider_token(
            normalized, account, original_token_json
        )
    except (GoogleDriveServiceError, OneDriveServiceError) as exc:
        if getattr(exc, "debug_code", "") == "AUTH_RECONNECT_REQUIRED":
            _mark_reconnect_and_raise(conn, normalized, int(account["id"]), exc)
        raise CloudConnectionError(str(exc), debug_code=getattr(exc, "debug_code", "")) from exc
    if not access_token:
        _mark_reconnect_and_raise(conn, normalized, int(account["id"]))
    if updated_token_json and (
        updated_token_json != original_token_json
        or (account_email or "").strip() != str(account.get("account_email") or "").strip()
    ):
        update_cloud_account_token(
            conn,
            account_id=int(account["id"]),
            token_json=updated_token_json,
            account_email=account_email or None,
        )
        conn.commit()
    return access_token, (account_email or str(account.get("account_email") or "")).strip()


def recover_authenticated_access_token_after_401(
    conn, provider: str
) -> tuple[str, str]:
    """Refresh canonically; a provider 401 alone never revokes durable authorization."""
    normalized = normalize_provider(provider)
    credential_status = get_application_credential_status(normalized)
    if not credential_status["configured"]:
        raise CloudConnectionError(
            "Credenciais do aplicativo nao configuradas nesta maquina.",
            debug_code="APPLICATION_CREDENTIALS_MISSING",
        )
    account = get_active_cloud_account(conn, normalized)
    if not account or not account.get("token_json_available", True):
        raise CloudConnectionError(
            _reconnect_error(normalized), debug_code="AUTH_RECONNECT_REQUIRED"
        )
    original_token_json = str(account.get("token_json") or "")
    try:
        if normalized == "google":
            access_token, updated_token_json, account_email = refresh_google_access_token(
                token_json=original_token_json
            )
        else:
            access_token, updated_token_json, account_email = _acquire_provider_token(
                normalized, account, original_token_json
            )
    except (GoogleDriveServiceError, OneDriveServiceError) as exc:
        debug_code = getattr(exc, "debug_code", "")
        if debug_code == "AUTH_RECONNECT_REQUIRED":
            _mark_reconnect_and_raise(conn, normalized, int(account["id"]), exc)
        raise CloudConnectionError(str(exc), debug_code=debug_code) from exc
    if not access_token:
        raise CloudConnectionError(
            "Nao foi possivel renovar o token de acesso.",
            debug_code="AUTH_TEMPORARY_FAILURE",
        )
    update_cloud_account_token(
        conn,
        account_id=int(account["id"]),
        token_json=updated_token_json,
        account_email=account_email or None,
    )
    conn.commit()
    return access_token, (
        account_email or str(account.get("account_email") or "")
    ).strip()


def upload_backup_zip(
    conn,
    provider: str,
    *,
    zip_path: str,
    file_name: str,
    folder_name: str,
    folder_id: str | None = None,
    drive_id: str | None = None,
) -> dict[str, str]:
    normalized = normalize_provider(provider)
    access_token, account_email = get_authenticated_access_token(conn, normalized)
    if normalized == "google":
        result = upload_google_with_access_token(
            access_token=access_token,
            zip_path=zip_path,
            file_name=file_name,
            folder_name=folder_name,
            folder_id=folder_id,
        )
    else:
        result = upload_onedrive_with_access_token(
            access_token=access_token,
            zip_path=zip_path,
            file_name=file_name,
            folder_name=folder_name,
            folder_id=folder_id,
            drive_id=drive_id,
        )
    result["account_email"] = account_email
    return result


def list_folders(
    conn,
    provider: str,
    *,
    parent_id: str | None = None,
    drive_id: str | None = None,
) -> dict[str, object]:
    normalized = normalize_provider(provider)
    access_token, account_email = get_authenticated_access_token(conn, normalized)
    if normalized == "google":
        result = list_google_folders_with_access_token(
            access_token=access_token, parent_id=parent_id
        )
    else:
        result = list_onedrive_folders_with_access_token(
            access_token=access_token,
            parent_id=parent_id,
            drive_id=drive_id,
        )
    result["account_email"] = account_email
    return result


def test_connection(conn, provider: str) -> dict[str, str]:
    normalized = normalize_provider(provider)
    access_token, account_email = get_authenticated_access_token(conn, normalized)
    try:
        if normalized == "google":
            identity = low_level_cloud.google_userinfo(access_token)
            account_email = str(identity.get("email") or account_email).strip()
            observed_key = _google_key_from_userinfo(identity)
        else:
            identity = low_level_cloud.onedrive_userinfo(access_token)
            account_email = str(
                identity.get("mail") or identity.get("userPrincipalName") or account_email
            ).strip()
    except RuntimeError as exc:
        text = str(exc)
        if "HTTP 401" in text:
            account = get_active_cloud_account(conn, normalized)
            if account:
                _deactivate_account(conn, int(account["id"]))
                conn.commit()
            raise CloudConnectionError(
                _reconnect_error(normalized), debug_code="AUTH_RECONNECT_REQUIRED"
            ) from exc
        raise CloudConnectionError("Nao foi possivel validar a conexao com o provedor.") from exc
    account = get_active_cloud_account(conn, normalized)
    if account and normalized == "google" and observed_key is not None:
        _bind_or_check_google_identity(conn, account, observed_key)
    if account and account_email and account_email != str(account.get("account_email") or ""):
        update_cloud_account_token(
            conn,
            account_id=int(account["id"]),
            token_json=str(account.get("token_json") or ""),
            account_email=account_email,
        )
        conn.commit()
    return {"provider": normalized, "status": "connected", "account_email": account_email}


def _google_key_from_userinfo(identity) -> str | None:
    """Key of the OIDC ``sub`` in a trusted userinfo response; ``None`` if absent/invalid."""
    try:
        return google_account_key(identity.get("sub") if isinstance(identity, dict) else None)
    except AccountIdentityError:
        return None


def _bind_or_check_google_identity(conn, account, observed_key: str) -> None:
    """Backfill a NULL logical key from a trusted response; refuse a different account."""
    recorded = account.get("provider_account_key")
    if recorded is None:
        conn.execute(
            "UPDATE cloud_accounts SET provider_account_key = ? WHERE id = ? AND provider_account_key IS NULL",
            (observed_key, int(account["id"])),
        )
        conn.commit()
        return
    if recorded != observed_key:
        raise CloudConnectionError(
            "A conta Google autorizada nao corresponde a conta registrada. Reconecte o Google Drive.",
            debug_code="ACCOUNT_IDENTITY_MISMATCH",
        )


def disconnect_cloud_account(conn, provider: str) -> None:
    normalized = normalize_provider(provider)
    account = get_active_cloud_account(conn, normalized)
    if account and normalized == "google" and account.get("token_json_available", True):
        try:
            payload = json.loads(str(account.get("token_json") or "{}"))
            token = str(payload.get("refresh_token") or payload.get("token") or "")
            if token:
                low_level_cloud.google_revoke(token)
        except (TypeError, ValueError, RuntimeError):
            pass
    conn.execute(
        f"UPDATE cloud_accounts SET active = 0, updated_at = {current_utc_text(conn)} WHERE provider = ? AND active = 1",
        (normalized,),
    )
