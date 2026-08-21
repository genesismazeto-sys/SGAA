from __future__ import annotations

import json

import pytest

import main
from tests.canonical_request_test_support import login_student
from tests.versioned_test_support import isolated_versioned_app_env


@pytest.fixture()
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "student-history.db") as value:
        login_student(value["client"])
        yield value


def _create(client, name="Student snapshot"):
    response = client.post("/aluno/nova-requisicao", data={
        "atividade_versao_id": "29", "nome_evento": name,
        "data_evento": "2026-05-10", "horas_solicitadas": "4", "observacao": "ok",
    })
    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT * FROM requisicoes WHERE nome_evento=?", (name,)
        ).fetchone()
        return response, dict(row)


def test_student_creation_always_persists_and_renders_snapshot(env):
    response, row = _create(env["client"])
    assert response.status_code == 302
    assert json.loads(row["regra_snapshot_json"])["atividade_versao_id"] == 29
    detail = env["client"].get(f"/aluno/requisicoes/{row['id']}")
    assert detail.status_code in {200, 302}


def test_activity_identity_is_immutable_on_edit(env):
    _, row = _create(env["client"], "Immutable identity")
    response = env["client"].post(f"/aluno/requisicoes/{row['id']}", data={
        "atividade_versao_id": "30", "nome_evento": "Immutable identity edited",
        "data_evento": "2026-05-11", "horas_solicitadas": "5", "observacao": "edit",
    })
    assert response.status_code in {200, 302}
    with main.app.app_context():
        current = main.get_db_connection().execute(
            "SELECT atividade_versao_id,regra_snapshot_json FROM requisicoes WHERE id=?", (row["id"],)
        ).fetchone()
    assert current["atividade_versao_id"] == 29
    assert current["regra_snapshot_json"] == row["regra_snapshot_json"]


def test_invalid_snapshot_presentation_fails_closed_without_live_repair(env):
    _, row = _create(env["client"], "Invalid snapshot")
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("DROP TRIGGER trg_requisicoes_snapshot_immutable")
        conn.execute("UPDATE requisicoes SET regra_snapshot_json='{}' WHERE id=?", (row["id"],))
        conn.commit()
    response = env["client"].get(f"/aluno/requisicoes/{row['id']}")
    assert response.status_code in {200, 409}
    assert "leitura indispon" in response.get_data(as_text=True).lower()
