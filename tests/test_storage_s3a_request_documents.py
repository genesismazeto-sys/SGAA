# coding: utf-8
"""STORAGE S3-A RED: direct request documents through the application surface.

Invariant activated at S3-A close for NEW request documents:
DRIVE_AVAILABILITY_MUST_NOT_BLOCK_REQUEST_SUBMISSION.

Protocol encoded (see ``tests/storage_s3a_support.py``):

    GET form            -> server-issued ``comprovantes_submission_id`` (128-bit)
    POST issue          -> intent + signed TUS capability (no-store); operation
                           identity ``<submission_id>:<upload_slot_id>`` (opaque slot)
    browser -> Supabase -> played against the injected canonical fake
    POST finalize       -> server-side bounded read, SHA-256, structural sniff
    POST business form  -> fields + submission id + verified intent ids, NO bytes;
                           one transaction: re-authorize, consume, attach, commit

Every Google entry point is a tripwire (``arm_google_tripwires``): the
canonical paths must leave its call log EMPTY -- a caught-and-ignored Google
error is still recorded.  The canonical object store is the deterministic fake
injected at ``app.extensions["canonical_object_store"]``; no network is used.

RED today: every node below that drives the new protocol fails because the
issue / finalize routes, the submission id and the canonical attach do not
exist.  GREEN controls are marked as such.
"""

from __future__ import annotations

import io
import logging
import re
import secrets
from pathlib import Path

import pytest

import main
from app.db import write_transaction
from app.storage import custody_common
from app.storage import upload_intents as intents
from tests.canonical_store_fake import InMemoryObjectStore
from tests.session_support import stamp_auth_version
from tests.storage_s3a_support import (
    BUCKET,
    CANONICAL_STORE_EXTENSION,
    DIRECT_TUS_ENDPOINT,
    FINALIZE_URL,
    INTENT_IDS_FIELD,
    INTENT_TTL_SECONDS,
    ISSUE_URL,
    LEGACY_FILE_FIELD,
    MIB16,
    PDF,
    PNG,
    SIGNED_DOWNLOAD_TTL_SECONDS,
    STORAGE_ORIGIN,
    SUBMISSION_FIELD,
    SUPABASE_URL,
    TEST_PUBLISHABLE_KEY,
    TEST_SECRET_KEY,
    TUS_CHUNK_BYTES,
    UPLOAD_SLOTS,
    GoogleTouched,
    arm_google_tripwires,
    browser_upload,
    declaration,
    encrypted_pdf,
    hidden_value,
    padded_png,
    operation_id,
    sha256,
)
from tests.versioned_test_support import isolated_versioned_app_env

ROOT = Path(__file__).resolve().parents[1]
T0 = "2026-10-08 12:00:00"
_CODE_RE = re.compile(r"^[A-Z0-9_]{1,64}$")
_SUBMISSION_RE = re.compile(r"^[0-9a-f]{32}$")
#: Opaque upload slots (``<submission_id>:<upload_slot_id>``); never positional.
SLOTS = UPLOAD_SLOTS


class Clock:
    def __init__(self, now: str) -> None:
        self.now = now

    def __call__(self) -> str:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now = custody_common.add_seconds(self.now, seconds)


class RecordingStore(InMemoryObjectStore):
    """The canonical fake plus a record of the limits / capabilities requested."""

    def __init__(self) -> None:
        super().__init__()
        self.read_limits: list[int] = []
        self.downloads: list[dict] = []
        self.signed_uploads: list[tuple[str, str]] = []

    def read(self, bucket, key, *, max_bytes):
        self.read_limits.append(max_bytes)
        return super().read(bucket, key, max_bytes=max_bytes)

    def create_signed_upload(self, bucket, key):
        self.signed_uploads.append((bucket, key))
        return super().create_signed_upload(bucket, key)

    def create_signed_download(self, bucket, key, *, expires_in, download_name=None):
        self.downloads.append(dict(bucket=bucket, key=key, expires_in=expires_in, download_name=download_name))
        return super().create_signed_download(bucket, key, expires_in=expires_in, download_name=download_name)


# ---------------------------------------------------------------------------
# environment
# ---------------------------------------------------------------------------


def _student(conn):
    return conn.execute(
        """SELECT a.id,a.usuario_id,a.turma_id FROM alunos a JOIN usuarios u ON u.id=a.usuario_id
            WHERE u.tipo='aluno' ORDER BY a.id LIMIT 1"""
    ).fetchone()


def _active_version(conn, student):
    return conn.execute(
        """SELECT item.atividade_versao_id FROM turmas t
             JOIN matriz_atividade_versao_item item ON item.matriz_id=t.matriz_id
             JOIN atividade_versao version ON version.id=item.atividade_versao_id
            WHERE t.id=? AND version.status='ativa' ORDER BY item.id LIMIT 1""",
        (student["turma_id"],),
    ).fetchone()[0]


def _login(client, *, user_id, user_type, access_level=None):
    with client.session_transaction() as sess:
        sess.clear()
        sess["user_id"] = int(user_id)
        sess["user_type"] = user_type
        if access_level:
            sess["access_level"] = access_level
        stamp_auth_version(sess)


def _setup(tmp_path, monkeypatch, *, tripwires=True):
    store = RecordingStore()
    monkeypatch.setitem(main.app.extensions, CANONICAL_STORE_EXTENSION, store)
    monkeypatch.setenv("SUPABASE_URL", SUPABASE_URL)
    monkeypatch.setenv("SUPABASE_SECRET_KEY", TEST_SECRET_KEY)
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", TEST_PUBLISHABLE_KEY)
    monkeypatch.setenv("SGAA_STORAGE_BUCKET", BUCKET)
    clock = Clock(T0)
    monkeypatch.setattr(custody_common, "utc_now_text", clock)
    calls = arm_google_tripwires(monkeypatch, main.app) if tripwires else []
    return store, clock, calls


@pytest.fixture
def env(tmp_path, monkeypatch):
    with isolated_versioned_app_env(tmp_path, "s3a-requests.db") as base:
        store, clock, calls = _setup(tmp_path, monkeypatch)
        with main.app.app_context():
            conn = main.get_db_connection()
            student = dict(_student(conn))
            version_id = _active_version(conn, student)
            admin = dict(conn.execute(
                "SELECT id,nivel_acesso FROM usuarios WHERE tipo='admin' ORDER BY id LIMIT 1"
            ).fetchone())
        yield {**base, "store": store, "clock": clock, "google_calls": calls,
               "student": student, "version_id": version_id, "admin": admin}


def _db():
    return main.get_db_connection()


def _as_student(env):
    _login(env["client"], user_id=env["student"]["usuario_id"], user_type="aluno")


def _as_admin(env):
    _login(env["client"], user_id=env["admin"]["id"], user_type="admin",
           access_level=env["admin"]["nivel_acesso"])


def _other_student(env, suffix="1"):
    with main.app.app_context():
        conn = _db()
        user_id = conn.execute(
            "INSERT INTO usuarios(nome,email,senha,tipo,nivel_acesso) VALUES(?,?,'x','aluno','aluno')",
            (f"Other {suffix}", f"other{suffix}@example.test"),
        ).lastrowid
        conn.execute(
            "INSERT INTO alunos(usuario_id,nome,matricula,email,turma_id) VALUES(?,?,?,?,?)",
            (user_id, f"Other {suffix}", f"OTHER-{suffix}", f"other{suffix}@example.test",
             env["student"]["turma_id"]),
        )
        conn.commit()
    return user_id


def _guarded(call):
    """Run a request; a tripped Google wire is recorded, never swallowed silently."""
    try:
        return call()
    except GoogleTouched:
        return None


def _submission(env, path="/aluno/nova-requisicao") -> str:
    page = env["client"].get(path)
    assert page.status_code == 200, (path, page.status_code)
    value = hidden_value(page.data, SUBMISSION_FIELD)
    assert value is not None, f"{path} renders no server-issued {SUBMISSION_FIELD}"
    assert _SUBMISSION_RE.fullmatch(value), "submission id must be 128-bit lowercase hex"
    return value


def _issue(env, submission_id, slot, content, filename, mime, **extra):
    payload = {"purpose": "comprovante", "submission_id": submission_id, "upload_slot_id": slot,
               **declaration(content, filename, mime), **extra}
    return env["client"].post(ISSUE_URL, json=payload)


def _capability(response) -> dict:
    assert response.status_code in (200, 201), response.status_code
    body = response.get_json(silent=True)
    assert isinstance(body, dict) and body.get("intent_id"), body
    return body


def _upload(env, submission_id, slot, content, filename="proof.pdf", mime="application/pdf",
            *, stored_type=None, **extra) -> str:
    cap = _capability(_issue(env, submission_id, slot, content, filename, mime, **extra))
    browser_upload(env["store"], cap, content, stored_type or mime)
    finalized = env["client"].post(FINALIZE_URL.format(intent_id=cap["intent_id"]))
    assert finalized.status_code == 200, finalized.status_code
    return cap["intent_id"]


def _create_fields(env, name):
    return {"atividade_versao_id": str(env["version_id"]), "nome_evento": name,
            "data_evento": "2026-09-06", "horas_solicitadas": "2"}


def _submit_create(env, name, submission_id, intent_ids):
    data = {**_create_fields(env, name), SUBMISSION_FIELD: submission_id, INTENT_IDS_FIELD: list(intent_ids)}
    return _guarded(lambda: env["client"].post("/aluno/nova-requisicao", data=data))


def _requests_named(name):
    with main.app.app_context():
        return [dict(r) for r in _db().execute("SELECT * FROM requisicoes WHERE nome_evento=?", (name,))]


def _attachments(request_id):
    with main.app.app_context():
        return [dict(r) for r in _db().execute(
            "SELECT * FROM requisicao_arquivos WHERE requisicao_id=? ORDER BY id", (request_id,))]


def _intent(intent_id):
    with main.app.app_context():
        row = _db().execute("SELECT * FROM storage_upload_intents WHERE id=?", (intent_id,)).fetchone()
        return dict(row) if row else None


def _counts():
    with main.app.app_context():
        conn = _db()
        return {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                for t in ("requisicoes", "requisicao_arquivos", "storage_objects")}


def _no_file_request(env, name):
    """A request without documents through the CURRENT route (no Drive involved)."""
    _as_student(env)
    response = env["client"].post("/aluno/nova-requisicao", data=_create_fields(env, name))
    assert response.status_code == 302
    [row] = _requests_named(name)
    return row["id"]


def _seed_intent(env, *, actor, submission_id, slot, content, mime="application/pdf",
                 filename="proof.pdf", requisicao_id=None, purpose="comprovante", verify=True, now=None):
    """Issue (and verify) an intent with the S2 primitives, bypassing the HTTP pre-checks."""
    now = now or env["clock"].now
    with main.app.app_context():
        conn = _db()
        with write_transaction(conn):
            intent = intents.issue_intent(
                conn, actor_user_id=actor, purpose=purpose, operation_id=f"{submission_id}:{slot}",
                bucket=BUCKET, declared_mime_type=mime, declared_size_bytes=len(content),
                declared_sha256=sha256(content), now=now, original_filename=filename,
                requisicao_id=requisicao_id, ttl_seconds=INTENT_TTL_SECONDS,
            )
        env["store"].objects[(BUCKET, intent.storage_key)] = (content, mime)
        if verify:
            with write_transaction(conn):
                intents.mark_verified(conn, intent_id=intent.id, actor_user_id=actor,
                                      observed_size_bytes=len(content), observed_sha256=sha256(content),
                                      now=now)
    return intent.id


def _seed_canonical_attachment(env, request_id, *, status="active", content=PDF):
    """A committed canonical attachment (needs the v15 provider) + its fake object."""
    key = f"comprovantes/2026/10/{request_id:032x}"
    with main.app.app_context():
        conn = _db()
        object_id = conn.execute(
            "INSERT INTO storage_objects(storage_backend,storage_bucket,storage_key,sha256,size_bytes,mime_type,"
            "uploader_user_id,origin,content_verified_at,created_at) VALUES('supabase',?,?,?,?,?,?,"
            "'direct_upload',?,?) RETURNING id",
            (BUCKET, key, sha256(content), len(content), "application/pdf", env["student"]["usuario_id"], T0, T0),
        ).fetchone()[0]
        attachment_id = conn.execute(
            "INSERT INTO requisicao_arquivos(requisicao_id,filename,provider,storage_status,original_filename,"
            "mime_type,size_bytes,sha256,uploaded_at,uploader_user_id,operation_key,storage_object_id)"
            " VALUES(?,?,'supabase',?,'comprovante.pdf','application/pdf',?,?,?,?,?,?) RETURNING id",
            (request_id, f"REQ-{request_id:06d}__canonical.pdf", status, len(content), sha256(content), T0,
             env["student"]["usuario_id"], operation_id(f"{request_id:032x}", SLOTS[5]), object_id),
        ).fetchone()[0]
        conn.commit()
    env["store"].objects[(BUCKET, key)] = (content, "application/pdf")
    return attachment_id, object_id, key


def _assert_canonical(env, request_id, expected_count):
    rows = [r for r in _attachments(request_id) if r["provider"] == "supabase"]
    assert len(rows) == expected_count, rows
    with main.app.app_context():
        conn = _db()
        for row in rows:
            assert row["storage_object_id"] is not None and row["storage_status"] == "active"
            assert row["remote_file_id"] is None and row["remote_parent_id"] is None
            obj = dict(conn.execute("SELECT * FROM storage_objects WHERE id=?",
                                    (row["storage_object_id"],)).fetchone())
            assert (obj["lifecycle_state"], obj["drive_sync_state"], obj["drive_account_key"]) == (
                "active", "pending", None)
            assert (obj["sha256"], obj["size_bytes"], obj["mime_type"]) == (
                row["sha256"], row["size_bytes"], row["mime_type"])
            consumed = conn.execute(
                "SELECT state FROM storage_upload_intents WHERE storage_object_id=?", (obj["id"],)
            ).fetchone()
            assert consumed is not None and consumed[0] == "consumed"
    assert env["google_calls"] == [], env["google_calls"]
    assert "delete" not in env["store"].calls


def _google_state(env, state, monkeypatch):
    with main.app.app_context():
        conn = _db()
        conn.execute("DELETE FROM cloud_accounts")
        if state == "corrupt_token":
            conn.execute(
                "INSERT INTO cloud_accounts(provider,account_email,token_json,active)"
                " VALUES('google','drive@example.test','{not json',1)"
            )
        conn.commit()
    if state == "no_app_credentials":
        for name in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"):
            monkeypatch.delenv(name, raising=False)


GOOGLE_STATES = ("no_account", "no_app_credentials", "corrupt_token")


# ===========================================================================
# 16. Drive hard-fail: the highest-priority business RED
# ===========================================================================


@pytest.mark.parametrize("google_state", GOOGLE_STATES)
def test_A_student_create_with_documents_never_consults_google(env, monkeypatch, google_state):
    _google_state(env, google_state, monkeypatch)
    _as_student(env)
    submission = _submission(env)
    ids = [_upload(env, submission, SLOTS[0], PDF, "a.pdf"), _upload(env, submission, SLOTS[1], PNG, "b.png", "image/png")]
    response = _submit_create(env, "S3A create", submission, ids)
    assert response is not None and response.status_code == 302, env["google_calls"]
    [request] = _requests_named("S3A create")
    _assert_canonical(env, request["id"], 2)


def test_B_student_edit_adds_canonical_document_without_google(env, monkeypatch):
    _google_state(env, "no_account", monkeypatch)
    request_id = _no_file_request(env, "S3A edit")
    submission = _submission(env, f"/aluno/requisicoes/{request_id}?edit=1")
    intent_id = _upload(env, submission, SLOTS[0], PDF, requisicao_id=request_id)
    response = _guarded(lambda: env["client"].post(
        f"/aluno/requisicoes/{request_id}",
        data={"observacao": "com comprovante", SUBMISSION_FIELD: submission, INTENT_IDS_FIELD: [intent_id]},
    ))
    assert response is not None and response.status_code == 302, env["google_calls"]
    _assert_canonical(env, request_id, 1)


def test_C_admin_create_with_document_never_consults_google(env, monkeypatch):
    _google_state(env, "no_account", monkeypatch)
    _as_admin(env)
    submission = _submission(env, "/admin/requisicoes")
    intent_id = _upload(env, submission, SLOTS[0], PDF, aluno_id=env["student"]["id"])
    response = _guarded(lambda: env["client"].post("/admin/requisicoes/nova", data={
        "aluno_id": str(env["student"]["id"]), **_create_fields(env, "S3A admin create"),
        SUBMISSION_FIELD: submission, INTENT_IDS_FIELD: [intent_id],
    }))
    assert response is not None and response.status_code == 302, env["google_calls"]
    [request] = _requests_named("S3A admin create")
    _assert_canonical(env, request["id"], 1)


def test_D_admin_edit_adds_canonical_document_without_google(env, monkeypatch):
    _google_state(env, "no_account", monkeypatch)
    request_id = _no_file_request(env, "S3A admin edit")
    _as_admin(env)
    submission = _submission(env, "/admin/requisicoes")
    intent_id = _upload(env, submission, SLOTS[0], PDF, requisicao_id=request_id)
    response = _guarded(lambda: env["client"].post(f"/admin/requisicoes/{request_id}/editar", data={
        "edit_target_id": str(request_id), "nome_evento": "S3A admin edit", "data_evento": "2026-09-06",
        "horas_solicitadas": "2", SUBMISSION_FIELD: submission, INTENT_IDS_FIELD: [intent_id],
    }))
    assert response is not None and response.status_code == 302, env["google_calls"]
    _assert_canonical(env, request_id, 1)


def test_no_file_request_stays_compatible_and_drive_free(env):
    """GREEN control: a request without documents never needed Drive."""
    request_id = _no_file_request(env, "S3A no file")
    assert _attachments(request_id) == []
    assert env["google_calls"] == []


# ===========================================================================
# 11. issue endpoint / 7. signed TUS capability / 9. TTL
# ===========================================================================


def test_issue_endpoint_is_routed_json_and_refuses_an_empty_declaration(env):
    """Independent of the form's submission id: the issue route itself exists."""
    _as_student(env)
    response = env["client"].post(ISSUE_URL, json={})
    assert response.status_code not in (404, 405), response.status_code
    assert 400 <= response.status_code < 500
    assert _CODE_RE.fullmatch(str((response.get_json(silent=True) or {}).get("error", "")))
    assert env["store"].signed_uploads == []


def test_finalize_endpoint_is_routed_and_unknown_intents_are_indistinguishable(env):
    _as_student(env)
    response = env["client"].post(FINALIZE_URL.format(intent_id=secrets.token_hex(16)))
    assert response.status_code == 404
    assert (response.get_json(silent=True) or {}).get("error") == "INTENT_NOT_FOUND"


def test_issue_returns_a_signed_tus_capability_for_a_server_chosen_locator(env):
    _as_student(env)
    submission = _submission(env)
    response = _issue(env, submission, SLOTS[0], PDF, "proof.pdf", "application/pdf",
                      bucket="attacker-bucket", object_name="comprovantes/../../x", key="x")
    cap = _capability(response)
    assert "no-store" in response.headers.get("Cache-Control", "")
    # Live-proven signed TUS contract: direct storage host, session created at
    # /upload/resumable/sign, x-signature token + the browser-safe publishable apikey.
    assert cap["tus_endpoint"] == DIRECT_TUS_ENDPOINT
    assert cap["tus_endpoint"].startswith(f"{STORAGE_ORIGIN}/")
    assert cap["tus_endpoint"].endswith("/storage/v1/upload/resumable/sign")
    assert cap["apikey"] == TEST_PUBLISHABLE_KEY and cap["apikey"].startswith("sb_publishable_")
    assert "sb_secret_" not in response.get_data(as_text=True)
    assert cap["chunk_size"] == TUS_CHUNK_BYTES
    assert cap["bucket"] == BUCKET
    assert re.fullmatch(r"comprovantes/\d{4}/\d{2}/[0-9a-f]{32}", cap["object_name"])
    assert env["store"].signed_uploads == [(BUCKET, cap["object_name"])]
    assert cap["upload_token"] and env["store"].pending_uploads.get(cap["upload_token"]) == (
        BUCKET, cap["object_name"])
    assert TEST_SECRET_KEY.encode() not in response.data
    row = _intent(cap["intent_id"])
    assert (row["actor_user_id"], row["purpose"], row["state"], row["requisicao_id"]) == (
        env["student"]["usuario_id"], "comprovante", "issued", None)
    assert row["operation_id"] == operation_id(submission, SLOTS[0])  # no index, digest or filename
    assert sha256(PDF)[:16] not in row["operation_id"] and "proof" not in row["operation_id"]
    assert row["storage_key"] == cap["object_name"]
    assert row["expires_at"] == custody_common.add_seconds(row["issued_at"], INTENT_TTL_SECONDS)
    assert "upload_token" not in row and cap["upload_token"] not in str(row)


@pytest.mark.parametrize(
    "publishable",
    [None, "", TEST_SECRET_KEY, "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoiYW5vbiJ9.c2lnbmF0dXJl", "sb_publishable_"],
    ids=["missing", "empty", "secret-key", "legacy-jwt", "prefix-only"],
)
def test_issue_refuses_a_capability_without_a_valid_publishable_key(env, monkeypatch, publishable):
    """Never a secret (or a legacy JWT) as the browser apikey: refused before any intent or signing."""
    if publishable is None:
        monkeypatch.delenv("SUPABASE_PUBLISHABLE_KEY", raising=False)
    else:
        monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", publishable)
    _as_student(env)
    submission = _submission(env)
    response = _issue(env, submission, SLOTS[0], PDF, "proof.pdf", "application/pdf")
    assert response.status_code == 503
    assert response.get_json()["error"] == "STORAGE_NOT_CONFIGURED"
    assert b"sb_secret_" not in response.data and b"eyJ" not in response.data
    assert env["store"].signed_uploads == []
    with main.app.app_context():
        assert _db().execute("SELECT count(*) FROM storage_upload_intents").fetchone()[0] == 0


def test_issue_requires_an_authenticated_actor(env):
    response = env["client"].post(ISSUE_URL, json={"purpose": "comprovante"})
    assert response.status_code in (401, 403) or (
        response.status_code == 302 and "/login" in response.headers.get("Location", ""))
    assert _counts()["storage_objects"] == 0
    with main.app.app_context():
        assert _db().execute("SELECT count(*) FROM storage_upload_intents").fetchone()[0] == 0


@pytest.mark.parametrize(
    ("purpose", "filename", "mime", "content", "extra"),
    [
        ("admin_arquivo", "proof.pdf", "application/pdf", PDF, {}),
        ("avatar", "proof.pdf", "application/pdf", PDF, {}),
        ("comprovante", "proof.pdf", "image/png", PDF, {}),
        ("comprovante", "proof.html", "text/html", b"<html></html>", {}),
        ("comprovante", "proof.pdf", "application/pdf", PDF, {"size_bytes": 0}),
        ("comprovante", "proof.pdf", "application/pdf", PDF, {"size_bytes": MIB16 + 1}),
    ],
    ids=["arquivos-not-switched", "unknown-purpose", "extension-vs-mime", "html", "zero-size", "over-16MiB"],
)
def test_issue_prechecks_purpose_and_declarations(env, purpose, filename, mime, content, extra):
    _as_student(env)
    submission = _submission(env)
    payload = {"purpose": purpose, "submission_id": submission, "upload_slot_id": SLOTS[0],
               **declaration(content, filename, mime), **extra}
    response = env["client"].post(ISSUE_URL, json=payload)
    body = response.get_json(silent=True)
    assert 400 <= response.status_code < 500 and response.status_code != 404, response.status_code
    assert isinstance(body, dict) and _CODE_RE.fullmatch(str(body.get("error", ""))), body
    assert env["store"].signed_uploads == []


def test_issue_refuses_a_foreign_or_closed_target(env):
    foreign_request = _no_file_request(env, "S3A foreign target")
    with main.app.app_context():
        conn = _db()
        conn.execute("UPDATE requisicoes SET status='Deferida' WHERE id=?", (foreign_request,))
        conn.commit()
    _as_student(env)
    submission = _submission(env)
    closed = _issue(env, submission, SLOTS[0], PDF, "p.pdf", "application/pdf", requisicao_id=foreign_request)
    other = _other_student(env)
    _login(env["client"], user_id=other, user_type="aluno")
    submission = _submission(env)
    foreign = _issue(env, submission, SLOTS[0], PDF, "p.pdf", "application/pdf", requisicao_id=foreign_request)
    for response in (closed, foreign):
        assert response.status_code in (403, 404, 409, 422), response.status_code
        assert isinstance(response.get_json(silent=True), dict)
    assert env["store"].signed_uploads == []


def test_issue_aggregate_precheck_is_the_16_mib_submission_total(env):
    _as_student(env)
    submission = _submission(env)
    half = MIB16 // 2
    first = _issue(env, submission, SLOTS[0], padded_png(half), "a.png", "image/png")
    exact = _issue(env, submission, SLOTS[1], padded_png(half), "b.png", "image/png")
    _capability(first), _capability(exact)
    over = _issue(env, submission, SLOTS[2], padded_png(len(PNG) + 13), "c.png", "image/png")
    assert 400 <= over.status_code < 500 and over.status_code != 404
    assert _CODE_RE.fullmatch(str((over.get_json(silent=True) or {}).get("error", "")))


def test_same_operation_same_declaration_reuses_the_live_intent_and_remints_without_extending(env):
    _as_student(env)
    submission = _submission(env)
    first = _capability(_issue(env, submission, SLOTS[0], PDF, "p.pdf", "application/pdf"))
    env["clock"].advance(60 * 60)
    again = _capability(_issue(env, submission, SLOTS[0], PDF, "p.pdf", "application/pdf"))
    assert again["intent_id"] == first["intent_id"]
    assert again["object_name"] == first["object_name"]
    assert again["upload_token"] != first["upload_token"]  # fresh capability, same immutable key
    row = _intent(first["intent_id"])
    assert row["issued_at"] == T0
    assert row["expires_at"] == custody_common.add_seconds(T0, INTENT_TTL_SECONDS)  # not extended


def test_same_operation_with_a_different_file_is_a_conflict(env):
    _as_student(env)
    submission = _submission(env)
    _capability(_issue(env, submission, SLOTS[0], PDF, "p.pdf", "application/pdf"))
    conflict = _issue(env, submission, SLOTS[0], PNG, "p.png", "image/png")
    assert conflict.status_code == 409
    assert (conflict.get_json(silent=True) or {}).get("error") == "INTENT_OPERATION_CONFLICT"


def test_a_deliberately_different_file_gets_a_new_slot_and_a_new_operation(env):
    _as_student(env)
    submission = _submission(env)
    first = _capability(_issue(env, submission, SLOTS[0], PDF, "p.pdf", "application/pdf"))
    replacement = _capability(_issue(env, submission, SLOTS[1], PNG, "p.png", "image/png"))
    assert replacement["intent_id"] != first["intent_id"]
    assert replacement["object_name"] != first["object_name"]
    assert _intent(replacement["intent_id"])["operation_id"] == operation_id(submission, SLOTS[1])


def test_reordering_or_removing_other_files_keeps_each_files_operation_identity(env):
    _as_student(env)
    submission = _submission(env)
    a = _capability(_issue(env, submission, SLOTS[0], PDF, "a.pdf", "application/pdf"))
    b = _capability(_issue(env, submission, SLOTS[1], PNG, "b.png", "image/png"))
    # the user removes file A and the list re-renders: B is retried first, alone
    b_again = _capability(_issue(env, submission, SLOTS[1], PNG, "b.png", "image/png"))
    assert b_again["intent_id"] == b["intent_id"]
    assert _intent(b["intent_id"])["operation_id"] == operation_id(submission, SLOTS[1])
    assert _intent(a["intent_id"])["operation_id"] == operation_id(submission, SLOTS[0])


@pytest.mark.parametrize(
    "slot",
    ["0", "1", "", "Z" * 32, SLOTS[0][:-1], SLOTS[0] + "0", SLOTS[0].upper(), "proof.pdf", sha256(PDF)],
    ids=["positional-0", "positional-1", "empty", "non-hex", "short", "long", "uppercase", "filename", "sha256"],
)
def test_issue_refuses_a_malformed_upload_slot(env, slot):
    _as_student(env)
    submission = _submission(env)
    response = _issue(env, submission, slot, PDF, "proof.pdf", "application/pdf")
    assert 400 <= response.status_code < 500 and response.status_code != 404, response.status_code
    assert _CODE_RE.fullmatch(str((response.get_json(silent=True) or {}).get("error", "")))
    assert env["store"].signed_uploads == []


def test_a_slot_never_authorizes_another_actor(env):
    _as_student(env)
    submission = _submission(env)
    _capability(_issue(env, submission, SLOTS[0], PDF, "p.pdf", "application/pdf"))
    _login(env["client"], user_id=_other_student(env, "5"), user_type="aluno")
    own_submission = _submission(env)
    stolen = _issue(env, submission, SLOTS[0], PDF, "p.pdf", "application/pdf")
    assert stolen.status_code in (403, 404, 409, 422), stolen.status_code
    assert isinstance(stolen.get_json(silent=True), dict)
    with main.app.app_context():
        assert _db().execute("SELECT count(*) FROM storage_upload_intents").fetchone()[0] == 1
    assert own_submission != submission


def test_expired_intent_cannot_finalize_or_attach(env):
    _as_student(env)
    submission = _submission(env)
    cap = _capability(_issue(env, submission, SLOTS[0], PDF, "p.pdf", "application/pdf"))
    browser_upload(env["store"], cap, PDF, "application/pdf")
    env["clock"].advance(INTENT_TTL_SECONDS + 1)
    late = env["client"].post(FINALIZE_URL.format(intent_id=cap["intent_id"]))
    assert late.status_code in (409, 410, 422)
    assert (late.get_json(silent=True) or {}).get("error") == "INTENT_EXPIRED"
    assert _intent(cap["intent_id"])["state"] != "verified"
    before = _counts()
    response = _submit_create(env, "S3A expired", submission, [cap["intent_id"]])
    assert response is not None and response.status_code != 500
    assert _counts() == before


def test_expired_submission_cannot_attach_old_verified_intents(env):
    _as_student(env)
    submission = _submission(env)
    intent_id = _upload(env, submission, SLOTS[0], PDF)
    env["clock"].advance(INTENT_TTL_SECONDS + 1)
    before = _counts()
    response = _submit_create(env, "S3A stale submission", submission, [intent_id])
    assert response is not None and response.status_code != 500
    assert _counts() == before and _intent(intent_id)["state"] == "verified"


# ===========================================================================
# 12/13/14. finalize: server-side bounded verification and idempotency
# ===========================================================================


def test_finalize_verifies_server_side_bounded_and_is_idempotent(env):
    _as_student(env)
    submission = _submission(env)
    cap = _capability(_issue(env, submission, SLOTS[0], PDF, "p.pdf", "application/pdf"))
    browser_upload(env["store"], cap, PDF, "application/pdf")
    url = FINALIZE_URL.format(intent_id=cap["intent_id"])
    lies = {"size_bytes": 1, "sha256": "0" * 64, "mime_type": "image/png", "bucket": "x", "key": "y"}
    first = env["client"].post(url, json=lies)
    assert first.status_code == 200 and (first.get_json() or {}).get("state") == "verified"
    verified = _intent(cap["intent_id"])
    assert verified["state"] == "verified" and verified["declared_sha256"] == sha256(PDF)
    assert env["store"].read_limits and set(env["store"].read_limits) == {MIB16}
    second = env["client"].post(url)
    assert second.status_code == 200 and (second.get_json() or {}).get("state") == "verified"
    assert _intent(cap["intent_id"])["verified_at"] == verified["verified_at"]


@pytest.mark.parametrize(
    ("declared", "filename", "mime", "stored", "stored_type"),
    [
        (PNG, "proof.pdf", "application/pdf", PNG, "application/pdf"),
        (PDF, "proof.pdf", "application/pdf", PDF, "image/png"),
        ("ENCRYPTED", "proof.pdf", "application/pdf", "ENCRYPTED", "application/pdf"),
        (PDF, "proof.pdf", "application/pdf", b"", "application/pdf"),
        (PDF, "proof.pdf", "application/pdf", "OVERSIZED", "application/pdf"),
    ],
    ids=["png-bytes-declared-pdf", "wrong-storage-content-type", "encrypted-pdf", "zero-bytes", "oversized"],
)
def test_finalize_fails_closed_with_a_sanitized_code(env, declared, filename, mime, stored, stored_type):
    if declared == "ENCRYPTED":
        declared = stored = encrypted_pdf()
    if stored == "OVERSIZED":
        stored = padded_png(MIB16 + 1)
    _as_student(env)
    submission = _submission(env)
    cap = _capability(_issue(env, submission, SLOTS[0], declared, filename, mime))
    env["store"].objects[(BUCKET, cap["object_name"])] = (stored, stored_type)
    response = env["client"].post(FINALIZE_URL.format(intent_id=cap["intent_id"]))
    body = response.get_json(silent=True) or {}
    assert 400 <= response.status_code < 500 and response.status_code != 404, response.status_code
    assert _CODE_RE.fullmatch(str(body.get("error", ""))), body
    assert _intent(cap["intent_id"])["state"] == "rejected"
    assert all(limit <= MIB16 for limit in env["store"].read_limits)
    for secret in (TEST_SECRET_KEY, "memory://", cap["upload_token"]):
        assert secret.encode() not in response.data


def test_finalize_of_a_missing_object_or_provider_outage_keeps_the_intent_retryable(env):
    _as_student(env)
    submission = _submission(env)
    cap = _capability(_issue(env, submission, SLOTS[0], PDF, "p.pdf", "application/pdf"))
    url = FINALIZE_URL.format(intent_id=cap["intent_id"])
    missing = env["client"].post(url)
    assert 400 <= missing.status_code < 600 and missing.status_code != 404
    assert _CODE_RE.fullmatch(str((missing.get_json(silent=True) or {}).get("error", "")))
    browser_upload(env["store"], cap, PDF, "application/pdf")
    env["store"].fail_next("STORAGE_PROVIDER_UNAVAILABLE")
    outage = env["client"].post(url)
    assert outage.status_code in (502, 503) and TEST_SECRET_KEY.encode() not in outage.data
    assert _intent(cap["intent_id"])["state"] == "issued"
    assert env["client"].post(url).status_code == 200


def test_finalize_never_masquerades_rejected_consumed_or_foreign_intents(env):
    """Seeded through the S2 primitives: independent of the form prerequisite."""
    _as_student(env)
    submission = secrets.token_hex(16)
    actor = env["student"]["usuario_id"]
    rejected = _seed_intent(env, actor=actor, submission_id=submission, slot=SLOTS[0], content=PDF, verify=False)
    with main.app.app_context():
        conn = _db()
        with write_transaction(conn):
            intents.reject_intent(conn, intent_id=rejected, rejection_code="MIME_MISMATCH", now=T0)
    consumed = _seed_intent(env, actor=actor, submission_id=submission, slot=SLOTS[1], content=PDF)
    with main.app.app_context():
        conn = _db()
        with write_transaction(conn):
            intents.consume_intent(conn, intent_id=consumed, actor_user_id=actor, purpose="comprovante",
                                   operation_id=f"{submission}:{SLOTS[1]}", now=T0)
    for intent_id in (rejected, consumed):
        response = env["client"].post(FINALIZE_URL.format(intent_id=intent_id))
        assert response.status_code in (409, 410, 422), response.status_code
        assert (response.get_json(silent=True) or {}).get("state") != "verified"
    foreign = _seed_intent(env, actor=actor, submission_id=submission, slot=SLOTS[2], content=PDF, verify=False)
    _login(env["client"], user_id=_other_student(env), user_type="aluno")
    stolen = env["client"].post(FINALIZE_URL.format(intent_id=foreign))
    assert stolen.status_code in (403, 404) and isinstance(stolen.get_json(silent=True), dict)
    assert _intent(foreign)["state"] == "issued"


# ===========================================================================
# 6. total 16 MiB per submission (verified bytes)
# ===========================================================================


@pytest.mark.parametrize(
    "sizes", [(MIB16 // 16,), (MIB16 // 2, MIB16 // 2)], ids=["one-file-below-16MiB", "total-exactly-16MiB"]
)
def test_submission_total_up_to_16_mib_is_accepted(env, sizes):
    _as_student(env)
    submission = _submission(env)
    ids = [_upload(env, submission, SLOTS[i], padded_png(size), f"f{i}.png", "image/png") for i, size in enumerate(sizes)]
    response = _submit_create(env, "S3A total ok", submission, ids)
    assert response is not None and response.status_code == 302
    [request] = _requests_named("S3A total ok")
    assert sum(r["size_bytes"] for r in _attachments(request["id"])) == sum(sizes)


def test_submit_enforces_the_verified_total_not_browser_declarations(env):
    """Two VERIFIED intents totalling 16 MiB + 1 (issued past the HTTP pre-check)."""
    _as_student(env)
    submission = _submission(env)
    actor = env["student"]["usuario_id"]
    half = MIB16 // 2
    ids = [
        _seed_intent(env, actor=actor, submission_id=submission, slot=SLOTS[0], content=padded_png(half),
                     mime="image/png", filename="a.png"),
        _seed_intent(env, actor=actor, submission_id=submission, slot=SLOTS[1], content=padded_png(half + 1),
                     mime="image/png", filename="b.png"),
    ]
    before = _counts()
    response = _submit_create(env, "S3A total over", submission, ids)
    assert response is not None and response.status_code in (302, 400, 413, 422)
    assert _counts() == before
    assert {_intent(i)["state"] for i in ids} == {"verified"}


def test_a_lying_size_declaration_never_verifies(env):
    _as_student(env)
    submission = _submission(env)
    real = padded_png(MIB16 // 4)
    response = _issue(env, submission, SLOTS[0], PNG, "a.png", "image/png")  # declares the 1x1 PNG
    cap = _capability(response)
    browser_upload(env["store"], cap, real, "image/png")  # uploads 4 MiB instead
    finalized = env["client"].post(FINALIZE_URL.format(intent_id=cap["intent_id"]))
    assert 400 <= finalized.status_code < 500 and finalized.status_code != 404
    assert _intent(cap["intent_id"])["state"] == "rejected"


def test_padded_png_fixture_is_a_supported_document():
    """GREEN control: the size fixtures pass the CURRENT business validator."""
    from app.file_validation import detect_supported_mime

    for size in (len(PNG) + 12, MIB16 // 2, MIB16 // 2 + 1):
        assert detect_supported_mime(padded_png(size)) == "image/png"


# ===========================================================================
# 10/15/21. submission binding, consume + attach, replay
# ===========================================================================


def test_binding_refuses_other_actor_other_submission_purpose_target_and_state(env):
    _as_student(env)
    actor = env["student"]["usuario_id"]
    mine = _submission(env)
    other_form = _submission(env)
    assert other_form != mine
    existing = _no_file_request(env, "S3A existing")
    other_actor = _other_student(env, "2")
    cases = {
        "another actor": _seed_intent(env, actor=other_actor, submission_id=mine, slot=SLOTS[0], content=PDF),
        "another submission": _seed_intent(env, actor=actor, submission_id=other_form, slot=SLOTS[0], content=PDF),
        "purpose swap": _seed_intent(env, actor=actor, submission_id=mine, slot=SLOTS[1], content=PDF,
                                     purpose="admin_arquivo"),
        "bound to an existing request": _seed_intent(env, actor=actor, submission_id=mine, slot=SLOTS[2], content=PDF,
                                                     requisicao_id=existing),
        "unverified": _seed_intent(env, actor=actor, submission_id=mine, slot=SLOTS[3], content=PDF, verify=False),
    }
    for label, intent_id in cases.items():
        state = _intent(intent_id)["state"]
        before = _counts()
        response = _submit_create(env, f"S3A bind {label}", mine, [intent_id])
        assert response is not None and response.status_code != 500, label
        assert _counts() == before, label
        assert _intent(intent_id)["state"] == state, label
    assert env["google_calls"] == []


def test_create_intent_cannot_be_attached_to_an_arbitrary_existing_request(env):
    request_id = _no_file_request(env, "S3A target swap")
    other_request = _no_file_request(env, "S3A target other")
    submission = _submission(env, f"/aluno/requisicoes/{request_id}?edit=1")
    actor = env["student"]["usuario_id"]
    create_intent = _seed_intent(env, actor=actor, submission_id=submission, slot=SLOTS[0], content=PDF)
    swapped = _seed_intent(env, actor=actor, submission_id=submission, slot=SLOTS[1], content=PDF,
                           requisicao_id=other_request)
    for intent_id in (create_intent, swapped):
        response = _guarded(lambda: env["client"].post(
            f"/aluno/requisicoes/{request_id}",
            data={"observacao": "swap", SUBMISSION_FIELD: submission, INTENT_IDS_FIELD: [intent_id]},
        ))
        assert response is not None and response.status_code != 500
        assert _attachments(request_id) == []
        assert _intent(intent_id)["state"] == "verified"


def test_db_fault_rolls_back_request_consume_and_attachment_together_then_retry_succeeds(env, monkeypatch):
    _as_student(env)
    submission = _submission(env)
    intent_id = _upload(env, submission, SLOTS[0], PDF)
    original = intents.consume_intent
    fired = []

    def faulty(*args, **kwargs):
        result = original(*args, **kwargs)
        fired.append(True)
        raise RuntimeError("injected fault after consume")

    monkeypatch.setattr(intents, "consume_intent", faulty)
    before = _counts()
    try:
        _submit_create(env, "S3A atomic", submission, [intent_id])
    except RuntimeError:
        pass
    assert fired, "the submit path must consume through app.storage.upload_intents.consume_intent"
    assert _counts() == before
    assert _intent(intent_id)["state"] == "verified"
    monkeypatch.setattr(intents, "consume_intent", original)
    retry = _submit_create(env, "S3A atomic", submission, [intent_id])
    assert retry is not None and retry.status_code == 302
    assert len(_requests_named("S3A atomic")) == 1


def test_submit_replay_creates_nothing_twice_and_another_student_cannot_replay(env):
    _as_student(env)
    submission = _submission(env)
    intent_id = _upload(env, submission, SLOTS[0], PDF)
    first = _submit_create(env, "S3A replay", submission, [intent_id])
    assert first is not None and first.status_code == 302
    after_first = _counts()
    again = _submit_create(env, "S3A replay", submission, [intent_id])  # response lost, user retries
    assert again is not None and again.status_code == 302
    assert _counts() == after_first and len(_requests_named("S3A replay")) == 1
    _login(env["client"], user_id=_other_student(env, "3"), user_type="aluno")
    stolen = _submit_create(env, "S3A replay theft", submission, [intent_id])
    assert stolen is not None and stolen.status_code != 500
    assert _requests_named("S3A replay theft") == [] and _counts() == after_first


# ===========================================================================
# 17/18. no file body through the application; no-JS contract
# ===========================================================================


@pytest.mark.parametrize("actor", ["student", "admin"])
def test_multipart_attachment_bytes_are_refused_by_the_switched_routes(env, actor):
    if actor == "student":
        _as_student(env)
        url, data, name = "/aluno/nova-requisicao", _create_fields(env, "S3A multipart"), "S3A multipart"
    else:
        _as_admin(env)
        name = "S3A admin multipart"
        url, data = "/admin/requisicoes/nova", {"aluno_id": str(env["student"]["id"]), **_create_fields(env, name)}
    data = {**data, LEGACY_FILE_FIELD: (io.BytesIO(PDF), "proof.pdf")}
    response = _guarded(lambda: env["client"].post(url, data=data, content_type="multipart/form-data"))
    assert env["google_calls"] == [], "file bytes reached the Drive path"
    assert response is not None and response.status_code in (302, 400, 413, 415, 422)
    assert _requests_named(name) == [] and env["store"].calls == []


def test_create_form_is_direct_upload_only_and_explains_the_javascript_requirement(env):
    _as_student(env)
    html = env["client"].get("/aluno/nova-requisicao").data.decode("utf-8")
    form = re.search(r"<form\b[^>]*>.*?</form>", html, re.DOTALL | re.IGNORECASE).group(0)
    assert "multipart/form-data" not in form.lower(), "the file-enabled form must not post bytes"
    file_inputs = re.findall(r"<input\b[^>]*type=[\"']file[\"'][^>]*>", form, re.IGNORECASE)
    assert file_inputs, "the attachment picker must stay on the page"
    for tag in file_inputs:
        assert not re.search(r"\bname\s*=", tag, re.IGNORECASE), "a no-JS submit must never send bytes"
        assert re.search(r"\bdisabled\b", tag, re.IGNORECASE), "the picker is enabled only by direct-upload.js"
    noscript = re.search(r"<noscript>(.*?)</noscript>", html, re.DOTALL | re.IGNORECASE)
    assert noscript and "javascript" in noscript.group(1).lower()
    assert "/static/js/direct-upload.js" in html
    assert re.search(r"/static/vendor/tus-js-client[-@]\d+\.\d+\.\d+(\.min)?\.js", html)
    assert hidden_value(html.encode(), SUBMISSION_FIELD)


# ===========================================================================
# 19. signed download
# ===========================================================================


def test_canonical_open_redirects_to_a_short_lived_signed_url_for_the_owner(env, caplog):
    request_id = _no_file_request(env, "S3A download")
    attachment_id, _object_id, key = _seed_canonical_attachment(env, request_id)
    caplog.set_level(logging.DEBUG)
    response = env["client"].get(f"/comprovantes/{attachment_id}/open")
    assert response.status_code == 302
    assert response.headers["Location"] == f"memory://download/{BUCKET}/{key}"
    assert "no-store" in response.headers.get("Cache-Control", "")
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert PDF not in response.data
    assert env["store"].downloads == [dict(bucket=BUCKET, key=key, expires_in=SIGNED_DOWNLOAD_TTL_SECONDS,
                                           download_name=None)]
    assert all(response.headers["Location"] not in record.getMessage() for record in caplog.records)
    named = env["client"].get(f"/comprovantes/{attachment_id}/open?download=1")
    assert named.status_code == 302 and env["store"].downloads[-1]["download_name"]
    assert env["google_calls"] == []


def test_canonical_open_authorization_admin_foreign_student_and_trashed(env):
    request_id = _no_file_request(env, "S3A download authz")
    attachment_id, _object_id, _key = _seed_canonical_attachment(env, request_id)
    trashed_id, _o, _k = _seed_canonical_attachment(env, _no_file_request(env, "S3A trashed"), status="trashed")
    assert env["client"].get(f"/comprovantes/{trashed_id}/open").status_code in (403, 404)
    _login(env["client"], user_id=_other_student(env, "4"), user_type="aluno")
    assert env["client"].get(f"/comprovantes/{attachment_id}/open").status_code in (403, 404)
    assert env["store"].downloads == []
    _as_admin(env)
    assert env["client"].get(f"/comprovantes/{attachment_id}/open").status_code == 302
    assert len(env["store"].downloads) == 1 and env["google_calls"] == []


# ===========================================================================
# 20. canonical remove / delete; mixed legacy failure
# ===========================================================================


def _object(object_id):
    with main.app.app_context():
        return dict(_db().execute("SELECT * FROM storage_objects WHERE id=?", (object_id,)).fetchone())


def test_canonical_remove_trashes_the_row_retires_the_object_and_never_deletes_bytes(env):
    request_id = _no_file_request(env, "S3A remove")
    attachment_id, object_id, key = _seed_canonical_attachment(env, request_id)
    response = _guarded(lambda: env["client"].post(
        f"/aluno/requisicoes/{request_id}",
        data={"observacao": "remove", "remover_comprovantes": [str(attachment_id)]},
    ))
    assert response is not None and response.status_code == 302
    [row] = _attachments(request_id)
    assert (row["storage_status"], row["storage_object_id"]) == ("trashed", object_id)
    assert _object(object_id)["lifecycle_state"] == "retired"
    assert (BUCKET, key) in env["store"].objects and "delete" not in env["store"].calls
    assert env["google_calls"] == []
    assert env["client"].get(f"/comprovantes/{attachment_id}/open").status_code in (403, 404)


def test_canonical_request_delete_retires_objects_in_the_same_transaction(env):
    request_id = _no_file_request(env, "S3A delete")
    _attachment_id, object_id, key = _seed_canonical_attachment(env, request_id)
    response = _guarded(lambda: env["client"].post(f"/aluno/requisicoes/{request_id}?delete=1"))
    assert response is not None and response.status_code in (200, 204, 302)
    assert _requests_named("S3A delete") == [] and _attachments(request_id) == []
    assert _object(object_id)["lifecycle_state"] == "retired"
    assert (BUCKET, key) in env["store"].objects and "delete" not in env["store"].calls
    assert env["google_calls"] == []


@pytest.fixture
def mixed_env(tmp_path, monkeypatch):
    """Legacy Google custody really is consulted here (legacy removal is S5's)."""
    from tests.test_comprovantes_google_drive import FakeStorage

    with isolated_versioned_app_env(tmp_path, "s3a-mixed.db") as base:
        store, clock, _calls = _setup(tmp_path, monkeypatch, tripwires=False)
        drive = FakeStorage()
        drive.fail_trash = True
        monkeypatch.setitem(main.app.extensions, "comprovante_storage", drive)
        with main.app.app_context():
            conn = main.get_db_connection()
            student = dict(_student(conn))
            version_id = _active_version(conn, student)
        yield {**base, "store": store, "clock": clock, "google_calls": [], "drive": drive,
               "student": student, "version_id": version_id}


def test_mixed_request_legacy_removal_failure_keeps_the_committed_canonical_edit(mixed_env):
    env = mixed_env
    request_id = _no_file_request(env, "S3A mixed")
    with main.app.app_context():
        conn = _db()
        legacy_id = conn.execute(
            "INSERT INTO requisicao_arquivos(requisicao_id,filename,provider,storage_status,remote_file_id,"
            "remote_parent_id,original_filename,mime_type,size_bytes,sha256,uploaded_at,uploader_user_id,"
            "operation_key) VALUES(?,'REQ-legacy.pdf','google','active','remote-legacy','folder-legacy',"
            "'legado.pdf','application/pdf',?,?,?,?,'legacy-op:0:x') RETURNING id",
            (request_id, len(PDF), sha256(PDF), T0, env["student"]["usuario_id"]),
        ).fetchone()[0]
        conn.commit()
    submission = _submission(env, f"/aluno/requisicoes/{request_id}?edit=1")
    intent_id = _upload(env, submission, SLOTS[0], PDF, requisicao_id=request_id)
    response = env["client"].post(f"/aluno/requisicoes/{request_id}", data={
        "observacao": "mixed edit", SUBMISSION_FIELD: submission, INTENT_IDS_FIELD: [intent_id],
        "remover_comprovantes": [str(legacy_id)],
    })
    assert response.status_code == 302
    with main.app.app_context():
        assert _db().execute("SELECT observacao FROM requisicoes WHERE id=?", (request_id,)).fetchone()[0] == (
            "mixed edit")
    rows = {r["id"]: r for r in _attachments(request_id)}
    assert rows[legacy_id]["storage_status"] == "active"  # legacy removal failed and was restored
    assert [r["provider"] for r in rows.values() if r["id"] != legacy_id] == ["supabase"]
    with env["client"].session_transaction() as sess:
        flashes = list(sess.get("_flashes", []))
    assert ("success", "Requisição atualizada.") in flashes, flashes
    assert any(category == "error" and "mantidos" in message for category, message in flashes), flashes


# ===========================================================================
# 22. frontend / CSP architecture
# ===========================================================================

_CHUNK_RE = re.compile(r"6\s*\*\s*1024\s*\*\s*1024|6291456")
_FORBIDDEN_CLIENT_MARKERS = ("supabase-js", "createclient(", "sb_secret_", "sb_publishable_", "service_role")


def _direct_upload_source() -> str:
    path = ROOT / "static" / "js" / "direct-upload.js"
    assert path.is_file(), "static/js/direct-upload.js is the S3-A upload client"
    return path.read_text(encoding="utf-8")


def test_vendored_tus_client_is_local_and_version_pinned():
    vendor = ROOT / "static" / "vendor"
    pinned = [p for p in vendor.iterdir()
              if re.fullmatch(r"tus-js-client[-@]\d+\.\d+\.\d+(\.min)?\.js", p.name)]
    assert len(pinned) == 1, sorted(p.name for p in vendor.iterdir())


def test_direct_upload_client_uses_signed_tus_chunks_and_holds_no_key():
    source = _direct_upload_source()
    assert _CHUNK_RE.search(source), "TUS chunk size must be 6 MiB"
    # Signed TUS headers: the capability's publishable apikey + x-signature token,
    # never an Authorization header; the endpoint comes from the capability.
    assert re.search(r"headers:\s*\{\s*apikey:\s*capability\.apikey,\s*'x-signature':\s*capability\.upload_token\s*\}",
                     source)
    assert not re.search(r"""['"]?authorization['"]?\s*:""", source, re.IGNORECASE)
    assert "bearer" not in source.lower()
    assert "/upload/resumable" not in source
    assert "/storage/upload-intents" in source and "/finalize" in source
    assert "onProgress" in source and "retryDelays" in source
    assert INTENT_IDS_FIELD in source
    lowered = source.lower()
    for marker in _FORBIDDEN_CLIENT_MARKERS:
        assert marker not in lowered, marker


def test_static_detectors_are_discriminating():
    """GREEN negative controls for the static detectors above."""
    assert _CHUNK_RE.search("chunkSize: 6 * 1024 * 1024") and _CHUNK_RE.search("6291456")
    assert not _CHUNK_RE.search("chunkSize: 5 * 1024 * 1024")
    picker = (ROOT / "static" / "js" / "comprovantes-picker.js").read_text(encoding="utf-8")
    assert not _CHUNK_RE.search(picker) and "x-signature" not in picker
    assert all(marker not in picker.lower() for marker in _FORBIDDEN_CLIENT_MARKERS)


def _connect_src(policy: str) -> list[str]:
    for chunk in policy.split(";"):
        parts = chunk.strip().split()
        if parts and parts[0] == "connect-src":
            return parts[1:]
    return []


def test_csp_connect_src_adds_exactly_the_configured_storage_origin(monkeypatch):
    from app import create_app

    monkeypatch.delenv("CONTENT_SECURITY_POLICY", raising=False)
    monkeypatch.setenv("SUPABASE_URL", SUPABASE_URL)
    policy = create_app().config["CONTENT_SECURITY_POLICY"]
    sources = _connect_src(policy)
    assert STORAGE_ORIGIN in sources
    assert [s for s in sources if "supabase" in s] == [STORAGE_ORIGIN]
    assert not any("*" in s for s in sources)
