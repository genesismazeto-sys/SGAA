import datetime


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
