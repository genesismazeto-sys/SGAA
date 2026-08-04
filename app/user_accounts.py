from app.auth import (
    DEFAULT_ACCESS_PASSWORDS,
    canonicalize_access_level,
    default_access_level_for_user_type,
)
from app.db_maintenance import ensure_usuario_access_schema
from app.security.passwords import hash_password


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


def create_usuario_with_default_access(conn, nome: str, email: str, senha_hash: str, user_type: str):
    from app.auth import default_access_level_for_user_type

    ensure_usuario_access_schema(conn)
    nivel_acesso = default_access_level_for_user_type(user_type)
    return conn.execute(
        "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?)",
        (nome, email, senha_hash, user_type, nivel_acesso),
    )


def create_usuario_with_default_password(conn, nome: str, email: str, user_type: str):
    senha_padrao = _default_password_for_user_type(conn, user_type)
    return create_usuario_with_default_access(conn, nome, email, hash_password(senha_padrao), user_type)


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
