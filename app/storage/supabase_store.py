"""Supabase Storage adapter for the canonical business-document store.

Documented Storage REST surface only (``<SUPABASE_URL>/storage/v1``):

    POST   /object/upload/sign/{bucket}/{key}   signed upload URL (x-upsert: false)
    POST   /object/sign/{bucket}/{key}          signed download URL
    HEAD   /object/authenticated/{bucket}/{key} metadata (size, content type)
    GET    /object/authenticated/{bucket}/{key} server-side bounded read
    POST   /object/{bucket}/{key}               operator/worker upload (x-upsert: false)
    DELETE /object/{bucket}/{key}               remove one object
    POST   /object/list/{bucket}                one folder level of a listing (paged)

CONFIGURATION IS LAZY
    Nothing reads ``SUPABASE_URL`` / ``SUPABASE_SECRET_KEY`` /
    ``SGAA_STORAGE_BUCKET`` at import or application start.  The configuration
    is loaded only when a store is built (``SupabaseObjectStore.from_environment``),
    and a missing variable is reported by NAME (``STORAGE_CONFIG_MISSING``).

SECRET HANDLING
    An opaque ``sb_secret_...`` key is a backend-only API key: it is sent ONLY
    as ``apikey`` and never as ``Authorization: Bearer`` (it is not a JWT).  A
    legacy JWT ``service_role`` key keeps the published compatibility form
    (``apikey`` duplicated as ``Authorization: Bearer``).  The secret is
    excluded from every ``repr``; redirects are never followed (no credential
    header may reach another host); provider bodies, URLs and signed tokens
    are never placed in an exception or a log line.

BROWSER CAPABILITY (STORAGE S3-A)
    The browser uploads with signed resumable (TUS) uploads straight to the
    project's direct storage hostname: the session is created at
    ``https://<project-ref>.storage.supabase.co/storage/v1/upload/resumable/sign``
    (the provider's Location then names ``/upload/resumable/<upload-id>``),
    authenticated by the signed upload token in ``x-signature`` plus the
    project's browser-safe publishable key (``sb_publishable_...``) in
    ``apikey`` -- never an ``Authorization`` header -- in 6 MiB chunks
    (live-proven on a non-production project).  ``resumable_upload_endpoint``
    / ``storage_browser_origin`` derive that public location from
    ``SUPABASE_URL`` and ``configured_publishable_key`` reads
    ``SUPABASE_PUBLISHABLE_KEY``, refusing anything that is not a publishable
    key; nothing here hands the secret key to a browser.
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
    ListedObject,
    ObjectStat,
    SignedDownload,
    SignedUpload,
)

SUPABASE_URL_ENV = "SUPABASE_URL"
SUPABASE_SECRET_KEY_ENV = "SUPABASE_SECRET_KEY"
SUPABASE_PUBLISHABLE_KEY_ENV = "SUPABASE_PUBLISHABLE_KEY"
STORAGE_BUCKET_ENV = "SGAA_STORAGE_BUCKET"

#: (connect, read) seconds -- fixed, never configurable per call.
HTTP_TIMEOUT = (5.0, 30.0)
SIGNED_DOWNLOAD_MAX_SECONDS = 3600
SECRET_KEY_PREFIX = "sb_secret_"
PUBLISHABLE_KEY_PREFIX = "sb_publishable_"
#: Supabase's documented resumable chunk size ("must be set to 6MB").
TUS_CHUNK_BYTES = 6 * 1024 * 1024
#: Signed (x-signature) resumable session creation; live-proven on the direct host.
RESUMABLE_PATH = "/storage/v1/upload/resumable/sign"
_HOSTED_SUFFIX = ".supabase.co"
_READ_CHUNK = 64 * 1024
#: One listing page; the service lists one folder level per request.
LIST_PAGE_SIZE = 100
LIST_MAX_DEPTH = 8
LIST_MAX_REQUESTS = 20_000

_BUCKET_RE = re.compile(rf"^[a-z0-9._-]{{1,{STORAGE_BUCKET_MAX_LENGTH}}}$")
_KEY_RE = re.compile(rf"^[A-Za-z0-9_.-][A-Za-z0-9/_.-]{{0,{STORAGE_KEY_MAX_LENGTH - 1}}}$")
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1"})


def check_locator(bucket: str, key: str) -> None:
    """The same alphabet as the v14 CHECK constraints; no traversal."""
    if not isinstance(bucket, str) or not _BUCKET_RE.fullmatch(bucket):
        raise CanonicalStoreError(STORAGE_INVALID_LOCATOR, "bucket")
    if not isinstance(key, str) or not _KEY_RE.fullmatch(key) or ".." in key:
        raise CanonicalStoreError(STORAGE_INVALID_LOCATOR, "key")


def _validated_project_url(value: str) -> str:
    """``SUPABASE_URL`` as an origin (https, or http on localhost); else refused by NAME."""
    url = str(value or "").strip().rstrip("/")
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
    return url


def storage_browser_origin(supabase_url: str) -> str:
    """The origin the browser uploads to: the hosted project's DIRECT storage host.

    ``https://<ref>.supabase.co`` -> ``https://<ref>.storage.supabase.co``; a
    local / self-hosted URL is its own storage origin.
    """
    url = _validated_project_url(supabase_url)
    parts = urlsplit(url)
    host = parts.hostname or ""
    if host.endswith(_HOSTED_SUFFIX):
        ref = host[: -len(_HOSTED_SUFFIX)]
        if ref and "." not in ref and parts.port is None:
            return f"https://{ref}.storage.supabase.co"
    return url


def resumable_upload_endpoint(supabase_url: str) -> str:
    """The direct signed-TUS session-creation endpoint (``.../upload/resumable/sign``)."""
    return storage_browser_origin(supabase_url) + RESUMABLE_PATH


def configured_project_url(environ=None) -> str:
    environ = os.environ if environ is None else environ
    value = str(environ.get(SUPABASE_URL_ENV) or "").strip()
    if not value:
        raise CanonicalStoreError(STORAGE_CONFIG_MISSING, SUPABASE_URL_ENV)
    return _validated_project_url(value)


def configured_bucket(environ=None) -> str:
    environ = os.environ if environ is None else environ
    bucket = str(environ.get(STORAGE_BUCKET_ENV) or "").strip()
    if not _BUCKET_RE.fullmatch(bucket):
        raise CanonicalStoreError(STORAGE_CONFIG_MISSING, STORAGE_BUCKET_ENV)
    return bucket


_PUBLISHABLE_KEY_RE = re.compile(rf"^{PUBLISHABLE_KEY_PREFIX}[A-Za-z0-9_-]{{8,200}}$")


def configured_publishable_key(environ=None) -> str:
    """``SUPABASE_PUBLISHABLE_KEY``: the browser-safe key sent as ``apikey`` with signed TUS.

    Only a modern ``sb_publishable_...`` key is accepted.  A secret key, a
    legacy JWT (anon / service_role) or the configured secret itself is refused
    by NAME and never substituted: a backend credential must not reach a browser.
    """
    environ = os.environ if environ is None else environ
    value = str(environ.get(SUPABASE_PUBLISHABLE_KEY_ENV) or "").strip()
    secret = str(environ.get(SUPABASE_SECRET_KEY_ENV) or "").strip()
    if (
        not _PUBLISHABLE_KEY_RE.fullmatch(value)
        or value.startswith(SECRET_KEY_PREFIX)
        or value.count(".") >= 2
        or (secret and value == secret)
    ):
        raise CanonicalStoreError(STORAGE_CONFIG_MISSING, SUPABASE_PUBLISHABLE_KEY_ENV)
    return value


def configured_storage_origin(environ=None) -> str | None:
    """The browser storage origin when ``SUPABASE_URL`` is configured and valid, else None."""
    try:
        return storage_browser_origin(configured_project_url(environ))
    except CanonicalStoreError:
        return None


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
        url = _validated_project_url(values[SUPABASE_URL_ENV])
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
        secret = self._config.secret_key
        headers = {"apikey": secret}
        if not secret.startswith(SECRET_KEY_PREFIX):
            # Legacy JWT service_role key only; an sb_secret_ key is never a Bearer token.
            headers["Authorization"] = f"Bearer {secret}"
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

    def list_objects(self, bucket: str, prefix: str = "", *, max_objects: int) -> list[ListedObject]:
        """Every object under ``prefix``, walking folders depth-first; bounded.

        The service lists ONE folder level per request: an entry without an
        ``id`` is a folder.  Keys are returned as stored, never validated
        against the application alphabet -- a foreign object is exactly what
        the cross-check must see.  A folder is read until an EMPTY page, so
        a service that returns shorter pages than asked never truncates it.
        Exceeding ``max_objects``, ``LIST_MAX_DEPTH`` or ``LIST_MAX_REQUESTS``
        raises ``STORAGE_INVALID_RESPONSE`` instead of returning a silently
        truncated listing.
        """
        if not isinstance(bucket, str) or not _BUCKET_RE.fullmatch(bucket):
            raise CanonicalStoreError(STORAGE_INVALID_LOCATOR, "bucket")
        if isinstance(max_objects, bool) or not isinstance(max_objects, int) or max_objects <= 0:
            raise ValueError("max_objects must be a positive integer")
        found: list[ListedObject] = []
        folders = [(str(prefix or "").strip("/"), 0)]
        url = f"{self._config.url}/storage/v1/object/list/{quote(bucket, safe='')}"
        requests_made = 0
        while folders:
            folder, depth = folders.pop()
            if depth > LIST_MAX_DEPTH:
                raise CanonicalStoreError(STORAGE_INVALID_RESPONSE, "listing_depth")
            offset = 0
            while True:
                requests_made += 1
                if requests_made > LIST_MAX_REQUESTS:
                    raise CanonicalStoreError(STORAGE_INVALID_RESPONSE, "listing_requests")
                response = self._request("POST", url, json={
                    "prefix": folder, "limit": LIST_PAGE_SIZE, "offset": offset,
                    "sortBy": {"column": "name", "order": "asc"},
                })
                _raise_for(response)
                try:
                    entries = response.json()
                except ValueError:
                    raise CanonicalStoreError(STORAGE_INVALID_RESPONSE, "json") from None
                if not isinstance(entries, list):
                    raise CanonicalStoreError(STORAGE_INVALID_RESPONSE, "json")
                for entry in entries:
                    name = entry.get("name") if isinstance(entry, dict) else None
                    if not isinstance(name, str) or not name or "/" in name:
                        raise CanonicalStoreError(STORAGE_INVALID_RESPONSE, "listing_entry")
                    key = f"{folder}/{name}" if folder else name
                    if entry.get("id") is None:
                        folders.append((key, depth + 1))
                        continue
                    metadata = entry.get("metadata")
                    size = metadata.get("size") if isinstance(metadata, dict) else None
                    valid = isinstance(size, int) and not isinstance(size, bool)
                    found.append(ListedObject(key, size if valid else None))
                    if len(found) > max_objects:
                        raise CanonicalStoreError(STORAGE_INVALID_RESPONSE, "listing_bound")
                if not entries:
                    break
                offset += len(entries)
        return found


__all__ = [
    "HTTP_TIMEOUT",
    "LIST_PAGE_SIZE",
    "PUBLISHABLE_KEY_PREFIX",
    "RESUMABLE_PATH",
    "SECRET_KEY_PREFIX",
    "SUPABASE_PUBLISHABLE_KEY_ENV",
    "TUS_CHUNK_BYTES",
    "configured_bucket",
    "configured_project_url",
    "configured_publishable_key",
    "configured_storage_origin",
    "resumable_upload_endpoint",
    "storage_browser_origin",
    "STORAGE_BUCKET_ENV",
    "SUPABASE_SECRET_KEY_ENV",
    "SUPABASE_URL_ENV",
    "SupabaseObjectStore",
    "SupabaseStorageConfig",
    "check_locator",
]
