"""Test-only inverse of the prod-1 v12 -> v13 database-image migration.

Two consumers, one definition:

* predecessor fixtures that reconstruct an older schema by reverting deltas
  from the bootstrapped head -- ``revert_prod1_v12_to_v11`` calls this first
  when it is handed the v13 head, so every existing builder keeps working;
* the v13 rollback proof, which reverts a migrated copy and demands the frozen
  v12 digest back, data included.

It is deliberately NOT production code: v13 has no shipped downgrade path.
The image tables must be empty -- a downgrade would otherwise lose images.
"""

from __future__ import annotations

import sqlite3

from app.prod1_images_ddl import IMAGES_V13_TABLES
from tests.prod1_v14_support import revert_prod1_v14_to_v13


def revert_prod1_v13_to_v12(conn: sqlite3.Connection) -> None:
    """Drop the three (empty) image tables and marker 13.

    Handed the bootstrapped head (v14 or v15), it reverts down to v13 first.
    """
    if conn.execute("PRAGMA user_version").fetchone()[0] in (14, 15):
        revert_prod1_v14_to_v13(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 13
    for table in IMAGES_V13_TABLES:
        assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0, table
    conn.commit()
    try:
        conn.execute("BEGIN IMMEDIATE")
        for table in reversed(IMAGES_V13_TABLES):
            conn.execute(f"DROP TABLE main.{table}")
        conn.execute("DELETE FROM schema_migrations WHERE version=13")
        conn.execute("PRAGMA user_version=12")
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


__all__ = ["revert_prod1_v13_to_v12"]
