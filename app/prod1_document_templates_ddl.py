"""Canonical prod-1/v19 schema objects: DOCX fill-in templates of activity versions.

v19 is purely additive: two new tables, their index and their two
immutability triggers.  No existing table, row or counter changes.

    modelo_documento_arquivos   the stored bytes of one DOCX template, content
                                addressed by SHA-256 (one row per distinct file)
    atividade_versao_modelos    the association of a template with ONE activity
                                version: the title the student sees, the file
                                name it downloads under, its position, and its
                                lifecycle (ativo -> substituido | retirado)

WHY THE DATABASE AND NOT THE CANONICAL OBJECT STORE
    The canonical store (``storage_objects``) pins request documents and
    ARQUIVOS: PDF / PNG / JPEG only, and one business row per object.  A
    template is a different contract -- a DOCX, small, written by an
    administrator, and shared by every version it is carried into -- so it
    follows the v13 precedent of application-owned content in the database
    (``app.prod1_images_ddl``) instead of widening the custody tables.  The
    bytes therefore travel with the governed PostgreSQL backup and the Path-B
    migration like every other row, and a download is always an authorized
    application response: there is no URL to the object at all.

THE CONTRACT
    * Content rows are immutable (trigger) and kept: an ended association --
      ``substituido`` or ``retirado`` -- still references its bytes, and
      ``ON DELETE RESTRICT`` refuses to delete content any association
      references, so every template ever offered still resolves.  Nothing in
      the application deletes content.  ``size_bytes`` equals the content
      length, ``sha256`` is its lowercase hex digest and is unique, the MIME
      type is the DOCX type, and the bytes start with the ZIP local-header
      signature.  What a DOCX may contain is decided by
      ``app.activity_documentation.validate_docx`` before a row is written.
    * An association belongs to exactly one version (``ON DELETE CASCADE``: a
      version that may be deleted is an unreferenced draft, and its
      associations go with it; the content stays).  Only an ``ativo`` row may
      change, and only into ``substituido`` / ``retirado`` with its end stamp;
      every identifying column is frozen from insertion (trigger).
    * ``ordem`` is the template's slot inside its version and is never
      reused there: a replacement takes over its predecessor's slot, a new
      template gets the next free one.  The rows of one slot, by ``id``, are
      that template's whole history (no self-reference, so a migration or a
      restore never needs a second pass that rewrites a frozen row).
    * Which versions may gain, replace or withdraw templates is the activity
      freeze policy (``can_activity_version_be_mutated_in_place``), enforced
      by the owner; a frozen version keeps its templates as they are.

The PostgreSQL authority (``app.pg_schema``) declares the same logical objects.
"""

from __future__ import annotations


DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
#: Small enough to travel through a hosted function body (4.5 MB) with its
#: multipart envelope; a fill-in form is far below it.
DOCUMENT_TEMPLATE_MAX_BYTES = 4 * 1024 * 1024
DOCUMENT_TEMPLATE_TITLE_MAX_LENGTH = 160
DOCUMENT_TEMPLATE_FILENAME_MAX_LENGTH = 255
DOCUMENT_TEMPLATE_STATUSES = ("ativo", "substituido", "retirado")

DOCUMENT_TEMPLATES_V19_TABLES = ("modelo_documento_arquivos", "atividade_versao_modelos")

MODELO_DOCUMENTO_ARQUIVOS_V19_TABLE_SQL = f"""CREATE TABLE modelo_documento_arquivos (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 sha256 TEXT NOT NULL UNIQUE CHECK(length(sha256)=64 AND sha256 NOT GLOB '*[^0-9a-f]*'),
 mime_type TEXT NOT NULL CHECK(mime_type='{DOCX_MIME_TYPE}'),
 size_bytes INTEGER NOT NULL CHECK(size_bytes>0 AND size_bytes<={DOCUMENT_TEMPLATE_MAX_BYTES}),
 conteudo BLOB NOT NULL CHECK(typeof(conteudo)='blob' AND length(conteudo)=size_bytes
    AND substr(conteudo,1,4)=X'504B0304'),
 criado_em TEXT NOT NULL DEFAULT (datetime('now'))
)"""

ATIVIDADE_VERSAO_MODELOS_V19_TABLE_SQL = f"""CREATE TABLE atividade_versao_modelos (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 atividade_versao_id INTEGER NOT NULL,
 arquivo_id INTEGER NOT NULL,
 titulo TEXT NOT NULL CHECK(length(titulo) BETWEEN 1 AND {DOCUMENT_TEMPLATE_TITLE_MAX_LENGTH} AND titulo=trim(titulo)),
 nome_arquivo TEXT NOT NULL CHECK(length(nome_arquivo) BETWEEN 1 AND {DOCUMENT_TEMPLATE_FILENAME_MAX_LENGTH}),
 ordem INTEGER NOT NULL CHECK(ordem>=1),
 status TEXT NOT NULL DEFAULT 'ativo' CHECK(status IN ('ativo','substituido','retirado')),
 criado_em TEXT NOT NULL DEFAULT (datetime('now')),
 criado_por_usuario_id INTEGER,
 encerrado_em TEXT,
 encerrado_por_usuario_id INTEGER,
 FOREIGN KEY(atividade_versao_id) REFERENCES atividade_versao(id) ON DELETE CASCADE,
 FOREIGN KEY(arquivo_id) REFERENCES modelo_documento_arquivos(id) ON DELETE RESTRICT,
 FOREIGN KEY(criado_por_usuario_id) REFERENCES usuarios(id) ON DELETE RESTRICT,
 FOREIGN KEY(encerrado_por_usuario_id) REFERENCES usuarios(id) ON DELETE RESTRICT,
 CHECK((status='ativo') = (encerrado_em IS NULL))
)"""

ATIVIDADE_VERSAO_MODELOS_V19_INDEX_SQL = (
    "CREATE INDEX idx_atividade_versao_modelos_versao "
    "ON atividade_versao_modelos(atividade_versao_id,status,ordem)"
)

DOCUMENT_TEMPLATES_V19_TRIGGERS_SQL = (
    """CREATE TRIGGER trg_modelo_documento_arquivos_immutable
BEFORE UPDATE ON modelo_documento_arquivos
BEGIN SELECT RAISE(ABORT,'document template content is immutable'); END""",
    """CREATE TRIGGER trg_atividade_versao_modelos_history
BEFORE UPDATE ON atividade_versao_modelos
FOR EACH ROW WHEN OLD.status<>'ativo'
   OR NEW.atividade_versao_id IS NOT OLD.atividade_versao_id
   OR NEW.arquivo_id IS NOT OLD.arquivo_id
   OR NEW.titulo IS NOT OLD.titulo
   OR NEW.nome_arquivo IS NOT OLD.nome_arquivo
   OR NEW.ordem IS NOT OLD.ordem
   OR NEW.criado_em IS NOT OLD.criado_em
   OR NEW.criado_por_usuario_id IS NOT OLD.criado_por_usuario_id
BEGIN SELECT RAISE(ABORT,'document template history is immutable'); END""",
)

DOCUMENT_TEMPLATES_V19_STATEMENTS = (
    MODELO_DOCUMENTO_ARQUIVOS_V19_TABLE_SQL,
    ATIVIDADE_VERSAO_MODELOS_V19_TABLE_SQL,
    ATIVIDADE_VERSAO_MODELOS_V19_INDEX_SQL,
    *DOCUMENT_TEMPLATES_V19_TRIGGERS_SQL,
)
DOCUMENT_TEMPLATES_V19_SCHEMA_OBJECTS_SQL = ";\n".join(DOCUMENT_TEMPLATES_V19_STATEMENTS) + ";"

DOCUMENT_TEMPLATES_V19_DETAILS_JSON = (
    '{"schema_epoch":"prod-1","document_templates":"database",'
    '"tables":["modelo_documento_arquivos","atividade_versao_modelos"],'
    '"mime_types":["' + DOCX_MIME_TYPE + '"],"backfill":"none"}'
)
DOCUMENT_TEMPLATES_V19_MARKER_SQL = (
    "INSERT INTO schema_migrations(version,name,schema_epoch,details_json)\n"
    "VALUES(19,'document_templates','prod-1','" + DOCUMENT_TEMPLATES_V19_DETAILS_JSON + "');"
)


__all__ = [
    "ATIVIDADE_VERSAO_MODELOS_V19_INDEX_SQL",
    "ATIVIDADE_VERSAO_MODELOS_V19_TABLE_SQL",
    "DOCUMENT_TEMPLATES_V19_DETAILS_JSON",
    "DOCUMENT_TEMPLATES_V19_MARKER_SQL",
    "DOCUMENT_TEMPLATES_V19_SCHEMA_OBJECTS_SQL",
    "DOCUMENT_TEMPLATES_V19_STATEMENTS",
    "DOCUMENT_TEMPLATES_V19_TABLES",
    "DOCUMENT_TEMPLATES_V19_TRIGGERS_SQL",
    "DOCUMENT_TEMPLATE_FILENAME_MAX_LENGTH",
    "DOCUMENT_TEMPLATE_MAX_BYTES",
    "DOCUMENT_TEMPLATE_STATUSES",
    "DOCUMENT_TEMPLATE_TITLE_MAX_LENGTH",
    "DOCX_MIME_TYPE",
    "MODELO_DOCUMENTO_ARQUIVOS_V19_TABLE_SQL",
]
