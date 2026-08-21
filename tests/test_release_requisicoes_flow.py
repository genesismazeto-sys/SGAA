"""Release happy path over the prod-1 request model."""
from __future__ import annotations

import main
from tests.canonical_request_test_support import create_admin_request, login_admin, login_student
from tests.versioned_test_support import isolated_versioned_app_env


def test_release_requisicoes_flow_happy_path_without_attachment(tmp_path):
    with isolated_versioned_app_env(tmp_path, "release-request.db") as env:
        login_student(env["client"])
        created = env["client"].post("/aluno/nova-requisicao", data={
            "atividade_versao_id": "29", "nome_evento": "Release canonical",
            "data_evento": "2026-05-10", "horas_solicitadas": "4",
        })
        assert created.status_code == 302
        with main.app.app_context():
            req_id = main.get_db_connection().execute(
                "SELECT id FROM requisicoes WHERE nome_evento='Release canonical'"
            ).fetchone()["id"]
        login_admin(env["client"])
        processed = env["client"].post(
            f"/admin/processar_requisicao/{req_id}",
            data={"status": "Deferida", "observacao": "release ok"},
        )
        assert processed.status_code == 302
        with main.app.app_context():
            row = main.get_db_connection().execute(
                "SELECT status,regra_snapshot_json FROM requisicoes WHERE id=?", (req_id,)
            ).fetchone()
        assert row["status"] == "Deferida"
        assert row["regra_snapshot_json"]
