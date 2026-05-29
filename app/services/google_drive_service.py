import json
import logging
import os
from typing import Any

from services.oauth_config import OAuthConfigError, get_google_redirect_uri


_GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
_GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
_DEFAULT_SCOPES = (
    "https://www.googleapis.com/auth/drive.file "
    "https://www.googleapis.com/auth/userinfo.email "
    "openid"
)
_DEFAULT_FOLDER_NAME = "SGAA - Backups"
logger = logging.getLogger(__name__)


class GoogleDriveServiceError(RuntimeError):
    pass


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
    raw_scopes = (os.environ.get("GOOGLE_SCOPES") or "").strip() or _DEFAULT_SCOPES
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
    client_id = (os.environ.get("GOOGLE_CLIENT_ID") or "").strip()
    client_secret = (os.environ.get("GOOGLE_CLIENT_SECRET") or "").strip()
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


def create_authorization_url(*, state: str, is_debug: bool) -> tuple[str, str]:
    Credentials, Request, Flow, build, MediaFileUpload = _import_google_dependencies()
    redirect_uri = get_redirect_uri()
    _allow_http_localhost_if_debug(is_debug=is_debug, redirect_uri=redirect_uri)

    flow = Flow.from_client_config(
        _build_client_config(redirect_uri),
        scopes=_get_scopes(),
        state=state,
    )
    flow.redirect_uri = redirect_uri

    auth_url, generated_state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
    )
    return auth_url, generated_state


def _serialize_credentials(credentials, previous_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
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


def exchange_code_for_token(*, code: str, is_debug: bool) -> tuple[str, str]:
    Credentials, Request, Flow, build, MediaFileUpload = _import_google_dependencies()
    redirect_uri = get_redirect_uri()
    _allow_http_localhost_if_debug(is_debug=is_debug, redirect_uri=redirect_uri)

    flow = Flow.from_client_config(_build_client_config(redirect_uri), scopes=_get_scopes())
    flow.redirect_uri = redirect_uri
    try:
        flow.fetch_token(code=code)
    except Exception as exc:
        raise GoogleDriveServiceError(f"Falha ao trocar code OAuth por token: {exc}") from exc

    credentials = flow.credentials
    email = _fetch_email(credentials)
    token_json = json.dumps(_serialize_credentials(credentials), ensure_ascii=False)
    return token_json, email


def _build_credentials_from_token_json(token_json: str):
    Credentials, Request, Flow, build, MediaFileUpload = _import_google_dependencies()
    try:
        payload = json.loads(token_json)
    except json.JSONDecodeError as exc:
        raise GoogleDriveServiceError("Token OAuth inválido no banco.") from exc

    credentials = Credentials.from_authorized_user_info(payload, scopes=_get_scopes())
    refreshed = False
    if credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
            refreshed = True
        except Exception as exc:
            raise GoogleDriveServiceError(f"Falha ao renovar token OAuth: {exc}") from exc

    updated_payload = _serialize_credentials(credentials, previous_payload=payload)
    return credentials, refreshed, json.dumps(updated_payload, ensure_ascii=False)


def _build_drive_service_from_token_json(token_json: str):
    Credentials, Request, Flow, build, MediaFileUpload = _import_google_dependencies()
    credentials, refreshed, updated_token_json = _build_credentials_from_token_json(token_json)
    drive_service = build("drive", "v3", credentials=credentials, cache_discovery=False)
    return drive_service, refreshed, updated_token_json


def list_google_folders(*, token_json: str, parent_id: str | None = None) -> dict[str, object]:
    drive_service, refreshed, updated_token_json = _build_drive_service_from_token_json(token_json)

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
        "Google folder list success: api=drive.files.list parent_is_root=%s total=%s token_refreshed=%s",
        normalized_parent_id == "root",
        len(folders),
        refreshed,
    )

    return {
        "folders": folders,
        "current_folder_id": normalized_parent_id,
        "token_json": updated_token_json,
        "token_refreshed": "1" if refreshed else "0",
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
