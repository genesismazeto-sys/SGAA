# coding: utf-8
"""Root administrator identity and break-glass recovery credential.

WHY THIS EXISTS
    An administrator account can be left without a usable password credential
    -- ``pending`` since prod-1/v11 (which is exactly where the built-in
    administrator of a database whose ``default_passwords_enabled`` switch was
    off lands after the v11 migration).  For the one account able to fix every
    other, that would mean no in-product recovery.  This module gives exactly
    one identity a second, independent authentication path so the product can
    always be recovered.

IDENTITY
    The root administrator is NOT a numeric id.  It is the account holding the
    configured bootstrap administrator e-mail -- the identity contract this
    application already had (``BOOTSTRAP_ADMIN_EMAIL`` / the
    ``APP_BOOTSTRAP_ADMIN_EMAIL`` environment variable, consumed by
    ``app/db.py``'s bootstrap).  Two guards make that safe to key on:

    * ``tipo = 'admin'`` is required.  The target root address may already
      belong to an ``aluno`` in a deployed database; such a row must never be
      resolved as root.
    * a legacy fallback keeps an already-deployed database recoverable.  When
      no admin holds the configured address, the historical bootstrap address
      is consulted.  Without it, changing the shipped default would silently
      strip root protection -- and the master key -- from every existing
      installation, which is the exact failure this module exists to prevent.

MASTER KEY
    The break-glass credential is compared against a PBKDF2 hash, never a
    plaintext, and the hash is configuration, not source: it is read from
    ``APP_ROOT_MASTER_KEY_HASH`` (or the ``ROOT_MASTER_KEY_HASH`` app config).
    With no hash configured the master-key path is simply unavailable -- the
    root keeps its ordinary password login and every other protection.  It is deliberately NOT a database row: it is not a shared
    profile default, it does not live in ``configuracoes_acesso``, and it is
    not a ``usuario_credenciais.estado``.  It is independent of the credential
    state, and it survives any number of personal-password changes.

    It is never logged and never rendered.
"""

from __future__ import annotations

import os

from app.security.passwords import check_password


# The address a fresh installation seeds when ``APP_BOOTSTRAP_ADMIN_EMAIL`` is
# not configured.  ``app/db.py`` and ``app/__init__.py`` both resolve the
# bootstrap address through here.  It is a reserved, non-deliverable
# placeholder (RFC 2606 ``.invalid``): the real root address of an installation
# is configuration, never source.
DEFAULT_ROOT_ADMIN_EMAIL = "root-admin@example.invalid"

# The address shipped before the one above.  Consulted only as a fallback, and
# only for a ``tipo = 'admin'`` row, so an installation created earlier keeps a
# working recovery path until its root e-mail is migrated.
LEGACY_ROOT_ADMIN_EMAIL = "admin@ej.edu.br"



def _configured(key: str, env: str, fallback: str) -> str:
    """Read a value from the Flask config when there is one, else the env."""
    try:
        from flask import current_app

        value = current_app.config.get(key)
        if value:
            return str(value)
    except Exception:
        # No application context (migrations, tools, tests touching the
        # helpers directly).  The environment is still authoritative.
        pass
    return (os.getenv(env) or fallback).strip()


def root_admin_email() -> str:
    """The address a root administrator is expected to hold."""
    return _configured(
        "BOOTSTRAP_ADMIN_EMAIL", "APP_BOOTSTRAP_ADMIN_EMAIL", DEFAULT_ROOT_ADMIN_EMAIL
    ).strip().lower()


def _root_master_key_hash() -> str:
    """The configured break-glass hash, or "" when none is configured."""
    return _configured("ROOT_MASTER_KEY_HASH", "APP_ROOT_MASTER_KEY_HASH", "")


def root_master_key_configured() -> bool:
    """True when this installation has a break-glass credential configured."""
    return bool(_root_master_key_hash())


def resolve_root_admin_id(conn) -> int | None:
    """The usuarios.id of the root administrator, or None when absent.

    Only an ``admin`` row can be root.  The configured address wins; the
    historical address is a fallback for databases created before the default
    changed.
    """
    configured = root_admin_email()
    for candidate in (configured, LEGACY_ROOT_ADMIN_EMAIL):
        if not candidate:
            continue
        row = conn.execute(
            "SELECT id FROM usuarios WHERE LOWER(email) = ? AND tipo = 'admin' ORDER BY id LIMIT 1",
            (candidate.strip().lower(),),
        ).fetchone()
        if row:
            return int(row[0])
    return None


def is_root_admin(conn, usuario_id: int | None) -> bool:
    """True when this account is the one protected root administrator."""
    if not usuario_id:
        return False
    root_id = resolve_root_admin_id(conn)
    return root_id is not None and int(usuario_id) == root_id


def verify_root_master_key(password: str) -> bool:
    """Constant-time check of the break-glass credential.

    Caller MUST have already established that the account is the root
    administrator: this function knows nothing about identity.
    """
    if not password:
        return False
    configured_hash = _root_master_key_hash()
    if not configured_hash:
        # No credential configured: the break-glass path does not exist here.
        return False
    return check_password(configured_hash, str(password))


class RootAdminEmailCollision(Exception):
    """The target root address is already held by another account."""

    def __init__(self, holder_id: int, holder_tipo: str, holder_nome: str) -> None:
        self.holder_id = int(holder_id)
        self.holder_tipo = str(holder_tipo or "")
        self.holder_nome = str(holder_nome or "")
        super().__init__(
            f"root address already held by usuarios.id={self.holder_id} "
            f"(tipo={self.holder_tipo!r})"
        )


def migrate_root_admin_email(conn, *, target_email: str | None = None) -> dict[str, object]:
    """Move the root administrator onto the configured address, in place.

    Bounded on purpose.  It updates exactly one column of exactly one row, so
    ``usuarios.id`` -- and with it the credential row, the permission
    overrides, and every historical FK pointing at the account -- is preserved.
    The account is never deleted and recreated, and ``auth_version`` is left
    alone: changing an address is not a credential change and must not sign
    existing sessions out.

    Raises ``RootAdminEmailCollision`` when the target address belongs to a
    different account.  That is a decision for a human: silently reassigning
    somebody else's address, or merging two identities, is never correct.
    """
    target = (target_email or root_admin_email()).strip().lower()
    if not target:
        raise ValueError("a target root address is required")

    root_id = resolve_root_admin_id(conn)
    if root_id is None:
        return {"migrated": False, "reason": "no_root_admin", "root_id": None, "email": target}

    current = str(
        conn.execute("SELECT email FROM usuarios WHERE id = ?", (root_id,)).fetchone()[0] or ""
    ).strip().lower()
    if current == target:
        return {"migrated": False, "reason": "already_current", "root_id": root_id, "email": target}

    holder = conn.execute(
        "SELECT id, tipo, nome FROM usuarios WHERE LOWER(email) = ? AND id <> ?",
        (target, root_id),
    ).fetchone()
    if holder:
        raise RootAdminEmailCollision(holder[0], holder[1], holder[2])

    conn.execute("UPDATE usuarios SET email = ? WHERE id = ?", (target, root_id))
    # An admin row may also carry an alunos mirror from historical data; keep
    # the two addresses consistent without touching anything else.
    conn.execute(
        "UPDATE alunos SET email = ? WHERE usuario_id = ?", (target, root_id)
    )
    return {"migrated": True, "reason": "ok", "root_id": root_id, "email": target, "previous": current}


__all__ = [
    "DEFAULT_ROOT_ADMIN_EMAIL",
    "RootAdminEmailCollision",
    "migrate_root_admin_email",
    "LEGACY_ROOT_ADMIN_EMAIL",
    "is_root_admin",
    "resolve_root_admin_id",
    "root_admin_email",
    "root_master_key_configured",
    "verify_root_master_key",
]
