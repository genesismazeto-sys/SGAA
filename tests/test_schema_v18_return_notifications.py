"""v18 CHECK expansion: frozen predecessor, data preservation and rollback."""
import sqlite3

import pytest
from app import prod1_schema
from app.prod1_storage_v14 import _sequences
from tests.prod1_v18_support import revert_prod1_v18_to_v17
from tests.request_email_support import decide, new_v7_connection, seed_activity, seed_request, seed_student


def predecessor():
    conn = new_v7_connection()
    version = seed_activity(conn)
    student = seed_student(conn, nome="Synthetic Student", matricula="TEST18", email="test@example.test")
    for state in ("pending", "sent", "superseded"):
        req = seed_request(conn, aluno_id=student, versao_id=version)
        event = decide(conn, req, status="Indeferida", observacao="Synthetic reason")
        conn.execute("UPDATE requisicao_email_eventos SET estado=? WHERE id=?", (state, event))
    conn.execute("UPDATE sqlite_sequence SET seq=1000 WHERE name='requisicao_email_eventos'")
    conn.commit()
    revert_prod1_v18_to_v17(conn)
    return conn


def test_migration_preserves_all_event_states_and_high_water_counter():
    conn = predecessor()
    prod1_schema._validate_prod1_v17_schema(conn)
    rows = [tuple(r) for r in conn.execute("SELECT * FROM requisicao_email_eventos ORDER BY id")]
    counters = _sequences(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE requisicao_email_eventos SET status_decisao='Devolvida'")
    conn.rollback()
    assert prod1_schema.bootstrap_prod1_schema(conn)["schema_version"] == 18
    assert [tuple(r) for r in conn.execute("SELECT * FROM requisicao_email_eventos ORDER BY id")] == rows
    assert _sequences(conn) == counters
    assert prod1_schema.bootstrap_prod1_schema(conn)["schema_version"] == 18
    conn.execute("UPDATE requisicao_email_eventos SET status_decisao='Devolvida'")
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.rollback()


def test_migration_failure_rolls_back_table_rows_indexes_and_counter(monkeypatch):
    import app.prod1_return_notifications_v18 as migration
    conn = predecessor()
    before = prod1_schema._physical_schema_digest(conn)
    counters = _sequences(conn)
    monkeypatch.setattr(migration, "RETURN_NOTIFICATIONS_V18_STATEMENTS",
                        migration.RETURN_NOTIFICATIONS_V18_STATEMENTS[:2] + ("INVALID SQL",))
    with pytest.raises(sqlite3.Error):
        prod1_schema.migrate_prod1_v17_to_v18(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 17
    assert prod1_schema._physical_schema_digest(conn) == before
    assert _sequences(conn) == counters
    assert conn.execute("SELECT count(*) FROM requisicao_email_eventos").fetchone()[0] == 3


def test_migration_refuses_a_tampered_predecessor():
    conn = predecessor()
    conn.execute("DROP INDEX ux_req_email_eventos_pendente")
    with pytest.raises(prod1_schema.Prod1SchemaError):
        prod1_schema.bootstrap_prod1_schema(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 17
