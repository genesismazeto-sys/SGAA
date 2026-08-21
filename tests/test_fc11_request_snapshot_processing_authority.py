"""FC11 snapshot-only request processing authority."""
from __future__ import annotations

import json

import pytest

import main
from app.versioning.snapshots import (
    RequisicaoSnapshotError,
    SnapshotProcessingAuthority,
    prepare_versioned_requisicao_snapshot,
    read_requisicao_snapshot_for_processing,
)
from tests.canonical_request_test_support import create_admin_request, login_admin, student_identity
from tests.versioned_test_support import isolated_versioned_app_env


@pytest.fixture()
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "fc11.db") as value:
        login_admin(value["client"])
        yield value


def test_missing_snapshot_is_invalid_not_compatibility_authority():
    read = read_requisicao_snapshot_for_processing({
        "atividade_versao_id": None, "codigo_normativo_snapshot": None,
        "regra_snapshot_json": None,
    })
    assert read.authority is SnapshotProcessingAuthority.INVALID_AUTHORITATIVE_SNAPSHOT
    assert read.reason == "mandatory_snapshot_missing"


def test_valid_snapshot_processes_and_preserves_bytes(env):
    _, row = create_admin_request(env["client"], "FC11 valid")
    frozen = row["regra_snapshot_json"]
    response = env["client"].post(
        f"/admin/processar_requisicao/{row['id']}",
        data={"status": "Deferida", "observacao": "ok"},
    )
    assert response.status_code == 302
    with main.app.app_context():
        saved = main.get_db_connection().execute(
            "SELECT * FROM requisicoes WHERE id=?", (row["id"],)
        ).fetchone()
    assert saved["status"] == "Deferida"
    assert saved["regra_snapshot_json"] == frozen


def _insert_with_payload(conn, payload, *, name, hours=4, normative_code=None):
    student = student_identity()
    if normative_code is None:
        normative_code = payload.get("codigo_normativo", "AAC-rev6")
    return conn.execute(
        """INSERT INTO requisicoes
           (aluno_id,atividade_versao_id,data_solicitacao,data_evento,horas_solicitadas,
            nome_evento,status,codigo_normativo_snapshot,regra_snapshot_json)
           VALUES(?,29,'2026-05-01 10:00:00','2026-05-01',?,?,'Pendente',?,?) RETURNING id""",
        (student["aluno_id"], hours, name, normative_code,
         json.dumps(payload, sort_keys=True)),
    ).fetchone()["id"]


def test_frozen_total_limit_overrides_mutated_current_rule(env):
    with main.app.app_context():
        conn = main.get_db_connection()
        prepared = prepare_versioned_requisicao_snapshot(
            conn, flow_origin="admin_create", aluno_id=student_identity()["aluno_id"],
            atividade_versao_id=29,
        )
        payload = dict(prepared.payload)
        payload["limite_total"] = 2
        req_id = _insert_with_payload(conn, payload, name="FC11 limited", hours=4)
        conn.execute("UPDATE atividade_versao SET limite_total=999 WHERE id=29")
        conn.commit()
    env["client"].post(
        f"/admin/processar_requisicao/{req_id}",
        data={"status": "Deferida", "observacao": "attempt"},
    )
    with main.app.app_context():
        saved = main.get_db_connection().execute(
            "SELECT status FROM requisicoes WHERE id=?", (req_id,)
        ).fetchone()
    assert saved["status"] == "Pendente"


def test_invalid_snapshot_processing_is_atomic(env):
    with main.app.app_context():
        conn = main.get_db_connection()
        req_id = _insert_with_payload(conn, {}, name="FC11 invalid")
        conn.commit()
    env["client"].post(
        f"/admin/processar_requisicao/{req_id}",
        data={"status": "Indeferida", "observacao": "must not apply"},
    )
    with main.app.app_context():
        saved = main.get_db_connection().execute(
            "SELECT status,observacao FROM requisicoes WHERE id=?", (req_id,)
        ).fetchone()
    assert (saved["status"], saved["observacao"]) == ("Pendente", None)


@pytest.mark.parametrize(
    ("invalid_class", "expected_reason"),
    [
        ("unsupported_schema_version", "unsupported_schema_version"),
        ("activity_version_identity_mismatch", "activity_version_identity_mismatch"),
        ("normative_code_identity_mismatch", "normative_code_identity_mismatch"),
    ],
)
def test_distinct_invalid_snapshot_branches_fail_closed_atomically(
    env, invalid_class, expected_reason
):
    with main.app.app_context():
        conn = main.get_db_connection()
        prepared = prepare_versioned_requisicao_snapshot(
            conn,
            flow_origin="admin_create",
            aluno_id=student_identity()["aluno_id"],
            atividade_versao_id=29,
        )
        payload = dict(prepared.payload)
        if invalid_class == "unsupported_schema_version":
            payload["schema_version"] = "prod-1-request-v999"
        elif invalid_class == "activity_version_identity_mismatch":
            payload["atividade_versao_id"] = 27
        else:
            payload["codigo_normativo"] = "AAC-TAMPERED"

        frozen_invalid_bytes = json.dumps(payload, sort_keys=True)
        direct_read = read_requisicao_snapshot_for_processing(
            {
                "atividade_versao_id": 29,
                "codigo_normativo_snapshot": prepared.codigo_normativo,
                "regra_snapshot_json": frozen_invalid_bytes,
            }
        )
        assert direct_read.authority is SnapshotProcessingAuthority.INVALID_AUTHORITATIVE_SNAPSHOT
        assert direct_read.reason == expected_reason

        req_id = _insert_with_payload(
            conn,
            payload,
            name=f"FC11 {invalid_class}",
            normative_code=prepared.codigo_normativo,
        )
        student_id = student_identity()["aluno_id"]
        approved_before = conn.execute(
            """SELECT COALESCE(SUM(CASE
                       WHEN status='Deferida' THEN horas_solicitadas
                       WHEN status='Deferida Parcialmente' THEN horas_deferidas
                       ELSE 0 END),0)
                 FROM requisicoes WHERE aluno_id=?""",
            (student_id,),
        ).fetchone()[0]
        conn.commit()

    response = env["client"].post(
        f"/admin/processar_requisicao/{req_id}",
        data={"status": "Deferida", "horas_deferidas": "3", "observacao": "must not apply"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert RequisicaoSnapshotError.user_message in response.get_data(as_text=True)

    with main.app.app_context():
        conn = main.get_db_connection()
        saved = conn.execute(
            """SELECT atividade_versao_id,codigo_normativo_snapshot,regra_snapshot_json,
                      status,horas_deferidas,observacao,data_processamento,admin_id
                 FROM requisicoes WHERE id=?""",
            (req_id,),
        ).fetchone()
        approved_after = conn.execute(
            """SELECT COALESCE(SUM(CASE
                       WHEN status='Deferida' THEN horas_solicitadas
                       WHEN status='Deferida Parcialmente' THEN horas_deferidas
                       ELSE 0 END),0)
                 FROM requisicoes WHERE aluno_id=?""",
            (student_id,),
        ).fetchone()[0]

    assert tuple(saved) == (
        29,
        prepared.codigo_normativo,
        frozen_invalid_bytes,
        "Pendente",
        None,
        None,
        None,
        None,
    )
    assert approved_after == approved_before


@pytest.mark.parametrize("status", ["Indeferida", "Devolvida", "Encerrada", "Pendente"])
def test_valid_snapshot_allows_six_status_contract_nonapproval_states(env, status):
    _, row = create_admin_request(env["client"], f"FC11 {status}")
    env["client"].post(
        f"/admin/processar_requisicao/{row['id']}", data={"status": status, "observacao": "ok"}
    )
    with main.app.app_context():
        saved = main.get_db_connection().execute(
            "SELECT status FROM requisicoes WHERE id=?", (row["id"],)
        ).fetchone()["status"]
    assert saved == status
