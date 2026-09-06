from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class StorageError(RuntimeError):
    """Sanitized provider-neutral storage failure."""

    code = "STORAGE_ERROR"
    retryable = False


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


class ComprovanteStorage(Protocol):
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
        request_id: int,
        attachment_id: int,
    ) -> RemoteObject: ...

    def trash(self, file_id: str) -> None: ...

    def untrash(self, file_id: str) -> None: ...

    def download(self, file_id: str) -> bytes: ...


__all__ = [
    "ComprovanteStorage",
    "RemoteObject",
    "StorageAuthorizationError",
    "StorageConfigurationError",
    "StorageConflictError",
    "StorageError",
    "StorageIntegrityError",
    "StorageTransientError",
]
