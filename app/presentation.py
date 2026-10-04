import datetime
import re

_INTERNAL_SEMESTER_RE = re.compile(r"^(\d{4})/([12])$")
_DISPLAY_SEMESTER_RE = re.compile(r"^([12])S/(\d{4})$")


def format_semester_label(value, semester=None) -> str:
    """Canonical human label for a calendar academic semester (``NS/YYYY``).

    Scope is strictly a year half: ``semestre`` is 1 (Jan-Jun) or 2 (Jul-Dec),
    so internal ``YYYY/N`` becomes ``NS/YYYY`` (e.g. ``2026/2`` -> ``2S/2026``).
    Accepts the internal string or a separate ``ano`` + ``semestre`` pair, is
    idempotent for an already formatted ``NS/YYYY`` label, and returns ``""``
    for ``None``, blank or unrecognized input.

    Curricular/course periods (``cursos.duracao_periodos``,
    ``app.views.admin.dashboard.periodo_corrente``) are a different concept with
    ordinals above 2 and must never be routed here; values like ``2028/4``,
    ``3S/2028`` or a matrix code such as ``01.2025`` return ``""`` instead of a
    misleading semester label.
    """
    if semester is not None:
        value = f"{value}/{semester}"
    raw = str(value or "").strip()
    if not raw:
        return ""
    match = _INTERNAL_SEMESTER_RE.fullmatch(raw)
    if match:
        return f"{match.group(2)}S/{match.group(1)}"
    if _DISPLAY_SEMESTER_RE.fullmatch(raw):
        return raw
    return ""


def _format_bytes_label(size_bytes):
    if size_bytes in (None, ""):
        return "-"
    size = float(size_bytes)
    units = ("B", "KB", "MB", "GB")
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
        size /= 1024
    return f"{int(size_bytes)} B"


def format_date_ptbr(value) -> str:
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%d/%m/%Y")
    raw = str(value).strip()
    if not raw:
        return ""
    base = raw.split(" ")[0].split("T")[0]
    try:
        return datetime.datetime.strptime(base, "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return raw
