"""Test-only inverse of the prod-1 v15 -> v16 ephemeral-state migration.

Two consumers, one definition:

* predecessor fixtures that reconstruct an older schema by reverting deltas
  from the bootstrapped head -- ``revert_prod1_v15_to_v14`` calls this first
  when it is handed the v16 head, so every existing builder keeps working;
* the v16 proofs (fresh v16 == v15 -> v16, rollback), which need the frozen
  v15 physical schema back, data included.

It is deliberately NOT production code: v16 has no shipped downgrade path.
Both tables must be empty -- a downgrade would otherwise discard live throttle
windows or a pending import preview.
"""

from __future__ import annotations

import sqlite3

from app.prod1_ephemeral_state_ddl import EPHEMERAL_STATE_V16_TABLES


def revert_prod1_v16_to_v15(conn: sqlite3.Connection) -> None:
    """Drop the (empty) v16 tables with their indexes and marker 16."""
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 16
    for table in EPHEMERAL_STATE_V16_TABLES:
        assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0, table
    conn.commit()
    try:
        conn.execute("BEGIN IMMEDIATE")
        for table in EPHEMERAL_STATE_V16_TABLES:
            conn.execute(f"DROP TABLE main.{table}")
            conn.execute("DELETE FROM main.sqlite_sequence WHERE name=?", (table,))
        conn.execute("DELETE FROM schema_migrations WHERE version=16")
        conn.execute("PRAGMA user_version=15")
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


__all__ = ["revert_prod1_v16_to_v15"]
