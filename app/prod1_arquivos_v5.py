from __future__ import annotations

import sqlite3

from app.prod1_schema import (
    ARQUIVOS_GOOGLE_DRIVE_MARKER,
    SCHEMA_EPOCH,
    Prod1SchemaError,
    _quote_identifier,
    _validate_prod1_v4_schema,
    canonical_prod1_object_sql,
    _validate_prod1_v5_schema,
)


def migrate_prod1_v4_to_v5(conn: sqlite3.Connection) -> dict[str, object]:
    """Add provider custody to ARQUIVOS without moving historical bytes."""
    if conn.in_transaction:
        raise Prod1SchemaError("prod-1/v5 migration requires a clean connection")
    _validate_prod1_v4_schema(conn)
    sequence_row = conn.execute(
        "SELECT seq FROM sqlite_sequence WHERE name='admin_arquivos'"
    ).fetchone()
    consumed_high_water = int(sequence_row[0]) if sequence_row else 0
    foreign_keys_enabled = bool(conn.execute("PRAGMA foreign_keys").fetchone()[0])
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        conn.execute("BEGIN IMMEDIATE")
        table_sql = canonical_prod1_object_sql("table", "admin_arquivos")
        conn.execute(
            table_sql.replace("CREATE TABLE admin_arquivos", "CREATE TABLE _admin_arquivos_v5", 1)
        )
        conn.execute(
            """INSERT INTO _admin_arquivos_v5 (
                   id,titulo,descricao,filename,original_filename,visivel,criado_em,
                   provider,storage_status)
               SELECT id,titulo,descricao,filename,original_filename,visivel,criado_em,
                      'local_legacy','legacy_active'
                 FROM admin_arquivos"""
        )
        conn.execute("DROP TABLE admin_arquivos")
        conn.execute(table_sql)
        conn.execute(
            """INSERT INTO admin_arquivos
               SELECT * FROM _admin_arquivos_v5"""
        )
        conn.execute("DROP TABLE _admin_arquivos_v5")
        existing_high_water = int(
            conn.execute("SELECT COALESCE(MAX(id),0) FROM admin_arquivos").fetchone()[0]
        )
        restored_high_water = max(consumed_high_water, existing_high_water)
        conn.execute("DELETE FROM sqlite_sequence WHERE name='admin_arquivos'")
        if restored_high_water:
            conn.execute(
                "INSERT INTO sqlite_sequence(name,seq) VALUES('admin_arquivos',?)",
                (restored_high_water,),
            )
        for kind, names in {
            "index": (
                "idx_admin_arquivos_visivel",
                "idx_admin_arquivos_criado_em",
                "ux_admin_arquivos_provider_remote_file",
                "ux_admin_arquivos_operation_key",
            ),
            "trigger": (
                "trg_admin_arquivos_custody_insert",
                "trg_admin_arquivos_custody_update",
            ),
        }.items():
            for name in names:
                conn.execute(canonical_prod1_object_sql(kind, name))
        conn.execute(
            "INSERT INTO schema_migrations(version,name,schema_epoch,details_json) VALUES(?,?,?,?)",
            (
                5,
                ARQUIVOS_GOOGLE_DRIVE_MARKER,
                SCHEMA_EPOCH,
                '{"schema_epoch":"prod-1","storage_provider":"google","legacy_provider":"local_legacy"}',
            ),
        )
        conn.execute("PRAGMA user_version=5")
        _validate_prod1_v5_schema(conn)
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise Prod1SchemaError("prod-1/v5 integrity check failed")
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute(f"PRAGMA foreign_keys={'ON' if foreign_keys_enabled else 'OFF'}")
    _validate_prod1_v5_schema(conn)
    return {
        "schema_epoch": SCHEMA_EPOCH,
        "schema_version": 5,
        "baseline_marker": "first_production_baseline",
    }


__all__ = ["migrate_prod1_v4_to_v5"]
