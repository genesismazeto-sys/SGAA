"""Prod-1 matrix selection is explicit; there is no implicit latest-version rule."""
from __future__ import annotations

import main
from app.views.admin.matrizes import _ensure_default_versao_link
from tests.canonical_matrix_test_support import current_version_id, seed_matrix_graph
from tests.versioned_test_support import isolated_versioned_app_env


def test_existing_explicit_choice_is_never_replaced(tmp_path):
    with isolated_versioned_app_env(tmp_path, "explicit-choice.db"):
        with main.app.app_context():
            conn = main.get_db_connection()
            seed = seed_matrix_graph(conn, name="Explicit choice")
            _ensure_default_versao_link(conn, seed["matrix_id"], seed["v2"])
            conn.commit()
            assert current_version_id(conn, seed) == seed["v1"]


def test_new_selected_version_becomes_the_exact_matrix_authority(tmp_path):
    with isolated_versioned_app_env(tmp_path, "exact-choice.db"):
        with main.app.app_context():
            conn = main.get_db_connection()
            seed = seed_matrix_graph(conn, name="Exact choice")
            conn.execute("DELETE FROM matriz_atividade_versao_item WHERE matriz_id=?", (seed["matrix_id"],))
            _ensure_default_versao_link(conn, seed["matrix_id"], seed["v2"])
            conn.commit()
            assert current_version_id(conn, seed) == seed["v2"]


def test_inactive_version_cannot_become_default_authority(tmp_path):
    with isolated_versioned_app_env(tmp_path, "inactive-choice.db"):
        with main.app.app_context():
            conn = main.get_db_connection()
            seed = seed_matrix_graph(conn, name="Inactive choice")
            conn.execute("DELETE FROM matriz_atividade_versao_item WHERE matriz_id=?", (seed["matrix_id"],))
            _ensure_default_versao_link(conn, seed["matrix_id"], seed["v3_inactive"])
            conn.commit()
            assert current_version_id(conn, seed) is None
