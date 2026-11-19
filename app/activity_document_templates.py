"""DOCX fill-in templates of activity versions: store, attach, replace, withdraw, read.

An administrator may offer students one or more Word documents to fill in
for an activity -- a declaration form, an attendance sheet.  Each template
belongs to ONE activity version (schema v19, ``app.prod1_document_templates_ddl``):

    modelo_documento_arquivos   the verified DOCX bytes, content addressed,
                                immutable, kept while any association
                                references them
    atividade_versao_modelos    title + download name + slot of a template in
                                a version, ``ativo`` -> ``substituido`` |
                                ``retirado``

Like the required-document guidance (``app.activity_documentation``) a
template is information for the student: nothing compares an uploaded proof
with it, requires it, or decides a request because of it.

VERSIONING
    Templates follow the activity freeze policy
    (``can_activity_version_be_mutated_in_place``): they are added, replaced
    and withdrawn only on an unreferenced draft.  A frozen version keeps the
    templates it had, so a request filed under it always points at the
    templates that were offered.  A new version -- the version form or any
    successor of the semantic policy -- starts with a copy of its source's
    active templates (``copy_active_templates``); Matrices and requests keep
    the version they reference.

CUSTODY
    A replacement ends the old association (``substituido``) and opens a new
    one in the same slot; a withdrawal ends it (``retirado``).  The bytes of
    every template ever offered stay in ``modelo_documento_arquivos``, and an
    administrator can still download an ended association.

AUTHORIZATION
    Writes: the caller's route is ``atividades:edit``; this owner re-checks
    the version state under the base lock, then the version row lock
    (``app.db``), inside one write transaction.  Reads: an administrator with
    ``atividades:view`` reads any association.
"""

from __future__ import annotations

import hashlib
import io
import re
import unicodedata
from dataclasses import dataclass

from flask import send_file

from app.activity_catalog import can_activity_version_be_mutated_in_place
from app.db import lock_activity_base, lock_activity_version, write_transaction
from app.docx_validation import DocxRejected, validate_docx
from app.prod1_document_templates_ddl import (
    DOCUMENT_TEMPLATE_FILENAME_MAX_LENGTH,
    DOCUMENT_TEMPLATE_MAX_BYTES,
    DOCUMENT_TEMPLATE_TITLE_MAX_LENGTH,
    DOCX_MIME_TYPE,
)
from app.presentation import _format_bytes_label, format_date_ptbr
from app.sql_dialect import current_utc_text

MAX_ACTIVE_TEMPLATES_PER_VERSION = 10
TEMPLATE_FILE_FIELD = "modelo_arquivo"
TEMPLATE_TITLE_FIELD = "modelo_titulo"

FROZEN_MESSAGE = (
    "Os modelos só podem ser alterados em uma versão em rascunho que ainda não está em uso. "
    "Crie uma nova versão para alterá-los."
)
VERSION_NOT_FOUND_MESSAGE = "Versão não encontrada para esta atividade-base."
TEMPLATE_NOT_FOUND_MESSAGE = "Modelo não encontrado nesta versão."
FILE_REQUIRED_MESSAGE = "Selecione um arquivo .docx para enviar."
EXTENSION_MESSAGE = "Envie o modelo no formato Word (.docx)."
TOO_LARGE_MESSAGE = "O modelo excede o limite de 4 MiB."
TOO_MANY_MESSAGE = f"Cada versão pode ter no máximo {MAX_ACTIVE_TEMPLATES_PER_VERSION} modelos."
TITLE_TOO_LONG_MESSAGE = f"O título do modelo deve ter no máximo {DOCUMENT_TEMPLATE_TITLE_MAX_LENGTH} caracteres."
NO_CHANGE_MESSAGE = "Nenhuma alteração informada para o modelo."


class DocumentTemplateRefused(ValueError):
    """A refused template operation: a fixed ``code`` and a user-facing message."""

    def __init__(self, code: str, user_message: str):
        super().__init__(code)
        self.code = code
        self.user_message = user_message


@dataclass(frozen=True)
class TemplateUpload:
    """A validated DOCX: its download name and its bytes (never logged)."""

    filename: str
    content: bytes

    def __repr__(self) -> str:
        return f"TemplateUpload(filename={self.filename!r}, size={len(self.content)})"


# ---------------------------------------------------------------- input


def _download_name(raw) -> str:
    """The original base name, kept readable (accents included) but inert."""
    name = str(raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(ch for ch in unicodedata.normalize("NFC", name) if unicodedata.category(ch)[0] != "C")
    name = re.sub(r'[<>:"|?*]', "", " ".join(name.split())).strip(" .")
    stem = name[:-5] if name.lower().endswith(".docx") else name
    stem = stem[: DOCUMENT_TEMPLATE_FILENAME_MAX_LENGTH - 5].strip(" .") or "modelo"
    return f"{stem}.docx"


def read_template_upload(file_storage) -> TemplateUpload:
    """Read one uploaded file (bounded) and prove it is a plain DOCX document."""
    original = str(getattr(file_storage, "filename", "") or "").strip()
    if file_storage is None or not original:
        raise DocumentTemplateRefused("FILE_REQUIRED", FILE_REQUIRED_MESSAGE)
    if not original.lower().endswith(".docx"):
        raise DocumentTemplateRefused("EXTENSION", EXTENSION_MESSAGE)
    stream = getattr(file_storage, "stream", file_storage)
    content = stream.read(DOCUMENT_TEMPLATE_MAX_BYTES + 1)
    if len(content) > DOCUMENT_TEMPLATE_MAX_BYTES:
        raise DocumentTemplateRefused("FILE_TOO_LARGE", TOO_LARGE_MESSAGE)
    if not content:
        raise DocumentTemplateRefused("FILE_EMPTY", FILE_REQUIRED_MESSAGE)
    try:
        validate_docx(content)
    except DocxRejected as exc:
        raise DocumentTemplateRefused(exc.code, exc.user_message) from None
    return TemplateUpload(filename=_download_name(original), content=content)


def normalize_template_title(raw, *, fallback_filename: str | None = None) -> str:
    """The trimmed title; a blank one becomes the file name without extension."""
    title = " ".join(str(raw or "").split())
    if not title and fallback_filename:
        title = fallback_filename[:-5] if fallback_filename.lower().endswith(".docx") else fallback_filename
        title = " ".join(title.split())[:DOCUMENT_TEMPLATE_TITLE_MAX_LENGTH].strip()
    if len(title) > DOCUMENT_TEMPLATE_TITLE_MAX_LENGTH:
        raise DocumentTemplateRefused("TITLE_TOO_LONG", TITLE_TOO_LONG_MESSAGE)
    return title


# ---------------------------------------------------------------- writes


def _require_mutable_version(conn, *, base_id: int, versao_id: int):
    """Lock order: the base, then the version row; then re-read and re-check."""
    lock_activity_base(conn, base_id)
    lock_activity_version(conn, versao_id)
    version = conn.execute(
        "SELECT id, atividade_base_id, status FROM atividade_versao WHERE id = ? AND atividade_base_id = ?",
        (int(versao_id), int(base_id)),
    ).fetchone()
    if version is None:
        raise DocumentTemplateRefused("VERSION_NOT_FOUND", VERSION_NOT_FOUND_MESSAGE)
    if not can_activity_version_be_mutated_in_place(conn, int(versao_id)):
        raise DocumentTemplateRefused("VERSION_FROZEN", FROZEN_MESSAGE)
    return version


def _store_content(conn, content: bytes) -> int:
    digest = hashlib.sha256(content).hexdigest()
    row = conn.execute(
        "INSERT INTO modelo_documento_arquivos (sha256, mime_type, size_bytes, conteudo) VALUES (?, ?, ?, ?)"
        " ON CONFLICT (sha256) DO NOTHING RETURNING id",
        (digest, DOCX_MIME_TYPE, len(content), content),
    ).fetchone()
    if row is not None:
        return int(row[0])
    return int(conn.execute("SELECT id FROM modelo_documento_arquivos WHERE sha256 = ?", (digest,)).fetchone()[0])


def _active_row(conn, *, versao_id: int, modelo_id: int):
    row = conn.execute(
        "SELECT * FROM atividade_versao_modelos WHERE id = ? AND atividade_versao_id = ? AND status = 'ativo'",
        (int(modelo_id), int(versao_id)),
    ).fetchone()
    if row is None:
        raise DocumentTemplateRefused("TEMPLATE_NOT_FOUND", TEMPLATE_NOT_FOUND_MESSAGE)
    return row


def add_template(conn, *, base_id: int, versao_id: int, titulo, upload: TemplateUpload, actor_user_id: int) -> int:
    """Attach a new template to a draft version, in the next free slot."""
    title = normalize_template_title(titulo, fallback_filename=upload.filename)
    with write_transaction(conn):
        _require_mutable_version(conn, base_id=base_id, versao_id=versao_id)
        active = conn.execute(
            "SELECT count(*) FROM atividade_versao_modelos WHERE atividade_versao_id = ? AND status = 'ativo'",
            (int(versao_id),),
        ).fetchone()[0]
        if int(active) >= MAX_ACTIVE_TEMPLATES_PER_VERSION:
            raise DocumentTemplateRefused("TOO_MANY_TEMPLATES", TOO_MANY_MESSAGE)
        slot = conn.execute(
            "SELECT COALESCE(MAX(ordem), 0) + 1 FROM atividade_versao_modelos WHERE atividade_versao_id = ?",
            (int(versao_id),),
        ).fetchone()[0]
        content_id = _store_content(conn, upload.content)
        return int(
            conn.execute(
                "INSERT INTO atividade_versao_modelos (atividade_versao_id, arquivo_id, titulo, nome_arquivo,"
                " ordem, criado_por_usuario_id) VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
                (int(versao_id), content_id, title, upload.filename, int(slot), int(actor_user_id)),
            ).fetchone()[0]
        )


def _end(conn, row, *, status: str, actor_user_id: int) -> None:
    conn.execute(
        f"UPDATE atividade_versao_modelos SET status = ?, encerrado_em = {current_utc_text(conn)},"
        " encerrado_por_usuario_id = ? WHERE id = ? AND status = 'ativo'",
        (status, int(actor_user_id), int(row["id"])),
    )


def update_template(
    conn, *, base_id: int, versao_id: int, modelo_id: int, titulo, upload: TemplateUpload | None,
    actor_user_id: int,
) -> int:
    """Replace a draft's template file and/or title; the old association ends ``substituido``.

    The replacement keeps the slot.  Returns the new association id; refuses a
    request that changes nothing.
    """
    with write_transaction(conn):
        _require_mutable_version(conn, base_id=base_id, versao_id=versao_id)
        row = _active_row(conn, versao_id=versao_id, modelo_id=modelo_id)
        title = normalize_template_title(titulo) or row["titulo"]
        content_id = _store_content(conn, upload.content) if upload is not None else int(row["arquivo_id"])
        filename = upload.filename if upload is not None else row["nome_arquivo"]
        if (title, content_id, filename) == (row["titulo"], int(row["arquivo_id"]), row["nome_arquivo"]):
            raise DocumentTemplateRefused("NO_CHANGE", NO_CHANGE_MESSAGE)
        _end(conn, row, status="substituido", actor_user_id=actor_user_id)
        return int(
            conn.execute(
                "INSERT INTO atividade_versao_modelos (atividade_versao_id, arquivo_id, titulo, nome_arquivo,"
                " ordem, criado_por_usuario_id) VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
                (int(versao_id), content_id, title, filename, int(row["ordem"]), int(actor_user_id)),
            ).fetchone()[0]
        )


def retire_template(conn, *, base_id: int, versao_id: int, modelo_id: int, actor_user_id: int) -> None:
    """Withdraw a draft's template (``retirado``); its bytes and history stay."""
    with write_transaction(conn):
        _require_mutable_version(conn, base_id=base_id, versao_id=versao_id)
        _end(conn, _active_row(conn, versao_id=versao_id, modelo_id=modelo_id), status="retirado",
             actor_user_id=actor_user_id)


def copy_active_templates(conn, *, from_versao_id: int, to_versao_id: int) -> int:
    """Give a NEW version its source's active templates; the caller owns the transaction.

    Called only for a version created in the same transaction, so the target
    has no template yet.  Slots, titles, names and contents are copied; the
    creator stamp is the source's, because nobody uploaded anything new.
    """
    cursor = conn.execute(
        "INSERT INTO atividade_versao_modelos (atividade_versao_id, arquivo_id, titulo, nome_arquivo, ordem,"
        " criado_por_usuario_id)"
        " SELECT ?, arquivo_id, titulo, nome_arquivo, ordem, criado_por_usuario_id"
        " FROM atividade_versao_modelos WHERE atividade_versao_id = ? AND status = 'ativo' ORDER BY ordem, id",
        (int(to_versao_id), int(from_versao_id)),
    )
    return int(cursor.rowcount or 0)


# ---------------------------------------------------------------- reads

_LIST_COLUMNS = (
    "m.id, m.atividade_versao_id, m.titulo, m.nome_arquivo, m.ordem, m.status, m.criado_em,"
    " m.encerrado_em, a.size_bytes, a.sha256"
)


def _as_dict(row) -> dict:
    return {key: row[key] for key in row.keys()}


def _listed(row) -> dict:
    item = _as_dict(row)
    item["tamanho_label"] = _format_bytes_label(item["size_bytes"])
    item["encerrado_em_label"] = format_date_ptbr(item["encerrado_em"]) if item["encerrado_em"] else ""
    return item


def list_version_templates(conn, versao_id: int, *, include_ended: bool = False) -> list[dict]:
    """A version's templates in slot order (ended ones too when asked), without bytes."""
    status = "" if include_ended else " AND m.status = 'ativo'"
    rows = conn.execute(
        f"SELECT {_LIST_COLUMNS} FROM atividade_versao_modelos m"
        " JOIN modelo_documento_arquivos a ON a.id = m.arquivo_id"
        f" WHERE m.atividade_versao_id = ?{status} ORDER BY m.ordem, m.id",
        (int(versao_id),),
    ).fetchall()
    return [_listed(row) for row in rows]


def read_template_file(conn, modelo_id: int):
    """The association with its bytes (any status), or None."""
    row = conn.execute(
        "SELECT m.id, m.atividade_versao_id, m.titulo, m.nome_arquivo, m.status, v.atividade_base_id,"
        " a.mime_type, a.size_bytes, a.sha256, a.conteudo"
        " FROM atividade_versao_modelos m"
        " JOIN modelo_documento_arquivos a ON a.id = m.arquivo_id"
        " JOIN atividade_versao v ON v.id = m.atividade_versao_id"
        " WHERE m.id = ?",
        (int(modelo_id),),
    ).fetchone()
    if row is None:
        return None
    item = _as_dict(row)
    item["conteudo"] = bytes(item["conteudo"])
    return item


def template_download_response(template):
    """A private, never-cached attachment response for one authorized template."""
    response = send_file(
        io.BytesIO(template["conteudo"]),
        mimetype=DOCX_MIME_TYPE,
        as_attachment=True,
        download_name=template["nome_arquivo"],
        conditional=False,
        etag=False,
        max_age=0,
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "private, no-store"
    return response


__all__ = [
    "DocumentTemplateRefused",
    "FROZEN_MESSAGE",
    "MAX_ACTIVE_TEMPLATES_PER_VERSION",
    "TEMPLATE_FILE_FIELD",
    "TEMPLATE_TITLE_FIELD",
    "TemplateUpload",
    "add_template",
    "copy_active_templates",
    "list_version_templates",
    "normalize_template_title",
    "read_template_file",
    "read_template_upload",
    "retire_template",
    "template_download_response",
    "update_template",
]
