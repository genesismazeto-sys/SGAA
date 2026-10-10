# coding: utf-8
"""MP-2 slice 3 on real PostgreSQL (opt-in, ``SGAA_PG_TEST_URL``): durable throttle, previews, schema v16.

Without ``SGAA_PG_TEST_URL`` the module skips (REAL-PG EVIDENCE: ABSENT).

E-PG1: the real login and recovery views of two INDEPENDENT hosted application
instances share one database, so a limit tripped through one instance holds in
the other; a blocked attempt writes nothing; the table holds only keyed digests;
the v16 schema provisions with its constraints, and a preview round-trips.

E-PG2: concurrent writers on separate connections lose no event, never
deadlock (the pruning batch skips rows another writer holds), and the limit
flips at exactly its threshold.
"""

from __future__ import annotations

import datetime
import tempfile
import threading

import pytest

from tests.mp2_pg_support import ADMIN_EMAIL, ADMIN_PASSWORD, PG_URL, Registry, adapter, seed_admin

pytestmark = pytest.mark.skipif(
    not PG_URL, reason="SGAA_PG_TEST_URL is not configured -- REAL-PG EVIDENCE: ABSENT"
)

psycopg = pytest.importorskip("psycopg")

from app import auth_throttle, import_previews, pg_schema  # noqa: E402

JOIN_TIMEOUT_SECONDS = 60
T0 = datetime.datetime(2026, 10, 9, 12, 0, 0)
WINDOW = 600


@pytest.fixture(scope="module")
def registry():
    registry = Registry("thr")
    try:
        registry.provision_template(seed=seed_admin)
        yield registry
    finally:
        assert registry.close() == 0


@pytest.fixture
def database(registry):
    name, url = registry.create(template=registry.template)
    yield url
    registry.drop(name)


def _hosted_app(monkeypatch, url, tmp_path, **config_env):
    import app.db as app_db

    for name in ("VERCEL", "AWS_LAMBDA_FUNCTION_NAME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SGAA_RUNTIME", "hosted")
    monkeypatch.setenv("TRUST_PROXY_XFF", "1")
    monkeypatch.setenv("APP_SECRET_KEY", "t" + "3" * 47)
    for key, value in config_env.items():
        monkeypatch.setenv(key, str(value))
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(app_db, "DATABASE_URL", url)
    from app import create_app

    return create_app()


def _login(client, email, password, ip):
    return client.post("/login", data={"email": email, "senha": password},
                       headers={"X-Forwarded-For": ip})


def _events(url):
    conn = adapter(url)
    try:
        return [tuple(r) for r in conn.execute(
            "SELECT scope, key_digest FROM auth_throttle_events ORDER BY id").fetchall()]
    finally:
        conn.close()


# --- schema ------------------------------------------------------------------------


def test_the_provisioned_schema_is_v16_with_both_tables_and_their_rules(database):
    conn = adapter(database)
    try:
        status = pg_schema.validate_pg_schema(conn)
        assert status["schema_version"] == 16
        assert conn.execute("SELECT count(*) FROM auth_throttle_events").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM admin_import_previews").fetchone()[0] == 0
        for sql, params in (
            ("INSERT INTO auth_throttle_events(scope,key_digest,occurred_at) VALUES('nope',%s,'2026-10-09 12:00:00')", ("a" * 64,)),
            ("INSERT INTO auth_throttle_events(scope,key_digest,occurred_at) VALUES('login_ip','xyz','2026-10-09 12:00:00')", ()),
            ("INSERT INTO auth_throttle_events(scope,key_digest,occurred_at) VALUES('login_ip',%s,'2026-10-09 24:00:00')", ("a" * 64,)),
            ("INSERT INTO admin_import_previews(token_digest,usuario_id,payload,created_at,expires_at)"
             " VALUES(%s,999999,'{}','2026-10-09 12:00:00','2026-10-09 13:00:00')", ("b" * 64,)),
            ("INSERT INTO admin_import_previews(token_digest,usuario_id,payload,created_at,expires_at)"
             " VALUES(%s,1,'{}','2026-10-09 12:00:00','2026-10-09 12:00:00')", ("b" * 64,)),
        ):
            with pytest.raises(psycopg.errors.Error):
                conn.raw_connection.execute(sql, params)
            conn.rollback()
    finally:
        conn.close()


def test_preview_state_round_trips_and_is_owned_on_postgresql(database):
    conn = adapter(database)
    try:
        admin_id = conn.execute("SELECT id FROM usuarios LIMIT 1").fetchone()[0]
        token = import_previews.store(conn, usuario_id=admin_id, payload={"rows": [{"nome": "Extensão"}]}, now=T0)
        assert import_previews.load(conn, usuario_id=admin_id, token=token, now=T0) == {"rows": [{"nome": "Extensão"}]}
        assert import_previews.load(conn, usuario_id=admin_id + 1, token=token, now=T0) is None
        import_previews.discard(conn, usuario_id=admin_id, token=token)
        assert import_previews.load(conn, usuario_id=admin_id, token=token, now=T0) is None
        later = T0 + datetime.timedelta(seconds=import_previews.TTL_SECONDS * 2)
        for index in range(3):
            import_previews.store(conn, usuario_id=admin_id, payload={"n": index}, now=T0 + datetime.timedelta(seconds=index))
        import_previews.store(conn, usuario_id=admin_id, payload={"n": "late"}, now=later)
        assert conn.execute("SELECT count(*) FROM admin_import_previews").fetchone()[0] == 1
    finally:
        conn.close()


# --- the real views, two instances -------------------------------------------------


def test_a_limit_tripped_through_one_instance_holds_in_another(database, monkeypatch, tmp_path):
    first = _hosted_app(monkeypatch, database, tmp_path, LOGIN_MAX_ATTEMPTS=50, LOGIN_ACCOUNT_MAX_ATTEMPTS=3)
    second = _hosted_app(monkeypatch, database, tmp_path, LOGIN_MAX_ATTEMPTS=50, LOGIN_ACCOUNT_MAX_ATTEMPTS=3)
    assert first is not second
    a, b = first.test_client(), second.test_client()
    for index in range(3):
        assert _login(a, ADMIN_EMAIL, "senha-errada", f"198.51.100.{index}").status_code == 200
    # Both instances live in this one process, so the in-memory limiter's dictionaries are
    # shared: empty them, as a separate process would have them, so only the database can block.
    from app import auth

    auth._login_attempts.clear()
    auth._login_attempts_by_account.clear()
    # The correct password, from a never-seen address, on a DIFFERENT instance: blocked.
    blocked = _login(b, ADMIN_EMAIL, ADMIN_PASSWORD, "203.0.113.50")
    assert blocked.status_code == 429
    # Another account is unaffected, and so is this one's neighbour on the same address.
    assert _login(b, "outra.conta@example.test", "x", "203.0.113.50").status_code == 200


def test_a_blocked_attempt_writes_nothing_and_the_table_holds_only_digests(database, monkeypatch, tmp_path):
    app = _hosted_app(monkeypatch, database, tmp_path, LOGIN_MAX_ATTEMPTS=50, LOGIN_ACCOUNT_MAX_ATTEMPTS=2)
    client = app.test_client()
    for _ in range(2):
        _login(client, ADMIN_EMAIL, "errada", "198.51.100.77")
    written = _events(database)
    assert len(written) == 4  # two failures, an ip key and an account key each
    for _ in range(5):
        assert _login(client, ADMIN_EMAIL, "errada", "198.51.100.77").status_code == 429
    assert _events(database) == written
    flat = " ".join(digest for _scope, digest in written)
    assert "198.51.100.77" not in flat and ADMIN_EMAIL.split("@")[0] not in flat
    assert all(len(digest) == 64 for _scope, digest in written)


def test_a_successful_login_clears_the_failures_it_follows(database, monkeypatch, tmp_path):
    app = _hosted_app(monkeypatch, database, tmp_path, LOGIN_MAX_ATTEMPTS=50, LOGIN_ACCOUNT_MAX_ATTEMPTS=5)
    client = app.test_client()
    for _ in range(3):
        _login(client, ADMIN_EMAIL, "errada", "198.51.100.8")
    assert len(_events(database)) == 6
    ok = _login(client, ADMIN_EMAIL, ADMIN_PASSWORD, "198.51.100.8")
    assert ok.status_code == 302
    assert _events(database) == []


def test_password_recovery_is_throttled_across_instances_with_its_own_scopes(database, monkeypatch, tmp_path):
    config = dict(PASSWORD_RESET_MAX_ATTEMPTS=50, PASSWORD_RESET_ACCOUNT_MAX_ATTEMPTS=2)
    first = _hosted_app(monkeypatch, database, tmp_path, **config)
    second = _hosted_app(monkeypatch, database, tmp_path, **config)
    # An address that belongs to no account: the neutral path, no mail, but the attempt still counts.
    for client in (first.test_client(), second.test_client()):
        assert client.post("/esqueci-minha-senha", data={"email": "ninguem@example.test"},
                           headers={"X-Forwarded-For": "198.51.100.9"}).status_code == 200
    scopes = sorted({scope for scope, _digest in _events(database)})
    assert scopes == ["recovery_account", "recovery_ip"]
    before = _events(database)
    third = first.test_client().post("/esqueci-minha-senha", data={"email": "ninguem@example.test"},
                                     headers={"X-Forwarded-For": "198.51.100.10"})
    assert third.status_code == 200
    assert _events(database) == before  # the account is over its limit: nothing more is written


# --- E-PG2 -------------------------------------------------------------------------


def _run(workers):
    errors = []

    def guarded(fn):
        def runner():
            try:
                fn()
            except BaseException as exc:  # reported, never swallowed
                errors.append(repr(exc))

        return runner

    threads = [threading.Thread(target=guarded(fn)) for fn in workers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(JOIN_TIMEOUT_SECONDS)
        assert not thread.is_alive(), "a writer is stuck: a lock wait that never ended"
    assert errors == []


def test_concurrent_failures_lose_no_event_and_the_limit_flips_at_its_threshold(database):
    digest = auth_throttle.key_digest("login_account", "alvo@example.test", secret="s" * 40)
    writers = 12
    connections = [adapter(database) for _ in range(writers)]
    try:
        _run([lambda c=c, i=i: auth_throttle.register(
            c, [("login_account", digest)], window_seconds=WINDOW, now=T0 + datetime.timedelta(seconds=i))
            for i, c in enumerate(connections)])
        probe = adapter(database)
        try:
            assert probe.execute("SELECT count(*) FROM auth_throttle_events WHERE key_digest = ?",
                                 (digest,)).fetchone()[0] == writers
            now = T0 + datetime.timedelta(seconds=30)
            assert auth_throttle.blocked(probe, "login_account", digest, window_seconds=WINDOW,
                                         max_attempts=writers, now=now)[0] is True
            assert auth_throttle.blocked(probe, "login_account", digest, window_seconds=WINDOW,
                                         max_attempts=writers + 1, now=now) == (False, 0)
        finally:
            probe.close()
    finally:
        for conn in connections:
            conn.close()


def test_concurrent_writers_over_an_expired_backlog_never_deadlock(database):
    seeder = adapter(database)
    old = T0 - datetime.timedelta(seconds=WINDOW * 4)
    try:
        for index in range(600):
            seeder.execute(
                "INSERT INTO auth_throttle_events(scope,key_digest,occurred_at) VALUES(?,?,?)",
                ("login_ip", f"{index:064x}", (old - datetime.timedelta(seconds=index)).strftime("%Y-%m-%d %H:%M:%S")),
            )
        seeder.commit()
    finally:
        seeder.close()
    connections = [adapter(database) for _ in range(8)]
    try:
        keys = [auth_throttle.key_digest("login_ip", f"10.0.0.{i}", secret="s" * 40) for i in range(8)]
        _run([lambda c=c, k=k: [auth_throttle.register(c, [("login_ip", k)], window_seconds=WINDOW, now=T0)
                                for _ in range(5)] for c, k in zip(connections, keys)])
    finally:
        for conn in connections:
            conn.close()
    probe = adapter(database)
    try:
        live = probe.execute("SELECT count(*) FROM auth_throttle_events WHERE occurred_at > ?",
                             ((T0 - datetime.timedelta(seconds=WINDOW)).strftime("%Y-%m-%d %H:%M:%S"),)).fetchone()[0]
        expired = probe.execute("SELECT count(*) FROM auth_throttle_events WHERE occurred_at <= ?",
                                ((T0 - datetime.timedelta(seconds=WINDOW)).strftime("%Y-%m-%d %H:%M:%S"),)).fetchone()[0]
        assert live == 40  # every concurrent event survived the concurrent pruning
        assert expired < 600  # and the backlog did shrink: the pruners made progress without waiting
    finally:
        probe.close()


def test_a_pruner_never_waits_on_rows_another_writer_holds(database):
    """Deterministic: a transaction holding the expired rows must not stall a writer.

    Without ``SKIP LOCKED`` the pruning subquery of the second writer would queue
    behind the holder (and two such writers could deadlock on overlapping batches).
    """
    seeder = adapter(database)
    old = T0 - datetime.timedelta(seconds=WINDOW * 4)
    try:
        for index in range(30):
            seeder.execute(
                "INSERT INTO auth_throttle_events(scope,key_digest,occurred_at) VALUES(?,?,?)",
                ("login_ip", f"{index:064x}", (old - datetime.timedelta(seconds=index)).strftime("%Y-%m-%d %H:%M:%S")),
            )
        seeder.commit()
    finally:
        seeder.close()
    holder = adapter(database)
    writer = adapter(database)
    try:
        held = holder.execute(
            "SELECT id FROM auth_throttle_events WHERE scope = 'login_ip' ORDER BY id FOR UPDATE"
        ).fetchall()
        assert len(held) == 30
        done = []

        def write():
            # The same scope as the held backlog: its prune subquery is what must skip them.
            auth_throttle.register(writer, [("login_ip", "a" * 64)], window_seconds=WINDOW, now=T0)
            done.append(True)

        thread = threading.Thread(target=write)
        thread.start()
        thread.join(15)
        assert done == [True], "the writer queued behind rows it did not need"
        holder.rollback()
    finally:
        holder.close()
        writer.close()
    probe = adapter(database)
    try:
        # the held rows were skipped, not deleted; the new event is committed
        cutoff = (T0 - datetime.timedelta(seconds=WINDOW)).strftime("%Y-%m-%d %H:%M:%S")
        assert probe.execute("SELECT count(*) FROM auth_throttle_events WHERE occurred_at <= ?",
                             (cutoff,)).fetchone()[0] == 30
        assert probe.execute("SELECT count(*) FROM auth_throttle_events WHERE occurred_at > ?",
                             (cutoff,)).fetchone()[0] == 1
    finally:
        probe.close()


def test_two_simultaneous_confirmations_of_one_preview_apply_exactly_one(database):
    """E-PG2: the claim is a DELETE ... RETURNING inside each caller's transaction."""
    from app.db import write_transaction

    seeder = adapter(database)
    try:
        admin_id = seeder.execute("SELECT id FROM usuarios LIMIT 1").fetchone()[0]
        token = import_previews.store(seeder, usuario_id=admin_id, payload={"rows": []}, now=T0)
    finally:
        seeder.close()
    contenders = 6
    connections = [adapter(database) for _ in range(contenders)]
    barrier = threading.Barrier(contenders)
    outcomes = []

    def contend(conn):
        barrier.wait(timeout=JOIN_TIMEOUT_SECONDS)
        with write_transaction(conn):
            outcomes.append(import_previews.claim(conn, usuario_id=admin_id, token=token, now=T0))

    try:
        _run([lambda c=c: contend(c) for c in connections])
    finally:
        for conn in connections:
            conn.close()
    assert sorted(outcomes) == [False] * (contenders - 1) + [True]
    probe = adapter(database)
    try:
        assert probe.execute("SELECT count(*) FROM admin_import_previews").fetchone()[0] == 0
    finally:
        probe.close()
