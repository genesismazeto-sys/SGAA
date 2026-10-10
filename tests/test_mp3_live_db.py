# coding: utf-8
"""MP-3 E-LIVE-DB: the database lanes against Supabase DEV through its poolers (opt-in, live).

Enabled only with ``SGAA_MP3_LIVE_DB=1`` and two URLs WITHOUT a password (libpq finds it in the
workstation password file; this module never reads, prints or stores it):

* ``SGAA_MP3_DEV_SESSION_URL``      the session pooler (port 5432), for DDL and the snapshot backup;
* ``SGAA_MP3_DEV_TRANSACTION_URL``  the transaction pooler (port 6543), the application's runtime path.

It also needs ``SGAA_PG_TEST_URL`` (a local PostgreSQL of the same major, for DR1 and DR3) and the
PostgreSQL client tools (``SGAA_PG_BIN_DIR``).  Everything happens inside the ``public`` schema of the
DEV database, which the SPEC declares run-owned (GA4); it is emptied first and left empty.  The data is
synthetic (one administrator account); no student datum exists anywhere in these lanes.

Lanes: provision v16 and the exposure probe; the transaction pooler (throttle flip and concurrency,
exactly-one preview claim, row locks that serialize, ``SKIP LOCKED``); the session-mode snapshot backup;
DR1 (the set taken from DEV restored into local PostgreSQL, the application booted on it and smoked);
DR3 (a synthetic set from local PostgreSQL restored into DEV through the supabase profile, the
application served through the transaction pooler and smoked).  RTO is the elapsed time from the start
of the restore to a passing smoke.  Timings are written, value-free, to ``SGAA_MP3_LIVE_DB_REPORT``.
"""

from __future__ import annotations

import datetime
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.mp2_pg_support import ADMIN_EMAIL, ADMIN_PASSWORD, PG_URL, Registry, seed_admin

SESSION_URL = os.environ.get("SGAA_MP3_DEV_SESSION_URL", "")
TRANSACTION_URL = os.environ.get("SGAA_MP3_DEV_TRANSACTION_URL", "")
REPORT = os.environ.get("SGAA_MP3_LIVE_DB_REPORT", "")

pytestmark = pytest.mark.skipif(
    not (os.environ.get("SGAA_MP3_LIVE_DB") == "1" and SESSION_URL and TRANSACTION_URL and PG_URL),
    reason="the live database lanes need SGAA_MP3_LIVE_DB=1, the two DEV pooler URLs and SGAA_PG_TEST_URL",
)

psycopg = pytest.importorskip("psycopg")

REPO_ROOT = Path(__file__).resolve().parents[1]
_KEEP = ("SYSTEMROOT", "SystemDrive", "WINDIR", "COMSPEC", "PATHEXT", "PATH", "USERPROFILE", "OS", "APPDATA",
         "HOMEDRIVE", "HOMEPATH", "LOCALAPPDATA")
_SERVER = (
    "import main; from werkzeug.serving import make_server; import sys;"
    "s = make_server('127.0.0.1', int(sys.argv[1]), main.app, threaded=True);"
    "print('READY', flush=True); s.serve_forever()"
)
RECIPE = (
    "ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM anon, authenticated, service_role",
    "ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM anon, authenticated, service_role",
    "ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON FUNCTIONS FROM anon, authenticated, service_role",
    "ALTER DEFAULT PRIVILEGES REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC",
    "REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC, anon, authenticated, service_role",
    "REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC, anon, authenticated, service_role",
    "REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC, anon, authenticated, service_role",
)
STATE: dict = {"timings": {}}


def _write_report() -> None:
    if REPORT:
        Path(REPORT).write_text(json.dumps(STATE["timings"], sort_keys=True, indent=1), encoding="ascii")


def _timed(name: str):
    class _Clock:
        def __enter__(self):
            self.start = time.perf_counter()
            return self

        def __exit__(self, *exc):
            STATE["timings"][name] = round(time.perf_counter() - self.start, 2)
            _write_report()

    return _Clock()


def _raw(url, *, autocommit=True):
    return psycopg.connect(url, prepare_threshold=None, autocommit=autocommit, connect_timeout=20)


def _adapter(url):
    from app.db import _PostgresConnectionAdapter

    raw = _raw(url, autocommit=False)
    raw.isolation_level = psycopg.IsolationLevel.READ_COMMITTED
    return _PostgresConnectionAdapter(raw)


def _apply_recipe(url) -> None:
    with _raw(url) as conn:
        for statement in RECIPE:
            conn.execute(statement)


def _reset_public(url) -> int:
    """Empty the run-owned ``public`` schema of SGAA objects; refuses to touch anything else."""
    from app import pg_schema

    known = set(pg_schema.PG_SCHEMA_TABLES)
    with _raw(url) as conn:
        assert conn.execute("SELECT count(*) FROM pg_namespace WHERE nspname IN ('auth','storage','extensions')"
                            ).fetchone()[0] == 3, "not a managed project"
        relations = conn.execute(
            "SELECT c.relname, c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
            " WHERE n.nspname = 'public' AND c.relkind IN ('r','p','v','m','f','S')"
            " AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = c.oid AND d.deptype = 'e')"
            " AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = c.oid AND d.deptype IN ('a','i')"
            "                 AND d.classid = 'pg_class'::regclass AND c.relkind = 'S')"
        ).fetchall()
        foreign = sorted(name for name, kind in relations if kind != "S" and name not in known)
        assert not foreign, f"public holds objects SGAA does not own: {foreign[:5]}"
        dropped = 0
        for name, kind in relations:
            if kind in {"r", "p"}:
                conn.execute(f'DROP TABLE IF EXISTS public."{name}" CASCADE')
                dropped += 1
        for name, kind in conn.execute(
            "SELECT c.relname, c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
            " WHERE n.nspname = 'public' AND c.relkind IN ('v','m','f','S')"
        ).fetchall():
            word = {"v": "VIEW", "m": "MATERIALIZED VIEW", "f": "FOREIGN TABLE", "S": "SEQUENCE"}[kind]
            conn.execute(f'DROP {word} IF EXISTS public."{name}" CASCADE')
        for oid_name in conn.execute(
            "SELECT p.oid::regprocedure::text FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace"
            " WHERE n.nspname = 'public' AND NOT EXISTS"
            " (SELECT 1 FROM pg_depend d WHERE d.objid = p.oid AND d.deptype = 'e')"
        ).fetchall():
            conn.execute(f"DROP ROUTINE IF EXISTS {oid_name[0]} CASCADE")
        for (name,) in conn.execute(
            "SELECT t.typname FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace"
            " WHERE n.nspname = 'public' AND t.typtype IN ('e','d','c') AND t.typrelid = 0"
        ).fetchall():
            conn.execute(f'DROP TYPE IF EXISTS public."{name}" CASCADE')
    return dropped


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class _Served:
    """``main:app`` in hosted production mode in a child interpreter over a given database URL."""

    def __init__(self, database_url, tmp_path):
        from cryptography.fernet import Fernet

        env = {key: os.environ[key] for key in _KEEP if key in os.environ}
        env.update({
            "TEMP": str(tmp_path), "TMP": str(tmp_path), "TMPDIR": str(tmp_path),
            "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8",
            "DATABASE_URL": database_url, "SGAA_RUNTIME": "hosted", "APP_ENV": "production", "TRUST_PROXY_XFF": "1",
            "APP_SECRET_KEY": "p" + "3" * 47, "TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode(),
            "APP_PUBLIC_BASE_URL": "https://sgaa.example.test", "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_SECRET_KEY": "not-a-real-key-" + "x" * 20, "SGAA_STORAGE_BUCKET": "sgaa-rehearsal-none",
            "GOOGLE_CLIENT_ID": "", "GOOGLE_CLIENT_SECRET": "",
        })
        port = _free_port()
        self.child = subprocess.Popen(
            [sys.executable, "-c", _SERVER, str(port)], cwd=REPO_ROOT, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        )
        deadline = time.time() + 120
        while time.time() < deadline:
            if self.child.stdout.readline().strip() == "READY":
                break
            if self.child.poll() is not None:
                raise AssertionError("the application did not start")
        else:
            raise AssertionError("the application did not become ready")
        self.url = f"http://127.0.0.1:{port}"

    def close(self):
        self.child.kill()
        self.child.wait(timeout=30)


def _smoke(url) -> dict:
    from tools import hosted_smoke

    report = hosted_smoke.run(url, allow_insecure=True, email=ADMIN_EMAIL, password=ADMIN_PASSWORD)
    failed = [(c["check"], c["code"]) for c in report["checks"] if not c["ok"]]
    assert report["result"] == "PASS", failed
    return report


@pytest.fixture(scope="module", autouse=True)
def dev_public():
    """DEV ``public`` emptied before and after (run-owned, SPEC section 10); the recipe applied."""
    _reset_public(SESSION_URL)
    _apply_recipe(SESSION_URL)
    try:
        yield
    finally:
        _reset_public(SESSION_URL)
        _write_report()


@pytest.fixture(scope="module")
def local_registry():
    registry = Registry("livedb")
    try:
        yield registry
    finally:
        assert registry.close() == 0


@pytest.fixture(autouse=True)
def _native_tools_env(monkeypatch):
    monkeypatch.setenv("PGCONNECT_TIMEOUT", "20")


# ---- provision, validate, probe -----------------------------------------------------------------


def test_the_two_pooler_urls_are_what_the_application_thinks_they_are():
    from app.hosting import connection_kind

    assert connection_kind(SESSION_URL) == "pooler_session"
    assert connection_kind(TRANSACTION_URL) == "pooler_transaction"
    for url in (SESSION_URL, TRANSACTION_URL):
        with _raw(url) as conn:
            assert int(conn.execute("SHOW server_version_num").fetchone()[0]) // 10000 == 17


def test_v16_provisions_validates_and_the_exposure_probe_is_clean_on_the_managed_project():
    from app import pg_schema

    with _timed("provision_v16_seconds"):
        raw = _raw(SESSION_URL, autocommit=False)
        try:
            pg_schema.provision_pg_schema(raw)
            raw.commit()
            validated = pg_schema.validate_pg_schema(raw)
            raw.rollback()
        finally:
            raw.close()
    assert validated["table_count"] > 0
    _apply_recipe(SESSION_URL)  # the recipe again after provisioning (the runbook's order)
    raw = _raw(SESSION_URL, autocommit=True)
    try:
        exposure = pg_schema.api_role_exposure(raw)
    finally:
        raw.close()
    assert exposure["clean"] is True, {k: v for k, v in exposure.items() if k != "clean"}
    assert set(exposure["roles_probed"]) >= {"anon", "authenticated", "service_role"}


def test_the_readiness_command_reports_ready_and_a_clean_exposure_through_the_session_pooler():
    from cryptography.fernet import Fernet

    env = {key: os.environ[key] for key in _KEEP if key in os.environ}
    env.update({"DATABASE_URL": SESSION_URL, "SGAA_RUNTIME": "hosted", "APP_ENV": "production",
                "APP_SECRET_KEY": "p" + "3" * 47, "TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode(),
                "SUPABASE_URL": "https://example.supabase.co", "SUPABASE_SECRET_KEY": "k" * 30,
                "SGAA_STORAGE_BUCKET": "b", "PYTHONDONTWRITEBYTECODE": "1", "TRUST_PROXY_XFF": "1",
                "APP_PUBLIC_BASE_URL": "https://sgaa.example.test"})
    done = subprocess.run([sys.executable, "-m", "app.hosting_cli", "check", "--database"], cwd=REPO_ROOT,
                          env=env, capture_output=True, text=True, timeout=180)
    report = json.loads(done.stdout)
    database = report["database"]
    assert done.returncode == 0 and report["startup"] == "OK", report
    assert database["current"] is True and database["api_exposure"]["clean"] is True
    assert database["connection_kind"] == "pooler_session"


def test_the_offline_administrator_bootstrap_creates_one_admin_prints_no_secret_and_then_refuses(
        monkeypatch, capsys):
    import re

    import app.db as app_db
    from app import admin_bootstrap

    monkeypatch.setattr(app_db, "DATABASE_URL", SESSION_URL)
    code = admin_bootstrap.main(["--email", ADMIN_EMAIL, "--name", "MP3 Live Admin"], prompt=lambda _text: ADMIN_PASSWORD)
    captured = capsys.readouterr()
    assert code == 0, captured.err
    assert ADMIN_PASSWORD not in captured.out and ADMIN_PASSWORD not in captured.err
    found = re.search(r"usuario_id=(\d+)", captured.out)
    assert found, captured.out
    STATE["admin_id"] = int(found.group(1))
    # a second run finds a login-capable full administrator and refuses (no force, no reset)
    again = admin_bootstrap.main(["--email", ADMIN_EMAIL, "--name", "MP3 Live Admin"], prompt=lambda _t: "x" * 20)
    second = capsys.readouterr()
    assert again == 1 and "refused" in second.err and ADMIN_PASSWORD not in second.err + second.out
    with _raw(SESSION_URL) as conn:
        assert conn.execute("SELECT count(*) FROM usuarios WHERE tipo = 'admin'").fetchone()[0] == 1


# ---- the transaction pooler: the application's runtime path --------------------------------------


def test_the_durable_throttle_flips_at_its_threshold_and_loses_no_event_under_concurrency():
    from app import auth_throttle

    scope, window, limit = "login_ip", 600, 5
    digest = "d" * 64
    conn = _adapter(TRANSACTION_URL)
    try:
        for index in range(limit):
            assert auth_throttle.blocked(conn, scope, digest, window_seconds=window, max_attempts=limit)[0] is False
            auth_throttle.register(conn, [(scope, digest)], window_seconds=window)
        assert auth_throttle.blocked(conn, scope, digest, window_seconds=window, max_attempts=limit)[0] is True
        auth_throttle.clear(conn, [(scope, digest)])
        assert auth_throttle.blocked(conn, scope, digest, window_seconds=window, max_attempts=limit)[0] is False
    finally:
        conn.close()
    workers, failures = 8, []
    barrier = threading.Barrier(workers)

    def writer(index):
        own = _adapter(TRANSACTION_URL)
        try:
            barrier.wait(timeout=60)
            auth_throttle.register(own, [(scope, "c" * 64)], window_seconds=window)
        except Exception as exc:  # pragma: no cover - reported below
            failures.append(repr(exc)[:120])
        finally:
            own.close()

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    assert failures == []
    check = _adapter(TRANSACTION_URL)
    try:
        count = check.execute("SELECT count(*) FROM auth_throttle_events WHERE scope = ? AND key_digest = ?",
                              (scope, "c" * 64)).fetchone()[0]
        check.execute("DELETE FROM auth_throttle_events WHERE scope = ?", (scope,))
        check.commit()
    finally:
        check.close()
    assert count == workers  # no lost event, no deadlock


def test_an_import_preview_is_claimed_by_exactly_one_of_several_concurrent_confirmations():
    from app import import_previews
    from app.db import write_transaction

    usuario_id = STATE.get("admin_id")
    assert usuario_id, "the bootstrap lane creates the administrator"
    conn = _adapter(TRANSACTION_URL)
    try:
        token = import_previews.store(conn, usuario_id=usuario_id, payload={"rows": [1, 2, 3]})
    finally:
        conn.close()
    winners, errors = [], []
    barrier = threading.Barrier(6)

    def confirm():
        own = _adapter(TRANSACTION_URL)
        try:
            barrier.wait(timeout=60)
            with write_transaction(own):
                winners.append(import_previews.claim(own, usuario_id=usuario_id, token=token))
        except Exception as exc:  # pragma: no cover
            errors.append(repr(exc)[:120])
        finally:
            own.close()

    threads = [threading.Thread(target=confirm) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    assert errors == [] and sorted(winners) == [False] * 5 + [True]


def test_a_row_lock_serializes_two_writers_and_skip_locked_never_waits():
    from app.db import lock_password_account, skip_locked

    usuario_id = STATE.get("admin_id")
    assert usuario_id, "the preview lane seeds the administrator"
    holder = _adapter(TRANSACTION_URL)
    waiter_result = {}
    try:
        assert lock_password_account(holder, usuario_id) is True
        released_at = {}

        def waiter():
            own = _adapter(TRANSACTION_URL)
            try:
                started = time.perf_counter()
                acquired = lock_password_account(own, usuario_id)
                waiter_result["waited"] = time.perf_counter() - started
                waiter_result["acquired"] = acquired
                waiter_result["after_release"] = time.perf_counter() >= released_at.get("t", float("inf"))
                own.rollback()
            finally:
                own.close()

        thread = threading.Thread(target=waiter)
        thread.start()
        time.sleep(3)
        assert thread.is_alive(), "the second writer must wait for the first"
        # while the row is held, a SKIP LOCKED reader passes it by without waiting
        reader = _adapter(TRANSACTION_URL)
        try:
            started = time.perf_counter()
            rows = reader.execute(
                f"SELECT id FROM usuarios WHERE id = ? FOR UPDATE{skip_locked(reader)}", (usuario_id,)).fetchall()
            skipped_in = time.perf_counter() - started
            reader.rollback()
        finally:
            reader.close()
        assert rows == [] and skipped_in < 3
        released_at["t"] = time.perf_counter()
        holder.rollback()
        thread.join(timeout=60)
    finally:
        holder.close()
    assert waiter_result.get("acquired") is True and waiter_result.get("after_release") is True
    assert waiter_result["waited"] >= 2.5


def test_prepared_statements_are_off_on_the_transaction_pooler_path():
    conn = _adapter(TRANSACTION_URL)
    try:
        for index in range(12):  # past psycopg's default prepare threshold
            assert conn.execute("SELECT ? + 1", (index,)).fetchone()[0] == index + 1
        assert conn.execute("SELECT count(*) FROM pg_prepared_statements").fetchone()[0] == 0
    finally:
        conn.close()


# ---- session mode: the snapshot backup, then DR1 --------------------------------------------------


def test_the_snapshot_backup_refuses_the_transaction_pooler_and_runs_through_session_mode(tmp_path, monkeypatch):
    from tools import pg_backup

    monkeypatch.setenv(pg_backup.SOURCE_URL_ENV, TRANSACTION_URL)
    with pytest.raises(pg_backup.Refused) as caught:
        pg_backup.backup(str(tmp_path / "refused"), "dev-live")
    assert "TRANSACTION" in caught.value.code
    monkeypatch.setenv(pg_backup.SOURCE_URL_ENV, SESSION_URL)
    sets = tmp_path / "dev-set"
    sets.mkdir()
    with _timed("dev_backup_seconds"):
        pg_backup.backup(str(sets), "dev-live")
    manifest = next(sets.glob("*.manifest.json"))
    loaded = pg_backup.verify_artifact(str(manifest))
    STATE["dev_manifest"] = manifest
    STATE["dev_set_dir"] = sets
    assert loaded.manifest["server"]["major"] == 17


def test_dr1_a_set_taken_from_dev_restores_into_local_postgres_and_the_application_boots_on_it(
        tmp_path, local_registry, monkeypatch):
    """The managed-platform RTO: restore start -> the application serves and the smoke passes."""
    from tools import pg_backup

    manifest = STATE.get("dev_manifest")
    assert manifest is not None
    name, url = local_registry.create()
    served = None
    try:
        with _timed("dr1_rto_seconds"):
            with _timed("dr1_restore_seconds"):
                pg_backup.restore(str(manifest), target_url=url)
            loaded = pg_backup.verify_artifact(str(manifest))
            pg_backup.verify_database(loaded.manifest, url)
            served = _Served(url, tmp_path)
            report = _smoke(served.url)
        assert {c["check"] for c in report["checks"]} >= {"HEALTH", "LOGIN_PAGE", "SIGN_IN"}
    finally:
        if served is not None:
            served.close()
        local_registry.drop(name)


# ---- DR3: a foreign set into the managed target, served through the transaction pooler ---------


def test_dr3_a_synthetic_set_from_local_postgres_restores_into_dev_through_the_supabase_profile(
        tmp_path, local_registry, monkeypatch):
    from app import pg_schema
    from tools import pg_backup

    name, url = local_registry.create()
    try:
        raw = _raw(url, autocommit=False)
        try:
            pg_schema.provision_pg_schema(raw)
            raw.commit()
        finally:
            raw.close()
        conn = _adapter(url)
        try:
            seed_admin(conn)
            conn.commit()
        finally:
            conn.close()
        monkeypatch.setenv(pg_backup.SOURCE_URL_ENV, url)
        sets = tmp_path / "local-set"
        sets.mkdir()
        pg_backup.backup(str(sets), "foreign")
    finally:
        local_registry.drop(name)
    manifest = next(sets.glob("*.manifest.json"))
    pg_backup.verify_artifact(str(manifest))
    # an empty managed target: DEV public emptied again (run-owned), the recipe applied
    _reset_public(SESSION_URL)
    _apply_recipe(SESSION_URL)
    monkeypatch.setenv(pg_backup.SOURCE_URL_ENV, "postgresql://unused@127.0.0.1:1/x")
    served = None
    try:
        with _timed("dr3_rto_seconds"):
            with _timed("dr3_restore_seconds"):
                pg_backup.restore(str(manifest), target_url=SESSION_URL, profile="supabase")
            loaded = pg_backup.verify_artifact(str(manifest))
            pg_backup.verify_database(loaded.manifest, SESSION_URL)
            _apply_recipe(SESSION_URL)  # Layer-2 dumps with --no-privileges: the recipe again
            raw = _raw(SESSION_URL)
            try:
                exposure = pg_schema.api_role_exposure(raw)
            finally:
                raw.close()
            assert exposure["clean"] is True
            served = _Served(TRANSACTION_URL, tmp_path)  # the runtime path: the transaction pooler
            report = _smoke(served.url)
        assert {c["check"] for c in report["checks"]} >= {"HEALTH", "LOGIN_PAGE", "SIGN_IN"}
    finally:
        if served is not None:
            served.close()
    # the profile refused a used project afterwards: the target is no longer empty
    with pytest.raises(pg_backup.Refused) as caught:
        pg_backup.restore(str(manifest), target_url=SESSION_URL, profile="supabase")
    assert caught.value.code == "TARGET_NOT_EMPTY"
