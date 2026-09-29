from __future__ import annotations

import csv
import datetime as dt
import re
import struct
from dataclasses import dataclass
from decimal import Decimal
from itertools import chain
from pathlib import Path
from typing import Iterable

import openpyxl

from app.services.mail_service import is_valid_email
from app.text import normalize_header


SUPPORTED_STUDENT_IMPORT_EXTENSIONS = {"csv", "xlsx", "xls"}
CANONICAL_STUDENT_IMPORT_HEADERS = ("Aluno", "E-mail", "Matricula")
_HEADER_ALIASES = (
    {"aluno", "nome"},
    {"e-mail", "email"},
    {"matricula"},
)
_HEADER_NAMES = frozenset().union(*_HEADER_ALIASES)
# Fórmula e valor de erro de planilha nunca são dado de aluno: a importação é
# de dados, não um motor de cálculo. A célula é recusada pelo tipo que o leitor
# informa, sem avaliar a fórmula nem usar o valor calculado em cache.
_SPREADSHEET_EXPRESSION_KINDS = frozenset({"formula", "error"})


class StudentImportError(ValueError):
    pass


@dataclass(frozen=True)
class StudentImportRow:
    aluno: str
    email: str
    matricula: str
    source_row: int


@dataclass(frozen=True)
class _Cell:
    value: object
    number_format: str = ""
    kind: str = "text"


def _numeric_text(value: int | float | Decimal, number_format: str = "") -> str:
    decimal_value = Decimal(str(value))
    if not decimal_value.is_finite():
        raise StudentImportError("A matrícula contém um valor numérico inválido.")
    significant_digits = len(decimal_value.normalize().as_tuple().digits)
    if significant_digits > 15:
        raise StudentImportError(
            "A matrícula contém um valor numérico sem representação textual segura."
        )
    primary_format = str(number_format or "").split(";", 1)[0].strip()
    if decimal_value == decimal_value.to_integral_value() and re.fullmatch(r"0+", primary_format):
        return str(int(decimal_value)).zfill(len(primary_format))

    rendered = format(decimal_value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def _cell_text(cell: _Cell, *, identifier: bool = False) -> str:
    value = cell.value
    if value is None:
        return ""
    if identifier and (
        cell.kind in {"date", "datetime"}
        or isinstance(value, (dt.date, dt.datetime, dt.time))
    ):
        raise StudentImportError("A matrícula não pode ser uma data ou hora.")
    if identifier and cell.kind == "boolean":
        raise StudentImportError("A matrícula não pode ser um valor booleano.")
    if identifier and isinstance(value, (bytes, bytearray, list, tuple, dict, set)):
        raise StudentImportError("A matrícula deve ser um identificador escalar.")
    if isinstance(value, bool):
        return "VERDADEIRO" if value else "FALSO"
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        return _numeric_text(value, cell.number_format if identifier else "")
    return str(value).strip()


def _is_expression(cell: _Cell) -> bool:
    return cell.kind in _SPREADSHEET_EXPRESSION_KINDS


def _row_has_content(cells: list[_Cell]) -> bool:
    # Uma fórmula conta como conteúdo mesmo quando o resultado em cache é vazio.
    return any(_is_expression(cell) or _cell_text(cell) for cell in cells)


def _header_name(cell: _Cell) -> str:
    # Uma fórmula nunca é nome de coluna, qualquer que seja o valor calculado.
    return "" if _is_expression(cell) else normalize_header(_cell_text(cell))


def _is_header(cells: list[_Cell]) -> bool:
    if len(cells) != 3:
        return False
    header = tuple(_header_name(cell) for cell in cells[:3])
    return all(value in aliases for value, aliases in zip(header, _HEADER_ALIASES))


def _looks_like_header(cells: list[_Cell]) -> bool:
    # Dois ou mais nomes de coluna numa linha nunca são um aluno real: é um
    # cabeçalho fora da ordem (ex.: Matricula, Aluno, E-mail), que lido como
    # dados trocaria as colunas de posição.
    return sum(_header_name(cell) in _HEADER_NAMES for cell in cells) >= 2


def _normalize_data_rows(
    rows: Iterable[tuple[int, list[_Cell]]],
    *,
    allow_empty: bool = False,
    from_file: bool = False,
) -> list[StudentImportRow]:
    normalized: list[StudentImportRow] = []
    seen_emails: dict[str, int] = {}
    seen_matriculas: dict[str, int] = {}

    for row_number, cells in rows:
        if not _row_has_content(cells):
            continue
        # Cabeçalho só na primeira linha: repetido adiante é arquivo
        # concatenado ou malformado, nunca um aluno chamado "Aluno".
        if from_file and _looks_like_header(cells):
            raise StudentImportError(
                f"Linha {row_number}: cabeçalho repetido no meio do arquivo; o cabeçalho só é aceito na primeira linha."
            )
        if len(cells) > 3:
            raise StudentImportError(
                f"Linha {row_number}: a linha deve ter exatamente 3 colunas: Aluno, E-mail, Matricula."
            )
        for label, cell in zip(CANONICAL_STUDENT_IMPORT_HEADERS, cells):
            if _is_expression(cell):
                raise StudentImportError(
                    f"Linha {row_number}: fórmula ou valor de erro na coluna {label}; a importação aceita apenas valores digitados."
                )

        aluno = _cell_text(cells[0]) if len(cells) > 0 else ""
        email = _cell_text(cells[1]) if len(cells) > 1 else ""
        matricula = _cell_text(cells[2], identifier=True) if len(cells) > 2 else ""
        missing = [
            label
            for label, value in (("Aluno", aluno), ("E-mail", email), ("Matricula", matricula))
            if not value
        ]
        if missing:
            raise StudentImportError(f"Linha {row_number}: campo(s) obrigatório(s) ausente(s): {', '.join(missing)}.")
        # A mesma regra de todo envio de e-mail do SGAA: o endereço gravado é o
        # que recebe o primeiro acesso. Vale também para a linha digitada no
        # formulário da Turma, que um POST direto entrega sem a validação do
        # navegador; nela o nome identifica o aluno, porque a página de erro
        # recarrega o roster salvo e a numeração da tela muda.
        if not is_valid_email(email):
            if from_file:
                raise StudentImportError(f"Linha {row_number}: e-mail inválido.")
            raise StudentImportError(f"Linha {row_number} ({aluno}): e-mail inválido.")

        email_key = email.casefold()
        if email_key in seen_emails:
            raise StudentImportError(
                f"Linha {row_number}: e-mail duplicado no arquivo; primeira ocorrência na linha {seen_emails[email_key]}."
            )
        if matricula in seen_matriculas:
            raise StudentImportError(
                f"Linha {row_number}: matrícula duplicada no arquivo; primeira ocorrência na linha {seen_matriculas[matricula]}."
            )
        seen_emails[email_key] = row_number
        seen_matriculas[matricula] = row_number
        normalized.append(StudentImportRow(aluno, email, matricula, row_number))

    if not normalized and not allow_empty:
        raise StudentImportError("O arquivo não contém nenhum aluno para importar.")
    return normalized


def _normalize_rows(rows: Iterable[tuple[int, list[_Cell]]]) -> list[StudentImportRow]:
    iterator = iter(rows)
    for row_number, cells in iterator:
        if not _row_has_content(cells):
            continue
        if _is_header(cells):
            return _normalize_data_rows(iterator, from_file=True)
        if _looks_like_header(cells):
            raise StudentImportError(
                f"Linha {row_number}: o cabeçalho deve seguir exatamente esta ordem: Aluno, E-mail, Matricula."
            )
        return _normalize_data_rows(chain([(row_number, cells)], iterator), from_file=True)
    raise StudentImportError("O arquivo está vazio.")


def _csv_rows(path: Path) -> Iterable[tuple[int, list[_Cell]]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            sample = source.read(4096)
            source.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
            except csv.Error:
                dialect = csv.excel
            for row_number, values in enumerate(
                csv.reader(source, dialect=dialect, strict=True),
                start=1,
            ):
                yield row_number, [_Cell(value) for value in values]
    except UnicodeDecodeError as exc:
        raise StudentImportError("O CSV deve estar codificado em UTF-8.") from exc
    except csv.Error as exc:
        raise StudentImportError("O CSV está malformado e não pôde ser lido.") from exc


def _xlsx_rows(path: Path) -> Iterable[tuple[int, list[_Cell]]]:
    try:
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=False)
    except Exception as exc:
        raise StudentImportError("A planilha XLSX está malformada e não pôde ser lida.") from exc
    rows = []
    try:
        sheet = workbook.active
        for row_number, cells in enumerate(sheet.iter_rows(), start=1):
            kinds = {"d": "date", "e": "error", "f": "formula", "b": "boolean"}
            rows.append(
                (
                    row_number,
                    [
                        _Cell(cell.value, cell.number_format, kinds.get(cell.data_type, cell.data_type))
                        for cell in cells
                    ],
                )
            )
    finally:
        workbook.close()
    return rows


_XLS_FORMULA_OPCODES = frozenset({0x0006, 0x0206, 0x0406})
_XLS_BOF_OPCODES = frozenset({0x0009, 0x0209, 0x0409, 0x0809})
_XLS_EOF_OPCODE = 0x000A


def _xls_formula_cells(workbook, sheet_index: int) -> frozenset[tuple[int, int]]:
    """(linha, coluna) de cada registro FORMULA da planilha, base 0.

    O xlrd guarda só o resultado em cache de uma fórmula, tipado como um valor
    comum; o tipo da célula está no registro BIFF. Varre o mesmo stream que o
    xlrd já leu, a partir do BOF da planilha até o EOF correspondente (um
    gráfico embutido abre e fecha o próprio par BOF/EOF).
    """
    stream = workbook.mem
    position = workbook._sh_abs_posn[sheet_index]
    end = workbook.base + workbook.stream_len
    depth = 0
    cells = set()
    while position + 4 <= end:
        opcode, length = struct.unpack_from("<HH", stream, position)
        body = position + 4
        if opcode in _XLS_BOF_OPCODES:
            depth += 1
        elif opcode == _XLS_EOF_OPCODE:
            depth -= 1
            if depth <= 0:
                break
        elif depth == 1 and opcode in _XLS_FORMULA_OPCODES:
            cells.add(struct.unpack_from("<HH", stream, body))
        position = body + length
    return frozenset(cells)


def _xls_rows(path: Path) -> Iterable[tuple[int, list[_Cell]]]:
    try:
        import xlrd
    except ImportError as exc:
        raise StudentImportError("A leitura de arquivos XLS não está disponível.") from exc

    try:
        workbook = xlrd.open_workbook(path, formatting_info=True, on_demand=True)
    except Exception as exc:
        raise StudentImportError("A planilha XLS está malformada e não pôde ser lida.") from exc
    rows = []
    try:
        if workbook.nsheets == 0:
            return rows
        sheet = workbook.sheet_by_index(0)
        try:
            formula_cells = _xls_formula_cells(workbook, 0)
        except struct.error as exc:
            raise StudentImportError("A planilha XLS está malformada e não pôde ser lida.") from exc
        for row_index in range(sheet.nrows):
            cells: list[_Cell] = []
            for column_index in range(sheet.ncols):
                source_cell = sheet.cell(row_index, column_index)
                number_format = ""
                if source_cell.ctype == xlrd.XL_CELL_NUMBER:
                    xf = workbook.xf_list[source_cell.xf_index]
                    fmt = workbook.format_map.get(xf.format_key)
                    number_format = fmt.format_str if fmt is not None else ""
                kinds = {
                    xlrd.XL_CELL_DATE: "date",
                    xlrd.XL_CELL_ERROR: "error",
                    xlrd.XL_CELL_BOOLEAN: "boolean",
                    xlrd.XL_CELL_NUMBER: "number",
                    xlrd.XL_CELL_TEXT: "text",
                }
                cells.append(
                    _Cell(
                        source_cell.value,
                        number_format,
                        "formula"
                        if (row_index, column_index) in formula_cells
                        else kinds.get(source_cell.ctype, "unknown"),
                    )
                )
            rows.append((row_index + 1, cells))
    finally:
        workbook.release_resources()
    return rows
def parse_student_import(path: str | Path) -> list[StudentImportRow]:
    source_path = Path(path)
    extension = source_path.suffix.lower().lstrip(".")
    if extension not in SUPPORTED_STUDENT_IMPORT_EXTENSIONS:
        raise StudentImportError("Formato não suportado. Envie um arquivo CSV, XLSX ou XLS.")
    if extension == "csv":
        rows = _csv_rows(source_path)
    elif extension == "xlsx":
        rows = _xlsx_rows(source_path)
    else:
        rows = _xls_rows(source_path)
    try:
        return _normalize_rows(rows)
    finally:
        close = getattr(rows, "close", None)
        if close:
            close()


def normalize_student_import_values(
    values: Iterable[tuple[object, object, object]],
    *,
    allow_empty: bool = False,
) -> list[StudentImportRow]:
    rows = (
        (row_number, [_Cell(aluno), _Cell(email), _Cell(matricula)])
        for row_number, (aluno, email, matricula) in enumerate(values, start=1)
    )
    return _normalize_data_rows(rows, allow_empty=allow_empty)


__all__ = [
    "CANONICAL_STUDENT_IMPORT_HEADERS",
    "SUPPORTED_STUDENT_IMPORT_EXTENSIONS",
    "StudentImportError",
    "StudentImportRow",
    "normalize_student_import_values",
    "parse_student_import",
]
