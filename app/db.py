import logging
import os
import re
import sqlite3
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


_TRANSACTIONAL_STATUS_NAMES = frozenset({"INTRANS", "INERROR"})


def connection_in_transaction(connection) -> bool:
    """Engine-neutral ``connection.in_transaction`` equivalent."""
    if isinstance(connection, _PostgresConnectionAdapter):
        connection = connection.raw_connection
    if isinstance(connection, sqlite3.Connection):
        return bool(connection.in_transaction)
    status = getattr(getattr(connection, "info", None), "transaction_status", None)
    status_name = getattr(status, "name", None)
    if status_name is not None:
        return status_name in _TRANSACTIONAL_STATUS_NAMES
    return bool(getattr(connection, "in_transaction", False))


_SQLITE_CONSTRAINT_NAME_RE = re.compile(r"constraint failed:\s*(.+?)\s*$")
_PG_CONSTRAINT_NAME_RE = re.compile(r'constraint "([^"]+)"')


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


def _psycopg_error_types():
    try:
        import psycopg
        import psycopg.errors
    except ImportError:
        return None
    return psycopg, psycopg.errors


def classify_database_error(exc):
    """Map an engine exception to the neutral class, or ``None`` if unknown."""
    if isinstance(exc, sqlite3.IntegrityError):
        return DatabaseIntegrityError(
            str(exc),
            constraint_name=_sqlite_constraint_name(exc),
            is_unique=_sqlite_is_unique(exc),
        )
    if isinstance(exc, sqlite3.OperationalError):
        return DatabaseOperationalError(str(exc))
    if isinstance(exc, sqlite3.DatabaseError):
        return DatabaseAdapterError(str(exc))
    types_ = _psycopg_error_types()
    if types_ is None:
        return None
    psycopg, errors = types_
    if isinstance(exc, errors.UniqueViolation):
        return DatabaseIntegrityError(
            str(exc), constraint_name=_pg_constraint_name(exc), is_unique=True
        )
    if isinstance(exc, errors.IntegrityError):
        return DatabaseIntegrityError(
            str(exc), constraint_name=_pg_constraint_name(exc), is_unique=False
        )
    if isinstance(exc, errors.OperationalError):
        return DatabaseOperationalError(str(exc))
    if isinstance(exc, (errors.DatabaseError, psycopg.Error)):
        return DatabaseAdapterError(str(exc))
    return None


def is_integrity_error(exc) -> bool:
    return isinstance(classify_database_error(exc), DatabaseIntegrityError)


def is_unique_violation(exc) -> bool:
    classified = classify_database_error(exc)
    return isinstance(classified, DatabaseIntegrityError) and classified.is_unique


def is_operational_error(exc) -> bool:
    return isinstance(classify_database_error(exc), DatabaseOperationalError)


def integrity_constraint_name(exc):
    classified = classify_database_error(exc)
    if isinstance(classified, DatabaseIntegrityError):
        return classified.constraint_name
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


def _connect_postgres():
    import psycopg

    return _PostgresConnectionAdapter(
        psycopg.connect(DATABASE_URL, prepare_threshold=None, autocommit=False)
    )


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
    validate_prod1_schema(conn)
    for chave, valor in _app_settings_defaults().items():
        conn.execute(
            "INSERT OR IGNORE INTO configuracoes_app (chave, valor) VALUES (?, ?)",
            (chave, valor),
        )


def ensure_cloud_backup_schema(conn) -> None:
    validate_prod1_schema(conn)


def ensure_turmas_matriz_schema(conn) -> None:
    validate_prod1_schema(conn)


def init_db():
    """Bootstrap or validate the empty-only first-production database."""
    if database_backend() != _BACKEND_SQLITE:
        raise RuntimeError(
            "PostgreSQL schema bootstrap is not implemented in this runtime yet"
        )
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
