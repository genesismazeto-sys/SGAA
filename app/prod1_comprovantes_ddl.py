"""Canonical v4-only index and trigger definitions."""

COMPROVANTES_V4_SCHEMA_OBJECTS_SQL = """
CREATE INDEX idx_req_arquivos_req_status ON requisicao_arquivos(requisicao_id,storage_status);
CREATE UNIQUE INDEX ux_req_arquivos_provider_remote_file ON requisicao_arquivos(provider,remote_file_id) WHERE remote_file_id IS NOT NULL;
CREATE UNIQUE INDEX ux_req_arquivos_operation_key ON requisicao_arquivos(operation_key) WHERE operation_key IS NOT NULL;
CREATE TRIGGER trg_requisicoes_turma_snapshot_insert
BEFORE INSERT ON requisicoes FOR EACH ROW
WHEN (NEW.turma_id_snapshot IS NULL)<>(NEW.turma_codigo_snapshot IS NULL)
  OR (NEW.turma_codigo_snapshot IS NOT NULL AND TRIM(NEW.turma_codigo_snapshot)='')
BEGIN SELECT RAISE(ABORT,'request turma snapshot must be complete'); END;
CREATE TRIGGER trg_requisicoes_turma_snapshot_update
BEFORE UPDATE OF turma_id_snapshot,turma_codigo_snapshot ON requisicoes FOR EACH ROW
WHEN (NEW.turma_id_snapshot IS NULL)<>(NEW.turma_codigo_snapshot IS NULL)
  OR (NEW.turma_codigo_snapshot IS NOT NULL AND TRIM(NEW.turma_codigo_snapshot)='')
  OR (OLD.turma_id_snapshot IS NOT NULL AND (
      NEW.turma_id_snapshot IS NOT OLD.turma_id_snapshot
      OR NEW.turma_codigo_snapshot IS NOT OLD.turma_codigo_snapshot))
BEGIN SELECT RAISE(ABORT,'request turma snapshot is immutable'); END;
CREATE TRIGGER trg_requisicao_arquivos_custody_insert
BEFORE INSERT ON requisicao_arquivos FOR EACH ROW
WHEN NEW.provider NOT IN ('local_legacy','google')
  OR NEW.storage_status NOT IN ('legacy_active','pending','uploaded','active','failed','reconciliation_required','deletion_pending','trashed')
  OR (NEW.size_bytes IS NOT NULL AND NEW.size_bytes<0)
  OR (NEW.provider='local_legacy' AND (NEW.remote_file_id IS NOT NULL OR NEW.remote_parent_id IS NOT NULL OR NEW.delete_previous_status IS NOT NULL OR NEW.delete_started_at IS NOT NULL))
  OR (NEW.provider='google' AND NEW.storage_status='active' AND (
      COALESCE(TRIM(NEW.filename),'')='' OR COALESCE(TRIM(NEW.remote_file_id),'')=''
      OR COALESCE(TRIM(NEW.remote_parent_id),'')='' OR COALESCE(TRIM(NEW.original_filename),'')=''
      OR COALESCE(TRIM(NEW.mime_type),'')='' OR NEW.mime_type NOT IN ('application/pdf','image/png','image/jpeg')
      OR NEW.size_bytes IS NULL OR NEW.size_bytes<=0
      OR COALESCE(TRIM(NEW.sha256),'')='' OR length(NEW.sha256)<>64
      OR lower(NEW.sha256) GLOB '*[^0-9a-f]*'
      OR COALESCE(TRIM(NEW.uploaded_at),'')='' OR datetime(NEW.uploaded_at) IS NULL
      OR NEW.uploader_user_id IS NULL
      OR COALESCE(TRIM(NEW.operation_key),'')='' OR length(NEW.operation_key)>124
      OR NEW.delete_previous_status IS NOT NULL OR NEW.delete_started_at IS NOT NULL))
  OR (NEW.storage_status IN ('deletion_pending','trashed') AND (
      NEW.provider<>'google' OR COALESCE(TRIM(NEW.remote_file_id),'')=''
      OR COALESCE(NEW.delete_previous_status,'') NOT IN ('pending','uploaded','active','failed','reconciliation_required')
      OR COALESCE(TRIM(NEW.delete_started_at),'')='' OR datetime(NEW.delete_started_at) IS NULL))
BEGIN SELECT RAISE(ABORT,'invalid comprovante custody metadata'); END;
CREATE TRIGGER trg_requisicao_arquivos_custody_update
BEFORE UPDATE ON requisicao_arquivos FOR EACH ROW
WHEN NEW.provider NOT IN ('local_legacy','google')
  OR NEW.storage_status NOT IN ('legacy_active','pending','uploaded','active','failed','reconciliation_required','deletion_pending','trashed')
  OR (NEW.size_bytes IS NOT NULL AND NEW.size_bytes<0)
  OR (NEW.provider='local_legacy' AND (NEW.remote_file_id IS NOT NULL OR NEW.remote_parent_id IS NOT NULL OR NEW.delete_previous_status IS NOT NULL OR NEW.delete_started_at IS NOT NULL))
  OR (NEW.provider='google' AND NEW.storage_status='active' AND (
      COALESCE(TRIM(NEW.filename),'')='' OR COALESCE(TRIM(NEW.remote_file_id),'')=''
      OR COALESCE(TRIM(NEW.remote_parent_id),'')='' OR COALESCE(TRIM(NEW.original_filename),'')=''
      OR COALESCE(TRIM(NEW.mime_type),'')='' OR NEW.mime_type NOT IN ('application/pdf','image/png','image/jpeg')
      OR NEW.size_bytes IS NULL OR NEW.size_bytes<=0
      OR COALESCE(TRIM(NEW.sha256),'')='' OR length(NEW.sha256)<>64
      OR lower(NEW.sha256) GLOB '*[^0-9a-f]*'
      OR COALESCE(TRIM(NEW.uploaded_at),'')='' OR datetime(NEW.uploaded_at) IS NULL
      OR NEW.uploader_user_id IS NULL
      OR COALESCE(TRIM(NEW.operation_key),'')='' OR length(NEW.operation_key)>124
      OR NEW.delete_previous_status IS NOT NULL OR NEW.delete_started_at IS NOT NULL))
  OR (NEW.storage_status IN ('deletion_pending','trashed') AND (
      NEW.provider<>'google' OR COALESCE(TRIM(NEW.remote_file_id),'')=''
      OR COALESCE(NEW.delete_previous_status,'') NOT IN ('pending','uploaded','active','failed','reconciliation_required')
      OR COALESCE(TRIM(NEW.delete_started_at),'')='' OR datetime(NEW.delete_started_at) IS NULL))
BEGIN SELECT RAISE(ABORT,'invalid comprovante custody metadata'); END;
"""

__all__ = ["COMPROVANTES_V4_SCHEMA_OBJECTS_SQL"]
