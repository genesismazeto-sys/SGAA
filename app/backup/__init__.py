# coding: utf-8
"""Pacote de backup — fachada de re-export.

Superfície mínima: apenas re-exporta, por identidade, os objetos canônicos
definidos em :mod:`app.backup.orchestrator`. Nenhum corpo de implementação
mora aqui.

``app.backup.sync`` (CLI) **não** é importado por esta fachada: ele depende de
``create_app`` e só deve ser carregado por ``python -m app.backup.sync``.
Nada neste pacote importa ``main``.
"""
from app.backup.orchestrator import (
    _RETENTION_WINDOWS_META,
    _build_retention_policy_windows,
    _database_backup_locations,
    _drive_settings_defaults,
    _get_runtime_backup_settings,
    _maybe_sync_database_snapshot,
    _maybe_upload_to_drives,
    _resolve_allowed_backup_manifest_path,
    _retention_policy_defaults,
    _run_retention_cleanup,
    _save_drive_config,
    _upload_snapshot_if_external_enabled,
    get_drive_settings,
    get_retention_policy,
    run_backup_cycle,
)
