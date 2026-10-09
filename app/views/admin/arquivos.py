# coding: utf-8
"""UT-10: dono canonico do cohort "Arquivos".

9 simbolos relocados de main.py por MOVE-VERBATIM (5 rotas, 4 helpers e 0
constantes). Nenhuma importacao de main; registra apenas rotas legadas via
LegacyRouteSpec.
"""

from __future__ import annotations

import io
import os

from flask import (
    Blueprint,
    current_app,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from app.admin_files import get_admin_arquivo
from app.arquivos import (
    ArquivoError,
    delete_arquivo,
    read_arquivo_content,
    remove_legacy_arquivo_file,
)
from app.auth import admin_required
from app.db import get_db_connection
from app.db_maintenance import ensure_admin_arquivos_table
from app.sql_dialect import ascii_ci_like, format_date_ptbr, human_text_order
from app.storage import arquivo_documents
from app.text import human_text_contains, human_text_key
from app.views.admin import LegacyRouteSpec, configure_legacy_routes
from app.web.filters import (
    append_conditions_sql,
    human_text_contains_sql,
    get_date_range_query,
    get_multi_query_values,
    get_text_query_value,
)
from utils.messages import flash


def _redirect_admin_arquivos_return(default_endpoint: str = "admin_arquivos", **values):
    return_to = (request.form.get("return_to") or request.args.get("return_to") or "").strip()
    if return_to:
        return redirect(return_to)
    return redirect(url_for(default_endpoint, **values))


def _list_admin_arquivos_rows(conn, q: str, sort_field: str, sort_dir: str):
    ensure_admin_arquivos_table(conn)
    where = []
    params = []
    if q:
        like = f"%{q}%"
        where.append(
            "(" + human_text_contains_sql("titulo", connection=conn)
            + " OR " + human_text_contains_sql("descricao", connection=conn)
            + " OR " + ascii_ci_like("original_filename", connection=conn) + ")"
        )
        params.extend([human_text_key(q), human_text_key(q), like])

    order_map = {
        "titulo": "titulo",
        "descricao": "descricao",
        "data_upload": "criado_em",
        "visivel": "visivel",
    }
    col = order_map.get(sort_field, "criado_em")
    if sort_field in ("titulo", "descricao"):
        # Human text: ordered by the canonical key (app/text.py).
        col = human_text_order(col, connection=conn)
    direction = "DESC" if sort_dir == "desc" else "ASC"

    sql = f"""
        SELECT id, titulo, descricao, filename, original_filename, visivel,
               storage_status, failure_code,
               {format_date_ptbr(conn, "criado_em")} AS data_upload, criado_em
          FROM admin_arquivos
    """
    sql += append_conditions_sql(False, where)
    sql += f" ORDER BY {col} {direction}, id DESC"
    return conn.execute(sql, params).fetchall()


def _save_admin_arquivo_payload(conn, *, arquivo=None, titulo=None, descricao=None, visivel=1, existing=None):
    """Compatibility parser; storage persistence belongs to app.arquivos."""
    ensure_admin_arquivos_table(conn)
    titulo = (titulo or "").strip()
    descricao = (descricao or "").strip() or None
    visivel = 1 if str(visivel).strip() not in {"0", "false", "False"} else 0

    if not titulo:
        raise ValueError("Informe o nome do arquivo.")

    if not (arquivo and getattr(arquivo, "filename", "")) and not existing:
        raise ValueError("Selecione um arquivo para enviar.")

    return {
        "titulo": titulo,
        "descricao": descricao,
        "visivel": visivel,
        "arquivo": arquivo,
    }


def _best_effort_remove_admin_arquivo_file(rel_path):
    if not rel_path:
        return
    try:
        upload_root = current_app.config.get("UPLOAD_FOLDER")
        if not upload_root:
            return
        remove_legacy_arquivo_file(str(upload_root), str(rel_path))
    except (ArquivoError, OSError, ValueError):
        return


@admin_required
def admin_arquivos():
    q = (request.args.get("q") or "").strip()
    titulo_filter = get_text_query_value("titulo")
    descricao_filter = get_text_query_value("descricao")
    tipo_filters = {
        str(value or "").strip().lower()
        for value in get_multi_query_values("tipo")
        if str(value or "").strip()
    }
    data_upload_min, data_upload_max = get_date_range_query("data_upload")
    visivel_filters = [value for value in get_multi_query_values("visivel") if value in {"0", "1"}]
    sort_field = (request.args.get("s") or "data_upload").strip()
    sort_dir = (request.args.get("dir") or "desc").strip().lower()
    edit_id = request.args.get("edit_arquivo", type=int)

    conn = get_db_connection()
    arquivos_rows = _list_admin_arquivos_rows(conn, q, sort_field, sort_dir)
    arquivos = []
    tipos_disponiveis = set()
    for row in arquivos_rows:
        item = {key: row[key] for key in row.keys()}
        source_name = item.get("original_filename") or item.get("filename") or ""
        tipo = os.path.splitext(source_name)[1].lstrip(".").upper() or "ARQUIVO"
        item["tipo"] = tipo
        tipos_disponiveis.add(tipo)
        arquivos.append(item)

    if titulo_filter:
        arquivos = [
            arquivo
            for arquivo in arquivos
            if human_text_contains(arquivo.get("titulo"), titulo_filter)
        ]

    if descricao_filter:
        arquivos = [
            arquivo
            for arquivo in arquivos
            if human_text_contains(arquivo.get("descricao"), descricao_filter)
        ]

    if tipo_filters:
        arquivos = [
            arquivo
            for arquivo in arquivos
            if str(arquivo.get("tipo") or "").strip().lower() in tipo_filters
        ]

    if data_upload_min or data_upload_max:
        filtrados = []
        for arquivo in arquivos:
            created_date = str(arquivo.get("criado_em") or "")[:10]
            if data_upload_min and (not created_date or created_date < data_upload_min):
                continue
            if data_upload_max and (not created_date or created_date > data_upload_max):
                continue
            filtrados.append(arquivo)
        arquivos = filtrados

    if visivel_filters:
        visivel_set = set(visivel_filters)
        arquivos = [arquivo for arquivo in arquivos if str(arquivo.get("visivel")) in visivel_set]

    edit_row = get_admin_arquivo(conn, edit_id) if edit_id else None
    edit_arquivo = dict(edit_row) if edit_row is not None else None
    filter_schema = [
        {
            "param": "titulo",
            "label": "Título",
            "type": "text_contains",
            "placeholder": "Contém no título",
        },
        {
            "param": "tipo",
            "label": "Tipo de arquivo",
            "type": "multi_select",
            "values": [
                {"value": tipo, "label": tipo}
                for tipo in sorted(tipos_disponiveis)
            ],
        },
        {
            "param": "descricao",
            "label": "Descrição",
            "type": "text_contains",
            "placeholder": "Contém na descrição",
        },
        {
            "param": "data_upload",
            "label": "Data de upload",
            "type": "date_range",
            "min_label": "De",
            "max_label": "Até",
        },
        {
            "param": "visivel",
            "label": "Visibilidade",
            "type": "multi_select",
            "values": [
                {"value": "1", "label": "Visível"},
                {"value": "0", "label": "Oculto"},
            ],
        },
    ]

    return render_template(
        "admin_arquivos.html",
        arquivos=arquivos,
        edit_arquivo=edit_arquivo,
        # STORAGE S3-B: the direct-upload form's server-issued ARQUIVOS submission.
        arquivos_submission_id=arquivo_documents.issue_submission(session, int(session["user_id"])),
        filter_schema=filter_schema,
    )


@admin_required
def admin_adicionar_arquivo():
    conn = get_db_connection()
    try:
        # STORAGE S3-B: ONE verified canonical intent, never file bytes.
        arquivo_documents.create_arquivo_from_intent(
            conn,
            session,
            actor_user_id=int(session["user_id"]),
            form=request.form,
            files=request.files,
        )
        flash("Arquivo cadastrado com sucesso.", "success")
        return _redirect_admin_arquivos_return()
    except ArquivoError as exc:
        flash(exc.user_message, "error")
        return redirect(url_for("admin_arquivos"))


@admin_required
def admin_editar_arquivo(arquivo_id):
    conn = get_db_connection()
    arquivo = get_admin_arquivo(conn, arquivo_id)
    if not arquivo:
        flash("Arquivo não encontrado.", "error")
        return redirect(url_for("admin_arquivos"))

    if request.method == "GET":
        return redirect(url_for("admin_arquivos", edit_arquivo=arquivo_id))

    try:
        # STORAGE S3-B: a verified canonical replacement intent, or metadata only.
        cleanup_complete = arquivo_documents.edit_arquivo(
            conn,
            session,
            actor_user_id=int(session["user_id"]),
            arquivo_id=arquivo_id,
            form=request.form,
            files=request.files,
            max_file_bytes=int(current_app.config["MAX_CONTENT_LENGTH"]),
            upload_root=str(current_app.config["UPLOAD_FOLDER"]),
        )
        if cleanup_complete:
            flash("Arquivo atualizado com sucesso.", "success")
        else:
            flash("Arquivo atualizado; a limpeza anterior será repetida.", "warning")
        return _redirect_admin_arquivos_return()
    except ArquivoError as exc:
        flash(exc.user_message, "error")
        return redirect(url_for("admin_arquivos", edit_arquivo=arquivo_id))


@admin_required
def admin_visualizar_arquivo(arquivo_id):
    conn = get_db_connection()
    arquivo = get_admin_arquivo(conn, arquivo_id)
    if not arquivo:
        flash("Arquivo não encontrado.", "error")
        return redirect(url_for("admin_arquivos"))
    if arquivo_documents.is_canonical(arquivo):
        # Canonical custody: a 60-second signed private URL, never proxied bytes.
        try:
            signed_url = arquivo_documents.canonical_download_url(conn, arquivo, download=False)
        except ArquivoError as exc:
            flash(exc.user_message, "error")
            return redirect(url_for("admin_arquivos"))
        response = redirect(signed_url, code=302)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response
    try:
        content, mime_type, download_name = read_arquivo_content(
            conn,
            arquivo,
            upload_root=str(current_app.config["UPLOAD_FOLDER"]),
        )
    except ArquivoError as exc:
        flash(exc.user_message, "error")
        return redirect(url_for("admin_arquivos"))
    response = send_file(
        io.BytesIO(content),
        mimetype=mime_type,
        as_attachment=False,
        download_name=download_name,
        conditional=False,
        max_age=0,
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "private, no-store"
    return response


@admin_required
def admin_deletar_arquivo(arquivo_id):
    conn = get_db_connection()
    arquivo = get_admin_arquivo(conn, arquivo_id)
    if not arquivo:
        flash("Arquivo não encontrado.", "error")
        return redirect(url_for("admin_arquivos"))

    try:
        if arquivo_documents.is_canonical(arquivo):
            arquivo_documents.delete_canonical_arquivo(conn, arquivo_id)
        else:
            delete_arquivo(
                conn,
                arquivo_id,
                upload_root=str(current_app.config["UPLOAD_FOLDER"]),
            )
        flash("Arquivo excluído com sucesso.", "success")
    except ArquivoError as exc:
        flash(exc.user_message, "error")
    return _redirect_admin_arquivos_return()


bp_admin_arquivos = Blueprint("admin_arquivos_blueprint", __name__)

LEGACY_ROUTE_SPECS = configure_legacy_routes(
    bp_admin_arquivos,
    (
        LegacyRouteSpec(
            "/admin/arquivos",
            "admin_arquivos",
            admin_arquivos,
            ("GET",),
        ),
        LegacyRouteSpec(
            "/admin/arquivos/adicionar",
            "admin_adicionar_arquivo",
            admin_adicionar_arquivo,
            ("POST",),
        ),
        LegacyRouteSpec(
            "/admin/arquivos/<int:arquivo_id>/editar",
            "admin_editar_arquivo",
            admin_editar_arquivo,
            ("GET", "POST"),
        ),
        LegacyRouteSpec(
            "/admin/arquivos/<int:arquivo_id>/visualizar",
            "admin_visualizar_arquivo",
            admin_visualizar_arquivo,
            ("GET",),
        ),
        LegacyRouteSpec(
            "/admin/arquivos/<int:arquivo_id>/deletar",
            "admin_deletar_arquivo",
            admin_deletar_arquivo,
            ("POST",),
        ),
    ),
)


__all__ = [
    "LEGACY_ROUTE_SPECS",
    "_best_effort_remove_admin_arquivo_file",
    "_list_admin_arquivos_rows",
    "_redirect_admin_arquivos_return",
    "_save_admin_arquivo_payload",
    "admin_adicionar_arquivo",
    "admin_arquivos",
    "admin_deletar_arquivo",
    "admin_editar_arquivo",
    "admin_visualizar_arquivo",
    "bp_admin_arquivos",
]
