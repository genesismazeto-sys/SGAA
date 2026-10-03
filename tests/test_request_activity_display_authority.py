"""Operational labels follow the linked base; historical evidence stays frozen."""
from __future__ import annotations

import json

import pytest

import main
from app.versioning.request_history import read_historical_request
from tests.canonical_request_test_support import (
    create_admin_request,
    login_admin,
    login_student,
)
from tests.versioned_test_support import isolated_versioned_app_env


@pytest.fixture()
def renamed_request(tmp_path, request):
    canonical_name = request.param
    with isolated_versioned_app_env(tmp_path, "display-authority.db") as env:
        login_admin(env["client"])
        with main.app.app_context():
            conn = main.get_db_connection()
            base_id = conn.execute(
                "SELECT atividade_base_id FROM atividade_versao WHERE id=29"
            ).fetchone()[0]
            conn.execute(
                "UPDATE atividade_base SET nome_conceito=? WHERE id=?",
                (canonical_name.upper(), base_id),
            )
            conn.commit()
        response, row = create_admin_request(env["client"], "Display authority")
        assert response.status_code == 302 and row is not None
        assert json.loads(row["regra_snapshot_json"])["nome_exibivel"] == canonical_name.upper()
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute(
                "UPDATE atividade_base SET nome_conceito=? WHERE id=?",
                (canonical_name, base_id),
            )
            conn.commit()
        yield env, row, canonical_name


@pytest.mark.parametrize("renamed_request", [
    "Palestras na Faculdade EJ",
    "Horas de voo em escola homologada pela ANAC",
], indirect=True)
def test_admin_api_uses_linked_base_name_without_rewriting_request(renamed_request):
    env, row, canonical_name = renamed_request
    response = env["client"].get(f"/admin/api/requisicao/{row['id']}")
    assert response.status_code == 200
    assert response.get_json()["atividade_nome"] == canonical_name
    with main.app.app_context():
        current = dict(main.get_db_connection().execute(
            "SELECT * FROM requisicoes WHERE id=?", (row["id"],)
        ).fetchone())
    assert current == row


@pytest.mark.parametrize("renamed_request", ["Palestras na Faculdade EJ"], indirect=True)
def test_request_list_details_filters_and_student_dashboard_use_linked_name(renamed_request):
    env, row, canonical_name = renamed_request
    client = env["client"]
    for url in ("/admin/requisicoes", f"/admin/requisicao/{row['id']}"):
        response = client.get(url)
        assert response.status_code == 200
        assert canonical_name in response.get_data(as_text=True)
        assert canonical_name.upper() not in response.get_data(as_text=True)
    filtered = client.get("/admin/requisicoes", query_string={"atividade": canonical_name})
    assert filtered.status_code == 200
    assert "Display authority" in filtered.get_data(as_text=True)
    login_student(client)
    for url in (
        "/aluno/requisicoes",
        f"/aluno/requisicoes/{row['id']}",
        "/aluno/progresso",
    ):
        response = client.get(url)
        assert response.status_code == 200
        assert canonical_name in response.get_data(as_text=True), url
        assert canonical_name.upper() not in response.get_data(as_text=True)
    # The dashboard contains aggregate metrics, not individual request labels.
    assert client.get("/aluno/dashboard").status_code == 200


@pytest.mark.parametrize("renamed_request", ["Palestras na Faculdade EJ"], indirect=True)
def test_frozen_historical_rules_and_provenance_remain_authoritative(renamed_request):
    env, row, canonical_name = renamed_request
    original_snapshot = row["regra_snapshot_json"]
    history = read_historical_request(row)
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "UPDATE atividade_versao SET grupo='New live group',limite_total=999 "
            "WHERE id=?", (row["atividade_versao_id"],),
        )
        conn.commit()
    response = env["client"].get(f"/admin/api/requisicao/{row['id']}")
    assert response.status_code == 200
    data = response.get_json()
    assert data["regra_snapshot_json"] == original_snapshot
    assert data["grupo"] == history.grupo
    assert data["tipo_atividade"] == history.tipo_atividade
    assert json.loads(data["regra_snapshot_json"]) == json.loads(original_snapshot)
