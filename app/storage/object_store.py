"""Canonical business-document object store: interface, values and errors.

Supabase Storage is THE canonical backend for business documents (STORAGE S2
prepares it; S3 switches the request / ARQUIVOS flows onto it).  Google Drive
is only an asynchronous mirror and never implements this interface.  This is
deliberately not a multi-cloud framework: one protocol, one real adapter
(``app.storage.supabase_store``) and a deterministic in-memory fake for tests.

SECURITY
    * Bucket and key are always chosen by the server (``storage_upload_intents``
      or a worker); nothing here accepts a browser-supplied locator.
    * Signed upload / download values are short-lived capability tokens: they
      live only in :class:`SignedUpload` / :class:`SignedDownload`, whose
      ``repr`` hides them, and are never written to the database or a log.
    * Every failure is a :class:`CanonicalStoreError` carrying a fixed code
      and a fixed message -- never a provider body, URL, key or secret.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Protocol

# ---------------------------------------------------------------------------
# errors
# ---------------------------------------------------------------------------

STORAGE_CONFIG_MISSING = "STORAGE_CONFIG_MISSING"
STORAGE_AUTH_FAILURE = "STORAGE_AUTH_FAILURE"
STORAGE_OBJECT_MISSING = "STORAGE_OBJECT_MISSING"
STORAGE_ALREADY_EXISTS = "STORAGE_ALREADY_EXISTS"
STORAGE_PROVIDER_UNAVAILABLE = "STORAGE_PROVIDER_UNAVAILABLE"
STORAGE_INTEGRITY_MISMATCH = "STORAGE_INTEGRITY_MISMATCH"
STORAGE_INVALID_RESPONSE = "STORAGE_INVALID_RESPONSE"
STORAGE_OBJECT_TOO_LARGE = "STORAGE_OBJECT_TOO_LARGE"
STORAGE_INVALID_LOCATOR = "STORAGE_INVALID_LOCATOR"

_MESSAGES = {
    STORAGE_CONFIG_MISSING: "canonical storage is not configured",
    STORAGE_AUTH_FAILURE: "canonical storage refused the server credentials",
    STORAGE_OBJECT_MISSING: "canonical storage object does not exist",
    STORAGE_ALREADY_EXISTS: "canonical storage object already exists",
    STORAGE_PROVIDER_UNAVAILABLE: "canonical storage is unavailable",
    STORAGE_INTEGRITY_MISMATCH: "canonical storage object does not match its recorded metadata",
    STORAGE_INVALID_RESPONSE: "canonical storage returned an unexpected response",
    STORAGE_OBJECT_TOO_LARGE: "canonical storage object exceeds the size limit",
    STORAGE_INVALID_LOCATOR: "canonical storage locator is invalid",
}
_RETRYABLE = frozenset({STORAGE_PROVIDER_UNAVAILABLE})


class CanonicalStoreError(RuntimeError):
    """Sanitized canonical-storage failure: a fixed code and a fixed message.

    ``detail`` is an optional application-owned, value-free hint (an HTTP
    status class, a missing variable NAME); it is never provider text.
    """

    def __init__(self, code: str, detail: str = "") -> None:
        if code not in _MESSAGES:
            raise ValueError("unknown canonical storage error code")
        self.code = code
        self.detail = detail
        self.retryable = code in _RETRYABLE
        message = _MESSAGES[code]
        super().__init__(f"{code}: {message}" + (f" ({detail})" if detail else ""))


# ---------------------------------------------------------------------------
# values
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SignedUpload:
    """A one-object upload capability.  ``url`` / ``token`` never appear in repr."""

    bucket: str
    key: str
    url: str = field(repr=False)
    token: str = field(repr=False)


@dataclass(frozen=True)
class SignedDownload:
    """A short-lived download capability.  ``url`` never appears in repr."""

    bucket: str
    key: str
    expires_in: int
    url: str = field(repr=False)


@dataclass(frozen=True)
class ObjectStat:
    bucket: str
    key: str
    size_bytes: int
    mime_type: str | None


@dataclass(frozen=True)
class ListedObject:
    """One object of a bucket listing: its key and, when reported, its size."""

    key: str
    size_bytes: int | None


@dataclass(frozen=True)
class VerifiedContent:
    size_bytes: int
    sha256: str
    mime_type: str | None


class CanonicalObjectStore(Protocol):
    """What S3 (request/ARQUIVOS flows) and S5 (migration) need -- nothing more."""

    backend: str

    def create_signed_upload(self, bucket: str, key: str) -> SignedUpload:
        """Signed upload for a NEW object; the key is immutable (no upsert)."""

    def create_signed_download(
        self, bucket: str, key: str, *, expires_in: int, download_name: str | None = None
    ) -> SignedDownload: ...

    def stat(self, bucket: str, key: str) -> ObjectStat:
        """Metadata of an existing object; ``STORAGE_OBJECT_MISSING`` otherwise."""

    def object_exists(self, bucket: str, key: str) -> bool: ...

    def read(self, bucket: str, key: str, *, max_bytes: int) -> bytes:
        """Server-side bounded read; ``STORAGE_OBJECT_TOO_LARGE`` past ``max_bytes``."""

    def upload(self, bucket: str, key: str, content: bytes, *, mime_type: str) -> ObjectStat:
        """Operator / worker upload of a NEW object; ``STORAGE_ALREADY_EXISTS`` if taken."""

    def delete(self, bucket: str, key: str) -> None:
        """Remove one object; ``STORAGE_OBJECT_MISSING`` if absent."""

    def list_objects(self, bucket: str, prefix: str = "", *, max_objects: int) -> list[ListedObject]:
        """Every object under ``prefix`` (recursive, bounded); for the storage cross-check."""


# ---------------------------------------------------------------------------
# verification
# ---------------------------------------------------------------------------


def read_verified(
    store: CanonicalObjectStore,
    bucket: str,
    key: str,
    *,
    expected_size: int,
    expected_sha256: str,
    max_bytes: int,
) -> tuple[bytes, ObjectStat]:
    """The stored bytes (bounded), proven to have the expected size and SHA-256.

    The provider's own metadata is never trusted for integrity: the bytes are
    hashed here.  Raises ``STORAGE_INTEGRITY_MISMATCH`` on any difference.
    """
    if expected_size <= 0 or expected_size > max_bytes:
        raise CanonicalStoreError(STORAGE_OBJECT_TOO_LARGE)
    stat = store.stat(bucket, key)
    if stat.size_bytes != expected_size:
        raise CanonicalStoreError(STORAGE_INTEGRITY_MISMATCH, "size")
    content = store.read(bucket, key, max_bytes=max_bytes)
    if len(content) != expected_size or hashlib.sha256(content).hexdigest() != expected_sha256:
        raise CanonicalStoreError(STORAGE_INTEGRITY_MISMATCH, "content")
    return content, stat


def verify_object(
    store: CanonicalObjectStore,
    bucket: str,
    key: str,
    *,
    expected_size: int,
    expected_sha256: str,
    max_bytes: int,
) -> VerifiedContent:
    """Prove a stored object's size and SHA-256 (see :func:`read_verified`)."""
    content, stat = read_verified(
        store, bucket, key, expected_size=expected_size, expected_sha256=expected_sha256, max_bytes=max_bytes
    )
    return VerifiedContent(len(content), expected_sha256, stat.mime_type)


__all__ = [
    "CanonicalObjectStore",
    "CanonicalStoreError",
    "ListedObject",
    "ObjectStat",
    "STORAGE_ALREADY_EXISTS",
    "STORAGE_AUTH_FAILURE",
    "STORAGE_CONFIG_MISSING",
    "STORAGE_INTEGRITY_MISMATCH",
    "STORAGE_INVALID_LOCATOR",
    "STORAGE_INVALID_RESPONSE",
    "STORAGE_OBJECT_MISSING",
    "STORAGE_OBJECT_TOO_LARGE",
    "STORAGE_PROVIDER_UNAVAILABLE",
    "SignedDownload",
    "SignedUpload",
    "VerifiedContent",
    "read_verified",
    "verify_object",
]
