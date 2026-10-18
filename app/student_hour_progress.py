"""A student's hour goal per axis, read against the effective academic Matrix.

The Matrix states mandatory hours for each axis (``horas_aac_obrigatorias``,
``horas_extensao_obrigatorias``), but an axis belongs to a student's goal only
when that Matrix actually offers it: at least one activity version of the axis
linked through ``matriz_atividade_versao_item``, the catalogue
``app.versioning.request_history.list_exact_matrix_activity_catalogue`` reads.
The Matrix is the one ``app.student_matrix.get_effective_matrix_for_student``
resolves; historical requests never decide applicability.

Each axis reads as one of:

- ``APLICAVEL``: offered; progress against its target. A target of 0 means no
  mandatory hours -- no percentage, never a false 100%.
- ``NAO_APLICAVEL``: not offered by the Matrix ("NA"); no target, and it stays
  out of the total.
- ``INDEFINIDO``: the student has no effective Matrix, so applicability is
  unknown -- which is not "NA".

The total runs over the applicable axes with a stated target, with the same
arithmetic the dashboard always used (rounded down, not capped); it is "NA"
when the Matrix offers neither axis.

A target stated for an axis the Matrix does not offer is an inconsistency of
the Matrix record. It is reported (``HourProgress.inconsistencies`` and a
warning naming the Matrix) and never corrected here.
"""

import logging
from dataclasses import dataclass

from app.student_matrix import get_effective_matrix_for_student
from app.versioning.request_history import (
    AAC_ACTIVITY_TYPE,
    AEU_ACTIVITY_TYPE,
    list_exact_matrix_activity_catalogue,
)

logger = logging.getLogger(__name__)

APLICAVEL = "aplicavel"
NAO_APLICAVEL = "nao_aplicavel"
INDEFINIDO = "indefinido"

AXIS_AAC = "AAC"
AXIS_AEU = "AEU"
_AXIS_ACTIVITY_TYPE = {AXIS_AAC: AAC_ACTIVITY_TYPE, AXIS_AEU: AEU_ACTIVITY_TYPE}
_AXIS_TARGET_COLUMN = {
    AXIS_AAC: "horas_aac_obrigatorias",
    AXIS_AEU: "horas_extensao_obrigatorias",
}


@dataclass(frozen=True)
class AxisProgress:
    """Progress of one axis, or of the total over the applicable axes."""

    state: str
    #: Approved hours counted toward this goal (0 unless APLICAVEL).
    completed: float = 0.0
    #: Mandatory hours; None unless APLICAVEL (0 there means no target).
    target: float | None = None
    #: Whole percent, rounded down; None without a positive target.
    pct: int | None = None

    @property
    def has_target(self) -> bool:
        return self.state == APLICAVEL and bool(self.target)


@dataclass(frozen=True)
class HourProgress:
    aac: AxisProgress
    aeu: AxisProgress
    total: AxisProgress
    #: Axes whose Matrix states a positive target but offers no activity.
    inconsistencies: tuple[str, ...] = ()


def _target(matriz, axis: str) -> float:
    try:
        return max(0.0, float(matriz[_AXIS_TARGET_COLUMN[axis]] or 0))
    except (TypeError, ValueError):
        return 0.0


def _applicable(completed: float, target: float, *, cap: bool) -> AxisProgress:
    pct = None
    if target > 0:
        pct = int(completed * 100 // target)
        if cap:
            pct = min(100, pct)
    return AxisProgress(state=APLICAVEL, completed=completed, target=target, pct=pct)


def read_student_hour_progress(conn, aluno_id: int, *, completed_aac, completed_aeu) -> HourProgress:
    """The student's AAC, AEU and total hour progress under their Matrix.

    ``completed_aac`` and ``completed_aeu`` are the approved hours already read
    from the student's history; they are only counted, never rewritten.
    """
    matriz = get_effective_matrix_for_student(conn, aluno_id)
    if matriz is None:
        undefined = AxisProgress(state=INDEFINIDO)
        return HourProgress(aac=undefined, aeu=undefined, total=undefined)

    offered = {
        row["tipo_atividade"]
        for row in list_exact_matrix_activity_catalogue(conn, matriz["id"])
    }
    completed = {AXIS_AAC: float(completed_aac or 0), AXIS_AEU: float(completed_aeu or 0)}
    axes = {}
    inconsistencies = []
    for axis, activity_type in _AXIS_ACTIVITY_TYPE.items():
        target = _target(matriz, axis)
        if activity_type in offered:
            axes[axis] = _applicable(completed[axis], target, cap=True)
            continue
        axes[axis] = AxisProgress(state=NAO_APLICAVEL)
        if target > 0:
            inconsistencies.append(axis)
            logger.warning(
                "event=matrix_axis_target_without_activities matriz_id=%r axis=%s target=%r",
                matriz["id"],
                axis,
                target,
            )

    applicable = [item for item in axes.values() if item.state == APLICAVEL]
    if applicable:
        # The goal is the sum of the stated targets; an axis without one shows
        # its own hours but cannot inflate the total percentage.
        with_target = [item for item in applicable if item.has_target]
        counted = with_target or applicable
        total = _applicable(
            sum(item.completed for item in counted),
            sum(item.target for item in with_target),
            cap=False,
        )
    else:
        total = AxisProgress(state=NAO_APLICAVEL)
    return HourProgress(
        aac=axes[AXIS_AAC],
        aeu=axes[AXIS_AEU],
        total=total,
        inconsistencies=tuple(inconsistencies),
    )


__all__ = [
    "APLICAVEL",
    "AXIS_AAC",
    "AXIS_AEU",
    "AxisProgress",
    "HourProgress",
    "INDEFINIDO",
    "NAO_APLICAVEL",
    "read_student_hour_progress",
]
