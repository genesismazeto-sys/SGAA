"""Canonical prod-1/v11 credential-pending schema objects.

v11 widens one CHECK constraint: ``usuario_credenciais.estado`` gains
``pending``.

THE THREE STATES
    ``pending``   the account exists but holds no usable password credential.
                  Password authentication is refused by state, whatever
                  ``usuarios.senha`` happens to contain. The normal way out is
                  the first-access e-mail; an administrator may instead apply
                  the profile default explicitly.
    ``personal``  an individual password: set by the user, or typed by an
                  administrator for this one account.
    ``default``   an administrator explicitly applied the shared profile
                  default to THIS account ("Aplicar senha padrão"). The applied
                  value is hashed into ``usuarios.senha`` like any other
                  credential, so later edits to the configured profile default
                  never reach it.

WHY v11 EXISTS
    Before v11 the table could not say "no usable credential". Accounts created
    without a password were stored as ``default`` -- with the shared hash when
    the global ``default_passwords_enabled`` switch was on, with an unusable
    random hash when it was off -- and login consulted that switch to decide
    whether ``default`` meant anything. v11 retires the switch: whether an
    account may authenticate with a password is now a property of the account
    alone.

WHY A TABLE REBUILD AND NOT AN ALTER
    SQLite cannot alter a CHECK constraint in place. The column order, types,
    defaults and the foreign key are byte-for-byte the v9 declaration, so the
    only schema delta a fresh v11 bootstrap and a migrated v10 database can
    disagree on is the one this module declares.
"""

USUARIO_CREDENCIAIS_V11_TABLE_SQL = """
CREATE TABLE usuario_credenciais (
 usuario_id INTEGER PRIMARY KEY,
 estado TEXT NOT NULL CHECK(estado IN ('pending','default','personal')),
 auth_version INTEGER NOT NULL DEFAULT 1,
 atualizado_em TEXT NOT NULL DEFAULT (datetime('now')),
 acesso_ativo INTEGER NOT NULL DEFAULT 1 CHECK(acesso_ativo IN (0,1)),
 FOREIGN KEY(usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
)
"""

CREDENTIAL_PENDING_V11_SCHEMA_OBJECTS = (USUARIO_CREDENCIAIS_V11_TABLE_SQL,)


__all__ = [
    "CREDENTIAL_PENDING_V11_SCHEMA_OBJECTS",
    "USUARIO_CREDENCIAIS_V11_TABLE_SQL",
]
