import ast
import inspect
import os
import sqlite3
import subprocess
import sys
import textwrap


BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main
from app import db as app_db
from app import db_maintenance
from app.views import aluno as aluno_views


BASELINE_ENSURE_REPORTES_TABLE_SOURCE = '''
def ensure_reportes_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reportes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            aluno_id INTEGER NOT NULL,
            titulo TEXT NOT NULL,
            descricao TEXT NOT NULL,
            categoria TEXT NOT NULL DEFAULT 'Bug na plataforma',
            screenshot_filename TEXT,
            status TEXT NOT NULL DEFAULT 'Novo' CHECK(status IN ('Novo', 'Em análise', 'Resolvido')),
            criado_em TEXT NOT NULL DEFAULT (datetime('now')),
            atualizado_em TEXT NOT NULL DEFAULT (datetime('now')),
            admin_id INTEGER,
            FOREIGN KEY (aluno_id) REFERENCES alunos(id) ON DELETE CASCADE ON UPDATE CASCADE,
            FOREIGN KEY (admin_id) REFERENCES usuarios(id) ON DELETE SET NULL ON UPDATE CASCADE
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reportes_aluno_id ON reportes(aluno_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reportes_status ON reportes(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reportes_criado_em ON reportes(criado_em)")
'''


def _function_body_ast(function):
    node = ast.parse(textwrap.dedent(inspect.getsource(function))).body[0]
    assert isinstance(node, ast.FunctionDef)
    return ast.dump(ast.Module(body=node.body, type_ignores=[]), include_attributes=False)


def _baseline_function_body_ast():
    node = ast.parse(textwrap.dedent(BASELINE_ENSURE_REPORTES_TABLE_SOURCE)).body[0]
    assert isinstance(node, ast.FunctionDef)
    return ast.dump(ast.Module(body=node.body, type_ignores=[]), include_attributes=False)


def _lazy_return_keys(function):
    node = ast.parse(textwrap.dedent(inspect.getsource(function))).body[0]
    assert isinstance(node, ast.FunctionDef)
    returns = [child for child in ast.walk(node) if isinstance(child, ast.Return)]
    assert len(returns) == 1
    mapping = returns[0].value
    assert isinstance(mapping, ast.Dict)
    return {key.value for key in mapping.keys if isinstance(key, ast.Constant)}


def _new_reportes_connection():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("CREATE TABLE alunos (id INTEGER PRIMARY KEY)")
    conn.execute("CREATE TABLE usuarios (id INTEGER PRIMARY KEY)")
    return conn


def test_reportes_helper_body_is_ast_equivalent_to_accepted_baseline():
    assert _function_body_ast(db_maintenance.ensure_reportes_table) == _baseline_function_body_ast()


def test_reportes_helper_owner_exports_and_direct_consumers():
    assert main.ensure_reportes_table is db_maintenance.ensure_reportes_table
    assert app_db.ensure_reportes_table is db_maintenance.ensure_reportes_table
    assert aluno_views.ensure_reportes_table is db_maintenance.ensure_reportes_table

    assert "ensure_reportes_table" not in _lazy_return_keys(app_db._get_main_db_helpers)
    assert "ensure_reportes_table" not in _lazy_return_keys(aluno_views._get_main_helpers)
    assert 'helpers["ensure_reportes_table"]' not in inspect.getsource(app_db._init_db_impl)
    assert 'helpers["ensure_reportes_table"]' not in inspect.getsource(aluno_views.aluno_reportar)
    assert "_get_main_helpers()" not in inspect.getsource(aluno_views.aluno_reportar)


def test_db_maintenance_import_does_not_import_main():
    code = (
        "import importlib, sys; "
        "assert 'main' not in sys.modules; "
        "module = importlib.import_module('app.db_maintenance'); "
        "assert module.ensure_reportes_table; "
        "assert 'main' not in sys.modules"
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", code],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    assert result.returncode == 0, result.stderr


def test_reportes_schema_is_exact_and_idempotent():
    conn = _new_reportes_connection()
    try:
        db_maintenance.ensure_reportes_table(conn)
        first_schema = conn.execute(
            "SELECT type, name, sql FROM sqlite_master "
            "WHERE tbl_name = 'reportes' ORDER BY type, name"
        ).fetchall()
        db_maintenance.ensure_reportes_table(conn)
        second_schema = conn.execute(
            "SELECT type, name, sql FROM sqlite_master "
            "WHERE tbl_name = 'reportes' ORDER BY type, name"
        ).fetchall()

        columns = conn.execute("PRAGMA table_info(reportes)").fetchall()
        assert [(row[1], row[2], row[3], row[4], row[5]) for row in columns] == [
            ("id", "INTEGER", 0, None, 1),
            ("aluno_id", "INTEGER", 1, None, 0),
            ("titulo", "TEXT", 1, None, 0),
            ("descricao", "TEXT", 1, None, 0),
            ("categoria", "TEXT", 1, "'Bug na plataforma'", 0),
            ("screenshot_filename", "TEXT", 0, None, 0),
            ("status", "TEXT", 1, "'Novo'", 0),
            ("criado_em", "TEXT", 1, "datetime('now')", 0),
            ("atualizado_em", "TEXT", 1, "datetime('now')", 0),
            ("admin_id", "INTEGER", 0, None, 0),
        ]

        table_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'reportes'"
        ).fetchone()[0]
        assert "CHECK(status IN ('Novo', 'Em análise', 'Resolvido'))" in table_sql

        foreign_keys = conn.execute("PRAGMA foreign_key_list(reportes)").fetchall()
        assert {
            (row[2], row[3], row[4], row[5], row[6]) for row in foreign_keys
        } == {
            ("alunos", "aluno_id", "id", "CASCADE", "CASCADE"),
            ("usuarios", "admin_id", "id", "CASCADE", "SET NULL"),
        }

        indexes = conn.execute("PRAGMA index_list(reportes)").fetchall()
        assert {row[1] for row in indexes} == {
            "idx_reportes_aluno_id",
            "idx_reportes_status",
            "idx_reportes_criado_em",
        }
        assert second_schema == first_schema
    finally:
        conn.close()


def test_reportes_helper_preserves_caller_owned_transaction():
    conn = _new_reportes_connection()
    try:
        conn.execute("BEGIN")
        assert conn.in_transaction

        db_maintenance.ensure_reportes_table(conn)

        assert conn.in_transaction
        conn.rollback()
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'reportes'"
        ).fetchone() is None
    finally:
        conn.close()


def test_init_db_registers_schema_version():
    with main.app.app_context():
        main.init_db()
        conn = main.get_db_connection()
        schema_version = conn.execute("PRAGMA user_version").fetchone()[0]
        migration = conn.execute(
            "SELECT version, name FROM schema_migrations ORDER BY version DESC LIMIT 1"
        ).fetchone()

    assert schema_version == db_maintenance.SCHEMA_VERSION
    assert migration is not None
    assert migration["version"] == db_maintenance.SCHEMA_VERSION
    assert migration["name"] == "baseline_schema_management"