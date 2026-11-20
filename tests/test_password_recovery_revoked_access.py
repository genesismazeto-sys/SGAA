"""A revoked access can neither receive a recovery link nor use an old one.

Covers the three layers: the public request (``app.password_recovery.recovery_account``), the
issuance (``issue_and_send_password_email`` rechecks under the account lock)
and the token itself (``resolve_password_token`` -- the link page and the
locked consumption). The public answer stays the same neutral message for an
active, a revoked and an unknown address. Fictitious accounts, isolated
database, simulated mail transport only.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

import pytest

import main
import app.password_email as password_email
from app.password_tokens import PURPOSE_FIRST_ACCESS, PURPOSE_PASSWORD_RESET, issue_password_token
from app.user_accounts import (
    create_usuario_pending,
    create_usuario_with_access_level,
    set_usuario_access_active,
)
from tests.canonical_matrix_test_support import login_admin
from tests.versioned_test_support import isolated_versioned_app_env

INVALID_LINK = "Este link é inválido, expirou ou já foi utilizado."
NEUTRAL = (
    "Se houver uma conta associada a este e-mail, enviaremos as instruções "
    "para redefinição da senha."
)


@pytest.fixture
def env(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(password_email, "password_email_status", lambda conn: {"ready": True})
    monkeypatch.setattr(password_email, "get_public_base_url", lambda: "https://sgaa.example.test")

    def fake_send(conn, message):
        assert message.to_address.endswith("@example.test"), "only fictitious recipients"
        sent.append(message)
        return {"ok": True}

    monkeypatch.setattr(password_email, "send_text_email", fake_send)
    with isolated_versioned_app_env(tmp_path, "recovery-revoked.db") as environment:
        with main.app.app_context():
            conn = main.get_db_connection()
            ids = {}
            for key in ("ativo", "revogado"):
                ids[key] = int(create_usuario_with_access_level(
                    conn, f"Rec {key}", f"rec.{key}@example.test", "fixture-hash", "admin",
                    "consultivo", credential_state="personal",
                ).lastrowid)
            set_usuario_access_active(conn, ids["revogado"], False)
            conn.commit()
        yield {**environment, "ids": ids, "sent": sent}


def _account(usuario_id):
    """Everything recovery could change, plus the academic record if any."""
    with main.app.app_context():
        conn = main.get_db_connection()
        row = conn.execute(
            "SELECT u.senha, c.estado, c.auth_version, c.acesso_ativo FROM usuarios u"
            " JOIN usuario_credenciais c ON c.usuario_id = u.id WHERE u.id = ?",
            (usuario_id,),
        ).fetchone()
        tokens = conn.execute(
            "SELECT id, purpose, consumed_at, invalidated_at FROM senha_tokens WHERE usuario_id = ? ORDER BY id",
            (usuario_id,),
        ).fetchall()
        aluno = conn.execute(
            "SELECT nome, matricula, turma_id, status FROM alunos WHERE usuario_id = ?", (usuario_id,)
        ).fetchone()
        return tuple(row), [tuple(t) for t in tokens], tuple(aluno) if aluno else None


def _request_recovery(client, email):
    return client.post("/esqueci-minha-senha", data={"email": email})


def _normalized(html, email):
    html = html.replace(email, "<email>")
    return re.sub(r'name="csrf_token" value="[^"]*"', 'name="csrf_token" value=""', html)


def _token_from(message):
    link = next(line for line in message.body_text.splitlines() if "token=" in line)
    return parse_qs(urlsplit(link.strip()).query)["token"][0]


def _issue(usuario_id, purpose):
    with main.app.app_context():
        conn = main.get_db_connection()
        raw_token, _token_id = issue_password_token(conn, usuario_id, purpose)
        conn.commit()
    return raw_token


def _submit(client, purpose, raw_token, password="Nova#2026"):
    path = "/redefinir-senha" if purpose == PURPOSE_PASSWORD_RESET else "/primeiro-acesso"
    return client.post(path, data={"token": raw_token, "senha": password, "confirmacao_senha": password})


def _page(client, purpose, raw_token):
    path = "/redefinir-senha" if purpose == PURPOSE_PASSWORD_RESET else "/primeiro-acesso"
    return client.get(f"{path}?token={raw_token}").get_data(as_text=True)


# --------------------------------------------------------------------------
# The public request
# --------------------------------------------------------------------------


def test_a_revoked_account_gets_no_link_and_the_same_neutral_answer(env):
    client = env["client"]
    answers = {}
    for key, email in (("ativo", "rec.ativo@example.test"), ("revogado", "rec.revogado@example.test"),
                       ("desconhecido", "ninguem@example.test")):
        before = _account(env["ids"][key]) if key in env["ids"] else None
        response = _request_recovery(client, email)
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert NEUTRAL in html
        answers[key] = _normalized(html, email)
        if key == "revogado":
            assert _account(env["ids"][key]) == before  # no token, nothing written
    # Indistinguishable answers: neither existence nor state is revealed.
    assert answers["ativo"] == answers["revogado"] == answers["desconhecido"]
    assert [message.to_address for message in env["sent"]] == ["rec.ativo@example.test"]


def test_an_active_account_still_recovers_end_to_end_and_keeps_its_credential_until_then(env):
    client = env["client"]
    before = _account(env["ids"]["ativo"])
    _request_recovery(client, "rec.ativo@example.test")
    after_request = _account(env["ids"]["ativo"])
    assert after_request[0] == before[0]  # a link changes no credential
    raw_token = _token_from(env["sent"][-1])
    assert INVALID_LINK not in _page(client, PURPOSE_PASSWORD_RESET, raw_token)
    response = _submit(client, PURPOSE_PASSWORD_RESET, raw_token)
    assert response.status_code == 302 and response.headers["Location"].endswith("/login")
    senha, estado, _version, ativo = _account(env["ids"]["ativo"])[0]
    assert estado == "personal" and ativo == 1
    with main.app.app_context():
        assert main.check_password(senha, "Nova#2026")


# --------------------------------------------------------------------------
# Old links after a revocation
# --------------------------------------------------------------------------


def test_a_link_issued_before_the_administrator_revokes_is_dead(env, tmp_path):
    client = env["client"]
    admin = main.app.test_client()
    login_admin(admin)
    # A student access, so the academic record is part of what must survive.
    assert admin.post("/admin/acesso/salvar", data={
        "nome": "Rec Aluno", "email": "rec.aluno@example.test", "nivel_acesso": "usuario",
        "matricula": "REC-001", "status": "Ativo", "turma_id": "1", "senha": "Inicial#2026",
    }).status_code == 302
    with main.app.app_context():
        usuario_id = int(main.get_db_connection().execute(
            "SELECT id FROM usuarios WHERE email='rec.aluno@example.test'").fetchone()[0])
    _request_recovery(client, "rec.aluno@example.test")
    raw_token = _token_from(env["sent"][-1])
    assert admin.post(f"/admin/acesso/{usuario_id}/deletar").status_code == 302  # revoke
    revoked = _account(usuario_id)

    assert INVALID_LINK in _page(client, PURPOSE_PASSWORD_RESET, raw_token)
    response = _submit(client, PURPOSE_PASSWORD_RESET, raw_token)
    assert response.status_code == 200 and INVALID_LINK in response.get_data(as_text=True)
    assert _account(usuario_id) == revoked  # not reactivated, academic record untouched
    assert revoked[0][3] == 0 and revoked[2] == ("Rec Aluno", "REC-001", 1, "Ativo")


@pytest.mark.parametrize("purpose", [PURPOSE_PASSWORD_RESET, PURPOSE_FIRST_ACCESS])
def test_a_token_that_survives_a_revocation_cannot_set_a_password(env, purpose):
    # The race the issuance lock closes, reproduced directly: a token still
    # live in its own row when the access is already revoked. First access is
    # the sharp case -- a revoked account is `pending`, which first access
    # alone would accept.
    client = env["client"]
    with main.app.app_context():
        conn = main.get_db_connection()
        if purpose == PURPOSE_FIRST_ACCESS:
            usuario_id = int(create_usuario_pending(conn, "Rec Pendente", "rec.pend@example.test", "admin").lastrowid)
        else:
            usuario_id = env["ids"]["ativo"]
        conn.commit()
    raw_token = _issue(usuario_id, purpose)
    with main.app.app_context():
        conn = main.get_db_connection()
        set_usuario_access_active(conn, usuario_id, False)  # no token invalidation
        conn.commit()
    before = _account(usuario_id)
    assert before[1][-1][2:] == (None, None)  # the token itself is still unconsumed and valid

    assert INVALID_LINK in _page(client, purpose, raw_token)
    response = _submit(client, purpose, raw_token)
    assert response.status_code == 200 and INVALID_LINK in response.get_data(as_text=True)
    assert _account(usuario_id) == before  # no password, no consumption, still revoked


def test_issuance_rechecks_the_access_inside_its_own_transaction(env):
    # A revocation that lands after the caller's eligibility check: the issuer
    # sees it under the account lock and issues nothing.
    usuario_id = env["ids"]["revogado"]
    before = _account(usuario_id)
    with main.app.app_context():
        outcome = password_email.issue_and_send_password_email(
            main.get_db_connection(), usuario_id=usuario_id, recipient="rec.revogado@example.test",
            user_name="Rec revogado", purpose=PURPOSE_PASSWORD_RESET,
        )
    assert outcome.status == "ineligible"
    assert _account(usuario_id) == before and env["sent"] == []


def test_the_recovery_request_itself_selects_no_revoked_account(env):
    # Layer one on its own (the issuance recheck would also refuse): the public
    # request never even reaches the issuer for a revoked access.
    from app.password_recovery import recovery_account

    with main.app.app_context():
        conn = main.get_db_connection()
        assert recovery_account(conn, "rec.revogado@example.test") is None
        assert int(recovery_account(conn, "rec.ativo@example.test")["id"]) == env["ids"]["ativo"]
        assert recovery_account(conn, "ninguem@example.test") is None
