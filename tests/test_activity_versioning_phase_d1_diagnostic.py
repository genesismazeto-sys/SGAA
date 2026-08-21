"""Read-only diagnostics over the canonical Activity Version model."""
from __future__ import annotations

import pytest

import main
from tests.versioned_test_support import isolated_versioned_app_env


@pytest.fixture()
def diagnostic_client(tmp_path):
    with isolated_versioned_app_env(tmp_path, "diagnostic.db") as env:
        client = env["client"]
        with client.session_transaction() as session:
            session.update(user_id=1, user_type="admin", user_name="Admin")
        yield client


def test_diagnostic_lists_exact_matrix_versions(diagnostic_client):
    response = diagnostic_client.get("/admin/diagnostico/atividades-versionadas?matriz_id=1")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["consulta"] == {"modo": "matriz", "matriz_id": 1}
    assert {row["atividade_versao_id"] for row in payload["atividades"]} == set(range(1, 29))


def test_diagnostic_resolves_turma_code_to_exact_matrix(diagnostic_client):
    response = diagnostic_client.get(
        "/admin/diagnostico/atividades-versionadas?turma_codigo=PPA-T10"
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["consulta"]["matriz_id"] == 1
    assert payload["matriz"]["id"] == 1


def test_diagnostic_view_renders_canonical_rows(diagnostic_client):
    response = diagnostic_client.get(
        "/admin/diagnostico/atividades-versionadas/view?matriz_id=2"
    )
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "AAC-rev6" in html
    assert "AEU-rev1" in html


def test_diagnostic_requires_admin(tmp_path):
    with isolated_versioned_app_env(tmp_path, "diagnostic_auth.db") as env:
        response = env["client"].get("/admin/diagnostico/atividades-versionadas")
    assert response.status_code in {302, 401, 403}
