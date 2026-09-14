"""The current Matrix is the current Turma's Matrix.

A student who belongs to a Turma is governed by that Turma's Matrix, so moving
Turma A -> Turma B changes what the next request may use immediately, with no
per-student copy to maintain. Hours already requested are never touched: each
requisicao carries its own regra_snapshot_json and that snapshot, not the live
Matrix, governs history.
"""
import json
import sqlite3

import main
from app.prod1_schema import bootstrap_prod1_schema
from app.student_matrix import (
    get_allowed_activity_version_ids_for_student,
    get_effective_matrix_for_student,
)
from tests.canonical_request_test_support import login_student
from tests.versioned_test_support import isolated_versioned_app_env


def _database():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    bootstrap_prod1_schema(conn)
    return conn


def _seed(conn):
    curso = conn.execute(
        "INSERT INTO cursos(nome,codigo,duracao_periodos) VALUES('Curso','C1',8)"
    ).lastrowid
    outro_curso = conn.execute(
        "INSERT INTO cursos(nome,codigo,duracao_periodos) VALUES('Outro','C2',8)"
    ).lastrowid
    matriz_a = conn.execute(
        "INSERT INTO matrizes_atividades(curso_id,nome) VALUES(?,'A')", (curso,)
    ).lastrowid
    matriz_b = conn.execute(
        "INSERT INTO matrizes_atividades(curso_id,nome) VALUES(?,'B')", (curso,)
    ).lastrowid
    turma_a = conn.execute(
        "INSERT INTO turmas(nome,numero,curso_id,matriz_id,ano_inicio,semestre_inicio,codigo) "
        "VALUES('TA',1,?,?,2026,1,'TA')",
        (curso, matriz_a),
    ).lastrowid
    turma_b = conn.execute(
        "INSERT INTO turmas(nome,numero,curso_id,matriz_id,ano_inicio,semestre_inicio,codigo) "
        "VALUES('TB',2,?,?,2026,1,'TB')",
        (curso, matriz_b),
    ).lastrowid
    turma_sem_matriz = conn.execute(
        "INSERT INTO turmas(nome,numero,curso_id,matriz_id,ano_inicio,semestre_inicio,codigo) "
        "VALUES('TC',3,?,NULL,2026,1,'TC')",
        (curso,),
    ).lastrowid
    base = conn.execute(
        "INSERT INTO atividade_base(nome_conceito) VALUES('Base')"
    ).lastrowid
    versao_a = conn.execute(
        "INSERT INTO atividade_versao(atividade_base_id,eixo,numero_versao,status) "
        "VALUES(?,'AAC',1,'ativa')",
        (base,),
    ).lastrowid
    versao_b = conn.execute(
        "INSERT INTO atividade_versao(atividade_base_id,eixo,numero_versao,status) "
        "VALUES(?,'AAC',2,'ativa')",
        (base,),
    ).lastrowid
    for matriz, versao in ((matriz_a, versao_a), (matriz_b, versao_b)):
        conn.execute(
            "INSERT INTO matriz_atividade_versao_item"
            "(matriz_id,atividade_base_id,atividade_versao_id) VALUES(?,?,?)",
            (matriz, base, versao),
        )
    return locals()


def _aluno(conn, turma_id, matriz_id=None, matricula="A1"):
    return conn.execute(
        "INSERT INTO alunos(nome,matricula,turma_id,matriz_id) VALUES('Aluno',?,?,?)",
        (matricula, turma_id, matriz_id),
    ).lastrowid


# ---------------------------------------------------------------------------
# Authority
# ---------------------------------------------------------------------------


def test_turma_matrix_governs_without_any_per_student_copy():
    conn = _database()
    d = _seed(conn)
    aluno = _aluno(conn, d["turma_a"])  # alunos.matriz_id stays NULL

    assert get_effective_matrix_for_student(conn, aluno)["id"] == d["matriz_a"]
    allowed, matriz = get_allowed_activity_version_ids_for_student(conn, aluno)
    assert matriz["id"] == d["matriz_a"]
    assert allowed == {d["versao_a"]}


def test_moving_turma_switches_the_governing_matrix_immediately():
    conn = _database()
    d = _seed(conn)
    aluno = _aluno(conn, d["turma_a"])

    assert get_effective_matrix_for_student(conn, aluno)["id"] == d["matriz_a"]
    conn.execute("UPDATE alunos SET turma_id=? WHERE id=?", (d["turma_b"], aluno))

    assert get_effective_matrix_for_student(conn, aluno)["id"] == d["matriz_b"]
    allowed, _ = get_allowed_activity_version_ids_for_student(conn, aluno)
    assert allowed == {d["versao_b"]}
    assert d["versao_a"] not in allowed


def test_stale_alunos_matriz_id_never_outranks_the_current_turma():
    """Rule 5: Matrix A must not survive because the column still holds it."""
    conn = _database()
    d = _seed(conn)
    # The student still carries Matrix A while already sitting in Turma B.
    aluno = _aluno(conn, d["turma_b"], matriz_id=d["matriz_a"])

    assert get_effective_matrix_for_student(conn, aluno)["id"] == d["matriz_b"]
    allowed, _ = get_allowed_activity_version_ids_for_student(conn, aluno)
    assert allowed == {d["versao_b"]}


def test_turma_without_a_matrix_yields_no_matrix_even_with_a_stale_column():
    conn = _database()
    d = _seed(conn)
    aluno = _aluno(conn, d["turma_sem_matriz"], matriz_id=d["matriz_a"])

    assert get_effective_matrix_for_student(conn, aluno) is None
    assert get_allowed_activity_version_ids_for_student(conn, aluno) == (set(), None)


def test_turma_less_student_still_resolves_through_its_explicit_matrix():
    """The only remaining use of alunos.matriz_id."""
    conn = _database()
    d = _seed(conn)
    aluno = _aluno(conn, None, matriz_id=d["matriz_a"])

    assert get_effective_matrix_for_student(conn, aluno)["id"] == d["matriz_a"]


def test_cross_course_turma_matrix_fails_closed():
    conn = _database()
    d = _seed(conn)
    estranha = conn.execute(
        "INSERT INTO matrizes_atividades(curso_id,nome) VALUES(?,'X')",
        (d["outro_curso"],),
    ).lastrowid
    conn.execute("UPDATE turmas SET matriz_id=? WHERE id=?", (estranha, d["turma_a"]))
    aluno = _aluno(conn, d["turma_a"])

    assert get_effective_matrix_for_student(conn, aluno) is None


# ---------------------------------------------------------------------------
# History is governed by the persisted snapshot, never by the current Turma
# ---------------------------------------------------------------------------


def _snapshot_of(conn, request_id):
    row = conn.execute(
        "SELECT regra_snapshot_json, atividade_versao_id, horas_deferidas, status,"
        " turma_id_snapshot FROM requisicoes WHERE id=?",
        (request_id,),
    ).fetchone()
    return dict(row)


def test_approved_hours_survive_a_turma_move_byte_identically(tmp_path):
    """Rule 3: the historical snapshot and its hours are never rewritten."""
    with isolated_versioned_app_env(tmp_path, "tma1-history.db") as env:
        identity = login_student(env["client"])
        aluno_id = identity["aluno_id"]
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute("UPDATE alunos SET turma_id=1,matriz_id=1 WHERE id=?", (aluno_id,))
            versao_a = conn.execute(
                "SELECT atividade_versao_id FROM matriz_atividade_versao_item"
                " WHERE matriz_id=1 ORDER BY atividade_versao_id LIMIT 1"
            ).fetchone()["atividade_versao_id"]
            conn.commit()

        # An approved historical request under Matrix A.
        with main.app.app_context():
            conn = main.get_db_connection()
            from app.versioning.snapshots import prepare_versioned_requisicao_snapshot

            prepared = prepare_versioned_requisicao_snapshot(
                conn,
                flow_origin="aluno_create",
                aluno_id=aluno_id,
                atividade_versao_id=versao_a,
            )
            request_id = conn.execute(
                """INSERT INTO requisicoes
                     (aluno_id,atividade_versao_id,data_solicitacao,data_evento,
                      horas_solicitadas,nome_evento,status,horas_deferidas,
                      regra_snapshot_json,turma_id_snapshot,turma_codigo_snapshot)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?) RETURNING id""",
                (
                    aluno_id, prepared.atividade_versao_id, "2026-01-10 10:00:00",
                    "2026-01-05", 8.0, "Historico sob Matriz A", "Deferida", 8.0,
                    prepared.snapshot_json, 1, "T1",
                ),
            ).fetchone()["id"]
            conn.commit()
            before = _snapshot_of(conn, request_id)

        # Move the student to Turma 2 / Matrix 2.
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute("UPDATE alunos SET turma_id=2 WHERE id=?", (aluno_id,))
            conn.commit()
            assert get_effective_matrix_for_student(conn, aluno_id)["id"] == 2
            after = _snapshot_of(conn, request_id)

        # Byte-identical snapshot, identical approved hours and version.
        assert after == before
        assert after["horas_deferidas"] == 8.0
        assert after["atividade_versao_id"] == versao_a
        assert json.loads(after["regra_snapshot_json"])["matriz_id_efetiva"] == 1

        # And the historical hours still count after the move.
        assert env["client"].get("/aluno/progresso").status_code == 200
        from app.versioning.request_history import list_approved_request_history

        with main.app.app_context():
            approved = list_approved_request_history(
                main.get_db_connection(), aluno_id=aluno_id
            )
        assert sum(row.approved_hours for row in approved) >= 8.0
        assert any(row.atividade_versao_id == versao_a for row in approved)


def test_moving_turma_does_not_flag_previous_requests_as_out_of_scope(tmp_path):
    """A legitimate transfer must not re-judge history against the new Matrix."""
    from tests.canonical_request_test_support import login_admin

    with isolated_versioned_app_env(tmp_path, "tma1-scope-flag.db") as env:
        identity = login_student(env["client"])
        aluno_id = identity["aluno_id"]
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute("UPDATE alunos SET turma_id=1,matriz_id=NULL WHERE id=?", (aluno_id,))
            versao_a = conn.execute(
                "SELECT atividade_versao_id FROM matriz_atividade_versao_item"
                " WHERE matriz_id=1 ORDER BY atividade_versao_id LIMIT 1"
            ).fetchone()["atividade_versao_id"]
            from app.versioning.snapshots import prepare_versioned_requisicao_snapshot

            prepared = prepare_versioned_requisicao_snapshot(
                conn,
                flow_origin="aluno_create",
                aluno_id=aluno_id,
                atividade_versao_id=versao_a,
            )
            conn.execute(
                """INSERT INTO requisicoes
                     (aluno_id,atividade_versao_id,data_solicitacao,data_evento,
                      horas_solicitadas,nome_evento,status,regra_snapshot_json,
                      turma_id_snapshot,turma_codigo_snapshot)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    aluno_id, prepared.atividade_versao_id, "2026-01-10 10:00:00",
                    "2026-01-05", 4.0, "ANTES DA TRANSFERENCIA", "Pendente",
                    prepared.snapshot_json, 1, "T1",
                ),
            )
            # Turma 2 carries a different Matrix, so the request now sits
            # outside the student's current Matrix — legitimately.
            conn.execute("UPDATE alunos SET turma_id=2 WHERE id=?", (aluno_id,))
            conn.commit()
            assert get_effective_matrix_for_student(conn, aluno_id)["id"] == 2
            allowed, _ = get_allowed_activity_version_ids_for_student(conn, aluno_id)
            assert versao_a not in allowed

        login_admin(env["client"])
        page = env["client"].get("/admin/requisicoes")
        assert page.status_code == 200
        html = page.get_data(as_text=True)
        assert "ANTES DA TRANSFERENCIA" in html
        # The row carries an authoritative snapshot, so it is not an issue.
        marker = html[: html.index("ANTES DA TRANSFERENCIA")]
        row_start = marker.rindex("data-matrix-scope-issue=")
        assert html[row_start : row_start + 40].startswith(
            "data-matrix-scope-issue=\"0\""
        ), html[row_start : row_start + 60]
