# coding: utf-8
"""STORAGE S3-B RED on real PostgreSQL (opt-in, ``SGAA_PG_TEST_URL``).

Without ``SGAA_PG_TEST_URL`` the module skips (REAL-PG EVIDENCE: ABSENT).  One
disposable database (prefix ``sgaa_s3b_test_<run>_``) is provisioned through
``app.pg_schema``; ``app.db.DATABASE_URL`` points the real ``main.app`` request
path at it for the module, and the accepted drop guard removes it at teardown.
No live Supabase Storage is involved: the canonical store is the deterministic
in-memory fake; every Google entry point is a tripwire.

The nodes pin OUTCOMES through the application surface, never a SQL sequence:

    PG1  create attach: consume + INSERT commit or roll back together;
    PG2  canonical replacement: consume + UPDATE + retire are atomic;
    PG3  canonical delete: retire + DELETE are atomic and legal under v15;
    PG4  two replacement submissions issued against ONE original custody,
         attached concurrently: exactly one business replacement, the other
         stale / refused, no double retirement, no deadlock;
    PG5  replacement vs delete, concurrently.  Scenario 1 (LIVE replacement
         intent): no live tracking lost through the FK cascade, no silently
         untracked provider object, a consistent final state, no deadlock.
         Scenario 2 (terminal replacement intent): the delete is not blocked
         by it, the final state is consistent, no deadlock (orphan provider
         bytes of a terminal intent are S5 / S6 scope, not asserted here).

The only seam used to interleave is ``app.storage.upload_intents.consume_intent``
(the S2 primitive every canonical attach consumes through, as S3-A pinned):
the FIRST attach is held right after its consume, inside its transaction,
while the competitor runs.  Lock order is the implementation's choice.

RED today: the admin page renders no ARQUIVOS submission and the canonical
ARQUIVOS business path does not exist.
"""

from __future__ import annotations

import os
import secrets
import threading
import time
from urllib.parse import urlsplit, urlunsplit

import pytest

PG_URL = os.environ.get("SGAA_PG_TEST_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not PG_URL, reason="SGAA_PG_TEST_URL is not configured -- REAL-PG EVIDENCE: ABSENT"
)

psycopg = pytest.importorskip("psycopg")

from app import db as app_db  # noqa: E402
from app import pg_schema  # noqa: E402
from app.storage import custody_common  # noqa: E402
from app.storage import upload_intents as intents  # noqa: E402
from tests.canonical_store_fake import InMemoryObjectStore  # noqa: E402
from tests.storage_s3a_support import (  # noqa: E402
    BUCKET,
    CANONICAL_STORE_EXTENSION,
    FINALIZE_URL,
    ISSUE_URL,
    PDF,
    PNG,
    SUPABASE_URL,
    TEST_PUBLISHABLE_KEY,
    TEST_SECRET_KEY,
    browser_upload,
    declaration,
    hidden_value,
    padded_png,
)
from tests.storage_s3b_support import (  # noqa: E402
    ADMIN_PAGE,
    ARQUIVO_SLOTS,
    ARQUIVOS_INTENT_IDS_FIELD,
    ARQUIVOS_SUBMISSION_FIELD,
    CREATE_URL,
    DELETE_URL,
    EDIT_URL,
    PURPOSE,
    TARGET_FIELD,
    arm_arquivos_google_tripwires,
    assert_canonical_steady,
    seed_canonical_arquivo,
)

RUN_PREFIX = f"sgaa_s3b_test_{secrets.token_hex(4)}_"
PROTECTED_DATABASES = frozenset({"postgres", "template0", "template1", "sgaa_qual"})
CONNECT_TIMEOUT_SECONDS = 10
T0 = "2026-10-08 12:00:00"
ADMIN_EMAIL = "s3b.admin@example.test"
ADMIN_PASSWORD = "s3b-senha-admin"
SLOTS = ARQUIVO_SLOTS
JOIN_TIMEOUT_SECONDS = 60


def _database_url(database):
    parts = urlsplit(PG_URL)
    return urlunsplit((parts.scheme, parts.netloc, "/" + database, f"connect_timeout={CONNECT_TIMEOUT_SECONDS}", ""))


def _raw(url, *, autocommit=False):
    return psycopg.connect(url, prepare_threshold=None, autocommit=autocommit, connect_timeout=CONNECT_TIMEOUT_SECONDS)


class _Registry:
    """Sole creator and destroyer of this run's disposable databases."""

    def __init__(self):
        self._admin = None
        self._owned = set()

    def admin(self):
        if self._admin is None or self._admin.closed:
            self._admin = _raw(PG_URL, autocommit=True)
        return self._admin

    def create(self):
        database = f"{RUN_PREFIX}{secrets.token_hex(4)}"
        assert database.startswith(RUN_PREFIX) and database not in PROTECTED_DATABASES
        self.admin().execute(f'CREATE DATABASE "{database}"')
        self._owned.add(database)
        return database, _database_url(database)

    def drop(self, database):
        if database in PROTECTED_DATABASES or not database.startswith(RUN_PREFIX) or database not in self._owned:
            raise AssertionError(f"refusing to drop {database!r}: not run-owned")
        row = self.admin().execute(
            "SELECT pg_get_userbyid(datdba) = current_user FROM pg_database WHERE datname = %s", (database,)
        ).fetchone()
        if row is not None and not row[0]:
            raise AssertionError(f"refusing to drop {database!r}: not owned by this role")
        try:
            self.admin().execute(f'DROP DATABASE IF EXISTS "{database}"')
        except psycopg.errors.ObjectInUse:
            self.admin().execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
        self._owned.discard(database)

    def close(self):
        failures = []
        for database in sorted(self._owned):
            try:
                self.drop(database)
            except Exception as exc:  # pragma: no cover - teardown reporting
                failures.append((database, repr(exc)))
        leftovers = [r[0] for r in self.admin().execute(
            "SELECT datname FROM pg_database WHERE starts_with(datname, %s)", (RUN_PREFIX,)).fetchall()]
        self._admin.close()
        assert not failures, f"could not drop run-owned databases: {failures!r}"
        assert not leftovers, f"run-owned databases left behind: {leftovers!r}"


class _Env:
    pass


@pytest.fixture(scope="module")
def env():
    import main
    from app.security.passwords import hash_password
    from app.user_accounts import create_usuario_with_access_level

    registry = _Registry()
    patcher = pytest.MonkeyPatch()
    try:
        try:
            registry.admin()
        except psycopg.Error as exc:
            pytest.skip(f"SGAA_PG_TEST_URL is not a usable PostgreSQL connection: {exc}")
        database, url = registry.create()
        connection = _raw(url)
        try:
            assert pg_schema.provision_pg_schema(connection)["status"] == "provisioned"
            connection.commit()
        finally:
            connection.close()
        patcher.setattr(app_db, "DATABASE_URL", url)
        patcher.setitem(main.app.config, "TESTING", True)
        assert app_db.database_backend() == "postgres"
        e = _Env()
        e.url, e.database, e.app = url, database, main.app
        e.store = InMemoryObjectStore()
        patcher.setitem(main.app.extensions, CANONICAL_STORE_EXTENSION, e.store)
        for name, value in (("SUPABASE_URL", SUPABASE_URL), ("SUPABASE_SECRET_KEY", TEST_SECRET_KEY),
                            ("SUPABASE_PUBLISHABLE_KEY", TEST_PUBLISHABLE_KEY), ("SGAA_STORAGE_BUCKET", BUCKET)):
            patcher.setenv(name, value)
        patcher.setattr(custody_common, "utc_now_text", lambda: T0)
        e.google_calls = arm_arquivos_google_tripwires(patcher, main.app)
        production = app_db._connect_postgres()
        try:
            cursor = create_usuario_with_access_level(
                production, "S3B Admin", ADMIN_EMAIL, hash_password(ADMIN_PASSWORD), "admin", "admin_total",
                credential_state="personal",
            )
            e.admin_id = int(cursor.usuario_id)
            production.commit()
        finally:
            production.close()
        try:
            yield e
        finally:
            with main.app.app_context():
                app_db.close_db_connection(None)
    finally:
        patcher.undo()
        registry.close()


def _client(env):
    client = env.app.test_client()
    response = client.post("/login", data={"email": ADMIN_EMAIL, "senha": ADMIN_PASSWORD})
    assert response.status_code == 302, response.status_code
    with client.session_transaction() as sess:
        sess.pop("_flashes", None)
    return client


def _observe(env, sql, params=()):
    observer = _raw(env.url, autocommit=True)
    try:
        return observer.execute(sql, params).fetchall()
    finally:
        observer.close()


def _one(env, sql, params=()):
    rows = _observe(env, sql, params)
    return rows[0] if rows else None


def _arquivo(env, row_id):
    observer = _raw(env.url, autocommit=True)
    try:
        cursor = observer.execute("SELECT * FROM admin_arquivos WHERE id=%s", (row_id,))
        row = cursor.fetchone()
        return None if row is None else dict(zip([c.name for c in cursor.description], row))
    finally:
        observer.close()


def _object_state(env, object_id):
    return _one(env, "SELECT lifecycle_state, retired_at FROM storage_objects WHERE id=%s", (object_id,))


def _intent_state(env, intent_id):
    return _one(env, "SELECT state, storage_object_id FROM storage_upload_intents WHERE id=%s", (intent_id,))


def _census(env):
    return tuple(_one(env, f"SELECT count(*) FROM {t}")[0]
                 for t in ("admin_arquivos", "storage_objects", "storage_upload_intents"))


def _seed_canonical(env, key_digit):
    conn = app_db._connect_postgres()
    try:
        row_id, object_id = seed_canonical_arquivo(
            conn, env.store, uploader=env.admin_id, now=T0, key=f"arquivos/2026/10/{key_digit * 32}",
            operation_key=f"seed-pg-{key_digit}", titulo=f"PG canonico {key_digit}")
        conn.commit()
    finally:
        conn.close()
    return row_id, object_id


def _submission(client, edit_id=None):
    path = ADMIN_PAGE + (f"?edit_arquivo={edit_id}" if edit_id else "")
    page = client.get(path)
    assert page.status_code == 200, (path, page.status_code)
    value = hidden_value(page.data, ARQUIVOS_SUBMISSION_FIELD)
    assert value is not None, f"{path} renders no server-issued {ARQUIVOS_SUBMISSION_FIELD} (S3-B form absent)"
    return value


def _upload(env, client, submission, slot, content=PNG, filename="novo.png", mime="image/png", target=None):
    payload = {"purpose": PURPOSE, "submission_id": submission, "upload_slot_id": slot,
               **declaration(content, filename, mime)}
    if target is not None:
        payload[TARGET_FIELD] = target
    issued = client.post(ISSUE_URL, json=payload)
    assert issued.status_code in (200, 201), (issued.status_code, issued.get_json(silent=True))
    cap = issued.get_json()
    browser_upload(env.store, cap, content, mime)
    finalized = client.post(FINALIZE_URL.format(intent_id=cap["intent_id"]))
    assert finalized.status_code == 200, finalized.status_code
    return cap["intent_id"]


def _form(titulo, submission, intent_ids):
    return {"titulo": titulo, "descricao": "PG", "visivel": "1", ARQUIVOS_SUBMISSION_FIELD: submission,
            ARQUIVOS_INTENT_IDS_FIELD: list(intent_ids)}


def _call(function):
    try:
        return function()
    except Exception as exc:  # recorded for the assertions (a deadlock would land here)
        return exc


class _ConsumeGate:
    """Hold the FIRST canonical attach right after its consume, inside its transaction."""

    def __init__(self, monkeypatch):
        self.entered = threading.Event()
        self.release = threading.Event()
        self._lock = threading.Lock()
        self._first = True
        original = intents.consume_intent

        def gated(*args, **kwargs):
            result = original(*args, **kwargs)
            with self._lock:
                hold, self._first = self._first, False
            if hold:
                self.entered.set()
                self.release.wait(JOIN_TIMEOUT_SECONDS)
            return result

        monkeypatch.setattr(intents, "consume_intent", gated)


def _start(function):
    outcome = {}

    def run():
        outcome["value"] = _call(function)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, outcome


def _settle_competitor(env, thread, seconds=5.0):
    """Let the competitor finish or block on a lock before the held attach resumes."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and thread.is_alive():
        waiting = _one(env, "SELECT count(*) FROM pg_stat_activity WHERE datname=%s AND wait_event_type='Lock'",
                       (env.database,))[0]
        if waiting:
            return
        time.sleep(0.05)


def _assert_answered(label, outcome):
    value = outcome.get("value")
    assert value is not None and not isinstance(value, Exception), (label, value)
    assert value.status_code != 500, (label, value.status_code)
    return value


def _tracked_keys(env):
    keys = {r[0] for r in _observe(env, "SELECT storage_key FROM storage_objects")}
    return keys | {r[0] for r in _observe(env, "SELECT storage_key FROM storage_upload_intents")}


# ---------------------------------------------------------------------------
# PG1..PG3 atomicity
# ---------------------------------------------------------------------------


def _faulty_consume(monkeypatch, fired):
    original = intents.consume_intent

    def faulty(*args, **kwargs):
        result = original(*args, **kwargs)
        fired.append(True)
        raise RuntimeError("injected fault after consume")

    monkeypatch.setattr(intents, "consume_intent", faulty)
    return original


def test_pg1_create_attach_consume_and_insert_are_one_transaction(env, monkeypatch):
    client = _client(env)
    submission = _submission(client)
    intent_id = _upload(env, client, submission, SLOTS[0], PDF, "manual.pdf", "application/pdf")
    before = _census(env)
    fired = []
    original = _faulty_consume(monkeypatch, fired)
    _call(lambda: client.post(CREATE_URL, data=_form("PG1 criado", submission, [intent_id])))
    assert fired, "the create attach must consume through app.storage.upload_intents.consume_intent"
    assert _census(env) == before
    assert _intent_state(env, intent_id)[0] == "verified"
    monkeypatch.setattr(intents, "consume_intent", original)
    response = client.post(CREATE_URL, data=_form("PG1 criado", submission, [intent_id]))
    assert response.status_code == 302
    [(row_id,)] = _observe(env, "SELECT id FROM admin_arquivos WHERE titulo='PG1 criado'")
    row = _arquivo(env, row_id)
    assert_canonical_steady(row)
    assert _intent_state(env, intent_id) == ("consumed", row["storage_object_id"])
    assert _one(env, "SELECT drive_sync_state, lease_token FROM storage_objects WHERE id=%s",
                (row["storage_object_id"],)) == ("pending", None)
    assert env.google_calls == []


def test_pg2_canonical_replacement_consume_update_and_retire_are_atomic(env, monkeypatch):
    row_id, old_object_id = _seed_canonical(env, "3")
    client = _client(env)
    submission = _submission(client, row_id)
    intent_id = _upload(env, client, submission, SLOTS[0], target=row_id)
    before_row, before_census = _arquivo(env, row_id), _census(env)
    fired = []
    original = _faulty_consume(monkeypatch, fired)
    _call(lambda: client.post(EDIT_URL.format(id=row_id), data=_form("PG2", submission, [intent_id])))
    assert fired, "the replacement must consume through app.storage.upload_intents.consume_intent"
    assert _arquivo(env, row_id) == before_row and _census(env) == before_census
    assert _object_state(env, old_object_id)[0] == "active"
    assert _intent_state(env, intent_id)[0] == "verified"
    monkeypatch.setattr(intents, "consume_intent", original)
    assert client.post(EDIT_URL.format(id=row_id), data=_form("PG2", submission, [intent_id])).status_code == 302
    row = _arquivo(env, row_id)
    assert_canonical_steady(row)
    assert row["storage_object_id"] != old_object_id
    assert _object_state(env, old_object_id)[0] == "retired"
    assert _object_state(env, row["storage_object_id"])[0] == "active"
    assert env.google_calls == []


def test_pg3_canonical_delete_retires_and_deletes_atomically_and_legally(env):
    row_id, object_id = _seed_canonical(env, "4")
    client = _client(env)
    response = _call(lambda: client.post(DELETE_URL.format(id=row_id)))
    assert not isinstance(response, Exception) and response.status_code == 302, response
    assert _arquivo(env, row_id) is None
    state, retired_at = _object_state(env, object_id)
    assert state == "retired" and retired_at is not None
    assert env.google_calls == []


# ---------------------------------------------------------------------------
# PG4 / PG5 concurrency
# ---------------------------------------------------------------------------


def test_pg4_two_replacements_against_one_original_custody_yield_exactly_one(env, monkeypatch):
    row_id, original_object_id = _seed_canonical(env, "5")
    first_client, second_client = _client(env), _client(env)
    first_submission = _submission(first_client, row_id)
    second_submission = _submission(second_client, row_id)
    first = _upload(env, first_client, first_submission, SLOTS[0], PNG, "um.png", target=row_id)
    second = _upload(env, second_client, second_submission, SLOTS[1], padded_png(2048), "dois.png", target=row_id)
    gate = _ConsumeGate(monkeypatch)
    held, held_outcome = _start(lambda: first_client.post(
        EDIT_URL.format(id=row_id), data=_form("PG4 primeiro", first_submission, [first])))
    assert gate.entered.wait(JOIN_TIMEOUT_SECONDS), "the first attach never consumed"
    competitor, competitor_outcome = _start(lambda: second_client.post(
        EDIT_URL.format(id=row_id), data=_form("PG4 segundo", second_submission, [second])))
    _settle_competitor(env, competitor)
    gate.release.set()
    held.join(JOIN_TIMEOUT_SECONDS)
    competitor.join(JOIN_TIMEOUT_SECONDS)
    assert not held.is_alive() and not competitor.is_alive(), "deadlock or hang"
    _assert_answered("first", held_outcome)
    _assert_answered("second", competitor_outcome)

    row = _arquivo(env, row_id)
    assert_canonical_steady(row)
    states = {intent: _intent_state(env, intent) for intent in (first, second)}
    winners = [intent for intent, (state, _object) in states.items() if state == "consumed"]
    assert len(winners) == 1, states
    [winner] = winners
    loser = second if winner == first else first
    assert states[winner][1] == row["storage_object_id"]
    assert states[loser][1] is None
    assert _object_state(env, row["storage_object_id"])[0] == "active"
    assert _object_state(env, original_object_id)[0] == "retired"
    loser_key = _one(env, "SELECT storage_key FROM storage_upload_intents WHERE id=%s", (loser,))[0]
    assert _observe(env, "SELECT id FROM storage_objects WHERE storage_key=%s", (loser_key,)) == [], (
        "the losing consume was not rolled back")
    assert env.google_calls == []


def test_pg5_live_replacement_versus_delete_loses_no_tracking_and_no_object(env, monkeypatch):
    """Scenario 1: the replacement intent is LIVE while the delete competes."""
    row_id, original_object_id = _seed_canonical(env, "6")
    replacer, deleter = _client(env), _client(env)
    submission = _submission(replacer, row_id)
    intent_id = _upload(env, replacer, submission, SLOTS[2], target=row_id)
    intent_key = _one(env, "SELECT storage_key FROM storage_upload_intents WHERE id=%s", (intent_id,))[0]
    gate = _ConsumeGate(monkeypatch)
    held, held_outcome = _start(lambda: replacer.post(
        EDIT_URL.format(id=row_id), data=_form("PG5", submission, [intent_id])))
    assert gate.entered.wait(JOIN_TIMEOUT_SECONDS), "the replacement never consumed"
    competitor, competitor_outcome = _start(lambda: deleter.post(DELETE_URL.format(id=row_id)))
    _settle_competitor(env, competitor)
    gate.release.set()
    held.join(JOIN_TIMEOUT_SECONDS)
    competitor.join(JOIN_TIMEOUT_SECONDS)
    assert not held.is_alive() and not competitor.is_alive(), "deadlock or hang"
    _assert_answered("replacement", held_outcome)
    _assert_answered("delete", competitor_outcome)

    # No provider object silently untracked: every stored key is still known to the database.
    stored = {key for (bucket, key) in env.store.objects if bucket == BUCKET}
    assert intent_key in stored and stored <= _tracked_keys(env), sorted(stored - _tracked_keys(env))
    intent = _intent_state(env, intent_id)
    row = _arquivo(env, row_id)
    if row is not None:
        assert_canonical_steady(row)
        assert _object_state(env, row["storage_object_id"])[0] == "active"
        if row["storage_object_id"] != original_object_id:
            assert intent == ("consumed", row["storage_object_id"])
            assert _object_state(env, original_object_id)[0] == "retired"
        else:
            assert intent is not None and intent[0] != "consumed", "a consumed object became unowned"
    else:
        # The row is gone: its intent was consumed into a tracked, retired object, never cascaded live.
        assert intent is None or intent[0] == "consumed", f"an unsafe intent state survived a delete: {intent}"
        objects = _observe(env, "SELECT id, lifecycle_state FROM storage_objects WHERE storage_key=%s", (intent_key,))
        assert objects and objects[0][1] == "retired", objects
        assert _object_state(env, original_object_id)[0] == "retired"
    assert env.google_calls == []


def test_pg5_terminal_replacement_intent_never_blocks_a_competing_delete(env):
    """Scenario 2: the target replacement intent is terminal (rejected at finalize)."""
    row_id, original_object_id = _seed_canonical(env, "7")
    replacer, deleter = _client(env), _client(env)
    submission = _submission(replacer, row_id)
    payload = {"purpose": PURPOSE, "submission_id": submission, "upload_slot_id": SLOTS[3],
               TARGET_FIELD: row_id, **declaration(PNG, "novo.png", "image/png")}
    issued = replacer.post(ISSUE_URL, json=payload)
    assert issued.status_code in (200, 201), (issued.status_code, issued.get_json(silent=True))
    cap = issued.get_json()
    env.store.objects[(BUCKET, cap["object_name"])] = (PDF, "image/png")  # not the declared bytes
    rejected = replacer.post(FINALIZE_URL.format(intent_id=cap["intent_id"]))
    assert 400 <= rejected.status_code < 500, rejected.status_code
    assert _intent_state(env, cap["intent_id"])[0] == "rejected"

    attach, attach_outcome = _start(lambda: replacer.post(
        EDIT_URL.format(id=row_id), data=_form("PG5 terminal", submission, [cap["intent_id"]])))
    delete, delete_outcome = _start(lambda: deleter.post(DELETE_URL.format(id=row_id)))
    attach.join(JOIN_TIMEOUT_SECONDS)
    delete.join(JOIN_TIMEOUT_SECONDS)
    assert not attach.is_alive() and not delete.is_alive(), "deadlock or hang"
    _assert_answered("terminal attach", attach_outcome)
    deleted = _assert_answered("delete", delete_outcome)
    assert deleted.status_code == 302
    assert _arquivo(env, row_id) is None, "a terminal intent blocked the delete"
    assert _object_state(env, original_object_id)[0] == "retired"
    assert _observe(env, "SELECT id FROM storage_objects WHERE storage_key=%s", (cap["object_name"],)) == [], (
        "a rejected intent was consumed")
    assert env.google_calls == []
