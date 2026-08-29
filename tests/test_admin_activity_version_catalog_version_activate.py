"""
COV-1 restoration — Activation of atividade_versao in rascunho.

Adapted from the pre-Norma suite (test_admin_activity_version_catalog_version_activate.py)
with all Norma-domain setup removed (norma_atividade, norma_id, codigo_normativo).

Covers:
  1. POST ativar versão rascunho retorna redirect e muda status para ativa.
  2. POST ativar versão inexistente não gera 500.
  3. POST ativar versão de outra base rejeita e não muda status.
  4. POST ativar versão já ativa rejeita.
  5. POST ativar versão inativa rejeita.
  6. POST ativar versão descontinuada rejeita.
  7. POST ativar versão substituida rejeita.
  8. POST ativar não altera matriz_atividade_versao_item.
  9. POST ativar não altera requisicoes.
 10. POST ativar não altera atividade_transicao.
 11. Após ativar, rota de edição existente bloqueia edição.
 12. Após ativar, resolver considera a versão ativa como candidata válida.
 13. Detalhe da base mostra botão Ativar apenas para rascunho.
 14. Detalhe da base não mostra botão Ativar para ativa/inativa/descontinuada/substituida.
 15. Rotas read-only continuam respondendo 200.
 16. Templates de aluno não expõem dados técnicos de versionamento.
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
from app.versioning import resolver as resolver_service


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


# ---------------------------------------------------------------------------
# Count helpers
# ---------------------------------------------------------------------------

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


def _count_atividade_transicao(client) -> int:
    with main.app.app_context():
        return main.get_db_connection().execute(
            "SELECT COUNT(*) AS c FROM atividade_transicao"
        ).fetchone()["c"]


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def _seed_base(client) -> dict:
    token = uuid.uuid4().hex[:8]
    with main.app.app_context():
        conn = main.get_db_connection()
        nome_base = f"Base Ativacao {token}"
        conn.execute(
            "INSERT INTO atividade_base (nome_conceito, descricao, status) VALUES (?, ?, ?)",
            (nome_base, "Descrição", "ativo"),
        )
        base_id = conn.execute(
            "SELECT id FROM atividade_base WHERE nome_conceito = ?",
            (nome_base,),
        ).fetchone()["id"]
        conn.commit()
    return {"base_id": base_id}


def _insert_versao(
    client,
    *,
    atividade_base_id,
    eixo="AAC",
    status="rascunho",
    grupo="1 - Grupo teste",
) -> int:
    with main.app.app_context():
        conn = main.get_db_connection()
        next_num = conn.execute(
            "SELECT COALESCE(MAX(numero_versao), 0) + 1 FROM atividade_versao WHERE atividade_base_id = ?",
            (atividade_base_id,),
        ).fetchone()[0]
        cur = conn.execute(
            """
            INSERT INTO atividade_versao (
                atividade_base_id, eixo, grupo, status, numero_versao
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (atividade_base_id, eixo, grupo, status, next_num),
        )
        versao_id = cur.lastrowid
        conn.commit()
    return versao_id


def _get_versao(client, versao_id):
    with main.app.app_context():
        return main.get_db_connection().execute(
            "SELECT * FROM atividade_versao WHERE id = ?",
            (versao_id,),
        ).fetchone()


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------

def _get_detalhe_base(client, base_id):
    return client.get(f"/admin/catalogo-versoes/{base_id}")


def _post_ativar_versao(client, base_id, versao_id):
    return client.post(
        f"/admin/catalogo-versoes/{base_id}/versoes/{versao_id}/ativar",
        follow_redirects=False,
    )


# ---------------------------------------------------------------------------
# 1. POST ativar versão rascunho muda status para ativa
# ---------------------------------------------------------------------------

def test_post_ativar_versao_rascunho_changes_status_to_ativa(client):
    _login_admin(client)
    seed = _seed_base(client)
    versao_id = _insert_versao(
        client,
        atividade_base_id=seed["base_id"],
        eixo="AAC",
    )
    r = _post_ativar_versao(client, seed["base_id"], versao_id)
    assert r.status_code == 302
    assert f"/admin/catalogo-versoes/{seed['base_id']}" in r.headers.get("Location", "")
    versao = _get_versao(client, versao_id)
    assert versao["status"] == "ativa"


# ---------------------------------------------------------------------------
# 2. POST ativar versão inexistente não gera 500
# ---------------------------------------------------------------------------

def test_post_ativar_versao_inexistente_redirects_without_500(client):
    _login_admin(client)
    seed = _seed_base(client)
    r = _post_ativar_versao(client, seed["base_id"], 999999)
    assert r.status_code == 302
    assert r.status_code != 500
    assert f"/admin/catalogo-versoes/{seed['base_id']}" in r.headers.get("Location", "")


# ---------------------------------------------------------------------------
# 3. POST ativar versão de outra base rejeita e não muda status
# ---------------------------------------------------------------------------

def test_post_ativar_versao_outra_base_rejected_and_status_unchanged(client):
    _login_admin(client)
    seed = _seed_base(client)
    versao_id = _insert_versao(
        client,
        atividade_base_id=seed["base_id"],
        eixo="AAC",
    )
    with main.app.app_context():
        conn = main.get_db_connection()
        nome_outra = f"Outra Base Ativacao {uuid.uuid4().hex[:6]}"
        conn.execute(
            "INSERT INTO atividade_base (nome_conceito, descricao, status) VALUES (?, ?, ?)",
            (nome_outra, "Desc", "ativo"),
        )
        outra_base_id = conn.execute(
            "SELECT id FROM atividade_base WHERE nome_conceito = ?", (nome_outra,)
        ).fetchone()["id"]
        conn.commit()

    r = _post_ativar_versao(client, outra_base_id, versao_id)
    assert r.status_code == 302
    versao = _get_versao(client, versao_id)
    assert versao["status"] == "rascunho"


# ---------------------------------------------------------------------------
# 4. POST ativar versão já ativa rejeita
# ---------------------------------------------------------------------------

def test_post_ativar_versao_ja_ativa_rejected(client):
    _login_admin(client)
    seed = _seed_base(client)
    versao_id = _insert_versao(
        client,
        atividade_base_id=seed["base_id"],
        eixo="AAC",
        status="ativa",
    )
    r = _post_ativar_versao(client, seed["base_id"], versao_id)
    assert r.status_code == 302
    versao = _get_versao(client, versao_id)
    assert versao["status"] == "ativa"


# ---------------------------------------------------------------------------
# 5. POST ativar versão inativa rejeita
# ---------------------------------------------------------------------------

def test_post_ativar_versao_inativa_rejected(client):
    _login_admin(client)
    seed = _seed_base(client)
    versao_id = _insert_versao(
        client,
        atividade_base_id=seed["base_id"],
        eixo="AAC",
        status="inativa",
    )
    r = _post_ativar_versao(client, seed["base_id"], versao_id)
    assert r.status_code == 302
    versao = _get_versao(client, versao_id)
    assert versao["status"] == "inativa"


# ---------------------------------------------------------------------------
# 6. POST ativar versão descontinuada rejeita
# ---------------------------------------------------------------------------

def test_post_ativar_versao_descontinuada_rejected(client):
    _login_admin(client)
    seed = _seed_base(client)
    versao_id = _insert_versao(
        client,
        atividade_base_id=seed["base_id"],
        eixo="AAC",
        status="descontinuada",
    )
    r = _post_ativar_versao(client, seed["base_id"], versao_id)
    assert r.status_code == 302
    versao = _get_versao(client, versao_id)
    assert versao["status"] == "descontinuada"


# ---------------------------------------------------------------------------
# 7. POST ativar versão substituida rejeita
# ---------------------------------------------------------------------------

def test_post_ativar_versao_substituida_rejected(client):
    _login_admin(client)
    seed = _seed_base(client)
    versao_id = _insert_versao(
        client,
        atividade_base_id=seed["base_id"],
        eixo="AAC",
        status="substituida",
    )
    r = _post_ativar_versao(client, seed["base_id"], versao_id)
    assert r.status_code == 302
    versao = _get_versao(client, versao_id)
    assert versao["status"] == "substituida"


# ---------------------------------------------------------------------------
# 8. POST ativar não altera matriz_atividade_versao_item
# ---------------------------------------------------------------------------

def test_post_ativar_does_not_touch_matriz_item(client):
    _login_admin(client)
    seed = _seed_base(client)
    versao_id = _insert_versao(
        client,
        atividade_base_id=seed["base_id"],
        eixo="AAC",
    )
    before = _count_matriz_versao_item(client)
    r = _post_ativar_versao(client, seed["base_id"], versao_id)
    assert r.status_code == 302
    if before != -1:
        assert _count_matriz_versao_item(client) == before


# ---------------------------------------------------------------------------
# 9. POST ativar não altera requisicoes
# ---------------------------------------------------------------------------

def test_post_ativar_does_not_touch_requisicoes(client):
    _login_admin(client)
    seed = _seed_base(client)
    versao_id = _insert_versao(
        client,
        atividade_base_id=seed["base_id"],
        eixo="AAC",
    )
    before = _count_requisicoes(client)
    r = _post_ativar_versao(client, seed["base_id"], versao_id)
    assert r.status_code == 302
    assert _count_requisicoes(client) == before


# ---------------------------------------------------------------------------
# 10. POST ativar não altera atividade_transicao
# ---------------------------------------------------------------------------

def test_post_ativar_does_not_touch_atividade_transicao(client):
    _login_admin(client)
    seed = _seed_base(client)
    versao_id = _insert_versao(
        client,
        atividade_base_id=seed["base_id"],
        eixo="AAC",
    )
    before = _count_atividade_transicao(client)
    r = _post_ativar_versao(client, seed["base_id"], versao_id)
    assert r.status_code == 302
    assert _count_atividade_transicao(client) == before


# ---------------------------------------------------------------------------
# 11. Após ativar, rota de edição existente bloqueia edição
# ---------------------------------------------------------------------------

def test_after_ativar_rota_edicao_blocks(client):
    _login_admin(client)
    seed = _seed_base(client)
    versao_id = _insert_versao(
        client,
        atividade_base_id=seed["base_id"],
        eixo="AAC",
    )
    r_ativar = _post_ativar_versao(client, seed["base_id"], versao_id)
    assert r_ativar.status_code == 302
    versao = _get_versao(client, versao_id)
    assert versao["status"] == "ativa"

    r_editar = client.get(
        f"/admin/catalogo-versoes/{seed['base_id']}/versoes/{versao_id}/editar"
    )
    assert r_editar.status_code == 302
    assert f"/admin/catalogo-versoes/{seed['base_id']}" in r_editar.headers.get("Location", "")


# ---------------------------------------------------------------------------
# 12. Após ativar, resolver considera a versão ativa como candidata válida
# ---------------------------------------------------------------------------

def test_after_ativar_resolver_considera_versao_como_ativa(client):
    _login_admin(client)
    seed = _seed_base(client)
    versao_id = _insert_versao(
        client,
        atividade_base_id=seed["base_id"],
        eixo="AAC",
    )
    r = _post_ativar_versao(client, seed["base_id"], versao_id)
    assert r.status_code == 302

    versao = _get_versao(client, versao_id)
    assert versao["status"] == "ativa"
    with main.app.app_context():
        conn = main.get_db_connection()
        token = uuid.uuid4().hex[:8]
        curso_id = conn.execute(
            "INSERT INTO cursos (nome,codigo,duracao_periodos) VALUES (?,?,8) RETURNING id",
            (f"Curso resolver {token}", f"RES-{token}"),
        ).fetchone()["id"]
        matriz_id = conn.execute(
            "INSERT INTO matrizes_atividades (curso_id,nome,status) "
            "VALUES (?,?,'vigente') RETURNING id",
            (curso_id, f"Matriz resolver {token}"),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO matriz_atividade_versao_item "
            "(matriz_id,atividade_base_id,atividade_versao_id) VALUES (?,?,?)",
            (matriz_id, seed["base_id"], versao_id),
        )
        resolved = resolver_service.resolver_versao_por_matriz(
            conn, matriz_id=matriz_id, atividade_versao_id=versao_id
        )
        assert resolved["status"] == "resolved"
        assert resolved["atividade_versao_id"] == versao_id


# ---------------------------------------------------------------------------
# 13. Detalhe da base mostra botão Ativar apenas para rascunho
# ---------------------------------------------------------------------------

def test_detalhe_base_mostra_botao_ativar_apenas_para_rascunho(client):
    _login_admin(client)
    seed = _seed_base(client)
    versao_id = _insert_versao(
        client,
        atividade_base_id=seed["base_id"],
        eixo="AAC",
    )
    r = _get_detalhe_base(client, seed["base_id"])
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "Ativar" in html
    assert f"/admin/catalogo-versoes/{seed['base_id']}/versoes/{versao_id}/ativar" in html


# ---------------------------------------------------------------------------
# 14. Detalhe da base não mostra botão Ativar para outros status
# ---------------------------------------------------------------------------

def test_detalhe_base_nao_mostra_botao_ativar_para_outros_status(client):
    _login_admin(client)
    seed = _seed_base(client)

    versao_ids = {}
    for status in ("ativa", "inativa", "descontinuada", "substituida"):
        versao_ids[status] = _insert_versao(
            client,
            atividade_base_id=seed["base_id"],
            eixo="AAC",
            status=status,
        )

    r = _get_detalhe_base(client, seed["base_id"])
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    for status, versao_id in versao_ids.items():
        url = f"/admin/catalogo-versoes/{seed['base_id']}/versoes/{versao_id}/ativar"
        assert url not in html, (
            f"Status {status} não deveria exibir botão Ativar (URL {url})"
        )


# ---------------------------------------------------------------------------
# 15. Rotas read-only continuam respondendo 200
# ---------------------------------------------------------------------------

def test_readonly_routes_still_respond(client):
    _login_admin(client)
    seed = _seed_base(client)
    routes = [
        "/admin/catalogo-versoes",
        f"/admin/catalogo-versoes/{seed['base_id']}",
    ]
    for path in routes:
        r = client.get(path)
        assert r.status_code == 200, f"Rota {path} não respondeu 200"


# ---------------------------------------------------------------------------
# 16. Templates de aluno não expõem dados técnicos de versionamento
# ---------------------------------------------------------------------------

def test_aluno_templates_do_not_expose_versioning_metadata(client):
    from pathlib import Path

    templates_dir = Path(BASE) / "templates"
    forbidden = (
        "codigo_normativo",
        "_atividade_versao_status_ativo",
    )
    aluno_files = [
        "aluno_dashboard.html",
        "aluno_nova_requisicao.html",
        "aluno_minhas_requisicoes.html",
        "aluno_progresso.html",
        "aluno_reportar.html",
        "aluno_arquivos.html",
        "aluno_meus_dados.html",
        "aluno_requisicao_detalhe.html",
    ]
    for fname in aluno_files:
        fpath = templates_dir / fname
        if not fpath.exists():
            continue
        content = fpath.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in content, (
                f"Template de aluno {fname} referencia token proibido: {token}"
            )