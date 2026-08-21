"""Central prod-1 schema ownership and validator helpers."""
from __future__ import annotations

import sqlite3

import pytest

from app import db_maintenance
from app.prod1_schema import Prod1SchemaError, bootstrap_prod1_schema


def _prod1():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    bootstrap_prod1_schema(conn)
    return conn


@pytest.mark.parametrize("helper", [
    db_maintenance.ensure_reportes_table,
    db_maintenance.ensure_requisicao_arquivos_table,
    db_maintenance.ensure_usuario_profile_schema,
    db_maintenance.ensure_requisicao_alert_receipts_table,
    db_maintenance.ensure_matrizes_atividades_table,
    db_maintenance.ensure_matriz_atividade_links_table,
    db_maintenance.ensure_atividade_versioning_schema,
])
def test_runtime_schema_helpers_are_nonmutating_prod1_validators(helper):
    conn = _prod1()
    before = conn.total_changes
    helper(conn)
    assert conn.total_changes == before


def test_runtime_schema_helpers_reject_partial_databases_without_mutation():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE usuarios(id INTEGER PRIMARY KEY)")
    before = list(conn.iterdump())
    with pytest.raises(Prod1SchemaError):
        db_maintenance.ensure_usuario_profile_schema(conn)
    assert list(conn.iterdump()) == before


def test_schema_status_is_prod1_v1():
    conn = _prod1()
    status = db_maintenance.get_schema_status(conn)
    assert status["schema_epoch"] == status["target_schema_epoch"] == "prod-1"
    assert status["schema_version"] == status["target_schema_version"] == 1
    assert status["latest_migration"]["name"] == "first_production_baseline"


def test_access_defaults_are_idempotent_and_do_not_overwrite_customization():
    conn = _prod1()
    db_maintenance.seed_usuario_access_default_data(conn)
    conn.execute("UPDATE configuracoes_acesso SET senha_padrao='custom' WHERE nivel_acesso='admin_total'")
    db_maintenance.seed_usuario_access_default_data(conn)
    assert conn.execute(
        "SELECT senha_padrao FROM configuracoes_acesso WHERE nivel_acesso='admin_total'"
    ).fetchone()[0] == "custom"


def test_access_orchestrator_preserves_outer_transaction_ownership():
    conn = _prod1()
    conn.commit()
    conn.execute("BEGIN")
    db_maintenance.ensure_usuario_access_schema(conn)
    assert conn.in_transaction
    conn.rollback()
