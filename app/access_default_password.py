# coding: utf-8
"""UI-B09: who may receive the shared profile default password, and why not.

WHAT THE ACTION MEANS
    "Aplicar senha padrão" replaces one account's current credential with the
    password configured for its access profile in ``configuracoes_acesso``, and
    marks the credential ``default``.  It is not a reset-by-e-mail, not a
    first-access delivery, not root recovery and not a reactivation.

    Since prod-1/v11 it is the ONLY normal way an account comes to authenticate
    with the shared default.  There is no global switch: an account created
    without a password is ``pending`` and cannot log in until either its first
    access completes or an administrator applies the default here.  It may be
    applied from ``pending``, ``personal`` or ``default``.

    Because it installs a *shared* secret, the decision of who may receive it is
    a product rule, not a convenience.  This module is its single owner, so the
    floating action bar and the endpoint can never disagree about the answer.

THE LADDER
    Ordered by authority; a later rule can never contradict an earlier one.

    1. the root administrator.  Root is the only recovery path into a
       locked-out installation.  Handing it a password that every administrator
       can read off the settings panel would put that path one shared secret
       away from anyone with access to this screen;
    2. revoked access.  An administrator deliberately ended this login;
       installing a usable shared password on it is a contradiction, and the
       way back is the explicit reactivation in ``admin_acesso_salvar``.

    That is the whole rule.  ``estado`` is deliberately NOT in it: a
    ``pending`` or ``default`` account is as eligible as a ``personal`` one.
    (Before v11 a global ``default_passwords_enabled`` switch sat above both
    rungs; it is retired, and nothing here reads it.)

WHY THERE IS NO "ALREADY USES THE CURRENT DEFAULT" REFUSAL
    Applying the shared default is an explicit administrative credential reset,
    not an assignment of a string.  It hashes the value configured NOW, with a
    fresh salt, into this account's own ``usuarios.senha``, bumps
    ``auth_version`` -- which ends every live session -- and invalidates any
    first-access or reset link still in flight.  Those effects are the point of
    the action and they happen whether or not the resulting plaintext is the one
    the account already had, so there is no no-op to detect and nothing to
    refuse.  Re-applying to a ``default`` account is therefore how it is brought
    onto a since-edited profile value: saving the profile defaults rewrites
    ``configuracoes_acesso`` only and never touches an account's hash.

    The corollary is the performance contract.  Deciding eligibility never
    compares a stored hash against anything: the two questions "may this
    account receive the default" and "what is its password right now" are
    unrelated.  ``/admin/acesso`` applies no LIMIT unless the client asks for
    one, so it renders the whole active population; a per-row PBKDF2
    verification there would be ~226ms EACH.  Every rule above reads a durable
    column instead, so the list costs one batched query for any number of rows.
    ``tests/test_access_default_password_ui_b09.py`` guards this by counting
    password verifications during a render and requiring zero.

NOTHING HERE WRITES
    Eligibility is a question, not an event.  Every function is read-only.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.root_admin import resolve_root_admin_id


#: Concise, actionable, and the same text on both layers: the action bar shows
#: it as the disabled button's reason, the endpoint flashes it on refusal.
#:
#: They live here rather than in ``app/views/**`` because this module -- not the
#: handler -- owns the vocabulary, exactly as ``app/status_presentation.py``
#: owns the lifecycle labels it renders.
REASON_ROOT_ADMIN = "Ação indisponível para o administrador raiz."
REASON_REVOKED = "Acesso revogado."


@dataclass(frozen=True)
class DefaultPasswordEligibility:
    """May this account receive the shared profile default, and if not, why."""

    allowed: bool
    reason: str = ""


_ALLOWED = DefaultPasswordEligibility(True, "")


def decide_default_password_eligibility(
    *,
    is_root_admin: bool,
    acesso_ativo,
) -> DefaultPasswordEligibility:
    """The whole rule, as a pure function of two facts."""
    if is_root_admin:
        return DefaultPasswordEligibility(False, REASON_ROOT_ADMIN)
    # A missing credential row is treated as inactive, the same reading
    # ``usuario_access_is_active`` already applies: an account with no
    # credential is structurally incomplete, not implicitly permitted.
    if acesso_ativo is None or int(acesso_ativo) != 1:
        return DefaultPasswordEligibility(False, REASON_REVOKED)
    return _ALLOWED


def default_password_eligibility_map(
    conn, usuario_ids
) -> dict[int, DefaultPasswordEligibility]:
    """Eligibility for a whole page of accounts, in one batched query.

    Built for the Acesso list, which renders every active account at a time and
    must not issue a query -- let alone a key derivation -- per row.
    """
    ids = sorted({int(value) for value in usuario_ids if value is not None})
    if not ids:
        return {}

    root_admin_id = resolve_root_admin_id(conn)
    placeholders = ", ".join("?" for _ in ids)
    active = {
        int(row[0]): row[1]
        for row in conn.execute(
            f"SELECT usuario_id,acesso_ativo FROM usuario_credenciais"
            f" WHERE usuario_id IN ({placeholders})",
            ids,
        ).fetchall()
    }
    return {
        usuario_id: decide_default_password_eligibility(
            is_root_admin=root_admin_id is not None and usuario_id == root_admin_id,
            acesso_ativo=active.get(usuario_id),
        )
        for usuario_id in ids
    }


def default_password_eligibility(conn, usuario_id: int) -> DefaultPasswordEligibility:
    """Eligibility for one account -- the answer the endpoint must obey.

    Same ladder, same columns, one row.  There is no second, stricter tier: the
    action bar and the endpoint resolve identical questions, so no state exists
    in which the bar offers the action and the endpoint categorically refuses
    it.
    """
    usuario_id = int(usuario_id)
    # An account with no credential row resolves to REASON_REVOKED through the
    # ladder's own missing-row reading -- the map always answers for every id
    # it is asked about.
    return default_password_eligibility_map(conn, [usuario_id])[usuario_id]


__all__ = [
    "REASON_REVOKED",
    "REASON_ROOT_ADMIN",
    "DefaultPasswordEligibility",
    "decide_default_password_eligibility",
    "default_password_eligibility",
    "default_password_eligibility_map",
]
