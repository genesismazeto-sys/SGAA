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


def resequence_turma_aluno_matriculas(conn, turma_id):
    if not turma_id:
        return

    turma = conn.execute("SELECT codigo FROM turmas WHERE id = ?", (turma_id,)).fetchone()
    if not turma:
        return

    turma_codigo = str(turma["codigo"] or "").strip()
    if not turma_codigo:
        return

    alunos = conn.execute(
        "SELECT id, nome, email FROM alunos WHERE turma_id = ?",
        (turma_id,),
    ).fetchall()
    if not alunos:
        return

    alunos_ordenados = sorted(
        alunos,
        key=lambda row: (
            ptbr_text_sort_key(row["nome"]),
            ptbr_text_sort_key(row["email"]),
            row["id"],
        ),
    )

    temporarias = [
        (f"__TMP_RESEQ__{turma_id}__{row['id']}__{secrets.token_hex(4)}", row["id"])
        for row in alunos_ordenados
    ]
    conn.executemany("UPDATE alunos SET matricula = ? WHERE id = ?", temporarias)

    total_alunos = len(alunos_ordenados)
    finais = [
        (build_turma_aluno_matricula(turma_codigo, ordem, total_alunos), row["id"])
        for ordem, row in enumerate(alunos_ordenados, start=1)
    ]
    conn.executemany("UPDATE alunos SET matricula = ? WHERE id = ?", finais)


def resequence_turma_aluno_matriculas_for_ids(conn, *turma_ids):
    turma_ids_validos = []
    for turma_id in turma_ids:
        if turma_id in (None, ""):
            continue
        turma_id_int = int(turma_id)
        if turma_id_int not in turma_ids_validos:
            turma_ids_validos.append(turma_id_int)
    for turma_id in turma_ids_validos:
        resequence_turma_aluno_matriculas(conn, turma_id)
