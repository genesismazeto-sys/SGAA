"""Informative documentation of one activity version: the required proofs.

An activity version carries a list of required proofs ("comprovantes
exigidos"): short names such as "Certificado de participação".  The list lives in the version's ``documentos_json`` column,
a semantic field of the version (``app.activity_catalog``), so it follows the
canonical freeze policy: it is written in place only while the version is an
unreferenced draft, and a frozen version changes only through a new version.

THE RULE THIS MODULE NEVER BREAKS
    The guidance is informative.  Nothing here, or anywhere that reads it,
    inspects an uploaded proof, matches a file to a required document, blocks
    a submission or decides a request: the coordination analyses every
    request.

STORAGE FORMAT
    The list is ``{"comprovantes_exigidos": [...]}``, written only by the
    version form.  Every other value the column holds -- the regulation's
    validation sentence each version carried before this feature -- is not a
    proof name: it is never shown and never rewritten while the list stays
    empty, and the first save of a list keeps it under ``"texto_anterior"``.
    Nothing already stored is lost.
"""

from __future__ import annotations

import json

from app.activity_document_templates import active_templates_by_version

REQUIRED_DOCUMENTS_FIELD = "documentos_exigidos"
#: Carried by every form that shows the list, so that a list emptied on purpose
#: (no item inputs at all) differs from a form that never showed it.
REQUIRED_DOCUMENTS_PRESENT_FIELD = "documentos_exigidos_presente"
REQUIRED_DOCUMENT_MAX_ITEMS = 20
#: A proof name, never a sentence.
REQUIRED_DOCUMENT_MAX_LENGTH = 60
LIST_KEY = "comprovantes_exigidos"
PREVIOUS_KEY = "texto_anterior"


class RequiredDocumentsInvalid(ValueError):
    """The submitted list cannot be stored; the message is user-facing."""


def _decode(raw):
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw


def normalize_required_documents(values) -> list[str]:
    """Whitespace collapsed, blank rows dropped, a repeat kept once, the given order."""
    items: list[str] = []
    for raw in values or ():
        text = " ".join(str(raw or "").split())
        if text and text not in items:
            items.append(text)
    return items


def read_required_documents(raw) -> list[str]:
    """The required proofs of a stored ``documentos_json`` value; [] for anything else."""
    value = _decode(raw)
    if isinstance(value, dict) and isinstance(value.get(LIST_KEY), list):
        return normalize_required_documents(item for item in value[LIST_KEY] if isinstance(item, str))
    return []


def submitted_required_documents(form, stored_raw) -> list[str]:
    """The list a version form submitted, or the stored one when the form did not carry it."""
    if form.get(REQUIRED_DOCUMENTS_PRESENT_FIELD) is None:
        return read_required_documents(stored_raw)
    return normalize_required_documents(form.getlist(REQUIRED_DOCUMENTS_FIELD))


def parse_required_documents_form(values) -> list[str]:
    """``normalize_required_documents``, refusing what cannot be stored."""
    items = normalize_required_documents(values)
    if any(len(text) > REQUIRED_DOCUMENT_MAX_LENGTH for text in items):
        raise RequiredDocumentsInvalid(f"Use até {REQUIRED_DOCUMENT_MAX_LENGTH} caracteres por comprovante.")
    if len(items) > REQUIRED_DOCUMENT_MAX_ITEMS:
        raise RequiredDocumentsInvalid(f"Use até {REQUIRED_DOCUMENT_MAX_ITEMS} comprovantes.")
    return items


def documentos_json_for_write(stored_raw, items) -> str:
    """The value to store for ``items`` given what the row holds now.

    An unchanged list keeps ``stored_raw`` exactly (so the older text of a
    version nobody edited is not touched); a changed list is stored in the
    list format, carrying the older text under ``PREVIOUS_KEY``.
    """
    items = list(items)
    if read_required_documents(stored_raw) == items:
        return stored_raw if stored_raw is not None else "[]"
    value: dict = {LIST_KEY: items}
    previous = _decode(stored_raw)
    if isinstance(previous, dict):
        if PREVIOUS_KEY in previous:
            value[PREVIOUS_KEY] = previous[PREVIOUS_KEY]
    elif previous not in (None, "", []):
        value[PREVIOUS_KEY] = previous
    return json.dumps(value, ensure_ascii=False)


def student_guidance_by_version(conn, atividades) -> dict[int, dict]:
    """The proofs and active templates of each listed version, keyed by its id.

    A version with neither is absent, so the request form shows no empty block.
    """
    templates = active_templates_by_version(conn, [atividade["id"] for atividade in atividades])
    guidance: dict[int, dict] = {}
    for atividade in atividades:
        version_id = int(atividade["id"])
        documentos = read_required_documents(atividade.get("documentos_json"))
        modelos = [{"id": int(item["id"]), "titulo": item["titulo"]} for item in templates.get(version_id, [])]
        if documentos or modelos:
            guidance[version_id] = {"documentos": documentos, "modelos": modelos}
    return guidance


__all__ = [
    "LIST_KEY",
    "PREVIOUS_KEY",
    "REQUIRED_DOCUMENTS_FIELD",
    "REQUIRED_DOCUMENTS_PRESENT_FIELD",
    "REQUIRED_DOCUMENT_MAX_ITEMS",
    "REQUIRED_DOCUMENT_MAX_LENGTH",
    "RequiredDocumentsInvalid",
    "documentos_json_for_write",
    "normalize_required_documents",
    "parse_required_documents_form",
    "read_required_documents",
    "student_guidance_by_version",
    "submitted_required_documents",
]
