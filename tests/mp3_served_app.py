# coding: utf-8
"""TEST ONLY: ``main:app`` served over HTTP by a fresh interpreter in hosted production mode.

The entrypoint a WSGI host loads, with a platform-shaped environment and no test-suite
variables (CSRF on, production settings), on 127.0.0.1.  ``extra_env`` overrides any
variable (the admission mode, the operator credential).  Shared by the MP-3 real-application
lanes; never imported by the application.
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

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVED_SECRET_KEY = "p" + "3" * 47
# An open production deployment names the reference it was lifted with; the lanes that do not test the
# opening itself use this one.
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
    env.update({key: str(value) for key, value in extra_env.items()})
    return env


@contextmanager
def served_app(database_url: str, tmp_path, *, ready_seconds: int = 120, wsgi: str = "main:app", **extra_env):
    Path(tmp_path).mkdir(parents=True, exist_ok=True)
    env = hosted_environment(database_url, tmp_path, **extra_env)
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
        yield SimpleNamespace(url=f"http://127.0.0.1:{port}", database=database_url)
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


__all__ = ["REPO_ROOT", "hosted_environment", "seed_admin_and_requests", "served_app"]
