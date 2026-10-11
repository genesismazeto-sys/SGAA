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
# Before the opening the deployment admits only the operator: the DR smokes run as C10 does (MP-3 A15/A17).
OPERATOR_TOKEN = "live-operator-" + "L7" * 16


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
            "SGAA_ADMISSION": "operator", "SGAA_OPERATOR_TOKEN": OPERATOR_TOKEN,
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

    report = hosted_smoke.run(url, allow_insecure=True, email=ADMIN_EMAIL, password=ADMIN_PASSWORD,
                              operator_token=OPERATOR_TOKEN, admission="closed")
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
    env.update({"DATABASE_URL": SESSION_URL, "SGAA_RUNTIME": "hosted", "APP_ENV": "production", "SGAA_ADMISSION": "open",
                "SGAA_OPENING_REFERENCE": "5" * 64, "APP_SECRET_KEY": "p" + "3" * 47, "TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode(),
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
    # The C1 qualification names the project this connection belongs to (the pooler's tenant) and
    # proves the cluster: DEV's here; at GP1 it must be the PROD project of C0 (MP-3 A16).
    from app import hosting
    from psycopg.conninfo import conninfo_to_dict

    tenant = conninfo_to_dict(SESSION_URL)["user"]
    assert database["database_project_sha256"] == hosting.project_sha256(tenant.split(".", 1)[1])
    assert database["database_identity_proven"] is True


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


# ---- A17: the verified source, the qualification, the barrier and the governed provenance on DEV ------------

# The PROD project of record: only its name's digest is used, to bind a ledger; it is never connected to.
PROD_REF_OF_RECORD = "uckadhcwfknklmdktuyi"


def _dev_env():
    from tests import mp3_rehearsal_support as rs

    if not rs.env_file().is_file():
        pytest.skip("the DEV Storage credential file is needed for the storage API channel")
    return rs.load_dev_env()


def test_the_verified_source_reaches_dev_only_through_tls_verified_against_the_pinned_ca(tmp_path, monkeypatch):
    """Finding 3 live: verify-full against the pinned root; a redirect or another root fails before any query."""
    from app import hosting
    from tools import prod_source

    conn = prod_source.connect(SESSION_URL)
    try:
        seen = prod_source.observe(conn)
        settings = conn.info.get_parameters()
        assert conn.pgconn.ssl_in_use and settings["sslmode"] == "verify-full"
    finally:
        conn.close()
    tenant = psycopg.conninfo.conninfo_to_dict(SESSION_URL)["user"].split(".", 1)[1]
    assert seen.project_sha256 == hosting.project_sha256(tenant)
    # The application's own path (the transaction pooler) reads the same identity the ledger records.
    with _raw(TRANSACTION_URL) as app_conn:
        assert hosting.source_identity_sha256(hosting.database_source(app_conn)) == seen.identity
    base = prod_source.verified_url(SESSION_URL).split("?", 1)[0]
    # Another root (the operating system's store) does not verify the provider's certificate ...
    with pytest.raises(psycopg.OperationalError):
        psycopg.connect(base + "?sslmode=verify-full&sslrootcert=system", connect_timeout=20).close()
    # ... and a redirect of the pooler's name to another server (here the local test server, as a hosts
    # entry or a hostaddr would do) fails the verification before any query.
    local = psycopg.conninfo.conninfo_to_dict(PG_URL)
    redirected = prod_source.verified_url(SESSION_URL) + f"&hostaddr=127.0.0.1&port={local.get('port', '5432')}"
    with pytest.raises(psycopg.OperationalError):
        psycopg.connect(redirected, connect_timeout=20).close()
    for name, value in (("PGHOSTADDR", "127.0.0.1"), ("PGHOST", "localhost"), ("PGSERVICE", "prod"),
                        ("PGSSLMODE", "disable"), ("PGSSLROOTCERT", "system")):
        monkeypatch.setenv(name, value)
        with pytest.raises(prod_source.Refused) as caught:
            prod_source.connect(SESSION_URL)
        assert caught.value.code == "SOURCE_ENV_ROUTING"
        monkeypatch.delenv(name)
    with pytest.raises(prod_source.Refused) as caught:
        prod_source.connect(TRANSACTION_URL)
    assert caught.value.code == "SOURCE_NOT_THE_SESSION_POOLER"


def _dev_observer():
    from tools import cutover_ledger as ledger

    return ledger.Observer(database_url=SESSION_URL)


def _ledger_bound_to(directory, project_ref):
    from app import hosting
    from tests.mp3_ledger_support import ALL_GATES, GOOD
    from tools import cutover_ledger as ledger

    ledger.init(directory)
    for index, gate in enumerate(ALL_GATES):
        ledger.grant(directory, gate, f"user-msg-{index}")
    ledger.advance(directory, "C0", dict(GOOD["C0"], prod_project_sha256=hosting.project_sha256(project_ref)))
    return directory


def test_the_ledger_qualifies_dev_by_its_authenticated_tenant_and_its_own_storage_api(tmp_path, monkeypatch):
    from tests import mp3_rehearsal_support as rs
    from tools import cutover_ledger as ledger

    dev = _dev_env()
    tenant = psycopg.conninfo.conninfo_to_dict(SESSION_URL)["user"].split(".", 1)[1]
    monkeypatch.setenv("SUPABASE_URL", dev["SUPABASE_URL"])
    monkeypatch.setenv("SUPABASE_SECRET_KEY", dev["SUPABASE_SECRET_KEY"])
    bucket = rs.RunBucket(dev)
    bucket.create()
    try:
        monkeypatch.setenv("SGAA_STORAGE_BUCKET", bucket.name)
        bound_to_prod = _ledger_bound_to(tmp_path / "prod", PROD_REF_OF_RECORD)
        with pytest.raises(ledger.Refused) as caught:  # DEV through a verified connection is still not PROD
            ledger.qualify(bound_to_prod, observer=_dev_observer())
        assert caught.value.code == "DATABASE_NOT_THE_PROD_PROJECT"
        bound_to_dev = _ledger_bound_to(tmp_path / "dev", tenant)
        entry = ledger.qualify(bound_to_dev, observer=_dev_observer())
        assert entry["tls"] == "VERIFIED" and entry["buckets_compared"] >= 1
        STATE["dev_identity"] = entry["database_identity_sha256"]
    finally:
        bucket.purge_and_delete()


def _barrier_probe(url, value):
    with _raw(url) as conn:
        conn.execute("INSERT INTO public.sgaa_mp3_barrier_probe(x) VALUES (%s)", (value,))


def test_the_write_barrier_on_dev_ends_older_sessions_and_refuses_every_new_write_until_lifted():
    """Finding 2 live: the provider's poolers, the application's path included, cannot write under the barrier."""
    observer = _dev_observer()
    with _raw(SESSION_URL) as conn:
        conn.execute("CREATE TABLE public.sgaa_mp3_barrier_probe (x integer)")
    held = _raw(SESSION_URL)  # a session opened before the barrier, held like a long request
    applied = None
    try:
        _barrier_probe(TRANSACTION_URL, 1)  # the application's path writes before the barrier
        with _timed("barrier_apply_seconds"):
            applied = observer.apply_barrier()
        assert applied["terminated"] >= 1
        state = observer.barrier_state(applied["barrier_at"])
        assert state == {"setting": True, "fresh_read_only": True, "write_refused": True, "older_sessions": 0,
                         "authorizations_in_force": 0}, state
        with pytest.raises(psycopg.OperationalError):
            held.execute("SELECT 1")  # ended: a session from before the barrier never writes after it
        for url in (TRANSACTION_URL, SESSION_URL):
            with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
                _barrier_probe(url, 2)
        with _timed("barrier_lift_seconds"):
            assert observer.lift_barrier("0" * 64) is True
        applied = None
        _barrier_probe(TRANSACTION_URL, 3)  # writable again once lifted
        with _raw(SESSION_URL) as conn:
            assert [row[0] for row in conn.execute("SELECT x FROM public.sgaa_mp3_barrier_probe ORDER BY x")] == [1, 3]
            assert conn.execute("SELECT count(*) FROM pg_db_role_setting WHERE setrole = (SELECT oid FROM pg_roles"
                                " WHERE rolname = current_user) AND 'default_transaction_read_only=on'"
                                " = ANY (setconfig)").fetchone()[0] == 0
    finally:
        if applied is not None:
            observer.lift_barrier("0" * 64)
        try:
            held.close()
        except Exception:
            pass
        with _raw(SESSION_URL) as conn:
            conn.execute("DROP TABLE IF EXISTS public.sgaa_mp3_barrier_probe")


def test_a_governed_generation_on_dev_is_recorded_with_the_provenance_of_its_own_run(
        tmp_path, local_registry, monkeypatch):
    """Findings 3, 4 and 6 live: the baseline and a generation taken from DEV through the verified source,
    the baseline restored into local scratch by the drill, each recorded only as its run's receipt."""
    from app import hosting
    from tests import mp3_ledger_support as ls
    from tests import mp3_rehearsal_support as rs
    from tests.mp3_ledger_support import DEPLOYMENT, GOOD
    from tools import cutover_ledger as ledger
    from tools import ops_backup

    dev = _dev_env()
    tenant = psycopg.conninfo.conninfo_to_dict(SESSION_URL)["user"].split(".", 1)[1]
    project = hosting.project_sha256(tenant)
    for name in ("SUPABASE_URL", "SUPABASE_SECRET_KEY"):
        monkeypatch.setenv(name, dev[name])
    monkeypatch.setenv("DATABASE_URL", SESSION_URL)
    bucket = rs.RunBucket(dev)
    bucket.create()
    scratch_name, scratch_url = local_registry.create()
    try:
        monkeypatch.setenv("SGAA_STORAGE_BUCKET", bucket.name)
        directory = _ledger_bound_to(tmp_path / "ledger", tenant)
        qualified = ledger.qualify(directory, observer=_dev_observer())
        ledger.advance(directory, "C1", dict(GOOD["C1"], data_api_project_sha256=project))
        for state in ledger.STATES[2:8]:
            ledger.advance(directory, state, GOOD[state])
        root = tmp_path / "baseline"
        with _timed("governed_baseline_seconds"):
            ops_backup.run_governed(directory, root, tmp_path / "baseline-off", objects=True, baseline=True)
        baseline = [e for e in ledger.read_ledger(directory) if e["type"] == "backup"][-1]
        assert baseline["kind"] == "BASELINE" and baseline["provenance"] == "LIVE_RUN"
        assert baseline["source_identity_sha256"] == qualified["database_identity_sha256"]
        drill_env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
        drill_env["SGAA_RESTORE_TARGET_URL"] = scratch_url
        with _timed("governed_drill_seconds"):
            drilled = ops_backup.drill(directory, root, tmp_path / "baseline-off", baseline["manifest_sha256"],
                                       environ=drill_env)
        assert drilled["result"] == "DRILL_VERIFIED"
        ledger.advance(directory, "C8", dict(GOOD["C8"], baseline_manifest_sha256=baseline["manifest_sha256"],
                                             object_set_digest=baseline["object_set_digest"]))
        platform = ls.Platform()  # no deployment is made in this lane: the states are recorded as receipts
        ls.record_served(directory, platform, DEPLOYMENT, "https://dark.example.test", code=ls.CODE)
        ledger.advance(directory, "C9", GOOD["C9"])
        ls.promote_served(directory, platform, DEPLOYMENT, code=ls.CODE, host=ls.PUBLIC_HOST)
        ledger.advance(directory, "C10", dict(GOOD["C10"], data_api_project_sha256=project))
        ledger.advance(directory, "C11", GOOD["C11"])
        # A governed generation whose DATABASE_URL is not the verified session address is refused before any step.
        monkeypatch.setenv("DATABASE_URL", TRANSACTION_URL)
        with pytest.raises(ops_backup.Refused) as caught:
            ops_backup.run_governed(directory, tmp_path / "wrong", tmp_path / "wrong-off", objects=True)
        assert caught.value.code == "SOURCE_NOT_THE_SESSION_POOLER" and not (tmp_path / "wrong").exists()
        monkeypatch.setenv("DATABASE_URL", SESSION_URL)
        with _timed("governed_generation_seconds"):
            ops_backup.run_governed(directory, tmp_path / "primary", tmp_path / "primary-off", objects=True)
        generation = [e for e in ledger.read_ledger(directory) if e["type"] == "backup"][-1]
        assert generation["kind"] == "GENERATION" and generation["provenance"] == "LIVE_RUN"
        assert generation["source_identity_sha256"] == baseline["source_identity_sha256"]
        assert generation["store_project_sha256"] == project
    finally:
        local_registry.drop(scratch_name)
        bucket.purge_and_delete()


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
