"""Server-issued upload intents for canonical business documents (prod-1/v14).

An intent is the durable, short-lived authorization for ONE browser upload of
ONE object straight to canonical storage (S3 wires it into the routes; S2
ships the primitives only -- no endpoint reaches them):

    issue_intent ──> issued ──mark_verified──> verified ──consume_intent──> consumed
                       │                          │
                       └──── reject_intent / expire_intents ──> rejected | expired

INVARIANTS
    * Server-chosen locator: the bucket comes from server configuration, the
      key is generated here from a 128-bit random name; the browser never
      chooses either.  The intent id is a separate 128-bit random value.
    * Bindings: actor, purpose, operation (and the optional current target --
      a request or an ARQUIVOS row) are fixed at issue and re-checked at every
      step; a wrong actor gets the same ``INTENT_NOT_FOUND`` as a wrong id.
    * One object per intent, consumed at most once: ``consume_intent`` locks
      the intent, requires ``verified`` and an unexpired window, creates the
      ``storage_objects`` row from the VERIFIED metadata and records its id.
      The v14 trigger freezes a terminal intent (except ``sweep_after``).
    * Nothing secret is stored: no signed URL, no upload token.

OPERATION IDENTITY (no parallel idempotency mechanism)
    ``operation_id`` is the existing per-file operation identity of the
    request / ARQUIVOS flows -- the value ``app.comprovantes`` and
    ``app.arquivos`` already derive from their form-issued operation id and
    store in ``operation_key`` (same 124-byte bound).  The intent stores a
    COPY as a binding; it never writes the business ``operation_key`` column
    (which also carries Google Drive ``appProperties`` semantics).  Replaying
    ``issue_intent`` with the same actor + purpose + operation and the same
    declaration returns the same live intent; any other reuse is refused.

The caller owns the transaction (``app.db.write_transaction``) and commits.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass

from app.prod1_storage_ddl import (
    BUSINESS_DOCUMENT_MAX_BYTES,
    BUSINESS_DOCUMENT_MIME_TYPES,
    INTENT_NONTERMINAL_STATES,
    INTENT_PURPOSES,
    OPERATION_ID_MAX_LENGTH,
    ORIGINAL_FILENAME_MAX_LENGTH,
    STORAGE_ORIGINS,
)
from app.storage.custody_common import (
    CustodyError,
    add_seconds,
    is_postgres,
    positive_limit,
    require_utc_text,
    require_write_transaction,
    sanitize_error_code,
)
from app.storage.supabase_store import check_locator

DEFAULT_TTL_SECONDS = 15 * 60
MAX_TTL_SECONDS = 2 * 60 * 60  # a Supabase signed upload URL lives two hours
DEFAULT_RETENTION_SECONDS = 24 * 60 * 60
MAX_SWEEP_BATCH = 500

INTENT_NOT_FOUND = "INTENT_NOT_FOUND"
INTENT_STATE_INVALID = "INTENT_STATE_INVALID"
INTENT_EXPIRED = "INTENT_EXPIRED"
INTENT_OPERATION_CONFLICT = "INTENT_OPERATION_CONFLICT"
INTENT_BINDING_MISMATCH = "INTENT_BINDING_MISMATCH"
STORAGE_INTEGRITY_MISMATCH = "STORAGE_INTEGRITY_MISMATCH"

_KEY_DIRECTORY = {"comprovante": "comprovantes", "admin_arquivo": "arquivos"}
_OPERATION_RE = re.compile(rf"^[A-Za-z0-9_.:-]{{1,{OPERATION_ID_MAX_LENGTH}}}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_COLUMNS = (
    "id", "actor_user_id", "purpose", "operation_id", "storage_bucket", "storage_key",
    "requisicao_id", "admin_arquivo_id", "original_filename", "declared_mime_type",
    "declared_size_bytes", "declared_sha256", "state", "rejection_code", "issued_at",
    "expires_at", "sweep_after", "verified_at", "consumed_at", "storage_object_id",
)


@dataclass(frozen=True)
class UploadIntent:
    id: str
    actor_user_id: int
    purpose: str
    operation_id: str
    storage_bucket: str
    storage_key: str
    requisicao_id: int | None
    admin_arquivo_id: int | None
    original_filename: str | None
    declared_mime_type: str
    declared_size_bytes: int
    declared_sha256: str
    state: str
    rejection_code: str | None
    issued_at: str
    expires_at: str
    sweep_after: str
    verified_at: str | None
    consumed_at: str | None
    storage_object_id: int | None


def _intent(row) -> UploadIntent:
    return UploadIntent(*tuple(row))


def _int_or_none(value, name):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive id")
    return value


def _load(conn, intent_id, *, lock: bool) -> UploadIntent | None:
    if not isinstance(intent_id, str) or not re.fullmatch(r"[0-9a-f]{32}", intent_id):
        return None
    suffix = " FOR UPDATE" if lock and is_postgres(conn) else ""
    row = conn.execute(
        f"SELECT {', '.join(_COLUMNS)} FROM storage_upload_intents WHERE id = ?{suffix}",
        (intent_id,),
    ).fetchone()
    return None if row is None else _intent(row)


def _owned(conn, intent_id, actor_user_id) -> UploadIntent:
    intent = _load(conn, intent_id, lock=True)
    if intent is None or intent.actor_user_id != actor_user_id:
        raise CustodyError(INTENT_NOT_FOUND)
    return intent


def issue_intent(
    conn,
    *,
    actor_user_id: int,
    purpose: str,
    operation_id: str,
    bucket: str,
    declared_mime_type: str,
    declared_size_bytes: int,
    declared_sha256: str,
    now: str,
    original_filename: str | None = None,
    requisicao_id: int | None = None,
    admin_arquivo_id: int | None = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    retention_seconds: int = DEFAULT_RETENTION_SECONDS,
) -> UploadIntent:
    """Issue (or idempotently replay) the intent for one operation."""
    _int_or_none(actor_user_id, "actor_user_id")
    if actor_user_id is None:
        raise ValueError("actor_user_id is required")
    if purpose not in INTENT_PURPOSES:
        raise ValueError("unknown intent purpose")
    if not isinstance(operation_id, str) or not _OPERATION_RE.fullmatch(operation_id):
        raise ValueError("invalid operation id")
    if declared_mime_type not in BUSINESS_DOCUMENT_MIME_TYPES:
        raise ValueError("unsupported business document type")
    if (
        isinstance(declared_size_bytes, bool)
        or not isinstance(declared_size_bytes, int)
        or not 0 < declared_size_bytes <= BUSINESS_DOCUMENT_MAX_BYTES
    ):
        raise ValueError("declared size outside the business document limit")
    if not isinstance(declared_sha256, str) or not _SHA256_RE.fullmatch(declared_sha256):
        raise ValueError("declared sha256 must be 64 lowercase hex")
    if original_filename is not None and not (
        isinstance(original_filename, str) and 1 <= len(original_filename) <= ORIGINAL_FILENAME_MAX_LENGTH
    ):
        raise ValueError("invalid original filename")
    _int_or_none(requisicao_id, "requisicao_id")
    _int_or_none(admin_arquivo_id, "admin_arquivo_id")
    if purpose != "comprovante" and requisicao_id is not None:
        raise ValueError("only a comprovante intent binds a request")
    if purpose != "admin_arquivo" and admin_arquivo_id is not None:
        raise ValueError("only an ARQUIVOS intent binds an ARQUIVOS row")
    if not isinstance(ttl_seconds, int) or not 1 <= ttl_seconds <= MAX_TTL_SECONDS:
        raise ValueError("ttl_seconds out of range")
    if not isinstance(retention_seconds, int) or retention_seconds < 0:
        raise ValueError("retention_seconds must be >= 0")
    require_utc_text(now)
    require_write_transaction(conn)

    intent_id = secrets.token_hex(16)
    key = f"{_KEY_DIRECTORY[purpose]}/{now[0:4]}/{now[5:7]}/{secrets.token_hex(16)}"
    check_locator(bucket, key)
    expires_at = add_seconds(now, ttl_seconds)
    sweep_after = add_seconds(expires_at, retention_seconds)
    row = conn.execute(
        "INSERT INTO storage_upload_intents (id, actor_user_id, purpose, operation_id,"
        " storage_bucket, storage_key, requisicao_id, admin_arquivo_id, original_filename,"
        " declared_mime_type, declared_size_bytes, declared_sha256, state, issued_at,"
        " expires_at, sweep_after) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'issued', ?, ?, ?)"
        " ON CONFLICT (actor_user_id, purpose, operation_id) DO NOTHING RETURNING id",
        (
            intent_id, actor_user_id, purpose, operation_id, bucket, key, requisicao_id,
            admin_arquivo_id, original_filename, declared_mime_type, declared_size_bytes,
            declared_sha256, now, expires_at, sweep_after,
        ),
    ).fetchone()
    if row is not None:
        return _load(conn, str(row[0]), lock=False)

    lock = " FOR UPDATE" if is_postgres(conn) else ""
    existing = conn.execute(
        f"SELECT {', '.join(_COLUMNS)} FROM storage_upload_intents"
        f" WHERE actor_user_id = ? AND purpose = ? AND operation_id = ?{lock}",
        (actor_user_id, purpose, operation_id),
    ).fetchone()
    if existing is None:  # pragma: no cover - the conflicting row cannot vanish under the lock
        raise CustodyError(INTENT_OPERATION_CONFLICT)
    intent = _intent(existing)
    same = (
        intent.storage_bucket, intent.declared_mime_type, intent.declared_size_bytes,
        intent.declared_sha256, intent.original_filename, intent.requisicao_id,
        intent.admin_arquivo_id,
    ) == (
        bucket, declared_mime_type, declared_size_bytes, declared_sha256, original_filename,
        requisicao_id, admin_arquivo_id,
    )
    if same and intent.state in INTENT_NONTERMINAL_STATES and intent.expires_at > now:
        return intent
    raise CustodyError(INTENT_OPERATION_CONFLICT)


def mark_verified(
    conn,
    *,
    intent_id: str,
    actor_user_id: int,
    observed_size_bytes: int,
    observed_sha256: str,
    now: str,
) -> UploadIntent:
    """Record the server-side verification of the uploaded bytes.

    Matching size and SHA-256 -> ``verified``; any difference -> ``rejected``
    with ``STORAGE_INTEGRITY_MISMATCH`` (returned, so the caller can commit the
    rejection).  An expired window raises ``INTENT_EXPIRED``.
    """
    require_utc_text(now)
    require_write_transaction(conn)
    intent = _owned(conn, intent_id, actor_user_id)
    if intent.state != "issued":
        raise CustodyError(INTENT_STATE_INVALID)
    if intent.expires_at <= now:
        raise CustodyError(INTENT_EXPIRED)
    if (observed_size_bytes, observed_sha256) == (intent.declared_size_bytes, intent.declared_sha256):
        conn.execute(
            "UPDATE storage_upload_intents SET state = 'verified', verified_at = ? WHERE id = ?",
            (now, intent.id),
        )
    else:
        conn.execute(
            "UPDATE storage_upload_intents SET state = 'rejected', rejection_code = ? WHERE id = ?",
            (STORAGE_INTEGRITY_MISMATCH, intent.id),
        )
    return _load(conn, intent.id, lock=False)


def consume_intent(
    conn,
    *,
    intent_id: str,
    actor_user_id: int,
    purpose: str,
    operation_id: str,
    now: str,
    origin: str = "direct_upload",
) -> tuple[UploadIntent, int]:
    """Create the one ``storage_objects`` row of a verified intent; consume it once."""
    if origin not in STORAGE_ORIGINS:
        raise ValueError("unknown storage origin")
    require_utc_text(now)
    require_write_transaction(conn)
    intent = _owned(conn, intent_id, actor_user_id)
    if (intent.purpose, intent.operation_id) != (purpose, operation_id):
        raise CustodyError(INTENT_BINDING_MISMATCH)
    if intent.state != "verified":
        raise CustodyError(INTENT_STATE_INVALID)
    if intent.expires_at <= now:
        raise CustodyError(INTENT_EXPIRED)
    object_row = conn.execute(
        "INSERT INTO storage_objects (storage_backend, storage_bucket, storage_key, sha256,"
        " size_bytes, mime_type, uploader_user_id, origin, content_verified_at, created_at)"
        " VALUES ('supabase', ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
        (
            intent.storage_bucket, intent.storage_key, intent.declared_sha256,
            intent.declared_size_bytes, intent.declared_mime_type, intent.actor_user_id,
            origin, intent.verified_at, now,
        ),
    ).fetchone()
    object_id = int(object_row[0])
    conn.execute(
        "UPDATE storage_upload_intents SET state = 'consumed', consumed_at = ?,"
        " storage_object_id = ? WHERE id = ? AND state = 'verified'",
        (now, object_id, intent.id),
    )
    return _load(conn, intent.id, lock=False), object_id


def reject_intent(conn, *, intent_id: str, rejection_code, now: str) -> UploadIntent:
    require_utc_text(now)
    require_write_transaction(conn)
    intent = _load(conn, intent_id, lock=True)
    if intent is None:
        raise CustodyError(INTENT_NOT_FOUND)
    if intent.state not in INTENT_NONTERMINAL_STATES:
        raise CustodyError(INTENT_STATE_INVALID)
    conn.execute(
        "UPDATE storage_upload_intents SET state = 'rejected', rejection_code = ? WHERE id = ?",
        (sanitize_error_code(rejection_code), intent.id),
    )
    return _load(conn, intent.id, lock=False)


def expire_intents(conn, *, now: str, limit: int = MAX_SWEEP_BATCH) -> int:
    """Mark live intents whose window closed as ``expired``; returns the count."""
    positive_limit(limit, MAX_SWEEP_BATCH)
    require_utc_text(now)
    require_write_transaction(conn)
    lock = " FOR UPDATE SKIP LOCKED" if is_postgres(conn) else ""
    ids = [
        str(row[0])
        for row in conn.execute(
            "SELECT id FROM storage_upload_intents WHERE state IN ('issued','verified')"
            f" AND expires_at <= ? ORDER BY expires_at, id LIMIT ?{lock}",
            (now, limit),
        ).fetchall()
    ]
    for intent_id in ids:
        conn.execute(
            "UPDATE storage_upload_intents SET state = 'expired' WHERE id = ?"
            " AND state IN ('issued','verified')",
            (intent_id,),
        )
    return len(ids)


def sweep_intents(conn, *, now: str, limit: int = MAX_SWEEP_BATCH) -> int:
    """Delete terminal intents past ``sweep_after``.  Never touches an object."""
    positive_limit(limit, MAX_SWEEP_BATCH)
    require_utc_text(now)
    require_write_transaction(conn)
    ids = [
        str(row[0])
        for row in conn.execute(
            "SELECT id FROM storage_upload_intents WHERE state IN ('consumed','rejected','expired')"
            " AND sweep_after <= ? ORDER BY sweep_after, id LIMIT ?",
            (now, limit),
        ).fetchall()
    ]
    for intent_id in ids:
        conn.execute("DELETE FROM storage_upload_intents WHERE id = ?", (intent_id,))
    return len(ids)


def count_nonterminal_intents(conn) -> int:
    """Live (issued / verified) intents -- must be zero at a cutover freeze."""
    return int(
        conn.execute(
            "SELECT count(*) FROM storage_upload_intents WHERE state IN ('issued','verified')"
        ).fetchone()[0]
    )


__all__ = [
    "DEFAULT_TTL_SECONDS",
    "INTENT_BINDING_MISMATCH",
    "INTENT_EXPIRED",
    "INTENT_NOT_FOUND",
    "INTENT_OPERATION_CONFLICT",
    "INTENT_STATE_INVALID",
    "UploadIntent",
    "consume_intent",
    "count_nonterminal_intents",
    "expire_intents",
    "issue_intent",
    "mark_verified",
    "reject_intent",
    "sweep_intents",
]
