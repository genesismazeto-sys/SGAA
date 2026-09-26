"""Canonical prod-1/v9 access-status schema objects.

v9 adds one column: whether an account may authenticate at all.

WHY A COLUMN AND NOT A NEW ``estado`` VALUE
    ``usuario_credenciais.estado`` describes where the password came from
    (``default`` = a shared profile password, ``personal`` = one the user
    chose). Whether login is permitted is an orthogonal fact: a revoked
    account still has a password origin, and an active account's origin says
    nothing about its right to sign in. Overloading ``estado`` would conflate
    the two and silently break the default-password switch, which keys off it.

``acesso_ativo`` is therefore a separate boolean, defaulting to 1 so every row
that existed before v9 migrates active.

SIGNATURE NOTE
    The column is declared last, immediately before the FOREIGN KEY clause,
    because that is exactly where SQLite's ``ALTER TABLE ... ADD COLUMN``
    splices it into the stored CREATE statement. Keeping the two textually
    equivalent lets the v8 -> v9 migration be a single additive ALTER while
    still producing a schema signature identical to a fresh v9 bootstrap.
"""

USUARIO_CREDENCIAIS_V9_TABLE_SQL = """
CREATE TABLE usuario_credenciais (
 usuario_id INTEGER PRIMARY KEY,
 estado TEXT NOT NULL CHECK(estado IN ('default','personal')),
 auth_version INTEGER NOT NULL DEFAULT 1,
 atualizado_em TEXT NOT NULL DEFAULT (datetime('now')),
 acesso_ativo INTEGER NOT NULL DEFAULT 1 CHECK(acesso_ativo IN (0,1)),
 FOREIGN KEY(usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
)
"""

# The additive step the v8 -> v9 migration applies. Declared here so the
# bootstrap DDL above and the migration can never drift apart.
USUARIO_CREDENCIAIS_V9_ADD_COLUMN_SQL = (
    "ALTER TABLE usuario_credenciais "
    "ADD COLUMN acesso_ativo INTEGER NOT NULL DEFAULT 1 CHECK(acesso_ativo IN (0,1))"
)

ACCESS_STATUS_V9_SCHEMA_OBJECTS = (USUARIO_CREDENCIAIS_V9_TABLE_SQL,)


__all__ = [
    "ACCESS_STATUS_V9_SCHEMA_OBJECTS",
    "USUARIO_CREDENCIAIS_V9_ADD_COLUMN_SQL",
    "USUARIO_CREDENCIAIS_V9_TABLE_SQL",
]
