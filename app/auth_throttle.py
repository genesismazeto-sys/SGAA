"""Login and password-recovery throttling that survives more than one process.

A single-process runtime throttles in memory (``app.auth`` for login,
``app.password_recovery_limiter`` for recovery) and that stays the behaviour
there.  A hosted runtime is many short-lived instances: memory is per
instance, so the same limits would never trip.  When hosted, this module keeps
the same counters in ``auth_throttle_events`` (schema v16) instead, with the
same thresholds and windows (the ``LOGIN_*`` / ``PASSWORD_RESET_*``
configuration).

The views call the selector functions (``login_blocked`` ...); each one picks
the store from ``app.hosting``.  Only the keyed digest of an address or
account is stored -- ``HMAC-SHA-256(secret key, scope NUL value)`` -- so the
table can neither be read back into e-mail addresses or IPs nor be
precomputed without the application secret.

Writes happen on a failed login and on a recovery request, never on a blocked
one: once a key is over its limit it stops costing rows.  Every write prunes
that key's expired events and a bounded batch of the expired events of the
scopes it wrote (each scope family has its own window), so the table cannot
grow without limit under a flood of distinct keys beyond the request rate
itself.
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import logging
from collections.abc import Sequence

from flask import current_app

from app import auth as _login_memory
from app import hosting
from app import password_recovery_limiter as _recovery_memory
from app.db import get_db_connection, skip_locked, write_transaction
from app.password_recovery_limiter import normalize_recovery_identifier as _normalized
from app.prod1_ephemeral_state_ddl import AUTH_THROTTLE_SCOPES
from app.storage import custody_common

logger = logging.getLogger(__name__)

# The scope names are the schema's (the CHECK constraint); the order is the DDL's.
SCOPE_LOGIN_IP, SCOPE_LOGIN_ACCOUNT, SCOPE_RECOVERY_IP, SCOPE_RECOVERY_ACCOUNT = AUTH_THROTTLE_SCOPES

#: Expired events removed per write beyond the written key's own (a bound, not a target).
GLOBAL_PRUNE_BATCH = 200


def key_digest(scope: str, value: str, *, secret: bytes | str | None = None) -> str:
    """Keyed digest of one throttled identity (the only form that is stored)."""
    if secret is None:
        secret = current_app.secret_key
    key = secret.encode("utf-8") if isinstance(secret, str) else bytes(secret)
    return hmac.new(key, f"{scope}\0{value}".encode("utf-8"), hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# the durable store
# ---------------------------------------------------------------------------


def blocked(conn, scope: str, digest: str, *, window_seconds: int, max_attempts: int,
            now: datetime.datetime | None = None) -> tuple[bool, int]:
    """Whether the key already has ``max_attempts`` events inside the window; seconds until it frees."""
    now = now or custody_common.utc_now()
    cutoff = custody_common.utc_text(now - datetime.timedelta(seconds=window_seconds))
    count, oldest = conn.execute(
        "SELECT count(*), min(occurred_at) FROM auth_throttle_events"
        " WHERE scope = ? AND key_digest = ? AND occurred_at > ?",
        (scope, digest, cutoff),
    ).fetchone()
    if int(count) < max_attempts:
        return False, 0
    if oldest is None:  # a limit of zero blocks outright: a full window, as the memory limiter reports
        return True, max(1, int(window_seconds))
    elapsed = (now - custody_common.parse_utc_text(str(oldest))).total_seconds()
    return True, max(1, int(window_seconds - elapsed))


def register(conn, keys: Sequence[tuple[str, str]], *, window_seconds: int,
             now: datetime.datetime | None = None) -> None:
    """Record one event for each ``(scope, digest)`` key and prune what has expired (bounded)."""
    now = now or custody_common.utc_now()
    cutoff = custody_common.utc_text(now - datetime.timedelta(seconds=window_seconds))
    scopes = sorted({scope for scope, _digest in keys})
    with write_transaction(conn):
        for scope, digest in keys:
            conn.execute(
                "INSERT INTO auth_throttle_events(scope, key_digest, occurred_at) VALUES (?, ?, ?)",
                (scope, digest, custody_common.utc_text(now)),
            )
            conn.execute(
                "DELETE FROM auth_throttle_events WHERE scope = ? AND key_digest = ? AND occurred_at <= ?",
                (scope, digest, cutoff),
            )
        # Only the scopes just written, whose window this cutoff is: another scope family
        # (login vs recovery) may be configured with a longer window and keeps its events.
        # Never waits on a row another writer's prune already holds (see skip_locked).
        if scopes:
            marks = ",".join("?" for _ in scopes)
            conn.execute(
                "DELETE FROM auth_throttle_events WHERE id IN ("
                f" SELECT id FROM auth_throttle_events WHERE scope IN ({marks}) AND occurred_at <= ?"
                f" ORDER BY occurred_at, id LIMIT ?{skip_locked(conn)})",
                (*scopes, cutoff, GLOBAL_PRUNE_BATCH),
            )


def clear(conn, keys: Sequence[tuple[str, str]]) -> None:
    with write_transaction(conn):
        for scope, digest in keys:
            conn.execute(
                "DELETE FROM auth_throttle_events WHERE scope = ? AND key_digest = ?", (scope, digest)
            )


def _limits(app, window: str, ip_max: str, account_max: str) -> tuple[int, int, int]:
    """The configured window and maxima: ``create_app`` always sets them, so a missing
    key is a wiring fault that must fail closed, not fall back to a second set of defaults."""
    config = app.config
    return int(config[window]), int(config[ip_max]), int(config[account_max])


def _durable_blocked(app, ip_scope: str, account_scope: str, ip: str, account: str | None,
                     limits: tuple[int, int, int]) -> tuple[bool, int]:
    window, ip_max, account_max = limits
    conn = get_db_connection()
    flagged, retry_in = blocked(conn, ip_scope, key_digest(ip_scope, str(ip or "?")),
                                window_seconds=window, max_attempts=ip_max)
    if flagged:
        return True, retry_in
    account_key = _normalized(account)
    if account_key:
        return blocked(conn, account_scope, key_digest(account_scope, account_key),
                       window_seconds=window, max_attempts=account_max)
    return False, 0


def _keys(ip_scope: str, account_scope: str, ip: str | None, account: str | None, *,
          ip_fallback: str | None = None) -> list[tuple[str, str]]:
    keys = []
    address = ip or ip_fallback
    if address:
        keys.append((ip_scope, key_digest(ip_scope, str(address))))
    account_key = _normalized(account)
    if account_key:
        keys.append((account_scope, key_digest(account_scope, account_key)))
    return keys


def _durable_register(ip_scope: str, account_scope: str, ip: str, account: str | None, window: int) -> None:
    register(get_db_connection(), _keys(ip_scope, account_scope, ip, account, ip_fallback="?"),
             window_seconds=window)


# ---------------------------------------------------------------------------
# what the views call
# ---------------------------------------------------------------------------


def login_blocked(app, ip: str, account: str | None = None) -> tuple[bool, int]:
    if not hosting.is_hosted():
        return _login_memory._login_rate_limited(app, ip, account=account)
    return _durable_blocked(app, SCOPE_LOGIN_IP, SCOPE_LOGIN_ACCOUNT, ip, account,
                            _limits(app, "LOGIN_WINDOW_SECONDS", "LOGIN_MAX_ATTEMPTS",
                                    "LOGIN_ACCOUNT_MAX_ATTEMPTS"))


def login_failed(ip: str, account: str | None = None) -> None:
    if not hosting.is_hosted():
        _login_memory._register_login_attempt(ip, account=account)
        return
    _durable_register(SCOPE_LOGIN_IP, SCOPE_LOGIN_ACCOUNT, ip, account,
                      int(current_app.config["LOGIN_WINDOW_SECONDS"]))


def login_succeeded(ip: str | None, account: str | None = None) -> None:
    if not hosting.is_hosted():
        _login_memory._clear_login_attempts(ip=ip, account=account)
        return
    try:
        clear(get_db_connection(), _keys(SCOPE_LOGIN_IP, SCOPE_LOGIN_ACCOUNT, ip, account))
    except Exception as exc:
        # The user is already authenticated: stale events only age out of the window.
        logger.warning("login throttle clear failed (%s)", type(exc).__name__)


def recovery_blocked(app, ip: str, account: str | None = None) -> tuple[bool, int]:
    if not hosting.is_hosted():
        return _recovery_memory.password_recovery_rate_limited(app, ip, account or "")
    return _durable_blocked(app, SCOPE_RECOVERY_IP, SCOPE_RECOVERY_ACCOUNT, ip, account,
                            _limits(app, "PASSWORD_RESET_WINDOW_SECONDS", "PASSWORD_RESET_MAX_ATTEMPTS",
                                    "PASSWORD_RESET_ACCOUNT_MAX_ATTEMPTS"))


def recovery_attempted(ip: str, account: str | None = None) -> None:
    if not hosting.is_hosted():
        _recovery_memory.register_password_recovery_attempt(ip, account or "")
        return
    _durable_register(SCOPE_RECOVERY_IP, SCOPE_RECOVERY_ACCOUNT, ip, account,
                      int(current_app.config["PASSWORD_RESET_WINDOW_SECONDS"]))


__all__ = [
    "GLOBAL_PRUNE_BATCH",
    "SCOPE_LOGIN_ACCOUNT",
    "SCOPE_LOGIN_IP",
    "SCOPE_RECOVERY_ACCOUNT",
    "SCOPE_RECOVERY_IP",
    "blocked",
    "clear",
    "key_digest",
    "login_blocked",
    "login_failed",
    "login_succeeded",
    "recovery_attempted",
    "recovery_blocked",
    "register",
]
