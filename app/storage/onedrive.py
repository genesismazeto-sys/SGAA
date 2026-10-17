"""OneDrive managed storage (Microsoft Graph): the second permanent document copy.

The same managed-storage surface the Drive mirror worker already drives for
Google (``ensure_folder`` / ``upload`` / ``download``), over the signed-in
account's own drive (``/me/drive``), on the SAME folder conventions:
``SGAA/COMPROVANTES/<turma>/<eixo>/<aluno>`` and ``SGAA/ARQUIVOS``.

IDENTITY WITHOUT APP PROPERTIES
    OneDrive has no per-file application properties, so a folder is the child
    of its parent with its display name, and a file is the child of its folder
    with its business file name -- both deterministic.  Every create uses
    ``conflictBehavior=fail``: a retry, an interrupted transfer or two
    overlapping passes find the existing item instead of making a second one.
    An upload never trusts an existing item: it returns the item with the
    SHA-256 of the bytes OneDrive actually serves (read back), so a different
    file under the same name is an integrity mismatch for the worker, never an
    adoption.

HTTP
    ``requests`` with fixed timeouts; the bearer token is sent only to Graph and
    redirects are never followed with it.  File bytes are read from Graph's
    short-lived pre-authorized download address, which carries no credential.
    Errors are the sanitized ``app.storage.contracts`` classes, never provider
    text.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from urllib.parse import quote

from flask import current_app

import app.cloud_connections as cloud_connections
from app.cloud_account_identity import AccountIdentityError, onedrive_account_key
from app.prod1_storage_ddl import BUSINESS_DOCUMENT_MAX_BYTES
from app.storage.contracts import (
    RemoteObject,
    StorageAuthorizationError,
    StorageConfigurationError,
    StorageConflictError,
    StorageConnectionError,
    StorageError,
    StorageTransientError,
)

GRAPH = "https://graph.microsoft.com/v1.0"
#: ``app.extensions`` key of an injected OneDrive storage (tests); production
#: resolves the active OneDrive connection.
ONEDRIVE_STORAGE_EXTENSION = "onedrive_mirror_storage"
#: (connect, read) seconds.
HTTP_TIMEOUT = (5.0, 60.0)
_READ_CHUNK = 64 * 1024
#: Graph item ids: alphanumeric, plus ``!`` on personal drives.
_ITEM_ID_RE = re.compile(r"^[A-Za-z0-9!_.-]{1,256}$")
#: Characters OneDrive refuses in a name.
_FORBIDDEN_NAME_CHARS = re.compile(r'["*:<>?/\\|\x00-\x1f]')

_AUTH_MESSAGE = "A autorização do OneDrive precisa ser renovada."
_TRANSIENT_MESSAGE = "O OneDrive está temporariamente indisponível."


def is_item_id(value) -> bool:
    return isinstance(value, str) and bool(_ITEM_ID_RE.fullmatch(value))


def safe_name(value) -> str:
    """The deterministic OneDrive form of a display or file name."""
    cleaned = _FORBIDDEN_NAME_CHARS.sub("-", str(value or "")).strip().rstrip(". ")
    return cleaned[:255] or "documento"


class _Conflict(Exception):
    """Graph answered 409: the name is already taken under that parent."""


class OneDriveManagedObjectStorage:
    provider = "onedrive"

    def __init__(self, access_token: str, *, access_token_refresher: Callable[[], str] | None = None,
                 session=None) -> None:
        if not access_token:
            raise StorageAuthorizationError(_AUTH_MESSAGE)
        self._token = access_token
        self._refresher = access_token_refresher
        self._session = session

    def __repr__(self) -> str:
        return "OneDriveManagedObjectStorage(<token>)"

    # -- HTTP boundary ----------------------------------------------------

    @property
    def _http(self):
        if self._session is None:
            import requests

            self._session = requests.Session()
        return self._session

    def _send(self, method: str, url: str, *, authorized: bool = True, **kwargs):
        import requests

        headers = dict(kwargs.pop("headers", None) or {})
        if authorized:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            return self._http.request(method, url, headers=headers, timeout=HTTP_TIMEOUT,
                                      allow_redirects=False, **kwargs)
        except requests.RequestException:
            raise StorageTransientError(_TRANSIENT_MESSAGE) from None

    def _call(self, method: str, path: str, **kwargs):
        """One Graph call; a 401 refreshes the token once.  Returns the response (2xx / 404)."""
        response = self._send(method, GRAPH + path, **kwargs)
        if response.status_code == 401 and self._refresher is not None:
            self._token = self._refresher() or ""
            if not self._token:
                raise StorageAuthorizationError(_AUTH_MESSAGE)
            response = self._send(method, GRAPH + path, **kwargs)
        status = int(response.status_code)
        if 200 <= status < 300 or status == 404:
            return response
        if status == 409:
            raise _Conflict()
        if status in (401, 403):
            raise StorageAuthorizationError(_AUTH_MESSAGE)
        if status == 429 or status >= 500:
            raise StorageTransientError(_TRANSIENT_MESSAGE)
        raise StorageError("O OneDrive recusou a operação solicitada.")

    @staticmethod
    def _item(response) -> dict:
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if not isinstance(payload, dict) or not is_item_id(payload.get("id")):
            raise StorageError("O OneDrive retornou uma resposta inesperada.")
        return payload

    @staticmethod
    def _items_path(parent_id: str) -> str:
        return "/me/drive/root" if parent_id == "root" else f"/me/drive/items/{quote(parent_id, safe='')}"

    def _child(self, parent_id: str, name: str) -> dict | None:
        response = self._call("GET", f"{self._items_path(parent_id)}:/{quote(name, safe='')}")
        return None if response.status_code == 404 else self._item(response)

    # -- managed storage ----------------------------------------------------

    def account_key(self) -> str:
        """The LOGICAL account key of the signed-in user (Graph ``/me`` id)."""
        response = self._call("GET", "/me?$select=id")
        if response.status_code == 404:
            raise StorageError("O OneDrive retornou uma resposta inesperada.")
        try:
            return onedrive_account_key(response.json().get("id"))
        except (ValueError, AttributeError, AccountIdentityError):
            raise StorageError("O OneDrive retornou uma resposta inesperada.") from None

    def ensure_folder(self, *, parent_id: str, kind: str, semantic_id: str, display_name: str) -> str:
        name = safe_name(display_name)
        for _attempt in (1, 2):
            found = self._child(parent_id, name)
            if found is not None:
                if "folder" not in found:
                    raise StorageConflictError("Há um arquivo no lugar de uma pasta gerenciada.")
                return str(found["id"])
            body = {"name": name, "folder": {}, "@microsoft.graph.conflictBehavior": "fail"}
            try:
                return str(self._item(self._call("POST", f"{self._items_path(parent_id)}/children", json=body))["id"])
            except _Conflict:
                continue  # created concurrently: the next lookup finds it
        raise StorageTransientError(_TRANSIENT_MESSAGE)

    def upload(self, *, parent_id: str, stored_filename: str, content: bytes, mime_type: str,
               operation_key: str, object_kind: str, semantic_properties) -> RemoteObject:
        name = safe_name(stored_filename)
        item = self._child(parent_id, name)
        reused = item is not None
        if item is None:
            path = (f"{self._items_path(parent_id)}:/{quote(name, safe='')}:/content"
                    "?@microsoft.graph.conflictBehavior=fail")
            try:
                item = self._item(self._call("PUT", path, data=content, headers={"Content-Type": mime_type}))
            except _Conflict:
                item, reused = self._child(parent_id, name), True
                if item is None:
                    raise StorageTransientError(_TRANSIENT_MESSAGE) from None
        if "file" not in item:
            raise StorageConflictError("Há uma pasta no lugar de um arquivo gerenciado.")
        data = self.download(str(item["id"]))
        parent = (item.get("parentReference") or {}).get("id") or parent_id
        return RemoteObject(file_id=str(item["id"]), parent_id=str(parent), name=str(item.get("name") or name),
                            size=len(data), sha256=hashlib.sha256(data).hexdigest(), reused=reused)

    def download_url(self, file_id: str) -> tuple[str, int]:
        """Graph's short-lived pre-authorized download address of a file and its size."""
        response = self._call(
            "GET", f"/me/drive/items/{quote(file_id, safe='')}?$select=id,size,file,@microsoft.graph.downloadUrl"
        )
        if response.status_code == 404:
            raise StorageError("O arquivo não existe mais no OneDrive.")
        item = self._item(response)
        url = str(item.get("@microsoft.graph.downloadUrl") or "")
        if not url.startswith("https://") or "file" not in item:
            raise StorageError("O OneDrive retornou uma resposta inesperada.")
        return url, int(item.get("size") or 0)

    def download(self, file_id: str, *, max_bytes: int = BUSINESS_DOCUMENT_MAX_BYTES) -> bytes:
        url, _size = self.download_url(file_id)
        # The pre-authorized address carries no credential, so it may redirect freely.
        import requests

        try:
            with self._http.get(url, timeout=HTTP_TIMEOUT, stream=True, allow_redirects=True) as response:
                if response.status_code != 200:
                    raise StorageTransientError(_TRANSIENT_MESSAGE)
                chunks, total = [], 0
                for chunk in response.iter_content(_READ_CHUNK):
                    total += len(chunk)
                    if total > max_bytes:
                        raise StorageError("O arquivo do OneDrive excede o limite.")
                    chunks.append(chunk)
        except requests.RequestException:
            raise StorageTransientError(_TRANSIENT_MESSAGE) from None
        return b"".join(chunks)


def _translate_connection_error(exc: cloud_connections.CloudConnectionError, *, phase: str) -> StorageError:
    if exc.debug_code == "AUTH_RECONNECT_REQUIRED":
        return StorageAuthorizationError(_AUTH_MESSAGE)
    if exc.debug_code.startswith("APPLICATION_CREDENTIAL"):
        return StorageConfigurationError("As credenciais do aplicativo Microsoft não estão configuradas corretamente.")
    return StorageConnectionError("Não foi possível acessar o OneDrive.", phase=phase)


def resolve_onedrive_managed_storage(conn, *, extension_key: str = ONEDRIVE_STORAGE_EXTENSION):
    """The active OneDrive connection's managed storage (an injected one in tests)."""
    override = current_app.extensions.get(extension_key)
    if override is not None:
        return override(conn) if callable(override) else override
    try:
        access_token, _email = cloud_connections.get_authenticated_access_token(conn, "onedrive")
    except cloud_connections.CloudConnectionError as exc:
        raise _translate_connection_error(exc, phase="access") from exc

    def recover_access_token() -> str:
        try:
            token, _email = cloud_connections.recover_authenticated_access_token_after_401(conn, "onedrive")
            return token
        except cloud_connections.CloudConnectionError as exc:
            raise _translate_connection_error(exc, phase="refresh") from exc

    return OneDriveManagedObjectStorage(access_token, access_token_refresher=recover_access_token)


__all__ = [
    "ONEDRIVE_STORAGE_EXTENSION",
    "OneDriveManagedObjectStorage",
    "is_item_id",
    "resolve_onedrive_managed_storage",
    "safe_name",
]
