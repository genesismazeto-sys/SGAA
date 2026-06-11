"""
D7.2B5-PATCH1 — Testes de inativação e descontinuação de atividade_versao ativa.

Cobre:
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
      para a mesma matriz (regressão D7.2B4).
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
    with isolated_versioned_app_env(tmp_path, "d72b5_lifecycle.db") as env:
        yield env


def _login_admin(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 999999
        sess["user_type"] = "admin"
        sess["user_name"] = "Admin Lifecycle Test"


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _seed_ativa_sem_vinculo() -> dict:
    """
    Insere: 1 atividade_base, 1 norma ativa (AAC), 1 atividade_versao ativa.
    Nenhum vínculo em matriz_atividade_versao_item.
    Retorna dict com base_id, norma_id, versao_id.
    """
    t = uuid.uuid4().hex[:8]
    with main.app.app_context():
        conn = main.get_db_connection()
        base_id = conn.execute(
            "INSERT INTO atividade_base (nome_conceito, descricao, status)"
            " VALUES (?, 'Base B5', 'ativo') RETURNING id",
            (f"Base B5 {t}",),
        ).fetchone()["id"]
        norma_id = conn.execute(
            "INSERT INTO norma_atividade (codigo, eixo, revisao, nome, status)"
            " VALUES (?, 'AAC', 'rev1', ?, 'ativa') RETURNING id",
            (f"B5NRM{t}", f"Norma B5 {t}"),
        ).fetchone()["id"]
        versao_id = conn.execute(
            "INSERT INTO atividade_versao"
            " (atividade_base_id, norma_id, codigo_normativo, eixo, grupo, status)"
            " VALUES (?, ?, ?, 'AAC', '1 - B5', 'ativa') RETURNING id",
            (base_id, norma_id, f"B5NRM{t}"),
        ).fetchone()["id"]
        conn.commit()
    return {"base_id": base_id, "norma_id": norma_id, "versao_id": versao_id}


def _seed_versao_com_status(status: str) -> dict:
    """
    Insere uma atividade_versao no status especificado (rascunho, inativa,
    descontinuada, substituida). Sem vínculo em matriz_atividade_versao_item.
    """
    t = uuid.uuid4().hex[:8]
    with main.app.app_context():
        conn = main.get_db_connection()
        base_id = conn.execute(
            "INSERT INTO atividade_base (nome_conceito, descricao, status)"
            " VALUES (?, 'Base B5s', 'ativo') RETURNING id",
            (f"Base B5s {t}",),
        ).fetchone()["id"]
        norma_id = conn.execute(
            "INSERT INTO norma_atividade (codigo, eixo, revisao, nome, status)"
            " VALUES (?, 'AAC', 'rev1', ?, 'ativa') RETURNING id",
            (f"B5SN{t}", f"Norma B5s {t}"),
        ).fetchone()["id"]
        versao_id = conn.execute(
            "INSERT INTO atividade_versao"
            " (atividade_base_id, norma_id, codigo_normativo, eixo, grupo, status)"
            " VALUES (?, ?, ?, 'AAC', '1 - B5s', ?) RETURNING id",
            (base_id, norma_id, f"B5SN{t}", status),
        ).fetchone()["id"]
        conn.commit()
    return {"base_id": base_id, "norma_id": norma_id, "versao_id": versao_id}


def _seed_ativa_com_vinculo() -> dict:
    """
    Insere: 1 curso, 1 matriz, 1 norma ativa, 1 base, 1 versão ativa,
    e um vínculo em matriz_atividade_versao_item.
    Retorna dict com base_id, norma_id, versao_id, matriz_id.
    """
    t = uuid.uuid4().hex[:8]
    with main.app.app_context():
        conn = main.get_db_connection()
        curso_id = conn.execute(
            "INSERT INTO cursos (nome, codigo, duracao_periodos, status)"
            " VALUES (?, ?, 8, 'ativo') RETURNING id",
            (f"Curso B5v {t}", f"B5V{t}"),
        ).fetchone()["id"]
        matriz_id = conn.execute(
            "INSERT INTO matrizes_atividades (curso_id, nome, versao, status)"
            " VALUES (?, ?, '2026.1', 'ativa') RETURNING id",
            (curso_id, f"Matriz B5v {t}"),
        ).fetchone()["id"]
        base_id = conn.execute(
            "INSERT INTO atividade_base (nome_conceito, descricao, status)"
            " VALUES (?, 'Base B5v', 'ativo') RETURNING id",
            (f"Base B5v {t}",),
        ).fetchone()["id"]
        norma_id = conn.execute(
            "INSERT INTO norma_atividade (codigo, eixo, revisao, nome, status)"
            " VALUES (?, 'AAC', 'rev1', ?, 'ativa') RETURNING id",
            (f"B5VN{t}", f"Norma B5v {t}"),
        ).fetchone()["id"]
        versao_id = conn.execute(
            "INSERT INTO atividade_versao"
            " (atividade_base_id, norma_id, codigo_normativo, eixo, grupo, status)"
            " VALUES (?, ?, ?, 'AAC', '1 - B5v', 'ativa') RETURNING id",
            (base_id, norma_id, f"B5VN{t}"),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO matriz_atividade_versao_item (matriz_id, atividade_versao_id)"
            " VALUES (?, ?)",
            (matriz_id, versao_id),
        )
        conn.commit()
    return {
        "base_id": base_id,
        "norma_id": norma_id,
        "versao_id": versao_id,
        "matriz_id": matriz_id,
    }


def _seed_full_resolver_setup() -> dict:
    """
    Insere setup completo para o resolver: curso, matriz, norma, base, atividade,
    atividade_versao ativa, atividade_legacy_map, matrizes_atividades_itens,
    matriz_norma e matriz_atividade_versao_item.
    Retorna todos os ids necessários para chamar resolver_versao_por_matriz.
    """
    t = uuid.uuid4().hex[:8]
    with main.app.app_context():
        conn = main.get_db_connection()
        curso_id = conn.execute(
            "INSERT INTO cursos (nome, codigo, duracao_periodos, status)"
            " VALUES (?, ?, 8, 'ativo') RETURNING id",
            (f"Curso B5r {t}", f"B5R{t}"),
        ).fetchone()["id"]
        matriz_id = conn.execute(
            "INSERT INTO matrizes_atividades (curso_id, nome, versao, status)"
            " VALUES (?, ?, '2026.1', 'ativa') RETURNING id",
            (curso_id, f"Matriz B5r {t}"),
        ).fetchone()["id"]
        norma_id = conn.execute(
            "INSERT INTO norma_atividade (codigo, eixo, revisao, nome, status)"
            " VALUES (?, 'AAC', 'rev1', ?, 'ativa') RETURNING id",
            (f"B5RN{t}", f"Norma B5r {t}"),
        ).fetchone()["id"]
        base_id = conn.execute(
            "INSERT INTO atividade_base (nome_conceito, descricao, status)"
            " VALUES (?, 'Base B5r', 'ativo') RETURNING id",
            (f"Base B5r {t}",),
        ).fetchone()["id"]
        atividade_id = conn.execute(
            "INSERT INTO atividades"
            " (grupo, nome, descricao, limite_horas, tipo_atividade, tem_limitacao)"
            " VALUES ('1 - B5r', ?, 'B5r', 40, 'Acadêmica Complementar', 0) RETURNING id",
            (f"Atividade B5r {t}",),
        ).fetchone()["id"]
        versao_id = conn.execute(
            "INSERT INTO atividade_versao"
            " (atividade_base_id, norma_id, codigo_normativo, eixo, grupo, status)"
            " VALUES (?, ?, ?, 'AAC', '1 - B5r', 'ativa') RETURNING id",
            (base_id, norma_id, f"B5RN{t}"),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO atividade_legacy_map"
            " (atividade_id_legacy, atividade_base_id, status)"
            " VALUES (?, ?, 'mapeada')",
            (atividade_id, base_id),
        )
        conn.execute(
            "INSERT INTO matrizes_atividades_itens (matriz_id, atividade_id)"
            " VALUES (?, ?)",
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
        "base_id": base_id,
        "norma_id": norma_id,
        "versao_id": versao_id,
        "matriz_id": matriz_id,
        "atividade_id": atividade_id,
    }


def _seed_multi_base_matrix() -> dict:
    """
    Insere: 1 matriz, 2 bases (A e B) cada com 1 versão ativa e vínculo explícito.
    Usado para regressão: inativar versão A não deve quebrar resolver para versão B.
    """
    t = uuid.uuid4().hex[:8]
    with main.app.app_context():
        conn = main.get_db_connection()
        curso_id = conn.execute(
            "INSERT INTO cursos (nome, codigo, duracao_periodos, status)"
            " VALUES (?, ?, 8, 'ativo') RETURNING id",
            (f"Curso B5m {t}", f"B5M{t}"),
        ).fetchone()["id"]
        matriz_id = conn.execute(
            "INSERT INTO matrizes_atividades (curso_id, nome, versao, status)"
            " VALUES (?, ?, '2026.1', 'ativa') RETURNING id",
            (curso_id, f"Matriz B5m {t}"),
        ).fetchone()["id"]
        norma_id = conn.execute(
            "INSERT INTO norma_atividade (codigo, eixo, revisao, nome, status)"
            " VALUES (?, 'AAC', 'rev1', ?, 'ativa') RETURNING id",
            (f"B5MN{t}", f"Norma B5m {t}"),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO matriz_norma (matriz_id, norma_id) VALUES (?, ?)",
            (matriz_id, norma_id),
        )

        # Base A
        base_a_id = conn.execute(
            "INSERT INTO atividade_base (nome_conceito, descricao, status)"
            " VALUES (?, 'Base A', 'ativo') RETURNING id",
            (f"Base B5m A {t}",),
        ).fetchone()["id"]
        ativ_a_id = conn.execute(
            "INSERT INTO atividades"
            " (grupo, nome, descricao, limite_horas, tipo_atividade, tem_limitacao)"
            " VALUES ('1 - B5mA', ?, 'A', 40, 'Acadêmica Complementar', 0) RETURNING id",
            (f"Atividade B5m A {t}",),
        ).fetchone()["id"]
        versao_a_id = conn.execute(
            "INSERT INTO atividade_versao"
            " (atividade_base_id, norma_id, codigo_normativo, eixo, grupo, status)"
            " VALUES (?, ?, ?, 'AAC', '1 - B5mA', 'ativa') RETURNING id",
            (base_a_id, norma_id, f"B5MNA{t}"),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO atividade_legacy_map"
            " (atividade_id_legacy, atividade_base_id, status)"
            " VALUES (?, ?, 'mapeada')",
            (ativ_a_id, base_a_id),
        )
        conn.execute(
            "INSERT INTO matrizes_atividades_itens (matriz_id, atividade_id)"
            " VALUES (?, ?)",
            (matriz_id, ativ_a_id),
        )
        conn.execute(
            "INSERT INTO matriz_atividade_versao_item (matriz_id, atividade_versao_id)"
            " VALUES (?, ?)",
            (matriz_id, versao_a_id),
        )

        # Base B
        base_b_id = conn.execute(
            "INSERT INTO atividade_base (nome_conceito, descricao, status)"
            " VALUES (?, 'Base B', 'ativo') RETURNING id",
            (f"Base B5m B {t}",),
        ).fetchone()["id"]
        ativ_b_id = conn.execute(
            "INSERT INTO atividades"
            " (grupo, nome, descricao, limite_horas, tipo_atividade, tem_limitacao)"
            " VALUES ('1 - B5mB', ?, 'B', 40, 'Acadêmica Complementar', 0) RETURNING id",
            (f"Atividade B5m B {t}",),
        ).fetchone()["id"]
        versao_b_id = conn.execute(
            "INSERT INTO atividade_versao"
            " (atividade_base_id, norma_id, codigo_normativo, eixo, grupo, status)"
            " VALUES (?, ?, ?, 'AAC', '1 - B5mB', 'ativa') RETURNING id",
            (base_b_id, norma_id, f"B5MNB{t}"),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO atividade_legacy_map"
            " (atividade_id_legacy, atividade_base_id, status)"
            " VALUES (?, ?, 'mapeada')",
            (ativ_b_id, base_b_id),
        )
        conn.execute(
            "INSERT INTO matrizes_atividades_itens (matriz_id, atividade_id)"
            " VALUES (?, ?)",
            (matriz_id, ativ_b_id),
        )
        conn.execute(
            "INSERT INTO matriz_atividade_versao_item (matriz_id, atividade_versao_id)"
            " VALUES (?, ?)",
            (matriz_id, versao_b_id),
        )
        conn.commit()
    return {
        "matriz_id": matriz_id,
        "norma_id": norma_id,
        "base_a_id": base_a_id,
        "versao_a_id": versao_a_id,
        "ativ_a_id": ativ_a_id,
        "base_b_id": base_b_id,
        "versao_b_id": versao_b_id,
        "ativ_b_id": ativ_b_id,
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


def _insert_norma_e_versao(
    conn,
    *,
    base_id: int,
    eixo: str,
    status: str,
    prefixo: str,
) -> tuple[int, int]:
    token = uuid.uuid4().hex[:8]
    codigo = f"{prefixo}{token}"
    norma_id = conn.execute(
        "INSERT INTO norma_atividade (codigo, eixo, revisao, nome, status)"
        " VALUES (?, ?, 'rev1', ?, 'ativa') RETURNING id",
        (codigo, eixo, f"Norma {codigo}"),
    ).fetchone()["id"]
    versao_id = conn.execute(
        "INSERT INTO atividade_versao"
        " (atividade_base_id, norma_id, codigo_normativo, eixo, grupo, status)"
        " VALUES (?, ?, ?, ?, '1 - SUB', ?) RETURNING id",
        (base_id, norma_id, codigo, eixo, status),
    ).fetchone()["id"]
    return norma_id, versao_id


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
        _, origem_id = _insert_norma_e_versao(
            conn,
            base_id=base_id,
            eixo=origem_eixo,
            status=origem_status,
            prefixo="SUBORIG",
        )
        _, destino_id = _insert_norma_e_versao(
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
            "INSERT INTO matrizes_atividades (curso_id, nome, versao, status)"
            " VALUES (?, ?, '2026.1', 'ativa') RETURNING id",
            (curso_id, f"Matriz Sub {token}"),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO matriz_atividade_versao_item (matriz_id, atividade_versao_id)"
            " VALUES (?, ?)",
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

    # Tenta inativar seed_b.versao_id usando base_id de seed_a
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

    # Verifica que resolver inicialmente resolve (antes da remoção de vínculo)
    with main.app.app_context():
        conn = main.get_db_connection()
        resultado_antes = main.resolver_versao_por_matriz(
            conn,
            matriz_id=seed["matriz_id"],
            atividade_id_legacy=seed["atividade_id"],
        )
    assert resultado_antes["status"] == "resolved"
    assert resultado_antes["atividade_versao_id"] == seed["versao_id"]

    # Remove o vínculo diretamente (pré-requisito para inativar)
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "DELETE FROM matriz_atividade_versao_item"
            " WHERE matriz_id = ? AND atividade_versao_id = ?",
            (seed["matriz_id"], seed["versao_id"]),
        )
        conn.commit()

    # Inativa a versão
    resp = client.post(
        f"/admin/catalogo-versoes/{seed['base_id']}/versoes/{seed['versao_id']}/inativar",
        data={},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert _get_versao_status(seed["versao_id"]) == "inativa"

    # Resolver retorna ausência de versão para essa base
    with main.app.app_context():
        conn = main.get_db_connection()
        resultado_depois = main.resolver_versao_por_matriz(
            conn,
            matriz_id=seed["matriz_id"],
            atividade_id_legacy=seed["atividade_id"],
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
    # Verifica presença dos botões (atributo class no elemento, não apenas a regra CSS)
    assert 'class="vc-inativar-btn"' in html
    assert 'class="vc-descontinuar-btn"' in html


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
    # Rascunho deve mostrar Ativar, não Inativar/Descontinuar
    assert 'class="vc-activate-btn"' in html
    assert 'class="vc-inativar-btn"' not in html
    assert 'class="vc-descontinuar-btn"' not in html


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
        assert 'class="vc-inativar-btn"' not in html, f"status={status}: vc-inativar-btn não deve aparecer"
        assert 'class="vc-descontinuar-btn"' not in html, f"status={status}: vc-descontinuar-btn não deve aparecer"


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

    # Garante que os forms renderizados têm csrf_token
    import re
    inativar_form_block = re.search(
        r'<form[^>]*vc-lifecycle-form[^>]*>.*?</form>',
        html,
        re.DOTALL,
    )
    assert inativar_form_block is not None, "form vc-lifecycle-form não encontrado"
    # Ao menos um form de lifecycle deve ter csrf_token
    lifecycle_forms = re.findall(
        r'<form[^>]*vc-lifecycle-form[^>]*>.*?</form>',
        html,
        re.DOTALL,
    )
    assert len(lifecycle_forms) >= 2
    for form_html in lifecycle_forms:
        assert 'name="csrf_token"' in form_html, "csrf_token ausente em form lifecycle"


# ---------------------------------------------------------------------------
# Test — regressão D7.2B4
# ---------------------------------------------------------------------------


def test_inativar_versao_a_nao_quebra_resolver_versao_b(versioned_env):
    """
    Após inativar versão A (base A), o resolver ainda resolve versão B (base B)
    para a mesma matriz — regressão D7.2B4.
    """
    client = versioned_env["client"]
    _login_admin(client)
    seed = _seed_multi_base_matrix()

    # Verifica que versão B resolve antes
    with main.app.app_context():
        conn = main.get_db_connection()
        resultado_b_antes = main.resolver_versao_por_matriz(
            conn,
            matriz_id=seed["matriz_id"],
            atividade_id_legacy=seed["ativ_b_id"],
        )
    assert resultado_b_antes["status"] == "resolved"
    assert resultado_b_antes["atividade_versao_id"] == seed["versao_b_id"]

    # Remove vínculo da versão A (pré-requisito para inativar)
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "DELETE FROM matriz_atividade_versao_item"
            " WHERE matriz_id = ? AND atividade_versao_id = ?",
            (seed["matriz_id"], seed["versao_a_id"]),
        )
        conn.commit()

    # Inativa versão A
    resp = client.post(
        f"/admin/catalogo-versoes/{seed['base_a_id']}/versoes/{seed['versao_a_id']}/inativar",
        data={},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert _get_versao_status(seed["versao_a_id"]) == "inativa"

    # Verifica que versão B ainda resolve
    with main.app.app_context():
        conn = main.get_db_connection()
        resultado_b_depois = main.resolver_versao_por_matriz(
            conn,
            matriz_id=seed["matriz_id"],
            atividade_id_legacy=seed["ativ_b_id"],
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
        _, terceiro_id = _insert_norma_e_versao(
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
        _, terceiro_id = _insert_norma_e_versao(
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
    assert 'class="vc-substituir-btn"' in html_ativa
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
        assert 'class="vc-substituir-btn"' not in html


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

    import re

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
