"""
Testes focados — D7.5D-PATCH-CARD-VERSION-MENU
Rota: POST /admin/matrizes/<id>/atividades/<id>/nova-versao

Contrato verificado:
  - UI: botão ⋮ no painel direito; modal com select de norma
  - Backend: criar OU reusar atividade_versao; relinkar apenas matriz atual
  - UNIQUE(atividade_base_id, norma_id): nunca duplicar
  - versao_anterior_id aponta para versão substituída
  - Matrizes antigas preservadas
  - Rollback total em erro intermediário
  - CSRF obrigatório
"""
from __future__ import annotations

import os
import re
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main
from tests.versioned_test_support import isolated_versioned_app_env


# ---------------------------------------------------------------------------
# Seed D7.5D
# ---------------------------------------------------------------------------

def _seed_d75d_scenario(conn) -> dict:
    """
    Cria, dentro do DB isolado do seed de referência:
      - matriz_test: norma_1 (AAC-rev5) + norma_2 (AAC-rev6) em matriz_norma
      - matriz_old:  norma_1 somente
      - 1 atividade AAC, 1 base, 1 legacy_map, versao_1 (norma_1)
      - Ambas as matrizes vinculadas à atividade e à versao_1
    Normas 1/2/3 já existem no seed de referência.
    """
    curso_id = conn.execute("SELECT id FROM cursos LIMIT 1").fetchone()["id"]

    matriz_test_id = conn.execute(
        """
        INSERT INTO matrizes_atividades
            (curso_id, nome, versao, status, horas_aac_obrigatorias, horas_extensao_obrigatorias)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (curso_id, "Matriz Teste D75D", "D75D-test", "ativa", 100, 50),
    ).lastrowid

    matriz_old_id = conn.execute(
        """
        INSERT INTO matrizes_atividades
            (curso_id, nome, versao, status, horas_aac_obrigatorias, horas_extensao_obrigatorias)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (curso_id, "Matriz Antiga D75D", "D75D-old", "ativa", 100, 50),
    ).lastrowid

    # norma_1=1 (AAC-rev5 ativa), norma_2=2 (AAC-rev6 ativa), norma_3=3 (AEU-rev1 ativa)
    norma_1_id = 1
    norma_2_id = 2
    norma_3_id = 3

    conn.execute("INSERT INTO matriz_norma (matriz_id, norma_id) VALUES (?, ?)", (matriz_test_id, norma_1_id))
    conn.execute("INSERT INTO matriz_norma (matriz_id, norma_id) VALUES (?, ?)", (matriz_test_id, norma_2_id))
    conn.execute("INSERT INTO matriz_norma (matriz_id, norma_id) VALUES (?, ?)", (matriz_old_id, norma_1_id))

    atividade_id = conn.execute(
        """
        INSERT INTO atividades (nome, grupo, tipo_atividade, descricao, limite_horas)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("Atividade Piloto D7.5D", "7 - Piloto D75D", "Acadêmica Complementar", "Atividade para testes D7.5D", 100),
    ).lastrowid

    base_id = conn.execute(
        "INSERT INTO atividade_base (nome_conceito, descricao, status) VALUES (?, ?, ?)",
        ("Base Piloto D75D", "Base para testes D7.5D", "ativo"),
    ).lastrowid

    conn.execute(
        "INSERT INTO atividade_legacy_map (atividade_id_legacy, atividade_base_id, status) VALUES (?, ?, ?)",
        (atividade_id, base_id, "mapeada"),
    )

    versao_1_id = conn.execute(
        """
        INSERT INTO atividade_versao
            (atividade_base_id, norma_id, codigo_normativo, eixo, grupo,
             ch_por_evento, limite_semestre, limite_total, observacao_aluno,
             observacao_admin, documentos_json, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (base_id, norma_1_id, "AAC-rev5", "AAC", "7 - Piloto D75D",
         2.0, 20.0, 60.0, "Obs aluno piloto", "Obs admin piloto", None, "ativa"),
    ).lastrowid

    conn.execute("INSERT INTO matrizes_atividades_itens (matriz_id, atividade_id) VALUES (?, ?)", (matriz_test_id, atividade_id))
    conn.execute("INSERT INTO matrizes_atividades_itens (matriz_id, atividade_id) VALUES (?, ?)", (matriz_old_id, atividade_id))

    conn.execute("INSERT INTO matriz_atividade_versao_item (matriz_id, atividade_versao_id) VALUES (?, ?)", (matriz_test_id, versao_1_id))
    conn.execute("INSERT INTO matriz_atividade_versao_item (matriz_id, atividade_versao_id) VALUES (?, ?)", (matriz_old_id, versao_1_id))

    conn.commit()

    return {
        "matriz_test_id": matriz_test_id,
        "matriz_old_id": matriz_old_id,
        "atividade_id": atividade_id,
        "base_id": base_id,
        "versao_1_id": versao_1_id,
        "norma_1_id": norma_1_id,
        "norma_2_id": norma_2_id,
        "norma_3_id": norma_3_id,
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def d75d_env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "d75d_nova_versao.db") as env:
        with main.app.app_context():
            conn = main.get_db_connection()
            seed_ids = _seed_d75d_scenario(conn)
        env["d75d_seed"] = seed_ids
        yield env


@pytest.fixture()
def d75d_env_csrf(tmp_path):
    with isolated_versioned_app_env(tmp_path, "d75d_csrf.db") as env:
        with main.app.app_context():
            conn = main.get_db_connection()
            seed_ids = _seed_d75d_scenario(conn)
        env["d75d_seed"] = seed_ids
        original_enabled = main.app.config.get("WTF_CSRF_ENABLED")
        original_check_default = main.app.config.get("WTF_CSRF_CHECK_DEFAULT")
        main.app.config["WTF_CSRF_ENABLED"] = True
        main.app.config["WTF_CSRF_CHECK_DEFAULT"] = True
        try:
            yield env
        finally:
            main.app.config["WTF_CSRF_ENABLED"] = original_enabled
            main.app.config["WTF_CSRF_CHECK_DEFAULT"] = original_check_default


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login_admin(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["user_type"] = "admin"
        sess["user_name"] = "Administrador"


def _post_nova_versao(client, matriz_id, atividade_id, norma_id, active_tab="aac"):
    return client.post(
        f"/admin/matrizes/{matriz_id}/atividades/{atividade_id}/nova-versao",
        data={"active_tab": active_tab, "norma_id": str(norma_id)},
        follow_redirects=False,
    )


# ---------------------------------------------------------------------------
# T01 — UI: botão ⋮ aparece no painel direito para atividade com norma alternativa
# ---------------------------------------------------------------------------

def test_get_renders_version_menu_button_in_right_panel(d75d_env):
    client = d75d_env["client"]
    seed = d75d_env["d75d_seed"]
    _login_admin(client)

    resp = client.get(f"/admin/editar_matriz/{seed['matriz_test_id']}?tab=aac")
    assert resp.status_code == 200

    html = resp.get_data(as_text=True)
    assert f'data-open-version-modal="{seed["atividade_id"]}"' in html


# ---------------------------------------------------------------------------
# T02 — UI: modal HTML está presente na página
# ---------------------------------------------------------------------------

def test_get_version_modal_present_in_page(d75d_env):
    client = d75d_env["client"]
    seed = d75d_env["d75d_seed"]
    _login_admin(client)

    resp = client.get(f"/admin/editar_matriz/{seed['matriz_test_id']}?tab=aac")
    assert resp.status_code == 200

    html = resp.get_data(as_text=True)
    assert 'id="matriz-version-modal"' in html
    assert 'id="version-modal-norma-select"' in html


# ---------------------------------------------------------------------------
# T03 — UI: JSON versionMenuData contém opção norma_2 para a atividade
# ---------------------------------------------------------------------------

def test_get_version_menu_data_json_has_norma_options(d75d_env):
    client = d75d_env["client"]
    seed = d75d_env["d75d_seed"]
    _login_admin(client)

    resp = client.get(f"/admin/editar_matriz/{seed['matriz_test_id']}?tab=aac")
    assert resp.status_code == 200

    html = resp.get_data(as_text=True)
    # JSON block with the activity key and the alternative norma
    assert f'"{seed["atividade_id"]}"' in html or f"'{seed['atividade_id']}'" in html
    assert '"AAC-rev6"' in html


# ---------------------------------------------------------------------------
# T04 — POST happy path: nova versão criada e vinculada à matriz atual
# ---------------------------------------------------------------------------

def test_post_creates_new_versao_and_relinks_matrix(d75d_env):
    client = d75d_env["client"]
    seed = d75d_env["d75d_seed"]
    _login_admin(client)

    with main.app.app_context():
        conn = main.get_db_connection()
        count_before = conn.execute("SELECT COUNT(*) AS c FROM atividade_versao").fetchone()["c"]

    resp = _post_nova_versao(client, seed["matriz_test_id"], seed["atividade_id"], seed["norma_2_id"])
    assert resp.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        count_after = conn.execute("SELECT COUNT(*) AS c FROM atividade_versao").fetchone()["c"]
        assert count_after == count_before + 1

        new_versao = conn.execute(
            "SELECT * FROM atividade_versao WHERE atividade_base_id = ? AND norma_id = ?",
            (seed["base_id"], seed["norma_2_id"]),
        ).fetchone()
        assert new_versao is not None
        assert new_versao["status"] == "ativa"

        link = conn.execute(
            "SELECT av.norma_id FROM matriz_atividade_versao_item mavi"
            " JOIN atividade_versao av ON av.id = mavi.atividade_versao_id"
            " WHERE mavi.matriz_id = ?",
            (seed["matriz_test_id"],),
        ).fetchone()
        assert link is not None
        assert link["norma_id"] == seed["norma_2_id"]


# ---------------------------------------------------------------------------
# T05 — POST: campos copiados da versão atual; versao_anterior_id correto
# ---------------------------------------------------------------------------

def test_post_new_versao_has_correct_fields_and_versao_anterior_id(d75d_env):
    client = d75d_env["client"]
    seed = d75d_env["d75d_seed"]
    _login_admin(client)

    resp = _post_nova_versao(client, seed["matriz_test_id"], seed["atividade_id"], seed["norma_2_id"])
    assert resp.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        new_versao = conn.execute(
            "SELECT * FROM atividade_versao WHERE atividade_base_id = ? AND norma_id = ?",
            (seed["base_id"], seed["norma_2_id"]),
        ).fetchone()
        assert new_versao is not None

        # Campos copiados da versao_1
        assert new_versao["eixo"] == "AAC"
        assert new_versao["grupo"] == "7 - Piloto D75D"
        assert new_versao["ch_por_evento"] == 2.0
        assert new_versao["limite_semestre"] == 20.0
        assert new_versao["limite_total"] == 60.0
        assert new_versao["observacao_aluno"] == "Obs aluno piloto"
        assert new_versao["observacao_admin"] == "Obs admin piloto"

        # codigo_normativo = código da nova norma, não da antiga
        assert new_versao["codigo_normativo"] == "AAC-rev6"

        # versao_anterior_id aponta para versao_1
        assert new_versao["versao_anterior_id"] == seed["versao_1_id"]


# ---------------------------------------------------------------------------
# T06 — POST: apenas a matriz atual é revinculada; matriz antiga preservada
# ---------------------------------------------------------------------------

def test_post_relinks_only_current_matrix(d75d_env):
    client = d75d_env["client"]
    seed = d75d_env["d75d_seed"]
    _login_admin(client)

    resp = _post_nova_versao(client, seed["matriz_test_id"], seed["atividade_id"], seed["norma_2_id"])
    assert resp.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()

        # matriz_test agora tem versao para norma_2
        link_test = conn.execute(
            "SELECT av.norma_id FROM matriz_atividade_versao_item mavi"
            " JOIN atividade_versao av ON av.id = mavi.atividade_versao_id"
            " WHERE mavi.matriz_id = ?",
            (seed["matriz_test_id"],),
        ).fetchone()
        assert link_test["norma_id"] == seed["norma_2_id"]

        # matriz_old ainda aponta para versao_1 (norma_1)
        link_old = conn.execute(
            "SELECT av.norma_id FROM matriz_atividade_versao_item mavi"
            " JOIN atividade_versao av ON av.id = mavi.atividade_versao_id"
            " WHERE mavi.matriz_id = ?",
            (seed["matriz_old_id"],),
        ).fetchone()
        assert link_old["norma_id"] == seed["norma_1_id"]


# ---------------------------------------------------------------------------
# T07 — POST: se versão (base, norma_2) já existe, reusa sem duplicar
# ---------------------------------------------------------------------------

def test_post_reuses_existing_versao_without_duplicate(d75d_env):
    client = d75d_env["client"]
    seed = d75d_env["d75d_seed"]
    _login_admin(client)

    with main.app.app_context():
        conn = main.get_db_connection()
        preexisting_id = conn.execute(
            """
            INSERT INTO atividade_versao
                (atividade_base_id, norma_id, codigo_normativo, eixo, grupo, numero_versao, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (seed["base_id"], seed["norma_2_id"], "AAC-rev6", "AAC", "7 - Pre-existing",
             main.get_next_numero_versao(conn, seed["base_id"]), "ativa"),
        ).lastrowid
        conn.commit()
        count_before = conn.execute("SELECT COUNT(*) AS c FROM atividade_versao").fetchone()["c"]

    resp = _post_nova_versao(client, seed["matriz_test_id"], seed["atividade_id"], seed["norma_2_id"])
    assert resp.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        count_after = conn.execute("SELECT COUNT(*) AS c FROM atividade_versao").fetchone()["c"]
        assert count_after == count_before  # nenhuma nova versão criada

        link = conn.execute(
            "SELECT atividade_versao_id FROM matriz_atividade_versao_item WHERE matriz_id = ?",
            (seed["matriz_test_id"],),
        ).fetchone()
        assert link["atividade_versao_id"] == preexisting_id


# ---------------------------------------------------------------------------
# T08 — POST: rejeita norma não presente em matriz_norma da matriz
# ---------------------------------------------------------------------------

def test_post_rejects_norma_not_in_matriz_norma(d75d_env):
    client = d75d_env["client"]
    seed = d75d_env["d75d_seed"]
    _login_admin(client)

    # Cria norma AAC fora do escopo da matriz (não adicionada em matriz_norma)
    with main.app.app_context():
        conn = main.get_db_connection()
        orphan_norma_id = conn.execute(
            "INSERT INTO norma_atividade (codigo, eixo, revisao, nome, status) VALUES (?, ?, ?, ?, ?)",
            ("AAC-orphan", "AAC", "orphan", "Norma fora do escopo", "ativa"),
        ).lastrowid
        conn.commit()

    resp = _post_nova_versao(client, seed["matriz_test_id"], seed["atividade_id"], orphan_norma_id)
    assert resp.status_code in (302, 303)

    # Link da matriz deve continuar na norma_1
    with main.app.app_context():
        conn = main.get_db_connection()
        link = conn.execute(
            "SELECT av.norma_id FROM matriz_atividade_versao_item mavi"
            " JOIN atividade_versao av ON av.id = mavi.atividade_versao_id"
            " WHERE mavi.matriz_id = ?",
            (seed["matriz_test_id"],),
        ).fetchone()
        assert link["norma_id"] == seed["norma_1_id"]


# ---------------------------------------------------------------------------
# T09 — POST: rejeita norma inativa
# ---------------------------------------------------------------------------

def test_post_rejects_inactive_norma(d75d_env):
    client = d75d_env["client"]
    seed = d75d_env["d75d_seed"]
    _login_admin(client)

    with main.app.app_context():
        conn = main.get_db_connection()
        inactive_id = conn.execute(
            "INSERT INTO norma_atividade (codigo, eixo, revisao, nome, status) VALUES (?, ?, ?, ?, ?)",
            ("AAC-inativa", "AAC", "rev-inativa", "Norma inativa", "inativa"),
        ).lastrowid
        conn.execute("INSERT INTO matriz_norma (matriz_id, norma_id) VALUES (?, ?)", (seed["matriz_test_id"], inactive_id))
        conn.commit()

    resp = _post_nova_versao(client, seed["matriz_test_id"], seed["atividade_id"], inactive_id)
    assert resp.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        link = conn.execute(
            "SELECT av.norma_id FROM matriz_atividade_versao_item mavi"
            " JOIN atividade_versao av ON av.id = mavi.atividade_versao_id"
            " WHERE mavi.matriz_id = ?",
            (seed["matriz_test_id"],),
        ).fetchone()
        assert link["norma_id"] == seed["norma_1_id"]


# ---------------------------------------------------------------------------
# T10 — POST: rejeita norma com eixo incompatível (AEU para atividade AAC)
# ---------------------------------------------------------------------------

def test_post_rejects_wrong_eixo_norma(d75d_env):
    client = d75d_env["client"]
    seed = d75d_env["d75d_seed"]
    _login_admin(client)

    # Adiciona norma AEU ao escopo da matriz para passar a validação de norma_in_matriz
    # mas falhar na validação de eixo
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "INSERT INTO matriz_norma (matriz_id, norma_id) VALUES (?, ?)",
            (seed["matriz_test_id"], seed["norma_3_id"]),
        )
        conn.commit()

    resp = _post_nova_versao(client, seed["matriz_test_id"], seed["atividade_id"], seed["norma_3_id"])
    assert resp.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        link = conn.execute(
            "SELECT av.norma_id FROM matriz_atividade_versao_item mavi"
            " JOIN atividade_versao av ON av.id = mavi.atividade_versao_id"
            " WHERE mavi.matriz_id = ?",
            (seed["matriz_test_id"],),
        ).fetchone()
        assert link["norma_id"] == seed["norma_1_id"]


# ---------------------------------------------------------------------------
# T11 — POST: rejeita norma igual à atual (flash info, sem escrita)
# ---------------------------------------------------------------------------

def test_post_rejects_same_norma_as_current(d75d_env):
    client = d75d_env["client"]
    seed = d75d_env["d75d_seed"]
    _login_admin(client)

    with main.app.app_context():
        conn = main.get_db_connection()
        count_before = conn.execute("SELECT COUNT(*) AS c FROM atividade_versao").fetchone()["c"]

    resp = _post_nova_versao(client, seed["matriz_test_id"], seed["atividade_id"], seed["norma_1_id"])
    assert resp.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        count_after = conn.execute("SELECT COUNT(*) AS c FROM atividade_versao").fetchone()["c"]
        assert count_after == count_before


# ---------------------------------------------------------------------------
# T12 — POST: rejeita norma_id ausente ou inválido
# ---------------------------------------------------------------------------

def test_post_rejects_missing_norma_id(d75d_env):
    client = d75d_env["client"]
    seed = d75d_env["d75d_seed"]
    _login_admin(client)

    with main.app.app_context():
        conn = main.get_db_connection()
        count_before = conn.execute("SELECT COUNT(*) AS c FROM atividade_versao").fetchone()["c"]

    # Envia sem norma_id
    resp = client.post(
        f"/admin/matrizes/{seed['matriz_test_id']}/atividades/{seed['atividade_id']}/nova-versao",
        data={"active_tab": "aac"},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        count_after = conn.execute("SELECT COUNT(*) AS c FROM atividade_versao").fetchone()["c"]
        assert count_after == count_before


# ---------------------------------------------------------------------------
# T13 — POST: rejeita atividade fora do escopo da matriz
# ---------------------------------------------------------------------------

def test_post_rejects_activity_not_in_matrix_scope(d75d_env):
    client = d75d_env["client"]
    seed = d75d_env["d75d_seed"]
    _login_admin(client)

    # Atividade do seed de referência (id=1) NÃO está no matriz_test
    resp = client.post(
        f"/admin/matrizes/{seed['matriz_test_id']}/atividades/1/nova-versao",
        data={"active_tab": "aac", "norma_id": str(seed["norma_2_id"])},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)

    # A atividade de referência não deve ter uma nova versão criada no matriz_test
    with main.app.app_context():
        conn = main.get_db_connection()
        links_for_test_matrix = conn.execute(
            "SELECT COUNT(*) AS c FROM matriz_atividade_versao_item WHERE matriz_id = ?",
            (seed["matriz_test_id"],),
        ).fetchone()["c"]
        # Deve continuar com exatamente 1 vínculo (a atividade D75D)
        assert links_for_test_matrix == 1


# ---------------------------------------------------------------------------
# T14 — POST: rollback total quando _set_versao_da_matriz_para_base levanta erro
# ---------------------------------------------------------------------------

def test_post_rolls_back_on_link_error(d75d_env, monkeypatch):
    client = d75d_env["client"]
    seed = d75d_env["d75d_seed"]
    _login_admin(client)

    with main.app.app_context():
        conn = main.get_db_connection()
        count_before = conn.execute("SELECT COUNT(*) AS c FROM atividade_versao").fetchone()["c"]
        link_before = conn.execute(
            "SELECT atividade_versao_id FROM matriz_atividade_versao_item WHERE matriz_id = ?",
            (seed["matriz_test_id"],),
        ).fetchone()["atividade_versao_id"]

    def _broken_set(conn, matriz_id, base_id, versao_id):
        raise Exception("Simulated link failure for rollback test")

    monkeypatch.setattr(main, "_set_versao_da_matriz_para_base", _broken_set)

    resp = _post_nova_versao(client, seed["matriz_test_id"], seed["atividade_id"], seed["norma_2_id"])
    assert resp.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        count_after = conn.execute("SELECT COUNT(*) AS c FROM atividade_versao").fetchone()["c"]
        link_after = conn.execute(
            "SELECT atividade_versao_id FROM matriz_atividade_versao_item WHERE matriz_id = ?",
            (seed["matriz_test_id"],),
        ).fetchone()["atividade_versao_id"]

    assert count_after == count_before  # INSERT revertido
    assert link_after == link_before    # link inalterado


# ---------------------------------------------------------------------------
# T15 — POST: CSRF obrigatório
# ---------------------------------------------------------------------------

def test_post_requires_csrf(d75d_env_csrf):
    client = d75d_env_csrf["client"]
    seed = d75d_env_csrf["d75d_seed"]
    _login_admin(client)

    # Busca o token CSRF da página
    page = client.get(f"/admin/editar_matriz/{seed['matriz_test_id']}?tab=aac")
    assert page.status_code == 200

    csrf_match = re.search(r'name="csrf_token"\s+value="([^"]+)"', page.get_data(as_text=True))
    assert csrf_match is not None, "csrf_token ausente na página"
    csrf_token = csrf_match.group(1)

    # Sem token: deve retornar 400
    no_token = client.post(
        f"/admin/matrizes/{seed['matriz_test_id']}/atividades/{seed['atividade_id']}/nova-versao",
        data={"active_tab": "aac", "norma_id": str(seed["norma_2_id"])},
        follow_redirects=False,
    )
    assert no_token.status_code == 400

    # Com token: deve redirecionar (criação bem-sucedida)
    with_token = client.post(
        f"/admin/matrizes/{seed['matriz_test_id']}/atividades/{seed['atividade_id']}/nova-versao",
        data={"active_tab": "aac", "norma_id": str(seed["norma_2_id"]), "csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert with_token.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        new_versao = conn.execute(
            "SELECT id FROM atividade_versao WHERE atividade_base_id = ? AND norma_id = ?",
            (seed["base_id"], seed["norma_2_id"]),
        ).fetchone()
    assert new_versao is not None
