from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from urllib.parse import quote

import pytest

import app.password_email as password_email
import app.views.admin.acesso as access_views
import app.views.passwords as password_views
import main
from app.oauth_log_filter import (
    OAuthQueryRedactionFilter,
    install_oauth_query_redaction_filter,
)
from app.password_email import issue_and_send_password_email
from app.password_recovery_limiter import clear_password_recovery_attempts
from app.password_tokens import (
    PURPOSE_FIRST_ACCESS,
    PURPOSE_PASSWORD_RESET,
    issue_password_token,
)
from app.prod1_schema import bootstrap_prod1_schema
from app.security.passwords import check_password, hash_password
from app.services.mail_service import MailTransportError
from app.user_accounts import (
    CREDENTIAL_STATE_PERSONAL,
    create_usuario_pending,
    create_usuario_with_access_level,
)
from tests.versioned_test_support import isolated_versioned_app_env


def _connection() -> tuple[sqlite3.Connection, int]:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    bootstrap_prod1_schema(conn)
    cursor = create_usuario_with_access_level(
        conn,
        "Mail User",
        "mail@example.test",
        hash_password("personal-secret"),
        "admin",
        "admin_total",
        credential_state=CREDENTIAL_STATE_PERSONAL,
    )
    conn.commit()
    return conn, int(cursor.lastrowid)


def _active_tokens(conn) -> int:
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM senha_tokens WHERE consumed_at IS NULL AND invalidated_at IS NULL"
        ).fetchone()[0]
    )


def test_mail_unavailable_does_not_issue_token(monkeypatch):
    conn, user_id = _connection()
    monkeypatch.setattr(
        password_email,
        "password_email_status",
        lambda _conn: {"ready": False, "message": "Unavailable"},
    )
    outcome = issue_and_send_password_email(
        conn,
        usuario_id=user_id,
        recipient="mail@example.test",
        user_name="Mail User",
        purpose=PURPOSE_PASSWORD_RESET,
    )
    assert outcome.status == "unavailable"
    assert _active_tokens(conn) == 0


def test_definite_failure_invalidates_but_indeterminate_retains(monkeypatch):
    monkeypatch.setattr(password_email, "password_email_status", lambda _conn: {"ready": True})
    monkeypatch.setattr(password_email, "get_public_base_url", lambda: "https://sgaa.example.test")

    conn, user_id = _connection()
    monkeypatch.setattr(
        password_email,
        "send_text_email",
        lambda _conn, _message: (_ for _ in ()).throw(
            MailTransportError("definite", debug_code="DEFINITE")
        ),
    )
    definite = issue_and_send_password_email(
        conn,
        usuario_id=user_id,
        recipient="mail@example.test",
        user_name="Mail User",
        purpose=PURPOSE_PASSWORD_RESET,
    )
    assert definite.status == "failed"
    assert _active_tokens(conn) == 0

    conn, user_id = _connection()
    monkeypatch.setattr(
        password_email,
        "send_text_email",
        lambda _conn, _message: (_ for _ in ()).throw(
            MailTransportError("uncertain", debug_code="UNCERTAIN", indeterminate=True)
        ),
    )
    uncertain = issue_and_send_password_email(
        conn,
        usuario_id=user_id,
        recipient="mail@example.test",
        user_name="Mail User",
        purpose=PURPOSE_PASSWORD_RESET,
    )
    assert uncertain.status == "indeterminate"
    assert _active_tokens(conn) == 1


def test_message_uses_canonical_base_url_and_database_never_stores_raw_token(monkeypatch):
    conn, user_id = _connection()
    sent = []
    monkeypatch.setattr(password_email, "password_email_status", lambda _conn: {"ready": True})
    monkeypatch.setattr(password_email, "get_public_base_url", lambda: "https://canonical.example/sgaa")
    monkeypatch.setattr(password_email, "send_text_email", lambda _conn, message: sent.append(message))

    outcome = issue_and_send_password_email(
        conn,
        usuario_id=user_id,
        recipient="mail@example.test",
        user_name="Mail User",
        purpose=PURPOSE_PASSWORD_RESET,
    )
    assert outcome.status == "sent"
    assert len(sent) == 1
    assert "https://canonical.example/sgaa/redefinir-senha?token=" in sent[0].body_text
    raw = sent[0].body_text.split("?token=", 1)[1].splitlines()[0]
    stored = conn.execute("SELECT token_hash FROM senha_tokens").fetchone()[0]
    assert raw not in stored


def test_public_recovery_response_is_neutral_and_does_not_send_for_unknown_account(
    tmp_path, monkeypatch
):
    clear_password_recovery_attempts()
    calls = []
    monkeypatch.setattr(
        password_views,
        "issue_and_send_password_email",
        lambda *args, **kwargs: calls.append(kwargs) or type("Outcome", (), {"status": "sent"})(),
    )
    with isolated_versioned_app_env(tmp_path, "public-recovery.db") as env:
        with main.app.app_context():
            known = main.get_db_connection().execute(
                "SELECT email FROM usuarios ORDER BY id LIMIT 1"
            ).fetchone()[0]
        known_response = env["client"].post(
            "/esqueci-minha-senha", data={"email": known}
        )
        unknown_response = env["client"].post(
            "/esqueci-minha-senha", data={"email": "absent@example.test"}
        )
    assert known_response.status_code == unknown_response.status_code == 200
    assert password_views.RECOVERY_NEUTRAL_MESSAGE in known_response.get_data(as_text=True)
    assert password_views.RECOVERY_NEUTRAL_MESSAGE in unknown_response.get_data(as_text=True)
    assert len(calls) == 1


def test_public_password_forms_require_csrf(tmp_path):
    original = main.app.config.get("WTF_CSRF_ENABLED")
    try:
        with isolated_versioned_app_env(tmp_path, "public-password-csrf.db") as env:
            main.app.config["WTF_CSRF_ENABLED"] = True
            with main.app.app_context():
                conn = main.get_db_connection()
                # First access is redeemable only on a pending account.
                user_id = int(
                    create_usuario_pending(
                        conn, "CSRF subject", "csrf-pending@example.test", "admin"
                    ).lastrowid
                )
                first_token, _ = issue_password_token(
                    conn, user_id, PURPOSE_FIRST_ACCESS
                )
                reset_token, _ = issue_password_token(
                    conn, user_id, PURPOSE_PASSWORD_RESET
                )
                conn.commit()

            forgot = env["client"].get("/esqueci-minha-senha")
            assert 'name="csrf_token"' in forgot.get_data(as_text=True)
            assert env["client"].post(
                "/esqueci-minha-senha", data={"email": "absent@example.test"}
            ).status_code == 400

            cases = (
                ("/primeiro-acesso", first_token),
                ("/redefinir-senha", reset_token),
            )
            for path, token in cases:
                page = env["client"].get(path, query_string={"token": token})
                html = page.get_data(as_text=True)
                assert page.status_code == 200
                assert 'name="csrf_token"' in html
                assert env["client"].post(
                    path,
                    data={
                        "token": token,
                        "senha": "new-secret",
                        "confirmacao_senha": "new-secret",
                    },
                ).status_code == 400
    finally:
        main.app.config["WTF_CSRF_ENABLED"] = original


def test_admin_single_user_email_action_chooses_purpose_from_credential_state(
    tmp_path, monkeypatch
):
    calls = []
    monkeypatch.setattr(
        access_views,
        "password_email_status",
        lambda _conn: {"ready": True, "cta_label": "", "cta_url": ""},
    )
    monkeypatch.setattr(
        access_views,
        "issue_and_send_password_email",
        lambda *args, **kwargs: calls.append(kwargs)
        or type("Outcome", (), {"status": "sent", "detail": ""})(),
    )
    with isolated_versioned_app_env(tmp_path, "admin-password-email.db") as env:
        with main.app.app_context():
            conn = main.get_db_connection()
            # prod-1/v11: first access is for an account still being
            # onboarded -- pending. One holding a credential gets a reset.
            default_user = {
                "id": create_usuario_pending(
                    conn, "Pending mail", "pending-mail@example.test", "admin"
                ).lastrowid
            }
            personal_cursor = create_usuario_with_access_level(
                conn,
                "Personal mail",
                "personal-mail@example.test",
                hash_password("personal-secret"),
                "admin",
                "consultivo",
                credential_state=CREDENTIAL_STATE_PERSONAL,
            )
            personal_id = int(personal_cursor.lastrowid)
            admin = conn.execute(
                """
                SELECT u.id,c.auth_version FROM usuarios u
                JOIN usuario_credenciais c ON c.usuario_id=u.id
                WHERE u.tipo='admin' AND u.nivel_acesso='admin_total'
                ORDER BY u.id LIMIT 1
                """
            ).fetchone()
            conn.commit()
        with env["client"].session_transaction() as session:
            session.update(
                user_id=int(admin["id"]),
                user_type="admin",
                user_name="Admin",
                access_level="admin_total",
                auth_version=int(admin["auth_version"]),
            )

        page = env["client"].get("/admin/acesso")
        html = page.get_data(as_text=True)
        assert page.status_code == 200
        assert "Recuperação por e-mail:" in html
        assert "Disponível" in html
        assert "Enviar acesso" in html
        assert "Redefinir por e-mail" in html

        first = env["client"].post(
            f"/admin/acesso/{int(default_user['id'])}/senha-por-email",
            follow_redirects=False,
        )
        reset = env["client"].post(
            f"/admin/acesso/{personal_id}/senha-por-email",
            follow_redirects=False,
        )
        assert first.status_code in (302, 303)
        assert reset.status_code in (302, 303)
    assert [call["purpose"] for call in calls] == [
        PURPOSE_FIRST_ACCESS,
        PURPOSE_PASSWORD_RESET,
    ]


def test_password_token_query_string_is_redacted_in_access_logs():
    """A security link lands in the Werkzeug access log; the raw token must not."""
    install_oauth_query_redaction_filter()
    werkzeug_logger = logging.getLogger("werkzeug")
    redaction_filters = [
        item
        for item in werkzeug_logger.filters
        if isinstance(item, OAuthQueryRedactionFilter)
    ]
    assert len(redaction_filters) == 1, "the redaction filter must be installed exactly once"

    raw_token = "s3cr3t-raw-password-token-value-not-in-logs"
    record = logging.LogRecord(
        name="werkzeug",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='127.0.0.1 - - [20/Sep/2026 12:00:00] "%s" %s -',
        args=(f"GET /redefinir-senha?token={raw_token} HTTP/1.1", "200"),
        exc_info=None,
    )
    assert redaction_filters[0].filter(record) is True
    rendered = record.getMessage()
    assert raw_token not in rendered
    assert "token=[REDACTED]" in rendered

    for path in ("/primeiro-acesso", "/redefinir-senha"):
        probe = logging.LogRecord(
            name="werkzeug",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg=f'"GET {path}?token={raw_token}&x=1 HTTP/1.1" 200 -',
            args=(),
            exc_info=None,
        )
        assert redaction_filters[0].filter(probe) is True
        assert raw_token not in probe.getMessage()
        assert "x=1" in probe.getMessage(), "only the token value may be redacted"


def _captured_link(sent) -> str:
    assert len(sent) == 1, sent
    line = next(
        part for part in sent[0].body_text.splitlines() if "?token=" in part
    )
    return line.strip()


def test_reset_link_round_trip_against_the_issuing_runtime(tmp_path, monkeypatch):
    """The failed acceptance click, reproduced and then proven correct.

    Captured mail only -- no provider send.  The link is composed from the
    trusted configured public base URL, then replayed against the SAME app and
    database that issued it.
    """
    base_url = "http://127.0.0.1:5000"
    sent = []
    monkeypatch.setattr(password_email, "password_email_status", lambda _conn: {"ready": True})
    monkeypatch.setattr(password_email, "get_public_base_url", lambda: base_url)
    monkeypatch.setattr(password_email, "send_text_email", lambda _conn, message: sent.append(message))
    monkeypatch.setattr(
        access_views, "password_email_status", lambda _conn: {"ready": True, "cta_label": "", "cta_url": ""}
    )

    with isolated_versioned_app_env(tmp_path, "reset-round-trip.db") as env:
        with main.app.app_context():
            conn = main.get_db_connection()
            admin = conn.execute(
                "SELECT u.id,c.auth_version FROM usuarios u "
                "JOIN usuario_credenciais c ON c.usuario_id=u.id "
                "WHERE u.tipo='admin' ORDER BY u.id LIMIT 1"
            ).fetchone()
            target_id = int(
                conn.execute(
                    "SELECT id FROM usuarios WHERE tipo='admin' ORDER BY id LIMIT 1"
                ).fetchone()[0]
            )
            # A personal-state account gets a password_reset, not a first access.
            conn.execute(
                "UPDATE usuario_credenciais SET estado='personal' WHERE usuario_id=?",
                (target_id,),
            )
            conn.commit()
        with env["client"].session_transaction() as session:
            session.update(
                user_id=int(admin["id"]),
                user_type="admin",
                user_name="Admin",
                access_level="admin_total",
                auth_version=int(admin["auth_version"]),
            )

        issued = env["client"].post(
            f"/admin/acesso/{target_id}/senha-por-email", follow_redirects=False
        )
        assert issued.status_code in (302, 303)

        # 2. the link target is the configured authority, not the request host
        link = _captured_link(sent)
        assert link.startswith(f"{base_url}/redefinir-senha?token=")
        path_and_query = link[len(base_url):]
        raw_token = path_and_query.split("?token=", 1)[1]

        with main.app.app_context():
            conn = main.get_db_connection()
            assert conn.execute(
                "SELECT purpose FROM senha_tokens WHERE consumed_at IS NULL"
            ).fetchone()[0] == PURPOSE_PASSWORD_RESET
            # the transported token is URL-safe, so it survives the query string
            assert raw_token == quote(raw_token, safe="")

        # 3/4. immediate GET renders the real form against the issuing DB
        first_get = env["client"].get(path_and_query)
        first_html = first_get.get_data(as_text=True)
        assert first_get.status_code == 200
        assert "Este link é inválido" not in first_html
        assert 'name="senha"' in first_html and 'name="confirmacao_senha"' in first_html

        # 5. GET did not consume
        with main.app.app_context():
            row = main.get_db_connection().execute(
                "SELECT consumed_at,invalidated_at FROM senha_tokens"
            ).fetchone()
            assert row["consumed_at"] is None and row["invalidated_at"] is None
        assert env["client"].get(path_and_query).status_code == 200

        # 6. POST with matching confirmation succeeds
        posted = env["client"].post(
            "/redefinir-senha",
            data={
                "token": raw_token,
                "senha": "nova-senha-pessoal",
                "confirmacao_senha": "nova-senha-pessoal",
            },
            follow_redirects=False,
        )
        assert posted.status_code in (302, 303)
        assert posted.headers["Location"].endswith("/login")

        # 7. token consumed, password installed, credential promoted
        with main.app.app_context():
            conn = main.get_db_connection()
            row = conn.execute("SELECT consumed_at FROM senha_tokens").fetchone()
            assert row["consumed_at"] is not None
            state = conn.execute(
                "SELECT estado FROM usuario_credenciais WHERE usuario_id=?", (target_id,)
            ).fetchone()[0]
            assert state == "personal"
            assert check_password(
                conn.execute("SELECT senha FROM usuarios WHERE id=?", (target_id,)).fetchone()[0],
                "nova-senha-pessoal",
            )

        # 8. replay is rejected
        replay_get = env["client"].get(path_and_query)
        assert replay_get.status_code == 200
        assert "Este link é inválido" in replay_get.get_data(as_text=True)
        replay_post = env["client"].post(
            "/redefinir-senha",
            data={
                "token": raw_token,
                "senha": "outra-senha",
                "confirmacao_senha": "outra-senha",
            },
        )
        assert "Este link é inválido" in replay_post.get_data(as_text=True)


def test_security_links_use_the_configured_authority_not_the_request_host(tmp_path, monkeypatch):
    """A spoofed Host header must never influence a password link."""
    sent = []
    monkeypatch.setattr(password_email, "password_email_status", lambda _conn: {"ready": True})
    monkeypatch.setattr(password_email, "get_public_base_url", lambda: "https://sgaa.example.org")
    monkeypatch.setattr(password_email, "send_text_email", lambda _conn, message: sent.append(message))
    monkeypatch.setattr(
        password_views, "password_recovery_rate_limited", lambda *a, **k: (False, 0)
    )

    with isolated_versioned_app_env(tmp_path, "trusted-authority.db") as env:
        with main.app.app_context():
            email = main.get_db_connection().execute(
                "SELECT email FROM usuarios ORDER BY id LIMIT 1"
            ).fetchone()[0]
        response = env["client"].post(
            "/esqueci-minha-senha",
            data={"email": email},
            headers={"Host": "attacker.example.net"},
        )
        assert response.status_code == 200

    link = _captured_link(sent)
    assert link.startswith("https://sgaa.example.org/redefinir-senha?token=")
    assert "attacker.example.net" not in link
    assert "localhost" not in link


def test_the_acceptance_base_url_override_is_gone_and_cannot_be_revived(monkeypatch):
    """One port means the stored base URL is already right for both runtimes.

    ``APP_ACCEPTANCE_PUBLIC_BASE_URL`` existed only to paper over an acceptance
    runtime listening on a different port. With a single port it reconciles
    nothing, and an env var able to silently replace the trusted link authority
    is not kept dormant: setting it must now change nothing at all.
    """
    from services import oauth_config

    source = Path(oauth_config.__file__).read_text(encoding="utf-8")
    assert 'os.getenv("APP_ACCEPTANCE_PUBLIC_BASE_URL")' not in source, (
        "the retired override is being read again"
    )
    assert "_acceptance_base_url_override" not in source.replace("# ", ""), (
        "the retired override function is back"
    )

    monkeypatch.setattr(
        oauth_config, "get_public_base_url_setting", lambda: "http://localhost:5000"
    )
    monkeypatch.setenv("APP_ENV", "development")
    assert oauth_config.get_public_base_url() == "http://localhost:5000"

    # Set to anything at all -- including a hostile value -- it is simply unread.
    for value in ("http://localhost:5001", "http://attacker.example.net", "not-a-url"):
        monkeypatch.setenv("APP_ACCEPTANCE_PUBLIC_BASE_URL", value)
        assert oauth_config.get_public_base_url() == "http://localhost:5000", value

    # Production is unaffected too: the store stays the sole authority.
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setattr(
        oauth_config, "get_public_base_url_setting", lambda: "https://sgaa.example.org"
    )
    assert oauth_config.get_public_base_url() == "https://sgaa.example.org"


def test_sgaa_has_exactly_one_application_port():
    """5000, everywhere. The isolation boundary is the DATABASE, not the port."""
    root = Path(main.__file__).resolve().parent
    canonical = (root / "run.bat").read_text(encoding="utf-8", errors="replace")
    acceptance = (root / "run_acceptance.bat").read_text(encoding="utf-8", errors="replace")

    for name, launcher in (("run.bat", canonical), ("run_acceptance.bat", acceptance)):
        assert "5001" not in launcher, f"{name} still knows about port 5001"
        assert "APP_ACCEPTANCE_PUBLIC_BASE_URL" not in launcher, name

    assert 'if "%APP_PORT%"=="" set "APP_PORT=5000"' in canonical
    assert 'set "APP_PORT=5000"' in acceptance


def test_acceptance_launcher_refuses_canonical_db_and_an_occupied_port():
    """Neither refusal may be softened: they are what keep the two apart."""
    root = Path(main.__file__).resolve().parent
    acceptance = (root / "run_acceptance.bat").read_text(encoding="utf-8", errors="replace")

    # Disposable database, and an explicit refusal of the canonical one.
    assert 'set "APP_DATABASE=%SGAA_ACCEPTANCE_DB%"' in acceptance
    assert 'if /i "%RESOLVED_DB%"=="%CANONICAL_DB%"' in acceptance
    refusal = acceptance.split('if /i "%RESOLVED_DB%"=="%CANONICAL_DB%"', 1)[1]
    assert "exit /b 1" in refusal.split(")", 1)[0], "the canonical-DB refusal does not abort"

    # It must decide for itself that 5000 is free -- never start a second SGAA.
    assert "Get-NetTCPConnection -LocalPort %APP_PORT% -State Listen" in acceptance
    port_guard = acceptance.split("Get-NetTCPConnection", 1)[1]
    assert "exit /b 1" in port_guard, "an occupied port does not abort the launch"

    # Launch steps stay owned by run.bat.
    assert 'call "%~dp0run.bat"' in acceptance
    for duplicated in ("bootstrap_sgaa_runtime.ps1", "main.py", "startup_preflight"):
        assert duplicated not in acceptance, f"{duplicated} must stay owned by run.bat"
