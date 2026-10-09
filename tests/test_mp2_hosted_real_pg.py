# coding: utf-8
"""MP-2 slice 1 on real PostgreSQL (opt-in, ``SGAA_PG_TEST_URL``): the hosted runtime end to end.

Without ``SGAA_PG_TEST_URL`` the module skips (REAL-PG EVIDENCE: ABSENT).

E-PG1: ``import main`` -- exactly what a WSGI host does -- in a FRESH interpreter
with a hosted environment, a disposable PostgreSQL database and the write
tripwire installed before the import.  The process serves the health check,
the login page, a real login, the admin dashboard and the Banco de dados page
and must attempt no write outside its scratch root and open no SQLite
connection.  The same script in local mode is the discriminating control: it
does attempt writes, and the tripwire sees them.

The health check also reports schema version skew between the code and the
provisioned database (a deployment fault) instead of failing later at random.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from tests.mp2_pg_support import ADMIN_EMAIL, ADMIN_PASSWORD, PG_URL, Registry, seed_admin

pytestmark = pytest.mark.skipif(
    not PG_URL, reason="SGAA_PG_TEST_URL is not configured -- REAL-PG EVIDENCE: ABSENT"
)

pytest.importorskip("psycopg")

REPO_ROOT = Path(__file__).resolve().parents[1]
_KEEP_FROM_PARENT = ("SYSTEMROOT", "SystemDrive", "WINDIR", "COMSPEC", "PATHEXT", "PATH", "USERPROFILE", "OS")


@pytest.fixture(scope="module")
def registry():
    registry = Registry("host")
    try:
        registry.provision_template(seed=seed_admin)
        yield registry
    finally:
        assert registry.close() == 0


@pytest.fixture
def database(registry):
    name, url = registry.create(template=registry.template)
    yield url
    registry.drop(name)


def _child_environment(url: str, scratch_parent: Path, *, hosted: bool) -> dict:
    """What a platform provides -- and nothing the developer machine happens to export."""
    env = {name: os.environ[name] for name in _KEEP_FROM_PARENT if name in os.environ}
    temp = str(scratch_parent)
    scratch = Path(temp) / "sgaa-scratch"
    env.update(
        {
            "TEMP": temp, "TMP": temp, "TMPDIR": temp,
            "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8",
            "DATABASE_URL": url,
            "SGAA_RUNTIME": "hosted" if hosted else "local",
            "TRUST_PROXY_XFF": "1",
            "APP_ENV": "development",
            "APP_SECRET_KEY": "s" + "9" * 47,
            "MP2_SCRATCH": str(scratch),
            "MP2_ADMIN_EMAIL": ADMIN_EMAIL,
            "MP2_ADMIN_PASSWORD": ADMIN_PASSWORD,
            # .env is loaded by main without overriding: blank what it might define.
            "TOKEN_ENCRYPTION_KEY": "", "GOOGLE_CLIENT_ID": "", "GOOGLE_CLIENT_SECRET": "",
            "SUPABASE_URL": "", "SUPABASE_SECRET_KEY": "", "SGAA_STORAGE_BUCKET": "", "APP_PUBLIC_BASE_URL": "",
        }
    )
    return env


def _run_smoke(url: str, tmp_path: Path, *, hosted: bool) -> dict:
    result = subprocess.run(
        [sys.executable, "-m", "tests.mp2_hosted_smoke_script"],
        cwd=REPO_ROOT, env=_child_environment(url, tmp_path, hosted=hosted),
        capture_output=True, text=True, timeout=240,
    )
    lines = [line for line in result.stdout.splitlines() if line.startswith("{")]
    assert lines, f"no report (exit {result.returncode}); stderr tail: {result.stderr[-600:]}"
    return json.loads(lines[-1])


def test_a_hosted_process_serves_real_requests_with_zero_writes(database, tmp_path):
    report = _run_smoke(database, tmp_path, hosted=True)
    assert report["import_error"] is None, report.get("import_traceback")
    # APP_LOG_DIR is deliberately NOT set: the hosted default must keep `main`'s
    # import-time log directory inside scratch on its own.
    assert report["attempts"] == [], report["attempts"]
    steps = report["steps"]
    assert steps["health"] == {"status": 200, "json": {"status": "ok"}}
    assert steps["login_page"]["status"] == 200
    assert steps["login"]["status"] == 302 and steps["login"]["location"].endswith("/admin/dashboard")
    assert steps["csrf_token"]["status"] == 200 and steps["csrf_token"]["json"]["csrf_token"]
    assert steps["admin_dashboard"]["status"] == 200
    assert steps["banco_dados"]["status"] == 200
    assert os.path.normcase(report["upload_folder"]).startswith(os.path.normcase(str(tmp_path / "sgaa-scratch")))


def test_the_same_script_in_local_mode_is_caught_writing(database, tmp_path):
    """Control: without the hosted contract the very same import DOES write."""
    report = _run_smoke(database, tmp_path, hosted=False)
    assert report["attempts"], "the tripwire must see the local runtime create its directories"
    assert {operation for operation, _path in report["attempts"]} & {"os.makedirs", "os.mkdir"}
    assert report["import_error"] == "OSError"


def _hosted_app(monkeypatch, url, tmp_path):
    import app.db as app_db

    for name in ("VERCEL", "AWS_LAMBDA_FUNCTION_NAME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SGAA_RUNTIME", "hosted")
    monkeypatch.setenv("TRUST_PROXY_XFF", "1")
    monkeypatch.setenv("APP_SECRET_KEY", "h" + "5" * 47)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(app_db, "DATABASE_URL", url)
    from app import create_app

    return create_app()


def test_health_reports_schema_version_skew_between_code_and_database(database, monkeypatch, tmp_path):
    from app import pg_schema

    flask_app = _hosted_app(monkeypatch, database, tmp_path)
    client = flask_app.test_client()
    assert client.get("/health").status_code == 200
    # The code now expects a schema the database was not provisioned with.
    monkeypatch.setattr(pg_schema, "PG_SCHEMA_VERSION", pg_schema.PG_SCHEMA_VERSION + 1)
    response = client.get("/health")
    assert response.status_code == 500 and json.loads(response.data) == {"status": "error"}


def test_check_database_reports_current_and_skewed_schemas(database, monkeypatch, tmp_path):
    from app import hosting_cli, pg_schema

    _hosted_app(monkeypatch, database, tmp_path)

    def run():
        out = io.StringIO()
        code = hosting_cli.main(["check", "--database"], out=out)
        return code, json.loads(out.getvalue())

    code, report = run()
    assert code == 0 and report["database"]["current"] is True
    assert report["database"]["backend"] == "postgres"
    assert report["database"]["schema_version"] == report["database"]["target_schema_version"]
    monkeypatch.setattr(pg_schema, "PG_SCHEMA_VERSION", pg_schema.PG_SCHEMA_VERSION + 1)
    code, report = run()
    assert code == 1 and "error_type" in report["database"]
