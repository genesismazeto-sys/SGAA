import main
from tests.canonical_request_test_support import create_admin_request, login_admin
from tests.versioned_test_support import isolated_versioned_app_env


def test_admin_dashboard_counts_canonical_pending_request(tmp_path):
    with isolated_versioned_app_env(tmp_path, "dashboard-request.db") as env:
        login_admin(env["client"])
        response, row = create_admin_request(env["client"], name="Dashboard canonical", version_id=29)
        assert response.status_code == 302 and row["status"] == "Pendente"
        dashboard = env["client"].get("/admin/dashboard")
        assert dashboard.status_code == 200
        assert "Dashboard canonical" in env["client"].get("/admin/requisicoes").get_data(as_text=True)
