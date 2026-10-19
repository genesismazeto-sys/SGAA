"""Correcting the activity classification of a request that is still editable.

A request's activity version and its rule snapshot are the authority an
administrator decides against.  While the request is ``Pendente`` -- or
``Devolvida`` inside its return deadline, which the caller checks through
``app.requisition_policy`` -- it may move to another activity of the student's
effective Matrix.  It keeps its id, documents and every other field; it gets a
fresh snapshot from the versioning service
(``app.versioning.snapshots.prepare_versioned_requisicao_snapshot``: effective
Matrix, active version, axis), and both columns change in one compare-and-set
statement.  Schema v17 (``app.prod1_request_reclassification_ddl``) refuses
any other shape in the database itself.  ``atividade_versao`` is only read.

Traceability lives in the authority row: the new snapshot carries
``reclassification_history``, every earlier classification of the request
(identity, axis, group, name, when that snapshot was written and by which
flow) with who replaced it, when and in which status -- carried forward from
the previous snapshot, so a chain of corrections is never lost.  Each committed
correction also logs ``event=request_reclassified`` with ids only.

The caller owns the transaction: ``apply_reclassification`` runs inside the
same ``write_transaction`` as the rest of the edit.
"""

from __future__ import annotations

import datetime
import json
import logging
from dataclasses import dataclass

from app.prod1_request_reclassification_ddl import RECLASSIFIABLE_REQUEST_STATUSES
from app.versioning.snapshots import (
    RequisicaoSnapshotError,
    SnapshotProcessingAuthority,
    prepare_versioned_requisicao_snapshot,
    read_requisicao_snapshot_for_processing,
)

logger = logging.getLogger(__name__)

HISTORY_KEY = "reclassification_history"

#: Classification facts kept for each replaced snapshot.
_CLASSIFICATION_FIELDS = (
    "atividade_versao_id", "atividade_base_id", "atividade_versao_numero", "eixo",
    "grupo", "nome_exibivel", "tipo_atividade", "snapshot_written_at", "flow_origin",
)


class ReclassificationRefused(Exception):
    """The requested classification is not acceptable; nothing was written.

    ``code``: ``ACTIVITY_NOT_ALLOWED`` (outside the student's effective Matrix,
    inactive, or contradicting the declared type), ``STALE_FORM`` (the form was
    filled for another classification than the stored one) or
    ``NOT_RECLASSIFIABLE`` (the request is no longer editable).
    """

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class ReclassificationConflict(Exception):
    """The request changed after it was read; nothing was written."""


@dataclass(frozen=True)
class PreparedReclassification:
    request_id: int
    status: str
    from_version_id: int
    from_snapshot_json: str
    to_version_id: int
    snapshot_json: str


def _utc_now_iso() -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _previous_classification(conn, request_row) -> tuple[dict[str, object], list[object]]:
    """What the stored row says the request was, and the history it already carries."""
    read = read_requisicao_snapshot_for_processing(request_row)
    if read.authority is SnapshotProcessingAuthority.VALID_AUTHORITATIVE_SNAPSHOT:
        payload = read.payload or {}
        history = payload.get(HISTORY_KEY)
        return (
            {key: payload.get(key) for key in _CLASSIFICATION_FIELDS},
            list(history) if isinstance(history, list) else [],
        )
    # A row without a readable snapshot still names its version; record that.
    version = conn.execute(
        """SELECT v.id AS atividade_versao_id, v.atividade_base_id,
                  v.numero_versao AS atividade_versao_numero, v.eixo, v.grupo,
                  b.nome_conceito AS nome_exibivel
             FROM atividade_versao v JOIN atividade_base b ON b.id = v.atividade_base_id
            WHERE v.id = ?""",
        (request_row["atividade_versao_id"],),
    ).fetchone()
    facts = {key: None for key in _CLASSIFICATION_FIELDS}
    facts["atividade_versao_id"] = request_row["atividade_versao_id"]
    if version is not None:
        facts.update({key: version[key] for key in version.keys()})
    facts["snapshot_invalid_reason"] = read.reason
    return facts, []


def prepare_reclassification(
    conn,
    *,
    request_row,
    aluno_id: int,
    new_version_id: int | None,
    form_version_id: int | None,
    declared_tipo: str | None,
    flow_origin: str,
    actor_role: str,
    actor_user_id: int,
) -> PreparedReclassification | None:
    """Validate a classification change; ``None`` when the activity is unchanged.

    ``request_row`` is the stored request as the caller read it (``id``,
    ``status``, ``atividade_versao_id``, ``regra_snapshot_json``).
    ``form_version_id`` is the classification the submitted form was filled
    with: a change is accepted only from the classification still stored, so
    a form filled before someone else's correction can never undo it.
    """
    current_id = int(request_row["atividade_versao_id"])
    if new_version_id is None or int(new_version_id) == current_id:
        return None
    new_version_id = int(new_version_id)
    if form_version_id is None or int(form_version_id) != current_id:
        raise ReclassificationRefused("STALE_FORM")
    status = str(request_row["status"] or "")
    if status not in RECLASSIFIABLE_REQUEST_STATUSES:
        raise ReclassificationRefused("NOT_RECLASSIFIABLE")
    try:
        prepared = prepare_versioned_requisicao_snapshot(
            conn,
            flow_origin=flow_origin,
            aluno_id=aluno_id,
            atividade_versao_id=new_version_id,
        )
    except RequisicaoSnapshotError as exc:
        raise ReclassificationRefused("ACTIVITY_NOT_ALLOWED") from exc
    declared = str(declared_tipo or "").strip()
    if declared and declared != prepared.payload["tipo_atividade"]:
        # The activity is the type authority; a contradicting Tipo is a crafted POST.
        raise ReclassificationRefused("ACTIVITY_NOT_ALLOWED")

    previous, history = _previous_classification(conn, request_row)
    entry = {
        "from": previous,
        "to_atividade_versao_id": new_version_id,
        "reclassified_at": _utc_now_iso(),
        "actor": {"role": actor_role, "usuario_id": int(actor_user_id)},
        "request_status": status,
    }
    payload = {**prepared.payload, HISTORY_KEY: [*history, entry]}
    return PreparedReclassification(
        request_id=int(request_row["id"]),
        status=status,
        from_version_id=current_id,
        from_snapshot_json=str(request_row["regra_snapshot_json"]),
        to_version_id=new_version_id,
        snapshot_json=json.dumps(payload, ensure_ascii=False, sort_keys=True),
    )


def apply_reclassification(conn, prepared: PreparedReclassification) -> None:
    """Write the new classification if the row is still what was prepared from.

    Raises :class:`ReclassificationConflict` when the status, the activity or
    the snapshot changed since the caller read the row.
    """
    cursor = conn.execute(
        "UPDATE requisicoes SET atividade_versao_id = ?, regra_snapshot_json = ? "
        "WHERE id = ? AND status = ? AND atividade_versao_id = ? AND regra_snapshot_json = ?",
        (
            prepared.to_version_id,
            prepared.snapshot_json,
            prepared.request_id,
            prepared.status,
            prepared.from_version_id,
            prepared.from_snapshot_json,
        ),
    )
    if cursor.rowcount != 1:
        raise ReclassificationConflict()


def log_reclassified(prepared: PreparedReclassification) -> None:
    """Log a committed correction (ids only); called after the transaction commits."""
    logger.info(
        "event=request_reclassified request_id=%d from_version=%d to_version=%d status=%s",
        prepared.request_id,
        prepared.from_version_id,
        prepared.to_version_id,
        prepared.status,
    )


__all__ = [
    "HISTORY_KEY",
    "PreparedReclassification",
    "ReclassificationConflict",
    "ReclassificationRefused",
    "apply_reclassification",
    "log_reclassified",
    "prepare_reclassification",
]
