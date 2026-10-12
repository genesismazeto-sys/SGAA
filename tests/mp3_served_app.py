# coding: utf-8
"""TEST ONLY: ``main:app`` served over HTTP by a fresh interpreter in hosted production mode.

The entrypoint a WSGI host loads, with a platform-shaped environment and no test-suite
variables (CSRF on, production settings), on 127.0.0.1.  ``extra_env`` overrides any
variable (the admission mode, the operator credential).  Shared by the MP-3 real-application
lanes; never imported by the application.

An open production application admits users only under the authorization the cutover ledger
writes with its reference (MP-3 A17).  Unless a lane names its own ``SGAA_OPENING_REFERENCE``,
an open application is served the way production is lifted: an authorization for this database,
this code and this platform project is written first (``authorize_opening``) and the application
carries its reference.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from tests.mp3_ledger_support import PROJECT_ID  # the platform project the served applications belong to

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVED_SECRET_KEY = "p" + "3" * 47
# The value an open application starts from: ``served_app`` replaces it with the reference of an authorization
# it writes, unless the lane names its own (a lane that tests the opening itself).
SERVED_OPENING_REFERENCE = "5" * 64
# APPDATA / LOCALAPPDATA: libpq finds the workstation password file there (the live lanes).
_KEEP = ("SYSTEMROOT", "SystemDrive", "WINDIR", "COMSPEC", "PATHEXT", "PATH", "USERPROFILE", "OS",
         "APPDATA", "LOCALAPPDATA", "HOMEDRIVE", "HOMEPATH")
_SERVER = (
    "import importlib, sys; from werkzeug.serving import make_server;"
    "module, name = sys.argv[2].split(':');"
    "s = make_server('127.0.0.1', int(sys.argv[1]), getattr(importlib.import_module(module), name), threaded=True);"
    "print('READY', flush=True); s.serve_forever()"
)


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def hosted_environment(database_url: str, tmp_path, **extra_env) -> dict:
    from cryptography.fernet import Fernet

    env = {key: os.environ[key] for key in _KEEP if key in os.environ}
    env.update({
        "TEMP": str(tmp_path), "TMP": str(tmp_path), "TMPDIR": str(tmp_path),
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8",
        "DATABASE_URL": database_url, "SGAA_RUNTIME": "hosted", "APP_ENV": "production", "TRUST_PROXY_XFF": "1",
        "SGAA_ADMISSION": "open", "SGAA_OPENING_REFERENCE": SERVED_OPENING_REFERENCE,
        "APP_SECRET_KEY": SERVED_SECRET_KEY, "TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "APP_PUBLIC_BASE_URL": "https://sgaa.example.test", "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_SECRET_KEY": "not-a-real-key-" + "x" * 20, "SGAA_STORAGE_BUCKET": "sgaa-documentos",
        "GOOGLE_CLIENT_ID": "", "GOOGLE_CLIENT_SECRET": "",
    })
    env.setdefault("VERCEL_PROJECT_ID", PROJECT_ID)
    env.update({key: str(value) for key, value in extra_env.items()})
    return env


def authorize_opening(database_url: str) -> str:
    """TEST ONLY: what the ledger's ``reference`` writes into PROD, for this database and the served code.

    A ledger-shaped reference entry naming the database's live identity, the code the served
    application runs and the platform project, stored through the ledger's own writer; returns the
    entry's hash (the value an open application is lifted with).
    """
    import hashlib
    import secrets

    from app import hosting
    from tests.mp3_ledger_support import local_connector
    from tools import cutover_ledger

    conn = local_connector(database_url)(database_url)
    try:
        identity = hosting.source_identity_sha256(hosting.database_source(conn))
    finally:
        conn.close()
    body = {"seq": 2 + secrets.randbelow(10 ** 6), "prev": "0" * 64, "at": "2026-11-01T00:00:00Z", "type": "reference",
            "database_identity_sha256": identity, "code_sha256": hosting.runtime_code_sha256(REPO_ROOT),
            "vercel_project_sha256": hashlib.sha256(PROJECT_ID.encode("utf-8")).hexdigest()}
    entry = dict(body, hash=hosting.ledger_entry_hash(body))
    observer = cutover_ledger.Observer(database_url=database_url, source_connector=local_connector(database_url))
    observer.authorize(entry["hash"], body["code_sha256"], entry, first=False)
    return entry["hash"]


@contextmanager
def served_app(database_url: str, tmp_path, *, ready_seconds: int = 120, wsgi: str = "main:app", **extra_env):
    Path(tmp_path).mkdir(parents=True, exist_ok=True)
    env = hosted_environment(database_url, tmp_path, **extra_env)
    if env["SGAA_ADMISSION"] == "open" and "SGAA_OPENING_REFERENCE" not in extra_env:
        env["SGAA_OPENING_REFERENCE"] = authorize_opening(database_url)
    port = _free_port()
    child = subprocess.Popen(
        [sys.executable, "-c", _SERVER, str(port), wsgi], cwd=REPO_ROOT, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
    )
    try:
        deadline = time.time() + ready_seconds
        while time.time() < deadline:
            if child.stdout.readline().strip() == "READY":
                break
            if child.poll() is not None:
                raise AssertionError("the application did not start")
        else:
            raise AssertionError("the application did not become ready")
        yield SimpleNamespace(url=f"http://127.0.0.1:{port}", database=database_url,
                              opening_reference=env.get("SGAA_OPENING_REFERENCE"))
    finally:
        child.kill()
        child.wait(timeout=30)


_RETURNED_REQUEST = (
    "UPDATE requisicoes SET status = 'Devolvida', data_processamento = '2020-01-01 00:00:00' WHERE id = 2"
)


def seed_admin_and_requests(conn) -> None:
    """The real administrator, plus a student with one pending and one returned (long overdue) request.

    The returned request is the trap: its deadline has passed, so an administrator's dashboard view
    would derive an automatic rejection.  The smoke must never open that view.
    """
    from tests.mp2_pg_support import seed_admin
    from tests.storage_mp1_support import SEED_SQL

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


__all__ = ["REPO_ROOT", "authorize_opening", "hosted_environment", "seed_admin_and_requests", "served_app"]
