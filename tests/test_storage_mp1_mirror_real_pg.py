# coding: utf-8
"""MP-1 slice 1 on real PostgreSQL (opt-in, ``SGAA_PG_TEST_URL``): the Drive mirror worker.

Without ``SGAA_PG_TEST_URL`` the module skips (REAL-PG EVIDENCE: ABSENT).

E-PG1: one pass through the runtime adapter -- owner lookup, request
placement (including the one-time turma-snapshot freeze), canonical read,
fenced completion, worker health, retry bookkeeping and operator requeue run
the SQL PostgreSQL runs.

Provider calls run with NO transaction open (the connection is IDLE at every
canonical read and every Drive call, for request and ARQUIVOS objects alike):
an upload never holds a lock or a snapshot.

E-PG2: concurrent workers on separate connections never mirror one object
twice (``FOR UPDATE SKIP LOCKED`` claims + the lease fence), never deadlock,
and a stale worker whose lease was reclaimed cannot complete; an operator
requeue never waits on, nor touches, objects a claim holds; concurrent
requeues requeue each object exactly once; a worker that dies after its Drive
write is resumed by adoption.
"""

from __future__ import annotations

import threading

import pytest
from flask import Flask

from tests.storage_mp1_pg_support import PG_URL

pytestmark = pytest.mark.skipif(
    not PG_URL, reason="SGAA_PG_TEST_URL is not configured -- REAL-PG EVIDENCE: ABSENT"
)

psycopg = pytest.importorskip("psycopg")

from app.db import connection_transaction_status, write_transaction  # noqa: E402
from app.storage import custody_common  # noqa: E402
from app.storage import drive_mirror  # noqa: E402
from app.storage import mirror_outbox as outbox  # noqa: E402
from app.storage.contracts import StorageTransientError  # noqa: E402
from tests.canonical_store_fake import InMemoryObjectStore  # noqa: E402
from tests.storage_mp1_pg_support import Registry, adapter  # noqa: E402
from tests.storage_mp1_support import (  # noqa: E402
    ACCOUNT_KEY,
    T0,
    Clock,
    FakeDrive,
    object_state,
    request_snapshot,
    seed_canonical_arquivo,
    seed_canonical_request_document,
)
from tests.storage_s3a_support import PDF, PNG  # noqa: E402

JOIN_TIMEOUT_SECONDS = 60


@pytest.fixture(scope="module")
def registry():
    registry = Registry("mirror")
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
    conn = adapter(url)
    opened = [conn]

    def connect():
        extra = adapter(url)
        opened.append(extra)
        return extra

    try:
        with flask_app.app_context():
            yield dict(app=flask_app, conn=conn, store=store, drive=drive, clock=clock, connect=connect)
    finally:
        for item in opened:
            item.close()
        registry.drop(name)


def _seed_requests(env, count):
    ids = []
    for index in range(count):
        ids.append(seed_canonical_request_document(
            env["conn"], env["store"], key=f"comprovantes/2026/10/{index:032d}",
            content=PDF + index.to_bytes(2, "big"), operation_key=f"pg-op-{index}",
        )[1])
    env["conn"].commit()
    return ids


# --- E-PG1 ---------------------------------------------------------------------------


def test_pass_mirrors_through_the_runtime_adapter(env):
    conn = env["conn"]
    conn.execute("DELETE FROM requisicoes WHERE id=1")
    conn.execute(
        "INSERT INTO requisicoes(id,aluno_id,atividade_versao_id,data_solicitacao,data_evento,horas_solicitadas,"
        "status,regra_snapshot_json) VALUES(1,1,1,'2026-09-05','2026-09-05',2,'Pendente',?)",
        (request_snapshot(),),
    )
    _req, req_obj = seed_canonical_request_document(conn, env["store"], key="comprovantes/2026/10/" + "a" * 32,
                                                    content=PDF)
    _arq, arq_obj = seed_canonical_arquivo(conn, env["store"], key="arquivos/2026/10/" + "b" * 32, content=PNG,
                                           mime="image/png")
    conn.commit()

    result = drive_mirror.run_mirror_pass(conn)

    assert (result.result_code, result.claimed, result.synced) == ("OK", 2, 2)
    for object_id in (req_obj, arq_obj):
        state = object_state(conn, object_id)
        assert (state["state"], state["account_key"], state["lease"]) == ("synced", ACCOUNT_KEY, None)
    assert tuple(conn.execute(
        "SELECT turma_id_snapshot,turma_codigo_snapshot FROM requisicoes WHERE id=1").fetchone()) == (1, "T-2026-1")
    status = outbox.read_worker_status(conn)
    assert (status["last_result_code"], status["last_synced_count"]) == ("OK", 2)
    conn.commit()


def test_retry_exhaustion_and_requeue_on_postgres(env):
    conn = env["conn"]
    (object_id,) = _seed_requests(env, 1)
    conn.execute("UPDATE storage_objects SET drive_attempts=? WHERE id=?", (drive_mirror.MAX_ATTEMPTS - 1, object_id))
    conn.commit()
    env["drive"].fail_next("upload", StorageTransientError("busy"))

    drive_mirror.run_mirror_pass(conn)
    state = object_state(conn, object_id)
    assert (state["state"], state["error"]) == ("reconciliation_required", "MIRROR_RETRY_EXHAUSTED")
    conn.commit()

    with write_transaction(conn):
        assert outbox.requeue_for_mirror(conn, now=T0, limit=5, error_code="MIRROR_RETRY_EXHAUSTED") == 1
    assert drive_mirror.run_mirror_pass(conn).synced == 1
    conn.commit()


# --- E-PG2 ---------------------------------------------------------------------------


def _in_context(env, target):
    def run():
        with env["app"].app_context():
            target()

    return run


def test_concurrent_workers_never_mirror_an_object_twice(env):
    ids = _seed_requests(env, 12)
    results, errors = [], []
    barrier = threading.Barrier(3)

    def worker():
        conn = env["connect"]()
        try:
            barrier.wait(timeout=JOIN_TIMEOUT_SECONDS)
            for _ in range(6):
                results.append(drive_mirror.run_mirror_pass(conn, limit=3))
                conn.commit()
        except Exception as exc:  # recorded and asserted below
            errors.append(exc)

    threads = [threading.Thread(target=_in_context(env, worker)) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(JOIN_TIMEOUT_SECONDS)
    assert not any(thread.is_alive() for thread in threads), "a worker is stuck (deadlock or wait)"
    assert errors == []
    assert sum(result.synced for result in results) == 12
    assert sum(result.lost for result in results) == 0
    assert len(env["drive"].files) == 12
    assert env["drive"].calls.count("upload") == 12
    conn = env["conn"]
    assert {object_state(conn, object_id)["state"] for object_id in ids} == {"synced"}
    assert {object_state(conn, object_id)["attempts"] for object_id in ids} == {1}
    conn.commit()


def test_stale_worker_is_fenced_after_a_rival_reclaims(env):
    (object_id,) = _seed_requests(env, 1)
    drive = env["drive"]
    original_upload = drive.upload
    rival = {}

    def slow_upload(**payload):
        remote = original_upload(**payload)
        env["clock"].advance(outbox.DEFAULT_LEASE_SECONDS + 1)
        drive.upload = original_upload
        other = env["connect"]()
        rival["result"] = drive_mirror.run_mirror_pass(other)
        other.commit()
        return remote

    drive.upload = slow_upload
    first = drive_mirror.run_mirror_pass(env["conn"])

    assert (first.lost, first.synced) == (1, 0)
    assert (rival["result"].released, rival["result"].synced) == (1, 1)
    assert len(drive.files) == 1
    assert object_state(env["conn"], object_id)["state"] == "synced"
    env["conn"].commit()


def test_concurrent_requeues_requeue_each_object_once(env):
    ids = _seed_requests(env, 8)
    conn = env["conn"]
    conn.execute(
        "UPDATE storage_objects SET drive_sync_state='reconciliation_required',"
        "drive_last_error_code='MIRROR_RETRY_EXHAUSTED' WHERE id = ANY(?)", (ids,))
    conn.commit()
    counts, errors = [], []
    barrier = threading.Barrier(2)

    def requeue():
        other = env["connect"]()
        try:
            barrier.wait(timeout=JOIN_TIMEOUT_SECONDS)
            with write_transaction(other):
                counts.append(outbox.requeue_for_mirror(other, now=T0, limit=100))
        except Exception as exc:  # recorded and asserted below
            errors.append(exc)

    threads = [threading.Thread(target=requeue) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(JOIN_TIMEOUT_SECONDS)
    assert errors == [] and sum(counts) == 8
    assert {object_state(conn, object_id)["state"] for object_id in ids} == {"pending"}
    conn.commit()


def test_no_transaction_is_open_during_any_provider_call(env):
    conn = env["conn"]
    seed_canonical_request_document(conn, env["store"], key="comprovantes/2026/10/" + "c" * 32, content=PDF)
    seed_canonical_arquivo(conn, env["store"], key="arquivos/2026/10/" + "d" * 32, content=PNG, mime="image/png")
    conn.commit()
    observed = []

    def spy(owner, name):
        original = getattr(owner, name)

        def call(*args, **kwargs):
            observed.append((name, connection_transaction_status(conn)))
            return original(*args, **kwargs)

        setattr(owner, name, call)

    for name in ("stat", "read"):
        spy(env["store"], name)
    for name in ("ensure_folder", "upload"):
        spy(env["drive"], name)

    assert drive_mirror.run_mirror_pass(conn).synced == 2
    assert {name for name, _status in observed} == {"stat", "read", "ensure_folder", "upload"}
    assert {status for _name, status in observed} == {"IDLE"}, observed
    conn.commit()


def test_requeue_never_waits_on_nor_touches_claimed_objects(env):
    conn = env["conn"]
    pending = _seed_requests(env, 4)
    stuck = [seed_canonical_request_document(
        conn, env["store"], key=f"comprovantes/2026/11/{index:032d}", content=PNG + bytes([index]),
        mime="image/png", operation_key=f"stuck-{index}")[1] for index in range(3)]
    conn.execute("UPDATE storage_objects SET drive_sync_state='reconciliation_required',"
                 "drive_last_error_code='MIRROR_RETRY_EXHAUSTED',drive_attempts=10 WHERE id = ANY(?)", (stuck,))
    conn.commit()
    claimer = env["connect"]()
    result, errors = {}, []
    with write_transaction(claimer):
        claimed = outbox.claim_due_mirror_work(claimer, limit=10, worker_token="e" * 32, now=T0)
        assert sorted(work.object_id for work in claimed) == sorted(pending)

        def requeue():
            other = env["connect"]()
            try:
                with write_transaction(other):
                    result["count"] = outbox.requeue_for_mirror(other, now=T0, limit=100)
            except Exception as exc:  # recorded and asserted below
                errors.append(exc)

        # The claim's row locks are held (uncommitted) while the requeue runs.
        thread = threading.Thread(target=requeue)
        thread.start()
        thread.join(JOIN_TIMEOUT_SECONDS)
        assert not thread.is_alive(), "the requeue waited on rows a claim holds"
    assert errors == [] and result["count"] == 3
    states = {object_id: object_state(conn, object_id) for object_id in pending + stuck}
    assert {states[i]["state"] for i in pending} == {"syncing"}
    assert {(states[i]["state"], states[i]["attempts"]) for i in stuck} == {("pending", 0)}
    conn.commit()
    # Committed leases are never requeued either.
    with write_transaction(conn):
        assert outbox.requeue_for_mirror(conn, now=T0, limit=100) == 0
    assert {object_state(conn, i)["state"] for i in pending} == {"syncing"}
    conn.commit()


class _Death(BaseException):
    pass


def test_death_after_the_drive_write_is_resumed_by_adoption(env, monkeypatch):
    conn = env["conn"]
    (object_id,) = _seed_requests(env, 1)
    real_complete = outbox.complete_synced

    def die(*_args, **_kwargs):
        raise _Death()

    monkeypatch.setattr(outbox, "complete_synced", die)
    with pytest.raises(_Death):
        drive_mirror.run_mirror_pass(conn)
    conn.rollback()
    assert object_state(conn, object_id)["state"] == "syncing"
    assert outbox.read_worker_status(conn)["last_finished_at"] is None
    monkeypatch.setattr(outbox, "complete_synced", real_complete)
    env["clock"].advance(outbox.DEFAULT_LEASE_SECONDS + 1)

    result = drive_mirror.run_mirror_pass(conn)

    assert (result.released, result.synced) == (1, 1)
    assert len(env["drive"].files) == 1 and env["drive"].calls.count("upload") == 2
    assert object_state(conn, object_id)["state"] == "synced"
    conn.commit()
