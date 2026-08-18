"""
D7.1 — Contratos do versionamento por matriz.

Prova que a resolução de versão por matriz é determinística e segura:

1. Mesma atividade-base, matriz com norma AAC-rev5 → resolve versão AAC-rev5.
2. Mesma atividade-base, matriz com norma AAC-rev6 → resolve versão diferente (AAC-rev6).
3. Mesma atividade-base com AEU na matriz nova → resolve AEU-rev1.
4. Ambiguidade (2 versões ativas da mesma base na mesma matriz) → ambiguous_version,
   resolvedor não escolhe "primeira ativa", writer não grava atividade_versao_id.
5. Turma sem matriz explícita → writer não carimba atividade_versao_id, mesmo que o
   curso possua matrizes (fallback heurístico proibido para carimbo).
6. Turma com matriz explícita → writer carimba corretamente (controle positivo).
7. Resolvedor é estritamente read-only (não muta o banco).

Dataset de referência: tests/versioned_test_support.py
  PPA-T10 → Matriz T10, norma AAC-rev5
  PPA-T11 → Matriz T11, normas AAC-rev6 + AEU-rev1
"""
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main
from app.versioning import resolver as resolver_service
from tests.versioned_test_support import isolated_versioned_app_env


@pytest.fixture()
def versioned_env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "d71_contract.db") as env:
        yield env


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_turma(conn, codigo: str):
    row = conn.execute("SELECT * FROM turmas WHERE codigo = ?", (codigo,)).fetchone()
    assert row is not None, f"Turma {codigo!r} não encontrada no dataset de referência"
    return row


# ---------------------------------------------------------------------------
# Contrato 1 — Mesma base, matriz AAC-rev5 → resolve AAC-rev5
# ---------------------------------------------------------------------------

def test_contrato_1_matriz_aac_rev5_resolve_versao_correta(versioned_env):
    """
    atividade_id=1 ('Visitas técnicas'), turma PPA-T10, matriz vinculada a AAC-rev5.
    Deve resolver para a versão AAC-rev5 dessa atividade-base.
    """
    with main.app.app_context():
        conn = main.get_db_connection()
        turma = _get_turma(conn, "PPA-T10")

        result = resolver_service.resolver_versao_por_matriz(
            conn,
            matriz_id=turma["matriz_id"],
            atividade_id_legacy=1,
            strict_legacy_scope=True,
        )

    assert result["status"] == "resolved", f"Esperado resolved, obteve: {result}"
    assert result["eixo"] == "AAC"
    assert result["codigo_normativo"] == "AAC-rev5", (
        f"Esperado AAC-rev5, obteve: {result['codigo_normativo']!r}"
    )
    assert result["atividade_versao_id"] is not None
    assert result["legacy_scope_ok"] is True


# ---------------------------------------------------------------------------
# Contrato 2 — Mesma base, matriz diferente → versão diferente (AAC-rev6)
# ---------------------------------------------------------------------------

def test_contrato_2_mesma_base_matrizes_diferentes_resolvem_versoes_distintas(versioned_env):
    """
    atividade_id=1, mesma atividade-base.
    PPA-T10 (norma AAC-rev5) → AAC-rev5.
    PPA-T11 (norma AAC-rev6) → AAC-rev6.
    Prova que a MESMA atividade-base produz versões distintas por matriz — nunca
    a mesma versão para matrizes com normas diferentes.
    """
    with main.app.app_context():
        conn = main.get_db_connection()
        t10 = _get_turma(conn, "PPA-T10")
        t11 = _get_turma(conn, "PPA-T11")

        result_t10 = resolver_service.resolver_versao_por_matriz(
            conn, matriz_id=t10["matriz_id"], atividade_id_legacy=1, strict_legacy_scope=True,
        )
        result_t11 = resolver_service.resolver_versao_por_matriz(
            conn, matriz_id=t11["matriz_id"], atividade_id_legacy=1, strict_legacy_scope=True,
        )

    assert result_t10["status"] == "resolved"
    assert result_t11["status"] == "resolved"

    assert result_t10["codigo_normativo"] == "AAC-rev5"
    assert result_t11["codigo_normativo"] == "AAC-rev6"

    # A mesma atividade-base deve resolver para IDs de versão distintos.
    assert result_t10["atividade_versao_id"] != result_t11["atividade_versao_id"], (
        "Mesma atividade-base deve resolver para versões distintas em matrizes diferentes"
    )
    # Ambas as matrizes retornam a mesma atividade_base_id (o conceito é o mesmo).
    assert result_t10["atividade_base_id"] == result_t11["atividade_base_id"]


# ---------------------------------------------------------------------------
# Contrato 3 — Base com AEU na matriz nova resolve AEU-rev1
# ---------------------------------------------------------------------------

def test_contrato_3_base_extensao_resolve_aeu_na_matriz_nova(versioned_env):
    """
    atividade_id=27 ('Participação em projetos de extensão').
    PPA-T11 inclui essa atividade no escopo (range 1-31 sem 6) e vincula versão AEU-rev1
    para essa base. Deve resolver para AEU.
    """
    with main.app.app_context():
        conn = main.get_db_connection()
        t11 = _get_turma(conn, "PPA-T11")

        result = resolver_service.resolver_versao_por_matriz(
            conn,
            matriz_id=t11["matriz_id"],
            atividade_id_legacy=27,
            strict_legacy_scope=True,
        )

    assert result["status"] == "resolved", f"Esperado resolved: {result}"
    assert result["eixo"] == "AEU", f"Esperado AEU, obteve: {result['eixo']!r}"
    assert result["codigo_normativo"] == "AEU-rev1"


# ---------------------------------------------------------------------------
# Contrato 4 — Ambiguidade é erro duro; resolvedor não escolhe "primeira ativa"
# ---------------------------------------------------------------------------

def test_contrato_4_ambiguidade_retorna_erro_duro_sem_versao_id(versioned_env):
    """
    Quando a mesma atividade-base tem DUAS versões ativas vinculadas à mesma matriz,
    o resolvedor deve retornar ambiguous_version — jamais escolher a "primeira ativa".
    O campo atividade_versao_id no resultado deve ser None.
    """
    import uuid

    with main.app.app_context():
        conn = main.get_db_connection()
        t11 = _get_turma(conn, "PPA-T11")
        matriz_id = t11["matriz_id"]

        # base_id=1 já tem versão AAC-rev6 na T11.
        # Adicionar segunda norma e versão ativa para a mesma base → ambiguidade.
        novo_codigo = f"AAC-rev6-amb4-{uuid.uuid4().hex[:8]}"
        conn.execute(
            "INSERT INTO norma_atividade (codigo, eixo, revisao, nome, status) "
            "VALUES (?, 'AAC', 'amb4', ?, 'ativa')",
            (novo_codigo, f"Norma duplicada {novo_codigo}"),
        )
        norma_id = conn.execute(
            "SELECT id FROM norma_atividade WHERE codigo = ?", (novo_codigo,)
        ).fetchone()["id"]

        conn.execute(
            "INSERT INTO atividade_versao "
            "(atividade_base_id, norma_id, codigo_normativo, eixo, grupo, numero_versao, status) "
            "VALUES (?, ?, ?, 'AAC', '1 - AAC ambíguo', ?, 'ativa')",
            (1, norma_id, novo_codigo, main.get_next_numero_versao(conn, 1)),
        )
        nova_versao_id = conn.execute(
            "SELECT id FROM atividade_versao WHERE norma_id = ?", (norma_id,)
        ).fetchone()["id"]

        conn.execute(
            "INSERT INTO matriz_norma (matriz_id, norma_id) VALUES (?, ?)",
            (matriz_id, norma_id),
        )
        conn.execute(
            "INSERT INTO matriz_atividade_versao_item (matriz_id, atividade_versao_id) VALUES (?, ?)",
            (matriz_id, nova_versao_id),
        )
        conn.commit()

        result = resolver_service.resolver_versao_por_matriz(
            conn,
            matriz_id=t11["matriz_id"],
            atividade_id_legacy=1,
            strict_legacy_scope=True,
        )

    assert result["status"] == "ambiguous_version", (
        f"Esperado ambiguous_version, obteve: {result['status']!r}. "
        "Resolvedor não deve escolher 'primeira ativa' quando há ambiguidade."
    )
    assert "multiple_valid_candidates" in result["warnings"]
    assert result["atividade_versao_id"] is None, (
        "Com ambiguidade, atividade_versao_id deve ser None no resultado do resolvedor"
    )


def test_contrato_4b_writer_nao_grava_atividade_versao_id_quando_ambiguo(versioned_env):
    """
    Quando o resolvedor retorna ambiguous_version, o writer NÃO deve gravar
    atividade_versao_id na requisição — a ambiguidade deve propagar-se para o banco.
    """
    import uuid

    with main.app.app_context():
        conn = main.get_db_connection()
        t11 = _get_turma(conn, "PPA-T11")
        matriz_id = t11["matriz_id"]

        # Aluno em T11 (com matriz explícita, para que o pre-check do writer passe).
        aluno = conn.execute(
            """
            SELECT a.id AS aluno_id
              FROM alunos a
              JOIN turmas t ON t.id = a.turma_id
             WHERE t.id = ?
             LIMIT 1
            """,
            (t11["id"],),
        ).fetchone()
        assert aluno is not None, "Dataset de referência deve ter aluno em PPA-T11"
        aluno_id = aluno["aluno_id"]

        # Criar requisição legada para atividade_id=1.
        req_id = conn.execute(
            """
            INSERT INTO requisicoes (
                aluno_id, atividade_id, data_solicitacao, data_evento,
                horas_solicitadas, nome_evento, status
            ) VALUES (?, 1, '2026-06-01 10:00:00', '2026-06-01', 4, 'Evento C4b', 'Pendente')
            RETURNING id
            """,
            (aluno_id,),
        ).fetchone()["id"]
        conn.commit()

        # Criar ambiguidade: segunda versão ativa para base_id=1 em T11.
        novo_codigo = f"AAC-rev6-c4b-{uuid.uuid4().hex[:8]}"
        conn.execute(
            "INSERT INTO norma_atividade (codigo, eixo, revisao, nome, status) "
            "VALUES (?, 'AAC', 'c4b', ?, 'ativa')",
            (novo_codigo, f"Norma C4b {novo_codigo}"),
        )
        norma_id = conn.execute(
            "SELECT id FROM norma_atividade WHERE codigo = ?", (novo_codigo,)
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO atividade_versao "
            "(atividade_base_id, norma_id, codigo_normativo, eixo, grupo, numero_versao, status) "
            "VALUES (?, ?, ?, 'AAC', '1 - AAC C4b', ?, 'ativa')",
            (1, norma_id, novo_codigo, main.get_next_numero_versao(conn, 1)),
        )
        nova_versao_id = conn.execute(
            "SELECT id FROM atividade_versao WHERE norma_id = ?", (norma_id,)
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO matriz_norma (matriz_id, norma_id) VALUES (?, ?)", (matriz_id, norma_id)
        )
        conn.execute(
            "INSERT INTO matriz_atividade_versao_item (matriz_id, atividade_versao_id) VALUES (?, ?)",
            (matriz_id, nova_versao_id),
        )
        conn.commit()

        with pytest.raises(main.RequisicaoSnapshotError):
            main.prepare_versioned_requisicao_snapshot(
                conn,
                flow_origin="test_contrato_4b",
                aluno_id=aluno_id,
                atividade_id_legacy=1,
            )

        row = conn.execute(
            "SELECT atividade_versao_id FROM requisicoes WHERE id = ?", (req_id,)
        ).fetchone()

    assert row["atividade_versao_id"] is None, (
        "Com ambiguidade, writer não deve gravar atividade_versao_id na requisição"
    )


# ---------------------------------------------------------------------------
# Contrato 5 — Turma sem matriz explícita não carimba atividade_versao_id
# ---------------------------------------------------------------------------

def test_contrato_5_turma_sem_matriz_explicita_nao_carimba(versioned_env):
    """
    Turma com matriz_id=NULL (mesmo com o curso possuindo matrizes) NÃO
    deve produzir carimbo de atividade_versao_id.

    Para carimbo operacional, escolher qualquer matriz do curso quando
    turma.matriz_id é NULL seria uma heurística perigosa que este contrato proíbe.

    Requer patch: _get_turma_explicit_matriz_id_for_snapshot + pre-check no writer.
    """
    with main.app.app_context():
        conn = main.get_db_connection()

        # Usar o curso PPA que já tem matrizes T10 e T11 no dataset.
        curso = conn.execute("SELECT id FROM cursos WHERE codigo = 'PPA'").fetchone()
        assert curso is not None, "Curso PPA não encontrado no dataset de referência"
        curso_id = curso["id"]

        # Garantir que o curso TEM matriz (para provar que uma escolha heurística existiria).
        matrix_exists = conn.execute(
            "SELECT 1 FROM matrizes_atividades WHERE curso_id = ? LIMIT 1",
            (curso_id,),
        ).fetchone()
        assert matrix_exists is not None, (
            "Curso PPA deve ter matriz para que este teste prove a prevenção do fallback"
        )

        # Criar turma SEM matriz_id (NULL).
        conn.execute(
            """
            INSERT INTO turmas (nome, semestre, turno, status, numero, curso_id, codigo,
                                ano_inicio, semestre_inicio, ano_fim, semestre_fim)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("PPA-T00-C5", 1, "Manhã", "Ativa", 99, curso_id, "PPA-T00-C5",
             2024, 1, 2027, 2),
            # Nota: matriz_id NÃO incluído → fica NULL
        )
        turma_id_sem_matriz = conn.execute(
            "SELECT id FROM turmas WHERE codigo = 'PPA-T00-C5'"
        ).fetchone()["id"]

        # Confirmar que turma.matriz_id é realmente NULL.
        turma_row = conn.execute(
            "SELECT matriz_id FROM turmas WHERE id = ?", (turma_id_sem_matriz,)
        ).fetchone()
        assert turma_row["matriz_id"] is None, (
            "Pré-condição: turma deve ter matriz_id NULL para este contrato"
        )

        # Criar usuário + aluno nessa turma.
        conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo) VALUES (?, ?, ?, ?)",
            ("Aluno Contrato5", "contrato5@teste.local", main.hash_password("test"), "aluno"),
        )
        usuario_id = conn.execute(
            "SELECT id FROM usuarios WHERE email = 'contrato5@teste.local'"
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (usuario_id, "Aluno Contrato5", "C5-001", "contrato5@teste.local",
             turma_id_sem_matriz, "Ativo"),
        )
        aluno_id = conn.execute(
            "SELECT id FROM alunos WHERE matricula = 'C5-001'"
        ).fetchone()["id"]

        # Criar requisição legada (atividade_versao_id deve ficar NULL).
        req_id = conn.execute(
            """
            INSERT INTO requisicoes (
                aluno_id, atividade_id, data_solicitacao, data_evento,
                horas_solicitadas, nome_evento, status
            ) VALUES (?, 1, '2026-06-01 10:00:00', '2026-06-01', 4, 'Evento C5', 'Pendente')
            RETURNING id
            """,
            (aluno_id,),
        ).fetchone()["id"]
        conn.commit()

        with pytest.raises(main.RequisicaoSnapshotError):
            main.prepare_versioned_requisicao_snapshot(
                conn,
                flow_origin="test_contrato_5",
                aluno_id=aluno_id,
                atividade_id_legacy=1,
            )

        row = conn.execute(
            "SELECT atividade_versao_id FROM requisicoes WHERE id = ?", (req_id,)
        ).fetchone()

    assert row["atividade_versao_id"] is None, (
        "Turma sem matriz explícita NÃO deve ter atividade_versao_id carimbado. "
        "Escolha automática de matriz do curso é heurística proibida para carimbo operacional."
    )


# ---------------------------------------------------------------------------
# Contrato 5b — Turma COM matriz explícita carimba corretamente (controle positivo)
# ---------------------------------------------------------------------------

def test_contrato_5b_turma_com_matriz_explicita_carimba_corretamente(versioned_env):
    """
    Controle positivo: aluno em PPA-T11 (turma com matriz_id explícito) deve ter
    atividade_versao_id carimbado pelo writer quando o resolvedor retorna 'resolved'.
    Garante que o contrato 5 não bloqueou o caminho feliz.
    """
    with main.app.app_context():
        conn = main.get_db_connection()
        t11 = _get_turma(conn, "PPA-T11")

        aluno = conn.execute(
            """
            SELECT a.id AS aluno_id
              FROM alunos a
              JOIN turmas t ON t.id = a.turma_id
             WHERE t.id = ?
             LIMIT 1
            """,
            (t11["id"],),
        ).fetchone()
        assert aluno is not None, "Dataset deve ter aluno em PPA-T11"
        aluno_id = aluno["aluno_id"]

        # Confirmar pré-condição: turma tem matriz explícita.
        turma = conn.execute(
            "SELECT t.matriz_id FROM alunos a JOIN turmas t ON t.id = a.turma_id WHERE a.id = ?",
            (aluno_id,),
        ).fetchone()
        assert turma["matriz_id"] is not None, "PPA-T11 deve ter matriz_id explícito"

        req_id = conn.execute(
            """
            INSERT INTO requisicoes (
                aluno_id, atividade_id, data_solicitacao, data_evento,
                horas_solicitadas, nome_evento, status
            ) VALUES (?, 1, '2026-06-01 10:00:00', '2026-06-01', 4, 'Evento C5b', 'Pendente')
            RETURNING id
            """,
            (aluno_id,),
        ).fetchone()["id"]
        conn.commit()

        result = main.prepare_versioned_requisicao_snapshot(
            conn,
            flow_origin="test_contrato_5b",
            aluno_id=aluno_id,
            atividade_id_legacy=1,
        )

        row = conn.execute(
            "SELECT atividade_versao_id FROM requisicoes WHERE id = ?", (req_id,)
        ).fetchone()

    assert result.atividade_versao_id is not None
    assert result.payload["matriz_id_efetiva"] == turma["matriz_id"]
    assert row["atividade_versao_id"] is None


# ---------------------------------------------------------------------------
# Contrato 6 — Resolvedor é estritamente read-only
# ---------------------------------------------------------------------------

def test_contrato_6_resolvedor_e_read_only(versioned_env):
    """
    Os resolvedores exatos por matriz e por aluno não devem inserir,
    atualizar ou deletar qualquer dado no banco.
    """
    with main.app.app_context():
        conn = main.get_db_connection()
        t10 = _get_turma(conn, "PPA-T10")
        t11 = _get_turma(conn, "PPA-T11")

        aluno = conn.execute(
            """
            SELECT a.id FROM alunos a
             JOIN turmas t ON t.id = a.turma_id
            WHERE t.id = ?
            LIMIT 1
            """,
            (t11["id"],),
        ).fetchone()

        changes_before = conn.total_changes
        reqs_count_before = conn.execute("SELECT COUNT(*) AS c FROM requisicoes").fetchone()["c"]
        versioned_count_before = conn.execute(
            "SELECT COUNT(*) AS c FROM requisicoes WHERE atividade_versao_id IS NOT NULL"
        ).fetchone()["c"]

        # Exercitar todos os caminhos públicos dos resolvedores exatos.
        resolver_service.resolver_versao_por_matriz(conn, matriz_id=t10["matriz_id"], atividade_id_legacy=1, strict_legacy_scope=True)
        resolver_service.resolver_versao_por_matriz(conn, matriz_id=t10["matriz_id"], atividade_id_legacy=1, strict_legacy_scope=False)
        resolver_service.resolver_versao_por_matriz(conn, matriz_id=t11["matriz_id"], atividade_id_legacy=1, strict_legacy_scope=True)
        resolver_service.resolver_versao_por_matriz(conn, matriz_id=t11["matriz_id"], atividade_id_legacy=27, strict_legacy_scope=True)
        # Atividade fora do escopo (retorna legacy_activity_not_in_matrix) — não deve mutar.
        resolver_service.resolver_versao_por_matriz(conn, matriz_id=t10["matriz_id"], atividade_id_legacy=27, strict_legacy_scope=True)
        if aluno:
            resolver_service.resolver_versao_por_aluno(conn, aluno_id=aluno["id"], atividade_id_legacy=1, strict_legacy_scope=True)

        changes_after = conn.total_changes
        reqs_count_after = conn.execute("SELECT COUNT(*) AS c FROM requisicoes").fetchone()["c"]
        versioned_count_after = conn.execute(
            "SELECT COUNT(*) AS c FROM requisicoes WHERE atividade_versao_id IS NOT NULL"
        ).fetchone()["c"]

    assert changes_after == changes_before, (
        "Resolvedor não deve mutar o banco de dados (total_changes alterado)"
    )
    assert reqs_count_after == reqs_count_before, (
        "Resolvedor não deve criar ou remover requisições"
    )
    assert versioned_count_after == versioned_count_before, (
        "Resolvedor não deve stampar atividade_versao_id em requisições existentes"
    )
