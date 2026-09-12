"""UT-MX3: close Matrix submission, rollback, and catalog ownership debt."""
from __future__ import annotations

import ast
import hashlib
import inspect
import sys

import pytest

import main
from app.student_matrix import StudentMatrixError, parse_submitted_matriz_id
from app.views.admin import alunos_turmas_cursos as turmas_view
from tests.canonical_matrix_test_support import login_admin
from tests.versioned_test_support import isolated_versioned_app_env
from utils import messages


INVALID_STUDENT = "A matriz acadêmica selecionada é inválida."
INVALID_TURMA = "A matriz selecionada é inválida."
NONEXISTENT_TURMA = "A matriz selecionada não existe."
INCOMPATIBLE_TURMA = "A matriz selecionada não pertence ao curso informado."

PARENT_CATALOG_COUNT = 548
CANDIDATE_CATALOG_COUNT = 554
PARENT_CATALOG_KEYS_SHA256 = (
    "f5dc176c0e574f969f566007ad05a867dc4362b4d51787a70844775136d44265"
)
NEW_STUDENT_MATRIX_KEYS = {
    "msg_0b2541cb6783e532": INVALID_STUDENT,
    "msg_6c846efc640f4a94": "A matriz acadêmica selecionada não existe.",
    "msg_98c12a0febff263e": "A turma de destino não existe.",
    "msg_a5d6d3c6eef9c604": (
        "A matriz acadêmica não pertence ao curso da turma do aluno."
    ),
    "msg_aabf50debc0f1bbe": (
        "A matriz padrão da turma não pertence ao curso informado."
    ),
    "msg_e9accecdaba2fbf3": (
        "A matriz acadêmica do aluno não pertence ao curso da turma de destino."
    ),
}
ALL_STUDENT_MATRIX_DEFAULTS = set(NEW_STUDENT_MATRIX_KEYS.values()) | {
    "Aluno não encontrado."
}


def _oversized_decimal() -> str:
    getter = getattr(sys, "get_int_max_str_digits", None)
    assert getter is not None, "UT-MX3 requires the Python 3.11+ digit-limit API"
    active_limit = getter()
    assert active_limit > 0, "the interpreter's int digit safety limit must stay enabled"
    return "9" * (active_limit + 512)


def _flash_messages(client) -> list[tuple[str, str]]:
    with client.session_transaction() as session:
        return list(session.pop("_flashes", []))


def _turma_payload(row, matriz_id: str, *, numero=None) -> dict[str, str]:
    def value(name: str) -> str:
        item = row[name]
        return "" if item is None else str(item)

    return {
        "curso_id": value("curso_id"),
        "matriz_id": matriz_id,
        "numero_turma": str(numero if numero is not None else row["numero"]),
        "ano_inicio": value("ano_inicio"),
        "semestre_inicio": value("semestre_inicio"),
        "ano_fim": value("ano_fim"),
        "semestre_fim": value("semestre_fim"),
        "turno": value("turno"),
        "status": value("status"),
    }


def _first_turma():
    with main.app.app_context():
        return main.get_db_connection().execute(
            "SELECT * FROM turmas WHERE matriz_id IS NOT NULL ORDER BY id LIMIT 1"
        ).fetchone()


def _turma_state(turma_id: int):
    with main.app.app_context():
        return main.get_db_connection().execute(
            "SELECT nome,turno,status,numero,curso_id,matriz_id,ano_inicio,"
            "semestre_inicio,ano_fim,semestre_fim,codigo FROM turmas WHERE id=?",
            (turma_id,),
        ).fetchone()


def _student_record():
    with main.app.app_context():
        return main.get_db_connection().execute(
            """SELECT u.id AS usuario_id,u.nome AS usuario_nome,
                      u.email AS usuario_email,a.nome AS aluno_nome,
                      a.email AS aluno_email,a.matricula,a.turma_id,
                      a.matriz_id,a.status
                 FROM alunos a
                 JOIN usuarios u ON u.id=a.usuario_id
                WHERE a.turma_id IS NOT NULL AND a.matriz_id IS NOT NULL
             ORDER BY a.id LIMIT 1"""
        ).fetchone()


def _student_state(usuario_id: int):
    with main.app.app_context():
        return main.get_db_connection().execute(
            """SELECT u.nome,u.email,a.nome,a.email,a.matricula,a.turma_id,
                      a.matriz_id,a.status
                 FROM alunos a
                 JOIN usuarios u ON u.id=a.usuario_id
                WHERE u.id=?""",
            (usuario_id,),
        ).fetchone()


def test_pre_fix_int_probe_and_parser_raise_controlled_student_matrix_error():
    raw = _oversized_decimal()
    with pytest.raises(ValueError):
        int(raw)

    with pytest.raises(StudentMatrixError, match="selecionada é inválida") as excinfo:
        parse_submitted_matriz_id(raw)

    assert type(excinfo.value) is StudentMatrixError
    assert isinstance(excinfo.value.__cause__, ValueError)
    assert str(excinfo.value) == INVALID_STUDENT
    assert parse_submitted_matriz_id("7") == 7


def test_student_edit_rejects_oversized_id_atomically_without_generic_error(tmp_path):
    with isolated_versioned_app_env(tmp_path, "mx3-student.db") as env:
        login_admin(env["client"])
        student = _student_record()
        before = tuple(_student_state(student["usuario_id"]))
        response = env["client"].post(
            f"/admin/editar_aluno/{student['usuario_id']}",
            data={
                "nome": "Nome Que Não Deve Persistir",
                "email": "mx3-rejected@example.com",
                "matricula": "MX3-REJECTED",
                "turma_id": str(student["turma_id"]),
                "matriz_id": _oversized_decimal(),
                "status": "Inativo",
            },
            follow_redirects=True,
        )

        html = response.get_data(as_text=True)
        assert response.status_code == 200
        assert INVALID_STUDENT in html
        assert "Aluno atualizado com sucesso" not in html
        assert "Erro inesperado ao atualizar aluno" not in html
        assert "Exceeds the limit" not in html
        assert tuple(_student_state(student["usuario_id"])) == before


def test_add_turma_rejects_oversized_id_without_partial_persistence(tmp_path):
    with isolated_versioned_app_env(tmp_path, "mx3-add-turma.db") as env:
        login_admin(env["client"])
        turma = _first_turma()
        with main.app.app_context():
            before_count = main.get_db_connection().execute(
                "SELECT COUNT(*) FROM turmas"
            ).fetchone()[0]

        response = env["client"].post(
            "/admin/adicionar_turma",
            data=_turma_payload(turma, _oversized_decimal(), numero=909),
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert _flash_messages(env["client"]) == [("error", INVALID_TURMA)]
        with main.app.app_context():
            after_count = main.get_db_connection().execute(
                "SELECT COUNT(*) FROM turmas"
            ).fetchone()[0]
        assert after_count == before_count


def test_edit_turma_rejects_oversized_id_without_partial_persistence(tmp_path):
    with isolated_versioned_app_env(tmp_path, "mx3-edit-turma.db") as env:
        login_admin(env["client"])
        turma = _first_turma()
        before = tuple(_turma_state(turma["id"]))
        payload = _turma_payload(turma, _oversized_decimal())
        payload.update(turno="Noite", status="Encerrada")

        response = env["client"].post(
            f"/admin/editar_turma/{turma['id']}",
            data=payload,
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert _flash_messages(env["client"]) == [("error", INVALID_TURMA)]
        assert tuple(_turma_state(turma["id"])) == before


def test_turma_rejection_is_reached_outside_a_transaction(tmp_path, monkeypatch):
    observed = []
    original = turmas_view._resolve_turma_matriz_id

    def recording_resolver(conn, curso_id, posted_matriz_id):
        result = original(conn, curso_id, posted_matriz_id)
        if result[1]:
            observed.append(conn.in_transaction)
        return result

    monkeypatch.setattr(turmas_view, "_resolve_turma_matriz_id", recording_resolver)
    with isolated_versioned_app_env(tmp_path, "mx3-no-transaction.db") as env:
        login_admin(env["client"])
        turma = _first_turma()
        env["client"].post(
            "/admin/adicionar_turma",
            data=_turma_payload(turma, _oversized_decimal(), numero=910),
        )
        env["client"].post(
            f"/admin/editar_turma/{turma['id']}",
            data=_turma_payload(turma, _oversized_decimal()),
        )

    assert observed == [False, False]


def test_turma_matrix_rejection_branches_are_exactly_no_write():
    tree = ast.parse(inspect.getsource(turmas_view))
    for function_name in ("admin_adicionar_turma", "admin_editar_turma"):
        function = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == function_name
        )
        rejection = next(
            node
            for node in ast.walk(function)
            if isinstance(node, ast.If)
            and isinstance(node.test, ast.Name)
            and node.test.id == "matriz_error"
        )
        transaction_calls = {
            node.func.attr
            for node in ast.walk(rejection)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"execute", "executemany", "commit", "rollback"}
        }
        assert transaction_calls == set(), function_name


def test_turma_resolver_keeps_exact_validation_messages_and_valid_ids(tmp_path):
    with isolated_versioned_app_env(tmp_path, "mx3-resolver.db"):
        turma = _first_turma()
        with main.app.app_context():
            conn = main.get_db_connection()
            other_course = conn.execute(
                "INSERT INTO cursos(nome,codigo,duracao_periodos,status) "
                "VALUES('MX3 Other','MX3O',8,'ativo') RETURNING id"
            ).fetchone()["id"]
            other_matrix = conn.execute(
                "INSERT INTO matrizes_atividades(curso_id,nome,status) "
                "VALUES(?,'MX3 Other Matrix','vigente') RETURNING id",
                (other_course,),
            ).fetchone()["id"]
            conn.commit()

            assert turmas_view._resolve_turma_matriz_id(
                conn, turma["curso_id"], str(turma["matriz_id"])
            ) == (turma["matriz_id"], None)
            assert turmas_view._resolve_turma_matriz_id(
                conn, turma["curso_id"], "abc"
            ) == (None, INVALID_TURMA)
            assert turmas_view._resolve_turma_matriz_id(
                conn, turma["curso_id"], _oversized_decimal()
            ) == (None, INVALID_TURMA)
            assert turmas_view._resolve_turma_matriz_id(
                conn, turma["curso_id"], "999999999"
            ) == (None, NONEXISTENT_TURMA)
            assert turmas_view._resolve_turma_matriz_id(
                conn, turma["curso_id"], str(other_matrix)
            ) == (None, INCOMPATIBLE_TURMA)


def test_student_matrix_error_catalog_delta_is_exact_and_bounded():
    assert messages.BACKEND_VALUE_ERROR_TYPES == {
        "ValueError",
        "RuntimeError",
        "ArquivoError",
        "StudentMatrixError",
    }
    backend_files = [
        path.relative_to(messages.PROJECT_ROOT).as_posix()
        for path in messages._iter_backend_files()
    ]
    assert backend_files.count("app/student_matrix.py") == 1

    messages._message_catalog.cache_clear()
    catalog = messages._message_catalog()
    assert len(catalog) == CANDIDATE_CATALOG_COUNT
    assert {
        key: catalog[key]["default_text"] for key in NEW_STUDENT_MATRIX_KEYS
    } == NEW_STUDENT_MATRIX_KEYS

    parent_keys = set(catalog) - set(NEW_STUDENT_MATRIX_KEYS)
    assert len(parent_keys) == PARENT_CATALOG_COUNT
    digest = hashlib.sha256("\n".join(sorted(parent_keys)).encode()).hexdigest()
    assert digest == PARENT_CATALOG_KEYS_SHA256

    owned = {
        entry["default_text"]
        for entry in catalog.values()
        if any(
            usage["source_path"] == "app/student_matrix.py"
            for usage in entry["usages"]
        )
    }
    assert owned == ALL_STUDENT_MATRIX_DEFAULTS
    aluno_usages = {
        usage["source_function"]
        for usage in catalog[messages.message_key_for_default("Aluno não encontrado.")][
            "usages"
        ]
        if usage["source_path"] == "app/student_matrix.py"
    }
    assert aluno_usages == {"assign_student_to_turma", "assign_student_matrix"}
