"""Fail-closed diagnostics for mandatory canonical snapshots."""
from __future__ import annotations

import json

from app.versioning.snapshots import _build_admin_requisicao_snapshot_diagnostic


def test_missing_snapshot_is_data_integrity_invalid():
    diagnostic = _build_admin_requisicao_snapshot_diagnostic({
        "atividade_versao_id": None,
        "regra_snapshot_json": None,
    })
    assert diagnostic == {
        "status": "invalid", "reason": "mandatory_snapshot_missing", "payload": None
    }


def test_malformed_snapshot_is_data_integrity_invalid():
    diagnostic = _build_admin_requisicao_snapshot_diagnostic({
        "atividade_versao_id": 1,
        "regra_snapshot_json": "{",
    })
    assert diagnostic["status"] == "invalid"
    assert diagnostic["payload"] is None


def test_valid_snapshot_diagnostic_uses_frozen_payload():
    payload = {
        "schema_version": "prod-1-request-v2", "atividade_versao_id": 7,
        "atividade_versao_numero": 1, "atividade_base_id": 4,
        "eixo": "AAC", "grupo": "1 - Teste",
        "nome_exibivel": "Teste", "tipo_atividade": "Acadêmica Complementar",
        "ch_por_evento": 4, "limite_semestre": 40, "limite_total": 100,
        "documentos_json": "[]", "versao_status": "ativa", "matriz_id_efetiva": 2,
        "flow_origin": "admin_create", "snapshot_written_at": "2026-01-01T00:00:00Z",
    }
    diagnostic = _build_admin_requisicao_snapshot_diagnostic({
        "atividade_versao_id": 7,
        "regra_snapshot_json": json.dumps(payload),
    })
    assert diagnostic["status"] == "valid"
    assert diagnostic["payload"] == payload
