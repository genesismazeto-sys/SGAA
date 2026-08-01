from __future__ import annotations

import datetime
from datetime import date

from app.db import (
    DEFAULT_HORAS_ACADEMICA,
    DEFAULT_HORAS_EXTENSAO,
    DEFAULT_RESPONSE_GOAL_DAYS,
    DEFAULT_RETURN_RESPONSE_DAYS,
    _app_settings_defaults,
    ensure_app_settings_schema,
)
from app.presentation import format_date_ptbr


def _normalize_optional_iso_date(value: str, *, allow_empty: bool = False) -> str:
    raw = str(value or "").strip()
    if not raw:
        if allow_empty:
            return ""
        raise ValueError("Informe uma data válida.")
    try:
        parsed = datetime.datetime.strptime(raw[:10], "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("Informe uma data válida no formato AAAA-MM-DD.") from exc
    if parsed > date.today():
        raise ValueError("O início da apuração não pode estar no futuro.")
    return parsed.isoformat()


def get_app_settings(conn) -> dict[str, str]:
    defaults = _app_settings_defaults()
    rows = conn.execute("SELECT chave, valor FROM configuracoes_app").fetchall()
    settings = dict(defaults)
    for row in rows:
        settings[str(row["chave"])] = str(row["valor"])
    return settings


def get_response_time_settings(conn) -> dict[str, object]:
    ensure_app_settings_schema(conn)
    settings = get_app_settings(conn)

    try:
        response_goal_days = max(
            0,
            int(
                str(
                    settings.get("response_goal_days") or DEFAULT_RESPONSE_GOAL_DAYS
                ).strip()
            ),
        )
    except ValueError:
        response_goal_days = DEFAULT_RESPONSE_GOAL_DAYS

    try:
        return_response_days = max(
            0,
            int(
                str(
                    settings.get("return_response_days") or DEFAULT_RETURN_RESPONSE_DAYS
                ).strip()
            ),
        )
    except ValueError:
        return_response_days = DEFAULT_RETURN_RESPONSE_DAYS

    response_metrics_reset_at = ""
    try:
        response_metrics_reset_at = _normalize_optional_iso_date(
            settings.get("response_metrics_reset_at") or "",
            allow_empty=True,
        )
    except ValueError:
        response_metrics_reset_at = ""

    auto_indefer = settings.get("auto_indefer_devolvida", "0") == "1"

    return {
        "response_goal_days": response_goal_days,
        "response_metrics_reset_at": response_metrics_reset_at,
        "response_metrics_reset_at_fmt": (
            format_date_ptbr(response_metrics_reset_at)
            if response_metrics_reset_at
            else ""
        ),
        "return_response_days": return_response_days,
        "auto_indefer_devolvida": auto_indefer,
    }


def save_app_settings(conn, payload: dict[str, str]) -> dict[str, str]:
    ensure_app_settings_schema(conn)

    response_goal_days_raw = str(
        payload.get("response_goal_days") or DEFAULT_RESPONSE_GOAL_DAYS
    ).strip()
    try:
        response_goal_days = max(0, int(response_goal_days_raw))
    except ValueError as exc:
        raise ValueError(
            "A meta de tempo de resposta deve ser um número inteiro maior ou igual a zero."
        ) from exc

    response_metrics_reset_at = _normalize_optional_iso_date(
        payload.get("response_metrics_reset_at") or "",
        allow_empty=True,
    )

    normalized = {
        "response_goal_days": str(response_goal_days),
        "response_metrics_reset_at": response_metrics_reset_at,
    }

    for chave, valor in normalized.items():
        conn.execute(
            """
            INSERT INTO configuracoes_app (chave, valor, atualizado_em)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor, atualizado_em = datetime('now')
            """,
            (chave, valor),
        )
    return normalized


def reset_response_time_metrics(
    conn,
    *,
    reset_at: str | None = None,
) -> dict[str, str]:
    settings = get_app_settings(conn)
    settings["response_metrics_reset_at"] = _normalize_optional_iso_date(
        reset_at or date.today().isoformat()
    )
    return save_app_settings(conn, settings)


def save_return_response_settings(conn, payload: dict[str, str]) -> dict[str, str]:
    ensure_app_settings_schema(conn)

    raw = str(
        payload.get("return_response_days") or DEFAULT_RETURN_RESPONSE_DAYS
    ).strip()
    try:
        days = max(0, int(raw))
    except ValueError as exc:
        raise ValueError(
            "O prazo de adequação deve ser um número inteiro maior ou igual a zero."
        ) from exc

    auto_indefer = (
        "1" if payload.get("auto_indefer_devolvida") in ("1", "on", True) else "0"
    )

    normalized = {
        "return_response_days": str(days),
        "auto_indefer_devolvida": auto_indefer,
    }
    for chave, valor in normalized.items():
        conn.execute(
            """
            INSERT INTO configuracoes_app (chave, valor, atualizado_em)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor, atualizado_em = datetime('now')
            """,
            (chave, valor),
        )
    return normalized


def get_horas_settings(conn) -> dict[str, int]:
    ensure_app_settings_schema(conn)
    settings = get_app_settings(conn)
    try:
        academica = max(
            0,
            int(
                str(
                    settings.get("horas_padrao_academica")
                    or DEFAULT_HORAS_ACADEMICA
                ).strip()
            ),
        )
    except ValueError:
        academica = DEFAULT_HORAS_ACADEMICA
    try:
        extensao = max(
            0,
            int(
                str(
                    settings.get("horas_padrao_extensao") or DEFAULT_HORAS_EXTENSAO
                ).strip()
            ),
        )
    except ValueError:
        extensao = DEFAULT_HORAS_EXTENSAO
    return {
        "horas_padrao_academica": academica,
        "horas_padrao_extensao": extensao,
    }


def save_horas_settings(conn, payload: dict[str, str]) -> dict[str, str]:
    ensure_app_settings_schema(conn)
    defaults = (
        ("horas_padrao_academica", DEFAULT_HORAS_ACADEMICA),
        ("horas_padrao_extensao", DEFAULT_HORAS_EXTENSAO),
    )
    for key, default in defaults:
        raw = str(payload.get(key) or default).strip()
        try:
            value = max(0, int(raw))
        except ValueError as exc:
            raise ValueError(
                "O valor de horas deve ser um número inteiro maior ou igual a zero."
            ) from exc
        conn.execute(
            """
            INSERT INTO configuracoes_app (chave, valor, atualizado_em)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor, atualizado_em = datetime('now')
            """,
            (key, str(value)),
        )
    return {key: str(payload.get(key) or default) for key, default in defaults}


__all__ = [
    "_normalize_optional_iso_date",
    "get_app_settings",
    "get_horas_settings",
    "get_response_time_settings",
    "reset_response_time_metrics",
    "save_app_settings",
    "save_horas_settings",
    "save_return_response_settings",
]
