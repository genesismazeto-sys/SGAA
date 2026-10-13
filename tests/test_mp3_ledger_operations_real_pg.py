# coding: utf-8
"""MP-3 SPEC A19 (14) R2 on real PostgreSQL: the ledger's own PROD transactions and their markers.

The ledger cannot commit a file and a database transaction atomically, so each act's PROD transaction
records the act's entry hash in ``sgaa_cutover.operations`` and ``reconcile`` reads it back.  These lanes
prove, on a real server and across two connections (E-PG1/E-PG2): the marker commits with the act's
writes or not at all; a COMMIT whose answer is lost is reported as uncertain, never as aborted; and the
reader waits for an act's transaction that is still open instead of reading it as not committed.
Each test names the defect it would catch.  They need ``SGAA_PG_TEST_URL`` (REAL-PG EVIDENCE: ABSENT
otherwise).
"""

from __future__ import annotations

import contextlib
import threading
import time

import pytest

from app import hosting
from tests.mp2_pg_support import PG_URL
from tools import cutover_ledger as ledger

real_pg = pytest.mark.skipif(not PG_URL, reason="SGAA_PG_TEST_URL is not configured -- REAL-PG EVIDENCE: ABSENT")
REFERENCE = "5" * 64


@pytest.fixture
def database():
    from tests.storage_mp1_pg_support import Registry

    registry = Registry("ledgerops")
    try:
        yield registry.create()[1]
    finally:
        assert registry.close() == 0


def _observer(url, *, wrap=None, read_only=False):
    from tests.mp3_ledger_support import local_connector

    connect = local_connector(url)

    def connector(u):
        conn = connect(u)
        if read_only:  # what a session of the writers' role gets under the write barrier
            conn.execute("SET default_transaction_read_only = on")
        return wrap(conn) if wrap else conn

    return ledger.Observer(source_connector=connector)


class _LostAnswer:
    """TEST ONLY: a connection whose COMMIT reaches the server but whose answer is lost."""

    def __init__(self, real):
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "_transactions", 0)

    def __getattr__(self, name):
        return getattr(self._real, name)

    def __setattr__(self, name, value):
        setattr(self._real, name, value)

    def transaction(self):
        import psycopg

        real = self._real
        object.__setattr__(self, "_transactions", self._transactions + 1)
        if self._transactions == 1:  # the tables, committed before the act: answered normally
            return real.transaction()

        @contextlib.contextmanager
        def lossy():
            with real.transaction():
                yield
            raise psycopg.OperationalError("server closed the connection unexpectedly")

        return lossy()


def _rows(url):
    import psycopg

    with psycopg.connect(url, autocommit=True) as conn:
        operations = [r[0] for r in conn.execute("SELECT entry_hash FROM sgaa_cutover.operations").fetchall()]
        opening = conn.execute("SELECT code_sha256, revoked_at IS NULL FROM sgaa_cutover.opening"
                               " ORDER BY code_sha256").fetchall()
    return operations, opening


@real_pg
def test_real_pg_an_acts_marker_commits_with_its_writes_or_not_at_all(database):
    observer = _observer(database)
    first = {"hash": "a" * 64, "type": "reference"}
    observer.authorize(REFERENCE, "7" * 64, first, first=True)
    assert observer.operation_committed(first["hash"]) is True
    refused = {"hash": "b" * 64, "type": "reference"}
    with pytest.raises(ledger.Refused) as caught:  # refused inside the transaction: nothing commits
        observer.authorize(REFERENCE, "9" * 64, refused, first=True)
    assert caught.value.code == "OPENING_AUTHORIZATION_EXISTS"
    assert observer.operation_committed(refused["hash"]) is False
    assert _rows(database) == (["a" * 64], [("7" * 64, True)])
    later = {"hash": "c" * 64, "type": "authorization"}
    observer.authorize(REFERENCE, "9" * 64, later, first=False)  # replaces every other code, with its marker
    assert _rows(database) == (["a" * 64, "c" * 64], [("7" * 64, False), ("9" * 64, True)])
    narrowing = {"hash": "d" * 64, "type": "supersession"}
    assert observer.supersede(REFERENCE, None, narrowing) == 1
    assert observer.operation_committed(narrowing["hash"]) is True


@real_pg
def test_real_pg_a_lost_commit_answer_is_uncertain_and_reconciled_as_committed(database):
    """R2: the COMMIT reached PostgreSQL but its answer was lost: never read as aborted."""
    lossy = _observer(database, wrap=_LostAnswer)
    entry = {"hash": "e" * 64, "type": "supersession"}
    _observer(database).authorize(REFERENCE, "7" * 64, {"hash": "a" * 64, "type": "reference"}, first=True)
    with pytest.raises(ledger.CommitUncertain):
        lossy.supersede(REFERENCE, None, entry)
    assert _observer(database).operation_committed(entry["hash"]) is True  # it did commit
    assert _rows(database)[1] == [("7" * 64, False)]


@real_pg
def test_real_pg_reconcile_waits_for_an_act_still_open_and_never_reads_it_as_aborted(database, monkeypatch):
    """E-PG2: an act's transaction is still open on another connection when `reconcile` reads."""
    import psycopg

    _observer(database).authorize(REFERENCE, "7" * 64, {"hash": "a" * 64, "type": "reference"}, first=True)
    observer = _observer(database, read_only=True)  # `reconcile` also runs under the write barrier
    assert observer.operation_committed("a" * 64) is True
    holder = psycopg.connect(database, autocommit=True)
    try:
        holder.execute("BEGIN")
        holder.execute("INSERT INTO sgaa_cutover.operations (entry_hash) VALUES (%s)", ("f" * 64,))
        monkeypatch.setattr(ledger, "RECONCILE_LOCK_SECONDS", 1)
        with pytest.raises(ledger.Refused) as caught:  # it cannot be decided while the act is open
            observer.operation_committed("f" * 64)
        assert caught.value.code == "RECONCILE_UNDECIDED"
        monkeypatch.setattr(ledger, "RECONCILE_LOCK_SECONDS", 30)
        answer = {}
        reader = threading.Thread(target=lambda: answer.setdefault("committed", observer.operation_committed("f" * 64)))
        reader.start()
        time.sleep(1.0)
        assert reader.is_alive()  # waiting, not guessing
        holder.execute("COMMIT")
        reader.join(timeout=20)
        assert answer == {"committed": True}
    finally:
        holder.close()


@real_pg
def test_real_pg_the_stored_authorization_is_the_entry_the_application_accepts(database):
    """The intent entry (``outcome_required``) is what PROD stores; the application verifies it as before."""
    entry = {"seq": 1, "prev": "0" * 64, "at": "2026-10-12T00:00:00Z", "type": "authorization",
             "opening_reference": REFERENCE, "code_sha256": "9" * 64, "database_identity_sha256": "1" * 64,
             "vercel_project_sha256": "2" * 64, "outcome_required": True}
    entry["hash"] = hosting.ledger_entry_hash(entry)
    _observer(database).authorize(REFERENCE, "9" * 64, entry, first=False)
    import psycopg

    with psycopg.connect(database, autocommit=True) as conn:
        stored = conn.execute("SELECT entry FROM sgaa_cutover.opening").fetchone()[0]
    assert hosting.opening_entry_authorizes(stored, reference=REFERENCE, database_identity="1" * 64,
                                            code="9" * 64, project="2" * 64)


@real_pg
def test_real_pg_a_lift_and_its_marker_commit_together_and_a_lost_answer_is_uncertain(database):
    """Rereview of b83b5fc M4: `resume`'s lift is a transaction act -- the role default reset, the code's
    authorization restored and the act's marker commit together; a lost COMMIT answer is uncertain (never
    read as not committed) and `reconcile` finds the marker."""
    import psycopg

    _observer(database).authorize(REFERENCE, "7" * 64, {"hash": "a" * 64, "type": "reference"}, first=True)
    with psycopg.connect(database, autocommit=True) as conn:  # the barrier, as `close` leaves it
        conn.execute(ledger.Observer._role_statement(conn, "SET default_transaction_read_only = on"))
        conn.execute(hosting.OPENING_REVOKE_SQL)
    assert _observer(database).writable() is False
    lift = {"hash": "f" * 64, "type": "barrier"}
    with pytest.raises(ledger.CommitUncertain):
        _observer(database, wrap=_LostAnswer).lift_barrier(REFERENCE, "7" * 64, lift)
    assert _observer(database, read_only=True).operation_committed(lift["hash"]) is True
    assert _observer(database).writable() is True  # the role default was reset with it
    assert _rows(database)[1] == [("7" * 64, True)]  # and the authorization restored with it


@real_pg
def test_real_pg_a_deployment_admission_commits_with_its_marker_and_is_what_the_application_reads(database):
    """A19 (17): `admit-deployment` writes the admission of one deployment with its marker; the application's
    own statement finds it for that deployment only."""
    import psycopg

    observer = _observer(database)
    observer.authorize(REFERENCE, "7" * 64, {"hash": "a" * 64, "type": "reference"}, first=True)
    admitted = {"hash": "b" * 64, "type": "admission", "deployment_id": "dpl_" + "L" * 24}
    observer.admit(REFERENCE, "dpl_" + "L" * 24, admitted)
    assert observer.operation_committed(admitted["hash"]) is True
    with psycopg.connect(database, autocommit=True) as conn:
        found = conn.execute(hosting.ADMISSION_SELECT_SQL, (REFERENCE, "dpl_" + "L" * 24)).fetchone()
        other = conn.execute(hosting.ADMISSION_SELECT_SQL, (REFERENCE, "dpl_" + "U" * 24)).fetchone()
    assert found is not None and other is None
    with pytest.raises(ledger.Refused) as caught:  # admitted once: a second write refuses, nothing commits
        observer.admit(REFERENCE, "dpl_" + "L" * 24, {"hash": "c" * 64, "type": "admission"})
    assert caught.value.code == "PROD_TRANSACTION_FAILED"
    assert observer.operation_committed("c" * 64) is False


@real_pg
def test_real_pg_a_forward_fix_authorization_admits_exactly_its_own_deployment(database):
    """A19 (17): `authorize-code`'s transaction writes the code's authorization AND the admission of the one
    deployment its entry names (the entry itself), with its marker; no other deployment is admitted."""
    import psycopg

    observer = _observer(database)
    observer.authorize(REFERENCE, "7" * 64, {"hash": "a" * 64, "type": "reference"}, first=True)
    fix = {"hash": "b" * 64, "type": "authorization", "deployment_id": "dpl_" + "F" * 24}
    observer.authorize(REFERENCE, "9" * 64, fix, first=False)
    assert observer.operation_committed(fix["hash"]) is True
    with psycopg.connect(database, autocommit=True) as conn:
        admitted = conn.execute("SELECT deployment_id, entry FROM sgaa_cutover.admission").fetchall()
    assert [row[0] for row in admitted] == ["dpl_" + "F" * 24] and '"hash":"' + "b" * 64 in admitted[0][1]
