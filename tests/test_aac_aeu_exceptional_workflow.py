"""AAC -> AEU exceptional workflow closure contract."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import main
from app.versioning.snapshots import (
    RequisicaoSnapshotError,
    prepare_versioned_requisicao_snapshot,
)
from app.views import aluno as aluno_view
from tests.versioned_test_support import isolated_versioned_app_env


ROOT = Path(__file__).resolve().parents[1]
AAC_LABEL = "Acadêmica Complementar"
AEU_LABEL = "Extensão Universitária"
SOURCE_VERSION_ID = 27
SUCCESSOR_VERSION_ID = 55
LEGACY_ACTIVITY_ID = 27


@pytest.fixture()
def workflow_env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "aac_aeu_workflow.db") as env:
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute(
                "INSERT INTO matrizes_atividades_itens (matriz_id, atividade_id) "
                "VALUES (1, ?)",
                (LEGACY_ACTIVITY_ID,),
            )
            conn.execute(
                "UPDATE atividades SET tipo_atividade = ? WHERE id = ?",
                (AEU_LABEL, LEGACY_ACTIVITY_ID),
            )
            _insert_transition(conn)
            conn.commit()
        yield env


def _insert_transition(conn, *, destination_id=SUCCESSOR_VERSION_ID):
    conn.execute(
        """
        INSERT INTO atividade_transicao (
            from_atividade_versao_id,
            to_atividade_versao_id,
            tipo_transicao,
            justificativa
        ) VALUES (?, ?, 'aac_para_aeu', ?)
        """,
        (
            SOURCE_VERSION_ID,
            destination_id,
            "Mudanca normativa explicita com interacao comunitaria.",
        ),
    )


def _student():
    with main.app.app_context():
        return dict(
            main.get_db_connection()
            .execute(
                """
                SELECT a.id AS aluno_id, a.usuario_id, a.turma_id
                  FROM alunos a
                 WHERE a.matricula = 'PPA.TESTE.0001'
                """
            )
            .fetchone()
        )


def _set_student_turma(turma_id):
    student = _student()
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "UPDATE alunos SET turma_id = ? WHERE id = ?",
            (turma_id, student["aluno_id"]),
        )
        conn.commit()
    return student


def _snapshot_for_turma(turma_id):
    student = _set_student_turma(turma_id)
    with main.app.app_context():
        return prepare_versioned_requisicao_snapshot(
            main.get_db_connection(),
            flow_origin="student_create",
            aluno_id=student["aluno_id"],
            atividade_id_legacy=LEGACY_ACTIVITY_ID,
        )


def _insert_approved_request(prepared, *, hours=3):
    student = _student()
    with main.app.app_context():
        conn = main.get_db_connection()
        request_id = conn.execute(
            """
            INSERT INTO requisicoes (
                aluno_id, atividade_id, nome_evento, data_evento,
                horas_solicitadas, horas_deferidas, status, data_solicitacao,
                atividade_versao_id, codigo_normativo_snapshot, regra_snapshot_json
            ) VALUES (?, ?, 'Historico AAC', '2026-05-10', ?, ?, 'Deferida',
                      '2026-05-11 10:00:00', ?, ?, ?)
            RETURNING id
            """,
            (
                student["aluno_id"],
                LEGACY_ACTIVITY_ID,
                hours,
                hours,
                prepared.atividade_versao_id,
                prepared.codigo_normativo,
                prepared.snapshot_json,
            ),
        ).fetchone()["id"]
        conn.commit()
        return int(request_id)


def _insert_request_without_snapshot(*, hours=3):
    student = _student()
    with main.app.app_context():
        conn = main.get_db_connection()
        request_id = conn.execute(
            """
            INSERT INTO requisicoes (
                aluno_id, atividade_id, nome_evento, data_evento,
                horas_solicitadas, horas_deferidas, status, data_solicitacao
            ) VALUES (?, ?, 'Legado sem snapshot', '2026-05-10', ?, ?, 'Deferida',
                      '2026-05-11 10:00:00')
            RETURNING id
            """,
            (student["aluno_id"], LEGACY_ACTIVITY_ID, hours, hours),
        ).fetchone()["id"]
        conn.commit()
        return int(request_id)


def _login_admin(client):
    with main.app.app_context():
        admin_id = main.get_db_connection().execute(
            "SELECT id FROM usuarios WHERE tipo = 'admin' ORDER BY id LIMIT 1"
        ).fetchone()["id"]
    with client.session_transaction() as session:
        session["user_id"] = admin_id
        session["user_type"] = "admin"
        session["user_name"] = "Administrador AAC AEU"


def _login_student(client):
    student = _student()
    with client.session_transaction() as session:
        session["user_id"] = student["usuario_id"]
        session["user_type"] = "aluno"
        session["user_name"] = "Aluno AAC AEU"


def test_transition_trigger_and_persisted_contract_are_explicit(workflow_env):
    with main.app.app_context():
        conn = main.get_db_connection()
        transition = conn.execute(
            "SELECT * FROM atividade_transicao WHERE tipo_transicao = 'aac_para_aeu'"
        ).fetchone()
        assert transition["from_atividade_versao_id"] == SOURCE_VERSION_ID
        assert transition["to_atividade_versao_id"] == SUCCESSOR_VERSION_ID
        assert transition["justificativa"].strip()
        with pytest.raises(sqlite3.IntegrityError, match="AAC -> AEU"):
            conn.execute(
                """
                INSERT INTO atividade_transicao (
                    from_atividade_versao_id, to_atividade_versao_id,
                    tipo_transicao, justificativa
                ) VALUES (?, ?, 'aac_para_aeu', 'Direcao invalida')
                """,
                (SUCCESSOR_VERSION_ID, SOURCE_VERSION_ID),
            )


def test_exact_matrix_controls_old_aac_and_new_aeu_snapshots(workflow_env):
    historical = _snapshot_for_turma(1)
    current = _snapshot_for_turma(2)

    historical_payload = json.loads(historical.snapshot_json)
    current_payload = json.loads(current.snapshot_json)
    assert historical.atividade_versao_id == SOURCE_VERSION_ID
    assert historical_payload["eixo"] == "AAC"
    assert historical_payload["tipo_atividade_legacy"] == AAC_LABEL
    assert historical_payload["aac_aeu_transition"] == {
        "from_atividade_versao_id": SOURCE_VERSION_ID,
        "justificativa": "Mudanca normativa explicita com interacao comunitaria.",
        "tipo_transicao": "aac_para_aeu",
        "to_atividade_versao_id": SUCCESSOR_VERSION_ID,
    }
    assert current.atividade_versao_id == SUCCESSOR_VERSION_ID
    assert current_payload["eixo"] == "AEU"
    assert current_payload["tipo_atividade_legacy"] == AEU_LABEL
    assert "aac_aeu_transition" not in current_payload


def test_frozen_historical_request_survives_later_transition_and_live_mutation(workflow_env):
    historical = _snapshot_for_turma(1)
    request_id = _insert_approved_request(historical)
    frozen_json = historical.snapshot_json

    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("DELETE FROM atividade_transicao")
        conn.execute(
            "UPDATE atividades SET nome = 'LIVE MUTATED AEU', grupo = '99 - MUTABLE' "
            "WHERE id = ?",
            (LEGACY_ACTIVITY_ID,),
        )
        conn.commit()
        progress = aluno_view._build_aluno_progresso_payload(
            conn, _student()["usuario_id"]
        )
        stored = conn.execute(
            "SELECT regra_snapshot_json FROM requisicoes WHERE id = ?", (request_id,)
        ).fetchone()["regra_snapshot_json"]

    rows = [row for row in progress["atividades"] if row["total"] == 3.0]
    assert len(rows) == 1
    assert rows[0]["tipo_atividade"] == AAC_LABEL
    assert rows[0]["nome"] != "LIVE MUTATED AEU"
    assert stored == frozen_json


@pytest.mark.parametrize("invalid_transition", ["missing", "wrong_base", "duplicate"])
def test_missing_wrong_base_or_ambiguous_transition_fails_closed(
    workflow_env, invalid_transition
):
    _set_student_turma(1)
    student = _student()
    with main.app.app_context():
        conn = main.get_db_connection()
        if invalid_transition in {"missing", "wrong_base"}:
            conn.execute("DELETE FROM atividade_transicao")
        if invalid_transition == "wrong_base":
            _insert_transition(conn, destination_id=56)
        if invalid_transition == "duplicate":
            _insert_transition(conn)
        conn.commit()
        with pytest.raises(RequisicaoSnapshotError):
            prepare_versioned_requisicao_snapshot(
                conn,
                flow_origin="student_create",
                aluno_id=student["aluno_id"],
                atividade_id_legacy=LEGACY_ACTIVITY_ID,
            )


def test_student_and_admin_present_exact_matrix_axis(workflow_env):
    client = workflow_env["client"]
    student = _set_student_turma(1)
    with main.app.app_context():
        conn = main.get_db_connection()
        _, _, aac_rows = aluno_view._list_atividades_for_usuario(
            conn, student["usuario_id"], AAC_LABEL
        )
        _, _, aeu_rows = aluno_view._list_atividades_for_usuario(
            conn, student["usuario_id"], AEU_LABEL
        )
    aac_item = next(row for row in aac_rows if row["id"] == LEGACY_ACTIVITY_ID)
    assert aac_item["tipo_atividade"] == AAC_LABEL
    assert not any(row["id"] == LEGACY_ACTIVITY_ID for row in aeu_rows)

    _login_admin(client)
    response = client.get(
        f"/admin/api/aluno/{student['aluno_id']}/requisicao-scope"
    )
    assert response.status_code == 200
    payload = response.get_json()
    admin_item = next(
        row for row in payload["activities"] if row["id"] == LEGACY_ACTIVITY_ID
    )
    assert admin_item["tipo_atividade"] == AAC_LABEL
    admin_html = client.get("/admin/requisicoes").get_data(as_text=True)
    assert "replaceActivityOptions" in admin_html
    assert "data.activities" in admin_html

    _set_student_turma(2)
    response = client.get(
        f"/admin/api/aluno/{student['aluno_id']}/requisicao-scope"
    )
    admin_item = next(
        row for row in response.get_json()["activities"]
        if row["id"] == LEGACY_ACTIVITY_ID
    )
    assert admin_item["tipo_atividade"] == AEU_LABEL


def test_historical_admin_api_keeps_frozen_matrix_authority_after_reassignment(
    workflow_env,
):
    historical = _snapshot_for_turma(1)
    request_id = _insert_approved_request(historical)
    student = _set_student_turma(2)
    client = workflow_env["client"]
    _login_admin(client)

    response = client.get(f"/admin/api/requisicao/{request_id}")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["activity_authority"] == "historical_snapshot"
    assert payload["atividade_versao_id"] == SOURCE_VERSION_ID
    assert payload["tipo_atividade"] == AAC_LABEL
    historical_item = next(
        row for row in payload["activities"]
        if row["atividade_versao_id"] == SOURCE_VERSION_ID
    )
    assert historical_item["id"] == LEGACY_ACTIVITY_ID
    assert historical_item["tipo_atividade"] == AAC_LABEL
    assert SUCCESSOR_VERSION_ID not in {
        row["atividade_versao_id"] for row in payload["activities"]
    }

    current = client.get(
        f"/admin/api/aluno/{student['aluno_id']}/requisicao-scope"
    ).get_json()
    current_item = next(
        row for row in current["activities"]
        if row["atividade_versao_id"] == SUCCESSOR_VERSION_ID
    )
    assert current_item["id"] == LEGACY_ACTIVITY_ID
    assert current_item["tipo_atividade"] == AEU_LABEL


def test_admin_api_true_no_snapshot_preserves_current_matrix_compatibility(workflow_env):
    _set_student_turma(2)
    request_id = _insert_request_without_snapshot()
    client = workflow_env["client"]
    _login_admin(client)

    response = client.get(f"/admin/api/requisicao/{request_id}")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["activity_authority"] == "current_matrix_compatibility"
    assert any(
        row["atividade_versao_id"] == SUCCESSOR_VERSION_ID
        and row["tipo_atividade"] == AEU_LABEL
        for row in payload["activities"]
    )


def test_admin_api_invalid_snapshot_fails_closed_without_current_catalogue(workflow_env):
    historical = _snapshot_for_turma(1)
    request_id = _insert_approved_request(historical)
    _set_student_turma(2)
    with main.app.app_context():
        conn = main.get_db_connection()
        malformed = json.loads(historical.snapshot_json)
        malformed["schema_version"] = "unsupported-test-schema"
        conn.execute(
            "UPDATE requisicoes SET regra_snapshot_json = ? WHERE id = ?",
            (json.dumps(malformed), request_id),
        )
        conn.commit()
    client = workflow_env["client"]
    _login_admin(client)

    response = client.get(f"/admin/api/requisicao/{request_id}")
    assert response.status_code == 409
    payload = response.get_json()
    assert payload["activity_authority"] == "invalid"
    assert payload["activities"] == []
    assert payload["allowed_activity_ids"] == []


def test_admin_modal_renders_server_authority_and_api_failure_fails_closed(workflow_env):
    from playwright.sync_api import sync_playwright

    historical = _snapshot_for_turma(1)
    request_id = _insert_approved_request(historical)
    _set_student_turma(2)
    client = workflow_env["client"]
    _login_admin(client)
    admin_html = client.get("/admin/requisicoes").get_data(as_text=True)
    browser_html = admin_html.replace(
        "<head>", '<head><base href="http://sgaa.test/">', 1
    )
    historical_payload = client.get(
        f"/admin/api/requisicao/{request_id}"
    ).get_json()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.route(
            f"**/admin/api/requisicao/{request_id}",
            lambda route: route.fulfill(json=historical_payload),
        )
        page.set_content(browser_html, wait_until="domcontentloaded")
        initial_options = page.locator("#m_atividade_id_select option")
        initial_option_count = initial_options.count()
        initial_placeholder = initial_options.first.get_attribute("data-placeholder")

        page.evaluate(
            "requestId => window.__openExistingReqModal(requestId, 'process')",
            request_id,
        )
        page.locator("#req-modal:not([hidden])").wait_for()
        options = page.locator("#m_atividade_id_select option:not([data-placeholder])")
        success_option_count = options.count()
        success_source_count = page.locator(
            "#m_atividade_id_select option[data-atividade-versao-id='27']"
        ).count()
        success_successor_count = page.locator(
            "#m_atividade_id_select option[data-atividade-versao-id='55']"
        ).count()

        failed_page = browser.new_page()
        failed_page.route(
            "**/admin/api/requisicao/**",
            lambda route: route.fulfill(status=503, body="unavailable"),
        )
        failed_page.set_content(browser_html, wait_until="domcontentloaded")
        failed_page.evaluate(
            "requestId => window.__openExistingReqModal(requestId, 'edit')",
            request_id,
        )
        failed_page.locator("#req-modal:not([hidden])").wait_for()
        failed_options = failed_page.locator("#m_atividade_id_select option")
        observed = {
            "initial_option_count": initial_option_count,
            "initial_placeholder": initial_placeholder,
            "success_option_count": success_option_count,
            "success_source_count": success_source_count,
            "success_successor_count": success_successor_count,
            "failure_option_count": failed_options.count(),
            "failure_disabled": failed_page.locator(
                "#m_atividade_id_select"
            ).is_disabled(),
            "failure_mode": failed_page.locator("#req-modal").get_attribute(
                "data-mode"
            ),
            "failure_hint": failed_page.locator("#m_scope_hint").inner_text().lower(),
        }
        browser.close()
    assert observed == {
        "initial_option_count": 1,
        "initial_placeholder": "1",
        "success_option_count": len(historical_payload["activities"]),
        "success_source_count": 1,
        "success_successor_count": 0,
        "failure_option_count": 1,
        "failure_disabled": True,
        "failure_mode": "view",
        "failure_hint": "não foi possível carregar os dados autoritativos da atividade.",
    }


def test_student_cannot_access_admin_scope(workflow_env):
    client = workflow_env["client"]
    _login_student(client)
    response = client.get(
        f"/admin/api/aluno/{_student()['aluno_id']}/requisicao-scope"
    )
    assert response.status_code in (302, 403)


def test_transition_is_consumed_only_by_snapshot_creation_authority():
    snapshots_source = (ROOT / "app/versioning/snapshots.py").read_text(encoding="utf-8")
    assert snapshots_source.count("FROM atividade_transicao") == 1
    assert "INSERT INTO atividade_transicao" not in snapshots_source
    assert "UPDATE atividade_transicao" not in snapshots_source
    assert "DELETE FROM atividade_transicao" not in snapshots_source
    for relative in (
        "app/versioning/resolver.py",
        "app/versioning/request_history.py",
        "app/views/aluno.py",
        "app/views/admin/requisicoes.py",
    ):
        assert "atividade_transicao" not in (ROOT / relative).read_text(encoding="utf-8")
