import ast
import inspect
import os
import sqlite3
import subprocess
import sys
import textwrap

import pytest


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

BASELINE_ENSURE_REQUISICAO_ALERT_RECEIPTS_TABLE_SOURCE = '''
def ensure_requisicao_alert_receipts_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS requisicao_alerta_receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            requisicao_id INTEGER NOT NULL,
            usuario_id INTEGER NOT NULL,
            alert_kind TEXT NOT NULL,
            seen_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (requisicao_id) REFERENCES requisicoes(id) ON DELETE CASCADE ON UPDATE CASCADE,
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE ON UPDATE CASCADE,
            UNIQUE(requisicao_id, usuario_id, alert_kind)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_req_alert_receipts_user_kind ON requisicao_alerta_receipts(usuario_id, alert_kind)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_req_alert_receipts_req ON requisicao_alerta_receipts(requisicao_id)"
    )
'''

EXPECTED_DB_LAZY_KEYS_AFTER_MATRIX_EXTRACTION = {
    "ensure_atividades_schema_current",
    "ensure_atividade_versioning_schema",
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


def _module_function_definition_counts(module, function_names):
    tree = ast.parse(inspect.getsource(module))
    return {
        name: sum(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
            for node in tree.body
        )
        for name in function_names
    }


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


def _new_alert_receipts_connection(*, with_parents=True):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if with_parents:
        conn.execute("CREATE TABLE usuarios (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE requisicoes (id INTEGER PRIMARY KEY)")
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

    assert "ensure_usuario_profile_schema" not in _lazy_return_keys(app_db._get_main_db_helpers)
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


def test_alert_receipts_helper_is_ast_identical_to_accepted_baseline():
    assert _function_ast(
        db_maintenance.ensure_requisicao_alert_receipts_table
    ) == _baseline_function_ast(BASELINE_ENSURE_REQUISICAO_ALERT_RECEIPTS_TABLE_SOURCE)


def test_alert_receipts_helper_owner_export_and_direct_db_consumer():
    assert (
        main.ensure_requisicao_alert_receipts_table
        is db_maintenance.ensure_requisicao_alert_receipts_table
    )
    assert (
        app_db.ensure_requisicao_alert_receipts_table
        is db_maintenance.ensure_requisicao_alert_receipts_table
    )
    assert "ensure_requisicao_alert_receipts_table" not in _lazy_return_keys(
        app_db._get_main_db_helpers
    )
    init_source = inspect.getsource(app_db._init_db_impl)
    assert 'helpers["ensure_requisicao_alert_receipts_table"]' not in init_source
    assert init_source.count("ensure_requisicao_alert_receipts_table(conn)") == 1


def test_db_maintenance_alert_receipts_import_does_not_import_main():
    code = (
        "import importlib, sys; "
        "assert 'main' not in sys.modules; "
        "module = importlib.import_module('app.db_maintenance'); "
        "assert module.ensure_requisicao_alert_receipts_table; "
        "assert 'main' not in sys.modules"
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", code],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    assert result.returncode == 0, result.stderr


def test_alert_receipts_schema_can_be_created_before_parent_tables_exist():
    conn = _new_alert_receipts_connection(with_parents=False)
    try:
        db_maintenance.ensure_requisicao_alert_receipts_table(conn)
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' "
            "AND name = 'requisicao_alerta_receipts'"
        ).fetchone() is not None
    finally:
        conn.close()


def test_alert_receipts_schema_is_exact_and_idempotent():
    conn = _new_alert_receipts_connection()
    try:
        db_maintenance.ensure_requisicao_alert_receipts_table(conn)
        first_schema = conn.execute(
            "SELECT type, name, sql FROM sqlite_master "
            "WHERE tbl_name = 'requisicao_alerta_receipts' ORDER BY type, name"
        ).fetchall()
        db_maintenance.ensure_requisicao_alert_receipts_table(conn)
        second_schema = conn.execute(
            "SELECT type, name, sql FROM sqlite_master "
            "WHERE tbl_name = 'requisicao_alerta_receipts' ORDER BY type, name"
        ).fetchall()

        columns = conn.execute("PRAGMA table_info(requisicao_alerta_receipts)").fetchall()
        assert [(row["name"], row["type"], row["notnull"], row["dflt_value"], row["pk"]) for row in columns] == [
            ("id", "INTEGER", 0, None, 1),
            ("requisicao_id", "INTEGER", 1, None, 0),
            ("usuario_id", "INTEGER", 1, None, 0),
            ("alert_kind", "TEXT", 1, None, 0),
            ("seen_at", "TEXT", 1, "datetime('now')", 0),
        ]

        foreign_keys = conn.execute(
            "PRAGMA foreign_key_list(requisicao_alerta_receipts)"
        ).fetchall()
        assert {
            (row["table"], row["from"], row["to"], row["on_update"], row["on_delete"])
            for row in foreign_keys
        } == {
            ("requisicoes", "requisicao_id", "id", "CASCADE", "CASCADE"),
            ("usuarios", "usuario_id", "id", "CASCADE", "CASCADE"),
        }

        indexes = conn.execute("PRAGMA index_list(requisicao_alerta_receipts)").fetchall()
        named_indexes = {row["name"] for row in indexes if not row["name"].startswith("sqlite_autoindex")}
        assert named_indexes == {
            "idx_req_alert_receipts_user_kind",
            "idx_req_alert_receipts_req",
        }
        unique_indexes = [row for row in indexes if row["unique"]]
        assert len(unique_indexes) == 1
        unique_columns = conn.execute(
            f"PRAGMA index_info({unique_indexes[0]['name']})"
        ).fetchall()
        assert [row["name"] for row in unique_columns] == [
            "requisicao_id",
            "usuario_id",
            "alert_kind",
        ]
        assert second_schema == first_schema
    finally:
        conn.close()


def test_alert_receipts_rejects_duplicate_composite_key():
    conn = _new_alert_receipts_connection()
    try:
        db_maintenance.ensure_requisicao_alert_receipts_table(conn)
        conn.execute("INSERT INTO usuarios (id) VALUES (1)")
        conn.execute("INSERT INTO requisicoes (id) VALUES (1)")
        values = (1, 1, "admin_new_request")
        conn.execute(
            "INSERT INTO requisicao_alerta_receipts "
            "(requisicao_id, usuario_id, alert_kind) VALUES (?, ?, ?)",
            values,
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO requisicao_alerta_receipts "
                "(requisicao_id, usuario_id, alert_kind) VALUES (?, ?, ?)",
                values,
            )
    finally:
        conn.close()


def test_alert_receipts_cascade_on_requisition_and_user_deletion():
    conn = _new_alert_receipts_connection()
    try:
        db_maintenance.ensure_requisicao_alert_receipts_table(conn)
        conn.executemany("INSERT INTO usuarios (id) VALUES (?)", [(1,), (2,)])
        conn.executemany("INSERT INTO requisicoes (id) VALUES (?)", [(1,), (2,)])
        conn.executemany(
            "INSERT INTO requisicao_alerta_receipts "
            "(requisicao_id, usuario_id, alert_kind) VALUES (?, ?, ?)",
            [(1, 1, "admin_new_request"), (2, 2, "coordinator_new_request")],
        )

        conn.execute("DELETE FROM requisicoes WHERE id = 1")
        assert conn.execute(
            "SELECT COUNT(*) FROM requisicao_alerta_receipts WHERE requisicao_id = 1"
        ).fetchone()[0] == 0
        conn.execute("DELETE FROM usuarios WHERE id = 2")
        assert conn.execute(
            "SELECT COUNT(*) FROM requisicao_alerta_receipts WHERE usuario_id = 2"
        ).fetchone()[0] == 0
    finally:
        conn.close()


def test_alert_receipts_helper_preserves_caller_owned_transaction():
    conn = _new_alert_receipts_connection()
    try:
        conn.commit()
        conn.execute("BEGIN")
        assert conn.in_transaction

        db_maintenance.ensure_requisicao_alert_receipts_table(conn)

        assert conn.in_transaction
        conn.rollback()
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' "
            "AND name = 'requisicao_alerta_receipts'"
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


BASELINE_ENSURE_MATRIZES_ATIVIDADES_TABLE_SOURCE = '''
def ensure_matrizes_atividades_table(conn) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS matrizes_atividades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            curso_id INTEGER NOT NULL,
            nome TEXT NOT NULL,
            versao TEXT NOT NULL,
            descricao TEXT,
            status TEXT NOT NULL DEFAULT 'rascunho',
            data_inicio_vigencia TEXT,
            data_fim_vigencia TEXT,
            horas_aac_obrigatorias INTEGER NOT NULL DEFAULT {DEFAULT_CURSO_TOTAL_HORAS_AAC},
            horas_extensao_obrigatorias INTEGER NOT NULL DEFAULT {DEFAULT_CURSO_TOTAL_HORAS_AEU},
            matriz_origem_id INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(curso_id) REFERENCES cursos(id),
            FOREIGN KEY(matriz_origem_id) REFERENCES matrizes_atividades(id)
        )
        """
    )
    try:
        cols = [row["name"] for row in conn.execute("PRAGMA table_info(matrizes_atividades)").fetchall()]
        if "horas_aac_obrigatorias" not in cols:
            conn.execute(
                f"ALTER TABLE matrizes_atividades ADD COLUMN horas_aac_obrigatorias INTEGER NOT NULL DEFAULT {DEFAULT_CURSO_TOTAL_HORAS_AAC}"
            )
        if "horas_extensao_obrigatorias" not in cols:
            conn.execute(
                f"ALTER TABLE matrizes_atividades ADD COLUMN horas_extensao_obrigatorias INTEGER NOT NULL DEFAULT {DEFAULT_CURSO_TOTAL_HORAS_AEU}"
            )
        if "matriz_origem_id" not in cols:
            conn.execute("ALTER TABLE matrizes_atividades ADD COLUMN matriz_origem_id INTEGER")
        if "created_at" not in cols:
            conn.execute("ALTER TABLE matrizes_atividades ADD COLUMN created_at TEXT")
            conn.execute("UPDATE matrizes_atividades SET created_at = datetime('now') WHERE created_at IS NULL OR created_at = ''")
    except sqlite3.OperationalError:
        pass
    conn.execute(
        "UPDATE matrizes_atividades SET horas_aac_obrigatorias = ? WHERE horas_aac_obrigatorias IS NULL OR horas_aac_obrigatorias < 0",
        (DEFAULT_CURSO_TOTAL_HORAS_AAC,),
    )
    conn.execute(
        "UPDATE matrizes_atividades SET horas_extensao_obrigatorias = ? WHERE horas_extensao_obrigatorias IS NULL OR horas_extensao_obrigatorias < 0",
        (DEFAULT_CURSO_TOTAL_HORAS_AEU,),
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_matrizes_curso ON matrizes_atividades(curso_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_matrizes_status ON matrizes_atividades(status)")
'''

BASELINE_ENSURE_MATRIZ_ATIVIDADE_LINKS_TABLE_SOURCE = '''
def ensure_matriz_atividade_links_table(conn) -> None:
    ensure_matrizes_atividades_table(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS matrizes_atividades_itens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            matriz_id INTEGER NOT NULL,
            atividade_id INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(matriz_id) REFERENCES matrizes_atividades(id) ON DELETE CASCADE,
            FOREIGN KEY(atividade_id) REFERENCES atividades(id) ON DELETE CASCADE,
            UNIQUE(matriz_id, atividade_id)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_matriz_itens_matriz ON matrizes_atividades_itens(matriz_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_matriz_itens_atividade ON matrizes_atividades_itens(atividade_id)")
'''


def _new_matriz_connection(*, with_parents=True):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if with_parents:
        conn.execute("CREATE TABLE cursos (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE atividades (id INTEGER PRIMARY KEY)")
    return conn


def test_matrizes_helper_is_ast_identical_to_accepted_baseline():
    assert _function_ast(
        db_maintenance.ensure_matrizes_atividades_table
    ) == _baseline_function_ast(BASELINE_ENSURE_MATRIZES_ATIVIDADES_TABLE_SOURCE)


def test_matriz_atividade_links_helper_is_ast_identical_to_accepted_baseline():
    assert _function_ast(
        db_maintenance.ensure_matriz_atividade_links_table
    ) == _baseline_function_ast(BASELINE_ENSURE_MATRIZ_ATIVIDADE_LINKS_TABLE_SOURCE)


def test_matrizes_helper_owner_exports_and_direct_consumers():
    function_names = {
        "ensure_matrizes_atividades_table",
        "ensure_matriz_atividade_links_table",
    }
    assert _module_function_definition_counts(db_maintenance, function_names) == {
        "ensure_matrizes_atividades_table": 1,
        "ensure_matriz_atividade_links_table": 1,
    }
    assert _module_function_definition_counts(main, function_names) == {
        "ensure_matrizes_atividades_table": 0,
        "ensure_matriz_atividade_links_table": 0,
    }
    assert _module_function_definition_counts(app_db, function_names) == {
        "ensure_matrizes_atividades_table": 0,
        "ensure_matriz_atividade_links_table": 0,
    }
    assert main.ensure_matrizes_atividades_table is db_maintenance.ensure_matrizes_atividades_table
    assert app_db.ensure_matrizes_atividades_table is db_maintenance.ensure_matrizes_atividades_table
    assert "ensure_matrizes_atividades_table" not in _lazy_return_keys(app_db._get_main_db_helpers)
    init_source = inspect.getsource(app_db._init_db_impl)
    assert 'helpers["ensure_matrizes_atividades_table"]' not in init_source
    assert init_source.count("ensure_matrizes_atividades_table(conn)") == 1


def test_matriz_atividade_links_helper_owner_exports_and_direct_consumers():
    assert main.ensure_matriz_atividade_links_table is db_maintenance.ensure_matriz_atividade_links_table
    assert app_db.ensure_matriz_atividade_links_table is db_maintenance.ensure_matriz_atividade_links_table
    assert (
        _lazy_return_keys(app_db._get_main_db_helpers)
        == EXPECTED_DB_LAZY_KEYS_AFTER_MATRIX_EXTRACTION
    )
    init_source = inspect.getsource(app_db._init_db_impl)
    assert 'helpers["ensure_matriz_atividade_links_table"]' not in init_source
    assert init_source.count("ensure_matriz_atividade_links_table(conn)") == 1
    assert init_source.count("ensure_matrizes_atividades_table(conn)") == 1
    assert init_source.count("ensure_atividade_versioning_schema(conn)") == 1
    lines = [l.strip() for l in init_source.splitlines()]
    idx_matriz = lines.index("ensure_matrizes_atividades_table(conn)")
    idx_links = lines.index("ensure_matriz_atividade_links_table(conn)")
    idx_vers = lines.index("ensure_atividade_versioning_schema(conn)")
    assert idx_matriz < idx_links < idx_vers


def test_db_maintenance_matrizes_import_does_not_import_main():
    code = (
        "import importlib, sys; "
        "assert 'main' not in sys.modules; "
        "module = importlib.import_module('app.db_maintenance'); "
        "assert module.ensure_matrizes_atividades_table; "
        "assert 'main' not in sys.modules"
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", code],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    assert result.returncode == 0, result.stderr


def test_db_maintenance_matriz_links_import_does_not_import_main():
    code = (
        "import importlib, sys; "
        "assert 'main' not in sys.modules; "
        "module = importlib.import_module('app.db_maintenance'); "
        "assert module.ensure_matriz_atividade_links_table; "
        "assert 'main' not in sys.modules"
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", code],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    assert result.returncode == 0, result.stderr


def test_matrizes_schema_is_exact_and_idempotent():
    conn = _new_matriz_connection()
    try:
        db_maintenance.ensure_matrizes_atividades_table(conn)
        first_schema = conn.execute(
            "SELECT type, name, sql FROM sqlite_master "
            "WHERE tbl_name = 'matrizes_atividades' ORDER BY type, name"
        ).fetchall()
        db_maintenance.ensure_matrizes_atividades_table(conn)
        second_schema = conn.execute(
            "SELECT type, name, sql FROM sqlite_master "
            "WHERE tbl_name = 'matrizes_atividades' ORDER BY type, name"
        ).fetchall()

        columns = conn.execute("PRAGMA table_info(matrizes_atividades)").fetchall()
        assert [(row["name"], row["type"], row["notnull"], row["dflt_value"], row["pk"]) for row in columns] == [
            ("id", "INTEGER", 0, None, 1),
            ("curso_id", "INTEGER", 1, None, 0),
            ("nome", "TEXT", 1, None, 0),
            ("versao", "TEXT", 1, None, 0),
            ("descricao", "TEXT", 0, None, 0),
            ("status", "TEXT", 1, "'rascunho'", 0),
            ("data_inicio_vigencia", "TEXT", 0, None, 0),
            ("data_fim_vigencia", "TEXT", 0, None, 0),
            ("horas_aac_obrigatorias", "INTEGER", 1, "160", 0),
            ("horas_extensao_obrigatorias", "INTEGER", 1, "80", 0),
            ("matriz_origem_id", "INTEGER", 0, None, 0),
            ("created_at", "TEXT", 1, "datetime('now')", 0),
        ]

        foreign_keys = conn.execute("PRAGMA foreign_key_list(matrizes_atividades)").fetchall()
        assert {
            (row["table"], row["from"], row["to"], row["on_update"], row["on_delete"])
            for row in foreign_keys
        } == {
            ("cursos", "curso_id", "id", "NO ACTION", "NO ACTION"),
            ("matrizes_atividades", "matriz_origem_id", "id", "NO ACTION", "NO ACTION"),
        }

        indexes = conn.execute("PRAGMA index_list(matrizes_atividades)").fetchall()
        named = {row["name"] for row in indexes if not row["name"].startswith("sqlite_autoindex")}
        assert named == {"idx_matrizes_curso", "idx_matrizes_status"}

        assert second_schema == first_schema
    finally:
        conn.close()


def test_matrizes_partial_legacy_schema_conditional_additions():
    conn = _new_matriz_connection()
    try:
        conn.execute(
            """
            CREATE TABLE matrizes_atividades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                curso_id INTEGER NOT NULL,
                nome TEXT NOT NULL,
                versao TEXT NOT NULL,
                descricao TEXT,
                status TEXT NOT NULL DEFAULT 'rascunho',
                data_inicio_vigencia TEXT,
                data_fim_vigencia TEXT
            )
            """
        )
        db_maintenance.ensure_matrizes_atividades_table(conn)
        cols_list = _column_names(conn, "matrizes_atividades")
        assert "horas_aac_obrigatorias" in cols_list
        assert "horas_extensao_obrigatorias" in cols_list
        assert "matriz_origem_id" in cols_list
        assert "created_at" in cols_list
    finally:
        conn.close()


def test_matrizes_created_at_backfill():
    conn = _new_matriz_connection()
    try:
        conn.execute(
            """
            CREATE TABLE matrizes_atividades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                curso_id INTEGER NOT NULL,
                nome TEXT NOT NULL,
                versao TEXT NOT NULL,
                descricao TEXT,
                status TEXT NOT NULL DEFAULT 'rascunho',
                data_inicio_vigencia TEXT,
                data_fim_vigencia TEXT,
                horas_aac_obrigatorias INTEGER NOT NULL DEFAULT 160,
                horas_extensao_obrigatorias INTEGER NOT NULL DEFAULT 80
            )
            """
        )
        conn.execute(
            "INSERT INTO matrizes_atividades (curso_id, nome, versao) VALUES (1, 'Test', '1.0')"
        )
        assert "created_at" not in _column_names(conn, "matrizes_atividades")

        db_maintenance.ensure_matrizes_atividades_table(conn)
        assert "created_at" in _column_names(conn, "matrizes_atividades")
        row = conn.execute("SELECT created_at FROM matrizes_atividades").fetchone()
        assert row["created_at"] is not None
    finally:
        conn.close()


def test_matrizes_null_and_negative_aac_aeu_normalization():
    conn = _new_matriz_connection()
    try:
        conn.execute(
            """
            CREATE TABLE matrizes_atividades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                curso_id INTEGER NOT NULL,
                nome TEXT NOT NULL,
                versao TEXT NOT NULL,
                descricao TEXT,
                status TEXT NOT NULL DEFAULT 'rascunho',
                data_inicio_vigencia TEXT,
                data_fim_vigencia TEXT,
                horas_aac_obrigatorias INTEGER,
                horas_extensao_obrigatorias INTEGER,
                matriz_origem_id INTEGER,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            "INSERT INTO matrizes_atividades (curso_id, nome, versao, horas_aac_obrigatorias, horas_extensao_obrigatorias) VALUES (?, ?, ?, ?, ?)",
            (1, "Test", "1.0", None, -10),
        )
        conn.execute(
            "INSERT INTO matrizes_atividades (curso_id, nome, versao, horas_aac_obrigatorias, horas_extensao_obrigatorias) VALUES (?, ?, ?, ?, ?)",
            (1, "Test2", "2.0", -5, None),
        )
        db_maintenance.ensure_matrizes_atividades_table(conn)
        rows = conn.execute(
            "SELECT horas_aac_obrigatorias, horas_extensao_obrigatorias FROM matrizes_atividades ORDER BY id"
        ).fetchall()
        assert rows[0]["horas_aac_obrigatorias"] == 160
        assert rows[0]["horas_extensao_obrigatorias"] == 80
        assert rows[1]["horas_aac_obrigatorias"] == 160
        assert rows[1]["horas_extensao_obrigatorias"] == 80
    finally:
        conn.close()


def test_matrizes_preserves_zero_and_positive_valid_values():
    conn = _new_matriz_connection()
    try:
        conn.execute(
            """
            CREATE TABLE matrizes_atividades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                curso_id INTEGER NOT NULL,
                nome TEXT NOT NULL,
                versao TEXT NOT NULL,
                descricao TEXT,
                status TEXT NOT NULL DEFAULT 'rascunho',
                data_inicio_vigencia TEXT,
                data_fim_vigencia TEXT,
                horas_aac_obrigatorias INTEGER,
                horas_extensao_obrigatorias INTEGER,
                matriz_origem_id INTEGER,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            "INSERT INTO matrizes_atividades (curso_id, nome, versao, horas_aac_obrigatorias, horas_extensao_obrigatorias) VALUES (?, ?, ?, ?, ?)",
            (1, "Test", "1.0", 0, 200),
        )
        conn.execute(
            "INSERT INTO matrizes_atividades (curso_id, nome, versao, horas_aac_obrigatorias, horas_extensao_obrigatorias) VALUES (?, ?, ?, ?, ?)",
            (1, "Test2", "2.0", 100, 0),
        )
        db_maintenance.ensure_matrizes_atividades_table(conn)
        rows = conn.execute(
            "SELECT horas_aac_obrigatorias, horas_extensao_obrigatorias FROM matrizes_atividades ORDER BY id"
        ).fetchall()
        assert rows[0]["horas_aac_obrigatorias"] == 0
        assert rows[0]["horas_extensao_obrigatorias"] == 200
        assert rows[1]["horas_aac_obrigatorias"] == 100
        assert rows[1]["horas_extensao_obrigatorias"] == 0
    finally:
        conn.close()


def test_matrizes_helper_preserves_caller_owned_transaction():
    conn = _new_matriz_connection()
    try:
        conn.execute("BEGIN")
        assert conn.in_transaction

        db_maintenance.ensure_matrizes_atividades_table(conn)

        assert conn.in_transaction
        conn.rollback()
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'matrizes_atividades'"
        ).fetchone() is None
    finally:
        conn.close()


def test_matriz_atividade_links_schema_is_exact_and_idempotent():
    conn = _new_matriz_connection()
    try:
        db_maintenance.ensure_matriz_atividade_links_table(conn)
        first_schema = conn.execute(
            "SELECT type, name, sql FROM sqlite_master "
            "WHERE tbl_name = 'matrizes_atividades_itens' ORDER BY type, name"
        ).fetchall()
        db_maintenance.ensure_matriz_atividade_links_table(conn)
        second_schema = conn.execute(
            "SELECT type, name, sql FROM sqlite_master "
            "WHERE tbl_name = 'matrizes_atividades_itens' ORDER BY type, name"
        ).fetchall()

        columns = conn.execute("PRAGMA table_info(matrizes_atividades_itens)").fetchall()
        assert [(row["name"], row["type"], row["notnull"], row["dflt_value"], row["pk"]) for row in columns] == [
            ("id", "INTEGER", 0, None, 1),
            ("matriz_id", "INTEGER", 1, None, 0),
            ("atividade_id", "INTEGER", 1, None, 0),
            ("created_at", "TEXT", 1, "datetime('now')", 0),
        ]

        foreign_keys = conn.execute(
            "PRAGMA foreign_key_list(matrizes_atividades_itens)"
        ).fetchall()
        assert {
            (row["table"], row["from"], row["to"], row["on_update"], row["on_delete"])
            for row in foreign_keys
        } == {
            ("matrizes_atividades", "matriz_id", "id", "NO ACTION", "CASCADE"),
            ("atividades", "atividade_id", "id", "NO ACTION", "CASCADE"),
        }

        indexes = conn.execute("PRAGMA index_list(matrizes_atividades_itens)").fetchall()
        named_indexes = {row["name"] for row in indexes if not row["name"].startswith("sqlite_autoindex")}
        assert named_indexes == {
            "idx_matriz_itens_matriz",
            "idx_matriz_itens_atividade",
        }
        unique_indexes = [row for row in indexes if row["unique"]]
        assert len(unique_indexes) == 1
        unique_columns = conn.execute(
            f"PRAGMA index_info({unique_indexes[0]['name']})"
        ).fetchall()
        assert [row["name"] for row in unique_columns] == ["matriz_id", "atividade_id"]

        assert second_schema == first_schema
    finally:
        conn.close()


def test_matriz_atividade_links_duplicate_rejection():
    conn = _new_matriz_connection()
    try:
        db_maintenance.ensure_matriz_atividade_links_table(conn)
        conn.execute("INSERT INTO cursos (id) VALUES (1)")
        conn.execute("INSERT INTO atividades (id) VALUES (1)")
        conn.execute("INSERT INTO matrizes_atividades (curso_id, nome, versao) VALUES (1, 'M1', '1.0')")
        values = (1, 1)
        conn.execute(
            "INSERT INTO matrizes_atividades_itens (matriz_id, atividade_id) VALUES (?, ?)",
            values,
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO matrizes_atividades_itens (matriz_id, atividade_id) VALUES (?, ?)",
                values,
            )
    finally:
        conn.close()


def test_matriz_atividade_links_delete_cascades():
    conn = _new_matriz_connection()
    try:
        db_maintenance.ensure_matriz_atividade_links_table(conn)
        conn.execute("INSERT INTO cursos (id) VALUES (1)")
        conn.execute("INSERT INTO atividades (id) VALUES (1)")
        conn.execute("INSERT INTO atividades (id) VALUES (2)")
        conn.executemany(
            "INSERT INTO matrizes_atividades (curso_id, nome, versao) VALUES (?, ?, ?)",
            [(1, "M1", "1.0"), (1, "M2", "2.0")],
        )
        conn.executemany(
            "INSERT INTO matrizes_atividades_itens (matriz_id, atividade_id) VALUES (?, ?)",
            [(1, 1), (2, 2)],
        )

        conn.execute("DELETE FROM matrizes_atividades WHERE id = 1")
        assert conn.execute(
            "SELECT COUNT(*) FROM matrizes_atividades_itens WHERE matriz_id = 1"
        ).fetchone()[0] == 0
        conn.execute("DELETE FROM atividades WHERE id = 2")
        assert conn.execute(
            "SELECT COUNT(*) FROM matrizes_atividades_itens WHERE atividade_id = 2"
        ).fetchone()[0] == 0
    finally:
        conn.close()


def test_matriz_atividade_links_nested_call_creates_matrizes_table():
    conn = _new_matriz_connection(with_parents=True)
    try:
        db_maintenance.ensure_matriz_atividade_links_table(conn)
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'matrizes_atividades'"
        ).fetchone() is not None
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'matrizes_atividades_itens'"
        ).fetchone() is not None
    finally:
        conn.close()


def test_matriz_atividade_links_preserves_caller_owned_transaction():
    conn = _new_matriz_connection()
    try:
        conn.commit()
        conn.execute("BEGIN")
        assert conn.in_transaction

        db_maintenance.ensure_matriz_atividade_links_table(conn)

        assert conn.in_transaction
        conn.rollback()
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' "
            "AND name = 'matrizes_atividades_itens'"
        ).fetchone() is None
    finally:
        conn.close()