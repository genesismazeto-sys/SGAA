# coding: utf-8
"""Drive copies and Supabase staging release on real PostgreSQL (opt-in, ``SGAA_PG_TEST_URL``).

Without ``SGAA_PG_TEST_URL`` the module skips (REAL-PG EVIDENCE: ABSENT).  The
copy registry lives in ``sgaa_ops`` (PostgreSQL only), so this is its lane.

1. every connected drive receives one verified copy; repeated passes and an
   interrupted completion never duplicate a file;
2. a connected drive that fails keeps the Supabase copy and is retried later;
3. the Supabase copy is deleted only after every connected drive's copy was
   read back and proven; afterwards the document is served from a verified
   copy, falling back to the other drive when one fails.
"""

from __future__ import annotations

import pytest
from flask import Flask

from tests.storage_mp1_pg_support import PG_URL

pytestmark = pytest.mark.skipif(
    not PG_URL, reason="SGAA_PG_TEST_URL is not configured -- REAL-PG EVIDENCE: ABSENT"
)

psycopg = pytest.importorskip("psycopg")

from app.db import write_transaction  # noqa: E402
from app.storage import arquivo_documents  # noqa: E402
from app.storage import copy_registry  # noqa: E402
from app.storage import custody_common  # noqa: E402
from app.storage import document_copies  # noqa: E402
from app.storage import drive_mirror  # noqa: E402
from app.storage import request_documents  # noqa: E402
from app.storage import staging_release  # noqa: E402
from app.storage.contracts import StorageTransientError  # noqa: E402
from app.storage.onedrive import ONEDRIVE_STORAGE_EXTENSION  # noqa: E402
from tests.canonical_store_fake import InMemoryObjectStore  # noqa: E402
from tests.storage_mp1_pg_support import Registry, adapter  # noqa: E402
from tests.storage_mp1_support import (  # noqa: E402
    ACCOUNT_KEY,
    BUCKET,
    OTHER_ACCOUNT_KEY,
    T0,
    Clock,
    FakeDrive,
    object_state,
    seed_canonical_arquivo,
    seed_canonical_request_document,
)
from tests.storage_s3a_support import PDF, PNG  # noqa: E402


class FakeOneDrive(FakeDrive):
    provider = "onedrive"


@pytest.fixture(scope="module")
def registry():
    registry = Registry("copies")
    try:
        registry.provision_template()
        yield registry
    finally:
        assert registry.close() == 0


@pytest.fixture
def env(registry, monkeypatch):
    name, url = registry.create(template=registry.template)
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    store, google, onedrive = InMemoryObjectStore(), FakeDrive(), FakeOneDrive()
    flask_app.extensions["canonical_object_store"] = store
    flask_app.extensions[drive_mirror.DRIVE_STORAGE_EXTENSION] = google
    flask_app.extensions[ONEDRIVE_STORAGE_EXTENSION] = onedrive
    clock = Clock(T0)
    monkeypatch.setattr(custody_common, "utc_now_text", clock)
    conn = adapter(url)
    try:
        with flask_app.app_context():
            conn.execute(
                "INSERT INTO cloud_accounts(provider,token_json,active,provider_account_key) VALUES('onedrive','{}',1,?)",
                (OTHER_ACCOUNT_KEY,),
            )
            conn.commit()
            # Activation first: everything seeded afterwards is a NEW upload (auto-enrolled).
            assert copy_registry.prepare(conn, now=T0)
            yield dict(app=flask_app, conn=conn, store=store, google=google, onedrive=onedrive, clock=clock)
    finally:
        conn.close()
        registry.drop(name)


def _seed(env):
    conn = env["conn"]
    _req, req_obj = seed_canonical_request_document(conn, env["store"], key="comprovantes/2026/10/" + "a" * 32,
                                                    content=PDF)
    _arq, arq_obj = seed_canonical_arquivo(conn, env["store"], key="arquivos/2026/10/" + "b" * 32, content=PNG,
                                           mime="image/png")
    conn.commit()
    return req_obj, arq_obj


def _mirror_both(conn):
    google = drive_mirror.run_mirror_pass(conn, provider="google")
    onedrive = drive_mirror.run_mirror_pass(conn, provider="onedrive")
    return google, onedrive


def _onedrive_row(conn, object_id):
    row = conn.execute(
        "SELECT sync_state, file_id, account_key, attempts, last_error_code, verified_at"
        " FROM sgaa_ops.storage_copies WHERE object_id = ? AND provider = 'onedrive'",
        (object_id,),
    ).fetchone()
    conn.commit()
    return dict(zip(("state", "file_id", "account_key", "attempts", "error", "verified_at"), tuple(row)))


def _staging(conn, object_id):
    state = copy_registry.staging_state(conn, object_id)
    conn.commit()
    return state


# --- 1. verified copies, no duplication ------------------------------------------------------


def test_every_connected_drive_gets_one_verified_copy_and_reruns_never_duplicate(env):
    conn = env["conn"]
    ids = _seed(env)
    copy_registry.prepare(conn, now=T0)  # enrolls the new uploads

    google, onedrive = _mirror_both(conn)

    assert (google.result_code, google.synced, onedrive.result_code, onedrive.synced) == ("OK", 2, "OK", 2)
    for object_id in ids:
        assert object_state(conn, object_id)["state"] == "synced"
        row = _onedrive_row(conn, object_id)
        assert (row["state"], row["account_key"]) == ("synced", OTHER_ACCOUNT_KEY) and row["file_id"]
        assert _staging(conn, object_id) == copy_registry.STAGED
    # Same folder conventions on both drives: SGAA / COMPROVANTES / turma / eixo / aluno and SGAA / ARQUIVOS.
    assert set(env["onedrive"].folders) == set(env["google"].folders)

    # Repeated scheduler runs: nothing is due, nothing is uploaded again.
    for _ in range(2):
        again = _mirror_both(conn)
        assert [result.claimed for result in again] == [0, 0]
    # An interrupted completion (the upload landed, the record did not): the next pass adopts it.
    with write_transaction(conn):
        conn.execute(
            "UPDATE sgaa_ops.storage_copies SET sync_state = 'pending', file_id = NULL, synced_at = NULL"
            " WHERE object_id = ?", (ids[0],),
        )
    resumed = drive_mirror.run_mirror_pass(conn, provider="onedrive")
    assert (resumed.claimed, resumed.synced) == (1, 1)
    assert len(env["google"].files) == 2 and len(env["onedrive"].files) == 2


# --- 2. an unavailable drive keeps the Supabase copy and is retried ------------------------------


def test_a_failing_drive_keeps_the_staging_copy_and_is_retried_until_it_succeeds(env):
    conn = env["conn"]
    req_obj, _arq_obj = _seed(env)
    copy_registry.prepare(conn, now=T0)
    for _ in range(2):
        env["onedrive"].fail_next("upload", StorageTransientError("down"))

    google, onedrive = _mirror_both(conn)
    released = staging_release.run_release_pass(conn)

    assert (google.synced, onedrive.retried) == (2, 2)
    assert _onedrive_row(conn, req_obj)["state"] == "retry"
    assert (released.released, released.waiting) == (0, 2)
    assert (BUCKET, "comprovantes/2026/10/" + "a" * 32) in env["store"].objects
    assert _staging(conn, req_obj) == copy_registry.STAGED

    # Not due yet: the backoff holds the retry.
    assert drive_mirror.run_mirror_pass(conn, provider="onedrive").claimed == 0
    env["clock"].advance(drive_mirror.backoff_seconds(1) + 1)
    retried = drive_mirror.run_mirror_pass(conn, provider="onedrive")
    assert (retried.claimed, retried.synced) == (2, 2)

    released = staging_release.run_release_pass(conn)
    assert released.released == 2 and env["store"].objects == {}
    assert _staging(conn, req_obj) == copy_registry.RELEASED
    assert _onedrive_row(conn, req_obj)["verified_at"] is not None


# --- 3. release only after read-back; downloads keep working ---------------------------------


def test_a_copy_that_fails_its_read_back_blocks_the_release_and_is_sent_back(env):
    conn = env["conn"]
    req_obj, arq_obj = _seed(env)
    copy_registry.prepare(conn, now=T0)
    _mirror_both(conn)
    tampered = _onedrive_row(conn, req_obj)["file_id"]
    env["onedrive"].files[tampered]["content"] = b"%PDF-1.4 something else"

    result = staging_release.run_release_pass(conn)

    assert (result.released, result.unverified) == (1, 1)  # the ARQUIVO only
    assert (BUCKET, "comprovantes/2026/10/" + "a" * 32) in env["store"].objects
    assert _staging(conn, req_obj) == copy_registry.STAGED
    assert _onedrive_row(conn, req_obj)["state"] == "pending"  # re-mirrored, never released on faith
    assert _staging(conn, arq_obj) == copy_registry.RELEASED


def test_after_release_documents_are_served_from_verified_copies_with_fallback(env):
    conn = env["conn"]
    req_obj, arq_obj = _seed(env)
    copy_registry.prepare(conn, now=T0)
    _mirror_both(conn)
    assert staging_release.run_release_pass(conn).released == 2
    assert env["store"].objects == {}
    attachment = conn.execute("SELECT * FROM requisicao_arquivos WHERE storage_object_id = ?", (req_obj,)).fetchone()
    arquivo = conn.execute("SELECT * FROM admin_arquivos WHERE storage_object_id = ?", (arq_obj,)).fetchone()
    conn.commit()

    document = request_documents.canonical_document(conn, attachment, download=False)
    assert (document.url, document.content, document.mime_type) == (None, PDF, "application/pdf")
    with env["app"].test_request_context():
        response = document_copies.response(document, download=True)
        assert response.status_code == 200 and response.headers["Cache-Control"] == "private, no-store"
        response.direct_passthrough = False
        assert response.get_data() == PDF

    # Google fails: the OneDrive copy serves the same verified bytes.
    env["google"].fail_next("download", StorageTransientError("down"))
    assert arquivo_documents.canonical_document(conn, arquivo, download=True).content == PNG
    # A divergent copy is never served: the other one is.
    google_file = object_state(conn, req_obj)["file_id"]
    conn.commit()
    env["google"].files[google_file]["content"] = b"not the document"
    assert request_documents.canonical_document(conn, attachment, download=False).content == PDF
    # No readable copy left: unavailable (503), never a wrong or empty document.
    env["onedrive"].fail_next("download", StorageTransientError("down"))
    with pytest.raises(request_documents.RequestDocumentError) as caught:
        request_documents.canonical_document(conn, attachment, download=False)
    assert caught.value.status == 503


def test_documents_older_than_the_activation_keep_their_supabase_copy_until_backfilled(env):
    conn = env["conn"]
    conn.execute("DELETE FROM sgaa_ops.storage_copy_meta")
    conn.execute(
        "INSERT INTO sgaa_ops.storage_copy_meta (id, activated_at, first_object_id) VALUES (1, ?, 1000000)", (T0,)
    )
    conn.commit()
    req_obj, _arq_obj = _seed(env)  # created "before" the activation

    _mirror_both(conn)
    untouched = staging_release.run_release_pass(conn)
    assert (untouched.examined, untouched.released, len(env["store"].objects)) == (0, 0, 2)
    assert _staging(conn, req_obj) is None

    dry = staging_release.enroll_existing(conn, limit=1, apply=False)
    assert (dry["unenrolled"], dry["enrolled"], _staging(conn, req_obj)) == (2, 0, None)
    applied = staging_release.enroll_existing(conn, limit=1, apply=True)
    assert applied["enrolled"] == 1 and _staging(conn, req_obj) == copy_registry.STAGED

    _mirror_both(conn)
    assert staging_release.run_release_pass(conn).released == 1
    assert len(env["store"].objects) == 1  # the batch was bounded: the other one is still there
