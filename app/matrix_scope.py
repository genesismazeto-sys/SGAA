from __future__ import annotations

from app.db import get_preferred_matriz_for_curso
from app.db_maintenance import (
    ensure_matriz_atividade_links_table,
    ensure_matrizes_atividades_table,
)


MATRIZ_STATUS_META = {
    "rascunho": {"label": "Rascunho", "badge_type": "warning"},
    "vigente": {"label": "Vigente", "badge_type": "success"},
    "encerrada": {"label": "Encerrada", "badge_type": "danger"},
}


def _matriz_status_label(status: str | None) -> str:
    normalized = (status or "rascunho").strip().lower()
    return MATRIZ_STATUS_META.get(normalized, MATRIZ_STATUS_META["rascunho"])["label"]


def _matriz_option_label(row) -> str:
    parts = [str(row["nome"] or "Matriz sem nome").strip()]
    if row["versao"]:
        parts.append(str(row["versao"]).strip())
    if row["status"]:
        parts.append(_matriz_status_label(row["status"]))
    return " | ".join(part for part in parts if part)


def get_effective_matriz_for_turma(
    conn,
    curso_id: int | None,
    turma_matriz_id: int | None,
):
    ensure_matrizes_atividades_table(conn)
    if turma_matriz_id:
        row = conn.execute(
            "SELECT * FROM matrizes_atividades WHERE id = ?",
            (turma_matriz_id,),
        ).fetchone()
        if row:
            return row
    return get_preferred_matriz_for_curso(conn, curso_id)


def is_activity_allowed_for_turma_matrix(
    conn,
    atividade_id: int | None,
    curso_id: int | None,
    turma_matriz_id: int | None,
) -> bool:
    if not atividade_id:
        return False
    ensure_matriz_atividade_links_table(conn)
    matriz = get_effective_matriz_for_turma(conn, curso_id, turma_matriz_id)
    if not matriz:
        return True
    row = conn.execute(
        "SELECT 1 FROM matrizes_atividades_itens WHERE matriz_id = ? AND atividade_id = ?",
        (matriz["id"], atividade_id),
    ).fetchone()
    return row is not None


def get_allowed_activity_ids_for_turma_matrix(
    conn,
    curso_id: int | None,
    turma_matriz_id: int | None,
):
    ensure_matriz_atividade_links_table(conn)
    matriz = get_effective_matriz_for_turma(conn, curso_id, turma_matriz_id)
    if not matriz:
        return None, None
    activity_ids = {
        row["atividade_id"]
        for row in conn.execute(
            "SELECT atividade_id FROM matrizes_atividades_itens WHERE matriz_id = ?",
            (matriz["id"],),
        ).fetchall()
    }
    return activity_ids, matriz


__all__ = [
    "MATRIZ_STATUS_META",
    "_matriz_option_label",
    "_matriz_status_label",
    "get_allowed_activity_ids_for_turma_matrix",
    "get_effective_matriz_for_turma",
    "is_activity_allowed_for_turma_matrix",
]
