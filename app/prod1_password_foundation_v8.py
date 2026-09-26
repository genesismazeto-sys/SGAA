from __future__ import annotations

import sqlite3

from app.auth import (
    DEFAULT_ACCESS_PASSWORDS,
    canonicalize_access_level,
    default_access_level_for_user_type,
)
from app.prod1_password_foundation_ddl import (
    PASSWORD_FOUNDATION_V8_SCHEMA_OBJECTS,
)
from app.security.passwords import check_password


_V8_DETAILS_JSON = (
    '{"schema_epoch":"prod-1","credential_state":"usuario_credenciais",'
    '"password_tokens":"senha_tokens","legacy_backfill":"current_default_match"}'
)


def _configured_access_defaults(conn: sqlite3.Connection) -> dict[str, str]:
    defaults = dict(DEFAULT_ACCESS_PASSWORDS)
    for row in conn.execute(
        "SELECT nivel_acesso,senha_padrao FROM configuracoes_acesso"
    ).fetchall():
        defaults[canonicalize_access_level(row[0])] = str(row[1])
    return defaults


def _legacy_credential_state(
    *,
    stored_hash: str,
    user_type: str,
    access_level: str | None,
    configured_defaults: dict[str, str],
) -> str:
    """Classify a legacy hash by matching the current profile default.

    This is deliberately a compatibility heuristic, not historical proof of
    how the account password was originally chosen.
    """
    canonical_level = canonicalize_access_level(
        access_level,
        default_access_level_for_user_type(user_type),
    )
    configured_default = configured_defaults.get(
        canonical_level,
        DEFAULT_ACCESS_PASSWORDS[default_access_level_for_user_type(user_type)],
    )
    return "default" if check_password(stored_hash, configured_default) else "personal"


def migrate_prod1_v7_to_v8(conn: sqlite3.Connection) -> dict[str, object]:
    """Add credential state, auth versions, token storage and the default-password switch."""
    from app.prod1_schema import (
        BASELINE_MARKER,
        PASSWORD_FOUNDATION_MARKER,
        SCHEMA_EPOCH,
        Prod1SchemaError,
        _validate_prod1_v7_schema,
        _validate_prod1_v8_schema,
    )

    if conn.in_transaction:
        raise Prod1SchemaError("prod-1/v8 migration requires a clean connection")
    _validate_prod1_v7_schema(conn)

    users_before = [
        (int(row[0]), str(row[1]), str(row[2]), str(row[3] or ""))
        for row in conn.execute(
            "SELECT id,senha,tipo,nivel_acesso FROM usuarios ORDER BY id"
        ).fetchall()
    ]
    passwords_before = [(user_id, password_hash) for user_id, password_hash, _, _ in users_before]
    configured_defaults = _configured_access_defaults(conn)

    try:
        conn.execute("BEGIN IMMEDIATE")
        for statement in PASSWORD_FOUNDATION_V8_SCHEMA_OBJECTS:
            conn.execute(statement)

        conn.executemany(
            "INSERT INTO usuario_credenciais(usuario_id,estado) VALUES(?,?)",
            [
                (
                    user_id,
                    _legacy_credential_state(
                        stored_hash=password_hash,
                        user_type=user_type,
                        access_level=access_level,
                        configured_defaults=configured_defaults,
                    ),
                )
                for user_id, password_hash, user_type, access_level in users_before
            ],
        )
        conn.execute(
            "INSERT OR IGNORE INTO configuracoes_app(chave,valor) VALUES(?,?)",
            ("default_passwords_enabled", "1"),
        )
        conn.execute(
            "INSERT INTO schema_migrations(version,name,schema_epoch,details_json)"
            " VALUES(?,?,?,?)",
            (8, PASSWORD_FOUNDATION_MARKER, SCHEMA_EPOCH, _V8_DETAILS_JSON),
        )
        conn.execute("PRAGMA user_version=8")

        passwords_after = [
            (int(row[0]), str(row[1]))
            for row in conn.execute("SELECT id,senha FROM usuarios ORDER BY id").fetchall()
        ]
        if passwords_after != passwords_before:
            raise Prod1SchemaError("prod-1/v8 migration changed usuarios.senha")
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise Prod1SchemaError("prod-1/v8 integrity check failed")
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise Prod1SchemaError(
                f"prod-1/v8 foreign key violations: {violations!r}"
            )
        _validate_prod1_v8_schema(conn)
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise

    # v8 is no longer the head: report its own contract rather than asking
    # validate_prod1_schema, which now describes v9.
    _validate_prod1_v8_schema(conn)
    tables = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    return {
        "schema_epoch": SCHEMA_EPOCH,
        "schema_version": 8,
        "baseline_marker": BASELINE_MARKER,
        "table_count": len(tables),
        "credential_backfill": "current_default_match_heuristic",
    }


__all__ = ["migrate_prod1_v7_to_v8"]
