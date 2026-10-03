"""Discriminate canonical operational names from unchanged snapshot authority."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict

import pytest

from app.versioning.request_history import (
    HistoricalRequestAuthorityError,
    read_historical_request,
    read_request_presentation,
)
from app.versioning.snapshots import read_requisicao_snapshot_for_processing


@pytest.fixture()
def linked_request(tmp_path, request):
    path = tmp_path / "display.db"
    name = request.param
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE atividade_base(id INTEGER PRIMARY KEY, nome_conceito TEXT);
        CREATE TABLE atividade_versao(
            id INTEGER PRIMARY KEY, atividade_base_id INTEGER,
            eixo TEXT, grupo TEXT, limite_semestre REAL, limite_total REAL
        );
    """)
    conn.execute("INSERT INTO atividade_base VALUES(5,?)", (name,))
    conn.execute(
        "INSERT INTO atividade_versao VALUES(7,5,'AEU','Changed live group',999,999)"
    )
    conn.commit()
    conn.close()
    payload = {
        "schema_version": "prod-1-request-v2",
        "atividade_base_id": 5, "atividade_versao_id": 7,
        "atividade_versao_numero": 3, "matriz_id_efetiva": 1,
        "nome_exibivel": name.upper(), "tipo_atividade": "Acadêmica Complementar",
        "eixo": "AAC", "grupo": "5 - Historical group",
        "ch_por_evento": 4, "limite_semestre": 20, "limite_total": 40,
        "documentos_json": '["Original required evidence"]',
        "observacao_aluno": "Original student requirements",
        "observacao_admin": "Original admin requirements",
        "source": {"file": "original.xlsx", "physical_row": 867},
        "migration": {"batch": "original-batch", "processing_observation": "Original"},
        "transition_provenance": {"from_atividade_versao_id": 7},
    }
    row = {
        "id": 28, "aluno_id": 1, "atividade_versao_id": 7,
        "status": "Deferida Parcialmente", "horas_solicitadas": 80,
        "horas_deferidas": 40, "data_evento": "2026-05-01",
        "regra_snapshot_json": json.dumps(payload, ensure_ascii=False),
    }
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    yield conn, path, row, name
    conn.close()


@pytest.mark.parametrize("linked_request", [
    "Palestras na Faculdade EJ",
    "Horas de voo em escola homologada pela ANAC",
    "Cursos de formação profissional",
    "Monitoria voluntária.",
    "Estágio extracurricular (não obrigatório)",
    "Cursos de idiomas fora da Faculdade",
    "Trabalho voluntário em organizações do terceiro setor",
], indirect=True)
def test_linked_display_name_wins_without_any_write_or_rule_substitution(linked_request):
    conn, path, row, name = linked_request
    before_bytes = path.read_bytes()
    before_row = dict(row)
    frozen = read_historical_request(row)
    displayed = read_request_presentation(row, conn=conn)
    expected = asdict(frozen)
    expected["nome"] = name
    assert asdict(displayed) == expected
    assert displayed.nome != frozen.nome
    assert displayed.eixo == "AAC"
    assert displayed.grupo == "5 - Historical group"
    assert displayed.limite_semestre == 20 and displayed.limite_total == 40
    assert displayed.approved_hours == 40
    assert read_requisicao_snapshot_for_processing(row).payload == json.loads(
        before_row["regra_snapshot_json"]
    )
    assert row == before_row
    assert conn.total_changes == 0
    assert path.read_bytes() == before_bytes
    assert not any(path.with_name(path.name + suffix).exists()
                   for suffix in ("-wal", "-shm", "-journal"))


@pytest.mark.parametrize("linked_request", ["Palestras na Faculdade EJ"], indirect=True)
def test_missing_canonical_link_fails_closed_instead_of_using_snapshot_label(linked_request):
    conn, path, row, name = linked_request
    row["atividade_versao_id"] = 99
    snapshot = json.loads(row["regra_snapshot_json"])
    snapshot["atividade_versao_id"] = 99
    row["regra_snapshot_json"] = json.dumps(snapshot)
    with pytest.raises(HistoricalRequestAuthorityError) as error:
        read_request_presentation(row, conn=conn)
    assert error.value.reason == "linked_activity_base_unavailable"


@pytest.mark.parametrize("linked_request", ["Palestras na Faculdade EJ"], indirect=True)
def test_valid_live_link_does_not_rescue_invalid_historical_rules(linked_request):
    conn, path, row, name = linked_request
    row["regra_snapshot_json"] = "{}"
    with pytest.raises(HistoricalRequestAuthorityError):
        read_request_presentation(row, conn=conn)
