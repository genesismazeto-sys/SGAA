"""Drive mirror worker: copy active canonical objects to Google Drive and OneDrive, post-commit.

Supabase Storage receives every upload; Google Drive and OneDrive hold the
permanent copies.  This module drives ONE bounded pass for ONE provider, each
independently: Google over the ``storage_objects`` outbox
(``app.storage.mirror_outbox``), OneDrive over the same state machine in
``app.storage.copy_registry`` (PostgreSQL only).  An operator or the scheduler
invokes it (``python -m app.storage.cli mirror-run``); no web route, view or
request hook reaches it, so drive availability never blocks a canonical
operation.  Once ``app.storage.staging_release`` has released an object's
Supabase copy, the bytes come from another verified drive copy instead.

ONE PASS
    1. record the start in the worker-health row;
    2. resolve the canonical store and the ACTIVE drive (the provider's single
       active connection and its logical account key; a OneDrive key is bound
       from Graph ``/me`` on first use).  Without them nothing is claimed: an
       unreachable drive leaves every object ``pending`` instead of burning
       attempts;
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
from app.storage import copy_registry
from app.storage import custody_common
from app.storage import document_copies
from app.storage import mirror_outbox as outbox
from app.storage import onedrive
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
DRIVE_STORAGE_EXTENSION = document_copies.GOOGLE_STORAGE_EXTENSION
PROVIDERS = ("google", "onedrive")

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
    """A provider's active connection: its managed storage, credential row and LOGICAL account key."""

    storage: object
    account_key: str
    account_id: int
    provider: str = "google"

    def __repr__(self) -> str:
        return f"ActiveDrive(provider={self.provider!r}, account_key=<bound>)"


@dataclass(frozen=True)
class _Lane:
    """What differs per provider: the outbox, the storage resolution and the item-id alphabet."""

    provider: str
    outbox: object
    resolve: object
    is_item_id: object
    records_health: bool


def _lane(provider: str) -> _Lane:
    if provider == "google":
        return _Lane("google", outbox,
                     lambda conn: resolve_google_managed_storage(conn, extension_key=DRIVE_STORAGE_EXTENSION),
                     custody_common.is_drive_id, True)
    if provider == copy_registry.PROVIDER:
        return _Lane(provider, copy_registry, onedrive.resolve_onedrive_managed_storage, onedrive.is_item_id, False)
    raise ValueError("unknown drive provider")


def _now() -> str:
    # The adjudicated clock seam: always through the module attribute.
    return custody_common.utc_now_text()


def _account(conn, provider: str = "google") -> tuple[int, str | None] | None:
    account = cloud_connections.get_active_cloud_account(conn, provider)
    if account is None:
        return None
    return int(account["id"]), account.get("provider_account_key")


def _bind_identity(conn, provider: str, before: tuple[int, str | None], storage) -> tuple[int, str]:
    """Bind a connection whose logical key was never established to the account the provider reports."""
    try:
        observed = storage.account_key()
    except StorageError as exc:
        raise DriveUnavailable(exc.code) from None
    account = cloud_connections.get_active_cloud_account(conn, provider)
    if account is None or int(account["id"]) != before[0]:
        raise DriveUnavailable(DRIVE_ACCOUNT_CHANGED)
    try:
        cloud_connections.bind_or_check_account_identity(conn, account, observed)
    except cloud_connections.CloudConnectionError as exc:
        raise DriveUnavailable(exc.debug_code or DRIVE_ACCOUNT_UNKNOWN) from None
    return before[0], observed


def active_drive(conn, provider: str = "google") -> ActiveDrive:
    """The provider's single active connection, for the storage background tools.

    The active account row is read before and after the credential is
    resolved: a connection replaced in between could otherwise bind objects to
    the wrong logical account.  A Google key comes from the connect flow; a
    OneDrive key is bound here, once, from the account Graph reports.  Raises
    :class:`DriveUnavailable`.
    """
    lane = _lane(provider)
    before = _account(conn, provider)
    if before is None:
        raise DriveUnavailable(outbox.DRIVE_NOT_CONNECTED)
    if not before[1] and provider == "google":
        raise DriveUnavailable(DRIVE_ACCOUNT_UNKNOWN)
    try:
        storage = lane.resolve(conn)
    except StorageError as exc:
        raise DriveUnavailable(exc.code) from None
    if not before[1]:
        before = _bind_identity(conn, provider, before, storage)
    if _account(conn, provider) != before:
        raise DriveUnavailable(DRIVE_ACCOUNT_CHANGED)
    return ActiveDrive(storage=storage, account_key=str(before[1]), account_id=before[0], provider=provider)


def still_active(conn, drive: ActiveDrive) -> bool:
    """Whether ``drive`` is still THE active connection (a credential refresh
    after a 401 resolves whatever account is active NOW)."""
    return _account(conn, drive.provider) == (drive.account_id, drive.account_key)


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
    #: The other providers' verified copies when the Supabase copy is released (the byte source).
    sources: tuple | None = None


def _resolve(conn, work: outbox.MirrorWork, provider: str) -> _Resolved | None:
    """Lifecycle, owner, Drive context and source in ONE short transaction; ``None`` if retired.

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
        sources = None
        if copy_registry.supabase_released(conn, work.object_id):
            sources = tuple(copy for copy in document_copies.verified_copies(conn, work.object_id)
                            if copy.provider != provider)
    return _Resolved(kind, row, context, sources)


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
    if isinstance(exc, document_copies.CopyUnavailable):
        return _RETRY, exc.code
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


def _record(conn, lane: _Lane, result: MirrorPassResult, work: outbox.MirrorWork, outcome: str, code: str,
            *, delay: int = UNAVAILABLE_DELAY_SECONDS, counter: str = "deferred") -> None:
    now = _now()
    try:
        with write_transaction(conn):
            if outcome == _RETRY and work.attempts < MAX_ATTEMPTS:
                lane.outbox.mark_retry(
                    conn, **_fence(work), error_code=code,
                    next_attempt_at=custody_common.add_seconds(now, backoff_seconds(work.attempts)), now=now,
                )
                result.retried += 1
            elif outcome in (_RETRY, _RECONCILE):
                lane.outbox.mark_reconciliation_required(
                    conn, **_fence(work), error_code=MIRROR_RETRY_EXHAUSTED if outcome == _RETRY else code, now=now,
                )
                result.reconciliation += 1
            else:
                lane.outbox.mark_pending_disconnected(
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
        remote.parent_id != placement.parent_id
        or int(remote.size) != work.size_bytes
        or str(remote.sha256 or "").lower() != work.sha256
    ):
        raise _Refusal(MIRROR_INTEGRITY_MISMATCH)


def _source_bytes(conn, lane: _Lane, store, work: outbox.MirrorWork, resolved: _Resolved) -> bytes:
    """The bytes the drive receives: the canonical bytes, proven against the verified
    record -- never trusted from provider metadata -- read from the Supabase staging
    copy, or from another provider's verified copy once that one was released."""
    if resolved.sources is None:
        try:
            content, _stat = read_verified(
                store, work.storage_bucket, work.storage_key, expected_size=work.size_bytes,
                expected_sha256=work.sha256, max_bytes=BUSINESS_DOCUMENT_MAX_BYTES,
            )
            return content
        except CanonicalStoreError as exc:
            # Released between the resolve and this read: the drive copies are the source now.
            if exc.code != STORAGE_OBJECT_MISSING or not copy_registry.supabase_released(conn, work.object_id):
                raise
            sources = [copy for copy in document_copies.verified_copies(conn, work.object_id)
                       if copy.provider != lane.provider]
    else:
        sources = list(resolved.sources)
    return document_copies.read_from_copies(conn, sources, sha256=work.sha256, size_bytes=work.size_bytes)


def _mirror_one(conn, lane: _Lane, store, drive: ActiveDrive, folders, work: outbox.MirrorWork,
                result: MirrorPassResult) -> None:
    if work.lease_expires_at <= custody_common.add_seconds(_now(), LEASE_SAFETY_SECONDS):
        # Never start provider work on a nearly lost lease: hand the object back now.
        _record(conn, lane, result, work, _DEFER, LEASE_SAFETY_MARGIN, delay=0, counter="skipped")
        return
    if work.drive_account_key is not None and work.drive_account_key != drive.account_key:
        _record(conn, lane, result, work, _DEFER, DRIVE_ACCOUNT_UNAVAILABLE)
        return
    resolved = _resolve(conn, work, lane.provider)
    if resolved is None:
        _record(conn, lane, result, work, _DEFER, OBJECT_RETIRED)
        return
    placement = _place(folders, resolved, work)
    content = _source_bytes(conn, lane, store, work, resolved)
    remote = drive.storage.upload(
        parent_id=placement.parent_id, stored_filename=placement.filename, content=content,
        mime_type=work.mime_type, operation_key=placement.operation_key,
        object_kind=placement.object_kind, semantic_properties=placement.semantic_properties,
    )
    if not lane.is_item_id(remote.file_id):
        raise _Refusal(MIRROR_INTEGRITY_MISMATCH)
    _verified_remote(work, placement, remote)
    if not still_active(conn, drive):
        # A refresh may have written the copy into whichever account is
        # active now: never bind it to the resolved one.  The next pass
        # finds the copy through ``sgaaOperation`` under the right account.
        raise DriveUnavailable(DRIVE_ACCOUNT_CHANGED)
    try:
        with write_transaction(conn):
            lane.outbox.complete_synced(
                conn, **_fence(work), drive_file_id=str(remote.file_id), drive_parent_id=placement.parent_id,
                drive_account_key=drive.account_key, now=_now(),
            )
    except CustodyError as exc:
        if exc.code == outbox.DRIVE_ACCOUNT_MISMATCH:
            # Bound to another account meanwhile: the lease is still ours -- hand it back.
            _record(conn, lane, result, work, _DEFER, DRIVE_ACCOUNT_UNAVAILABLE)
            return
        if exc.code != outbox.MIRROR_LEASE_LOST:
            raise
        result.lost += 1
        return
    result.synced += 1


def run_mirror_pass(
    conn,
    *,
    provider: str = "google",
    limit: int = DEFAULT_BATCH,
    lease_seconds: int = outbox.DEFAULT_LEASE_SECONDS,
) -> MirrorPassResult:
    """Run ONE bounded mirror pass for ``provider``; see the module docstring.

    An item failure is classified and recorded, never raised.  A database
    failure propagates and leaves the health row started-but-unfinished --
    the durable trace of an interrupted pass.  The singleton health row
    describes the Google pass; a OneDrive pass reports its result only.
    """
    lane = _lane(provider)
    custody_common.positive_limit(limit, outbox.MAX_CLAIM_BATCH)
    if not LEASE_SAFETY_SECONDS < lease_seconds <= outbox.MAX_LEASE_SECONDS:
        raise ValueError(f"lease_seconds must be {LEASE_SAFETY_SECONDS + 1}..{outbox.MAX_LEASE_SECONDS}")
    if lane.records_health:
        with write_transaction(conn):
            outbox.record_worker_started(conn, now=_now())
    result = _pass(conn, lane, limit=limit, lease_seconds=lease_seconds)
    if lane.records_health:
        with write_transaction(conn):
            outbox.record_worker_finished(
                conn, now=_now(), result_code=result.result_code, claimed=result.claimed,
                synced=result.synced, retried=result.retried,
            )
    logger.info("drive mirror pass (%s): %s", provider, result.as_dict())
    return result


def _pass(conn, lane: _Lane, *, limit: int, lease_seconds: int) -> MirrorPassResult:
    result = MirrorPassResult()
    if lane.outbox is copy_registry and not copy_registry.prepare(conn, now=_now()):
        result.result_code = copy_registry.REGISTRY_UNAVAILABLE
        return result
    try:
        store = request_documents.canonical_store()
    except CanonicalStoreError as exc:
        result.result_code = exc.code
        return result
    try:
        drive = active_drive(conn, lane.provider)
    except DriveUnavailable as exc:
        result.result_code = exc.code
        return result
    with write_transaction(conn):
        now = _now()
        result.released = lane.outbox.release_expired_leases(conn, now=now, limit=outbox.MAX_CLAIM_BATCH)
        claimed = lane.outbox.claim_due_mirror_work(
            conn, limit=limit, worker_token=custody_common.new_lease_token(), now=now,
            lease_seconds=lease_seconds,
        )
    result.claimed = len(claimed)
    folders = _FolderMemo(drive.storage)
    for index, work in enumerate(claimed):
        try:
            _mirror_one(conn, lane, store, drive, folders, work, result)
            continue
        except Exception as exc:  # per-item isolation: classified and recorded below
            if classify_database_error(exc) is not None:
                raise
            outcome, code = _classify(exc)
            if code == MIRROR_UNEXPECTED_ERROR:
                logger.error("drive mirror: object %s failed (%s)", work.object_id, type(exc).__name__)
        _record(conn, lane, result, work, outcome, code)
        if outcome == _DEFER:
            # The credential is unusable for every remaining object too.
            for remaining in claimed[index + 1:]:
                _record(conn, lane, result, remaining, _DEFER, code)
            result.result_code = code
            break
    return result


__all__ = [
    "ActiveDrive",
    "DRIVE_STORAGE_EXTENSION",
    "DriveUnavailable",
    "MAX_ATTEMPTS",
    "MirrorPassResult",
    "PROVIDERS",
    "Placement",
    "active_drive",
    "backoff_seconds",
    "mirror_operation_key",
    "run_mirror_pass",
    "still_active",
]
