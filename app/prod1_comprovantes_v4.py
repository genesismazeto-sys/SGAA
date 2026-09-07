# flake8: noqa: E501
from __future__ import annotations

import sqlite3

from app.prod1_schema import (
    BASELINE_MARKER,
    COMPROVANTES_GOOGLE_DRIVE_MARKER,
    SCHEMA_EPOCH,
    Prod1SchemaError,
    _quote_identifier,
    _validate_prod1_v3_schema,
    _validate_prod1_v4_schema,
    canonical_prod1_object_sql,
)


def migrate_prod1_v3_to_v4(conn: sqlite3.Connection) -> dict[str, object]:
    """Add immutable turma context and provider custody to comprovantes."""
    if conn.in_transaction:
        raise Prod1SchemaError("prod-1/v4 migration requires a clean connection")
    _validate_prod1_v3_schema(conn)
    foreign_keys_enabled = bool(conn.execute("PRAGMA foreign_keys").fetchone()[0])
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        conn.execute("BEGIN IMMEDIATE")
        for name in (
            "trg_requisicoes_snapshot_immutable",
            "idx_reqs_aluno", "idx_reqs_status",
            "idx_requisicoes_atividade_versao_id",
            "idx_reqs_aluno_update_pending", "idx_req_arquivos_req",
        ):
            kind = "TRIGGER" if name.startswith("trg_") else "INDEX"
            conn.execute(f"DROP {kind} IF EXISTS {_quote_identifier(name)}")

        requisicoes_sql = canonical_prod1_object_sql("table", "requisicoes")
        arquivos_sql = canonical_prod1_object_sql("table", "requisicao_arquivos")
        conn.execute(
            requisicoes_sql.replace(
                "CREATE TABLE requisicoes", "CREATE TABLE _requisicoes_v4", 1
            )
        )
        conn.execute(
            """INSERT INTO _requisicoes_v4 (
                   id,aluno_id,atividade_versao_id,data_solicitacao,data_evento,
                   horas_solicitadas,nome_evento,status,horas_deferidas,observacao,
                   data_processamento,admin_id,aluno_update_notified_at,
                   aluno_update_seen_at,regra_snapshot_json,
                   turma_id_snapshot,turma_codigo_snapshot)
               SELECT id,aluno_id,atividade_versao_id,data_solicitacao,data_evento,
                      horas_solicitadas,nome_evento,status,horas_deferidas,observacao,
                      data_processamento,admin_id,aluno_update_notified_at,
                      aluno_update_seen_at,regra_snapshot_json,NULL,NULL
                 FROM requisicoes"""
        )
        conn.execute("DROP TABLE requisicoes")
        conn.execute(requisicoes_sql)
        conn.execute(
            """INSERT INTO requisicoes (
                   id,aluno_id,atividade_versao_id,data_solicitacao,data_evento,
                   horas_solicitadas,nome_evento,status,horas_deferidas,observacao,
                   data_processamento,admin_id,aluno_update_notified_at,
                   aluno_update_seen_at,regra_snapshot_json,
                   turma_id_snapshot,turma_codigo_snapshot)
               SELECT id,aluno_id,atividade_versao_id,data_solicitacao,data_evento,
                      horas_solicitadas,nome_evento,status,horas_deferidas,observacao,
                      data_processamento,admin_id,aluno_update_notified_at,
                      aluno_update_seen_at,regra_snapshot_json,
                      turma_id_snapshot,turma_codigo_snapshot
                 FROM _requisicoes_v4"""
        )
        conn.execute("DROP TABLE _requisicoes_v4")

        conn.execute(
            arquivos_sql.replace(
                "CREATE TABLE requisicao_arquivos",
                "CREATE TABLE _requisicao_arquivos_v4",
                1,
            )
        )
        conn.execute(
            """INSERT INTO _requisicao_arquivos_v4 (
                   id,requisicao_id,label,filename,criado_em,provider,storage_status)
               SELECT id,requisicao_id,label,filename,criado_em,
                      'local_legacy','legacy_active'
                 FROM requisicao_arquivos"""
        )
        conn.execute("DROP TABLE requisicao_arquivos")
        conn.execute(arquivos_sql)
        conn.execute(
            """INSERT INTO requisicao_arquivos (
                   id,requisicao_id,label,filename,criado_em,provider,remote_file_id,
                   remote_parent_id,original_filename,mime_type,size_bytes,sha256,
                   uploaded_at,uploader_user_id,operation_key,storage_status,failure_code,
                   delete_previous_status,delete_started_at)
               SELECT id,requisicao_id,label,filename,criado_em,provider,remote_file_id,
                      remote_parent_id,original_filename,mime_type,size_bytes,sha256,
                      uploaded_at,uploader_user_id,operation_key,storage_status,failure_code,
                      delete_previous_status,delete_started_at
                 FROM _requisicao_arquivos_v4"""
        )
        conn.execute("DROP TABLE _requisicao_arquivos_v4")

        schema_objects = {
            "index": (
                "idx_reqs_aluno", "idx_reqs_status",
                "idx_requisicoes_atividade_versao_id",
                "idx_reqs_aluno_update_pending", "idx_req_arquivos_req",
                "idx_req_arquivos_req_status", "ux_req_arquivos_provider_remote_file",
                "ux_req_arquivos_operation_key",
            ),
            "trigger": (
                "trg_requisicoes_snapshot_immutable",
                "trg_requisicoes_turma_snapshot_insert",
                "trg_requisicoes_turma_snapshot_update",
                "trg_requisicao_arquivos_custody_insert",
                "trg_requisicao_arquivos_custody_update",
            ),
        }
        for kind, names in schema_objects.items():
            for name in names:
                conn.execute(canonical_prod1_object_sql(kind, name))
        conn.execute(
            "INSERT INTO schema_migrations(version,name,schema_epoch,details_json) VALUES(?,?,?,?)",
            (4, COMPROVANTES_GOOGLE_DRIVE_MARKER, SCHEMA_EPOCH,
             '{"schema_epoch":"prod-1","storage_provider":"google","legacy_provider":"local_legacy"}'),
        )
        conn.execute("PRAGMA user_version=4")
        _validate_prod1_v4_schema(conn)
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise Prod1SchemaError("prod-1/v4 integrity check failed")
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute(f"PRAGMA foreign_keys={'ON' if foreign_keys_enabled else 'OFF'}")
    _validate_prod1_v4_schema(conn)
    return {
        "schema_epoch": SCHEMA_EPOCH,
        "schema_version": 4,
        "baseline_marker": BASELINE_MARKER,
        "table_count": len(
            conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        ),
    }
