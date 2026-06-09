"""
D7.2B4-PATCH1 — Testes de vínculo explícito matriz → atividade_versao.

Cobre:
  1.  GET da página admin de versões da matriz retorna 200.
  2.  UI mostra bases do escopo da matriz.
  3.  UI oferece apenas versões ativas.
  4.  UI não oferece versões rascunho, inativas, descontinuadas ou substituídas.
  5.  POST definir exige norma vinculada em matriz_norma.
  6.  POST definir define versão ativa válida para matriz+base.
  7.  POST definir troca versão da mesma base substituindo a anterior, sem criar ambiguidade.
  8.  POST remover remove vínculo.
  9.  Após definir vínculo, resolver_versao_por_matriz resolve a versão.
 10.  Após remover vínculo, resolver retorna ausência de versão para a matriz.
 11.  POST definir rejeita versão de base fora do escopo da matriz.
 12.  POST definir rejeita versão cuja norma não está em matriz_norma.
 13.  Não há fallback para primeira ativa sem vínculo explícito.
 14.  CSRF real presente nos formulários POST.
"""
from __future__ import annotations

import os
import sys
import uuid

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main
from tests.versioned_test_support import isolated_versioned_app_env


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def versioned_env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "d72b4_link.db") as env:
        yield env


def _login_admin(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 999999
        sess["user_type"] = "admin"
        sess["user_name"] = "Admin Link Test"


# ---------------------------------------------------------------------------
# Seed helper: fresh isolated matrix with controlled state
# ---------------------------------------------------------------------------


def _seed_fresh_matrix() -> dict:
    """
    Inserts an isolated matrix with: 1 curso, 1 matriz, 1 norma ativa (AAC),
    1 atividade_base, 1 atividade legada, 1 versao ativa.
    matriz_norma and matrizes_atividades_itens are wired up.
    NO link in matriz_atividade_versao_item (write tests set this explicitly).
    Returns a dict with all relevant ids.
    """
    t = uuid.uuid4().hex[:8]
    with main.app.app_context():
        conn = main.get_db_connection()

        curso_id = conn.execute(
            "INSERT INTO cursos (nome, codigo, duracao_periodos, status)"
            " VALUES (?, ?, 8, 'ativo') RETURNING id",
            (f"Curso B4 {t}", f"B4-{t}"),
        ).fetchone()["id"]

        matriz_id = conn.execute(
            "INSERT INTO matrizes_atividades (curso_id, nome, versao, status)"
            " VALUES (?, ?, '2026.1', 'ativa') RETURNING id",
            (curso_id, f"Matriz B4 {t}"),
        ).fetchone()["id"]

        norma_id = conn.execute(
            "INSERT INTO norma_atividade (codigo, eixo, revisao, nome, status)"
            " VALUES (?, 'AAC', 'rev1', ?, 'ativa') RETURNING id",
            (f"B4NRM{t}", f"Norma B4 {t}"),
        ).fetchone()["id"]

        base_id = conn.execute(
            "INSERT INTO atividade_base (nome_conceito, descricao, status)"
            " VALUES (?, 'Base B4', 'ativo') RETURNING id",
            (f"Base B4 {t}",),
        ).fetchone()["id"]

        atividade_id = conn.execute(
            "INSERT INTO atividades (grupo, nome, descricao, limite_horas, tipo_atividade, tem_limitacao)"
            " VALUES ('1 - Grupo B4', ?, 'Teste B4', 40, 'Acadêmica Complementar', 0) RETURNING id",
            (f"Atividade B4 {t}",),
        ).fetchone()["id"]

        versao_id = conn.execute(
            "INSERT INTO atividade_versao"
            " (atividade_base_id, norma_id, codigo_normativo, eixo, grupo, status)"
            " VALUES (?, ?, ?, 'AAC', '1 - Grupo B4', 'ativa') RETURNING id",
            (base_id, norma_id, f"B4NRM{t}"),
        ).fetchone()["id"]

        conn.execute(
            "INSERT INTO atividade_legacy_map (atividade_id_legacy, atividade_base_id, status)"
            " VALUES (?, ?, 'mapeada')",
            (atividade_id, base_id),
        )
        conn.execute(
            "INSERT INTO matrizes_atividades_itens (matriz_id, atividade_id) VALUES (?, ?)",
            (matriz_id, atividade_id),
        )
        conn.execute(
            "INSERT INTO matriz_norma (matriz_id, norma_id) VALUES (?, ?)",
            (matriz_id, norma_id),
        )
        conn.commit()

    return {
        "matriz_id": matriz_id,
        "norma_id": norma_id,
        "base_id": base_id,
        "atividade_id": atividade_id,
        "versao_id": versao_id,
    }


# ---------------------------------------------------------------------------
# 1. GET da página admin de versões da matriz retorna 200
# ---------------------------------------------------------------------------


def test_get_versoes_page_returns_200(versioned_env):
    client = versioned_env["client"]
    _login_admin(client)
    resp = client.get("/admin/matrizes/1/versoes")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 2. UI mostra bases do escopo da matriz
# ---------------------------------------------------------------------------


def test_get_versoes_page_shows_scope_bases(versioned_env):
    client = versioned_env["client"]
    _login_admin(client)
    resp = client.get("/admin/matrizes/1/versoes")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    # seed_reference_versioned_dataset cria "Base conceitual 01", "Base conceitual 02", ...
    assert "Base conceitual 01" in html

    with main.app.app_context():
        conn = main.get_db_connection()
        bases = main.get_bases_escopo_matriz(conn, 1)
    assert len(bases) > 0


# ---------------------------------------------------------------------------
# 3. UI oferece apenas versões ativas
# ---------------------------------------------------------------------------


def test_get_versoes_page_offers_only_ativas(versioned_env):
    with main.app.app_context():
        conn = main.get_db_connection()
        # Matriz 1 usa norma_id=1 (AAC-rev5); base_id=1 tem versão ativa vinculada
        versoes = main.get_versoes_ativas_por_base_na_matriz(conn, 1, 1)
    assert len(versoes) >= 1
    assert all(v["status"] == "ativa" for v in versoes)


# ---------------------------------------------------------------------------
# 4. UI não oferece versões rascunho, inativas, descontinuadas ou substituídas
# ---------------------------------------------------------------------------


def test_get_versoes_page_excludes_non_ativas(versioned_env):
    t = uuid.uuid4().hex[:6]
    with main.app.app_context():
        conn = main.get_db_connection()
        # Nova norma para não colidir com UNIQUE(atividade_base_id, norma_id) existente
        norma_draft_id = conn.execute(
            "INSERT INTO norma_atividade (codigo, eixo, revisao, nome, status)"
            " VALUES (?, 'AAC', 'draftx', 'Norma Draft', 'ativa') RETURNING id",
            (f"AACdraft{t}",),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO atividade_versao"
            " (atividade_base_id, norma_id, codigo_normativo, eixo, grupo, status)"
            " VALUES (1, ?, ?, 'AAC', '1 - Draft', 'rascunho')",
            (norma_draft_id, f"AACdraft{t}"),
        )
        # Vincular norma à matriz 1 para que ela "qualificaria" sem o filtro de status
        conn.execute("INSERT INTO matriz_norma (matriz_id, norma_id) VALUES (1, ?)", (norma_draft_id,))
        conn.commit()

        versoes = main.get_versoes_ativas_por_base_na_matriz(conn, 1, 1)

    status_set = {v["status"] for v in versoes}
    assert "rascunho" not in status_set
    assert "inativa" not in status_set
    assert "descontinuada" not in status_set
    assert "substituida" not in status_set


# ---------------------------------------------------------------------------
# 5. POST definir exige norma vinculada em matriz_norma
# ---------------------------------------------------------------------------


def test_post_definir_rejeita_versao_sem_norma_na_matriz(versioned_env):
    client = versioned_env["client"]
    _login_admin(client)
    seed = _seed_fresh_matrix()
    t = uuid.uuid4().hex[:6]

    with main.app.app_context():
        conn = main.get_db_connection()
        norma_fora_id = conn.execute(
            "INSERT INTO norma_atividade (codigo, eixo, revisao, nome, status)"
            " VALUES (?, 'AAC', 'rev9', 'Norma Fora', 'ativa') RETURNING id",
            (f"NRMfora{t}",),
        ).fetchone()["id"]
        versao_fora_id = conn.execute(
            "INSERT INTO atividade_versao"
            " (atividade_base_id, norma_id, codigo_normativo, eixo, grupo, status)"
            " VALUES (?, ?, ?, 'AAC', '1 - Fora', 'ativa') RETURNING id",
            (seed["base_id"], norma_fora_id, f"NRMfora{t}"),
        ).fetchone()["id"]
        # NÃO inserir norma_fora_id em matriz_norma
        conn.commit()

    resp = client.post(
        f"/admin/matrizes/{seed['matriz_id']}/versoes/definir",
        data={"base_id": str(seed["base_id"]), "versao_id": str(versao_fora_id)},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "norma" in html.lower()

    with main.app.app_context():
        conn = main.get_db_connection()
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM matriz_atividade_versao_item"
            " WHERE matriz_id = ? AND atividade_versao_id = ?",
            (seed["matriz_id"], versao_fora_id),
        ).fetchone()["c"]
    assert count == 0


# ---------------------------------------------------------------------------
# 6. POST define versão ativa válida para matriz+base
# ---------------------------------------------------------------------------


def test_post_definir_define_versao_valida(versioned_env):
    client = versioned_env["client"]
    _login_admin(client)
    seed = _seed_fresh_matrix()

    resp = client.post(
        f"/admin/matrizes/{seed['matriz_id']}/versoes/definir",
        data={"base_id": str(seed["base_id"]), "versao_id": str(seed["versao_id"])},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "sucesso" in html.lower()

    with main.app.app_context():
        conn = main.get_db_connection()
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM matriz_atividade_versao_item"
            " WHERE matriz_id = ? AND atividade_versao_id = ?",
            (seed["matriz_id"], seed["versao_id"]),
        ).fetchone()["c"]
    assert count == 1


# ---------------------------------------------------------------------------
# 7. POST troca versão da mesma base sem criar ambiguidade
# ---------------------------------------------------------------------------


def test_post_definir_troca_versao_anterior_sem_ambiguidade(versioned_env):
    client = versioned_env["client"]
    _login_admin(client)
    seed = _seed_fresh_matrix()
    t = uuid.uuid4().hex[:6]

    with main.app.app_context():
        conn = main.get_db_connection()
        norma2_id = conn.execute(
            "INSERT INTO norma_atividade (codigo, eixo, revisao, nome, status)"
            " VALUES (?, 'AAC', 'rev2', 'Norma B4 v2', 'ativa') RETURNING id",
            (f"B4NRM2{t}",),
        ).fetchone()["id"]
        versao2_id = conn.execute(
            "INSERT INTO atividade_versao"
            " (atividade_base_id, norma_id, codigo_normativo, eixo, grupo, status)"
            " VALUES (?, ?, ?, 'AAC', '1 - Grupo B4 v2', 'ativa') RETURNING id",
            (seed["base_id"], norma2_id, f"B4NRM2{t}"),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO matriz_norma (matriz_id, norma_id) VALUES (?, ?)",
            (seed["matriz_id"], norma2_id),
        )
        conn.commit()

    # Definir versão 1
    client.post(
        f"/admin/matrizes/{seed['matriz_id']}/versoes/definir",
        data={"base_id": str(seed["base_id"]), "versao_id": str(seed["versao_id"])},
        follow_redirects=True,
    )

    # Trocar para versão 2
    client.post(
        f"/admin/matrizes/{seed['matriz_id']}/versoes/definir",
        data={"base_id": str(seed["base_id"]), "versao_id": str(versao2_id)},
        follow_redirects=True,
    )

    with main.app.app_context():
        conn = main.get_db_connection()
        count = conn.execute(
            """
            SELECT COUNT(*) AS c
              FROM matriz_atividade_versao_item mavi
              JOIN atividade_versao av ON av.id = mavi.atividade_versao_id
             WHERE mavi.matriz_id = ? AND av.atividade_base_id = ?
            """,
            (seed["matriz_id"], seed["base_id"]),
        ).fetchone()["c"]
        vinculo = main.get_vinculo_versao_da_matriz(conn, seed["matriz_id"], seed["base_id"])

    assert count == 1, "Deve existir exatamente 1 vínculo por matriz+base após troca"
    assert vinculo is not None
    assert vinculo["atividade_versao_id"] == versao2_id


# ---------------------------------------------------------------------------
# 8. POST remover remove vínculo
# ---------------------------------------------------------------------------


def test_post_remover_remove_vinculo(versioned_env):
    client = versioned_env["client"]
    _login_admin(client)
    seed = _seed_fresh_matrix()

    client.post(
        f"/admin/matrizes/{seed['matriz_id']}/versoes/definir",
        data={"base_id": str(seed["base_id"]), "versao_id": str(seed["versao_id"])},
        follow_redirects=True,
    )

    resp = client.post(
        f"/admin/matrizes/{seed['matriz_id']}/versoes/remover",
        data={"base_id": str(seed["base_id"])},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "removido" in html.lower() or "sucesso" in html.lower()

    with main.app.app_context():
        conn = main.get_db_connection()
        vinculo = main.get_vinculo_versao_da_matriz(conn, seed["matriz_id"], seed["base_id"])
    assert vinculo is None


# ---------------------------------------------------------------------------
# 9. Após definir vínculo, resolver_versao_por_matriz resolve a versão
# ---------------------------------------------------------------------------


def test_resolver_resolve_apos_definir_vinculo(versioned_env):
    client = versioned_env["client"]
    _login_admin(client)
    seed = _seed_fresh_matrix()

    with main.app.app_context():
        conn = main.get_db_connection()
        result_antes = main.resolver_versao_por_matriz(
            conn,
            matriz_id=seed["matriz_id"],
            atividade_id_legacy=seed["atividade_id"],
            strict_legacy_scope=True,
        )
    assert result_antes["status"] == "base_without_version_for_matrix"

    client.post(
        f"/admin/matrizes/{seed['matriz_id']}/versoes/definir",
        data={"base_id": str(seed["base_id"]), "versao_id": str(seed["versao_id"])},
        follow_redirects=True,
    )

    with main.app.app_context():
        conn = main.get_db_connection()
        result_depois = main.resolver_versao_por_matriz(
            conn,
            matriz_id=seed["matriz_id"],
            atividade_id_legacy=seed["atividade_id"],
            strict_legacy_scope=True,
        )
    assert result_depois["status"] == "resolved", (
        f"Esperado resolved, obteve: {result_depois['status']!r}"
    )
    assert result_depois["atividade_versao_id"] == seed["versao_id"]


# ---------------------------------------------------------------------------
# 10. Após remover vínculo, resolver retorna ausência de versão
# ---------------------------------------------------------------------------


def test_resolver_retorna_ausencia_apos_remover_vinculo(versioned_env):
    client = versioned_env["client"]
    _login_admin(client)
    seed = _seed_fresh_matrix()

    client.post(
        f"/admin/matrizes/{seed['matriz_id']}/versoes/definir",
        data={"base_id": str(seed["base_id"]), "versao_id": str(seed["versao_id"])},
        follow_redirects=True,
    )
    client.post(
        f"/admin/matrizes/{seed['matriz_id']}/versoes/remover",
        data={"base_id": str(seed["base_id"])},
        follow_redirects=True,
    )

    with main.app.app_context():
        conn = main.get_db_connection()
        result = main.resolver_versao_por_matriz(
            conn,
            matriz_id=seed["matriz_id"],
            atividade_id_legacy=seed["atividade_id"],
            strict_legacy_scope=True,
        )
    assert result["status"] == "base_without_version_for_matrix", (
        f"Após remover vínculo o resolvedor deve retornar base_without_version_for_matrix,"
        f" obteve: {result['status']!r}"
    )
    assert result.get("atividade_versao_id") is None


# ---------------------------------------------------------------------------
# 11. POST rejeita versão de base fora do escopo da matriz
# ---------------------------------------------------------------------------


def test_post_definir_rejeita_base_fora_do_escopo(versioned_env):
    client = versioned_env["client"]
    _login_admin(client)
    seed = _seed_fresh_matrix()
    t = uuid.uuid4().hex[:6]

    with main.app.app_context():
        conn = main.get_db_connection()
        base_fora_id = conn.execute(
            "INSERT INTO atividade_base (nome_conceito, descricao, status)"
            " VALUES (?, 'Fora escopo', 'ativo') RETURNING id",
            (f"Base Fora {t}",),
        ).fetchone()["id"]
        versao_fora_id = conn.execute(
            "INSERT INTO atividade_versao"
            " (atividade_base_id, norma_id, codigo_normativo, eixo, grupo, status)"
            " VALUES (?, ?, ?, 'AAC', '1 - Fora', 'ativa') RETURNING id",
            (base_fora_id, seed["norma_id"], f"B4FORA{t}"),
        ).fetchone()["id"]
        # NÃO inserir em matrizes_atividades_itens (fora do escopo)
        conn.commit()

    resp = client.post(
        f"/admin/matrizes/{seed['matriz_id']}/versoes/definir",
        data={"base_id": str(base_fora_id), "versao_id": str(versao_fora_id)},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "escopo" in html.lower() or "não está" in html.lower()

    with main.app.app_context():
        conn = main.get_db_connection()
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM matriz_atividade_versao_item"
            " WHERE matriz_id = ? AND atividade_versao_id = ?",
            (seed["matriz_id"], versao_fora_id),
        ).fetchone()["c"]
    assert count == 0


# ---------------------------------------------------------------------------
# 12. POST rejeita versão cuja norma não está em matriz_norma
# ---------------------------------------------------------------------------


def test_post_definir_rejeita_versao_com_norma_nao_na_matriz(versioned_env):
    client = versioned_env["client"]
    _login_admin(client)
    seed = _seed_fresh_matrix()
    t = uuid.uuid4().hex[:6]

    with main.app.app_context():
        conn = main.get_db_connection()
        norma_extra_id = conn.execute(
            "INSERT INTO norma_atividade (codigo, eixo, revisao, nome, status)"
            " VALUES (?, 'AAC', 'revX', 'Norma Extra', 'ativa') RETURNING id",
            (f"B4EXT{t}",),
        ).fetchone()["id"]
        versao_extra_id = conn.execute(
            "INSERT INTO atividade_versao"
            " (atividade_base_id, norma_id, codigo_normativo, eixo, grupo, status)"
            " VALUES (?, ?, ?, 'AAC', '1 - Extra', 'ativa') RETURNING id",
            (seed["base_id"], norma_extra_id, f"B4EXT{t}"),
        ).fetchone()["id"]
        # NÃO inserir norma_extra_id em matriz_norma
        conn.commit()

    resp = client.post(
        f"/admin/matrizes/{seed['matriz_id']}/versoes/definir",
        data={"base_id": str(seed["base_id"]), "versao_id": str(versao_extra_id)},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "norma" in html.lower()

    with main.app.app_context():
        conn = main.get_db_connection()
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM matriz_atividade_versao_item"
            " WHERE matriz_id = ? AND atividade_versao_id = ?",
            (seed["matriz_id"], versao_extra_id),
        ).fetchone()["c"]
    assert count == 0


# ---------------------------------------------------------------------------
# 13. Não há fallback para primeira ativa sem vínculo explícito
# ---------------------------------------------------------------------------


def test_sem_vinculo_resolvedor_nao_usa_primeira_ativa(versioned_env):
    """
    Mesmo com versões ativas disponíveis via norma da matriz, o resolvedor
    NÃO retorna resolved sem um vínculo explícito em matriz_atividade_versao_item.
    """
    seed = _seed_fresh_matrix()

    with main.app.app_context():
        conn = main.get_db_connection()
        versoes_disponiveis = main.get_versoes_ativas_por_base_na_matriz(
            conn, seed["matriz_id"], seed["base_id"]
        )
    assert len(versoes_disponiveis) >= 1, "Pré-condição: deve haver versão ativa disponível"

    with main.app.app_context():
        conn = main.get_db_connection()
        result = main.resolver_versao_por_matriz(
            conn,
            matriz_id=seed["matriz_id"],
            atividade_id_legacy=seed["atividade_id"],
            strict_legacy_scope=True,
        )
    assert result["status"] != "resolved", (
        "Resolvedor não deve usar fallback para primeira ativa sem vínculo explícito."
        f" Obteve status={result['status']!r} mesmo sem entrada em matriz_atividade_versao_item."
    )
    assert result["status"] == "base_without_version_for_matrix"


# ---------------------------------------------------------------------------
# 14. CSRF real presente nos formulários POST
# ---------------------------------------------------------------------------


def test_csrf_token_presente_nos_forms_post(versioned_env):
    """
    A página GET deve renderizar formulários com campo csrf_token nos actions
    de definir e remover. Usa a matriz 1 do dataset de referência, que já tem
    bases no escopo e versões ativas disponíveis.
    """
    client = versioned_env["client"]
    _login_admin(client)
    resp = client.get("/admin/matrizes/1/versoes")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'name="csrf_token"' in html or "name='csrf_token'" in html
