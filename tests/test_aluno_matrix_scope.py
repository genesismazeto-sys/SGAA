from __future__ import annotations

import pytest

import main
from tests.canonical_request_test_support import login_student
from tests.versioned_test_support import isolated_versioned_app_env


@pytest.fixture()
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "student-scope.db") as value:
        login_student(value["client"])
        yield value


def test_student_dashboard_with_exact_matrix_is_available(env):
    assert env["client"].get("/aluno/dashboard").status_code == 200


def test_student_creation_obeys_exact_matrix_version_scope(env):
    accepted = env["client"].post("/aluno/nova-requisicao", data={
        "atividade_versao_id": "29", "nome_evento": "Allowed exact",
        "data_evento": "2026-05-10", "horas_solicitadas": "4",
    })
    rejected = env["client"].post("/aluno/nova-requisicao", data={
        "atividade_versao_id": "1", "nome_evento": "Rejected exact",
        "data_evento": "2026-05-10", "horas_solicitadas": "4",
    })
    assert accepted.status_code == 302
    assert rejected.status_code == 200
    with main.app.app_context():
        conn = main.get_db_connection()
        assert conn.execute("SELECT 1 FROM requisicoes WHERE nome_evento='Allowed exact'").fetchone()
        assert conn.execute("SELECT 1 FROM requisicoes WHERE nome_evento='Rejected exact'").fetchone() is None
