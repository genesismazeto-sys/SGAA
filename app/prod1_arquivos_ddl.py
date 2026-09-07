"""Single semantic DDL authority for ARQUIVOS storage custody in prod-1/v5."""

ARQUIVOS_V5_TABLE_SQL = """
CREATE TABLE admin_arquivos (
 id INTEGER PRIMARY KEY AUTOINCREMENT, titulo TEXT NOT NULL, descricao TEXT,
 filename TEXT NOT NULL, original_filename TEXT, visivel INTEGER NOT NULL DEFAULT 1 CHECK(visivel IN (0,1)),
 criado_em TEXT NOT NULL DEFAULT (datetime('now')),
 provider TEXT NOT NULL DEFAULT 'local_legacy' CHECK(provider IN ('local_legacy','google')),
 remote_file_id TEXT, remote_parent_id TEXT, mime_type TEXT, size_bytes INTEGER,
 sha256 TEXT, uploaded_at TEXT, uploader_user_id INTEGER, operation_key TEXT,
 replacement_mime_type TEXT, replacement_size_bytes INTEGER, replacement_sha256 TEXT,
 storage_status TEXT NOT NULL DEFAULT 'legacy_active'
   CHECK(storage_status IN ('legacy_active','pending','active','failed','reconciliation_required','replacement_cleanup_pending','deletion_pending')),
 failure_code TEXT, prior_provider TEXT CHECK(prior_provider IS NULL OR prior_provider IN ('local_legacy','google')),
 prior_locator TEXT, cleanup_started_at TEXT,
 FOREIGN KEY(uploader_user_id) REFERENCES usuarios(id) ON DELETE RESTRICT ON UPDATE CASCADE,
  CHECK(size_bytes IS NULL OR size_bytes>=0),
  CHECK(replacement_size_bytes IS NULL OR replacement_size_bytes>0)
);
"""

ARQUIVOS_V5_SCHEMA_OBJECTS_SQL = """
CREATE INDEX idx_admin_arquivos_visivel ON admin_arquivos(visivel);
CREATE INDEX idx_admin_arquivos_criado_em ON admin_arquivos(criado_em);
CREATE UNIQUE INDEX ux_admin_arquivos_provider_remote_file
ON admin_arquivos(provider,remote_file_id) WHERE remote_file_id IS NOT NULL;
CREATE UNIQUE INDEX ux_admin_arquivos_operation_key
ON admin_arquivos(operation_key) WHERE operation_key IS NOT NULL;
CREATE TRIGGER trg_admin_arquivos_custody_insert
BEFORE INSERT ON admin_arquivos FOR EACH ROW
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
      NEW.replacement_mime_type NOT IN ('application/pdf','image/png','image/jpeg')
      OR NEW.replacement_size_bytes<=0 OR length(NEW.replacement_sha256)<>64
      OR lower(NEW.replacement_sha256) GLOB '*[^0-9a-f]*'))
  OR (NEW.provider='google' AND NEW.storage_status IN ('pending','active','replacement_cleanup_pending','deletion_pending') AND (
      COALESCE(TRIM(NEW.filename),'')='' OR COALESCE(TRIM(NEW.original_filename),'')=''
      OR COALESCE(TRIM(NEW.mime_type),'')='' OR NEW.mime_type NOT IN ('application/pdf','image/png','image/jpeg')
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
  OR (NEW.storage_status NOT IN ('replacement_cleanup_pending') AND (
      NEW.prior_provider IS NOT NULL OR NEW.prior_locator IS NOT NULL))
  OR (NEW.storage_status NOT IN ('replacement_cleanup_pending','deletion_pending') AND NEW.cleanup_started_at IS NOT NULL)
BEGIN SELECT RAISE(ABORT,'invalid admin arquivo custody metadata'); END;
CREATE TRIGGER trg_admin_arquivos_custody_update
BEFORE UPDATE ON admin_arquivos FOR EACH ROW
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
      NEW.replacement_mime_type NOT IN ('application/pdf','image/png','image/jpeg')
      OR NEW.replacement_size_bytes<=0 OR length(NEW.replacement_sha256)<>64
      OR lower(NEW.replacement_sha256) GLOB '*[^0-9a-f]*'))
  OR (NEW.provider='google' AND NEW.storage_status IN ('pending','active','replacement_cleanup_pending','deletion_pending') AND (
      COALESCE(TRIM(NEW.filename),'')='' OR COALESCE(TRIM(NEW.original_filename),'')=''
      OR COALESCE(TRIM(NEW.mime_type),'')='' OR NEW.mime_type NOT IN ('application/pdf','image/png','image/jpeg')
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
  OR (NEW.storage_status NOT IN ('replacement_cleanup_pending') AND (
      NEW.prior_provider IS NOT NULL OR NEW.prior_locator IS NOT NULL))
  OR (NEW.storage_status NOT IN ('replacement_cleanup_pending','deletion_pending') AND NEW.cleanup_started_at IS NOT NULL)
BEGIN SELECT RAISE(ABORT,'invalid admin arquivo custody metadata'); END;
"""

__all__ = ["ARQUIVOS_V5_SCHEMA_OBJECTS_SQL", "ARQUIVOS_V5_TABLE_SQL"]
