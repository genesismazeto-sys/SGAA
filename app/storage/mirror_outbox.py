"""Durable Google Drive mirror outbox over ``storage_objects`` (prod-1/v14).

``storage_objects`` itself is the outbox: every active canonical object owes
Drive a copy, tracked by ``drive_sync_state``:

    pending ──claim──> syncing ──complete_synced──> synced
       ^                 │  ├──mark_retry──> retry ──claim──> syncing
       │                 │  ├──mark_reconciliation_required──> reconciliation_required
       ├─mark_pending_disconnected (no usable Drive)              │
       │                 └──lease expires──> reclaimable by claim / release_expired_leases
       └─────────── requeue_for_mirror (operator recovery) ───────┘

LEASES AND FENCING
    A claim stamps a fresh random ``lease_token``, a ``lease_expires_at`` and
    increments ``drive_generation``.  Every later transition matches the row
    id, the lease token, the generation, ``drive_sync_state = 'syncing'`` AND
    an unexpired lease.  A worker whose lease expired -- whether or not
    another worker already reclaimed the row -- therefore updates nothing and
    gets ``MIRROR_LEASE_LOST``.

CONCURRENCY
    PostgreSQL claims with ``SELECT ... FOR UPDATE SKIP LOCKED`` in a bounded
    batch, so concurrent claimers never take the same row and never wait on
    each other; the row predicate is re-checked on the locked row version.
    SQLite has no row locks: the caller's ``BEGIN IMMEDIATE`` serializes
    whole claim transactions, which yields the same logical outcome (no
    duplicate claim) without pretending to offer the same primitive.

ACCOUNT IDENTITY
    ``drive_account_key`` is the LOGICAL Google account
    (``app.cloud_account_identity``), never a ``cloud_accounts`` row.  It may
    be NULL while no account was bound (pending / retry); once bound it is
    never replaced or dropped (``DRIVE_ACCOUNT_MISMATCH`` here, the
    ``trg_storage_objects_drive_account_bound`` trigger in the schema).  A
    worker resolves it to the current credential through
    ``app.cloud_connections.resolve_active_account_id_by_key``; no active
    credential means "Drive disconnected" (``mark_pending_disconnected``), never
    a problem of the canonical object.

SCOPE
    State machine and primitives only; the worker that drives them is
    ``app.storage.drive_mirror``.  No thread, no scheduler, and no physical
    purge of a canonical object anywhere.  The caller owns the transaction
    and commits.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.cloud_account_identity import AccountIdentityError, require_provider_account_key
from app.storage.custody_common import (
    CustodyError,
    add_seconds,
    is_postgres,
    new_lease_token,
    positive_limit,
    require_lease_token,
    require_utc_text,
    require_write_transaction,
    sanitize_error_code,
)

MAX_CLAIM_BATCH = 100
MAX_REQUEUE_BATCH = 1000
DEFAULT_LEASE_SECONDS = 300
MAX_LEASE_SECONDS = 3600
DRIVE_NOT_CONNECTED = "DRIVE_NOT_CONNECTED"
LEASE_EXPIRED = "LEASE_EXPIRED"
MIRROR_LEASE_LOST = "MIRROR_LEASE_LOST"
DRIVE_ACCOUNT_MISMATCH = "DRIVE_ACCOUNT_MISMATCH"
OPERATOR_REQUEUED = "OPERATOR_REQUEUED"

#: Rows a claimer may take at ``now``.  Retired objects are never mirrored anew.
_DUE = (
    "lifecycle_state = 'active' AND ("
    "(drive_sync_state IN ('pending','retry') "
    "AND (drive_next_attempt_at IS NULL OR drive_next_attempt_at <= ?)) "
    "OR (drive_sync_state = 'syncing' AND lease_expires_at <= ?))"
)

_CLAIM_COLUMNS = (
    "id, drive_generation, lease_token, lease_expires_at, storage_bucket, storage_key, "
    "sha256, size_bytes, mime_type, drive_file_id, drive_account_key, drive_attempts"
)


@dataclass(frozen=True)
class MirrorWork:
    """One claimed object.  ``lease_token`` is internal worker state, not a secret.

    ``attempts`` counts claims, this one included.
    """

    object_id: int
    generation: int
    lease_token: str
    lease_expires_at: str
    storage_bucket: str
    storage_key: str
    sha256: str
    size_bytes: int
    mime_type: str
    drive_file_id: str | None
    drive_account_key: str | None
    attempts: int


def _lease_seconds(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_LEASE_SECONDS:
        raise ValueError(f"lease_seconds must be 1..{MAX_LEASE_SECONDS}")
    return value


def claim_due_mirror_work(
    conn, *, limit: int, worker_token: str, now: str, lease_seconds: int = DEFAULT_LEASE_SECONDS
) -> list[MirrorWork]:
    """Lease up to ``limit`` due objects to ``worker_token`` (a fresh lease token)."""
    positive_limit(limit, MAX_CLAIM_BATCH)
    require_lease_token(worker_token)
    require_utc_text(now)
    expires = add_seconds(now, _lease_seconds(lease_seconds))
    require_write_transaction(conn)
    lock = " FOR UPDATE SKIP LOCKED" if is_postgres(conn) else ""
    ids = [
        int(row[0])
        for row in conn.execute(
            f"SELECT id FROM storage_objects WHERE {_DUE}"
            " ORDER BY COALESCE(drive_next_attempt_at, created_at), id"
            f" LIMIT ?{lock}",
            (now, now, limit),
        ).fetchall()
    ]
    claimed = []
    for object_id in ids:
        row = conn.execute(
            "UPDATE storage_objects SET drive_sync_state = 'syncing', lease_token = ?,"
            " lease_expires_at = ?, drive_generation = drive_generation + 1,"
            " drive_attempts = drive_attempts + 1, drive_last_attempt_at = ?,"
            " drive_next_attempt_at = NULL"
            f" WHERE id = ? AND {_DUE}"
            f" RETURNING {_CLAIM_COLUMNS}",
            (worker_token, expires, now, object_id, now, now),
        ).fetchone()
        if row is not None:
            claimed.append(
                MirrorWork(
                    int(row[0]), int(row[1]), str(row[2]), str(row[3]), str(row[4]), str(row[5]),
                    str(row[6]), int(row[7]), str(row[8]),
                    None if row[9] is None else str(row[9]),
                    None if row[10] is None else str(row[10]),
                    int(row[11]),
                )
            )
    return claimed


_FENCE = (
    " WHERE id = ? AND lease_token = ? AND drive_generation = ?"
    " AND drive_sync_state = 'syncing' AND lease_expires_at > ?"
)


def _fenced_update(conn, work_object_id, lease_token, generation, now, assignments, params,
                   *, extra_where="", extra_params=()) -> None:
    require_lease_token(lease_token)
    require_utc_text(now)
    require_write_transaction(conn)
    fence = (int(work_object_id), lease_token, int(generation), now)
    row = conn.execute(
        f"UPDATE storage_objects SET {assignments}, lease_token = NULL, lease_expires_at = NULL"
        f"{_FENCE}{extra_where} RETURNING id",
        (*params, *fence, *extra_params),
    ).fetchone()
    if row is None:
        if extra_where and conn.execute(f"SELECT id FROM storage_objects{_FENCE}", fence).fetchone():
            raise CustodyError(DRIVE_ACCOUNT_MISMATCH)  # live lease, different bound account
        raise CustodyError(MIRROR_LEASE_LOST)


def _account_key(value) -> str:
    try:
        return require_provider_account_key(value)
    except AccountIdentityError:
        raise ValueError("drive_account_key must be a logical provider-account key") from None


def complete_synced(
    conn,
    *,
    object_id: int,
    lease_token: str,
    generation: int,
    drive_file_id: str,
    drive_parent_id: str | None,
    drive_account_key: str,
    now: str,
) -> None:
    """``syncing`` -> ``synced`` under a live, matching lease, for the bound account.

    An object never bound before is bound to ``drive_account_key`` here; an
    object already bound to another logical account is refused
    (``DRIVE_ACCOUNT_MISMATCH``) -- never silently re-pointed.
    """
    key = _account_key(drive_account_key)
    _fenced_update(
        conn, object_id, lease_token, generation, now,
        "drive_sync_state = 'synced', drive_file_id = ?, drive_parent_id = ?,"
        " drive_account_key = ?, drive_synced_at = ?, drive_last_error_code = NULL,"
        " drive_next_attempt_at = NULL",
        (drive_file_id, drive_parent_id, key, now),
        extra_where=" AND (drive_account_key IS NULL OR drive_account_key = ?)",
        extra_params=(key,),
    )


def mark_retry(
    conn, *, object_id: int, lease_token: str, generation: int, error_code, next_attempt_at: str, now: str
) -> None:
    """``syncing`` -> ``retry`` with a sanitized code and a due time."""
    require_utc_text(next_attempt_at)
    _fenced_update(
        conn, object_id, lease_token, generation, now,
        "drive_sync_state = 'retry', drive_last_error_code = ?, drive_next_attempt_at = ?",
        (sanitize_error_code(error_code), next_attempt_at),
    )


def mark_pending_disconnected(
    conn, *, object_id: int, lease_token: str, generation: int, next_attempt_at: str, now: str,
    code: str = DRIVE_NOT_CONNECTED,
) -> None:
    """``syncing`` -> ``pending``: no usable Drive; wait, do not count as failure.

    ``code`` says why (no connection, the bound account is not the active one,
    the authorization failed mid-pass, the object was retired meanwhile).  The
    claim's attempt is given back, so waiting never exhausts the retry budget.
    """
    require_utc_text(next_attempt_at)
    _fenced_update(
        conn, object_id, lease_token, generation, now,
        "drive_sync_state = 'pending', drive_last_error_code = ?, drive_next_attempt_at = ?,"
        " drive_attempts = drive_attempts - 1",
        (sanitize_error_code(code), next_attempt_at),
    )


def mark_reconciliation_required(
    conn, *, object_id: int, lease_token: str, generation: int, error_code, now: str
) -> None:
    """``syncing`` -> ``reconciliation_required``: automatic retry is unsafe."""
    _fenced_update(
        conn, object_id, lease_token, generation, now,
        "drive_sync_state = 'reconciliation_required', drive_last_error_code = ?,"
        " drive_next_attempt_at = NULL",
        (sanitize_error_code(error_code),),
    )


def release_expired_leases(conn, *, now: str, limit: int) -> int:
    """Turn expired ``syncing`` leases into due ``retry`` rows (``LEASE_EXPIRED``)."""
    positive_limit(limit, MAX_CLAIM_BATCH)
    require_utc_text(now)
    require_write_transaction(conn)
    lock = " FOR UPDATE SKIP LOCKED" if is_postgres(conn) else ""
    ids = [
        int(row[0])
        for row in conn.execute(
            "SELECT id FROM storage_objects WHERE drive_sync_state = 'syncing'"
            f" AND lease_expires_at <= ? ORDER BY lease_expires_at, id LIMIT ?{lock}",
            (now, limit),
        ).fetchall()
    ]
    released = 0
    for object_id in ids:
        row = conn.execute(
            "UPDATE storage_objects SET drive_sync_state = 'retry', lease_token = NULL,"
            " lease_expires_at = NULL, drive_last_error_code = ?, drive_next_attempt_at = ?"
            " WHERE id = ? AND drive_sync_state = 'syncing' AND lease_expires_at <= ?"
            " RETURNING id",
            (LEASE_EXPIRED, now, object_id, now),
        ).fetchone()
        released += row is not None
    return released


def requeue_for_mirror(conn, *, now: str, limit: int, error_code: str | None = None) -> int:
    """Operator recovery: active ``reconciliation_required`` -> ``pending``, attempts reset.

    ``error_code`` restricts the batch to one failure class.  One conditional
    UPDATE: a concurrent requeue or claim re-evaluates the state predicate, so
    no object is requeued twice and no lease is ever touched.  The account
    binding is kept: an object stays bound to the logical account it was
    first mirrored to.
    """
    positive_limit(limit, MAX_REQUEUE_BATCH)
    require_utc_text(now)
    require_write_transaction(conn)
    predicate = "drive_sync_state = 'reconciliation_required' AND lifecycle_state = 'active'"
    params: tuple = ()
    if error_code is not None:
        if sanitize_error_code(error_code) != error_code:
            raise ValueError("error_code must be a sanitized code")
        predicate += " AND drive_last_error_code = ?"
        params = (error_code,)
    rows = conn.execute(
        "UPDATE storage_objects SET drive_sync_state = 'pending', drive_attempts = 0,"
        " drive_last_error_code = ?, drive_next_attempt_at = NULL"
        f" WHERE id IN (SELECT id FROM storage_objects WHERE {predicate} ORDER BY id LIMIT ?)"
        f" AND {predicate} RETURNING id",
        (OPERATOR_REQUEUED, *params, limit, *params),
    ).fetchall()
    return len(rows)


def retire_object(conn, *, object_id: int, now: str) -> None:
    """Lifecycle state only: ``active`` -> ``retired``.  Nothing is purged.

    ``purge_after`` stays NULL -- the retention policy is not decided, and no
    code path deletes a canonical object.
    """
    require_utc_text(now)
    require_write_transaction(conn)
    row = conn.execute(
        "UPDATE storage_objects SET lifecycle_state = 'retired', retired_at = ?"
        " WHERE id = ? AND lifecycle_state = 'active' RETURNING id",
        (now, int(object_id)),
    ).fetchone()
    if row is None:
        raise CustodyError("STORAGE_OBJECT_NOT_ACTIVE")


# ---------------------------------------------------------------------------
# worker health (singleton row id 1; no row = never ran)
# ---------------------------------------------------------------------------


def _count(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("counts must be non-negative integers")
    return value


def record_worker_started(conn, *, now: str) -> None:
    require_utc_text(now)
    require_write_transaction(conn)
    conn.execute(
        "INSERT INTO storage_worker_status (id, last_started_at) VALUES (1, ?)"
        " ON CONFLICT (id) DO UPDATE SET last_started_at = excluded.last_started_at,"
        " last_finished_at = NULL, last_result_code = NULL, last_claimed_count = 0,"
        " last_synced_count = 0, last_retry_count = 0",
        (now,),
    )


def record_worker_finished(
    conn, *, now: str, result_code, claimed: int, synced: int, retried: int
) -> None:
    require_utc_text(now)
    require_write_transaction(conn)
    row = conn.execute(
        "UPDATE storage_worker_status SET last_finished_at = ?, last_result_code = ?,"
        " last_claimed_count = ?, last_synced_count = ?, last_retry_count = ?"
        " WHERE id = 1 RETURNING id",
        (now, sanitize_error_code(result_code), _count(claimed), _count(synced), _count(retried)),
    ).fetchone()
    if row is None:
        raise CustodyError("WORKER_NOT_STARTED")


def read_worker_status(conn) -> dict | None:
    row = conn.execute(
        "SELECT last_started_at, last_finished_at, last_result_code, last_claimed_count,"
        " last_synced_count, last_retry_count FROM storage_worker_status WHERE id = 1"
    ).fetchone()
    if row is None:
        return None
    keys = ("last_started_at", "last_finished_at", "last_result_code",
            "last_claimed_count", "last_synced_count", "last_retry_count")
    return dict(zip(keys, tuple(row)))


__all__ = [
    "DEFAULT_LEASE_SECONDS",
    "DRIVE_ACCOUNT_MISMATCH",
    "DRIVE_NOT_CONNECTED",
    "LEASE_EXPIRED",
    "MAX_CLAIM_BATCH",
    "MAX_REQUEUE_BATCH",
    "MIRROR_LEASE_LOST",
    "MirrorWork",
    "OPERATOR_REQUEUED",
    "claim_due_mirror_work",
    "complete_synced",
    "mark_pending_disconnected",
    "mark_reconciliation_required",
    "mark_retry",
    "read_worker_status",
    "record_worker_finished",
    "record_worker_started",
    "release_expired_leases",
    "requeue_for_mirror",
    "retire_object",
]
