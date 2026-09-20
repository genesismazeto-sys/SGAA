"""Test-only helper that makes a hand-built session look like a real login.

Production stamps ``session["auth_version"]`` in the login view and
``app.session_auth.enforce_session_auth_version`` rejects any authenticated
session whose stamp no longer matches the durable credential.  Tests that
manufacture a session instead of posting to ``/login`` have to stamp it too.

This helper performs exactly what a successful login performs and nothing
else: it reads the durable ``usuario_credenciais.auth_version`` and copies it
into the session.  It never relaxes, patches or bypasses the production guard,
so a genuine regression in that guard still fails the suite.
"""
from __future__ import annotations

import sqlite3

import app.db as app_db


def stamp_auth_version(session_obj, usuario_id=None):
    """Stamp the current durable auth_version into a manufactured session.

    ``usuario_id`` defaults to the ``user_id`` the caller already put in the
    session.  Fixtures that insert into ``usuarios`` directly get the
    credential row production would have created alongside the account.
    """
    if usuario_id is None:
        usuario_id = session_obj.get("user_id")
    if usuario_id is None:
        return None

    conn = sqlite3.connect(app_db.DATABASE, timeout=30.0)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        row = conn.execute(
            "SELECT auth_version FROM usuario_credenciais WHERE usuario_id=?",
            (int(usuario_id),),
        ).fetchone()
        if row is None:
            exists = conn.execute(
                "SELECT 1 FROM usuarios WHERE id=?", (int(usuario_id),)
            ).fetchone()
            if exists is None:
                # Synthetic id with no account behind it: there is no durable
                # credential to copy, so leave the session unstamped rather
                # than inventing one.
                return None
            conn.execute(
                "INSERT INTO usuario_credenciais(usuario_id,estado) VALUES(?,'personal')",
                (int(usuario_id),),
            )
            conn.commit()
            version = 1
        else:
            version = int(row[0])
    finally:
        conn.close()

    session_obj["auth_version"] = version
    return version


def existing_admin_user_id():
    """Id of a real admin account in the configured test database.

    For fixtures that used to authenticate as a synthetic id: the production
    session guard now reads the durable credential on every authenticated
    request, so a session must belong to an account that actually exists.
    """
    conn = sqlite3.connect(app_db.DATABASE, timeout=30.0)
    try:
        row = conn.execute(
            "SELECT id FROM usuarios WHERE tipo='admin' ORDER BY id LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, "the test database has no admin account to authenticate as"
    return int(row[0])


def ensure_student_user_id(email="session.support.aluno@ej.edu.br"):
    """Id of a real aluno account, created once if the fixture has none.

    Same reason as :func:`existing_admin_user_id`: the production session guard
    reads the durable credential on every authenticated request, so a session
    can no longer stand on a synthetic id.
    """
    conn = sqlite3.connect(app_db.DATABASE, timeout=30.0)
    try:
        row = conn.execute("SELECT id FROM usuarios WHERE email=?", (email,)).fetchone()
        if row is not None:
            usuario_id = int(row[0])
        else:
            usuario_id = int(
                conn.execute(
                    "INSERT INTO usuarios (nome,email,senha,tipo,nivel_acesso)"
                    " VALUES (?,?,?,'aluno','usuario')",
                    ("Aluno de sessao", email, "x"),
                ).lastrowid
            )
        conn.execute(
            "INSERT OR IGNORE INTO usuario_credenciais(usuario_id,estado)"
            " VALUES (?,'personal')",
            (usuario_id,),
        )
        conn.commit()
    finally:
        conn.close()
    return usuario_id


__all__ = ["ensure_student_user_id", "existing_admin_user_id", "stamp_auth_version"]
