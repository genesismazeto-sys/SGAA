"""Test-only inverse of the prod-1 v10 -> v11 credential-pending migration.

Two consumers, one definition:

* predecessor fixtures (``_build_v10`` / ``_build_v9`` / ``_build_v8`` ...) that
  reconstruct an older schema by reverting deltas from the bootstrapped head --
  every one of them has to revert v11 first;
* the v11 rollback proof, which reverts a migrated copy and demands the frozen
  v10 digest back, byte-identical data included.

It is deliberately NOT production code: v11 has no shipped downgrade path.
"""

from __future__ import annotations

import sqlite3

from app.prod1_access_status_ddl import USUARIO_CREDENCIAIS_V9_TABLE_SQL

LEGACY_SETTING = "default_passwords_enabled"


def revert_prod1_v11_to_v10(
    conn: sqlite3.Connection,
    *,
    restore_setting: tuple[str, str] | None = None,
) -> None:
    """Rebuild ``usuario_credenciais`` in its v9/v10 form and drop marker 11.

    ``pending`` maps back to ``default`` -- the only state v10 could store for
    an account without a usable credential. ``restore_setting`` re-inserts the
    retired ``default_passwords_enabled`` row as ``(valor, atualizado_em)``.
    No hash is touched: the v11 migration never rewrites one.
    """
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 11
    foreign_keys = bool(conn.execute("PRAGMA foreign_keys").fetchone()[0])
    conn.commit()
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "CREATE TEMP TABLE _cred_v11 AS"
            " SELECT usuario_id,estado,auth_version,atualizado_em,acesso_ativo"
            " FROM main.usuario_credenciais"
        )
        conn.execute("DROP TABLE main.usuario_credenciais")
        conn.execute(USUARIO_CREDENCIAIS_V9_TABLE_SQL)
        conn.execute(
            """
            INSERT INTO main.usuario_credenciais(
                usuario_id,estado,auth_version,atualizado_em,acesso_ativo)
            SELECT usuario_id,
                   CASE estado WHEN 'pending' THEN 'default' ELSE estado END,
                   auth_version,atualizado_em,acesso_ativo
              FROM temp._cred_v11
            """
        )
        conn.execute("DROP TABLE temp._cred_v11")
        conn.execute("DELETE FROM schema_migrations WHERE version=11")
        if restore_setting is not None:
            valor, atualizado_em = restore_setting
            conn.execute(
                "INSERT INTO configuracoes_app(chave,valor,atualizado_em) VALUES(?,?,?)",
                (LEGACY_SETTING, valor, atualizado_em),
            )
        conn.execute("PRAGMA user_version=10")
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute(f"PRAGMA foreign_keys={'ON' if foreign_keys else 'OFF'}")


__all__ = ["LEGACY_SETTING", "revert_prod1_v11_to_v10"]
