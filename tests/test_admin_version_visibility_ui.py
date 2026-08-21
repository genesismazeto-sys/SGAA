from tests.canonical_matrix_test_support import login_admin
from tests.versioned_test_support import isolated_versioned_app_env


def test_matrix_version_page_shows_number_and_normative_code(tmp_path):
    with isolated_versioned_app_env(tmp_path, "version-visibility.db") as env:
        login_admin(env["client"])
        response = env["client"].get("/admin/matrizes/1/versoes")
        html = response.get_data(as_text=True)
        assert response.status_code == 200
        assert "v1" in html
        assert "AAC-rev5" in html
