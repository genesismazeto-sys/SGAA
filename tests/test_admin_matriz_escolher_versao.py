"""
Testes focados — D7.6D-MATRIX-CHOOSES-OPERATIONAL-VERSION
Rota: POST /admin/matrizes/<id>/atividades/<id>/nova-versao (semântica D7.6D)

Contrato verificado:
  - Card da matriz exibe badge vN baseado em numero_versao, não codigo_normativo
  - get_card_version_menu_data retorna numero_versao e lista de versoes existentes
  - Modal lista v3, v2, v1 por atividade_base (ordenado DESC)
  - Versão atual da matriz aparece marcada como is_current
  - POST relinka matriz para versao_id existente sem criar atividade_versao
  - Versão de outra base é rejeitada
  - Versão inexistente é rejeitada
  - Após relink, matriz_atividade_versao_item aponta para nova versão
  - Admin → Atividades (rotas catalogo) não é alterado
"""
from __future__ import annotations

import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main
from tests.versioned_test_support import isolated_versioned_app_env


# ---------------------------------------------------------------------------
# Seed
# ---------------------------------------------------------------------------

def _seed_d76d(conn) -> dict:
    """
    Cria cenário isolado para D7.6D:
      - 1 matriz_test com 1 atividade (base_A)
      - 3 versões da base_A: v1, v2, v3 (v1 = vinculada à matriz_test)
      - 1 base_B com 1 versão (vB1) para testar rejeição cross-base
    """
    curso_id = conn.execute("SELECT id FROM cursos LIMIT 1").fetchone()["id"]

    matriz_id = conn.execute(
        """
        INSERT INTO matrizes_atividades
            (curso_id, nome, versao, status, horas_aac_obrigatorias, horas_extensao_obrigatorias)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (curso_id, "Matriz D7.6D", "D76D-test", "ativa", 100, 50),
    ).lastrowid

    norma_1_id = 1  # AAC-rev5 ativa (seed de referência)
    conn.execute("INSERT INTO matriz_norma (matriz_id, norma_id) VALUES (?, ?)", (matriz_id, norma_1_id))

    atividade_id = conn.execute(
        """
        INSERT INTO atividades (nome, grupo, tipo_atividade, descricao, limite_horas)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("Congresso D7.6D", "1 - Congresso", "Acadêmica Complementar", "desc", 100),
    ).lastrowid

    base_a_id = conn.execute(
        "INSERT INTO atividade_base (nome_conceito, descricao, status) VALUES (?, ?, ?)",
        ("Base A D7.6D", "base para teste", "ativo"),
    ).lastrowid

    conn.execute(
        "INSERT INTO atividade_legacy_map (atividade_id_legacy, atividade_base_id, status) VALUES (?, ?, ?)",
        (atividade_id, base_a_id, "mapeada"),
    )

    versao_1_id = conn.execute(
        """
        INSERT INTO atividade_versao
            (atividade_base_id, norma_id, codigo_normativo, eixo, grupo,
             ch_por_evento, limite_semestre, limite_total, numero_versao, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (base_a_id, norma_1_id, "AAC-rev5", "AAC", "1 - Congresso", 2.0, 20.0, 60.0, 1, "ativa"),
    ).lastrowid

    versao_2_id = conn.execute(
        """
        INSERT INTO atividade_versao
            (atividade_base_id, norma_id, codigo_normativo, eixo, grupo,
             ch_por_evento, limite_semestre, limite_total, numero_versao, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (base_a_id, norma_1_id, "AAC-rev5-alt", "AAC", "1 - Congresso", 2.0, 20.0, 60.0, 2, "ativa"),
    ).lastrowid

    versao_3_id = conn.execute(
        """
        INSERT INTO atividade_versao
            (atividade_base_id, norma_id, codigo_normativo, eixo, grupo,
             ch_por_evento, limite_semestre, limite_total, numero_versao, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (base_a_id, norma_1_id, "AAC-rev5-v3", "AAC", "1 - Congresso", 2.0, 20.0, 60.0, 3, "ativa"),
    ).lastrowid

    conn.execute(
        "INSERT INTO matrizes_atividades_itens (matriz_id, atividade_id) VALUES (?, ?)",
        (matriz_id, atividade_id),
    )
    conn.execute(
        "INSERT INTO matriz_atividade_versao_item (matriz_id, atividade_versao_id) VALUES (?, ?)",
        (matriz_id, versao_1_id),
    )

    # Base B para testar rejeição cross-base
    base_b_id = conn.execute(
        "INSERT INTO atividade_base (nome_conceito, descricao, status) VALUES (?, ?, ?)",
        ("Base B D7.6D", "base diferente", "ativo"),
    ).lastrowid
    versao_b1_id = conn.execute(
        """
        INSERT INTO atividade_versao
            (atividade_base_id, norma_id, codigo_normativo, eixo, grupo,
             ch_por_evento, limite_semestre, limite_total, numero_versao, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (base_b_id, norma_1_id, "AAC-B1", "AAC", "Outro grupo", 2.0, 10.0, 40.0, 1, "ativa"),
    ).lastrowid

    conn.commit()

    return {
        "matriz_id": matriz_id,
        "atividade_id": atividade_id,
        "base_a_id": base_a_id,
        "base_b_id": base_b_id,
        "versao_1_id": versao_1_id,
        "versao_2_id": versao_2_id,
        "versao_3_id": versao_3_id,
        "versao_b1_id": versao_b1_id,
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "d76d_escolher_versao.db") as e:
        with main.app.app_context():
            conn = main.get_db_connection()
            seed = _seed_d76d(conn)
        e["seed"] = seed
        yield e


def _login(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["user_type"] = "admin"
        sess["user_name"] = "Admin D7.6D"


def _escolher(client, matriz_id, atividade_id, versao_id, tab="aac"):
    return client.post(
        f"/admin/matrizes/{matriz_id}/atividades/{atividade_id}/nova-versao",
        data={"active_tab": tab, "versao_id": str(versao_id)},
        follow_redirects=False,
    )


# ---------------------------------------------------------------------------
# T01 — card da matriz exibe badge vN, não codigo_normativo
# ---------------------------------------------------------------------------

def test_card_shows_vN_badge(env):
    client = env["client"]
    seed = env["seed"]
    _login(client)

    resp = client.get(f"/admin/editar_matriz/{seed['matriz_id']}?tab=aac")
    assert resp.status_code == 200

    html = resp.get_data(as_text=True)
    # Badge class present
    assert 'class="version-badge"' in html
    # Shows vN where N is numero_versao (versao_1 = 1)
    assert '>v1<' in html
    # Does NOT show codigo_normativo as primary badge
    # (codigo_normativo may appear in JS data, but not as a standalone badge)
    assert 'class="version-badge"' in html
    assert 'AAC-rev5' not in html.split('class="version-badge"')[1].split('>')[1].split('<')[0]


# ---------------------------------------------------------------------------
# T02 — get_card_version_menu_data retorna numero_versao e lista versoes
# ---------------------------------------------------------------------------

def test_card_version_menu_data_returns_numero_versao(env):
    seed = env["seed"]

    with main.app.app_context():
        conn = main.get_db_connection()
        result = main.get_card_version_menu_data(
            conn, seed["matriz_id"], [seed["atividade_id"]]
        )

    assert str(seed["atividade_id"]) in result
    entry = result[str(seed["atividade_id"])]

    # Must contain numero_versao of current linked version (v1)
    assert "numero_versao" in entry
    assert entry["numero_versao"] == 1

    # Must contain versoes list
    assert "versoes" in entry
    assert len(entry["versoes"]) == 3

    # versoes ordered DESC by numero_versao
    numeros = [v["numero_versao"] for v in entry["versoes"]]
    assert numeros == sorted(numeros, reverse=True)

    # No "normas" key (old D7.5D field)
    assert "normas" not in entry


# ---------------------------------------------------------------------------
# T03 — modal lista v3, v2, v1 em ordem decrescente para a atividade_base
# ---------------------------------------------------------------------------

def test_card_version_menu_data_versoes_ordered_desc(env):
    seed = env["seed"]

    with main.app.app_context():
        conn = main.get_db_connection()
        result = main.get_card_version_menu_data(
            conn, seed["matriz_id"], [seed["atividade_id"]]
        )

    entry = result[str(seed["atividade_id"])]
    versoes = entry["versoes"]

    assert len(versoes) == 3
    assert versoes[0]["numero_versao"] == 3
    assert versoes[1]["numero_versao"] == 2
    assert versoes[2]["numero_versao"] == 1


# ---------------------------------------------------------------------------
# T04 — versão atual aparece marcada como is_current=True
# ---------------------------------------------------------------------------

def test_current_versao_marked_as_is_current(env):
    seed = env["seed"]

    with main.app.app_context():
        conn = main.get_db_connection()
        result = main.get_card_version_menu_data(
            conn, seed["matriz_id"], [seed["atividade_id"]]
        )

    entry = result[str(seed["atividade_id"])]
    current_entries = [v for v in entry["versoes"] if v["is_current"]]
    non_current = [v for v in entry["versoes"] if not v["is_current"]]

    # Exactly one version is current
    assert len(current_entries) == 1
    assert current_entries[0]["id"] == seed["versao_1_id"]
    # Others are not current
    assert len(non_current) == 2


# ---------------------------------------------------------------------------
# T05 — POST relinka para versao_id existente sem criar atividade_versao
# ---------------------------------------------------------------------------

def test_post_relinks_to_existing_versao_no_insert(env):
    client = env["client"]
    seed = env["seed"]
    _login(client)

    with main.app.app_context():
        conn = main.get_db_connection()
        count_before = conn.execute("SELECT COUNT(*) AS c FROM atividade_versao").fetchone()["c"]

    resp = _escolher(client, seed["matriz_id"], seed["atividade_id"], seed["versao_3_id"])
    assert resp.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        count_after = conn.execute("SELECT COUNT(*) AS c FROM atividade_versao").fetchone()["c"]

    assert count_after == count_before  # nenhuma nova versao criada


# ---------------------------------------------------------------------------
# T06 — após relink, matriz_atividade_versao_item aponta para nova versão
# ---------------------------------------------------------------------------

def test_post_relink_updates_matriz_atividade_versao_item(env):
    client = env["client"]
    seed = env["seed"]
    _login(client)

    _escolher(client, seed["matriz_id"], seed["atividade_id"], seed["versao_3_id"])

    with main.app.app_context():
        conn = main.get_db_connection()
        link = conn.execute(
            "SELECT atividade_versao_id FROM matriz_atividade_versao_item WHERE matriz_id = ?",
            (seed["matriz_id"],),
        ).fetchone()

    assert link is not None
    assert link["atividade_versao_id"] == seed["versao_3_id"]


# ---------------------------------------------------------------------------
# T07 — versão de outra atividade_base é rejeitada
# ---------------------------------------------------------------------------

def test_post_rejects_versao_from_different_base(env):
    client = env["client"]
    seed = env["seed"]
    _login(client)

    resp = _escolher(client, seed["matriz_id"], seed["atividade_id"], seed["versao_b1_id"])
    assert resp.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        link = conn.execute(
            "SELECT atividade_versao_id FROM matriz_atividade_versao_item WHERE matriz_id = ?",
            (seed["matriz_id"],),
        ).fetchone()

    # Link must remain on versao_1_id (unchanged)
    assert link["atividade_versao_id"] == seed["versao_1_id"]


# ---------------------------------------------------------------------------
# T08 — versão inexistente é rejeitada
# ---------------------------------------------------------------------------

def test_post_rejects_nonexistent_versao(env):
    client = env["client"]
    seed = env["seed"]
    _login(client)

    resp = _escolher(client, seed["matriz_id"], seed["atividade_id"], 9999999)
    assert resp.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        link = conn.execute(
            "SELECT atividade_versao_id FROM matriz_atividade_versao_item WHERE matriz_id = ?",
            (seed["matriz_id"],),
        ).fetchone()

    assert link["atividade_versao_id"] == seed["versao_1_id"]


# ---------------------------------------------------------------------------
# T09 — Admin → Atividades não é alterado (catálogo não toca na rota da matriz)
# ---------------------------------------------------------------------------

def test_admin_atividades_route_unaffected(env):
    client = env["client"]
    seed = env["seed"]
    _login(client)

    # GET do catálogo de versões da atividade_base deve retornar 200
    resp = client.get(f"/admin/catalogo-versoes/{seed['base_a_id']}")
    assert resp.status_code == 200

    html = resp.get_data(as_text=True)
    # Catalogo shows v1, v2, v3 for base_a
    assert "v1" in html or "numero_versao" in html or "AAC-rev5" in html


# ---------------------------------------------------------------------------
# T10 — get_card_version_menu_data: atividade sem vínculo não incluída no resultado
# ---------------------------------------------------------------------------

def test_card_version_menu_data_excludes_unlinked_activity(env):
    seed = env["seed"]

    with main.app.app_context():
        conn = main.get_db_connection()
        # Busca atividade_id que existe mas NÃO está em matriz_atividade_versao_item
        other_atividade = conn.execute(
            "SELECT id FROM atividades WHERE id != ? LIMIT 1",
            (seed["atividade_id"],),
        ).fetchone()
        if other_atividade is None:
            pytest.skip("Nenhuma outra atividade disponível no seed")

        result = main.get_card_version_menu_data(
            conn, seed["matriz_id"], [other_atividade["id"]]
        )

    # Activity not linked to any versão in this matrix → not included
    assert str(other_atividade["id"]) not in result
