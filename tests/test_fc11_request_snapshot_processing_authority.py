from __future__ import annotations

import datetime
import json

import pytest

import main
from app.versioning.snapshots import (
    REQUISICAO_SNAPSHOT_SUPPORTED_SCHEMA,
    SnapshotProcessingAuthority,
    read_requisicao_snapshot_for_processing,
)
from tests.versioned_test_support import isolated_versioned_app_env


@pytest.fixture()
def fc11_env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "fc11_request_processing.db") as env:
        yield env


def _login_admin(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["user_type"] = "admin"
        sess["user_name"] = "Administrador"


def _snapshot_payload(conn, *, version_id=29, activity_id=1, matrix_id=2, **overrides):
    row = conn.execute(
        """
        SELECT atividade_base_id, norma_id, codigo_normativo, eixo, grupo,
               ch_por_evento, limite_semestre, limite_total, numero_versao, status
          FROM atividade_versao
         WHERE id = ?
        """,
        (version_id,),
    ).fetchone()
    payload = {
        "schema_version": "d6.4.0-v1",
        "atividade_base_id": row["atividade_base_id"],
        "atividade_id_legacy": activity_id,
        "atividade_versao_id": version_id,
        "atividade_versao_numero": row["numero_versao"],
        "norma_id": row["norma_id"],
        "codigo_normativo": row["codigo_normativo"],
        "eixo": row["eixo"],
        "matriz_id_efetiva": matrix_id,
        "ch_por_evento": row["ch_por_evento"],
        "limite_semestre": row["limite_semestre"],
        "limite_total": row["limite_total"],
    }
    payload.update(overrides)
    return payload


def _insert_request(
    conn,
    *,
    payload=None,
    activity_id=1,
    version_id=29,
    code="AAC-rev6",
    hours=3,
    event_date=None,
    status="Pendente",
):
    event_date = event_date or datetime.date.today().isoformat()
    raw_payload = None if payload is None else json.dumps(payload, sort_keys=True)
    cur = conn.execute(
        """
        INSERT INTO requisicoes (
            aluno_id, atividade_id, data_solicitacao, data_evento,
            horas_solicitadas, nome_evento, status, horas_deferidas,
            atividade_versao_id, regra_snapshot_json, codigo_normativo_snapshot,
            data_processamento, admin_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            1,
            activity_id,
            f"{event_date} 09:00:00",
            event_date,
            hours,
            "FC11 request",
            status,
            None,
            None if payload is None else version_id,
            raw_payload,
            None if payload is None else code,
            None,
            None,
        ),
    )
    conn.commit()
    return cur.lastrowid


def _post_process(client, req_id, *, status="Deferida", hours=None):
    data = {"status": status, "observacao": "FC11"}
    if hours is not None:
        data["horas_deferidas"] = str(hours)
    return client.post(
        f"/admin/processar_requisicao/{req_id}",
        data=data,
        follow_redirects=False,
    )


def _insert_invalid_snapshot_request(conn, *, raw_snapshot="{not-json"):
    req_id = _insert_request(conn, payload=None, hours=3)
    conn.execute(
        """
        UPDATE requisicoes
           SET atividade_versao_id = 29,
               codigo_normativo_snapshot = 'AAC-rev6',
               regra_snapshot_json = ?
         WHERE id = ?
        """,
        (raw_snapshot, req_id),
    )
    conn.commit()
    return req_id


def _processing_state(conn, req_id):
    return tuple(
        conn.execute(
            """
            SELECT status, horas_deferidas, observacao, data_processamento,
                   admin_id, aluno_update_notified_at, aluno_update_seen_at,
                   atividade_versao_id, codigo_normativo_snapshot, regra_snapshot_json
              FROM requisicoes
             WHERE id = ?
            """,
            (req_id,),
        ).fetchone()
    )


def test_reader_classifies_true_no_snapshot_without_reinterpreting_legacy_rows():
    result = read_requisicao_snapshot_for_processing(
        {
            "atividade_id": 1,
            "atividade_versao_id": None,
            "codigo_normativo_snapshot": None,
            "regra_snapshot_json": None,
        }
    )
    assert result.authority is SnapshotProcessingAuthority.NO_SNAPSHOT
    assert result.rule is None


def test_supported_schema_version_is_valid_authority(fc11_env):
    with main.app.app_context():
        conn = main.get_db_connection()
        payload = _snapshot_payload(conn, limite_total=4)
        assert payload["schema_version"] == REQUISICAO_SNAPSHOT_SUPPORTED_SCHEMA
        result = read_requisicao_snapshot_for_processing(
            {
                "atividade_id": 1,
                "atividade_versao_id": 29,
                "codigo_normativo_snapshot": "AAC-rev6",
                "regra_snapshot_json": json.dumps(payload),
            }
        )
    assert result.authority is SnapshotProcessingAuthority.VALID_AUTHORITATIVE_SNAPSHOT


@pytest.mark.parametrize(
    "schema_version",
    ["unsupported-future-v999", "d6.4.0-v2", None, 1],
)
def test_unsupported_or_non_string_schema_version_is_invalid(fc11_env, schema_version):
    with main.app.app_context():
        conn = main.get_db_connection()
        payload = _snapshot_payload(conn, limite_total=4)
        if schema_version is None:
            payload.pop("schema_version")
        else:
            payload["schema_version"] = schema_version
        result = read_requisicao_snapshot_for_processing(
            {
                "atividade_id": 1,
                "atividade_versao_id": 29,
                "codigo_normativo_snapshot": "AAC-rev6",
                "regra_snapshot_json": json.dumps(payload),
            }
        )
    assert result.authority is SnapshotProcessingAuthority.INVALID_AUTHORITATIVE_SNAPSHOT


def test_partial_snapshot_markers_are_invalid_not_no_snapshot(fc11_env):
    with main.app.app_context():
        conn = main.get_db_connection()
        payload = _snapshot_payload(conn, limite_total=4)
        cases = [
            {"atividade_versao_id": 29, "codigo_normativo_snapshot": None, "regra_snapshot_json": None},
            {"atividade_versao_id": None, "codigo_normativo_snapshot": "AAC-rev6", "regra_snapshot_json": None},
            {"atividade_versao_id": None, "codigo_normativo_snapshot": None, "regra_snapshot_json": json.dumps(payload)},
        ]
        results = [
            read_requisicao_snapshot_for_processing({"atividade_id": 1, **case})
            for case in cases
        ]
    assert all(
        result.authority is SnapshotProcessingAuthority.INVALID_AUTHORITATIVE_SNAPSHOT
        for result in results
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: "{not-json",
        lambda payload: json.dumps([payload]),
        lambda payload: json.dumps({**payload, "norma_id": None}),
        lambda payload: json.dumps({**payload, "limite_total": "not-a-number"}),
    ],
)
def test_malformed_or_incomplete_snapshot_is_invalid_authority(fc11_env, mutation):
    with main.app.app_context():
        conn = main.get_db_connection()
        payload = _snapshot_payload(conn, limite_total=4)
        raw = mutation(payload)
        row = {
            "atividade_id": 1,
            "atividade_versao_id": 29,
            "codigo_normativo_snapshot": "AAC-rev6",
            "regra_snapshot_json": raw,
        }
        result = read_requisicao_snapshot_for_processing(row)
    assert result.authority is SnapshotProcessingAuthority.INVALID_AUTHORITATIVE_SNAPSHOT
    assert result.rule is None


@pytest.mark.parametrize(
    "column, payload_key, column_value",
    [
        ("atividade_versao_id", "atividade_versao_id", 30),
        ("codigo_normativo_snapshot", "codigo_normativo", "FOREIGN-CODE"),
    ],
)
def test_snapshot_db_json_identity_mismatch_is_invalid(fc11_env, column, payload_key, column_value):
    with main.app.app_context():
        conn = main.get_db_connection()
        payload = _snapshot_payload(conn, limite_total=4)
        payload[payload_key] = 30 if payload_key == "atividade_versao_id" else "FOREIGN-CODE"
        result = read_requisicao_snapshot_for_processing(
            {
                "atividade_id": 1,
                "atividade_versao_id": 29,
                "codigo_normativo_snapshot": "AAC-rev6",
                "regra_snapshot_json": json.dumps(payload),
            }
        )
    assert result.authority is SnapshotProcessingAuthority.INVALID_AUTHORITATIVE_SNAPSHOT


def test_snapshot_total_limit_beats_mutated_legacy_rule_and_preserves_bytes(fc11_env):
    with main.app.app_context():
        conn = main.get_db_connection()
        payload = _snapshot_payload(conn, limite_total=4, limite_semestre=None)
        req_id = _insert_request(conn, payload=payload, hours=5)
        snapshot_bytes = conn.execute(
            "SELECT atividade_versao_id, codigo_normativo_snapshot, regra_snapshot_json FROM requisicoes WHERE id = ?",
            (req_id,),
        ).fetchone()
        conn.execute(
            "UPDATE atividades SET tem_limitacao = 1, tipo_limitacao = 'total', limite_horas_total = 100 WHERE id = 1"
        )
        conn.commit()
    _login_admin(fc11_env["client"])
    response = _post_process(fc11_env["client"], req_id)
    assert response.status_code == 302
    with main.app.app_context():
        conn = main.get_db_connection()
        row = conn.execute(
            "SELECT status, horas_deferidas, admin_id, data_processamento, atividade_versao_id, codigo_normativo_snapshot, regra_snapshot_json FROM requisicoes WHERE id = ?",
            (req_id,),
        ).fetchone()
    assert row["status"] == "Pendente"
    assert row["horas_deferidas"] is None
    assert row["admin_id"] is None
    assert row["data_processamento"] is None
    assert tuple(row[key] for key in ("atividade_versao_id", "codigo_normativo_snapshot", "regra_snapshot_json")) == tuple(snapshot_bytes)


def test_snapshot_total_limit_beats_newer_version_rule(fc11_env):
    with main.app.app_context():
        conn = main.get_db_connection()
        payload = _snapshot_payload(conn, limite_total=4, limite_semestre=None)
        req_id = _insert_request(conn, payload=payload, hours=5)
        version = conn.execute(
            "SELECT * FROM atividade_versao WHERE id = 29"
        ).fetchone()
        conn.execute(
            """
            INSERT INTO atividade_versao (
                atividade_base_id, norma_id, codigo_normativo, eixo, grupo,
                ch_por_evento, limite_semestre, limite_total, numero_versao, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                version["atividade_base_id"], version["norma_id"], "AAC-v2",
                version["eixo"], version["grupo"], version["ch_por_evento"],
                None, 100, version["numero_versao"] + 1, "ativa",
            ),
        )
        conn.execute(
            "UPDATE atividades SET tem_limitacao = 1, tipo_limitacao = 'total', limite_horas_total = 100 WHERE id = 1"
        )
        conn.commit()
    _login_admin(fc11_env["client"])
    response = _post_process(fc11_env["client"], req_id)
    assert response.status_code == 302
    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT status FROM requisicoes WHERE id = ?", (req_id,)
        ).fetchone()
    assert row["status"] == "Pendente"


def test_live_activity_version_and_norma_mutation_cannot_override_snapshot(fc11_env):
    with main.app.app_context():
        conn = main.get_db_connection()
        source = conn.execute("SELECT * FROM atividade_versao WHERE id = 29").fetchone()
        version_id = conn.execute(
            """
            INSERT INTO atividade_versao (
                atividade_base_id, norma_id, codigo_normativo, eixo, grupo,
                ch_por_evento, limite_semestre, limite_total, numero_versao, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (
                source["atividade_base_id"], source["norma_id"], "AAC-live-v1",
                source["eixo"], source["grupo"], source["ch_por_evento"],
                None, 4, 99, "ativa",
            ),
        ).fetchone()["id"]
        payload = _snapshot_payload(
            conn,
            version_id=version_id,
            codigo_normativo="AAC-live-v1",
            limite_total=4,
            limite_semestre=None,
        )
        req_id = _insert_request(conn, payload=payload, version_id=version_id, code="AAC-live-v1", hours=5)
        conn.execute(
            "UPDATE atividade_versao SET limite_total = 100, codigo_normativo = 'AAC-live-v2' WHERE id = ?",
            (version_id,),
        )
        conn.execute("UPDATE norma_atividade SET codigo = 'NORMA-LIVE-V2' WHERE id = ?", (source["norma_id"],))
        conn.execute(
            "UPDATE atividades SET tem_limitacao = 1, tipo_limitacao = 'total', limite_horas_total = 100 WHERE id = 1"
        )
        conn.commit()
    _login_admin(fc11_env["client"])
    response = _post_process(fc11_env["client"], req_id)
    assert response.status_code == 302
    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT status FROM requisicoes WHERE id = ?", (req_id,)
        ).fetchone()
    assert row["status"] == "Pendente"


def test_snapshot_semester_and_partial_limits_use_frozen_rule(fc11_env):
    with main.app.app_context():
        conn = main.get_db_connection()
        payload = _snapshot_payload(conn, limite_total=None, limite_semestre=4)
        req_id = _insert_request(conn, payload=payload, hours=5)
        conn.execute(
            "UPDATE atividades SET tem_limitacao = 1, tipo_limitacao = 'semestral', limite_horas_semestral = 100 WHERE id = 1"
        )
        conn.commit()
    _login_admin(fc11_env["client"])
    response = _post_process(fc11_env["client"], req_id, status="Deferida Parcialmente", hours=5)
    assert response.status_code == 302
    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT status, horas_deferidas FROM requisicoes WHERE id = ?", (req_id,)
        ).fetchone()
    assert row["status"] == "Pendente"
    assert row["horas_deferidas"] is None


def test_successful_deferment_and_partial_deferment_preserve_snapshot_bytes(fc11_env):
    with main.app.app_context():
        conn = main.get_db_connection()
        full_payload = _snapshot_payload(conn, limite_total=10, limite_semestre=None)
        full_id = _insert_request(conn, payload=full_payload, hours=3)
        partial_payload = _snapshot_payload(conn, limite_total=10, limite_semestre=None)
        partial_id = _insert_request(conn, payload=partial_payload, hours=6)
        before = conn.execute(
            """
            SELECT id, atividade_versao_id, codigo_normativo_snapshot, regra_snapshot_json
              FROM requisicoes WHERE id IN (?, ?) ORDER BY id
            """,
            (full_id, partial_id),
        ).fetchall()
        conn.commit()

    _login_admin(fc11_env["client"])
    assert _post_process(fc11_env["client"], full_id).status_code == 302
    assert _post_process(
        fc11_env["client"], partial_id, status="Deferida Parcialmente", hours=3
    ).status_code == 302

    with main.app.app_context():
        conn = main.get_db_connection()
        after = conn.execute(
            """
            SELECT id, atividade_versao_id, codigo_normativo_snapshot, regra_snapshot_json
              FROM requisicoes WHERE id IN (?, ?) ORDER BY id
            """,
            (full_id, partial_id),
        ).fetchall()
        statuses = conn.execute(
            "SELECT id, status, horas_deferidas FROM requisicoes WHERE id IN (?, ?) ORDER BY id",
            (full_id, partial_id),
        ).fetchall()
    assert [tuple(row) for row in after] == [tuple(row) for row in before]
    assert statuses[0]["status"] == "Deferida"
    assert statuses[0]["horas_deferidas"] is None
    assert statuses[1]["status"] == "Deferida Parcialmente"
    assert statuses[1]["horas_deferidas"] == 3


@pytest.mark.parametrize(
    "raw_snapshot, version_id, code",
    [
        ("{not-json", 29, "AAC-rev6"),
        (json.dumps({"schema_version": "d6.4.0-v1"}), 29, "AAC-rev6"),
    ],
)
def test_invalid_snapshot_processing_fails_closed_without_row_mutation(
    fc11_env, raw_snapshot, version_id, code
):
    with main.app.app_context():
        conn = main.get_db_connection()
        req_id = _insert_request(
            conn,
            payload=None,
            version_id=version_id,
            code=code,
            hours=3,
        )
        conn.execute(
            "UPDATE requisicoes SET atividade_versao_id = ?, regra_snapshot_json = ?, codigo_normativo_snapshot = ? WHERE id = ?",
            (version_id, raw_snapshot, code, req_id),
        )
        before = conn.execute(
            "SELECT status, horas_deferidas, admin_id, data_processamento, atividade_versao_id, codigo_normativo_snapshot, regra_snapshot_json FROM requisicoes WHERE id = ?",
            (req_id,),
        ).fetchone()
        conn.commit()
    _login_admin(fc11_env["client"])
    assert _post_process(fc11_env["client"], req_id).status_code == 302
    with main.app.app_context():
        after = main.get_db_connection().execute(
            "SELECT status, horas_deferidas, admin_id, data_processamento, atividade_versao_id, codigo_normativo_snapshot, regra_snapshot_json FROM requisicoes WHERE id = ?",
            (req_id,),
        ).fetchone()
    assert tuple(after) == tuple(before)


def _assert_invalid_snapshot_status_is_unchanged(fc11_env, target_status):
    with main.app.app_context():
        conn = main.get_db_connection()
        req_id = _insert_invalid_snapshot_request(conn)
        before = _processing_state(conn, req_id)
    _login_admin(fc11_env["client"])
    response = _post_process(fc11_env["client"], req_id, status=target_status)
    assert response.status_code == 302
    with main.app.app_context():
        after = _processing_state(main.get_db_connection(), req_id)
    assert after == before


def test_invalid_snapshot_indeferida_reproduction_is_atomic(fc11_env):
    _assert_invalid_snapshot_status_is_unchanged(fc11_env, "Indeferida")


def test_invalid_snapshot_devolvida_is_atomic(fc11_env):
    _assert_invalid_snapshot_status_is_unchanged(fc11_env, "Devolvida")


def test_invalid_snapshot_encerrada_is_atomic(fc11_env):
    _assert_invalid_snapshot_status_is_unchanged(fc11_env, "Encerrada")


def test_invalid_snapshot_pendente_is_atomic(fc11_env):
    _assert_invalid_snapshot_status_is_unchanged(fc11_env, "Pendente")


def test_valid_snapshot_non_defer_status_still_processes(fc11_env):
    with main.app.app_context():
        conn = main.get_db_connection()
        payload = _snapshot_payload(conn, limite_total=10)
        req_id = _insert_request(conn, payload=payload, hours=3)
    _login_admin(fc11_env["client"])
    response = _post_process(fc11_env["client"], req_id, status="Indeferida")
    assert response.status_code == 302
    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT status, admin_id, data_processamento FROM requisicoes WHERE id = ?",
            (req_id,),
        ).fetchone()
    assert row["status"] == "Indeferida"
    assert row["admin_id"] == 1
    assert row["data_processamento"] is not None


def test_unsupported_schema_processing_post_is_atomic(fc11_env):
    with main.app.app_context():
        conn = main.get_db_connection()
        payload = _snapshot_payload(conn, limite_total=10)
        payload["schema_version"] = "unsupported-future-v999"
        req_id = _insert_request(conn, payload=payload, hours=3)
        before = _processing_state(conn, req_id)
    _login_admin(fc11_env["client"])
    response = _post_process(fc11_env["client"], req_id, status="Indeferida")
    assert response.status_code == 302
    with main.app.app_context():
        after = _processing_state(main.get_db_connection(), req_id)
    assert after == before


def test_valid_snapshot_survives_current_matrix_change_and_does_not_call_resolver(fc11_env, monkeypatch):
    with main.app.app_context():
        conn = main.get_db_connection()
        payload = _snapshot_payload(conn, limite_total=10, matriz_id_efetiva=2)
        req_id = _insert_request(conn, payload=payload, hours=3)
        conn.execute("UPDATE turmas SET matriz_id = 1 WHERE id = 2")
        conn.execute("DELETE FROM matrizes_atividades_itens WHERE matriz_id = 1 AND atividade_id = 1")
        conn.commit()

    def forbidden(*args, **kwargs):
        raise AssertionError("processing must not resolve a replacement version")

    monkeypatch.setattr("app.versioning.resolver.resolver_versao_por_aluno", forbidden)
    _login_admin(fc11_env["client"])
    response = _post_process(fc11_env["client"], req_id)
    assert response.status_code == 302
    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT status FROM requisicoes WHERE id = ?", (req_id,)
        ).fetchone()
    assert row["status"] == "Deferida"


def test_historical_no_snapshot_legacy_and_null_matrix_compatibility_remain(fc11_env):
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "UPDATE atividades SET tem_limitacao = 1, tipo_limitacao = 'total', limite_horas_total = 10 WHERE id = 1"
        )
        req_id = _insert_request(conn, payload=None, hours=3)
        conn.execute("UPDATE turmas SET matriz_id = NULL WHERE id = 2")
        conn.commit()
    _login_admin(fc11_env["client"])
    response = _post_process(fc11_env["client"], req_id)
    assert response.status_code == 302
    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT status, atividade_versao_id, regra_snapshot_json FROM requisicoes WHERE id = ?",
            (req_id,),
        ).fetchone()
    assert row["status"] == "Deferida"
    assert row["atividade_versao_id"] is None
    assert row["regra_snapshot_json"] is None


@pytest.mark.parametrize("flag", [None, "0", "false", "1"])
def test_display_flag_has_no_processing_authority(fc11_env, monkeypatch, flag):
    if flag is None:
        monkeypatch.delenv("SGAA_VERSIONED_REQUISICAO_SNAPSHOT_DISPLAY", raising=False)
    else:
        monkeypatch.setenv("SGAA_VERSIONED_REQUISICAO_SNAPSHOT_DISPLAY", flag)
    with main.app.app_context():
        conn = main.get_db_connection()
        payload = _snapshot_payload(conn, limite_total=10)
        req_id = _insert_request(conn, payload=payload, hours=3)
        conn.commit()
    _login_admin(fc11_env["client"])
    response = _post_process(fc11_env["client"], req_id)
    assert response.status_code == 302
    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT status FROM requisicoes WHERE id = ?", (req_id,)
        ).fetchone()
    assert row["status"] == "Deferida"
