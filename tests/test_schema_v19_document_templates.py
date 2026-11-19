"""prod-1/v19: the document-template tables, on both authorities.

v19 is purely additive. A v18 database migrates to exactly the fresh head,
keeping every row and counter; anything but the frozen v18 contract is
refused; a failed migration leaves v18 untouched; the PostgreSQL authority
declares the same tables; Path-B and the backup registers know them.
"""
from __future__ import annotations

import sqlite3

import pytest

from app import pg_migrate_from_sqlite as pathb
from app import pg_schema, prod1_schema
from app.backup import pg_snapshot
from app.prod1_document_templates_ddl import DOCUMENT_TEMPLATES_V19_TABLES, DOCX_MIME_TYPE
from tests.prod1_v19_support import revert_prod1_v19_to_v18


def _head():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    prod1_schema.bootstrap_prod1_schema(conn)
    return conn


def _v18_with_rows():
    conn = _head()
    revert_prod1_v19_to_v18(conn)
    conn.execute("INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES ('A', 'a@example.test', 'x', 'admin', 'admin_total')")
    conn.execute("INSERT INTO atividade_base (nome_conceito, status) VALUES ('Conceito', 'ativo')")
    conn.execute("INSERT INTO atividade_versao (atividade_base_id, eixo, numero_versao, status) VALUES (1, 'AAC', 1, 'ativa')")
    conn.commit()
    return conn


def _rows(conn):
    return {
        table: conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
        for table in ("usuarios", "atividade_base", "atividade_versao")
    }


def test_the_reverted_head_is_exactly_the_frozen_v18_contract():
    conn = _head()
    revert_prod1_v19_to_v18(conn)
    prod1_schema._validate_prod1_v18_schema(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 18


def test_v18_migrates_to_the_fresh_head_and_keeps_every_row_and_counter():
    conn = _v18_with_rows()
    before = _rows(conn)
    sequences = conn.execute("SELECT name, seq FROM sqlite_sequence ORDER BY name").fetchall()
    result = prod1_schema.bootstrap_prod1_schema(conn)
    assert (result["schema_version"], result["document_templates"], result["backfill"]) == (19, "enabled", "none")
    assert _rows(conn) == before
    assert conn.execute("SELECT name, seq FROM sqlite_sequence ORDER BY name").fetchall() == sequences
    assert prod1_schema._physical_schema_digest(conn) == prod1_schema._physical_schema_digest(_head())
    for table in DOCUMENT_TEMPLATES_V19_TABLES:
        assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    marker = conn.execute("SELECT name, details_json FROM schema_migrations WHERE version = 19").fetchone()
    assert marker[0] == "document_templates" and DOCX_MIME_TYPE in marker[1]
    assert prod1_schema.bootstrap_prod1_schema(conn) == prod1_schema.validate_prod1_schema(conn)


def test_a_tampered_v18_is_refused_and_left_alone():
    conn = _v18_with_rows()
    conn.execute("CREATE TABLE intruso (id INTEGER)")
    conn.commit()
    with pytest.raises(prod1_schema.Prod1SchemaError):
        prod1_schema.migrate_prod1_v18_to_v19(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 18
    assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'atividade_versao_modelos'").fetchone()


def test_a_failed_migration_rolls_everything_back(monkeypatch):
    from app import prod1_document_templates_v19 as migration

    conn = _v18_with_rows()
    before = _rows(conn)
    broken = (*migration.DOCUMENT_TEMPLATES_V19_STATEMENTS[:2], "CREATE TABLE broken (")
    monkeypatch.setattr(migration, "DOCUMENT_TEMPLATES_V19_STATEMENTS", broken)
    with pytest.raises(sqlite3.Error):
        migration.migrate_prod1_v18_to_v19(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 18
    assert _rows(conn) == before
    assert not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name IN ('modelo_documento_arquivos', 'atividade_versao_modelos')"
    ).fetchone()
    prod1_schema._validate_prod1_v18_schema(conn)


def test_both_authorities_declare_the_same_v19_tables_and_columns():
    assert prod1_schema.SCHEMA_VERSION == pg_schema.PG_SCHEMA_VERSION == 19
    assert prod1_schema.LATEST_MIGRATION_MARKER == "document_templates"
    conn = _head()
    for table in DOCUMENT_TEMPLATES_V19_TABLES:
        assert table in prod1_schema.EXPECTED_TABLES and table in pg_schema.PG_APPLICATION_TABLES
        sqlite_columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
        pg_columns = [column["name"] for column in pg_schema.PG_TABLE_SPECS[table]["columns"]]
        assert sqlite_columns == pg_columns, table
    assert {t["name"] for t in pg_schema.PG_TRIGGERS if t["table"] in DOCUMENT_TEMPLATES_V19_TABLES} == {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name IN (?, ?)", DOCUMENT_TEMPLATES_V19_TABLES
        )
    }
    seed = {version: name for version, name, _details in pg_schema.PG_SCHEMA_MIGRATIONS_SEED}
    assert seed[19] == "document_templates"


def test_the_upgrade_accepts_exactly_the_frozen_predecessors():
    import inspect

    source = inspect.getsource(pg_schema.upgrade_pg_schema)
    assert "18: _PG_V18_CONTRACT_SHA256" in source
    assert pg_schema._PG_V18_CONTRACT_SHA256 != pg_schema.PG_CONTRACT_SHA256


def test_path_b_and_the_backup_registers_cover_the_templates():
    for table in DOCUMENT_TEMPLATES_V19_TABLES:
        assert pathb.SOURCE_TABLE_POLICIES[table].policy == pathb.MIGRATE_EXACT
    assert {"modelo_documento_arquivos_content_mismatch", "atividade_versao_modelos_lifecycle_invalid",
            "atividade_versao_modelos_slot_reused"} <= set(pathb.DOMAIN_CHECKS)
    order = pathb.load_order()
    assert order.index("modelo_documento_arquivos") < order.index("atividade_versao_modelos")
    assert order.index("atividade_versao") < order.index("atividade_versao_modelos")
    # The bytes stay out of the readable registers; the associations are registers.
    assert "modelo_documento_arquivos" in pg_snapshot._NOT_REGISTERS
    assert "atividade_versao_modelos" not in pg_snapshot._NOT_REGISTERS
