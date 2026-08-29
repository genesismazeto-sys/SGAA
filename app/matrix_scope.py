from __future__ import annotations

class AcademicGraphFrozenError(RuntimeError):
    """Raised before a write would mutate a graph used by an assigned Turma."""


ACADEMIC_GRAPH_FROZEN_MESSAGE = "Parâmetros inválidos."
ACADEMIC_VERSION_FROZEN_MESSAGE = "Esta versão já está em uso e não pode mais ser editada."


MATRIZ_STATUS_META = {
    "rascunho": {"label": "Rascunho", "badge_type": "warning"},
    "vigente": {"label": "Vigente", "badge_type": "success"},
    "encerrada": {"label": "Encerrada", "badge_type": "danger"},
    "ativa": {"label": "Ativa", "badge_type": "success"},
    "inativa": {"label": "Inativa", "badge_type": "danger"},
}


def _matriz_status_label(status: str | None) -> str:
    normalized = (status or "rascunho").strip().lower()
    return MATRIZ_STATUS_META.get(normalized, MATRIZ_STATUS_META["rascunho"])["label"]


def _matriz_option_label(row) -> str:
    parts = [str(row["nome"] or "Matriz sem nome").strip()]
    if row["status"]:
        parts.append(_matriz_status_label(row["status"]))
    return " | ".join(part for part in parts if part)


def is_matrix_assigned(conn, matriz_id: int | None) -> bool:
    """Return whether at least one Turma currently points to this Matrix."""
    if not matriz_id:
        return False
    return (
        conn.execute(
            "SELECT EXISTS(SELECT 1 FROM turmas WHERE matriz_id = ?)",
            (matriz_id,),
        ).fetchone()[0]
        == 1
    )


def is_activity_version_referenced_by_assigned_matrix(
    conn,
    atividade_versao_id: int | None,
) -> bool:
    """Return whether an exact version link is reachable from an assigned Matrix."""
    if not atividade_versao_id:
        return False
    return (
        conn.execute(
            """
            SELECT EXISTS(
                SELECT 1
                  FROM matriz_atividade_versao_item mavi
                  JOIN turmas t ON t.matriz_id = mavi.matriz_id
                 WHERE mavi.atividade_versao_id = ?
            )
            """,
            (atividade_versao_id,),
        ).fetchone()[0]
        == 1
    )


def is_activity_base_referenced_by_assigned_matrix(
    conn, atividade_base_id: int | None
) -> bool:
    """Return whether any selected version of a base is in an assigned Matrix."""
    if not atividade_base_id:
        return False
    return (
        conn.execute(
            """
            SELECT EXISTS(
                SELECT 1
                  FROM matriz_atividade_versao_item mavi
                  JOIN turmas t ON t.matriz_id = mavi.matriz_id
                 WHERE mavi.atividade_base_id = ?
            )
            """,
            (atividade_base_id,),
        ).fetchone()[0]
        == 1
    )


def get_effective_matriz_for_turma(
    conn,
    curso_id: int | None,
    turma_matriz_id: int | None,
):
    if not turma_matriz_id or not curso_id:
        return None
    return conn.execute(
        "SELECT * FROM matrizes_atividades WHERE id = ? AND curso_id = ?",
        (turma_matriz_id, curso_id),
    ).fetchone()


def is_activity_version_allowed_for_turma_matrix(
    conn,
    atividade_versao_id: int | None,
    curso_id: int | None,
    turma_matriz_id: int | None,
) -> bool:
    if not atividade_versao_id:
        return False
    matriz = get_effective_matriz_for_turma(conn, curso_id, turma_matriz_id)
    if not matriz:
        return False
    row = conn.execute(
        "SELECT 1 FROM matriz_atividade_versao_item WHERE matriz_id = ? AND atividade_versao_id = ?",
        (matriz["id"], atividade_versao_id),
    ).fetchone()
    return row is not None


def get_allowed_activity_version_ids_for_turma_matrix(
    conn,
    curso_id: int | None,
    turma_matriz_id: int | None,
):
    matriz = get_effective_matriz_for_turma(conn, curso_id, turma_matriz_id)
    if not matriz:
        return set(), None
    version_ids = {
        row["atividade_versao_id"]
        for row in conn.execute(
            "SELECT atividade_versao_id FROM matriz_atividade_versao_item WHERE matriz_id = ?",
            (matriz["id"],),
        ).fetchall()
    }
    return version_ids, matriz


__all__ = [
    "AcademicGraphFrozenError",
    "ACADEMIC_GRAPH_FROZEN_MESSAGE",
    "ACADEMIC_VERSION_FROZEN_MESSAGE",
    "MATRIZ_STATUS_META",
    "_matriz_option_label",
    "_matriz_status_label",
    "get_allowed_activity_version_ids_for_turma_matrix",
    "get_effective_matriz_for_turma",
    "is_activity_base_referenced_by_assigned_matrix",
    "is_activity_version_referenced_by_assigned_matrix",
    "is_activity_version_allowed_for_turma_matrix",
    "is_matrix_assigned",
]
