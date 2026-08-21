from __future__ import annotations

from tests.canonical_request_test_support import create_admin_request, login_admin
from tests.versioned_test_support import isolated_versioned_app_env


def test_admin_request_list_renders_snapshot_activity_and_typed_filter(tmp_path):
    with isolated_versioned_app_env(tmp_path, "admin-list.db") as env:
        login_admin(env["client"])
        create_admin_request(env["client"], "Listed canonical")
        response = env["client"].get("/admin/requisicoes?status=Pendente&atividade_versao_id=29")
        html = response.get_data(as_text=True)
        assert response.status_code == 200
        assert "Listed canonical" in html
        assert "DATA_INTEGRITY_INVALID" not in html
