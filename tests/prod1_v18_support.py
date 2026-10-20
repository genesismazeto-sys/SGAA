"""Test-only v18 -> v17 inverse for frozen predecessor fixtures."""
from app.prod1_notifications_ddl import NOTIFICATIONS_V7_INDEXES_SQL
from app.prod1_schema import canonical_prod1_pre_v18_object_sql


def revert_prod1_v18_to_v17(conn):
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 18
    assert not conn.execute("SELECT 1 FROM requisicao_email_eventos WHERE status_decisao='Devolvida'").fetchone()
    conn.commit()
    sequences = conn.execute("SELECT name,seq FROM sqlite_sequence WHERE name='requisicao_email_eventos'").fetchall()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("CREATE TABLE _return_events_v17 AS SELECT * FROM requisicao_email_eventos")
        conn.execute("DROP TABLE requisicao_email_eventos")
        conn.execute(canonical_prod1_pre_v18_object_sql("table", "requisicao_email_eventos"))
        conn.execute("INSERT INTO requisicao_email_eventos SELECT * FROM _return_events_v17")
        conn.execute("DROP TABLE _return_events_v17")
        for statement in NOTIFICATIONS_V7_INDEXES_SQL[:4]:
            conn.execute(statement)
        conn.execute("DELETE FROM sqlite_sequence WHERE name='requisicao_email_eventos'")
        for name, seq in sequences:
            conn.execute("INSERT INTO sqlite_sequence(name,seq) VALUES(?,?)", (name, seq))
        conn.execute("DELETE FROM schema_migrations WHERE version=18")
        conn.execute("PRAGMA user_version=17")
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
