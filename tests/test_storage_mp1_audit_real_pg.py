# coding: utf-8
"""MP-1 slice 2 on real PostgreSQL (opt-in, ``SGAA_PG_TEST_URL``): census and cross-check SQL.

Without ``SGAA_PG_TEST_URL`` the module skips (REAL-PG EVIDENCE: ABSENT).

E-PG1: the census eligibility predicates, the reference-discrepancy joins,
the reference digest and the mirror recovery transition run on PostgreSQL
through the runtime adapter, with the same verdicts as the SQLite lane; the
digest of an identical reference set is identical on both engines (the
cutover comparison the digest exists for).
"""

from __future__ import annotations

import sqlite3

import pytest
from flask import Flask

from tests.storage_mp1_pg_support import PG_URL

pytestmark = pytest.mark.skipif(
    not PG_URL, reason="SGAA_PG_TEST_URL is not configured -- REAL-PG EVIDENCE: ABSENT"
)

psycopg = pytest.importorskip("psycopg")

from app.db import write_transaction  # noqa: E402
from app.prod1_schema import bootstrap_prod1_schema  # noqa: E402
from app.storage import custody_common  # noqa: E402
from app.storage import drive_mirror  # noqa: E402
from app.storage import mirror_outbox as outbox  # noqa: E402
from app.storage import storage_audit as audit  # noqa: E402
from tests.canonical_store_fake import InMemoryObjectStore  # noqa: E402
from tests.storage_mp1_pg_support import Registry, adapter  # noqa: E402
from tests.storage_mp1_support import (  # noqa: E402
    ADMIN_ID,
    BUCKET,
    T0,
    Clock,
    FakeDrive,
    insert_object,
    object_state,
    seed_business,
    seed_canonical_arquivo,
    seed_canonical_request_document,
    sha256,
)
from tests.storage_s3a_support import PDF, PNG  # noqa: E402


@pytest.fixture(scope="module")
def registry():
    registry = Registry("audit")
    try:
        registry.provision_template()
        yield registry
    finally:
        assert registry.close() == 0


@pytest.fixture
def env(registry, monkeypatch):
    name, url = registry.create(template=registry.template)
    flask_app = Flask(__name__)
    store = InMemoryObjectStore()
    drive = FakeDrive()
    flask_app.extensions["canonical_object_store"] = store
    flask_app.extensions[drive_mirror.DRIVE_STORAGE_EXTENSION] = drive
    monkeypatch.setattr(custody_common, "utc_now_text", Clock(T0))
    conn = adapter(url)
    try:
        with flask_app.app_context():
            yield dict(conn=conn, store=store, drive=drive)
    finally:
        conn.close()
        registry.drop(name)


def _seed(conn, store):
    """The same reference set on either engine (explicit ids: the digest compares ids)."""
    seed_canonical_request_document(conn, store, key="comprovantes/2026/10/" + "1" * 32, content=PDF)
    seed_canonical_arquivo(conn, store, key="arquivos/2026/10/" + "2" * 32, content=PNG, mime="image/png")
    conn.execute(
        "INSERT INTO requisicao_arquivos(requisicao_id,filename,provider,storage_status,remote_file_id,"
        "remote_parent_id,original_filename,mime_type,size_bytes,sha256,uploaded_at,uploader_user_id,operation_key)"
        " VALUES(1,'REQ-000001__x.pdf','google','active','drvreq1','drvparent1','prova.pdf','application/pdf',"
        "?,?,'2026-09-01T10:00:00Z',?,'legacy-op')", (len(PDF), sha256(PDF), ADMIN_ID))
    conn.execute("INSERT INTO requisicao_arquivos(requisicao_id,filename) VALUES(1,'documentos/x.pdf')")
    conn.execute("INSERT INTO admin_arquivos(titulo,filename) VALUES('Antigo','arquivos/antigo.pdf')")
    orphan = insert_object(conn, key="comprovantes/2026/10/" + "9" * 32, content=b"%PDF-orphan")
    store.objects[(BUCKET, "comprovantes/2026/10/" + "9" * 32)] = (b"%PDF-orphan", "application/pdf")
    conn.commit()
    return orphan


def test_census_and_cross_check_on_postgres(env):
    conn, store = env["conn"], env["store"]
    _seed(conn, store)

    census = audit.census(conn)
    report = audit.cross_check(conn, store=store, deep=True, show_ids=True)

    assert census["documents"]["requisicao_arquivos"]["eligible"] == {"google": 1, "local_legacy": 1}
    assert census["documents"]["admin_arquivos"]["eligible"] == {"google": 0, "local_legacy": 1}
    assert census["objects"]["lifecycle"] == {"active": 3, "retired": 0}
    assert {k: v for k, v in report["references"].items() if v} == {"ACTIVE_OBJECT_UNOWNED": 1}
    assert report["storage"]["checked"] == 3 and report["verdict"]["storage_consistent"] is True
    assert report["legacy_remaining"] == 3
    conn.commit()


def test_reference_digest_is_engine_neutral(env, tmp_path):
    conn, store = env["conn"], env["store"]
    _seed(conn, store)
    lite = sqlite3.connect(tmp_path / "digest.db")
    lite.execute("PRAGMA foreign_keys=ON")
    bootstrap_prod1_schema(lite)
    seed_business(lite)
    _seed(lite, InMemoryObjectStore())

    assert audit.reference_digest(conn) == audit.reference_digest(lite)
    lite.close()
    conn.commit()


def test_mirror_recovery_transition_on_postgres(env):
    conn, store = env["conn"], env["store"]
    seed_canonical_arquivo(conn, store, key="arquivos/2026/10/" + "3" * 32, content=PDF)
    conn.commit()
    assert drive_mirror.run_mirror_pass(conn).synced == 1
    drive = drive_mirror.active_drive(conn)
    next(iter(env["drive"].files.values()))["trashed"] = True

    report = audit.cross_check(conn, store=store, drive=drive, requeue_missing_mirrors=True)

    assert (report["mirror"]["MIRROR_MISSING"], report["mirror"]["requeued"]) == (1, 1)
    object_id = conn.execute("SELECT id FROM storage_objects").fetchone()[0]
    state = object_state(conn, object_id)
    assert (state["state"], state["file_id"], state["error"], state["attempts"]) == (
        "pending", None, "MIRROR_MISSING", 0)
    with write_transaction(conn):
        assert outbox.reset_missing_mirror(conn, object_id=object_id, drive_file_id="x",
                                           error_code="MIRROR_MISSING", now=T0) == 0
    assert drive_mirror.run_mirror_pass(conn).synced == 1
    conn.commit()
