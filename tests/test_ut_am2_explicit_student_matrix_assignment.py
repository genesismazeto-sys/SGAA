"""Explicit admin assignment of the student-owned academic Matrix (UT-AM2).

UT-AM1 made ``alunos.matriz_id`` the academic authority and left
``turmas.matriz_id`` a mere default.  This module pins the admin operation that
makes that authority usable: assigning, changing and clearing a student's
academic Matrix, for students bound to a Turma and for Turma-less students
(AM1 finding F5), plus the dedicated NULL fail-closed regression (AM1 finding
F8).
"""
import os
import sqlite3
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main
from app import db as app_db_module
from app.prod1_schema import bootstrap_prod1_schema


# --------------------------------------------------------------------------
# Domain fixtures (in-memory; never touches any runtime database)
# --------------------------------------------------------------------------


def _database():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    bootstrap_prod1_schema(conn)
    return conn


def _seed(conn):
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
    t4 = conn.execute(
        "INSERT INTO turmas(nome,numero,curso_id,matriz_id,ano_inicio,semestre_inicio,codigo) "
        "VALUES('T4',1,?,?,2026,1,'T4')",
        (c2, other),
    ).lastrowid
    # Aluno matriculado numa Turma, com autoridade de matriz propria.
    student = conn.execute(
        "INSERT INTO alunos(nome,matricula,turma_id,matriz_id) VALUES('Aluno','A1',?,?)",
        (t1, m1),
    ).lastrowid
    # Aluno sem Turma e sem matriz (cenario F5).
    loose = conn.execute(
        "INSERT INTO alunos(nome,matricula) VALUES('Sem turma','A2')"
    ).lastrowid
    # Aluno numa Turma cuja matriz padrao existe, mas sem autoridade propria.
    nullmatrix = conn.execute(
        "INSERT INTO alunos(nome,matricula,turma_id,matriz_id) VALUES('Sem matriz','A3',?,NULL)",
        (t1,),
    ).lastrowid
    return locals()


def _matriz_do_aluno(conn, aluno_id):
    return conn.execute(
        "SELECT matriz_id FROM alunos WHERE id=?", (aluno_id,)
    ).fetchone()[0]


# --------------------------------------------------------------------------
# 1-4. Turma-bound explicit assignment
# --------------------------------------------------------------------------


def test_admin_assigns_same_curso_matrix_to_student_in_turma():
    from app.student_matrix import assign_student_matrix

    conn = _database()
    data = _seed(conn)
    conn.execute("UPDATE alunos SET matriz_id=NULL WHERE id=?", (data["student"],))

    returned = assign_student_matrix(conn, data["student"], data["m1"])

    assert returned == data["m1"]
    assert _matriz_do_aluno(conn, data["student"]) == data["m1"]


def test_admin_changes_matrix_between_two_matrices_of_the_same_curso():
    from app.student_matrix import assign_student_matrix

    conn = _database()
    data = _seed(conn)
    assert _matriz_do_aluno(conn, data["student"]) == data["m1"]

    assign_student_matrix(conn, data["student"], data["m2"])

    assert _matriz_do_aluno(conn, data["student"]) == data["m2"]


def test_cross_curso_assignment_is_rejected_while_student_is_in_a_turma():
    from app.student_matrix import StudentMatrixError, assign_student_matrix

    conn = _database()
    data = _seed(conn)

    with pytest.raises(StudentMatrixError):
        assign_student_matrix(conn, data["student"], data["other"])


def test_rejected_assignment_preserves_the_previous_matrix():
    from app.student_matrix import StudentMatrixError, assign_student_matrix

    conn = _database()
    data = _seed(conn)

    with pytest.raises(StudentMatrixError):
        assign_student_matrix(conn, data["student"], data["other"])
    assert _matriz_do_aluno(conn, data["student"]) == data["m1"]

    # Uma matriz inexistente tambem falha fechada, sem apagar a autoridade atual.
    with pytest.raises(StudentMatrixError):
        assign_student_matrix(conn, data["student"], 99999)
    assert _matriz_do_aluno(conn, data["student"]) == data["m1"]


# --------------------------------------------------------------------------
# 5. Clear to NULL
# --------------------------------------------------------------------------


def test_admin_can_clear_matrix_to_null():
    from app.student_matrix import assign_student_matrix

    conn = _database()
    data = _seed(conn)

    assert assign_student_matrix(conn, data["student"], None) is None
    assert _matriz_do_aluno(conn, data["student"]) is None


# --------------------------------------------------------------------------
# 6-7. Invariants: history and Turma default
# --------------------------------------------------------------------------


def test_matrix_assignment_leaves_request_history_untouched():
    from app.student_matrix import assign_student_matrix

    conn = _database()
    data = _seed(conn)
    base = conn.execute(
        "INSERT INTO atividade_base(nome_conceito) VALUES('Base')"
    ).lastrowid
    version = conn.execute(
        "INSERT INTO atividade_versao(atividade_base_id,eixo,numero_versao,status) "
        "VALUES(?,'AAC',1,'ativa')",
        (base,),
    ).lastrowid
    request_id = conn.execute(
        "INSERT INTO requisicoes(aluno_id,atividade_versao_id,data_solicitacao,data_evento,"
        "horas_solicitadas,status,regra_snapshot_json,turma_id_snapshot,turma_codigo_snapshot) "
        "VALUES(?,?,date('now'),date('now'),10,'Deferida','{\"v\":1}',?,'T1')",
        (data["student"], version, data["t1"]),
    ).lastrowid
    conn.execute("UPDATE requisicoes SET horas_deferidas=10 WHERE id=?", (request_id,))

    campos = (
        "atividade_versao_id,regra_snapshot_json,horas_solicitadas,horas_deferidas,"
        "status,turma_id_snapshot,turma_codigo_snapshot"
    )
    before = tuple(
        conn.execute(
            f"SELECT {campos} FROM requisicoes WHERE id=?", (request_id,)
        ).fetchone()
    )

    assign_student_matrix(conn, data["student"], data["m2"])

    after = tuple(
        conn.execute(
            f"SELECT {campos} FROM requisicoes WHERE id=?", (request_id,)
        ).fetchone()
    )
    assert before == after
    # A aprovacao historica continua valendo 10 h sob a Versao 1.
    assert after[3] == 10
    assert after[0] == version


def test_matrix_assignment_never_touches_the_turma_default():
    from app.student_matrix import assign_student_matrix

    conn = _database()
    data = _seed(conn)
    defaults_before = conn.execute(
        "SELECT id,matriz_id FROM turmas ORDER BY id"
    ).fetchall()

    assign_student_matrix(conn, data["student"], data["m2"])

    defaults_after = conn.execute(
        "SELECT id,matriz_id FROM turmas ORDER BY id"
    ).fetchall()
    assert [tuple(r) for r in defaults_before] == [tuple(r) for r in defaults_after]
    assert conn.execute(
        "SELECT matriz_id FROM turmas WHERE id=?", (data["t1"],)
    ).fetchone()[0] == data["m1"]


def test_changing_the_turma_default_does_not_change_the_student_matrix():
    conn = _database()
    data = _seed(conn)

    conn.execute("UPDATE turmas SET matriz_id=? WHERE id=?", (data["m2"], data["t1"]))

    assert _matriz_do_aluno(conn, data["student"]) == data["m1"]


# --------------------------------------------------------------------------
# 8-10. Turma-less students (AM1 finding F5)
# --------------------------------------------------------------------------


def test_student_without_turma_can_explicitly_receive_a_matrix():
    from app.student_matrix import assign_student_matrix

    conn = _database()
    data = _seed(conn)
    assert conn.execute(
        "SELECT turma_id FROM alunos WHERE id=?", (data["loose"],)
    ).fetchone()[0] is None

    returned = assign_student_matrix(conn, data["loose"], data["m1"])

    assert returned == data["m1"]
    assert _matriz_do_aluno(conn, data["loose"]) == data["m1"]
    # Nenhuma Turma ficticia foi criada nem vinculada.
    assert conn.execute(
        "SELECT turma_id FROM alunos WHERE id=?", (data["loose"],)
    ).fetchone()[0] is None


def test_student_without_turma_can_change_and_clear_matrix_explicitly():
    from app.student_matrix import assign_student_matrix

    conn = _database()
    data = _seed(conn)

    assign_student_matrix(conn, data["loose"], data["m1"])
    # Sem Turma nao existe Curso para restringir: a propria matriz define o contexto.
    assign_student_matrix(conn, data["loose"], data["other"])
    assert _matriz_do_aluno(conn, data["loose"]) == data["other"]

    assign_student_matrix(conn, data["loose"], None)
    assert _matriz_do_aluno(conn, data["loose"]) is None


def test_student_without_turma_still_cannot_enter_an_incompatible_turma():
    from app.student_matrix import (
        StudentMatrixError,
        assign_student_matrix,
        assign_student_to_turma,
    )

    conn = _database()
    data = _seed(conn)
    assign_student_matrix(conn, data["loose"], data["m1"])

    with pytest.raises(StudentMatrixError):
        assign_student_to_turma(conn, data["loose"], data["t4"])

    assert _matriz_do_aluno(conn, data["loose"]) == data["m1"]
    assert conn.execute(
        "SELECT turma_id FROM alunos WHERE id=?", (data["loose"],)
    ).fetchone()[0] is None

    # A mesma matriz continua compativel com uma Turma do proprio Curso.
    assign_student_to_turma(conn, data["loose"], data["t2"])
    assert _matriz_do_aluno(conn, data["loose"]) == data["m1"]


def test_nonexistent_matrix_is_rejected_for_a_turma_less_student():
    from app.student_matrix import StudentMatrixError, assign_student_matrix

    conn = _database()
    data = _seed(conn)

    with pytest.raises(StudentMatrixError):
        assign_student_matrix(conn, data["loose"], 99999)
    assert _matriz_do_aluno(conn, data["loose"]) is None


# --------------------------------------------------------------------------
# 11. NULL fail-closed regression (AM1 finding F8)
# --------------------------------------------------------------------------


def test_null_student_matrix_does_not_fall_back_to_the_turma_default():
    """A Turma default must never stand in for a missing student authority."""
    from app.student_matrix import (
        get_allowed_activity_version_ids_for_student,
        get_effective_matrix_for_student,
    )

    conn = _database()
    data = _seed(conn)
    base = conn.execute(
        "INSERT INTO atividade_base(nome_conceito) VALUES('Base F8')"
    ).lastrowid
    version = conn.execute(
        "INSERT INTO atividade_versao(atividade_base_id,eixo,numero_versao,status) "
        "VALUES(?,'AAC',1,'ativa')",
        (base,),
    ).lastrowid
    # A matriz padrao da Turma tem conteudo: um fallback devolveria esta versao.
    conn.execute(
        "INSERT INTO matriz_atividade_versao_item(matriz_id,atividade_base_id,atividade_versao_id) "
        "VALUES(?,?,?)",
        (data["m1"], base, version),
    )

    aluno = conn.execute(
        "SELECT turma_id,matriz_id FROM alunos WHERE id=?", (data["nullmatrix"],)
    ).fetchone()
    assert aluno["turma_id"] == data["t1"]
    assert aluno["matriz_id"] is None
    assert conn.execute(
        "SELECT matriz_id FROM turmas WHERE id=?", (data["t1"],)
    ).fetchone()[0] == data["m1"]

    assert get_effective_matrix_for_student(conn, data["nullmatrix"]) is None

    allowed, matriz = get_allowed_activity_version_ids_for_student(
        conn, data["nullmatrix"]
    )
    assert matriz is None
    assert allowed == set()
    assert version not in allowed

    # Controle: com autoridade propria a mesma versao passa a ser elegivel.
    conn.execute(
        "UPDATE alunos SET matriz_id=? WHERE id=?", (data["m1"], data["nullmatrix"])
    )
    allowed_com_matriz, matriz_com = get_allowed_activity_version_ids_for_student(
        conn, data["nullmatrix"]
    )
    assert matriz_com is not None
    assert allowed_com_matriz == {version}


# --------------------------------------------------------------------------
# Effective-Matrix resolution: the authority is alunos.matriz_id, not the Turma
# --------------------------------------------------------------------------


def _seed_matrix_content(conn, data):
    """Give M1 and Other one selected Activity Version each."""
    base = conn.execute(
        "INSERT INTO atividade_base(nome_conceito) VALUES('Base efetiva')"
    ).lastrowid
    v_m1 = conn.execute(
        "INSERT INTO atividade_versao(atividade_base_id,eixo,numero_versao,status) "
        "VALUES(?,'AAC',1,'ativa')",
        (base,),
    ).lastrowid
    v_other = conn.execute(
        "INSERT INTO atividade_versao(atividade_base_id,eixo,numero_versao,status) "
        "VALUES(?,'AAC',2,'ativa')",
        (base,),
    ).lastrowid
    conn.execute(
        "INSERT INTO matriz_atividade_versao_item(matriz_id,atividade_base_id,atividade_versao_id) "
        "VALUES(?,?,?)",
        (data["m1"], base, v_m1),
    )
    conn.execute(
        "INSERT INTO matriz_atividade_versao_item(matriz_id,atividade_base_id,atividade_versao_id) "
        "VALUES(?,?,?)",
        (data["other"], base, v_other),
    )
    return base, v_m1, v_other


def test_turma_less_student_with_matrix_has_an_effective_matrix():
    """TEST 1 — detachment from a Turma must not erase the academic Matrix."""
    from app.student_matrix import (
        assign_student_matrix,
        get_effective_matrix_for_student,
    )

    conn = _database()
    data = _seed(conn)
    assign_student_matrix(conn, data["loose"], data["m1"])

    matriz = get_effective_matrix_for_student(conn, data["loose"])

    assert matriz is not None
    assert matriz["id"] == data["m1"]
    assert matriz["curso_id"] == data["c1"]


def test_turma_less_student_allowed_versions_come_from_its_own_matrix():
    """TEST 2 — eligibility is derived from M, not from any Turma."""
    from app.student_matrix import (
        assign_student_matrix,
        get_allowed_activity_version_ids_for_student,
    )

    conn = _database()
    data = _seed(conn)
    _base, v_m1, v_other = _seed_matrix_content(conn, data)
    assign_student_matrix(conn, data["loose"], data["m1"])

    allowed, matriz = get_allowed_activity_version_ids_for_student(conn, data["loose"])

    assert matriz is not None and matriz["id"] == data["m1"]
    assert allowed == {v_m1}
    assert v_other not in allowed


def test_turma_less_student_version_resolver_resolves_exact_selected_version():
    """TEST 3 — the versioning resolver must not gate on a Turma either."""
    from app.student_matrix import assign_student_matrix
    from app.versioning.resolver import resolver_versao_por_aluno

    conn = _database()
    data = _seed(conn)
    _base, v_m1, v_other = _seed_matrix_content(conn, data)
    assign_student_matrix(conn, data["loose"], data["m1"])

    resolvido = resolver_versao_por_aluno(
        conn, aluno_id=data["loose"], atividade_versao_id=v_m1
    )
    assert resolvido["status"] == "resolved"
    assert resolvido["matriz_id_efetiva"] == data["m1"]
    assert resolvido["atividade_versao_id"] == v_m1

    # Uma versao fora da matriz do aluno continua nao resolvendo.
    fora = resolver_versao_por_aluno(
        conn, aluno_id=data["loose"], atividade_versao_id=v_other
    )
    assert fora["status"] == "not_found"


def test_turma_less_student_without_matrix_stays_fail_closed():
    """TEST 4 — no Turma AND no Matrix resolves to nothing."""
    from app.student_matrix import (
        get_allowed_activity_version_ids_for_student,
        get_effective_matrix_for_student,
    )
    from app.versioning.resolver import resolver_versao_por_aluno

    conn = _database()
    data = _seed(conn)
    _base, v_m1, _v_other = _seed_matrix_content(conn, data)

    assert get_effective_matrix_for_student(conn, data["loose"]) is None
    allowed, matriz = get_allowed_activity_version_ids_for_student(conn, data["loose"])
    assert (allowed, matriz) == (set(), None)
    assert (
        resolver_versao_por_aluno(
            conn, aluno_id=data["loose"], atividade_versao_id=v_m1
        )["status"]
        == "not_found"
    )


def test_turma_bound_student_with_compatible_matrix_still_resolves_its_own():
    """TEST 5 — the Turma-bound path is unchanged."""
    from app.student_matrix import (
        get_allowed_activity_version_ids_for_student,
        get_effective_matrix_for_student,
    )
    from app.versioning.resolver import resolver_versao_por_aluno

    conn = _database()
    data = _seed(conn)
    _base, v_m1, _v_other = _seed_matrix_content(conn, data)

    matriz = get_effective_matrix_for_student(conn, data["student"])
    assert matriz is not None and matriz["id"] == data["m1"]

    allowed, _m = get_allowed_activity_version_ids_for_student(conn, data["student"])
    assert allowed == {v_m1}
    assert (
        resolver_versao_por_aluno(
            conn, aluno_id=data["student"], atividade_versao_id=v_m1
        )["status"]
        == "resolved"
    )


def test_turma_bound_student_with_null_matrix_never_adopts_the_turma_default():
    """TEST 6 — the widened resolver must not have opened a fallback."""
    from app.student_matrix import (
        get_allowed_activity_version_ids_for_student,
        get_effective_matrix_for_student,
    )
    from app.versioning.resolver import resolver_versao_por_aluno

    conn = _database()
    data = _seed(conn)
    _base, v_m1, _v_other = _seed_matrix_content(conn, data)
    # A Turma do aluno tem matriz padrao povoada; o aluno nao tem autoridade.
    assert conn.execute(
        "SELECT matriz_id FROM turmas WHERE id=?", (data["t1"],)
    ).fetchone()[0] == data["m1"]

    assert get_effective_matrix_for_student(conn, data["nullmatrix"]) is None
    allowed, matriz = get_allowed_activity_version_ids_for_student(
        conn, data["nullmatrix"]
    )
    assert (allowed, matriz) == (set(), None)
    assert (
        resolver_versao_por_aluno(
            conn, aluno_id=data["nullmatrix"], atividade_versao_id=v_m1
        )["status"]
        == "not_found"
    )


def test_corrupt_incompatible_turma_matrix_pairing_fails_closed():
    """TEST 7 — stale data fails closed instead of adopting the Turma default."""
    from app.student_matrix import (
        get_allowed_activity_version_ids_for_student,
        get_effective_matrix_for_student,
    )
    from app.versioning.resolver import resolver_versao_por_aluno

    conn = _database()
    data = _seed(conn)
    _base, v_m1, v_other = _seed_matrix_content(conn, data)
    # Estado que a validacao de escrita impede; simulado como corrupcao.
    conn.execute(
        "UPDATE alunos SET turma_id=?, matriz_id=? WHERE id=?",
        (data["t1"], data["other"], data["student"]),
    )

    assert get_effective_matrix_for_student(conn, data["student"]) is None
    allowed, matriz = get_allowed_activity_version_ids_for_student(conn, data["student"])
    assert (allowed, matriz) == (set(), None)
    # Nem a matriz incompativel do aluno nem o padrao da Turma sao adotados.
    for versao in (v_m1, v_other):
        assert (
            resolver_versao_por_aluno(
                conn, aluno_id=data["student"], atividade_versao_id=versao
            )["status"]
            == "not_found"
        )


# --------------------------------------------------------------------------
# Simultaneous Turma + Matrix edit reconciliation
# --------------------------------------------------------------------------


def test_explicit_matrix_is_validated_against_the_destination_turma():
    from app.student_matrix import StudentMatrixError, resolve_student_matrix_for_edit

    conn = _database()
    data = _seed(conn)

    # A Turma anterior (Curso 1) nao pode vetar a matriz explicita do Curso 2.
    resolvido = resolve_student_matrix_for_edit(
        conn,
        current_matriz_id=data["m1"],
        current_turma_id=data["t1"],
        turma_id=data["t4"],
        explicit_matriz_id=data["other"],
        matrix_explicitly_submitted=True,
    )
    assert resolvido == data["other"]

    # A Turma de destino permanece autoritativa contra escolhas incompativeis.
    with pytest.raises(StudentMatrixError):
        resolve_student_matrix_for_edit(
            conn,
            current_matriz_id=data["m1"],
            current_turma_id=data["t1"],
            turma_id=data["t4"],
            explicit_matriz_id=data["m2"],
            matrix_explicitly_submitted=True,
        )


def test_turma_edit_without_explicit_matrix_keeps_am1_semantics():
    from app.student_matrix import StudentMatrixError, resolve_student_matrix_for_edit

    conn = _database()
    data = _seed(conn)

    # Sem escolha explicita a autoridade existente e preservada.
    assert (
        resolve_student_matrix_for_edit(
            conn,
            current_matriz_id=data["m1"],
            current_turma_id=data["t1"],
            turma_id=data["t2"],
            explicit_matriz_id=None,
            matrix_explicitly_submitted=False,
        )
        == data["m1"]
    )

    # E a transferencia entre Cursos continua falhando fechada.
    with pytest.raises(StudentMatrixError):
        resolve_student_matrix_for_edit(
            conn,
            current_matriz_id=data["m1"],
            current_turma_id=data["t1"],
            turma_id=data["t4"],
            explicit_matriz_id=None,
            matrix_explicitly_submitted=False,
        )


def test_explicit_null_clears_matrix_even_while_changing_turma():
    from app.student_matrix import resolve_student_matrix_for_edit

    conn = _database()
    data = _seed(conn)

    assert (
        resolve_student_matrix_for_edit(
            conn,
            current_matriz_id=data["m1"],
            current_turma_id=data["t1"],
            turma_id=data["t2"],
            explicit_matriz_id=None,
            matrix_explicitly_submitted=True,
        )
        is None
    )


def test_assignable_matrices_are_scoped_by_turma_and_labelled_by_curso():
    from app.student_matrix import list_assignable_matrices_for_student

    conn = _database()
    data = _seed(conn)

    na_turma = list_assignable_matrices_for_student(conn, data["t1"])
    assert {row["id"] for row in na_turma} == {data["m1"], data["m2"]}
    assert data["other"] not in {row["id"] for row in na_turma}
    assert all(row["curso_nome"] for row in na_turma)

    sem_turma = list_assignable_matrices_for_student(conn, None)
    assert {row["id"] for row in sem_turma} == {data["m1"], data["m2"], data["other"]}
    assert all(row["curso_codigo"] for row in sem_turma)


# --------------------------------------------------------------------------
# 12. Admin route / UI surface
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """Admin client on a private prod-1 database.

    The shared session database is written to by earlier suites, so this module
    owns its own file: route behaviour must not depend on suite ordering.
    """
    app = main.app
    temp_root = tmp_path_factory.mktemp("am2_explicit_matrix")
    temp_database = temp_root / "am2.db"

    previous = {
        "env": os.environ.get("APP_DATABASE"),
        "main": main.DATABASE,
        "module": app_db_module.DATABASE,
        "config": app.config.get("DATABASE_PATH"),
        "testing": app.config.get("TESTING"),
        "uploads": app.config.get("UPLOAD_FOLDER"),
    }
    os.environ["APP_DATABASE"] = str(temp_database)
    main.DATABASE = str(temp_database)
    app_db_module.DATABASE = str(temp_database)
    app.config["DATABASE_PATH"] = str(temp_database)
    app.config["TESTING"] = True
    app.config["UPLOAD_FOLDER"] = str(temp_root / "uploads")

    try:
        with app.app_context():
            try:
                main.close_db_connection(None)
            except Exception:
                pass
            main.init_db()
        with app.test_client() as test_client:
            yield test_client
    finally:
        with app.app_context():
            try:
                main.close_db_connection(None)
            except Exception:
                pass
        if previous["env"] is None:
            os.environ.pop("APP_DATABASE", None)
        else:
            os.environ["APP_DATABASE"] = previous["env"]
        main.DATABASE = previous["main"]
        app_db_module.DATABASE = previous["module"]
        app.config["DATABASE_PATH"] = previous["config"]
        app.config["TESTING"] = previous["testing"]
        app.config["UPLOAD_FOLDER"] = previous["uploads"]


def _login_admin(test_client):
    with test_client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["user_type"] = "admin"
        sess["user_name"] = "Administrador"
        sess["access_level"] = "admin_total"
        sess["perfil"] = "Admin"


def _seed_route_fixture(suffix):
    """Seed two Cursos, three Matrizes, two Turmas and one Aluno in the test DB."""
    with main.app.app_context():
        conn = main.get_db_connection()
        ids = {}
        for chave, codigo in (("c1", f"AM2A{suffix}"), ("c2", f"AM2B{suffix}")):
            ids[chave] = conn.execute(
                "INSERT INTO cursos (nome, codigo, duracao_periodos, status) "
                "VALUES (?,?,?,?) RETURNING id",
                (f"Curso {codigo}", codigo, 8, "ativo"),
            ).fetchone()["id"]
        for chave, curso, nome in (
            ("m1", "c1", f"Matriz A1 {suffix}"),
            ("m2", "c1", f"Matriz A2 {suffix}"),
            ("other", "c2", f"Matriz B1 {suffix}"),
        ):
            ids[chave] = conn.execute(
                "INSERT INTO matrizes_atividades (curso_id, nome, status, "
                "horas_aac_obrigatorias, horas_extensao_obrigatorias) "
                "VALUES (?,?,?,?,?) RETURNING id",
                (ids[curso], nome, "vigente", 120, 60),
            ).fetchone()["id"]
        for chave, curso, matriz, codigo in (
            ("t1", "c1", "m1", f"AM2T1{suffix}"),
            ("t4", "c2", "other", f"AM2T4{suffix}"),
        ):
            ids[chave] = conn.execute(
                "INSERT INTO turmas (nome, status, numero, curso_id, matriz_id, "
                "ano_inicio, semestre_inicio, codigo) VALUES (?,?,?,?,?,?,?,?) RETURNING id",
                (codigo, "Ativa", 1, ids[curso], ids[matriz], 2026, 1, codigo),
            ).fetchone()["id"]
        email = f"am2.{suffix}@teste.local"
        ids["usuario"] = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo) VALUES (?,?,?,?) RETURNING id",
            (f"Aluno AM2 {suffix}", email, main.hash_password("aluno12345"), "aluno"),
        ).fetchone()["id"]
        ids["aluno"] = conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, matriz_id, status) "
            "VALUES (?,?,?,?,?,?,?) RETURNING id",
            (
                ids["usuario"],
                f"Aluno AM2 {suffix}",
                f"AM2-{suffix}",
                email,
                ids["t1"],
                ids["m1"],
                "Ativo",
            ),
        ).fetchone()["id"]
        conn.commit()
        return ids


def _aluno_state(usuario_id):
    with main.app.app_context():
        conn = main.get_db_connection()
        return conn.execute(
            "SELECT turma_id, matriz_id FROM alunos WHERE usuario_id=?", (usuario_id,)
        ).fetchone()


def _turma_default(turma_id):
    with main.app.app_context():
        conn = main.get_db_connection()
        return conn.execute(
            "SELECT matriz_id FROM turmas WHERE id=?", (turma_id,)
        ).fetchone()[0]


def _post_editar(test_client, ids, **overrides):
    payload = {
        "nome": "Aluno AM2",
        "email": f"am2.{ids['usuario']}@teste.local",
        "matricula": f"AM2-{ids['usuario']}",
        "turma_id": str(ids["t1"]),
        "status": "Ativo",
    }
    payload.update(overrides)
    return test_client.post(
        f"/admin/editar_aluno/{ids['usuario']}", data=payload, follow_redirects=True
    )


def test_edit_aluno_page_shows_current_academic_matrix_and_sem_matriz(client):
    _login_admin(client)
    ids = _seed_route_fixture("UI1")

    response = client.get(f"/admin/editar_aluno/{ids['usuario']}")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "Matriz acadêmica" in html
    assert "Matriz da turma" not in html
    assert "Sem matriz" in html
    assert 'name="matriz_id"' in html
    # A matriz vigente do aluno aparece marcada como selecionada.
    assert f'<option value="{ids["m1"]}" selected>' in html
    # A outra matriz do mesmo Curso e ofertada; a de outro Curso nao.
    assert f'value="{ids["m2"]}"' in html
    assert f'value="{ids["other"]}"' not in html


def test_edit_aluno_post_assigns_matrix_without_touching_turma_default(client):
    _login_admin(client)
    ids = _seed_route_fixture("P1")

    response = _post_editar(client, ids, matriz_id=str(ids["m2"]))
    assert response.status_code == 200

    estado = _aluno_state(ids["usuario"])
    assert estado["matriz_id"] == ids["m2"]
    assert estado["turma_id"] == ids["t1"]
    assert _turma_default(ids["t1"]) == ids["m1"]


def test_edit_aluno_post_rejects_cross_curso_matrix_and_preserves_previous(client):
    _login_admin(client)
    ids = _seed_route_fixture("P2")

    response = _post_editar(client, ids, nome="Nome Rejeitado", matriz_id=str(ids["other"]))
    assert response.status_code == 200
    # Erro controlado, e nao sucesso silencioso.
    html = response.get_data(as_text=True)
    assert "não pertence ao curso da turma do aluno" in html
    assert "Aluno atualizado com sucesso" not in html

    estado = _aluno_state(ids["usuario"])
    assert estado["matriz_id"] == ids["m1"]
    assert estado["turma_id"] == ids["t1"]
    # Rollback: nenhum outro dado do aluno foi parcialmente gravado.
    with main.app.app_context():
        conn = main.get_db_connection()
        nome_persistido = conn.execute(
            "SELECT nome FROM alunos WHERE usuario_id=?", (ids["usuario"],)
        ).fetchone()[0]
    assert nome_persistido != "Nome Rejeitado"


def test_edit_aluno_post_clears_matrix_when_sem_matriz_is_chosen(client):
    _login_admin(client)
    ids = _seed_route_fixture("P3")

    response = _post_editar(client, ids, matriz_id="")
    assert response.status_code == 200

    assert _aluno_state(ids["usuario"])["matriz_id"] is None


def test_edit_aluno_post_without_matrix_field_leaves_matrix_untouched(client):
    _login_admin(client)
    ids = _seed_route_fixture("P4")

    response = _post_editar(client, ids)
    assert response.status_code == 200

    assert _aluno_state(ids["usuario"])["matriz_id"] == ids["m1"]


def test_edit_aluno_post_supports_turma_less_student_receiving_a_matrix(client):
    _login_admin(client)
    ids = _seed_route_fixture("P5")
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "UPDATE alunos SET turma_id=NULL, matriz_id=NULL WHERE usuario_id=?",
            (ids["usuario"],),
        )
        conn.commit()

    page = client.get(f"/admin/editar_aluno/{ids['usuario']}")
    html = page.get_data(as_text=True)
    # Sem Turma, matrizes de qualquer Curso sao ofertadas com identificacao do Curso.
    assert f'value="{ids["other"]}"' in html
    assert f'value="{ids["m1"]}"' in html

    response = _post_editar(client, ids, turma_id="", matriz_id=str(ids["other"]))
    assert response.status_code == 200

    estado = _aluno_state(ids["usuario"])
    assert estado["turma_id"] is None
    assert estado["matriz_id"] == ids["other"]
