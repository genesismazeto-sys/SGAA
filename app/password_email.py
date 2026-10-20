from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlencode

from app.access_onboarding import access_status_map
from app.db import lock_password_account, write_transaction
from app.password_tokens import (
    FIRST_ACCESS_TTL,
    PASSWORD_RESET_TTL,
    PURPOSE_FIRST_ACCESS,
    PURPOSE_PASSWORD_RESET,
    invalidate_password_token,
    issue_password_token,
    mark_password_token_sent,
)
from app.services.mail_service import (
    MailMessage,
    MailTransportError,
    is_valid_email,
    mail_transport_status,
    send_text_email,
)
from app.user_accounts import CREDENTIAL_STATE_PENDING
from services.oauth_config import OAuthConfigError, get_public_base_url


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PasswordMailOutcome:
    status: str
    detail: str = ""
    cta_label: str = ""
    cta_url: str = ""

    @property
    def sent(self) -> bool:
        return self.status == "sent"


def password_email_purpose(credential_state: str) -> str:
    """Shared individual/batch policy: onboarding only for pending accounts."""
    return PURPOSE_FIRST_ACCESS if credential_state == CREDENTIAL_STATE_PENDING else PURPOSE_PASSWORD_RESET


def password_email_target(conn, usuario_id: int) -> dict:
    """Read the same credential policy as individual sending, without issuing."""
    return password_email_targets(conn, [usuario_id])[usuario_id]


def password_email_targets(conn, usuario_ids: list[int]) -> dict[int, dict]:
    """Bounded-query preview, including missing/revoked/invalid selected IDs."""
    if not usuario_ids:
        return {}
    placeholders = ",".join("?" for _ in usuario_ids)
    rows = conn.execute(
        "SELECT u.id,u.nome,u.email,c.estado,c.acesso_ativo,c.auth_version,"
        " (SELECT COALESCE(MAX(id),0) FROM senha_tokens WHERE usuario_id=u.id) AS token_version"
        f" FROM usuarios u LEFT JOIN usuario_credenciais c ON c.usuario_id=u.id WHERE u.id IN ({placeholders})",
        usuario_ids,
    ).fetchall()
    rows_by_id = {row["id"]: row for row in rows}
    statuses = access_status_map(conn, usuario_ids)
    return {user_id: _password_email_target(user_id, rows_by_id.get(user_id), statuses[user_id])
            for user_id in usuario_ids}


def _password_email_target(usuario_id, row, status) -> dict:
    target = {"id": usuario_id, "nome": "", "email": "", "category": "ineligible", "reason": ""}
    if row is None:
        return {**target, "reason": "Usuário não encontrado."}
    target.update(nome=str(row["nome"] or ""), email=str(row["email"] or ""))
    if row["acesso_ativo"] != 1 or row["estado"] not in ("pending", "personal", "default"):
        return {**target, "reason": "Acesso revogado ou sem credenciais elegíveis."}
    if not is_valid_email(target["email"]):
        return {**target, "reason": "Destinatário ausente ou inválido."}
    purpose = password_email_purpose(row["estado"])
    target.update(
        access_status=status,
        purpose=purpose,
        category=("password_reset" if purpose == PURPOSE_PASSWORD_RESET else
                  "resend" if status == "Disponibilizado" else "first_access"),
        signature=[target["email"], row["estado"], row["acesso_ativo"], row["auth_version"], row["token_version"], status],
    )
    return target


def password_email_status(conn) -> dict[str, object]:
    status = dict(mail_transport_status(conn))
    if not status.get("ready"):
        return status
    try:
        get_public_base_url()
    except OAuthConfigError:
        return {
            **status,
            "ready": False,
            "reason": "public_base_url_unavailable",
            "message": "Configure a URL pública do SGAA para enviar links de senha.",
            "cta_label": "Configurar integração",
            "cta_url": status.get("cta_url") or "",
        }
    return status


def _password_message(
    *,
    purpose: str,
    recipient: str,
    user_name: str,
    raw_token: str,
    public_base_url: str,
) -> MailMessage:
    if purpose == PURPOSE_FIRST_ACCESS:
        path = "/primeiro-acesso"
        subject = "Defina sua senha de acesso ao SGAA"
        reason = "Um administrador disponibilizou seu primeiro acesso ao SGAA."
        expiry = f"Este link é válido por {int(FIRST_ACCESS_TTL.total_seconds() // 3600)} horas."
        closing = "Se você não esperava este acesso, entre em contato com a administração."
    elif purpose == PURPOSE_PASSWORD_RESET:
        path = "/redefinir-senha"
        subject = "Redefinição de senha do SGAA"
        reason = "Foi solicitada a redefinição da sua senha de acesso ao SGAA."
        expiry = f"Este link é válido por {int(PASSWORD_RESET_TTL.total_seconds() // 60)} minutos."
        closing = "Se você não solicitou esta redefinição, ignore esta mensagem."
    else:
        raise ValueError(f"invalid password mail purpose: {purpose!r}")

    link = f"{public_base_url.rstrip('/')}{path}?{urlencode({'token': raw_token})}"
    greeting = f"Olá, {user_name.strip()}." if user_name.strip() else "Olá."
    body = "\n\n".join(
        (
            greeting,
            reason,
            f"Use o link seguro abaixo para definir uma nova senha:\n{link}",
            expiry,
            closing,
        )
    )
    return MailMessage(to_address=recipient, subject=subject, body_text=body)


def issue_and_send_password_email(
    conn,
    *,
    usuario_id: int,
    recipient: str,
    user_name: str,
    purpose: str,
    expected_target: dict | None = None,
) -> PasswordMailOutcome:
    # Validate before superseding any existing link. Batch confirmations also
    # recheck their snapshot under the account lock, shared with revoke/reset.
    if not is_valid_email(recipient):
        return PasswordMailOutcome("failed", "Destinatário ausente ou inválido.")
    capability = password_email_status(conn)
    if not capability.get("ready"):
        return PasswordMailOutcome(
            "unavailable",
            str(capability.get("message") or "Envio de e-mail indisponível."),
            str(capability.get("cta_label") or ""),
            str(capability.get("cta_url") or ""),
        )

    try:
        public_base_url = get_public_base_url()
    except OAuthConfigError:
        return PasswordMailOutcome(
            "unavailable",
            "Configure a URL pública do SGAA para enviar links de senha.",
        )

    if expected_target is not None:
        with write_transaction(conn):
            lock_password_account(conn, usuario_id)
            target = password_email_target(conn, usuario_id)
            if target != expected_target:
                return PasswordMailOutcome("stale", "O acesso ou seu link mudou. Confira a conta e confirme uma nova operação.")
            raw_token, token_id = issue_password_token(conn, usuario_id, purpose)
    else:
        raw_token, token_id = issue_password_token(conn, usuario_id, purpose)
        conn.commit()
    message = _password_message(
        purpose=purpose,
        recipient=recipient,
        user_name=user_name,
        raw_token=raw_token,
        public_base_url=public_base_url,
    )
    try:
        send_text_email(conn, message)
    except MailTransportError as exc:
        if exc.indeterminate:
            # Deliberately NOT marked sent: the provider did not confirm
            # anything. The token stays valid because the mail may well have
            # arrived, but no durable evidence of a send is written, so no
            # surface may later present this as delivered.
            logger.warning(
                "event=password_mail_indeterminate purpose=%s usuario_id=%s code=%s",
                purpose,
                int(usuario_id),
                exc.debug_code or "MAIL_SEND_INDETERMINATE",
            )
            return PasswordMailOutcome(
                "indeterminate",
                "O provedor não confirmou o envio. O link permanece válido porque a mensagem pode ter sido entregue.",
            )
        invalidate_password_token(conn, token_id)
        conn.commit()
        logger.warning(
            "event=password_mail_failed purpose=%s usuario_id=%s code=%s",
            purpose,
            int(usuario_id),
            exc.debug_code or "MAIL_SEND_FAILED",
        )
        return PasswordMailOutcome("failed", str(exc))

    # The provider confirmed the send. This is the only branch allowed to write
    # the durable evidence, and it is what lets Admin > Acesso say
    # "Disponibilizado" without claiming something SGAA cannot know.
    mark_password_token_sent(conn, token_id)
    conn.commit()
    logger.info(
        "event=password_mail_sent purpose=%s usuario_id=%s",
        purpose,
        int(usuario_id),
    )
    return PasswordMailOutcome("sent")


__all__ = [
    "PasswordMailOutcome",
    "issue_and_send_password_email",
    "password_email_status",
    "password_email_purpose",
    "password_email_target",
    "password_email_targets",
]
