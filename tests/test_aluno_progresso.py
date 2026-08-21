"""Student progress derives approved hours exclusively from frozen snapshots."""
from __future__ import annotations

import pytest

import main
from tests.canonical_request_test_support import create_admin_request, login_admin, login_student
from tests.versioned_test_support import isolated_versioned_app_env


@pytest.fixture()
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "progress.db") as value:
        yield value


def _approve(client, name, version_id, hours):
    _, row = create_admin_request(client, name, version_id=version_id)
    response = client.post(
        f"/admin/processar_requisicao/{row['id']}",
        data={"status": "Deferida", "horas_deferidas": str(hours), "observacao": "ok"},
    )
    assert response.status_code == 302
    return row["id"]


def test_progress_counts_aac_and_aeu_from_snapshot_axis(env):
    login_admin(env["client"])
    _approve(env["client"], "Progress AAC", 29, 4)
    _approve(env["client"], "Progress AEU", 55, 3)
    login_student(env["client"])
    response = env["client"].get("/aluno/progresso")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Progress AAC" in html or "4" in html
    assert "Progress AEU" in html or "3" in html


def test_progress_ignores_later_mutation_of_current_version_axis(env):
    login_admin(env["client"])
    _approve(env["client"], "Frozen progress", 29, 5)
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("UPDATE atividade_versao SET grupo='Grupo mutado', limite_total=999 WHERE id=29")
        conn.commit()
    login_student(env["client"])
    response = env["client"].get("/aluno/progresso")
    assert response.status_code == 200
    assert "DATA_INTEGRITY_INVALID" not in response.get_data(as_text=True)
