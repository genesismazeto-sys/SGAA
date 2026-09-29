"""Import rows that cannot be a student reject the whole file.

Two holes let junk into the student table: an e-mail that is not an e-mail
(the address later receives the first-access link), and a header row repeated
in the middle of a file (typical of concatenated exports), which became a
student called "Aluno". Both now reject the file at the true source row, in
the server parser and in the browser preview alike, and nothing is written.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

import main
from app.services.mail_service import is_valid_email
from app.student_import import StudentImportError, parse_student_import
from app.user_accounts import create_usuario_pending
from tests.canonical_matrix_test_support import login_admin
from tests.test_student_import_optional_header import _browser_preview, _file_bytes
from tests.versioned_test_support import isolated_versioned_app_env


FORMATS = ("csv", "xls", "xlsx")
HEADER = ["Aluno", "E-mail", "Matricula"]
VALID = [
    ["Primeira Pessoa", "primeira@example.com", "001234"],
    ["Segunda Pessoa", "segunda@example.com", "ACE-0002"],
]
REPEATED_HEADER_ERROR = (
    "cabeçalho repetido no meio do arquivo; o cabeçalho só é aceito na primeira linha."
)


def _write(tmp_path: Path, extension: str, rows, name="alunos") -> Path:
    path = tmp_path / f"{name}.{extension}"
    path.write_bytes(_file_bytes(extension, rows))
    return path


def _server(path: Path) -> dict:
    try:
        rows = parse_student_import(path)
    except StudentImportError as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "rows": [{"aluno": r.aluno, "email": r.email, "matricula": r.matricula} for r in rows],
    }


def _cases(with_header: bool):
    """(label, rows, expected error) with the true 1-based source row."""
    top = [HEADER] if with_header else []
    offset = len(top)
    return [
        ("valid", [*top, *VALID], None),
        (
            "bad-email-first",
            [*top, ["Primeira Pessoa", "primeira.example.com", "001234"], VALID[1]],
            f"Linha {offset + 1}: e-mail inválido.",
        ),
        (
            "bad-email-last",
            [*top, *VALID, ["Terceira Pessoa", "terceira@example", "T-3"]],
            f"Linha {offset + 3}: e-mail inválido.",
        ),
        (
            "repeated-header",
            [*top, VALID[0], HEADER, VALID[1]],
            f"Linha {offset + 2}: {REPEATED_HEADER_ERROR}",
        ),
        (
            "repeated-header-after-blank-rows",
            [*top, *VALID, [], [], ["Nome", "Email", "Matrícula"]],
            f"Linha {offset + 5}: {REPEATED_HEADER_ERROR}",
        ),
        (
            "repeated-obsolete-header",
            [*top, *VALID, ["Matricula", "Aluno", "E-mail"]],
            f"Linha {offset + 3}: {REPEATED_HEADER_ERROR}",
        ),
    ]


@pytest.mark.parametrize("extension", FORMATS)
@pytest.mark.parametrize("with_header", (True, False), ids=("with-header", "without-header"))
def test_server_and_preview_agree_on_every_row_rule(tmp_path, extension, with_header):
    paths, expected = [], []
    for label, rows, error in _cases(with_header):
        paths.append(_write(tmp_path, extension, rows, label))
        if error is None:
            expected.append(
                {
                    "ok": True,
                    "rows": [
                        {"aluno": a, "email": e, "matricula": m} for a, e, m in VALID
                    ],
                }
            )
        else:
            expected.append({"ok": False, "error": error})

    assert [_server(path) for path in paths] == expected
    assert _browser_preview(paths) == expected


def test_first_row_header_is_still_optional_and_never_counted_as_repeated(tmp_path):
    for extension in FORMATS:
        for rows in ([HEADER, *VALID], VALID, [[], [], HEADER, *VALID]):
            result = _server(_write(tmp_path, extension, rows))
            assert result["ok"], (extension, rows, result)
            assert [r["matricula"] for r in result["rows"]] == ["001234", "ACE-0002"]


EMAIL_CORPUS = (
    "a@b.co",
    "first.last+tag@sub.example.com.br",
    "UPPER@EXAMPLE.COM",
    "x@example.invalid",
    "a@b.c",
    "ümlaut@exämple.de",
    "a" * 240 + "@example.com",
    "plainaddress",
    "@no-local.com",
    "no-at.example.com",
    "a@b",
    "a@@b.com",
    "a@b..com",
    "a@.b.com",
    "a b@c.com",
    "a@b.com.",
    "E-mail",
    "#N/A",
    "a" * 243 + "@example.com",
    "a@b c.com",
)


def test_import_uses_the_shared_sgaa_email_rule_on_both_sides(tmp_path):
    """No import-only regex: the verdict is exactly ``is_valid_email``'s."""
    assert any(is_valid_email(e) for e in EMAIL_CORPUS)
    assert not all(is_valid_email(e) for e in EMAIL_CORPUS)
    paths, expected = [], []
    for index, email in enumerate(EMAIL_CORPUS):
        path = tmp_path / f"email-{index}.csv"
        with path.open("w", encoding="utf-8", newline="") as target:
            csv.writer(target).writerow(["Pessoa", email, f"M-{index}"])
        paths.append(path)
        if is_valid_email(email):
            expected.append(
                {"ok": True, "rows": [{"aluno": "Pessoa", "email": email, "matricula": f"M-{index}"}]}
            )
        else:
            expected.append({"ok": False, "error": "Linha 1: e-mail inválido."})

    assert [_server(path) for path in paths] == expected
    assert _browser_preview(paths) == expected


# --- nothing is written: modal import and Editar Turma with a file ---------

TURMA_ID = 1  # seeded PPA-T10


def _seed_existing_student():
    with main.app.app_context():
        conn = main.get_db_connection()
        usuario_id = create_usuario_pending(
            conn, "Aluna Existente", "existente@example.com", "aluno"
        ).lastrowid
        conn.execute(
            "INSERT INTO alunos (usuario_id,nome,email,matricula,turma_id,status)"
            " VALUES (?,?,?,?,?,'Ativo')",
            (usuario_id, "Aluna Existente", "existente@example.com", "EX-0001", TURMA_ID),
        )
        conn.commit()


def _database_state():
    with main.app.app_context():
        conn = main.get_db_connection()
        return {
            table: [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY 1")]
            for table in ("alunos", "usuarios", "usuario_credenciais", "senha_tokens", "turmas")
        }


def _rejected_rows(extension):
    # Row 1 would update an existing student's e-mail, row 2 would create one;
    # row 3 is the defect. Nothing of rows 1-2 may survive.
    return [
        HEADER,
        ["Aluna Existente", "existente.nova@example.com", "EX-0001"],
        ["Nova Pessoa", "nova@example.com", "NEW-0001"],
        ["Terceira Pessoa", "terceira@@example.com", "T-0003"],
    ], "Linha 4: e-mail inválido."


def _repeated_header_rows(extension):
    return [
        ["Aluna Existente", "existente.nova@example.com", "EX-0001"],
        ["Nova Pessoa", "nova@example.com", "NEW-0001"],
        HEADER,
        ["Quarta Pessoa", "quarta@example.com", "Q-0004"],
    ], f"Linha 3: {REPEATED_HEADER_ERROR}"


@pytest.mark.parametrize("extension", FORMATS)
@pytest.mark.parametrize("builder", (_rejected_rows, _repeated_header_rows), ids=("bad-email", "mid-header"))
def test_modal_import_rejects_the_file_and_writes_nothing(tmp_path, extension, builder):
    with isolated_versioned_app_env(tmp_path, f"row-modal-{extension}.db") as env:
        _seed_existing_student()
        login_admin(env["client"])
        rows, error = builder(extension)
        before = _database_state()

        response = env["client"].post(
            "/admin/turmas/importar",
            data={
                "turma_id": str(TURMA_ID),
                "csv_arquivo": (io.BytesIO(_file_bytes(extension, rows)), f"alunos.{extension}"),
            },
        )

        assert response.status_code == 302
        with env["client"].session_transaction() as session:
            flashes = session.get("_flashes", [])
        assert any(category == "error" and error in message for category, message in flashes)
        assert _database_state() == before


@pytest.mark.parametrize("extension", FORMATS)
@pytest.mark.parametrize("builder", (_rejected_rows, _repeated_header_rows), ids=("bad-email", "mid-header"))
def test_turma_form_with_file_rolls_back_the_turma_update_too(tmp_path, extension, builder):
    with isolated_versioned_app_env(tmp_path, f"row-form-{extension}.db") as env:
        _seed_existing_student()
        login_admin(env["client"])
        rows, error = builder(extension)
        before = _database_state()
        with main.app.app_context():
            curso_id = main.get_db_connection().execute(
                "SELECT curso_id FROM turmas WHERE id=?", (TURMA_ID,)
            ).fetchone()["curso_id"]

        response = env["client"].post(
            f"/admin/editar_turma/{TURMA_ID}",
            data={
                "curso_id": str(curso_id),
                "numero_turma": "10",
                "ano_inicio": "2025",
                "semestre_inicio": "2",
                "turno": "Noite",  # would change if anything were committed
                "status": "Ativa",
                "matriz_id": "",
                "aluno_nome[]": "Aluna Existente",
                "aluno_email[]": "existente@example.com",
                "aluno_matricula[]": "EX-0001",
                "aluno_situacao[]": "ATIVO",
                "aluno_importado[]": "0",
                "student_import_file": (io.BytesIO(_file_bytes(extension, rows)), f"alunos.{extension}"),
            },
        )

        assert response.status_code == 200
        assert f"Erro ao atualizar turma: {error}" in response.get_data(as_text=True)
        assert _database_state() == before


def test_valid_file_still_imports_and_keeps_matricula_identity(tmp_path):
    with isolated_versioned_app_env(tmp_path, "row-valid.db") as env:
        _seed_existing_student()
        login_admin(env["client"])
        rows = [
            ["Aluna Existente", "existente.nova@example.com", "EX-0001"],
            ["Nova Pessoa", "nova@example.com", "001234"],
        ]
        response = env["client"].post(
            "/admin/turmas/importar",
            data={
                "turma_id": str(TURMA_ID),
                "csv_arquivo": (io.BytesIO(_file_bytes("csv", rows)), "alunos.csv"),
            },
        )

        assert response.status_code == 302
        with main.app.app_context():
            found = {
                row["matricula"]: row["email"]
                for row in main.get_db_connection().execute(
                    "SELECT matricula, email FROM alunos WHERE turma_id=?", (TURMA_ID,)
                )
            }
        # E-mail update keyed on matrícula; leading zeros kept.
        assert found["EX-0001"] == "existente.nova@example.com"
        assert found["001234"] == "nova@example.com"
