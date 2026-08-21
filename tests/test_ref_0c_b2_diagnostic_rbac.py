"""RBAC contract for the two surviving canonical version diagnostics."""

import uuid

import pytest

import main
from tests.versioned_test_support import isolated_versioned_app_env


ROUTES = (
    ("/admin/diagnostico/atividades-versionadas", "admin_diagnostico_atividades_versionadas"),
    ("/admin/diagnostico/atividades-versionadas/view", "admin_diagnostico_atividades_versionadas_view"),
)


@pytest.fixture()
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "canonical_diagnostic_rbac.db") as value:
        yield value


def _login(client, access_level):
    with main.app.app_context():
        conn = main.get_db_connection()
        user_id = conn.execute(
            "INSERT INTO usuarios(nome,email,senha,tipo,nivel_acesso) VALUES(?,?,?,?,?) RETURNING id",
            ("Diagnostic", f"diag-{uuid.uuid4().hex}@example.test", main.hash_password("pass"), "admin", access_level),
        ).fetchone()["id"]
        conn.commit()
    with client.session_transaction() as session:
        session.update(user_id=user_id, user_type="admin", user_name="Diagnostic")


def test_surviving_diagnostics_have_exact_activity_view_requirement():
    for _, endpoint in ROUTES:
        assert main.get_admin_permission_requirement(endpoint, "GET") == ("atividades", "view")
        assert main.get_admin_permission_requirement(endpoint, "POST") is None
    assert main.get_admin_permission_requirement("admin_diagnostico_versioned_shadow_reads", "GET") is None


@pytest.mark.parametrize("path,_endpoint", ROUTES)
@pytest.mark.parametrize("level", ["admin_total", "administrativo", "consultivo"])
def test_surviving_diagnostics_allow_approved_admin_roles(env, path, _endpoint, level):
    _login(env["client"], level)
    assert env["client"].get(path).status_code == 200


@pytest.mark.parametrize("path,_endpoint", ROUTES)
def test_surviving_diagnostics_require_authentication(env, path, _endpoint):
    response = env["client"].get(path)
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
