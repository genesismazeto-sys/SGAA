import re

import main
from tests.canonical_matrix_test_support import login_admin
from tests.versioned_test_support import isolated_versioned_app_env


def _token(html):
    match = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
    assert match
    return match.group(1)


def test_admin_mutation_requires_and_accepts_active_csrf(tmp_path):
    with isolated_versioned_app_env(tmp_path, "csrf-admin.db") as env:
        login_admin(env["client"])
        original_enabled = main.app.config.get("WTF_CSRF_ENABLED")
        original_check_default = main.app.config.get("WTF_CSRF_CHECK_DEFAULT")
        main.app.config.update(WTF_CSRF_ENABLED=True, WTF_CSRF_CHECK_DEFAULT=True)
        try:
            page = env["client"].get("/admin/adicionar_matriz")
            token = _token(page.get_data(as_text=True))
            payload = {"curso_id": 1, "nome": "CSRF Matrix",
                       "status": "rascunho", "horas_aac_obrigatorias": 1,
                       "horas_extensao_obrigatorias": 1}
            assert env["client"].post("/admin/adicionar_matriz", data=payload).status_code == 400
            payload["csrf_token"] = token
            assert env["client"].post("/admin/adicionar_matriz", data=payload).status_code == 302
        finally:
            main.app.config.update(
                WTF_CSRF_ENABLED=original_enabled,
                WTF_CSRF_CHECK_DEFAULT=original_check_default,
            )


def test_logout_get_is_safe(tmp_path):
    with isolated_versioned_app_env(tmp_path, "csrf-logout.db") as env:
        login_admin(env["client"])
        assert env["client"].get("/logout").status_code == 302
