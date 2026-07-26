from unidecode import unidecode


def normalize_header(text):
    if not isinstance(text, str):
        text = str(text)
    text = unidecode(text)
    return " ".join(text.lower().split())


def ptbr_text_sort_key(text):
    normalized = " ".join(unidecode(str(text or "")).casefold().split())
    return (normalized == "", normalized)


def ptbr_sqlite_collation(a, b):
    """SQLite collation for accent-insensitive, case-insensitive PT-BR sorting."""
    a_norm = " ".join(unidecode(str(a or "")).casefold().split())
    b_norm = " ".join(unidecode(str(b or "")).casefold().split())
    if a_norm < b_norm:
        return -1
    if a_norm > b_norm:
        return 1
    return 0
