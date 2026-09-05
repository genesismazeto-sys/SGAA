"""
COV-1 restoration — Read-only versioned catalog routes.

Adapted from the pre-Norma suite (test_admin_activity_version_catalog_readonly.py)
with all Norma-domain routes removed (normas-atividade).

Covers:
 1. GET /admin/catalogo-versoes      — lista atividade_base.
 2. GET /admin/catalogo-versoes/<id> — detalhe base + versões + histórico.
 3. Provas obrigatórias:
    - GETs não escrevem no banco (total_changes antes=depois).
    - Termos proibidos ("snapshot versionado", "diagnóstico do snapshot")
      ausentes nas respostas.
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


def _seed_base_e_versao(
    client,
    *,
    base_nome: str = "Atividade Teste",
    base_descricao: str = "Descrição de teste",
    versao_grupo: str = "1 - Grupo Teste",
    versao_status: str = "ativa",
) -> tuple[int, int]:
    """
    Insere diretamente uma atividade_base e uma atividade_versao
    no banco de teste para que os testes de listagem tenham algo a exibir.
    Retorna (base_id, versao_id).
    """
    with main.app.app_context():
        conn = main.get_db_connection()
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

        versao = conn.execute(
            "SELECT id FROM atividade_versao WHERE atividade_base_id = ? AND grupo = ?",
            (base_id, versao_grupo),
        ).fetchone()
        if versao:
            versao_id = versao["id"]
        else:
            next_num = conn.execute(
                "SELECT COALESCE(MAX(numero_versao), 0) + 1 FROM atividade_versao WHERE atividade_base_id = ?",
                (base_id,),
            ).fetchone()[0]
            conn.execute(
                """
                INSERT INTO atividade_versao
                    (atividade_base_id, eixo, grupo, status, numero_versao)
                VALUES (?, 'AAC', ?, ?, ?)
                """,
                (base_id, versao_grupo, versao_status, next_num),
            )
            conn.commit()
            versao_id = conn.execute(
                "SELECT id FROM atividade_versao WHERE atividade_base_id = ? AND grupo = ?",
                (base_id, versao_grupo),
            ).fetchone()["id"]

    return base_id, versao_id


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
    """
    _login_admin(client)
    _seed_base_e_versao(client)

    response = client.get("/admin/catalogo-versoes")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "Atividade Teste" in html

    html_lower = html.lower()
    assert "snapshot versionado" not in html_lower, \
        "Termo 'snapshot versionado' não deve aparecer no catálogo"
    assert "diagnóstico do snapshot" not in html_lower
    assert "comparação read-only" not in html_lower


def test_catalogo_versoes_omits_base_status_and_preserves_version_counts(client):
    _login_admin(client)
    base_nome = "Atividade Base Status Oculto"
    base_id, _ = _seed_base_e_versao(client, base_nome=base_nome)

    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "UPDATE atividade_base SET status = 'inativo' WHERE id = ?",
            (base_id,),
        )
        conn.execute(
            """
            INSERT INTO atividade_versao
                (atividade_base_id, eixo, grupo, status, numero_versao)
            VALUES (?, 'AAC', '2 - Grupo Rascunho', 'rascunho', 2)
            """,
            (base_id,),
        )
        conn.commit()

    response = client.get("/admin/catalogo-versoes")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert ">Status<" not in html
    assert ">inativo<" not in html
    assert re.search(
        rf'data-base-id="{base_id}"[^>]*>.*?'
        rf'{re.escape(base_nome)}.*?'
        r'class="cell center">\s*2\s*</div>.*?'
        r'class="cell center">\s*1\s*</div>.*?'
        rf'href="/admin/catalogo-versoes/{base_id}"[^>]*>Ver</a>',
        html,
        re.DOTALL,
    )


# ---------------------------------------------------------------------------
# 3. GET /admin/catalogo-versoes/<base_id> — detalhe com versões
# ---------------------------------------------------------------------------

def test_catalogo_versao_detalhe_lists_versions(client):
    """Detalhe da base mostra o badge de número das versões."""
    _login_admin(client)
    base_id, versao_id = _seed_base_e_versao(client)

    response = client.get(f"/admin/catalogo-versoes/{base_id}")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "v1" in html
    assert "Acadêmica Complementar" in html
    assert ">Eixo<" not in html
    html_lower = html.lower()
    assert "snapshot versionado" not in html_lower
    assert "diagnóstico do snapshot" not in html_lower


def test_catalogo_versao_detalhe_shows_base_name(client):
    """O nome da atividade-base aparece no cabeçalho do detalhe."""
    _login_admin(client)
    base_id, _ = _seed_base_e_versao(client)

    response = client.get(f"/admin/catalogo-versoes/{base_id}")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Atividade Teste" in html


def test_catalogo_versao_detalhe_shows_empty_transition_history(client):
    _login_admin(client)
    base_id, _ = _seed_base_e_versao(
        client,
        base_nome="Atividade Historico Vazio",
        versao_grupo="1 - Grupo Historico Vazio",
    )

    response = client.get(f"/admin/catalogo-versoes/{base_id}")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Histórico de transições" in html
    assert "Nenhuma transição registrada" in html


def test_catalogo_versao_detalhe_lists_transition_history_for_current_base(client):
    _login_admin(client)
    base_id, origem_id = _seed_base_e_versao(
        client,
        base_nome="Atividade Historico Lista",
        versao_grupo="1 - Grupo Historico Origem",
    )
    _, destino_id = _seed_base_e_versao(
        client,
        base_nome="Atividade Historico Lista",
        versao_grupo="1 - Grupo Historico Destino",
    )
    _insert_transicao(
        origem_id,
        destino_id,
        created_at="2026-06-11 09:45:00",
    )

    response = client.get(f"/admin/catalogo-versoes/{base_id}")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "v1" in html
    assert "v2" in html
    assert "Mesmo Tipo" in html
    assert "11/06/2026" in html
    assert "2026-06-11 09:45:00" not in html


@pytest.mark.parametrize(
    ("tipo_transicao", "expected_label"),
    [
        ("mesmo_eixo", "Mesmo Tipo"),
        ("aac_para_aeu", "Mudança de Tipo"),
        ("nova_aeu", "Nova versão de Extensão"),
        ("descontinuada", "Descontinuação"),
        ("sem_transicao", "Sem transição"),
    ],
)
def test_catalogo_versao_detalhe_humanizes_known_transition_types(
    client, tipo_transicao, expected_label
):
    _login_admin(client)
    base_id, origem_id = _seed_base_e_versao(
        client,
        base_nome=f"Atividade Transição {tipo_transicao}",
        versao_grupo="1 - Origem",
    )
    _, destino_id = _seed_base_e_versao(
        client,
        base_nome=f"Atividade Transição {tipo_transicao}",
        versao_grupo="1 - Destino",
    )
    if tipo_transicao == "aac_para_aeu":
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute(
                "UPDATE atividade_versao SET eixo = 'AEU' WHERE id = ?",
                (destino_id,),
            )
            conn.commit()
    _insert_transicao(
        origem_id,
        destino_id,
        tipo_transicao=tipo_transicao,
        justificativa=(
            "Mudança normativa documentada"
            if tipo_transicao == "aac_para_aeu"
            else None
        ),
    )

    response = client.get(f"/admin/catalogo-versoes/{base_id}")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert expected_label in html
    assert f">{tipo_transicao}<" not in html


def test_catalogo_versao_detalhe_filters_transition_history_by_base(client):
    _login_admin(client)
    base_a_id, origem_a_id = _seed_base_e_versao(
        client,
        base_nome="Atividade Historico Filtro A",
        versao_grupo="1 - Grupo Filtro A Origem",
    )
    _, destino_a_id = _seed_base_e_versao(
        client,
        base_nome="Atividade Historico Filtro A",
        versao_grupo="1 - Grupo Filtro A Destino",
    )
    _insert_transicao(origem_a_id, destino_a_id, created_at="2026-06-11 10:10:10")

    _, origem_b_id = _seed_base_e_versao(
        client,
        base_nome="Atividade Historico Filtro B",
        versao_grupo="1 - Grupo Filtro B Origem",
    )
    _, destino_b_id = _seed_base_e_versao(
        client,
        base_nome="Atividade Historico Filtro B",
        versao_grupo="1 - Grupo Filtro B Destino",
    )
    _insert_transicao(origem_b_id, destino_b_id, created_at="2026-06-12 10:20:20")

    response = client.get(f"/admin/catalogo-versoes/{base_a_id}")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "11/06/2026" in html
    assert "12/06/2026" not in html


def test_catalogo_versao_detalhe_shows_dash_for_empty_transition_note(client):
    _login_admin(client)
    base_id, origem_id = _seed_base_e_versao(
        client,
        base_nome="Atividade Historico Nota Vazia",
        versao_grupo="1 - Grupo Nota Origem",
    )
    _, destino_id = _seed_base_e_versao(
        client,
        base_nome="Atividade Historico Nota Vazia",
        versao_grupo="1 - Grupo Nota Destino",
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
    assert re.search(r'<td class="transition-note">\s*-\s*</td>', html)


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
    assert response.status_code == 302
    assert "/admin/catalogo-versoes" in response.headers.get("Location", "")


# ---------------------------------------------------------------------------
# 5. GETs não mutam o banco (total_changes)
# ---------------------------------------------------------------------------

def test_readonly_catalog_routes_do_not_mutate_database(client):
    """
    Todos os GETs canônicos do catálogo não devem alterar o banco de dados.
    """
    _login_admin(client)
    base_id, _ = _seed_base_e_versao(client)

    with main.app.app_context():
        conn = main.get_db_connection()
        changes_before = conn.total_changes

        client.get("/admin/catalogo-versoes")
        client.get(f"/admin/catalogo-versoes/{base_id}")
        client.get("/admin/catalogo-versoes/999999")  # missing → redirect
        changes_after = conn.total_changes

    assert changes_after == changes_before, (
        "Rotas GET do catálogo não devem mutar o banco de dados. "
        f"total_changes antes={changes_before}, depois={changes_after}"
    )


# ---------------------------------------------------------------------------
# 6. Templates do aluno não expõem termos do catálogo versionado
# ---------------------------------------------------------------------------

def test_student_templates_do_not_expose_version_catalog_terms(client):
    """
    Rotas do aluno relevantes (dashboard, minhas-requisicoes) não devem
    expor 'atividade_versao_id' ou termos do snapshot versionado.
    """
    with client.session_transaction() as sess:
        sess["user_id"] = 9999999  # id inexistente → redirecionamento esperado
        sess["user_type"] = "aluno"
        sess["user_name"] = "Aluno Teste"

    forbidden = ["atividade_versao_id", "snapshot versionado", "diagnóstico do snapshot"]

    for path in ["/aluno/dashboard", "/aluno/minhas-requisicoes"]:
        response = client.get(path, follow_redirects=True)
        html_lower = response.get_data(as_text=True).lower()
        for term in forbidden:
            assert term not in html_lower, (
                f"Termo '{term}' não deve aparecer em {path}"
            )
