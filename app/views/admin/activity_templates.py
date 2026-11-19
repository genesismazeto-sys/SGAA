"""Admin routes of an activity version's DOCX templates (Modelos para preenchimento).

Thin views: parse the form, call ``app.activity_document_templates`` (which
re-checks the version state under its locks), flash and return to the version
form.  Registered with the activity routes (``app.views.admin.atividades``);
RBAC: ``atividades:edit`` for the writes, ``atividades:view`` for the download.
"""

from __future__ import annotations

import logging

from flask import abort, redirect, request, session, url_for

from app.activity_document_templates import (
    TEMPLATE_FILE_FIELD,
    TEMPLATE_TITLE_FIELD,
    DocumentTemplateRefused,
    add_template,
    read_template_file,
    read_template_upload,
    retire_template,
    template_download_response,
    update_template,
)
from app.auth import admin_required
from app.db import get_db_connection
from utils.messages import flash


def _back(base_id: int, versao_id: int):
    url = url_for("admin_catalogo_editar_versao", base_id=base_id, versao_id=versao_id)
    return redirect(f"{url}#modelos-preenchimento")


def _refused(exc: DocumentTemplateRefused) -> None:
    flash(exc.user_message, "error")


def _unexpected(base_id: int, versao_id: int):
    logging.exception("Falha ao alterar modelo de atividade")
    flash("Não foi possível alterar o modelo; nenhuma alteração foi aplicada.", "error")
    return _back(base_id, versao_id)


@admin_required
def admin_catalogo_adicionar_modelo(base_id: int, versao_id: int):
    conn = get_db_connection()
    try:
        upload = read_template_upload(request.files.get(TEMPLATE_FILE_FIELD))
        add_template(
            conn, base_id=base_id, versao_id=versao_id, titulo=request.form.get(TEMPLATE_TITLE_FIELD),
            upload=upload, actor_user_id=int(session["user_id"]),
        )
        flash("Modelo adicionado.", "success")
    except DocumentTemplateRefused as exc:
        _refused(exc)
    except Exception:
        return _unexpected(base_id, versao_id)
    return _back(base_id, versao_id)


@admin_required
def admin_catalogo_atualizar_modelo(base_id: int, versao_id: int, modelo_id: int):
    conn = get_db_connection()
    try:
        file_storage = request.files.get(TEMPLATE_FILE_FIELD)
        upload = read_template_upload(file_storage) if file_storage and file_storage.filename else None
        update_template(
            conn, base_id=base_id, versao_id=versao_id, modelo_id=modelo_id,
            titulo=request.form.get(TEMPLATE_TITLE_FIELD), upload=upload,
            actor_user_id=int(session["user_id"]),
        )
        flash("Modelo substituído. A versão anterior do modelo foi preservada no histórico.", "success")
    except DocumentTemplateRefused as exc:
        _refused(exc)
    except Exception:
        return _unexpected(base_id, versao_id)
    return _back(base_id, versao_id)


@admin_required
def admin_catalogo_retirar_modelo(base_id: int, versao_id: int, modelo_id: int):
    conn = get_db_connection()
    try:
        retire_template(
            conn, base_id=base_id, versao_id=versao_id, modelo_id=modelo_id,
            actor_user_id=int(session["user_id"]),
        )
        flash("Modelo retirado desta versão. O arquivo foi preservado no histórico.", "success")
    except DocumentTemplateRefused as exc:
        _refused(exc)
    except Exception:
        return _unexpected(base_id, versao_id)
    return _back(base_id, versao_id)


@admin_required
def admin_catalogo_baixar_modelo(base_id: int, versao_id: int, modelo_id: int):
    template = read_template_file(get_db_connection(), modelo_id)
    if (
        template is None
        or int(template["atividade_versao_id"]) != int(versao_id)
        or int(template["atividade_base_id"]) != int(base_id)
    ):
        abort(404)
    return template_download_response(template)


__all__ = [
    "admin_catalogo_adicionar_modelo",
    "admin_catalogo_atualizar_modelo",
    "admin_catalogo_baixar_modelo",
    "admin_catalogo_retirar_modelo",
]
