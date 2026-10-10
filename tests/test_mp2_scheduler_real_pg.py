# coding: utf-8
"""MP-2 slice 4 on real PostgreSQL (opt-in, ``SGAA_PG_TEST_URL``): the scheduler front under overlap.

Without ``SGAA_PG_TEST_URL`` the module skips (REAL-PG EVIDENCE: ABSENT).

Platform cron delivery is at-least-once and may overlap.  E-PG2 drives the
front itself (``app.storage.scheduler.application``) -- not only the worker --
with concurrent authorized invocations on separate connections to one database:

* overlapping invocations mirror every object exactly once (``FOR UPDATE SKIP
  LOCKED`` claims + the lease fence): no duplicate Drive write, no deadlock, no
  failed response;
* an invocation never takes an object a live lease holds, and reclaims it only
  once that lease has expired.

The canonical store and the Drive are in-memory doubles; the database is real.
"""

from __future__ import annotations

import secrets
import threading

import pytest
from flask import Flask
from werkzeug.test import Client

from tests.storage_mp1_pg_support import PG_URL

pytestmark = pytest.mark.skipif(
    not PG_URL, reason="SGAA_PG_TEST_URL is not configured -- REAL-PG EVIDENCE: ABSENT"
)

psycopg = pytest.importorskip("psycopg")

import app.db as app_db  # noqa: E402
from app.db import write_transaction  # noqa: E402
from app.storage import custody_common, drive_mirror, scheduler  # noqa: E402
from app.storage import mirror_outbox as outbox  # noqa: E402
from tests.canonical_store_fake import InMemoryObjectStore  # noqa: E402
from tests.storage_mp1_pg_support import Registry, adapter  # noqa: E402
from tests.storage_mp1_support import (  # noqa: E402
    T0,
    Clock,
    FakeDrive,
    object_state,
    seed_canonical_request_document,
)
from tests.storage_s3a_support import PDF  # noqa: E402

JOIN_TIMEOUT_SECONDS = 90
SECRET = "p" * 40


@pytest.fixture(scope="module")
def registry():
    registry = Registry("sched")
    try:
        registry.provision_template()
        yield registry
    finally:
        assert registry.close() == 0


@pytest.fixture
def env(registry, monkeypatch):
    name, url = registry.create(template=registry.template)
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    store = InMemoryObjectStore()
    drive = FakeDrive()
    flask_app.extensions["canonical_object_store"] = store
    flask_app.extensions[drive_mirror.DRIVE_STORAGE_EXTENSION] = drive
    clock = Clock(T0)
    monkeypatch.setattr(custody_common, "utc_now_text", clock)
    # The front reaches the database exactly as a hosted function does: through
    # ``app.db.get_db_connection`` against the configured PostgreSQL URL.
    monkeypatch.setattr(app_db, "DATABASE_URL", url)
    monkeypatch.setenv("CRON_SECRET", SECRET)
    for variable in (scheduler.BATCH_ENV, scheduler.LEASE_ENV):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setattr(scheduler, "_app", None)
    monkeypatch.setattr(scheduler, "_build_app", lambda: flask_app)
    conn = adapter(url)
    try:
        with flask_app.app_context():
            yield dict(app=flask_app, conn=conn, store=store, drive=drive, clock=clock, url=url)
    finally:
        conn.close()
        registry.drop(name)


def _seed(env, count):
    ids = []
    for index in range(count):
        ids.append(seed_canonical_request_document(
            env["conn"], env["store"], key=f"comprovantes/2026/10/{index:032d}",
            content=PDF + index.to_bytes(2, "big"), operation_key=f"sched-op-{index}",
        )[1])
    env["conn"].commit()
    return ids


def _call():
    return Client(scheduler.application).post(
        scheduler.ROUTE_MIRROR, headers={"Authorization": f"Bearer {SECRET}"}
    )


def test_overlapping_invocations_mirror_each_object_exactly_once(env):
    ids = _seed(env, 12)
    statuses, bodies, errors = [], [], []
    barrier = threading.Barrier(3)

    def invoker():
        try:
            barrier.wait(timeout=JOIN_TIMEOUT_SECONDS)
            for _ in range(5):
                response = _call()
                statuses.append(response.status_code)
                bodies.append(response.get_json())
        except Exception as exc:  # recorded and asserted below
            errors.append(exc)

    threads = [threading.Thread(target=invoker) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(JOIN_TIMEOUT_SECONDS)

    assert not any(thread.is_alive() for thread in threads), "an invocation is stuck (deadlock or wait)"
    assert errors == []
    assert statuses and set(statuses) == {200}, statuses
    # 15 overlapping invocations of at most 5 objects each cover 12 objects exactly once.
    assert sum(body["synced"] for body in bodies) == 12
    assert sum(body["lost"] for body in bodies) == 0
    assert env["drive"].calls.count("upload") == 12 and len(env["drive"].files) == 12
    conn = env["conn"]
    assert {object_state(conn, object_id)["state"] for object_id in ids} == {"synced"}
    assert {object_state(conn, object_id)["attempts"] for object_id in ids} == {1}
    conn.commit()


def test_an_invocation_respects_a_live_lease_and_reclaims_only_after_expiry(env):
    (object_id,) = _seed(env, 1)
    rival = adapter(env["url"])
    try:
        with write_transaction(rival):
            claimed = outbox.claim_due_mirror_work(
                rival, limit=1, worker_token=secrets.token_hex(16), now=T0,
                lease_seconds=outbox.DEFAULT_LEASE_SECONDS,
            )
        assert [work.object_id for work in claimed] == [object_id]
        rival.commit()
    finally:
        rival.close()

    held = _call()
    assert held.status_code == 200
    assert held.get_json()["claimed"] == 0 and held.get_json()["synced"] == 0
    assert env["drive"].calls.count("upload") == 0
    state = object_state(env["conn"], object_id)
    assert state["state"] == "syncing" and state["lease"] is not None
    env["conn"].commit()

    env["clock"].advance(outbox.DEFAULT_LEASE_SECONDS + 1)
    reclaimed = _call()
    assert reclaimed.status_code == 200
    body = reclaimed.get_json()
    assert (body["released"], body["synced"]) == (1, 1)
    assert env["drive"].calls.count("upload") == 1
    assert object_state(env["conn"], object_id)["state"] == "synced"
    env["conn"].commit()
