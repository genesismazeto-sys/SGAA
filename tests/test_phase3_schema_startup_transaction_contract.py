"""Prod-1 startup ownership and transaction contracts."""
from __future__ import annotations

import ast
from pathlib import Path

from app import db as app_db
from app import db_maintenance


ROOT = Path(__file__).resolve().parents[1]


def test_single_init_owner_and_no_main_bridge():
    app_tree = ast.parse((ROOT / "app" / "db.py").read_text(encoding="utf-8"))
    main_tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    app_defs = {node.name for node in app_tree.body if isinstance(node, ast.FunctionDef)}
    main_defs = {node.name for node in main_tree.body if isinstance(node, ast.FunctionDef)}
    assert "init_db" in app_defs
    assert "init_db" not in main_defs
    assert "_get_main_db_helpers" not in app_defs


def test_migration_registry_is_exactly_prod1_v1():
    assert len(db_maintenance.SCHEMA_MIGRATIONS) == 1
    version, marker, owner = db_maintenance.SCHEMA_MIGRATIONS[0]
    assert (version, marker) == (1, "first_production_baseline")
    assert owner.__module__ == "app.prod1_schema"


def test_app_db_bootstrap_calls_only_central_schema_owner():
    source = (ROOT / "app" / "db.py").read_text(encoding="utf-8")
    assert "apply_early_schema_migrations(conn" in source
    assert "CREATE TABLE" not in source.upper()


def test_compatibility_helpers_are_validators_not_ddl_owners():
    source = (ROOT / "app" / "db_maintenance.py").read_text(encoding="utf-8")
    for name in (
        "ensure_reportes_table", "ensure_requisicao_arquivos_table",
        "ensure_matrizes_atividades_table", "ensure_matriz_atividade_links_table",
    ):
        function = next(
            node for node in ast.parse(source).body
            if isinstance(node, ast.FunctionDef) and node.name == name
        )
        segment = ast.get_source_segment(source, function)
        assert "CREATE TABLE" not in segment.upper()
