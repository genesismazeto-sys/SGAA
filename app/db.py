import logging
import os
import re
import sqlite3
from contextlib import contextmanager

from flask import current_app, g

from app.backup_settings import (
    bind_backup_settings_runtime_app,
    ensure_backup_settings_schema,
)
from app.academics import (
    DEFAULT_CURSO_TOTAL_HORAS_AAC,
    DEFAULT_CURSO_TOTAL_HORAS_AEU,
    gerar_codigo_turma,
)
from app.db_maintenance import (
    apply_early_schema_migrations,
    apply_schema_migrations,
    ensure_atividade_versioning_schema,
    ensure_matriz_atividade_links_table,
    ensure_matrizes_atividades_table,
    ensure_reportes_table,
    ensure_requisicao_arquivos_table,
    ensure_requisicao_alert_receipts_table,
    ensure_usuario_access_schema,
    ensure_usuario_profile_schema,
)
from app.root_admin import DEFAULT_ROOT_ADMIN_EMAIL
from app.security.passwords import hash_password
from app.text import register_human_text_sql
from app.prod1_schema import validate_prod1_schema
from app.user_accounts import (
    CREDENTIAL_STATE_DEFAULT,
    CREDENTIAL_STATE_PERSONAL,
    _access_defaults_map,
    create_usuario_with_access_level,
)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATABASE = os.getenv("APP_DATABASE", os.path.join(PROJECT_ROOT, "database.db"))
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
logger = logging.getLogger(__name__)

DEFAULT_RESPONSE_GOAL_DAYS = 10
DEFAULT_RETURN_RESPONSE_DAYS = 7
DEFAULT_HORAS_ACADEMICA = 160
DEFAULT_HORAS_EXTENSAO = 160

_BACKEND_SQLITE = "sqlite"
_BACKEND_POSTGRES = "postgres"
_POSTGRES_URL_PREFIXES = ("postgres://", "postgresql://")
_DATABASE_URI_SCHEME_RE = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*)://")


class DatabaseAdapterError(Exception):
    """Engine-neutral database failure."""


class DatabaseIntegrityError(DatabaseAdapterError):
    """Integrity/constraint violation, engine-neutral."""

    def __init__(self, message, *, constraint_name=None, is_unique=False):
        super().__init__(message)
        self.constraint_name = constraint_name
        self.is_unique = bool(is_unique)


class DatabaseOperationalError(DatabaseAdapterError):
    """Operational failure (lock, connection, unavailable database)."""


def database_backend() -> str:
    """The active engine: SQLite unless a PostgreSQL URL is configured."""
    url = (DATABASE_URL or "").strip()
    if not url:
        return _BACKEND_SQLITE
    if url.startswith(_POSTGRES_URL_PREFIXES):
        return _BACKEND_POSTGRES
    match = _DATABASE_URI_SCHEME_RE.match(url)
    if match is not None:
        raise ValueError(f"unsupported DATABASE_URL scheme: {match.group(1)!r}")
    raise ValueError("unsupported DATABASE_URL format")


class EngineRow:
    """``sqlite3.Row``-compatible row for non-SQLite engines.

    Name access is case-insensitive and the first occurrence of a duplicated
    column wins, matching the sqlite3 behaviour callers already rely on.
    """

    __slots__ = ("_values", "_names", "_index")

    def __init__(self, values, names):
        self._values = tuple(values)
        self._names = [str(name) for name in names]
        index = {}
        for position, name in enumerate(self._names):
            index.setdefault(name.casefold(), position)
        self._index = index

    def __getitem__(self, key):
        if isinstance(key, str):
            try:
                return self._values[self._index[key.casefold()]]
            except KeyError:
                raise IndexError(f"no such column: {key}") from None
        return self._values[key]

    def keys(self):
        return list(self._names)

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def __contains__(self, key):
        if isinstance(key, str):
            return key.casefold() in self._index
        return key in self._values


def engine_row(values, description) -> EngineRow:
    names = [column[0] for column in description] if description else []
    return EngineRow(values, names)


def _escape_percent(text: str) -> str:
    return text.replace("%", "%%")


_DOLLAR_QUOTE_RE = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$")


def adapt_sql_for_postgres(sql: str) -> str:
    """Translate SQLite qmark SQL to psycopg pyformat safely.

    Only literal ``?`` in ordinary SQL become ``%s``.  Single-quoted strings
    (including doubled quotes), double-quoted identifiers, line and block
    comments and dollar-quoted bodies keep their ``?``.  Literal ``%`` becomes
    ``%%`` because psycopg percent-formats the whole statement whenever
    parameters are passed.
    """
    out = []
    index = 0
    length = len(sql)
    dollar_tag = None
    while index < length:
        char = sql[index]
        if dollar_tag is not None:
            if sql.startswith(dollar_tag, index):
                out.append(dollar_tag)
                index += len(dollar_tag)
                dollar_tag = None
                continue
            out.append(_escape_percent(char))
            index += 1
            continue
        if char == "'":
            out.append(char)
            index += 1
            while index < length:
                inner = sql[index]
                out.append(_escape_percent(inner))
                index += 1
                if inner == "'":
                    if index < length and sql[index] == "'":
                        out.append("'")
                        index += 1
                        continue
                    break
            continue
        if char == '"':
            out.append(char)
            index += 1
            while index < length:
                inner = sql[index]
                out.append(_escape_percent(inner))
                index += 1
                if inner == '"':
                    if index < length and sql[index] == '"':
                        out.append('"')
                        index += 1
                        continue
                    break
            continue
        if char == "-" and sql.startswith("--", index):
            end = sql.find("\n", index)
            if end == -1:
                end = length
            out.append(_escape_percent(sql[index:end]))
            index = end
            continue
        if char == "/" and sql.startswith("/*", index):
            depth = 1
            cursor = index + 2
            while cursor < length and depth:
                if sql.startswith("/*", cursor):
                    depth += 1
                    cursor += 2
                elif sql.startswith("*/", cursor):
                    depth -= 1
                    cursor += 2
                else:
                    cursor += 1
            out.append(_escape_percent(sql[index:cursor]))
            index = cursor
            continue
        if char == "$":
            match = _DOLLAR_QUOTE_RE.match(sql, index)
            if match:
                dollar_tag = match.group(0)
                out.append(dollar_tag)
                index = match.end()
                continue
        if char == "?":
            out.append("%s")
            index += 1
            continue
        out.append(_escape_percent(char))
        index += 1
    return "".join(out)


_TRANSACTION_IDLE = "IDLE"
_TRANSACTION_INTRANS = "INTRANS"
_TRANSACTION_INERROR = "INERROR"
_TRANSACTIONAL_STATUS_NAMES = frozenset({_TRANSACTION_INTRANS, _TRANSACTION_INERROR})


class DatabaseTransactionStateError(DatabaseAdapterError):
    """A transaction could not start from the connection's current state."""


def database_engine(connection) -> str:
    """The engine behind ``connection``: ``"sqlite"`` or ``"postgres"``.

    The canonical runtime connections are ``sqlite3.Connection`` and
    ``_PostgresConnectionAdapter``.  psycopg-shaped connections are recognised
    by their ``info.transaction_status``; anything else falls back to the
    configured backend, which keeps test proxies of the canonical connections
    on the engine they wrap.
    """
    if isinstance(connection, _PostgresConnectionAdapter):
        return _BACKEND_POSTGRES
    if isinstance(connection, sqlite3.Connection):
        return _BACKEND_SQLITE
    status = getattr(getattr(connection, "info", None), "transaction_status", None)
    if getattr(status, "name", None) is not None:
        return _BACKEND_POSTGRES
    return database_backend()


def connection_transaction_status(connection) -> str:
    """Engine-neutral transaction status: ``IDLE``, ``INTRANS``, ``INERROR``."""
    if isinstance(connection, _PostgresConnectionAdapter):
        connection = connection.raw_connection
    if isinstance(connection, sqlite3.Connection):
        return _TRANSACTION_INTRANS if connection.in_transaction else _TRANSACTION_IDLE
    status = getattr(getattr(connection, "info", None), "transaction_status", None)
    status_name = getattr(status, "name", None)
    if status_name in (
        _TRANSACTION_IDLE,
        _TRANSACTION_INTRANS,
        _TRANSACTION_INERROR,
        "UNKNOWN",
    ):
        return status_name
    if getattr(connection, "in_transaction", False):
        return _TRANSACTION_INTRANS
    return _TRANSACTION_IDLE


def connection_in_transaction(connection) -> bool:
    """Engine-neutral ``connection.in_transaction`` equivalent."""
    return connection_transaction_status(connection) in _TRANSACTIONAL_STATUS_NAMES


_POSTGRES_XACT_ID_PROBE_SQL = "SELECT pg_current_xact_id_if_assigned()"


def _postgres_transaction_has_assigned_xid(connection) -> bool:
    """Whether the current PostgreSQL transaction already owns write work.

    ``pg_current_xact_id_if_assigned()`` returns NULL until a write or locking
    statement assigns the transaction an XID, and does not assign one itself.
    It is therefore the read-only discriminator between a harmless
    INTRANS-after-SELECT transaction and a caller-owned write/locking
    transaction.  It requires PostgreSQL 13+.
    """
    row = connection.execute(_POSTGRES_XACT_ID_PROBE_SQL).fetchone()
    if row is None:
        return False
    return row[0] is not None


_WRITE_TRANSACTION_OWNER_ATTR = "_sgaa_write_transaction_owner"
_WRITE_TRANSACTION_UNOWNED = object()


def _write_transaction_owner(connection):
    """The manager-ownership token currently claimed on ``connection``.

    A nested ``write_transaction`` must be refused even on an IDLE connection
    whose outer block has not executed any SQL yet (so no XID exists to probe),
    so ownership is an explicit per-connection marker rather than an inference
    from the engine transaction status.  Connections that cannot carry
    attributes (raw ``sqlite3.Connection``) keep the historical engine-state
    refusal: ``BEGIN IMMEDIATE`` is taken before the outer block is yielded and
    makes ``connection_in_transaction`` true for the whole block.  No
    process-global owner state exists, and the marker dies with the connection.
    """
    return getattr(
        connection, _WRITE_TRANSACTION_OWNER_ATTR, _WRITE_TRANSACTION_UNOWNED
    )


def _claim_write_transaction(connection):
    owner = object()
    try:
        setattr(connection, _WRITE_TRANSACTION_OWNER_ATTR, owner)
    except (AttributeError, TypeError):
        return _WRITE_TRANSACTION_UNOWNED
    return owner


def _release_write_transaction(connection, owner) -> None:
    if owner is _WRITE_TRANSACTION_UNOWNED:
        return
    if getattr(connection, _WRITE_TRANSACTION_OWNER_ATTR, None) is not owner:
        return
    try:
        delattr(connection, _WRITE_TRANSACTION_OWNER_ATTR)
    except (AttributeError, TypeError):
        pass


@contextmanager
def write_transaction(connection):
    """Engine-neutral write transaction owned by the ``with`` block.

    SQLite keeps the historical write-intent transaction: a clean connection is
    required and ``BEGIN IMMEDIATE`` takes the database write lock before the
    first statement.  PostgreSQL starts lazily (psycopg ``autocommit=False``)
    or adopts a transaction a prior statement already opened -- a harmless
    INTRANS after SELECT, with no XID assigned, is not an open write
    transaction and must not be refused.  An INTRANS transaction that already
    owns write/locking work (an assigned XID) is caller-owned DML: the block
    refuses it instead of committing it.  An INERROR transaction is rolled
    back before the block reuses the connection.  A block that exits normally
    while the connection is INERROR is rolled back and reported as a state
    error, never silently committed or reported as success.

    A connection may have at most one active ``write_transaction`` owner.  The
    owner is an explicit marker claimed on the connection before the block is
    yielded and released in a ``finally`` path (success, block exception,
    swallowed-error state exception, commit failure and even rollback failure).
    A nested entry on the same connection therefore raises
    ``DatabaseTransactionStateError`` before the inner block runs, whatever the
    engine status is (IDLE, INTRANS after SELECT, or an assigned XID): the
    inner block cannot execute, commit or roll back the outer transaction.
    Separate connections own their markers independently.  Savepoint-style
    nesting is deliberately not offered -- nested write transactions are not a
    requirement.
    """
    if _write_transaction_owner(connection) is not _WRITE_TRANSACTION_UNOWNED:
        raise DatabaseTransactionStateError(
            "write transaction is already owned by an enclosing block on this "
            "connection"
        )
    if database_engine(connection) == _BACKEND_SQLITE:
        if connection_in_transaction(connection):
            raise DatabaseTransactionStateError(
                "write transaction requires a clean connection"
            )
        connection.execute("BEGIN IMMEDIATE")
    else:
        status = connection_transaction_status(connection)
        if status == _TRANSACTION_INERROR:
            connection.rollback()
            status = _TRANSACTION_IDLE
        if status == _TRANSACTION_INTRANS and _postgres_transaction_has_assigned_xid(
            connection
        ):
            raise DatabaseTransactionStateError(
                "write transaction requires a clean connection; the PostgreSQL "
                "transaction already owns write work"
            )
    owner = _claim_write_transaction(connection)
    try:
        try:
            yield connection
        except BaseException:
            connection.rollback()
            raise
        else:
            if connection_transaction_status(connection) == _TRANSACTION_INERROR:
                connection.rollback()
                raise DatabaseTransactionStateError(
                    "write transaction entered an error state and was rolled back"
                )
            connection.commit()
    finally:
        _release_write_transaction(connection, owner)


def lock_activity_base(connection, base_id: int) -> bool:
    """Serialize destructive version-set writes of one activity base.

    SQLite needs no explicit lock: ``BEGIN IMMEDIATE`` already excludes every
    other writer for the whole transaction.  PostgreSQL locks the parent
    ``atividade_base`` row for the remainder of the transaction, so concurrent
    version deletes of the same base cannot interleave their read-check-write
    and renumbering (which could otherwise empty a base or collide on
    ``UNIQUE(atividade_base_id, numero_versao)``).  ``FOR NO KEY UPDATE``
    conflicts with itself, which is all the proven invariant needs, and does
    not block foreign-key-check inserts of new versions.  A missing row means
    no version can belong to the base, so the caller's own validation refuses.

    F2 (delete × create-version numbering) is solved by the callers, not here:
    every automatic version creator takes this same base lock before computing
    ``get_next_numero_versao`` (MAX+1), so a concurrent creator or delete of the
    same base serializes on one lock domain.  ``FOR NO KEY UPDATE`` is retained
    because it is the weakest mode that still conflicts with itself (two
    creators, creator × delete) while remaining compatible with the foreign-key
    ``KEY SHARE`` checks that insert new versions; no table-wide lock and no
    unrelated-base serialization are introduced.
    """
    if database_engine(connection) != _BACKEND_POSTGRES:
        return True
    row = connection.execute(
        "SELECT id FROM atividade_base WHERE id = ? FOR NO KEY UPDATE",
        (int(base_id),),
    ).fetchone()
    return row is not None


def lock_password_account(connection, usuario_id: int) -> bool:
    """Serialize credential and token mutations of one account (PostgreSQL).

    The account row is the shared resource every password/token writer updates
    (``usuarios.senha``, ``usuario_credenciais``), so taking it first gives all
    of them one lock order.  SQLite needs no explicit lock because
    ``BEGIN IMMEDIATE`` already serializes the whole database.
    """
    if database_engine(connection) != _BACKEND_POSTGRES:
        return True
    row = connection.execute(
        "SELECT id FROM usuarios WHERE id = ? FOR UPDATE",
        (int(usuario_id),),
    ).fetchone()
    return row is not None


def lock_password_token(connection, token_id: int) -> bool:
    """Lock one password-token row against concurrent state changes.

    Token state writers (consume, invalidate, issue supersession, direct
    password change) all write the token row; locking it after the account
    keeps the account -> token order, so no deadlock-prone ordering is
    introduced.  SQLite needs no explicit lock.
    """
    if database_engine(connection) != _BACKEND_POSTGRES:
        return True
    row = connection.execute(
        "SELECT id FROM senha_tokens WHERE id = ? FOR UPDATE",
        (int(token_id),),
    ).fetchone()
    return row is not None


def lock_admin_arquivo(connection, arquivo_id: int) -> bool:
    """Lock one ``admin_arquivos`` row against concurrent custody changes (PostgreSQL).

    Every custody writer of an ARQUIVOS row -- canonical replacement, every
    deletion transition, legacy convergence -- takes this lock FIRST, then
    the row's upload intents.  SQLite needs no explicit lock:
    ``BEGIN IMMEDIATE`` already serializes the whole database.
    """
    if database_engine(connection) != _BACKEND_POSTGRES:
        return True
    row = connection.execute(
        "SELECT id FROM admin_arquivos WHERE id = ? FOR UPDATE",
        (int(arquivo_id),),
    ).fetchone()
    return row is not None


def lock_requisicao_arquivo(connection, attachment_id: int) -> bool:
    """Lock one ``requisicao_arquivos`` row against concurrent custody changes (PostgreSQL).

    Legacy convergence links a comprovante under this lock; removal and
    request deletion change the same row (``lock_request_attachments``), so
    the two serialize.  SQLite needs no explicit lock.
    """
    if database_engine(connection) != _BACKEND_POSTGRES:
        return True
    row = connection.execute(
        "SELECT id FROM requisicao_arquivos WHERE id = ? FOR UPDATE",
        (int(attachment_id),),
    ).fetchone()
    return row is not None


def lock_request_attachments(connection, request_id: int) -> None:
    """Lock every comprovante row of one request, in id order (PostgreSQL).

    A request deletion takes them before it reads which canonical objects to
    retire: a comprovante linked concurrently (legacy convergence) is then
    either seen and retired, or waits and finds its row gone.  SQLite needs
    no explicit lock.
    """
    if database_engine(connection) != _BACKEND_POSTGRES:
        return
    connection.execute(
        "SELECT id FROM requisicao_arquivos WHERE requisicao_id = ? ORDER BY id FOR UPDATE",
        (int(request_id),),
    ).fetchall()


_SQLITE_CONSTRAINT_NAME_RE = re.compile(r"constraint failed:\s*(.+?)\s*$")
_PG_CONSTRAINT_NAME_RE = re.compile(r'constraint "([^"]+)"')

#: U5-A PostgreSQL trigger functions raise this custom SQLSTATE for business
#: integrity refusals.  It is defined here as a literal so importing
#: ``app.db`` never imports ``app.pg_schema``; ``PG_BUSINESS_RULE_SQLSTATE`` is
#: asserted equal in the U5-B tests.
_PG_BUSINESS_RULE_SQLSTATE = "SG001"

_PG_CONSTRAINT_IDENTITIES = None


def _sqlite_constraint_name(exc):
    match = _SQLITE_CONSTRAINT_NAME_RE.search(str(exc))
    return match.group(1) if match else None


def _sqlite_is_unique(exc) -> bool:
    errorname = str(getattr(exc, "sqlite_errorname", "") or "")
    if "UNIQUE" in errorname or "PRIMARYKEY" in errorname:
        return True
    return "UNIQUE constraint failed" in str(exc)


def _pg_constraint_name(exc):
    diag = getattr(exc, "diag", None)
    name = getattr(diag, "constraint_name", None)
    if name:
        return str(name)
    match = _PG_CONSTRAINT_NAME_RE.search(str(exc))
    return match.group(1) if match else None


def _pg_sqlstate(exc):
    """Structured PostgreSQL SQLSTATE only, never inferred from message text.

    Trusts the psycopg-shaped metadata surfaces ``exc.sqlstate`` and
    ``exc.diag.sqlstate``.  Arbitrary exception text (``str``/``repr``/``args``)
    is never inspected, so an application error whose message happens to
    contain a SQLSTATE-looking token is not reclassified as a database error.
    """
    state = getattr(exc, "sqlstate", None)
    if state:
        return str(state)
    diag = getattr(exc, "diag", None)
    state = getattr(diag, "sqlstate", None)
    if state:
        return str(state)
    return None


def _pg_constraint_identities():
    """Lazily built ``explicit PostgreSQL name -> neutral logical identity``.

    The mapping is derived from the U5-A ``PG_CONSTRAINT_MAP`` (the single
    owner of the explicit stable names) only when a PostgreSQL-shaped name is
    first seen, so importing ``app.db`` on SQLite never imports
    ``app.pg_schema``.  A constraint name absent from the map is left as-is:
    unknown PostgreSQL names stay diagnosable rather than being silently
    misclassified.
    """
    global _PG_CONSTRAINT_IDENTITIES
    if _PG_CONSTRAINT_IDENTITIES is None:
        mapping = {}
        try:
            from app.pg_schema import PG_CONSTRAINT_MAP
        except Exception:  # pragma: no cover - authority always importable
            PG_CONSTRAINT_MAP = {}
        for name, entry in PG_CONSTRAINT_MAP.items():
            table = entry.get("table")
            if not table:
                continue
            fields = entry.get("fields")
            if fields:
                mapping[name] = ", ".join(f"{table}.{field}" for field in fields)
            else:
                mapping[name] = f"{table}.{name}"
        _PG_CONSTRAINT_IDENTITIES = mapping
    return _PG_CONSTRAINT_IDENTITIES


def normalize_constraint_identity(name):
    """Map an engine constraint name to the neutral logical identity.

    SQLite already reports the logical ``table.column`` identity; PostgreSQL
    reports the explicit stable name created by U5-A, which is translated
    through :data:`PG_CONSTRAINT_MAP`.  Unknown names are returned unchanged.
    """
    if not name:
        return None
    text = str(name)
    return _pg_constraint_identities().get(text, text)


def _classified(cls, exc, **kwargs):
    classified = cls(str(exc), **kwargs)
    classified.__cause__ = exc
    return classified


def _psycopg_error_types():
    try:
        import psycopg
        import psycopg.errors
    except ImportError:
        return None
    return psycopg, psycopg.errors


def classify_database_error(exc):
    """Map an engine exception to the neutral class, or ``None`` if unknown."""
    if isinstance(exc, DatabaseAdapterError):
        return exc
    if isinstance(exc, sqlite3.IntegrityError):
        return _classified(
            DatabaseIntegrityError,
            exc,
            constraint_name=_sqlite_constraint_name(exc),
            is_unique=_sqlite_is_unique(exc),
        )
    if isinstance(exc, sqlite3.OperationalError):
        return _classified(DatabaseOperationalError, exc)
    if isinstance(exc, sqlite3.DatabaseError):
        return _classified(DatabaseAdapterError, exc)
    if _pg_sqlstate(exc) == _PG_BUSINESS_RULE_SQLSTATE:
        # U5-A trigger business refusal: an integrity/business failure, never a
        # unique violation.  The trigger message is preserved.
        return _classified(
            DatabaseIntegrityError,
            exc,
            constraint_name=_pg_constraint_name(exc),
            is_unique=False,
        )
    types_ = _psycopg_error_types()
    if types_ is None:
        return None
    psycopg, errors = types_
    if isinstance(exc, errors.UniqueViolation):
        return _classified(
            DatabaseIntegrityError,
            exc,
            constraint_name=_pg_constraint_name(exc),
            is_unique=True,
        )
    if isinstance(exc, errors.IntegrityError):
        return _classified(
            DatabaseIntegrityError,
            exc,
            constraint_name=_pg_constraint_name(exc),
            is_unique=False,
        )
    if isinstance(exc, errors.OperationalError):
        return _classified(DatabaseOperationalError, exc)
    if isinstance(exc, (errors.DatabaseError, psycopg.Error)):
        return _classified(DatabaseAdapterError, exc)
    return None


def is_integrity_error(exc) -> bool:
    return isinstance(classify_database_error(exc), DatabaseIntegrityError)


def is_unique_violation(exc) -> bool:
    classified = classify_database_error(exc)
    return isinstance(classified, DatabaseIntegrityError) and classified.is_unique


def is_operational_error(exc) -> bool:
    return isinstance(classify_database_error(exc), DatabaseOperationalError)


def integrity_constraint_name(exc):
    """The neutral logical identity of the violated constraint, if any.

    SQLite reports ``table.column`` directly; PostgreSQL explicit U5-A names
    are normalised to the same identity so call sites never learn PostgreSQL
    constraint names.
    """
    classified = classify_database_error(exc)
    if isinstance(classified, DatabaseIntegrityError):
        return normalize_constraint_identity(classified.constraint_name)
    return None


class _PostgresCursorAdapter:
    """psycopg 3 cursor with qmark translation and EngineRow results."""

    def __init__(self, cursor):
        self._cursor = cursor

    def execute(self, sql, params=None):
        if params is None:
            self._cursor.execute(sql)
        else:
            self._cursor.execute(adapt_sql_for_postgres(sql), params)
        return self

    def executemany(self, sql, params_seq):
        self._cursor.executemany(adapt_sql_for_postgres(sql), params_seq)
        return self

    def _wrap(self, row):
        if row is None:
            return None
        return engine_row(row, self._cursor.description)

    def fetchone(self):
        return self._wrap(self._cursor.fetchone())

    def fetchmany(self, size=None):
        rows = self._cursor.fetchmany() if size is None else self._cursor.fetchmany(size)
        return [self._wrap(row) for row in rows]

    def fetchall(self):
        return [self._wrap(row) for row in self._cursor.fetchall()]

    def __iter__(self):
        for row in self._cursor:
            yield self._wrap(row)

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class _PostgresConnectionAdapter:
    """psycopg 3 connection exposing the SQLite-era call surface.

    Callers keep ``execute``/``cursor``/``commit``/``rollback``/``close`` and
    ``in_transaction``; SQL is translated and rows are wrapped so the switch to
    PostgreSQL does not require a global call-site rewrite.
    """

    def __init__(self, raw_connection):
        self._raw_connection = raw_connection
        # The natural owner of the write_transaction nesting marker.  The
        # manager claims/releases it per active block; it never leaks past the
        # adapter's lifetime and is not shared between connections.
        self._sgaa_write_transaction_owner = _WRITE_TRANSACTION_UNOWNED

    @property
    def raw_connection(self):
        return self._raw_connection

    def execute(self, sql, params=None):
        cursor = _PostgresCursorAdapter(self._raw_connection.cursor())
        return cursor.execute(sql, params)

    def cursor(self):
        return _PostgresCursorAdapter(self._raw_connection.cursor())

    def executemany(self, sql, params_seq):
        cursor = _PostgresCursorAdapter(self._raw_connection.cursor())
        return cursor.executemany(sql, params_seq)

    def commit(self):
        return self._raw_connection.commit()

    def rollback(self):
        return self._raw_connection.rollback()

    def close(self):
        return self._raw_connection.close()

    @property
    def in_transaction(self):
        return connection_in_transaction(self._raw_connection)

    def __enter__(self):
        self._raw_connection.__enter__()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return self._raw_connection.__exit__(exc_type, exc_value, traceback)

    def __getattr__(self, name):
        return getattr(self._raw_connection, name)


PG_CONNECT_TIMEOUT_ENV = "SGAA_PG_CONNECT_TIMEOUT"
_DEFAULT_PG_CONNECT_TIMEOUT_SECONDS = 10


def _postgres_connect_options(conninfo: str) -> dict:
    """``connect_timeout`` unless the connection string already carries one.

    Without a bound, a paused or unreachable database holds a serverless
    invocation until the platform kills it.
    """
    from psycopg.conninfo import conninfo_to_dict

    if "connect_timeout" in conninfo_to_dict(conninfo) or os.getenv("PGCONNECT_TIMEOUT"):
        return {}
    configured = (os.getenv(PG_CONNECT_TIMEOUT_ENV) or "").strip()
    seconds = int(configured) if re.fullmatch(r"[0-9]+", configured) and int(configured) > 0 else _DEFAULT_PG_CONNECT_TIMEOUT_SECONDS
    return {"connect_timeout": seconds}


def _connect_postgres():
    import psycopg

    raw = psycopg.connect(
        DATABASE_URL,
        prepare_threshold=None,
        autocommit=False,
        **_postgres_connect_options(DATABASE_URL),
    )
    # Configure while IDLE: post-lock latest/current reads require a fresh
    # READ COMMITTED snapshot, regardless of server/role/database defaults.
    try:
        raw.isolation_level = psycopg.IsolationLevel.READ_COMMITTED
    except Exception:
        raw.close()
        raise
    return _PostgresConnectionAdapter(raw)


def get_db_connection():
    if "db" not in g:
        if database_backend() == _BACKEND_POSTGRES:
            g.db = _connect_postgres()
        else:
            # NOTA: uma gravacao longa (ex.: criar dezenas de alunos, cada um com
            # hash PBKDF2 de 600k iteracoes) segura o lock de escrita do SQLite por
            # dezenas de segundos. Com o timeout padrao de 5s qualquer requisicao
            # concorrente morria em "database is locked" (HTTP 500); agora ela espera.
            g.db = sqlite3.connect(DATABASE, timeout=30.0)
            g.db.row_factory = sqlite3.Row
            try:
                register_human_text_sql(g.db)
            except Exception:
                pass
            try:
                g.db.execute("PRAGMA foreign_keys = ON")
                g.db.execute("PRAGMA synchronous = NORMAL")
            except Exception:
                pass
    return g.db


def close_db_connection(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def _app_settings_defaults() -> dict[str, str]:
    return {
        "response_goal_days": str(DEFAULT_RESPONSE_GOAL_DAYS),
        "response_metrics_reset_at": "",
        "return_response_days": str(DEFAULT_RETURN_RESPONSE_DAYS),
        "auto_indefer_devolvida": "0",
        "horas_padrao_academica": str(DEFAULT_HORAS_ACADEMICA),
        "horas_padrao_extensao": str(DEFAULT_HORAS_EXTENSAO),
        # "default_passwords_enabled" is deliberately absent: prod-1/v11
        # retired that switch and its migration deletes the stored row, so
        # seeding it here would resurrect a setting nothing may read.
    }


def ensure_app_settings_schema(conn) -> None:
    if database_engine(conn) != _BACKEND_SQLITE:
        # PostgreSQL runtime: the physical baseline is provisioned by the
        # explicit CLI (U5-A, read-only assertion here).  The application-data
        # default rows are U5-B and are seeded idempotently without ever
        # executing DDL or SQLite-only SQL.
        from app.pg_schema import require_pg_tables

        require_pg_tables(conn, "configuracoes_app")
        for chave, valor in _app_settings_defaults().items():
            conn.execute(
                "INSERT INTO configuracoes_app (chave, valor) VALUES (?, ?) "
                "ON CONFLICT DO NOTHING",
                (chave, valor),
            )
        return
    validate_prod1_schema(conn)
    for chave, valor in _app_settings_defaults().items():
        conn.execute(
            "INSERT INTO configuracoes_app (chave, valor) VALUES (?, ?) "
            "ON CONFLICT DO NOTHING",
            (chave, valor),
        )


def ensure_cloud_backup_schema(conn) -> None:
    if database_engine(conn) != _BACKEND_SQLITE:
        from app.pg_schema import require_pg_tables

        require_pg_tables(conn, "cloud_accounts", "backup_logs", "cloud_drive_settings")
        return
    validate_prod1_schema(conn)


def ensure_turmas_matriz_schema(conn) -> None:
    if database_engine(conn) != _BACKEND_SQLITE:
        from app.pg_schema import require_pg_tables

        require_pg_tables(conn, "turmas", "matrizes_atividades")
        return
    validate_prod1_schema(conn)


def init_db():
    """Bootstrap or validate the empty-only first-production database."""
    if database_backend() != _BACKEND_SQLITE:
        # PostgreSQL boundary: validate the explicitly provisioned baseline and
        # never bootstrap, repair, migrate or execute DDL here.
        from app.pg_schema import PostgresSchemaError, validate_pg_schema

        db = get_db_connection()
        try:
            validate_pg_schema(db)
        except PostgresSchemaError as exc:
            raise RuntimeError(
                "PostgreSQL schema is not provisioned or is incompatible; run "
                "'python -m app.pg_schema provision' explicitly before startup: "
                f"{exc}"
            ) from exc
        finally:
            db.rollback()
        return
    runtime_app = current_app._get_current_object()
    bind_backup_settings_runtime_app(runtime_app)
    conn = get_db_connection()

    apply_early_schema_migrations(conn, logger=logger)
    conn.execute("PRAGMA journal_mode = WAL")

    # The prod-1 bootstrap owns physical schema; these calls only seed defaults.
    ensure_usuario_access_schema(conn)
    ensure_app_settings_schema(conn)
    ensure_backup_settings_schema(conn)

    from presets_api import ensure_presets_schema

    ensure_presets_schema(conn)

    existe_curso = conn.execute("SELECT 1 FROM cursos LIMIT 1").fetchone()
    if not existe_curso:
        conn.execute(
            """
            INSERT INTO cursos (
                nome, codigo, duracao_periodos,
                total_horas_aac, total_horas_aeu, status
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "Geral", "GERAL", 8,
                DEFAULT_CURSO_TOTAL_HORAS_AAC,
                DEFAULT_CURSO_TOTAL_HORAS_AEU,
                "ativo",
            ),
        )

    admin_email = (
        current_app.config.get("BOOTSTRAP_ADMIN_EMAIL") or DEFAULT_ROOT_ADMIN_EMAIL
    ).strip().lower()
    bootstrap_admin = bool(current_app.config.get("BOOTSTRAP_DEFAULT_ADMIN"))
    bootstrap_password = (
        current_app.config.get("BOOTSTRAP_ADMIN_PASSWORD") or ""
    ).strip()
    admin_exists = conn.execute(
        "SELECT 1 FROM usuarios WHERE LOWER(email) = ?", (admin_email,)
    ).fetchone()
    if not admin_exists and bootstrap_admin and bootstrap_password:
        configured_default = _access_defaults_map(conn).get("admin_total", "admin123")
        create_usuario_with_access_level(
            conn,
            "Administrador",
            admin_email,
            hash_password(bootstrap_password),
            "admin",
            "admin_total",
            credential_state=(
                CREDENTIAL_STATE_DEFAULT
                if bootstrap_password == configured_default
                else CREDENTIAL_STATE_PERSONAL
            ),
        )
    elif not admin_exists and not bootstrap_admin:
        logger.warning(
            "Nenhum usuário admin existente e bootstrap automático desabilitado. "
            "Crie um admin manualmente antes do primeiro login produtivo."
        )
    conn.commit()
