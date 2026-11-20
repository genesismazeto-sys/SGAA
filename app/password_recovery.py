"""Self-service password recovery: which account a public request may reach.

Two public surfaces ask the same question. The recovery request
(``/esqueci-minha-senha``) mails a reset link only to an account that may still
sign in; the page of a dead link (``/redefinir-senha``, ``/primeiro-acesso``)
offers to send a new one and may pre-fill the address only for such an
account. The request answers the same way whatever the outcome; what the dead
link's page reveals, and to whom, is bounded by ``expired_link_email``.
"""

from __future__ import annotations

import datetime as dt

from app.password_tokens import (
    PASSWORD_TOKEN_TTLS,
    PURPOSE_PASSWORD_RESET,
    expired_password_token_owner,
)
from app.user_accounts import usuario_access_is_active


#: What the public recovery mails, whatever link the user lost: a reset link.
RECOVERY_LINK_PURPOSE = PURPOSE_PASSWORD_RESET

#: How long after its expiry a dead link may still pre-fill its address.
#: Beyond it the link sits in an old mailbox, a shared computer's history or a
#: pasted message, and the page offers an empty field instead.
PREFILL_AFTER_EXPIRY = dt.timedelta(hours=24)


def recovery_link_ttl() -> dt.timedelta:
    """The validity of the link a recovery request sends."""
    return PASSWORD_TOKEN_TTLS[RECOVERY_LINK_PURPOSE]


def recovery_account(conn, email: str):
    """The account a recovery request for ``email`` may mail, or ``None``.

    A revoked access, an account without credentials and a student whose
    enrolment is not ``Ativo`` receive no link.
    """
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
    if not usuario_access_is_active(conn, int(row["id"])):
        return None
    if str(row["tipo"] or "").strip().lower() == "aluno":
        if str(row["aluno_status"] or "Ativo").strip().lower() != "ativo":
            return None
    return row


def expired_link_email(conn, raw_token: str, *, purpose: str) -> str:
    """The address a dead link's page may pre-fill, or ``""``.

    Identification is safe only for a link that expired untouched, at most
    ``PREFILL_AFTER_EXPIRY`` ago, while its account can still recover:
    ``expired_password_token_owner`` guarantees the address is the very one
    the link was mailed to, so whoever holds the link learns the address it
    was sent to and, by a blank field, that the account changed since -- no
    other account and no other address. An unknown token, a used link, a link
    invalidated while live (superseded, a password or address change, a
    revocation), an older one and an account that could not receive a new
    link all leave the field blank.
    """
    owner = expired_password_token_owner(
        conn, raw_token, purpose=purpose, expired_within=PREFILL_AFTER_EXPIRY
    )
    if owner is None:
        return ""
    usuario_id, email = owner
    account = recovery_account(conn, email)
    # usuarios.email is unique, so this is the same account; the comparison
    # keeps the address from ever naming another one.
    if account is None or int(account["id"]) != usuario_id:
        return ""
    return email


__all__ = [
    "PREFILL_AFTER_EXPIRY",
    "RECOVERY_LINK_PURPOSE",
    "expired_link_email",
    "recovery_account",
    "recovery_link_ttl",
]
