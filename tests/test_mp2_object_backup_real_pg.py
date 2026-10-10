# coding: utf-8
"""MP-2 slice 5 on real PostgreSQL (opt-in, ``SGAA_PG_TEST_URL``): the object backup's database reads.

Without ``SGAA_PG_TEST_URL`` the module skips (REAL-PG EVIDENCE: ABSENT).

E-PG1: ``current_rows`` and the ``--database`` comparison run the SQL
PostgreSQL runs, and a backup leaves its connection IDLE: a long copy of the
objects must not hold ``ACCESS SHARE`` on ``storage_objects`` for its duration
(a held lock would block DDL and the schema migration behind it).
"""

from __future__ import annotations

import pytest

from tests.storage_mp1_pg_support import PG_URL

pytestmark = pytest.mark.skipif(
    not PG_URL, reason="SGAA_PG_TEST_URL is not configured -- REAL-PG EVIDENCE: ABSENT"
)

psycopg = pytest.importorskip("psycopg")

from app.db import connection_transaction_status  # noqa: E402
from app.storage import object_backup  # noqa: E402
from tests.canonical_store_fake import InMemoryObjectStore  # noqa: E402
from tests.storage_mp1_pg_support import Registry, adapter  # noqa: E402
from tests.storage_mp1_support import BUCKET, insert_object  # noqa: E402

PDF = b"%PDF-1.4\n" + b"0123456789abcdef" * 32
PNG = b"\x89PNG\r\n\x1a\n" + b"fedcba9876543210" * 20


@pytest.fixture(scope="module")
def registry():
    registry = Registry("objbak")
    try:
        registry.provision_template()
        yield registry
    finally:
        assert registry.close() == 0


@pytest.fixture
def database(registry):
    name, url = registry.create(template=registry.template)
    conn = adapter(url)
    try:
        yield conn, url
    finally:
        conn.close()
        registry.drop(name)


def _seed(conn, store):
    ids = []
    for name, content, mime in (("a", PDF, "application/pdf"), ("b", PNG, "image/png"), ("c", PDF + b"2", "application/pdf")):
        key = f"comprovantes/2026/10/{name * 32}"
        ids.append(insert_object(conn, key=key, content=content, mime=mime))
        store.objects[(BUCKET, key)] = (content, mime)
    conn.commit()
    return ids


def test_backup_and_database_comparison_run_on_postgresql_and_leave_no_open_transaction(database, tmp_path):
    conn, url = database
    store = InMemoryObjectStore()
    ids = _seed(conn, store)
    target = tmp_path / "set"

    report = object_backup.backup(conn, store, str(target), label="pg")

    assert report.ok and report.objects == 3
    assert connection_transaction_status(conn) == "IDLE"  # the snapshot read did not stay open
    assert set(store.calls) <= {"stat", "read"}
    verified = object_backup.verify_set(str(target), conn=conn)
    assert verified.ok and verified.database["missing"] == verified.database["extra"] == 0
    assert connection_transaction_status(conn) == "INTRANS"  # the comparison's own read; ended below
    conn.rollback()

    other = adapter(url)
    try:
        other.execute("DELETE FROM storage_objects WHERE id=?", (ids[0],))
        other.execute("UPDATE storage_objects SET mime_type='image/png' WHERE id=?", (ids[2],))
        other.commit()
    finally:
        other.close()
    drifted = object_backup.verify_set(str(target), conn=conn)
    conn.rollback()
    assert not drifted.ok and drifted.result_code == object_backup.RESULT_OK
    assert drifted.database["extra_ids"] == [ids[0]] and drifted.database["changed_ids"] == [ids[2]]


def test_a_concurrent_ddl_is_not_blocked_by_a_finished_backup(database, tmp_path):
    """The proof the rollback matters: DDL needing ACCESS EXCLUSIVE proceeds right after the backup."""
    conn, url = database
    store = InMemoryObjectStore()
    _seed(conn, store)
    assert object_backup.backup(conn, store, str(tmp_path / "set")).ok
    other = adapter(url)
    try:
        other.raw_connection.execute("SET lock_timeout = '3s'")
        other.execute("ALTER TABLE storage_objects ADD COLUMN sgaa_probe_column TEXT")
        other.rollback()  # the probe column never persists
    finally:
        other.close()
