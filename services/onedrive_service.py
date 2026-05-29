import datetime
import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from services.oauth_config import OAuthConfigError, get_onedrive_redirect_uri


DEFAULT_GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
DEFAULT_UPLOAD_FOLDER = "SGAA - Backups"
# NOTE:
# Do not include reserved OIDC scopes such as "offline_access" here.
# MSAL adds reserved scopes internally during the auth request flow.
SCOPES = ["User.Read", "Files.ReadWrite"]
logger = logging.getLogger(__name__)

class OneDriveServiceError(RuntimeError):
    def __init__(self, message: str, *, debug_code: str = "", http_status: int | None = None):
        super().__init__(message)
        self.debug_code = debug_code
        self.http_status = http_status


@dataclass(frozen=True)
class _OneDriveConfig:
    client_id: str
    client_secret: str
    tenant_id: str
    redirect_uri: str
    graph_base_url: str

    @property
    def authority(self) -> str:
        return f"https://login.microsoftonline.com/{self.tenant_id}"


def get_ms_redirect_uri() -> str:
    try:
        return get_onedrive_redirect_uri()
    except OAuthConfigError as exc:
        raise OneDriveServiceError(str(exc)) from exc


def _utc_now_iso() -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _load_config() -> _OneDriveConfig:
    env = {
        "MS_CLIENT_ID": (os.environ.get("MS_CLIENT_ID") or "").strip(),
        "MS_CLIENT_SECRET": (os.environ.get("MS_CLIENT_SECRET") or "").strip(),
        "MS_TENANT_ID": (os.environ.get("MS_TENANT_ID") or "").strip(),
        "MS_GRAPH_BASE_URL": (
            (os.environ.get("MS_GRAPH_BASE_URL") or "").strip()
            or DEFAULT_GRAPH_BASE_URL
        ),
    }
    missing = [
        key
        for key in (
            "MS_CLIENT_ID",
            "MS_CLIENT_SECRET",
            "MS_TENANT_ID",
            "MS_GRAPH_BASE_URL",
        )
        if not env[key]
    ]
    if missing:
        logger.warning(
            "Configuracao OneDrive incompleta. Variaveis ausentes: %s",
            ", ".join(missing),
        )
        raise OneDriveServiceError(
            "Variaveis MS ausentes no .env: " + ", ".join(missing)
        )

    return _OneDriveConfig(
        client_id=env["MS_CLIENT_ID"],
        client_secret=env["MS_CLIENT_SECRET"],
        tenant_id=env["MS_TENANT_ID"],
        redirect_uri=get_ms_redirect_uri(),
        graph_base_url=env["MS_GRAPH_BASE_URL"].rstrip("/"),
    )


def validate_configuration() -> None:
    _load_config()

def _import_msal():
    try:
        import msal
    except Exception as exc:
        raise OneDriveServiceError(
            "Biblioteca MSAL não instalada. Execute pip install -r requirements.txt."
        ) from exc
    return msal


def _import_requests():
    try:
        import requests
    except Exception as exc:
        raise OneDriveServiceError(
            "Dependência requests ausente. Instale o pacote requests para usar OneDrive."
        ) from exc
    return requests


def _new_cache(serialized: str = ""):
    msal = _import_msal()
    cache = msal.SerializableTokenCache()
    if serialized:
        try:
            cache.deserialize(serialized)
        except Exception as exc:
            raise OneDriveServiceError(
                "Token OAuth do OneDrive inválido. Reconecte a conta."
            ) from exc
    return cache


def _build_app(config: _OneDriveConfig, cache):
    msal = _import_msal()
    return msal.ConfidentialClientApplication(
        client_id=config.client_id,
        authority=config.authority,
        client_credential=config.client_secret,
        token_cache=cache,
    )


def _token_error_message(result: dict[str, Any]) -> str:
    error_code = str(result.get("error") or "").strip().lower()
    if error_code == "invalid_client":
        return "Falha de autenticação Microsoft. Verifique MS_CLIENT_SECRET e o App Registration."
    if error_code in {"invalid_grant", "interaction_required"}:
        return "Não foi possível concluir a autorização do OneDrive. Tente conectar novamente."
    return "Falha na autenticação com Microsoft/OneDrive."


def _sanitize_oauth_error_description(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(
        r"(?i)(access_token|refresh_token|client_secret|code)\s*=\s*[^&\s]+",
        r"\1=[redacted]",
        text,
    )
    cleaned = " ".join(cleaned.split())
    return cleaned[:400]

def _graph_error_message(status_code: int, payload: dict[str, Any], *, operation: str) -> str:
    error_obj = payload.get("error") if isinstance(payload, dict) else {}
    code = str((error_obj or {}).get("code") or "").strip().lower()

    if status_code == 401:
        return "Token expirado e sem refresh válido. Reconecte o OneDrive."
    if status_code in {403, 404} and code in {
        "accessdenied",
        "drivenotfound",
        "itemnotfound",
        "resourcenotfound",
        "forbidden",
    }:
        return "OneDrive indisponível para esta conta Microsoft."
    if status_code in {403, 404}:
        return "OneDrive indisponível para esta conta Microsoft."
    if status_code == 413:
        return "Arquivo grande demais para upload simples no OneDrive. TODO: implementar upload session."

    if operation == "me":
        op_label = "consulta"
    elif operation == "list":
        op_label = "listagem de pastas"
    else:
        op_label = "upload"
    return f"Falha no {op_label} OneDrive (HTTP {status_code})."


def create_authorization_url(*, state: str) -> str:
    if not state:
        raise OneDriveServiceError("State OAuth ausente para conexão OneDrive.")

    config = _load_config()
    try:
        app = _build_app(config, _new_cache())
        return app.get_authorization_request_url(
            scopes=SCOPES,
            state=state,
            redirect_uri=get_ms_redirect_uri(),
            prompt="select_account",
        )
    except ValueError as exc:
        raise OneDriveServiceError(
            "Configuração OAuth do OneDrive inválida. Revise os escopos e o App Registration."
        ) from exc


def fetch_account_email(access_token: str) -> str:
    config = _load_config()
    requests = _import_requests()
    response = requests.get(
        f"{config.graph_base_url}/me",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    if response.status_code >= 400:
        payload: dict[str, Any]
        try:
            payload = response.json() if response.content else {}
        except ValueError:
            payload = {}
        raise OneDriveServiceError(
            _graph_error_message(response.status_code, payload, operation="me")
        )

    data = response.json() if response.content else {}
    return str(data.get("mail") or data.get("userPrincipalName") or "").strip()


def _serialize_cache_payload(cache, account_email: str = "") -> str:
    payload = {
        "version": 1,
        "msal_cache": cache.serialize(),
        "account_email": (account_email or "").strip(),
        "scopes": SCOPES,
        "updated_at": _utc_now_iso(),
    }
    return json.dumps(payload, ensure_ascii=False)


def _parse_token_json(token_json: str) -> dict[str, Any]:
    try:
        payload = json.loads(token_json or "{}")
    except json.JSONDecodeError as exc:
        raise OneDriveServiceError("Token OAuth do OneDrive inválido. Reconecte a conta.") from exc

    if not isinstance(payload, dict) or not payload.get("msal_cache"):
        raise OneDriveServiceError("Token OAuth do OneDrive inválido. Reconecte a conta.")
    return payload


def exchange_code_for_token(*, code: str) -> tuple[str, str]:
    if not code:
        raise OneDriveServiceError("Codigo OAuth ausente no callback do OneDrive.")

    config = _load_config()
    cache = _new_cache()
    app = _build_app(config, cache)

    result = app.acquire_token_by_authorization_code(
        code=code,
        scopes=SCOPES,
        redirect_uri=get_ms_redirect_uri(),
    )

    if not isinstance(result, dict):
        logger.warning("OneDrive OAuth falhou: resposta invalida da MSAL.")
        raise OneDriveServiceError("Falha na autenticacao com Microsoft/OneDrive.")

    access_token = result.get("access_token")
    if not access_token:
        error_code = str(result.get("error") or "").strip().lower() or "unknown_error"
        error_description = _sanitize_oauth_error_description(
            str(result.get("error_description") or "")
        )
        logger.warning("OneDrive OAuth falhou: %s", error_code)
        if error_description:
            logger.info("OneDrive OAuth detalhe (sanitizado): %s", error_description)
        raise OneDriveServiceError(_token_error_message(result or {}))

    account_email = fetch_account_email(str(access_token))
    return _serialize_cache_payload(cache, account_email), account_email

def _acquire_access_token(token_json: str) -> tuple[str, str, str]:
    config = _load_config()
    payload = _parse_token_json(token_json)

    cache = _new_cache(str(payload.get("msal_cache") or ""))
    app = _build_app(config, cache)

    accounts = app.get_accounts()
    if not accounts:
        raise OneDriveServiceError(
            "Token expirado e sem refresh válido. Reconecte o OneDrive."
        )

    account = accounts[0]
    try:
        result = app.acquire_token_silent_with_error(SCOPES, account=account)
    except Exception:
        result = app.acquire_token_silent(SCOPES, account=account)

    access_token = result.get("access_token") if isinstance(result, dict) else None
    if not access_token:
        raise OneDriveServiceError(
            "Token expirado e sem refresh válido. Reconecte o OneDrive."
        )

    account_email = str(payload.get("account_email") or account.get("username") or "").strip()
    updated_token_json = _serialize_cache_payload(cache, account_email)
    return str(access_token), updated_token_json, account_email


def _build_folder_upload_url(
    *,
    graph_base_url: str,
    file_name: str,
    folder_name: str = DEFAULT_UPLOAD_FOLDER,
    folder_id: str | None = None,
    drive_id: str | None = None,
) -> str:
    clean_name = (file_name or "").strip()
    if not clean_name:
        clean_name = "backup.zip"
    encoded_name = quote(clean_name, safe="")

    selected_drive_id = (drive_id or "").strip()
    selected_folder_id = (folder_id or "").strip()

    if selected_folder_id:
        if selected_folder_id.lower() == "root":
            if selected_drive_id:
                encoded_drive = quote(selected_drive_id, safe="")
                return f"{graph_base_url}/drives/{encoded_drive}/root:/{encoded_name}:/content"
            return f"{graph_base_url}/me/drive/root:/{encoded_name}:/content"
        encoded_folder = quote(selected_folder_id, safe="")
        if selected_drive_id:
            encoded_drive = quote(selected_drive_id, safe="")
            return f"{graph_base_url}/drives/{encoded_drive}/items/{encoded_folder}:/{encoded_name}:/content"
        return f"{graph_base_url}/me/drive/items/{encoded_folder}:/{encoded_name}:/content"

    clean_folder = (folder_name or DEFAULT_UPLOAD_FOLDER).strip().strip("/")
    encoded_path = quote(f"{clean_folder}/{clean_name}", safe="")
    if selected_drive_id:
        encoded_drive = quote(selected_drive_id, safe="")
        return f"{graph_base_url}/drives/{encoded_drive}/root:/{encoded_path}:/content"
    return f"{graph_base_url}/me/drive/root:/{encoded_path}:/content"


def _list_folders_with_access_token(
    *,
    access_token: str,
    graph_base_url: str,
    parent_id: str | None = None,
    drive_id: str | None = None,
) -> dict[str, object]:
    requests = _import_requests()
    selected_drive_id = (drive_id or "").strip()
    selected_parent_id = (parent_id or "").strip() or "root"

    if selected_parent_id == "root":
        if selected_drive_id:
            encoded_drive = quote(selected_drive_id, safe="")
            list_url = f"{graph_base_url}/drives/{encoded_drive}/root/children"
            endpoint_label = "/drives/{drive_id}/root/children"
        else:
            list_url = f"{graph_base_url}/me/drive/root/children"
            endpoint_label = "/me/drive/root/children"
    else:
        encoded_parent = quote(selected_parent_id, safe="")
        if selected_drive_id:
            encoded_drive = quote(selected_drive_id, safe="")
            list_url = f"{graph_base_url}/drives/{encoded_drive}/items/{encoded_parent}/children"
            endpoint_label = "/drives/{drive_id}/items/{item_id}/children"
        else:
            list_url = f"{graph_base_url}/me/drive/items/{encoded_parent}/children"
            endpoint_label = "/me/drive/items/{item_id}/children"

    logger.info(
        "OneDrive folder list request: endpoint=%s parent_is_root=%s drive_id_present=%s",
        endpoint_label,
        selected_parent_id == "root",
        bool(selected_drive_id),
    )

    response = requests.get(
        list_url,
        headers={"Authorization": f"Bearer {access_token}"},
        params={
            "$select": "id,name,folder,parentReference",
            "$orderby": "name",
            "$top": "200",
        },
        timeout=30,
    )
    if response.status_code >= 400:
        payload: dict[str, Any]
        try:
            payload = response.json() if response.content else {}
        except ValueError:
            payload = {}
        error_obj = payload.get("error") if isinstance(payload, dict) else {}
        error_code = str((error_obj or {}).get("code") or "").strip().lower() or "unknown"
        logger.warning(
            "OneDrive folder list failed: endpoint=%s status=%s error_code=%s",
            endpoint_label,
            response.status_code,
            error_code,
        )
        debug_code = "GRAPH_LIST_CHILDREN_FAILED"
        if response.status_code == 401:
            debug_code = "GRAPH_TOKEN_INVALID"
        elif response.status_code == 403:
            debug_code = "GRAPH_PERMISSION_DENIED"
        raise OneDriveServiceError(
            _graph_error_message(response.status_code, payload, operation="list"),
            debug_code=debug_code,
            http_status=response.status_code,
        )

    payload = response.json() if response.content else {}
    folders: list[dict[str, str | None]] = []
    for item in payload.get("value", []) if isinstance(payload, dict) else []:
        if not isinstance(item, dict) or not item.get("folder"):
            continue
        folder_id = str(item.get("id") or "").strip()
        folder_name = str(item.get("name") or "").strip()
        if not folder_id or not folder_name:
            continue
        parent_reference = item.get("parentReference") if isinstance(item.get("parentReference"), dict) else {}
        folder_drive_id = str(parent_reference.get("driveId") or selected_drive_id or "").strip()
        folders.append(
            {
                "id": folder_id,
                "drive_id": folder_drive_id or None,
                "name": folder_name,
                "path_label": folder_name,
            }
        )

    logger.info(
        "OneDrive folder list success: endpoint=%s total=%s",
        endpoint_label,
        len(folders),
    )

    return {
        "parent_id": selected_parent_id,
        "drive_id": selected_drive_id or None,
        "folders": folders,
    }


def get_connected_account(*, token_json: str) -> dict[str, str]:
    access_token, updated_token_json, cached_email = _acquire_access_token(token_json)
    account_email = fetch_account_email(access_token) or cached_email

    refreshed_payload = _parse_token_json(updated_token_json)
    refreshed_payload["account_email"] = account_email
    refreshed_payload["updated_at"] = _utc_now_iso()

    return {
        "account_email": account_email,
        "token_json": json.dumps(refreshed_payload, ensure_ascii=False),
    }


def list_onedrive_folders(
    *,
    token_json: str,
    parent_id: str | None = None,
    drive_id: str | None = None,
) -> dict[str, object]:
    config = _load_config()
    access_token, updated_token_json, account_email = _acquire_access_token(token_json)
    list_result = _list_folders_with_access_token(
        access_token=access_token,
        graph_base_url=config.graph_base_url,
        parent_id=parent_id,
        drive_id=drive_id,
    )
    list_result["token_json"] = updated_token_json
    list_result["account_email"] = account_email
    return list_result


def upload_zip_backup_with_access_token(
    *,
    access_token: str,
    zip_path: str,
    file_name: str,
    folder_name: str = DEFAULT_UPLOAD_FOLDER,
    folder_id: str | None = None,
    drive_id: str | None = None,
) -> dict[str, str]:
    if not zip_path or not os.path.exists(zip_path):
        raise OneDriveServiceError("Arquivo ZIP de backup não encontrado para upload.")

    config = _load_config()
    clean_name = (file_name or os.path.basename(zip_path)).strip() or os.path.basename(zip_path)
    upload_url = _build_folder_upload_url(
        graph_base_url=config.graph_base_url,
        file_name=clean_name,
        folder_name=folder_name,
        folder_id=folder_id,
        drive_id=drive_id,
    )
    requests = _import_requests()

    with open(zip_path, "rb") as handle:
        response = requests.put(
            upload_url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/zip",
            },
            data=handle,
            timeout=180,
        )

    if response.status_code in {200, 201}:
        response_payload = response.json() if response.content else {}
        return {
            "file_id": str(response_payload.get("id") or ""),
            "file_name": str(response_payload.get("name") or clean_name),
        }

    payload: dict[str, Any]
    try:
        payload = response.json() if response.content else {}
    except ValueError:
        payload = {}

    raise OneDriveServiceError(
        _graph_error_message(response.status_code, payload, operation="upload")
    )


def upload_zip_backup(
    *,
    token_json: str,
    zip_path: str,
    file_name: str,
    folder_name: str = DEFAULT_UPLOAD_FOLDER,
    folder_id: str | None = None,
    drive_id: str | None = None,
) -> dict[str, str]:
    if not zip_path or not os.path.exists(zip_path):
        raise OneDriveServiceError("Arquivo ZIP de backup não encontrado para upload.")

    config = _load_config()
    access_token, updated_token_json, account_email = _acquire_access_token(token_json)
    upload_result = upload_zip_backup_with_access_token(
        access_token=access_token,
        zip_path=zip_path,
        file_name=file_name,
        folder_name=folder_name,
        folder_id=folder_id,
        drive_id=drive_id,
    )
    upload_result["account_email"] = account_email
    upload_result["token_json"] = updated_token_json
    return upload_result
