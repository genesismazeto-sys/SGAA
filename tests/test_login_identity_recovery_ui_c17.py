"""UI-C17: the login page says "SGAA" and sends access problems to self-service
password recovery instead of a mailbox.

Only ``templates/login.html`` changes. The recovery flow it points to is the
existing one -- ``/esqueci-minha-senha`` (``forgot_password``): anonymous,
rate-limited, one neutral answer whether or not the e-mail exists, a
``PURPOSE_PASSWORD_RESET`` link through ``issue_and_send_password_email``.
Nothing here sends a real e-mail: the send is replaced by a recorder.
"""

from __future__ import annotations

import re
import uuid

import pytest

import main
import app.views.passwords as passwords_view
from app.password_recovery_limiter import clear_password_recovery_attempts
from app.root_admin import root_admin_email
from app.user_accounts import create_usuario_with_access_level
from tests.root_admin_test_config import TEST_ROOT_MASTER_KEY
from tests.versioned_test_support import isolated_versioned_app_env

NEUTRAL = passwords_view.RECOVERY_NEUTRAL_MESSAGE


@pytest.fixture
def env(tmp_path, monkeypatch):
    sent: list[dict] = []

    class _Outcome:
        status = "sent"

    def _recorder(conn, **kwargs):
        sent.append(kwargs)
        return _Outcome()

    monkeypatch.setattr(passwords_view, "issue_and_send_password_email", _recorder)
    _reset_rate_limits()
    try:
        with isolated_versioned_app_env(tmp_path, "ui-c17.db") as environment:
            yield environment["client"], sent
    finally:
        # The limiters are process-global and every test client is 127.0.0.1:
        # leave no attempts behind for later suites.
        _reset_rate_limits()


def _reset_rate_limits() -> None:
    import app.auth as auth

    clear_password_recovery_attempts()
    auth._login_attempts.clear()
    auth._login_attempts_by_account.clear()


def _account(state: str = "personal", *, password="senha-c17", active=True) -> tuple[int, str]:
    token = uuid.uuid4().hex[:8]
    email = f"c17-{token}@example.invalid"
    with main.app.app_context():
        conn = main.get_db_connection()
        uid = int(create_usuario_with_access_level(
            conn, f"C17 {token}", email, main.hash_password(password), "admin", "administrativo",
            credential_state=state,
        ).lastrowid)
        if not active:
            conn.execute("UPDATE usuario_credenciais SET acesso_ativo=0 WHERE usuario_id=?", (uid,))
        conn.commit()
    return uid, email


def _credential(uid: int) -> tuple:
    with main.app.app_context():
        return tuple(main.get_db_connection().execute(
            "SELECT estado,acesso_ativo,auth_version FROM usuario_credenciais WHERE usuario_id=?", (uid,)
        ).fetchone())


def _logged_in_user(client, email: str, secret: str):
    client.post("/login", data={"email": email, "senha": secret}, follow_redirects=False)
    with client.session_transaction() as session:
        return session.get("user_id")


# --------------------------------------------------------------------------
# Login page
# --------------------------------------------------------------------------


def test_login_shows_sgaa_and_a_self_service_recovery_cta(env):
    client, _sent = env
    response = client.get("/login")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert '<h1 class="login-title">SGAA</h1>' in html
    assert "Sistema de Atividades Complementares" not in html
    assert "mailto:" not in html
    assert "atividadescomplementares@" not in html
    footer = re.search(r'<p class="login-footer">(.*?)</p>', html, re.S)
    assert footer, "the login footer is gone"
    # Styled like the footer's former mailto link (a plain anchor in
    # .login-footer); the page keeps its single .login-forgot-link (the form's
    # "Esqueceu sua senha?"), which test_password_login_session_phase2 pins.
    assert '<a href="/esqueci-minha-senha">Recuperar senha</a>' in footer.group(1)
    assert '<a class="login-forgot-link" href="/esqueci-minha-senha">Esqueceu sua senha?</a>' in html
    assert html.count('class="login-forgot-link"') == 1
    # Accepted auth shell untouched.
    assert '<main class="login-page">' in html and '<div class="login-card">' in html


def test_login_institutional_name_is_exact_ui_b22(env):
    # UI-B22: the login subtitle carries the "EJ - " institutional prefix.
    client, _sent = env
    html = client.get("/login").get_data(as_text=True)

    subtitles = re.findall(r'<p class="login-subtitle">(.*?)</p>', html, re.S)
    assert subtitles == ["EJ - Faculdade de Tecnologia em Aviação Civil"]
    assert '<h1 class="login-title">SGAA</h1>' in html


def test_recovery_route_is_anonymous(env):
    client, _sent = env
    with client.session_transaction() as session:
        session.clear()
    response = client.get("/esqueci-minha-senha")
    assert response.status_code == 200
    assert 'action="/esqueci-minha-senha"' in response.get_data(as_text=True)


# --------------------------------------------------------------------------
# Existing recovery semantics preserved
# --------------------------------------------------------------------------


def test_recovery_answers_neutrally_and_only_mails_an_existing_account(env):
    client, sent = env
    _uid, email = _account("personal")

    unknown = client.post("/esqueci-minha-senha", data={"email": "ninguem@example.invalid"})
    known = client.post("/esqueci-minha-senha", data={"email": email})

    for response in (unknown, known):
        assert response.status_code == 200
        assert NEUTRAL in response.get_data(as_text=True)
    assert [s["recipient"] for s in sent] == [email]
    assert sent[0]["purpose"] == passwords_view.PURPOSE_PASSWORD_RESET


@pytest.mark.parametrize("state", ["pending", "default", "personal"])
def test_recovery_request_changes_no_credential_state(env, state):
    client, sent = env
    uid, email = _account(state)
    before = _credential(uid)
    client.post("/esqueci-minha-senha", data={"email": email})
    assert sent and sent[-1]["usuario_id"] == uid
    assert _credential(uid) == before


def test_revoked_account_is_not_reactivated_by_a_recovery_request(env):
    client, _sent = env
    uid, email = _account("personal", active=False)
    client.post("/esqueci-minha-senha", data={"email": email})
    assert _credential(uid)[1] == 0
    assert _logged_in_user(client, email, "senha-c17") is None


# --------------------------------------------------------------------------
# Logins still work
# --------------------------------------------------------------------------


def test_normal_password_login_still_works(env):
    client, _sent = env
    uid, email = _account("personal")
    assert _logged_in_user(client, email, "senha-c17") == uid


def test_root_master_key_login_still_works(env):
    client, _sent = env
    with client.session_transaction() as session:
        session.clear()
    assert _logged_in_user(client, root_admin_email(), TEST_ROOT_MASTER_KEY) is not None
