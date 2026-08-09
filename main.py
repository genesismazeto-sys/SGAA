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


REPORTE_STATUS_OPTIONS = (
    "Novo",
    "Em análise",
    "Resolvido",
)































































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
        if not _path_within_root(file_path, upload_root):
            logger.warning(
                f"Remocao ignorada: caminho de arquivo admin '{rel_path}' resolvido para "
                f"'{file_path}' fora de UPLOAD_FOLDER '{upload_root}'"
            )
            return
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
