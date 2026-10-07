# coding: utf-8
"""E-PG1 phase 2: the missing single-connection real-PostgreSQL contracts M1-M9.

Runs only when ``SGAA_PG_TEST_URL`` supplies a local PostgreSQL role with
CREATE DATABASE; otherwise the whole module skips (REAL-PG EVIDENCE: ABSENT).
The URL is server access only: nothing is ever written into the database it
names.  Every test works in databases this run creates under a random per-run
prefix, records in a session registry, and drops at teardown; the registry
refuses to drop anything it did not create or that the connected role does not
own, and the session ends by asserting no run-owned database is left.

Overlap with the existing E-PG1 lanes (U5-A 33 nodes, U5-D 12 nodes) is
deliberately not repeated:

* U5-A already proves that real violations carry the explicit constraint names
  and that triggers raise SG001.  M1 here proves only the missing edge: those
  real exceptions through production ``classify_database_error`` and the
  ``PG_CONSTRAINT_MAP`` identity normalisation.
* U5-A proves ``sgaa_utcnow_text()`` directly and that the ``ensure_*`` paths
  run no DDL.  M5 proves the production *fragments* through the production
  adapter against an SQLite oracle; M7 proves the separate question of whether
  the lazy default *DML* persists across the caller's commit boundary.
* U5-A proves ``validate_pg_schema``; ``pg_schema_status`` (M6) is a distinct,
  lighter owner with no real-PG evidence until now.

Everything runs through the production owners (``app.db._connect_postgres``,
``_PostgresConnectionAdapter``, ``write_transaction``, ``app.sql_dialect``,
``app.pg_schema``, the settings/access/backup seeders and the real
``/admin/acesso/salvar`` route).  No psycopg exception is constructed by hand.
"""
from __future__ import annotations

import os
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

import pytest

PG_URL = os.environ.get("SGAA_PG_TEST_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not PG_URL,
    reason="SGAA_PG_TEST_URL is not configured -- REAL-PG EVIDENCE: ABSENT",
)

psycopg = pytest.importorskip("psycopg")

from app import db as app_db  # noqa: E402
from app import pg_schema  # noqa: E402
from app import sql_dialect  # noqa: E402

#: Every database this run creates carries this prefix (random per run).
RUN_PREFIX = f"sgaa_epg1m_test_{secrets.token_hex(4)}_"
PROTECTED_DATABASES = frozenset({"postgres", "template0", "template1", "sgaa_qual"})
CONNECT_TIMEOUT_SECONDS = 10
CANONICAL_UTC_TEXT_RE = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")


def _database_url(database):
    parts = urlsplit(PG_URL)
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            "/" + database,
            f"connect_timeout={CONNECT_TIMEOUT_SECONDS}",
            "",
        )
    )


def _raw_connect(url, *, autocommit=False):
    return psycopg.connect(
        url,
        prepare_threshold=None,
        autocommit=autocommit,
        connect_timeout=CONNECT_TIMEOUT_SECONDS,
    )


def _production_connection(url):
    """A connection from the production factory (``_connect_postgres``)."""
    previous = app_db.DATABASE_URL
    app_db.DATABASE_URL = url
    try:
        return app_db._connect_postgres()
    finally:
        app_db.DATABASE_URL = previous


class _RunDatabaseRegistry:
    """Sole creator and destroyer of this run's disposable databases."""

    def __init__(self):
        self._admin = None
        self._owned = set()

    def admin(self):
        if self._admin is None or self._admin.closed:
            self._admin = _raw_connect(PG_URL, autocommit=True)
        return self._admin

    def create(self, label):
        database = f"{RUN_PREFIX}{label}_{secrets.token_hex(4)}"
        self.admin().execute(f'CREATE DATABASE "{database}"')
        self._owned.add(database)
        return database, _database_url(database)

    def create_provisioned(self, label):
        database, url = self.create(label)
        connection = _raw_connect(url)
        try:
            result = pg_schema.provision_pg_schema(connection)
            connection.commit()
        finally:
            connection.close()
        assert result["status"] == "provisioned"
        return database, url

    def drop(self, database):
        if database in PROTECTED_DATABASES or not database.startswith(RUN_PREFIX):
            raise AssertionError(f"refusing to drop {database!r}: not run-owned")
        if database not in self._owned:
            raise AssertionError(f"refusing to drop {database!r}: not created by this run")
        row = self.admin().execute(
            "SELECT pg_get_userbyid(datdba) = current_user FROM pg_database "
            "WHERE datname = %s",
            (database,),
        ).fetchone()
        if row is not None and not row[0]:
            raise AssertionError(f"refusing to drop {database!r}: not owned by this role")
        self.admin().execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
        self._owned.discard(database)

    def leftovers(self):
        rows = self.admin().execute(
            "SELECT datname FROM pg_database WHERE starts_with(datname, %s)",
            (RUN_PREFIX,),
        ).fetchall()
        return sorted(row[0] for row in rows)

    def close(self):
        failures = []
        for database in sorted(self._owned):
            try:
                self.drop(database)
            except Exception as exc:  # pragma: no cover - teardown reporting
                failures.append((database, repr(exc)))
        leftovers = self.leftovers() if not failures else []
        if self._admin is not None and not self._admin.closed:
            self._admin.close()
        assert not failures, f"could not drop run-owned databases: {failures!r}"
        assert not leftovers, f"run-owned databases left behind: {leftovers!r}"


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def registry():
    run = _RunDatabaseRegistry()
    try:
        try:
            run.admin()
        except psycopg.Error as exc:
            pytest.skip(f"SGAA_PG_TEST_URL is not a usable PostgreSQL connection: {exc}")
        yield run
    finally:
        run.close()


@pytest.fixture(scope="module")
def shared_url(registry):
    """One provisioned run-owned database for the low-level M1-M6 cases."""
    database, url = registry.create_provisioned("shared")
    try:
        yield url
    finally:
        registry.drop(database)


@pytest.fixture()
def fresh_url(registry):
    """A newly provisioned run-owned database with no application rows."""
    database, url = registry.create_provisioned("fresh")
    try:
        yield url
    finally:
        registry.drop(database)


@pytest.fixture()
def empty_url(registry):
    """A run-owned database that was never provisioned."""
    database, url = registry.create("empty")
    try:
        yield url
    finally:
        registry.drop(database)


@pytest.fixture()
def conn(shared_url):
    connection = _production_connection(shared_url)
    try:
        yield connection
    finally:
        try:
            connection.rollback()
        finally:
            connection.close()


@pytest.fixture()
def inspector(shared_url):
    connection = _raw_connect(shared_url, autocommit=True)
    try:
        yield connection
    finally:
        connection.close()


def _raw_status(connection):
    return connection.raw_connection.info.transaction_status.name


def _assigned_xid(connection):
    return connection.raw_connection.execute(
        "SELECT pg_current_xact_id_if_assigned()"
    ).fetchone()[0]


def _unique(label):
    return f"EPG1 {label} {secrets.token_hex(4)}"


def _count_named(inspector, nome):
    return inspector.execute(
        "SELECT count(*) FROM atividade_base WHERE nome_conceito = %s", (nome,)
    ).fetchone()[0]


# ===========================================================================
# M8 -- version floor (first: everything else is meaningless off PG15)
# ===========================================================================


def test_m8_server_is_postgresql_15(conn):
    version_num = int(conn.execute("SHOW server_version_num").fetchone()[0])
    assert version_num >= 150000, version_num
    assert version_num < 160000, f"qualification lane expects PG15, got {version_num}"
    assert int(
        conn.execute("SELECT current_setting('server_version_num')").fetchone()[0]
    ) == version_num


# ===========================================================================
# M1 -- real error classification
# ===========================================================================


def _real_error(connection, sql, params=None):
    """Execute through the production adapter and return the server's error."""
    connection.execute("SAVEPOINT epg1_m1")
    try:
        connection.execute(sql, params)
    except psycopg.Error as exc:
        connection.execute("ROLLBACK TO SAVEPOINT epg1_m1")
        connection.execute("RELEASE SAVEPOINT epg1_m1")
        assert exc.diag.severity_nonlocalized == "ERROR", exc
        assert exc.diag.message_primary, exc
        assert exc.diag.sqlstate == exc.sqlstate
        return exc
    raise AssertionError(f"statement unexpectedly succeeded: {sql}")


def _assert_classified(exc, *, unique, constraint, identity):
    classified = app_db.classify_database_error(exc)
    assert isinstance(classified, app_db.DatabaseIntegrityError), classified
    assert classified.__cause__ is exc
    assert classified.is_unique is unique
    assert classified.constraint_name == constraint
    assert app_db.is_integrity_error(exc) is True
    assert app_db.is_unique_violation(exc) is unique
    assert app_db.is_operational_error(exc) is False
    assert app_db.integrity_constraint_name(exc) == identity
    return classified


def test_m1_unique_violation_23505_is_classified_unique(conn):
    conn.execute(
        "INSERT INTO usuarios(nome,email,senha,tipo) VALUES(?,?,?,?)",
        ("A", "m1.dup@epg1.test", "hash", "admin"),
    )
    exc = _real_error(
        conn,
        "INSERT INTO usuarios(nome,email,senha,tipo) VALUES(?,?,?,?)",
        ("B", "m1.dup@epg1.test", "hash", "admin"),
    )
    assert exc.sqlstate == "23505"
    assert isinstance(exc, psycopg.errors.UniqueViolation)
    assert exc.diag.constraint_name == "uq_usuarios_email"
    assert exc.diag.table_name == "usuarios"
    entry = pg_schema.PG_CONSTRAINT_MAP["uq_usuarios_email"]
    assert entry["kind"] == "unique" and entry["fields"] == ["email"]
    _assert_classified(
        exc, unique=True, constraint="uq_usuarios_email", identity="usuarios.email"
    )


def test_m1_foreign_key_violation_23503_is_classified_integrity(conn):
    exc = _real_error(
        conn,
        "INSERT INTO alunos(nome,matricula,turma_id) VALUES(?,?,?)",
        ("A", "M1-FK", 999999),
    )
    assert exc.sqlstate == "23503"
    assert isinstance(exc, psycopg.errors.ForeignKeyViolation)
    assert exc.diag.constraint_name == "fk_alunos_turma_id"
    assert pg_schema.PG_CONSTRAINT_MAP["fk_alunos_turma_id"]["kind"] == "foreign_key"
    _assert_classified(
        exc, unique=False, constraint="fk_alunos_turma_id", identity="alunos.turma_id"
    )


def test_m1_check_violation_23514_is_classified_integrity(conn):
    exc = _real_error(
        conn,
        "INSERT INTO usuarios(nome,email,senha,tipo) VALUES(?,?,?,?)",
        ("C", "m1.check@epg1.test", "hash", "root"),
    )
    assert exc.sqlstate == "23514"
    assert isinstance(exc, psycopg.errors.CheckViolation)
    assert exc.diag.constraint_name == "ck_usuarios_tipo"
    assert pg_schema.PG_CONSTRAINT_MAP["ck_usuarios_tipo"]["kind"] == "check"
    _assert_classified(
        exc,
        unique=False,
        constraint="ck_usuarios_tipo",
        identity="usuarios.ck_usuarios_tipo",
    )


def test_m1_not_null_violation_23502_is_classified_integrity(conn):
    exc = _real_error(
        conn,
        "INSERT INTO usuarios(nome,email,senha) VALUES(?,?,?)",
        ("D", "m1.null@epg1.test", "hash"),
    )
    assert exc.sqlstate == "23502"
    assert isinstance(exc, psycopg.errors.NotNullViolation)
    assert exc.diag.table_name == "usuarios"
    assert exc.diag.column_name == "tipo"
    # PostgreSQL names no constraint for NOT NULL; nothing is invented.
    assert exc.diag.constraint_name is None
    _assert_classified(exc, unique=False, constraint=None, identity=None)


def test_m1_trigger_sg001_is_classified_business_integrity(conn):
    exc = _real_error(
        conn,
        "INSERT INTO admin_arquivos(titulo,filename,remote_file_id) VALUES(?,?,?)",
        ("A", "a.pdf", "remote"),
    )
    assert exc.sqlstate == pg_schema.PG_BUSINESS_RULE_SQLSTATE == "SG001"
    # SG001 is not a standard integrity class: psycopg cannot map it to
    # IntegrityError, so the classification must come from the SQLSTATE.
    assert not isinstance(exc, psycopg.errors.IntegrityError)
    classified = _assert_classified(
        exc,
        unique=False,
        constraint=exc.diag.constraint_name,
        identity=app_db.normalize_constraint_identity(exc.diag.constraint_name),
    )
    assert str(classified) == str(exc)
    assert exc.diag.message_primary in str(classified)
    # The connection is still usable after every probe.
    assert conn.execute("SELECT 1").fetchone()[0] == 1


# ===========================================================================
# M2 -- INERROR recovery through write_transaction
# ===========================================================================


def test_m2_inerror_before_block_is_rolled_back_on_entry(conn, inspector):
    with pytest.raises(psycopg.errors.DivisionByZero):
        conn.execute("SELECT 1/0")
    assert _raw_status(conn) == "INERROR"
    assert app_db.connection_transaction_status(conn) == "INERROR"

    nome = _unique("m2a")
    with app_db.write_transaction(conn) as tx:
        assert tx is conn
        assert _raw_status(conn) == "IDLE"
        tx.execute("INSERT INTO atividade_base(nome_conceito) VALUES(?)", (nome,))

    assert _raw_status(conn) == "IDLE"
    assert _count_named(inspector, nome) == 1
    assert conn.execute("SELECT 1").fetchone()[0] == 1
    conn.rollback()
    with app_db.write_transaction(conn):
        conn.execute("SELECT 1")


def test_m2_block_leaving_inerror_raises_state_error_and_rolls_back(conn, inspector):
    nome = _unique("m2b")
    with pytest.raises(app_db.DatabaseTransactionStateError):
        with app_db.write_transaction(conn):
            conn.execute("INSERT INTO atividade_base(nome_conceito) VALUES(?)", (nome,))
            try:
                conn.execute("SELECT 1/0")
            except psycopg.errors.DivisionByZero:
                pass  # a swallowed error must not let the block report success
            assert _raw_status(conn) == "INERROR"

    assert _raw_status(conn) == "IDLE"
    assert _count_named(inspector, nome) == 0
    assert conn.execute("SELECT 1").fetchone()[0] == 1
    conn.rollback()
    # The owner marker was released: the connection is reusable for writes.
    after = _unique("m2b-after")
    with app_db.write_transaction(conn):
        conn.execute("INSERT INTO atividade_base(nome_conceito) VALUES(?)", (after,))
    assert _count_named(inspector, after) == 1


# ===========================================================================
# M3 -- write_transaction adoption / refusal
# ===========================================================================


def test_m3_read_only_intrans_is_adopted(conn, inspector):
    conn.execute("SELECT count(*) FROM atividade_base").fetchone()
    assert _raw_status(conn) == "INTRANS"
    assert _assigned_xid(conn) is None
    started = conn.execute("SELECT transaction_timestamp()").fetchone()[0]

    nome = _unique("m3a")
    with app_db.write_transaction(conn):
        # Same transaction: the block adopted it rather than starting another.
        assert conn.execute("SELECT transaction_timestamp()").fetchone()[0] == started
        conn.execute("INSERT INTO atividade_base(nome_conceito) VALUES(?)", (nome,))

    assert _raw_status(conn) == "IDLE"
    assert _count_named(inspector, nome) == 1


def test_m3_caller_owned_dml_with_assigned_xid_is_refused(conn, inspector):
    nome = _unique("m3b")
    conn.execute("INSERT INTO atividade_base(nome_conceito) VALUES(?)", (nome,))
    assert _raw_status(conn) == "INTRANS"
    assert _assigned_xid(conn) is not None

    body_ran = False
    with pytest.raises(app_db.DatabaseTransactionStateError):
        with app_db.write_transaction(conn):
            body_ran = True
    assert body_ran is False
    # Refusal neither commits nor discards the caller's transaction.
    assert _raw_status(conn) == "INTRANS"
    assert _count_named(inspector, nome) == 0
    conn.rollback()
    assert _count_named(inspector, nome) == 0
    with app_db.write_transaction(conn):
        conn.execute("SELECT 1")


def test_m3_caller_held_row_lock_with_assigned_xid_is_refused(conn, inspector):
    nome = _unique("m3c")
    with app_db.write_transaction(conn):
        base_id = conn.execute(
            "INSERT INTO atividade_base(nome_conceito) VALUES(?) RETURNING id", (nome,)
        ).fetchone()[0]

    conn.execute("SELECT count(*) FROM atividade_base").fetchone()
    assert _assigned_xid(conn) is None
    # Production lock owner; on this server FOR NO KEY UPDATE assigns an XID,
    # so a caller already holding the lock owns locking work.
    assert app_db.lock_activity_base(conn, base_id) is True
    assert _assigned_xid(conn) is not None
    with pytest.raises(app_db.DatabaseTransactionStateError):
        with app_db.write_transaction(conn):
            raise AssertionError("refused block must not run")
    conn.rollback()
    assert _raw_status(conn) == "IDLE"


# ===========================================================================
# M4 -- adapter edge cases on the real server
# ===========================================================================


def test_m4_qmark_translation_and_percent_literals(conn):
    row = conn.execute("SELECT ? + ? AS total, ? AS label", (2, 3, "x")).fetchone()
    assert tuple(row) == (5, "x")
    assert tuple(conn.execute("SELECT 7 % 3 AS m, ? AS p", ("v",)).fetchone()) == (1, "v")
    assert tuple(conn.execute("SELECT '%' AS pct, '?' AS q").fetchone()) == ("%", "?")

    conn.execute("CREATE TEMP TABLE epg1_m4(nome text) ON COMMIT DROP")
    conn.executemany(
        "INSERT INTO epg1_m4(nome) VALUES(?)", [("abc",), ("a%c",), ("xyz",), ("100%",)]
    )
    literal_like = conn.execute(
        "SELECT nome FROM epg1_m4 WHERE nome LIKE 'a%' AND nome <> ?", ("zzz",)
    ).fetchall()
    assert {row["nome"] for row in literal_like} == {"abc", "a%c"}
    suffix_like = conn.execute(
        "SELECT nome FROM epg1_m4 WHERE nome LIKE '%\\%' ESCAPE '\\' AND length(nome) > ?",
        (0,),
    ).fetchall()
    assert {row["nome"] for row in suffix_like} == {"100%"}
    bound_like = conn.execute(
        "SELECT nome FROM epg1_m4 WHERE nome LIKE ?", ("a%",)
    ).fetchall()
    assert {row["nome"] for row in bound_like} == {"abc", "a%c"}
    conn.rollback()


def test_m4_question_marks_in_quotes_comments_and_dollar_bodies_are_not_placeholders(conn):
    row = conn.execute(
        "SELECT '?' AS q, 'it''s ?' AS r, ? AS p", ("v",)
    ).fetchone()
    assert tuple(row) == ("?", "it's ?", "v")

    row = conn.execute(
        "SELECT $$a?b%$$ AS d, $tag$?'?$tag$ AS t, ? AS p", ("v",)
    ).fetchone()
    assert tuple(row) == ("a?b%", "?'?", "v")

    row = conn.execute('SELECT ? AS "col?"', ("v",)).fetchone()
    assert row.keys() == ["col?"] and row["col?"] == "v"

    row = conn.execute("/* ? */ SELECT ? AS p -- trailing ?\n", ("v",)).fetchone()
    assert tuple(row) == ("v",)

    # A dollar-quoted plpgsql body keeps its '?' and '%' while the outer
    # statement still binds its own parameter.
    row = conn.execute(
        "SELECT ? AS p, (SELECT $body$ RAISE NOTICE '% ?'; $body$) AS body", ("v",)
    ).fetchone()
    assert tuple(row) == ("v", " RAISE NOTICE '% ?'; ")


def test_m4_engine_row_access_semantics(conn):
    row = conn.execute(
        'SELECT 1 AS Alpha, 2 AS alpha, ? AS "Beta"', ("x",)
    ).fetchone()
    assert isinstance(row, app_db.EngineRow)
    # Unquoted Alpha folds to alpha on PostgreSQL; the first duplicate wins.
    assert row.keys() == ["alpha", "alpha", "Beta"]
    assert row[0] == 1 and row[1] == 2 and row[2] == "x" and row[-1] == "x"
    assert row["alpha"] == 1 and row["ALPHA"] == 1
    assert row["Beta"] == "x" and row["beta"] == "x" and row["BETA"] == "x"
    assert len(row) == 3
    assert list(row) == [1, 2, "x"]
    assert tuple(row) == (1, 2, "x")
    assert "BETA" in row and "gamma" not in row
    with pytest.raises(IndexError):
        row["gamma"]
    with pytest.raises(IndexError):
        row[3]

    named = conn.execute("SELECT 1 AS id, ? AS nome", ("n",)).fetchone()
    assert dict(named) == {"id": 1, "nome": "n"}

    rows = list(conn.execute("SELECT generate_series(1, ?) AS n", (3,)))
    assert [r["N"] for r in rows] == [1, 2, 3]
    assert all(isinstance(r, app_db.EngineRow) for r in rows)
    assert conn.execute("SELECT 1 WHERE false").fetchone() is None


# ===========================================================================
# M5 -- SQL dialect fragments and upserts on PG15
# ===========================================================================

_M5_DATES = [
    (1, "2026-01-10 10:00:00"),
    (2, "2026-01-09 23:59:59"),
    (3, "2026-01-11 00:00:00"),
    (4, "2026-01-10"),
    (5, None),
    (6, "not-a-date"),
]
_M5_JSON = [
    (1, '{"a":"x"}'),
    (2, '{"b":"y"}'),
    (3, None),
    (4, '{"a":"l1\\nl2"}'),
    (5, '{"a":""}'),
]


@pytest.fixture()
def m5_pair(conn):
    """The same rows on real PG (temp table) and on an in-memory SQLite oracle."""
    oracle = sqlite3.connect(":memory:")
    for target in (conn, oracle):
        target.execute("CREATE TEMP TABLE m5_d(id integer, d text)")
        target.execute("CREATE TEMP TABLE m5_j(id integer, j text)")
        target.executemany("INSERT INTO m5_d(id, d) VALUES(?, ?)", _M5_DATES)
        target.executemany("INSERT INTO m5_j(id, j) VALUES(?, ?)", _M5_JSON)
    try:
        yield conn, oracle
    finally:
        oracle.close()
        conn.rollback()


def _both(pair, build_sql, params=()):
    pg, oracle = pair
    pg_rows = [tuple(row) for row in pg.execute(build_sql(pg), params).fetchall()]
    sqlite_rows = [tuple(row) for row in oracle.execute(build_sql(oracle), params).fetchall()]
    return pg_rows, sqlite_rows


def test_m5_current_utc_text_is_canonical_utc(conn):
    conn.execute("SET TIME ZONE 'America/Sao_Paulo'")
    assert sql_dialect.current_utc_text(conn) == "sgaa_utcnow_text()"
    value = sql_dialect.fetch_current_utc_text(conn)
    assert CANONICAL_UTC_TEXT_RE.fullmatch(value), value
    parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    assert abs((parsed - datetime.now(timezone.utc)).total_seconds()) < 120
    conn.rollback()


@pytest.mark.parametrize("operator", [">=", "<="])
def test_m5_date_compare_matches_sqlite_date(m5_pair, operator):
    pg_rows, sqlite_rows = _both(
        m5_pair,
        lambda c: "SELECT id FROM m5_d WHERE "
        + sql_dialect.date_compare(c, "d", operator)
        + " ORDER BY id",
        ("2026-01-10",),
    )
    assert pg_rows == sqlite_rows
    expected = [(1,), (3,), (4,)] if operator == ">=" else [(1,), (2,), (4,)]
    assert pg_rows == expected


def test_m5_datetime_order_matches_sqlite_datetime(m5_pair):
    # Canonical timestamp text (and NULL) only: the documented column contract.
    pg_rows, sqlite_rows = _both(
        m5_pair,
        lambda c: "SELECT id FROM m5_d WHERE id <> 6 ORDER BY "
        + sql_dialect.datetime_order(c, "d")
        + ", id",
    )
    assert pg_rows == sqlite_rows == [(5,), (2,), (4,), (1,), (3,)]


def test_m5_format_date_ptbr_matches_sqlite_strftime(m5_pair):
    pg_rows, sqlite_rows = _both(
        m5_pair,
        lambda c: "SELECT id, "
        + sql_dialect.format_date_ptbr(c, "d")
        + " FROM m5_d ORDER BY id",
    )
    assert pg_rows == sqlite_rows
    assert dict(pg_rows) == {
        1: "10/01/2026",
        2: "09/01/2026",
        3: "11/01/2026",
        4: "10/01/2026",
        5: None,
        6: None,
    }


def test_m5_json_text_matches_sqlite_json_extract(m5_pair):
    pg_rows, sqlite_rows = _both(
        m5_pair,
        lambda c: "SELECT id, " + sql_dialect.json_text(c, "j", "a") + " FROM m5_j ORDER BY id",
    )
    assert pg_rows == sqlite_rows
    assert dict(pg_rows) == {1: "x", 2: None, 3: None, 4: "l1\nl2", 5: ""}


def test_m5_newline_fragment_and_embedded_newline_round_trip(m5_pair):
    pg_rows, sqlite_rows = _both(
        m5_pair,
        lambda c: "SELECT 'a' || " + sql_dialect.newline(c) + " || 'b', ?",
        ("x\ny",),
    )
    assert pg_rows == sqlite_rows == [("a\nb", "x\ny")]


def test_m5_settings_and_message_upserts_use_excluded_values(conn, inspector):
    from app.settings import save_app_settings, save_horas_settings
    from utils.messages import _message_catalog, save_message_override

    with app_db.write_transaction(conn):
        save_horas_settings(
            conn, {"horas_padrao_academica": "200", "horas_padrao_extensao": "150"}
        )
        save_app_settings(
            conn, {"response_goal_days": "12", "response_metrics_reset_at": "2026-01-10"}
        )
        conn.execute(
            "UPDATE configuracoes_app SET atualizado_em = '2000-01-01 00:00:00' "
            "WHERE chave = 'horas_padrao_academica'"
        )
    with app_db.write_transaction(conn):
        save_horas_settings(
            conn, {"horas_padrao_academica": "250", "horas_padrao_extensao": "150"}
        )

    rows = inspector.execute(
        "SELECT chave, valor, atualizado_em FROM configuracoes_app "
        "WHERE chave IN ('horas_padrao_academica','horas_padrao_extensao',"
        "'response_goal_days','response_metrics_reset_at') ORDER BY chave"
    ).fetchall()
    by_key = {row[0]: (row[1], row[2]) for row in rows}
    assert len(rows) == 4
    assert by_key["horas_padrao_academica"][0] == "250"
    assert by_key["horas_padrao_academica"][1] != "2000-01-01 00:00:00"
    assert CANONICAL_UTC_TEXT_RE.fullmatch(by_key["horas_padrao_academica"][1])
    assert by_key["horas_padrao_extensao"][0] == "150"
    assert by_key["response_goal_days"][0] == "12"
    assert by_key["response_metrics_reset_at"][0] == "2026-01-10"

    key = sorted(_message_catalog())[0]
    with app_db.write_transaction(conn):
        save_message_override(conn, key, "linha 1\nlinha 2")
    with app_db.write_transaction(conn):
        save_message_override(conn, key, "linha 3\nlinha 4")
    stored = inspector.execute(
        "SELECT texto, atualizado_em FROM mensagens_editaveis WHERE chave = %s", (key,)
    ).fetchall()
    assert len(stored) == 1
    assert stored[0][0] == "linha 3\nlinha 4"
    assert CANONICAL_UTC_TEXT_RE.fullmatch(stored[0][1])


# ===========================================================================
# M6 -- pg_schema_status
# ===========================================================================


def test_m6_status_reports_current_on_provisioned_schema(conn):
    from app.db_maintenance import get_schema_status

    status = pg_schema.pg_schema_status(conn)
    assert status["schema_epoch"] == pg_schema.PG_SCHEMA_EPOCH
    assert status["schema_version"] == pg_schema.PG_SCHEMA_VERSION
    assert status["target_schema_version"] == pg_schema.PG_SCHEMA_VERSION
    assert status["contract_sha256"] == pg_schema.PG_CONTRACT_SHA256
    latest = status["latest_migration"]
    assert latest["version"] == pg_schema.PG_SCHEMA_VERSION
    assert latest["name"]
    assert CANONICAL_UTC_TEXT_RE.fullmatch(latest["applied_at"])
    assert _assigned_xid(conn) is None  # SELECT only
    assert get_schema_status(conn) == status


def test_m6_status_refuses_an_unprovisioned_database(empty_url):
    from app.db_maintenance import get_schema_status

    connection = _production_connection(empty_url)
    try:
        for owner in (pg_schema.pg_schema_status, get_schema_status):
            # Fail closed, never a healthy summary.  Which exception class an
            # absent baseline raises is not pinned by the current contract.
            with pytest.raises(
                (pg_schema.PostgresSchemaError, psycopg.errors.UndefinedTable)
            ) as excinfo:
                owner(connection)
            print(f"M6-B {owner.__name__}: {excinfo.type.__module__}.{excinfo.type.__name__}")
            connection.rollback()
        assert connection.execute("SELECT 1").fetchone()[0] == 1
    finally:
        connection.rollback()
        connection.close()


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE pg_schema_meta SET contract_sha256 = repeat('0', 64)",
        "UPDATE pg_schema_meta SET schema_version = schema_version - 1",
        "UPDATE pg_schema_meta SET schema_epoch = 'other'",
        "DELETE FROM pg_schema_meta",
    ],
)
def test_m6_status_reports_meta_mismatch(conn, mutation):
    conn.execute(mutation)
    with pytest.raises(pg_schema.PostgresSchemaError):
        pg_schema.pg_schema_status(conn)
    conn.rollback()
    assert pg_schema.pg_schema_status(conn)["schema_version"] == pg_schema.PG_SCHEMA_VERSION


def test_m6_status_is_lightweight_structural_drift_needs_the_validator(conn):
    """Documented boundary: no material census in ``pg_schema_status``."""
    conn.execute(
        "DROP TRIGGER trg_atividade_versao_prev_same_eixo_insert ON atividade_versao"
    )
    assert pg_schema.pg_schema_status(conn)["schema_version"] == pg_schema.PG_SCHEMA_VERSION
    with pytest.raises(pg_schema.PostgresSchemaError):
        pg_schema.validate_pg_schema(conn)
    conn.rollback()


# ===========================================================================
# M7 -- lazy default seed persistence across the caller's commit boundary
# ===========================================================================


def _m7_owners():
    import main  # noqa: F401  (create_app binds the backup-settings runtime app)
    from app.auth import DEFAULT_ACCESS_PASSWORDS
    from app.backup_settings import _backup_settings_defaults, ensure_backup_settings_schema
    from app.db_maintenance import ensure_usuario_access_schema

    return {
        "access": (
            ensure_usuario_access_schema,
            "SELECT nivel_acesso, senha_padrao FROM configuracoes_acesso",
            dict(DEFAULT_ACCESS_PASSWORDS),
        ),
        "app": (
            app_db.ensure_app_settings_schema,
            "SELECT chave, valor FROM configuracoes_app",
            app_db._app_settings_defaults(),
        ),
        "backup": (
            ensure_backup_settings_schema,
            "SELECT chave, valor FROM configuracoes_backup",
            _backup_settings_defaults(),
        ),
    }


class _Boom(Exception):
    pass


@pytest.fixture()
def restore_backup_config():
    import main

    keys = (
        "LOCAL_BACKUP_DIR",
        "CLOUD_BACKUP_DIR",
        "CLOUD_SYNC_INTERVAL_SECONDS",
        "EXTERNAL_BACKUP_URL",
        "EXTERNAL_BACKUP_TOKEN",
        "EXTERNAL_BACKUP_ENABLED",
    )
    missing = object()
    saved = {key: main.app.config.get(key, missing) for key in keys}
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is missing:
                main.app.config.pop(key, None)
            else:
                main.app.config[key] = value


@pytest.mark.parametrize("family", ["access", "app", "backup"])
def test_m7_lazy_defaults_persist_only_when_the_caller_commits(
    fresh_url, family, restore_backup_config
):
    ensure, read_sql, defaults = _m7_owners()[family]
    assert defaults
    observer = _raw_connect(fresh_url, autocommit=True)
    connection = _production_connection(fresh_url)
    try:
        # A. provisioning seeds no application default rows.
        assert observer.execute(read_sql).fetchall() == []

        # D1. block rolled back: seeded rows were visible in-transaction only.
        with pytest.raises(_Boom):
            with app_db.write_transaction(connection):
                ensure(connection)
                assert len(connection.execute(read_sql).fetchall()) == len(defaults)
                assert observer.execute(read_sql).fetchall() == []
                raise _Boom()
        assert observer.execute(read_sql).fetchall() == []

        # D2. no commit at all (a request that ends without commit): the
        # connection closes and the rows never become committed.
        ensure(connection)
        assert _assigned_xid(connection) is not None
        assert observer.execute(read_sql).fetchall() == []
        connection.close()
        assert observer.execute(read_sql).fetchall() == []

        # B/C. the production transaction owner commits: the defaults persist.
        connection = _production_connection(fresh_url)
        with app_db.write_transaction(connection):
            ensure(connection)
        assert dict(observer.execute(read_sql).fetchall()) == defaults

        # Idempotent and non-overwriting once persisted.
        first_key = sorted(defaults)[0]
        table = read_sql.split(" FROM ")[1]
        key_column = read_sql.split()[1].rstrip(",")
        value_column = read_sql.split()[2]
        observer.execute(
            f"UPDATE {table} SET {value_column} = 'custom' WHERE {key_column} = %s",
            (first_key,),
        )
        with app_db.write_transaction(connection):
            ensure(connection)
        persisted = dict(observer.execute(read_sql).fetchall())
        assert persisted == {**defaults, first_key: "custom"}
    finally:
        if not connection.closed:
            connection.rollback()
            connection.close()
        observer.close()


# ===========================================================================
# M9 -- real /admin/acesso/salvar uniqueness on PostgreSQL
# ===========================================================================

SAVE_ROUTE = "/admin/acesso/salvar"
SAVED_MESSAGE = "Acesso salvo com sucesso."
DUPLICATE_EMAIL_MESSAGE = "Já existe um usuário com este e-mail."
ADMIN_EMAIL = "epg1.admin@example.test"
TARGET_EMAIL = "epg1.alvo@example.test"
OTHER_EMAIL = "epg1.outro@example.test"


@pytest.fixture()
def pg_app(registry, monkeypatch):
    import main
    from app.security.passwords import hash_password
    from app.user_accounts import create_usuario_with_access_level, get_usuario_auth_version

    database, url = registry.create_provisioned("route")
    monkeypatch.setattr(app_db, "DATABASE_URL", url)
    monkeypatch.setitem(main.app.config, "TESTING", True)
    observer = _raw_connect(url, autocommit=True)
    try:
        connection = app_db._connect_postgres()
        try:
            password_hash = hash_password("epg1-senha")
            ids = {}
            for key, nome, email in (
                ("admin", "EPG1 Admin", ADMIN_EMAIL),
                ("target", "EPG1 Alvo", TARGET_EMAIL),
                ("other", "EPG1 Outro", OTHER_EMAIL),
            ):
                cursor = create_usuario_with_access_level(
                    connection, nome, email, password_hash, "admin", "admin_total",
                    credential_state="personal",
                )
                ids[key] = int(cursor.usuario_id)
            auth_version = get_usuario_auth_version(connection, ids["admin"])
            connection.commit()
        finally:
            connection.close()
        client = main.app.test_client()
        with client.session_transaction() as session:
            session.update(
                user_id=ids["admin"],
                user_type="admin",
                user_name="EPG1 Admin",
                auth_version=auth_version,
            )
        yield {"client": client, "ids": ids, "observer": observer}
    finally:
        with main.app.app_context():
            app_db.close_db_connection(None)
        observer.close()
        registry.drop(database)


def _form(nome, email, usuario_id=None):
    data = {"nome": nome, "email": email, "nivel_acesso": "admin_total", "senha": ""}
    if usuario_id is not None:
        data["usuario_id"] = str(usuario_id)
    return data


def _post(env, data):
    response = env["client"].post(SAVE_ROUTE, data=data)
    with env["client"].session_transaction() as session:
        flashes = [message for _category, message in session.pop("_flashes", [])]
    return response, flashes


def _users_by_email(env, email):
    return env["observer"].execute(
        "SELECT id, nome FROM usuarios WHERE lower(email) = lower(%s) ORDER BY id",
        (email,),
    ).fetchall()


def _user(env, usuario_id):
    return tuple(
        env["observer"].execute(
            "SELECT nome, email FROM usuarios WHERE id = %s", (usuario_id,)
        ).fetchone()
    )


def _user_count(env):
    return env["observer"].execute("SELECT count(*) FROM usuarios").fetchone()[0]


def test_m9_control_pre_u5f_shape_raises_42p18_on_real_pg(conn):
    """The lane can see the defect class: the pre-U5-F text fails on PG15."""
    pre_u5f = (
        "SELECT id FROM usuarios WHERE LOWER(email) = LOWER(?) AND (? IS NULL OR id <> ?)"
    )
    with pytest.raises(psycopg.errors.IndeterminateDatatype) as excinfo:
        conn.execute(pre_u5f, ("a@epg1.test", None, None))
    assert excinfo.value.sqlstate == "42P18"
    conn.rollback()
    # The same text binds when the id is an int (why EDIT survived pre-U5-F).
    assert conn.execute(pre_u5f, ("a@epg1.test", 7, 7)).fetchone() is None
    conn.rollback()


def test_m9_create_runs_uniqueness_on_real_pg_and_creates(pg_app):
    email = "epg1.novo@example.test"
    before = _user_count(pg_app)
    response, flashes = _post(pg_app, _form("EPG1 Novo", email))
    assert response.status_code == 302, response.status_code
    assert SAVED_MESSAGE in flashes, flashes
    assert len(_users_by_email(pg_app, email)) == 1
    assert _user_count(pg_app) == before + 1


def test_m9_create_rejects_duplicate_email(pg_app):
    before = _user_count(pg_app)
    response, flashes = _post(pg_app, _form("EPG1 Duplicado", OTHER_EMAIL.upper()))
    assert response.status_code == 302
    assert DUPLICATE_EMAIL_MESSAGE in flashes, flashes
    assert SAVED_MESSAGE not in flashes
    assert _user_count(pg_app) == before
    assert len(_users_by_email(pg_app, OTHER_EMAIL)) == 1


def test_m9_edit_retaining_own_email_succeeds(pg_app):
    target = pg_app["ids"]["target"]
    response, flashes = _post(
        pg_app, _form("EPG1 Alvo Editado", TARGET_EMAIL, usuario_id=target)
    )
    assert response.status_code == 302
    assert SAVED_MESSAGE in flashes, flashes
    assert _user(pg_app, target) == ("EPG1 Alvo Editado", TARGET_EMAIL)


def test_m9_edit_to_another_users_email_is_rejected(pg_app):
    target = pg_app["ids"]["target"]
    response, flashes = _post(
        pg_app, _form("EPG1 Alvo Roubo", OTHER_EMAIL, usuario_id=target)
    )
    assert response.status_code == 302
    assert DUPLICATE_EMAIL_MESSAGE in flashes, flashes
    assert _user(pg_app, target) == ("EPG1 Alvo", TARGET_EMAIL)
    assert len(_users_by_email(pg_app, OTHER_EMAIL)) == 1


# ---------------------------------------------------------------------------
# M7 request-level corroboration (same real-PG Flask fixture)
# ---------------------------------------------------------------------------


def test_m7_request_commit_persists_lazy_access_defaults(pg_app):
    from app.auth import DEFAULT_ACCESS_PASSWORDS

    observer = pg_app["observer"]
    observer.execute("DELETE FROM configuracoes_acesso")
    response, flashes = _post(pg_app, _form("EPG1 M7", "epg1.m7@example.test"))
    assert response.status_code == 302 and SAVED_MESSAGE in flashes, flashes
    persisted = dict(
        observer.execute("SELECT nivel_acesso, senha_padrao FROM configuracoes_acesso").fetchall()
    )
    assert persisted == dict(DEFAULT_ACCESS_PASSWORDS)


def test_m7_request_without_commit_does_not_persist_lazy_access_defaults(pg_app):
    observer = pg_app["observer"]
    observer.execute("DELETE FROM configuracoes_acesso")
    response = pg_app["client"].get("/admin/acesso")
    assert response.status_code == 200
    assert observer.execute("SELECT count(*) FROM configuracoes_acesso").fetchone()[0] == 0
