"""The first-access link is valid for 7 days, and its e-mail says so.

The password-reset link keeps its 60 minutes. Fictitious account, isolated
database, simulated mail transport only.
"""
from __future__ import annotations

import datetime as dt

import pytest

import main
import app.password_email as password_email
from app.access_onboarding import access_status_for_usuario
from app.password_tokens import (
    FIRST_ACCESS_TTL,
    PASSWORD_RESET_TTL,
    PURPOSE_FIRST_ACCESS,
    PURPOSE_PASSWORD_RESET,
    issue_password_token,
    mark_password_token_sent,
    resolve_password_token,
)
from app.status_presentation import ACCESS_STATUS_DISPONIBILIZADO, ACCESS_STATUS_EXPIRADO
from app.user_accounts import create_usuario_pending
from tests.versioned_test_support import isolated_versioned_app_env

ISSUED = dt.datetime(2026, 11, 18, 12, 0, 0, tzinfo=dt.timezone.utc)


@pytest.fixture
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "first-access-ttl.db") as environment:
        with main.app.app_context():
            conn = main.get_db_connection()
            usuario_id = int(create_usuario_pending(conn, "Validade Link", "validade@example.test", "admin").lastrowid)
            conn.commit()
        yield {**environment, "usuario_id": usuario_id}


def test_the_durations_are_seven_days_and_sixty_minutes():
    assert FIRST_ACCESS_TTL == dt.timedelta(days=7)
    assert PASSWORD_RESET_TTL == dt.timedelta(minutes=60)


def test_a_first_access_link_lives_exactly_seven_days(env):
    with main.app.app_context():
        conn = main.get_db_connection()
        raw_token, token_id = issue_password_token(conn, env["usuario_id"], PURPOSE_FIRST_ACCESS, now=ISSUED)
        conn.commit()
        created, expires = conn.execute(
            "SELECT created_at, expires_at FROM senha_tokens WHERE id = ?", (token_id,)
        ).fetchone()
        parse = lambda text: dt.datetime.strptime(str(text), "%Y-%m-%d %H:%M:%S")
        assert parse(expires) - parse(created) == dt.timedelta(days=7)
        # Still usable at day 6 (the old 72 h would have expired it), gone after day 7.
        assert resolve_password_token(conn, raw_token, now=ISSUED + dt.timedelta(days=6, hours=23)) is not None
        assert resolve_password_token(conn, raw_token, now=ISSUED + dt.timedelta(days=7, seconds=1)) is None


def test_a_delivered_first_access_link_reads_expirado_only_after_seven_days(env):
    with main.app.app_context():
        conn = main.get_db_connection()
        now = dt.datetime.now(dt.timezone.utc)
        _raw, token_id = issue_password_token(conn, env["usuario_id"], PURPOSE_FIRST_ACCESS, now=now - dt.timedelta(days=4))
        mark_password_token_sent(conn, token_id)
        conn.commit()
        assert access_status_for_usuario(conn, env["usuario_id"]) == ACCESS_STATUS_DISPONIBILIZADO
        conn.execute(
            "UPDATE senha_tokens SET expires_at = ? WHERE id = ?",
            ((now - dt.timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S"), token_id),
        )
        conn.commit()
        assert access_status_for_usuario(conn, env["usuario_id"]) == ACCESS_STATUS_EXPIRADO


@pytest.mark.parametrize(("purpose", "phrase"), [
    (PURPOSE_FIRST_ACCESS, "Este link é válido por 7 dias."),
    (PURPOSE_PASSWORD_RESET, "Este link é válido por 60 minutos."),
])
def test_the_e_mail_states_the_real_validity(env, monkeypatch, purpose, phrase):
    sent = []
    monkeypatch.setattr(password_email, "password_email_status", lambda conn: {"ready": True})
    monkeypatch.setattr(password_email, "get_public_base_url", lambda: "https://sgaa.example.test")
    monkeypatch.setattr(password_email, "send_text_email", lambda conn, message: sent.append(message))
    with main.app.app_context():
        outcome = password_email.issue_and_send_password_email(
            main.get_db_connection(), usuario_id=env["usuario_id"], recipient="validade@example.test",
            user_name="Validade Link", purpose=purpose,
        )
    assert outcome.status == "sent"
    assert phrase in sent[0].body_text
    assert "horas" not in sent[0].body_text
