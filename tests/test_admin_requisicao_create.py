from __future__ import annotations

import pytest

from tests.canonical_request_test_support import create_admin_request, login_admin, student_identity
from tests.versioned_test_support import isolated_versioned_app_env


@pytest.fixture()
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "admin-create.db") as value:
        yield value


def test_admin_scope_exposes_exact_matrix_versions(env):
    login_admin(env["client"])
    response = env["client"].get(
        f"/admin/api/aluno/{student_identity()['aluno_id']}/requisicao-scope"
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert 29 in payload["allowed_activity_ids"]
    assert payload["matriz_scope"]["id"] == 2


def test_admin_creation_writes_mandatory_snapshot(env):
    login_admin(env["client"])
    response, row = create_admin_request(env["client"], "Admin canonical create")
    assert response.status_code == 302
    assert row["atividade_versao_id"] == 29
    assert row["regra_snapshot_json"]
    assert "codigo_normativo_snapshot" not in row
