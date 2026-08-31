"""Compatibility contract for the retired base-only Activity creator.

Creating an Activity is one atomic atividade_base + atividade_versao v1
operation. The former base-only entrypoint delegates to Add Activity and never
writes an incomplete atividade_base row.
"""
from __future__ import annotations

import main
from tests.versioned_test_support import isolated_versioned_app_env


def _login_admin(client):
    with client.session_transaction() as session:
        session.update(
            user_id=1,
            user_type="admin",
            user_name="Administrador",
        )


def test_retired_base_only_get_redirects_to_canonical_add(tmp_path):
    with isolated_versioned_app_env(tmp_path, "retired-base-get.db") as env:
        _login_admin(env["client"])
        response = env["client"].get(
            "/admin/catalogo-versoes/nova-base",
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/admin/adicionar_atividade")


def test_retired_base_only_post_redirects_without_writing(tmp_path):
    with isolated_versioned_app_env(tmp_path, "retired-base-post.db") as env:
        _login_admin(env["client"])
        with main.app.app_context():
            conn = main.get_db_connection()
            before = {
                "base": conn.execute("SELECT COUNT(*) FROM atividade_base").fetchone()[0],
                "version": conn.execute("SELECT COUNT(*) FROM atividade_versao").fetchone()[0],
                "matrix": conn.execute(
                    "SELECT COUNT(*) FROM matriz_atividade_versao_item"
                ).fetchone()[0],
                "requests": conn.execute("SELECT COUNT(*) FROM requisicoes").fetchone()[0],
            }

        response = env["client"].post(
            "/admin/catalogo-versoes/nova-base",
            data={
                "nome_conceito": "Forbidden base-only row",
                "descricao": "Must not persist",
                "status": "ativo",
            },
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/admin/adicionar_atividade")

        with main.app.app_context():
            conn = main.get_db_connection()
            assert conn.execute("SELECT COUNT(*) FROM atividade_base").fetchone()[0] == before["base"]
            assert conn.execute("SELECT COUNT(*) FROM atividade_versao").fetchone()[0] == before["version"]
            assert conn.execute(
                "SELECT COUNT(*) FROM matriz_atividade_versao_item"
            ).fetchone()[0] == before["matrix"]
            assert conn.execute("SELECT COUNT(*) FROM requisicoes").fetchone()[0] == before["requests"]


def test_retired_base_only_entrypoint_requires_admin(tmp_path):
    with isolated_versioned_app_env(tmp_path, "retired-base-auth.db") as env:
        response = env["client"].get("/admin/catalogo-versoes/nova-base")
        assert response.status_code in {302, 401, 403}


def test_student_templates_do_not_expose_versioning_terms(tmp_path):
    with isolated_versioned_app_env(tmp_path, "student-version-language.db") as env:
        with env["client"].session_transaction() as session:
            session.update(
                user_id=2,
                user_type="aluno",
                user_name="Aluno Teste",
            )

        forbidden = (
            "atividade_versao_id",
            "snapshot versionado",
            "diagnóstico do snapshot",
        )
        for path in ("/aluno/dashboard", "/aluno/minhas-requisicoes"):
            html = env["client"].get(path, follow_redirects=True).get_data(as_text=True).lower()
            for term in forbidden:
                assert term not in html
