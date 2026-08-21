from __future__ import annotations

import main
from tests.canonical_request_test_support import create_admin_request, login_admin, login_student
from tests.versioned_test_support import isolated_versioned_app_env


def test_student_dashboard_shows_processed_request_update_once(tmp_path):
    with isolated_versioned_app_env(tmp_path, "student-alert.db") as env:
        login_admin(env["client"])
        _, row = create_admin_request(env["client"], "Alert canonical")
        env["client"].post(
            f"/admin/processar_requisicao/{row['id']}",
            data={"status": "Deferida", "observacao": "done"},
        )
        login_student(env["client"])
        first = env["client"].get("/aluno/dashboard")
        second = env["client"].get("/aluno/dashboard")
        assert first.status_code == second.status_code == 200
        with main.app.app_context():
            saved = main.get_db_connection().execute(
                "SELECT aluno_update_notified_at FROM requisicoes WHERE id=?", (row["id"],)
            ).fetchone()
        assert saved["aluno_update_notified_at"] is not None
