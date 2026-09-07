from __future__ import annotations

from flask import current_app
from typing import Callable

import app.cloud_connections as cloud_connections
from app.storage.contracts import (
    StorageAuthorizationError,
    StorageConnectionError,
    StorageConfigurationError,
    StorageError,
)
from app.storage.google_drive import GoogleDriveManagedObjectStorage


def _translate_connection_error(
    exc: cloud_connections.CloudConnectionError, *, phase: str
) -> StorageError:
    if exc.debug_code == "AUTH_RECONNECT_REQUIRED":
        return StorageAuthorizationError("A autorização do Google Drive precisa ser renovada.")
    if exc.debug_code.startswith("APPLICATION_CREDENTIAL"):
        return StorageConfigurationError(
            "As credenciais do aplicativo Google não estão configuradas corretamente."
        )
    return StorageConnectionError(
        "Não foi possível acessar o Google Drive.", phase=phase
    )


def resolve_google_managed_storage(
    conn,
    *,
    extension_key: str,
    storage_factory: Callable[..., object] = GoogleDriveManagedObjectStorage,
):
    override = current_app.extensions.get(extension_key)
    if override is not None:
        return override(conn) if callable(override) else override
    try:
        access_token, _identity = cloud_connections.get_authenticated_access_token(conn, "google")
    except cloud_connections.CloudConnectionError as exc:
        raise _translate_connection_error(exc, phase="access") from exc

    def recover_access_token() -> str:
        try:
            token, _identity = cloud_connections.recover_authenticated_access_token_after_401(
                conn, "google"
            )
            return token
        except cloud_connections.CloudConnectionError as exc:
            raise _translate_connection_error(exc, phase="refresh") from exc

    return storage_factory(
        access_token, access_token_refresher=recover_access_token
    )


__all__ = ["resolve_google_managed_storage"]
