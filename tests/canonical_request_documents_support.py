"""Test-only helpers for STORAGE S3-A canonical request documents.

Request documents no longer travel through the application: the browser
obtains a capability (``POST /storage/upload-intents``), uploads straight to
canonical storage and has the server verify the object
(``POST /storage/upload-intents/<id>/finalize``); the request form then posts
only ``comprovantes_submission_id`` and the verified
``comprovantes_intent_ids``.  These helpers play that protocol against the
deterministic in-memory canonical store (never a live provider), so suites
that need stored request documents create them exactly as production does.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import secrets

from tests.canonical_store_fake import InMemoryObjectStore

CANONICAL_STORE_EXTENSION = "canonical_object_store"
SUBMISSION_FIELD = "comprovantes_submission_id"
INTENT_IDS_FIELD = "comprovantes_intent_ids"
ISSUE_URL = "/storage/upload-intents"
TEST_SUPABASE_URL = "https://abcdefghijklmnopqrst.supabase.co"
TEST_BUCKET = "sgaa-documentos"
_ENV = {
    "SUPABASE_URL": TEST_SUPABASE_URL,
    "SUPABASE_SECRET_KEY": "sb_secret_TESTONLY0000000000000000000000",
    "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_TESTONLY000000000000000000",
    "SGAA_STORAGE_BUCKET": TEST_BUCKET,
}
_MIME = {"pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}
_SUBMISSION_RE = re.compile(rb'name="comprovantes_submission_id" value="([0-9a-f]{32})"')


@contextlib.contextmanager
def canonical_documents(app):
    """Inject the in-memory canonical store and the (synthetic) storage configuration."""
    store = InMemoryObjectStore()
    original_store = app.extensions.get(CANONICAL_STORE_EXTENSION)
    original_env = {name: os.environ.get(name) for name in _ENV}
    app.extensions[CANONICAL_STORE_EXTENSION] = store
    os.environ.update(_ENV)
    try:
        yield store
    finally:
        if original_store is None:
            app.extensions.pop(CANONICAL_STORE_EXTENSION, None)
        else:
            app.extensions[CANONICAL_STORE_EXTENSION] = original_store
        for name, value in original_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def form_submission(client, path: str) -> str:
    """The server-issued submission id rendered by a request form."""
    page = client.get(path)
    match = _SUBMISSION_RE.search(page.data)
    assert match, f"{path} renders no comprovantes_submission_id"
    return match.group(1).decode()


def declared_mime(filename: str) -> str:
    return _MIME.get(filename.rsplit(".", 1)[-1].lower() if "." in filename else "", "application/pdf")


def issue(client, submission_id: str, content: bytes, filename: str, *, mime=None, slot=None, **extra):
    return client.post(ISSUE_URL, json={
        "purpose": "comprovante", "submission_id": submission_id,
        "upload_slot_id": slot or secrets.token_hex(16), "filename": filename,
        "mime_type": mime or declared_mime(filename), "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(), **extra,
    })


def upload(client, store, submission_id: str, content: bytes, filename: str, *, mime=None,
           stored_type=None, finalize=True, **extra):
    """Issue, upload straight to the fake store and (by default) finalize; returns the response pair."""
    issued = issue(client, submission_id, content, filename, mime=mime, **extra)
    if issued.status_code != 201:
        return issued, None
    capability = issued.get_json()
    store.complete_resumable_upload(
        token=capability["upload_token"], bucket=capability["bucket"],
        object_name=capability["object_name"], content=content,
        content_type=stored_type or mime or declared_mime(filename),
    )
    finalized = client.post(f"{ISSUE_URL}/{capability['intent_id']}/finalize") if finalize else None
    return issued, finalized


def upload_verified(client, store, submission_id: str, content: bytes, filename: str, **extra) -> str:
    issued, finalized = upload(client, store, submission_id, content, filename, **extra)
    assert issued.status_code == 201, (issued.status_code, issued.get_json())
    assert finalized.status_code == 200, (finalized.status_code, finalized.get_json())
    return issued.get_json()["intent_id"]


__all__ = [
    "CANONICAL_STORE_EXTENSION", "INTENT_IDS_FIELD", "ISSUE_URL", "SUBMISSION_FIELD", "TEST_BUCKET",
    "TEST_SUPABASE_URL", "canonical_documents", "declared_mime", "form_submission", "issue", "upload",
    "upload_verified",
]
