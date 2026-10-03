from __future__ import annotations

import json

import pytest
import main

from tests.canonical_request_test_support import create_admin_request, login_admin
from tests.versioned_test_support import isolated_versioned_app_env


def test_admin_request_api_uses_historical_snapshot_scope(tmp_path):
    with isolated_versioned_app_env(tmp_path, "admin-api.db") as env:
        login_admin(env["client"])
        _, row = create_admin_request(env["client"], "API canonical")
        response = env["client"].get(f"/admin/api/requisicao/{row['id']}")
        payload = response.get_json()
        assert response.status_code == 200
        assert payload["activity_authority"] == "historical_snapshot"
        assert payload["current_activity_allowed"] is True
        assert row["atividade_versao_id"] in payload["allowed_activity_ids"]


@pytest.mark.parametrize("selection_change", ["remove", "successor"])
def test_historical_modal_survives_matrix_selection_change(tmp_path, selection_change):
    with isolated_versioned_app_env(tmp_path, "historical-api.db") as env:
        login_admin(env["client"])
        _, row = create_admin_request(env["client"], "Historical modal")
        frozen = json.loads(row["regra_snapshot_json"])
        with main.app.app_context():
            conn = main.get_db_connection()
            if selection_change == "remove":
                conn.execute(
                    "DELETE FROM matriz_atividade_versao_item WHERE matriz_id=? AND atividade_base_id=?",
                    (frozen["matriz_id_efetiva"], frozen["atividade_base_id"]),
                )
            else:
                successor = conn.execute(
                    "SELECT id FROM atividade_versao WHERE atividade_base_id=? AND id<>? LIMIT 1",
                    (frozen["atividade_base_id"], row["atividade_versao_id"]),
                ).fetchone()["id"]
                conn.execute(
                    "UPDATE matriz_atividade_versao_item SET atividade_versao_id=? WHERE matriz_id=? AND atividade_base_id=?",
                    (successor, frozen["matriz_id_efetiva"], frozen["atividade_base_id"]),
                )
            conn.execute("UPDATE atividade_base SET nome_conceito='Canonical current label' WHERE id=?",
                         (frozen["atividade_base_id"],))
            conn.execute("UPDATE atividade_versao SET grupo='Changed',ch_por_evento=999,limite_total=999,limite_semestre=999,documentos_json='[]' WHERE id=?",
                         (row["atividade_versao_id"],))
            conn.commit()
        response = env["client"].get(f"/admin/api/requisicao/{row['id']}")
        assert response.status_code == 200
        payload = response.get_json()
        assert payload["atividade_nome"] == "Canonical current label"
        assert payload["allowed_activity_ids"] == [row["atividade_versao_id"]]
        assert payload["current_activity_allowed"] is True
        assert payload["activity_authority"] == "historical_snapshot"
        assert len(payload["activities"]) == 1
        option = payload["activities"][0]
        assert option["id"] == option["atividade_versao_id"] == row["atividade_versao_id"]
        assert option["nome"] == payload["atividade_nome"]
        assert option["grupo"] == payload["grupo"] == frozen["grupo"]
        assert option["tipo_atividade"] == payload["tipo_atividade"] == frozen["tipo_atividade"]
        assert option["ch_por_evento"] == frozen["ch_por_evento"]
        assert option["limite_horas_total"] == frozen["limite_total"]
        assert option["limite_horas_semestral"] == frozen["limite_semestre"]
        assert option["documentos_json"] == frozen["documentos_json"]
        with main.app.app_context():
            saved = dict(main.get_db_connection().execute("SELECT * FROM requisicoes WHERE id=?", (row["id"],)).fetchone())
        assert saved == row


def test_historical_modal_rejects_snapshot_base_identity_mismatch(tmp_path):
    with isolated_versioned_app_env(tmp_path, "invalid-link.db") as env:
        login_admin(env["client"])
        _, row = create_admin_request(env["client"], "Invalid identity")
        frozen = json.loads(row["regra_snapshot_json"])
        frozen["atividade_base_id"] = 999999
        with main.app.app_context():
            conn = main.get_db_connection()
            req_id = conn.execute(
                """INSERT INTO requisicoes
                   (aluno_id,atividade_versao_id,data_solicitacao,data_evento,
                    horas_solicitadas,nome_evento,status,regra_snapshot_json)
                   VALUES(?,?,'2026-05-01 10:00:00','2026-05-01',4,
                          'Invalid imported authority','Pendente',?) RETURNING id""",
                (row["aluno_id"], row["atividade_versao_id"], json.dumps(frozen)),
            ).fetchone()["id"]
            conn.commit()
        response = env["client"].get(f"/admin/api/requisicao/{req_id}")
        assert response.status_code == 409
        assert response.get_json()["activities"] == []
        assert response.get_json()["allowed_activity_ids"] == []


def test_historical_read_does_not_authorize_new_requests_or_version_rebinding(tmp_path):
    with isolated_versioned_app_env(tmp_path, "historical-write-guards.db") as env:
        login_admin(env["client"])
        _, row = create_admin_request(env["client"], "Immutable original")
        frozen = json.loads(row["regra_snapshot_json"])
        with main.app.app_context():
            conn = main.get_db_connection()
            successor = conn.execute(
                "SELECT id FROM atividade_versao WHERE atividade_base_id=? AND id<>? LIMIT 1",
                (frozen["atividade_base_id"], row["atividade_versao_id"]),
            ).fetchone()["id"]
            conn.execute(
                "UPDATE matriz_atividade_versao_item SET atividade_versao_id=? WHERE matriz_id=? AND atividade_base_id=?",
                (successor, frozen["matriz_id_efetiva"], frozen["atividade_base_id"]),
            )
            conn.commit()
        assert env["client"].get(f"/admin/api/requisicao/{row['id']}").status_code == 200
        _, rejected = create_admin_request(env["client"], "Not selected anymore", row["atividade_versao_id"])
        assert rejected is None
        response = env["client"].post(f"/admin/requisicoes/{row['id']}/editar", data={
            "edit_target_id": str(row["id"]), "atividade_versao_id": str(successor),
            "nome_evento": "Forbidden rebinding", "data_evento": "2026-05-01",
            "horas_solicitadas": "4", "observacao": "replacement attempt",
        })
        assert response.status_code == 302
        assert "open_edit=1" in response.headers["Location"]
        with env["client"].session_transaction() as session:
            assert any("Para trocar a atividade, crie uma nova solicitação" in message
                       for _, message in session.get("_flashes", []))
        with main.app.app_context():
            saved = dict(main.get_db_connection().execute("SELECT * FROM requisicoes WHERE id=?", (row["id"],)).fetchone())
        assert saved == row
