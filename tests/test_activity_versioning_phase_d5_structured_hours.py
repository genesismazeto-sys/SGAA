import os
import sys

import pytest


BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main
from app.versioning import resolver as resolver_service
from tests.versioned_test_support import isolated_versioned_app_env


SIMPLE_EXPECTED = {
    3: 2.0,
    4: 2.0,
    17: 2.0,
    18: 2.0,
    9: 4.0,
    10: 4.0,
    12: 5.0,
    14: 5.0,
    41: 5.0,
    42: 5.0,
    47: 5.0,
    25: 10.0,
    26: 10.0,
    37: 10.0,
    38: 10.0,
    46: 10.0,
    5: 20.0,
    6: 20.0,
    7: 20.0,
    8: 20.0,
    39: 20.0,
    40: 20.0,
}

BLOCKED_IDS = {11, 13, 27, 28, 35, 36, 43, 44, 45, 48, 52, 54, 56, 57, 58, 59}


@pytest.fixture()
def diagnostic_database(tmp_path):
    with isolated_versioned_app_env(tmp_path, "d5_structured_hours.db") as env:
        yield env["db_path"]


def _get_turma_id_by_code(code: str) -> int:
    with main.app.app_context():
        conn = main.get_db_connection()
        row = conn.execute("SELECT id FROM turmas WHERE codigo = ?", (code,)).fetchone()
        assert row is not None
        return row["id"]


def test_phase_d5_structured_hours_fill_only_simple_ids(diagnostic_database):
    with main.app.app_context():
        conn = main.get_db_connection()
        rows = conn.execute(
            "SELECT id, ch_por_evento FROM atividade_versao ORDER BY id"
        ).fetchall()

    rows_by_id = {row["id"]: row["ch_por_evento"] for row in rows}

    assert len(rows_by_id) == 59
    assert len(SIMPLE_EXPECTED) == 22
    for atividade_versao_id, expected in SIMPLE_EXPECTED.items():
        assert rows_by_id[atividade_versao_id] == expected
    for atividade_versao_id in BLOCKED_IDS:
        assert rows_by_id[atividade_versao_id] is None


def test_phase_d5_structured_hours_keep_documentos_textual_only(diagnostic_database):
    turma_id = _get_turma_id_by_code("PPA-T11")

    with main.app.app_context():
        conn = main.get_db_connection()
        total = conn.execute("SELECT COUNT(*) FROM atividade_versao").fetchone()[0]
        docs_null = conn.execute(
            "SELECT COUNT(*) FROM atividade_versao WHERE documentos_json IS NULL"
        ).fetchone()[0]
        obs_aluno = conn.execute(
            "SELECT COUNT(*) FROM atividade_versao WHERE TRIM(COALESCE(observacao_aluno, '')) <> ''"
        ).fetchone()[0]
        obs_admin = conn.execute(
            "SELECT COUNT(*) FROM atividade_versao WHERE TRIM(COALESCE(observacao_admin, '')) <> ''"
        ).fetchone()[0]
        payload = resolver_service.listar_atividades_versionadas_por_turma(conn, turma_id)

    assert total == 59
    assert docs_null == 59
    assert obs_aluno == 59
    assert obs_admin == 59
    assert len(payload["atividades"]) == 31
    assert all(item["documentos_json"] is None for item in payload["atividades"])


def test_phase_d5_3_puntual_observation_and_limit_sanitization(diagnostic_database):
    expected_texts = {
        48: {
            "observacao_aluno": "5h por filme/peça, limite de 50h por semestre. Recomenda-se bilhete/ingresso e relatório conforme modelo da atividade, com mínimo de 2 páginas.",
            "observacao_admin": "Aplicar 5h por filme/peça, até o limite de 50h por semestre. Validar relatório no modelo da atividade, com mínimo de 2 páginas, além do ingresso/comprovação.",
        },
        52: {
            "observacao_aluno": "No regime histórico AAC-rev5, esta atividade é contabilizada como AAC. Limite de 40h por semestre. Recomenda-se declaração ou certificado contendo nome do aluno, identificação do projeto, período e carga horária.",
            "observacao_admin": "Manter enquadramento histórico como AAC para matriz antiga. Aplicar limite de 40h por semestre. Validar comprovação do projeto e evitar migração automática para AEU neste regime.",
        },
        54: {
            "observacao_aluno": "No regime histórico AAC-rev5, esta atividade é contabilizada como AAC. Limite de 40h por semestre. Recomenda-se declaração da entidade contendo período, atividades desenvolvidas e carga horária.",
            "observacao_admin": "Manter enquadramento histórico como AAC para matriz antiga. Aplicar limite de 40h por semestre. Validar declaração da entidade, atividades desenvolvidas e carga horária comprovada.",
        },
    }

    with main.app.app_context():
        conn = main.get_db_connection()
        rows = conn.execute(
            """
            SELECT id, ch_por_evento, limite_total, observacao_aluno, observacao_admin
              FROM atividade_versao
             WHERE id IN (48, 52, 54, 59)
             ORDER BY id
            """
        ).fetchall()
        qmark_aluno = conn.execute(
            "SELECT COUNT(*) FROM atividade_versao WHERE observacao_aluno LIKE '%?%'"
        ).fetchone()[0]
        qmark_admin = conn.execute(
            "SELECT COUNT(*) FROM atividade_versao WHERE observacao_admin LIKE '%?%'"
        ).fetchone()[0]

    rows_by_id = {row["id"]: row for row in rows}

    for atividade_versao_id, expected in expected_texts.items():
        assert rows_by_id[atividade_versao_id]["observacao_aluno"] == expected["observacao_aluno"]
        assert rows_by_id[atividade_versao_id]["observacao_admin"] == expected["observacao_admin"]

    assert rows_by_id[59]["limite_total"] == 40
    assert rows_by_id[59]["ch_por_evento"] is None
    assert qmark_aluno == 0
    assert qmark_admin == 0
