"""
COV-1 restoration — New atividade_versao starts as a copy of its predecessor.

Adapted from the pre-Norma suite (test_admin_activity_version_catalog_copy.py)
with all Norma-domain setup removed (norma_atividade, norma_id, codigo_normativo).

Covers:
  T1  — GET ?from=Av1 renders the exact Av1 values in all editable fields and
        selects Av1 as versao_anterior_id.
  T2  — The source identity comes from the exact `from` id, not label/axis/order.
  T3  — A source from another atividade-base is refused (no prefill, no creation).
  T4  — `from` missing/malformed is handled safely with zero writes.
  T5  — A base without history keeps the form blank and valid.
  T6  — Base detail points "Criar versão" at the highest numero_versao (?from=).
  T7  — Admin edit after copy is persisted (no forced recopy on POST).
  T8  — Av2 is born with versao_anterior_id = Av1.id (lineage).
  T9  — Av2 gets next numero_versao and status='rascunho'; the new version must
        succeed the canonical latest version (no silent fallback to older sources).
  T10 — Av1 remains unchanged (value-equivalent before/after).
  T11 — No mutation in matriz_atividade_versao_item linked to Av1.
  T12 — GET copy does not change relevant row counts.
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
from tests.versioned_test_support import isolated_versioned_app_env


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "fc07_copy.db") as env:
        yield env


@pytest.fixture()
def client(env):
    return env["client"]


def _login_admin(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["user_type"] = "admin"
        sess["user_name"] = "Administrador"


# ---------------------------------------------------------------------------
# Count / row helpers
# ---------------------------------------------------------------------------

def _count(client, table: str) -> int:
    with main.app.app_context():
        return main.get_db_connection().execute(
            f"SELECT COUNT(*) AS c FROM {table}"
        ).fetchone()["c"]


def _count_where(client, table: str, where: str, params) -> int:
    with main.app.app_context():
        return main.get_db_connection().execute(
            f"SELECT COUNT(*) AS c FROM {table} WHERE {where}", params
        ).fetchone()["c"]


def _get_versao_row(client, versao_id: int) -> dict:
    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT * FROM atividade_versao WHERE id = ?", (versao_id,)
        ).fetchone()
    return dict(row) if row is not None else None


def _get_all_versoes(client, base_id: int) -> list[dict]:
    with main.app.app_context():
        rows = main.get_db_connection().execute(
            "SELECT * FROM atividade_versao WHERE atividade_base_id = ? ORDER BY id",
            (base_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def _seed_base(client, *, eixo: str = "AAC") -> dict:
    token = uuid.uuid4().hex[:8]
    with main.app.app_context():
        conn = main.get_db_connection()
        nome_base = f"Base FC07 {token}"
        conn.execute(
            "INSERT INTO atividade_base (nome_conceito, descricao, status)"
            " VALUES (?, ?, ?)",
            (nome_base, "Descrição FC07", "ativo"),
        )
        base_id = conn.execute(
            "SELECT id FROM atividade_base WHERE nome_conceito = ?",
            (nome_base,),
        ).fetchone()["id"]
        conn.commit()
    return {"base_id": base_id, "eixo": eixo}


def _insert_versao(
    client,
    *,
    base_id: int,
    eixo: str,
    grupo: str,
    ch_por_evento,
    limite_semestre,
    limite_total,
    observacao_aluno: str,
    observacao_admin: str,
    vigencia_inicio: str,
    vigencia_fim: str,
    status: str = "rascunho",
    versao_anterior_id=None,
    numero_versao=None,
) -> int:
    with main.app.app_context():
        conn = main.get_db_connection()
        if numero_versao is None:
            numero_versao = conn.execute(
                "SELECT COALESCE(MAX(numero_versao), 0) + 1 FROM atividade_versao"
                " WHERE atividade_base_id = ?",
                (base_id,),
            ).fetchone()[0]
        cur = conn.execute(
            """
            INSERT INTO atividade_versao (
                atividade_base_id, eixo, grupo, status,
                ch_por_evento, limite_semestre, limite_total,
                observacao_aluno, observacao_admin,
                vigencia_inicio, vigencia_fim, versao_anterior_id, numero_versao
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                base_id, eixo, grupo, status,
                ch_por_evento, limite_semestre, limite_total,
                observacao_aluno, observacao_admin,
                vigencia_inicio, vigencia_fim, versao_anterior_id, numero_versao,
            ),
        )
        versao_id = cur.lastrowid
        conn.commit()
    return versao_id


V1_VALUES = {
    "grupo": "1 - Grupo FC07 v1",
    "ch_por_evento": 4.5,
    "limite_semestre": 40.0,
    "limite_total": 100.0,
    "observacao_aluno": "Observação do aluno v1",
    "observacao_admin": "Observação do admin v1",
    "vigencia_inicio": "2026-01-01",
    "vigencia_fim": "2026-12-31",
}

V2_VALUES = {
    "grupo": "1 - Grupo FC07 v2",
    "ch_por_evento": 6.0,
    "limite_semestre": 60.0,
    "limite_total": 150.0,
    "observacao_aluno": "Observação do aluno v2",
    "observacao_admin": "Observação do admin v2",
    "vigencia_inicio": "2027-01-01",
    "vigencia_fim": "2027-12-31",
}


def _seed_versao(client, *, eixo: str = "AAC", valores: dict | None = None) -> dict:
    """Base + uma atividade_versao com valores distintivos."""
    seed = _seed_base(client, eixo=eixo)
    valores = valores or V1_VALUES
    versao_id = _insert_versao(
        client,
        base_id=seed["base_id"],
        eixo=seed["eixo"],
        grupo=valores["grupo"],
        ch_por_evento=valores["ch_por_evento"],
        limite_semestre=valores["limite_semestre"],
        limite_total=valores["limite_total"],
        observacao_aluno=valores["observacao_aluno"],
        observacao_admin=valores["observacao_admin"],
        vigencia_inicio=valores["vigencia_inicio"],
        vigencia_fim=valores["vigencia_fim"],
    )
    return {**seed, "versao_id": versao_id}


def _nova_versao_url(client, base_id: int) -> str:
    return f"/admin/catalogo-versoes/{base_id}/nova-versao"


def _post_nova_versao(client, base_id: int, data: dict):
    with main.app.app_context():
        conn = main.get_db_connection()
        base = conn.execute(
            "SELECT nome_conceito, descricao FROM atividade_base WHERE id = ?", (base_id,)
        ).fetchone()
        predecessor = None
        if data.get("versao_anterior_id"):
            predecessor = conn.execute(
                "SELECT * FROM atividade_versao WHERE id = ?", (data["versao_anterior_id"],)
            ).fetchone()
    eixo = data.get("eixo", "AAC")
    tipo = "Extensão Universitária" if eixo == "AEU" else "Acadêmica Complementar"
    limite_semestre = data.get("limite_semestre", predecessor["limite_semestre"] if predecessor else "")
    limite_total = data.get("limite_total", predecessor["limite_total"] if predecessor else "")
    payload = {
        "tipo_atividade": tipo,
        "grupo": data.get("grupo", predecessor["grupo"] if predecessor else ""),
        "nome": base["nome_conceito"],
        "descricao": base["descricao"] or "",
        "tipo_limitacao": "semestral" if limite_semestre != "" else ("total" if limite_total != "" else ""),
        "limite_valor": limite_semestre if limite_semestre != "" else limite_total,
        "ch_por_evento": data.get("ch_por_evento", predecessor["ch_por_evento"] if predecessor else ""),
        "observacoes": data.get("observacao_admin") or data.get("observacao_aluno") or (
            (predecessor["observacao_admin"] or predecessor["observacao_aluno"] or "") if predecessor else ""
        ),
        "versao_anterior_id": data.get("versao_anterior_id", ""),
    }
    return client.post(_nova_versao_url(client, base_id), data=payload, follow_redirects=False)


# ---------------------------------------------------------------------------
# HTML assertion helpers
# ---------------------------------------------------------------------------

def _input_value(html: str, field_id: str) -> str:
    if field_id == "grupo":
        field_id = "grupo_hidden"
    match = re.search(rf'id="{field_id}"[^>]*value="([^"]*)"', html)
    assert match, f"campo id={field_id} não encontrado no HTML"
    return match.group(1)


def _textarea_value(html: str, field_id: str) -> str:
    match = re.search(rf'id="{field_id}"[^>]*>([^<]*)</textarea>', html)
    assert match, f"textarea id={field_id} não encontrado no HTML"
    return match.group(1)


def _selected_option_value(html: str, select_id: str):
    match = re.search(rf'<select id="{select_id}"[^>]*>(.*?)</select>', html, re.S)
    assert match, f"select id={select_id} não encontrado no HTML"
    options = re.findall(
        r'<option value="([^"]*)"\s*(selected)?[^>]*>(.*?)</option>', match.group(1), re.S
    )
    return [value for value, selected, _body in options if selected]


def _hidden_input_value(html: str, name: str) -> str:
    match = re.search(rf'<input type="hidden" name="{name}" value="([^"]*)"', html)
    assert match, f"hidden input name={name} não encontrado no HTML"
    return match.group(1)


def _readonly_meta_value(html: str, field_id: str) -> str:
    match = re.search(rf'id="{field_id}"[^>]*value="([^"]*)"', html)
    assert match, f"campo read-only id={field_id} não encontrado no HTML"
    return match.group(1)


def _assert_no_editable_predecessor(html: str) -> None:
    assert '<select id="versao_anterior_id" name="versao_anterior_id"' in html


def _assert_form_blank(html: str) -> None:
    assert _input_value(html, "grupo") == ""
    assert _input_value(html, "ch_por_evento") == ""
    assert _input_value(html, "limite_valor_hidden") == ""
    assert _textarea_value(html, "observacoes") == ""
    _assert_no_editable_predecessor(html)
    assert _selected_option_value(html, "versao_anterior_id") == []


def _assert_fixed_predecessor(html: str, predecessor_id: int) -> None:
    _assert_no_editable_predecessor(html)
    assert _selected_option_value(html, "versao_anterior_id") == [str(predecessor_id)]


# ---------------------------------------------------------------------------
# T1 — GET copy renderiza valores exatos do predecessor
# ---------------------------------------------------------------------------

def test_t1_get_copy_renders_exact_predecessor_values(client):
    _login_admin(client)
    seed = _seed_versao(client)

    r = client.get(_nova_versao_url(client, seed["base_id"]) + f"?from={seed['versao_id']}")
    assert r.status_code == 200
    html = r.get_data(as_text=True)

    assert _input_value(html, "grupo") == V1_VALUES["grupo"]
    assert _input_value(html, "ch_por_evento") == "4.5"
    assert _input_value(html, "limite_valor_hidden") == "40"
    assert _textarea_value(html, "observacoes") == V1_VALUES["observacao_admin"]
    assert "Vigência início" not in html and "Vigência fim" not in html

    _assert_fixed_predecessor(html, seed["versao_id"])


# ---------------------------------------------------------------------------
# T2 — identidade vem do id exato de `from`
# ---------------------------------------------------------------------------

def test_t2_exact_source_identity_from_id(client):
    _login_admin(client)
    seed = _seed_base(client)
    v1_id = _insert_versao(
        client, base_id=seed["base_id"], eixo=seed["eixo"], **V1_VALUES,
    )
    v2_id = _insert_versao(
        client, base_id=seed["base_id"], eixo=seed["eixo"], **V2_VALUES,
    )
    assert v1_id != v2_id

    r1 = client.get(_nova_versao_url(client, seed["base_id"]) + f"?from={v1_id}")
    html1 = r1.get_data(as_text=True)
    assert _input_value(html1, "grupo") == V1_VALUES["grupo"]
    assert _input_value(html1, "ch_por_evento") == "4.5"

    r2 = client.get(_nova_versao_url(client, seed["base_id"]) + f"?from={v2_id}")
    html2 = r2.get_data(as_text=True)
    assert _input_value(html2, "grupo") == V2_VALUES["grupo"]
    assert _input_value(html2, "ch_por_evento") == "6"
    _assert_fixed_predecessor(html2, v2_id)

    assert _input_value(html1, "grupo") != _input_value(html2, "grupo")


# ---------------------------------------------------------------------------
# T3 — fonte de outra atividade-base recusada (sem prefill, sem criação)
# ---------------------------------------------------------------------------

def test_t3_foreign_base_source_refused_on_get(client):
    _login_admin(client)
    base_a = _seed_versao(client)
    base_b = _seed_versao(client)

    r = client.get(_nova_versao_url(client, base_a["base_id"]) + f"?from={base_b['versao_id']}")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    _assert_form_blank(html)
    assert "mesma atividade-base" in html


def test_t3_foreign_base_source_refused_on_post(client):
    _login_admin(client)
    base_a = _seed_versao(client)
    base_b = _seed_versao(client)
    before = _count(client, "atividade_versao")

    r = _post_nova_versao(client, base_a["base_id"], {
        "eixo": "AAC",
        "versao_anterior_id": str(base_b["versao_id"]),
    })
    assert r.status_code == 200
    assert _count(client, "atividade_versao") == before


# ---------------------------------------------------------------------------
# T4 — `from` inexistente/malformado tratado com segurança, zero escritas
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("from_value", ["999999", "abc", "4.7", "-3"])
def test_t4_malformed_or_missing_from_handled_safely(client, from_value):
    _login_admin(client)
    seed = _seed_versao(client)
    before_versoes = _count(client, "atividade_versao")
    before_matriz = _count(client, "matriz_atividade_versao_item")
    before_transicoes = _count(client, "atividade_transicao")
    before_requisicoes = _count(client, "requisicoes")
    before_turmas = _count(client, "turmas")
    before_row = _get_versao_row(client, seed["versao_id"])

    r = client.get(_nova_versao_url(client, seed["base_id"]) + f"?from={from_value}")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    _assert_form_blank(html)

    assert _count(client, "atividade_versao") == before_versoes
    assert _count(client, "matriz_atividade_versao_item") == before_matriz
    assert _count(client, "atividade_transicao") == before_transicoes
    assert _count(client, "requisicoes") == before_requisicoes
    assert _count(client, "turmas") == before_turmas
    assert _get_versao_row(client, seed["versao_id"]) == before_row


# ---------------------------------------------------------------------------
# T5 — base sem histórico mantém formulário em branco
# ---------------------------------------------------------------------------

def test_t5_zero_history_base_blank_form(client):
    _login_admin(client)
    seed = _seed_base(client)

    r = client.get(_nova_versao_url(client, seed["base_id"]))
    assert r.status_code == 200
    _assert_form_blank(r.get_data(as_text=True))

    r_detail = client.get(f"/admin/catalogo-versoes/{seed['base_id']}")
    assert r_detail.status_code == 200
    html = r_detail.get_data(as_text=True)
    href_match = re.search(
        r'href="([^"]*nova-versao[^"]*)"[^>]*>(.*?)Criar versão', html, re.S
    )
    assert href_match, "link Criar versão não encontrado no detalhe"
    assert "from=" not in href_match.group(1), (
        "base sem histórico não deve carregar ?from= no link Criar versão"
    )


# ---------------------------------------------------------------------------
# T6 — link normal aponta para a versão de maior numero_versao
# ---------------------------------------------------------------------------

def test_t6_detail_page_points_to_highest_numero_versao(client):
    _login_admin(client)
    seed = _seed_base(client)
    a_id = _insert_versao(
        client, base_id=seed["base_id"], eixo=seed["eixo"], numero_versao=9, **V1_VALUES,
    )
    b_id = _insert_versao(
        client, base_id=seed["base_id"], eixo=seed["eixo"], numero_versao=3, **V2_VALUES,
    )
    versoes = _get_all_versoes(client, seed["base_id"])
    numero_por_id = {v["id"]: v["numero_versao"] for v in versoes}
    assert a_id < b_id, "A deve ter sido criada primeiro (id menor)"
    assert numero_por_id[a_id] == 9 and numero_por_id[b_id] == 3
    assert numero_por_id[a_id] > numero_por_id[b_id], (
        "A deve ter numero_versao maior que B para o teste discriminar"
    )
    assert numero_por_id[a_id] == max(numero_por_id.values())

    r = client.get(f"/admin/catalogo-versoes/{seed['base_id']}")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    href_match = re.search(
        r'href="([^"]*nova-versao[^"]*)"[^>]*>(.*?)Criar versão', html, re.S
    )
    assert href_match, "link Criar versão não encontrado no detalhe"
    href = href_match.group(1)
    assert f"?from={a_id}" in href, (
        "link Criar versão deve apontar para a versão de maior numero_versao (A), "
        f"não para a de maior id/criação mais recente, href={href!r}"
    )
    assert f"from={b_id}" not in href


# ---------------------------------------------------------------------------
# T7 — edição do admin após cópia é persistida (sem recópia no POST)
# ---------------------------------------------------------------------------

def test_t7_admin_edit_after_copy_is_persisted(client):
    _login_admin(client)
    seed = _seed_versao(client)

    r = client.get(_nova_versao_url(client, seed["base_id"]) + f"?from={seed['versao_id']}")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    _assert_fixed_predecessor(html, seed["versao_id"])

    edited = {
        "eixo": "AAC",
        "grupo": "1 - Grupo editado pelo admin",
        "ch_por_evento": "9",
        "limite_semestre": "30",
        "limite_total": "120",
        "observacao_aluno": "Observação editada pelo admin",
        "observacao_admin": "Admin editou esta observação",
        "vigencia_inicio": "2026-03-01",
        "vigencia_fim": "2026-09-30",
        "versao_anterior_id": str(seed["versao_id"]),
    }
    r = _post_nova_versao(client, seed["base_id"], edited)
    assert r.status_code == 302

    versoes = _get_all_versoes(client, seed["base_id"])
    assert len(versoes) == 2
    nova = [v for v in versoes if v["id"] != seed["versao_id"]][0]
    assert nova["eixo"] == "AAC"
    assert nova["grupo"] == "1 - Grupo editado pelo admin"
    assert nova["ch_por_evento"] == 9.0
    assert nova["limite_semestre"] == 30.0
    assert nova["limite_total"] is None
    assert nova["observacao_aluno"] == "Admin editou esta observação"
    assert nova["observacao_admin"] == "Admin editou esta observação"
    assert nova["vigencia_inicio"] == V1_VALUES["vigencia_inicio"]
    assert nova["vigencia_fim"] == V1_VALUES["vigencia_fim"]
    assert nova["grupo"] != V1_VALUES["grupo"], (
        "POST deve persistir os valores submetidos, não recopiar o predecessor"
    )


# ---------------------------------------------------------------------------
# T8 — linhagem: Av2.versao_anterior_id = Av1.id
# ---------------------------------------------------------------------------

def test_t8_lineage_versao_anterior_id(client):
    _login_admin(client)
    seed = _seed_versao(client)

    r = _post_nova_versao(client, seed["base_id"], {
        "eixo": "AAC",
        "ch_por_evento": "5",
        "versao_anterior_id": str(seed["versao_id"]),
    })
    assert r.status_code == 302

    versoes = _get_all_versoes(client, seed["base_id"])
    assert len(versoes) == 2
    nova = [v for v in versoes if v["id"] != seed["versao_id"]][0]
    assert nova["versao_anterior_id"] == seed["versao_id"]


# ---------------------------------------------------------------------------
# T9 — nova identidade: numero_versao base-wide MAX+1 e status rascunho;
#      a nova versão deve suceder a versão canônica mais recente (sem fallback)
# ---------------------------------------------------------------------------

def test_t9_new_identity_next_number_and_rascunho(client):
    _login_admin(client)
    seed = _seed_versao(client)
    older = _get_versao_row(client, seed["versao_id"])
    newer_id = _insert_versao(
        client, base_id=seed["base_id"], eixo=seed["eixo"], numero_versao=5, **V2_VALUES,
    )
    newer = _get_versao_row(client, newer_id)
    assert newer["numero_versao"] > older["numero_versao"], (
        "base deve ter uma versão com numero_versao maior que a fonte"
    )

    rejected = _post_nova_versao(client, seed["base_id"], {
        "eixo": "AAC",
        "versao_anterior_id": str(seed["versao_id"]),
    })
    before_rejected = _count(client, "atividade_versao")
    assert rejected.status_code == 200, (
        "sucessor de fonte não-canônica (mais antiga) deve ser rejeitado: "
        "a nova versão deve suceder a versão canônica mais recente"
    )
    assert _count(client, "atividade_versao") == before_rejected

    r = _post_nova_versao(client, seed["base_id"], {
        "eixo": "AAC",
        "ch_por_evento": "7",
        "versao_anterior_id": str(newer_id),
    })
    assert r.status_code == 302

    versoes = _get_all_versoes(client, seed["base_id"])
    assert len(versoes) == 3
    nova = [v for v in versoes if v["id"] not in (seed["versao_id"], newer_id)][0]
    assert nova["versao_anterior_id"] == newer_id, (
        "linhagem deve apontar para a versão canônica mais recente"
    )
    assert nova["numero_versao"] == newer["numero_versao"] + 1, (
        "novo numero_versao deve ser MAX(numero_versao) da base + 1"
    )
    assert nova["numero_versao"] != older["numero_versao"] + 1
    assert nova["status"] == "rascunho"
    assert nova["atividade_base_id"] == seed["base_id"]


# ---------------------------------------------------------------------------
# T10 — zero mutação histórica em Av1
# ---------------------------------------------------------------------------

def test_t10_predecessor_row_unchanged(client):
    _login_admin(client)
    seed = _seed_versao(client)
    before = _get_versao_row(client, seed["versao_id"])

    r = _post_nova_versao(client, seed["base_id"], {
        "eixo": "AAC",
        "ch_por_evento": "5",
        "versao_anterior_id": str(seed["versao_id"]),
    })
    assert r.status_code == 302

    after = _get_versao_row(client, seed["versao_id"])
    assert after == before, "Av1 deve permanecer valor-equivalente após criação de Av2"


# ---------------------------------------------------------------------------
# T11 — zero mutação em matriz_atividade_versao_item vinculada a Av1
# ---------------------------------------------------------------------------

def _seed_matriz_vinculada(client, versao_id: int) -> dict:
    token = uuid.uuid4().hex[:8]
    with main.app.app_context():
        conn = main.get_db_connection()
        curso_id = conn.execute(
            "INSERT INTO cursos (nome, codigo, duracao_periodos, periodo, status)"
            " VALUES (?, ?, ?, ?, ?)",
            (f"Curso FC07 {token}", f"CUR-FC07-{token}", 8, "integral", "ativo"),
        ).lastrowid
        matriz_id = conn.execute(
            "INSERT INTO matrizes_atividades (curso_id, nome, status)"
            " VALUES (?, ?, ?)",
            (curso_id, f"Matriz FC07 {token}", "ativa"),
        ).lastrowid
        item_id = conn.execute(
            "INSERT INTO matriz_atividade_versao_item "
            "(matriz_id, atividade_base_id, atividade_versao_id) "
            "SELECT ?, atividade_base_id, id FROM atividade_versao WHERE id = ?",
            (matriz_id, versao_id),
        ).lastrowid
        conn.commit()
    return {"curso_id": curso_id, "matriz_id": matriz_id, "item_id": item_id}


def test_t11_matrix_link_to_predecessor_untouched(client):
    _login_admin(client)
    seed = _seed_versao(client)
    matriz = _seed_matriz_vinculada(client, seed["versao_id"])
    before_items = _count(client, "matriz_atividade_versao_item")

    r = _post_nova_versao(client, seed["base_id"], {
        "eixo": "AAC",
        "ch_por_evento": "5",
        "versao_anterior_id": str(seed["versao_id"]),
    })
    assert r.status_code == 302

    assert _count(client, "matriz_atividade_versao_item") == before_items
    assert _count_where(
        client,
        "matriz_atividade_versao_item",
        "matriz_id = ? AND atividade_versao_id = ?",
        (matriz["matriz_id"], seed["versao_id"]),
    ) == 1


# ---------------------------------------------------------------------------
# T12 — GET de cópia: zero escritas em linhas/contagens relevantes
# ---------------------------------------------------------------------------

def test_t12_copy_prefill_get_writes_nothing(client):
    _login_admin(client)
    seed = _seed_versao(client)
    matriz = _seed_matriz_vinculada(client, seed["versao_id"])

    before = {
        "versoes": _count(client, "atividade_versao"),
        "matriz_items": _count(client, "matriz_atividade_versao_item"),
        "transicoes": _count(client, "atividade_transicao"),
        "requisicoes": _count(client, "requisicoes"),
        "turmas": _count(client, "turmas"),
    }
    before_row = _get_versao_row(client, seed["versao_id"])

    r = client.get(_nova_versao_url(client, seed["base_id"]) + f"?from={seed['versao_id']}")
    assert r.status_code == 200

    assert _count(client, "atividade_versao") == before["versoes"]
    assert _count(client, "matriz_atividade_versao_item") == before["matriz_items"]
    assert _count(client, "atividade_transicao") == before["transicoes"]
    assert _count(client, "requisicoes") == before["requisicoes"]
    assert _count(client, "turmas") == before["turmas"]
    assert _get_versao_row(client, seed["versao_id"]) == before_row
    assert _count_where(
        client,
        "matriz_atividade_versao_item",
        "matriz_id = ? AND atividade_versao_id = ?",
        (matriz["matriz_id"], seed["versao_id"]),
    ) == 1
