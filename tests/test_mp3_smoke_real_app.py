# coding: utf-8
"""MP-3 slice 5 on real PostgreSQL (opt-in): the public smoke against the REAL application.

``test_mp3_hosted_smoke`` pins the tool against a scripted server.  Here the tool
runs over HTTP against ``main:app`` -- the entrypoint a WSGI host loads -- in
production + hosted mode, in a FRESH interpreter with a platform-shaped
environment and a disposable PostgreSQL database, so a header, a cookie flag or
a route the smoke expects is proven to be what the application actually does.
Without ``SGAA_PG_TEST_URL`` the module skips (REAL-PG EVIDENCE: ABSENT).
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.mp2_pg_support import ADMIN_EMAIL, ADMIN_PASSWORD, PG_URL, Registry, seed_admin
from tests.storage_mp1_support import SEED_SQL
from tools import hosted_smoke, pg_fingerprint

pytestmark = pytest.mark.skipif(
    not PG_URL, reason="SGAA_PG_TEST_URL is not configured -- REAL-PG EVIDENCE: ABSENT"
)

pytest.importorskip("psycopg")

REPO_ROOT = Path(__file__).resolve().parents[1]
_KEEP = ("SYSTEMROOT", "SystemDrive", "WINDIR", "COMSPEC", "PATHEXT", "PATH", "USERPROFILE", "OS")
_SERVER = (
    "import main; from werkzeug.serving import make_server; import sys;"
    "s = make_server('127.0.0.1', int(sys.argv[1]), main.app, threaded=True);"
    "print('READY', flush=True); s.serve_forever()"
)


_RETURNED_REQUEST = (
    "UPDATE requisicoes SET status = 'Devolvida', data_processamento = '2020-01-01 00:00:00' WHERE id = 2"
)


def _seed(conn) -> None:
    """The real administrator, plus a student with one pending and one returned (long overdue) request.

    The returned request is the trap: its deadline has passed, so an administrator's dashboard view
    would derive an automatic rejection.  The smoke must never open that view.
    """
    seed_admin(conn)
    business = [
        (sql, params) for sql, params in SEED_SQL
        if not sql.startswith(("INSERT INTO cloud_accounts", "INSERT INTO usuarios(id,nome,email,senha,tipo) VALUES(1,"))
    ]
    for sql, params in business:
        conn.execute(sql, params)
    conn.execute(
        "INSERT INTO requisicoes(id,aluno_id,atividade_versao_id,data_solicitacao,data_evento,horas_solicitadas,"
        "status,regra_snapshot_json,turma_id_snapshot,turma_codigo_snapshot)"
        " SELECT 2,aluno_id,atividade_versao_id,data_solicitacao,data_evento,horas_solicitadas,"
        "status,regra_snapshot_json,turma_id_snapshot,turma_codigo_snapshot FROM requisicoes WHERE id = 1"
    )
    conn.execute(_RETURNED_REQUEST)
    # The column default is the legacy 'administrativo'; accounts made by the production owner carry 'aluno'.
    conn.execute("UPDATE usuarios SET nivel_acesso = 'aluno' WHERE id = 2")


@pytest.fixture(scope="module")
def registry():
    registry = Registry("smoke")
    try:
        registry.provision_template(seed=_seed)
        yield registry
    finally:
        assert registry.close() == 0


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture
def served(registry, tmp_path):
    """``main:app`` in production + hosted mode served on 127.0.0.1 by a child interpreter."""
    from cryptography.fernet import Fernet

    name, url = registry.create(template=registry.template)
    env = {key: os.environ[key] for key in _KEEP if key in os.environ}
    env.update({
        "TEMP": str(tmp_path), "TMP": str(tmp_path), "TMPDIR": str(tmp_path),
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8",
        "DATABASE_URL": url, "SGAA_RUNTIME": "hosted", "APP_ENV": "production", "TRUST_PROXY_XFF": "1",
        "APP_SECRET_KEY": "p" + "3" * 47, "TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "APP_PUBLIC_BASE_URL": "https://sgaa.example.test", "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_SECRET_KEY": "not-a-real-key-" + "x" * 20, "SGAA_STORAGE_BUCKET": "sgaa-documentos",
        "GOOGLE_CLIENT_ID": "", "GOOGLE_CLIENT_SECRET": "",
    })
    port = _free_port()
    child = subprocess.Popen(
        [sys.executable, "-c", _SERVER, str(port)], cwd=REPO_ROOT, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
    )
    try:
        deadline = time.time() + 90
        while time.time() < deadline:
            if child.stdout.readline().strip() == "READY":
                break
            if child.poll() is not None:
                raise AssertionError("the application did not start")
        else:
            raise AssertionError("the application did not become ready")
        yield SimpleNamespace(url=f"http://127.0.0.1:{port}", database=url)
    finally:
        child.kill()
        child.wait(timeout=30)
        registry.drop(name)


def _fingerprint(url):
    from tools import pg_backup

    conn = pg_backup.connect(url)
    try:
        return pg_fingerprint.snapshot(conn)
    finally:
        conn.close()


def test_the_real_application_passes_every_public_check_and_the_smoke_writes_no_business_row(served):
    before = _fingerprint(served.database)
    report = hosted_smoke.run(served.url, allow_insecure=True, email=ADMIN_EMAIL, password=ADMIN_PASSWORD)
    failed = [(item["check"], item["code"]) for item in report["checks"] if not item["ok"]]
    assert report["result"] == "PASS", failed
    assert {item["check"] for item in report["checks"]} >= {
        "HEALTH", "LOGIN_PAGE", "COOKIE_FLAGS", "HEADERS", "ADMIN_REFUSED", "STATIC", "SCHEDULER",
        "NO_TRACEBACK", "SIGN_IN",
    }
    # The smoke's only application write is the sign-in; the PONR detector must not see it (SPEC D8).
    assert pg_fingerprint.compare(before, _fingerprint(served.database)) == {
        "identical": True, "changed_tables": [], "detail": {}}


def _smoke(served):
    report = hosted_smoke.run(served.url, allow_insecure=True, email=ADMIN_EMAIL, password=ADMIN_PASSWORD)
    assert report["result"] == "PASS", [(i["check"], i["code"]) for i in report["checks"] if not i["ok"]]


def test_a_legacy_access_level_is_normalized_once_by_the_first_sign_in_so_the_reference_follows_the_smoke(served):
    """A student row that kept the legacy default is rewritten by the application's own start-up
    normalization on the first sign-in -- a derived write the PONR detector WOULD count.  The cutover
    order (smoke C10 before the reference C12) makes it happen before the reference; this pins both facts."""
    from tools import pg_backup

    conn = pg_backup.connect(served.database)
    try:
        conn.execute("UPDATE usuarios SET nivel_acesso = 'administrativo' WHERE id = 2")
        conn.commit()
    finally:
        conn.close()
    reference_before_smoke = _fingerprint(served.database)
    _smoke(served)
    after_first = pg_fingerprint.compare(reference_before_smoke, _fingerprint(served.database))
    assert after_first["changed_tables"] == ["USUARIOS"]
    assert after_first["detail"]["USUARIOS"]["changed_columns"] == ["nivel_acesso"]
    reference_after_smoke = _fingerprint(served.database)
    _smoke(served)
    assert pg_fingerprint.compare(reference_after_smoke, _fingerprint(served.database))["identical"] is True


def test_the_seeded_requests_are_what_the_trap_needs(served):
    from tools import pg_backup

    conn = pg_backup.connect(served.database)
    try:
        rows = conn.execute("SELECT id, status FROM requisicoes ORDER BY id").fetchall()
    finally:
        conn.close()
    assert [tuple(row) for row in rows] == [(1, "Pendente"), (2, "Devolvida")]
