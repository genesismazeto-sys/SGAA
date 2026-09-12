from __future__ import annotations

import re


class StudentMatrixError(ValueError):
    """Raised when a student Matrix would conflict with the academic Curso."""


# Somente digitos ASCII: int() aceitaria "1_0", digitos unicode e espacos.
_SUBMITTED_MATRIZ_ID_RE = re.compile(r"-?[0-9]+")


def parse_submitted_matriz_id(raw: str | None) -> int | None:
    """Read a submitted Matrix choice without confusing "none" with garbage.

    An empty submission is the explicit "Sem matriz" choice and clears the
    authority. Anything else must name a Matrix, so a non-empty value that is
    not a plain integer is a malformed request and fails closed here instead of
    being silently coerced into a clear.
    """
    value = (raw or "").strip()
    if not value:
        return None
    if not _SUBMITTED_MATRIZ_ID_RE.fullmatch(value):
        raise StudentMatrixError("A matriz acadêmica selecionada é inválida.")
    try:
        return int(value)
    except ValueError as exc:
        # Python 3.11+ limits decimal-to-int conversion size. Keep that safety
        # boundary local and surface every integer-like conversion rejection
        # through the same controlled validation path as malformed syntax.
        raise StudentMatrixError(
            "A matriz acadêmica selecionada é inválida."
        ) from exc


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


def validate_student_matrix_for_turma(
    conn, *, matriz_id: int | None, turma_id: int | None
) -> int | None:
    """Resolve an explicitly chosen Matrix against the Turma that scopes it.

    A Turma constrains the choice to its own Curso. Without a Turma there is no
    Curso to validate against, so the chosen Matrix itself establishes the
    student's academic Curso context.
    """
    if matriz_id is None:
        return None
    matriz = conn.execute(
        "SELECT id,curso_id FROM matrizes_atividades WHERE id=?", (matriz_id,)
    ).fetchone()
    if not matriz:
        raise StudentMatrixError("A matriz acadêmica selecionada não existe.")
    if turma_id is not None:
        turma = _turma_scope(conn, turma_id)
        if matriz["curso_id"] != turma["curso_id"]:
            raise StudentMatrixError(
                "A matriz acadêmica não pertence ao curso da turma do aluno."
            )
    return int(matriz["id"])


def assign_student_matrix(conn, aluno_id: int, matriz_id: int | None) -> int | None:
    """Explicitly set the student's academic Matrix authority."""
    aluno = conn.execute(
        "SELECT id,turma_id FROM alunos WHERE id=?", (aluno_id,)
    ).fetchone()
    if not aluno:
        raise StudentMatrixError("Aluno não encontrado.")
    matriz_id = validate_student_matrix_for_turma(
        conn, matriz_id=matriz_id, turma_id=aluno["turma_id"]
    )
    conn.execute("UPDATE alunos SET matriz_id=? WHERE id=?", (matriz_id, aluno_id))
    return matriz_id


def resolve_student_matrix_for_edit(
    conn,
    *,
    current_matriz_id: int | None,
    current_turma_id: int | None,
    turma_id: int | None,
    explicit_matriz_id: int | None,
    matrix_explicitly_submitted: bool,
) -> int | None:
    """Reconcile a simultaneous Turma and academic Matrix edit.

    An explicitly submitted Matrix wins and is validated against the destination
    Turma, so the previous Turma can never veto the new choice and the new Turma
    can never silently replace it. Without an explicit choice the ordinary Turma
    reassignment rules preserve whatever authority the student already holds.
    """
    if not matrix_explicitly_submitted:
        return matrix_for_turma_assignment(
            conn,
            current_matriz_id=current_matriz_id,
            turma_id=turma_id,
            current_turma_id=current_turma_id,
        )
    return validate_student_matrix_for_turma(
        conn, matriz_id=explicit_matriz_id, turma_id=turma_id
    )


def list_assignable_matrices_for_student(conn, turma_id: int | None):
    """Matrices an admin may explicitly assign, carrying Curso context for labels."""
    if turma_id is not None:
        return conn.execute(
            """
            SELECT m.id,m.nome,m.status,c.nome AS curso_nome,c.codigo AS curso_codigo
              FROM turmas t
              JOIN matrizes_atividades m ON m.curso_id=t.curso_id
              JOIN cursos c ON c.id=m.curso_id
             WHERE t.id=?
          ORDER BY m.nome
            """,
            (turma_id,),
        ).fetchall()
    return conn.execute(
        """
        SELECT m.id,m.nome,m.status,c.nome AS curso_nome,c.codigo AS curso_codigo
          FROM matrizes_atividades m
          JOIN cursos c ON c.id=m.curso_id
      ORDER BY c.nome,m.nome
        """
    ).fetchall()


def get_effective_matrix_for_student(conn, aluno_id: int):
    """Resolve the student's academic Matrix authority.

    The value always comes from ``alunos.matriz_id``; a Turma is never its
    source. A Turma-bound student additionally requires Curso compatibility, so
    a stale or corrupt pairing fails closed instead of silently adopting the
    Turma default. A Turma-less student resolves against the Matrix itself,
    which supplies its own Curso identity. "No Turma" is not "no Matrix".
    """
    return conn.execute(
        """
        SELECT m.*
          FROM alunos a
          JOIN matrizes_atividades m ON m.id=a.matriz_id
          LEFT JOIN turmas t ON t.id=a.turma_id
         WHERE a.id=?
           AND (a.turma_id IS NULL OR (t.id IS NOT NULL AND m.curso_id=t.curso_id))
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
    "list_assignable_matrices_for_student",
    "matrix_for_turma_assignment",
    "parse_submitted_matriz_id",
    "resolve_student_matrix_for_edit",
    "validate_student_matrix_for_turma",
]
