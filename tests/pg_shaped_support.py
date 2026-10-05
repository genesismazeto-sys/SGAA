# coding: utf-8
"""PostgreSQL-shaped connection double for the PostgreSQL-readiness gates.

Wraps a real SQLite connection and adds the transaction-state semantics of
psycopg 3 with ``autocommit=False`` so the runtime transaction/locking contract
can be exercised without a network, a PostgreSQL server or a psycopg
connection:

* every statement opens or joins a transaction (IDLE -> INTRANS), so an
  unrelated prior ``SELECT`` leaves the connection INTRANS;
* a failed statement leaves the transaction INERROR and every later statement
  is refused until ``rollback`` (transaction-control statements still pass);
* ``BEGIN IMMEDIATE`` is a syntax error, exactly as PostgreSQL rejects it;
* an XID is modelled as assigned by the first write or locking statement, so
  ``SELECT pg_current_xact_id_if_assigned()`` reports NULL for a read-only
  transaction and a value once the transaction owns write work;
* row locks are modelled with the PostgreSQL conflict matrix for the modes the
  runtime uses: ``EXCLUSIVE`` (``FOR UPDATE``, ``DELETE``), ``NO_KEY_UPDATE``
  (``FOR NO KEY UPDATE``, non-key ``UPDATE``) and ``KEY_SHARE`` (the lock a
  foreign-key check takes on the referenced row).  ``EXCLUSIVE`` conflicts with
  everything, ``NO_KEY_UPDATE`` with itself and ``EXCLUSIVE``, ``KEY_SHARE``
  only with ``EXCLUSIVE``.  Explicit lock clauses are recorded and stripped so
  the wrapped SQLite engine can still run the row work; an optional shared lock
  registry turns a conflicting acquisition into an observable
  :class:`PostgresLockBlocked` (in a real server it would wait instead).
* the effective lock of one transaction on one row never downgrades: a
  re-acquisition merges into the strongest mode requested so far and the lock
  is retained in that effective mode until ``commit``/``rollback`` (or
  ``close``), as real PostgreSQL does for its tuple locks.  Example: a
  ``FOR UPDATE`` account lock followed by the ``senha_tokens`` FK ``KEY SHARE``
  stays ``EXCLUSIVE``, so a concurrent direct account writer still conflicts.

WHAT THIS DOUBLE DOES NOT MODEL (do not over-read it):

* it is not a scheduler: a blocked acquisition raises immediately instead of
  waiting, so tests must pin the *ordering* of acquisitions, not real timing;
* it does not parse arbitrary SQL: DML row locks are derived only for
  ``usuarios`` and ``senha_tokens``, and the ``senha_tokens`` FK key-share is
  derived from the insert's ``usuario_id`` parameter;
* it does not model multixact, tuple versions, lock queues, serialization
  failures or the full PostgreSQL deadlock detector; each owner keeps one
  effective mode per row, which is enough to discriminate the Unit 4
  lock-order contract but is not full PostgreSQL lock-manager semantics.
"""
from __future__ import annotations

import re
import types


class PostgresSyntaxError(Exception):
    """The statement is not valid PostgreSQL (``BEGIN IMMEDIATE``)."""


class PostgresFailedTransactionError(Exception):
    """PostgreSQL refuses SQL while the transaction is in error."""


class PostgresLockBlocked(Exception):
    """Another connection holds a conflicting logical row lock."""


MODE_EXCLUSIVE = "EXCLUSIVE"
MODE_NO_KEY_UPDATE = "NO_KEY_UPDATE"
MODE_KEY_SHARE = "KEY_SHARE"

#: PostgreSQL row-lock strength; a same-owner re-acquisition keeps the max.
_MODE_STRENGTH = {
    MODE_KEY_SHARE: 1,
    MODE_NO_KEY_UPDATE: 2,
    MODE_EXCLUSIVE: 3,
}


def effective_lock_mode(held_mode, requested_mode):
    """The mode a transaction effectively holds after re-acquiring one row.

    PostgreSQL keeps the strongest lock of a transaction on a tuple until the
    end of the transaction, so a weaker re-acquisition never downgrades:
    ``FOR UPDATE`` + FK ``KEY SHARE`` stays ``EXCLUSIVE``.
    """
    if _MODE_STRENGTH.get(requested_mode, 0) >= _MODE_STRENGTH.get(held_mode, 0):
        return requested_mode
    return held_mode


#: The PostgreSQL row-lock conflict matrix restricted to the modes above.
_CONFLICTING_MODES = frozenset(
    {
        (MODE_EXCLUSIVE, MODE_EXCLUSIVE),
        (MODE_EXCLUSIVE, MODE_NO_KEY_UPDATE),
        (MODE_EXCLUSIVE, MODE_KEY_SHARE),
        (MODE_NO_KEY_UPDATE, MODE_EXCLUSIVE),
        (MODE_NO_KEY_UPDATE, MODE_NO_KEY_UPDATE),
        (MODE_KEY_SHARE, MODE_EXCLUSIVE),
    }
)

_ROW_LOCK_RE = re.compile(
    r"\s+FOR\s+(NO\s+KEY\s+)?UPDATE(?:\s+OF\s+\w+)?", re.IGNORECASE
)
_FROM_TABLE_RE = re.compile(r"\bFROM\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE)
_UPDATE_RE = re.compile(
    r"^\s*UPDATE\s+([A-Za-z_][A-Za-z0-9_]*)\s+SET\s+.+?(?=\bWHERE\b)(WHERE\b.+)$",
    re.IGNORECASE | re.DOTALL,
)
_DELETE_RE = re.compile(
    r"^\s*DELETE\s+FROM\s+([A-Za-z_][A-Za-z0-9_]*)\s+(WHERE\b.+)$",
    re.IGNORECASE | re.DOTALL,
)
_INSERT_TOKEN_RE = re.compile(r"^\s*INSERT\s+INTO\s+senha_tokens\b", re.IGNORECASE)
_DML_RE = re.compile(r"^\s*(?:INSERT|UPDATE|DELETE)\b", re.IGNORECASE)
_XACT_PROBE_RE = re.compile(r"pg_current_xact_id_if_assigned", re.IGNORECASE)
_TRANSACTION_CONTROL_RE = re.compile(r"^\s*(?:ROLLBACK|COMMIT)\b", re.IGNORECASE)

#: Tables whose DML row locks the double derives from the statement text.
_DML_ROW_LOCK_TABLES = frozenset({"usuarios", "senha_tokens"})


class _XidProbeCursor:
    """Result of the ``pg_current_xact_id_if_assigned()`` probe."""

    def __init__(self, assigned):
        self._row = (1,) if assigned else (None,)

    def fetchone(self):
        return self._row

    def fetchall(self):
        return [self._row]

    def __iter__(self):
        return iter([self._row])


class PostgresShapedConnection:
    """A SQLite row engine behind psycopg 3 transaction-state semantics."""

    def __init__(self, real, *, lock_registry=None, owner=None):
        self._real = real
        self._status = "IDLE"
        self._xid_assigned = False
        self._lock_registry = lock_registry if lock_registry is not None else {}
        self._owner = owner if owner is not None else object()
        self._held_locks = []
        self.statements = []
        self.failed_statements = []
        self.locks = []
        self.lock_events = []
        self.commits = 0
        self.rollbacks = 0

    @property
    def info(self):
        return types.SimpleNamespace(
            transaction_status=types.SimpleNamespace(name=self._status)
        )

    @property
    def in_transaction(self):
        return self._status in ("INTRANS", "INERROR")

    @property
    def raw_connection(self):
        return self._real

    @property
    def xid_assigned(self):
        return self._xid_assigned

    def __getattr__(self, name):
        return getattr(self._real, name)

    # -- lock registry ------------------------------------------------------

    def _acquire(self, key, mode):
        self.locks.append(key)
        self.lock_events.append((key, mode))
        holders = self._lock_registry.setdefault(key, {})
        for holder, held_mode in holders.items():
            if holder is not self._owner and (held_mode, mode) in _CONFLICTING_MODES:
                raise PostgresLockBlocked(
                    f"row lock {key!r} ({mode}) conflicts with {held_mode!r}"
                )
        held = holders.get(self._owner)
        holders[self._owner] = (
            mode if held is None else effective_lock_mode(held, mode)
        )
        if key not in self._held_locks:
            self._held_locks.append(key)

    def _release_locks(self):
        for key in self._held_locks:
            holders = self._lock_registry.get(key)
            if holders is None:
                continue
            holders.pop(self._owner, None)
            if not holders:
                del self._lock_registry[key]
        self._held_locks = []

    def _explicit_lock_key(self, sql, params):
        match = _FROM_TABLE_RE.search(sql)
        table = match.group(1).lower() if match else "?"
        identifier = params[0] if params else None
        return (table, int(identifier) if isinstance(identifier, int) else identifier)

    def _matched_ids(self, table, where, params):
        placeholders = where.count("?")
        if not placeholders:
            return []
        where_params = tuple(params)[-placeholders:]
        rows = self._real.execute(
            f"SELECT id FROM {table} {where}", where_params
        ).fetchall()
        return [int(row[0]) for row in rows]

    def _acquire_statement_locks(self, text, params):
        if _DML_RE.match(text):
            self._xid_assigned = True
        if _INSERT_TOKEN_RE.match(text):
            # The senha_tokens -> usuarios foreign key check takes a KEY SHARE
            # lock on the referenced account row.
            if params:
                self._acquire(("usuarios", int(params[0])), MODE_KEY_SHARE)
            return
        match = _UPDATE_RE.match(text)
        if match and match.group(1).lower() in _DML_ROW_LOCK_TABLES:
            table = match.group(1).lower()
            for row_id in self._matched_ids(table, match.group(2), params):
                self._acquire((table, row_id), MODE_NO_KEY_UPDATE)
            return
        match = _DELETE_RE.match(text)
        if match and match.group(1).lower() in _DML_ROW_LOCK_TABLES:
            table = match.group(1).lower()
            for row_id in self._matched_ids(table, match.group(2), params):
                self._acquire((table, row_id), MODE_EXCLUSIVE)

    # -- statement execution ------------------------------------------------

    def execute(self, sql, params=None):
        text = str(sql)
        self.statements.append((text, params))
        if self._status == "INERROR":
            if _TRANSACTION_CONTROL_RE.match(text):
                if text.strip().upper().startswith("ROLLBACK"):
                    self._real.rollback()
                else:
                    self._real.commit()
                self._status = "IDLE"
                self._xid_assigned = False
                return self._real.execute("SELECT 1 WHERE 0")
            self.failed_statements.append(text)
            raise PostgresFailedTransactionError(text)
        if _XACT_PROBE_RE.search(text):
            return _XidProbeCursor(self._xid_assigned)
        self._status = "INTRANS"
        if "BEGIN IMMEDIATE" in text.upper():
            self._status = "INERROR"
            raise PostgresSyntaxError("BEGIN IMMEDIATE is not valid PostgreSQL")
        lock = _ROW_LOCK_RE.search(text)
        if lock:
            self._xid_assigned = True
            mode = MODE_NO_KEY_UPDATE if lock.group(1) else MODE_EXCLUSIVE
            self._acquire(self._explicit_lock_key(text, params), mode)
            text = _ROW_LOCK_RE.sub("", text)
        else:
            self._acquire_statement_locks(text, params)
        try:
            if params is None:
                return self._real.execute(text)
            return self._real.execute(text, params)
        except Exception:
            self._status = "INERROR"
            raise

    def commit(self):
        self.commits += 1
        self._release_locks()
        self._real.commit()
        self._status = "IDLE"
        self._xid_assigned = False

    def rollback(self):
        self.rollbacks += 1
        self._release_locks()
        self._real.rollback()
        self._status = "IDLE"
        self._xid_assigned = False

    def close(self):
        self._release_locks()
        self._real.close()
        self._status = "IDLE"
        self._xid_assigned = False


__all__ = [
    "MODE_EXCLUSIVE",
    "MODE_KEY_SHARE",
    "MODE_NO_KEY_UPDATE",
    "PostgresFailedTransactionError",
    "PostgresLockBlocked",
    "PostgresShapedConnection",
    "PostgresSyntaxError",
    "effective_lock_mode",
]
