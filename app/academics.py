import secrets

from app.text import ptbr_text_sort_key

DEFAULT_CURSO_TOTAL_HORAS_AAC = 160
DEFAULT_CURSO_TOTAL_HORAS_AEU = 80


def gerar_codigo_turma(curso_codigo: str, numero: int) -> str:
    return f"{curso_codigo}-T{int(numero):02d}"


def build_turma_aluno_matricula(turma_codigo, ordem, total_alunos):
    codigo = str(turma_codigo or "").strip()
    if not codigo:
        raise ValueError("Turma sem código para gerar matrícula.")
    width = max(3, len(str(max(1, total_alunos))))
    return f"{codigo}.{ordem:0{width}d}"


def _turma_resequence_plan(conn, turma_id):
    """The ordered students of a Turma and the code their matrículas derive from."""
    if not turma_id:
        return None

    turma = conn.execute("SELECT codigo FROM turmas WHERE id = ?", (turma_id,)).fetchone()
    if not turma:
        return None

    turma_codigo = str(turma["codigo"] or "").strip()
    if not turma_codigo:
        return None

    alunos = conn.execute(
        "SELECT id, nome, email FROM alunos WHERE turma_id = ?",
        (turma_id,),
    ).fetchall()
    if not alunos:
        return None

    alunos_ordenados = sorted(
        alunos,
        key=lambda row: (
            ptbr_text_sort_key(row["nome"]),
            ptbr_text_sort_key(row["email"]),
            row["id"],
        ),
    )
    return turma_codigo, alunos_ordenados


def _hold_matriculas(conn, rows, turma_id):
    """Park these matrículas on unique placeholders so finals can be assigned."""
    conn.executemany(
        "UPDATE alunos SET matricula = ? WHERE id = ?",
        [
            (f"__TMP_RESEQ__{turma_id}__{row['id']}__{secrets.token_hex(4)}", row["id"])
            for row in rows
        ],
    )


def _assign_final_matriculas(conn, turma_codigo, rows):
    total_alunos = len(rows)
    conn.executemany(
        "UPDATE alunos SET matricula = ? WHERE id = ?",
        [
            (build_turma_aluno_matricula(turma_codigo, ordem, total_alunos), row["id"])
            for ordem, row in enumerate(rows, start=1)
        ],
    )


def resequence_turma_aluno_matriculas(conn, turma_id):
    plan = _turma_resequence_plan(conn, turma_id)
    if plan is None:
        return
    turma_codigo, alunos_ordenados = plan
    _hold_matriculas(conn, alunos_ordenados, turma_id)
    _assign_final_matriculas(conn, turma_codigo, alunos_ordenados)


def resequence_turma_aluno_matriculas_for_ids(conn, *turma_ids):
    """Resequence several Turmas as one operation.

    The placeholder pass has to cover every Turma involved before any final
    matrícula is written. Holding them one Turma at a time only protects rows
    inside that Turma, and a student who just moved out of it still occupies a
    name it is about to hand to somebody else — the transfer then dies on
    ``UNIQUE constraint failed: alunos.matricula``. Parking all of them first
    makes the outcome independent of the order the Turmas are passed in.
    """
    turma_ids_validos = []
    for turma_id in turma_ids:
        if turma_id in (None, ""):
            continue
        turma_id_int = int(turma_id)
        if turma_id_int not in turma_ids_validos:
            turma_ids_validos.append(turma_id_int)

    planos = []
    for turma_id in turma_ids_validos:
        plano = _turma_resequence_plan(conn, turma_id)
        if plano is not None:
            planos.append((turma_id, *plano))

    for turma_id, _turma_codigo, alunos_ordenados in planos:
        _hold_matriculas(conn, alunos_ordenados, turma_id)
    for _turma_id, turma_codigo, alunos_ordenados in planos:
        _assign_final_matriculas(conn, turma_codigo, alunos_ordenados)
