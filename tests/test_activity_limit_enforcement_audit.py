"""Activity-limit enforcement audit (final review, item 1).

Evidence only: this module pins where SGAA enforces an activity's semester /
total limit today and where it does not. It changes no rule. The canonical
authority is ``app/versioning/request_limits.py``; the only caller that
refuses an over-limit request is ``admin_processar_requisicao`` (the
standalone page and the Requisições modal both POST to it).

Matrix 1 fixture rules (frozen into each request's snapshot):
  version 3 -- Participação em eventos técnico-científicos, 20h per semester
  version 2 -- Visitas técnicas ou culturais, 100h in total
  version 4 -- Monitoria acadêmica supervisionada, no limit
"""
from __future__ import annotations

import io

import openpyxl
import pytest

import main
from tests.canonical_request_test_support import login_admin
from tests.test_atividade_limits_canonical import (
    _approve_direct,
    _create_request,
    _current_semester_date,
    _login_student,
    _other_past_semester_date,
    _process,
    _status,
    _student_in_matrix1,
)
from tests.versioned_test_support import isolated_versioned_app_env

SEMESTER_V, TOTAL_V, FREE_V = 3, 2, 4


@pytest.fixture()
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "limit-audit.db") as value:
        login_admin(value["client"])
        yield value


def _row(nome):
    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT * FROM requisicoes WHERE nome_evento=?", (nome,)
        ).fetchone()
    return dict(row) if row else None


def _student_submit(client, student, version_id, nome, data_evento, horas):
    _login_student(client, student["usuario_id"])
    response = client.post("/aluno/nova-requisicao", data={
        "atividade_versao_id": str(version_id), "nome_evento": nome,
        "data_evento": data_evento, "horas_solicitadas": str(horas),
    })
    login_admin(client)
    return response


def _flash_after(response, client):
    assert response.status_code == 302
    return client.get(response.headers["Location"]).get_data(as_text=True)


# ------------------------------------------------- student creation / editing


def test_student_creation_accepts_an_over_semester_limit_request_as_pendente(env):
    client, student = env["client"], _student_in_matrix1()
    today = _current_semester_date()
    _approve_direct(_create_request(client, student["aluno_id"], SEMESTER_V, "Hist 15h", today, 15)["id"])

    # 15h already approved in the event's semester + 10h requested > 20h limit,
    # and a single 25h request alone exceeds it: both are stored, no refusal.
    for nome, horas in (("Over sem 10h", 10), ("Over sem 25h", 25)):
        response = _student_submit(client, student, SEMESTER_V, nome, today, horas)
        assert response.status_code == 302 and response.headers["Location"].endswith("/aluno/dashboard")
        row = _row(nome)
        assert row["status"] == "Pendente" and row["horas_solicitadas"] == horas


def test_student_creation_accepts_an_over_total_limit_request_as_pendente(env):
    client, student = env["client"], _student_in_matrix1()
    _approve_direct(_create_request(
        client, student["aluno_id"], TOTAL_V, "Hist 95h", _other_past_semester_date(), 95)["id"])
    response = _student_submit(client, student, TOTAL_V, "Over total", _current_semester_date(), 20)
    assert response.status_code == 302
    assert _row("Over total")["status"] == "Pendente"


def test_student_edit_can_raise_hours_past_the_limit(env):
    client, student = env["client"], _student_in_matrix1()
    today = _current_semester_date()
    _student_submit(client, student, SEMESTER_V, "Edit me", today, 5)
    row = _row("Edit me")
    _login_student(client, student["usuario_id"])
    response = client.post(f"/aluno/requisicoes/{row['id']}", data={
        "nome_evento": "Edit me", "data_evento": today, "horas_solicitadas": "50",
    })
    assert response.status_code == 302
    edited = _row("Edit me")
    assert edited["horas_solicitadas"] == 50 and edited["status"] == "Pendente"


def test_student_may_submit_for_a_semester_that_has_already_ended(env):
    client, student = env["client"], _student_in_matrix1()
    past = _other_past_semester_date()
    _approve_direct(_create_request(client, student["aluno_id"], SEMESTER_V, "Past full", past, 20)["id"])
    response = _student_submit(client, student, SEMESTER_V, "Late past", past, 5)
    assert response.status_code == 302
    late = _row("Late past")
    assert late["status"] == "Pendente" and late["data_evento"] == past
    assert late["data_solicitacao"][:10] > past  # submitted after that semester
    # The deferment guard counts it against the EVENT semester (already full).
    _process(client, late["id"])
    assert _status(late["id"]) == "Pendente"
    current = _create_request(client, student["aluno_id"], SEMESTER_V, "Now ok", _current_semester_date(), 5)
    _process(client, current["id"])
    assert _status(current["id"]) == "Deferida"


def test_admin_creation_also_accepts_an_over_limit_request_as_pendente(env):
    client, student = env["client"], _student_in_matrix1()
    row = _create_request(client, student["aluno_id"], SEMESTER_V, "Admin 30h", _current_semester_date(), 30)
    assert row["status"] == "Pendente" and row["horas_solicitadas"] == 30


# ------------------------------------------------------- admin deferment guard


def test_deferment_counts_partial_hours_toward_the_total_limit(env):
    client, student = env["client"], _student_in_matrix1()
    today = _current_semester_date()
    first = _create_request(client, student["aluno_id"], TOTAL_V, "Tot first", today, 80)
    _process(client, first["id"], status="Deferida Parcialmente", horas=60)
    assert _status(first["id"]) == "Deferida Parcialmente"

    second = _create_request(client, student["aluno_id"], TOTAL_V, "Tot second", today, 50)
    page = _flash_after(_process(client, second["id"]), client)
    assert _status(second["id"]) == "Pendente"  # 60 partial + 50 > 100
    assert "Limite total: 100.0h" in page and "Máximo a deferir agora: 40.0h" in page

    # Reaching the limit exactly is allowed (the guard refuses only "> limit").
    _process(client, second["id"], status="Deferida Parcialmente", horas=40)
    assert _status(second["id"]) == "Deferida Parcialmente"
    third = _create_request(client, student["aluno_id"], TOTAL_V, "Tot third", today, 1)
    _process(client, third["id"])
    assert _status(third["id"]) == "Pendente"


def test_deferment_semester_limit_counts_full_and_partial_approvals(env):
    client, student = env["client"], _student_in_matrix1()
    today = _current_semester_date()
    full = _create_request(client, student["aluno_id"], SEMESTER_V, "Sem full", today, 10)
    _process(client, full["id"])
    partial = _create_request(client, student["aluno_id"], SEMESTER_V, "Sem partial", today, 10)
    _process(client, partial["id"], status="Deferida Parcialmente", horas=6)
    assert (_status(full["id"]), _status(partial["id"])) == ("Deferida", "Deferida Parcialmente")

    over = _create_request(client, student["aluno_id"], SEMESTER_V, "Sem over", today, 5)
    page = _flash_after(_process(client, over["id"]), client)
    assert _status(over["id"]) == "Pendente"  # 16 + 5 > 20
    assert "Limite semestral: 20.0h" in page and "Máximo agora: 4.0h" in page
    _process(client, over["id"], status="Deferida Parcialmente", horas=4)
    assert _status(over["id"]) == "Deferida Parcialmente"


def test_pending_requests_reserve_no_capacity(env):
    client, student = env["client"], _student_in_matrix1()
    today = _current_semester_date()
    a = _create_request(client, student["aluno_id"], SEMESTER_V, "Pend A", today, 15)
    b = _create_request(client, student["aluno_id"], SEMESTER_V, "Pend B", today, 15)
    assert (_status(a["id"]), _status(b["id"])) == ("Pendente", "Pendente")
    _process(client, a["id"])
    _process(client, b["id"])
    assert (_status(a["id"]), _status(b["id"])) == ("Deferida", "Pendente")


def test_activity_without_limits_is_never_refused(env):
    client, student = env["client"], _student_in_matrix1()
    today = _current_semester_date()
    for nome in ("Free 1", "Free 2"):
        row = _create_request(client, student["aluno_id"], FREE_V, nome, today, 500)
        _process(client, row["id"])
        assert _status(row["id"]) == "Deferida"


def test_rejection_is_never_limited(env):
    client, student = env["client"], _student_in_matrix1()
    today = _current_semester_date()
    _approve_direct(_create_request(client, student["aluno_id"], SEMESTER_V, "Fill", today, 20)["id"])
    row = _create_request(client, student["aluno_id"], SEMESTER_V, "Reject me", today, 5)
    _process(client, row["id"], status="Indeferida")
    assert _status(row["id"]) == "Indeferida"


def test_modal_post_reaches_the_same_guard_and_lands_on_the_standalone_page(env):
    """The modal's Confirmar sends exactly this request (admin_requisicoes.html,
    executeConfirmedAction): urlencoded status, X-CSRFToken header, no
    observacao for Deferir. A refusal redirects to the standalone page, which
    the modal follows (res.redirected) and where the flash is shown."""
    client, student = env["client"], _student_in_matrix1()
    today = _current_semester_date()
    _approve_direct(_create_request(client, student["aluno_id"], SEMESTER_V, "Modal fill", today, 18)["id"])
    row = _create_request(client, student["aluno_id"], SEMESTER_V, "Modal over", today, 5)
    headers = {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8", "X-CSRFToken": "x"}

    refused = client.post(f"/admin/processar_requisicao/{row['id']}", data="status=Deferida", headers=headers)
    assert refused.status_code == 302
    assert refused.headers["Location"].endswith(f"/admin/processar_requisicao/{row['id']}")
    assert "Limite semestral: 20.0h" in client.get(refused.headers["Location"]).get_data(as_text=True)
    assert _status(row["id"]) == "Pendente"

    accepted = client.post(f"/admin/processar_requisicao/{row['id']}",
                           data="status=Deferida+Parcialmente&horas_deferidas=2&observacao=ok", headers=headers)
    assert accepted.headers["Location"].endswith("/admin/requisicoes")
    assert _status(row["id"]) == "Deferida Parcialmente"


# --------------------------------------------------------- spreadsheet import


def test_spreadsheet_import_writes_approved_rows_without_the_limit_guard(env):
    client, student = env["client"], _student_in_matrix1()
    today = _current_semester_date()
    with main.app.app_context():
        nome = main.get_db_connection().execute(
            "SELECT b.nome_conceito FROM atividade_versao v JOIN atividade_base b"
            " ON b.id=v.atividade_base_id WHERE v.id=?", (SEMESTER_V,)
        ).fetchone()[0]
    with main.app.app_context():
        matricula = main.get_db_connection().execute(
            "SELECT matricula FROM alunos WHERE id=?", (student["aluno_id"],)
        ).fetchone()[0]
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Requisições"
    sheet.append(["Matrícula"] + [""] * 8)
    sheet.append(["header"] + [""] * 8)
    sheet.append([matricula, "", "", "", "", nome, 50, today, "Deferido"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    response = client.post("/admin/importar_requisicoes",
                           data={"arquivo_excel": (buffer, "audit.xlsx")},
                           content_type="multipart/form-data")
    assert response.status_code in (200, 302)
    with main.app.app_context():
        imported = main.get_db_connection().execute(
            "SELECT status, horas_solicitadas, horas_deferidas FROM requisicoes"
            " WHERE aluno_id=? AND observacao LIKE 'Importado da planilha%'", (student["aluno_id"],)
        ).fetchall()
    # 50h approved against a 20h semester limit, with no refusal.
    assert [tuple(r) for r in imported] == [("Deferida", 50.0, 50.0)]
