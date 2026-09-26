from __future__ import annotations

import hashlib
import logging

from flask import (
    current_app,
    flash,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)

from app.auth import _client_ip
from app.db import get_db_connection
from app.password_email import issue_and_send_password_email
from app.password_recovery_limiter import (
    password_recovery_rate_limited,
    register_password_recovery_attempt,
)
from app.password_tokens import (
    PURPOSE_FIRST_ACCESS,
    PURPOSE_PASSWORD_RESET,
    consume_password_token_and_set_password,
    resolve_password_token,
)
from app.security.passwords import hash_password
from app.user_accounts import first_access_redeemable


logger = logging.getLogger(__name__)

RECOVERY_NEUTRAL_MESSAGE = (
    "Se houver uma conta associada a este e-mail, enviaremos as instruções "
    "para redefinição da senha."
)


def _identifier_hash(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:12]


def _eligible_recovery_user(conn, email: str):
    row = conn.execute(
        """
        SELECT u.id,u.nome,u.email,u.tipo,a.status AS aluno_status
          FROM usuarios u
          LEFT JOIN alunos a ON a.usuario_id=u.id
         WHERE u.email=?
         LIMIT 1
        """,
        (email,),
    ).fetchone()
    if row is None:
        return None
    if str(row["tipo"] or "").strip().lower() == "aluno":
        if str(row["aluno_status"] or "Ativo").strip().lower() != "ativo":
            return None
    return row


def forgot_password():
    email = ""
    submitted = False
    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        submitted = True
        ip = _client_ip()
        blocked, _retry_in = password_recovery_rate_limited(
            current_app,
            ip,
            email,
        )
        if not blocked:
            register_password_recovery_attempt(ip, email)
            conn = get_db_connection()
            user = _eligible_recovery_user(conn, email)
            if user is not None:
                outcome = issue_and_send_password_email(
                    conn,
                    usuario_id=int(user["id"]),
                    recipient=str(user["email"] or ""),
                    user_name=str(user["nome"] or ""),
                    purpose=PURPOSE_PASSWORD_RESET,
                )
                logger.info(
                    "event=public_password_recovery outcome=%s account_hash=%s",
                    outcome.status,
                    _identifier_hash(email),
                )
            else:
                logger.info(
                    "event=public_password_recovery outcome=neutral_no_eligible_account account_hash=%s",
                    _identifier_hash(email),
                )
        else:
            logger.info(
                "event=public_password_recovery outcome=rate_limited account_hash=%s",
                _identifier_hash(email),
            )

    response = make_response(
        render_template(
            "forgot_password.html",
            email_value=email,
            submitted=submitted,
            neutral_message=RECOVERY_NEUTRAL_MESSAGE,
        )
    )
    response.headers["Cache-Control"] = "no-store"
    return response


def _render_set_password(*, purpose: str, raw_token: str, error: str = ""):
    conn = get_db_connection()
    record = resolve_password_token(conn, raw_token, purpose=purpose)
    valid = record is not None
    if valid and purpose == PURPOSE_FIRST_ACCESS:
        valid = first_access_redeemable(record.credential_state)
    response = make_response(
        render_template(
            "set_password.html",
            purpose=purpose,
            token=raw_token if valid else "",
            valid=valid,
            error=error,
        )
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def _set_password(purpose: str):
    raw_token = (
        request.form.get("token")
        if request.method == "POST"
        else request.args.get("token")
    ) or ""
    if request.method == "GET":
        return _render_set_password(purpose=purpose, raw_token=raw_token)

    password = request.form.get("senha") or ""
    confirmation = request.form.get("confirmacao_senha") or ""
    if not password:
        return _render_set_password(
            purpose=purpose,
            raw_token=raw_token,
            error="Informe a nova senha.",
        )
    if password != confirmation:
        return _render_set_password(
            purpose=purpose,
            raw_token=raw_token,
            error="As senhas informadas não coincidem.",
        )

    new_hash = hash_password(password)
    auth_version = consume_password_token_and_set_password(
        get_db_connection(),
        raw_token,
        purpose,
        new_hash,
    )
    if auth_version is None:
        return _render_set_password(purpose=purpose, raw_token="")
    flash("Senha definida com sucesso. Entre com sua nova senha.", "success")
    return redirect(url_for("login"))


def reset_password():
    return _set_password(PURPOSE_PASSWORD_RESET)


def first_access():
    return _set_password(PURPOSE_FIRST_ACCESS)


__all__ = [
    "RECOVERY_NEUTRAL_MESSAGE",
    "first_access",
    "forgot_password",
    "reset_password",
]
