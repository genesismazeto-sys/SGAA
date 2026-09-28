"""UI-B13: "Meus dados" password field against the v11 credential model.

Contract (both ``/admin/meus_dados`` and ``/aluno/meus_dados``):

* **blank** password -> a true no-op for credentials: the password hash,
  ``estado``, ``auth_version``, ``acesso_ativo``, every first-access /
  password-reset token and the current session all stay as they were; only the
  profile fields are written. So "Deixe em branco para manter" is truthful.
* **new** password -> the shared credential service
  (``set_usuario_password_hash``): new hash, ``estado='personal'``,
  ``auth_version`` + 1 (other sessions end), active tokens invalidated, the
  current session restamped, ``acesso_ativo`` untouched.
* root keeps its master key independently of its personal password.

Assertions read the database before and after. Only synthetic credentials.
"""

from __future__ import annotations

import uuid

import pytest

import main
from app.password_tokens import issue_password_token
from app.root_admin import resolve_root_admin_id, root_admin_email, verify_root_master_key
from app.security.passwords import check_password
from app.user_accounts import create_usuario_with_access_level, set_usuario_access_active
from tests.canonical_request_test_support import student_identity
from tests.root_admin_test_config import TEST_ROOT_MASTER_KEY
from tests.session_support import stamp_auth_version
from tests.versioned_test_support import isolated_versioned_app_env


@pytest.fixture
def env(tmp_path):
    import app.auth as auth

    auth._login_attempts.clear()
    auth._login_attempts_by_account.clear()
    try:
        with isolated_versioned_app_env(tmp_path, "ui-b13.db") as environment:
            yield environment["client"]
    finally:
        auth._login_attempts.clear()
        auth._login_attempts_by_account.clear()


def _admin(state: str) -> tuple[int, str]:
    token = uuid.uuid4().hex[:8]
    email = f"b13-{state}-{token}@example.invalid"
    with main.app.app_context():
        conn = main.get_db_connection()
        uid = int(create_usuario_with_access_level(
            conn, f"B13 {state} {token}", email, main.hash_password("senha-original"),
            "admin", "administrativo", credential_state=state,
        ).lastrowid)
        conn.commit()
    return uid, email


def _tokens(uid: int) -> None:
    with main.app.app_context():
        conn = main.get_db_connection()
        issue_password_token(conn, uid, "first_access")
        issue_password_token(conn, uid, "password_reset")
        conn.commit()


def _state(uid: int) -> dict:
    with main.app.app_context():
        conn = main.get_db_connection()
        user = conn.execute("SELECT nome, senha FROM usuarios WHERE id=?", (uid,)).fetchone()
        cred = conn.execute(
            "SELECT estado, auth_version, acesso_ativo FROM usuario_credenciais WHERE usuario_id=?", (uid,)
        ).fetchone()
        tokens = [tuple(r) for r in conn.execute(
            "SELECT id, purpose, consumed_at, invalidated_at FROM senha_tokens WHERE usuario_id=? ORDER BY id", (uid,)
        )]
    return {"nome": user["nome"], "senha": user["senha"], "estado": cred["estado"],
            "auth_version": cred["auth_version"], "acesso_ativo": cred["acesso_ativo"], "tokens": tokens}


def _login_session(client, uid: int, user_type: str = "admin") -> None:
    with client.session_transaction() as session:
        session.clear()
        session.update(user_id=uid, user_type=user_type, user_name="B13")
        stamp_auth_version(session, uid)


def _admin_post(client, email: str, senha: str, nome: str):
    return client.post("/admin/meus_dados", data={"nome": nome, "email": email, "senha": senha}, follow_redirects=False)


def _session_valid(client, path: str) -> bool:
    return client.get(path, follow_redirects=False).status_code == 200


# --------------------------------------------------------------------------
# Admin: blank is a no-op
# --------------------------------------------------------------------------


@pytest.mark.parametrize("state", ["personal", "default"])
def test_admin_blank_password_is_a_credential_no_op(env, state):
    uid, email = _admin(state)
    _tokens(uid)
    _login_session(env, uid)
    before = _state(uid)

    response = _admin_post(env, email, "", "Nome B13 alterado")
    assert response.status_code == 302
    after = _state(uid)

    assert after["nome"] == "Nome B13 alterado"
    for key in ("senha", "estado", "auth_version", "acesso_ativo", "tokens"):
        assert after[key] == before[key], key
    assert all(consumed is None and invalidated is None for _i, _p, consumed, invalidated in after["tokens"])
    assert _session_valid(env, "/admin/meus_dados")


def test_admin_omitted_password_field_is_also_a_no_op(env):
    uid, email = _admin("personal")
    _login_session(env, uid)
    before = _state(uid)
    env.post("/admin/meus_dados", data={"nome": "Sem campo senha", "email": email}, follow_redirects=False)
    after = _state(uid)
    assert {k: after[k] for k in ("senha", "estado", "auth_version")} == {k: before[k] for k in ("senha", "estado", "auth_version")}


# --------------------------------------------------------------------------
# Admin: new password goes through the shared credential service
# --------------------------------------------------------------------------


@pytest.mark.parametrize("state", ["personal", "default"])
def test_admin_new_password_becomes_personal_and_ends_other_sessions(env, state):
    uid, email = _admin(state)
    _tokens(uid)
    _login_session(env, uid)
    stale = main.app.test_client()
    _login_session(stale, uid)  # a second session stamped with the old auth_version
    before = _state(uid)

    response = _admin_post(env, email, "Nova-Senha-B13", "B13 nova senha")
    assert response.status_code == 302
    after = _state(uid)

    assert after["estado"] == "personal"
    assert after["auth_version"] == before["auth_version"] + 1
    assert after["senha"] != before["senha"] and check_password(after["senha"], "Nova-Senha-B13")
    assert after["acesso_ativo"] == before["acesso_ativo"] == 1
    assert all(invalidated is not None for _i, _p, _c, invalidated in after["tokens"])
    assert _session_valid(env, "/admin/meus_dados"), "the acting session is restamped"
    assert not _session_valid(stale, "/admin/meus_dados"), "other sessions end"


def test_revoked_account_cannot_reach_meus_dados_and_is_not_reactivated(env):
    uid, email = _admin("personal")
    _login_session(env, uid)
    with main.app.app_context():
        conn = main.get_db_connection()
        set_usuario_access_active(conn, uid, False)
        conn.commit()
    before = _state(uid)
    _admin_post(env, email, "Tentativa-B13", "Nao deve gravar")
    after = _state(uid)
    assert after == before
    assert after["acesso_ativo"] == 0


# --------------------------------------------------------------------------
# Root
# --------------------------------------------------------------------------


def _root_login(client) -> int:
    client.post("/login", data={"email": root_admin_email(), "senha": TEST_ROOT_MASTER_KEY}, follow_redirects=False)
    with client.session_transaction() as session:
        return session.get("user_id")


def test_root_blank_password_keeps_personal_state_and_master_key(env):
    with main.app.app_context():
        root_id = resolve_root_admin_id(main.get_db_connection())
    assert _root_login(env) == root_id
    before = _state(root_id)

    _admin_post(env, root_admin_email(), "", before["nome"])
    after = _state(root_id)

    for key in ("senha", "estado", "auth_version", "acesso_ativo", "tokens"):
        assert after[key] == before[key], key
    assert verify_root_master_key(TEST_ROOT_MASTER_KEY)
    with main.app.app_context():
        assert resolve_root_admin_id(main.get_db_connection()) == root_id


def test_root_new_personal_password_leaves_the_master_key_independent(env):
    with main.app.app_context():
        root_id = resolve_root_admin_id(main.get_db_connection())
    assert _root_login(env) == root_id
    before = _state(root_id)

    _admin_post(env, root_admin_email(), "Raiz-Pessoal-B13", before["nome"])
    after = _state(root_id)
    assert after["estado"] == "personal"
    assert after["auth_version"] == before["auth_version"] + 1

    fresh = main.app.test_client()
    assert _root_login(fresh) == root_id, "master key still authenticates root"
    personal = main.app.test_client()
    personal.post("/login", data={"email": root_admin_email(), "senha": "Raiz-Pessoal-B13"}, follow_redirects=False)
    with personal.session_transaction() as session:
        assert session.get("user_id") == root_id, "the new personal password works too"


# --------------------------------------------------------------------------
# Aluno
# --------------------------------------------------------------------------


def _aluno_post(client, senha: str):
    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT a.nome, a.matricula, a.email, a.turma_id FROM alunos a WHERE a.usuario_id=?",
            (student_identity()["usuario_id"],),
        ).fetchone()
    data = {"nome": row["nome"], "email": row["email"], "matricula": row["matricula"], "senha": senha}
    if row["turma_id"]:
        data["turma_id"] = str(row["turma_id"])
    return client.post("/aluno/meus_dados", data=data, follow_redirects=False)


def test_aluno_blank_password_is_a_no_op_and_new_password_uses_the_service(env):
    uid = int(student_identity()["usuario_id"])
    _tokens(uid)
    _login_session(env, uid, "aluno")
    before = _state(uid)

    _aluno_post(env, "")
    blank = _state(uid)
    for key in ("senha", "estado", "auth_version", "acesso_ativo", "tokens"):
        assert blank[key] == before[key], key

    _aluno_post(env, "Aluno-Nova-B13")
    changed = _state(uid)
    assert changed["estado"] == "personal"
    assert changed["auth_version"] == before["auth_version"] + 1
    assert check_password(changed["senha"], "Aluno-Nova-B13")
    assert all(invalidated is not None for _i, _p, _c, invalidated in changed["tokens"])
    assert changed["acesso_ativo"] == before["acesso_ativo"]
