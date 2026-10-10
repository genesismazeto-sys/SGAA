"""Test-only inverse of the prod-1 v11 -> v12 extension-hours migration.

Two consumers, one definition:

* predecessor fixtures that reconstruct an older schema by reverting deltas
  from the bootstrapped head -- ``revert_prod1_v11_to_v10`` calls this first
  when it is handed the v12 head, so every existing builder keeps working;
* the v12 rollback proof, which reverts a migrated copy and demands the frozen
  v11 digest back, data included.

It is deliberately NOT production code: v12 has no shipped downgrade path.
"""

from __future__ import annotations

import sqlite3

from app.prod1_extension_hours_ddl import (
    CURSOS_COLUMNS,
    CURSOS_V12_TABLE_SQL,
    MATRIZES_ATIVIDADES_COLUMNS,
    MATRIZES_ATIVIDADES_INDEX_SQL,
    MATRIZES_ATIVIDADES_V12_TABLE_SQL,
)
from tests.prod1_v13_support import revert_prod1_v13_to_v12

CURSOS_V11_TABLE_SQL = CURSOS_V12_TABLE_SQL.replace(
    "total_horas_aeu INTEGER NOT NULL DEFAULT 160",
    "total_horas_aeu INTEGER NOT NULL DEFAULT 80",
)
MATRIZES_ATIVIDADES_V11_TABLE_SQL = MATRIZES_ATIVIDADES_V12_TABLE_SQL.replace(
    "horas_extensao_obrigatorias INTEGER NOT NULL DEFAULT 160",
    "horas_extensao_obrigatorias INTEGER NOT NULL DEFAULT 80",
)
assert CURSOS_V11_TABLE_SQL != CURSOS_V12_TABLE_SQL
assert MATRIZES_ATIVIDADES_V11_TABLE_SQL != MATRIZES_ATIVIDADES_V12_TABLE_SQL


def revert_prod1_v12_to_v11(conn: sqlite3.Connection) -> None:
    """Rebuild both tables with the v11 DEFAULT 80 and drop marker 12.

    Rows, ids and AUTOINCREMENT counters are carried over exactly, as the
    forward migration does.  Handed a later head (v13, v14 or v15), it reverts
    down to v12 first, so every predecessor builder keeps a single "revert from the
    head" call.
    """
    if conn.execute("PRAGMA user_version").fetchone()[0] in (13, 14, 15, 16):
        revert_prod1_v13_to_v12(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 12
    foreign_keys = bool(conn.execute("PRAGMA foreign_keys").fetchone()[0])
    conn.commit()
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        conn.execute("BEGIN IMMEDIATE")
        tables = (
            ("cursos", CURSOS_COLUMNS, CURSOS_V11_TABLE_SQL),
            ("matrizes_atividades", MATRIZES_ATIVIDADES_COLUMNS, MATRIZES_ATIVIDADES_V11_TABLE_SQL),
        )
        sequences = conn.execute(
            "SELECT name,seq FROM sqlite_sequence WHERE name IN ('cursos','matrizes_atividades')"
        ).fetchall()
        for table, columns, _sql in tables:
            conn.execute(f"CREATE TEMP TABLE _{table}_v12 AS SELECT {','.join(columns)} FROM main.{table}")
        conn.execute("DROP TABLE main.matrizes_atividades")
        conn.execute("DROP TABLE main.cursos")
        for table, columns, sql in tables:
            conn.execute(sql)
        for statement in MATRIZES_ATIVIDADES_INDEX_SQL:
            conn.execute(statement)
        for table, columns, _sql in tables:
            column_list = ",".join(columns)
            conn.execute(
                f"INSERT INTO main.{table}({column_list})"
                f" SELECT {column_list} FROM temp._{table}_v12 ORDER BY id"
            )
            conn.execute(f"DROP TABLE temp._{table}_v12")
        # An INSERT...SELECT creates a counter even when it copies no row;
        # keep exactly the counters that existed.
        conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('cursos','matrizes_atividades')")
        for name, seq in sequences:
            conn.execute("INSERT INTO sqlite_sequence(name,seq) VALUES(?,?)", (name, seq))
        conn.execute("DELETE FROM schema_migrations WHERE version=12")
        conn.execute("PRAGMA user_version=11")
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute(f"PRAGMA foreign_keys={'ON' if foreign_keys else 'OFF'}")


__all__ = [
    "CURSOS_V11_TABLE_SQL",
    "MATRIZES_ATIVIDADES_V11_TABLE_SQL",
    "revert_prod1_v12_to_v11",
]
