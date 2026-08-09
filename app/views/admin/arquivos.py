# coding: utf-8
"""UT-10: dono canonico do cohort "Arquivos".

9 simbolos relocados de main.py por MOVE-VERBATIM (5 rotas, 4 helpers e 0
constantes). Nenhuma importacao de main; registra apenas rotas legadas via
LegacyRouteSpec.
"""

from __future__ import annotations

import logging
import os

from flask import (
    Blueprint,
    current_app,
    redirect,
    render_template,
    request,
    url_for,
)

from app.admin_files import get_admin_arquivo
from app.auth import admin_required
from app.db import get_db_connection
from app.db_maintenance import ensure_admin_arquivos_table
from app.paths import _path_within_root
from app.uploads import ALLOWED_ATTACHMENTS, _allowed, save_upload
from app.views.admin import LegacyRouteSpec, configure_legacy_routes
from app.web.filters import (
    append_conditions_sql,
    get_date_range_query,
    get_multi_query_values,
    get_text_query_value,
)
from utils.messages import flash


logger = logging.getLogger("main")


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
        where.append("(titulo LIKE ? OR descricao LIKE ? OR original_filename LIKE ?)")
        params.extend([like, like, like])

    order_map = {
        "titulo": "titulo",
        "descricao": "descricao",
        "data_upload": "criado_em",
        "visivel": "visivel",
    }
    col = order_map.get(sort_field, "criado_em")
    direction = "DESC" if sort_dir == "desc" else "ASC"

    sql = """
        SELECT id, titulo, descricao, filename, original_filename, visivel,
               strftime('%d/%m/%Y', criado_em) AS data_upload, criado_em
          FROM admin_arquivos
    """
    sql += append_conditions_sql(False, where)
    sql += f" ORDER BY {col} {direction}, id DESC"
    return conn.execute(sql, params).fetchall()


def _save_admin_arquivo_payload(conn, *, arquivo=None, titulo=None, descricao=None, visivel=1, existing=None):
    ensure_admin_arquivos_table(conn)
    titulo = (titulo or "").strip()
    descricao = (descricao or "").strip() or None
    visivel = 1 if str(visivel).strip() not in {"0", "false", "False"} else 0

    if not titulo:
        raise ValueError("Informe o nome do arquivo.")

    filename = existing["filename"] if existing else None
    original_filename = existing["original_filename"] if existing else None
    new_saved_file = None
    if arquivo and getattr(arquivo, "filename", ""):
        if not _allowed(arquivo.filename, ALLOWED_ATTACHMENTS):
            raise ValueError("Envie um arquivo PDF, PNG ou JPG válido.")
        new_saved_file = save_upload(
            arquivo,
            ALLOWED_ATTACHMENTS,
            prefix="admin-arquivo",
            subdir="admin_arquivos",
        )
        filename = new_saved_file
        original_filename = arquivo.filename

    if not filename:
        raise ValueError("Selecione um arquivo para enviar.")

    return {
        "titulo": titulo,
        "descricao": descricao,
        "visivel": visivel,
        "filename": filename,
        "original_filename": original_filename,
        "new_saved_file": new_saved_file,
    }


def _best_effort_remove_admin_arquivo_file(rel_path):
    if not rel_path:
        return
    try:
        upload_root = current_app.config.get("UPLOAD_FOLDER")
        if not upload_root:
            return
        file_path = os.path.normpath(os.path.join(upload_root, rel_path))
        if not _path_within_root(file_path, upload_root):
            logger.warning(
                f"Remocao ignorada: caminho de arquivo admin '{rel_path}' resolvido para "
                f"'{file_path}' fora de UPLOAD_FOLDER '{upload_root}'"
            )
            return
        if os.path.isfile(file_path):
            os.remove(file_path)
    except Exception as exc:
        logger.warning(f"Falha ao remover arquivo admin '{rel_path}': {exc}")


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
        filtro = titulo_filter.casefold()
        arquivos = [
            arquivo
            for arquivo in arquivos
            if filtro in str(arquivo.get("titulo") or "").casefold()
        ]

    if descricao_filter:
        filtro = descricao_filter.casefold()
        arquivos = [
            arquivo
            for arquivo in arquivos
            if filtro in str(arquivo.get("descricao") or "").casefold()
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

    edit_arquivo = get_admin_arquivo(conn, edit_id) if edit_id else None
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
        filter_schema=filter_schema,
    )


@admin_required
def admin_adicionar_arquivo():
    conn = get_db_connection()
    try:
        payload = _save_admin_arquivo_payload(
            conn,
            arquivo=request.files.get("arquivo"),
            titulo=request.form.get("titulo"),
            descricao=request.form.get("descricao"),
            visivel=request.form.get("visivel", "1"),
        )
        conn.execute(
            """
            INSERT INTO admin_arquivos (titulo, descricao, filename, original_filename, visivel)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                payload["titulo"],
                payload["descricao"],
                payload["filename"],
                payload["original_filename"],
                payload["visivel"],
            ),
        )
        conn.commit()
        flash("Arquivo cadastrado com sucesso.", "success")
        return _redirect_admin_arquivos_return()
    except ValueError as exc:
        flash(str(exc), "error")
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
        payload = _save_admin_arquivo_payload(
            conn,
            arquivo=request.files.get("arquivo"),
            titulo=request.form.get("titulo"),
            descricao=request.form.get("descricao"),
            visivel=request.form.get("visivel", "1"),
            existing=arquivo,
        )
        conn.execute(
            """
            UPDATE admin_arquivos
               SET titulo = ?, descricao = ?, filename = ?, original_filename = ?, visivel = ?
             WHERE id = ?
            """,
            (
                payload["titulo"],
                payload["descricao"],
                payload["filename"],
                payload["original_filename"],
                payload["visivel"],
                arquivo_id,
            ),
        )
        conn.commit()
        if payload["new_saved_file"] and arquivo["filename"] != payload["new_saved_file"]:
            _best_effort_remove_admin_arquivo_file(arquivo["filename"])
        flash("Arquivo atualizado com sucesso.", "success")
        return _redirect_admin_arquivos_return()
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin_arquivos", edit_arquivo=arquivo_id))


@admin_required
def admin_visualizar_arquivo(arquivo_id):
    conn = get_db_connection()
    arquivo = get_admin_arquivo(conn, arquivo_id)
    if not arquivo:
        flash("Arquivo não encontrado.", "error")
        return redirect(url_for("admin_arquivos"))
    safe_filename = os.path.normpath(arquivo["filename"]).replace("\\", "/").lstrip("/")
    return redirect(url_for("uploaded_file", filename=safe_filename))


@admin_required
def admin_deletar_arquivo(arquivo_id):
    conn = get_db_connection()
    arquivo = get_admin_arquivo(conn, arquivo_id)
    if not arquivo:
        flash("Arquivo não encontrado.", "error")
        return redirect(url_for("admin_arquivos"))

    conn.execute("DELETE FROM admin_arquivos WHERE id = ?", (arquivo_id,))
    conn.commit()
    _best_effort_remove_admin_arquivo_file(arquivo["filename"])
    flash("Arquivo excluído com sucesso.", "success")
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
