"""Canonical student/admin creation and snapshot-only processing flows."""

import json

import pytest

import main
from app.versioning.snapshots import (
    SnapshotProcessingAuthority,
    read_requisicao_snapshot_for_processing,
)
from tests.versioned_test_support import isolated_versioned_app_env


@pytest.fixture()
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "pg-canonical-flows.db") as value:
        yield value


def _student_identity():
    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT a.id AS aluno_id,a.usuario_id FROM alunos a WHERE a.matricula='PPA.TESTE.0001'"
        ).fetchone()
        return dict(row)


def _login_student(client, identity):
    with client.session_transaction() as session:
        session.update(user_id=identity["usuario_id"], user_type="aluno", user_name="Aluno")


def _login_admin(client):
    with main.app.app_context():
        row = main.get_db_connection().execute("SELECT id FROM usuarios WHERE tipo='admin' ORDER BY id LIMIT 1").fetchone()
    with client.session_transaction() as session:
        session.update(user_id=row["id"], user_type="admin", user_name="Admin")


def _assert_canonical_request(name):
    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT * FROM requisicoes WHERE nome_evento=?", (name,)
        ).fetchone()
        assert row is not None
        read = read_requisicao_snapshot_for_processing(row)
        assert read.authority is SnapshotProcessingAuthority.VALID_AUTHORITATIVE_SNAPSHOT
        assert read.rule.atividade_versao_id == row["atividade_versao_id"]
        assert json.loads(row["regra_snapshot_json"])["schema_version"] == "prod-1-request-v2"
        return row["id"]


def test_student_creation_requires_exact_version_and_writes_snapshot(env):
    identity = _student_identity()
    _login_student(env["client"], identity)
    response = env["client"].post(
        "/aluno/nova-requisicao",
        data={
            "atividade_versao_id": "29", "nome_evento": "PG student",
            "data_evento": "2026-05-01", "horas_solicitadas": "4", "observacao": "ok",
        },
    )
    assert response.status_code == 302
    _assert_canonical_request("PG student")


def test_student_creation_without_exact_version_is_transactionally_rejected(env):
    identity = _student_identity()
    _login_student(env["client"], identity)
    response = env["client"].post(
        "/aluno/nova-requisicao",
        data={"nome_evento": "PG rejected", "data_evento": "2026-05-01", "horas_solicitadas": "4"},
    )
    assert response.status_code == 200
    with main.app.app_context():
        assert main.get_db_connection().execute("SELECT 1 FROM requisicoes WHERE nome_evento='PG rejected'").fetchone() is None


def test_admin_creation_and_processing_use_frozen_snapshot(env):
    identity = _student_identity()
    _login_admin(env["client"])
    response = env["client"].post(
        "/admin/requisicoes/nova",
        data={
            "aluno_id": str(identity["aluno_id"]), "atividade_versao_id": "29",
            "nome_evento": "PG admin", "data_evento": "2026-05-01",
            "horas_solicitadas": "4", "observacao": "ok",
        },
    )
    assert response.status_code == 302
    request_id = _assert_canonical_request("PG admin")
    response = env["client"].post(
        f"/admin/processar_requisicao/{request_id}",
        data={"status": "Deferida", "observacao": "approved"},
    )
    assert response.status_code == 302
    with main.app.app_context():
        row = main.get_db_connection().execute("SELECT * FROM requisicoes WHERE id=?", (request_id,)).fetchone()
        assert row["status"] == "Deferida"
        assert read_requisicao_snapshot_for_processing(row).authority is SnapshotProcessingAuthority.VALID_AUTHORITATIVE_SNAPSHOT
