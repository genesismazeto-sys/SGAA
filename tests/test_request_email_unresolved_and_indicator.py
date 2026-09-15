"""Unresolved-outcome holds, per-generation failure attribution, and the
"exactly one *valid* default model" send gate.

These three rules all exist to stop the same class of harm: a student receiving
a duplicate, an empty, or a misattributed decision e-mail.
"""

from __future__ import annotations

import pytest

import app.request_email_dispatch as dispatch_module
from app.request_email_dispatch import (
    UNRESOLVED_HOLD_DETAIL,
    build_plan,
    dispatch,
    unresolved_student_ids,
)
from app.request_email_notifications import failed_request_ids, pending_request_ids
from app.services.mail_service import MailTransportError
from presets_api import DefaultEmailPresetError, get_default_email_preset
from tests.request_email_support import (
    decide,
    install_email_preset,
    new_v7_connection,
    seed_activity,
    seed_request,
    seed_student,
)


class FakeTransport:
    def __init__(self, *, fail_for=(), indeterminate_for=()):
        self.sent = []
        self.fail_for = set(fail_for)
        self.indeterminate_for = set(indeterminate_for)

    def __call__(self, conn, message):
        if message.to_address in self.indeterminate_for:
            raise MailTransportError("sem resposta do provedor", indeterminate=True)
        if message.to_address in self.fail_for:
            raise MailTransportError("recusado pelo provedor")
        self.sent.append(message.to_address)
        return {"http_status": 202}


@pytest.fixture
def scenario():
    conn = new_v7_connection()
    versao = seed_activity(conn)
    template = install_email_preset(conn)
    return conn, versao, template


def _decided(conn, versao, *, nome, matricula, email, **kw):
    aluno = seed_student(conn, nome=nome, matricula=matricula, email=email)
    req = seed_request(conn, aluno_id=aluno, versao_id=versao, **kw)
    decide(conn, req, status="Deferida")
    return aluno, req


# =====================================================================
# A. An UNRESOLVED outcome is never silently re-sent
# =====================================================================

def test_indeterminate_is_held_on_the_next_explicit_send(scenario):
    conn, versao, template = scenario
    aluno, req = _decided(conn, versao, nome="João", matricula="1", email="joao@x.com")

    dispatch_module.send_text_email = FakeTransport(indeterminate_for={"joao@x.com"})
    first = dispatch(conn, build_plan(conn, [req], template), template)
    assert first["outcomes"][0]["status"] == "indeterminate"

    # Administrator clicks Enviar again on the very same selection.
    second_transport = FakeTransport()
    dispatch_module.send_text_email = second_transport
    second = dispatch(conn, build_plan(conn, [req], template), template)

    assert second_transport.sent == [], "an unknown outcome must not be re-sent"
    assert second["held"] == 1 and second["sent"] == 0
    assert second["outcomes"][0]["status"] == "held"
    assert second["outcomes"][0]["detail"] == UNRESOLVED_HOLD_DETAIL
    assert second["outcomes"][0]["requer_confirmacao"] is True
    assert conn.execute(
        "SELECT tentativas FROM email_envios"
    ).fetchone()[0] == 1, "a held send must not burn an attempt"


def test_a_stale_sending_row_is_held_not_treated_as_delivered(scenario):
    """Process died mid-send: the outcome is unknown, so hold and ask."""
    conn, versao, template = scenario
    aluno, req = _decided(conn, versao, nome="Ana", matricula="2", email="ana@x.com")

    plan = build_plan(conn, [req], template)
    key = dispatch_module.compute_idempotency_key(aluno, plan[0]["event_ids"])
    conn.execute(
        "INSERT INTO email_envios(aluno_id,destinatario,assunto,corpo,status,"
        "tentativas,idempotency_key) VALUES(?,?,?,?,'sending',1,?)",
        (aluno, "ana@x.com", "s", "c", key),
    )
    conn.commit()

    transport = FakeTransport()
    dispatch_module.send_text_email = transport
    result = dispatch(conn, plan, template)

    assert transport.sent == []
    assert result["held"] == 1
    assert result["outcomes"][0]["requer_confirmacao"] is True


def test_explicit_acknowledgement_releases_the_resend(scenario):
    conn, versao, template = scenario
    aluno, req = _decided(conn, versao, nome="João", matricula="1", email="joao@x.com")

    dispatch_module.send_text_email = FakeTransport(indeterminate_for={"joao@x.com"})
    dispatch(conn, build_plan(conn, [req], template), template)

    transport = FakeTransport()
    dispatch_module.send_text_email = transport
    result = dispatch(
        conn, build_plan(conn, [req], template), template,
        confirmed_resend=[aluno],
    )

    assert transport.sent == ["joao@x.com"]
    assert result["sent"] == 1 and result["held"] == 0
    assert conn.execute(
        "SELECT estado FROM requisicao_email_eventos WHERE requisicao_id=?", (req,)
    ).fetchone()[0] == "sent"


def test_acknowledging_one_student_does_not_release_another(scenario):
    conn, versao, template = scenario
    a, req_a = _decided(conn, versao, nome="Ana", matricula="1", email="ana@x.com")
    b, req_b = _decided(conn, versao, nome="Bruno", matricula="2", email="bruno@x.com")

    dispatch_module.send_text_email = FakeTransport(
        indeterminate_for={"ana@x.com", "bruno@x.com"}
    )
    dispatch(conn, build_plan(conn, [req_a, req_b], template), template)

    transport = FakeTransport()
    dispatch_module.send_text_email = transport
    result = dispatch(
        conn, build_plan(conn, [req_a, req_b], template), template,
        confirmed_resend=[a],
    )

    assert transport.sent == ["ana@x.com"]
    assert result["sent"] == 1 and result["held"] == 1
    held = [o for o in result["outcomes"] if o["status"] == "held"]
    assert [o["aluno_id"] for o in held] == [b]


def test_definite_failure_is_still_retried_without_acknowledgement(scenario):
    """A *definite* failure is safe to retry -- only unknown outcomes hold."""
    conn, versao, template = scenario
    aluno, req = _decided(conn, versao, nome="João", matricula="1", email="joao@x.com")

    dispatch_module.send_text_email = FakeTransport(fail_for={"joao@x.com"})
    dispatch(conn, build_plan(conn, [req], template), template)

    transport = FakeTransport()
    dispatch_module.send_text_email = transport
    result = dispatch(conn, build_plan(conn, [req], template), template)

    assert transport.sent == ["joao@x.com"]
    assert result["sent"] == 1 and result["held"] == 0


def test_confirmed_sent_is_still_skipped_even_when_acknowledged(scenario):
    """Acknowledgement covers unknown outcomes, never a confirmed delivery."""
    conn, versao, template = scenario
    aluno, req = _decided(conn, versao, nome="João", matricula="1", email="joao@x.com")

    transport = FakeTransport()
    dispatch_module.send_text_email = transport
    plan = build_plan(conn, [req], template)
    dispatch(conn, plan, template)

    second = dispatch(conn, plan, template, confirmed_resend=[aluno])

    assert len(transport.sent) == 1, "a confirmed send is never repeated"
    assert second["skipped"] == 1 and second["held"] == 0


def test_preview_reports_unresolved_students_before_confirmation(scenario):
    conn, versao, template = scenario
    aluno, req = _decided(conn, versao, nome="João", matricula="1", email="joao@x.com")

    plan = build_plan(conn, [req], template)
    assert unresolved_student_ids(conn, plan) == set()

    dispatch_module.send_text_email = FakeTransport(indeterminate_for={"joao@x.com"})
    dispatch(conn, plan, template)

    assert unresolved_student_ids(conn, build_plan(conn, [req], template)) == {aluno}


# =====================================================================
# B. Failure attribution is per generation, not per student
# =====================================================================

def test_a_students_old_failure_does_not_flag_a_new_decision(scenario):
    conn, versao, template = scenario
    aluno = seed_student(conn, nome="Maria", matricula="9", email="maria@x.com")

    antiga = seed_request(conn, aluno_id=aluno, versao_id=versao)
    decide(conn, antiga, status="Indeferida")
    dispatch_module.send_text_email = FakeTransport(fail_for={"maria@x.com"})
    dispatch(conn, build_plan(conn, [antiga], template), template)

    # A brand-new decision on a different request, never attempted.
    nova = seed_request(conn, aluno_id=aluno, versao_id=versao)
    decide(conn, nova, status="Deferida")
    conn.commit()

    pending = pending_request_ids(conn, [antiga, nova])
    flagged = failed_request_ids(conn, [antiga, nova])

    assert pending == {antiga, nova}
    assert antiga in flagged, "the request that actually failed keeps the warning"
    assert nova not in flagged, (
        "a never-attempted generation must not inherit an old failure"
    )


def test_failure_never_crosses_to_another_student(scenario):
    conn, versao, template = scenario
    a, req_a = _decided(conn, versao, nome="Ana", matricula="1", email="ana@x.com")
    b, req_b = _decided(conn, versao, nome="Bruno", matricula="2", email="bruno@x.com")

    dispatch_module.send_text_email = FakeTransport(fail_for={"ana@x.com"})
    dispatch(conn, build_plan(conn, [req_a, req_b], template), template)

    flagged = failed_request_ids(conn, [req_a, req_b])
    assert req_a in flagged
    assert req_b not in flagged


def test_indeterminate_and_stale_sending_are_flagged_for_the_operator(scenario):
    conn, versao, template = scenario
    aluno, req = _decided(conn, versao, nome="João", matricula="1", email="joao@x.com")

    dispatch_module.send_text_email = FakeTransport(indeterminate_for={"joao@x.com"})
    dispatch(conn, build_plan(conn, [req], template), template)
    assert req in failed_request_ids(conn, [req])

    conn.execute("UPDATE email_envios SET status='sending'")
    conn.commit()
    assert req in failed_request_ids(conn, [req])


def test_a_pending_generation_is_linked_to_its_own_attempt(scenario):
    conn, versao, template = scenario
    aluno, req = _decided(conn, versao, nome="João", matricula="1", email="joao@x.com")

    dispatch_module.send_text_email = FakeTransport(fail_for={"joao@x.com"})
    dispatch(conn, build_plan(conn, [req], template), template)

    row = conn.execute(
        "SELECT estado,email_envio_id FROM requisicao_email_eventos"
        " WHERE requisicao_id=?",
        (req,),
    ).fetchone()
    assert row["estado"] == "pending", "a failed attempt keeps the generation pending"
    assert row["email_envio_id"] is not None, (
        "the pending generation must name the attempt that failed"
    )


def test_blocked_recipient_creates_no_outbox_row_and_no_link(scenario):
    """No address means no attempt at all -- nothing to attribute."""
    conn, versao, template = scenario
    aluno = seed_student(conn, nome="Carla", matricula="3", email="")
    req = seed_request(conn, aluno_id=aluno, versao_id=versao)
    decide(conn, req, status="Deferida")

    dispatch_module.send_text_email = FakeTransport()
    result = dispatch(conn, build_plan(conn, [req], template), template)

    assert result["failed"] == 1
    assert conn.execute("SELECT COUNT(*) FROM email_envios").fetchone()[0] == 0
    assert conn.execute(
        "SELECT email_envio_id FROM requisicao_email_eventos WHERE requisicao_id=?",
        (req,),
    ).fetchone()[0] is None
    assert req not in failed_request_ids(conn, [req])


# =====================================================================
# C. Sending requires exactly one VALID default model
# =====================================================================

def _set_default(conn, *, assunto, texto):
    conn.execute("DELETE FROM configuracoes_presets WHERE tipo='emails'")
    conn.execute(
        "INSERT INTO configuracoes_presets"
        "(tipo,preset_id,titulo,texto,assunto,is_default)"
        " VALUES('emails',1,'Modelo padrão',?,?,1)",
        (texto, assunto),
    )
    conn.commit()


def test_valid_default_is_returned():
    conn = new_v7_connection()
    _set_default(conn, assunto="Resultado", texto="Corpo do e-mail")
    chosen = get_default_email_preset(conn)
    assert chosen["assunto"] == "Resultado"
    assert chosen["texto"] == "Corpo do e-mail"


@pytest.mark.parametrize(
    ("assunto", "texto", "missing"),
    [
        ("", "Corpo", "assunto"),
        ("   ", "Corpo", "assunto"),
        ("Resultado", "", "conteúdo"),
        ("Resultado", "   \n ", "conteúdo"),
    ],
)
def test_incomplete_default_blocks_sending_with_an_actionable_error(
    assunto, texto, missing
):
    conn = new_v7_connection()
    _set_default(conn, assunto=assunto, texto=texto)

    with pytest.raises(DefaultEmailPresetError) as excinfo:
        get_default_email_preset(conn)

    message = str(excinfo.value)
    assert missing in message
    assert "Modelo padrão" in message, "the error must name the offending model"
    assert "Pré-definições" in message, "the error must say where to fix it"


def test_incomplete_default_is_never_silently_replaced():
    """No fallback to another model, to the first row, or to a hardcoded text."""
    conn = new_v7_connection()
    conn.execute(
        "INSERT INTO configuracoes_presets"
        "(tipo,preset_id,titulo,texto,assunto,is_default)"
        " VALUES('emails',1,'Completo','Corpo','Assunto',0)"
    )
    conn.execute(
        "INSERT INTO configuracoes_presets"
        "(tipo,preset_id,titulo,texto,assunto,is_default)"
        " VALUES('emails',2,'Incompleto','Corpo','',1)"
    )
    conn.commit()

    with pytest.raises(DefaultEmailPresetError):
        get_default_email_preset(conn)


def test_justificativa_presets_are_unaffected_by_the_email_gate():
    conn = new_v7_connection()
    conn.execute(
        "INSERT INTO configuracoes_presets(tipo,preset_id,titulo,texto)"
        " VALUES('respostas',1,'Justificativa','')"
    )
    _set_default(conn, assunto="Resultado", texto="Corpo")
    conn.commit()

    assert get_default_email_preset(conn)["id"] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM configuracoes_presets WHERE tipo='respostas'"
    ).fetchone()[0] == 1
