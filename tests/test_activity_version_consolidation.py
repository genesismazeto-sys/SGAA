"""Consolidating two versions that encode the same rule into one canonical version."""
from __future__ import annotations

import json
import uuid

import pytest

import main
from app import activity_catalog
from app.activity_catalog import (
    consolidate_equivalent_activity_versions,
    get_next_numero_versao,
)
from tests.versioned_test_support import isolated_versioned_app_env


@pytest.fixture()
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "activity_version_consolidation.db") as value:
        yield value


def _seed_duplicate(*, remove_overrides=None):
    """v1 (kept, two historical requests) -> v2 (same rule, selected by two Matrizes).

    Mirrors the Conferências shape: same axis, group number, hours and limits;
    different guidance text, group label and documentos.
    """
    token = uuid.uuid4().hex[:8]
    remove_values = {
        "grupo": "1 - Atividades fora da Universidade",
        "ch_por_evento": 4.0,
        "limite_semestre": None,
        "limite_total": None,
    }
    remove_values.update(remove_overrides or {})
    with main.app.app_context():
        conn = main.get_db_connection()
        base_id = conn.execute(
            "INSERT INTO atividade_base(nome_conceito,status) VALUES(?,'ativo') RETURNING id",
            (f"Conferências {token}",),
        ).fetchone()[0]
        keep_id = conn.execute(
            "INSERT INTO atividade_versao(atividade_base_id,eixo,grupo,ch_por_evento,"
            "observacao_aluno,observacao_admin,numero_versao,status) "
            "VALUES(?,'AAC','1 - Atividades fora da Faculdade',4,"
            "'4h por evento. Recomenda-se anexar certificado.','Aplicar 4h/evento.',1,'ativa') "
            "RETURNING id",
            (base_id,),
        ).fetchone()[0]
        remove_id = conn.execute(
            "INSERT INTO atividade_versao(atividade_base_id,eixo,grupo,ch_por_evento,"
            "limite_semestre,limite_total,observacao_aluno,observacao_admin,documentos_json,"
            "numero_versao,status,versao_anterior_id) "
            "VALUES(?,'AAC',?,?,?,?,'Conferências\n4 h/evento','Conferências\n4 h/evento',"
            "'[\"certificado\"]',2,'ativa',?) RETURNING id",
            (
                base_id,
                remove_values["grupo"],
                remove_values["ch_por_evento"],
                remove_values["limite_semestre"],
                remove_values["limite_total"],
                keep_id,
            ),
        ).fetchone()[0]
        request_ids = [
            conn.execute(
                "INSERT INTO requisicoes(atividade_versao_id,data_solicitacao,data_evento,"
                "horas_solicitadas,status,regra_snapshot_json) VALUES(?,?,?,4,?,?) RETURNING id",
                (
                    keep_id,
                    "2026-09-15",
                    "2026-09-01",
                    status,
                    json.dumps(
                        {"atividade_versao_id": keep_id, "atividade_versao_numero": 1,
                         "grupo": "1 - Atividades fora da Faculdade"},
                        ensure_ascii=False,
                    ),
                ),
            ).fetchone()[0]
            for status in ("Deferida Parcialmente", "Pendente")
        ]
        item_ids = []
        for matrix_id in (1, 2):
            item_ids.append(
                conn.execute(
                    "INSERT INTO matriz_atividade_versao_item"
                    "(matriz_id,atividade_base_id,atividade_versao_id) VALUES(?,?,?) RETURNING id",
                    (matrix_id, base_id, remove_id),
                ).fetchone()[0]
            )
        conn.commit()
    return base_id, keep_id, remove_id, request_ids, item_ids


def _state():
    with main.app.app_context():
        conn = main.get_db_connection()
        return {
            table: [dict(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY id")]
            for table in (
                "atividade_base", "atividade_versao", "requisicoes",
                "matriz_atividade_versao_item", "atividade_transicao",
            )
        }


def _consolidate(base_id, keep_id, remove_id):
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("BEGIN IMMEDIATE")
        try:
            consolidate_equivalent_activity_versions(
                conn, base_id=base_id, keep_versao_id=keep_id, remove_versao_id=remove_id
            )
        except Exception:
            conn.rollback()
            raise
        conn.commit()


def test_equivalent_versions_consolidate_preserving_requests_and_repointing_matrices(env):
    base_id, keep_id, remove_id, request_ids, item_ids = _seed_duplicate()
    before = _state()

    _consolidate(base_id, keep_id, remove_id)

    after = _state()
    versions = [row for row in after["atividade_versao"] if row["atividade_base_id"] == base_id]
    assert [(v["id"], v["numero_versao"], v["versao_anterior_id"]) for v in versions] == [
        (keep_id, 1, None)
    ]
    kept_before = next(v for v in before["atividade_versao"] if v["id"] == keep_id)
    assert versions[0] == kept_before
    # Historical requests: byte-identical rows, still pointing at the kept version.
    assert [r for r in after["requisicoes"] if r["id"] in request_ids] == [
        r for r in before["requisicoes"] if r["id"] in request_ids
    ]
    assert {r["atividade_versao_id"] for r in after["requisicoes"] if r["id"] in request_ids} == {keep_id}
    # Both Matriz selections now point at the kept version; nothing else moved.
    repointed = {
        item["id"]: item["atividade_versao_id"]
        for item in after["matriz_atividade_versao_item"]
        if item["id"] in item_ids
    }
    assert repointed == {item_ids[0]: keep_id, item_ids[1]: keep_id}
    assert [i for i in after["matriz_atividade_versao_item"] if i["id"] not in item_ids] == [
        i for i in before["matriz_atividade_versao_item"] if i["id"] not in item_ids
    ]
    assert [v for v in after["atividade_versao"] if v["atividade_base_id"] != base_id] == [
        v for v in before["atividade_versao"] if v["atividade_base_id"] != base_id
    ]
    assert after["atividade_base"] == before["atividade_base"]
    with main.app.app_context():
        assert get_next_numero_versao(main.get_db_connection(), base_id) == 2


@pytest.mark.parametrize(
    "overrides,field",
    [
        ({"ch_por_evento": 5.0}, "ch_por_evento"),
        ({"limite_semestre": 20.0}, "limite_semestre"),
        ({"limite_total": 40.0}, "limite_total"),
        ({"grupo": "2 - Atividades de extensão"}, "grupo"),
    ],
)
def test_material_rule_difference_refuses_without_writing(env, overrides, field):
    base_id, keep_id, remove_id, _, _ = _seed_duplicate(remove_overrides=overrides)
    before = _state()

    with pytest.raises(ValueError, match=field):
        _consolidate(base_id, keep_id, remove_id)

    assert _state() == before


def test_version_with_requests_cannot_be_folded_away(env):
    base_id, keep_id, remove_id, request_ids, _ = _seed_duplicate()
    before = _state()

    # Folding the requested version away would orphan immutable history.
    with pytest.raises(ValueError) as refused:
        _consolidate(base_id, remove_id, keep_id)

    assert str(refused.value) == (
        f"A versão removida é utilizada pelas requisições {request_ids[0]} e {request_ids[1]}."
    )

    assert _state() == before


def test_failure_after_repointing_rolls_everything_back(env, monkeypatch):
    base_id, keep_id, remove_id, _, _ = _seed_duplicate()
    before = _state()

    def failing_delete(conn, *, base_id, versao_id):
        raise RuntimeError("simulated failure after repointing")

    monkeypatch.setattr(activity_catalog, "delete_activity_version", failing_delete)
    with pytest.raises(RuntimeError):
        _consolidate(base_id, keep_id, remove_id)

    assert _state() == before
