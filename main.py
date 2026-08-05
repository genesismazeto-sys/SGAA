# coding: utf-8
import os
import csv
import sqlite3
import json
import datetime
import time
import tempfile
import base64   # Para codificação/decodificação de salt
import secrets  # Para geração segura de tokens
import openpyxl
import logging
from logging.handlers import RotatingFileHandler
import traceback
import re
from datetime import date
from urllib.parse import urlsplit
from flask import render_template, request, redirect, url_for, session, send_from_directory, send_file, jsonify, g, abort, make_response, current_app
import shutil
from urllib.parse import urlparse
from flask_compress import Compress
try:
    from dotenv import load_dotenv  # type: ignore[import-not-found]
except Exception:
    # Fallback no-op keeps local/dev execution working even before dependencies are installed.
    def load_dotenv(*args, **kwargs):
        return False

# Carrega variaveis do .env antes de importar modulos que dependem de configuracao OAuth.
load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from app import create_app
from app.academics import (
    DEFAULT_CURSO_TOTAL_HORAS_AAC,
    DEFAULT_CURSO_TOTAL_HORAS_AEU,
    build_turma_aluno_matricula,
    gerar_codigo_turma,
    resequence_turma_aluno_matriculas,
    resequence_turma_aluno_matriculas_for_ids,
)
from app.user_accounts import (
    _access_defaults_map,
    _default_password_for_user_type,
    create_usuario_with_default_access,
    create_usuario_with_default_password,
    normalize_usuario_access_for_user_type,
)
from app.web.request import _is_ajax_request
from app.activity_catalog import (
    _normalize_atividade_grupo,
    get_atividade_base,
    get_atividade_base_list,
    get_atividade_transicoes_por_base,
    get_atividade_versao_by_id,
    get_atividade_versao_usage_counts,
    get_legacy_map_list,
    get_next_numero_versao,
    get_norma_by_id,
    get_norma_list,
    get_ultima_versao_ativa_por_base,
    get_versoes_da_base_por_eixo,
    get_versoes_por_base,
    parse_documentos_json,
)
from app.db import (
    DATABASE,
    DEFAULT_HORAS_ACADEMICA,
    DEFAULT_HORAS_EXTENSAO,
    DEFAULT_RESPONSE_GOAL_DAYS,
    DEFAULT_RETURN_RESPONSE_DAYS,
    _app_settings_defaults,
    close_db_connection,
    ensure_app_settings_schema,
    ensure_cloud_backup_schema,
    ensure_turmas_matriz_schema,
    get_db_connection,
    get_preferred_matriz_for_curso,
    init_db,
)
from app.presentation import format_date_ptbr
from app.reporting import REPORTE_CATEGORY_OPTIONS
from app.matrix_scope import (
    MATRIZ_STATUS_META,
    _matriz_option_label,
    _matriz_status_label,
    get_allowed_activity_ids_for_turma_matrix,
    get_effective_matriz_for_turma,
    is_activity_allowed_for_turma_matrix,
)
from app.requisition_policy import (
    _parse_optional_processing_datetime,
    can_student_delete_requisition,
    can_student_edit_requisition,
)
from app.requisitions import auto_indefer_devolvidas
from app.settings import (
    _normalize_optional_iso_date,
    get_app_settings,
    get_horas_settings,
    get_response_time_settings,
    reset_response_time_metrics,
    save_app_settings,
    save_horas_settings,
    save_return_response_settings,
)
from app.security.passwords import (
    check_password,
    hash_password,
    is_legacy_password_hash,
)
from app.text import normalize_header, ptbr_sqlite_collation, ptbr_text_sort_key
from app.uploads import (
    ALLOWED_ATTACHMENTS,
    ALLOWED_CSV,
    ALLOWED_REPORTE_SCREENSHOTS,
    _allowed,
    _unique_filename,
    save_upload,
)
from app.web.filters import (
    append_conditions_sql,
    append_text_contains_condition,
    get_date_range_query,
    get_int_multi_query_values,
    get_multi_query_values,
    get_number_range_query,
    get_text_query_value,
)
from app.web.pagination import get_pagination, wants_pagination
from app.auth import (
    ACCESS_RESOURCE_GROUPS,
    ACCESS_RESOURCE_ORDER,
    ACCESS_RESOURCES_META,
    ACCESS_LEVEL_META,
    AdminAuthorizationConfigurationError,
    classify_governed_admin_request,
    access_level_label,
    access_level_to_user_type,
    admin_required as _auth_admin_required,
    aluno_required as _auth_aluno_required,
    build_access_scope_groups,
    canonicalize_access_level,
    default_access_level_for_user_type,
    get_admin_permission_requirement,
    merge_resource_scopes,
    normalize_permission_scope,
    permission_scope_label,
    permission_scope_satisfies,
)
from app.admin_access import (
    _admin_can,
    _build_access_scope_groups_for_level,
    _fetch_user_access_overrides,
    _get_current_admin_access_context,
    _load_admin_access_context,
)
from app.admin_alerts import list_active_admin_alertas
from app.admin_files import get_admin_arquivo
import app.cloud_drives as _cd
from app.backup_settings import (
    _apply_backup_settings_to_app,
    _backup_settings_defaults,
    bind_backup_settings_runtime_app,
    ensure_backup_settings_schema,
    get_backup_settings,
)
from app.db_maintenance import (
    apply_early_schema_migrations,
    apply_retention_policy,
    apply_schema_migrations,
    create_database_snapshot,
    delete_database_snapshot,
    ensure_admin_alertas_table,
    ensure_admin_arquivos_table,
    ensure_atividade_versioning_schema,
    ensure_matriz_atividade_links_table,
    ensure_matrizes_atividades_table,
    ensure_reportes_table,
    ensure_requisicao_alert_receipts_table,
    ensure_usuario_access_schema,
    ensure_usuario_profile_schema,
    get_schema_status,
    list_database_backups,
    maybe_sync_database_to_cloud,
    restore_database_snapshot,
    upload_snapshot_to_external_server,
)
from app.services.backup_service import (
    BackupServiceError,
    cleanup_backup_artifacts,
    create_sqlite_backup_zip,
    extract_restore_database_artifact,
)
from app.student_documents import (
    resolve_student_document_path,
    sanitize_student_document_relpath,
    save_student_document,
)
from app.services.token_encryption import (
    TokenEncryptionConfigError,
    TokenEncryptionError,
    decrypt_token_json_from_storage,
    encrypt_token_json_for_storage,
    validate_token_encryption_configuration,
)
from app.services.google_drive_service import (
    GoogleDriveServiceError,
    create_authorization_url as google_create_authorization_url,
    exchange_code_for_token as google_exchange_code_for_token,
    get_redirect_uri as google_get_redirect_uri,
    list_google_folders as google_list_folders,
    upload_zip_backup as google_upload_zip_backup,
)
from services.onedrive_service import (
    OneDriveServiceError,
    create_authorization_url as onedrive_create_authorization_url,
    exchange_code_for_token as onedrive_exchange_code_for_token,
    get_ms_redirect_uri as onedrive_get_ms_redirect_uri,
    get_connected_account as onedrive_get_connected_account,
    list_onedrive_folders as onedrive_list_folders,
    validate_configuration as onedrive_validate_configuration,
    upload_zip_backup as onedrive_upload_zip_backup,
    upload_zip_backup_with_access_token as onedrive_upload_with_access_token,
)
from services.oauth_config import (
    OAuthConfigError,
    get_google_redirect_uri as oauth_get_google_redirect_uri,
    get_onedrive_redirect_uri as oauth_get_onedrive_redirect_uri,
    get_public_base_url as oauth_get_public_base_url,
)
from werkzeug.utils import secure_filename
from werkzeug.exceptions import RequestEntityTooLarge
from utils.messages import (
    flash,
    frontend_message_templates,
    list_editable_messages,
    reset_message_override,
    resolve_user_message,
    save_message_override,
)
from app.views.admin.atividades import (
    ATIVIDADES_IMPORT_REQUIRED_HEADERS,
    _atividades_import_preview_dir,
    _atividades_import_preview_path,
    _build_atividades_import_preview,
    _build_grupo_label,
    _canonicalize_tipo_atividade,
    _canonicalize_tipo_limitacao,
    _delete_atividades_import_preview,
    _delete_upload_relpath,
    _ensure_grupos_def_table,
    _format_preview_limitacao,
    _load_atividades_import_preview,
    _normalize_import_header_name,
    _parse_csv_boolean,
    _parse_optional_positive_int,
    _store_atividades_import_preview,
    _upsert_grupo_definition,
    admin_adicionar_atividade,
    admin_atividades,
    admin_atividades_academicas,
    admin_atividades_extensao,
    admin_atividades_importar_confirmar,
    admin_atividades_importar_preview,
    admin_catalogo_ativar_versao,
    admin_catalogo_descontinuar_versao,
    admin_catalogo_editar_versao,
    admin_catalogo_inativar_versao,
    admin_catalogo_nova_base,
    admin_catalogo_nova_versao,
    admin_catalogo_substituir_versao,
    admin_catalogo_versao_detalhe,
    admin_catalogo_versoes,
    admin_deletar_atividade,
    admin_editar_atividade,
    admin_grupos_excluir,
    admin_grupos_renomear,
    admin_mapeamento_legado,
    admin_norma_nova,
    admin_normas_atividade,
)
from app.views.admin.configuracoes import (
    admin_configuracoes,
    admin_configuracoes_horas_padrao_salvar,
    admin_configuracoes_prazo_adequacao_salvar,
    admin_configuracoes_tempo_resposta_resetar,
    admin_configuracoes_tempo_resposta_salvar,
    admin_mensagens,
    admin_mensagens_resetar,
    admin_mensagens_salvar,
)
from app.views.admin.requisicoes import (
    ALLOWED_EXCEL,
    _append_requisicao_arquivos,
    _get_admin_requisicao_scope_for_aluno,
    _list_admin_requisicao_alunos,
    _normalize_requisicao_data_evento,
    admin_api_aluno_requisicao_scope,
    admin_api_requisicao,
    admin_detalhes_requisicao,
    admin_editar_requisicao,
    admin_excluir_requisicao,
    admin_importar_requisicoes,
    admin_nova_requisicao,
    admin_processar_requisicao,
    admin_requisicoes,
)
from app.versioning.resolver import (
    _atividade_versao_status_ativo,
    _get_effective_matriz_for_turma_readonly,
    _get_preferred_matriz_for_curso_readonly,
    _require_versioning_read_model,
    _resolver_result,
    _serialize_versioned_activity_row,
    listar_atividades_versionadas_por_matriz,
    listar_atividades_versionadas_por_turma,
    resolver_versao,
    resolver_versao_por_aluno,
    resolver_versao_por_matriz,
)
from app.versioning.shadow_reads import (
    _append_versioned_shadow_read_event_line,
    _build_versioned_shadow_read_event_line,
    _collect_versioned_shadow_read_log_paths,
    _normalize_shadow_read_int,
    _normalize_shadow_read_scalar,
    _parse_shadow_read_bool_filter,
    _parse_shadow_read_warnings,
    _parse_versioned_shadow_read_event_line,
    _read_versioned_shadow_read_events,
    _resolve_versioned_shadow_read_log_sources,
    _serialize_shadow_read_log_value,
    _shadow_read_event_dedup_key,
    _shadow_read_event_matches_filters,
    _versioned_shadow_read_dedicated_log_path,
    is_versioned_resolver_shadow_read_enabled,
    maybe_run_versioned_resolver_shadow_read,
)
from app.versioning.snapshots import (
    _build_admin_requisicao_snapshot_diagnostic,
    _build_versioned_requisicao_snapshot_payload,
    _get_turma_explicit_matriz_id_for_snapshot,
    _has_versioned_requisicao_snapshot,
    _load_versioned_requisicao_snapshot_rule_row,
    _normalize_snapshot_diagnostic_scalar,
    _snapshot_diagnostic_row_value,
    is_versioned_requisicao_snapshot_display_enabled,
    is_versioned_requisicao_snapshot_write_enabled,
    maybe_write_versioned_requisicao_snapshot,
)
from app.views.admin.versioning import (
    admin_diagnostico_atividades_versionadas,
    admin_diagnostico_atividades_versionadas_view,
    admin_diagnostico_versioned_shadow_reads,
)
from app.views.admin.matrizes import (
    get_bases_escopo_matriz,
    get_versoes_ativas_por_base_na_matriz,
    get_vinculo_versao_da_matriz,
    _set_versao_da_matriz_para_base,
    _remover_versao_da_matriz_para_base,
    get_card_version_menu_data,
    _matriz_status_badge_type,
    _matriz_vigencia_label,
    _matriz_activity_type_for_tab,
    _matriz_axis_for_tab,
    _get_grupos_por_tipo,
    _get_matriz_active_normas_for_axis,
    _build_matriz_new_activity_modal_context,
    _matriz_transfer_meta,
    _matriz_activity_rule_summary,
    _matriz_transfer_lists,
    _matriz_counts,
    _render_matriz_form,
    _matriz_payload_from_request,
    _ensure_default_versao_link,
    _save_matriz_activity_links,
    admin_matrizes,
    admin_adicionar_matriz,
    admin_editar_matriz,
    admin_matriz_nova_atividade,
    admin_matriz_nova_versao_card,
    admin_excluir_matrizes,
    admin_excluir_matriz,
    admin_matriz_versoes,
    admin_matriz_versoes_definir,
    admin_matriz_versoes_remover,
)
from app.views.admin.alunos_turmas_cursos import (
    admin_adicionar_aluno,
    admin_adicionar_curso,
    admin_adicionar_turma,
    admin_alunos,
    admin_alterar_status_alunos,
    admin_cursos,
    admin_deletar_aluno,
    admin_deletar_curso,
    admin_deletar_turma,
    admin_detalhes_curso,
    admin_detalhes_turma,
    admin_editar_aluno,
    admin_editar_curso,
    admin_editar_turma,
    admin_turmas,
    admin_turmas_importar,
    admin_visualizar_curso,
    curso_mais_populoso_id,
    proximo_numero_turma_por_curso,
    resolve_existing_aluno_by_identifiers,
    semestre_atual_hoje,
    validar_codigo_curso,
    _matrizes_by_curso,
    _periodo_label_for_turma_row,
    _resolve_turma_matriz_id,
    _safe_return_to_target,
    _turma_effective_matriz_label,
)



# ===================== Auth helpers =====================


def admin_required(f):
    return _auth_admin_required(f)

def aluno_required(f):
    return _auth_aluno_required(f)

# ===================== Utils =====================


# ===================== Parsing helpers =====================



def _calculate_pending_response_metrics(conn, *, goal_days: int, reset_at: str = "") -> tuple[float, int]:
    rows = conn.execute(
        """
        SELECT data_solicitacao
          FROM requisicoes
         WHERE status = 'Pendente'
           AND data_solicitacao IS NOT NULL
        """
    ).fetchall()

    reset_dt = None
    if reset_at:
        try:
            reset_dt = datetime.datetime.strptime(reset_at, "%Y-%m-%d")
        except ValueError:
            reset_dt = None

    now_dt = datetime.datetime.now()
    ages = []
    overdue_count = 0
    for row in rows:
        requested_at = _parse_optional_processing_datetime(row["data_solicitacao"])
        if not requested_at:
            continue
        effective_start = reset_dt if reset_dt and requested_at < reset_dt else requested_at
        age_days = max(0.0, (now_dt - effective_start).total_seconds() / 86400.0)
        ages.append(age_days)
        if age_days > goal_days:
            overdue_count += 1

    avg_days = (sum(ages) / len(ages)) if ages else 0.0
    return avg_days, overdue_count


def _normalize_backup_directory(value: str, *, allow_empty: bool = False) -> str:
    text = str(value or "").strip()
    if not text:
        if allow_empty:
            return ""
        raise ValueError("Informe um caminho de pasta válido.")
    return os.path.abspath(os.path.normpath(text))


def save_backup_settings(conn, payload: dict[str, str]) -> dict[str, str]:
    ensure_backup_settings_schema(conn)
    local_backup_dir = _normalize_backup_directory(payload.get("local_backup_dir") or "")
    cloud_backup_dir = _normalize_backup_directory(payload.get("cloud_backup_dir") or "", allow_empty=True)
    external_backup_url = str(payload.get("external_backup_url") or "").strip()
    external_backup_token = str(payload.get("external_backup_token") or "").strip()
    external_backup_enabled = str(payload.get("external_backup_enabled") or "0") in {"1", "true", "True", "on", "yes"}

    try:
        cloud_sync_interval_seconds = max(0, int(str(payload.get("cloud_sync_interval_seconds") or "600").strip()))
    except ValueError as exc:
        raise ValueError("O intervalo de sincronização deve ser um número inteiro maior ou igual a zero.") from exc

    if external_backup_enabled:
        parsed = urlparse(external_backup_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Informe uma URL HTTP/HTTPS válida para o servidor externo.")

    os.makedirs(local_backup_dir, exist_ok=True)
    if cloud_backup_dir:
        os.makedirs(cloud_backup_dir, exist_ok=True)

    normalized = {
        "local_backup_dir": local_backup_dir,
        "cloud_backup_dir": cloud_backup_dir,
        "cloud_sync_interval_seconds": str(cloud_sync_interval_seconds),
        "external_backup_url": external_backup_url,
        "external_backup_token": external_backup_token,
        "external_backup_enabled": "1" if external_backup_enabled else "0",
    }

    for chave, valor in normalized.items():
        conn.execute(
            """
            INSERT INTO configuracoes_backup (chave, valor, atualizado_em)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor, atualizado_em = datetime('now')
            """,
            (chave, valor),
        )
    _apply_backup_settings_to_app(normalized)
    return normalized


_RETENTION_INTERVAL_OPTIONS = [
    ("0.5", "a cada 30 min"),
    ("1", "a cada 1 h"),
    ("2", "a cada 2 h"),
    ("4", "a cada 4 h"),
    ("6", "a cada 6 h"),
    ("8", "a cada 8 h"),
    ("12", "a cada 12 h"),
    ("24", "a cada 1 dia"),
    ("48", "a cada 2 dias"),
    ("72", "a cada 3 dias"),
    ("168", "a cada 1 semana"),
    ("336", "a cada 2 semanas"),
    ("730", "a cada 1 mês"),
    ("1460", "a cada 2 meses"),
    ("2190", "a cada 3 meses"),
]

_RETENTION_WINDOWS_META = [
    {"key": "w0", "label": "Últimas 24 h", "period_hours": 24, "default_interval": "2", "default_slots": "12"},
    {"key": "w1", "label": "Últimos 7 dias", "period_hours": 168, "default_interval": "24", "default_slots": "7"},
    {"key": "w2", "label": "Últimas 4 semanas", "period_hours": 672, "default_interval": "168", "default_slots": "4"},
    {"key": "w3", "label": "Últimos 12 meses", "period_hours": 8760, "default_interval": "730", "default_slots": "12"},
]


def _retention_policy_defaults() -> dict[str, str]:
    defaults = {}
    for w in _RETENTION_WINDOWS_META:
        defaults[f"retention_{w['key']}_interval_hours"] = w["default_interval"]
        defaults[f"retention_{w['key']}_slots"] = w["default_slots"]
    return defaults


def get_retention_policy(conn) -> dict[str, str]:
    defaults = _retention_policy_defaults()
    try:
        rows = conn.execute(
            "SELECT chave, valor FROM configuracoes_backup WHERE chave LIKE 'retention_%'"
        ).fetchall()
        settings = dict(defaults)
        for row in rows:
            settings[str(row["chave"])] = str(row["valor"])
        return settings
    except sqlite3.OperationalError:
        return defaults


def save_retention_policy(conn, payload: dict) -> dict[str, str]:
    ensure_backup_settings_schema(conn)
    defaults = _retention_policy_defaults()
    normalized: dict[str, str] = {}
    for key, default_val in defaults.items():
        raw = str(payload.get(key) or default_val).strip()
        if "interval" in key:
            try:
                v = float(raw)
                if v <= 0:
                    raise ValueError
                normalized[key] = raw
            except ValueError:
                raise ValueError(f"Intervalo inválido para a janela '{key}'.")
        else:
            try:
                v = int(raw)
                if v < 1:
                    raise ValueError
                normalized[key] = str(v)
            except ValueError:
                raise ValueError(f"Número de slots inválido para a janela '{key}'.")

    for chave, valor in normalized.items():
        conn.execute(
            """
            INSERT INTO configuracoes_backup (chave, valor, atualizado_em)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor, atualizado_em = datetime('now')
            """,
            (chave, valor),
        )
    return normalized


def _build_retention_policy_windows(settings: dict[str, str]) -> list[dict]:
    windows = []
    for w in _RETENTION_WINDOWS_META:
        windows.append({
            "period_hours": w["period_hours"],
            "interval_hours": float(settings.get(f"retention_{w['key']}_interval_hours") or w["default_interval"]),
            "slots": int(settings.get(f"retention_{w['key']}_slots") or w["default_slots"]),
        })
    return windows


def _run_retention_cleanup(conn=None) -> dict:
    temp_conn = None
    if conn is None:
        temp_conn = sqlite3.connect(DATABASE)
        temp_conn.row_factory = sqlite3.Row
        conn = temp_conn
    try:
        settings = _get_runtime_backup_settings(conn)
        retention_settings = get_retention_policy(conn)
        policy = _build_retention_policy_windows(retention_settings)
        locations = _database_backup_locations(settings)
        all_snapshots = list_database_backups(locations)
        to_delete = apply_retention_policy(all_snapshots, policy)
        deleted: list[str] = []
        errors: list[str] = []
        for mp in to_delete:
            safe_mp = _resolve_allowed_backup_manifest_path(mp)
            if not safe_mp or not os.path.exists(safe_mp):
                continue
            try:
                delete_database_snapshot(safe_mp, logger=logger)
                deleted.append(safe_mp)
            except Exception as exc:
                errors.append(str(exc))
        if deleted:
            logger.info("Política de retenção removeu %d snapshot(s).", len(deleted))
        return {"deleted": deleted, "errors": errors}
    finally:
        if temp_conn is not None:
            temp_conn.close()


def _drive_settings_defaults() -> dict[str, str]:
    return {
        "gdrive_enabled": "0",
        "gdrive_dest_folder": "Backups/sistema",
        "gdrive_access_token": "",
        "gdrive_refresh_token": "",
        "gdrive_expires_at": "",
        "gdrive_account_email": "",
        "gdrive_last_upload_at": "",
        "gdrive_last_upload_error": "",
        "onedrive_enabled": "0",
        "onedrive_dest_folder": "Backups/sistema",
        "onedrive_access_token": "",
        "onedrive_refresh_token": "",
        "onedrive_expires_at": "",
        "onedrive_account_email": "",
        "onedrive_last_upload_at": "",
        "onedrive_last_upload_error": "",
    }


def get_drive_settings(conn) -> dict[str, str]:
    defaults = _drive_settings_defaults()
    try:
        rows = conn.execute(
            "SELECT chave, valor FROM configuracoes_backup"
            " WHERE chave LIKE 'gdrive_%' OR chave LIKE 'onedrive_%'"
        ).fetchall()
        settings = dict(defaults)
        for row in rows:
            settings[str(row["chave"])] = str(row["valor"])
        return settings
    except sqlite3.OperationalError:
        return defaults


def _save_drive_config(conn, updates: dict[str, str]) -> None:
    ensure_backup_settings_schema(conn)
    for chave, valor in updates.items():
        conn.execute(
            """
            INSERT INTO configuracoes_backup (chave, valor, atualizado_em)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor, atualizado_em = datetime('now')
            """,
            (chave, str(valor)),
        )


_CLOUD_FOLDER_PROVIDERS = {"google", "onedrive"}


def _normalize_cloud_folder_provider(provider: str) -> str:
    normalized = str(provider or "").strip().lower()
    if normalized not in _CLOUD_FOLDER_PROVIDERS:
        raise ValueError("Provedor inválido.")
    return normalized


def _save_cloud_drive_folder_setting(
    conn,
    *,
    provider: str,
    folder_id: str,
    folder_name: str,
    folder_path_label: str,
    drive_id: str = "",
) -> None:
    ensure_cloud_backup_schema(conn)
    safe_provider = _normalize_cloud_folder_provider(provider)
    safe_folder_id = (folder_id or "").strip()
    safe_folder_name = (folder_name or "").strip()
    safe_folder_path = (folder_path_label or "").strip()
    safe_drive_id = (drive_id or "").strip()
    conn.execute(
        """
        INSERT INTO cloud_drive_settings (provider, folder_id, folder_name, folder_path_label, drive_id, updated_at)
        VALUES (?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(provider) DO UPDATE SET
            folder_id = excluded.folder_id,
            folder_name = excluded.folder_name,
            folder_path_label = excluded.folder_path_label,
            drive_id = excluded.drive_id,
            updated_at = datetime('now')
        """,
        (
            safe_provider,
            safe_folder_id or None,
            safe_folder_name or None,
            safe_folder_path or None,
            safe_drive_id or None,
        ),
    )


def _get_cloud_drive_folder_setting(conn, provider: str) -> dict[str, str]:
    ensure_cloud_backup_schema(conn)
    safe_provider = _normalize_cloud_folder_provider(provider)
    row = conn.execute(
        """
        SELECT provider, folder_id, folder_name, folder_path_label, drive_id, updated_at
          FROM cloud_drive_settings
         WHERE provider = ?
         LIMIT 1
        """,
        (safe_provider,),
    ).fetchone()
    if not row:
        return {
            "provider": safe_provider,
            "folder_id": "",
            "folder_name": "",
            "folder_path_label": "",
            "drive_id": "",
            "updated_at": "",
        }
    return {
        "provider": str(row["provider"] or safe_provider),
        "folder_id": str(row["folder_id"] or ""),
        "folder_name": str(row["folder_name"] or ""),
        "folder_path_label": str(row["folder_path_label"] or ""),
        "drive_id": str(row["drive_id"] or ""),
        "updated_at": str(row["updated_at"] or ""),
    }


def _extract_oauth_scopes(token_json: str) -> list[str]:
    try:
        payload = json.loads(token_json or "{}")
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict):
        return []
    scopes = payload.get("scopes") or []
    if isinstance(scopes, list):
        return [str(item).strip() for item in scopes if str(item).strip()]
    if isinstance(scopes, str) and scopes.strip():
        return [scope.strip() for scope in scopes.split() if scope.strip()]
    return []


def _set_active_cloud_account(conn, provider: str, account_email: str, token_json: str) -> None:
    ensure_cloud_backup_schema(conn)
    encrypted_token_json = encrypt_token_json_for_storage(
        token_json,
        env=str(app.config.get("APP_ENV") or os.getenv("APP_ENV") or "development"),
    )
    conn.execute(
        "UPDATE cloud_accounts SET active = 0, updated_at = datetime('now') WHERE provider = ? AND active = 1",
        (provider,),
    )
    conn.execute(
        """
        INSERT INTO cloud_accounts (provider, account_email, token_json, connected_at, updated_at, active)
        VALUES (?, ?, ?, datetime('now'), datetime('now'), 1)
        """,
        (provider, (account_email or "").strip() or None, encrypted_token_json),
    )


def _get_active_cloud_account(conn, provider: str):
    ensure_cloud_backup_schema(conn)
    row = conn.execute(
        """
        SELECT id, provider, account_email, token_json, connected_at, updated_at, active
          FROM cloud_accounts
         WHERE provider = ? AND active = 1
      ORDER BY id DESC
        LIMIT 1
        """,
        (provider,),
    ).fetchone()
    if not row:
        return None

    payload = dict(row)
    try:
        payload["token_json"] = decrypt_token_json_from_storage(
            str(payload.get("token_json") or ""),
            env=str(app.config.get("APP_ENV") or os.getenv("APP_ENV") or "development"),
        )
        payload["token_json_available"] = True
        payload["token_json_error"] = ""
    except TokenEncryptionError as exc:
        logger.warning("Token OAuth indisponivel para %s: %s", provider, exc)
        payload["token_json"] = ""
        payload["token_json_available"] = False
        payload["token_json_error"] = str(exc)
    return payload


def _require_cloud_token_encryption_ready() -> None:
    validate_token_encryption_configuration(
        env=str(app.config.get("APP_ENV") or os.getenv("APP_ENV") or "development")
    )


def _update_cloud_account_token(
    conn,
    *,
    account_id: int,
    token_json: str,
    account_email: str | None = None,
) -> None:
    encrypted_token_json = encrypt_token_json_for_storage(
        token_json,
        env=str(app.config.get("APP_ENV") or os.getenv("APP_ENV") or "development"),
    )
    if account_email is None:
        conn.execute(
            "UPDATE cloud_accounts SET token_json = ?, updated_at = datetime('now') WHERE id = ?",
            (encrypted_token_json, int(account_id)),
        )
        return

    conn.execute(
        "UPDATE cloud_accounts SET token_json = ?, account_email = ?, updated_at = datetime('now') WHERE id = ?",
        (encrypted_token_json, account_email or None, int(account_id)),
    )


def _record_backup_log(
    conn,
    *,
    provider: str,
    file_name: str,
    file_size: int | None,
    status: str,
    error_message: str = "",
) -> None:
    ensure_cloud_backup_schema(conn)
    normalized_status = "sucesso" if status == "sucesso" else "erro"
    conn.execute(
        """
        INSERT INTO backup_logs (provider, file_name, file_size, status, error_message)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            provider,
            (file_name or "").strip() or None,
            int(file_size) if file_size not in (None, "") else None,
            normalized_status,
            (error_message or "")[:500],
        ),
    )


def _list_backup_logs(conn, *, provider: str | None = None, limit: int = 20):
    ensure_cloud_backup_schema(conn)
    safe_limit = max(1, min(int(limit or 20), 200))
    params: list[object] = []
    sql = "SELECT id, provider, file_name, file_size, status, error_message, created_at FROM backup_logs"
    if provider:
        sql += " WHERE provider = ?"
        params.append(provider)
    sql += " ORDER BY datetime(created_at) DESC, id DESC LIMIT ?"
    params.append(safe_limit)
    return conn.execute(sql, tuple(params)).fetchall()


def _maybe_upload_to_drives(snapshot_path: str, conn=None) -> None:
    """Upload snapshot to enabled cloud drive providers, then apply remote retention."""
    temp_conn = None
    if conn is None:
        temp_conn = sqlite3.connect(DATABASE)
        temp_conn.row_factory = sqlite3.Row
        conn = temp_conn
    try:
        drive_settings = get_drive_settings(conn)
        retention_settings = get_retention_policy(conn)
        policy = _build_retention_policy_windows(retention_settings)

        for provider in ("google", "onedrive"):
            prefix = "gdrive" if provider == "google" else "onedrive"
            enabled = str(drive_settings.get(f"{prefix}_enabled") or "0") in {"1", "true"}
            if not enabled or not drive_settings.get(f"{prefix}_access_token"):
                continue

            dest_folder = drive_settings.get(f"{prefix}_dest_folder") or "Backups/sistema"
            try:
                if provider == "google":
                    token, updates = _cd.refresh_google_if_needed(drive_settings)
                else:
                    token, updates = _cd.refresh_onedrive_if_needed(drive_settings)

                if updates:
                    _save_drive_config(conn, updates)
                    drive_settings.update(updates)
                    conn.commit()

                if provider == "google":
                    _cd.google_upload(token, snapshot_path, dest_folder)
                else:
                    _cd.onedrive_upload(token, snapshot_path, dest_folder)

                now_iso = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
                _save_drive_config(conn, {
                    f"{prefix}_last_upload_at": now_iso,
                    f"{prefix}_last_upload_error": "",
                })
                conn.commit()
                logger.info("Drive upload [%s] concluído: %s", provider, snapshot_path)

                try:
                    _cd.apply_retention_to_drive(
                        provider, token=token, dest_folder=dest_folder,
                        policy=policy, logger=logger,
                    )
                except Exception as exc:
                    logger.warning("Retenção remota [%s] falhou: %s", provider, exc)

            except Exception as exc:
                logger.warning("Drive upload [%s] falhou: %s", provider, exc)
                try:
                    _save_drive_config(conn, {f"{prefix}_last_upload_error": str(exc)[:200]})
                    conn.commit()
                except Exception:
                    pass
    finally:
        if temp_conn is not None:
            temp_conn.close()


def _format_drive_timestamp(ts_iso: str) -> str:
    if not ts_iso:
        return ""
    try:
        dt = datetime.datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
        local_dt = dt.astimezone()
        return local_dt.strftime("%d/%m/%Y às %H:%M")
    except Exception:
        return ts_iso


def _persist_user_access_overrides(conn, usuario_id: int, access_level: str, overrides: dict[str, str]) -> None:
    ensure_usuario_access_schema(conn)
    defaults = merge_resource_scopes(access_level)
    conn.execute("DELETE FROM usuarios_permissoes_acesso WHERE usuario_id = ?", (usuario_id,))
    for recurso in ACCESS_RESOURCE_ORDER:
        if recurso not in overrides:
            continue
        escopo = normalize_permission_scope(overrides[recurso], defaults.get(recurso, "none"))
        if escopo == defaults.get(recurso, "none"):
            continue
        conn.execute(
            "INSERT INTO usuarios_permissoes_acesso (usuario_id, recurso, escopo) VALUES (?, ?, ?)",
            (usuario_id, recurso, escopo),
        )


def _parse_access_overrides_from_form(form) -> dict[str, str]:
    overrides = {}
    for recurso in ACCESS_RESOURCE_ORDER:
        value = (form.get(f"scope_{recurso}") or "").strip()
        if not value or value == "inherit":
            continue
        overrides[recurso] = normalize_permission_scope(value, "none")
    return overrides


def get_student_request_update_alert(conn, aluno_id: int | None):
    if not aluno_id:
        return None

    rows = conn.execute(
        """
        SELECT id
          FROM requisicoes
         WHERE aluno_id = ?
           AND aluno_update_notified_at IS NOT NULL
           AND aluno_update_seen_at IS NULL
      ORDER BY COALESCE(aluno_update_notified_at, data_processamento, data_solicitacao) DESC,
               id DESC
        """,
        (aluno_id,),
    ).fetchall()
    if not rows:
        return None

    return {
        "requisicao_ids": [row["id"] for row in rows],
        "alerta": {
            "mensagem": resolve_user_message("Houve atualizações nas suas solicitações."),
            "bg_color": AUTO_ALERT_YELLOW_BG,
            "border_color": AUTO_ALERT_YELLOW_BORDER,
            "href": aluno_url("aluno_minhas_requisicoes"),
        },
    }


def mark_student_request_updates_seen(conn, requisicao_ids: list[int] | None):
    if not requisicao_ids:
        return

    placeholders = ", ".join("?" for _ in requisicao_ids)
    seen_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        f"UPDATE requisicoes SET aluno_update_seen_at = ? WHERE id IN ({placeholders})",
        (seen_at, *requisicao_ids),
    )


def _admin_request_alert_kind(access_level: str | None) -> str | None:
    normalized = canonicalize_access_level(access_level, default_access_level_for_user_type("admin"))
    if normalized == "admin_total":
        return "admin_new_request"
    if normalized == "administrativo":
        return "coordinator_new_request"
    return None


def get_admin_new_request_alert(conn, usuario_id: int | None, access_level: str | None):
    alert_kind = _admin_request_alert_kind(access_level)
    if not usuario_id or not alert_kind:
        return None

    ensure_requisicao_alert_receipts_table(conn)
    rows = conn.execute(
        """
        SELECT r.id
          FROM requisicoes r
         WHERE r.status = 'Pendente'
           AND NOT EXISTS (
                SELECT 1
                  FROM requisicao_alerta_receipts receipts
                 WHERE receipts.requisicao_id = r.id
                   AND receipts.usuario_id = ?
                   AND receipts.alert_kind = ?
           )
      ORDER BY COALESCE(r.data_solicitacao, '') DESC,
               r.id DESC
        """,
        (usuario_id, alert_kind),
    ).fetchall()
    if not rows:
        return None

    return {
        "requisicao_ids": [row["id"] for row in rows],
        "alerta": {
            "mensagem": resolve_user_message("Há novas solicitações aguardando análise."),
            "bg_color": AUTO_ALERT_YELLOW_BG,
            "border_color": AUTO_ALERT_YELLOW_BORDER,
            "href": url_for("admin_requisicoes"),
        },
    }


def mark_admin_new_request_alert_seen(
    conn,
    requisicao_ids: list[int] | None,
    usuario_id: int | None,
    access_level: str | None,
):
    alert_kind = _admin_request_alert_kind(access_level)
    if not requisicao_ids or not usuario_id or not alert_kind:
        return

    ensure_requisicao_alert_receipts_table(conn)
    seen_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.executemany(
        """
        INSERT OR IGNORE INTO requisicao_alerta_receipts (requisicao_id, usuario_id, alert_kind, seen_at)
        VALUES (?, ?, ?, ?)
        """,
        [(requisicao_id, usuario_id, alert_kind, seen_at) for requisicao_id in requisicao_ids],
    )




def validar_integridade_versionamento_atividades(conn, *, raise_on_error: bool = True) -> list[str]:
    """Valida consistÃªncia estrutural do versionamento AAC/AEU sem mutar dados."""
    required_tables = ("atividade_base", "atividade_versao", "atividade_transicao")
    existing_tables = {
        row[0]
        for row in conn.execute(
            f"""
            SELECT name
              FROM sqlite_master
             WHERE type = 'table'
               AND name IN ({",".join("?" for _ in required_tables)})
            """,
            required_tables,
        ).fetchall()
    }
    missing_tables = [name for name in required_tables if name not in existing_tables]

    issues: list[str] = []
    if missing_tables:
        issues.append(
            "Schema de versionamento indisponÃ­vel para validaÃ§Ã£o: faltam as tabelas "
            + ", ".join(missing_tables)
            + "."
        )

    if not missing_tables:
        transition_rows = conn.execute(
            """
            SELECT t.id,
                   COALESCE(TRIM(t.justificativa), '') AS justificativa,
                   src.id AS from_id,
                   src.atividade_base_id AS from_base_id,
                   src.eixo AS from_eixo,
                   dst.id AS to_id,
                   dst.atividade_base_id AS to_base_id,
                   dst.eixo AS to_eixo
              FROM atividade_transicao t
              LEFT JOIN atividade_versao src ON src.id = t.from_atividade_versao_id
              LEFT JOIN atividade_versao dst ON dst.id = t.to_atividade_versao_id
             WHERE t.tipo_transicao = 'aac_para_aeu'
            """
        ).fetchall()
        for row in transition_rows:
            transition_errors = []
            if row["from_id"] is None or row["to_id"] is None:
                transition_errors.append("from/to atividade_versao ausente")
            if not row["justificativa"]:
                transition_errors.append("justificativa ausente")
            if row["from_eixo"] != "AAC" or row["to_eixo"] != "AEU":
                transition_errors.append(
                    f"eixos incompatÃ­veis ({row['from_eixo'] or 'NULL'} -> {row['to_eixo'] or 'NULL'})"
                )
            if row["from_base_id"] is None or row["to_base_id"] is None or row["from_base_id"] != row["to_base_id"]:
                transition_errors.append("atividade_base divergente entre origem e destino")
            if transition_errors:
                issues.append(
                    f"atividade_transicao {row['id']} marcada como aac_para_aeu invÃ¡lida: "
                    + "; ".join(transition_errors)
                    + "."
                )

        mixed_axis_bases = conn.execute(
            """
            SELECT av.atividade_base_id,
                   ab.nome_conceito,
                   SUM(CASE WHEN av.status = 'ativa' AND av.eixo = 'AAC' THEN 1 ELSE 0 END) AS total_aac_ativas,
                   SUM(CASE WHEN av.status = 'ativa' AND av.eixo = 'AEU' THEN 1 ELSE 0 END) AS total_aeu_ativas
              FROM atividade_versao av
              JOIN atividade_base ab ON ab.id = av.atividade_base_id
             GROUP BY av.atividade_base_id, ab.nome_conceito
            HAVING total_aac_ativas > 0
               AND total_aeu_ativas > 0
            """
        ).fetchall()
        for row in mixed_axis_bases:
            valid_transition = conn.execute(
                """
                SELECT t.id
                  FROM atividade_transicao t
                  JOIN atividade_versao src ON src.id = t.from_atividade_versao_id
                  JOIN atividade_versao dst ON dst.id = t.to_atividade_versao_id
                 WHERE t.tipo_transicao = 'aac_para_aeu'
                   AND src.atividade_base_id = ?
                   AND dst.atividade_base_id = ?
                   AND src.status = 'ativa'
                   AND dst.status = 'ativa'
                   AND src.eixo = 'AAC'
                   AND dst.eixo = 'AEU'
                   AND COALESCE(TRIM(t.justificativa), '') <> ''
                 LIMIT 1
                """,
                (row["atividade_base_id"], row["atividade_base_id"]),
            ).fetchone()
            if valid_transition is None:
                issues.append(
                    "atividade_base "
                    f"{row['atividade_base_id']} ({row['nome_conceito']}) possui versÃµes AAC/AEU ativas "
                    "sem transiÃ§Ã£o aac_para_aeu vÃ¡lida e justificada."
                )

    if issues and raise_on_error:
        raise ValueError("Integridade do versionamento de atividades invÃ¡lida:\n- " + "\n- ".join(issues))
    return issues


# ===================== Helpers: Catálogo Versionado (read-only) =====================

























# ===================== App / Config =====================

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
_log_fmt = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
try:
    logs_dir = (os.getenv("APP_LOG_DIR") or "").strip() or os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    os.makedirs(logs_dir, exist_ok=True)
    log_path = os.path.join(logs_dir, "app.log")
    # Evita conflito de rotação no Windows: se der erro, cai para StreamHandler
    rfh = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=1, encoding="utf-8")
    rfh.setFormatter(_log_fmt)
    logger.addHandler(rfh)
except Exception as _e:
    sh = logging.StreamHandler()
    sh.setFormatter(_log_fmt)
    logger.addHandler(sh)

# Diretórios e app principal
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
_TEMPLATES_DIR = os.path.join(_APP_DIR, "templates")
USE_ALUNO_BLUEPRINT = True




app = create_app(register_aluno_blueprint=USE_ALUNO_BLUEPRINT)
app.add_template_global(resolve_user_message, name="user_message")


def aluno_url(endpoint: str, **values):
    resolved_endpoint = f"aluno.{endpoint}" if USE_ALUNO_BLUEPRINT else endpoint
    return url_for(resolved_endpoint, **values)

# Config via ambiente (com defaults seguros)
# `app.secret_key`, cookies de sessão, lifetime e flags CSRF já são aplicados
# centralmente em `app/__init__.py::create_app`. Não sobrescreva aqui.
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB
Compress(app)
# Garante recarregamento de templates em dev
app.config["TEMPLATES_AUTO_RELOAD"] = not app.config.get("IS_PRODUCTION", False)
try:
    app.jinja_env.auto_reload = not app.config.get("IS_PRODUCTION", False)
except Exception:
    pass
try:
    # Garanta que o searchpath está correto e único
    app.jinja_loader.searchpath = [_TEMPLATES_DIR]
except Exception:
    pass

# Caminho robusto do banco, resolvido canonicamente por app.db.
app.config["DATABASE_PATH"] = DATABASE
app.config["LOCAL_BACKUP_DIR"] = os.getenv(
    "APP_LOCAL_BACKUP_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "backups", "local"),
)
app.config["CLOUD_BACKUP_DIR"] = os.getenv(
    "APP_CLOUD_BACKUP_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "backups", "cloud_sync"),
)
app.config["CLOUD_SYNC_INTERVAL_SECONDS"] = int(
    os.getenv("APP_CLOUD_SYNC_INTERVAL_SECONDS", "600")
)
app.config["EXTERNAL_BACKUP_URL"] = os.getenv("APP_EXTERNAL_BACKUP_URL", "")
app.config["EXTERNAL_BACKUP_TOKEN"] = os.getenv("APP_EXTERNAL_BACKUP_TOKEN", "")
app.config["EXTERNAL_BACKUP_ENABLED"] = os.getenv("APP_EXTERNAL_BACKUP_ENABLED", "0") in ("1", "true", "True")
bind_backup_settings_runtime_app(app)


REPORTE_STATUS_OPTIONS = (
    "Novo",
    "Em análise",
    "Resolvido",
)








def _format_bytes_label(size_bytes):
    if size_bytes in (None, ""):
        return "-"
    size = float(size_bytes)
    units = ("B", "KB", "MB", "GB")
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
        size /= 1024
    return f"{int(size_bytes)} B"


def _get_runtime_backup_settings(conn=None):
    temp_conn = None
    if conn is None:
        temp_conn = sqlite3.connect(DATABASE)
        temp_conn.row_factory = sqlite3.Row
        conn = temp_conn
    try:
        try:
            settings = get_backup_settings(conn)
        except sqlite3.OperationalError:
            settings = _backup_settings_defaults()
        _apply_backup_settings_to_app(settings)
        return settings
    finally:
        if temp_conn is not None:
            temp_conn.close()


def _database_backup_locations(settings=None):
    settings = settings or _backup_settings_defaults()
    return {
        "local": settings.get("local_backup_dir") or app.config.get("LOCAL_BACKUP_DIR"),
        "cloud": settings.get("cloud_backup_dir") or app.config.get("CLOUD_BACKUP_DIR"),
    }


def _path_within_root(candidate_path: str, root_path: str | None) -> bool:
    if not candidate_path or not root_path:
        return False
    candidate_abs = os.path.abspath(candidate_path)
    root_abs = os.path.abspath(root_path)
    try:
        return os.path.commonpath([candidate_abs, root_abs]) == root_abs
    except ValueError:
        return False


def _resolve_allowed_backup_manifest_path(manifest_path: str) -> str | None:
    candidate = os.path.abspath(manifest_path or "")
    for root in _database_backup_locations(_get_runtime_backup_settings()).values():
        if _path_within_root(candidate, root):
            return candidate
    return None


def _build_database_admin_context(conn):
    settings = _get_runtime_backup_settings(conn)
    oauth_context = _build_oauth_redirect_context()
    schema_status = get_schema_status(conn)
    backups = list_database_backups(_database_backup_locations(settings))
    for backup in backups:
        backup["size_label"] = _format_bytes_label(backup.get("size_bytes"))
        backup["schema_version"] = (backup.get("schema_status") or {}).get("schema_version")
        backup["target_schema_version"] = (backup.get("schema_status") or {}).get("target_schema_version")
    latest_cloud_backup = next((item for item in backups if item.get("location") == "cloud"), None)
    retention_policy = get_retention_policy(conn)
    drive_settings = get_drive_settings(conn)
    google_folder_setting = _get_cloud_drive_folder_setting(conn, "google")
    onedrive_folder_setting = _get_cloud_drive_folder_setting(conn, "onedrive")
    google_account = _get_active_cloud_account(conn, "google")
    onedrive_account = _get_active_cloud_account(conn, "onedrive")
    google_backup_logs = []
    onedrive_backup_logs = []
    for row in _list_backup_logs(conn, provider="google", limit=20):
        payload = dict(row)
        payload["size_label"] = _format_bytes_label(payload.get("file_size"))
        google_backup_logs.append(payload)
    for row in _list_backup_logs(conn, provider="onedrive", limit=20):
        payload = dict(row)
        payload["size_label"] = _format_bytes_label(payload.get("file_size"))
        onedrive_backup_logs.append(payload)

    google_connected = bool(google_account)
    google_legacy_connection_detected = bool(
        (drive_settings.get("gdrive_access_token") or "").strip()
    ) and not google_connected
    google_legacy_account_email = str(drive_settings.get("gdrive_account_email") or "")
    google_account_email = ""
    if google_account:
        google_account_email = str(google_account["account_email"] or "")
    if not google_account_email:
        google_account_email = google_legacy_account_email

    onedrive_connected = bool(onedrive_account)
    onedrive_account_email = ""
    if onedrive_account:
        onedrive_account_email = str(onedrive_account["account_email"] or "")
    if not onedrive_account_email:
        onedrive_account_email = str(drive_settings.get("onedrive_account_email") or "")

    google_folder_label = (
        google_folder_setting.get("folder_path_label")
        or google_folder_setting.get("folder_name")
        or ""
    )
    onedrive_folder_label = (
        onedrive_folder_setting.get("folder_path_label")
        or onedrive_folder_setting.get("folder_name")
        or ""
    )
    if google_folder_label:
        drive_settings["gdrive_dest_folder"] = google_folder_label
    if onedrive_folder_label:
        drive_settings["onedrive_dest_folder"] = onedrive_folder_label
    google_client_id = str(os.environ.get("GOOGLE_CLIENT_ID") or "").strip()
    google_picker_api_key = str(os.environ.get("GOOGLE_PICKER_API_KEY") or "").strip()
    google_app_id = str(os.environ.get("GOOGLE_APP_ID") or "").strip()

    return {
        "schema_status": schema_status,
        "backups": backups,
        "backup_settings": settings,
        "local_backup_dir": settings.get("local_backup_dir") or app.config.get("LOCAL_BACKUP_DIR"),
        "cloud_backup_dir": settings.get("cloud_backup_dir") or app.config.get("CLOUD_BACKUP_DIR"),
        "cloud_sync_interval_seconds": settings.get("cloud_sync_interval_seconds") or app.config.get("CLOUD_SYNC_INTERVAL_SECONDS", 300),
        "external_backup_url": settings.get("external_backup_url") or "",
        "external_backup_enabled": str(settings.get("external_backup_enabled") or "0") in {"1", "true", "True"},
        "latest_cloud_backup": latest_cloud_backup,
        "retention_policy": retention_policy,
        "retention_windows_meta": _RETENTION_WINDOWS_META,
        "retention_interval_options": _RETENTION_INTERVAL_OPTIONS,
        "drive_settings": drive_settings,
        "gdrive_configured": bool(os.environ.get("GOOGLE_CLIENT_ID")),
        "onedrive_configured": bool(
            (os.environ.get("MS_CLIENT_ID") or "").strip()
            or (os.environ.get("ONEDRIVE_CLIENT_ID") or "").strip()
        ),
        "gdrive_connected": google_connected,
        "gdrive_legacy_connection_detected": google_legacy_connection_detected,
        "gdrive_legacy_account_email": google_legacy_account_email,
        "onedrive_connected": onedrive_connected,
        "gdrive_last_upload_label": _format_drive_timestamp(drive_settings.get("gdrive_last_upload_at") or ""),
        "onedrive_last_upload_label": _format_drive_timestamp(drive_settings.get("onedrive_last_upload_at") or ""),
        "google_drive_connected": google_connected,
        "google_drive_account_email": google_account_email,
        "google_client_id": google_client_id,
        "google_picker_api_key": google_picker_api_key,
        "google_app_id": google_app_id,
        "google_picker_configured": bool(google_client_id and google_picker_api_key and google_app_id),
        "google_backup_logs": google_backup_logs,
        "onedrive_account_email": onedrive_account_email,
        "onedrive_backup_logs": onedrive_backup_logs,
        "google_folder_setting": google_folder_setting,
        "onedrive_folder_setting": onedrive_folder_setting,
        "google_folder_label": google_folder_label or (drive_settings.get("gdrive_dest_folder") or "Backups/sistema"),
        "onedrive_folder_label": onedrive_folder_label or (drive_settings.get("onedrive_dest_folder") or "SGAA - Backups"),
        "oauth_public_base_url": oauth_context["oauth_public_base_url"],
        "google_oauth_callback_uri": oauth_context["google_oauth_callback_uri"],
        "onedrive_oauth_callback_uri": oauth_context["onedrive_oauth_callback_uri"],
        "oauth_config_error": oauth_context["oauth_config_error"],
    }


def _upload_snapshot_if_external_enabled(snapshot: dict[str, object], settings: dict[str, str]):
    if str(settings.get("external_backup_enabled") or "0") not in {"1", "true", "True"}:
        return {"ok": False, "skipped": True, "reason": "external_disabled"}

    server_url = (settings.get("external_backup_url") or "").strip()
    if not server_url:
        return {"ok": False, "skipped": True, "reason": "external_url_missing"}

    result = upload_snapshot_to_external_server(
        str(snapshot["database_path"]),
        str(snapshot["manifest_path"]),
        server_url=server_url,
        token=(settings.get("external_backup_token") or "").strip() or None,
        logger=logger,
    )
    return {"ok": True, "skipped": False, "result": result}


def _maybe_sync_database_snapshot(force: bool = False, conn=None):
    settings = _get_runtime_backup_settings(conn)
    cloud_root = settings.get("cloud_backup_dir") or app.config.get("CLOUD_BACKUP_DIR")
    if not cloud_root:
        return {"ok": False, "skipped": True, "reason": "cloud_backup_disabled"}

    temp_conn = None
    if conn is None:
        conn = getattr(g, "db", None)
    if conn is None and not force:
        return {"ok": True, "skipped": True, "reason": "no_open_connection"}
    if conn is None:
        temp_conn = sqlite3.connect(DATABASE)
        temp_conn.row_factory = sqlite3.Row
        conn = temp_conn
    try:
        return maybe_sync_database_to_cloud(
            DATABASE,
            cloud_root,
            schema_status=get_schema_status(conn),
            min_interval_seconds=int(settings.get("cloud_sync_interval_seconds") or app.config.get("CLOUD_SYNC_INTERVAL_SECONDS", 300)),
            force=force,
            logger=logger,
        )
    finally:
        if temp_conn is not None:
            temp_conn.close()























































# Headers de segurança básicos em todas as respostas
@app.after_request
def add_security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    resp.headers.setdefault("Referrer-Policy", "no-referrer-when-downgrade")
    try:
        if request.endpoint != "static" and resp.status_code < 500:
            sync_result = _maybe_sync_database_snapshot(force=False)
            if sync_result.get("ok") and not sync_result.get("skipped"):
                _run_retention_cleanup()
                db_path = (sync_result.get("snapshot") or {}).get("database_path") or ""
                if db_path:
                    _maybe_upload_to_drives(db_path, conn=getattr(g, "db", None))
    except Exception as exc:
        logger.warning("Falha ao sincronizar snapshot do banco para nuvem: %s", exc)
    return resp

def _admin_access_denied_response(resource: str, required_scope: str):
    message = resolve_user_message(
        f"Seu perfil não possui acesso {permission_scope_label(required_scope).lower()} para {ACCESS_RESOURCES_META.get(resource, {}).get('label', 'este módulo')}."
    )
    if _is_ajax_request():
        return jsonify({
            "ok": False,
            "error": "forbidden",
            "resource": resource,
            "required_scope": required_scope,
            "message": message,
        }), 403
    flash(message, "error")
    return redirect(url_for("admin_dashboard"))


def _audit_missing_admin_authorization_configuration(classification: dict[str, object]) -> None:
    """Production-only shadow evidence; never include request payload or secrets."""
    try:
        logger.error(
            "event=admin_rbac_missing_configuration endpoint=%s method=%s rule=%s "
            "access_level=%s rollout_mode=production_shadow",
            classification.get("endpoint"),
            classification.get("method"),
            classification.get("rule"),
            session.get("access_level"),
        )
    except Exception:
        # Shadow auditing must never turn a missing-policy observation into a
        # production request failure.  Do not recurse into logging or expose
        # request data through another fallback channel.
        return


@app.before_request
def enforce_admin_access_control():
    classification = classify_governed_admin_request(
        request.endpoint,
        request.url_rule,
        request.method,
    )
    if session.get("user_type") != "admin":
        return None
    if not classification["governed"]:
        return None
    kind = classification["kind"]
    if kind == "exemption":
        return None
    if kind in {"missing_configuration", "invalid_configuration"}:
        if app.config.get("IS_PRODUCTION"):
            _audit_missing_admin_authorization_configuration(classification)
            return None
        raise AdminAuthorizationConfigurationError(
            "Resolved governed endpoint lacks exactly one RBAC requirement or approved exemption: "
            f"{classification.get('endpoint')} {classification.get('method')}"
        )
    requirement = classification["requirement"]
    if requirement is None:  # Defensive invariant; classifier keeps this unreachable.
        raise AdminAuthorizationConfigurationError("Governed request classifier returned no requirement")
    resource, required_scope = requirement
    auth_context = _get_current_admin_access_context(force_reload=True)
    g.admin_permission_requirement = {"resource": resource, "scope": required_scope}
    if _admin_can(resource, required_scope, auth_context):
        return None
    return _admin_access_denied_response(resource, required_scope)


@app.context_processor
def inject_admin_access_helpers():
    requirement = get_admin_permission_requirement(request.endpoint or "", request.method)
    auth_context = _get_current_admin_access_context() if session.get("user_type") == "admin" else {
        "is_admin": False,
        "access_level": None,
        "access_level_label": None,
        "overrides": {},
        "effective_scopes": {},
        "scope_groups": [],
    }
    current_resource = requirement[0] if requirement else None
    current_scope = requirement[1] if requirement else None

    return {
        "auth_context": auth_context,
        "auth_current_resource": current_resource,
        "auth_current_required_scope": current_scope,
        "auth_current_can_edit": _admin_can(current_resource, "edit", auth_context) if current_resource else False,
        "auth_current_can_full": _admin_can(current_resource, "full", auth_context) if current_resource else False,
        "auth_can": lambda resource, scope="view": _admin_can(resource, scope, auth_context),
        "auth_scope": lambda resource: auth_context.get("effective_scopes", {}).get(resource, "none"),
        "auth_scope_label": permission_scope_label,
    }


@app.context_processor
def inject_editable_message_templates():
    try:
        templates = frontend_message_templates(get_db_connection())
    except Exception:
        templates = {}
    return {
        "app_frontend_messages": templates,
    }

# ===================== Rotas Aluno: Arquivos =====================

# ===================== Rotas Aluno: Minhas Requisições =====================

def _coerce_aluno_snapshot_scalar(value):
    """Converte um campo escalar do payload do snapshot em string segura.

    Aceita apenas tipos escalares (str/int/float); qualquer outro tipo
    (dict/list/tuple/set) é descartado para evitar vazamento de estrutura
    complexa para o template do aluno. Strings vazias viram None.
    """
    if value is None:
        return None
    if isinstance(value, (dict, list, tuple, set)):
        return None
    if isinstance(value, str):
        trimmed = value.strip()
        return trimmed or None
    return value


def _build_aluno_requisicao_snapshot_display(
    *,
    atividade_versao_id,
    codigo_normativo_snapshot,
    regra_snapshot_json,
    versao_row,
):
    """Extrai um payload read-only de snapshot para o template do aluno.

    Retorna None quando não houver snapshot registrado. Quando o payload
    JSON for inválido, faz fallback silencioso usando apenas os campos
    disponíveis no banco, sem nunca lançar exceção.
    """
    has_atividade_versao_id = atividade_versao_id not in (None, "")
    has_codigo_normativo = bool(str(codigo_normativo_snapshot or "").strip())
    if not has_atividade_versao_id and not has_codigo_normativo:
        return None

    display = {
        "snapshot_versionado_presente": True,
        "snapshot_vn": None,
        "snapshot_codigo": None,
        "snapshot_eixo": None,
        "snapshot_grupo": None,
        "snapshot_written_at": None,
        "snapshot_flow_origin": None,
    }

    if versao_row is not None:
        numero_versao = versao_row.get("numero_versao") if isinstance(versao_row, dict) else None
        if numero_versao is not None:
            try:
                display["snapshot_vn"] = int(numero_versao)
            except (TypeError, ValueError):
                display["snapshot_vn"] = None
        display["snapshot_codigo"] = _coerce_aluno_snapshot_scalar(
            versao_row.get("codigo_normativo") if isinstance(versao_row, dict) else None
        )
        display["snapshot_eixo"] = _coerce_aluno_snapshot_scalar(
            versao_row.get("eixo") if isinstance(versao_row, dict) else None
        )
        display["snapshot_grupo"] = _coerce_aluno_snapshot_scalar(
            versao_row.get("grupo") if isinstance(versao_row, dict) else None
        )

    parsed = None
    if regra_snapshot_json is not None:
        try:
            candidate = json.loads(str(regra_snapshot_json))
            if isinstance(candidate, dict):
                parsed = candidate
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed = None

    if parsed is not None:
        for key, target in (
            ("snapshot_codigo", "codigo_normativo"),
            ("snapshot_eixo", "eixo"),
            ("snapshot_grupo", "grupo"),
            ("snapshot_written_at", "snapshot_written_at"),
            ("snapshot_flow_origin", "flow_origin"),
        ):
            if display[key] is None:
                display[key] = _coerce_aluno_snapshot_scalar(parsed.get(target))
        payload_vn = parsed.get("atividade_versao_numero")
        if display["snapshot_vn"] is None and payload_vn is not None:
            try:
                display["snapshot_vn"] = int(payload_vn)
            except (TypeError, ValueError):
                pass

    if display["snapshot_codigo"] is None and has_codigo_normativo:
        display["snapshot_codigo"] = _coerce_aluno_snapshot_scalar(
            codigo_normativo_snapshot
        )

    return display



# Detalhe da requisição (Aluno)

# ===================== Helpers Novos (Cursos/Turmas) =====================

UPPER_CODE_RE = re.compile(r'^[A-Z-]+$')  # letras maiúsculas + hífen (ex.: PPA-NOT)

def periodo_corrente(ano_inicio: int | None, semestre_inicio: int | None, ref: date | None = None) -> int:
    """Período da turma contando a partir do (ano_inicio, semestre_inicio). Começa em 1."""
    if not ano_inicio or not semestre_inicio:
        return 1
    if ref is None:
        ref = date.today()
    sem_ref = 1 if ref.month <= 6 else 2
    delta = (ref.year - int(ano_inicio)) * 2 + (sem_ref - int(semestre_inicio))
    return max(1, delta + 1)

# ===================== DB Init / Migrações =====================


def proximo_numero_turma(conn, ano=None, semestre=None):
    """[LEGADO] Sugere próximo número de turma (global ou filtrado por ano/semestre)."""
    sql = "SELECT COALESCE(MAX(numero), 0) FROM turmas WHERE 1=1"
    params = []
    if ano is not None:
        sql += " AND ano = ?"; params.append(int(ano))
    if semestre is not None:
        sql += " AND semestre = ?"; params.append(int(semestre))
    maxn = conn.execute(sql, params).fetchone()[0]
    return (maxn or 0) + 1


def _format_dashboard_hours(value) -> str:
    total = float(value or 0)
    if total.is_integer():
        return str(int(total))
    return f"{total:.1f}".rstrip("0").rstrip(".")


def _format_dashboard_average(value) -> str:
    return f"{float(value or 0):.1f}".replace(".", ",")


def _format_dashboard_days(value) -> str:
    total = float(value or 0)
    if total.is_integer():
        return str(int(total))
    return f"{total:.1f}".replace(".", ",")


def _build_admin_dashboard_turma_cards(conn):
    ensure_turmas_matriz_schema(conn)

    attainment_bucket_specs = (
        {"label": "100%", "color": "#003366"},
        {"label": "75 a 100%", "color": "#2f6fa3"},
        {"label": "50 a 75%", "color": "#4d8cb5"},
        {"label": "25 a 50%", "color": "#d08b2f"},
        {"label": "0 a 25%", "color": "#cbd5e1"},
    )

    turma_rows = conn.execute(
        """
        SELECT t.id,
               t.nome,
               t.codigo,
               t.status,
               t.curso_id,
               t.matriz_id,
               t.ano_inicio,
               t.semestre_inicio,
               COUNT(a.id) AS total_alunos
               ,COALESCE(SUM(CASE WHEN a.status = 'Ativo' THEN 1 ELSE 0 END), 0) AS total_alunos_ativos
          FROM turmas t
          LEFT JOIN alunos a ON a.turma_id = t.id
      GROUP BY t.id, t.nome, t.codigo, t.status, t.curso_id, t.matriz_id, t.ano_inicio, t.semestre_inicio
      ORDER BY LOWER(COALESCE(t.codigo, t.nome, '')) ASC,
               t.id ASC
        """
    ).fetchall()

    if not turma_rows:
        return [], None, {
            "total_turmas": 0,
            "total_turmas_ativas": 0,
            "turmas_com_aac": 0,
            "turmas_com_aeu": 0,
            "media_alunos_por_turma_fmt": _format_dashboard_average(0),
        }

    pendentes_por_turma = {
        row["turma_id"]: int(row["pendentes"] or 0)
        for row in conn.execute(
            """
            SELECT a.turma_id, COUNT(*) AS pendentes
              FROM requisicoes r
              JOIN alunos a ON a.id = r.aluno_id
             WHERE a.turma_id IS NOT NULL
               AND r.status = 'Pendente'
          GROUP BY a.turma_id
            """
        ).fetchall()
    }

    horas_por_turma = {}
    for row in conn.execute(
        """
        SELECT a.turma_id,
               act.tipo_atividade,
               SUM(COALESCE(r.horas_deferidas, r.horas_solicitadas, 0)) AS total_horas
          FROM requisicoes r
          JOIN alunos a ON a.id = r.aluno_id
          JOIN atividades act ON act.id = r.atividade_id
         WHERE a.turma_id IS NOT NULL
           AND r.status IN ('Deferida', 'Deferida Parcialmente')
      GROUP BY a.turma_id, act.tipo_atividade
        """
    ).fetchall():
        turma_metrics = horas_por_turma.setdefault(
            row["turma_id"],
            {"aac_hours": 0.0, "aeu_hours": 0.0},
        )
        if row["tipo_atividade"] == "Acadêmica Complementar":
            turma_metrics["aac_hours"] = float(row["total_horas"] or 0)
        elif row["tipo_atividade"] == "Extensão Universitária":
            turma_metrics["aeu_hours"] = float(row["total_horas"] or 0)

    active_student_ids_by_turma = {}
    for row in conn.execute(
        """
        SELECT id, turma_id
          FROM alunos
         WHERE turma_id IS NOT NULL
           AND status = 'Ativo'
        """
    ).fetchall():
        active_student_ids_by_turma.setdefault(row["turma_id"], []).append(row["id"])

    horas_por_aluno = {}
    for row in conn.execute(
        """
        SELECT r.aluno_id,
               act.tipo_atividade,
               SUM(COALESCE(r.horas_deferidas, r.horas_solicitadas, 0)) AS total_horas
          FROM requisicoes r
          JOIN atividades act ON act.id = r.atividade_id
          JOIN alunos a ON a.id = r.aluno_id
         WHERE a.turma_id IS NOT NULL
           AND a.status = 'Ativo'
           AND r.status IN ('Deferida', 'Deferida Parcialmente')
      GROUP BY r.aluno_id, act.tipo_atividade
        """
    ).fetchall():
        aluno_metrics = horas_por_aluno.setdefault(
            row["aluno_id"],
            {"aac_hours": 0.0, "aeu_hours": 0.0},
        )
        if row["tipo_atividade"] == "Acadêmica Complementar":
            aluno_metrics["aac_hours"] = float(row["total_horas"] or 0)
        elif row["tipo_atividade"] == "Extensão Universitária":
            aluno_metrics["aeu_hours"] = float(row["total_horas"] or 0)

    turma_cards = []
    total_alunos = 0
    total_pendentes = 0
    total_ch = 0.0
    total_aac_denominador = 0.0
    total_aeu_denominador = 0.0
    total_aac_hours = 0.0
    total_aeu_hours = 0.0
    total_turmas = len(turma_rows)
    total_turmas_ativas = 0
    turmas_com_aac = 0
    turmas_com_aeu = 0
    total_aac_applicables = 0
    total_aeu_applicables = 0

    for row in turma_rows:
        turma_id = row["id"]
        turma_label = (row["codigo"] or row["nome"] or "").strip() or f"Turma {turma_id}"
        turma_alunos = int(row["total_alunos"] or 0)
        turma_alunos_ativos = int(row["total_alunos_ativos"] or 0)
        turma_horas = horas_por_turma.get(turma_id, {})
        aac_hours = float(turma_horas.get("aac_hours", 0) or 0)
        aeu_hours = float(turma_horas.get("aeu_hours", 0) or 0)
        ch_total = aac_hours + aeu_hours
        pendentes = int(pendentes_por_turma.get(turma_id, 0) or 0)
        periodo_atual_label = "-"
        if row["ano_inicio"] and row["semestre_inicio"]:
            periodo_atual_label = f"{periodo_corrente(row['ano_inicio'], row['semestre_inicio'])}º período"

        matriz = get_effective_matriz_for_turma(conn, row["curso_id"], row["matriz_id"])
        meta_aac = float(
            matriz["horas_aac_obrigatorias"]
            if matriz and matriz["horas_aac_obrigatorias"] is not None
            else DEFAULT_CURSO_TOTAL_HORAS_AAC
        )
        meta_aeu = float(
            matriz["horas_extensao_obrigatorias"]
            if matriz and matriz["horas_extensao_obrigatorias"] is not None
            else DEFAULT_CURSO_TOTAL_HORAS_AEU
        )
        aac_applicable = meta_aac > 0
        aeu_applicable = meta_aeu > 0
        meta_aac_total = meta_aac * turma_alunos
        meta_aeu_total = meta_aeu * turma_alunos
        aac_pct = int((aac_hours * 100) // meta_aac_total) if aac_applicable and meta_aac_total > 0 else 0
        aeu_pct = int((aeu_hours * 100) // meta_aeu_total) if aeu_applicable and meta_aeu_total > 0 else 0
        meta_total_por_aluno = (meta_aac if aac_applicable else 0.0) + (meta_aeu if aeu_applicable else 0.0)
        meta_total_turma = meta_total_por_aluno * turma_alunos
        total_applicable = meta_total_por_aluno > 0
        total_pct = int((ch_total * 100) // meta_total_turma) if total_applicable and meta_total_turma > 0 else 0

        attainment_buckets = [
            {"label": bucket["label"], "color": bucket["color"], "count": 0, "share_pct": 0}
            for bucket in attainment_bucket_specs
        ]
        attainment_pct_total = 0.0
        active_student_ids = active_student_ids_by_turma.get(turma_id, [])
        for aluno_id in active_student_ids:
            aluno_horas = horas_por_aluno.get(aluno_id, {})
            aluno_total_horas = float(aluno_horas.get("aac_hours", 0) or 0) + float(aluno_horas.get("aeu_hours", 0) or 0)
            aluno_pct_total = min(100.0, (aluno_total_horas * 100.0) / meta_total_por_aluno) if meta_total_por_aluno > 0 else 0.0
            attainment_pct_total += aluno_pct_total

            if aluno_pct_total >= 100:
                bucket_index = 0
            elif aluno_pct_total >= 75:
                bucket_index = 1
            elif aluno_pct_total >= 50:
                bucket_index = 2
            elif aluno_pct_total >= 25:
                bucket_index = 3
            else:
                bucket_index = 4
            attainment_buckets[bucket_index]["count"] += 1

        attainment_avg_pct = int(round(attainment_pct_total / turma_alunos_ativos)) if turma_alunos_ativos else 0
        donut_gradient_parts = []
        if turma_alunos_ativos:
            start_pct = 0.0
            for bucket in attainment_buckets:
                bucket["share_pct"] = int(round((bucket["count"] * 100.0) / turma_alunos_ativos))
                if bucket["count"] <= 0:
                    continue
                sweep_pct = (bucket["count"] * 100.0) / turma_alunos_ativos
                end_pct = start_pct + sweep_pct
                donut_gradient_parts.append(f"{bucket['color']} {start_pct:.2f}% {end_pct:.2f}%")
                start_pct = end_pct
            if start_pct < 100.0:
                donut_gradient_parts.append(f"#e8edf3 {start_pct:.2f}% 100%")
        else:
            donut_gradient_parts.append("#e8edf3 0% 100%")
        attainment_donut_gradient = f"conic-gradient({', '.join(donut_gradient_parts)})"

        turma_cards.append(
            {
                "id": turma_id,
                "label": turma_label,
                "total_alunos": turma_alunos,
                "total_alunos_ativos": turma_alunos_ativos,
                "periodo_atual_label": periodo_atual_label,
                "aac_hours_fmt": _format_dashboard_hours(aac_hours),
                "aeu_hours_fmt": _format_dashboard_hours(aeu_hours),
                "ch_total_fmt": _format_dashboard_hours(ch_total),
                "aac_applicable": aac_applicable,
                "aeu_applicable": aeu_applicable,
                "aac_pct": min(100, aac_pct),
                "aeu_pct": min(100, aeu_pct),
                "total_applicable": total_applicable,
                "total_pct": min(100, total_pct),
                "attainment_buckets": attainment_buckets,
                "attainment_avg_pct_label": f"{attainment_avg_pct}%",
                "attainment_donut_gradient": attainment_donut_gradient,
                "pendentes": pendentes,
            }
        )

        total_alunos += turma_alunos
        total_pendentes += pendentes
        total_ch += ch_total
        if aac_applicable:
            total_aac_hours += aac_hours
            total_aac_denominador += meta_aac_total
            total_aac_applicables += 1
        if aeu_applicable:
            total_aeu_hours += aeu_hours
            total_aeu_denominador += meta_aeu_total
            total_aeu_applicables += 1

        if (row["status"] or "") == "Ativa":
            total_turmas_ativas += 1
            if aac_applicable:
                turmas_com_aac += 1
            if aeu_applicable:
                turmas_com_aeu += 1

    total_geral = None
    if len(turma_cards) % 2 == 1:
        total_geral = {
            "label": "Total Geral",
            "total_alunos": total_alunos,
            "aac_applicable": total_aac_applicables > 0,
            "aeu_applicable": total_aeu_applicables > 0,
            "aac_pct": min(100, int((total_aac_hours * 100) // total_aac_denominador)) if total_aac_denominador > 0 else 0,
            "aeu_pct": min(100, int((total_aeu_hours * 100) // total_aeu_denominador)) if total_aeu_denominador > 0 else 0,
            "ch_total_fmt": _format_dashboard_hours(total_ch),
            "pendentes": total_pendentes,
        }

    return turma_cards, total_geral, {
        "total_turmas": total_turmas,
        "total_turmas_ativas": total_turmas_ativas,
        "turmas_com_aac": turmas_com_aac,
        "turmas_com_aeu": turmas_com_aeu,
        "media_alunos_por_turma_fmt": _format_dashboard_average(total_alunos / total_turmas if total_turmas else 0),
    }

# ===================== Rotas Admin: Dashboard =====================

@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    conn = get_db_connection()
    ensure_requisicao_alert_receipts_table(conn)
    response_time_settings = get_response_time_settings(conn)
    auto_indefer_devolvidas(conn)
    usuario_id = session.get("user_id")
    access_level = session.get("access_level")
    if usuario_id:
        usuario = conn.execute("SELECT nivel_acesso FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
        if usuario:
            access_level = usuario["nivel_acesso"]
    alertas_ativos = list(list_active_admin_alertas(conn))
    new_request_alert = get_admin_new_request_alert(conn, usuario_id, access_level)
    if new_request_alert:
        alertas_ativos.insert(0, new_request_alert["alerta"])
        mark_admin_new_request_alert_seen(conn, new_request_alert["requisicao_ids"], usuario_id, access_level)
        conn.commit()
    now = time.time()
    metrics = getattr(g, '_adm_dash_metrics', None)
    ts = getattr(g, '_adm_dash_ts', 0)
    if not metrics or now - ts >= 30:
        metrics = {}
        metrics['total_alunos'] = conn.execute("SELECT COUNT(*) FROM alunos").fetchone()[0]
        metrics['total_atividades_academicas'] = conn.execute("SELECT COUNT(*) FROM atividades WHERE tipo_atividade = 'Acadêmica Complementar'").fetchone()[0]
        metrics['total_atividades_extensao'] = conn.execute("SELECT COUNT(*) FROM atividades WHERE tipo_atividade = 'Extensão Universitária'").fetchone()[0]
        metrics['total_atividades'] = metrics['total_atividades_academicas'] + metrics['total_atividades_extensao']
        metrics['total_requisicoes'] = conn.execute("SELECT COUNT(*) FROM requisicoes").fetchone()[0]
        metrics['requisicoes_pendentes'] = conn.execute("SELECT COUNT(*) FROM requisicoes WHERE status = 'Pendente'").fetchone()[0]
        avg_pending_response_days, overdue_pending_count = _calculate_pending_response_metrics(
            conn,
            goal_days=response_time_settings["response_goal_days"],
            reset_at=str(response_time_settings["response_metrics_reset_at"] or ""),
        )
        metrics['tempo_medio_resposta_dias'] = avg_pending_response_days
        metrics['tempo_medio_resposta_dias_fmt'] = _format_dashboard_days(avg_pending_response_days)
        metrics['tempo_medio_resposta_meta_dias'] = response_time_settings["response_goal_days"]
        metrics['tempo_medio_resposta_apuracao_inicio'] = response_time_settings["response_metrics_reset_at"]
        metrics['tempo_medio_resposta_apuracao_inicio_fmt'] = response_time_settings["response_metrics_reset_at_fmt"]
        metrics['tempo_medio_resposta_meta_excedida'] = avg_pending_response_days > response_time_settings["response_goal_days"]
        metrics['requisicoes_devolvidas_abertas'] = conn.execute("SELECT COUNT(*) FROM requisicoes WHERE status = 'Devolvida'").fetchone()[0]
        metrics['requisicoes_atrasadas_meta_dias'] = overdue_pending_count
        metrics['requisicoes_academicas'] = conn.execute("SELECT COUNT(*) FROM requisicoes r JOIN atividades a ON r.atividade_id = a.id WHERE a.tipo_atividade = 'Acadêmica Complementar'").fetchone()[0]
        metrics['requisicoes_extensao'] = conn.execute("SELECT COUNT(*) FROM requisicoes r JOIN atividades a ON r.atividade_id = a.id WHERE a.tipo_atividade = 'Extensão Universitária'").fetchone()[0]
        metrics['turma_cards'], metrics['dashboard_total_geral'], turma_summary = _build_admin_dashboard_turma_cards(conn)
        metrics.update(turma_summary)
        g._adm_dash_metrics = metrics
        g._adm_dash_ts = now

    return render_template("admin_dashboard.html", 
                           total_alunos=metrics['total_alunos'], 
                           total_atividades=metrics['total_atividades'],
                           total_atividades_academicas=metrics['total_atividades_academicas'],
                           total_atividades_extensao=metrics['total_atividades_extensao'],
                           total_requisicoes=metrics['total_requisicoes'],
                           requisicoes_pendentes=metrics['requisicoes_pendentes'],
                           tempo_medio_resposta_dias=metrics['tempo_medio_resposta_dias'],
                           tempo_medio_resposta_dias_fmt=metrics['tempo_medio_resposta_dias_fmt'],
                           tempo_medio_resposta_meta_dias=metrics['tempo_medio_resposta_meta_dias'],
                           tempo_medio_resposta_apuracao_inicio=metrics['tempo_medio_resposta_apuracao_inicio'],
                           tempo_medio_resposta_apuracao_inicio_fmt=metrics['tempo_medio_resposta_apuracao_inicio_fmt'],
                           tempo_medio_resposta_meta_excedida=metrics['tempo_medio_resposta_meta_excedida'],
                           requisicoes_devolvidas_abertas=metrics['requisicoes_devolvidas_abertas'],
                           requisicoes_atrasadas_meta_dias=metrics['requisicoes_atrasadas_meta_dias'],
                           requisicoes_academicas=metrics['requisicoes_academicas'],
                           requisicoes_extensao=metrics['requisicoes_extensao'],
                           total_turmas=metrics['total_turmas'],
                           total_turmas_ativas=metrics['total_turmas_ativas'],
                           turmas_com_aac=metrics['turmas_com_aac'],
                           turmas_com_aeu=metrics['turmas_com_aeu'],
                           media_alunos_por_turma_fmt=metrics['media_alunos_por_turma_fmt'],
                           turma_cards=metrics['turma_cards'],
                           dashboard_total_geral=metrics['dashboard_total_geral'],
                           alertas_ativos=alertas_ativos)


@app.route("/admin/banco-dados")
@admin_required
def admin_banco_dados():
    conn = get_db_connection()
    context = _build_database_admin_context(conn)
    return render_template("admin_banco_dados.html", **context)


def _maybe_redirect_to_oauth_callback_host(redirect_uri: str) -> str:
    parsed_redirect = urlsplit((redirect_uri or "").strip())
    if parsed_redirect.scheme not in {"http", "https"} or not parsed_redirect.netloc:
        return ""

    current_host = (request.host or "").strip().lower()
    target_host = parsed_redirect.netloc.strip().lower()
    if not current_host or current_host == target_host:
        return ""

    parsed_current = urlsplit(request.url)
    return parsed_current._replace(
        scheme=parsed_redirect.scheme,
        netloc=parsed_redirect.netloc,
    ).geturl()


def _clear_legacy_oauth_session() -> None:
    removed = False
    for key in ("oauth_provider", "oauth_state", "oauth_verifier"):
        if key in session:
            session.pop(key, None)
            removed = True
    if removed:
        session.modified = True


def _resolve_onedrive_redirect_uri() -> str:
    return onedrive_get_ms_redirect_uri()


def _resolve_google_redirect_uri() -> str:
    return google_get_redirect_uri()


def _onedrive_connect_diagnostics(redirect_uri: str = "") -> dict[str, str]:
    try:
        import msal  # noqa: F401
        msal_imported = "sim"
    except Exception:
        msal_imported = "não"

    return {
        "APP_ENV": str(app.config.get("APP_ENV") or os.getenv("APP_ENV") or ""),
        "APP_PUBLIC_BASE_URL": (os.getenv("APP_PUBLIC_BASE_URL") or "").strip(),
        "MS_TENANT_ID_presente": "sim" if (os.getenv("MS_TENANT_ID") or "").strip() else "não",
        "MS_CLIENT_ID_presente": "sim" if (os.getenv("MS_CLIENT_ID") or "").strip() else "não",
        "MS_CLIENT_SECRET_presente": "sim" if (os.getenv("MS_CLIENT_SECRET") or "").strip() else "não",
        "MS_GRAPH_BASE_URL_presente": "sim" if (os.getenv("MS_GRAPH_BASE_URL") or "").strip() else "não",
        "redirect_uri_calculado": redirect_uri,
        "msal_importado": msal_imported,
    }


def _build_oauth_redirect_context() -> dict[str, str]:
    context = {
        "oauth_public_base_url": "",
        "google_oauth_callback_uri": "",
        "onedrive_oauth_callback_uri": "",
        "oauth_config_error": "",
    }
    try:
        context["oauth_public_base_url"] = oauth_get_public_base_url()
        context["google_oauth_callback_uri"] = oauth_get_google_redirect_uri()
        context["onedrive_oauth_callback_uri"] = oauth_get_onedrive_redirect_uri()
    except OAuthConfigError as exc:
        context["oauth_config_error"] = str(exc)
    except Exception as exc:
        context["oauth_config_error"] = f"Falha ao resolver callbacks OAuth: {exc}"
    return context


@app.route("/admin/backup/google/connect")
@admin_required
def admin_backup_google_connect():
    try:
        redirect_uri = _resolve_google_redirect_uri()
    except GoogleDriveServiceError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin_banco_dados"))

    host_redirect = _maybe_redirect_to_oauth_callback_host(redirect_uri)
    if host_redirect:
        return redirect(host_redirect)

    try:
        _require_cloud_token_encryption_ready()
    except TokenEncryptionConfigError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin_banco_dados"))

    _clear_legacy_oauth_session()
    state = secrets.token_urlsafe(24)
    session["google_oauth_state"] = state
    session.modified = True

    try:
        auth_url, generated_state = google_create_authorization_url(
            state=state,
            is_debug=not app.config.get("IS_PRODUCTION", False),
        )
        session["google_oauth_state"] = generated_state or state
        session.modified = True
    except GoogleDriveServiceError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin_banco_dados"))
    except Exception as exc:
        logger.warning("Falha ao iniciar OAuth Google Drive: %s", exc)
        flash(f"Falha ao iniciar conexão com Google Drive: {exc}", "error")
        return redirect(url_for("admin_banco_dados"))

    return redirect(auth_url)


@app.route("/google/callback")
@admin_required
def google_callback():
    _clear_legacy_oauth_session()
    error = request.args.get("error")
    if error:
        error_description = (request.args.get("error_description") or "").strip()
        if error == "access_denied" and (
            "test" in error_description.lower()
            or "tester" in error_description.lower()
            or "verification" in error_description.lower()
        ):
            flash(
                "Google OAuth bloqueado: o aplicativo está em modo de teste. "
                "Adicione este e-mail como usuário de teste no Google Cloud Console (OAuth consent screen).",
                "error",
            )
            return redirect(url_for("admin_banco_dados"))
        flash(f"Autorização negada: {error}", "error")
        return redirect(url_for("admin_banco_dados"))

    state = request.args.get("state") or ""
    code = request.args.get("code") or ""
    expected_state = session.pop("google_oauth_state", "")
    session.modified = True

    if not state or not expected_state or not secrets.compare_digest(state, expected_state):
        flash("Estado OAuth inválido. Reinicie a conexão Google.", "error")
        return redirect(url_for("admin_banco_dados"))
    if not code:
        flash("Resposta OAuth incompleta (code ausente).", "error")
        return redirect(url_for("admin_banco_dados"))

    try:
        _resolve_google_redirect_uri()
    except GoogleDriveServiceError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin_banco_dados"))

    conn = get_db_connection()
    try:
        token_json, account_email = google_exchange_code_for_token(
            code=code,
            is_debug=not app.config.get("IS_PRODUCTION", False),
        )
        _set_active_cloud_account(conn, "google", account_email, token_json)
        _save_drive_config(
            conn,
            {
                "gdrive_account_email": account_email,
                "gdrive_last_upload_error": "",
            },
        )
        conn.commit()
        if account_email:
            flash(f"Google Drive conectado como {account_email}.", "success")
        else:
            flash("Google Drive conectado com sucesso.", "success")
    except (GoogleDriveServiceError, TokenEncryptionConfigError) as exc:
        conn.rollback()
        logger.warning("Falha no callback OAuth Google Drive: %s", exc)
        flash(f"Falha ao conectar Google Drive: {exc}", "error")
    except Exception as exc:
        conn.rollback()
        logger.warning("Erro inesperado no callback OAuth Google Drive: %s", exc)
        flash(f"Falha ao conectar Google Drive: {exc}", "error")

    return redirect(url_for("admin_banco_dados"))


@app.route("/admin/backup/google/upload", methods=["POST"])
@admin_required
def admin_backup_google_upload():
    conn = get_db_connection()
    google_account = _get_active_cloud_account(conn, "google")
    if not google_account:
        drive_settings = get_drive_settings(conn)
        if (drive_settings.get("gdrive_access_token") or "").strip():
            flash("Conexão antiga detectada. Reconecte o Google Drive.", "error")
        else:
            flash("Nenhuma conta Google conectada. Conecte o Google Drive antes de enviar.", "error")
        return redirect(url_for("admin_banco_dados"))

    if not bool(google_account.get("token_json_available", True)):
        flash(
            str(
                google_account.get("token_json_error")
                or "Token OAuth do Google Drive indisponivel. Reconecte a conta."
            ),
            "error",
        )
        return redirect(url_for("admin_banco_dados"))

    try:
        _require_cloud_token_encryption_ready()
    except TokenEncryptionConfigError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin_banco_dados"))

    backup_artifacts = None
    file_name = ""
    file_size = None
    try:
        backup_artifacts = create_sqlite_backup_zip(DATABASE)
        file_name = str(backup_artifacts.get("file_name") or "")
        file_size = int(backup_artifacts.get("file_size") or 0)
        google_folder_setting = _get_cloud_drive_folder_setting(conn, "google")
        selected_google_folder_id = str(google_folder_setting.get("folder_id") or "").strip()

        upload_result = google_upload_zip_backup(
            token_json=str(google_account["token_json"] or ""),
            zip_path=str(backup_artifacts["zip_path"]),
            file_name=file_name,
            folder_name="SGAA - Backups",
            folder_id=selected_google_folder_id or None,
        )
        updated_token_json = str(upload_result.get("token_json") or "")
        if updated_token_json:
            _update_cloud_account_token(
                conn,
                account_id=int(google_account["id"]),
                token_json=updated_token_json,
            )

        now_iso = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        _save_drive_config(
            conn,
            {
                "gdrive_last_upload_at": now_iso,
                "gdrive_last_upload_error": "",
                "gdrive_account_email": str(google_account["account_email"] or ""),
            },
        )
        _record_backup_log(
            conn,
            provider="google",
            file_name=file_name,
            file_size=file_size,
            status="sucesso",
        )
        conn.commit()
        flash("Backup enviado para o Google Drive com sucesso.", "success")
    except (BackupServiceError, GoogleDriveServiceError, TokenEncryptionConfigError) as exc:
        conn.rollback()
        error_message = str(exc)
        safe_lower_error = error_message.lower()
        folder_access_error = any(
            marker in safe_lower_error
            for marker in (
                "forbidden",
                "permission",
                "insufficient",
                "not found",
                "403",
                "404",
                "cannot find",
            )
        )
        try:
            _record_backup_log(
                conn,
                provider="google",
                file_name=file_name,
                file_size=file_size,
                status="erro",
                error_message=error_message,
            )
            _save_drive_config(conn, {"gdrive_last_upload_error": error_message[:200]})
            conn.commit()
        except Exception:
            conn.rollback()
        logger.warning("Falha no backup manual Google Drive: %s", exc)
        if folder_access_error:
            flash(
                "Não foi possível enviar o backup para a pasta selecionada. "
                "Verifique se ela pertence à conta Google conectada.",
                "error",
            )
        else:
            flash(f"Falha ao enviar backup para o Google Drive: {exc}", "error")
    except Exception as exc:
        conn.rollback()
        error_message = str(exc)
        try:
            _record_backup_log(
                conn,
                provider="google",
                file_name=file_name,
                file_size=file_size,
                status="erro",
                error_message=error_message,
            )
            _save_drive_config(conn, {"gdrive_last_upload_error": error_message[:200]})
            conn.commit()
        except Exception:
            conn.rollback()
        logger.warning("Erro inesperado no backup manual Google Drive: %s", exc)
        flash(f"Falha ao enviar backup para o Google Drive: {exc}", "error")
    finally:
        cleanup_backup_artifacts(backup_artifacts)

    return redirect(url_for("admin_banco_dados"))


@app.route("/admin/backup/onedrive/connect")
@admin_required
def admin_backup_onedrive_connect():
    diagnostics = _onedrive_connect_diagnostics("")
    try:
        onedrive_redirect_uri = _resolve_onedrive_redirect_uri()
    except OneDriveServiceError as exc:
        current_app.logger.exception("Falha ao iniciar conexão OneDrive")
        current_app.logger.info(
            (
                "OneDrive connect diagnostics: APP_ENV=%s APP_PUBLIC_BASE_URL=%s "
                "MS_TENANT_ID presente=%s MS_CLIENT_ID presente=%s "
                "MS_CLIENT_SECRET presente=%s MS_GRAPH_BASE_URL presente=%s "
                "redirect_uri=%s msal importado=%s"
            ),
            diagnostics["APP_ENV"],
            diagnostics["APP_PUBLIC_BASE_URL"],
            diagnostics["MS_TENANT_ID_presente"],
            diagnostics["MS_CLIENT_ID_presente"],
            diagnostics["MS_CLIENT_SECRET_presente"],
            diagnostics["MS_GRAPH_BASE_URL_presente"],
            diagnostics["redirect_uri_calculado"],
            diagnostics["msal_importado"],
        )
        flash(str(exc), "error")
        return redirect(url_for("admin_banco_dados"))

    diagnostics = _onedrive_connect_diagnostics(onedrive_redirect_uri)
    current_app.logger.info(
        (
            "OneDrive connect diagnostics: APP_ENV=%s APP_PUBLIC_BASE_URL=%s "
            "MS_TENANT_ID presente=%s MS_CLIENT_ID presente=%s "
            "MS_CLIENT_SECRET presente=%s MS_GRAPH_BASE_URL presente=%s "
            "redirect_uri=%s msal importado=%s"
        ),
        diagnostics["APP_ENV"],
        diagnostics["APP_PUBLIC_BASE_URL"],
        diagnostics["MS_TENANT_ID_presente"],
        diagnostics["MS_CLIENT_ID_presente"],
        diagnostics["MS_CLIENT_SECRET_presente"],
        diagnostics["MS_GRAPH_BASE_URL_presente"],
        diagnostics["redirect_uri_calculado"],
        diagnostics["msal_importado"],
    )
    current_app.logger.info(
        "OneDrive redirect URI OAuth resolvido: %s",
        onedrive_redirect_uri,
    )
    logger.info(
        "OneDrive redirect URI OAuth resolvido: %s",
        onedrive_redirect_uri,
    )
    host_redirect = _maybe_redirect_to_oauth_callback_host(onedrive_redirect_uri)
    if host_redirect:
        return redirect(host_redirect)

    try:
        _require_cloud_token_encryption_ready()
    except TokenEncryptionConfigError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin_banco_dados"))

    _clear_legacy_oauth_session()
    state = secrets.token_urlsafe(24)
    session["onedrive_oauth_state"] = state
    session.pop("onedrive_oauth_verifier", None)
    session.pop("onedrive_oauth_flow_mode", None)
    session.modified = True

    try:
        auth_url = onedrive_create_authorization_url(state=state)
        session["onedrive_oauth_flow_mode"] = "msal"
        session.modified = True
    except OneDriveServiceError as exc:
        current_app.logger.exception("Falha ao iniciar conexão OneDrive")
        flash(str(exc), "error")
        return redirect(url_for("admin_banco_dados"))
    except Exception as exc:
        current_app.logger.exception("Falha ao iniciar conexão OneDrive")
        if isinstance(exc, ModuleNotFoundError) and "msal" in str(exc).lower():
            flash("Biblioteca MSAL não instalada. Execute pip install -r requirements.txt.", "error")
        else:
            flash("Falha ao iniciar conexão com OneDrive.", "error")
        return redirect(url_for("admin_banco_dados"))

    return redirect(auth_url)


@app.route("/onedrive/callback")
@admin_required
def onedrive_callback():
    _clear_legacy_oauth_session()
    has_code = bool((request.args.get("code") or "").strip())
    has_state = bool((request.args.get("state") or "").strip())
    current_app.logger.info(
        "OneDrive callback recebido: has_code=%s has_state=%s",
        has_code,
        has_state,
    )

    error = (request.args.get("error") or "").strip()
    if error:
        current_app.logger.warning(
            "OneDrive callback retornou erro do provedor: %s",
            error.lower(),
        )
        if error.lower() == "access_denied":
            flash("Autorização do OneDrive cancelada pelo usuário.", "error")
        else:
            flash("Falha na autorização Microsoft para OneDrive.", "error")
        return redirect(url_for("admin_banco_dados"))

    state = request.args.get("state") or ""
    code = request.args.get("code") or ""
    expected_state = session.pop("onedrive_oauth_state", "")
    verifier = session.pop("onedrive_oauth_verifier", "")
    flow_mode = session.pop("onedrive_oauth_flow_mode", "msal")
    session.modified = True

    state_match = bool(state and expected_state and secrets.compare_digest(state, expected_state))
    current_app.logger.info("OneDrive state validado: state_match=%s", state_match)
    if not state_match:
        flash("Sessão OAuth expirada ou inválida. Tente conectar novamente.", "error")
        return redirect(url_for("admin_banco_dados"))

    if not code:
        flash("Resposta OAuth incompleta (código ausente).", "error")
        return redirect(url_for("admin_banco_dados"))

    try:
        redirect_uri = _resolve_onedrive_redirect_uri()
    except OneDriveServiceError as exc:
        current_app.logger.warning("OneDrive callback com configuracao invalida: %s", exc)
        flash(str(exc), "error")
        return redirect(url_for("admin_banco_dados"))

    current_app.logger.info(
        "OneDrive callback usando redirect URI resolvido: %s",
        redirect_uri,
    )
    try:
        onedrive_validate_configuration()
    except OneDriveServiceError as exc:
        current_app.logger.warning("OneDrive callback com configuracao Microsoft invalida: %s", exc)
        flash(str(exc), "error")
        return redirect(url_for("admin_banco_dados"))

    conn = get_db_connection()
    try:
        if flow_mode == "legacy_pkce":
            client_id = (
                (os.environ.get("ONEDRIVE_CLIENT_ID") or "").strip()
                or (os.environ.get("MS_CLIENT_ID") or "").strip()
            )
            if not verifier:
                raise OneDriveServiceError("Sessao OAuth expirada. Inicie a conexao OneDrive novamente.")
            if not client_id:
                raise OneDriveServiceError("ONEDRIVE_CLIENT_ID/MS_CLIENT_ID ausente para OAuth OneDrive.")

            current_app.logger.info("OneDrive token exchange iniciado: flow_mode=legacy_pkce")
            tokens = _cd.onedrive_exchange(client_id, code, redirect_uri, verifier)
            access_token = str(tokens.get("access_token") or "").strip()
            current_app.logger.info("OneDrive token obtido com sucesso: %s", bool(access_token))
            if not access_token:
                error_code = str(tokens.get("error") or "").strip().lower() or "unknown_error"
                current_app.logger.warning("OneDrive OAuth falhou: %s", error_code)
                raise OneDriveServiceError("Falha na autenticacao com Microsoft/OneDrive.")

            current_app.logger.info("OneDrive consulta /me iniciada")
            info = _cd.onedrive_userinfo(access_token)
            account_email = str(info.get("mail") or info.get("userPrincipalName") or "").strip()
            current_app.logger.info("OneDrive e-mail obtido: %s", bool(account_email))

            expires_in = int(tokens.get("expires_in") or 3600)
            refresh_token = str(tokens.get("refresh_token") or "").strip()
            expires_at = _cd.token_expires_at(expires_in)

            legacy_payload = {
                "version": 1,
                "provider": "onedrive",
                "mode": "legacy_pkce",
                "account_email": account_email,
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_at": expires_at,
                "updated_at": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            }
            token_json = json.dumps(legacy_payload, ensure_ascii=False)
            _save_drive_config(
                conn,
                {
                    "onedrive_access_token": access_token,
                    "onedrive_refresh_token": refresh_token,
                    "onedrive_expires_at": expires_at,
                    "onedrive_account_email": account_email,
                    "onedrive_last_upload_error": "",
                },
            )
        else:
            current_app.logger.info("OneDrive token exchange iniciado: flow_mode=msal")
            token_json, account_email = onedrive_exchange_code_for_token(code=code)
            current_app.logger.info("OneDrive token obtido com sucesso: %s", bool(token_json))
            current_app.logger.info("OneDrive consulta /me iniciada")
            account_info = onedrive_get_connected_account(token_json=token_json)
            token_json = str(account_info.get("token_json") or token_json)
            account_email = str(account_info.get("account_email") or account_email)
            current_app.logger.info("OneDrive e-mail obtido: %s", bool(account_email))

        current_app.logger.info("OneDrive salvamento cloud_accounts iniciado")
        _set_active_cloud_account(conn, "onedrive", account_email, token_json)
        _save_drive_config(
            conn,
            {
                "onedrive_account_email": account_email,
                "onedrive_last_upload_error": "",
            },
        )
        conn.commit()
        current_app.logger.info("OneDrive conexao salva com sucesso")
        if account_email:
            flash(f"OneDrive conectado como {account_email}.", "success")
        else:
            flash("OneDrive conectado com sucesso.", "success")
    except (OneDriveServiceError, TokenEncryptionConfigError) as exc:
        conn.rollback()
        current_app.logger.warning("Falha no callback OAuth OneDrive: %s", exc)
        flash(str(exc), "error")
    except Exception:
        conn.rollback()
        current_app.logger.exception("Erro no callback OneDrive")
        flash("Erro ao conectar o OneDrive. Veja os logs do servidor.", "error")
        return redirect(url_for("admin_banco_dados"))

    return redirect(url_for("admin_banco_dados"))


@app.route("/admin/backup/onedrive/upload", methods=["POST"])
@admin_required
def admin_backup_onedrive_upload():
    conn = get_db_connection()
    onedrive_account = _get_active_cloud_account(conn, "onedrive")
    if not onedrive_account:
        flash("Nenhuma conta OneDrive conectada. Conecte o OneDrive antes de enviar.", "error")
        return redirect(url_for("admin_banco_dados"))

    if not bool(onedrive_account.get("token_json_available", True)):
        flash(
            str(
                onedrive_account.get("token_json_error")
                or "Token OAuth do OneDrive indisponivel. Reconecte a conta."
            ),
            "error",
        )
        return redirect(url_for("admin_banco_dados"))

    try:
        _require_cloud_token_encryption_ready()
    except TokenEncryptionConfigError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin_banco_dados"))

    backup_artifacts = None
    file_name = ""
    file_size = None
    try:
        backup_artifacts = create_sqlite_backup_zip(DATABASE)
        file_name = str(backup_artifacts.get("file_name") or "")
        file_size = int(backup_artifacts.get("file_size") or 0)
        onedrive_folder_setting = _get_cloud_drive_folder_setting(conn, "onedrive")
        selected_onedrive_folder_id = str(onedrive_folder_setting.get("folder_id") or "").strip()
        selected_onedrive_drive_id = str(onedrive_folder_setting.get("drive_id") or "").strip()

        token_json_raw = str(onedrive_account["token_json"] or "")
        token_payload: dict[str, object] = {}
        try:
            loaded = json.loads(token_json_raw or "{}")
            if isinstance(loaded, dict):
                token_payload = loaded
        except json.JSONDecodeError:
            token_payload = {}

        legacy_mode = bool(
            token_payload.get("mode") == "legacy_pkce"
            or (
                token_payload.get("provider") == "onedrive"
                and token_payload.get("access_token")
                and not token_payload.get("msal_cache")
            )
        )

        if legacy_mode:
            client_id = (
                (os.environ.get("ONEDRIVE_CLIENT_ID") or "").strip()
                or (os.environ.get("MS_CLIENT_ID") or "").strip()
            )
            if not client_id:
                raise OneDriveServiceError("ONEDRIVE_CLIENT_ID/MS_CLIENT_ID ausente para refresh do OneDrive.")

            access_token = str(token_payload.get("access_token") or "").strip()
            refresh_token = str(token_payload.get("refresh_token") or "").strip()
            expires_at = str(token_payload.get("expires_at") or "").strip()

            if not access_token:
                raise OneDriveServiceError("Token OAuth do OneDrive inválido. Reconecte a conta.")

            if _cd.is_token_expired(expires_at):
                if not refresh_token:
                    raise OneDriveServiceError("Token expirado e sem refresh válido. Reconecte o OneDrive.")
                refreshed_tokens = _cd.onedrive_refresh(client_id, refresh_token)
                access_token = str(refreshed_tokens.get("access_token") or "").strip()
                if not access_token:
                    raise OneDriveServiceError("Falha ao renovar token OAuth do OneDrive.")
                refresh_token = str(refreshed_tokens.get("refresh_token") or refresh_token).strip()
                expires_at = _cd.token_expires_at(int(refreshed_tokens.get("expires_in") or 3600))

            onedrive_upload_with_access_token(
                access_token=access_token,
                zip_path=str(backup_artifacts["zip_path"]),
                file_name=file_name,
                folder_name="SGAA - Backups",
                folder_id=selected_onedrive_folder_id or None,
                drive_id=selected_onedrive_drive_id or None,
            )
            profile = _cd.onedrive_userinfo(access_token)
            connected_email = str(
                profile.get("mail")
                or profile.get("userPrincipalName")
                or token_payload.get("account_email")
                or onedrive_account["account_email"]
                or ""
            ).strip()

            token_payload.update(
                {
                    "version": int(token_payload.get("version") or 1),
                    "provider": "onedrive",
                    "mode": "legacy_pkce",
                    "account_email": connected_email,
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "expires_at": expires_at,
                    "updated_at": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                }
            )
            refreshed_token_json = json.dumps(token_payload, ensure_ascii=False)
        else:
            upload_result = onedrive_upload_zip_backup(
                token_json=token_json_raw,
                zip_path=str(backup_artifacts["zip_path"]),
                file_name=file_name,
                folder_name="SGAA - Backups",
                folder_id=selected_onedrive_folder_id or None,
                drive_id=selected_onedrive_drive_id or None,
            )
            refreshed_token_json = str(upload_result.get("token_json") or "")
            connected_email = str(upload_result.get("account_email") or onedrive_account["account_email"] or "")

        if refreshed_token_json:
            _update_cloud_account_token(
                conn,
                account_id=int(onedrive_account["id"]),
                token_json=refreshed_token_json,
                account_email=connected_email or None,
            )

        now_iso = (
            datetime.datetime.now(datetime.timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
        drive_updates = {
            "onedrive_last_upload_at": now_iso,
            "onedrive_last_upload_error": "",
            "onedrive_account_email": connected_email,
        }
        if legacy_mode:
            drive_updates.update(
                {
                    "onedrive_access_token": str(token_payload.get("access_token") or ""),
                    "onedrive_refresh_token": str(token_payload.get("refresh_token") or ""),
                    "onedrive_expires_at": str(token_payload.get("expires_at") or ""),
                }
            )
        _save_drive_config(conn, drive_updates)
        _record_backup_log(
            conn,
            provider="onedrive",
            file_name=file_name,
            file_size=file_size,
            status="sucesso",
        )
        conn.commit()
        flash("Backup enviado para o OneDrive com sucesso.", "success")
    except BackupServiceError as exc:
        conn.rollback()
        error_message = str(exc)
        try:
            _record_backup_log(
                conn,
                provider="onedrive",
                file_name=file_name,
                file_size=file_size,
                status="erro",
                error_message=error_message,
            )
            _save_drive_config(conn, {"onedrive_last_upload_error": error_message[:200]})
            conn.commit()
        except Exception:
            conn.rollback()
        logger.warning("Falha no backup local para OneDrive: %s", exc)
        flash("Falha no backup local antes do envio para OneDrive.", "error")
    except (OneDriveServiceError, TokenEncryptionConfigError) as exc:
        conn.rollback()
        error_message = str(exc)
        try:
            _record_backup_log(
                conn,
                provider="onedrive",
                file_name=file_name,
                file_size=file_size,
                status="erro",
                error_message=error_message,
            )
            _save_drive_config(conn, {"onedrive_last_upload_error": error_message[:200]})
            conn.commit()
        except Exception:
            conn.rollback()
        logger.warning("Falha no upload manual OneDrive: %s", exc)
        flash(str(exc), "error")
    except Exception as exc:
        conn.rollback()
        error_message = "Falha inesperada no upload para OneDrive."
        try:
            _record_backup_log(
                conn,
                provider="onedrive",
                file_name=file_name,
                file_size=file_size,
                status="erro",
                error_message=error_message,
            )
            _save_drive_config(conn, {"onedrive_last_upload_error": error_message[:200]})
            conn.commit()
        except Exception:
            conn.rollback()
        logger.warning("Erro inesperado no backup manual OneDrive: %s", type(exc).__name__)
        flash(error_message, "error")
    finally:
        cleanup_backup_artifacts(backup_artifacts)

    return redirect(url_for("admin_banco_dados"))


def _get_cloud_folder_account(conn, provider: str):
    account = _get_active_cloud_account(conn, provider)
    if not account:
        if provider == "google":
            return None, "Conecte o Google Drive antes de selecionar a pasta."
        return None, "Conecte o OneDrive antes de selecionar a pasta."
    if not bool(account.get("token_json_available", True)):
        message = str(
            account.get("token_json_error")
            or (
                "Token OAuth do Google Drive indisponivel. Reconecte a conta."
                if provider == "google"
                else "Token OAuth do OneDrive indisponivel. Reconecte a conta."
            )
        )
        return None, message
    return account, ""


@app.route("/admin/backup/cloud-folders/<provider>")
@admin_required
def admin_backup_cloud_folders(provider):
    try:
        safe_provider = _normalize_cloud_folder_provider(provider)
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400

    parent_id = (request.args.get("parent_id") or "").strip() or "root"
    drive_id = (request.args.get("drive_id") or "").strip()
    conn = get_db_connection()
    account, message = _get_cloud_folder_account(conn, safe_provider)
    if not account:
        return jsonify({"ok": False, "message": message}), 400

    scopes = _extract_oauth_scopes(str(account.get("token_json") or ""))
    logger.info(
        "Cloud folder picker request: provider=%s has_account=%s has_token=%s token_available=%s scopes=%s",
        safe_provider,
        True,
        bool(account.get("token_json")),
        bool(account.get("token_json_available", True)),
        scopes,
    )

    try:
        if safe_provider == "google":
            list_result = google_list_folders(
                token_json=str(account["token_json"] or ""),
                parent_id=parent_id,
            )
        else:
            list_result = onedrive_list_folders(
                token_json=str(account["token_json"] or ""),
                parent_id=parent_id,
                drive_id=drive_id or None,
            )

        updated_token_json = str(list_result.get("token_json") or "")
        if updated_token_json and updated_token_json != str(account.get("token_json") or ""):
            _update_cloud_account_token(
                conn,
                account_id=int(account["id"]),
                token_json=updated_token_json,
                account_email=str(list_result.get("account_email") or account.get("account_email") or "") or None,
            )
            conn.commit()

        folders = []
        for item in list_result.get("folders", []) if isinstance(list_result, dict) else []:
            if not isinstance(item, dict):
                continue
            folder_id = str(item.get("id") or "").strip()
            folder_name = str(item.get("name") or "").strip()
            folder_path_label = str(item.get("path_label") or folder_name).strip()
            if not folder_id or not folder_name:
                continue
            folders.append(
                {
                    "id": folder_id,
                    "drive_id": str(item.get("drive_id") or "").strip() or None,
                    "name": folder_name,
                    "path_label": folder_path_label or folder_name,
                }
            )

        logger.info(
            "Listagem de pastas remotas: provider=%s parent=%s total=%s",
            safe_provider,
            parent_id,
            len(folders),
        )
        response_payload = {
            "ok": True,
            "provider": safe_provider,
            "parent_id": str(list_result.get("parent_id") or parent_id),
            "drive_id": str(list_result.get("drive_id") or drive_id) or None,
            "folders": folders,
        }
        google_scope_limited = (
            safe_provider == "google"
            and parent_id == "root"
            and not folders
            and "https://www.googleapis.com/auth/drive.file" in scopes
            and not any(
                scope in scopes
                for scope in (
                    "https://www.googleapis.com/auth/drive.metadata.readonly",
                    "https://www.googleapis.com/auth/drive.readonly",
                    "https://www.googleapis.com/auth/drive",
                )
            )
        )
        if google_scope_limited:
            response_payload["debug_code"] = "GOOGLE_SCOPE_LIMITED"
            response_payload["notice"] = (
                "Com a permissão segura atual, o sistema não pode navegar por todo o Google Drive. "
                "Use a pasta padrão do aplicativo ou implemente o Google Picker para escolher uma pasta manualmente."
            )
            logger.info(
                "Google folder picker limitado por escopo: provider=%s parent=%s scopes=%s",
                safe_provider,
                parent_id,
                scopes,
            )
        return jsonify(response_payload)
    except GoogleDriveServiceError as exc:
        conn.rollback()
        logger.warning(
            "Falha ao listar pastas remotas Google: provider=%s parent=%s erro=%s",
            safe_provider,
            parent_id,
            exc,
        )
        return jsonify({"ok": False, "message": str(exc)}), 400
    except OneDriveServiceError as exc:
        conn.rollback()
        logger.warning(
            "Falha ao listar pastas remotas OneDrive: provider=%s parent=%s debug_code=%s http_status=%s erro=%s",
            safe_provider,
            parent_id,
            getattr(exc, "debug_code", ""),
            getattr(exc, "http_status", None),
            exc,
        )
        if getattr(exc, "debug_code", "") == "GRAPH_PERMISSION_DENIED":
            return jsonify(
                {
                    "ok": False,
                    "message": "Permissão insuficiente para listar as pastas do OneDrive. Reconecte e conceda acesso aos arquivos.",
                    "debug_code": "GRAPH_PERMISSION_DENIED",
                }
            ), 403
        if getattr(exc, "debug_code", "") == "GRAPH_TOKEN_INVALID":
            return jsonify(
                {
                    "ok": False,
                    "message": "A sessão do OneDrive expirou. Reconecte o provedor e tente novamente.",
                    "debug_code": "GRAPH_TOKEN_INVALID",
                }
            ), 401
        return jsonify(
            {
                "ok": False,
                "message": "Não foi possível listar as pastas do OneDrive.",
                "debug_code": "GRAPH_LIST_CHILDREN_FAILED",
            }
        ), 502
    except (TokenEncryptionError, TokenEncryptionConfigError) as exc:
        conn.rollback()
        logger.warning(
            "Falha de token ao listar pastas remotas: provider=%s parent=%s erro=%s",
            safe_provider,
            parent_id,
            exc,
        )
        return jsonify({"ok": False, "message": str(exc)}), 400
    except Exception:
        conn.rollback()
        logger.exception("Erro inesperado ao listar pastas remotas: provider=%s", safe_provider)
        return jsonify({"ok": False, "message": "Falha ao listar pastas remotas."}), 500


@app.route("/admin/backup/cloud-folder/<provider>", methods=["GET", "POST"])
@admin_required
def admin_backup_cloud_folder(provider):
    try:
        safe_provider = _normalize_cloud_folder_provider(provider)
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400

    conn = get_db_connection()
    if request.method == "GET":
        current_setting = _get_cloud_drive_folder_setting(conn, safe_provider)
        return jsonify(
            {
                "ok": True,
                "provider": safe_provider,
                "folder_id": current_setting.get("folder_id") or "",
                "drive_id": current_setting.get("drive_id") or "",
                "folder_name": current_setting.get("folder_name") or "",
                "folder_path_label": current_setting.get("folder_path_label") or "",
                "updated_at": current_setting.get("updated_at") or "",
            }
        )

    account, message = _get_cloud_folder_account(conn, safe_provider)
    if not account:
        return jsonify({"ok": False, "message": message}), 400

    payload = request.get_json(silent=True) or {}
    folder_id = str(payload.get("folder_id") or "").strip()
    drive_id = str(payload.get("drive_id") or "").strip()
    folder_name = str(payload.get("folder_name") or "").strip()
    folder_path_label = str(payload.get("folder_path_label") or "").strip()

    if not folder_id:
        return jsonify({"ok": False, "message": "Informe a pasta de destino."}), 400

    if not folder_name:
        if folder_id.lower() == "root":
            folder_name = "Meu Drive" if safe_provider == "google" else "OneDrive"
        else:
            folder_name = "Pasta selecionada"
    if not folder_path_label:
        folder_path_label = folder_name

    try:
        _save_cloud_drive_folder_setting(
            conn,
            provider=safe_provider,
            folder_id=folder_id,
            folder_name=folder_name,
            folder_path_label=folder_path_label,
            drive_id=drive_id,
        )
        prefix = "gdrive" if safe_provider == "google" else "onedrive"
        _save_drive_config(
            conn,
            {
                f"{prefix}_dest_folder": folder_path_label,
            },
        )
        conn.commit()
        logger.info(
            "Pasta remota salva: provider=%s folder_id=%s",
            safe_provider,
            folder_id[:8] + "***" if len(folder_id) > 8 else "***",
        )
        return jsonify(
            {
                "ok": True,
                "message": "Pasta de destino atualizada.",
                "provider": safe_provider,
                "folder_id": folder_id,
                "drive_id": drive_id or None,
                "folder_name": folder_name,
                "folder_path_label": folder_path_label,
            }
        )
    except Exception:
        conn.rollback()
        logger.exception("Falha ao salvar pasta remota: provider=%s", safe_provider)
        return jsonify({"ok": False, "message": "Falha ao salvar pasta de destino."}), 500


@app.route("/admin/banco-dados/configuracoes", methods=["POST"])
@admin_required
def admin_banco_dados_configuracoes():
    conn = get_db_connection()
    try:
        save_backup_settings(
            conn,
            {
                "local_backup_dir": request.form.get("local_backup_dir") or "",
                "cloud_backup_dir": request.form.get("cloud_backup_dir") or "",
                "cloud_sync_interval_seconds": request.form.get("cloud_sync_interval_seconds") or "600",
                "external_backup_url": request.form.get("external_backup_url") or "",
                "external_backup_token": request.form.get("external_backup_token") or "",
                "external_backup_enabled": request.form.get("external_backup_enabled") or "0",
            },
        )
        conn.commit()
    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "error")
        return redirect(url_for("admin_banco_dados"))
    flash("Destinos de backup atualizados com sucesso.", "success")
    return redirect(url_for("admin_banco_dados"))


@app.route("/admin/banco-dados/retencao", methods=["POST"])
@admin_required
def admin_banco_dados_retencao():
    conn = get_db_connection()
    try:
        save_retention_policy(conn, request.form.to_dict())
        conn.commit()
    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "error")
        return redirect(url_for("admin_banco_dados"))
    flash("Política de retenção atualizada com sucesso.", "success")
    return redirect(url_for("admin_banco_dados"))


@app.route("/admin/banco-dados/oauth/start")
@admin_required
def admin_banco_dados_oauth_start():
    provider = request.args.get("provider") or ""
    if provider not in ("google", "onedrive"):
        flash("Provedor OAuth inválido.", "error")
        return redirect(url_for("admin_banco_dados"))

    if provider == "google":
        return redirect(url_for("admin_backup_google_connect"))
    return redirect(url_for("admin_backup_onedrive_connect"))


@app.route("/auth/callback")
@admin_required
def auth_callback():
    provider = str(session.get("oauth_provider") or "").strip().lower()
    has_oauth_payload = any(
        (request.args.get(key) or "").strip()
        for key in ("state", "code", "error", "error_description")
    )
    _clear_legacy_oauth_session()

    if provider in {"google", "onedrive"} or has_oauth_payload:
        flash(
            "Fluxo OAuth legado desativado. Use a conexão específica do provedor.",
            "error",
        )
        return redirect(url_for("admin_banco_dados"))

    abort(404)


@app.route("/admin/banco-dados/oauth/disconnect", methods=["POST"])
@admin_required
def admin_banco_dados_oauth_disconnect():
    provider = request.form.get("provider") or ""
    if provider not in ("google", "onedrive"):
        flash("Provedor inválido.", "error")
        return redirect(url_for("admin_banco_dados"))

    conn = get_db_connection()
    drive_settings = get_drive_settings(conn)
    prefix = "gdrive" if provider == "google" else "onedrive"
    token = drive_settings.get(f"{prefix}_access_token") or ""

    if provider in ("google", "onedrive"):
        ensure_cloud_backup_schema(conn)
        conn.execute(
            "UPDATE cloud_accounts SET active = 0, updated_at = datetime('now') WHERE provider = ? AND active = 1",
            (provider,),
        )

    if token and provider == "google":
        _cd.google_revoke(token)  # best-effort; failures are silently ignored

    _save_drive_config(conn, {
        f"{prefix}_access_token": "",
        f"{prefix}_refresh_token": "",
        f"{prefix}_expires_at": "",
        f"{prefix}_account_email": "",
        f"{prefix}_last_upload_error": "",
    })
    conn.commit()
    flash(f"{'Google Drive' if provider == 'google' else 'OneDrive'} desconectado.", "success")
    return redirect(url_for("admin_banco_dados"))


@app.route("/admin/banco-dados/drive-settings", methods=["POST"])
@admin_required
def admin_banco_dados_drive_settings():
    provider = request.form.get("provider") or ""
    if provider not in ("google", "onedrive"):
        flash("Provedor inválido.", "error")
        return redirect(url_for("admin_banco_dados"))

    prefix = "gdrive" if provider == "google" else "onedrive"
    dest_folder = (request.form.get(f"{prefix}_dest_folder") or "Backups/sistema").strip()
    enabled = "1" if request.form.get(f"{prefix}_enabled") else "0"

    conn = get_db_connection()
    _save_drive_config(conn, {
        f"{prefix}_dest_folder": dest_folder,
        f"{prefix}_enabled": enabled,
    })
    conn.commit()
    flash("Configurações de destino em nuvem salvas.", "success")
    return redirect(url_for("admin_banco_dados"))


@app.route("/admin/banco-dados/backup", methods=["POST"])
@admin_required
def admin_banco_dados_backup():
    conn = get_db_connection()
    context = _build_database_admin_context(conn)
    settings = context["backup_settings"]
    local_snapshot = create_database_snapshot(
        DATABASE,
        settings["local_backup_dir"],
        schema_status=context["schema_status"],
        reason="manual-backup",
        origin="local",
        logger=logger,
        extra_metadata={"requested_by": session.get("user_id")},
    )
    cloud_result = _maybe_sync_database_snapshot(force=True, conn=conn)
    try:
        external_result = _upload_snapshot_if_external_enabled(local_snapshot, settings)
    except RuntimeError as exc:
        logger.warning("Falha ao enviar snapshot para servidor externo: %s", exc)
        external_result = {"ok": False, "skipped": False, "reason": "external_error", "error": str(exc)}

    if external_result.get("ok") and not external_result.get("skipped"):
        flash("Backup local, snapshot em nuvem e cópia externa enviados com sucesso.", "success")
    elif external_result.get("error"):
        flash(f"Backup local criado, mas o envio ao servidor externo falhou: {external_result['error']}", "warning")
    elif cloud_result.get("skipped"):
        flash(
            "Backup local criado. A sincronização em nuvem foi adiada ou não detectou mudanças.",
            "info",
        )
    else:
        flash("Backup local e snapshot em nuvem criados com sucesso.", "success")
    logger.info(
        "Backup manual solicitado pelo admin %s em %s",
        session.get("user_id"),
        local_snapshot["database_path"],
    )
    try:
        _run_retention_cleanup(conn=conn)
    except Exception as exc:
        logger.warning("Falha ao aplicar política de retenção após backup: %s", exc)
    try:
        _maybe_upload_to_drives(local_snapshot["database_path"], conn=conn)
    except Exception as exc:
        logger.warning("Falha no upload para drives após backup: %s", exc)
    return redirect(url_for("admin_banco_dados"))


@app.route("/admin/banco-dados/download")
@admin_required
def admin_banco_dados_download():
    manifest_path = _resolve_allowed_backup_manifest_path(request.args.get("manifest_path") or "")
    if not manifest_path or not os.path.exists(manifest_path):
        flash("Snapshot solicitado não está disponível para download.", "error")
        return redirect(url_for("admin_banco_dados"))

    try:
        with open(manifest_path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, json.JSONDecodeError):
        flash("Manifesto do snapshot inválido.", "error")
        return redirect(url_for("admin_banco_dados"))

    db_path = manifest.get("database_path") or ""
    if not db_path or not os.path.exists(db_path):
        flash("Arquivo do banco para download não foi encontrado.", "error")
        return redirect(url_for("admin_banco_dados"))

    return send_file(db_path, as_attachment=True, download_name=os.path.basename(db_path))


@app.route("/admin/banco-dados/excluir", methods=["POST"])
@admin_required
def admin_banco_dados_excluir():
    manifest_path = _resolve_allowed_backup_manifest_path(request.form.get("manifest_path") or "")
    if not manifest_path or not os.path.exists(manifest_path):
        flash("Snapshot selecionado não está disponível para exclusão.", "error")
        return redirect(url_for("admin_banco_dados"))

    try:
        delete_database_snapshot(manifest_path, logger=logger)
    except (OSError, json.JSONDecodeError, KeyError, ValueError) as exc:
        flash(f"Não foi possível excluir o snapshot: {exc}", "error")
        return redirect(url_for("admin_banco_dados"))
    flash("Snapshot excluído com sucesso.", "success")
    return redirect(url_for("admin_banco_dados"))


def _get_current_schema_status_for_restore() -> dict[str, object]:
    conn = getattr(g, "db", None)
    if conn is not None:
        current_schema_status = get_schema_status(conn)
        conn.close()
        g.pop("db", None)
        return current_schema_status

    with sqlite3.connect(DATABASE) as temp_conn:
        temp_conn.row_factory = sqlite3.Row
        return get_schema_status(temp_conn)


def _restore_database_from_source(
    source_database_path: str,
    *,
    source_manifest_path: str = "",
    source_upload_name: str = "",
    source_kind: str = "snapshot",
) -> None:
    runtime_settings = _get_runtime_backup_settings()
    extra_metadata = {
        "requested_by": session.get("user_id"),
        "source_kind": source_kind,
    }
    if source_manifest_path:
        extra_metadata["source_manifest_path"] = source_manifest_path
    if source_upload_name:
        extra_metadata["source_upload_name"] = source_upload_name

    create_database_snapshot(
        DATABASE,
        runtime_settings.get("local_backup_dir") or app.config["LOCAL_BACKUP_DIR"],
        schema_status=_get_current_schema_status_for_restore(),
        reason="pre-restore-safety",
        origin="local",
        logger=logger,
        extra_metadata=extra_metadata,
    )
    restore_database_snapshot(source_database_path, DATABASE, logger=logger)

    conn = get_db_connection()
    init_db()
    sync_result = _maybe_sync_database_snapshot(force=True, conn=conn)
    try:
        _run_retention_cleanup(conn=conn)
    except Exception as exc:
        logger.warning("Falha ao aplicar política de retenção após restauração: %s", exc)
    try:
        db_path = (sync_result.get("snapshot") or {}).get("database_path") or ""
        if db_path:
            _maybe_upload_to_drives(db_path, conn=conn)
    except Exception as exc:
        logger.warning("Falha no upload para drives após restauração: %s", exc)


@app.route("/admin/banco-dados/restaurar", methods=["POST"])
@admin_required
def admin_banco_dados_restaurar():
    manifest_path = _resolve_allowed_backup_manifest_path(request.form.get("manifest_path") or "")
    if not manifest_path or not os.path.exists(manifest_path):
        flash("Backup selecionado é inválido ou não está mais disponível.", "error")
        return redirect(url_for("admin_banco_dados"))

    try:
        with open(manifest_path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, json.JSONDecodeError):
        flash("Não foi possível ler o manifesto do backup selecionado.", "error")
        return redirect(url_for("admin_banco_dados"))

    snapshot_path = manifest.get("database_path") or ""
    if not snapshot_path or not os.path.exists(snapshot_path):
        flash("Arquivo do backup não foi encontrado.", "error")
        return redirect(url_for("admin_banco_dados"))

    _restore_database_from_source(
        snapshot_path,
        source_manifest_path=manifest_path,
        source_kind="snapshot",
    )
    flash(
        "Banco restaurado com sucesso. Um snapshot de segurança da base anterior foi salvo localmente.",
        "success",
    )
    return redirect(url_for("admin_banco_dados"))


@app.route("/admin/banco-dados/restaurar/upload", methods=["POST"])
@admin_required
def admin_banco_dados_restaurar_upload():
    request.max_content_length = app.config.get("BACKUP_RESTORE_MAX_CONTENT_LENGTH")
    backup_file = request.files.get("backup_file")
    if not backup_file or not getattr(backup_file, "filename", ""):
        flash("Selecione um arquivo de backup do banco para restaurar.", "error")
        return redirect(url_for("admin_banco_dados"))

    work_dir = tempfile.mkdtemp(prefix="sgaa-restore-upload-")
    restore_artifacts: dict[str, object] = {"work_dir": work_dir}
    try:
        upload_name = secure_filename(str(backup_file.filename or "")) or "backup-banco"
        upload_path = os.path.join(work_dir, upload_name)
        backup_file.save(upload_path)
        restore_artifacts = extract_restore_database_artifact(upload_path, work_dir=work_dir)
        _restore_database_from_source(
            str(restore_artifacts["database_path"]),
            source_upload_name=str(backup_file.filename or upload_name),
            source_kind=str(restore_artifacts.get("source_kind") or "upload"),
        )
    except (BackupServiceError, OSError, sqlite3.Error, ValueError) as exc:
        flash(f"Não foi possível restaurar o arquivo enviado: {exc}", "error")
        return redirect(url_for("admin_banco_dados"))
    finally:
        cleanup_backup_artifacts(restore_artifacts)

    flash(
        "Banco restaurado com sucesso a partir do arquivo enviado. Um snapshot de segurança da base anterior foi salvo localmente.",
        "success",
    )
    return redirect(url_for("admin_banco_dados"))


# Demo: clientes-form pack (visual)
@app.route("/admin/demo/clientes-form-pack")
@admin_required
def admin_demo_clientes_form_pack():
    return render_template("demo_clientes_form_pack.html")

# ===================== Rotas Admin: Cursos (NOVO) =====================








# ===================== Rotas Admin: Arquivos (NOVO) =====================

def _redirect_admin_arquivos_return(default_endpoint: str = "admin_arquivos", **values):
    return_to = (request.form.get("return_to") or request.args.get("return_to") or "").strip()
    if return_to:
        return redirect(return_to)
    return redirect(url_for(default_endpoint, **values))




def _list_admin_arquivos_rows(conn, q: str, sort_field: str, sort_dir: str):
    ensure_admin_arquivos_table(conn)
    where = []
    params = []
    if q:
        like = f"%{q}%"
        where.append("(titulo LIKE ? OR descricao LIKE ? OR original_filename LIKE ?)")
        params.extend([like, like, like])

    order_map = {
        "titulo": "titulo",
        "descricao": "descricao",
        "data_upload": "criado_em",
        "visivel": "visivel",
    }
    col = order_map.get(sort_field, "criado_em")
    direction = "DESC" if sort_dir == "desc" else "ASC"

    sql = """
        SELECT id, titulo, descricao, filename, original_filename, visivel,
               strftime('%d/%m/%Y', criado_em) AS data_upload, criado_em
          FROM admin_arquivos
    """
    sql += append_conditions_sql(False, where)
    sql += f" ORDER BY {col} {direction}, id DESC"
    return conn.execute(sql, params).fetchall()


def _save_admin_arquivo_payload(conn, *, arquivo=None, titulo=None, descricao=None, visivel=1, existing=None):
    ensure_admin_arquivos_table(conn)
    titulo = (titulo or "").strip()
    descricao = (descricao or "").strip() or None
    visivel = 1 if str(visivel).strip() not in {"0", "false", "False"} else 0

    if not titulo:
        raise ValueError("Informe o nome do arquivo.")

    filename = existing["filename"] if existing else None
    original_filename = existing["original_filename"] if existing else None
    new_saved_file = None
    if arquivo and getattr(arquivo, "filename", ""):
        if not _allowed(arquivo.filename, ALLOWED_ATTACHMENTS):
            raise ValueError("Envie um arquivo PDF, PNG ou JPG válido.")
        new_saved_file = save_upload(
            arquivo,
            ALLOWED_ATTACHMENTS,
            prefix="admin-arquivo",
            subdir="admin_arquivos",
        )
        filename = new_saved_file
        original_filename = arquivo.filename

    if not filename:
        raise ValueError("Selecione um arquivo para enviar.")

    return {
        "titulo": titulo,
        "descricao": descricao,
        "visivel": visivel,
        "filename": filename,
        "original_filename": original_filename,
        "new_saved_file": new_saved_file,
    }


def _best_effort_remove_admin_arquivo_file(rel_path):
    if not rel_path:
        return
    try:
        upload_root = app.config.get("UPLOAD_FOLDER")
        if not upload_root:
            return
        file_path = os.path.normpath(os.path.join(upload_root, rel_path))
        if os.path.isfile(file_path):
            os.remove(file_path)
    except Exception as exc:
        logger.warning(f"Falha ao remover arquivo admin '{rel_path}': {exc}")

@app.route("/admin/arquivos")
@admin_required
def admin_arquivos():
    q = (request.args.get("q") or "").strip()
    titulo_filter = get_text_query_value("titulo")
    descricao_filter = get_text_query_value("descricao")
    tipo_filters = {
        str(value or "").strip().lower()
        for value in get_multi_query_values("tipo")
        if str(value or "").strip()
    }
    data_upload_min, data_upload_max = get_date_range_query("data_upload")
    visivel_filters = [value for value in get_multi_query_values("visivel") if value in {"0", "1"}]
    sort_field = (request.args.get("s") or "data_upload").strip()
    sort_dir = (request.args.get("dir") or "desc").strip().lower()
    edit_id = request.args.get("edit_arquivo", type=int)

    conn = get_db_connection()
    arquivos_rows = _list_admin_arquivos_rows(conn, q, sort_field, sort_dir)
    arquivos = []
    tipos_disponiveis = set()
    for row in arquivos_rows:
        item = {key: row[key] for key in row.keys()}
        source_name = item.get("original_filename") or item.get("filename") or ""
        tipo = os.path.splitext(source_name)[1].lstrip(".").upper() or "ARQUIVO"
        item["tipo"] = tipo
        tipos_disponiveis.add(tipo)
        arquivos.append(item)

    if titulo_filter:
        filtro = titulo_filter.casefold()
        arquivos = [
            arquivo
            for arquivo in arquivos
            if filtro in str(arquivo.get("titulo") or "").casefold()
        ]

    if descricao_filter:
        filtro = descricao_filter.casefold()
        arquivos = [
            arquivo
            for arquivo in arquivos
            if filtro in str(arquivo.get("descricao") or "").casefold()
        ]

    if tipo_filters:
        arquivos = [
            arquivo
            for arquivo in arquivos
            if str(arquivo.get("tipo") or "").strip().lower() in tipo_filters
        ]

    if data_upload_min or data_upload_max:
        filtrados = []
        for arquivo in arquivos:
            created_date = str(arquivo.get("criado_em") or "")[:10]
            if data_upload_min and (not created_date or created_date < data_upload_min):
                continue
            if data_upload_max and (not created_date or created_date > data_upload_max):
                continue
            filtrados.append(arquivo)
        arquivos = filtrados

    if visivel_filters:
        visivel_set = set(visivel_filters)
        arquivos = [arquivo for arquivo in arquivos if str(arquivo.get("visivel")) in visivel_set]

    edit_arquivo = get_admin_arquivo(conn, edit_id) if edit_id else None
    filter_schema = [
        {
            "param": "titulo",
            "label": "Título",
            "type": "text_contains",
            "placeholder": "Contém no título",
        },
        {
            "param": "tipo",
            "label": "Tipo de arquivo",
            "type": "multi_select",
            "values": [
                {"value": tipo, "label": tipo}
                for tipo in sorted(tipos_disponiveis)
            ],
        },
        {
            "param": "descricao",
            "label": "Descrição",
            "type": "text_contains",
            "placeholder": "Contém na descrição",
        },
        {
            "param": "data_upload",
            "label": "Data de upload",
            "type": "date_range",
            "min_label": "De",
            "max_label": "Até",
        },
        {
            "param": "visivel",
            "label": "Visibilidade",
            "type": "multi_select",
            "values": [
                {"value": "1", "label": "Visível"},
                {"value": "0", "label": "Oculto"},
            ],
        },
    ]

    return render_template(
        "admin_arquivos.html",
        arquivos=arquivos,
        edit_arquivo=edit_arquivo,
        filter_schema=filter_schema,
    )


@app.route("/admin/arquivos/adicionar", methods=["POST"])
@admin_required
def admin_adicionar_arquivo():
    conn = get_db_connection()
    try:
        payload = _save_admin_arquivo_payload(
            conn,
            arquivo=request.files.get("arquivo"),
            titulo=request.form.get("titulo"),
            descricao=request.form.get("descricao"),
            visivel=request.form.get("visivel", "1"),
        )
        conn.execute(
            """
            INSERT INTO admin_arquivos (titulo, descricao, filename, original_filename, visivel)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                payload["titulo"],
                payload["descricao"],
                payload["filename"],
                payload["original_filename"],
                payload["visivel"],
            ),
        )
        conn.commit()
        flash("Arquivo cadastrado com sucesso.", "success")
        return _redirect_admin_arquivos_return()
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin_arquivos"))


@app.route("/admin/arquivos/<int:arquivo_id>/editar", methods=["GET", "POST"])
@admin_required
def admin_editar_arquivo(arquivo_id):
    conn = get_db_connection()
    arquivo = get_admin_arquivo(conn, arquivo_id)
    if not arquivo:
        flash("Arquivo não encontrado.", "error")
        return redirect(url_for("admin_arquivos"))

    if request.method == "GET":
        return redirect(url_for("admin_arquivos", edit_arquivo=arquivo_id))

    try:
        payload = _save_admin_arquivo_payload(
            conn,
            arquivo=request.files.get("arquivo"),
            titulo=request.form.get("titulo"),
            descricao=request.form.get("descricao"),
            visivel=request.form.get("visivel", "1"),
            existing=arquivo,
        )
        conn.execute(
            """
            UPDATE admin_arquivos
               SET titulo = ?, descricao = ?, filename = ?, original_filename = ?, visivel = ?
             WHERE id = ?
            """,
            (
                payload["titulo"],
                payload["descricao"],
                payload["filename"],
                payload["original_filename"],
                payload["visivel"],
                arquivo_id,
            ),
        )
        conn.commit()
        if payload["new_saved_file"] and arquivo["filename"] != payload["new_saved_file"]:
            _best_effort_remove_admin_arquivo_file(arquivo["filename"])
        flash("Arquivo atualizado com sucesso.", "success")
        return _redirect_admin_arquivos_return()
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin_arquivos", edit_arquivo=arquivo_id))


@app.route("/admin/arquivos/<int:arquivo_id>/visualizar")
@admin_required
def admin_visualizar_arquivo(arquivo_id):
    conn = get_db_connection()
    arquivo = get_admin_arquivo(conn, arquivo_id)
    if not arquivo:
        flash("Arquivo não encontrado.", "error")
        return redirect(url_for("admin_arquivos"))
    safe_filename = os.path.normpath(arquivo["filename"]).replace("\\", "/").lstrip("/")
    return redirect(url_for("uploaded_file", filename=safe_filename))


@app.route("/admin/arquivos/<int:arquivo_id>/deletar", methods=["POST"])
@admin_required
def admin_deletar_arquivo(arquivo_id):
    conn = get_db_connection()
    arquivo = get_admin_arquivo(conn, arquivo_id)
    if not arquivo:
        flash("Arquivo não encontrado.", "error")
        return redirect(url_for("admin_arquivos"))

    conn.execute("DELETE FROM admin_arquivos WHERE id = ?", (arquivo_id,))
    conn.commit()
    _best_effort_remove_admin_arquivo_file(arquivo["filename"])
    flash("Arquivo excluído com sucesso.", "success")
    return _redirect_admin_arquivos_return()


# ===================== Rotas Admin: Atividades =====================














# ===================== Rotas Admin: Alunos =====================






# ===================== Rotas Admin: Turmas =====================






# ====== Importar Alunos (CSV) para uma Turma ======


# ===================== Rotas Aluno =====================





@app.route("/admin/meus_dados", methods=["GET", "POST"])
@admin_required
def admin_meus_dados():
    conn = get_db_connection()
    ensure_usuario_profile_schema(conn)
    usuario_id = session["user_id"]
    profile = conn.execute(
        "SELECT nome, email, foto_perfil FROM usuarios WHERE id = ?",
        (usuario_id,),
    ).fetchone()

    if not profile:
        flash("Usuário não encontrado.", "error")
        return redirect(url_for("admin_dashboard"))

    if request.method == "POST":
        nome = request.form["nome"]
        email = request.form["email"]
        senha = request.form.get("senha")

        try:
            if senha:
                hashed_password = hash_password(senha)
                conn.execute(
                    "UPDATE usuarios SET nome = ?, email = ?, senha = ? WHERE id = ?",
                    (nome, email, hashed_password, usuario_id),
                )
            else:
                conn.execute(
                    "UPDATE usuarios SET nome = ?, email = ? WHERE id = ?",
                    (nome, email, usuario_id),
                )

            session["user_name"] = nome

            remove_foto = request.form.get("remove_foto") == "1"
            foto_file = request.files.get("foto_perfil")
            if remove_foto:
                conn.execute("UPDATE usuarios SET foto_perfil = NULL WHERE id = ?", (usuario_id,))
                session.pop("foto_perfil", None)
            elif foto_file and foto_file.filename:
                try:
                    foto_rel = save_upload(
                        foto_file,
                        {"png", "jpg", "jpeg"},
                        prefix="avatar",
                        subdir=f"avatars/usuario_{usuario_id}",
                    )
                    if foto_rel:
                        conn.execute(
                            "UPDATE usuarios SET foto_perfil = ? WHERE id = ?",
                            (foto_rel, usuario_id),
                        )
                        session["foto_perfil"] = foto_rel
                except ValueError:
                    flash("Foto inválida. Use PNG ou JPG.", "error")

            conn.commit()
            flash("Seus dados foram atualizados com sucesso.", "success")
            return redirect(url_for("admin_meus_dados"))
        except sqlite3.IntegrityError as exc:
            if "UNIQUE constraint failed: usuarios.email" in str(exc):
                flash("Erro: Já existe outro usuário com este e-mail.", "error")
            else:
                flash(f"Erro ao atualizar dados: {exc}", "error")
        except Exception as exc:
            flash(f"Erro inesperado ao atualizar dados: {exc}", "error")

    return render_template(
        "aluno_meus_dados.html",
        base_template="base.html",
        profile=profile,
        show_student_fields=False,
        cancel_url=url_for("admin_dashboard"),
        turmas=[],
    )





# ===================== Rotas Admin: Catálogo Versionado (read-only) =====================

























ALERTA_COLOR_OPTIONS = [
    {"label": "Azul", "bg": "#e3eefd", "border": "#7e95b2"},
    {"label": "Amarelo", "bg": "#fef4c0", "border": "#c9a227"},
    {"label": "Verde", "bg": "#dcfaeb", "border": "#4ea86a"},
    {"label": "Laranja", "bg": "#ffecd4", "border": "#c07a3a"},
    {"label": "Vermelho", "bg": "#fee2e2", "border": "#bb6464"},
    {"label": "Roxo", "bg": "#ede9fe", "border": "#8872c4"},
    {"label": "Ciano", "bg": "#cffafe", "border": "#3aaab8"},
]

AUTO_ALERT_YELLOW_BG = "#fef4c0"
AUTO_ALERT_YELLOW_BORDER = "#c9a227"


def _normalize_hex_color(value: str | None, fallback: str | None = None) -> str:
    candidate = (value or "").strip().lower()
    if re.fullmatch(r"#[0-9a-f]{3}", candidate):
        candidate = "#" + "".join(ch * 2 for ch in candidate[1:])
    if re.fullmatch(r"#[0-9a-f]{6}", candidate):
        return candidate
    return (fallback or ALERTA_COLOR_OPTIONS[0]["bg"]).strip().lower()


def _derive_border_from_hex(bg_color: str) -> str:
    normalized = _normalize_hex_color(bg_color)
    red = int(normalized[1:3], 16)
    green = int(normalized[3:5], 16)
    blue = int(normalized[5:7], 16)
    luminance = ((0.299 * red) + (0.587 * green) + (0.114 * blue)) / 255
    target = 0 if luminance > 0.72 else 255
    weight = 0.18 if luminance > 0.72 else 0.26

    def _mix(channel: int) -> int:
        return max(0, min(255, round((channel * (1 - weight)) + (target * weight))))

    return "#{:02x}{:02x}{:02x}".format(_mix(red), _mix(green), _mix(blue))


def _alerta_border_for(bg_color: str) -> str:
    normalized = _normalize_hex_color(bg_color)
    for option in ALERTA_COLOR_OPTIONS:
        if option["bg"].lower() == normalized:
            return option["border"]
    return _derive_border_from_hex(normalized)


def _turma_label_by_id(conn, turma_id: int | None) -> str:
    if not turma_id:
        return ""
    row = conn.execute(
        "SELECT COALESCE(codigo, nome) AS label FROM turmas WHERE id = ?",
        (turma_id,),
    ).fetchone()
    return (row["label"] or "") if row else ""


def _reporte_status_badge_type(status: str | None) -> str:
    normalized = str(status or "").strip()
    if normalized == "Resolvido":
        return "success"
    if normalized == "Em análise":
        return "warning"
    return "danger" if normalized else "warning"


@app.route("/admin/reportes")
@admin_required
def admin_reportes():
    page, per_page, offset = get_pagination(default_per_page=20)
    q = (request.args.get("q") or "").strip()
    status_filters = [item for item in get_multi_query_values("status") if item in REPORTE_STATUS_OPTIONS]
    categoria_filters = [item for item in get_multi_query_values("categoria") if item in REPORTE_CATEGORY_OPTIONS]
    aluno_filter = get_text_query_value("aluno")
    matricula_filter = get_text_query_value("matricula")
    titulo_filter = get_text_query_value("titulo")
    data_min, data_max = get_date_range_query("criado_em")
    sort_field = (request.args.get("s") or "data").strip().lower()
    sort_dir = (request.args.get("dir") or "desc").strip().lower()

    conn = get_db_connection()
    ensure_reportes_table(conn)

    base_from = (
        " FROM reportes rep"
        " JOIN alunos a ON a.id = rep.aluno_id"
        " LEFT JOIN usuarios u ON u.id = a.usuario_id"
    )
    where = []
    params: list[object] = []

    if q:
        like = f"%{q}%"
        where.append(
            "(LOWER(rep.titulo) LIKE LOWER(?) OR LOWER(rep.descricao) LIKE LOWER(?) OR LOWER(COALESCE(a.nome, '')) LIKE LOWER(?) OR LOWER(COALESCE(a.matricula, '')) LIKE LOWER(?))"
        )
        params.extend([like, like, like, like])
    append_text_contains_condition(where, params, "a.nome", aluno_filter)
    append_text_contains_condition(where, params, "a.matricula", matricula_filter)
    append_text_contains_condition(where, params, "rep.titulo", titulo_filter)
    if status_filters:
        placeholders = ", ".join("?" for _ in status_filters)
        where.append(f"rep.status IN ({placeholders})")
        params.extend(status_filters)
    if categoria_filters:
        placeholders = ", ".join("?" for _ in categoria_filters)
        where.append(f"rep.categoria IN ({placeholders})")
        params.extend(categoria_filters)
    if data_min:
        where.append("date(rep.criado_em) >= date(?)")
        params.append(data_min)
    if data_max:
        where.append("date(rep.criado_em) <= date(?)")
        params.append(data_max)

    where_sql = append_conditions_sql(False, where)
    total = conn.execute("SELECT COUNT(*)" + base_from + where_sql, params).fetchone()[0]

    sort_map = {
        "data": "datetime(rep.criado_em)",
        "aluno": "LOWER(COALESCE(a.nome, ''))",
        "titulo": "LOWER(rep.titulo)",
        "categoria": "LOWER(rep.categoria)",
        "status": "LOWER(rep.status)",
    }
    order_col = sort_map.get(sort_field, sort_map["data"])
    direction = "DESC" if sort_dir == "desc" else "ASC"

    query = (
        "SELECT rep.id, rep.titulo, rep.descricao, rep.categoria, rep.screenshot_filename, rep.status,"
        " rep.criado_em, rep.atualizado_em, a.nome AS aluno_nome, a.matricula,"
        " COALESCE(u.email, a.email, '') AS aluno_email"
        + base_from
        + where_sql
        + f" ORDER BY {order_col} {direction}, rep.id DESC"
    )
    exec_params = list(params)
    apply_limit = wants_pagination()
    if apply_limit:
        query += " LIMIT ? OFFSET ?"
        exec_params += [per_page, offset]

    rows = conn.execute(query, exec_params).fetchall()
    reportes = [
        {
            "id": row["id"],
            "titulo": row["titulo"],
            "descricao": row["descricao"],
            "categoria": row["categoria"],
            "screenshot_filename": row["screenshot_filename"],
            "status": row["status"],
            "status_badge_type": _reporte_status_badge_type(row["status"]),
            "criado_em_fmt": format_date_ptbr(row["criado_em"]),
            "atualizado_em_fmt": format_date_ptbr(row["atualizado_em"]),
            "aluno_nome": row["aluno_nome"],
            "matricula": row["matricula"],
            "aluno_email": row["aluno_email"],
        }
        for row in rows
    ]
    total_pages = (total + per_page - 1) // per_page if apply_limit and per_page else 1
    filter_schema = [
        {
            "param": "aluno",
            "label": "Aluno",
            "type": "text_contains",
            "placeholder": "Contém no nome",
        },
        {
            "param": "matricula",
            "label": "Matrícula",
            "type": "text_contains",
            "placeholder": "Contém na matrícula",
        },
        {
            "param": "titulo",
            "label": "Título",
            "type": "text_contains",
            "placeholder": "Contém no título",
        },
        {
            "param": "criado_em",
            "label": "Data",
            "type": "date_range",
            "min_label": "De",
            "max_label": "Até",
        },
        {
            "param": "status",
            "label": "Status",
            "type": "multi_select",
            "values": [{"value": s, "label": s} for s in REPORTE_STATUS_OPTIONS],
        },
        {
            "param": "categoria",
            "label": "Categoria",
            "type": "multi_select",
            "values": [{"value": c, "label": c} for c in REPORTE_CATEGORY_OPTIONS],
        },
    ]
    return render_template(
        "admin_reportes.html",
        reportes=reportes,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        filter_schema=filter_schema,
        status_options=REPORTE_STATUS_OPTIONS,
        categoria_options=REPORTE_CATEGORY_OPTIONS,
    )


@app.route("/admin/reportes/<int:reporte_id>/status", methods=["POST"])
@admin_required
def admin_reportes_atualizar_status(reporte_id: int):
    status = (request.form.get("status") or "").strip()
    if status not in REPORTE_STATUS_OPTIONS:
        flash("Selecione um status válido para o reporte.", "error")
        return redirect(url_for("admin_reportes"))

    conn = get_db_connection()
    ensure_reportes_table(conn)
    reporte = conn.execute("SELECT id FROM reportes WHERE id = ?", (reporte_id,)).fetchone()
    if not reporte:
        flash("Reporte não encontrado.", "error")
        return redirect(url_for("admin_reportes"))

    conn.execute(
        """
        UPDATE reportes
           SET status = ?,
               atualizado_em = datetime('now'),
               admin_id = ?
         WHERE id = ?
        """,
        (status, session.get("user_id"), reporte_id),
    )
    conn.commit()
    flash("Status do reporte atualizado.", "success")
    return redirect(url_for("admin_reportes"))


@app.route("/admin/reportes/<int:reporte_id>/deletar", methods=["POST"])
@admin_required
def admin_reportes_deletar(reporte_id: int):
    conn = get_db_connection()
    ensure_reportes_table(conn)
    reporte = conn.execute("SELECT id FROM reportes WHERE id = ?", (reporte_id,)).fetchone()
    if not reporte:
        flash("Reporte não encontrado.", "error")
        return redirect(url_for("admin_reportes"))
    conn.execute("DELETE FROM reportes WHERE id = ?", (reporte_id,))
    conn.commit()
    flash("Reporte excluído.", "success")
    return redirect(url_for("admin_reportes"))


@app.route("/admin/alertas")
@admin_required
def admin_alertas():
    page, per_page, offset = get_pagination(default_per_page=25)
    q = (request.args.get("q") or "").strip()
    sort_field = (request.args.get("s") or "titulo").strip().lower()
    sort_dir = (request.args.get("dir") or "asc").strip().lower()
    titulo_filter = get_text_query_value("titulo")
    status_filters = {item.lower() for item in get_multi_query_values("status")}
    allowed_bg_colors = {option["bg"].lower() for option in ALERTA_COLOR_OPTIONS}
    bg_color_filters = []
    for raw in get_multi_query_values("bg_color"):
        normalized = _normalize_hex_color(raw, "__invalid__")
        if normalized in allowed_bg_colors and normalized not in bg_color_filters:
            bg_color_filters.append(normalized)

    conn = get_db_connection()
    ensure_admin_alertas_table(conn)

    base_from = " FROM admin_alertas "
    where = []
    params = []
    if q:
        like = f"%{q}%"
        where.append("(COALESCE(titulo, '') LIKE ? OR mensagem LIKE ?)")
        params.extend([like, like])
    append_text_contains_condition(where, params, "COALESCE(titulo, mensagem)", titulo_filter)
    if status_filters:
        status_where = []
        if "ativo" in status_filters:
            status_where.append("visivel = 1")
        if "inativo" in status_filters:
            status_where.append("visivel = 0")
        if status_where:
            where.append("(" + " OR ".join(status_where) + ")")
    if bg_color_filters:
        placeholders = ", ".join("?" for _ in bg_color_filters)
        where.append(f"LOWER(bg_color) IN ({placeholders})")
        params.extend(bg_color_filters)

    where_sql = append_conditions_sql(False, where)
    order_map = {
        "titulo": "LOWER(COALESCE(titulo, mensagem))",
        "bg_color": "LOWER(bg_color)",
        "status": "visivel",
    }
    order_col = order_map.get(sort_field, order_map["titulo"])
    direction = "DESC" if sort_dir == "desc" else "ASC"
    count_sql = "SELECT COUNT(*)" + base_from + where_sql
    total = conn.execute(count_sql, params).fetchone()[0]

    query = (
        "SELECT id, COALESCE(NULLIF(TRIM(titulo), ''), mensagem) AS titulo, mensagem, bg_color, border_color, visivel, criado_em"
        + base_from
        + where_sql
        + f" ORDER BY {order_col} {direction}, id DESC"
    )
    params_exec = list(params)
    apply_limit = wants_pagination()
    if apply_limit:
        query += " LIMIT ? OFFSET ?"
        params_exec += [per_page, offset]
    rows = conn.execute(query, params_exec).fetchall()
    alertas = [
        {
            "id": row["id"],
            "titulo": row["titulo"],
            "mensagem": row["mensagem"],
            "bg_color": row["bg_color"],
            "border_color": row["border_color"],
            "visivel": bool(row["visivel"]),
            "criado_em": row["criado_em"],
        }
        for row in rows
    ]
    filter_schema = [
        {
            "param": "titulo",
            "label": "Nome do alerta",
            "type": "text_contains",
            "placeholder": "Contém no nome",
        },
        {
            "param": "bg_color",
            "label": "Cor",
            "type": "multi_select",
            "values": [
                {"value": option["bg"], "label": option.get("label") or option["bg"]}
                for option in ALERTA_COLOR_OPTIONS
            ],
        },
        {
            "param": "status",
            "label": "Status",
            "type": "multi_select",
            "values": [
                {"value": "ativo", "label": "Ativo"},
                {"value": "inativo", "label": "Inativo"},
            ],
        }
    ]
    total_pages = (total + per_page - 1) // per_page if apply_limit and per_page else 1
    return render_template(
        "admin_alertas.html",
        alertas=alertas,
        filter_schema=filter_schema,
        alerta_color_options=ALERTA_COLOR_OPTIONS,
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages,
    )


@app.route("/admin/alertas/salvar", methods=["POST"])
@admin_required
def admin_salvar_alerta():
    conn = get_db_connection()
    ensure_admin_alertas_table(conn)

    alerta_id = request.form.get("alerta_id", type=int)
    titulo = (request.form.get("titulo") or "").strip()
    mensagem = (request.form.get("mensagem") or "").strip()
    bg_color = _normalize_hex_color(request.form.get("bg_color"), ALERTA_COLOR_OPTIONS[0]["bg"])
    border_color_raw = (request.form.get("border_color") or "").strip()
    border_color = _normalize_hex_color(border_color_raw, _alerta_border_for(bg_color)) if border_color_raw else _alerta_border_for(bg_color)
    visivel = 1 if (request.form.get("visivel") or "1") == "1" else 0

    if not titulo or not mensagem:
        flash("Título e mensagem do alerta são obrigatórios.", "error")
        return redirect(url_for("admin_alertas"))

    if alerta_id:
        conn.execute(
            """
            UPDATE admin_alertas
               SET titulo = ?, mensagem = ?, bg_color = ?, border_color = ?, visivel = ?
             WHERE id = ?
            """,
            (titulo, mensagem, bg_color, border_color, visivel, alerta_id),
        )
        flash("Alerta atualizado com sucesso.", "success")
    else:
        conn.execute(
            """
            INSERT INTO admin_alertas (titulo, mensagem, bg_color, border_color, visivel)
            VALUES (?, ?, ?, ?, ?)
            """,
            (titulo, mensagem, bg_color, border_color, visivel),
        )
        flash("Alerta criado com sucesso.", "success")
    conn.commit()
    return redirect(url_for("admin_alertas"))


@app.route("/admin/alertas/<int:alerta_id>/alternar", methods=["POST"])
@admin_required
def admin_alternar_alerta(alerta_id):
    conn = get_db_connection()
    ensure_admin_alertas_table(conn)
    conn.execute(
        "UPDATE admin_alertas SET visivel = CASE WHEN visivel = 1 THEN 0 ELSE 1 END WHERE id = ?",
        (alerta_id,),
    )
    conn.commit()
    flash("Status do alerta atualizado.", "success")
    return redirect(url_for("admin_alertas"))


@app.route("/admin/alertas/<int:alerta_id>/deletar", methods=["POST"])
@admin_required
def admin_deletar_alerta(alerta_id):
    conn = get_db_connection()
    ensure_admin_alertas_table(conn)
    conn.execute("DELETE FROM admin_alertas WHERE id = ?", (alerta_id,))
    conn.commit()
    flash("Alerta excluído com sucesso.", "success")
    return redirect(url_for("admin_alertas"))


@app.route("/admin/acesso")
@admin_required
def admin_acesso():
    page, per_page, offset = get_pagination(default_per_page=25)
    q = (request.args.get("q") or "").strip()
    sort_field = (request.args.get("s") or "nome").strip().lower()
    sort_dir = (request.args.get("dir") or "asc").strip().lower()
    nome_filter = get_text_query_value("nome")
    email_filter = get_text_query_value("email")
    matricula_filter = get_text_query_value("matricula")
    turma_filters = get_int_multi_query_values("turma_id")
    nivel_filters = {canonicalize_access_level(item) for item in get_multi_query_values("nivel")}
    tipo_filters = {str(item or "").strip().lower() for item in get_multi_query_values("tipo")}

    conn = get_db_connection()
    ensure_usuario_access_schema(conn)
    ensure_usuario_profile_schema(conn)

    summary_rows = conn.execute(
        "SELECT nivel_acesso, COUNT(*) AS total FROM usuarios GROUP BY nivel_acesso"
    ).fetchall()
    summary = {"admin_total": 0, "consultivo": 0, "administrativo": 0, "usuario": 0, "usuario_teste": 0}
    for row in summary_rows:
        summary[canonicalize_access_level(row["nivel_acesso"])] = row["total"]

    access_defaults = _access_defaults_map(conn)
    turmas = conn.execute(
        "SELECT id, COALESCE(codigo, nome) AS nome FROM turmas ORDER BY nome"
    ).fetchall()

    base_from = """
        FROM usuarios u
        LEFT JOIN alunos a ON a.usuario_id = u.id
        LEFT JOIN turmas t ON t.id = a.turma_id
    """
    where = []
    params = []
    if q:
        like = f"%{q}%"
        where.append(
            "(u.nome LIKE ? OR u.email LIKE ? OR COALESCE(a.matricula, '') LIKE ? OR COALESCE(t.codigo, t.nome, a.turma, '') LIKE ?)"
        )
        params.extend([like, like, like, like])
    append_text_contains_condition(where, params, "u.nome", nome_filter)
    append_text_contains_condition(where, params, "u.email", email_filter)
    append_text_contains_condition(where, params, "a.matricula", matricula_filter)
    if turma_filters:
        placeholders = ", ".join("?" for _ in turma_filters)
        where.append(f"a.turma_id IN ({placeholders})")
        params.extend(turma_filters)
    if nivel_filters:
        placeholders = ", ".join("?" for _ in nivel_filters)
        where.append(f"u.nivel_acesso IN ({placeholders})")
        params.extend(sorted(nivel_filters))
    if tipo_filters:
        placeholders = ", ".join("?" for _ in tipo_filters)
        where.append(f"u.tipo IN ({placeholders})")
        params.extend(sorted(tipo_filters))

    where_sql = append_conditions_sql(False, where)
    order_map = {
        "nome": "LOWER(u.nome)",
        "email": "LOWER(u.email)",
        "nivel": "LOWER(u.nivel_acesso)",
        "perfil": "LOWER(u.tipo)",
        "matricula": "LOWER(COALESCE(a.matricula, ''))",
    }
    order_col = order_map.get(sort_field, order_map["nome"])
    direction = "DESC" if sort_dir == "desc" else "ASC"
    count_sql = "SELECT COUNT(*) " + base_from + where_sql
    total = conn.execute(count_sql, params).fetchone()[0]
    query = (
        """
        SELECT
            u.id,
            u.nome,
            u.email,
            u.tipo,
            u.nivel_acesso,
            a.id AS aluno_id,
            a.matricula,
            a.status AS aluno_status,
            a.turma_id,
            COALESCE(t.codigo, t.nome, a.turma, '') AS turma_label
        """
        + base_from
        + where_sql
        + f" ORDER BY {order_col} {direction}, u.id DESC"
    )
    params_exec = list(params)
    apply_limit = wants_pagination()
    if apply_limit:
        query += " LIMIT ? OFFSET ?"
        params_exec += [per_page, offset]

    rows = conn.execute(query, params_exec).fetchall()
    current_user_id = session.get("user_id")
    users = []
    users_payload = {}
    for row in rows:
        nivel = canonicalize_access_level(row["nivel_acesso"])
        tipo = (row["tipo"] or "admin").strip().lower()
        is_student = tipo == "aluno"
        access_context = _load_admin_access_context(conn, row["id"]) if not is_student else {
            "is_admin": False,
            "overrides": {},
            "effective_scopes": {},
            "scope_groups": [],
        }
        users.append(
            {
                "id": row["id"],
                "nome": row["nome"],
                "email": row["email"],
                "tipo": tipo,
                "tipo_label": "Aluno" if is_student else "Admin",
                "nivel_acesso": nivel,
                "nivel_label": access_level_label(nivel),
                "matricula": row["matricula"] if is_student else "",
                "turma_id": row["turma_id"] if is_student else "",
                "turma_label": row["turma_label"] if is_student else "",
                "aluno_status": row["aluno_status"] if is_student else "Ativo",
                "has_aluno": bool(row["aluno_id"]) and is_student,
                "is_current_user": row["id"] == current_user_id,
                "scope_summary": access_context.get("scope_groups", []),
            }
        )
        users_payload[str(row["id"])] = {
            "id": row["id"],
            "nome": row["nome"],
            "email": row["email"],
            "tipo": tipo,
            "level": nivel,
            "matricula": row["matricula"] if is_student else "",
            "turmaId": row["turma_id"] if is_student else "",
            "turmaLabel": row["turma_label"] if is_student else "",
            "status": row["aluno_status"] if is_student else "Ativo",
            "isSelf": row["id"] == current_user_id,
            "canCustomize": not is_student,
            "accessOverrides": access_context.get("overrides", {}),
            "effectiveScopes": access_context.get("effective_scopes", {}),
            "scopeGroups": access_context.get("scope_groups", []),
        }

    filter_schema = [
        {
            "param": "nome",
            "label": "Nome",
            "type": "text_contains",
            "placeholder": "Contém no nome",
        },
        {
            "param": "email",
            "label": "E-mail",
            "type": "text_contains",
            "placeholder": "Contém no e-mail",
        },
        {
            "param": "matricula",
            "label": "Matrícula",
            "type": "text_contains",
            "placeholder": "Contém na matrícula",
        },
        {
            "param": "turma_id",
            "label": "Turma",
            "type": "multi_select",
            "values": [
                {"value": str(turma["id"]), "label": turma["nome"]}
                for turma in turmas
            ],
        },
        {
            "param": "nivel",
            "label": "Nível",
            "type": "multi_select",
            "values": [
                {"value": "admin_total", "label": "Admin"},
                {"value": "consultivo", "label": "Consultor"},
                {"value": "administrativo", "label": "Coordenador"},
                {"value": "usuario", "label": "Usuário"},
                {"value": "usuario_teste", "label": "Usuário teste"},
            ],
        },
        {
            "param": "tipo",
            "label": "Perfil base",
            "type": "multi_select",
            "values": [
                {"value": "admin", "label": "Admin"},
                {"value": "aluno", "label": "Aluno"},
            ],
        },
    ]
    access_resource_groups = []
    for group_label, resources in ACCESS_RESOURCE_GROUPS:
        access_resource_groups.append(
            {
                "label": group_label,
                "items": [
                    {
                        "resource": resource,
                        "label": ACCESS_RESOURCES_META[resource]["label"],
                    }
                    for resource in resources
                ],
            }
        )
    access_scope_options = [
        {"value": "inherit", "label": "Herdar perfil"},
        {"value": "none", "label": permission_scope_label("none")},
        {"value": "view", "label": permission_scope_label("view")},
        {"value": "edit", "label": permission_scope_label("edit")},
        {"value": "full", "label": permission_scope_label("full")},
    ]
    access_level_choices = [
        {"value": value, "label": meta["label"]}
        for value, meta in ACCESS_LEVEL_META.items()
    ]
    access_profile_defaults = {
        level: merge_resource_scopes(level)
        for level in ACCESS_LEVEL_META
    }
    total_pages = (total + per_page - 1) // per_page if apply_limit and per_page else 1
    return render_template(
        "admin_acesso.html",
        summary=summary,
        access_defaults=access_defaults,
        access_level_choices=access_level_choices,
        access_profile_defaults=access_profile_defaults,
        access_resource_groups=access_resource_groups,
        access_scope_options=access_scope_options,
        turmas=turmas,
        users=users,
        users_payload=users_payload,
        filter_schema=filter_schema,
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages,
    )


@app.route("/admin/acesso/senhas-default", methods=["POST"])
@admin_required
def admin_acesso_salvar_senhas_default():
    conn = get_db_connection()
    ensure_usuario_access_schema(conn)
    updates = {
        "admin_total": (request.form.get("default_admin_total") or "").strip(),
        "consultivo": (request.form.get("default_consultivo") or "").strip(),
        "administrativo": (request.form.get("default_administrativo") or "").strip(),
        "usuario": (request.form.get("default_usuario") or "").strip(),
        "usuario_teste": (request.form.get("default_usuario_teste") or "").strip(),
    }
    if not all(updates.values()):
        flash("Todas as senhas default precisam ser informadas.", "error")
        return redirect(url_for("admin_acesso"))
    for nivel, senha_padrao in updates.items():
        conn.execute(
            """
            INSERT INTO configuracoes_acesso (nivel_acesso, senha_padrao)
            VALUES (?, ?)
            ON CONFLICT(nivel_acesso) DO UPDATE SET senha_padrao = excluded.senha_padrao
            """,
            (nivel, senha_padrao),
        )
    conn.commit()
    flash("Senhas padrão atualizadas com sucesso.", "success")
    return redirect(url_for("admin_acesso"))


@app.route("/admin/acesso/salvar", methods=["POST"])
@admin_required
def admin_acesso_salvar():
    conn = get_db_connection()
    ensure_usuario_access_schema(conn)
    ensure_usuario_profile_schema(conn)

    usuario_id = request.form.get("usuario_id", type=int)
    nome = (request.form.get("nome") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    nivel_acesso = canonicalize_access_level(request.form.get("nivel_acesso"))
    user_type = access_level_to_user_type(nivel_acesso)
    senha = (request.form.get("senha") or "").strip()
    matricula = (request.form.get("matricula") or "").strip()
    status_aluno = (request.form.get("status") or "Ativo").strip()
    turma_id = request.form.get("turma_id", type=int)
    access_overrides = _parse_access_overrides_from_form(request.form) if user_type == "admin" else {}

    if not nome or not email:
        flash("Nome e e-mail são obrigatórios.", "error")
        return redirect(url_for("admin_acesso"))
    if user_type == "aluno" and not matricula:
        flash("Matrícula é obrigatória para perfis de aluno.", "error")
        return redirect(url_for("admin_acesso"))
    if status_aluno not in {"Ativo", "Inativo"}:
        status_aluno = "Ativo"

    dup_email = conn.execute(
        "SELECT id FROM usuarios WHERE LOWER(email) = LOWER(?) AND (? IS NULL OR id <> ?)",
        (email, usuario_id, usuario_id),
    ).fetchone()
    if dup_email:
        flash("Já existe um usuário com este e-mail.", "error")
        return redirect(url_for("admin_acesso"))

    turma_label = _turma_label_by_id(conn, turma_id)
    defaults = _access_defaults_map(conn)

    try:
        if usuario_id:
            usuario = conn.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
            if not usuario:
                flash("Usuário não encontrado.", "error")
                return redirect(url_for("admin_acesso"))
            if senha:
                conn.execute(
                    "UPDATE usuarios SET nome = ?, email = ?, tipo = ?, nivel_acesso = ?, senha = ? WHERE id = ?",
                    (nome, email, user_type, nivel_acesso, hash_password(senha), usuario_id),
                )
            else:
                conn.execute(
                    "UPDATE usuarios SET nome = ?, email = ?, tipo = ?, nivel_acesso = ? WHERE id = ?",
                    (nome, email, user_type, nivel_acesso, usuario_id),
                )
        else:
            senha_final = senha or defaults.get(nivel_acesso, "admin123")
            cursor = conn.execute(
                "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?)",
                (nome, email, hash_password(senha_final), user_type, nivel_acesso),
            )
            usuario_id = cursor.lastrowid

        aluno_existente = conn.execute("SELECT id, turma_id FROM alunos WHERE usuario_id = ?", (usuario_id,)).fetchone()
        if user_type == "aluno":
            dup_matricula = conn.execute(
                "SELECT id FROM alunos WHERE matricula = ? AND usuario_id <> ?",
                (matricula, usuario_id),
            ).fetchone()
            if dup_matricula:
                conn.rollback()
                flash("Já existe um aluno com esta matrícula.", "error")
                return redirect(url_for("admin_acesso"))
            if aluno_existente:
                conn.execute(
                    """
                    UPDATE alunos
                       SET nome = ?, email = ?, matricula = ?, turma = ?, turma_id = ?, status = ?
                     WHERE usuario_id = ?
                    """,
                    (nome, email, matricula, turma_label or None, turma_id, status_aluno, usuario_id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO alunos (usuario_id, nome, matricula, email, turma, turma_id, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (usuario_id, nome, matricula, email, turma_label or None, turma_id, status_aluno),
                )
        elif aluno_existente:
            conn.execute(
                "UPDATE alunos SET nome = ?, email = ? WHERE usuario_id = ?",
                (nome, email, usuario_id),
            )

        if user_type == "aluno":
            resequence_turma_aluno_matriculas_for_ids(
                conn,
                aluno_existente["turma_id"] if aluno_existente else None,
                turma_id,
            )
        elif aluno_existente:
            resequence_turma_aluno_matriculas_for_ids(conn, aluno_existente["turma_id"])

        _persist_user_access_overrides(conn, usuario_id, nivel_acesso, access_overrides if user_type == "admin" else {})

        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        flash(f"Falha ao salvar acesso: {exc}", "error")
        return redirect(url_for("admin_acesso"))

    if usuario_id == session.get("user_id"):
        session["user_type"] = user_type
        session["access_level"] = nivel_acesso
        session["perfil"] = access_level_label(nivel_acesso)
        if user_type != "admin":
            session.clear()
            flash("Seu perfil foi alterado. Faça login novamente para continuar.", "success")
            return redirect(url_for("login"))

    flash("Acesso salvo com sucesso.", "success")
    return redirect(url_for("admin_acesso"))


@app.route("/admin/acesso/<int:usuario_id>/resetar-senha", methods=["POST"])
@admin_required
def admin_acesso_resetar_senha(usuario_id):
    conn = get_db_connection()
    ensure_usuario_access_schema(conn)
    usuario = conn.execute("SELECT id, nome, nivel_acesso FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    if not usuario:
        flash("Usuário não encontrado.", "error")
        return redirect(url_for("admin_acesso"))
    defaults = _access_defaults_map(conn)
    nivel = canonicalize_access_level(usuario["nivel_acesso"])
    nova_senha = defaults.get(nivel, "admin123")
    conn.execute("UPDATE usuarios SET senha = ? WHERE id = ?", (hash_password(nova_senha), usuario_id))
    conn.commit()
    flash(f"Senha de {usuario['nome']} resetada para o padrão do nível.", "success")
    return redirect(url_for("admin_acesso"))


@app.route("/admin/acesso/definir-senha", methods=["POST"])
@admin_required
def admin_acesso_definir_senha():
    usuario_ids = []
    for raw_value in request.form.getlist("usuario_ids"):
        if str(raw_value).strip().isdigit():
            usuario_ids.append(int(raw_value))
    usuario_ids = sorted(set(usuario_ids))
    nova_senha = (request.form.get("nova_senha") or "").strip()

    if not usuario_ids:
        if _is_ajax_request():
            return jsonify({"ok": False, "error": "missing-users"}), 400
        flash("Selecione ao menos um acesso para definir a nova senha.", "error")
        return redirect(url_for("admin_acesso"))

    if not nova_senha:
        if _is_ajax_request():
            return jsonify({"ok": False, "error": "missing-password"}), 400
        flash("Informe a nova senha.", "error")
        return redirect(url_for("admin_acesso"))

    conn = get_db_connection()
    placeholders = ", ".join("?" for _ in usuario_ids)
    rows = conn.execute(
        f"SELECT id, nome FROM usuarios WHERE id IN ({placeholders})",
        usuario_ids,
    ).fetchall()
    found_ids = {row["id"] for row in rows}
    missing_ids = [usuario_id for usuario_id in usuario_ids if usuario_id not in found_ids]
    if missing_ids:
        if _is_ajax_request():
            return jsonify({"ok": False, "error": "not-found", "missing_ids": missing_ids}), 404
        flash("Um ou mais acessos selecionados não foram encontrados.", "error")
        return redirect(url_for("admin_acesso"))

    conn.execute(
        f"UPDATE usuarios SET senha = ? WHERE id IN ({placeholders})",
        [hash_password(nova_senha), *usuario_ids],
    )
    conn.commit()

    if _is_ajax_request():
        return jsonify({"ok": True, "updated": len(usuario_ids)})

    flash("Nova senha aplicada com sucesso.", "success")
    return redirect(url_for("admin_acesso"))


@app.route("/admin/acesso/<int:usuario_id>/deletar", methods=["POST"])
@admin_required
def admin_acesso_deletar(usuario_id):
    if usuario_id == session.get("user_id"):
        flash("Você não pode excluir o próprio acesso.", "error")
        return redirect(url_for("admin_acesso"))

    conn = get_db_connection()
    ensure_usuario_profile_schema(conn)
    try:
        aluno = conn.execute("SELECT turma_id FROM alunos WHERE usuario_id = ?", (usuario_id,)).fetchone()
        conn.execute("DELETE FROM alunos WHERE usuario_id = ?", (usuario_id,))
        conn.execute("DELETE FROM usuarios WHERE id = ?", (usuario_id,))
        resequence_turma_aluno_matriculas_for_ids(conn, aluno["turma_id"] if aluno else None)
        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        flash(f"Não foi possível excluir o acesso: {exc}", "error")
        return redirect(url_for("admin_acesso"))
    flash("Acesso excluído com sucesso.", "success")
    return redirect(url_for("admin_acesso"))

# ===================== Uploads =====================

@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    """Serve arquivos do diretório de uploads com controle de acesso.

    Regras:
      - Sem sessão ativa -> redireciona para login.
            - Admin -> requer escopo `arquivos:view`.
      - Aluno -> só pode ler:
          * próprios uploads em `aluno_<aluno_id>/...`
          * próprio avatar em `avatars/usuario_<user_id>/...`
          * arquivos publicados em admin_arquivos com visivel = 1
          * arquivos referenciados em suas próprias requisições
      - Caso contrário -> 403.
    """
    # Normalização + path-traversal guard
    try:
        safe_rel = sanitize_student_document_relpath(filename)
    except ValueError:
        abort(403)

    user_id = session.get("user_id")
    user_type = session.get("user_type")
    if not user_id:
        # Sem sessão, redireciona em vez de 401 para fluxo natural via browser
        return redirect(url_for("login"))

    rel_norm = safe_rel.replace("\\", "/")
    is_student_document_relpath = rel_norm.startswith("aluno_")
    allowed = False
    if user_type == "admin":
        auth_context = _get_current_admin_access_context(force_reload=True)
        allowed = _admin_can("arquivos", "view", auth_context)
    elif user_type == "aluno":
        try:
            conn = get_db_connection()
            arow = conn.execute(
                "SELECT id FROM alunos WHERE usuario_id = ?", (user_id,)
            ).fetchone()
            aluno_id = arow["id"] if arow else None
            if aluno_id and (
                rel_norm.startswith(f"aluno_{aluno_id}/")
                or rel_norm.startswith(f"aluno_{aluno_id} - ")
            ):
                allowed = True
            elif rel_norm.startswith(f"avatars/usuario_{user_id}/"):
                allowed = True
            else:
                # Arquivos publicados pelo admin (visíveis ao aluno)
                row = conn.execute(
                    "SELECT 1 FROM admin_arquivos WHERE filename = ? AND visivel = 1",
                    (rel_norm,),
                ).fetchone()
                if row:
                    allowed = True
                elif aluno_id:
                    # Anexos vinculados a requisições do próprio aluno
                    row = conn.execute(
                        """
                        SELECT 1 FROM requisicao_arquivos ra
                          JOIN requisicoes r ON r.id = ra.requisicao_id
                         WHERE ra.filename = ? AND r.aluno_id = ?
                         LIMIT 1
                        """,
                        (rel_norm, aluno_id),
                    ).fetchone()
                    if not row:
                        # Comprovante legado armazenado direto em requisicoes
                        row = conn.execute(
                            "SELECT 1 FROM requisicoes WHERE arquivo_comprovante = ? AND aluno_id = ? LIMIT 1",
                            (rel_norm, aluno_id),
                        ).fetchone()
                    if row:
                        allowed = True
        except Exception:
            allowed = False

    if not allowed:
        abort(403)

    candidate_paths = []
    if is_student_document_relpath:
        docs_root = app.config.get("DOCUMENTOS_ALUNOS_FOLDER")
        if docs_root:
            try:
                candidate_paths.append(resolve_student_document_path(docs_root, rel_norm))
            except ValueError:
                abort(403)
    try:
        candidate_paths.append(resolve_student_document_path(app.config["UPLOAD_FOLDER"], rel_norm))
    except ValueError:
        abort(403)

    target_path = next((path for path in candidate_paths if os.path.isfile(path)), None)
    if not target_path:
        abort(404)

    rel_dir = os.path.dirname(target_path)
    rel_name = os.path.basename(target_path)
    resp = send_from_directory(
        rel_dir,
        rel_name,
        as_attachment=False,
    )
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    # Não cachear arquivos sensíveis em proxies/dispositivos compartilhados
    resp.headers["Cache-Control"] = "private, no-store"
    return resp

@app.route("/health")
def health():
    try:
        conn = get_db_connection()
        conn.execute("SELECT 1")
        return jsonify({"status": "ok"})
    except Exception:
        # Evita vazar detalhes internos (paths/driver) no payload público
        logger.exception("healthcheck falhou")
        return jsonify({"status": "error"}), 500

# ===================== Autenticação (legado mantido apenas para compat) =====================
# A view `login()` ativa vive em app/views/core.py. As funções a seguir são
# stubs delegadores mantidos para não quebrar referencias antigas em scripts.

_login_attempts: dict[str, list[float]] = {}


def _client_ip() -> str:
    from app.auth import _client_ip as _real
    return _real()


def _login_rate_limited(ip: str) -> tuple[bool, int]:
    from app.auth import _login_rate_limited as _real
    return _real(app, ip)


def _register_login_attempt(ip: str):
    from app.auth import _register_login_attempt as _real
    return _real(ip)


def login():
    from app.views import core as _core_views
    return _core_views.login()


def logout():
    from app.views import core as _core_views
    return _core_views.logout()


def index():
    from app.views import core as _core_views
    return _core_views.index()


def _rebind_legacy_core_exports():
    from app.views import core as core_views

    for view_name in ("index", "login", "logout"):
        globals()[view_name] = getattr(core_views, view_name)


def _rebind_legacy_aluno_exports():
    if not USE_ALUNO_BLUEPRINT:
        return

    from app.views import aluno as aluno_views

    for view_name in (
        "aluno_dashboard",
        "aluno_meus_dados",
        "aluno_nova_requisicao",
        "aluno_minhas_requisicoes",
        "aluno_requisicao_detalhe",
        "aluno_arquivos",
        "aluno_visualizar_arquivo",
        "aluno_baixar_arquivo",
    ):
        globals()[view_name] = getattr(aluno_views, view_name)


_rebind_legacy_core_exports()
_rebind_legacy_aluno_exports()

# ===================== Handlers / estáticos auxiliares =====================

@app.route("/favicon.ico")
def favicon():
    static_dir = os.path.join(app.root_path, "static")
    fav_path = os.path.join(static_dir, "favicon.ico")
    if os.path.exists(fav_path):
        return send_from_directory(static_dir, "favicon.ico")
    # evita quebrar se não existir
    return ("", 204)

@app.errorhandler(404)
def not_found(e):
    try:
        return render_template("404.html"), 404
    except Exception:
        # fallback simples caso o template 404.html não exista
        return ("<h1>404</h1><p>Página não encontrada.</p>", 404)

@app.errorhandler(500)
def internal_error(e):
    logger.exception("Erro interno do servidor")
    try:
        return (render_template("500.html"), 500)
    except Exception:
        return ("<h1>500</h1><p>Erro interno do servidor.</p>", 500)

@app.errorhandler(RequestEntityTooLarge)
def handle_large_upload(e):
    limit_bytes = request.max_content_length or app.config.get("MAX_CONTENT_LENGTH")
    flash(f"Arquivo muito grande. Tamanho máximo: {_format_bytes_label(limit_bytes)}.", "error")
    # tenta redirecionar de volta para a página anterior
    ref = request.headers.get('Referer') or url_for('index')
    return redirect(ref)

# ===================== Run =====================

if __name__ == "__main__":
    with app.app_context():
        init_db()
    debug_mode = (
        os.getenv("FLASK_DEBUG", "0").strip().lower() in {"1", "true", "yes", "on"}
        and not app.config.get("IS_PRODUCTION", False)
    )
    host = os.getenv("APP_HOST", "127.0.0.1")
    port = int(os.getenv("APP_PORT", "5000"))
    if app.config.get("IS_PRODUCTION", False):
        # Em produção use um servidor WSGI real (waitress / gunicorn).
        # Este atalho só é mantido por conveniência em desenvolvimento.
        logger.warning(
            "app.run() chamado em modo de produção. Recomenda-se waitress/gunicorn atrás de um proxy reverso."
        )
    app.run(debug=debug_mode, host=host, port=port)
