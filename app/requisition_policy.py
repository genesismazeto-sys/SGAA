"""What a student may still do with an own request, and the return deadline.

A ``Pendente`` request is editable. A ``Devolvida`` request (returned for
correction) is editable until its deadline: ``data_processamento`` plus the
administrator-configured return days (``app.settings.get_return_response_days``;
0 means no deadline). It closes when ``now >= deadline`` -- the same boundary
at which ``app.requisitions.auto_indefer_devolvidas`` expires it. The student
dashboard, the edit and delete permissions and the comprovante authorization
all read this one rule. Every other status, ``Indeferida`` included, is
read-only.
"""

import datetime
import math
from dataclasses import dataclass


def _parse_optional_processing_datetime(data_processamento):
    raw = str(data_processamento or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.datetime.strptime(raw[:19], fmt)
        except ValueError:
            continue
    try:
        return datetime.datetime.strptime(raw[:10], "%Y-%m-%d")
    except ValueError:
        return None


@dataclass(frozen=True)
class ReturnWindow:
    """The open correction window of one returned request."""

    total_days: int
    #: None when no deadline is configured (return days = 0).
    deadline: datetime.datetime | None
    #: Whole days left, rounded up (at least 1 while open); None without a deadline.
    remaining_days: int | None


def open_return_window(status, data_processamento, return_days: int) -> ReturnWindow | None:
    """The request's open correction window, or None when it has none.

    None for any status other than ``Devolvida``, for an unreadable processing
    date (fail closed) and once the deadline has passed.
    """
    if str(status or "").strip() != "Devolvida":
        return None
    processed_at = _parse_optional_processing_datetime(data_processamento)
    if not processed_at:
        return None
    total_days = max(0, int(return_days))
    if total_days == 0:
        return ReturnWindow(total_days=0, deadline=None, remaining_days=None)
    deadline = processed_at + datetime.timedelta(days=total_days)
    left = (deadline - datetime.datetime.now()).total_seconds()
    if left <= 0:
        return None
    return ReturnWindow(
        total_days=total_days,
        deadline=deadline,
        remaining_days=math.ceil(left / 86400),
    )


def can_student_edit_requisition(status, data_processamento, *, return_days: int):
    if str(status or "").strip() == "Pendente":
        return True
    return open_return_window(status, data_processamento, return_days) is not None


def can_student_delete_requisition(status, data_processamento, *, return_days: int):
    return can_student_edit_requisition(status, data_processamento, return_days=return_days)
