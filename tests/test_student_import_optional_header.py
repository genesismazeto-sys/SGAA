from __future__ import annotations

import io
import json
import shutil
import subprocess
from pathlib import Path

import openpyxl
import pytest
import xlwt
from flask import session

from app import db as app_db
from app.student_import import StudentImportError, parse_student_import
from app.views.admin import alunos_turmas_cursos as target
import main


FORMATS = ("csv", "xls", "xlsx")


def _file_bytes(extension: str, rows: list[list[object]]) -> bytes:
    if extension == "csv":
        text = "\n".join(",".join(str(value) for value in row) for row in rows)
        return f"{text}\n".encode("utf-8")
    payload = io.BytesIO()
    if extension == "xlsx":
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        for row in rows:
            sheet.append(row)
        workbook.save(payload)
        workbook.close()
    else:
        workbook = xlwt.Workbook()
        sheet = workbook.add_sheet("Alunos")
        for row_index, row in enumerate(rows):
            for column_index, value in enumerate(row):
                sheet.write(row_index, column_index, value)
        workbook.save(payload)
    return payload.getvalue()


def _write_file(tmp_path: Path, extension: str, rows: list[list[object]]) -> Path:
    path = tmp_path / f"students.{extension}"
    path.write_bytes(_file_bytes(extension, rows))
    return path


def _seed_turma(code: str) -> int:
    with main.app.app_context():
        conn = app_db.get_db_connection()
        curso_id = conn.execute(
            "INSERT INTO cursos (nome,codigo,duracao_periodos,status) VALUES (?,?,8,'ativo') RETURNING id",
            (f"Curso {code}", f"C-{code}"),
        ).fetchone()["id"]
        turma_id = conn.execute(
            """
            INSERT INTO turmas (nome,codigo,numero,curso_id,status,ano_inicio,semestre_inicio)
            VALUES (?,?,?,?, 'Ativa', 2026, 1) RETURNING id
            """,
            (f"Turma {code}", f"T-{code}", 1, curso_id),
        ).fetchone()["id"]
        conn.commit()
        return int(turma_id)


def _post_import(turma_id: int, payload: bytes, filename: str):
    with main.app.test_request_context(
        "/admin/turmas/importar",
        method="POST",
        data={"turma_id": str(turma_id), "csv_arquivo": (io.BytesIO(payload), filename)},
    ):
        session["user_id"] = 999_999
        session["user_type"] = "admin"
        return target.admin_turmas_importar()


@pytest.mark.parametrize("extension", FORMATS)
@pytest.mark.parametrize("with_header", (True, False), ids=("with-header", "without-header"))
def test_all_formats_accept_optional_header_without_losing_first_student(
    tmp_path, extension, with_header
):
    suffix = f"{extension}-{int(with_header)}"
    data_rows = [
        [f"First {suffix}", f"first.{suffix}@example.com", f"MAT-{suffix}-1"],
        [f"Second {suffix}", f"second.{suffix}@example.com", f"MAT-{suffix}-2"],
    ]
    rows = [["Aluno", "E-mail", "Matricula"], *data_rows] if with_header else data_rows
    path = _write_file(tmp_path, extension, rows)

    parsed = parse_student_import(path)

    assert [(row.aluno, row.email, row.matricula) for row in parsed] == [
        tuple(row) for row in data_rows
    ]
    assert [row.source_row for row in parsed] == ([2, 3] if with_header else [1, 2])


@pytest.mark.parametrize("extension", FORMATS)
@pytest.mark.parametrize("with_header", (True, False), ids=("with-header", "without-header"))
def test_all_formats_import_optional_header_rows_as_active(extension, with_header):
    suffix = f"status-{extension}-{int(with_header)}"
    matricula = f"ACTIVE-{extension}-{int(with_header)}"
    data_rows = [[f"Active {suffix}", f"active.{suffix}@example.com", matricula]]
    rows = [["Aluno", "E-mail", "Matricula"], *data_rows] if with_header else data_rows
    turma_id = _seed_turma(suffix)

    response = _post_import(turma_id, _file_bytes(extension, rows), f"students.{extension}")

    assert response.status_code == 302
    with main.app.app_context():
        imported = app_db.get_db_connection().execute(
            "SELECT nome,email,matricula,status FROM alunos WHERE turma_id=?",
            (turma_id,),
        ).fetchall()
    assert [dict(row) for row in imported] == [
        {
            "nome": data_rows[0][0],
            "email": data_rows[0][1],
            "matricula": matricula,
            "status": "Ativo",
        }
    ]


@pytest.mark.parametrize("extension", FORMATS)
def test_existing_header_aliases_remain_supported(tmp_path, extension):
    path = _write_file(
        tmp_path,
        extension,
        [["Nome", "Email", "Matrícula"], ["Alias Student", "alias@example.com", "ALIAS-1"]],
    )

    rows = parse_student_import(path)

    assert [(row.aluno, row.email, row.matricula, row.source_row) for row in rows] == [
        ("Alias Student", "alias@example.com", "ALIAS-1", 2)
    ]


def test_partial_header_match_is_first_student_data_row(tmp_path):
    path = _write_file(
        tmp_path,
        "csv",
        [
            ["Aluno", "real.student@example.com", "REAL-1"],
            ["Second", "second@example.com", "REAL-2"],
        ],
    )

    rows = parse_student_import(path)

    assert [(row.aluno, row.source_row) for row in rows] == [("Aluno", 1), ("Second", 2)]


@pytest.mark.parametrize(
    ("with_header", "expected_row"),
    ((False, 1), (True, 2)),
    ids=("without-header", "with-header"),
)
def test_required_value_error_uses_actual_source_row(tmp_path, with_header, expected_row):
    data = [["Missing Email", "", "MISSING-1"]]
    rows = [["Aluno", "E-mail", "Matricula"], *data] if with_header else data
    path = _write_file(tmp_path, "csv", rows)

    with pytest.raises(StudentImportError, match=rf"Linha {expected_row}:"):
        parse_student_import(path)


# A first row carrying two or more column names is a header, never a student:
# read as data it would shift every column (the published obsolete-order guard).
HEADER_LIKE_FIRST_ROWS = {
    "obsolete-order": ["Matricula", "Aluno", "E-mail"],
    "near-miss-name": ["Nome completo", "E-mail", "Matrícula"],
    "legacy-situacao": ["Aluno", "E-mail", "Matricula", "Situação"],
}
HEADER_ORDER_ERROR = (
    "Linha 2: o cabeçalho deve seguir exatamente esta ordem: Aluno, E-mail, Matricula."
)


def _header_like_rows(header: list[str]) -> list[list[object]]:
    return [[], header, ["SWAP-1", "Swapped Student", "swapped@example.com"]]


@pytest.mark.parametrize("extension", FORMATS)
@pytest.mark.parametrize(
    "header", HEADER_LIKE_FIRST_ROWS.values(), ids=HEADER_LIKE_FIRST_ROWS.keys()
)
def test_header_like_first_row_is_rejected_instead_of_shifting_columns(
    tmp_path, extension, header
):
    path = _write_file(tmp_path, extension, _header_like_rows(header))

    with pytest.raises(StudentImportError) as excinfo:
        parse_student_import(path)

    assert str(excinfo.value) == HEADER_ORDER_ERROR


@pytest.mark.parametrize("extension", FORMATS)
def test_obsolete_order_file_writes_nothing_in_any_format(extension):
    turma_id = _seed_turma(f"obsolete-{extension}")
    payload = _file_bytes(extension, _header_like_rows(HEADER_LIKE_FIRST_ROWS["obsolete-order"]))

    response = _post_import(turma_id, payload, f"obsolete.{extension}")

    assert response.status_code == 302
    with main.app.app_context():
        conn = app_db.get_db_connection()
        assert conn.execute(
            "SELECT COUNT(*) FROM alunos WHERE turma_id=?", (turma_id,)
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM alunos WHERE matricula IN ('SWAP-1','swapped@example.com')"
        ).fetchone()[0] == 0


def _browser_preview(paths: list[Path]) -> list[dict]:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for browser-preview parity coverage")
    project_root = Path(__file__).resolve().parents[1]
    script = r"""
const fs = require('fs');
global.window = { XLSX: require(process.argv[1]) };
eval(fs.readFileSync(process.argv[2], 'utf8'));
(async () => {
  const results = [];
  for (const filePath of process.argv.slice(3)) {
    const bytes = fs.readFileSync(filePath);
    const buffer = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
    try {
      const rows = await window.StudentImportPreview.read({
        name: filePath,
        arrayBuffer: async () => buffer,
      });
      results.push({ ok: true, rows });
    } catch (error) {
      results.push({ ok: false, error: String(error.message || error) });
    }
  }
  process.stdout.write(JSON.stringify(results));
})().catch((error) => { console.error(error); process.exit(1); });
"""
    result = subprocess.run(
        [
            node,
            "-e",
            script,
            str(project_root / "static" / "vendor" / "xlsx.full.min.js"),
            str(project_root / "static" / "js" / "student-import-preview.js"),
            *(str(path) for path in paths),
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_browser_preview_matches_optional_header_contract_for_all_formats(tmp_path):
    paths = []
    expected = []
    for extension in FORMATS:
        for with_header in (True, False):
            student = {
                "aluno": f"Preview {extension} {with_header}",
                "email": f"preview.{extension}.{int(with_header)}@example.com",
                "matricula": f"PREVIEW-{extension}-{int(with_header)}",
            }
            data = [[student["aluno"], student["email"], student["matricula"]]]
            rows = [["Aluno", "E-mail", "Matricula"], *data] if with_header else data
            path = tmp_path / f"preview-{int(with_header)}.{extension}"
            path.write_bytes(_file_bytes(extension, rows))
            paths.append(path)
            expected.append({"ok": True, "rows": [student]})

    assert _browser_preview(paths) == expected


def test_browser_preview_uses_exact_header_detection_and_true_source_rows(tmp_path):
    alias_header = _write_file(
        tmp_path,
        "xlsx",
        [["Nome", "Email", "Matrícula"], ["Alias", "alias.preview@example.com", "A-1"]],
    )
    partial_header = tmp_path / "partial.csv"
    partial_header.write_bytes(
        _file_bytes(
            "csv",
            [
                ["Aluno", "real.preview@example.com", "REAL-1"],
                ["Second", "second.preview@example.com", "REAL-2"],
            ],
        )
    )
    no_header_error = tmp_path / "no-header-error.csv"
    no_header_error.write_bytes(_file_bytes("csv", [["Missing", "", "MISSING-1"]]))
    header_error = tmp_path / "header-error.csv"
    header_error.write_bytes(
        _file_bytes(
            "csv",
            [["Aluno", "E-mail", "Matricula"], ["Missing", "", "MISSING-2"]],
        )
    )

    assert _browser_preview(
        [alias_header, partial_header, no_header_error, header_error]
    ) == [
        {
            "ok": True,
            "rows": [
                {"aluno": "Alias", "email": "alias.preview@example.com", "matricula": "A-1"}
            ],
        },
        {
            "ok": True,
            "rows": [
                {
                    "aluno": "Aluno",
                    "email": "real.preview@example.com",
                    "matricula": "REAL-1",
                },
                {
                    "aluno": "Second",
                    "email": "second.preview@example.com",
                    "matricula": "REAL-2",
                },
            ],
        },
        {
            "ok": False,
            "error": "Linha 1: Aluno, E-mail e Matricula são obrigatórios.",
        },
        {
            "ok": False,
            "error": "Linha 2: Aluno, E-mail e Matricula são obrigatórios.",
        },
    ]


def test_browser_preview_rejects_header_like_first_row_like_the_server(tmp_path):
    paths = []
    for name, header in HEADER_LIKE_FIRST_ROWS.items():
        for extension in FORMATS:
            path = tmp_path / f"{name}.{extension}"
            path.write_bytes(_file_bytes(extension, _header_like_rows(header)))
            paths.append(path)

    assert _browser_preview(paths) == [{"ok": False, "error": HEADER_ORDER_ERROR}] * len(paths)


def test_browser_preview_reads_csv_as_utf8_text_like_the_server(tmp_path):
    accented_header = tmp_path / "accented-header.csv"
    accented_header.write_bytes(
        "Aluno,E-mail,Matrícula\nJoão Conceição,joao@example.com,001234\n".encode("utf-8")
    )
    bom_semicolon = tmp_path / "bom-semicolon.csv"
    bom_semicolon.write_bytes(
        "\ufeffAluno;E-mail;Matricula\nAna Lúcia;ana@example.com;3.200\n".encode("utf-8")
    )
    not_utf8 = tmp_path / "cp1252.csv"
    not_utf8.write_bytes("Aluno,E-mail,Matricula\nJosé,jose@example.com,1\n".encode("cp1252"))
    paths = [accented_header, bom_semicolon, not_utf8]

    server = []
    for path in paths:
        try:
            server.append(
                {
                    "ok": True,
                    "rows": [
                        {"aluno": row.aluno, "email": row.email, "matricula": row.matricula}
                        for row in parse_student_import(path)
                    ],
                }
            )
        except StudentImportError as exc:
            server.append({"ok": False, "error": str(exc)})

    assert server == [
        {
            "ok": True,
            "rows": [
                {"aluno": "João Conceição", "email": "joao@example.com", "matricula": "001234"}
            ],
        },
        {
            "ok": True,
            "rows": [{"aluno": "Ana Lúcia", "email": "ana@example.com", "matricula": "3.200"}],
        },
        {"ok": False, "error": "O CSV deve estar codificado em UTF-8."},
    ]
    assert _browser_preview(paths) == server
