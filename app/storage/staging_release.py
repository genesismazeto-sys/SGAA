"""Release the temporary Supabase copy of a document once its drive copies are proven.

Supabase Storage is upload staging and the durable fallback; Google Drive and
OneDrive hold the permanent copies (``drive_mirror``).  ONE bounded pass:

    1. finish every interrupted release (``releasing``: delete the Supabase
       object again; an already missing one counts as done);
    2. the REQUIRED providers are the connected ones; with none connected
       nothing is released;
    3. per ``staged`` object: every required provider must hold a synced copy
       bound to its active account, and a document too large to relay through
       the hosting platform needs a OneDrive copy (``document_copies``);
    4. every required copy is READ BACK in full and proven against the
       recorded size and SHA-256 -- exactly the read the application serves
       afterwards.  A copy that does not match is sent back to ``pending``
       (re-mirrored, never duplicated); any failure keeps the Supabase copy;
    5. only then ``staged`` -> ``releasing`` (committed: readers move to the
       drive copies), the Supabase object is deleted, -> ``released``.

The Supabase copy is therefore never deleted unless the application has just
retrieved the document from every connected drive.  An unavailable provider
leaves the object ``staged``; the next pass tries again.

``enroll_existing`` is the controlled backfill for documents uploaded before
the activation: a dry run by default, an explicit bounded batch otherwise.
Nothing else ever enrolls an older document.  Operator command line and
scheduler only (never imported by the web runtime).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import app.cloud_connections as cloud_connections
from app.db import write_transaction
from app.storage import copy_registry
from app.storage import custody_common
from app.storage import document_copies
from app.storage import mirror_outbox
from app.storage import request_documents
from app.storage.contracts import StorageError, StorageIntegrityError
from app.storage.object_store import STORAGE_OBJECT_MISSING, CanonicalStoreError

logger = logging.getLogger(__name__)

DEFAULT_BATCH = 5
MAX_BATCH = 100
PROVIDERS = ("google", copy_registry.PROVIDER)
RESULT_OK = "OK"
NO_DRIVE_CONNECTED = "NO_DRIVE_CONNECTED"
COPY_VERIFICATION_FAILED = "COPY_VERIFICATION_FAILED"


def _now() -> str:
    return custody_common.utc_now_text()


@dataclass
class ReleasePassResult:
    result_code: str = RESULT_OK
    examined: int = 0
    released: int = 0
    finished: int = 0
    waiting: int = 0
    kept_large: int = 0
    unverified: int = 0

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def _delete_staging_copy(conn, store, object_id: int) -> bool:
    row = conn.execute(
        "SELECT storage_bucket, storage_key FROM storage_objects WHERE id = ?", (int(object_id),)
    ).fetchone()
    try:
        store.delete(row[0], row[1])
    except CanonicalStoreError as exc:
        if exc.code != STORAGE_OBJECT_MISSING:
            # Stays ``releasing``: readers already use the drive copies; the next pass deletes again.
            logger.warning("staging copy of object %s not deleted (%s)", object_id, exc.code)
            return False
    with write_transaction(conn):
        copy_registry.mark_released(conn, object_id=object_id)
    return True


def _reset_copy(conn, copy: document_copies.Copy, object_id: int) -> None:
    with write_transaction(conn):
        if copy.provider == "google":
            mirror_outbox.reset_missing_mirror(conn, object_id=object_id, drive_file_id=copy.file_id,
                                               error_code=COPY_VERIFICATION_FAILED, now=_now())
        else:
            copy_registry.reset_missing_copy(conn, object_id=object_id, file_id=copy.file_id,
                                             error_code=COPY_VERIFICATION_FAILED, now=_now())


def _release_one(conn, store, object_id: int, required: list[str], result: ReleasePassResult) -> None:
    obj = conn.execute(
        "SELECT sha256, size_bytes, lifecycle_state FROM storage_objects WHERE id = ?", (int(object_id),)
    ).fetchone()
    if obj is None or obj[2] != "active":
        return
    copies = {copy.provider: copy for copy in document_copies.verified_copies(conn, object_id)}
    if any(provider not in copies for provider in required):
        result.waiting += 1
        return
    if int(obj[1]) > document_copies.DRIVE_PROXY_MAX_BYTES and copy_registry.PROVIDER not in copies:
        result.kept_large += 1
        return
    for provider in required:
        copy = copies[provider]
        try:
            document_copies.read_copy(conn, copy, sha256=str(obj[0]), size_bytes=int(obj[1]))
        except StorageIntegrityError:
            _reset_copy(conn, copy, object_id)
            result.unverified += 1
            return
        except StorageError as exc:
            logger.warning("copy of object %s not readable now (%s, %s)", object_id, provider, type(exc).__name__)
            result.unverified += 1
            return
    with write_transaction(conn):
        marked = copy_registry.mark_releasing(conn, object_id=object_id, providers=required, now=_now())
    if marked and _delete_staging_copy(conn, store, object_id):
        result.released += 1


def run_release_pass(conn, *, limit: int = DEFAULT_BATCH) -> ReleasePassResult:
    """ONE bounded release pass; see the module docstring.  Item failures keep the copy, never raise."""
    custody_common.positive_limit(limit, MAX_BATCH)
    result = ReleasePassResult()
    if not copy_registry.prepare(conn, now=_now()):
        result.result_code = copy_registry.REGISTRY_UNAVAILABLE
        return result
    try:
        store = request_documents.canonical_store()
    except CanonicalStoreError as exc:
        result.result_code = exc.code
        return result
    for object_id in copy_registry.releasing_objects(conn, limit=MAX_BATCH):
        result.finished += _delete_staging_copy(conn, store, object_id)
    required = [p for p in PROVIDERS if cloud_connections.get_active_cloud_account(conn, p) is not None]
    if not required:
        result.result_code = NO_DRIVE_CONNECTED
        return result
    for object_id in copy_registry.staged_objects(conn, limit=limit):
        result.examined += 1
        _release_one(conn, store, object_id, required, result)
    logger.info("staging release pass: %s", result.as_dict())
    return result


def enroll_existing(conn, *, limit: int, apply: bool) -> dict:
    """The controlled backfill: report (dry run) or enroll ``limit`` older documents."""
    if not copy_registry.prepare(conn, now=_now()):
        return {"result_code": copy_registry.REGISTRY_UNAVAILABLE}
    unenrolled = copy_registry.count_unenrolled(conn)
    enrolled = []
    if apply:
        with write_transaction(conn):
            enrolled = copy_registry.enroll_existing(conn, limit=limit, now=_now())
    return {"result_code": RESULT_OK, "applied": bool(apply), "unenrolled": unenrolled, "enrolled": len(enrolled)}


__all__ = [
    "DEFAULT_BATCH",
    "MAX_BATCH",
    "NO_DRIVE_CONNECTED",
    "RESULT_OK",
    "ReleasePassResult",
    "enroll_existing",
    "run_release_pass",
]
