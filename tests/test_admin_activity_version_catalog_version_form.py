"""
COV-1 restoration — Creation of atividade_versao in rascunho (form flow).

Adapted from the pre-Norma suite (test_admin_activity_version_catalog_version_form.py)
with all Norma-domain setup removed (norma_atividade, norma_id, codigo_normativo).

Covers:
 1. GET /admin/catalogo-versoes/<base_id>/nova-versao retorna 200.
 2. GET com base inexistente redireciona.
 3. POST válido cria atividade_versao com status 'rascunho' e redireciona para detalhe.
 4. POST eixo inválido rejeita e não insere.
 5. POST ch_por_evento negativo rejeita.
 6. POST versao_anterior_id de outra base rejeita.
 7. POST versao_anterior_id de eixo diferente rejeita.
 8. POST não altera matriz_atividade_versao_item.
 9. POST não altera requisicoes.
10. Templates aluno não expõem termos versionados.
11. Formulário tem select para versao_anterior_id com placeholder vazio.
12. POST número não numérico rejeita.
13. POST versao_anterior_id inexistente rejeita.
14. Segunda versão para a mesma base não é bloqueada por duplicidade
    (o próximo numero_versao é atribuído automaticamente).
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


def _seed_base(client) -> dict:
    token = uuid.uuid4().hex[:8]
    with main.app.app_context():
        conn = main.get_db_connection()
        nome_base = f"Base Versão {token}"
        conn.execute(
            "INSERT INTO atividade_base (nome_conceito, descricao, status) VALUES (?, ?, ?)",
            (nome_base, "Descrição", "ativo"),
        )
        base_id = conn.execute(
            "SELECT id FROM atividade_base WHERE nome_conceito = ?",
            (nome_base,),
        ).fetchone()["id"]
        conn.commit()
    return {"base_id": base_id, "nome": nome_base, "descricao": "Descrição"}


def _post_nova_versao(client, base_id, **kwargs):
    with main.app.app_context():
        base = main.get_db_connection().execute(
            "SELECT nome_conceito, descricao FROM atividade_base WHERE id = ?", (base_id,)
        ).fetchone()
    eixo = kwargs.get("eixo", "AAC")
    limite_semestre = kwargs.get("limite_semestre", "40")
    limite_total = kwargs.get("limite_total", "100")
    data = {
        "tipo_atividade": (
            "Extensão Universitária" if eixo == "AEU" else
            ("Acadêmica Complementar" if eixo == "AAC" else eixo)
        ),
        "grupo": kwargs.get("grupo", "1 - Grupo teste"),
        "nome": base["nome_conceito"],
        "descricao": base["descricao"] or "",
        "ch_por_evento": kwargs.get("ch_por_evento", "4"),
        "tipo_limitacao": "semestral" if limite_semestre != "" else ("total" if limite_total != "" else ""),
        "limite_valor": limite_semestre if limite_semestre != "" else limite_total,
        "observacoes": kwargs.get("observacao_admin") or kwargs.get("observacao_aluno") or "",
        "versao_anterior_id": kwargs.get("versao_anterior_id", ""),
    }
    return client.post(
        f"/admin/catalogo-versoes/{base_id}/nova-versao",
        data=data,
        follow_redirects=False,
    )


def _insert_versao_direct(client, *, base_id: int, eixo: str, numero_versao: int, status: str = "rascunho") -> int:
    with main.app.app_context():
        conn = main.get_db_connection()
        cur = conn.execute(
            """
            INSERT INTO atividade_versao
                (atividade_base_id, eixo, grupo, status, numero_versao)
            VALUES (?, ?, ?, ?, ?)
            """,
            (base_id, eixo, "Grupo direto", status, numero_versao),
        )
        versao_id = cur.lastrowid
        conn.commit()
    return versao_id


# ---------------------------------------------------------------------------
# 1. GET retorna 200
# ---------------------------------------------------------------------------

def test_get_nova_versao_returns_200(client):
    _login_admin(client)
    seed = _seed_base(client)
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
    seed = _seed_base(client)
    before = _count_atividade_versao(client)

    r = _post_nova_versao(client, seed["base_id"], eixo="AAC")
    assert r.status_code == 302, f"Esperado 302, obtido {r.status_code}"
    assert f"/admin/catalogo-versoes/{seed['base_id']}" in r.headers.get("Location", "")

    after = _count_atividade_versao(client)
    assert after == before + 1

    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT status, eixo, numero_versao FROM atividade_versao WHERE atividade_base_id = ?",
            (seed["base_id"],),
        ).fetchone()
    assert row is not None
    assert row["status"] == "rascunho"
    assert row["eixo"] == "AAC"
    assert row["numero_versao"] == 1


# ---------------------------------------------------------------------------
# 4. POST eixo inválido rejeita e não insere
# ---------------------------------------------------------------------------

def test_post_nova_versao_invalid_eixo_rejected(client):
    _login_admin(client)
    seed = _seed_base(client)
    before = _count_atividade_versao(client)
    r = _post_nova_versao(client, seed["base_id"], eixo="OUTRO")
    assert r.status_code == 200
    assert _count_atividade_versao(client) == before

    r_empty = _post_nova_versao(client, seed["base_id"], eixo="")
    assert r_empty.status_code == 200
    assert _count_atividade_versao(client) == before


# ---------------------------------------------------------------------------
# 5. POST ch_por_evento negativo rejeita
# ---------------------------------------------------------------------------

def test_post_nova_versao_negative_hours_rejected(client):
    _login_admin(client)
    seed = _seed_base(client)
    before = _count_atividade_versao(client)
    r = _post_nova_versao(client, seed["base_id"], eixo="AAC", ch_por_evento="-1")
    assert r.status_code == 200
    assert _count_atividade_versao(client) == before


# ---------------------------------------------------------------------------
# 6. POST versao_anterior_id de outra base rejeita
# ---------------------------------------------------------------------------

def test_post_nova_versao_prev_other_base_rejected(client):
    _login_admin(client)
    seed = _seed_base(client)
    outra_base = _seed_base(client)
    outra_versao_id = _insert_versao_direct(
        client, base_id=outra_base["base_id"], eixo="AAC", numero_versao=1
    )

    before = _count_atividade_versao(client)
    r = _post_nova_versao(client, seed["base_id"], eixo="AAC", versao_anterior_id=str(outra_versao_id))
    assert r.status_code == 200
    assert _count_atividade_versao(client) == before


# ---------------------------------------------------------------------------
# 7. POST versao_anterior_id de eixo diferente rejeita
# ---------------------------------------------------------------------------

def test_post_nova_versao_prev_different_eixo_rejected(client):
    _login_admin(client)
    seed = _seed_base(client)
    versao_aeu_id = _insert_versao_direct(
        client, base_id=seed["base_id"], eixo="AEU", numero_versao=1
    )
    _insert_versao_direct(
        client, base_id=seed["base_id"], eixo="AAC", numero_versao=2
    )

    before = _count_atividade_versao(client)
    r = _post_nova_versao(client, seed["base_id"], eixo="AAC", versao_anterior_id=str(versao_aeu_id))
    assert r.status_code == 200
    assert _count_atividade_versao(client) == before


# ---------------------------------------------------------------------------
# 8. POST não altera matriz_atividade_versao_item
# ---------------------------------------------------------------------------

def test_post_nova_versao_does_not_touch_matriz_item(client):
    _login_admin(client)
    seed = _seed_base(client)
    before = _count_matriz_versao_item(client)
    _post_nova_versao(client, seed["base_id"], eixo="AAC")
    after = _count_matriz_versao_item(client)
    if before != -1:
        assert after == before


# ---------------------------------------------------------------------------
# 9. POST não altera requisicoes
# ---------------------------------------------------------------------------

def test_post_nova_versao_does_not_touch_requisicoes(client):
    _login_admin(client)
    seed = _seed_base(client)
    before = _count_requisicoes(client)
    _post_nova_versao(client, seed["base_id"], eixo="AAC")
    after = _count_requisicoes(client)
    assert after == before


# ---------------------------------------------------------------------------
# 10. Templates aluno não expõem termos versionados
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
# 11. Formulário preserva o controle visível e editável de Versão anterior
# ---------------------------------------------------------------------------

def test_get_nova_versao_form_has_visible_editable_predecessor_select(client):
    _login_admin(client)
    seed = _seed_base(client)
    r = client.get(f"/admin/catalogo-versoes/{seed['base_id']}/nova-versao")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert '<select id="versao_anterior_id" name="versao_anterior_id"' in html
    assert 'Sem versão anterior' in html


# ---------------------------------------------------------------------------
# 12. POST número não numérico rejeita
# ---------------------------------------------------------------------------

def test_post_nova_versao_non_numeric_hours_rejected(client):
    _login_admin(client)
    seed = _seed_base(client)
    before = _count_atividade_versao(client)
    r = _post_nova_versao(client, seed["base_id"], eixo="AAC", ch_por_evento="abc")
    assert r.status_code == 200
    assert _count_atividade_versao(client) == before


# ---------------------------------------------------------------------------
# 13. POST versao_anterior_id inexistente rejeita
# ---------------------------------------------------------------------------

def test_post_nova_versao_invalid_versao_anterior_id_rejected(client):
    _login_admin(client)
    seed = _seed_base(client)
    before = _count_atividade_versao(client)
    r = _post_nova_versao(client, seed["base_id"], eixo="AAC", versao_anterior_id="999999")
    assert r.status_code == 200
    assert _count_atividade_versao(client) == before


# ---------------------------------------------------------------------------
# 14. Segunda versão para a mesma base é permitida com próximo numero_versao
# ---------------------------------------------------------------------------

def test_post_nova_versao_second_version_same_base_gets_next_number(client):
    _login_admin(client)
    seed = _seed_base(client)
    first = _post_nova_versao(client, seed["base_id"], eixo="AAC")
    assert first.status_code == 302

    with main.app.app_context():
        conn = main.get_db_connection()
        v1 = conn.execute(
            "SELECT id FROM atividade_versao WHERE atividade_base_id = ? AND numero_versao = 1",
            (seed["base_id"],),
        ).fetchone()["id"]

    second = _post_nova_versao(
        client, seed["base_id"], eixo="AAC", versao_anterior_id=str(v1),
        ch_por_evento="6",
    )
    assert second.status_code == 302

    with main.app.app_context():
        rows = main.get_db_connection().execute(
            "SELECT numero_versao, versao_anterior_id FROM atividade_versao"
            " WHERE atividade_base_id = ? ORDER BY numero_versao",
            (seed["base_id"],),
        ).fetchall()
    assert [(row["numero_versao"], row["versao_anterior_id"]) for row in rows] == [
        (1, None),
        (2, v1),
    ]
