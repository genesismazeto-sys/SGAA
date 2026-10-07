"""Canonical prod-1/v13 database-backed image schema objects.

v13 adds three one-to-one side tables that hold the small application-owned
images as database content instead of files under an upload root:

    usuarios_foto     administrator profile photo   (owner usuarios.id)
    alunos_foto       student profile photo          (owner alunos.id)
    reportes_captura  report screenshot              (owner reportes.id)

THE CONTRACT
    One row per owner (the owner id is the primary key) and the row dies with
    its owner (``ON DELETE CASCADE``).  Each row carries the verified image
    bytes plus the metadata the application serves them with: the detected
    MIME type, the byte length, the lowercase hex SHA-256 of the bytes (the
    HTTP validator) and the pixel geometry.  The CHECK constraints pin what
    ``app.image_validation`` guarantees, so a row the validator never produced
    cannot be stored:

    * ``size_bytes`` is positive, within the category's stored cap, and equal
      to the length of ``conteudo``;
    * ``sha256`` is exactly 64 lowercase hexadecimal characters;
    * ``width`` / ``height`` are positive; a profile photo is normalized to at
      most 512 px on each side;
    * ``mime_type`` is one of the formats the category stores (profile photos
      are re-encoded to JPEG or PNG; screenshots keep PNG, JPEG or WEBP).

    The legacy path columns ``usuarios.foto_perfil``, ``alunos.foto_perfil``
    and ``reportes.screenshot_filename`` are NOT removed here: v13 is purely
    additive.  New writes never fill them again; a later normalization step
    retires them once no installation still references a file.

    The PostgreSQL authority (``app.pg_schema``) declares the same logical
    tables with ``bytea`` and equivalent constraints.
"""

from __future__ import annotations


PROFILE_PHOTO_MAX_STORED_BYTES = 1024 * 1024
PROFILE_PHOTO_MAX_EDGE = 512
REPORT_SCREENSHOT_MAX_BYTES = 4 * 1024 * 1024
REPORT_SCREENSHOT_MAX_EDGE = 20000

PROFILE_PHOTO_MIME_TYPES = ("image/jpeg", "image/png")
REPORT_SCREENSHOT_MIME_TYPES = ("image/jpeg", "image/png", "image/webp")


def _mime_list(mime_types) -> str:
    return ",".join(f"'{mime}'" for mime in mime_types)


def _image_table_sql(table, owner_column, owner_table, mime_types, max_bytes, max_edge) -> str:
    return f"""CREATE TABLE {table} (
 {owner_column} INTEGER PRIMARY KEY,
 mime_type TEXT NOT NULL CHECK(mime_type IN ({_mime_list(mime_types)})),
 size_bytes INTEGER NOT NULL CHECK(size_bytes>0 AND size_bytes<={max_bytes}),
 sha256 TEXT NOT NULL CHECK(length(sha256)=64 AND sha256 NOT GLOB '*[^0-9a-f]*'),
 width INTEGER NOT NULL CHECK(width>0 AND width<={max_edge}),
 height INTEGER NOT NULL CHECK(height>0 AND height<={max_edge}),
 conteudo BLOB NOT NULL CHECK(typeof(conteudo)='blob' AND length(conteudo)=size_bytes),
 atualizado_em TEXT NOT NULL DEFAULT (datetime('now')),
 FOREIGN KEY({owner_column}) REFERENCES {owner_table}(id) ON DELETE CASCADE ON UPDATE CASCADE
)"""


USUARIOS_FOTO_V13_TABLE_SQL = _image_table_sql(
    "usuarios_foto", "usuario_id", "usuarios",
    PROFILE_PHOTO_MIME_TYPES, PROFILE_PHOTO_MAX_STORED_BYTES, PROFILE_PHOTO_MAX_EDGE,
)
ALUNOS_FOTO_V13_TABLE_SQL = _image_table_sql(
    "alunos_foto", "aluno_id", "alunos",
    PROFILE_PHOTO_MIME_TYPES, PROFILE_PHOTO_MAX_STORED_BYTES, PROFILE_PHOTO_MAX_EDGE,
)
REPORTES_CAPTURA_V13_TABLE_SQL = _image_table_sql(
    "reportes_captura", "reporte_id", "reportes",
    REPORT_SCREENSHOT_MIME_TYPES, REPORT_SCREENSHOT_MAX_BYTES, REPORT_SCREENSHOT_MAX_EDGE,
)

IMAGES_V13_TABLES = ("usuarios_foto", "alunos_foto", "reportes_captura")
IMAGES_V13_TABLE_SQL = (
    USUARIOS_FOTO_V13_TABLE_SQL,
    ALUNOS_FOTO_V13_TABLE_SQL,
    REPORTES_CAPTURA_V13_TABLE_SQL,
)
IMAGES_V13_SCHEMA_OBJECTS_SQL = ";\n".join(IMAGES_V13_TABLE_SQL)


__all__ = [
    "ALUNOS_FOTO_V13_TABLE_SQL",
    "IMAGES_V13_SCHEMA_OBJECTS_SQL",
    "IMAGES_V13_TABLES",
    "IMAGES_V13_TABLE_SQL",
    "PROFILE_PHOTO_MAX_EDGE",
    "PROFILE_PHOTO_MAX_STORED_BYTES",
    "PROFILE_PHOTO_MIME_TYPES",
    "REPORTES_CAPTURA_V13_TABLE_SQL",
    "REPORT_SCREENSHOT_MAX_BYTES",
    "REPORT_SCREENSHOT_MAX_EDGE",
    "REPORT_SCREENSHOT_MIME_TYPES",
    "USUARIOS_FOTO_V13_TABLE_SQL",
]
