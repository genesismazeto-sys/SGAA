import secrets

from app.auth import (
    DEFAULT_ACCESS_PASSWORDS,
    canonicalize_access_level,
    default_access_level_for_user_type,
)
from app.db_maintenance import ensure_usuario_access_schema
from app.security.passwords import hash_password, hash_password_batch


# prod-1/v11 credential states -- see app/prod1_credential_pending_ddl.py.
#
#   pending   no usable password credential; password login is refused by state
#   default   an administrator explicitly applied the shared profile default
#   personal  an individual password
#
# Whether an account may authenticate with a password is a property of the
# account alone: no global setting widens or narrows it.
CREDENTIAL_STATE_PENDING = "pending"
CREDENTIAL_STATE_DEFAULT = "default"
CREDENTIAL_STATE_PERSONAL = "personal"
_CREDENTIAL_STATES = {
    CREDENTIAL_STATE_PENDING,
    CREDENTIAL_STATE_DEFAULT,
    CREDENTIAL_STATE_PERSONAL,
}
#: The states whose stored hash is a credential login may verify.
PASSWORD_LOGIN_CREDENTIAL_STATES = frozenset(
    {CREDENTIAL_STATE_DEFAULT, CREDENTIAL_STATE_PERSONAL}
)


def _validate_credential_state(state: str) -> str:
    if state not in _CREDENTIAL_STATES:
        raise ValueError(f"invalid credential state: {state!r}")
    return state


def credential_state_allows_password_login(state) -> bool:
    """Whether login may compare a password against this account's hash."""
    return str(state or "") in PASSWORD_LOGIN_CREDENTIAL_STATES


def first_access_redeemable(state) -> bool:
    """Whether a first-access link may be redeemed for an account in ``state``.

    First access is onboarding: it establishes a credential that does not exist
    yet, so only ``pending`` qualifies. A ``default`` or ``personal`` account
    already holds one; its e-mail path is ``password_reset``. Checked at the
    moment of redemption, so a link that outlived its account's state -- a
    stale historical token, migrated data, a writer that forgot to invalidate
    -- is refused rather than trusted.
    """
    return str(state or "") == CREDENTIAL_STATE_PENDING


def unusable_password_hash() -> str:
    """A well-formed hash of a secret nobody holds.

    ``usuarios.senha`` is NOT NULL, so a ``pending`` account still stores a
    hash. Login refuses ``pending`` by state before comparing anything; this
    value is the second wall, so even a misread state could not match.
    """
    return hash_password(secrets.token_urlsafe(32))


def prepare_pending_password_hashes(count: int) -> list[str]:
    """``count`` unusable hashes for new ``pending`` accounts, in parallel.

    For batch creation: the PBKDF2 cost leaves the write loop. One random
    secret, never retained, with a distinct salt per hash.
    """
    if count <= 0:
        return []
    return hash_password_batch(secrets.token_urlsafe(32), count)


def set_usuario_credential_state(conn, usuario_id: int, state: str) -> None:
    state = _validate_credential_state(state)
    conn.execute(
        """
        INSERT INTO usuario_credenciais(usuario_id,estado)
        VALUES(?,?)
        ON CONFLICT(usuario_id) DO UPDATE SET
            estado=excluded.estado,
            atualizado_em=datetime('now')
        """,
        (usuario_id, state),
    )


def get_usuario_credential(conn, usuario_id: int):
    return conn.execute(
        "SELECT estado,auth_version,acesso_ativo FROM usuario_credenciais WHERE usuario_id=?",
        (int(usuario_id),),
    ).fetchone()


def usuario_access_is_active(conn, usuario_id: int) -> bool:
    """Whether this account is permitted to authenticate at all (prod-1/v9).

    Orthogonal to ``estado``, which only records where the password came from.
    A missing credential row is treated as inactive: an account with no
    credential is structurally incomplete, not implicitly allowed.
    """
    row = conn.execute(
        "SELECT acesso_ativo FROM usuario_credenciais WHERE usuario_id=?",
        (int(usuario_id),),
    ).fetchone()
    return bool(row) and int(row[0]) == 1


def set_usuario_access_active(conn, usuario_id: int, active: bool) -> None:
    """Flip the durable access status, bumping auth_version when revoking.

    Revocation has to end live sessions, and the session guard compares the
    stamped ``auth_version``; reactivation deliberately does not bump, because
    there is nothing to sign out.
    """
    if active:
        conn.execute(
            "UPDATE usuario_credenciais SET acesso_ativo=1, atualizado_em=datetime('now') "
            "WHERE usuario_id=?",
            (int(usuario_id),),
        )
        return
    conn.execute(
        "UPDATE usuario_credenciais SET acesso_ativo=0, "
        "auth_version=auth_version+1, atualizado_em=datetime('now') WHERE usuario_id=?",
        (int(usuario_id),),
    )


def get_usuario_auth_version(conn, usuario_id: int) -> int | None:
    row = get_usuario_credential(conn, usuario_id)
    return int(row["auth_version"] if hasattr(row, "keys") else row[1]) if row else None


def _write_usuario_credential_after_password_change(
    conn,
    usuario_id: int,
    state: str,
) -> None:
    conn.execute(
        """
        INSERT INTO usuario_credenciais(usuario_id,estado,auth_version,atualizado_em)
        VALUES(?,?,1,datetime('now'))
        ON CONFLICT(usuario_id) DO UPDATE SET
            estado=excluded.estado,
            auth_version=usuario_credenciais.auth_version+1,
            atualizado_em=excluded.atualizado_em
        """,
        (int(usuario_id), state),
    )


def invalidate_usuario_password_tokens(
    conn,
    usuario_ids: list[int] | tuple[int, ...],
    *,
    except_token_id: int | None = None,
) -> int:
    ids = sorted({int(usuario_id) for usuario_id in usuario_ids})
    if not ids:
        return 0
    placeholders = ", ".join("?" for _ in ids)
    params: list[object] = [*ids]
    except_clause = ""
    if except_token_id is not None:
        except_clause = " AND id <> ?"
        params.append(int(except_token_id))
    cursor = conn.execute(
        f"""
        UPDATE senha_tokens
           SET invalidated_at=datetime('now')
         WHERE usuario_id IN ({placeholders})
           AND consumed_at IS NULL
           AND invalidated_at IS NULL
           {except_clause}
        """,
        params,
    )
    return int(cursor.rowcount)


def create_usuario_with_access_level(
    conn,
    nome: str,
    email: str,
    senha_hash: str,
    user_type: str,
    access_level: str,
    *,
    credential_state: str,
):
    ensure_usuario_access_schema(conn)
    cursor = conn.execute(
        "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?)",
        (nome, email, senha_hash, user_type, access_level),
    )
    set_usuario_credential_state(conn, int(cursor.lastrowid), credential_state)
    return cursor


def set_usuarios_password_hash(
    conn,
    usuario_ids: list[int] | tuple[int, ...],
    senha_hash: str,
    *,
    credential_state: str,
    consumed_token_id: int | None = None,
) -> int:
    state = _validate_credential_state(credential_state)
    ids = sorted({int(usuario_id) for usuario_id in usuario_ids})
    if not ids:
        return 0
    if consumed_token_id is not None and len(ids) != 1:
        raise ValueError("a consumed password token requires exactly one usuario")
    placeholders = ", ".join("?" for _ in ids)
    cursor = conn.execute(
        f"UPDATE usuarios SET senha = ? WHERE id IN ({placeholders})",
        [senha_hash, *ids],
    )
    for usuario_id in ids:
        _write_usuario_credential_after_password_change(conn, usuario_id, state)
    invalidate_usuario_password_tokens(
        conn,
        ids,
        except_token_id=consumed_token_id,
    )
    if consumed_token_id is not None:
        consumed = conn.execute(
            """
            UPDATE senha_tokens
               SET consumed_at=datetime('now')
             WHERE id=? AND usuario_id=?
               AND consumed_at IS NULL AND invalidated_at IS NULL
            """,
            (int(consumed_token_id), ids[0]),
        )
        if consumed.rowcount != 1:
            raise ValueError("password token is no longer active")
    return int(cursor.rowcount)


def set_usuario_password_hash(
    conn,
    usuario_id: int,
    senha_hash: str,
    *,
    credential_state: str,
    consumed_token_id: int | None = None,
) -> None:
    updated = set_usuarios_password_hash(
        conn,
        [usuario_id],
        senha_hash,
        credential_state=credential_state,
        consumed_token_id=consumed_token_id,
    )
    if updated != 1:
        raise ValueError(f"usuario not found for password write: {usuario_id}")


def rehash_usuario_password(conn, usuario_id: int, senha_hash: str) -> None:
    """Upgrade hash encoding without changing the credential classification."""
    cursor = conn.execute(
        "UPDATE usuarios SET senha = ? WHERE id = ?",
        (senha_hash, usuario_id),
    )
    if cursor.rowcount != 1:
        raise ValueError(f"usuario not found for password rehash: {usuario_id}")
    credential = conn.execute(
        """
        UPDATE usuario_credenciais
           SET auth_version=auth_version+1,atualizado_em=datetime('now')
         WHERE usuario_id=?
        """,
        (int(usuario_id),),
    )
    if credential.rowcount != 1:
        raise ValueError(f"credential not found for password rehash: {usuario_id}")
    invalidate_usuario_password_tokens(conn, [int(usuario_id)])


def _access_defaults_map(conn) -> dict[str, str]:
    from app.auth import DEFAULT_ACCESS_PASSWORDS, canonicalize_access_level

    ensure_usuario_access_schema(conn)
    defaults = dict(DEFAULT_ACCESS_PASSWORDS)
    rows = conn.execute("SELECT nivel_acesso, senha_padrao FROM configuracoes_acesso").fetchall()
    for row in rows:
        nivel = canonicalize_access_level(row["nivel_acesso"])
        defaults[nivel] = row["senha_padrao"]
    return defaults


def _default_password_for_user_type(conn, user_type: str) -> str:
    from app.auth import default_access_level_for_user_type

    nivel_acesso = default_access_level_for_user_type(user_type)
    return _access_defaults_map(conn).get(nivel_acesso, "admin123")


def create_usuario_with_default_access(
    conn,
    nome: str,
    email: str,
    senha_hash: str,
    user_type: str,
    *,
    credential_state: str = CREDENTIAL_STATE_PERSONAL,
):
    from app.auth import default_access_level_for_user_type

    ensure_usuario_access_schema(conn)
    nivel_acesso = default_access_level_for_user_type(user_type)
    return create_usuario_with_access_level(
        conn,
        nome,
        email,
        senha_hash,
        user_type,
        nivel_acesso,
        credential_state=credential_state,
    )


def create_usuario_with_default_password(conn, nome: str, email: str, user_type: str):
    """Create an account with the profile default EXPLICITLY applied (``default``).

    Not the blank-password path: an account created without a password is
    ``pending`` (``create_usuario_pending``). This exists for callers that
    deliberately provision the shared default, such as demo seeding.
    """
    senha_padrao = _default_password_for_user_type(conn, user_type)
    return create_usuario_with_default_access(
        conn,
        nome,
        email,
        hash_password(senha_padrao),
        user_type,
        credential_state=CREDENTIAL_STATE_DEFAULT,
    )


def create_usuario_pending(
    conn,
    nome: str,
    email: str,
    user_type: str,
    *,
    senha_hash: str | None = None,
):
    """Create an account with no usable password credential (``pending``).

    The account waits for a completed first access (-> ``personal``) or an
    explicit "Aplicar senha padrão" (-> ``default``). ``senha_hash`` lets a
    batch caller pass a precomputed ``prepare_pending_password_hashes`` value.
    """
    return create_usuario_with_default_access(
        conn,
        nome,
        email,
        senha_hash or unusable_password_hash(),
        user_type,
        credential_state=CREDENTIAL_STATE_PENDING,
    )


def normalize_usuario_access_for_user_type(conn, usuario_id: int | None):
    if not usuario_id:
        return
    ensure_usuario_access_schema(conn)
    usuario = conn.execute(
        "SELECT id, tipo, nivel_acesso FROM usuarios WHERE id = ?",
        (usuario_id,),
    ).fetchone()
    if not usuario:
        return
    if usuario["tipo"] == "aluno" and str(usuario["nivel_acesso"] or "").strip().lower() == "administrativo":
        conn.execute(
            "UPDATE usuarios SET nivel_acesso = ? WHERE id = ?",
            (default_access_level_for_user_type("aluno"), usuario_id),
        )
