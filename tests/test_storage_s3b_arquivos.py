# coding: utf-8
"""STORAGE S3-B RED: admin ARQUIVOS on canonical Supabase Storage (SQLite lane).

Invariant activated at S3-B close:
DRIVE_AVAILABILITY_MUST_NOT_BLOCK_ADMIN_ARQUIVOS_CANONICAL_OPERATION -- for
canonical create, canonical replacement (from canonical / google-active /
local-legacy-active custody), canonical admin and student reads, canonical
delete and canonical metadata-only edit.  Legacy-only Google / local reads,
deletes and cleanup retries stay outside the guarantee until S5.

Protocol encoded (supervisor-adjudicated contract; see
``tests/storage_s3b_support.py``):

    GET /admin/arquivos       -> server-issued ``arquivos_submission_id`` (own
                                 session namespace)
    POST issue                -> the SHARED S3-A route, purpose ``admin_arquivo``,
                                 target ``admin_arquivo_id`` (replacement only)
    browser -> Supabase       -> played against the injected canonical fake
    POST finalize             -> the SHARED S3-A route (bounded verify)
    POST business form        -> metadata + submission + ONE verified intent,
                                 NO bytes; one transaction: re-authorize,
                                 re-check custody, consume, attach / replace /
                                 retire, commit

Every Google entry point -- including the ARQUIVOS from-import binding and the
``arquivo_storage`` override -- is a tripwire (``arm_arquivos_google_tripwires``);
canonical paths must leave its call log EMPTY.

RED today: every node that drives the S3-B protocol fails because the admin
page renders no ARQUIVOS submission, the shared routes refuse ``admin_arquivo``
and the ARQUIVOS business / read / delete paths are Google- or
filesystem-only.  Nodes named ``*control*`` are current-HEAD GREEN controls
that must stay green.
"""

from __future__ import annotations

import io
import re
import secrets
from pathlib import Path
from urllib.parse import urlsplit

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
    INTENT_TTL_SECONDS,
    ISSUE_URL,
    MIB16,
    PDF,
    PNG,
    SIGNED_DOWNLOAD_TTL_SECONDS,
    STORAGE_ORIGIN,
    SUPABASE_URL,
    TEST_PUBLISHABLE_KEY,
    TEST_SECRET_KEY,
    TUS_CHUNK_BYTES,
    GoogleTouched,
    arm_google_tripwires,
    browser_upload,
    declaration,
    encrypted_pdf,
    hidden_value,
    padded_png,
    sha256,
)
from tests.storage_s3b_support import (
    ADMIN_PAGE,
    ARQUIVO_KEY_RE,
    ARQUIVO_SLOTS,
    ARQUIVOS_INTENT_IDS_FIELD,
    ARQUIVOS_SUBMISSION_FIELD,
    CREATE_URL,
    DELETE_URL,
    EDIT_URL,
    FORM_INTENT_FIELD_ATTR,
    FORM_PURPOSE_ATTR,
    FORM_SINGLE_ATTR,
    FORM_SUBMISSION_FIELD_ATTR,
    FORM_TARGET_ATTR,
    LEGACY_ARQUIVO_FILE_FIELD,
    LEGACY_GOOGLE_HELPERS,
    NON_STEADY_LEGACY_STATES,
    PURPOSE,
    STUDENT_DOWNLOAD_URL,
    STUDENT_VIEW_URL,
    LIVE_TARGET_INTENT_STATES,
    NON_LIVE_TARGET_INTENT_CASES,
    TARGET_FIELD,
    VIEW_URL,
    arm_arquivos_google_tripwires,
    assert_canonical_steady,
    png_with_dimensions,
    seed_admin_intent,
    seed_canonical_arquivo,
    seed_google_arquivo,
    seed_local_arquivo,
)
from tests.versioned_test_support import isolated_versioned_app_env

ROOT = Path(__file__).resolve().parents[1]
T0 = "2026-10-08 12:00:00"
_CODE_RE = re.compile(r"^[A-Z0-9_]{1,64}$")
_HEX128 = re.compile(r"^[0-9a-f]{32}$")
SLOTS = ARQUIVO_SLOTS
REFUSAL_STATUSES = (302, 400, 403, 404, 409, 410, 413, 415, 422)
GOOGLE_STATES = ("no_account", "no_app_credentials", "corrupt_token")
OLD_KEY = "arquivos/2026/10/" + "1" * 32
OTHER_KEY = "arquivos/2026/10/" + "2" * 32


class Clock:
    def __init__(self, now: str) -> None:
        self.now = now

    def __call__(self) -> str:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now = custody_common.add_seconds(self.now, seconds)


class RecordingStore(InMemoryObjectStore):
    """The canonical fake plus a record of reads / capabilities / downloads."""

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


class Raised:
    """A request that raised instead of answering (a 500 in production)."""

    status_code = None
    headers: dict = {}

    def __init__(self, exc: BaseException) -> None:
        self.exc = exc

    def __repr__(self) -> str:
        return f"Raised({type(self.exc).__name__}: {self.exc})"


def _call(function):
    try:
        return function()
    except Exception as exc:  # recorded and asserted: a canonical path must answer, not raise
        return Raised(exc)


def _answered(response) -> bool:
    return not isinstance(response, Raised) and response.status_code != 500


def _refused(response) -> bool:
    return _answered(response) and response.status_code in REFUSAL_STATUSES


# ---------------------------------------------------------------------------
# environment
# ---------------------------------------------------------------------------


def _setup(monkeypatch, *, tripwires=True):
    store = RecordingStore()
    monkeypatch.setitem(main.app.extensions, CANONICAL_STORE_EXTENSION, store)
    monkeypatch.setenv("SUPABASE_URL", SUPABASE_URL)
    monkeypatch.setenv("SUPABASE_SECRET_KEY", TEST_SECRET_KEY)
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", TEST_PUBLISHABLE_KEY)
    monkeypatch.setenv("SGAA_STORAGE_BUCKET", BUCKET)
    clock = Clock(T0)
    monkeypatch.setattr(custody_common, "utc_now_text", clock)
    calls = arm_arquivos_google_tripwires(monkeypatch, main.app) if tripwires else []
    return store, clock, calls


def _db():
    return main.get_db_connection()


def _make_admin(level="admin_total", overrides=None, label=None) -> int:
    label = label or secrets.token_hex(4)
    with main.app.app_context():
        conn = _db()
        user_id = conn.execute(
            "INSERT INTO usuarios(nome,email,senha,tipo,nivel_acesso) VALUES(?,?,'x','admin',?) RETURNING id",
            (f"S3B {label}", f"s3b-{label}@example.test", level),
        ).fetchone()[0]
        for recurso, escopo in (overrides or {}).items():
            conn.execute("INSERT INTO usuarios_permissoes_acesso(usuario_id,recurso,escopo) VALUES(?,?,?)",
                         (user_id, recurso, escopo))
        conn.commit()
    return int(user_id)


def _student(conn):
    return conn.execute(
        """SELECT a.id,a.usuario_id FROM alunos a JOIN usuarios u ON u.id=a.usuario_id
            WHERE u.tipo='aluno' ORDER BY a.id LIMIT 1"""
    ).fetchone()


@pytest.fixture
def env(tmp_path, monkeypatch):
    with isolated_versioned_app_env(tmp_path, "s3b-arquivos.db") as base:
        store, clock, calls = _setup(monkeypatch)
        admin_id = _make_admin("admin_total", label="total")
        with main.app.app_context():
            student = dict(_student(_db()))
        yield {**base, "store": store, "clock": clock, "google_calls": calls, "admin_id": admin_id,
               "student": student, "upload_root": main.app.config["UPLOAD_FOLDER"]}


@pytest.fixture
def legacy_env(tmp_path, monkeypatch):
    """Legacy Google custody really is consulted here (legacy reads / deletes stay S5's)."""
    from tests.test_arquivos_google_drive import FakeManagedStorage

    with isolated_versioned_app_env(tmp_path, "s3b-legacy.db") as base:
        store, clock, _calls = _setup(monkeypatch, tripwires=False)
        drive = FakeManagedStorage()
        monkeypatch.setitem(main.app.extensions, "arquivo_storage", drive)
        admin_id = _make_admin("admin_total", label="legacy")
        with main.app.app_context():
            student = dict(_student(_db()))
        yield {**base, "store": store, "clock": clock, "google_calls": [], "drive": drive, "admin_id": admin_id,
               "student": student, "upload_root": main.app.config["UPLOAD_FOLDER"]}


def _login(client, *, user_id, user_type, access_level=None):
    with client.session_transaction() as sess:
        sess.clear()
        sess["user_id"] = int(user_id)
        sess["user_type"] = user_type
        if access_level:
            sess["access_level"] = access_level
        stamp_auth_version(sess)


def _as_admin(env, user_id=None, level="admin_total", client=None):
    _login(client or env["client"], user_id=user_id or env["admin_id"], user_type="admin", access_level=level)


def _as_student(env):
    _login(env["client"], user_id=env["student"]["usuario_id"], user_type="aluno")


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


# ---------------------------------------------------------------------------
# protocol helpers
# ---------------------------------------------------------------------------


def _submission(env, *, edit_id=None, client=None) -> str:
    path = ADMIN_PAGE + (f"?edit_arquivo={edit_id}" if edit_id else "")
    page = (client or env["client"]).get(path)
    assert page.status_code == 200, (path, page.status_code)
    value = hidden_value(page.data, ARQUIVOS_SUBMISSION_FIELD)
    assert value is not None, f"{path} renders no server-issued {ARQUIVOS_SUBMISSION_FIELD} (S3-B form absent)"
    assert _HEX128.fullmatch(value), "the ARQUIVOS submission id must be 128-bit lowercase hex"
    return value


def _issue(env, submission, slot, content=PDF, filename="novo.pdf", mime="application/pdf", *, target=None,
           client=None, **extra):
    payload = {"purpose": PURPOSE, "submission_id": submission, "upload_slot_id": slot,
               **declaration(content, filename, mime), **extra}
    if target is not None:
        payload[TARGET_FIELD] = target
    return (client or env["client"]).post(ISSUE_URL, json=payload)


def _capability(response) -> dict:
    body = response.get_json(silent=True)
    assert response.status_code in (200, 201), (response.status_code, body)
    assert isinstance(body, dict) and body.get("intent_id"), body
    return body


def _upload(env, submission, slot, content=PDF, filename="novo.pdf", mime="application/pdf", *, target=None,
            client=None) -> str:
    client = client or env["client"]
    cap = _capability(_issue(env, submission, slot, content, filename, mime, target=target, client=client))
    browser_upload(env["store"], cap, content, mime)
    finalized = client.post(FINALIZE_URL.format(intent_id=cap["intent_id"]))
    assert finalized.status_code == 200 and (finalized.get_json() or {}).get("state") == "verified", (
        finalized.status_code, finalized.get_json(silent=True))
    return cap["intent_id"]


def _fields(titulo, descricao="Descricao S3-B", visivel="1"):
    return {"titulo": titulo, "descricao": descricao, "visivel": visivel}


def _create(env, submission, intent_ids, *, titulo="S3B criado", client=None, **fields):
    data = {**_fields(titulo, **fields), ARQUIVOS_SUBMISSION_FIELD: submission,
            ARQUIVOS_INTENT_IDS_FIELD: list(intent_ids)}
    return _call(lambda: (client or env["client"]).post(CREATE_URL, data=data))


def _replace(env, row_id, submission, intent_ids, *, titulo="S3B substituido", client=None):
    data = {**_fields(titulo), ARQUIVOS_SUBMISSION_FIELD: submission, ARQUIVOS_INTENT_IDS_FIELD: list(intent_ids)}
    return _call(lambda: (client or env["client"]).post(EDIT_URL.format(id=row_id), data=data))


def _delete(env, row_id, client=None):
    return _call(lambda: (client or env["client"]).post(DELETE_URL.format(id=row_id)))


def _rows_titled(titulo):
    with main.app.app_context():
        return [dict(r) for r in _db().execute("SELECT * FROM admin_arquivos WHERE titulo=? ORDER BY id", (titulo,))]


def _arquivo(row_id):
    with main.app.app_context():
        row = _db().execute("SELECT * FROM admin_arquivos WHERE id=?", (row_id,)).fetchone()
        return dict(row) if row else None


def _object(object_id):
    with main.app.app_context():
        row = _db().execute("SELECT * FROM storage_objects WHERE id=?", (object_id,)).fetchone()
        return dict(row) if row else None


def _intent(intent_id):
    with main.app.app_context():
        row = _db().execute("SELECT * FROM storage_upload_intents WHERE id=?", (intent_id,)).fetchone()
        return dict(row) if row else None


def _counts():
    with main.app.app_context():
        conn = _db()
        return {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                for t in ("admin_arquivos", "storage_objects", "storage_upload_intents")}


def _seed(kind, env, **kwargs):
    """Seed one ARQUIVOS row of the given custody kind; returns its id (and object id for canonical)."""
    with main.app.app_context():
        conn = _db()
        if kind == "canonical":
            result = seed_canonical_arquivo(conn, env["store"], uploader=env["admin_id"], now=T0,
                                            key=kwargs.pop("key", OLD_KEY), **kwargs)
        elif kind == "google":
            result = seed_google_arquivo(conn, uploader=env["admin_id"], now=T0, **kwargs)
        elif kind == "local":
            result = seed_local_arquivo(conn, env["upload_root"], **kwargs)
        else:  # pragma: no cover - test wiring
            raise AssertionError(kind)
        conn.commit()
    return result


def _seed_row_id(kind, env, **kwargs) -> int:
    result = _seed(kind, env, **kwargs)
    return result[0] if isinstance(result, tuple) else result


def _local_path(env, relative):
    return Path(env["upload_root"]).joinpath(*relative.split("/"))


def _flashes(client):
    with client.session_transaction() as sess:
        return list(sess.get("_flashes", []))


# ===========================================================================
# A. canonical create / Drive independence
# ===========================================================================


@pytest.mark.parametrize("google_state", GOOGLE_STATES)
def test_A1_create_completes_with_every_google_entry_point_tripwired(env, monkeypatch, google_state):
    _google_state(env, google_state, monkeypatch)
    _as_admin(env)
    submission = _submission(env)
    intent_id = _upload(env, submission, SLOTS[0], PDF, "manual.pdf")
    response = _create(env, submission, [intent_id], titulo="S3B A1")
    assert _answered(response) and response.status_code == 302, (response, env["google_calls"])
    [row] = _rows_titled("S3B A1")
    assert_canonical_steady(row)
    assert env["google_calls"] == [], env["google_calls"]


def test_A2_create_refuses_any_multipart_file_part_before_a_business_write(env):
    _as_admin(env)
    before = _counts()
    data = {**_fields("S3B A2"), "operation_key": "legacy-form-op-a2",
            LEGACY_ARQUIVO_FILE_FIELD: (io.BytesIO(PDF), "manual.pdf")}
    response = _call(lambda: env["client"].post(CREATE_URL, data=data, content_type="multipart/form-data"))
    assert env["google_calls"] == [], f"file bytes reached the Drive path: {env['google_calls']}"
    assert _refused(response), response
    assert _rows_titled("S3B A2") == [] and _counts() == before
    assert env["store"].calls == []


def test_A3_create_attach_requires_exactly_one_verified_admin_arquivo_intent(env):
    _as_admin(env)
    submission = _submission(env)
    first = _upload(env, submission, SLOTS[0], PDF, "a.pdf")
    second = _upload(env, submission, SLOTS[1], PNG, "b.png", "image/png")
    unverified = _capability(_issue(env, submission, SLOTS[2], PDF, "c.pdf"))["intent_id"]
    cases = {"no intent": [], "two intents": [first, second], "unverified": [unverified]}
    for label, ids in cases.items():
        before = _counts()
        states = {i: _intent(i)["state"] for i in ids}
        response = _create(env, submission, ids, titulo=f"S3B A3 {label}")
        assert _refused(response), (label, response)
        assert _counts() == before and _rows_titled(f"S3B A3 {label}") == [], label
        assert {i: _intent(i)["state"] for i in ids} == states, label
    accepted = _create(env, submission, [first], titulo="S3B A3 one")
    assert _answered(accepted) and accepted.status_code == 302
    assert len(_rows_titled("S3B A3 one")) == 1
    assert env["google_calls"] == []


def test_A4_attach_persists_exact_verified_metadata_and_leaves_the_mirror_pending(env):
    _as_admin(env)
    submission = _submission(env)
    content = padded_png(4096)
    intent_id = _upload(env, submission, SLOTS[0], content, "Relatorio Final.png", "image/png")
    response = _create(env, submission, [intent_id], titulo="S3B A4", descricao="Descricao A4", visivel="0")
    assert _answered(response) and response.status_code == 302, response
    [row] = _rows_titled("S3B A4")
    assert_canonical_steady(row)
    intent = _intent(intent_id)
    assert intent["state"] == "consumed" and intent["storage_object_id"] == row["storage_object_id"]
    assert row["operation_key"] == intent["operation_id"] == f"{submission}:{SLOTS[0]}"
    assert (row["mime_type"], row["size_bytes"], row["sha256"]) == ("image/png", len(content), sha256(content))
    assert row["original_filename"] == intent["original_filename"] == "Relatorio Final.png"
    assert row["filename"] and "/" not in row["filename"] and "\\" not in row["filename"]
    assert (row["uploader_user_id"], row["visivel"], row["descricao"]) == (env["admin_id"], 0, "Descricao A4")
    assert (row["prior_provider"], row["prior_locator"]) == (None, None)
    obj = _object(row["storage_object_id"])
    assert (obj["lifecycle_state"], obj["drive_sync_state"], obj["drive_account_key"], obj["origin"]) == (
        "active", "pending", None, "direct_upload")
    assert obj["lease_token"] is None and obj["storage_key"] == intent["storage_key"]
    assert re.fullmatch(ARQUIVO_KEY_RE, obj["storage_key"])
    assert (obj["sha256"], obj["size_bytes"], obj["mime_type"]) == (row["sha256"], row["size_bytes"], "image/png")
    with main.app.app_context():
        assert _db().execute("SELECT count(*) FROM storage_worker_status").fetchone()[0] == 0  # no S4 worker
    assert "upload" not in env["store"].calls and "delete" not in env["store"].calls
    assert env["google_calls"] == []


def test_A4_a_posted_legacy_operation_key_is_not_authoritative(env):
    _as_admin(env)
    submission = _submission(env)
    intent_id = _upload(env, submission, SLOTS[0], PDF)
    data = {**_fields("S3B A4 op"), "operation_key": "browser-chosen-operation",
            ARQUIVOS_SUBMISSION_FIELD: submission, ARQUIVOS_INTENT_IDS_FIELD: [intent_id]}
    response = _call(lambda: env["client"].post(CREATE_URL, data=data))
    assert _answered(response) and response.status_code == 302, response
    [row] = _rows_titled("S3B A4 op")
    assert row["operation_key"] == _intent(intent_id)["operation_id"] == f"{submission}:{SLOTS[0]}"
    assert env["google_calls"] == []


def test_A5_lost_response_replay_reuses_the_row_and_another_admin_cannot_replay(env):
    _as_admin(env)
    submission = _submission(env)
    intent_id = _upload(env, submission, SLOTS[0], PDF)
    first = _create(env, submission, [intent_id], titulo="S3B A5")
    assert _answered(first) and first.status_code == 302, first
    after_first = _counts()
    again = _create(env, submission, [intent_id], titulo="S3B A5")  # response lost, the admin retries
    assert _answered(again) and again.status_code == 302, again
    assert _counts() == after_first and len(_rows_titled("S3B A5")) == 1
    _as_admin(env, user_id=_make_admin("admin_total", label="thief"))
    stolen = _create(env, submission, [intent_id], titulo="S3B A5 theft")
    assert _answered(stolen), stolen
    assert _rows_titled("S3B A5 theft") == [] and _counts() == after_first
    assert env["google_calls"] == []


# ===========================================================================
# B. issue / capability
# ===========================================================================


def test_B1_arquivos_edit_admin_gets_a_signed_tus_capability_for_a_server_chosen_key(env):
    editor = _make_admin("administrativo", overrides={"arquivos": "edit"}, label="editor")
    _as_admin(env, user_id=editor, level="administrativo")
    submission = _submission(env)
    response = _issue(env, submission, SLOTS[0], PDF, "manual.pdf")
    cap = _capability(response)
    assert "no-store" in response.headers.get("Cache-Control", "")
    assert cap["tus_endpoint"] == DIRECT_TUS_ENDPOINT
    assert cap["tus_endpoint"].startswith(f"{STORAGE_ORIGIN}/")
    assert cap["tus_endpoint"].endswith("/storage/v1/upload/resumable/sign")
    assert cap["apikey"] == TEST_PUBLISHABLE_KEY and cap["apikey"].startswith("sb_publishable_")
    text = response.get_data(as_text=True)
    assert "sb_secret_" not in text and TEST_SECRET_KEY not in text
    assert "authorization" not in {k.lower() for k in cap} and "bearer" not in text.lower()
    assert cap["chunk_size"] == TUS_CHUNK_BYTES and cap["bucket"] == BUCKET
    assert re.fullmatch(ARQUIVO_KEY_RE, cap["object_name"]), cap["object_name"]
    assert env["store"].signed_uploads == [(BUCKET, cap["object_name"])]
    row = _intent(cap["intent_id"])
    assert (row["actor_user_id"], row["purpose"], row["state"]) == (editor, PURPOSE, "issued")
    assert (row["admin_arquivo_id"], row["requisicao_id"]) == (None, None)
    assert row["operation_id"] == f"{submission}:{SLOTS[0]}"
    assert row["storage_key"] == cap["object_name"] and cap["upload_token"] not in str(row)
    # x-upsert false: once the bytes landed, a replayed issue never re-opens the key.
    browser_upload(env["store"], cap, PDF, "application/pdf")
    replay = _issue(env, submission, SLOTS[0], PDF, "manual.pdf")
    assert replay.status_code == 409 and replay.get_json()["error"] == "UPLOAD_ALREADY_RECEIVED"
    assert env["store"].objects[(BUCKET, cap["object_name"])] == (PDF, "application/pdf")
    assert env["google_calls"] == []


@pytest.mark.parametrize("actor", ["unauthenticated", "student", "consultivo", "arquivos-view-override"])
def test_B2_issue_refuses_actors_without_arquivos_edit(env, actor):
    submission = secrets.token_hex(16)
    if actor == "student":
        _as_student(env)
    elif actor == "consultivo":
        _as_admin(env, user_id=_make_admin("consultivo", label="consult"), level="consultivo")
        submission = _submission(env)
    elif actor == "arquivos-view-override":
        _as_admin(env, user_id=_make_admin("admin_total", overrides={"arquivos": "view"}, label="viewer"))
        submission = _submission(env)
    response = _issue(env, submission, SLOTS[0], PDF, "manual.pdf")
    assert response.status_code in (401, 403), (actor, response.status_code, response.get_json(silent=True))
    assert _CODE_RE.fullmatch(str((response.get_json(silent=True) or {}).get("error", "")))
    assert env["store"].signed_uploads == [] and _counts()["storage_upload_intents"] == 0


def test_B3_client_supplied_bucket_or_key_never_selects_authority(env):
    _as_admin(env)
    submission = _submission(env)
    cap = _capability(_issue(env, submission, SLOTS[0], PDF, "manual.pdf", bucket="attacker-bucket",
                             object_name="arquivos/../../x", key="comprovantes/2026/10/" + "f" * 32,
                             storage_key="x", storage_bucket="y"))
    assert cap["bucket"] == BUCKET and re.fullmatch(ARQUIVO_KEY_RE, cap["object_name"])
    row = _intent(cap["intent_id"])
    assert (row["storage_bucket"], row["storage_key"]) == (BUCKET, cap["object_name"])


def test_B4_target_binding_create_is_null_replacement_is_exact_and_unknown_is_not_found(env):
    row_id, _object_id = _seed("canonical", env)
    _as_admin(env)
    submission = _submission(env, edit_id=row_id)
    create = _capability(_issue(env, submission, SLOTS[0], PDF))
    replace = _capability(_issue(env, submission, SLOTS[1], PNG, "p.png", "image/png", target=row_id))
    assert _intent(create["intent_id"])["admin_arquivo_id"] is None
    assert _intent(replace["intent_id"])["admin_arquivo_id"] == row_id
    missing = _issue(env, submission, SLOTS[2], PDF, target=row_id + 999)
    assert missing.status_code == 404, missing.status_code
    for bad in ("abc", 0, -1, True, 1.5):
        refused = _issue(env, submission, SLOTS[3], PDF, target=bad)
        assert 400 <= refused.status_code < 500 and refused.status_code != 201, (bad, refused.status_code)
    assert env["google_calls"] == []


@pytest.mark.parametrize("source", ["canonical", "google-active", "local-legacy-active"])
def test_B4_replacement_issue_is_accepted_from_each_steady_source(env, source):
    kind = {"canonical": "canonical", "google-active": "google", "local-legacy-active": "local"}[source]
    row_id = _seed_row_id(kind, env)
    _as_admin(env)
    submission = _submission(env, edit_id=row_id)
    cap = _capability(_issue(env, submission, SLOTS[0], PNG, "p.png", "image/png", target=row_id))
    assert _intent(cap["intent_id"])["admin_arquivo_id"] == row_id
    assert env["google_calls"] == []


@pytest.mark.parametrize(("label", "provider", "overrides"), NON_STEADY_LEGACY_STATES,
                         ids=[case[0] for case in NON_STEADY_LEGACY_STATES])
def test_B4_replacement_issue_from_a_non_steady_legacy_state_is_refused(env, label, provider, overrides):
    kind = "google" if provider == "google" else "local"
    row_id = _seed_row_id(kind, env, **overrides)
    before = _arquivo(row_id)
    _as_admin(env)
    submission = _submission(env, edit_id=row_id)
    response = _issue(env, submission, SLOTS[0], PNG, "p.png", "image/png", target=row_id)
    assert response.status_code in (409, 422), (label, response.status_code, response.get_json(silent=True))
    assert _CODE_RE.fullmatch(str((response.get_json(silent=True) or {}).get("error", "")))
    assert env["store"].signed_uploads == [] and _counts()["storage_upload_intents"] == 0
    assert _arquivo(row_id) == before
    assert env["google_calls"] == []


def test_B5_same_operation_replays_a_different_declaration_conflicts_and_a_new_slot_is_new(env):
    row_id, _object_id = _seed("canonical", env)
    _as_admin(env)
    submission = _submission(env, edit_id=row_id)
    first = _capability(_issue(env, submission, SLOTS[0], PDF, "p.pdf"))
    again = _capability(_issue(env, submission, SLOTS[0], PDF, "p.pdf"))
    assert again["intent_id"] == first["intent_id"] and again["object_name"] == first["object_name"]
    conflict = _issue(env, submission, SLOTS[0], PNG, "p.png", "image/png")
    assert conflict.status_code == 409 and conflict.get_json()["error"] == "INTENT_OPERATION_CONFLICT"
    retarget = _issue(env, submission, SLOTS[0], PDF, "p.pdf", target=row_id)
    assert retarget.status_code == 409, retarget.status_code
    other = _capability(_issue(env, submission, SLOTS[1], PNG, "p.png", "image/png"))
    assert other["intent_id"] != first["intent_id"] and other["object_name"] != first["object_name"]
    assert _intent(other["intent_id"])["operation_id"] == f"{submission}:{SLOTS[1]}"


def test_B6_arquivos_submissions_live_in_their_own_session_namespace(env):
    _as_admin(env)
    arquivos_submission = _submission(env)
    page = env["client"].get("/admin/requisicoes")
    comprovantes_submission = hidden_value(page.data, "comprovantes_submission_id")
    assert comprovantes_submission and comprovantes_submission != arquivos_submission
    with env["client"].session_transaction() as sess:
        assert arquivos_submission not in (sess.get("comprovantes_submissions") or {})
    cross = _issue(env, comprovantes_submission, SLOTS[0], PDF)
    assert 400 <= cross.status_code < 500 and cross.status_code != 404, cross.status_code
    reverse = env["client"].post(ISSUE_URL, json={
        "purpose": "comprovante", "submission_id": arquivos_submission, "upload_slot_id": SLOTS[1],
        **declaration(PDF, "p.pdf", "application/pdf")})
    assert 400 <= reverse.status_code < 500 and reverse.status_code != 404, reverse.status_code
    assert env["store"].signed_uploads == []


# ===========================================================================
# C. finalize / verification
# ===========================================================================


def test_C1_finalize_verifies_an_admin_arquivo_intent_server_side_and_is_idempotent(env):
    _as_admin(env)
    submission = _submission(env)
    cap = _capability(_issue(env, submission, SLOTS[0], PDF, "p.pdf"))
    browser_upload(env["store"], cap, PDF, "application/pdf")
    url = FINALIZE_URL.format(intent_id=cap["intent_id"])
    lies = {"size_bytes": 1, "sha256": "0" * 64, "mime_type": "image/png", "bucket": "x", "key": "y"}
    first = env["client"].post(url, json=lies)
    assert first.status_code == 200 and (first.get_json() or {}).get("state") == "verified"
    verified = _intent(cap["intent_id"])
    assert verified["state"] == "verified" and verified["declared_sha256"] == sha256(PDF)
    assert env["store"].read_limits and set(env["store"].read_limits) == {MIB16}
    second = env["client"].post(url)
    assert second.status_code == 200 and _intent(cap["intent_id"])["verified_at"] == verified["verified_at"]
    assert env["google_calls"] == []


@pytest.mark.parametrize(
    ("declared", "filename", "mime", "stored", "stored_type"),
    [
        (PNG, "doc.pdf", "application/pdf", PNG, "application/pdf"),
        (PDF, "doc.pdf", "application/pdf", PDF, "image/png"),
        ("ENCRYPTED", "doc.pdf", "application/pdf", "ENCRYPTED", "application/pdf"),
        (PDF, "doc.pdf", "application/pdf", b"", "application/pdf"),
        (PDF, "doc.pdf", "application/pdf", "OVERSIZED", "application/pdf"),
        (PNG, "doc.png", "image/png", padded_png(len(PNG) + 64), "image/png"),
        ("WIDE", "wide.png", "image/png", "WIDE", "image/png"),
        ("PIXELS", "huge.png", "image/png", "PIXELS", "image/png"),
    ],
    ids=["png-bytes-declared-pdf", "wrong-storage-content-type", "encrypted-pdf", "zero-bytes", "oversized",
         "size-or-sha-mismatch", "image-dimension-limit", "image-pixel-limit"],
)
def test_C2_finalize_fails_closed_with_a_sanitized_code(env, declared, filename, mime, stored, stored_type):
    specials = {"ENCRYPTED": encrypted_pdf, "WIDE": lambda: png_with_dimensions(20001, 1),
                "PIXELS": lambda: png_with_dimensions(4000, 4000)}
    if declared in specials:
        declared = stored = specials[declared]()
    if stored == "OVERSIZED":
        stored = padded_png(MIB16 + 1)
    _as_admin(env)
    submission = _submission(env)
    cap = _capability(_issue(env, submission, SLOTS[0], declared, filename, mime))
    env["store"].objects[(BUCKET, cap["object_name"])] = (stored, stored_type)
    response = env["client"].post(FINALIZE_URL.format(intent_id=cap["intent_id"]))
    body = response.get_json(silent=True) or {}
    assert 400 <= response.status_code < 500 and response.status_code != 404, (response.status_code, body)
    assert _CODE_RE.fullmatch(str(body.get("error", ""))), body
    assert _intent(cap["intent_id"])["state"] == "rejected"
    assert all(limit <= MIB16 for limit in env["store"].read_limits)
    for secret in (TEST_SECRET_KEY, "memory://", cap["upload_token"]):
        assert secret.encode() not in response.data


def test_C2_finalize_of_a_missing_object_or_provider_outage_keeps_the_intent_retryable(env):
    _as_admin(env)
    submission = _submission(env)
    cap = _capability(_issue(env, submission, SLOTS[0], PDF))
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
    assert env["google_calls"] == []


def test_C3_owner_finalizes_and_another_actor_gets_the_indistinguishable_not_found(env):
    _as_admin(env)
    with main.app.app_context():
        intent = seed_admin_intent(_db(), env["store"], actor=env["admin_id"], submission_id=secrets.token_hex(16),
                                   slot=SLOTS[0], content=PDF, now=T0, verify=False)
    _as_admin(env, user_id=_make_admin("admin_total", label="other-finalizer"))
    stolen = env["client"].post(FINALIZE_URL.format(intent_id=intent.id))
    unknown = env["client"].post(FINALIZE_URL.format(intent_id=secrets.token_hex(16)))
    assert stolen.status_code == unknown.status_code == 404
    assert stolen.get_json() == unknown.get_json()
    assert _intent(intent.id)["state"] == "issued"
    _as_admin(env)
    owner = env["client"].post(FINALIZE_URL.format(intent_id=intent.id))
    assert owner.status_code == 200 and owner.get_json().get("state") == "verified", (
        owner.status_code, owner.get_json(silent=True))


# ===========================================================================
# D. replacement
# ===========================================================================


def _replace_through_protocol(env, row_id, content=PNG, filename="novo.png", mime="image/png", slot=SLOTS[0]):
    submission = _submission(env, edit_id=row_id)
    intent_id = _upload(env, submission, slot, content, filename, mime, target=row_id)
    return submission, intent_id, _replace(env, row_id, submission, [intent_id])


def test_D1_canonical_replacement_attaches_a_new_immutable_object_and_retires_the_old(env):
    row_id, old_object_id = _seed("canonical", env)
    _as_admin(env)
    _submission_id, intent_id, response = _replace_through_protocol(env, row_id)
    assert _answered(response) and response.status_code == 302, response
    row = _arquivo(row_id)
    assert_canonical_steady(row)
    intent = _intent(intent_id)
    assert row["storage_object_id"] not in (None, old_object_id)
    assert intent["state"] == "consumed" and intent["storage_object_id"] == row["storage_object_id"]
    assert row["operation_key"] == intent["operation_id"]
    assert (row["mime_type"], row["size_bytes"], row["sha256"]) == ("image/png", len(PNG), sha256(PNG))
    old, new = _object(old_object_id), _object(row["storage_object_id"])
    assert (old["lifecycle_state"], new["lifecycle_state"]) == ("retired", "active")
    assert old["retired_at"] is not None and old["purge_after"] is None
    assert new["storage_key"] != old["storage_key"]
    assert env["store"].objects[(BUCKET, OLD_KEY)] == (PDF, "application/pdf")  # never deleted / overwritten
    assert (BUCKET, new["storage_key"]) in env["store"].objects
    assert "delete" not in env["store"].calls and "upload" not in env["store"].calls
    assert env["google_calls"] == []


def test_D2_google_active_replacement_preserves_the_drive_locator_as_residue_without_google(env):
    row_id = _seed_row_id("google", env, remote_file_id="drv-old-a1")
    _as_admin(env)
    _submission_id, intent_id, response = _replace_through_protocol(env, row_id)
    assert _answered(response) and response.status_code == 302, (response, env["google_calls"])
    row = _arquivo(row_id)
    assert_canonical_steady(row)
    assert (row["prior_provider"], row["prior_locator"]) == ("google", "drv-old-a1")
    assert _intent(intent_id)["storage_object_id"] == row["storage_object_id"]
    assert env["google_calls"] == [], "no Drive trash / cleanup on a canonical replacement"


def test_D3_local_legacy_replacement_preserves_the_local_locator_and_leaves_the_file(env):
    relative = "arquivos/manual-legado.pdf"
    row_id = _seed_row_id("local", env, filename=relative)
    _as_admin(env)
    _submission_id, _intent_id, response = _replace_through_protocol(env, row_id)
    assert _answered(response) and response.status_code == 302, response
    row = _arquivo(row_id)
    assert_canonical_steady(row)
    assert (row["prior_provider"], row["prior_locator"]) == ("local_legacy", relative)
    assert _local_path(env, relative).read_bytes() == PDF
    assert env["google_calls"] == []


@pytest.mark.parametrize(("label", "provider", "overrides"), NON_STEADY_LEGACY_STATES,
                         ids=[case[0] for case in NON_STEADY_LEGACY_STATES])
def test_D4_attach_refuses_a_source_that_became_non_steady_without_auto_heal(env, label, provider, overrides):
    """Issued against a steady source; the row then entered a non-steady legacy state.

    The custody locator (Drive id / local filename) is kept, so only the state
    rule -- not the stale-custody rule -- can refuse it.
    """
    kind = "google" if provider == "google" else "local"
    row_id = _seed_row_id(kind, env)
    _as_admin(env)
    submission = _submission(env, edit_id=row_id)
    intent_id = _upload(env, submission, SLOTS[0], PNG, "p.png", "image/png", target=row_id)
    flip = {k: v for k, v in overrides.items() if k not in ("remote_file_id", "remote_parent_id")}
    with main.app.app_context():
        conn = _db()
        conn.execute(f"UPDATE admin_arquivos SET {', '.join(f'{k}=?' for k in flip)} WHERE id=?",
                     (*flip.values(), row_id))
        conn.commit()
    before, counts = _arquivo(row_id), _counts()
    response = _replace(env, row_id, submission, [intent_id])
    assert _refused(response), (label, response)
    assert _arquivo(row_id) == before and _counts() == counts
    assert _intent(intent_id)["state"] == "verified"
    assert env["google_calls"] == []


def test_D5_db_fault_rolls_back_the_whole_replacement_then_retry_succeeds(env, monkeypatch):
    row_id, old_object_id = _seed("canonical", env)
    _as_admin(env)
    submission = _submission(env, edit_id=row_id)
    intent_id = _upload(env, submission, SLOTS[0], PNG, "p.png", "image/png", target=row_id)
    original = intents.consume_intent
    fired = []

    def faulty(*args, **kwargs):
        result = original(*args, **kwargs)
        fired.append(True)
        raise RuntimeError("injected fault after consume")

    monkeypatch.setattr(intents, "consume_intent", faulty)
    before, counts = _arquivo(row_id), _counts()
    _replace(env, row_id, submission, [intent_id])
    assert fired, "the replacement must consume through app.storage.upload_intents.consume_intent"
    assert _arquivo(row_id) == before and _counts() == counts
    assert _object(old_object_id)["lifecycle_state"] == "active"
    assert _intent(intent_id)["state"] == "verified"
    monkeypatch.setattr(intents, "consume_intent", original)
    retry = _replace(env, row_id, submission, [intent_id])
    assert _answered(retry) and retry.status_code == 302, retry
    assert _arquivo(row_id)["storage_object_id"] != old_object_id
    assert _object(old_object_id)["lifecycle_state"] == "retired"


def test_D6_replacement_never_overwrites_an_existing_object_in_place(env):
    row_id, old_object_id = _seed("canonical", env)
    _as_admin(env)
    submission = _submission(env, edit_id=row_id)
    cap = _capability(_issue(env, submission, SLOTS[0], PNG, "p.png", "image/png", target=row_id))
    assert cap["object_name"] != OLD_KEY and cap["object_name"] != _object(old_object_id)["storage_key"]
    browser_upload(env["store"], cap, PNG, "image/png")
    replay = _issue(env, submission, SLOTS[0], PNG, "p.png", "image/png", target=row_id)
    assert replay.status_code == 409 and replay.get_json()["error"] == "UPLOAD_ALREADY_RECEIVED"
    assert env["store"].objects[(BUCKET, OLD_KEY)] == (PDF, "application/pdf")
    assert env["store"].objects[(BUCKET, cap["object_name"])] == (PNG, "image/png")


def test_D7_replacement_refuses_any_multipart_file_part(env):
    row_id, object_id = _seed("canonical", env)
    _as_admin(env)
    before, counts = _arquivo(row_id), _counts()
    data = {**_fields("S3B D7"), "operation_key": "legacy-form-op-d7",
            LEGACY_ARQUIVO_FILE_FIELD: (io.BytesIO(PNG), "novo.png")}
    response = _call(lambda: env["client"].post(EDIT_URL.format(id=row_id), data=data,
                                                content_type="multipart/form-data"))
    assert env["google_calls"] == [], env["google_calls"]
    assert _refused(response), response
    assert _arquivo(row_id) == before and _counts() == counts
    assert _object(object_id)["lifecycle_state"] == "active" and env["store"].calls == []


# ===========================================================================
# R. stale replacement (expected custody captured at issue)
# ===========================================================================


@pytest.mark.parametrize("source", ["canonical", "google", "local"])
def test_R_a_second_replacement_issued_against_the_same_original_custody_is_stale(env, source):
    original_object_id = None
    if source == "canonical":
        row_id, original_object_id = _seed("canonical", env)
    else:
        row_id = _seed_row_id(source, env)
    _as_admin(env)
    first_submission = _submission(env, edit_id=row_id)
    first = _upload(env, first_submission, SLOTS[0], PNG, "um.png", "image/png", target=row_id)
    second_submission = _submission(env, edit_id=row_id)
    second_content = padded_png(2048)
    second = _upload(env, second_submission, SLOTS[1], second_content, "dois.png", "image/png", target=row_id)

    won = _replace(env, row_id, first_submission, [first], titulo="S3B R primeiro")
    assert _answered(won) and won.status_code == 302, won
    after_first = _arquivo(row_id)
    assert_canonical_steady(after_first)
    winner_object_id = after_first["storage_object_id"]
    assert _intent(first)["storage_object_id"] == winner_object_id
    retired_at = _object(original_object_id)["retired_at"] if original_object_id else None
    counts = _counts()

    stale = _replace(env, row_id, second_submission, [second], titulo="S3B R segundo")
    assert _refused(stale), stale
    assert _arquivo(row_id) == after_first, "a stale replacement mutated the row"
    assert _object(winner_object_id)["lifecycle_state"] == "active", "the stale attach retired the current object"
    if original_object_id:
        original = _object(original_object_id)
        assert (original["lifecycle_state"], original["retired_at"]) == ("retired", retired_at)
    loser = _intent(second)
    assert loser["state"] != "consumed" and loser["storage_object_id"] is None
    assert _counts() == counts
    assert env["google_calls"] == []


# ===========================================================================
# E. reads
# ===========================================================================


def _assert_signed_redirect(env, response, key, *, download_name):
    assert _answered(response) and response.status_code == 302, response
    assert response.headers["Location"] == f"memory://download/{BUCKET}/{key}"
    assert "no-store" in response.headers.get("Cache-Control", "")
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert PDF not in response.data
    assert env["store"].downloads[-1] == dict(bucket=BUCKET, key=key, expires_in=SIGNED_DOWNLOAD_TTL_SECONDS,
                                              download_name=download_name)


def test_E1_admin_visualizar_of_a_canonical_row_redirects_to_a_short_lived_signed_url(env):
    row_id, _object_id = _seed("canonical", env)
    _as_admin(env)
    response = _call(lambda: env["client"].get(VIEW_URL.format(id=row_id)))
    _assert_signed_redirect(env, response, OLD_KEY, download_name=None)
    assert env["google_calls"] == []


def test_E2_student_reads_a_visible_canonical_row_inline_and_named_and_never_a_hidden_one(env):
    visible_id, _o = _seed("canonical", env, original="manual.pdf")
    hidden_id, _h = _seed("canonical", env, key=OTHER_KEY, visivel=0, operation_key="seed-hidden-op",
                          titulo="Oculto")
    _as_student(env)
    inline = _call(lambda: env["client"].get(STUDENT_VIEW_URL.format(id=visible_id)))
    _assert_signed_redirect(env, inline, OLD_KEY, download_name=None)
    named = _call(lambda: env["client"].get(STUDENT_DOWNLOAD_URL.format(id=visible_id)))
    _assert_signed_redirect(env, named, OLD_KEY, download_name="manual.pdf")
    downloads = len(env["store"].downloads)
    for url in (STUDENT_VIEW_URL, STUDENT_DOWNLOAD_URL):
        denied = _call(lambda: env["client"].get(url.format(id=hidden_id)))
        assert _answered(denied) and denied.status_code == 302
        assert denied.headers["Location"].endswith("/aluno/arquivos")
    assert len(env["store"].downloads) == downloads
    assert env["google_calls"] == []


def test_E3_canonical_provider_outage_never_falls_back_to_google(env):
    row_id, _object_id = _seed("canonical", env)
    _as_admin(env)
    _assert_signed_redirect(env, _call(lambda: env["client"].get(VIEW_URL.format(id=row_id))), OLD_KEY,
                            download_name=None)
    env["store"].fail_next("STORAGE_PROVIDER_UNAVAILABLE")
    outage = _call(lambda: env["client"].get(VIEW_URL.format(id=row_id)))
    assert _answered(outage), outage
    assert not str(outage.headers.get("Location", "")).startswith("memory://")
    assert PDF not in outage.data
    assert env["google_calls"] == []


def test_E4_retired_or_missing_canonical_object_is_not_found(env):
    retired_id, retired_object = _seed("canonical", env)
    missing_id, _missing_object = _seed("canonical", env, key=OTHER_KEY, operation_key="seed-missing-op",
                                        titulo="Sem objeto")
    del env["store"].objects[(BUCKET, OTHER_KEY)]
    _as_admin(env)
    _assert_signed_redirect(env, _call(lambda: env["client"].get(VIEW_URL.format(id=retired_id))), OLD_KEY,
                            download_name=None)
    with main.app.app_context():
        conn = _db()
        conn.execute("UPDATE storage_objects SET lifecycle_state='retired', retired_at=? WHERE id=?",
                     (T0, retired_object))
        conn.commit()
    for row_id in (retired_id, missing_id):
        response = _call(lambda: env["client"].get(VIEW_URL.format(id=row_id)))
        assert _answered(response), response
        assert not str(response.headers.get("Location", "")).startswith("memory://")
        assert PDF not in response.data
    assert env["google_calls"] == []


def test_E5_control_legacy_google_and_local_reads_keep_their_legacy_behavior(legacy_env):
    env = legacy_env
    with main.app.app_context():
        conn = _db()
        google_id = seed_google_arquivo(conn, uploader=env["admin_id"], now=T0, remote_file_id="remote-legacy-1")
        local_id = seed_local_arquivo(conn, env["upload_root"], content=PNG, filename="arquivos/legado.png")
        conn.commit()
    env["drive"].files["remote-legacy-1"] = {"id": "remote-legacy-1", "name": "x", "content": PDF,
                                             "sha256": sha256(PDF), "operation_key": "seed-google-op",
                                             "properties": {}}
    _as_admin(env)
    google = env["client"].get(VIEW_URL.format(id=google_id))
    local = env["client"].get(VIEW_URL.format(id=local_id))
    assert (google.status_code, google.data) == (200, PDF)
    assert (local.status_code, local.data) == (200, PNG)
    assert env["store"].downloads == []


def test_E6_a_transitional_row_with_a_storage_object_uses_canonical_dispatch(env):
    with main.app.app_context():
        conn = _db()
        from tests.storage_s3b_support import seed_object

        object_id = seed_object(conn, key=OTHER_KEY, content=PDF, mime="application/pdf",
                                uploader=env["admin_id"], now=T0)
        row_id = seed_local_arquivo(conn, env["upload_root"], filename="arquivos/sem-arquivo.pdf",
                                    write_file=False, storage_object_id=object_id)
        conn.commit()
    env["store"].objects[(BUCKET, OTHER_KEY)] = (PDF, "application/pdf")
    _as_admin(env)
    response = _call(lambda: env["client"].get(VIEW_URL.format(id=row_id)))
    _assert_signed_redirect(env, response, OTHER_KEY, download_name=None)
    assert env["google_calls"] == []


# ===========================================================================
# F. delete
# ===========================================================================


def test_F1_canonical_delete_retires_the_object_and_deletes_the_row(env):
    row_id, object_id = _seed("canonical", env)
    _as_admin(env)
    response = _delete(env, row_id)
    assert _answered(response) and response.status_code == 302, response
    assert _arquivo(row_id) is None
    obj = _object(object_id)
    assert obj["lifecycle_state"] == "retired" and obj["retired_at"] is not None and obj["purge_after"] is None
    assert env["store"].objects[(BUCKET, OLD_KEY)] == (PDF, "application/pdf")
    assert "delete" not in env["store"].calls
    assert env["google_calls"] == []


@pytest.mark.parametrize("residue", ["google", "local"])
def test_F2_canonical_delete_with_legacy_residue_never_touches_the_residue(env, residue):
    relative = "arquivos/residuo-antigo.pdf"
    if residue == "google":
        prior = {"prior_provider": "google", "prior_locator": "drv-residue-1"}
    else:
        prior = {"prior_provider": "local_legacy", "prior_locator": relative}
        path = _local_path(env, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(PNG)
    row_id, object_id = _seed("canonical", env, residue=prior)
    tables_before = _tables()
    _as_admin(env)
    response = _delete(env, row_id)
    assert _answered(response) and response.status_code == 302, response
    assert _arquivo(row_id) is None and _object(object_id)["lifecycle_state"] == "retired"
    if residue == "local":
        assert _local_path(env, relative).read_bytes() == PNG
    assert _tables() == tables_before, "no tombstone table / schema change"
    assert "delete" not in env["store"].calls
    assert env["google_calls"] == []


def _tables():
    with main.app.app_context():
        return sorted(r[0] for r in _db().execute("SELECT name FROM sqlite_master WHERE type='table'"))


def test_F3_control_legacy_google_and_local_delete_keep_their_legacy_behavior(legacy_env):
    env = legacy_env
    with main.app.app_context():
        conn = _db()
        google_id = seed_google_arquivo(conn, uploader=env["admin_id"], now=T0, remote_file_id="remote-del-1")
        local_id = seed_local_arquivo(conn, env["upload_root"], filename="arquivos/apagar.pdf")
        conn.commit()
    _as_admin(env)
    assert env["client"].post(DELETE_URL.format(id=google_id)).status_code == 302
    assert env["client"].post(DELETE_URL.format(id=local_id)).status_code == 302
    assert _arquivo(google_id) is None and _arquivo(local_id) is None
    assert env["drive"].trashed == ["remote-del-1"]
    assert not _local_path(env, "arquivos/apagar.pdf").exists()


def test_F4_control_arquivos_edit_alone_cannot_delete_a_canonical_row(env):
    row_id, object_id = _seed("canonical", env)
    editor = _make_admin("administrativo", overrides={"arquivos": "edit"}, label="edit-only")
    _as_admin(env, user_id=editor, level="administrativo")
    response = _delete(env, row_id)
    assert _answered(response) and response.status_code == 302
    assert response.headers["Location"].endswith("/admin/dashboard")
    assert _arquivo(row_id) is not None and _object(object_id)["lifecycle_state"] == "active"
    assert env["google_calls"] == []


def _seed_target_intent(env, row_id, case):
    """A target ``admin_arquivo`` intent in the given delete-gate case (S2 primitives)."""
    state = case.split("-")[0]
    with main.app.app_context():
        conn = _db()
        intent = seed_admin_intent(conn, env["store"], actor=env["admin_id"], submission_id=secrets.token_hex(16),
                                   slot=SLOTS[0], content=PNG, mime="image/png", now=env["clock"].now,
                                   admin_arquivo_id=row_id, verify=(state == "verified"))
        if state == "rejected":
            with write_transaction(conn):
                intents.reject_intent(conn, intent_id=intent.id, rejection_code="MIME_MISMATCH", now=env["clock"].now)
        if state == "expired":
            env["clock"].advance(INTENT_TTL_SECONDS + 1)
            with write_transaction(conn):
                assert intents.expire_intents(conn, now=env["clock"].now) == 1
        if case.endswith("-past-expiry"):
            # The window closed but nothing ran the lifecycle: still issued / verified in the row.
            env["clock"].advance(INTENT_TTL_SECONDS + 1)
    return intent


def _assert_allowed_canonical_delete(env, row_id, object_id, response):
    assert _answered(response) and response.status_code == 302, response
    assert _arquivo(row_id) is None
    obj = _object(object_id)
    assert obj["lifecycle_state"] == "retired" and obj["retired_at"] is not None and obj["purge_after"] is None
    assert (BUCKET, obj["storage_key"]) in env["store"].objects and "delete" not in env["store"].calls
    assert env["google_calls"] == []


@pytest.mark.parametrize("state", LIVE_TARGET_INTENT_STATES)
def test_F5_delete_is_refused_while_a_live_target_intent_exists(env, state):
    row_id, object_id = _seed("canonical", env)
    intent = _seed_target_intent(env, row_id, state)
    assert _intent(intent.id)["state"] == state and _intent(intent.id)["expires_at"] > env["clock"].now
    _as_admin(env)
    refused = _delete(env, row_id)
    assert _refused(refused), refused
    assert _arquivo(row_id) is not None, "the row vanished under a live replacement intent"
    assert _intent(intent.id) is not None and _intent(intent.id)["state"] == state, "live intent tracking was lost"
    assert _object(object_id)["lifecycle_state"] == "active"
    assert (BUCKET, intent.storage_key) in env["store"].objects
    assert "delete" not in env["store"].calls and env["google_calls"] == []
    # Once the window closes the intent is no longer live: the row is deletable without any
    # scheduler / sweeper having run.
    env["clock"].advance(INTENT_TTL_SECONDS + 1)
    _assert_allowed_canonical_delete(env, row_id, object_id, _delete(env, row_id))


@pytest.mark.parametrize("case", NON_LIVE_TARGET_INTENT_CASES)
def test_F5_a_non_live_target_intent_never_blocks_delete(env, case):
    row_id, object_id = _seed("canonical", env)
    intent = _seed_target_intent(env, row_id, case)
    row = _intent(intent.id)
    assert row["state"] == case.split("-")[0]
    assert row["state"] in ("rejected", "expired") or row["expires_at"] <= env["clock"].now
    _as_admin(env)
    _assert_allowed_canonical_delete(env, row_id, object_id, _delete(env, row_id))


def test_F5_a_consumed_target_intent_owned_by_the_row_does_not_block_delete(env):
    row_id, old_object_id = _seed("canonical", env)
    with main.app.app_context():
        conn = _db()
        intent = seed_admin_intent(conn, env["store"], actor=env["admin_id"], submission_id=secrets.token_hex(16),
                                   slot=SLOTS[0], content=PNG, mime="image/png", now=T0, admin_arquivo_id=row_id)
        from app.storage import mirror_outbox

        with write_transaction(conn):
            _consumed, new_object_id = intents.consume_intent(
                conn, intent_id=intent.id, actor_user_id=env["admin_id"], purpose=PURPOSE,
                operation_id=intent.operation_id, now=T0)
            conn.execute("UPDATE admin_arquivos SET storage_object_id=?,mime_type='image/png',size_bytes=?,"
                         "sha256=?,operation_key=? WHERE id=?",
                         (new_object_id, len(PNG), sha256(PNG), intent.operation_id, row_id))
            mirror_outbox.retire_object(conn, object_id=old_object_id, now=T0)
    _as_admin(env)
    _assert_allowed_canonical_delete(env, row_id, new_object_id, _delete(env, row_id))


# ===========================================================================
# G. state / scope guards
# ===========================================================================


def test_G1_no_flow_writes_an_illegal_canonical_state(env):
    _as_admin(env)
    submission = _submission(env)
    created = _create(env, submission, [_upload(env, submission, SLOTS[0], PDF)], titulo="S3B G1")
    assert _answered(created) and created.status_code == 302, created
    [row] = _rows_titled("S3B G1")
    assert_canonical_steady(row)
    metadata = _call(lambda: env["client"].post(EDIT_URL.format(id=row["id"]), data=_fields("S3B G1", "nova")))
    assert _answered(metadata) and metadata.status_code == 302
    assert_canonical_steady(_arquivo(row["id"]))
    _s, _i, replaced = _replace_through_protocol(env, row["id"], slot=SLOTS[1])
    assert _answered(replaced) and replaced.status_code == 302, replaced
    assert_canonical_steady(_arquivo(row["id"]))
    with main.app.app_context():
        assert _db().execute(
            "SELECT count(*) FROM admin_arquivos WHERE provider='supabase' AND (storage_status<>'active'"
            " OR failure_code LIKE 'REPLACEMENT_%' OR cleanup_started_at IS NOT NULL)").fetchone()[0] == 0
    assert env["google_calls"] == []


def test_G2_control_schema_head_remains_v15():
    from app import pg_schema, prod1_schema

    assert prod1_schema.SCHEMA_VERSION == 15
    assert pg_schema.PG_SCHEMA_VERSION == 15
    assert not [p.name for p in (ROOT / "app").glob("prod1_*v16*.py")]


def test_G3_no_s4_mirror_behaviour_on_canonical_paths(env):
    _as_admin(env)
    submission = _submission(env)
    assert _create(env, submission, [_upload(env, submission, SLOTS[0], PDF)], titulo="S3B G3").status_code == 302
    [row] = _rows_titled("S3B G3")
    _replace_through_protocol(env, row["id"], slot=SLOTS[1])
    _delete(env, row["id"])
    with main.app.app_context():
        conn = _db()
        objects = [dict(r) for r in conn.execute("SELECT * FROM storage_objects")]
        assert len(objects) == 2
        assert {o["drive_sync_state"] for o in objects} == {"pending"}
        assert all(o["lease_token"] is None and o["drive_account_key"] is None for o in objects)
        assert conn.execute("SELECT count(*) FROM storage_worker_status").fetchone()[0] == 0
    assert env["google_calls"] == []


def test_G4_control_list_and_metadata_edit_never_migrate_a_legacy_row(env):
    google_id = _seed_row_id("google", env)
    local_id = _seed_row_id("local", env)
    canonical_id, _object_id = _seed("canonical", env, key=OTHER_KEY, operation_key="seed-g4-op")
    before = {i: _arquivo(i) for i in (google_id, local_id)}
    objects = _counts()["storage_objects"]
    _as_admin(env)
    assert env["client"].get(ADMIN_PAGE).status_code == 200
    for row_id in (google_id, local_id, canonical_id):
        response = _call(lambda: env["client"].post(EDIT_URL.format(id=row_id), data=_fields(f"G4 {row_id}")))
        assert _answered(response) and response.status_code == 302, response
    for row_id, row in before.items():
        after = _arquivo(row_id)
        assert (after["provider"], after["storage_status"], after["storage_object_id"]) == (
            row["provider"], row["storage_status"], row["storage_object_id"])
    assert _arquivo(canonical_id)["titulo"] == f"G4 {canonical_id}"
    assert _counts()["storage_objects"] == objects
    assert env["google_calls"] == []


def test_G5_no_physical_purge_on_any_canonical_path(env):
    _as_admin(env)
    submission = _submission(env)
    assert _create(env, submission, [_upload(env, submission, SLOTS[0], PDF)], titulo="S3B G5").status_code == 302
    [row] = _rows_titled("S3B G5")
    _replace_through_protocol(env, row["id"], slot=SLOTS[1])
    assert _answered(_delete(env, row["id"]))
    with main.app.app_context():
        keys = {r[0] for r in _db().execute("SELECT storage_key FROM storage_objects")}
    assert len(keys) == 2 and all((BUCKET, key) in env["store"].objects for key in keys)
    assert "delete" not in env["store"].calls
    assert env["google_calls"] == []


def test_G6_control_legacy_google_helpers_are_retained_for_s5():
    import app.arquivos as arquivos

    missing = [name for name in LEGACY_GOOGLE_HELPERS if not callable(getattr(arquivos, name, None))]
    assert missing == []


# ===========================================================================
# H. template / client / CSP / CSRF
# ===========================================================================


def _admin_form(html: str) -> tuple[str, str]:
    match = re.search(r"(<form\b[^>]*\bid=[\"']admin-arquivo-form[\"'][^>]*>)(.*?)</form>", html,
                      re.DOTALL | re.IGNORECASE)
    assert match, "admin-arquivo-form not rendered"
    return match.group(1), match.group(0)


def test_H1_admin_form_is_a_single_file_direct_upload_form(env):
    _as_admin(env)
    html = env["client"].get(ADMIN_PAGE).data.decode("utf-8")
    open_tag, form = _admin_form(html)
    assert "multipart/form-data" not in open_tag.lower(), "the business POST must not carry bytes"
    assert re.search(r"\sdata-direct-upload(?=[\s>=])", open_tag), open_tag
    assert f'{FORM_PURPOSE_ATTR}="{PURPOSE}"' in open_tag
    assert re.search(rf"\s{FORM_SINGLE_ATTR}(?=[\s>=])", open_tag)
    assert f'{FORM_SUBMISSION_FIELD_ATTR}="{ARQUIVOS_SUBMISSION_FIELD}"' in open_tag
    assert f'{FORM_INTENT_FIELD_ATTR}="{ARQUIVOS_INTENT_IDS_FIELD}"' in open_tag
    assert FORM_TARGET_ATTR not in open_tag, "a create render has no replacement target"
    file_inputs = re.findall(r"<input\b[^>]*type=[\"']file[\"'][^>]*>", form, re.IGNORECASE)
    assert len(file_inputs) == 1, file_inputs
    assert not re.search(r"\bname\s*=", file_inputs[0], re.IGNORECASE), "no multipart name=arquivo transport"
    assert not re.search(r"\bmultiple\b", file_inputs[0], re.IGNORECASE)
    assert "data-direct-upload-input" in file_inputs[0]
    assert _HEX128.fullmatch(hidden_value(form.encode(), ARQUIVOS_SUBMISSION_FIELD) or "")
    for name in ("csrf_token", "return_to", "visivel"):
        assert hidden_value(form.encode(), name) is not None, name
    assert hidden_value(form.encode(), "operation_key") is None, (
        "the legacy hidden operation_key is not authoritative for the direct-upload form")
    assert re.search(r"name=[\"']titulo[\"']", form) and re.search(r"name=[\"']descricao[\"']", form)
    assert "/static/js/direct-upload.js" in html
    assert re.search(r"/static/vendor/tus-js-client[-@]\d+\.\d+\.\d+(\.min)?\.js", html)


def test_H1_edit_render_binds_the_replacement_target(env):
    row_id, _object_id = _seed("canonical", env)
    _as_admin(env)
    html = env["client"].get(f"{ADMIN_PAGE}?edit_arquivo={row_id}").data.decode("utf-8")
    open_tag, _form = _admin_form(html)
    assert f'{FORM_TARGET_ATTR}="{row_id}"' in open_tag, open_tag
    assert EDIT_URL.format(id=row_id) in open_tag


_CHUNK_RE = re.compile(r"6\s*\*\s*1024\s*\*\s*1024|6291456")


def _direct_upload_source() -> str:
    return (ROOT / "static" / "js" / "direct-upload.js").read_text(encoding="utf-8")


def test_H2_client_is_purpose_target_and_field_parameterized():
    source = _direct_upload_source()
    missing = [marker for marker in (FORM_PURPOSE_ATTR, FORM_SINGLE_ATTR, FORM_SUBMISSION_FIELD_ATTR,
                                     FORM_INTENT_FIELD_ATTR, FORM_TARGET_ATTR, TARGET_FIELD)
               if marker not in source]
    assert missing == [], f"direct-upload.js lacks the ARQUIVOS parameterization: {missing}"


def test_H2_control_client_keeps_the_s3a_transport_and_comprovante_defaults():
    source = _direct_upload_source()
    assert re.search(r"headers:\s*\{\s*apikey:\s*capability\.apikey,\s*'x-signature':\s*capability\.upload_token\s*\}",
                     source)
    assert not re.search(r"""['"]?authorization['"]?\s*:""", source, re.IGNORECASE)
    assert "bearer" not in source.lower() and _CHUNK_RE.search(source)
    for default in ("'comprovante'", "comprovantes_intent_ids", "comprovantes_submission_id"):
        assert default in source, default
    for marker in ("supabase-js", "createclient(", "sb_secret_", "sb_publishable_", "service_role"):
        assert marker not in source.lower(), marker


def _connect_src(policy: str) -> list[str]:
    for chunk in policy.split(";"):
        parts = chunk.strip().split()
        if parts and parts[0] == "connect-src":
            return parts[1:]
    return []


def test_H3_the_published_csp_storage_origin_covers_the_admin_arquivo_capability(env, monkeypatch):
    from app import create_app

    monkeypatch.delenv("CONTENT_SECURITY_POLICY", raising=False)
    sources = _connect_src(create_app().config["CONTENT_SECURITY_POLICY"])
    _as_admin(env)
    cap = _capability(_issue(env, _submission(env), SLOTS[0], PDF))
    parts = urlsplit(cap["tus_endpoint"])
    assert f"{parts.scheme}://{parts.netloc}" in sources
    assert [s for s in sources if "supabase" in s] == [STORAGE_ORIGIN]


def test_H4_control_csrf_is_enforced_on_every_same_origin_arquivos_write(env, monkeypatch):
    row_id, _object_id = _seed("canonical", env)
    monkeypatch.setitem(main.app.config, "WTF_CSRF_ENABLED", True)
    _as_admin(env)
    before, counts = _arquivo(row_id), _counts()
    attempts = (
        (ISSUE_URL, dict(json={"purpose": PURPOSE, **declaration(PDF, "p.pdf", "application/pdf")})),
        (FINALIZE_URL.format(intent_id=secrets.token_hex(16)), {}),
        (CREATE_URL, dict(data=_fields("S3B H4"))),
        (EDIT_URL.format(id=row_id), dict(data=_fields("S3B H4"))),
        (DELETE_URL.format(id=row_id), {}),
    )
    for url, kwargs in attempts:
        response = env["client"].post(url, **kwargs)
        assert response.status_code == 400, (url, response.status_code)
    assert _arquivo(row_id) == before and _counts() == counts
    assert env["store"].calls == [] and env["google_calls"] == []


def test_H4_a_csrf_carrying_admin_arquivo_issue_is_accepted(env, monkeypatch):
    monkeypatch.setitem(main.app.config, "WTF_CSRF_ENABLED", True)
    _as_admin(env)
    token = env["client"].get("/csrf-token").get_json()["csrf_token"]
    submission = _submission(env)
    payload = {"purpose": PURPOSE, "submission_id": submission, "upload_slot_id": SLOTS[0],
               **declaration(PDF, "p.pdf", "application/pdf")}
    response = env["client"].post(ISSUE_URL, json=payload, headers={"X-CSRFToken": token})
    assert response.status_code == 201, (response.status_code, response.get_json(silent=True))


def test_H4_control_cross_origin_tus_never_receives_the_csrf_token():
    shim = (ROOT / "static" / "js" / "csrf-shim.js").read_text(encoding="utf-8")
    assert shim.count("isSameOrigin(") >= 3, "fetch and XHR must both gate the token on same-origin"
    assert re.search(r"!isSafeMethod\(method\)\s*&&\s*isSameOrigin\(url\)", shim)
    assert re.search(r"!isSafeMethod\(this\.__csrf_method\)\s*&&\s*isSameOrigin\(", shim)


# ===========================================================================
# T. the Google tripwire itself
# ===========================================================================


def test_T1_control_strengthened_tripwire_catches_every_arquivos_google_binding(env):
    import app.arquivos as arquivos
    from werkzeug.datastructures import FileStorage

    google_id = _seed_row_id("google", env)
    probes = {
        "app.arquivos.resolve_arquivo_storage": lambda conn: arquivos.resolve_arquivo_storage(conn),
        "app.arquivos.resolve_google_managed_storage": lambda conn: arquivos.resolve_google_managed_storage(
            conn, extension_key="arquivo_storage"),
        "arquivo_storage.download": lambda conn: main.app.extensions["arquivo_storage"].download("x"),
        "legacy create": lambda conn: arquivos.create_arquivo(
            conn, file_storage=FileStorage(stream=io.BytesIO(PDF), filename="t.pdf"), titulo="T1",
            descricao=None, visivel=1, uploader_user_id=env["admin_id"], operation_key="t1-legacy-op",
            max_file_bytes=MIB16),
        "legacy google read": lambda conn: arquivos.read_arquivo_content(
            conn, conn.execute("SELECT * FROM admin_arquivos WHERE id=?", (google_id,)).fetchone(),
            upload_root=env["upload_root"]),
    }
    with main.app.app_context():
        conn = _db()
        for label, probe in probes.items():
            recorded = len(env["google_calls"])
            with pytest.raises(GoogleTouched):
                probe(conn)
            assert len(env["google_calls"]) > recorded, label
            conn.rollback()


def test_T2_control_the_s3a_tripwire_alone_would_miss_an_injected_arquivo_storage(tmp_path, monkeypatch):
    import app.arquivos as arquivos
    from tests.test_arquivos_google_drive import FakeManagedStorage

    with isolated_versioned_app_env(tmp_path, "s3b-tripwire.db"):
        fake = FakeManagedStorage()
        monkeypatch.setitem(main.app.extensions, "arquivo_storage", fake)
        s3a_calls = arm_google_tripwires(monkeypatch, main.app)
        with main.app.app_context():
            assert arquivos.resolve_arquivo_storage(_db()) is fake  # the false-green gap
        assert s3a_calls == []
        s3b_calls = arm_arquivos_google_tripwires(monkeypatch, main.app)
        with main.app.app_context():
            with pytest.raises(GoogleTouched):
                arquivos.resolve_arquivo_storage(_db())
        assert "app.arquivos.resolve_arquivo_storage" in s3b_calls
