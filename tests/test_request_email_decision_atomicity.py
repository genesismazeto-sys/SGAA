"""The academic decision and its pending e-mail generation are ONE transaction.

Required invariant (review section B): there must never be a normal successful
explicit final-decision response that leaves the request final but without its
required pending generation.  So if persisting the generation fails, the
decision mutation must not commit either.

This is deliberately NOT the same rule as provider delivery failure: a Graph
failure must never roll back an already-committed academic decision.  The first
test pair proves the local atomicity; the last test proves the two rules are not
conflated.
"""

from __future__ import annotations

import sqlite3

import pytest

import app.request_email_notifications as notifications
import app.views.admin.requisicoes as requisicoes_view
from tests.request_email_support import (
    new_v7_connection,
    seed_activity,
    seed_request,
    seed_student,
)


def _setup():
    conn = new_v7_connection()
    versao = seed_activity(conn)
    aluno = seed_student(conn, nome="João Silva", matricula="2026001", email="joao@x.com")
    req = seed_request(conn, aluno_id=aluno, versao_id=versao)
    conn.commit()
    return conn, versao, aluno, req


def _decide_like_the_handler(conn, req_id, *, status, fail_event=False):
    """Replay the canonical handler's ordering: UPDATE, then event, then COMMIT.

    Mirrors ``admin_processar_requisicao``: a single implicit transaction opened
    by the UPDATE and closed by one ``conn.commit()``.
    """
    conn.execute(
        "UPDATE requisicoes"
        "   SET status=?, data_processamento='2026-04-01 09:00:00'"
        " WHERE id=?",
        (status, req_id),
    )
    if fail_event:
        raise sqlite3.OperationalError("INJECTED decision-event persistence failure")
    notifications.record_final_decision_event(
        conn, requisicao_id=req_id, decided_at="2026-04-01 09:00:00"
    )
    conn.commit()


@pytest.mark.parametrize("status", ["Deferida", "Deferida Parcialmente", "Indeferida"])
def test_decision_and_generation_commit_together(status):
    conn, _versao, _aluno, req = _setup()

    _decide_like_the_handler(conn, req, status=status)

    assert conn.execute(
        "SELECT status FROM requisicoes WHERE id=?", (req,)
    ).fetchone()[0] == status
    assert conn.execute(
        "SELECT COUNT(*) FROM requisicao_email_eventos"
        " WHERE requisicao_id=? AND estado='pending'",
        (req,),
    ).fetchone()[0] == 1


@pytest.mark.parametrize("status", ["Deferida", "Deferida Parcialmente", "Indeferida"])
def test_event_persistence_failure_rolls_back_the_decision(status):
    """Failure injection: no event => no final decision either."""
    conn, _versao, _aluno, req = _setup()

    with pytest.raises(sqlite3.OperationalError, match="INJECTED"):
        _decide_like_the_handler(conn, req, status=status, fail_event=True)
    conn.rollback()   # what the Flask teardown does when the handler raises

    assert conn.execute(
        "SELECT status FROM requisicoes WHERE id=?", (req,)
    ).fetchone()[0] == "Pendente", "the academic decision must not survive alone"
    assert conn.execute(
        "SELECT COUNT(*) FROM requisicao_email_eventos"
    ).fetchone()[0] == 0


def test_a_raising_record_call_leaves_nothing_committed(monkeypatch):
    """Same invariant, driven through the real module entry point."""
    conn, _versao, _aluno, req = _setup()

    def explode(*_args, **_kwargs):
        raise sqlite3.IntegrityError("INJECTED constraint failure")

    monkeypatch.setattr(notifications, "record_final_decision_event", explode)

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "UPDATE requisicoes SET status='Deferida' WHERE id=?", (req,)
        )
        notifications.record_final_decision_event(conn, requisicao_id=req)
        conn.commit()
    conn.rollback()

    assert conn.execute(
        "SELECT status FROM requisicoes WHERE id=?", (req,)
    ).fetchone()[0] == "Pendente"


def test_handler_records_the_event_before_it_commits():
    """Static ordering guard on the canonical handler.

    If a future edit moves ``conn.commit()`` above ``record_final_decision_event``
    the two would stop being atomic while every behavioural test still passed,
    because the handler would simply be running two transactions.
    """
    import inspect

    source = inspect.getsource(requisicoes_view.admin_processar_requisicao)
    tail = source.split("UPDATE requisicoes SET")[-1]
    record_at = tail.find("record_final_decision_event")
    supersede_at = tail.find("supersede_pending_event")
    commit_at = tail.find("conn.commit()")

    assert record_at != -1, "the explicit decision path must create a generation"
    assert supersede_at != -1, "reabrir must supersede the pending generation"
    assert commit_at != -1
    assert record_at < commit_at, (
        "record_final_decision_event must run BEFORE conn.commit() so the "
        "decision and its pending generation share one transaction"
    )
    assert supersede_at < commit_at


def test_decision_without_student_commits_without_a_generation():
    """Documented carve-out: an unaddressable request has nothing to notify.

    ``record_final_decision_event`` returns ``None`` rather than raising, so the
    decision still commits -- there is no recipient a pending generation could
    ever be sent to.
    """
    conn = new_v7_connection()
    versao = seed_activity(conn)
    aluno = seed_student(conn, nome="Temp", matricula="tmp", email="t@x.com")
    req = seed_request(conn, aluno_id=aluno, versao_id=versao)
    conn.execute("UPDATE requisicoes SET aluno_id=NULL WHERE id=?", (req,))
    conn.commit()

    _decide_like_the_handler(conn, req, status="Indeferida")

    assert conn.execute(
        "SELECT status FROM requisicoes WHERE id=?", (req,)
    ).fetchone()[0] == "Indeferida"
    assert conn.execute(
        "SELECT COUNT(*) FROM requisicao_email_eventos"
    ).fetchone()[0] == 0


def test_provider_failure_does_not_roll_back_the_committed_decision():
    """The rule NOT to conflate: delivery failure is outside the decision.

    The decision and its generation are already durable; a later transport
    failure must leave both in place and the generation merely still pending.
    """
    import app.request_email_dispatch as dispatch_module
    from app.request_email_dispatch import build_plan, dispatch
    from app.services.mail_service import MailTransportError
    from tests.request_email_support import install_email_preset

    conn, _versao, _aluno, req = _setup()
    template = install_email_preset(conn)
    _decide_like_the_handler(conn, req, status="Deferida")

    def refuse(_conn, _message):
        raise MailTransportError("provedor recusou")

    dispatch_module.send_text_email = refuse
    result = dispatch(conn, build_plan(conn, [req], template), template)

    assert result["failed"] == 1 and result["sent"] == 0
    assert conn.execute(
        "SELECT status FROM requisicoes WHERE id=?", (req,)
    ).fetchone()[0] == "Deferida", "a delivery failure must not undo the decision"
    assert conn.execute(
        "SELECT estado FROM requisicao_email_eventos WHERE requisicao_id=?", (req,)
    ).fetchone()[0] == "pending"
