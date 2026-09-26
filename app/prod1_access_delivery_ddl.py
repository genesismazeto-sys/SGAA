"""Canonical prod-1/v10 access-delivery schema objects.

v10 adds one column: ``senha_tokens.sent_at``, the durable record that a
password e-mail carrying this token was **confirmed sent** by the mail
provider.

WHY THE SCHEMA NEEDED THIS AT ALL
    ``app.password_email.issue_and_send_password_email`` already distinguishes
    four outcomes -- ``sent``, ``failed``, ``indeterminate``, ``unavailable`` --
    but before v10 only two of them left a trace:

    * ``unavailable`` returns before issuing anything, so no token row exists;
    * ``failed`` invalidates the token it just issued, so ``invalidated_at`` is
      set;
    * ``sent`` and ``indeterminate`` were **indistinguishable**. Both left a
      live, unconsumed, un-invalidated token and differed only in a log line.

    A live first-access token therefore proved "issued, and the provider either
    confirmed the send or said nothing at all". That is not evidence of
    delivery, and presenting it as such would claim something SGAA does not
    know. ``sent_at`` is written on the confirmed-send path only, so its
    presence is the one fact that separates the two.

WHY A NULLABLE COLUMN ON THE TOKEN AND NOT A NEW TABLE
    The fact being recorded is a property of a specific token's lifecycle --
    issued, sent, consumed, invalidated, expired -- and ``senha_tokens``
    already owns the other four timestamps of exactly that lifecycle. A
    separate table would duplicate the token's identity to carry one nullable
    timestamp, and a UI-only status table would put the evidence somewhere the
    auth domain could not see it.

    ``NULL`` means "no confirmed send", which is the honest value both for a
    token that was never sent and for every token that predates v10. The
    migration therefore backfills nothing.

    ``sent_at`` is deliberately NOT part of token validity. A resolved token is
    still resolved whether or not the provider confirmed the mail -- an
    indeterminate send may well have been delivered, so invalidating it would
    lock out a user who did receive the link.

SIGNATURE NOTE
    Declared last, immediately before the FOREIGN KEY clause, because that is
    exactly where SQLite's ``ALTER TABLE ... ADD COLUMN`` splices it into the
    stored CREATE statement. Keeping the two textually equivalent lets the
    v9 -> v10 migration be a single additive ALTER while still producing a
    schema signature identical to a fresh v10 bootstrap -- the same technique
    v9 used for ``usuario_credenciais.acesso_ativo``.
"""

SENHA_TOKENS_V10_TABLE_SQL = """
CREATE TABLE senha_tokens (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 usuario_id INTEGER NOT NULL,
 purpose TEXT NOT NULL CHECK(purpose IN ('first_access','password_reset')),
 token_hash TEXT NOT NULL UNIQUE,
 created_at TEXT NOT NULL DEFAULT (datetime('now')),
 expires_at TEXT NOT NULL,
 consumed_at TEXT,
 invalidated_at TEXT,
 sent_at TEXT,
 FOREIGN KEY(usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
)
"""

# The additive step the v9 -> v10 migration applies. Declared here so the
# bootstrap DDL above and the migration can never drift apart.
SENHA_TOKENS_V10_ADD_COLUMN_SQL = "ALTER TABLE senha_tokens ADD COLUMN sent_at TEXT"

ACCESS_DELIVERY_V10_SCHEMA_OBJECTS = (SENHA_TOKENS_V10_TABLE_SQL,)


__all__ = [
    "ACCESS_DELIVERY_V10_SCHEMA_OBJECTS",
    "SENHA_TOKENS_V10_ADD_COLUMN_SQL",
    "SENHA_TOKENS_V10_TABLE_SQL",
]
