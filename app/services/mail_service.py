"""Generic outbound mail transport over the connected Microsoft identity.

Deliberately knows nothing about Requisições: no request ids, no presets, no
decision events.  It accepts a recipient, a subject and a plain-text body.

Consumers:

* request-decision e-mails -- the first consumer;
* first-access account e-mail;
* password-recovery e-mail.

See ``docs/mail/AUTH_EMAIL_EXTENSION_POINT.md`` for the auth contracts those
consumers honour.

Security
--------
Access tokens, refresh tokens, the MSAL cache blob, the client secret and the
token encryption key never leave this layer.  :func:`sanitize_provider_error`
is the only channel by which a provider failure becomes persistable text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.cloud_connections import (
    CloudConnectionError,
    get_authenticated_access_token,
)
from services.onedrive_service import (
    MailSendIndeterminate,
    OneDriveServiceError,
    send_mail_with_access_token,
    token_grants_mail_send,
)

MAIL_PROVIDER = "onedrive"

# Connection and mail authorization are DIFFERENT capabilities. A delegated
# token obtained before Mail.Send existed still grants full OneDrive/files
# access, so describing that account as "disconnected" is simply wrong.
CONNECT_MESSAGE = (
    "Conecte uma conta Microsoft para habilitar o envio de e-mails."
)
AUTHORIZE_MAIL_MESSAGE = (
    "Autorize o envio de e-mails para a conta Microsoft conectada."
)
AUTHORIZE_MAIL_CTA = "Autorizar envio de e-mails"
CONNECT_CTA = "Conectar Microsoft"

# Back-compat alias: existing callers that imported the old single message.
RECONNECT_MESSAGE = AUTHORIZE_MAIL_MESSAGE

# Deliberately conservative: structural validation only, no deliverability claim.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")

_SECRET_HINTS = (
    "bearer",
    "access_token",
    "refresh_token",
    "client_secret",
    "id_token",
    "authorization",
    "msal_cache",
)

_MAX_ERROR_CHARS = 300


class MailTransportError(RuntimeError):
    """Sanitized outbound-mail failure."""

    def __init__(self, message: str, *, debug_code: str = "", indeterminate: bool = False):
        super().__init__(message)
        self.debug_code = debug_code
        self.indeterminate = indeterminate


@dataclass(frozen=True)
class MailMessage:
    to_address: str
    subject: str
    body_text: str


def is_valid_email(value: str | None) -> bool:
    candidate = str(value or "").strip()
    if not candidate or len(candidate) > 254:
        return False
    return bool(_EMAIL_RE.match(candidate))


def sanitize_provider_error(error: BaseException | str) -> str:
    """Reduce a provider failure to short, secret-free, persistable text."""
    text = str(error or "").strip()
    if not text:
        return "Falha não especificada no provedor de e-mail."
    lowered = text.lower()
    if any(hint in lowered for hint in _SECRET_HINTS):
        return "Falha de autenticação no provedor de e-mail."
    # Strip anything token-shaped that slipped through.
    text = re.sub(r"[A-Za-z0-9_\-]{40,}", "[redacted]", text)
    if len(text) > _MAX_ERROR_CHARS:
        text = text[:_MAX_ERROR_CHARS].rstrip() + "…"
    return text


def mail_transport_status(conn) -> dict[str, object]:
    """Read-only capability probe. Never reconnects and never writes a token.

    Reports provider connection and mail authorization as two independent
    facts, so a healthy OneDrive account missing only ``Mail.Send`` is reported
    as connected-but-unauthorized rather than disconnected.
    """
    from app.cloud_connections import get_active_cloud_account

    def _authorize_url() -> str:
        # The existing OneDrive connect route performs incremental consent for
        # the canonical scope set and never disconnects first, so it is safe to
        # reuse as the permission-upgrade path.
        try:
            from flask import url_for

            return url_for("admin_banco_dados_oauth_start", provider=MAIL_PROVIDER)
        except Exception:
            return ""

    account = get_active_cloud_account(conn, MAIL_PROVIDER)
    if not account:
        return {
            "ready": False,
            "reason": "not_connected",
            "provider_connected": False,
            "provider_status": "disconnected",
            "message": CONNECT_MESSAGE,
            "cta_label": CONNECT_CTA,
            "cta_url": _authorize_url(),
            "account_email": "",
        }

    token_json = str(account.get("token_json") or "")
    if not account.get("token_json_available", True) or not token_json:
        return {
            "ready": False,
            "reason": "token_unavailable",
            "provider_connected": False,
            "provider_status": "needs_reconnection",
            "message": CONNECT_MESSAGE,
            "cta_label": CONNECT_CTA,
            "cta_url": _authorize_url(),
            "account_email": str(account.get("account_email") or ""),
        }

    if not token_grants_mail_send(token_json):
        # Files/OneDrive capability is intact; only the mail permission is
        # missing. The account stays "Conectado".
        return {
            "ready": False,
            "reason": "scope_missing",
            "provider_connected": True,
            "provider_status": "connected",
            "message": AUTHORIZE_MAIL_MESSAGE,
            "cta_label": AUTHORIZE_MAIL_CTA,
            "cta_url": _authorize_url(),
            "account_email": str(account.get("account_email") or ""),
        }

    return {
        "ready": True,
        "reason": "",
        "provider_connected": True,
        "provider_status": "connected",
        "message": "",
        "cta_label": "",
        "cta_url": "",
        "account_email": str(account.get("account_email") or ""),
    }


def send_text_email(conn, message: MailMessage) -> dict[str, object]:
    """Send one plain-text e-mail as the connected delegated identity.

    Raises :class:`MailTransportError`.  ``indeterminate=True`` means the send
    may have reached the provider: callers must surface it for explicit human
    resolution rather than retrying automatically.
    """
    if not is_valid_email(message.to_address):
        raise MailTransportError(
            "Endereço de e-mail do destinatário ausente ou inválido.",
            debug_code="INVALID_RECIPIENT",
        )

    status = mail_transport_status(conn)
    if not status["ready"]:
        raise MailTransportError(
            str(status["message"]),
            debug_code=(
                "MAIL_SEND_SCOPE_REQUIRED"
                if status["reason"] == "scope_missing"
                else "AUTH_RECONNECT_REQUIRED"
            ),
        )

    try:
        access_token, _account_email = get_authenticated_access_token(conn, MAIL_PROVIDER)
    except CloudConnectionError as exc:
        raise MailTransportError(
            RECONNECT_MESSAGE, debug_code="AUTH_RECONNECT_REQUIRED"
        ) from exc

    try:
        result = send_mail_with_access_token(
            access_token=access_token,
            to_address=message.to_address.strip(),
            subject=message.subject,
            body_text=message.body_text,
        )
    except MailSendIndeterminate as exc:
        raise MailTransportError(
            sanitize_provider_error(exc),
            debug_code=getattr(exc, "debug_code", "MAIL_SEND_INDETERMINATE"),
            indeterminate=True,
        ) from exc
    except OneDriveServiceError as exc:
        raise MailTransportError(
            sanitize_provider_error(exc),
            debug_code=getattr(exc, "debug_code", "MAIL_SEND_FAILED"),
        ) from exc

    return dict(result)


__all__ = [
    "AUTHORIZE_MAIL_CTA",
    "AUTHORIZE_MAIL_MESSAGE",
    "CONNECT_CTA",
    "CONNECT_MESSAGE",
    "MAIL_PROVIDER",
    "RECONNECT_MESSAGE",
    "MailMessage",
    "MailTransportError",
    "is_valid_email",
    "mail_transport_status",
    "sanitize_provider_error",
    "send_text_email",
]
