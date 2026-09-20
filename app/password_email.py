from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlencode

from app.password_tokens import (
    FIRST_ACCESS_TTL,
    PASSWORD_RESET_TTL,
    PURPOSE_FIRST_ACCESS,
    PURPOSE_PASSWORD_RESET,
    invalidate_password_token,
    issue_password_token,
)
from app.services.mail_service import (
    MailMessage,
    MailTransportError,
    mail_transport_status,
    send_text_email,
)
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
) -> PasswordMailOutcome:
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
]
