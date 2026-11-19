"""Informative documentation of one activity version: the required-proof guidance.

An activity version carries a list of required documents ("comprovantes
exigidos") -- short texts telling the student what to attach, such as
"Certificado de participação".  The list is stored in the version's
``documentos_json`` column, a semantic field of the version
(``app.activity_catalog.ACTIVITY_VERSION_SEMANTIC_FIELDS``), so it follows the
canonical freeze policy: it is written in place only while the version is an
unreferenced draft, and a frozen version changes only through a new version.

THE RULE THIS MODULE NEVER BREAKS
    The guidance is informative.  Nothing here, or anywhere that reads it,
    inspects an uploaded proof, matches a file to a required document, blocks
    a submission or decides a request: the coordination analyses every
    request.

STORAGE FORMAT
    New writes store a JSON array of strings, in the administrator's order.
    Older rows may hold other shapes (a JSON-encoded string, a delimited
    string, placeholders such as ``NA``); ``read_required_documents`` reads all
    of them through the tolerant ``parse_documentos_json``.  A form save that
    leaves the list unchanged keeps the stored text exactly as it is
    (``documentos_json_for_write``), so opening and saving a version never
    rewrites data nobody edited.

WHAT THE STUDENT SEES
    ``student_guidance_by_version`` is the read model of the request form: for
    each version it offers, the required documents and the active DOCX
    templates (``app.activity_document_templates``) of that exact version --
    a request being edited or rectified shows its own recorded version's.
"""

from __future__ import annotations

import json

from app.activity_catalog import parse_documentos_json
from app.activity_document_templates import active_templates_by_version

REQUIRED_DOCUMENTS_FIELD = "documentos_exigidos"
#: Carried by every form that shows the list, so that a list emptied on purpose
#: (no item inputs at all) differs from a form that never showed it.
REQUIRED_DOCUMENTS_PRESENT_FIELD = "documentos_exigidos_presente"
REQUIRED_DOCUMENT_MAX_ITEMS = 20
REQUIRED_DOCUMENT_MAX_LENGTH = 300


class RequiredDocumentsInvalid(ValueError):
    """The submitted guidance list cannot be stored; the message is user-facing."""


def read_required_documents(raw) -> list[str]:
    """The guidance list of a stored ``documentos_json`` value, in order, never None."""
    return parse_documentos_json(raw)


def normalize_required_documents(values) -> list[str]:
    """The submitted items as the form compares them: whitespace collapsed,
    blank rows dropped, a repeated item kept once, the administrator's order."""
    items: list[str] = []
    for raw in values or ():
        text = " ".join(str(raw or "").split())
        if text and text not in items:
            items.append(text)
    return items


def submitted_required_documents(form, stored_raw) -> list[str]:
    """The list a version form submitted, or the stored one when the form did not carry it.

    An omitted field keeps the stored value (the form convention of the
    project): a POST without ``REQUIRED_DOCUMENTS_PRESENT_FIELD`` -- an older
    page, any client that never showed the section -- changes nothing.
    """
    if form.get(REQUIRED_DOCUMENTS_PRESENT_FIELD) is None:
        return read_required_documents(stored_raw)
    return normalize_required_documents(form.getlist(REQUIRED_DOCUMENTS_FIELD))


def parse_required_documents_form(values) -> list[str]:
    """``normalize_required_documents``, refusing what cannot be stored.

    Refuses more than ``REQUIRED_DOCUMENT_MAX_ITEMS`` items or an item longer
    than ``REQUIRED_DOCUMENT_MAX_LENGTH`` characters.
    """
    items = normalize_required_documents(values)
    if any(len(text) > REQUIRED_DOCUMENT_MAX_LENGTH for text in items):
        raise RequiredDocumentsInvalid(
            f"Cada comprovante exigido deve ter no máximo {REQUIRED_DOCUMENT_MAX_LENGTH} caracteres."
        )
    if len(items) > REQUIRED_DOCUMENT_MAX_ITEMS:
        raise RequiredDocumentsInvalid(
            f"Informe no máximo {REQUIRED_DOCUMENT_MAX_ITEMS} comprovantes exigidos."
        )
    return items


def student_guidance_by_version(conn, atividades) -> dict[int, dict]:
    """What the student is told for each listed activity version, keyed by its id.

    ``atividades`` are the version rows a request form offers (each with
    ``id`` and ``documentos_json``).  A version with neither required
    documents nor active templates is absent, so the form shows no empty
    block for it.  Each template carries what the download button shows; the
    bytes stay behind the authorized download route.
    """
    templates = active_templates_by_version(conn, [atividade["id"] for atividade in atividades])
    guidance: dict[int, dict] = {}
    for atividade in atividades:
        version_id = int(atividade["id"])
        documentos = read_required_documents(atividade.get("documentos_json"))
        modelos = [
            {
                "id": int(item["id"]),
                "titulo": item["titulo"],
                "nome_arquivo": item["nome_arquivo"],
                "tamanho": item["tamanho_label"],
            }
            for item in templates.get(version_id, [])
        ]
        if documentos or modelos:
            guidance[version_id] = {"documentos": documentos, "modelos": modelos}
    return guidance


def serialize_required_documents(items) -> str:
    """The canonical stored form: a JSON array of the items, in order."""
    return json.dumps(list(items), ensure_ascii=False)


def documentos_json_for_write(stored_raw, items) -> str:
    """The value to store for ``items`` given what the row holds now.

    An unchanged list keeps ``stored_raw`` byte for byte (a legacy shape is not
    rewritten merely because the form was saved); a changed list is stored in
    the canonical form.  A row with no stored value and no items gets ``[]``.
    """
    items = list(items)
    if stored_raw is not None and read_required_documents(stored_raw) == items:
        return stored_raw
    return serialize_required_documents(items)


__all__ = [
    "REQUIRED_DOCUMENTS_FIELD",
    "REQUIRED_DOCUMENTS_PRESENT_FIELD",
    "REQUIRED_DOCUMENT_MAX_ITEMS",
    "REQUIRED_DOCUMENT_MAX_LENGTH",
    "RequiredDocumentsInvalid",
    "documentos_json_for_write",
    "normalize_required_documents",
    "parse_required_documents_form",
    "read_required_documents",
    "serialize_required_documents",
    "student_guidance_by_version",
    "submitted_required_documents",
]
