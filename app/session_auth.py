from __future__ import annotations

from flask import flash, redirect, request, session, url_for

from app.db import get_db_connection
from app.user_accounts import get_usuario_auth_version


_PUBLIC_OR_INFRA_ENDPOINTS = frozenset(
    {
        "favicon",
        "first_access",
        "forgot_password",
        "health",
        "login",
        "logout",
        "reset_password",
        "static",
    }
)


def enforce_session_auth_version():
    usuario_id = session.get("user_id")
    if not usuario_id:
        return None

    current = get_usuario_auth_version(get_db_connection(), int(usuario_id))
    stamped = session.get("auth_version")
    try:
        matches = current is not None and int(stamped) == int(current)
    except (TypeError, ValueError):
        matches = False
    if matches:
        return None

    session.clear()
    if request.endpoint in _PUBLIC_OR_INFRA_ENDPOINTS:
        return None
    flash("Sua sessão foi encerrada porque a credencial da conta foi alterada.", "info")
    return redirect(url_for("login"))


__all__ = ["enforce_session_auth_version"]
