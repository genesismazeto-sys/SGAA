# coding: utf-8
"""UT-12: dono canonico do cohort "Reportes".

6 simbolos relocados de main.py por MOVE-VERBATIM (4 rotas, 1 helper e 1
constante). Nenhuma importacao de main; registra apenas rotas legadas via
LegacyRouteSpec.
"""

from __future__ import annotations

from flask import (
    Blueprint,
    current_app,
    redirect,
    render_template,
    request,
    url_for,
    session,
)

from app.auth import admin_required
from app.db import get_db_connection
from app.db_maintenance import ensure_reportes_table
from app.presentation import format_date_ptbr
from app.reporting import REPORTE_CATEGORY_OPTIONS
from app.student_documents import remove_student_document, save_student_document
from app.uploads import ALLOWED_REPORTE_SCREENSHOTS
from app.views.admin import LegacyRouteSpec, configure_legacy_routes
from app.web.filters import (
    append_conditions_sql,
    append_text_contains_condition,
    get_date_range_query,
    get_multi_query_values,
    get_text_query_value,
)
from app.web.pagination import get_pagination, wants_pagination
from utils.messages import flash


REPORTE_STATUS_OPTIONS = (
    "Novo",
    "Em análise",
    "Resolvido",
)


def _reporte_status_badge_type(status: str | None) -> str:
    normalized = str(status or "").strip()
    if normalized == "Resolvido":
        return "success"
    if normalized == "Em análise":
        return "warning"
    return "danger" if normalized else "warning"


@admin_required
def admin_reportes():
    page, per_page, offset = get_pagination(default_per_page=20)
    q = (request.args.get("q") or "").strip()
    status_filters = [item for item in get_multi_query_values("status") if item in REPORTE_STATUS_OPTIONS]
    categoria_filters = [item for item in get_multi_query_values("categoria") if item in REPORTE_CATEGORY_OPTIONS]
    aluno_filter = get_text_query_value("aluno")
    matricula_filter = get_text_query_value("matricula")
    titulo_filter = get_text_query_value("titulo")
    data_min, data_max = get_date_range_query("criado_em")
    sort_field = (request.args.get("s") or "data").strip().lower()
    sort_dir = (request.args.get("dir") or "desc").strip().lower()

    conn = get_db_connection()
    ensure_reportes_table(conn)
    alunos = conn.execute(
        """
        SELECT id, nome, matricula
          FROM alunos
      ORDER BY LOWER(COALESCE(nome, '')), LOWER(COALESCE(matricula, '')), id
        """
    ).fetchall()

    base_from = (
        " FROM reportes rep"
        " JOIN alunos a ON a.id = rep.aluno_id"
        " LEFT JOIN usuarios u ON u.id = a.usuario_id"
    )
    where = []
    params: list[object] = []

    if q:
        like = f"%{q}%"
        where.append(
            "(LOWER(rep.titulo) LIKE LOWER(?) OR LOWER(rep.descricao) LIKE LOWER(?) OR LOWER(COALESCE(a.nome, '')) LIKE LOWER(?) OR LOWER(COALESCE(a.matricula, '')) LIKE LOWER(?))"
        )
        params.extend([like, like, like, like])
    append_text_contains_condition(where, params, "a.nome", aluno_filter)
    append_text_contains_condition(where, params, "a.matricula", matricula_filter)
    append_text_contains_condition(where, params, "rep.titulo", titulo_filter)
    if status_filters:
        placeholders = ", ".join("?" for _ in status_filters)
        where.append(f"rep.status IN ({placeholders})")
        params.extend(status_filters)
    if categoria_filters:
        placeholders = ", ".join("?" for _ in categoria_filters)
        where.append(f"rep.categoria IN ({placeholders})")
        params.extend(categoria_filters)
    if data_min:
        where.append("date(rep.criado_em) >= date(?)")
        params.append(data_min)
    if data_max:
        where.append("date(rep.criado_em) <= date(?)")
        params.append(data_max)

    where_sql = append_conditions_sql(False, where)
    total = conn.execute("SELECT COUNT(*)" + base_from + where_sql, params).fetchone()[0]

    sort_map = {
        "data": "datetime(rep.criado_em)",
        "aluno": "LOWER(COALESCE(a.nome, ''))",
        "titulo": "LOWER(rep.titulo)",
        "categoria": "LOWER(rep.categoria)",
        "status": "LOWER(rep.status)",
    }
    order_col = sort_map.get(sort_field, sort_map["data"])
    direction = "DESC" if sort_dir == "desc" else "ASC"

    query = (
        "SELECT rep.id, rep.titulo, rep.descricao, rep.categoria, rep.screenshot_filename, rep.status,"
        " rep.criado_em, rep.atualizado_em, a.nome AS aluno_nome, a.matricula,"
        " COALESCE(u.email, a.email, '') AS aluno_email"
        + base_from
        + where_sql
        + f" ORDER BY {order_col} {direction}, rep.id DESC"
    )
    exec_params = list(params)
    apply_limit = wants_pagination()
    if apply_limit:
        query += " LIMIT ? OFFSET ?"
        exec_params += [per_page, offset]

    rows = conn.execute(query, exec_params).fetchall()
    reportes = [
        {
            "id": row["id"],
            "titulo": row["titulo"],
            "descricao": row["descricao"],
            "categoria": row["categoria"],
            "screenshot_filename": row["screenshot_filename"],
            "status": row["status"],
            "status_badge_type": _reporte_status_badge_type(row["status"]),
            "criado_em_fmt": format_date_ptbr(row["criado_em"]),
            "atualizado_em_fmt": format_date_ptbr(row["atualizado_em"]),
            "aluno_nome": row["aluno_nome"],
            "matricula": row["matricula"],
            "aluno_email": row["aluno_email"],
        }
        for row in rows
    ]
    total_pages = (total + per_page - 1) // per_page if apply_limit and per_page else 1
    filter_schema = [
        {
            "param": "aluno",
            "label": "Aluno",
            "type": "text_contains",
            "placeholder": "Contém no nome",
        },
        {
            "param": "matricula",
            "label": "Matrícula",
            "type": "text_contains",
            "placeholder": "Contém na matrícula",
        },
        {
            "param": "titulo",
            "label": "Título",
            "type": "text_contains",
            "placeholder": "Contém no título",
        },
        {
            "param": "criado_em",
            "label": "Data",
            "type": "date_range",
            "min_label": "De",
            "max_label": "Até",
        },
        {
            "param": "status",
            "label": "Status",
            "type": "multi_select",
            "values": [{"value": s, "label": s} for s in REPORTE_STATUS_OPTIONS],
        },
        {
            "param": "categoria",
            "label": "Categoria",
            "type": "multi_select",
            "values": [{"value": c, "label": c} for c in REPORTE_CATEGORY_OPTIONS],
        },
    ]
    return render_template(
        "admin_reportes.html",
        reportes=reportes,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        filter_schema=filter_schema,
        status_options=REPORTE_STATUS_OPTIONS,
        categoria_options=REPORTE_CATEGORY_OPTIONS,
        alunos=alunos,
    )


@admin_required
def admin_reportes_novo():
    conn = get_db_connection()
    ensure_reportes_table(conn)

    aluno_raw = (request.form.get("aluno_id") or "").strip()
    categoria = (request.form.get("categoria") or "").strip()
    titulo = (request.form.get("titulo") or "").strip()
    descricao = (request.form.get("descricao") or "").strip()
    captura_tela = request.files.get("captura_tela")

    if not aluno_raw:
        flash("Selecione um aluno para o reporte.", "error")
        return redirect(url_for("admin_reportes", novo="1"))
    try:
        aluno_id = int(aluno_raw)
    except (TypeError, ValueError):
        aluno_id = 0
    aluno = conn.execute(
        "SELECT id, nome FROM alunos WHERE id = ?", (aluno_id,)
    ).fetchone()
    if not aluno:
        flash("O aluno selecionado não foi encontrado.", "error")
        return redirect(url_for("admin_reportes", novo="1"))

    if categoria not in REPORTE_CATEGORY_OPTIONS:
        flash("Selecione uma categoria válida para o reporte.", "error")
        return redirect(url_for("admin_reportes", novo="1"))
    if not titulo:
        flash("Informe o título do reporte.", "error")
        return redirect(url_for("admin_reportes", novo="1"))
    if len(titulo) > 120:
        flash("O título do reporte deve ter no máximo 120 caracteres.", "error")
        return redirect(url_for("admin_reportes", novo="1"))
    if not descricao:
        flash("Descreva o problema encontrado.", "error")
        return redirect(url_for("admin_reportes", novo="1"))

    screenshot_filename = None
    try:
        if captura_tela and getattr(captura_tela, "filename", ""):
            screenshot_filename = save_student_document(
                captura_tela,
                ALLOWED_REPORTE_SCREENSHOTS,
                root_folder=current_app.config["DOCUMENTOS_ALUNOS_FOLDER"],
                student_id=aluno["id"],
                student_name=aluno["nome"],
                category="reportes",
                prefix=f"reporte{aluno['id']}",
            )
    except ValueError:
        flash("A captura deve estar em PNG, JPG, JPEG ou WEBP.", "error")
        return redirect(url_for("admin_reportes", novo="1"))

    try:
        conn.execute(
            """
            INSERT INTO reportes
                (aluno_id, titulo, descricao, categoria, screenshot_filename, status)
            VALUES (?, ?, ?, ?, ?, 'Novo')
            """,
            (aluno["id"], titulo, descricao, categoria, screenshot_filename),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        if screenshot_filename:
            try:
                remove_student_document(
                    current_app.config["DOCUMENTOS_ALUNOS_FOLDER"], screenshot_filename
                )
            except (OSError, ValueError):
                pass
        flash("Não foi possível criar o reporte.", "error")
        return redirect(url_for("admin_reportes", novo="1"))

    flash("Reporte registrado para acompanhamento.", "success")
    return redirect(url_for("admin_reportes"))


@admin_required
def admin_reportes_atualizar_status(reporte_id: int):
    status = (request.form.get("status") or "").strip()
    if status not in REPORTE_STATUS_OPTIONS:
        flash("Selecione um status válido para o reporte.", "error")
        return redirect(url_for("admin_reportes"))

    conn = get_db_connection()
    ensure_reportes_table(conn)
    reporte = conn.execute("SELECT id FROM reportes WHERE id = ?", (reporte_id,)).fetchone()
    if not reporte:
        flash("Reporte não encontrado.", "error")
        return redirect(url_for("admin_reportes"))

    conn.execute(
        """
        UPDATE reportes
           SET status = ?,
               atualizado_em = datetime('now'),
               admin_id = ?
         WHERE id = ?
        """,
        (status, session.get("user_id"), reporte_id),
    )
    conn.commit()
    flash("Status do reporte atualizado.", "success")
    return redirect(url_for("admin_reportes"))


@admin_required
def admin_reportes_deletar(reporte_id: int):
    conn = get_db_connection()
    ensure_reportes_table(conn)
    reporte = conn.execute("SELECT id FROM reportes WHERE id = ?", (reporte_id,)).fetchone()
    if not reporte:
        flash("Reporte não encontrado.", "error")
        return redirect(url_for("admin_reportes"))
    conn.execute("DELETE FROM reportes WHERE id = ?", (reporte_id,))
    conn.commit()
    flash("Reporte excluído.", "success")
    return redirect(url_for("admin_reportes"))


bp_admin_reportes = Blueprint(
    "admin_reportes_blueprint",
    __name__,
)

LEGACY_ROUTE_SPECS = configure_legacy_routes(
    bp_admin_reportes,
    (
        LegacyRouteSpec(
            "/admin/reportes",
            "admin_reportes",
            admin_reportes,
            ("GET",),
        ),
        LegacyRouteSpec(
            "/admin/reportes/novo",
            "admin_reportes_novo",
            admin_reportes_novo,
            ("POST",),
        ),
        LegacyRouteSpec(
            "/admin/reportes/<int:reporte_id>/status",
            "admin_reportes_atualizar_status",
            admin_reportes_atualizar_status,
            ("POST",),
        ),
        LegacyRouteSpec(
            "/admin/reportes/<int:reporte_id>/deletar",
            "admin_reportes_deletar",
            admin_reportes_deletar,
            ("POST",),
        ),
    ),
)


__all__ = [
    "LEGACY_ROUTE_SPECS",
    "REPORTE_STATUS_OPTIONS",
    "_reporte_status_badge_type",
    "admin_reportes",
    "admin_reportes_novo",
    "admin_reportes_atualizar_status",
    "admin_reportes_deletar",
    "bp_admin_reportes",
]
