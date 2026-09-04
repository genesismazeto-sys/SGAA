"""
COV-1 restoration — Lifecycle of atividade_versao status transitions.

Adapted from the pre-Norma suite (test_admin_activity_version_catalog_version_lifecycle.py)
with all Norma-domain setup removed (norma_atividade, matriz_norma, norma_id,
codigo_normativo). Covers:

  1.  POST inativar versão ativa sem vínculo → status muda para 'inativa', redirect.
  2.  POST inativar versão inexistente → redirect (não 500).
  3.  POST inativar versão de outra base → rejeitado, status inalterado.
  4.  POST inativar versão já inativa → rejeitado com flash de erro.
  5.  POST inativar versão rascunho → rejeitado.
  6.  POST inativar versão descontinuada → rejeitado.
  7.  POST inativar versão substituida → rejeitado.
  8.  POST inativar versão com vínculo em matriz_atividade_versao_item →
      bloqueia (status inalterado, vínculo não removido).
  9.  Após inativar, resolver retorna ausência de versão para aquela matriz+base.
 10.  POST descontinuar versão ativa sem vínculo → status muda para 'descontinuada'.
 11.  POST descontinuar versão com vínculo → bloqueia (status inalterado).
 12.  POST descontinuar versão rascunho → rejeitado.
 13.  POST descontinuar versão já descontinuada → rejeitado.
 14.  POST descontinuar versão inativa → rejeitado.
 15.  Detalhe da base mostra botões Inativar/Descontinuar apenas para versão ativa.
 16.  Detalhe da base não mostra Inativar/Descontinuar para versão rascunho
      (mostra Ativar em vez disso).
 17.  Detalhe da base não mostra Inativar/Descontinuar para inativa/descontinuada/substituida.
 18.  CSRF token presente nos forms de inativar e descontinuar.
 19.  Após inativar versão A de uma base, versão B de outra base ainda resolve
      para a mesma matriz.
 20.  Substituir: transição 'mesmo_eixo' + origem 'substituida' + destino intacto.
 21.  Substituir: todas as rejeições (sem destino, destino inválido, inexistente,
      inativo, outra base, outro eixo, auto-substituição, origem com vínculo,
      origem já com transição, destino já usado como origem).
 22.  Inativar/descontinuar não criam atividade_transicao.
"""
from __future__ import annotations

import os
import re
import sys
import uuid

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main
from app.versioning import resolver as resolver_service
from tests.versioned_test_support import isolated_versioned_app_env


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def versioned_env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "d72b5_lifecycle.db") as env:
        yield env


def _login_admin(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["user_type"] = "admin"
        sess["user_name"] = "Admin Lifecycle Test"


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _seed_ativa_sem_vinculo() -> dict:
    t = uuid.uuid4().hex[:8]
    with main.app.app_context():
        conn = main.get_db_connection()
        base_id = conn.execute(
            "INSERT INTO atividade_base (nome_conceito, descricao, status)"
            " VALUES (?, 'Base B5', 'ativo') RETURNING id",
            (f"Base B5 {t}",),
        ).fetchone()["id"]
        versao_id = conn.execute(
            "INSERT INTO atividade_versao"
            " (atividade_base_id, eixo, grupo, numero_versao, status)"
            " VALUES (?, 'AAC', '1 - B5', 1, 'ativa') RETURNING id",
            (base_id,),
        ).fetchone()["id"]
        conn.commit()
    return {"base_id": base_id, "versao_id": versao_id}


def _seed_versao_com_status(status: str) -> dict:
    t = uuid.uuid4().hex[:8]
    with main.app.app_context():
        conn = main.get_db_connection()
        base_id = conn.execute(
            "INSERT INTO atividade_base (nome_conceito, descricao, status)"
            " VALUES (?, 'Base B5s', 'ativo') RETURNING id",
            (f"Base B5s {t}",),
        ).fetchone()["id"]
        versao_id = conn.execute(
            "INSERT INTO atividade_versao"
            " (atividade_base_id, eixo, grupo, numero_versao, status)"
            " VALUES (?, 'AAC', '1 - B5s', 1, ?) RETURNING id",
            (base_id, status),
        ).fetchone()["id"]
        conn.commit()
    return {"base_id": base_id, "versao_id": versao_id}


def _seed_ativa_com_vinculo() -> dict:
    t = uuid.uuid4().hex[:8]
    with main.app.app_context():
        conn = main.get_db_connection()
        curso_id = conn.execute(
            "INSERT INTO cursos (nome, codigo, duracao_periodos, status)"
            " VALUES (?, ?, 8, 'ativo') RETURNING id",
            (f"Curso B5v {t}", f"B5V{t}"),
        ).fetchone()["id"]
        matriz_id = conn.execute(
            "INSERT INTO matrizes_atividades (curso_id, nome, status)"
            " VALUES (?, ?, 'ativa') RETURNING id",
            (curso_id, f"Matriz B5v {t}"),
        ).fetchone()["id"]
        base_id = conn.execute(
            "INSERT INTO atividade_base (nome_conceito, descricao, status)"
            " VALUES (?, 'Base B5v', 'ativo') RETURNING id",
            (f"Base B5v {t}",),
        ).fetchone()["id"]
        versao_id = conn.execute(
            "INSERT INTO atividade_versao"
            " (atividade_base_id, eixo, grupo, numero_versao, status)"
            " VALUES (?, 'AAC', '1 - B5v', 1, 'ativa') RETURNING id",
            (base_id,),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO matriz_atividade_versao_item "
            "(matriz_id, atividade_base_id, atividade_versao_id) VALUES (?, ?, ?)",
            (matriz_id, base_id, versao_id),
        )
        conn.commit()
    return {
        "base_id": base_id,
        "versao_id": versao_id,
        "matriz_id": matriz_id,
    }


def _seed_full_resolver_setup() -> dict:
    t = uuid.uuid4().hex[:8]
    with main.app.app_context():
        conn = main.get_db_connection()
        curso_id = conn.execute(
            "INSERT INTO cursos (nome, codigo, duracao_periodos, status)"
            " VALUES (?, ?, 8, 'ativo') RETURNING id",
            (f"Curso B5r {t}", f"B5R{t}"),
        ).fetchone()["id"]
        matriz_id = conn.execute(
            "INSERT INTO matrizes_atividades (curso_id, nome, status)"
            " VALUES (?, ?, 'ativa') RETURNING id",
            (curso_id, f"Matriz B5r {t}"),
        ).fetchone()["id"]
        base_id = conn.execute(
            "INSERT INTO atividade_base (nome_conceito, descricao, status)"
            " VALUES (?, 'Base B5r', 'ativo') RETURNING id",
            (f"Base B5r {t}",),
        ).fetchone()["id"]
        versao_id = conn.execute(
            "INSERT INTO atividade_versao"
            " (atividade_base_id, eixo, grupo, numero_versao, status)"
            " VALUES (?, 'AAC', '1 - B5r', 1, 'ativa') RETURNING id",
            (base_id,),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO matriz_atividade_versao_item "
            "(matriz_id, atividade_base_id, atividade_versao_id) "
            "SELECT ?, atividade_base_id, id FROM atividade_versao WHERE id = ?",
            (matriz_id, versao_id),
        )
        conn.commit()
    return {
        "base_id": base_id,
        "versao_id": versao_id,
        "matriz_id": matriz_id,
        "atividade_id": versao_id,
    }


def _seed_multi_base_matrix() -> dict:
    t = uuid.uuid4().hex[:8]
    with main.app.app_context():
        conn = main.get_db_connection()
        curso_id = conn.execute(
            "INSERT INTO cursos (nome, codigo, duracao_periodos, status)"
            " VALUES (?, ?, 8, 'ativo') RETURNING id",
            (f"Curso B5m {t}", f"B5M{t}"),
        ).fetchone()["id"]
        matriz_id = conn.execute(
            "INSERT INTO matrizes_atividades (curso_id, nome, status)"
            " VALUES (?, ?, 'ativa') RETURNING id",
            (curso_id, f"Matriz B5m {t}"),
        ).fetchone()["id"]

        base_a_id = conn.execute(
            "INSERT INTO atividade_base (nome_conceito, descricao, status)"
            " VALUES (?, 'Base A', 'ativo') RETURNING id",
            (f"Base B5m A {t}",),
        ).fetchone()["id"]
        versao_a_id = conn.execute(
            "INSERT INTO atividade_versao"
            " (atividade_base_id, eixo, grupo, numero_versao, status)"
            " VALUES (?, 'AAC', '1 - B5mA', 1, 'ativa') RETURNING id",
            (base_a_id,),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO matriz_atividade_versao_item "
            "(matriz_id, atividade_base_id, atividade_versao_id) "
            "SELECT ?, atividade_base_id, id FROM atividade_versao WHERE id = ?",
            (matriz_id, versao_a_id),
        )

        base_b_id = conn.execute(
            "INSERT INTO atividade_base (nome_conceito, descricao, status)"
            " VALUES (?, 'Base B', 'ativo') RETURNING id",
            (f"Base B5m B {t}",),
        ).fetchone()["id"]
        versao_b_id = conn.execute(
            "INSERT INTO atividade_versao"
            " (atividade_base_id, eixo, grupo, numero_versao, status)"
            " VALUES (?, 'AAC', '1 - B5mB', 1, 'ativa') RETURNING id",
            (base_b_id,),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO matriz_atividade_versao_item "
            "(matriz_id, atividade_base_id, atividade_versao_id) "
            "SELECT ?, atividade_base_id, id FROM atividade_versao WHERE id = ?",
            (matriz_id, versao_b_id),
        )
        conn.commit()
    return {
        "matriz_id": matriz_id,
        "base_a_id": base_a_id,
        "versao_a_id": versao_a_id,
        "ativ_a_id": versao_a_id,
        "base_b_id": base_b_id,
        "versao_b_id": versao_b_id,
        "ativ_b_id": versao_b_id,
    }


def _get_versao_status(versao_id: int) -> str:
    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT status FROM atividade_versao WHERE id = ?",
            (versao_id,),
        ).fetchone()
    return str(row["status"]) if row else ""


def _count_matriz_versao_item_for(versao_id: int) -> int:
    with main.app.app_context():
        return main.get_db_connection().execute(
            "SELECT COUNT(*) AS c FROM matriz_atividade_versao_item"
            " WHERE atividade_versao_id = ?",
            (versao_id,),
        ).fetchone()["c"]


_MISSING = object()


def _count_atividade_transicao_total() -> int:
    with main.app.app_context():
        return main.get_db_connection().execute(
            "SELECT COUNT(*) AS c FROM atividade_transicao"
        ).fetchone()["c"]


def _get_transicoes() -> list[dict]:
    with main.app.app_context():
        rows = main.get_db_connection().execute(
            """
            SELECT from_atividade_versao_id, to_atividade_versao_id, tipo_transicao
              FROM atividade_transicao
             ORDER BY id
            """
        ).fetchall()
    return [dict(row) for row in rows]


def _insert_versao(
    conn,
    *,
    base_id: int,
    eixo: str,
    status: str,
    prefixo: str,
) -> int:
    token = uuid.uuid4().hex[:8]
    next_num = conn.execute(
        "SELECT COALESCE(MAX(numero_versao), 0) + 1 FROM atividade_versao WHERE atividade_base_id = ?",
        (base_id,),
    ).fetchone()[0]
    return conn.execute(
        "INSERT INTO atividade_versao"
        " (atividade_base_id, eixo, grupo, status, numero_versao)"
        " VALUES (?, ?, ?, ?, ?) RETURNING id",
        (base_id, eixo, f"{prefixo}{token}", status, next_num),
    ).fetchone()["id"]


def _seed_substituicao_par(
    *,
    origem_status: str = "ativa",
    destino_status: str = "ativa",
    origem_eixo: str = "AAC",
    destino_eixo: str = "AAC",
    destino_mesma_base: bool = True,
) -> dict:
    token = uuid.uuid4().hex[:8]
    with main.app.app_context():
        conn = main.get_db_connection()
        base_id = conn.execute(
            "INSERT INTO atividade_base (nome_conceito, descricao, status)"
            " VALUES (?, 'Base Sub', 'ativo') RETURNING id",
            (f"Base Sub {token}",),
        ).fetchone()["id"]
        destino_base_id = base_id
        if not destino_mesma_base:
            destino_base_id = conn.execute(
                "INSERT INTO atividade_base (nome_conceito, descricao, status)"
                " VALUES (?, 'Base Dest', 'ativo') RETURNING id",
                (f"Base Dest {token}",),
            ).fetchone()["id"]
        origem_id = _insert_versao(
            conn,
            base_id=base_id,
            eixo=origem_eixo,
            status=origem_status,
            prefixo="SUBORIG",
        )
        destino_id = _insert_versao(
            conn,
            base_id=destino_base_id,
            eixo=destino_eixo,
            status=destino_status,
            prefixo="SUBDEST",
        )
        conn.commit()
    return {
        "base_id": base_id,
        "destino_base_id": destino_base_id,
        "origem_id": origem_id,
        "destino_id": destino_id,
    }


def _criar_vinculo_matriz_para_versao(versao_id: int) -> int:
    token = uuid.uuid4().hex[:8]
    with main.app.app_context():
        conn = main.get_db_connection()
        curso_id = conn.execute(
            "INSERT INTO cursos (nome, codigo, duracao_periodos, status)"
            " VALUES (?, ?, 8, 'ativo') RETURNING id",
            (f"Curso Sub {token}", f"SUB{token}"),
        ).fetchone()["id"]
        matriz_id = conn.execute(
            "INSERT INTO matrizes_atividades (curso_id, nome, status)"
            " VALUES (?, ?, 'ativa') RETURNING id",
            (curso_id, f"Matriz Sub {token}"),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO matriz_atividade_versao_item "
            "(matriz_id, atividade_base_id, atividade_versao_id) "
            "SELECT ?, atividade_base_id, id FROM atividade_versao WHERE id = ?",
            (matriz_id, versao_id),
        )
        conn.commit()
    return matriz_id


def _post_substituir(client, base_id: int, versao_id: int, to_versao_id=_MISSING):
    data = {}
    if to_versao_id is not _MISSING:
        data["to_versao_id"] = to_versao_id
    return client.post(
        f"/admin/catalogo-versoes/{base_id}/versoes/{versao_id}/substituir",
        data=data,
        follow_redirects=True,
    )


# ---------------------------------------------------------------------------
# Tests — inativar
# ---------------------------------------------------------------------------


def test_inativar_versao_ativa_muda_status(versioned_env):
    """POST inativar versão ativa sem vínculo → status = 'inativa'."""
    client = versioned_env["client"]
    _login_admin(client)
    seed = _seed_ativa_sem_vinculo()

    resp = client.post(
        f"/admin/catalogo-versoes/{seed['base_id']}/versoes/{seed['versao_id']}/inativar",
        data={},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert _get_versao_status(seed["versao_id"]) == "inativa"


def test_inativar_versao_inexistente_nao_500(versioned_env):
    """POST inativar versão inexistente retorna redirect, não 500."""
    client = versioned_env["client"]
    _login_admin(client)
    seed = _seed_ativa_sem_vinculo()

    resp = client.post(
        f"/admin/catalogo-versoes/{seed['base_id']}/versoes/999999/inativar",
        data={},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)
    assert resp.status_code != 500


def test_inativar_versao_de_outra_base_rejeitado(versioned_env):
    """POST inativar versão de outra base é rejeitado e status não muda."""
    client = versioned_env["client"]
    _login_admin(client)
    seed_a = _seed_ativa_sem_vinculo()
    seed_b = _seed_ativa_sem_vinculo()

    resp = client.post(
        f"/admin/catalogo-versoes/{seed_a['base_id']}/versoes/{seed_b['versao_id']}/inativar",
        data={},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert _get_versao_status(seed_b["versao_id"]) == "ativa"


def test_inativar_versao_ja_inativa_rejeitado(versioned_env):
    """POST inativar versão já inativa é rejeitado (status permanece 'inativa')."""
    client = versioned_env["client"]
    _login_admin(client)
    seed = _seed_versao_com_status("inativa")

    resp = client.post(
        f"/admin/catalogo-versoes/{seed['base_id']}/versoes/{seed['versao_id']}/inativar",
        data={},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert _get_versao_status(seed["versao_id"]) == "inativa"
    assert b"Apenas vers" in resp.data


def test_inativar_versao_rascunho_rejeitado(versioned_env):
    """POST inativar versão rascunho é rejeitado."""
    client = versioned_env["client"]
    _login_admin(client)
    seed = _seed_versao_com_status("rascunho")

    resp = client.post(
        f"/admin/catalogo-versoes/{seed['base_id']}/versoes/{seed['versao_id']}/inativar",
        data={},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert _get_versao_status(seed["versao_id"]) == "rascunho"
    assert b"Apenas vers" in resp.data


def test_inativar_versao_descontinuada_rejeitado(versioned_env):
    """POST inativar versão descontinuada é rejeitado."""
    client = versioned_env["client"]
    _login_admin(client)
    seed = _seed_versao_com_status("descontinuada")

    resp = client.post(
        f"/admin/catalogo-versoes/{seed['base_id']}/versoes/{seed['versao_id']}/inativar",
        data={},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert _get_versao_status(seed["versao_id"]) == "descontinuada"


def test_inativar_versao_substituida_rejeitado(versioned_env):
    """POST inativar versão substituida é rejeitado."""
    client = versioned_env["client"]
    _login_admin(client)
    seed = _seed_versao_com_status("substituida")

    resp = client.post(
        f"/admin/catalogo-versoes/{seed['base_id']}/versoes/{seed['versao_id']}/inativar",
        data={},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert _get_versao_status(seed["versao_id"]) == "substituida"


def test_inativar_versao_com_vinculo_bloqueado(versioned_env):
    """
    POST inativar versão ativa com vínculo em matriz_atividade_versao_item →
    bloqueia: status não muda, vínculo não é removido.
    """
    client = versioned_env["client"]
    _login_admin(client)
    seed = _seed_ativa_com_vinculo()

    assert _count_matriz_versao_item_for(seed["versao_id"]) == 1

    resp = client.post(
        f"/admin/catalogo-versoes/{seed['base_id']}/versoes/{seed['versao_id']}/inativar",
        data={},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert _get_versao_status(seed["versao_id"]) == "ativa"
    assert _count_matriz_versao_item_for(seed["versao_id"]) == 1
    assert "Remova o v" in resp.data.decode("utf-8") or b"matriz" in resp.data


def test_inativar_resolver_retorna_ausencia(versioned_env):
    """
    Após remover vínculo da matriz e inativar, resolver retorna ausência de versão.
    """
    client = versioned_env["client"]
    _login_admin(client)
    seed = _seed_full_resolver_setup()

    with main.app.app_context():
        conn = main.get_db_connection()
        resultado_antes = resolver_service.resolver_versao_por_matriz(
            conn,
            matriz_id=seed["matriz_id"],
            atividade_versao_id=seed["atividade_id"],
        )
    assert resultado_antes["status"] == "resolved"
    assert resultado_antes["atividade_versao_id"] == seed["versao_id"]

    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "DELETE FROM matriz_atividade_versao_item"
            " WHERE matriz_id = ? AND atividade_versao_id = ?",
            (seed["matriz_id"], seed["versao_id"]),
        )
        conn.commit()

    resp = client.post(
        f"/admin/catalogo-versoes/{seed['base_id']}/versoes/{seed['versao_id']}/inativar",
        data={},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert _get_versao_status(seed["versao_id"]) == "inativa"

    with main.app.app_context():
        conn = main.get_db_connection()
        resultado_depois = resolver_service.resolver_versao_por_matriz(
            conn,
            matriz_id=seed["matriz_id"],
            atividade_versao_id=seed["atividade_id"],
        )
    assert resultado_depois["status"] != "resolved"


# ---------------------------------------------------------------------------
# Tests — descontinuar
# ---------------------------------------------------------------------------


def test_descontinuar_versao_ativa_muda_status(versioned_env):
    """POST descontinuar versão ativa sem vínculo → status = 'descontinuada'."""
    client = versioned_env["client"]
    _login_admin(client)
    seed = _seed_ativa_sem_vinculo()

    resp = client.post(
        f"/admin/catalogo-versoes/{seed['base_id']}/versoes/{seed['versao_id']}/descontinuar",
        data={},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert _get_versao_status(seed["versao_id"]) == "descontinuada"


def test_descontinuar_versao_com_vinculo_bloqueado(versioned_env):
    """POST descontinuar versão ativa com vínculo → bloqueia, status não muda."""
    client = versioned_env["client"]
    _login_admin(client)
    seed = _seed_ativa_com_vinculo()

    resp = client.post(
        f"/admin/catalogo-versoes/{seed['base_id']}/versoes/{seed['versao_id']}/descontinuar",
        data={},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert _get_versao_status(seed["versao_id"]) == "ativa"
    assert _count_matriz_versao_item_for(seed["versao_id"]) == 1


def test_descontinuar_versao_rascunho_rejeitado(versioned_env):
    """POST descontinuar versão rascunho é rejeitado."""
    client = versioned_env["client"]
    _login_admin(client)
    seed = _seed_versao_com_status("rascunho")

    resp = client.post(
        f"/admin/catalogo-versoes/{seed['base_id']}/versoes/{seed['versao_id']}/descontinuar",
        data={},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert _get_versao_status(seed["versao_id"]) == "rascunho"


def test_descontinuar_versao_ja_descontinuada_rejeitado(versioned_env):
    """POST descontinuar versão já descontinuada é rejeitado."""
    client = versioned_env["client"]
    _login_admin(client)
    seed = _seed_versao_com_status("descontinuada")

    resp = client.post(
        f"/admin/catalogo-versoes/{seed['base_id']}/versoes/{seed['versao_id']}/descontinuar",
        data={},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert _get_versao_status(seed["versao_id"]) == "descontinuada"
    assert b"Apenas vers" in resp.data


def test_descontinuar_versao_inativa_rejeitado(versioned_env):
    """POST descontinuar versão inativa é rejeitado."""
    client = versioned_env["client"]
    _login_admin(client)
    seed = _seed_versao_com_status("inativa")

    resp = client.post(
        f"/admin/catalogo-versoes/{seed['base_id']}/versoes/{seed['versao_id']}/descontinuar",
        data={},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert _get_versao_status(seed["versao_id"]) == "inativa"


# ---------------------------------------------------------------------------
# Tests — template (renderização condicional)
# ---------------------------------------------------------------------------


def test_detalhe_mostra_inativar_descontinuar_para_ativa(versioned_env):
    """Detalhe da base renderiza botões Inativar e Descontinuar para versão ativa."""
    client = versioned_env["client"]
    _login_admin(client)
    seed = _seed_ativa_sem_vinculo()

    resp = client.get(
        f"/admin/catalogo-versoes/{seed['base_id']}",
        follow_redirects=False,
    )
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")
    assert 'class="vc-lifecycle-form vc-inativar-form"' in html
    assert 'class="vc-lifecycle-form vc-descontinuar-form"' in html


def test_detalhe_nao_mostra_inativar_para_rascunho_mostra_ativar(versioned_env):
    """Detalhe da base mostra 'Ativar' para rascunho, não Inativar/Descontinuar."""
    client = versioned_env["client"]
    _login_admin(client)
    seed = _seed_versao_com_status("rascunho")

    resp = client.get(
        f"/admin/catalogo-versoes/{seed['base_id']}",
        follow_redirects=False,
    )
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")
    assert 'class="vc-activate-form"' in html
    assert 'class="vc-lifecycle-form vc-inativar-form"' not in html
    assert 'class="vc-lifecycle-form vc-descontinuar-form"' not in html


def test_detalhe_nao_mostra_inativar_para_outros_status(versioned_env):
    """Detalhe não exibe Inativar/Descontinuar para status inativa, descontinuada, substituida."""
    client = versioned_env["client"]
    _login_admin(client)

    for status in ("inativa", "descontinuada", "substituida"):
        seed = _seed_versao_com_status(status)
        resp = client.get(
            f"/admin/catalogo-versoes/{seed['base_id']}",
            follow_redirects=False,
        )
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        assert 'class="vc-lifecycle-form vc-inativar-form"' not in html, f"status={status}: form de inativação não deve aparecer"
        assert 'class="vc-lifecycle-form vc-descontinuar-form"' not in html, f"status={status}: form de descontinuação não deve aparecer"


# ---------------------------------------------------------------------------
# Test — CSRF
# ---------------------------------------------------------------------------


def test_csrf_token_presente_nos_forms_lifecycle(versioned_env):
    """Forms de Inativar e Descontinuar contêm csrf_token oculto."""
    client = versioned_env["client"]
    _login_admin(client)
    seed = _seed_ativa_sem_vinculo()

    resp = client.get(
        f"/admin/catalogo-versoes/{seed['base_id']}",
        follow_redirects=False,
    )
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")

    lifecycle_forms = re.findall(
        r'<form[^>]*vc-lifecycle-form[^>]*>.*?</form>',
        html,
        re.DOTALL,
    )
    assert len(lifecycle_forms) >= 2
    for form_html in lifecycle_forms:
        assert 'name="csrf_token"' in form_html, "csrf_token ausente em form lifecycle"


# ---------------------------------------------------------------------------
# Test — isolamento entre bases no resolver
# ---------------------------------------------------------------------------


def test_inativar_versao_a_nao_quebra_resolver_versao_b(versioned_env):
    """
    Após inativar versão A (base A), o resolver ainda resolve versão B (base B)
    para a mesma matriz.
    """
    client = versioned_env["client"]
    _login_admin(client)
    seed = _seed_multi_base_matrix()

    with main.app.app_context():
        conn = main.get_db_connection()
        resultado_b_antes = resolver_service.resolver_versao_por_matriz(
            conn,
            matriz_id=seed["matriz_id"],
            atividade_versao_id=seed["ativ_b_id"],
        )
    assert resultado_b_antes["status"] == "resolved"
    assert resultado_b_antes["atividade_versao_id"] == seed["versao_b_id"]

    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "DELETE FROM matriz_atividade_versao_item"
            " WHERE matriz_id = ? AND atividade_versao_id = ?",
            (seed["matriz_id"], seed["versao_a_id"]),
        )
        conn.commit()

    resp = client.post(
        f"/admin/catalogo-versoes/{seed['base_a_id']}/versoes/{seed['versao_a_id']}/inativar",
        data={},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert _get_versao_status(seed["versao_a_id"]) == "inativa"

    with main.app.app_context():
        conn = main.get_db_connection()
        resultado_b_depois = resolver_service.resolver_versao_por_matriz(
            conn,
            matriz_id=seed["matriz_id"],
            atividade_versao_id=seed["ativ_b_id"],
        )
    assert resultado_b_depois["status"] == "resolved"
    assert resultado_b_depois["atividade_versao_id"] == seed["versao_b_id"]


# ---------------------------------------------------------------------------
# Tests — substituir
# ---------------------------------------------------------------------------


def test_substituir_versao_ativa_muda_status_e_cria_transicao(versioned_env):
    client = versioned_env["client"]
    _login_admin(client)
    seed = _seed_substituicao_par()

    resp = _post_substituir(
        client, seed["base_id"], seed["origem_id"], str(seed["destino_id"])
    )

    assert resp.status_code == 200
    assert _get_versao_status(seed["origem_id"]) == "substituida"
    assert _get_versao_status(seed["destino_id"]) == "ativa"
    transicoes = _get_transicoes()
    assert len(transicoes) == 1
    assert transicoes[0]["from_atividade_versao_id"] == seed["origem_id"]
    assert transicoes[0]["to_atividade_versao_id"] == seed["destino_id"]
    assert transicoes[0]["tipo_transicao"] == "mesmo_eixo"


def test_substituir_sem_to_versao_id_rejeita(versioned_env):
    client = versioned_env["client"]
    _login_admin(client)
    seed = _seed_substituicao_par()

    resp = _post_substituir(client, seed["base_id"], seed["origem_id"])

    assert resp.status_code == 200
    assert _get_versao_status(seed["origem_id"]) == "ativa"
    assert _count_atividade_transicao_total() == 0
    assert b"destino" in resp.data


def test_substituir_to_versao_id_nao_numerico_rejeita(versioned_env):
    client = versioned_env["client"]
    _login_admin(client)
    seed = _seed_substituicao_par()

    resp = _post_substituir(client, seed["base_id"], seed["origem_id"], "abc")

    assert resp.status_code == 200
    assert _get_versao_status(seed["origem_id"]) == "ativa"
    assert _count_atividade_transicao_total() == 0


def test_substituir_destino_inexistente_rejeita(versioned_env):
    client = versioned_env["client"]
    _login_admin(client)
    seed = _seed_substituicao_par()

    resp = _post_substituir(client, seed["base_id"], seed["origem_id"], "999999")

    assert resp.status_code == 200
    assert _get_versao_status(seed["origem_id"]) == "ativa"
    assert _count_atividade_transicao_total() == 0


def test_substituir_destino_nao_ativa_rejeita(versioned_env):
    client = versioned_env["client"]
    _login_admin(client)
    seed = _seed_substituicao_par(destino_status="inativa")

    resp = _post_substituir(
        client, seed["base_id"], seed["origem_id"], str(seed["destino_id"])
    )

    assert resp.status_code == 200
    assert _get_versao_status(seed["origem_id"]) == "ativa"
    assert _count_atividade_transicao_total() == 0


def test_substituir_destino_de_outra_base_rejeita(versioned_env):
    client = versioned_env["client"]
    _login_admin(client)
    seed = _seed_substituicao_par(destino_mesma_base=False)

    resp = _post_substituir(
        client, seed["base_id"], seed["origem_id"], str(seed["destino_id"])
    )

    assert resp.status_code == 200
    assert _get_versao_status(seed["origem_id"]) == "ativa"
    assert _count_atividade_transicao_total() == 0


def test_substituir_destino_de_outro_eixo_rejeita(versioned_env):
    client = versioned_env["client"]
    _login_admin(client)
    seed = _seed_substituicao_par(destino_eixo="AEU")

    resp = _post_substituir(
        client, seed["base_id"], seed["origem_id"], str(seed["destino_id"])
    )

    assert resp.status_code == 200
    assert _get_versao_status(seed["origem_id"]) == "ativa"
    assert _count_atividade_transicao_total() == 0


def test_substituir_auto_substituicao_rejeita(versioned_env):
    client = versioned_env["client"]
    _login_admin(client)
    seed = _seed_substituicao_par()

    resp = _post_substituir(
        client, seed["base_id"], seed["origem_id"], str(seed["origem_id"])
    )

    assert resp.status_code == 200
    assert _get_versao_status(seed["origem_id"]) == "ativa"
    assert _count_atividade_transicao_total() == 0


def test_substituir_origem_com_vinculo_em_matriz_rejeita(versioned_env):
    client = versioned_env["client"]
    _login_admin(client)
    seed = _seed_substituicao_par()
    _criar_vinculo_matriz_para_versao(seed["origem_id"])

    resp = _post_substituir(
        client, seed["base_id"], seed["origem_id"], str(seed["destino_id"])
    )

    assert resp.status_code == 200
    assert _get_versao_status(seed["origem_id"]) == "ativa"
    assert _count_atividade_transicao_total() == 0


def test_substituir_origem_ja_com_transicao_rejeita(versioned_env):
    client = versioned_env["client"]
    _login_admin(client)
    seed = _seed_substituicao_par()

    with main.app.app_context():
        conn = main.get_db_connection()
        terceiro_id = _insert_versao(
            conn,
            base_id=seed["base_id"],
            eixo="AAC",
            status="ativa",
            prefixo="SUBEXTRA",
        )
        conn.execute(
            """
            INSERT INTO atividade_transicao
                (from_atividade_versao_id, to_atividade_versao_id, tipo_transicao)
            VALUES (?, ?, 'mesmo_eixo')
            """,
            (seed["origem_id"], terceiro_id),
        )
        conn.commit()

    resp = _post_substituir(
        client, seed["base_id"], seed["origem_id"], str(seed["destino_id"])
    )

    assert resp.status_code == 200
    assert _get_versao_status(seed["origem_id"]) == "ativa"
    assert _count_atividade_transicao_total() == 1


def test_substituir_destino_ja_como_from_rejeita(versioned_env):
    client = versioned_env["client"]
    _login_admin(client)
    seed = _seed_substituicao_par()

    with main.app.app_context():
        conn = main.get_db_connection()
        terceiro_id = _insert_versao(
            conn,
            base_id=seed["base_id"],
            eixo="AAC",
            status="ativa",
            prefixo="SUBDESTX",
        )
        conn.execute(
            """
            INSERT INTO atividade_transicao
                (from_atividade_versao_id, to_atividade_versao_id, tipo_transicao)
            VALUES (?, ?, 'mesmo_eixo')
            """,
            (seed["destino_id"], terceiro_id),
        )
        conn.commit()

    resp = _post_substituir(
        client, seed["base_id"], seed["origem_id"], str(seed["destino_id"])
    )

    assert resp.status_code == 200
    assert _get_versao_status(seed["origem_id"]) == "ativa"
    assert _count_atividade_transicao_total() == 1


def test_detalhe_mostra_substituir_apenas_para_ativa(versioned_env):
    client = versioned_env["client"]
    _login_admin(client)
    seed_ativa = _seed_substituicao_par()

    resp_ativa = client.get(
        f"/admin/catalogo-versoes/{seed_ativa['base_id']}",
        follow_redirects=False,
    )
    assert resp_ativa.status_code == 200
    html_ativa = resp_ativa.data.decode("utf-8")
    assert 'class="vc-substituir-form"' in html_ativa
    assert '<select hidden data-substitution-options=' in html_ativa
    assert 'name="to_versao_id"' in html_ativa

    for status in ("rascunho", "inativa", "descontinuada", "substituida"):
        seed = _seed_versao_com_status(status)
        resp = client.get(
            f"/admin/catalogo-versoes/{seed['base_id']}",
            follow_redirects=False,
        )
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        assert 'class="vc-substituir-form"' not in html
        assert '<select hidden data-substitution-options=' not in html


def test_csrf_token_presente_no_form_substituir(versioned_env):
    client = versioned_env["client"]
    _login_admin(client)
    seed = _seed_substituicao_par()

    resp = client.get(
        f"/admin/catalogo-versoes/{seed['base_id']}",
        follow_redirects=False,
    )
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")

    form_match = re.search(
        r'<form[^>]*class="vc-substituir-form"[^>]*>.*?</form>',
        html,
        re.DOTALL,
    )
    assert form_match is not None
    assert 'name="csrf_token"' in form_match.group(0)


def test_inativar_nao_cria_atividade_transicao(versioned_env):
    client = versioned_env["client"]
    _login_admin(client)
    seed = _seed_ativa_sem_vinculo()

    before = _count_atividade_transicao_total()
    resp = client.post(
        f"/admin/catalogo-versoes/{seed['base_id']}/versoes/{seed['versao_id']}/inativar",
        data={},
        follow_redirects=True,
    )

    assert resp.status_code == 200
    assert _count_atividade_transicao_total() == before


def test_descontinuar_nao_cria_atividade_transicao(versioned_env):
    client = versioned_env["client"]
    _login_admin(client)
    seed = _seed_ativa_sem_vinculo()

    before = _count_atividade_transicao_total()
    resp = client.post(
        f"/admin/catalogo-versoes/{seed['base_id']}/versoes/{seed['versao_id']}/descontinuar",
        data={},
        follow_redirects=True,
    )

    assert resp.status_code == 200
    assert _count_atividade_transicao_total() == before
