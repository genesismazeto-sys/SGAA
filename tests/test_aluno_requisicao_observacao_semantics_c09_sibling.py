"""UI-C09 sibling: the student's own requisition edit keeps an omitted observação.

``aluno_requisicao_detalhe`` (POST ``/aluno/requisicoes/<id>``) read
``observacao = request.form.get("observacao")`` and always wrote it, so a valid
edit that omitted the field erased the stored observação -- the anti-pattern
UI-C09 removed from ``admin_editar_requisicao``. Both student forms that post
here (the edit page and the Pendente detail form) always submit the textarea,
so the normal UI is unaffected; the repair only closes the omission path.

Contract (three states, as in UI-C09):
* field **missing**   -> the stored observação is preserved;
* field **empty**     -> explicit clear (stored empty, as before);
* field **with text** -> replaced.

Ownership, the Pendente/Devolvida edit window and the snapshot activity lock
still refuse before anything is written.
"""

from __future__ import annotations

import uuid

import pytest

import main
from app.user_accounts import create_usuario_with_access_level
from tests.canonical_request_test_support import create_admin_request, login_admin, login_student
from tests.session_support import stamp_auth_version
from tests.versioned_test_support import isolated_versioned_app_env


@pytest.fixture
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "ui-c09-aluno.db") as environment:
        client = environment["client"]
        login_admin(client)
        _response, created = create_admin_request(client, name=f"C09 aluno {uuid.uuid4().hex[:6]}")
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute("UPDATE requisicoes SET observacao='OBS ALUNO' WHERE id=?", (created["id"],))
            conn.commit()
        with client.session_transaction() as session:
            session.clear()
        login_student(client)
        yield client, created["id"]


def _row(req_id: int) -> dict:
    with main.app.app_context():
        return dict(main.get_db_connection().execute(
            "SELECT nome_evento,horas_solicitadas,data_evento,observacao FROM requisicoes WHERE id=?",
            (req_id,),
        ).fetchone())


def _all_rows() -> list[tuple]:
    with main.app.app_context():
        return [tuple(r) for r in main.get_db_connection().execute("SELECT * FROM requisicoes ORDER BY id")]


def _post(client, req_id: int, **fields):
    return client.post(f"/aluno/requisicoes/{req_id}", data=fields, follow_redirects=False)


# ------------------------------------------------------------------ states


def test_omitted_observacao_is_preserved_and_other_fields_still_update(env):
    client, req_id = env
    response = _post(client, req_id, nome_evento="Evento aluno C09", horas_solicitadas="6", data_evento="2026-07-02")
    assert response.status_code == 302
    assert _row(req_id) == {
        "nome_evento": "Evento aluno C09", "horas_solicitadas": 6.0,
        "data_evento": "2026-07-02", "observacao": "OBS ALUNO",
    }


def test_a_post_with_nothing_but_uploads_metadata_keeps_the_observacao(env):
    client, req_id = env
    before = _row(req_id)
    assert _post(client, req_id, comprovantes_operation_id=uuid.uuid4().hex).status_code == 302
    assert _row(req_id) == before


def test_submitted_empty_observacao_is_an_explicit_clear(env):
    client, req_id = env
    assert _post(client, req_id, observacao="").status_code == 302
    assert _row(req_id)["observacao"] in ("", None)


def test_submitted_text_replaces_the_observacao(env):
    client, req_id = env
    assert _post(client, req_id, observacao="Nova observação do aluno").status_code == 302
    assert _row(req_id)["observacao"] == "Nova observação do aluno"


def test_the_normal_edit_form_always_submits_the_observacao(env):
    client, req_id = env
    html = client.get(f"/aluno/requisicoes/{req_id}?edit=1").get_data(as_text=True)
    form = html.split('<form method="post"', 1)[1].split("</form>", 1)[0]
    assert 'name="observacao"' in form
    textarea = form.split('name="observacao"', 1)[0].rsplit("<", 1)[1]
    assert textarea.startswith("textarea") and "disabled" not in textarea


# ------------------------------------------------------- refusals write nothing


def test_another_student_writes_nothing(env):
    client, req_id = env
    token = uuid.uuid4().hex[:6]
    with main.app.app_context():
        conn = main.get_db_connection()
        turma_id = conn.execute("SELECT turma_id FROM alunos WHERE matricula='PPA.TESTE.0001'").fetchone()[0]
        uid = int(create_usuario_with_access_level(
            conn, f"Outro aluno {token}", f"c09-outro-{token}@example.invalid",
            main.hash_password("outro"), "aluno", "usuario", credential_state="personal",
        ).lastrowid)
        conn.execute(
            "INSERT INTO alunos(usuario_id,nome,matricula,email,turma_id,matriz_id,status) VALUES (?,?,?,?,?,NULL,'Ativo')",
            (uid, f"Outro aluno {token}", f"C09-{token}", f"c09-outro-{token}@example.invalid", turma_id),
        )
        conn.commit()
    with client.session_transaction() as session:
        session.clear()
        session.update(user_id=uid, user_type="aluno", user_name="Outro aluno")
        stamp_auth_version(session, uid)
    before = _all_rows()
    assert _post(client, req_id, observacao="", nome_evento="invasão").status_code == 302
    assert _all_rows() == before


def test_outside_the_edit_window_writes_nothing(env):
    client, req_id = env
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("UPDATE requisicoes SET status='Deferida', data_processamento='2026-01-01' WHERE id=?", (req_id,))
        conn.commit()
    before = _all_rows()
    assert _post(client, req_id, observacao="", nome_evento="fora da janela").status_code == 302
    assert _all_rows() == before


def test_refused_activity_change_writes_nothing(env):
    client, req_id = env
    before = _all_rows()
    response = _post(client, req_id, atividade_versao_id="30", observacao="", nome_evento="troca recusada")
    assert response.status_code == 302
    assert _all_rows() == before
