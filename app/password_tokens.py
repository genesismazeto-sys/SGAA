from __future__ import annotations

import datetime as dt
import hashlib
import re
import secrets
from dataclasses import dataclass

from app.user_accounts import CREDENTIAL_STATE_PERSONAL, first_access_redeemable


PURPOSE_FIRST_ACCESS = "first_access"
PURPOSE_PASSWORD_RESET = "password_reset"
PASSWORD_TOKEN_PURPOSES = frozenset({PURPOSE_FIRST_ACCESS, PURPOSE_PASSWORD_RESET})

FIRST_ACCESS_TTL = dt.timedelta(hours=72)
PASSWORD_RESET_TTL = dt.timedelta(minutes=60)
PASSWORD_TOKEN_TTLS = {
    PURPOSE_FIRST_ACCESS: FIRST_ACCESS_TTL,
    PURPOSE_PASSWORD_RESET: PASSWORD_RESET_TTL,
}

_RAW_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{40,64}$")


class PasswordTokenError(RuntimeError):
    pass


@dataclass(frozen=True)
class PasswordTokenRecord:
    id: int
    usuario_id: int
    purpose: str
    expires_at: str
    credential_state: str
    auth_version: int
    nome: str
    email: str


def _utc_now(now: dt.datetime | None = None) -> dt.datetime:
    value = now or dt.datetime.now(dt.timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc).replace(microsecond=0)


def _db_timestamp(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def password_token_digest(raw_token: str) -> str:
    return hashlib.sha256(str(raw_token or "").encode("utf-8")).hexdigest()


def _valid_raw_token(raw_token: str) -> bool:
    return bool(_RAW_TOKEN_RE.fullmatch(str(raw_token or "")))


def issue_password_token(
    conn,
    usuario_id: int,
    purpose: str,
    *,
    now: dt.datetime | None = None,
    ttl: dt.timedelta | None = None,
    token_factory=secrets.token_urlsafe,
) -> tuple[str, int]:
    if purpose not in PASSWORD_TOKEN_PURPOSES:
        raise ValueError(f"invalid password token purpose: {purpose!r}")
    current = _utc_now(now)
    expires = current + (ttl or PASSWORD_TOKEN_TTLS[purpose])
    raw_token = str(token_factory(32))
    if not _valid_raw_token(raw_token):
        raise PasswordTokenError("generated password token has an invalid shape")

    current_text = _db_timestamp(current)
    conn.execute(
        """
        UPDATE senha_tokens
           SET invalidated_at=?
         WHERE usuario_id=? AND purpose=?
           AND consumed_at IS NULL AND invalidated_at IS NULL
           AND expires_at>?
        """,
        (current_text, int(usuario_id), purpose, current_text),
    )
    cursor = conn.execute(
        """
        INSERT INTO senha_tokens(
            usuario_id,purpose,token_hash,created_at,expires_at
        ) VALUES(?,?,?,?,?)
        """,
        (
            int(usuario_id),
            purpose,
            password_token_digest(raw_token),
            current_text,
            _db_timestamp(expires),
        ),
    )
    return raw_token, int(cursor.lastrowid)


def resolve_password_token(
    conn,
    raw_token: str,
    *,
    purpose: str | None = None,
    now: dt.datetime | None = None,
) -> PasswordTokenRecord | None:
    if purpose is not None and purpose not in PASSWORD_TOKEN_PURPOSES:
        raise ValueError(f"invalid password token purpose: {purpose!r}")
    if not _valid_raw_token(raw_token):
        return None
    params: list[object] = [password_token_digest(raw_token), _db_timestamp(_utc_now(now))]
    purpose_sql = ""
    if purpose is not None:
        purpose_sql = " AND t.purpose=?"
        params.append(purpose)
    row = conn.execute(
        f"""
        SELECT t.id,t.usuario_id,t.purpose,t.expires_at,
               c.estado,c.auth_version,u.nome,u.email
          FROM senha_tokens t
          JOIN usuarios u ON u.id=t.usuario_id
          JOIN usuario_credenciais c ON c.usuario_id=t.usuario_id
         WHERE t.token_hash=?
           AND t.expires_at>?
           AND t.consumed_at IS NULL
           AND t.invalidated_at IS NULL
           {purpose_sql}
         LIMIT 1
        """,
        params,
    ).fetchone()
    if row is None:
        return None
    return PasswordTokenRecord(
        id=int(row[0]),
        usuario_id=int(row[1]),
        purpose=str(row[2]),
        expires_at=str(row[3]),
        credential_state=str(row[4]),
        auth_version=int(row[5]),
        nome=str(row[6] or ""),
        email=str(row[7] or ""),
    )


def mark_password_token_sent(
    conn,
    token_id: int,
    *,
    now: dt.datetime | None = None,
) -> bool:
    """Record that a mail provider CONFIRMED sending this token's message.

    The single writer of ``senha_tokens.sent_at`` (prod-1/v10). It must be
    called only on the confirmed-send branch: an indeterminate provider result
    is not a send, and a definite failure is the opposite of one. That
    restriction is the whole value of the column -- see
    ``app.prod1_access_delivery_ddl``.

    Writing is idempotent and does not resurrect a spent token: a token already
    marked, consumed or invalidated is left alone and ``False`` is returned.
    """
    cursor = conn.execute(
        """
        UPDATE senha_tokens
           SET sent_at=?
         WHERE id=? AND sent_at IS NULL
           AND consumed_at IS NULL AND invalidated_at IS NULL
        """,
        (_db_timestamp(_utc_now(now)), int(token_id)),
    )
    return cursor.rowcount == 1


def invalidate_password_token(conn, token_id: int) -> bool:
    cursor = conn.execute(
        """
        UPDATE senha_tokens
           SET invalidated_at=datetime('now')
         WHERE id=? AND consumed_at IS NULL AND invalidated_at IS NULL
        """,
        (int(token_id),),
    )
    return cursor.rowcount == 1


def consume_password_token_and_set_password(
    conn,
    raw_token: str,
    purpose: str,
    password_hash: str,
    *,
    now: dt.datetime | None = None,
) -> int | None:
    """Atomically consume a valid token and install a personal password.

    Returns the new ``auth_version`` or ``None`` when the token is no longer
    valid.  Hashing is intentionally performed by the caller before the write
    transaction so PBKDF2 never holds the SQLite write lock.
    """
    if conn.in_transaction:
        raise PasswordTokenError("password token consumption requires a clean transaction")
    try:
        conn.execute("BEGIN IMMEDIATE")
        record = resolve_password_token(conn, raw_token, purpose=purpose, now=now)
        if record is None:
            conn.execute("ROLLBACK")
            return None
        # Defence in depth: first access only ever completes a PENDING account.
        # The state is read inside this write transaction, so no writer can
        # change it between the check and the password write.  Refusal is the
        # same generic None an expired or unknown token gets -- nothing is
        # written, nothing is consumed, and the account state does not leak.
        # password_reset carries no such precondition.
        if purpose == PURPOSE_FIRST_ACCESS and not first_access_redeemable(
            record.credential_state
        ):
            conn.execute("ROLLBACK")
            return None

        from app.user_accounts import get_usuario_auth_version, set_usuario_password_hash

        set_usuario_password_hash(
            conn,
            record.usuario_id,
            password_hash,
            credential_state=CREDENTIAL_STATE_PERSONAL,
            consumed_token_id=record.id,
        )
        auth_version = get_usuario_auth_version(conn, record.usuario_id)
        if auth_version is None:
            raise PasswordTokenError("credential state disappeared during token consumption")
        conn.execute("COMMIT")
        return auth_version
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


__all__ = [
    "FIRST_ACCESS_TTL",
    "PASSWORD_RESET_TTL",
    "PASSWORD_TOKEN_PURPOSES",
    "PURPOSE_FIRST_ACCESS",
    "PURPOSE_PASSWORD_RESET",
    "PasswordTokenError",
    "PasswordTokenRecord",
    "consume_password_token_and_set_password",
    "invalidate_password_token",
    "issue_password_token",
    "mark_password_token_sent",
    "password_token_digest",
    "resolve_password_token",
]
