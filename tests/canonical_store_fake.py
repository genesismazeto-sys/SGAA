"""Deterministic in-memory canonical object store for tests (never production).

Implements ``app.storage.object_store.CanonicalObjectStore`` with the semantics
the S2/S3 flows rely on:

* immutable keys -- a second upload (direct or signed) to a taken key is
  ``STORAGE_ALREADY_EXISTS``; nothing is ever overwritten (upsert is false);
* signed uploads -- ``create_signed_upload`` issues a token bound to exactly
  one (bucket, key) and, like the service, REUSABLE until it expires (a reuse
  against a taken key is ``STORAGE_ALREADY_EXISTS``, never an overwrite);
  ``expire_signed_uploads`` plays the clock running past every capability;
  ``complete_signed_upload`` plays the browser PUT and
  ``complete_resumable_upload`` the browser's signed TUS upload (the token,
  sent as ``x-signature``, must match the TUS ``bucketName`` / ``objectName``
  metadata; chunking is not observable by the application and not modelled);
* bounded reads, metadata, deletion, missing objects;
* failure injection -- ``fail_next(code)`` makes the next call raise that
  sanitized error (provider outage, auth failure, invalid response ...).
"""

from __future__ import annotations

import secrets

from app.storage.object_store import (
    STORAGE_ALREADY_EXISTS,
    STORAGE_AUTH_FAILURE,
    STORAGE_INVALID_LOCATOR,
    STORAGE_OBJECT_MISSING,
    STORAGE_OBJECT_TOO_LARGE,
    CanonicalStoreError,
    ObjectStat,
    SignedDownload,
    SignedUpload,
)
from app.storage.supabase_store import check_locator


class InMemoryObjectStore:
    backend = "supabase"

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], tuple[bytes, str]] = {}
        self.pending_uploads: dict[str, tuple[str, str]] = {}
        self.calls: list[str] = []
        self._failures: list[str] = []

    def fail_next(self, code: str) -> None:
        self._failures.append(code)

    def _enter(self, name: str) -> None:
        self.calls.append(name)
        if self._failures:
            raise CanonicalStoreError(self._failures.pop(0))

    def create_signed_upload(self, bucket: str, key: str) -> SignedUpload:
        self._enter("create_signed_upload")
        check_locator(bucket, key)
        if (bucket, key) in self.objects:
            raise CanonicalStoreError(STORAGE_ALREADY_EXISTS)
        token = secrets.token_urlsafe(16)
        self.pending_uploads[token] = (bucket, key)
        return SignedUpload(bucket, key, url=f"memory://upload/{bucket}/{key}?token={token}", token=token)

    def complete_signed_upload(self, token: str, content: bytes, *, mime_type: str) -> None:
        """The browser's PUT to a signed URL: the bound key only, no overwrite."""
        locator = self.pending_uploads.get(token)
        if locator is None:
            raise CanonicalStoreError(STORAGE_INVALID_LOCATOR, "token")
        if locator in self.objects:
            raise CanonicalStoreError(STORAGE_ALREADY_EXISTS)
        self.objects[locator] = (bytes(content), mime_type)

    def complete_resumable_upload(
        self, *, token: str, bucket: str, object_name: str, content: bytes, content_type: str
    ) -> None:
        """The browser's signed TUS upload: ``x-signature`` must bind the metadata locator."""
        locator = self.pending_uploads.get(token)
        if locator is None:
            raise CanonicalStoreError(STORAGE_INVALID_LOCATOR, "token")
        if locator != (bucket, object_name):
            raise CanonicalStoreError(STORAGE_AUTH_FAILURE, "signature")
        self.complete_signed_upload(token, content, mime_type=content_type)

    def expire_signed_uploads(self) -> None:
        """Every outstanding upload capability passes its expiry."""
        self.pending_uploads.clear()

    def create_signed_download(self, bucket, key, *, expires_in, download_name=None) -> SignedDownload:
        self._enter("create_signed_download")
        check_locator(bucket, key)
        if (bucket, key) not in self.objects:
            raise CanonicalStoreError(STORAGE_OBJECT_MISSING)
        return SignedDownload(bucket, key, expires_in, url=f"memory://download/{bucket}/{key}")

    def stat(self, bucket: str, key: str) -> ObjectStat:
        self._enter("stat")
        check_locator(bucket, key)
        try:
            content, mime = self.objects[(bucket, key)]
        except KeyError:
            raise CanonicalStoreError(STORAGE_OBJECT_MISSING) from None
        return ObjectStat(bucket, key, len(content), mime)

    def object_exists(self, bucket: str, key: str) -> bool:
        self._enter("object_exists")
        check_locator(bucket, key)
        return (bucket, key) in self.objects

    def read(self, bucket: str, key: str, *, max_bytes: int) -> bytes:
        self._enter("read")
        check_locator(bucket, key)
        try:
            content, _mime = self.objects[(bucket, key)]
        except KeyError:
            raise CanonicalStoreError(STORAGE_OBJECT_MISSING) from None
        if len(content) > max_bytes:
            raise CanonicalStoreError(STORAGE_OBJECT_TOO_LARGE)
        return content

    def upload(self, bucket: str, key: str, content: bytes, *, mime_type: str) -> ObjectStat:
        self._enter("upload")
        check_locator(bucket, key)
        if (bucket, key) in self.objects:
            raise CanonicalStoreError(STORAGE_ALREADY_EXISTS)
        self.objects[(bucket, key)] = (bytes(content), mime_type)
        return ObjectStat(bucket, key, len(content), mime_type)

    def delete(self, bucket: str, key: str) -> None:
        self._enter("delete")
        check_locator(bucket, key)
        if self.objects.pop((bucket, key), None) is None:
            raise CanonicalStoreError(STORAGE_OBJECT_MISSING)


__all__ = ["InMemoryObjectStore"]
