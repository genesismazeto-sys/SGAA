# coding: utf-8
"""UT-11: dono canonico do cohort "Alertas".

8 simbolos relocados de main.py por MOVE-VERBATIM (4 rotas, 3 helpers e 1
constante). Nenhuma importacao de main; registra apenas rotas legadas via
LegacyRouteSpec.
"""

from __future__ import annotations

import re

from flask import (
    Blueprint,
    redirect,
    render_template,
    request,
    url_for,
)

from app.auth import admin_required
from app.db import get_db_connection
from app.db_maintenance import ensure_admin_alertas_table
from app.views.admin import LegacyRouteSpec, configure_legacy_routes
from app.web.filters import (
    append_conditions_sql,
    append_text_contains_condition,
    get_multi_query_values,
    get_text_query_value,
)
from app.web.pagination import get_pagination, wants_pagination
from utils.messages import flash


ALERTA_COLOR_OPTIONS = [
    {"label": "Azul", "bg": "#e3eefd", "border": "#7e95b2"},
    {"label": "Amarelo", "bg": "#fef4c0", "border": "#c9a227"},
    {"label": "Verde", "bg": "#dcfaeb", "border": "#4ea86a"},
    {"label": "Laranja", "bg": "#ffecd4", "border": "#c07a3a"},
    {"label": "Vermelho", "bg": "#fee2e2", "border": "#bb6464"},
    {"label": "Roxo", "bg": "#ede9fe", "border": "#8872c4"},
    {"label": "Ciano", "bg": "#cffafe", "border": "#3aaab8"},
]


def _normalize_hex_color(value: str | None, fallback: str | None = None) -> str:
    candidate = (value or "").strip().lower()
    if re.fullmatch(r"#[0-9a-f]{3}", candidate):
        candidate = "#" + "".join(ch * 2 for ch in candidate[1:])
    if re.fullmatch(r"#[0-9a-f]{6}", candidate):
        return candidate
    return (fallback or ALERTA_COLOR_OPTIONS[0]["bg"]).strip().lower()


def _derive_border_from_hex(bg_color: str) -> str:
    normalized = _normalize_hex_color(bg_color)
    red = int(normalized[1:3], 16)
    green = int(normalized[3:5], 16)
    blue = int(normalized[5:7], 16)
    luminance = ((0.299 * red) + (0.587 * green) + (0.114 * blue)) / 255
    target = 0 if luminance > 0.72 else 255
    weight = 0.18 if luminance > 0.72 else 0.26

    def _mix(channel: int) -> int:
        return max(0, min(255, round((channel * (1 - weight)) + (target * weight))))

    return "#{:02x}{:02x}{:02x}".format(_mix(red), _mix(green), _mix(blue))


def _alerta_border_for(bg_color: str) -> str:
    normalized = _normalize_hex_color(bg_color)
    for option in ALERTA_COLOR_OPTIONS:
        if option["bg"].lower() == normalized:
            return option["border"]
    return _derive_border_from_hex(normalized)


@admin_required
def admin_alertas():
    page, per_page, offset = get_pagination(default_per_page=25)
    q = (request.args.get("q") or "").strip()
    sort_field = (request.args.get("s") or "titulo").strip().lower()
    sort_dir = (request.args.get("dir") or "asc").strip().lower()
    titulo_filter = get_text_query_value("titulo")
    status_filters = {item.lower() for item in get_multi_query_values("status")}
    allowed_bg_colors = {option["bg"].lower() for option in ALERTA_COLOR_OPTIONS}
    bg_color_filters = []
    for raw in get_multi_query_values("bg_color"):
        normalized = _normalize_hex_color(raw, "__invalid__")
        if normalized in allowed_bg_colors and normalized not in bg_color_filters:
            bg_color_filters.append(normalized)

    conn = get_db_connection()
    ensure_admin_alertas_table(conn)

    base_from = " FROM admin_alertas "
    where = []
    params = []
    if q:
        like = f"%{q}%"
        where.append("(COALESCE(titulo, '') LIKE ? OR mensagem LIKE ?)")
        params.extend([like, like])
    append_text_contains_condition(where, params, "COALESCE(titulo, mensagem)", titulo_filter)
    if status_filters:
        status_where = []
        if "ativo" in status_filters:
            status_where.append("visivel = 1")
        if "inativo" in status_filters:
            status_where.append("visivel = 0")
        if status_where:
            where.append("(" + " OR ".join(status_where) + ")")
    if bg_color_filters:
        placeholders = ", ".join("?" for _ in bg_color_filters)
        where.append(f"LOWER(bg_color) IN ({placeholders})")
        params.extend(bg_color_filters)

    where_sql = append_conditions_sql(False, where)
    order_map = {
        "titulo": "LOWER(COALESCE(titulo, mensagem))",
        "bg_color": "LOWER(bg_color)",
        "status": "visivel",
    }
    order_col = order_map.get(sort_field, order_map["titulo"])
    direction = "DESC" if sort_dir == "desc" else "ASC"
    count_sql = "SELECT COUNT(*)" + base_from + where_sql
    total = conn.execute(count_sql, params).fetchone()[0]

    query = (
        "SELECT id, COALESCE(NULLIF(TRIM(titulo), ''), mensagem) AS titulo, mensagem, bg_color, border_color, visivel, criado_em"
        + base_from
        + where_sql
        + f" ORDER BY {order_col} {direction}, id DESC"
    )
    params_exec = list(params)
    apply_limit = wants_pagination()
    if apply_limit:
        query += " LIMIT ? OFFSET ?"
        params_exec += [per_page, offset]
    rows = conn.execute(query, params_exec).fetchall()
    alertas = [
        {
            "id": row["id"],
            "titulo": row["titulo"],
            "mensagem": row["mensagem"],
            "bg_color": row["bg_color"],
            "border_color": row["border_color"],
            "visivel": bool(row["visivel"]),
            "criado_em": row["criado_em"],
        }
        for row in rows
    ]
    filter_schema = [
        {
            "param": "titulo",
            "label": "Nome do alerta",
            "type": "text_contains",
            "placeholder": "Contém no nome",
        },
        {
            "param": "bg_color",
            "label": "Cor",
            "type": "multi_select",
            "values": [
                {"value": option["bg"], "label": option.get("label") or option["bg"]}
                for option in ALERTA_COLOR_OPTIONS
            ],
        },
        {
            "param": "status",
            "label": "Status",
            "type": "multi_select",
            "values": [
                {"value": "ativo", "label": "Ativo"},
                {"value": "inativo", "label": "Inativo"},
            ],
        }
    ]
    total_pages = (total + per_page - 1) // per_page if apply_limit and per_page else 1
    return render_template(
        "admin_alertas.html",
        alertas=alertas,
        filter_schema=filter_schema,
        alerta_color_options=ALERTA_COLOR_OPTIONS,
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages,
    )


@admin_required
def admin_salvar_alerta():
    conn = get_db_connection()
    ensure_admin_alertas_table(conn)

    alerta_id = request.form.get("alerta_id", type=int)
    titulo = (request.form.get("titulo") or "").strip()
    mensagem = (request.form.get("mensagem") or "").strip()
    bg_color = _normalize_hex_color(request.form.get("bg_color"), ALERTA_COLOR_OPTIONS[0]["bg"])
    border_color_raw = (request.form.get("border_color") or "").strip()
    border_color = _normalize_hex_color(border_color_raw, _alerta_border_for(bg_color)) if border_color_raw else _alerta_border_for(bg_color)
    visivel = 1 if (request.form.get("visivel") or "1") == "1" else 0

    if not titulo or not mensagem:
        flash("Título e mensagem do alerta são obrigatórios.", "error")
        return redirect(url_for("admin_alertas"))

    if alerta_id:
        conn.execute(
            """
            UPDATE admin_alertas
               SET titulo = ?, mensagem = ?, bg_color = ?, border_color = ?, visivel = ?
             WHERE id = ?
            """,
            (titulo, mensagem, bg_color, border_color, visivel, alerta_id),
        )
        flash("Alerta atualizado com sucesso.", "success")
    else:
        conn.execute(
            """
            INSERT INTO admin_alertas (titulo, mensagem, bg_color, border_color, visivel)
            VALUES (?, ?, ?, ?, ?)
            """,
            (titulo, mensagem, bg_color, border_color, visivel),
        )
        flash("Alerta criado com sucesso.", "success")
    conn.commit()
    return redirect(url_for("admin_alertas"))


@admin_required
def admin_alternar_alerta(alerta_id):
    conn = get_db_connection()
    ensure_admin_alertas_table(conn)
    conn.execute(
        "UPDATE admin_alertas SET visivel = CASE WHEN visivel = 1 THEN 0 ELSE 1 END WHERE id = ?",
        (alerta_id,),
    )
    conn.commit()
    flash("Status do alerta atualizado.", "success")
    return redirect(url_for("admin_alertas"))


@admin_required
def admin_deletar_alerta(alerta_id):
    conn = get_db_connection()
    ensure_admin_alertas_table(conn)
    conn.execute("DELETE FROM admin_alertas WHERE id = ?", (alerta_id,))
    conn.commit()
    flash("Alerta excluído com sucesso.", "success")
    return redirect(url_for("admin_alertas"))


bp_admin_alertas = Blueprint(
    "admin_alertas_blueprint",
    __name__,
)

LEGACY_ROUTE_SPECS = configure_legacy_routes(
    bp_admin_alertas,
    (
        LegacyRouteSpec(
            "/admin/alertas",
            "admin_alertas",
            admin_alertas,
            ("GET",),
        ),
        LegacyRouteSpec(
            "/admin/alertas/salvar",
            "admin_salvar_alerta",
            admin_salvar_alerta,
            ("POST",),
        ),
        LegacyRouteSpec(
            "/admin/alertas/<int:alerta_id>/alternar",
            "admin_alternar_alerta",
            admin_alternar_alerta,
            ("POST",),
        ),
        LegacyRouteSpec(
            "/admin/alertas/<int:alerta_id>/deletar",
            "admin_deletar_alerta",
            admin_deletar_alerta,
            ("POST",),
        ),
    ),
)


__all__ = [
    "ALERTA_COLOR_OPTIONS",
    "LEGACY_ROUTE_SPECS",
    "_alerta_border_for",
    "_derive_border_from_hex",
    "_normalize_hex_color",
    "admin_alertas",
    "admin_alternar_alerta",
    "admin_deletar_alerta",
    "admin_salvar_alerta",
    "bp_admin_alertas",
]
