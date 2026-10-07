"""Database-backed application images (prod-1/v13): storage, lookup, legacy fallback.

Owner of the three image side tables declared by ``app.prod1_images_ddl``:

    usuarios_foto     administrator profile photo   (owner usuarios.id)
    alunos_foto       student profile photo          (owner alunos.id)
    reportes_captura  report screenshot              (owner reportes.id)

WRITES
    ``store_image`` upserts the owner's single row and clears the owner's
    legacy path column in the caller's transaction; ``delete_image`` removes
    the row and clears the path the same way.  The caller commits.  Nothing is
    ever written to the filesystem.

READS
    ``load_image`` prefers the database row.  Only when an owner has no row
    and its legacy path column is still populated does it fall back to the
    file that path names (resolved with the same containment rules as the
    ``uploaded_file`` endpoint) -- and that file is served only if its bytes
    decode as an image of the category.  A database row is never ignored in
    favour of a local path.  The fallback disappears once the one-shot
    importer has moved every legacy file into the tables.

SESSION / TEMPLATES
    ``profile_photo_marker`` returns a short version marker (a SHA-256 prefix,
    or ``legacy-<digest of the reference>``) for the session and for the image
    URL's cache-busting parameter: never image bytes and never a path.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

from app.image_validation import (
    PROFILE_LEGACY_FORMATS,
    PROFILE_PHOTO_MAX_SOURCE_PIXELS,
    REPORT_SCREENSHOT_MAX_PIXELS,
    SCREENSHOT_FORMATS,
    ImageRejected,
    StoredImage,
    detect_image,
)
from app.sql_dialect import current_utc_text
from app.student_documents import resolve_student_document_path, sanitize_student_document_relpath


#: Upper bound for reading a legacy file: the former global request limit.
LEGACY_FILE_MAX_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class ImageTable:
    table: str
    owner_column: str
    owner_table: str
    legacy_column: str
    legacy_formats: dict
    legacy_max_pixels: int


USUARIOS_FOTO = ImageTable(
    "usuarios_foto", "usuario_id", "usuarios", "foto_perfil",
    PROFILE_LEGACY_FORMATS, PROFILE_PHOTO_MAX_SOURCE_PIXELS,
)
ALUNOS_FOTO = ImageTable(
    "alunos_foto", "aluno_id", "alunos", "foto_perfil",
    PROFILE_LEGACY_FORMATS, PROFILE_PHOTO_MAX_SOURCE_PIXELS,
)
REPORTES_CAPTURA = ImageTable(
    "reportes_captura", "reporte_id", "reportes", "screenshot_filename",
    SCREENSHOT_FORMATS, REPORT_SCREENSHOT_MAX_PIXELS,
)
IMAGE_TABLES = (USUARIOS_FOTO, ALUNOS_FOTO, REPORTES_CAPTURA)


class LegacyImageError(Exception):
    """A legacy reference cannot be resolved to exactly one readable file."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


# ---------------------------------------------------------------------------
# writes
# ---------------------------------------------------------------------------


def store_image(conn, spec: ImageTable, owner_id: int, image: StoredImage) -> None:
    """Insert or replace the owner's image row; clear its legacy path."""
    now = current_utc_text(conn)
    conn.execute(
        f"""INSERT INTO {spec.table}
                ({spec.owner_column}, mime_type, size_bytes, sha256, width, height, conteudo, atualizado_em)
            VALUES (?, ?, ?, ?, ?, ?, ?, {now})
            ON CONFLICT ({spec.owner_column}) DO UPDATE SET
                mime_type = excluded.mime_type,
                size_bytes = excluded.size_bytes,
                sha256 = excluded.sha256,
                width = excluded.width,
                height = excluded.height,
                conteudo = excluded.conteudo,
                atualizado_em = excluded.atualizado_em""",
        (
            int(owner_id), image.mime_type, image.size_bytes, image.sha256,
            image.width, image.height, image.content,
        ),
    )
    _clear_legacy_reference(conn, spec, owner_id)


def delete_image(conn, spec: ImageTable, owner_id: int) -> None:
    """Remove the owner's image: the row and any legacy path reference."""
    conn.execute(f"DELETE FROM {spec.table} WHERE {spec.owner_column} = ?", (int(owner_id),))
    _clear_legacy_reference(conn, spec, owner_id)


def _clear_legacy_reference(conn, spec: ImageTable, owner_id: int) -> None:
    conn.execute(
        f"UPDATE {spec.owner_table} SET {spec.legacy_column} = NULL"
        f" WHERE id = ? AND {spec.legacy_column} IS NOT NULL",
        (int(owner_id),),
    )


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LoadedImage:
    mime_type: str
    content: bytes
    sha256: str
    source: str  # "database" | "legacy"


def image_sha256(conn, spec: ImageTable, owner_id: int) -> str | None:
    """The stored digest only (no content), or None when there is no row."""
    row = conn.execute(
        f"SELECT sha256 FROM {spec.table} WHERE {spec.owner_column} = ?", (int(owner_id),)
    ).fetchone()
    return str(row[0]) if row else None


def legacy_reference(conn, spec: ImageTable, owner_id: int) -> str | None:
    row = conn.execute(
        f"SELECT {spec.legacy_column} FROM {spec.owner_table} WHERE id = ?", (int(owner_id),)
    ).fetchone()
    value = str(row[0] or "").strip() if row else ""
    return value or None


def legacy_marker(reference: str) -> str:
    return "legacy-" + hashlib.sha256(reference.encode("utf-8")).hexdigest()[:16]


def image_marker(conn, spec: ImageTable, owner_id: int) -> str | None:
    """Version marker for the owner's image (database row first), or None."""
    digest = image_sha256(conn, spec, owner_id)
    if digest:
        return digest[:16]
    reference = legacy_reference(conn, spec, owner_id)
    return legacy_marker(reference) if reference else None


def profile_owner(conn, user_type: str | None, usuario_id) -> tuple[ImageTable, int] | None:
    """Which table holds the signed-in user's profile photo, and under which owner id."""
    if not usuario_id:
        return None
    if user_type == "admin":
        return USUARIOS_FOTO, int(usuario_id)
    if user_type == "aluno":
        row = conn.execute("SELECT id FROM alunos WHERE usuario_id = ?", (int(usuario_id),)).fetchone()
        return (ALUNOS_FOTO, int(row[0])) if row else None
    return None


def profile_photo_marker(conn, user_type: str | None, usuario_id) -> str | None:
    owner = profile_owner(conn, user_type, usuario_id)
    return image_marker(conn, *owner) if owner else None


def resolve_legacy_path(reference: str, *, upload_root, documents_root, strict: bool) -> str:
    """Absolute path of the file a legacy reference names.

    Candidate roots follow the ``uploaded_file`` endpoint: a reference that
    starts with ``aluno_`` is looked up under the student-documents root first,
    then under the upload root; anything else only under the upload root.
    Both use the shared containment guard.  ``strict`` (the importer) refuses
    a reference present under both roots instead of picking one.
    """
    try:
        safe = sanitize_student_document_relpath(reference)
    except ValueError as exc:
        raise LegacyImageError("PATH_INVALID") from exc
    roots = []
    if safe.startswith("aluno_") and documents_root:
        roots.append(documents_root)
    if upload_root:
        roots.append(upload_root)
    found = []
    for root in roots:
        try:
            candidate = resolve_student_document_path(str(root), safe)
        except ValueError as exc:
            raise LegacyImageError("PATH_INVALID") from exc
        if os.path.isfile(candidate):
            found.append(candidate)
    if not found:
        raise LegacyImageError("FILE_MISSING")
    if strict and len(found) > 1 and len({os.path.normcase(os.path.realpath(p)) for p in found}) > 1:
        raise LegacyImageError("PATH_AMBIGUOUS")
    return found[0]


def read_legacy_file(path: str) -> bytes:
    with open(path, "rb") as handle:
        content = handle.read(LEGACY_FILE_MAX_BYTES + 1)
    if len(content) > LEGACY_FILE_MAX_BYTES:
        raise LegacyImageError("FILE_TOO_LARGE")
    return content


def load_image(conn, spec: ImageTable, owner_id: int, *, upload_root, documents_root) -> LoadedImage | None:
    """The owner's image for delivery, or None when there is nothing to serve."""
    row = conn.execute(
        f"SELECT mime_type, sha256, conteudo FROM {spec.table} WHERE {spec.owner_column} = ?",
        (int(owner_id),),
    ).fetchone()
    if row is not None:
        return LoadedImage(str(row[0]), bytes(row[2]), str(row[1]), "database")
    reference = legacy_reference(conn, spec, owner_id)
    if not reference:
        return None
    try:
        path = resolve_legacy_path(
            reference, upload_root=upload_root, documents_root=documents_root, strict=False
        )
        detected = detect_image(
            read_legacy_file(path), formats=spec.legacy_formats, max_pixels=spec.legacy_max_pixels
        )
    except (LegacyImageError, ImageRejected, OSError):
        return None
    return LoadedImage(detected.mime_type, detected.content, detected.sha256, "legacy")


__all__ = [
    "ALUNOS_FOTO",
    "IMAGE_TABLES",
    "ImageTable",
    "LEGACY_FILE_MAX_BYTES",
    "LegacyImageError",
    "LoadedImage",
    "REPORTES_CAPTURA",
    "USUARIOS_FOTO",
    "delete_image",
    "image_marker",
    "image_sha256",
    "legacy_marker",
    "legacy_reference",
    "load_image",
    "profile_owner",
    "profile_photo_marker",
    "read_legacy_file",
    "resolve_legacy_path",
    "store_image",
]
