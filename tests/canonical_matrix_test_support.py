"""Small builders for matrix tests on the prod-1 authority graph."""
from __future__ import annotations


def login_admin(client) -> None:
    with client.session_transaction() as session:
        session.update(user_id=1, user_type="admin", user_name="Administrador")


def seed_matrix_graph(conn, *, name="Canonical matrix test") -> dict[str, int]:
    course_id = conn.execute("SELECT id FROM cursos ORDER BY id LIMIT 1").fetchone()["id"]
    matrix_id = conn.execute(
        """INSERT INTO matrizes_atividades
               (curso_id,nome,versao,status,horas_aac_obrigatorias,horas_extensao_obrigatorias)
             VALUES (?,?,'test','rascunho',100,50)""",
        (course_id, name),
    ).lastrowid
    base_id = conn.execute(
        "INSERT INTO atividade_base(nome_conceito,descricao,status) VALUES (?,?,'ativo')",
        (f"{name} activity", "canonical test base"),
    ).lastrowid
    versions = []
    for number, status in ((1, "ativa"), (2, "ativa"), (3, "inativa")):
        versions.append(conn.execute(
            """INSERT INTO atividade_versao
                   (atividade_base_id,eixo,grupo,
                    ch_por_evento,limite_semestre,limite_total,numero_versao,status)
                 VALUES (?,'AAC','1 - Teste',2,20,60,?,?)""",
            (base_id, number, status),
        ).lastrowid)
    conn.execute(
        """INSERT INTO matriz_atividade_versao_item
               (matriz_id,atividade_base_id,atividade_versao_id) VALUES (?,?,?)""",
        (matrix_id, base_id, versions[0]),
    )
    conn.commit()
    return {
        "course_id": course_id,
        "matrix_id": matrix_id,
        "base_id": base_id,
        "v1": versions[0],
        "v2": versions[1],
        "v3_inactive": versions[2],
    }


def current_version_id(conn, seed: dict[str, int]) -> int | None:
    row = conn.execute(
        """SELECT atividade_versao_id FROM matriz_atividade_versao_item
             WHERE matriz_id=? AND atividade_base_id=?""",
        (seed["matrix_id"], seed["base_id"]),
    ).fetchone()
    return row["atividade_versao_id"] if row else None
