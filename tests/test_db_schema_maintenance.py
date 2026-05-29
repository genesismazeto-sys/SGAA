import os
import sys


BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main
from app.db_maintenance import SCHEMA_VERSION


def test_init_db_registers_schema_version():
    with main.app.app_context():
        main.init_db()
        conn = main.get_db_connection()
        schema_version = conn.execute("PRAGMA user_version").fetchone()[0]
        migration = conn.execute(
            "SELECT version, name FROM schema_migrations ORDER BY version DESC LIMIT 1"
        ).fetchone()

    assert schema_version == SCHEMA_VERSION
    assert migration is not None
    assert migration["version"] == SCHEMA_VERSION
    assert migration["name"] == "baseline_schema_management"