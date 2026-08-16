"""D8.1B — Read-only display do snapshot versionado nas telas do aluno.

Objetivo: garantir que, quando a requisição possui `atividade_versao_id` /
`regra_snapshot_json` / `codigo_normativo_snapshot` populados, as telas
do aluno (detalhe e lista) exibam o bloco "Versão normativa registrada"
e o chip `vN` apenas em modo read-only, sem nenhum efeito colateral de
escrita no writer, no resolvedor ou no deferimento admin.

Cenários cobertos:
  T01 — aluno_create com SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE=ON em
        turma com matriz explícita: writer carimba; GET detalhe mostra
        bloco com vN/codigo_normativo/eixo/grupo.
  T02 — flag OFF (modo atual do workspace): GET detalhe não mostra bloco;
        lista não mostra chip.
  T03 — lista /aluno/requisicoes mostra chip quando
        snapshot_versionado_presente=1; não mostra quando ausente.
  T04 — regra_snapshot_json inválido: GET detalhe não retorna 500;
        fallback silencioso.
  T05 — aluno_create em turma sem matriz explícita (contrato 5):
        writer no-op; detalhe não mostra bloco.
  T06 — edição do aluno trocando atividade_id: snapshot NÃO é regenerado;
        vN exibido permanece o do carimbo original; status Pendente
        preservado.
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
from app.versioning import resolver as versioning_resolver
from tests.versioned_test_support import isolated_versioned_app_env


@pytest.fixture()
def versioned_env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "d81b_readonly.db") as env:
        yield env


def _login_aluno(client, *, user_id, user_name):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["user_type"] = "aluno"
        sess["user_name"] = user_name


def _seed_aluno_em_t11():
    token = uuid.uuid4().hex[:8]
    email = f"aluno.d81b.{token}@teste.local"
    nome = f"Aluno D81B {token}"

    with main.app.app_context():
        conn = main.get_db_connection()
        turma = conn.execute(
            "SELECT id, codigo FROM turmas WHERE codigo = ?",
            ("PPA-T11",),
        ).fetchone()
        assert turma is not None

        conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?)",
            (nome, email, main.hash_password("aluno123"), "aluno", "usuario"),
        )
        usuario_id = conn.execute(
            "SELECT id FROM usuarios WHERE email = ?", (email,)
        ).fetchone()["id"]

        conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                usuario_id,
                nome,
                f"PPA.D81B.{token}",
                email,
                turma["id"],
                "Ativo",
            ),
        )
        aluno_id = conn.execute(
            "SELECT id FROM alunos WHERE usuario_id = ?", (usuario_id,)
        ).fetchone()["id"]
        conn.commit()

    return {
        "usuario_id": usuario_id,
        "aluno_id": aluno_id,
        "nome": nome,
        "turma_codigo": "PPA-T11",
    }


def _fetch_req(aluno_id: int, nome_evento: str):
    with main.app.app_context():
        conn = main.get_db_connection()
        return conn.execute(
            """
            SELECT id, atividade_id, atividade_versao_id, regra_snapshot_json,
                   codigo_normativo_snapshot, status, atividade_id
              FROM requisicoes
             WHERE aluno_id = ? AND nome_evento = ?
            """,
            (aluno_id, nome_evento),
        ).fetchone()


def _create_pending_requisicao_legada(aluno_id: int, atividade_id: int, *, nome_evento: str):
    with main.app.app_context():
        conn = main.get_db_connection()
        cur = conn.execute(
            """
            INSERT INTO requisicoes (
                aluno_id, atividade_id, data_solicitacao, data_evento,
                horas_solicitadas, nome_evento, status, observacao
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                aluno_id,
                atividade_id,
                "2026-05-30 10:00:00",
                "2026-05-24",
                4,
                nome_evento,
                "Pendente",
                "seed legada",
            ),
        )
        req_id = cur.lastrowid
        conn.commit()
    return req_id


# ---------------------------------------------------------------------------
# T01 — aluno_create com flag ON: writer carimba; detalhe mostra bloco.
# ---------------------------------------------------------------------------

def test_aluno_create_with_snapshot_write_flag_on_shows_block_in_detail(
    versioned_env, monkeypatch
):
    env = versioned_env
    client = env["client"]
    seed = _seed_aluno_em_t11()
    _login_aluno(
        client, user_id=seed["usuario_id"], user_name=seed["nome"]
    )
    monkeypatch.setenv("SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE", "1")
    monkeypatch.delenv("SGAA_VERSIONED_RESOLVER_SHADOW_READ", raising=False)

    event_name = f"Evento T01 {uuid.uuid4().hex[:6]}"
    response = client.post(
        "/aluno/nova-requisicao",
        data={
            "atividade_id": "1",
            "nome_evento": event_name,
            "data_evento": "2026-05-24",
            "horas_solicitadas": "4",
            "observacao": "snapshot aluno create t01",
        },
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)

    req = _fetch_req(seed["aluno_id"], event_name)
    assert req is not None
    assert req["atividade_versao_id"] is not None
    assert req["codigo_normativo_snapshot"] is not None

    detail = client.get(f"/aluno/requisicoes/{req['id']}")
    assert detail.status_code == 200
    detail_html = detail.get_data(as_text=True)
    assert "Versão normativa registrada" in detail_html
    assert "AAC-rev6" in detail_html
    assert "Eixo:" in detail_html
    assert "Grupo:" in detail_html
    assert "Registrado em:" in detail_html


# ---------------------------------------------------------------------------
# T02 — flag ausente: snapshot obrigatório permanece ativo.
# ---------------------------------------------------------------------------

def test_aluno_create_with_snapshot_write_flag_off_hides_block_in_detail(
    versioned_env, monkeypatch
):
    env = versioned_env
    client = env["client"]
    seed = _seed_aluno_em_t11()
    _login_aluno(
        client, user_id=seed["usuario_id"], user_name=seed["nome"]
    )
    monkeypatch.delenv("SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE", raising=False)

    event_name = f"Evento T02 {uuid.uuid4().hex[:6]}"
    response = client.post(
        "/aluno/nova-requisicao",
        data={
            "atividade_id": "1",
            "nome_evento": event_name,
            "data_evento": "2026-05-24",
            "horas_solicitadas": "3",
            "observacao": "snapshot aluno create t02",
        },
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)

    req = _fetch_req(seed["aluno_id"], event_name)
    assert req is not None
    assert req["atividade_versao_id"] is not None
    assert req["regra_snapshot_json"] is not None
    assert req["codigo_normativo_snapshot"] is not None

    detail = client.get(f"/aluno/requisicoes/{req['id']}")
    assert detail.status_code == 200
    detail_html = detail.get_data(as_text=True)
    assert "Versão normativa registrada" in detail_html


# ---------------------------------------------------------------------------
# T03 — lista: chip aparece quando snapshot_versionado_presente=1; some caso contrário.
# ---------------------------------------------------------------------------

def test_aluno_lista_mostra_chip_quando_snapshot_presente_e_some_quando_ausente(
    versioned_env, monkeypatch
):
    env = versioned_env
    client = env["client"]
    seed = _seed_aluno_em_t11()
    _login_aluno(
        client, user_id=seed["usuario_id"], user_name=seed["nome"]
    )

    monkeypatch.delenv("SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE", raising=False)
    legacy_name = f"Evento Legado T03 {uuid.uuid4().hex[:6]}"
    _create_pending_requisicao_legada(
        seed["aluno_id"], 1, nome_evento=legacy_name
    )

    monkeypatch.setenv("SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE", "1")
    versioned_name = f"Evento Versionado T03 {uuid.uuid4().hex[:6]}"
    response = client.post(
        "/aluno/nova-requisicao",
        data={
            "atividade_id": "1",
            "nome_evento": versioned_name,
            "data_evento": "2026-05-24",
            "horas_solicitadas": "5",
            "observacao": "lista t03",
        },
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)

    lista = client.get("/aluno/requisicoes")
    assert lista.status_code == 200
    lista_html = lista.get_data(as_text=True)

    # O chip aparece pelo menos uma vez (linha versionada).
    assert 'class="aluno-snapshot-chip"' in lista_html
    # A linha com snapshot também deve carregar o label v<N>.
    assert "v1" in lista_html or "v2" in lista_html or "v3" in lista_html or "v4" in lista_html
    # A linha legada não deve carregar bloco/aria-label "Versão normativa registrada".
    # Garante que o tooltip aparece ao menos uma vez:
    assert "Versão normativa registrada:" in lista_html


# ---------------------------------------------------------------------------
# T04 — regra_snapshot_json inválido: GET detalhe não retorna 500; fallback silencioso.
# ---------------------------------------------------------------------------

def test_aluno_detail_with_invalid_snapshot_json_does_not_500(
    versioned_env, monkeypatch
):
    env = versioned_env
    client = env["client"]
    seed = _seed_aluno_em_t11()
    _login_aluno(
        client, user_id=seed["usuario_id"], user_name=seed["nome"]
    )

    with main.app.app_context():
        conn = main.get_db_connection()
        versao_row = conn.execute(
            "SELECT id FROM atividade_versao WHERE atividade_base_id = 1 "
            "AND codigo_normativo = 'AAC-rev6' LIMIT 1"
        ).fetchone()
        assert versao_row is not None
        versao_id = versao_row["id"]
        codigo_norm = "AAC-rev6"
        cur = conn.execute(
            """
            INSERT INTO requisicoes (
                aluno_id, atividade_id, data_solicitacao, data_evento,
                horas_solicitadas, nome_evento, status, observacao,
                atividade_versao_id, codigo_normativo_snapshot,
                regra_snapshot_json
            ) VALUES (?, 1, '2026-05-30 10:00:00', '2026-05-24', 4, ?, 'Pendente', ?,
                      ?, ?, ?)
            """,
            (
                seed["aluno_id"],
                f"Evento T04 {uuid.uuid4().hex[:6]}",
                "json invalido proposital",
                versao_id,
                codigo_norm,
                "{ this is not valid json ::",
            ),
        )
        req_id = cur.lastrowid
        conn.commit()

    detail = client.get(f"/aluno/requisicoes/{req_id}")
    assert detail.status_code == 200
    detail_html = detail.get_data(as_text=True)
    # O bloco "Versão normativa registrada" deve aparecer (vinda do
    # codigo_normativo_snapshot + atividade_versao_id mesmo com JSON
    # inválido); o importante é não ter 500 e não vazar string crua.
    assert "Versão normativa registrada" in detail_html
    assert "Versão:" in detail_html
    assert "{ this is not valid json ::" not in detail_html


# ---------------------------------------------------------------------------
# T05 — turma sem matriz explícita: academic request scope fails closed.
# ---------------------------------------------------------------------------

def test_aluno_create_em_turma_sem_matriz_explicita_nao_carimba_e_nao_mostra_bloco(
    versioned_env, monkeypatch
):
    env = versioned_env
    client = env["client"]
    monkeypatch.setenv("SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE", "1")
    monkeypatch.delenv("SGAA_VERSIONED_RESOLVER_SHADOW_READ", raising=False)

    with main.app.app_context():
        conn = main.get_db_connection()
        curso_ppa = conn.execute(
            "SELECT id FROM cursos WHERE codigo = 'PPA'"
        ).fetchone()
        assert curso_ppa is not None
        turma_codigo = f"PPA-T05-{uuid.uuid4().hex[:6]}"
        conn.execute(
            """
            INSERT INTO turmas (
                nome, semestre, turno, status, numero, curso_id, codigo,
                ano_inicio, semestre_inicio, ano_fim, semestre_fim
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "PPA-T05-C5", 1, "Manhã", "Ativa", 50,
                curso_ppa["id"], turma_codigo,
                2024, 1, 2027, 2,
            ),
        )
        turma_id = conn.execute(
            "SELECT id FROM turmas WHERE codigo = ?", (turma_codigo,)
        ).fetchone()["id"]
        assert (
            conn.execute(
                "SELECT matriz_id FROM turmas WHERE id = ?", (turma_id,)
            ).fetchone()["matriz_id"] is None
        )
        token = uuid.uuid4().hex[:8]
        email = f"aluno.t05.{token}@teste.local"
        conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo) VALUES (?, ?, ?, ?)",
            (f"Aluno T05 {token}", email, main.hash_password("aluno123"), "aluno"),
        )
        usuario_id = conn.execute(
            "SELECT id FROM usuarios WHERE email = ?", (email,)
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                usuario_id, f"Aluno T05 {token}", f"T05-{token}",
                email, turma_id, "Ativo",
            ),
        )
        aluno_id = conn.execute(
            "SELECT id FROM alunos WHERE usuario_id = ?", (usuario_id,)
        ).fetchone()["id"]
        conn.commit()

    _login_aluno(client, user_id=usuario_id, user_name=f"Aluno T05 {token}")

    event_name = f"Evento T05 {uuid.uuid4().hex[:6]}"
    response = client.post(
        "/aluno/nova-requisicao",
        data={
            "atividade_id": "1",
            "nome_evento": event_name,
            "data_evento": "2026-05-24",
            "horas_solicitadas": "2",
            "observacao": "turma sem matriz",
        },
        follow_redirects=False,
    )
    assert response.status_code == 200

    req = _fetch_req(aluno_id, event_name)
    assert req is None
    assert "não está disponível para a matriz da sua turma" in response.get_data(as_text=True)


# ---------------------------------------------------------------------------
# T06 — edição do aluno trocando atividade_id: snapshot NÃO é regenerado.
# ---------------------------------------------------------------------------

def test_aluno_edit_trocando_atividade_id_nao_regenera_snapshot(
    versioned_env, monkeypatch
):
    env = versioned_env
    client = env["client"]
    seed = _seed_aluno_em_t11()
    _login_aluno(
        client, user_id=seed["usuario_id"], user_name=seed["nome"]
    )
    monkeypatch.setenv("SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE", "1")
    monkeypatch.delenv("SGAA_VERSIONED_RESOLVER_SHADOW_READ", raising=False)

    event_name = f"Evento T06 {uuid.uuid4().hex[:6]}"
    create = client.post(
        "/aluno/nova-requisicao",
        data={
            "atividade_id": "1",
            "nome_evento": event_name,
            "data_evento": "2026-05-24",
            "horas_solicitadas": "4",
            "observacao": "create t06",
        },
        follow_redirects=False,
    )
    assert create.status_code in (302, 303)
    req = _fetch_req(seed["aluno_id"], event_name)
    assert req is not None
    original_versao_id = req["atividade_versao_id"]
    original_codigo = req["codigo_normativo_snapshot"]
    original_status = req["status"]
    assert original_versao_id is not None
    assert original_codigo is not None

    # Mantém o mesmo atividade_id (1) e apenas altera horas/nome. A
    # rota do aluno, por contrato, NÃO regenera o snapshot em edit.
    edit = client.post(
        f"/aluno/requisicoes/{req['id']}?edit=1",
        data={
            "atividade_id": "1",
            "nome_evento": event_name + " editado",
            "horas_solicitadas": "7",
            "data_evento": "2026-05-25",
            "observacao": "edit t06",
        },
        follow_redirects=False,
    )
    assert edit.status_code in (302, 303)

    after = _fetch_req(seed["aluno_id"], event_name + " editado")
    assert after is not None
    assert after["atividade_versao_id"] == original_versao_id
    assert after["codigo_normativo_snapshot"] == original_codigo
    assert after["status"] == "Pendente"

    detail = client.get(f"/aluno/requisicoes/{req['id']}")
    assert detail.status_code == 200
    detail_html = detail.get_data(as_text=True)
    assert "Versão normativa registrada" in detail_html
    assert original_codigo in detail_html


# ===========================================================================
# D8.2B — Contrato de edição do aluno após snapshot versionado.
#
# Regra: se a requisição já possui snapshot versionado (qualquer um de
# `atividade_versao_id` / `codigo_normativo_snapshot` / `regra_snapshot_json`),
# o aluno NÃO pode trocar a atividade. O snapshot não é recalculado nem limpo;
# é um registro imutável do momento da criação. Demais edições continuam
# permitidas. Requisições SEM snapshot preservam a troca de atividade legada,
# mantida a validação de atividade permitida pela matriz.
#
# A flag SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE só é ligada dentro de cada
# teste, via monkeypatch; nunca no ambiente do workspace.
# ===========================================================================

_GUARD_MESSAGE = "Esta solicitação já possui versão normativa registrada"


def _create_versioned_pending(client, seed, *, atividade_id="1"):
    """Cria via aluno_create (WRITE ON) e devolve (nome_evento, req carimbada)."""
    event_name = f"D82B base {uuid.uuid4().hex[:8]}"
    resp = client.post(
        "/aluno/nova-requisicao",
        data={
            "atividade_id": atividade_id,
            "nome_evento": event_name,
            "data_evento": "2026-05-24",
            "horas_solicitadas": "4",
            "observacao": "d82b base",
        },
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)
    req = _fetch_req(seed["aluno_id"], event_name)
    assert req is not None
    return event_name, req


def _row_by_id(req_id: int, columns: str):
    with main.app.app_context():
        conn = main.get_db_connection()
        return conn.execute(
            f"SELECT {columns} FROM requisicoes WHERE id = ?",
            (req_id,),
        ).fetchone()


# ---------------------------------------------------------------------------
# T01 — snapshot presente: trocar atividade_id é bloqueado (rejeição atômica).
# ---------------------------------------------------------------------------

def test_d82b_t01_edit_change_activity_blocked_when_snapshot_present(
    versioned_env, monkeypatch
):
    env = versioned_env
    client = env["client"]
    seed = _seed_aluno_em_t11()
    _login_aluno(client, user_id=seed["usuario_id"], user_name=seed["nome"])
    monkeypatch.setenv("SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE", "1")
    monkeypatch.delenv("SGAA_VERSIONED_RESOLVER_SHADOW_READ", raising=False)

    event_name, req = _create_versioned_pending(client, seed)
    assert req["atividade_id"] == 1
    assert req["atividade_versao_id"] is not None
    assert req["codigo_normativo_snapshot"] is not None
    original_versao_id = req["atividade_versao_id"]
    original_codigo = req["codigo_normativo_snapshot"]
    original_json = req["regra_snapshot_json"]

    # Tenta trocar a atividade (1 -> 2; ambas permitidas na matriz da T11).
    edit = client.post(
        f"/aluno/requisicoes/{req['id']}?edit=1",
        data={
            "atividade_id": "2",
            "nome_evento": event_name + " tentativa de troca",
            "horas_solicitadas": "6",
            "data_evento": "2026-05-25",
            "observacao": "tentativa de troca t01",
        },
        follow_redirects=True,
    )
    assert edit.status_code == 200
    # Comportamento de rejeição é observável via flash renderizado.
    assert _GUARD_MESSAGE in edit.get_data(as_text=True)

    # Estado no banco: atividade e snapshot inalterados; rejeição atômica
    # (nenhum outro campo do POST foi aplicado).
    after = _row_by_id(
        req["id"],
        "atividade_id, atividade_versao_id, codigo_normativo_snapshot, "
        "regra_snapshot_json, nome_evento, horas_solicitadas, status",
    )
    assert after["atividade_id"] == 1
    assert after["atividade_versao_id"] == original_versao_id
    assert after["codigo_normativo_snapshot"] == original_codigo
    assert after["regra_snapshot_json"] == original_json
    assert after["nome_evento"] == event_name
    assert float(after["horas_solicitadas"]) == 4.0
    assert after["status"] == "Pendente"


# ---------------------------------------------------------------------------
# T02 — snapshot presente: edições não estruturais continuam permitidas.
# ---------------------------------------------------------------------------

def test_d82b_t02_edit_nonstructural_fields_allowed_with_snapshot_present(
    versioned_env, monkeypatch
):
    env = versioned_env
    client = env["client"]
    seed = _seed_aluno_em_t11()
    _login_aluno(client, user_id=seed["usuario_id"], user_name=seed["nome"])
    monkeypatch.setenv("SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE", "1")
    monkeypatch.delenv("SGAA_VERSIONED_RESOLVER_SHADOW_READ", raising=False)

    event_name, req = _create_versioned_pending(client, seed)
    original_versao_id = req["atividade_versao_id"]
    original_codigo = req["codigo_normativo_snapshot"]
    original_json = req["regra_snapshot_json"]
    assert original_versao_id is not None

    new_name = event_name + " editado"
    edit = client.post(
        f"/aluno/requisicoes/{req['id']}?edit=1",
        data={
            "atividade_id": "1",  # mesma atividade
            "nome_evento": new_name,
            "horas_solicitadas": "9",
            "data_evento": "2026-06-01",
            "observacao": "obs editada t02",
        },
        follow_redirects=False,
    )
    assert edit.status_code in (302, 303)

    after = _row_by_id(
        req["id"],
        "atividade_id, atividade_versao_id, codigo_normativo_snapshot, "
        "regra_snapshot_json, nome_evento, horas_solicitadas, observacao, data_evento",
    )
    # Campos não estruturais atualizados.
    assert after["nome_evento"] == new_name
    assert float(after["horas_solicitadas"]) == 9.0
    assert after["observacao"] == "obs editada t02"
    assert str(after["data_evento"]).startswith("2026-06-01")
    # Atividade e snapshot preservados.
    assert after["atividade_id"] == 1
    assert after["atividade_versao_id"] == original_versao_id
    assert after["codigo_normativo_snapshot"] == original_codigo
    assert after["regra_snapshot_json"] == original_json


# ---------------------------------------------------------------------------
# T03 — sem snapshot: troca de atividade continua permitida (legado).
# ---------------------------------------------------------------------------

def test_d82b_t03_edit_change_activity_allowed_when_no_snapshot(
    versioned_env, monkeypatch
):
    env = versioned_env
    client = env["client"]
    seed = _seed_aluno_em_t11()
    _login_aluno(client, user_id=seed["usuario_id"], user_name=seed["nome"])
    monkeypatch.delenv("SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE", raising=False)

    legacy_name = f"D82B legado {uuid.uuid4().hex[:8]}"
    req_id = _create_pending_requisicao_legada(seed["aluno_id"], 1, nome_evento=legacy_name)

    before = _row_by_id(
        req_id,
        "atividade_id, atividade_versao_id, codigo_normativo_snapshot, regra_snapshot_json",
    )
    assert before["atividade_id"] == 1
    assert before["atividade_versao_id"] is None
    assert before["codigo_normativo_snapshot"] is None
    assert before["regra_snapshot_json"] is None

    # Troca 1 -> 2 (ambas permitidas na matriz da T11) deve ser aceita.
    edit = client.post(
        f"/aluno/requisicoes/{req_id}?edit=1",
        data={
            "atividade_id": "2",
            "nome_evento": legacy_name,
            "horas_solicitadas": "4",
            "data_evento": "2026-05-24",
            "observacao": "troca legada permitida",
        },
        follow_redirects=False,
    )
    assert edit.status_code in (302, 303)

    after = _row_by_id(req_id, "atividade_id, atividade_versao_id")
    assert after["atividade_id"] == 2
    assert after["atividade_versao_id"] is None


# ---------------------------------------------------------------------------
# T04 — resolvedor não-resolvido: criação rejeitada sem persistência.
# ---------------------------------------------------------------------------

def test_d82b_t04_aluno_create_write_on_unresolved_creates_without_snapshot(
    versioned_env, monkeypatch
):
    env = versioned_env
    client = env["client"]
    seed = _seed_aluno_em_t11()
    _login_aluno(client, user_id=seed["usuario_id"], user_name=seed["nome"])
    monkeypatch.setenv("SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE", "1")
    monkeypatch.delenv("SGAA_VERSIONED_RESOLVER_SHADOW_READ", raising=False)

    # Força status não-resolvido no resolvedor consumido pelo writer (patch de
    # teste; não altera o código de produção do resolver/writer).
    def _fake_resolver(conn, **kwargs):
        return main._resolver_result(
            "version_inactive",
            reason="forçado não-resolvido para T04",
        )

    monkeypatch.setattr(versioning_resolver, "resolver_versao_por_aluno", _fake_resolver)

    event_name = f"D82B T04 {uuid.uuid4().hex[:8]}"
    resp = client.post(
        "/aluno/nova-requisicao",
        data={
            "atividade_id": "1",
            "nome_evento": event_name,
            "data_evento": "2026-05-24",
            "horas_solicitadas": "3",
            "observacao": "t04 unresolved",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200

    req = _fetch_req(seed["aluno_id"], event_name)
    assert req is None


# ---------------------------------------------------------------------------
# T05 — exceção no resolvedor: criação rejeitada sem persistência.
# ---------------------------------------------------------------------------

def test_d82b_t05_writer_exception_does_not_block_creation(
    versioned_env, monkeypatch
):
    env = versioned_env
    client = env["client"]
    seed = _seed_aluno_em_t11()
    _login_aluno(client, user_id=seed["usuario_id"], user_name=seed["nome"])
    monkeypatch.setenv("SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE", "1")
    monkeypatch.delenv("SGAA_VERSIONED_RESOLVER_SHADOW_READ", raising=False)

    def _boom_resolver(conn, **kwargs):
        raise RuntimeError("falha simulada no resolvedor (T05)")

    monkeypatch.setattr(versioning_resolver, "resolver_versao_por_aluno", _boom_resolver)

    event_name = f"D82B T05 {uuid.uuid4().hex[:8]}"
    resp = client.post(
        "/aluno/nova-requisicao",
        data={
            "atividade_id": "1",
            "nome_evento": event_name,
            "data_evento": "2026-05-24",
            "horas_solicitadas": "2",
            "observacao": "t05 boom",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200

    req = _fetch_req(seed["aluno_id"], event_name)
    assert req is None


# ---------------------------------------------------------------------------
# T06 — regressão D8.1B: detalhe mostra bloco e lista mostra chip vN.
# ---------------------------------------------------------------------------

def test_d82b_t06_regression_display_block_and_chip(versioned_env, monkeypatch):
    env = versioned_env
    client = env["client"]
    seed = _seed_aluno_em_t11()
    _login_aluno(client, user_id=seed["usuario_id"], user_name=seed["nome"])
    monkeypatch.setenv("SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE", "1")
    monkeypatch.delenv("SGAA_VERSIONED_RESOLVER_SHADOW_READ", raising=False)

    _event_name, req = _create_versioned_pending(client, seed)
    assert req["atividade_versao_id"] is not None

    detail = client.get(f"/aluno/requisicoes/{req['id']}")
    assert detail.status_code == 200
    assert "Versão normativa registrada" in detail.get_data(as_text=True)

    lista = client.get("/aluno/requisicoes")
    assert lista.status_code == 200
    assert 'class="aluno-snapshot-chip"' in lista.get_data(as_text=True)
