# coding: utf-8
"""MP-2 slice 4: the authenticated scheduler front (``app.storage.scheduler``).

The front is a WSGI callable outside the web application.  Proofs: disabled
without a long enough secret; every unauthenticated shape is refused BEFORE
the application, database or any provider is built or touched; an authorized
GET or POST runs exactly one bounded mirror pass; failures answer fixed codes
and never exception text; the secret is never echoed.
"""

from __future__ import annotations

import hashlib
import hmac
from types import SimpleNamespace

import pytest
from werkzeug.test import Client

from app import hosting
from app.storage import drive_mirror, scheduler
from tests.storage_mp1_support import (
    BUCKET,
    sqlite_storage_env,
    seed_canonical_arquivo,
    seed_canonical_request_document,
)
from tests.storage_s3a_support import PDF

SECRET = "c" * 40
SENTINEL = "SENTINEL-EXCEPTION-TEXT-0123456789"


class Spy:
    def __init__(self):
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        raise AssertionError("the application / a provider was touched before authentication")


@pytest.fixture
def front(monkeypatch):
    for name in (scheduler.BATCH_ENV, scheduler.LEASE_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CRON_SECRET", SECRET)
    monkeypatch.setattr(scheduler, "_app", None)
    return SimpleNamespace(
        client=Client(scheduler.application),
        headers={"Authorization": f"Bearer {SECRET}"},
        path=scheduler.ROUTE_MIRROR,
    )


@pytest.fixture
def untouched(monkeypatch):
    """Every way past the authentication gate is a recording failure."""
    spies = SimpleNamespace(build=Spy(), run=Spy())
    monkeypatch.setattr(scheduler, "_build_app", spies.build)
    monkeypatch.setattr(drive_mirror, "run_mirror_pass", spies.run)
    return spies


def _assert_clean(response):
    body = response.get_data(as_text=True)
    assert SECRET not in body and SECRET not in str(response.headers)
    assert "Set-Cookie" not in response.headers
    assert response.headers["Cache-Control"] == "no-store"


# --- the gate -----------------------------------------------------------------------


@pytest.mark.parametrize("secret", [None, "", "short", "x" * (hosting.CRON_SECRET_MIN_LENGTH - 1)])
def test_the_front_is_disabled_without_a_long_enough_secret(front, untouched, monkeypatch, secret):
    if secret is None:
        monkeypatch.delenv("CRON_SECRET")
    else:
        monkeypatch.setenv("CRON_SECRET", secret)
    for method in ("get", "post"):
        response = getattr(front.client, method)(front.path, headers={"Authorization": f"Bearer {secret or ''}"})
        assert response.status_code == 404
        _assert_clean(response)
    assert untouched.build.calls == [] and untouched.run.calls == []


def test_the_minimum_length_boundary_enables_the_front(front, untouched, monkeypatch):
    exact = "e" * hosting.CRON_SECRET_MIN_LENGTH
    monkeypatch.setenv("CRON_SECRET", exact)
    response = front.client.get(front.path, headers={"Authorization": "Bearer nope"})
    assert response.status_code == 401  # enabled: it asks for credentials
    assert untouched.build.calls == []


@pytest.mark.parametrize("path", ["/", "/health", "/internal/scheduler", "/internal/scheduler/mirror/", "/INTERNAL/scheduler/mirror",
                                  "/internal/scheduler/mirror/extra", "/internal/scheduler/converge"])
def test_every_other_path_is_a_404_even_with_valid_credentials(front, untouched, path):
    response = front.client.get(path, headers=front.headers)
    assert response.status_code == 404
    assert untouched.build.calls == []


@pytest.mark.parametrize("method", ["put", "delete", "patch", "options", "head"])
def test_other_methods_are_refused_with_allow(front, untouched, method):
    response = getattr(front.client, method)(front.path, headers=front.headers)
    assert response.status_code == 405
    assert response.headers["Allow"] == "GET, POST"
    assert untouched.build.calls == []


@pytest.mark.parametrize(
    "headers, query",
    [
        ({}, ""),
        ({"Authorization": ""}, ""),
        ({"Authorization": "Bearer"}, ""),
        ({"Authorization": "Bearer "}, ""),
        ({"Authorization": f"bearer {SECRET}"}, ""),
        ({"Authorization": f"Basic {SECRET}"}, ""),
        ({"Authorization": SECRET}, ""),
        ({"Authorization": f"Bearer {SECRET[:-1]}"}, ""),
        ({"Authorization": f"Bearer {SECRET}x"}, ""),
        ({"Authorization": f"Bearer  {SECRET}"}, ""),
        ({"Authorization": f"Bearer {SECRET.upper()}"}, ""),
        ({}, f"?token={SECRET}"),
        ({}, f"?secret={SECRET}&CRON_SECRET={SECRET}"),
        ({"Cookie": "session=abc; user_id=1; user_type=admin"}, ""),
        ({"X-Authorization": f"Bearer {SECRET}"}, ""),
    ],
)
def test_every_unauthenticated_shape_is_a_401_before_anything_is_built(front, untouched, headers, query):
    for method in ("get", "post"):
        response = getattr(front.client, method)(front.path + query, headers=headers)
        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "Bearer"
        _assert_clean(response)
    assert untouched.build.calls == [] and untouched.run.calls == []


def test_the_comparison_is_constant_time_over_digests(front, monkeypatch):
    seen = []
    real = hmac.compare_digest

    def spy(left, right):
        seen.append((left, right))
        return real(left, right)

    monkeypatch.setattr(scheduler.hmac, "compare_digest", spy)
    front.client.get(front.path, headers={"Authorization": "Bearer wrong"})
    assert seen == [(hashlib.sha256(b"wrong").digest(), hashlib.sha256(SECRET.encode()).digest())]


# --- the job ------------------------------------------------------------------------


@pytest.fixture
def seeded(tmp_path, monkeypatch, front):
    with sqlite_storage_env(tmp_path, monkeypatch) as env:
        monkeypatch.setattr(scheduler, "_build_app", lambda: env.app)
        yield env


def _pending(env, count):
    for index in range(count):
        seed_canonical_request_document(
            env.conn, env.store, key=f"requests/obj-{index:02d}", content=PDF + bytes([index]),
            operation_key=f"sub:slot{index}", filename=f"REQ-0000{index:02d}__Conceito.pdf",
        )
    env.conn.commit()


def _synced(env):
    return env.conn.execute("SELECT count(*) FROM storage_objects WHERE drive_sync_state='synced'").fetchone()[0]


@pytest.mark.parametrize("method", ["get", "post"])
def test_an_authorized_call_runs_one_mirror_pass_and_reports_value_free(front, seeded, method):
    _pending(seeded, 2)
    response = getattr(front.client, method)(front.path, headers=front.headers)
    assert response.status_code == 200
    body = response.get_json()
    assert body["command"] == "mirror" and body["result_code"] == "OK"
    assert body["claimed"] == 2 and body["synced"] == 2
    assert _synced(seeded) == 2
    _assert_clean(response)
    again = getattr(front.client, method)(front.path, headers=front.headers)
    assert again.status_code == 200 and again.get_json()["claimed"] == 0  # nothing due: still a success


def test_the_batch_is_bounded_by_configuration(front, seeded, monkeypatch):
    _pending(seeded, 8)
    assert front.client.post(front.path, headers=front.headers).get_json()["claimed"] == scheduler.DEFAULT_BATCH
    monkeypatch.setenv(scheduler.BATCH_ENV, "2")
    assert front.client.post(front.path, headers=front.headers).get_json()["claimed"] == 2  # 3 left, 2 allowed
    assert _synced(seeded) == scheduler.DEFAULT_BATCH + 2


@pytest.mark.parametrize(
    "raw, expected",
    [("0", 1), ("-4", scheduler.DEFAULT_BATCH), ("abc", scheduler.DEFAULT_BATCH), ("", scheduler.DEFAULT_BATCH),
     ("999", scheduler.MAX_BATCH), ("²", scheduler.DEFAULT_BATCH), ("7", 7)],
)
def test_the_batch_setting_is_clamped_or_defaulted(monkeypatch, raw, expected):
    monkeypatch.setenv(scheduler.BATCH_ENV, raw)
    assert scheduler._bounded_env(scheduler.BATCH_ENV, scheduler.DEFAULT_BATCH, 1, scheduler.MAX_BATCH) == expected


def test_the_lease_is_bounded_and_defaults_safely(front, seeded, monkeypatch):
    captured = []
    real = drive_mirror.run_mirror_pass

    def spy(conn, *, limit, lease_seconds):
        captured.append((limit, lease_seconds))
        return real(conn, limit=limit, lease_seconds=lease_seconds)

    monkeypatch.setattr(drive_mirror, "run_mirror_pass", spy)
    front.client.post(front.path, headers=front.headers)
    assert captured[-1] == (scheduler.DEFAULT_BATCH, scheduler.DEFAULT_LEASE_SECONDS)
    monkeypatch.setenv(scheduler.LEASE_ENV, "1")
    front.client.post(front.path, headers=front.headers)
    # the floor lets every claimed object clear the worker's safety margin, as the CLI's does
    assert captured[-1][1] == 2 * drive_mirror.LEASE_SAFETY_SECONDS
    monkeypatch.setenv(scheduler.LEASE_ENV, "999999")
    front.client.post(front.path, headers=front.headers)
    assert captured[-1][1] == drive_mirror.outbox.MAX_LEASE_SECONDS


def test_an_unavailable_drive_is_a_503_with_the_result_code_and_nothing_is_claimed(front, seeded):
    _pending(seeded, 1)
    seeded.conn.execute("DELETE FROM cloud_accounts")
    seeded.conn.commit()
    response = front.client.post(front.path, headers=front.headers)
    assert response.status_code == 503
    body = response.get_json()
    assert body["result_code"] == "DRIVE_NOT_CONNECTED" and body["claimed"] == 0
    assert _synced(seeded) == 0


def test_a_missing_canonical_store_is_a_503(front, seeded):
    _pending(seeded, 1)
    del seeded.app.extensions["canonical_object_store"]
    response = front.client.post(front.path, headers=front.headers)
    assert response.status_code == 503
    assert response.get_json()["result_code"] == "STORAGE_CONFIG_MISSING"


def test_an_unexpected_failure_is_a_500_with_a_fixed_code_and_no_exception_text(front, monkeypatch, caplog):
    monkeypatch.setattr(scheduler, "_build_app", lambda: __import__("flask").Flask("scheduler-test"))

    def boom(conn, **kwargs):
        raise RuntimeError(f"provider said {SENTINEL} {SECRET}")

    monkeypatch.setattr(drive_mirror, "run_mirror_pass", boom)
    monkeypatch.setattr("app.db.get_db_connection", lambda: object())
    response = front.client.post(front.path, headers=front.headers)
    assert response.status_code == 500
    assert response.get_json() == {"command": "mirror", "result_code": "SCHEDULER_JOB_FAILED"}
    assert SENTINEL not in response.get_data(as_text=True)
    assert SENTINEL not in caplog.text and SECRET not in caplog.text


def test_a_startup_failure_is_a_500_that_is_retried_not_cached(front, monkeypatch):
    attempts = []

    def failing():
        attempts.append(1)
        raise ValueError(f"startup {SENTINEL}")

    monkeypatch.setattr(scheduler, "_build_app", failing)
    for expected in (1, 2):
        response = front.client.post(front.path, headers=front.headers)
        assert response.status_code == 500
        assert response.get_json() == {"command": "mirror", "result_code": "SCHEDULER_STARTUP_FAILED"}
        assert len(attempts) == expected
        assert SENTINEL not in response.get_data(as_text=True)


def test_the_documented_numbers_are_pinned_not_derived():
    """HOSTED_RUNTIME section 9 states these values; a change must be a deliberate edit of both."""
    assert (scheduler.DEFAULT_BATCH, scheduler.MAX_BATCH, scheduler.DEFAULT_LEASE_SECONDS) == (5, 25, 300)
    assert hosting.CRON_SECRET_MIN_LENGTH == 32


@pytest.mark.parametrize("raw", ["9" * 5000, "1" * 10])
def test_an_absurdly_long_numeric_setting_falls_back_instead_of_raising(monkeypatch, raw):
    monkeypatch.setenv(scheduler.BATCH_ENV, raw)
    assert scheduler._bounded_env(scheduler.BATCH_ENV, scheduler.DEFAULT_BATCH, 1, scheduler.MAX_BATCH) == (
        scheduler.DEFAULT_BATCH
    )


def test_the_secret_rule_has_one_owner_for_the_front_and_the_readiness_report(front, untouched, monkeypatch):
    for value, enabled in (
        ("   " + SECRET + "  ", True),            # surrounding whitespace is ignored
        ("s" * 31, False),
        ("é" * 40, False),                          # non-ASCII can never be presented faithfully
    ):
        monkeypatch.setenv("CRON_SECRET", value)
        assert hosting.scheduler_secret_configured() is enabled
        assert (hosting.cron_secret() is not None) is enabled
        status = front.client.get(front.path, headers=front.headers).status_code
        # enabled: the presented SECRET authenticates (it reaches the application build, which the
        # `untouched` spy fails -> 500); disabled: the front does not exist (404)
        assert status == (500 if enabled else 404)


def test_a_header_that_cannot_be_encoded_is_a_401_not_a_server_error(front, untouched):
    """Called as a WSGI server would: a lone surrogate must not escape as an exception."""
    seen = []
    environ = {"PATH_INFO": scheduler.ROUTE_MIRROR, "REQUEST_METHOD": "GET",
               "HTTP_AUTHORIZATION": "Bearer \ud800" + "x" * 40}
    body = scheduler.application(environ, lambda status, headers: seen.append(status))
    assert seen == ["401 Unauthorized"] and body


def test_a_non_ascii_presented_token_is_a_401_not_an_error(front, untouched):
    response = front.client.get(front.path, headers={"Authorization": "Bearer " + "é" * 40})
    assert response.status_code == 401


def test_the_connection_is_closed_on_every_path_and_the_application_is_built_under_a_lock(front, seeded, monkeypatch):
    import threading

    import app.db as app_db

    closed = []
    real_close = app_db.close_db_connection
    monkeypatch.setattr(app_db, "close_db_connection", lambda exc=None: (closed.append(1), real_close(exc))[1])
    assert front.client.post(front.path, headers=front.headers).status_code == 200
    assert closed == [1]
    # a failing pass closes it too
    monkeypatch.setattr(drive_mirror, "run_mirror_pass", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    assert front.client.post(front.path, headers=front.headers).status_code == 500
    assert closed == [1, 1]

    # concurrent first requests build the application exactly once
    monkeypatch.setattr(scheduler, "_app", None)
    builds, gate = [], threading.Event()
    original = scheduler._build_app

    def slow():
        builds.append(1)
        gate.wait(5)
        return original()

    monkeypatch.setattr(scheduler, "_build_app", slow)
    threads = [threading.Thread(target=scheduler._flask_app) for _ in range(4)]
    for thread in threads:
        thread.start()
    gate.set()
    for thread in threads:
        thread.join(10)
    assert builds == [1]


def test_the_application_is_built_once_per_process(front, monkeypatch, seeded):
    builds = []
    original = scheduler._build_app

    def counting():
        builds.append(1)
        return original()

    monkeypatch.setattr(scheduler, "_build_app", counting)
    for _ in range(3):
        assert front.client.get(front.path, headers=front.headers).status_code == 200
    assert builds == [1]


def test_arquivos_objects_are_mirrored_by_the_same_pass(front, seeded):
    seed_canonical_arquivo(seeded.conn, seeded.store, key="arquivos/manual-1", content=PDF + b"A")
    seeded.conn.commit()
    response = front.client.post(front.path, headers=front.headers)
    assert response.status_code == 200 and response.get_json()["synced"] == 1
    assert BUCKET  # the fake bucket the object lives in
