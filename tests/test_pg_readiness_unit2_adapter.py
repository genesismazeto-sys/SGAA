# coding: utf-8
"""PostgreSQL-readiness Unit 2: database adapter foundation focus gate.

The unit introduces an engine-neutral adapter foundation in ``app.db`` while
keeping SQLite as the default, behaviourally unchanged runtime:

A. SQLite remains the default backend without ``DATABASE_URL``.
B. SQLite row semantics stay available through the canonical connection owner.
C. qmark -> psycopg placeholder translation is literal-safe: string literals,
   escaped quotes, comments and dollar-quoted bodies keep their ``?``; literal
   percent signs are escaped for psycopg; generated ``%s`` placeholders stay
   intact; dynamic IN lists work.
D. an engine-neutral transaction-state helper serves sqlite3 and psycopg 3.
E. database exceptions classify into engine-neutral classes/accessors.
F. PostgreSQL connection construction uses psycopg 3, receives the configured
   URL, sets ``prepare_threshold=None`` and connects lazily (never on import).
G. SQLite connection ownership and PTBR registration stay valid.

Focused tests use fakes for psycopg connections; no network or Supabase access
is performed.  New ``app.db`` API is accessed through a guarded accessor so the
RED run fails with plain assertions instead of import errors.
"""
import os
import sqlite3
import subprocess
import sys
import types
from pathlib import Path

import pytest

import main
from app import db as app_db

REPO_ROOT = Path(__file__).resolve().parents[1]


def _require(name):
    value = getattr(app_db, name, None)
    assert value is not None, f"app.db.{name} is not implemented yet"
    return value


def _sqlite_connection(monkeypatch):
    monkeypatch.setattr(app_db, "DATABASE_URL", "")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    context = main.app.app_context()
    context.push()
    app_db.close_db_connection(None)
    conn = app_db.get_db_connection()
    return context, conn


def _release_sqlite(context, conn):
    try:
        conn.close()
    finally:
        app_db.close_db_connection(None)
        context.pop()


# ---------------------------------------------------------------------------
# A. backend selection
# ---------------------------------------------------------------------------


def test_backend_defaults_to_sqlite_without_database_url(monkeypatch):
    database_backend = _require("database_backend")
    monkeypatch.setattr(app_db, "DATABASE_URL", "")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert database_backend() == "sqlite"


def test_database_url_postgres_selects_postgres_backend(monkeypatch):
    database_backend = _require("database_backend")
    monkeypatch.setattr(
        app_db, "DATABASE_URL", "postgresql://user:secret@localhost:6543/postgres"
    )
    assert database_backend() == "postgres"


def test_unsupported_database_url_scheme_is_rejected_without_leaking_credentials(
    monkeypatch,
):
    database_backend = _require("database_backend")
    monkeypatch.setattr(
        app_db, "DATABASE_URL", "mysql://user:secret@localhost:3306/db"
    )
    with pytest.raises(ValueError) as excinfo:
        database_backend()
    assert "secret" not in str(excinfo.value)


def test_unsupported_uri_scheme_error_mentions_only_the_scheme(monkeypatch):
    database_backend = _require("database_backend")
    monkeypatch.setattr(
        app_db, "DATABASE_URL", "mysql://user:secret@example.invalid/db"
    )
    with pytest.raises(ValueError) as excinfo:
        database_backend()
    message = str(excinfo.value)
    assert "mysql" in message
    for leaked in ("user", "secret", "example.invalid", "mysql://user"):
        assert leaked not in message


def test_keyword_dsn_error_does_not_leak_any_dsn_fragment(monkeypatch):
    database_backend = _require("database_backend")
    monkeypatch.setattr(
        app_db,
        "DATABASE_URL",
        "host=db.example.invalid password=secret dbname=postgres",
    )
    with pytest.raises(ValueError) as excinfo:
        database_backend()
    message = str(excinfo.value)
    for leaked in ("host", "db.example.invalid", "password", "secret", "dbname", "postgres"):
        assert leaked not in message


def test_bare_token_error_does_not_echo_the_value(monkeypatch):
    database_backend = _require("database_backend")
    monkeypatch.setattr(app_db, "DATABASE_URL", "super-secret-token")
    with pytest.raises(ValueError) as excinfo:
        database_backend()
    assert "super-secret-token" not in str(excinfo.value)
    assert "secret" not in str(excinfo.value)


def test_keyword_dsn_with_colon_password_does_not_leak_fragments(monkeypatch):
    database_backend = _require("database_backend")
    monkeypatch.setattr(
        app_db,
        "DATABASE_URL",
        "host=db.example.invalid password=se:cret dbname=postgres",
    )
    with pytest.raises(ValueError) as excinfo:
        database_backend()
    message = str(excinfo.value)
    for leaked in ("host=", "db.example.invalid", "se:cret", "cret", "postgres"):
        assert leaked not in message


# ---------------------------------------------------------------------------
# B + G. SQLite ownership, row semantics and PTBR
# ---------------------------------------------------------------------------


def test_sqlite_default_connection_keeps_ownership_and_row_semantics(monkeypatch):
    context, conn = _sqlite_connection(monkeypatch)
    try:
        assert isinstance(conn, sqlite3.Connection)
        assert conn.row_factory is sqlite3.Row
        row = conn.execute("SELECT 1 AS alpha, 'x' AS beta").fetchone()
        assert row["alpha"] == 1
        assert row[0] == 1
        assert list(row.keys()) == ["alpha", "beta"]
        assert dict(row) == {"alpha": 1, "beta": "x"}
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        _release_sqlite(context, conn)


def test_sqlite_connection_still_registers_ptbr(monkeypatch):
    context, conn = _sqlite_connection(monkeypatch)
    try:
        assert conn.execute("SELECT 'á' = 'a' COLLATE PTBR_NOACCENT").fetchone()[0] == 1
        assert conn.execute("SELECT PTBR_FOLD('ÁçãO')").fetchone()[0] == "acao"
    finally:
        _release_sqlite(context, conn)


# ---------------------------------------------------------------------------
# C. qmark -> psycopg placeholder translation
# ---------------------------------------------------------------------------


def test_translate_single_and_multiple_placeholders():
    adapt = _require("adapt_sql_for_postgres")
    assert (
        adapt("SELECT * FROM t WHERE a=? AND b=?")
        == "SELECT * FROM t WHERE a=%s AND b=%s"
    )


def test_translate_dynamic_in_list():
    adapt = _require("adapt_sql_for_postgres")
    placeholders = ", ".join("?" for _ in range(4))
    expected = ", ".join("%s" for _ in range(4))
    assert adapt(f"SELECT id FROM t WHERE id IN ({placeholders})") == (
        f"SELECT id FROM t WHERE id IN ({expected})"
    )


def test_question_mark_inside_single_quoted_literal_is_not_converted():
    adapt = _require("adapt_sql_for_postgres")
    assert (
        adapt("SELECT '?' AS q, x FROM t WHERE x=?")
        == "SELECT '?' AS q, x FROM t WHERE x=%s"
    )


def test_escaped_quotes_protect_the_question_mark():
    adapt = _require("adapt_sql_for_postgres")
    assert (
        adapt("SELECT 'it''s ?' AS q FROM t WHERE x=?")
        == "SELECT 'it''s ?' AS q FROM t WHERE x=%s"
    )


def test_question_mark_inside_double_quoted_identifier_is_not_converted():
    adapt = _require("adapt_sql_for_postgres")
    assert (
        adapt('SELECT "we?ird" FROM t WHERE x=?')
        == 'SELECT "we?ird" FROM t WHERE x=%s'
    )


def test_question_mark_inside_comments_is_not_converted():
    adapt = _require("adapt_sql_for_postgres")
    assert (
        adapt("SELECT 1 -- what?\nFROM t WHERE x=?")
        == "SELECT 1 -- what?\nFROM t WHERE x=%s"
    )
    assert (
        adapt("SELECT /* ? */ 1 FROM t WHERE x=?")
        == "SELECT /* ? */ 1 FROM t WHERE x=%s"
    )


def test_question_mark_inside_dollar_quoted_body_is_not_converted():
    adapt = _require("adapt_sql_for_postgres")
    assert (
        adapt("SELECT $$?$$, x FROM t WHERE x=?")
        == "SELECT $$?$$, x FROM t WHERE x=%s"
    )


def test_literal_percent_is_escaped_for_psycopg():
    adapt = _require("adapt_sql_for_postgres")
    assert (
        adapt("SELECT * FROM t WHERE a=? AND b LIKE '100%'")
        == "SELECT * FROM t WHERE a=%s AND b LIKE '100%%'"
    )


def test_generated_placeholders_are_exactly_percent_s():
    adapt = _require("adapt_sql_for_postgres")
    adapted = adapt("SELECT * FROM t WHERE a=? AND b=?")
    assert adapted.count("%s") == 2
    assert "%%s" not in adapted


def test_zero_placeholder_sql_is_unchanged():
    adapt = _require("adapt_sql_for_postgres")
    assert adapt("SELECT 1") == "SELECT 1"
    assert adapt("SELECT 'plain text'") == "SELECT 'plain text'"


# ---------------------------------------------------------------------------
# D. transaction-state helper
# ---------------------------------------------------------------------------


def _status_connection(name):
    class _Status:
        pass

    status = _Status()
    status.name = name
    raw = types.SimpleNamespace()
    raw.info = types.SimpleNamespace(transaction_status=status)
    return raw


def test_connection_in_transaction_for_sqlite():
    helper = _require("connection_in_transaction")
    conn = sqlite3.connect(":memory:")
    try:
        assert helper(conn) is False
        conn.execute("CREATE TABLE t(x)")
        conn.execute("INSERT INTO t VALUES (1)")
        assert helper(conn) is True
        conn.commit()
        assert helper(conn) is False
    finally:
        conn.close()


def test_connection_in_transaction_for_psycopg_status():
    helper = _require("connection_in_transaction")
    assert helper(_status_connection("INTRANS")) is True
    assert helper(_status_connection("INERROR")) is True
    assert helper(_status_connection("IDLE")) is False
    assert helper(_status_connection("UNKNOWN")) is False


def test_postgres_adapter_exposes_in_transaction_property():
    adapter_cls = _require("_PostgresConnectionAdapter")
    raw = _status_connection("INTRANS")
    raw.close = lambda: None
    adapter = adapter_cls(raw)
    assert adapter.in_transaction is True


# ---------------------------------------------------------------------------
# E. exception classification
# ---------------------------------------------------------------------------


def test_sqlite_unique_integrity_error_is_classified_with_constraint_name():
    classify = _require("classify_database_error")
    integrity_cls = _require("DatabaseIntegrityError")
    exc = sqlite3.IntegrityError("UNIQUE constraint failed: usuarios.email")
    classified = classify(exc)
    assert isinstance(classified, integrity_cls)
    assert _require("is_integrity_error")(exc) is True
    assert _require("is_unique_violation")(exc) is True
    assert _require("integrity_constraint_name")(exc) == "usuarios.email"


def test_sqlite_not_null_integrity_error_is_not_unique():
    exc = sqlite3.IntegrityError("NOT NULL constraint failed: alunos.nome")
    assert _require("is_integrity_error")(exc) is True
    assert _require("is_unique_violation")(exc) is False
    assert _require("integrity_constraint_name")(exc) == "alunos.nome"


def test_sqlite_operational_error_is_classified():
    classify = _require("classify_database_error")
    operational_cls = _require("DatabaseOperationalError")
    exc = sqlite3.OperationalError("database is locked")
    assert isinstance(classify(exc), operational_cls)
    assert _require("is_operational_error")(exc) is True


def test_unknown_exception_is_not_classified():
    classify = _require("classify_database_error")
    assert classify(ValueError("not a database error")) is None


def test_psycopg_unique_violation_is_classified_with_constraint_name():
    import psycopg.errors

    classify = _require("classify_database_error")
    integrity_cls = _require("DatabaseIntegrityError")
    exc = psycopg.errors.UniqueViolation(
        'duplicate key value violates unique constraint "usuarios_email_key"'
    )
    assert isinstance(classify(exc), integrity_cls)
    assert _require("is_integrity_error")(exc) is True
    assert _require("is_unique_violation")(exc) is True
    assert _require("integrity_constraint_name")(exc) == "usuarios_email_key"


def test_psycopg_operational_error_is_classified():
    import psycopg.errors

    classify = _require("classify_database_error")
    operational_cls = _require("DatabaseOperationalError")
    exc = psycopg.errors.OperationalError("connection failed")
    assert isinstance(classify(exc), operational_cls)
    assert _require("is_operational_error")(exc) is True


# ---------------------------------------------------------------------------
# F. PostgreSQL connection construction (fakes only)
# ---------------------------------------------------------------------------


def _fake_psycopg(monkeypatch, opened):
    fake = types.ModuleType("psycopg")

    class _FakeRaw:
        def __init__(self):
            self.query_log = []

        def cursor(self):
            return types.SimpleNamespace()

        def close(self):
            pass

    def _fake_connect(url, **kwargs):
        opened.append((url, kwargs))
        return _FakeRaw()

    fake.connect = _fake_connect
    monkeypatch.setitem(sys.modules, "psycopg", fake)
    return fake


def test_postgres_connect_uses_psycopg_url_and_prepare_threshold(monkeypatch):
    connect = _require("_connect_postgres")
    adapter_cls = _require("_PostgresConnectionAdapter")
    url = "postgresql://user:secret@localhost:6543/postgres?sslmode=disable"
    monkeypatch.setattr(app_db, "DATABASE_URL", url)
    opened = []
    _fake_psycopg(monkeypatch, opened)

    conn = connect()
    try:
        assert isinstance(conn, adapter_cls)
        assert len(opened) == 1
        assert opened[0][0] == url
        assert opened[0][1].get("prepare_threshold", "missing") is None
        assert opened[0][1].get("autocommit", "missing") is False
    finally:
        conn.close()


def test_get_db_connection_uses_postgres_adapter_when_configured(monkeypatch):
    adapter_cls = _require("_PostgresConnectionAdapter")
    url = "postgresql://user:secret@localhost:6543/postgres"
    monkeypatch.setattr(app_db, "DATABASE_URL", url)
    opened = []
    _fake_psycopg(monkeypatch, opened)

    with main.app.app_context():
        app_db.close_db_connection(None)
        conn = app_db.get_db_connection()
        try:
            assert isinstance(conn, adapter_cls)
            assert [entry[0] for entry in opened] == [url]
        finally:
            app_db.close_db_connection(None)


def test_importing_app_db_does_not_import_or_connect_psycopg(monkeypatch):
    code = (
        "import sys\n"
        "import app.db\n"
        "print('PSYCOPG_IMPORTED=' + str('psycopg' in sys.modules))\n"
        "print('HAS_DATABASE_URL=' + str(hasattr(app.db, 'DATABASE_URL')))\n"
    )
    environment = dict(os.environ)
    environment["DATABASE_URL"] = "postgresql://user:secret@localhost:6543/postgres"
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT),
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "PSYCOPG_IMPORTED=False" in result.stdout
    assert "HAS_DATABASE_URL=True" in result.stdout


# ---------------------------------------------------------------------------
# Adapter mechanics: translation + row wrapping over a fake engine
# ---------------------------------------------------------------------------


class _FakeEngineCursor:
    def __init__(self):
        self.executed = []
        self.description = None
        self._rows = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        self.description = [("alpha",), ("beta",)]
        self._rows = [(1, "x")]
        return self

    def executemany(self, sql, seq):
        self.executed.append((sql, list(seq)))
        return self

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


class _FakeEngineConnection:
    def __init__(self):
        self._cursor = _FakeEngineCursor()
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def test_postgres_adapter_translates_sql_and_wraps_rows():
    adapter_cls = _require("_PostgresConnectionAdapter")
    raw = _FakeEngineConnection()
    adapter = adapter_cls(raw)

    cursor = adapter.execute("SELECT * FROM t WHERE a=? AND b=?", (1, 2))
    assert raw._cursor.executed[-1] == (
        "SELECT * FROM t WHERE a=%s AND b=%s",
        (1, 2),
    )

    row = cursor.fetchone()
    assert row["alpha"] == 1
    assert row[0] == 1
    assert list(row.keys()) == ["alpha", "beta"]
    assert dict(row) == {"alpha": 1, "beta": "x"}
    assert [tuple(item) for item in cursor.fetchall()] == [(1, "x")]

    adapter.commit()
    adapter.rollback()
    adapter.close()
    assert (raw.commits, raw.rollbacks, raw.closed) == (1, 1, True)


def test_postgres_adapter_passes_parameterless_sql_untouched():
    adapter_cls = _require("_PostgresConnectionAdapter")
    raw = _FakeEngineConnection()
    adapter = adapter_cls(raw)
    adapter.execute("SELECT 1 FROM t -- 100%")
    assert raw._cursor.executed[-1] == ("SELECT 1 FROM t -- 100%", None)


def test_engine_row_supports_sqlite_row_semantics():
    row_cls = _require("EngineRow")
    row = row_cls((1, "x", 3), ["alpha", "beta", "gamma"])
    assert row["alpha"] == 1
    assert row["ALPHA"] == 1
    assert row[0] == 1
    assert row[-1] == 3
    assert list(row.keys()) == ["alpha", "beta", "gamma"]
    assert dict(row) == {"alpha": 1, "beta": "x", "gamma": 3}
    assert list(row) == [1, "x", 3]

    duplicate = row_cls((1, 2), ["a", "a"])
    assert duplicate["a"] == 1
    assert list(duplicate.keys()) == ["a", "a"]
