"""Supabase Storage adapter for the canonical business-document store.

Documented Storage REST surface only (``<SUPABASE_URL>/storage/v1``):

    POST   /object/upload/sign/{bucket}/{key}   signed upload URL (x-upsert: false)
    POST   /object/sign/{bucket}/{key}          signed download URL
    HEAD   /object/authenticated/{bucket}/{key} metadata (size, content type)
    GET    /object/authenticated/{bucket}/{key} server-side bounded read
    POST   /object/{bucket}/{key}               operator/worker upload (x-upsert: false)
    DELETE /object/{bucket}/{key}               remove one object

CONFIGURATION IS LAZY
    Nothing reads ``SUPABASE_URL`` / ``SUPABASE_SECRET_KEY`` /
    ``SGAA_STORAGE_BUCKET`` at import or application start.  The configuration
    is loaded only when a store is built (``SupabaseObjectStore.from_environment``),
    and a missing variable is reported by NAME (``STORAGE_CONFIG_MISSING``).

SECRET HANDLING
    The server-side secret key is sent as ``apikey`` and duplicated as
    ``Authorization: Bearer`` (the gateway accepts both the legacy JWT
    ``service_role`` key and the opaque ``sb_secret_`` key this way).  It is
    excluded from every ``repr``; redirects are never followed (the
    ``Authorization`` header must not reach another host); provider bodies,
    URLs and signed tokens are never placed in an exception or a log line.
    The bucket is assumed PRIVATE: only signed or authenticated endpoints are
    used, never ``/object/public``.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, quote, urlsplit

from app.prod1_storage_ddl import STORAGE_BUCKET_MAX_LENGTH, STORAGE_KEY_MAX_LENGTH
from app.storage.object_store import (
    STORAGE_ALREADY_EXISTS,
    STORAGE_AUTH_FAILURE,
    STORAGE_CONFIG_MISSING,
    STORAGE_INVALID_LOCATOR,
    STORAGE_INVALID_RESPONSE,
    STORAGE_OBJECT_MISSING,
    STORAGE_OBJECT_TOO_LARGE,
    STORAGE_PROVIDER_UNAVAILABLE,
    CanonicalStoreError,
    ObjectStat,
    SignedDownload,
    SignedUpload,
)

SUPABASE_URL_ENV = "SUPABASE_URL"
SUPABASE_SECRET_KEY_ENV = "SUPABASE_SECRET_KEY"
STORAGE_BUCKET_ENV = "SGAA_STORAGE_BUCKET"

#: (connect, read) seconds -- fixed, never configurable per call.
HTTP_TIMEOUT = (5.0, 30.0)
SIGNED_DOWNLOAD_MAX_SECONDS = 3600
_READ_CHUNK = 64 * 1024

_BUCKET_RE = re.compile(rf"^[a-z0-9._-]{{1,{STORAGE_BUCKET_MAX_LENGTH}}}$")
_KEY_RE = re.compile(rf"^[A-Za-z0-9_.-][A-Za-z0-9/_.-]{{0,{STORAGE_KEY_MAX_LENGTH - 1}}}$")
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1"})


def check_locator(bucket: str, key: str) -> None:
    """The same alphabet as the v14 CHECK constraints; no traversal."""
    if not isinstance(bucket, str) or not _BUCKET_RE.fullmatch(bucket):
        raise CanonicalStoreError(STORAGE_INVALID_LOCATOR, "bucket")
    if not isinstance(key, str) or not _KEY_RE.fullmatch(key) or ".." in key:
        raise CanonicalStoreError(STORAGE_INVALID_LOCATOR, "key")


@dataclass(frozen=True)
class SupabaseStorageConfig:
    url: str
    bucket: str
    secret_key: str = field(repr=False)

    @classmethod
    def from_environment(cls, environ=None) -> "SupabaseStorageConfig":
        environ = os.environ if environ is None else environ
        values = {
            name: str(environ.get(name) or "").strip()
            for name in (SUPABASE_URL_ENV, SUPABASE_SECRET_KEY_ENV, STORAGE_BUCKET_ENV)
        }
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise CanonicalStoreError(STORAGE_CONFIG_MISSING, ",".join(missing))
        url = values[SUPABASE_URL_ENV].rstrip("/")
        parts = urlsplit(url)
        local = parts.scheme == "http" and parts.hostname in _LOCAL_HOSTS
        if (
            (parts.scheme != "https" and not local)
            or not parts.hostname
            or parts.username
            or parts.password
            or parts.path
            or parts.query
            or parts.fragment
        ):
            raise CanonicalStoreError(STORAGE_CONFIG_MISSING, SUPABASE_URL_ENV)
        bucket = values[STORAGE_BUCKET_ENV]
        if not _BUCKET_RE.fullmatch(bucket):
            raise CanonicalStoreError(STORAGE_CONFIG_MISSING, STORAGE_BUCKET_ENV)
        return cls(url=url, bucket=bucket, secret_key=values[SUPABASE_SECRET_KEY_ENV])


def _effective_status(response) -> int:
    """Storage reports some errors as HTTP 400 with the real code in the body."""
    status = int(response.status_code)
    if status == 400:
        try:
            payload = response.json()
        except ValueError:
            return status
        code = payload.get("statusCode") if isinstance(payload, dict) else None
        if isinstance(code, (str, int)) and str(code).isdigit():
            return int(code)
    return status


def _raise_for(response) -> None:
    status = int(response.status_code)
    if 200 <= status < 300:
        return
    effective = _effective_status(response)
    detail = f"http_{effective}"
    if effective in (401, 403):
        raise CanonicalStoreError(STORAGE_AUTH_FAILURE, detail)
    if effective == 404:
        raise CanonicalStoreError(STORAGE_OBJECT_MISSING, detail)
    if effective == 409:
        raise CanonicalStoreError(STORAGE_ALREADY_EXISTS, detail)
    if effective == 413:
        raise CanonicalStoreError(STORAGE_OBJECT_TOO_LARGE, detail)
    if effective == 429 or effective >= 500:
        raise CanonicalStoreError(STORAGE_PROVIDER_UNAVAILABLE, detail)
    raise CanonicalStoreError(STORAGE_INVALID_RESPONSE, detail)


def _json_object(response) -> dict:
    try:
        payload = response.json()
    except ValueError:
        raise CanonicalStoreError(STORAGE_INVALID_RESPONSE, "json") from None
    if not isinstance(payload, dict):
        raise CanonicalStoreError(STORAGE_INVALID_RESPONSE, "json")
    return payload


class SupabaseObjectStore:
    """:class:`app.storage.object_store.CanonicalObjectStore` over Supabase Storage."""

    backend = "supabase"

    def __init__(self, config: SupabaseStorageConfig, *, session=None) -> None:
        self._config = config
        self._session = session

    def __repr__(self) -> str:
        return f"SupabaseObjectStore(bucket={self._config.bucket!r})"

    @classmethod
    def from_environment(cls, environ=None, *, session=None) -> "SupabaseObjectStore":
        return cls(SupabaseStorageConfig.from_environment(environ), session=session)

    @property
    def bucket(self) -> str:
        return self._config.bucket

    # -- HTTP boundary ----------------------------------------------------

    @property
    def _http(self):
        if self._session is None:
            import requests

            self._session = requests.Session()
        return self._session

    def _endpoint(self, prefix: str, bucket: str, key: str | None = None) -> str:
        path = f"{self._config.url}/storage/v1/{prefix}/{quote(bucket, safe='')}"
        if key is not None:
            path += "/" + quote(key, safe="/")
        return path

    def _headers(self, extra=None) -> dict:
        headers = {
            "apikey": self._config.secret_key,
            "Authorization": f"Bearer {self._config.secret_key}",
        }
        headers.update(extra or {})
        return headers

    def _request(self, method: str, url: str, **kwargs):
        import requests

        try:
            response = self._http.request(
                method,
                url,
                headers=self._headers(kwargs.pop("headers", None)),
                timeout=HTTP_TIMEOUT,
                allow_redirects=False,
                **kwargs,
            )
        except requests.Timeout:
            raise CanonicalStoreError(STORAGE_PROVIDER_UNAVAILABLE, "timeout") from None
        except requests.RequestException:
            raise CanonicalStoreError(STORAGE_PROVIDER_UNAVAILABLE, "transport") from None
        return response

    def _signed_path(self, relative: str, expected_prefix: str) -> str:
        """``relative`` must be the provider's ``/object/...`` path for this endpoint."""
        if not isinstance(relative, str) or not relative.startswith(expected_prefix):
            raise CanonicalStoreError(STORAGE_INVALID_RESPONSE, "signed_path")
        parts = urlsplit(relative)
        if parts.scheme or parts.netloc:
            raise CanonicalStoreError(STORAGE_INVALID_RESPONSE, "signed_path")
        return f"{self._config.url}/storage/v1{relative}"

    # -- CanonicalObjectStore ---------------------------------------------

    def create_signed_upload(self, bucket: str, key: str) -> SignedUpload:
        check_locator(bucket, key)
        response = self._request(
            "POST",
            self._endpoint("object/upload/sign", bucket, key),
            headers={"x-upsert": "false"},
            json={},
        )
        _raise_for(response)
        payload = _json_object(response)
        prefix = "/object/upload/sign/" + quote(bucket, safe="") + "/" + quote(key, safe="/")
        url = self._signed_path(payload.get("url"), prefix + "?")
        tokens = parse_qs(urlsplit(url).query).get("token") or []
        token = payload.get("token") if isinstance(payload.get("token"), str) else None
        if len(tokens) != 1 or not tokens[0] or (token is not None and token != tokens[0]):
            raise CanonicalStoreError(STORAGE_INVALID_RESPONSE, "signed_token")
        return SignedUpload(bucket=bucket, key=key, url=url, token=tokens[0])

    def create_signed_download(
        self, bucket: str, key: str, *, expires_in: int, download_name: str | None = None
    ) -> SignedDownload:
        check_locator(bucket, key)
        if (
            isinstance(expires_in, bool)
            or not isinstance(expires_in, int)
            or not 1 <= expires_in <= SIGNED_DOWNLOAD_MAX_SECONDS
        ):
            raise ValueError("expires_in must be 1..3600 seconds")
        response = self._request(
            "POST", self._endpoint("object/sign", bucket, key), json={"expiresIn": expires_in}
        )
        _raise_for(response)
        payload = _json_object(response)
        prefix = "/object/sign/" + quote(bucket, safe="") + "/" + quote(key, safe="/")
        url = self._signed_path(payload.get("signedURL"), prefix + "?")
        if not parse_qs(urlsplit(url).query).get("token"):
            raise CanonicalStoreError(STORAGE_INVALID_RESPONSE, "signed_token")
        if download_name:
            url += "&download=" + quote(str(download_name), safe="")
        return SignedDownload(bucket=bucket, key=key, expires_in=expires_in, url=url)

    def stat(self, bucket: str, key: str) -> ObjectStat:
        check_locator(bucket, key)
        response = self._request("HEAD", self._endpoint("object/authenticated", bucket, key))
        if int(response.status_code) == 400:
            # HEAD carries no body: Storage's "400 for missing" cannot be refined.
            raise CanonicalStoreError(STORAGE_OBJECT_MISSING, "http_400")
        _raise_for(response)
        length = response.headers.get("Content-Length")
        if length is None or not str(length).isdigit():
            raise CanonicalStoreError(STORAGE_INVALID_RESPONSE, "content_length")
        mime = response.headers.get("Content-Type")
        mime = str(mime).split(";", 1)[0].strip().lower() if mime else None
        return ObjectStat(bucket=bucket, key=key, size_bytes=int(length), mime_type=mime or None)

    def object_exists(self, bucket: str, key: str) -> bool:
        try:
            self.stat(bucket, key)
        except CanonicalStoreError as exc:
            if exc.code == STORAGE_OBJECT_MISSING:
                return False
            raise
        return True

    def read(self, bucket: str, key: str, *, max_bytes: int) -> bytes:
        check_locator(bucket, key)
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
            raise ValueError("max_bytes must be a positive integer")
        response = self._request(
            "GET", self._endpoint("object/authenticated", bucket, key), stream=True
        )
        try:
            _raise_for(response)
            declared = response.headers.get("Content-Length")
            if declared is not None and str(declared).isdigit() and int(declared) > max_bytes:
                raise CanonicalStoreError(STORAGE_OBJECT_TOO_LARGE)
            chunks = []
            total = 0
            try:
                for chunk in response.iter_content(chunk_size=_READ_CHUNK):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > max_bytes:
                        raise CanonicalStoreError(STORAGE_OBJECT_TOO_LARGE)
                    chunks.append(chunk)
            except CanonicalStoreError:
                raise
            except Exception:
                raise CanonicalStoreError(STORAGE_PROVIDER_UNAVAILABLE, "stream") from None
            return b"".join(chunks)
        finally:
            response.close()

    def upload(self, bucket: str, key: str, content: bytes, *, mime_type: str) -> ObjectStat:
        check_locator(bucket, key)
        if not isinstance(content, (bytes, bytearray)) or not content:
            raise ValueError("content must be non-empty bytes")
        response = self._request(
            "POST",
            self._endpoint("object", bucket, key),
            headers={"Content-Type": str(mime_type), "x-upsert": "false"},
            data=bytes(content),
        )
        _raise_for(response)
        payload = _json_object(response)
        stored = payload.get("Key")
        if stored is not None and stored != f"{bucket}/{key}":
            raise CanonicalStoreError(STORAGE_INVALID_RESPONSE, "key")
        return ObjectStat(bucket=bucket, key=key, size_bytes=len(content), mime_type=str(mime_type))

    def delete(self, bucket: str, key: str) -> None:
        check_locator(bucket, key)
        response = self._request("DELETE", self._endpoint("object", bucket, key))
        _raise_for(response)


__all__ = [
    "HTTP_TIMEOUT",
    "STORAGE_BUCKET_ENV",
    "SUPABASE_SECRET_KEY_ENV",
    "SUPABASE_URL_ENV",
    "SupabaseObjectStore",
    "SupabaseStorageConfig",
    "check_locator",
]
