import ast
import inspect
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_COMMIT = "d1947b0c11506045b8d52bd235bc7381a2ca22c9"
MAIN_PATH = PROJECT_ROOT / "main.py"
APP_DB_PATH = PROJECT_ROOT / "app" / "db.py"
DB_MAINTENANCE_PATH = PROJECT_ROOT / "app" / "db_maintenance.py"

LEAF_TABLE_HELPER = "ensure_atividade_versioning_leaf_tables"
LEAF_TRIGGER_HELPER = "ensure_atividade_versioning_leaf_triggers"
LEAF_INDEX_HELPER = "ensure_atividade_versioning_leaf_indexes"
LEAF_HELPERS = (LEAF_TABLE_HELPER, LEAF_TRIGGER_HELPER, LEAF_INDEX_HELPER)
LEAF_TABLES = (
    "atividade_transicao",
    "matriz_norma",
    "matriz_atividade_versao_item",
    "atividade_legacy_map",
)
LEAF_TRIGGERS = (
    "trg_atividade_transicao_aac_para_aeu_insert",
    "trg_atividade_transicao_aac_para_aeu_update",
)
LEAF_INDEXES = (
    ("idx_atividade_transicao_from", "atividade_transicao", ("from_atividade_versao_id",)),
    ("idx_atividade_transicao_to", "atividade_transicao", ("to_atividade_versao_id",)),
    ("idx_atividade_transicao_tipo", "atividade_transicao", ("tipo_transicao",)),
    ("idx_matriz_norma_matriz", "matriz_norma", ("matriz_id",)),
    ("idx_matriz_norma_norma", "matriz_norma", ("norma_id",)),
    (
        "idx_matriz_atividade_versao_item_matriz",
        "matriz_atividade_versao_item",
        ("matriz_id",),
    ),
    (
        "idx_matriz_atividade_versao_item_versao",
        "matriz_atividade_versao_item",
        ("atividade_versao_id",),
    ),
    ("idx_atividade_legacy_map_base", "atividade_legacy_map", ("atividade_base_id",)),
)
LEAF_SQL_MARKERS = {
    LEAF_TABLE_HELPER: tuple(f"CREATE TABLE IF NOT EXISTS {name} " for name in LEAF_TABLES),
    LEAF_TRIGGER_HELPER: tuple(
        f"CREATE TRIGGER IF NOT EXISTS {name} " for name in LEAF_TRIGGERS
    ),
    LEAF_INDEX_HELPER: tuple(
        f"INDEX IF NOT EXISTS {name} " for name, _, _ in LEAF_INDEXES
    ),
}
CORE_FUNCTIONS = (
    "_needs_atividade_versao_migration",
    "_needs_atividade_versao_default_fix",
    "_needs_index_hardening",
    "_recreate_atividade_versao",
    "_migrate_atividade_versao_to_numero_versao",
    "_fix_atividade_versao_default",
)


def _read(path):
    return path.read_text(encoding="utf-8")


def _baseline(path):
    relative = path.relative_to(PROJECT_ROOT).as_posix()
    result = subprocess.run(
        ["git", "show", f"{BASELINE_COMMIT}:{relative}"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def _tree(source):
    return ast.parse(source)


def _function(tree, name):
    matches = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name]
    assert len(matches) == 1, name
    return matches[0]


def _assignment(tree, name):
    matches = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            matches.append(node)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            matches.append(node)
    assert len(matches) == 1, name
    return matches[0]


def _dump(node):
    return ast.dump(node, include_attributes=False)


def _execute_sql(statement):
    if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call):
        return None
    call = statement.value
    if not (
        isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "conn"
        and call.func.attr == "execute"
        and call.args
    ):
        return None
    try:
        value = ast.literal_eval(call.args[0])
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, str) else None


def _normalized_sql(sql):
    return " ".join(sql.split())


def _sql_for_markers(function, markers):
    result = []
    normalized_markers = tuple(_normalized_sql(marker) for marker in markers)
    for statement in function.body:
        sql = _execute_sql(statement)
        if sql is not None:
            normalized = _normalized_sql(sql)
            if any(marker in normalized for marker in normalized_markers):
                result.append(normalized)
    return tuple(result)


def _helper_call(name):
    return ast.Expr(
        value=ast.Call(func=ast.Name(id=name, ctx=ast.Load()), args=[ast.Name(id="conn", ctx=ast.Load())], keywords=[])
    )


def _expected_b8_orchestrator(baseline_function):
    body = []
    inserted = set()
    groups = tuple(LEAF_SQL_MARKERS.items())
    for statement in baseline_function.body:
        sql = _execute_sql(statement)
        matched = None
        if sql is not None:
            normalized = _normalized_sql(sql)
            for helper, markers in groups:
                if any(_normalized_sql(marker) in normalized for marker in markers):
                    matched = helper
                    break
        if matched is None:
            body.append(statement)
        elif matched not in inserted:
            body.append(_helper_call(matched))
            inserted.add(matched)
    assert inserted == set(LEAF_HELPERS)
    return ast.FunctionDef(
        name=baseline_function.name,
        args=baseline_function.args,
        body=body,
        decorator_list=baseline_function.decorator_list,
        returns=baseline_function.returns,
        type_comment=baseline_function.type_comment,
    )


def _definition_count(tree, name):
    return sum(isinstance(node, ast.FunctionDef) and node.name == name for node in tree.body)


def _direct_calls(function):
    calls = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            calls.append(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            calls.append(node.func.attr)
    return calls


def _new_connection():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(
        """
        CREATE TABLE atividades (id INTEGER PRIMARY KEY);
        CREATE TABLE atividade_base (id INTEGER PRIMARY KEY);
        CREATE TABLE norma_atividade (id INTEGER PRIMARY KEY, eixo TEXT NOT NULL);
        CREATE TABLE matrizes_atividades (id INTEGER PRIMARY KEY);
        CREATE TABLE atividade_versao (id INTEGER PRIMARY KEY, eixo TEXT NOT NULL);
        """
    )
    return conn


def _seed_parents(conn):
    conn.executemany("INSERT INTO atividades (id) VALUES (?)", [(1,), (2,)])
    conn.executemany("INSERT INTO atividade_base (id) VALUES (?)", [(1,), (2,)])
    conn.executemany("INSERT INTO norma_atividade (id, eixo) VALUES (?, ?)", [(1, "AAC"), (2, "AEU")])
    conn.executemany("INSERT INTO matrizes_atividades (id) VALUES (?)", [(1,), (2,)])
    conn.executemany("INSERT INTO atividade_versao (id, eixo) VALUES (?, ?)", [(1, "AAC"), (2, "AEU")])


def _schema_rows(conn, table):
    return [tuple(row) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def test_baseline_leaf_blocks_are_owned_by_three_pure_helpers_in_exact_order():
    from app import db_maintenance

    baseline_main = _tree(_baseline(MAIN_PATH))
    current_maintenance = _tree(_read(DB_MAINTENANCE_PATH))
    baseline_orchestrator = _function(baseline_main, "ensure_atividade_versioning_schema")

    expected = {
        name: _sql_for_markers(baseline_orchestrator, markers)
        for name, markers in LEAF_SQL_MARKERS.items()
    }
    assert tuple(len(expected[name]) for name in LEAF_HELPERS) == (4, 2, 8)
    for name in LEAF_HELPERS:
        helper = _function(current_maintenance, name)
        assert _sql_for_markers(helper, LEAF_SQL_MARKERS[name]) == expected[name]
        assert len(helper.body) == len(expected[name])
        assert getattr(db_maintenance, name)


def test_main_orchestrator_is_absent_after_b10_core_migration():
    current_tree = _tree(_read(MAIN_PATH))
    assert _definition_count(current_tree, "ensure_atividade_versioning_schema") == 0
    assert _definition_count(current_tree, "_VERSAO_NEW_DDL") == 0


def test_core_migration_and_rebuild_nodes_are_absent_from_main_after_b10():
    current_tree = _tree(_read(MAIN_PATH))
    assert _definition_count(current_tree, "_VERSAO_NEW_DDL") == 0
    for name in CORE_FUNCTIONS:
        assert _definition_count(current_tree, name) == 0


def test_b8_v1_is_unchanged_and_b10_adds_v2_and_v3_registry_entries():
    baseline_tree = _tree(_baseline(DB_MAINTENANCE_PATH))
    current_tree = _tree(_read(DB_MAINTENANCE_PATH))
    baseline_registry = _assignment(baseline_tree, "SCHEMA_MIGRATIONS").value
    current_registry = _assignment(current_tree, "SCHEMA_MIGRATIONS").value
    assert isinstance(baseline_registry, (ast.Tuple, ast.List))
    assert isinstance(current_registry, (ast.Tuple, ast.List))
    assert ast.literal_eval(_assignment(baseline_tree, "SCHEMA_VERSION").value) == 1
    assert ast.literal_eval(_assignment(current_tree, "SCHEMA_VERSION").value) == 3
    assert len(baseline_registry.elts) == 1
    assert len(current_registry.elts) == 3
    assert _dump(current_registry.elts[0]) == _dump(baseline_registry.elts[0])
    v2_version, v2_name, v2_function = current_registry.elts[1].elts
    assert ast.literal_eval(v2_version) == 2
    assert ast.literal_eval(v2_name) == "normalize_atividades_schema"
    assert isinstance(v2_function, ast.Name) and v2_function.id == "_migration_v2_normalize_atividades_schema"
    v3_version, v3_name, v3_function = current_registry.elts[2].elts
    assert ast.literal_eval(v3_version) == 3
    assert ast.literal_eval(v3_name) == "normalize_activity_versioning_core"
    assert isinstance(v3_function, ast.Name) and v3_function.id == "_migration_v3_normalize_activity_versioning_core"


def test_sole_defining_ownership_import_identity_and_cycle_isolation():
    import main
    from app import db as app_db
    from app import db_maintenance

    trees = {
        "maintenance": _tree(_read(DB_MAINTENANCE_PATH)),
        "main": _tree(_read(MAIN_PATH)),
        "app_db": _tree(_read(APP_DB_PATH)),
    }
    for name in LEAF_HELPERS:
        assert _definition_count(trees["maintenance"], name) == 1
        assert _definition_count(trees["main"], name) == 0
        assert _definition_count(trees["app_db"], name) == 0

    assert getattr(main, "ensure_atividade_versioning_schema") is getattr(db_maintenance, "ensure_atividade_versioning_schema")

    code = (
        "import sys; assert 'main' not in sys.modules; "
        "import app.db_maintenance as module; "
        f"assert hasattr(module, 'ensure_atividade_versioning_schema'); "
        "assert 'main' not in sys.modules"
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", code],
        cwd=PROJECT_ROOT,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_app_db_preserves_b8_semantics_with_only_the_b9_checkpoint_and_lazy_delta():
    tree = _tree(_read(APP_DB_PATH))
    baseline_tree = _tree(_baseline(APP_DB_PATH))
    current_functions = {
        node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)
    }
    baseline_functions = {
        node.name: node for node in baseline_tree.body if isinstance(node, ast.FunctionDef)
    }
    assert current_functions.keys() == baseline_functions.keys()
    for name in current_functions.keys() - {"_get_main_db_helpers", "_init_db_impl"}:
        assert _dump(current_functions[name]) == _dump(baseline_functions[name]), name

    helper_map = _function(tree, "_get_main_db_helpers")
    returns = [node for node in ast.walk(helper_map) if isinstance(node, ast.Return)]
    assert len(returns) == 1 and isinstance(returns[0].value, ast.Dict)
    keys = tuple(ast.literal_eval(key) for key in returns[0].value.keys)
    values = tuple(
        f"{value.value.id}.{value.attr}"
        for value in returns[0].value.values
        if isinstance(value, ast.Attribute) and isinstance(value.value, ast.Name)
    )
    expected = (
        "get_preferred_matriz_for_curso",
        "logger",
    )
    assert keys == expected
    assert values == tuple(f"main.{name}" for name in expected)
    init = _function(tree, "_init_db_impl")
    source = ast.get_source_segment(_read(APP_DB_PATH), init)
    assert source is not None
    for name in expected:
        assert source.count(f'helpers["{name}"]') == 1
    assert "ensure_atividades_schema_current" not in source
    assert source.count("apply_early_schema_migrations(conn, logger=logger)") == 1
    assert source.index("conn = get_db_connection()") < source.index(
        "apply_early_schema_migrations(conn, logger=logger)"
    ) < source.index("CREATE TABLE IF NOT EXISTS usuarios")
    assert "ALTER TABLE atividades ADD COLUMN" not in source
    assert "UPDATE atividades SET tipo_atividade" not in source
    assert "from main import ensure_atividade_versioning_schema" not in _read(APP_DB_PATH)


@pytest.mark.parametrize("name", LEAF_HELPERS)
def test_helpers_are_static_caller_owned_transactions(name):
    from app import db_maintenance

    function = getattr(db_maintenance, name)
    source = inspect.getsource(function).upper()
    forbidden = (
        ".COMMIT(",
        ".ROLLBACK(",
        ".EXECUTESCRIPT(",
        "SAVEPOINT",
        "ROLLBACK TO",
        "BEGIN;",
        "PRAGMA ",
        "ALTER TABLE",
    )
    assert not any(token in source for token in forbidden)
    assert len(inspect.signature(function).parameters) == 1


def test_leaf_tables_have_exact_columns_defaults_checks_foreign_keys_and_idempotence():
    from app import db_maintenance

    conn = _new_connection()
    try:
        db_maintenance.ensure_atividade_versioning_leaf_tables(conn)
        first = {
            table: conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()[0]
            for table in LEAF_TABLES
        }
        first_columns = {table: _schema_rows(conn, table) for table in LEAF_TABLES}
        db_maintenance.ensure_atividade_versioning_leaf_tables(conn)
        second_columns = {table: _schema_rows(conn, table) for table in LEAF_TABLES}
        assert second_columns == first_columns

        assert [(row[1], row[2], row[3], row[4], row[5]) for row in first_columns["atividade_transicao"]] == [
            ("id", "INTEGER", 0, None, 1),
            ("from_atividade_versao_id", "INTEGER", 0, None, 0),
            ("to_atividade_versao_id", "INTEGER", 0, None, 0),
            ("tipo_transicao", "TEXT", 1, None, 0),
            ("justificativa", "TEXT", 0, None, 0),
            ("observacao_admin", "TEXT", 0, None, 0),
            ("created_at", "TEXT", 1, "datetime('now')", 0),
        ]
        assert [(row[1], row[2], row[3], row[4], row[5]) for row in first_columns["matriz_norma"]] == [
            ("id", "INTEGER", 0, None, 1),
            ("matriz_id", "INTEGER", 1, None, 0),
            ("norma_id", "INTEGER", 1, None, 0),
            ("created_at", "TEXT", 1, "datetime('now')", 0),
        ]
        assert [(row[1], row[2], row[3], row[4], row[5]) for row in first_columns["matriz_atividade_versao_item"]] == [
            ("id", "INTEGER", 0, None, 1),
            ("matriz_id", "INTEGER", 1, None, 0),
            ("atividade_versao_id", "INTEGER", 1, None, 0),
            ("created_at", "TEXT", 1, "datetime('now')", 0),
        ]
        assert [(row[1], row[2], row[3], row[4], row[5]) for row in first_columns["atividade_legacy_map"]] == [
            ("id", "INTEGER", 0, None, 1),
            ("atividade_id_legacy", "INTEGER", 1, None, 0),
            ("atividade_base_id", "INTEGER", 0, None, 0),
            ("status", "TEXT", 1, "'pendente'", 0),
            ("observacao_admin", "TEXT", 0, None, 0),
            ("created_at", "TEXT", 1, "datetime('now')", 0),
        ]
        normalized = {table: _normalized_sql(sql) for table, sql in first.items()}
        assert "CHECK(from_atividade_versao_id IS NOT NULL OR to_atividade_versao_id IS NOT NULL)" in normalized["atividade_transicao"]
        assert "from_atividade_versao_id <> to_atividade_versao_id" in normalized["atividade_transicao"]
        assert "tipo_transicao IN ('mesmo_eixo', 'aac_para_aeu', 'nova_aeu', 'descontinuada', 'sem_transicao')" in normalized["atividade_transicao"]
        assert "status IN ('pendente', 'mapeada', 'revisar')" in normalized["atividade_legacy_map"]

        expected_fks = {
            "atividade_transicao": {
                ("atividade_versao", "from_atividade_versao_id", "RESTRICT"),
                ("atividade_versao", "to_atividade_versao_id", "RESTRICT"),
            },
            "matriz_norma": {
                ("matrizes_atividades", "matriz_id", "CASCADE"),
                ("norma_atividade", "norma_id", "RESTRICT"),
            },
            "matriz_atividade_versao_item": {
                ("matrizes_atividades", "matriz_id", "CASCADE"),
                ("atividade_versao", "atividade_versao_id", "RESTRICT"),
            },
            "atividade_legacy_map": {
                ("atividades", "atividade_id_legacy", "RESTRICT"),
                ("atividade_base", "atividade_base_id", "SET NULL"),
            },
        }
        for table, expected in expected_fks.items():
            rows = conn.execute(f"PRAGMA foreign_key_list({table})").fetchall()
            assert {(row[2], row[3], row[6]) for row in rows} == expected
            assert {row[5] for row in rows} == {"NO ACTION"}
    finally:
        conn.close()


def test_leaf_unique_checks_and_foreign_key_actions():
    from app import db_maintenance

    conn = _new_connection()
    try:
        db_maintenance.ensure_atividade_versioning_leaf_tables(conn)
        _seed_parents(conn)
        conn.execute("INSERT INTO matriz_norma (matriz_id, norma_id) VALUES (1, 1)")
        conn.execute(
            "INSERT INTO matriz_atividade_versao_item (matriz_id, atividade_versao_id) VALUES (1, 1)"
        )
        conn.execute(
            "INSERT INTO atividade_legacy_map (atividade_id_legacy, atividade_base_id) VALUES (1, 1)"
        )
        for sql in (
            "INSERT INTO matriz_norma (matriz_id, norma_id) VALUES (1, 1)",
            "INSERT INTO matriz_atividade_versao_item (matriz_id, atividade_versao_id) VALUES (1, 1)",
            "INSERT INTO atividade_legacy_map (atividade_id_legacy, atividade_base_id) VALUES (1, 2)",
            "INSERT INTO atividade_transicao (tipo_transicao) VALUES ('sem_transicao')",
            "INSERT INTO atividade_transicao (from_atividade_versao_id, to_atividade_versao_id, tipo_transicao) VALUES (1, 1, 'mesmo_eixo')",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(sql)

        conn.execute("DELETE FROM matrizes_atividades WHERE id = 1")
        assert conn.execute("SELECT COUNT(*) FROM matriz_norma").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM matriz_atividade_versao_item").fetchone()[0] == 0
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM atividades WHERE id = 1")
        conn.execute("DELETE FROM atividade_base WHERE id = 1")
        assert conn.execute(
            "SELECT atividade_base_id FROM atividade_legacy_map WHERE atividade_id_legacy = 1"
        ).fetchone()[0] is None
    finally:
        conn.close()


def test_transition_triggers_preserve_exact_insert_and_update_behavior():
    from app import db_maintenance

    conn = _new_connection()
    try:
        db_maintenance.ensure_atividade_versioning_leaf_tables(conn)
        db_maintenance.ensure_atividade_versioning_leaf_triggers(conn)
        _seed_parents(conn)
        conn.execute(
            "INSERT INTO atividade_transicao (from_atividade_versao_id, to_atividade_versao_id, tipo_transicao) VALUES (1, 2, 'mesmo_eixo')"
        )

        cases = (
            (
                "INSERT INTO atividade_transicao (from_atividade_versao_id, to_atividade_versao_id, tipo_transicao) VALUES (1, 2, 'aac_para_aeu')",
                "Transição aac_para_aeu exige justificativa",
            ),
            (
                "INSERT INTO atividade_transicao (from_atividade_versao_id, tipo_transicao, justificativa) VALUES (1, 'aac_para_aeu', 'j')",
                "Transição aac_para_aeu exige from/to atividade_versao",
            ),
            (
                "INSERT INTO atividade_transicao (from_atividade_versao_id, to_atividade_versao_id, tipo_transicao, justificativa) VALUES (2, 1, 'aac_para_aeu', 'j')",
                "Transição aac_para_aeu exige eixo AAC -> AEU",
            ),
        )
        for sql, message in cases:
            with pytest.raises(sqlite3.IntegrityError, match=message):
                conn.execute(sql)

        conn.execute(
            "INSERT INTO atividade_transicao (from_atividade_versao_id, to_atividade_versao_id, tipo_transicao, justificativa) VALUES (1, 2, 'aac_para_aeu', 'válida')"
        )
        with pytest.raises(
            sqlite3.IntegrityError, match="Transição aac_para_aeu exige justificativa"
        ):
            conn.execute(
                "UPDATE atividade_transicao SET tipo_transicao='aac_para_aeu', justificativa=NULL WHERE id=1"
            )
        conn.execute(
            "UPDATE atividade_transicao SET tipo_transicao='aac_para_aeu', justificativa='update válido' WHERE id=1"
        )
        inventory = tuple(
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger' ORDER BY rowid"
            ).fetchall()
        )
        assert inventory == LEAF_TRIGGERS
    finally:
        conn.close()


def test_leaf_indexes_have_exact_inventory_order_columns_and_nonunique_classification():
    from app import db_maintenance

    conn = _new_connection()
    try:
        db_maintenance.ensure_atividade_versioning_leaf_tables(conn)
        db_maintenance.ensure_atividade_versioning_leaf_indexes(conn)
        rows = conn.execute(
            "SELECT name, tbl_name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_autoindex%' ORDER BY rowid"
        ).fetchall()
        assert [(row[0], row[1]) for row in rows] == [(name, table) for name, table, _ in LEAF_INDEXES]
        for name, table, columns in LEAF_INDEXES:
            index_row = next(row for row in conn.execute(f"PRAGMA index_list({table})") if row[1] == name)
            assert index_row[2] == 0
            assert tuple(row[2] for row in conn.execute(f"PRAGMA index_info({name})")) == columns
    finally:
        conn.close()


@pytest.mark.parametrize(
    ("helper_name", "expected_objects"),
    (
        (LEAF_TABLE_HELPER, LEAF_TABLES),
        (LEAF_TRIGGER_HELPER, LEAF_TRIGGERS),
        (LEAF_INDEX_HELPER, tuple(name for name, _, _ in LEAF_INDEXES)),
    ),
)
def test_caller_rollback_removes_each_helpers_uncommitted_ddl(helper_name, expected_objects):
    from app import db_maintenance

    conn = _new_connection()
    try:
        if helper_name != LEAF_TABLE_HELPER:
            db_maintenance.ensure_atividade_versioning_leaf_tables(conn)
            conn.commit()
        conn.execute("BEGIN")
        getattr(db_maintenance, helper_name)(conn)
        assert conn.in_transaction
        conn.rollback()
        object_type = "table" if helper_name == LEAF_TABLE_HELPER else "trigger" if helper_name == LEAF_TRIGGER_HELPER else "index"
        placeholders = ",".join("?" for _ in expected_objects)
        count = conn.execute(
            f"SELECT COUNT(*) FROM sqlite_master WHERE type=? AND name IN ({placeholders})",
            (object_type, *expected_objects),
        ).fetchone()[0]
        assert count == 0
    finally:
        conn.close()


class _InjectedFailure(RuntimeError):
    pass


class _FailingConnection:
    def __init__(self, connection, fail_at):
        self.connection = connection
        self.fail_at = fail_at
        self.calls = 0

    @property
    def in_transaction(self):
        return self.connection.in_transaction

    def execute(self, sql, *args):
        self.calls += 1
        if self.calls == self.fail_at:
            raise _InjectedFailure(sql)
        return self.connection.execute(sql, *args)


@pytest.mark.parametrize(
    ("helper_name", "fail_at"),
    ((LEAF_TABLE_HELPER, 2), (LEAF_TRIGGER_HELPER, 2), (LEAF_INDEX_HELPER, 4)),
)
def test_failure_in_each_helper_propagates_without_stealing_outer_transaction(helper_name, fail_at):
    from app import db_maintenance

    conn = _new_connection()
    try:
        if helper_name != LEAF_TABLE_HELPER:
            db_maintenance.ensure_atividade_versioning_leaf_tables(conn)
            conn.commit()
        conn.execute("BEGIN")
        proxy = _FailingConnection(conn, fail_at)
        with pytest.raises(_InjectedFailure):
            getattr(db_maintenance, helper_name)(proxy)
        assert conn.in_transaction
        conn.rollback()
        assert not conn.in_transaction
    finally:
        conn.close()
