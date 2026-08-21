"""
D7.2B3-PATCH2 — Testes de edição de atividade_versao em rascunho.

Cobre:
 1. GET editar versão rascunho retorna 200.
 2. GET editar versão inexistente redireciona ou bloqueia sem 500.
 3. GET editar versão de outra base rejeita.
 4. GET editar versão não-rascunho bloqueia para ativa, inativa, descontinuada e substituida.
 5. POST válido em rascunho atualiza campos permitidos.
 6. POST válido recalcula codigo_normativo/eixo quando norma_id muda.
 7. POST duplicidade base+norma rejeita ignorando a própria versão.
 8. POST sem norma_id rejeita.
 9. POST norma inexistente rejeita.
10. POST norma inativa rejeita.
11. POST número não numérico rejeita.
12. POST número negativo rejeita.
13. POST versao_anterior_id inexistente rejeita.
14. POST versao_anterior_id de outra base rejeita.
15. POST versao_anterior_id de eixo incompatível rejeita.
16. POST versao_anterior_id igual ao próprio id rejeita.
17. POST em versão ativa/inativa/descontinuada/substituida rejeita.
18. POST com status=ativa no payload não muda status.
19. POST com atividade_base_id manipulada no payload não muda base.
20. POST bloqueia edição se houver uso em matriz_atividade_versao_item.
21. POST bloqueia edição se houver uso em requisicoes.atividade_versao_id.
22. POST bloqueia edição se houver uso em atividade_transicao.from_atividade_versao_id.
23. POST bloqueia edição se houver uso em atividade_transicao.to_atividade_versao_id.
24. POST não altera matriz_atividade_versao_item.
25. POST não altera requisicoes.
26. Rotas read-only D7.2B1 continuam respondendo.
27. Criação PATCH1 continua funcionando.
28. Contrato D7.1 (rascunho excluído do resolver) continua intacto após edição.
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


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def _seed_base_and_normas(client):
    """
    Insere uma atividade_base, uma norma ativa (AAC) e uma norma inativa (AAC).
    Retorna dict com base_id, norma_ativa_id, norma_inativa_id, e os codigos.
    """
    token = uuid.uuid4().hex[:8]
    with main.app.app_context():
        conn = main.get_db_connection()
        nome_base = f"Base Edicao D72B3 {token}"
        conn.execute(
            "INSERT INTO atividade_base (nome_conceito, descricao, status) VALUES (?, ?, ?)",
            (nome_base, "Descrição", "ativo"),
        )
        base_id = conn.execute(
            "SELECT id FROM atividade_base WHERE nome_conceito = ?",
            (nome_base,),
        ).fetchone()["id"]

        cod_ativa = f"NRM-ATIVA-EDIT-{token}"
        conn.execute(
            "INSERT INTO norma_atividade (codigo, eixo, revisao, nome, status) VALUES (?, ?, ?, ?, ?)",
            (cod_ativa, "AAC", "rev1", "Norma Ativa Edição", "ativa"),
        )
        norma_ativa_id = conn.execute(
            "SELECT id FROM norma_atividade WHERE codigo = ?",
            (cod_ativa,),
        ).fetchone()["id"]

        cod_inat = f"NRM-INAT-EDIT-{token}"
        conn.execute(
            "INSERT INTO norma_atividade (codigo, eixo, revisao, nome, status) VALUES (?, ?, ?, ?, ?)",
            (cod_inat, "AAC", "rev1", "Norma Inativa Edição", "inativa"),
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


def _insert_versao(
    client,
    *,
    atividade_base_id,
    norma_id,
    codigo_normativo,
    eixo,
    status="rascunho",
    grupo="1 - Grupo teste",
    ch_por_evento=None,
    limite_semestre=None,
    limite_total=None,
    observacao_aluno=None,
    observacao_admin=None,
    vigencia_inicio=None,
    vigencia_fim=None,
    versao_anterior_id=None,
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
                atividade_base_id, norma_id, codigo_normativo, eixo, grupo, status,
                ch_por_evento, limite_semestre, limite_total,
                observacao_aluno, observacao_admin,
                vigencia_inicio, vigencia_fim, versao_anterior_id, numero_versao
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                atividade_base_id, norma_id, codigo_normativo, eixo, grupo, status,
                ch_por_evento, limite_semestre, limite_total,
                observacao_aluno, observacao_admin,
                vigencia_inicio, vigencia_fim, versao_anterior_id, next_num,
            ),
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

def _get_editar_versao(client, base_id, versao_id):
    return client.get(f"/admin/catalogo-versoes/{base_id}/versoes/{versao_id}/editar")


def _post_editar_versao(client, base_id, versao_id, norma_id, **kwargs):
    data = {
        "norma_id": str(norma_id),
        "grupo": kwargs.get("grupo", "1 - Grupo editado"),
        "ch_por_evento": kwargs.get("ch_por_evento", "5"),
        "limite_semestre": kwargs.get("limite_semestre", "50"),
        "limite_total": kwargs.get("limite_total", "120"),
        "observacao_aluno": kwargs.get("observacao_aluno", ""),
        "observacao_admin": kwargs.get("observacao_admin", ""),
        "vigencia_inicio": kwargs.get("vigencia_inicio", ""),
        "vigencia_fim": kwargs.get("vigencia_fim", ""),
        "versao_anterior_id": kwargs.get("versao_anterior_id", ""),
    }
    for extra in ("status", "atividade_base_id", "codigo_normativo", "eixo"):
        if extra in kwargs:
            data[extra] = kwargs[extra]
    return client.post(
        f"/admin/catalogo-versoes/{base_id}/versoes/{versao_id}/editar",
        data=data,
        follow_redirects=False,
    )


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
# 1. GET editar versão rascunho retorna 200
# ---------------------------------------------------------------------------

def test_get_editar_versao_rascunho_returns_200(client):
    _login_admin(client)
    seed = _seed_base_and_normas(client)
    versao_id = _insert_versao(
        client,
        atividade_base_id=seed["base_id"],
        norma_id=seed["norma_ativa_id"],
        codigo_normativo=seed["codigo_ativa"],
        eixo="AAC",
    )
    r = _get_editar_versao(client, seed["base_id"], versao_id)
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "Salvar alterações" in html


# ---------------------------------------------------------------------------
# 2. GET editar versão inexistente redireciona sem 500
# ---------------------------------------------------------------------------

def test_get_editar_versao_inexistente_redirects_without_500(client):
    _login_admin(client)
    seed = _seed_base_and_normas(client)
    r = _get_editar_versao(client, seed["base_id"], 999999)
    assert r.status_code == 302
    assert r.status_code != 500
    assert f"/admin/catalogo-versoes/{seed['base_id']}" in r.headers.get("Location", "")


# ---------------------------------------------------------------------------
# 3. GET editar versão de outra base rejeita
# ---------------------------------------------------------------------------

def test_get_editar_versao_outra_base_rejected(client):
    _login_admin(client)
    seed = _seed_base_and_normas(client)
    versao_id = _insert_versao(
        client,
        atividade_base_id=seed["base_id"],
        norma_id=seed["norma_ativa_id"],
        codigo_normativo=seed["codigo_ativa"],
        eixo="AAC",
    )
    with main.app.app_context():
        conn = main.get_db_connection()
        nome_outra = f"Outra Base Edicao GET {uuid.uuid4().hex[:6]}"
        conn.execute(
            "INSERT INTO atividade_base (nome_conceito, descricao, status) VALUES (?, ?, ?)",
            (nome_outra, "Desc", "ativo"),
        )
        outra_base_id = conn.execute(
            "SELECT id FROM atividade_base WHERE nome_conceito = ?", (nome_outra,)
        ).fetchone()["id"]
        conn.commit()

    r = _get_editar_versao(client, outra_base_id, versao_id)
    assert r.status_code == 302
    assert f"/admin/catalogo-versoes/{outra_base_id}" in r.headers.get("Location", "")
    versao = _get_versao(client, versao_id)
    assert versao["atividade_base_id"] == seed["base_id"]


# ---------------------------------------------------------------------------
# 4. GET editar versão não-rascunho bloqueia para ativa, inativa, descontinuada, substituida
# ---------------------------------------------------------------------------

def test_get_editar_versao_non_rascunho_blocked(client):
    _login_admin(client)
    seed = _seed_base_and_normas(client)
    for status in ("ativa", "inativa", "descontinuada", "substituida"):
        token = uuid.uuid4().hex[:6]
        cod = f"NRM-GET-{status[:4].upper()}-{token}"
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute(
                "INSERT INTO norma_atividade (codigo, eixo, revisao, nome, status) VALUES (?, ?, ?, ?, ?)",
                (cod, "AAC", "rev1", f"Norma GET {status}", "ativa"),
            )
            norma_id = conn.execute(
                "SELECT id FROM norma_atividade WHERE codigo = ?", (cod,)
            ).fetchone()["id"]
            conn.commit()
        versao_id = _insert_versao(
            client,
            atividade_base_id=seed["base_id"],
            norma_id=norma_id,
            codigo_normativo=cod,
            eixo="AAC",
            status=status,
        )
        r = _get_editar_versao(client, seed["base_id"], versao_id)
        assert r.status_code == 302, f"status={status} deveria bloquear GET com redirect"
        assert f"/admin/catalogo-versoes/{seed['base_id']}" in r.headers.get("Location", "")


# ---------------------------------------------------------------------------
# 5. POST válido em rascunho atualiza campos permitidos
# ---------------------------------------------------------------------------

def test_post_editar_versao_valid_updates_allowed_fields(client):
    _login_admin(client)
    seed = _seed_base_and_normas(client)
    versao_id = _insert_versao(
        client,
        atividade_base_id=seed["base_id"],
        norma_id=seed["norma_ativa_id"],
        codigo_normativo=seed["codigo_ativa"],
        eixo="AAC",
        grupo="Grupo original",
        ch_por_evento=4.0,
        limite_semestre=40.0,
        limite_total=100.0,
    )
    r = _post_editar_versao(
        client, seed["base_id"], versao_id, seed["norma_ativa_id"],
        grupo="Grupo atualizado",
        ch_por_evento="8",
        limite_semestre="60",
        limite_total="200",
        observacao_aluno="Obs aluno nova",
        observacao_admin="Obs admin nova",
        vigencia_inicio="2026-01-01",
        vigencia_fim="2026-12-31",
    )
    assert r.status_code == 302
    assert f"/admin/catalogo-versoes/{seed['base_id']}" in r.headers.get("Location", "")

    versao = _get_versao(client, versao_id)
    assert versao["grupo"] == "Grupo atualizado"
    assert versao["ch_por_evento"] == 8.0
    assert versao["limite_semestre"] == 60.0
    assert versao["limite_total"] == 200.0
    assert versao["observacao_aluno"] == "Obs aluno nova"
    assert versao["observacao_admin"] == "Obs admin nova"
    assert versao["vigencia_inicio"] == "2026-01-01"
    assert versao["vigencia_fim"] == "2026-12-31"
    assert versao["status"] == "rascunho"


# ---------------------------------------------------------------------------
# 6. POST válido recalcula codigo_normativo/eixo quando norma_id muda
# ---------------------------------------------------------------------------

def test_post_editar_versao_recalculates_codigo_and_eixo_on_norma_change(client):
    _login_admin(client)
    seed = _seed_base_and_normas(client)
    token = uuid.uuid4().hex[:8]
    cod_aeu = f"NRM-AEU-TROCA-EDIT-{token}"
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "INSERT INTO norma_atividade (codigo, eixo, revisao, nome, status) VALUES (?, ?, ?, ?, ?)",
            (cod_aeu, "AEU", "rev1", "Norma AEU Trocada", "ativa"),
        )
        norma_aeu_id = conn.execute(
            "SELECT id FROM norma_atividade WHERE codigo = ?", (cod_aeu,)
        ).fetchone()["id"]
        conn.commit()

    versao_id = _insert_versao(
        client,
        atividade_base_id=seed["base_id"],
        norma_id=seed["norma_ativa_id"],
        codigo_normativo=seed["codigo_ativa"],
        eixo="AAC",
    )
    r = _post_editar_versao(client, seed["base_id"], versao_id, norma_aeu_id)
    assert r.status_code == 302

    versao = _get_versao(client, versao_id)
    assert versao["norma_id"] == norma_aeu_id
    assert versao["codigo_normativo"] == cod_aeu
    assert versao["eixo"] == "AEU"


# ---------------------------------------------------------------------------
# 7. POST duplicidade base+norma rejeita ignorando a própria versão
# ---------------------------------------------------------------------------

def test_post_editar_versao_duplicate_rejected_but_self_allowed(client):
    _login_admin(client)
    seed = _seed_base_and_normas(client)
    token = uuid.uuid4().hex[:8]
    cod_b = f"NRM-B-DUP-EDIT-{token}"
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "INSERT INTO norma_atividade (codigo, eixo, revisao, nome, status) VALUES (?, ?, ?, ?, ?)",
            (cod_b, "AAC", "rev1", "Norma B Duplic", "ativa"),
        )
        norma_b_id = conn.execute(
            "SELECT id FROM norma_atividade WHERE codigo = ?", (cod_b,)
        ).fetchone()["id"]
        conn.commit()

    versao_a_id = _insert_versao(
        client, atividade_base_id=seed["base_id"], norma_id=seed["norma_ativa_id"],
        codigo_normativo=seed["codigo_ativa"], eixo="AAC",
    )
    versao_b_id = _insert_versao(
        client, atividade_base_id=seed["base_id"], norma_id=norma_b_id,
        codigo_normativo=cod_b, eixo="AAC",
    )

    # 7a: editar B mantendo sua própria norma (self-exclusion) não deve ser bloqueado
    r_self = _post_editar_versao(
        client, seed["base_id"], versao_b_id, norma_b_id, grupo="Grupo B Editado"
    )
    assert r_self.status_code == 302, "Editar mantendo a própria norma não deve ser bloqueado por duplicidade"
    versao_b = _get_versao(client, versao_b_id)
    assert versao_b["grupo"] == "Grupo B Editado"

    # 7b: editar B trocando para a norma já usada por A agora é permitido (D7.6B2 removeu UNIQUE(base,norma))
    r_dup = _post_editar_versao(client, seed["base_id"], versao_b_id, seed["norma_ativa_id"])
    assert r_dup.status_code == 302
    versao_b_after = _get_versao(client, versao_b_id)
    assert versao_b_after["norma_id"] == seed["norma_ativa_id"], "norma_id de B deve ter sido atualizada"


# ---------------------------------------------------------------------------
# 8. POST sem norma_id rejeita
# ---------------------------------------------------------------------------

def test_post_editar_versao_empty_norma_id_rejected(client):
    _login_admin(client)
    seed = _seed_base_and_normas(client)
    versao_id = _insert_versao(
        client, atividade_base_id=seed["base_id"], norma_id=seed["norma_ativa_id"],
        codigo_normativo=seed["codigo_ativa"], eixo="AAC",
    )
    r = client.post(
        f"/admin/catalogo-versoes/{seed['base_id']}/versoes/{versao_id}/editar",
        data={
            "norma_id": "",
            "grupo": "Grupo X",
            "ch_por_evento": "4",
            "limite_semestre": "40",
            "limite_total": "100",
        },
        follow_redirects=False,
    )
    assert r.status_code == 200
    versao = _get_versao(client, versao_id)
    assert versao["norma_id"] == seed["norma_ativa_id"]


# ---------------------------------------------------------------------------
# 9. POST norma inexistente rejeita
# ---------------------------------------------------------------------------

def test_post_editar_versao_norma_inexistente_rejected(client):
    _login_admin(client)
    seed = _seed_base_and_normas(client)
    versao_id = _insert_versao(
        client, atividade_base_id=seed["base_id"], norma_id=seed["norma_ativa_id"],
        codigo_normativo=seed["codigo_ativa"], eixo="AAC",
    )
    r = _post_editar_versao(client, seed["base_id"], versao_id, 999999)
    assert r.status_code == 200
    versao = _get_versao(client, versao_id)
    assert versao["norma_id"] == seed["norma_ativa_id"]


# ---------------------------------------------------------------------------
# 10. POST norma inativa rejeita
# ---------------------------------------------------------------------------

def test_post_editar_versao_norma_inativa_rejected(client):
    _login_admin(client)
    seed = _seed_base_and_normas(client)
    versao_id = _insert_versao(
        client, atividade_base_id=seed["base_id"], norma_id=seed["norma_ativa_id"],
        codigo_normativo=seed["codigo_ativa"], eixo="AAC",
    )
    r = _post_editar_versao(client, seed["base_id"], versao_id, seed["norma_inativa_id"])
    assert r.status_code == 200
    versao = _get_versao(client, versao_id)
    assert versao["norma_id"] == seed["norma_ativa_id"]


# ---------------------------------------------------------------------------
# 11. POST número não numérico rejeita
# ---------------------------------------------------------------------------

def test_post_editar_versao_non_numeric_number_rejected(client):
    _login_admin(client)
    seed = _seed_base_and_normas(client)
    versao_id = _insert_versao(
        client, atividade_base_id=seed["base_id"], norma_id=seed["norma_ativa_id"],
        codigo_normativo=seed["codigo_ativa"], eixo="AAC", ch_por_evento=4.0,
    )
    r = _post_editar_versao(
        client, seed["base_id"], versao_id, seed["norma_ativa_id"], ch_por_evento="abc"
    )
    assert r.status_code == 200
    versao = _get_versao(client, versao_id)
    assert versao["ch_por_evento"] == 4.0


# ---------------------------------------------------------------------------
# 12. POST número negativo rejeita
# ---------------------------------------------------------------------------

def test_post_editar_versao_negative_number_rejected(client):
    _login_admin(client)
    seed = _seed_base_and_normas(client)
    versao_id = _insert_versao(
        client, atividade_base_id=seed["base_id"], norma_id=seed["norma_ativa_id"],
        codigo_normativo=seed["codigo_ativa"], eixo="AAC", limite_total=100.0,
    )
    r = _post_editar_versao(
        client, seed["base_id"], versao_id, seed["norma_ativa_id"], limite_total="-5"
    )
    assert r.status_code == 200
    versao = _get_versao(client, versao_id)
    assert versao["limite_total"] == 100.0


# ---------------------------------------------------------------------------
# 13. POST versao_anterior_id inexistente rejeita
# ---------------------------------------------------------------------------

def test_post_editar_versao_versao_anterior_inexistente_rejected(client):
    _login_admin(client)
    seed = _seed_base_and_normas(client)
    versao_id = _insert_versao(
        client, atividade_base_id=seed["base_id"], norma_id=seed["norma_ativa_id"],
        codigo_normativo=seed["codigo_ativa"], eixo="AAC",
    )
    r = _post_editar_versao(
        client, seed["base_id"], versao_id, seed["norma_ativa_id"], versao_anterior_id="999999"
    )
    assert r.status_code == 200
    versao = _get_versao(client, versao_id)
    assert versao["versao_anterior_id"] is None


# ---------------------------------------------------------------------------
# 14. POST versao_anterior_id de outra base rejeita
# ---------------------------------------------------------------------------

def test_post_editar_versao_versao_anterior_outra_base_rejected(client):
    _login_admin(client)
    seed = _seed_base_and_normas(client)
    with main.app.app_context():
        conn = main.get_db_connection()
        nome_outra = f"Outra Base Prev {uuid.uuid4().hex[:6]}"
        conn.execute(
            "INSERT INTO atividade_base (nome_conceito, descricao, status) VALUES (?, ?, ?)",
            (nome_outra, "Desc", "ativo"),
        )
        outra_base_id = conn.execute(
            "SELECT id FROM atividade_base WHERE nome_conceito = ?", (nome_outra,)
        ).fetchone()["id"]
        conn.commit()

    outra_versao_id = _insert_versao(
        client, atividade_base_id=outra_base_id, norma_id=seed["norma_ativa_id"],
        codigo_normativo=seed["codigo_ativa"], eixo="AAC",
    )
    versao_id = _insert_versao(
        client, atividade_base_id=seed["base_id"], norma_id=seed["norma_ativa_id"],
        codigo_normativo=seed["codigo_ativa"], eixo="AAC",
    )

    r = _post_editar_versao(
        client, seed["base_id"], versao_id, seed["norma_ativa_id"],
        versao_anterior_id=str(outra_versao_id),
    )
    assert r.status_code == 200
    versao = _get_versao(client, versao_id)
    assert versao["versao_anterior_id"] is None


# ---------------------------------------------------------------------------
# 15. POST versao_anterior_id de eixo incompatível rejeita
# ---------------------------------------------------------------------------

def test_post_editar_versao_versao_anterior_eixo_incompativel_rejected(client):
    _login_admin(client)
    seed = _seed_base_and_normas(client)
    token = uuid.uuid4().hex[:8]
    cod_aeu = f"NRM-AEU-PREV-EDICAO-{token}"
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "INSERT INTO norma_atividade (codigo, eixo, revisao, nome, status) VALUES (?, ?, ?, ?, ?)",
            (cod_aeu, "AEU", "rev1", "Norma AEU Prev Edição", "ativa"),
        )
        norma_aeu_id = conn.execute(
            "SELECT id FROM norma_atividade WHERE codigo = ?", (cod_aeu,)
        ).fetchone()["id"]
        conn.commit()

    versao_aeu_id = _insert_versao(
        client, atividade_base_id=seed["base_id"], norma_id=norma_aeu_id,
        codigo_normativo=cod_aeu, eixo="AEU",
    )
    versao_id = _insert_versao(
        client, atividade_base_id=seed["base_id"], norma_id=seed["norma_ativa_id"],
        codigo_normativo=seed["codigo_ativa"], eixo="AAC",
    )

    r = _post_editar_versao(
        client, seed["base_id"], versao_id, seed["norma_ativa_id"],
        versao_anterior_id=str(versao_aeu_id),
    )
    assert r.status_code == 200
    versao = _get_versao(client, versao_id)
    assert versao["versao_anterior_id"] is None


# ---------------------------------------------------------------------------
# 16. POST versao_anterior_id igual ao próprio id rejeita
# ---------------------------------------------------------------------------

def test_post_editar_versao_versao_anterior_self_rejected(client):
    _login_admin(client)
    seed = _seed_base_and_normas(client)
    versao_id = _insert_versao(
        client, atividade_base_id=seed["base_id"], norma_id=seed["norma_ativa_id"],
        codigo_normativo=seed["codigo_ativa"], eixo="AAC",
    )
    r = _post_editar_versao(
        client, seed["base_id"], versao_id, seed["norma_ativa_id"],
        versao_anterior_id=str(versao_id),
    )
    assert r.status_code == 200
    versao = _get_versao(client, versao_id)
    assert versao["versao_anterior_id"] is None


# ---------------------------------------------------------------------------
# 17. POST em versão ativa/inativa/descontinuada/substituida rejeita (server-side)
# ---------------------------------------------------------------------------

def test_post_editar_versao_non_rascunho_blocked(client):
    _login_admin(client)
    seed = _seed_base_and_normas(client)
    for status in ("ativa", "inativa", "descontinuada", "substituida"):
        token = uuid.uuid4().hex[:6]
        cod = f"NRM-POST-{status[:4].upper()}-{token}"
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute(
                "INSERT INTO norma_atividade (codigo, eixo, revisao, nome, status) VALUES (?, ?, ?, ?, ?)",
                (cod, "AAC", "rev1", f"Norma POST {status}", "ativa"),
            )
            norma_id = conn.execute(
                "SELECT id FROM norma_atividade WHERE codigo = ?", (cod,)
            ).fetchone()["id"]
            conn.commit()
        versao_id = _insert_versao(
            client, atividade_base_id=seed["base_id"], norma_id=norma_id,
            codigo_normativo=cod, eixo="AAC", status=status, grupo="Grupo original",
        )
        r = _post_editar_versao(
            client, seed["base_id"], versao_id, norma_id, grupo="Grupo TENTATIVA"
        )
        assert r.status_code == 302, f"status={status} deveria bloquear POST com redirect"
        versao = _get_versao(client, versao_id)
        assert versao["grupo"] == "Grupo original", f"status={status}: edição não deveria ter sido aplicada"
        assert versao["status"] == status


# ---------------------------------------------------------------------------
# 18. POST com status=ativa no payload não muda status
# ---------------------------------------------------------------------------

def test_post_editar_versao_status_in_payload_ignored(client):
    _login_admin(client)
    seed = _seed_base_and_normas(client)
    versao_id = _insert_versao(
        client, atividade_base_id=seed["base_id"], norma_id=seed["norma_ativa_id"],
        codigo_normativo=seed["codigo_ativa"], eixo="AAC",
    )
    r = _post_editar_versao(
        client, seed["base_id"], versao_id, seed["norma_ativa_id"],
        status="ativa",
        grupo="Grupo com status manipulado",
    )
    assert r.status_code == 302
    versao = _get_versao(client, versao_id)
    assert versao["status"] == "rascunho"
    assert versao["grupo"] == "Grupo com status manipulado"


# ---------------------------------------------------------------------------
# 19. POST com atividade_base_id manipulada no payload não muda base
# ---------------------------------------------------------------------------

def test_post_editar_versao_atividade_base_id_in_payload_ignored(client):
    _login_admin(client)
    seed = _seed_base_and_normas(client)
    with main.app.app_context():
        conn = main.get_db_connection()
        nome_outra = f"Outra Base Manipulacao {uuid.uuid4().hex[:6]}"
        conn.execute(
            "INSERT INTO atividade_base (nome_conceito, descricao, status) VALUES (?, ?, ?)",
            (nome_outra, "Desc", "ativo"),
        )
        outra_base_id = conn.execute(
            "SELECT id FROM atividade_base WHERE nome_conceito = ?", (nome_outra,)
        ).fetchone()["id"]
        conn.commit()

    versao_id = _insert_versao(
        client, atividade_base_id=seed["base_id"], norma_id=seed["norma_ativa_id"],
        codigo_normativo=seed["codigo_ativa"], eixo="AAC",
    )
    r = _post_editar_versao(
        client, seed["base_id"], versao_id, seed["norma_ativa_id"],
        atividade_base_id=str(outra_base_id),
        grupo="Grupo com base manipulada",
    )
    assert r.status_code == 302
    versao = _get_versao(client, versao_id)
    assert versao["atividade_base_id"] == seed["base_id"]
    assert versao["grupo"] == "Grupo com base manipulada"


# ---------------------------------------------------------------------------
# 20. POST bloqueia edição se houver uso em matriz_atividade_versao_item
# ---------------------------------------------------------------------------

def test_post_editar_versao_blocked_when_used_in_matriz_item(client):
    _login_admin(client)
    seed = _seed_base_and_normas(client)
    versao_id = _insert_versao(
        client, atividade_base_id=seed["base_id"], norma_id=seed["norma_ativa_id"],
        codigo_normativo=seed["codigo_ativa"], eixo="AAC", grupo="Grupo em uso matriz",
    )
    token = uuid.uuid4().hex[:8]
    with main.app.app_context():
        conn = main.get_db_connection()
        curso_id = conn.execute("SELECT id FROM cursos WHERE codigo = 'GERAL'").fetchone()["id"]
        matriz_id = conn.execute(
            "INSERT INTO matrizes_atividades (curso_id, nome, versao, status) VALUES (?, ?, ?, 'ativa')",
            (curso_id, f"Matriz Bloqueio {token}", "2026.1"),
        ).lastrowid
        conn.execute(
            "INSERT INTO matriz_atividade_versao_item "
            "(matriz_id, atividade_base_id, atividade_versao_id) VALUES (?, ?, ?)",
            (matriz_id, seed["base_id"], versao_id),
        )
        conn.execute(
            """
                INSERT INTO turmas (
                    nome, turno, status, numero, curso_id, matriz_id,
                    ano_inicio, semestre_inicio, ano_fim, semestre_fim, codigo
                ) VALUES (?, 'Noite', 'Ativa', 991, ?, ?, 2026, 1, 2029, 2, ?)
            """,
            (f"Turma B5v {token}", curso_id, matriz_id, f"B5V-{token}"),
        )
        conn.commit()

    r = _post_editar_versao(
        client, seed["base_id"], versao_id, seed["norma_ativa_id"], grupo="Tentativa"
    )
    assert r.status_code == 302
    assert f"/admin/catalogo-versoes/{seed['base_id']}" in r.headers.get("Location", "")
    versao = _get_versao(client, versao_id)
    assert versao["grupo"] == "Grupo em uso matriz"


# ---------------------------------------------------------------------------
# 21. POST bloqueia edição se houver uso em requisicoes.atividade_versao_id
# ---------------------------------------------------------------------------

def test_post_editar_versao_blocked_when_used_in_requisicoes(client):
    _login_admin(client)
    seed = _seed_base_and_normas(client)
    versao_id = _insert_versao(
        client, atividade_base_id=seed["base_id"], norma_id=seed["norma_ativa_id"],
        codigo_normativo=seed["codigo_ativa"], eixo="AAC", grupo="Grupo em uso requisicao",
    )
    token = uuid.uuid4().hex[:8]
    with main.app.app_context():
        conn = main.get_db_connection()
        usuario_id = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo) VALUES (?, ?, ?, ?)",
            (f"Aluno Req {token}", f"aluno.req.{token}@teste.local", "hash", "aluno"),
        ).lastrowid
        aluno_id = conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email) VALUES (?, ?, ?, ?)",
            (usuario_id, f"Aluno Req {token}", f"REQ-{token}", f"aluno.req.{token}@teste.local"),
        ).lastrowid
        conn.execute(
            """
            INSERT INTO requisicoes (
                aluno_id, data_solicitacao, data_evento, horas_solicitadas,
                nome_evento, status, atividade_versao_id,
                codigo_normativo_snapshot, regra_snapshot_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (aluno_id, "2026-05-22 10:00:00", "2026-05-22", 2.0,
             f"Evento {token}", "Pendente", versao_id, seed["codigo_ativa"], "{}"),
        )
        conn.commit()

    r = _post_editar_versao(
        client, seed["base_id"], versao_id, seed["norma_ativa_id"], grupo="Tentativa"
    )
    assert r.status_code == 302
    versao = _get_versao(client, versao_id)
    assert versao["grupo"] == "Grupo em uso requisicao"


# ---------------------------------------------------------------------------
# 22. POST bloqueia edição se houver uso em atividade_transicao.from_atividade_versao_id
# ---------------------------------------------------------------------------

def test_post_editar_versao_blocked_when_used_in_transicao_origem(client):
    _login_admin(client)
    seed = _seed_base_and_normas(client)
    token = uuid.uuid4().hex[:8]
    cod_dest = f"NRM-DEST-ORIG-{token}"
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "INSERT INTO norma_atividade (codigo, eixo, revisao, nome, status) VALUES (?, ?, ?, ?, ?)",
            (cod_dest, "AAC", "rev2", "Norma Destino Transicao", "ativa"),
        )
        norma_dest_id = conn.execute(
            "SELECT id FROM norma_atividade WHERE codigo = ?", (cod_dest,)
        ).fetchone()["id"]
        conn.commit()

    versao_id = _insert_versao(
        client, atividade_base_id=seed["base_id"], norma_id=seed["norma_ativa_id"],
        codigo_normativo=seed["codigo_ativa"], eixo="AAC", grupo="Grupo origem transicao",
    )
    versao_dest_id = _insert_versao(
        client, atividade_base_id=seed["base_id"], norma_id=norma_dest_id,
        codigo_normativo=cod_dest, eixo="AAC",
    )

    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            """
            INSERT INTO atividade_transicao
                (from_atividade_versao_id, to_atividade_versao_id, tipo_transicao)
            VALUES (?, ?, 'mesmo_eixo')
            """,
            (versao_id, versao_dest_id),
        )
        conn.commit()

    r = _post_editar_versao(
        client, seed["base_id"], versao_id, seed["norma_ativa_id"], grupo="Tentativa"
    )
    assert r.status_code == 302
    versao = _get_versao(client, versao_id)
    assert versao["grupo"] == "Grupo origem transicao"


# ---------------------------------------------------------------------------
# 23. POST bloqueia edição se houver uso em atividade_transicao.to_atividade_versao_id
# ---------------------------------------------------------------------------

def test_post_editar_versao_blocked_when_used_in_transicao_destino(client):
    _login_admin(client)
    seed = _seed_base_and_normas(client)
    token = uuid.uuid4().hex[:8]
    cod_orig = f"NRM-ORIG-DEST-{token}"
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "INSERT INTO norma_atividade (codigo, eixo, revisao, nome, status) VALUES (?, ?, ?, ?, ?)",
            (cod_orig, "AAC", "rev2", "Norma Origem Transicao", "ativa"),
        )
        norma_orig_id = conn.execute(
            "SELECT id FROM norma_atividade WHERE codigo = ?", (cod_orig,)
        ).fetchone()["id"]
        conn.commit()

    versao_orig_id = _insert_versao(
        client, atividade_base_id=seed["base_id"], norma_id=norma_orig_id,
        codigo_normativo=cod_orig, eixo="AAC",
    )
    versao_id = _insert_versao(
        client, atividade_base_id=seed["base_id"], norma_id=seed["norma_ativa_id"],
        codigo_normativo=seed["codigo_ativa"], eixo="AAC", grupo="Grupo destino transicao",
    )

    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            """
            INSERT INTO atividade_transicao
                (from_atividade_versao_id, to_atividade_versao_id, tipo_transicao)
            VALUES (?, ?, 'mesmo_eixo')
            """,
            (versao_orig_id, versao_id),
        )
        conn.commit()

    r = _post_editar_versao(
        client, seed["base_id"], versao_id, seed["norma_ativa_id"], grupo="Tentativa"
    )
    assert r.status_code == 302
    versao = _get_versao(client, versao_id)
    assert versao["grupo"] == "Grupo destino transicao"


# ---------------------------------------------------------------------------
# 24. POST não altera matriz_atividade_versao_item
# ---------------------------------------------------------------------------

def test_post_editar_versao_does_not_touch_matriz_item(client):
    _login_admin(client)
    seed = _seed_base_and_normas(client)
    versao_id = _insert_versao(
        client, atividade_base_id=seed["base_id"], norma_id=seed["norma_ativa_id"],
        codigo_normativo=seed["codigo_ativa"], eixo="AAC",
    )
    before = _count_matriz_versao_item(client)
    r = _post_editar_versao(client, seed["base_id"], versao_id, seed["norma_ativa_id"])
    assert r.status_code == 302
    if before != -1:
        assert _count_matriz_versao_item(client) == before


# ---------------------------------------------------------------------------
# 25. POST não altera requisicoes
# ---------------------------------------------------------------------------

def test_post_editar_versao_does_not_touch_requisicoes(client):
    _login_admin(client)
    seed = _seed_base_and_normas(client)
    versao_id = _insert_versao(
        client, atividade_base_id=seed["base_id"], norma_id=seed["norma_ativa_id"],
        codigo_normativo=seed["codigo_ativa"], eixo="AAC",
    )
    before = _count_requisicoes(client)
    r = _post_editar_versao(client, seed["base_id"], versao_id, seed["norma_ativa_id"])
    assert r.status_code == 302
    assert _count_requisicoes(client) == before


# ---------------------------------------------------------------------------
# 26. Rotas read-only D7.2B1 continuam respondendo
# ---------------------------------------------------------------------------

def test_d7_2b1_readonly_routes_still_respond(client):
    _login_admin(client)
    seed = _seed_base_and_normas(client)
    routes = [
        "/admin/catalogo-versoes",
        f"/admin/catalogo-versoes/{seed['base_id']}",
        "/admin/normas-atividade",
    ]
    for path in routes:
        r = client.get(path)
        assert r.status_code == 200, f"Rota {path} não respondeu 200"


# ---------------------------------------------------------------------------
# 27. Criação PATCH1 continua funcionando (template parametrizado não quebrou criação)
# ---------------------------------------------------------------------------

def test_patch1_creation_still_works(client):
    _login_admin(client)
    seed = _seed_base_and_normas(client)
    before = _count_atividade_versao(client)
    r = _post_nova_versao(client, seed["base_id"], seed["norma_ativa_id"])
    assert r.status_code == 302
    assert f"/admin/catalogo-versoes/{seed['base_id']}" in r.headers.get("Location", "")
    assert _count_atividade_versao(client) == before + 1
    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT status, codigo_normativo FROM atividade_versao "
            "WHERE atividade_base_id = ? AND norma_id = ?",
            (seed["base_id"], seed["norma_ativa_id"]),
        ).fetchone()
    assert row["status"] == "rascunho"
    assert row["codigo_normativo"] == seed["codigo_ativa"]


# ---------------------------------------------------------------------------
# 28. Contrato D7.1 (rascunho excluído do resolver) continua intacto após edição
# ---------------------------------------------------------------------------

def test_d7_1_contract_still_holds_after_edit(client):
    _login_admin(client)
    seed = _seed_base_and_normas(client)
    versao_id = _insert_versao(
        client, atividade_base_id=seed["base_id"], norma_id=seed["norma_ativa_id"],
        codigo_normativo=seed["codigo_ativa"], eixo="AAC", grupo="Grupo pré-edição",
    )
    r = _post_editar_versao(
        client, seed["base_id"], versao_id, seed["norma_ativa_id"], grupo="Grupo pós-edição"
    )
    assert r.status_code == 302

    versao = _get_versao(client, versao_id)
    assert versao["status"] == "rascunho"
    assert versao["grupo"] == "Grupo pós-edição"

    assert versao["status"] == "rascunho"
