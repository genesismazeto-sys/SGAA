"""UI-C20: processing a requisição never erases the stored observação by omission.

``admin_processar_requisicao`` always wrote ``observacao = request.form.get(...)``.
The Requisições modal sends ``observacao`` only when its justificativa is
non-empty, so every Deferir, Encerrar and Reabrir wrote NULL over whatever was
stored -- the student's own note, a student reply after Devolvida, or an earlier
admin justification. There is one column (no separate admin note): the student
forms edit it, the modal's justificativa replaces it, the full-page processing
form always submits it prefilled, and a final decision snapshots it.

Contract now (the UI-C09 / UI-C19 three states):
* field **missing**   -> the stored observação is preserved (column not written);
* field **empty**     -> explicit clear (the full-page form can submit it empty);
* field **with text** -> replaced (the modal's justificativa, as before).

Status, hours, processing date, admin, validations, permissions, notification
events and their atomic commit are unchanged.
"""

from __future__ import annotations

import uuid

import pytest

import main
from app.request_email_render import render_request_block
from app.user_accounts import create_usuario_with_access_level
from tests.canonical_request_test_support import create_admin_request, login_admin, login_student
from tests.session_support import stamp_auth_version
from tests.versioned_test_support import isolated_versioned_app_env

ORIGINAL = "Texto original"


@pytest.fixture
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "ui-c20.db") as environment:
        client = environment["client"]
        login_admin(client)
        _response, created = create_admin_request(client, name=f"C20 {uuid.uuid4().hex[:6]}")
        _set(created["id"], observacao=ORIGINAL)
        yield client, created["id"]


def _set(req_id: int, **values) -> None:
    with main.app.app_context():
        conn = main.get_db_connection()
        for column, value in values.items():
            conn.execute(f"UPDATE requisicoes SET {column}=? WHERE id=?", (value, req_id))
        conn.commit()


def _row(req_id: int) -> dict:
    with main.app.app_context():
        return dict(main.get_db_connection().execute(
            "SELECT status, observacao, horas_deferidas, data_processamento, admin_id FROM requisicoes WHERE id=?",
            (req_id,),
        ).fetchone())


def _all_rows() -> list[tuple]:
    with main.app.app_context():
        conn = main.get_db_connection()
        return [tuple(r) for r in conn.execute("SELECT * FROM requisicoes ORDER BY id")] + [
            tuple(r) for r in conn.execute("SELECT * FROM requisicao_email_eventos ORDER BY id")
        ]


def _process(client, req_id: int, **fields):
    return client.post(f"/admin/processar_requisicao/{req_id}", data=fields, follow_redirects=False)


# ------------------------------------------------ missing: status-only actions preserve


@pytest.mark.parametrize(
    "action, before, status",
    [("deferir", "Pendente", "Deferida"), ("encerrar", "Pendente", "Encerrada"), ("reabrir", "Deferida", "Pendente")],
)
def test_status_only_modal_actions_keep_the_stored_observacao(env, action, before, status):
    client, req_id = env
    _set(req_id, status=before)
    # Exactly the modal payload for this action: `status` and nothing else.
    response = _process(client, req_id, status=status)
    assert response.status_code == 302 and response.headers["Location"].endswith("/admin/requisicoes")
    row = _row(req_id)
    assert row["status"] == status, action
    assert row["observacao"] == ORIGINAL, action


def test_status_only_decision_keeps_the_note_out_of_the_email_justification(env):
    client, req_id = env
    assert _process(client, req_id, status="Deferida").status_code == 302
    with main.app.app_context():
        event = main.get_db_connection().execute(
            "SELECT * FROM requisicao_email_eventos WHERE requisicao_id=? AND estado='pending'", (req_id,)
        ).fetchone()
    assert event is not None and event["status_decisao"] == "Deferida"
    block = render_request_block([event])
    assert "Justificativa" not in block and ORIGINAL not in block


def test_the_student_still_sees_the_observacao_after_status_only_processing(env):
    client, req_id = env
    assert _process(client, req_id, status="Deferida").status_code == 302
    with client.session_transaction() as session:
        session.clear()
    login_student(client)
    page = client.get(f"/aluno/requisicoes/{req_id}").get_data(as_text=True)
    assert ORIGINAL in page


# ------------------------------------------------ present: empty clears, text replaces


def test_submitted_empty_observacao_is_an_explicit_clear(env):
    client, req_id = env
    assert _process(client, req_id, status="Encerrada", observacao="").status_code == 302
    row = _row(req_id)
    assert row["status"] == "Encerrada" and row["observacao"] in ("", None)


@pytest.mark.parametrize("status", ["Indeferida", "Devolvida", "Deferida"])
def test_submitted_text_replaces_the_observacao(env, status):
    client, req_id = env
    assert _process(client, req_id, status=status, observacao="Novo texto").status_code == 302
    row = _row(req_id)
    assert row["status"] == status and row["observacao"] == "Novo texto"


def test_partial_approval_with_justification_replaces_it_and_keeps_the_hours(env):
    client, req_id = env
    response = _process(client, req_id, status="Deferida Parcialmente", horas_deferidas="2", observacao="Parcial")
    assert response.status_code == 302
    row = _row(req_id)
    assert (row["status"], row["horas_deferidas"], row["observacao"]) == ("Deferida Parcialmente", 2.0, "Parcial")


# ------------------------------------------------ refusals write nothing


def test_view_only_user_cannot_process(env):
    client, req_id = env
    token = uuid.uuid4().hex[:8]
    with main.app.app_context():
        conn = main.get_db_connection()
        uid = int(create_usuario_with_access_level(
            conn, f"C20 viewer {token}", f"c20-viewer-{token}@example.invalid",
            main.hash_password("c20"), "admin", "consultivo", credential_state="personal",
        ).lastrowid)
        conn.commit()
    with client.session_transaction() as session:
        session.clear()
        session.update(user_id=uid, user_type="admin", user_name="C20 viewer")
        stamp_auth_version(session, uid)
    before = _all_rows()
    for fields in ({"status": "Deferida"}, {"status": "Encerrada", "observacao": ""}, {"status": "Indeferida", "observacao": "X"}):
        response = _process(client, req_id, **fields)
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/admin/dashboard")
    assert _all_rows() == before


@pytest.mark.parametrize(
    "fields",
    [
        {"status": "Aprovada"},
        {"status": "Deferida Parcialmente"},
        {"status": "Deferida Parcialmente", "horas_deferidas": "abc"},
        {"status": "Deferida Parcialmente", "horas_deferidas": "-1"},
    ],
)
@pytest.mark.parametrize("observacao", [None, "", "Não deve gravar"])
def test_a_refused_transition_changes_neither_status_nor_observacao(env, fields, observacao):
    client, req_id = env
    payload = dict(fields)
    if observacao is not None:
        payload["observacao"] = observacao
    before = _all_rows()
    response = _process(client, req_id, **payload)
    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/admin/processar_requisicao/{req_id}")
    assert _all_rows() == before
    assert _row(req_id)["observacao"] == ORIGINAL


def test_the_modal_still_omits_observacao_only_for_status_only_actions():
    """The client half of the contract: omission is how Deferir/Encerrar/Reabrir submit."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "templates" / "admin_requisicoes.html").read_text(encoding="utf-8")
    assert "if (j) params.set('observacao', j);" in source
    assert "if (status === 'Indeferida' || status === 'Deferida Parcialmente'){" in source
    assert "if (status === 'Devolvida' && !j){ preparePanelFor('indeferir'); return; }" in source
