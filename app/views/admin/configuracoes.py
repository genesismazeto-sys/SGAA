from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, url_for

from app.auth import admin_required
from app.db import (
    DEFAULT_HORAS_ACADEMICA,
    DEFAULT_HORAS_EXTENSAO,
    DEFAULT_RESPONSE_GOAL_DAYS,
    DEFAULT_RETURN_RESPONSE_DAYS,
    get_db_connection,
)
from app.settings import (
    _normalize_optional_iso_date,
    get_app_settings,
    get_horas_settings,
    get_response_time_settings,
    reset_response_time_metrics,
    save_app_settings,
    save_horas_settings,
    save_return_response_settings,
)
from app.views.admin import LegacyRouteSpec, configure_legacy_routes
from utils.messages import (
    flash,
    list_editable_messages,
    reset_message_override,
    save_message_override,
)


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
