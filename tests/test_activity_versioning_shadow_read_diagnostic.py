import hashlib
import os
import sqlite3
import sys
import uuid
from pathlib import Path

import pytest


BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main
from app import db as app_db_module
from tests.versioned_test_support import isolated_versioned_app_env


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


@pytest.fixture()
def shadow_diagnostic_env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "shadow_diagnostic.db") as env:
        yield {"client": env["client"], "db_path": env["db_path"]}


def _set_admin_session(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["user_type"] = "admin"
        sess["user_name"] = "Administrador"


def _set_aluno_session(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["user_type"] = "aluno"
        sess["user_name"] = "Aluno"


def _write_log(path: Path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(lines) + "\n"
    path.write_text(content, encoding="utf-8")


def _shadow_row(conn):
    return conn.execute(
        """
        SELECT COUNT(*) AS total,
               COALESCE(SUM(CASE WHEN atividade_versao_id IS NOT NULL THEN 1 ELSE 0 END), 0) AS versao_set,
               COALESCE(SUM(CASE WHEN regra_snapshot_json IS NOT NULL THEN 1 ELSE 0 END), 0) AS regra_set,
               COALESCE(SUM(CASE WHEN codigo_normativo_snapshot IS NOT NULL THEN 1 ELSE 0 END), 0) AS codigo_set
          FROM requisicoes
        """
    ).fetchone()


def _pick_admin_create_scope(conn):
    aluno = conn.execute(
        """
        SELECT id
          FROM alunos
      ORDER BY id
         LIMIT 1
        """
    ).fetchone()
    assert aluno is not None
    aluno_id = int(aluno["id"])
    scope = main._get_admin_requisicao_scope_for_aluno(conn, aluno_id)
    assert scope is not None

    allowed_ids = scope["allowed_activity_ids"]
    if allowed_ids:
        return aluno_id, int(allowed_ids[0])

    atividade = conn.execute(
        """
        SELECT id
          FROM atividades
      ORDER BY id
         LIMIT 1
        """
    ).fetchone()
    assert atividade is not None
    return aluno_id, int(atividade["id"])


def test_shadow_diagnostic_endpoint_requires_admin(shadow_diagnostic_env):
    client = shadow_diagnostic_env["client"]
    response = client.get("/admin/diagnostico/versioned-shadow-reads", follow_redirects=False)
    assert response.status_code in (301, 302, 303)
    assert "/login" in (response.headers.get("Location") or "")


def test_shadow_diagnostic_endpoint_is_not_in_main_menu(shadow_diagnostic_env):
    client = shadow_diagnostic_env["client"]
    _set_admin_session(client)
    response = client.get("/admin/dashboard")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "/admin/diagnostico/versioned-shadow-reads" not in html


def test_shadow_diagnostic_without_log_returns_empty_payload(shadow_diagnostic_env, monkeypatch, tmp_path):
    client = shadow_diagnostic_env["client"]
    _set_admin_session(client)
    missing_log = tmp_path / "missing" / "versioned_shadow_reads.log"
    monkeypatch.setattr(
        main,
        "_versioned_shadow_read_dedicated_log_path",
        lambda: str(missing_log),
    )
    monkeypatch.setattr(main, "_collect_versioned_shadow_read_log_paths", lambda: [str(missing_log)])

    response = client.get("/admin/diagnostico/versioned-shadow-reads")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["diagnostico"] == "versioned_shadow_reads"
    assert payload["source"] == "log"
    assert payload["count"] == 0
    assert payload["raw_count"] == 0
    assert payload["deduplicated_count"] == 0
    assert payload["source_mode"] == "fallback_app_log"
    assert payload["limit"] == 100
    assert payload["events"] == []
    assert payload["log_not_found"] is True
    assert "shadow_read_enabled" in payload
    assert "shadow_read_env_raw" in payload
    assert payload["dedicated_log_path"] == str(missing_log)
    assert payload["dedicated_log_exists"] is False
    assert payload["dedicated_log_in_paths"] is True
    assert "log_paths" in payload
    assert "logger_level" in payload
    assert "handler_count" in payload


def test_shadow_diagnostic_parser_filters_and_limit(shadow_diagnostic_env, monkeypatch, tmp_path):
    client = shadow_diagnostic_env["client"]
    _set_admin_session(client)
    monkeypatch.setenv("SGAA_VERSIONED_RESOLVER_SHADOW_READ", "1")

    log_path = tmp_path / "logs" / "versioned_shadow_reads.log"
    _write_log(
        log_path,
        [
            "2026-05-24 10:00:01 - main - INFO - event=versioned_resolver_shadow_read origin=aluno_create req_id=100 aluno_id=900 atividade_id_legacy=1 status=resolved atividade_versao_id=11 codigo_normativo=AAC-rev6 eixo=AAC warnings=[] reason=ok",
            "2026-05-24 10:00:02 - main - INFO - event=versioned_resolver_shadow_read malformed_line",
            "2026-05-24 10:00:03 - main - INFO - event=versioned_resolver_shadow_read origin=admin_create req_id=101 aluno_id=901 atividade_id_legacy=27 status=legacy_activity_not_in_matrix atividade_versao_id=null codigo_normativo=AEU-rev1 eixo=AEU warnings=[\"legacy_activity_outside_matrix_scope\"] reason=outside_scope",
            "2026-05-24 10:00:04 - main - INFO - event=versioned_resolver_shadow_read origin=aluno_create req_id=102 aluno_id=901 atividade_id_legacy=8 status=base_without_version_for_matrix atividade_versao_id=null codigo_normativo=AAC-rev6 eixo=AAC warnings=[] reason=no_version",
            "2026-05-24 10:00:05 - main - INFO - event=versioned_resolver_shadow_read origin=aluno_create req_id=100 aluno_id=900 atividade_id_legacy=1 status=resolved atividade_versao_id=11 codigo_normativo=AAC-rev6 eixo=AAC warnings=[] reason=ok",
        ],
    )
    monkeypatch.setattr(
        main,
        "_versioned_shadow_read_dedicated_log_path",
        lambda: str(log_path),
    )
    monkeypatch.setattr(main, "_collect_versioned_shadow_read_log_paths", lambda: [str(log_path)])

    response = client.get("/admin/diagnostico/versioned-shadow-reads")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["count"] == 3
    assert payload["raw_count"] == 4
    assert payload["deduplicated_count"] == 1
    assert payload["source_mode"] == "dedicated"
    assert payload["shadow_read_enabled"] is True
    assert payload["shadow_read_env_raw"] == "1"
    assert payload["dedicated_log_path"] == str(log_path)
    assert payload["dedicated_log_exists"] is True
    assert payload["dedicated_log_in_paths"] is True
    assert payload["log_paths"] == [str(log_path)]
    assert payload["logger_level"] == "INFO"
    assert payload["handler_count"] >= 1
    events = payload["events"]
    assert [event["status"] for event in events] == [
        "resolved",
        "base_without_version_for_matrix",
        "legacy_activity_not_in_matrix",
    ]
    assert events[2]["warnings"] == ["legacy_activity_outside_matrix_scope"]
    assert events[2]["has_warnings"] is True

    by_origin = client.get("/admin/diagnostico/versioned-shadow-reads?origin=admin_create").get_json()
    assert by_origin["count"] == 1
    assert by_origin["events"][0]["origin"] == "admin_create"

    by_status = client.get("/admin/diagnostico/versioned-shadow-reads?status=resolved").get_json()
    assert by_status["count"] == 1
    assert by_status["events"][0]["status"] == "resolved"

    by_aluno = client.get("/admin/diagnostico/versioned-shadow-reads?aluno_id=901").get_json()
    assert by_aluno["count"] == 2
    assert all(event["aluno_id"] == 901 for event in by_aluno["events"])

    by_legacy = client.get("/admin/diagnostico/versioned-shadow-reads?atividade_id_legacy=27").get_json()
    assert by_legacy["count"] == 1
    assert by_legacy["events"][0]["atividade_id_legacy"] == 27

    by_norma = client.get("/admin/diagnostico/versioned-shadow-reads?codigo_normativo=AEU-rev1").get_json()
    assert by_norma["count"] == 1
    assert by_norma["events"][0]["codigo_normativo"] == "AEU-rev1"

    by_eixo = client.get("/admin/diagnostico/versioned-shadow-reads?eixo=AEU").get_json()
    assert by_eixo["count"] == 1
    assert by_eixo["events"][0]["eixo"] == "AEU"

    with_warnings = client.get("/admin/diagnostico/versioned-shadow-reads?has_warnings=1").get_json()
    assert with_warnings["count"] == 1
    assert with_warnings["events"][0]["has_warnings"] is True

    without_warnings = client.get("/admin/diagnostico/versioned-shadow-reads?has_warnings=0").get_json()
    assert without_warnings["count"] == 2
    assert all(event["has_warnings"] is False for event in without_warnings["events"])

    single = client.get("/admin/diagnostico/versioned-shadow-reads?limit=1").get_json()
    assert single["limit"] == 1
    assert single["count"] == 1

    bulk_lines = [
        (
            f"2026-05-24 11:00:{index % 60:02d} - main - INFO - "
            "event=versioned_resolver_shadow_read "
            f"origin=aluno_create req_id={index} aluno_id={index} atividade_id_legacy=1 "
            "status=resolved atividade_versao_id=11 codigo_normativo=AAC-rev6 eixo=AAC "
            "warnings=[] reason=ok"
        )
        for index in range(620)
    ]
    _write_log(log_path, bulk_lines)
    capped = client.get("/admin/diagnostico/versioned-shadow-reads?limit=999").get_json()
    assert capped["limit"] == 500
    assert capped["count"] == 500


def test_shadow_diagnostic_read_only_and_flag_default_off(shadow_diagnostic_env, monkeypatch, tmp_path):
    client = shadow_diagnostic_env["client"]
    db_path: Path = shadow_diagnostic_env["db_path"]
    _set_admin_session(client)
    _set_aluno_session(client)
    _set_admin_session(client)

    log_path = tmp_path / "logs" / "versioned_shadow_reads.log"
    _write_log(
        log_path,
        [
            "2026-05-24 12:00:00 - main - INFO - event=versioned_resolver_shadow_read origin=aluno_create req_id=500 aluno_id=200 atividade_id_legacy=8 status=resolved atividade_versao_id=12 codigo_normativo=AAC-rev6 eixo=AAC warnings=[] reason=ok"
        ],
    )
    monkeypatch.setattr(
        main,
        "_versioned_shadow_read_dedicated_log_path",
        lambda: str(log_path),
    )
    monkeypatch.setattr(main, "_collect_versioned_shadow_read_log_paths", lambda: [str(log_path)])
    monkeypatch.delenv("SGAA_VERSIONED_RESOLVER_SHADOW_READ", raising=False)
    assert main.is_versioned_resolver_shadow_read_enabled() is False

    before_hash = _sha256_file(db_path)
    with main.app.app_context():
        conn = main.get_db_connection()
        before = _shadow_row(conn)

    response = client.get("/admin/diagnostico/versioned-shadow-reads")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["count"] == 1
    assert payload["raw_count"] == 1
    assert payload["deduplicated_count"] == 0
    assert payload["source_mode"] == "dedicated"
    assert payload["events"][0]["status"] == "resolved"
    assert payload["shadow_read_enabled"] is False
    assert payload["shadow_read_env_raw"] is None
    assert payload["dedicated_log_path"] == str(log_path)
    assert payload["dedicated_log_exists"] is True
    assert payload["dedicated_log_in_paths"] is True
    assert payload["log_paths"] == [str(log_path)]
    assert payload["logger_level"] == "INFO"
    assert payload["handler_count"] >= 1

    with main.app.app_context():
        conn = main.get_db_connection()
        after = _shadow_row(conn)
    after_hash = _sha256_file(db_path)

    assert before["total"] == after["total"]
    assert before["versao_set"] == after["versao_set"]
    assert before["regra_set"] == after["regra_set"]
    assert before["codigo_set"] == after["codigo_set"]
    assert before_hash == after_hash


def test_shadow_diagnostic_prefers_dedicated_log_over_fallback_sources(
    shadow_diagnostic_env, monkeypatch, tmp_path
):
    client = shadow_diagnostic_env["client"]
    _set_admin_session(client)

    dedicated_log = tmp_path / "logs" / "versioned_shadow_reads.log"
    app_log_1 = tmp_path / "logs" / "app.log.1"
    app_log = tmp_path / "logs" / "app.log"
    _write_log(
        dedicated_log,
        [
            "2026-05-24 13:00:00 - main - INFO - event=versioned_resolver_shadow_read origin=admin_create req_id=700 aluno_id=100 atividade_id_legacy=1 status=resolved atividade_versao_id=11 codigo_normativo=AAC-rev6 eixo=AAC warnings=[] reason=ok",
            "2026-05-24 13:00:01 - main - INFO - event=versioned_resolver_shadow_read origin=admin_create req_id=700 aluno_id=100 atividade_id_legacy=1 status=resolved atividade_versao_id=11 codigo_normativo=AAC-rev6 eixo=AAC warnings=[] reason=ok",
        ],
    )
    _write_log(
        app_log_1,
        [
            "2026-05-24 12:59:59 - main - INFO - event=versioned_resolver_shadow_read origin=admin_create req_id=699 aluno_id=100 atividade_id_legacy=2 status=error atividade_versao_id=null codigo_normativo=null eixo=null warnings=[] reason=resolver_exception"
        ],
    )
    _write_log(
        app_log,
        [
            "2026-05-24 13:00:02 - main - INFO - event=versioned_resolver_shadow_read origin=admin_create req_id=701 aluno_id=100 atividade_id_legacy=3 status=legacy_activity_not_in_matrix atividade_versao_id=null codigo_normativo=AAC-rev6 eixo=AAC warnings=[] reason=outside_scope"
        ],
    )

    monkeypatch.setattr(
        main,
        "_versioned_shadow_read_dedicated_log_path",
        lambda: str(dedicated_log),
    )
    monkeypatch.setattr(
        main,
        "_collect_versioned_shadow_read_log_paths",
        lambda: [str(dedicated_log), str(app_log_1), str(app_log)],
    )

    response = client.get("/admin/diagnostico/versioned-shadow-reads")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["source_mode"] == "dedicated"
    assert payload["log_paths"] == [str(dedicated_log)]
    assert payload["raw_count"] == 2
    assert payload["deduplicated_count"] == 1
    assert payload["count"] == 1
    assert payload["events"][0]["status"] == "resolved"


def test_shadow_diagnostic_fallback_reads_app_logs_when_dedicated_is_missing(
    shadow_diagnostic_env, monkeypatch, tmp_path
):
    client = shadow_diagnostic_env["client"]
    _set_admin_session(client)

    dedicated_missing = tmp_path / "logs" / "versioned_shadow_reads.log"
    app_log_1 = tmp_path / "logs" / "app.log.1"
    app_log = tmp_path / "logs" / "app.log"
    _write_log(
        app_log_1,
        [
            "2026-05-24 14:00:00 - main - INFO - event=versioned_resolver_shadow_read origin=aluno_create req_id=800 aluno_id=200 atividade_id_legacy=8 status=resolved atividade_versao_id=12 codigo_normativo=AAC-rev6 eixo=AAC warnings=[] reason=ok"
        ],
    )
    _write_log(
        app_log,
        [
            "2026-05-24 14:00:01 - main - INFO - event=versioned_resolver_shadow_read origin=aluno_create req_id=800 aluno_id=200 atividade_id_legacy=8 status=resolved atividade_versao_id=12 codigo_normativo=AAC-rev6 eixo=AAC warnings=[] reason=ok",
            "2026-05-24 14:00:02 - main - INFO - event=versioned_resolver_shadow_read origin=admin_create req_id=801 aluno_id=201 atividade_id_legacy=27 status=legacy_activity_not_in_matrix atividade_versao_id=null codigo_normativo=AEU-rev1 eixo=AEU warnings=[] reason=outside_scope",
        ],
    )

    monkeypatch.setattr(
        main,
        "_versioned_shadow_read_dedicated_log_path",
        lambda: str(dedicated_missing),
    )
    monkeypatch.setattr(
        main,
        "_collect_versioned_shadow_read_log_paths",
        lambda: [str(dedicated_missing), str(app_log_1), str(app_log)],
    )

    response = client.get("/admin/diagnostico/versioned-shadow-reads")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["source_mode"] == "fallback_app_log"
    assert payload["dedicated_log_exists"] is False
    assert payload["log_paths"] == [str(app_log_1), str(app_log)]
    assert payload["raw_count"] == 3
    assert payload["deduplicated_count"] == 1
    assert payload["count"] == 2
    assert payload["events"][0]["status"] == "legacy_activity_not_in_matrix"
    assert payload["events"][1]["status"] == "resolved"


def test_shadow_diagnostic_e2e_create_request_logs_and_is_readable(
    shadow_diagnostic_env, monkeypatch, tmp_path
):
    client = shadow_diagnostic_env["client"]
    db_path: Path = shadow_diagnostic_env["db_path"]
    _set_admin_session(client)
    monkeypatch.setenv("SGAA_VERSIONED_RESOLVER_SHADOW_READ", "1")
    original_csrf = main.app.config.get("WTF_CSRF_ENABLED")
    main.app.config["WTF_CSRF_ENABLED"] = False

    probe_log = tmp_path / "logs" / "versioned_shadow_reads.log"
    probe_log.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        main,
        "_versioned_shadow_read_dedicated_log_path",
        lambda: str(probe_log),
    )
    monkeypatch.setattr(
        main,
        "_collect_versioned_shadow_read_log_paths",
        lambda: [str(probe_log)],
    )

    try:
        with main.app.app_context():
            conn = main.get_db_connection()
            aluno_id, atividade_id = _pick_admin_create_scope(conn)
            before = _shadow_row(conn)

        event_name = f"D631 Shadow {uuid.uuid4().hex[:8]}"
        post_response = client.post(
            "/admin/requisicoes/nova",
            data={
                "aluno_id": str(aluno_id),
                "atividade_id": str(atividade_id),
                "nome_evento": event_name,
                "data_evento": "2026-05-24",
                "horas_solicitadas": "1",
                "observacao": "diagnostico runtime d6.3.1",
            },
            follow_redirects=False,
        )
        assert post_response.status_code in (302, 303)
        assert probe_log.exists()
        log_content = probe_log.read_text(encoding="utf-8")
        assert "event=versioned_resolver_shadow_read" in log_content
        assert "origin=admin_create" in log_content

        with main.app.app_context():
            conn = main.get_db_connection()
            req = conn.execute(
                """
                SELECT id, atividade_id, atividade_versao_id, regra_snapshot_json, codigo_normativo_snapshot
                  FROM requisicoes
                 WHERE aluno_id = ? AND nome_evento = ?
              ORDER BY id DESC
                 LIMIT 1
                """,
                (aluno_id, event_name),
            ).fetchone()
            assert req is not None
            assert int(req["atividade_id"]) == atividade_id
            assert req["atividade_versao_id"] is None
            assert req["regra_snapshot_json"] is None
            assert req["codigo_normativo_snapshot"] is None
            before_diag = _shadow_row(conn)
        before_diag_hash = _sha256_file(db_path)

        diag_response = client.get(
            f"/admin/diagnostico/versioned-shadow-reads?origin=admin_create&aluno_id={aluno_id}&atividade_id_legacy={atividade_id}"
        )
        assert diag_response.status_code == 200
        payload = diag_response.get_json()
        assert payload["shadow_read_enabled"] is True
        assert payload["shadow_read_env_raw"] == "1"
        assert payload["source_mode"] == "dedicated"
        assert payload["dedicated_log_path"] == str(probe_log)
        assert payload["dedicated_log_exists"] is True
        assert payload["dedicated_log_in_paths"] is True
        assert payload["log_paths"] == [str(probe_log)]
        assert payload["logger_level"] == "INFO"
        assert payload["handler_count"] >= 1
        assert payload["count"] >= 1
        assert payload["raw_count"] >= payload["count"]
        assert payload["deduplicated_count"] >= 0
        first_event = payload["events"][0]
        assert first_event["origin"] == "admin_create"
        assert first_event["aluno_id"] == aluno_id
        assert first_event["atividade_id_legacy"] == atividade_id
        assert first_event["status"] in {
            "resolved",
            "legacy_activity_not_in_matrix",
            "legacy_activity_without_base_map",
            "base_without_version_for_matrix",
            "ambiguous_version",
            "matrix_without_norma",
            "version_inactive",
            "error",
        }

        with main.app.app_context():
            conn = main.get_db_connection()
            after_diag = _shadow_row(conn)
        after_diag_hash = _sha256_file(db_path)

        assert before["versao_set"] == after_diag["versao_set"]
        assert before["regra_set"] == after_diag["regra_set"]
        assert before["codigo_set"] == after_diag["codigo_set"]
        assert before_diag["versao_set"] == after_diag["versao_set"]
        assert before_diag["regra_set"] == after_diag["regra_set"]
        assert before_diag["codigo_set"] == after_diag["codigo_set"]

        # A leitura diagnóstica não deve alterar o banco.
        assert before_diag_hash == after_diag_hash
    finally:
        main.app.config["WTF_CSRF_ENABLED"] = original_csrf


def test_shadow_diagnostic_flag_off_does_not_write_dedicated_log(
    shadow_diagnostic_env, monkeypatch, tmp_path
):
    client = shadow_diagnostic_env["client"]
    _set_admin_session(client)
    monkeypatch.delenv("SGAA_VERSIONED_RESOLVER_SHADOW_READ", raising=False)
    original_csrf = main.app.config.get("WTF_CSRF_ENABLED")
    main.app.config["WTF_CSRF_ENABLED"] = False

    probe_log = tmp_path / "logs" / "versioned_shadow_reads.log"
    monkeypatch.setattr(
        main,
        "_versioned_shadow_read_dedicated_log_path",
        lambda: str(probe_log),
    )
    monkeypatch.setattr(
        main,
        "_collect_versioned_shadow_read_log_paths",
        lambda: [str(probe_log)],
    )

    try:
        with main.app.app_context():
            conn = main.get_db_connection()
            aluno_id, atividade_id = _pick_admin_create_scope(conn)

        event_name = f"D632 Shadow Off {uuid.uuid4().hex[:8]}"
        post_response = client.post(
            "/admin/requisicoes/nova",
            data={
                "aluno_id": str(aluno_id),
                "atividade_id": str(atividade_id),
                "nome_evento": event_name,
                "data_evento": "2026-05-24",
                "horas_solicitadas": "1",
                "observacao": "flag off nao deve registrar shadow read",
            },
            follow_redirects=False,
        )
        assert post_response.status_code in (302, 303)
        assert not probe_log.exists()

        diag_response = client.get(
            f"/admin/diagnostico/versioned-shadow-reads?origin=admin_create&aluno_id={aluno_id}&atividade_id_legacy={atividade_id}"
        )
        assert diag_response.status_code == 200
        payload = diag_response.get_json()
        assert payload["shadow_read_enabled"] is False
        assert payload["shadow_read_env_raw"] is None
        assert payload["source_mode"] == "fallback_app_log"
        assert payload["count"] == 0
        assert payload["raw_count"] == 0
        assert payload["deduplicated_count"] == 0
        assert payload["events"] == []
    finally:
        main.app.config["WTF_CSRF_ENABLED"] = original_csrf
