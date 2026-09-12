"""UT-TM2: precise Turma Matrix errors without changing parser ownership."""

import pytest

import main
from app.student_matrix import StudentMatrixError, parse_submitted_matriz_id
from app.views.admin import alunos_turmas_cursos as turmas_view
from tests.canonical_matrix_test_support import login_admin
from tests.versioned_test_support import isolated_versioned_app_env
from utils import messages


INVALID = "A matriz selecionada é inválida."
NONEXISTENT = "A matriz selecionada não existe."
INCOMPATIBLE = "A matriz selecionada não pertence ao curso informado."
STUDENT_INVALID = "A matriz acadêmica selecionada é inválida."

TURMA_ID = 1
TURMA_NUMBER = 10
TURMA_MATRIX_ID = 1


def _course_id():
    with main.app.app_context():
        return main.get_db_connection().execute(
            "SELECT curso_id FROM turmas WHERE id=?", (TURMA_ID,)
        ).fetchone()["curso_id"]


def _turma_state(turma_id=TURMA_ID):
    with main.app.app_context():
        return main.get_db_connection().execute(
            "SELECT nome,turno,status,numero,curso_id,matriz_id,ano_inicio,"
            "semestre_inicio,ano_fim,semestre_fim,codigo FROM turmas WHERE id=?",
            (turma_id,),
        ).fetchone()


def _turma_by_code(code):
    with main.app.app_context():
        return main.get_db_connection().execute(
            "SELECT id, matriz_id FROM turmas WHERE codigo=?", (code,)
        ).fetchone()


def _student_by_email(email):
    with main.app.app_context():
        return main.get_db_connection().execute(
            "SELECT id FROM alunos WHERE email=?", (email,)
        ).fetchone()


def _other_course_matrix():
    with main.app.app_context():
        conn = main.get_db_connection()
        other_course_id = conn.execute(
            "INSERT INTO cursos(nome,codigo,duracao_periodos,status) "
            "VALUES('Outro TM2','TM2',8,'ativo') RETURNING id"
        ).fetchone()["id"]
        matrix_id = conn.execute(
            "INSERT INTO matrizes_atividades(curso_id,nome,status) "
            "VALUES(?,'Matriz TM2','vigente') RETURNING id",
            (other_course_id,),
        ).fetchone()["id"]
        conn.commit()
        return matrix_id


def _payload(*, number, course_id, matrix_marker, student_email=None, **overrides):
    payload = {
        "curso_id": str(course_id),
        "matriz_id": str(matrix_marker),
        "numero_turma": str(number),
        "ano_inicio": "2025",
        "semestre_inicio": "2",
        "ano_fim": "2028",
        "semestre_fim": "1",
        "turno": "Manhã",
        "status": "Ativa",
    }
    if student_email:
        payload.update(
            {
                "aluno_nome[]": "Aluno Rejeitado TM2",
                "aluno_email[]": student_email,
                "aluno_matricula[]": "TM2-REJEITADA",
                "aluno_situacao[]": "ATIVO",
                "aluno_importado[]": "0",
            }
        )
    payload.update(overrides)
    return payload


def _flashes(client):
    with client.session_transaction() as session_state:
        return list(session_state.pop("_flashes", []))


def _marker_for_case(case):
    if case == "malformed":
        return "abc"
    if case == "nonexistent":
        return "99999"
    return _other_course_matrix()


@pytest.mark.parametrize("raw", ("abc", "1_0", "+5", "1.5"))
def test_resolver_translates_shared_parser_syntax_error_at_turma_boundary(tmp_path, raw):
    with isolated_versioned_app_env(tmp_path, "tm2-resolver-invalid.db"):
        course_id = _course_id()
        assert turmas_view._resolve_turma_matriz_id(None, course_id, raw) == (
            None,
            INVALID,
        )
        with pytest.raises(StudentMatrixError) as excinfo:
            parse_submitted_matriz_id(raw)
        assert str(excinfo.value) == STUDENT_INVALID


@pytest.mark.parametrize("raw", ("0", "99999", "-1"))
def test_resolver_distinguishes_nonexistent_integer_ids(tmp_path, raw):
    with isolated_versioned_app_env(tmp_path, "tm2-resolver-nonexistent.db"):
        with main.app.app_context():
            conn = main.get_db_connection()
            assert turmas_view._resolve_turma_matriz_id(conn, _course_id(), raw) == (
                None,
                NONEXISTENT,
            )


def test_resolver_distinguishes_blank_compatible_and_cross_course(tmp_path):
    with isolated_versioned_app_env(tmp_path, "tm2-resolver-states.db"):
        course_id = _course_id()
        other_matrix = _other_course_matrix()
        with main.app.app_context():
            conn = main.get_db_connection()
            assert turmas_view._resolve_turma_matriz_id(conn, course_id, "") == (
                None,
                None,
            )
            assert turmas_view._resolve_turma_matriz_id(conn, course_id, "   ") == (
                None,
                None,
            )
            assert turmas_view._resolve_turma_matriz_id(conn, course_id, "1") == (
                TURMA_MATRIX_ID,
                None,
            )
            assert turmas_view._resolve_turma_matriz_id(
                conn, course_id, str(other_matrix)
            ) == (None, INCOMPATIBLE)


@pytest.mark.parametrize(
    ("case", "expected"),
    (("malformed", INVALID), ("nonexistent", NONEXISTENT), ("incompatible", INCOMPATIBLE)),
)
def test_add_rejection_is_precise_and_atomic(tmp_path, case, expected):
    with isolated_versioned_app_env(tmp_path, f"tm2-add-{case}.db") as env:
        login_admin(env["client"])
        course_id = _course_id()
        marker = _marker_for_case(case)
        student_email = f"tm2.add.{case}@example.com"

        response = env["client"].post(
            "/admin/adicionar_turma",
            data=_payload(
                number=90,
                course_id=course_id,
                matrix_marker=marker,
                student_email=student_email,
            ),
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert _flashes(env["client"]) == [("error", expected)]
        assert _turma_by_code("PPA-T90") is None
        assert _student_by_email(student_email) is None


@pytest.mark.parametrize(
    ("case", "expected"),
    (("malformed", INVALID), ("nonexistent", NONEXISTENT), ("incompatible", INCOMPATIBLE)),
)
def test_edit_rejection_is_precise_and_atomic(tmp_path, case, expected):
    with isolated_versioned_app_env(tmp_path, f"tm2-edit-{case}.db") as env:
        login_admin(env["client"])
        course_id = _course_id()
        marker = _marker_for_case(case)
        student_email = f"tm2.edit.{case}@example.com"
        before = tuple(_turma_state())

        response = env["client"].post(
            f"/admin/editar_turma/{TURMA_ID}",
            data=_payload(
                number=TURMA_NUMBER,
                course_id=course_id,
                matrix_marker=marker,
                student_email=student_email,
                turno="Noite",
                status="Encerrada",
                ano_fim="2031",
                semestre_fim="2",
            ),
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert _flashes(env["client"]) == [("error", expected)]
        assert tuple(_turma_state()) == before
        assert _student_by_email(student_email) is None


@pytest.mark.parametrize(
    ("action", "marker", "expected_matrix"),
    (("blank", "   ", None), ("compatible", "2", 2)),
)
def test_add_and_edit_keep_blank_and_compatible_behavior(tmp_path, action, marker, expected_matrix):
    with isolated_versioned_app_env(tmp_path, f"tm2-accepted-{action}.db") as env:
        login_admin(env["client"])
        course_id = _course_id()

        add_response = env["client"].post(
            "/admin/adicionar_turma",
            data=_payload(number=90, course_id=course_id, matrix_marker=marker),
            follow_redirects=False,
        )
        assert add_response.status_code == 302
        assert _turma_by_code("PPA-T90")["matriz_id"] == expected_matrix
        _flashes(env["client"])

        edit_response = env["client"].post(
            f"/admin/editar_turma/{TURMA_ID}",
            data=_payload(
                number=TURMA_NUMBER, course_id=course_id, matrix_marker=marker
            ),
            follow_redirects=False,
        )
        assert edit_response.status_code == 302
        assert _turma_state()["matriz_id"] == expected_matrix


def test_exact_turma_return_messages_are_owned_by_the_catalog():
    messages._message_catalog.cache_clear()
    catalog = messages._message_catalog()
    entries = {entry["default_text"]: entry for entry in catalog.values()}

    expected_lines = {INVALID: 179, NONEXISTENT: 186, INCOMPATIBLE: 188}
    for text, source_line in expected_lines.items():
        assert text in entries
        assert entries[text]["kinds"] == ("return-message",)
        assert entries[text]["usages"] == [
            {
                "source_path": "app/views/admin/alunos_turmas_cursos.py",
                "source_line": source_line,
                "kind": "return-message",
                "source_function": "_resolve_turma_matriz_id",
                "source_route": "",
                "source_key": "",
            }
        ]
