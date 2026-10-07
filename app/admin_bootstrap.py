# coding: utf-8
"""Supported offline first/full administrator bootstrap (R5).

WHY THIS EXISTS
    A PostgreSQL database is provisioned empty (``python -m app.pg_schema
    provision``) and the runtime never seeds an account there, so a fresh or
    disaster-recovered installation has no way in.  A migrated database can be
    just as locked out: its only full administrator may hold a ``pending``
    credential, which login refuses by state.  Neither may depend on the
    password e-mail flow.  This module is the one supported offline way to end
    up with exactly one usable full administrator.

WHAT IT DOES -- AND WHAT IT REFUSES
    The operator names the administrator by e-mail and types the password at a
    hidden prompt.  Under one write transaction the command either

    * CREATES the first full administrator when the database holds no full
      administrator at all (greenfield / disaster recovery); or
    * ACTIVATES the named full administrator in place when its credential is
      ``pending``: same ``usuarios.id``, same access level and overrides, a new
      personal password through the production password writer (which bumps
      ``auth_version`` and retires outstanding first-access/reset links).

    It is not a password-reset tool.  It refuses whenever any login-capable
    full administrator exists (that administrator owns password management from
    then on), when the named account is not a full administrator (no role is
    ever escalated), when the named account's access was revoked, and whenever
    the rows cannot be classified safely.  There is no ``--force``.

    "Full administrator" is the production reading: ``tipo = 'admin'``, an
    access level that canonicalizes to ``admin_total`` and effective scopes --
    profile defaults merged with per-account overrides -- that are ``full`` on
    every resource.  "Login-capable" is the login route's reading: a credential
    row, ``acesso_ativo = 1`` and a state whose hash login verifies
    (``PASSWORD_LOGIN_CREDENTIAL_STATES``).  An applied ``default`` credential is
    login-capable, so it is refused like a ``personal`` one.

    The password is never accepted as an argument, never echoed, never logged.
"""

from __future__ import annotations

import getpass
import sys
from dataclasses import dataclass

from app.admin_access import _fetch_user_access_overrides
from app.auth import canonicalize_access_level, merge_resource_scopes
from app.db import database_engine, lock_password_account, write_transaction
from app.security.passwords import hash_password
from app.user_accounts import (
    CREDENTIAL_STATE_PENDING,
    CREDENTIAL_STATE_PERSONAL,
    credential_state_allows_password_login,
    create_usuario_with_access_level,
    get_usuario_credential,
    require_valid_email,
    set_usuario_password_hash,
)


FULL_ADMIN_ACCESS_LEVEL = "admin_total"
DEFAULT_ADMIN_NAME = "Administrador"

OUTCOME_CREATED = "created"
OUTCOME_ACTIVATED = "activated"

REFUSED_USABLE_ADMIN_EXISTS = "usable_full_admin_exists"
REFUSED_NOT_FULL_ADMIN = "target_not_full_admin"
REFUSED_TARGET_REVOKED = "target_access_revoked"
REFUSED_UNACTIVATED_ADMIN_ELSEWHERE = "unactivated_full_admin_elsewhere"
REFUSED_AMBIGUOUS_TARGET = "ambiguous_target"
REFUSED_UNCLASSIFIABLE = "unclassifiable_state"
REFUSED_INVALID_EMAIL = "invalid_email"

_REFUSAL_MESSAGES = {
    REFUSED_USABLE_ADMIN_EXISTS: (
        "a login-capable full administrator already exists; manage passwords "
        "from inside the application"
    ),
    REFUSED_NOT_FULL_ADMIN: (
        "the account holding this e-mail is not a full administrator; "
        "bootstrap never changes an account's role"
    ),
    REFUSED_TARGET_REVOKED: (
        "this full administrator's access was revoked; bootstrap does not "
        "reactivate access"
    ),
    REFUSED_UNACTIVATED_ADMIN_ELSEWHERE: (
        "full administrator account(s) already exist without a usable "
        "credential; rerun with the e-mail of the one to activate"
    ),
    REFUSED_AMBIGUOUS_TARGET: "more than one account matches this e-mail",
    REFUSED_UNCLASSIFIABLE: "the account state cannot be classified safely",
    REFUSED_INVALID_EMAIL: "invalid e-mail",
}


class AdminBootstrapRefused(Exception):
    """The bootstrap was refused; nothing was written."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        message = _REFUSAL_MESSAGES.get(reason, reason)
        super().__init__(f"{message} ({detail})" if detail else message)


@dataclass(frozen=True)
class AdminBootstrapPlan:
    outcome: str
    usuario_id: int | None
    email: str


@dataclass(frozen=True)
class AdminBootstrapResult:
    outcome: str
    usuario_id: int
    email: str


def _normalize_email(email) -> str:
    return str(email or "").strip().lower()


def _is_full_admin(conn, row) -> bool | None:
    """True/False for a classifiable account, ``None`` when it cannot be read.

    An access level the product does not recognise is not silently mapped to
    a profile (``canonicalize_access_level``'s usual fallback): it is
    unclassifiable.
    """
    if str(row["tipo"] or "") != "admin":
        return False
    level = canonicalize_access_level(row["nivel_acesso"], fallback="")
    if not level:
        return None
    if level != FULL_ADMIN_ACCESS_LEVEL:
        return False
    scopes = merge_resource_scopes(level, _fetch_user_access_overrides(conn, row["id"]))
    return all(scope == "full" for scope in scopes.values())


def _is_login_capable(credential) -> bool:
    return (
        credential is not None
        and int(credential["acesso_ativo"]) == 1
        and credential_state_allows_password_login(credential["estado"])
    )


def _full_admin_ids(conn) -> list[int]:
    """Every full administrator; fails closed on an unreadable ``admin`` row.

    Such a row could be the administrator the operator means, and the product's
    own startup normalization would promote an empty level to ``admin_total``
    behind a "no administrator exists" reading.
    """
    rows = conn.execute(
        "SELECT id,tipo,nivel_acesso FROM usuarios WHERE tipo = 'admin' ORDER BY id"
    ).fetchall()
    ids = []
    for row in rows:
        full_admin = _is_full_admin(conn, row)
        if full_admin is None:
            raise AdminBootstrapRefused(REFUSED_UNCLASSIFIABLE, "access level")
        if full_admin:
            ids.append(int(row["id"]))
    return ids


def _usable_full_admin_ids(conn, admin_ids) -> list[int]:
    return [
        usuario_id
        for usuario_id in admin_ids
        if _is_login_capable(get_usuario_credential(conn, usuario_id))
    ]


def classify_admin_bootstrap(conn, email) -> AdminBootstrapPlan:
    """Read-only decision for ``email``; raises ``AdminBootstrapRefused``.

    Run again by ``bootstrap_admin`` inside its write transaction, so the
    decision that is acted on is never a stale one.
    """
    target_email = _normalize_email(email)
    targets = conn.execute(
        "SELECT id,email,tipo,nivel_acesso FROM usuarios WHERE LOWER(email) = ? ORDER BY id",
        (target_email,),
    ).fetchall()
    if len(targets) > 1:
        raise AdminBootstrapRefused(REFUSED_AMBIGUOUS_TARGET)

    if targets and _is_full_admin(conn, targets[0]) is None:
        raise AdminBootstrapRefused(REFUSED_UNCLASSIFIABLE, "access level")
    full_admin_ids = _full_admin_ids(conn)
    usable_ids = _usable_full_admin_ids(conn, full_admin_ids)

    if not targets:
        if usable_ids:
            raise AdminBootstrapRefused(REFUSED_USABLE_ADMIN_EXISTS)
        if full_admin_ids:
            raise AdminBootstrapRefused(
                REFUSED_UNACTIVATED_ADMIN_ELSEWHERE, f"count={len(full_admin_ids)}"
            )
        try:
            require_valid_email(target_email)
        except ValueError:
            raise AdminBootstrapRefused(REFUSED_INVALID_EMAIL) from None
        return AdminBootstrapPlan(OUTCOME_CREATED, None, target_email)

    target = targets[0]
    target_id = int(target["id"])
    if not _is_full_admin(conn, target):
        raise AdminBootstrapRefused(REFUSED_NOT_FULL_ADMIN)
    credential = get_usuario_credential(conn, target_id)
    if credential is None:
        raise AdminBootstrapRefused(REFUSED_UNCLASSIFIABLE, "missing credential")
    if int(credential["acesso_ativo"]) != 1:
        raise AdminBootstrapRefused(REFUSED_TARGET_REVOKED)
    if usable_ids:
        # The target itself, or any other full administrator, can already log in.
        raise AdminBootstrapRefused(REFUSED_USABLE_ADMIN_EXISTS)
    if str(credential["estado"] or "") != CREDENTIAL_STATE_PENDING:
        raise AdminBootstrapRefused(REFUSED_UNCLASSIFIABLE, "credential state")
    return AdminBootstrapPlan(OUTCOME_ACTIVATED, target_id, str(target["email"]))


def _lock_account_tables(conn) -> None:
    """Serialize the decision with every account writer (PostgreSQL).

    ``SHARE ROW EXCLUSIVE`` conflicts with itself and with row writes, so two
    bootstraps -- or a bootstrap and a concurrent account/credential change --
    cannot both act on the same "no usable administrator" reading.  Readers,
    including login, are not blocked.  SQLite's ``BEGIN IMMEDIATE`` already
    excludes every other writer.
    """
    if database_engine(conn) != "postgres":
        return
    conn.execute("LOCK TABLE usuarios, usuario_credenciais IN SHARE ROW EXCLUSIVE MODE")


def bootstrap_admin(
    conn,
    email,
    password_hash: str,
    *,
    nome: str = DEFAULT_ADMIN_NAME,
) -> AdminBootstrapResult:
    """Create or activate the full administrator, atomically.

    ``password_hash`` is computed by the caller (``hash_password``) before the
    transaction, so PBKDF2 never runs under the lock.  Every write goes through
    the production account owners inside one ``write_transaction``: a refusal
    or any failure leaves no user, no credential and no changed state behind.
    """
    if not password_hash:
        raise ValueError("a password hash is required")
    with write_transaction(conn):
        _lock_account_tables(conn)
        plan = classify_admin_bootstrap(conn, email)
        if plan.outcome == OUTCOME_CREATED:
            created = create_usuario_with_access_level(
                conn,
                str(nome or "").strip() or DEFAULT_ADMIN_NAME,
                plan.email,
                password_hash,
                "admin",
                FULL_ADMIN_ACCESS_LEVEL,
                credential_state=CREDENTIAL_STATE_PERSONAL,
            )
            usuario_id = int(created.usuario_id)
        else:
            usuario_id = int(plan.usuario_id)
            lock_password_account(conn, usuario_id)
            set_usuario_password_hash(
                conn,
                usuario_id,
                password_hash,
                credential_state=CREDENTIAL_STATE_PERSONAL,
            )
    return AdminBootstrapResult(plan.outcome, usuario_id, plan.email)


# ---------------------------------------------------------------------------
# command line
# ---------------------------------------------------------------------------


_USAGE = (
    "usage: python -m app.admin_bootstrap --email EMAIL [--name NAME]\n"
    "\n"
    "Offline first/full administrator bootstrap for the configured database\n"
    "(DATABASE_URL for PostgreSQL). Creates the first full administrator when\n"
    "none exists, or activates the named full administrator whose credential\n"
    "is pending. Refuses when a login-capable full administrator exists, when\n"
    "the e-mail belongs to a non-full-administrator, and on any ambiguous or\n"
    "unclassifiable state. The password is read from a hidden prompt, twice.\n"
)

_MESSAGES = {
    OUTCOME_CREATED: "bootstrap-admin: full administrator created",
    OUTCOME_ACTIVATED: "bootstrap-admin: pending full administrator activated",
}


class _UsageError(Exception):
    pass


def _parse_arguments(arguments):
    values = {"email": None, "name": DEFAULT_ADMIN_NAME}
    pending = list(arguments)
    while pending:
        flag = pending.pop(0)
        if flag not in ("--email", "--name") or not pending:
            raise _UsageError(flag)
        values[flag[2:]] = pending.pop(0)
    if not _normalize_email(values["email"]):
        raise _UsageError("--email")
    return values


def _open_connection():
    """A production connection for the configured backend, outside requests."""
    from flask import Flask

    from app.db import get_db_connection

    context = Flask(__name__).app_context()
    context.push()
    try:
        return context, get_db_connection()
    except BaseException:
        context.pop()
        raise


def _close_connection(context) -> None:
    from app.db import close_db_connection

    try:
        close_db_connection(None)
    finally:
        context.pop()


def _read_password(prompt) -> str | None:
    password = prompt("New administrator password: ")
    if not password:
        print("error: an empty password is not accepted", file=sys.stderr)
        return None
    if prompt("Confirm password: ") != password:
        print("error: the passwords do not match", file=sys.stderr)
        return None
    return password


def main(argv=None, *, prompt=getpass.getpass) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] in {"-h", "--help"}:
        print(_USAGE)
        return 0
    try:
        options = _parse_arguments(arguments)
    except _UsageError:
        print(_USAGE, file=sys.stderr)
        return 2

    try:
        context, conn = _open_connection()
    except Exception as exc:
        print(f"error: cannot open the database: {exc.__class__.__name__}", file=sys.stderr)
        return 1
    try:
        # Decide before asking for a secret that would be thrown away.
        try:
            classify_admin_bootstrap(conn, options["email"])
        finally:
            conn.rollback()
        password = _read_password(prompt)
        if password is None:
            return 1
        password_hash = hash_password(password)
        del password
        result = bootstrap_admin(conn, options["email"], password_hash, nome=options["name"])
    except AdminBootstrapRefused as exc:
        print(f"bootstrap-admin: refused: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"error: bootstrap failed: {exc.__class__.__name__}", file=sys.stderr)
        return 1
    finally:
        _close_connection(context)
    print(f"{_MESSAGES[result.outcome]} (usuario_id={result.usuario_id} email={result.email})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AdminBootstrapPlan",
    "AdminBootstrapRefused",
    "AdminBootstrapResult",
    "bootstrap_admin",
    "classify_admin_bootstrap",
    "main",
]
