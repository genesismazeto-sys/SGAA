"""Real PostgreSQL 17: v18 upgrade, return snapshots, expiry and recovery."""
import datetime
import pytest
from app import pg_schema
from app.request_email_notifications import pending_request_ids
from app.request_email_recovery import recover_return_notification
from app.requisitions import auto_indefer_devolvidas
from tests.storage_mp1_pg_support import PG_URL, Registry, adapter, raw_connection
from tests.storage_mp1_support import REQUEST_ID

pytestmark = pytest.mark.skipif(not PG_URL, reason="SGAA_PG_TEST_URL is required")


@pytest.fixture(scope="module")
def registry():
    registry = Registry("return18")
    try:
        registry.provision_template()
        yield registry
    finally:
        assert registry.close() == 0


def test_v17_upgrade_and_return_notification_lifecycle(registry):
    name, url = registry.create(template=registry.template)
    raw = raw_connection(url)
    try:
        check = next(c for c in pg_schema.PG_TABLE_SPECS['requisicao_email_eventos']['checks'] if c['name'].endswith('status_decisao'))
        old = check['expression'].replace(",'Devolvida'", "")
        raw.execute(f'ALTER TABLE requisicao_email_eventos DROP CONSTRAINT "{check["name"]}", '
                    f'ADD CONSTRAINT "{check["name"]}" CHECK ({old})')
        raw.execute("DELETE FROM schema_migrations WHERE version=18")
        raw.execute(f"UPDATE pg_schema_meta SET schema_version=17,contract_sha256='{pg_schema._PG_V17_CONTRACT_SHA256}'")
        raw.commit()
        assert pg_schema.upgrade_database(url)["from_version"] == 17
        assert pg_schema.upgrade_database(url)["status"] == "already_current"
    finally:
        raw.close()
    conn = adapter(url)
    try:
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("UPDATE requisicoes SET status='Devolvida',observacao='Synthetic correction',data_processamento=?,admin_id=1 WHERE id=?", (stamp, REQUEST_ID))
        conn.commit()
        assert recover_return_notification(conn, request_id=REQUEST_ID, decided_at=stamp) == "eligible"
        assert recover_return_notification(conn, request_id=REQUEST_ID, decided_at=stamp, apply=True) == "recovered"
        assert pending_request_ids(conn) == {REQUEST_ID}
        # Snapshot round-trip and repeated controlled recovery.
        assert conn.execute("SELECT status_decisao,justificativa FROM requisicao_email_eventos").fetchone()["status_decisao"] == "Devolvida"
        conn.commit()
        assert recover_return_notification(conn, request_id=REQUEST_ID, decided_at=stamp, apply=True) == "ineligible"
        conn.execute("INSERT INTO configuracoes_app(chave,valor) VALUES('auto_indefer_devolvida','1') ON CONFLICT(chave) DO UPDATE SET valor='1'")
        conn.execute("UPDATE requisicoes SET data_processamento='2000-01-01' WHERE id=?", (REQUEST_ID,))
        conn.commit()
        assert auto_indefer_devolvidas(conn) == 1
        assert pending_request_ids(conn) == set()
        assert conn.execute("SELECT estado FROM requisicao_email_eventos").fetchone()["estado"] == "superseded"
    finally:
        conn.close()
        registry.drop(name)
