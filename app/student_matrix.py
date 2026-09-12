from __future__ import annotations


class StudentMatrixError(ValueError):
    """Raised when a student Matrix would conflict with the academic Curso."""


def _turma_scope(conn, turma_id: int | None):
    if turma_id is None:
        return None
    row = conn.execute(
        """
        SELECT t.id,t.curso_id,t.matriz_id,
               m.id AS compatible_default_matrix_id
          FROM turmas t
          LEFT JOIN matrizes_atividades m
            ON m.id=t.matriz_id AND m.curso_id=t.curso_id
         WHERE t.id=?
        """,
        (turma_id,),
    ).fetchone()
    if not row:
        raise StudentMatrixError("A turma de destino não existe.")
    if row["matriz_id"] is not None and row["compatible_default_matrix_id"] is None:
        raise StudentMatrixError("A matriz padrão da turma não pertence ao curso informado.")
    return row


def matrix_for_turma_assignment(
    conn,
    *,
    current_matriz_id: int | None,
    turma_id: int | None,
    current_turma_id: int | None = None,
) -> int | None:
    """Preserve an authority, or initialize it once from a compatible default."""
    turma = _turma_scope(conn, turma_id)
    if current_matriz_id is not None:
        if turma is not None:
            compatible = conn.execute(
                "SELECT 1 FROM matrizes_atividades WHERE id=? AND curso_id=?",
                (current_matriz_id, turma["curso_id"]),
            ).fetchone()
            if not compatible:
                raise StudentMatrixError(
                    "A matriz acadêmica do aluno não pertence ao curso da turma de destino."
                )
        return int(current_matriz_id)
    if turma is None or turma_id == current_turma_id:
        return None
    default_id = turma["compatible_default_matrix_id"]
    return int(default_id) if default_id is not None else None


def assign_student_to_turma(conn, aluno_id: int, turma_id: int | None) -> int | None:
    aluno = conn.execute(
        "SELECT id,turma_id,matriz_id FROM alunos WHERE id=?", (aluno_id,)
    ).fetchone()
    if not aluno:
        raise StudentMatrixError("Aluno não encontrado.")
    matriz_id = matrix_for_turma_assignment(
        conn,
        current_matriz_id=aluno["matriz_id"],
        turma_id=turma_id,
        current_turma_id=aluno["turma_id"],
    )
    conn.execute(
        "UPDATE alunos SET turma_id=?,matriz_id=? WHERE id=?",
        (turma_id, matriz_id, aluno_id),
    )
    return matriz_id


def assign_student_matrix(conn, aluno_id: int, matriz_id: int | None) -> int | None:
    aluno = conn.execute(
        """
        SELECT a.id,t.curso_id
          FROM alunos a LEFT JOIN turmas t ON t.id=a.turma_id
         WHERE a.id=?
        """,
        (aluno_id,),
    ).fetchone()
    if not aluno:
        raise StudentMatrixError("Aluno não encontrado.")
    if matriz_id is not None:
        valid = conn.execute(
            "SELECT 1 FROM matrizes_atividades WHERE id=? AND curso_id=?",
            (matriz_id, aluno["curso_id"]),
        ).fetchone()
        if not valid:
            raise StudentMatrixError("A matriz acadêmica não pertence ao curso do aluno.")
        matriz_id = int(matriz_id)
    conn.execute("UPDATE alunos SET matriz_id=? WHERE id=?", (matriz_id, aluno_id))
    return matriz_id


def get_effective_matrix_for_student(conn, aluno_id: int):
    return conn.execute(
        """
        SELECT m.*
          FROM alunos a
          JOIN turmas t ON t.id=a.turma_id
          JOIN matrizes_atividades m
            ON m.id=a.matriz_id AND m.curso_id=t.curso_id
         WHERE a.id=?
        """,
        (aluno_id,),
    ).fetchone()


def get_allowed_activity_version_ids_for_student(conn, aluno_id: int):
    matriz = get_effective_matrix_for_student(conn, aluno_id)
    if not matriz:
        return set(), None
    version_ids = {
        row["atividade_versao_id"]
        for row in conn.execute(
            "SELECT atividade_versao_id FROM matriz_atividade_versao_item WHERE matriz_id=?",
            (matriz["id"],),
        ).fetchall()
    }
    return version_ids, matriz


__all__ = [
    "StudentMatrixError",
    "assign_student_matrix",
    "assign_student_to_turma",
    "get_effective_matrix_for_student",
    "get_allowed_activity_version_ids_for_student",
    "matrix_for_turma_assignment",
]
