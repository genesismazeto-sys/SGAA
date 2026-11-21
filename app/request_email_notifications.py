"""Explicit decision-generation authority for request e-mail notifications.

RULING 3 -- generations are *explicit*, never derived.

Nothing in this module infers a notification from ``requisicoes.status``,
``data_processamento`` or a content hash of the request row.  A generation is
created only by :func:`record_final_decision_event`, which the canonical
processing handler calls in the same transaction as an administrator's explicit
``deferir`` / ``deferir_parte`` / ``indeferir`` / return-for-correction confirmation.

That distinction matters because status can move without an administrator:
``auto_indefer_devolvidas`` rewrites ``Devolvida -> Indeferida`` in bulk on mere
page load.  Such maintenance transitions deliberately never reach this module,
so they never manufacture an e-mail.

Lifecycle of one request::

    decide        -> pending  (previous pending, if any, becomes superseded)
    reopen        -> superseded
    dismiss       -> superseded  (the administrator withdrew the flag)
    decide again  -> a NEW pending generation
    sent          -> sent, and frozen forever

``ux_req_email_eventos_pendente`` (partial unique index) is what makes "the
request's *current* generation" well defined: at most one ``pending`` row may
exist per request.
"""

from __future__ import annotations

import datetime
import sqlite3
from collections import OrderedDict
from collections.abc import Mapping

from app.db import write_transaction

#: Explicit administrative decisions, including the non-final return for correction.
#: The historical constant name is retained for its existing callers.
FINAL_DECISION_STATUSES = ("Deferida", "Deferida Parcialmente", "Indeferida", "Devolvida")

#: Transitions that must never create a notification generation.
NON_NOTIFYING_STATUSES = ("Pendente", "Encerrada")

_EVENT_COLUMNS = """
    e.id, e.requisicao_id, e.aluno_id, e.destinatario_snapshot,
    e.status_decisao, e.horas_solicitadas, e.horas_deferidas,
    e.justificativa, e.atividade_nome, e.nome_evento,
    e.data_solicitacao, e.decidido_em, e.estado, e.email_envio_id
"""


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def supersede_pending_event(conn: sqlite3.Connection, *, requisicao_id: int) -> int:
    """Close the request's current pending generation, if it has one.

    Used by ``reabrir``: the decision that was awaiting communication no longer
    describes reality, so it stops being pending.  Rows already ``sent`` are
    never touched -- sent history is immutable.
    """
    cursor = conn.execute(
        "UPDATE requisicao_email_eventos"
        "    SET estado='superseded', superseded_em=?"
        "  WHERE requisicao_id=? AND estado='pending'",
        (_now(), requisicao_id),
    )
    return int(cursor.rowcount or 0)


def record_final_decision_event(
    conn: sqlite3.Connection, *, requisicao_id: int, decided_at: str | None = None
) -> int | None:
    """Create the pending generation for an explicit administrative decision.

    Returns the new event id, or ``None`` when the request's current status is
    not a communicable decision (defensive: callers should only invoke this on
    the explicit decision path).
    """
    row = conn.execute(
        """
        SELECT r.id, r.aluno_id, r.status, r.horas_solicitadas, r.horas_deferidas,
               r.observacao, r.data_solicitacao, r.nome_evento, r.data_processamento,
               a.email AS aluno_email, b.nome_conceito AS atividade_nome
          FROM requisicoes r
          LEFT JOIN alunos a ON a.id = r.aluno_id
          LEFT JOIN atividade_versao v ON v.id = r.atividade_versao_id
          LEFT JOIN atividade_base b ON b.id = v.atividade_base_id
         WHERE r.id = ?
        """,
        (requisicao_id,),
    ).fetchone()
    if row is None:
        return None
    status = str(row["status"] or "").strip()
    if status not in FINAL_DECISION_STATUSES:
        return None
    if row["aluno_id"] is None:
        # No authoritative student -> no addressable communication.
        return None

    # A new decision replaces whatever was still awaiting communication.
    supersede_pending_event(conn, requisicao_id=requisicao_id)

    justificativa = (row["observacao"] or "").strip() or None
    cursor = conn.execute(
        """
        INSERT INTO requisicao_email_eventos
            (requisicao_id, aluno_id, destinatario_snapshot, status_decisao,
             horas_solicitadas, horas_deferidas, justificativa, atividade_nome,
             nome_evento, data_solicitacao, decidido_em, estado)
        VALUES (?,?,?,?,?,?,?,?,?,?,?, 'pending')
        RETURNING id
        """,
        (
            requisicao_id,
            row["aluno_id"],
            (row["aluno_email"] or "").strip() or None,
            status,
            row["horas_solicitadas"],
            row["horas_deferidas"],
            justificativa,
            row["atividade_nome"],
            row["nome_evento"],
            row["data_solicitacao"],
            decided_at or row["data_processamento"] or _now(),
        ),
    )
    return int(cursor.fetchone()[0])


def pending_event_ids(
    conn: sqlite3.Connection, requisicao_ids=None
) -> dict[int, int]:
    """Request id -> the id of its *current* pending generation."""
    sql = "SELECT requisicao_id, id FROM requisicao_email_eventos WHERE estado='pending'"
    params: list = []
    if requisicao_ids is not None:
        ids = [int(value) for value in requisicao_ids]
        if not ids:
            return {}
        sql += f" AND requisicao_id IN ({','.join('?' for _ in ids)})"
        params = ids
    return {int(row[0]): int(row[1]) for row in conn.execute(sql, params)}


def pending_request_ids(
    conn: sqlite3.Connection, requisicao_ids=None
) -> set[int]:
    """Request ids whose *current* decision still awaits communication."""
    return set(pending_event_ids(conn, requisicao_ids))


class EmailFlagDismissalStale(Exception):
    """The named generations are no longer all their requests' pending ones.

    ``requisicao_ids`` are the requests whose flag changed (sent, superseded
    by a newer decision, or never that generation) since the page was shown.
    """

    def __init__(self, requisicao_ids) -> None:
        self.requisicao_ids = sorted(int(value) for value in requisicao_ids)
        super().__init__(f"stale e-mail flag selection: {self.requisicao_ids}")


def dismiss_pending_events(
    conn: sqlite3.Connection, generations: Mapping[int, int]
) -> int:
    """Withdraw the pending flag of exactly these generations, all or none.

    ``generations`` maps a request id to the pending generation id the
    administrator saw.  Matching on the generation, never on the request,
    is what keeps a page opened before a newer decision from clearing that
    decision's flag.  Each generation closes as ``superseded`` -- closed
    without delivery, the state a reopen already gives -- so the next
    decision raises its own flag through :func:`record_final_decision_event`.

    Nothing else is written: no ``email_envios`` row, no attempt link
    (``email_envio_id`` keeps naming a failed or unconfirmed attempt), no
    request column.  When any pair is not a current pending generation the
    transaction rolls back and :class:`EmailFlagDismissalStale` names the
    requests that moved.

    One ``UPDATE ... WHERE estado='pending' AND id IN (...)``: a concurrent
    decision or dispatch that commits first is seen by the re-checked
    ``estado='pending'``; one that comes later waits.  The processing handler
    locks the request row and then one generation, so it cannot deadlock with
    this.  A dispatch locking several of the same student's generations in
    another order can (the lock order of an ``IN`` list follows the plan);
    PostgreSQL then aborts one side and, both being single transactions,
    nothing is half-applied.
    """
    expected = {int(req_id): int(event_id) for req_id, event_id in generations.items()}
    if not expected:
        return 0
    event_ids = sorted(expected.values())
    placeholders = ",".join("?" for _ in event_ids)
    with write_transaction(conn):
        rows = conn.execute(
            f"""
            UPDATE requisicao_email_eventos
               SET estado='superseded', superseded_em=?
             WHERE estado='pending' AND id IN ({placeholders})
            RETURNING requisicao_id, id
            """,
            [_now(), *event_ids],
        ).fetchall()
        dismissed = {int(row[0]): int(row[1]) for row in rows}
        stale = [
            req_id for req_id, event_id in expected.items()
            if dismissed.get(req_id) != event_id
        ]
        if stale:
            raise EmailFlagDismissalStale(stale)
    return len(rows)


def failed_request_ids(conn: sqlite3.Connection, requisicao_ids=None) -> set[int]:
    """Pending requests whose own most recent delivery attempt did not succeed.

    Drives the danger treatment on the row indicator.  The join is on
    ``e.email_envio_id`` -- *this* generation's own attempt -- and deliberately
    not on ``aluno_id``: a student who once had a failed e-mail must not have
    every later, never-attempted decision painted as a failed attempt.
    ``attach_events_to_send`` is what makes that link exist while the generation
    is still pending.

    ``sending`` counts as unresolved: a row left in that state means the process
    died mid-send, and the operator needs to see it rather than have it look
    like an ordinary untouched pending generation.
    """
    sql = """
        SELECT DISTINCT e.requisicao_id
          FROM requisicao_email_eventos e
          JOIN email_envios s ON s.id = e.email_envio_id
         WHERE e.estado='pending'
           AND s.status IN ('failed','indeterminate','sending')
    """
    params: list = []
    if requisicao_ids is not None:
        ids = [int(value) for value in requisicao_ids]
        if not ids:
            return set()
        sql += f" AND e.requisicao_id IN ({','.join('?' for _ in ids)})"
        params = ids
    return {int(row[0]) for row in conn.execute(sql, params)}


def load_pending_events(conn: sqlite3.Connection, requisicao_ids) -> list[sqlite3.Row]:
    """Current pending generations for the given requests, oldest request first."""
    ids = [int(value) for value in requisicao_ids]
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    return conn.execute(
        f"""
        SELECT {_EVENT_COLUMNS},
               al.nome AS aluno_nome, al.matricula AS aluno_matricula,
               al.email AS aluno_email
          FROM requisicao_email_eventos e
          JOIN alunos al ON al.id = e.aluno_id
         WHERE e.estado='pending' AND e.requisicao_id IN ({placeholders})
         ORDER BY e.aluno_id, e.data_solicitacao, e.requisicao_id
        """,
        ids,
    ).fetchall()


def group_events_by_student(events) -> "OrderedDict[int, list]":
    """Partition decision events by authoritative ``aluno_id``.

    This is the single guarantee that one student's data never reaches another
    student's message: the renderer and the transport only ever receive one
    bucket at a time.
    """
    grouped: "OrderedDict[int, list]" = OrderedDict()
    for event in events:
        grouped.setdefault(int(event["aluno_id"]), []).append(event)
    return grouped


def attach_events_to_send(
    conn: sqlite3.Connection, *, event_ids, email_envio_id: int
) -> int:
    """Record which outbound attempt is currently carrying these generations.

    Called *before* the provider is contacted, while the events are still
    ``pending``.  Without this link a pending generation has no way to name the
    attempt that failed, and the only remaining join would be ``aluno_id`` --
    which cannot distinguish "this decision's delivery failed" from "this
    student once had some other failure".

    ``estado`` is untouched: only a confirmed success moves a generation out of
    ``pending`` (see :func:`mark_events_sent`).
    """
    ids = [int(value) for value in event_ids]
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    cursor = conn.execute(
        f"""
        UPDATE requisicao_email_eventos
           SET email_envio_id=?
         WHERE id IN ({placeholders}) AND estado='pending'
        """,
        [int(email_envio_id), *ids],
    )
    return int(cursor.rowcount or 0)


def mark_events_sent(conn: sqlite3.Connection, *, event_ids, email_envio_id: int) -> int:
    """Attach generations to the e-mail that successfully carried them."""
    ids = [int(value) for value in event_ids]
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    cursor = conn.execute(
        f"""
        UPDATE requisicao_email_eventos
           SET estado='sent', enviado_em=?, email_envio_id=?
         WHERE id IN ({placeholders}) AND estado='pending'
        """,
        [_now(), int(email_envio_id), *ids],
    )
    return int(cursor.rowcount or 0)


__all__ = [
    "EmailFlagDismissalStale",
    "FINAL_DECISION_STATUSES",
    "NON_NOTIFYING_STATUSES",
    "attach_events_to_send",
    "dismiss_pending_events",
    "failed_request_ids",
    "group_events_by_student",
    "load_pending_events",
    "mark_events_sent",
    "pending_event_ids",
    "pending_request_ids",
    "record_final_decision_event",
    "supersede_pending_event",
]
