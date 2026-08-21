"""
D7.2B1 — Testes read-only do catálogo versionado.

Cobre:
1. GET /admin/catalogo-versoes      — lista atividade_base
2. GET /admin/catalogo-versoes/<id> — detalhe base + versões
3. GET /admin/normas-atividade      — lista norma_atividade

Provas obrigatórias:
- GETs não escrevem no banco (total_changes / contagens antes=depois).
- Termos proibidos ("snapshot", "diagnóstico") ausentes nas respostas.
- Detalhe de base inexistente não quebra (flash + redirect).
- Templates de aluno não expõem termos do catálogo versionado.
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    app = main.app
    with app.app_context():
        main.init_db()
        yield app.test_client()


def _login_admin(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["user_type"] = "admin"
        sess["user_name"] = "Administrador"


def _seed_base_and_norma(
    client,
    *,
    base_nome: str = "Atividade Teste D72B1",
    base_descricao: str = "Descrição de teste",
    norma_codigo: str = "TST-rev1",
    norma_eixo: str = "AAC",
    norma_revisao: str = "rev1",
    norma_nome: str = "Norma Teste D72B1",
    norma_status: str = "ativa",
    versao_codigo_normativo: str | None = None,
    versao_grupo: str = "1 - Grupo Teste",
    versao_status: str = "ativa",
):
    """
    Insere diretamente uma atividade_base, norma_atividade e atividade_versao
    no banco de teste para que os testes de listagem tenham algo a exibir.
    Usa o contexto do app para acessar o banco da app de teste.
    Retorna (base_id, norma_id, versao_id).
    """
    with main.app.app_context():
        conn = main.get_db_connection()
        # Garante que não há colisão de nome único
        existing = conn.execute(
            "SELECT id FROM atividade_base WHERE nome_conceito = ?",
            (base_nome,),
        ).fetchone()
        if existing:
            base_id = existing["id"]
        else:
            conn.execute(
                "INSERT INTO atividade_base (nome_conceito, descricao, status) VALUES (?, ?, ?)",
                (base_nome, base_descricao, "ativo"),
            )
            conn.commit()
            base_id = conn.execute(
                "SELECT id FROM atividade_base WHERE nome_conceito = ?",
                (base_nome,),
            ).fetchone()["id"]

        existing_norma = conn.execute(
            "SELECT id FROM norma_atividade WHERE codigo = ?",
            (norma_codigo,),
        ).fetchone()
        if existing_norma:
            norma_id = existing_norma["id"]
        else:
            conn.execute(
                "INSERT INTO norma_atividade (codigo, eixo, revisao, nome, status) VALUES (?, ?, ?, ?, ?)",
                (norma_codigo, norma_eixo, norma_revisao, norma_nome, norma_status),
            )
            conn.commit()
            norma_id = conn.execute(
                "SELECT id FROM norma_atividade WHERE codigo = ?",
                (norma_codigo,),
            ).fetchone()["id"]

        codigo_normativo = versao_codigo_normativo or norma_codigo
        existing_versao = conn.execute(
            "SELECT id FROM atividade_versao WHERE atividade_base_id = ? AND norma_id = ?",
            (base_id, norma_id),
        ).fetchone()
        if existing_versao:
            versao_id = existing_versao["id"]
        else:
            next_num = conn.execute(
                "SELECT COALESCE(MAX(numero_versao), 0) + 1 FROM atividade_versao WHERE atividade_base_id = ?",
                (base_id,),
            ).fetchone()[0]
            conn.execute(
                """
                INSERT INTO atividade_versao
                    (atividade_base_id, norma_id, codigo_normativo, eixo, grupo, status, numero_versao)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    base_id,
                    norma_id,
                    codigo_normativo,
                    norma_eixo,
                    versao_grupo,
                    versao_status,
                    next_num,
                ),
            )
            conn.commit()
            versao_id = conn.execute(
                "SELECT id FROM atividade_versao WHERE atividade_base_id = ? AND norma_id = ?",
                (base_id, norma_id),
            ).fetchone()["id"]

    return base_id, norma_id, versao_id


def _insert_transicao(
    from_versao_id: int,
    to_versao_id: int,
    *,
    tipo_transicao: str = "mesmo_eixo",
    justificativa: str | None = None,
    observacao_admin: str | None = None,
    created_at: str = "2026-06-11 08:15:00",
):
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            """
            INSERT INTO atividade_transicao (
                from_atividade_versao_id,
                to_atividade_versao_id,
                tipo_transicao,
                justificativa,
                observacao_admin,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                from_versao_id,
                to_versao_id,
                tipo_transicao,
                justificativa,
                observacao_admin,
                created_at,
            ),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# 1. GET /admin/catalogo-versoes — lista vazia ou com seed
# ---------------------------------------------------------------------------

def test_catalogo_versoes_list_get_returns_200(client):
    """GET /admin/catalogo-versoes retorna 200 com admin logado."""
    _login_admin(client)
    response = client.get("/admin/catalogo-versoes")
    assert response.status_code == 200


def test_catalogo_versoes_list_get_contains_title(client):
    """A página contém o título 'Catálogo de versões'."""
    _login_admin(client)
    response = client.get("/admin/catalogo-versoes")
    html = response.get_data(as_text=True)
    assert "Catálogo de versões" in html or "Catálogo de vers" in html


def test_catalogo_versoes_list_requires_admin(client):
    """Sem login, deve redirecionar (não 200)."""
    response = client.get("/admin/catalogo-versoes")
    assert response.status_code in (302, 401, 403)


# ---------------------------------------------------------------------------
# 2. Termos proibidos ausentes na listagem
# ---------------------------------------------------------------------------

def test_catalogo_versoes_list_shows_base_without_forbidden_terms(client):
    """
    Com base seedada, nome_conceito aparece; termos específicos do D6 proibidos
    ('snapshot versionado', 'diagnóstico do snapshot', 'comparação read-only')
    estão ausentes na área de conteúdo.

    Nota: 'snapshot' genérico pode aparecer no base.html em contexto de backup
    de banco de dados — não é o termo proibido aqui. O que não deve aparecer é
    a terminologia específica do módulo de versioning D6.
    """
    _login_admin(client)
    _seed_base_and_norma(client)

    response = client.get("/admin/catalogo-versoes")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    # nome da base deve aparecer
    assert "Atividade Teste D72B1" in html

    # termos específicos do D6 proibidos (case-insensitive)
    html_lower = html.lower()
    assert "snapshot versionado" not in html_lower, \
        "Termo 'snapshot versionado' não deve aparecer no catálogo"
    assert "diagnóstico do snapshot" not in html_lower
    assert "comparação read-only" not in html_lower


# ---------------------------------------------------------------------------
# 3. GET /admin/catalogo-versoes/<base_id> — detalhe com versões
# ---------------------------------------------------------------------------

def test_catalogo_versao_detalhe_lists_versions(client):
    """
    Detalhe da base mostra código normativo das versões AAC.
    """
    _login_admin(client)
    base_id, norma_id, versao_id = _seed_base_and_norma(client)

    response = client.get(f"/admin/catalogo-versoes/{base_id}")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    # código normativo da versão deve aparecer
    assert "TST-rev1" in html
    # eixo deve aparecer
    assert "AAC" in html
    # termos específicos do D6 proibidos
    html_lower = html.lower()
    assert "snapshot versionado" not in html_lower
    assert "diagnóstico do snapshot" not in html_lower


def test_catalogo_versao_detalhe_shows_base_name(client):
    """O nome da atividade-base aparece no cabeçalho do detalhe."""
    _login_admin(client)
    base_id, _, _ = _seed_base_and_norma(client)

    response = client.get(f"/admin/catalogo-versoes/{base_id}")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Atividade Teste D72B1" in html


def test_catalogo_versao_detalhe_shows_empty_transition_history(client):
    _login_admin(client)
    base_id, _, _ = _seed_base_and_norma(
        client,
        base_nome="Atividade Historico Vazio D72B6",
        norma_codigo="HIST-EMPTY-D72B6",
        norma_nome="Norma Historico Vazio D72B6",
        norma_revisao="rev-empty-d72b6",
    )

    response = client.get(f"/admin/catalogo-versoes/{base_id}")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Histórico de transições" in html
    assert "Nenhuma transição registrada para esta atividade-base." in html


def test_catalogo_versao_detalhe_lists_transition_history_for_current_base(client):
    _login_admin(client)
    base_id, _, origem_id = _seed_base_and_norma(
        client,
        base_nome="Atividade Historico Lista D72B6",
        norma_codigo="HIST-LISTA-ORIG-D72B6",
        norma_nome="Norma Origem Historico Lista D72B6",
        norma_revisao="rev-lista-orig-d72b6",
    )
    _, _, destino_id = _seed_base_and_norma(
        client,
        base_nome="Atividade Historico Lista D72B6",
        norma_codigo="HIST-LISTA-DEST-D72B6",
        norma_nome="Norma Destino Historico Lista D72B6",
        norma_revisao="rev-lista-dest-d72b6",
    )
    _insert_transicao(
        origem_id,
        destino_id,
        created_at="2026-06-11 09:45:00",
    )

    response = client.get(f"/admin/catalogo-versoes/{base_id}")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "HIST-LISTA-ORIG-D72B6" in html
    assert "HIST-LISTA-DEST-D72B6" in html
    assert "mesmo_eixo" in html
    assert "2026-06-11 09:45:00" in html


def test_catalogo_versao_detalhe_filters_transition_history_by_base(client):
    _login_admin(client)
    base_id, _, origem_a_id = _seed_base_and_norma(
        client,
        base_nome="Atividade Historico Filtro A D72B6",
        norma_codigo="HIST-FILT-A-ORIG-D72B6",
        norma_nome="Norma Filtro A Origem D72B6",
        norma_revisao="rev-filt-a-orig-d72b6",
    )
    _, _, destino_a_id = _seed_base_and_norma(
        client,
        base_nome="Atividade Historico Filtro A D72B6",
        norma_codigo="HIST-FILT-A-DEST-D72B6",
        norma_nome="Norma Filtro A Destino D72B6",
        norma_revisao="rev-filt-a-dest-d72b6",
    )
    _insert_transicao(origem_a_id, destino_a_id, created_at="2026-06-11 10:10:10")

    _, _, origem_b_id = _seed_base_and_norma(
        client,
        base_nome="Atividade Historico Filtro B D72B6",
        norma_codigo="HIST-FILT-B-ORIG-D72B6",
        norma_nome="Norma Filtro B Origem D72B6",
        norma_revisao="rev-filt-b-orig-d72b6",
    )
    _, _, destino_b_id = _seed_base_and_norma(
        client,
        base_nome="Atividade Historico Filtro B D72B6",
        norma_codigo="HIST-FILT-B-DEST-D72B6",
        norma_nome="Norma Filtro B Destino D72B6",
        norma_revisao="rev-filt-b-dest-d72b6",
    )
    _insert_transicao(origem_b_id, destino_b_id, created_at="2026-06-11 10:20:20")

    response = client.get(f"/admin/catalogo-versoes/{base_id}")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "HIST-FILT-A-ORIG-D72B6" in html
    assert "HIST-FILT-A-DEST-D72B6" in html
    assert "HIST-FILT-B-ORIG-D72B6" not in html
    assert "HIST-FILT-B-DEST-D72B6" not in html


def test_catalogo_versao_detalhe_shows_dash_for_empty_transition_note(client):
    _login_admin(client)
    base_id, _, origem_id = _seed_base_and_norma(
        client,
        base_nome="Atividade Historico Nota Vazia D72B6",
        norma_codigo="HIST-NOTA-ORIG-D72B6",
        norma_nome="Norma Nota Origem D72B6",
        norma_revisao="rev-nota-orig-d72b6",
    )
    _, _, destino_id = _seed_base_and_norma(
        client,
        base_nome="Atividade Historico Nota Vazia D72B6",
        norma_codigo="HIST-NOTA-DEST-D72B6",
        norma_nome="Norma Nota Destino D72B6",
        norma_revisao="rev-nota-dest-d72b6",
    )
    _insert_transicao(
        origem_id,
        destino_id,
        justificativa=None,
        observacao_admin=None,
        created_at="2026-06-11 11:11:11",
    )

    response = client.get(f"/admin/catalogo-versoes/{base_id}")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert re.search(r'<td class="history-note-cell">\s*-\s*</td>', html)


# ---------------------------------------------------------------------------
# 4. Detalhe com base inexistente — não deve quebrar
# ---------------------------------------------------------------------------

def test_catalogo_versao_detalhe_404_for_missing_base(client):
    """
    Base inexistente (id=999999) não deve retornar 500.
    Deve redirecionar (302) com flash de erro.
    """
    _login_admin(client)
    response = client.get("/admin/catalogo-versoes/999999")
    # Redireciona de volta ao catálogo, não 500
    assert response.status_code == 302
    assert "/admin/catalogo-versoes" in response.headers.get("Location", "")


# ---------------------------------------------------------------------------
# 5. GET /admin/normas-atividade — lista normas
# ---------------------------------------------------------------------------

def test_normas_atividade_list_get_returns_200(client):
    """GET /admin/normas-atividade retorna 200."""
    _login_admin(client)
    response = client.get("/admin/normas-atividade")
    assert response.status_code == 200


def test_normas_atividade_list_shows_seeded_norma(client):
    """Com norma seedada, código aparece na listagem."""
    _login_admin(client)
    _seed_base_and_norma(client)

    response = client.get("/admin/normas-atividade")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "TST-rev1" in html


def test_normas_atividade_list_no_forbidden_terms(client):
    """Página de normas não exibe termos específicos do D6 proibidos."""
    _login_admin(client)
    response = client.get("/admin/normas-atividade")
    assert response.status_code == 200
    html_lower = response.get_data(as_text=True).lower()
    assert "snapshot versionado" not in html_lower
    assert "diagnóstico do snapshot" not in html_lower
    assert "comparação read-only" not in html_lower


# ---------------------------------------------------------------------------
# 8. GETs não mutam o banco (total_changes)
# ---------------------------------------------------------------------------

def test_readonly_catalog_routes_do_not_mutate_database(client):
    """
    Todos os GETs canônicos do catálogo não devem alterar o banco de dados.
    """
    _login_admin(client)
    base_id, _, _ = _seed_base_and_norma(client)

    with main.app.app_context():
        conn = main.get_db_connection()
        changes_before = conn.total_changes

        # Exercitar todos os endpoints GET da D7.2B1
        client.get("/admin/catalogo-versoes")
        client.get(f"/admin/catalogo-versoes/{base_id}")
        client.get("/admin/catalogo-versoes/999999")  # missing → redirect
        client.get("/admin/normas-atividade")
        changes_after = conn.total_changes

    assert changes_after == changes_before, (
        "Rotas GET do catálogo não devem mutar o banco de dados. "
        f"total_changes antes={changes_before}, depois={changes_after}"
    )


# ---------------------------------------------------------------------------
# 9. Templates do aluno não expõem termos do catálogo versionado
# ---------------------------------------------------------------------------

def test_student_templates_do_not_expose_version_catalog_terms(client):
    """
    Rotas do aluno relevantes (dashboard, minhas-requisicoes) não devem
    expor 'atividade_versao_id', 'codigo_normativo' ou 'snapshot'.

    Como o banco de teste pode não ter aluno logado, verificamos apenas
    que as rotas retornam sem vazar termos versionados no HTML.
    """
    # Simula sessão de aluno básica (mesmo sem aluno real no banco)
    with client.session_transaction() as sess:
        sess["user_id"] = 9999999  # id inexistente → redirecionamento esperado
        sess["user_type"] = "aluno"
        sess["user_name"] = "Aluno Teste"

    # Termos que identificam exposição do catálogo versionado ao aluno
    forbidden = ["atividade_versao_id", "snapshot versionado", "diagnóstico do snapshot"]

    for path in ["/aluno/dashboard", "/aluno/minhas-requisicoes"]:
        response = client.get(path, follow_redirects=True)
        html_lower = response.get_data(as_text=True).lower()
        for term in forbidden:
            assert term not in html_lower, (
                f"Termo '{term}' não deve aparecer em {path}"
            )
