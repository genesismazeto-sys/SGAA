"""prod-1 v8 -> v9: durable access status on the credential row.

Additive and non-destructive. One ``ALTER TABLE ... ADD COLUMN`` adds
``usuario_credenciais.acesso_ativo``; every pre-existing credential row
migrates ``acesso_ativo = 1`` through the column default, because an account
that could authenticate before the migration must still be able to after it.

Nothing else is touched: no password hash, no credential state, no
auth_version. The migration asserts all three afterwards rather than trusting
the statement, and validates the resulting schema against the v9 head before
committing.
"""

from __future__ import annotations

import sqlite3

from app.prod1_access_status_ddl import USUARIO_CREDENCIAIS_V9_ADD_COLUMN_SQL


_V9_DETAILS_JSON = (
    '{"schema_epoch":"prod-1","access_status":"usuario_credenciais.acesso_ativo",'
    '"backfill":"all_existing_credentials_active"}'
)


def migrate_prod1_v8_to_v9(conn: sqlite3.Connection) -> dict[str, object]:
    from app.prod1_schema import (
        ACCESS_STATUS_MARKER,
        BASELINE_MARKER,
        SCHEMA_EPOCH,
        Prod1SchemaError,
        _validate_prod1_v8_schema,
        _validate_prod1_v9_schema,
    )

    if conn.in_transaction:
        raise Prod1SchemaError("prod-1/v9 migration requires a clean connection")
    _validate_prod1_v8_schema(conn)

    credentials_before = [
        (int(row[0]), str(row[1]), int(row[2]))
        for row in conn.execute(
            "SELECT usuario_id,estado,auth_version FROM usuario_credenciais ORDER BY usuario_id"
        ).fetchall()
    ]
    passwords_before = [
        (int(row[0]), str(row[1]))
        for row in conn.execute("SELECT id,senha FROM usuarios ORDER BY id").fetchall()
    ]

    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(USUARIO_CREDENCIAIS_V9_ADD_COLUMN_SQL)
        conn.execute(
            "INSERT INTO schema_migrations(version,name,schema_epoch,details_json)"
            " VALUES(?,?,?,?)",
            (9, ACCESS_STATUS_MARKER, SCHEMA_EPOCH, _V9_DETAILS_JSON),
        )
        conn.execute("PRAGMA user_version=9")

        credentials_after = [
            (int(row[0]), str(row[1]), int(row[2]))
            for row in conn.execute(
                "SELECT usuario_id,estado,auth_version FROM usuario_credenciais ORDER BY usuario_id"
            ).fetchall()
        ]
        if credentials_after != credentials_before:
            raise Prod1SchemaError("prod-1/v9 migration changed credential state")

        inactive = int(
            conn.execute(
                "SELECT COUNT(*) FROM usuario_credenciais WHERE acesso_ativo <> 1"
            ).fetchone()[0]
        )
        if inactive:
            raise Prod1SchemaError(
                f"prod-1/v9 migration left {inactive} credential row(s) inactive"
            )

        passwords_after = [
            (int(row[0]), str(row[1]))
            for row in conn.execute("SELECT id,senha FROM usuarios ORDER BY id").fetchall()
        ]
        if passwords_after != passwords_before:
            raise Prod1SchemaError("prod-1/v9 migration changed usuarios.senha")

        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise Prod1SchemaError("prod-1/v9 integrity check failed")
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise Prod1SchemaError(f"prod-1/v9 foreign key violations: {violations!r}")
        # v9 is no longer the head: validate against the frozen v9 recognizer,
        # never against validate_prod1_schema, which now describes v10.
        _validate_prod1_v9_schema(conn)
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise

    _validate_prod1_v9_schema(conn)
    status = {"schema_epoch": SCHEMA_EPOCH, "schema_version": 9}
    return {
        **status,
        "baseline_marker": BASELINE_MARKER,
        "access_status_backfill": "all_existing_credentials_active",
    }


__all__ = ["migrate_prod1_v8_to_v9"]
