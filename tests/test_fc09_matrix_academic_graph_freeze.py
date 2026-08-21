"""FC09: an assigned Matrix freezes its canonical academic graph."""
from __future__ import annotations

import pytest

import main
from app.matrix_scope import (
    AcademicGraphFrozenError,
    is_activity_base_referenced_by_assigned_matrix,
    is_activity_version_referenced_by_assigned_matrix,
    is_matrix_assigned,
)
from app.views.admin.matrizes import (
    _remover_versao_da_matriz_para_base,
    _set_versao_da_matriz_para_base,
)
from tests.canonical_matrix_test_support import current_version_id, login_admin, seed_matrix_graph
from tests.versioned_test_support import isolated_versioned_app_env


def _assign(conn, seed):
    turma_id = conn.execute(
        """INSERT INTO turmas
               (nome,turno,status,numero,curso_id,ano_inicio,semestre_inicio,codigo,matriz_id)
             VALUES (?,'Noite','Ativa',?,?,2026,1,?,?) RETURNING id""",
        (f'Frozen {seed["matrix_id"]}', 2000 + seed["matrix_id"], seed["course_id"],
         f'FROZEN-{seed["matrix_id"]}', seed["matrix_id"]),
    ).fetchone()["id"]
    conn.commit()
    return turma_id


def test_assigned_matrix_and_exact_graph_are_detected(tmp_path):
    with isolated_versioned_app_env(tmp_path, "fc09-detect.db"):
        with main.app.app_context():
            conn = main.get_db_connection()
            seed = seed_matrix_graph(conn, name="FC09 detect")
            _assign(conn, seed)
            assert is_matrix_assigned(conn, seed["matrix_id"])
            assert is_activity_base_referenced_by_assigned_matrix(conn, seed["base_id"])
            assert is_activity_version_referenced_by_assigned_matrix(conn, seed["v1"])
            assert not is_activity_version_referenced_by_assigned_matrix(conn, seed["v2"])


def test_assigned_matrix_relink_and_removal_fail_before_write(tmp_path):
    with isolated_versioned_app_env(tmp_path, "fc09-link.db"):
        with main.app.app_context():
            conn = main.get_db_connection()
            seed = seed_matrix_graph(conn, name="FC09 link")
            _assign(conn, seed)
            with pytest.raises(AcademicGraphFrozenError):
                _set_versao_da_matriz_para_base(conn, seed["matrix_id"], seed["base_id"], seed["v2"])
            with pytest.raises(AcademicGraphFrozenError):
                _remover_versao_da_matriz_para_base(conn, seed["matrix_id"], seed["base_id"])
            assert current_version_id(conn, seed) == seed["v1"]


def test_unassigned_matrix_can_relink_and_remove(tmp_path):
    with isolated_versioned_app_env(tmp_path, "fc09-unassigned.db"):
        with main.app.app_context():
            conn = main.get_db_connection()
            seed = seed_matrix_graph(conn, name="FC09 unassigned")
            _set_versao_da_matriz_para_base(conn, seed["matrix_id"], seed["base_id"], seed["v2"])
            conn.commit()
            assert current_version_id(conn, seed) == seed["v2"]
            assert _remover_versao_da_matriz_para_base(conn, seed["matrix_id"], seed["base_id"]) == 1


def test_assigned_matrix_delete_is_refused_and_pointer_survives(tmp_path):
    with isolated_versioned_app_env(tmp_path, "fc09-delete.db") as env:
        with main.app.app_context():
            conn = main.get_db_connection()
            seed = seed_matrix_graph(conn, name="FC09 delete")
            turma_id = _assign(conn, seed)
        login_admin(env["client"])
        response = env["client"].post(f'/admin/matrizes/{seed["matrix_id"]}/excluir')
        assert response.status_code == 302
        with main.app.app_context():
            conn = main.get_db_connection()
            assert conn.execute("SELECT matriz_id FROM turmas WHERE id=?", (turma_id,)).fetchone()["matriz_id"] == seed["matrix_id"]
            assert conn.execute("SELECT 1 FROM matrizes_atividades WHERE id=?", (seed["matrix_id"],)).fetchone()


def test_assigned_matrix_membership_post_is_atomic(tmp_path):
    with isolated_versioned_app_env(tmp_path, "fc09-membership.db") as env:
        with main.app.app_context():
            conn = main.get_db_connection()
            seed = seed_matrix_graph(conn, name="FC09 membership")
            _assign(conn, seed)
        login_admin(env["client"])
        response = env["client"].post(
            f'/admin/editar_matriz/{seed["matrix_id"]}?tab=aac',
            data={"active_tab": "aac", "selected_activity_ids": [str(seed["v2"])]},
        )
        assert response.status_code == 302
        with main.app.app_context():
            assert current_version_id(main.get_db_connection(), seed) == seed["v1"]


def test_freeze_ends_only_after_last_turma_pointer_is_removed(tmp_path):
    with isolated_versioned_app_env(tmp_path, "fc09-lifetime.db"):
        with main.app.app_context():
            conn = main.get_db_connection()
            seed = seed_matrix_graph(conn, name="FC09 lifetime")
            turma_id = _assign(conn, seed)
            conn.execute("DELETE FROM turmas WHERE id=?", (turma_id,))
            conn.commit()
            assert not is_matrix_assigned(conn, seed["matrix_id"])
            _set_versao_da_matriz_para_base(conn, seed["matrix_id"], seed["base_id"], seed["v2"])
            assert current_version_id(conn, seed) == seed["v2"]
