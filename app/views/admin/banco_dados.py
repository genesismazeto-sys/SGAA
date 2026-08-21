# coding: utf-8
"""UT-8: dono canonico do cohort "Banco de Dados".

46 simbolos relocados de main.py por MOVE-VERBATIM (20 rotas, 24 helpers e 2
constantes). Nenhuma importacao de main; registra apenas wrappers de rotas
legadas via LegacyRouteSpec.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import secrets
import sqlite3
import tempfile
from urllib.parse import urlparse, urlsplit

from flask import (
    Blueprint,
    abort,
    current_app,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from werkzeug.utils import secure_filename

import app.cloud_drives as _cd
import app.db as app_db
from app.auth import admin_required
from app.backup import orchestrator as _backup_orchestrator
from app.backup import (
    _RETENTION_WINDOWS_META,
    _database_backup_locations,
    _get_runtime_backup_settings,
    _resolve_allowed_backup_manifest_path,
    _retention_policy_defaults,
    _save_drive_config,
    get_drive_settings,
    get_retention_policy,
)
from app.backup_settings import (
    _apply_backup_settings_to_app,
    ensure_backup_settings_schema,
)
from app.db import ensure_cloud_backup_schema, get_db_connection, init_db
from app.db_maintenance import (
    create_database_snapshot,
    delete_database_snapshot,
    get_schema_status,
    list_database_backups,
    restore_database_snapshot,
)
from app.presentation import _format_bytes_label
from app.services.backup_service import (
    BackupServiceError,
    cleanup_backup_artifacts,
    create_sqlite_backup_zip,
    extract_restore_database_artifact,
    validate_manifest_backed_restore,
)
from app.services.google_drive_service import (
    GoogleDriveServiceError,
    create_authorization_url as google_create_authorization_url,
    exchange_code_for_token as google_exchange_code_for_token,
    get_redirect_uri as google_get_redirect_uri,
    list_google_folders as google_list_folders,
    upload_zip_backup as google_upload_zip_backup,
)
from app.services.token_encryption import (
    TokenEncryptionConfigError,
    TokenEncryptionError,
    decrypt_token_json_from_storage,
    encrypt_token_json_for_storage,
    validate_token_encryption_configuration,
)
from app.views.admin import LegacyRouteSpec, configure_legacy_routes
from services.oauth_config import (
    OAuthConfigError,
    get_google_redirect_uri as oauth_get_google_redirect_uri,
    get_onedrive_redirect_uri as oauth_get_onedrive_redirect_uri,
    get_public_base_url as oauth_get_public_base_url,
)
from services.onedrive_service import (
    OneDriveServiceError,
    create_authorization_url as onedrive_create_authorization_url,
    exchange_code_for_token as onedrive_exchange_code_for_token,
    get_connected_account as onedrive_get_connected_account,
    get_ms_redirect_uri as onedrive_get_ms_redirect_uri,
    list_onedrive_folders as onedrive_list_folders,
    upload_zip_backup as onedrive_upload_zip_backup,
    upload_zip_backup_with_access_token as onedrive_upload_with_access_token,
    validate_configuration as onedrive_validate_configuration,
)
from utils.messages import flash


logger = logging.getLogger("main")


def _normalize_backup_directory(value: str, *, allow_empty: bool = False) -> str:
    text = str(value or "").strip()
    if not text:
        if allow_empty:
            return ""
        raise ValueError("Informe um caminho de pasta válido.")
    return os.path.abspath(os.path.normpath(text))

def save_backup_settings(conn, payload: dict[str, str]) -> dict[str, str]:
    ensure_backup_settings_schema(conn)
    local_backup_dir = _normalize_backup_directory(payload.get("local_backup_dir") or "")
    cloud_backup_dir = _normalize_backup_directory(payload.get("cloud_backup_dir") or "", allow_empty=True)
    external_backup_url = str(payload.get("external_backup_url") or "").strip()
    external_backup_token = str(payload.get("external_backup_token") or "").strip()
    external_backup_enabled = str(payload.get("external_backup_enabled") or "0") in {"1", "true", "True", "on", "yes"}

    try:
        cloud_sync_interval_seconds = max(0, int(str(payload.get("cloud_sync_interval_seconds") or "600").strip()))
    except ValueError as exc:
        raise ValueError("O intervalo de sincronização deve ser um número inteiro maior ou igual a zero.") from exc

    if external_backup_enabled:
        parsed = urlparse(external_backup_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Informe uma URL HTTP/HTTPS válida para o servidor externo.")

    os.makedirs(local_backup_dir, exist_ok=True)
    if cloud_backup_dir:
        os.makedirs(cloud_backup_dir, exist_ok=True)

    normalized = {
        "local_backup_dir": local_backup_dir,
        "cloud_backup_dir": cloud_backup_dir,
        "cloud_sync_interval_seconds": str(cloud_sync_interval_seconds),
        "external_backup_url": external_backup_url,
        "external_backup_token": external_backup_token,
        "external_backup_enabled": "1" if external_backup_enabled else "0",
    }

    for chave, valor in normalized.items():
        conn.execute(
            """
            INSERT INTO configuracoes_backup (chave, valor, atualizado_em)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor, atualizado_em = datetime('now')
            """,
            (chave, valor),
        )
    _apply_backup_settings_to_app(normalized)
    return normalized

_RETENTION_INTERVAL_OPTIONS = [
    ("0.5", "a cada 30 min"),
    ("1", "a cada 1 h"),
    ("2", "a cada 2 h"),
    ("4", "a cada 4 h"),
    ("6", "a cada 6 h"),
    ("8", "a cada 8 h"),
    ("12", "a cada 12 h"),
    ("24", "a cada 1 dia"),
    ("48", "a cada 2 dias"),
    ("72", "a cada 3 dias"),
    ("168", "a cada 1 semana"),
    ("336", "a cada 2 semanas"),
    ("730", "a cada 1 mês"),
    ("1460", "a cada 2 meses"),
    ("2190", "a cada 3 meses"),
]


def save_retention_policy(conn, payload: dict) -> dict[str, str]:
    ensure_backup_settings_schema(conn)
    defaults = _retention_policy_defaults()
    normalized: dict[str, str] = {}
    for key, default_val in defaults.items():
        raw = str(payload.get(key) or default_val).strip()
        if "interval" in key:
            try:
                v = float(raw)
                if v <= 0:
                    raise ValueError
                normalized[key] = raw
            except ValueError:
                raise ValueError(f"Intervalo inválido para a janela '{key}'.")
        else:
            try:
                v = int(raw)
                if v < 1:
                    raise ValueError
                normalized[key] = str(v)
            except ValueError:
                raise ValueError(f"Número de slots inválido para a janela '{key}'.")

    for chave, valor in normalized.items():
        conn.execute(
            """
            INSERT INTO configuracoes_backup (chave, valor, atualizado_em)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor, atualizado_em = datetime('now')
            """,
            (chave, valor),
        )
    return normalized

_CLOUD_FOLDER_PROVIDERS = {"google", "onedrive"}


def _normalize_cloud_folder_provider(provider: str) -> str:
    normalized = str(provider or "").strip().lower()
    if normalized not in _CLOUD_FOLDER_PROVIDERS:
        raise ValueError("Provedor inválido.")
    return normalized

def _save_cloud_drive_folder_setting(
    conn,
    *,
    provider: str,
    folder_id: str,
    folder_name: str,
    folder_path_label: str,
    drive_id: str = "",
) -> None:
    ensure_cloud_backup_schema(conn)
    safe_provider = _normalize_cloud_folder_provider(provider)
    safe_folder_id = (folder_id or "").strip()
    safe_folder_name = (folder_name or "").strip()
    safe_folder_path = (folder_path_label or "").strip()
    safe_drive_id = (drive_id or "").strip()
    conn.execute(
        """
        INSERT INTO cloud_drive_settings (provider, folder_id, folder_name, folder_path_label, drive_id, updated_at)
        VALUES (?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(provider) DO UPDATE SET
            folder_id = excluded.folder_id,
            folder_name = excluded.folder_name,
            folder_path_label = excluded.folder_path_label,
            drive_id = excluded.drive_id,
            updated_at = datetime('now')
        """,
        (
            safe_provider,
            safe_folder_id or None,
            safe_folder_name or None,
            safe_folder_path or None,
            safe_drive_id or None,
        ),
    )

def _get_cloud_drive_folder_setting(conn, provider: str) -> dict[str, str]:
    ensure_cloud_backup_schema(conn)
    safe_provider = _normalize_cloud_folder_provider(provider)
    row = conn.execute(
        """
        SELECT provider, folder_id, folder_name, folder_path_label, drive_id, updated_at
          FROM cloud_drive_settings
         WHERE provider = ?
         LIMIT 1
        """,
        (safe_provider,),
    ).fetchone()
    if not row:
        return {
            "provider": safe_provider,
            "folder_id": "",
            "folder_name": "",
            "folder_path_label": "",
            "drive_id": "",
            "updated_at": "",
        }
    return {
        "provider": str(row["provider"] or safe_provider),
        "folder_id": str(row["folder_id"] or ""),
        "folder_name": str(row["folder_name"] or ""),
        "folder_path_label": str(row["folder_path_label"] or ""),
        "drive_id": str(row["drive_id"] or ""),
        "updated_at": str(row["updated_at"] or ""),
    }

def _extract_oauth_scopes(token_json: str) -> list[str]:
    try:
        payload = json.loads(token_json or "{}")
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict):
        return []
    scopes = payload.get("scopes") or []
    if isinstance(scopes, list):
        return [str(item).strip() for item in scopes if str(item).strip()]
    if isinstance(scopes, str) and scopes.strip():
        return [scope.strip() for scope in scopes.split() if scope.strip()]
    return []

def _set_active_cloud_account(conn, provider: str, account_email: str, token_json: str) -> None:
    ensure_cloud_backup_schema(conn)
    encrypted_token_json = encrypt_token_json_for_storage(
        token_json,
        env=str(current_app.config.get("APP_ENV") or os.getenv("APP_ENV") or "development"),
    )
    conn.execute(
        "UPDATE cloud_accounts SET active = 0, updated_at = datetime('now') WHERE provider = ? AND active = 1",
        (provider,),
    )
    conn.execute(
        """
        INSERT INTO cloud_accounts (provider, account_email, token_json, connected_at, updated_at, active)
        VALUES (?, ?, ?, datetime('now'), datetime('now'), 1)
        """,
        (provider, (account_email or "").strip() or None, encrypted_token_json),
    )

def _get_active_cloud_account(conn, provider: str):
    ensure_cloud_backup_schema(conn)
    row = conn.execute(
        """
        SELECT id, provider, account_email, token_json, connected_at, updated_at, active
          FROM cloud_accounts
         WHERE provider = ? AND active = 1
      ORDER BY id DESC
        LIMIT 1
        """,
        (provider,),
    ).fetchone()
    if not row:
        return None

    payload = dict(row)
    try:
        payload["token_json"] = decrypt_token_json_from_storage(
            str(payload.get("token_json") or ""),
            env=str(current_app.config.get("APP_ENV") or os.getenv("APP_ENV") or "development"),
        )
        payload["token_json_available"] = True
        payload["token_json_error"] = ""
    except TokenEncryptionError as exc:
        logger.warning("Token OAuth indisponivel para %s: %s", provider, exc)
        payload["token_json"] = ""
        payload["token_json_available"] = False
        payload["token_json_error"] = str(exc)
    return payload

def _require_cloud_token_encryption_ready() -> None:
    validate_token_encryption_configuration(
        env=str(current_app.config.get("APP_ENV") or os.getenv("APP_ENV") or "development")
    )

def _update_cloud_account_token(
    conn,
    *,
    account_id: int,
    token_json: str,
    account_email: str | None = None,
) -> None:
    encrypted_token_json = encrypt_token_json_for_storage(
        token_json,
        env=str(current_app.config.get("APP_ENV") or os.getenv("APP_ENV") or "development"),
    )
    if account_email is None:
        conn.execute(
            "UPDATE cloud_accounts SET token_json = ?, updated_at = datetime('now') WHERE id = ?",
            (encrypted_token_json, int(account_id)),
        )
        return

    conn.execute(
        "UPDATE cloud_accounts SET token_json = ?, account_email = ?, updated_at = datetime('now') WHERE id = ?",
        (encrypted_token_json, account_email or None, int(account_id)),
    )

def _record_backup_log(
    conn,
    *,
    provider: str,
    file_name: str,
    file_size: int | None,
    status: str,
    error_message: str = "",
) -> None:
    ensure_cloud_backup_schema(conn)
    normalized_status = "sucesso" if status == "sucesso" else "erro"
    conn.execute(
        """
        INSERT INTO backup_logs (provider, file_name, file_size, status, error_message)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            provider,
            (file_name or "").strip() or None,
            int(file_size) if file_size not in (None, "") else None,
            normalized_status,
            (error_message or "")[:500],
        ),
    )

def _list_backup_logs(conn, *, provider: str | None = None, limit: int = 20):
    ensure_cloud_backup_schema(conn)
    safe_limit = max(1, min(int(limit or 20), 200))
    params: list[object] = []
    sql = "SELECT id, provider, file_name, file_size, status, error_message, created_at FROM backup_logs"
    if provider:
        sql += " WHERE provider = ?"
        params.append(provider)
    sql += " ORDER BY datetime(created_at) DESC, id DESC LIMIT ?"
    params.append(safe_limit)
    return conn.execute(sql, tuple(params)).fetchall()

def _format_drive_timestamp(ts_iso: str) -> str:
    if not ts_iso:
        return ""
    try:
        dt = datetime.datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
        local_dt = dt.astimezone()
        return local_dt.strftime("%d/%m/%Y às %H:%M")
    except Exception:
        return ts_iso

def _build_database_admin_context(conn):
    settings = _get_runtime_backup_settings(conn)
    oauth_context = _build_oauth_redirect_context()
    schema_status = get_schema_status(conn)
    backups = list_database_backups(_database_backup_locations(settings))
    for backup in backups:
        backup["size_label"] = _format_bytes_label(backup.get("size_bytes"))
        backup["schema_version"] = (backup.get("schema_status") or {}).get("schema_version")
        backup["target_schema_version"] = (backup.get("schema_status") or {}).get("target_schema_version")
    latest_cloud_backup = next((item for item in backups if item.get("location") == "cloud"), None)
    retention_policy = get_retention_policy(conn)
    drive_settings = get_drive_settings(conn)
    google_folder_setting = _get_cloud_drive_folder_setting(conn, "google")
    onedrive_folder_setting = _get_cloud_drive_folder_setting(conn, "onedrive")
    google_account = _get_active_cloud_account(conn, "google")
    onedrive_account = _get_active_cloud_account(conn, "onedrive")
    google_backup_logs = []
    onedrive_backup_logs = []
    for row in _list_backup_logs(conn, provider="google", limit=20):
        payload = dict(row)
        payload["size_label"] = _format_bytes_label(payload.get("file_size"))
        google_backup_logs.append(payload)
    for row in _list_backup_logs(conn, provider="onedrive", limit=20):
        payload = dict(row)
        payload["size_label"] = _format_bytes_label(payload.get("file_size"))
        onedrive_backup_logs.append(payload)

    google_connected = bool(google_account)
    google_legacy_connection_detected = bool(
        (drive_settings.get("gdrive_access_token") or "").strip()
    ) and not google_connected
    google_legacy_account_email = str(drive_settings.get("gdrive_account_email") or "")
    google_account_email = ""
    if google_account:
        google_account_email = str(google_account["account_email"] or "")
    if not google_account_email:
        google_account_email = google_legacy_account_email

    onedrive_connected = bool(onedrive_account)
    onedrive_account_email = ""
    if onedrive_account:
        onedrive_account_email = str(onedrive_account["account_email"] or "")
    if not onedrive_account_email:
        onedrive_account_email = str(drive_settings.get("onedrive_account_email") or "")

    google_folder_label = (
        google_folder_setting.get("folder_path_label")
        or google_folder_setting.get("folder_name")
        or ""
    )
    onedrive_folder_label = (
        onedrive_folder_setting.get("folder_path_label")
        or onedrive_folder_setting.get("folder_name")
        or ""
    )
    if google_folder_label:
        drive_settings["gdrive_dest_folder"] = google_folder_label
    if onedrive_folder_label:
        drive_settings["onedrive_dest_folder"] = onedrive_folder_label
    google_client_id = str(os.environ.get("GOOGLE_CLIENT_ID") or "").strip()
    google_picker_api_key = str(os.environ.get("GOOGLE_PICKER_API_KEY") or "").strip()
    google_app_id = str(os.environ.get("GOOGLE_APP_ID") or "").strip()

    return {
        "schema_status": schema_status,
        "backups": backups,
        "backup_settings": settings,
        "local_backup_dir": settings.get("local_backup_dir") or current_app.config.get("LOCAL_BACKUP_DIR"),
        "cloud_backup_dir": settings.get("cloud_backup_dir") or current_app.config.get("CLOUD_BACKUP_DIR"),
        "cloud_sync_interval_seconds": settings.get("cloud_sync_interval_seconds") or current_app.config.get("CLOUD_SYNC_INTERVAL_SECONDS", 300),
        "external_backup_url": settings.get("external_backup_url") or "",
        "external_backup_enabled": str(settings.get("external_backup_enabled") or "0") in {"1", "true", "True"},
        "latest_cloud_backup": latest_cloud_backup,
        "retention_policy": retention_policy,
        "retention_windows_meta": _RETENTION_WINDOWS_META,
        "retention_interval_options": _RETENTION_INTERVAL_OPTIONS,
        "drive_settings": drive_settings,
        "gdrive_configured": bool(os.environ.get("GOOGLE_CLIENT_ID")),
        "onedrive_configured": bool(
            (os.environ.get("MS_CLIENT_ID") or "").strip()
            or (os.environ.get("ONEDRIVE_CLIENT_ID") or "").strip()
        ),
        "gdrive_connected": google_connected,
        "gdrive_legacy_connection_detected": google_legacy_connection_detected,
        "gdrive_legacy_account_email": google_legacy_account_email,
        "onedrive_connected": onedrive_connected,
        "gdrive_last_upload_label": _format_drive_timestamp(drive_settings.get("gdrive_last_upload_at") or ""),
        "onedrive_last_upload_label": _format_drive_timestamp(drive_settings.get("onedrive_last_upload_at") or ""),
        "google_drive_connected": google_connected,
        "google_drive_account_email": google_account_email,
        "google_client_id": google_client_id,
        "google_picker_api_key": google_picker_api_key,
        "google_app_id": google_app_id,
        "google_picker_configured": bool(google_client_id and google_picker_api_key and google_app_id),
        "google_backup_logs": google_backup_logs,
        "onedrive_account_email": onedrive_account_email,
        "onedrive_backup_logs": onedrive_backup_logs,
        "google_folder_setting": google_folder_setting,
        "onedrive_folder_setting": onedrive_folder_setting,
        "google_folder_label": google_folder_label or (drive_settings.get("gdrive_dest_folder") or "Backups/sistema"),
        "onedrive_folder_label": onedrive_folder_label or (drive_settings.get("onedrive_dest_folder") or "SGAA - Backups"),
        "oauth_public_base_url": oauth_context["oauth_public_base_url"],
        "google_oauth_callback_uri": oauth_context["google_oauth_callback_uri"],
        "onedrive_oauth_callback_uri": oauth_context["onedrive_oauth_callback_uri"],
        "oauth_config_error": oauth_context["oauth_config_error"],
    }

@admin_required
def admin_banco_dados():
    conn = get_db_connection()
    context = _build_database_admin_context(conn)
    return render_template("admin_banco_dados.html", **context)

def _maybe_redirect_to_oauth_callback_host(redirect_uri: str) -> str:
    parsed_redirect = urlsplit((redirect_uri or "").strip())
    if parsed_redirect.scheme not in {"http", "https"} or not parsed_redirect.netloc:
        return ""

    current_host = (request.host or "").strip().lower()
    target_host = parsed_redirect.netloc.strip().lower()
    if not current_host or current_host == target_host:
        return ""

    parsed_current = urlsplit(request.url)
    return parsed_current._replace(
        scheme=parsed_redirect.scheme,
        netloc=parsed_redirect.netloc,
    ).geturl()

def _clear_legacy_oauth_session() -> None:
    removed = False
    for key in ("oauth_provider", "oauth_state", "oauth_verifier"):
        if key in session:
            session.pop(key, None)
            removed = True
    if removed:
        session.modified = True

def _resolve_onedrive_redirect_uri() -> str:
    return onedrive_get_ms_redirect_uri()

def _resolve_google_redirect_uri() -> str:
    return google_get_redirect_uri()

def _onedrive_connect_diagnostics(redirect_uri: str = "") -> dict[str, str]:
    try:
        import msal  # noqa: F401
        msal_imported = "sim"
    except Exception:
        msal_imported = "não"

    return {
        "APP_ENV": str(current_app.config.get("APP_ENV") or os.getenv("APP_ENV") or ""),
        "APP_PUBLIC_BASE_URL": (os.getenv("APP_PUBLIC_BASE_URL") or "").strip(),
        "MS_TENANT_ID_presente": "sim" if (os.getenv("MS_TENANT_ID") or "").strip() else "não",
        "MS_CLIENT_ID_presente": "sim" if (os.getenv("MS_CLIENT_ID") or "").strip() else "não",
        "MS_CLIENT_SECRET_presente": "sim" if (os.getenv("MS_CLIENT_SECRET") or "").strip() else "não",
        "MS_GRAPH_BASE_URL_presente": "sim" if (os.getenv("MS_GRAPH_BASE_URL") or "").strip() else "não",
        "redirect_uri_calculado": redirect_uri,
        "msal_importado": msal_imported,
    }

def _build_oauth_redirect_context() -> dict[str, str]:
    context = {
        "oauth_public_base_url": "",
        "google_oauth_callback_uri": "",
        "onedrive_oauth_callback_uri": "",
        "oauth_config_error": "",
    }
    try:
        context["oauth_public_base_url"] = oauth_get_public_base_url()
        context["google_oauth_callback_uri"] = oauth_get_google_redirect_uri()
        context["onedrive_oauth_callback_uri"] = oauth_get_onedrive_redirect_uri()
    except OAuthConfigError as exc:
        context["oauth_config_error"] = str(exc)
    except Exception as exc:
        context["oauth_config_error"] = f"Falha ao resolver callbacks OAuth: {exc}"
    return context

@admin_required
def admin_backup_google_connect():
    try:
        redirect_uri = _resolve_google_redirect_uri()
    except GoogleDriveServiceError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin_banco_dados"))

    host_redirect = _maybe_redirect_to_oauth_callback_host(redirect_uri)
    if host_redirect:
        return redirect(host_redirect)

    try:
        _require_cloud_token_encryption_ready()
    except TokenEncryptionConfigError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin_banco_dados"))

    _clear_legacy_oauth_session()
    state = secrets.token_urlsafe(24)
    session["google_oauth_state"] = state
    session.modified = True

    try:
        auth_url, generated_state = google_create_authorization_url(
            state=state,
            is_debug=not current_app.config.get("IS_PRODUCTION", False),
        )
        session["google_oauth_state"] = generated_state or state
        session.modified = True
    except GoogleDriveServiceError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin_banco_dados"))
    except Exception as exc:
        logger.warning("Falha ao iniciar OAuth Google Drive: %s", exc)
        flash(f"Falha ao iniciar conexão com Google Drive: {exc}", "error")
        return redirect(url_for("admin_banco_dados"))

    return redirect(auth_url)

@admin_required
def google_callback():
    _clear_legacy_oauth_session()
    error = request.args.get("error")
    if error:
        error_description = (request.args.get("error_description") or "").strip()
        if error == "access_denied" and (
            "test" in error_description.lower()
            or "tester" in error_description.lower()
            or "verification" in error_description.lower()
        ):
            flash(
                "Google OAuth bloqueado: o aplicativo está em modo de teste. "
                "Adicione este e-mail como usuário de teste no Google Cloud Console (OAuth consent screen).",
                "error",
            )
            return redirect(url_for("admin_banco_dados"))
        flash(f"Autorização negada: {error}", "error")
        return redirect(url_for("admin_banco_dados"))

    state = request.args.get("state") or ""
    code = request.args.get("code") or ""
    expected_state = session.pop("google_oauth_state", "")
    session.modified = True

    if not state or not expected_state or not secrets.compare_digest(state, expected_state):
        flash("Estado OAuth inválido. Reinicie a conexão Google.", "error")
        return redirect(url_for("admin_banco_dados"))
    if not code:
        flash("Resposta OAuth incompleta (code ausente).", "error")
        return redirect(url_for("admin_banco_dados"))

    try:
        _resolve_google_redirect_uri()
    except GoogleDriveServiceError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin_banco_dados"))

    conn = get_db_connection()
    try:
        token_json, account_email = google_exchange_code_for_token(
            code=code,
            is_debug=not current_app.config.get("IS_PRODUCTION", False),
        )
        _set_active_cloud_account(conn, "google", account_email, token_json)
        _save_drive_config(
            conn,
            {
                "gdrive_account_email": account_email,
                "gdrive_last_upload_error": "",
            },
        )
        conn.commit()
        if account_email:
            flash(f"Google Drive conectado como {account_email}.", "success")
        else:
            flash("Google Drive conectado com sucesso.", "success")
    except (GoogleDriveServiceError, TokenEncryptionConfigError) as exc:
        conn.rollback()
        logger.warning("Falha no callback OAuth Google Drive: %s", exc)
        flash(f"Falha ao conectar Google Drive: {exc}", "error")
    except Exception as exc:
        conn.rollback()
        logger.warning("Erro inesperado no callback OAuth Google Drive: %s", exc)
        flash(f"Falha ao conectar Google Drive: {exc}", "error")

    return redirect(url_for("admin_banco_dados"))

@admin_required
def admin_backup_google_upload():
    conn = get_db_connection()
    google_account = _get_active_cloud_account(conn, "google")
    if not google_account:
        drive_settings = get_drive_settings(conn)
        if (drive_settings.get("gdrive_access_token") or "").strip():
            flash("Conexão antiga detectada. Reconecte o Google Drive.", "error")
        else:
            flash("Nenhuma conta Google conectada. Conecte o Google Drive antes de enviar.", "error")
        return redirect(url_for("admin_banco_dados"))

    if not bool(google_account.get("token_json_available", True)):
        flash(
            str(
                google_account.get("token_json_error")
                or "Token OAuth do Google Drive indisponivel. Reconecte a conta."
            ),
            "error",
        )
        return redirect(url_for("admin_banco_dados"))

    try:
        _require_cloud_token_encryption_ready()
    except TokenEncryptionConfigError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin_banco_dados"))

    backup_artifacts = None
    file_name = ""
    file_size = None
    try:
        backup_artifacts = create_sqlite_backup_zip(app_db.DATABASE)
        file_name = str(backup_artifacts.get("file_name") or "")
        file_size = int(backup_artifacts.get("file_size") or 0)
        google_folder_setting = _get_cloud_drive_folder_setting(conn, "google")
        selected_google_folder_id = str(google_folder_setting.get("folder_id") or "").strip()

        upload_result = google_upload_zip_backup(
            token_json=str(google_account["token_json"] or ""),
            zip_path=str(backup_artifacts["zip_path"]),
            file_name=file_name,
            folder_name="SGAA - Backups",
            folder_id=selected_google_folder_id or None,
        )
        updated_token_json = str(upload_result.get("token_json") or "")
        if updated_token_json:
            _update_cloud_account_token(
                conn,
                account_id=int(google_account["id"]),
                token_json=updated_token_json,
            )

        now_iso = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        _save_drive_config(
            conn,
            {
                "gdrive_last_upload_at": now_iso,
                "gdrive_last_upload_error": "",
                "gdrive_account_email": str(google_account["account_email"] or ""),
            },
        )
        _record_backup_log(
            conn,
            provider="google",
            file_name=file_name,
            file_size=file_size,
            status="sucesso",
        )
        conn.commit()
        flash("Backup enviado para o Google Drive com sucesso.", "success")
    except (BackupServiceError, GoogleDriveServiceError, TokenEncryptionConfigError) as exc:
        conn.rollback()
        error_message = str(exc)
        safe_lower_error = error_message.lower()
        folder_access_error = any(
            marker in safe_lower_error
            for marker in (
                "forbidden",
                "permission",
                "insufficient",
                "not found",
                "403",
                "404",
                "cannot find",
            )
        )
        try:
            _record_backup_log(
                conn,
                provider="google",
                file_name=file_name,
                file_size=file_size,
                status="erro",
                error_message=error_message,
            )
            _save_drive_config(conn, {"gdrive_last_upload_error": error_message[:200]})
            conn.commit()
        except Exception:
            conn.rollback()
        logger.warning("Falha no backup manual Google Drive: %s", exc)
        if folder_access_error:
            flash(
                "Não foi possível enviar o backup para a pasta selecionada. "
                "Verifique se ela pertence à conta Google conectada.",
                "error",
            )
        else:
            flash(f"Falha ao enviar backup para o Google Drive: {exc}", "error")
    except Exception as exc:
        conn.rollback()
        error_message = str(exc)
        try:
            _record_backup_log(
                conn,
                provider="google",
                file_name=file_name,
                file_size=file_size,
                status="erro",
                error_message=error_message,
            )
            _save_drive_config(conn, {"gdrive_last_upload_error": error_message[:200]})
            conn.commit()
        except Exception:
            conn.rollback()
        logger.warning("Erro inesperado no backup manual Google Drive: %s", exc)
        flash(f"Falha ao enviar backup para o Google Drive: {exc}", "error")
    finally:
        cleanup_backup_artifacts(backup_artifacts)

    return redirect(url_for("admin_banco_dados"))

@admin_required
def admin_backup_onedrive_connect():
    diagnostics = _onedrive_connect_diagnostics("")
    try:
        onedrive_redirect_uri = _resolve_onedrive_redirect_uri()
    except OneDriveServiceError as exc:
        current_app.logger.exception("Falha ao iniciar conexão OneDrive")
        current_app.logger.info(
            (
                "OneDrive connect diagnostics: APP_ENV=%s APP_PUBLIC_BASE_URL=%s "
                "MS_TENANT_ID presente=%s MS_CLIENT_ID presente=%s "
                "MS_CLIENT_SECRET presente=%s MS_GRAPH_BASE_URL presente=%s "
                "redirect_uri=%s msal importado=%s"
            ),
            diagnostics["APP_ENV"],
            diagnostics["APP_PUBLIC_BASE_URL"],
            diagnostics["MS_TENANT_ID_presente"],
            diagnostics["MS_CLIENT_ID_presente"],
            diagnostics["MS_CLIENT_SECRET_presente"],
            diagnostics["MS_GRAPH_BASE_URL_presente"],
            diagnostics["redirect_uri_calculado"],
            diagnostics["msal_importado"],
        )
        flash(str(exc), "error")
        return redirect(url_for("admin_banco_dados"))

    diagnostics = _onedrive_connect_diagnostics(onedrive_redirect_uri)
    current_app.logger.info(
        (
            "OneDrive connect diagnostics: APP_ENV=%s APP_PUBLIC_BASE_URL=%s "
            "MS_TENANT_ID presente=%s MS_CLIENT_ID presente=%s "
            "MS_CLIENT_SECRET presente=%s MS_GRAPH_BASE_URL presente=%s "
            "redirect_uri=%s msal importado=%s"
        ),
        diagnostics["APP_ENV"],
        diagnostics["APP_PUBLIC_BASE_URL"],
        diagnostics["MS_TENANT_ID_presente"],
        diagnostics["MS_CLIENT_ID_presente"],
        diagnostics["MS_CLIENT_SECRET_presente"],
        diagnostics["MS_GRAPH_BASE_URL_presente"],
        diagnostics["redirect_uri_calculado"],
        diagnostics["msal_importado"],
    )
    current_app.logger.info(
        "OneDrive redirect URI OAuth resolvido: %s",
        onedrive_redirect_uri,
    )
    logger.info(
        "OneDrive redirect URI OAuth resolvido: %s",
        onedrive_redirect_uri,
    )
    host_redirect = _maybe_redirect_to_oauth_callback_host(onedrive_redirect_uri)
    if host_redirect:
        return redirect(host_redirect)

    try:
        _require_cloud_token_encryption_ready()
    except TokenEncryptionConfigError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin_banco_dados"))

    _clear_legacy_oauth_session()
    state = secrets.token_urlsafe(24)
    session["onedrive_oauth_state"] = state
    session.pop("onedrive_oauth_verifier", None)
    session.pop("onedrive_oauth_flow_mode", None)
    session.modified = True

    try:
        auth_url = onedrive_create_authorization_url(state=state)
        session["onedrive_oauth_flow_mode"] = "msal"
        session.modified = True
    except OneDriveServiceError as exc:
        current_app.logger.exception("Falha ao iniciar conexão OneDrive")
        flash(str(exc), "error")
        return redirect(url_for("admin_banco_dados"))
    except Exception as exc:
        current_app.logger.exception("Falha ao iniciar conexão OneDrive")
        if isinstance(exc, ModuleNotFoundError) and "msal" in str(exc).lower():
            flash("Biblioteca MSAL não instalada. Execute pip install -r requirements.txt.", "error")
        else:
            flash("Falha ao iniciar conexão com OneDrive.", "error")
        return redirect(url_for("admin_banco_dados"))

    return redirect(auth_url)

@admin_required
def onedrive_callback():
    _clear_legacy_oauth_session()
    has_code = bool((request.args.get("code") or "").strip())
    has_state = bool((request.args.get("state") or "").strip())
    current_app.logger.info(
        "OneDrive callback recebido: has_code=%s has_state=%s",
        has_code,
        has_state,
    )

    error = (request.args.get("error") or "").strip()
    if error:
        current_app.logger.warning(
            "OneDrive callback retornou erro do provedor: %s",
            error.lower(),
        )
        if error.lower() == "access_denied":
            flash("Autorização do OneDrive cancelada pelo usuário.", "error")
        else:
            flash("Falha na autorização Microsoft para OneDrive.", "error")
        return redirect(url_for("admin_banco_dados"))

    state = request.args.get("state") or ""
    code = request.args.get("code") or ""
    expected_state = session.pop("onedrive_oauth_state", "")
    verifier = session.pop("onedrive_oauth_verifier", "")
    flow_mode = session.pop("onedrive_oauth_flow_mode", "msal")
    session.modified = True

    state_match = bool(state and expected_state and secrets.compare_digest(state, expected_state))
    current_app.logger.info("OneDrive state validado: state_match=%s", state_match)
    if not state_match:
        flash("Sessão OAuth expirada ou inválida. Tente conectar novamente.", "error")
        return redirect(url_for("admin_banco_dados"))

    if not code:
        flash("Resposta OAuth incompleta (código ausente).", "error")
        return redirect(url_for("admin_banco_dados"))

    try:
        redirect_uri = _resolve_onedrive_redirect_uri()
    except OneDriveServiceError as exc:
        current_app.logger.warning("OneDrive callback com configuracao invalida: %s", exc)
        flash(str(exc), "error")
        return redirect(url_for("admin_banco_dados"))

    current_app.logger.info(
        "OneDrive callback usando redirect URI resolvido: %s",
        redirect_uri,
    )
    try:
        onedrive_validate_configuration()
    except OneDriveServiceError as exc:
        current_app.logger.warning("OneDrive callback com configuracao Microsoft invalida: %s", exc)
        flash(str(exc), "error")
        return redirect(url_for("admin_banco_dados"))

    conn = get_db_connection()
    try:
        if flow_mode == "legacy_pkce":
            client_id = (
                (os.environ.get("ONEDRIVE_CLIENT_ID") or "").strip()
                or (os.environ.get("MS_CLIENT_ID") or "").strip()
            )
            if not verifier:
                raise OneDriveServiceError("Sessao OAuth expirada. Inicie a conexao OneDrive novamente.")
            if not client_id:
                raise OneDriveServiceError("ONEDRIVE_CLIENT_ID/MS_CLIENT_ID ausente para OAuth OneDrive.")

            current_app.logger.info("OneDrive token exchange iniciado: flow_mode=legacy_pkce")
            tokens = _cd.onedrive_exchange(client_id, code, redirect_uri, verifier)
            access_token = str(tokens.get("access_token") or "").strip()
            current_app.logger.info("OneDrive token obtido com sucesso: %s", bool(access_token))
            if not access_token:
                error_code = str(tokens.get("error") or "").strip().lower() or "unknown_error"
                current_app.logger.warning("OneDrive OAuth falhou: %s", error_code)
                raise OneDriveServiceError("Falha na autenticacao com Microsoft/OneDrive.")

            current_app.logger.info("OneDrive consulta /me iniciada")
            info = _cd.onedrive_userinfo(access_token)
            account_email = str(info.get("mail") or info.get("userPrincipalName") or "").strip()
            current_app.logger.info("OneDrive e-mail obtido: %s", bool(account_email))

            expires_in = int(tokens.get("expires_in") or 3600)
            refresh_token = str(tokens.get("refresh_token") or "").strip()
            expires_at = _cd.token_expires_at(expires_in)

            legacy_payload = {
                "version": 1,
                "provider": "onedrive",
                "mode": "legacy_pkce",
                "account_email": account_email,
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_at": expires_at,
                "updated_at": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            }
            token_json = json.dumps(legacy_payload, ensure_ascii=False)
            _save_drive_config(
                conn,
                {
                    "onedrive_access_token": access_token,
                    "onedrive_refresh_token": refresh_token,
                    "onedrive_expires_at": expires_at,
                    "onedrive_account_email": account_email,
                    "onedrive_last_upload_error": "",
                },
            )
        else:
            current_app.logger.info("OneDrive token exchange iniciado: flow_mode=msal")
            token_json, account_email = onedrive_exchange_code_for_token(code=code)
            current_app.logger.info("OneDrive token obtido com sucesso: %s", bool(token_json))
            current_app.logger.info("OneDrive consulta /me iniciada")
            account_info = onedrive_get_connected_account(token_json=token_json)
            token_json = str(account_info.get("token_json") or token_json)
            account_email = str(account_info.get("account_email") or account_email)
            current_app.logger.info("OneDrive e-mail obtido: %s", bool(account_email))

        current_app.logger.info("OneDrive salvamento cloud_accounts iniciado")
        _set_active_cloud_account(conn, "onedrive", account_email, token_json)
        _save_drive_config(
            conn,
            {
                "onedrive_account_email": account_email,
                "onedrive_last_upload_error": "",
            },
        )
        conn.commit()
        current_app.logger.info("OneDrive conexao salva com sucesso")
        if account_email:
            flash(f"OneDrive conectado como {account_email}.", "success")
        else:
            flash("OneDrive conectado com sucesso.", "success")
    except (OneDriveServiceError, TokenEncryptionConfigError) as exc:
        conn.rollback()
        current_app.logger.warning("Falha no callback OAuth OneDrive: %s", exc)
        flash(str(exc), "error")
    except Exception:
        conn.rollback()
        current_app.logger.exception("Erro no callback OneDrive")
        flash("Erro ao conectar o OneDrive. Veja os logs do servidor.", "error")
        return redirect(url_for("admin_banco_dados"))

    return redirect(url_for("admin_banco_dados"))

@admin_required
def admin_backup_onedrive_upload():
    conn = get_db_connection()
    onedrive_account = _get_active_cloud_account(conn, "onedrive")
    if not onedrive_account:
        flash("Nenhuma conta OneDrive conectada. Conecte o OneDrive antes de enviar.", "error")
        return redirect(url_for("admin_banco_dados"))

    if not bool(onedrive_account.get("token_json_available", True)):
        flash(
            str(
                onedrive_account.get("token_json_error")
                or "Token OAuth do OneDrive indisponivel. Reconecte a conta."
            ),
            "error",
        )
        return redirect(url_for("admin_banco_dados"))

    try:
        _require_cloud_token_encryption_ready()
    except TokenEncryptionConfigError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin_banco_dados"))

    backup_artifacts = None
    file_name = ""
    file_size = None
    try:
        backup_artifacts = create_sqlite_backup_zip(app_db.DATABASE)
        file_name = str(backup_artifacts.get("file_name") or "")
        file_size = int(backup_artifacts.get("file_size") or 0)
        onedrive_folder_setting = _get_cloud_drive_folder_setting(conn, "onedrive")
        selected_onedrive_folder_id = str(onedrive_folder_setting.get("folder_id") or "").strip()
        selected_onedrive_drive_id = str(onedrive_folder_setting.get("drive_id") or "").strip()

        token_json_raw = str(onedrive_account["token_json"] or "")
        token_payload: dict[str, object] = {}
        try:
            loaded = json.loads(token_json_raw or "{}")
            if isinstance(loaded, dict):
                token_payload = loaded
        except json.JSONDecodeError:
            token_payload = {}

        legacy_mode = bool(
            token_payload.get("mode") == "legacy_pkce"
            or (
                token_payload.get("provider") == "onedrive"
                and token_payload.get("access_token")
                and not token_payload.get("msal_cache")
            )
        )

        if legacy_mode:
            client_id = (
                (os.environ.get("ONEDRIVE_CLIENT_ID") or "").strip()
                or (os.environ.get("MS_CLIENT_ID") or "").strip()
            )
            if not client_id:
                raise OneDriveServiceError("ONEDRIVE_CLIENT_ID/MS_CLIENT_ID ausente para refresh do OneDrive.")

            access_token = str(token_payload.get("access_token") or "").strip()
            refresh_token = str(token_payload.get("refresh_token") or "").strip()
            expires_at = str(token_payload.get("expires_at") or "").strip()

            if not access_token:
                raise OneDriveServiceError("Token OAuth do OneDrive inválido. Reconecte a conta.")

            if _cd.is_token_expired(expires_at):
                if not refresh_token:
                    raise OneDriveServiceError("Token expirado e sem refresh válido. Reconecte o OneDrive.")
                refreshed_tokens = _cd.onedrive_refresh(client_id, refresh_token)
                access_token = str(refreshed_tokens.get("access_token") or "").strip()
                if not access_token:
                    raise OneDriveServiceError("Falha ao renovar token OAuth do OneDrive.")
                refresh_token = str(refreshed_tokens.get("refresh_token") or refresh_token).strip()
                expires_at = _cd.token_expires_at(int(refreshed_tokens.get("expires_in") or 3600))

            onedrive_upload_with_access_token(
                access_token=access_token,
                zip_path=str(backup_artifacts["zip_path"]),
                file_name=file_name,
                folder_name="SGAA - Backups",
                folder_id=selected_onedrive_folder_id or None,
                drive_id=selected_onedrive_drive_id or None,
            )
            profile = _cd.onedrive_userinfo(access_token)
            connected_email = str(
                profile.get("mail")
                or profile.get("userPrincipalName")
                or token_payload.get("account_email")
                or onedrive_account["account_email"]
                or ""
            ).strip()

            token_payload.update(
                {
                    "version": int(token_payload.get("version") or 1),
                    "provider": "onedrive",
                    "mode": "legacy_pkce",
                    "account_email": connected_email,
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "expires_at": expires_at,
                    "updated_at": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                }
            )
            refreshed_token_json = json.dumps(token_payload, ensure_ascii=False)
        else:
            upload_result = onedrive_upload_zip_backup(
                token_json=token_json_raw,
                zip_path=str(backup_artifacts["zip_path"]),
                file_name=file_name,
                folder_name="SGAA - Backups",
                folder_id=selected_onedrive_folder_id or None,
                drive_id=selected_onedrive_drive_id or None,
            )
            refreshed_token_json = str(upload_result.get("token_json") or "")
            connected_email = str(upload_result.get("account_email") or onedrive_account["account_email"] or "")

        if refreshed_token_json:
            _update_cloud_account_token(
                conn,
                account_id=int(onedrive_account["id"]),
                token_json=refreshed_token_json,
                account_email=connected_email or None,
            )

        now_iso = (
            datetime.datetime.now(datetime.timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
        drive_updates = {
            "onedrive_last_upload_at": now_iso,
            "onedrive_last_upload_error": "",
            "onedrive_account_email": connected_email,
        }
        if legacy_mode:
            drive_updates.update(
                {
                    "onedrive_access_token": str(token_payload.get("access_token") or ""),
                    "onedrive_refresh_token": str(token_payload.get("refresh_token") or ""),
                    "onedrive_expires_at": str(token_payload.get("expires_at") or ""),
                }
            )
        _save_drive_config(conn, drive_updates)
        _record_backup_log(
            conn,
            provider="onedrive",
            file_name=file_name,
            file_size=file_size,
            status="sucesso",
        )
        conn.commit()
        flash("Backup enviado para o OneDrive com sucesso.", "success")
    except BackupServiceError as exc:
        conn.rollback()
        error_message = str(exc)
        try:
            _record_backup_log(
                conn,
                provider="onedrive",
                file_name=file_name,
                file_size=file_size,
                status="erro",
                error_message=error_message,
            )
            _save_drive_config(conn, {"onedrive_last_upload_error": error_message[:200]})
            conn.commit()
        except Exception:
            conn.rollback()
        logger.warning("Falha no backup local para OneDrive: %s", exc)
        flash("Falha no backup local antes do envio para OneDrive.", "error")
    except (OneDriveServiceError, TokenEncryptionConfigError) as exc:
        conn.rollback()
        error_message = str(exc)
        try:
            _record_backup_log(
                conn,
                provider="onedrive",
                file_name=file_name,
                file_size=file_size,
                status="erro",
                error_message=error_message,
            )
            _save_drive_config(conn, {"onedrive_last_upload_error": error_message[:200]})
            conn.commit()
        except Exception:
            conn.rollback()
        logger.warning("Falha no upload manual OneDrive: %s", exc)
        flash(str(exc), "error")
    except Exception as exc:
        conn.rollback()
        error_message = "Falha inesperada no upload para OneDrive."
        try:
            _record_backup_log(
                conn,
                provider="onedrive",
                file_name=file_name,
                file_size=file_size,
                status="erro",
                error_message=error_message,
            )
            _save_drive_config(conn, {"onedrive_last_upload_error": error_message[:200]})
            conn.commit()
        except Exception:
            conn.rollback()
        logger.warning("Erro inesperado no backup manual OneDrive: %s", type(exc).__name__)
        flash(error_message, "error")
    finally:
        cleanup_backup_artifacts(backup_artifacts)

    return redirect(url_for("admin_banco_dados"))

def _get_cloud_folder_account(conn, provider: str):
    account = _get_active_cloud_account(conn, provider)
    if not account:
        if provider == "google":
            return None, "Conecte o Google Drive antes de selecionar a pasta."
        return None, "Conecte o OneDrive antes de selecionar a pasta."
    if not bool(account.get("token_json_available", True)):
        message = str(
            account.get("token_json_error")
            or (
                "Token OAuth do Google Drive indisponivel. Reconecte a conta."
                if provider == "google"
                else "Token OAuth do OneDrive indisponivel. Reconecte a conta."
            )
        )
        return None, message
    return account, ""

@admin_required
def admin_backup_cloud_folders(provider):
    try:
        safe_provider = _normalize_cloud_folder_provider(provider)
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400

    parent_id = (request.args.get("parent_id") or "").strip() or "root"
    drive_id = (request.args.get("drive_id") or "").strip()
    conn = get_db_connection()
    account, message = _get_cloud_folder_account(conn, safe_provider)
    if not account:
        return jsonify({"ok": False, "message": message}), 400

    scopes = _extract_oauth_scopes(str(account.get("token_json") or ""))
    logger.info(
        "Cloud folder picker request: provider=%s has_account=%s has_token=%s token_available=%s scopes=%s",
        safe_provider,
        True,
        bool(account.get("token_json")),
        bool(account.get("token_json_available", True)),
        scopes,
    )

    try:
        if safe_provider == "google":
            list_result = google_list_folders(
                token_json=str(account["token_json"] or ""),
                parent_id=parent_id,
            )
        else:
            list_result = onedrive_list_folders(
                token_json=str(account["token_json"] or ""),
                parent_id=parent_id,
                drive_id=drive_id or None,
            )

        updated_token_json = str(list_result.get("token_json") or "")
        if updated_token_json and updated_token_json != str(account.get("token_json") or ""):
            _update_cloud_account_token(
                conn,
                account_id=int(account["id"]),
                token_json=updated_token_json,
                account_email=str(list_result.get("account_email") or account.get("account_email") or "") or None,
            )
            conn.commit()

        folders = []
        for item in list_result.get("folders", []) if isinstance(list_result, dict) else []:
            if not isinstance(item, dict):
                continue
            folder_id = str(item.get("id") or "").strip()
            folder_name = str(item.get("name") or "").strip()
            folder_path_label = str(item.get("path_label") or folder_name).strip()
            if not folder_id or not folder_name:
                continue
            folders.append(
                {
                    "id": folder_id,
                    "drive_id": str(item.get("drive_id") or "").strip() or None,
                    "name": folder_name,
                    "path_label": folder_path_label or folder_name,
                }
            )

        logger.info(
            "Listagem de pastas remotas: provider=%s parent=%s total=%s",
            safe_provider,
            parent_id,
            len(folders),
        )
        response_payload = {
            "ok": True,
            "provider": safe_provider,
            "parent_id": str(list_result.get("parent_id") or parent_id),
            "drive_id": str(list_result.get("drive_id") or drive_id) or None,
            "folders": folders,
        }
        google_scope_limited = (
            safe_provider == "google"
            and parent_id == "root"
            and not folders
            and "https://www.googleapis.com/auth/drive.file" in scopes
            and not any(
                scope in scopes
                for scope in (
                    "https://www.googleapis.com/auth/drive.metadata.readonly",
                    "https://www.googleapis.com/auth/drive.readonly",
                    "https://www.googleapis.com/auth/drive",
                )
            )
        )
        if google_scope_limited:
            response_payload["debug_code"] = "GOOGLE_SCOPE_LIMITED"
            response_payload["notice"] = (
                "Com a permissão segura atual, o sistema não pode navegar por todo o Google Drive. "
                "Use a pasta padrão do aplicativo ou implemente o Google Picker para escolher uma pasta manualmente."
            )
            logger.info(
                "Google folder picker limitado por escopo: provider=%s parent=%s scopes=%s",
                safe_provider,
                parent_id,
                scopes,
            )
        return jsonify(response_payload)
    except GoogleDriveServiceError as exc:
        conn.rollback()
        logger.warning(
            "Falha ao listar pastas remotas Google: provider=%s parent=%s erro=%s",
            safe_provider,
            parent_id,
            exc,
        )
        return jsonify({"ok": False, "message": str(exc)}), 400
    except OneDriveServiceError as exc:
        conn.rollback()
        logger.warning(
            "Falha ao listar pastas remotas OneDrive: provider=%s parent=%s debug_code=%s http_status=%s erro=%s",
            safe_provider,
            parent_id,
            getattr(exc, "debug_code", ""),
            getattr(exc, "http_status", None),
            exc,
        )
        if getattr(exc, "debug_code", "") == "GRAPH_PERMISSION_DENIED":
            return jsonify(
                {
                    "ok": False,
                    "message": "Permissão insuficiente para listar as pastas do OneDrive. Reconecte e conceda acesso aos arquivos.",
                    "debug_code": "GRAPH_PERMISSION_DENIED",
                }
            ), 403
        if getattr(exc, "debug_code", "") == "GRAPH_TOKEN_INVALID":
            return jsonify(
                {
                    "ok": False,
                    "message": "A sessão do OneDrive expirou. Reconecte o provedor e tente novamente.",
                    "debug_code": "GRAPH_TOKEN_INVALID",
                }
            ), 401
        return jsonify(
            {
                "ok": False,
                "message": "Não foi possível listar as pastas do OneDrive.",
                "debug_code": "GRAPH_LIST_CHILDREN_FAILED",
            }
        ), 502
    except (TokenEncryptionError, TokenEncryptionConfigError) as exc:
        conn.rollback()
        logger.warning(
            "Falha de token ao listar pastas remotas: provider=%s parent=%s erro=%s",
            safe_provider,
            parent_id,
            exc,
        )
        return jsonify({"ok": False, "message": str(exc)}), 400
    except Exception:
        conn.rollback()
        logger.exception("Erro inesperado ao listar pastas remotas: provider=%s", safe_provider)
        return jsonify({"ok": False, "message": "Falha ao listar pastas remotas."}), 500

@admin_required
def admin_backup_cloud_folder(provider):
    try:
        safe_provider = _normalize_cloud_folder_provider(provider)
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400

    conn = get_db_connection()
    if request.method == "GET":
        current_setting = _get_cloud_drive_folder_setting(conn, safe_provider)
        return jsonify(
            {
                "ok": True,
                "provider": safe_provider,
                "folder_id": current_setting.get("folder_id") or "",
                "drive_id": current_setting.get("drive_id") or "",
                "folder_name": current_setting.get("folder_name") or "",
                "folder_path_label": current_setting.get("folder_path_label") or "",
                "updated_at": current_setting.get("updated_at") or "",
            }
        )

    account, message = _get_cloud_folder_account(conn, safe_provider)
    if not account:
        return jsonify({"ok": False, "message": message}), 400

    payload = request.get_json(silent=True) or {}
    folder_id = str(payload.get("folder_id") or "").strip()
    drive_id = str(payload.get("drive_id") or "").strip()
    folder_name = str(payload.get("folder_name") or "").strip()
    folder_path_label = str(payload.get("folder_path_label") or "").strip()

    if not folder_id:
        return jsonify({"ok": False, "message": "Informe a pasta de destino."}), 400

    if not folder_name:
        if folder_id.lower() == "root":
            folder_name = "Meu Drive" if safe_provider == "google" else "OneDrive"
        else:
            folder_name = "Pasta selecionada"
    if not folder_path_label:
        folder_path_label = folder_name

    try:
        _save_cloud_drive_folder_setting(
            conn,
            provider=safe_provider,
            folder_id=folder_id,
            folder_name=folder_name,
            folder_path_label=folder_path_label,
            drive_id=drive_id,
        )
        prefix = "gdrive" if safe_provider == "google" else "onedrive"
        _save_drive_config(
            conn,
            {
                f"{prefix}_dest_folder": folder_path_label,
            },
        )
        conn.commit()
        logger.info(
            "Pasta remota salva: provider=%s folder_id=%s",
            safe_provider,
            folder_id[:8] + "***" if len(folder_id) > 8 else "***",
        )
        return jsonify(
            {
                "ok": True,
                "message": "Pasta de destino atualizada.",
                "provider": safe_provider,
                "folder_id": folder_id,
                "drive_id": drive_id or None,
                "folder_name": folder_name,
                "folder_path_label": folder_path_label,
            }
        )
    except Exception:
        conn.rollback()
        logger.exception("Falha ao salvar pasta remota: provider=%s", safe_provider)
        return jsonify({"ok": False, "message": "Falha ao salvar pasta de destino."}), 500

@admin_required
def admin_banco_dados_configuracoes():
    conn = get_db_connection()
    try:
        save_backup_settings(
            conn,
            {
                "local_backup_dir": request.form.get("local_backup_dir") or "",
                "cloud_backup_dir": request.form.get("cloud_backup_dir") or "",
                "cloud_sync_interval_seconds": request.form.get("cloud_sync_interval_seconds") or "600",
                "external_backup_url": request.form.get("external_backup_url") or "",
                "external_backup_token": request.form.get("external_backup_token") or "",
                "external_backup_enabled": request.form.get("external_backup_enabled") or "0",
            },
        )
        conn.commit()
    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "error")
        return redirect(url_for("admin_banco_dados"))
    flash("Destinos de backup atualizados com sucesso.", "success")
    return redirect(url_for("admin_banco_dados"))

@admin_required
def admin_banco_dados_retencao():
    conn = get_db_connection()
    try:
        save_retention_policy(conn, request.form.to_dict())
        conn.commit()
    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "error")
        return redirect(url_for("admin_banco_dados"))
    flash("Política de retenção atualizada com sucesso.", "success")
    return redirect(url_for("admin_banco_dados"))

@admin_required
def admin_banco_dados_oauth_start():
    provider = request.args.get("provider") or ""
    if provider not in ("google", "onedrive"):
        flash("Provedor OAuth inválido.", "error")
        return redirect(url_for("admin_banco_dados"))

    if provider == "google":
        return redirect(url_for("admin_backup_google_connect"))
    return redirect(url_for("admin_backup_onedrive_connect"))

@admin_required
def auth_callback():
    provider = str(session.get("oauth_provider") or "").strip().lower()
    has_oauth_payload = any(
        (request.args.get(key) or "").strip()
        for key in ("state", "code", "error", "error_description")
    )
    _clear_legacy_oauth_session()

    if provider in {"google", "onedrive"} or has_oauth_payload:
        flash(
            "Fluxo OAuth legado desativado. Use a conexão específica do provedor.",
            "error",
        )
        return redirect(url_for("admin_banco_dados"))

    abort(404)

@admin_required
def admin_banco_dados_oauth_disconnect():
    provider = request.form.get("provider") or ""
    if provider not in ("google", "onedrive"):
        flash("Provedor inválido.", "error")
        return redirect(url_for("admin_banco_dados"))

    conn = get_db_connection()
    drive_settings = get_drive_settings(conn)
    prefix = "gdrive" if provider == "google" else "onedrive"
    token = drive_settings.get(f"{prefix}_access_token") or ""

    if provider in ("google", "onedrive"):
        ensure_cloud_backup_schema(conn)
        conn.execute(
            "UPDATE cloud_accounts SET active = 0, updated_at = datetime('now') WHERE provider = ? AND active = 1",
            (provider,),
        )

    if token and provider == "google":
        _cd.google_revoke(token)  # best-effort; failures are silently ignored

    _save_drive_config(conn, {
        f"{prefix}_access_token": "",
        f"{prefix}_refresh_token": "",
        f"{prefix}_expires_at": "",
        f"{prefix}_account_email": "",
        f"{prefix}_last_upload_error": "",
    })
    conn.commit()
    flash(f"{'Google Drive' if provider == 'google' else 'OneDrive'} desconectado.", "success")
    return redirect(url_for("admin_banco_dados"))

@admin_required
def admin_banco_dados_drive_settings():
    provider = request.form.get("provider") or ""
    if provider not in ("google", "onedrive"):
        flash("Provedor inválido.", "error")
        return redirect(url_for("admin_banco_dados"))

    prefix = "gdrive" if provider == "google" else "onedrive"
    dest_folder = (request.form.get(f"{prefix}_dest_folder") or "Backups/sistema").strip()
    enabled = "1" if request.form.get(f"{prefix}_enabled") else "0"

    conn = get_db_connection()
    _save_drive_config(conn, {
        f"{prefix}_dest_folder": dest_folder,
        f"{prefix}_enabled": enabled,
    })
    conn.commit()
    flash("Configurações de destino em nuvem salvas.", "success")
    return redirect(url_for("admin_banco_dados"))

@admin_required
def admin_banco_dados_backup():
    conn = get_db_connection()
    context = _build_database_admin_context(conn)
    settings = context["backup_settings"]
    local_snapshot = create_database_snapshot(
        app_db.DATABASE,
        settings["local_backup_dir"],
        schema_status=context["schema_status"],
        reason="manual-backup",
        origin="local",
        logger=logger,
        extra_metadata={"requested_by": session.get("user_id")},
    )
    cloud_result = _backup_orchestrator._maybe_sync_database_snapshot(force=True, conn=conn)
    try:
        external_result = _backup_orchestrator._upload_snapshot_if_external_enabled(local_snapshot, settings)
    except RuntimeError as exc:
        logger.warning("Falha ao enviar snapshot para servidor externo: %s", exc)
        external_result = {"ok": False, "skipped": False, "reason": "external_error", "error": str(exc)}

    if external_result.get("ok") and not external_result.get("skipped"):
        flash("Backup local, snapshot em nuvem e cópia externa enviados com sucesso.", "success")
    elif external_result.get("error"):
        flash(f"Backup local criado, mas o envio ao servidor externo falhou: {external_result['error']}", "warning")
    elif cloud_result.get("skipped"):
        flash(
            "Backup local criado. A sincronização em nuvem foi adiada ou não detectou mudanças.",
            "info",
        )
    else:
        flash("Backup local e snapshot em nuvem criados com sucesso.", "success")
    logger.info(
        "Backup manual solicitado pelo admin %s em %s",
        session.get("user_id"),
        local_snapshot["database_path"],
    )
    try:
        _backup_orchestrator._run_retention_cleanup(conn=conn)
    except Exception as exc:
        logger.warning("Falha ao aplicar política de retenção após backup: %s", exc)
    try:
        _backup_orchestrator._maybe_upload_to_drives(local_snapshot["database_path"], conn=conn)
    except Exception as exc:
        logger.warning("Falha no upload para drives após backup: %s", exc)
    return redirect(url_for("admin_banco_dados"))

@admin_required
def admin_banco_dados_download():
    manifest_path = _resolve_allowed_backup_manifest_path(request.args.get("manifest_path") or "")
    if not manifest_path or not os.path.exists(manifest_path):
        flash("Snapshot solicitado não está disponível para download.", "error")
        return redirect(url_for("admin_banco_dados"))

    try:
        with open(manifest_path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, json.JSONDecodeError):
        flash("Manifesto do snapshot inválido.", "error")
        return redirect(url_for("admin_banco_dados"))

    db_path = manifest.get("database_path") or ""
    if not db_path or not os.path.exists(db_path):
        flash("Arquivo do banco para download não foi encontrado.", "error")
        return redirect(url_for("admin_banco_dados"))

    return send_file(db_path, as_attachment=True, download_name=os.path.basename(db_path))

@admin_required
def admin_banco_dados_excluir():
    manifest_path = _resolve_allowed_backup_manifest_path(request.form.get("manifest_path") or "")
    if not manifest_path or not os.path.exists(manifest_path):
        flash("Snapshot selecionado não está disponível para exclusão.", "error")
        return redirect(url_for("admin_banco_dados"))

    try:
        delete_database_snapshot(manifest_path, logger=logger)
    except (OSError, json.JSONDecodeError, KeyError, ValueError) as exc:
        flash(f"Não foi possível excluir o snapshot: {exc}", "error")
        return redirect(url_for("admin_banco_dados"))
    flash("Snapshot excluído com sucesso.", "success")
    return redirect(url_for("admin_banco_dados"))

def _get_current_schema_status_for_restore() -> dict[str, object]:
    conn = getattr(g, "db", None)
    if conn is not None:
        current_schema_status = get_schema_status(conn)
        conn.close()
        g.pop("db", None)
        return current_schema_status

    with sqlite3.connect(app_db.DATABASE) as temp_conn:
        temp_conn.row_factory = sqlite3.Row
        return get_schema_status(temp_conn)

def _restore_database_from_source(
    source_database_path: str,
    *,
    source_manifest_path: str = "",
    source_upload_name: str = "",
    source_kind: str = "snapshot",
) -> None:
    runtime_settings = _get_runtime_backup_settings()
    extra_metadata = {
        "requested_by": session.get("user_id"),
        "source_kind": source_kind,
    }
    if source_manifest_path:
        extra_metadata["source_manifest_path"] = source_manifest_path
    if source_upload_name:
        extra_metadata["source_upload_name"] = source_upload_name

    create_database_snapshot(
        app_db.DATABASE,
        runtime_settings.get("local_backup_dir") or current_app.config["LOCAL_BACKUP_DIR"],
        schema_status=_get_current_schema_status_for_restore(),
        reason="pre-restore-safety",
        origin="local",
        logger=logger,
        extra_metadata=extra_metadata,
    )
    restore_database_snapshot(source_database_path, app_db.DATABASE, logger=logger)

    conn = get_db_connection()
    init_db()
    sync_result = _backup_orchestrator._maybe_sync_database_snapshot(force=True, conn=conn)
    try:
        _backup_orchestrator._run_retention_cleanup(conn=conn)
    except Exception as exc:
        logger.warning("Falha ao aplicar política de retenção após restauração: %s", exc)
    try:
        db_path = (sync_result.get("snapshot") or {}).get("database_path") or ""
        if db_path:
            _backup_orchestrator._maybe_upload_to_drives(db_path, conn=conn)
    except Exception as exc:
        logger.warning("Falha no upload para drives após restauração: %s", exc)

@admin_required
def admin_banco_dados_restaurar():
    manifest_path = _resolve_allowed_backup_manifest_path(request.form.get("manifest_path") or "")
    if not manifest_path or not os.path.exists(manifest_path):
        flash("Backup selecionado é inválido ou não está mais disponível.", "error")
        return redirect(url_for("admin_banco_dados"))

    try:
        with open(manifest_path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, json.JSONDecodeError):
        flash("Não foi possível ler o manifesto do backup selecionado.", "error")
        return redirect(url_for("admin_banco_dados"))

    snapshot_path = manifest.get("database_path") or ""
    if not snapshot_path or not os.path.exists(snapshot_path):
        flash("Arquivo do backup não foi encontrado.", "error")
        return redirect(url_for("admin_banco_dados"))

    try:
        validate_manifest_backed_restore(snapshot_path, manifest)
    except BackupServiceError as exc:
        flash(f"Não foi possível restaurar o backup selecionado: {exc}", "error")
        return redirect(url_for("admin_banco_dados"))

    _restore_database_from_source(
        snapshot_path,
        source_manifest_path=manifest_path,
        source_kind="snapshot",
    )
    flash(
        "Banco restaurado com sucesso. Um snapshot de segurança da base anterior foi salvo localmente.",
        "success",
    )
    return redirect(url_for("admin_banco_dados"))

@admin_required
def admin_banco_dados_restaurar_upload():
    request.max_content_length = current_app.config.get("BACKUP_RESTORE_MAX_CONTENT_LENGTH")
    backup_file = request.files.get("backup_file")
    if not backup_file or not getattr(backup_file, "filename", ""):
        flash("Selecione um arquivo de backup do banco para restaurar.", "error")
        return redirect(url_for("admin_banco_dados"))

    work_dir = tempfile.mkdtemp(prefix="sgaa-restore-upload-")
    restore_artifacts: dict[str, object] = {"work_dir": work_dir}
    try:
        upload_name = secure_filename(str(backup_file.filename or "")) or "backup-banco"
        upload_path = os.path.join(work_dir, upload_name)
        backup_file.save(upload_path)
        restore_artifacts = extract_restore_database_artifact(upload_path, work_dir=work_dir)
        _restore_database_from_source(
            str(restore_artifacts["database_path"]),
            source_upload_name=str(backup_file.filename or upload_name),
            source_kind=str(restore_artifacts.get("source_kind") or "upload"),
        )
    except (BackupServiceError, OSError, sqlite3.Error, ValueError) as exc:
        flash(f"Não foi possível restaurar o arquivo enviado: {exc}", "error")
        return redirect(url_for("admin_banco_dados"))
    finally:
        cleanup_backup_artifacts(restore_artifacts)

    flash(
        "Banco restaurado com sucesso a partir do arquivo enviado. Um snapshot de segurança da base anterior foi salvo localmente.",
        "success",
    )
    return redirect(url_for("admin_banco_dados"))

bp_admin_banco_dados = Blueprint("admin_banco_dados_blueprint", __name__)

LEGACY_ROUTE_SPECS = configure_legacy_routes(
    bp_admin_banco_dados,
    (
        LegacyRouteSpec(
            "/admin/banco-dados",
            "admin_banco_dados",
            admin_banco_dados,
            ("GET",),
        ),
        LegacyRouteSpec(
            "/admin/backup/google/connect",
            "admin_backup_google_connect",
            admin_backup_google_connect,
            ("GET",),
        ),
        LegacyRouteSpec(
            "/google/callback",
            "google_callback",
            google_callback,
            ("GET",),
        ),
        LegacyRouteSpec(
            "/admin/backup/google/upload",
            "admin_backup_google_upload",
            admin_backup_google_upload,
            ("POST",),
        ),
        LegacyRouteSpec(
            "/admin/backup/onedrive/connect",
            "admin_backup_onedrive_connect",
            admin_backup_onedrive_connect,
            ("GET",),
        ),
        LegacyRouteSpec(
            "/onedrive/callback",
            "onedrive_callback",
            onedrive_callback,
            ("GET",),
        ),
        LegacyRouteSpec(
            "/admin/backup/onedrive/upload",
            "admin_backup_onedrive_upload",
            admin_backup_onedrive_upload,
            ("POST",),
        ),
        LegacyRouteSpec(
            "/admin/backup/cloud-folders/<provider>",
            "admin_backup_cloud_folders",
            admin_backup_cloud_folders,
            ("GET",),
        ),
        LegacyRouteSpec(
            "/admin/backup/cloud-folder/<provider>",
            "admin_backup_cloud_folder",
            admin_backup_cloud_folder,
            ("GET", "POST"),
        ),
        LegacyRouteSpec(
            "/admin/banco-dados/configuracoes",
            "admin_banco_dados_configuracoes",
            admin_banco_dados_configuracoes,
            ("POST",),
        ),
        LegacyRouteSpec(
            "/admin/banco-dados/retencao",
            "admin_banco_dados_retencao",
            admin_banco_dados_retencao,
            ("POST",),
        ),
        LegacyRouteSpec(
            "/admin/banco-dados/oauth/start",
            "admin_banco_dados_oauth_start",
            admin_banco_dados_oauth_start,
            ("GET",),
        ),
        LegacyRouteSpec(
            "/auth/callback",
            "auth_callback",
            auth_callback,
            ("GET",),
        ),
        LegacyRouteSpec(
            "/admin/banco-dados/oauth/disconnect",
            "admin_banco_dados_oauth_disconnect",
            admin_banco_dados_oauth_disconnect,
            ("POST",),
        ),
        LegacyRouteSpec(
            "/admin/banco-dados/drive-settings",
            "admin_banco_dados_drive_settings",
            admin_banco_dados_drive_settings,
            ("POST",),
        ),
        LegacyRouteSpec(
            "/admin/banco-dados/backup",
            "admin_banco_dados_backup",
            admin_banco_dados_backup,
            ("POST",),
        ),
        LegacyRouteSpec(
            "/admin/banco-dados/download",
            "admin_banco_dados_download",
            admin_banco_dados_download,
            ("GET",),
        ),
        LegacyRouteSpec(
            "/admin/banco-dados/excluir",
            "admin_banco_dados_excluir",
            admin_banco_dados_excluir,
            ("POST",),
        ),
        LegacyRouteSpec(
            "/admin/banco-dados/restaurar",
            "admin_banco_dados_restaurar",
            admin_banco_dados_restaurar,
            ("POST",),
        ),
        LegacyRouteSpec(
            "/admin/banco-dados/restaurar/upload",
            "admin_banco_dados_restaurar_upload",
            admin_banco_dados_restaurar_upload,
            ("POST",),
        ),
    ),
)


__all__ = [
    "LEGACY_ROUTE_SPECS",
    "bp_admin_banco_dados",
"_normalize_backup_directory", "save_backup_settings", "_RETENTION_INTERVAL_OPTIONS", "save_retention_policy", "_CLOUD_FOLDER_PROVIDERS", "_normalize_cloud_folder_provider", "_save_cloud_drive_folder_setting", "_get_cloud_drive_folder_setting", "_extract_oauth_scopes", "_set_active_cloud_account", "_get_active_cloud_account", "_require_cloud_token_encryption_ready", "_update_cloud_account_token", "_record_backup_log", "_list_backup_logs", "_format_drive_timestamp", "_build_database_admin_context", "admin_banco_dados", "_maybe_redirect_to_oauth_callback_host", "_clear_legacy_oauth_session", "_resolve_onedrive_redirect_uri", "_resolve_google_redirect_uri", "_onedrive_connect_diagnostics", "_build_oauth_redirect_context", "admin_backup_google_connect", "google_callback", "admin_backup_google_upload", "admin_backup_onedrive_connect", "onedrive_callback", "admin_backup_onedrive_upload", "_get_cloud_folder_account", "admin_backup_cloud_folders", "admin_backup_cloud_folder", "admin_banco_dados_configuracoes", "admin_banco_dados_retencao", "admin_banco_dados_oauth_start", "auth_callback", "admin_banco_dados_oauth_disconnect", "admin_banco_dados_drive_settings", "admin_banco_dados_backup", "admin_banco_dados_download", "admin_banco_dados_excluir", "_get_current_schema_status_for_restore", "_restore_database_from_source", "admin_banco_dados_restaurar", "admin_banco_dados_restaurar_upload",
]
