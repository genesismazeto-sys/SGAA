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

BASELINE_ENSURE_USUARIO_PROFILE_SCHEMA_SOURCE = '''
def ensure_usuario_profile_schema(conn) -> None:
    usuarios_cols = [row["name"] for row in conn.execute("PRAGMA table_info(usuarios)").fetchall()]
    if "foto_perfil" not in usuarios_cols:
        try:
            conn.execute("ALTER TABLE usuarios ADD COLUMN foto_perfil TEXT")
        except sqlite3.OperationalError:
            pass

    alunos_cols = [row["name"] for row in conn.execute("PRAGMA table_info(alunos)").fetchall()]
    if "foto_perfil" not in alunos_cols:
        try:
            conn.execute("ALTER TABLE alunos ADD COLUMN foto_perfil TEXT")
        except sqlite3.OperationalError:
            pass
    if "turma_id" not in alunos_cols:
        try:
            conn.execute("ALTER TABLE alunos ADD COLUMN turma_id INTEGER")
        except sqlite3.OperationalError:
            pass
'''

EXPECTED_DB_LAZY_KEYS_AFTER_PROFILE_EXTRACTION = {
    "ensure_requisicao_alert_receipts_table",
    "ensure_atividades_schema_current",
    "ensure_atividade_versioning_schema",
    "ensure_matriz_atividade_links_table",
    "ensure_matrizes_atividades_table",
    "ensure_usuario_access_schema",
    "ensure_backup_settings_schema",
    "get_preferred_matriz_for_curso",
    "logger",
}

EXPECTED_ALUNO_LAZY_KEYS_AFTER_PROFILE_EXTRACTION = {
    "ensure_admin_arquivos_table",
    "get_admin_arquivo",
    "get_effective_matriz_for_turma",
    "get_student_request_update_alert",
    "list_active_admin_alertas",
    "mark_student_request_updates_seen",
    "maybe_run_versioned_resolver_shadow_read",
    "maybe_write_versioned_requisicao_snapshot",
}


def _function_body_ast(function):
    node = ast.parse(textwrap.dedent(inspect.getsource(function))).body[0]
    assert isinstance(node, ast.FunctionDef)
    return ast.dump(ast.Module(body=node.body, type_ignores=[]), include_attributes=False)


def _baseline_function_body_ast():
    node = ast.parse(textwrap.dedent(BASELINE_ENSURE_REPORTES_TABLE_SOURCE)).body[0]
    assert isinstance(node, ast.FunctionDef)
    return ast.dump(ast.Module(body=node.body, type_ignores=[]), include_attributes=False)


def _function_ast(function):
    node = ast.parse(textwrap.dedent(inspect.getsource(function))).body[0]
    assert isinstance(node, ast.FunctionDef)
    return ast.dump(node, include_attributes=False)


def _baseline_function_ast(source):
    node = ast.parse(textwrap.dedent(source)).body[0]
    assert isinstance(node, ast.FunctionDef)
    return ast.dump(node, include_attributes=False)


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


def _new_profile_connection():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def _column_names(conn, table):
    return [row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]


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


def test_usuario_profile_helper_is_ast_identical_to_accepted_baseline():
    assert _function_ast(db_maintenance.ensure_usuario_profile_schema) == _baseline_function_ast(
        BASELINE_ENSURE_USUARIO_PROFILE_SCHEMA_SOURCE
    )


def test_usuario_profile_helper_owner_exports_and_direct_consumers():
    assert main.ensure_usuario_profile_schema is db_maintenance.ensure_usuario_profile_schema
    assert app_db.ensure_usuario_profile_schema is db_maintenance.ensure_usuario_profile_schema
    assert aluno_views.ensure_usuario_profile_schema is db_maintenance.ensure_usuario_profile_schema

    assert _lazy_return_keys(app_db._get_main_db_helpers) == EXPECTED_DB_LAZY_KEYS_AFTER_PROFILE_EXTRACTION
    assert _lazy_return_keys(aluno_views._get_main_helpers) == EXPECTED_ALUNO_LAZY_KEYS_AFTER_PROFILE_EXTRACTION
    assert 'helpers["ensure_usuario_profile_schema"]' not in inspect.getsource(app_db._init_db_impl)
    assert 'helpers["ensure_usuario_profile_schema"]' not in inspect.getsource(aluno_views.aluno_meus_dados)
    assert "_get_main_helpers()" not in inspect.getsource(aluno_views.aluno_meus_dados)


def test_db_maintenance_profile_helper_import_does_not_import_main():
    code = (
        "import importlib, sys; "
        "assert 'main' not in sys.modules; "
        "module = importlib.import_module('app.db_maintenance'); "
        "assert module.ensure_usuario_profile_schema; "
        "assert 'main' not in sys.modules"
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", code],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    assert result.returncode == 0, result.stderr


def test_usuario_profile_schema_with_no_tables_is_a_noop():
    conn = _new_profile_connection()
    try:
        db_maintenance.ensure_usuario_profile_schema(conn)
        assert conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall() == []
    finally:
        conn.close()


def test_usuario_profile_schema_with_only_usuarios_updates_only_existing_table():
    conn = _new_profile_connection()
    try:
        conn.execute("CREATE TABLE usuarios (id INTEGER PRIMARY KEY)")
        db_maintenance.ensure_usuario_profile_schema(conn)
        assert _column_names(conn, "usuarios") == ["id", "foto_perfil"]
        assert _column_names(conn, "alunos") == []
    finally:
        conn.close()


def test_usuario_profile_schema_adds_all_missing_columns_and_is_idempotent():
    conn = _new_profile_connection()
    try:
        conn.execute("CREATE TABLE usuarios (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE alunos (id INTEGER PRIMARY KEY)")

        db_maintenance.ensure_usuario_profile_schema(conn)
        first_schema = conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()
        db_maintenance.ensure_usuario_profile_schema(conn)
        second_schema = conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()

        assert _column_names(conn, "usuarios") == ["id", "foto_perfil"]
        assert _column_names(conn, "alunos") == ["id", "foto_perfil", "turma_id"]
        assert [(row["name"], row["sql"]) for row in second_schema] == [
            (row["name"], row["sql"]) for row in first_schema
        ]
    finally:
        conn.close()


def test_usuario_profile_schema_preserves_existing_columns_exactly():
    conn = _new_profile_connection()
    try:
        conn.execute("CREATE TABLE usuarios (id INTEGER PRIMARY KEY, foto_perfil TEXT)")
        conn.execute(
            "CREATE TABLE alunos (id INTEGER PRIMARY KEY, foto_perfil TEXT, turma_id INTEGER)"
        )
        before = conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()

        db_maintenance.ensure_usuario_profile_schema(conn)

        after = conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()
        assert [(row["name"], row["sql"]) for row in after] == [
            (row["name"], row["sql"]) for row in before
        ]
    finally:
        conn.close()


def test_usuario_profile_helper_preserves_caller_owned_transaction():
    conn = _new_profile_connection()
    try:
        conn.execute("CREATE TABLE usuarios (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE alunos (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.execute("BEGIN")
        assert conn.in_transaction

        db_maintenance.ensure_usuario_profile_schema(conn)

        assert conn.in_transaction
        conn.rollback()
        assert _column_names(conn, "usuarios") == ["id"]
        assert _column_names(conn, "alunos") == ["id"]
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