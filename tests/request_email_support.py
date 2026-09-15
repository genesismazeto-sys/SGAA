"""Shared fixtures for the request e-mail notification suites.

Every helper builds a throwaway prod-1/v7 database in memory.  Nothing here
touches the operational ``database.db``.
"""

from __future__ import annotations

import sqlite3

from app.prod1_schema import bootstrap_prod1_schema


def new_v7_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    bootstrap_prod1_schema(conn)
    return conn


def seed_activity(conn: sqlite3.Connection, *, nome="Congresso", eixo="AAC") -> int:
    base_id = conn.execute(
        "INSERT INTO atividade_base(nome_conceito) VALUES(?)", (nome,)
    ).lastrowid
    return int(
        conn.execute(
            "INSERT INTO atividade_versao(atividade_base_id,eixo) VALUES(?,?)",
            (base_id, eixo),
        ).lastrowid
    )


def seed_student(conn: sqlite3.Connection, *, nome, matricula, email) -> int:
    return int(
        conn.execute(
            "INSERT INTO alunos(nome,matricula,email) VALUES(?,?,?)",
            (nome, matricula, email),
        ).lastrowid
    )


def seed_request(
    conn: sqlite3.Connection,
    *,
    aluno_id: int,
    versao_id: int,
    data_solicitacao="2026-03-10",
    horas=10.0,
    status="Pendente",
    nome_evento="Semana Acadêmica",
) -> int:
    return int(
        conn.execute(
            """
            INSERT INTO requisicoes
                (aluno_id,atividade_versao_id,data_solicitacao,data_evento,
                 horas_solicitadas,nome_evento,status,regra_snapshot_json)
            VALUES (?,?,?,?,?,?,?,'{"atividade_base_id":1}')
            """,
            (
                aluno_id,
                versao_id,
                data_solicitacao,
                data_solicitacao,
                horas,
                nome_evento,
                status,
            ),
        ).lastrowid
    )


def decide(
    conn: sqlite3.Connection,
    req_id: int,
    *,
    status: str,
    horas_deferidas=None,
    observacao=None,
    decided_at="2026-04-01 09:00:00",
):
    """Simulate the explicit administrator decision path end to end."""
    from app.request_email_notifications import record_final_decision_event

    conn.execute(
        "UPDATE requisicoes"
        "   SET status=?, horas_deferidas=?, observacao=?, data_processamento=?"
        " WHERE id=?",
        (status, horas_deferidas, observacao, decided_at, req_id),
    )
    return record_final_decision_event(conn, requisicao_id=req_id, decided_at=decided_at)


def reopen(conn: sqlite3.Connection, req_id: int):
    from app.request_email_notifications import supersede_pending_event

    conn.execute(
        "UPDATE requisicoes SET status='Pendente', data_processamento=NULL WHERE id=?",
        (req_id,),
    )
    return supersede_pending_event(conn, requisicao_id=req_id)


def install_email_preset(
    conn: sqlite3.Connection,
    *,
    titulo="Resposta padrão",
    assunto="Resultado das suas requisições",
    texto="{saudacao}, {aluno.primeironome}.\n\n{requisicoes}\n\nAtenciosamente.",
    preset_id=1,
    is_default=1,
):
    conn.execute(
        "INSERT INTO configuracoes_presets"
        "(tipo,preset_id,titulo,texto,assunto,is_default)"
        " VALUES('emails',?,?,?,?,?)",
        (preset_id, titulo, texto, assunto, is_default),
    )
    return {"id": preset_id, "titulo": titulo, "texto": texto, "assunto": assunto}
