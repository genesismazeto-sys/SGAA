"""Provider-neutral storage boundaries."""

from app.storage.contracts import (
    RemoteObject,
    StorageAuthorizationError,
    StorageConfigurationError,
    StorageConflictError,
    StorageError,
    StorageIntegrityError,
    StorageTransientError,
)

__all__ = [
    "RemoteObject",
    "StorageAuthorizationError",
    "StorageConfigurationError",
    "StorageConflictError",
    "StorageError",
    "StorageIntegrityError",
    "StorageTransientError",
]
