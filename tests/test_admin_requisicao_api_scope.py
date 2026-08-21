from __future__ import annotations

import pytest

from tests.canonical_request_test_support import create_admin_request, login_admin
from tests.versioned_test_support import isolated_versioned_app_env


def test_admin_request_api_uses_historical_snapshot_scope(tmp_path):
    with isolated_versioned_app_env(tmp_path, "admin-api.db") as env:
        login_admin(env["client"])
        _, row = create_admin_request(env["client"], "API canonical")
        response = env["client"].get(f"/admin/api/requisicao/{row['id']}")
        payload = response.get_json()
        assert response.status_code == 200
        assert payload["activity_authority"] == "historical_snapshot"
        assert payload["current_activity_allowed"] is True
        assert row["atividade_versao_id"] in payload["allowed_activity_ids"]
