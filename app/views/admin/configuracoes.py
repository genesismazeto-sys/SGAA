from __future__ import annotations

import datetime
from datetime import date

from flask import Blueprint, redirect, render_template, request, url_for

from app.auth import admin_required
from app.db import (
    DEFAULT_HORAS_ACADEMICA,
    DEFAULT_HORAS_EXTENSAO,
    DEFAULT_RESPONSE_GOAL_DAYS,
    DEFAULT_RETURN_RESPONSE_DAYS,
    _app_settings_defaults,
    ensure_app_settings_schema,
    get_db_connection,
)
from app.presentation import format_date_ptbr
from app.views.admin import LegacyRouteSpec, configure_legacy_routes
from utils.messages import (
    flash,
    list_editable_messages,
    reset_message_override,
    save_message_override,
)


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


@admin_required
def admin_configuracoes():
    conn = get_db_connection()
    return render_template(
        "admin_configuracoes.html",
        response_settings=get_response_time_settings(conn),
        horas_settings=get_horas_settings(conn),
    )


@admin_required
def admin_configuracoes_horas_padrao_salvar():
    conn = get_db_connection()
    try:
        save_horas_settings(
            conn,
            {
                "horas_padrao_academica": request.form.get("horas_padrao_academica")
                or str(DEFAULT_HORAS_ACADEMICA),
                "horas_padrao_extensao": request.form.get("horas_padrao_extensao")
                or str(DEFAULT_HORAS_EXTENSAO),
            },
        )
        conn.commit()
    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "error")
        return redirect(url_for("admin_configuracoes"))
    flash("Padrão de horas atualizado com sucesso.", "success")
    return redirect(url_for("admin_configuracoes"))


@admin_required
def admin_configuracoes_prazo_adequacao_salvar():
    conn = get_db_connection()
    try:
        save_return_response_settings(
            conn,
            {
                "return_response_days": request.form.get("return_response_days")
                or str(DEFAULT_RETURN_RESPONSE_DAYS),
                "auto_indefer_devolvida": request.form.get("auto_indefer_devolvida")
                or "0",
            },
        )
        conn.commit()
    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "error")
        return redirect(url_for("admin_configuracoes"))
    flash(
        "Prazo de adequação de solicitações devolvidas atualizado com sucesso.",
        "success",
    )
    return redirect(url_for("admin_configuracoes"))


@admin_required
def admin_configuracoes_tempo_resposta_salvar():
    conn = get_db_connection()
    try:
        save_app_settings(
            conn,
            {
                "response_goal_days": request.form.get("response_goal_days")
                or str(DEFAULT_RESPONSE_GOAL_DAYS),
                "response_metrics_reset_at": request.form.get(
                    "response_metrics_reset_at"
                )
                or "",
            },
        )
        conn.commit()
    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "error")
        return redirect(url_for("admin_configuracoes"))
    flash(
        "Configurações de tempo de resposta atualizadas com sucesso.",
        "success",
    )
    return redirect(url_for("admin_configuracoes"))


@admin_required
def admin_configuracoes_tempo_resposta_resetar():
    conn = get_db_connection()
    reset_response_time_metrics(conn)
    conn.commit()
    flash("Apuração do tempo de resposta reiniciada a partir de hoje.", "success")
    return redirect(url_for("admin_configuracoes"))


@admin_required
def admin_mensagens():
    conn = get_db_connection()
    messages = list_editable_messages(conn)
    return render_template(
        "admin_mensagens.html",
        messages=messages,
        total_messages=len(messages),
        overridden_messages=sum(1 for item in messages if item["is_overridden"]),
    )


@admin_required
def admin_mensagens_salvar():
    conn = get_db_connection()
    try:
        save_message_override(
            conn,
            request.form.get("message_key") or "",
            request.form.get("message_text") or "",
        )
        conn.commit()
    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "error")
        return redirect(url_for("admin_mensagens"))
    flash("Mensagem atualizada com sucesso.", "success")
    return redirect(url_for("admin_mensagens"))


@admin_required
def admin_mensagens_resetar(message_key: str):
    conn = get_db_connection()
    try:
        reset_message_override(conn, message_key)
        conn.commit()
    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "error")
        return redirect(url_for("admin_mensagens"))
    flash("Mensagem restaurada para o padrão.", "success")
    return redirect(url_for("admin_mensagens"))


bp_admin_configuracoes = Blueprint("admin_configuracoes_blueprint", __name__)

LEGACY_ROUTE_SPECS = configure_legacy_routes(
    bp_admin_configuracoes,
    (
        LegacyRouteSpec(
            "/admin/configuracoes",
            "admin_configuracoes",
            admin_configuracoes,
            ("GET",),
        ),
        LegacyRouteSpec(
            "/admin/configuracoes/horas-padrao",
            "admin_configuracoes_horas_padrao_salvar",
            admin_configuracoes_horas_padrao_salvar,
            ("POST",),
        ),
        LegacyRouteSpec(
            "/admin/configuracoes/prazo-adequacao",
            "admin_configuracoes_prazo_adequacao_salvar",
            admin_configuracoes_prazo_adequacao_salvar,
            ("POST",),
        ),
        LegacyRouteSpec(
            "/admin/configuracoes/tempo-resposta",
            "admin_configuracoes_tempo_resposta_salvar",
            admin_configuracoes_tempo_resposta_salvar,
            ("POST",),
        ),
        LegacyRouteSpec(
            "/admin/configuracoes/tempo-resposta/reset",
            "admin_configuracoes_tempo_resposta_resetar",
            admin_configuracoes_tempo_resposta_resetar,
            ("POST",),
        ),
        LegacyRouteSpec(
            "/admin/mensagens",
            "admin_mensagens",
            admin_mensagens,
            ("GET",),
        ),
        LegacyRouteSpec(
            "/admin/mensagens/salvar",
            "admin_mensagens_salvar",
            admin_mensagens_salvar,
            ("POST",),
        ),
        LegacyRouteSpec(
            "/admin/mensagens/<message_key>/reset",
            "admin_mensagens_resetar",
            admin_mensagens_resetar,
            ("POST",),
        ),
    ),
)


__all__ = [
    "LEGACY_ROUTE_SPECS",
    "admin_configuracoes",
    "admin_configuracoes_horas_padrao_salvar",
    "admin_configuracoes_prazo_adequacao_salvar",
    "admin_configuracoes_tempo_resposta_resetar",
    "admin_configuracoes_tempo_resposta_salvar",
    "admin_mensagens",
    "admin_mensagens_resetar",
    "admin_mensagens_salvar",
    "bp_admin_configuracoes",
    "get_app_settings",
    "get_horas_settings",
    "get_response_time_settings",
    "reset_response_time_metrics",
    "save_app_settings",
    "save_horas_settings",
    "save_return_response_settings",
    "_normalize_optional_iso_date",
]
