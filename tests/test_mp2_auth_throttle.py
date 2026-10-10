# coding: utf-8
"""MP-2 slice 3: the durable login / recovery throttle (``app.auth_throttle``) on SQLite.

Store-level proofs use an explicit clock.  Selector proofs run the real
login and recovery views with the hosted switch on.  The discriminating
pairs: a fresh instance (empty process memory) still blocks when hosted and
does NOT when local; a blocked key writes nothing; the table never holds an
address or an e-mail.
"""

from __future__ import annotations

import datetime
import sqlite3

import pytest

from app import auth, auth_throttle, password_recovery_limiter
from app.prod1_schema import bootstrap_prod1_schema

T0 = datetime.datetime(2026, 10, 9, 12, 0, 0)
WINDOW = 600
SECRET = "unit-secret-" + "0" * 40


@pytest.fixture
def conn(tmp_path):
    connection = sqlite3.connect(str(tmp_path / "throttle.db"))
    connection.execute("PRAGMA foreign_keys=ON")
    bootstrap_prod1_schema(connection)
    yield connection
    connection.close()


def _digest(scope="login_account", value="aluno@example.test"):
    return auth_throttle.key_digest(scope, value, secret=SECRET)


def _fail(conn, n, *, scope="login_account", value="aluno@example.test", start=T0, step=1):
    for index in range(n):
        auth_throttle.register(conn, [(scope, _digest(scope, value))], window_seconds=WINDOW,
                               now=start + datetime.timedelta(seconds=index * step))


def _blocked(conn, *, scope="login_account", value="aluno@example.test", max_attempts=8, now=T0):
    return auth_throttle.blocked(conn, scope, _digest(scope, value), window_seconds=WINDOW,
                                 max_attempts=max_attempts, now=now)


# --- store ------------------------------------------------------------------------


def test_a_key_is_blocked_exactly_at_its_limit_and_reports_the_time_left(conn):
    _fail(conn, 7)
    assert _blocked(conn, now=T0 + datetime.timedelta(seconds=10)) == (False, 0)
    _fail(conn, 1, start=T0 + datetime.timedelta(seconds=7))
    blocked, retry_in = _blocked(conn, now=T0 + datetime.timedelta(seconds=100))
    assert blocked is True
    assert retry_in == WINDOW - 100  # measured from the OLDEST event in the window


def test_events_older_than_the_window_stop_counting(conn):
    _fail(conn, 8)
    assert _blocked(conn, now=T0 + datetime.timedelta(seconds=30))[0] is True
    assert _blocked(conn, now=T0 + datetime.timedelta(seconds=WINDOW + 8)) == (False, 0)


def test_keys_and_scopes_are_isolated(conn):
    _fail(conn, 8)
    assert _blocked(conn, value="outra@example.test") == (False, 0)
    assert _blocked(conn, scope="recovery_account")[0] is False
    assert _blocked(conn)[0] is True


def test_registering_prunes_the_keys_expired_events_and_a_bounded_global_batch(conn):
    old = T0 - datetime.timedelta(seconds=WINDOW + 60)
    _fail(conn, 3, value="vazio@example.test", start=old)
    for index in range(auth_throttle.GLOBAL_PRUNE_BATCH + 50):
        conn.execute(
            "INSERT INTO auth_throttle_events(scope,key_digest,occurred_at) VALUES(?,?,?)",
            ("login_account", _digest("login_account", f"conta{index}@example.test"), (old - datetime.timedelta(seconds=index)).strftime("%Y-%m-%d %H:%M:%S")),
        )
    conn.commit()
    cutoff = (T0 - datetime.timedelta(seconds=WINDOW)).strftime("%Y-%m-%d %H:%M:%S")
    _fail(conn, 1, value="vazio@example.test", start=T0)
    expired = conn.execute("SELECT count(*) FROM auth_throttle_events WHERE occurred_at <= ?", (cutoff,)).fetchone()[0]
    live = conn.execute("SELECT count(*) FROM auth_throttle_events WHERE occurred_at > ?", (cutoff,)).fetchone()[0]
    # The key's own 3 expired events went, then exactly one bounded batch of the 250 others:
    # the backlog shrinks by the batch, it is not wiped in one request.
    assert live == 1
    assert expired == 250 - auth_throttle.GLOBAL_PRUNE_BATCH


def test_a_write_prunes_only_the_scopes_it_wrote_with_that_scopes_window(conn):
    """A shorter login window must not delete recovery events still inside the longer recovery window."""
    recovery_window = 900
    for index in range(6):
        auth_throttle.register(
            conn, [("recovery_ip", _digest("recovery_ip", "198.51.100.5"))],
            window_seconds=recovery_window, now=T0 + datetime.timedelta(seconds=index),
        )
    later = T0 + datetime.timedelta(seconds=700)  # past the login window (600), inside recovery's (900)
    auth_throttle.register(
        conn, [("login_ip", _digest("login_ip", "203.0.113.5"))], window_seconds=WINDOW, now=later
    )
    kept = conn.execute("SELECT count(*) FROM auth_throttle_events WHERE scope='recovery_ip'").fetchone()[0]
    assert kept == 6, "a login failure pruned the recovery scope"
    flagged = auth_throttle.blocked(
        conn, "recovery_ip", _digest("recovery_ip", "198.51.100.5"), window_seconds=recovery_window,
        max_attempts=6, now=later + datetime.timedelta(seconds=1),
    )
    assert flagged[0] is True


def test_a_limit_of_zero_blocks_outright_like_the_memory_limiter(conn):
    assert _blocked(conn, max_attempts=0) == (True, WINDOW)


def test_clear_removes_only_the_named_keys(conn):
    _fail(conn, 3)
    _fail(conn, 2, value="outra@example.test")
    auth_throttle.clear(conn, [("login_account", _digest())])
    counts = dict(conn.execute("SELECT key_digest, count(*) FROM auth_throttle_events GROUP BY key_digest").fetchall())
    assert counts == {_digest(value="outra@example.test"): 2}


def test_the_table_holds_keyed_digests_never_the_value(conn):
    _fail(conn, 1, scope="login_ip", value="203.0.113.77")
    _fail(conn, 1, value="Secreto.Pessoa@Example.Test")
    stored = " ".join(row[0] for row in conn.execute("SELECT key_digest FROM auth_throttle_events"))
    assert "203.0.113.77" not in stored and "secreto" not in stored.lower()
    assert len(stored.split()) == 2 and all(len(d) == 64 for d in stored.split())


def test_the_digest_is_keyed_scoped_and_stable():
    assert _digest() == _digest()
    assert _digest() != _digest(scope="recovery_account")
    assert _digest() != auth_throttle.key_digest("login_account", "aluno@example.test", secret=SECRET + "x")
    assert _digest() != _digest(value="aluno2@example.test")


# --- selector ---------------------------------------------------------------------


_THRESHOLD_KEYS = (
    "LOGIN_MAX_ATTEMPTS", "LOGIN_ACCOUNT_MAX_ATTEMPTS", "LOGIN_WINDOW_SECONDS",
    "PASSWORD_RESET_MAX_ATTEMPTS", "PASSWORD_RESET_ACCOUNT_MAX_ATTEMPTS", "PASSWORD_RESET_WINDOW_SECONDS",
)


@pytest.fixture
def web():
    """The shared test application with its limiter state and thresholds restored afterwards."""
    import main

    saved = {key: main.app.config.get(key) for key in _THRESHOLD_KEYS}
    auth._login_attempts.clear()
    auth._login_attempts_by_account.clear()
    password_recovery_limiter.clear_password_recovery_attempts()
    try:
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute("DELETE FROM auth_throttle_events")
            conn.commit()
            yield main.app
            conn.execute("DELETE FROM auth_throttle_events")
            conn.commit()
    finally:
        for key, value in saved.items():
            if value is None:
                main.app.config.pop(key, None)
            else:
                main.app.config[key] = value
        auth._login_attempts.clear()
        auth._login_attempts_by_account.clear()
        password_recovery_limiter.clear_password_recovery_attempts()


def _rows():
    import main

    return main.get_db_connection().execute("SELECT count(*) FROM auth_throttle_events").fetchone()[0]


def test_local_mode_keeps_the_in_memory_limiter_and_never_touches_the_table(web, monkeypatch):
    monkeypatch.delenv("SGAA_RUNTIME", raising=False)
    web.config.update(LOGIN_MAX_ATTEMPTS=3, LOGIN_ACCOUNT_MAX_ATTEMPTS=3)
    for _ in range(3):
        auth_throttle.login_failed("198.51.100.1", "a@example.test")
    assert auth_throttle.login_blocked(web, "198.51.100.1", "a@example.test")[0] is True
    assert auth._login_attempts["198.51.100.1"] and _rows() == 0
    # a "new instance" (empty memory) forgets: the limitation the hosted store removes
    auth._login_attempts.clear()
    auth._login_attempts_by_account.clear()
    assert auth_throttle.login_blocked(web, "198.51.100.1", "a@example.test") == (False, 0)


def test_hosted_mode_survives_a_fresh_instance_and_leaves_memory_untouched(web, monkeypatch):
    monkeypatch.setenv("SGAA_RUNTIME", "hosted")
    web.config.update(LOGIN_MAX_ATTEMPTS=3, LOGIN_ACCOUNT_MAX_ATTEMPTS=3)
    for _ in range(3):
        auth_throttle.login_failed("198.51.100.1", "A@Example.Test ")
    auth._login_attempts.clear()
    auth._login_attempts_by_account.clear()
    flagged, retry_in = auth_throttle.login_blocked(web, "198.51.100.1", "nobody@example.test")
    assert flagged is True and 0 < retry_in <= web.config["LOGIN_WINDOW_SECONDS"]  # the IP limit
    assert auth_throttle.login_blocked(web, "203.0.113.9", "a@example.test")[0] is True  # the account limit
    assert auth_throttle.login_blocked(web, "203.0.113.9", "someone.else@example.test") == (False, 0)
    assert not auth._login_attempts and not auth._login_attempts_by_account
    assert _rows() == 6  # three failures, two keys each


def test_a_blocked_attempt_writes_nothing_and_success_clears_both_keys(web, monkeypatch):
    monkeypatch.setenv("SGAA_RUNTIME", "hosted")
    web.config.update(LOGIN_MAX_ATTEMPTS=2, LOGIN_ACCOUNT_MAX_ATTEMPTS=2)
    for _ in range(2):
        auth_throttle.login_failed("198.51.100.2", "b@example.test")
    before = _rows()
    for _ in range(5):
        assert auth_throttle.login_blocked(web, "198.51.100.2", "b@example.test")[0] is True
    assert _rows() == before
    auth_throttle.login_succeeded("198.51.100.2", "b@example.test")
    assert _rows() == 0
    assert auth_throttle.login_blocked(web, "198.51.100.2", "b@example.test") == (False, 0)


def test_recovery_uses_its_own_scopes_and_thresholds(web, monkeypatch):
    monkeypatch.setenv("SGAA_RUNTIME", "hosted")
    web.config.update(PASSWORD_RESET_MAX_ATTEMPTS=2, PASSWORD_RESET_ACCOUNT_MAX_ATTEMPTS=2,
                      LOGIN_MAX_ATTEMPTS=10, LOGIN_ACCOUNT_MAX_ATTEMPTS=10)
    for _ in range(2):
        auth_throttle.recovery_attempted("198.51.100.3", "c@example.test")
    assert auth_throttle.recovery_blocked(web, "198.51.100.3", "c@example.test")[0] is True
    assert auth_throttle.login_blocked(web, "198.51.100.3", "c@example.test") == (False, 0)
    scopes = {row[0] for row in __import__("main").get_db_connection().execute(
        "SELECT DISTINCT scope FROM auth_throttle_events")}
    assert scopes == {"recovery_ip", "recovery_account"}


def test_the_hosted_limit_uses_the_configured_window(web, monkeypatch):
    monkeypatch.setenv("SGAA_RUNTIME", "hosted")
    web.config.update(LOGIN_MAX_ATTEMPTS=1, LOGIN_ACCOUNT_MAX_ATTEMPTS=1, LOGIN_WINDOW_SECONDS=1)
    auth_throttle.login_failed("198.51.100.4", None)
    assert auth_throttle.login_blocked(web, "198.51.100.4", None)[0] is True  # inside the window
    import time

    time.sleep(2.2)
    assert auth_throttle.login_blocked(web, "198.51.100.4", None) == (False, 0)


def test_a_limit_of_zero_matches_the_memory_limiter_through_the_selectors(web, monkeypatch):
    web.config.update(LOGIN_MAX_ATTEMPTS=0, LOGIN_ACCOUNT_MAX_ATTEMPTS=0)
    monkeypatch.delenv("SGAA_RUNTIME", raising=False)
    local = auth_throttle.login_blocked(web, "198.51.100.6", "z@example.test")
    monkeypatch.setenv("SGAA_RUNTIME", "hosted")
    hosted = auth_throttle.login_blocked(web, "198.51.100.6", "z@example.test")
    assert local[0] is True and hosted[0] is True
    assert hosted[1] == web.config["LOGIN_WINDOW_SECONDS"]


def test_an_unreadable_store_fails_closed_before_the_password_is_checked(web, monkeypatch):
    """No fallback to memory and no pass-through: the check raises and the login view has no handler for it."""
    monkeypatch.setenv("SGAA_RUNTIME", "hosted")

    def unreadable(*_a, **_k):
        raise sqlite3.OperationalError("auth_throttle_events is unreadable")

    monkeypatch.setattr(auth_throttle, "blocked", unreadable)
    with pytest.raises(sqlite3.OperationalError):
        auth_throttle.login_blocked(web, "198.51.100.7", "z@example.test")
    with pytest.raises(sqlite3.OperationalError):
        auth_throttle.recovery_blocked(web, "198.51.100.7", "z@example.test")
    assert not auth._login_attempts  # nothing was recorded in memory instead


def test_the_durable_limits_come_from_configuration_and_a_missing_value_fails_closed(web, monkeypatch):
    monkeypatch.setenv("SGAA_RUNTIME", "hosted")
    saved = web.config.pop("LOGIN_WINDOW_SECONDS")
    try:
        with pytest.raises(KeyError):
            auth_throttle.login_blocked(web, "198.51.100.9", "z@example.test")
        with pytest.raises(KeyError):
            auth_throttle.login_failed("198.51.100.9", "z@example.test")
    finally:
        web.config["LOGIN_WINDOW_SECONDS"] = saved


def test_a_failed_attempt_that_cannot_be_recorded_is_an_error_but_a_failed_clear_is_not(web, monkeypatch):
    monkeypatch.setenv("SGAA_RUNTIME", "hosted")

    def broken(*_a, **_k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(auth_throttle, "register", broken)
    with pytest.raises(sqlite3.OperationalError):
        auth_throttle.login_failed("198.51.100.8", "z@example.test")  # fail closed: do not pretend it counted
    monkeypatch.setattr(auth_throttle, "clear", broken)
    assert auth_throttle.login_succeeded("198.51.100.8", "z@example.test") is None  # the user is in; events age out
