"""Canonical prod-1/v15 business-document custody (SQLite authority).

v15 makes a canonical (Supabase Storage) business-document row LEGAL on both
business file tables; it adds no table and moves no byte:

    requisicao_arquivos   provider 'supabase' (STORAGE S3-A writes it)
    admin_arquivos        provider 'supabase' (schema preparation only: the
                          ARQUIVOS runtime stays on Google Drive until S3-B)

THE CONTRACT
    * ``provider = 'supabase'`` => ``storage_object_id`` NOT NULL, no Google
      locator (``remote_file_id`` / ``remote_parent_id``), no Drive delete or
      cleanup bookkeeping, and the full custody metadata (original filename,
      PDF / PNG / JPEG, positive size, 64 lowercase-hex SHA-256, upload time,
      uploader, operation key of at most 124 characters).
    * The reverse implication is deliberately NOT a database rule:
      ``storage_object_id`` NOT NULL does not imply ``supabase``.  Legacy rows
      that carry a canonical reference stay legal exactly as published in
      v14 (S2 / Path-B / Layer-2 compatibility); new S3 writes choose
      ``supabase`` as an application rule.
    * Canonical request statuses: ``active`` and ``trashed`` (a removed
      canonical comprovante keeps its row and object reference as evidence).
      Pending / uploaded / failed upload state lives in
      ``storage_upload_intents``, never in a half-created business row.
    * Canonical ARQUIVOS status: ``active`` only.  An optional legacy residue
      reuses ``prior_provider`` (``google`` / ``local_legacy``) +
      ``prior_locator`` (a Drive id, or a relative upload path without
      traversal) and means LEGACY RESIDUE PRESERVED FOR S5 -- never "cleanup
      pending": ``cleanup_started_at`` stays NULL and
      ``replacement_cleanup_pending`` keeps its Google-only meaning.
    * Every legacy verdict of v14 is unchanged.

WHY A REBUILD FOR ``admin_arquivos``
    Its provider domain is a column CHECK, which SQLite cannot alter in place.
    The rebuild copies the rows through a scratch table and recreates the
    table, its indexes and its triggers from the v15 DDL below.  The fresh
    bootstrap runs the very same statements (on an empty table) as the
    migration, so a migrated and a fresh database store identical DDL.  The
    request custody lives in triggers only, so those are simply replaced.

The PostgreSQL authority (``app.pg_schema``) declares the same contract.
"""

from __future__ import annotations

from app.prod1_storage_ddl import STORAGE_V14_INDEX_SQL, STORAGE_V14_TRIGGER_SQL

CANONICAL_PROVIDER = "supabase"
BUSINESS_PROVIDERS_V15 = ("local_legacy", "google", CANONICAL_PROVIDER)
CANONICAL_REQUEST_STATUSES = ("active", "trashed")
CANONICAL_ARQUIVO_STATUSES = ("active",)
LEGACY_RESIDUE_PROVIDERS = ("google", "local_legacy")
LEGACY_LOCAL_LOCATOR_MAX_LENGTH = 1024

_MIMES = "'application/pdf','image/png','image/jpeg'"

#: Shared canonical custody metadata (``NEW.`` row), refused when incomplete.
_CANONICAL_METADATA_INVALID = f"""COALESCE(TRIM(NEW.filename),'')='' OR COALESCE(TRIM(NEW.original_filename),'')=''
      OR NEW.mime_type IS NULL OR NEW.mime_type NOT IN ({_MIMES})
      OR NEW.size_bytes IS NULL OR NEW.size_bytes<=0
      OR NEW.sha256 IS NULL OR length(NEW.sha256)<>64 OR NEW.sha256 GLOB '*[^0-9a-f]*'
      OR COALESCE(TRIM(NEW.uploaded_at),'')='' OR datetime(NEW.uploaded_at) IS NULL
      OR NEW.uploader_user_id IS NULL
      OR COALESCE(TRIM(NEW.operation_key),'')='' OR length(NEW.operation_key)>124"""


def _request_custody_trigger(event: str) -> str:
    timing = "INSERT" if event == "insert" else "UPDATE"
    return f"""CREATE TRIGGER trg_requisicao_arquivos_custody_{event}
BEFORE {timing} ON requisicao_arquivos FOR EACH ROW
WHEN NEW.provider NOT IN ('local_legacy','google','supabase')
  OR NEW.storage_status NOT IN ('legacy_active','pending','uploaded','active','failed','reconciliation_required','deletion_pending','trashed')
  OR (NEW.size_bytes IS NOT NULL AND NEW.size_bytes<0)
  OR (NEW.provider='local_legacy' AND (NEW.remote_file_id IS NOT NULL OR NEW.remote_parent_id IS NOT NULL OR NEW.delete_previous_status IS NOT NULL OR NEW.delete_started_at IS NOT NULL))
  OR (NEW.provider='google' AND NEW.storage_status='active' AND (
      COALESCE(TRIM(NEW.filename),'')='' OR COALESCE(TRIM(NEW.remote_file_id),'')=''
      OR COALESCE(TRIM(NEW.remote_parent_id),'')='' OR COALESCE(TRIM(NEW.original_filename),'')=''
      OR COALESCE(TRIM(NEW.mime_type),'')='' OR NEW.mime_type NOT IN ({_MIMES})
      OR NEW.size_bytes IS NULL OR NEW.size_bytes<=0
      OR COALESCE(TRIM(NEW.sha256),'')='' OR length(NEW.sha256)<>64
      OR lower(NEW.sha256) GLOB '*[^0-9a-f]*'
      OR COALESCE(TRIM(NEW.uploaded_at),'')='' OR datetime(NEW.uploaded_at) IS NULL
      OR NEW.uploader_user_id IS NULL
      OR COALESCE(TRIM(NEW.operation_key),'')='' OR length(NEW.operation_key)>124
      OR NEW.delete_previous_status IS NOT NULL OR NEW.delete_started_at IS NOT NULL))
  OR (NEW.storage_status IN ('deletion_pending','trashed') AND NEW.provider<>'supabase' AND (
      NEW.provider<>'google' OR COALESCE(TRIM(NEW.remote_file_id),'')=''
      OR COALESCE(NEW.delete_previous_status,'') NOT IN ('pending','uploaded','active','failed','reconciliation_required')
      OR COALESCE(TRIM(NEW.delete_started_at),'')='' OR datetime(NEW.delete_started_at) IS NULL))
  OR (NEW.provider='supabase' AND (
      NEW.storage_object_id IS NULL OR NEW.storage_status NOT IN ('active','trashed')
      OR NEW.remote_file_id IS NOT NULL OR NEW.remote_parent_id IS NOT NULL
      OR NEW.delete_previous_status IS NOT NULL OR NEW.delete_started_at IS NOT NULL
      OR {_CANONICAL_METADATA_INVALID}))
BEGIN SELECT RAISE(ABORT,'invalid comprovante custody metadata'); END"""


ARQUIVOS_V15_TABLE_SQL = """CREATE TABLE admin_arquivos (
 id INTEGER PRIMARY KEY AUTOINCREMENT, titulo TEXT NOT NULL, descricao TEXT,
 filename TEXT NOT NULL, original_filename TEXT, visivel INTEGER NOT NULL DEFAULT 1 CHECK(visivel IN (0,1)),
 criado_em TEXT NOT NULL DEFAULT (datetime('now')),
 provider TEXT NOT NULL DEFAULT 'local_legacy' CHECK(provider IN ('local_legacy','google','supabase')),
 remote_file_id TEXT, remote_parent_id TEXT, mime_type TEXT, size_bytes INTEGER,
 sha256 TEXT, uploaded_at TEXT, uploader_user_id INTEGER, operation_key TEXT,
 replacement_mime_type TEXT, replacement_size_bytes INTEGER, replacement_sha256 TEXT,
 storage_status TEXT NOT NULL DEFAULT 'legacy_active'
   CHECK(storage_status IN ('legacy_active','pending','active','failed','reconciliation_required','replacement_cleanup_pending','deletion_pending')),
 failure_code TEXT, prior_provider TEXT CHECK(prior_provider IS NULL OR prior_provider IN ('local_legacy','google')),
 prior_locator TEXT, cleanup_started_at TEXT,
 storage_object_id INTEGER REFERENCES storage_objects(id) ON DELETE RESTRICT,
 FOREIGN KEY(uploader_user_id) REFERENCES usuarios(id) ON DELETE RESTRICT ON UPDATE CASCADE,
  CHECK(size_bytes IS NULL OR size_bytes>=0),
  CHECK(replacement_size_bytes IS NULL OR replacement_size_bytes>0)
)"""

#: The legacy residue locator, validated by its provider.
_RESIDUE_LOCATOR_INVALID = f"""(NEW.prior_provider='google' AND (
          length(NEW.prior_locator) NOT BETWEEN 1 AND 256 OR NEW.prior_locator GLOB '*[^A-Za-z0-9_-]*'))
      OR (NEW.prior_provider='local_legacy' AND (
          TRIM(NEW.prior_locator)='' OR length(NEW.prior_locator)>{LEGACY_LOCAL_LOCATOR_MAX_LENGTH}
          OR TRIM(NEW.prior_locator)<>NEW.prior_locator
          OR substr(NEW.prior_locator,1,1) IN ('/','\\') OR instr(NEW.prior_locator,':')>0
          OR instr(NEW.prior_locator,'..')>0))"""


def _arquivo_custody_trigger(event: str) -> str:
    timing = "INSERT" if event == "insert" else "UPDATE"
    return f"""CREATE TRIGGER trg_admin_arquivos_custody_{event}
BEFORE {timing} ON admin_arquivos FOR EACH ROW
WHEN
  (NEW.provider='local_legacy' AND (
      NEW.remote_file_id IS NOT NULL OR NEW.remote_parent_id IS NOT NULL
      OR NEW.storage_status NOT IN ('legacy_active','deletion_pending')))
  OR (NEW.provider='local_legacy' AND NEW.operation_key IS NOT NULL AND (
      NEW.storage_status<>'legacy_active' OR COALESCE(NEW.failure_code,'') NOT LIKE 'REPLACEMENT_%'))
  OR (NEW.operation_key IS NOT NULL AND (
      COALESCE(TRIM(NEW.operation_key),'')='' OR length(NEW.operation_key)>124))
  OR (COALESCE(NEW.failure_code,'') LIKE 'REPLACEMENT_%' AND (
      NEW.replacement_mime_type IS NULL OR NEW.replacement_size_bytes IS NULL
      OR NEW.replacement_sha256 IS NULL))
  OR (COALESCE(NEW.failure_code,'') NOT LIKE 'REPLACEMENT_%' AND (
      NEW.replacement_mime_type IS NOT NULL OR NEW.replacement_size_bytes IS NOT NULL
      OR NEW.replacement_sha256 IS NOT NULL))
  OR (NEW.replacement_mime_type IS NOT NULL AND (
      NEW.replacement_mime_type NOT IN ({_MIMES})
      OR NEW.replacement_size_bytes<=0 OR length(NEW.replacement_sha256)<>64
      OR lower(NEW.replacement_sha256) GLOB '*[^0-9a-f]*'))
  OR (NEW.provider='google' AND NEW.storage_status IN ('pending','active','replacement_cleanup_pending','deletion_pending') AND (
      COALESCE(TRIM(NEW.filename),'')='' OR COALESCE(TRIM(NEW.original_filename),'')=''
      OR COALESCE(TRIM(NEW.mime_type),'')='' OR NEW.mime_type NOT IN ({_MIMES})
      OR NEW.size_bytes IS NULL OR NEW.size_bytes<=0
      OR COALESCE(TRIM(NEW.sha256),'')='' OR length(NEW.sha256)<>64 OR lower(NEW.sha256) GLOB '*[^0-9a-f]*'
      OR COALESCE(TRIM(NEW.uploaded_at),'')='' OR datetime(NEW.uploaded_at) IS NULL
      OR NEW.uploader_user_id IS NULL
      OR COALESCE(TRIM(NEW.operation_key),'')='' OR length(NEW.operation_key)>124))
  OR (NEW.provider='google' AND NEW.storage_status IN ('active','replacement_cleanup_pending','deletion_pending') AND (
      COALESCE(TRIM(NEW.remote_file_id),'')='' OR COALESCE(TRIM(NEW.remote_parent_id),'')=''))
  OR (NEW.storage_status='replacement_cleanup_pending' AND (
      NEW.provider<>'google' OR NEW.prior_provider IS NULL OR COALESCE(TRIM(NEW.prior_locator),'')=''
      OR COALESCE(TRIM(NEW.cleanup_started_at),'')='' OR datetime(NEW.cleanup_started_at) IS NULL))
  OR (NEW.storage_status='deletion_pending' AND (
      COALESCE(TRIM(NEW.cleanup_started_at),'')='' OR datetime(NEW.cleanup_started_at) IS NULL))
  OR (NEW.provider<>'supabase' AND NEW.storage_status NOT IN ('replacement_cleanup_pending') AND (
      NEW.prior_provider IS NOT NULL OR NEW.prior_locator IS NOT NULL))
  OR (NEW.storage_status NOT IN ('replacement_cleanup_pending','deletion_pending') AND NEW.cleanup_started_at IS NOT NULL)
  OR (NEW.provider='supabase' AND (
      NEW.storage_object_id IS NULL OR NEW.storage_status<>'active'
      OR NEW.remote_file_id IS NOT NULL OR NEW.remote_parent_id IS NOT NULL
      OR NEW.cleanup_started_at IS NOT NULL OR COALESCE(NEW.failure_code,'') LIKE 'REPLACEMENT_%'
      OR (NEW.prior_provider IS NULL)<>(NEW.prior_locator IS NULL)
      OR {_RESIDUE_LOCATOR_INVALID}
      OR {_CANONICAL_METADATA_INVALID}))
BEGIN SELECT RAISE(ABORT,'invalid admin arquivo custody metadata'); END"""


_ARQUIVOS_INDEX_SQL = (
    "CREATE INDEX idx_admin_arquivos_visivel ON admin_arquivos(visivel)",
    "CREATE INDEX idx_admin_arquivos_criado_em ON admin_arquivos(criado_em)",
    "CREATE UNIQUE INDEX ux_admin_arquivos_provider_remote_file\n"
    "ON admin_arquivos(provider,remote_file_id) WHERE remote_file_id IS NOT NULL",
    "CREATE UNIQUE INDEX ux_admin_arquivos_operation_key\n"
    "ON admin_arquivos(operation_key) WHERE operation_key IS NOT NULL",
    *(sql for sql in STORAGE_V14_INDEX_SQL if "ux_admin_arquivos_storage_object" in sql),
)
_ARQUIVOS_EXCLUSIVE_TRIGGER_SQL = tuple(
    sql for sql in STORAGE_V14_TRIGGER_SQL if "BEFORE INSERT ON admin_arquivos" in sql
    or "ON admin_arquivos FOR EACH ROW" in sql
)
assert len(_ARQUIVOS_INDEX_SQL) == 5 and len(_ARQUIVOS_EXCLUSIVE_TRIGGER_SQL) == 2

ARQUIVOS_V15_SCRATCH_TABLE = "_admin_arquivos_v15"

#: Every v15 statement, in execution order -- shared verbatim by the fresh
#: bootstrap and the v14 -> v15 migration.  The ARQUIVOS rebuild preserves
#: rows and ids; the migration restores the AUTOINCREMENT high-water mark.
DOCUMENT_CUSTODY_V15_STATEMENTS = (
    "DROP TRIGGER trg_requisicao_arquivos_custody_insert",
    "DROP TRIGGER trg_requisicao_arquivos_custody_update",
    _request_custody_trigger("insert"),
    _request_custody_trigger("update"),
    f"CREATE TABLE {ARQUIVOS_V15_SCRATCH_TABLE} AS SELECT * FROM admin_arquivos",
    "DROP TABLE admin_arquivos",
    ARQUIVOS_V15_TABLE_SQL,
    f"INSERT INTO admin_arquivos SELECT * FROM {ARQUIVOS_V15_SCRATCH_TABLE}",
    f"DROP TABLE {ARQUIVOS_V15_SCRATCH_TABLE}",
    *_ARQUIVOS_INDEX_SQL,
    _arquivo_custody_trigger("insert"),
    _arquivo_custody_trigger("update"),
    *_ARQUIVOS_EXCLUSIVE_TRIGGER_SQL,
)
DOCUMENT_CUSTODY_V15_SCHEMA_OBJECTS_SQL = ";\n".join(DOCUMENT_CUSTODY_V15_STATEMENTS) + ";"

DOCUMENT_CUSTODY_V15_DETAILS_JSON = (
    '{"schema_epoch":"prod-1","canonical_provider":"supabase",'
    '"tables":["requisicao_arquivos","admin_arquivos"],'
    '"canonical_request_statuses":["active","trashed"],"canonical_arquivo_statuses":["active"],'
    '"legacy_residue":"prior_provider+prior_locator","reverse_implication":"none",'
    '"backfill":"none","runtime_switch":"requisicao_arquivos"}'
)

__all__ = [
    "ARQUIVOS_V15_SCRATCH_TABLE",
    "ARQUIVOS_V15_TABLE_SQL",
    "BUSINESS_PROVIDERS_V15",
    "CANONICAL_ARQUIVO_STATUSES",
    "CANONICAL_PROVIDER",
    "CANONICAL_REQUEST_STATUSES",
    "DOCUMENT_CUSTODY_V15_DETAILS_JSON",
    "DOCUMENT_CUSTODY_V15_SCHEMA_OBJECTS_SQL",
    "DOCUMENT_CUSTODY_V15_STATEMENTS",
    "LEGACY_LOCAL_LOCATOR_MAX_LENGTH",
    "LEGACY_RESIDUE_PROVIDERS",
]
