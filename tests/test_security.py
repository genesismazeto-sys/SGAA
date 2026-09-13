"""Testes mínimos de segurança / produção.

Esses testes blindam regressões em pontos críticos:
  * SECRET_KEY não pode ser o valor público histórico.
  * `app.debug` deve estar desligado quando a app é importada normalmente.
  * /uploads/<path> não pode servir arquivos para visitantes anônimos.
  * /admin/api/presets deve exigir admin.
  * /health não pode vazar detalhes de exceção.
"""
import json
import os
import sqlite3
import sys
from contextlib import contextmanager

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main  # noqa: E402
import presets_api  # noqa: E402
from app import db as app_db  # noqa: E402
from app.prod1_schema import validate_prod1_schema  # noqa: E402


# Captured at import time (collection), before any test can rebind the runtime
# database: this is the shared pytest session database created by conftest.
SESSION_DATABASE = os.environ["APP_DATABASE"]


@pytest.fixture(scope="module")
def client():
    app = main.app
    with app.app_context():
        main.init_db()
        try:
            main.close_db_connection(None)
        except Exception:
            pass

    with app.test_client() as test_client:
        yield test_client

    with app.app_context():
        try:
            main.close_db_connection(None)
        except Exception:
            pass


def _login_admin(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["user_type"] = "admin"
        sess["user_name"] = "Administrador"


def test_secret_key_is_not_public_default():
    forbidden = {
        "ej_atividades_complementares_2025",
        "change-me",
        "secret",
        "test",
    }
    assert main.app.secret_key not in forbidden
    assert isinstance(main.app.secret_key, str)
    assert len(main.app.secret_key) >= 24


def test_app_debug_is_disabled():
    assert main.app.debug is False


def test_health_does_not_leak_details(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.get_json() or {}
    assert "detail" not in body


def test_uploads_require_authentication(client):
    # Arquivo inexistente ainda deve ser bloqueado por falta de sessão.
    r = client.get("/uploads/qualquer/coisa.pdf", follow_redirects=False)
    assert r.status_code in (302, 303), r.status_code
    assert "/login" in (r.headers.get("Location") or "")


def test_uploads_blocks_path_traversal(client):
    r = client.get("/uploads/..%2F..%2Fmain.py", follow_redirects=False)
    # 302 (sem sessão) ou 403 (com sessão) — nunca 200
    assert r.status_code != 200


def test_presets_api_requires_admin(client):
    r = client.get("/admin/api/presets")
    assert r.status_code == 403
    body = r.get_json() or {}
    assert body.get("error") == "forbidden"


def test_presets_post_rejects_invalid_payload_when_unauth(client):
    r = client.post("/admin/api/presets", json={"foo": "bar"})
    assert r.status_code == 403


def test_presets_post_persists_object_payload_for_responses_and_emails(client):
    _login_admin(client)

    payload = {
        "respostas": [
            {"id": 1, "titulo": "Justificativa revisada", "texto": "Conteudo persistido"},
        ],
        "emails": [
            {"id": 7, "titulo": "Resposta por email", "texto": "Corpo do email persistido"},
        ],
    }

    r = client.post("/admin/api/presets", json=payload)
    assert r.status_code == 200
    assert r.get_json() == {"ok": True}

    conn = sqlite3.connect(main.DATABASE)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            f"SELECT tipo, preset_id, titulo, texto FROM {presets_api.PRESETS_TABLE} ORDER BY tipo, preset_id"
        ).fetchall()
    finally:
        conn.close()

    assert [dict(row) for row in rows] == [
        {"tipo": "emails", "preset_id": 7, "titulo": "Resposta por email", "texto": "Corpo do email persistido"},
        {"tipo": "respostas", "preset_id": 1, "titulo": "Justificativa revisada", "texto": "Conteudo persistido"},
    ]

    loaded = client.get("/admin/api/presets")
    assert loaded.status_code == 200
    assert loaded.get_json() == payload


LEGACY_PRESETS_PAYLOAD = {
    "respostas": [
        {"id": 3, "titulo": "Legado justificativa", "texto": "Texto legado"},
    ],
    "emails": [
        {"id": 9, "titulo": "Legado email", "texto": "Email legado"},
    ],
}


@contextmanager
def _isolated_presets_app(tmp_path, monkeypatch):
    """Bind the runtime database to a private prod-1 database under `tmp_path`.

    `configuracoes_presets` is a prod-1 physical-contract table.  The legacy
    migration scenario drops it so that `presets_api.ensure_presets_schema`
    re-creates it, and that DDL text is not byte-identical to the canonical
    `PROD1_SCHEMA_SQL` one.  Running that against the shared pytest session
    database would leave its physical schema signature permanently outside the
    prod-1 contract, so every later test reaching `validate_prod1_schema`
    (e.g. any request through `ensure_turmas_matriz_schema`) would fail.  The
    scenario therefore owns its own database; `monkeypatch` guarantees every
    rebinding is restored even if the body raises.
    """
    isolated_database = tmp_path / "presets_isolated.db"
    monkeypatch.setenv("APP_DATABASE", str(isolated_database))
    monkeypatch.setattr(main, "DATABASE", str(isolated_database))
    monkeypatch.setattr(app_db, "DATABASE", str(isolated_database))
    monkeypatch.setitem(main.app.config, "DATABASE_PATH", str(isolated_database))

    # Own the application context explicitly.  Flask reuses the top application
    # context for a test request, so a context preserved by another test client
    # would otherwise hand this scenario a `g.db` bound to a different database.
    with main.app.app_context():
        try:
            main.init_db()
            main.close_db_connection(None)
            yield main.app.test_client(), isolated_database
        finally:
            main.close_db_connection(None)


def _run_legacy_presets_migration(tmp_path, monkeypatch):
    """Drive GET /admin/api/presets with no presets table on a private database."""
    presets_path = tmp_path / "presets_data.json"
    presets_path.write_text(
        json.dumps(LEGACY_PRESETS_PAYLOAD, ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setattr(presets_api, "PRESETS_PATH", str(presets_path))

    with _isolated_presets_app(tmp_path, monkeypatch) as (client, database_path):
        conn = sqlite3.connect(database_path)
        try:
            conn.execute(f"DROP TABLE IF EXISTS {presets_api.PRESETS_TABLE}")
            conn.commit()
        finally:
            conn.close()

        _login_admin(client)
        response = client.get("/admin/api/presets")

        conn = sqlite3.connect(database_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = [
                dict(row)
                for row in conn.execute(
                    f"SELECT tipo, preset_id, titulo, texto FROM {presets_api.PRESETS_TABLE} ORDER BY tipo, preset_id"
                )
            ]
        finally:
            conn.close()

    return response, rows


def test_presets_get_migrates_legacy_json_to_database(tmp_path, monkeypatch):
    response, rows = _run_legacy_presets_migration(tmp_path, monkeypatch)

    assert response.status_code == 200
    assert response.get_json() == LEGACY_PRESETS_PAYLOAD
    assert rows == [
        {"tipo": "emails", "preset_id": 9, "titulo": "Legado email", "texto": "Email legado"},
        {"tipo": "respostas", "preset_id": 3, "titulo": "Legado justificativa", "texto": "Texto legado"},
    ]


def test_legacy_presets_migration_leaves_session_database_prod1_clean(tmp_path, monkeypatch):
    """The presets legacy migration must not leak prod-1 schema drift.

    Historical defect: this scenario dropped `configuracoes_presets` on the
    shared pytest session database and let the request re-create it, which made
    every later `validate_prod1_schema` consumer raise
    `prod-1 physical schema contract mismatch`.  The guard is order-independent
    -- it runs the scenario itself and then re-validates the session database.
    """
    _run_legacy_presets_migration(tmp_path, monkeypatch)

    conn = sqlite3.connect(SESSION_DATABASE)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        validate_prod1_schema(conn)
    finally:
        conn.close()


def test_security_headers_present(client):
    r = client.get("/login")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert "Content-Security-Policy" in r.headers
    assert r.headers.get("Referrer-Policy")
    assert "Permissions-Policy" in r.headers


def test_session_cookie_settings():
    cfg = main.app.config
    assert cfg.get("SESSION_COOKIE_HTTPONLY") is True
    # SameSite deve estar definido (Lax ou Strict)
    assert cfg.get("SESSION_COOKIE_SAMESITE") in ("Lax", "Strict")


def test_password_hash_is_pbkdf2():
    h = main.hash_password("alguma-senha-forte")
    assert h.startswith("pbkdf2:") or h.startswith("scrypt:") or h.startswith("argon2")
    assert main.check_password(h, "alguma-senha-forte") is True
    assert main.check_password(h, "errada") is False


def test_legacy_password_hash_still_verifies():
    # Gera um hash no formato antigo para garantir compatibilidade.
    import base64
    import hashlib
    import secrets as _sec

    salt = _sec.token_bytes(16)
    digest = hashlib.sha256(salt + b"legado-ok").digest()
    legacy = base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()
    assert main.is_legacy_password_hash(legacy) is True
    assert main.check_password(legacy, "legado-ok") is True
    assert main.check_password(legacy, "outra") is False
