"""Google Drive mirror worker: copy active canonical objects to Drive, post-commit.

Supabase Storage is the canonical store; Drive is the required asynchronous
secondary mirror / archive.  This module drives the ``storage_objects`` outbox
(``app.storage.mirror_outbox``) for ONE bounded pass; an operator or, later, a
scheduler invokes it (``python -m app.storage.cli mirror-run``).  No web route,
view or request hook reaches it, so Drive availability never blocks a
canonical operation.

ONE PASS
    1. record the start in the worker-health row;
    2. resolve the canonical store and the ACTIVE Drive (the single active
       Google connection and its logical account key).  Without them nothing
       is claimed: an unreachable Drive leaves every object ``pending``
       instead of burning attempts;
    3. turn expired leases into due retries, claim a bounded batch under a
       fresh lease token;
    4. per object: read its lifecycle, its one business owner and (for a
       request) its Drive context in ONE short transaction; then, with NO
       transaction open, place it on the EXISTING managed Drive conventions,
       read and verify the canonical bytes, upload idempotently
       (find-by-``sgaaOperation`` first) and verify the Drive result; re-check
       that the active Drive account is still the one the pass resolved; and
       complete under the lease fence;
    5. record the outcome counts.

PLACEMENT (the existing conventions, never new ones)
    request documents  SGAA/COMPROVANTES/<turma>/<eixo>/<aluno>
                       (``app.comprovante_hierarchy.ensure_request_hierarchy``),
                       kind ``comprovante``, ``sgaaRequest`` / ``sgaaAttachment``
    admin ARQUIVOS     SGAA/ARQUIVOS (``app.arquivos._ensure_arquivos_root``),
                       kind ``arquivo``, ``sgaaArquivo``
    The Drive name is the basename of the business ``filename``; the
    operation key is the business ``operation_key`` or, for a legacy row that
    has none, ``sgaa-object-`` + 40 hex of SHA-256(``bucket/key``).  A legacy
    Google file uploaded under the same conventions is therefore found and
    ADOPTED (after verification) instead of duplicated.

RETRY POLICY
    Backoff 60 s doubling per attempt, capped at 6 h; at most
    ``MAX_ATTEMPTS`` claims, after which a retryable failure becomes
    ``reconciliation_required`` (``MIRROR_RETRY_EXHAUSTED``).  Unsafe
    outcomes -- a Drive conflict or integrity mismatch, an invalid placement,
    a missing owner, a missing or divergent canonical object -- go straight to
    ``reconciliation_required``: retrying cannot fix them.  Drive or canonical
    authorization failing mid-pass, or the active account changing, stops the
    pass and returns the remaining claimed objects to ``pending`` uncounted.
    A transport failure (timeout, connection reset) is transient: it counts.
    An object whose lease is nearly over is returned to ``pending`` at once.
    ``mirror_outbox.requeue_for_mirror`` is the operator's recovery.

WHAT THE WORKER NEVER DOES
    Delete, overwrite or upsert a canonical object; trash or delete a Drive
    file; start a copy of a retired object (an object retired while its copy
    is being written keeps the copy and is recorded ``synced``: the record
    states what Drive holds); re-point an object bound to one Drive account
    to another (the binding is permanent; such an object waits ``pending``
    until its account is the active connection again).
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass

import app.cloud_connections as cloud_connections
from app import arquivos
from app.comprovante_hierarchy import ComprovanteHierarchyError, ensure_request_hierarchy
from app.comprovantes import ComprovanteError, _request_context
from app.db import classify_database_error, write_transaction
from app.prod1_storage_ddl import BUSINESS_DOCUMENT_MAX_BYTES
from app.storage import custody_common
from app.storage import mirror_outbox as outbox
from app.storage import request_documents
from app.storage.contracts import (
    StorageAuthorizationError,
    StorageConfigurationError,
    StorageConflictError,
    StorageConnectionError,
    StorageError,
    StorageIntegrityError,
)
from app.storage.custody_common import CustodyError
from app.storage.google_connection import resolve_google_managed_storage
from app.storage.object_store import (
    STORAGE_AUTH_FAILURE,
    STORAGE_CONFIG_MISSING,
    STORAGE_INTEGRITY_MISMATCH,
    STORAGE_OBJECT_MISSING,
    STORAGE_OBJECT_TOO_LARGE,
    CanonicalStoreError,
    read_verified,
)

logger = logging.getLogger(__name__)

#: ``app.extensions`` key of an injected Drive storage (tests); production
#: resolves the active Google connection.
DRIVE_STORAGE_EXTENSION = "drive_mirror_storage"

DEFAULT_BATCH = 25
MAX_ATTEMPTS = 10
BACKOFF_BASE_SECONDS = 60
BACKOFF_CAP_SECONDS = 6 * 60 * 60
#: A pass that cannot use Drive or the canonical store retries its objects later.
UNAVAILABLE_DELAY_SECONDS = 5 * 60
#: An object whose lease ends sooner than this is handed back to ``pending``
#: at once: a provider call is never started on a nearly lost lease.
LEASE_SAFETY_SECONDS = 60

RESULT_OK = "OK"
DRIVE_ACCOUNT_UNKNOWN = "DRIVE_ACCOUNT_UNKNOWN"
DRIVE_ACCOUNT_CHANGED = "DRIVE_ACCOUNT_CHANGED"
DRIVE_ACCOUNT_UNAVAILABLE = "DRIVE_ACCOUNT_UNAVAILABLE"
LEASE_SAFETY_MARGIN = "LEASE_SAFETY_MARGIN"
DRIVE_AUTH_UNAVAILABLE = "DRIVE_AUTH_UNAVAILABLE"
OBJECT_RETIRED = "OBJECT_RETIRED"
MIRROR_OWNER_MISSING = "MIRROR_OWNER_MISSING"
MIRROR_OWNER_AMBIGUOUS = "MIRROR_OWNER_AMBIGUOUS"
MIRROR_INTEGRITY_MISMATCH = "MIRROR_INTEGRITY_MISMATCH"
MIRROR_RETRY_EXHAUSTED = "MIRROR_RETRY_EXHAUSTED"
MIRROR_UNEXPECTED_ERROR = "MIRROR_UNEXPECTED_ERROR"
CANONICAL_OBJECT_MISSING = "CANONICAL_OBJECT_MISSING"
CANONICAL_INTEGRITY_MISMATCH = "CANONICAL_INTEGRITY_MISMATCH"

_DRIVE_NAME_MAX = 255


class DriveUnavailable(RuntimeError):
    """No usable Drive for background storage work; ``code`` is fixed and value-free."""

    def __init__(self, code: str) -> None:
        self.code = custody_common.sanitize_error_code(code)
        super().__init__(self.code)


@dataclass(frozen=True)
class ActiveDrive:
    """The active Google connection: its managed storage, credential row and LOGICAL account key."""

    storage: object
    account_key: str
    account_id: int

    def __repr__(self) -> str:
        return "ActiveDrive(account_key=<bound>)"


def _now() -> str:
    # The adjudicated clock seam: always through the module attribute.
    return custody_common.utc_now_text()


def _account(conn) -> tuple[int, str | None] | None:
    account = cloud_connections.get_active_cloud_account(conn, "google")
    if account is None:
        return None
    return int(account["id"]), account.get("provider_account_key")


def active_drive(conn) -> ActiveDrive:
    """The single active Google connection, for the storage background tools.

    The active account row is read before and after the credential is
    resolved: a connection replaced in between could otherwise bind objects to
    the wrong logical account.  Raises :class:`DriveUnavailable`.
    """
    before = _account(conn)
    if before is None:
        raise DriveUnavailable(outbox.DRIVE_NOT_CONNECTED)
    if not before[1]:
        raise DriveUnavailable(DRIVE_ACCOUNT_UNKNOWN)
    try:
        storage = resolve_google_managed_storage(conn, extension_key=DRIVE_STORAGE_EXTENSION)
    except StorageError as exc:
        raise DriveUnavailable(exc.code) from None
    if _account(conn) != before:
        raise DriveUnavailable(DRIVE_ACCOUNT_CHANGED)
    return ActiveDrive(storage=storage, account_key=str(before[1]), account_id=before[0])


def still_active(conn, drive: ActiveDrive) -> bool:
    """Whether ``drive`` is still THE active connection (a credential refresh
    after a 401 resolves whatever account is active NOW)."""
    return _account(conn) == (drive.account_id, drive.account_key)


# ---------------------------------------------------------------------------
# placement
# ---------------------------------------------------------------------------


class _Refusal(RuntimeError):
    """An item that must not be retried automatically; ``code`` is value-free."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Placement:
    parent_id: str
    filename: str
    operation_key: str
    object_kind: str
    semantic_properties: dict


class _FolderMemo:
    """Per-pass memo of ``ensure_folder``: one Drive lookup per managed folder."""

    def __init__(self, storage) -> None:
        self._storage = storage
        self._ids: dict[tuple[str, str, str], str] = {}

    def ensure_folder(self, *, parent_id: str, kind: str, semantic_id: str, display_name: str) -> str:
        key = (str(parent_id), str(kind), str(semantic_id))
        if key not in self._ids:
            self._ids[key] = self._storage.ensure_folder(
                parent_id=parent_id, kind=kind, semantic_id=semantic_id, display_name=display_name
            )
        return self._ids[key]


def mirror_operation_key(operation_key, *, bucket: str, key: str) -> str:
    """The Drive ``sgaaOperation`` of an object: the business key, else one derived from the locator."""
    value = str(operation_key or "").strip()
    if value:
        return value
    return "sgaa-object-" + hashlib.sha256(f"{bucket}/{key}".encode("utf-8")).hexdigest()[:40]


def _drive_name(filename) -> str:
    name = os.path.basename(str(filename or "").replace("\\", "/")).strip()
    return (name or "documento")[:_DRIVE_NAME_MAX]


def _owner(conn, object_id: int):
    requests = conn.execute(
        "SELECT id, requisicao_id, filename, operation_key FROM requisicao_arquivos WHERE storage_object_id = ?",
        (int(object_id),),
    ).fetchall()
    files = conn.execute(
        "SELECT id, filename, operation_key FROM admin_arquivos WHERE storage_object_id = ?",
        (int(object_id),),
    ).fetchall()
    if len(requests) + len(files) == 0:
        raise _Refusal(MIRROR_OWNER_MISSING)
    if len(requests) + len(files) > 1:
        raise _Refusal(MIRROR_OWNER_AMBIGUOUS)
    return ("comprovante", requests[0]) if requests else ("arquivo", files[0])


@dataclass(frozen=True)
class _Resolved:
    kind: str
    row: object
    request_context: tuple | None


def _resolve(conn, work: outbox.MirrorWork) -> _Resolved | None:
    """Lifecycle, owner and Drive context in ONE short transaction; ``None`` if retired.

    No provider call may run while a transaction (and its locks) is open, so
    every database read an item needs happens here.  The first Drive
    placement of an old request freezes its turma snapshot -- the
    established rule of the legacy uploader -- which is why this is a write
    transaction.
    """
    with write_transaction(conn):
        state = conn.execute(
            "SELECT lifecycle_state FROM storage_objects WHERE id = ?", (work.object_id,)
        ).fetchone()
        if state is None or state[0] != "active":
            return None
        kind, row = _owner(conn, work.object_id)
        context = _request_context(conn, int(row["requisicao_id"])) if kind == "comprovante" else None
    return _Resolved(kind, row, context)


def _place(folders, resolved: _Resolved, work: outbox.MirrorWork) -> Placement:
    """Where the object belongs in the managed Drive hierarchy (creating folders as needed)."""
    row = resolved.row
    operation = mirror_operation_key(row["operation_key"], bucket=work.storage_bucket, key=work.storage_key)
    if resolved.kind == "comprovante":
        request_row, payload, turma_id, turma_code = resolved.request_context
        parent = ensure_request_hierarchy(
            folders, request_row=request_row, snapshot_payload=payload,
            turma_id=turma_id, turma_code=turma_code,
        )
        semantic = {"sgaaRequest": str(int(row["requisicao_id"])), "sgaaAttachment": str(int(row["id"]))}
    else:
        parent = arquivos._ensure_arquivos_root(folders)
        semantic = {"sgaaArquivo": str(int(row["id"]))}
    return Placement(parent, _drive_name(row["filename"]), operation, resolved.kind, semantic)


# ---------------------------------------------------------------------------
# outcomes
# ---------------------------------------------------------------------------


def backoff_seconds(attempts: int) -> int:
    """Delay before the next attempt after ``attempts`` claims (>= 1)."""
    return min(BACKOFF_BASE_SECONDS * 2 ** (max(1, int(attempts)) - 1), BACKOFF_CAP_SECONDS)


@dataclass
class MirrorPassResult:
    result_code: str = RESULT_OK
    released: int = 0
    claimed: int = 0
    synced: int = 0
    retried: int = 0
    reconciliation: int = 0
    deferred: int = 0
    lost: int = 0
    skipped: int = 0

    def as_dict(self) -> dict:
        return dict(self.__dict__)


#: Item outcomes.  ``_DEFER`` returns the object to ``pending`` uncounted; when
#: a FAILURE classifies as ``_DEFER`` the credential is unusable and the pass stops.
_RETRY, _RECONCILE, _DEFER = "retry", "reconcile", "defer"


def _classify(exc: BaseException) -> tuple[str, str]:
    """(outcome, value-free code) of one failed item."""
    if isinstance(exc, _Refusal):
        return _RECONCILE, exc.code
    if isinstance(exc, DriveUnavailable):
        return _DEFER, exc.code
    if isinstance(exc, CanonicalStoreError):
        if exc.code == STORAGE_OBJECT_MISSING:
            return _RECONCILE, CANONICAL_OBJECT_MISSING
        if exc.code in (STORAGE_INTEGRITY_MISMATCH, STORAGE_OBJECT_TOO_LARGE):
            return _RECONCILE, CANONICAL_INTEGRITY_MISMATCH
        if exc.code in (STORAGE_AUTH_FAILURE, STORAGE_CONFIG_MISSING):
            return _DEFER, exc.code
        return _RETRY, exc.code
    if isinstance(exc, (StorageAuthorizationError, StorageConfigurationError, StorageConnectionError)):
        return _DEFER, DRIVE_AUTH_UNAVAILABLE
    if isinstance(exc, (StorageConflictError, StorageIntegrityError)):
        return _RECONCILE, exc.code
    if isinstance(exc, StorageError):
        return _RETRY, exc.code
    if isinstance(exc, (ComprovanteError, ComprovanteHierarchyError)):
        return _RECONCILE, custody_common.sanitize_error_code(exc.code)
    return _RETRY, MIRROR_UNEXPECTED_ERROR


def _fence(work: outbox.MirrorWork) -> dict:
    return dict(object_id=work.object_id, lease_token=work.lease_token, generation=work.generation)


def _record(conn, result: MirrorPassResult, work: outbox.MirrorWork, outcome: str, code: str,
            *, delay: int = UNAVAILABLE_DELAY_SECONDS, counter: str = "deferred") -> None:
    now = _now()
    try:
        with write_transaction(conn):
            if outcome == _RETRY and work.attempts < MAX_ATTEMPTS:
                outbox.mark_retry(
                    conn, **_fence(work), error_code=code,
                    next_attempt_at=custody_common.add_seconds(now, backoff_seconds(work.attempts)), now=now,
                )
                result.retried += 1
            elif outcome in (_RETRY, _RECONCILE):
                outbox.mark_reconciliation_required(
                    conn, **_fence(work), error_code=MIRROR_RETRY_EXHAUSTED if outcome == _RETRY else code, now=now,
                )
                result.reconciliation += 1
            else:
                outbox.mark_pending_disconnected(
                    conn, **_fence(work), code=code,
                    next_attempt_at=custody_common.add_seconds(now, delay), now=now,
                )
                setattr(result, counter, getattr(result, counter) + 1)
    except CustodyError as exc:
        if exc.code != outbox.MIRROR_LEASE_LOST:
            raise
        result.lost += 1


def _verified_remote(work: outbox.MirrorWork, placement: Placement, remote) -> None:
    if (
        not custody_common.is_drive_id(remote.file_id)
        or remote.parent_id != placement.parent_id
        or int(remote.size) != work.size_bytes
        or str(remote.sha256 or "").lower() != work.sha256
    ):
        raise _Refusal(MIRROR_INTEGRITY_MISMATCH)


def _mirror_one(conn, store, drive: ActiveDrive, folders, work: outbox.MirrorWork, result: MirrorPassResult) -> None:
    if work.lease_expires_at <= custody_common.add_seconds(_now(), LEASE_SAFETY_SECONDS):
        # Never start provider work on a nearly lost lease: hand the object back now.
        _record(conn, result, work, _DEFER, LEASE_SAFETY_MARGIN, delay=0, counter="skipped")
        return
    if work.drive_account_key is not None and work.drive_account_key != drive.account_key:
        _record(conn, result, work, _DEFER, DRIVE_ACCOUNT_UNAVAILABLE)
        return
    resolved = _resolve(conn, work)
    if resolved is None:
        _record(conn, result, work, _DEFER, OBJECT_RETIRED)
        return
    placement = _place(folders, resolved, work)
    # The bytes Drive receives are the canonical bytes, proven against the
    # verified record -- never trusted from provider metadata.
    content, _stat = read_verified(
        store, work.storage_bucket, work.storage_key, expected_size=work.size_bytes,
        expected_sha256=work.sha256, max_bytes=BUSINESS_DOCUMENT_MAX_BYTES,
    )
    remote = drive.storage.upload(
        parent_id=placement.parent_id, stored_filename=placement.filename, content=content,
        mime_type=work.mime_type, operation_key=placement.operation_key,
        object_kind=placement.object_kind, semantic_properties=placement.semantic_properties,
    )
    _verified_remote(work, placement, remote)
    if not still_active(conn, drive):
        # A refresh may have written the copy into whichever account is
        # active now: never bind it to the resolved one.  The next pass
        # finds the copy through ``sgaaOperation`` under the right account.
        raise DriveUnavailable(DRIVE_ACCOUNT_CHANGED)
    try:
        with write_transaction(conn):
            outbox.complete_synced(
                conn, **_fence(work), drive_file_id=str(remote.file_id), drive_parent_id=placement.parent_id,
                drive_account_key=drive.account_key, now=_now(),
            )
    except CustodyError as exc:
        if exc.code == outbox.DRIVE_ACCOUNT_MISMATCH:
            # Bound to another account meanwhile: the lease is still ours -- hand it back.
            _record(conn, result, work, _DEFER, DRIVE_ACCOUNT_UNAVAILABLE)
            return
        if exc.code != outbox.MIRROR_LEASE_LOST:
            raise
        result.lost += 1
        return
    result.synced += 1


def run_mirror_pass(
    conn,
    *,
    limit: int = DEFAULT_BATCH,
    lease_seconds: int = outbox.DEFAULT_LEASE_SECONDS,
) -> MirrorPassResult:
    """Run ONE bounded mirror pass; see the module docstring.

    An item failure is classified and recorded, never raised.  A database
    failure propagates and leaves the health row started-but-unfinished --
    the durable trace of an interrupted pass.
    """
    custody_common.positive_limit(limit, outbox.MAX_CLAIM_BATCH)
    if not LEASE_SAFETY_SECONDS < lease_seconds <= outbox.MAX_LEASE_SECONDS:
        raise ValueError(f"lease_seconds must be {LEASE_SAFETY_SECONDS + 1}..{outbox.MAX_LEASE_SECONDS}")
    with write_transaction(conn):
        outbox.record_worker_started(conn, now=_now())
    result = _pass(conn, limit=limit, lease_seconds=lease_seconds)
    with write_transaction(conn):
        outbox.record_worker_finished(
            conn, now=_now(), result_code=result.result_code, claimed=result.claimed,
            synced=result.synced, retried=result.retried,
        )
    logger.info("drive mirror pass: %s", result.as_dict())
    return result


def _pass(conn, *, limit: int, lease_seconds: int) -> MirrorPassResult:
    result = MirrorPassResult()
    try:
        store = request_documents.canonical_store()
    except CanonicalStoreError as exc:
        result.result_code = exc.code
        return result
    try:
        drive = active_drive(conn)
    except DriveUnavailable as exc:
        result.result_code = exc.code
        return result
    with write_transaction(conn):
        now = _now()
        result.released = outbox.release_expired_leases(conn, now=now, limit=outbox.MAX_CLAIM_BATCH)
        claimed = outbox.claim_due_mirror_work(
            conn, limit=limit, worker_token=custody_common.new_lease_token(), now=now,
            lease_seconds=lease_seconds,
        )
    result.claimed = len(claimed)
    folders = _FolderMemo(drive.storage)
    for index, work in enumerate(claimed):
        try:
            _mirror_one(conn, store, drive, folders, work, result)
            continue
        except Exception as exc:  # per-item isolation: classified and recorded below
            if classify_database_error(exc) is not None:
                raise
            outcome, code = _classify(exc)
            if code == MIRROR_UNEXPECTED_ERROR:
                logger.error("drive mirror: object %s failed (%s)", work.object_id, type(exc).__name__)
        _record(conn, result, work, outcome, code)
        if outcome == _DEFER:
            # The credential is unusable for every remaining object too.
            for remaining in claimed[index + 1:]:
                _record(conn, result, remaining, _DEFER, code)
            result.result_code = code
            break
    return result


__all__ = [
    "ActiveDrive",
    "DRIVE_STORAGE_EXTENSION",
    "DriveUnavailable",
    "MAX_ATTEMPTS",
    "MirrorPassResult",
    "Placement",
    "active_drive",
    "backoff_seconds",
    "mirror_operation_key",
    "run_mirror_pass",
    "still_active",
]
