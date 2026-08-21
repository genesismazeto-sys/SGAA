"""Canonical exact-version resolver contracts."""
from __future__ import annotations

import pytest

import main
from app.versioning import resolver
from tests.versioned_test_support import isolated_versioned_app_env


@pytest.fixture()
def versioned_env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "resolver.db") as env:
        yield env


def test_matrix_resolver_accepts_only_its_exact_selected_version(versioned_env):
    with main.app.app_context():
        conn = main.get_db_connection()
        resolved = resolver.resolver_versao_por_matriz(conn, matriz_id=1, atividade_versao_id=27)
        missing = resolver.resolver_versao_por_matriz(conn, matriz_id=1, atividade_versao_id=55)
    assert resolved["status"] == "resolved"
    assert resolved["atividade_versao_id"] == 27
    assert missing["status"] == "not_found"


def test_student_resolver_uses_exact_turma_matrix(versioned_env):
    with main.app.app_context():
        conn = main.get_db_connection()
        aluno_id = conn.execute(
            "SELECT id FROM alunos WHERE matricula='PPA.TESTE.0001'"
        ).fetchone()["id"]
        conn.execute("UPDATE alunos SET turma_id=1 WHERE id=?", (aluno_id,))
        first = resolver.resolver_versao_por_aluno(
            conn, aluno_id=aluno_id, atividade_versao_id=27
        )
        conn.execute("UPDATE alunos SET turma_id=2 WHERE id=?", (aluno_id,))
        second = resolver.resolver_versao_por_aluno(
            conn, aluno_id=aluno_id, atividade_versao_id=55
        )
    assert first["matriz_id_efetiva"] == 1
    assert second["matriz_id_efetiva"] == 2


def test_inactive_selected_version_fails_closed(versioned_env):
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("UPDATE atividade_versao SET status='inativa' WHERE id=27")
        result = resolver.resolver_versao_por_matriz(conn, matriz_id=1, atividade_versao_id=27)
    assert result["status"] == "inactive"


def test_resolver_lists_canonical_version_rows_without_snapshot_payload(versioned_env):
    with main.app.app_context():
        result = resolver.listar_atividades_versionadas_por_matriz(
            main.get_db_connection(), 1
        )
    assert result["status"] == "resolved"
    assert result["atividades"]
    assert all("atividade_versao_id" in row for row in result["atividades"])
    assert all("regra_snapshot_json" not in row for row in result["atividades"])


def test_missing_exact_identity_is_rejected(versioned_env):
    with main.app.app_context():
        result = resolver.resolver_versao_por_matriz(
            main.get_db_connection(), matriz_id=1, atividade_versao_id=None
        )
    assert result == {"status": "not_found", "reason": "exact version is required"}
