"""
D7.7C1 — Version number visibility in admin UI.

Proves:
1. Catálogo detalhe renders vN badge for each version row.
2. Edit form title shows "Editar versão vN".
3. Nova versão form title shows expected next version number.
4. Matriz versoes page shows vN in current-link chip.
5. Matriz versoes select options include vN.
6. codigo_normativo still visible as metadata in detalhe and matriz versoes.
7. get_versoes_ativas_por_base_na_matriz now includes numero_versao field.
8. D7.7B resolver/validity logic unchanged (no regression).
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
def client():
    app = main.app
    with app.app_context():
        main.init_db()
        yield app.test_client()


@pytest.fixture()
def versioned_env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "d77c1_visibility.db") as env:
        yield env


def _login_admin(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["user_type"] = "admin"
        sess["user_name"] = "Administrador"


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def _seed_base_with_rascunho(tag: str) -> dict:
    """Creates base + norma + rascunho versao with numero_versao=1."""
    with main.app.app_context():
        conn = main.get_db_connection()
        base_id = conn.execute(
            "INSERT INTO atividade_base (nome_conceito, descricao, status)"
            " VALUES (?, 'Desc', 'ativo') RETURNING id",
            (f"Base C1 {tag}",),
        ).fetchone()["id"]
        norma_id = conn.execute(
            "INSERT INTO norma_atividade (codigo, eixo, revisao, nome, status)"
            " VALUES (?, 'AAC', 'rev1', ?, 'ativa') RETURNING id",
            (f"C1NRM{tag}", f"Norma C1 {tag}"),
        ).fetchone()["id"]
        versao_id = conn.execute(
            "INSERT INTO atividade_versao"
            " (atividade_base_id, norma_id, codigo_normativo, eixo, grupo, numero_versao, status)"
            " VALUES (?, ?, ?, 'AAC', '1 - Grupo', 1, 'rascunho') RETURNING id",
            (base_id, norma_id, f"C1NRM{tag}"),
        ).fetchone()["id"]
        conn.commit()
    return {"base_id": base_id, "norma_id": norma_id, "versao_id": versao_id, "tag": tag}


def _seed_fresh_matrix_with_link() -> dict:
    """Creates matriz + norma + base + versao ativa + link in matriz_atividade_versao_item."""
    t = uuid.uuid4().hex[:8]
    with main.app.app_context():
        conn = main.get_db_connection()

        curso_id = conn.execute(
            "INSERT INTO cursos (nome, codigo, duracao_periodos, status)"
            " VALUES (?, ?, 8, 'ativo') RETURNING id",
            (f"Curso C1 {t}", f"C1-{t}"),
        ).fetchone()["id"]

        matriz_id = conn.execute(
            "INSERT INTO matrizes_atividades (curso_id, nome, versao, status)"
            " VALUES (?, ?, '2026.1', 'ativa') RETURNING id",
            (curso_id, f"Matriz C1 {t}"),
        ).fetchone()["id"]

        norma_id = conn.execute(
            "INSERT INTO norma_atividade (codigo, eixo, revisao, nome, status)"
            " VALUES (?, 'AAC', 'rev1', ?, 'ativa') RETURNING id",
            (f"C1MNM{t}", f"Norma Matriz C1 {t}"),
        ).fetchone()["id"]

        base_id = conn.execute(
            "INSERT INTO atividade_base (nome_conceito, descricao, status)"
            " VALUES (?, 'Base C1', 'ativo') RETURNING id",
            (f"Base Matriz C1 {t}",),
        ).fetchone()["id"]

        atividade_id = conn.execute(
            "INSERT INTO atividades (grupo, nome, descricao, limite_horas, tipo_atividade, tem_limitacao)"
            " VALUES ('1 - Grupo', ?, 'Teste C1', 40, 'Acadêmica Complementar', 0) RETURNING id",
            (f"Atividade C1 {t}",),
        ).fetchone()["id"]

        versao_id = conn.execute(
            "INSERT INTO atividade_versao"
            " (atividade_base_id, norma_id, codigo_normativo, eixo, grupo, numero_versao, status)"
            " VALUES (?, ?, ?, 'AAC', '1 - Grupo', 1, 'ativa') RETURNING id",
            (base_id, norma_id, f"C1MNM{t}"),
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
        conn.execute(
            "INSERT INTO matriz_atividade_versao_item (matriz_id, atividade_versao_id)"
            " VALUES (?, ?)",
            (matriz_id, versao_id),
        )
        conn.commit()

    return {
        "matriz_id": matriz_id,
        "base_id": base_id,
        "versao_id": versao_id,
        "norma_codigo": f"C1MNM{t}",
    }


# ---------------------------------------------------------------------------
# 1. Catálogo detalhe renders vN badge
# ---------------------------------------------------------------------------

def test_catalogo_detalhe_renders_vn_badge(client):
    _login_admin(client)
    tag = uuid.uuid4().hex[:8]
    seed = _seed_base_with_rascunho(tag)

    resp = client.get(f"/admin/catalogo-versoes/{seed['base_id']}")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert "v1" in html, "Catálogo detalhe deve exibir badge 'v1' para numero_versao=1"


# ---------------------------------------------------------------------------
# 2. codigo_normativo visible as metadata in catálogo detalhe
# ---------------------------------------------------------------------------

def test_catalogo_detalhe_codigo_normativo_still_visible(client):
    _login_admin(client)
    tag = uuid.uuid4().hex[:8]
    seed = _seed_base_with_rascunho(tag)

    resp = client.get(f"/admin/catalogo-versoes/{seed['base_id']}")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert f"C1NRM{tag}" in html, "codigo_normativo deve continuar visível como metadado"


# ---------------------------------------------------------------------------
# 3. Edit form title shows "Editar versão vN"
# ---------------------------------------------------------------------------

def test_edit_form_title_shows_vn(client):
    _login_admin(client)
    tag = uuid.uuid4().hex[:8]
    seed = _seed_base_with_rascunho(tag)

    resp = client.get(
        f"/admin/catalogo-versoes/{seed['base_id']}/versoes/{seed['versao_id']}/editar"
    )
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert "Editar versão v1" in html, (
        "Título do formulário de edição deve mostrar 'Editar versão v1' quando numero_versao=1"
    )


# ---------------------------------------------------------------------------
# 4. Nova versão form title shows next expected version
# ---------------------------------------------------------------------------

def test_nova_versao_form_title_shows_next_vn(client):
    _login_admin(client)
    tag = uuid.uuid4().hex[:8]
    seed = _seed_base_with_rascunho(tag)

    resp = client.get(f"/admin/catalogo-versoes/{seed['base_id']}/nova-versao")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # Already has v1 rascunho → next should be v2
    assert "será v2" in html, (
        "Título de nova versão deve indicar a próxima versão prevista (será v2)"
    )


# ---------------------------------------------------------------------------
# 5. Matriz versoes page shows vN in current-link chip
# ---------------------------------------------------------------------------

def test_matriz_versoes_shows_vn_in_current_link(versioned_env):
    client = versioned_env["client"]
    _login_admin(client)
    seed = _seed_fresh_matrix_with_link()

    resp = client.get(f"/admin/matrizes/{seed['matriz_id']}/versoes")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert "v1" in html, (
        "Tela de versões da matriz deve mostrar 'v1' no chip da versão atual"
    )


# ---------------------------------------------------------------------------
# 6. Matriz versoes select options include vN
# ---------------------------------------------------------------------------

def test_matriz_versoes_select_options_include_vn(versioned_env):
    client = versioned_env["client"]
    _login_admin(client)
    seed = _seed_fresh_matrix_with_link()

    resp = client.get(f"/admin/matrizes/{seed['matriz_id']}/versoes")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert "v1 —" in html or "v1&nbsp;" in html or ">v1" in html, (
        "As opções do select de versões devem incluir 'v1' para numero_versao=1"
    )


# ---------------------------------------------------------------------------
# 7. codigo_normativo still visible in matriz versoes page
# ---------------------------------------------------------------------------

def test_matriz_versoes_codigo_normativo_still_visible(versioned_env):
    client = versioned_env["client"]
    _login_admin(client)
    seed = _seed_fresh_matrix_with_link()

    resp = client.get(f"/admin/matrizes/{seed['matriz_id']}/versoes")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert seed["norma_codigo"] in html, (
        "codigo_normativo deve continuar visível como metadado na tela de versões da matriz"
    )


# ---------------------------------------------------------------------------
# 8. get_versoes_ativas_por_base_na_matriz includes numero_versao
# ---------------------------------------------------------------------------

def test_versoes_ativas_query_includes_numero_versao(versioned_env):
    seed = _seed_fresh_matrix_with_link()

    with main.app.app_context():
        conn = main.get_db_connection()
        versoes = main.get_versoes_ativas_por_base_na_matriz(
            conn, seed["matriz_id"], seed["base_id"]
        )

    assert len(versoes) >= 1
    row = versoes[0]
    assert "numero_versao" in row.keys(), (
        "get_versoes_ativas_por_base_na_matriz deve retornar numero_versao"
    )
    assert row["numero_versao"] == 1


# ---------------------------------------------------------------------------
# 9. D7.7B regression: resolver still works after patch
# ---------------------------------------------------------------------------

def test_d77b_resolver_unaffected_by_visibility_patch(versioned_env):
    """Resolver com link explícito continua retornando 'resolved' após o patch C1."""
    seed = _seed_fresh_matrix_with_link()

    with main.app.app_context():
        conn = main.get_db_connection()
        # Find the atividade_id_legacy for this base
        row = conn.execute(
            "SELECT atividade_id_legacy FROM atividade_legacy_map WHERE atividade_base_id = ?",
            (seed["base_id"],),
        ).fetchone()
        assert row is not None
        atividade_id_legacy = row["atividade_id_legacy"]

        result = main.resolver_versao_por_matriz(
            conn,
            matriz_id=seed["matriz_id"],
            atividade_id_legacy=atividade_id_legacy,
            strict_legacy_scope=True,
        )

    assert result["status"] == "resolved", (
        f"D7.7B resolver deve retornar 'resolved' com link explícito; "
        f"obteve {result['status']!r}"
    )
    assert result["atividade_versao_id"] == seed["versao_id"]


# ---------------------------------------------------------------------------
# 10. versoes_anteriores select shows vN in edit form
# ---------------------------------------------------------------------------

def test_versoes_anteriores_select_shows_vn(client):
    """
    Quando há versões anteriores disponíveis no formulário de edição,
    o select deve exibir vN em vez do id numérico.
    """
    _login_admin(client)
    tag = uuid.uuid4().hex[:8]
    # Create base + norma + first versao (ativa) + second versao (rascunho)
    with main.app.app_context():
        conn = main.get_db_connection()
        base_id = conn.execute(
            "INSERT INTO atividade_base (nome_conceito, descricao, status)"
            " VALUES (?, 'Desc', 'ativo') RETURNING id",
            (f"Base Anterior C1 {tag}",),
        ).fetchone()["id"]
        norma_id = conn.execute(
            "INSERT INTO norma_atividade (codigo, eixo, revisao, nome, status)"
            " VALUES (?, 'AAC', 'rev1', ?, 'ativa') RETURNING id",
            (f"C1PREV{tag}", f"Norma Prev C1 {tag}"),
        ).fetchone()["id"]
        # v1 ativa
        conn.execute(
            "INSERT INTO atividade_versao"
            " (atividade_base_id, norma_id, codigo_normativo, eixo, grupo, numero_versao, status)"
            " VALUES (?, ?, ?, 'AAC', '1 - Grupo', 1, 'ativa')",
            (base_id, norma_id, f"C1PREV{tag}"),
        )
        versao_v1_id = conn.execute(
            "SELECT id FROM atividade_versao WHERE atividade_base_id = ? AND numero_versao = 1",
            (base_id,),
        ).fetchone()["id"]
        # v2 rascunho
        norma2_id = conn.execute(
            "INSERT INTO norma_atividade (codigo, eixo, revisao, nome, status)"
            " VALUES (?, 'AAC', 'rev2', ?, 'ativa') RETURNING id",
            (f"C1PREV2{tag}", f"Norma Prev2 C1 {tag}"),
        ).fetchone()["id"]
        versao_v2_id = conn.execute(
            "INSERT INTO atividade_versao"
            " (atividade_base_id, norma_id, codigo_normativo, eixo, grupo, numero_versao, status)"
            " VALUES (?, ?, ?, 'AAC', '1 - Grupo', 2, 'rascunho') RETURNING id",
            (base_id, norma2_id, f"C1PREV2{tag}"),
        ).fetchone()["id"]
        conn.commit()

    resp = client.get(
        f"/admin/catalogo-versoes/{base_id}/versoes/{versao_v2_id}/editar"
    )
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # The versoes_anteriores select should show v1 (the ativa versao is excluded from edit target
    # but available as versao_anterior option)
    assert "v1 —" in html or "v1&nbsp;" in html or ">v1 " in html, (
        "Select versao_anterior deve mostrar 'v1' para a versão com numero_versao=1"
    )
