"""Generic outbound mail transport over the connected Microsoft identity.

Deliberately knows nothing about Requisições: no request ids, no presets, no
decision events.  It accepts a recipient, a subject and a plain-text body.

Reuse targets (designed for, not implemented here):

* request-decision e-mails -- the first consumer;
* first-access account e-mail;
* password-recovery e-mail.

See ``docs/mail/AUTH_EMAIL_EXTENSION_POINT.md`` for the auth contracts those
later consumers must honour.

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

RECONNECT_MESSAGE = (
    "Reconecte o OneDrive/Microsoft para autorizar o envio de e-mails."
)

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
    """Read-only readiness probe. Never triggers an interactive reconnect."""
    from app.cloud_connections import get_active_cloud_account

    account = get_active_cloud_account(conn, MAIL_PROVIDER)
    if not account:
        return {
            "ready": False,
            "reason": "not_connected",
            "message": RECONNECT_MESSAGE,
            "account_email": "",
        }
    token_json = str(account.get("token_json") or "")
    if not account.get("token_json_available", True) or not token_json:
        return {
            "ready": False,
            "reason": "token_unavailable",
            "message": RECONNECT_MESSAGE,
            "account_email": str(account.get("account_email") or ""),
        }
    if not token_grants_mail_send(token_json):
        return {
            "ready": False,
            "reason": "scope_missing",
            "message": RECONNECT_MESSAGE,
            "account_email": str(account.get("account_email") or ""),
        }
    return {
        "ready": True,
        "reason": "",
        "message": "",
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
            str(status["message"]), debug_code="MAIL_SEND_SCOPE_REQUIRED"
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
    "MAIL_PROVIDER",
    "RECONNECT_MESSAGE",
    "MailMessage",
    "MailTransportError",
    "is_valid_email",
    "mail_transport_status",
    "sanitize_provider_error",
    "send_text_email",
]
