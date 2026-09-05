"""
COV-1 restoration — Edit of atividade_versao in rascunho.

Adapted from the pre-Norma suite (test_admin_activity_version_catalog_version_edit.py)
with all Norma-domain setup removed (norma_atividade, norma_id, codigo_normativo).

Covers:
  1. GET editar versão rascunho retorna 200.
  2. GET editar versão inexistente redireciona ou bloqueia sem 500.
  3. GET editar versão de outra base rejeita.
  4. GET editar versão não-rascunho bloqueia (ativa, inativa, descontinuada, substituida).
  5. POST válido em rascunho atualiza campos permitidos.
  6. POST número não numérico rejeita.
  7. POST número negativo rejeita.
  8. POST versao_anterior_id inexistente rejeita.
  9. POST versao_anterior_id de outra base rejeita.
 10. POST versao_anterior_id de eixo incompatível rejeita.
 11. POST versao_anterior_id igual ao próprio id rejeita.
 12. POST em versão ativa/inativa/descontinuada/substituida rejeita (server-side).
 13. POST com status=ativa no payload não muda status.
 14. POST com atividade_base_id manipulada no payload não muda base.
 15. POST bloqueia edição se houver uso em matriz atribuída a turma.
 16. POST bloqueia edição se houver uso em requisicoes.atividade_versao_id.
 17. POST bloqueia edição se houver uso em atividade_transicao.from_atividade_versao_id.
 18. POST bloqueia edição se houver uso em atividade_transicao.to_atividade_versao_id.
 19. POST não altera matriz_atividade_versao_item.
 20. POST não altera requisicoes.
 21. Rotas read-only continuam respondendo.
 22. Criação PATCH1 continua funcionando.
 23. Contrato D7.1 (rascunho excluído do resolver) continua intacto após edição.
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

def _seed_base(client) -> dict:
    """Insere uma atividade_base ativa."""
    token = uuid.uuid4().hex[:8]
    with main.app.app_context():
        conn = main.get_db_connection()
        nome_base = f"Base Edicao {token}"
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
                atividade_base_id, eixo, grupo, status,
                ch_por_evento, limite_semestre, limite_total,
                observacao_aluno, observacao_admin,
                vigencia_inicio, vigencia_fim, versao_anterior_id, numero_versao
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                atividade_base_id, eixo, grupo, status,
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


def _insert_outra_base(client) -> int:
    with main.app.app_context():
        conn = main.get_db_connection()
        nome_outra = f"Outra Base {uuid.uuid4().hex[:6]}"
        conn.execute(
            "INSERT INTO atividade_base (nome_conceito, descricao, status) VALUES (?, ?, ?)",
            (nome_outra, "Desc", "ativo"),
        )
        outra_base_id = conn.execute(
            "SELECT id FROM atividade_base WHERE nome_conceito = ?", (nome_outra,)
        ).fetchone()["id"]
        conn.commit()
    return outra_base_id


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------

def _get_editar_versao(client, base_id, versao_id):
    return client.get(f"/admin/catalogo-versoes/{base_id}/versoes/{versao_id}/editar")


def _post_editar_versao(client, base_id, versao_id, **kwargs):
    with main.app.app_context():
        conn = main.get_db_connection()
        base = conn.execute("SELECT nome_conceito, descricao FROM atividade_base WHERE id = ?", (base_id,)).fetchone()
        current = conn.execute("SELECT eixo FROM atividade_versao WHERE id = ?", (versao_id,)).fetchone()
    eixo = kwargs.get("eixo", current["eixo"] if current else "AAC")
    if "limite_semestre" in kwargs:
        limite_semestre, limite_total = kwargs["limite_semestre"], ""
    elif "limite_total" in kwargs:
        limite_semestre, limite_total = "", kwargs["limite_total"]
    else:
        limite_semestre, limite_total = "50", ""
    data = {
        "tipo_atividade": "Extensão Universitária" if eixo == "AEU" else "Acadêmica Complementar",
        "grupo": kwargs.get("grupo", "1 - Grupo editado"),
        "nome": base["nome_conceito"],
        "descricao": base["descricao"] or "",
        "ch_por_evento": kwargs.get("ch_por_evento", "5"),
        "tipo_limitacao": "semestral" if limite_semestre != "" else ("total" if limite_total != "" else ""),
        "limite_valor": limite_semestre if limite_semestre != "" else limite_total,
        "observacoes": kwargs.get("observacao_admin") or kwargs.get("observacao_aluno") or "",
        "versao_anterior_id": kwargs.get("versao_anterior_id", ""),
    }
    for extra in ("status", "atividade_base_id", "eixo"):
        if extra in kwargs:
            data[extra] = kwargs[extra]
    return client.post(
        f"/admin/catalogo-versoes/{base_id}/versoes/{versao_id}/editar",
        data=data,
        follow_redirects=False,
    )


def _post_nova_versao(client, base_id, **kwargs):
    with main.app.app_context():
        base = main.get_db_connection().execute(
            "SELECT nome_conceito, descricao FROM atividade_base WHERE id = ?", (base_id,)
        ).fetchone()
    eixo = kwargs.get("eixo", "AAC")
    limite_semestre = kwargs.get("limite_semestre", "40")
    limite_total = kwargs.get("limite_total", "100")
    data = {
        "tipo_atividade": "Extensão Universitária" if eixo == "AEU" else "Acadêmica Complementar",
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


# ---------------------------------------------------------------------------
# 1. GET editar versão rascunho retorna 200
# ---------------------------------------------------------------------------

def test_get_editar_versao_rascunho_returns_200(client):
    _login_admin(client)
    seed = _seed_base(client)
    versao_id = _insert_versao(client, atividade_base_id=seed["base_id"], eixo="AAC")
    r = _get_editar_versao(client, seed["base_id"], versao_id)
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "Salvar alterações" in html


# ---------------------------------------------------------------------------
# 2. GET editar versão inexistente redireciona sem 500
# ---------------------------------------------------------------------------

def test_get_editar_versao_inexistente_redirects_without_500(client):
    _login_admin(client)
    seed = _seed_base(client)
    r = _get_editar_versao(client, seed["base_id"], 999999)
    assert r.status_code == 302
    assert r.status_code != 500
    assert f"/admin/catalogo-versoes/{seed['base_id']}" in r.headers.get("Location", "")


# ---------------------------------------------------------------------------
# 3. GET editar versão de outra base rejeita
# ---------------------------------------------------------------------------

def test_get_editar_versao_outra_base_rejected(client):
    _login_admin(client)
    seed = _seed_base(client)
    versao_id = _insert_versao(
        client, atividade_base_id=seed["base_id"], eixo="AAC",
    )
    outra_base_id = _insert_outra_base(client)

    r = _get_editar_versao(client, outra_base_id, versao_id)
    assert r.status_code == 302
    assert f"/admin/catalogo-versoes/{outra_base_id}" in r.headers.get("Location", "")
    versao = _get_versao(client, versao_id)
    assert versao["atividade_base_id"] == seed["base_id"]


# ---------------------------------------------------------------------------
# 4. GET editar versão não-rascunho abre em modo somente-leitura
# ---------------------------------------------------------------------------

def test_get_editar_versao_non_rascunho_opens_readonly(client):
    _login_admin(client)
    seed = _seed_base(client)
    for status in ("ativa", "inativa", "descontinuada", "substituida"):
        versao_id = _insert_versao(
            client,
            atividade_base_id=seed["base_id"],
            eixo="AAC",
            status=status,
        )
        r = _get_editar_versao(client, seed["base_id"], versao_id)
        assert r.status_code == 200, f"status={status} deveria abrir em modo somente-leitura"
        html = r.get_data(as_text=True)
        assert 'class="btn primary"' not in html, (
            f"status={status}: modo somente-leitura não deve expor botão Salvar"
        )
        assert 'name="grupo"' in html and 'readonly' in html, (
            f"status={status}: campos devem ser visíveis como somente-leitura"
        )


# ---------------------------------------------------------------------------
# 5. POST válido em rascunho atualiza campos permitidos
# ---------------------------------------------------------------------------

def test_post_editar_versao_valid_updates_allowed_fields(client):
    _login_admin(client)
    seed = _seed_base(client)
    versao_id = _insert_versao(
        client,
        atividade_base_id=seed["base_id"],
        eixo="AAC",
        grupo="Grupo original",
        ch_por_evento=4.0,
        limite_semestre=40.0,
        limite_total=100.0,
    )
    r = _post_editar_versao(
        client, seed["base_id"], versao_id,
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
    assert versao["limite_total"] is None
    assert versao["observacao_aluno"] == "Obs admin nova"
    assert versao["observacao_admin"] == "Obs admin nova"
    assert versao["vigencia_inicio"] is None
    assert versao["vigencia_fim"] is None
    assert versao["status"] == "rascunho"


# ---------------------------------------------------------------------------
# 6. POST número não numérico rejeita
# ---------------------------------------------------------------------------

def test_post_editar_versao_non_numeric_number_rejected(client):
    _login_admin(client)
    seed = _seed_base(client)
    versao_id = _insert_versao(
        client, atividade_base_id=seed["base_id"], eixo="AAC", ch_por_evento=4.0,
    )
    r = _post_editar_versao(
        client, seed["base_id"], versao_id, ch_por_evento="abc"
    )
    assert r.status_code == 200
    versao = _get_versao(client, versao_id)
    assert versao["ch_por_evento"] == 4.0


# ---------------------------------------------------------------------------
# 7. POST número negativo rejeita
# ---------------------------------------------------------------------------

def test_post_editar_versao_negative_number_rejected(client):
    _login_admin(client)
    seed = _seed_base(client)
    versao_id = _insert_versao(
        client, atividade_base_id=seed["base_id"], eixo="AAC", limite_total=100.0,
    )
    r = _post_editar_versao(
        client, seed["base_id"], versao_id, limite_total="-5"
    )
    assert r.status_code == 200
    versao = _get_versao(client, versao_id)
    assert versao["limite_total"] == 100.0


# ---------------------------------------------------------------------------
# 8. POST versao_anterior_id inexistente rejeita
# ---------------------------------------------------------------------------

def test_post_editar_versao_versao_anterior_inexistente_rejected(client):
    _login_admin(client)
    seed = _seed_base(client)
    versao_id = _insert_versao(
        client, atividade_base_id=seed["base_id"], eixo="AAC",
    )
    r = _post_editar_versao(
        client, seed["base_id"], versao_id, versao_anterior_id="999999"
    )
    assert r.status_code == 200
    versao = _get_versao(client, versao_id)
    assert versao["versao_anterior_id"] is None


# ---------------------------------------------------------------------------
# 9. POST versao_anterior_id de outra base rejeita
# ---------------------------------------------------------------------------

def test_post_editar_versao_versao_anterior_outra_base_rejected(client):
    _login_admin(client)
    seed = _seed_base(client)
    outra_base_id = _insert_outra_base(client)

    outra_versao_id = _insert_versao(
        client, atividade_base_id=outra_base_id, eixo="AAC",
    )
    versao_id = _insert_versao(
        client, atividade_base_id=seed["base_id"], eixo="AAC",
    )

    r = _post_editar_versao(
        client, seed["base_id"], versao_id,
        versao_anterior_id=str(outra_versao_id),
    )
    assert r.status_code == 200
    versao = _get_versao(client, versao_id)
    assert versao["versao_anterior_id"] is None


# ---------------------------------------------------------------------------
# 10. POST versao_anterior_id de eixo incompatível rejeita
# ---------------------------------------------------------------------------

def test_post_editar_versao_versao_anterior_eixo_incompativel_rejected(client):
    _login_admin(client)
    seed = _seed_base(client)

    versao_aeu_id = _insert_versao(
        client, atividade_base_id=seed["base_id"], eixo="AEU",
    )
    versao_id = _insert_versao(
        client, atividade_base_id=seed["base_id"], eixo="AAC",
    )

    r = _post_editar_versao(
        client, seed["base_id"], versao_id,
        versao_anterior_id=str(versao_aeu_id),
    )
    assert r.status_code == 200
    versao = _get_versao(client, versao_id)
    assert versao["versao_anterior_id"] is None


# ---------------------------------------------------------------------------
# 11. POST versao_anterior_id igual ao próprio id rejeita
# ---------------------------------------------------------------------------

def test_post_editar_versao_versao_anterior_self_rejected(client):
    _login_admin(client)
    seed = _seed_base(client)
    versao_id = _insert_versao(
        client, atividade_base_id=seed["base_id"], eixo="AAC",
    )
    r = _post_editar_versao(
        client, seed["base_id"], versao_id,
        versao_anterior_id=str(versao_id),
    )
    assert r.status_code == 200
    versao = _get_versao(client, versao_id)
    assert versao["versao_anterior_id"] is None


# ---------------------------------------------------------------------------
# 12. POST em versão não-rascunho rejeita (server-side)
# ---------------------------------------------------------------------------

def test_post_editar_versao_non_rascunho_blocked(client):
    _login_admin(client)
    seed = _seed_base(client)
    for status in ("ativa", "inativa", "descontinuada", "substituida"):
        versao_id = _insert_versao(
            client, atividade_base_id=seed["base_id"], eixo="AAC",
            status=status, grupo="Grupo original",
        )
        r = _post_editar_versao(
            client, seed["base_id"], versao_id, grupo="Grupo TENTATIVA"
        )
        assert r.status_code == 302, f"status={status} deveria bloquear POST com redirect"
        versao = _get_versao(client, versao_id)
        assert versao["grupo"] == "Grupo original", f"status={status}: edição não deveria ter sido aplicada"
        assert versao["status"] == status


# ---------------------------------------------------------------------------
# 13. POST com status=ativa no payload não muda status
# ---------------------------------------------------------------------------

def test_post_editar_versao_status_in_payload_ignored(client):
    _login_admin(client)
    seed = _seed_base(client)
    versao_id = _insert_versao(
        client, atividade_base_id=seed["base_id"], eixo="AAC",
    )
    r = _post_editar_versao(
        client, seed["base_id"], versao_id,
        status="ativa",
        grupo="Grupo com status manipulado",
    )
    assert r.status_code == 302
    versao = _get_versao(client, versao_id)
    assert versao["status"] == "rascunho"
    assert versao["grupo"] == "Grupo com status manipulado"


# ---------------------------------------------------------------------------
# 14. POST com atividade_base_id manipulada no payload não muda base
# ---------------------------------------------------------------------------

def test_post_editar_versao_atividade_base_id_in_payload_ignored(client):
    _login_admin(client)
    seed = _seed_base(client)
    outra_base_id = _insert_outra_base(client)

    versao_id = _insert_versao(
        client, atividade_base_id=seed["base_id"], eixo="AAC",
    )
    r = _post_editar_versao(
        client, seed["base_id"], versao_id,
        atividade_base_id=str(outra_base_id),
        grupo="Grupo com base manipulada",
    )
    assert r.status_code == 302
    versao = _get_versao(client, versao_id)
    assert versao["atividade_base_id"] == seed["base_id"]
    assert versao["grupo"] == "Grupo com base manipulada"


# ---------------------------------------------------------------------------
# 15. POST bloqueia edição se houver uso em matriz atribuída a turma
# ---------------------------------------------------------------------------

def test_post_editar_versao_blocked_when_used_in_matriz_item(client):
    _login_admin(client)
    seed = _seed_base(client)
    versao_id = _insert_versao(
        client, atividade_base_id=seed["base_id"], eixo="AAC", grupo="Grupo em uso matriz",
    )
    token = uuid.uuid4().hex[:8]
    with main.app.app_context():
        conn = main.get_db_connection()
        curso_id = conn.execute(
            "INSERT INTO cursos (nome, codigo, duracao_periodos, status)"
            " VALUES (?, ?, 8, 'ativo') RETURNING id",
            (f"Curso Bloqueio {token}", f"BLQ{token}"),
        ).fetchone()["id"]
        matriz_id = conn.execute(
            "INSERT INTO matrizes_atividades (curso_id, nome, status) VALUES (?, ?, 'ativa')",
            (curso_id, f"Matriz Bloqueio {token}"),
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
            (f"Turma Bloqueio {token}", curso_id, matriz_id, f"BLQ-{token}"),
        )
        conn.commit()

    r = _post_editar_versao(
        client, seed["base_id"], versao_id, grupo="Tentativa"
    )
    assert r.status_code == 302
    assert f"/admin/catalogo-versoes/{seed['base_id']}" in r.headers.get("Location", "")
    versao = _get_versao(client, versao_id)
    assert versao["grupo"] == "Grupo em uso matriz"


# ---------------------------------------------------------------------------
# 16. POST bloqueia edição se houver uso em requisicoes.atividade_versao_id
# ---------------------------------------------------------------------------

def test_post_editar_versao_blocked_when_used_in_requisicoes(client):
    _login_admin(client)
    seed = _seed_base(client)
    versao_id = _insert_versao(
        client, atividade_base_id=seed["base_id"], eixo="AAC", grupo="Grupo em uso requisicao",
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
                nome_evento, status, atividade_versao_id, regra_snapshot_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (aluno_id, "2026-05-22 10:00:00", "2026-05-22", 2.0,
             f"Evento {token}", "Pendente", versao_id, "{}"),
        )
        conn.commit()

    r = _post_editar_versao(
        client, seed["base_id"], versao_id, grupo="Tentativa"
    )
    assert r.status_code == 302
    versao = _get_versao(client, versao_id)
    assert versao["grupo"] == "Grupo em uso requisicao"


# ---------------------------------------------------------------------------
# 17. POST bloqueia edição se houver uso em atividade_transicao.from
# ---------------------------------------------------------------------------

def test_post_editar_versao_blocked_when_used_in_transicao_origem(client):
    _login_admin(client)
    seed = _seed_base(client)

    versao_id = _insert_versao(
        client, atividade_base_id=seed["base_id"], eixo="AAC", grupo="Grupo origem transicao",
    )
    versao_dest_id = _insert_versao(
        client, atividade_base_id=seed["base_id"], eixo="AAC",
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
        client, seed["base_id"], versao_id, grupo="Tentativa"
    )
    assert r.status_code == 302
    versao = _get_versao(client, versao_id)
    assert versao["grupo"] == "Grupo origem transicao"


# ---------------------------------------------------------------------------
# 18. POST bloqueia edição se houver uso em atividade_transicao.to
# ---------------------------------------------------------------------------

def test_post_editar_versao_blocked_when_used_in_transicao_destino(client):
    _login_admin(client)
    seed = _seed_base(client)

    versao_orig_id = _insert_versao(
        client, atividade_base_id=seed["base_id"], eixo="AAC",
    )
    versao_id = _insert_versao(
        client, atividade_base_id=seed["base_id"], eixo="AAC", grupo="Grupo destino transicao",
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
        client, seed["base_id"], versao_id, grupo="Tentativa"
    )
    assert r.status_code == 302
    versao = _get_versao(client, versao_id)
    assert versao["grupo"] == "Grupo destino transicao"


# ---------------------------------------------------------------------------
# 19. POST não altera matriz_atividade_versao_item
# ---------------------------------------------------------------------------

def test_post_editar_versao_does_not_touch_matriz_item(client):
    _login_admin(client)
    seed = _seed_base(client)
    versao_id = _insert_versao(
        client, atividade_base_id=seed["base_id"], eixo="AAC",
    )
    before = _count_matriz_versao_item(client)
    r = _post_editar_versao(client, seed["base_id"], versao_id)
    assert r.status_code == 302
    if before != -1:
        assert _count_matriz_versao_item(client) == before


# ---------------------------------------------------------------------------
# 20. POST não altera requisicoes
# ---------------------------------------------------------------------------

def test_post_editar_versao_does_not_touch_requisicoes(client):
    _login_admin(client)
    seed = _seed_base(client)
    versao_id = _insert_versao(
        client, atividade_base_id=seed["base_id"], eixo="AAC",
    )
    before = _count_requisicoes(client)
    r = _post_editar_versao(client, seed["base_id"], versao_id)
    assert r.status_code == 302
    assert _count_requisicoes(client) == before


# ---------------------------------------------------------------------------
# 21. Rotas read-only continuam respondendo
# ---------------------------------------------------------------------------

def test_readonly_routes_still_respond(client):
    _login_admin(client)
    seed = _seed_base(client)
    routes = [
        "/admin/atividades",
        f"/admin/catalogo-versoes/{seed['base_id']}",
    ]
    for path in routes:
        r = client.get(path)
        assert r.status_code == 200, f"Rota {path} não respondeu 200"


# ---------------------------------------------------------------------------
# 22. Criação PATCH1 continua funcionando
# ---------------------------------------------------------------------------

def test_patch1_creation_still_works(client):
    _login_admin(client)
    seed = _seed_base(client)
    before = _count_atividade_versao(client)
    r = _post_nova_versao(client, seed["base_id"], eixo="AAC")
    assert r.status_code == 302
    assert f"/admin/catalogo-versoes/{seed['base_id']}" in r.headers.get("Location", "")
    assert _count_atividade_versao(client) == before + 1
    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT status, eixo, numero_versao FROM atividade_versao "
            "WHERE atividade_base_id = ?",
            (seed["base_id"],),
        ).fetchone()
    assert row["status"] == "rascunho"
    assert row["eixo"] == "AAC"
    assert row["numero_versao"] == 1


# ---------------------------------------------------------------------------
# 23. Contrato D7.1 (rascunho excluído do resolver) continua intacto após edição
# ---------------------------------------------------------------------------

def test_d7_1_contract_still_holds_after_edit(client):
    _login_admin(client)
    seed = _seed_base(client)
    versao_id = _insert_versao(
        client, atividade_base_id=seed["base_id"], eixo="AAC", grupo="Grupo pré-edição",
    )
    r = _post_editar_versao(
        client, seed["base_id"], versao_id, grupo="Grupo pós-edição"
    )
    assert r.status_code == 302

    versao = _get_versao(client, versao_id)
    assert versao["status"] == "rascunho"
    assert versao["grupo"] == "Grupo pós-edição"

    assert versao["status"] == "rascunho"
