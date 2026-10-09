# coding: utf-8
"""MP-1 slice 3 on real PostgreSQL (opt-in, ``SGAA_PG_TEST_URL``): legacy convergence.

Without ``SGAA_PG_TEST_URL`` the module skips (REAL-PG EVIDENCE: ABSENT).

E-PG1: dry run, apply and an idempotent rerun through the runtime adapter.

E-PG2 (separate connections; the waiting side is PROVEN waiting through
``pg_stat_activity`` before the holder commits -- no sleep is a correctness
proof): the convergence link holds the business row lock while a competitor
runs, and the reverse --

    converge x converge         exactly one object and one link per row
    converge x removal          a Google comprovante linked meanwhile is never
                                trashed; the removal refuses (CUSTODY_CHANGED)
    converge x request delete   the delete waits, re-reads, retires the object:
                                no active object is left unowned
    converge x ARQUIVOS delete  the legacy deletion transition waits, sees the
                                canonical reference, deletes canonically
    runtime first               the convergence finds the custody changed and
                                links nothing
"""

from __future__ import annotations

import threading
import time

import pytest
from flask import Flask

from tests.storage_mp1_pg_support import PG_URL

pytestmark = pytest.mark.skipif(
    not PG_URL, reason="SGAA_PG_TEST_URL is not configured -- REAL-PG EVIDENCE: ABSENT"
)

psycopg = pytest.importorskip("psycopg")

from app import comprovantes  # noqa: E402
from app.arquivos import delete_arquivo  # noqa: E402
from app.storage import custody_common  # noqa: E402
from app.storage import drive_mirror  # noqa: E402
from app.storage import legacy_convergence as convergence  # noqa: E402
from app.storage import storage_audit as audit  # noqa: E402
from tests.canonical_store_fake import InMemoryObjectStore  # noqa: E402
from tests.storage_mp1_pg_support import Registry, adapter, raw_connection  # noqa: E402
from tests.storage_mp1_support import (  # noqa: E402
    ADMIN_ID,
    BUCKET,
    STUDENT_USER_ID,
    T0,
    Clock,
    DriveTouched,
    FakeDrive,
    sha256,
)
from tests.storage_s3a_support import PDF, PNG  # noqa: E402

JOIN_TIMEOUT_SECONDS = 60
WAIT_PROBE_SECONDS = 20


@pytest.fixture(scope="module")
def registry():
    registry = Registry("converge")
    try:
        registry.provision_template()
        yield registry
    finally:
        assert registry.close() == 0


@pytest.fixture
def env(registry, monkeypatch, tmp_path):
    name, url = registry.create(template=registry.template)
    flask_app = Flask(__name__)
    store = InMemoryObjectStore()
    drive = FakeDrive()
    flask_app.extensions["canonical_object_store"] = store
    flask_app.extensions[drive_mirror.DRIVE_STORAGE_EXTENSION] = drive
    documents = tmp_path / "documentos"
    uploads = tmp_path / "uploads"
    documents.mkdir()
    uploads.mkdir()
    flask_app.config.update(DOCUMENTOS_ALUNOS_FOLDER=str(documents), UPLOAD_FOLDER=str(uploads))
    monkeypatch.setattr(custody_common, "utc_now_text", Clock(T0))
    conn = adapter(url)
    opened = [conn]

    def connect():
        extra = adapter(url)
        opened.append(extra)
        return extra

    try:
        with flask_app.app_context():
            yield dict(app=flask_app, conn=conn, store=store, drive=drive, connect=connect, url=url,
                       roots={"requisicao_arquivos": (str(documents), str(uploads)),
                              "admin_arquivos": (str(uploads),)},
                       documents=documents, uploads=uploads)
    finally:
        for item in opened:
            item.close()
        registry.drop(name)


def _local_request(env, relative="aluno-1/prova.pdf", content=PDF):
    path = env["documents"].joinpath(*relative.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return int(env["conn"].execute(
        "INSERT INTO requisicao_arquivos(requisicao_id,filename) VALUES(1,?) RETURNING id", (relative,)
    ).fetchone()[0])


def _google_request(env, file_id="drvpg1", content=PDF + b"%g"):
    env["drive"].add_file(parent_id="drvparent1", name="REQ.pdf", content=content, operation_key=f"op-{file_id}",
                          object_kind="comprovante", file_id=file_id)
    return int(env["conn"].execute(
        "INSERT INTO requisicao_arquivos(requisicao_id,filename,provider,storage_status,remote_file_id,"
        "remote_parent_id,original_filename,mime_type,size_bytes,sha256,uploaded_at,uploader_user_id,operation_key)"
        " VALUES(1,'REQ.pdf','google','active',?,'drvparent1','prova.pdf','application/pdf',?,?,"
        "'2026-09-01T10:00:00Z',?,?) RETURNING id",
        (file_id, len(content), sha256(content), ADMIN_ID, f"op-{file_id}"),
    ).fetchone()[0])


def _local_arquivo(env, relative="arquivos/legado.pdf", content=PNG):
    path = env["uploads"].joinpath(*relative.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return int(env["conn"].execute(
        "INSERT INTO admin_arquivos(titulo,filename) VALUES('Legado',?) RETURNING id", (relative,)
    ).fetchone()[0])


def _converge(env, conn=None, **kwargs):
    conn = conn or env["conn"]
    report = convergence.converge(
        conn, apply=kwargs.pop("apply", True), limit=50, store=env["store"], bucket=BUCKET,
        drive=drive_mirror.active_drive(conn), roots=env["roots"], **kwargs)
    conn.commit()
    return report


def _in_app(env, target):
    def run():
        with env["app"].app_context():
            target()

    return run


def _wait_until_blocked(url, *, timeout=WAIT_PROBE_SECONDS):
    """Prove a backend of this database is WAITING on a lock (no sleep as proof)."""
    database = url.rsplit("/", 1)[1].split("?", 1)[0]
    probe = raw_connection(PG_URL, autocommit=True)
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            waiting = probe.execute(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = %s AND wait_event_type = 'Lock'",
                (database,),
            ).fetchone()[0]
            if waiting:
                return True
            time.sleep(0.05)
        return False
    finally:
        probe.close()


def _hold_after_row_lock(monkeypatch, helper):
    """The NEXT convergence link pauses right after taking its business-row lock.

    The seam is the ``app.db`` lock helper the link calls first (bound in
    ``legacy_convergence``): the row stays locked, uncommitted, until released.
    """
    held, release = threading.Event(), threading.Event()
    real = getattr(convergence, helper)
    pending = {"first": True}

    def paused(conn, row_id):
        locked = real(conn, row_id)
        if pending.pop("first", False):
            held.set()
            assert release.wait(JOIN_TIMEOUT_SECONDS)
        return locked

    monkeypatch.setattr(convergence, helper, paused)
    return held, release


def _run_in_thread(env, target):
    outcome = {}

    def run():
        try:
            outcome["value"] = target()
        except BaseException as exc:  # recorded and asserted by the caller
            outcome["error"] = exc

    thread = threading.Thread(target=_in_app(env, run))
    thread.start()
    return thread, outcome


# --- E-PG1 ---------------------------------------------------------------------------


def test_dry_run_apply_and_rerun_on_postgres(env):
    rows = (_local_request(env), _google_request(env), _local_arquivo(env))
    env["conn"].commit()

    assert _converge(env, apply=False).as_dict()["totals"] == {"WOULD_CONVERGE": 3}
    assert env["conn"].execute("SELECT count(*) FROM storage_objects").fetchone()[0] == 0
    applied = _converge(env)
    assert applied.as_dict()["totals"] == {"CONVERGED": 3} and applied.synced_mirrors == 1
    digest = audit.reference_digest(env["conn"])
    assert _converge(env).as_dict()["totals"] == {}
    assert audit.reference_digest(env["conn"]) == digest
    report = audit.cross_check(env["conn"], store=env["store"], deep=True)
    assert report["verdict"]["converged"] is True and report["legacy_remaining"] == 0
    assert rows
    env["conn"].commit()


# --- E-PG2 ---------------------------------------------------------------------------


def test_converge_x_converge_links_each_row_once(env, monkeypatch):
    row_id = _local_request(env)
    env["conn"].commit()
    held, release = _hold_after_row_lock(monkeypatch, "lock_requisicao_arquivo")
    first, first_out = _run_in_thread(env, lambda: _converge(env, env["connect"]()))
    assert held.wait(JOIN_TIMEOUT_SECONDS)
    second, second_out = _run_in_thread(env, lambda: _converge(env, env["connect"]()))
    assert _wait_until_blocked(env["url"]), "the second convergence must wait on the row lock"
    release.set()
    for thread in (first, second):
        thread.join(JOIN_TIMEOUT_SECONDS)
        assert not thread.is_alive()
    assert "error" not in first_out and "error" not in second_out, (first_out, second_out)
    totals = [first_out["value"].as_dict()["totals"], second_out["value"].as_dict()["totals"]]
    assert sorted(totals, key=str) == sorted([{"CONVERGED": 1}, {"ALREADY_CONVERGED": 1}], key=str)
    assert env["conn"].execute("SELECT count(*) FROM storage_objects").fetchone()[0] == 1
    assert env["conn"].execute("SELECT storage_object_id FROM requisicao_arquivos WHERE id=?",
                               (row_id,)).fetchone()[0] is not None
    env["conn"].commit()


def test_converge_x_comprovante_removal_never_trashes_a_linked_google_file(env, monkeypatch):
    row_id = _google_request(env)
    env["conn"].commit()
    trashed = []
    monkeypatch.setattr(comprovantes, "resolve_google_storage",
                        lambda _conn: type("Drive", (), {"trash": lambda self, fid: trashed.append(fid),
                                                         "untrash": lambda self, fid: None})())
    held, release = _hold_after_row_lock(monkeypatch, "lock_requisicao_arquivo")
    converger, converge_out = _run_in_thread(env, lambda: _converge(env, env["connect"]()))
    assert held.wait(JOIN_TIMEOUT_SECONDS)
    remover_conn = env["connect"]()
    remover, remove_out = _run_in_thread(env, lambda: comprovantes.remove_comprovantes(
        remover_conn, request_id=1, attachment_ids=[row_id], actor_user_id=STUDENT_USER_ID))
    assert _wait_until_blocked(env["url"]), "the removal must wait on the convergence's row lock"
    release.set()
    for thread in (converger, remover):
        thread.join(JOIN_TIMEOUT_SECONDS)
        assert not thread.is_alive()
    assert converge_out["value"].as_dict()["totals"] == {"CONVERGED": 1}
    assert isinstance(remove_out.get("error"), comprovantes.ComprovanteError)
    assert remove_out["error"].code == "CUSTODY_CHANGED"
    assert trashed == []
    status = env["conn"].execute("SELECT storage_status FROM requisicao_arquivos WHERE id=?", (row_id,)).fetchone()
    assert status[0] == "active"
    env["conn"].commit()


def test_converge_x_request_delete_leaves_no_unowned_active_object(env, monkeypatch):
    _local_request(env)
    env["conn"].commit()
    monkeypatch.setattr(comprovantes, "resolve_google_storage", lambda _conn: (_ for _ in ()).throw(
        DriveTouched("google")))
    held, release = _hold_after_row_lock(monkeypatch, "lock_requisicao_arquivo")
    converger, converge_out = _run_in_thread(env, lambda: _converge(env, env["connect"]()))
    assert held.wait(JOIN_TIMEOUT_SECONDS)
    deleter_conn = env["connect"]()
    deleter, delete_out = _run_in_thread(env, lambda: comprovantes.delete_request_with_comprovantes(
        deleter_conn, request_id=1, actor_user_id=STUDENT_USER_ID))
    assert _wait_until_blocked(env["url"]), "the request delete must wait on the convergence's row lock"
    release.set()
    for thread in (converger, deleter):
        thread.join(JOIN_TIMEOUT_SECONDS)
        assert not thread.is_alive()
    assert "error" not in delete_out, delete_out
    assert converge_out["value"].as_dict()["totals"] == {"CONVERGED": 1}
    conn = env["conn"]
    assert conn.execute("SELECT count(*) FROM requisicoes WHERE id=1").fetchone()[0] == 0
    report = audit.cross_check(conn)
    assert report["references"]["ACTIVE_OBJECT_UNOWNED"] == 0
    assert conn.execute("SELECT lifecycle_state FROM storage_objects").fetchone()[0] == "retired"
    conn.commit()


def test_converge_x_arquivo_delete_deletes_canonically(env, monkeypatch):
    row_id = _local_arquivo(env)
    env["conn"].commit()
    held, release = _hold_after_row_lock(monkeypatch, "lock_admin_arquivo")
    converger, converge_out = _run_in_thread(env, lambda: _converge(env, env["connect"]()))
    assert held.wait(JOIN_TIMEOUT_SECONDS)
    deleter_conn = env["connect"]()
    deleter, delete_out = _run_in_thread(env, lambda: delete_arquivo(
        deleter_conn, row_id, upload_root=str(env["uploads"])))
    assert _wait_until_blocked(env["url"]), "the deletion transition must wait on the convergence's row lock"
    release.set()
    for thread in (converger, deleter):
        thread.join(JOIN_TIMEOUT_SECONDS)
        assert not thread.is_alive()
    assert "error" not in delete_out, delete_out
    conn = env["conn"]
    assert conn.execute("SELECT count(*) FROM admin_arquivos WHERE id=?", (row_id,)).fetchone()[0] == 0
    assert conn.execute("SELECT lifecycle_state FROM storage_objects").fetchone()[0] == "retired"
    assert env["uploads"].joinpath("arquivos", "legado.pdf").read_bytes() == PNG
    conn.commit()


def test_runtime_first_then_converge_links_nothing(env):
    row_id = _local_arquivo(env)
    env["conn"].commit()
    delete_arquivo(env["connect"](), row_id, upload_root=str(env["uploads"]))

    report = _converge(env)

    assert report.as_dict()["totals"] == {}
    assert env["conn"].execute("SELECT count(*) FROM storage_objects").fetchone()[0] == 0
    env["conn"].commit()
