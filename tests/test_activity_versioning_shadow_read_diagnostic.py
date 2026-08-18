from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import pytest

import main
from app.versioning import shadow_reads
from tests.versioned_test_support import isolated_versioned_app_env


@pytest.fixture()
def diagnostic_env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "historical_shadow_diagnostic.db") as env:
        yield env


def _login_admin(client) -> None:
    with main.app.app_context():
        conn = main.get_db_connection()
        user_id = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) "
            "VALUES (?, ?, ?, 'admin', 'admin_total') RETURNING id",
            (
                "FC13 diagnostic admin",
                f"fc13.{uuid.uuid4().hex[:10]}@example.com",
                main.hash_password("fc13-test-pass"),
            ),
        ).fetchone()["id"]
        conn.commit()
    with client.session_transaction() as session:
        session.clear()
        session["user_id"] = int(user_id)
        session["user_type"] = "admin"
        session["user_name"] = "FC13 diagnostic admin"


def _configure_log(monkeypatch, path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    monkeypatch.setattr(
        shadow_reads,
        "_versioned_shadow_read_dedicated_log_path",
        lambda: str(path),
    )
    monkeypatch.setattr(
        shadow_reads,
        "_collect_versioned_shadow_read_log_paths",
        lambda: [str(path)],
    )


def test_historical_shadow_diagnostic_endpoint_requires_admin(diagnostic_env):
    response = diagnostic_env["client"].get(
        "/admin/diagnostico/versioned-shadow-reads",
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_historical_shadow_diagnostic_reads_filters_and_deduplicates(
    diagnostic_env, monkeypatch, tmp_path
):
    client = diagnostic_env["client"]
    _login_admin(client)
    log_path = tmp_path / "logs" / "versioned_shadow_reads.log"
    resolved = (
        "event=versioned_resolver_shadow_read origin=aluno_create req_id=100 "
        "aluno_id=900 atividade_id_legacy=1 status=resolved "
        "atividade_versao_id=11 codigo_normativo=AAC-rev6 eixo=AAC "
        "warnings=[] reason=ok"
    )
    _configure_log(
        monkeypatch,
        log_path,
        [
            resolved,
            "event=versioned_resolver_shadow_read malformed_line",
            "event=versioned_resolver_shadow_read origin=admin_create req_id=101 "
            "aluno_id=901 atividade_id_legacy=27 status=error "
            "atividade_versao_id=null codigo_normativo=AEU-rev1 eixo=AEU "
            "warnings=[\"legacy_activity_outside_matrix_scope\"] reason=outside_scope",
            resolved,
        ],
    )

    payload = client.get("/admin/diagnostico/versioned-shadow-reads").get_json()
    assert payload["source_mode"] == "dedicated"
    assert payload["raw_count"] == 3
    assert payload["deduplicated_count"] == 1
    assert payload["count"] == 2
    assert "shadow_read_enabled" not in payload
    assert "shadow_read_env_raw" not in payload

    filtered = client.get(
        "/admin/diagnostico/versioned-shadow-reads?origin=admin_create&has_warnings=1"
    ).get_json()
    assert filtered["count"] == 1
    assert filtered["events"][0]["atividade_id_legacy"] == 27


def test_historical_shadow_diagnostic_is_read_only(
    diagnostic_env, monkeypatch, tmp_path
):
    client = diagnostic_env["client"]
    db_path = diagnostic_env["db_path"]
    _login_admin(client)
    log_path = tmp_path / "logs" / "versioned_shadow_reads.log"
    _configure_log(
        monkeypatch,
        log_path,
        [
            "event=versioned_resolver_shadow_read origin=admin_create req_id=700 "
            "aluno_id=200 atividade_id_legacy=8 status=error "
            "atividade_versao_id=null codigo_normativo=AAC-rev6 eixo=AAC "
            "warnings=[] reason=historical"
        ],
    )
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()

    response = client.get("/admin/diagnostico/versioned-shadow-reads")

    assert response.status_code == 200
    assert response.get_json()["count"] == 1
    assert hashlib.sha256(db_path.read_bytes()).hexdigest() == before
