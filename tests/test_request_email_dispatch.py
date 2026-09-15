"""Batch grouping, recipient validation, idempotency and delivery outcomes.

Every test fakes the transport. No test in this module performs a network call
or a real Microsoft Graph send.
"""

from __future__ import annotations

import pytest

import app.request_email_dispatch as dispatch_module
from app.request_email_dispatch import build_plan, compute_idempotency_key, dispatch, summarize
from app.services.mail_service import MailTransportError
from tests.request_email_support import (
    decide,
    install_email_preset,
    new_v7_connection,
    seed_activity,
    seed_request,
    seed_student,
)


class FakeTransport:
    """Records sends instead of contacting Graph."""

    def __init__(self, *, fail_for=(), indeterminate_for=()):
        self.sent: list[tuple[str, str, str]] = []
        self.fail_for = set(fail_for)
        self.indeterminate_for = set(indeterminate_for)

    def __call__(self, conn, message):
        if message.to_address in self.indeterminate_for:
            raise MailTransportError(
                "Envio não confirmado.", debug_code="MAIL_SEND_INDETERMINATE",
                indeterminate=True,
            )
        if message.to_address in self.fail_for:
            raise MailTransportError("Falha do provedor.", debug_code="MAIL_SEND_FAILED")
        self.sent.append((message.to_address, message.subject, message.body_text))
        return {"status": "sent", "http_status": 202}


@pytest.fixture
def fake_transport(monkeypatch):
    transport = FakeTransport()
    monkeypatch.setattr(dispatch_module, "send_text_email", transport)
    return transport


def _scenario():
    conn = new_v7_connection()
    versao = seed_activity(conn)
    template = install_email_preset(conn)
    return conn, versao, template


def test_one_request_one_student_one_email(fake_transport):
    conn, versao, template = _scenario()
    aluno = seed_student(conn, nome="João Silva", matricula="1", email="joao@x.com")
    req = seed_request(conn, aluno_id=aluno, versao_id=versao)
    decide(conn, req, status="Deferida")

    plan = build_plan(conn, [req], template)
    result = dispatch(conn, plan, template)

    assert len(fake_transport.sent) == 1
    assert result["sent"] == 1
    assert fake_transport.sent[0][0] == "joao@x.com"


def test_several_requests_same_student_produce_one_email(fake_transport):
    conn, versao, template = _scenario()
    aluno = seed_student(conn, nome="João Silva", matricula="1", email="joao@x.com")
    ids = [seed_request(conn, aluno_id=aluno, versao_id=versao) for _ in range(3)]
    for req in ids:
        decide(conn, req, status="Deferida")

    plan = build_plan(conn, ids, template)
    result = dispatch(conn, plan, template)

    assert len(fake_transport.sent) == 1
    assert result["sent"] == 1
    body = fake_transport.sent[0][2]
    for req in ids:
        assert body.count(f"Requisição nº {req}") == 1


def test_multiple_students_produce_one_email_each(fake_transport):
    conn, versao, template = _scenario()
    joao = seed_student(conn, nome="João Silva", matricula="1", email="joao@x.com")
    maria = seed_student(conn, nome="Maria Souza", matricula="2", email="maria@x.com")
    joao_ids = [seed_request(conn, aluno_id=joao, versao_id=versao) for _ in range(3)]
    maria_ids = [seed_request(conn, aluno_id=maria, versao_id=versao) for _ in range(2)]
    for req in joao_ids + maria_ids:
        decide(conn, req, status="Deferida")

    plan = build_plan(conn, joao_ids + maria_ids, template)
    assert len(plan) == 2                      # 5 requisições · 2 alunos · 2 e-mails
    assert sum(e["quantidade"] for e in plan) == 5

    result = dispatch(conn, plan, template)
    assert result["sent"] == 2
    assert len(fake_transport.sent) == 2


def test_no_cross_student_data_leakage(fake_transport):
    conn, versao, template = _scenario()
    joao = seed_student(conn, nome="João Silva", matricula="111", email="joao@x.com")
    maria = seed_student(conn, nome="Maria Souza", matricula="222", email="maria@x.com")
    joao_req = seed_request(conn, aluno_id=joao, versao_id=versao)
    maria_req = seed_request(conn, aluno_id=maria, versao_id=versao)
    decide(conn, joao_req, status="Deferida")
    decide(conn, maria_req, status="Indeferida", observacao="Sigilo da Maria.")

    dispatch(conn, build_plan(conn, [joao_req, maria_req], template), template)

    by_address = {addr: body for addr, _subj, body in fake_transport.sent}
    assert f"Requisição nº {maria_req}" not in by_address["joao@x.com"]
    assert "Sigilo da Maria." not in by_address["joao@x.com"]
    assert "222" not in by_address["joao@x.com"]
    assert f"Requisição nº {joao_req}" not in by_address["maria@x.com"]
    assert "111" not in by_address["maria@x.com"]


def test_student_without_email_stays_pending(fake_transport):
    conn, versao, template = _scenario()
    sem_email = seed_student(conn, nome="Sem Email", matricula="3", email=None)
    req = seed_request(conn, aluno_id=sem_email, versao_id=versao)
    decide(conn, req, status="Deferida")

    result = dispatch(conn, build_plan(conn, [req], template), template)

    assert result["sent"] == 0 and result["failed"] == 1
    assert fake_transport.sent == []
    assert conn.execute(
        "SELECT estado FROM requisicao_email_eventos WHERE requisicao_id=?", (req,)
    ).fetchone()[0] == "pending"


def test_structurally_invalid_email_stays_pending(fake_transport):
    conn, versao, template = _scenario()
    invalido = seed_student(conn, nome="Invalido", matricula="4", email="nao-e-email")
    req = seed_request(conn, aluno_id=invalido, versao_id=versao)
    decide(conn, req, status="Deferida")

    result = dispatch(conn, build_plan(conn, [req], template), template)

    assert result["failed"] == 1
    assert fake_transport.sent == []
    assert conn.execute(
        "SELECT estado FROM requisicao_email_eventos WHERE requisicao_id=?", (req,)
    ).fetchone()[0] == "pending"


def test_mixed_batch_reports_partial_success(monkeypatch):
    conn, versao, template = _scenario()
    joao = seed_student(conn, nome="João", matricula="1", email="joao@x.com")
    maria = seed_student(conn, nome="Maria", matricula="2", email="maria@x.com")
    ana = seed_student(conn, nome="Ana", matricula="3", email="ana@x.com")
    reqs = {}
    for name, aluno in (("joao", joao), ("maria", maria), ("ana", ana)):
        req = seed_request(conn, aluno_id=aluno, versao_id=versao)
        decide(conn, req, status="Deferida")
        reqs[name] = req

    transport = FakeTransport(fail_for={"ana@x.com"})
    monkeypatch.setattr(dispatch_module, "send_text_email", transport)

    result = dispatch(conn, build_plan(conn, list(reqs.values()), template), template)

    assert (result["sent"], result["failed"]) == (2, 1)
    assert summarize(result) == "2 e-mails enviados. 1 não pôde ser enviado."
    # Only successfully delivered events lose pending status.
    assert conn.execute(
        "SELECT estado FROM requisicao_email_eventos WHERE requisicao_id=?", (reqs["ana"],)
    ).fetchone()[0] == "pending"
    assert conn.execute(
        "SELECT estado FROM requisicao_email_eventos WHERE requisicao_id=?", (reqs["joao"],)
    ).fetchone()[0] == "sent"


def test_definite_failure_leaves_requests_pending(monkeypatch):
    conn, versao, template = _scenario()
    aluno = seed_student(conn, nome="João", matricula="1", email="joao@x.com")
    req = seed_request(conn, aluno_id=aluno, versao_id=versao)
    decide(conn, req, status="Deferida")

    monkeypatch.setattr(
        dispatch_module, "send_text_email", FakeTransport(fail_for={"joao@x.com"})
    )
    dispatch(conn, build_plan(conn, [req], template), template)

    assert conn.execute(
        "SELECT estado FROM requisicao_email_eventos WHERE requisicao_id=?", (req,)
    ).fetchone()[0] == "pending"
    assert conn.execute(
        "SELECT status FROM email_envios"
    ).fetchone()[0] == "failed"


def test_indeterminate_result_is_recorded_and_not_auto_retried(monkeypatch):
    """Graph gave no definitive answer: never silently resend."""
    conn, versao, template = _scenario()
    aluno = seed_student(conn, nome="João", matricula="1", email="joao@x.com")
    req = seed_request(conn, aluno_id=aluno, versao_id=versao)
    decide(conn, req, status="Deferida")

    transport = FakeTransport(indeterminate_for={"joao@x.com"})
    monkeypatch.setattr(dispatch_module, "send_text_email", transport)
    dispatch(conn, build_plan(conn, [req], template), template)

    assert transport.sent == []
    assert conn.execute("SELECT status FROM email_envios").fetchone()[0] == "indeterminate"
    assert conn.execute(
        "SELECT estado FROM requisicao_email_eventos WHERE requisicao_id=?", (req,)
    ).fetchone()[0] == "pending"


def test_retry_after_failure_can_complete(monkeypatch):
    conn, versao, template = _scenario()
    aluno = seed_student(conn, nome="João", matricula="1", email="joao@x.com")
    req = seed_request(conn, aluno_id=aluno, versao_id=versao)
    decide(conn, req, status="Deferida")

    monkeypatch.setattr(
        dispatch_module, "send_text_email", FakeTransport(fail_for={"joao@x.com"})
    )
    dispatch(conn, build_plan(conn, [req], template), template)

    working = FakeTransport()
    monkeypatch.setattr(dispatch_module, "send_text_email", working)
    result = dispatch(conn, build_plan(conn, [req], template), template)

    assert result["sent"] == 1
    assert len(working.sent) == 1
    assert conn.execute(
        "SELECT estado FROM requisicao_email_eventos WHERE requisicao_id=?", (req,)
    ).fetchone()[0] == "sent"
    # Retry reuses the same outbox row rather than creating a duplicate.
    assert conn.execute("SELECT COUNT(*) FROM email_envios").fetchone()[0] == 1


def test_duplicate_submit_does_not_send_twice(fake_transport):
    conn, versao, template = _scenario()
    aluno = seed_student(conn, nome="João", matricula="1", email="joao@x.com")
    req = seed_request(conn, aluno_id=aluno, versao_id=versao)
    decide(conn, req, status="Deferida")

    plan = build_plan(conn, [req], template)
    dispatch(conn, plan, template)
    # Exact same confirmed payload posted a second time.
    second = dispatch(conn, plan, template)

    assert len(fake_transport.sent) == 1
    assert second["skipped"] == 1 and second["sent"] == 0
    assert conn.execute("SELECT COUNT(*) FROM email_envios").fetchone()[0] == 1


def test_idempotency_key_is_stable_and_order_independent():
    assert compute_idempotency_key(7, [3, 1, 2]) == compute_idempotency_key(7, [1, 2, 3])
    assert compute_idempotency_key(7, [1, 2]) != compute_idempotency_key(8, [1, 2])
    assert compute_idempotency_key(7, [1, 2]) != compute_idempotency_key(7, [1, 2, 3])


def test_successful_send_marks_only_included_events(fake_transport):
    conn, versao, template = _scenario()
    aluno = seed_student(conn, nome="João", matricula="1", email="joao@x.com")
    incluida = seed_request(conn, aluno_id=aluno, versao_id=versao)
    de_fora = seed_request(conn, aluno_id=aluno, versao_id=versao)
    decide(conn, incluida, status="Deferida")
    decide(conn, de_fora, status="Deferida")

    dispatch(conn, build_plan(conn, [incluida], template), template)

    assert conn.execute(
        "SELECT estado FROM requisicao_email_eventos WHERE requisicao_id=?", (incluida,)
    ).fetchone()[0] == "sent"
    assert conn.execute(
        "SELECT estado FROM requisicao_email_eventos WHERE requisicao_id=?", (de_fora,)
    ).fetchone()[0] == "pending"


def test_sent_body_snapshot_is_frozen_against_preset_edits(fake_transport):
    conn, versao, template = _scenario()
    aluno = seed_student(conn, nome="João", matricula="1", email="joao@x.com")
    req = seed_request(conn, aluno_id=aluno, versao_id=versao)
    decide(conn, req, status="Deferida")

    dispatch(conn, build_plan(conn, [req], template), template)
    original_body = conn.execute("SELECT corpo FROM email_envios").fetchone()[0]

    conn.execute(
        "UPDATE configuracoes_presets SET texto='CORPO COMPLETAMENTE NOVO'"
        " WHERE tipo='emails' AND preset_id=1"
    )

    assert conn.execute("SELECT corpo FROM email_envios").fetchone()[0] == original_body
    assert "CORPO COMPLETAMENTE NOVO" not in original_body
