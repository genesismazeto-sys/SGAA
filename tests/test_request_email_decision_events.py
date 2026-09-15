"""RULING 3: notification generations are explicit, never derived."""

from __future__ import annotations

from app.request_email_notifications import (
    pending_request_ids,
    record_final_decision_event,
)
from app.requisitions import auto_indefer_devolvidas
from tests.request_email_support import (
    decide,
    new_v7_connection,
    reopen,
    seed_activity,
    seed_request,
    seed_student,
)


def _setup():
    conn = new_v7_connection()
    versao = seed_activity(conn)
    aluno = seed_student(conn, nome="João Silva", matricula="2026001", email="joao@x.com")
    return conn, versao, aluno


def test_explicit_deferir_creates_pending_generation():
    conn, versao, aluno = _setup()
    req = seed_request(conn, aluno_id=aluno, versao_id=versao)
    assert decide(conn, req, status="Deferida") is not None
    assert pending_request_ids(conn) == {req}


def test_explicit_deferir_parte_creates_pending_generation():
    conn, versao, aluno = _setup()
    req = seed_request(conn, aluno_id=aluno, versao_id=versao)
    decide(conn, req, status="Deferida Parcialmente", horas_deferidas=4.0,
           observacao="Somente 4h comprovadas.")
    event = conn.execute(
        "SELECT * FROM requisicao_email_eventos WHERE requisicao_id=?", (req,)
    ).fetchone()
    assert event["estado"] == "pending"
    assert event["horas_deferidas"] == 4.0
    assert event["justificativa"] == "Somente 4h comprovadas."


def test_explicit_indeferir_creates_pending_generation():
    conn, versao, aluno = _setup()
    req = seed_request(conn, aluno_id=aluno, versao_id=versao)
    decide(conn, req, status="Indeferida", observacao="Documento ilegível.")
    event = conn.execute(
        "SELECT * FROM requisicao_email_eventos WHERE requisicao_id=?", (req,)
    ).fetchone()
    assert event["status_decisao"] == "Indeferida"
    assert event["justificativa"] == "Documento ilegível."


def test_non_final_transitions_create_nothing():
    conn, versao, aluno = _setup()
    for status in ("Devolvida", "Encerrada", "Pendente"):
        req = seed_request(conn, aluno_id=aluno, versao_id=versao)
        conn.execute("UPDATE requisicoes SET status=? WHERE id=?", (status, req))
        assert record_final_decision_event(conn, requisicao_id=req) is None
    assert conn.execute("SELECT COUNT(*) FROM requisicao_email_eventos").fetchone()[0] == 0


def test_auto_indefer_devolvidas_creates_no_pending_events():
    """The guard that keeps page-load maintenance out of the outbox."""
    conn, versao, aluno = _setup()
    conn.execute(
        "INSERT INTO configuracoes_app(chave,valor) VALUES('auto_indefer_devolvida','1')"
    )
    conn.execute(
        "INSERT INTO configuracoes_app(chave,valor) VALUES('return_response_days','5')"
    )
    req = seed_request(conn, aluno_id=aluno, versao_id=versao, status="Devolvida")
    conn.execute(
        "UPDATE requisicoes SET data_processamento=datetime('now','-30 days') WHERE id=?",
        (req,),
    )
    conn.commit()

    changed = auto_indefer_devolvidas(conn)

    # The academic status really did flip...
    assert changed == 1
    assert conn.execute(
        "SELECT status FROM requisicoes WHERE id=?", (req,)
    ).fetchone()[0] == "Indeferida"
    # ...and yet no e-mail generation exists, because no administrator decided.
    assert conn.execute("SELECT COUNT(*) FROM requisicao_email_eventos").fetchone()[0] == 0
    assert pending_request_ids(conn) == set()


def test_reopen_supersedes_current_pending_generation():
    conn, versao, aluno = _setup()
    req = seed_request(conn, aluno_id=aluno, versao_id=versao)
    decide(conn, req, status="Deferida")
    assert pending_request_ids(conn) == {req}

    reopen(conn, req)

    assert pending_request_ids(conn) == set()
    assert conn.execute(
        "SELECT estado FROM requisicao_email_eventos WHERE requisicao_id=?", (req,)
    ).fetchone()[0] == "superseded"


def test_new_decision_after_reopen_creates_new_generation():
    conn, versao, aluno = _setup()
    req = seed_request(conn, aluno_id=aluno, versao_id=versao)
    decide(conn, req, status="Indeferida", observacao="Faltou comprovante.")
    reopen(conn, req)
    decide(conn, req, status="Deferida", decided_at="2026-05-02 10:00:00")

    rows = conn.execute(
        "SELECT estado,status_decisao FROM requisicao_email_eventos"
        " WHERE requisicao_id=? ORDER BY id",
        (req,),
    ).fetchall()
    assert [(r["estado"], r["status_decisao"]) for r in rows] == [
        ("superseded", "Indeferida"),
        ("pending", "Deferida"),
    ]
    assert pending_request_ids(conn) == {req}


def test_sent_generation_is_never_superseded_by_reopen():
    """Sent history is immutable."""
    conn, versao, aluno = _setup()
    req = seed_request(conn, aluno_id=aluno, versao_id=versao)
    decide(conn, req, status="Deferida")
    conn.execute(
        "UPDATE requisicao_email_eventos SET estado='sent' WHERE requisicao_id=?", (req,)
    )

    reopen(conn, req)

    assert conn.execute(
        "SELECT estado FROM requisicao_email_eventos WHERE requisicao_id=?", (req,)
    ).fetchone()[0] == "sent"


def test_redeciding_supersedes_previous_pending():
    conn, versao, aluno = _setup()
    req = seed_request(conn, aluno_id=aluno, versao_id=versao)
    decide(conn, req, status="Deferida")
    decide(conn, req, status="Indeferida", observacao="Revisão.")

    states = [
        r["estado"]
        for r in conn.execute(
            "SELECT estado FROM requisicao_email_eventos WHERE requisicao_id=? ORDER BY id",
            (req,),
        )
    ]
    assert states == ["superseded", "pending"]


def test_request_without_student_creates_no_event():
    conn, versao, _aluno = _setup()
    req = seed_request(conn, aluno_id=None, versao_id=versao)
    conn.execute("UPDATE requisicoes SET status='Deferida' WHERE id=?", (req,))
    assert record_final_decision_event(conn, requisicao_id=req) is None
