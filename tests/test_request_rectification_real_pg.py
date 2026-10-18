"""Real PostgreSQL (E-PG1): the student's resubmission write of ``app.student_request_edit``.

The production database is PostgreSQL, so the compare-and-set UPDATE that
resubmits a returned request -- literal NULL resets, the text processing-date
match, ``rowcount`` -- and the superseded pending decision e-mail are proven
on a real server through the runtime adapter. Skips without
``SGAA_PG_TEST_URL`` (REAL-PG EVIDENCE: ABSENT). Run-owned databases only
(``tests.storage_mp1_pg_support``), seeded with synthetic rows.
"""
from __future__ import annotations

import pytest

from app.db import write_transaction
from app.student_request_edit import (
    StudentEditConflict,
    StudentRequestEdit,
    save_student_request_edit,
)
from tests.storage_mp1_pg_support import PG_URL, Registry, adapter
from tests.storage_mp1_support import REQUEST_ID, STUDENT_ID

pytestmark = pytest.mark.skipif(
    not PG_URL, reason="SGAA_PG_TEST_URL is not configured -- REAL-PG EVIDENCE: ABSENT"
)

PROCESSED = "2026-10-15 10:00:00"
REASON = "Falta o certificado assinado."


@pytest.fixture(scope="module")
def registry():
    registry = Registry("rect")
    try:
        registry.provision_template()
        yield registry
    finally:
        assert registry.close() == 0


@pytest.fixture
def conn(registry):
    name, url = registry.create(template=registry.template)
    connection = adapter(url)
    try:
        connection.execute(
            "UPDATE requisicoes SET status='Devolvida', data_processamento=?, observacao=?, admin_id=1,"
            " horas_deferidas=NULL, aluno_update_notified_at=? WHERE id=?",
            (PROCESSED, REASON, PROCESSED, REQUEST_ID),
        )
        connection.execute(
            "INSERT INTO requisicao_email_eventos(requisicao_id,aluno_id,destinatario_snapshot,status_decisao,"
            "horas_solicitadas,justificativa,atividade_nome,data_solicitacao,decidido_em,estado)"
            " VALUES(?,?,'aluno@example.test','Indeferida',2,'Antes da devolução.','Atividade',?,?,'pending')",
            (REQUEST_ID, STUDENT_ID, PROCESSED, PROCESSED),
        )
        connection.commit()
        yield connection
    finally:
        connection.close()
        registry.drop(name)


def _row(conn):
    return dict(conn.execute("SELECT * FROM requisicoes WHERE id=?", (REQUEST_ID,)).fetchone())


def test_resubmission_resets_the_request_and_supersedes_the_pending_decision(conn):
    with write_transaction(conn):
        resubmitted = save_student_request_edit(
            conn, request_id=REQUEST_ID, aluno_id=STUDENT_ID, status="Devolvida",
            data_processamento=PROCESSED, stored_observacao=REASON,
            edit=StudentRequestEdit(nome_evento="Corrigido", horas_solicitadas=3.0,
                                    data_evento="2026-09-10", observacao="Segue o certificado."),
        )
    assert resubmitted is True
    row = _row(conn)
    assert (row["status"], row["data_processamento"], row["admin_id"], row["horas_deferidas"]) == (
        "Pendente", None, None, None)
    assert (row["aluno_update_notified_at"], row["aluno_update_seen_at"]) == (None, None)
    assert (row["nome_evento"], float(row["horas_solicitadas"]), row["data_evento"]) == (
        "Corrigido", 3.0, "2026-09-10")
    assert row["observacao"] == f"[Motivo da devolução: {REASON}]\nSegue o certificado."
    assert [tuple(r) for r in conn.execute(
        "SELECT estado FROM requisicao_email_eventos WHERE requisicao_id=?", (REQUEST_ID,))] == [("superseded",)]
    conn.commit()


@pytest.mark.parametrize("change", [
    "UPDATE requisicoes SET status='Indeferida' WHERE id=?",
    "UPDATE requisicoes SET data_processamento='2026-10-16 09:00:00' WHERE id=?",
])
def test_a_request_that_moved_after_the_check_is_refused_and_untouched(conn, change):
    conn.execute(change, (REQUEST_ID,))
    conn.commit()
    before = _row(conn)
    with pytest.raises(StudentEditConflict):
        with write_transaction(conn):
            save_student_request_edit(
                conn, request_id=REQUEST_ID, aluno_id=STUDENT_ID, status="Devolvida",
                data_processamento=PROCESSED, stored_observacao=REASON,
                edit=StudentRequestEdit(nome_evento="tarde demais"),
            )
    assert _row(conn) == before
    assert [tuple(r) for r in conn.execute(
        "SELECT estado FROM requisicao_email_eventos WHERE requisicao_id=?", (REQUEST_ID,))] == [("pending",)]
