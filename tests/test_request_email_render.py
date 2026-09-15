"""Placeholder contract for request-decision e-mails."""

from __future__ import annotations

import datetime

import pytest

from app.request_email_render import (
    PlaceholderError,
    build_context,
    first_name,
    greeting_for,
    render_request_block,
    render_student_email,
    render_template,
    validate_template,
)
from tests.request_email_support import (
    decide,
    new_v7_connection,
    seed_activity,
    seed_request,
    seed_student,
)


def _events(conn, req_ids):
    from app.request_email_notifications import load_pending_events

    return load_pending_events(conn, req_ids)


def _one_student(**decisions):
    """Build a student with the given {status: kwargs} decisions."""
    conn = new_v7_connection()
    versao = seed_activity(conn)
    aluno = seed_student(conn, nome="João Carlos Silva", matricula="2026001",
                         email="joao@x.com")
    return conn, versao, aluno


# --- {saudacao} boundaries -------------------------------------------------

@pytest.mark.parametrize(
    "hour,expected",
    [
        (0, "Bom dia"), (6, "Bom dia"), (11, "Bom dia"),
        (12, "Boa tarde"), (15, "Boa tarde"), (17, "Boa tarde"),
        (18, "Boa noite"), (21, "Boa noite"), (23, "Boa noite"),
    ],
)
def test_greeting_boundaries(hour, expected):
    assert greeting_for(datetime.datetime(2026, 9, 15, hour, 0)) == expected


def test_greeting_is_computed_at_send_time_not_decision_time():
    morning = greeting_for(datetime.datetime(2026, 9, 15, 9, 0))
    evening = greeting_for(datetime.datetime(2026, 9, 15, 20, 0))
    assert morning != evening


# --- name / scalar placeholders -------------------------------------------

@pytest.mark.parametrize(
    "full,expected",
    [
        ("João Carlos Silva", "João"),
        ("  Maria  Clara ", "Maria"),
        ("Ana", "Ana"),
        ("", ""),
        (None, ""),
    ],
)
def test_first_name(full, expected):
    assert first_name(full) == expected


def test_first_name_does_not_mutate_stored_name():
    original = "João Carlos Silva"
    first_name(original)
    assert original == "João Carlos Silva"


# --- date range ------------------------------------------------------------

def test_date_range_uses_oldest_and_newest_included_request():
    conn, versao, aluno = _one_student()
    a = seed_request(conn, aluno_id=aluno, versao_id=versao, data_solicitacao="2026-03-01")
    b = seed_request(conn, aluno_id=aluno, versao_id=versao, data_solicitacao="2026-05-20")
    c = seed_request(conn, aluno_id=aluno, versao_id=versao, data_solicitacao="2026-04-10")
    for req in (a, b, c):
        decide(conn, req, status="Deferida")
    context = build_context(_events(conn, [a, b, c]), aluno_nome="João", aluno_matricula="1")
    assert context["data.inicio"] == "01/03/2026"
    assert context["data.fim"] == "20/05/2026"


def test_same_day_range_does_not_invent_a_range():
    conn, versao, aluno = _one_student()
    a = seed_request(conn, aluno_id=aluno, versao_id=versao, data_solicitacao="2026-03-01")
    b = seed_request(conn, aluno_id=aluno, versao_id=versao, data_solicitacao="2026-03-01")
    for req in (a, b):
        decide(conn, req, status="Deferida")
    context = build_context(_events(conn, [a, b]), aluno_nome="João", aluno_matricula="1")
    assert context["data.inicio"] == context["data.fim"] == "01/03/2026"


def test_quantity_counts_included_events():
    conn, versao, aluno = _one_student()
    ids = [seed_request(conn, aluno_id=aluno, versao_id=versao) for _ in range(3)]
    for req in ids:
        decide(conn, req, status="Deferida")
    context = build_context(_events(conn, ids), aluno_nome="João", aluno_matricula="1")
    assert context["quantidade_requisicoes"] == "3"


# --- {requisicoes} block ---------------------------------------------------

def test_block_contains_every_request_exactly_once():
    conn, versao, aluno = _one_student()
    ids = [seed_request(conn, aluno_id=aluno, versao_id=versao) for _ in range(3)]
    for req in ids:
        decide(conn, req, status="Deferida")
    block = render_request_block(_events(conn, ids))
    for req in ids:
        assert block.count(f"Requisição nº {req}") == 1


def test_partial_deferment_keeps_persisted_justification():
    conn, versao, aluno = _one_student()
    req = seed_request(conn, aluno_id=aluno, versao_id=versao)
    decide(conn, req, status="Deferida Parcialmente", horas_deferidas=4.0,
           observacao="Apenas 4h comprovadas.")
    block = render_request_block(_events(conn, [req]))
    assert "Justificativa: Apenas 4h comprovadas." in block
    assert "Horas deferidas: 4" in block


def test_denial_keeps_persisted_justification():
    conn, versao, aluno = _one_student()
    req = seed_request(conn, aluno_id=aluno, versao_id=versao)
    decide(conn, req, status="Indeferida", observacao="Documento ilegível.")
    block = render_request_block(_events(conn, [req]))
    assert "Justificativa: Documento ilegível." in block


def test_full_deferment_emits_no_empty_justification_label():
    conn, versao, aluno = _one_student()
    req = seed_request(conn, aluno_id=aluno, versao_id=versao)
    decide(conn, req, status="Deferida")
    block = render_request_block(_events(conn, [req]))
    assert "Justificativa:" not in block


def test_block_uses_decision_snapshot_not_current_preset():
    """Editing a justification preset must not rewrite sent/pending history."""
    conn, versao, aluno = _one_student()
    req = seed_request(conn, aluno_id=aluno, versao_id=versao)
    decide(conn, req, status="Indeferida", observacao="Texto original da decisão.")
    conn.execute(
        "INSERT INTO configuracoes_presets(tipo,preset_id,titulo,texto)"
        " VALUES('respostas',1,'Justificativa','TEXTO NOVO DO PRESET')"
    )
    block = render_request_block(_events(conn, [req]))
    assert "Texto original da decisão." in block
    assert "TEXTO NOVO DO PRESET" not in block


# --- validation ------------------------------------------------------------

def test_unknown_placeholder_is_rejected():
    with pytest.raises(PlaceholderError):
        validate_template("Olá {aluno.sobrenome}")


def test_requisicoes_rejected_in_subject():
    with pytest.raises(PlaceholderError):
        validate_template("Resultado {requisicoes}", allow_block=False)


def test_scalar_placeholders_allowed_in_subject():
    validate_template("Resultado de {aluno.primeironome} ({quantidade_requisicoes})",
                      allow_block=False)


def test_stored_template_is_not_executed_as_code():
    """Jinja/format syntax in a preset is data, never evaluated."""
    for hostile in ("{{ config }}", "{__class__}", "{0}", "{self.__dict__}"):
        with pytest.raises(PlaceholderError):
            render_template(hostile, {})


def test_render_replaces_known_tokens():
    conn, versao, aluno = _one_student()
    req = seed_request(conn, aluno_id=aluno, versao_id=versao, data_solicitacao="2026-03-01")
    decide(conn, req, status="Deferida")
    assunto, corpo = render_student_email(
        assunto="Resultado — {aluno.primeironome}",
        corpo="{saudacao}, {aluno.primeironome}.\n"
              "Matrícula {aluno.matricula}.\n"
              "De {data.inicio} a {data.fim}.\n\n{requisicoes}",
        events=_events(conn, [req]),
        aluno_nome="João Carlos Silva",
        aluno_matricula="2026001",
        moment=datetime.datetime(2026, 9, 15, 9, 0),
    )
    assert assunto == "Resultado — João"
    assert corpo.startswith("Bom dia, João.")
    assert "Matrícula 2026001." in corpo
    assert "De 01/03/2026 a 01/03/2026." in corpo
    assert f"Requisição nº {req}" in corpo
