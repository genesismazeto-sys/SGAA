from __future__ import annotations

import pytest

import main
from tests.canonical_request_test_support import create_admin_request, login_admin
from tests.versioned_test_support import isolated_versioned_app_env


@pytest.fixture()
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "admin-process.db") as value:
        yield value


def test_processing_ui_uses_frozen_canonical_request(env):
    login_admin(env["client"])
    _, row = create_admin_request(env["client"], "Process canonical")
    response = env["client"].get(f"/admin/processar_requisicao/{row['id']}")
    assert response.status_code == 200
    assert 'name="status"' in response.get_data(as_text=True)


def test_reopen_persists_pending_status(env):
    login_admin(env["client"])
    _, row = create_admin_request(env["client"], "Reopen canonical")
    response = env["client"].post(
        f"/admin/processar_requisicao/{row['id']}", data={"status": "Pendente", "observacao": "reopen"}
    )
    assert response.status_code == 302
    with main.app.app_context():
        status = main.get_db_connection().execute(
            "SELECT status FROM requisicoes WHERE id=?", (row["id"],)
        ).fetchone()["status"]
    assert status == "Pendente"
