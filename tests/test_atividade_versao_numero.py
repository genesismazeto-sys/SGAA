"""
Testes focados — D7.6B2: numero_versao operacional por atividade_base.

Cobre:
  - todos os registros migrados têm numero_versao NOT NULL (> 0)
  - v1/v2 por base são atribuídos em ordem de id
  - permite criar v3 preservando o eixo de v1/v2
  - bloqueia duas versões da mesma base com mesmo numero_versao
  - bases diferentes podem ter numero_versao=1
  - matriz_atividade_versao_item preserva vínculos válidos após migração
  - atividade_transicao preserva vínculos válidos após migração
  - get_next_numero_versao retorna max+1
  - próximo INSERT preserva AUTOINCREMENT
"""
from __future__ import annotations

import os
import sqlite3
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main
from tests.versioned_test_support import isolated_versioned_app_env


# ---------------------------------------------------------------------------
# Fixture: fresh isolated DB with reference seed
# ---------------------------------------------------------------------------


@pytest.fixture()
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "d76b2_numero.db") as e:
        yield e


def _conn(env):
    return env["conn"]


# ---------------------------------------------------------------------------
# T01 — Todos os registros migrados têm numero_versao > 0
# ---------------------------------------------------------------------------


def test_todos_migrados_tem_numero_versao_positivo(env):
    with main.app.app_context():
        conn = main.get_db_connection()
        null_count = conn.execute(
            "SELECT COUNT(*) AS c FROM atividade_versao WHERE numero_versao IS NULL OR numero_versao <= 0"
        ).fetchone()["c"]
    assert null_count == 0, f"Registros com numero_versao NULL ou <= 0: {null_count}"


# ---------------------------------------------------------------------------
# T02 — v1/v2 por base atribuídos em ordem de id
# ---------------------------------------------------------------------------


def test_versao_numerada_em_ordem_de_id_por_base(env):
    with main.app.app_context():
        conn = main.get_db_connection()
        # Base 1 tem versão T10 (menor id) e versão T11 (maior id)
        rows = conn.execute(
            "SELECT id, numero_versao FROM atividade_versao WHERE atividade_base_id = 1 ORDER BY id ASC"
        ).fetchall()
    assert len(rows) >= 2, "Base 1 deve ter pelo menos 2 versões no seed"
    for i, row in enumerate(rows, start=1):
        assert row["numero_versao"] == i, (
            f"Versão id={row['id']} deveria ter numero_versao={i}, "
            f"obteve {row['numero_versao']}"
        )


# ---------------------------------------------------------------------------
# T03 — Permite criar v3 preservando o eixo das versões anteriores
# ---------------------------------------------------------------------------


def test_permite_nova_versao_mesmo_eixo(env):
    with main.app.app_context():
        conn = main.get_db_connection()
        next_num = main.get_next_numero_versao(conn, 1)
        conn.execute(
            """
            INSERT INTO atividade_versao
                (atividade_base_id, eixo, grupo,
                 numero_versao, status)
            VALUES (1, 'AAC', '1 - v3 mesmo eixo', ?, 'rascunho')
            """,
            (next_num,),
        )
        conn.commit()
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM atividade_versao WHERE atividade_base_id = 1"
        ).fetchone()["c"]
    assert count == 3, f"Esperado 3 versões para base 1, obteve {count}"


# ---------------------------------------------------------------------------
# T04 — Bloqueia duas versões da mesma base com mesmo numero_versao
# ---------------------------------------------------------------------------


def test_bloqueia_duplicata_base_numero_versao(env):
    with main.app.app_context():
        conn = main.get_db_connection()
        # Base 2 já tem num=1. Tentar inserir outro num=1 deve falhar.
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO atividade_versao
                    (atividade_base_id, eixo, grupo,
                     numero_versao, status)
                VALUES (2, 'AAC', '1 - conflito', 1, 'rascunho')
                """
            )


# ---------------------------------------------------------------------------
# T05 — Bases diferentes podem ter numero_versao=1
# ---------------------------------------------------------------------------


def test_bases_diferentes_podem_ter_mesmo_numero_versao(env):
    with main.app.app_context():
        conn = main.get_db_connection()
        # Verifica que base 26 e base 29 ambas têm numero_versao=1 (sem conflito).
        rows = conn.execute(
            "SELECT atividade_base_id, numero_versao FROM atividade_versao"
            " WHERE atividade_base_id IN (26, 29) AND numero_versao = 1"
        ).fetchall()
    base_ids = {r["atividade_base_id"] for r in rows}
    assert 26 in base_ids, "Base 26 deve ter numero_versao=1"
    assert 29 in base_ids, "Base 29 deve ter numero_versao=1"


# ---------------------------------------------------------------------------
# T06 — matriz_atividade_versao_item preserva vínculos válidos
# ---------------------------------------------------------------------------


def test_matriz_atividade_versao_item_integro(env):
    with main.app.app_context():
        conn = main.get_db_connection()
        orphans = conn.execute(
            """
            SELECT COUNT(*) AS c
              FROM matriz_atividade_versao_item m
              LEFT JOIN atividade_versao av ON av.id = m.atividade_versao_id
             WHERE av.id IS NULL
            """
        ).fetchone()["c"]
    assert orphans == 0, f"matriz_atividade_versao_item com vínculos órfãos: {orphans}"


# ---------------------------------------------------------------------------
# T07 — atividade_transicao preserva vínculos válidos
# ---------------------------------------------------------------------------


def test_atividade_transicao_integra(env):
    with main.app.app_context():
        conn = main.get_db_connection()
        broken = conn.execute(
            """
            SELECT COUNT(*) AS c
              FROM atividade_transicao t
              LEFT JOIN atividade_versao av1 ON av1.id = t.from_atividade_versao_id
              LEFT JOIN atividade_versao av2 ON av2.id = t.to_atividade_versao_id
             WHERE (t.from_atividade_versao_id IS NOT NULL AND av1.id IS NULL)
                OR (t.to_atividade_versao_id IS NOT NULL AND av2.id IS NULL)
            """
        ).fetchone()["c"]
    assert broken == 0, f"atividade_transicao com referências quebradas: {broken}"


# ---------------------------------------------------------------------------
# T08 — get_next_numero_versao retorna max+1
# ---------------------------------------------------------------------------


def test_get_next_numero_versao(env):
    with main.app.app_context():
        conn = main.get_db_connection()
        # Base 1 tem v1 e v2; próximo deve ser 3
        next_num = main.get_next_numero_versao(conn, 1)
        assert next_num == 3, f"Esperado 3, obteve {next_num}"

        # Base 26 tem apenas v1; próximo deve ser 2
        next_num_26 = main.get_next_numero_versao(conn, 26)
        assert next_num_26 == 2, f"Esperado 2 para base 26, obteve {next_num_26}"

        # Base nova sem versões; próximo deve ser 1
        new_base_id = conn.execute(
            "INSERT INTO atividade_base (nome_conceito, status) VALUES ('Base Nova Test', 'ativo') RETURNING id"
        ).fetchone()["id"]
        next_num_new = main.get_next_numero_versao(conn, new_base_id)
        assert next_num_new == 1, f"Esperado 1 para base nova, obteve {next_num_new}"


# ---------------------------------------------------------------------------
# T09 — Próximo INSERT preserva AUTOINCREMENT (id > max existente)
# ---------------------------------------------------------------------------


def test_autoincrement_preservado_apos_migracao(env):
    with main.app.app_context():
        conn = main.get_db_connection()
        max_id_before = conn.execute(
            "SELECT MAX(id) AS m FROM atividade_versao"
        ).fetchone()["m"]

        next_num = main.get_next_numero_versao(conn, 26)
        inserted_id = conn.execute(
            """
            INSERT INTO atividade_versao
                (atividade_base_id, eixo,
                 numero_versao, status)
            VALUES (26, 'AAC', ?, 'rascunho')
            RETURNING id
            """,
            (next_num,),
        ).fetchone()["id"]
        conn.commit()

    assert inserted_id > max_id_before, (
        f"Novo id={inserted_id} não é maior que max anterior={max_id_before}"
    )


# ---------------------------------------------------------------------------
# T11 — numero_versao=0 é bloqueado
# ---------------------------------------------------------------------------


def test_bloqueia_numero_versao_zero(env):
    with main.app.app_context():
        conn = main.get_db_connection()
        with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError)):
            conn.execute(
                """
                INSERT INTO atividade_versao
                    (atividade_base_id, eixo, grupo,
                     numero_versao, status)
                VALUES (26, 'AAC', '1 - Zero', 0, 'rascunho')
                """
            )


# ---------------------------------------------------------------------------
# T12 — numero_versao negativo é bloqueado
# ---------------------------------------------------------------------------


def test_bloqueia_numero_versao_negativo(env):
    with main.app.app_context():
        conn = main.get_db_connection()
        with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError)):
            conn.execute(
                """
                INSERT INTO atividade_versao
                    (atividade_base_id, eixo, grupo,
                     numero_versao, status)
                VALUES (26, 'AAC', '1 - Negativo', -5, 'rascunho')
                """
            )
