from __future__ import annotations

import hashlib
import re

from werkzeug.utils import secure_filename

from app.storage.contracts import ComprovanteStorage


class ComprovanteHierarchyError(RuntimeError):
    code = "INVALID_REQUEST_AXIS"


def _display_component(value: object, fallback: str) -> str:
    cleaned = re.sub(r"[\x00-\x1f/\\]+", "-", str(value or "")).strip(" .-")
    return (cleaned or fallback)[:120]


def _filename_component(value: object, fallback: str) -> str:
    cleaned = secure_filename(str(value or ""))
    cleaned = re.sub(r"_+", "-", cleaned).strip(".-_")
    return (cleaned or fallback)[:80]


def stored_filename(request_id: int, snapshot_payload: dict, item) -> str:
    activity = _filename_component(snapshot_payload.get("nome_exibivel"), "Atividade")
    version = int(snapshot_payload["atividade_versao_numero"])
    timestamp = item.uploaded_at.replace("T", "_").replace(":", "-").removesuffix("Z")
    suffix = hashlib.sha256(item.operation_key.encode("utf-8")).hexdigest()[:8]
    return (
        f"REQ-{int(request_id):06d}__{activity}__v{version}__"
        f"{timestamp}__{suffix}.{item.extension}"
    )


def ensure_request_hierarchy(
    storage: ComprovanteStorage,
    *,
    request_row,
    snapshot_payload: dict,
    turma_id: int,
    turma_code: str,
) -> str:
    parent = storage.ensure_folder(
        parent_id="root", kind="product_root", semantic_id="sgaa", display_name="SGAA"
    )
    parent = storage.ensure_folder(
        parent_id=parent,
        kind="domain_root",
        semantic_id="comprovantes",
        display_name="COMPROVANTES",
    )
    parent = storage.ensure_folder(
        parent_id=parent,
        kind="turma",
        semantic_id=str(turma_id),
        display_name=_display_component(turma_code, f"Turma {turma_id}"),
    )
    axis = str(snapshot_payload.get("eixo") or "").upper()
    if axis not in {"AAC", "AEU"}:
        raise ComprovanteHierarchyError(
            "O eixo histórico da requisição está indisponível."
        )
    parent = storage.ensure_folder(
        parent_id=parent, kind="request_axis", semantic_id=axis, display_name=axis
    )
    student_id = int(request_row["aluno_id"])
    student_display = " - ".join(
        (
            _display_component(request_row["aluno_matricula"], f"Aluno {student_id}"),
            _display_component(request_row["aluno_nome"], f"Aluno {student_id}"),
        )
    )
    return storage.ensure_folder(
        parent_id=parent,
        kind="student",
        semantic_id=str(student_id),
        display_name=student_display,
    )


__all__ = ["ComprovanteHierarchyError", "ensure_request_hierarchy", "stored_filename"]
