# coding: utf-8
"""STORAGE S3-B M1 RED extension on real PostgreSQL (opt-in, ``SGAA_PG_TEST_URL``).

Material review finding M1: a legacy ARQUIVOS row can be the target of a LIVE
S3-B replacement intent, so a legacy delete must be gated exactly like a
canonical delete, and the gate must serialize against a concurrent issue.

    PG-L1  a live (issued / verified) replacement intent committed against a
           legacy Google target BEFORE the delete: the delete is refused; the
           row, the intent and the provider-object tracking survive; Drive is
           never reached.
    PG-L2  issue vs legacy delete, interleaved at three points.  Exactly one
           safe serialization must result:
             A. the issue wins: its live intent exists and the delete refuses;
             B. the delete wins: the row is gone and the issue was refused.
           Forbidden: a successful delete AND a successful issue (a live intent
           whose target vanished / cascaded), lost tracking, a deadlock.

Interleaving seams (the published S2 / S3-B surfaces, never a SQL sequence):
``app.storage.upload_intents.issue_intent`` (every issue goes through it),
``app.storage.arquivo_documents.is_replaceable`` (the issue's target check) and
the legacy Drive ``trash`` call (reached only after the legacy delete committed
its deletion state).  The disposable database comes from the frozen S3-B
real-PG module's fixture (its own run-owned database for this module).
"""

from __future__ import annotations

import os
import secrets
import threading
import time

import pytest

PG_URL = os.environ.get("SGAA_PG_TEST_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not PG_URL, reason="SGAA_PG_TEST_URL is not configured -- REAL-PG EVIDENCE: ABSENT"
)

pytest.importorskip("psycopg")

import app.arquivos as arquivos  # noqa: E402
from app import db as app_db  # noqa: E402
from app.storage import arquivo_documents  # noqa: E402
from app.storage import upload_intents as intents  # noqa: E402
from tests.storage_s3a_support import ISSUE_URL, PNG, declaration  # noqa: E402
from tests.storage_s3b_support import DELETE_URL, PURPOSE, TARGET_FIELD, seed_google_arquivo  # noqa: E402
from tests.test_arquivos_google_drive import FakeManagedStorage  # noqa: E402
from tests.test_storage_s3b_real_pg import (  # noqa: E402,F401 - ``env`` is a fixture
    JOIN_TIMEOUT_SECONDS,
    SLOTS,
    T0,
    _arquivo,
    _client,
    _observe,
    _one,
    _start,
    _submission,
    _upload,
    env,
)


def _seed_google(env) -> tuple[int, str]:
    remote = f"drv-m1-{secrets.token_hex(6)}"
    conn = app_db._connect_postgres()
    try:
        row_id = seed_google_arquivo(conn, uploader=env.admin_id, now=T0, remote_file_id=remote,
                                     operation_key=f"seed-m1-{secrets.token_hex(6)}", titulo=f"PG M1 {remote}")
        conn.commit()
    finally:
        conn.close()
    return row_id, remote


def _issue_payload(submission, slot, row_id):
    return {"purpose": PURPOSE, "submission_id": submission, "upload_slot_id": slot, TARGET_FIELD: row_id,
            **declaration(PNG, "novo.png", "image/png")}


def _row_intents(env, row_id):
    return _observe(env, "SELECT id, state, storage_key FROM storage_upload_intents WHERE admin_arquivo_id=%s",
                    (row_id,))


def _submission_intents(env, submission):
    return _observe(env, "SELECT id, state, admin_arquivo_id FROM storage_upload_intents WHERE operation_id LIKE %s",
                    (f"{submission}:%",))


def _lock_waiting(env) -> bool:
    return bool(_one(env, "SELECT count(*) FROM pg_stat_activity WHERE datname=%s AND wait_event_type='Lock'",
                     (env.database,))[0])


def _settle(env, thread, event, seconds=10.0):
    """Wait until the competitor reached ``event``, blocks on a lock, or finished."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and thread.is_alive() and not event.is_set():
        if _lock_waiting(env):
            return
        time.sleep(0.05)


def _answer(label, outcome):
    value = outcome.get("value")
    assert value is not None and not isinstance(value, Exception), (label, value)
    assert value.status_code != 500, (label, value.status_code)
    return value


class _Hold:
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()

    def hold(self):
        self.entered.set()
        self.release.wait(JOIN_TIMEOUT_SECONDS)


@pytest.fixture
def drive(monkeypatch):
    """A legacy Drive whose ``trash`` can be held (the delete already committed its deletion state)."""
    fake = FakeManagedStorage()
    gate = _Hold()
    gate.active = False

    def on_trash(_file_id):
        if gate.active:
            gate.hold()

    fake.on_trash = on_trash
    fake.gate = gate
    # The module env tripwires the legacy resolver itself; legacy delete is legacy
    # (Drive) behavior, so this test routes it to the gated fake instead.
    monkeypatch.setattr(arquivos, "resolve_arquivo_storage", lambda _conn: fake)
    return fake


# ---------------------------------------------------------------------------
# PG-L1
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("state", ("issued", "verified"))
def test_pg_L1_a_committed_live_intent_on_a_legacy_target_refuses_the_delete(env, state):
    row_id, _remote = _seed_google(env)
    client = _client(env)
    submission = _submission(client, row_id)
    if state == "verified":
        intent_id = _upload(env, client, submission, SLOTS[0], target=row_id)
    else:
        issued = client.post(ISSUE_URL, json=_issue_payload(submission, SLOTS[0], row_id))
        assert issued.status_code in (200, 201), (issued.status_code, issued.get_json(silent=True))
        intent_id = issued.get_json()["intent_id"]
    before_row = _arquivo(env, row_id)
    before_intents = _row_intents(env, row_id)
    assert [(i, s) for (i, s, _k) in before_intents] == [(intent_id, state)]
    calls_before = list(env.google_calls)

    response = _client(env).post(DELETE_URL.format(id=row_id))

    assert response.status_code == 302, response.status_code
    assert _arquivo(env, row_id) == before_row, "the legacy row changed under a live replacement intent"
    assert _row_intents(env, row_id) == before_intents, "live intent tracking was lost"
    if state == "verified":
        key = before_intents[0][2]
        assert any(k == key for (_b, k) in env.store.objects), "the uploaded bytes are not where tracking says"
    assert env.google_calls == calls_before, "Drive was reached under a live replacement intent"


# ---------------------------------------------------------------------------
# PG-L2
# ---------------------------------------------------------------------------


def _hold_issue_after_target_check(monkeypatch, gate):
    original = arquivo_documents.is_replaceable
    first = [True]

    def gated(row):
        result = original(row)
        if first[0]:
            first[0] = False
            gate.hold()
        return result

    monkeypatch.setattr(arquivo_documents, "is_replaceable", gated)


def _hold_issue_after_insert(monkeypatch, gate):
    original = intents.issue_intent

    def gated(*args, **kwargs):
        result = original(*args, **kwargs)
        gate.hold()
        return result

    monkeypatch.setattr(intents, "issue_intent", gated)


@pytest.mark.parametrize("interleaving", ("issue-checked-target", "issue-inserted-intent", "delete-transitioned-first"))
def test_pg_L2_issue_versus_legacy_delete_serializes_safely(env, monkeypatch, drive, interleaving):
    row_id, remote = _seed_google(env)
    issuer, deleter = _client(env), _client(env)
    submission = _submission(issuer, row_id)
    payload = _issue_payload(submission, SLOTS[1], row_id)
    issue_gate = _Hold()

    if interleaving == "delete-transitioned-first":
        drive.gate.active = True
        delete_thread, delete_outcome = _start(lambda: deleter.post(DELETE_URL.format(id=row_id)))
        assert drive.gate.entered.wait(JOIN_TIMEOUT_SECONDS), "the legacy delete never reached its Drive cleanup"
        issue_thread, issue_outcome = _start(lambda: issuer.post(ISSUE_URL, json=payload))
        issue_thread.join(JOIN_TIMEOUT_SECONDS)
        assert _submission_intents(env, submission) == [], "an intent was issued against a row being deleted"
        drive.gate.release.set()
        delete_thread.join(JOIN_TIMEOUT_SECONDS)
    else:
        if interleaving == "issue-checked-target":
            _hold_issue_after_target_check(monkeypatch, issue_gate)
        else:
            _hold_issue_after_insert(monkeypatch, issue_gate)
        drive.gate.active = True
        issue_thread, issue_outcome = _start(lambda: issuer.post(ISSUE_URL, json=payload))
        assert issue_gate.entered.wait(JOIN_TIMEOUT_SECONDS), "the issue never reached its interleaving point"
        delete_thread, delete_outcome = _start(lambda: deleter.post(DELETE_URL.format(id=row_id)))
        _settle(env, delete_thread, drive.gate.entered)
        issue_gate.release.set()
        issue_thread.join(JOIN_TIMEOUT_SECONDS)
        drive.gate.release.set()
        delete_thread.join(JOIN_TIMEOUT_SECONDS)

    assert not issue_thread.is_alive() and not delete_thread.is_alive(), "deadlock or hang"
    issued = _answer("issue", issue_outcome)
    deleted = _answer("delete", delete_outcome)
    assert deleted.status_code == 302, deleted.status_code
    row = _arquivo(env, row_id)
    issue_won = issued.status_code in (200, 201)

    if row is None:
        # B. the delete won: the issue must have been refused -- never a minted capability
        # for a live intent whose target vanished through the FK cascade.
        assert not issue_won, f"successful delete AND successful issue ({issued.status_code})"
        assert 400 <= issued.status_code < 500, issued.status_code
        assert _submission_intents(env, submission) == []
        assert drive.trashed == [remote]
    else:
        # A. the issue won: its live intent is tracked and the delete refused.
        assert issue_won, f"the delete was refused but the issue failed too ({issued.status_code})"
        intent_id = issued.get_json()["intent_id"]
        assert [(i, s) for (i, s, _k) in _row_intents(env, row_id)] == [(intent_id, "issued")]
        assert (row["provider"], row["storage_status"], row["remote_file_id"]) == ("google", "active", remote)
        assert row["cleanup_started_at"] is None
        assert drive.trashed == [], "Drive was trashed while a live replacement intent exists"
