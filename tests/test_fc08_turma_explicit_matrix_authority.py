"""FC08: Turma.matriz_id is the sole matrix authority in prod-1."""
from __future__ import annotations

import main
from app.matrix_scope import (
    get_allowed_activity_version_ids_for_turma_matrix,
    get_effective_matriz_for_turma,
    is_activity_version_allowed_for_turma_matrix,
)
from tests.versioned_test_support import isolated_versioned_app_env


def _turma(conn):
    return conn.execute("SELECT * FROM turmas WHERE codigo='PPA-T10'").fetchone()


def test_explicit_turma_matrix_resolves_exact_matrix(tmp_path):
    with isolated_versioned_app_env(tmp_path, "fc08-resolve.db"):
        with main.app.app_context():
            conn = main.get_db_connection()
            turma = _turma(conn)
            matrix = get_effective_matriz_for_turma(conn, turma["curso_id"], turma["matriz_id"])
            assert matrix["id"] == turma["matriz_id"]


def test_missing_explicit_matrix_fails_closed(tmp_path):
    with isolated_versioned_app_env(tmp_path, "fc08-missing.db"):
        with main.app.app_context():
            conn = main.get_db_connection()
            turma = _turma(conn)
            assert get_effective_matriz_for_turma(conn, turma["curso_id"], None) is None
            assert get_allowed_activity_version_ids_for_turma_matrix(conn, turma["curso_id"], None) == (set(), None)


def test_only_exact_matrix_versions_are_allowed(tmp_path):
    with isolated_versioned_app_env(tmp_path, "fc08-exact.db"):
        with main.app.app_context():
            conn = main.get_db_connection()
            turma = _turma(conn)
            allowed, matrix = get_allowed_activity_version_ids_for_turma_matrix(
                conn, turma["curso_id"], turma["matriz_id"]
            )
            assert matrix["id"] == 1
            assert 1 in allowed
            assert 29 not in allowed
            assert is_activity_version_allowed_for_turma_matrix(conn, 1, turma["curso_id"], turma["matriz_id"])
            assert not is_activity_version_allowed_for_turma_matrix(conn, 29, turma["curso_id"], turma["matriz_id"])


def test_matrix_from_other_course_is_rejected(tmp_path):
    with isolated_versioned_app_env(tmp_path, "fc08-course.db"):
        with main.app.app_context():
            conn = main.get_db_connection()
            turma = _turma(conn)
            other_course = conn.execute(
                "INSERT INTO cursos(nome,codigo,duracao_periodos,status) VALUES ('Outro','OUT',8,'ativo') RETURNING id"
            ).fetchone()["id"]
            assert get_effective_matriz_for_turma(conn, other_course, turma["matriz_id"]) is None
