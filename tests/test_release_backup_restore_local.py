"""Release-level local backup/restore over an isolated prod-1 database."""
from __future__ import annotations

import sqlite3

from app.db_maintenance import create_database_snapshot, restore_database_snapshot
from app.prod1_schema import bootstrap_prod1_schema, validate_prod1_schema


def test_release_backup_restore_local_isolated(tmp_path):
    database = tmp_path / "release-prod1.db"
    backups = tmp_path / "backups"
    conn = sqlite3.connect(database)
    bootstrap_prod1_schema(conn)
    conn.execute(
        "INSERT INTO atividade_base(nome_conceito,status) VALUES('Release marker','ativo')"
    )
    conn.commit(); conn.close()

    manifest = create_database_snapshot(str(database), str(backups), reason="release-test")
    conn = sqlite3.connect(database)
    conn.execute("DELETE FROM atividade_base WHERE nome_conceito='Release marker'")
    conn.commit(); conn.close()

    restore_database_snapshot(manifest["database_path"], str(database))
    conn = sqlite3.connect(database)
    assert conn.execute(
        "SELECT 1 FROM atividade_base WHERE nome_conceito='Release marker'"
    ).fetchone()
    assert validate_prod1_schema(conn)["schema_epoch"] == "prod-1"
    conn.close()
