from __future__ import annotations

import datetime
import json
import os
from dataclasses import dataclass
from enum import Enum
from math import isfinite

from app.versioning import resolver as resolver_service

REQUISICAO_SNAPSHOT_SUPPORTED_SCHEMA = "prod-1-request-v2"


class RequisicaoSnapshotError(RuntimeError):
    user_message = "A atividade selecionada não está disponível para a matriz da sua turma."


@dataclass(frozen=True)
class PreparedRequisicaoSnapshot:
    atividade_versao_id: int
    snapshot_json: str
    payload: dict[str, object]


class SnapshotProcessingAuthority(str, Enum):
    VALID_AUTHORITATIVE_SNAPSHOT = "VALID_AUTHORITATIVE_SNAPSHOT"
    INVALID_AUTHORITATIVE_SNAPSHOT = "INVALID_AUTHORITATIVE_SNAPSHOT"


@dataclass(frozen=True)
class AuthoritativeRequisicaoSnapshotRule:
    atividade_base_id: int
    atividade_versao_id: int
    atividade_versao_numero: int
    eixo: str
    matriz_id_efetiva: int
    schema_version: str
    ch_por_evento: float | int | None
    limite_semestre: float | int | None
    limite_total: float | int | None


@dataclass(frozen=True)
class RequisicaoSnapshotProcessingRead:
    authority: SnapshotProcessingAuthority
    rule: AuthoritativeRequisicaoSnapshotRule | None = None
    reason: str | None = None
    payload: dict[str, object] | None = None


IDENTITY_FIELDS = (
    "atividade_base_id", "atividade_versao_id", "atividade_versao_numero",
    "eixo", "matriz_id_efetiva", "schema_version",
)
RULE_FIELDS = ("ch_por_evento", "limite_semestre", "limite_total")
DISPLAY_FIELDS = ("nome_exibivel", "tipo_atividade", "grupo", "documentos_json")


def _value(row, key):
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get(key)
    try:
        return row[key]
    except (IndexError, KeyError, TypeError):
        return None


def _positive_int(value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError
    return value


def _optional_nonnegative(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError
    if not isfinite(float(value)) or value < 0:
        raise ValueError
    return value


def _invalid(reason: str) -> RequisicaoSnapshotProcessingRead:
    return RequisicaoSnapshotProcessingRead(
        SnapshotProcessingAuthority.INVALID_AUTHORITATIVE_SNAPSHOT, reason=reason
    )


def read_requisicao_snapshot_for_processing(row) -> RequisicaoSnapshotProcessingRead:
    raw = _value(row, "regra_snapshot_json")
    version_id = _value(row, "atividade_versao_id")
    if raw in (None, "") or version_id in (None, ""):
        return _invalid("mandatory_snapshot_missing")
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return _invalid("snapshot_json_invalid")
    if not isinstance(payload, dict):
        return _invalid("snapshot_json_not_object")
    missing = [key for key in (*IDENTITY_FIELDS, *RULE_FIELDS, *DISPLAY_FIELDS) if key not in payload]
    if missing:
        return _invalid("missing:" + ",".join(missing))
    try:
        identity = {
            "atividade_base_id": _positive_int(payload["atividade_base_id"]),
            "atividade_versao_id": _positive_int(payload["atividade_versao_id"]),
            "atividade_versao_numero": _positive_int(payload["atividade_versao_numero"]),
            "matriz_id_efetiva": _positive_int(payload["matriz_id_efetiva"]),
        }
        for key in ("eixo", "schema_version"):
            item = payload[key]
            if not isinstance(item, str) or not item.strip():
                raise ValueError
            identity[key] = item
        rules = {key: _optional_nonnegative(payload[key]) for key in RULE_FIELDS}
        if any(not isinstance(payload[key], str) or not payload[key].strip() for key in ("nome_exibivel", "tipo_atividade", "grupo")):
            raise ValueError
    except (TypeError, ValueError):
        return _invalid("snapshot_value_invalid")
    if identity["schema_version"] != REQUISICAO_SNAPSHOT_SUPPORTED_SCHEMA:
        return _invalid("unsupported_schema_version")
    if identity["atividade_versao_id"] != version_id:
        return _invalid("activity_version_identity_mismatch")
    return RequisicaoSnapshotProcessingRead(
        SnapshotProcessingAuthority.VALID_AUTHORITATIVE_SNAPSHOT,
        rule=AuthoritativeRequisicaoSnapshotRule(**identity, **rules), payload=payload,
    )


def is_versioned_requisicao_snapshot_display_enabled() -> bool:
    return str(os.getenv("SGAA_VERSIONED_REQUISICAO_SNAPSHOT_DISPLAY", "0")).lower() in {"1", "true", "yes", "on"}


def _load_rule(conn, version_id: int):
    return conn.execute(
        """
        SELECT version.id AS atividade_versao_id,
               version.atividade_base_id, base.nome_conceito AS nome_exibivel,
               version.numero_versao AS atividade_versao_numero,
               version.eixo,
               version.grupo, version.ch_por_evento, version.limite_semestre,
               version.limite_total, version.documentos_json,
               version.observacao_aluno, version.observacao_admin,
               version.vigencia_inicio, version.vigencia_fim,
               version.status AS versao_status
          FROM atividade_versao version
          JOIN atividade_base base ON base.id=version.atividade_base_id
         WHERE version.id=?
        """, (version_id,),
    ).fetchone()


def prepare_versioned_requisicao_snapshot(conn, *, flow_origin: str, aluno_id, atividade_versao_id):
    try:
        resolved = resolver_service.resolver_versao_por_aluno(
            conn, aluno_id=aluno_id, atividade_versao_id=atividade_versao_id
        )
    except Exception as exc:
        raise RequisicaoSnapshotError(RequisicaoSnapshotError.user_message) from exc
    if resolved.get("status") != "resolved":
        raise RequisicaoSnapshotError(RequisicaoSnapshotError.user_message)
    row = _load_rule(conn, int(atividade_versao_id))
    if not row or row["versao_status"] != "ativa":
        raise RequisicaoSnapshotError(RequisicaoSnapshotError.user_message)
    axis = str(row["eixo"]).upper()
    activity_type = "Acadêmica Complementar" if axis == "AAC" else "Extensão Universitária" if axis == "AEU" else None
    if activity_type is None:
        raise RequisicaoSnapshotError(RequisicaoSnapshotError.user_message)
    payload = {
        "atividade_base_id": int(row["atividade_base_id"]),
        "atividade_versao_id": int(row["atividade_versao_id"]),
        "atividade_versao_numero": int(row["atividade_versao_numero"]),
        "eixo": axis, "grupo": str(row["grupo"] or "Sem grupo"),
        "ch_por_evento": row["ch_por_evento"], "limite_semestre": row["limite_semestre"],
        "limite_total": row["limite_total"], "documentos_json": row["documentos_json"] or "[]",
        "observacao_aluno": row["observacao_aluno"], "observacao_admin": row["observacao_admin"],
        "vigencia_inicio": row["vigencia_inicio"], "vigencia_fim": row["vigencia_fim"],
        "versao_status": row["versao_status"], "matriz_id_efetiva": int(resolved["matriz_id_efetiva"]),
        "nome_exibivel": str(row["nome_exibivel"]), "tipo_atividade": activity_type,
        "flow_origin": str(flow_origin), "schema_version": REQUISICAO_SNAPSHOT_SUPPORTED_SCHEMA,
        "snapshot_written_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"),
    }
    transition = conn.execute(
        """SELECT tipo_transicao,from_atividade_versao_id,to_atividade_versao_id,justificativa
             FROM atividade_transicao
            WHERE from_atividade_versao_id=? OR to_atividade_versao_id=?
         ORDER BY id LIMIT 1""", (atividade_versao_id, atividade_versao_id),
    ).fetchone()
    if transition:
        payload["transition_provenance"] = {key: transition[key] for key in transition.keys()}
    snapshot_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return PreparedRequisicaoSnapshot(int(atividade_versao_id), snapshot_json, payload)


def _build_admin_requisicao_snapshot_diagnostic(row) -> dict[str, object] | None:
    read = read_requisicao_snapshot_for_processing(row)
    if read.authority is SnapshotProcessingAuthority.VALID_AUTHORITATIVE_SNAPSHOT:
        return {"status": "valid", "reason": None, "payload": read.payload}
    return {"status": "invalid", "reason": read.reason, "payload": None}


__all__ = [
    "AuthoritativeRequisicaoSnapshotRule", "PreparedRequisicaoSnapshot",
    "RequisicaoSnapshotError", "RequisicaoSnapshotProcessingRead",
    "SnapshotProcessingAuthority", "_build_admin_requisicao_snapshot_diagnostic",
    "is_versioned_requisicao_snapshot_display_enabled",
    "prepare_versioned_requisicao_snapshot", "read_requisicao_snapshot_for_processing",
]
