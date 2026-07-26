import datetime


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
