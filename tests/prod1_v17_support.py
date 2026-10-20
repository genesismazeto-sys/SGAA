"""Test-only inverse of the prod-1 v16 -> v17 request-reclassification migration.

Two consumers, one definition:

* predecessor fixtures that reconstruct an older schema by reverting deltas
  from the bootstrapped head -- ``revert_prod1_v16_to_v15`` calls this first
  when it is handed the v17 head, so every existing builder keeps working;
* the v17 proofs (fresh v17 == v16 -> v17, rows preserved), which need the
  frozen v16 physical schema back, data included.

It is deliberately NOT production code: v17 has no shipped downgrade path.
"""

from __future__ import annotations

import sqlite3

from app.prod1_schema import canonical_prod1_pre_v17_object_sql


def revert_prod1_v17_to_v16(conn: sqlite3.Connection) -> None:
    """Restore the v16 snapshot trigger and drop marker 17."""
    if conn.execute("PRAGMA user_version").fetchone()[0] == 18:
        from tests.prod1_v18_support import revert_prod1_v18_to_v17
        revert_prod1_v18_to_v17(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 17
    conn.commit()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DROP TRIGGER trg_requisicoes_snapshot_immutable")
        conn.execute(canonical_prod1_pre_v17_object_sql("trigger", "trg_requisicoes_snapshot_immutable"))
        conn.execute("DELETE FROM schema_migrations WHERE version=17")
        conn.execute("PRAGMA user_version=16")
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


__all__ = ["revert_prod1_v17_to_v16"]
