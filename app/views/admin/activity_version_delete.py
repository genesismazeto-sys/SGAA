from __future__ import annotations

import logging
import sqlite3

from flask import redirect, url_for

from app.activity_catalog import (
    ActivityVersionDeleteBlocked,
    assert_activity_version_can_be_safely_deleted,
    get_atividade_base,
)
from app.auth import admin_required
from app.db import get_db_connection
from utils.messages import flash


def _flash_delete_block(exc: ActivityVersionDeleteBlocked) -> None:
    if exc.code == "wrong_base_or_version":
        flash("Versão não encontrada para esta atividade-base.", "error")
    elif exc.code == "active":
        flash(
            "Versão ativa não pode ser excluída. Inative-a antes de tentar novamente.",
            "error",
        )
    elif exc.code == "lifecycle_frozen":
        flash(
            "Somente versões em rascunho ou inativas podem ser excluídas.",
            "error",
        )
    elif exc.code == "referenced":
        flash(
            f"Não é possível excluir: a versão possui {exc.count} "
            f"referência(s) em {exc.reference_label}.",
            "error",
        )
    elif exc.code == "sole_version":
        flash(
            "A única versão de uma atividade-base não pode ser excluída.",
            "error",
        )
    else:
        flash("Erro seguro ao excluir versão; nenhuma alteração foi aplicada.", "error")


@admin_required
def admin_catalogo_excluir_versao(base_id: int, versao_id: int):
    """Hard-delete one exact, transactionally revalidated disposable version."""
    conn = get_db_connection()
    redirect_endpoint = "admin_catalogo_versao_detalhe"
    redirect_values = {"base_id": base_id}
    try:
        conn.execute("BEGIN IMMEDIATE")
        assert_activity_version_can_be_safely_deleted(
            conn,
            base_id=base_id,
            versao_id=versao_id,
        )
        deleted = conn.execute(
            "DELETE FROM atividade_versao WHERE id = ? AND atividade_base_id = ?",
            (versao_id, base_id),
        )
        if deleted.rowcount != 1:
            raise sqlite3.IntegrityError("exact version delete lost its target")
        conn.commit()
        flash("Versão excluída definitivamente com sucesso.", "success")
    except ActivityVersionDeleteBlocked as exc:
        conn.rollback()
        if get_atividade_base(conn, base_id) is None:
            redirect_endpoint = "admin_atividades"
            redirect_values = {}
        _flash_delete_block(exc)
    except sqlite3.IntegrityError:
        conn.rollback()
        flash(
            "A versão não foi excluída porque uma referência protegida ainda existe.",
            "error",
        )
    except Exception:
        conn.rollback()
        logging.exception("Erro ao excluir versão de atividade")
        flash("Erro seguro ao excluir versão; nenhuma alteração foi aplicada.", "error")
    return redirect(url_for(redirect_endpoint, **redirect_values))


__all__ = ["admin_catalogo_excluir_versao"]
