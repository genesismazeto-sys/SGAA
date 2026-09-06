import json
import datetime
import logging
import os
from typing import Any

from app.cloud_config import get_google_oauth_config
from services.oauth_config import OAuthConfigError, get_google_redirect_uri


_GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
_GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
_DEFAULT_SCOPES = (
    "https://www.googleapis.com/auth/drive.file "
    "https://www.googleapis.com/auth/userinfo.email "
    "openid"
)
_DEFAULT_FOLDER_NAME = "SGAA - Backups"
_AUTH_RECONNECT_REQUIRED = "AUTH_RECONNECT_REQUIRED"
_AUTH_TEMPORARY_FAILURE = "AUTH_TEMPORARY_FAILURE"
_APPLICATION_CREDENTIALS_INVALID = "APPLICATION_CREDENTIALS_INVALID"
_INVALID_REFRESH_AUTHORIZATION_ERRORS = frozenset({"invalid_grant", "invalid_token"})
_INVALID_APPLICATION_CREDENTIAL_ERRORS = frozenset({"invalid_client", "unauthorized_client"})
logger = logging.getLogger(__name__)


class GoogleDriveServiceError(RuntimeError):
    def __init__(self, message: str, *, debug_code: str = ""):
        super().__init__(message)
        self.debug_code = debug_code


def _classify_refresh_failure(exc: Exception) -> str:
    try:
        from google.auth import exceptions as google_auth_exceptions
    except Exception:
        return _AUTH_TEMPORARY_FAILURE

    if isinstance(exc, google_auth_exceptions.TransportError) or bool(
        getattr(exc, "retryable", False)
    ):
        return _AUTH_TEMPORARY_FAILURE
    if isinstance(exc, google_auth_exceptions.RefreshError):
        response_data = exc.args[1] if len(exc.args) > 1 else None
        error_code = (
            str(response_data.get("error") or "").strip().lower()
            if isinstance(response_data, dict)
            else ""
        )
        if error_code in _INVALID_REFRESH_AUTHORIZATION_ERRORS:
            return _AUTH_RECONNECT_REQUIRED
        if error_code in _INVALID_APPLICATION_CREDENTIAL_ERRORS:
            return _APPLICATION_CREDENTIALS_INVALID
    return _AUTH_TEMPORARY_FAILURE


def _import_google_dependencies():
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from google_auth_oauthlib.flow import Flow
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
    except Exception as exc:
        raise GoogleDriveServiceError(
            "Dependencias Google ausentes. Instale: google-api-python-client, "
            "google-auth, google-auth-oauthlib, google-auth-httplib2"
        ) from exc
    return Credentials, Request, Flow, build, MediaFileUpload


def _get_scopes() -> list[str]:
    raw_scopes = get_google_oauth_config()["scopes"] or _DEFAULT_SCOPES
    scopes = [scope.strip() for scope in raw_scopes.split() if scope.strip()]
    if not scopes:
        raise GoogleDriveServiceError("GOOGLE_SCOPES não foi configurado.")
    if "openid" not in scopes:
        scopes.append("openid")
    return scopes


def get_redirect_uri(default_uri: str | None = None) -> str:
    try:
        return get_google_redirect_uri()
    except OAuthConfigError as exc:
        raise GoogleDriveServiceError(str(exc)) from exc


def _build_client_config(redirect_uri: str) -> dict[str, Any]:
    config = get_google_oauth_config()
    client_id = config["client_id"]
    client_secret = config["client_secret"]
    if not client_id or not client_secret:
        raise GoogleDriveServiceError(
            "Credenciais Google ausentes. Defina GOOGLE_CLIENT_ID e GOOGLE_CLIENT_SECRET."
        )
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": _GOOGLE_AUTH_URI,
            "token_uri": _GOOGLE_TOKEN_URI,
            "redirect_uris": [redirect_uri],
        }
    }


def _allow_http_localhost_if_debug(*, is_debug: bool, redirect_uri: str) -> None:
    if not is_debug:
        return
    local_http = redirect_uri.startswith("http://localhost") or redirect_uri.startswith("http://127.0.0.1")
    if local_http:
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"


def create_authorization_url(*, state: str, is_debug: bool) -> tuple[str, str, str]:
    Credentials, Request, Flow, build, MediaFileUpload = _import_google_dependencies()
    redirect_uri = get_redirect_uri()
    _allow_http_localhost_if_debug(is_debug=is_debug, redirect_uri=redirect_uri)

    flow = Flow.from_client_config(
        _build_client_config(redirect_uri),
        scopes=_get_scopes(),
        state=state,
        autogenerate_code_verifier=True,
    )
    flow.redirect_uri = redirect_uri

    auth_url, generated_state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
    )
    code_verifier = str(flow.code_verifier or "")
    if not code_verifier:
        raise GoogleDriveServiceError("Falha ao gerar PKCE para a conexao Google.")
    return auth_url, generated_state, code_verifier


def _serialize_credentials(credentials, previous_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "version": 2,
        "provider": "google",
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "scopes": credentials.scopes,
    }
    if credentials.expiry is not None:
        payload["expiry"] = credentials.expiry.isoformat()
    if previous_payload and not payload.get("refresh_token"):
        payload["refresh_token"] = previous_payload.get("refresh_token")
    return payload


def _fetch_email(credentials) -> str:
    Credentials, Request, Flow, build, MediaFileUpload = _import_google_dependencies()
    oauth_service = build("oauth2", "v2", credentials=credentials, cache_discovery=False)
    info = oauth_service.userinfo().get().execute() or {}
    return str(info.get("email") or "").strip()


def exchange_code_for_token(*, code: str, code_verifier: str, is_debug: bool) -> tuple[str, str]:
    Credentials, Request, Flow, build, MediaFileUpload = _import_google_dependencies()
    redirect_uri = get_redirect_uri()
    _allow_http_localhost_if_debug(is_debug=is_debug, redirect_uri=redirect_uri)

    if not code_verifier:
        raise GoogleDriveServiceError("Sessao PKCE expirada. Inicie a conexao Google novamente.")
    flow = Flow.from_client_config(
        _build_client_config(redirect_uri),
        scopes=_get_scopes(),
        code_verifier=code_verifier,
    )
    flow.redirect_uri = redirect_uri
    try:
        flow.fetch_token(code=code)
    except Exception as exc:
        logger.warning("Falha na troca OAuth Google: %s", type(exc).__name__)
        if type(exc).__name__ == "InvalidClientError":
            raise GoogleDriveServiceError(
                "Credenciais do aplicativo Google rejeitadas. "
                "Reconfigure o Client ID e o Client Secret desta maquina.",
                debug_code="APPLICATION_CREDENTIALS_INVALID",
            ) from exc
        raise GoogleDriveServiceError(
            "Falha ao concluir a autorizacao Google. Inicie a conexao novamente."
        ) from exc

    credentials = flow.credentials
    try:
        email = _fetch_email(credentials)
    except Exception as exc:
        raise GoogleDriveServiceError("Nao foi possivel validar a identidade Google.") from exc
    token_json = json.dumps(_serialize_credentials(credentials), ensure_ascii=False)
    return token_json, email


def _build_credentials_from_token_json(token_json: str, *, force_refresh: bool = False):
    Credentials, Request, Flow, build, MediaFileUpload = _import_google_dependencies()
    try:
        payload = json.loads(token_json)
    except json.JSONDecodeError as exc:
        raise GoogleDriveServiceError(
            "Autorizacao Google invalida. Reconecte o Google Drive.",
            debug_code="AUTH_RECONNECT_REQUIRED",
        ) from exc

    config = get_google_oauth_config()
    if not config["client_id"] or not config["client_secret"]:
        raise GoogleDriveServiceError(
            "Credenciais Google ausentes. Configure esta maquina antes de reconectar.",
            debug_code="APPLICATION_CREDENTIALS_MISSING",
        )
    expiry = None
    if payload.get("expiry"):
        try:
            expiry = datetime.datetime.fromisoformat(str(payload["expiry"]).replace("Z", "+00:00"))
        except ValueError:
            expiry = None
    credentials = Credentials(
        token=payload.get("token"),
        refresh_token=payload.get("refresh_token"),
        token_uri=str(payload.get("token_uri") or _GOOGLE_TOKEN_URI),
        client_id=config["client_id"],
        client_secret=config["client_secret"],
        scopes=_get_scopes(),
        expiry=expiry,
    )
    refreshed = False
    refresh_required = bool(credentials.expired or force_refresh)
    if refresh_required and not credentials.refresh_token:
        raise GoogleDriveServiceError(
            "Autorizacao Google expirada e sem renovacao valida. Reconecte o Google Drive.",
            debug_code="AUTH_RECONNECT_REQUIRED",
        )
    if refresh_required and credentials.refresh_token:
        try:
            credentials.refresh(Request())
            refreshed = True
        except Exception as exc:
            debug_code = _classify_refresh_failure(exc)
            if debug_code == _AUTH_RECONNECT_REQUIRED:
                message = "A autorizacao Google nao e mais valida. Reconecte o Google Drive."
            elif debug_code == _APPLICATION_CREDENTIALS_INVALID:
                message = (
                    "Credenciais do aplicativo Google rejeitadas. "
                    "Reconfigure esta maquina antes de tentar novamente."
                )
            else:
                message = "Nao foi possivel renovar a autorizacao Google agora. Tente novamente."
            raise GoogleDriveServiceError(
                message,
                debug_code=debug_code,
            ) from exc

    updated_payload = _serialize_credentials(credentials, previous_payload=payload)
    return credentials, refreshed, json.dumps(updated_payload, ensure_ascii=False)


def acquire_access_token(*, token_json: str) -> tuple[str, str, str]:
    credentials, refreshed, updated_token_json = _build_credentials_from_token_json(token_json)
    if not credentials.token:
        raise GoogleDriveServiceError(
            "Autorizacao Google invalida. Reconecte o Google Drive.",
            debug_code="AUTH_RECONNECT_REQUIRED",
        )
    try:
        account_email = _fetch_email(credentials)
    except Exception as exc:
        raise GoogleDriveServiceError("Nao foi possivel validar a identidade Google.") from exc
    return str(credentials.token), updated_token_json, account_email


def refresh_access_token(*, token_json: str) -> tuple[str, str, str]:
    """Force canonical token refresh after an access-token rejection."""
    credentials, _refreshed, updated_token_json = _build_credentials_from_token_json(
        token_json, force_refresh=True
    )
    if not credentials.token:
        raise GoogleDriveServiceError(
            "Autorizacao Google invalida. Reconecte o Google Drive.",
            debug_code="AUTH_RECONNECT_REQUIRED",
        )
    return str(credentials.token), updated_token_json, ""


def get_connected_account(*, token_json: str) -> dict[str, str]:
    access_token, updated_token_json, account_email = acquire_access_token(token_json=token_json)
    return {
        "account_email": account_email,
        "token_json": updated_token_json,
        "access_token": access_token,
    }


def _build_drive_service_from_token_json(token_json: str):
    Credentials, Request, Flow, build, MediaFileUpload = _import_google_dependencies()
    credentials, refreshed, updated_token_json = _build_credentials_from_token_json(token_json)
    drive_service = build("drive", "v3", credentials=credentials, cache_discovery=False)
    return drive_service, refreshed, updated_token_json


def list_google_folders(*, token_json: str, parent_id: str | None = None) -> dict[str, object]:
    drive_service, refreshed, updated_token_json = _build_drive_service_from_token_json(token_json)

    result = _list_google_folders_with_service(drive_service, parent_id=parent_id)
    result["token_json"] = updated_token_json
    result["token_refreshed"] = "1" if refreshed else "0"
    return result


def list_google_folders_with_access_token(
    *, access_token: str, parent_id: str | None = None
) -> dict[str, object]:
    try:
        Credentials, Request, Flow, build, MediaFileUpload = _import_google_dependencies()
        credentials = Credentials(token=access_token)
        drive_service = build("drive", "v3", credentials=credentials, cache_discovery=False)
        return _list_google_folders_with_service(drive_service, parent_id=parent_id)
    except GoogleDriveServiceError:
        raise
    except Exception as exc:
        raise GoogleDriveServiceError(
            "Nao foi possivel listar as pastas do Google Drive."
        ) from exc


def _list_google_folders_with_service(
    drive_service, *, parent_id: str | None = None
) -> dict[str, object]:

    normalized_parent_id = (parent_id or "").strip() or "root"
    if normalized_parent_id == "root":
        parent_clause = "'root' in parents"
    else:
        escaped_parent_id = normalized_parent_id.replace("'", "\\'")
        parent_clause = f"'{escaped_parent_id}' in parents"

    query = (
        "mimeType='application/vnd.google-apps.folder' and trashed=false "
        f"and {parent_clause}"
    )
    response = drive_service.files().list(
        q=query,
        spaces="drive",
        fields="files(id, name)",
        orderBy="name_natural",
        pageSize=200,
    ).execute()

    folders: list[dict[str, str]] = []
    for folder in response.get("files", []) or []:
        folder_id = str(folder.get("id") or "").strip()
        folder_name = str(folder.get("name") or "").strip()
        if not folder_id or not folder_name:
            continue
        folders.append(
            {
                "id": folder_id,
                "name": folder_name,
                "path_label": folder_name,
            }
        )

    logger.info(
        "Google folder list success: api=drive.files.list parent_is_root=%s total=%s",
        normalized_parent_id == "root",
        len(folders),
    )

    return {
        "folders": folders,
        "current_folder_id": normalized_parent_id,
    }


def _ensure_backup_folder(drive_service, folder_name: str) -> str:
    escaped_name = folder_name.replace("'", "\\'")
    managed_query = (
        "appProperties has { key='managedBy' and value='SGAA' } and "
        f"name='{escaped_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    )
    response = drive_service.files().list(
        q=managed_query,
        spaces="drive",
        fields="files(id, name)",
        pageSize=10,
    ).execute()
    files = response.get("files", [])
    if files:
        return files[0]["id"]

    name_query = (
        f"name='{escaped_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    )
    response = drive_service.files().list(
        q=name_query,
        spaces="drive",
        fields="files(id, name)",
        pageSize=10,
    ).execute()
    files = response.get("files", [])
    if files:
        return files[0]["id"]

    created = drive_service.files().create(
        body={
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder",
            "appProperties": {"managedBy": "SGAA"},
        },
        fields="id",
    ).execute()
    return created["id"]


def upload_zip_backup_with_access_token(
    *,
    access_token: str,
    zip_path: str,
    file_name: str,
    folder_name: str = _DEFAULT_FOLDER_NAME,
    folder_id: str | None = None,
) -> dict[str, str]:
    if not os.path.exists(zip_path):
        raise GoogleDriveServiceError("Arquivo ZIP de backup não encontrado para upload.")
    try:
        Credentials, Request, Flow, build, MediaFileUpload = _import_google_dependencies()
        credentials = Credentials(token=access_token)
        drive_service = build("drive", "v3", credentials=credentials, cache_discovery=False)
        selected_folder_id = (folder_id or "").strip()
        target_folder_id = selected_folder_id or _ensure_backup_folder(drive_service, folder_name)
        media = MediaFileUpload(zip_path, mimetype="application/zip", resumable=False)
        created = drive_service.files().create(
            body={"name": file_name, "parents": [target_folder_id]},
            media_body=media,
            fields="id, name",
        ).execute()
    except GoogleDriveServiceError:
        raise
    except Exception as exc:
        raise GoogleDriveServiceError(
            "Nao foi possivel enviar o backup ao Google Drive."
        ) from exc
    return {
        "file_id": str(created.get("id") or ""),
        "file_name": str(created.get("name") or file_name),
        "folder_id": target_folder_id,
    }


def upload_zip_backup(
    *,
    token_json: str,
    zip_path: str,
    file_name: str,
    folder_name: str = _DEFAULT_FOLDER_NAME,
    folder_id: str | None = None,
) -> dict[str, str]:
    if not os.path.exists(zip_path):
        raise GoogleDriveServiceError("Arquivo ZIP de backup não encontrado para upload.")

    Credentials, Request, Flow, build, MediaFileUpload = _import_google_dependencies()
    drive_service, refreshed, updated_token_json = _build_drive_service_from_token_json(token_json)
    selected_folder_id = (folder_id or "").strip()
    target_folder_id = selected_folder_id or _ensure_backup_folder(drive_service, folder_name)

    media = MediaFileUpload(zip_path, mimetype="application/zip", resumable=False)
    created = drive_service.files().create(
        body={"name": file_name, "parents": [target_folder_id]},
        media_body=media,
        fields="id, name",
    ).execute()

    return {
        "file_id": str(created.get("id") or ""),
        "file_name": str(created.get("name") or file_name),
        "folder_id": target_folder_id,
        "token_json": updated_token_json,
        "token_refreshed": "1" if refreshed else "0",
    }
