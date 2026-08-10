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
from app.presentation import _format_bytes_label, format_date_ptbr
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
# UT-6: app/requisitions.py passou a ser o dono canônico do alerta de
# atualização do aluno e das cores do alerta automático.  Os nomes seguem
# reexportados aqui apenas por compatibilidade (identidade preservada).
from app.requisitions import (
    AUTO_ALERT_YELLOW_BG,
    AUTO_ALERT_YELLOW_BORDER,
    auto_indefer_devolvidas,
    get_student_request_update_alert,
    mark_student_request_updates_seen,
)
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
# UT-6: app/web/urls.py é o dono canônico da resolução de URL do aluno; main
# apenas reexporta os nomes (identidade preservada).
from app.web.urls import USE_ALUNO_BLUEPRINT, aluno_url
# UT-3: hooks Flask cujos donos canônicos passaram a ser app/web/*.  São
# importados aqui apenas para registro no app composto e compatibilidade de
# re-export (identidade preservada; nenhum corpo é redefinido em main.py).
from app.web.authz_gate import (
    _admin_access_denied_response,
    _audit_missing_admin_authorization_configuration,
    enforce_admin_access_control,
)
from app.web.context import (
    inject_admin_access_helpers,
    inject_editable_message_templates,
)
from app.web.errors import (
    handle_large_upload,
    internal_error,
    not_found,
)
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
# UT-5: a orquestração de backup (sync de snapshot, retenção, upload para
# drives/servidor externo, configurações de runtime e resolução segura de
# manifesto) passou a ser propriedade canônica de app/backup.  Os nomes abaixo
# são re-exports por IDENTIDADE -- nunca wrappers:
#     main.<nome> is app.backup.orchestrator.<nome>
# O módulo `orchestrator` também é importado como objeto porque os pontos de
# composição das rotas resolvem a função no momento da chamada; é assim que um
# patch aplicado ao dono canônico intercepta de fato a rota manual de "Banco de
# Dados" em vez de esbarrar num alias obsoleto de main.
from app.backup import orchestrator as _backup_orchestrator
from app.backup import (
    _RETENTION_WINDOWS_META,
    _database_backup_locations,
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
)
# UT-5: contenção de caminho é de app/paths.py (mesmo objeto, comportamento
# inalterado); _best_effort_remove_admin_arquivo_file (UT-4) segue chamando
# exatamente esta função.
from app.paths import _path_within_root
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



# UT-8: o cohort "Banco de Dados" (46 simbolos: 20 rotas, 24 helpers e 2
# constantes) passou a ser propriedade canonica de app/views/admin/banco_dados.py.
# main apenas re-exporta os nomes por IDENTIDADE -- nunca wrappers.
from app.views.admin.banco_dados import (
    _RETENTION_INTERVAL_OPTIONS,
    _CLOUD_FOLDER_PROVIDERS,
    _normalize_backup_directory,
    save_backup_settings,
    save_retention_policy,
    _normalize_cloud_folder_provider,
    _save_cloud_drive_folder_setting,
    _get_cloud_drive_folder_setting,
    _extract_oauth_scopes,
    _set_active_cloud_account,
    _get_active_cloud_account,
    _require_cloud_token_encryption_ready,
    _update_cloud_account_token,
    _record_backup_log,
    _list_backup_logs,
    _format_drive_timestamp,
    _build_database_admin_context,
    _maybe_redirect_to_oauth_callback_host,
    _clear_legacy_oauth_session,
    _resolve_onedrive_redirect_uri,
    _resolve_google_redirect_uri,
    _onedrive_connect_diagnostics,
    _build_oauth_redirect_context,
    _get_cloud_folder_account,
    _get_current_schema_status_for_restore,
    _restore_database_from_source,
    admin_banco_dados,
    admin_backup_google_connect,
    google_callback,
    admin_backup_google_upload,
    admin_backup_onedrive_connect,
    onedrive_callback,
    admin_backup_onedrive_upload,
    admin_backup_cloud_folders,
    admin_backup_cloud_folder,
    admin_banco_dados_configuracoes,
    admin_banco_dados_retencao,
    admin_banco_dados_oauth_start,
    auth_callback,
    admin_banco_dados_oauth_disconnect,
    admin_banco_dados_drive_settings,
    admin_banco_dados_backup,
    admin_banco_dados_download,
    admin_banco_dados_excluir,
    admin_banco_dados_restaurar,
    admin_banco_dados_restaurar_upload,
)


# UT-9: o cohort "Acesso" (9 simbolos: 6 rotas e 3 helpers) passou a ser
# propriedade canonica de app/views/admin/acesso.py.  main apenas re-exporta os
# nomes por IDENTIDADE -- nunca wrappers.
from app.views.admin.acesso import (
    _parse_access_overrides_from_form,
    _persist_user_access_overrides,
    _turma_label_by_id,
    admin_acesso,
    admin_acesso_deletar,
    admin_acesso_definir_senha,
    admin_acesso_resetar_senha,
    admin_acesso_salvar,
    admin_acesso_salvar_senhas_default,
)


# UT-10: o cohort "Arquivos" (9 simbolos: 5 rotas e 4 helpers) passou a ser
# propriedade canonica de app/views/admin/arquivos.py.  main apenas re-exporta
# os nomes por IDENTIDADE -- nunca wrappers.
from app.views.admin.arquivos import (
    _best_effort_remove_admin_arquivo_file,
    _list_admin_arquivos_rows,
    _redirect_admin_arquivos_return,
    _save_admin_arquivo_payload,
    admin_adicionar_arquivo,
    admin_arquivos,
    admin_deletar_arquivo,
    admin_editar_arquivo,
    admin_visualizar_arquivo,
)


# UT-11: o cohort "Alertas" (8 simbolos: 4 rotas, 3 helpers e 1 constante)
# passou a ser propriedade canonica de app/views/admin/alertas.py.  main apenas
# re-exporta os nomes por IDENTIDADE -- nunca wrappers.
from app.views.admin.alertas import (
    ALERTA_COLOR_OPTIONS,
    _alerta_border_for,
    _derive_border_from_hex,
    _normalize_hex_color,
    admin_alertas,
    admin_alternar_alerta,
    admin_deletar_alerta,
    admin_salvar_alerta,
)


# UT-12: o cohort "Reportes" (5 simbolos: 3 rotas, 1 helper e 1 constante)
# passou a ser propriedade canonica de app/views/admin/reportes.py.  main
# apenas re-exporta os nomes por IDENTIDADE -- nunca wrappers.
from app.views.admin.reportes import (
    REPORTE_STATUS_OPTIONS,
    _reporte_status_badge_type,
    admin_reportes,
    admin_reportes_atualizar_status,
    admin_reportes_deletar,
)


# UT-13: o cohort "Dashboard" (10 simbolos: 1 rota e 9 helpers) passou a ser
# propriedade canonica de app/views/admin/dashboard.py.  main apenas
# re-exporta os nomes por IDENTIDADE -- nunca wrappers.
from app.views.admin.dashboard import (
    _admin_request_alert_kind,
    _build_admin_dashboard_turma_cards,
    _calculate_pending_response_metrics,
    _format_dashboard_average,
    _format_dashboard_days,
    _format_dashboard_hours,
    admin_dashboard,
    get_admin_new_request_alert,
    mark_admin_new_request_alert_seen,
    periodo_corrente,
)


# ===================== Auth helpers =====================


def admin_required(f):
    return _auth_admin_required(f)

def aluno_required(f):
    return _auth_aluno_required(f)

# ===================== Utils =====================


# ===================== Parsing helpers =====================









































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

logger = logging.getLogger("main")
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




app = create_app(register_aluno_blueprint=USE_ALUNO_BLUEPRINT)
app.add_template_global(resolve_user_message, name="user_message")

# UT-3: registro funcional explícito (sem decorator) dos hooks cujos donos
# canônicos agora são app/web/*.  O registro explícito mantém a ordem
# determinística exigida pelo contrato de arquitetura:
#   before_request     -> csrf_protect (flask_wtf, registrado em create_app)
#                         e só depois enforce_admin_access_control;
#   context_processor  -> inject_admin_access_helpers e depois
#                         inject_editable_message_templates;
#   error_handler      -> 404/500/413 (o handler de CSRFError continua sendo
#                         de app/__init__.py).
# after_request tem exatamente dois handlers, ambos fora de main (Compress e
# _apply_security_headers @ app): a UT-5 removeu o hook de backup pós-resposta
# sem alterar a ordem relativa de registro dos dois sobreviventes.
app.before_request(enforce_admin_access_control)
app.context_processor(inject_admin_access_helpers)
app.context_processor(inject_editable_message_templates)
app.register_error_handler(404, not_found)
app.register_error_handler(500, internal_error)
app.register_error_handler(RequestEntityTooLarge, handle_large_upload)


# Config via ambiente: `app.secret_key`, cookies de sessão, lifetime, flags
# CSRF, MAX_CONTENT_LENGTH, compressão, templates, DATABASE_PATH, diretórios
# de backup e EXTERNAL_BACKUP_* são todos aplicados centralmente em
# `app/__init__.py::create_app` (UT-2 unificou o composition root). Não
# redefina nada disso aqui.































































# UT-5: o hook transitório `_legacy_post_response_backup_sync` (@app.after_request)
# foi REMOVIDO daqui. O I/O de backup deixou de correr no ciclo de request:
# nenhuma requisição HTTP comum (inclusive GET /health) dispara orquestração de
# backup, e o hook não foi realocado para before_request/teardown_request/
# teardown_appcontext, thread, timer, atexit, signal ou worker. O ciclo
# automático canônico agora é app.backup.orchestrator.run_backup_cycle,
# acionado fora do request por `python -m app.backup.sync`. main não registra
# mais nenhum hook Flask (hooks_main == 0).

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





# ===================== Rotas Admin: Dashboard =====================





























































# Demo: clientes-form pack (visual)
@app.route("/admin/demo/clientes-form-pack")
@admin_required
def admin_demo_clientes_form_pack():
    return render_template("demo_clientes_form_pack.html")

# ===================== Rotas Admin: Cursos (NOVO) =====================








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
