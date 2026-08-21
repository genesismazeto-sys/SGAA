"""FC12 historical approved-hours authority is the frozen snapshot."""
from __future__ import annotations

import pytest

import main
from app.versioning.request_history import (
    HistoricalRequestAuthorityError,
    filter_historical_request_rows,
    list_approved_request_history,
    read_historical_request,
)
from tests.canonical_request_test_support import create_admin_request, login_admin, student_identity
from tests.versioned_test_support import isolated_versioned_app_env


@pytest.fixture()
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "fc12.db") as value:
        login_admin(value["client"])
        yield value


def _approved(env, name="FC12 approved", version_id=29):
    _, row = create_admin_request(env["client"], name, version_id=version_id)
    env["client"].post(
        f"/admin/processar_requisicao/{row['id']}",
        data={"status": "Deferida", "observacao": "ok"},
    )
    return row


def test_history_uses_frozen_name_axis_group_and_hours(env):
    row = _approved(env)
    with main.app.app_context():
        conn = main.get_db_connection()
        before = list_approved_request_history(conn, aluno_id=student_identity()["aluno_id"])[0]
        conn.execute("UPDATE atividade_base SET nome_conceito='LIVE MUTATED' WHERE id=?", (before.atividade_base_id,))
        conn.execute("UPDATE atividade_versao SET grupo='LIVE GROUP',limite_total=999 WHERE id=?", (before.atividade_versao_id,))
        after = list_approved_request_history(conn, aluno_id=student_identity()["aluno_id"])[0]
    assert after.nome == before.nome
    assert after.grupo == before.grupo
    assert after.limite_total == before.limite_total
    assert after.approved_hours == 4


def test_partial_approval_uses_deferred_hours(env):
    _, row = create_admin_request(env["client"], "FC12 partial")
    env["client"].post(
        f"/admin/processar_requisicao/{row['id']}",
        data={"status": "Deferida Parcialmente", "horas_deferidas": "2", "observacao": "ok"},
    )
    with main.app.app_context():
        history = list_approved_request_history(
            main.get_db_connection(), aluno_id=student_identity()["aluno_id"]
        )[0]
    assert history.approved_hours == 2


def test_historical_filters_use_frozen_identity(env):
    _approved(env, "FC12 filter")
    with main.app.app_context():
        conn = main.get_db_connection()
        rows = conn.execute("SELECT * FROM requisicoes WHERE status='Deferida'").fetchall()
        history = read_historical_request(rows[0])
        selected = filter_historical_request_rows(rows, grupo_filters=[history.grupo], query=history.nome)
    assert len(selected) == 1


def test_invalid_snapshot_never_falls_back_to_live_catalogue(env):
    with pytest.raises(HistoricalRequestAuthorityError):
        read_historical_request({
            "id": 1, "aluno_id": 1, "status": "Deferida", "horas_solicitadas": 4,
            "atividade_versao_id": 29, "codigo_normativo_snapshot": "AAC-rev6",
            "regra_snapshot_json": "{}",
        })
