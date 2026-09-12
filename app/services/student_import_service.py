from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Iterable, Sequence

from app.student_import import (
    StudentImportError,
    StudentImportRow,
    normalize_student_import_values,
)
from app.student_matrix import matrix_for_turma_assignment
from app.user_accounts import (
    create_usuario_with_default_password,
    normalize_usuario_access_for_user_type,
)


ACTIVE_STUDENT_STATUS = "Ativo"
INACTIVE_STUDENT_STATUS = "Inativo"


@dataclass(frozen=True)
class StudentImportResult:
    created: int
    updated: int
    skipped: int

    @property
    def imported(self) -> int:
        return self.created + self.updated


@dataclass(frozen=True)
class StudentFormSyncResult:
    import_result: StudentImportResult
    matriculas: frozenset[str]
    has_imported_rows: bool


def _single_casefold_email_row(conn, table: str, email: str):
    if table not in {"alunos", "usuarios"}:
        raise RuntimeError("Tabela de identidade não autorizada.")
    rows = conn.execute(
        f"SELECT * FROM {table} WHERE LOWER(email)=LOWER(?) ORDER BY id",
        (email,),
    ).fetchall()
    if len(rows) > 1:
        raise StudentImportError(
            "Há identidades duplicadas por diferença apenas de maiúsculas no e-mail."
        )
    return rows[0] if rows else None


def _resolve_existing_student(conn, row: StudentImportRow):
    by_matricula = conn.execute(
        "SELECT * FROM alunos WHERE matricula=?", (row.matricula,)
    ).fetchone()
    by_email = _single_casefold_email_row(conn, "alunos", row.email)
    if by_matricula and by_email and by_matricula["id"] != by_email["id"]:
        raise StudentImportError(
            f"Linha {row.source_row}: conflito entre matrícula e e-mail; pertencem a alunos diferentes."
        )
    return by_matricula or by_email


def _validated_linked_user(conn, row: StudentImportRow, existing):
    target_user = _single_casefold_email_row(conn, "usuarios", row.email)
    if not existing:
        if not target_user:
            return None
        if target_user["tipo"] != "aluno":
            raise StudentImportError(
                f"Linha {row.source_row}: o e-mail pertence a uma conta que não é de aluno."
            )
        raise StudentImportError(
            f"Linha {row.source_row}: existe uma conta de aluno sem cadastro de aluno vinculado; correção manual necessária."
        )

    if not existing["usuario_id"]:
        raise StudentImportError(
            f"Linha {row.source_row}: o aluno existente não possui conta de aluno vinculada."
        )
    linked_user = conn.execute(
        "SELECT * FROM usuarios WHERE id=?", (existing["usuario_id"],)
    ).fetchone()
    if not linked_user or linked_user["tipo"] != "aluno":
        raise StudentImportError(
            f"Linha {row.source_row}: o cadastro está ligado a uma conta que não é de aluno."
        )
    if target_user and target_user["id"] != linked_user["id"]:
        raise StudentImportError(
            f"Linha {row.source_row}: o e-mail pertence a outra conta; identidades não podem ser mescladas."
        )
    return linked_user


def _persist_student_row(conn, turma_id: int, row: StudentImportRow, status: str, existing, linked_user) -> str:
    if existing:
        matriz_id = matrix_for_turma_assignment(
            conn,
            current_matriz_id=existing["matriz_id"],
            turma_id=turma_id,
            current_turma_id=existing["turma_id"],
        )
        conn.execute(
            "UPDATE usuarios SET nome=?, email=? WHERE id=?",
            (row.aluno, row.email, linked_user["id"]),
        )
        normalize_usuario_access_for_user_type(conn, linked_user["id"])
        conn.execute(
            """
            UPDATE alunos
               SET nome=?, email=?, matricula=?, turma_id=?, matriz_id=?, status=?
             WHERE id=?
            """,
            (row.aluno, row.email, row.matricula, turma_id, matriz_id, status, existing["id"]),
        )
        return "updated"

    usuario_id = create_usuario_with_default_password(
        conn, row.aluno, row.email, "aluno"
    ).lastrowid
    conn.execute(
        """
        INSERT INTO alunos (usuario_id,nome,email,matricula,turma_id,matriz_id,status)
        VALUES (?,?,?,?,?,?,?)
        """,
        (
            usuario_id,
            row.aluno,
            row.email,
            row.matricula,
            turma_id,
            matrix_for_turma_assignment(
                conn, current_matriz_id=None, turma_id=turma_id
            ),
            status,
        ),
    )
    return "created"


def _persist_rows(
    conn,
    turma_id: int,
    rows_with_status: Iterable[tuple[StudentImportRow, str]],
    *,
    on_conflict: str,
) -> StudentImportResult:
    if on_conflict not in {"skip", "update"}:
        raise StudentImportError("A opção de conflito informada é inválida.")
    if not conn.execute("SELECT 1 FROM turmas WHERE id=?", (turma_id,)).fetchone():
        raise StudentImportError("A turma de destino não existe.")

    items = list(rows_with_status)
    seen_emails: dict[str, int] = {}
    seen_matriculas: dict[str, int] = {}
    for row, _ in items:
        email_key = row.email.casefold()
        if email_key in seen_emails:
            raise StudentImportError(
                f"Linha {row.source_row}: e-mail duplicado no envio."
            )
        if row.matricula in seen_matriculas:
            raise StudentImportError(
                f"Linha {row.source_row}: matrícula duplicada no envio."
            )
        seen_emails[email_key] = row.source_row
        seen_matriculas[row.matricula] = row.source_row

    created = updated = skipped = 0
    for row, status in items:
        try:
            existing = _resolve_existing_student(conn, row)
            linked_user = _validated_linked_user(conn, row, existing)
            if existing and on_conflict == "skip":
                skipped += 1
                continue
            outcome = _persist_student_row(
                conn, turma_id, row, status, existing, linked_user
            )
            created += outcome == "created"
            updated += outcome == "updated"
        except StudentImportError:
            raise
        except sqlite3.IntegrityError as exc:
            raise StudentImportError(
                f"Linha {row.source_row}: matrícula ou e-mail em conflito com um cadastro existente."
            ) from exc
        except ValueError as exc:
            raise StudentImportError(f"Linha {row.source_row}: {exc}") from exc
    return StudentImportResult(created=created, updated=updated, skipped=skipped)


def import_students_into_turma(
    conn,
    turma_id: int,
    rows: Iterable[StudentImportRow],
    *,
    on_conflict: str = "update",
) -> StudentImportResult:
    return _persist_rows(
        conn,
        turma_id,
        ((row, ACTIVE_STUDENT_STATUS) for row in rows),
        on_conflict=on_conflict,
    )


def _reconcile_roster_form_rows(
    conn,
    turma_id: int,
    form_rows: Sequence[StudentImportRow],
    imported_rows: Sequence[StudentImportRow],
) -> list[StudentImportRow]:
    if not imported_rows:
        return list(form_rows)
    roster = conn.execute(
        "SELECT email,matricula FROM alunos WHERE turma_id=?", (turma_id,)
    ).fetchall()
    roster_emails = {
        str(item["email"] or "").casefold() for item in roster if item["email"]
    }
    roster_matriculas = {item["matricula"] for item in roster}
    imported_emails = {row.email.casefold() for row in imported_rows}
    imported_matriculas = {row.matricula for row in imported_rows}
    return [
        row
        for row in form_rows
        if not (
            (row.email.casefold() in roster_emails or row.matricula in roster_matriculas)
            and (
                row.email.casefold() in imported_emails
                or row.matricula in imported_matriculas
            )
        )
    ]


def sync_turma_form_students(
    conn,
    turma_id: int,
    nomes: Sequence[str],
    emails: Sequence[str],
    matriculas: Sequence[str],
    statuses: Sequence[str],
    imported_flags: Sequence[str],
    *,
    imported_rows: Sequence[StudentImportRow] = (),
) -> StudentFormSyncResult:
    count = max((len(nomes), len(emails), len(matriculas)), default=0)
    values = []
    status_by_row: dict[int, str] = {}
    for index in range(count):
        imported = (
            index < len(imported_flags)
            and str(imported_flags[index]).strip().lower() in {"1", "true", "yes"}
        )
        values.append(
            ("", "", "")
            if imported
            else (
                nomes[index] if index < len(nomes) else "",
                emails[index] if index < len(emails) else "",
                matriculas[index] if index < len(matriculas) else "",
            )
        )
        submitted_status = statuses[index] if index < len(statuses) else "ATIVO"
        status_by_row[index + 1] = ACTIVE_STUDENT_STATUS if (
            str(submitted_status).strip().upper() == "ATIVO"
        ) else INACTIVE_STUDENT_STATUS

    form_rows = normalize_student_import_values(values, allow_empty=True)
    imported_rows = tuple(imported_rows)
    form_rows = _reconcile_roster_form_rows(
        conn, turma_id, form_rows, imported_rows
    )
    result = _persist_rows(
        conn,
        turma_id,
        [
            *((row, status_by_row[row.source_row]) for row in form_rows),
            *((row, ACTIVE_STUDENT_STATUS) for row in imported_rows),
        ],
        on_conflict="update",
    )
    return StudentFormSyncResult(
        import_result=result,
        matriculas=frozenset(
            row.matricula for row in (*form_rows, *imported_rows)
        ),
        has_imported_rows=bool(imported_rows),
    )


__all__ = [
    "ACTIVE_STUDENT_STATUS",
    "StudentFormSyncResult",
    "StudentImportResult",
    "import_students_into_turma",
    "sync_turma_form_students",
]
