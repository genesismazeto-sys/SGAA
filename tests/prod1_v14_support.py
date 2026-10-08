"""Test-only inverse of the prod-1 v13 -> v14 canonical-storage migration.

Two consumers, one definition:

* predecessor fixtures that reconstruct an older schema by reverting deltas
  from the bootstrapped head -- ``revert_prod1_v13_to_v12`` calls this first
  when it is handed the v14 head, so every existing builder keeps working;
* the v14 rollback proof, which reverts a migrated copy and demands the frozen
  v13 digest back, data included.

It is deliberately NOT production code: v14 has no shipped downgrade path.
The storage tables must be empty and every business ``storage_object_id``
NULL -- a downgrade would otherwise lose canonical custody.
"""

from __future__ import annotations

import sqlite3

from app.prod1_storage_ddl import STORAGE_OBJECT_REFERENCE_TABLES, STORAGE_V14_TABLES

_V14_TRIGGERS = (
    "trg_requisicao_arquivos_storage_object_insert",
    "trg_requisicao_arquivos_storage_object_update",
    "trg_admin_arquivos_storage_object_insert",
    "trg_admin_arquivos_storage_object_update",
    "trg_storage_upload_intents_transition",
)
_V14_BUSINESS_INDEXES = (
    "ux_req_arquivos_storage_object", "ux_admin_arquivos_storage_object",
    "idx_cloud_accounts_provider_account_key",
)


def revert_prod1_v14_to_v13(conn: sqlite3.Connection) -> None:
    """Drop the (empty) v14 objects, the three NULL columns and marker 14."""
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 14
    for table in STORAGE_V14_TABLES:
        assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0, table
    for table in STORAGE_OBJECT_REFERENCE_TABLES:
        assert conn.execute(
            f"SELECT count(*) FROM {table} WHERE storage_object_id IS NOT NULL"
        ).fetchone()[0] == 0, table
    assert conn.execute(
        "SELECT count(*) FROM cloud_accounts WHERE provider_account_key IS NOT NULL"
    ).fetchone()[0] == 0
    conn.commit()
    try:
        conn.execute("BEGIN IMMEDIATE")
        for name in _V14_TRIGGERS:
            conn.execute(f"DROP TRIGGER main.{name}")
        for name in _V14_BUSINESS_INDEXES:
            conn.execute(f"DROP INDEX main.{name}")
        for table in STORAGE_OBJECT_REFERENCE_TABLES:
            conn.execute(f"ALTER TABLE main.{table} DROP COLUMN storage_object_id")
        conn.execute("ALTER TABLE main.cloud_accounts DROP COLUMN provider_account_key")
        for table in ("storage_upload_intents", "storage_worker_status", "storage_objects"):
            conn.execute(f"DROP TABLE main.{table}")
        conn.execute("DELETE FROM main.sqlite_sequence WHERE name='storage_objects'")
        conn.execute("DELETE FROM schema_migrations WHERE version=14")
        conn.execute("PRAGMA user_version=13")
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


__all__ = ["revert_prod1_v14_to_v13"]
