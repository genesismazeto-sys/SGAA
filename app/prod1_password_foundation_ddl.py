"""Canonical prod-1/v8 password-foundation schema objects."""

USUARIO_CREDENCIAIS_TABLE_SQL = """
CREATE TABLE usuario_credenciais (
 usuario_id INTEGER PRIMARY KEY,
 estado TEXT NOT NULL CHECK(estado IN ('default','personal')),
 auth_version INTEGER NOT NULL DEFAULT 1,
 atualizado_em TEXT NOT NULL DEFAULT (datetime('now')),
 FOREIGN KEY(usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
)
"""

SENHA_TOKENS_TABLE_SQL = """
CREATE TABLE senha_tokens (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 usuario_id INTEGER NOT NULL,
 purpose TEXT NOT NULL CHECK(purpose IN ('first_access','password_reset')),
 token_hash TEXT NOT NULL UNIQUE,
 created_at TEXT NOT NULL DEFAULT (datetime('now')),
 expires_at TEXT NOT NULL,
 consumed_at TEXT,
 invalidated_at TEXT,
 FOREIGN KEY(usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
)
"""

SENHA_TOKENS_USER_PURPOSE_INDEX_SQL = (
    "CREATE INDEX idx_senha_tokens_usuario_purpose "
    "ON senha_tokens(usuario_id,purpose)"
)

PASSWORD_FOUNDATION_V8_SCHEMA_OBJECTS = (
    USUARIO_CREDENCIAIS_TABLE_SQL,
    SENHA_TOKENS_TABLE_SQL,
    SENHA_TOKENS_USER_PURPOSE_INDEX_SQL,
)

PASSWORD_FOUNDATION_V8_SCHEMA_OBJECTS_SQL = ";\n".join(
    PASSWORD_FOUNDATION_V8_SCHEMA_OBJECTS
)


__all__ = [
    "PASSWORD_FOUNDATION_V8_SCHEMA_OBJECTS",
    "PASSWORD_FOUNDATION_V8_SCHEMA_OBJECTS_SQL",
    "SENHA_TOKENS_TABLE_SQL",
    "SENHA_TOKENS_USER_PURPOSE_INDEX_SQL",
    "USUARIO_CREDENCIAIS_TABLE_SQL",
]
