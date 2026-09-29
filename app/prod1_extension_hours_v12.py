"""prod-1 v11 -> v12: Extensão defaults to 160 h for future rows.

WHAT CHANGES
    ``cursos.total_horas_aeu`` and ``matrizes_atividades.horas_extensao_
    obrigatorias`` change their column DEFAULT from 80 to 160 -- see
    ``app.prod1_extension_hours_ddl``. Only rows inserted after the migration
    without an explicit value see the new default.

WHAT DOES NOT CHANGE
    Every stored row, byte for byte: ids, names, codes, statuses and every
    hours value -- a course or matrix holding 80 keeps 80, 120 keeps 120, 160
    keeps 160. There is no backfill. The AUTOINCREMENT counters
    (``sqlite_sequence``) are carried over too, so an id freed by an earlier
    delete is never handed out again. Foreign keys, CHECK constraints and the
    ``matrizes_atividades`` indexes are recreated exactly.

HOW
    SQLite cannot alter a DEFAULT, so both tables are rebuilt the way v3 and
    v11 rebuilt theirs: rows are staged in TEMP tables, the originals are
    dropped (foreign keys off, so the children -- turmas, alunos, matrix items
    -- are untouched and keep pointing at the same ids), the canonical v12 DDL
    is created under the real names and the rows are copied back. Everything
    is compared again inside the transaction and the whole database must pass
    ``integrity_check`` and ``foreign_key_check`` before COMMIT.
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


_V12_DETAILS_JSON = (
    '{"schema_epoch":"prod-1","extension_hours_default":160,'
    '"columns":["cursos.total_horas_aeu","matrizes_atividades.horas_extensao_obrigatorias"],'
    '"backfill":"none_stored_values_kept"}'
)

_REBUILT_TABLES = (
    ("cursos", CURSOS_COLUMNS),
    ("matrizes_atividades", MATRIZES_ATIVIDADES_COLUMNS),
)


def _rows(conn: sqlite3.Connection, table: str, columns: tuple[str, ...]) -> list[tuple]:
    return [
        tuple(row)
        for row in conn.execute(
            f"SELECT {','.join(columns)} FROM main.{table} ORDER BY id"
        ).fetchall()
    ]


def _sequences(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        str(name): int(seq)
        for name, seq in conn.execute(
            "SELECT name,seq FROM main.sqlite_sequence WHERE name IN (?,?)",
            tuple(table for table, _columns in _REBUILT_TABLES),
        ).fetchall()
    }


def _child_rows(conn: sqlite3.Connection) -> list[tuple]:
    """Every row that points at a rebuilt table; none may move."""
    return [
        tuple(conn.execute("SELECT id,curso_id,matriz_id FROM turmas ORDER BY id").fetchall()),
        tuple(conn.execute("SELECT id,matriz_id FROM alunos ORDER BY id").fetchall()),
        tuple(
            conn.execute(
                "SELECT matriz_id,atividade_base_id,atividade_versao_id"
                " FROM matriz_atividade_versao_item ORDER BY 1,2,3"
            ).fetchall()
        ),
    ]


def migrate_prod1_v11_to_v12(conn: sqlite3.Connection) -> dict[str, object]:
    from app.prod1_schema import (
        EXTENSION_HOURS_DEFAULT_MARKER,
        SCHEMA_EPOCH,
        Prod1SchemaError,
        _validate_prod1_v11_schema,
        validate_prod1_schema,
    )

    if conn.in_transaction:
        raise Prod1SchemaError("prod-1/v12 migration requires a clean connection")
    _validate_prod1_v11_schema(conn)

    foreign_keys_enabled = bool(conn.execute("PRAGMA foreign_keys").fetchone()[0])
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        conn.execute("BEGIN IMMEDIATE")
        rows_before = {table: _rows(conn, table, columns) for table, columns in _REBUILT_TABLES}
        sequences_before = _sequences(conn)
        children_before = _child_rows(conn)

        for table, columns in _REBUILT_TABLES:
            conn.execute(
                f"CREATE TEMP TABLE _{table}_v11 AS SELECT {','.join(columns)} FROM main.{table}"
            )
        # Child first: dropping a table also drops its indexes.
        conn.execute("DROP TABLE main.matrizes_atividades")
        conn.execute("DROP TABLE main.cursos")
        conn.execute(CURSOS_V12_TABLE_SQL)
        conn.execute(MATRIZES_ATIVIDADES_V12_TABLE_SQL)
        for statement in MATRIZES_ATIVIDADES_INDEX_SQL:
            conn.execute(statement)
        for table, columns in _REBUILT_TABLES:
            column_list = ",".join(columns)
            conn.execute(
                f"INSERT INTO main.{table}({column_list})"
                f" SELECT {column_list} FROM temp._{table}_v11 ORDER BY id"
            )
            conn.execute(f"DROP TABLE temp._{table}_v11")
        # DROP TABLE removed their counters and the copy restarted them at
        # max(id) -- or created one at 0 for a table that never had a row.
        # Put back exactly the counters that existed, and nothing else.
        for table, _columns in _REBUILT_TABLES:
            conn.execute("DELETE FROM main.sqlite_sequence WHERE name=?", (table,))
            if table in sequences_before:
                conn.execute(
                    "INSERT INTO main.sqlite_sequence(name,seq) VALUES(?,?)",
                    (table, sequences_before[table]),
                )

        conn.execute(
            "INSERT INTO schema_migrations(version,name,schema_epoch,details_json)"
            " VALUES(?,?,?,?)",
            (12, EXTENSION_HOURS_DEFAULT_MARKER, SCHEMA_EPOCH, _V12_DETAILS_JSON),
        )
        conn.execute("PRAGMA user_version=12")

        for table, columns in _REBUILT_TABLES:
            if _rows(conn, table, columns) != rows_before[table]:
                raise Prod1SchemaError(f"prod-1/v12 migration changed {table} rows")
        if _sequences(conn) != sequences_before:
            raise Prod1SchemaError("prod-1/v12 migration changed AUTOINCREMENT counters")
        if _child_rows(conn) != children_before:
            raise Prod1SchemaError("prod-1/v12 migration changed rows that reference courses or matrices")
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise Prod1SchemaError("prod-1/v12 integrity check failed")
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise Prod1SchemaError(f"prod-1/v12 foreign key violations: {violations!r}")
        validate_prod1_schema(conn)
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute(f"PRAGMA foreign_keys={'ON' if foreign_keys_enabled else 'OFF'}")

    status = validate_prod1_schema(conn)
    return {
        **status,
        "extension_hours_default": 160,
        "rows_preserved": {table: len(rows) for table, rows in rows_before.items()},
    }


__all__ = ["migrate_prod1_v11_to_v12"]
