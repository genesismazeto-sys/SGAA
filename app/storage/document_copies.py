"""Reading a business document from its verified copies.

A canonical object (``storage_objects``) can be read from three places:

    Supabase Storage   the upload staging copy -- a 60-second signed URL, as
                       before -- unless the copy was released
                       (``copy_registry``)
    Google Drive       the ``storage_objects`` mirror columns, when ``synced``
                       and bound to the ACTIVE Google account
    OneDrive           ``copy_registry`` when ``synced`` and bound to the
                       ACTIVE OneDrive account

A Drive copy is served only after its bytes are proven against the recorded
size and SHA-256; one that cannot be read or does not match is skipped and the
next verified copy is tried.  A document larger than the hosting platform's
response limit cannot be relayed through the server: OneDrive then serves it
through Graph's short-lived pre-authorized address (size checked), and Google
cannot -- which is why ``staging_release`` never releases a large document
that has no verified OneDrive copy.

The caller authorizes the actor first; nothing here decides who may read.
The same verified read is the mirror worker's source once Supabase is
released and the release worker's proof before it releases.
"""

from __future__ import annotations

import hashlib
import io
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

import app.cloud_connections as cloud_connections
from app.storage import copy_registry
from app.storage.contracts import StorageError, StorageIntegrityError
from app.storage.google_connection import resolve_google_managed_storage
from app.storage.object_store import STORAGE_OBJECT_MISSING, CanonicalStoreError
from app.storage.onedrive import resolve_onedrive_managed_storage

logger = logging.getLogger(__name__)

#: ``app.extensions`` key of an injected Google storage (tests) -- the mirror worker's key.
GOOGLE_STORAGE_EXTENSION = "drive_mirror_storage"
#: Largest document relayed through the server: under the hosting platform's
#: 4.5 MB function-response limit.
DRIVE_PROXY_MAX_BYTES = 4 * 1024 * 1024
COPY_UNAVAILABLE = "COPY_UNAVAILABLE"


class DocumentNotFound(RuntimeError):
    """No active object, or every copy is known to be missing."""


class DocumentUnavailable(RuntimeError):
    """The document exists but no copy can be served right now."""


class CopyUnavailable(RuntimeError):
    """No verified copy could be read; ``code`` is fixed and value-free."""

    code = COPY_UNAVAILABLE


@dataclass(frozen=True)
class Copy:
    provider: str
    file_id: str
    account_key: str


@dataclass(frozen=True)
class DocumentRead:
    """Either a short-lived ``url`` to redirect to or the verified ``content`` to send."""

    url: str | None = field(default=None, repr=False)
    content: bytes | None = field(default=None, repr=False)
    mime_type: str = "application/octet-stream"
    filename: str | None = None


def _active_key(conn, provider: str) -> str | None:
    account = cloud_connections.get_active_cloud_account(conn, provider)
    return None if account is None else account.get("provider_account_key")


def verified_copies(conn, object_id: int) -> list[Copy]:
    """The synced copies bound to each provider's ACTIVE account (Google first)."""
    copies = []
    row = conn.execute(
        "SELECT drive_sync_state, drive_file_id, drive_account_key FROM storage_objects WHERE id = ?",
        (int(object_id),),
    ).fetchone()
    if row is not None and row[0] == "synced" and row[2] is not None and row[2] == _active_key(conn, "google"):
        copies.append(Copy("google", str(row[1]), str(row[2])))
    onedrive = copy_registry.synced_copy(conn, object_id)
    if onedrive is not None and onedrive[1] == _active_key(conn, copy_registry.PROVIDER):
        copies.append(Copy(copy_registry.PROVIDER, *onedrive))
    return copies


def storage_for(conn, provider: str):
    if provider == "google":
        return resolve_google_managed_storage(conn, extension_key=GOOGLE_STORAGE_EXTENSION)
    return resolve_onedrive_managed_storage(conn)


def read_copy(conn, copy: Copy, *, sha256: str, size_bytes: int) -> bytes:
    """The copy's bytes, proven against the recorded size and SHA-256."""
    content = storage_for(conn, copy.provider).download(copy.file_id)
    if len(content) != int(size_bytes) or hashlib.sha256(content).hexdigest() != sha256:
        raise StorageIntegrityError("A cópia remota não corresponde ao documento registrado.")
    return content


def read_from_copies(conn, copies: list[Copy], *, sha256: str, size_bytes: int) -> bytes:
    """Verified bytes from the first readable copy of ``copies``."""
    for copy in copies:
        try:
            return read_copy(conn, copy, sha256=sha256, size_bytes=size_bytes)
        except StorageError as exc:
            logger.warning("document copy unreadable (%s, %s)", copy.provider, type(exc).__name__)
    raise CopyUnavailable(COPY_UNAVAILABLE)


def _serve_copy(conn, copy: Copy, obj, filename: str) -> DocumentRead | None:
    size = int(obj["size_bytes"])
    if size <= DRIVE_PROXY_MAX_BYTES:
        content = read_copy(conn, copy, sha256=str(obj["sha256"]), size_bytes=size)
        return DocumentRead(content=content, mime_type=str(obj["mime_type"]), filename=filename)
    if copy.provider == copy_registry.PROVIDER:
        url, remote_size = storage_for(conn, copy.provider).download_url(copy.file_id)
        if remote_size == size:
            return DocumentRead(url=url)
        raise StorageIntegrityError("A cópia remota não corresponde ao documento registrado.")
    return None


def open_document(conn, object_id: int, *, store_factory: Callable[[], object], ttl_seconds: int,
                  filename: str, download: bool) -> DocumentRead:
    """How to serve an ACTIVE object to an already authorized caller.

    The Supabase staging copy first (unchanged signed-URL behaviour) unless it
    was released; on release, or when Supabase cannot serve it, every verified
    Drive copy in turn.
    """
    obj = conn.execute(
        "SELECT storage_bucket, storage_key, lifecycle_state, sha256, size_bytes, mime_type"
        " FROM storage_objects WHERE id = ?",
        (int(object_id),),
    ).fetchone()
    if obj is None or obj["lifecycle_state"] != "active":
        raise DocumentNotFound()
    staging_missing = False
    if not copy_registry.supabase_released(conn, object_id):
        try:
            signed = store_factory().create_signed_download(
                obj["storage_bucket"], obj["storage_key"], expires_in=ttl_seconds,
                download_name=filename if download else None,
            )
            return DocumentRead(url=signed.url)
        except CanonicalStoreError as exc:
            staging_missing = exc.code == STORAGE_OBJECT_MISSING
            logger.warning("staging copy unavailable (%s); trying the drive copies", exc.code)
    copies = verified_copies(conn, object_id)
    for copy in copies:
        try:
            served = _serve_copy(conn, copy, obj, filename)
        except StorageError as exc:
            logger.warning("document copy unreadable (%s, %s)", copy.provider, type(exc).__name__)
            continue
        if served is not None:
            return served
    if staging_missing and not copies:
        raise DocumentNotFound()
    raise DocumentUnavailable()


def response(read: DocumentRead, *, download: bool):
    """The private, uncached HTTP response for ``read``: a redirect or the verified bytes."""
    from flask import redirect, send_file

    if read.url is not None:
        result = redirect(read.url, code=302)
        result.headers["Referrer-Policy"] = "no-referrer"
    else:
        result = send_file(io.BytesIO(read.content), mimetype=read.mime_type, as_attachment=download,
                           download_name=read.filename, conditional=False, max_age=0)
    result.headers["X-Content-Type-Options"] = "nosniff"
    result.headers["Cache-Control"] = "private, no-store"
    return result


__all__ = [
    "COPY_UNAVAILABLE",
    "Copy",
    "CopyUnavailable",
    "DRIVE_PROXY_MAX_BYTES",
    "DocumentNotFound",
    "DocumentRead",
    "DocumentUnavailable",
    "GOOGLE_STORAGE_EXTENSION",
    "open_document",
    "read_copy",
    "read_from_copies",
    "response",
    "storage_for",
    "verified_copies",
]
