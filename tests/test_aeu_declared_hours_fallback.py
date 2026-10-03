"""AE-rev1 AEU conditional hours: "Tempo declarado OU 20/10 h/evento" is a
fallback rule, not a fixed ``ch_por_evento`` suggestion.

The SGAA contract (PROJECT_STATE.md: ``ch_por_evento`` is an optional
suggestion/default, never a limit) cannot express "use the declared hours;
only when absent apply the normative per-event fallback". Storing 20/10 in
``ch_por_evento`` would turn the conditional rule into a fixed prefill and
silently rewrite declared hours. The canonical catalog must keep those values
NULL, keep the fallback text in the version observations, and the request flow
must preserve whatever hours the student/admin declared.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

import main
from app.versioning.request_history import (
    list_exact_matrix_activity_catalogue,
    read_historical_request,
)
from app.versioning.snapshots import read_requisicao_snapshot_for_processing
from tests.canonical_request_test_support import login_admin, login_student, student_identity
from tests.versioned_test_support import isolated_versioned_app_env

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_DB = PROJECT_ROOT / "database.db"

# AE-rev1: the three fallback activities and their per-event fallback text.
AEU_FALLBACKS = {
    108: ("20 h/evento", 30),  # Organização de eventos extensionistas
    109: ("10 h/evento", 31),  # Participação em eventos extensionistas
    110: ("10 h/evento", 32),  # Cursos/oficinas/palestras à comunidade externa
}
AEU_SEMESTER_LIMITS = {106: 40.0, 107: 40.0}

FALLBACK_OBS = (
    "A validação será realizada mediante declaração, certificado ou documento "
    "oficial emitido pela EJ. Tempo declarado ou 20 h/evento. §2º Para fins de "
    "contabilização da carga horária, caso não declarada a carga horária "
    "expressamente em documento comprobatório, poderão ser atribuídas até 20 "
    "horas pela organização de eventos ou ações extensionistas."
)


# ------------------------------------------------------------ canonical data


def _canonical_connection():
    if not CANONICAL_DB.exists():
        pytest.skip("no canonical database present in this checkout")
    conn = sqlite3.connect(f"file:{CANONICAL_DB.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def test_canonical_aeu_fallbacks_are_not_stored_as_ch_por_evento():
    conn = _canonical_connection()
    try:
        for version_id, (fallback, base_id) in AEU_FALLBACKS.items():
            row = conn.execute(
                "SELECT * FROM atividade_versao WHERE id=?", (version_id,)
            ).fetchone()
            assert row is not None, version_id
            assert row["eixo"] == "AEU"
            assert row["atividade_base_id"] == base_id
            assert row["ch_por_evento"] is None, (
                f"av{version_id}: the conditional fallback must never become a "
                "fixed suggested hours value"
            )
            assert row["limite_semestre"] is None
            assert row["limite_total"] is None
            for column in ("observacao_aluno", "observacao_admin"):
                text = row[column] or ""
                assert "Tempo declarado" in text, (version_id, column)
                assert fallback in text, (version_id, column)
                assert "não declarada a carga horária" in text, (version_id, column)
    finally:
        conn.close()


def test_canonical_aeu_semester_limits_are_kept_off_ch_por_evento():
    conn = _canonical_connection()
    try:
        for version_id, limit in AEU_SEMESTER_LIMITS.items():
            row = conn.execute(
                "SELECT * FROM atividade_versao WHERE id=?", (version_id,)
            ).fetchone()
            assert row is not None, version_id
            assert row["eixo"] == "AEU"
            assert row["ch_por_evento"] is None
            assert row["limite_semestre"] == limit
            assert row["limite_total"] is None
    finally:
        conn.close()


# --------------------------------------------------------------- behaviour


@pytest.fixture()
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "aeu-fallback.db") as value:
        login_admin(value["client"])
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute(
                "UPDATE atividade_base SET nome_conceito=? WHERE id=27",
                ("Organização de eventos extensionistas",),
            )
            conn.execute(
                "UPDATE atividade_versao SET ch_por_evento=NULL,"
                " observacao_aluno=?, observacao_admin=? WHERE id=55",
                (FALLBACK_OBS, FALLBACK_OBS),
            )
            conn.commit()
        yield value


def _create_request(client, aluno_id, version_id, nome, horas, data_evento="2026-09-15"):
    response = client.post(
        "/admin/requisicoes/nova",
        data={
            "aluno_id": str(aluno_id),
            "atividade_versao_id": str(version_id),
            "nome_evento": nome,
            "data_evento": data_evento,
            "horas_solicitadas": str(horas),
            "observacao": "aeu-fallback",
        },
    )
    assert response.status_code == 302
    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT * FROM requisicoes WHERE nome_evento=?", (nome,)
        ).fetchone()
    assert row is not None
    return dict(row)


def test_declared_hours_are_never_replaced_by_the_fallback(env):
    client = env["client"]
    identity = student_identity()
    declared_15 = _create_request(client, identity["aluno_id"], 55, "Declarado 15h", 15)
    declared_6 = _create_request(client, identity["aluno_id"], 55, "Declarado 6h", 6)

    with main.app.app_context():
        conn = main.get_db_connection()
        for request_row, expected in ((declared_15, 15.0), (declared_6, 6.0)):
            row = conn.execute(
                "SELECT * FROM requisicoes WHERE id=?", (request_row["id"],)
            ).fetchone()
            assert float(row["horas_solicitadas"]) == expected
            snapshot = read_requisicao_snapshot_for_processing(row)
            assert snapshot.rule.ch_por_evento is None
            assert snapshot.rule.limite_semestre is None
            assert snapshot.rule.limite_total is None

    response = client.post(
        f"/admin/processar_requisicao/{declared_15['id']}",
        data={"status": "Deferida", "observacao": "ok"},
    )
    assert response.status_code == 302
    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT * FROM requisicoes WHERE id=?", (declared_15["id"],)
        ).fetchone()
        assert row["status"] == "Deferida"
        history = read_historical_request(row)
        assert history.approved_hours == 15.0, (
            "the 20 h/evento fallback must not replace declared hours"
        )


def test_catalogue_does_not_offer_fallback_as_suggested_hours(env):
    with main.app.app_context():
        catalogue = {
            row["atividade_versao_id"]: row
            for row in list_exact_matrix_activity_catalogue(
                main.get_db_connection(), 2
            )
        }
    activity = catalogue[55]
    assert activity["nome"] == "Organização de eventos extensionistas"
    assert activity["ch_por_evento"] is None
    assert activity["tem_limitacao"] is False


def test_student_ui_does_not_present_fallback_as_suggested_hours(env):
    client = env["client"]
    login_student(client)
    html = client.get("/aluno/nova-requisicao").get_data(as_text=True)
    option = re.search(r'<option value="55"[^>]*>', html)
    assert option is not None, "the AEU activity option was not rendered"
    markup = option.group(0)
    assert 'data-default-hours=""' in markup
    assert 'data-default-hours="20"' not in markup
    assert 'data-default-hours="10"' not in markup


def test_admin_scope_api_does_not_present_fallback_as_suggested_hours(env):
    client = env["client"]
    identity = student_identity()
    payload = client.get(
        f"/admin/api/aluno/{identity['aluno_id']}/requisicao-scope"
    ).get_json()
    activity = next(
        item for item in payload["activities"] if item["atividade_versao_id"] == 55
    )
    assert activity["ch_por_evento"] is None
