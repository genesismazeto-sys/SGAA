# coding: utf-8
"""Access/onboarding lifecycle state, derived from durable evidence only.

WHAT THIS IS NOT
    It is not ``alunos.status`` (Ativo/Inativo), which is an academic fact
    about a student's enrolment. This module answers a different question:
    where is this *login* in its lifecycle -- never created a password yet,
    been sent a usable first-access link, established its own credential, or
    had access ended.

    Since prod-1/v11 it does coincide with "does this login hold a usable
    credential" for every active account -- see THE DEFAULT-PASSWORD CASE
    below -- but it is still derived from the lifecycle evidence, not from a
    login attempt.

THE EVIDENCE, AND ONLY THE EVIDENCE
    Four durable columns decide every state. Nothing here reads a flash
    message, a session, a log line or a global setting:

    * ``usuario_credenciais.acesso_ativo``  -- may this account authenticate
      at all (prod-1/v9);
    * ``usuario_credenciais.estado``        -- ``pending`` while no usable
      credential exists, ``default`` once an administrator explicitly applied
      the shared profile default, ``personal`` once the user or an
      administrator installed an individual password (prod-1/v11);
    * ``senha_tokens.sent_at``              -- a mail provider CONFIRMED
      sending this token (prod-1/v10). ``NULL`` for a token that failed, for
      one whose provider result was indeterminate, and for every token issued
      before v10;
    * ``senha_tokens.consumed_at`` / ``invalidated_at`` / ``expires_at`` --
      whether the link that confirmed delivery carried is still usable.

    ``sent_at`` is what makes ``Disponibilizado`` honest. A token merely
    existing proves an administrator clicked, not that anything was delivered;
    before v10 a confirmed send and an unconfirmed one were indistinguishable
    in the database. Note the ceiling: a confirmed send means SGAA handed the
    message to the provider successfully. It is NOT a read receipt, and no
    state here claims the recipient opened anything.

THE DEFAULT-PASSWORD CASE
    The column answers "where is this login in its lifecycle". Provisioning
    ends when the account holds a credential it can use, and there are exactly
    two ways to hold one: an individual password (``personal``), or the shared
    default an administrator explicitly applied to this account (``default``).
    Both are ``Ativo``.

    Before prod-1/v11 ``default`` was ``Pendente``, and rightly: it was also
    what an account created without a password was stored as, and whether it
    could log in hung on a global switch. v11 moved both of those out --
    blank creation is ``pending`` and the switch is retired -- so a ``default``
    row now means one deliberate administrative act that stays usable until
    somebody changes it. Calling that "awaiting a credential" would be false.

    ``pending`` is the only state still awaiting one, and the only state whose
    pill follows first-access delivery evidence.
"""

from __future__ import annotations

from app.status_presentation import (
    ACCESS_STATUS_ATIVO,
    ACCESS_STATUS_DISPONIBILIZADO,
    ACCESS_STATUS_EXPIRADO,
    ACCESS_STATUS_PENDENTE,
    ACCESS_STATUS_REVOGADO,
)


#: Selects the newest CONFIRMED-SENT first-access delivery per account, with
#: the lifecycle of the link it carried. Rows with ``sent_at IS NULL`` are
#: excluded at the source: an unconfirmed send is not evidence of a send.
#:
#: "Newest" is ``sent_at`` then ``id``, so a resend always supersedes the
#: delivery before it and there is exactly one authoritative row per account.
_LATEST_CONFIRMED_FIRST_ACCESS_SQL = """
SELECT t.usuario_id AS usuario_id,
       t.sent_at    AS sent_at,
       t.expires_at AS expires_at,
       t.consumed_at AS consumed_at,
       t.invalidated_at AS invalidated_at
  FROM senha_tokens t
 WHERE t.purpose='first_access'
   AND t.sent_at IS NOT NULL
   AND t.id = (
        SELECT n.id FROM senha_tokens n
         WHERE n.usuario_id = t.usuario_id
           AND n.purpose='first_access'
           AND n.sent_at IS NOT NULL
         ORDER BY n.sent_at DESC, n.id DESC
         LIMIT 1
   )
"""


def _db_now(conn) -> str:
    """SQLite's own UTC clock, the one every token timestamp was written with.

    Comparing against a Python clock would risk a timezone skew deciding
    whether an onboarding link counts as expired.
    """
    return str(conn.execute("SELECT datetime('now')").fetchone()[0])


def derive_access_status(
    *,
    acesso_ativo,
    credential_state,
    confirmed_sent_at=None,
    confirmed_expires_at=None,
    confirmed_consumed_at=None,
    confirmed_invalidated_at=None,
    now: str,
) -> str:
    """The onboarding state for one account, from its durable evidence.

    Pure: it takes values, not a connection, so every branch is directly
    testable. The ladder is ordered by authority -- a later rule can never
    contradict an earlier one.
    """
    # A missing credential row is an incomplete account, not a revoked one:
    # nothing was ever ended. It has no individual password either, so the
    # honest reading is the same as a freshly created access.
    if acesso_ativo is None:
        return ACCESS_STATUS_PENDENTE

    # Revocation outranks everything. An administrator deliberately ended this
    # login, and _revoke_usuario_access also resets estado and kills every
    # outstanding token, so no downstream rule could disagree anyway.
    if int(acesso_ativo) == 0:
        return ACCESS_STATUS_REVOGADO

    # A usable credential exists and access is live. This is the single
    # definition of Ativo, which is why it covers every way to get one: the
    # user completed first access, an administrator typed a password at
    # creation, a reactivation supplied one, or an administrator explicitly
    # applied the shared default. No e-mail is required.
    if str(credential_state or "") in ("personal", "default"):
        return ACCESS_STATUS_ATIVO

    # From here the account is active and pending: it holds no usable
    # credential. Only a CONFIRMED delivery can move it off Pendente.
    if not confirmed_sent_at:
        return ACCESS_STATUS_PENDENTE

    # The delivery was used, yet the account is pending again: the personal
    # password it created has since been taken away -- a revocation followed
    # by a reactivation without a password does exactly that. It is not
    # waiting on a link, and no link died: Pendente, not Expirado.
    if confirmed_consumed_at:
        return ACCESS_STATUS_PENDENTE

    # A confirmed delivery whose link no longer works. Two ways to get here and
    # they are one operational situation -- an e-mail went out, nothing usable
    # remains, an administrator must send again:
    #   * invalidated, i.e. superseded by a later send that then failed, or
    #     cancelled by a credential write;
    #   * past its expires_at.
    if confirmed_invalidated_at:
        return ACCESS_STATUS_EXPIRADO
    if str(confirmed_expires_at or "") <= str(now):
        return ACCESS_STATUS_EXPIRADO

    # Confirmed delivery, link still usable, onboarding not finished.
    return ACCESS_STATUS_DISPONIBILIZADO


def access_status_map(conn, usuario_ids) -> dict[int, str]:
    """Onboarding state for each requested account, in one pair of queries.

    Built for the Acesso list, which renders a page of accounts at a time and
    must not issue a query per row.
    """
    ids = sorted({int(value) for value in usuario_ids if value is not None})
    if not ids:
        return {}
    placeholders = ", ".join("?" for _ in ids)

    credentials = {
        int(row[0]): (row[1], row[2])
        for row in conn.execute(
            f"SELECT usuario_id,acesso_ativo,estado FROM usuario_credenciais"
            f" WHERE usuario_id IN ({placeholders})",
            ids,
        ).fetchall()
    }
    deliveries = {
        int(row["usuario_id"]): row
        for row in conn.execute(
            f"SELECT * FROM ({_LATEST_CONFIRMED_FIRST_ACCESS_SQL})"
            f" WHERE usuario_id IN ({placeholders})",
            ids,
        ).fetchall()
    }
    now = _db_now(conn)

    resolved: dict[int, str] = {}
    for usuario_id in ids:
        acesso_ativo, credential_state = credentials.get(usuario_id, (None, None))
        delivery = deliveries.get(usuario_id)
        resolved[usuario_id] = derive_access_status(
            acesso_ativo=acesso_ativo,
            credential_state=credential_state,
            confirmed_sent_at=delivery["sent_at"] if delivery else None,
            confirmed_expires_at=delivery["expires_at"] if delivery else None,
            confirmed_consumed_at=delivery["consumed_at"] if delivery else None,
            confirmed_invalidated_at=delivery["invalidated_at"] if delivery else None,
            now=now,
        )
    return resolved


def access_status_for_usuario(conn, usuario_id: int) -> str:
    """Onboarding state for a single account."""
    return access_status_map(conn, [usuario_id])[int(usuario_id)]


__all__ = [
    "access_status_for_usuario",
    "access_status_map",
    "derive_access_status",
]
