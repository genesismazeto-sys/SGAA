"""UI-B01 -- grammatical number in the processing-notification e-mail.

A real delivered message read "Suas requisição do dia 15/09/2026 foi
processada.": three number-bearing words chosen independently, two of them
frozen as literals in the stored preset.  These tests pin the whole sentence and
the whole subject to ONE cardinality decision.

Everything here goes through the production composer -- ``build_plan`` renders,
``dispatch`` hands the result to the transport -- and captures the outbound
subject/body at the existing fake-mail boundary.  No copied string fixture, no
network call.
"""

from __future__ import annotations

import pytest

import app.request_email_dispatch as dispatch_module
from app.request_email_dispatch import build_plan, dispatch
from app.request_email_render import (
    DEFAULT_BODY_TEMPLATE,
    DEFAULT_SUBJECT_TEMPLATE,
    build_context,
)
from tests.request_email_support import (
    decide,
    install_email_preset,
    new_v7_connection,
    seed_activity,
    seed_request,
    seed_student,
)


class CapturingTransport:
    """Records the composed message instead of contacting the provider."""

    def __init__(self):
        self.sent: list[tuple[str, str, str]] = []

    def __call__(self, conn, message):
        self.sent.append((message.to_address, message.subject, message.body_text))
        return {"status": "sent", "http_status": 202}


@pytest.fixture
def captured(monkeypatch):
    transport = CapturingTransport()
    monkeypatch.setattr(dispatch_module, "send_text_email", transport)
    return transport


def _send(captured, dates, *, nomes_atividade=None):
    """Decide ``len(dates)`` requests for one student and send the real e-mail."""
    conn = new_v7_connection()
    # Distinct activities by default; the repeated-activity test passes one name.
    nomes = nomes_atividade or [f"Congresso {i}" for i in range(len(dates))]
    aluno = seed_student(conn, nome="João Silva", matricula="1", email="joao@x.com")
    template = install_email_preset(
        conn, assunto=DEFAULT_SUBJECT_TEMPLATE, texto=DEFAULT_BODY_TEMPLATE
    )
    ids = []
    # `atividade_base.nome_conceito` is UNIQUE, so a repeated activity name is
    # the SAME activity -- exactly the shape the repeated-activity test needs.
    versoes: dict[str, int] = {}
    for data, nome in zip(dates, nomes):
        if nome not in versoes:
            versoes[nome] = seed_activity(conn, nome=nome)
        versao = versoes[nome]
        req = seed_request(conn, aluno_id=aluno, versao_id=versao, data_solicitacao=data)
        decide(conn, req, status="Deferida")
        ids.append(req)

    plan = build_plan(conn, ids, template)
    result = dispatch(conn, plan, template)
    assert result["sent"] == 1, result
    assert len(captured.sent) == 1
    _to, subject, body = captured.sent[0]
    return subject, body


# ===================== A. one processed request =====================

def test_one_request_subject_is_singular(captured):
    subject, _body = _send(captured, ["2026-09-15"])
    assert subject == "Processamento de atividade acadêmica"


def test_one_request_body_agrees_in_the_singular(captured):
    _subject, body = _send(captured, ["2026-09-15"])
    assert "Sua requisição do dia 15/09/2026 foi processada." in body
    assert "Acesse o SGAA para conferir." in body


@pytest.mark.parametrize(
    "mixed",
    [
        "Suas requisição",
        "Suas requisições do dia 15/09/2026 foi",
        "requisição do dia 15/09/2026 foram",
        "Sua requisições",
        "foram processada",
        "foi processadas",
    ],
)
def test_one_request_never_mixes_number(captured, mixed):
    """The exact delivered defect, plus every other fragment mismatch."""
    _subject, body = _send(captured, ["2026-09-15"])
    assert mixed not in body


# ===================== B. two processed requests =====================

def test_two_requests_subject_is_plural(captured):
    subject, _body = _send(captured, ["2026-09-15", "2026-09-15"])
    assert subject == "Processamento de atividades acadêmicas"


def test_two_requests_body_agrees_in_the_plural(captured):
    _subject, body = _send(captured, ["2026-09-15", "2026-09-15"])
    assert "Suas requisições do dia 15/09/2026 foram processadas." in body
    assert "Sua requisição" not in body
    assert "foi processada" not in body


def test_two_requests_on_different_days_keep_the_plural_with_a_range(captured):
    _subject, body = _send(captured, ["2026-09-15", "2026-09-18"])
    assert "Suas requisições de 15/09/2026 a 18/09/2026 foram processadas." in body


# ===================== C. three or more =====================

def test_three_requests_hold_the_plural_contract(captured):
    subject, body = _send(captured, ["2026-09-15", "2026-09-16", "2026-09-17"])
    assert subject == "Processamento de atividades acadêmicas"
    assert "Suas requisições de 15/09/2026 a 17/09/2026 foram processadas." in body
    assert "Sua requisição" not in body


# ===================== the model: requests vs activities =====================

def test_request_count_is_the_activity_count_even_for_repeated_activities(captured):
    """Two requests for the SAME activity are still two processed items.

    Each decision event snapshots exactly one request and exactly one activity,
    so ``len(events)`` governs both phrases.  Distinct activity *names* are
    deliberately not collapsed: a subject reading "atividade acadêmica" beside a
    body reading "Suas requisições … foram processadas" would contradict itself.
    """
    subject, body = _send(
        captured,
        ["2026-09-15", "2026-09-15"],
        nomes_atividade=["Congresso", "Congresso"],
    )
    assert subject == "Processamento de atividades acadêmicas"
    assert "Suas requisições do dia 15/09/2026 foram processadas." in body


def test_subject_and_body_derive_from_the_same_count(captured):
    """Per-student number: João's two plural, Maria's one singular, one batch."""
    conn = new_v7_connection()
    versao = seed_activity(conn)
    template = install_email_preset(
        conn, assunto=DEFAULT_SUBJECT_TEMPLATE, texto=DEFAULT_BODY_TEMPLATE
    )
    joao = seed_student(conn, nome="João", matricula="1", email="joao@x.com")
    maria = seed_student(conn, nome="Maria", matricula="2", email="maria@x.com")
    ids = []
    for aluno, quantidade in ((joao, 2), (maria, 1)):
        for _ in range(quantidade):
            req = seed_request(
                conn, aluno_id=aluno, versao_id=versao, data_solicitacao="2026-09-15"
            )
            decide(conn, req, status="Deferida")
            ids.append(req)

    plan = build_plan(conn, ids, template)
    dispatch(conn, plan, template)

    by_recipient = {to: (subject, body) for to, subject, body in captured.sent}
    assert by_recipient["joao@x.com"][0] == "Processamento de atividades acadêmicas"
    assert "Suas requisições do dia 15/09/2026 foram processadas." in by_recipient["joao@x.com"][1]
    assert by_recipient["maria@x.com"][0] == "Processamento de atividade acadêmica"
    assert "Sua requisição do dia 15/09/2026 foi processada." in by_recipient["maria@x.com"][1]


# ===================== the centralized decision =====================

def test_phrase_is_assembled_once_not_glued_from_fragments():
    """The sentence is one context value, so a preset cannot desynchronize it."""
    conn = new_v7_connection()
    versao = seed_activity(conn)
    aluno = seed_student(conn, nome="João", matricula="1", email="joao@x.com")
    ids = []
    for _ in range(2):
        req = seed_request(
            conn, aluno_id=aluno, versao_id=versao, data_solicitacao="2026-09-15"
        )
        decide(conn, req, status="Deferida")
        ids.append(req)
    from app.request_email_notifications import load_pending_events

    plural = build_context(
        load_pending_events(conn, ids), aluno_nome="João", aluno_matricula="1"
    )
    singular = build_context(
        load_pending_events(conn, ids[:1]), aluno_nome="João", aluno_matricula="1"
    )
    assert singular["requisicao.frase"] == "Sua requisição do dia 15/09/2026 foi processada."
    assert plural["requisicao.frase"] == "Suas requisições do dia 15/09/2026 foram processadas."
    assert singular["atividade.substantivo"] == "atividade acadêmica"
    assert plural["atividade.substantivo"] == "atividades acadêmicas"


def test_phrase_has_no_double_space_when_no_date_is_known():
    """A missing period must not leave "Sua requisição  foi processada."."""
    events = [
        {
            "data_solicitacao": None,
            "requisicao_id": 1,
            "atividade_nome": "Congresso",
            "nome_evento": "",
            "status_decisao": "Deferida",
            "horas_solicitadas": 4,
            "horas_deferidas": 4,
            "justificativa": "",
        }
    ]
    ctx = build_context(events, aluno_nome="João", aluno_matricula="1")
    assert ctx["requisicao.frase"] == "Sua requisição foi processada."
    assert "  " not in ctx["requisicao.frase"]


def test_default_copy_hardcodes_no_number_bearing_word():
    """Every agreeing word in the shipped copy is a placeholder, not a literal."""
    for frozen in (
        "Sua ",
        "Suas ",
        "requisição",
        "requisições",
        "foi processada",
        "foram processadas",
        "atividade acadêmica",
        "atividades acadêmicas",
    ):
        assert frozen not in DEFAULT_BODY_TEMPLATE
        assert frozen not in DEFAULT_SUBJECT_TEMPLATE


def test_new_placeholders_are_subject_safe():
    from app.request_email_render import validate_template

    validate_template(DEFAULT_SUBJECT_TEMPLATE, allow_block=False)
    validate_template(DEFAULT_BODY_TEMPLATE, allow_block=True)
