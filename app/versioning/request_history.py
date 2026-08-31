from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from app.versioning.snapshots import (
    SnapshotProcessingAuthority,
    read_requisicao_snapshot_for_processing,
)

AAC_ACTIVITY_TYPE = "Acadêmica Complementar"
AEU_ACTIVITY_TYPE = "Extensão Universitária"
APPROVED_STATUSES = ("Deferida", "Deferida Parcialmente")


class HistoricalRequestAuthorityError(RuntimeError):
    def __init__(self, request_id, reason: str):
        self.request_id, self.reason = request_id, reason
        super().__init__(f"historical request authority unavailable: {request_id}: {reason}")


@dataclass(frozen=True)
class HistoricalRequestRead:
    request_id: int
    aluno_id: int | None
    turma_id: int | None
    atividade_base_id: int
    atividade_versao_id: int
    authority: SnapshotProcessingAuthority
    tipo_atividade: str
    eixo: str
    grupo: str
    nome: str
    limite_total: float | int | None
    limite_semestre: float | int | None
    data_evento: str | None
    status: str
    approved_hours: float


def _value(row, key, default=None):
    if isinstance(row, dict): return row.get(key, default)
    try: return row[key]
    except (IndexError, KeyError, TypeError): return default


def _approved_hours(row) -> float:
    raw = _value(row, "horas_deferidas")
    if raw is None: raw = _value(row, "horas_solicitadas")
    try: return float(raw or 0)
    except (TypeError, ValueError): return 0.0


def read_historical_request(row) -> HistoricalRequestRead:
    snapshot = read_requisicao_snapshot_for_processing(row)
    request_id = int(_value(row, "id") or 0)
    if snapshot.authority is not SnapshotProcessingAuthority.VALID_AUTHORITATIVE_SNAPSHOT:
        raise HistoricalRequestAuthorityError(request_id, snapshot.reason or "invalid_snapshot")
    rule, payload = snapshot.rule, snapshot.payload or {}
    assert rule is not None
    try:
        name = str(payload["nome_exibivel"]).strip()
        activity_type = str(payload["tipo_atividade"]).strip()
        group = str(payload["grupo"]).strip()
    except (KeyError, TypeError, ValueError) as exc:
        raise HistoricalRequestAuthorityError(request_id, "snapshot_information_gap") from exc
    expected_type = AAC_ACTIVITY_TYPE if rule.eixo == "AAC" else AEU_ACTIVITY_TYPE if rule.eixo == "AEU" else None
    if not name or not group or activity_type != expected_type:
        raise HistoricalRequestAuthorityError(request_id, "snapshot_classification_invalid")
    return HistoricalRequestRead(
        request_id=request_id, aluno_id=_value(row, "aluno_id"), turma_id=_value(row, "turma_id"),
        atividade_base_id=rule.atividade_base_id, atividade_versao_id=rule.atividade_versao_id,
        authority=snapshot.authority, tipo_atividade=activity_type, eixo=rule.eixo,
        grupo=group, nome=name, limite_total=rule.limite_total,
        limite_semestre=rule.limite_semestre, data_evento=_value(row, "data_evento"),
        status=str(_value(row, "status") or ""), approved_hours=_approved_hours(row),
    )


def read_request_presentation(row) -> HistoricalRequestRead:
    return read_historical_request(row)


def filter_historical_request_rows(rows: Iterable[object], *, tipo_filters=(), grupo_filters=(), atividade_filters=(), query="", extra_search_values: Callable[[object], Iterable[object]] | None=None):
    tipos, grupos, atividades = ({str(v).strip() for v in values if str(v).strip()} for values in (tipo_filters, grupo_filters, atividade_filters))
    needle, selected = str(query or "").strip().casefold(), []
    for row in rows:
        history = read_request_presentation(row)
        if tipos and history.tipo_atividade not in tipos: continue
        if grupos and history.grupo not in grupos: continue
        if atividades and history.nome not in atividades: continue
        values = [history.nome, history.tipo_atividade, history.grupo, history.status]
        if extra_search_values: values.extend(extra_search_values(row))
        if needle and not any(needle in str(v or "").casefold() for v in values): continue
        selected.append((row, history))
    return selected


def list_approved_request_history(conn, *, aluno_id=None, turma_id=None, active_students_only=False):
    conditions, params = ["r.status IN (?,?)"], list(APPROVED_STATUSES)
    if aluno_id is not None: conditions.append("r.aluno_id=?"); params.append(aluno_id)
    if turma_id is not None: conditions.append("student.turma_id=?"); params.append(turma_id)
    if active_students_only: conditions.append("student.status='Ativo'")
    rows = conn.execute(
        f"""SELECT r.*,student.turma_id FROM requisicoes r
              LEFT JOIN alunos student ON student.id=r.aluno_id
             WHERE {' AND '.join(conditions)} ORDER BY r.id""", params,
    ).fetchall()
    return [read_historical_request(row) for row in rows]


def list_exact_matrix_activity_catalogue(conn, matriz_id: int):
    rows = conn.execute(
        """SELECT version.id, version.id AS atividade_versao_id,
                  selected.atividade_base_id, base.nome_conceito AS nome,
                  CASE version.eixo WHEN 'AAC' THEN 'Acadêmica Complementar' ELSE 'Extensão Universitária' END AS tipo_atividade,
                  version.grupo, version.ch_por_evento,
                  version.limite_total AS limite_horas_total,
                  version.limite_semestre AS limite_horas_semestral,
                  version.documentos_json
             FROM matriz_atividade_versao_item selected
             JOIN atividade_versao version ON version.id=selected.atividade_versao_id
             JOIN atividade_base base ON base.id=selected.atividade_base_id
            WHERE selected.matriz_id=?
         ORDER BY version.eixo,version.grupo,base.nome_conceito""", (matriz_id,),
    ).fetchall()
    result=[]
    for row in rows:
        item={key:row[key] for key in row.keys()}
        item["tem_limitacao"] = row["limite_horas_total"] is not None or row["limite_horas_semestral"] is not None
        item["tipo_limitacao"] = "semestral" if row["limite_horas_semestral"] is not None else "total"
        item["limite_horas"] = row["limite_horas_semestral"] if row["limite_horas_semestral"] is not None else row["limite_horas_total"]
        result.append(item)
    return result


__all__=["AAC_ACTIVITY_TYPE","AEU_ACTIVITY_TYPE","APPROVED_STATUSES","HistoricalRequestAuthorityError","HistoricalRequestRead","filter_historical_request_rows","list_approved_request_history","list_exact_matrix_activity_catalogue","read_historical_request","read_request_presentation"]
