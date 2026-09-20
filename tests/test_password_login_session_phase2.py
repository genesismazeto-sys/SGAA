from __future__ import annotations

from pathlib import Path

import main
from app.auth import _clear_login_attempts
from app.password_tokens import PURPOSE_PASSWORD_RESET, issue_password_token
from app.security.passwords import hash_password
from app.settings import save_default_passwords_enabled
from app.user_accounts import (
    CREDENTIAL_STATE_PERSONAL,
    get_usuario_auth_version,
    set_usuario_credential_state,
    set_usuario_password_hash,
)
from tests.versioned_test_support import isolated_versioned_app_env


def _admin(conn):
    return conn.execute(
        "SELECT id,email FROM usuarios WHERE tipo='admin' ORDER BY id LIMIT 1"
    ).fetchone()


def test_login_uses_authoritative_credential_state_and_global_switch(tmp_path):
    with isolated_versioned_app_env(tmp_path, "login-switch.db") as env:
        with main.app.app_context():
            conn = main.get_db_connection()
            admin = _admin(conn)
            save_default_passwords_enabled(conn, False)
            conn.commit()
        _clear_login_attempts()
        denied = env["client"].post(
            "/login", data={"email": admin["email"], "senha": "admin123"}
        )
        assert denied.status_code == 200
        assert "E-mail ou senha inv" in denied.get_data(as_text=True)
        with env["client"].session_transaction() as session:
            assert "user_id" not in session

        with main.app.app_context():
            conn = main.get_db_connection()
            set_usuario_credential_state(conn, int(admin["id"]), CREDENTIAL_STATE_PERSONAL)
            conn.commit()
        _clear_login_attempts()
        allowed = env["client"].post(
            "/login",
            data={"email": admin["email"], "senha": "admin123"},
            follow_redirects=False,
        )
        assert allowed.status_code in (302, 303)
        with env["client"].session_transaction() as session:
            assert session["user_id"] == admin["id"]
            assert session["auth_version"] == 1


def test_password_change_invalidates_other_authenticated_session(tmp_path):
    with isolated_versioned_app_env(tmp_path, "session-version.db") as env:
        with main.app.app_context():
            conn = main.get_db_connection()
            admin = _admin(conn)
            set_usuario_credential_state(conn, int(admin["id"]), CREDENTIAL_STATE_PERSONAL)
            conn.commit()
            old_version = get_usuario_auth_version(conn, int(admin["id"]))
        with env["client"].session_transaction() as session:
            session.update(
                user_id=int(admin["id"]),
                user_type="admin",
                user_name="Admin",
                access_level="admin_total",
                auth_version=old_version,
            )

        with main.app.app_context():
            conn = main.get_db_connection()
            set_usuario_password_hash(
                conn,
                int(admin["id"]),
                hash_password("changed-elsewhere"),
                credential_state=CREDENTIAL_STATE_PERSONAL,
            )
            conn.commit()

        response = env["client"].get("/admin/acesso", follow_redirects=False)
        assert response.status_code in (302, 303)
        assert response.headers["Location"].endswith("/login")
        with env["client"].session_transaction() as session:
            assert "user_id" not in session


def test_own_admin_password_change_restamps_current_session(tmp_path, monkeypatch):
    import app.views.admin.acesso as access_views

    monkeypatch.setattr(
        access_views,
        "password_email_status",
        lambda _conn: {"ready": False, "cta_label": "", "cta_url": ""},
    )
    with isolated_versioned_app_env(tmp_path, "own-session-restamp.db") as env:
        with main.app.app_context():
            conn = main.get_db_connection()
            admin = conn.execute(
                """
                SELECT u.id,u.nome,u.email,u.nivel_acesso,c.auth_version
                FROM usuarios u JOIN usuario_credenciais c ON c.usuario_id=u.id
                WHERE u.tipo='admin' AND u.nivel_acesso='admin_total'
                ORDER BY u.id LIMIT 1
                """
            ).fetchone()
        with env["client"].session_transaction() as session:
            session.update(
                user_id=int(admin["id"]),
                user_type="admin",
                user_name=str(admin["nome"]),
                access_level="admin_total",
                auth_version=int(admin["auth_version"]),
            )

        changed = env["client"].post(
            "/admin/acesso/salvar",
            data={
                "usuario_id": str(admin["id"]),
                "nome": admin["nome"],
                "email": admin["email"],
                "nivel_acesso": admin["nivel_acesso"],
                "senha": "own-new-secret",
            },
            follow_redirects=False,
        )
        assert changed.status_code in (302, 303)
        with env["client"].session_transaction() as session:
            assert session["auth_version"] == int(admin["auth_version"]) + 1
        assert env["client"].get("/admin/acesso").status_code == 200


def test_public_password_surfaces_use_the_shared_auth_design_system(tmp_path):
    """Login, recovery request and set-password must speak one visual language.

    The SGAA authentication language is the ``login-page``/``login-card`` shell
    loaded through the shared ``design_system_css`` macro.  A page-local
    ``<style>`` block on any of these surfaces would be a parallel design
    system, which the contract forbids.
    """
    project_root = Path(main.__file__).resolve().parent
    templates = {
        "login.html",
        "forgot_password.html",
        "set_password.html",
    }
    for name in templates:
        source = (project_root / "templates" / name).read_text(encoding="utf-8")
        assert "design_system_css" in source, f"{name} must load the shared DS bundle"
        assert "<style" not in source, f"{name} must not carry a page-local stylesheet"
        assert "login-card" in source, f"{name} must use the shared auth card shell"

    with isolated_versioned_app_env(tmp_path, "public-ds.db") as env:
        login_html = env["client"].get("/login").get_data(as_text=True)
        assert login_html.count('class="login-forgot-link"') == 1
        assert 'href="/esqueci-minha-senha"' in login_html
        assert 'aria-disabled="true"' not in login_html
        assert 'onclick="return false;"' not in login_html

        forgot = env["client"].get("/esqueci-minha-senha")
        forgot_html = forgot.get_data(as_text=True)
        assert forgot.status_code == 200
        assert forgot.headers["Cache-Control"] == "no-store"
        assert 'class="login-page"' in forgot_html
        assert 'class="login-form"' in forgot_html
        assert 'name="csrf_token"' in forgot_html

        # An invalid token still renders the DS shell with a DS feedback line,
        # never a bare browser error page.
        invalid = env["client"].get("/redefinir-senha?token=not-a-real-token")
        invalid_html = invalid.get_data(as_text=True)
        assert invalid.status_code == 200
        assert invalid.headers["Referrer-Policy"] == "no-referrer"
        assert 'class="login-card"' in invalid_html
        assert "login-feedback-error" in invalid_html
        assert 'type="password"' not in invalid_html

        # A live token renders the DS password fields with the shared pw-toggle.
        with main.app.app_context():
            conn = main.get_db_connection()
            admin = _admin(conn)
            raw_token, _token_id = issue_password_token(
                conn, int(admin["id"]), PURPOSE_PASSWORD_RESET
            )
            conn.commit()
        valid_html = env["client"].get(
            f"/redefinir-senha?token={raw_token}"
        ).get_data(as_text=True)
        assert valid_html.count('class="pw-wrapper"') == 2
        assert valid_html.count('class="pw-toggle"') == 2
        assert 'name="senha"' in valid_html
        assert 'name="confirmacao_senha"' in valid_html
