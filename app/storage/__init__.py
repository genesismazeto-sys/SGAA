"""Provider-neutral storage boundaries."""

from app.storage.contracts import (
    ManagedObjectStorage,
    RemoteObject,
    StorageAuthorizationError,
    StorageConnectionError,
    StorageConfigurationError,
    StorageConflictError,
    StorageError,
    StorageIntegrityError,
    StorageTransientError,
)

__all__ = [
    "RemoteObject",
    "ManagedObjectStorage",
    "StorageAuthorizationError",
    "StorageConnectionError",
    "StorageConfigurationError",
    "StorageConflictError",
    "StorageError",
    "StorageIntegrityError",
    "StorageTransientError",
]
