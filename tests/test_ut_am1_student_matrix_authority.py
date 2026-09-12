import sqlite3

import pytest

from app.prod1_schema import bootstrap_prod1_schema


def _database():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    bootstrap_prod1_schema(conn)
    return conn


def _seed(conn):
    from app.student_matrix import assign_student_to_turma

    c1 = conn.execute(
        "INSERT INTO cursos(nome,codigo,duracao_periodos) VALUES('Curso 1','C1',8)"
    ).lastrowid
    c2 = conn.execute(
        "INSERT INTO cursos(nome,codigo,duracao_periodos) VALUES('Curso 2','C2',8)"
    ).lastrowid
    m1 = conn.execute(
        "INSERT INTO matrizes_atividades(curso_id,nome) VALUES(?,'M1')", (c1,)
    ).lastrowid
    m2 = conn.execute(
        "INSERT INTO matrizes_atividades(curso_id,nome) VALUES(?,'M2')", (c1,)
    ).lastrowid
    other = conn.execute(
        "INSERT INTO matrizes_atividades(curso_id,nome) VALUES(?,'Other')", (c2,)
    ).lastrowid
    t1 = conn.execute(
        "INSERT INTO turmas(nome,numero,curso_id,matriz_id,ano_inicio,semestre_inicio,codigo) "
        "VALUES('T1',1,?,?,2026,1,'T1')",
        (c1, m1),
    ).lastrowid
    t2 = conn.execute(
        "INSERT INTO turmas(nome,numero,curso_id,matriz_id,ano_inicio,semestre_inicio,codigo) "
        "VALUES('T2',2,?,?,2026,1,'T2')",
        (c1, m2),
    ).lastrowid
    t3 = conn.execute(
        "INSERT INTO turmas(nome,numero,curso_id,matriz_id,ano_inicio,semestre_inicio,codigo) "
        "VALUES('T3',3,?,NULL,2026,1,'T3')",
        (c1,),
    ).lastrowid
    t4 = conn.execute(
        "INSERT INTO turmas(nome,numero,curso_id,matriz_id,ano_inicio,semestre_inicio,codigo) "
        "VALUES('T4',1,?,?,2026,1,'T4')",
        (c2, other),
    ).lastrowid
    student = conn.execute(
        "INSERT INTO alunos(nome,matricula,turma_id,matriz_id) VALUES('Aluno','A1',?,?)",
        (t1, m1),
    ).lastrowid
    null_student = conn.execute(
        "INSERT INTO alunos(nome,matricula) VALUES('Sem matriz','A2')"
    ).lastrowid
    return locals()


def test_transfer_preserves_existing_matrix_and_turma_default_change_does_not_cascade():
    from app.student_matrix import assign_student_to_turma

    conn = _database()
    data = _seed(conn)
    assign_student_to_turma(conn, data["student"], data["t2"])
    conn.execute("UPDATE turmas SET matriz_id=? WHERE id=?", (data["m2"], data["t1"]))
    row = conn.execute("SELECT turma_id,matriz_id FROM alunos WHERE id=?", (data["student"],)).fetchone()
    assert (row["turma_id"], row["matriz_id"]) == (data["t2"], data["m1"])


def test_null_student_initializes_from_default_and_remains_null_without_default():
    from app.student_matrix import assign_student_to_turma

    conn = _database()
    data = _seed(conn)
    assign_student_to_turma(conn, data["null_student"], data["t1"])
    assert conn.execute("SELECT matriz_id FROM alunos WHERE id=?", (data["null_student"],)).fetchone()[0] == data["m1"]
    conn.execute("UPDATE alunos SET turma_id=NULL,matriz_id=NULL WHERE id=?", (data["null_student"],))
    assign_student_to_turma(conn, data["null_student"], data["t3"])
    assert conn.execute("SELECT matriz_id FROM alunos WHERE id=?", (data["null_student"],)).fetchone()[0] is None


def test_cross_course_transfer_and_explicit_assignment_fail_closed():
    from app.student_matrix import StudentMatrixError, assign_student_matrix, assign_student_to_turma

    conn = _database()
    data = _seed(conn)
    with pytest.raises(StudentMatrixError):
        assign_student_to_turma(conn, data["student"], data["t4"])
    with pytest.raises(StudentMatrixError):
        assign_student_matrix(conn, data["student"], data["other"])


def test_explicit_matrix_change_does_not_rewrite_request_history():
    from app.student_matrix import assign_student_matrix

    conn = _database()
    data = _seed(conn)
    base = conn.execute("INSERT INTO atividade_base(nome_conceito) VALUES('Base')").lastrowid
    version = conn.execute(
        "INSERT INTO atividade_versao(atividade_base_id,eixo,numero_versao,status) VALUES(?,'AAC',1,'ativa')",
        (base,),
    ).lastrowid
    request_id = conn.execute(
        "INSERT INTO requisicoes(aluno_id,atividade_versao_id,data_solicitacao,data_evento,horas_solicitadas,status,regra_snapshot_json,turma_id_snapshot,turma_codigo_snapshot) "
        "VALUES(?,?,date('now'),date('now'),1,'Deferida','{}',?, 'T1')",
        (data["student"], version, data["t1"]),
    ).lastrowid
    conn.execute("UPDATE requisicoes SET horas_deferidas=1 WHERE id=?", (request_id,))
    before = tuple(conn.execute("SELECT atividade_versao_id,regra_snapshot_json,turma_id_snapshot,turma_codigo_snapshot,status,horas_deferidas FROM requisicoes WHERE id=?", (request_id,)).fetchone())
    assign_student_matrix(conn, data["student"], data["m2"])
    from app.student_matrix import assign_student_to_turma
    assign_student_to_turma(conn, data["student"], data["t2"])
    after = tuple(conn.execute("SELECT atividade_versao_id,regra_snapshot_json,turma_id_snapshot,turma_codigo_snapshot,status,horas_deferidas FROM requisicoes WHERE id=?", (request_id,)).fetchone())
    assert before == after


def test_matrix_delete_is_restricted_by_student_reference():
    conn = _database()
    data = _seed(conn)
    conn.execute("UPDATE turmas SET matriz_id=NULL")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM matrizes_atividades WHERE id=?", (data["m1"],))
