"""REF-0C-B2 diagnostic RBAC requirements, actor matrix, and denial contracts.

All state is fixture-controlled. Shadow-read fixtures use only ``tmp_path`` logs;
the repository database and production logs are never opened by these tests.
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest


BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main
from app.versioning import shadow_reads as versioning_shadow_reads
from tests.versioned_test_support import isolated_versioned_app_env


R22 = "admin_diagnostico_atividades_versionadas"
R23 = "admin_diagnostico_atividades_versionadas_view"
R24 = "admin_diagnostico_versioned_shadow_reads"
R22_PATH = "/admin/diagnostico/atividades-versionadas"
R23_PATH = "/admin/diagnostico/atividades-versionadas/view"
R24_PATH = "/admin/diagnostico/versioned-shadow-reads"


@pytest.fixture()
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "ref0cb2_diagnostic_rbac.db") as value:
        yield value


def _make_admin(access_level: str) -> int:
    with main.app.app_context():
        conn = main.get_db_connection()
        user_id = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) "
            "VALUES (?, ?, ?, ?, ?) RETURNING id",
            (
                f"B2 {access_level}",
                f"b2.{access_level}.{uuid.uuid4().hex[:10]}@example.com",
                main.hash_password("rbac-test-pass"),
                "admin",
                access_level,
            ),
        ).fetchone()["id"]
        conn.commit()
    return int(user_id)


def _login_admin(client, access_level: str) -> None:
    user_id = _make_admin(access_level)
    with client.session_transaction() as session:
        session.clear()
        session["user_id"] = user_id
        session["user_type"] = "admin"
        session["user_name"] = f"B2 {access_level}"


def _login_aluno(client) -> None:
    with client.session_transaction() as session:
        session.clear()
        session["user_id"] = 999999
        session["user_type"] = "aluno"
        session["user_name"] = "B2 aluno"


def _logout(client) -> None:
    with client.session_transaction() as session:
        session.clear()


def _is_dashboard_denial(response) -> bool:
    return response.status_code == 302 and response.headers.get("Location", "").endswith(
        "/admin/dashboard"
    )


def _is_login_denial(response) -> bool:
    return response.status_code == 302 and "/login" in response.headers.get("Location", "")


def _domain_state() -> dict[str, int]:
    tables = (
        "atividades",
        "atividade_base",
        "atividade_versao",
        "atividade_legacy_map",
        "matrizes_atividades",
        "matrizes_atividades_itens",
        "matriz_atividade_versao_item",
        "matriz_norma",
        "turmas",
        "requisicoes",
    )
    with main.app.app_context():
        conn = main.get_db_connection()
        return {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in tables
        }


def _configure_temporary_shadow_log(monkeypatch, tmp_path: Path) -> Path:
    log_path = tmp_path / "controlled-logs" / "versioned_shadow_reads.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        "2026-05-24 14:00:00 - main - ERROR - "
        "event=versioned_resolver_shadow_read origin=admin_create req_id=700 "
        "aluno_id=200 atividade_id_legacy=8 status=error atividade_versao_id=null "
        "codigo_normativo=AAC-rev6 eixo=AAC warnings=[] reason=boom "
        "exception_type=RuntimeError exception_message=controlled_traceback\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(versioning_shadow_reads, "_versioned_shadow_read_dedicated_log_path", lambda: str(log_path))
    monkeypatch.setattr(versioning_shadow_reads, "_collect_versioned_shadow_read_log_paths", lambda: [str(log_path)])
    return log_path


def test_approved_requirement_mapping_and_no_fallback_policy():
    assert main.get_admin_permission_requirement(R22, "GET") == ("atividades", "view")
    assert main.get_admin_permission_requirement(R23, "GET") == ("atividades", "view")
    assert main.get_admin_permission_requirement(R24, "GET") == ("banco_dados", "view")
    assert main.get_admin_permission_requirement(R22, "GET") == main.get_admin_permission_requirement(R23, "GET")
    assert main.get_admin_permission_requirement(R22, "POST") is None
    assert main.get_admin_permission_requirement(R24, "POST") is None
    assert main.get_admin_permission_requirement("admin_unrelated_diagnostic", "GET") is None
    assert main.get_admin_permission_requirement("unrelated_endpoint", "GET") is None


@pytest.mark.parametrize("path", [R22_PATH, R23_PATH])
@pytest.mark.parametrize("access_level", ["admin_total", "administrativo", "consultivo"])
def test_r22_r23_allow_all_approved_admin_roles(env, path, access_level):
    client = env["client"]
    _login_admin(client, access_level)
    response = client.get(path)
    assert response.status_code == 200


@pytest.mark.parametrize("path", [R22_PATH, R23_PATH, R24_PATH])
def test_aluno_and_anonymous_keep_outer_authentication_contract(env, path):
    client = env["client"]
    _login_aluno(client)
    assert _is_login_denial(client.get(path))
    _logout(client)
    assert _is_login_denial(client.get(path))


@pytest.mark.parametrize("access_level", ["administrativo", "consultivo"])
def test_r24_denied_admin_roles_follow_browser_contract(env, monkeypatch, tmp_path, access_level):
    client = env["client"]
    log_path = _configure_temporary_shadow_log(monkeypatch, tmp_path)
    before_state = _domain_state()
    before_content = log_path.read_text(encoding="utf-8")
    before_mtime = log_path.stat().st_mtime_ns
    _login_admin(client, access_level)

    response = client.get(R24_PATH)

    assert _is_dashboard_denial(response)
    assert _domain_state() == before_state
    assert log_path.read_text(encoding="utf-8") == before_content
    assert log_path.stat().st_mtime_ns == before_mtime


@pytest.mark.parametrize("access_level", ["administrativo", "consultivo"])
def test_r24_ajax_denial_is_json_403_without_sensitive_payload(env, monkeypatch, tmp_path, access_level):
    client = env["client"]
    log_path = _configure_temporary_shadow_log(monkeypatch, tmp_path)
    _login_admin(client, access_level)

    response = client.get(R24_PATH, headers={"X-Requested-With": "XMLHttpRequest"})

    assert response.status_code == 403
    assert response.get_json() == {
        "ok": False,
        "error": "forbidden",
        "resource": "banco_dados",
        "required_scope": "view",
        "message": response.get_json()["message"],
    }
    body = response.get_data(as_text=True)
    for forbidden in (str(log_path), "aluno_id", "req_id", "controlled_traceback", "events"):
        assert forbidden not in body


def test_r24_admin_total_gets_controlled_sensitive_output_and_preserves_log(env, monkeypatch, tmp_path):
    client = env["client"]
    log_path = _configure_temporary_shadow_log(monkeypatch, tmp_path)
    before_content = log_path.read_text(encoding="utf-8")
    before_mtime = log_path.stat().st_mtime_ns
    _login_admin(client, "admin_total")

    response = client.get(f"{R24_PATH}?limit=9999")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["limit"] == 500
    assert payload["dedicated_log_path"] == str(log_path)
    assert payload["log_paths"] == [str(log_path)]
    assert payload["events"][0]["aluno_id"] == 200
    assert payload["events"][0]["req_id"] == 700
    assert log_path.read_text(encoding="utf-8") == before_content
    assert log_path.stat().st_mtime_ns == before_mtime


@pytest.mark.parametrize(
    "path,access_level",
    [(R22_PATH, "aluno"), (R23_PATH, "aluno"), (R24_PATH, "administrativo")],
)
def test_denied_diagnostics_do_not_mutate_fixture_domain_state(env, monkeypatch, tmp_path, path, access_level):
    client = env["client"]
    _configure_temporary_shadow_log(monkeypatch, tmp_path)
    before_state = _domain_state()
    if access_level == "aluno":
        _login_aluno(client)
        response = client.get(path)
        assert _is_login_denial(response)
    else:
        _login_admin(client, access_level)
        response = client.get(path)
        assert _is_dashboard_denial(response)
    assert _domain_state() == before_state
