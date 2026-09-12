from __future__ import annotations

import sqlite3

from app.prod1_schema import (
    SCHEMA_EPOCH,
    STUDENT_MATRIX_AUTHORITY_MARKER,
    Prod1SchemaError,
    _validate_prod1_v5_schema,
    canonical_prod1_object_sql,
    validate_prod1_schema,
)


def migrate_prod1_v5_to_v6(conn: sqlite3.Connection) -> dict[str, object]:
    """Make the student's compatible Matrix the academic authority."""
    if conn.in_transaction:
        raise Prod1SchemaError("prod-1/v6 migration requires a clean connection")
    _validate_prod1_v5_schema(conn)
    sequence_row = conn.execute(
        "SELECT seq FROM sqlite_sequence WHERE name='alunos'"
    ).fetchone()
    consumed_high_water = int(sequence_row[0]) if sequence_row else 0
    foreign_keys_enabled = bool(conn.execute("PRAGMA foreign_keys").fetchone()[0])
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        conn.execute("BEGIN IMMEDIATE")
        table_sql = canonical_prod1_object_sql("table", "alunos")
        conn.execute(
            table_sql.replace("CREATE TABLE alunos", "CREATE TABLE _alunos_v6", 1)
        )
        conn.execute(
            """
            INSERT INTO _alunos_v6 (
                id,usuario_id,nome,matricula,email,turma_id,matriz_id,
                foto_perfil,status
            )
            SELECT a.id,a.usuario_id,a.nome,a.matricula,a.email,a.turma_id,
                   CASE WHEN t.id IS NOT NULL
                              AND t.matriz_id IS NOT NULL
                              AND m.id IS NOT NULL
                         THEN m.id ELSE NULL END,
                   a.foto_perfil,a.status
              FROM alunos a
              LEFT JOIN turmas t ON t.id=a.turma_id
              LEFT JOIN matrizes_atividades m
                ON m.id=t.matriz_id AND m.curso_id=t.curso_id
            """
        )
        conn.execute("DROP TABLE alunos")
        conn.execute(table_sql)
        conn.execute("INSERT INTO alunos SELECT * FROM _alunos_v6")
        conn.execute("DROP TABLE _alunos_v6")

        existing_high_water = int(
            conn.execute("SELECT COALESCE(MAX(id),0) FROM alunos").fetchone()[0]
        )
        restored_high_water = max(consumed_high_water, existing_high_water)
        conn.execute("DELETE FROM sqlite_sequence WHERE name='alunos'")
        if restored_high_water:
            conn.execute(
                "INSERT INTO sqlite_sequence(name,seq) VALUES('alunos',?)",
                (restored_high_water,),
            )
        for name in (
            "idx_alunos_usuario_id",
            "idx_alunos_matricula",
            "idx_alunos_email",
            "idx_alunos_turma_id",
            "idx_alunos_matriz_id",
        ):
            conn.execute(canonical_prod1_object_sql("index", name))
        conn.execute(
            "INSERT INTO schema_migrations(version,name,schema_epoch,details_json) VALUES(?,?,?,?)",
            (
                6,
                STUDENT_MATRIX_AUTHORITY_MARKER,
                SCHEMA_EPOCH,
                '{"schema_epoch":"prod-1","authority":"alunos.matriz_id","turma_matrix_semantics":"optional_default"}',
            ),
        )
        conn.execute("PRAGMA user_version=6")
        validate_prod1_schema(conn)
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise Prod1SchemaError("prod-1/v6 integrity check failed")
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute(f"PRAGMA foreign_keys={'ON' if foreign_keys_enabled else 'OFF'}")
    return validate_prod1_schema(conn)


__all__ = ["migrate_prod1_v5_to_v6"]
