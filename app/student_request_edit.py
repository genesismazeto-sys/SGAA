"""A student's edit of an own request, including the resubmission of a returned one.

The view checks ``app.requisition_policy`` first; this owner writes only if
the request is still in the state that check approved (the status and, for a
returned request, the processing date it read), so an administrator decision
or an expiry landing in between refuses the edit instead of being overwritten.

Editing a ``Pendente`` request changes its fields in place. Saving a
``Devolvida`` request resubmits it: it goes back to ``Pendente`` with every
processing field cleared -- the state an administrator's Reabrir leaves -- so
it is reviewed again and leaves the student's correction list. The
administrator's reason for the return stays in ``observacao`` as a bracketed
line above the student's reply (one column holds both, as with
``auto_indefer_devolvidas``), and a decision e-mail still pending from before
the return is superseded. The activity version and its rule snapshot are not
written here: a corrected classification goes through
``app.request_reclassification`` in the same transaction. The caller owns the
transaction.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.request_email_notifications import supersede_pending_event

RETURN_REASON_LABEL = "Motivo da devolução"

# A resubmission puts the request back where an administrator's Reabrir does:
# undecided, unprocessed, with no student notification outstanding.
_RESUBMISSION_RESET = (
    "status = 'Pendente'",
    "horas_deferidas = NULL",
    "data_processamento = NULL",
    "admin_id = NULL",
    "aluno_update_notified_at = NULL",
    "aluno_update_seen_at = NULL",
)


class StudentEditConflict(Exception):
    """The request changed after its edit permission was checked."""


@dataclass(frozen=True)
class StudentRequestEdit:
    """What the student submitted; ``None`` keeps the stored value."""

    nome_evento: str | None = None
    horas_solicitadas: float | None = None
    data_evento: str | None = None
    #: ``None``: the field was not submitted; ``""`` clears it.
    observacao: str | None = None


def _resubmitted_observacao(reason, reply: str | None) -> str | None:
    lines = []
    reason = str(reason or "").strip()
    if reason:
        lines.append(f"[{RETURN_REASON_LABEL}: {reason}]")
    if reply and reply.strip():
        lines.append(reply.strip())
    if not lines:
        return None if reply is None else ""
    return "\n".join(lines)


def save_student_request_edit(
    conn,
    *,
    request_id: int,
    aluno_id: int,
    status: str,
    data_processamento,
    stored_observacao,
    edit: StudentRequestEdit,
) -> bool:
    """Write the student's edit; True when it resubmitted a returned request.

    ``status``, ``data_processamento`` and ``stored_observacao`` are the
    values the caller read when it checked the edit permission. Raises
    :class:`StudentEditConflict` when the row no longer matches them.
    """
    resubmission = str(status or "").strip() == "Devolvida"
    set_parts: list[str] = []
    params: list[object] = []
    if edit.nome_evento is not None:
        set_parts.append("nome_evento = ?")
        params.append(edit.nome_evento)
    if edit.horas_solicitadas is not None:
        set_parts.append("horas_solicitadas = ?")
        params.append(edit.horas_solicitadas)
    if edit.data_evento:
        set_parts.append("data_evento = ?")
        params.append(edit.data_evento)
    observacao = (
        _resubmitted_observacao(stored_observacao, edit.observacao)
        if resubmission
        else edit.observacao
    )
    if observacao is not None:
        set_parts.append("observacao = ?")
        params.append(observacao)
    if resubmission:
        set_parts.extend(_RESUBMISSION_RESET)
    if not set_parts:
        # Nothing to change, but the state check below must still run.
        set_parts.append("observacao = observacao")

    where = "id = ? AND aluno_id = ? AND status = ?"
    params.extend([int(request_id), int(aluno_id), status])
    if resubmission:
        where += " AND data_processamento = ?"
        params.append(data_processamento)
    cursor = conn.execute(
        f"UPDATE requisicoes SET {', '.join(set_parts)} WHERE {where}",
        tuple(params),
    )
    if cursor.rowcount != 1:
        raise StudentEditConflict()
    if resubmission:
        supersede_pending_event(conn, requisicao_id=int(request_id))
    return resubmission


__all__ = [
    "RETURN_REASON_LABEL",
    "StudentEditConflict",
    "StudentRequestEdit",
    "save_student_request_edit",
]
