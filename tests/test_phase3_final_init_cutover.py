"""The application factory remains the sole prod-1 initialization owner."""
from __future__ import annotations

import inspect
import sqlite3
from pathlib import Path

import pytest
from flask import Flask

from app import db as app_db
from app.prod1_schema import (
    EXPECTED_TABLES,
    LATEST_MIGRATION_MARKER,
    SCHEMA_EPOCH,
    SCHEMA_VERSION,
    Prod1SchemaError,
    validate_prod1_schema,
)


def _app(path):
    app = Flask(__name__)
    app.config.update(DATABASE=str(path), SECRET_KEY="test", AUTO_CREATE_DEFAULT_ADMIN=False)
    return app


def test_app_db_is_sole_init_owner_and_does_not_import_main():
    source = inspect.getsource(app_db)
    assert "def init_db" in source
    assert "import main" not in source


def test_factory_init_bootstraps_empty_prod1_database(tmp_path, monkeypatch):
    path = tmp_path / "empty.db"
    assert not path.exists()
    assert path.resolve() != Path(__file__).resolve().parents[1] / "database.db"
    monkeypatch.setattr(app_db, "DATABASE", str(path))
    app = _app(path)
    with app.app_context():
        app_db.init_db()
        conn = app_db.get_db_connection()
        status = validate_prod1_schema(conn)
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        latest_marker = conn.execute(
            "SELECT version,name,schema_epoch FROM schema_migrations "
            "ORDER BY version DESC LIMIT 1"
        ).fetchone()
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        app_db.close_db_connection(None)
    assert path.is_file()
    assert tables == EXPECTED_TABLES
    assert status["schema_epoch"] == "prod-1"
    assert status["schema_version"] == SCHEMA_VERSION
    assert tuple(latest_marker) == (
        SCHEMA_VERSION,
        LATEST_MIGRATION_MARKER,
        SCHEMA_EPOCH,
    )


def test_factory_init_is_idempotent(tmp_path):
    app = _app(tmp_path / "idempotent.db")
    with app.app_context():
        app_db.init_db()
        app_db.init_db()
        validate_prod1_schema(app_db.get_db_connection())


def test_factory_rejects_nonempty_legacy_database_before_mutation(tmp_path, monkeypatch):
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE atividades(id INTEGER PRIMARY KEY)")
    conn.commit(); conn.close()
    before = path.read_bytes()
    monkeypatch.setattr(app_db, "DATABASE", str(path))
    app = _app(path)
    with app.app_context(), pytest.raises(Prod1SchemaError):
        app_db.init_db()
    assert path.read_bytes() == before
