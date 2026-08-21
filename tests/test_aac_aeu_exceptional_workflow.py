"""Canonical AAC -> AEU transition and frozen-snapshot contracts."""
from __future__ import annotations

import json
import sqlite3

import pytest

import main
from app.versioning.snapshots import prepare_versioned_requisicao_snapshot
from tests.versioned_test_support import isolated_versioned_app_env


@pytest.fixture()
def workflow_env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "aac_aeu_workflow.db") as env:
        yield env


def _student_id(conn) -> int:
    return int(conn.execute(
        "SELECT id FROM alunos WHERE matricula='PPA.TESTE.0001'"
    ).fetchone()["id"])


def test_aac_to_aeu_transition_requires_explicit_valid_provenance(workflow_env):
    with main.app.app_context():
        conn = main.get_db_connection()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO atividade_transicao "
                "(from_atividade_versao_id,to_atividade_versao_id,tipo_transicao,justificativa) "
                "VALUES (27,55,'aac_para_aeu','')"
            )
        conn.execute(
            "INSERT INTO atividade_transicao "
            "(from_atividade_versao_id,to_atividade_versao_id,tipo_transicao,justificativa) "
            "VALUES (27,55,'aac_para_aeu','Mudanca normativa explicita')"
        )
        row = conn.execute("SELECT * FROM atividade_transicao").fetchone()
        assert (row["from_atividade_versao_id"], row["to_atividade_versao_id"]) == (27, 55)


def test_exact_matrix_selects_aac_then_aeu_version(workflow_env):
    with main.app.app_context():
        conn = main.get_db_connection()
        aluno_id = _student_id(conn)
        conn.execute("UPDATE alunos SET turma_id=1 WHERE id=?", (aluno_id,))
        aac = prepare_versioned_requisicao_snapshot(
            conn, flow_origin="student_create", aluno_id=aluno_id, atividade_versao_id=27
        )
        conn.execute("UPDATE alunos SET turma_id=2 WHERE id=?", (aluno_id,))
        aeu = prepare_versioned_requisicao_snapshot(
            conn, flow_origin="student_create", aluno_id=aluno_id, atividade_versao_id=55
        )
        assert (aac.payload["eixo"], aac.atividade_versao_id) == ("AAC", 27)
        assert (aeu.payload["eixo"], aeu.atividade_versao_id) == ("AEU", 55)


def test_snapshot_remains_frozen_after_live_version_change(workflow_env):
    with main.app.app_context():
        conn = main.get_db_connection()
        aluno_id = _student_id(conn)
        conn.execute("UPDATE alunos SET turma_id=1 WHERE id=?", (aluno_id,))
        prepared = prepare_versioned_requisicao_snapshot(
            conn, flow_origin="student_create", aluno_id=aluno_id, atividade_versao_id=27
        )
        frozen = json.loads(prepared.snapshot_json)
        conn.execute("UPDATE atividade_versao SET limite_total=999 WHERE id=27")
        assert json.loads(prepared.snapshot_json) == frozen
        assert frozen["limite_total"] != 999


def test_cross_axis_previous_version_is_rejected_but_transition_is_allowed(workflow_env):
    with main.app.app_context():
        conn = main.get_db_connection()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE atividade_versao SET versao_anterior_id=27 WHERE id=55")
        conn.execute(
            "INSERT INTO atividade_transicao "
            "(from_atividade_versao_id,to_atividade_versao_id,tipo_transicao,justificativa) "
            "VALUES (27,55,'aac_para_aeu','Excecao normativa documentada')"
        )
