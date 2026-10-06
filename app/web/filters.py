import datetime
import re

from flask import request

from app.sql_dialect import ascii_ci_like, human_text_contains
from app.text import human_text_key


def append_conditions_sql(base_has_where: bool, conditions: list[str], joiner: str = " AND ") -> str:
    """Monta trecho SQL de condições a partir de uma lista de strings.
    - Se base_has_where=True, prefixa com " AND "; caso contrário, com " WHERE ".
    - Retorna string vazia quando não há condições.
    """
    if not conditions:
        return ""
    return (" AND " if base_has_where else " WHERE ") + joiner.join(conditions)


def get_multi_query_values(name: str) -> list[str]:
    values = request.args.getlist(name)
    if not values and name in request.args:
        values = [request.args.get(name)]

    normalized = []
    seen = set()
    for value in values:
        if value is None:
            continue
        parts = [str(value)]
        if isinstance(value, str) and ("," in value or ";" in value):
            parts = re.split(r"\s*[,;]\s*", value)
        for part in parts:
            item = str(part or "").strip()
            if not item or item in seen:
                continue
            seen.add(item)
            normalized.append(item)
    return normalized


def get_text_query_value(name: str) -> str:
    return " ".join(str(request.args.get(name) or "").split())


def get_int_multi_query_values(name: str) -> list[int]:
    values = []
    for raw in get_multi_query_values(name):
        try:
            values.append(int(raw))
        except (TypeError, ValueError):
            continue
    return values


def get_number_range_query(name: str, caster=int):
    def _parse(raw):
        raw = str(raw or "").strip()
        if not raw:
            return None
        try:
            return caster(raw)
        except (TypeError, ValueError):
            return None

    return _parse(request.args.get(f"{name}_min")), _parse(request.args.get(f"{name}_max"))


def get_date_range_query(name: str):
    def _parse(raw):
        raw = str(raw or "").strip()
        if not raw:
            return None
        try:
            return datetime.datetime.strptime(raw[:10], "%Y-%m-%d").date().isoformat()
        except (TypeError, ValueError):
            return None

    return _parse(request.args.get(f"{name}_min")), _parse(request.args.get(f"{name}_max"))


def append_text_contains_condition(
    conditions: list[str], params: list, sql_expression: str, value: str, *, connection
) -> None:
    """Technical-token contains filter (e-mails, codes, matrículas).

    SQLite LIKE semantics on every engine (``app.sql_dialect.ascii_ci_like``):
    ASCII case-insensitive, no escape character.
    """
    if not value:
        return
    conditions.append(ascii_ci_like(f"LOWER(COALESCE({sql_expression}, ''))", connection=connection))
    params.append(f"%{value.lower()}%")


def human_text_contains_sql(sql_expression: str, *, connection) -> str:
    """SQL predicate: HUMAN text ``sql_expression`` contains the bound needle.

    Bind ``human_text_key(value)``. Both sides go through the one authority
    (``app.text.human_text_key``: ``PTBR_FOLD`` on SQLite,
    ``sgaa_human_text_key`` on PostgreSQL), so case and accents never decide a
    match. A literal substring test: ``%`` and ``_`` in the user's text are not
    wildcards.
    """
    return human_text_contains(sql_expression, connection=connection)


def append_human_text_contains_condition(
    conditions: list[str], params: list, sql_expression: str, value: str, *, connection
) -> None:
    """``append_text_contains_condition`` for names, titles and descriptions.

    E-mails, codes and matrículas keep ``append_text_contains_condition``.
    """
    needle = human_text_key(value)
    if not needle:
        return
    conditions.append(human_text_contains_sql(sql_expression, connection=connection))
    params.append(needle)
