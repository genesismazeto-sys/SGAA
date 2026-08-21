"""End-to-end contracts for the prod-1 Matrix/version authority."""
from __future__ import annotations

import sqlite3

import pytest

import main
from app.versioning import resolver
from tests.versioned_test_support import isolated_versioned_app_env


@pytest.fixture()
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "matrix-version-contract.db") as value:
        yield value


def test_same_base_can_resolve_different_exact_versions_in_different_matrices(env):
    with main.app.app_context():
        conn = main.get_db_connection()
        first = resolver.resolver_versao_por_matriz(conn, matriz_id=1, atividade_versao_id=27)
        second = resolver.resolver_versao_por_matriz(conn, matriz_id=2, atividade_versao_id=55)
    assert first["status"] == second["status"] == "resolved"
    assert first["atividade_base_id"] == second["atividade_base_id"]
    assert first["atividade_versao_id"] != second["atividade_versao_id"]


def test_matrix_cannot_hold_two_versions_of_same_base(env):
    with main.app.app_context():
        conn = main.get_db_connection()
        existing = conn.execute(
            "SELECT atividade_base_id FROM matriz_atividade_versao_item WHERE matriz_id=1 AND atividade_versao_id=27"
        ).fetchone()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO matriz_atividade_versao_item
                       (matriz_id,atividade_base_id,atividade_versao_id) VALUES (1,?,28)""",
                (existing["atividade_base_id"],),
            )


def test_composite_foreign_key_rejects_base_version_mismatch(env):
    with main.app.app_context():
        conn = main.get_db_connection()
        version = conn.execute("SELECT atividade_base_id FROM atividade_versao WHERE id=29").fetchone()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO matriz_atividade_versao_item
                       (matriz_id,atividade_base_id,atividade_versao_id) VALUES (1,?,29)""",
                (version["atividade_base_id"] + 10000,),
            )


def test_resolver_is_read_only(env):
    with main.app.app_context():
        conn = main.get_db_connection()
        before = conn.total_changes
        for _ in range(3):
            assert resolver.resolver_versao_por_matriz(
                conn, matriz_id=1, atividade_versao_id=27
            )["status"] == "resolved"
        assert conn.total_changes == before


def test_student_without_turma_matrix_fails_closed(env):
    with main.app.app_context():
        conn = main.get_db_connection()
        aluno_id = conn.execute("SELECT id FROM alunos WHERE matricula='PPA.TESTE.0001'").fetchone()["id"]
        conn.execute("UPDATE alunos SET turma_id=NULL WHERE id=?", (aluno_id,))
        result = resolver.resolver_versao_por_aluno(conn, aluno_id=aluno_id, atividade_versao_id=27)
    assert result == {"status": "not_found", "reason": "student has no effective matrix"}


def test_matrix_listing_contains_only_explicit_canonical_items(env):
    with main.app.app_context():
        conn = main.get_db_connection()
        expected = conn.execute(
            "SELECT COUNT(*) FROM matriz_atividade_versao_item WHERE matriz_id=1"
        ).fetchone()[0]
        result = resolver.listar_atividades_versionadas_por_matriz(conn, 1)
    assert result["status"] == "resolved"
    assert len(result["atividades"]) == expected
    assert all(row["atividade_base_id"] and row["atividade_versao_id"] for row in result["atividades"])
