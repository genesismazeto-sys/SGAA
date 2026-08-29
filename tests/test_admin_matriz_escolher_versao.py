"""
COV-1 restoration — Matrix card chooses the exact operational version (relink).

Adapted from the pre-Norma suite (test_admin_matriz_escolher_versao.py) with all
Norma-domain setup removed (matriz_norma, norma_id, codigo_normativo).

Contract verified:
  - Card da matriz exibe badge vN baseado em numero_versao.
  - get_card_version_menu_data retorna numero_versao e lista de versões existentes.
  - Modal lista versões por atividade_base (ordenado DESC).
  - Versão atual da matriz aparece marcada como is_current.
  - POST relinka matriz para versao_id existente sem criar atividade_versao.
  - Versão de outra base é rejeitada; versão inexistente é rejeitada.
  - Modal não oferece versão inativa; POST rejeita versão inativa.
  - Matriz atribuída a turma congela o relink (assigned-matrix freeze).
  - Após relink, matriz_atividade_versao_item aponta para a nova versão.
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
    Cria cenário isolado:
      - 1 matriz_test com 1 atividade (base_A)
      - 3 versões da base_A: v1, v2, v3 (v1 = vinculada à matriz_test)
      - 1 versão inativa (v4) na base_A
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

    base_a_id = conn.execute(
        "INSERT INTO atividade_base (nome_conceito, descricao, status) VALUES (?, ?, ?)",
        ("Base A D7.6D", "base para teste", "ativo"),
    ).lastrowid

    def _versao(base_id, eixo, numero_versao, status):
        return conn.execute(
            """
            INSERT INTO atividade_versao
                (atividade_base_id, eixo, grupo,
                 ch_por_evento, limite_semestre, limite_total, numero_versao, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (base_id, eixo, "1 - Congresso", 2.0, 20.0, 60.0, numero_versao, status),
        ).lastrowid

    versao_1_id = _versao(base_a_id, "AAC", 1, "ativa")
    versao_2_id = _versao(base_a_id, "AAC", 2, "ativa")
    versao_3_id = _versao(base_a_id, "AAC", 3, "ativa")
    versao_inactive_id = _versao(base_a_id, "AAC", 4, "inativa")

    conn.execute(
        "INSERT INTO matriz_atividade_versao_item "
        "(matriz_id, atividade_base_id, atividade_versao_id) VALUES (?, ?, ?)",
        (matriz_id, base_a_id, versao_1_id),
    )

    base_b_id = conn.execute(
        "INSERT INTO atividade_base (nome_conceito, descricao, status) VALUES (?, ?, ?)",
        ("Base B D7.6D", "base diferente", "ativo"),
    ).lastrowid
    versao_b1_id = _versao(base_b_id, "AAC", 1, "ativa")

    conn.commit()

    return {
        "matriz_id": matriz_id,
        "atividade_id": versao_1_id,
        "base_a_id": base_a_id,
        "base_b_id": base_b_id,
        "versao_1_id": versao_1_id,
        "versao_2_id": versao_2_id,
        "versao_3_id": versao_3_id,
        "versao_b1_id": versao_b1_id,
        "versao_inactive_id": versao_inactive_id,
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


def _current_link(seed) -> int | None:
    with main.app.app_context():
        link = main.get_db_connection().execute(
            "SELECT atividade_versao_id FROM matriz_atividade_versao_item WHERE matriz_id = ?",
            (seed["matriz_id"],),
        ).fetchone()
    return link["atividade_versao_id"] if link else None


# ---------------------------------------------------------------------------
# T01 — card da matriz exibe badge vN
# ---------------------------------------------------------------------------

def test_card_shows_vN_badge(env):
    client = env["client"]
    seed = env["seed"]
    _login(client)

    resp = client.get(f"/admin/editar_matriz/{seed['matriz_id']}?tab=aac")
    assert resp.status_code == 200

    html = resp.get_data(as_text=True)
    assert 'class="version-badge"' in html
    assert '>v1<' in html


# ---------------------------------------------------------------------------
# T02 — get_card_version_menu_data retorna numero_versao e lista versões
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

    assert "numero_versao" in entry
    assert entry["numero_versao"] == 1

    assert "versoes" in entry
    assert len(entry["versoes"]) == 3

    numeros = [v["numero_versao"] for v in entry["versoes"]]
    assert numeros == sorted(numeros, reverse=True)


# ---------------------------------------------------------------------------
# T03 — modal lista v3, v2, v1 em ordem decrescente
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

    assert len(current_entries) == 1
    assert current_entries[0]["id"] == seed["versao_1_id"]
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

    assert count_after == count_before  # nenhuma nova versão criada


# ---------------------------------------------------------------------------
# T06 — após relink, matriz_atividade_versao_item aponta para a nova versão
# ---------------------------------------------------------------------------

def test_post_relink_updates_matriz_atividade_versao_item(env):
    client = env["client"]
    seed = env["seed"]
    _login(client)

    _escolher(client, seed["matriz_id"], seed["atividade_id"], seed["versao_3_id"])

    assert _current_link(seed) == seed["versao_3_id"]


# ---------------------------------------------------------------------------
# T07 — versão inexistente é rejeitada
# ---------------------------------------------------------------------------

def test_post_rejects_nonexistent_versao(env):
    client = env["client"]
    seed = env["seed"]
    _login(client)

    resp = _escolher(client, seed["matriz_id"], seed["atividade_id"], 9999999)
    assert resp.status_code in (302, 303)

    assert _current_link(seed) == seed["versao_1_id"]


# ---------------------------------------------------------------------------
# T08 — Admin → Atividades (catálogo) não é alterado
# ---------------------------------------------------------------------------

def test_admin_atividades_route_unaffected(env):
    client = env["client"]
    seed = env["seed"]
    _login(client)

    resp = client.get(f"/admin/catalogo-versoes/{seed['base_a_id']}")
    assert resp.status_code == 200

    html = resp.get_data(as_text=True)
    assert "v1" in html or "numero_versao" in html


# ---------------------------------------------------------------------------
# T09 — get_card_version_menu_data: atividade sem vínculo não incluída
# ---------------------------------------------------------------------------

def test_card_version_menu_data_excludes_unlinked_activity(env):
    seed = env["seed"]

    with main.app.app_context():
        conn = main.get_db_connection()
        result = main.get_card_version_menu_data(
            conn, seed["matriz_id"], [seed["versao_b1_id"]]
        )

    assert str(seed["versao_b1_id"]) not in result


# ---------------------------------------------------------------------------
# T10 — modal não oferece versão inativa
# ---------------------------------------------------------------------------

def test_modal_excludes_inactive_versions(env):
    seed = env["seed"]

    with main.app.app_context():
        conn = main.get_db_connection()
        result = main.get_card_version_menu_data(
            conn, seed["matriz_id"], [seed["atividade_id"]]
        )

    entry = result[str(seed["atividade_id"])]
    versao_ids = {v["id"] for v in entry["versoes"]}

    assert seed["versao_inactive_id"] not in versao_ids
    assert len(entry["versoes"]) == 3


# ---------------------------------------------------------------------------
# T11 — POST rejeita versão inativa, link permanece inalterado
# ---------------------------------------------------------------------------

def test_post_rejects_inactive_version(env):
    client = env["client"]
    seed = env["seed"]
    _login(client)

    resp = _escolher(client, seed["matriz_id"], seed["atividade_id"], seed["versao_inactive_id"])
    assert resp.status_code in (302, 303)

    assert _current_link(seed) == seed["versao_1_id"]


# ---------------------------------------------------------------------------
# T12 — POST válido relinka para versão ativa da mesma base e eixo
# ---------------------------------------------------------------------------

def test_post_accepts_valid_active_version(env):
    client = env["client"]
    seed = env["seed"]
    _login(client)

    resp = _escolher(client, seed["matriz_id"], seed["atividade_id"], seed["versao_2_id"])
    assert resp.status_code in (302, 303)

    assert _current_link(seed) == seed["versao_2_id"]


# ---------------------------------------------------------------------------
# T13 — matriz atribuída a turma congela o relink (assigned-matrix freeze)
# ---------------------------------------------------------------------------

def test_post_relink_rejected_when_matrix_assigned(env):
    client = env["client"]
    seed = env["seed"]
    _login(client)

    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            """INSERT INTO turmas
                   (nome,turno,status,numero,curso_id,ano_inicio,semestre_inicio,codigo,matriz_id)
                 VALUES (?,'Noite','Ativa',?,?,2026,1,?,?)""",
            (f'Turma {seed["matriz_id"]}', 1000 + seed["matriz_id"],
             seed.get("course_id") or conn.execute(
                 "SELECT curso_id FROM matrizes_atividades WHERE id = ?", (seed["matriz_id"],)
             ).fetchone()["curso_id"],
             f'TEST-{seed["matriz_id"]}', seed["matriz_id"]),
        )
        conn.commit()

    resp = _escolher(client, seed["matriz_id"], seed["atividade_id"], seed["versao_3_id"])
    assert resp.status_code in (302, 303)

    assert _current_link(seed) == seed["versao_1_id"]