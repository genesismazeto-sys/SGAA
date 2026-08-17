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
    """An approved request cannot be interpreted without inventing history."""

    def __init__(self, request_id, reason: str):
        self.request_id = request_id
        self.reason = reason
        super().__init__(f"historical request authority unavailable: {request_id}: {reason}")


@dataclass(frozen=True)
class HistoricalRequestRead:
    request_id: int
    aluno_id: int | None
    turma_id: int | None
    atividade_id: int
    atividade_versao_id: int | None
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


def _row_value(row, key, default=None):
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except (IndexError, KeyError, TypeError):
        return default


def _axis_to_activity_type(axis: str) -> str:
    normalized = str(axis or "").strip().upper()
    if normalized == "AAC":
        return AAC_ACTIVITY_TYPE
    if normalized == "AEU":
        return AEU_ACTIVITY_TYPE
    raise ValueError("invalid_snapshot_axis")


def _legacy_type_axis(value: str) -> str | None:
    normalized = str(value or "").strip()
    if normalized == AAC_ACTIVITY_TYPE:
        return "AAC"
    if normalized == AEU_ACTIVITY_TYPE:
        return "AEU"
    return None


def _approved_hours(row) -> float:
    status = str(_row_value(row, "status") or "")
    deferred = _row_value(row, "horas_deferidas")
    raw = deferred if deferred is not None else _row_value(row, "horas_solicitadas")
    try:
        return float(raw or 0)
    except (TypeError, ValueError):
        return 0.0


def _legacy_request_read(row, authority) -> HistoricalRequestRead:
    request_id = int(_row_value(row, "id") or 0)
    live_type = str(_row_value(row, "live_tipo_atividade") or "").strip()
    live_axis = _legacy_type_axis(live_type)
    live_name = str(_row_value(row, "live_nome") or "").strip()
    if live_axis is None:
        raise HistoricalRequestAuthorityError(request_id, "legacy_compatibility_unavailable")
    return HistoricalRequestRead(
        request_id=request_id,
        aluno_id=_row_value(row, "aluno_id"),
        turma_id=_row_value(row, "turma_id"),
        atividade_id=int(_row_value(row, "atividade_id")),
        atividade_versao_id=None,
        authority=authority,
        tipo_atividade=live_type,
        eixo=live_axis,
        grupo=str(_row_value(row, "live_grupo") or "").strip(),
        nome=live_name,
        limite_total=_row_value(row, "live_limite_total"),
        limite_semestre=_row_value(row, "live_limite_semestre"),
        data_evento=_row_value(row, "data_evento"),
        status=str(_row_value(row, "status") or ""),
        approved_hours=_approved_hours(row),
    )


def read_historical_request(row) -> HistoricalRequestRead:
    snapshot = read_requisicao_snapshot_for_processing(row)
    request_id = int(_row_value(row, "id") or 0)
    if snapshot.authority is SnapshotProcessingAuthority.INVALID_AUTHORITATIVE_SNAPSHOT:
        raise HistoricalRequestAuthorityError(request_id, snapshot.reason or "invalid_snapshot")

    if snapshot.authority is SnapshotProcessingAuthority.VALID_AUTHORITATIVE_SNAPSHOT:
        rule = snapshot.rule
        assert rule is not None
        payload = snapshot.payload or {}
        required = ("grupo", "tipo_atividade_legacy", "nome_exibivel", "nome_legacy")
        missing = [key for key in required if key not in payload]
        if missing:
            raise HistoricalRequestAuthorityError(
                request_id, "snapshot_information_gap:" + ",".join(missing)
            )
        grupo = payload["grupo"]
        legacy_type = payload["tipo_atividade_legacy"]
        nome_legacy = payload["nome_legacy"]
        nome_exibivel = payload["nome_exibivel"]
        if any(
            not isinstance(value, str) or not value.strip()
            for value in (grupo, legacy_type, nome_exibivel)
        ):
            raise HistoricalRequestAuthorityError(request_id, "snapshot_history_value_invalid")
        if nome_legacy is not None and (
            not isinstance(nome_legacy, str) or not nome_legacy.strip()
        ):
            raise HistoricalRequestAuthorityError(request_id, "snapshot_history_value_invalid")
        try:
            tipo_atividade = _axis_to_activity_type(rule.eixo)
        except ValueError as exc:
            raise HistoricalRequestAuthorityError(request_id, str(exc)) from exc
        legacy_axis = _legacy_type_axis(legacy_type)
        if legacy_axis is None or legacy_axis != rule.eixo.strip().upper():
            raise HistoricalRequestAuthorityError(
                request_id, "snapshot_axis_classification_conflict"
            )
        return HistoricalRequestRead(
            request_id=request_id,
            aluno_id=_row_value(row, "aluno_id"),
            turma_id=_row_value(row, "turma_id"),
            atividade_id=rule.atividade_id_legacy,
            atividade_versao_id=rule.atividade_versao_id,
            authority=snapshot.authority,
            tipo_atividade=tipo_atividade,
            eixo=rule.eixo.strip().upper(),
            grupo=grupo,
            nome=nome_exibivel,
            limite_total=rule.limite_total,
            limite_semestre=rule.limite_semestre,
            data_evento=_row_value(row, "data_evento"),
            status=str(_row_value(row, "status") or ""),
            approved_hours=_approved_hours(row),
        )

    return _legacy_request_read(row, snapshot.authority)


def read_request_presentation(row) -> HistoricalRequestRead:
    """Use frozen identity when valid; keep legacy display only for non-approved invalid rows."""
    try:
        return read_historical_request(row)
    except HistoricalRequestAuthorityError:
        if str(_row_value(row, "status") or "") in APPROVED_STATUSES:
            raise
        snapshot = read_requisicao_snapshot_for_processing(row)
        return _legacy_request_read(row, snapshot.authority)


def filter_historical_request_rows(
    rows: Iterable[object],
    *,
    tipo_filters: Iterable[str] = (),
    grupo_filters: Iterable[str] = (),
    atividade_filters: Iterable[str] = (),
    query: str = "",
    extra_search_values: Callable[[object], Iterable[object]] | None = None,
) -> list[tuple[object, HistoricalRequestRead]]:
    """Apply list inclusion using the same effective identity used for rendering."""
    tipos = {str(value).strip() for value in tipo_filters if str(value).strip()}
    grupos = {str(value).strip() for value in grupo_filters if str(value).strip()}
    atividades = {str(value).strip() for value in atividade_filters if str(value).strip()}
    needle = str(query or "").strip().casefold()
    selected: list[tuple[object, HistoricalRequestRead]] = []

    for row in rows:
        history = read_request_presentation(row)
        if tipos and history.tipo_atividade not in tipos:
            continue
        if grupos and history.grupo not in grupos:
            continue
        if atividades and history.nome not in atividades:
            continue
        if needle:
            values: list[object] = [
                history.nome,
                history.tipo_atividade,
                history.grupo,
                history.status,
            ]
            if extra_search_values is not None:
                values.extend(extra_search_values(row))
            if not any(needle in str(value or "").casefold() for value in values):
                continue
        selected.append((row, history))
    return selected


def list_approved_request_history(
    conn,
    *,
    aluno_id: int | None = None,
    turma_id: int | None = None,
    active_students_only: bool = False,
) -> list[HistoricalRequestRead]:
    conditions = ["r.status IN (?, ?)"]
    params: list[object] = list(APPROVED_STATUSES)
    if aluno_id is not None:
        conditions.append("r.aluno_id = ?")
        params.append(aluno_id)
    if turma_id is not None:
        conditions.append("student.turma_id = ?")
        params.append(turma_id)
    if active_students_only:
        conditions.append("student.status = 'Ativo'")
    activity_columns = {
        row["name"] if hasattr(row, "keys") else row[1]
        for row in conn.execute("PRAGMA table_info(atividades)").fetchall()
    }

    def live_column(column: str, alias: str) -> str:
        return f"live.{column} AS {alias}" if column in activity_columns else f"NULL AS {alias}"

    live_columns_sql = ",\n               ".join(
        (
            live_column("nome", "live_nome"),
            live_column("tipo_atividade", "live_tipo_atividade"),
            live_column("grupo", "live_grupo"),
            live_column("limite_horas_total", "live_limite_total"),
            live_column("limite_horas_semestral", "live_limite_semestre"),
        )
    )
    rows = conn.execute(
        f"""
        SELECT r.*,
               student.turma_id,
               {live_columns_sql}
          FROM requisicoes r
          LEFT JOIN alunos student ON student.id = r.aluno_id
          LEFT JOIN atividades live ON live.id = r.atividade_id
         WHERE {' AND '.join(conditions)}
      ORDER BY r.id
        """,
        params,
    ).fetchall()
    return [read_historical_request(row) for row in rows]


def list_exact_matrix_activity_catalogue(conn, matriz_id: int) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT av.id AS atividade_versao_id,
               av.eixo,
               av.grupo,
               av.limite_total,
               av.limite_semestre,
               ab.nome_conceito,
               live.id AS atividade_id,
               live.nome AS legacy_nome
          FROM matriz_atividade_versao_item selected
          JOIN atividade_versao av ON av.id = selected.atividade_versao_id
          JOIN atividade_base ab ON ab.id = av.atividade_base_id
          LEFT JOIN atividade_legacy_map legacy_map
            ON legacy_map.atividade_base_id = av.atividade_base_id
           AND EXISTS (
                SELECT 1
                  FROM matrizes_atividades_itens legacy_selected
                 WHERE legacy_selected.matriz_id = selected.matriz_id
                   AND legacy_selected.atividade_id = legacy_map.atividade_id_legacy
           )
          LEFT JOIN atividades live ON live.id = legacy_map.atividade_id_legacy
         WHERE selected.matriz_id = ?
      ORDER BY av.id, live.id
        """,
        (matriz_id,),
    ).fetchall()
    if not rows:
        legacy_rows = conn.execute(
            """
            SELECT live.*
              FROM matrizes_atividades_itens selected
              JOIN atividades live ON live.id = selected.atividade_id
             WHERE selected.matriz_id = ?
          ORDER BY live.tipo_atividade, live.grupo, live.nome, live.id
            """,
            (matriz_id,),
        ).fetchall()
        return [
            {
                **{key: row[key] for key in row.keys()},
                "atividade_versao_id": None,
            }
            for row in legacy_rows
        ]

    catalogue = []
    seen_versions = set()
    for row in rows:
        version_id = int(row["atividade_versao_id"])
        if version_id in seen_versions:
            continue
        seen_versions.add(version_id)
        tipo_atividade = _axis_to_activity_type(row["eixo"])
        catalogue.append(
            {
                "id": int(row["atividade_id"] or -version_id),
                "atividade_versao_id": version_id,
                "nome": row["legacy_nome"] or row["nome_conceito"],
                "tipo_atividade": tipo_atividade,
                "grupo": row["grupo"],
                "tem_limitacao": row["limite_total"] is not None
                or row["limite_semestre"] is not None,
                "tipo_limitacao": (
                    "semestral" if row["limite_semestre"] is not None else "total"
                ),
                "limite_horas_total": row["limite_total"],
                "limite_horas_semestral": row["limite_semestre"],
                "limite_horas": row["limite_semestre"]
                if row["limite_semestre"] is not None
                else row["limite_total"],
            }
        )
    return catalogue


__all__ = [
    "AAC_ACTIVITY_TYPE",
    "AEU_ACTIVITY_TYPE",
    "APPROVED_STATUSES",
    "HistoricalRequestAuthorityError",
    "HistoricalRequestRead",
    "filter_historical_request_rows",
    "list_approved_request_history",
    "list_exact_matrix_activity_catalogue",
    "read_historical_request",
    "read_request_presentation",
]
