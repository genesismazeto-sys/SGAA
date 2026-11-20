"""Synthetic DOCX packages for the template tests -- built in memory, no real documents.

``make_docx`` writes the smallest WordprocessingML package Word itself opens:
content types, the package relationships and one document part.  The
keyword arguments add exactly one hostile trait each, so a test can show the
validator refuses that trait and nothing else.
"""
from __future__ import annotations

import io
import zipfile

MAIN = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
MACRO_MAIN = "application/vnd.ms-word.document.macroEnabled.main+xml"
TEMPLATE_MAIN = "application/vnd.openxmlformats-officedocument.wordprocessingml.template.main+xml"
VBA_TYPE = "application/vnd.ms-office.vbaProject"

#: The fill-in annexes of the ACC rev6 regulation -- the only downloadable
#: models the Regulamento has. Fixture titles only: the bytes the tests upload
#: are synthetic documents built by ``make_docx``, never the official forms.
ANEXO_3_TITULO = "Anexo 3 — Leitura de livro/filme"
ANEXO_5_TITULO = "Anexo 5 — Atividades de monitoria, apoio institucional e visitas técnicas"


def _content_types(main_type: str, extra: str = "") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f'<Override PartName="/word/document.xml" ContentType="{main_type}"/>'
        f"{extra}</Types>"
    )


PACKAGE_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"'
    ' Target="word/document.xml"/></Relationships>'
)


def _document(text: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>"
    )


def make_docx(
    text: str = "Declaração de participação",
    *,
    main_type: str = MAIN,
    vba_project: bool = False,
    external_template: bool = False,
    template_target: str = "https://example.test/modelo.dotm",
    external_hyperlink: bool = False,
    embedded_exe: bool = False,
    doctype: bool = False,
    printer_settings: bool = False,
    padding: int = 0,
) -> bytes:
    buffer = io.BytesIO()
    extra_types = f'<Override PartName="/word/vbaProject.bin" ContentType="{VBA_TYPE}"/>' if vba_project else ""
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", _content_types(main_type, extra_types))
        package.writestr("_rels/.rels", PACKAGE_RELS)
        body = _document(text)
        if doctype:
            body = body.replace("?>", '?><!DOCTYPE w [<!ENTITY a "aaaa">]>', 1)
        package.writestr("word/document.xml", body)
        document_rels = []
        if external_template:
            document_rels.append(
                '<Relationship Id="rId9" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                f'relationships/attachedTemplate" Target="{template_target}" TargetMode="External"/>'
            )
        if external_hyperlink:
            document_rels.append(
                '<Relationship Id="rId8" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                'relationships/hyperlink" Target="https://example.test/regulamento" TargetMode="External"/>'
            )
        if document_rels:
            package.writestr(
                "word/_rels/document.xml.rels",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                + "".join(document_rels) + "</Relationships>",
            )
        if vba_project:
            package.writestr("word/vbaProject.bin", b"\xd0\xcf\x11\xe0fake-vba")
        if embedded_exe:
            package.writestr("word/media/image1.png", b"MZ\x90\x00 this is not an image")
        if printer_settings:
            package.writestr("word/printerSettings/printerSettings1.bin", b"\x00\x01printer")
        if padding:
            # A stored (uncompressed) picture part, to reach a target package size.
            package.writestr(
                "word/media/pad.png", b"\x89PNG" + bytes(range(256)) * (padding // 256),
                compress_type=zipfile.ZIP_STORED,
            )
    return buffer.getvalue()


def corrupt_crc(content: bytes) -> bytes:
    """The same package with one byte of the document part's data flipped."""
    marker = b"word/document.xml"
    index = content.index(marker) + len(marker) + 8
    damaged = bytearray(content)
    damaged[index] ^= 0xFF
    return bytes(damaged)
