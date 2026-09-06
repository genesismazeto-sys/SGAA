from __future__ import annotations

import io
import random
import socket
import time
from collections.abc import Callable

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

from app.storage.contracts import (
    RemoteObject,
    StorageAuthorizationError,
    StorageConflictError,
    StorageError,
    StorageTransientError,
)


FOLDER_MIME = "application/vnd.google-apps.folder"
FILE_FIELDS = "id,name,parents,size,sha256Checksum,appProperties,trashed"


def _q(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace("'", "\\'")


class GoogleDriveComprovanteStorage:
    provider = "google"

    def __init__(
        self,
        access_token: str,
        *,
        service=None,
        retry_delays=(0.1, 0.25, 0.5),
        access_token_refresher: Callable[[], str] | None = None,
        service_factory=None,
    ):
        if not access_token and service is None:
            raise StorageAuthorizationError("A autorização do Google Drive precisa ser renovada.")
        self._service_factory = service_factory or self._build_service
        self._service = service or self._service_factory(access_token)
        self._retry_delays = tuple(float(value) for value in retry_delays)
        self._access_token_refresher = access_token_refresher
        self._auth_generation = 0

    @staticmethod
    def _build_service(access_token: str):
        return build(
            "drive",
            "v3",
            credentials=Credentials(token=access_token),
            cache_discovery=False,
        )

    @staticmethod
    def _status(exc: Exception) -> int | None:
        response = getattr(exc, "resp", None)
        try:
            return int(getattr(response, "status", None))
        except (TypeError, ValueError):
            return None

    def _translate(self, exc: Exception) -> StorageError:
        status = self._status(exc)
        if status == 401:
            return StorageAuthorizationError(
                "A autorização do Google Drive precisa ser renovada."
            )
        if status == 429 or (status is not None and 500 <= status <= 599):
            return StorageTransientError("O Google Drive está temporariamente indisponível.")
        if status is not None:
            return StorageError("O Google Drive recusou a operação solicitada.")
        if isinstance(exc, (OSError, socket.timeout, TimeoutError, ConnectionError)):
            return StorageTransientError(
                "O Google Drive está temporariamente indisponível."
            )
        return StorageError("Não foi possível concluir a operação no Google Drive.")

    def _refresh_service(self) -> None:
        if self._access_token_refresher is None:
            raise StorageAuthorizationError(
                "A autorização do Google Drive precisa ser renovada."
            )
        access_token = self._access_token_refresher()
        if not access_token:
            raise StorageAuthorizationError(
                "A autorização do Google Drive precisa ser renovada."
            )
        self._service = self._service_factory(access_token)
        self._auth_generation += 1

    def _with_auth_recovery(self, operation: Callable[[], object]):
        try:
            return operation()
        except StorageAuthorizationError:
            self._refresh_service()
            return operation()

    def _retry(self, operation: Callable[[], object]):
        attempts = len(self._retry_delays) + 1
        for attempt in range(attempts):
            try:
                return operation()
            except (HttpError, OSError, socket.timeout, TimeoutError, ConnectionError) as exc:
                translated = self._translate(exc)
                if not translated.retryable or attempt + 1 >= attempts:
                    raise translated from exc
                delay = self._retry_delays[attempt]
                time.sleep(delay + random.uniform(0, delay / 4 if delay else 0))
        raise StorageTransientError("Não foi possível concluir a operação no Google Drive.")

    def _list_once(self, query: str) -> list[dict]:
        files: list[dict] = []
        page_token = None
        while True:
            request = self._service.files().list(
                q=query,
                spaces="drive",
                fields=f"nextPageToken,files({FILE_FIELDS})",
                pageSize=100,
                pageToken=page_token,
            )
            result = self._retry(lambda request=request: request.execute(num_retries=0)) or {}
            files.extend(result.get("files") or [])
            page_token = result.get("nextPageToken")
            if not page_token:
                return files

    def _list(self, query: str, *, recover_auth: bool = True) -> list[dict]:
        if not recover_auth:
            return self._list_once(query)
        return self._with_auth_recovery(lambda: self._list_once(query))

    def ensure_folder(
        self, *, parent_id: str, kind: str, semantic_id: str, display_name: str
    ) -> str:
        properties = {
            "sgaaManaged": "true",
            "sgaaKind": str(kind),
            "sgaaSemanticId": str(semantic_id),
        }
        query = " and ".join(
            (
                f"mimeType='{FOLDER_MIME}'",
                f"'{_q(parent_id)}' in parents",
                "trashed=false",
                "appProperties has { key='sgaaManaged' and value='true' }",
                f"appProperties has {{ key='sgaaKind' and value='{_q(kind)}' }}",
                f"appProperties has {{ key='sgaaSemanticId' and value='{_q(semantic_id)}' }}",
            )
        )
        starting_generation = self._auth_generation
        matches = self._list(query)
        if len(matches) > 1:
            raise StorageConflictError("Há mais de uma pasta gerenciada para a mesma identidade.")
        if matches:
            return str(matches[0]["id"])
        body = {
            "name": str(display_name),
            "mimeType": FOLDER_MIME,
            "parents": [str(parent_id)],
            "appProperties": properties,
        }
        def create_once():
            request = self._service.files().create(
                body=body, fields="id", supportsAllDrives=True
            )
            try:
                return request.execute(num_retries=0) or {}
            except (HttpError, OSError, socket.timeout, TimeoutError, ConnectionError) as exc:
                raise self._translate(exc) from exc

        try:
            created = create_once()
        except StorageAuthorizationError:
            if self._auth_generation != starting_generation:
                raise
            self._refresh_service()
            matches = self._list(query, recover_auth=False)
            if len(matches) > 1:
                raise StorageConflictError(
                    "Há mais de uma pasta gerenciada para a mesma identidade."
                )
            if matches:
                return str(matches[0]["id"])
            created = create_once()
        except StorageTransientError:
            matches = self._list(
                query,
                recover_auth=self._auth_generation == starting_generation,
            )
            if len(matches) > 1:
                raise StorageConflictError(
                    "Há mais de uma pasta gerenciada para a mesma identidade."
                )
            if matches:
                return str(matches[0]["id"])
            raise
        file_id = str(created.get("id") or "")
        if not file_id:
            raise StorageError("O Google Drive não retornou a identidade da pasta criada.")
        return file_id

    def _find_operation(
        self, parent_id: str, operation_key: str, *, recover_auth: bool = True
    ) -> list[dict]:
        query = " and ".join(
            (
                f"'{_q(parent_id)}' in parents",
                "trashed=false",
                "appProperties has { key='sgaaManaged' and value='true' }",
                "appProperties has { key='sgaaKind' and value='comprovante' }",
                f"appProperties has {{ key='sgaaOperation' and value='{_q(operation_key)}' }}",
            )
        )
        return self._list(query, recover_auth=recover_auth)

    @staticmethod
    def _remote_object(payload: dict, parent_id: str, *, reused: bool) -> RemoteObject:
        parents = payload.get("parents") or [parent_id]
        return RemoteObject(
            file_id=str(payload.get("id") or ""),
            parent_id=str(parents[0] if parents else parent_id),
            name=str(payload.get("name") or ""),
            size=int(payload.get("size") or 0),
            sha256=(str(payload.get("sha256Checksum")) if payload.get("sha256Checksum") else None),
            reused=reused,
        )

    def upload(
        self,
        *,
        parent_id: str,
        stored_filename: str,
        content: bytes,
        mime_type: str,
        operation_key: str,
        request_id: int,
        attachment_id: int,
        _authorization_retry: bool = True,
    ) -> RemoteObject:
        starting_generation = self._auth_generation
        matches = self._find_operation(
            parent_id, operation_key, recover_auth=_authorization_retry
        )
        if len(matches) > 1:
            raise StorageConflictError("Há mais de um arquivo remoto para a mesma operação.")
        if matches:
            return self._remote_object(matches[0], parent_id, reused=True)

        media = MediaIoBaseUpload(
            io.BytesIO(content),
            mimetype=mime_type,
            chunksize=256 * 1024,
            resumable=True,
        )
        body = {
            "name": stored_filename,
            "parents": [parent_id],
            "appProperties": {
                "sgaaManaged": "true",
                "sgaaKind": "comprovante",
                "sgaaOperation": operation_key,
                "sgaaRequest": str(request_id),
                "sgaaAttachment": str(attachment_id),
            },
        }
        request = self._service.files().create(
            body=body,
            media_body=media,
            fields=FILE_FIELDS,
            supportsAllDrives=True,
        )
        try:
            response = None
            while response is None:
                _status, response = self._retry(
                    lambda: request.next_chunk(num_retries=0)
                )
            return self._remote_object(response or {}, parent_id, reused=False)
        except StorageAuthorizationError:
            if (
                not _authorization_retry
                or self._auth_generation != starting_generation
            ):
                raise
            self._refresh_service()
            return self.upload(
                parent_id=parent_id,
                stored_filename=stored_filename,
                content=content,
                mime_type=mime_type,
                operation_key=operation_key,
                request_id=request_id,
                attachment_id=attachment_id,
                _authorization_retry=False,
            )

    def _set_trashed(self, file_id: str, trashed: bool) -> None:
        def update_once():
            request = self._service.files().update(
                fileId=str(file_id),
                body={"trashed": bool(trashed)},
                fields="id,trashed",
                supportsAllDrives=True,
            )
            return self._retry(lambda: request.execute(num_retries=0))

        self._with_auth_recovery(update_once)

    def trash(self, file_id: str) -> None:
        self._set_trashed(file_id, True)

    def untrash(self, file_id: str) -> None:
        self._set_trashed(file_id, False)

    def download(self, file_id: str) -> bytes:
        def download_once():
            target = io.BytesIO()
            downloader = MediaIoBaseDownload(
                target,
                self._service.files().get_media(
                    fileId=str(file_id), supportsAllDrives=True
                ),
                chunksize=256 * 1024,
            )
            done = False
            while not done:
                _status, done = self._retry(
                    lambda: downloader.next_chunk(num_retries=0)
                )
            return target.getvalue()

        return self._with_auth_recovery(download_once)


__all__ = ["GoogleDriveComprovanteStorage"]
