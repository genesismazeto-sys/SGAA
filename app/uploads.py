from __future__ import annotations

import datetime
import os
import secrets

from flask import current_app
from werkzeug.utils import secure_filename


ALLOWED_ATTACHMENTS = {"pdf", "png", "jpg", "jpeg"}
ALLOWED_CSV = {"csv"}
ALLOWED_REPORTE_SCREENSHOTS = {"png", "jpg", "jpeg", "webp"}
_UPLOAD_PATH_ERROR = "Caminho de upload inválido."


def _allowed(filename: str, allowed: set[str]) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed


def _unique_filename(original_name: str, prefix: str = "") -> str:
    base = secure_filename(original_name)
    name, ext = os.path.splitext(base)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    rnd = secrets.token_hex(4)
    if prefix:
        prefix = secure_filename(prefix)
        return f"{prefix}-{ts}-{rnd}-{name}{ext}"
    return f"{ts}-{rnd}-{name}{ext}"


def save_upload(
    file_storage,
    allowed: set[str],
    prefix: str = "",
    subdir: str | None = None,
) -> str | None:
    """Save an upload below the configured upload root and return its relative path."""
    if not file_storage or not getattr(file_storage, "filename", None):
        return None
    fname = file_storage.filename
    if not _allowed(fname, allowed):
        raise ValueError("Extensão de arquivo não permitida.")
    final_name = _unique_filename(fname, prefix=prefix)
    rel_path = final_name
    if subdir:
        safe_subdir = os.path.normpath(subdir).lstrip(os.sep).replace("..", "")
        rel_path = os.path.join(safe_subdir, final_name)
    upload_root = os.path.abspath(current_app.config["UPLOAD_FOLDER"])
    path = os.path.abspath(os.path.join(upload_root, rel_path))
    try:
        is_contained = os.path.commonpath((upload_root, path)) == upload_root
    except ValueError:
        is_contained = False
    if not is_contained:
        raise ValueError(_UPLOAD_PATH_ERROR)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    file_storage.save(path)
    return rel_path


__all__ = [
    "ALLOWED_ATTACHMENTS",
    "ALLOWED_CSV",
    "ALLOWED_REPORTE_SCREENSHOTS",
    "_allowed",
    "_unique_filename",
    "save_upload",
]
