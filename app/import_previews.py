"""Server-side state of a pending administrator import preview.

An import is two requests: the first validates an upload and shows what would
change; the second, with the returned key, applies it.  The state between them
used to be a JSON file under the upload folder, which a runtime with no
durable disk (or more than one instance) cannot keep.  It is a row of
``admin_import_previews`` (schema v16) instead.

The key handed to the browser is an unguessable token; only its SHA-256 is
stored.  A preview belongs to the administrator who generated it, expires
after ``TTL_SECONDS`` and is consumed by applying it: ``claim`` deletes the row
inside the import's own transaction, so exactly one of two simultaneous
confirmations applies and a rolled-back import leaves the preview in place.
Expired rows are pruned, a bounded batch at a time, whenever a new preview is
stored.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import secrets

from app.db import skip_locked, write_transaction
from app.prod1_ephemeral_state_ddl import IMPORT_PREVIEW_PAYLOAD_MAX_BYTES
from app.storage import custody_common

TTL_SECONDS = 3600
PRUNE_BATCH = 100
_TOKEN_BYTES = 24


class PreviewTooLarge(ValueError):
    """The preview payload exceeds what one preview may hold."""


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _well_formed(token: str) -> bool:
    return isinstance(token, str) and 16 <= len(token) <= 128 and token.isascii()


def store(conn, *, usuario_id: int, payload: dict, now: datetime.datetime | None = None) -> str:
    """Persist the payload for ``usuario_id``; returns the key to hand to the browser."""
    now = now or custody_common.utc_now()
    encoded = json.dumps(payload, ensure_ascii=False)
    if len(encoded.encode("utf-8")) > IMPORT_PREVIEW_PAYLOAD_MAX_BYTES:
        raise PreviewTooLarge("the import preview is too large to hold")
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    with write_transaction(conn):
        conn.execute(
            "DELETE FROM admin_import_previews WHERE token_digest IN ("
            " SELECT token_digest FROM admin_import_previews WHERE expires_at <= ?"
            f" ORDER BY expires_at, token_digest LIMIT ?{skip_locked(conn)})",
            (custody_common.utc_text(now), PRUNE_BATCH),
        )
        conn.execute(
            "INSERT INTO admin_import_previews(token_digest, usuario_id, payload, created_at, expires_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (_digest(token), int(usuario_id), encoded, custody_common.utc_text(now),
             custody_common.utc_text(now + datetime.timedelta(seconds=TTL_SECONDS))),
        )
    return token


def load(conn, *, usuario_id: int, token: str, now: datetime.datetime | None = None) -> dict | None:
    """The payload, or ``None`` when the key is unknown, expired or another administrator's."""
    if not _well_formed(token):
        return None
    row = conn.execute(
        "SELECT payload FROM admin_import_previews"
        " WHERE token_digest = ? AND usuario_id = ? AND expires_at > ?",
        (_digest(token), int(usuario_id), custody_common.utc_text(now or custody_common.utc_now())),
    ).fetchone()
    if row is None:
        return None
    payload = json.loads(row[0])
    return payload if isinstance(payload, dict) else None


def claim(conn, *, usuario_id: int, token: str, now: datetime.datetime | None = None) -> bool:
    """Consume the preview inside the CALLER's write transaction.

    ``True`` only for the one caller whose statement deleted the row (a concurrent
    confirmation, an expired, unknown or foreign key all get ``False``).  It opens
    no transaction of its own: the claim commits or rolls back with the import.
    """
    custody_common.require_write_transaction(conn)
    if not _well_formed(token):
        return False
    row = conn.execute(
        "DELETE FROM admin_import_previews"
        " WHERE token_digest = ? AND usuario_id = ? AND expires_at > ? RETURNING token_digest",
        (_digest(token), int(usuario_id), custody_common.utc_text(now or custody_common.utc_now())),
    ).fetchone()
    return row is not None


def discard(conn, *, usuario_id: int, token: str) -> None:
    if not _well_formed(token):
        return
    with write_transaction(conn):
        conn.execute(
            "DELETE FROM admin_import_previews WHERE token_digest = ? AND usuario_id = ?",
            (_digest(token), int(usuario_id)),
        )


__all__ = ["PRUNE_BATCH", "PreviewTooLarge", "TTL_SECONDS", "claim", "discard", "load", "store"]
