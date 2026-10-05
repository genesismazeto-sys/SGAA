# coding: utf-8
"""Engine-neutral SQL dialect surface for the SGAA runtime.

This module is the single owner of the *small* set of recurring differences
between the SQLite runtime (the current default engine) and the PostgreSQL
runtime baseline created by ``app.pg_schema``.  Route and service code asks
this module for a fixed, application-owned SQL fragment instead of embedding
engine-specific syntax or scattering ``database_engine(conn) == "postgres"``
branches through the codebase.

Design rules:

* Every fragment returned here is fixed application-owned SQL.  No fragment
  ever interpolates user input; values stay bound parameters (``?``), which the
  PostgreSQL connection adapter translates to ``psycopg`` pyformat.
* SQLite behaviour is preserved exactly: each SQLite branch reproduces the
  historical expression verbatim.
* PostgreSQL fragments are PG15-compatible and rely only on helpers already
  provisioned by the U5-A schema authority (``sgaa_utcnow_text``,
  ``sgaa_datetime_text_valid``).  No DDL is executed or required.
* Timestamp columns remain canonical UTC ``TEXT`` (``YYYY-MM-DD HH:MM:SS``);
  this module never converts them to ``timestamp``/``timestamptz`` columns.

The engine behind a connection is resolved through ``app.db.database_engine``
so PG-shaped test doubles and the canonical adapter are recognised exactly as
they are elsewhere.  The import is deliberately lazy: importing this module
must never import ``app.db`` at module load time.
"""
from __future__ import annotations

import re

_SQLITE = "sqlite"
_POSTGRES = "postgres"

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_COLUMN_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$"
)


def _engine(connection) -> str:
    from app.db import database_engine

    return database_engine(connection)


def _is_postgres(connection) -> bool:
    return _engine(connection) == _POSTGRES


def _validate_column(column: str) -> str:
    """Refuse any column reference that is not a fixed app-owned identifier.

    Column references are application-owned literals (never user input); this
    guard makes that explicit and keeps a future refactor from interpolating a
    request value into a dialect fragment.
    """
    if not _COLUMN_RE.match(str(column)):
        raise ValueError(f"invalid column reference for dialect fragment: {column!r}")
    return column


#: The exact comparison operators ``date_compare`` supports.  This is the set
#: actually required by the current production callers (inclusive range
#: filters), never "everything SQL allows".  The operator is interpolated into
#: the fragment, so it is validated against this immutable allowlist before any
#: SQL is constructed; no normalisation, no whitespace variants, no compound
#: fragments and no SQL keywords are accepted.
_ALLOWED_DATE_COMPARISON_OPERATORS = frozenset({">=", "<="})


def _validate_date_operator(operator: str) -> str:
    if operator not in _ALLOWED_DATE_COMPARISON_OPERATORS:
        raise ValueError(
            f"unsupported date comparison operator: {operator!r}; allowed: "
            f"{sorted(_ALLOWED_DATE_COMPARISON_OPERATORS)!r}"
        )
    return operator


# ---------------------------------------------------------------------------
# current UTC text
# ---------------------------------------------------------------------------


def current_utc_text(connection) -> str:
    """SQL expression for the database's current UTC text (seconds precision).

    SQLite: ``datetime('now')``.  PostgreSQL: ``sgaa_utcnow_text()`` (U5-A).
    Both produce ``YYYY-MM-DD HH:MM:SS`` in UTC.
    """
    if _is_postgres(connection):
        return "sgaa_utcnow_text()"
    return "datetime('now')"


def fetch_current_utc_text(connection) -> str:
    """Run ``SELECT`` on :func:`current_utc_text` and return the text value."""
    row = connection.execute("SELECT " + current_utc_text(connection)).fetchone()
    return str(row[0])


# ---------------------------------------------------------------------------
# date extraction / filtering
# ---------------------------------------------------------------------------


def date_compare(connection, column: str, operator: str) -> str:
    """Predicate comparing a stored text date/datetime to one bound date.

    Returns a fragment containing exactly one ``?`` placeholder.  SQLite keeps
    ``date(column) <op> date(?)``.  PostgreSQL extracts the leading ISO date
    from the canonical text only when it is a valid datetime text (mirroring
    SQLite's ``date()`` returning NULL for invalid/NULL input) and compares it
    to the bound ``YYYY-MM-DD`` parameter as text, avoiding a ``::timestamp``
    cast that would raise on malformed persisted data.
    """
    column = _validate_column(column)
    operator = _validate_date_operator(operator)
    if _is_postgres(connection):
        return (
            f"(CASE WHEN sgaa_datetime_text_valid({column}) "
            f"THEN left(btrim({column}), 10) ELSE NULL END) {operator} ?"
        )
    return f"date({column}) {operator} date(?)"


# ---------------------------------------------------------------------------
# datetime ordering / conversion
# ---------------------------------------------------------------------------


def datetime_order(connection, column: str) -> str:
    """Ordering expression equivalent to SQLite ``datetime(column)``.

    Timestamp columns are canonical UTC text, so ordering by the raw text is
    the same order.  ``COALESCE(column, '')`` keeps SQLite's NULL placement
    (NULL is smaller than any value) in a PostgreSQL ``ORDER BY``.
    """
    column = _validate_column(column)
    if _is_postgres(connection):
        return f"COALESCE({column}, '')"
    return f"datetime({column})"


def format_date_ptbr(connection, column: str) -> str:
    """Expression rendering a stored date/datetime as ``DD/MM/YYYY``.

    SQLite keeps ``strftime('%d/%m/%Y', column)``.  PostgreSQL uses
    ``to_char`` behind the same validity guard, so NULL and malformed text
    yield NULL exactly as SQLite's ``strftime`` does.
    """
    column = _validate_column(column)
    if _is_postgres(connection):
        return (
            f"CASE WHEN sgaa_datetime_text_valid({column}) "
            f"THEN to_char(({column})::timestamp, 'DD/MM/YYYY') ELSE NULL END"
        )
    return f"strftime('%d/%m/%Y', {column})"


def datetime_before_now_days(connection, column: str) -> str:
    """Predicate: stored ``column`` is at least ``?`` days in the past.

    Returns a fragment containing exactly one ``?`` placeholder (the number of
    days, bound as an integer).  SQLite keeps
    ``datetime(column) <= datetime('now', '-' || ? || ' days')``; PostgreSQL
    compares against the database clock minus ``make_interval(days => ?)``
    behind the validity guard.
    """
    column = _validate_column(column)
    if _is_postgres(connection):
        return (
            f"(CASE WHEN sgaa_datetime_text_valid({column}) "
            f"THEN ({column})::timestamp ELSE NULL END) "
            f"<= (sgaa_utcnow_text()::timestamp - make_interval(days => ?::int))"
        )
    return f"datetime({column}) <= datetime('now', '-' || ? || ' days')"


# ---------------------------------------------------------------------------
# JSON text extraction
# ---------------------------------------------------------------------------


def json_text(connection, column: str, key: str) -> str:
    """Extract one scalar text field from a JSON-as-TEXT column.

    The ``key`` is a fixed application-owned identifier (validated here), never
    user input.  SQLite keeps ``json_extract(column, '$.key')``; PostgreSQL
    uses ``column::jsonb ->> 'key'``.  Both return NULL for a NULL column and
    for a missing key; both reject malformed JSON, which the schema contract
    already forbids on the columns this is used for.
    """
    column = _validate_column(column)
    if not _IDENTIFIER_RE.match(key):
        raise ValueError(f"invalid JSON key for dialect extraction: {key!r}")
    if _is_postgres(connection):
        return f"(({column})::jsonb ->> '{key}')"
    return f"json_extract({column}, '$.{key}')"


# ---------------------------------------------------------------------------
# misc fixed fragments
# ---------------------------------------------------------------------------


def newline(connection) -> str:
    """SQL expression for a line-feed character (SQLite ``char(10)``)."""
    if _is_postgres(connection):
        return "chr(10)"
    return "char(10)"


__all__ = [
    "current_utc_text",
    "date_compare",
    "datetime_before_now_days",
    "datetime_order",
    "fetch_current_utc_text",
    "format_date_ptbr",
    "json_text",
    "newline",
]
