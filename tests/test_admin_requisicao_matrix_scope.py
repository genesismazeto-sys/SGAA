from __future__ import annotations

from tests.canonical_request_test_support import create_admin_request, login_admin
from tests.versioned_test_support import isolated_versioned_app_env


def test_admin_cannot_create_request_outside_exact_matrix(tmp_path):
    with isolated_versioned_app_env(tmp_path, "admin-matrix-scope.db") as env:
        login_admin(env["client"])
        response, row = create_admin_request(env["client"], "Outside matrix", version_id=1)
        assert response.status_code == 302
        assert row is None
