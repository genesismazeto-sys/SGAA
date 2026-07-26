import ast
import inspect
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from flask import g

from app import db as app_db
import main


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _top_level_definitions(module):
    tree = ast.parse(inspect.getsource(module))
    functions = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assignments = {
        target.id
        for node in tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        for target in (
            node.targets if isinstance(node, ast.Assign) else [node.target]
        )
        if isinstance(target, ast.Name)
    }
    imports = {
        alias.asname or alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "app.db"
        for alias in node.names
    }
    return functions, assignments, imports


def test_app_db_is_the_only_connection_owner_and_main_imports_compatibility_exports():
    app_functions, app_assignments, _ = _top_level_definitions(app_db)
    main_functions, main_assignments, main_imports = _top_level_definitions(main)

    assert {"get_db_connection", "close_db_connection"} <= app_functions
    assert "_sync_database_from_main" in app_functions
    assert "DATABASE" in app_assignments
    assert not ({"get_db_connection", "close_db_connection"} & main_functions)
    assert "DATABASE" not in main_assignments
    assert {"DATABASE", "get_db_connection", "close_db_connection"} <= main_imports

    app_db_source = inspect.getsource(app_db)
    sync_source = inspect.getsource(app_db._sync_database_from_main)
    assert 'sys.modules.get("main")' not in app_db_source
    assert "main.DATABASE" not in app_db_source
    assert "import main" not in sync_source
    assert "sys.modules" not in sync_source
    assert inspect.getsource(app_db.init_db) == (
        "def init_db():\n"
        "    _sync_database_from_main()\n"
        "    return _init_db_impl()\n"
    )


def test_main_connection_compatibility_exports_are_owner_objects():
    assert main.DATABASE is app_db.DATABASE
    assert main.get_db_connection is app_db.get_db_connection
    assert main.close_db_connection is app_db.close_db_connection


def test_disposable_connection_preserves_configuration_collation_reuse_and_close(
    monkeypatch, tmp_path
):
    database_path = tmp_path / "phase3a_connection.db"
    monkeypatch.setattr(app_db, "DATABASE", str(database_path))
    monkeypatch.setattr(main, "DATABASE", str(database_path))
    monkeypatch.setitem(main.app.config, "DATABASE_PATH", str(database_path))

    with main.app.app_context():
        app_db.close_db_connection(None)
        first = app_db.get_db_connection()
        second = main.get_db_connection()

        assert first is second
        assert first.row_factory is sqlite3.Row
        assert first.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert first.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert first.execute("PRAGMA synchronous").fetchone()[0] == 1
        assert first.execute(
            "SELECT CASE WHEN 'ação' = 'ACAO' COLLATE PTBR_NOACCENT THEN 1 ELSE 0 END"
        ).fetchone()[0] == 1

        main.close_db_connection(None)
        assert "db" not in g
        with pytest.raises(sqlite3.ProgrammingError):
            first.execute("SELECT 1")

    assert database_path.is_file()
    assert not database_path.with_name(database_path.name + "-wal").exists()
    assert not database_path.with_name(database_path.name + "-shm").exists()


def test_factory_registers_only_the_canonical_close_lifecycle():
    connection_closers = [
        function
        for function in main.app.teardown_appcontext_funcs
        if function.__name__ == "close_db_connection"
    ]
    assert connection_closers == [app_db.close_db_connection]


def test_app_database_environment_resolution_and_import_isolation(tmp_path):
    database_path = tmp_path / "configured.db"
    code = (
        "import os, sys; "
        "assert 'main' not in sys.modules; "
        "import app.db as db; "
        "assert db.DATABASE == os.environ['APP_DATABASE']; "
        "assert 'main' not in sys.modules"
    )
    environment = os.environ.copy()
    environment["APP_DATABASE"] = str(database_path)

    result = subprocess.run(
        [sys.executable, "-B", "-c", code],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert not database_path.exists()


def test_app_database_default_resolution_does_not_open_the_canonical_database():
    code = (
        "import os, pathlib, sys; "
        "os.environ.pop('APP_DATABASE', None); "
        "assert 'main' not in sys.modules; "
        "import app.db as db; "
        "expected = pathlib.Path(db.PROJECT_ROOT) / 'database.db'; "
        "assert pathlib.Path(db.DATABASE) == expected; "
        "assert 'main' not in sys.modules"
    )
    environment = os.environ.copy()
    environment.pop("APP_DATABASE", None)

    result = subprocess.run(
        [sys.executable, "-B", "-c", code],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
