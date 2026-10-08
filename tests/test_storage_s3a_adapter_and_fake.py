# coding: utf-8
"""STORAGE S3-A RED: Supabase adapter key header and the stricter canonical fake.

A. ``sb_secret_...`` keys are backend-only API keys: every server-side Storage
   call authenticates with ``apikey: <secret>`` and sends NO
   ``Authorization: Bearer <secret>``.  The published S2 adapter duplicates the
   secret into ``Authorization`` -- expected RED.  Secret hygiene (repr,
   sanitized errors) is a GREEN control.
B. The S3 application tests need a fake whose observable semantics match the
   service: a signed upload capability is reusable until it expires (no
   overwrite: upsert is false), can be expired by the test clock, and supports
   a TUS-shaped completion bound to the capability's bucket / object name.
   Declared Content-Type vs actual bytes, stat vs read, bounded reads, missing
   objects and injected provider errors are GREEN controls of the S2 fake.
"""

from __future__ import annotations

import pytest

from app.storage.object_store import (
    STORAGE_ALREADY_EXISTS,
    STORAGE_OBJECT_MISSING,
    STORAGE_OBJECT_TOO_LARGE,
    STORAGE_PROVIDER_UNAVAILABLE,
    CanonicalStoreError,
)
from app.storage.supabase_store import (
    SupabaseObjectStore,
    SupabaseStorageConfig,
    configured_publishable_key,
    resumable_upload_endpoint,
)
from tests.canonical_store_fake import InMemoryObjectStore
from tests.storage_s3a_support import (
    BUCKET, PDF, PNG, STORAGE_ORIGIN, SUPABASE_URL, TEST_PUBLISHABLE_KEY, TEST_SECRET_KEY,
)

KEY = "comprovantes/2026/01/" + "f" * 32


class _Response:
    def __init__(self, status=200, *, json=None, headers=None, body=b""):
        self.status_code = status
        self._json = json
        self.headers = headers or {}
        self._body = body

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json

    def iter_content(self, chunk_size=1):
        for start in range(0, len(self._body), chunk_size):
            yield self._body[start:start + chunk_size]

    def close(self):
        pass


class _Session:
    """Records every outbound request; answers like the Storage REST surface."""

    def __init__(self, status=200):
        self.requests = []
        self.status = status

    def request(self, method, url, headers=None, **kwargs):
        self.requests.append((method, url, dict(headers or {})))
        if self.status != 200:
            return _Response(self.status, json={"statusCode": str(self.status), "error": TEST_SECRET_KEY})
        if method == "POST" and "/object/upload/sign/" in url:
            return _Response(json={"url": f"/object/upload/sign/{BUCKET}/{KEY}?token=up-token", "token": "up-token"})
        if method == "POST" and "/object/sign/" in url:
            return _Response(json={"signedURL": f"/object/sign/{BUCKET}/{KEY}?token=dl-token"})
        if method == "HEAD":
            return _Response(headers={"Content-Length": str(len(PDF)), "Content-Type": "application/pdf"})
        if method == "GET":
            return _Response(headers={"Content-Length": str(len(PDF))}, body=PDF)
        if method == "POST":
            return _Response(json={"Key": f"{BUCKET}/{KEY}"})
        return _Response(json={})


def _store(session):
    config = SupabaseStorageConfig(url=SUPABASE_URL, bucket=BUCKET, secret_key=TEST_SECRET_KEY)
    return SupabaseObjectStore(config, session=session)


def _every_call(store):
    store.create_signed_upload(BUCKET, KEY)
    store.create_signed_download(BUCKET, KEY, expires_in=60)
    store.stat(BUCKET, KEY)
    store.read(BUCKET, KEY, max_bytes=len(PDF))
    store.upload(BUCKET, KEY, PDF, mime_type="application/pdf")
    store.delete(BUCKET, KEY)


# --- A. sb_secret_ key header -------------------------------------------------------


def test_sb_secret_key_is_sent_only_as_apikey_never_as_bearer():
    session = _Session()
    _every_call(_store(session))
    assert len(session.requests) == 6
    for method, url, headers in session.requests:
        lowered = {name.lower(): value for name, value in headers.items()}
        assert lowered.get("apikey") == TEST_SECRET_KEY, (method, url)
        assert "authorization" not in lowered, (method, url, "sb_secret_ must not be a Bearer token")
        assert TEST_SECRET_KEY not in url


def test_secret_never_reaches_repr_or_a_sanitized_error():
    """GREEN control (S2 hygiene) -- must survive the header change."""
    store = _store(_Session(status=401))
    assert TEST_SECRET_KEY not in repr(store)
    with pytest.raises(CanonicalStoreError) as caught:
        store.stat(BUCKET, KEY)
    assert TEST_SECRET_KEY not in str(caught.value)
    assert TEST_SECRET_KEY not in repr(caught.value)


# --- A2. live-proven signed TUS browser contract -------------------------------------


def test_resumable_endpoint_is_the_direct_host_signed_session_path():
    endpoint = resumable_upload_endpoint(SUPABASE_URL)
    assert endpoint == f"{STORAGE_ORIGIN}/storage/v1/upload/resumable/sign"
    assert endpoint.endswith("/storage/v1/upload/resumable/sign")


def test_publishable_key_setting_accepts_only_a_modern_publishable_key():
    good = {"SUPABASE_PUBLISHABLE_KEY": f" {TEST_PUBLISHABLE_KEY} ", "SUPABASE_SECRET_KEY": TEST_SECRET_KEY}
    assert configured_publishable_key(good) == TEST_PUBLISHABLE_KEY
    refused = (
        {},
        {"SUPABASE_PUBLISHABLE_KEY": ""},
        {"SUPABASE_PUBLISHABLE_KEY": TEST_SECRET_KEY},
        {"SUPABASE_PUBLISHABLE_KEY": "sb_secret_" + "a" * 30},
        {"SUPABASE_PUBLISHABLE_KEY": "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.c2ln"},
        {"SUPABASE_PUBLISHABLE_KEY": "sb_publishable_"},
        {"SUPABASE_PUBLISHABLE_KEY": "sb_publishable_abc def ghi"},
        # the configured secret is never substituted, even under a publishable-looking name
        {"SUPABASE_PUBLISHABLE_KEY": TEST_PUBLISHABLE_KEY, "SUPABASE_SECRET_KEY": TEST_PUBLISHABLE_KEY},
    )
    for environ in refused:
        with pytest.raises(CanonicalStoreError) as caught:
            configured_publishable_key(environ)
        assert caught.value.code == "STORAGE_CONFIG_MISSING"
        assert caught.value.detail == "SUPABASE_PUBLISHABLE_KEY"
        assert TEST_SECRET_KEY not in str(caught.value) and "sb_secret_" not in repr(caught.value)


def test_backend_adapter_keeps_the_secret_apikey_contract_beside_a_publishable_setting():
    """The publishable key is browser-only: server calls still send the secret as apikey, no Bearer."""
    session = _Session()
    store = SupabaseObjectStore.from_environment({
        "SUPABASE_URL": SUPABASE_URL, "SUPABASE_SECRET_KEY": TEST_SECRET_KEY,
        "SUPABASE_PUBLISHABLE_KEY": TEST_PUBLISHABLE_KEY, "SGAA_STORAGE_BUCKET": BUCKET,
    }, session=session)
    _every_call(store)
    for method, url, headers in session.requests:
        lowered = {name.lower(): value for name, value in headers.items()}
        assert lowered.get("apikey") == TEST_SECRET_KEY, (method, url)
        assert "authorization" not in lowered and TEST_PUBLISHABLE_KEY not in str(headers)


# --- B. stricter canonical fake ------------------------------------------------------


def test_fake_signed_capability_is_reusable_until_expiry_but_never_overwrites():
    store = InMemoryObjectStore()
    upload = store.create_signed_upload(BUCKET, KEY)
    store.complete_signed_upload(upload.token, PDF, mime_type="application/pdf")
    with pytest.raises(CanonicalStoreError) as caught:
        store.complete_signed_upload(upload.token, PNG, mime_type="image/png")
    # The service validates the token (still live) and then refuses the taken key.
    assert caught.value.code == STORAGE_ALREADY_EXISTS
    assert store.read(BUCKET, KEY, max_bytes=len(PDF)) == PDF


def test_fake_capability_expires_on_the_test_clock():
    store = InMemoryObjectStore()
    expire = getattr(store, "expire_signed_uploads", None)
    assert callable(expire), "the S3 fake needs a deterministic capability-expiry hook"
    upload = store.create_signed_upload(BUCKET, KEY)
    expire()
    with pytest.raises(CanonicalStoreError):
        store.complete_signed_upload(upload.token, PDF, mime_type="application/pdf")
    assert not store.object_exists(BUCKET, KEY)


def test_fake_tus_completion_is_bound_to_the_capability_locator():
    store = InMemoryObjectStore()
    complete = getattr(store, "complete_resumable_upload", None)
    assert callable(complete), "the S3 fake needs a TUS-shaped completion"
    upload = store.create_signed_upload(BUCKET, KEY)
    with pytest.raises(CanonicalStoreError):
        complete(token=upload.token, bucket=BUCKET, object_name=KEY + "x", content=PDF,
                 content_type="application/pdf")
    with pytest.raises(CanonicalStoreError):
        complete(token=upload.token, bucket="other-bucket", object_name=KEY, content=PDF,
                 content_type="application/pdf")
    assert not store.object_exists(BUCKET, KEY)
    complete(token=upload.token, bucket=BUCKET, object_name=KEY, content=PDF, content_type="application/pdf")
    assert store.read(BUCKET, KEY, max_bytes=len(PDF)) == PDF


def test_fake_remint_for_an_absent_key_gives_independent_live_capabilities():
    """GREEN control: a re-minted capability targets the same immutable key."""
    store = InMemoryObjectStore()
    first = store.create_signed_upload(BUCKET, KEY)
    second = store.create_signed_upload(BUCKET, KEY)
    assert first.token != second.token
    store.complete_signed_upload(second.token, PDF, mime_type="application/pdf")
    with pytest.raises(CanonicalStoreError) as caught:
        store.complete_signed_upload(first.token, PNG, mime_type="image/png")
    assert caught.value.code == STORAGE_ALREADY_EXISTS


def test_fake_declared_content_type_is_independent_of_the_bytes():
    """GREEN control: Storage metadata is the CLIENT-declared type, not a sniff."""
    store = InMemoryObjectStore()
    upload = store.create_signed_upload(BUCKET, KEY)
    store.complete_signed_upload(upload.token, PNG, mime_type="application/pdf")
    assert store.stat(BUCKET, KEY).mime_type == "application/pdf"
    assert store.read(BUCKET, KEY, max_bytes=len(PNG)) == PNG


def test_fake_bounded_read_missing_object_and_injected_provider_error():
    """GREEN controls the S3 verification tests rely on."""
    store = InMemoryObjectStore()
    with pytest.raises(CanonicalStoreError) as missing:
        store.stat(BUCKET, KEY)
    assert missing.value.code == STORAGE_OBJECT_MISSING
    upload = store.create_signed_upload(BUCKET, KEY)
    store.complete_signed_upload(upload.token, PDF, mime_type="application/pdf")
    with pytest.raises(CanonicalStoreError) as large:
        store.read(BUCKET, KEY, max_bytes=len(PDF) - 1)
    assert large.value.code == STORAGE_OBJECT_TOO_LARGE
    store.fail_next(STORAGE_PROVIDER_UNAVAILABLE)
    with pytest.raises(CanonicalStoreError) as outage:
        store.stat(BUCKET, KEY)
    assert outage.value.code == STORAGE_PROVIDER_UNAVAILABLE and outage.value.retryable
