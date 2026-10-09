# coding: utf-8
"""MP-1 slice 3: converged legacy rows are canonical custody in every runtime path (SQLite lane).

Contract (``docs/specs/MP-1-storage-convergence.md`` D6, D9, D14, I1, I2): a
legacy row that carries ``storage_object_id`` is read, removed, deleted and
replaced exactly like a canonical row -- with NO Google call (every Google
entry point is a tripwire) -- and its legacy bytes are never trashed or
unlinked.  A runtime path that read a row BEFORE it converged never acts on
it as legacy custody afterwards: it refuses (retryable) or takes the
canonical path.
"""

from __future__ import annotations

import os

import pytest

import main
from app import comprovantes
from app.arquivos import delete_arquivo
from app.storage import legacy_convergence as convergence
from tests.storage_mp1_support import (
    BUCKET,
    STUDENT_USER_ID,
    T0,
    DriveTouched,
    insert_object,
    sha256,
    sqlite_storage_env,
)
from tests.storage_s3a_support import PDF, PNG
from tests.storage_s3b_support import seed_google_arquivo, seed_local_arquivo
from tests.test_storage_s3b_arquivos import (  # noqa: F401  (the S3-B HTTP environment and helpers)
    _arquivo,
    _as_admin,
    _as_student,
    _db,
    _object,
    _replace_through_protocol,
    env,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _converge_row(conn, store, table, row_id, content, *, origin, mime="application/pdf"):
    """Link a legacy row the way convergence does (its owner is proven elsewhere)."""
    key = convergence.canonical_key(table, row_id)
    object_id = insert_object(conn, key=key, content=content, mime=mime, origin=origin, uploader=None)
    conn.execute(f"UPDATE {table} SET storage_object_id=? WHERE id=?", (object_id, row_id))
    store.objects[(BUCKET, key)] = (content, mime)
    return object_id


def _object_state(conn, object_id):
    return conn.execute("SELECT lifecycle_state FROM storage_objects WHERE id=?", (object_id,)).fetchone()[0]


# ===========================================================================
# ARQUIVOS (the S3-B HTTP environment: Google tripwires armed)
# ===========================================================================


def _converged_arquivo(env, kind):
    with main.app.app_context():
        conn = _db()
        if kind == "local":
            row_id = seed_local_arquivo(conn, env["upload_root"], content=PDF, filename="arquivos/conv.pdf")
            origin = "migrated_local_legacy"
        else:
            row_id = seed_google_arquivo(conn, uploader=env["admin_id"], now=T0, remote_file_id="drvconv1")
            origin = "migrated_google"
        object_id = _converge_row(conn, env["store"], "admin_arquivos", row_id, PDF, origin=origin)
        conn.commit()
    return row_id, object_id


@pytest.mark.parametrize("kind", ["local", "google"])
def test_converged_arquivo_reads_are_signed_canonical_redirects(env, kind):
    row_id, _object_id = _converged_arquivo(env, kind)
    _as_admin(env)
    response = env["client"].get(f"/admin/arquivos/{row_id}/visualizar")
    assert response.status_code == 302 and response.headers["Location"].startswith("memory://")
    _as_student(env)
    for path in (f"/aluno/arquivos/ver/{row_id}", f"/aluno/arquivos/download/{row_id}"):
        response = env["client"].get(path)
        assert response.status_code == 302 and response.headers["Location"].startswith("memory://"), path
    assert env["google_calls"] == []


@pytest.mark.parametrize("kind", ["local", "google"])
def test_converged_arquivo_delete_retires_canonically_and_keeps_legacy_bytes(env, kind):
    row_id, object_id = _converged_arquivo(env, kind)
    _as_admin(env)
    response = env["client"].post(f"/admin/arquivos/{row_id}/deletar")
    assert response.status_code == 302
    assert _arquivo(row_id) is None and _object(object_id)["lifecycle_state"] == "retired"
    if kind == "local":
        assert open(os.path.join(env["upload_root"], "arquivos", "conv.pdf"), "rb").read() == PDF
    assert env["google_calls"] == []
    assert "delete" not in env["store"].calls


@pytest.mark.parametrize("kind", ["local", "google"])
def test_converged_arquivo_replacement_retires_the_migrated_object_and_keeps_the_residue(env, kind):
    row_id, object_id = _converged_arquivo(env, kind)
    _as_admin(env)
    _submission, intent_id, response = _replace_through_protocol(env, row_id)
    assert response.status_code == 302, response
    row = _arquivo(row_id)
    assert row["provider"] == "supabase" and row["storage_object_id"] not in (None, object_id)
    expected = ("local_legacy", "arquivos/conv.pdf") if kind == "local" else ("google", "drvconv1")
    assert (row["prior_provider"], row["prior_locator"]) == expected
    assert _object(object_id)["lifecycle_state"] == "retired"
    assert env["google_calls"] == []


def test_legacy_delete_that_finds_the_row_converged_deletes_canonically(env):
    """The view dispatched on a row read BEFORE convergence linked it."""
    with main.app.app_context():
        conn = _db()
        row_id = seed_local_arquivo(conn, env["upload_root"], content=PDF, filename="arquivos/race.pdf")
        object_id = _converge_row(conn, env["store"], "admin_arquivos", row_id, PDF, origin="migrated_local_legacy")
        conn.commit()
        delete_arquivo(conn, row_id, upload_root=env["upload_root"])
    assert _arquivo(row_id) is None and _object(object_id)["lifecycle_state"] == "retired"
    assert open(os.path.join(env["upload_root"], "arquivos", "race.pdf"), "rb").read() == PDF
    assert env["google_calls"] == []


# ===========================================================================
# request documents (owner level; every Google resolution is a tripwire)
# ===========================================================================


@pytest.fixture
def req(tmp_path, monkeypatch):
    with sqlite_storage_env(tmp_path, monkeypatch) as context:
        documents = tmp_path / "documentos"
        documents.mkdir()
        context.app.config["DOCUMENTOS_ALUNOS_FOLDER"] = str(documents)
        context.app.config["UPLOAD_FOLDER"] = str(tmp_path / "uploads")
        context.documents = documents
        context.google_calls = []

        def tripwire(_conn):
            context.google_calls.append("resolve_google_storage")
            raise DriveTouched("resolve_google_storage")

        monkeypatch.setattr(comprovantes, "resolve_google_storage", tripwire)
        yield context


def _local_row(req, relative, content=PDF):
    path = req.documents.joinpath(*relative.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    row_id = int(req.conn.execute(
        "INSERT INTO requisicao_arquivos(requisicao_id,filename) VALUES(1,?) RETURNING id", (relative,)
    ).fetchone()[0])
    return row_id, path


def _google_row(req, file_id, content=PDF):
    return int(req.conn.execute(
        "INSERT INTO requisicao_arquivos(requisicao_id,filename,provider,storage_status,remote_file_id,"
        "remote_parent_id,original_filename,mime_type,size_bytes,sha256,uploaded_at,uploader_user_id,operation_key)"
        " VALUES(1,'REQ-legado.pdf','google','active',?,'drvparent1','prova.pdf','application/pdf',?,?,"
        "'2026-09-01T10:00:00Z',1,?) RETURNING id",
        (file_id, len(content), sha256(content), f"op-{file_id}"),
    ).fetchone()[0])


def _converged_requests(req):
    local_id, local_path = _local_row(req, "aluno-1/conv.pdf")
    google_id = _google_row(req, "drvreqconv")
    local_obj = _converge_row(req.conn, req.store, "requisicao_arquivos", local_id, PDF, origin="migrated_local_legacy")
    google_obj = _converge_row(req.conn, req.store, "requisicao_arquivos", google_id, PDF, origin="migrated_google")
    req.conn.commit()
    return (local_id, local_obj, local_path), (google_id, google_obj)


def test_converged_comprovante_removal_is_canonical_and_keeps_legacy_bytes(req):
    (local_id, local_obj, local_path), (google_id, google_obj) = _converged_requests(req)
    plain_id, plain_path = _local_row(req, "aluno-1/plain.pdf")
    req.conn.commit()

    removed = comprovantes.remove_comprovantes(req.conn, request_id=1, attachment_ids=[local_id, google_id, plain_id],
                                               actor_user_id=STUDENT_USER_ID)

    assert sorted(removed) == sorted([local_id, google_id, plain_id])
    remaining = {row[0] for row in req.conn.execute("SELECT id FROM requisicao_arquivos").fetchall()}
    assert remaining.isdisjoint({local_id, google_id, plain_id})
    assert {_object_state(req.conn, local_obj), _object_state(req.conn, google_obj)} == {"retired"}
    assert local_path.read_bytes() == PDF          # converged: legacy residue untouched
    assert not plain_path.exists()                 # unconverged legacy: the legacy contract, unchanged
    assert req.google_calls == []
    assert "delete" not in req.store.calls


def test_request_delete_retires_converged_objects_without_google(req):
    (_local_id, local_obj, local_path), (_google_id, google_obj) = _converged_requests(req)

    comprovantes.delete_request_with_comprovantes(req.conn, request_id=1, actor_user_id=STUDENT_USER_ID)

    assert req.conn.execute("SELECT count(*) FROM requisicoes WHERE id=1").fetchone()[0] == 0
    assert {_object_state(req.conn, local_obj), _object_state(req.conn, google_obj)} == {"retired"}
    assert local_path.read_bytes() == PDF
    assert req.google_calls == []


def test_removal_of_a_google_row_converged_after_it_was_read_is_refused_untouched(req, monkeypatch):
    google_id = _google_row(req, "drvlate")
    req.conn.commit()
    real_rows = comprovantes._removal_rows

    def read_then_converge(conn, request_id, attachment_ids):
        rows = real_rows(conn, request_id, attachment_ids)
        _converge_row(conn, req.store, "requisicao_arquivos", google_id, PDF, origin="migrated_google")
        conn.commit()
        return rows

    monkeypatch.setattr(comprovantes, "_removal_rows", read_then_converge)
    monkeypatch.setattr(comprovantes, "resolve_google_storage", lambda _conn: object())  # never used

    with pytest.raises(comprovantes.ComprovanteError) as refused:
        comprovantes.remove_comprovantes(req.conn, request_id=1, attachment_ids=[google_id],
                                         actor_user_id=STUDENT_USER_ID)

    assert refused.value.code == "CUSTODY_CHANGED" and refused.value.retryable
    row = req.conn.execute("SELECT storage_status, storage_object_id FROM requisicao_arquivos WHERE id=?",
                           (google_id,)).fetchone()
    assert row[0] == "active" and row[1] is not None


def test_removal_of_a_local_row_converged_after_it_was_read_keeps_row_and_file(req, monkeypatch):
    local_id, local_path = _local_row(req, "aluno-1/late.pdf")
    req.conn.commit()
    real_rows = comprovantes._removal_rows

    def read_then_converge(conn, request_id, attachment_ids):
        rows = real_rows(conn, request_id, attachment_ids)
        _converge_row(conn, req.store, "requisicao_arquivos", local_id, PDF, origin="migrated_local_legacy")
        conn.commit()
        return rows

    monkeypatch.setattr(comprovantes, "_removal_rows", read_then_converge)

    with pytest.raises(comprovantes.ComprovanteError) as refused:
        comprovantes.remove_comprovantes(req.conn, request_id=1, attachment_ids=[local_id],
                                         actor_user_id=STUDENT_USER_ID)

    assert refused.value.code == "CUSTODY_CHANGED"
    assert req.conn.execute("SELECT count(*) FROM requisicao_arquivos WHERE id=?", (local_id,)).fetchone()[0] == 1
    assert local_path.read_bytes() == PDF


def test_request_delete_retires_a_comprovante_converged_after_the_first_read(req, monkeypatch):
    local_id, local_path = _local_row(req, "aluno-1/late-delete.pdf")
    req.conn.commit()
    linked = {}
    real_lock = comprovantes.lock_request_attachments

    def converge_then_lock(conn, request_id):
        linked["object"] = _converge_row(conn, req.store, "requisicao_arquivos", local_id, PDF,
                                         origin="migrated_local_legacy")
        return real_lock(conn, request_id)

    monkeypatch.setattr(comprovantes, "lock_request_attachments", converge_then_lock)

    comprovantes.delete_request_with_comprovantes(req.conn, request_id=1, actor_user_id=STUDENT_USER_ID)

    assert _object_state(req.conn, linked["object"]) == "retired"
    assert local_path.read_bytes() == PDF
    unowned = req.conn.execute(
        "SELECT count(*) FROM storage_objects o WHERE lifecycle_state='active' AND NOT EXISTS"
        " (SELECT 1 FROM requisicao_arquivos r WHERE r.storage_object_id=o.id)").fetchone()[0]
    assert unowned == 0


def test_converged_comprovante_opens_as_a_signed_redirect(req):
    (local_id, _obj, _path), _google = _converged_requests(req)
    req.app.config["SECRET_KEY"] = "test-only"
    from app.views.comprovantes import bp_comprovantes

    if "comprovantes" not in req.app.blueprints:
        req.app.register_blueprint(bp_comprovantes)
    req.app.add_url_rule("/login", "login", lambda: "login")
    client = req.app.test_client()
    with client.session_transaction() as session:
        session["user_id"] = STUDENT_USER_ID
    response = client.get(f"/comprovantes/{local_id}/open")
    assert response.status_code == 302 and response.headers["Location"].startswith("memory://")
    assert req.google_calls == []


def test_request_delete_never_trashes_a_google_comprovante_converged_after_the_first_read(req, monkeypatch):
    google_id = _google_row(req, "drvlatedel")
    req.conn.commit()
    trashed = []

    class _Drive:
        def trash(self, file_id):
            trashed.append(file_id)

        def untrash(self, file_id):  # pragma: no cover - only on a failure path
            return None

    monkeypatch.setattr(comprovantes, "resolve_google_storage", lambda _conn: _Drive())
    real_begin = comprovantes._begin_delete_intent
    linked = {}

    def converge_then_begin(conn, request_id):
        linked["object"] = _converge_row(conn, req.store, "requisicao_arquivos", google_id, PDF,
                                         origin="migrated_google")
        conn.commit()
        return real_begin(conn, request_id)

    monkeypatch.setattr(comprovantes, "_begin_delete_intent", converge_then_begin)

    comprovantes.delete_request_with_comprovantes(req.conn, request_id=1, actor_user_id=STUDENT_USER_ID)

    assert trashed == []  # the adopted mirror file is never trashed (I2)
    assert _object_state(req.conn, linked["object"]) == "retired"
    assert req.conn.execute("SELECT count(*) FROM requisicoes WHERE id=1").fetchone()[0] == 0
