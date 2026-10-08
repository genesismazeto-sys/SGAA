"""Shared helpers for the v14 canonical-custody primitives.

* Time is ``YYYY-MM-DD HH:MM:SS`` UTC text -- the exact shape the v14 CHECK
  constraints require, so lease / due / expiry comparisons are plain text
  comparisons on SQLite and PostgreSQL alike.  Every primitive takes ``now``
  explicitly: tests drive time deterministically, never by sleeping.
* Error codes are sanitized to ``[A-Z0-9_]{1,64}``; anything else (exception
  text, a path, an e-mail, a token) becomes ``UNCLASSIFIED_ERROR``.
* The caller owns the transaction (``app.db.write_transaction``).  On SQLite
  that is ``BEGIN IMMEDIATE`` -- the database write lock is the logical
  equivalent of PostgreSQL's row locks, so writers refuse to run outside it.
"""

from __future__ import annotations

import datetime
import re
import secrets

from app.prod1_storage_ddl import ERROR_CODE_MAX_LENGTH, LEASE_TOKEN_LENGTH

UNCLASSIFIED_ERROR = "UNCLASSIFIED_ERROR"
_UTC_TEXT_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
_CODE_RE = re.compile(rf"^[A-Z0-9_]{{1,{ERROR_CODE_MAX_LENGTH}}}$")
_LEASE_RE = re.compile(rf"^[0-9a-f]{{{LEASE_TOKEN_LENGTH}}}$")
_FORMAT = "%Y-%m-%d %H:%M:%S"


class CustodyError(RuntimeError):
    """A refused custody operation; ``code`` is fixed and value-free."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def require_utc_text(value) -> str:
    if not isinstance(value, str) or not _UTC_TEXT_RE.fullmatch(value):
        raise ValueError("expected UTC text YYYY-MM-DD HH:MM:SS")
    datetime.datetime.strptime(value, _FORMAT)
    return value


def utc_now_text() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime(_FORMAT)


def add_seconds(value: str, seconds: int) -> str:
    moment = datetime.datetime.strptime(require_utc_text(value), _FORMAT)
    return (moment + datetime.timedelta(seconds=int(seconds))).strftime(_FORMAT)


def sanitize_error_code(code) -> str:
    return code if isinstance(code, str) and _CODE_RE.fullmatch(code) else UNCLASSIFIED_ERROR


def new_lease_token() -> str:
    return secrets.token_hex(LEASE_TOKEN_LENGTH // 2)


def require_lease_token(value) -> str:
    if not isinstance(value, str) or not _LEASE_RE.fullmatch(value):
        raise ValueError("invalid lease token")
    return value


def is_postgres(conn) -> bool:
    from app.db import database_engine

    return database_engine(conn) == "postgres"


def require_write_transaction(conn) -> None:
    """SQLite writers must run under the caller's ``BEGIN IMMEDIATE``."""
    if not is_postgres(conn) and not conn.in_transaction:
        raise CustodyError("WRITE_TRANSACTION_REQUIRED")


def positive_limit(limit, maximum: int) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= maximum:
        raise ValueError(f"limit must be 1..{maximum}")
    return limit


__all__ = [
    "CustodyError",
    "UNCLASSIFIED_ERROR",
    "add_seconds",
    "is_postgres",
    "new_lease_token",
    "positive_limit",
    "require_lease_token",
    "require_utc_text",
    "require_write_transaction",
    "sanitize_error_code",
    "utc_now_text",
]
