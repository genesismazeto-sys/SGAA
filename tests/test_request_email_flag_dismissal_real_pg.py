"""UI-B47 on real PostgreSQL: dismissing a flag while a decision lands (E-PG1, E-PG2).

The dismissal names the generation the page showed. Whichever transaction
commits first, the waiter re-checks ``estado='pending'`` on the committed row:
a dismissal never clears the newer decision's flag, a decision never loses its
flag to a dismissal, and the partial unique index never trips.
"""
from __future__ import annotations

import datetime
import threading

import pytest

from app.db import _PostgresConnectionAdapter
from app.request_email_notifications import (
    EmailFlagDismissalStale,
    dismiss_pending_events,
    pending_event_ids,
    record_final_decision_event,
)
from tests.storage_mp1_pg_support import PG_URL, Registry, adapter, raw_connection
from tests.storage_mp1_support import REQUEST_ID

pytestmark = pytest.mark.skipif(not PG_URL, reason="SGAA_PG_TEST_URL is required")

WAIT = 10.0


@pytest.fixture(scope="module")
def registry():
    registry = Registry("flag47")
    try:
        registry.provision_template()
        yield registry
    finally:
        assert registry.close() == 0


@pytest.fixture
def url(registry):
    name, database_url = registry.create(template=registry.template)
    try:
        yield database_url
    finally:
        registry.drop(name)


class _CommitGate(_PostgresConnectionAdapter):
    """A canonical adapter whose commit waits: the transaction's locks stay held."""

    def __init__(self, raw, entered: threading.Event, release: threading.Event):
        super().__init__(raw)
        self._entered, self._release = entered, release

    def commit(self):
        self._entered.set()
        assert self._release.wait(WAIT), "the gate was never released"
        return super().commit()


def _stamp(minutes=0):
    return (datetime.datetime(2026, 11, 21, 9, 0) + datetime.timedelta(minutes=minutes)).strftime(
        "%Y-%m-%d %H:%M:%S")


def _decide(conn, status, stamp):
    """The processing handler's decision statements, left uncommitted."""
    conn.execute(
        "UPDATE requisicoes SET status=?, data_processamento=?, admin_id=1 WHERE id=?",
        (status, stamp, REQUEST_ID),
    )
    return record_final_decision_event(conn, requisicao_id=REQUEST_ID, decided_at=stamp)


def _flagged(url):
    conn = adapter(url)
    try:
        event = _decide(conn, "Deferida", _stamp())
        conn.commit()
        return event
    finally:
        conn.close()


def _state(url):
    conn = adapter(url)
    try:
        rows = conn.execute(
            "SELECT id, estado FROM requisicao_email_eventos WHERE requisicao_id=? ORDER BY id",
            (REQUEST_ID,),
        ).fetchall()
        return [(int(row["id"]), row["estado"]) for row in rows], pending_event_ids(conn)
    finally:
        conn.close()


def _waiting_on_a_lock(url, pid):
    probe = raw_connection(url, autocommit=True)
    try:
        row = probe.execute("SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s", (pid,)).fetchone()
        return row is not None and row[0] == "Lock"
    finally:
        probe.close()


def _until(predicate, timeout=WAIT):
    deadline = threading.Event()
    timer = threading.Timer(timeout, deadline.set)
    timer.start()
    try:
        while not deadline.is_set():
            if predicate():
                return True
            deadline.wait(0.05)
        return False
    finally:
        timer.cancel()


def _run(target):
    outcome = {}

    def body():
        try:
            outcome["value"] = target()
        except BaseException as exc:  # handed to the main thread
            outcome["error"] = exc

    thread = threading.Thread(target=body, daemon=True)
    thread.start()
    return thread, outcome


def test_epg1_dismissal_then_a_new_decision(url):
    event = _flagged(url)
    conn = adapter(url)
    try:
        assert dismiss_pending_events(conn, {REQUEST_ID: event}) == 1
        assert _state(url) == ([(event, "superseded")], {})
        with pytest.raises(EmailFlagDismissalStale):
            dismiss_pending_events(conn, {REQUEST_ID: event})
        newer = _decide(conn, "Indeferida", _stamp(5))
        conn.commit()
    finally:
        conn.close()
    assert _state(url) == ([(event, "superseded"), (newer, "pending")], {REQUEST_ID: newer})


def test_epg2_a_dismissal_waiting_on_a_new_decision_is_refused_as_stale(url):
    event = _flagged(url)
    decision = adapter(url)
    dismissal = adapter(url)
    try:
        newer = _decide(decision, "Indeferida", _stamp(5))       # holds the old generation's row
        pid = dismissal.raw_connection.info.backend_pid
        thread, outcome = _run(lambda: dismiss_pending_events(dismissal, {REQUEST_ID: event}))
        assert _until(lambda: _waiting_on_a_lock(url, pid)), "the dismissal did not wait for the decision"
        decision.commit()
        thread.join(WAIT)
        assert not thread.is_alive()
        assert isinstance(outcome.get("error"), EmailFlagDismissalStale), outcome
        assert outcome["error"].requisicao_ids == [REQUEST_ID]
    finally:
        decision.close()
        dismissal.close()
    assert _state(url) == ([(event, "superseded"), (newer, "pending")], {REQUEST_ID: newer})


def test_epg2_a_decision_waiting_on_a_dismissal_raises_its_own_flag(url):
    event = _flagged(url)
    entered, release = threading.Event(), threading.Event()
    gated_raw = raw_connection(url)
    dismissal = _CommitGate(gated_raw, entered, release)
    decision = adapter(url)
    try:
        dismissing, dismissed = _run(lambda: dismiss_pending_events(dismissal, {REQUEST_ID: event}))
        assert entered.wait(WAIT), "the dismissal never reached its commit"
        pid = decision.raw_connection.info.backend_pid

        def decide():
            newer = _decide(decision, "Deferida Parcialmente", _stamp(5))
            decision.commit()
            return newer

        deciding, decided = _run(decide)
        assert _until(lambda: _waiting_on_a_lock(url, pid)), "the decision did not wait for the dismissal"
        release.set()
        dismissing.join(WAIT)
        deciding.join(WAIT)
        assert not dismissing.is_alive() and not deciding.is_alive()
        assert dismissed == {"value": 1}, dismissed
        assert "error" not in decided, decided
        newer = decided["value"]
    finally:
        release.set()
        dismissal.close()
        decision.close()
    assert newer != event
    assert _state(url) == ([(event, "superseded"), (newer, "pending")], {REQUEST_ID: newer})
