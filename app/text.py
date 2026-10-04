import unicodedata

from unidecode import unidecode


def normalize_header(text):
    if not isinstance(text, str):
        text = str(text)
    text = unidecode(text)
    return " ".join(text.lower().split())


def human_text_key(value) -> str:
    """Comparison key for HUMAN text: names, titles, descriptions.

    The single SGAA authority for alphabetical ordering and textual search of
    human text. Unicode compatibility decomposition (NFKD), then only the
    combining marks are dropped, then casefold, with whitespace collapsed:
    "Éverto", "éverto" and "EVERTO" all compare as "everto", "Ç" as "c".

    Comparison only -- stored and displayed text is never rewritten. Not for
    e-mails, codes, enum values or other technical tokens, which keep their own
    semantics. SQLite sees this function as ``PTBR_FOLD`` and the collation
    ``PTBR_NOACCENT`` (see ``register_human_text_sql``); the browser mirrors it
    in ``static/js/human-text.js``.
    """
    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    base = "".join(ch for ch in decomposed if not unicodedata.category(ch).startswith("M"))
    return " ".join(base.casefold().split())


def human_text_contains(haystack, needle) -> bool:
    """Human-text search: does ``haystack`` contain ``needle`` under the key?"""
    return human_text_key(needle) in human_text_key(haystack)


def ptbr_text_sort_key(text):
    """Python sort key for human text: empty values last, then the human key.

    The raw text is the final, deterministic tie-break when two values share a
    key ("Everto" before "Éverto"), so the order never depends on input order.
    """
    raw = str(text or "")
    normalized = human_text_key(raw)
    return (normalized == "", normalized, raw)


def ptbr_sqlite_collation(a, b):
    """SQLite collation for accent-insensitive, case-insensitive PT-BR sorting.

    Equal keys compare equal; ORDER BY clauses carry their own id tie-break.
    """
    a_norm = human_text_key(a)
    b_norm = human_text_key(b)
    if a_norm < b_norm:
        return -1
    if a_norm > b_norm:
        return 1
    return 0


def register_human_text_sql(conn) -> None:
    """Expose the human-text authority to SQL on ``conn``.

    ``COLLATE PTBR_NOACCENT`` orders by the human key; ``PTBR_FOLD(x)`` yields
    the key itself, for searches. Any connection running SQL that uses either
    must be registered; ``app.db.get_db_connection`` does it for every request.
    """
    conn.create_collation("PTBR_NOACCENT", ptbr_sqlite_collation)
    conn.create_function("PTBR_FOLD", 1, human_text_key, deterministic=True)
