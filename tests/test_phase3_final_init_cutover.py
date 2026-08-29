"""The application factory remains the sole prod-1 initialization owner."""
from __future__ import annotations

import inspect
import sqlite3

import pytest
from flask import Flask

from app import db as app_db
from app.prod1_schema import Prod1SchemaError, validate_prod1_schema


def _app(path):
    app = Flask(__name__)
    app.config.update(DATABASE=str(path), SECRET_KEY="test", AUTO_CREATE_DEFAULT_ADMIN=False)
    return app


def test_app_db_is_sole_init_owner_and_does_not_import_main():
    source = inspect.getsource(app_db)
    assert "def init_db" in source
    assert "import main" not in source


def test_factory_init_bootstraps_empty_prod1_database(tmp_path):
    app = _app(tmp_path / "empty.db")
    with app.app_context():
        app_db.init_db()
        status = validate_prod1_schema(app_db.get_db_connection())
    assert status["schema_epoch"] == "prod-1"
    assert status["schema_version"] == 3


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
