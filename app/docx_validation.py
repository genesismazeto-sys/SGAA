"""Structural validation of an uploaded DOCX fill-in template.

``validate_docx`` decides from the bytes alone -- never from the file name or
a browser-declared type -- whether a file is a plain Word document an
administrator may offer students to download.  It accepts exactly an Office
Open XML WordprocessingML *document* package and refuses:

* anything that is not a ZIP package (an executable, an old binary ``.doc``,
  an encrypted Office file, a PDF renamed ``.docx``);
* a damaged package (bad CRC, truncated entry), an encrypted entry, an
  unsafe or duplicated entry name, and an archive whose declared sizes make
  it a decompression bomb;
* macro-enabled or template packages (``.docm``, ``.dotx``, ``.dotm``): the
  main part must be the plain document content type;
* active content: VBA projects, ActiveX controls, embedded OLE objects and
  any embedded executable, by part name, by content type and by the bytes of
  every entry;
* external relationships other than hyperlinks, except the ``attachedTemplate``
  Word records for a document made from a template on the author's own
  machine (a local ``file:///X:/...`` path): a template on the network --
  http(s), ftp, a UNC share -- is the classic way to pull macros into a
  clean document, and is refused;
* an XML part that declares a DTD or entities (OOXML never does; refusing
  them keeps entity expansion out of this parser and of any later reader).

Every refusal carries a fixed code and a user message in Portuguese.  The
caller has already bounded the size of the bytes it read.
"""

from __future__ import annotations

import io
import posixpath
import re
import zipfile
import zlib
from xml.etree import ElementTree

ZIP_LOCAL_HEADER = b"PK\x03\x04"
DOCUMENT_MAIN_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
)
OFFICE_DOCUMENT_RELATIONSHIP = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
)
HYPERLINK_RELATIONSHIP = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"
)
ATTACHED_TEMPLATE_RELATIONSHIP = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/attachedTemplate"
)
#: A path on the author's own machine: ``file:///C:/...`` or ``C:\...``.
_LOCAL_TEMPLATE_TARGET = re.compile(r"^(?:file:///)?[A-Za-z]:[\\/]", re.IGNORECASE)
MAX_ENTRIES = 1000
MAX_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
MAX_ENTRY_RATIO = 200
MAX_XML_PART_BYTES = 8 * 1024 * 1024

_CONTENT_TYPES_NS = "{http://schemas.openxmlformats.org/package/2006/content-types}"
_RELATIONSHIPS_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_FORBIDDEN_TYPE_MARKERS = ("macroenabled", "vbaproject", "vbadata", "activex", "oleobject", ".template.")
_FORBIDDEN_PART = re.compile(
    r"(?:^|/)(?:vbaProject\.bin|vbaData\.xml|vbaProjectSignature\.bin)$"
    r"|(?:^|/)(?:activeX|embeddings)/"
    r"|\.(?:exe|dll|com|bat|cmd|scr|msi|js|jse|vbs|vbe|wsf|ps1|jar|hta|lnk|cpl)$",
    re.IGNORECASE,
)
#: Binary parts a plain Word document legitimately carries.
_ALLOWED_BINARY_PART = re.compile(r"^word/printerSettings/printerSettings\d+\.bin$")
_EXECUTABLE_SIGNATURES = (b"MZ", b"\x7fELF", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"#!")

NOT_DOCX_MESSAGE = "O arquivo enviado não é um documento Word (.docx) válido."
DAMAGED_MESSAGE = "O arquivo .docx está corrompido ou incompleto."
MACRO_MESSAGE = (
    "O modelo contém macros, controles, objetos incorporados ou conteúdo executável, "
    "que não são aceitos. Salve-o como Documento do Word (.docx) sem macros e envie novamente."
)
EXTERNAL_MESSAGE = (
    "O modelo aponta para um modelo ou objeto externo, o que não é aceito. "
    "Salve-o como Documento do Word (.docx) e envie novamente."
)


class DocxRejected(ValueError):
    """A refused template file: a fixed ``code`` and a user-facing message."""

    def __init__(self, code: str, user_message: str):
        super().__init__(code)
        self.code = code
        self.user_message = user_message


def _safe_name(name: str) -> bool:
    if not name or "\\" in name or name.startswith("/") or "\x00" in name:
        return False
    if re.match(r"^[A-Za-z]:", name):
        return False
    parts = name.split("/")
    return ".." not in parts and posixpath.normpath(name).lstrip("./") != ""


def _declares_dtd(data: bytes) -> bool:
    lowered = data.lower()
    return b"<!doctype" in lowered or b"<!entity" in lowered


def _parse_xml(data: bytes):
    try:
        return ElementTree.fromstring(data)
    except ElementTree.ParseError:
        raise DocxRejected("XML_MALFORMED", DAMAGED_MESSAGE) from None


def _relationship_parts(names) -> list[str]:
    return [name for name in names if name.endswith(".rels") and "/_rels/" in f"/{name}"]


def validate_docx(content: bytes) -> None:
    """Return when ``content`` is a plain DOCX document; raise ``DocxRejected`` otherwise."""
    if not content.startswith(ZIP_LOCAL_HEADER):
        raise DocxRejected("NOT_ZIP", NOT_DOCX_MESSAGE)
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except (zipfile.BadZipFile, zipfile.LargeZipFile, ValueError, OSError):
        raise DocxRejected("ZIP_INVALID", DAMAGED_MESSAGE) from None
    with archive:
        infos = archive.infolist()
        if not infos or len(infos) > MAX_ENTRIES:
            raise DocxRejected("ZIP_ENTRIES", NOT_DOCX_MESSAGE)
        names = [info.filename for info in infos]
        if len(set(names)) != len(names) or not all(_safe_name(name) for name in names):
            raise DocxRejected("ZIP_NAMES", NOT_DOCX_MESSAGE)
        if sum(info.file_size for info in infos) > MAX_UNCOMPRESSED_BYTES:
            raise DocxRejected("ZIP_BOMB", NOT_DOCX_MESSAGE)
        for info in infos:
            if info.flag_bits & 0x1:
                raise DocxRejected("ZIP_ENCRYPTED", NOT_DOCX_MESSAGE)
            if info.file_size > 1024 * 1024 and info.file_size > MAX_ENTRY_RATIO * max(info.compress_size, 1):
                raise DocxRejected("ZIP_BOMB", NOT_DOCX_MESSAGE)
            if _FORBIDDEN_PART.search(info.filename) or (
                info.filename.lower().endswith(".bin") and not _ALLOWED_BINARY_PART.match(info.filename)
            ):
                raise DocxRejected("ACTIVE_CONTENT", MACRO_MESSAGE)

        parts: dict[str, bytes] = {}
        for info in infos:
            if info.is_dir():
                continue
            try:
                # Reading to the end verifies the CRC; the declared size bounds it.
                data = archive.read(info)
            except (zipfile.BadZipFile, zlib.error, NotImplementedError, OSError, EOFError, RuntimeError):
                raise DocxRejected("ZIP_DAMAGED", DAMAGED_MESSAGE) from None
            if data.startswith(_EXECUTABLE_SIGNATURES):
                raise DocxRejected("ACTIVE_CONTENT", MACRO_MESSAGE)
            if info.filename.lower().endswith((".xml", ".rels")) and _declares_dtd(data):
                raise DocxRejected("XML_DTD", NOT_DOCX_MESSAGE)
            if info.filename == "[Content_Types].xml" or info.filename.endswith(".rels"):
                if len(data) > MAX_XML_PART_BYTES:
                    raise DocxRejected("XML_TOO_LARGE", NOT_DOCX_MESSAGE)
                parts[info.filename] = data

    if "[Content_Types].xml" not in parts or "_rels/.rels" not in parts:
        raise DocxRejected("NOT_OOXML", NOT_DOCX_MESSAGE)
    types = _parse_xml(parts["[Content_Types].xml"])
    overrides = {}
    for element in types:
        content_type = str(element.get("ContentType") or "")
        if any(marker in content_type.lower() for marker in _FORBIDDEN_TYPE_MARKERS):
            raise DocxRejected("ACTIVE_CONTENT", MACRO_MESSAGE)
        if element.tag == f"{_CONTENT_TYPES_NS}Override":
            overrides[str(element.get("PartName") or "").lstrip("/")] = content_type

    main_parts = []
    for rels_name in _relationship_parts(parts):
        for relationship in _parse_xml(parts[rels_name]):
            if relationship.tag != f"{_RELATIONSHIPS_NS}Relationship":
                continue
            kind = str(relationship.get("Type") or "")
            target = str(relationship.get("Target") or "").strip()
            if str(relationship.get("TargetMode") or "").lower() == "external" and not (
                kind == HYPERLINK_RELATIONSHIP
                or (kind == ATTACHED_TEMPLATE_RELATIONSHIP and _LOCAL_TEMPLATE_TARGET.match(target))
            ):
                raise DocxRejected("EXTERNAL_RELATIONSHIP", EXTERNAL_MESSAGE)
            if rels_name == "_rels/.rels" and kind == OFFICE_DOCUMENT_RELATIONSHIP:
                main_parts.append(str(relationship.get("Target") or "").lstrip("/"))
    if len(main_parts) != 1:
        raise DocxRejected("NOT_OOXML", NOT_DOCX_MESSAGE)
    main_part = posixpath.normpath(main_parts[0])
    if main_part not in names or overrides.get(main_part) != DOCUMENT_MAIN_CONTENT_TYPE:
        raise DocxRejected("NOT_WORD_DOCUMENT", NOT_DOCX_MESSAGE)


__all__ = [
    "DOCUMENT_MAIN_CONTENT_TYPE",
    "DocxRejected",
    "MAX_ENTRIES",
    "MAX_UNCOMPRESSED_BYTES",
    "validate_docx",
]
