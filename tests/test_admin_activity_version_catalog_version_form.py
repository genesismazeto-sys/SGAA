"""
D7.2B3-PATCH1 — Testes de criação de atividade_versao em rascunho.

Cobre:
1. GET /admin/catalogo-versoes/<base_id>/nova-versao retorna 200.
2. GET com base inexistente redireciona.
3. POST válido cria atividade_versao com status 'rascunho' e redireciona para detalhe.
4. POST norma_id inexistente rejeita e não insere.
5. POST norma inativa rejeita e não insere.
6. POST duplicidade (base_id, norma_id) rejeita e não insere.
7. POST ch_por_evento negativo rejeita.
8. POST versao_anterior_id de outra base rejeita.
9. POST versao_anterior_id de eixo diferente rejeita.
10. POST não altera matriz_atividade_versao_item.
11. POST não altera requisicoes.
12. Templates aluno não expõem termos versionados.
"""
from __future__ import annotations

import os
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


def _count_atividade_versao(client) -> int:
    with main.app.app_context():
        return main.get_db_connection().execute(
            "SELECT COUNT(*) AS c FROM atividade_versao"
        ).fetchone()["c"]


def _count_matriz_versao_item(client) -> int:
    with main.app.app_context():
        try:
            return main.get_db_connection().execute(
                "SELECT COUNT(*) AS c FROM matriz_atividade_versao_item"
            ).fetchone()["c"]
        except Exception:
            return -1


def _count_requisicoes(client) -> int:
    with main.app.app_context():
        return main.get_db_connection().execute(
            "SELECT COUNT(*) AS c FROM requisicoes"
        ).fetchone()["c"]


import uuid

def _seed_base_and_normas(client):
    """
    Insere uma atividade_base e duas normas (ativa e inativa) no banco de teste.
    Retorna dict com base_id, norma_ativa_id, norma_inativa_id.
    """
    token = uuid.uuid4().hex[:8]
    with main.app.app_context():
        conn = main.get_db_connection()
        nome_base = f"Base Versão D72B3 {token}"
        conn.execute(
            "INSERT INTO atividade_base (nome_conceito, descricao, status) VALUES (?, ?, ?)",
            (nome_base, "Descrição", "ativo"),
        )
        base_id = conn.execute(
            "SELECT id FROM atividade_base WHERE nome_conceito = ?",
            (nome_base,),
        ).fetchone()["id"]

        cod_ativa = f"NRM-ATIVA-D72B3-{token}"
        conn.execute(
            "INSERT INTO norma_atividade (codigo, eixo, revisao, nome, status) VALUES (?, ?, ?, ?, ?)",
            (cod_ativa, "AAC", "rev1", "Norma Ativa", "ativa"),
        )
        norma_ativa_id = conn.execute(
            "SELECT id FROM norma_atividade WHERE codigo = ?",
            (cod_ativa,),
        ).fetchone()["id"]

        cod_inat = f"NRM-INAT-D72B3-{token}"
        conn.execute(
            "INSERT INTO norma_atividade (codigo, eixo, revisao, nome, status) VALUES (?, ?, ?, ?, ?)",
            (cod_inat, "AAC", "rev1", "Norma Inativa", "inativa"),
        )
        norma_inativa_id = conn.execute(
            "SELECT id FROM norma_atividade WHERE codigo = ?",
            (cod_inat,),
        ).fetchone()["id"]

        conn.commit()
    return {
        "base_id": base_id,
        "norma_ativa_id": norma_ativa_id,
        "norma_inativa_id": norma_inativa_id,
        "codigo_ativa": cod_ativa,
        "codigo_inativa": cod_inat,
    }


def _post_nova_versao(client, base_id, norma_id, **kwargs):
    data = {
        "norma_id": str(norma_id),
        "grupo": kwargs.get("grupo", "1 - Grupo teste"),
        "ch_por_evento": kwargs.get("ch_por_evento", "4"),
        "limite_semestre": kwargs.get("limite_semestre", "40"),
        "limite_total": kwargs.get("limite_total", "100"),
        "observacao_aluno": kwargs.get("observacao_aluno", ""),
        "observacao_admin": kwargs.get("observacao_admin", ""),
        "vigencia_inicio": kwargs.get("vigencia_inicio", ""),
        "vigencia_fim": kwargs.get("vigencia_fim", ""),
        "versao_anterior_id": kwargs.get("versao_anterior_id", ""),
    }
    return client.post(
        f"/admin/catalogo-versoes/{base_id}/nova-versao",
        data=data,
        follow_redirects=False,
    )


# ---------------------------------------------------------------------------
# 1. GET retorna 200
# ---------------------------------------------------------------------------

def test_get_nova_versao_returns_200(client):
    _login_admin(client)
    seed = _seed_base_and_normas(client)
    r = client.get(f"/admin/catalogo-versoes/{seed['base_id']}/nova-versao")
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# 2. GET base inexistente redireciona
# ---------------------------------------------------------------------------

def test_get_nova_versao_missing_base_redirects(client):
    _login_admin(client)
    r = client.get("/admin/catalogo-versoes/999999/nova-versao")
    assert r.status_code == 302
    assert "/admin/catalogo-versoes" in r.headers.get("Location", "")


# ---------------------------------------------------------------------------
# 3. POST válido cria versão em rascunho
# ---------------------------------------------------------------------------

def test_post_nova_versao_valid_creates_rascunho(client):
    _login_admin(client)
    seed = _seed_base_and_normas(client)
    before = _count_atividade_versao(client)

    r = _post_nova_versao(client, seed["base_id"], seed["norma_ativa_id"])
    assert r.status_code == 302, f"Esperado 302, obtido {r.status_code}"
    assert f"/admin/catalogo-versoes/{seed['base_id']}" in r.headers.get("Location", "")

    after = _count_atividade_versao(client)
    assert after == before + 1

    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT status, codigo_normativo, eixo FROM atividade_versao WHERE atividade_base_id = ? AND norma_id = ?",
            (seed["base_id"], seed["norma_ativa_id"]),
        ).fetchone()
    assert row is not None
    assert row["status"] == "rascunho"
    assert row["codigo_normativo"] == seed["codigo_ativa"]
    assert row["eixo"] == "AAC"


# ---------------------------------------------------------------------------
# 4. POST norma_id inexistente rejeita
# ---------------------------------------------------------------------------

def test_post_nova_versao_invalid_norma_rejected(client):
    _login_admin(client)
    seed = _seed_base_and_normas(client)
    before = _count_atividade_versao(client)
    r = _post_nova_versao(client, seed["base_id"], 999999)
    assert r.status_code == 200
    assert _count_atividade_versao(client) == before


# ---------------------------------------------------------------------------
# 5. POST norma inativa rejeita
# ---------------------------------------------------------------------------

def test_post_nova_versao_inactive_norma_rejected(client):
    _login_admin(client)
    seed = _seed_base_and_normas(client)
    before = _count_atividade_versao(client)
    r = _post_nova_versao(client, seed["base_id"], seed["norma_inativa_id"])
    assert r.status_code == 200
    assert _count_atividade_versao(client) == before


# ---------------------------------------------------------------------------
# 6. POST duplicidade base+norma rejeita
# ---------------------------------------------------------------------------

def test_post_nova_versao_duplicate_rejected(client):
    _login_admin(client)
    seed = _seed_base_and_normas(client)
    _post_nova_versao(client, seed["base_id"], seed["norma_ativa_id"])
    before = _count_atividade_versao(client)
    r = _post_nova_versao(client, seed["base_id"], seed["norma_ativa_id"])
    assert r.status_code == 200
    assert _count_atividade_versao(client) == before


# ---------------------------------------------------------------------------
# 7. POST ch_por_evento negativo rejeita
# ---------------------------------------------------------------------------

def test_post_nova_versao_negative_hours_rejected(client):
    _login_admin(client)
    seed = _seed_base_and_normas(client)
    before = _count_atividade_versao(client)
    r = _post_nova_versao(client, seed["base_id"], seed["norma_ativa_id"], ch_por_evento="-1")
    assert r.status_code == 200
    assert _count_atividade_versao(client) == before


# ---------------------------------------------------------------------------
# 8. POST versao_anterior_id de outra base rejeita
# ---------------------------------------------------------------------------

def test_post_nova_versao_prev_other_base_rejected(client):
    _login_admin(client)
    seed = _seed_base_and_normas(client)
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "INSERT INTO atividade_base (nome_conceito, descricao, status) VALUES (?, ?, ?)",
            ("Outra Base", "Desc", "ativo"),
        )
        outra_base_id = conn.execute(
            "SELECT id FROM atividade_base WHERE nome_conceito = ?", ("Outra Base",)
        ).fetchone()["id"]
        conn.execute(
            """
            INSERT INTO atividade_versao (
                atividade_base_id, norma_id, codigo_normativo, eixo, grupo, status
            ) VALUES (?, ?, ?, ?, ?, 'rascunho')
            """,
            (outra_base_id, seed["norma_ativa_id"], seed["codigo_ativa"], "AAC", "Grupo"),
        )
        outra_versao_id = conn.execute(
            "SELECT id FROM atividade_versao WHERE atividade_base_id = ?", (outra_base_id,)
        ).fetchone()["id"]
        conn.commit()

    before = _count_atividade_versao(client)
    r = _post_nova_versao(client, seed["base_id"], seed["norma_ativa_id"], versao_anterior_id=str(outra_versao_id))
    assert r.status_code == 200
    assert _count_atividade_versao(client) == before


# ---------------------------------------------------------------------------
# 9. POST versao_anterior_id de eixo diferente rejeita
# ---------------------------------------------------------------------------

def test_post_nova_versao_prev_different_eixo_rejected(client):
    _login_admin(client)
    seed = _seed_base_and_normas(client)
    token_aeu = uuid.uuid4().hex[:8]
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "INSERT INTO norma_atividade (codigo, eixo, revisao, nome, status) VALUES (?, ?, ?, ?, ?)",
            (f"NRM-AEU-D72B3-{token_aeu}", "AEU", "rev1", "Norma AEU", "ativa"),
        )
        cod_aeu = f"NRM-AEU-D72B3-{token_aeu}"
        norma_aeu_id = conn.execute(
            "SELECT id FROM norma_atividade WHERE codigo = ?", (cod_aeu,)
        ).fetchone()["id"]
        conn.execute(
            """
            INSERT INTO atividade_versao (
                atividade_base_id, norma_id, codigo_normativo, eixo, grupo, status
            ) VALUES (?, ?, ?, ?, ?, 'rascunho')
            """,
            (seed["base_id"], norma_aeu_id, cod_aeu, "AEU", "Grupo AEU"),
        )
        versao_aeu_id = conn.execute(
            "SELECT id FROM atividade_versao WHERE atividade_base_id = ? AND eixo = ?",
            (seed["base_id"], "AEU"),
        ).fetchone()["id"]
        conn.commit()

    before = _count_atividade_versao(client)
    r = _post_nova_versao(client, seed["base_id"], seed["norma_ativa_id"], versao_anterior_id=str(versao_aeu_id))
    assert r.status_code == 200
    assert _count_atividade_versao(client) == before


# ---------------------------------------------------------------------------
# 10. POST não altera matriz_atividade_versao_item
# ---------------------------------------------------------------------------

def test_post_nova_versao_does_not_touch_matriz_item(client):
    _login_admin(client)
    seed = _seed_base_and_normas(client)
    before = _count_matriz_versao_item(client)
    _post_nova_versao(client, seed["base_id"], seed["norma_ativa_id"])
    after = _count_matriz_versao_item(client)
    if before != -1:
        assert after == before


# ---------------------------------------------------------------------------
# 11. POST não altera requisicoes
# ---------------------------------------------------------------------------

def test_post_nova_versao_does_not_touch_requisicoes(client):
    _login_admin(client)
    seed = _seed_base_and_normas(client)
    before = _count_requisicoes(client)
    _post_nova_versao(client, seed["base_id"], seed["norma_ativa_id"])
    after = _count_requisicoes(client)
    assert after == before


# ---------------------------------------------------------------------------
# 12. Templates aluno não expõem termos versionados
# ---------------------------------------------------------------------------

def test_student_templates_do_not_expose_versioning_terms(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 9999999
        sess["user_type"] = "aluno"
        sess["user_name"] = "Aluno Teste"

    forbidden = ["atividade_versao_id", "snapshot versionado", "diagnóstico do snapshot"]
    for path in ["/aluno/dashboard", "/aluno/minhas-requisicoes"]:
        r = client.get(path, follow_redirects=True)
        html_lower = r.get_data(as_text=True).lower()
        for term in forbidden:
            assert term not in html_lower, f"Termo '{term}' não deve aparecer em {path}"


# ---------------------------------------------------------------------------
# 13. Formulário tem placeholder de norma e nenhuma pré-selecionada
# ---------------------------------------------------------------------------

def test_get_nova_versao_form_has_norma_placeholder(client):
    _login_admin(client)
    seed = _seed_base_and_normas(client)
    r = client.get(f"/admin/catalogo-versoes/{seed['base_id']}/nova-versao")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'Selecione uma norma' in html
    # Garante que nenhuma norma real tem selected por default
    # (norma_id vazio no GET → nenhuma option deve ter selected exceto o placeholder)
    selected_count = html.count('selected')
    assert selected_count <= 1, "Nenhuma norma deve vir pré-selecionada no GET"


# ---------------------------------------------------------------------------
# 14. Formulário tem select para versao_anterior_id com placeholder vazio
# ---------------------------------------------------------------------------

def test_get_nova_versao_form_has_versao_anterior_select(client):
    _login_admin(client)
    seed = _seed_base_and_normas(client)
    r = client.get(f"/admin/catalogo-versoes/{seed['base_id']}/nova-versao")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert '<select id="versao_anterior_id" name="versao_anterior_id"' in html
    assert 'Sem versão anterior' in html


# ---------------------------------------------------------------------------
# 15. POST sem norma_id rejeita e não insere
# ---------------------------------------------------------------------------

def test_post_nova_versao_empty_norma_id_rejected(client):
    _login_admin(client)
    seed = _seed_base_and_normas(client)
    before = _count_atividade_versao(client)
    r = client.post(
        f"/admin/catalogo-versoes/{seed['base_id']}/nova-versao",
        data={
            "norma_id": "",
            "grupo": "1 - Grupo",
            "ch_por_evento": "4",
            "limite_semestre": "40",
            "limite_total": "100",
        },
        follow_redirects=False,
    )
    assert r.status_code == 200
    assert _count_atividade_versao(client) == before


# ---------------------------------------------------------------------------
# 16. POST número não numérico rejeita
# ---------------------------------------------------------------------------

def test_post_nova_versao_non_numeric_hours_rejected(client):
    _login_admin(client)
    seed = _seed_base_and_normas(client)
    before = _count_atividade_versao(client)
    r = _post_nova_versao(client, seed["base_id"], seed["norma_ativa_id"], ch_por_evento="abc")
    assert r.status_code == 200
    assert _count_atividade_versao(client) == before


# ---------------------------------------------------------------------------
# 17. POST versao_anterior_id inexistente rejeita
# ---------------------------------------------------------------------------

def test_post_nova_versao_invalid_versao_anterior_id_rejected(client):
    _login_admin(client)
    seed = _seed_base_and_normas(client)
    before = _count_atividade_versao(client)
    r = _post_nova_versao(client, seed["base_id"], seed["norma_ativa_id"], versao_anterior_id="999999")
    assert r.status_code == 200
    assert _count_atividade_versao(client) == before
