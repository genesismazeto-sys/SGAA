import re

import main
from tests.canonical_matrix_test_support import login_admin
from tests.versioned_test_support import isolated_versioned_app_env


def test_release_admin_post_requires_csrf_when_enabled(tmp_path):
    with isolated_versioned_app_env(tmp_path, "release-csrf.db") as env:
        login_admin(env["client"])
        original_enabled = main.app.config.get("WTF_CSRF_ENABLED")
        original_check_default = main.app.config.get("WTF_CSRF_CHECK_DEFAULT")
        main.app.config.update(WTF_CSRF_ENABLED=True, WTF_CSRF_CHECK_DEFAULT=True)
        try:
            assert env["client"].post("/admin/matrizes/1/excluir").status_code == 400
            page = env["client"].get("/admin/matrizes")
            assert re.search(r'name="csrf_token"', page.get_data(as_text=True))
        finally:
            main.app.config.update(
                WTF_CSRF_ENABLED=original_enabled,
                WTF_CSRF_CHECK_DEFAULT=original_check_default,
            )
