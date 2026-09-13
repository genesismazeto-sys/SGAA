"""Turma default reaches students only when an admin explicitly asks.

Students enrolled before their Turma had a default Matrix end up with
``alunos.matriz_id IS NULL`` and Nova Requisicao offers them nothing. Saving the
Turma must NOT repair that on its own: the Turma Matrix is a suggestion, and an
admin who chose "Sem matriz" for a student has to keep that choice through any
number of saves. The repair is its own explicit admin action.
"""
import sqlite3

import pytest

import main
from app.prod1_schema import bootstrap_prod1_schema
from app.student_matrix import StudentMatrixError
from tests.canonical_matrix_test_support import login_admin
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
    default_matrix = conn.execute(
        "INSERT INTO matrizes_atividades(curso_id,nome) VALUES(?,'Default')", (curso,)
    ).lastrowid
    other_matrix = conn.execute(
        "INSERT INTO matrizes_atividades(curso_id,nome) VALUES(?,'Other')", (curso,)
    ).lastrowid
    turma = conn.execute(
        "INSERT INTO turmas(nome,numero,curso_id,matriz_id,ano_inicio,semestre_inicio,codigo) "
        "VALUES('T1',1,?,?,2026,1,'T1')",
        (curso, default_matrix),
    ).lastrowid
    turma_sem_default = conn.execute(
        "INSERT INTO turmas(nome,numero,curso_id,matriz_id,ano_inicio,semestre_inicio,codigo) "
        "VALUES('T2',2,?,NULL,2026,1,'T2')",
        (curso,),
    ).lastrowid
    vizinha = conn.execute(
        "INSERT INTO turmas(nome,numero,curso_id,matriz_id,ano_inicio,semestre_inicio,codigo) "
        "VALUES('T3',3,?,?,2026,1,'T3')",
        (curso, default_matrix),
    ).lastrowid
    return locals()


def _aluno(conn, turma_id, matricula, matriz_id=None):
    return conn.execute(
        "INSERT INTO alunos(nome,matricula,turma_id,matriz_id) VALUES(?,?,?,?)",
        (f"Aluno {matricula}", matricula, turma_id, matriz_id),
    ).lastrowid


def _matriz_of(conn, aluno_id):
    return conn.execute(
        "SELECT matriz_id FROM alunos WHERE id=?", (aluno_id,)
    ).fetchone()["matriz_id"]


# ---------------------------------------------------------------------------
# Canonical semantics: an ordinary save never initializes a Matrix
# ---------------------------------------------------------------------------


def test_same_turma_save_never_initializes_a_matrix_less_student():
    """The rejected shortcut: a save that does not move the student must not write."""
    from app.student_matrix import assign_student_to_turma

    conn = _database()
    data = _seed(conn)
    aluno = _aluno(conn, data["turma"], "A1")

    assign_student_to_turma(conn, aluno, data["turma"])

    assert _matriz_of(conn, aluno) is None


def test_turma_entry_still_initializes_from_the_compatible_default():
    """Initialization on real Turma entry is untouched by that rule."""
    from app.student_matrix import assign_student_to_turma

    conn = _database()
    data = _seed(conn)
    aluno = _aluno(conn, None, "A2")

    assign_student_to_turma(conn, aluno, data["turma"])

    assert _matriz_of(conn, aluno) == data["default_matrix"]


def test_effective_matrix_never_falls_back_to_the_turma_default():
    """The read path stays authority-only."""
    from app.student_matrix import get_effective_matrix_for_student

    conn = _database()
    data = _seed(conn)
    aluno = _aluno(conn, data["turma"], "A3")

    assert get_effective_matrix_for_student(conn, aluno) is None


# ---------------------------------------------------------------------------
# The explicit admin action
# ---------------------------------------------------------------------------


def test_explicit_action_initializes_only_matrix_less_students_of_that_turma():
    from app.student_matrix import apply_turma_default_to_students_without_matrix

    conn = _database()
    data = _seed(conn)
    sem_matriz = _aluno(conn, data["turma"], "A4")
    com_matriz = _aluno(conn, data["turma"], "A5", data["other_matrix"])
    outra_turma = _aluno(conn, data["vizinha"], "A6")

    initialized = apply_turma_default_to_students_without_matrix(conn, data["turma"])

    assert initialized == 1
    assert _matriz_of(conn, sem_matriz) == data["default_matrix"]
    # An authority already held is never replaced...
    assert _matriz_of(conn, com_matriz) == data["other_matrix"]
    # ...and no other Turma is reached.
    assert _matriz_of(conn, outra_turma) is None


def test_explicit_action_does_not_move_students_between_turmas():
    from app.student_matrix import apply_turma_default_to_students_without_matrix

    conn = _database()
    data = _seed(conn)
    aluno = _aluno(conn, data["turma"], "A7")

    apply_turma_default_to_students_without_matrix(conn, data["turma"])

    row = conn.execute(
        "SELECT turma_id FROM alunos WHERE id=?", (aluno,)
    ).fetchone()
    assert row["turma_id"] == data["turma"]
    assert conn.execute(
        "SELECT matriz_id FROM turmas WHERE id=?", (data["turma"],)
    ).fetchone()["matriz_id"] == data["default_matrix"]


def test_explicit_action_fails_closed_without_a_turma_default():
    from app.student_matrix import apply_turma_default_to_students_without_matrix

    conn = _database()
    data = _seed(conn)
    aluno = _aluno(conn, data["turma_sem_default"], "A8")

    with pytest.raises(StudentMatrixError):
        apply_turma_default_to_students_without_matrix(conn, data["turma_sem_default"])
    assert _matriz_of(conn, aluno) is None


def test_explicit_action_fails_closed_on_a_cross_course_turma_default():
    from app.student_matrix import apply_turma_default_to_students_without_matrix

    conn = _database()
    data = _seed(conn)
    estranha = conn.execute(
        "INSERT INTO matrizes_atividades(curso_id,nome) VALUES(?,'Estranha')",
        (data["outro_curso"],),
    ).lastrowid
    conn.execute(
        "UPDATE turmas SET matriz_id=? WHERE id=?", (estranha, data["turma"])
    )
    aluno = _aluno(conn, data["turma"], "A9")

    with pytest.raises(StudentMatrixError):
        apply_turma_default_to_students_without_matrix(conn, data["turma"])
    assert _matriz_of(conn, aluno) is None


def test_explicit_action_fails_closed_on_an_unknown_turma():
    from app.student_matrix import apply_turma_default_to_students_without_matrix

    conn = _database()
    _seed(conn)

    with pytest.raises(StudentMatrixError):
        apply_turma_default_to_students_without_matrix(conn, 999999)


# ---------------------------------------------------------------------------
# MANDATORY: an explicit "Sem matriz" survives an ordinary Save Turma
# ---------------------------------------------------------------------------


def _turma_payload(*, number, course_id, matrix_marker, student):
    return {
        "curso_id": str(course_id),
        "numero_turma": str(number),
        "ano_inicio": "2026",
        "semestre_inicio": "1",
        "ano_fim": "2029",
        "semestre_fim": "2",
        "turno": "Manhã",
        "status": "Ativa",
        "matriz_id": str(matrix_marker),
        "aluno_nome[]": student["nome"],
        "aluno_email[]": student["email"],
        "aluno_matricula[]": student["matricula"],
        "aluno_situacao[]": "ATIVO",
        "aluno_importado[]": "0",
    }


def test_explicit_sem_matriz_survives_save_turma_and_only_the_action_restores_it(tmp_path):
    """The mandatory regression for the rejected auto-initialization."""
    with isolated_versioned_app_env(tmp_path, "am3-explicit-clear.db") as env:
        login_admin(env["client"])
        student = {
            "nome": "Aluno Base Versionado",
            "email": "aluno.base.versionado@example.com",
            "matricula": "PPA.TESTE.0001",
        }
        with main.app.app_context():
            conn = main.get_db_connection()
            course_id = conn.execute(
                "SELECT curso_id FROM turmas WHERE id=2"
            ).fetchone()[0]
            aluno_id = conn.execute(
                "SELECT id FROM alunos WHERE matricula=?", (student["matricula"],)
            ).fetchone()["id"]
            # 2. the admin explicitly chooses "Sem matriz" for this student.
            conn.execute("UPDATE alunos SET matriz_id=NULL WHERE id=?", (aluno_id,))
            conn.execute("UPDATE turmas SET matriz_id=1 WHERE id=2")
            conn.commit()

        # 3. an ordinary Save Turma, with the Turma default set to Matrix 1.
        saved = env["client"].post(
            "/admin/editar_turma/2",
            data=_turma_payload(
                number=11, course_id=course_id, matrix_marker=1, student=student
            ),
            follow_redirects=False,
        )
        assert saved.status_code == 302

        with main.app.app_context():
            conn = main.get_db_connection()
            assert conn.execute(
                "SELECT matriz_id FROM turmas WHERE id=2"
            ).fetchone()[0] == 1
            # 4. the explicit clear survived the save.
            assert conn.execute(
                "SELECT matriz_id FROM alunos WHERE id=?", (aluno_id,)
            ).fetchone()[0] is None

        # Only the explicit action assigns Matrix 1 again.
        applied = env["client"].post(
            "/admin/turma/2/aplicar-matriz-alunos", follow_redirects=False
        )
        assert applied.status_code == 302

        with main.app.app_context():
            assert main.get_db_connection().execute(
                "SELECT matriz_id FROM alunos WHERE id=?", (aluno_id,)
            ).fetchone()[0] == 1


def test_explicit_action_requires_admin_and_rejects_get(tmp_path):
    with isolated_versioned_app_env(tmp_path, "am3-route-guard.db") as env:
        # Anonymous POST must not reach the mutation.
        anonymous = env["client"].post(
            "/admin/turma/2/aplicar-matriz-alunos", follow_redirects=False
        )
        assert anonymous.status_code in (302, 401, 403)

        login_admin(env["client"])
        assert env["client"].get("/admin/turma/2/aplicar-matriz-alunos").status_code == 405


def test_explicit_action_on_unknown_turma_redirects_without_writing(tmp_path):
    with isolated_versioned_app_env(tmp_path, "am3-unknown-turma.db") as env:
        login_admin(env["client"])
        with main.app.app_context():
            before = main.get_db_connection().execute(
                "SELECT COUNT(*) FROM alunos WHERE matriz_id IS NULL"
            ).fetchone()[0]

        response = env["client"].post(
            "/admin/turma/999999/aplicar-matriz-alunos", follow_redirects=False
        )
        assert response.status_code == 302

        with main.app.app_context():
            assert main.get_db_connection().execute(
                "SELECT COUNT(*) FROM alunos WHERE matriz_id IS NULL"
            ).fetchone()[0] == before


# ---------------------------------------------------------------------------
# UI contract: the action is visibly distinct from "Salvar Turma"
# ---------------------------------------------------------------------------


def _detalhes_template() -> str:
    from pathlib import Path

    return Path("templates/admin_detalhes_turma.html").read_text(encoding="utf-8")


def test_action_is_its_own_post_form_on_the_turma_detail_page():
    source = _detalhes_template()

    assert "admin_turma_aplicar_matriz_alunos" in source
    assert "Aplicar matriz aos alunos sem matriz" in source
    assert 'name="csrf_token"' in source
    # Its own <form method="post">, never a control inside another form.
    assert 'method="post"' in source
    assert "data-aplicar-matriz-form" in source


def test_action_confirms_before_writing_and_is_not_wired_into_save_turma():
    from pathlib import Path

    source = _detalhes_template()
    assert "confirm(" in source, "the action must confirm before it writes"

    # The frozen Salvar Turma surfaces must not gain this action.
    for frozen in ("templates/admin_editar_turma.html", "templates/admin_adicionar_turma.html"):
        frozen_source = Path(frozen).read_text(encoding="utf-8")
        assert "aplicar_matriz_alunos" not in frozen_source
        assert "Aplicar matriz aos alunos sem matriz" not in frozen_source


def test_detail_view_exposes_the_matrix_less_student_count(tmp_path):
    with isolated_versioned_app_env(tmp_path, "am3-detail-count.db") as env:
        login_admin(env["client"])
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute("UPDATE alunos SET matriz_id=NULL WHERE turma_id=2")
            conn.execute("UPDATE turmas SET matriz_id=1 WHERE id=2")
            conn.commit()
            expected = conn.execute(
                "SELECT COUNT(*) FROM alunos WHERE turma_id=2 AND matriz_id IS NULL"
            ).fetchone()[0]

        html = env["client"].get("/admin/turma/2").get_data(as_text=True)
        assert expected >= 1
        assert "Aplicar matriz aos alunos sem matriz" in html
        assert f"({expected})" in html
