from __future__ import annotations

import main
from app.matrix_scope import is_matrix_assigned
from app.views.admin.matrizes import _prepare_matriz_norma_delta
from tests.canonical_matrix_test_support import login_admin, seed_matrix_graph
from tests.versioned_test_support import isolated_versioned_app_env


def _assign_turma(conn, seed):
    conn.execute(
        """INSERT INTO turmas
               (nome,turno,status,numero,curso_id,ano_inicio,semestre_inicio,codigo,matriz_id)
             VALUES (?,'Noite','Ativa',?,?,2026,1,?,?)""",
        (f'Turma {seed["matrix_id"]}', 1000 + seed["matrix_id"], seed["course_id"],
         f'TEST-{seed["matrix_id"]}', seed["matrix_id"]),
    )
    conn.commit()


def test_bound_norm_cannot_be_removed_while_selected_version_uses_it(tmp_path):
    with isolated_versioned_app_env(tmp_path, "norm-protected.db"):
        with main.app.app_context():
            conn = main.get_db_connection()
            seed = seed_matrix_graph(conn, name="Protected norm")
            delta, error = _prepare_matriz_norma_delta(conn, seed["matrix_id"], set())
            assert delta is None
            assert error == "protected_norma_removal"


def test_assigned_matrix_freezes_norm_changes(tmp_path):
    with isolated_versioned_app_env(tmp_path, "norm-frozen.db"):
        with main.app.app_context():
            conn = main.get_db_connection()
            seed = seed_matrix_graph(conn, name="Frozen norm")
            conn.execute("INSERT INTO norma_atividade(codigo,eixo,revisao,nome,status) VALUES ('AAC-extra','AAC','x','Extra','ativa')")
            extra = conn.execute("SELECT id FROM norma_atividade WHERE codigo='AAC-extra'").fetchone()["id"]
            _assign_turma(conn, seed)
            assert is_matrix_assigned(conn, seed["matrix_id"])
            delta, error = _prepare_matriz_norma_delta(conn, seed["matrix_id"], {1, extra})
            assert delta is None
            assert error == "frozen_matrix"


def test_unassigned_matrix_accepts_active_norm_delta(tmp_path):
    with isolated_versioned_app_env(tmp_path, "norm-delta.db"):
        with main.app.app_context():
            conn = main.get_db_connection()
            seed = seed_matrix_graph(conn, name="Norm delta")
            extra = conn.execute(
                "INSERT INTO norma_atividade(codigo,eixo,revisao,nome,status) VALUES ('AAC-extra-2','AAC','x','Extra','ativa') RETURNING id"
            ).fetchone()["id"]
            delta, error = _prepare_matriz_norma_delta(conn, seed["matrix_id"], {1, extra})
            assert error is None
            assert delta == {"to_add": {extra}, "to_remove": set()}


def test_matrix_page_exposes_norm_controls_and_freeze_state(tmp_path):
    with isolated_versioned_app_env(tmp_path, "norm-ui.db") as env:
        with main.app.app_context():
            conn = main.get_db_connection()
            seed = seed_matrix_graph(conn, name="Norm UI")
            _assign_turma(conn, seed)
        login_admin(env["client"])
        response = env["client"].get(f'/admin/editar_matriz/{seed["matrix_id"]}')
        html = response.get_data(as_text=True)
        assert response.status_code == 200
        assert "AAC-rev5" in html
        assert "disabled" in html


def test_route_inventory_matches_canonical_surface(tmp_path):
    with isolated_versioned_app_env(tmp_path, "route-count.db"):
        assert len(list(main.app.url_map.iter_rules())) == 129
        assert len({rule.endpoint for rule in main.app.url_map.iter_rules()}) == 128
