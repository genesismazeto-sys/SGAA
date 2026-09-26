"""prod-1 v9 -> v10: durable confirmed-send evidence on the password token.

Additive and non-destructive. One ``ALTER TABLE ... ADD COLUMN`` adds
``senha_tokens.sent_at``.

NOTHING IS BACKFILLED, ON PURPOSE
    ``sent_at`` records that a mail provider confirmed the send. No
    pre-existing row carries that evidence -- before v10 a confirmed send and
    an unconfirmed ("indeterminate") send were indistinguishable in the
    database -- so every migrated token keeps ``sent_at = NULL``. Inventing a
    timestamp from ``created_at`` would manufacture exactly the proof this
    column exists to require.

    The user-visible consequence is deterministic and stated here so it is not
    discovered later: an account whose first-access e-mail went out before v10
    reads *Pendente*, not *Disponibilizado*, until an administrator sends it
    again. That is the correct reading -- SGAA genuinely cannot prove the older
    send succeeded.

The migration asserts afterwards that no token's existing lifecycle column
moved, and validates the resulting schema against the v10 head before
committing.
"""

from __future__ import annotations

import sqlite3

from app.prod1_access_delivery_ddl import SENHA_TOKENS_V10_ADD_COLUMN_SQL


_V10_DETAILS_JSON = (
    '{"schema_epoch":"prod-1","access_delivery":"senha_tokens.sent_at",'
    '"backfill":"none_no_durable_send_evidence_predates_v10"}'
)


def migrate_prod1_v9_to_v10(conn: sqlite3.Connection) -> dict[str, object]:
    from app.prod1_schema import (
        ACCESS_DELIVERY_MARKER,
        BASELINE_MARKER,
        SCHEMA_EPOCH,
        Prod1SchemaError,
        _validate_prod1_v9_schema,
        _validate_prod1_v10_schema,
    )

    if conn.in_transaction:
        raise Prod1SchemaError("prod-1/v10 migration requires a clean connection")
    _validate_prod1_v9_schema(conn)

    tokens_before = [
        tuple(row)
        for row in conn.execute(
            "SELECT id,usuario_id,purpose,token_hash,created_at,expires_at,"
            "consumed_at,invalidated_at FROM senha_tokens ORDER BY id"
        ).fetchall()
    ]
    credentials_before = [
        tuple(row)
        for row in conn.execute(
            "SELECT usuario_id,estado,auth_version,acesso_ativo"
            " FROM usuario_credenciais ORDER BY usuario_id"
        ).fetchall()
    ]

    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(SENHA_TOKENS_V10_ADD_COLUMN_SQL)
        conn.execute(
            "INSERT INTO schema_migrations(version,name,schema_epoch,details_json)"
            " VALUES(?,?,?,?)",
            (10, ACCESS_DELIVERY_MARKER, SCHEMA_EPOCH, _V10_DETAILS_JSON),
        )
        conn.execute("PRAGMA user_version=10")

        tokens_after = [
            tuple(row)
            for row in conn.execute(
                "SELECT id,usuario_id,purpose,token_hash,created_at,expires_at,"
                "consumed_at,invalidated_at FROM senha_tokens ORDER BY id"
            ).fetchall()
        ]
        if tokens_after != tokens_before:
            raise Prod1SchemaError("prod-1/v10 migration changed password token state")

        confirmed = int(
            conn.execute(
                "SELECT COUNT(*) FROM senha_tokens WHERE sent_at IS NOT NULL"
            ).fetchone()[0]
        )
        if confirmed:
            raise Prod1SchemaError(
                f"prod-1/v10 migration invented send evidence for {confirmed} token(s)"
            )

        credentials_after = [
            tuple(row)
            for row in conn.execute(
                "SELECT usuario_id,estado,auth_version,acesso_ativo"
                " FROM usuario_credenciais ORDER BY usuario_id"
            ).fetchall()
        ]
        if credentials_after != credentials_before:
            raise Prod1SchemaError("prod-1/v10 migration changed credential state")

        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise Prod1SchemaError("prod-1/v10 integrity check failed")
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise Prod1SchemaError(f"prod-1/v10 foreign key violations: {violations!r}")
        # v10 is no longer the head: validate against the frozen v10 recognizer,
        # never against validate_prod1_schema, which now describes v11.
        _validate_prod1_v10_schema(conn)
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise

    _validate_prod1_v10_schema(conn)
    status = {"schema_epoch": SCHEMA_EPOCH, "schema_version": 10}
    return {
        **status,
        "baseline_marker": BASELINE_MARKER,
        "access_delivery_backfill": "none",
    }


__all__ = ["migrate_prod1_v9_to_v10"]
