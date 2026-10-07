# coding: utf-8
"""E-PG2: real-PostgreSQL concurrency, locking and deadlock evidence P1-P8.

Runs only when ``SGAA_PG_TEST_URL`` supplies a local PostgreSQL role with
CREATE DATABASE; otherwise the whole module skips (REAL-PG EVIDENCE: ABSENT).
The URL is server access only: nothing is written into the database it names.
Every test provisions its own disposable database under a random per-run
prefix, records it in a run registry and drops it at teardown; the registry
refuses to drop anything it did not create or that the role does not own, and
the module ends by asserting that no run-owned database is left.

Production owners under test (never monkeypatched):

* ``app.password_tokens.issue_password_token`` / ``consume_password_token_and_set_password``
  with ``app.db.lock_password_account`` (``usuarios`` FOR UPDATE) then
  ``app.db.lock_password_token`` (``senha_tokens`` FOR UPDATE);
* ``app.db.write_transaction`` and ``app.db._connect_postgres`` (READ COMMITTED);
* ``app.db.lock_activity_base`` (``atividade_base`` FOR NO KEY UPDATE);
* ``app.activity_catalog.apply_activity_version_semantic_changes`` /
  ``apply_latest_activity_version_semantic_changes`` (MAX+1 creators) and
  ``delete_activity_version`` (re-anchor + renumber);
* ``admin_atividades_importar_confirmar`` (``/admin/atividades/importar/confirmar``),
  the multi-base owner that normalizes payload order to ascending base ids.

Synchronization is deterministic: a *holder* is a production transaction the
test keeps open (the test is the caller that owns the commit), or -- only when a
self-committing production owner must be paused mid-transaction -- a raw *gate*
connection holding one row lock that the owner needs later.  Every expected
block is proven by an *observer* connection: the contender backend shows
``wait_event_type = 'Lock'`` and the expected holder is in
``pg_blocking_pids(contender)``.  Every expected non-block is proven by the
contender *completing* while the potential blocker is still open.  Sleeps are
only polling intervals under a bounded deadline, never an assertion.  Every
contender connection carries ``lock_timeout`` and ``statement_timeout``;
``deadlock_timeout`` keeps the server default.
"""
from __future__ import annotations

import os
import secrets
import threading
import time
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

import pytest

PG_URL = os.environ.get("SGAA_PG_TEST_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not PG_URL,
    reason="SGAA_PG_TEST_URL is not configured -- REAL-PG EVIDENCE: ABSENT",
)

psycopg = pytest.importorskip("psycopg")

from app import db as app_db  # noqa: E402
from app import pg_schema  # noqa: E402
from app.activity_catalog import (  # noqa: E402
    ActivityVersionDeleteBlocked,
    apply_activity_version_semantic_changes,
    apply_latest_activity_version_semantic_changes,
    delete_activity_version,
)
from app.password_tokens import (  # noqa: E402
    PURPOSE_PASSWORD_RESET,
    consume_password_token_and_set_password,
    issue_password_token,
)

#: Every database this run creates carries this prefix (random per run).
RUN_PREFIX = f"sgaa_epg2_test_{secrets.token_hex(4)}_"
PROTECTED_DATABASES = frozenset({"postgres", "template0", "template1", "sgaa_qual"})
CONNECT_TIMEOUT_SECONDS = 10
LOCK_TIMEOUT_MS = 5000
STATEMENT_TIMEOUT_MS = 30000
#: Bounded deadlines for the harness itself (observation and thread joins).
OBSERVE_DEADLINE_SECONDS = 15.0
JOIN_DEADLINE_SECONDS = 40.0
POLL_INTERVAL_SECONDS = 0.005

DEADLOCK_SQLSTATE = "40P01"
LOCK_NOT_AVAILABLE_SQLSTATE = "55P03"
ACCOUNT_LOCK_SQL = "FROM usuarios WHERE id = $1 FOR UPDATE"
TOKEN_LOCK_SQL = "FROM senha_tokens WHERE id = $1 FOR UPDATE"
BASE_LOCK_SQL = "FROM atividade_base WHERE id = $1 FOR NO KEY UPDATE"


def _database_url(database, *, guarded):
    parts = urlsplit(PG_URL)
    query = {"connect_timeout": str(CONNECT_TIMEOUT_SECONDS)}
    if guarded:
        query["options"] = (
            f"-c lock_timeout={LOCK_TIMEOUT_MS} "
            f"-c statement_timeout={STATEMENT_TIMEOUT_MS}"
        )
    return urlunsplit((parts.scheme, parts.netloc, "/" + database, urlencode(query, quote_via=quote), ""))


def _raw_connect(url, *, autocommit=False):
    return psycopg.connect(
        url,
        prepare_threshold=None,
        autocommit=autocommit,
        connect_timeout=CONNECT_TIMEOUT_SECONDS,
    )


class _RunDatabaseRegistry:
    """Sole creator and destroyer of this run's disposable databases."""

    def __init__(self):
        self._admin = None
        self._owned = set()

    def admin(self):
        if self._admin is None or self._admin.closed:
            self._admin = _raw_connect(_database_url("sgaa_qual", guarded=False), autocommit=True)
        return self._admin

    def create_provisioned(self, label):
        database = f"{RUN_PREFIX}{label}_{secrets.token_hex(4)}"
        self.admin().execute(f'CREATE DATABASE "{database}"')
        self._owned.add(database)
        connection = _raw_connect(_database_url(database, guarded=False))
        try:
            result = pg_schema.provision_pg_schema(connection)
            connection.commit()
        finally:
            connection.close()
        assert result["status"] == "provisioned"
        return database

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
        # Plain DROP first: it makes autovacuum workers in the database exit and
        # waits for them, whereas FORCE must terminate them and a non-superuser
        # role may not (InsufficientPrivilege).  FORCE is only the fallback for
        # a leftover run connection.
        try:
            self.admin().execute(f'DROP DATABASE IF EXISTS "{database}"')
        except psycopg.errors.ObjectInUse:
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
# harness: workers, holders, gates, observer
# ---------------------------------------------------------------------------


class Worker:
    """Runs one production call on its own thread; its exception propagates."""

    def __init__(self, name, target):
        self.name = name
        self._target = target
        self._result = None
        self._error = None
        self._thread = threading.Thread(target=self._run, name=f"epg2-{name}", daemon=True)

    def _run(self):
        try:
            self._result = self._target()
        except BaseException as exc:  # re-raised in the test thread
            self._error = exc

    def start(self):
        self._thread.start()
        return self

    @property
    def finished(self):
        return not self._thread.is_alive()

    def join(self):
        self._thread.join(JOIN_DEADLINE_SECONDS)
        if self._thread.is_alive():
            raise AssertionError(f"worker {self.name} did not finish within the deadline")

    def outcome(self):
        self.join()
        if self._error is not None:
            sqlstate = getattr(self._error, "sqlstate", None)
            if sqlstate == DEADLOCK_SQLSTATE:
                raise AssertionError(
                    f"worker {self.name} hit a PostgreSQL deadlock (40P01)"
                ) from self._error
            raise self._error
        return self._result

    @property
    def error(self):
        self.join()
        return self._error


class HeldWrite:
    """A production ``write_transaction`` whose commit the test (the caller) owns."""

    def __init__(self, connection):
        self.connection = connection
        self._manager = app_db.write_transaction(connection)
        self._open = False

    def __enter__(self):
        self._manager.__enter__()
        self._open = True
        return self.connection

    def commit(self):
        assert self._open, "holder is not open"
        self._open = False
        self._manager.__exit__(None, None, None)

    def abort(self):
        if not self._open:
            return
        self._open = False
        sentinel = RuntimeError("E-PG2 harness abort")
        try:
            self._manager.__exit__(RuntimeError, sentinel, None)
        except RuntimeError as exc:
            if exc is not sentinel:
                raise


class Env:
    """One disposable provisioned database plus every connection a test opens."""

    def __init__(self, registry, database):
        self.registry = registry
        self.database = database
        self.url = _database_url(database, guarded=True)
        self._connections = []
        self._holders = []
        self._gates = []
        self._workers = []
        self.observer = self._track(_raw_connect(self.url, autocommit=True))

    def _track(self, connection):
        self._connections.append(connection)
        return connection

    # -- connections -------------------------------------------------------
    def production(self):
        """A connection from the production factory (READ COMMITTED adapter)."""
        previous = app_db.DATABASE_URL
        app_db.DATABASE_URL = self.url
        try:
            connection = app_db._connect_postgres()
        finally:
            app_db.DATABASE_URL = previous
        self._track(connection.raw_connection)
        return connection

    def raw(self):
        """A raw non-autocommit connection: gate or NOWAIT probe only."""
        return self._track(_raw_connect(self.url))

    def hold(self, connection):
        holder = HeldWrite(connection)
        self._holders.append(holder)
        return holder

    def gate(self, sql, params):
        """Controlled lock orchestration: one raw row lock held until released."""
        connection = self.raw()
        row = connection.execute(sql, params).fetchone()
        assert row is not None, "gate target row is missing"
        self._gates.append(connection)
        return connection

    def worker(self, name, target):
        worker = Worker(name, target)
        self._workers.append(worker)
        return worker.start()

    # -- teardown ----------------------------------------------------------
    def close(self):
        problems = []
        for holder in reversed(self._holders):
            try:
                holder.abort()
            except Exception as exc:
                problems.append(f"holder abort: {exc!r}")
        for gate in self._gates:
            try:
                if not gate.closed:
                    gate.rollback()
            except Exception as exc:
                problems.append(f"gate rollback: {exc!r}")
        for worker in self._workers:
            worker._thread.join(JOIN_DEADLINE_SECONDS)
            if worker._thread.is_alive():
                problems.append(f"worker {worker.name} still running at teardown")
        for connection in reversed(self._connections):
            try:
                if not connection.closed:
                    if not connection.autocommit:
                        connection.rollback()
                    connection.close()
            except Exception as exc:
                problems.append(f"connection close: {exc!r}")
        assert not problems, problems


def _pid(connection):
    raw = getattr(connection, "raw_connection", connection)
    return raw.info.backend_pid


def _activity(observer, pid):
    row = observer.execute(
        "SELECT state, wait_event_type, wait_event, query, pg_blocking_pids(pid), backend_xid "
        "FROM pg_stat_activity WHERE pid = %s",
        (pid,),
    ).fetchone()
    assert row is not None, f"backend {pid} is not visible in pg_stat_activity"
    keys = ("state", "wait_event_type", "wait_event", "query", "blocking", "backend_xid")
    return dict(zip(keys, row))


def wait_until_blocked(observer, pid, *, by, worker=None):
    """Return the activity row once ``pid`` waits on a heavyweight lock held by ``by``.

    ``by`` is the set of pids allowed to be the blocker; at least one blocker
    must be in it and no other blocker may appear.  Fails loudly if the worker
    finishes (or raises) without ever blocking, or on the bounded deadline.
    """
    allowed = set(by)
    deadline = time.monotonic() + OBSERVE_DEADLINE_SECONDS
    last = None
    while time.monotonic() < deadline:
        if worker is not None and worker.finished:
            worker.outcome()
            raise AssertionError(
                f"worker {worker.name} finished without blocking (last={last!r})"
            )
        last = _activity(observer, pid)
        blocking = set(last["blocking"] or ())
        if last["wait_event_type"] == "Lock" and blocking:
            assert blocking <= allowed, (
                f"backend {pid} blocked by unexpected pids {blocking - allowed}; "
                f"allowed {allowed}"
            )
            return last
        time.sleep(POLL_INTERVAL_SECONDS)
    raise AssertionError(f"backend {pid} never blocked on a lock held by {allowed}: {last!r}")


def wait_for_new_lock_waiter(observer, *, known, by, worker):
    """Discover the pid of a route worker whose connection the request opens."""
    deadline = time.monotonic() + OBSERVE_DEADLINE_SECONDS
    rows = None
    while time.monotonic() < deadline:
        if worker.finished:
            worker.outcome()
            raise AssertionError(f"worker {worker.name} finished without blocking")
        rows = observer.execute(
            "SELECT pid, pg_blocking_pids(pid) FROM pg_stat_activity "
            "WHERE datname = current_database() AND wait_event_type = 'Lock' "
            "AND NOT (pid = ANY(%s))",
            (list(known),),
        ).fetchall()
        candidates = [pid for pid, blocking in rows if set(blocking or ()) & set(by)]
        assert len(candidates) <= 1, f"ambiguous new lock waiters: {rows!r}"
        if candidates:
            return candidates[0]
        time.sleep(POLL_INTERVAL_SECONDS)
    raise AssertionError(f"no new lock waiter blocked by {set(by)}: {rows!r}")


def _relation_locks(observer, pid):
    rows = observer.execute(
        "SELECT c.relname, l.mode, l.granted FROM pg_locks l "
        "JOIN pg_class c ON c.oid = l.relation "
        "WHERE l.pid = %s AND l.locktype = 'relation'",
        (pid,),
    ).fetchall()
    return {(relname, mode, granted) for relname, mode, granted in rows}


def _row_lock_free(probe, sql, params):
    """NOWAIT probe: True when the row lock is obtainable, False on 55P03."""
    try:
        probe.execute(sql + " NOWAIT", params).fetchone()
    except psycopg.errors.LockNotAvailable as exc:
        assert exc.sqlstate == LOCK_NOT_AVAILABLE_SQLSTATE
        probe.rollback()
        return False
    probe.rollback()
    return True


def _assert_guarded(connection):
    raw = getattr(connection, "raw_connection", connection)
    settings = raw.execute(
        "SELECT current_setting('lock_timeout'), current_setting('statement_timeout'), "
        "current_setting('transaction_isolation')"
    ).fetchone()
    raw.rollback()
    assert settings[0] == f"{LOCK_TIMEOUT_MS // 1000}s", settings
    assert settings[1] == f"{STATEMENT_TIMEOUT_MS // 1000}s", settings
    return settings[2]


# ---------------------------------------------------------------------------
# fixtures and seeding
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


@pytest.fixture()
def env(registry, request):
    label = request.node.name.split("_")[1][:3]
    database = registry.create_provisioned(label)
    try:
        environment = Env(registry, database)
        try:
            yield environment
        finally:
            environment.close()
    finally:
        registry.drop(database)


@pytest.fixture(scope="module")
def password_hashes():
    from app.security.passwords import hash_password

    return {
        "seed": hash_password("epg2-seed"),
        "a": hash_password("epg2-alpha"),
        "b": hash_password("epg2-beta"),
    }


def _seed_user(env, hashes, *, email="epg2.user@example.test", credential_state="personal"):
    from app.user_accounts import create_usuario_with_access_level

    connection = env.production()
    with app_db.write_transaction(connection):
        usuario_id = int(
            create_usuario_with_access_level(
                connection, "EPG2 Usuario", email, hashes["seed"], "admin",
                "admin_total", credential_state=credential_state,
            ).usuario_id
        )
    return usuario_id


def _seed_token(env, usuario_id, purpose=PURPOSE_PASSWORD_RESET):
    connection = env.production()
    with app_db.write_transaction(connection):
        raw_token, token_id = issue_password_token(connection, usuario_id, purpose)
    return raw_token, token_id


def _token_rows(env, usuario_id):
    return {
        row[0]: {"consumed": row[1] is not None, "invalidated": row[2] is not None}
        for row in env.observer.execute(
            "SELECT id, consumed_at, invalidated_at FROM senha_tokens "
            "WHERE usuario_id = %s ORDER BY id",
            (usuario_id,),
        ).fetchall()
    }


def _account(env, usuario_id):
    row = env.observer.execute(
        "SELECT u.senha, c.estado, c.auth_version FROM usuarios u "
        "JOIN usuario_credenciais c ON c.usuario_id = u.id WHERE u.id = %s",
        (usuario_id,),
    ).fetchone()
    return {"senha": row[0], "estado": row[1], "auth_version": int(row[2])}


def _seed_base(env, statuses, *, nome=None, grupo="1 - EPG2"):
    """One base with a chained v1..vN version set; returns (base_id, [ids])."""
    connection = env.observer
    base_id = connection.execute(
        "INSERT INTO atividade_base(nome_conceito, status) VALUES (%s, 'ativo') RETURNING id",
        (nome or f"EPG2 Base {secrets.token_hex(4)}",),
    ).fetchone()[0]
    ids = []
    for number, status in enumerate(statuses, start=1):
        ids.append(
            connection.execute(
                "INSERT INTO atividade_versao(atividade_base_id, eixo, grupo, limite_total, "
                "numero_versao, status, versao_anterior_id) "
                "VALUES (%s, 'AAC', %s, 40, %s, %s, %s) RETURNING id",
                (base_id, grupo, number, status, ids[-1] if ids else None),
            ).fetchone()[0]
        )
    return int(base_id), [int(i) for i in ids]


def _versions(env, base_id):
    """[(id, numero_versao, versao_anterior_id, status)] ordered by number."""
    return [
        tuple(row)
        for row in env.observer.execute(
            "SELECT id, numero_versao, versao_anterior_id, status FROM atividade_versao "
            "WHERE atividade_base_id = %s ORDER BY numero_versao, id",
            (base_id,),
        ).fetchall()
    ]


def _assert_canonical_version_set(versions):
    numbers = [number for _id, number, _prev, _status in versions]
    assert numbers == list(range(1, len(versions) + 1)), versions
    ids = {version_id for version_id, *_rest in versions}
    for version_id, _number, previous, _status in versions:
        assert previous is None or previous in ids, (version_id, previous, versions)


def _in_write(connection, call):
    def run():
        with app_db.write_transaction(connection):
            return call(connection)

    return run


# ===========================================================================
# P1 -- account -> token lock order (issue x consume)
# ===========================================================================


def test_p1a_issuer_holds_account_consumer_blocks_on_account_first(env, password_hashes):
    """Issuer owns the account; the consumer waits on the account, not the token."""
    usuario_id = _seed_user(env, password_hashes)
    raw_token, token_id = _seed_token(env, usuario_id)
    before = _account(env, usuario_id)

    issuer = env.production()
    _assert_guarded(issuer)
    holder = env.hold(issuer)
    holder.__enter__()
    _new_raw, new_token_id = issue_password_token(issuer, usuario_id, PURPOSE_PASSWORD_RESET)

    consumer = env.production()
    _assert_guarded(consumer)
    consumer_pid = _pid(consumer)
    worker = env.worker(
        "consume",
        lambda: consume_password_token_and_set_password(
            consumer, raw_token, PURPOSE_PASSWORD_RESET, password_hashes["a"]
        ),
    )
    blocked = wait_until_blocked(env.observer, consumer_pid, by={_pid(issuer)}, worker=worker)
    assert ACCOUNT_LOCK_SQL in blocked["query"], blocked
    consumer_locks = _relation_locks(env.observer, consumer_pid)
    # Waiting on the account row: the token row lock was not requested yet.
    assert ("usuarios", "RowShareLock", True) in consumer_locks, consumer_locks
    assert not any(
        rel == "senha_tokens" and mode != "AccessShareLock"
        for rel, mode, _granted in consumer_locks
    ), consumer_locks

    holder.commit()

    # Post-lock re-resolution sees the committed supersession: clean refusal.
    assert worker.outcome() is None
    tokens = _token_rows(env, usuario_id)
    assert tokens[token_id] == {"consumed": False, "invalidated": True}
    assert tokens[new_token_id] == {"consumed": False, "invalidated": False}
    assert _account(env, usuario_id) == before


def test_p1b_consumer_holds_account_and_token_issuer_blocks_on_account(env, password_hashes):
    """The deadlock-prone shape: consumer owns account+token, issuer arrives.

    An issuer that touched ``senha_tokens`` before the account would own token
    rows and then wait on the account while the consumer waits on those rows.
    """
    usuario_id = _seed_user(env, password_hashes)
    raw_token, token_id = _seed_token(env, usuario_id)
    before = _account(env, usuario_id)

    gate = env.gate(
        "SELECT usuario_id FROM usuario_credenciais WHERE usuario_id = %s FOR UPDATE",
        (usuario_id,),
    )
    consumer = env.production()
    consumer_pid = _pid(consumer)
    consumer_worker = env.worker(
        "consume",
        lambda: consume_password_token_and_set_password(
            consumer, raw_token, PURPOSE_PASSWORD_RESET, password_hashes["a"]
        ),
    )
    paused = wait_until_blocked(env.observer, consumer_pid, by={_pid(gate)}, worker=consumer_worker)
    assert "usuario_credenciais" in paused["query"], paused
    # The paused consumer already owns the account row, then the token row.
    probe = env.raw()
    assert not _row_lock_free(probe, "SELECT id FROM usuarios WHERE id = %s FOR UPDATE", (usuario_id,))
    assert not _row_lock_free(probe, "SELECT id FROM senha_tokens WHERE id = %s FOR UPDATE", (token_id,))

    issuer = env.production()
    issuer_pid = _pid(issuer)
    issued = {}

    def issue():
        with app_db.write_transaction(issuer):
            issued["raw"], issued["id"] = issue_password_token(
                issuer, usuario_id, PURPOSE_PASSWORD_RESET
            )
        return issued["id"]

    issuer_worker = env.worker("issue", issue)
    blocked = wait_until_blocked(env.observer, issuer_pid, by={consumer_pid}, worker=issuer_worker)
    assert ACCOUNT_LOCK_SQL in blocked["query"], blocked
    issuer_locks = _relation_locks(env.observer, issuer_pid)
    assert not any(rel == "senha_tokens" for rel, _mode, _granted in issuer_locks), issuer_locks

    gate.rollback()
    auth_version = consumer_worker.outcome()
    new_token_id = issuer_worker.outcome()

    assert auth_version == before["auth_version"] + 1
    tokens = _token_rows(env, usuario_id)
    assert tokens[token_id] == {"consumed": True, "invalidated": False}
    assert tokens[new_token_id] == {"consumed": False, "invalidated": False}
    after = _account(env, usuario_id)
    assert after == {
        "senha": password_hashes["a"],
        "estado": "personal",
        "auth_version": before["auth_version"] + 1,
    }


# ===========================================================================
# P2 -- consume x consume of the same token
# ===========================================================================


def test_p2_concurrent_consume_of_one_token_succeeds_exactly_once(env, password_hashes):
    usuario_id = _seed_user(env, password_hashes)
    raw_token, token_id = _seed_token(env, usuario_id)
    before = _account(env, usuario_id)

    gate = env.gate(
        "SELECT usuario_id FROM usuario_credenciais WHERE usuario_id = %s FOR UPDATE",
        (usuario_id,),
    )
    first = env.production()
    first_pid = _pid(first)
    first_worker = env.worker(
        "consume-a",
        lambda: consume_password_token_and_set_password(
            first, raw_token, PURPOSE_PASSWORD_RESET, password_hashes["a"]
        ),
    )
    wait_until_blocked(env.observer, first_pid, by={_pid(gate)}, worker=first_worker)

    second = env.production()
    second_pid = _pid(second)
    second_worker = env.worker(
        "consume-b",
        lambda: consume_password_token_and_set_password(
            second, raw_token, PURPOSE_PASSWORD_RESET, password_hashes["b"]
        ),
    )
    # The second consumer resolved the (still valid) token and now waits on
    # the account row owned by the first consumer.
    blocked = wait_until_blocked(env.observer, second_pid, by={first_pid}, worker=second_worker)
    assert ACCOUNT_LOCK_SQL in blocked["query"], blocked

    gate.rollback()
    first_result = first_worker.outcome()
    second_result = second_worker.outcome()

    assert first_result == before["auth_version"] + 1
    assert second_result is None
    assert _token_rows(env, usuario_id) == {token_id: {"consumed": True, "invalidated": False}}
    assert _account(env, usuario_id) == {
        "senha": password_hashes["a"],
        "estado": "personal",
        "auth_version": before["auth_version"] + 1,
    }
    for connection in (first, second):
        assert connection.raw_connection.info.transaction_status.name == "IDLE"


# ===========================================================================
# P3 -- FOR NO KEY UPDATE semantics of lock_activity_base
# ===========================================================================


def test_p3a_base_lock_conflicts_with_itself(env):
    base_id, _ids = _seed_base(env, ["ativa"])
    holder_conn = env.production()
    holder = env.hold(holder_conn)
    holder.__enter__()
    assert app_db.lock_activity_base(holder_conn, base_id) is True

    contender = env.production()
    contender_pid = _pid(contender)
    worker = env.worker(
        "lock", _in_write(contender, lambda c: app_db.lock_activity_base(c, base_id))
    )
    blocked = wait_until_blocked(env.observer, contender_pid, by={_pid(holder_conn)}, worker=worker)
    assert BASE_LOCK_SQL in blocked["query"], blocked

    holder.commit()
    assert worker.outcome() is True


def test_p3b_base_lock_admits_fk_key_share_and_is_not_for_update(env):
    base_id, ids = _seed_base(env, ["ativa"])
    holder_conn = env.production()
    holder = env.hold(holder_conn)
    holder.__enter__()
    assert app_db.lock_activity_base(holder_conn, base_id) is True
    holder_pid = _pid(holder_conn)

    # Lock-mode identification by the PostgreSQL row-lock conflict matrix:
    # KEY SHARE is compatible only with NO KEY UPDATE (not FOR UPDATE), and
    # FOR SHARE / NO KEY UPDATE both conflict with it.
    probe = env.raw()
    select = "SELECT id FROM atividade_base WHERE id = %s"
    assert _row_lock_free(probe, select + " FOR KEY SHARE", (base_id,))
    assert not _row_lock_free(probe, select + " FOR SHARE", (base_id,))
    assert not _row_lock_free(probe, select + " FOR NO KEY UPDATE", (base_id,))

    # A real FK-referencing insert (PostgreSQL's own KEY SHARE check on the
    # base) completes and commits while the base lock is still held.
    inserter = env.production()
    worker = env.worker(
        "fk-insert",
        _in_write(
            inserter,
            lambda c: c.execute(
                "INSERT INTO atividade_versao(atividade_base_id, eixo, grupo, numero_versao, "
                "status, versao_anterior_id) VALUES (?, 'AAC', '1 - EPG2', 2, 'rascunho', ?) "
                "RETURNING id",
                (base_id, ids[0]),
            ).fetchone()[0],
        ),
    )
    inserted_id = worker.outcome()
    assert _activity(env.observer, holder_pid)["state"] == "idle in transaction"
    assert [v[0] for v in _versions(env, base_id)] == [ids[0], inserted_id]
    holder.commit()


def test_p3c_control_for_update_would_block_the_fk_insert(env):
    """Negative control: the harness does detect a stronger (FOR UPDATE) lock."""
    base_id, ids = _seed_base(env, ["ativa"])
    gate = env.gate("SELECT id FROM atividade_base WHERE id = %s FOR UPDATE", (base_id,))
    inserter = env.production()
    worker = env.worker(
        "fk-insert",
        _in_write(
            inserter,
            lambda c: c.execute(
                "INSERT INTO atividade_versao(atividade_base_id, eixo, grupo, numero_versao, "
                "status, versao_anterior_id) VALUES (?, 'AAC', '1 - EPG2', 2, 'rascunho', ?) "
                "RETURNING id",
                (base_id, ids[0]),
            ).fetchone()[0],
        ),
    )
    blocked = wait_until_blocked(env.observer, _pid(inserter), by={_pid(gate)}, worker=worker)
    assert "INSERT INTO atividade_versao" in blocked["query"], blocked
    gate.rollback()
    assert worker.outcome() is not None


# ===========================================================================
# P4 -- create x create on the same base
# ===========================================================================


def test_p4_concurrent_creators_serialize_and_number_contiguously(env):
    base_id, ids = _seed_base(env, ["ativa", "ativa"])
    latest = ids[-1]

    holder_conn = env.production()
    holder = env.hold(holder_conn)
    holder.__enter__()
    first = apply_activity_version_semantic_changes(holder_conn, latest, {"limite_total": 50})
    assert first["mode"] == "successor"

    contender = env.production()
    contender_pid = _pid(contender)
    worker = env.worker(
        "create",
        _in_write(
            contender,
            lambda c: apply_activity_version_semantic_changes(c, latest, {"limite_total": 60}),
        ),
    )
    blocked = wait_until_blocked(env.observer, contender_pid, by={_pid(holder_conn)}, worker=worker)
    assert BASE_LOCK_SQL in blocked["query"], blocked

    holder.commit()
    second = worker.outcome()
    assert second["mode"] == "successor"

    versions = _versions(env, base_id)
    _assert_canonical_version_set(versions)
    by_id = {v[0]: v for v in versions}
    assert by_id[first["version_id"]][1] == 3
    assert by_id[second["version_id"]][1] == 4
    assert by_id[first["version_id"]][2] == latest
    assert by_id[second["version_id"]][2] == latest
    assert len(versions) == 4


# ===========================================================================
# P5 -- create x delete: fresh READ COMMITTED snapshot after the base lock
# ===========================================================================


def test_p5_creator_after_delete_uses_post_commit_state(env):
    # Make the database default REPEATABLE READ: only the production factory's
    # explicit READ COMMITTED keeps the post-lock reads fresh.
    env.observer.execute(
        f'ALTER DATABASE "{env.database}" SET default_transaction_isolation = \'repeatable read\''
    )
    base_id, (v1, v2, v3) = _seed_base(env, ["ativa", "ativa", "ativa"])

    plain = env.raw()
    assert plain.execute("SHOW transaction_isolation").fetchone()[0] == "repeatable read"
    plain.rollback()

    deleter = env.production()
    assert _assert_guarded(deleter) == "read committed"
    holder = env.hold(deleter)
    holder.__enter__()
    delete_activity_version(deleter, base_id=base_id, versao_id=v2)

    creator = env.production()
    assert _assert_guarded(creator) == "read committed"
    creator_pid = _pid(creator)
    seen = {}

    def create(c):
        # A pre-lock read in the same transaction (as a request would do):
        # under a transaction snapshot it would pin the three-version state.
        seen["pre_lock"] = c.execute(
            "SELECT COUNT(*) FROM atividade_versao WHERE atividade_base_id = ?", (base_id,)
        ).fetchone()[0]
        return apply_latest_activity_version_semantic_changes(c, base_id, {"limite_total": 77})

    worker = env.worker("create", _in_write(creator, create))
    blocked = wait_until_blocked(env.observer, creator_pid, by={_pid(deleter)}, worker=worker)
    assert BASE_LOCK_SQL in blocked["query"], blocked
    assert seen["pre_lock"] == 3

    holder.commit()
    created = worker.outcome()

    assert created["mode"] == "successor"
    assert created["predecessor_id"] == v3
    versions = _versions(env, base_id)
    _assert_canonical_version_set(versions)
    assert versions == [
        (v1, 1, None, "ativa"),
        (v3, 2, v1, "ativa"),
        (created["version_id"], 3, v3, "rascunho"),
    ]


# ===========================================================================
# P6 -- delete x delete
# ===========================================================================


def test_p6a_concurrent_deletes_of_different_versions(env):
    base_id, (v1, v2, v3, v4) = _seed_base(env, ["ativa"] * 4)

    first = env.production()
    holder = env.hold(first)
    holder.__enter__()
    delete_activity_version(first, base_id=base_id, versao_id=v2)

    second = env.production()
    second_pid = _pid(second)
    worker = env.worker(
        "delete",
        _in_write(second, lambda c: delete_activity_version(c, base_id=base_id, versao_id=v3)),
    )
    blocked = wait_until_blocked(env.observer, second_pid, by={_pid(first)}, worker=worker)
    assert BASE_LOCK_SQL in blocked["query"], blocked

    holder.commit()
    assert worker.outcome() is None

    versions = _versions(env, base_id)
    _assert_canonical_version_set(versions)
    # v4's predecessor was re-anchored twice: v3 -> v2's predecessor -> v1.
    assert versions == [(v1, 1, None, "ativa"), (v4, 2, v1, "ativa")]


def test_p6b_concurrent_deletes_of_the_same_version(env):
    base_id, (v1, v2, v3) = _seed_base(env, ["ativa"] * 3)

    first = env.production()
    holder = env.hold(first)
    holder.__enter__()
    delete_activity_version(first, base_id=base_id, versao_id=v2)

    second = env.production()
    second_pid = _pid(second)
    worker = env.worker(
        "delete",
        _in_write(second, lambda c: delete_activity_version(c, base_id=base_id, versao_id=v2)),
    )
    blocked = wait_until_blocked(env.observer, second_pid, by={_pid(first)}, worker=worker)
    assert BASE_LOCK_SQL in blocked["query"], blocked

    holder.commit()
    error = worker.error
    assert isinstance(error, ActivityVersionDeleteBlocked), repr(error)
    assert error.code == "wrong_base_or_version"
    assert second.raw_connection.info.transaction_status.name == "IDLE"

    versions = _versions(env, base_id)
    _assert_canonical_version_set(versions)
    assert versions == [(v1, 1, None, "ativa"), (v3, 2, v1, "ativa")]


# ===========================================================================
# P7 -- multi-base import with opposite payload order
# ===========================================================================

IMPORT_ROUTE = "/admin/atividades/importar/confirmar"
TIPO_AAC = "Acadêmica Complementar"


def _import_row(base_id, group_number):
    return {
        "action": "update",
        "existing_id": base_id,
        "tipo_atividade": TIPO_AAC,
        "grupo_numero": str(group_number),
        "grupo_descricao": f"EPG2 W{group_number}",
        "grupo": f"{group_number} - EPG2 W{group_number}",
        "limite_horas_total": 100 + group_number,
        "limite_horas_semestral": None,
    }


@pytest.fixture()
def route_app(env, password_hashes, monkeypatch):
    import main
    from app.user_accounts import get_usuario_auth_version

    usuario_id = _seed_user(env, password_hashes, email="epg2.admin@example.test")
    connection = env.production()
    auth_version = get_usuario_auth_version(connection, usuario_id)
    connection.rollback()
    monkeypatch.setattr(app_db, "DATABASE_URL", env.url)
    monkeypatch.setitem(main.app.config, "TESTING", True)

    def client():
        test_client = main.app.test_client()
        with test_client.session_transaction() as session:
            session.update(
                user_id=usuario_id,
                user_type="admin",
                user_name="EPG2 Admin",
                auth_version=auth_version,
            )
        return test_client

    try:
        yield {"app": main.app, "client": client}
    finally:
        with main.app.app_context():
            app_db.close_db_connection(None)


def _store_preview(app, rows):
    from app.views.admin.atividades import _store_atividades_import_preview

    with app.test_request_context():
        return _store_atividades_import_preview({"rows": rows, "csv_relpath": None})


def _post_import(client, preview_key):
    response = client.post(IMPORT_ROUTE, data={"preview_key": preview_key})
    with client.session_transaction() as session:
        flashes = [message for _category, message in session.pop("_flashes", [])]
    return response.status_code, flashes


def test_p7_opposite_payload_orders_lock_bases_in_one_global_order(env, route_app):
    base_a, (a1,) = _seed_base(env, ["ativa"])
    base_b, (b1,) = _seed_base(env, ["ativa"])
    assert base_a < base_b
    key_ab = _store_preview(route_app["app"], [_import_row(base_a, 91), _import_row(base_b, 91)])
    key_ba = _store_preview(route_app["app"], [_import_row(base_b, 92), _import_row(base_a, 92)])

    # Hold the lower base A: with the global ascending order both workers must
    # queue on A while B stays free.  A payload-ordered worker 2 would own B
    # and wait on A -- then the gate release forces the A/B cycle (40P01).
    gate = env.gate("SELECT id FROM atividade_base WHERE id = %s FOR NO KEY UPDATE", (base_a,))
    gate_pid = _pid(gate)
    known = {gate_pid, _pid(env.observer)}

    client_ab, client_ba = route_app["client"](), route_app["client"]()
    worker_ab = env.worker("import-ab", lambda: _post_import(client_ab, key_ab))
    pid_ab = wait_for_new_lock_waiter(env.observer, known=known, by={gate_pid}, worker=worker_ab)
    blocked_ab = wait_until_blocked(env.observer, pid_ab, by={gate_pid}, worker=worker_ab)
    assert BASE_LOCK_SQL in blocked_ab["query"], blocked_ab
    known.add(pid_ab)

    worker_ba = env.worker("import-ba", lambda: _post_import(client_ba, key_ba))
    pid_ba = wait_for_new_lock_waiter(
        env.observer, known=known, by={gate_pid, pid_ab}, worker=worker_ba
    )
    blocked_ba = wait_until_blocked(env.observer, pid_ba, by={gate_pid, pid_ab}, worker=worker_ba)
    assert BASE_LOCK_SQL in blocked_ba["query"], blocked_ba

    # Both workers wait on A; neither owns B.
    probe = env.raw()
    assert _row_lock_free(
        probe, "SELECT id FROM atividade_base WHERE id = %s FOR NO KEY UPDATE", (base_b,)
    )
    assert not _row_lock_free(
        probe, "SELECT id FROM atividade_base WHERE id = %s FOR NO KEY UPDATE", (base_a,)
    )

    gate.rollback()
    for worker in (worker_ab, worker_ba):
        status, flashes = worker.outcome()
        assert status == 302, (worker.name, status, flashes)
        assert "Importação concluída. Criadas: 0. Atualizadas: 2." in flashes, flashes

    versions_a = _versions(env, base_a)
    versions_b = _versions(env, base_b)
    for versions, first_id in ((versions_a, a1), (versions_b, b1)):
        _assert_canonical_version_set(versions)
        assert len(versions) == 2, versions
        assert versions[0] == (first_id, 1, None, "ativa")
        assert versions[1][2] == first_id and versions[1][3] == "rascunho"
    grupos = {
        row[0]: row[1]
        for row in env.observer.execute(
            "SELECT atividade_base_id, grupo FROM atividade_versao WHERE id IN (%s, %s)",
            (versions_a[1][0], versions_b[1][0]),
        ).fetchall()
    }
    # Whole-transaction serialization: the last committer wrote both bases.
    assert grupos[base_a] == grupos[base_b]
    assert grupos[base_a] in {"91 - EPG2 W91", "92 - EPG2 W92"}
    assert sorted(
        env.observer.execute(
            "SELECT numero FROM grupos_def WHERE tipo_atividade = %s AND numero IN (91, 92)",
            (TIPO_AAC,),
        ).fetchall()
    ) == [(91,), (92,)]


# ===========================================================================
# P8 -- different bases: no cross-base serialization (negative control)
# ===========================================================================


def test_p8_creators_on_different_bases_do_not_serialize(env):
    base_a, (a1,) = _seed_base(env, ["ativa"])
    base_b, (b1,) = _seed_base(env, ["ativa"])

    holder_conn = env.production()
    holder = env.hold(holder_conn)
    holder.__enter__()
    on_a = apply_activity_version_semantic_changes(holder_conn, a1, {"limite_total": 51})
    assert on_a["mode"] == "successor"
    holder_pid = _pid(holder_conn)

    contender = env.production()
    contender_pid = _pid(contender)
    worker = env.worker(
        "create-b",
        _in_write(
            contender,
            lambda c: apply_activity_version_semantic_changes(c, b1, {"limite_total": 52}),
        ),
    )
    # The equivalent operation on B completes and commits while A's creator
    # still holds its base lock and uncommitted successor: it was never
    # blocked by the A transaction (a blocked worker cannot finish).
    on_b = worker.outcome()
    assert on_b["mode"] == "successor"
    holder_state = _activity(env.observer, holder_pid)
    assert holder_state["state"] == "idle in transaction", holder_state
    assert _activity(env.observer, contender_pid)["wait_event_type"] != "Lock"
    assert len(_versions(env, base_a)) == 1  # A's successor is not committed yet
    assert [v[1] for v in _versions(env, base_b)] == [1, 2]

    holder.commit()
    for base_id, first_id, created in ((base_a, a1, on_a), (base_b, b1, on_b)):
        versions = _versions(env, base_id)
        _assert_canonical_version_set(versions)
        assert versions == [
            (first_id, 1, None, "ativa"),
            (created["version_id"], 2, first_id, "rascunho"),
        ]
