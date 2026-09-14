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


def test_student_resolver_follows_the_current_turma_matrix_across_transfer(versioned_env):
    """Moving Turma changes which Matrix governs the NEXT request, at once.

    Version 27 belongs to Turma 1's Matrix. After the transfer the student is
    governed by Turma 2's Matrix, so 27 stops resolving and Turma 2's own
    version resolves instead. Requests already submitted are untouched: they
    carry their own snapshot and are not re-resolved through this path.
    """
    from app.student_matrix import assign_student_to_turma

    with main.app.app_context():
        conn = main.get_db_connection()
        aluno_id = conn.execute(
            "SELECT id FROM alunos WHERE matricula='PPA.TESTE.0001'"
        ).fetchone()["id"]
        conn.execute("UPDATE alunos SET turma_id=1,matriz_id=1 WHERE id=?", (aluno_id,))
        turma2_versao = conn.execute(
            """SELECT item.atividade_versao_id
                 FROM matriz_atividade_versao_item item
                 JOIN turmas t ON t.matriz_id = item.matriz_id
                WHERE t.id = 2
             ORDER BY item.atividade_versao_id LIMIT 1"""
        ).fetchone()["atividade_versao_id"]

        first = resolver.resolver_versao_por_aluno(
            conn, aluno_id=aluno_id, atividade_versao_id=27
        )
        assign_student_to_turma(conn, aluno_id, 2)
        second = resolver.resolver_versao_por_aluno(
            conn, aluno_id=aluno_id, atividade_versao_id=27
        )
        after = resolver.resolver_versao_por_aluno(
            conn, aluno_id=aluno_id, atividade_versao_id=turma2_versao
        )
        turma2_matriz = conn.execute(
            "SELECT matriz_id FROM turmas WHERE id=2"
        ).fetchone()["matriz_id"]

    assert first["matriz_id_efetiva"] == 1
    # Turma 1's version is no longer reachable...
    assert second["status"] == "not_found"
    assert "matriz_id_efetiva" not in second
    # ...and Turma 2's Matrix now governs.
    assert after["status"] == "resolved"
    assert after["matriz_id_efetiva"] == turma2_matriz


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
