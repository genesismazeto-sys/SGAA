# coding: utf-8
"""MP-1 slice 3: legacy convergence into canonical storage (SQLite lane, deterministic fakes).

Contract (``docs/specs/MP-1-storage-convergence.md`` §3, D6-D10, D14, I2, I4,
I5): a dry run reads and proves every eligible legacy source and writes
nothing; ``apply`` uploads each to its deterministic key (no upsert), proves
the stored bytes, and links the row under its lock after re-checking its
custody; a rerun changes nothing; an interrupted run is resumed by adoption;
different bytes at the key are refused; a Google row adopts its verified
legacy Drive file as its synced mirror; legacy bytes are only ever read.
"""

from __future__ import annotations

import io
import json
import os

import pytest

from app.storage import drive_mirror
from app.storage import legacy_convergence as convergence
from app.storage import storage_audit as audit
from app.storage.cli import EXIT_NOT_CONVERGED, EXIT_NOT_RUNNABLE, EXIT_OK, EXIT_USAGE, main as cli_main
from tests.storage_mp1_support import (
    ACCOUNT_KEY,
    ADMIN_ID,
    BUCKET,
    T0,
    Tripwire,
    object_state,
    sha256,
    sqlite_storage_env,
)
from tests.storage_s3a_support import PDF, PNG


@pytest.fixture
def env(tmp_path, monkeypatch):
    with sqlite_storage_env(tmp_path, monkeypatch) as context:
        context.drive.files.clear()
        monkeypatch.setenv("SGAA_STORAGE_BUCKET", BUCKET)
        context.roots = {
            "requisicao_arquivos": (str(tmp_path / "documentos"), str(tmp_path / "uploads")),
            "admin_arquivos": (str(tmp_path / "uploads"),),
        }
        for root in ("documentos", "uploads"):
            (tmp_path / root).mkdir(exist_ok=True)
        context.app.config["DOCUMENTOS_ALUNOS_FOLDER"] = context.roots["requisicao_arquivos"][0]
        context.app.config["UPLOAD_FOLDER"] = context.roots["admin_arquivos"][0]
        original_delete = context.store.delete

        def tripwire_delete(*args, **kwargs):
            context.store.calls.append("delete")
            raise Tripwire("canonical delete")

        context.store.delete = tripwire_delete
        context.original_delete = original_delete
        yield context


def _write(root, relative, content):
    path = os.path.join(root, *relative.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(content)
    return path


def _local_request(env, content=PDF, relative="aluno-1/comprovantes/prova.pdf", *, root_index=0):
    if content is not None:
        _write(env.roots["requisicao_arquivos"][root_index], relative, content)
    return int(env.conn.execute(
        "INSERT INTO requisicao_arquivos(requisicao_id,filename) VALUES(1,?) RETURNING id", (relative,)
    ).fetchone()[0])


def _local_arquivo(env, content=PDF, relative="arquivos/manual-legado.pdf"):
    if content is not None:
        _write(env.roots["admin_arquivos"][0], relative, content)
    return int(env.conn.execute(
        "INSERT INTO admin_arquivos(titulo,filename,original_filename) VALUES('Manual',?,'manual.pdf') RETURNING id",
        (relative,),
    ).fetchone()[0])


def _google_request(env, content=PDF, *, file_id="drvlegacy1", parent="drvparent1", recorded=None, mime=None):
    env.drive.add_file(parent_id=parent, name="REQ-legacy.pdf", content=content, operation_key=f"op-{file_id}",
                       object_kind="comprovante", file_id=file_id)
    recorded = content if recorded is None else recorded
    return int(env.conn.execute(
        "INSERT INTO requisicao_arquivos(requisicao_id,filename,provider,storage_status,remote_file_id,"
        "remote_parent_id,original_filename,mime_type,size_bytes,sha256,uploaded_at,uploader_user_id,operation_key)"
        " VALUES(1,'REQ-000001__legado.pdf','google','active',?,?,'prova.pdf',?,?,?,'2026-09-01T10:00:00Z',?,?)"
        " RETURNING id",
        (file_id, parent, mime or "application/pdf", len(recorded), sha256(recorded), ADMIN_ID, f"op-{file_id}"),
    ).fetchone()[0])


def _google_arquivo(env, content=PNG, *, file_id="drvlegacy2"):
    env.drive.add_file(parent_id="drvparent2", name="ARQ-legacy.png", content=content,
                       operation_key=f"op-{file_id}", object_kind="arquivo", file_id=file_id)
    return int(env.conn.execute(
        "INSERT INTO admin_arquivos(titulo,filename,original_filename,provider,storage_status,remote_file_id,"
        "remote_parent_id,mime_type,size_bytes,sha256,uploaded_at,uploader_user_id,operation_key)"
        " VALUES('Manual G','ARQ-legacy.png','manual.png','google','active',?,'drvparent2','image/png',?,?,?,?,?)"
        " RETURNING id",
        (file_id, len(content), sha256(content), T0, ADMIN_ID, f"op-{file_id}"),
    ).fetchone()[0])


def _converge(env, *, apply=True, limit=50, drive="active", tables=convergence.TABLES):
    if drive == "active":
        drive = drive_mirror.active_drive(env.conn)
    return convergence.converge(env.conn, apply=apply, limit=limit, tables=tables, store=env.store,
                                bucket=BUCKET, drive=drive, roots=env.roots)


def _link(env, table, row_id):
    return env.conn.execute(
        f"SELECT o.id, o.storage_key, o.sha256, o.size_bytes, o.mime_type, o.origin, o.uploader_user_id"
        f" FROM {table} r JOIN storage_objects o ON o.id = r.storage_object_id WHERE r.id = ?", (row_id,)
    ).fetchone()


def _seed_all(env):
    rows = {
        "local_request": _local_request(env, PDF),
        "local_request_upload_root": _local_request(env, PNG, "antigo/foto.png", root_index=1),
        "local_arquivo": _local_arquivo(env, PDF + b"%arq"),
        "google_request": _google_request(env, PDF + b"%goog"),
        "google_arquivo": _google_arquivo(env, PNG),
    }
    env.conn.commit()
    return rows


# ---------------------------------------------------------------------------
# dry run / apply / rerun
# ---------------------------------------------------------------------------


def test_dry_run_proves_every_source_and_writes_nothing(env):
    _seed_all(env)

    report = _converge(env, apply=False)

    assert report.as_dict()["totals"] == {"WOULD_CONVERGE": 5}
    assert report.clean and env.store.objects == {}
    assert env.conn.execute("SELECT count(*) FROM storage_objects").fetchone()[0] == 0
    assert "upload" not in env.store.calls


def test_apply_converges_every_eligible_row_with_verified_bytes(env):
    rows = _seed_all(env)

    report = _converge(env)

    assert report.as_dict()["totals"] == {"CONVERGED": 5} and report.synced_mirrors == 2
    expected = {
        ("requisicao_arquivos", "local_request"): (PDF, "application/pdf", "migrated_local_legacy", None),
        ("requisicao_arquivos", "local_request_upload_root"): (PNG, "image/png", "migrated_local_legacy", None),
        ("admin_arquivos", "local_arquivo"): (PDF + b"%arq", "application/pdf", "migrated_local_legacy", None),
        ("requisicao_arquivos", "google_request"): (PDF + b"%goog", "application/pdf", "migrated_google", ADMIN_ID),
        ("admin_arquivos", "google_arquivo"): (PNG, "image/png", "migrated_google", ADMIN_ID),
    }
    for (table, label), (content, mime, origin, uploader) in expected.items():
        link = _link(env, table, rows[label])
        directory = "legacy/comprovantes" if table == "requisicao_arquivos" else "legacy/arquivos"
        assert link[1] == f"{directory}/{rows[label]}"
        assert (link[2], link[3], link[4], link[5], link[6]) == (sha256(content), len(content), mime, origin, uploader)
        assert env.store.objects[(BUCKET, link[1])] == (content, mime)
    google = object_state(env.conn, _link(env, "requisicao_arquivos", rows["google_request"])[0])
    assert (google["state"], google["file_id"], google["parent_id"], google["account_key"]) == (
        "synced", "drvlegacy1", "drvparent1", ACCOUNT_KEY)
    local = object_state(env.conn, _link(env, "admin_arquivos", rows["local_arquivo"])[0])
    assert (local["state"], local["file_id"]) == ("pending", None)
    # Provider and legacy locator are kept as provenance and residue.
    assert env.conn.execute("SELECT provider, remote_file_id, storage_status FROM requisicao_arquivos WHERE id=?",
                            (rows["google_request"],)).fetchone()[:] == ("google", "drvlegacy1", "active")
    verdict = audit.cross_check(env.conn, store=env.store, deep=True)["verdict"]
    assert verdict == {"references_consistent": True, "storage_consistent": True, "bucket_clean": True,
                       "mirrors_verified": None, "legacy_converged": True, "mirror_complete": False,
                       "converged": True}


def test_rerun_changes_nothing(env):
    _seed_all(env)
    _converge(env)
    digest = audit.reference_digest(env.conn)
    uploads = env.store.calls.count("upload")

    again = _converge(env)

    assert again.as_dict()["totals"] == {} and again.clean
    assert env.store.calls.count("upload") == uploads
    assert audit.reference_digest(env.conn) == digest


def test_limit_and_table_filter_bound_a_run(env):
    _seed_all(env)
    first = _converge(env, limit=1, tables=("admin_arquivos",))
    assert first.as_dict()["totals"] == {"CONVERGED": 1}
    assert audit.census(env.conn)["documents"]["admin_arquivos"]["unconverged"] == 1
    assert audit.census(env.conn)["documents"]["requisicao_arquivos"]["unconverged"] == 3


def test_interrupted_run_is_resumed_by_adopting_its_own_upload(env, monkeypatch):
    rows = _seed_all(env)

    class _Death(BaseException):
        pass

    real_link = convergence._link
    calls = []

    def die_after_upload(conn, candidate, **kwargs):
        calls.append(candidate.row_id)
        if len(calls) == 2:
            raise _Death()
        return real_link(conn, candidate, **kwargs)

    monkeypatch.setattr(convergence, "_link", die_after_upload)
    with pytest.raises(_Death):
        _converge(env)
    monkeypatch.setattr(convergence, "_link", real_link)
    assert env.conn.execute("SELECT count(*) FROM storage_objects").fetchone()[0] == 1
    assert len(env.store.objects) == 2  # one linked, one uploaded but unlinked

    resumed = _converge(env)

    assert resumed.as_dict()["totals"] == {"CONVERGED": 4} and resumed.adopted_targets == 1
    assert audit.cross_check(env.conn, store=env.store, deep=True)["verdict"]["converged"] is True
    assert all(_link(env, table, row_id) for table, row_id in (
        ("requisicao_arquivos", rows["local_request"]), ("admin_arquivos", rows["google_arquivo"])))


def test_different_bytes_at_the_key_are_refused_never_overwritten(env):
    row_id = _local_arquivo(env, PDF)
    env.conn.commit()
    env.store.objects[(BUCKET, f"legacy/arquivos/{row_id}")] = (PDF + b"other", "application/pdf")

    report = _converge(env)

    assert report.as_dict()["totals"] == {"TARGET_CONFLICT": 1} and not report.clean
    assert env.store.objects[(BUCKET, f"legacy/arquivos/{row_id}")][0] == PDF + b"other"
    assert _link(env, "admin_arquivos", row_id) is None


# ---------------------------------------------------------------------------
# source classes
# ---------------------------------------------------------------------------


def test_every_unusable_source_is_classified_and_skipped(env):
    big = b"%PDF-1.4\n" + b"0" * (16 * 1024 * 1024)
    rows = {
        "SOURCE_MISSING": _local_request(env, None, "aluno-1/sumiu.pdf"),
        "SOURCE_EMPTY": _local_request(env, b"", "aluno-1/vazio.pdf"),
        "SOURCE_UNSUPPORTED": _local_request(env, b"MZ not a document", "aluno-1/x.exe"),
        "SOURCE_TOO_LARGE": _local_arquivo(env, big, "arquivos/grande.pdf"),
        "SOURCE_LOCATOR_INVALID": _local_arquivo(env, None, "../fora/raiz.pdf"),
        "SOURCE_INTEGRITY_MISMATCH": _google_request(env, PDF, file_id="drvbad1", recorded=PDF + b"x"),
        "SOURCE_MIME_MISMATCH": _google_request(env, PDF, file_id="drvbad2", mime="image/png"),
    }
    rows["SOURCE_UNAVAILABLE"] = _google_request(env, PDF + b"g", file_id="drvgone3")
    env.drive.files.pop("drvgone3")
    env.conn.commit()

    report = _converge(env)

    assert report.as_dict()["totals"] == {code: 1 for code in rows}
    assert env.conn.execute("SELECT count(*) FROM storage_objects").fetchone()[0] == 0
    assert env.store.objects == {}


def test_google_rows_wait_for_drive_while_local_rows_converge(env):
    rows = _seed_all(env)

    report = _converge(env, drive=None)

    assert report.as_dict()["totals"] == {"CONVERGED": 3, "DRIVE_UNAVAILABLE": 2}
    assert _link(env, "requisicao_arquivos", rows["google_request"]) is None


def test_google_row_with_an_unusable_parent_converges_with_a_pending_mirror(env):
    """No adoptable Drive locator: the canonical bytes converge, the mirror worker places them later."""
    row_id = _google_request(env, PDF, parent="drv parent with spaces")
    env.conn.commit()

    report = _converge(env)

    assert report.as_dict()["totals"] == {"CONVERGED": 1} and report.synced_mirrors == 0
    state = object_state(env.conn, _link(env, "requisicao_arquivos", row_id)[0])
    assert (state["state"], state["file_id"], state["account_key"]) == ("pending", None, None)


def test_blocked_rows_are_never_touched(env):
    _local_arquivo(env, PDF)
    env.conn.execute("UPDATE admin_arquivos SET storage_status='deletion_pending',cleanup_started_at=?", (T0,))
    _google_request(env, PDF, file_id="drvpend")
    env.conn.execute("UPDATE requisicao_arquivos SET storage_status='pending'")
    env.conn.commit()

    assert _converge(env).as_dict()["totals"] == {}
    assert env.store.calls == [] and "download" not in env.drive.calls


# ---------------------------------------------------------------------------
# custody races: the link re-checks under the row lock
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("change", [
    "DELETE FROM requisicao_arquivos WHERE id=?",
    "UPDATE requisicao_arquivos SET filename='aluno-1/outra.pdf' WHERE id=?",
])
def test_custody_changed_between_read_and_link_is_not_linked(env, monkeypatch, change):
    row_id = _local_request(env, PDF)
    env.conn.commit()
    real_store = convergence._store_target

    def change_after_upload(store, bucket, key, source):
        adopted = real_store(store, bucket, key, source)
        env.conn.execute(change, (row_id,))
        env.conn.commit()
        return adopted

    monkeypatch.setattr(convergence, "_store_target", change_after_upload)
    report = _converge(env)

    assert report.as_dict()["totals"] == {"CUSTODY_CHANGED": 1}
    assert env.conn.execute("SELECT count(*) FROM storage_objects").fetchone()[0] == 0
    bucket = audit.cross_check(env.conn, store=env.store, buckets=(BUCKET,))["bucket"]
    assert bucket["UNREFERENCED_OBJECT"] == 1  # the lost race leaves bucket garbage, never a bad reference


def test_row_converged_concurrently_counts_as_converged_once(env, monkeypatch):
    row_id = _local_request(env, PDF)
    env.conn.commit()
    real_store = convergence._store_target
    rival = {}

    def rival_first(store, bucket, key, source):
        adopted = real_store(store, bucket, key, source)
        if not rival:
            monkeypatch.setattr(convergence, "_store_target", real_store)
            rival["report"] = _converge(env)
        return adopted

    monkeypatch.setattr(convergence, "_store_target", rival_first)
    report = _converge(env)

    assert rival["report"].as_dict()["totals"] == {"CONVERGED": 1}
    assert report.as_dict()["totals"] == {"ALREADY_CONVERGED": 1} and report.clean
    assert env.conn.execute("SELECT count(*) FROM storage_objects").fetchone()[0] == 1


def test_a_drive_file_already_owned_by_another_object_is_refused(env):
    row_id = _google_request(env, PDF, file_id="drvshared")
    env.conn.execute(
        "INSERT INTO storage_objects(storage_backend,storage_bucket,storage_key,sha256,size_bytes,mime_type,origin,"
        "content_verified_at,created_at,drive_sync_state,drive_file_id,drive_account_key,drive_synced_at,"
        "uploader_user_id) VALUES('supabase',?,'comprovantes/2026/10/" + "5" * 32 + "',?,?,'application/pdf',"
        "'direct_upload',?,?,'synced','drvshared',?,?,?)",
        (BUCKET, sha256(b"x"), 1, T0, T0, ACCOUNT_KEY, T0, ADMIN_ID))
    env.conn.commit()

    report = _converge(env)

    assert report.as_dict()["totals"] == {"LINK_REFUSED": 1}
    assert _link(env, "requisicao_arquivos", row_id) is None


# ---------------------------------------------------------------------------
# I2 / I5
# ---------------------------------------------------------------------------


def test_legacy_bytes_are_only_read(env):
    rows = _seed_all(env)
    local = os.path.join(env.roots["requisicao_arquivos"][0], "aluno-1", "comprovantes", "prova.pdf")
    before = open(local, "rb").read()

    _converge(env)

    assert open(local, "rb").read() == before
    assert not {"trash", "untrash", "delete"} & set(env.drive.calls)
    assert all(not item["trashed"] for item in env.drive.files.values())
    assert "delete" not in env.store.calls
    assert rows


def test_report_and_cli_are_value_free(env):
    _seed_all(env)
    out = io.StringIO()
    env.conn.commit()
    code = cli_main(["converge"], app=env.app, out=out)
    dry = json.loads(out.getvalue())
    assert code == EXIT_OK and dry["totals"] == {"WOULD_CONVERGE": 5} and dry["apply"] is False

    out = io.StringIO()
    code = cli_main(["converge", "--apply", "--table", "admin_arquivos", "--limit", "10"], app=env.app, out=out)
    applied = json.loads(out.getvalue())
    assert code == EXIT_OK and applied["totals"] == {"CONVERGED": 2}

    text = json.dumps([dry, applied])
    for forbidden in ("prova.pdf", "aluno-1", "manual", "drvlegacy", "drvparent", "legacy/", ACCOUNT_KEY, BUCKET):
        assert forbidden not in text, forbidden


def test_cli_converge_exit_codes(env, monkeypatch):
    _local_request(env, None, "aluno-1/sumiu.pdf")
    env.conn.commit()
    out = io.StringIO()
    assert cli_main(["converge", "--apply"], app=env.app, out=out) == EXIT_NOT_CONVERGED
    assert json.loads(out.getvalue())["totals"] == {"SOURCE_MISSING": 1}
    assert cli_main(["converge", "--table", "nope"], app=env.app, out=io.StringIO()) == EXIT_USAGE
    env.app.extensions.pop("canonical_object_store")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    assert cli_main(["converge", "--apply"], app=env.app, out=io.StringIO()) == EXIT_NOT_RUNNABLE


def test_a_google_row_is_never_adopted_into_an_account_that_is_no_longer_active(env, monkeypatch):
    """The bytes converge; the mirror is left pending when the active account changed meanwhile."""
    row_id = _google_request(env, PDF)
    env.conn.commit()
    drive = drive_mirror.active_drive(env.conn)
    monkeypatch.setattr(drive_mirror, "still_active", lambda _conn, _drive: False)

    report = convergence.converge(env.conn, apply=True, limit=5, store=env.store, bucket=BUCKET, drive=drive,
                                  roots=env.roots)

    assert report.as_dict()["totals"] == {"CONVERGED": 1} and report.synced_mirrors == 0
    state = object_state(env.conn, _link(env, "requisicao_arquivos", row_id)[0])
    assert (state["state"], state["file_id"], state["account_key"]) == ("pending", None, None)


def test_the_cursor_moves_past_rows_that_keep_failing(env):
    failing = [_local_request(env, None, f"aluno-1/sumiu-{index}.pdf") for index in range(3)]
    good = _local_request(env, PDF, "aluno-1/ok.pdf")
    env.conn.commit()

    first = _converge(env, limit=3, tables=("requisicao_arquivos",))
    assert first.as_dict()["totals"] == {"SOURCE_MISSING": 3}
    assert first.last_row_id == {"requisicao_arquivos": failing[-1]}
    assert _converge(env, limit=3, tables=("requisicao_arquivos",)).as_dict()["totals"] == {"SOURCE_MISSING": 3}

    report = convergence.converge(env.conn, apply=True, limit=3, tables=("requisicao_arquivos",), store=env.store,
                                  bucket=BUCKET, drive=None, roots=env.roots, after_id=first.last_row_id[
                                      "requisicao_arquivos"])
    assert report.as_dict()["totals"] == {"CONVERGED": 1}
    assert _link(env, "requisicao_arquivos", good) is not None


def test_cli_after_id_needs_a_table(env):
    assert cli_main(["converge", "--after-id", "5"], app=env.app, out=io.StringIO()) == EXIT_USAGE
    out = io.StringIO()
    assert cli_main(["converge", "--table", "admin_arquivos", "--after-id", "5"], app=env.app, out=out) == EXIT_OK
    assert json.loads(out.getvalue())["totals"] == {}


def test_an_unreadable_local_file_is_classified_not_fatal(env, monkeypatch):
    blocked = _local_request(env, PDF, "aluno-1/bloqueado.pdf")
    fine = _local_request(env, PNG, "aluno-1/livre.png")
    env.conn.commit()
    real_getsize = os.path.getsize

    def getsize(path):
        if path.endswith("bloqueado.pdf"):
            raise PermissionError("denied")
        return real_getsize(path)

    monkeypatch.setattr(convergence.os.path, "getsize", getsize)
    report = _converge(env)

    assert report.as_dict()["totals"] == {"SOURCE_UNREADABLE": 1, "CONVERGED": 1}
    assert _link(env, "requisicao_arquivos", blocked) is None
    assert _link(env, "requisicao_arquivos", fine) is not None
