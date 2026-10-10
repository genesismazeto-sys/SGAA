"""Canonical prod-1/v16 ephemeral-state schema objects.

v16 gives a multi-instance (hosted) runtime the two pieces of short-lived,
cross-request state that a single-process runtime kept in memory or on disk.
It is purely additive: two new, empty tables and their indexes.

    auth_throttle_events   one failed login / one password-recovery attempt of
                           a keyed identity (``scope`` + a keyed digest of the
                           IP address or account -- never the value itself)
    admin_import_previews  one pending administrator import preview: the
                           digest of an unguessable token, the owning
                           administrator, the JSON payload and its expiry

THE CONTRACT
    * Both tables are EPHEMERAL: a row is meaningful for minutes to hours.
      Path-B never copies them and Layer-2 archives their schema only; a
      restore starts with both empty, which is the correct state (every
      limit window is clear, every preview is gone and is simply generated
      again).
    * Digests are lowercase hex SHA-256 / HMAC-SHA-256 (64 characters). No
      e-mail address, IP address or token is ever stored.
    * Timestamps are ``YYYY-MM-DD HH:MM:SS`` UTC text, exactly, so window and
      expiry comparisons are plain text comparisons on both engines (the
      convention of v14).
    * A preview belongs to one administrator and is deleted with that account.
"""

from __future__ import annotations

from app.prod1_storage_ddl import _hex, _ts

AUTH_THROTTLE_SCOPES = ("login_ip", "login_account", "recovery_ip", "recovery_account")
IMPORT_PREVIEW_PAYLOAD_MAX_BYTES = 8 * 1024 * 1024
EPHEMERAL_STATE_V16_TABLES = ("auth_throttle_events", "admin_import_previews")

_SCOPES_SQL = ",".join(f"'{scope}'" for scope in AUTH_THROTTLE_SCOPES)

AUTH_THROTTLE_EVENTS_V16_TABLE_SQL = f"""CREATE TABLE auth_throttle_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 scope TEXT NOT NULL CHECK(scope IN ({_SCOPES_SQL})),
 key_digest TEXT NOT NULL CHECK{_hex('key_digest', 64)},
 occurred_at TEXT NOT NULL CHECK{_ts('occurred_at')}
)"""

ADMIN_IMPORT_PREVIEWS_V16_TABLE_SQL = f"""CREATE TABLE admin_import_previews (
 token_digest TEXT NOT NULL PRIMARY KEY CHECK{_hex('token_digest', 64)},
 usuario_id INTEGER NOT NULL,
 payload TEXT NOT NULL CHECK(length(CAST(payload AS BLOB)) BETWEEN 2 AND {IMPORT_PREVIEW_PAYLOAD_MAX_BYTES}),
 created_at TEXT NOT NULL CHECK{_ts('created_at')},
 expires_at TEXT NOT NULL CHECK{_ts('expires_at')},
 FOREIGN KEY(usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE,
 CHECK(expires_at>created_at)
)"""

EPHEMERAL_STATE_V16_TABLE_SQL = (
    AUTH_THROTTLE_EVENTS_V16_TABLE_SQL,
    ADMIN_IMPORT_PREVIEWS_V16_TABLE_SQL,
)

EPHEMERAL_STATE_V16_INDEX_SQL = (
    "CREATE INDEX idx_auth_throttle_events_lookup ON auth_throttle_events(scope,key_digest,occurred_at)",
    "CREATE INDEX idx_auth_throttle_events_expiry ON auth_throttle_events(occurred_at)",
    "CREATE INDEX idx_admin_import_previews_expiry ON admin_import_previews(expires_at)",
)

#: Every v16 statement in execution order -- shared verbatim by the bootstrap
#: and the v15 -> v16 migration.
EPHEMERAL_STATE_V16_STATEMENTS = EPHEMERAL_STATE_V16_TABLE_SQL + EPHEMERAL_STATE_V16_INDEX_SQL
EPHEMERAL_STATE_V16_SCHEMA_OBJECTS_SQL = ";\n".join(EPHEMERAL_STATE_V16_STATEMENTS) + ";"

EPHEMERAL_STATE_V16_DETAILS_JSON = (
    '{"schema_epoch":"prod-1","ephemeral_state":"database",'
    '"tables":["auth_throttle_events","admin_import_previews"],'
    '"backfill":"none","runtime_switch":"hosted_only_throttle"}'
)


__all__ = [
    "ADMIN_IMPORT_PREVIEWS_V16_TABLE_SQL",
    "AUTH_THROTTLE_EVENTS_V16_TABLE_SQL",
    "AUTH_THROTTLE_SCOPES",
    "EPHEMERAL_STATE_V16_DETAILS_JSON",
    "EPHEMERAL_STATE_V16_INDEX_SQL",
    "EPHEMERAL_STATE_V16_SCHEMA_OBJECTS_SQL",
    "EPHEMERAL_STATE_V16_STATEMENTS",
    "EPHEMERAL_STATE_V16_TABLES",
    "EPHEMERAL_STATE_V16_TABLE_SQL",
    "IMPORT_PREVIEW_PAYLOAD_MAX_BYTES",
]
