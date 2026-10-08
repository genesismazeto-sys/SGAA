# coding: utf-8
"""PostgreSQL-readiness Unit 4: runtime transaction and locking semantics.

The unit gives the ordinary runtime paths that depended on SQLite
``BEGIN IMMEDIATE`` or on SQLite-specific transaction-state assumptions an
engine-neutral contract:

A. ``write_transaction`` keeps the historical SQLite ``BEGIN IMMEDIATE``
   write-intent transaction (clean connection required) and gives PostgreSQL a
   transaction the block explicitly owns: a harmless read-only
   INTRANS-after-SELECT is adopted, an INTRANS transaction that already owns an
   assigned XID is refused, an INERROR transaction is rolled back before reuse,
   a swallowed database error is rolled back and reported, and commit and
   rollback are the block's own;
B. password-token consumption serializes per account and per token on
   PostgreSQL (``usuarios`` and ``senha_tokens`` row locks) while SQLite keeps
   its global write-lock semantics; issuance takes the account lock before any
   token mutation, so consume × issue cannot invert the account/token order;
   the token can still be consumed only once;
C. activity-version delete serializes per activity base on PostgreSQL
   (``atividade_base`` row lock) while SQLite keeps ``BEGIN IMMEDIATE``, so two
   concurrent deletes cannot both pass the survivor check and empty a base, and
   interleaved renumbering cannot happen;
D. every production ``BEGIN IMMEDIATE`` outside the ``prod1_*`` migration
   chain is gone, and the runtime paths never emit one on PostgreSQL.

All PostgreSQL behaviour is modelled by ``tests.pg_shaped_support``: a real
SQLite row engine behind psycopg 3 transaction-state semantics, the PostgreSQL
row-lock conflict matrix and XID assignment.  No network, no Supabase, no
PostgreSQL server and no schema bootstrap are involved.
"""
from __future__ import annotations

import datetime as dt
import inspect
import re
import sqlite3
import uuid
from pathlib import Path

import pytest
from flask import g

import main
from app import db as app_db
from app.activity_catalog import (
    ActivityVersionDeleteBlocked,
    delete_activity_version,
)
from app.password_tokens import (
    PURPOSE_FIRST_ACCESS,
    consume_password_token_and_set_password,
    issue_password_token,
)
from app.prod1_schema import bootstrap_prod1_schema
from app.security.passwords import check_password, hash_password
from app.user_accounts import (
    CREDENTIAL_STATE_PENDING,
    CREDENTIAL_STATE_PERSONAL,
    create_usuario_with_access_level,
    set_usuario_email,
    set_usuario_password_hash,
)
from tests.pg_shaped_support import (
    MODE_EXCLUSIVE,
    MODE_KEY_SHARE,
    MODE_NO_KEY_UPDATE,
    PostgresLockBlocked,
    PostgresShapedConnection,
)
from tests.session_support import existing_admin_user_id, stamp_auth_version
from tests.versioned_test_support import isolated_versioned_app_env

REPO_ROOT = Path(__file__).resolve().parents[1]
NOW = dt.datetime(2026, 9, 20, 12, 0, tzinfo=dt.timezone.utc)

#: Every production ``BEGIN IMMEDIATE`` that remains belongs to the SQLite
#: migration/bootstrap chain (Phase 5 boundary, Unit 5).  No ordinary runtime
#: module may keep one.
DEFERRED_MIGRATION_BEGIN_IMMEDIATE = frozenset(
    {
        "app/prod1_access_delivery_v10.py",
        "app/prod1_access_status_v9.py",
        "app/prod1_arquivos_v5.py",
        "app/prod1_comprovantes_v4.py",
        "app/prod1_credential_pending_v11.py",
        "app/prod1_extension_hours_v12.py",
        "app/prod1_images_v13.py",
        "app/prod1_storage_v14.py",
        "app/prod1_notifications_v7.py",
        "app/prod1_password_foundation_v8.py",
        "app/prod1_schema.py",
        "app/prod1_student_matrix_v6.py",
    }
)
#: The offline one-shot legacy image importer (STORAGE S1) opens an explicit
#: SQLite file outside any request and moves one record per BEGIN IMMEDIATE
#: transaction; it is never imported by the runtime.
OFFLINE_TOOL_BEGIN_IMMEDIATE = frozenset({"app/image_import.py"})


def _require(name):
    value = getattr(app_db, name, None)
    assert value is not None, f"app.db.{name} is not implemented yet"
    return value


def _bootstrap_connection(tmp_path, name, *, timeout=0):
    conn = sqlite3.connect(tmp_path / name, timeout=timeout)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    bootstrap_prod1_schema(conn)
    return conn


def _seed_pending_token(conn, *, raw="H" * 43, email=None):
    email = email or f"u4-{uuid.uuid4().hex[:8]}@example.test"
    result = create_usuario_with_access_level(
        conn,
        "U4 Token",
        email,
        hash_password("u4-original"),
        "admin",
        "admin_total",
        credential_state=CREDENTIAL_STATE_PENDING,
    )
    usuario_id = result.usuario_id
    _raw, token_id = issue_password_token(
        conn,
        usuario_id,
        PURPOSE_FIRST_ACCESS,
        now=NOW,
        token_factory=lambda _size: raw,
    )
    conn.commit()
    return usuario_id, token_id


def _seed_base_with_versions(conn, *numbers):
    base_id = conn.execute(
        "INSERT INTO atividade_base(nome_conceito,status) VALUES(?,'ativo') RETURNING id",
        (f"U4 Base {uuid.uuid4().hex[:10]}",),
    ).fetchone()[0]
    version_ids = [
        conn.execute(
            "INSERT INTO atividade_versao"
            "(atividade_base_id,eixo,grupo,numero_versao,status) "
            "VALUES(?,'AAC','1 - U4',?,'ativa') RETURNING id",
            (base_id, number),
        ).fetchone()[0]
        for number in numbers
    ]
    conn.commit()
    return base_id, version_ids


def _version_row(conn, version_id):
    return conn.execute(
        "SELECT * FROM atividade_versao WHERE id=?", (version_id,)
    ).fetchone()


def _joined_statements(connection):
    return " ".join(sql for sql, _ in connection.statements).upper()


def _first_index(connection, predicate):
    for index, (sql, _params) in enumerate(connection.statements):
        if predicate(sql):
            return index
    return None


_DESTRUCTIVE_RE = re.compile(
    r"(?:UPDATE|DELETE\s+FROM|INSERT\s+INTO)\s+ATIVIDADE_(?:VERSAO|TRANSICAO)",
    re.IGNORECASE,
)
_EXECUTED_BEGIN_IMMEDIATE_RE = re.compile(
    r"""(?:execute|executescript)\s*\(\s*["']BEGIN IMMEDIATE""", re.IGNORECASE
)


def _is_destructive(sql):
    return bool(_DESTRUCTIVE_RE.search(sql))


# ---------------------------------------------------------------------------
# A. engine-neutral write transaction
# ---------------------------------------------------------------------------


def test_sqlite_write_transaction_emits_begin_immediate_and_commits(tmp_path):
    write_transaction = _require("write_transaction")
    conn = sqlite3.connect(tmp_path / "u4-tx-commit.db")
    traced = []
    conn.set_trace_callback(traced.append)
    try:
        with write_transaction(conn):
            conn.execute("CREATE TABLE t(x)")
            conn.execute("INSERT INTO t VALUES(1)")
        assert any("BEGIN IMMEDIATE" in statement for statement in traced)
        assert conn.in_transaction is False
        assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1
    finally:
        conn.close()


def test_sqlite_write_transaction_rolls_back_on_error(tmp_path):
    write_transaction = _require("write_transaction")
    conn = sqlite3.connect(tmp_path / "u4-tx-rollback.db")
    try:
        conn.execute("CREATE TABLE t(x)")
        conn.commit()
        with pytest.raises(RuntimeError):
            with write_transaction(conn):
                conn.execute("INSERT INTO t VALUES(1)")
                raise RuntimeError("simulated failure")
        assert conn.in_transaction is False
        assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 0
    finally:
        conn.close()


def test_sqlite_write_transaction_refuses_an_open_transaction(tmp_path):
    write_transaction = _require("write_transaction")
    state_error = _require("DatabaseTransactionStateError")
    conn = sqlite3.connect(tmp_path / "u4-tx-dirty.db")
    try:
        conn.execute("CREATE TABLE t(x)")
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(state_error):
            with write_transaction(conn):
                pass
        assert conn.in_transaction is True
        conn.rollback()
    finally:
        conn.close()


def test_postgres_write_transaction_adopts_intrans_without_begin_immediate():
    write_transaction = _require("write_transaction")
    real = sqlite3.connect(":memory:")
    real.execute("CREATE TABLE t(x)")
    pg = PostgresShapedConnection(real)
    try:
        pg.execute("SELECT 1 FROM t")  # harmless prior SELECT: INTRANS
        assert pg.info.transaction_status.name == "INTRANS"
        with write_transaction(pg):
            pg.execute("INSERT INTO t VALUES(1)")
        assert pg.commits == 1
        assert pg.info.transaction_status.name == "IDLE"
        assert "BEGIN IMMEDIATE" not in _joined_statements(pg)
        assert pg.failed_statements == []
        assert real.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1
    finally:
        real.close()


def test_postgres_write_transaction_refuses_intrans_with_assigned_xid():
    """An INTRANS transaction that already owns write/locking work is refused."""
    write_transaction = _require("write_transaction")
    state_error = _require("DatabaseTransactionStateError")
    real = sqlite3.connect(":memory:")
    real.execute("CREATE TABLE t(x)")
    pg = PostgresShapedConnection(real)
    try:
        pg.execute("INSERT INTO t VALUES(1)")  # first write assigns the XID
        assert pg.info.transaction_status.name == "INTRANS"
        assert pg.xid_assigned is True

        with pytest.raises(state_error):
            with write_transaction(pg):
                pg.execute("INSERT INTO t VALUES(2)")

        assert pg.commits == 0
        assert pg.rollbacks == 0
        assert real.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1
        # The caller-owned transaction is left exactly as it was found.
        assert pg.info.transaction_status.name == "INTRANS"
        pg.rollback()
    finally:
        real.close()


def test_postgres_write_transaction_rolls_back_inerror_before_reuse():
    write_transaction = _require("write_transaction")
    real = sqlite3.connect(":memory:")
    real.execute("CREATE TABLE t(x)")
    pg = PostgresShapedConnection(real)
    try:
        with pytest.raises(sqlite3.OperationalError):
            pg.execute("SELECT * FROM missing_table")
        assert pg.info.transaction_status.name == "INERROR"

        with write_transaction(pg):
            pg.execute("INSERT INTO t VALUES(1)")

        assert pg.rollbacks == 1
        assert pg.info.transaction_status.name == "IDLE"
        assert real.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1
    finally:
        real.close()


def test_postgres_swallowed_error_rolls_back_and_raises_state_error():
    """A block that swallowed a database error must not look successful."""
    write_transaction = _require("write_transaction")
    state_error = _require("DatabaseTransactionStateError")
    real = sqlite3.connect(":memory:")
    real.execute("CREATE TABLE t(x)")
    pg = PostgresShapedConnection(real)
    try:
        with pytest.raises(state_error):
            with write_transaction(pg):
                with pytest.raises(sqlite3.OperationalError):
                    pg.execute("SELECT * FROM missing_table")

        assert pg.commits == 0
        assert pg.rollbacks == 1
        assert pg.info.transaction_status.name == "IDLE"

        # The connection is clean and reusable after the reported rollback.
        with write_transaction(pg):
            pg.execute("INSERT INTO t VALUES(1)")
        assert real.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1
    finally:
        real.close()


def test_postgres_explicit_exception_keeps_its_identity():
    """An ordinary caller exception is never replaced by a state error."""
    write_transaction = _require("write_transaction")
    real = sqlite3.connect(":memory:")
    real.execute("CREATE TABLE t(x)")
    pg = PostgresShapedConnection(real)
    try:
        with pytest.raises(RuntimeError, match="caller failure"):
            with write_transaction(pg):
                pg.execute("INSERT INTO t VALUES(1)")
                raise RuntimeError("caller failure")
        assert pg.commits == 0
        assert pg.rollbacks == 1
        assert pg.info.transaction_status.name == "IDLE"
    finally:
        real.close()


def test_postgres_write_transaction_refuses_intrans_owning_only_a_row_lock():
    """F3: an INTRANS transaction that already owns a row lock is refused.

    No DML has run, so only the lock (hence the assigned XID) marks it as
    caller-owned; the manager must not adopt and commit it.
    """
    write_transaction = _require("write_transaction")
    state_error = _require("DatabaseTransactionStateError")
    real, pg = _memory_connection()
    try:
        pg.execute("SELECT x FROM t WHERE x=? FOR UPDATE", (1,))
        assert pg.info.transaction_status.name == "INTRANS"
        assert pg.xid_assigned is True

        with pytest.raises(state_error):
            with write_transaction(pg):
                pg.execute("INSERT INTO t VALUES(1)")

        assert pg.commits == 0
        assert pg.rollbacks == 0
        assert pg.info.transaction_status.name == "INTRANS"
        pg.rollback()
        assert pg.info.transaction_status.name == "IDLE"
    finally:
        real.close()


def test_postgres_select_only_intrans_stays_allowed_after_managed_success():
    """F3: after a managed block, a fresh SELECT-only INTRANS is still adopted.

    The nested-ownership marker must be per active block, not a lifetime flag.
    """
    write_transaction = _require("write_transaction")
    real, pg = _memory_connection()
    try:
        with write_transaction(pg):
            pg.execute("INSERT INTO t VALUES(1)")

        pg.execute("SELECT x FROM t")  # external read-only INTRANS

        with write_transaction(pg):
            pg.execute("INSERT INTO t VALUES(2)")

        assert pg.commits == 2
        assert real.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 2
    finally:
        real.close()


# ---------------------------------------------------------------------------
# A2. one write_transaction owner per connection (explicit manager marker)
# ---------------------------------------------------------------------------


class _CommitFailsOnce(PostgresShapedConnection):
    """The first commit fails at transport level; the connection stays open."""

    def __init__(self, real):
        super().__init__(real)
        self.commit_failures = 0

    def commit(self):
        if self.commit_failures == 0:
            self.commit_failures += 1
            raise RuntimeError("commit transport failure")
        return super().commit()


class _RollbackFails(PostgresShapedConnection):
    """Rollback fails at transport level; the connection stays open."""

    def __init__(self, real):
        super().__init__(real)
        self.rollback_failures = 0

    def rollback(self):
        self.rollback_failures += 1
        raise RuntimeError("rollback transport failure")


def _memory_connection(table_sql="CREATE TABLE t(x)"):
    real = sqlite3.connect(":memory:")
    real.execute(table_sql)
    return real, PostgresShapedConnection(real)


def test_n1_nested_write_transaction_before_any_sql_is_refused(tmp_path):
    """N1: the outer owner exists before any SQL/XID; the inner block must not run."""
    write_transaction = _require("write_transaction")
    state_error = _require("DatabaseTransactionStateError")
    real, pg = _memory_connection()
    inner_ran = []
    try:
        with pytest.raises(state_error):
            with write_transaction(pg):  # outer, no SQL yet
                with write_transaction(pg):  # inner must refuse at entry
                    inner_ran.append(True)
                    pg.execute("INSERT INTO t VALUES(1)")
                raise RuntimeError("outer failure after inner block")

        assert inner_ran == []
        assert pg.commits == 0
        assert pg.rollbacks == 1
        assert real.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 0
        assert pg.info.transaction_status.name == "IDLE"
    finally:
        real.close()


def test_n1b_nested_refusal_leaves_outer_ownership_intact(tmp_path):
    """N1 corollary: the refused inner entry neither commits nor clears ownership."""
    write_transaction = _require("write_transaction")
    state_error = _require("DatabaseTransactionStateError")
    real, pg = _memory_connection()
    inner_ran = []
    try:
        with write_transaction(pg):
            with pytest.raises(state_error):
                with write_transaction(pg):
                    inner_ran.append(True)
            # The outer still owns the transaction and can write and commit.
            pg.execute("INSERT INTO t VALUES(1)")

        assert inner_ran == []
        assert pg.commits == 1
        assert pg.rollbacks == 0
        assert real.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1
    finally:
        real.close()


def test_n2_nested_write_transaction_after_select_is_refused(tmp_path):
    """N2: INTRANS after SELECT does not make the inner entry legal."""
    write_transaction = _require("write_transaction")
    state_error = _require("DatabaseTransactionStateError")
    real, pg = _memory_connection()
    inner_ran = []
    try:
        with pytest.raises(state_error):
            with write_transaction(pg):
                pg.execute("SELECT 1 FROM t")  # INTRANS, no assigned XID
                with write_transaction(pg):
                    inner_ran.append(True)
                    pg.execute("INSERT INTO t VALUES(1)")

        assert inner_ran == []
        assert pg.commits == 0
        assert pg.rollbacks == 1
        assert real.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 0
    finally:
        real.close()


def test_n3_nested_write_transaction_after_dml_is_refused(tmp_path):
    """N3: the existing XID refusal must not be weakened by the marker."""
    write_transaction = _require("write_transaction")
    state_error = _require("DatabaseTransactionStateError")
    real, pg = _memory_connection()
    inner_ran = []
    try:
        with write_transaction(pg):
            pg.execute("INSERT INTO t VALUES(1)")
            with pytest.raises(state_error):
                with write_transaction(pg):
                    inner_ran.append(True)
            pg.execute("INSERT INTO t VALUES(2)")

        assert inner_ran == []
        assert pg.commits == 1
        assert pg.rollbacks == 0
        assert real.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 2
    finally:
        real.close()


def test_n4_ownership_marker_cleared_after_success(tmp_path):
    """N4: a later independent write_transaction works after a successful one."""
    write_transaction = _require("write_transaction")
    real, pg = _memory_connection()
    try:
        with write_transaction(pg):
            pg.execute("INSERT INTO t VALUES(1)")
        pg.execute("SELECT 1 FROM t")  # harmless INTRANS between blocks
        with write_transaction(pg):
            pg.execute("INSERT INTO t VALUES(2)")

        assert pg.commits == 2
        assert real.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 2
    finally:
        real.close()


def test_n5_ownership_marker_cleared_after_rollback(tmp_path):
    """N5: a later write_transaction works after an outer exception/rollback."""
    write_transaction = _require("write_transaction")
    real, pg = _memory_connection()
    try:
        with pytest.raises(RuntimeError, match="outer failure"):
            with write_transaction(pg):
                pg.execute("INSERT INTO t VALUES(1)")
                raise RuntimeError("outer failure")
        with write_transaction(pg):
            pg.execute("INSERT INTO t VALUES(2)")

        assert pg.commits == 1
        assert pg.rollbacks == 1
        assert real.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1
    finally:
        real.close()


def test_n6_two_connections_own_write_transactions_independently(tmp_path):
    """N6: markers are per connection, never a process-global flag."""
    write_transaction = _require("write_transaction")
    state_error = _require("DatabaseTransactionStateError")
    first_real, first = _memory_connection()
    second_real, second = _memory_connection()
    inner_ran = []
    try:
        with write_transaction(first):
            with write_transaction(second):
                second.execute("INSERT INTO t VALUES(1)")
            first.execute("INSERT INTO t VALUES(1)")
            # Second is free again while first still owns its block.
            with write_transaction(second):
                second.execute("INSERT INTO t VALUES(2)")
            with pytest.raises(state_error):
                with write_transaction(first):
                    inner_ran.append(True)

        assert inner_ran == []
        assert first.commits == 1
        assert second.commits == 2
        assert first_real.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1
        assert second_real.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 2
    finally:
        first_real.close()
        second_real.close()


def test_n7_ownership_marker_cleared_when_commit_fails(tmp_path):
    """A transport-level commit failure must not leave a stale marker."""
    write_transaction = _require("write_transaction")
    real = sqlite3.connect(":memory:")
    real.execute("CREATE TABLE t(x)")
    pg = _CommitFailsOnce(real)
    try:
        with pytest.raises(RuntimeError, match="commit transport failure"):
            with write_transaction(pg):
                pass
        with write_transaction(pg):
            pg.execute("INSERT INTO t VALUES(1)")

        assert pg.commits == 1
        assert real.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1
    finally:
        real.close()


def test_n8_ownership_marker_cleared_when_rollback_fails(tmp_path):
    """Even a failing rollback must clear the manager marker."""
    write_transaction = _require("write_transaction")
    real = sqlite3.connect(":memory:")
    real.execute("CREATE TABLE t(x)")
    pg = _RollbackFails(real)
    try:
        with pytest.raises(RuntimeError, match="rollback transport failure"):
            with write_transaction(pg):
                raise ValueError("body failure")
        with write_transaction(pg):
            pg.execute("INSERT INTO t VALUES(1)")

        assert pg.rollback_failures == 1
        assert pg.commits == 1
        assert real.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1
    finally:
        real.close()


def test_n9_sqlite_nested_write_transaction_is_refused_before_sql(tmp_path):
    """SQLite keeps its historical nested refusal (BEGIN IMMEDIATE state)."""
    write_transaction = _require("write_transaction")
    state_error = _require("DatabaseTransactionStateError")
    conn = sqlite3.connect(tmp_path / "u4-nested-sqlite.db")
    conn.execute("CREATE TABLE t(x)")
    inner_ran = []
    try:
        with pytest.raises(state_error):
            with write_transaction(conn):
                with write_transaction(conn):
                    inner_ran.append(True)
        assert inner_ran == []
        assert conn.in_transaction is False
    finally:
        conn.close()


def test_n10_nested_write_transaction_after_outer_row_lock_is_refused(tmp_path):
    """The matrix cell where the outer block owns only a row lock (assigned XID)."""
    write_transaction = _require("write_transaction")
    state_error = _require("DatabaseTransactionStateError")
    lock_password_account = _require("lock_password_account")
    real = _bootstrap_connection(tmp_path, "u4-nested-outer-row-lock.db")
    inner_ran = []
    try:
        usuario_id, _token_id = _seed_pending_token(real)
        pg = PostgresShapedConnection(real)
        with write_transaction(pg):
            assert lock_password_account(pg, usuario_id) is True
            with pytest.raises(state_error):
                with write_transaction(pg):
                    inner_ran.append(True)

        assert inner_ran == []
        assert pg.commits == 1
        assert pg.rollbacks == 0
    finally:
        real.close()


# ---------------------------------------------------------------------------
# B. password-token path
# ---------------------------------------------------------------------------


def test_sqlite_token_consumption_keeps_begin_immediate_baseline(tmp_path):
    conn = _bootstrap_connection(tmp_path, "u4-sqlite-token.db")
    traced = []
    conn.set_trace_callback(traced.append)
    try:
        usuario_id, token_id = _seed_pending_token(conn)
        auth_version = consume_password_token_and_set_password(
            conn, "H" * 43, PURPOSE_FIRST_ACCESS, hash_password("u4-new"), now=NOW
        )
        assert auth_version == 2
        assert any("BEGIN IMMEDIATE" in statement for statement in traced)
        assert conn.in_transaction is False
        stored = conn.execute(
            "SELECT senha FROM usuarios WHERE id=?", (usuario_id,)
        ).fetchone()["senha"]
        assert check_password(stored, "u4-new")
        consumed = conn.execute(
            "SELECT consumed_at FROM senha_tokens WHERE id=?", (token_id,)
        ).fetchone()["consumed_at"]
        assert consumed is not None
    finally:
        conn.close()


def test_postgres_token_consumption_after_prior_select_is_accepted(tmp_path):
    """A harmless SELECT must not look like an open SQLite write transaction."""
    real = _bootstrap_connection(tmp_path, "u4-pg-prior-select.db")
    try:
        usuario_id, token_id = _seed_pending_token(real)
        pg = PostgresShapedConnection(real)
        pg.execute("SELECT email FROM usuarios WHERE id=?", (usuario_id,))
        assert app_db.connection_in_transaction(pg) is True

        auth_version = consume_password_token_and_set_password(
            pg, "H" * 43, PURPOSE_FIRST_ACCESS, hash_password("u4-new"), now=NOW
        )

        assert auth_version == 2
        stored = real.execute(
            "SELECT senha FROM usuarios WHERE id=?", (usuario_id,)
        ).fetchone()["senha"]
        assert check_password(stored, "u4-new")
        assert real.execute(
            "SELECT consumed_at FROM senha_tokens WHERE id=?", (token_id,)
        ).fetchone()["consumed_at"] is not None
    finally:
        real.close()


def test_postgres_token_consumption_never_emits_begin_immediate(tmp_path):
    real = _bootstrap_connection(tmp_path, "u4-pg-no-begin.db")
    try:
        _usuario_id, _token_id = _seed_pending_token(real)
        pg = PostgresShapedConnection(real)

        assert consume_password_token_and_set_password(
            pg, "H" * 43, PURPOSE_FIRST_ACCESS, hash_password("u4-new"), now=NOW
        ) == 2

        assert "BEGIN IMMEDIATE" not in _joined_statements(pg)
        assert pg.failed_statements == []
        assert pg.info.transaction_status.name == "IDLE"
    finally:
        real.close()


def test_postgres_token_consumption_locks_account_then_token_before_writes(tmp_path):
    real = _bootstrap_connection(tmp_path, "u4-pg-lock-order.db")
    try:
        usuario_id, token_id = _seed_pending_token(real)
        pg = PostgresShapedConnection(real)

        assert consume_password_token_and_set_password(
            pg, "H" * 43, PURPOSE_FIRST_ACCESS, hash_password("u4-new"), now=NOW
        ) == 2

        assert ("usuarios", usuario_id) in pg.locks
        assert ("senha_tokens", token_id) in pg.locks
        assert pg.locks.index(("usuarios", usuario_id)) < pg.locks.index(
            ("senha_tokens", token_id)
        )
        first_lock = _first_index(pg, lambda sql: "FOR UPDATE" in sql.upper())
        first_password_write = _first_index(
            pg, lambda sql: bool(re.search(r"UPDATE\s+usuarios\s+SET", sql, re.I))
        )
        assert first_lock is not None
        assert first_password_write is not None
        assert first_lock < first_password_write
    finally:
        real.close()


def test_postgres_token_cannot_be_consumed_twice(tmp_path):
    real = _bootstrap_connection(tmp_path, "u4-pg-single-use.db")
    try:
        usuario_id, token_id = _seed_pending_token(real)
        pg = PostgresShapedConnection(real)

        assert consume_password_token_and_set_password(
            pg, "H" * 43, PURPOSE_FIRST_ACCESS, hash_password("u4-first"), now=NOW
        ) == 2
        assert consume_password_token_and_set_password(
            pg, "H" * 43, PURPOSE_FIRST_ACCESS, hash_password("u4-second"), now=NOW
        ) is None

        stored = real.execute(
            "SELECT senha FROM usuarios WHERE id=?", (usuario_id,)
        ).fetchone()["senha"]
        assert check_password(stored, "u4-first")
        assert not check_password(stored, "u4-second")
        consumed = real.execute(
            "SELECT COUNT(*) FROM senha_tokens WHERE id=? AND consumed_at IS NOT NULL",
            (token_id,),
        ).fetchone()[0]
        assert consumed == 1
        credential = real.execute(
            "SELECT auth_version FROM usuario_credenciais WHERE usuario_id=?",
            (usuario_id,),
        ).fetchone()[0]
        assert credential == 2
    finally:
        real.close()


def test_postgres_failed_transaction_is_rolled_back_before_token_reuse(tmp_path):
    real = _bootstrap_connection(tmp_path, "u4-pg-inerror.db")
    try:
        _usuario_id, _token_id = _seed_pending_token(real)
        pg = PostgresShapedConnection(real)
        with pytest.raises(sqlite3.OperationalError):
            pg.execute("SELECT * FROM missing_table")
        assert pg.info.transaction_status.name == "INERROR"

        assert consume_password_token_and_set_password(
            pg, "H" * 43, PURPOSE_FIRST_ACCESS, hash_password("u4-new"), now=NOW
        ) == 2

        assert pg.rollbacks == 1
        assert pg.info.transaction_status.name == "IDLE"
    finally:
        real.close()


def test_postgres_token_locks_are_released_after_commit_and_rollback(tmp_path, monkeypatch):
    import app.user_accounts as user_accounts
    from app.password_tokens import PURPOSE_PASSWORD_RESET

    registry = {}
    real = _bootstrap_connection(tmp_path, "u4-pg-lock-release.db")
    try:
        usuario_id, _token_id = _seed_pending_token(real)
        pg = PostgresShapedConnection(real, lock_registry=registry, owner="u4")
        assert consume_password_token_and_set_password(
            pg, "H" * 43, PURPOSE_FIRST_ACCESS, hash_password("u4-new"), now=NOW
        ) == 2
        assert registry == {}

        # A failure after both locks were taken must roll the transaction back
        # and release every lock before the connection is reused.
        reset_raw = "R" * 43
        _raw, _reset_id = issue_password_token(
            real,
            usuario_id,
            PURPOSE_PASSWORD_RESET,
            now=NOW,
            token_factory=lambda _size: reset_raw,
        )
        real.commit()
        calls = {"count": 0}
        real_set_password = user_accounts.set_usuario_password_hash

        def flaky_set_password(conn, target_usuario_id, senha_hash, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("simulated failure after lock acquisition")
            return real_set_password(conn, target_usuario_id, senha_hash, **kwargs)

        monkeypatch.setattr(user_accounts, "set_usuario_password_hash", flaky_set_password)
        with pytest.raises(RuntimeError):
            consume_password_token_and_set_password(
                pg, reset_raw, PURPOSE_PASSWORD_RESET, hash_password("u4-retry"), now=NOW
            )
        assert pg.rollbacks >= 1
        assert registry == {}
        assert pg.info.transaction_status.name == "IDLE"

        assert consume_password_token_and_set_password(
            pg, reset_raw, PURPOSE_PASSWORD_RESET, hash_password("u4-retry"), now=NOW
        ) is not None
        assert registry == {}
        stored = real.execute(
            "SELECT senha FROM usuarios WHERE id=?", (usuario_id,)
        ).fetchone()["senha"]
        assert check_password(stored, "u4-retry")
    finally:
        real.close()


def test_postgres_concurrent_token_consumers_serialize_on_account(tmp_path):
    """The second consumer blocks on the account lock before writing anything."""
    write_transaction = _require("write_transaction")
    lock_password_account = _require("lock_password_account")
    database = tmp_path / "u4-pg-token-concurrent.db"
    first_real = _bootstrap_connection(tmp_path, "u4-pg-token-concurrent.db")
    second_real = sqlite3.connect(database, timeout=0)
    second_real.row_factory = sqlite3.Row
    second_real.execute("PRAGMA foreign_keys=ON")
    registry = {}
    try:
        usuario_id, _token_id = _seed_pending_token(first_real)
        first = PostgresShapedConnection(first_real, lock_registry=registry, owner="first")
        second = PostgresShapedConnection(
            second_real, lock_registry=registry, owner="second"
        )

        with write_transaction(first):
            assert lock_password_account(first, usuario_id) is True
            with pytest.raises(PostgresLockBlocked):
                consume_password_token_and_set_password(
                    second,
                    "H" * 43,
                    PURPOSE_FIRST_ACCESS,
                    hash_password("u4-second"),
                    now=NOW,
                )
            assert not any(
                re.match(r"\s*(?:UPDATE|INSERT|DELETE)\b", sql, re.I)
                for sql, _params in second.statements
            )

        assert registry == {}
    finally:
        first_real.close()
        second_real.close()


def test_postgres_token_locks_do_not_serialize_different_accounts(tmp_path):
    registry = {}
    real = _bootstrap_connection(tmp_path, "u4-pg-multi-account.db")
    try:
        first_user, first_token = _seed_pending_token(
            real, raw="A" * 43, email="u4-a@example.test"
        )
        second_user, second_token = _seed_pending_token(
            real, raw="B" * 43, email="u4-b@example.test"
        )
        first = PostgresShapedConnection(real, lock_registry=registry, owner="first")
        second = PostgresShapedConnection(real, lock_registry=registry, owner="second")

        assert consume_password_token_and_set_password(
            first, "A" * 43, PURPOSE_FIRST_ACCESS, hash_password("u4-a"), now=NOW
        ) == 2
        assert consume_password_token_and_set_password(
            second, "B" * 43, PURPOSE_FIRST_ACCESS, hash_password("u4-b"), now=NOW
        ) == 2

        assert ("usuarios", first_user) in first.locks
        assert ("usuarios", second_user) in second.locks
        assert ("usuarios", second_user) not in first.locks
        assert ("usuarios", first_user) not in second.locks
        assert ("senha_tokens", first_token) in first.locks
        assert ("senha_tokens", second_token) in second.locks
    finally:
        real.close()


# ---------------------------------------------------------------------------
# B2. F1: one account -> token(s) lock order for every writer
# ---------------------------------------------------------------------------


def _two_connections(tmp_path, name):
    database = tmp_path / name
    first = _bootstrap_connection(tmp_path, name)
    second = sqlite3.connect(database, timeout=5.0)
    second.row_factory = sqlite3.Row
    second.execute("PRAGMA foreign_keys=ON")
    return first, second


def test_postgres_issue_locks_account_before_touching_tokens(tmp_path):
    """The issuer acquires the account lock before any senha_tokens mutation."""
    write_transaction = _require("write_transaction")
    real = _bootstrap_connection(tmp_path, "u4-f1-issue-order.db")
    try:
        usuario_id, _token_id = _seed_pending_token(real)
        pg = PostgresShapedConnection(real)
        with write_transaction(pg):
            issue_password_token(
                pg,
                usuario_id,
                PURPOSE_FIRST_ACCESS,
                now=NOW,
                token_factory=lambda _size: "I" * 43,
            )

        first_account_lock = _first_index(
            pg,
            lambda sql: "FOR UPDATE" in sql.upper() and "USUARIOS" in sql.upper(),
        )
        first_token_mutation = _first_index(
            pg,
            lambda sql: bool(
                re.match(r"\s*(?:UPDATE|INSERT)\b.*SENHA_TOKENS", sql, re.I | re.S)
            ),
        )
        assert first_account_lock is not None
        assert first_token_mutation is not None
        assert first_account_lock < first_token_mutation
    finally:
        real.close()


def test_postgres_issue_cannot_own_a_token_while_consumer_holds_account(tmp_path):
    """consume × issue: issue waits on the account before owning any token."""
    lock_password_account = _require("lock_password_account")
    lock_password_token = _require("lock_password_token")
    holder_real, issuer_real = _two_connections(tmp_path, "u4-f1-issue-blocked.db")
    registry = {}
    try:
        usuario_id, token_id = _seed_pending_token(holder_real)
        consumer_holder = PostgresShapedConnection(
            holder_real, lock_registry=registry, owner="consumer"
        )
        issuer = PostgresShapedConnection(
            issuer_real, lock_registry=registry, owner="issuer"
        )
        # The consumer's acquisitions, in order: account, then token.
        assert lock_password_account(consumer_holder, usuario_id) is True
        assert lock_password_token(consumer_holder, token_id) is True

        with pytest.raises(PostgresLockBlocked):
            issue_password_token(
                issuer,
                usuario_id,
                PURPOSE_FIRST_ACCESS,
                now=NOW,
                token_factory=lambda _size: "J" * 43,
            )
        # The issuer was stopped before it owned a token row; the pre-fix
        # protocol took the token first and only then waited on the account.
        assert not any(key[0] == "senha_tokens" for key in issuer.locks)
    finally:
        holder_real.close()
        issuer_real.close()


def test_postgres_consume_waits_for_issuer_account_lock_before_token(tmp_path):
    """consume × issue: consume waits on the account before owning any token."""
    write_transaction = _require("write_transaction")
    issuer_real, consumer_real = _two_connections(
        tmp_path, "u4-f1-consume-blocked.db"
    )
    registry = {}
    try:
        usuario_id, _token_id = _seed_pending_token(issuer_real)
        issuer = PostgresShapedConnection(
            issuer_real, lock_registry=registry, owner="issuer"
        )
        consumer = PostgresShapedConnection(
            consumer_real, lock_registry=registry, owner="consumer"
        )

        with write_transaction(issuer):
            _raw_new, new_token_id = issue_password_token(
                issuer,
                usuario_id,
                PURPOSE_FIRST_ACCESS,
                now=NOW,
                token_factory=lambda _size: "K" * 43,
            )
            with pytest.raises(PostgresLockBlocked):
                consume_password_token_and_set_password(
                    consumer,
                    "H" * 43,
                    PURPOSE_FIRST_ACCESS,
                    hash_password("u4-late"),
                    now=NOW,
                )
            assert not any(key[0] == "senha_tokens" for key in consumer.locks)

        active = issuer_real.execute(
            "SELECT id FROM senha_tokens WHERE usuario_id=? AND consumed_at IS NULL "
            "AND invalidated_at IS NULL ORDER BY id",
            (usuario_id,),
        ).fetchall()
        assert [int(row[0]) for row in active] == [new_token_id]
    finally:
        issuer_real.close()
        consumer_real.close()


def test_postgres_issue_lock_is_per_account(tmp_path):
    """An issuer for user B never touches user A's account lock."""
    lock_password_account = _require("lock_password_account")
    registry = {}
    real = _bootstrap_connection(tmp_path, "u4-f1-per-account.db")
    try:
        first_user, _first_token = _seed_pending_token(
            real, raw="A" * 43, email="u4-f1-a@example.test"
        )
        second_user, _second_token = _seed_pending_token(
            real, raw="B" * 43, email="u4-f1-b@example.test"
        )
        holder = PostgresShapedConnection(real, lock_registry=registry, owner="holder")
        issuer = PostgresShapedConnection(real, lock_registry=registry, owner="issuer")
        assert lock_password_account(holder, first_user) is True

        _raw, token_id = issue_password_token(
            issuer,
            second_user,
            PURPOSE_FIRST_ACCESS,
            now=NOW,
            token_factory=lambda _size: "L" * 43,
        )
        assert token_id > 0
        assert ("usuarios", second_user) in issuer.locks
        assert ("usuarios", first_user) not in issuer.locks
    finally:
        real.close()


def test_postgres_issue_waits_for_email_writer_account_lock(tmp_path):
    """set_usuario_email × issue cannot invert the account/token order."""
    write_transaction = _require("write_transaction")
    updater_real, issuer_real = _two_connections(tmp_path, "u4-f1-email-issue.db")
    registry = {}
    try:
        usuario_id, _token_id = _seed_pending_token(updater_real)
        updater = PostgresShapedConnection(
            updater_real, lock_registry=registry, owner="updater"
        )
        issuer = PostgresShapedConnection(
            issuer_real, lock_registry=registry, owner="issuer"
        )

        with write_transaction(updater):
            assert set_usuario_email(updater, usuario_id, "u4-f1-new@example.test") is True
            with pytest.raises(PostgresLockBlocked):
                issue_password_token(
                    issuer,
                    usuario_id,
                    PURPOSE_FIRST_ACCESS,
                    now=NOW,
                    token_factory=lambda _size: "M" * 43,
                )
            assert not any(key[0] == "senha_tokens" for key in issuer.locks)
    finally:
        updater_real.close()
        issuer_real.close()


def test_postgres_issue_waits_for_direct_password_writer_account_lock(tmp_path):
    """A direct password write × issue cannot invert the account/token order."""
    write_transaction = _require("write_transaction")
    updater_real, issuer_real = _two_connections(
        tmp_path, "u4-f1-direct-password-issue.db"
    )
    registry = {}
    try:
        usuario_id, _token_id = _seed_pending_token(updater_real)
        updater = PostgresShapedConnection(
            updater_real, lock_registry=registry, owner="updater"
        )
        issuer = PostgresShapedConnection(
            issuer_real, lock_registry=registry, owner="issuer"
        )

        with write_transaction(updater):
            set_usuario_password_hash(
                updater,
                usuario_id,
                hash_password("u4-f1-direct"),
                credential_state=CREDENTIAL_STATE_PERSONAL,
            )
            with pytest.raises(PostgresLockBlocked):
                issue_password_token(
                    issuer,
                    usuario_id,
                    PURPOSE_FIRST_ACCESS,
                    now=NOW,
                    token_factory=lambda _size: "N" * 43,
                )
            assert not any(key[0] == "senha_tokens" for key in issuer.locks)
    finally:
        updater_real.close()
        issuer_real.close()


def test_postgres_issue_keeps_exclusive_account_lock_after_fk_check(tmp_path):
    """The senha_tokens FK KEY SHARE must not downgrade the issuer's lock.

    Real PostgreSQL keeps the stronger effective row lock until the end of the
    transaction; the double previously replaced EXCLUSIVE with KEY_SHARE.
    """
    write_transaction = _require("write_transaction")
    real = _bootstrap_connection(tmp_path, "u4-f1-no-downgrade.db")
    registry = {}
    try:
        usuario_id, _token_id = _seed_pending_token(real)
        issuer = PostgresShapedConnection(real, lock_registry=registry, owner="issuer")
        with write_transaction(issuer):
            issue_password_token(
                issuer,
                usuario_id,
                PURPOSE_FIRST_ACCESS,
                now=NOW,
                token_factory=lambda _size: "O" * 43,
            )
            assert registry[("usuarios", usuario_id)]["issuer"] == MODE_EXCLUSIVE
        assert registry == {}
    finally:
        real.close()


def test_postgres_email_writer_cannot_slip_after_issuer_fk_check(tmp_path):
    """A direct address writer conflicts with the retained account lock."""
    write_transaction = _require("write_transaction")
    real = _bootstrap_connection(tmp_path, "u4-f1-issue-email-writer.db")
    registry = {}
    new_email = "u4-f1-writer@example.test"
    try:
        usuario_id, _token_id = _seed_pending_token(real)
        issuer = PostgresShapedConnection(real, lock_registry=registry, owner="issuer")
        writer = PostgresShapedConnection(real, lock_registry=registry, owner="writer")
        with write_transaction(issuer):
            issue_password_token(
                issuer,
                usuario_id,
                PURPOSE_FIRST_ACCESS,
                now=NOW,
                token_factory=lambda _size: "P" * 43,
            )
            # Issuance just ran its usuarios FK KEY SHARE check.
            with pytest.raises(PostgresLockBlocked):
                set_usuario_email(writer, usuario_id, new_email)

        stored = real.execute(
            "SELECT email FROM usuarios WHERE id=?", (usuario_id,)
        ).fetchone()[0]
        assert stored != new_email
        assert registry == {}
    finally:
        real.close()


def test_postgres_direct_password_writer_cannot_slip_after_issuer_fk_check(tmp_path):
    """A direct password writer conflicts with the retained account lock."""
    write_transaction = _require("write_transaction")
    real = _bootstrap_connection(tmp_path, "u4-f1-issue-password-writer.db")
    registry = {}
    try:
        usuario_id, _token_id = _seed_pending_token(real)
        original = real.execute(
            "SELECT senha FROM usuarios WHERE id=?", (usuario_id,)
        ).fetchone()[0]
        issuer = PostgresShapedConnection(real, lock_registry=registry, owner="issuer")
        writer = PostgresShapedConnection(real, lock_registry=registry, owner="writer")
        with write_transaction(issuer):
            issue_password_token(
                issuer,
                usuario_id,
                PURPOSE_FIRST_ACCESS,
                now=NOW,
                token_factory=lambda _size: "Q" * 43,
            )
            with pytest.raises(PostgresLockBlocked):
                set_usuario_password_hash(
                    writer,
                    usuario_id,
                    hash_password("u4-f1-slip"),
                    credential_state=CREDENTIAL_STATE_PERSONAL,
                )

        stored = real.execute(
            "SELECT senha FROM usuarios WHERE id=?", (usuario_id,)
        ).fetchone()[0]
        assert stored == original
        assert registry == {}
    finally:
        real.close()


def test_postgres_issuer_lock_stays_per_account_for_direct_writers(tmp_path):
    """A direct writer of another account is not blocked by an active issuer."""
    write_transaction = _require("write_transaction")
    real = _bootstrap_connection(tmp_path, "u4-f1-issue-other-account.db")
    registry = {}
    try:
        first_user, _first_token = _seed_pending_token(
            real, raw="A" * 43, email="u4-f1-other-a@example.test"
        )
        second_user, _second_token = _seed_pending_token(
            real, raw="B" * 43, email="u4-f1-other-b@example.test"
        )
        issuer = PostgresShapedConnection(real, lock_registry=registry, owner="issuer")
        writer = PostgresShapedConnection(real, lock_registry=registry, owner="writer")
        with write_transaction(issuer):
            issue_password_token(
                issuer,
                first_user,
                PURPOSE_FIRST_ACCESS,
                now=NOW,
                token_factory=lambda _size: "R" * 43,
            )
            with write_transaction(writer):
                assert set_usuario_email(
                    writer, second_user, "u4-f1-other-b2@example.test"
                )

        stored = real.execute(
            "SELECT email FROM usuarios WHERE id=?", (second_user,)
        ).fetchone()[0]
        assert stored == "u4-f1-other-b2@example.test"
        assert registry == {}
    finally:
        real.close()


def test_token_first_issuance_mutation_fails_the_protocol_gate(tmp_path, monkeypatch):
    """Mutation probe: without the account-first lock the order gate must fail.

    The probe removes the issuance account lock (the pre-F1 shape) and proves
    ``test_postgres_issue_locks_account_before_touching_tokens`` would refuse
    that shape, so the order gate really discriminates the repair.
    """
    import app.password_tokens as password_tokens

    write_transaction = _require("write_transaction")
    real = _bootstrap_connection(tmp_path, "u4-f1-mutation-probe.db")
    try:
        usuario_id, _token_id = _seed_pending_token(real)
        pg = PostgresShapedConnection(real)
        monkeypatch.setattr(
            password_tokens, "lock_password_account", lambda conn, uid: True
        )
        with write_transaction(pg):
            issue_password_token(
                pg,
                usuario_id,
                PURPOSE_FIRST_ACCESS,
                now=NOW,
                token_factory=lambda _size: "S" * 43,
            )

        first_account_lock = _first_index(
            pg,
            lambda sql: "FOR UPDATE" in sql.upper() and "USUARIOS" in sql.upper(),
        )
        first_token_mutation = _first_index(
            pg,
            lambda sql: bool(
                re.match(r"\s*(?:UPDATE|INSERT)\b.*SENHA_TOKENS", sql, re.I | re.S)
            ),
        )
        assert first_account_lock is None
        assert first_token_mutation is not None
    finally:
        real.close()


# ---------------------------------------------------------------------------
# B3. PostgreSQL-shaped row-lock model: retention, upgrade and compatibility
# ---------------------------------------------------------------------------


def _lock_model_connection():
    real = sqlite3.connect(":memory:")
    real.execute("CREATE TABLE usuarios(id INTEGER PRIMARY KEY, nome TEXT)")
    real.execute("INSERT INTO usuarios(id, nome) VALUES(1, 'A')")
    real.execute(
        "CREATE TABLE senha_tokens("
        "id INTEGER PRIMARY KEY, usuario_id INTEGER, purpose TEXT, "
        "token_hash TEXT, created_at TEXT, expires_at TEXT)"
    )
    return real


def _insert_token(pg, token_id):
    # The double derives the FK KEY SHARE from params[0] as ``usuario_id``,
    # matching the production INSERT parameter order.
    pg.execute(
        "INSERT INTO senha_tokens"
        "(usuario_id, purpose, token_hash, created_at, expires_at, id) "
        "VALUES(?, 'password_reset', 'h', 'now', 'later', ?)",
        (1, token_id),
    )


def test_l1_exclusive_then_key_share_keeps_exclusive():
    real = _lock_model_connection()
    registry = {}
    try:
        pg = PostgresShapedConnection(real, lock_registry=registry, owner="tx")
        pg.execute("SELECT id FROM usuarios WHERE id=? FOR UPDATE", (1,))
        assert registry[("usuarios", 1)]["tx"] == MODE_EXCLUSIVE

        _insert_token(pg, 10)  # FK KEY SHARE on usuarios(1)

        assert registry[("usuarios", 1)]["tx"] == MODE_EXCLUSIVE
        pg.commit()
        assert registry == {}
    finally:
        real.close()


def test_l2_no_key_update_then_key_share_keeps_no_key_update():
    real = _lock_model_connection()
    registry = {}
    try:
        pg = PostgresShapedConnection(real, lock_registry=registry, owner="tx")
        pg.execute("SELECT id FROM usuarios WHERE id=? FOR NO KEY UPDATE", (1,))
        assert registry[("usuarios", 1)]["tx"] == MODE_NO_KEY_UPDATE

        _insert_token(pg, 11)

        assert registry[("usuarios", 1)]["tx"] == MODE_NO_KEY_UPDATE
        pg.rollback()
        assert registry == {}
    finally:
        real.close()


def test_l3_key_share_then_exclusive_upgrades():
    real = _lock_model_connection()
    registry = {}
    try:
        pg = PostgresShapedConnection(real, lock_registry=registry, owner="tx")
        _insert_token(pg, 12)
        assert registry[("usuarios", 1)]["tx"] == MODE_KEY_SHARE

        pg.execute("SELECT id FROM usuarios WHERE id=? FOR UPDATE", (1,))

        assert registry[("usuarios", 1)]["tx"] == MODE_EXCLUSIVE
        pg.commit()
    finally:
        real.close()


def test_l4_exclusive_owner_blocks_other_no_key_update():
    real = _lock_model_connection()
    registry = {}
    try:
        first = PostgresShapedConnection(real, lock_registry=registry, owner="first")
        second = PostgresShapedConnection(real, lock_registry=registry, owner="second")
        first.execute("SELECT id FROM usuarios WHERE id=? FOR UPDATE", (1,))

        with pytest.raises(PostgresLockBlocked):
            second.execute("SELECT id FROM usuarios WHERE id=? FOR NO KEY UPDATE", (1,))

        assert registry[("usuarios", 1)] == {"first": MODE_EXCLUSIVE}
        first.commit()
        assert registry == {}
        # Released: the second owner can now acquire.
        second.execute("SELECT id FROM usuarios WHERE id=? FOR NO KEY UPDATE", (1,))
        assert registry[("usuarios", 1)] == {"second": MODE_NO_KEY_UPDATE}
    finally:
        real.close()


def test_l5_no_key_update_and_key_share_are_compatible():
    real = _lock_model_connection()
    registry = {}
    try:
        first = PostgresShapedConnection(real, lock_registry=registry, owner="first")
        second = PostgresShapedConnection(real, lock_registry=registry, owner="second")
        first.execute("SELECT id FROM usuarios WHERE id=? FOR NO KEY UPDATE", (1,))

        _insert_token(second, 13)  # KEY SHARE must not conflict

        assert registry[("usuarios", 1)] == {
            "first": MODE_NO_KEY_UPDATE,
            "second": MODE_KEY_SHARE,
        }
    finally:
        real.close()


def test_l6_commit_and_rollback_release_the_effective_lock():
    real = _lock_model_connection()
    registry = {}
    try:
        pg = PostgresShapedConnection(real, lock_registry=registry, owner="tx")
        pg.execute("SELECT id FROM usuarios WHERE id=? FOR UPDATE", (1,))
        pg.commit()
        assert registry == {}

        pg.execute("SELECT id FROM usuarios WHERE id=? FOR UPDATE", (1,))
        assert registry[("usuarios", 1)]["tx"] == MODE_EXCLUSIVE
        pg.rollback()
        assert registry == {}
    finally:
        real.close()


# ---------------------------------------------------------------------------
# C. activity-version-delete path
# ---------------------------------------------------------------------------


def test_sqlite_delete_inside_write_transaction_keeps_begin_immediate(tmp_path):
    write_transaction = _require("write_transaction")
    real = _bootstrap_connection(tmp_path, "u4-sqlite-delete.db")
    traced = []
    real.set_trace_callback(traced.append)
    try:
        base_id, (first_id, second_id) = _seed_base_with_versions(real, 1, 2)
        with write_transaction(real):
            delete_activity_version(real, base_id=base_id, versao_id=second_id)
        assert any("BEGIN IMMEDIATE" in statement for statement in traced)
        assert _version_row(real, second_id) is None
        assert _version_row(real, first_id) is not None
    finally:
        real.close()


def test_postgres_delete_locks_base_before_destructive_writes(tmp_path):
    write_transaction = _require("write_transaction")
    real = _bootstrap_connection(tmp_path, "u4-pg-delete-order.db")
    try:
        base_id, (first_id, second_id) = _seed_base_with_versions(real, 1, 2)
        pg = PostgresShapedConnection(real)

        with write_transaction(pg):
            delete_activity_version(pg, base_id=base_id, versao_id=second_id)

        assert ("atividade_base", base_id) in pg.locks
        first_lock = _first_index(
            pg, lambda sql: "FOR NO KEY UPDATE" in sql.upper()
        )
        first_destructive = _first_index(pg, _is_destructive)
        assert first_lock is not None
        assert first_destructive is not None
        assert first_lock < first_destructive
        assert "BEGIN IMMEDIATE" not in _joined_statements(pg)
        assert pg.failed_statements == []
        assert _version_row(real, second_id) is None
        assert _version_row(real, first_id) is not None
    finally:
        real.close()


def test_postgres_concurrent_deletes_serialize_per_base(tmp_path):
    """Two deletes of one base cannot both pass the survivor check."""
    write_transaction = _require("write_transaction")
    lock_activity_base = _require("lock_activity_base")
    database = tmp_path / "u4-pg-concurrent-delete.db"
    first_real = _bootstrap_connection(tmp_path, "u4-pg-concurrent-delete.db")
    second_real = sqlite3.connect(database, timeout=0)
    second_real.row_factory = sqlite3.Row
    second_real.execute("PRAGMA foreign_keys=ON")
    registry = {}
    try:
        base_id, (first_id, second_id) = _seed_base_with_versions(first_real, 1, 2)
        first = PostgresShapedConnection(first_real, lock_registry=registry, owner="first")
        second = PostgresShapedConnection(
            second_real, lock_registry=registry, owner="second"
        )

        with write_transaction(first):
            delete_activity_version(first, base_id=base_id, versao_id=second_id)
            # While the first delete holds the base lock, the second cannot
            # even begin its read-check-write, let alone reach a write.
            with pytest.raises(PostgresLockBlocked):
                lock_activity_base(second, base_id)
            assert not any(_is_destructive(sql) for sql, _ in second.statements)

        # The fake raises instead of waiting; in a real server the statement
        # would block and then acquire the lock.  Discard the failed attempt so
        # the connection models that wait-then-proceed transaction.
        second.rollback()
        assert registry == {}

        # The second delete now re-reads the committed state and refuses the
        # sole survivor instead of deleting the last version of the base.
        with write_transaction(second):
            with pytest.raises(ActivityVersionDeleteBlocked) as excinfo:
                delete_activity_version(second, base_id=base_id, versao_id=first_id)
            assert excinfo.value.code == "sole_version"
        assert _version_row(first_real, first_id) is not None
    finally:
        first_real.close()
        second_real.close()


def test_postgres_delete_locks_are_per_base_and_released(tmp_path):
    write_transaction = _require("write_transaction")
    lock_activity_base = _require("lock_activity_base")
    registry = {}
    real = _bootstrap_connection(tmp_path, "u4-pg-per-base.db")
    try:
        first_base, _ = _seed_base_with_versions(real, 1, 2)
        second_base, _ = _seed_base_with_versions(real, 1, 2)
        pg = PostgresShapedConnection(real, lock_registry=registry, owner="u4")

        with write_transaction(pg):
            assert lock_activity_base(pg, first_base) is True
            assert lock_activity_base(pg, second_base) is True

        assert ("atividade_base", first_base) in pg.locks
        assert ("atividade_base", second_base) in pg.locks
        assert registry == {}
        assert pg.info.transaction_status.name == "IDLE"
    finally:
        real.close()


def test_postgres_delete_route_uses_neutral_transaction(tmp_path, monkeypatch):
    with isolated_versioned_app_env(tmp_path, "u4-pg-delete-route.db") as env:
        client = env["client"]
        _login_admin(client)
        with main.app.app_context():
            main.close_db_connection(None)
            real = main.get_db_connection()
            base_id, (first_id, second_id) = _seed_base_with_versions(real, 1, 2)
            pg = PostgresShapedConnection(real)
            import app.views.admin.activity_version_delete as delete_view

            _install_fake_connection(monkeypatch, pg, delete_view)
            try:
                response = client.post(
                    f"/admin/catalogo-versoes/{base_id}/versoes/{second_id}/excluir",
                    follow_redirects=True,
                )
                text = response.get_data(as_text=True)
                second_exists = _version_row(real, second_id) is not None
                first_exists = _version_row(real, first_id) is not None
            finally:
                main.close_db_connection(None)

        assert response.status_code == 200
        assert "Versão excluída definitivamente com sucesso." in text
        assert ("atividade_base", base_id) in pg.locks
        assert "BEGIN IMMEDIATE" not in _joined_statements(pg)
        assert pg.failed_statements == []
        assert second_exists is False
        assert first_exists is True


def test_postgres_delete_route_rolls_back_and_releases_on_failure(tmp_path, monkeypatch):
    import app.activity_catalog as activity_catalog

    with isolated_versioned_app_env(tmp_path, "u4-pg-delete-rollback.db") as env:
        client = env["client"]
        _login_admin(client)
        with main.app.app_context():
            main.close_db_connection(None)
            real = main.get_db_connection()
            base_id, (first_id, second_id) = _seed_base_with_versions(real, 1, 2)
            pg = PostgresShapedConnection(real, lock_registry={}, owner="u4")
            import app.views.admin.activity_version_delete as delete_view

            real_renumber = activity_catalog.renumber_activity_versions

            def failing_renumber(conn, base_id):
                real_renumber(conn, base_id)
                raise RuntimeError("simulated failure after renumbering")

            monkeypatch.setattr(
                activity_catalog, "renumber_activity_versions", failing_renumber
            )
            _install_fake_connection(monkeypatch, pg, delete_view)
            try:
                response = client.post(
                    f"/admin/catalogo-versoes/{base_id}/versoes/{second_id}/excluir",
                    follow_redirects=True,
                )
                text = response.get_data(as_text=True)
                second_exists = _version_row(real, second_id) is not None
                first_exists = _version_row(real, first_id) is not None
            finally:
                main.close_db_connection(None)

        assert "nenhuma alteração foi aplicada" in text
        assert ("atividade_base", base_id) in pg.locks
        assert pg.rollbacks >= 1
        assert pg.info.transaction_status.name == "IDLE"
        assert "BEGIN IMMEDIATE" not in _joined_statements(pg)
        assert second_exists is True
        assert first_exists is True


# ---------------------------------------------------------------------------
# D. structural gates
# ---------------------------------------------------------------------------


def test_runtime_begin_immediate_is_confined_to_deferred_migrations():
    found = set()
    for path in (REPO_ROOT / "app").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        if _EXECUTED_BEGIN_IMMEDIATE_RE.search(path.read_text(encoding="utf-8")):
            found.add(path.relative_to(REPO_ROOT).as_posix())
    # app/db.py is the single runtime owner that still emits BEGIN IMMEDIATE,
    # and only on the SQLite branch of the neutral write transaction.
    assert frozenset(found) == (
        DEFERRED_MIGRATION_BEGIN_IMMEDIATE | OFFLINE_TOOL_BEGIN_IMMEDIATE | {"app/db.py"}
    )


def test_runtime_transaction_paths_use_the_neutral_manager():
    for relative in (
        "app/password_tokens.py",
        "app/views/admin/activity_version_delete.py",
    ):
        source = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert not _EXECUTED_BEGIN_IMMEDIATE_RE.search(source), relative
        assert "write_transaction" in source, relative


def test_neutral_manager_owns_engine_specific_begin():
    source = inspect.getsource(app_db)
    assert "def write_transaction" in source
    assert "BEGIN IMMEDIATE" in source
    assert "INERROR" in source
    for helper in ("lock_activity_base", "lock_password_account", "lock_password_token"):
        assert f"def {helper}" in source


def _login_admin(client):
    with client.session_transaction() as session:
        session.update(user_id=existing_admin_user_id(), user_type="admin", user_name="Admin U4")
        stamp_auth_version(session)


def _install_fake_connection(monkeypatch, fake, *modules):
    def provider():
        g.db = fake
        return fake

    monkeypatch.setattr(app_db, "get_db_connection", provider)
    for module in modules:
        monkeypatch.setattr(module, "get_db_connection", provider)
