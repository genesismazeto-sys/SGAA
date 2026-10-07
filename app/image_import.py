# coding: utf-8
"""One-shot importer: legacy image files -> prod-1/v13 database image rows.

WHY THIS EXISTS
    Before v13 a profile photo or report screenshot was a file under an upload
    root, referenced by ``usuarios.foto_perfil``, ``alunos.foto_perfil`` or
    ``reportes.screenshot_filename``.  From v13 on they are rows in
    ``usuarios_foto`` / ``alunos_foto`` / ``reportes_captura``.  This offline
    command moves every still-referenced legacy file into its row so the
    installation stops needing those files (and Path-B, which refuses any
    populated legacy reference, can run).  Nothing in the web application
    imports or runs it.

    python -m app.image_import --database DB --upload-root DIR --documents-root DIR [--apply]

    Without ``--apply`` it is a DRY RUN: it opens the database read-only and
    prints counts only.  Run it with the application stopped; take a backup
    first.

PER RECORD (``--apply``), in its own ``BEGIN IMMEDIATE`` transaction
    1. resolve the reference with the ``uploaded_file`` containment rules; a
       reference that escapes its root, names no file, or names a file under
       BOTH roots is refused (``PATH_INVALID`` / ``FILE_MISSING`` /
       ``PATH_AMBIGUOUS``) -- the tool never chooses;
    2. validate the bytes exactly as a new upload: a profile photo is decoded
       and re-encoded (<= 512 px, no metadata), a screenshot is verified and
       kept; anything else is refused with the validator's code;
    3. inside the transaction the reference must still be the one read, then:
       no image row -> insert it; a row with the same SHA-256 -> keep it; a row
       with a DIFFERENT SHA-256 -> refuse (``CONFLICT_DIFFERENT_IMAGE``), never
       pick one silently;
    4. the legacy path column is set to NULL in the same transaction.

    Rerunning is safe: migrated records no longer have a reference, and a
    record whose row already holds the same image only gets its path cleared.
    Source files are never modified or deleted.

OUTPUT
    Table, owner row id and a status code only -- never a path, filename,
    person's name or image byte.  Exit 0 when nothing was refused, 1 when any
    record was refused (the others are still migrated), 2 on usage errors.
"""

from __future__ import annotations

import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

from app.db_images import (
    IMAGE_TABLES,
    LEGACY_FILE_MAX_BYTES,
    REPORTES_CAPTURA,
    LegacyImageError,
    read_legacy_file,
    resolve_legacy_path,
    store_image,
)
from app.image_validation import ImageRejected, normalize_profile_photo, validate_report_screenshot


MIGRATED = "MIGRATED"
ALREADY_PRESENT_IDENTICAL = "ALREADY_PRESENT_IDENTICAL"
CONFLICT_DIFFERENT_IMAGE = "CONFLICT_DIFFERENT_IMAGE"
REFERENCE_CHANGED = "REFERENCE_CHANGED"
SUCCESS_CODES = frozenset({MIGRATED, ALREADY_PRESENT_IDENTICAL})


class ImportRefused(Exception):
    """The whole run cannot start (database, schema or arguments)."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass
class TableCensus:
    legacy_references: int = 0
    database_images: int = 0
    already_migrated: int = 0
    reference_with_image: int = 0


@dataclass
class ImportReport:
    applied: bool = False
    census: dict = field(default_factory=dict)  # table -> TableCensus
    results: list = field(default_factory=list)  # (table, owner id, code)

    def counts(self) -> dict:
        totals: dict = {}
        for table, _owner_id, code in self.results:
            totals.setdefault(table, {}).setdefault(code, 0)
            totals[table][code] += 1
        return totals

    @property
    def refused(self) -> int:
        return sum(1 for _table, _owner_id, code in self.results if code not in SUCCESS_CODES)


def _connect(database, *, read_only: bool) -> sqlite3.Connection:
    path = Path(database)
    if not path.is_file():
        raise ImportRefused("DATABASE_MISSING")
    if read_only:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=30.0)
    else:
        conn = sqlite3.connect(str(path), timeout=30.0, isolation_level=None)
        conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _require_current_schema(conn) -> None:
    from app.prod1_schema import Prod1SchemaError, validate_prod1_schema

    try:
        validate_prod1_schema(conn)
    except Prod1SchemaError as exc:
        raise ImportRefused("SCHEMA_NOT_CURRENT") from exc


def census(conn) -> dict:
    result = {}
    for spec in IMAGE_TABLES:
        one = lambda sql: int(conn.execute(sql).fetchone()[0])  # noqa: E731
        legacy = f"COALESCE(o.{spec.legacy_column}, '') <> ''"
        result[spec.table] = TableCensus(
            legacy_references=one(f"SELECT count(*) FROM {spec.owner_table} o WHERE {legacy}"),
            database_images=one(f"SELECT count(*) FROM {spec.table}"),
            already_migrated=one(
                f"SELECT count(*) FROM {spec.table} i JOIN {spec.owner_table} o"
                f" ON o.id = i.{spec.owner_column} WHERE NOT ({legacy})"
            ),
            reference_with_image=one(
                f"SELECT count(*) FROM {spec.table} i JOIN {spec.owner_table} o"
                f" ON o.id = i.{spec.owner_column} WHERE {legacy}"
            ),
        )
    return result


def _candidates(conn, spec) -> list[tuple[int, str]]:
    return [
        (int(row[0]), str(row[1]).strip())
        for row in conn.execute(
            f"SELECT id, {spec.legacy_column} FROM {spec.owner_table}"
            f" WHERE COALESCE({spec.legacy_column}, '') <> '' ORDER BY id"
        ).fetchall()
    ]


def _prepare(spec, reference, *, upload_root, documents_root):
    """Validated image for one reference; raises with a value-free code."""
    path = resolve_legacy_path(
        reference, upload_root=upload_root, documents_root=documents_root, strict=True
    )
    content = read_legacy_file(path)
    if spec is REPORTES_CAPTURA:
        return validate_report_screenshot(content)
    return normalize_profile_photo(content, max_input_bytes=LEGACY_FILE_MAX_BYTES)


def _import_one(conn, spec, owner_id, reference, image) -> str:
    conn.execute("BEGIN IMMEDIATE")
    try:
        current = conn.execute(
            f"SELECT {spec.legacy_column} FROM {spec.owner_table} WHERE id = ?", (owner_id,)
        ).fetchone()
        if current is None or str(current[0] or "").strip() != reference:
            conn.execute("ROLLBACK")
            return REFERENCE_CHANGED
        existing = conn.execute(
            f"SELECT sha256 FROM {spec.table} WHERE {spec.owner_column} = ?", (owner_id,)
        ).fetchone()
        if existing is not None and str(existing[0]) != image.sha256:
            conn.execute("ROLLBACK")
            return CONFLICT_DIFFERENT_IMAGE
        if existing is None:
            store_image(conn, spec, owner_id, image)
            code = MIGRATED
        else:
            conn.execute(
                f"UPDATE {spec.owner_table} SET {spec.legacy_column} = NULL WHERE id = ?",
                (owner_id,),
            )
            code = ALREADY_PRESENT_IDENTICAL
        conn.execute("COMMIT")
        return code
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def run_import(database, *, upload_root=None, documents_root=None, apply=False, announce=lambda line: None) -> ImportReport:
    report = ImportReport()
    conn = _connect(database, read_only=not apply)
    try:
        _require_current_schema(conn)
        report.census = census(conn)
        if not apply:
            return report
        if not upload_root and not documents_root:
            if any(c.legacy_references for c in report.census.values()):
                raise ImportRefused("ASSET_ROOTS_REQUIRED")
        for spec in IMAGE_TABLES:
            for owner_id, reference in _candidates(conn, spec):
                try:
                    image = _prepare(
                        spec, reference, upload_root=upload_root, documents_root=documents_root
                    )
                except (LegacyImageError, ImageRejected) as exc:
                    code = exc.code
                except OSError:
                    code = "FILE_UNREADABLE"
                else:
                    code = _import_one(conn, spec, owner_id, reference, image)
                report.results.append((spec.table, owner_id, code))
                announce(f"{spec.table} id={owner_id} status={code}")
        report.applied = True
        report.census = census(conn)
    finally:
        conn.close()
    return report


def format_report(report: ImportReport) -> list[str]:
    lines = []
    for table, item in report.census.items():
        lines.append(
            f"census: {table} legacy_references={item.legacy_references} "
            f"database_images={item.database_images} already_migrated={item.already_migrated} "
            f"reference_with_image={item.reference_with_image}"
        )
    for table, codes in sorted(report.counts().items()):
        for code, count in sorted(codes.items()):
            lines.append(f"result: {table} {code}={count}")
    if not report.applied:
        lines.append("result: DRY RUN -- nothing written (pass --apply)")
    elif report.refused:
        lines.append(f"result: APPLIED_WITH_REFUSALS refused={report.refused}")
    else:
        lines.append("result: APPLIED")
    return lines


_USAGE = (
    "usage: python -m app.image_import --database DB\n"
    "         [--upload-root DIR] [--documents-root DIR] [--apply]\n"
    "\n"
    "Moves legacy profile photos and report screenshots (files referenced by\n"
    "usuarios.foto_perfil, alunos.foto_perfil, reportes.screenshot_filename)\n"
    "into the prod-1/v13 image tables, one record per transaction, clearing\n"
    "each path in the same transaction. Without --apply: counts only.\n"
    "Stop the application and back the database up first.\n"
    "\n"
    "exit: 0 ok / dry run; 1 refused or any record refused; 2 usage.\n"
)

_OPTIONS = {
    "--database": "database",
    "--upload-root": "upload_root",
    "--documents-root": "documents_root",
}


def _parse(arguments):
    values = {"apply": False}
    pending = list(arguments)
    while pending:
        flag = pending.pop(0)
        if flag == "--apply":
            values["apply"] = True
            continue
        if flag not in _OPTIONS or not pending or _OPTIONS[flag] in values:
            raise ValueError("usage")
        values[_OPTIONS[flag]] = pending.pop(0)
    if not values.get("database"):
        raise ValueError("usage")
    return values


def main(argv=None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] in {"-h", "--help"}:
        print(_USAGE)
        return 0
    try:
        options = _parse(arguments)
    except ValueError:
        print(_USAGE, file=sys.stderr)
        return 2
    try:
        report = run_import(
            options["database"],
            upload_root=options.get("upload_root"),
            documents_root=options.get("documents_root"),
            apply=options["apply"],
            announce=print,
        )
    except ImportRefused as exc:
        print(f"image-import: refused: {exc.code}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"image-import: error: {exc.__class__.__name__}", file=sys.stderr)
        return 1
    for line in format_report(report):
        print(line)
    return 1 if report.refused else 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ALREADY_PRESENT_IDENTICAL",
    "CONFLICT_DIFFERENT_IMAGE",
    "ImportRefused",
    "ImportReport",
    "MIGRATED",
    "REFERENCE_CHANGED",
    "census",
    "format_report",
    "main",
    "run_import",
]
