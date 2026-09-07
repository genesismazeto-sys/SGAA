from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol


class StorageError(RuntimeError):
    """Sanitized provider-neutral storage failure."""

    code = "STORAGE_ERROR"
    retryable = False


class StorageConnectionError(StorageError):
    code = "GOOGLE_CONNECTION_FAILED"

    def __init__(self, message: str, *, phase: str):
        super().__init__(message)
        self.phase = phase


class StorageTransientError(StorageError):
    code = "STORAGE_TRANSIENT"
    retryable = True


class StorageAuthorizationError(StorageError):
    code = "AUTH_RECONNECT_REQUIRED"


class StorageConfigurationError(StorageError):
    code = "APPLICATION_CREDENTIALS_INVALID"


class StorageConflictError(StorageError):
    code = "REMOTE_SEMANTIC_CONFLICT"


class StorageIntegrityError(StorageError):
    code = "REMOTE_INTEGRITY_MISMATCH"


@dataclass(frozen=True)
class RemoteObject:
    file_id: str
    parent_id: str
    name: str
    size: int
    sha256: str | None
    reused: bool = False


class ManagedObjectStorage(Protocol):
    provider: str

    def ensure_folder(self, *, parent_id: str, kind: str, semantic_id: str, display_name: str) -> str: ...

    def upload(
        self,
        *,
        parent_id: str,
        stored_filename: str,
        content: bytes,
        mime_type: str,
        operation_key: str,
        object_kind: str,
        semantic_properties: Mapping[str, str],
    ) -> RemoteObject: ...

    def find_operation(
        self, *, parent_id: str, operation_key: str, object_kind: str
    ) -> RemoteObject | None: ...

    def trash(self, file_id: str) -> None: ...

    def untrash(self, file_id: str) -> None: ...

    def download(self, file_id: str) -> bytes: ...


class ComprovanteStorage(Protocol):
    provider: str

    def ensure_folder(self, *, parent_id: str, kind: str, semantic_id: str, display_name: str) -> str: ...

    def upload(
        self, *, parent_id: str, stored_filename: str, content: bytes,
        mime_type: str, operation_key: str, request_id: int, attachment_id: int,
    ) -> RemoteObject: ...

    def trash(self, file_id: str) -> None: ...
    def untrash(self, file_id: str) -> None: ...
    def download(self, file_id: str) -> bytes: ...


__all__ = [
    "ComprovanteStorage",
    "ManagedObjectStorage",
    "RemoteObject",
    "StorageAuthorizationError",
    "StorageConfigurationError",
    "StorageConnectionError",
    "StorageConflictError",
    "StorageError",
    "StorageIntegrityError",
    "StorageTransientError",
]
