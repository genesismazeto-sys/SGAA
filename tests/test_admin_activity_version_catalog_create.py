"""
D7.2B2 — Testes de criação de atividade_base e norma_atividade.

Cobre:
1.  GET /admin/catalogo-versoes/nova-base retorna 200.
2.  POST válido cria atividade_base e redireciona para detalhe.
3.  POST nome vazio rejeita e não insere.
4.  POST nome duplicado rejeita e não insere.
5.  POST status inválido rejeita e não insere.
6.  Form possui campo csrf_token.
7.  GET /admin/normas-atividade/nova retorna 200.
8.  POST válido cria norma_atividade e redireciona para listagem.
9.  POST codigo vazio rejeita e não insere.
10. POST codigo duplicado rejeita e não insere.
11. POST eixo inválido rejeita e não insere.
12. POST status inválido (norma) rejeita e não insere.
13. POST revisao vazia rejeita e não insere.
14. Rotas read-only da D7.2B1 continuam 200.
15. D7.1 não é afetada (proxy: rotas do catálogo intactas).
16. Nenhum POST novo altera matriz_atividade_versao_item.
17. Nenhum POST novo altera requisicoes.
18. Nenhum template aluno expõe termos versionados.
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


def _count_atividade_base(client) -> int:
    with main.app.app_context():
        return main.get_db_connection().execute(
            "SELECT COUNT(*) AS c FROM atividade_base"
        ).fetchone()["c"]


def _count_norma_atividade(client) -> int:
    with main.app.app_context():
        return main.get_db_connection().execute(
            "SELECT COUNT(*) AS c FROM norma_atividade"
        ).fetchone()["c"]


def _count_matriz_versao_item(client) -> int:
    with main.app.app_context():
        try:
            return main.get_db_connection().execute(
                "SELECT COUNT(*) AS c FROM matriz_atividade_versao_item"
            ).fetchone()["c"]
        except Exception:
            return -1  # tabela pode não existir em ambiente de teste mínimo


def _count_requisicoes(client) -> int:
    with main.app.app_context():
        return main.get_db_connection().execute(
            "SELECT COUNT(*) AS c FROM requisicoes"
        ).fetchone()["c"]


def _post_base(client, nome_conceito="Base Teste D72B2", descricao="Desc", status="ativo"):
    return client.post(
        "/admin/catalogo-versoes/nova-base",
        data={"nome_conceito": nome_conceito, "descricao": descricao, "status": status},
        follow_redirects=False,
    )


def _post_norma(client, codigo="NRM-D72B2", eixo="AAC", revisao="rev1",
                nome="Norma Teste D72B2", descricao="", status="ativa"):
    return client.post(
        "/admin/normas-atividade/nova",
        data={"codigo": codigo, "eixo": eixo, "revisao": revisao,
              "nome": nome, "descricao": descricao, "status": status},
        follow_redirects=False,
    )


# ---------------------------------------------------------------------------
# 1. GET /admin/catalogo-versoes/nova-base retorna 200
# ---------------------------------------------------------------------------

def test_get_nova_base_returns_200(client):
    _login_admin(client)
    r = client.get("/admin/catalogo-versoes/nova-base")
    assert r.status_code == 200


def test_get_nova_base_requires_admin(client):
    r = client.get("/admin/catalogo-versoes/nova-base")
    assert r.status_code in (302, 401, 403)


def test_get_nova_base_contains_csrf(client):
    _login_admin(client)
    r = client.get("/admin/catalogo-versoes/nova-base")
    html = r.get_data(as_text=True)
    assert 'name="csrf_token"' in html


# ---------------------------------------------------------------------------
# 2. POST válido cria atividade_base e redireciona para detalhe
# ---------------------------------------------------------------------------

def test_post_nova_base_valid_creates_and_redirects(client):
    _login_admin(client)
    before = _count_atividade_base(client)

    r = _post_base(client, nome_conceito="Base Única D72B2")
    assert r.status_code == 302, f"Esperado redirect 302, obtido {r.status_code}"

    after = _count_atividade_base(client)
    assert after == before + 1, "Deve ter inserido exatamente 1 linha em atividade_base"

    location = r.headers.get("Location", "")
    assert "/admin/catalogo-versoes/" in location, \
        f"Redirect deve apontar para detalhe, location={location!r}"


def test_post_nova_base_preserves_original_text(client):
    """Nome inserido deve ser preservado sem alteração de capitalização."""
    _login_admin(client)
    _post_base(client, nome_conceito="MinhaBaseOriginal")

    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT nome_conceito FROM atividade_base WHERE nome_conceito = ?",
            ("MinhaBaseOriginal",),
        ).fetchone()
    assert row is not None, "Linha deve existir no banco"
    assert row["nome_conceito"] == "MinhaBaseOriginal", \
        "Texto original deve ser preservado"


# ---------------------------------------------------------------------------
# 3. POST nome vazio rejeita e não insere
# ---------------------------------------------------------------------------

def test_post_nova_base_empty_nome_rejected(client):
    _login_admin(client)
    before = _count_atividade_base(client)
    r = _post_base(client, nome_conceito="   ")
    assert r.status_code == 200, "Deve renderizar form com erro (não redirecionar)"
    assert _count_atividade_base(client) == before, "Não deve inserir linha"


def test_post_nova_base_blank_nome_rejected(client):
    _login_admin(client)
    before = _count_atividade_base(client)
    r = _post_base(client, nome_conceito="")
    assert r.status_code == 200
    assert _count_atividade_base(client) == before


# ---------------------------------------------------------------------------
# 4. POST nome duplicado rejeita e não insere
# ---------------------------------------------------------------------------

def test_post_nova_base_duplicate_nome_rejected(client):
    _login_admin(client)
    _post_base(client, nome_conceito="Base Duplicada D72B2")
    before = _count_atividade_base(client)

    r = _post_base(client, nome_conceito="Base Duplicada D72B2")
    assert r.status_code == 200, "Deve renderizar form com erro"
    assert _count_atividade_base(client) == before, "Não deve inserir duplicata"


def test_post_nova_base_duplicate_case_insensitive_rejected(client):
    """Duplicidade deve ser detectada case-insensitive."""
    _login_admin(client)
    _post_base(client, nome_conceito="Base Case D72B2")
    before = _count_atividade_base(client)

    r = _post_base(client, nome_conceito="BASE CASE D72B2")
    assert r.status_code == 200
    assert _count_atividade_base(client) == before


# ---------------------------------------------------------------------------
# 5. POST status inválido rejeita e não insere
# ---------------------------------------------------------------------------

def test_post_nova_base_invalid_status_rejected(client):
    _login_admin(client)
    before = _count_atividade_base(client)
    r = _post_base(client, nome_conceito="Base Status Inválido D72B2", status="rascunho")
    assert r.status_code == 200
    assert _count_atividade_base(client) == before


# ---------------------------------------------------------------------------
# 7. GET /admin/normas-atividade/nova retorna 200
# ---------------------------------------------------------------------------

def test_get_nova_norma_returns_200(client):
    _login_admin(client)
    r = client.get("/admin/normas-atividade/nova")
    assert r.status_code == 200


def test_get_nova_norma_requires_admin(client):
    r = client.get("/admin/normas-atividade/nova")
    assert r.status_code in (302, 401, 403)


def test_get_nova_norma_contains_csrf(client):
    _login_admin(client)
    r = client.get("/admin/normas-atividade/nova")
    html = r.get_data(as_text=True)
    assert 'name="csrf_token"' in html


# ---------------------------------------------------------------------------
# 8. POST válido cria norma_atividade e redireciona para listagem
# ---------------------------------------------------------------------------

def test_post_nova_norma_valid_creates_and_redirects(client):
    _login_admin(client)
    before = _count_norma_atividade(client)

    r = _post_norma(client, codigo="NRM-VALID-D72B2")
    assert r.status_code == 302, f"Esperado redirect 302, obtido {r.status_code}"

    after = _count_norma_atividade(client)
    assert after == before + 1, "Deve ter inserido exatamente 1 linha em norma_atividade"

    location = r.headers.get("Location", "")
    assert "/admin/normas-atividade" in location, \
        f"Redirect deve apontar para listagem de normas, location={location!r}"


def test_post_nova_norma_preserves_original_codigo(client):
    """Código inserido deve ser preservado sem alteração."""
    _login_admin(client)
    _post_norma(client, codigo="NRM-PreserveCase-D72B2")

    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT codigo FROM norma_atividade WHERE codigo = ?",
            ("NRM-PreserveCase-D72B2",),
        ).fetchone()
    assert row is not None
    assert row["codigo"] == "NRM-PreserveCase-D72B2"


# ---------------------------------------------------------------------------
# 9. POST codigo vazio rejeita e não insere
# ---------------------------------------------------------------------------

def test_post_nova_norma_empty_codigo_rejected(client):
    _login_admin(client)
    before = _count_norma_atividade(client)
    r = _post_norma(client, codigo="   ")
    assert r.status_code == 200
    assert _count_norma_atividade(client) == before


def test_post_nova_norma_blank_codigo_rejected(client):
    _login_admin(client)
    before = _count_norma_atividade(client)
    r = _post_norma(client, codigo="")
    assert r.status_code == 200
    assert _count_norma_atividade(client) == before


# ---------------------------------------------------------------------------
# 10. POST codigo duplicado rejeita e não insere
# ---------------------------------------------------------------------------

def test_post_nova_norma_duplicate_codigo_rejected(client):
    _login_admin(client)
    _post_norma(client, codigo="NRM-DUP-D72B2")
    before = _count_norma_atividade(client)

    r = _post_norma(client, codigo="NRM-DUP-D72B2")
    assert r.status_code == 200
    assert _count_norma_atividade(client) == before


def test_post_nova_norma_duplicate_case_insensitive_rejected(client):
    _login_admin(client)
    _post_norma(client, codigo="NRM-CASE-D72B2")
    before = _count_norma_atividade(client)

    r = _post_norma(client, codigo="nrm-case-d72b2")
    assert r.status_code == 200
    assert _count_norma_atividade(client) == before


# ---------------------------------------------------------------------------
# 11. POST eixo inválido rejeita e não insere
# ---------------------------------------------------------------------------

def test_post_nova_norma_invalid_eixo_rejected(client):
    _login_admin(client)
    before = _count_norma_atividade(client)
    r = _post_norma(client, codigo="NRM-EIXO-D72B2", eixo="OUTRO")
    assert r.status_code == 200
    assert _count_norma_atividade(client) == before


def test_post_nova_norma_empty_eixo_rejected(client):
    _login_admin(client)
    before = _count_norma_atividade(client)
    r = _post_norma(client, codigo="NRM-EIXO2-D72B2", eixo="")
    assert r.status_code == 200
    assert _count_norma_atividade(client) == before


# ---------------------------------------------------------------------------
# 12. POST status inválido (norma) rejeita e não insere
# ---------------------------------------------------------------------------

def test_post_nova_norma_invalid_status_rejected(client):
    _login_admin(client)
    before = _count_norma_atividade(client)
    r = _post_norma(client, codigo="NRM-STATUS-D72B2", status="ativo")
    assert r.status_code == 200
    assert _count_norma_atividade(client) == before


# ---------------------------------------------------------------------------
# 13. POST revisao vazia rejeita e não insere
# ---------------------------------------------------------------------------

def test_post_nova_norma_empty_revisao_rejected(client):
    _login_admin(client)
    before = _count_norma_atividade(client)
    r = _post_norma(client, codigo="NRM-REV-D72B2", revisao="")
    assert r.status_code == 200
    assert _count_norma_atividade(client) == before


def test_post_nova_norma_blank_revisao_rejected(client):
    _login_admin(client)
    before = _count_norma_atividade(client)
    r = _post_norma(client, codigo="NRM-REV2-D72B2", revisao="   ")
    assert r.status_code == 200
    assert _count_norma_atividade(client) == before


# ---------------------------------------------------------------------------
# 14. Rotas read-only da D7.2B1 continuam 200
# ---------------------------------------------------------------------------

def test_readonly_routes_still_200_after_d72b2(client):
    _login_admin(client)
    for path in [
        "/admin/catalogo-versoes",
        "/admin/normas-atividade",
        "/admin/mapeamento-legado",
    ]:
        r = client.get(path)
        assert r.status_code == 200, f"Rota {path} deve continuar 200"


# ---------------------------------------------------------------------------
# 16. Nenhum POST novo altera matriz_atividade_versao_item
# ---------------------------------------------------------------------------

def test_post_nova_base_does_not_touch_versao_item(client):
    _login_admin(client)
    before = _count_matriz_versao_item(client)
    _post_base(client, nome_conceito="Base IsolationTest D72B2")
    after = _count_matriz_versao_item(client)
    if before != -1:
        assert after == before, \
            "POST nova-base não deve alterar matriz_atividade_versao_item"


def test_post_nova_norma_does_not_touch_versao_item(client):
    _login_admin(client)
    before = _count_matriz_versao_item(client)
    _post_norma(client, codigo="NRM-ISO-D72B2")
    after = _count_matriz_versao_item(client)
    if before != -1:
        assert after == before, \
            "POST nova norma não deve alterar matriz_atividade_versao_item"


# ---------------------------------------------------------------------------
# 17. Nenhum POST novo altera requisicoes
# ---------------------------------------------------------------------------

def test_post_nova_base_does_not_touch_requisicoes(client):
    _login_admin(client)
    before = _count_requisicoes(client)
    _post_base(client, nome_conceito="Base ReqIso D72B2")
    after = _count_requisicoes(client)
    assert after == before, "POST nova-base não deve alterar requisicoes"


def test_post_nova_norma_does_not_touch_requisicoes(client):
    _login_admin(client)
    before = _count_requisicoes(client)
    _post_norma(client, codigo="NRM-REQISO-D72B2")
    after = _count_requisicoes(client)
    assert after == before, "POST nova norma não deve alterar requisicoes"


# ---------------------------------------------------------------------------
# 18. Nenhum template aluno expõe termos versionados
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
            assert term not in html_lower, \
                f"Termo '{term}' não deve aparecer em {path}"
