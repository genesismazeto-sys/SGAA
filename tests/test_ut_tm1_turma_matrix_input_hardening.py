"""Hardening of the submitted Turma Matrix input (UT-TM1).

Add and Edit Turma read the optional Matrix choice with
``request.form.get("matriz_id", type=int)``, which yields ``None`` both for the
blank "Sem matriz" choice and for any non-empty malformed value. Both readings
then reached the same early branch of ``_resolve_turma_matriz_id``, so a
handcrafted authenticated POST could clear a Turma's academic Matrix -- or
create a Matrix-free Turma -- while looking like an ordinary submission.

This module pins the backend as authoritative over that parse for both Turma
routes: syntax is delegated to the shared submitted-Matrix parser, existence and
Curso compatibility stay with the Turma validation path, and the blank/absent
readings keep the semantics the product already had.
"""
import inspect
import re

import pytest
from flask import request

import main
from app.student_matrix import StudentMatrixError, parse_submitted_matriz_id
from app.views.admin import alunos_turmas_cursos as turmas_view
from tests.canonical_matrix_test_support import login_admin
from tests.versioned_test_support import isolated_versioned_app_env


# Mesmo conjunto usado em UT-AM2H: nenhum destes valores nomeia uma matriz.
MALFORMED = ("abc", "1a", "a1", "1.5", "1,5", "null", "None", "NaN", "-", "1e3", "1_0", "+5")

STUDENT_PARSER_REJECTION = "matriz acadêmica selecionada é inválida"
TURMA_SYNTAX_REJECTION = "matriz selecionada é inválida"
NONEXISTENT_REJECTION = "matriz selecionada não existe"
COMPATIBILITY_REJECTION = "não pertence ao curso informado"

# Turma 1 do dataset de referencia: PPA-T10, numero 10, matriz 1, sem alunos.
TURMA_ID = 1
TURMA_MATRIZ_ID = 1
TURMA_NUMERO = 10


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _course_id():
    with main.app.app_context():
        return main.get_db_connection().execute(
            "SELECT curso_id FROM turmas WHERE id=?", (TURMA_ID,)
        ).fetchone()[0]


def _turma_state(turma_id):
    with main.app.app_context():
        return main.get_db_connection().execute(
            "SELECT nome,turno,status,numero,curso_id,matriz_id,ano_inicio,"
            "semestre_inicio,ano_fim,semestre_fim,codigo FROM turmas WHERE id=?",
            (turma_id,),
        ).fetchone()


def _turma_by_codigo(codigo):
    with main.app.app_context():
        return main.get_db_connection().execute(
            "SELECT id, matriz_id FROM turmas WHERE codigo=?", (codigo,)
        ).fetchone()


def _aluno_by_email(email):
    with main.app.app_context():
        return main.get_db_connection().execute(
            "SELECT id FROM alunos WHERE email=?", (email,)
        ).fetchone()


def _take_flashes(client):
    """Read and consume the pending flashes, so later asserts stay isolated."""
    with client.session_transaction() as session_state:
        return list(session_state.pop("_flashes", []))


def _payload(*, number, course_id, matrix_marker=None, student=None, **overrides):
    """A full Turma form submission; ``matrix_marker=None`` omits the field."""
    payload = {
        "curso_id": str(course_id),
        "numero_turma": str(number),
        "ano_inicio": "2025",
        "semestre_inicio": "2",
        "ano_fim": "2028",
        "semestre_fim": "1",
        "turno": "Manhã",
        "status": "Ativa",
    }
    if matrix_marker is not None:
        payload["matriz_id"] = str(matrix_marker)
    if student:
        payload.update(
            {
                "aluno_nome[]": student["nome"],
                "aluno_email[]": student["email"],
                "aluno_matricula[]": student["matricula"],
                "aluno_situacao[]": "ATIVO",
                "aluno_importado[]": "0",
            }
        )
    payload.update(overrides)
    return payload


def _post_edit(client, course_id, **kwargs):
    return client.post(
        f"/admin/editar_turma/{TURMA_ID}",
        data=_payload(number=TURMA_NUMERO, course_id=course_id, **kwargs),
        follow_redirects=False,
    )


def _post_add(client, course_id, *, number, **kwargs):
    return client.post(
        "/admin/adicionar_turma",
        data=_payload(number=number, course_id=course_id, **kwargs),
        follow_redirects=False,
    )


def _other_course_matrix():
    """A Matrix that exists but belongs to a different Curso."""
    with main.app.app_context():
        conn = main.get_db_connection()
        other_course = conn.execute(
            "INSERT INTO cursos(nome,codigo,duracao_periodos,status) "
            "VALUES('Outro','OTH',8,'ativo') RETURNING id"
        ).fetchone()["id"]
        other_matrix = conn.execute(
            "INSERT INTO matrizes_atividades(curso_id,nome,status) "
            "VALUES(?,'Matriz OTH','vigente') RETURNING id",
            (other_course,),
        ).fetchone()["id"]
        conn.commit()
        return other_matrix


# ---------------------------------------------------------------------------
# Mutation probe: the pre-fix read collapsed garbage into the explicit clear
# ---------------------------------------------------------------------------


def test_probe_pre_fix_type_int_read_would_have_collapsed_malformed_turma_input():
    """``type=int`` cannot tell "abc" from "" at either Turma route.

    This reproduces the retired expression against real request contexts for
    both routes. It is harmless only because neither route still uses it.
    """
    for path in ("/admin/adicionar_turma", f"/admin/editar_turma/{TURMA_ID}"):
        for raw in ("abc", ""):
            with main.app.test_request_context(path, method="POST", data={"matriz_id": raw}):
                # Campo presente nos dois casos...
                assert "matriz_id" in request.form
                # ... e a leitura antiga devolve None nos dois, ou seja, "sem matriz".
                assert request.form.get("matriz_id", type=int) is None

    # A leitura endurecida separa os dois casos.
    assert parse_submitted_matriz_id("") is None
    with pytest.raises(StudentMatrixError):
        parse_submitted_matriz_id("abc")


def test_turma_view_module_no_longer_uses_the_coercive_read_for_matriz_id():
    """Static guard against reintroducing the collapsing read in this module."""
    source = inspect.getsource(turmas_view)
    # Nenhuma leitura de matriz_id neste modulo pode voltar a coagir com type=int.
    assert not re.search(r'request\.form\.get\(\s*"matriz_id"[^)]*type=int', source)
    # E os dois call sites de Turma passam o valor bruto para o resolvedor.
    assert source.count(
        '_resolve_turma_matriz_id(conn, curso_id, request.form.get("matriz_id"))'
    ) == 2


# ---------------------------------------------------------------------------
# 5. Parser reuse: syntax is shared, compatibility is not duplicated
# ---------------------------------------------------------------------------


def test_turma_path_reuses_the_shared_submitted_matrix_parser():
    """No divergent second parser: the Turma routes import the landed one."""
    import app.student_matrix as student_matrix

    assert turmas_view.parse_submitted_matriz_id is student_matrix.parse_submitted_matriz_id
    # O parser compartilhado preserva a mensagem da superficie Aluno.
    with pytest.raises(StudentMatrixError) as excinfo:
        parse_submitted_matriz_id("abc")
    assert STUDENT_PARSER_REJECTION in str(excinfo.value)


def test_resolver_delegates_syntax_and_keeps_compatibility(tmp_path):
    """The parser owns syntax only; existence/Curso stay with the resolver."""
    with isolated_versioned_app_env(tmp_path, "tm1-resolver.db"):
        with main.app.app_context():
            conn = main.get_db_connection()
            course_id = conn.execute(
                "SELECT curso_id FROM turmas WHERE id=?", (TURMA_ID,)
            ).fetchone()[0]

            # Sintaxe invalida: recusada sem nem consultar o banco.
            resolved, error = turmas_view._resolve_turma_matriz_id(conn, course_id, "abc")
            assert resolved is None
            assert TURMA_SYNTAX_REJECTION in error

            # Em branco continua sendo a escolha explicita "Sem matriz".
            assert turmas_view._resolve_turma_matriz_id(conn, course_id, "") == (None, None)
            assert turmas_view._resolve_turma_matriz_id(conn, course_id, None) == (None, None)

            # Sintaxe valida: o resolvedor separa existencia e compatibilidade.
            assert turmas_view._resolve_turma_matriz_id(conn, course_id, "1") == (1, None)
            resolved, error = turmas_view._resolve_turma_matriz_id(conn, course_id, "99999")
            assert resolved is None
            assert NONEXISTENT_REJECTION in error


# ---------------------------------------------------------------------------
# 1-3. Edit Turma: malformed is rejected and never read as NULL
# ---------------------------------------------------------------------------


def test_edit_turma_rejects_malformed_matrix_and_preserves_the_previous_one(tmp_path):
    with isolated_versioned_app_env(tmp_path, "tm1-edit-malformed.db") as env:
        login_admin(env["client"])
        course_id = _course_id()
        before = _turma_state(TURMA_ID)
        assert before["matriz_id"] == TURMA_MATRIZ_ID

        response = _post_edit(env["client"], course_id, matrix_marker="abc")

        assert response.status_code == 302
        # Recusa controlada, e nao um sucesso silencioso.
        categories, messages = zip(*_take_flashes(env["client"]))
        assert "error" in categories
        assert any(TURMA_SYNTAX_REJECTION in message for message in messages)
        assert not any("atualizada com sucesso" in message for message in messages)

        after = _turma_state(TURMA_ID)
        # A matriz anterior sobreviveu e nao virou NULL.
        assert after["matriz_id"] == TURMA_MATRIZ_ID
        assert after["matriz_id"] is not None


@pytest.mark.parametrize("raw", MALFORMED)
def test_edit_turma_never_clears_the_matrix_on_any_malformed_value(tmp_path, raw):
    with isolated_versioned_app_env(tmp_path, "tm1-edit-never-clears.db") as env:
        login_admin(env["client"])
        course_id = _course_id()

        _post_edit(env["client"], course_id, matrix_marker=raw)

        # Nunca interpretado como "Sem matriz".
        assert _turma_state(TURMA_ID)["matriz_id"] == TURMA_MATRIZ_ID


def test_malformed_matrix_rolls_back_concurrent_edit_turma_changes(tmp_path):
    """Every field of the same rejected submission is discarded together."""
    with isolated_versioned_app_env(tmp_path, "tm1-edit-rollback.db") as env:
        login_admin(env["client"])
        course_id = _course_id()
        before = _turma_state(TURMA_ID)
        student = {
            "nome": "Aluno Que Nao Deve Existir",
            "email": "rejeitado.tm1@teste.local",
            "matricula": "TM1-REJEITADA",
        }

        response = _post_edit(
            env["client"],
            course_id,
            matrix_marker="abc",
            student=student,
            turno="Noite",
            status="Encerrada",
            ano_fim="2031",
            semestre_fim="2",
        )
        assert response.status_code == 302

        after = _turma_state(TURMA_ID)
        # Nenhuma das edicoes simultaneas foi parcialmente gravada.
        assert tuple(after) == tuple(before)
        assert after["turno"] != "Noite"
        assert after["status"] != "Encerrada"
        assert after["ano_fim"] != 2031
        # E o aluno enviado na mesma submissao tambem nao foi criado.
        assert _aluno_by_email(student["email"]) is None


# ---------------------------------------------------------------------------
# 5-7. The legitimate Edit Turma readings still behave as the product specified
# ---------------------------------------------------------------------------


def test_edit_turma_blank_matrix_still_clears_to_null(tmp_path):
    with isolated_versioned_app_env(tmp_path, "tm1-edit-blank.db") as env:
        login_admin(env["client"])
        course_id = _course_id()
        assert _turma_state(TURMA_ID)["matriz_id"] == TURMA_MATRIZ_ID

        response = _post_edit(env["client"], course_id, matrix_marker="")

        assert response.status_code == 302
        assert _turma_state(TURMA_ID)["matriz_id"] is None


def test_edit_turma_whitespace_only_matrix_is_still_the_explicit_clear(tmp_path):
    """A field with only spaces is an empty field, not garbage."""
    with isolated_versioned_app_env(tmp_path, "tm1-edit-whitespace.db") as env:
        login_admin(env["client"])
        course_id = _course_id()

        response = _post_edit(env["client"], course_id, matrix_marker="   ")

        assert response.status_code == 302
        assert _turma_state(TURMA_ID)["matriz_id"] is None


def test_edit_turma_valid_matrix_still_assigns(tmp_path):
    with isolated_versioned_app_env(tmp_path, "tm1-edit-valid.db") as env:
        login_admin(env["client"])
        course_id = _course_id()

        response = _post_edit(env["client"], course_id, matrix_marker=2)

        assert response.status_code == 302
        messages = [message for _, message in _take_flashes(env["client"])]
        assert any("atualizada com sucesso" in message for message in messages)
        assert _turma_state(TURMA_ID)["matriz_id"] == 2


def test_edit_turma_cross_course_matrix_remains_rejected(tmp_path):
    with isolated_versioned_app_env(tmp_path, "tm1-edit-cross-course.db") as env:
        login_admin(env["client"])
        course_id = _course_id()
        other_matrix = _other_course_matrix()

        response = _post_edit(env["client"], course_id, matrix_marker=other_matrix)

        assert response.status_code == 302
        messages = [message for _, message in _take_flashes(env["client"])]
        assert any(COMPATIBILITY_REJECTION in message for message in messages)
        # Recusa de compatibilidade tambem preserva a matriz anterior.
        assert _turma_state(TURMA_ID)["matriz_id"] == TURMA_MATRIZ_ID


# ---------------------------------------------------------------------------
# 8-9. Add Turma
# ---------------------------------------------------------------------------


def test_add_turma_with_malformed_matrix_creates_no_turma(tmp_path):
    with isolated_versioned_app_env(tmp_path, "tm1-add-malformed.db") as env:
        login_admin(env["client"])
        course_id = _course_id()

        response = _post_add(env["client"], course_id, number=90, matrix_marker="abc")

        assert response.status_code == 302
        messages = [message for _, message in _take_flashes(env["client"])]
        assert any(TURMA_SYNTAX_REJECTION in message for message in messages)
        assert not any("criada com sucesso" in message for message in messages)
        # Nenhuma turma nasceu, nem com matriz nem sem matriz.
        assert _turma_by_codigo("PPA-T90") is None


@pytest.mark.parametrize("raw", MALFORMED)
def test_add_turma_never_creates_a_matrix_free_turma_from_malformed_input(tmp_path, raw):
    with isolated_versioned_app_env(tmp_path, "tm1-add-never-creates.db") as env:
        login_admin(env["client"])
        course_id = _course_id()

        _post_add(env["client"], course_id, number=90, matrix_marker=raw)

        assert _turma_by_codigo("PPA-T90") is None


def test_add_turma_with_malformed_matrix_creates_no_student_either(tmp_path):
    """The rejection rolls back the whole Add Turma submission."""
    with isolated_versioned_app_env(tmp_path, "tm1-add-rollback.db") as env:
        login_admin(env["client"])
        course_id = _course_id()
        student = {
            "nome": "Aluno Turma Rejeitada",
            "email": "add.rejeitado.tm1@teste.local",
            "matricula": "TM1-ADD-REJEITADA",
        }

        response = _post_add(
            env["client"], course_id, number=92, matrix_marker="abc", student=student
        )

        assert response.status_code == 302
        assert _turma_by_codigo("PPA-T92") is None
        assert _aluno_by_email(student["email"]) is None


def test_add_turma_with_blank_matrix_still_creates_a_matrix_free_turma(tmp_path):
    with isolated_versioned_app_env(tmp_path, "tm1-add-blank.db") as env:
        login_admin(env["client"])
        course_id = _course_id()

        response = _post_add(env["client"], course_id, number=90, matrix_marker="")

        assert response.status_code == 302
        messages = [message for _, message in _take_flashes(env["client"])]
        assert any("criada com sucesso" in message for message in messages)
        created = _turma_by_codigo("PPA-T90")
        assert created is not None
        assert created["matriz_id"] is None


def test_add_turma_with_valid_matrix_still_assigns(tmp_path):
    with isolated_versioned_app_env(tmp_path, "tm1-add-valid.db") as env:
        login_admin(env["client"])
        course_id = _course_id()

        response = _post_add(env["client"], course_id, number=93, matrix_marker=1)

        assert response.status_code == 302
        created = _turma_by_codigo("PPA-T93")
        assert created is not None
        assert created["matriz_id"] == 1


def test_add_turma_cross_course_matrix_remains_rejected(tmp_path):
    with isolated_versioned_app_env(tmp_path, "tm1-add-cross-course.db") as env:
        login_admin(env["client"])
        course_id = _course_id()
        other_matrix = _other_course_matrix()

        response = _post_add(env["client"], course_id, number=94, matrix_marker=other_matrix)

        assert response.status_code == 302
        messages = [message for _, message in _take_flashes(env["client"])]
        assert any(COMPATIBILITY_REJECTION in message for message in messages)
        assert _turma_by_codigo("PPA-T94") is None


# ---------------------------------------------------------------------------
# 10. Absent/blank semantics stay on the existing product contract
# ---------------------------------------------------------------------------


def test_absent_matrix_field_keeps_the_existing_add_turma_contract(tmp_path):
    """Add Turma has no previous value: absent means the Matrix-free default.

    This is the reading ``test_admin_turmas_matriz`` already pins, and UT-TM1
    deliberately leaves it alone -- only the malformed case changed.
    """
    with isolated_versioned_app_env(tmp_path, "tm1-add-absent.db") as env:
        login_admin(env["client"])
        course_id = _course_id()

        response = _post_add(env["client"], course_id, number=95)

        assert response.status_code == 302
        created = _turma_by_codigo("PPA-T95")
        assert created is not None
        assert created["matriz_id"] is None


def test_absent_matrix_field_keeps_the_existing_edit_turma_contract(tmp_path):
    """Edit Turma is a full-form replace, so an absent field reads as blank.

    Unchanged by UT-TM1: the defect was malformed input being read as this
    branch, not the branch itself.
    """
    with isolated_versioned_app_env(tmp_path, "tm1-edit-absent.db") as env:
        login_admin(env["client"])
        course_id = _course_id()
        assert _turma_state(TURMA_ID)["matriz_id"] == TURMA_MATRIZ_ID

        response = _post_edit(env["client"], course_id)

        assert response.status_code == 302
        assert _turma_state(TURMA_ID)["matriz_id"] is None


# ---------------------------------------------------------------------------
# Tightened edge: a non-empty value that names no Matrix is not a clear
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw", ("0", "-1", "00"))
def test_non_empty_out_of_range_matrix_is_rejected_instead_of_clearing(tmp_path, raw):
    """``"0"`` parses as an integer, so compatibility -- not the clear -- decides."""
    with isolated_versioned_app_env(tmp_path, "tm1-edit-zero.db") as env:
        login_admin(env["client"])
        course_id = _course_id()

        response = _post_edit(env["client"], course_id, matrix_marker=raw)

        assert response.status_code == 302
        messages = [message for _, message in _take_flashes(env["client"])]
        assert any(NONEXISTENT_REJECTION in message for message in messages)
        assert _turma_state(TURMA_ID)["matriz_id"] == TURMA_MATRIZ_ID
