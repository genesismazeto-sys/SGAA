"""
Testes focados — D7.6E-MATRIX-DEFAULTS-TO-LATEST-ACTIVE-VERSION

Contrato verificado:
  - Ao vincular atividade à matriz, cria link para última versão ATIVA da base
  - Versão inativa mais recente é ignorada; usa a ativa mais recente
  - Escolha manual existente (matriz_atividade_versao_item) nunca é sobrescrita
  - POST de escolha manual D7.6D continua funcionando
  - Nenhum INSERT INTO atividade_versao ocorre ao salvar atividades na matriz
  - Atividade sem versão ativa: nenhum link criado (comportamento documentado)
  - Card continua exibindo vN via matriz_atividade_versao_item
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
# Seed — dados específicos D7.6E
# ---------------------------------------------------------------------------

def _seed_d76e(conn) -> dict:
    """
    Insere cenário complementar ao seed de referência para D7.6E:

    Bases e versões (criadas além do seed de referência):
      base_A: v1(ativa), v2(ativa)         → default esperado: v2
      base_B: v1(ativa), v2(inativa), v3(ativa) → default esperado: v3
      base_C: v1(ativa), v2(ativa), v3(inativa) → default esperado: v2
      base_D: v1(inativa) apenas            → sem link criado

    Atividades legadas e mapeamentos correspondentes:
      atividade_A → base_A
      atividade_B → base_B
      atividade_C → base_C
      atividade_D → base_D

    Matriz nova (sem atividades inicialmente):
      matriz_test — usada para simular o fluxo de vinculação
    """
    curso_id = conn.execute("SELECT id FROM cursos LIMIT 1").fetchone()["id"]
    norma_id = conn.execute("SELECT id FROM norma_atividade LIMIT 1").fetchone()["id"]

    # Matriz vazia para testes de default
    matriz_id = conn.execute(
        """
        INSERT INTO matrizes_atividades
            (curso_id, nome, versao, status, horas_aac_obrigatorias, horas_extensao_obrigatorias)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (curso_id, "Matriz D7.6E", "D76E-test", "ativa", 100, 50),
    ).lastrowid

    def _new_atividade(nome: str) -> int:
        return conn.execute(
            """
            INSERT INTO atividades (nome, grupo, tipo_atividade, descricao, limite_horas)
            VALUES (?, ?, ?, ?, ?)
            """,
            (nome, "1 - Grupo D7.6E", "Acadêmica Complementar", "desc", 100),
        ).lastrowid

    def _new_base(nome: str) -> int:
        return conn.execute(
            "INSERT INTO atividade_base (nome_conceito, descricao, status) VALUES (?, ?, ?)",
            (nome, "base D7.6E", "ativo"),
        ).lastrowid

    def _map(ativ_id: int, base_id: int):
        conn.execute(
            "INSERT INTO atividade_legacy_map (atividade_id_legacy, atividade_base_id, status) VALUES (?, ?, ?)",
            (ativ_id, base_id, "mapeada"),
        )

    def _versao(base_id: int, numero_versao: int, status: str, norma: int = None) -> int:
        n = norma if norma is not None else norma_id
        return conn.execute(
            """
            INSERT INTO atividade_versao
                (atividade_base_id, norma_id, codigo_normativo, eixo, grupo,
                 ch_por_evento, limite_semestre, limite_total, numero_versao, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (base_id, n, f"NRM-v{numero_versao}", "AAC", "1 - Grupo D7.6E",
             2.0, 20.0, 60.0, numero_versao, status),
        ).lastrowid

    # base_A: v1(ativa), v2(ativa) → default: v2
    ativ_a = _new_atividade("Atividade A D7.6E")
    base_a = _new_base("Base A D7.6E")
    _map(ativ_a, base_a)
    versao_a1 = _versao(base_a, 1, "ativa")
    versao_a2 = _versao(base_a, 2, "ativa")

    # base_B: v1(ativa), v2(inativa), v3(ativa) → default: v3
    ativ_b = _new_atividade("Atividade B D7.6E")
    base_b = _new_base("Base B D7.6E")
    _map(ativ_b, base_b)
    versao_b1 = _versao(base_b, 1, "ativa")
    versao_b2 = _versao(base_b, 2, "inativa")
    versao_b3 = _versao(base_b, 3, "ativa")

    # base_C: v1(ativa), v2(ativa), v3(inativa) → default: v2
    ativ_c = _new_atividade("Atividade C D7.6E")
    base_c = _new_base("Base C D7.6E")
    _map(ativ_c, base_c)
    versao_c1 = _versao(base_c, 1, "ativa")
    versao_c2 = _versao(base_c, 2, "ativa")
    versao_c3 = _versao(base_c, 3, "inativa")

    # base_D: v1(inativa) apenas → sem link criado
    ativ_d = _new_atividade("Atividade D D7.6E")
    base_d = _new_base("Base D D7.6E")
    _map(ativ_d, base_d)
    versao_d1 = _versao(base_d, 1, "inativa")

    conn.commit()

    return {
        "matriz_id": matriz_id,
        "ativ_a": ativ_a, "base_a": base_a, "versao_a1": versao_a1, "versao_a2": versao_a2,
        "ativ_b": ativ_b, "base_b": base_b, "versao_b1": versao_b1, "versao_b2": versao_b2, "versao_b3": versao_b3,
        "ativ_c": ativ_c, "base_c": base_c, "versao_c1": versao_c1, "versao_c2": versao_c2, "versao_c3": versao_c3,
        "ativ_d": ativ_d, "base_d": base_d, "versao_d1": versao_d1,
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "d76e_latest_active.db") as e:
        with main.app.app_context():
            conn = main.get_db_connection()
            seed = _seed_d76e(conn)
        e["seed"] = seed
        yield e


def _login(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["user_type"] = "admin"
        sess["user_name"] = "Admin D7.6E"


def _save_activities(client, matriz_id, activity_ids, tab="aac"):
    """POST to save selected_activity_ids on a matrix tab."""
    return client.post(
        f"/admin/editar_matriz/{matriz_id}?tab={tab}",
        data={"active_tab": tab, "selected_activity_ids": [str(i) for i in activity_ids]},
        follow_redirects=False,
    )


def _get_versao_link(matriz_id, base_id) -> int | None:
    """Return the linked atividade_versao_id for (matriz_id, base_id), or None."""
    with main.app.app_context():
        conn = main.get_db_connection()
        link = main.get_vinculo_versao_da_matriz(conn, matriz_id, base_id)
    return link["atividade_versao_id"] if link else None


# ---------------------------------------------------------------------------
# T01 — base com v1(ativa) e v2(ativa): default usa v2 (maior numero_versao ativa)
# ---------------------------------------------------------------------------

def test_default_uses_latest_active_when_multiple_active(env):
    client = env["client"]
    seed = env["seed"]
    _login(client)

    resp = _save_activities(client, seed["matriz_id"], [seed["ativ_a"]])
    assert resp.status_code in (302, 303)

    assert _get_versao_link(seed["matriz_id"], seed["base_a"]) == seed["versao_a2"]


# ---------------------------------------------------------------------------
# T02 — base com v1(ativa), v2(inativa), v3(ativa): default usa v3
# ---------------------------------------------------------------------------

def test_default_skips_inactive_uses_highest_active(env):
    client = env["client"]
    seed = env["seed"]
    _login(client)

    resp = _save_activities(client, seed["matriz_id"], [seed["ativ_b"]])
    assert resp.status_code in (302, 303)

    assert _get_versao_link(seed["matriz_id"], seed["base_b"]) == seed["versao_b3"]


# ---------------------------------------------------------------------------
# T03 — base com v1(ativa), v2(ativa), v3(inativa): default usa v2 (v3 ignorada)
# ---------------------------------------------------------------------------

def test_default_ignores_inactive_higher_version(env):
    client = env["client"]
    seed = env["seed"]
    _login(client)

    resp = _save_activities(client, seed["matriz_id"], [seed["ativ_c"]])
    assert resp.status_code in (302, 303)

    assert _get_versao_link(seed["matriz_id"], seed["base_c"]) == seed["versao_c2"]


# ---------------------------------------------------------------------------
# T04 — adicionar atividade à matriz existente cria vínculo para última ativa
# ---------------------------------------------------------------------------

def test_add_activity_to_existing_matrix_links_latest_active(env):
    client = env["client"]
    seed = env["seed"]
    _login(client)

    # Start: no link exists
    assert _get_versao_link(seed["matriz_id"], seed["base_a"]) is None

    _save_activities(client, seed["matriz_id"], [seed["ativ_a"]])

    assert _get_versao_link(seed["matriz_id"], seed["base_a"]) == seed["versao_a2"]


# ---------------------------------------------------------------------------
# T05 — escolha manual existente não é sobrescrita ao re-salvar a lista
# ---------------------------------------------------------------------------

def test_existing_manual_link_not_overwritten(env):
    client = env["client"]
    seed = env["seed"]
    _login(client)

    # Add activity → auto-links to versao_a2
    _save_activities(client, seed["matriz_id"], [seed["ativ_a"]])
    assert _get_versao_link(seed["matriz_id"], seed["base_a"]) == seed["versao_a2"]

    # Admin manually picks v1
    with main.app.app_context():
        conn = main.get_db_connection()
        main._set_versao_da_matriz_para_base(conn, seed["matriz_id"], seed["base_a"], seed["versao_a1"])
        conn.commit()
    assert _get_versao_link(seed["matriz_id"], seed["base_a"]) == seed["versao_a1"]

    # Re-save the same activity list — must NOT revert to v2
    _save_activities(client, seed["matriz_id"], [seed["ativ_a"]])
    assert _get_versao_link(seed["matriz_id"], seed["base_a"]) == seed["versao_a1"]


# ---------------------------------------------------------------------------
# T06 — POST de escolha manual D7.6D continua funcionando após D7.6E
# ---------------------------------------------------------------------------

def test_d76d_manual_relink_still_works(env):
    client = env["client"]
    seed = env["seed"]
    _login(client)

    # Add activity → auto-links to versao_a2
    _save_activities(client, seed["matriz_id"], [seed["ativ_a"]])
    assert _get_versao_link(seed["matriz_id"], seed["base_a"]) == seed["versao_a2"]

    # Use D7.6D relink route to choose v1
    resp = client.post(
        f"/admin/matrizes/{seed['matriz_id']}/atividades/{seed['ativ_a']}/nova-versao",
        data={"active_tab": "aac", "versao_id": str(seed["versao_a1"])},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)

    assert _get_versao_link(seed["matriz_id"], seed["base_a"]) == seed["versao_a1"]


# ---------------------------------------------------------------------------
# T07 — nenhum INSERT INTO atividade_versao ao salvar atividades na matriz
# ---------------------------------------------------------------------------

def test_no_new_atividade_versao_created_on_activity_save(env):
    client = env["client"]
    seed = env["seed"]
    _login(client)

    with main.app.app_context():
        conn = main.get_db_connection()
        count_before = conn.execute("SELECT COUNT(*) AS c FROM atividade_versao").fetchone()["c"]

    _save_activities(client, seed["matriz_id"], [seed["ativ_a"], seed["ativ_b"], seed["ativ_c"]])

    with main.app.app_context():
        conn = main.get_db_connection()
        count_after = conn.execute("SELECT COUNT(*) AS c FROM atividade_versao").fetchone()["c"]

    assert count_after == count_before


# ---------------------------------------------------------------------------
# T08 — card exibe vN após vínculo criado por default (regressão badge)
# ---------------------------------------------------------------------------

def test_card_shows_vN_badge_after_default_link(env):
    client = env["client"]
    seed = env["seed"]
    _login(client)

    _save_activities(client, seed["matriz_id"], [seed["ativ_a"]])

    resp = client.get(f"/admin/editar_matriz/{seed['matriz_id']}?tab=aac")
    assert resp.status_code == 200

    html = resp.get_data(as_text=True)
    assert 'class="version-badge"' in html
    # versao_a2 has numero_versao=2
    assert ">v2<" in html


# ---------------------------------------------------------------------------
# T09 — base sem versão ativa: nenhum link criado (comportamento documentado)
# ---------------------------------------------------------------------------

def test_no_active_versao_no_link_created(env):
    client = env["client"]
    seed = env["seed"]
    _login(client)

    # ativ_d → base_d has only v1(inativa)
    _save_activities(client, seed["matriz_id"], [seed["ativ_d"]])

    assert _get_versao_link(seed["matriz_id"], seed["base_d"]) is None
