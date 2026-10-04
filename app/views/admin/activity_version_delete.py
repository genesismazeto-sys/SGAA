from __future__ import annotations

import logging

from flask import redirect, url_for

from app.activity_catalog import (
    ActivityVersionDeleteBlocked,
    delete_activity_version,
    get_atividade_base,
)
from app.auth import admin_required
from app.db import get_db_connection, is_integrity_error
from utils.messages import flash


def _flash_delete_block(exc: ActivityVersionDeleteBlocked) -> None:
    if exc.code == "wrong_base_or_version":
        flash("Versão não encontrada para esta atividade-base.", "error")
    elif exc.code == "in_use":
        dependencias = exc.describe_dependencies()
        flash(
            f"Não é possível excluir esta versão porque ela é utilizada {dependencias}.",
            "error",
        )
    elif exc.code == "sole_version":
        flash("Não é possível excluir: única versão da atividade.", "error")
    else:
        flash("Erro seguro ao excluir versão; nenhuma alteração foi aplicada.", "error")


@admin_required
def admin_catalogo_excluir_versao(base_id: int, versao_id: int):
    """Hard-delete one version atomically, re-anchoring and renumbering survivors."""
    conn = get_db_connection()
    redirect_endpoint = "admin_catalogo_versao_detalhe"
    redirect_values = {"base_id": base_id}
    try:
        conn.execute("BEGIN IMMEDIATE")
        delete_activity_version(conn, base_id=base_id, versao_id=versao_id)
        conn.commit()
        flash("Versão excluída definitivamente com sucesso.", "success")
    except ActivityVersionDeleteBlocked as exc:
        conn.rollback()
        if get_atividade_base(conn, base_id) is None:
            redirect_endpoint = "admin_atividades"
            redirect_values = {}
        _flash_delete_block(exc)
    except Exception as exc:
        conn.rollback()
        if is_integrity_error(exc):
            flash(
                "A versão não foi excluída porque uma referência protegida ainda existe.",
                "error",
            )
        else:
            logging.exception("Erro ao excluir versão de atividade")
            flash("Erro seguro ao excluir versão; nenhuma alteração foi aplicada.", "error")
    return redirect(url_for(redirect_endpoint, **redirect_values))


__all__ = ["admin_catalogo_excluir_versao"]
