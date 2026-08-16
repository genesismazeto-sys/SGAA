from __future__ import annotations

import datetime
import os
import re
import secrets
from typing import Final

from unidecode import unidecode
from werkzeug.utils import secure_filename


STUDENT_DOCUMENT_CATEGORIES: Final[set[str]] = {"requisicoes", "perfil", "reportes"}


def _is_allowed_extension(filename: str, allowed: set[str]) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed


def slugify_student_name(student_name: str) -> str:
    normalized = unidecode(str(student_name or "")).lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return normalized or "sem-nome"


def normalize_student_document_category(category: str) -> str:
    normalized = str(category or "").strip().lower()
    if normalized not in STUDENT_DOCUMENT_CATEGORIES:
        raise ValueError("Categoria de documento do aluno invalida.")
    return normalized


def build_student_documents_dirname(student_id: int, student_name: str) -> str:
    return f"aluno_{int(student_id)} - {slugify_student_name(student_name)}"


def build_student_documents_rel_dir(student_id: int, student_name: str, category: str) -> str:
    safe_category = normalize_student_document_category(category)
    return "/".join((build_student_documents_dirname(student_id, student_name), safe_category))


def sanitize_student_document_relpath(rel_path: str) -> str:
    raw_value = str(rel_path or "")
    if not raw_value.strip():
        raise ValueError("Caminho relativo do documento do aluno ausente.")
    if os.path.isabs(raw_value):
        raise ValueError("Caminho absoluto nao permitido para documento do aluno.")

    normalized = os.path.normpath(raw_value).replace("\\", "/").lstrip("/")
    parts = normalized.split("/")
    if normalized in {"", ".", ".."} or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("Caminho relativo invalido para documento do aluno.")
    return normalized


def resolve_student_document_path(root_folder: str, rel_path: str) -> str:
    root_abs = os.path.abspath(str(root_folder or ""))
    if not root_abs:
        raise ValueError("Root de documentos do aluno nao configurado.")

    safe_rel = sanitize_student_document_relpath(rel_path)
    candidate_abs = os.path.abspath(os.path.join(root_abs, safe_rel))
    try:
        if os.path.commonpath([candidate_abs, root_abs]) != root_abs:
            raise ValueError("Documento do aluno fora do root permitido.")
    except ValueError as exc:
        raise ValueError("Documento do aluno fora do root permitido.") from exc
    return candidate_abs


def remove_student_document(root_folder: str, rel_path: str) -> None:
    """Remove one confined student document, tolerating an absent file."""
    abs_path = resolve_student_document_path(root_folder, rel_path)
    try:
        os.remove(abs_path)
    except FileNotFoundError:
        return


def sanitize_student_document_filename(
    original_name: str,
    *,
    prefix: str = "",
    stem: str = "",
) -> str:
    safe_name = secure_filename(str(original_name or ""))
    if not safe_name:
        raise ValueError("Nome de arquivo invalido.")

    base_name, extension = os.path.splitext(safe_name)
    parts = [secure_filename(prefix).strip("-_") if prefix else ""]
    if stem:
        parts.append(secure_filename(stem).strip("-_") or "")
    parts.append(base_name or "arquivo")
    filename_base = "-".join(part for part in parts if part)
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    token = secrets.token_hex(4)
    return f"{filename_base}-{timestamp}-{token}{extension.lower()}"


def save_student_document(
    file_storage,
    allowed: set[str],
    *,
    root_folder: str,
    student_id: int,
    student_name: str,
    category: str,
    prefix: str = "",
    stem: str = "",
) -> str | None:
    if not file_storage or not getattr(file_storage, "filename", None):
        return None

    original_name = str(file_storage.filename or "")
    if not _is_allowed_extension(original_name, allowed):
        raise ValueError("Extensao de arquivo nao permitida.")

    rel_dir = build_student_documents_rel_dir(student_id, student_name, category)
    final_name = sanitize_student_document_filename(
        original_name,
        prefix=prefix,
        stem=stem,
    )
    rel_path = "/".join((rel_dir, final_name))
    abs_path = resolve_student_document_path(root_folder, rel_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    try:
        file_storage.save(abs_path)
    except Exception:
        try:
            os.remove(abs_path)
        except FileNotFoundError:
            pass
        raise
    return rel_path
