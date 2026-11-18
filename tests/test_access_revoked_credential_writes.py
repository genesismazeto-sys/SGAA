"""Administrative credential writes refuse a revoked access, all or nothing.

A revoked login keeps no usable credential (app/views/admin/acesso.py
``_revoke_usuario_access``). These are the administrative paths that write a
password into an account chosen by id; each must refuse a revoked one before
writing anything, and a selection containing one must leave every selected
account untouched. Reactivation stays the explicit Novo acesso path.

Fictitious accounts in an isolated database only.
"""
from __future__ import annotations

import pytest

import main
from app.user_accounts import create_usuario_with_access_level, set_usuario_access_active
from tests.canonical_matrix_test_support import login_admin
from tests.versioned_test_support import isolated_versioned_app_env

REVOKED_SINGLE = "Este acesso está revogado. Reative-o antes de definir uma senha."
REVOKED_BATCH = "Um ou mais acessos selecionados estão revogados. Nenhuma senha foi alterada."
AJAX = {"X-Requested-With": "XMLHttpRequest"}


def _account(conn, nome, email, *, user_type="admin", level="consultivo"):
    return int(create_usuario_with_access_level(
        conn, nome, email, "fixture-hash", user_type, level, credential_state="personal",
    ).lastrowid)


@pytest.fixture
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "revoked-credentials.db") as environment:
        with main.app.app_context():
            conn = main.get_db_connection()
            ids = {
                "ativo_a": _account(conn, "Cred Ativo A", "cred.a@example.test"),
                "ativo_b": _account(conn, "Cred Ativo B", "cred.b@example.test"),
                "revogado": _account(conn, "Cred Revogado", "cred.r@example.test"),
            }
            set_usuario_access_active(conn, ids["revogado"], False)
            conn.commit()
        login_admin(environment["client"])
        yield {**environment, "ids": ids}


def _credentials(ids):
    """Everything a password write could change, per account."""
    with main.app.app_context():
        conn = main.get_db_connection()
        state = {}
        for usuario_id in ids:
            row = conn.execute(
                "SELECT u.nome, u.senha, c.estado, c.auth_version, c.acesso_ativo"
                " FROM usuarios u LEFT JOIN usuario_credenciais c ON c.usuario_id = u.id"
                " WHERE u.id = ?",
                (usuario_id,),
            ).fetchone()
            tokens = conn.execute(
                "SELECT COUNT(*), COUNT(invalidated_at) FROM senha_tokens WHERE usuario_id = ?",
                (usuario_id,),
            ).fetchone()
            state[usuario_id] = (tuple(row), tuple(tokens))
        return state


def _flashes(client):
    with client.session_transaction() as session:
        return [message for _category, message in session.pop("_flashes", [])]


# --------------------------------------------------------------------------
# Nova senha (admin_acesso_definir_senha): a selection, all or nothing
# --------------------------------------------------------------------------


def test_a_selection_holding_a_revoked_account_changes_nobody(env):
    ids = env["ids"]
    selection = [ids["ativo_a"], ids["revogado"], ids["ativo_b"]]
    before = _credentials(selection)
    response = env["client"].post(
        "/admin/acesso/definir-senha",
        data={"usuario_ids": [str(value) for value in selection], "nova_senha": "Fixture#2026"},
        headers=AJAX,
    )
    assert response.status_code == 409
    assert response.json == {"ok": False, "error": "revoked", "revoked_ids": [ids["revogado"]]}
    assert _credentials(selection) == before


def test_the_form_path_refuses_with_its_message_and_writes_nothing(env):
    ids = env["ids"]
    selection = [ids["ativo_a"], ids["revogado"]]
    before = _credentials(selection)
    response = env["client"].post(
        "/admin/acesso/definir-senha",
        data={"usuario_ids": [str(value) for value in selection], "nova_senha": "Fixture#2026"},
    )
    assert response.status_code == 302
    assert _flashes(env["client"]) == [REVOKED_BATCH]
    assert _credentials(selection) == before


def test_an_all_active_selection_is_still_written_in_one_operation(env):
    ids = env["ids"]
    selection = [ids["ativo_a"], ids["ativo_b"]]
    before = _credentials(selection)
    response = env["client"].post(
        "/admin/acesso/definir-senha",
        data={"usuario_ids": [str(value) for value in selection], "nova_senha": "Fixture#2026"},
        headers=AJAX,
    )
    assert response.status_code == 200 and response.json == {"ok": True, "updated": 2}
    after = _credentials(selection)
    for usuario_id in selection:
        (nome, senha, estado, auth_version, ativo), _tokens = after[usuario_id]
        assert senha != before[usuario_id][0][1] and estado == "personal" and ativo == 1
        assert auth_version == before[usuario_id][0][3] + 1
        with main.app.app_context():
            assert main.check_password(senha, "Fixture#2026")


def test_an_account_without_a_credential_row_is_not_treated_as_revoked(env):
    # The fixture's base student has no usuario_credenciais row: the access
    # lifecycle reads it as Pendente, and a password write completes it, as
    # before. Only Revogado is refused.
    response = env["client"].post(
        "/admin/acesso/definir-senha",
        data={"usuario_ids": ["2"], "nova_senha": "Fixture#2026"},
        headers=AJAX,
    )
    assert response.status_code == 200 and response.json["ok"] is True


def test_a_missing_account_is_still_reported_before_revocation(env):
    ids = env["ids"]
    response = env["client"].post(
        "/admin/acesso/definir-senha",
        data={"usuario_ids": [str(ids["revogado"]), "999999"], "nova_senha": "Fixture#2026"},
        headers=AJAX,
    )
    assert response.status_code == 404 and response.json["missing_ids"] == [999999]


# --------------------------------------------------------------------------
# Edits that carry a password: Acesso form and Alunos form
# --------------------------------------------------------------------------


def test_acesso_edit_of_a_revoked_account_with_a_password_is_refused_whole(env):
    ids = env["ids"]
    before = _credentials([ids["revogado"]])
    response = env["client"].post("/admin/acesso/salvar", data={
        "usuario_id": str(ids["revogado"]), "nome": "Nome Trocado", "email": "cred.r@example.test",
        "nivel_acesso": "consultivo", "senha": "Fixture#2026",
    })
    assert response.status_code == 302
    assert _flashes(env["client"]) == [REVOKED_SINGLE]
    assert _credentials([ids["revogado"]]) == before  # not even the name changed


def test_reactivation_through_novo_acesso_still_works(env):
    ids = env["ids"]
    response = env["client"].post("/admin/acesso/salvar", data={
        "nome": "Cred Revogado", "email": "cred.r@example.test",
        "nivel_acesso": "consultivo", "senha": "Fixture#2026",
    })
    assert response.status_code == 302
    assert _flashes(env["client"]) == ["Acesso reativado e vinculado ao registro existente."]
    (_nome, senha, estado, _version, ativo), _tokens = _credentials([ids["revogado"]])[ids["revogado"]]
    assert ativo == 1 and estado == "personal"


def _revoked_student(env):
    client = env["client"]
    assert client.post("/admin/acesso/salvar", data={
        "nome": "Cred Aluno", "email": "cred.aluno@example.test", "nivel_acesso": "usuario",
        "matricula": "CRED-001", "status": "Ativo", "turma_id": "1", "senha": "Inicial#2026",
    }).status_code == 302
    with main.app.app_context():
        conn = main.get_db_connection()
        usuario_id = int(conn.execute("SELECT id FROM usuarios WHERE email='cred.aluno@example.test'").fetchone()[0])
    assert client.post(f"/admin/acesso/{usuario_id}/deletar").status_code == 302  # revocation
    _flashes(client)
    return usuario_id


def _student_form(**overrides):
    return {"nome": "Cred Aluno", "email": "cred.aluno@example.test", "matricula": "CRED-001",
            "turma_id": "1", "status": "Ativo", **overrides}


def test_alunos_edit_refuses_a_password_for_a_revoked_student_and_writes_nothing(env):
    usuario_id = _revoked_student(env)
    before = _credentials([usuario_id])
    response = env["client"].post(
        f"/admin/editar_aluno/{usuario_id}",
        data=_student_form(nome="Nome Trocado", senha="Fixture#2026"),
    )
    assert response.status_code == 200  # the edit form again, as every refusal there
    assert REVOKED_SINGLE in response.get_data(as_text=True)  # rendered with the form
    assert _credentials([usuario_id]) == before
    with main.app.app_context():
        conn = main.get_db_connection()
        assert conn.execute("SELECT nome FROM alunos WHERE usuario_id=?", (usuario_id,)).fetchone()[0] == "Cred Aluno"


def test_alunos_edit_without_a_password_still_saves_a_revoked_student(env):
    # The academic record outlives the login: editing it stays allowed, it
    # just never writes a credential.
    usuario_id = _revoked_student(env)
    before = _credentials([usuario_id])
    response = env["client"].post(f"/admin/editar_aluno/{usuario_id}", data=_student_form(nome="Cred Aluno Novo"))
    assert response.status_code == 302
    after = _credentials([usuario_id])
    assert after[usuario_id][0][1:] == before[usuario_id][0][1:]  # senha, estado, version, ativo
    assert after[usuario_id][0][0] == "Cred Aluno Novo"


def test_alunos_edit_with_a_password_for_an_active_student_is_unchanged(env):
    client = env["client"]
    assert client.post("/admin/acesso/salvar", data={
        "nome": "Cred Aluno Ativo", "email": "cred.ativo@example.test", "nivel_acesso": "usuario",
        "matricula": "CRED-002", "status": "Ativo", "turma_id": "1", "senha": "Inicial#2026",
    }).status_code == 302
    with main.app.app_context():
        conn = main.get_db_connection()
        usuario_id = int(conn.execute("SELECT id FROM usuarios WHERE email='cred.ativo@example.test'").fetchone()[0])
    response = client.post(f"/admin/editar_aluno/{usuario_id}", data={
        "nome": "Cred Aluno Ativo", "email": "cred.ativo@example.test", "matricula": "CRED-002",
        "turma_id": "1", "status": "Ativo", "senha": "Nova#2026",
    })
    assert response.status_code == 302
    with main.app.app_context():
        conn = main.get_db_connection()
        senha = conn.execute("SELECT senha FROM usuarios WHERE id=?", (usuario_id,)).fetchone()[0]
        assert main.check_password(senha, "Nova#2026")
