"""Test-only v19 -> v18 inverse for frozen predecessor fixtures.

v19 only adds the two (empty) document-template tables, their index and
triggers, so the inverse drops exactly those and marker 19.  It is not
production code: v19 has no shipped downgrade path.
"""
from app.prod1_document_templates_ddl import DOCUMENT_TEMPLATES_V19_TABLES


def drop_pg_v19_objects(raw):
    """PostgreSQL: remove the v19 additions from a provisioned head, inside the caller's
    transaction, leaving the frozen v18 objects (meta row and digest are the caller's)."""
    from app import pg_schema

    for table in reversed(DOCUMENT_TEMPLATES_V19_TABLES):
        raw.execute(f"DROP TABLE {table}")
    for function in ("fn_atividade_versao_modelos_history", "fn_modelo_documento_arquivos_immutable"):
        raw.execute(f"DROP FUNCTION {function}()")
    raw.execute("DELETE FROM schema_migrations WHERE version >= 19")
    raw.execute(f"UPDATE {pg_schema.PG_SCHEMA_META_TABLE} SET schema_version = 18, "
                f"contract_sha256 = '{pg_schema._PG_V18_CONTRACT_SHA256}'")


def revert_prod1_v19_to_v18(conn):
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 19
    for table in DOCUMENT_TEMPLATES_V19_TABLES:
        assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0, table
    conn.commit()
    try:
        conn.execute("BEGIN IMMEDIATE")
        # Children first: the association references the content table.
        for table in reversed(DOCUMENT_TEMPLATES_V19_TABLES):
            conn.execute(f"DROP TABLE {table}")
        conn.execute(
            "DELETE FROM sqlite_sequence WHERE name IN (%s)" % ",".join("?" for _ in DOCUMENT_TEMPLATES_V19_TABLES),
            DOCUMENT_TEMPLATES_V19_TABLES,
        )
        conn.execute("DELETE FROM schema_migrations WHERE version=19")
        conn.execute("PRAGMA user_version=18")
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
