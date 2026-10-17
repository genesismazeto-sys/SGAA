"""Per-provider document copies and the Supabase staging state (PostgreSQL ``sgaa_ops``).

Google Drive and OneDrive hold the permanent copies of business documents;
Supabase Storage is the upload staging area and the durable fallback.  The
Google copy keeps its proven outbox on ``storage_objects`` (``mirror_outbox``).
This module records the rest, in the hosted control schema ``sgaa_ops`` that
the hosted backup already owns (``app.backup.pg_posture``) -- operational
state outside the versioned application schema, created idempotently on first
use, PostgreSQL only (the local SQLite runtime keeps its single Google mirror):

    storage_copies     the OneDrive copy of an object: the same state machine,
                       lease fence and account binding as the Google mirror
                       (``mirror_outbox``), plus ``verified_at`` -- the last
                       full read-back that proved the copy byte for byte
    storage_staging    an object whose Supabase copy is temporary:
                       ``staged`` -> ``releasing`` -> ``released``
    storage_copy_meta  the activation: objects uploaded from then on are
                       enrolled automatically; older ones only by the
                       operator's bounded backfill (``staging_release``)

An object without a ``storage_staging`` row keeps its Supabase copy for good.
``releasing`` means the Supabase copy is no longer relied on (readers go to the
verified provider copies) and its removal may be in progress or repeated.

The surface the Drive mirror worker drives is ``mirror_outbox``'s (claim,
fenced completion, retry, defer, reconcile, expired leases), so the one worker
runs both providers; the error codes are ``mirror_outbox``'s.  The caller owns
the transaction.
"""

from __future__ import annotations

from app.backup import pg_posture
from app.cloud_account_identity import AccountIdentityError, require_provider_account_key
from app.db import write_transaction
from app.storage.custody_common import (
    CustodyError,
    add_seconds,
    is_postgres,
    positive_limit,
    require_lease_token,
    require_utc_text,
    require_write_transaction,
    sanitize_error_code,
)
from app.storage.mirror_outbox import (
    DEFAULT_LEASE_SECONDS,
    DRIVE_ACCOUNT_MISMATCH,
    DRIVE_NOT_CONNECTED,
    LEASE_EXPIRED,
    MAX_CLAIM_BATCH,
    MAX_LEASE_SECONDS,
    MIRROR_LEASE_LOST,
    MirrorWork,
)

PROVIDER = "onedrive"
REGISTRY_UNAVAILABLE = "COPY_REGISTRY_UNAVAILABLE"
MAX_ENROLL_BATCH = 1000
STAGED, RELEASING, RELEASED = "staged", "releasing", "released"

DDL = (
    *pg_posture.SCHEMA_DDL,
    "CREATE TABLE IF NOT EXISTS sgaa_ops.storage_copy_meta ("
    " id smallint PRIMARY KEY CHECK (id = 1), activated_at text NOT NULL, first_object_id bigint NOT NULL)",
    "CREATE TABLE IF NOT EXISTS sgaa_ops.storage_staging ("
    " object_id bigint PRIMARY KEY,"
    " state text NOT NULL CHECK (state IN ('staged','releasing','released')),"
    " enrolled_at text NOT NULL, released_at text, verified_providers text,"
    " CHECK ((state = 'staged') = (released_at IS NULL)))",
    "CREATE TABLE IF NOT EXISTS sgaa_ops.storage_copies ("
    " object_id bigint NOT NULL, provider text NOT NULL CHECK (provider = 'onedrive'),"
    " sync_state text NOT NULL DEFAULT 'pending'"
    " CHECK (sync_state IN ('pending','syncing','synced','retry','reconciliation_required')),"
    " generation integer NOT NULL DEFAULT 0, lease_token text, lease_expires_at text,"
    " attempts integer NOT NULL DEFAULT 0, next_attempt_at text, last_attempt_at text, last_error_code text,"
    " file_id text, parent_id text, account_key text, synced_at text, verified_at text,"
    " PRIMARY KEY (object_id, provider),"
    " CHECK ((sync_state = 'syncing') = (lease_token IS NOT NULL)),"
    " CHECK (sync_state <> 'synced' OR (file_id IS NOT NULL AND account_key IS NOT NULL"
    " AND synced_at IS NOT NULL)))",
    "CREATE INDEX IF NOT EXISTS storage_copies_due ON sgaa_ops.storage_copies (sync_state, next_attempt_at)",
    "REVOKE ALL ON sgaa_ops.storage_copy_meta, sgaa_ops.storage_staging, sgaa_ops.storage_copies FROM PUBLIC",
)
_TABLES = ("sgaa_ops.storage_copy_meta", "sgaa_ops.storage_staging", "sgaa_ops.storage_copies")


# ---------------------------------------------------------------------------
# presence, activation, enrollment
# ---------------------------------------------------------------------------


def available(conn) -> bool:
    """Whether the registry exists on this connection (never creates it: the web runtime reads only)."""
    if not is_postgres(conn):
        return False
    row = conn.execute("SELECT to_regclass('sgaa_ops.storage_staging') IS NOT NULL").fetchone()
    return bool(row[0])


def prepare(conn, *, now: str) -> bool:
    """Create the registry if needed, record the activation, enroll new uploads.

    ``False`` when the database is not PostgreSQL.  Background tools only.
    """
    if not is_postgres(conn):
        return False
    if not all(conn.execute("SELECT to_regclass(?) IS NOT NULL", (name,)).fetchone()[0] for name in _TABLES):
        conn.commit()  # the DDL runs in its own transactions on the raw connection
        pg_posture.run_ddl(conn.raw_connection, DDL)
    with write_transaction(conn):
        conn.execute(
            "INSERT INTO sgaa_ops.storage_copy_meta (id, activated_at, first_object_id)"
            " SELECT 1, ?, COALESCE(MAX(id), 0) + 1 FROM storage_objects ON CONFLICT (id) DO NOTHING",
            (require_utc_text(now),),
        )
        _enroll(
            conn,
            "SELECT o.id FROM storage_objects o JOIN sgaa_ops.storage_copy_meta m ON m.id = 1"
            " WHERE o.id >= m.first_object_id AND o.origin = 'direct_upload' AND o.lifecycle_state = 'active'"
            " AND NOT EXISTS (SELECT 1 FROM sgaa_ops.storage_staging s WHERE s.object_id = o.id)"
            " ORDER BY o.id LIMIT ?",
            (MAX_ENROLL_BATCH,), now,
        )
    return True


def _enroll(conn, select_sql: str, params: tuple, now: str) -> list[int]:
    ids = [int(row[0]) for row in conn.execute(select_sql, params).fetchall()]
    for object_id in ids:
        conn.execute(
            "INSERT INTO sgaa_ops.storage_staging (object_id, state, enrolled_at) VALUES (?, 'staged', ?)"
            " ON CONFLICT (object_id) DO NOTHING",
            (object_id, now),
        )
        conn.execute(
            "INSERT INTO sgaa_ops.storage_copies (object_id, provider) VALUES (?, ?)"
            " ON CONFLICT (object_id, provider) DO NOTHING",
            (object_id, PROVIDER),
        )
    return ids


_UNENROLLED = (
    "SELECT o.id FROM storage_objects o WHERE o.lifecycle_state = 'active'"
    " AND NOT EXISTS (SELECT 1 FROM sgaa_ops.storage_staging s WHERE s.object_id = o.id)"
)


def count_unenrolled(conn) -> int:
    return int(conn.execute(f"SELECT count(*) FROM ({_UNENROLLED}) u").fetchone()[0])


def enroll_existing(conn, *, limit: int, now: str) -> list[int]:
    """Operator backfill: the next ``limit`` active objects that keep a durable Supabase copy
    become staged -- copied to every connected drive, then released once verified."""
    positive_limit(limit, MAX_ENROLL_BATCH)
    require_utc_text(now)
    require_write_transaction(conn)
    return _enroll(conn, _UNENROLLED + " ORDER BY o.id LIMIT ?", (limit,), now)


# ---------------------------------------------------------------------------
# staging state
# ---------------------------------------------------------------------------


def staging_state(conn, object_id: int) -> str | None:
    """``staged`` / ``releasing`` / ``released``; ``None``: a durable Supabase copy (or no registry)."""
    if not available(conn):
        return None
    row = conn.execute(
        "SELECT state FROM sgaa_ops.storage_staging WHERE object_id = ?", (int(object_id),)
    ).fetchone()
    return None if row is None else str(row[0])


def supabase_released(conn, object_id: int) -> bool:
    return staging_state(conn, object_id) in (RELEASING, RELEASED)


def released_object_ids(conn) -> set[int]:
    """Every object whose Supabase copy is no longer relied on (for whole-store tools)."""
    if not available(conn):
        return set()
    return {int(row[0]) for row in conn.execute(
        "SELECT object_id FROM sgaa_ops.storage_staging WHERE state IN ('releasing','released')"
    ).fetchall()}


def staged_objects(conn, *, limit: int) -> list[int]:
    positive_limit(limit, MAX_ENROLL_BATCH)
    return [int(row[0]) for row in conn.execute(
        "SELECT s.object_id FROM sgaa_ops.storage_staging s JOIN storage_objects o ON o.id = s.object_id"
        " WHERE s.state = 'staged' AND o.lifecycle_state = 'active' ORDER BY s.object_id LIMIT ?",
        (limit,),
    ).fetchall()]


def releasing_objects(conn, *, limit: int) -> list[int]:
    positive_limit(limit, MAX_ENROLL_BATCH)
    return [int(row[0]) for row in conn.execute(
        "SELECT object_id FROM sgaa_ops.storage_staging WHERE state = 'releasing' ORDER BY object_id LIMIT ?",
        (limit,),
    ).fetchall()]


def mark_releasing(conn, *, object_id: int, providers: list[str], now: str) -> bool:
    """``staged`` -> ``releasing``: from now on no reader relies on the Supabase copy."""
    require_utc_text(now)
    require_write_transaction(conn)
    row = conn.execute(
        "UPDATE sgaa_ops.storage_staging SET state = 'releasing', released_at = ?, verified_providers = ?"
        " WHERE object_id = ? AND state = 'staged' RETURNING object_id",
        (now, ",".join(sorted(providers)), int(object_id)),
    ).fetchone()
    if row is not None and PROVIDER in providers:
        conn.execute(
            "UPDATE sgaa_ops.storage_copies SET verified_at = ? WHERE object_id = ? AND provider = ?",
            (now, int(object_id), PROVIDER),
        )
    return row is not None


def mark_released(conn, *, object_id: int) -> None:
    """``releasing`` -> ``released``: the Supabase copy is gone."""
    require_write_transaction(conn)
    conn.execute(
        "UPDATE sgaa_ops.storage_staging SET state = 'released' WHERE object_id = ? AND state = 'releasing'",
        (int(object_id),),
    )


# ---------------------------------------------------------------------------
# the OneDrive copy: mirror_outbox's state machine over sgaa_ops.storage_copies
# ---------------------------------------------------------------------------


def synced_copy(conn, object_id: int) -> tuple[str, str] | None:
    """``(file_id, account_key)`` of a synced OneDrive copy, else ``None``."""
    if not available(conn):
        return None
    row = conn.execute(
        "SELECT file_id, account_key FROM sgaa_ops.storage_copies"
        " WHERE object_id = ? AND provider = ? AND sync_state = 'synced'",
        (int(object_id), PROVIDER),
    ).fetchone()
    return None if row is None else (str(row[0]), str(row[1]))


_DUE = (
    "c.provider = 'onedrive' AND o.lifecycle_state = 'active' AND ("
    "(c.sync_state IN ('pending','retry') AND (c.next_attempt_at IS NULL OR c.next_attempt_at <= ?))"
    " OR (c.sync_state = 'syncing' AND c.lease_expires_at <= ?))"
)


def claim_due_mirror_work(conn, *, limit: int, worker_token: str, now: str,
                          lease_seconds: int = DEFAULT_LEASE_SECONDS) -> list[MirrorWork]:
    positive_limit(limit, MAX_CLAIM_BATCH)
    require_lease_token(worker_token)
    require_utc_text(now)
    if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, int) \
            or not 1 <= lease_seconds <= MAX_LEASE_SECONDS:
        raise ValueError(f"lease_seconds must be 1..{MAX_LEASE_SECONDS}")
    require_write_transaction(conn)
    expires = add_seconds(now, lease_seconds)
    ids = [int(row[0]) for row in conn.execute(
        "SELECT c.object_id FROM sgaa_ops.storage_copies c JOIN storage_objects o ON o.id = c.object_id"
        f" WHERE {_DUE} ORDER BY COALESCE(c.next_attempt_at, o.created_at), c.object_id"
        " LIMIT ? FOR UPDATE OF c SKIP LOCKED",
        (now, now, limit),
    ).fetchall()]
    claimed = []
    for object_id in ids:
        row = conn.execute(
            "UPDATE sgaa_ops.storage_copies c SET sync_state = 'syncing', lease_token = ?, lease_expires_at = ?,"
            " generation = c.generation + 1, attempts = c.attempts + 1, last_attempt_at = ?,"
            " next_attempt_at = NULL FROM storage_objects o"
            f" WHERE o.id = c.object_id AND c.object_id = ? AND {_DUE}"
            " RETURNING c.object_id, c.generation, c.lease_token, c.lease_expires_at, o.storage_bucket,"
            " o.storage_key, o.sha256, o.size_bytes, o.mime_type, c.file_id, c.account_key, c.attempts",
            (worker_token, expires, now, object_id, now, now),
        ).fetchone()
        if row is not None:
            claimed.append(MirrorWork(
                int(row[0]), int(row[1]), str(row[2]), str(row[3]), str(row[4]), str(row[5]), str(row[6]),
                int(row[7]), str(row[8]), None if row[9] is None else str(row[9]),
                None if row[10] is None else str(row[10]), int(row[11]),
            ))
    return claimed


_FENCE = (
    " WHERE object_id = ? AND provider = 'onedrive' AND lease_token = ? AND generation = ?"
    " AND sync_state = 'syncing' AND lease_expires_at > ?"
)


def _fenced_update(conn, object_id, lease_token, generation, now, assignments, params,
                   *, extra_where="", extra_params=()) -> None:
    require_lease_token(lease_token)
    require_utc_text(now)
    require_write_transaction(conn)
    fence = (int(object_id), lease_token, int(generation), now)
    row = conn.execute(
        f"UPDATE sgaa_ops.storage_copies SET {assignments}, lease_token = NULL, lease_expires_at = NULL"
        f"{_FENCE}{extra_where} RETURNING object_id",
        (*params, *fence, *extra_params),
    ).fetchone()
    if row is None:
        if extra_where and conn.execute(f"SELECT object_id FROM sgaa_ops.storage_copies{_FENCE}", fence).fetchone():
            raise CustodyError(DRIVE_ACCOUNT_MISMATCH)
        raise CustodyError(MIRROR_LEASE_LOST)


def complete_synced(conn, *, object_id: int, lease_token: str, generation: int, drive_file_id: str,
                    drive_parent_id: str | None, drive_account_key: str, now: str) -> None:
    """``syncing`` -> ``synced`` for the bound account; another bound account is refused."""
    try:
        key = require_provider_account_key(drive_account_key)
    except AccountIdentityError:
        raise ValueError("drive_account_key must be a logical provider-account key") from None
    _fenced_update(
        conn, object_id, lease_token, generation, now,
        "sync_state = 'synced', file_id = ?, parent_id = ?, account_key = ?, synced_at = ?,"
        " last_error_code = NULL, next_attempt_at = NULL",
        (drive_file_id, drive_parent_id, key, now),
        extra_where=" AND (account_key IS NULL OR account_key = ?)", extra_params=(key,),
    )


def mark_retry(conn, *, object_id: int, lease_token: str, generation: int, error_code, next_attempt_at: str,
               now: str) -> None:
    require_utc_text(next_attempt_at)
    _fenced_update(conn, object_id, lease_token, generation, now,
                   "sync_state = 'retry', last_error_code = ?, next_attempt_at = ?",
                   (sanitize_error_code(error_code), next_attempt_at))


def mark_pending_disconnected(conn, *, object_id: int, lease_token: str, generation: int, next_attempt_at: str,
                              now: str, code: str = DRIVE_NOT_CONNECTED) -> None:
    """``syncing`` -> ``pending`` without spending the attempt (no usable OneDrive)."""
    require_utc_text(next_attempt_at)
    _fenced_update(conn, object_id, lease_token, generation, now,
                   "sync_state = 'pending', last_error_code = ?, next_attempt_at = ?, attempts = attempts - 1",
                   (sanitize_error_code(code), next_attempt_at))


def mark_reconciliation_required(conn, *, object_id: int, lease_token: str, generation: int, error_code,
                                 now: str) -> None:
    _fenced_update(conn, object_id, lease_token, generation, now,
                   "sync_state = 'reconciliation_required', last_error_code = ?, next_attempt_at = NULL",
                   (sanitize_error_code(error_code),))


def release_expired_leases(conn, *, now: str, limit: int) -> int:
    positive_limit(limit, MAX_CLAIM_BATCH)
    require_utc_text(now)
    require_write_transaction(conn)
    rows = conn.execute(
        "UPDATE sgaa_ops.storage_copies SET sync_state = 'retry', lease_token = NULL, lease_expires_at = NULL,"
        " last_error_code = ?, next_attempt_at = ? WHERE (object_id, provider) IN ("
        " SELECT object_id, provider FROM sgaa_ops.storage_copies WHERE sync_state = 'syncing'"
        " AND lease_expires_at <= ? ORDER BY lease_expires_at, object_id LIMIT ? FOR UPDATE SKIP LOCKED)"
        " AND sync_state = 'syncing' AND lease_expires_at <= ? RETURNING object_id",
        (LEASE_EXPIRED, now, now, limit, now),
    ).fetchall()
    return len(rows)


def reset_missing_copy(conn, *, object_id: int, file_id: str, error_code: str, now: str) -> int:
    """``synced`` -> ``pending`` when the recorded copy is gone or divergent (binding kept)."""
    require_utc_text(now)
    require_write_transaction(conn)
    if sanitize_error_code(error_code) != error_code:
        raise ValueError("error_code must be a sanitized code")
    return len(conn.execute(
        "UPDATE sgaa_ops.storage_copies SET sync_state = 'pending', file_id = NULL, parent_id = NULL,"
        " synced_at = NULL, verified_at = NULL, attempts = 0, last_error_code = ?, next_attempt_at = NULL"
        " WHERE object_id = ? AND provider = ? AND sync_state = 'synced' AND file_id = ? RETURNING object_id",
        (error_code, int(object_id), PROVIDER, str(file_id)),
    ).fetchall())



__all__ = [
    "DDL",
    "PROVIDER",
    "REGISTRY_UNAVAILABLE",
    "available",
    "claim_due_mirror_work",
    "complete_synced",
    "count_unenrolled",
    "enroll_existing",
    "mark_pending_disconnected",
    "mark_reconciliation_required",
    "mark_released",
    "mark_releasing",
    "mark_retry",
    "prepare",
    "release_expired_leases",
    "released_object_ids",
    "releasing_objects",
    "reset_missing_copy",
    "staged_objects",
    "staging_state",
    "supabase_released",
    "synced_copy",
]
