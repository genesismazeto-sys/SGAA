"""Canonical prod-1/v17 request reclassification (SQLite authority).

Until v16 ``trg_requisicoes_snapshot_immutable`` froze a request's activity
version and its rule snapshot for every status, so a student who picked the
wrong activity could never correct it, even while the request was still
pending.  v17 narrows that freeze to what must be frozen: the classification
of a request that is no longer editable.

THE CONTRACT
    * A request whose status is ``Pendente`` or ``Devolvida`` (before and
      after the write) may be reclassified: ``atividade_versao_id`` and
      ``regra_snapshot_json`` change together, in one statement, and the new
      snapshot is a JSON object whose integer ``atividade_versao_id`` names
      the new activity version.  An old snapshot can never stay paired with a
      new activity, nor a new snapshot with the old one.
    * Every other status (``Deferida``, ``Deferida Parcialmente``,
      ``Indeferida``, ``Encerrada``) keeps the v16 refusal and its message.
    * The database enforces shape and pairing only.  Which activity is valid
      (the student's effective Matrix, an active version) and the return
      deadline of a ``Devolvida`` request are application rules
      (``app.request_reclassification``, ``app.requisition_policy``).
    * ``atividade_versao`` and every other table are untouched; v17 replaces
      one trigger and backfills nothing.

Comparisons use ``IS`` / ``IS NOT`` so a NULL can never slip past them, and
the snapshot is inspected only after ``json_valid`` (a CASE stops at its first
true branch).  The PostgreSQL authority (``app.pg_schema``) declares the same
contract in ``fn_requisicoes_snapshot_immutable``.
"""

from __future__ import annotations

#: Statuses in which a request's classification may still be corrected.
RECLASSIFIABLE_REQUEST_STATUSES = ("Pendente", "Devolvida")

SNAPSHOT_IMMUTABLE_MESSAGE = "request snapshot authority is immutable"
SNAPSHOT_PAIRING_MESSAGE = "request reclassification must replace the activity and its snapshot together"
SNAPSHOT_IDENTITY_MESSAGE = "request snapshot must name its activity version"

_STATUSES = ",".join(f"'{status}'" for status in RECLASSIFIABLE_REQUEST_STATUSES)

REQUEST_SNAPSHOT_V17_TRIGGER_SQL = f"""CREATE TRIGGER trg_requisicoes_snapshot_immutable
BEFORE UPDATE OF atividade_versao_id,regra_snapshot_json ON requisicoes
FOR EACH ROW WHEN NEW.atividade_versao_id IS NOT OLD.atividade_versao_id
 OR NEW.regra_snapshot_json IS NOT OLD.regra_snapshot_json
BEGIN
 SELECT CASE
  WHEN OLD.status NOT IN ({_STATUSES}) OR NEW.status NOT IN ({_STATUSES})
   THEN RAISE(ABORT,'{SNAPSHOT_IMMUTABLE_MESSAGE}')
  WHEN NEW.atividade_versao_id IS OLD.atividade_versao_id
   OR NEW.regra_snapshot_json IS OLD.regra_snapshot_json
   THEN RAISE(ABORT,'{SNAPSHOT_PAIRING_MESSAGE}')
  WHEN NEW.regra_snapshot_json IS NULL OR json_valid(NEW.regra_snapshot_json)=0
   THEN RAISE(ABORT,'{SNAPSHOT_IDENTITY_MESSAGE}')
  WHEN json_type(NEW.regra_snapshot_json) IS NOT 'object'
   OR json_type(NEW.regra_snapshot_json,'$.atividade_versao_id') IS NOT 'integer'
   OR json_extract(NEW.regra_snapshot_json,'$.atividade_versao_id') IS NOT NEW.atividade_versao_id
   THEN RAISE(ABORT,'{SNAPSHOT_IDENTITY_MESSAGE}')
 END;
END"""

#: Every v17 statement, in execution order -- shared verbatim by the fresh
#: bootstrap and the v16 -> v17 migration, so both store identical DDL.
REQUEST_RECLASSIFICATION_V17_STATEMENTS = (
    "DROP TRIGGER trg_requisicoes_snapshot_immutable",
    REQUEST_SNAPSHOT_V17_TRIGGER_SQL,
)
REQUEST_RECLASSIFICATION_V17_SCHEMA_OBJECTS_SQL = (
    ";\n".join(REQUEST_RECLASSIFICATION_V17_STATEMENTS) + ";"
)

REQUEST_RECLASSIFICATION_V17_DETAILS_JSON = (
    '{"schema_epoch":"prod-1","request_reclassification":"pending_or_returned",'
    '"statuses":["Pendente","Devolvida"],"pairing":"activity_and_snapshot_together",'
    '"trigger":"trg_requisicoes_snapshot_immutable","backfill":"none"}'
)

__all__ = [
    "RECLASSIFIABLE_REQUEST_STATUSES",
    "REQUEST_RECLASSIFICATION_V17_DETAILS_JSON",
    "REQUEST_RECLASSIFICATION_V17_SCHEMA_OBJECTS_SQL",
    "REQUEST_RECLASSIFICATION_V17_STATEMENTS",
    "REQUEST_SNAPSHOT_V17_TRIGGER_SQL",
    "SNAPSHOT_IDENTITY_MESSAGE",
    "SNAPSHOT_IMMUTABLE_MESSAGE",
    "SNAPSHOT_PAIRING_MESSAGE",
]
