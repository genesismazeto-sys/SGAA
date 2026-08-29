"""R4 independent behavioral oracles for PROD-1 leaf and integrity contracts."""

from __future__ import annotations

import sqlite3

import pytest

from app.prod1_schema import bootstrap_prod1_schema
from app.versioning.integrity import validar_integridade_versionamento_atividades


def _connection(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    bootstrap_prod1_schema(conn)
    return conn


def _seed_parent_graph(conn):
    course_id = conn.execute(
        "INSERT INTO cursos(nome,codigo,duracao_periodos) VALUES('Curso R4','R4',8) RETURNING id"
    ).fetchone()[0]
    matrix_id = conn.execute(
        "INSERT INTO matrizes_atividades(curso_id,nome,versao) VALUES(?,'Matriz R4','1') RETURNING id",
        (course_id,),
    ).fetchone()[0]
    return matrix_id


def _base(conn, name):
    return conn.execute(
        "INSERT INTO atividade_base(nome_conceito) VALUES(?) RETURNING id", (name,)
    ).fetchone()[0]


def _version(conn, *, base_id, axis, number=1):
    return conn.execute(
        """INSERT INTO atividade_versao
           (atividade_base_id,eixo,grupo,status,numero_versao)
           VALUES(?,?,?,'ativa',?) RETURNING id""",
        (base_id, axis, f"Grupo {axis}", number),
    ).fetchone()[0]


def _same_base_aac_aeu(conn):
    _seed_parent_graph(conn)
    base_id = _base(conn, "Conceito R4 compartilhado")
    aac_id = _version(
        conn, base_id=base_id, axis="AAC"
    )
    aeu_id = _version(
        conn,
        base_id=base_id,
        axis="AEU",
        number=2,
    )
    return aac_id, aeu_id


def test_g1_transition_update_rejects_reverse_semantics(tmp_path):
    conn = _connection(tmp_path / "g1-update.db")
    aac_id, aeu_id = _same_base_aac_aeu(conn)
    transition_id = conn.execute(
        """INSERT INTO atividade_transicao
           (from_atividade_versao_id,to_atividade_versao_id,tipo_transicao,justificativa)
           VALUES(?,?,'aac_para_aeu','Proveniência R4') RETURNING id""",
        (aac_id, aeu_id),
    ).fetchone()[0]

    with pytest.raises(sqlite3.IntegrityError, match="AAC -> AEU"):
        conn.execute(
            """UPDATE atividade_transicao
                  SET from_atividade_versao_id=?, to_atividade_versao_id=?
                WHERE id=?""",
            (aeu_id, aac_id, transition_id),
        )

    persisted = conn.execute(
        "SELECT from_atividade_versao_id,to_atividade_versao_id FROM atividade_transicao WHERE id=?",
        (transition_id,),
    ).fetchone()
    assert tuple(persisted) == (aac_id, aeu_id)


@pytest.mark.parametrize("missing_side", ["source", "destination"])
def test_g1_transition_missing_endpoint_fails_closed_by_foreign_key(tmp_path, missing_side):
    conn = _connection(tmp_path / f"g1-missing-{missing_side}.db")
    aac_id, aeu_id = _same_base_aac_aeu(conn)
    source_id = 999_999 if missing_side == "source" else aac_id
    destination_id = 999_999 if missing_side == "destination" else aeu_id

    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY constraint failed"):
        conn.execute(
            """INSERT INTO atividade_transicao
               (from_atividade_versao_id,to_atividade_versao_id,tipo_transicao,justificativa)
               VALUES(?,?,'aac_para_aeu','Endpoint obrigatório')""",
            (source_id, destination_id),
        )

    assert conn.execute("SELECT COUNT(*) FROM atividade_transicao").fetchone()[0] == 0


def test_g1_reverse_aac_to_aeu_direction_is_rejected(tmp_path):
    conn = _connection(tmp_path / "g1-reverse.db")
    aac_id, aeu_id = _same_base_aac_aeu(conn)

    with pytest.raises(sqlite3.IntegrityError, match="AAC -> AEU"):
        conn.execute(
            """INSERT INTO atividade_transicao
               (from_atividade_versao_id,to_atividade_versao_id,tipo_transicao,justificativa)
               VALUES(?,?,'aac_para_aeu','Direção reversa inválida')""",
            (aeu_id, aac_id),
        )

    assert conn.execute("SELECT COUNT(*) FROM atividade_transicao").fetchone()[0] == 0


def _index_inventory(conn, table):
    inventory = {}
    for row in conn.execute(f"PRAGMA index_list('{table}')"):
        name = row[1]
        columns = tuple(info[2] for info in conn.execute(f"PRAGMA index_info('{name}')"))
        inventory[name] = {"unique": bool(row[2]), "columns": columns}
    return inventory


def test_g1_leaf_index_inventory_has_independent_order_and_uniqueness_contract(tmp_path):
    conn = _connection(tmp_path / "g1-indexes.db")
    required_nonunique = {
        "atividade_transicao": {
            "idx_atividade_transicao_from": ("from_atividade_versao_id",),
            "idx_atividade_transicao_to": ("to_atividade_versao_id",),
            "idx_atividade_transicao_tipo": ("tipo_transicao",),
        },
        "matriz_atividade_versao_item": {
            "idx_matriz_atividade_versao_item_matriz": ("matriz_id",),
            "idx_matriz_atividade_versao_item_base": ("atividade_base_id",),
            "idx_matriz_atividade_versao_item_versao": ("atividade_versao_id",),
        },
    }

    for table, expected in required_nonunique.items():
        inventory = _index_inventory(conn, table)
        for name, columns in expected.items():
            assert name in inventory
            assert inventory[name] == {"unique": False, "columns": columns}

    matrix_items = _index_inventory(conn, "matriz_atividade_versao_item")
    required_unique_sequences = {
        ("matriz_id", "atividade_base_id"),
        ("matriz_id", "atividade_versao_id"),
    }
    actual_unique_sequences = {
        item["columns"] for item in matrix_items.values() if item["unique"]
    }
    assert required_unique_sequences <= actual_unique_sequences


def test_g2_integrity_rejects_mixed_aac_aeu_without_transition(tmp_path):
    conn = _connection(tmp_path / "g2-mixed.db")
    _same_base_aac_aeu(conn)

    issues = validar_integridade_versionamento_atividades(conn, raise_on_error=False)

    assert len(issues) == 1
    assert "AAC/AEU ativas" in issues[0]
    assert "aac_para_aeu" in issues[0]
    with pytest.raises(ValueError, match="aac_para_aeu"):
        validar_integridade_versionamento_atividades(conn)


def test_g2_integrity_accepts_valid_explicit_aac_to_aeu_transition(tmp_path):
    conn = _connection(tmp_path / "g2-valid.db")
    aac_id, aeu_id = _same_base_aac_aeu(conn)
    conn.execute(
        """INSERT INTO atividade_transicao
           (from_atividade_versao_id,to_atividade_versao_id,tipo_transicao,justificativa)
           VALUES(?,?,'aac_para_aeu','Mudança normativa explicitamente documentada')""",
        (aac_id, aeu_id),
    )

    assert validar_integridade_versionamento_atividades(conn) == []


def test_g2_integrity_rejects_cross_base_transition(tmp_path):
    conn = _connection(tmp_path / "g2-cross-base.db")
    _seed_parent_graph(conn)
    source_base = _base(conn, "Conceito R4 origem")
    destination_base = _base(conn, "Conceito R4 destino")
    aac_id = _version(
        conn, base_id=source_base, axis="AAC"
    )
    aeu_id = _version(
        conn, base_id=destination_base, axis="AEU"
    )
    conn.execute(
        """INSERT INTO atividade_transicao
           (from_atividade_versao_id,to_atividade_versao_id,tipo_transicao,justificativa)
           VALUES(?,?,'aac_para_aeu','Bases distintas não são equivalentes')""",
        (aac_id, aeu_id),
    )

    issues = validar_integridade_versionamento_atividades(conn, raise_on_error=False)

    assert len(issues) == 1
    assert "atividade_base divergente entre origem e destino" in issues[0]
    with pytest.raises(ValueError, match="atividade_base divergente"):
        validar_integridade_versionamento_atividades(conn)


def test_g2_invalid_transition_type_is_physically_rejected(tmp_path):
    conn = _connection(tmp_path / "g2-invalid-type.db")
    aac_id, aeu_id = _same_base_aac_aeu(conn)

    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
        conn.execute(
            """INSERT INTO atividade_transicao
               (from_atividade_versao_id,to_atividade_versao_id,tipo_transicao,justificativa)
               VALUES(?,?,'conversao_implicita','Tipo fora do contrato PROD-1')""",
            (aac_id, aeu_id),
        )
