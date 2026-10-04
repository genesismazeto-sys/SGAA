"""Canonical per-activity limitation authority for requests.

A limitation always belongs to one conceptual Activity (``atividade_base``)
under one frozen rule -- never to its display group. This module is the single
authority used by the student dashboard panel and by admin deferment
enforcement, so both count exactly the same hours.

Numerator rules
---------------

- Only approved requests (``Deferida`` / ``Deferida Parcialmente``) count.
- Only requests whose frozen rule is the same activity, axis and limits
  (``atividade_base_id`` + ``eixo`` + ``limite_semestre`` + ``limite_total``)
  participate. Historical versions with a materially different rule keep their
  own line; a current version never rewrites a frozen rule.
- A semester limit counts only requests whose event semester is the requested
  scope semester. The event semester is derived from ``data_evento``:
  January-June = semester 1, July-December = semester 2 of the event year.
- A total limit counts every approved request of that exact rule.

Denominator rules
-----------------

- ``limite_semestre`` for a semester line, ``limite_total`` for a total line.
- An activity without any limit never produces a limitation line.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass
from typing import Any, Iterable

from app.text import human_text_key

AAC_ACTIVITY_TYPE = "Acadêmica Complementar"
AEU_ACTIVITY_TYPE = "Extensão Universitária"
APPROVED_STATUSES = ("Deferida", "Deferida Parcialmente")
SEMESTRAL = "semestral"
TOTAL = "total"


def parse_event_date(value: Any) -> datetime.date | None:
    """Return the event date, or ``None`` when it is absent/unparseable.

    ``data_evento`` is the single calendar authority for the semester of a
    request; there is no separate semester column in the schema.
    """
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.datetime.strptime(raw[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def semester_label_for_date(value: datetime.date | None) -> str | None:
    """Return ``YYYY/N`` for a date (N=1 for Jan-Jun, N=2 for Jul-Dec)."""
    if value is None:
        return None
    return f"{value.year}/{1 if value.month <= 6 else 2}"


def semester_sort_key(label: str) -> tuple[int, int]:
    ano_raw, _, semestre_raw = str(label or "").partition("/")
    try:
        return int(ano_raw), int(semestre_raw)
    except ValueError:
        return (9999, 9)


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _value(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


def _status(row: Any) -> str:
    return str(_value(row, "status", "") or "")


def _request_id(row: Any) -> int | None:
    raw = _value(row, "request_id", _value(row, "id", None))
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _approved_hours(row: Any) -> float:
    raw = _value(row, "approved_hours", None)
    if raw is None:
        raw = _value(row, "horas_deferidas", None)
    if raw is None:
        raw = _value(row, "horas_solicitadas", None)
    try:
        return float(raw or 0)
    except (TypeError, ValueError):
        return 0.0


def _tipo_atividade(eixo: str) -> str:
    return AAC_ACTIVITY_TYPE if eixo == "AAC" else AEU_ACTIVITY_TYPE


def _grupo_order(grupo: str) -> int:
    match = re.search(r"\d+", str(grupo or ""))
    if not match:
        return 9999
    try:
        return int(match.group())
    except ValueError:
        return 9999


def is_same_activity_rule(row: Any, *, atividade_base_id, eixo, limite_semestre, limite_total) -> bool:
    """True when the frozen rule of ``row`` is the exact rule being evaluated."""
    if _value(row, "atividade_base_id") != atividade_base_id:
        return False
    if str(_value(row, "eixo", "") or "") != str(eixo or ""):
        return False
    return _as_float(_value(row, "limite_semestre")) == _as_float(limite_semestre) and _as_float(
        _value(row, "limite_total")
    ) == _as_float(limite_total)


def approved_hours_for_activity_rule(
    history_rows: Iterable[Any],
    *,
    atividade_base_id,
    eixo,
    limite_semestre,
    limite_total,
    semester_label: str | None = None,
    exclude_request_id: int | None = None,
) -> float:
    """Sum approved hours of one exact activity rule, optionally one semester.

    Used by admin deferment enforcement; the same predicate defines which
    requests can participate in any limitation numerator.
    """
    total = 0.0
    for row in history_rows:
        if _status(row) not in APPROVED_STATUSES:
            continue
        if exclude_request_id is not None and _request_id(row) == int(exclude_request_id):
            continue
        if not is_same_activity_rule(
            row,
            atividade_base_id=atividade_base_id,
            eixo=eixo,
            limite_semestre=limite_semestre,
            limite_total=limite_total,
        ):
            continue
        if semester_label is not None:
            row_semester = semester_label_for_date(parse_event_date(_value(row, "data_evento")))
            if row_semester != semester_label:
                continue
        total += _approved_hours(row)
    return round(total, 2)


@dataclass(frozen=True)
class AtividadeRuleSummary:
    """One limitation line: one activity rule plus its own limit."""

    atividade_base_id: int
    eixo: str
    tipo_atividade: str
    grupo: str
    nome: str
    periodicidade: str
    limite: float
    consumido: float

    @property
    def pct(self) -> int:
        if self.limite > 0:
            return int((self.consumido * 100) // self.limite)
        return 100 if self.consumido > 0 else 0


def build_atividade_rule_summary(
    history_rows: Iterable[Any],
    *,
    semester_label: str | None = None,
    exclude_request_id: int | None = None,
) -> list[AtividadeRuleSummary]:
    """Build the canonical per-activity limitation lines of one student.

    ``semester_label`` is the semester scope of ``periodicidade="semestral"``
    lines; callers pass the semester they display (the dashboard uses the
    current one). ``Limite total`` lines always span the whole history.
    """
    rows = list(history_rows)
    groups: dict[tuple, dict[str, Any]] = {}
    for row in rows:
        if _status(row) not in APPROVED_STATUSES:
            continue
        if exclude_request_id is not None and _request_id(row) == int(exclude_request_id):
            continue
        limite_semestre = _as_float(_value(row, "limite_semestre"))
        limite_total = _as_float(_value(row, "limite_total"))
        if limite_semestre is None and limite_total is None:
            continue
        base_id = int(_value(row, "atividade_base_id"))
        eixo = str(_value(row, "eixo", "") or "")
        key = (base_id, eixo, limite_semestre, limite_total)
        entry = groups.get(key)
        if entry is None:
            entry = groups[key] = {
                "atividade_base_id": base_id,
                "eixo": eixo,
                "tipo_atividade": _tipo_atividade(eixo),
                "grupo": str(_value(row, "grupo", "") or ""),
                "nome": str(_value(row, "nome", "") or ""),
                "limite_semestre": limite_semestre,
                "limite_total": limite_total,
                "semestral": 0.0,
                "total": 0.0,
            }
        hours = _approved_hours(row)
        entry["total"] = round(entry["total"] + hours, 2)
        row_semester = semester_label_for_date(parse_event_date(_value(row, "data_evento")))
        if row_semester == semester_label:
            entry["semestral"] = round(entry["semestral"] + hours, 2)

    lines: list[AtividadeRuleSummary] = []
    for entry in groups.values():
        if entry["limite_semestre"] is not None and entry["semestral"] > 0:
            lines.append(
                AtividadeRuleSummary(
                    atividade_base_id=entry["atividade_base_id"],
                    eixo=entry["eixo"],
                    tipo_atividade=entry["tipo_atividade"],
                    grupo=entry["grupo"],
                    nome=entry["nome"],
                    periodicidade=SEMESTRAL,
                    limite=entry["limite_semestre"],
                    consumido=entry["semestral"],
                )
            )
        if entry["limite_total"] is not None and entry["total"] > 0:
            lines.append(
                AtividadeRuleSummary(
                    atividade_base_id=entry["atividade_base_id"],
                    eixo=entry["eixo"],
                    tipo_atividade=entry["tipo_atividade"],
                    grupo=entry["grupo"],
                    nome=entry["nome"],
                    periodicidade=TOTAL,
                    limite=entry["limite_total"],
                    consumido=entry["total"],
                )
            )
    lines.sort(
        key=lambda line: (
            0 if line.eixo == "AAC" else 1,
            _grupo_order(line.grupo),
            human_text_key(line.nome),
            line.atividade_base_id,
            0 if line.periodicidade == SEMESTRAL else 1,
        )
    )
    return lines


__all__ = [
    "AAC_ACTIVITY_TYPE",
    "AEU_ACTIVITY_TYPE",
    "APPROVED_STATUSES",
    "AtividadeRuleSummary",
    "SEMESTRAL",
    "TOTAL",
    "approved_hours_for_activity_rule",
    "build_atividade_rule_summary",
    "is_same_activity_rule",
    "parse_event_date",
    "semester_label_for_date",
    "semester_sort_key",
]
