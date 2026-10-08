"""Test-only inverse of the prod-1 v14 -> v15 canonical document-custody migration.

Two consumers, one definition:

* predecessor fixtures that reconstruct an older schema by reverting deltas
  from the bootstrapped head -- ``revert_prod1_v14_to_v13`` calls this first
  when it is handed the v15 head, so every existing builder keeps working;
* the v15 proofs (fresh v15 == v14 -> v15, rollback), which need the frozen
  v14 physical schema back, data included.

It is deliberately NOT production code: v15 has no shipped downgrade path.
No row may use the canonical ``supabase`` provider -- a downgrade would
otherwise produce rows the v14 custody triggers refuse.
"""

from __future__ import annotations

import sqlite3

from app.prod1_schema import canonical_prod1_pre_v15_object_sql

_REQUEST_TRIGGERS = ("trg_requisicao_arquivos_custody_insert", "trg_requisicao_arquivos_custody_update")
_ARQUIVOS_INDEXES = (
    "idx_admin_arquivos_visivel", "idx_admin_arquivos_criado_em", "ux_admin_arquivos_provider_remote_file",
    "ux_admin_arquivos_operation_key", "ux_admin_arquivos_storage_object",
)
_ARQUIVOS_TRIGGERS = (
    "trg_admin_arquivos_custody_insert", "trg_admin_arquivos_custody_update",
    "trg_admin_arquivos_storage_object_insert", "trg_admin_arquivos_storage_object_update",
)


def revert_prod1_v15_to_v14(conn: sqlite3.Connection) -> None:
    """Restore the v14 request triggers and ``admin_arquivos`` DDL and marker 14."""
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 15
    for table in ("requisicao_arquivos", "admin_arquivos"):
        assert conn.execute(f"SELECT count(*) FROM {table} WHERE provider='supabase'").fetchone()[0] == 0, table
    conn.commit()
    sequence = conn.execute("SELECT seq FROM main.sqlite_sequence WHERE name='admin_arquivos'").fetchone()
    foreign_keys = bool(conn.execute("PRAGMA foreign_keys").fetchone()[0])
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        conn.execute("BEGIN IMMEDIATE")
        for name in _REQUEST_TRIGGERS:
            conn.execute(f"DROP TRIGGER main.{name}")
            conn.execute(canonical_prod1_pre_v15_object_sql("trigger", name))
        conn.execute("CREATE TABLE main._admin_arquivos_v14 AS SELECT * FROM main.admin_arquivos")
        conn.execute("DROP TABLE main.admin_arquivos")
        conn.execute(canonical_prod1_pre_v15_object_sql("table", "admin_arquivos"))
        conn.execute("INSERT INTO main.admin_arquivos SELECT * FROM main._admin_arquivos_v14")
        conn.execute("DROP TABLE main._admin_arquivos_v14")
        for name in _ARQUIVOS_INDEXES:
            conn.execute(canonical_prod1_pre_v15_object_sql("index", name))
        for name in _ARQUIVOS_TRIGGERS:
            conn.execute(canonical_prod1_pre_v15_object_sql("trigger", name))
        conn.execute("DELETE FROM main.sqlite_sequence WHERE name='admin_arquivos'")
        if sequence is not None:
            conn.execute("INSERT INTO main.sqlite_sequence(name,seq) VALUES('admin_arquivos',?)", (sequence[0],))
        conn.execute("DELETE FROM schema_migrations WHERE version=15")
        conn.execute("PRAGMA user_version=14")
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute(f"PRAGMA foreign_keys={'ON' if foreign_keys else 'OFF'}")


__all__ = ["revert_prod1_v15_to_v14"]
