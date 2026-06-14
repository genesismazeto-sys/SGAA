# coding: utf-8
import os
import csv
import sqlite3
import json
import datetime
import time
import tempfile
import hashlib  # Substituindo bcrypt por hashlib
import base64   # Para codificação/decodificação de salt
import secrets  # Para geração segura de salt
import openpyxl
import logging
from logging.handlers import RotatingFileHandler
import traceback
import re
from datetime import date
from functools import wraps
from urllib.parse import urlsplit
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, send_file, jsonify, g, abort, make_response, current_app
import shutil
from urllib.parse import urlparse
from presets_api import bp_presets
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
from app.auth import (
    ACCESS_RESOURCE_GROUPS,
    ACCESS_RESOURCE_ORDER,
    ACCESS_RESOURCES_META,
    ACCESS_LEVEL_META,
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
import app.cloud_drives as _cd
from app.db_maintenance import (
    apply_retention_policy,
    apply_schema_migrations,
    create_database_snapshot,
    delete_database_snapshot,
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
from unidecode import unidecode
from werkzeug.exceptions import RequestEntityTooLarge
from utils.messages import (
    flash,
    frontend_message_templates,
    list_editable_messages,
    reset_message_override,
    resolve_user_message,
    save_message_override,
)



# ===================== Auth helpers =====================


def admin_required(f):
    return _auth_admin_required(f)

def aluno_required(f):
    return _auth_aluno_required(f)

# ===================== Utils =====================

def normalize_header(text):
    if not isinstance(text, str):
        text = str(text)
    text = unidecode(text)
    return " ".join(text.lower().split())

def ptbr_text_sort_key(text):
    normalized = " ".join(unidecode(str(text or "")).casefold().split())
    return (normalized == "", normalized)


def ptbr_sqlite_collation(a, b):
    """SQLite collation for accent-insensitive, case-insensitive PT-BR sorting."""
    a_norm = " ".join(unidecode(str(a or "")).casefold().split())
    b_norm = " ".join(unidecode(str(b or "")).casefold().split())
    if a_norm < b_norm:
        return -1
    if a_norm > b_norm:
        return 1
    return 0


def format_date_ptbr(value) -> str:
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%d/%m/%Y")
    raw = str(value).strip()
    if not raw:
        return ""
    base = raw.split(" ")[0].split("T")[0]
    try:
        return datetime.datetime.strptime(base, "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return raw

def resolve_existing_aluno_by_identifiers(conn, matricula, email):
    matricula = (matricula or "").strip()
    email = (email or "").strip()

    aluno_por_matricula = None
    aluno_por_email = None
    if matricula:
        aluno_por_matricula = conn.execute(
            "SELECT id, nome, matricula, email, usuario_id FROM alunos WHERE matricula = ?",
            (matricula,),
        ).fetchone()
    if email:
        aluno_por_email = conn.execute(
            "SELECT id, nome, matricula, email, usuario_id FROM alunos WHERE email = ?",
            (email,),
        ).fetchone()

    if aluno_por_matricula and aluno_por_email and aluno_por_matricula["id"] != aluno_por_email["id"]:
        raise ValueError("Conflito entre matrícula e e-mail: os dados informados pertencem a alunos diferentes.")

    return aluno_por_matricula or aluno_por_email
def build_turma_aluno_matricula(turma_codigo, ordem, total_alunos):
    codigo = str(turma_codigo or "").strip()
    if not codigo:
        raise ValueError("Turma sem código para gerar matrícula.")
    width = max(3, len(str(max(1, total_alunos))))
    return f"{codigo}.{ordem:0{width}d}"

def resequence_turma_aluno_matriculas(conn, turma_id):
    if not turma_id:
        return

    turma = conn.execute("SELECT codigo FROM turmas WHERE id = ?", (turma_id,)).fetchone()
    if not turma:
        return

    turma_codigo = str(turma["codigo"] or "").strip()
    if not turma_codigo:
        return

    alunos = conn.execute(
        "SELECT id, nome, email FROM alunos WHERE turma_id = ?",
        (turma_id,),
    ).fetchall()
    if not alunos:
        return

    alunos_ordenados = sorted(
        alunos,
        key=lambda row: (
            ptbr_text_sort_key(row["nome"]),
            ptbr_text_sort_key(row["email"]),
            row["id"],
        ),
    )

    temporarias = [
        (f"__TMP_RESEQ__{turma_id}__{row['id']}__{secrets.token_hex(4)}", row["id"])
        for row in alunos_ordenados
    ]
    conn.executemany("UPDATE alunos SET matricula = ? WHERE id = ?", temporarias)

    total_alunos = len(alunos_ordenados)
    finais = [
        (build_turma_aluno_matricula(turma_codigo, ordem, total_alunos), row["id"])
        for ordem, row in enumerate(alunos_ordenados, start=1)
    ]
    conn.executemany("UPDATE alunos SET matricula = ? WHERE id = ?", finais)

def resequence_turma_aluno_matriculas_for_ids(conn, *turma_ids):
    turma_ids_validos = []
    for turma_id in turma_ids:
        if turma_id in (None, ""):
            continue
        turma_id_int = int(turma_id)
        if turma_id_int not in turma_ids_validos:
            turma_ids_validos.append(turma_id_int)
    for turma_id in turma_ids_validos:
        resequence_turma_aluno_matriculas(conn, turma_id)

def hash_password(password: str) -> str:
    """Gera hash seguro de senha (PBKDF2-SHA256, 600k iterações).

    Mantemos compat com hashes legados (sha256+salt) na verificação; o login
    re-hashifica oportunisticamente para o novo formato.
    """
    from werkzeug.security import generate_password_hash
    return generate_password_hash(str(password or ""), method="pbkdf2:sha256:600000")


def is_legacy_password_hash(stored_password: str) -> bool:
    """Retorna True para hashes do formato antigo (base64$base64 SHA256)."""
    if not stored_password or not isinstance(stored_password, str):
        return False
    if stored_password.startswith("pbkdf2:") or stored_password.startswith("scrypt:") or stored_password.startswith("argon2"):
        return False
    parts = stored_password.split("$")
    return len(parts) == 2 and all(len(p) > 0 for p in parts)


def _check_password_legacy(stored_password: str, provided_password: str) -> bool:
    try:
        salt_b64, hash_b64 = stored_password.split("$")
        salt = base64.b64decode(salt_b64)
        h = hashlib.sha256()
        h.update(salt + provided_password.encode("utf-8"))
        calculated_hash = h.digest()
        stored_hash = base64.b64decode(hash_b64)
        return secrets.compare_digest(calculated_hash, stored_hash)
    except Exception:
        return False


def check_password(stored_password: str, provided_password: str) -> bool:
    """Compara senha aceitando tanto hashes novos (werkzeug) quanto legados."""
    if not stored_password:
        return False
    try:
        if is_legacy_password_hash(stored_password):
            return _check_password_legacy(stored_password, provided_password)
        from werkzeug.security import check_password_hash
        return check_password_hash(stored_password, provided_password or "")
    except Exception as exc:
        logging.error(f"Erro ao verificar senha: tipo={type(exc).__name__}")
        return False

# ===================== Parsing helpers =====================

def parse_documentos_json(raw) -> list[str]:
    """Robustly parse documentos list from various legacy formats.
    Accepts: JSON array (string), JSON-encoded string, Python-like list with single quotes,
    or plain delimited string (comma/semicolon/pipe/newline). Filters placeholders like NA.
    """
    bad = {"na", "n/a", "-", "_", "null", "none", "sem", "vazio"}
    def _normalize_list(arr):
        out = []
        seen = set()
        for x in (arr or []):
            s = str(x or "").strip().strip('"').strip("'")
            if not s:
                continue
            if s.lower() in bad:
                continue
            if s not in seen:
                seen.add(s); out.append(s)
        return out
    if raw is None:
        return []
    # Try JSON directly
    try:
        obj = json.loads(raw)
        if isinstance(obj, list):
            return _normalize_list(obj)
        if isinstance(obj, str):
            try:
                obj2 = json.loads(obj)
                if isinstance(obj2, list):
                    return _normalize_list(obj2)
            except Exception:
                s = obj
        else:
            s = str(obj)
    except Exception:
        s = str(raw)

    t = (s or "").strip()
    # Python-like list with single quotes
    if t.startswith('[') and t.endswith(']'):
        try:
            obj3 = json.loads(t.replace("'", '"'))
            if isinstance(obj3, list):
                return _normalize_list(obj3)
        except Exception:
            # strip brackets and continue to split
            t = t[1:-1]
    # strip surrounding quotes
    t = t.strip().strip('"').strip("'")
    if not t:
        return []
    import re as _re
    parts = _re.split(r"[,;\n\|]+", t)
    return _normalize_list(parts)

# ===================== Pagination helper =====================
def get_pagination(default_per_page: int = 20, max_per_page: int = 100):
    try:
        page = int(request.args.get('page', 1))
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = int(request.args.get('per_page', default_per_page))
    except (TypeError, ValueError):
        per_page = default_per_page
    page = max(1, page)
    per_page = max(1, min(max_per_page, per_page))
    offset = (page - 1) * per_page
    return page, per_page, offset

def wants_pagination() -> bool:
    """True se o cliente explicitou page/per_page via querystring.
    Mantém comportamento atual: só aplica LIMIT/OFFSET quando solicitado.
    """
    args = request.args
    return ('page' in args) or ('per_page' in args)

def append_conditions_sql(base_has_where: bool, conditions: list[str], joiner: str = " AND ") -> str:
    """Monta trecho SQL de condições a partir de uma lista de strings.
    - Se base_has_where=True, prefixa com " AND "; caso contrário, com " WHERE ".
    - Retorna string vazia quando não há condições.
    """
    if not conditions:
        return ""
    return (" AND " if base_has_where else " WHERE ") + joiner.join(conditions)


DEFAULT_CURSO_TOTAL_HORAS_AAC = 160
DEFAULT_CURSO_TOTAL_HORAS_AEU = 80
ATIVIDADES_SCHEMA_COLUMNS = (
    "id",
    "grupo",
    "nome",
    "descricao",
    "limite_horas",
    "tipo_atividade",
    "tem_limitacao",
    "tipo_limitacao",
    "limite_horas_total",
    "limite_horas_semestral",
)


def get_multi_query_values(name: str) -> list[str]:
    values = request.args.getlist(name)
    if not values and name in request.args:
        values = [request.args.get(name)]

    normalized = []
    seen = set()
    for value in values:
        if value is None:
            continue
        parts = [str(value)]
        if isinstance(value, str) and ("," in value or ";" in value):
            parts = re.split(r"\s*[,;]\s*", value)
        for part in parts:
            item = str(part or "").strip()
            if not item or item in seen:
                continue
            seen.add(item)
            normalized.append(item)
    return normalized


def get_text_query_value(name: str) -> str:
    return " ".join(str(request.args.get(name) or "").split())


def get_int_multi_query_values(name: str) -> list[int]:
    values = []
    for raw in get_multi_query_values(name):
        try:
            values.append(int(raw))
        except (TypeError, ValueError):
            continue
    return values


def get_number_range_query(name: str, caster=int):
    def _parse(raw):
        raw = str(raw or "").strip()
        if not raw:
            return None
        try:
            return caster(raw)
        except (TypeError, ValueError):
            return None

    return _parse(request.args.get(f"{name}_min")), _parse(request.args.get(f"{name}_max"))


def get_date_range_query(name: str):
    def _parse(raw):
        raw = str(raw or "").strip()
        if not raw:
            return None
        try:
            return datetime.datetime.strptime(raw[:10], "%Y-%m-%d").date().isoformat()
        except (TypeError, ValueError):
            return None

    return _parse(request.args.get(f"{name}_min")), _parse(request.args.get(f"{name}_max"))


def append_text_contains_condition(conditions: list[str], params: list, sql_expression: str, value: str) -> None:
    if not value:
        return
    conditions.append(f"LOWER(COALESCE({sql_expression}, '')) LIKE ?")
    params.append(f"%{value.lower()}%")


def ensure_usuario_access_schema(conn) -> None:
    cols = [row["name"] for row in conn.execute("PRAGMA table_info(usuarios)").fetchall()]
    if "nivel_acesso" not in cols:
        try:
            conn.execute("ALTER TABLE usuarios ADD COLUMN nivel_acesso TEXT NOT NULL DEFAULT 'administrativo'")
        except sqlite3.OperationalError:
            pass
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS configuracoes_acesso (
            nivel_acesso TEXT PRIMARY KEY,
            senha_padrao TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS usuarios_permissoes_acesso (
            usuario_id INTEGER NOT NULL,
            recurso TEXT NOT NULL,
            escopo TEXT NOT NULL,
            PRIMARY KEY (usuario_id, recurso),
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE ON UPDATE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_usuarios_permissoes_usuario ON usuarios_permissoes_acesso(usuario_id)"
    )
    for nivel_acesso, senha_padrao in {
        "admin_total": "admin123",
        "consultivo": "consultivo123",
        "administrativo": "admin123",
        "usuario": "aluno123",
        "usuario_teste": "teste123",
    }.items():
        # NOTA: senhas "padrão" históricas são gravadas SOMENTE na primeira inicialização.
        # Em ambientes onde não houver linha pré-existente, mantemos os valores acima
        # para preservar o fluxo administrativo. NUNCA reutilize esses valores em
        # produção; reescreva-os via interface após o primeiro login.
        conn.execute(
            "INSERT OR IGNORE INTO configuracoes_acesso (nivel_acesso, senha_padrao) VALUES (?, ?)",
            (nivel_acesso, senha_padrao),
        )
    conn.execute(
        "UPDATE usuarios SET nivel_acesso = ? WHERE tipo = 'admin' AND (nivel_acesso IS NULL OR TRIM(nivel_acesso) = '')",
        (default_access_level_for_user_type("admin"),),
    )
    conn.execute(
        "UPDATE usuarios SET nivel_acesso = ? WHERE tipo = 'aluno' AND (nivel_acesso IS NULL OR TRIM(nivel_acesso) = '')",
        (default_access_level_for_user_type("aluno"),),
    )
    conn.execute(
        "UPDATE usuarios SET nivel_acesso = ? WHERE tipo = 'aluno' AND LOWER(TRIM(COALESCE(nivel_acesso, ''))) = 'administrativo'",
        (default_access_level_for_user_type("aluno"),),
    )
    # NOTA: removido UPDATE incondicional que promovia
    # o e-mail "admin@ej.edu.br" a admin_total a cada execução.
    # A promoção por e-mail era um vetor de elevação de privilégios
    # (atacante criar conta com esse e-mail ? admin total).


DEFAULT_RESPONSE_GOAL_DAYS = 10
DEFAULT_RETURN_RESPONSE_DAYS = 7
DEFAULT_HORAS_ACADEMICA = 160
DEFAULT_HORAS_EXTENSAO = 160


def _app_settings_defaults() -> dict[str, str]:
    return {
        "response_goal_days": str(DEFAULT_RESPONSE_GOAL_DAYS),
        "response_metrics_reset_at": "",
        "return_response_days": str(DEFAULT_RETURN_RESPONSE_DAYS),
        "auto_indefer_devolvida": "0",
        "horas_padrao_academica": str(DEFAULT_HORAS_ACADEMICA),
        "horas_padrao_extensao": str(DEFAULT_HORAS_EXTENSAO),
    }


def _normalize_optional_iso_date(value: str, *, allow_empty: bool = False) -> str:
    raw = str(value or "").strip()
    if not raw:
        if allow_empty:
            return ""
        raise ValueError("Informe uma data válida.")
    try:
        parsed = datetime.datetime.strptime(raw[:10], "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("Informe uma data válida no formato AAAA-MM-DD.") from exc
    if parsed > date.today():
        raise ValueError("O início da apuração não pode estar no futuro.")
    return parsed.isoformat()


def ensure_app_settings_schema(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS configuracoes_app (
            chave TEXT PRIMARY KEY,
            valor TEXT NOT NULL,
            atualizado_em TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    defaults = _app_settings_defaults()
    for chave, valor in defaults.items():
        conn.execute(
            "INSERT OR IGNORE INTO configuracoes_app (chave, valor) VALUES (?, ?)",
            (chave, valor),
        )


def get_app_settings(conn) -> dict[str, str]:
    defaults = _app_settings_defaults()
    rows = conn.execute("SELECT chave, valor FROM configuracoes_app").fetchall()
    settings = dict(defaults)
    for row in rows:
        settings[str(row["chave"])] = str(row["valor"])
    return settings


def get_response_time_settings(conn) -> dict[str, object]:
    ensure_app_settings_schema(conn)
    settings = get_app_settings(conn)

    try:
        response_goal_days = max(0, int(str(settings.get("response_goal_days") or DEFAULT_RESPONSE_GOAL_DAYS).strip()))
    except ValueError:
        response_goal_days = DEFAULT_RESPONSE_GOAL_DAYS

    try:
        return_response_days = max(0, int(str(settings.get("return_response_days") or DEFAULT_RETURN_RESPONSE_DAYS).strip()))
    except ValueError:
        return_response_days = DEFAULT_RETURN_RESPONSE_DAYS

    response_metrics_reset_at = ""
    try:
        response_metrics_reset_at = _normalize_optional_iso_date(
            settings.get("response_metrics_reset_at") or "",
            allow_empty=True,
        )
    except ValueError:
        response_metrics_reset_at = ""

    auto_indefer = settings.get("auto_indefer_devolvida", "0") == "1"

    return {
        "response_goal_days": response_goal_days,
        "response_metrics_reset_at": response_metrics_reset_at,
        "response_metrics_reset_at_fmt": format_date_ptbr(response_metrics_reset_at) if response_metrics_reset_at else "",
        "return_response_days": return_response_days,
        "auto_indefer_devolvida": auto_indefer,
    }


def save_app_settings(conn, payload: dict[str, str]) -> dict[str, str]:
    ensure_app_settings_schema(conn)

    response_goal_days_raw = str(payload.get("response_goal_days") or DEFAULT_RESPONSE_GOAL_DAYS).strip()
    try:
        response_goal_days = max(0, int(response_goal_days_raw))
    except ValueError as exc:
        raise ValueError("A meta de tempo de resposta deve ser um número inteiro maior ou igual a zero.") from exc

    response_metrics_reset_at = _normalize_optional_iso_date(
        payload.get("response_metrics_reset_at") or "",
        allow_empty=True,
    )

    normalized = {
        "response_goal_days": str(response_goal_days),
        "response_metrics_reset_at": response_metrics_reset_at,
    }

    for chave, valor in normalized.items():
        conn.execute(
            """
            INSERT INTO configuracoes_app (chave, valor, atualizado_em)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor, atualizado_em = datetime('now')
            """,
            (chave, valor),
        )
    return normalized


def reset_response_time_metrics(conn, *, reset_at: str | None = None) -> dict[str, str]:
    settings = get_app_settings(conn)
    settings["response_metrics_reset_at"] = _normalize_optional_iso_date(reset_at or date.today().isoformat())
    return save_app_settings(conn, settings)


def save_return_response_settings(conn, payload: dict[str, str]) -> dict[str, str]:
    ensure_app_settings_schema(conn)

    raw = str(payload.get("return_response_days") or DEFAULT_RETURN_RESPONSE_DAYS).strip()
    try:
        days = max(0, int(raw))
    except ValueError as exc:
        raise ValueError("O prazo de adequação deve ser um número inteiro maior ou igual a zero.") from exc

    auto_indefer = "1" if payload.get("auto_indefer_devolvida") in ("1", "on", True) else "0"

    normalized = {
        "return_response_days": str(days),
        "auto_indefer_devolvida": auto_indefer,
    }
    for chave, valor in normalized.items():
        conn.execute(
            """
            INSERT INTO configuracoes_app (chave, valor, atualizado_em)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor, atualizado_em = datetime('now')
            """,
            (chave, valor),
        )
    return normalized


def get_horas_settings(conn) -> dict[str, int]:
    ensure_app_settings_schema(conn)
    settings = get_app_settings(conn)
    try:
        academica = max(0, int(str(settings.get("horas_padrao_academica") or DEFAULT_HORAS_ACADEMICA).strip()))
    except ValueError:
        academica = DEFAULT_HORAS_ACADEMICA
    try:
        extensao = max(0, int(str(settings.get("horas_padrao_extensao") or DEFAULT_HORAS_EXTENSAO).strip()))
    except ValueError:
        extensao = DEFAULT_HORAS_EXTENSAO
    return {"horas_padrao_academica": academica, "horas_padrao_extensao": extensao}


def save_horas_settings(conn, payload: dict[str, str]) -> dict[str, str]:
    ensure_app_settings_schema(conn)
    for key, default in (("horas_padrao_academica", DEFAULT_HORAS_ACADEMICA), ("horas_padrao_extensao", DEFAULT_HORAS_EXTENSAO)):
        raw = str(payload.get(key) or default).strip()
        try:
            value = max(0, int(raw))
        except ValueError as exc:
            raise ValueError(f"O valor de horas deve ser um número inteiro maior ou igual a zero.") from exc
        conn.execute(
            """
            INSERT INTO configuracoes_app (chave, valor, atualizado_em)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor, atualizado_em = datetime('now')
            """,
            (key, str(value)),
        )
    return {k: str(payload.get(k) or default) for k, default in (("horas_padrao_academica", DEFAULT_HORAS_ACADEMICA), ("horas_padrao_extensao", DEFAULT_HORAS_EXTENSAO))}


def auto_indefer_devolvidas(conn) -> int:
    """Indeferir automaticamente requisições Devolvidas cujo prazo de adequação expirou.

    Retorna o número de requisições alteradas.
    """
    settings = get_response_time_settings(conn)
    if not settings.get("auto_indefer_devolvida"):
        return 0
    days = int(settings.get("return_response_days") or DEFAULT_RETURN_RESPONSE_DAYS)
    if days <= 0:
        return 0

    result = conn.execute(
        """
        UPDATE requisicoes
           SET status = 'Indeferida',
               observacao = CASE
                   WHEN observacao IS NULL OR observacao = ''
                       THEN '[Indeferida automaticamente: prazo de adequação de ' || ? || ' dias expirado.]'
                   ELSE observacao || char(10) || '[Indeferida automaticamente: prazo de adequação de ' || ? || ' dias expirado.]'
               END
         WHERE status = 'Devolvida'
           AND data_processamento IS NOT NULL
           AND datetime(data_processamento) <= datetime('now', '-' || ? || ' days')
        """,
        (days, days, days),
    )
    count = result.rowcount
    if count:
        conn.commit()
    return count


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


def _backup_settings_defaults() -> dict[str, str]:
    return {
        "local_backup_dir": str(app.config.get("LOCAL_BACKUP_DIR") or ""),
        "cloud_backup_dir": str(app.config.get("CLOUD_BACKUP_DIR") or ""),
        "cloud_sync_interval_seconds": str(app.config.get("CLOUD_SYNC_INTERVAL_SECONDS") or 600),
        "external_backup_url": str(app.config.get("EXTERNAL_BACKUP_URL") or ""),
        "external_backup_token": str(app.config.get("EXTERNAL_BACKUP_TOKEN") or ""),
        "external_backup_enabled": "1" if app.config.get("EXTERNAL_BACKUP_ENABLED") else "0",
    }


def _apply_backup_settings_to_app(settings: dict[str, str]) -> None:
    app.config["LOCAL_BACKUP_DIR"] = settings.get("local_backup_dir") or app.config.get("LOCAL_BACKUP_DIR")
    app.config["CLOUD_BACKUP_DIR"] = settings.get("cloud_backup_dir") or ""
    try:
        app.config["CLOUD_SYNC_INTERVAL_SECONDS"] = max(0, int(settings.get("cloud_sync_interval_seconds") or 600))
    except (TypeError, ValueError):
        app.config["CLOUD_SYNC_INTERVAL_SECONDS"] = 600
    app.config["EXTERNAL_BACKUP_URL"] = settings.get("external_backup_url") or ""
    app.config["EXTERNAL_BACKUP_TOKEN"] = settings.get("external_backup_token") or ""
    app.config["EXTERNAL_BACKUP_ENABLED"] = str(settings.get("external_backup_enabled") or "0") in {"1", "true", "True"}


def ensure_backup_settings_schema(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS configuracoes_backup (
            chave TEXT PRIMARY KEY,
            valor TEXT NOT NULL,
            atualizado_em TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    defaults = _backup_settings_defaults()
    for chave, valor in defaults.items():
        conn.execute(
            "INSERT OR IGNORE INTO configuracoes_backup (chave, valor) VALUES (?, ?)",
            (chave, valor),
        )
    intervalo_atual = conn.execute(
        "SELECT valor FROM configuracoes_backup WHERE chave = 'cloud_sync_interval_seconds'"
    ).fetchone()
    if intervalo_atual and str(intervalo_atual["valor"] or "").strip() == "300":
        conn.execute(
            "UPDATE configuracoes_backup SET valor = ?, atualizado_em = datetime('now') WHERE chave = 'cloud_sync_interval_seconds'",
            (defaults["cloud_sync_interval_seconds"],),
        )
    _apply_backup_settings_to_app(get_backup_settings(conn))


def get_backup_settings(conn) -> dict[str, str]:
    defaults = _backup_settings_defaults()
    rows = conn.execute("SELECT chave, valor FROM configuracoes_backup").fetchall()
    settings = dict(defaults)
    for row in rows:
        settings[str(row["chave"])] = str(row["valor"])
    return settings


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


def ensure_cloud_backup_schema(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cloud_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT NOT NULL,
            account_email TEXT,
            token_json TEXT NOT NULL,
            connected_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT,
            active INTEGER DEFAULT 1
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS backup_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT,
            file_name TEXT,
            file_size INTEGER,
            status TEXT,
            error_message TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_cloud_accounts_provider_active ON cloud_accounts(provider, active, id DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_backup_logs_provider_created ON backup_logs(provider, created_at DESC, id DESC)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cloud_drive_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT NOT NULL UNIQUE,
            folder_id TEXT,
            folder_name TEXT,
            folder_path_label TEXT,
            drive_id TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
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


def create_usuario_with_default_access(conn, nome: str, email: str, senha_hash: str, user_type: str):
    from app.auth import default_access_level_for_user_type

    ensure_usuario_access_schema(conn)
    nivel_acesso = default_access_level_for_user_type(user_type)
    return conn.execute(
        "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?)",
        (nome, email, senha_hash, user_type, nivel_acesso),
    )


def normalize_usuario_access_for_user_type(conn, usuario_id: int | None):
    if not usuario_id:
        return
    ensure_usuario_access_schema(conn)
    usuario = conn.execute(
        "SELECT id, tipo, nivel_acesso FROM usuarios WHERE id = ?",
        (usuario_id,),
    ).fetchone()
    if not usuario:
        return
    if usuario["tipo"] == "aluno" and str(usuario["nivel_acesso"] or "").strip().lower() == "administrativo":
        conn.execute(
            "UPDATE usuarios SET nivel_acesso = ? WHERE id = ?",
            (default_access_level_for_user_type("aluno"), usuario_id),
        )


def _fetch_user_access_overrides(conn, usuario_id: int | None) -> dict[str, str]:
    if not usuario_id:
        return {}
    ensure_usuario_access_schema(conn)
    rows = conn.execute(
        "SELECT recurso, escopo FROM usuarios_permissoes_acesso WHERE usuario_id = ?",
        (usuario_id,),
    ).fetchall()
    overrides = {}
    for row in rows:
        recurso = str(row["recurso"] or "").strip().lower()
        if recurso not in ACCESS_RESOURCES_META:
            continue
        overrides[recurso] = normalize_permission_scope(row["escopo"], "none")
    return overrides


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


def _build_access_scope_groups_for_level(access_level: str, overrides: dict[str, str]) -> list[dict[str, object]]:
    defaults = merge_resource_scopes(access_level)
    effective_scopes = merge_resource_scopes(access_level, overrides)
    grouped = []
    for group in build_access_scope_groups(effective_scopes):
        items = []
        for item in group["items"]:
            recurso = item["resource"]
            default_scope = defaults.get(recurso, "none")
            override_scope = overrides.get(recurso)
            items.append(
                {
                    **item,
                    "default_scope": default_scope,
                    "default_scope_label": permission_scope_label(default_scope),
                    "override_scope": override_scope,
                    "override_scope_label": permission_scope_label(override_scope) if override_scope else None,
                }
            )
        grouped.append({"label": group["label"], "items": items})
    return grouped


def _load_admin_access_context(conn, usuario_id: int | None = None) -> dict[str, object]:
    if not usuario_id:
        return {
            "is_admin": False,
            "access_level": None,
            "access_level_label": None,
            "overrides": {},
            "effective_scopes": {},
            "scope_groups": [],
        }

    ensure_usuario_access_schema(conn)
    row = conn.execute(
        "SELECT id, tipo, nivel_acesso FROM usuarios WHERE id = ?",
        (usuario_id,),
    ).fetchone()
    if not row or (row["tipo"] or "").strip().lower() != "admin":
        return {
            "is_admin": False,
            "access_level": None,
            "access_level_label": None,
            "overrides": {},
            "effective_scopes": {},
            "scope_groups": [],
        }

    access_level = canonicalize_access_level(
        row["nivel_acesso"],
        default_access_level_for_user_type("admin"),
    )
    overrides = _fetch_user_access_overrides(conn, row["id"])
    effective_scopes = merge_resource_scopes(access_level, overrides)
    return {
        "is_admin": True,
        "access_level": access_level,
        "access_level_label": ACCESS_LEVEL_META.get(access_level, ACCESS_LEVEL_META["administrativo"])["label"],
        "overrides": overrides,
        "effective_scopes": effective_scopes,
        "scope_groups": _build_access_scope_groups_for_level(access_level, overrides),
    }


def _get_current_admin_access_context(force_reload: bool = False) -> dict[str, object]:
    if not force_reload and hasattr(g, "admin_access_context"):
        return g.admin_access_context
    if session.get("user_type") != "admin":
        g.admin_access_context = {
            "is_admin": False,
            "access_level": None,
            "access_level_label": None,
            "overrides": {},
            "effective_scopes": {},
            "scope_groups": [],
        }
        return g.admin_access_context
    g.admin_access_context = _load_admin_access_context(get_db_connection(), session.get("user_id"))
    return g.admin_access_context


def _admin_can(resource: str | None, scope: str = "view", context: dict[str, object] | None = None) -> bool:
    if not resource:
        return False
    auth_context = context or _get_current_admin_access_context()
    if not auth_context.get("is_admin"):
        return False
    effective = auth_context.get("effective_scopes", {})
    return permission_scope_satisfies(effective.get(resource, "none"), scope)


def ensure_usuario_profile_schema(conn) -> None:
    usuarios_cols = [row["name"] for row in conn.execute("PRAGMA table_info(usuarios)").fetchall()]
    if "foto_perfil" not in usuarios_cols:
        try:
            conn.execute("ALTER TABLE usuarios ADD COLUMN foto_perfil TEXT")
        except sqlite3.OperationalError:
            pass

    alunos_cols = [row["name"] for row in conn.execute("PRAGMA table_info(alunos)").fetchall()]
    if "foto_perfil" not in alunos_cols:
        try:
            conn.execute("ALTER TABLE alunos ADD COLUMN foto_perfil TEXT")
        except sqlite3.OperationalError:
            pass
    if "turma_id" not in alunos_cols:
        try:
            conn.execute("ALTER TABLE alunos ADD COLUMN turma_id INTEGER")
        except sqlite3.OperationalError:
            pass


def _parse_optional_processing_datetime(data_processamento):
    raw = str(data_processamento or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.datetime.strptime(raw[:19], fmt)
        except ValueError:
            continue
    try:
        return datetime.datetime.strptime(raw[:10], "%Y-%m-%d")
    except ValueError:
        return None


def can_student_edit_requisition(status, data_processamento):
    status_norm = str(status or "").strip()
    if status_norm == "Pendente":
        return True
    if status_norm != "Devolvida":
        return False
    processed_at = _parse_optional_processing_datetime(data_processamento)
    if not processed_at:
        return False
    return datetime.datetime.now() <= (processed_at + datetime.timedelta(days=14))


def can_student_delete_requisition(status, data_processamento):
    return can_student_edit_requisition(status, data_processamento)


def ensure_requisicao_alert_receipts_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS requisicao_alerta_receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            requisicao_id INTEGER NOT NULL,
            usuario_id INTEGER NOT NULL,
            alert_kind TEXT NOT NULL,
            seen_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (requisicao_id) REFERENCES requisicoes(id) ON DELETE CASCADE ON UPDATE CASCADE,
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE ON UPDATE CASCADE,
            UNIQUE(requisicao_id, usuario_id, alert_kind)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_req_alert_receipts_user_kind ON requisicao_alerta_receipts(usuario_id, alert_kind)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_req_alert_receipts_req ON requisicao_alerta_receipts(requisicao_id)"
    )


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


def ensure_atividades_schema_current(conn) -> None:
    cols = tuple(row["name"] for row in conn.execute("PRAGMA table_info(atividades)").fetchall())
    if not cols:
        return
    if cols == ATIVIDADES_SCHEMA_COLUMNS:
        return

    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS atividades__new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                grupo TEXT NOT NULL,
                nome TEXT NOT NULL UNIQUE,
                descricao TEXT,
                limite_horas INTEGER,
                tipo_atividade TEXT NOT NULL DEFAULT 'Acadêmica Complementar' CHECK(tipo_atividade IN ('Acadêmica Complementar', 'Extensão Universitária')),
                tem_limitacao BOOLEAN DEFAULT 0,
                tipo_limitacao TEXT CHECK(tipo_limitacao IN ('total', 'semestral')),
                limite_horas_total INTEGER,
                limite_horas_semestral INTEGER
            )
            """
        )
        conn.execute(
            """
            INSERT INTO atividades__new (
                id,
                grupo,
                nome,
                descricao,
                limite_horas,
                tipo_atividade,
                tem_limitacao,
                tipo_limitacao,
                limite_horas_total,
                limite_horas_semestral
            )
            SELECT
                id,
                grupo,
                nome,
                CASE
                    WHEN EXISTS(SELECT 1 FROM pragma_table_info('atividades') WHERE name = 'descricao') THEN descricao
                    ELSE NULL
                END,
                limite_horas,
                COALESCE(NULLIF(tipo_atividade, ''), 'Acadêmica Complementar'),
                COALESCE(tem_limitacao, 0),
                tipo_limitacao,
                limite_horas_total,
                limite_horas_semestral
            FROM atividades
            """
        )
        conn.execute("DROP TABLE atividades")
        conn.execute("ALTER TABLE atividades__new RENAME TO atividades")
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def ensure_matrizes_atividades_table(conn) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS matrizes_atividades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            curso_id INTEGER NOT NULL,
            nome TEXT NOT NULL,
            versao TEXT NOT NULL,
            descricao TEXT,
            status TEXT NOT NULL DEFAULT 'rascunho',
            data_inicio_vigencia TEXT,
            data_fim_vigencia TEXT,
            horas_aac_obrigatorias INTEGER NOT NULL DEFAULT {DEFAULT_CURSO_TOTAL_HORAS_AAC},
            horas_extensao_obrigatorias INTEGER NOT NULL DEFAULT {DEFAULT_CURSO_TOTAL_HORAS_AEU},
            matriz_origem_id INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(curso_id) REFERENCES cursos(id),
            FOREIGN KEY(matriz_origem_id) REFERENCES matrizes_atividades(id)
        )
        """
    )
    try:
        cols = [row["name"] for row in conn.execute("PRAGMA table_info(matrizes_atividades)").fetchall()]
        if "horas_aac_obrigatorias" not in cols:
            conn.execute(
                f"ALTER TABLE matrizes_atividades ADD COLUMN horas_aac_obrigatorias INTEGER NOT NULL DEFAULT {DEFAULT_CURSO_TOTAL_HORAS_AAC}"
            )
        if "horas_extensao_obrigatorias" not in cols:
            conn.execute(
                f"ALTER TABLE matrizes_atividades ADD COLUMN horas_extensao_obrigatorias INTEGER NOT NULL DEFAULT {DEFAULT_CURSO_TOTAL_HORAS_AEU}"
            )
        if "matriz_origem_id" not in cols:
            conn.execute("ALTER TABLE matrizes_atividades ADD COLUMN matriz_origem_id INTEGER")
        if "created_at" not in cols:
            conn.execute("ALTER TABLE matrizes_atividades ADD COLUMN created_at TEXT")
            conn.execute("UPDATE matrizes_atividades SET created_at = datetime('now') WHERE created_at IS NULL OR created_at = ''")
    except sqlite3.OperationalError:
        pass
    conn.execute(
        "UPDATE matrizes_atividades SET horas_aac_obrigatorias = ? WHERE horas_aac_obrigatorias IS NULL OR horas_aac_obrigatorias < 0",
        (DEFAULT_CURSO_TOTAL_HORAS_AAC,),
    )
    conn.execute(
        "UPDATE matrizes_atividades SET horas_extensao_obrigatorias = ? WHERE horas_extensao_obrigatorias IS NULL OR horas_extensao_obrigatorias < 0",
        (DEFAULT_CURSO_TOTAL_HORAS_AEU,),
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_matrizes_curso ON matrizes_atividades(curso_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_matrizes_status ON matrizes_atividades(status)")


def ensure_matriz_atividade_links_table(conn) -> None:
    ensure_matrizes_atividades_table(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS matrizes_atividades_itens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            matriz_id INTEGER NOT NULL,
            atividade_id INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(matriz_id) REFERENCES matrizes_atividades(id) ON DELETE CASCADE,
            FOREIGN KEY(atividade_id) REFERENCES atividades(id) ON DELETE CASCADE,
            UNIQUE(matriz_id, atividade_id)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_matriz_itens_matriz ON matrizes_atividades_itens(matriz_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_matriz_itens_atividade ON matrizes_atividades_itens(atividade_id)")


_VERSAO_NEW_DDL = """
        CREATE TABLE atividade_versao_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            atividade_base_id INTEGER NOT NULL,
            norma_id INTEGER NOT NULL,
            codigo_normativo TEXT NOT NULL,
            eixo TEXT NOT NULL CHECK(eixo IN ('AAC', 'AEU')),
            grupo TEXT,
            ch_por_evento REAL,
            limite_semestre REAL,
            limite_total REAL,
            observacao_aluno TEXT,
            observacao_admin TEXT,
            documentos_json TEXT,
            vigencia_inicio TEXT,
            vigencia_fim TEXT,
            numero_versao INTEGER NOT NULL DEFAULT 1 CHECK(numero_versao >= 1),
            status TEXT NOT NULL DEFAULT 'rascunho' CHECK(status IN ('rascunho', 'ativa', 'inativa', 'descontinuada', 'substituida')),
            versao_anterior_id INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(atividade_base_id) REFERENCES atividade_base(id) ON DELETE RESTRICT,
            FOREIGN KEY(norma_id) REFERENCES norma_atividade(id) ON DELETE RESTRICT,
            FOREIGN KEY(versao_anterior_id) REFERENCES atividade_versao_new(id) ON DELETE RESTRICT
        )"""


def _needs_atividade_versao_migration(conn) -> bool:
    """True if atividade_versao exists but still carries the old UNIQUE(base, norma) constraint."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='atividade_versao'"
    ).fetchone()
    if not row:
        return False
    schema_sql = row["sql"] or ""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(atividade_versao)").fetchall()}
    return "numero_versao" not in cols or "UNIQUE(atividade_base_id, norma_id)" in schema_sql


def _needs_atividade_versao_default_fix(conn) -> bool:
    """True if atividade_versao has numero_versao DEFAULT 0 instead of DEFAULT 1."""
    for row in conn.execute("PRAGMA table_info(atividade_versao)").fetchall():
        if row["name"] == "numero_versao":
            return row["dflt_value"] == "0"
    return False


def _needs_index_hardening(conn) -> bool:
    """True if idx_atividade_versao_base_num exists as a partial (WHERE) index."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_atividade_versao_base_num'"
    ).fetchone()
    if not row:
        return False
    return " WHERE " in (row["sql"] or "").upper()


def _recreate_atividade_versao(conn, *, copy_sql: str) -> None:
    """
    Core helper: drops+recreates atividade_versao using _VERSAO_NEW_DDL.
    copy_sql must be a SELECT that provides all columns including numero_versao.
    Drops atividade_transicao triggers before rename to avoid SQLite validation error.
    """
    conn.executescript(f"""
        PRAGMA foreign_keys = OFF;
        BEGIN;
        DROP TRIGGER IF EXISTS trg_atividade_transicao_aac_para_aeu_insert;
        DROP TRIGGER IF EXISTS trg_atividade_transicao_aac_para_aeu_update;
        {_VERSAO_NEW_DDL};
        INSERT INTO atividade_versao_new (
            id, atividade_base_id, norma_id, codigo_normativo, eixo, grupo,
            ch_por_evento, limite_semestre, limite_total, observacao_aluno, observacao_admin,
            documentos_json, vigencia_inicio, vigencia_fim,
            numero_versao, status, versao_anterior_id, created_at
        )
        {copy_sql};
        DROP TABLE atividade_versao;
        ALTER TABLE atividade_versao_new RENAME TO atividade_versao;
        DELETE FROM sqlite_sequence WHERE name = 'atividade_versao';
        INSERT INTO sqlite_sequence (name, seq)
            VALUES ('atividade_versao', (SELECT COALESCE(MAX(id), 0) FROM atividade_versao));
        COMMIT;
        PRAGMA foreign_keys = ON;
    """)


def _migrate_atividade_versao_to_numero_versao(conn) -> None:
    """Recreates atividade_versao with numero_versao assigned via ROW_NUMBER() per base."""
    _recreate_atividade_versao(
        conn,
        copy_sql="""
        SELECT
            id, atividade_base_id, norma_id, codigo_normativo, eixo, grupo,
            ch_por_evento, limite_semestre, limite_total, observacao_aluno, observacao_admin,
            documentos_json, vigencia_inicio, vigencia_fim,
            CAST(ROW_NUMBER() OVER (PARTITION BY atividade_base_id ORDER BY id ASC) AS INTEGER),
            status, versao_anterior_id, created_at
        FROM atividade_versao
        """,
    )


def _fix_atividade_versao_default(conn) -> None:
    """Recreates atividade_versao to change DEFAULT 0 → DEFAULT 1, preserving all data."""
    _recreate_atividade_versao(
        conn,
        copy_sql="""
        SELECT
            id, atividade_base_id, norma_id, codigo_normativo, eixo, grupo,
            ch_por_evento, limite_semestre, limite_total, observacao_aluno, observacao_admin,
            documentos_json, vigencia_inicio, vigencia_fim,
            numero_versao, status, versao_anterior_id, created_at
        FROM atividade_versao
        """,
    )


def ensure_atividade_versioning_schema(conn) -> None:
    """Garante schema aditivo para versionamento normativo de atividades.

    Importante: não altera fluxo operacional legado nesta fase.
    """
    if _needs_atividade_versao_migration(conn):
        _migrate_atividade_versao_to_numero_versao(conn)
    elif _needs_atividade_versao_default_fix(conn):
        _fix_atividade_versao_default(conn)
    if _needs_index_hardening(conn):
        conn.execute("DROP INDEX IF EXISTS idx_atividade_versao_base_num")

    ensure_matriz_atividade_links_table(conn)

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS atividade_base (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome_conceito TEXT NOT NULL UNIQUE,
            descricao TEXT,
            status TEXT NOT NULL DEFAULT 'ativo' CHECK(status IN ('ativo', 'inativo')),
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS norma_atividade (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT NOT NULL UNIQUE,
            eixo TEXT NOT NULL CHECK(eixo IN ('AAC', 'AEU')),
            revisao TEXT NOT NULL,
            nome TEXT,
            descricao TEXT,
            status TEXT NOT NULL DEFAULT 'ativa' CHECK(status IN ('ativa', 'inativa')),
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS atividade_versao (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            atividade_base_id INTEGER NOT NULL,
            norma_id INTEGER NOT NULL,
            codigo_normativo TEXT NOT NULL,
            eixo TEXT NOT NULL CHECK(eixo IN ('AAC', 'AEU')),
            grupo TEXT,
            ch_por_evento REAL,
            limite_semestre REAL,
            limite_total REAL,
            observacao_aluno TEXT,
            observacao_admin TEXT,
            documentos_json TEXT,
            vigencia_inicio TEXT,
            vigencia_fim TEXT,
            numero_versao INTEGER NOT NULL DEFAULT 1 CHECK(numero_versao >= 1),
            status TEXT NOT NULL DEFAULT 'rascunho' CHECK(status IN ('rascunho', 'ativa', 'inativa', 'descontinuada', 'substituida')),
            versao_anterior_id INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(atividade_base_id) REFERENCES atividade_base(id) ON DELETE RESTRICT,
            FOREIGN KEY(norma_id) REFERENCES norma_atividade(id) ON DELETE RESTRICT,
            FOREIGN KEY(versao_anterior_id) REFERENCES atividade_versao(id) ON DELETE RESTRICT
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS atividade_transicao (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_atividade_versao_id INTEGER,
            to_atividade_versao_id INTEGER,
            tipo_transicao TEXT NOT NULL CHECK(tipo_transicao IN ('mesmo_eixo', 'aac_para_aeu', 'nova_aeu', 'descontinuada', 'sem_transicao')),
            justificativa TEXT,
            observacao_admin TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(from_atividade_versao_id) REFERENCES atividade_versao(id) ON DELETE RESTRICT,
            FOREIGN KEY(to_atividade_versao_id) REFERENCES atividade_versao(id) ON DELETE RESTRICT,
            CHECK(from_atividade_versao_id IS NOT NULL OR to_atividade_versao_id IS NOT NULL),
            CHECK(from_atividade_versao_id IS NULL OR to_atividade_versao_id IS NULL OR from_atividade_versao_id <> to_atividade_versao_id)
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS matriz_norma (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            matriz_id INTEGER NOT NULL,
            norma_id INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(matriz_id) REFERENCES matrizes_atividades(id) ON DELETE CASCADE,
            FOREIGN KEY(norma_id) REFERENCES norma_atividade(id) ON DELETE RESTRICT,
            UNIQUE(matriz_id, norma_id)
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS matriz_atividade_versao_item (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            matriz_id INTEGER NOT NULL,
            atividade_versao_id INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(matriz_id) REFERENCES matrizes_atividades(id) ON DELETE CASCADE,
            FOREIGN KEY(atividade_versao_id) REFERENCES atividade_versao(id) ON DELETE RESTRICT,
            UNIQUE(matriz_id, atividade_versao_id)
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS atividade_legacy_map (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            atividade_id_legacy INTEGER NOT NULL UNIQUE,
            atividade_base_id INTEGER,
            status TEXT NOT NULL DEFAULT 'pendente' CHECK(status IN ('pendente', 'mapeada', 'revisar')),
            observacao_admin TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(atividade_id_legacy) REFERENCES atividades(id) ON DELETE RESTRICT,
            FOREIGN KEY(atividade_base_id) REFERENCES atividade_base(id) ON DELETE SET NULL
        )
        """
    )

    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_atividade_versao_eixo_norma_insert
        BEFORE INSERT ON atividade_versao
        FOR EACH ROW
        WHEN NEW.norma_id IS NOT NULL
             AND EXISTS(SELECT 1 FROM norma_atividade n WHERE n.id = NEW.norma_id AND n.eixo <> NEW.eixo)
        BEGIN
            SELECT RAISE(ABORT, 'atividade_versao.eixo incompatível com norma_atividade.eixo');
        END;
        """
    )

    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_atividade_versao_prev_same_eixo_insert
        BEFORE INSERT ON atividade_versao
        FOR EACH ROW
        WHEN NEW.versao_anterior_id IS NOT NULL
             AND EXISTS(
                 SELECT 1
                   FROM atividade_versao prev
                  WHERE prev.id = NEW.versao_anterior_id
                    AND prev.eixo <> NEW.eixo
             )
        BEGIN
            SELECT RAISE(ABORT, 'Mudança de eixo não pode ocorrer via versao_anterior_id; registre em atividade_transicao');
        END;
        """
    )

    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_atividade_versao_prev_same_eixo_update
        BEFORE UPDATE OF versao_anterior_id, eixo ON atividade_versao
        FOR EACH ROW
        WHEN NEW.versao_anterior_id IS NOT NULL
             AND EXISTS(
                 SELECT 1
                   FROM atividade_versao prev
                  WHERE prev.id = NEW.versao_anterior_id
                    AND prev.eixo <> NEW.eixo
             )
        BEGIN
            SELECT RAISE(ABORT, 'Mudança de eixo não pode ocorrer via versao_anterior_id; registre em atividade_transicao');
        END;
        """
    )

    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_atividade_versao_eixo_norma_update
        BEFORE UPDATE OF norma_id, eixo ON atividade_versao
        FOR EACH ROW
        WHEN NEW.norma_id IS NOT NULL
             AND EXISTS(SELECT 1 FROM norma_atividade n WHERE n.id = NEW.norma_id AND n.eixo <> NEW.eixo)
        BEGIN
            SELECT RAISE(ABORT, 'atividade_versao.eixo incompatível com norma_atividade.eixo');
        END;
        """
    )

    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_atividade_versao_num_pos_insert
        BEFORE INSERT ON atividade_versao
        FOR EACH ROW
        WHEN NEW.numero_versao <= 0
        BEGIN
            SELECT RAISE(ABORT, 'numero_versao deve ser >= 1');
        END;
        """
    )

    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_atividade_versao_num_pos_update
        BEFORE UPDATE OF numero_versao ON atividade_versao
        FOR EACH ROW
        WHEN NEW.numero_versao <= 0
        BEGIN
            SELECT RAISE(ABORT, 'numero_versao deve ser >= 1');
        END;
        """
    )

    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_atividade_transicao_aac_para_aeu_insert
        BEFORE INSERT ON atividade_transicao
        FOR EACH ROW
        WHEN NEW.tipo_transicao = 'aac_para_aeu'
        BEGIN
            SELECT CASE
                WHEN NEW.justificativa IS NULL OR TRIM(NEW.justificativa) = ''
                THEN RAISE(ABORT, 'Transição aac_para_aeu exige justificativa')
            END;
            SELECT CASE
                WHEN NEW.from_atividade_versao_id IS NULL OR NEW.to_atividade_versao_id IS NULL
                THEN RAISE(ABORT, 'Transição aac_para_aeu exige from/to atividade_versao')
            END;
            SELECT CASE
                WHEN (SELECT eixo FROM atividade_versao WHERE id = NEW.from_atividade_versao_id) <> 'AAC'
                     OR (SELECT eixo FROM atividade_versao WHERE id = NEW.to_atividade_versao_id) <> 'AEU'
                THEN RAISE(ABORT, 'Transição aac_para_aeu exige eixo AAC -> AEU')
            END;
        END;
        """
    )

    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_atividade_transicao_aac_para_aeu_update
        BEFORE UPDATE OF tipo_transicao, justificativa, from_atividade_versao_id, to_atividade_versao_id
        ON atividade_transicao
        FOR EACH ROW
        WHEN NEW.tipo_transicao = 'aac_para_aeu'
        BEGIN
            SELECT CASE
                WHEN NEW.justificativa IS NULL OR TRIM(NEW.justificativa) = ''
                THEN RAISE(ABORT, 'Transição aac_para_aeu exige justificativa')
            END;
            SELECT CASE
                WHEN NEW.from_atividade_versao_id IS NULL OR NEW.to_atividade_versao_id IS NULL
                THEN RAISE(ABORT, 'Transição aac_para_aeu exige from/to atividade_versao')
            END;
            SELECT CASE
                WHEN (SELECT eixo FROM atividade_versao WHERE id = NEW.from_atividade_versao_id) <> 'AAC'
                     OR (SELECT eixo FROM atividade_versao WHERE id = NEW.to_atividade_versao_id) <> 'AEU'
                THEN RAISE(ABORT, 'Transição aac_para_aeu exige eixo AAC -> AEU')
            END;
        END;
        """
    )

    try:
        req_cols = [row["name"] for row in conn.execute("PRAGMA table_info(requisicoes)").fetchall()]
        if "atividade_versao_id" not in req_cols:
            conn.execute("ALTER TABLE requisicoes ADD COLUMN atividade_versao_id INTEGER")
        if "regra_snapshot_json" not in req_cols:
            conn.execute("ALTER TABLE requisicoes ADD COLUMN regra_snapshot_json TEXT")
        if "codigo_normativo_snapshot" not in req_cols:
            conn.execute("ALTER TABLE requisicoes ADD COLUMN codigo_normativo_snapshot TEXT")
    except sqlite3.OperationalError:
        pass

    conn.execute("CREATE INDEX IF NOT EXISTS idx_norma_atividade_codigo ON norma_atividade(codigo)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_norma_atividade_eixo ON norma_atividade(eixo)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_atividade_versao_base ON atividade_versao(atividade_base_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_atividade_versao_norma ON atividade_versao(norma_id)")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_atividade_versao_base_num"
        " ON atividade_versao(atividade_base_id, numero_versao)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_atividade_versao_eixo ON atividade_versao(eixo)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_atividade_versao_status ON atividade_versao(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_atividade_transicao_from ON atividade_transicao(from_atividade_versao_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_atividade_transicao_to ON atividade_transicao(to_atividade_versao_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_atividade_transicao_tipo ON atividade_transicao(tipo_transicao)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_matriz_norma_matriz ON matriz_norma(matriz_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_matriz_norma_norma ON matriz_norma(norma_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_matriz_atividade_versao_item_matriz ON matriz_atividade_versao_item(matriz_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_matriz_atividade_versao_item_versao ON matriz_atividade_versao_item(atividade_versao_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_atividade_legacy_map_base ON atividade_legacy_map(atividade_base_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_requisicoes_atividade_versao_id ON requisicoes(atividade_versao_id)")


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

def get_atividade_base_list(conn) -> list:
    """
    Retorna todas as atividade_base com contagem de versões.
    Estritamente read-only — nenhum INSERT/UPDATE/DELETE.
    """
    return conn.execute(
        """
        SELECT
            ab.id,
            ab.nome_conceito,
            ab.descricao,
            ab.status,
            ab.created_at,
            COUNT(av.id)                                              AS total_versoes,
            SUM(CASE WHEN av.status = 'ativa' THEN 1 ELSE 0 END)     AS versoes_ativas
          FROM atividade_base ab
          LEFT JOIN atividade_versao av ON av.atividade_base_id = ab.id
         GROUP BY ab.id
         ORDER BY LOWER(ab.nome_conceito) ASC
        """
    ).fetchall()


def get_atividade_base(conn, base_id: int):
    """
    Retorna uma atividade_base pelo id, ou None.
    Estritamente read-only.
    """
    return conn.execute(
        "SELECT * FROM atividade_base WHERE id = ?",
        (base_id,),
    ).fetchone()


def get_versoes_por_base(conn, base_id: int) -> list:
    """
    Retorna as atividade_versao vinculadas a uma base, enriquecidas com dados da norma
    e contagem de uso em matrizes. Estritamente read-only.
    """
    return conn.execute(
        """
        SELECT
            av.id,
            av.atividade_base_id,
            av.norma_id,
            av.codigo_normativo,
            av.eixo,
            av.grupo,
            av.ch_por_evento,
            av.limite_semestre,
            av.limite_total,
            av.observacao_aluno,
            av.observacao_admin,
            av.vigencia_inicio,
            av.vigencia_fim,
            av.numero_versao,
            av.status,
            av.versao_anterior_id,
            av.created_at,
            n.codigo          AS norma_codigo,
            n.nome            AS norma_nome,
            n.revisao         AS norma_revisao,
            n.status          AS norma_status,
            COUNT(DISTINCT mavi.matriz_id) AS uso_em_matrizes
          FROM atividade_versao av
          JOIN norma_atividade n ON n.id = av.norma_id
          LEFT JOIN matriz_atividade_versao_item mavi ON mavi.atividade_versao_id = av.id
         WHERE av.atividade_base_id = ?
         GROUP BY av.id
         ORDER BY av.numero_versao DESC
        """,
        (base_id,),
    ).fetchall()


def get_norma_list(conn) -> list:
    """
    Retorna todas as norma_atividade com contagem de versões vinculadas.
    Estritamente read-only.
    """
    return conn.execute(
        """
        SELECT
            n.id,
            n.codigo,
            n.eixo,
            n.revisao,
            n.nome,
            n.descricao,
            n.status,
            n.created_at,
            COUNT(av.id)                                              AS total_versoes,
            SUM(CASE WHEN av.status = 'ativa' THEN 1 ELSE 0 END)     AS versoes_ativas
          FROM norma_atividade n
          LEFT JOIN atividade_versao av ON av.norma_id = n.id
         GROUP BY n.id
         ORDER BY n.eixo ASC, LOWER(n.codigo) ASC
        """
    ).fetchall()


def get_norma_by_id(conn, norma_id: int):
    """
    Retorna uma norma_atividade pelo id, ou None.
    Estritamente read-only.
    """
    return conn.execute(
        "SELECT * FROM norma_atividade WHERE id = ?",
        (norma_id,),
    ).fetchone()


def get_versoes_da_base_por_eixo(conn, base_id: int, eixo: str) -> list:
    """
    Retorna as atividade_versao da mesma base e eixo, ordenadas por created_at DESC.
    Estritamente read-only — usado para popular versao_anterior_id.
    """
    return conn.execute(
        """
        SELECT id, codigo_normativo, eixo, status, created_at
          FROM atividade_versao
         WHERE atividade_base_id = ? AND eixo = ?
         ORDER BY created_at DESC
        """,
        (base_id, eixo),
    ).fetchall()


def get_next_numero_versao(conn, base_id: int) -> int:
    """Retorna o próximo numero_versao para uma atividade_base (MAX positivo + 1)."""
    row = conn.execute(
        "SELECT COALESCE(MAX(numero_versao), 0) + 1 AS next_num"
        " FROM atividade_versao"
        " WHERE atividade_base_id = ? AND numero_versao > 0",
        (base_id,),
    ).fetchone()
    return row["next_num"] if row else 1


def get_ultima_versao_ativa_por_base(conn, base_id: int):
    """Retorna a versão ativa de maior numero_versao para uma atividade_base, ou None."""
    return conn.execute(
        """
        SELECT *
          FROM atividade_versao
         WHERE atividade_base_id = ? AND status = 'ativa'
         ORDER BY numero_versao DESC
         LIMIT 1
        """,
        (base_id,),
    ).fetchone()


def get_atividade_versao_by_id(conn, versao_id: int):
    """
    Retorna uma atividade_versao pelo id, ou None se não existir.
    Estritamente read-only — sem fallback ou inferência.
    """
    return conn.execute(
        "SELECT * FROM atividade_versao WHERE id = ?",
        (versao_id,),
    ).fetchone()


def get_atividade_versao_usage_counts(conn, versao_id: int) -> dict:
    """
    Retorna contagens de uso de uma atividade_versao em outras tabelas
    (matriz_atividade_versao_item, requisicoes, atividade_transicao).
    Estritamente read-only — usado para bloquear edição de versões em uso.
    """
    matriz_itens = conn.execute(
        "SELECT COUNT(*) FROM matriz_atividade_versao_item WHERE atividade_versao_id = ?",
        (versao_id,),
    ).fetchone()[0]
    requisicoes = conn.execute(
        "SELECT COUNT(*) FROM requisicoes WHERE atividade_versao_id = ?",
        (versao_id,),
    ).fetchone()[0]
    transicoes_origem = conn.execute(
        "SELECT COUNT(*) FROM atividade_transicao WHERE from_atividade_versao_id = ?",
        (versao_id,),
    ).fetchone()[0]
    transicoes_destino = conn.execute(
        "SELECT COUNT(*) FROM atividade_transicao WHERE to_atividade_versao_id = ?",
        (versao_id,),
    ).fetchone()[0]
    return {
        "matriz_atividade_versao_item": matriz_itens,
        "requisicoes": requisicoes,
        "atividade_transicao_origem": transicoes_origem,
        "atividade_transicao_destino": transicoes_destino,
        "total": matriz_itens + requisicoes + transicoes_origem + transicoes_destino,
    }


def get_atividade_transicoes_por_base(conn, base_id: int) -> list[dict]:
    """
    Lista o histórico administrativo de atividade_transicao relacionado a uma
    atividade_base, sem mutar dados.
    """
    rows = conn.execute(
        """
        SELECT t.id,
               t.tipo_transicao,
               t.justificativa,
               t.observacao_admin,
               t.created_at,
               src.id AS from_id,
               src.atividade_base_id AS from_base_id,
               src.codigo_normativo AS from_codigo_normativo,
               src.eixo AS from_eixo,
               dst.id AS to_id,
               dst.atividade_base_id AS to_base_id,
               dst.codigo_normativo AS to_codigo_normativo,
               dst.eixo AS to_eixo
          FROM atividade_transicao t
          LEFT JOIN atividade_versao src ON src.id = t.from_atividade_versao_id
          LEFT JOIN atividade_versao dst ON dst.id = t.to_atividade_versao_id
         WHERE src.atividade_base_id = ?
            OR dst.atividade_base_id = ?
         ORDER BY datetime(t.created_at) DESC, t.id DESC
        """,
        (base_id, base_id),
    ).fetchall()

    transicoes = []
    for row in rows:
        justificativa = (row["justificativa"] or "").strip()
        observacao_admin = (row["observacao_admin"] or "").strip()
        from_label = "-"
        if row["from_id"] is not None:
            from_label = row["from_codigo_normativo"] or f"Versão #{row['from_id']}"
        to_label = "-"
        if row["to_id"] is not None:
            to_label = row["to_codigo_normativo"] or f"Versão #{row['to_id']}"
        transicoes.append(
            {
                "id": row["id"],
                "versao_origem": from_label,
                "versao_destino": to_label,
                "tipo_transicao": row["tipo_transicao"],
                "motivo": justificativa or observacao_admin or "-",
                "created_at": row["created_at"] or "-",
                "eixo": row["from_eixo"] or row["to_eixo"] or "-",
            }
        )
    return transicoes


# ===================== Helpers: D7.2B4 - Vínculo Matriz → atividade_versao =====================

def get_bases_escopo_matriz(conn, matriz_id: int) -> list:
    """
    Retorna as atividade_base no escopo legado de uma matriz via
    matrizes_atividades_itens + atividade_legacy_map.
    Estritamente read-only — sem fallback ou inferência.
    """
    return conn.execute(
        """
        SELECT DISTINCT
            ab.id,
            ab.nome_conceito,
            ab.status
          FROM matrizes_atividades_itens mai
          JOIN atividade_legacy_map alm ON alm.atividade_id_legacy = mai.atividade_id
          JOIN atividade_base ab ON ab.id = alm.atividade_base_id
         WHERE mai.matriz_id = ?
         ORDER BY LOWER(ab.nome_conceito) ASC
        """,
        (matriz_id,),
    ).fetchall()


def get_versoes_ativas_por_base_na_matriz(conn, matriz_id: int, base_id: int) -> list:
    """
    Retorna versões ativas de uma atividade_base cuja norma está vinculada
    à matriz em matriz_norma. Apenas status 'ativa'.
    Estritamente read-only — sem fallback, sem inferência, sem primeira ativa.
    """
    return conn.execute(
        """
        SELECT
            av.id,
            av.codigo_normativo,
            av.eixo,
            av.status,
            n.id      AS norma_id,
            n.codigo  AS norma_codigo
          FROM atividade_versao av
          JOIN norma_atividade n ON n.id = av.norma_id
          JOIN matriz_norma mn ON mn.norma_id = n.id AND mn.matriz_id = ?
         WHERE av.atividade_base_id = ?
           AND av.status = 'ativa'
         ORDER BY av.id
        """,
        (matriz_id, base_id),
    ).fetchall()


def get_vinculo_versao_da_matriz(conn, matriz_id: int, base_id: int):
    """
    Retorna o vínculo atual (matriz_atividade_versao_item) para uma matriz+base.
    Deve existir no máximo um por matriz+base (invariante garantido pelo set).
    Retorna None se não houver vínculo.
    Estritamente read-only.
    """
    return conn.execute(
        """
        SELECT
            mavi.id                AS item_id,
            mavi.atividade_versao_id,
            av.codigo_normativo,
            av.numero_versao,
            av.eixo,
            av.status              AS versao_status,
            av.atividade_base_id
          FROM matriz_atividade_versao_item mavi
          JOIN atividade_versao av ON av.id = mavi.atividade_versao_id
         WHERE mavi.matriz_id = ?
           AND av.atividade_base_id = ?
         LIMIT 1
        """,
        (matriz_id, base_id),
    ).fetchone()


def _set_versao_da_matriz_para_base(conn, matriz_id: int, base_id: int, versao_id: int) -> None:
    """
    Define (substitui) o vínculo matriz→atividade_versao para uma atividade_base.
    Operação "set": remove qualquer vínculo anterior da mesma matriz+base antes de inserir.
    Garante no máximo um vínculo por matriz+base — nunca cria ambiguidade.
    Não commita — responsabilidade do chamador.
    """
    conn.execute(
        """
        DELETE FROM matriz_atividade_versao_item
         WHERE matriz_id = ?
           AND atividade_versao_id IN (
               SELECT id FROM atividade_versao WHERE atividade_base_id = ?
           )
        """,
        (matriz_id, base_id),
    )
    conn.execute(
        "INSERT INTO matriz_atividade_versao_item (matriz_id, atividade_versao_id) VALUES (?, ?)",
        (matriz_id, versao_id),
    )


def _remover_versao_da_matriz_para_base(conn, matriz_id: int, base_id: int) -> int:
    """
    Remove o vínculo matriz→atividade_versao para uma atividade_base.
    Retorna o número de linhas apagadas (0 ou 1).
    Não commita — responsabilidade do chamador.
    """
    cur = conn.execute(
        """
        DELETE FROM matriz_atividade_versao_item
         WHERE matriz_id = ?
           AND atividade_versao_id IN (
               SELECT id FROM atividade_versao WHERE atividade_base_id = ?
           )
        """,
        (matriz_id, base_id),
    )
    return cur.rowcount


def get_card_version_menu_data(conn, matriz_id: int, activity_ids: list) -> dict:
    """
    Para cada atividade legada vinculada à matriz, retorna a versão atual vinculada
    e todas as versões disponíveis da mesma base (para escolha/relink).
    Retorna dict str(legacy_id) → {base_id, versao_id, numero_versao, eixo, versoes}.
    Atividades sem mapa de legado ou sem vínculo de versão na matriz não são incluídas.
    Estritamente read-only.
    """
    if not activity_ids:
        return {}
    placeholders = ", ".join("?" for _ in activity_ids)
    rows = conn.execute(
        f"""
        SELECT
            mai.atividade_id      AS legacy_id,
            alm.atividade_base_id AS base_id,
            av.id                 AS versao_id,
            av.numero_versao,
            av.eixo
          FROM matrizes_atividades_itens mai
          JOIN atividade_legacy_map alm ON alm.atividade_id_legacy = mai.atividade_id
          JOIN atividade_versao av ON av.atividade_base_id = alm.atividade_base_id
          JOIN matriz_atividade_versao_item mavi
            ON mavi.matriz_id = mai.matriz_id
           AND mavi.atividade_versao_id = av.id
         WHERE mai.matriz_id = ?
           AND mai.atividade_id IN ({placeholders})
        """,
        [matriz_id] + list(activity_ids),
    ).fetchall()

    result = {}
    for row in rows:
        current_versao_id = row["versao_id"]
        versoes_rows = conn.execute(
            """
            SELECT id, numero_versao, status, codigo_normativo
              FROM atividade_versao
             WHERE atividade_base_id = ?
             ORDER BY numero_versao DESC
            """,
            (row["base_id"],),
        ).fetchall()
        versoes = [
            {
                "id": v["id"],
                "numero_versao": v["numero_versao"],
                "status": v["status"],
                "codigo_normativo": v["codigo_normativo"] or "",
                "is_current": v["id"] == current_versao_id,
            }
            for v in versoes_rows
        ]
        result[str(row["legacy_id"])] = {
            "base_id": row["base_id"],
            "versao_id": current_versao_id,
            "numero_versao": row["numero_versao"],
            "eixo": row["eixo"],
            "versoes": versoes,
        }
    return result


def get_legacy_map_list(conn) -> list:
    """
    Retorna as atividades legadas com seus dados de mapeamento
    (LEFT JOIN em atividade_legacy_map) e contagem de requisições existentes.
    Estritamente read-only — não cria nenhuma entrada em atividade_legacy_map.
    """
    return conn.execute(
        """
        SELECT
            a.id                     AS atividade_id,
            a.nome                   AS atividade_nome,
            a.tipo_atividade,
            a.grupo,
            alm.id                   AS mapa_id,
            alm.status               AS mapa_status,
            alm.atividade_base_id    AS base_id,
            ab.nome_conceito         AS base_nome,
            alm.observacao_admin,
            alm.created_at           AS mapa_criado_em,
            COUNT(r.id)              AS qtd_requisicoes
          FROM atividades a
          LEFT JOIN atividade_legacy_map alm ON alm.atividade_id_legacy = a.id
          LEFT JOIN atividade_base ab ON ab.id = alm.atividade_base_id
          LEFT JOIN requisicoes r ON r.atividade_id = a.id
         GROUP BY a.id
         ORDER BY
            CASE COALESCE(alm.status, 'sem_mapa')
                WHEN 'pendente'   THEN 0
                WHEN 'revisar'    THEN 1
                WHEN 'sem_mapa'   THEN 2
                WHEN 'mapeada'    THEN 3
                ELSE 4
            END ASC,
            LOWER(a.nome) ASC
        """
    ).fetchall()


def get_preferred_matriz_for_curso(conn, curso_id: int | None):
    if not curso_id:
        return None
    ensure_matrizes_atividades_table(conn)
    return conn.execute(
        """
        SELECT *
          FROM matrizes_atividades
         WHERE curso_id = ?
      ORDER BY CASE LOWER(COALESCE(status, ''))
                   WHEN 'ativa' THEN 0
                   WHEN 'vigente' THEN 0
                   WHEN 'rascunho' THEN 1
                   ELSE 2
               END,
               COALESCE(data_inicio_vigencia, '') DESC,
               id DESC
         LIMIT 1
        """,
        (curso_id,),
    ).fetchone()


def get_effective_matriz_for_turma(conn, curso_id: int | None, turma_matriz_id: int | None):
    ensure_matrizes_atividades_table(conn)
    if turma_matriz_id:
        row = conn.execute("SELECT * FROM matrizes_atividades WHERE id = ?", (turma_matriz_id,)).fetchone()
        if row:
            return row
    return get_preferred_matriz_for_curso(conn, curso_id)


def ensure_turmas_matriz_schema(conn) -> None:
    ensure_matrizes_atividades_table(conn)
    try:
        cols_t = [row["name"] for row in conn.execute("PRAGMA table_info(turmas)").fetchall()]
        if "matriz_id" not in cols_t:
            conn.execute("ALTER TABLE turmas ADD COLUMN matriz_id INTEGER")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_turmas_matriz_id ON turmas(matriz_id)")
    except sqlite3.OperationalError:
        pass


def _matriz_option_label(row) -> str:
    parts = [str(row["nome"] or "Matriz sem nome").strip()]
    if row["versao"]:
        parts.append(str(row["versao"]).strip())
    if row["status"]:
        parts.append(_matriz_status_label(row["status"]))
    return " | ".join(part for part in parts if part)


def _matrizes_by_curso(conn) -> dict[str, list[dict[str, object]]]:
    ensure_matrizes_atividades_table(conn)
    rows = conn.execute(
        """
        SELECT id, curso_id, nome, versao, status, data_inicio_vigencia
          FROM matrizes_atividades
         WHERE curso_id IS NOT NULL
      ORDER BY curso_id,
               CASE LOWER(COALESCE(status, ''))
                   WHEN 'ativa' THEN 0
                   WHEN 'vigente' THEN 0
                   WHEN 'rascunho' THEN 1
                   ELSE 2
               END,
               COALESCE(data_inicio_vigencia, '') DESC,
               id DESC
        """
    ).fetchall()
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        grouped.setdefault(str(row["curso_id"]), []).append(
            {"id": row["id"], "label": _matriz_option_label(row)}
        )
    return grouped


def _resolve_turma_matriz_id(conn, curso_id: int | None, posted_matriz_id: int | None):
    preferred = get_preferred_matriz_for_curso(conn, curso_id)
    matriz_id = posted_matriz_id or (preferred["id"] if preferred else None)
    if not matriz_id:
        return None, "Selecione uma matriz para a turma."
    matriz = conn.execute(
        "SELECT * FROM matrizes_atividades WHERE id = ? AND curso_id = ?",
        (matriz_id, curso_id),
    ).fetchone()
    if not matriz:
        return None, "A matriz selecionada não pertence ao curso informado."
    return matriz["id"], None


def _periodo_label_for_turma_row(turma) -> str:
    inicio = None
    fim = None
    if turma["semestre_inicio"] and turma["ano_inicio"]:
        inicio = f"{turma['semestre_inicio']}S-{turma['ano_inicio']}"
    if turma["semestre_fim"] and turma["ano_fim"]:
        fim = f"{turma['semestre_fim']}S-{turma['ano_fim']}"
    if inicio and fim:
        return f"{inicio} a {fim}"
    if inicio:
        return inicio
    if fim:
        return fim
    return "-"


def _turma_effective_matriz_label(conn, turma) -> str:
    matriz = get_effective_matriz_for_turma(conn, turma["curso_id"], turma["matriz_id"])
    return _matriz_option_label(matriz) if matriz else "-"


def is_activity_allowed_for_turma_matrix(
    conn,
    atividade_id: int | None,
    curso_id: int | None,
    turma_matriz_id: int | None,
) -> bool:
    if not atividade_id:
        return False
    ensure_matriz_atividade_links_table(conn)
    matriz = get_effective_matriz_for_turma(conn, curso_id, turma_matriz_id)
    if not matriz:
        return True
    row = conn.execute(
        "SELECT 1 FROM matrizes_atividades_itens WHERE matriz_id = ? AND atividade_id = ?",
        (matriz["id"], atividade_id),
    ).fetchone()
    return row is not None


def get_allowed_activity_ids_for_turma_matrix(
    conn,
    curso_id: int | None,
    turma_matriz_id: int | None,
):
    ensure_matriz_atividade_links_table(conn)
    matriz = get_effective_matriz_for_turma(conn, curso_id, turma_matriz_id)
    if not matriz:
        return None, None
    activity_ids = {
        row["atividade_id"]
        for row in conn.execute(
            "SELECT atividade_id FROM matrizes_atividades_itens WHERE matriz_id = ?",
            (matriz["id"],),
        ).fetchall()
    }
    return activity_ids, matriz


def _require_versioning_read_model(conn) -> None:
    required_tables = (
        "atividade_base",
        "norma_atividade",
        "atividade_versao",
        "matriz_norma",
        "matriz_atividade_versao_item",
        "atividade_legacy_map",
        "matrizes_atividades",
        "turmas",
    )
    existing_tables = {
        row["name"]
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
    missing = [name for name in required_tables if name not in existing_tables]
    if missing:
        raise RuntimeError(
            "Schema de versionamento indisponível para leitura diagnóstica: faltam as tabelas "
            + ", ".join(missing)
            + "."
        )


def _get_preferred_matriz_for_curso_readonly(conn, curso_id: int | None):
    if not curso_id:
        return None
    return conn.execute(
        """
        SELECT *
          FROM matrizes_atividades
         WHERE curso_id = ?
      ORDER BY CASE LOWER(COALESCE(status, ''))
                   WHEN 'ativa' THEN 0
                   WHEN 'vigente' THEN 0
                   WHEN 'rascunho' THEN 1
                   ELSE 2
               END,
               COALESCE(data_inicio_vigencia, '') DESC,
               id DESC
         LIMIT 1
        """,
        (curso_id,),
    ).fetchone()


def _get_effective_matriz_for_turma_readonly(conn, curso_id: int | None, turma_matriz_id: int | None):
    if turma_matriz_id:
        row = conn.execute(
            "SELECT * FROM matrizes_atividades WHERE id = ?",
            (turma_matriz_id,),
        ).fetchone()
        if row:
            return row
    return _get_preferred_matriz_for_curso_readonly(conn, curso_id)


def _serialize_versioned_activity_row(row) -> dict[str, object]:
    return {
        "eixo": row["eixo"],
        "norma": row["norma_codigo"],
        "atividade_base": {
            "id": row["atividade_base_id"],
            "nome": row["atividade_base_nome"],
        },
        "atividade_versao_id": row["atividade_versao_id"],
        "nome_exibivel": row["nome_exibivel"],
        "grupo": row["grupo"],
        "ch_por_evento": row["ch_por_evento"],
        "limite_semestre": row["limite_semestre"],
        "limite_total": row["limite_total"],
        "observacao_aluno": row["observacao_aluno"],
        "observacao_admin": row["observacao_admin"],
        "status": row["status"],
        "tem_correspondente_legado": bool(row["tem_correspondente_legado"]),
        "atividade_id_legacy": row["atividade_id_legacy"],
        "nome_legacy": row["nome_legacy"],
        "tipo_atividade_legacy": row["tipo_atividade_legacy"],
    }


def listar_atividades_versionadas_por_matriz(conn, matriz_id: int) -> dict[str, object]:
    _require_versioning_read_model(conn)

    matriz = conn.execute(
        """
        SELECT m.*,
               c.nome AS curso_nome,
               c.codigo AS curso_codigo
          FROM matrizes_atividades m
          LEFT JOIN cursos c ON c.id = m.curso_id
         WHERE m.id = ?
        """,
        (matriz_id,),
    ).fetchone()
    if not matriz:
        raise LookupError("Matriz não encontrada para leitura diagnóstica.")

    turmas_vinculadas = [
        {
            "id": row["id"],
            "codigo": row["codigo"],
            "nome": row["nome"],
            "periodo_label": _periodo_label_for_turma_row(row),
        }
        for row in conn.execute(
            """
            SELECT id, codigo, nome, ano_inicio, semestre_inicio, ano_fim, semestre_fim
              FROM turmas
             WHERE matriz_id = ?
          ORDER BY COALESCE(codigo, nome, '')
            """,
            (matriz_id,),
        ).fetchall()
    ]

    normas = [
        {
            "id": row["id"],
            "codigo": row["codigo"],
            "eixo": row["eixo"],
            "revisao": row["revisao"],
            "nome": row["nome"],
        }
        for row in conn.execute(
            """
            SELECT n.id, n.codigo, n.eixo, n.revisao, n.nome
              FROM matriz_norma mn
              JOIN norma_atividade n ON n.id = mn.norma_id
             WHERE mn.matriz_id = ?
          ORDER BY n.eixo, n.codigo
            """,
            (matriz_id,),
        ).fetchall()
    ]

    versioned_rows = conn.execute(
        """
        SELECT av.id AS atividade_versao_id,
               av.atividade_base_id,
               ab.nome_conceito AS atividade_base_nome,
               COALESCE(
                   (
                       SELECT a.nome
                         FROM atividade_legacy_map alm
                         JOIN atividades a ON a.id = alm.atividade_id_legacy
                        WHERE alm.atividade_base_id = av.atividade_base_id
                     ORDER BY alm.atividade_id_legacy
                        LIMIT 1
                   ),
                   ab.nome_conceito
               ) AS nome_exibivel,
               av.grupo,
               av.ch_por_evento,
               av.limite_semestre,
               av.limite_total,
               av.observacao_aluno,
               av.observacao_admin,
               av.status,
               av.eixo,
               n.codigo AS norma_codigo,
               EXISTS(
                   SELECT 1
                     FROM atividade_legacy_map alm
                    WHERE alm.atividade_base_id = av.atividade_base_id
               ) AS tem_correspondente_legado,
               (
                   SELECT alm.atividade_id_legacy
                     FROM atividade_legacy_map alm
                    WHERE alm.atividade_base_id = av.atividade_base_id
                 ORDER BY alm.atividade_id_legacy
                    LIMIT 1
               ) AS atividade_id_legacy,
               (
                   SELECT a.nome
                     FROM atividade_legacy_map alm
                     JOIN atividades a ON a.id = alm.atividade_id_legacy
                    WHERE alm.atividade_base_id = av.atividade_base_id
                 ORDER BY alm.atividade_id_legacy
                    LIMIT 1
               ) AS nome_legacy,
               (
                   SELECT a.tipo_atividade
                     FROM atividade_legacy_map alm
                     JOIN atividades a ON a.id = alm.atividade_id_legacy
                    WHERE alm.atividade_base_id = av.atividade_base_id
                 ORDER BY alm.atividade_id_legacy
                    LIMIT 1
               ) AS tipo_atividade_legacy
          FROM matriz_atividade_versao_item mavi
          JOIN atividade_versao av ON av.id = mavi.atividade_versao_id
          JOIN atividade_base ab ON ab.id = av.atividade_base_id
          JOIN norma_atividade n ON n.id = av.norma_id
         WHERE mavi.matriz_id = ?
      ORDER BY CASE av.eixo
                   WHEN 'AAC' THEN 0
                   WHEN 'AEU' THEN 1
                   ELSE 2
               END,
               COALESCE(NULLIF(TRIM(av.grupo), ''), 'zzzz'),
               COALESCE(NULLIF(TRIM(ab.nome_conceito), ''), 'zzzz'),
               av.id
        """,
        (matriz_id,),
    ).fetchall()

    atividades = [_serialize_versioned_activity_row(row) for row in versioned_rows]
    por_eixo: dict[str, list[dict[str, object]]] = {"AAC": [], "AEU": []}
    for item in atividades:
        por_eixo.setdefault(str(item["eixo"]), []).append(item)

    return {
        "turma": None,
        "turmas_vinculadas": turmas_vinculadas,
        "matriz": {
            "id": matriz["id"],
            "nome": matriz["nome"],
            "versao": matriz["versao"],
            "status": matriz["status"],
            "label": _matriz_option_label(matriz),
            "curso_id": matriz["curso_id"],
            "curso_nome": matriz["curso_nome"],
            "curso_codigo": matriz["curso_codigo"],
        },
        "normas": normas,
        "totais": {
            "geral": len(atividades),
            "por_eixo": {eixo: len(items) for eixo, items in por_eixo.items()},
        },
        "atividades": atividades,
        "por_eixo": por_eixo,
    }


def listar_atividades_versionadas_por_turma(conn, turma_id: int) -> dict[str, object]:
    _require_versioning_read_model(conn)

    turma = conn.execute(
        """
        SELECT t.*,
               c.nome AS curso_nome,
               c.codigo AS curso_codigo
          FROM turmas t
          LEFT JOIN cursos c ON c.id = t.curso_id
         WHERE t.id = ?
        """,
        (turma_id,),
    ).fetchone()
    if not turma:
        raise LookupError("Turma não encontrada para leitura diagnóstica.")

    matriz = _get_effective_matriz_for_turma_readonly(conn, turma["curso_id"], turma["matriz_id"])
    if not matriz:
        raise LookupError("Turma sem matriz disponível para leitura diagnóstica.")

    payload = listar_atividades_versionadas_por_matriz(conn, matriz["id"])
    payload["turma"] = {
        "id": turma["id"],
        "codigo": turma["codigo"],
        "nome": turma["nome"],
        "curso_id": turma["curso_id"],
        "curso_nome": turma["curso_nome"],
        "curso_codigo": turma["curso_codigo"],
        "periodo_label": _periodo_label_for_turma_row(turma),
        "matriz_id": matriz["id"],
    }
    return payload


def _resolver_result(
    status: str,
    *,
    atividade_versao_id=None,
    atividade_base_id=None,
    codigo_normativo=None,
    eixo=None,
    matriz_id_efetiva=None,
    legacy_scope_ok=None,
    warnings=None,
    reason=None,
) -> dict[str, object]:
    return {
        "status": status,
        "atividade_versao_id": atividade_versao_id,
        "atividade_base_id": atividade_base_id,
        "codigo_normativo": codigo_normativo,
        "eixo": eixo,
        "matriz_id_efetiva": matriz_id_efetiva,
        "legacy_scope_ok": legacy_scope_ok,
        "warnings": list(warnings or []),
        "reason": reason,
    }


def _atividade_versao_status_ativo(status: str | None) -> bool:
    return str(status or "").strip().lower() in {"ativa", "vigente", "active"}


def resolver_versao_por_matriz(
    conn,
    *,
    matriz_id,
    atividade_id_legacy,
    strict_legacy_scope=True,
) -> dict[str, object]:
    warnings: list[str] = []
    try:
        _require_versioning_read_model(conn)

        if not matriz_id:
            return _resolver_result(
                "error",
                matriz_id_efetiva=matriz_id,
                reason="matriz_id inválido para resolução.",
            )
        if not atividade_id_legacy:
            return _resolver_result(
                "error",
                matriz_id_efetiva=matriz_id,
                reason="atividade_id_legacy inválido para resolução.",
            )

        matriz = conn.execute(
            "SELECT id FROM matrizes_atividades WHERE id = ?",
            (matriz_id,),
        ).fetchone()
        if not matriz:
            return _resolver_result(
                "error",
                matriz_id_efetiva=matriz_id,
                reason="Matriz não encontrada para resolução versionada.",
            )

        legacy_scope_ok = conn.execute(
            """
            SELECT 1
              FROM matrizes_atividades_itens
             WHERE matriz_id = ? AND atividade_id = ?
            """,
            (matriz_id, atividade_id_legacy),
        ).fetchone() is not None

        if not legacy_scope_ok:
            if strict_legacy_scope:
                return _resolver_result(
                    "legacy_activity_not_in_matrix",
                    matriz_id_efetiva=matriz_id,
                    legacy_scope_ok=False,
                    reason="Atividade legado fora do escopo da matriz efetiva no modo estrito.",
                )
            warnings.append("legacy_activity_outside_matrix_scope")

        base_rows = conn.execute(
            """
            SELECT DISTINCT atividade_base_id
              FROM atividade_legacy_map
             WHERE atividade_id_legacy = ?
            """,
            (atividade_id_legacy,),
        ).fetchall()

        base_ids = sorted(
            {
                int(row["atividade_base_id"])
                for row in base_rows
                if row["atividade_base_id"] is not None
            }
        )
        if not base_ids:
            return _resolver_result(
                "legacy_activity_without_base_map",
                matriz_id_efetiva=matriz_id,
                legacy_scope_ok=legacy_scope_ok,
                warnings=warnings,
                reason="Atividade legado sem mapeamento para atividade_base.",
            )

        atividade_base_id = base_ids[0] if len(base_ids) == 1 else None
        placeholders = ",".join("?" for _ in base_ids)

        candidate_rows = conn.execute(
            f"""
            SELECT av.id AS atividade_versao_id,
                   av.atividade_base_id,
                   av.norma_id,
                   av.eixo,
                   av.status,
                   n.codigo AS codigo_normativo
              FROM atividade_versao av
              JOIN matriz_atividade_versao_item mavi
                ON mavi.atividade_versao_id = av.id
               AND mavi.matriz_id = ?
              LEFT JOIN norma_atividade n ON n.id = av.norma_id
             WHERE av.atividade_base_id IN ({placeholders})
          ORDER BY av.id
            """,
            [matriz_id, *base_ids],
        ).fetchall()

        if not candidate_rows:
            return _resolver_result(
                "base_without_version_for_matrix",
                atividade_base_id=atividade_base_id,
                matriz_id_efetiva=matriz_id,
                legacy_scope_ok=legacy_scope_ok,
                warnings=warnings,
                reason="Atividade base mapeada sem versão associada à matriz.",
            )

        matriz_norma_ids = {
            row["norma_id"]
            for row in conn.execute(
                "SELECT norma_id FROM matriz_norma WHERE matriz_id = ?",
                (matriz_id,),
            ).fetchall()
        }
        if not matriz_norma_ids:
            return _resolver_result(
                "matrix_without_norma",
                atividade_base_id=atividade_base_id,
                matriz_id_efetiva=matriz_id,
                legacy_scope_ok=legacy_scope_ok,
                warnings=warnings,
                reason="Matriz sem normas configuradas para validar resolução.",
            )

        norma_candidates = [
            row for row in candidate_rows if row["norma_id"] in matriz_norma_ids
        ]
        if not norma_candidates:
            return _resolver_result(
                "matrix_without_norma",
                atividade_base_id=atividade_base_id,
                matriz_id_efetiva=matriz_id,
                legacy_scope_ok=legacy_scope_ok,
                warnings=warnings,
                reason="Versões encontradas sem norma vinculada à matriz.",
            )

        valid_candidates = [
            row for row in norma_candidates if _atividade_versao_status_ativo(row["status"])
        ]
        if not valid_candidates:
            return _resolver_result(
                "version_inactive",
                atividade_base_id=atividade_base_id,
                matriz_id_efetiva=matriz_id,
                legacy_scope_ok=legacy_scope_ok,
                warnings=warnings,
                reason="Existe versão para a matriz, mas sem status ativo/vigente.",
            )

        if len(valid_candidates) > 1:
            warnings.append("multiple_valid_candidates")
            return _resolver_result(
                "ambiguous_version",
                atividade_base_id=atividade_base_id,
                matriz_id_efetiva=matriz_id,
                legacy_scope_ok=legacy_scope_ok,
                warnings=warnings,
                reason=(
                    "Mais de uma versão válida encontrada para a mesma atividade base: "
                    + ", ".join(str(row["atividade_versao_id"]) for row in valid_candidates)
                ),
            )

        resolved = valid_candidates[0]
        return _resolver_result(
            "resolved",
            atividade_versao_id=resolved["atividade_versao_id"],
            atividade_base_id=resolved["atividade_base_id"],
            codigo_normativo=resolved["codigo_normativo"],
            eixo=resolved["eixo"],
            matriz_id_efetiva=matriz_id,
            legacy_scope_ok=legacy_scope_ok,
            warnings=warnings,
            reason="Resolução versionada concluída com sucesso.",
        )
    except Exception as exc:
        return _resolver_result(
            "error",
            matriz_id_efetiva=matriz_id,
            reason=f"Falha inesperada no resolvedor versionado: {exc}",
        )


def resolver_versao_por_aluno(
    conn,
    *,
    aluno_id,
    atividade_id_legacy,
    strict_legacy_scope=True,
) -> dict[str, object]:
    try:
        _require_versioning_read_model(conn)

        if not aluno_id:
            return _resolver_result(
                "error",
                reason="aluno_id inválido para resolução.",
            )
        if not atividade_id_legacy:
            return _resolver_result(
                "error",
                reason="atividade_id_legacy inválido para resolução.",
            )

        aluno = conn.execute(
            """
            SELECT a.id AS aluno_id,
                   t.id AS turma_id,
                   t.curso_id AS turma_curso_id,
                   t.matriz_id AS turma_matriz_id
              FROM alunos a
              LEFT JOIN turmas t ON t.id = a.turma_id
             WHERE a.id = ?
            """,
            (aluno_id,),
        ).fetchone()
        if not aluno:
            return _resolver_result(
                "error",
                reason="Aluno não encontrado para resolução.",
            )

        matriz = _get_effective_matriz_for_turma_readonly(
            conn,
            aluno["turma_curso_id"],
            aluno["turma_matriz_id"],
        )
        if not matriz:
            return _resolver_result(
                "error",
                reason="Aluno sem matriz efetiva para resolução.",
            )

        return resolver_versao_por_matriz(
            conn,
            matriz_id=matriz["id"],
            atividade_id_legacy=atividade_id_legacy,
            strict_legacy_scope=strict_legacy_scope,
        )
    except Exception as exc:
        return _resolver_result(
            "error",
            reason=f"Falha inesperada no resolvedor por aluno: {exc}",
        )


def resolver_versao(
    conn,
    *,
    atividade_id_legacy,
    aluno_id=None,
    turma_id=None,
    matriz_id=None,
    strict_legacy_scope=True,
) -> dict[str, object]:
    try:
        _require_versioning_read_model(conn)

        if matriz_id:
            return resolver_versao_por_matriz(
                conn,
                matriz_id=matriz_id,
                atividade_id_legacy=atividade_id_legacy,
                strict_legacy_scope=strict_legacy_scope,
            )

        if turma_id:
            turma = conn.execute(
                """
                SELECT id, curso_id, matriz_id
                  FROM turmas
                 WHERE id = ?
                """,
                (turma_id,),
            ).fetchone()
            if not turma:
                return _resolver_result(
                    "error",
                    reason="Turma não encontrada para resolução.",
                )

            matriz = _get_effective_matriz_for_turma_readonly(
                conn,
                turma["curso_id"],
                turma["matriz_id"],
            )
            if not matriz:
                return _resolver_result(
                    "error",
                    reason="Turma sem matriz efetiva para resolução.",
                )

            return resolver_versao_por_matriz(
                conn,
                matriz_id=matriz["id"],
                atividade_id_legacy=atividade_id_legacy,
                strict_legacy_scope=strict_legacy_scope,
            )

        if aluno_id:
            return resolver_versao_por_aluno(
                conn,
                aluno_id=aluno_id,
                atividade_id_legacy=atividade_id_legacy,
                strict_legacy_scope=strict_legacy_scope,
            )

        return _resolver_result(
            "error",
            reason="Informe aluno_id, turma_id ou matriz_id para resolver a versão.",
        )
    except Exception as exc:
        return _resolver_result(
            "error",
            reason=f"Falha inesperada no wrapper do resolvedor: {exc}",
        )


def is_versioned_resolver_shadow_read_enabled() -> bool:
    return str(os.getenv("SGAA_VERSIONED_RESOLVER_SHADOW_READ", "0")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def is_versioned_requisicao_snapshot_display_enabled() -> bool:
    return str(os.getenv("SGAA_VERSIONED_REQUISICAO_SNAPSHOT_DISPLAY", "0")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def is_versioned_requisicao_snapshot_write_enabled() -> bool:
    return str(os.getenv("SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE", "0")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _versioned_shadow_read_dedicated_log_path() -> str:
    app_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(app_dir, "logs", "versioned_shadow_reads.log")


def _serialize_shadow_read_log_value(value) -> str:
    if value is None:
        return "null"
    text = str(value).strip()
    return text if text else "null"


def _build_versioned_shadow_read_event_line(
    *,
    origin,
    req_id,
    aluno_id,
    atividade_id_legacy,
    status,
    atividade_versao_id,
    codigo_normativo,
    eixo,
    warnings,
    reason,
    timestamp=None,
    exception_type=None,
    exception_message=None,
    exception_traceback=None,
) -> str:
    warnings_json = json.dumps(warnings or [], ensure_ascii=False)
    base = (
        "event=versioned_resolver_shadow_read "
        f"origin={_serialize_shadow_read_log_value(origin)} "
        f"req_id={_serialize_shadow_read_log_value(req_id)} "
        f"aluno_id={_serialize_shadow_read_log_value(aluno_id)} "
        f"atividade_id_legacy={_serialize_shadow_read_log_value(atividade_id_legacy)} "
        f"status={_serialize_shadow_read_log_value(status)} "
        f"atividade_versao_id={_serialize_shadow_read_log_value(atividade_versao_id)} "
        f"codigo_normativo={_serialize_shadow_read_log_value(codigo_normativo)} "
        f"eixo={_serialize_shadow_read_log_value(eixo)} "
        f"warnings={warnings_json} "
        f"reason={_serialize_shadow_read_log_value(reason)}"
    )
    suffix_parts: list[str] = []
    if timestamp:
        suffix_parts.append(f"timestamp={_serialize_shadow_read_log_value(timestamp)}")
    if exception_type:
        suffix_parts.append(f"exception_type={_serialize_shadow_read_log_value(exception_type)}")
    if exception_message is not None and str(exception_message) != "":
        encoded_msg = base64.b64encode(str(exception_message).encode("utf-8")).decode("ascii")
        suffix_parts.append(f"exception_message_b64={encoded_msg}")
    if exception_traceback is not None and str(exception_traceback) != "":
        encoded_tb = base64.b64encode(str(exception_traceback).encode("utf-8")).decode("ascii")
        suffix_parts.append(f"exception_traceback_b64={encoded_tb}")
    if suffix_parts:
        return base + " " + " ".join(suffix_parts)
    return base


def _append_versioned_shadow_read_event_line(event_line: str) -> None:
    log_path = _versioned_shadow_read_dedicated_log_path()
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as log_file:
            log_file.write(f"{event_line}\n")
    except Exception:
        # Diagnostico em modo sombra nunca deve bloquear o fluxo operacional.
        try:
            logger.warning(
                "event=versioned_resolver_shadow_read_sink_error log_path=%s reason=write_failed",
                log_path,
            )
        except Exception:
            pass


def _load_versioned_requisicao_snapshot_rule_row(
    conn,
    *,
    atividade_versao_id,
    atividade_id_legacy,
):
    return conn.execute(
        """
        SELECT av.id AS atividade_versao_id,
               av.atividade_base_id,
               av.codigo_normativo,
               av.eixo,
               av.grupo,
               av.ch_por_evento,
               av.limite_semestre,
               av.limite_total,
               av.status AS versao_status,
               ab.nome_conceito AS atividade_base_nome,
               COALESCE(
                   a.nome,
                   (
                       SELECT a2.nome
                         FROM atividade_legacy_map alm2
                         JOIN atividades a2 ON a2.id = alm2.atividade_id_legacy
                        WHERE alm2.atividade_base_id = av.atividade_base_id
                     ORDER BY alm2.atividade_id_legacy
                        LIMIT 1
                   ),
                   ab.nome_conceito
               ) AS nome_exibivel,
               COALESCE(
                   a.nome,
                   (
                       SELECT a2.nome
                         FROM atividade_legacy_map alm2
                         JOIN atividades a2 ON a2.id = alm2.atividade_id_legacy
                        WHERE alm2.atividade_base_id = av.atividade_base_id
                     ORDER BY alm2.atividade_id_legacy
                        LIMIT 1
                   )
               ) AS nome_legacy,
               COALESCE(
                   a.tipo_atividade,
                   (
                       SELECT a2.tipo_atividade
                         FROM atividade_legacy_map alm2
                         JOIN atividades a2 ON a2.id = alm2.atividade_id_legacy
                        WHERE alm2.atividade_base_id = av.atividade_base_id
                     ORDER BY alm2.atividade_id_legacy
                        LIMIT 1
                   )
               ) AS tipo_atividade_legacy
          FROM atividade_versao av
          JOIN atividade_base ab ON ab.id = av.atividade_base_id
          LEFT JOIN atividade_legacy_map alm
            ON alm.atividade_base_id = av.atividade_base_id
           AND alm.atividade_id_legacy = ?
          LEFT JOIN atividades a ON a.id = alm.atividade_id_legacy
         WHERE av.id = ?
        """,
        (atividade_id_legacy, atividade_versao_id),
    ).fetchone()


def _build_versioned_requisicao_snapshot_payload(
    *,
    flow_origin: str,
    atividade_id_legacy,
    resolver_result,
    rule_row,
) -> dict[str, object]:
    snapshot_written_at = (
        datetime.datetime.now(datetime.timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    return {
        "atividade_base_id": resolver_result.get("atividade_base_id"),
        "atividade_id_legacy": atividade_id_legacy,
        "atividade_versao_id": resolver_result.get("atividade_versao_id"),
        "ch_por_evento": rule_row["ch_por_evento"],
        "codigo_normativo": resolver_result.get("codigo_normativo") or rule_row["codigo_normativo"],
        "eixo": resolver_result.get("eixo") or rule_row["eixo"],
        "flow_origin": flow_origin,
        "grupo": rule_row["grupo"],
        "legacy_scope_ok": resolver_result.get("legacy_scope_ok"),
        "limite_semestre": rule_row["limite_semestre"],
        "limite_total": rule_row["limite_total"],
        "matriz_id_efetiva": resolver_result.get("matriz_id_efetiva"),
        "nome_exibivel": rule_row["nome_exibivel"],
        "nome_legacy": rule_row["nome_legacy"],
        "resolver_status": resolver_result.get("status"),
        "resolver_warnings": list(resolver_result.get("warnings") or []),
        "schema_version": "d6.4.0-v1",
        "snapshot_written_at": snapshot_written_at,
        "tipo_atividade_legacy": rule_row["tipo_atividade_legacy"],
        "versao_status": rule_row["versao_status"],
    }


def _get_turma_explicit_matriz_id_for_snapshot(conn, aluno_id: int | None) -> int | None:
    """Returns turma.matriz_id only when explicitly set for the aluno's turma.

    No fallback to preferred matriz for the curso — that is a heuristic that must
    not silently determine which version gets stamped on a requisição operacional.
    Used exclusively by the versioned snapshot writer; not by legacy scoping.
    """
    if not aluno_id:
        return None
    row = conn.execute(
        """
        SELECT t.matriz_id
          FROM alunos a
          LEFT JOIN turmas t ON t.id = a.turma_id
         WHERE a.id = ?
        """,
        (aluno_id,),
    ).fetchone()
    if not row:
        return None
    return row["matriz_id"]


def maybe_write_versioned_requisicao_snapshot(
    conn,
    *,
    flow_origin: str,
    req_id,
    aluno_id,
    atividade_id_legacy,
):
    if not is_versioned_requisicao_snapshot_write_enabled():
        return None

    # Strict check: turma must have an explicit matriz_id for the versioned stamp.
    # Fallback to preferred matriz is deliberately excluded — it is a heuristic and
    # must not silently determine which version gets stamped on a requisição.
    explicit_matriz_id = _get_turma_explicit_matriz_id_for_snapshot(conn, aluno_id)
    if not explicit_matriz_id:
        try:
            logger.info(
                "event=versioned_requisicao_snapshot_skip origin=%s req_id=%s aluno_id=%s "
                "atividade_id_legacy=%s status=turma_without_explicit_matrix",
                flow_origin,
                req_id,
                aluno_id,
                atividade_id_legacy,
            )
        except Exception:
            pass
        return None

    try:
        resolver_result = resolver_versao_por_aluno(
            conn,
            aluno_id=aluno_id,
            atividade_id_legacy=atividade_id_legacy,
            strict_legacy_scope=True,
        )
    except Exception:
        try:
            logger.exception(
                "event=versioned_requisicao_snapshot_exception origin=%s req_id=%s aluno_id=%s atividade_id_legacy=%s",
                flow_origin,
                req_id,
                aluno_id,
                atividade_id_legacy,
            )
        except Exception:
            pass
        return None

    if resolver_result.get("status") != "resolved":
        try:
            logger.warning(
                "event=versioned_requisicao_snapshot_skip origin=%s req_id=%s aluno_id=%s atividade_id_legacy=%s status=%s reason=%s",
                flow_origin,
                req_id,
                aluno_id,
                atividade_id_legacy,
                resolver_result.get("status"),
                resolver_result.get("reason"),
            )
        except Exception:
            pass
        return resolver_result

    atividade_versao_id = resolver_result.get("atividade_versao_id")
    if not atividade_versao_id:
        try:
            logger.warning(
                "event=versioned_requisicao_snapshot_skip origin=%s req_id=%s aluno_id=%s atividade_id_legacy=%s status=resolved reason=missing_atividade_versao_id",
                flow_origin,
                req_id,
                aluno_id,
                atividade_id_legacy,
            )
        except Exception:
            pass
        return resolver_result

    rule_row = _load_versioned_requisicao_snapshot_rule_row(
        conn,
        atividade_versao_id=atividade_versao_id,
        atividade_id_legacy=atividade_id_legacy,
    )
    if not rule_row:
        try:
            logger.warning(
                "event=versioned_requisicao_snapshot_skip origin=%s req_id=%s aluno_id=%s atividade_id_legacy=%s status=resolved reason=missing_rule_row",
                flow_origin,
                req_id,
                aluno_id,
                atividade_id_legacy,
            )
        except Exception:
            pass
        return resolver_result

    payload = _build_versioned_requisicao_snapshot_payload(
        flow_origin=flow_origin,
        atividade_id_legacy=atividade_id_legacy,
        resolver_result=resolver_result,
        rule_row=rule_row,
    )
    snapshot_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    conn.execute(
        """
        UPDATE requisicoes
           SET atividade_versao_id = ?,
               regra_snapshot_json = ?,
               codigo_normativo_snapshot = ?
         WHERE id = ?
        """,
        (
            atividade_versao_id,
            snapshot_json,
            resolver_result.get("codigo_normativo") or rule_row["codigo_normativo"],
            req_id,
        ),
    )
    try:
        logger.info(
            "event=versioned_requisicao_snapshot_written origin=%s req_id=%s aluno_id=%s atividade_id_legacy=%s atividade_versao_id=%s codigo_normativo=%s",
            flow_origin,
            req_id,
            aluno_id,
            atividade_id_legacy,
            atividade_versao_id,
            resolver_result.get("codigo_normativo") or rule_row["codigo_normativo"],
        )
    except Exception:
        pass
    return resolver_result


_ADMIN_REQUISICAO_SNAPSHOT_DIAGNOSTIC_FIELDS = (
    "codigo_normativo",
    "eixo",
    "grupo",
    "ch_por_evento",
    "limite_semestre",
    "limite_total",
    "nome_exibivel",
    "nome_legacy",
    "tipo_atividade_legacy",
    "flow_origin",
    "snapshot_written_at",
    "resolver_status",
    "resolver_warnings",
    "legacy_scope_ok",
    "atividade_id_legacy",
    "atividade_base_id",
    "matriz_id_efetiva",
    "versao_status",
)


def _snapshot_diagnostic_row_value(row, key):
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get(key)
    try:
        return row[key]
    except Exception:
        return None


def _normalize_snapshot_diagnostic_scalar(value):
    if value is None:
        return None
    if isinstance(value, (dict, list, tuple, set)):
        return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def _has_versioned_requisicao_snapshot(row) -> bool:
    atividade_versao_id = _snapshot_diagnostic_row_value(row, "atividade_versao_id")
    codigo_normativo_snapshot = _snapshot_diagnostic_row_value(row, "codigo_normativo_snapshot")
    if atividade_versao_id not in (None, ""):
        return True
    return bool(str(codigo_normativo_snapshot or "").strip())


def _build_admin_requisicao_snapshot_diagnostic(row) -> dict[str, object] | None:
    if not _has_versioned_requisicao_snapshot(row):
        return None

    atividade_versao_id = _snapshot_diagnostic_row_value(row, "atividade_versao_id")
    codigo_normativo_snapshot = str(
        _snapshot_diagnostic_row_value(row, "codigo_normativo_snapshot") or ""
    ).strip()
    raw_snapshot = _snapshot_diagnostic_row_value(row, "regra_snapshot_json")

    diagnostic: dict[str, object] = {
        "snapshot_versionado_presente": True,
        "diagnostico_disponivel": False,
    }
    if atividade_versao_id not in (None, ""):
        diagnostic["atividade_versao_id"] = atividade_versao_id
    if codigo_normativo_snapshot:
        diagnostic["codigo_normativo_snapshot"] = codigo_normativo_snapshot

    if raw_snapshot is None:
        return diagnostic
    raw_snapshot = str(raw_snapshot).strip()
    if not raw_snapshot:
        return diagnostic

    try:
        payload = json.loads(raw_snapshot)
    except (TypeError, ValueError, json.JSONDecodeError):
        return diagnostic

    if not isinstance(payload, dict):
        return diagnostic

    diagnostic["diagnostico_disponivel"] = True
    parsed_atividade_versao_id = payload.get("atividade_versao_id")
    if "atividade_versao_id" not in diagnostic and parsed_atividade_versao_id not in (None, ""):
        diagnostic["atividade_versao_id"] = parsed_atividade_versao_id

    for key in _ADMIN_REQUISICAO_SNAPSHOT_DIAGNOSTIC_FIELDS:
        value = payload.get(key)
        if key == "resolver_warnings":
            if value is None:
                continue
            if isinstance(value, list):
                warnings = [str(item).strip() for item in value if str(item).strip()]
            else:
                normalized = str(value).strip()
                warnings = [normalized] if normalized else []
            diagnostic[key] = warnings
            continue
        value = _normalize_snapshot_diagnostic_scalar(value)
        if value is None:
            continue
        diagnostic[key] = value

    return diagnostic


def maybe_run_versioned_resolver_shadow_read(
    conn,
    *,
    origin: str,
    aluno_id,
    atividade_id_legacy,
    req_id=None,
):
    if not is_versioned_resolver_shadow_read_enabled():
        return None

    try:
        event_timestamp = datetime.datetime.now().isoformat(timespec="microseconds")
    except Exception:
        event_timestamp = None

    try:
        result = resolver_versao_por_aluno(
            conn,
            aluno_id=aluno_id,
            atividade_id_legacy=atividade_id_legacy,
            strict_legacy_scope=True,
        )
    except Exception as exc:
        try:
            exc_type = type(exc).__name__
        except Exception:
            exc_type = "Exception"
        try:
            exc_message = str(exc)
        except Exception:
            exc_message = ""
        try:
            exc_traceback = traceback.format_exc()
        except Exception:
            exc_traceback = ""
        event_line = _build_versioned_shadow_read_event_line(
            origin=origin,
            req_id=req_id,
            aluno_id=aluno_id,
            atividade_id_legacy=atividade_id_legacy,
            status="error",
            atividade_versao_id=None,
            codigo_normativo=None,
            eixo=None,
            warnings=[],
            reason="resolver_exception",
            timestamp=event_timestamp,
            exception_type=exc_type,
            exception_message=exc_message,
            exception_traceback=exc_traceback,
        )
        _append_versioned_shadow_read_event_line(event_line)
        try:
            logger.exception(event_line)
        except Exception:
            pass
        return None

    event_line = _build_versioned_shadow_read_event_line(
        origin=origin,
        req_id=req_id,
        aluno_id=aluno_id,
        atividade_id_legacy=atividade_id_legacy,
        status=result.get("status"),
        atividade_versao_id=result.get("atividade_versao_id"),
        codigo_normativo=result.get("codigo_normativo"),
        eixo=result.get("eixo"),
        warnings=result.get("warnings") or [],
        reason=result.get("reason"),
        timestamp=event_timestamp,
    )
    _append_versioned_shadow_read_event_line(event_line)
    try:
        logger.info(event_line)
    except Exception:
        pass
    return result


def _normalize_shadow_read_scalar(value):
    text = str(value or "").strip()
    if not text or text.lower() in {"null", "none"}:
        return None
    return text


def _normalize_shadow_read_int(value):
    scalar = _normalize_shadow_read_scalar(value)
    if scalar is None:
        return None
    try:
        return int(scalar)
    except Exception:
        return None


def _parse_shadow_read_warnings(raw_warnings) -> list[str]:
    scalar = _normalize_shadow_read_scalar(raw_warnings)
    if not scalar:
        return []

    try:
        parsed = json.loads(scalar)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    except Exception:
        pass

    compact = scalar.strip()
    if compact.startswith("[") and compact.endswith("]"):
        compact = compact[1:-1].strip()
    if not compact:
        return []

    return [
        piece.strip().strip("\"'")
        for piece in compact.split(",")
        if piece.strip().strip("\"'")
    ]


def _parse_versioned_shadow_read_event_line(line: str):
    marker = "event=versioned_resolver_shadow_read"
    if marker not in line:
        return None

    payload = line[line.index("event="):].strip()
    token_pairs: dict[str, str] = {}
    for match in re.finditer(r"(\w+)=((?:(?!\s\w+=).)*)", payload):
        token_pairs[match.group(1)] = match.group(2).strip()

    if token_pairs.get("event") != "versioned_resolver_shadow_read":
        return None

    origin = _normalize_shadow_read_scalar(token_pairs.get("origin"))
    status = _normalize_shadow_read_scalar(token_pairs.get("status"))
    if not origin or not status:
        # Linha incompleta/malformada: ignora sem falhar endpoint.
        return None

    warnings = _parse_shadow_read_warnings(token_pairs.get("warnings"))

    exception_message = None
    exception_message_b64 = _normalize_shadow_read_scalar(
        token_pairs.get("exception_message_b64")
    )
    if exception_message_b64:
        try:
            exception_message = base64.b64decode(
                exception_message_b64.encode("ascii")
            ).decode("utf-8")
        except Exception:
            exception_message = None

    exception_traceback = None
    exception_traceback_b64 = _normalize_shadow_read_scalar(
        token_pairs.get("exception_traceback_b64")
    )
    if exception_traceback_b64:
        try:
            exception_traceback = base64.b64decode(
                exception_traceback_b64.encode("ascii")
            ).decode("utf-8")
        except Exception:
            exception_traceback = None

    return {
        "origin": origin,
        "req_id": _normalize_shadow_read_int(token_pairs.get("req_id")),
        "aluno_id": _normalize_shadow_read_int(token_pairs.get("aluno_id")),
        "atividade_id_legacy": _normalize_shadow_read_int(token_pairs.get("atividade_id_legacy")),
        "status": status,
        "atividade_versao_id": _normalize_shadow_read_int(token_pairs.get("atividade_versao_id")),
        "codigo_normativo": _normalize_shadow_read_scalar(token_pairs.get("codigo_normativo")),
        "eixo": _normalize_shadow_read_scalar(token_pairs.get("eixo")),
        "warnings": warnings,
        "has_warnings": bool(warnings),
        "reason": _normalize_shadow_read_scalar(token_pairs.get("reason")),
        "timestamp": _normalize_shadow_read_scalar(token_pairs.get("timestamp")),
        "exception_type": _normalize_shadow_read_scalar(token_pairs.get("exception_type")),
        "exception_message": exception_message,
        "exception_traceback": exception_traceback,
    }


def _collect_versioned_shadow_read_log_paths() -> list[str]:
    dedicated_path = os.path.abspath(_versioned_shadow_read_dedicated_log_path())
    base_paths: list[str] = [dedicated_path]
    for handler in logger.handlers:
        handler_path = getattr(handler, "baseFilename", None)
        if handler_path:
            base_paths.append(os.path.abspath(handler_path))

    app_dir = os.path.dirname(os.path.abspath(__file__))
    base_paths.append(os.path.join(app_dir, "logs", "app.log"))

    dedup_base_paths: list[str] = []
    seen: set[str] = set()
    for candidate in base_paths:
        normalized = os.path.abspath(candidate)
        if normalized in seen:
            continue
        seen.add(normalized)
        dedup_base_paths.append(normalized)

    # Mantém ordem cronológica aproximada: rotacionado imediato antes do log atual.
    expanded_paths: list[str] = []
    for base_path in dedup_base_paths:
        if os.path.abspath(base_path) != dedicated_path:
            expanded_paths.append(f"{base_path}.1")
        expanded_paths.append(base_path)
    return expanded_paths


def _resolve_versioned_shadow_read_log_sources() -> dict[str, object]:
    dedicated_path = os.path.abspath(_versioned_shadow_read_dedicated_log_path())
    candidate_paths = _collect_versioned_shadow_read_log_paths()
    dedicated_exists = os.path.exists(dedicated_path)

    if dedicated_exists:
        return {
            "source_mode": "dedicated",
            "dedicated_path": dedicated_path,
            "dedicated_exists": True,
            "paths_to_read": [dedicated_path],
            "candidate_paths": candidate_paths,
        }

    fallback_paths = [
        os.path.abspath(path)
        for path in candidate_paths
        if os.path.abspath(path) != dedicated_path
    ]
    if not fallback_paths:
        fallback_paths = [dedicated_path]

    return {
        "source_mode": "fallback_app_log",
        "dedicated_path": dedicated_path,
        "dedicated_exists": False,
        "paths_to_read": fallback_paths,
        "candidate_paths": candidate_paths,
    }


def _shadow_read_event_dedup_key(event: dict[str, object]) -> tuple[object, ...]:
    return (
        event.get("origin"),
        event.get("req_id"),
        event.get("aluno_id"),
        event.get("atividade_id_legacy"),
        event.get("status"),
        event.get("atividade_versao_id"),
        event.get("codigo_normativo"),
        event.get("eixo"),
        event.get("reason"),
    )


def _parse_shadow_read_bool_filter(raw_value):
    text = str(raw_value or "").strip().lower()
    if not text:
        return None
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None


def _shadow_read_event_matches_filters(event, filters: dict[str, object]) -> bool:
    origin = filters.get("origin")
    if origin and event.get("origin") != origin:
        return False

    status = filters.get("status")
    if status and event.get("status") != status:
        return False

    codigo_normativo = filters.get("codigo_normativo")
    if codigo_normativo and event.get("codigo_normativo") != codigo_normativo:
        return False

    eixo = filters.get("eixo")
    if eixo and event.get("eixo") != eixo:
        return False

    aluno_id = filters.get("aluno_id")
    if aluno_id is not None and event.get("aluno_id") != aluno_id:
        return False

    atividade_id_legacy = filters.get("atividade_id_legacy")
    if atividade_id_legacy is not None and event.get("atividade_id_legacy") != atividade_id_legacy:
        return False

    has_warnings = filters.get("has_warnings")
    if has_warnings is not None and bool(event.get("has_warnings")) != has_warnings:
        return False

    return True


def _read_versioned_shadow_read_events(
    *,
    limit: int,
    filters: dict[str, object],
    source_info: dict[str, object] | None = None,
):
    events_raw: list[dict[str, object]] = []
    effective_source_info = source_info or _resolve_versioned_shadow_read_log_sources()
    log_paths = [str(path) for path in effective_source_info.get("paths_to_read", [])]
    found_any_log_file = False

    for log_path in log_paths:
        if not os.path.exists(log_path):
            continue
        found_any_log_file = True
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as log_file:
                for line in log_file:
                    event = _parse_versioned_shadow_read_event_line(line)
                    if not event:
                        continue
                    if _shadow_read_event_matches_filters(event, filters):
                        events_raw.append(event)
        except Exception:
            # Diagnóstico é melhor-esforço e jamais deve quebrar o endpoint.
            continue

    raw_count = len(events_raw)
    events_desc = list(reversed(events_raw))
    deduped_events: list[dict[str, object]] = []
    seen_keys: set[tuple[object, ...]] = set()
    for event in events_desc:
        dedup_key = _shadow_read_event_dedup_key(event)
        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)
        deduped_events.append(event)

    deduplicated_count = raw_count - len(deduped_events)
    return (
        deduped_events[:limit],
        (not found_any_log_file),
        raw_count,
        deduplicated_count,
        str(effective_source_info.get("source_mode") or "fallback_app_log"),
        log_paths,
    )


def ensure_admin_arquivos_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_arquivos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT NOT NULL,
            descricao TEXT,
            filename TEXT NOT NULL,
            original_filename TEXT,
            visivel INTEGER NOT NULL DEFAULT 1,
            criado_em TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_admin_arquivos_visivel ON admin_arquivos(visivel)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_admin_arquivos_criado_em ON admin_arquivos(criado_em)")


def get_admin_arquivo(conn, arquivo_id: int):
    ensure_admin_arquivos_table(conn)
    return conn.execute("SELECT * FROM admin_arquivos WHERE id = ?", (arquivo_id,)).fetchone()


def ensure_admin_alertas_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_alertas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT,
            mensagem TEXT NOT NULL,
            bg_color TEXT NOT NULL DEFAULT '#eff6ff',
            border_color TEXT NOT NULL DEFAULT '#bfdbfe',
            visivel INTEGER NOT NULL DEFAULT 1,
            criado_em TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_admin_alertas_visivel ON admin_alertas(visivel)")


def ensure_reportes_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reportes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            aluno_id INTEGER NOT NULL,
            titulo TEXT NOT NULL,
            descricao TEXT NOT NULL,
            categoria TEXT NOT NULL DEFAULT 'Bug na plataforma',
            screenshot_filename TEXT,
            status TEXT NOT NULL DEFAULT 'Novo' CHECK(status IN ('Novo', 'Em análise', 'Resolvido')),
            criado_em TEXT NOT NULL DEFAULT (datetime('now')),
            atualizado_em TEXT NOT NULL DEFAULT (datetime('now')),
            admin_id INTEGER,
            FOREIGN KEY (aluno_id) REFERENCES alunos(id) ON DELETE CASCADE ON UPDATE CASCADE,
            FOREIGN KEY (admin_id) REFERENCES usuarios(id) ON DELETE SET NULL ON UPDATE CASCADE
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reportes_aluno_id ON reportes(aluno_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reportes_status ON reportes(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reportes_criado_em ON reportes(criado_em)")


def list_active_admin_alertas(conn):
    ensure_admin_alertas_table(conn)
    return conn.execute(
        """
        SELECT id, titulo, mensagem, bg_color, border_color, visivel, criado_em
          FROM admin_alertas
         WHERE visivel = 1
      ORDER BY datetime(criado_em) DESC, id DESC
        """
    ).fetchall()

# ===================== App / Config =====================

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
_log_fmt = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
try:
    logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
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


def _noop_route(*args, **kwargs):
    def decorator(func):
        return func

    return decorator


app = create_app(register_aluno_blueprint=USE_ALUNO_BLUEPRINT)
aluno_runtime_route = app.route if not USE_ALUNO_BLUEPRINT else _noop_route
app.add_template_global(resolve_user_message, name="user_message")


def aluno_url(endpoint: str, **values):
    resolved_endpoint = f"aluno.{endpoint}" if USE_ALUNO_BLUEPRINT else endpoint
    return url_for(resolved_endpoint, **values)

# Config via ambiente (com defaults seguros)
# `app.secret_key`, cookies de sessão, lifetime e flags CSRF já são aplicados
# centralmente em `app/__init__.py::create_app`. Não sobrescreva aqui.
app.config["UPLOAD_FOLDER"] = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
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

# Caminho robusto do banco (padrão: arquivo local na pasta src)
DATABASE = os.getenv(
    "APP_DATABASE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "database.db")
)
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

# Uploads: extensões permitidas
ALLOWED_EXCEL = {"xlsx"}
ALLOWED_CSV = {"csv"}
ALLOWED_ATTACHMENTS = {"pdf", "png", "jpg", "jpeg"}
ALLOWED_REPORTE_SCREENSHOTS = {"png", "jpg", "jpeg", "webp"}
REPORTE_CATEGORY_OPTIONS = (
    "Bug na plataforma",
    "Problema em dados",
    "Dificuldade de uso",
    "Outro",
)
REPORTE_STATUS_OPTIONS = (
    "Novo",
    "Em análise",
    "Resolvido",
)

def _allowed(filename: str, allowed: set[str]) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed

def _unique_filename(original_name: str, prefix: str = "") -> str:
    base = secure_filename(original_name)
    name, ext = os.path.splitext(base)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    rnd = secrets.token_hex(4)
    if prefix:
        prefix = secure_filename(prefix)
        return f"{prefix}-{ts}-{rnd}-{name}{ext}"
    return f"{ts}-{rnd}-{name}{ext}"

def save_upload(file_storage, allowed: set[str], prefix: str = "", subdir: str | None = None) -> str | None:
    """Salva um upload validando extensão e gerando nome único.
    - allowed: conjunto de extensões permitidas
    - prefix: prefixo opcional do nome do arquivo
    - subdir: subpasta relativa dentro de UPLOAD_FOLDER (ex.: 'aluno_10/req_123')
    Retorna o caminho relativo salvo (ex.: 'aluno_10/req_123/2025-...-file.pdf') ou None.
    """
    if not file_storage or not getattr(file_storage, "filename", None):
        return None
    fname = file_storage.filename
    if not _allowed(fname, allowed):
        raise ValueError("Extensão de arquivo não permitida.")
    final_name = _unique_filename(fname, prefix=prefix)
    rel_path = final_name
    if subdir:
        # normaliza subdir e impede caminhos absolutos
        safe_subdir = os.path.normpath(subdir).lstrip(os.sep).replace('..', '')
        rel_path = os.path.join(safe_subdir, final_name)
    path = os.path.join(app.config["UPLOAD_FOLDER"], rel_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    file_storage.save(path)
    return rel_path


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


ATIVIDADES_IMPORT_REQUIRED_HEADERS = (
    "nome",
    "tipo_atividade",
    "grupo_numero",
    "grupo_descricao",
    "tem_limitacao",
    "tipo_limitacao",
    "limite_horas_total",
    "limite_horas_semestral",
)


def _normalize_import_header_name(text: str) -> str:
    return normalize_header(text).replace("-", "_").replace(" ", "_")


def _canonicalize_tipo_atividade(value: str) -> str | None:
    normalized = normalize_header(value).replace("_", " ")
    if normalized in {"academica complementar", "academica", "aac"}:
        return "Acadêmica Complementar"
    if normalized in {"extensao universitaria", "extensao universitária", "extensao", "aeu"}:
        return "Extensão Universitária"
    return None


def _canonicalize_tipo_limitacao(value: str) -> str | None:
    normalized = normalize_header(value).replace("_", " ")
    if normalized == "total":
        return "total"
    if normalized == "semestral":
        return "semestral"
    return None


def _parse_csv_boolean(value) -> bool | None:
    normalized = normalize_header(value or "").replace("_", " ")
    if normalized in {"", "0", "false", "nao", "não", "no", "n"}:
        return False
    if normalized in {"1", "true", "sim", "yes", "y", "s"}:
        return True
    return None


def _parse_optional_positive_int(value):
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        raise ValueError("valor_invalido")
    if parsed <= 0:
        raise ValueError("valor_invalido")
    return parsed


def _build_grupo_label(numero: str, descricao: str) -> str:
    numero = str(numero or "").strip()
    descricao = str(descricao or "").strip()
    return f"{numero} - {descricao}" if descricao else numero


def _normalize_atividade_grupo(tipo_atividade: str, grupo: str) -> str:
    if (tipo_atividade or "").strip() == "Extensão Universitária":
        return "NA"
    return (grupo or "").strip()


def _format_preview_limitacao(tem_limitacao: bool, tipo_limitacao: str | None, limite_total, limite_semestral) -> str:
    if not tem_limitacao:
        return "Sem limitação"
    if tipo_limitacao == "total" and limite_total is not None:
        return f"Total: {limite_total}h"
    if tipo_limitacao == "semestral" and limite_semestral is not None:
        return f"Semestral: {limite_semestral}h"
    return "Com limitação"


def _ensure_grupos_def_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS grupos_def (
            tipo_atividade TEXT NOT NULL,
            numero INTEGER NOT NULL,
            descricao TEXT,
            PRIMARY KEY (tipo_atividade, numero)
        )
        """
    )


def _upsert_grupo_definition(conn, tipo_atividade: str, grupo_numero: str, grupo_descricao: str) -> None:
    _ensure_grupos_def_table(conn)
    numero = int(grupo_numero)
    descricao = (grupo_descricao or "").strip()
    updated = conn.execute(
        "UPDATE grupos_def SET descricao = ? WHERE tipo_atividade = ? AND numero = ?",
        (descricao, tipo_atividade, numero),
    )
    if updated.rowcount == 0:
        conn.execute(
            "INSERT INTO grupos_def (tipo_atividade, numero, descricao) VALUES (?, ?, ?)",
            (tipo_atividade, numero, descricao),
        )


def _atividades_import_preview_dir() -> str:
    path = os.path.join(app.config["UPLOAD_FOLDER"], "atividades_import_previews")
    os.makedirs(path, exist_ok=True)
    return path


def _atividades_import_preview_path(preview_key: str) -> str:
    safe_key = secure_filename(preview_key)
    return os.path.join(_atividades_import_preview_dir(), f"{safe_key}.json")


def _store_atividades_import_preview(payload: dict) -> str:
    preview_key = secrets.token_urlsafe(16)
    with open(_atividades_import_preview_path(preview_key), "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
    return preview_key


def _load_atividades_import_preview(preview_key: str) -> dict | None:
    path = _atividades_import_preview_path(preview_key)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _delete_atividades_import_preview(preview_key: str) -> None:
    path = _atividades_import_preview_path(preview_key)
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def _delete_upload_relpath(rel_path: str | None) -> None:
    if not rel_path:
        return
    abs_path = os.path.join(app.config["UPLOAD_FOLDER"], rel_path)
    try:
        if os.path.exists(abs_path):
            os.remove(abs_path)
    except OSError:
        pass


def _build_atividades_import_preview(csv_abspath: str, csv_relpath: str, mode: str) -> tuple[dict, dict | None]:
    conn = get_db_connection()
    existing_rows = conn.execute("SELECT id, nome FROM atividades").fetchall()
    existing_by_name = {str(row["nome"]): row["id"] for row in existing_rows}

    preview = {
        "ok": True,
        "missing_headers": [],
        "rows": [],
        "summary": {
            "linhas_lidas": 0,
            "criar": 0,
            "atualizar": 0,
            "ignorar": 0,
            "erros": 0,
        },
    }

    with open(csv_abspath, "r", encoding="utf-8-sig", newline="") as handle:
        sample = handle.read(2048)
        handle.seek(0)
        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=";,").delimiter
        except csv.Error:
            delimiter = ";" if sample.count(";") >= sample.count(",") else ","
        reader = csv.DictReader(handle, delimiter=delimiter)
        header_map = {_normalize_import_header_name(header): header for header in (reader.fieldnames or [])}
        missing_headers = [header for header in ATIVIDADES_IMPORT_REQUIRED_HEADERS if header not in header_map]
        if missing_headers:
            preview["ok"] = False
            preview["missing_headers"] = missing_headers
            return preview, None

        action_rows = []
        for line_number, row in enumerate(reader, start=2):
            if not any(str(value or "").strip() for value in row.values()):
                continue

            preview["summary"]["linhas_lidas"] += 1
            errors = []

            def cell(name: str) -> str:
                return str(row.get(header_map[name], "") or "").strip()

            nome = cell("nome")
            tipo_atividade = _canonicalize_tipo_atividade(cell("tipo_atividade"))
            grupo_numero = cell("grupo_numero")
            grupo_descricao = cell("grupo_descricao")
            tem_limitacao = _parse_csv_boolean(cell("tem_limitacao"))
            tipo_limitacao = _canonicalize_tipo_limitacao(cell("tipo_limitacao"))
            limite_total = None
            limite_semestral = None

            if not nome:
                errors.append("Nome é obrigatório")
            if not grupo_numero.isdigit():
                errors.append("Grupo deve ter número válido")
            if not tipo_atividade:
                errors.append("Tipo de atividade inválido")
            if tem_limitacao is None:
                errors.append("Campo tem_limitacao inválido")

            if tem_limitacao:
                if tipo_limitacao not in {"total", "semestral"}:
                    errors.append("Tipo de limitação inválido")
                try:
                    limite_total = _parse_optional_positive_int(cell("limite_horas_total"))
                    limite_semestral = _parse_optional_positive_int(cell("limite_horas_semestral"))
                except ValueError:
                    errors.append("Limites devem ser inteiros positivos")
                if tipo_limitacao == "total" and limite_total is None:
                    errors.append("Limite total é obrigatório")
                if tipo_limitacao == "semestral" and limite_semestral is None:
                    errors.append("Limite semestral é obrigatório")
            else:
                tipo_limitacao = "total"

            grupo = _build_grupo_label(grupo_numero, grupo_descricao)
            action = None
            situacao = "Erro"
            existing_id = existing_by_name.get(nome)
            if errors:
                preview["summary"]["erros"] += 1
            elif existing_id:
                if mode == "upsert":
                    action = "update"
                    situacao = "Atualizar"
                    preview["summary"]["atualizar"] += 1
                else:
                    action = "ignore"
                    situacao = "Ignorar"
                    preview["summary"]["ignorar"] += 1
            else:
                action = "create"
                situacao = "Criar"
                preview["summary"]["criar"] += 1

            payload = None
            if action in {"create", "update"}:
                payload = {
                    "action": action,
                    "existing_id": existing_id,
                    "nome": nome,
                    "grupo": grupo,
                    "grupo_numero": grupo_numero,
                    "grupo_descricao": grupo_descricao,
                    "tipo_atividade": tipo_atividade,
                    "tem_limitacao": bool(tem_limitacao),
                    "tipo_limitacao": tipo_limitacao,
                    "limite_horas_total": limite_total,
                    "limite_horas_semestral": limite_semestral,
                }
                action_rows.append(payload)

            preview["rows"].append(
                {
                    "line_number": line_number,
                    "nome": nome,
                    "tipo_atividade": tipo_atividade or cell("tipo_atividade"),
                    "grupo": grupo,
                    "limitacao": _format_preview_limitacao(bool(tem_limitacao), tipo_limitacao, limite_total, limite_semestral),
                    "situacao": situacao,
                    "errors": errors,
                }
            )

    storage_payload = {
        "mode": mode,
        "csv_relpath": csv_relpath,
        "rows": action_rows,
    }
    return preview, storage_payload

def get_db_connection():
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        try:
            g.db.create_collation("PTBR_NOACCENT", ptbr_sqlite_collation)
        except Exception:
            pass
        try:
            # Segurança e integridade
            g.db.execute("PRAGMA foreign_keys = ON")
            # Performance para acesso concorrente leve
            g.db.execute("PRAGMA journal_mode = WAL")
            g.db.execute("PRAGMA synchronous = NORMAL")
        except Exception:
            pass
    return g.db

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

@app.teardown_appcontext
def close_db_connection(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()


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


@app.before_request
def enforce_admin_access_control():
    endpoint = request.endpoint or ""
    if session.get("user_type") != "admin":
        return None
    requirement = get_admin_permission_requirement(endpoint, request.method)
    if requirement is None:
        return None
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
@aluno_runtime_route("/aluno/arquivos")
@aluno_required
def aluno_arquivos():
    # Lista simples de arquivos sob static/docs se existir
    docs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'docs')
    arquivos = []
    if os.path.isdir(docs_dir):
        for name in sorted(os.listdir(docs_dir)):
            p = os.path.join(docs_dir, name)
            if os.path.isfile(p):
                rel = f"docs/{name}"
                size_kb = max(1, int(os.path.getsize(p) / 1024)) if os.path.getsize(p) else None
                arquivos.append({
                    'label': name,
                    'path': rel,
                    'size_kb': size_kb
                })
    return render_template('aluno_arquivos.html', arquivos=arquivos)

# ===================== Rotas Aluno: Minhas Requisições =====================
@aluno_runtime_route("/aluno/requisicoes")
@aluno_required
def aluno_minhas_requisicoes():
    """Lista as requisições do aluno autenticado com filtros opcionais.
    Backend-only cleanup: constrói SQL de forma explícita (SELECT/FROM/WHERE/ORDER)
    e calcula COUNT sem manipulacao frágil de strings. Sem mudanças de UI.
    """
    page, per_page, offset = get_pagination(default_per_page=20)
    conn = get_db_connection()
    # Mapear user_id -> aluno_id
    user_id = session.get('user_id')
    arow = conn.execute("SELECT id FROM alunos WHERE usuario_id = ?", (user_id,)).fetchone()
    if not arow:
        flash("Aluno não encontrado.", "error")
        return redirect(url_for('aluno_dashboard'))
    aluno_id = arow['id']

    q = (request.args.get('q') or '').strip()
    status = (request.args.get('status') or '').strip()
    sort = (request.args.get('sort') or '').strip().lower()
    dir_ = (request.args.get('dir') or 'desc').strip().lower()
    dir_sql = 'DESC' if dir_ == 'desc' else 'ASC'

    # Blocos SQL claros
    select_cols = (
        "SELECT r.id, r.data_evento, r.data_processamento, r.horas_solicitadas, r.horas_deferidas, r.status, "
        "a.nome AS atividade_nome, a.tipo_atividade, a.grupo AS grupo "
    )
    base_from = (
        "FROM requisicoes r "
        "JOIN atividades a ON a.id = r.atividade_id "
        "WHERE r.aluno_id = ?"
    )
    params: list[object] = [aluno_id]
    where_parts: list[str] = []
    if q:
        like = f"%{q}%"
        where_parts.append("(LOWER(a.nome) LIKE LOWER(?) OR LOWER(r.status) LIKE LOWER(?))")
        params.extend([like, like])
    if status:
        where_parts.append("r.status = ?")
        params.append(status)
    # Build WHERE suffix to append to base_from (which already has WHERE r.aluno_id = ?)
    where_sql = ""
    if where_parts:
        where_sql = " AND " + " AND ".join(where_parts)

    # Ordenação controlada (whitelist)
    sort_map = {
        'data_evento': 'r.data_evento',
        'horas_solicitadas': 'r.horas_solicitadas',
        'status': 'r.status',
        'processado_em': 'r.data_processamento'
    }
    order_col = sort_map.get(sort, 'r.data_evento')
    query = select_cols + base_from + where_sql + f" ORDER BY {order_col} {dir_sql}, r.id DESC"

    # COUNT consistente (mesmo FROM/WHERE, sem ORDER BY)
    count_sql = "SELECT COUNT(*) " + base_from + where_sql
    total = conn.execute(count_sql, params).fetchone()[0]

    # Mantém sem paginação a menos que usuário informe page/per_page
    apply_limit = wants_pagination()
    exec_params = list(params)
    if apply_limit:
        query += " LIMIT ? OFFSET ?"
        exec_params += [per_page, offset]

    rows = conn.execute(query, exec_params).fetchall()
    requisicoes = [{
        'id': r['id'],
        'data_evento': r['data_evento'],
        'data_processamento': r['data_processamento'],
        'horas_solicitadas': r['horas_solicitadas'],
        'horas_deferidas': r['horas_deferidas'],
        'status': r['status'],
        'atividade_nome': r['atividade_nome'],
        'tipo_atividade': r['tipo_atividade'],
        'grupo': r['grupo']
    } for r in rows]

    total_pages = (total + per_page - 1) // per_page if apply_limit and per_page else 1
    return render_template('aluno_minhas_requisicoes.html', requisicoes=requisicoes, page=page, per_page=per_page, total=total, total_pages=total_pages)

# Detalhe da requisição (Aluno)
@aluno_runtime_route("/aluno/requisicoes/<int:req_id>", methods=["GET","POST"])
@aluno_required
def aluno_requisicao_detalhe(req_id: int):
    conn = get_db_connection()
    user_id = session.get('user_id')
    arow = conn.execute("SELECT id FROM alunos WHERE usuario_id = ?", (user_id,)).fetchone()
    if not arow:
        flash("Aluno não encontrado.", "error")
        return redirect(url_for('aluno_dashboard'))
    aluno_id = arow['id']

    # Exclusão via ?delete=1 (enviado por formulário POST oculto no front)
    delete_flag = (request.args.get('delete') or '').strip() == '1'
    if request.method == 'POST' and delete_flag:
        # Verifica propriedade
        owns = conn.execute("SELECT id FROM requisicoes WHERE id=? AND aluno_id=?", (req_id, aluno_id)).fetchone()
        if not owns:
            flash("Requisição não encontrada ou não pertence ao aluno.", "error")
            return redirect(url_for('aluno_minhas_requisicoes'))
        # Carrega anexos para remoção
        anexos_rows = conn.execute("SELECT filename FROM requisicao_arquivos WHERE requisicao_id=?", (req_id,)).fetchall()
        legacy_row = conn.execute("SELECT arquivo_comprovante FROM requisicoes WHERE id=?", (req_id,)).fetchone()
        try:
            conn.execute("DELETE FROM requisicao_arquivos WHERE requisicao_id=?", (req_id,))
            conn.execute("DELETE FROM requisicoes WHERE id=? AND aluno_id=?", (req_id, aluno_id))
            conn.commit()
        except Exception as e:
            flash("Não foi possível excluir a requisição.", "error")
            logger.error(f"Erro ao excluir requisicao {req_id}: {e}")
            return redirect(url_for('aluno_minhas_requisicoes'))
        # Remover arquivos físicos (melhor esforço)
        try:
            upload_root = app.config.get('UPLOAD_FOLDER')
            if upload_root:
                # Pasta padrão utilizada: aluno_<aluno_id>/req_<req_id>
                req_dir = os.path.join(upload_root, f"aluno_{aluno_id}", f"req_{req_id}")
                if os.path.isdir(req_dir):
                    shutil.rmtree(req_dir, ignore_errors=True)
                # Legacy single file (se estiver em raiz do aluno)
                if legacy_row and legacy_row['arquivo_comprovante']:
                    legacy_path = os.path.join(upload_root, legacy_row['arquivo_comprovante'])
                    if os.path.isfile(legacy_path):
                        try: os.remove(legacy_path)
                        except Exception: pass
        except Exception as e:
            logger.warning(f"Falha ao remover arquivos da requisicao {req_id}: {e}")
        flash("Requisição excluída.", "success")
        return redirect(url_for('aluno_minhas_requisicoes'))

    if request.method == 'POST' and not delete_flag:
        # Edição completa (campos) + novos anexos permitida se Pendente ou Devolvida (até 14 dias)
        rec = conn.execute("SELECT status, arquivo_comprovante, data_processamento FROM requisicoes WHERE id=? AND aluno_id=?", (req_id, aluno_id)).fetchone()
        if not rec:
            flash("Requisição não encontrada.", "error")
            return redirect(url_for('aluno_minhas_requisicoes'))
        can_edit = False
        try:
            st = rec['status']
            if st == 'Pendente':
                can_edit = True
            elif st == 'Devolvida':
                dp = rec['data_processamento']
                if dp:
                    try:
                        dt = datetime.datetime.strptime(str(dp), "%Y-%m-%d %H:%M:%S")
                    except Exception:
                        dt = None
                    if dt and datetime.datetime.now() <= (dt + datetime.timedelta(days=14)):
                        can_edit = True
        except Exception:
            can_edit = False
        if not can_edit:
            flash("Edição só permitida enquanto Pendente ou Devolvida (até 14 dias).", "error")
            return redirect(url_for('aluno_requisicao_detalhe', req_id=req_id))

        # Campos editáveis
        nome_evento = request.form.get('nome_evento')
        horas_solicitadas_raw = request.form.get('horas_solicitadas')
        data_evento_raw = request.form.get('data_evento')
        observacao = request.form.get('observacao')
        atividade_id_new = request.form.get('atividade_id')  # opcional; se ausente mantém

        # Normalizações
        try:
            horas_solicitadas = float(horas_solicitadas_raw) if horas_solicitadas_raw not in (None, '') else None
        except Exception:
            horas_solicitadas = None
        data_evento_norm = None
        if data_evento_raw:
            s = str(data_evento_raw).strip()
            # aceita YYYY-MM-DD ou DD/MM/YYYY
            if '/' in s:
                parts = s.split('/')
                if len(parts) >= 3:
                    try:
                        data_evento_norm = f"{parts[2]}-{int(parts[1]):02d}-{int(parts[0]):02d}"
                    except Exception:
                        data_evento_norm = None
            elif '-' in s:
                data_evento_norm = s.split(' ')[0][:10]

        # Anexos múltiplos (apêndice)
        arquivos = request.files.getlist('comprovantes_files') or []
        labels = request.form.getlist('comprovantes_labels') or []
        novo_arquivo_unico = request.files.get('arquivo_comprovante')  # legado
        filenames_saved = []
        first_saved = None
        if novo_arquivo_unico and novo_arquivo_unico.filename and not arquivos:
            arquivos = [novo_arquivo_unico]
            labels = ['Comprovante']
        for idx, f in enumerate(arquivos):
            if not f or not getattr(f, 'filename', ''):
                continue
            if not _allowed(f.filename, ALLOWED_ATTACHMENTS):
                flash(f"Arquivo ignorado por extensão não permitida: {f.filename}", 'warning')
                continue
            try:
                saved = save_upload(
                    f,
                    ALLOWED_ATTACHMENTS,
                    prefix=f"req{req_id}",
                    subdir=f"aluno_{aluno_id}/req_{req_id}"
                )
                if saved:
                    if first_saved is None:
                        first_saved = saved
                    label_val = labels[idx] if labels and idx < len(labels) else None
                    conn.execute(
                        "INSERT INTO requisicao_arquivos (requisicao_id, label, filename) VALUES (?, ?, ?)",
                        (req_id, label_val, saved)
                    )
                    filenames_saved.append(saved)
            except Exception as e:
                logger.error(f"Falha ao salvar anexo em edição: {e}")

        # Atualização principal
        set_parts = ["observacao = ?"]
        params = [observacao]
        if nome_evento is not None:
            set_parts.append("nome_evento = ?")
            params.append(nome_evento)
        if horas_solicitadas is not None:
            set_parts.append("horas_solicitadas = ?")
            params.append(horas_solicitadas)
        if data_evento_norm:
            set_parts.append("data_evento = ?")
            params.append(data_evento_norm)
        if atividade_id_new and atividade_id_new.isdigit():
            set_parts.append("atividade_id = ?")
            params.append(int(atividade_id_new))
        # Atualiza coluna legado se ainda vazia e houve novo anexo
        if rec['arquivo_comprovante'] is None and first_saved:
            set_parts.append("arquivo_comprovante = ?")
            params.append(first_saved)

        if set_parts:
            params.extend([req_id, aluno_id])
            sql = f"UPDATE requisicoes SET {', '.join(set_parts)} WHERE id = ? AND aluno_id = ?"
            try:
                conn.execute(sql, tuple(params))
                conn.commit()
                flash("Requisição atualizada.", "success")
            except Exception as e:
                logger.error(f"Erro ao atualizar requisicao {req_id}: {e}")
                flash("Falha ao atualizar requisição.", "error")
        return redirect(url_for('aluno_requisicao_detalhe', req_id=req_id))

    row = conn.execute(
        """
        SELECT r.*, a.nome AS atividade_nome, a.tipo_atividade, a.grupo
          FROM requisicoes r
          JOIN atividades a ON a.id = r.atividade_id
         WHERE r.id = ? AND r.aluno_id = ?
        """,
        (req_id, aluno_id)
    ).fetchone()
    if not row:
        flash("Requisição não encontrada.", "error")
        return redirect(url_for('aluno_minhas_requisicoes'))

    detalhe = {
        'id': row['id'],
        'atividade_nome': row['atividade_nome'],
        'tipo_atividade': row['tipo_atividade'],
        'grupo': row['grupo'],
        'data_evento': row['data_evento'],
        'data_solicitacao': row['data_solicitacao'],
        'status': row['status'],
        'horas_solicitadas': row['horas_solicitadas'],
        'horas_deferidas': row['horas_deferidas'],
        'observacao': row['observacao'],
        'arquivo_comprovante': row['arquivo_comprovante'],
        'data_processamento': row['data_processamento'],
        # Campo opcional (pode ser NULL em registros antigos)
        'nome_evento': row['nome_evento'] if 'nome_evento' in row.keys() else None
    }
    # Modo edição somente leitura a partir do sticky button (abre o mesmo form de nova requisição, preenchido e bloqueado)
    edit_flag = (request.args.get('edit') or '').strip().lower() in {'1','true','yes','y'}
    view_flag = (request.args.get('view') or '').strip().lower() in {'1','true','yes','y'}
    if edit_flag or view_flag:
        # Carregar atividades e documentos obrigatórios (mesmo da rota nova_requisicao)
        tipo_filtro = detalhe['tipo_atividade'] or 'Acadêmica Complementar'
        try:
            if tipo_filtro == 'Todas':
                atividades = conn.execute("SELECT * FROM atividades ORDER BY tipo_atividade, grupo, nome").fetchall()
            else:
                atividades = conn.execute("SELECT * FROM atividades ORDER BY grupo, nome").fetchall()
        except Exception:
            atividades = conn.execute("SELECT * FROM atividades").fetchall()

        # Mapear documentos obrigatórios por atividade
        docs_por_atividade = {}
        try:
            for a in atividades:
                raw = None
                try:
                    raw = a["documentos_json"] if "documentos_json" in a.keys() else None
                except Exception:
                    raw = None
                docs = parse_documentos_json(raw)
                if docs:
                    docs_por_atividade[a["id"]] = docs
        except Exception:
            pass

        # Preparar iniciais (normalizar data YYYY-MM-DD)
        data_iso10 = ''
        try:
            s = str(detalhe['data_evento'] or '').strip()
            if s:
                # formatos comuns: YYYY-MM-DD[ HH:MM:SS], DD/MM/YYYY
                if '-' in s:
                    data_iso10 = s.split(' ')[0][:10]
                elif '/' in s:
                    # DD/MM/YYYY -> YYYY-MM-DD
                    px = s.split('/')
                    if len(px) >= 3:
                        data_iso10 = f"{px[2]}-{int(px[1]):02d}-{int(px[0]):02d}"
        except Exception:
            data_iso10 = ''
        grupo_raw = detalhe['grupo'] or ''
        grupo_num = grupo_raw.split(' - ')[0].strip() if ' - ' in grupo_raw else grupo_raw.strip()
        init = {
            'tipo_atividade': detalhe['tipo_atividade'],
            'grupo': detalhe['grupo'],
            'grupo_num': grupo_num,
            'atividade_id': row['atividade_id'],
            'nome_evento': row['nome_evento'],
            'horas_solicitadas': detalhe['horas_solicitadas'],
            'data_evento': data_iso10,
            'observacao': detalhe['observacao']
        }
        # Recuperar anexos da requisição (lista de arquivos salvos)
        anexos = []
        try:
            anexos_rows = conn.execute(
                "SELECT id, label, filename, criado_em FROM requisicao_arquivos WHERE requisicao_id = ? ORDER BY id",
                (req_id,)
            ).fetchall()
            for ax in anexos_rows:
                anexos.append({
                    'id': ax['id'],
                    'label': ax['label'] or 'Comprovante',
                    'filename': ax['filename'],
                    'criado_em': ax['criado_em']
                })
        except Exception as _e:
            logger.warning(f"Falha ao carregar anexos da requisicao {req_id}: {_e}")
        return render_template(
            'aluno_nova_requisicao.html',
            atividades=atividades,
            tipo_atual=tipo_filtro,
            docs_por_atividade=docs_por_atividade,
            mode=('view_readonly' if view_flag else 'edit'),
            init=init,
            anexos=anexos
        )

    return render_template('aluno_requisicao_detalhe.html', r=detalhe)

# ===================== Helpers Novos (Cursos/Turmas) =====================

UPPER_CODE_RE = re.compile(r'^[A-Z-]+$')  # letras maiúsculas + hífen (ex.: PPA-NOT)

def validar_codigo_curso(codigo: str) -> bool:
    return bool(UPPER_CODE_RE.fullmatch((codigo or "").strip()))

def semestre_atual_hoje() -> int:
    m = date.today().month
    return 1 if m <= 6 else 2

def periodo_corrente(ano_inicio: int | None, semestre_inicio: int | None, ref: date | None = None) -> int:
    """Período da turma contando a partir do (ano_inicio, semestre_inicio). Começa em 1."""
    if not ano_inicio or not semestre_inicio:
        return 1
    if ref is None:
        ref = date.today()
    sem_ref = 1 if ref.month <= 6 else 2
    delta = (ref.year - int(ano_inicio)) * 2 + (sem_ref - int(semestre_inicio))
    return max(1, delta + 1)

def proximo_numero_turma_por_curso(curso_id: int) -> int:
    row = get_db_connection().execute("SELECT COALESCE(MAX(numero), 0) AS mx FROM turmas WHERE curso_id = ?", (curso_id,)).fetchone()
    return (row["mx"] or 0) + 1

def curso_mais_populoso_id() -> int | None:
    row = get_db_connection().execute("""
        SELECT c.id
        FROM cursos c
        LEFT JOIN turmas t ON t.curso_id = c.id
        LEFT JOIN alunos a ON a.turma_id = t.id
        GROUP BY c.id
        ORDER BY COUNT(a.id) DESC, c.id ASC
        LIMIT 1
    """).fetchone()
    return row["id"] if row else None

def gerar_codigo_turma(curso_codigo: str, numero: int) -> str:
    return f"{curso_codigo}-T{int(numero):02d}"

# ===================== DB Init / Migrações =====================

def init_db():
    conn = get_db_connection()

    # usuarios
    conn.execute("""
    CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        senha TEXT NOT NULL,
        tipo TEXT NOT NULL CHECK(tipo IN ("admin", "aluno"))
    );
    """)
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_usuarios_email ON usuarios(email)")
    except sqlite3.OperationalError:
        pass

    # alunos
    conn.execute("""
    CREATE TABLE IF NOT EXISTS alunos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER UNIQUE,
        nome TEXT NOT NULL,
        matricula TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE,
        turma TEXT,                -- legado (texto)
        turma_id INTEGER,          -- FK opcional para turmas(id)
        foto_perfil TEXT,
        status TEXT DEFAULT 'Ativo' CHECK(status IN ('Ativo', 'Inativo')),
        FOREIGN KEY (usuario_id) REFERENCES usuarios (id)
    );
    """)
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_alunos_usuario_id ON alunos(usuario_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_alunos_matricula ON alunos(matricula)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_alunos_email ON alunos(email)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_alunos_turma_id ON alunos(turma_id)")
    except sqlite3.OperationalError:
        pass

    # turmas (com numero, mantendo nome como legado)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS turmas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL UNIQUE,
        ano INTEGER,
        semestre INTEGER CHECK(semestre IN (1,2)),
        turno TEXT,
        status TEXT NOT NULL DEFAULT 'Ativa' CHECK(status IN ('Ativa','Inativa')),
        numero INTEGER
    );
    """)
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_turmas_status ON turmas(status)")
    except sqlite3.OperationalError:
        pass

    # atividades
    conn.execute("""
    CREATE TABLE IF NOT EXISTS atividades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        grupo TEXT NOT NULL,
        nome TEXT NOT NULL UNIQUE,
        descricao TEXT,
        limite_horas INTEGER,
        tipo_atividade TEXT NOT NULL DEFAULT 'Acadêmica Complementar' CHECK(tipo_atividade IN ('Acadêmica Complementar', 'Extensão Universitária')),
        tem_limitacao BOOLEAN DEFAULT 0,
        tipo_limitacao TEXT CHECK(tipo_limitacao IN ('total', 'semestral')),
        limite_horas_total INTEGER,
        limite_horas_semestral INTEGER
    );
    """)

    # requisicoes
    conn.execute("""
CREATE TABLE IF NOT EXISTS requisicoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    aluno_id INTEGER,
    atividade_id INTEGER NOT NULL,
    data_solicitacao TEXT NOT NULL,
    data_evento TEXT NOT NULL,
    horas_solicitadas REAL NOT NULL,
    nome_evento TEXT,
    status TEXT NOT NULL CHECK(status IN ('Pendente','Deferida','Deferida Parcialmente','Indeferida','Devolvida')),
    horas_deferidas REAL,
    observacao TEXT,
    arquivo_comprovante TEXT,
    data_processamento TEXT,
    admin_id INTEGER,
    aluno_update_notified_at TEXT,
    aluno_update_seen_at TEXT,
    FOREIGN KEY (aluno_id)   REFERENCES alunos(id)   ON DELETE SET NULL ON UPDATE CASCADE,
    FOREIGN KEY (atividade_id) REFERENCES atividades(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    FOREIGN KEY (admin_id)   REFERENCES usuarios(id) ON DELETE SET NULL ON UPDATE CASCADE
);

    """)

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS requisicao_arquivos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            requisicao_id INTEGER NOT NULL,
            label TEXT,
            filename TEXT,
            criado_em TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(requisicao_id) REFERENCES requisicoes(id)
        )
        """
    )

    # Índices para melhorar consultas
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reqs_aluno ON requisicoes(aluno_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reqs_atividade ON requisicoes(atividade_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reqs_status ON requisicoes(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_req_arquivos_req ON requisicao_arquivos(requisicao_id)")
    except sqlite3.OperationalError:
        pass

    # Admin default â€” apenas quando explicitamente habilitado pelo ambiente.
    # IMPORTANTE: a coluna `nivel_acesso` é adicionada por
    # `ensure_usuario_access_schema()` mais abaixo. Para evitar erro em primeira
    # execução, inserimos com colunas básicas e ajustamos o nível depois.
    bootstrap_admin = bool(app.config.get("BOOTSTRAP_DEFAULT_ADMIN"))
    bootstrap_email = (app.config.get("BOOTSTRAP_ADMIN_EMAIL") or "admin@ej.edu.br").strip().lower()
    bootstrap_password = (app.config.get("BOOTSTRAP_ADMIN_PASSWORD") or "").strip()
    admin_exists = conn.execute(
        "SELECT 1 FROM usuarios WHERE LOWER(email) = ?", (bootstrap_email,)
    ).fetchone()
    seeded_admin_email = None
    if not admin_exists and bootstrap_admin and bootstrap_password:
        hashed_password = hash_password(bootstrap_password)
        try:
            conn.execute(
                "INSERT INTO usuarios (nome, email, senha, tipo) VALUES (?, ?, ?, ?)",
                ("Administrador", bootstrap_email, hashed_password, "admin"),
            )
            seeded_admin_email = bootstrap_email
        except sqlite3.IntegrityError:
            # Já existe um registro com este e-mail (corrida ou variação de caixa).
            seeded_admin_email = bootstrap_email
    elif not admin_exists and not bootstrap_admin:
        try:
            logger.warning(
                "Nenhum usuário admin existente e bootstrap automático desabilitado. "
                "Crie um admin manualmente antes do primeiro login produtivo."
            )
        except Exception:
            pass

    ensure_usuario_access_schema(conn)
    ensure_usuario_profile_schema(conn)
    ensure_app_settings_schema(conn)
    ensure_backup_settings_schema(conn)
    ensure_cloud_backup_schema(conn)

    # Após garantir o schema de acesso, marca o admin recém-semeado como admin_total.
    if seeded_admin_email:
        try:
            conn.execute(
                "UPDATE usuarios SET nivel_acesso = 'admin_total' WHERE LOWER(email) = ?",
                (seeded_admin_email,),
            )
        except sqlite3.OperationalError:
            pass

    # Migrações defensivas (atividades)
    try:
        conn.execute("ALTER TABLE atividades ADD COLUMN tipo_atividade TEXT NOT NULL DEFAULT 'Acadêmica Complementar' CHECK(tipo_atividade IN ('Acadêmica Complementar', 'Extensão Universitária'))")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE atividades ADD COLUMN tem_limitacao BOOLEAN DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE atividades ADD COLUMN tipo_limitacao TEXT CHECK(tipo_limitacao IN ('total', 'semestral'))")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE atividades ADD COLUMN limite_horas_total INTEGER")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE atividades ADD COLUMN limite_horas_semestral INTEGER")
    except sqlite3.OperationalError:
        pass
    # documentos obrigatórios por atividade (JSON textual)
    try:
        conn.execute("ALTER TABLE atividades ADD COLUMN documentos_json TEXT")
    except sqlite3.OperationalError:
        pass
    conn.execute("UPDATE atividades SET tipo_atividade = 'Acadêmica Complementar' WHERE tipo_atividade IS NULL OR tipo_atividade = ''")

    # Migração defensiva: garantir turma_id em alunos
    try:
        cols = [row["name"] for row in conn.execute("PRAGMA table_info(alunos)").fetchall()]
        if "turma_id" not in cols:
            conn.execute("ALTER TABLE alunos ADD COLUMN turma_id INTEGER")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_alunos_turma_id ON alunos(turma_id)")
    except sqlite3.OperationalError as e:
        logger.warning(f"Migração turma_id já aplicada ou não necessária: {e}")

    # Migração defensiva: garantir numero em turmas (bancos antigos)
    # Migração defensiva: adicionar nome_evento em requisicoes, se não existir
    try:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(requisicoes)").fetchall()]
        if "nome_evento" not in cols:
            conn.execute("ALTER TABLE requisicoes ADD COLUMN nome_evento TEXT")
    except sqlite3.OperationalError as e:
        logger.warning(f"Migração nome_evento já aplicada ou não necessária: {e}")
    try:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(requisicoes)").fetchall()]
        if "aluno_update_notified_at" not in cols:
            conn.execute("ALTER TABLE requisicoes ADD COLUMN aluno_update_notified_at TEXT")
    except sqlite3.OperationalError as e:
        logger.warning(f"Migração aluno_update_notified_at já aplicada ou não necessária: {e}")
    try:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(requisicoes)").fetchall()]
        if "aluno_update_seen_at" not in cols:
            conn.execute("ALTER TABLE requisicoes ADD COLUMN aluno_update_seen_at TEXT")
    except sqlite3.OperationalError as e:
        logger.warning(f"Migração aluno_update_seen_at já aplicada ou não necessária: {e}")
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reqs_aluno_update_pending ON requisicoes(aluno_id, aluno_update_seen_at, aluno_update_notified_at)")
    except sqlite3.OperationalError:
        pass
    ensure_requisicao_alert_receipts_table(conn)
    try:
        cols_t = [row["name"] for row in conn.execute("PRAGMA table_info(turmas)").fetchall()]
        if "numero" not in cols_t:
            conn.execute("ALTER TABLE turmas ADD COLUMN numero INTEGER")
    except sqlite3.OperationalError as e:
        logger.warning(f"Migração 'numero' já aplicada ou não necessária: {e}")

    # ===== NOVO: cursos =====
    conn.execute("""
    CREATE TABLE IF NOT EXISTS cursos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        codigo TEXT NOT NULL UNIQUE,             -- LETRAS MAIÚSCULAS + HÍFEN
        duracao_periodos INTEGER NOT NULL CHECK(duracao_periodos > 0),
        periodo TEXT NOT NULL DEFAULT 'diurno',  -- diurno | vespertino | noturno | integral
        status TEXT NOT NULL DEFAULT 'ativo' CHECK(status IN ('ativo','inativo'))
    );
    """)

    # Seed: curso GERAL (para amarrar turmas antigas, se necessário)
    # Migração defensiva: adicionar coluna periodo em bancos antigos
    try:
        cols_c = [row[1] if isinstance(row, tuple) else row["name"] for row in conn.execute("PRAGMA table_info(cursos)").fetchall()]
        if "periodo" not in cols_c:
            conn.execute("ALTER TABLE cursos ADD COLUMN periodo TEXT DEFAULT 'diurno'")
    except sqlite3.OperationalError:
        pass

    existe_curso = conn.execute("SELECT 1 FROM cursos LIMIT 1").fetchone()
    if not existe_curso:
        conn.execute(
            "INSERT INTO cursos (nome, codigo, duracao_periodos, status) VALUES (?,?,?,?)",
            ("Geral", "GERAL", 8, "ativo")
        )

    # NOVAS colunas em turmas
    try:
        cols_t = [row["name"] for row in conn.execute("PRAGMA table_info(turmas)").fetchall()]
        if "curso_id" not in cols_t:
            conn.execute("ALTER TABLE turmas ADD COLUMN curso_id INTEGER")
    except sqlite3.OperationalError:
        pass
    try:
        cols_t = [row["name"] for row in conn.execute("PRAGMA table_info(turmas)").fetchall()]
        if "ano_inicio" not in cols_t:
            conn.execute("ALTER TABLE turmas ADD COLUMN ano_inicio INTEGER")
    except sqlite3.OperationalError:
        pass
    try:
        cols_t = [row["name"] for row in conn.execute("PRAGMA table_info(turmas)").fetchall()]
        if "semestre_inicio" not in cols_t:
            conn.execute("ALTER TABLE turmas ADD COLUMN semestre_inicio INTEGER")
    except sqlite3.OperationalError:
        pass
    try:
        cols_t = [row["name"] for row in conn.execute("PRAGMA table_info(turmas)").fetchall()]
        if "codigo" not in cols_t:
            conn.execute("ALTER TABLE turmas ADD COLUMN codigo TEXT")
    except sqlite3.OperationalError:
        pass
    ensure_turmas_matriz_schema(conn)
    ensure_matriz_atividade_links_table(conn)
    ensure_atividade_versioning_schema(conn)

    # Migração defensiva: adicionar período final (ano_fim, semestre_fim) em turmas
    try:
        cols_t = [row["name"] for row in conn.execute("PRAGMA table_info(turmas)").fetchall()]
        if "ano_fim" not in cols_t:
            conn.execute("ALTER TABLE turmas ADD COLUMN ano_fim INTEGER")
    except sqlite3.OperationalError as e:
        logger.warning(f"Migração 'ano_fim' já aplicada ou não necessária: {e}")
    try:
        cols_t = [row["name"] for row in conn.execute("PRAGMA table_info(turmas)").fetchall()]
        if "semestre_fim" not in cols_t:
            conn.execute("ALTER TABLE turmas ADD COLUMN semestre_fim INTEGER")
    except sqlite3.OperationalError as e:
        logger.warning(f"Migração 'semestre_fim' já aplicada ou não necessária: {e}")

    # Índices/constraints novas
    conn.execute("CREATE INDEX IF NOT EXISTS idx_turmas_curso ON turmas(curso_id);")
    try:
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_turma_por_curso ON turmas(curso_id, numero);")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_turma_codigo ON turmas(codigo);")
    except sqlite3.OperationalError:
        pass

    # Popular curso_id/codigo para turmas antigas
    try:
        geral = conn.execute("SELECT id, codigo FROM cursos WHERE codigo='GERAL'").fetchone()
        if geral:
            conn.execute("UPDATE turmas SET curso_id = ? WHERE curso_id IS NULL OR curso_id = 0", (geral["id"],))
            # numero vazio -> dar números sequenciais simples (em Python para evitar dependências)
            turmas_sem_num = conn.execute("SELECT id FROM turmas WHERE numero IS NULL OR numero = 0 ORDER BY id").fetchall()
            if turmas_sem_num:
                maxnum = conn.execute("SELECT COALESCE(MAX(numero),0) AS mx FROM turmas").fetchone()["mx"] or 0
                n = int(maxnum)
                for r in turmas_sem_num:
                    n += 1
                    conn.execute("UPDATE turmas SET numero=? WHERE id=?", (n, r["id"]))
            # gerar códigos faltantes para GERAL
            turmas_sem_cod = conn.execute("SELECT id, numero FROM turmas WHERE (codigo IS NULL OR codigo='')").fetchall()
            for t in turmas_sem_cod:
                cod = gerar_codigo_turma(geral["codigo"], t["numero"])
                try:
                    conn.execute("UPDATE turmas SET codigo=? WHERE id=?", (cod, t["id"]))
                except sqlite3.IntegrityError:
                    # se por algum motivo colidir, acrescenta sufixo
                    cod2 = f"{cod}-{t['id']}"
                    conn.execute("UPDATE turmas SET codigo=? WHERE id=?", (cod2, t["id"]))
    except Exception as e:
        logger.warning(f"População inicial de curso_id/codigo em turmas antigas: {e}")

    apply_schema_migrations(conn, logger=logger)
    conn.commit()

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


@app.route("/admin/configuracoes")
@admin_required
def admin_configuracoes():
    conn = get_db_connection()
    return render_template(
        "admin_configuracoes.html",
        response_settings=get_response_time_settings(conn),
        horas_settings=get_horas_settings(conn),
    )


@app.route("/admin/mensagens")
@admin_required
def admin_mensagens():
    conn = get_db_connection()
    messages = list_editable_messages(conn)
    return render_template(
        "admin_mensagens.html",
        messages=messages,
        total_messages=len(messages),
        overridden_messages=sum(1 for item in messages if item["is_overridden"]),
    )


@app.route("/admin/mensagens/salvar", methods=["POST"])
@admin_required
def admin_mensagens_salvar():
    conn = get_db_connection()
    try:
        save_message_override(
            conn,
            request.form.get("message_key") or "",
            request.form.get("message_text") or "",
        )
        conn.commit()
    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "error")
        return redirect(url_for("admin_mensagens"))
    flash("Mensagem atualizada com sucesso.", "success")
    return redirect(url_for("admin_mensagens"))


@app.route("/admin/mensagens/<message_key>/reset", methods=["POST"])
@admin_required
def admin_mensagens_resetar(message_key: str):
    conn = get_db_connection()
    try:
        reset_message_override(conn, message_key)
        conn.commit()
    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "error")
        return redirect(url_for("admin_mensagens"))
    flash("Mensagem restaurada para o padrão.", "success")
    return redirect(url_for("admin_mensagens"))


@app.route("/admin/configuracoes/tempo-resposta", methods=["POST"])
@admin_required
def admin_configuracoes_tempo_resposta_salvar():
    conn = get_db_connection()
    try:
        save_app_settings(
            conn,
            {
                "response_goal_days": request.form.get("response_goal_days") or str(DEFAULT_RESPONSE_GOAL_DAYS),
                "response_metrics_reset_at": request.form.get("response_metrics_reset_at") or "",
            },
        )
        conn.commit()
    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "error")
        return redirect(url_for("admin_configuracoes"))
    flash("Configurações de tempo de resposta atualizadas com sucesso.", "success")
    return redirect(url_for("admin_configuracoes"))


@app.route("/admin/configuracoes/tempo-resposta/reset", methods=["POST"])
@admin_required
def admin_configuracoes_tempo_resposta_resetar():
    conn = get_db_connection()
    reset_response_time_metrics(conn)
    conn.commit()
    flash("Apuração do tempo de resposta reiniciada a partir de hoje.", "success")
    return redirect(url_for("admin_configuracoes"))


@app.route("/admin/configuracoes/prazo-adequacao", methods=["POST"])
@admin_required
def admin_configuracoes_prazo_adequacao_salvar():
    conn = get_db_connection()
    try:
        save_return_response_settings(
            conn,
            {
                "return_response_days": request.form.get("return_response_days") or str(DEFAULT_RETURN_RESPONSE_DAYS),
                "auto_indefer_devolvida": request.form.get("auto_indefer_devolvida") or "0",
            },
        )
        conn.commit()
    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "error")
        return redirect(url_for("admin_configuracoes"))
    flash("Prazo de adequação de solicitações devolvidas atualizado com sucesso.", "success")
    return redirect(url_for("admin_configuracoes"))


@app.route("/admin/configuracoes/horas-padrao", methods=["POST"])
@admin_required
def admin_configuracoes_horas_padrao_salvar():
    conn = get_db_connection()
    try:
        save_horas_settings(
            conn,
            {
                "horas_padrao_academica": request.form.get("horas_padrao_academica") or str(DEFAULT_HORAS_ACADEMICA),
                "horas_padrao_extensao": request.form.get("horas_padrao_extensao") or str(DEFAULT_HORAS_EXTENSAO),
            },
        )
        conn.commit()
    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "error")
        return redirect(url_for("admin_configuracoes"))
    flash("Padrão de horas atualizado com sucesso.", "success")
    return redirect(url_for("admin_configuracoes"))

# Demo: clientes-form pack (visual)
@app.route("/admin/demo/clientes-form-pack")
@admin_required
def admin_demo_clientes_form_pack():
    return render_template("demo_clientes_form_pack.html")

# ===================== Rotas Admin: Cursos (NOVO) =====================

@app.route("/admin/cursos")
@admin_required
def admin_cursos():
    """Lista de cursos com totais de turmas/alunos.
    Backend-only: adiciona paginação opcional, sem alterar UI por padrão.
    """
    page, per_page, offset = get_pagination(default_per_page=25)
    sort_field = (request.args.get("s") or "nome").strip().lower()
    sort_dir = (request.args.get("dir") or "asc").strip().lower()
    status_filters = [value.strip().lower() for value in get_multi_query_values("status") if value.strip()]
    codigo_filter = get_text_query_value("codigo")
    nome_filter = get_text_query_value("nome")
    duracao_min, duracao_max = get_number_range_query("duracao_periodos")
    qtd_turmas_min, qtd_turmas_max = get_number_range_query("qtd_turmas")
    qtd_alunos_min, qtd_alunos_max = get_number_range_query("qtd_alunos")
    conn = get_db_connection()
    base_from = (
        " FROM cursos c"
        " LEFT JOIN turmas t ON t.curso_id = c.id"
        " LEFT JOIN alunos a ON a.turma_id = t.id"
    )
    select_cols = (
        "SELECT c.*, COUNT(DISTINCT t.id) AS qtd_turmas, COUNT(a.id) AS qtd_alunos"
    )
    where = []
    params = []
    append_text_contains_condition(where, params, "c.codigo", codigo_filter)
    append_text_contains_condition(where, params, "c.nome", nome_filter)
    if status_filters:
        placeholders = ", ".join("?" for _ in status_filters)
        where.append(f"LOWER(COALESCE(c.status, '')) IN ({placeholders})")
        params.extend(status_filters)
    if duracao_min is not None:
        where.append("COALESCE(c.duracao_periodos, 0) >= ?")
        params.append(duracao_min)
    if duracao_max is not None:
        where.append("COALESCE(c.duracao_periodos, 0) <= ?")
        params.append(duracao_max)

    having = []
    having_params = []
    if qtd_turmas_min is not None:
        having.append("COUNT(DISTINCT t.id) >= ?")
        having_params.append(qtd_turmas_min)
    if qtd_turmas_max is not None:
        having.append("COUNT(DISTINCT t.id) <= ?")
        having_params.append(qtd_turmas_max)
    if qtd_alunos_min is not None:
        having.append("COUNT(a.id) >= ?")
        having_params.append(qtd_alunos_min)
    if qtd_alunos_max is not None:
        having.append("COUNT(a.id) <= ?")
        having_params.append(qtd_alunos_max)

    where_sql = append_conditions_sql(False, where)
    order_map = {
        "codigo": "LOWER(COALESCE(c.codigo, ''))",
        "nome": "LOWER(COALESCE(c.nome, ''))",
        "duracao_periodos": "COALESCE(c.duracao_periodos, 0)",
        "status": "LOWER(COALESCE(c.status, ''))",
    }
    order_sql = order_map.get(sort_field, order_map["nome"])
    direction = "DESC" if sort_dir == "desc" else "ASC"

    having_sql = (" HAVING " + " AND ".join(having)) if having else ""
    grouped_sql = base_from + where_sql + " GROUP BY c.id" + having_sql
    query = select_cols + grouped_sql + f" ORDER BY {order_sql} {direction}, c.id ASC"
    count_sql = "SELECT COUNT(*) FROM (SELECT c.id" + grouped_sql + ") cursos_filtrados"
    total = conn.execute(count_sql, params + having_params).fetchone()[0]
    apply_limit = wants_pagination()
    params_exec = list(params) + list(having_params)
    if apply_limit:
        query += " LIMIT ? OFFSET ?"
        params_exec += [per_page, offset]
    cursos = conn.execute(query, params_exec).fetchall()
    total_pages = (total + per_page - 1) // per_page if apply_limit and per_page else 1
    filter_schema = [
        {
            "param": "codigo",
            "label": "Código",
            "type": "text_contains",
            "placeholder": "Contém no código",
        },
        {
            "param": "nome",
            "label": "Nome",
            "type": "text_contains",
            "placeholder": "Contém no nome",
        },
        {
            "param": "duracao_periodos",
            "label": "Duração",
            "type": "number_range",
            "min_label": "Mínimo",
            "max_label": "Máximo",
        },
        {
            "param": "qtd_turmas",
            "label": "Turmas",
            "type": "number_range",
            "min_label": "Mínimo",
            "max_label": "Máximo",
        },
        {
            "param": "qtd_alunos",
            "label": "Alunos",
            "type": "number_range",
            "min_label": "Mínimo",
            "max_label": "Máximo",
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
    return render_template(
        "admin_cursos.html",
        cursos=cursos,
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages,
        filter_schema=filter_schema,
    )

@app.route("/admin/cursos/adicionar", methods=["GET", "POST"])
@admin_required
def admin_adicionar_curso():
    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        codigo = (request.form.get("codigo") or "").strip().upper()
        duracao_periodos = request.form.get("duracao_periodos", type=int)
        status = request.form.get("status", "ativo")

        if not nome:
            flash("Nome do curso é obrigatório.", "error")
            return redirect(url_for("admin_adicionar_curso"))
        if not validar_codigo_curso(codigo):
            flash("Código do curso deve conter apenas letras maiúsculas e hífen (A-Z e -).", "error")
            return redirect(url_for("admin_adicionar_curso"))
        if not duracao_periodos or duracao_periodos <= 0:
            flash("Duração em períodos deve ser maior que zero.", "error")
            return redirect(url_for("admin_adicionar_curso"))

        conn = get_db_connection()
        try:
            # Não recebemos mais 'periodo' via formulário; usar default do banco
            conn.execute(
                """
                INSERT INTO cursos (nome, codigo, duracao_periodos, status)
                VALUES (?,?,?,?)
                """,
                (nome, codigo, duracao_periodos, status)
            )
            conn.commit()
            flash("Curso criado com sucesso.", "success")
            return redirect(url_for("admin_cursos"))
        except sqlite3.IntegrityError as e:
            if "UNIQUE constraint failed: cursos.codigo" in str(e):
                flash("Já existe um curso com este código.", "error")
            else:
                flash(f"Erro ao criar curso: {e}", "error")
    return render_template("admin_adicionar_curso.html")

@app.route("/admin/cursos/<int:curso_id>/editar", methods=["GET", "POST"])
@admin_required
def admin_editar_curso(curso_id):
    conn = get_db_connection()
    curso = conn.execute("SELECT * FROM cursos WHERE id=?", (curso_id,)).fetchone()
    if not curso:
        flash("Curso não encontrado.", "error")
        return redirect(url_for("admin_cursos"))

    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        codigo_novo = (request.form.get("codigo") or "").strip().upper()
        duracao_periodos = request.form.get("duracao_periodos", type=int)
        status = request.form.get("status", "ativo")

        if not nome:
            flash("Nome do curso é obrigatório.", "error")
            return redirect(url_for("admin_editar_curso", curso_id=curso_id))
        if not validar_codigo_curso(codigo_novo):
            flash("Código do curso deve conter apenas letras maiúsculas e hífen.", "error")
            return redirect(url_for("admin_editar_curso", curso_id=curso_id))
        if not duracao_periodos or duracao_periodos <= 0:
            flash("Duração em períodos deve ser maior que zero.", "error")
            return redirect(url_for("admin_editar_curso", curso_id=curso_id))

        try:
            codigo_antigo = curso["codigo"]
            # Não alteramos mais 'periodo' em edição
            conn.execute(
                """
                UPDATE cursos SET nome=?, codigo=?, duracao_periodos=?, status=? WHERE id=?
                """,
                (nome, codigo_novo, duracao_periodos, status, curso_id)
            )

            # Regerar codigos de turmas vinculadas se o código do curso mudou
            if codigo_novo != codigo_antigo:
                turmas = conn.execute("SELECT id, numero FROM turmas WHERE curso_id=?", (curso_id,)).fetchall()
                for t in turmas:
                    novo = gerar_codigo_turma(codigo_novo, t["numero"])
                    try:
                        conn.execute("UPDATE turmas SET codigo=? WHERE id=?", (novo, t["id"]))
                    except sqlite3.IntegrityError:
                        # evitar colisão improvável
                        conn.execute("UPDATE turmas SET codigo=? WHERE id=?", (f"{novo}-{t['id']}", t["id"]))
            conn.commit()
            flash("Curso atualizado com sucesso.", "success")
            return redirect(url_for("admin_cursos"))
        except sqlite3.IntegrityError as e:
            if "UNIQUE constraint failed: cursos.codigo" in str(e):
                flash("Já existe um curso com este código.", "error")
            else:
                flash(f"Erro ao atualizar curso: {e}", "error")

    return render_template("admin_editar_curso.html", curso=curso)

@app.route("/admin/cursos/<int:curso_id>")
@admin_required
def admin_detalhes_curso(curso_id):
    conn = get_db_connection()
    curso = conn.execute("SELECT * FROM cursos WHERE id=?", (curso_id,)).fetchone()
    if not curso:
        flash("Curso não encontrado.", "error")
        return redirect(url_for("admin_cursos"))

    turmas = conn.execute("""
        SELECT t.*,
               COUNT(a.id) AS qtd_alunos
          FROM turmas t
     LEFT JOIN alunos a ON a.turma_id = t.id
         WHERE t.curso_id = ?
      GROUP BY t.id
      ORDER BY t.numero
    """, (curso_id,)).fetchall()

    return render_template("admin_detalhes_curso.html", curso=curso, turmas=turmas, periodo_corrente=periodo_corrente)


@app.route("/admin/cursos/<int:curso_id>/visualizar")
@admin_required
def admin_visualizar_curso(curso_id):
    return redirect(url_for("admin_detalhes_curso", curso_id=curso_id))


# ===================== Rotas Admin: Arquivos (NOVO) =====================

def _redirect_admin_arquivos_return(default_endpoint: str = "admin_arquivos", **values):
    return_to = (request.form.get("return_to") or request.args.get("return_to") or "").strip()
    if return_to:
        return redirect(return_to)
    return redirect(url_for(default_endpoint, **values))


def _safe_return_to_target(default_endpoint: str, **values) -> str:
    return_to = (request.form.get("return_to") or request.args.get("return_to") or "").strip()
    if return_to:
        parsed = urlsplit(return_to)
        if not parsed.scheme and not parsed.netloc and return_to.startswith("/") and not return_to.startswith("//"):
            return return_to
    return url_for(default_endpoint, **values)


def _is_ajax_request() -> bool:
    return request.headers.get("X-Requested-With", "").lower() == "xmlhttprequest"


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

@app.route("/admin/deletar_curso/<int:curso_id>", methods=["POST"])
@admin_required
def admin_deletar_curso(curso_id):
    conn = get_db_connection()
    try:
        # Se houver FK/ON, o SQLite impedirá excluir com turmas vinculadas.
        conn.execute("DELETE FROM cursos WHERE id = ?", (curso_id,))
        conn.commit()
        flash("Curso excluído com sucesso.", "success")
    except Exception as e:
        flash(f"Erro ao excluir curso: {e}", "error")
    return redirect(url_for("admin_cursos"))

# ===================== Rotas Admin: Importar requisições =====================

@app.route("/admin/importar_requisicoes", methods=["GET", "POST"])
@admin_required
def admin_importar_requisicoes():
    if request.method == "POST":
        usar_padrao = "usar_arquivo_padrao" in request.form
        arquivo_selecionado = request.files.get("arquivo_excel")

        arquivo_path = None
        if usar_padrao:
            arquivo_path = os.path.join(app.config["UPLOAD_FOLDER"], "Acompanhamento de atividades complementares.xlsx")
            if not os.path.exists(arquivo_path):
                flash("Arquivo padrão não encontrado na pasta de uploads.", "error")
                return render_template("admin_importar_requisicoes.html")
        elif arquivo_selecionado and arquivo_selecionado.filename != "":
            if not _allowed(arquivo_selecionado.filename, ALLOWED_EXCEL):
                flash("Envie um arquivo .xlsx válido.", "error")
                return render_template("admin_importar_requisicoes.html")
            filename = save_upload(arquivo_selecionado, ALLOWED_EXCEL, prefix="import", subdir="imports")
            arquivo_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        else:
            flash("Nenhum arquivo selecionado.", "error")
            return render_template("admin_importar_requisicoes.html")

        try:
            logger.info(f"Iniciando importação do arquivo: {arquivo_path} usando openpyxl")
            workbook = openpyxl.load_workbook(arquivo_path, data_only=True)
            if "Requisições" not in workbook.sheetnames:
                flash("Aba 'Requisições' não encontrada na planilha.", "error")
                logger.error(f"Aba 'Requisições' não encontrada em {arquivo_path}")
                return render_template("admin_importar_requisicoes.html")

            sheet = workbook["Requisições"]
            logger.info(f"Planilha 'Requisições' lida. Total de linhas: {sheet.max_row}")

            conn = get_db_connection()
            sucesso_count = 0
            erro_count = 0
            erros_detalhes = []

            atividades_map = {normalize_header(row["nome"]): row["id"] for row in conn.execute("SELECT id, nome FROM atividades").fetchall()}
            logger.info(f"Cache de atividades criado: {len(atividades_map)} atividades.")

            data_solicitacao_hoje = datetime.date.today().strftime("%Y-%m-%d")

            for row_index in range(3, sheet.max_row + 1):
                try:
                    nome_atividade_raw = sheet.cell(row=row_index, column=6).value
                    data_evento_raw = sheet.cell(row=row_index, column=8).value
                    horas_raw = sheet.cell(row=row_index, column=7).value
                    status_raw = sheet.cell(row=row_index, column=9).value

                    if nome_atividade_raw is None or data_evento_raw is None or horas_raw is None:
                        logger.warning(f"Linha {row_index}: dados essenciais ausentes, pulando.")
                        continue
                    if all(sheet.cell(row=row_index, column=c).value is None for c in range(1, sheet.max_column + 1)):
                        logger.info(f"Linha {row_index}: linha vazia, pulando.")
                        continue

                    aluno_id = None
                    nome_atividade_norm = normalize_header(str(nome_atividade_raw))
                    atividade_id = atividades_map.get(nome_atividade_norm)
                    if not atividade_id:
                        logger.warning(f"Linha {row_index}: Atividade '{nome_atividade_raw}' não encontrada")
                        erro_count += 1
                        erros_detalhes.append(f"Linha {row_index}: Atividade '{nome_atividade_raw}' não encontrada")
                        continue

                    data_evento = "Indisponível"
                    if isinstance(data_evento_raw, datetime.datetime):
                        data_evento = data_evento_raw.strftime("%Y-%m-%d")
                    elif data_evento_raw is not None:
                        try:
                            if isinstance(data_evento_raw, (int, float)):
                                data_evento_dt = openpyxl.utils.datetime.from_excel(data_evento_raw)
                                data_evento = data_evento_dt.strftime("%Y-%m-%d")
                            else:
                                data_evento_dt = datetime.datetime.strptime(str(data_evento_raw).split()[0], '%Y-%m-%d')
                                data_evento = data_evento_dt.strftime("%Y-%m-%d")
                        except (ValueError, TypeError) as e_date:
                            logger.warning(f"Linha {row_index}: data inválida '{data_evento_raw}'. {e_date}")

                    horas_solicitadas = 0.0
                    horas_deferidas = None
                    if horas_raw is not None:
                        try:
                            horas_solicitadas = float(horas_raw)
                        except (ValueError, TypeError) as e_horas:
                            logger.warning(f"Linha {row_index}: horas inválidas '{horas_raw}'. {e_horas}")
                    else:
                        logger.warning(f"Linha {row_index}: horas ausentes, usando 0.0.")

                    status = "Pendente"
                    if status_raw is not None:
                        status_norm = normalize_header(str(status_raw))
                        if status_norm == "deferido":
                            status = "Deferida"
                            horas_deferidas = horas_solicitadas
                        elif status_norm == "deferido parcialmente":
                            status = "Deferida Parcialmente"
                            horas_deferidas = 0.0
                        elif status_norm == "indeferido":
                            status = "Indeferida"
                            horas_deferidas = 0.0

                    conn.execute("""
                        INSERT INTO requisicoes 
                        (aluno_id, atividade_id, data_solicitacao, data_evento, horas_solicitadas, status, horas_deferidas, observacao)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (aluno_id, atividade_id, data_solicitacao_hoje, data_evento, horas_solicitadas, status, horas_deferidas, f"Importado da planilha linha {row_index}"))
                    sucesso_count += 1

                except Exception as e:
                    logger.error(f"Erro ao processar linha {row_index}: {e}")
                    traceback.print_exc()
                    erro_count += 1
                    erros_detalhes.append(f"Linha {row_index}: Erro inesperado - {e}")

            conn.commit()
            logger.info(f"Importação concluída. Sucesso: {sucesso_count}, Erros/Pulados: {erro_count}")

            flash(f"{sucesso_count} requisições importadas com sucesso.", "success")
            if erro_count > 0:
                flash(f"{erro_count} linhas não puderam ser importadas ou foram puladas. Veja app.log para detalhes.", "warning")

            return redirect(url_for("admin_requisicoes"))

        except FileNotFoundError:
            logger.error(f"Arquivo não encontrado: {arquivo_path}")
            flash(f"Erro: Arquivo não encontrado em {arquivo_path}", "error")
            return render_template("admin_importar_requisicoes.html")
        except Exception as e:
            logger.error(f"Erro GERAL durante a importação: {e}")
            traceback.print_exc()
            flash(f"Ocorreu um erro grave durante a importação: {e}", "error")
            return render_template("admin_importar_requisicoes.html")

    return render_template("admin_importar_requisicoes.html")

# ===================== Rotas Admin: Requisições =====================

def _normalize_requisicao_data_evento(value):
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if "/" in raw:
        parts = raw.split("/")
        if len(parts) >= 3:
            try:
                return f"{parts[2]}-{int(parts[1]):02d}-{int(parts[0]):02d}"
            except Exception:
                return None
        return None
    if "-" in raw:
        return raw.split(" ")[0][:10]
    return None

def _get_admin_requisicao_scope_for_aluno(conn, aluno_id):
    ensure_turmas_matriz_schema(conn)
    ensure_matriz_atividade_links_table(conn)
    row = conn.execute(
        """
        SELECT a.id, a.nome, a.matricula, a.turma_id,
               t.nome AS turma_nome, t.codigo AS turma_codigo,
               t.curso_id, t.matriz_id AS turma_matriz_id
          FROM alunos a
          LEFT JOIN turmas t ON t.id = a.turma_id
         WHERE a.id = ?
        """,
        (aluno_id,),
    ).fetchone()
    if not row:
        return None
    allowed_activity_ids, matriz = get_allowed_activity_ids_for_turma_matrix(
        conn,
        row["curso_id"],
        row["turma_matriz_id"],
    )
    turma_label = row["turma_codigo"] or row["turma_nome"] or "Sem turma"
    return {
        "aluno": row,
        "allowed_activity_ids": sorted(allowed_activity_ids) if allowed_activity_ids is not None else None,
        "matriz_scope": ({"id": matriz["id"], "label": _matriz_option_label(matriz)} if matriz else None),
        "turma_label": turma_label,
    }

def _list_admin_requisicao_alunos(conn):
    ensure_turmas_matriz_schema(conn)
    return conn.execute(
        """
        SELECT a.id, a.nome, a.matricula,
               COALESCE(t.codigo, t.nome, 'Sem turma') AS turma_label
          FROM alunos a
          LEFT JOIN turmas t ON t.id = a.turma_id
         ORDER BY a.nome COLLATE NOCASE, a.id
        """
    ).fetchall()

def _append_requisicao_arquivos(conn, req_id, aluno_id, arquivos, labels=None):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS requisicao_arquivos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            requisicao_id INTEGER NOT NULL,
            label TEXT,
            filename TEXT,
            criado_em TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(requisicao_id) REFERENCES requisicoes(id)
        )
        """
    )
    first_saved = None
    labels = labels or []
    aluno_row = conn.execute("SELECT nome FROM alunos WHERE id = ?", (aluno_id,)).fetchone()
    student_name = str((aluno_row["nome"] if aluno_row else "") or f"aluno-{aluno_id}")
    for idx, arquivo in enumerate(arquivos or []):
        if not arquivo or not getattr(arquivo, "filename", ""):
            continue
        if not _allowed(arquivo.filename, ALLOWED_ATTACHMENTS):
            flash(f"Arquivo ignorado por extensão não permitida: {arquivo.filename}", "warning")
            continue
        try:
            saved = save_student_document(
                arquivo,
                ALLOWED_ATTACHMENTS,
                root_folder=app.config["DOCUMENTOS_ALUNOS_FOLDER"],
                student_id=aluno_id,
                student_name=student_name,
                category="requisicoes",
                prefix=f"req{req_id}",
            )
            if saved:
                if first_saved is None:
                    first_saved = saved
                label_value = labels[idx] if labels and idx < len(labels) else None
                conn.execute(
                    "INSERT INTO requisicao_arquivos (requisicao_id, label, filename) VALUES (?, ?, ?)",
                    (req_id, label_value, saved),
                )
        except Exception as exc:
            logger.error(f"Falha ao salvar arquivo de comprovante na requisição {req_id}: {exc}")
    return first_saved

@app.route("/admin/requisicoes")
@admin_required
def admin_requisicoes():
    page, per_page, offset = get_pagination(default_per_page=25)
    status_filters = {item.strip().lower() for item in get_multi_query_values("status") if item.strip()}
    processamento_filters = {
        item.strip().lower()
        for item in get_multi_query_values("processamento")
        if item.strip().lower() in {"com_data", "sem_data"}
    }
    aluno_filters = [item for item in get_multi_query_values("aluno") if item]
    turma_filters = [item for item in get_multi_query_values("turma") if item]
    tipo_filters = [item for item in get_multi_query_values("tipo") if item]
    grupo_filters = [item for item in get_multi_query_values("grupo") if item]
    atividade_filters = [item for item in get_multi_query_values("atividade") if item]
    data_solicitacao_min, data_solicitacao_max = get_date_range_query("data_solicitacao")
    data_processamento_min, data_processamento_max = get_date_range_query("data_processamento")
    status_filtro = next(iter(status_filters), 'Todas') if status_filters else 'Todas'
    q = (request.args.get('q') or '').strip()
    sort_field = (request.args.get('s') or 'data_solicitacao').strip()
    sort_dir = (request.args.get('dir') or 'desc').strip().lower()
    conn = get_db_connection()
    auto_indefer_devolvidas(conn)
    ensure_turmas_matriz_schema(conn)
    ensure_matriz_atividade_links_table(conn)
    base_from = """
        FROM requisicoes r
        LEFT JOIN alunos a ON r.aluno_id = a.id
        LEFT JOIN turmas t ON t.id = a.turma_id
        JOIN atividades act ON r.atividade_id = act.id
    """
    select_cols = """
        SELECT r.*, 
               a.nome              AS aluno_nome,
               a.matricula         AS aluno_matricula,
               COALESCE(t.codigo, t.nome, a.turma) AS turma_codigo,
               t.curso_id          AS turma_curso_id,
               t.matriz_id         AS turma_matriz_id,
               act.nome            AS atividade_nome,
               act.grupo           AS grupo,
               act.tipo_atividade  AS tipo_atividade
    """
    query = select_cols + base_from
    params = []
    where = []
    if aluno_filters:
        placeholders = ", ".join("?" for _ in aluno_filters)
        where.append(f"COALESCE(TRIM(a.nome), '') IN ({placeholders})")
        params.extend(aluno_filters)
    if turma_filters:
        placeholders = ", ".join("?" for _ in turma_filters)
        where.append(f"COALESCE(TRIM(COALESCE(t.codigo, t.nome, a.turma)), '') IN ({placeholders})")
        params.extend(turma_filters)
    if tipo_filters:
        placeholders = ", ".join("?" for _ in tipo_filters)
        where.append(f"COALESCE(TRIM(act.tipo_atividade), '') IN ({placeholders})")
        params.extend(tipo_filters)
    if grupo_filters:
        placeholders = ", ".join("?" for _ in grupo_filters)
        where.append(f"COALESCE(TRIM(act.grupo), '') IN ({placeholders})")
        params.extend(grupo_filters)
    if atividade_filters:
        placeholders = ", ".join("?" for _ in atividade_filters)
        where.append(f"COALESCE(TRIM(act.nome), '') IN ({placeholders})")
        params.extend(atividade_filters)
    if data_solicitacao_min:
        where.append("date(r.data_solicitacao) >= date(?)")
        params.append(data_solicitacao_min)
    if data_solicitacao_max:
        where.append("date(r.data_solicitacao) <= date(?)")
        params.append(data_solicitacao_max)
    if data_processamento_min:
        where.append("date(r.data_processamento) >= date(?)")
        params.append(data_processamento_min)
    if data_processamento_max:
        where.append("date(r.data_processamento) <= date(?)")
        params.append(data_processamento_max)
    if processamento_filters:
        processamento_clauses = []
        if "com_data" in processamento_filters:
            processamento_clauses.append("(r.data_processamento IS NOT NULL AND TRIM(r.data_processamento) <> '')")
        if "sem_data" in processamento_filters:
            processamento_clauses.append("(r.data_processamento IS NULL OR TRIM(r.data_processamento) = '')")
        if processamento_clauses:
            where.append("(" + " OR ".join(processamento_clauses) + ")")
    if status_filters:
        status_clauses = []
        for status_filter in status_filters:
            if status_filter == 'pendente':
                status_clauses.append("LOWER(COALESCE(r.status, '')) IN ('pendente', 'aguardando', 'pending')")
            elif status_filter == 'deferida':
                status_clauses.append("LOWER(COALESCE(r.status, '')) IN ('deferido', 'deferida', 'aprovado', 'aprovada', 'approved')")
            elif status_filter == 'deferida_parcialmente':
                status_clauses.append("LOWER(COALESCE(r.status, '')) IN ('deferida parcialmente', 'deferido parcialmente', 'parcialmente deferida', 'partially approved')")
            elif status_filter == 'indeferida':
                status_clauses.append("LOWER(COALESCE(r.status, '')) IN ('indeferido', 'indeferida', 'rejeitado', 'rejeitada')")
            elif status_filter == 'devolvida':
                status_clauses.append("LOWER(COALESCE(r.status, '')) IN ('devolvido', 'devolvida')")
            elif status_filter == 'encerrada':
                status_clauses.append("LOWER(COALESCE(r.status, '')) IN ('encerrado', 'encerrada', 'closed')")
            else:
                status_clauses.append("LOWER(COALESCE(r.status, '')) = ?")
                params.append(status_filter)
        if status_clauses:
            where.append("(" + " OR ".join(status_clauses) + ")")
    if q:
        like = f"%{q}%"
        where.append("(a.nome LIKE ? OR a.matricula LIKE ? OR a.turma LIKE ? OR act.nome LIKE ? OR act.grupo LIKE ? OR act.tipo_atividade LIKE ? OR r.status LIKE ?)")
        params.extend([like, like, like, like, like, like, like])
    where_sql = append_conditions_sql(False, where)
    query += where_sql
    # Ordenação (whitelist para segurança)
    order_map = {
        'data_solicitacao': 'r.data_solicitacao',
        'data_processamento': 'r.data_processamento',
        'aluno_nome': 'a.nome',
        'turma_codigo': 'a.turma',
        'tipo_atividade': 'act.tipo_atividade',
        'grupo': 'act.grupo',
        'atividade_nome': 'act.nome',
        'status': 'r.status'
    }
    col = order_map.get(sort_field, 'r.data_solicitacao')
    direction = 'DESC' if sort_dir == 'desc' else 'ASC'
    query += f" ORDER BY {col} {direction}"

    # total para paginação (conta sem ORDER BY)
    count_sql = "SELECT COUNT(*) " + base_from + where_sql
    total = conn.execute(count_sql, params).fetchone()[0]

    # Só aplica LIMIT/OFFSET se o usuário explicitamente paginar (evita quebrar UI sem controles)
    apply_limit = wants_pagination()
    params_exec = list(params)
    if apply_limit:
        query += " LIMIT ? OFFSET ?"
        params_exec += [per_page, offset]

    requisicoes_rows = conn.execute(query, params_exec).fetchall()
    requisicoes = []
    matrix_scope_cache = {}
    for row in requisicoes_rows:
        item = {k: row[k] for k in row.keys()}
        item["snapshot_versionado_presente"] = _has_versioned_requisicao_snapshot(item)
        cache_key = (item.get("turma_curso_id"), item.get("turma_matriz_id"))
        if cache_key not in matrix_scope_cache:
            matrix_scope_cache[cache_key] = get_allowed_activity_ids_for_turma_matrix(
                conn,
                item.get("turma_curso_id"),
                item.get("turma_matriz_id"),
            )
        allowed_activity_ids, matriz = matrix_scope_cache[cache_key]
        item["matrix_scope_issue"] = bool(
            allowed_activity_ids is not None and item.get("atividade_id") not in allowed_activity_ids
        )
        item["matrix_scope_label"] = _matriz_option_label(matriz) if matriz else None
        requisicoes.append(item)
    # Carregar atividades e documentos obrigatórios (para reuso do form do aluno no modal admin)
    atividades = conn.execute("SELECT * FROM atividades ORDER BY tipo_atividade, grupo, nome").fetchall()
    alunos_opcoes = _list_admin_requisicao_alunos(conn)
    docs_por_atividade = {}
    try:
        for a in atividades:
            raw = None
            try:
                raw = a["documentos_json"] if "documentos_json" in a.keys() else None
            except Exception:
                raw = None
            docs = parse_documentos_json(raw)
            if docs:
                docs_por_atividade[a["id"]] = docs
    except Exception:
        pass
    alunos_filtro = conn.execute(
        """
        SELECT DISTINCT COALESCE(NULLIF(TRIM(a.nome), ''), '') AS aluno_nome
          FROM requisicoes r
          LEFT JOIN alunos a ON r.aluno_id = a.id
         WHERE COALESCE(NULLIF(TRIM(a.nome), ''), '') <> ''
      ORDER BY LOWER(COALESCE(a.nome, '')) ASC
        """
    ).fetchall()
    turmas_filtro = conn.execute(
        """
        SELECT DISTINCT COALESCE(NULLIF(TRIM(COALESCE(t.codigo, t.nome, a.turma)), ''), '') AS turma_codigo
          FROM requisicoes r
          LEFT JOIN alunos a ON r.aluno_id = a.id
          LEFT JOIN turmas t ON t.id = a.turma_id
         WHERE COALESCE(NULLIF(TRIM(COALESCE(t.codigo, t.nome, a.turma)), ''), '') <> ''
      ORDER BY LOWER(COALESCE(t.codigo, t.nome, a.turma, '')) ASC
        """
    ).fetchall()
    tipos_filtro = conn.execute(
        """
        SELECT DISTINCT COALESCE(NULLIF(TRIM(act.tipo_atividade), ''), '') AS tipo_atividade
          FROM requisicoes r
          JOIN atividades act ON r.atividade_id = act.id
         WHERE COALESCE(NULLIF(TRIM(act.tipo_atividade), ''), '') <> ''
      ORDER BY LOWER(COALESCE(act.tipo_atividade, '')) ASC
        """
    ).fetchall()
    grupos_filtro = conn.execute(
        """
        SELECT DISTINCT COALESCE(NULLIF(TRIM(act.grupo), ''), '') AS grupo
          FROM requisicoes r
          JOIN atividades act ON r.atividade_id = act.id
         WHERE COALESCE(NULLIF(TRIM(act.grupo), ''), '') <> ''
      ORDER BY LOWER(COALESCE(act.grupo, '')) ASC
        """
    ).fetchall()
    atividades_filtro = conn.execute(
        """
        SELECT DISTINCT COALESCE(NULLIF(TRIM(act.nome), ''), '') AS atividade_nome
          FROM requisicoes r
          JOIN atividades act ON r.atividade_id = act.id
         WHERE COALESCE(NULLIF(TRIM(act.nome), ''), '') <> ''
      ORDER BY LOWER(COALESCE(act.nome, '')) ASC
        """
    ).fetchall()
    filter_schema = [
        {
            "param": "data_solicitacao",
            "label": "Solicitação",
            "type": "date_range",
            "min_label": "De",
            "max_label": "Até",
        },
        {
            "param": "data_processamento",
            "label": "Processamento",
            "type": "date_range",
            "min_label": "De",
            "max_label": "Até",
        },
        {
            "param": "processamento",
            "label": "Estado do processamento",
            "type": "multi_select",
            "values": [
                {"value": "com_data", "label": "Com processamento"},
                {"value": "sem_data", "label": "Sem processamento"},
            ],
        },
        {
            "param": "aluno",
            "label": "Aluno",
            "type": "multi_select",
            "values": [
                {"value": row["aluno_nome"], "label": row["aluno_nome"]}
                for row in alunos_filtro
            ],
        },
        {
            "param": "turma",
            "label": "Turma",
            "type": "multi_select",
            "values": [
                {"value": row["turma_codigo"], "label": row["turma_codigo"]}
                for row in turmas_filtro
            ],
        },
        {
            "param": "tipo",
            "label": "Tipo",
            "type": "multi_select",
            "values": [
                {"value": row["tipo_atividade"], "label": row["tipo_atividade"]}
                for row in tipos_filtro
            ],
        },
        {
            "param": "grupo",
            "label": "Grupo",
            "type": "multi_select",
            "values": [
                {"value": row["grupo"], "label": row["grupo"]}
                for row in grupos_filtro
            ],
        },
        {
            "param": "atividade",
            "label": "Atividade",
            "type": "multi_select",
            "values": [
                {"value": row["atividade_nome"], "label": row["atividade_nome"]}
                for row in atividades_filtro
            ],
        },
        {
            "param": "status",
            "label": "Status",
            "type": "multi_select",
            "values": [
                {"value": "pendente", "label": "Pendente"},
                {"value": "deferida", "label": "Deferida"},
                {"value": "deferida_parcialmente", "label": "Deferida Parcialmente"},
                {"value": "indeferida", "label": "Indeferida"},
                {"value": "devolvida", "label": "Devolvida"},
                {"value": "encerrada", "label": "Encerrada"},
            ],
        },
    ]
    total_pages = (total + per_page - 1) // per_page if apply_limit and per_page else 1
    return render_template(
        "admin_requisicoes.html",
        requisicoes=requisicoes,
        status_atual=status_filtro,
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages,
        atividades=atividades,
        alunos_opcoes=alunos_opcoes,
        docs_por_atividade=docs_por_atividade,
        filter_schema=filter_schema,
    )

@app.route("/admin/requisicoes/nova", methods=["GET", "POST"])
@admin_required
def admin_nova_requisicao():
    conn = get_db_connection()
    ensure_turmas_matriz_schema(conn)
    ensure_matriz_atividade_links_table(conn)

    if request.method == "GET":
        aluno_id = (request.args.get("aluno_id") or "").strip()
        return redirect(url_for("admin_requisicoes", open_new="1", aluno_id=aluno_id or None))

    aluno_id = request.form.get("aluno_id", type=int)
    atividade_id = request.form.get("atividade_id", type=int)
    nome_evento = (request.form.get("nome_evento") or "").strip()
    observacao = (request.form.get("observacao") or "").strip() or None
    data_evento = _normalize_requisicao_data_evento(request.form.get("data_evento"))
    horas_raw = (request.form.get("horas_solicitadas") or "").strip()

    redirect_kwargs = {"open_new": "1"}
    if aluno_id:
        redirect_kwargs["aluno_id"] = aluno_id

    scope = _get_admin_requisicao_scope_for_aluno(conn, aluno_id) if aluno_id else None
    if not scope:
        flash("Selecione um aluno válido para criar a requisição.", "error")
        return redirect(url_for("admin_requisicoes", **redirect_kwargs))

    if not atividade_id:
        flash("Selecione uma atividade válida.", "error")
        return redirect(url_for("admin_requisicoes", **redirect_kwargs))

    allowed_activity_ids = scope["allowed_activity_ids"]
    if allowed_activity_ids is not None and atividade_id not in allowed_activity_ids:
        flash("A atividade selecionada não pertence à matriz efetiva da turma do aluno.", "error")
        return redirect(url_for("admin_requisicoes", **redirect_kwargs))

    atividade = conn.execute("SELECT id FROM atividades WHERE id = ?", (atividade_id,)).fetchone()
    if not atividade:
        flash("Atividade não encontrada.", "error")
        return redirect(url_for("admin_requisicoes", **redirect_kwargs))

    if not nome_evento:
        flash("Informe o nome do evento.", "error")
        return redirect(url_for("admin_requisicoes", **redirect_kwargs))

    try:
        horas_solicitadas = float(horas_raw)
        if horas_solicitadas < 0:
            raise ValueError()
    except Exception:
        flash("Informe um valor válido para horas solicitadas.", "error")
        return redirect(url_for("admin_requisicoes", **redirect_kwargs))

    if not data_evento:
        flash("Informe uma data válida para o evento.", "error")
        return redirect(url_for("admin_requisicoes", **redirect_kwargs))

    data_solicitacao = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO requisicoes
        (aluno_id, atividade_id, data_solicitacao, data_evento, horas_solicitadas, nome_evento, status, observacao, arquivo_comprovante)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (aluno_id, atividade_id, data_solicitacao, data_evento, horas_solicitadas, nome_evento, "Pendente", observacao, None),
    )
    req_id = cur.lastrowid

    arquivos = request.files.getlist("comprovantes_files") or []
    first_saved = _append_requisicao_arquivos(conn, req_id, aluno_id, arquivos)

    if first_saved:
        conn.execute("UPDATE requisicoes SET arquivo_comprovante = ? WHERE id = ?", (first_saved, req_id))

    maybe_write_versioned_requisicao_snapshot(
        conn,
        flow_origin="admin_create",
        aluno_id=aluno_id,
        atividade_id_legacy=atividade_id,
        req_id=req_id,
    )
    conn.commit()
    try:
        maybe_run_versioned_resolver_shadow_read(
            conn,
            origin="admin_create",
            aluno_id=aluno_id,
            atividade_id_legacy=atividade_id,
            req_id=req_id,
        )
    except Exception:
        logger.exception("Falha ao executar resolvedor versionado em modo sombra no fluxo do admin")
    flash("Requisição criada com sucesso.", "success")
    return redirect(url_for("admin_requisicoes"))

@app.route("/admin/requisicoes/<int:req_id>/editar", methods=["POST"])
@admin_required
def admin_editar_requisicao(req_id):
    conn = get_db_connection()
    ensure_turmas_matriz_schema(conn)
    ensure_matriz_atividade_links_table(conn)

    requisicao = conn.execute(
        """
        SELECT r.*, a.turma_id,
               t.curso_id AS turma_curso_id,
               t.matriz_id AS turma_matriz_id
          FROM requisicoes r
          LEFT JOIN alunos a ON a.id = r.aluno_id
          LEFT JOIN turmas t ON t.id = a.turma_id
         WHERE r.id = ?
        """,
        (req_id,),
    ).fetchone()
    if not requisicao:
        flash("Requisição não encontrada.", "error")
        return redirect(url_for("admin_requisicoes"))

    redirect_kwargs = {"open_edit": "1", "req_id": req_id}

    if (requisicao["status"] or "") != "Pendente":
        flash("Somente requisições pendentes podem ser editadas pelo admin.", "error")
        return redirect(url_for("admin_requisicoes", **redirect_kwargs))

    atividade_id = request.form.get("atividade_id", type=int)
    nome_evento = (request.form.get("nome_evento") or "").strip()
    observacao = (request.form.get("observacao") or "").strip() or None
    data_evento = _normalize_requisicao_data_evento(request.form.get("data_evento"))
    horas_raw = (request.form.get("horas_solicitadas") or "").strip()

    if not nome_evento:
        flash("Informe o nome do evento.", "error")
        return redirect(url_for("admin_requisicoes", **redirect_kwargs))

    try:
        horas_solicitadas = float(horas_raw)
        if horas_solicitadas < 0:
            raise ValueError()
    except Exception:
        flash("Informe um valor válido para horas solicitadas.", "error")
        return redirect(url_for("admin_requisicoes", **redirect_kwargs))

    if not data_evento:
        flash("Informe uma data válida para o evento.", "error")
        return redirect(url_for("admin_requisicoes", **redirect_kwargs))

    if not atividade_id:
        atividade_id = requisicao["atividade_id"]

    allowed_activity_ids, _matriz = get_allowed_activity_ids_for_turma_matrix(
        conn,
        requisicao["turma_curso_id"],
        requisicao["turma_matriz_id"],
    )
    current_atividade_id = requisicao["atividade_id"]
    if allowed_activity_ids is not None and atividade_id != current_atividade_id and atividade_id not in allowed_activity_ids:
        flash("A atividade selecionada não pertence à matriz efetiva da turma do aluno.", "error")
        return redirect(url_for("admin_requisicoes", **redirect_kwargs))

    atividade = conn.execute("SELECT id FROM atividades WHERE id = ?", (atividade_id,)).fetchone()
    if not atividade:
        flash("Atividade não encontrada.", "error")
        return redirect(url_for("admin_requisicoes", **redirect_kwargs))

    arquivos = request.files.getlist("comprovantes_files") or []
    first_saved = _append_requisicao_arquivos(conn, req_id, requisicao["aluno_id"], arquivos)

    params = [atividade_id, nome_evento, horas_solicitadas, data_evento, observacao]
    sql = """
        UPDATE requisicoes
           SET atividade_id = ?,
               nome_evento = ?,
               horas_solicitadas = ?,
               data_evento = ?,
               observacao = ?
    """
    if requisicao["arquivo_comprovante"] is None and first_saved:
        sql += ", arquivo_comprovante = ?"
        params.append(first_saved)
    sql += " WHERE id = ?"
    params.append(req_id)

    conn.execute(sql, tuple(params))
    conn.commit()
    flash("Requisição atualizada com sucesso.", "success")
    return redirect(url_for("admin_requisicoes"))

@app.route("/admin/requisicoes/<int:req_id>/excluir", methods=["POST"])
@admin_required
def admin_excluir_requisicao(req_id):
    conn = get_db_connection()
    row = conn.execute("SELECT id FROM requisicoes WHERE id = ?", (req_id,)).fetchone()
    if not row:
        return ("Requisição não encontrada.", 404)
    try:
        conn.execute("DELETE FROM requisicao_arquivos WHERE requisicao_id = ?", (req_id,))
        conn.execute("DELETE FROM requisicoes WHERE id = ?", (req_id,))
        conn.commit()
    except Exception as e:
        logger.error(f"Erro ao excluir requisição {req_id}: {e}")
        return ("Erro ao excluir.", 500)
    # Remove arquivos físicos (best-effort)
    try:
        upload_root = app.config.get("UPLOAD_FOLDER")
        if upload_root:
            req_dir = os.path.join(upload_root, f"req_{req_id}")
            if os.path.isdir(req_dir):
                shutil.rmtree(req_dir, ignore_errors=True)
    except Exception:
        pass
    return ("", 204)

@app.route("/admin/requisicao/<int:req_id>")
@admin_required
def admin_detalhes_requisicao(req_id):
    conn = get_db_connection()
    requisicao = conn.execute("""
        SELECT r.*, u.nome as AdminNome, a.nome as AlunoNome, a.matricula as AlunoMatricula, act.nome as AtividadeNome
        FROM requisicoes r
        LEFT JOIN usuarios u ON r.admin_id = u.id
        LEFT JOIN alunos a ON r.aluno_id = a.id
        JOIN atividades act ON r.atividade_id = act.id
        WHERE r.id = ?
    """, (req_id,)).fetchone()
    if not requisicao:
        flash("Requisição não encontrada.", "error")
        return redirect(url_for("admin_requisicoes"))
    return render_template("admin_detalhes_requisicao.html", requisicao=requisicao)

@app.route("/admin/api/requisicao/<int:req_id>")
@admin_required
def admin_api_requisicao(req_id):
    """Retorna detalhes da requisição para hidratar o modal (inclui anexos)."""
    conn = get_db_connection()
    ensure_turmas_matriz_schema(conn)
    ensure_matriz_atividade_links_table(conn)
    r = conn.execute(
        """
        SELECT r.*, a.nome as aluno_nome, a.turma_id as turma_id,
             COALESCE(t.codigo, t.nome, 'Sem turma') as turma_label,
             t.curso_id as turma_curso_id, t.matriz_id as turma_matriz_id,
               act.nome as atividade_nome, act.grupo as grupo, act.tipo_atividade as tipo_atividade
          FROM requisicoes r
          LEFT JOIN alunos a ON r.aluno_id = a.id
          LEFT JOIN turmas t ON t.id = a.turma_id
          JOIN atividades act ON r.atividade_id = act.id
         WHERE r.id = ?
        """,
        (req_id,)
    ).fetchone()
    if not r:
        return jsonify({"error":"not-found"}), 404
    anexos = conn.execute(
        "SELECT id, label, filename, criado_em FROM requisicao_arquivos WHERE requisicao_id = ? ORDER BY id",
        (req_id,)
    ).fetchall()
    def row_to_dict(row):
        if row is None:
            return None
        try:
            return {k: row[k] for k in row.keys()}
        except Exception:
            # fallback: sqlite3.Row supports .keys(); if not, map by items
            return dict(row)
    data = row_to_dict(r)
    allowed_activity_ids, matriz = get_allowed_activity_ids_for_turma_matrix(
        conn,
        data.get("turma_curso_id"),
        data.get("turma_matriz_id"),
    )
    data["allowed_activity_ids"] = sorted(allowed_activity_ids) if allowed_activity_ids is not None else None
    data["current_activity_allowed"] = (
        True if allowed_activity_ids is None else data.get("atividade_id") in allowed_activity_ids
    )
    data["matriz_scope"] = (
        {"id": matriz["id"], "label": _matriz_option_label(matriz)} if matriz else None
    )
    data["anexos"] = [row_to_dict(x) for x in anexos]
    # URL pública para cada anexo (se possível)
    base_upload = app.config.get("UPLOAD_FOLDER")
    items = []
    for x in data["anexos"]:
        fn = x.get("filename")
        if not fn:
            items.append(x); continue
        # normalizar caminho para rota /uploads
        safe = os.path.normpath(fn).replace("\\", "/").lstrip("/")
        x["url"] = url_for("uploaded_file", filename=safe)
        items.append(x)
    data["anexos"] = items
    return jsonify(data)

@app.route("/admin/api/aluno/<int:aluno_id>/requisicao-scope")
@admin_required
def admin_api_aluno_requisicao_scope(aluno_id):
    conn = get_db_connection()
    scope = _get_admin_requisicao_scope_for_aluno(conn, aluno_id)
    if not scope:
        return jsonify({"error": "not-found"}), 404
    aluno = scope["aluno"]
    return jsonify(
        {
            "aluno_id": aluno["id"],
            "aluno_nome": aluno["nome"],
            "aluno_matricula": aluno["matricula"],
            "turma_id": aluno["turma_id"],
            "turma_label": scope["turma_label"],
            "allowed_activity_ids": scope["allowed_activity_ids"],
            "matriz_scope": scope["matriz_scope"],
        }
    )


def _diagnostico_versionado_turmas_disponiveis(conn) -> list[dict[str, object]]:
    return [
        {
            "id": row["turma_id"],
            "codigo": row["turma_codigo"],
            "nome": row["turma_nome"],
            "matriz_id": row["matriz_id"],
            "matriz_label": (
                _matriz_option_label(row)
                if row["matriz_id"] is not None
                else None
            ),
            "periodo_label": _periodo_label_for_turma_row(row),
        }
        for row in conn.execute(
            """
            SELECT t.id AS turma_id,
                   t.codigo AS turma_codigo,
                   t.nome AS turma_nome,
                   t.matriz_id,
                   t.ano_inicio,
                   t.semestre_inicio,
                   t.ano_fim,
                   t.semestre_fim,
                   m.nome,
                   m.versao,
                   m.status
              FROM turmas t
              LEFT JOIN matrizes_atividades m ON m.id = t.matriz_id
          ORDER BY COALESCE(t.codigo, t.nome, '')
            """
        ).fetchall()
    ]


@app.route("/admin/diagnostico/atividades-versionadas")
@admin_required
def admin_diagnostico_atividades_versionadas():
    conn = get_db_connection()
    turma_id = request.args.get("turma_id", type=int)
    matriz_id = request.args.get("matriz_id", type=int)
    turma_codigo = (request.args.get("turma_codigo") or "").strip()

    try:
        if turma_id:
            payload = listar_atividades_versionadas_por_turma(conn, turma_id)
            payload["consulta"] = {"modo": "turma", "turma_id": turma_id, "matriz_id": payload["matriz"]["id"]}
            return jsonify({"ok": True, **payload})

        if turma_codigo:
            turma = conn.execute("SELECT id FROM turmas WHERE codigo = ?", (turma_codigo,)).fetchone()
            if not turma:
                raise LookupError("Turma não encontrada para leitura diagnóstica.")
            payload = listar_atividades_versionadas_por_turma(conn, turma["id"])
            payload["consulta"] = {
                "modo": "turma_codigo",
                "turma_codigo": turma_codigo,
                "turma_id": turma["id"],
                "matriz_id": payload["matriz"]["id"],
            }
            return jsonify({"ok": True, **payload})

        if matriz_id:
            payload = listar_atividades_versionadas_por_matriz(conn, matriz_id)
            payload["consulta"] = {"modo": "matriz", "matriz_id": matriz_id}
            return jsonify({"ok": True, **payload})

        turmas_disponiveis = _diagnostico_versionado_turmas_disponiveis(conn)
        return jsonify(
            {
                "ok": True,
                "consulta": {"modo": "indice"},
                "message": "Informe turma_id, turma_codigo ou matriz_id para consultar o modelo versionado em paralelo.",
                "turmas_disponiveis": turmas_disponiveis,
            }
        )
    except LookupError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 404
    except RuntimeError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 503
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400


@app.route("/admin/diagnostico/versioned-shadow-reads")
@admin_required
def admin_diagnostico_versioned_shadow_reads():
    origin = (request.args.get("origin") or "").strip() or None
    status = (request.args.get("status") or "").strip() or None
    codigo_normativo = (request.args.get("codigo_normativo") or "").strip() or None
    eixo = (request.args.get("eixo") or "").strip() or None
    aluno_id = request.args.get("aluno_id", type=int)
    atividade_id_legacy = request.args.get("atividade_id_legacy", type=int)
    has_warnings = _parse_shadow_read_bool_filter(request.args.get("has_warnings"))

    raw_limit = request.args.get("limit", type=int)
    limit = raw_limit if raw_limit is not None else 100
    if limit <= 0:
        limit = 100
    limit = min(limit, 500)

    filters = {
        "origin": origin,
        "status": status,
        "aluno_id": aluno_id,
        "atividade_id_legacy": atividade_id_legacy,
        "codigo_normativo": codigo_normativo,
        "eixo": eixo,
        "has_warnings": has_warnings,
    }

    source_info = _resolve_versioned_shadow_read_log_sources()
    dedicated_log_path = str(source_info.get("dedicated_path") or os.path.abspath(_versioned_shadow_read_dedicated_log_path()))
    dedicated_log_exists = bool(source_info.get("dedicated_exists"))
    log_paths = [str(path) for path in source_info.get("paths_to_read", [])]
    source_mode = str(source_info.get("source_mode") or "fallback_app_log")
    shadow_read_env_raw = os.getenv("SGAA_VERSIONED_RESOLVER_SHADOW_READ")
    shadow_read_enabled = is_versioned_resolver_shadow_read_enabled()
    logger_level = logging.getLevelName(logger.getEffectiveLevel())
    events, log_not_found, raw_count, deduplicated_count, read_source_mode, read_paths = _read_versioned_shadow_read_events(
        limit=limit,
        filters=filters,
        source_info=source_info,
    )
    if read_source_mode:
        source_mode = read_source_mode
    if read_paths:
        log_paths = [str(path) for path in read_paths]
    return jsonify(
        {
            "diagnostico": "versioned_shadow_reads",
            "source": "log",
            "source_mode": source_mode,
            "count": len(events),
            "raw_count": raw_count,
            "deduplicated_count": deduplicated_count,
            "limit": limit,
            "filters": {key: value for key, value in filters.items() if value is not None},
            "log_not_found": log_not_found,
            "shadow_read_enabled": shadow_read_enabled,
            "shadow_read_env_raw": shadow_read_env_raw,
            "dedicated_log_path": dedicated_log_path,
            "dedicated_log_exists": dedicated_log_exists,
            "dedicated_log_in_paths": dedicated_log_path in set(log_paths),
            "log_paths": log_paths,
            "logger_level": logger_level,
            "handler_count": len(logger.handlers),
            "events": events,
        }
    )


@app.route("/admin/diagnostico/atividades-versionadas/view")
@admin_required
def admin_diagnostico_atividades_versionadas_view():
    conn = get_db_connection()
    turma_id = request.args.get("turma_id", type=int)
    matriz_id = request.args.get("matriz_id", type=int)
    turma_codigo = (request.args.get("turma_codigo") or "").strip()
    status_code = 200
    payload = None
    consulta = {"modo": "indice"}
    message = "Informe turma_id, turma_codigo ou matriz_id para carregar a visualização diagnóstica."

    try:
        if turma_id:
            payload = listar_atividades_versionadas_por_turma(conn, turma_id)
            consulta = {"modo": "turma", "turma_id": turma_id, "matriz_id": payload["matriz"]["id"]}
            message = ""
        elif turma_codigo:
            turma = conn.execute("SELECT id FROM turmas WHERE codigo = ?", (turma_codigo,)).fetchone()
            if not turma:
                raise LookupError("Turma não encontrada para leitura diagnóstica.")
            payload = listar_atividades_versionadas_por_turma(conn, turma["id"])
            consulta = {
                "modo": "turma_codigo",
                "turma_codigo": turma_codigo,
                "turma_id": turma["id"],
                "matriz_id": payload["matriz"]["id"],
            }
            message = ""
        elif matriz_id:
            payload = listar_atividades_versionadas_por_matriz(conn, matriz_id)
            consulta = {"modo": "matriz", "matriz_id": matriz_id}
            message = ""
    except LookupError as exc:
        status_code = 404
        message = str(exc)
    except RuntimeError as exc:
        status_code = 503
        message = str(exc)
    except ValueError as exc:
        status_code = 400
        message = str(exc)

    response = make_response(
        render_template(
            "admin_diagnostico_atividades_versionadas_view.html",
            payload=payload,
            consulta=consulta,
            message=message,
            turmas_disponiveis=_diagnostico_versionado_turmas_disponiveis(conn),
        ),
        status_code,
    )
    return response


@app.route("/admin/processar_requisicao/<int:req_id>", methods=["GET", "POST"])
@admin_required
def admin_processar_requisicao(req_id):
    conn = get_db_connection()
    ensure_turmas_matriz_schema(conn)
    ensure_matriz_atividade_links_table(conn)
    snapshot_display_enabled = is_versioned_requisicao_snapshot_display_enabled()
    requisicao = conn.execute("""
        SELECT r.*, a.nome as atividade_nome, a.tipo_atividade AS atividade_tipo_legacy_atual,
               a.tem_limitacao, a.tipo_limitacao,
               a.limite_horas_total, a.limite_horas_semestral, al.nome as aluno_nome,
               t.curso_id AS turma_curso_id, t.matriz_id AS turma_matriz_id
        FROM requisicoes r
        JOIN atividades a ON r.atividade_id = a.id
        LEFT JOIN alunos al ON r.aluno_id = al.id
        LEFT JOIN turmas t ON t.id = al.turma_id
        WHERE r.id = ?
    """, (req_id,)).fetchone()
    
    if not requisicao:
        flash("Requisição não encontrada.", "error")
        return redirect(url_for("admin_requisicoes"))

    snapshot_diag = _build_admin_requisicao_snapshot_diagnostic(requisicao)

    if request.method == "GET":
        return render_template(
            "admin_processar_requisicao.html",
            requisicao=requisicao,
            snapshot_diag=snapshot_diag,
            snapshot_display_enabled=snapshot_display_enabled,
        )

    if request.method == "POST":
        status = request.form["status"]
        horas_deferidas = request.form.get("horas_deferidas")
        observacao = request.form.get("observacao")
        admin_id = session["user_id"]
        data_processamento = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        allowed_statuses = {
            "Pendente",
            "Deferida",
            "Deferida Parcialmente",
            "Indeferida",
            "Devolvida",
            "Encerrada",
        }

        if status not in allowed_statuses:
            flash("Status de processamento inválido.", "error")
            return redirect(url_for("admin_processar_requisicao", req_id=req_id))

        if status == "Deferida Parcialmente" and (horas_deferidas is None or str(horas_deferidas).strip() == ""):
            flash("Horas deferidas são obrigatórias para status 'Deferida Parcialmente'.", "error")
            return redirect(url_for("admin_processar_requisicao", req_id=req_id))
        # normaliza horas_deferidas se necessário
        if status == "Deferida Parcialmente":
            try:
                horas_deferidas = float(horas_deferidas)
                if horas_deferidas < 0:
                    raise ValueError()
            except Exception:
                flash("Informe um número válido para horas deferidas.", "error")
                return redirect(url_for("admin_processar_requisicao", req_id=req_id))

        if status in ["Deferida", "Deferida Parcialmente"] and not is_activity_allowed_for_turma_matrix(
            conn,
            requisicao["atividade_id"],
            requisicao["turma_curso_id"],
            requisicao["turma_matriz_id"],
        ):
            flash(
                "A atividade desta requisição não pertence mais a matriz efetiva da turma do aluno.",
                "error",
            )
            return redirect(url_for("admin_processar_requisicao", req_id=req_id))
        
        if status in ["Deferida", "Deferida Parcialmente"] and requisicao["tem_limitacao"]:
            horas_a_deferir = float(horas_deferidas) if status == "Deferida Parcialmente" else float(requisicao["horas_solicitadas"])
            if requisicao["tipo_limitacao"] == "total":
                horas_ja_deferidas = conn.execute("""
                    SELECT COALESCE(SUM(
                        CASE 
                            WHEN status = 'Deferida' THEN horas_solicitadas
                            WHEN status = 'Deferida Parcialmente' THEN horas_deferidas
                            ELSE 0
                        END
                    ), 0) as total
                    FROM requisicoes 
                    WHERE aluno_id = ? AND atividade_id = ? AND status IN ('Deferida', 'Deferida Parcialmente')
                """, (requisicao["aluno_id"], requisicao["atividade_id"])).fetchone()[0]
                
                if horas_ja_deferidas + horas_a_deferir > requisicao["limite_horas_total"]:
                    flash(f"Erro: O aluno já possui {horas_ja_deferidas}h nesta atividade. Limite total: {requisicao['limite_horas_total']}h. Máximo a deferir agora: {requisicao['limite_horas_total'] - horas_ja_deferidas}h.", "error")
                    return redirect(url_for("admin_processar_requisicao", req_id=req_id))
            
            elif requisicao["tipo_limitacao"] == "semestral":
                ano_atual = datetime.datetime.now().year
                semestre_atual = 1 if datetime.datetime.now().month <= 6 else 2
                
                horas_ja_deferidas_semestre = conn.execute("""
                    SELECT COALESCE(SUM(
                        CASE 
                            WHEN status = 'Deferida' THEN horas_solicitadas
                            WHEN status = 'Deferida Parcialmente' THEN horas_deferidas
                            ELSE 0
                        END
                    ), 0) as total
                    FROM requisicoes 
                    WHERE aluno_id = ? AND atividade_id = ? AND status IN ('Deferida', 'Deferida Parcialmente')
                    AND strftime('%Y', data_evento) = ? 
                    AND (
                        (? = 1 AND strftime('%m', data_evento) BETWEEN '01' AND '06') OR
                        (? = 2 AND strftime('%m', data_evento) BETWEEN '07' AND '12')
                    )
                """, (requisicao["aluno_id"], requisicao["atividade_id"], str(ano_atual), semestre_atual, semestre_atual)).fetchone()[0]

                if horas_ja_deferidas_semestre + horas_a_deferir > requisicao["limite_horas_semestral"]:
                    flash(f"Erro: Já possui {horas_ja_deferidas_semestre}h neste semestre. Limite semestral: {requisicao['limite_horas_semestral']}h. Máximo agora: {requisicao['limite_horas_semestral'] - horas_ja_deferidas_semestre}h.", "error")
                    return redirect(url_for("admin_processar_requisicao", req_id=req_id))

        if status != "Deferida Parcialmente":
            horas_deferidas = None

        if status == "Pendente":
            data_processamento = None
            admin_id = None

        set_parts = [
            "status = ?",
            "horas_deferidas = ?",
            "observacao = ?",
            "data_processamento = ?",
            "admin_id = ?",
        ]
        params = [status, horas_deferidas, observacao, data_processamento, admin_id]
        current_status = str(requisicao["status"] or "").strip()
        if status == "Pendente":
            set_parts.extend([
                "aluno_update_notified_at = ?",
                "aluno_update_seen_at = ?",
            ])
            params.extend([None, None])
        elif current_status == "Pendente":
            set_parts.extend([
                "aluno_update_notified_at = ?",
                "aluno_update_seen_at = ?",
            ])
            params.extend([data_processamento, None])

        params.append(req_id)
        conn.execute(
            f"UPDATE requisicoes SET {', '.join(set_parts)} WHERE id = ?",
            params,
        )
        conn.commit()
        flash("Requisição processada com sucesso.", "success")
        return redirect(url_for("admin_requisicoes"))

    return render_template(
        "admin_processar_requisicao.html",
        requisicao=requisicao,
        snapshot_diag=snapshot_diag,
        snapshot_display_enabled=snapshot_display_enabled,
    )

# ===================== Rotas Admin: Atividades =====================

@app.route("/admin/atividades")
@admin_required
def admin_atividades():
    """Lista atividades com filtro por tipo e docs.
    Backend-only: adiciona paginação opcional e COUNT consistente.
    """
    page, per_page, offset = get_pagination(default_per_page=50)
    tipo_filters = [value.strip() for value in get_multi_query_values('tipo') if value.strip() and value.strip() != 'Todas']
    grupo_filters = [value.strip() for value in get_multi_query_values('grupo') if value.strip()]
    limitacao_filters = [value.strip().lower() for value in get_multi_query_values('limitacao') if value.strip()]
    nome_filter = get_text_query_value('nome')
    tipo_filtro = tipo_filters[0] if len(tipo_filters) == 1 else 'Todas'
    sort_field = (request.args.get('s') or '').strip().lower()
    sort_dir = 'DESC' if (request.args.get('dir') or 'asc').strip().lower() == 'desc' else 'ASC'
    conn = get_db_connection()
    base_from = " FROM atividades"
    where = []
    params = []
    append_text_contains_condition(where, params, 'nome', nome_filter)
    if tipo_filters:
        placeholders = ", ".join("?" for _ in tipo_filters)
        where.append(f"COALESCE(tipo_atividade, 'Acadêmica Complementar') IN ({placeholders})")
        params.extend(tipo_filters)
    if grupo_filters:
        placeholders = ", ".join("?" for _ in grupo_filters)
        where.append(f"COALESCE(TRIM(grupo), '') IN ({placeholders})")
        params.extend(grupo_filters)
    if limitacao_filters:
        clauses = []
        if 'limitadas' in limitacao_filters:
            clauses.append("COALESCE(tem_limitacao, 0) = 1")
        if 'sem_limite' in limitacao_filters:
            clauses.append("COALESCE(tem_limitacao, 0) = 0")
        if clauses:
            where.append("(" + " OR ".join(clauses) + ")")
    where_sql = append_conditions_sql(False, where)
    sort_map = {
        'nome': f" ORDER BY nome COLLATE NOCASE {sort_dir}, tipo_atividade COLLATE NOCASE ASC, grupo COLLATE NOCASE ASC",
        'grupo': f" ORDER BY grupo COLLATE NOCASE {sort_dir}, nome COLLATE NOCASE ASC",
        'tipo_atividade': f" ORDER BY tipo_atividade COLLATE NOCASE {sort_dir}, grupo COLLATE NOCASE ASC, nome COLLATE NOCASE ASC",
        'limitacao': (
            " ORDER BY "
            f"COALESCE(tem_limitacao, 0) {sort_dir}, "
            f"CASE WHEN tipo_limitacao = 'total' THEN COALESCE(limite_horas_total, 0) "
            f"WHEN tipo_limitacao = 'semestral' THEN COALESCE(limite_horas_semestral, 0) "
            f"ELSE 0 END {sort_dir}, "
            "nome COLLATE NOCASE ASC"
        ),
    }
    order_sql = sort_map.get(sort_field)
    if not order_sql:
        order_sql = " ORDER BY tipo_atividade, grupo, nome" if (not where) else " ORDER BY grupo, nome"
    query = (
        "SELECT *, (SELECT atividade_base_id FROM atividade_legacy_map"
        " WHERE atividade_id_legacy = id) AS base_id"
        + base_from + where_sql + order_sql
    )
    count_sql = "SELECT COUNT(*)" + base_from + where_sql
    total = conn.execute(count_sql, params).fetchone()[0]
    apply_limit = wants_pagination()
    exec_params = list(params)
    if apply_limit:
        query += " LIMIT ? OFFSET ?"
        exec_params += [per_page, offset]
    atividades = conn.execute(query, exec_params).fetchall()
    # Load documentos obrigatórios per atividade (tolerant parser)
    docs_por_atividade = {}
    try:
        cols = [c[1] for c in conn.execute("PRAGMA table_info(atividades)").fetchall()]
        if 'documentos_json' in cols:
            for a in atividades:
                docs_por_atividade[a['id']] = parse_documentos_json(a.get('documentos_json') if isinstance(a, dict) else a['documentos_json'])
    except Exception:
        pass
    # Build grupos_por_tipo including explicit definitions from grupos_def table
    def build_grupos_por_tipo_from_db(c):
        grupos = {}
        try:
            rows = c.execute("SELECT tipo_atividade, numero, descricao FROM grupos_def").fetchall()
            for r in rows:
                tipo, num, desc = r[0], str(r[1]), (r[2] or '').strip()
                grupos.setdefault(tipo, {})[num] = desc
        except Exception:
            pass
        # also derive from atividades for missing entries
        rows2 = conn.execute(
            "SELECT tipo_atividade, grupo FROM atividades WHERE grupo IS NOT NULL AND TRIM(grupo) <> ''"
        ).fetchall()
        for r in rows2:
            tipo = r[0]
            label = (r[1] or '').strip()
            m = re.match(r'^\s*(\d+)\s*-\s*(.*)$', label)
            if m:
                num = m.group(1)
                desc = (m.group(2) or '').strip()
            else:
                m2 = re.match(r'^\s*(\d+)\s*$', label)
                if not m2:
                    continue
                num = m2.group(1)
                desc = ''
            if tipo not in grupos:
                grupos[tipo] = {}
            if num not in grupos[tipo] or (not grupos[tipo][num] and desc):
                grupos[tipo][num] = desc
        return grupos
    grupos_por_tipo = build_grupos_por_tipo_from_db(conn)
    grupos_filtro = conn.execute(
        """
        SELECT DISTINCT COALESCE(NULLIF(TRIM(grupo), ''), '') AS grupo
          FROM atividades
         WHERE COALESCE(NULLIF(TRIM(grupo), ''), '') <> ''
      ORDER BY LOWER(COALESCE(grupo, '')) ASC
        """
    ).fetchall()
    filter_schema = [
        {
            "param": "tipo",
            "label": "Tipo",
            "type": "multi_select",
            "values": [
                {"value": "Acadêmica Complementar", "label": "Acadêmica Complementar"},
                {"value": "Extensão Universitária", "label": "Extensão Universitária"},
            ],
        },
        {
            "param": "nome",
            "label": "Nome",
            "type": "text_contains",
            "placeholder": "Contém no nome",
        },
        {
            "param": "limitacao",
            "label": "Limitação",
            "type": "multi_select",
            "values": [
                {"value": "limitadas", "label": "Apenas com limitação"},
                {"value": "sem_limite", "label": "Sem limitação"},
            ],
        },
        {
            "param": "grupo",
            "label": "Grupo",
            "type": "multi_select",
            "values": [
                {"value": row["grupo"], "label": row["grupo"]}
                for row in grupos_filtro
            ],
        },
    ]
    total_pages = (total + per_page - 1) // per_page if apply_limit and per_page else 1
    return render_template("admin_atividades.html", atividades=atividades, tipo_atual=tipo_filtro, grupos_por_tipo=grupos_por_tipo, docs_por_atividade=docs_por_atividade, page=page, per_page=per_page, total=total, total_pages=total_pages, filter_schema=filter_schema)


@app.route("/admin/atividades/importar/preview", methods=["GET", "POST"])
@admin_required
def admin_atividades_importar_preview():
    mode = (request.form.get("mode") or request.args.get("mode") or "create_only").strip() or "create_only"
    if request.method == "POST":
        arquivo = request.files.get("csv_arquivo")
        if not arquivo or not getattr(arquivo, "filename", ""):
            flash("Selecione um arquivo CSV para validar.", "error")
            return render_template("admin_importar_atividades.html", preview=None, preview_key="", mode=mode)
        try:
            rel_path = save_upload(arquivo, ALLOWED_CSV, prefix="atividades", subdir="atividades_imports")
        except ValueError:
            flash("Envie um arquivo CSV válido.", "error")
            return render_template("admin_importar_atividades.html", preview=None, preview_key="", mode=mode)

        abs_path = os.path.join(app.config["UPLOAD_FOLDER"], rel_path)
        preview, storage_payload = _build_atividades_import_preview(abs_path, rel_path, mode)
        preview_key = ""
        if storage_payload is not None:
            preview_key = _store_atividades_import_preview(storage_payload)
        else:
            _delete_upload_relpath(rel_path)
        return render_template("admin_importar_atividades.html", preview=preview, preview_key=preview_key, mode=mode)
    return render_template("admin_importar_atividades.html", preview=None, preview_key="", mode=mode)


@app.route("/admin/atividades/importar/confirmar", methods=["POST"])
@admin_required
def admin_atividades_importar_confirmar():
    preview_key = (request.form.get("preview_key") or "").strip()
    payload = _load_atividades_import_preview(preview_key) if preview_key else None
    if not payload:
        flash("Preview de importação não encontrado ou expirado. Gere um novo preview.", "error")
        return redirect(url_for("admin_atividades", import_csv=1))

    conn = get_db_connection()
    created = 0
    updated = 0
    csv_relpath = payload.get("csv_relpath")
    try:
        for row in payload.get("rows", []):
            _upsert_grupo_definition(conn, row["tipo_atividade"], row["grupo_numero"], row["grupo_descricao"])
            if row.get("action") == "create":
                conn.execute(
                    """
                    INSERT INTO atividades (
                        grupo,
                        nome,
                        limite_horas,
                        tipo_atividade,
                        tem_limitacao,
                        tipo_limitacao,
                        limite_horas_total,
                        limite_horas_semestral,
                        documentos_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["grupo"],
                        row["nome"],
                        None,
                        row["tipo_atividade"],
                        1 if row["tem_limitacao"] else 0,
                        row["tipo_limitacao"],
                        row["limite_horas_total"],
                        row["limite_horas_semestral"],
                        None,
                    ),
                )
                created += 1
            elif row.get("action") == "update":
                conn.execute(
                    """
                    UPDATE atividades
                       SET grupo = ?,
                           tipo_atividade = ?,
                           tem_limitacao = ?,
                           tipo_limitacao = ?,
                           limite_horas_total = ?,
                           limite_horas_semestral = ?
                     WHERE id = ?
                    """,
                    (
                        row["grupo"],
                        row["tipo_atividade"],
                        1 if row["tem_limitacao"] else 0,
                        row["tipo_limitacao"],
                        row["limite_horas_total"],
                        row["limite_horas_semestral"],
                        row["existing_id"],
                    ),
                )
                updated += 1
        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        flash(f"Falha ao confirmar importação: {exc}", "error")
        _delete_atividades_import_preview(preview_key)
        _delete_upload_relpath(csv_relpath)
        return redirect(url_for("admin_atividades", import_csv=1))

    _delete_atividades_import_preview(preview_key)
    _delete_upload_relpath(csv_relpath)
    flash(f"Importação concluída. Criadas: {created}. Atualizadas: {updated}.", "success")
    return redirect(url_for("admin_atividades"))

@app.route("/admin/atividades/academicas")
@admin_required
def admin_atividades_academicas():
    """Lista atividades do tipo Acadêmica Complementar com paginação opcional."""
    page, per_page, offset = get_pagination(default_per_page=50)
    conn = get_db_connection()
    base_from = " FROM atividades WHERE tipo_atividade = 'Acadêmica Complementar'"
    query = "SELECT *" + base_from + " ORDER BY grupo, nome"
    count_sql = "SELECT COUNT(*)" + base_from
    total = conn.execute(count_sql).fetchone()[0]
    apply_limit = wants_pagination()
    params_exec = []
    if apply_limit:
        query += " LIMIT ? OFFSET ?"
        params_exec += [per_page, offset]
    atividades = conn.execute(query, params_exec).fetchall()
    total_pages = (total + per_page - 1) // per_page if apply_limit and per_page else 1
    return render_template("admin_atividades_academicas.html", atividades=atividades, page=page, per_page=per_page, total=total, total_pages=total_pages)

@app.route("/admin/atividades/extensao")
@admin_required
def admin_atividades_extensao():
    """Lista atividades do tipo Extensão Universitária com paginação opcional."""
    page, per_page, offset = get_pagination(default_per_page=50)
    conn = get_db_connection()
    base_from = " FROM atividades WHERE tipo_atividade = 'Extensão Universitária'"
    query = "SELECT *" + base_from + " ORDER BY grupo, nome"
    count_sql = "SELECT COUNT(*)" + base_from
    total = conn.execute(count_sql).fetchone()[0]
    apply_limit = wants_pagination()
    params_exec = []
    if apply_limit:
        query += " LIMIT ? OFFSET ?"
        params_exec += [per_page, offset]
    atividades = conn.execute(query, params_exec).fetchall()
    total_pages = (total + per_page - 1) // per_page if apply_limit and per_page else 1
    return render_template("admin_atividades_extensao.html", atividades=atividades, page=page, per_page=per_page, total=total, total_pages=total_pages)

@app.route("/admin/adicionar_atividade", methods=["GET", "POST"])
@admin_required
def admin_adicionar_atividade():
    # Build mapping of existing group numbers -> description per activity type
    def build_grupos_por_tipo(conn):
        rows = conn.execute(
            "SELECT tipo_atividade, grupo FROM atividades WHERE grupo IS NOT NULL AND TRIM(grupo) <> ''"
        ).fetchall()
        grupos = {}
        for r in rows:
            tipo = r[0]
            label = (r[1] or '').strip()
            m = re.match(r'^\s*(\d+)\s*-\s*(.*)$', label)
            if m:
                num = m.group(1)
                desc = (m.group(2) or '').strip()
            else:
                m2 = re.match(r'^\s*(\d+)\s*$', label)
                if not m2:
                    # ignore labels without numeric prefix for this mapping
                    continue
                num = m2.group(1)
                desc = ''
            if tipo not in grupos:
                grupos[tipo] = {}
            # prefer first non-empty description seen
            if num not in grupos[tipo] or (not grupos[tipo][num] and desc):
                grupos[tipo][num] = desc
        # merge explicit definitions from grupos_def if present
        try:
            rows2 = conn.execute("SELECT tipo_atividade, numero, descricao FROM grupos_def").fetchall()
            for r2 in rows2:
                tipo2, num2, desc2 = r2[0], str(r2[1]), (r2[2] or '').strip()
                if tipo2 not in grupos:
                    grupos[tipo2] = {}
                # explicit def has priority
                grupos[tipo2][num2] = desc2
        except Exception:
            pass
        return grupos

    if request.method == "POST":
        grupo = _normalize_atividade_grupo(request.form.get("tipo_atividade"), request.form.get("grupo"))
        nome = (request.form.get("nome") or "").strip()
        descricao = (request.form.get("descricao") or "").strip() or None
        # Campo opcional: pode não vir do formulário
        limite_horas_raw = request.form.get("limite_horas")
        try:
            limite_horas = int(limite_horas_raw) if (limite_horas_raw is not None and str(limite_horas_raw).strip() != "") else None
        except (TypeError, ValueError):
            limite_horas = None
        tipo_atividade = request.form["tipo_atividade"]
        # Hidden chega como '0'/'1'; evite tratar '0' como truthy
        tem_limitacao = 1 if (request.form.get("tem_limitacao") or "0") in ("1", "true", "on", "yes") else 0
        tipo_limitacao = request.form.get("tipo_limitacao") if tem_limitacao else None
        limite_horas_total = request.form.get("limite_horas_total") if tem_limitacao and tipo_limitacao == "total" else None
        limite_horas_semestral = request.form.get("limite_horas_semestral") if tem_limitacao and tipo_limitacao == "semestral" else None
        # Se há limitação, exigir tipo_limitacao válido
        if tem_limitacao and tipo_limitacao not in ("total", "semestral"):
            flash("Erro: selecione o tipo de limitação (Total ou Semestral).", "error")
            conn = get_db_connection()
            grupos_por_tipo = build_grupos_por_tipo(conn)
            return render_template("admin_adicionar_atividade.html", grupos_por_tipo=grupos_por_tipo)
        # Satisfaz o CHECK da coluna: quando não há limitação, persistimos um valor válido
        if not tem_limitacao:
            tipo_limitacao = "total"
            limite_horas_total = None
            limite_horas_semestral = None
        
        conn = get_db_connection()
        # Validações básicas
        if not grupo:
            flash("Erro: selecione o Grupo (nº/descrição).", "error")
            grupos_por_tipo = build_grupos_por_tipo(conn)
            return render_template("admin_adicionar_atividade.html", grupos_por_tipo=grupos_por_tipo)
        if not nome:
            flash("Erro: informe o Nome da atividade.", "error")
            grupos_por_tipo = build_grupos_por_tipo(conn)
            return render_template("admin_adicionar_atividade.html", grupos_por_tipo=grupos_por_tipo)
        # Checagem explícita de duplicidade por nome (escopo global)
        dup = conn.execute("SELECT id, tipo_atividade, grupo FROM atividades WHERE nome = ?", (nome,)).fetchone()
        if dup:
            flash(f"Erro: Já existe atividade com este nome (ID {dup['id']}, Tipo: {dup['tipo_atividade']}, Grupo: {dup['grupo']}).", "error")
            grupos_por_tipo = build_grupos_por_tipo(conn)
            return render_template("admin_adicionar_atividade.html", grupos_por_tipo=grupos_por_tipo)
        try:
            conn.execute(
                """
                INSERT INTO atividades 
                (grupo, nome, descricao, limite_horas, tipo_atividade, tem_limitacao, tipo_limitacao, limite_horas_total, limite_horas_semestral, documentos_json) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    grupo,
                    nome,
                    descricao,
                    limite_horas,
                    tipo_atividade,
                    tem_limitacao,
                    tipo_limitacao,
                    limite_horas_total,
                    limite_horas_semestral,
                    request.form.get("documentos_json") or None,
                ),
            )
            conn.commit()
            flash("Atividade adicionada com sucesso.", "success")
            return redirect(url_for("admin_atividades"))
        except sqlite3.IntegrityError as e:
            msg = str(e).lower()
            if 'not null constraint failed' in msg and 'atividades.grupo' in msg:
                flash("Erro: selecione um número de grupo válido.", "error")
            elif 'unique' in msg and 'nome' in msg:
                flash("Erro: Atividade com este nome já existe.", "error")
            else:
                flash(f"Erro de integridade: {e}", "error")
        grupos_por_tipo = build_grupos_por_tipo(conn)
        return render_template("admin_adicionar_atividade.html", grupos_por_tipo=grupos_por_tipo)
    # GET
    conn = get_db_connection()
    grupos_por_tipo = build_grupos_por_tipo(conn)
    return render_template("admin_adicionar_atividade.html", grupos_por_tipo=grupos_por_tipo)

@app.route('/admin/grupos/renomear', methods=['POST'])
@admin_required
def admin_grupos_renomear():
    try:
        data = request.get_json(force=True) or {}
        tipo = (data.get('tipo_atividade') or '').strip()
        numero = str(data.get('numero') or '').strip()
        descricao = (data.get('descricao') or '').strip()
        if not tipo:
            return jsonify({ 'ok': False, 'error': 'tipo_atividade requerido' }), 400
        if not numero.isdigit():
            return jsonify({ 'ok': False, 'error': 'numero inválido' }), 400
        novo_label = f"{numero} - {descricao}" if descricao else numero
        conn = get_db_connection()
        # ensure grupos_def table exists
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS grupos_def (
                tipo_atividade TEXT NOT NULL,
                numero INTEGER NOT NULL,
                descricao TEXT,
                PRIMARY KEY (tipo_atividade, numero)
            )
            """
        )
        cur = conn.execute("SELECT id, grupo FROM atividades WHERE tipo_atividade = ? AND grupo IS NOT NULL AND TRIM(grupo) <> ''", (tipo,))
        rows = cur.fetchall()
        def parse_num(s):
            m = re.match(r'^\s*(\d+)', (s or '').strip())
            return m.group(1) if m else None
        updated = 0
        for r in rows:
            gid, g = r[0], r[1]
            n = parse_num(g)
            if n == numero and (g or '').strip() != novo_label:
                conn.execute("UPDATE atividades SET grupo = ? WHERE id = ?", (novo_label, gid))
                updated += 1
        # upsert definition (compatible): try update, if none affected then insert
        cur2 = conn.execute(
            "UPDATE grupos_def SET descricao = ? WHERE tipo_atividade = ? AND numero = ?",
            (descricao, tipo, int(numero))
        )
        if cur2.rowcount == 0:
            conn.execute(
                "INSERT INTO grupos_def (tipo_atividade, numero, descricao) VALUES (?,?,?)",
                (tipo, int(numero), descricao)
            )
        conn.commit()
        return jsonify({ 'ok': True, 'updated': updated, 'label': novo_label })
    except Exception as e:
        logging.exception('Erro ao renomear grupo')
        return jsonify({ 'ok': False, 'error': 'erro_interno' }), 500


@app.route('/admin/grupos/excluir', methods=['POST'])
@admin_required
def admin_grupos_excluir():
    try:
        data = request.get_json(force=True) or {}
        tipo = (data.get('tipo_atividade') or '').strip()
        numero = str(data.get('numero') or '').strip()
        if not tipo:
            return jsonify({'ok': False, 'error': 'tipo_atividade requerido'}), 400
        if not numero.isdigit():
            return jsonify({'ok': False, 'error': 'numero inválido'}), 400

        conn = get_db_connection()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS grupos_def (
                tipo_atividade TEXT NOT NULL,
                numero INTEGER NOT NULL,
                descricao TEXT,
                PRIMARY KEY (tipo_atividade, numero)
            )
            """
        )

        prefixo = f"{numero}%"
        em_uso = conn.execute(
            """
            SELECT 1
              FROM atividades
             WHERE tipo_atividade = ?
               AND grupo IS NOT NULL
               AND TRIM(grupo) <> ''
               AND TRIM(grupo) LIKE ?
             LIMIT 1
            """,
            (tipo, prefixo),
        ).fetchone()
        if em_uso:
            return jsonify({'ok': False, 'error': 'grupo_em_uso'}), 409

        cur = conn.execute(
            "DELETE FROM grupos_def WHERE tipo_atividade = ? AND numero = ?",
            (tipo, int(numero)),
        )
        conn.commit()
        return jsonify({'ok': True, 'deleted': cur.rowcount})
    except Exception:
        logging.exception('Erro ao excluir grupo')
        return jsonify({'ok': False, 'error': 'erro_interno'}), 500

@app.route("/admin/editar_atividade/<int:atividade_id>", methods=["GET", "POST"])
@admin_required
def admin_editar_atividade(atividade_id):
    # Força recarregar o template a cada requisição (evita servir versão antiga em dev)
    try:
        app.jinja_env.cache.clear()
    except Exception:
        pass
    conn = get_db_connection()
    atividade = conn.execute("SELECT * FROM atividades WHERE id = ?", (atividade_id,)).fetchone()
    if not atividade:
        flash("Atividade não encontrada.", "error")
        return redirect(url_for("admin_atividades"))
    # Docs salvos (normalizados) para inicializar chips no template
    try:
        atividade_docs_saved = parse_documentos_json(atividade['documentos_json'] if 'documentos_json' in atividade.keys() else None)
    except Exception:
        atividade_docs_saved = []

    # Build mapping of existing group numbers -> description per activity type (for UI parity with 'Adicionar')
    def build_grupos_por_tipo(c):
        grupos = {}
        # explicit definitions first
        try:
            rows = c.execute("SELECT tipo_atividade, numero, descricao FROM grupos_def").fetchall()
            for r in rows:
                tipo, num, desc = r[0], str(r[1]), (r[2] or '').strip()
                grupos.setdefault(tipo, {})[num] = desc
        except Exception:
            pass
        # derive from atividades for gaps
        rows2 = c.execute(
            "SELECT tipo_atividade, grupo FROM atividades WHERE grupo IS NOT NULL AND TRIM(grupo) <> ''"
        ).fetchall()
        for r in rows2:
            tipo = r[0]
            label = (r[1] or '').strip()
            m = re.match(r'^\s*(\d+)\s*-\s*(.*)$', label)
            if m:
                num = m.group(1)
                desc = (m.group(2) or '').strip()
            else:
                m2 = re.match(r'^\s*(\d+)\s*$', label)
                if not m2:
                    continue
                num = m2.group(1)
                desc = ''
            if tipo not in grupos:
                grupos[tipo] = {}
            if num not in grupos[tipo] or (not grupos[tipo][num] and desc):
                grupos[tipo][num] = desc
        return grupos

    if request.method == "POST":
        # Use .get to avoid BadRequestKeyError if inputs are missing
        grupo = _normalize_atividade_grupo(request.form.get("tipo_atividade"), request.form.get("grupo"))
        nome = request.form.get("nome", "")
        descricao = (request.form.get("descricao") or "").strip() or None
        limite_horas_raw = request.form.get("limite_horas")
        try:
            limite_horas = int(limite_horas_raw) if (limite_horas_raw is not None and str(limite_horas_raw).strip() != "") else None
        except (TypeError, ValueError):
            limite_horas = None
        tipo_atividade = request.form.get("tipo_atividade", "")
        tem_limitacao = 1 if (request.form.get("tem_limitacao") or "0") in ("1", "true", "on", "yes") else 0
        tipo_limitacao = request.form.get("tipo_limitacao") if tem_limitacao else None
        limite_horas_total = request.form.get("limite_horas_total") if tem_limitacao and tipo_limitacao == "total" else None
        limite_horas_semestral = request.form.get("limite_horas_semestral") if tem_limitacao and tipo_limitacao == "semestral" else None
        # Se há limitação, exigir tipo_limitacao válido
        if tem_limitacao and tipo_limitacao not in ("total", "semestral"):
            flash("Erro: selecione o tipo de limitação (Total ou Semestral).", "error")
            return render_template("admin_editar_atividade.html", atividade=atividade)
        # Satisfaz o CHECK da coluna: quando não há limitação, persistimos um valor válido
        if not tem_limitacao:
            tipo_limitacao = "total"
            limite_horas_total = None
            limite_horas_semestral = None
        
        # Checagem explícita de duplicidade por nome (escopo global), ignorando a própria
        dup = conn.execute("SELECT id, tipo_atividade, grupo FROM atividades WHERE nome = ? AND id <> ?", (nome, atividade_id)).fetchone()
        if dup:
            flash(f"Erro: Já existe atividade com este nome (ID {dup['id']}, Tipo: {dup['tipo_atividade']}, Grupo: {dup['grupo']}).", "error")
            grupos_por_tipo = build_grupos_por_tipo(conn)
            # Repassa lista de documentos a partir do que veio do form (ou salvos)
            atividade_docs = parse_documentos_json(request.form.get("documentos_json") or (atividade['documentos_json'] if 'documentos_json' in atividade.keys() else None))
            try:
                logger.info("[admin_editar_atividade POST dup] id=%s raw=%r parsed=%s", atividade_id, request.form.get("documentos_json"), atividade_docs)
            except Exception:
                pass
            resp = make_response(render_template("admin_editar_atividade.html", atividade=atividade, grupos_por_tipo=grupos_por_tipo, atividade_docs=atividade_docs))
            resp.headers['X-Template-Editar-Version'] = 'editar-atividade-20251012-02'
            return resp
        # Validações básicas
        if not grupo:
            flash("Erro: selecione o Grupo (nº/descrição).", "error")
            grupos_por_tipo = build_grupos_por_tipo(conn)
            atividade_docs = parse_documentos_json(request.form.get("documentos_json") or (atividade['documentos_json'] if 'documentos_json' in atividade.keys() else None))
            try:
                logger.info("[admin_editar_atividade POST grupo_vazio] id=%s raw=%r parsed=%s", atividade_id, request.form.get("documentos_json"), atividade_docs)
            except Exception:
                pass
            resp = make_response(render_template("admin_editar_atividade.html", atividade=atividade, grupos_por_tipo=grupos_por_tipo, atividade_docs=atividade_docs))
            resp.headers['X-Template-Editar-Version'] = 'editar-atividade-20251012-02'
            return resp
        if not nome:
            flash("Erro: informe o Nome da atividade.", "error")
            grupos_por_tipo = build_grupos_por_tipo(conn)
            atividade_docs = parse_documentos_json(request.form.get("documentos_json") or (atividade['documentos_json'] if 'documentos_json' in atividade.keys() else None))
            try:
                logger.info("[admin_editar_atividade POST nome_vazio] id=%s raw=%r parsed=%s", atividade_id, request.form.get("documentos_json"), atividade_docs)
            except Exception:
                pass
            resp = make_response(render_template("admin_editar_atividade.html", atividade=atividade, grupos_por_tipo=grupos_por_tipo, atividade_docs=atividade_docs))
            resp.headers['X-Template-Editar-Version'] = 'editar-atividade-20251012-02'
            return resp

        try:
            conn.execute("""
                UPDATE atividades 
                SET grupo = ?, nome = ?, descricao = ?, limite_horas = ?, tipo_atividade = ?, 
                    tem_limitacao = ?, tipo_limitacao = ?, limite_horas_total = ?, limite_horas_semestral = ?, documentos_json = ?
                WHERE id = ?
            """, (grupo, nome, descricao, limite_horas, tipo_atividade, tem_limitacao, tipo_limitacao, limite_horas_total, limite_horas_semestral, request.form.get("documentos_json") or None, atividade_id))
            conn.commit()
            flash("Atividade atualizada com sucesso.", "success")
            return redirect(url_for("admin_atividades"))
        except sqlite3.IntegrityError as e:
            msg = str(e).lower()
            if 'not null constraint failed' in msg and 'atividades.grupo' in msg:
                flash("Erro: selecione um número de grupo válido.", "error")
            elif 'unique' in msg and 'nome' in msg:
                flash("Erro: Atividade com este nome já existe.", "error")
            else:
                flash(f"Erro de integridade: {e}", "error")
    grupos_por_tipo = build_grupos_por_tipo(conn)
    try:
        logger.info("[admin_editar_atividade GET] id=%s raw=%r parsed=%s", atividade_id, (atividade['documentos_json'] if 'documentos_json' in atividade.keys() else None), atividade_docs_saved)
        try:
            src, fname, uptodate = app.jinja_loader.get_source(app.jinja_env, 'admin_editar_atividade.html')
            logger.info("[tmpl] editar path=%s uptodate=%s has_marker=%s", fname, uptodate, ('editar-atividade-20251012-02' in src))
        except Exception as e2:
            logger.warning("[tmpl] get_source error: %s", e2)
    except Exception:
        pass
    resp = make_response(render_template("admin_editar_atividade.html", atividade=atividade, grupos_por_tipo=grupos_por_tipo, atividade_docs=atividade_docs_saved))
    resp.headers['X-Template-Editar-Version'] = 'editar-atividade-20251012-02'
    return resp

@app.route("/admin/deletar_atividade/<int:atividade_id>", methods=["POST"])
@admin_required
def admin_deletar_atividade(atividade_id):
    conn = get_db_connection()
    atividade = conn.execute("SELECT id, nome FROM atividades WHERE id = ?", (atividade_id,)).fetchone()
    if not atividade:
        flash("Atividade não encontrada.", "error")
        return redirect(url_for("admin_atividades"))

    requisicoes_em_uso = conn.execute(
        "SELECT COUNT(*) FROM requisicoes WHERE atividade_id = ?",
        (atividade_id,),
    ).fetchone()[0]
    if requisicoes_em_uso:
        sufixo = "requisição" if requisicoes_em_uso == 1 else "requisições"
        flash(
            f"Não é possível excluir a atividade porque ela está vinculada a {requisicoes_em_uso} {sufixo}.",
            "error",
        )
        return redirect(url_for("admin_atividades"))

    try:
        ensure_matriz_atividade_links_table(conn)
        conn.execute("DELETE FROM matrizes_atividades_itens WHERE atividade_id = ?", (atividade_id,))
        conn.execute("DELETE FROM atividades WHERE id = ?", (atividade_id,))
        conn.commit()
        flash("Atividade deletada com sucesso.", "success")
    except sqlite3.IntegrityError:
        conn.rollback()
        logging.exception("Erro de integridade ao deletar atividade %s", atividade_id)
        flash("Não foi possível excluir a atividade porque ela possui vínculos em uso no sistema.", "error")
    except Exception:
        conn.rollback()
        logging.exception("Erro inesperado ao deletar atividade %s", atividade_id)
        flash("Erro interno ao deletar atividade.", "error")
    return redirect(url_for("admin_atividades"))

# ===================== Rotas Admin: Alunos =====================

@app.route("/admin/alunos")
@admin_required
def admin_alunos():
    page, per_page, offset = get_pagination(default_per_page=25)
    sort_field = (request.args.get("s") or "nome").strip().lower()
    sort_dir = (request.args.get("dir") or "asc").strip().lower()
    status_filters = [value.strip() for value in get_multi_query_values("status") if value.strip()]
    curso_filters = get_int_multi_query_values("curso_id")
    turma_filters = get_int_multi_query_values("turma_id")
    pendencia_filters = [value.strip().lower() for value in get_multi_query_values("pendencias") if value.strip()]
    nome_filter = get_text_query_value("nome")
    email_filter = get_text_query_value("email")
    pendentes_min, pendentes_max = get_number_range_query("pendentes")
    conn = get_db_connection()
    base_from = """
        FROM usuarios u
        JOIN alunos a ON u.id = a.usuario_id
        LEFT JOIN turmas t ON t.id = a.turma_id
        LEFT JOIN cursos c ON c.id = t.curso_id
        LEFT JOIN (
            SELECT r.aluno_id, COUNT(*) AS pendentes
            FROM requisicoes r
            WHERE r.status = 'Pendente'
            GROUP BY r.aluno_id
        ) p ON p.aluno_id = a.id
    """
    select_cols = """
        SELECT 
            u.id AS usuario_id,
            u.nome,
            u.email,
            a.matricula,
            c.nome AS curso_nome,
            COALESCE(t.codigo, t.nome, a.turma) AS turma,
            a.turma_id,
            a.status,
            COALESCE(p.pendentes, 0) AS pendentes
    """
    where = []
    params = []
    append_text_contains_condition(where, params, "u.nome", nome_filter)
    append_text_contains_condition(where, params, "u.email", email_filter)
    if status_filters:
        placeholders = ", ".join("?" for _ in status_filters)
        where.append(f"COALESCE(a.status, 'Ativo') IN ({placeholders})")
        params.extend(status_filters)
    if curso_filters:
        placeholders = ", ".join("?" for _ in curso_filters)
        where.append(f"t.curso_id IN ({placeholders})")
        params.extend(curso_filters)
    if turma_filters:
        placeholders = ", ".join("?" for _ in turma_filters)
        where.append(f"a.turma_id IN ({placeholders})")
        params.extend(turma_filters)
    pendencia_modes = {value for value in pendencia_filters if value in {"com_pendencias", "sem_pendencias"}}
    if pendencia_modes == {"com_pendencias"}:
        where.append("COALESCE(p.pendentes, 0) > 0")
    elif pendencia_modes == {"sem_pendencias"}:
        where.append("COALESCE(p.pendentes, 0) = 0")
    if pendentes_min is not None:
        where.append("COALESCE(p.pendentes, 0) >= ?")
        params.append(pendentes_min)
    if pendentes_max is not None:
        where.append("COALESCE(p.pendentes, 0) <= ?")
        params.append(pendentes_max)

    where_sql = append_conditions_sql(False, where)
    order_map = {
        "nome": "COALESCE(u.nome, '') COLLATE PTBR_NOACCENT",
        "matricula": "COALESCE(a.matricula, '') COLLATE PTBR_NOACCENT",
        "email": "COALESCE(u.email, '') COLLATE PTBR_NOACCENT",
        "curso_nome": "COALESCE(c.nome, '') COLLATE PTBR_NOACCENT",
        "turma": "COALESCE(t.codigo, t.nome, a.turma, '') COLLATE PTBR_NOACCENT",
        "status": "COALESCE(a.status, '') COLLATE PTBR_NOACCENT",
        "pendentes": "COALESCE(p.pendentes, 0)",
    }
    order_sql = order_map.get(sort_field, order_map["nome"])
    direction = "DESC" if sort_dir == "desc" else "ASC"
    query = select_cols + base_from + where_sql + f" ORDER BY {order_sql} {direction}, u.id ASC"
    # counting rows (same FROM, no ORDER)
    count_sql = "SELECT COUNT(*) " + base_from + where_sql
    total = conn.execute(count_sql, params).fetchone()[0]
    apply_limit = wants_pagination()
    params_exec = list(params)
    if apply_limit:
        query += " LIMIT ? OFFSET ?"
        params_exec += [per_page, offset]
    alunos = conn.execute(query, params_exec).fetchall()
    total_pages = (total + per_page - 1) // per_page if apply_limit and per_page else 1
    cursos = conn.execute("SELECT id, nome, codigo FROM cursos ORDER BY COALESCE(nome, '') COLLATE PTBR_NOACCENT, id").fetchall()
    turmas = conn.execute(
        """
        SELECT t.id, t.codigo, t.nome, t.numero, c.nome AS curso_nome
          FROM turmas t
          LEFT JOIN cursos c ON c.id = t.curso_id
            ORDER BY COALESCE(c.nome, '') COLLATE PTBR_NOACCENT,
                             COALESCE(t.numero, 0),
                             COALESCE(t.codigo, t.nome, '') COLLATE PTBR_NOACCENT,
                             t.id
        """
    ).fetchall()
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
            "param": "status",
            "label": "Status",
            "type": "multi_select",
            "values": [
                {"value": "Ativo", "label": "Ativo"},
                {"value": "Inativo", "label": "Inativo"},
            ],
        },
        {
            "param": "curso_id",
            "label": "Curso",
            "type": "multi_select",
            "values": [
                {
                    "value": str(curso["id"]),
                    "label": f"{curso['nome']} ({curso['codigo']})" if curso["codigo"] else curso["nome"],
                }
                for curso in cursos
            ],
        },
        {
            "param": "turma_id",
            "label": "Turma",
            "type": "multi_select",
            "values": [
                {
                    "value": str(turma["id"]),
                    "label": turma["codigo"]
                    or turma["nome"]
                    or (f"Turma {turma['numero']}" if turma["numero"] else "Turma sem código"),
                }
                for turma in turmas
            ],
        },
        {
            "param": "pendentes",
            "label": "Solicitações pendentes",
            "type": "number_range",
            "min_label": "Mínimo",
            "max_label": "Máximo",
        },
        {
            "param": "pendencias",
            "label": "Pendências",
            "type": "multi_select",
            "values": [
                {"value": "com_pendencias", "label": "Com pendências"},
                {"value": "sem_pendencias", "label": "Sem pendências"},
            ],
        },
    ]
    return render_template(
        "admin_alunos.html",
        alunos=alunos,
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages,
        filter_schema=filter_schema,
    )

@app.route("/admin/adicionar_aluno", methods=["GET", "POST"])
@admin_required
def admin_adicionar_aluno():
    conn = get_db_connection()
    ensure_usuario_access_schema(conn)
    return_to = (request.form.get("return_to") or request.args.get("return_to") or "").strip()
    turma_default_id = request.form.get("turma_id", type=int) if request.method == "POST" else request.args.get("turma_id", type=int)
    if request.method == "POST":
        nome = request.form["nome"]
        email = request.form["email"]
        senha = (request.form.get("senha") or "").strip()
        matricula = request.form["matricula"]
        turma_id = request.form.get("turma_id", type=int)
        status = request.form["status"]

        try:
            senha_final = senha or _default_password_for_user_type(conn, "aluno")
            hashed_password = hash_password(senha_final)
            cursor = create_usuario_with_default_access(conn, nome, email, hashed_password, "aluno")
            usuario_id = cursor.lastrowid
            conn.execute("INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status) VALUES (?, ?, ?, ?, ?, ?)", 
                         (usuario_id, nome, matricula, email, turma_id, status))
            resequence_turma_aluno_matriculas_for_ids(conn, turma_id)
            conn.commit()
            flash("Aluno adicionado com sucesso.", "success")
            return redirect(_safe_return_to_target("admin_alunos"))
        except sqlite3.IntegrityError as e:
            if "UNIQUE constraint failed: usuarios.email" in str(e):
                flash("Erro: Já existe um usuário com este e-mail.", "error")
            elif "UNIQUE constraint failed: alunos.matricula" in str(e):
                flash("Erro: Já existe um aluno com esta matrícula.", "error")
            else:
                flash(f"Erro ao adicionar aluno: {e}", "error")
        except Exception as e:
            flash(f"Erro inesperado ao adicionar aluno: {e}", "error")

    # Compat: templates antigos esperam (id, nome). Exibo código como "nome".
    turmas = conn.execute("""
        SELECT t.id, COALESCE(t.codigo, t.nome) AS nome
          FROM turmas t
         WHERE t.status='Ativa'
      ORDER BY t.ano DESC, t.semestre DESC, nome
    """).fetchall()
    return render_template(
        "admin_adicionar_aluno.html",
        turmas=turmas,
        turma_default_id=turma_default_id,
        return_to=return_to,
    )

@app.route("/admin/editar_aluno/<int:usuario_id>", methods=["GET", "POST"])
@admin_required
def admin_editar_aluno(usuario_id):
    conn = get_db_connection()
    aluno = conn.execute("""
      SELECT u.id as usuario_id, u.nome, u.email, a.matricula, a.turma_id, a.status 
      FROM usuarios u 
      JOIN alunos a ON u.id = a.usuario_id 
      WHERE u.id = ?
    """, (usuario_id,)).fetchone()
    if not aluno:
        flash("Aluno não encontrado.", "error")
        return redirect(url_for("admin_alunos"))

    if request.method == "POST":
        nome = request.form["nome"]
        email = request.form["email"]
        matricula = request.form["matricula"]
        turma_id = request.form.get("turma_id", type=int)
        status = request.form["status"]
        senha = request.form.get("senha")
        turma_id_anterior = aluno["turma_id"]

        try:
            if senha:
                hashed_password = hash_password(senha)
                conn.execute("UPDATE usuarios SET nome = ?, email = ?, senha = ? WHERE id = ?", (nome, email, hashed_password, usuario_id))
            else:
                conn.execute("UPDATE usuarios SET nome = ?, email = ? WHERE id = ?", (nome, email, usuario_id))
            conn.execute("UPDATE alunos SET nome = ?, matricula = ?, email = ?, turma_id = ?, status = ? WHERE usuario_id = ?", 
                         (nome, matricula, email, turma_id, status, usuario_id))
            resequence_turma_aluno_matriculas_for_ids(conn, turma_id_anterior, turma_id)
            conn.commit()
            flash("Aluno atualizado com sucesso.", "success")
            return redirect(url_for("admin_alunos"))
        except sqlite3.IntegrityError as e:
            if "UNIQUE constraint failed: usuarios.email" in str(e):
                flash("Erro: Já existe outro usuário com este e-mail.", "error")
            elif "UNIQUE constraint failed: alunos.matricula" in str(e):
                flash("Erro: Já existe outro aluno com esta matrícula.", "error")
            else:
                flash(f"Erro ao atualizar aluno: {e}", "error")
        except Exception as e:
            flash(f"Erro inesperado ao atualizar aluno: {e}", "error")

    turmas = conn.execute("""
        SELECT t.id, COALESCE(t.codigo, t.nome) AS nome
          FROM turmas t
         WHERE t.status='Ativa'
      ORDER BY t.ano DESC, t.semestre DESC, nome
    """).fetchall()
    return render_template("admin_editar_aluno.html", aluno=aluno, turmas=turmas)

@app.route("/admin/deletar_aluno/<int:usuario_id>", methods=["POST"])
@admin_required
def admin_deletar_aluno(usuario_id):
    conn = get_db_connection()
    try:
        aluno = conn.execute("SELECT turma_id FROM alunos WHERE usuario_id = ?", (usuario_id,)).fetchone()
        deleted_aluno = conn.execute("DELETE FROM alunos WHERE usuario_id = ?", (usuario_id,))
        deleted_usuario = conn.execute("DELETE FROM usuarios WHERE id = ?", (usuario_id,))
        if deleted_aluno.rowcount == 0 and deleted_usuario.rowcount == 0:
            raise LookupError("Aluno não encontrado para exclusão.")
        resequence_turma_aluno_matriculas_for_ids(conn, aluno["turma_id"] if aluno else None)
        conn.commit()
        if _is_ajax_request():
            return jsonify({"ok": True, "deleted": usuario_id})
        flash("Aluno deletado com sucesso.", "success")
    except Exception as e:
        conn.rollback()
        if _is_ajax_request():
            return jsonify({"ok": False, "error": str(e)}), 500
        flash(f"Erro ao deletar aluno: {e}", "error")
    return redirect(_safe_return_to_target("admin_alunos"))

@app.route("/admin/alterar_status_alunos", methods=["POST"])
@admin_required
def admin_alterar_status_alunos():
    selected_alunos_ids = request.form.getlist("selected_alunos")
    novo_status = request.form["novo_status"]

    if not selected_alunos_ids:
        flash("Nenhum aluno selecionado para alteração de status.", "warning")
        return redirect(url_for("admin_alunos"))

    conn = get_db_connection()
    try:
        placeholders = ", ".join(["?" for _ in selected_alunos_ids])
        query = f"UPDATE alunos SET status = ? WHERE usuario_id IN ({placeholders})"
        conn.execute(query, (novo_status, *selected_alunos_ids))
        conn.commit()
        flash(f"Status de {len(selected_alunos_ids)} aluno(s) alterado(s) para '{novo_status}' com sucesso.", "success")
    except Exception as e:
        flash(f"Erro ao alterar status dos alunos: {e}", "error")
        logger.error(f"Erro ao alterar status em massa: {e}")
        traceback.print_exc()
    return redirect(url_for("admin_alunos"))

# ===================== Rotas Admin: Turmas =====================

@app.route("/admin/turmas")
@admin_required
def admin_turmas():
    page, per_page, offset = get_pagination(default_per_page=25)
    sort_field = (request.args.get("s") or "curso_nome").strip().lower()
    sort_dir = (request.args.get("dir") or "asc").strip().lower()
    status_filters = [value.strip() for value in get_multi_query_values("status") if value.strip()]
    curso_filters = get_int_multi_query_values("curso_id")
    codigo_filter = get_text_query_value("codigo")
    matriz_filter = get_text_query_value("matriz")
    numero_min, numero_max = get_number_range_query("numero")
    qtd_alunos_min, qtd_alunos_max = get_number_range_query("qtd_alunos")
    conn = get_db_connection()
    ensure_turmas_matriz_schema(conn)
    base_from = """
        FROM turmas t
   LEFT JOIN cursos c ON c.id = t.curso_id
   LEFT JOIN alunos a ON a.turma_id = t.id
   LEFT JOIN matrizes_atividades tm_assigned ON tm_assigned.id = t.matriz_id
   LEFT JOIN matrizes_atividades tm ON tm.id = COALESCE(
       tm_assigned.id,
       (
           SELECT mp.id
             FROM matrizes_atividades mp
            WHERE mp.curso_id = t.curso_id
         ORDER BY CASE LOWER(COALESCE(mp.status, ''))
                      WHEN 'ativa' THEN 0
                      WHEN 'vigente' THEN 0
                      WHEN 'rascunho' THEN 1
                      ELSE 2
                  END,
                  COALESCE(mp.data_inicio_vigencia, '') DESC,
                  mp.id DESC
            LIMIT 1
       )
   )
    """
    select_cols = """
        SELECT t.id, t.nome, t.ano, t.semestre, t.turno, t.status, t.numero,
               t.ano_inicio, t.semestre_inicio, t.ano_fim, t.semestre_fim, t.codigo,
               t.matriz_id, c.nome AS curso_nome, c.codigo AS curso_codigo, c.duracao_periodos,
               tm.nome AS matriz_nome, tm.versao AS matriz_versao, tm.status AS matriz_status,
               COUNT(a.id) AS qtd_alunos
    """
    where = []
    params = []
    append_text_contains_condition(where, params, "t.codigo", codigo_filter)
    append_text_contains_condition(where, params, "tm.nome", matriz_filter)
    if status_filters:
        placeholders = ", ".join("?" for _ in status_filters)
        where.append(f"COALESCE(t.status, 'Ativa') IN ({placeholders})")
        params.extend(status_filters)
    if curso_filters:
        placeholders = ", ".join("?" for _ in curso_filters)
        where.append(f"t.curso_id IN ({placeholders})")
        params.extend(curso_filters)
    if numero_min is not None:
        where.append("COALESCE(t.numero, 0) >= ?")
        params.append(numero_min)
    if numero_max is not None:
        where.append("COALESCE(t.numero, 0) <= ?")
        params.append(numero_max)

    having = []
    having_params = []
    if qtd_alunos_min is not None:
        having.append("COUNT(a.id) >= ?")
        having_params.append(qtd_alunos_min)
    if qtd_alunos_max is not None:
        having.append("COUNT(a.id) <= ?")
        having_params.append(qtd_alunos_max)

    where_sql = append_conditions_sql(False, where)
    order_map = {
        "codigo": "LOWER(COALESCE(t.codigo, ''))",
        "curso_nome": "LOWER(COALESCE(c.nome, ''))",
        "matriz_nome": "LOWER(COALESCE(tm.nome, ''))",
        "numero": "COALESCE(t.numero, 0)",
        "status": "LOWER(COALESCE(t.status, ''))",
    }
    order_sql = order_map.get(sort_field, order_map["curso_nome"])
    direction = "DESC" if sort_dir == "desc" else "ASC"

    having_sql = (" HAVING " + " AND ".join(having)) if having else ""
    grouped_sql = base_from + where_sql + " GROUP BY t.id" + having_sql
    query = select_cols + grouped_sql + f" ORDER BY {order_sql} {direction}, t.id ASC"
    count_sql = "SELECT COUNT(*) FROM (SELECT t.id" + grouped_sql + ") turmas_filtradas"
    total = conn.execute(count_sql, params + having_params).fetchone()[0]
    apply_limit = wants_pagination()
    params_exec = list(params) + list(having_params)
    if apply_limit:
        query += " LIMIT ? OFFSET ?"
        params_exec += [per_page, offset]
    turmas = conn.execute(query, params_exec).fetchall()
    total_pages = (total + per_page - 1) // per_page if apply_limit and per_page else 1
    cursos = conn.execute("SELECT id, nome, codigo FROM cursos ORDER BY LOWER(nome), id").fetchall()
    filter_schema = [
        {
            "param": "codigo",
            "label": "Código",
            "type": "text_contains",
            "placeholder": "Contém no código",
        },
        {
            "param": "status",
            "label": "Status",
            "type": "multi_select",
            "values": [
                {"value": "Ativa", "label": "Ativa"},
                {"value": "Inativa", "label": "Inativa"},
            ],
        },
        {
            "param": "curso_id",
            "label": "Curso",
            "type": "multi_select",
            "values": [
                {
                    "value": str(curso["id"]),
                    "label": f"{curso['nome']} ({curso['codigo']})" if curso["codigo"] else curso["nome"],
                }
                for curso in cursos
            ],
        },
        {
            "param": "matriz",
            "label": "Matriz",
            "type": "text_contains",
            "placeholder": "Contém no nome da matriz",
        },
        {
            "param": "numero",
            "label": "Nº Turma",
            "type": "number_range",
            "min_label": "Mínimo",
            "max_label": "Máximo",
        },
        {
            "param": "qtd_alunos",
            "label": "Alunos",
            "type": "number_range",
            "min_label": "Mínimo",
            "max_label": "Máximo",
        },
    ]
    return render_template(
        "admin_turmas.html",
        turmas=turmas,
        periodo_corrente=periodo_corrente,
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages,
        filter_schema=filter_schema,
    )

@app.route("/admin/adicionar_turma", methods=["GET", "POST"])
@admin_required
def admin_adicionar_turma():
    conn = get_db_connection()
    ensure_turmas_matriz_schema(conn)
    ensure_usuario_access_schema(conn)

    cursos = conn.execute("SELECT id, nome, codigo, duracao_periodos FROM cursos WHERE status='ativo' ORDER BY nome").fetchall()
    default_curso_id = curso_mais_populoso_id() or (cursos[0]["id"] if cursos else None)
    matrizes_by_curso = _matrizes_by_curso(conn)
    preferred_default = get_preferred_matriz_for_curso(conn, default_curso_id)
    default_matriz_id = preferred_default["id"] if preferred_default else None

    if request.method == "POST":
        curso_id = request.form.get("curso_id", type=int)
        matriz_id, matriz_error = _resolve_turma_matriz_id(conn, curso_id, request.form.get("matriz_id", type=int))
        ano_inicio = request.form.get("ano_inicio", type=int) or date.today().year
        semestre_inicio = request.form.get("semestre_inicio", type=int) or semestre_atual_hoje()
        ano_fim = request.form.get("ano_fim", type=int)
        semestre_fim = request.form.get("semestre_fim", type=int)
        turno = request.form.get("turno") or ""
        status = request.form.get("status", "Ativa")
        numero = request.form.get("numero_turma", type=int)
        if numero is None:
            numero = request.form.get("numero", type=int)

        if not curso_id:
            flash("Selecione um curso.", "error")
            return redirect(url_for("admin_adicionar_turma"))

        curso = conn.execute("SELECT * FROM cursos WHERE id=?", (curso_id,)).fetchone()
        if not curso:
            flash("Curso inválido.", "error")
            return redirect(url_for("admin_adicionar_turma"))
        if matriz_error:
            flash(matriz_error, "error")
            return redirect(url_for("admin_adicionar_turma"))

        if not numero:
            numero = proximo_numero_turma_por_curso(curso_id)

        codigo = gerar_codigo_turma(curso["codigo"], numero)

        # validar unicidades
        existe1 = conn.execute("SELECT 1 FROM turmas WHERE curso_id=? AND numero=?", (curso_id, numero)).fetchone()
        if existe1:
            flash("Já existe uma turma com esse número neste curso.", "error")
            return redirect(url_for("admin_adicionar_turma"))
        existe2 = conn.execute("SELECT 1 FROM turmas WHERE codigo=?", (codigo,)).fetchone()
        if existe2:
            flash("Código de turma já existente.", "error")
            return redirect(url_for("admin_adicionar_turma"))

        try:
            cur = conn.execute(
                """
                INSERT INTO turmas (nome, ano, semestre, turno, status, numero, curso_id, matriz_id, ano_inicio, semestre_inicio, ano_fim, semestre_fim, codigo)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (codigo, None, None, turno, status, numero, curso_id, matriz_id, ano_inicio, semestre_inicio, ano_fim, semestre_fim, codigo)
            )
            turma_id = cur.lastrowid

            # Processar alunos do formulário (cadastro em massa inline)
            nomes = request.form.getlist("aluno_nome[]")
            emails = request.form.getlist("aluno_email[]")
            mats  = request.form.getlist("aluno_matricula[]")
            sits  = request.form.getlist("aluno_situacao[]")

            def map_status_db(s):
                return "Ativo" if (s or "").upper() == "ATIVO" else "Inativo"

            if nomes or emails or mats:
                for i in range(max(len(nomes), len(emails), len(mats))):
                    nome_i = (nomes[i] if i < len(nomes) else "").strip()
                    email_i = (emails[i] if i < len(emails) else "").strip()
                    mat_i = (mats[i] if i < len(mats) else "").strip()
                    sit_i = (sits[i] if i < len(sits) else "ATIVO").strip().upper()
                    if not (nome_i or email_i or mat_i):
                        continue
                    if not mat_i:
                        # exigir matrícula para evitar violar NOT NULL/UNIQUE
                        continue
                    # Se houver usuário com este email, reusar; se não, criar apenas se email existir
                    usuario_id = None
                    if email_i:
                        u = conn.execute("SELECT id FROM usuarios WHERE email=?", (email_i,)).fetchone()
                        if u:
                            usuario_id = u[0] if isinstance(u, tuple) else u["id"]
                            normalize_usuario_access_for_user_type(conn, usuario_id)
                        else:
                            # criar usuário aluno com a senha padrão configurada para o nível usuario
                            try:
                                c2 = create_usuario_with_default_password(
                                    conn,
                                    nome_i or email_i.split("@")[0],
                                    email_i,
                                    "aluno",
                                )
                                usuario_id = c2.lastrowid
                            except sqlite3.IntegrityError:
                                # email pode existir em outra conta; não cria usuário, segue sem
                                usuario_id = None
                    # Upsert em alunos pela matrícula
                    # Upsert em alunos por matrícula ou e-mail para reaproveitar cadastros já existentes.
                    a = resolve_existing_aluno_by_identifiers(conn, mat_i, email_i)
                    if a:
                        conn.execute(
                            "UPDATE alunos SET nome=?, matricula=?, email=?, turma_id=?, status=? WHERE id=?",
                            (nome_i or a["nome"], mat_i, email_i or None, turma_id, map_status_db(sit_i), a["id"])
                        )
                        if usuario_id:
                            conn.execute("UPDATE alunos SET usuario_id=? WHERE id=?", (usuario_id, a["id"]))
                    else:
                        conn.execute(
                            "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status) VALUES (?,?,?,?,?,?)",
                            (usuario_id, nome_i or "", mat_i, email_i or None, turma_id, map_status_db(sit_i))
                        )

            resequence_turma_aluno_matriculas_for_ids(conn, turma_id)

            conn.commit()
            flash("Turma criada com sucesso.", "success")
            return redirect(url_for("admin_turmas"))
        except (sqlite3.IntegrityError, ValueError) as e:
            flash(f"Erro ao criar turma: {e}", "error")

    suggested = proximo_numero_turma_por_curso(default_curso_id) if default_curso_id else 1
    return render_template("admin_adicionar_turma.html",
                           cursos=cursos,
                           matrizes_by_curso=matrizes_by_curso,
                           matriz_default_id=default_matriz_id,
                           curso_default_id=default_curso_id,
                           proximo_numero=suggested,
                           ano_sugerido=date.today().year,
                           semestre_sugerido=semestre_atual_hoje())

@app.route("/admin/editar_turma/<int:turma_id>", methods=["GET", "POST"])
@admin_required
def admin_editar_turma(turma_id):
    conn = get_db_connection()
    ensure_turmas_matriz_schema(conn)
    ensure_usuario_access_schema(conn)
    turma = conn.execute("SELECT * FROM turmas WHERE id = ?", (turma_id,)).fetchone()
    if not turma:
        flash("Turma não encontrada.", "error")
        return redirect(url_for("admin_turmas"))

    cursos = conn.execute("SELECT id, nome, codigo, duracao_periodos FROM cursos WHERE status='ativo' ORDER BY nome").fetchall()
    matrizes_by_curso = _matrizes_by_curso(conn)

    if request.method == "POST":
        curso_id = request.form.get("curso_id", type=int)
        matriz_id, matriz_error = _resolve_turma_matriz_id(conn, curso_id, request.form.get("matriz_id", type=int))
        ano_inicio = request.form.get("ano_inicio", type=int)
        semestre_inicio = request.form.get("semestre_inicio", type=int)
        ano_fim = request.form.get("ano_fim", type=int)
        semestre_fim = request.form.get("semestre_fim", type=int)
        turno = request.form.get("turno") or ""
        status = request.form.get("status", "Ativa")
        numero = request.form.get("numero_turma", type=int)
        if numero is None:
            numero = request.form.get("numero", type=int)

        if not curso_id:
            flash("Selecione um curso.", "error")
            return redirect(url_for("admin_editar_turma", turma_id=turma_id))

        curso = conn.execute("SELECT * FROM cursos WHERE id=?", (curso_id,)).fetchone()
        if not curso:
            flash("Curso inválido.", "error")
            return redirect(url_for("admin_editar_turma", turma_id=turma_id))
        if matriz_error:
            flash(matriz_error, "error")
            return redirect(url_for("admin_editar_turma", turma_id=turma_id))

        if not numero:
            numero = proximo_numero_turma_por_curso(curso_id)

        codigo_novo = gerar_codigo_turma(curso["codigo"], numero)

        # validar unicidades (ignorando a própria turma)
        existe1 = conn.execute("SELECT 1 FROM turmas WHERE curso_id=? AND numero=? AND id<>?", (curso_id, numero, turma_id)).fetchone()
        if existe1:
            flash("Já existe uma turma com esse número neste curso.", "error")
            return redirect(url_for("admin_editar_turma", turma_id=turma_id))
        existe2 = conn.execute("SELECT 1 FROM turmas WHERE codigo=? AND id<>?", (codigo_novo, turma_id)).fetchone()
        if existe2:
            flash("Código de turma já existente.", "error")
            return redirect(url_for("admin_editar_turma", turma_id=turma_id))

        try:
            conn.execute(
                """
                UPDATE turmas
                   SET nome=?, ano=?, semestre=?, turno=?, status=?, numero=?, curso_id=?, matriz_id=?, ano_inicio=?, semestre_inicio=?, ano_fim=?, semestre_fim=?, codigo=?
                 WHERE id=?
                """,
                (codigo_novo, None, None, turno, status, numero, curso_id, matriz_id, ano_inicio, semestre_inicio, ano_fim, semestre_fim, codigo_novo, turma_id)
            )

            # Atualizar alunos vinculados via formulário
            nomes = request.form.getlist("aluno_nome[]")
            emails = request.form.getlist("aluno_email[]")
            mats  = request.form.getlist("aluno_matricula[]")
            sits  = request.form.getlist("aluno_situacao[]")

            def map_status_db(s):
                return "Ativo" if (s or "").upper() == "ATIVO" else "Inativo"

            posted_mats = set()
            for i in range(max(len(nomes), len(emails), len(mats))):
                nome_i = (nomes[i] if i < len(nomes) else "").strip()
                email_i = (emails[i] if i < len(emails) else "").strip()
                mat_i = (mats[i] if i < len(mats) else "").strip()
                sit_i = (sits[i] if i < len(sits) else "ATIVO").strip().upper()
                if not (nome_i or email_i or mat_i):
                    continue
                if not mat_i:
                    continue
                posted_mats.add(mat_i)
                # encontrar ou criar usuario se email presente
                usuario_id = None
                if email_i:
                    u = conn.execute("SELECT id FROM usuarios WHERE email=?", (email_i,)).fetchone()
                    if u:
                        usuario_id = u[0] if isinstance(u, tuple) else u["id"]
                        normalize_usuario_access_for_user_type(conn, usuario_id)
                    else:
                        try:
                            c2 = create_usuario_with_default_password(
                                conn,
                                nome_i or email_i.split("@")[0],
                                email_i,
                                "aluno",
                            )
                            usuario_id = c2.lastrowid
                        except sqlite3.IntegrityError:
                            usuario_id = None
                # upsert por matrícula ou e-mail para reaproveitar alunos já cadastrados e apenas relinkar a turma.
                a = resolve_existing_aluno_by_identifiers(conn, mat_i, email_i)
                if a:
                    conn.execute(
                        "UPDATE alunos SET nome=?, matricula=?, email=?, turma_id=?, status=? WHERE id=?",
                        (nome_i or a["nome"], mat_i, email_i or None, turma_id, map_status_db(sit_i), a["id"])
                    )
                    if usuario_id:
                        conn.execute("UPDATE alunos SET usuario_id=? WHERE id=?", (usuario_id, a["id"]))
                else:
                    conn.execute(
                        "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status) VALUES (?,?,?,?,?,?)",
                        (usuario_id, nome_i or "", mat_i, email_i or None, turma_id, map_status_db(sit_i))
                    )

            # Desvincular alunos que foram removidos da lista
            atuais = conn.execute("SELECT matricula FROM alunos WHERE turma_id = ?", (turma_id,)).fetchall()
            atuais_set = {(r[0] if isinstance(r, tuple) else r["matricula"]) for r in atuais}
            to_unlink = atuais_set - posted_mats
            for m in to_unlink:
                conn.execute("UPDATE alunos SET turma_id = NULL WHERE matricula = ?", (m,))

            resequence_turma_aluno_matriculas_for_ids(conn, turma_id)

            conn.commit()
            flash("Turma atualizada com sucesso.", "success")
            return redirect(url_for("admin_turmas"))
        except (sqlite3.IntegrityError, ValueError) as e:
            flash(f"Erro ao atualizar turma: {e}", "error")

    # Carregar alunos da turma para edição inline
    alunos = conn.execute(
        "SELECT nome, email, matricula, status FROM alunos WHERE turma_id = ?",
        (turma_id,)
    ).fetchall()
    alunos = sorted(alunos, key=lambda row: ptbr_text_sort_key(row["nome"]))
    effective_matriz = get_effective_matriz_for_turma(conn, turma["curso_id"], turma["matriz_id"])
    return render_template(
        "admin_editar_turma.html",
        turma=turma,
        cursos=cursos,
        alunos=alunos,
        matrizes_by_curso=matrizes_by_curso,
        matriz_default_id=effective_matriz["id"] if effective_matriz else None,
    )

@app.route("/admin/deletar_turma/<int:turma_id>", methods=["POST"])
@admin_required
def admin_deletar_turma(turma_id):
    conn = get_db_connection()
    try:
        alunos_vinc = conn.execute("SELECT COUNT(*) FROM alunos WHERE turma_id = ?", (turma_id,)).fetchone()[0]
        if alunos_vinc:
            flash("Não é possível excluir: há alunos vinculados a esta turma.", "error")
            return redirect(url_for("admin_turmas"))

        conn.execute("DELETE FROM turmas WHERE id=?", (turma_id,))
        conn.commit()
        flash("Turma deletada com sucesso.", "success")
    except Exception as e:
        flash(f"Erro ao deletar turma: {e}", "error")
    return redirect(url_for("admin_turmas"))

@app.route("/admin/turma/<int:turma_id>")
@admin_required
def admin_detalhes_turma(turma_id):
    conn = get_db_connection()
    ensure_turmas_matriz_schema(conn)
    sort_field = (request.args.get("s") or "nome").strip().lower()
    sort_dir = (request.args.get("dir") or "asc").strip().lower()
    status_filter_map = {"ativo": "Ativo", "inativo": "Inativo"}
    status_filters = {
        status_filter_map[value.strip().lower()]
        for value in get_multi_query_values("status")
        if value.strip().lower() in status_filter_map
    }
    turma = conn.execute("""
        SELECT t.*, c.nome AS curso_nome, c.codigo AS curso_codigo, c.duracao_periodos,
               tm.nome AS matriz_nome, tm.versao AS matriz_versao, tm.status AS matriz_status
          FROM turmas t
          LEFT JOIN cursos c ON c.id = t.curso_id
          LEFT JOIN matrizes_atividades tm_assigned ON tm_assigned.id = t.matriz_id
          LEFT JOIN matrizes_atividades tm ON tm.id = COALESCE(
              tm_assigned.id,
              (
                  SELECT mp.id
                    FROM matrizes_atividades mp
                   WHERE mp.curso_id = t.curso_id
                ORDER BY CASE LOWER(COALESCE(mp.status, ''))
                             WHEN 'ativa' THEN 0
                             WHEN 'vigente' THEN 0
                             WHEN 'rascunho' THEN 1
                             ELSE 2
                         END,
                         COALESCE(mp.data_inicio_vigencia, '') DESC,
                         mp.id DESC
                   LIMIT 1
              )
          )
         WHERE t.id=?
    """, (turma_id,)).fetchone()
    if not turma:
        flash("Turma não encontrada.", "error")
        return redirect(url_for("admin_turmas"))
    alunos = conn.execute(
        """
        SELECT
            u.id AS usuario_id,
            u.nome,
            u.email,
            a.matricula,
            a.status,
            COALESCE(
                SUM(
                    CASE
                        WHEN act.tipo_atividade = 'Acadêmica Complementar'
                             AND r.status IN ('Deferida', 'Deferida Parcialmente')
                        THEN COALESCE(r.horas_deferidas, r.horas_solicitadas, 0)
                        ELSE 0
                    END
                ),
                0
            ) AS total_aac,
            COALESCE(
                SUM(
                    CASE
                        WHEN act.tipo_atividade = 'Extensão Universitária'
                             AND r.status IN ('Deferida', 'Deferida Parcialmente')
                        THEN COALESCE(r.horas_deferidas, r.horas_solicitadas, 0)
                        ELSE 0
                    END
                ),
                0
            ) AS total_ae
        FROM alunos a
        JOIN usuarios u ON u.id = a.usuario_id
        LEFT JOIN requisicoes r ON r.aluno_id = a.id
        LEFT JOIN atividades act ON act.id = r.atividade_id
        WHERE a.turma_id = ?
        GROUP BY a.id, u.id, u.nome, u.email, a.matricula, a.status
        """,
        (turma_id,),
    ).fetchall()
    alunos_normalizados = []
    for row in alunos:
        aluno = {key: row[key] for key in row.keys()}
        aluno["status"] = "Ativo" if str(row["status"] or "").strip().lower() == "ativo" else "Inativo"
        aluno["total_aac"] = float(row["total_aac"] or 0)
        aluno["total_ae"] = float(row["total_ae"] or 0)
        if status_filters and aluno["status"] not in status_filters:
            continue
        alunos_normalizados.append(aluno)

    sort_map = {
        "usuario_id": lambda row: int(row["usuario_id"] or 0),
        "nome": lambda row: ptbr_text_sort_key(row["nome"]),
        "email": lambda row: ptbr_text_sort_key(row["email"] or ""),
        "matricula": lambda row: ptbr_text_sort_key(row["matricula"] or ""),
        "total_aac": lambda row: float(row["total_aac"] or 0),
        "total_ae": lambda row: float(row["total_ae"] or 0),
        "status": lambda row: ptbr_text_sort_key(row["status"]),
    }
    order_key = sort_map.get(sort_field, sort_map["nome"])
    alunos = sorted(alunos_normalizados, key=order_key, reverse=(sort_dir == "desc"))
    all_turmas = conn.execute(
        """
        SELECT t.id, t.codigo, t.numero, c.nome AS curso_nome
          FROM turmas t
          LEFT JOIN cursos c ON c.id = t.curso_id
      ORDER BY LOWER(COALESCE(c.nome, '')), COALESCE(t.numero, 0), LOWER(COALESCE(t.codigo, t.nome, '')), t.id
        """
    ).fetchall()
    filter_schema = [
        {
            "param": "status",
            "label": "Status",
            "type": "multi_select",
            "values": [
                {"value": "Ativo", "label": "Ativo"},
                {"value": "Inativo", "label": "Inativo"},
            ],
        }
    ]
    return render_template(
        "admin_detalhes_turma.html",
        turma=turma,
        alunos=alunos,
        all_turmas=all_turmas,
        filter_schema=filter_schema,
        periodo_corrente=periodo_corrente,
        periodo_label=_periodo_label_for_turma_row(turma),
        matriz_label=_turma_effective_matriz_label(conn, turma),
    )

# ====== Importar Alunos (CSV) para uma Turma ======

@app.route("/admin/turmas/importar", methods=["GET", "POST"])
@admin_required
def admin_turmas_importar():
    if request.method == "GET":
        # Fluxo oficial de importacao acontece no modal de /admin/turmas.
        return redirect(url_for("admin_turmas"))

    conn = get_db_connection()

    if request.method == "POST":
        turma_id = request.form.get("turma_id", type=int)
        arquivo = request.files.get("csv_arquivo")

        if not turma_id:
            flash("Selecione a turma de destino.", "error")
            return redirect(url_for("admin_turmas_importar"))
        if not arquivo or arquivo.filename == "":
            flash("Selecione um arquivo CSV.", "error")
            return redirect(url_for("admin_turmas_importar"))

        # Salva arquivo
        try:
            filename = save_upload(arquivo, ALLOWED_CSV, prefix=f"turma{turma_id}", subdir=f"turmas_imports")
        except ValueError:
            flash("Envie um arquivo CSV válido.", "error")
            return redirect(url_for("admin_turmas_importar"))
        path = os.path.join(app.config["UPLOAD_FOLDER"], filename)

        sucesso, nao_encontrados, erros = 0, 0, 0
        try:
            with open(path, "r", encoding="utf-8-sig", newline="") as f:
                # Detecta delimitador
                sample = f.read(2048)
                f.seek(0)
                try:
                    dialect = csv.Sniffer().sniff(sample)
                except csv.Error:
                    dialect = csv.excel
                reader = csv.DictReader(f, dialect=dialect)

                # Normaliza nomes de colunas
                field_map = {normalize_header(h): h for h in reader.fieldnames or []}
                col_matricula = field_map.get("matricula")
                col_email = field_map.get("email")

                if not (col_matricula or col_email):
                    flash("O CSV precisa ter a coluna 'matrícula' ou 'email'.", "error")
                    return redirect(url_for("admin_turmas_importar"))

                for row in reader:
                    try:
                        matricula = (row.get(col_matricula, "") if col_matricula else "").strip()
                        email = (row.get(col_email, "") if col_email else "").strip()

                        achou = None
                        if matricula:
                            achou = conn.execute("SELECT usuario_id FROM alunos WHERE matricula = ?", (matricula,)).fetchone()
                        if not achou and email:
                            achou = conn.execute("SELECT usuario_id FROM alunos WHERE email = ?", (email,)).fetchone()

                        if achou:
                            conn.execute("UPDATE alunos SET turma_id = ? WHERE usuario_id = ?", (turma_id, achou["usuario_id"]))
                            sucesso += 1
                        else:
                            nao_encontrados += 1
                    except Exception:
                        erros += 1

            resequence_turma_aluno_matriculas_for_ids(conn, turma_id)
            conn.commit()
            msg = resolve_user_message(f"Importação concluída. Vinculados: {sucesso}.")
            if nao_encontrados:
                msg += " " + resolve_user_message(f"Não encontrados: {nao_encontrados}.")
            if erros:
                msg += " " + resolve_user_message(f"Linhas com erro: {erros}.")
            flash(msg, "success")
            return redirect(url_for("admin_turmas"))
        except Exception as e:
            logger.error(f"Erro ao importar CSV de turmas: {e}")
            traceback.print_exc()
            flash(f"Falha ao processar CSV: {e}", "error")
            return redirect(url_for("admin_turmas_importar"))

# ===================== Rotas Aluno =====================

@aluno_runtime_route("/aluno/dashboard")
@aluno_required
def aluno_dashboard():
    if "user_id" not in session or session.get("user_type") != "aluno":
        flash("Acesso não autorizado.", "error")
        return redirect(url_for("login"))
    
    conn = get_db_connection()
    aluno_id = session["user_id"]

    aluno_info = conn.execute("SELECT * FROM alunos WHERE usuario_id = ?", (aluno_id,)).fetchone()
    if not aluno_info:
        flash("Dados do aluno não encontrados.", "error")
        return redirect(url_for("login"))

    requisicoes = conn.execute("""
        SELECT r.*, act.nome as AtividadeNome, act.tipo_atividade
        FROM requisicoes r
        JOIN atividades act ON r.atividade_id = act.id
        WHERE r.aluno_id = ?
        ORDER BY r.data_solicitacao DESC
    """, (aluno_info["id"],)).fetchall()

    horas_por_tipo = conn.execute("""
        SELECT act.tipo_atividade, SUM(r.horas_deferidas) as total_horas
        FROM requisicoes r
        JOIN atividades act ON r.atividade_id = act.id
        WHERE r.aluno_id = ? AND r.status IN ('Deferida', 'Deferida Parcialmente')
        GROUP BY act.tipo_atividade
    """, (aluno_info["id"],)).fetchall()

    horas_por_grupo = conn.execute("""
        SELECT act.grupo, act.tipo_atividade, SUM(r.horas_deferidas) as total_horas
        FROM requisicoes r
        JOIN atividades act ON r.atividade_id = act.id
        WHERE r.aluno_id = ? AND r.status IN ('Deferida', 'Deferida Parcialmente')
        GROUP BY act.grupo, act.tipo_atividade
    """, (aluno_info["id"],)).fetchall()
    
    limites_por_grupo = {row["grupo"]: row["limite_horas"] for row in conn.execute("SELECT grupo, limite_horas FROM atividades GROUP BY grupo").fetchall()}

    total_horas_academicas = sum([
        (r["horas_deferidas"] or 0)
        for r in requisicoes
        if r["status"] in ('Deferida', 'Deferida Parcialmente') and r["tipo_atividade"] == "Acadêmica Complementar"
    ])
    total_horas_extensao = sum([
        (r["horas_deferidas"] or 0)
        for r in requisicoes
        if r["status"] in ('Deferida', 'Deferida Parcialmente') and r["tipo_atividade"] == "Extensão Universitária"
    ])

    # ===== KPIs para o aluno =====
    total_reqs = len(requisicoes)
    pendentes = sum(1 for r in requisicoes if r["status"] == 'Pendente')
    pendentes_acad = sum(1 for r in requisicoes if r["status"] == 'Pendente' and r["tipo_atividade"] == "Acadêmica Complementar")
    pendentes_ext = sum(1 for r in requisicoes if r["status"] == 'Pendente' and r["tipo_atividade"] == "Extensão Universitária")
    # Corrigíveis: não alteramos o schema (CHECK) para adicionar novo status.
    # Critério: requisições Indeferidas com data_processamento definida dentro da janela de 30 dias.
    # Essas são consideradas "corrigíveis" enquanto houver dias restantes > 0.
    hoje = datetime.date.today()
    corrigiveis_lista = []
    for r in requisicoes:
        if r["status"] == 'Indeferida':
            dp_raw = r["data_processamento"]
            if dp_raw:
                try:
                    # data_processamento pode ter HH:MM:SS; usamos somente data
                    if len(dp_raw) > 10:
                        dp_date = datetime.datetime.strptime(dp_raw[:19], "%Y-%m-%d %H:%M:%S").date()
                    else:
                        dp_date = datetime.datetime.strptime(dp_raw, "%Y-%m-%d").date()
                except Exception:
                    try:
                        dp_date = datetime.datetime.strptime(dp_raw[:10], "%Y-%m-%d").date()
                    except Exception:
                        dp_date = None
                if dp_date:
                    dias_passados = (hoje - dp_date).days
                    dias_restantes = 30 - dias_passados
                    if dias_restantes > 0:
                        # Data de expiração em formato brasileiro (DD/MM/YYYY)
                        data_expira = (dp_date + datetime.timedelta(days=30)).strftime("%d/%m/%Y")
                        corrigiveis_lista.append({
                            "id": r["id"],
                            "nome": r["AtividadeNome"],
                            "tipo_atividade": r["tipo_atividade"],
                            "dias_restantes": dias_restantes,
                            "data_expira": data_expira,
                        })
    # Contagem para KPI
    corrigiveis = len(corrigiveis_lista)
    deferidas = sum(1 for r in requisicoes if r["status"] in ('Deferida', 'Deferida Parcialmente'))
    indeferidas = sum(1 for r in requisicoes if r["status"] == 'Indeferida')
    horas_deferidas_total = sum((r["horas_deferidas"] or 0) for r in requisicoes if r["status"] in ('Deferida', 'Deferida Parcialmente'))
    aprov_pct = (deferidas / total_reqs * 100.0) if total_reqs else 0.0
    pend_pct = (pendentes / total_reqs * 100.0) if total_reqs else 0.0

    # Separar listas por tipo
    corrigiveis_acad = [c for c in corrigiveis_lista if c["tipo_atividade"] == "Acadêmica Complementar"]
    corrigiveis_ext  = [c for c in corrigiveis_lista if c["tipo_atividade"] == "Extensão Universitária"]
    # Ordenar por dias restantes (asc) para priorizar os mais urgentes
    corrigiveis_acad.sort(key=lambda x: x["dias_restantes"])
    corrigiveis_ext.sort(key=lambda x: x["dias_restantes"])

    # Periodicidades por grupo (se a atividade tiver tipo_limitacao='semestral')
    periodicidades_por_grupo = {}
    try:
        for row in conn.execute("SELECT grupo, tipo_limitacao FROM atividades").fetchall():
            if row["tipo_limitacao"] == 'semestral':
                periodicidades_por_grupo[row["grupo"]] = 'semestral'
    except Exception:
        pass

    # Lista recente (limitar para exibição)
    requisicoes_recentes = requisicoes[:8]
    alertas_ativos = []
    update_alert = get_student_request_update_alert(conn, aluno_info["id"])
    if update_alert:
        alertas_ativos.append(update_alert["alerta"])
        mark_student_request_updates_seen(conn, update_alert["requisicao_ids"])
        conn.commit()

    return render_template(
        "aluno_dashboard.html",
        aluno=aluno_info,
        requisicoes=requisicoes,
        requisicoes_recentes=requisicoes_recentes,
        horas_por_tipo=horas_por_tipo,
        horas_por_grupo=horas_por_grupo,
        limites_por_grupo=limites_por_grupo,
        total_horas_academicas=total_horas_academicas,
        total_horas_extensao=total_horas_extensao,
        total_reqs=total_reqs,
    pendentes=pendentes,
    corrigiveis=corrigiveis,
    pendentes_acad=pendentes_acad,
    pendentes_ext=pendentes_ext,
        deferidas=deferidas,
        indeferidas=indeferidas,
        horas_deferidas_total=horas_deferidas_total,
        aprov_pct=aprov_pct,
        pend_pct=pend_pct,
        corrigiveis_acad=corrigiveis_acad,
        corrigiveis_ext=corrigiveis_ext,
        periodicidades_por_grupo=periodicidades_por_grupo,
        alertas_ativos=alertas_ativos,
    )

@aluno_runtime_route("/aluno/nova_requisicao", methods=["GET", "POST"])
@aluno_required
def aluno_nova_requisicao():
    if "user_id" not in session or session.get("user_type") != "aluno":
        flash("Acesso não autorizado.", "error")
        return redirect(url_for("login"))

    conn = get_db_connection()
    tipo_filtro = request.args.get('tipo', 'Acadêmica Complementar')
    
    if tipo_filtro == 'Todas':
        atividades = conn.execute("SELECT * FROM atividades ORDER BY tipo_atividade, grupo, nome").fetchall()
    else:
        atividades = conn.execute("SELECT * FROM atividades WHERE tipo_atividade = ? ORDER BY grupo, nome", (tipo_filtro,)).fetchall()

    # Mapear documentos obrigatórios por atividade com parser tolerante
    docs_por_atividade = {}
    try:
        for a in atividades:
            raw = None
            try:
                raw = a["documentos_json"] if "documentos_json" in a.keys() else None
            except Exception:
                raw = None
            docs = parse_documentos_json(raw)
            if docs:
                docs_por_atividade[a["id"]] = docs
    except Exception:
        pass

    if request.method == "POST":
        aluno_usuario_id = session["user_id"]
        aluno_info = conn.execute(
            "SELECT id, nome FROM alunos WHERE usuario_id = ?",
            (aluno_usuario_id,),
        ).fetchone()
        if not aluno_info:
            flash("Dados do aluno não encontrados.", "error")
            return redirect(url_for("login"))
        aluno_id = aluno_info["id"]

        atividade_id = request.form["atividade_id"]
        nome_evento = request.form.get("nome_evento")
        data_evento = request.form["data_evento"]
        horas_solicitadas = float(request.form["horas_solicitadas"])
        observacao = request.form.get("observacao")
        # Suporte a múltiplos comprovantes
        arquivos = request.files.getlist("comprovantes_files") or []
        labels   = request.form.getlist("comprovantes_labels") or []
        # Backward-compat: se existir campo único
        arquivo_comprovante_legacy = request.files.get("arquivo_comprovante")
        if (not arquivos or all((not f or not getattr(f, 'filename', '')) for f in arquivos)) and arquivo_comprovante_legacy and arquivo_comprovante_legacy.filename:
            arquivos = [arquivo_comprovante_legacy]
            labels = ["Comprovante"]

        # Primeiro arquivo (se existir) mantém compat na coluna antiga
        first_filename = None  # será definido após salvar o primeiro arquivo válido
        
        data_solicitacao = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO requisicoes 
                (aluno_id, atividade_id, data_solicitacao, data_evento, horas_solicitadas, nome_evento, status, observacao, arquivo_comprovante)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (aluno_id, atividade_id, data_solicitacao, data_evento, horas_solicitadas, nome_evento, "Pendente", observacao, first_filename))
            req_id = cur.lastrowid

            # Cria tabela de anexos se não existir
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS requisicao_arquivos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    requisicao_id INTEGER NOT NULL,
                    label TEXT,
                    filename TEXT,
                    criado_em TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY(requisicao_id) REFERENCES requisicoes(id)
                )
                """
            )

            # Salva arquivos enviados e persiste
            saved_any = False
            first_saved = None
            student_name = str(aluno_info["nome"] or session.get("user_name") or f"aluno-{aluno_id}")
            for idx, f in enumerate(arquivos):
                if not f or not getattr(f, 'filename', ''):
                    continue
                if not _allowed(f.filename, ALLOWED_ATTACHMENTS):
                    logger.warning(f"Arquivo ignorado por extensão não permitida: {f.filename}")
                    continue
                try:
                    fname = save_student_document(
                        f,
                        ALLOWED_ATTACHMENTS,
                        root_folder=app.config["DOCUMENTOS_ALUNOS_FOLDER"],
                        student_id=aluno_id,
                        student_name=student_name,
                        category="requisicoes",
                        prefix=f"req{req_id}",
                    )
                    if first_saved is None:
                        first_saved = fname
                    lbl = None
                    if labels and idx < len(labels):
                        lbl = labels[idx]
                    conn.execute(
                        "INSERT INTO requisicao_arquivos (requisicao_id, label, filename) VALUES (?, ?, ?)",
                        (req_id, lbl, fname)
                    )
                    saved_any = True
                except Exception as _e:
                    logger.error(f"Falha ao salvar arquivo de comprovante: {_e}")

            # Atualiza coluna legado com o primeiro arquivo salvo
            if first_saved:
                conn.execute("UPDATE requisicoes SET arquivo_comprovante = ? WHERE id = ?", (first_saved, req_id))

            conn.commit()
            flash("Requisição enviada com sucesso.", "success")
            return redirect(aluno_url("aluno_dashboard"))
        except Exception as e:
            flash(f"Erro ao enviar requisição: {e}", "error")
            logger.error(f"Erro ao enviar requisição: {e}")
            traceback.print_exc()

    return render_template("aluno_nova_requisicao.html", atividades=atividades, tipo_atual=tipo_filtro, docs_por_atividade=docs_por_atividade)

@aluno_runtime_route("/aluno/meus_dados", methods=["GET", "POST"])
@aluno_required
def aluno_meus_dados():
    if "user_id" not in session or session.get("user_type") != "aluno":
        flash("Acesso não autorizado.", "error")
        return redirect(url_for("login"))

    conn = get_db_connection()
    usuario_id = session["user_id"]
    aluno = conn.execute("SELECT u.nome, u.email, a.matricula, a.turma_id FROM usuarios u JOIN alunos a ON u.id = a.usuario_id WHERE u.id = ?", (usuario_id,)).fetchone()

    if request.method == "POST":
        nome = request.form["nome"]
        email = request.form["email"]
        matricula = request.form["matricula"]
        turma_id = request.form.get("turma_id", type=int)
        senha = request.form.get("senha")
        turma_id_anterior = aluno["turma_id"]

        try:
            if senha:
                hashed_password = hash_password(senha)
                conn.execute("UPDATE usuarios SET nome = ?, email = ?, senha = ? WHERE id = ?", (nome, email, hashed_password, usuario_id))
            else:
                conn.execute("UPDATE usuarios SET nome = ?, email = ? WHERE id = ?", (nome, email, usuario_id))
            
            conn.execute("UPDATE alunos SET nome = ?, matricula = ?, email = ?, turma_id = ? WHERE usuario_id = ?", 
                         (nome, matricula, email, turma_id, usuario_id))
            resequence_turma_aluno_matriculas_for_ids(conn, turma_id_anterior, turma_id)
            conn.commit()
            flash("Seus dados foram atualizados com sucesso.", "success")
            return redirect(aluno_url("aluno_dashboard"))
        except sqlite3.IntegrityError as e:
            if "UNIQUE constraint failed: usuarios.email" in str(e):
                flash("Erro: Já existe outro usuário com este e-mail.", "error")
            elif "UNIQUE constraint failed: alunos.matricula" in str(e):
                flash("Erro: Já existe outro aluno com esta matrícula.", "error")
            else:
                flash(f"Erro ao atualizar dados: {e}", "error")
        except Exception as e:
            flash(f"Erro inesperado ao atualizar dados: {e}", "error")

    turmas = conn.execute("""
        SELECT t.id, COALESCE(t.codigo, t.nome) AS nome
          FROM turmas t
         WHERE t.status='Ativa'
      ORDER BY t.ano DESC, t.semestre DESC, nome
    """).fetchall()
    return render_template("aluno_meus_dados.html", aluno=aluno, turmas=turmas)


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


@app.route("/admin/matrizes")
@admin_required
def admin_matrizes():
    page, per_page, offset = get_pagination(default_per_page=25)
    q = (request.args.get("q") or "").strip()
    sort_field = (request.args.get("s") or "nome").strip().lower()
    sort_dir = (request.args.get("dir") or "asc").strip().lower()
    nome_filter = get_text_query_value("nome")
    versao_filter = get_text_query_value("versao")
    inicio_min, inicio_max = get_date_range_query("data_inicio_vigencia")
    fim_min, fim_max = get_date_range_query("data_fim_vigencia")
    horas_aac_min, horas_aac_max = get_number_range_query("horas_aac_obrigatorias")
    horas_extensao_min, horas_extensao_max = get_number_range_query("horas_extensao_obrigatorias")
    status_filters = {item.lower() for item in get_multi_query_values("status") if item}
    curso_filters = {
        int(item)
        for item in get_multi_query_values("curso_id")
        if str(item).strip().isdigit()
    }

    conn = get_db_connection()
    ensure_matrizes_atividades_table(conn)
    ensure_matriz_atividade_links_table(conn)

    where = []
    params = []
    if q:
        like = f"%{q}%"
        where.append(
            "(COALESCE(m.nome, '') LIKE ? OR COALESCE(c.nome, '') LIKE ? OR COALESCE(m.versao, '') LIKE ?)"
        )
        params.extend([like, like, like])
    append_text_contains_condition(where, params, "m.nome", nome_filter)
    append_text_contains_condition(where, params, "m.versao", versao_filter)
    if status_filters:
        placeholders = ", ".join("?" for _ in status_filters)
        where.append(f"LOWER(COALESCE(m.status, 'rascunho')) IN ({placeholders})")
        params.extend(sorted(status_filters))
    if curso_filters:
        placeholders = ", ".join("?" for _ in curso_filters)
        where.append(f"m.curso_id IN ({placeholders})")
        params.extend(sorted(curso_filters))
    if horas_aac_min is not None:
        where.append("COALESCE(m.horas_aac_obrigatorias, 0) >= ?")
        params.append(horas_aac_min)
    if horas_aac_max is not None:
        where.append("COALESCE(m.horas_aac_obrigatorias, 0) <= ?")
        params.append(horas_aac_max)
    if horas_extensao_min is not None:
        where.append("COALESCE(m.horas_extensao_obrigatorias, 0) >= ?")
        params.append(horas_extensao_min)
    if horas_extensao_max is not None:
        where.append("COALESCE(m.horas_extensao_obrigatorias, 0) <= ?")
        params.append(horas_extensao_max)
    if inicio_min:
        where.append("date(m.data_inicio_vigencia) >= date(?)")
        params.append(inicio_min)
    if inicio_max:
        where.append("date(m.data_inicio_vigencia) <= date(?)")
        params.append(inicio_max)
    if fim_min:
        where.append("date(m.data_fim_vigencia) >= date(?)")
        params.append(fim_min)
    if fim_max:
        where.append("date(m.data_fim_vigencia) <= date(?)")
        params.append(fim_max)

    order_map = {
        "nome": "LOWER(COALESCE(m.nome, ''))",
        "curso": "LOWER(COALESCE(c.nome, ''))",
        "versao": "LOWER(COALESCE(m.versao, ''))",
        "vigencia": "COALESCE(m.data_inicio_vigencia, ''), COALESCE(m.data_fim_vigencia, '')",
        "status": "LOWER(COALESCE(m.status, 'rascunho'))",
        "horas_aac_obrigatorias": "m.horas_aac_obrigatorias",
        "horas_extensao_obrigatorias": "m.horas_extensao_obrigatorias",
    }
    order_sql = order_map.get(sort_field, order_map["nome"])
    direction = "DESC" if sort_dir == "desc" else "ASC"

    base_from = " FROM matrizes_atividades m LEFT JOIN cursos c ON c.id = m.curso_id"
    where_sql = append_conditions_sql(False, where)
    total = conn.execute("SELECT COUNT(*)" + base_from + where_sql, params).fetchone()[0]

    query = (
        "SELECT m.*, COALESCE(c.nome, 'Curso não encontrado') AS curso_nome, COALESCE(c.codigo, '') AS curso_codigo"
        + base_from
        + where_sql
        + f" ORDER BY {order_sql} {direction}, m.id DESC"
    )
    query_params = list(params)
    apply_limit = wants_pagination()
    if apply_limit:
        query += " LIMIT ? OFFSET ?"
        query_params.extend([per_page, offset])
    rows = conn.execute(query, query_params).fetchall()

    cursos = conn.execute("SELECT id, nome, codigo FROM cursos ORDER BY LOWER(nome), id").fetchall()
    filter_schema = [
        {
            "param": "nome",
            "label": "Nome",
            "type": "text_contains",
            "placeholder": "Contém no nome",
        },
        {
            "param": "curso_id",
            "label": "Curso",
            "type": "multi_select",
            "values": [
                {
                    "value": str(curso["id"]),
                    "label": f"{curso['nome']} ({curso['codigo']})" if curso["codigo"] else curso["nome"],
                }
                for curso in cursos
            ],
        },
        {
            "param": "versao",
            "label": "Versão",
            "type": "text_contains",
            "placeholder": "Contém na versão",
        },
        {
            "param": "data_inicio_vigencia",
            "label": "Vigência inicial",
            "type": "date_range",
            "min_label": "De",
            "max_label": "Até",
        },
        {
            "param": "data_fim_vigencia",
            "label": "Vigência final",
            "type": "date_range",
            "min_label": "De",
            "max_label": "Até",
        },
        {
            "param": "horas_aac_obrigatorias",
            "label": "AAC (h)",
            "type": "number_range",
            "min_label": "Mínimo",
            "max_label": "Máximo",
        },
        {
            "param": "horas_extensao_obrigatorias",
            "label": "Extensão (h)",
            "type": "number_range",
            "min_label": "Mínimo",
            "max_label": "Máximo",
        },
        {
            "param": "status",
            "label": "Status",
            "type": "multi_select",
            "values": [
                {"value": "rascunho", "label": "Rascunho"},
                {"value": "vigente", "label": "Vigente"},
                {"value": "encerrada", "label": "Encerrada"},
            ],
        },
    ]
    matrizes = [
        {
            "id": row["id"],
            "nome": row["nome"],
            "curso": row["curso_nome"],
            "versao": row["versao"],
            "vigencia": _matriz_vigencia_label(row),
            "horas_aac_obrigatorias": row["horas_aac_obrigatorias"] or 0,
            "horas_extensao_obrigatorias": row["horas_extensao_obrigatorias"] or 0,
            "status": _matriz_status_label(row["status"]),
            "status_badge_type": _matriz_status_badge_type(row["status"]),
            "view_url": url_for("admin_editar_matriz", matriz_id=row["id"], tab="dados"),
            "edit_url": url_for("admin_editar_matriz", matriz_id=row["id"], tab="dados"),
            "delete_url": url_for("admin_excluir_matriz", matriz_id=row["id"]),
            "manage_academicas_url": url_for("admin_editar_matriz", matriz_id=row["id"], tab="aac"),
            "manage_extensao_url": url_for("admin_editar_matriz", matriz_id=row["id"], tab="aea"),
        }
        for row in rows
    ]
    total_pages = (total + per_page - 1) // per_page if apply_limit and per_page else 1
    return render_template(
        "admin_matrizes.html",
        matrizes=matrizes,
        filter_schema=filter_schema,
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages,
    )


MATRIZ_STATUS_META = {
    "rascunho": {"label": "Rascunho", "badge_type": "warning"},
    "vigente": {"label": "Vigente", "badge_type": "success"},
    "encerrada": {"label": "Encerrada", "badge_type": "danger"},
}


def _matriz_status_label(status: str | None) -> str:
    normalized = (status or "rascunho").strip().lower()
    return MATRIZ_STATUS_META.get(normalized, MATRIZ_STATUS_META["rascunho"])["label"]


def _matriz_status_badge_type(status: str | None) -> str:
    normalized = (status or "rascunho").strip().lower()
    return MATRIZ_STATUS_META.get(normalized, MATRIZ_STATUS_META["rascunho"])["badge_type"]


def _matriz_vigencia_label(row) -> str:
    def _format_date_ptbr(value: str) -> str:
        raw = (value or "").strip()
        if not raw:
            return ""
        base = raw[:10]
        try:
            return datetime.datetime.strptime(base, "%Y-%m-%d").strftime("%d/%m/%Y")
        except ValueError:
            return raw

    inicio = _format_date_ptbr(row["data_inicio_vigencia"])
    fim = _format_date_ptbr(row["data_fim_vigencia"])
    if inicio and fim:
        return f"{inicio} a {fim}"
    if inicio:
        return f"A partir de {inicio}"
    if fim:
        return f"Até {fim}"
    return "-"


def _matriz_activity_type_for_tab(active_tab: str) -> str | None:
    if active_tab == "aac":
        return "Acadêmica Complementar"
    if active_tab == "aea":
        return "Extensão Universitária"
    return None


def _matriz_axis_for_tab(active_tab: str) -> str | None:
    if active_tab == "aac":
        return "AAC"
    if active_tab == "aea":
        return "AEU"
    return None


def _get_grupos_por_tipo(conn) -> dict[str, dict[str, str]]:
    rows = conn.execute(
        "SELECT tipo_atividade, grupo FROM atividades WHERE grupo IS NOT NULL AND TRIM(grupo) <> ''"
    ).fetchall()
    grupos = {}
    for row in rows:
        tipo = row["tipo_atividade"]
        label = (row["grupo"] or "").strip()
        match = re.match(r"^\s*(\d+)\s*-\s*(.*)$", label)
        if match:
            numero = match.group(1)
            descricao = (match.group(2) or "").strip()
        else:
            match = re.match(r"^\s*(\d+)\s*$", label)
            if not match:
                continue
            numero = match.group(1)
            descricao = ""
        if tipo not in grupos:
            grupos[tipo] = {}
        if numero not in grupos[tipo] or (not grupos[tipo][numero] and descricao):
            grupos[tipo][numero] = descricao
    try:
        rows = conn.execute("SELECT tipo_atividade, numero, descricao FROM grupos_def").fetchall()
        for row in rows:
            tipo = row["tipo_atividade"]
            numero = str(row["numero"])
            descricao = (row["descricao"] or "").strip()
            if tipo not in grupos:
                grupos[tipo] = {}
            grupos[tipo][numero] = descricao
    except Exception:
        pass
    return grupos


def _get_matriz_active_normas_for_axis(conn, matriz_id: int, eixo: str) -> list:
    return conn.execute(
        """
        SELECT
            n.id,
            n.codigo,
            n.eixo,
            n.revisao,
            n.nome
          FROM matriz_norma mn
          JOIN norma_atividade n ON n.id = mn.norma_id
         WHERE mn.matriz_id = ?
           AND n.eixo = ?
           AND n.status = 'ativa'
         ORDER BY LOWER(n.codigo) ASC, n.id ASC
        """,
        (matriz_id, eixo),
    ).fetchall()


def _build_matriz_new_activity_modal_context(
    conn,
    matriz,
    active_tab: str,
    *,
    form_data: dict | None = None,
    is_open: bool = False,
):
    matriz_id = matriz["id"] if matriz else None
    activity_type = _matriz_activity_type_for_tab(active_tab)
    axis = _matriz_axis_for_tab(active_tab)
    if not matriz_id or not activity_type or not axis:
        return None

    form_data = form_data or {}
    grupos_por_tipo = _get_grupos_por_tipo(conn)
    group_map = grupos_por_tipo.get(activity_type, {})

    def _group_sort_key(value: str):
        normalized = str(value or "").strip()
        if normalized.isdigit():
            return (0, int(normalized))
        return (1, normalized.lower())

    group_suggestions = [
        {"numero": numero, "descricao": group_map[numero]}
        for numero in sorted(group_map.keys(), key=_group_sort_key)
    ]
    try:
        normas = _get_matriz_active_normas_for_axis(conn, matriz_id, axis)
    except sqlite3.OperationalError:
        normas = []

    raw_add_to_matrix = form_data.get("add_to_matrix")
    if raw_add_to_matrix is None:
        add_to_matrix_checked = True
    elif isinstance(raw_add_to_matrix, bool):
        add_to_matrix_checked = raw_add_to_matrix
    else:
        add_to_matrix_checked = str(raw_add_to_matrix).strip().lower() in {"1", "true", "on", "yes"}

    return {
        "is_open": bool(is_open),
        "form_action": url_for("admin_matriz_nova_atividade", matriz_id=matriz_id, active_tab=active_tab),
        "activity_type_label": activity_type,
        "axis": axis,
        "matrix_context_label": (matriz["nome"] or "").strip(),
        "group_suggestions": group_suggestions,
        "normas": normas,
        "norm_count": len(normas),
        "has_normas": bool(normas),
        "requires_norma_selection": len(normas) > 1,
        "single_norma": normas[0] if len(normas) == 1 else None,
        "submit_disabled": not normas,
        "prefill": {
            "nome": str(form_data.get("nome") or "").strip(),
            "grupo_numero": str(form_data.get("grupo_numero") or "").strip(),
            "grupo_descricao": str(form_data.get("grupo_descricao") or "").strip(),
            "norma_id": str(form_data.get("norma_id") or "").strip(),
            "add_to_matrix": add_to_matrix_checked,
        },
    }


def _matriz_transfer_meta(active_tab: str) -> dict[str, str]:
    if active_tab == "aea":
        return {
            "help_text": "Selecione quais atividades de extensão pertencem a esta matriz.",
            "available_title": "Atividades de extensão disponíveis",
            "selected_title": "Atividades de extensão vinculadas",
            "empty_available": "Nenhuma atividade de extensão disponível.",
            "empty_selected": "Nenhuma atividade de extensão vinculada.",
        }
    return {
        "help_text": "Selecione quais atividades acadêmicas complementares pertencem a esta matriz.",
        "available_title": "Atividades AAC disponíveis",
        "selected_title": "Atividades AAC vinculadas",
        "empty_available": "Nenhuma atividade AAC disponível.",
        "empty_selected": "Nenhuma atividade AAC vinculada.",
    }


def _matriz_activity_rule_summary(row) -> str:
    if not row["tem_limitacao"]:
        return "Sem limitação"
    tipo_limitacao = _canonicalize_tipo_limitacao(row["tipo_limitacao"])
    if tipo_limitacao == "total" and row["limite_horas_total"] is not None:
        return f"Limite total: {row['limite_horas_total']} h"
    if tipo_limitacao == "semestral" and row["limite_horas_semestral"] is not None:
        return f"Limite semestral: {row['limite_horas_semestral']} h"
    if row["limite_horas"] is not None:
        return f"Limite base: {row['limite_horas']} h"
    return "Com limitação"


def _matriz_transfer_lists(conn, matriz_id: int, active_tab: str):
    activity_type = _matriz_activity_type_for_tab(active_tab)
    if not activity_type:
        return [], [], []

    selected_ids = {
        row["atividade_id"]
        for row in conn.execute(
            "SELECT atividade_id FROM matrizes_atividades_itens WHERE matriz_id = ?",
            (matriz_id,),
        ).fetchall()
    }
    rows = conn.execute(
        """
        SELECT
            id,
            nome,
            COALESCE(NULLIF(TRIM(grupo), ''), 'Sem grupo') AS grupo,
            limite_horas,
            tem_limitacao,
            tipo_limitacao,
            limite_horas_total,
            limite_horas_semestral
        FROM atividades
        WHERE COALESCE(tipo_atividade, 'Acadêmica Complementar') = ?
        ORDER BY LOWER(COALESCE(grupo, '')), LOWER(nome), id
        """,
        (activity_type,),
    ).fetchall()

    available = []
    selected = []
    groups = set()
    for row in rows:
        groups.add(row["grupo"])
        item = {
            "id": row["id"],
            "nome": row["nome"],
            "grupo": row["grupo"],
            "rule_summary": _matriz_activity_rule_summary(row),
        }
        item["search_blob"] = " ".join(
            [
                str(item["nome"] or "").strip().lower(),
                str(item["grupo"] or "").strip().lower(),
                str(item["rule_summary"] or "").strip().lower(),
            ]
        ).strip()
        if row["id"] in selected_ids:
            selected.append(item)
        else:
            available.append(item)

    return available, selected, sorted(groups, key=lambda value: value.lower())


def _matriz_counts(conn, matriz_id: int) -> tuple[int, int]:
    counts = {"Acadêmica Complementar": 0, "Extensão Universitária": 0}
    rows = conn.execute(
        """
        SELECT COALESCE(a.tipo_atividade, 'Acadêmica Complementar') AS tipo_atividade, COUNT(*) AS total
        FROM matrizes_atividades_itens mi
        JOIN atividades a ON a.id = mi.atividade_id
        WHERE mi.matriz_id = ?
        GROUP BY COALESCE(a.tipo_atividade, 'Acadêmica Complementar')
        """,
        (matriz_id,),
    ).fetchall()
    for row in rows:
        counts[row["tipo_atividade"]] = row["total"]
    return counts["Acadêmica Complementar"], counts["Extensão Universitária"]


def _render_matriz_form(
    conn,
    matriz=None,
    active_tab: str = "dados",
    readonly: bool = False,
    new_activity_modal=None,
):
    cursos = conn.execute("SELECT id, nome, codigo FROM cursos ORDER BY LOWER(nome), id").fetchall()
    matriz_id = matriz["id"] if matriz else None
    activity_tabs_enabled = bool(matriz_id)
    if active_tab not in {"dados", "aac", "aea"}:
        active_tab = "dados"
    if not activity_tabs_enabled:
        active_tab = "dados"

    academicas_count = 0
    extensao_count = 0
    transfer_available = []
    transfer_selected = []
    transfer_groups = []
    if matriz_id:
        academicas_count, extensao_count = _matriz_counts(conn, matriz_id)
        if active_tab in {"aac", "aea"}:
            transfer_available, transfer_selected, transfer_groups = _matriz_transfer_lists(conn, matriz_id, active_tab)
            if new_activity_modal is None:
                new_activity_modal = _build_matriz_new_activity_modal_context(conn, matriz, active_tab)
    else:
        new_activity_modal = None

    card_version_menu_data = {}
    if matriz_id and active_tab in {"aac", "aea"} and not readonly:
        selected_ids = [item["id"] for item in transfer_selected]
        if selected_ids:
            try:
                raw_menu = get_card_version_menu_data(conn, matriz_id, selected_ids)
                for lid_str, entry in raw_menu.items():
                    entry["form_action"] = url_for(
                        "admin_matriz_nova_versao_card",
                        matriz_id=matriz_id,
                        atividade_id=int(lid_str),
                    )
                card_version_menu_data = raw_menu
            except Exception:
                card_version_menu_data = {}

    return render_template(
        "admin_matriz_form.html",
        matriz_title="Nova matriz de atividades" if not matriz_id else "Editar matriz de atividades",
        active_tab=active_tab,
        matriz_id=matriz_id,
        cursos=cursos,
        matriz=matriz,
        submit_label="Salvar matriz" if not matriz_id else "Salvar alterações",
        back_url=url_for("admin_matrizes"),
        cancel_label="Voltar",
        activity_tabs_enabled=activity_tabs_enabled,
        academicas_count=academicas_count,
        extensao_count=extensao_count,
        manage_academicas_url=url_for("admin_editar_matriz", matriz_id=matriz_id, tab="aac") if matriz_id else "",
        manage_extensao_url=url_for("admin_editar_matriz", matriz_id=matriz_id, tab="aea") if matriz_id else "",
        transfer_meta=_matriz_transfer_meta(active_tab),
        transfer_available=transfer_available,
        transfer_selected=transfer_selected,
        transfer_groups=transfer_groups,
        new_activity_modal=new_activity_modal,
        card_version_menu_data=card_version_menu_data,
        readonly=readonly,
    )


def _matriz_payload_from_request(conn):
    curso_id = request.form.get("curso_id", type=int)
    nome = (request.form.get("nome") or "").strip()
    versao = (request.form.get("versao") or "").strip()
    status = (request.form.get("status") or "rascunho").strip().lower()
    data_inicio_vigencia = (request.form.get("data_inicio_vigencia") or "").strip() or None
    data_fim_vigencia = (request.form.get("data_fim_vigencia") or "").strip() or None
    horas_aac_obrigatorias = request.form.get("horas_aac_obrigatorias", type=int)
    horas_extensao_obrigatorias = request.form.get("horas_extensao_obrigatorias", type=int)
    descricao = (request.form.get("descricao") or "").strip() or None

    if not curso_id:
        return None, "Selecione um curso para a matriz."
    curso = conn.execute("SELECT id FROM cursos WHERE id = ?", (curso_id,)).fetchone()
    if not curso:
        return None, "Curso inválido para a matriz."
    if not nome:
        return None, "Informe o nome da matriz."
    if not versao:
        return None, "Informe a versão da matriz."
    if status not in MATRIZ_STATUS_META:
        return None, "Status de matriz inválido."
    if horas_aac_obrigatorias is None or horas_aac_obrigatorias < 0:
        return None, "Informe uma carga horária AAC válida."
    if horas_extensao_obrigatorias is None or horas_extensao_obrigatorias < 0:
        return None, "Informe uma carga horária de extensão válida."
    if data_inicio_vigencia and data_fim_vigencia and data_fim_vigencia < data_inicio_vigencia:
        return None, "A data final de vigência não pode ser anterior à inicial."

    return {
        "curso_id": curso_id,
        "nome": nome,
        "versao": versao,
        "status": status,
        "data_inicio_vigencia": data_inicio_vigencia,
        "data_fim_vigencia": data_fim_vigencia,
        "horas_aac_obrigatorias": horas_aac_obrigatorias,
        "horas_extensao_obrigatorias": horas_extensao_obrigatorias,
        "descricao": descricao,
    }, None


def _ensure_default_versao_link(conn, matriz_id: int, activity_id: int) -> None:
    """
    Create a default matrix→versao link for activity_id if none exists yet.
    Uses the latest active versao of the activity's base. No-op when:
    - activity has no legacy map entry
    - the base has no active versao
    - a link already exists (manual choice preserved)
    Does not commit — caller's responsibility.
    """
    row = conn.execute(
        "SELECT atividade_base_id FROM atividade_legacy_map WHERE atividade_id_legacy = ?",
        (activity_id,),
    ).fetchone()
    if not row:
        return
    base_id = row["atividade_base_id"]
    if get_vinculo_versao_da_matriz(conn, matriz_id, base_id):
        return
    latest = get_ultima_versao_ativa_por_base(conn, base_id)
    if not latest:
        return
    _set_versao_da_matriz_para_base(conn, matriz_id, base_id, latest["id"])


def _save_matriz_activity_links(conn, matriz_id: int, active_tab: str):
    activity_type = _matriz_activity_type_for_tab(active_tab)
    if not activity_type:
        return False

    selected_ids = []
    for raw_value in request.form.getlist("selected_activity_ids"):
        if str(raw_value).strip().isdigit():
            selected_ids.append(int(raw_value))
    selected_ids = sorted(set(selected_ids))

    type_activity_ids = {
        row["id"]
        for row in conn.execute(
            "SELECT id FROM atividades WHERE COALESCE(tipo_atividade, 'Acadêmica Complementar') = ?",
            (activity_type,),
        ).fetchall()
    }
    valid_ids = [activity_id for activity_id in selected_ids if activity_id in type_activity_ids]

    conn.execute(
        """
        DELETE FROM matrizes_atividades_itens
        WHERE matriz_id = ?
          AND atividade_id IN (
              SELECT id FROM atividades WHERE COALESCE(tipo_atividade, 'Acadêmica Complementar') = ?
          )
        """,
        (matriz_id, activity_type),
    )
    if valid_ids:
        conn.executemany(
            "INSERT INTO matrizes_atividades_itens (matriz_id, atividade_id) VALUES (?, ?)",
            [(matriz_id, activity_id) for activity_id in valid_ids],
        )
        for activity_id in valid_ids:
            _ensure_default_versao_link(conn, matriz_id, activity_id)
    conn.commit()
    return True


@app.route("/admin/adicionar_matriz", methods=["GET", "POST"])
@admin_required
def admin_adicionar_matriz():
    conn = get_db_connection()
    ensure_matrizes_atividades_table(conn)
    ensure_matriz_atividade_links_table(conn)

    if request.method == "POST":
        payload, error_message = _matriz_payload_from_request(conn)
        if error_message:
            flash(error_message, "error")
            return _render_matriz_form(conn)
        cursor = conn.execute(
            """
            INSERT INTO matrizes_atividades (
                curso_id,
                nome,
                versao,
                status,
                data_inicio_vigencia,
                data_fim_vigencia,
                horas_aac_obrigatorias,
                horas_extensao_obrigatorias,
                descricao
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["curso_id"],
                payload["nome"],
                payload["versao"],
                payload["status"],
                payload["data_inicio_vigencia"],
                payload["data_fim_vigencia"],
                payload["horas_aac_obrigatorias"],
                payload["horas_extensao_obrigatorias"],
                payload["descricao"],
            ),
        )
        conn.commit()
        flash("Matriz criada com sucesso.", "success")
        return redirect(url_for("admin_editar_matriz", matriz_id=cursor.lastrowid, tab="dados"))

    return _render_matriz_form(conn)


@app.route("/admin/editar_matriz/<int:matriz_id>", methods=["GET", "POST"])
@admin_required
def admin_editar_matriz(matriz_id: int):
    conn = get_db_connection()
    ensure_matrizes_atividades_table(conn)
    ensure_matriz_atividade_links_table(conn)

    matriz = conn.execute("SELECT * FROM matrizes_atividades WHERE id = ?", (matriz_id,)).fetchone()
    if not matriz:
        flash("Matriz não encontrada.", "error")
        return redirect(url_for("admin_matrizes"))

    auth_context = _get_current_admin_access_context()
    readonly = not _admin_can("matrizes", "edit", auth_context)

    active_tab = (request.values.get("tab") or request.values.get("active_tab") or "dados").strip().lower()
    if active_tab not in {"dados", "aac", "aea"}:
        active_tab = "dados"

    if request.method == "POST":
        if active_tab == "dados":
            payload, error_message = _matriz_payload_from_request(conn)
            if error_message:
                flash(error_message, "error")
                matriz = conn.execute("SELECT * FROM matrizes_atividades WHERE id = ?", (matriz_id,)).fetchone()
                return _render_matriz_form(conn, matriz=matriz, active_tab="dados", readonly=readonly)
            conn.execute(
                """
                UPDATE matrizes_atividades
                SET curso_id = ?,
                    nome = ?,
                    versao = ?,
                    status = ?,
                    data_inicio_vigencia = ?,
                    data_fim_vigencia = ?,
                    horas_aac_obrigatorias = ?,
                    horas_extensao_obrigatorias = ?,
                    descricao = ?
                WHERE id = ?
                """,
                (
                    payload["curso_id"],
                    payload["nome"],
                    payload["versao"],
                    payload["status"],
                    payload["data_inicio_vigencia"],
                    payload["data_fim_vigencia"],
                    payload["horas_aac_obrigatorias"],
                    payload["horas_extensao_obrigatorias"],
                    payload["descricao"],
                    matriz_id,
                ),
            )
            conn.commit()
            flash("Matriz atualizada com sucesso.", "success")
            return redirect(url_for("admin_editar_matriz", matriz_id=matriz_id, tab="dados"))

        if _save_matriz_activity_links(conn, matriz_id, active_tab):
            flash("Lista da matriz atualizada com sucesso.", "success")
        else:
            flash("Aba de gestão de atividades inválida.", "error")
        return redirect(url_for("admin_editar_matriz", matriz_id=matriz_id, tab=active_tab))

    matriz = conn.execute("SELECT * FROM matrizes_atividades WHERE id = ?", (matriz_id,)).fetchone()
    return _render_matriz_form(conn, matriz=matriz, active_tab=active_tab, readonly=readonly)


@app.route("/admin/matrizes/<int:matriz_id>/atividades/nova/<string:active_tab>", methods=["POST"])
@admin_required
def admin_matriz_nova_atividade(matriz_id: int, active_tab: str):
    conn = get_db_connection()
    ensure_atividades_schema_current(conn)
    ensure_matriz_atividade_links_table(conn)
    ensure_atividade_versioning_schema(conn)

    matriz = conn.execute("SELECT * FROM matrizes_atividades WHERE id = ?", (matriz_id,)).fetchone()
    if not matriz:
        flash("Matriz não encontrada.", "error")
        return redirect(url_for("admin_matrizes"))

    auth_context = _get_current_admin_access_context()
    readonly = not _admin_can("matrizes", "edit", auth_context)

    active_tab = (active_tab or "").strip().lower()
    activity_type = _matriz_activity_type_for_tab(active_tab)
    axis = _matriz_axis_for_tab(active_tab)
    if not activity_type or not axis:
        flash("Aba de gestão de atividades inválida.", "error")
        return redirect(url_for("admin_editar_matriz", matriz_id=matriz_id, tab="dados"))

    form_data = {
        "nome": (request.form.get("nome") or "").strip(),
        "grupo_numero": (request.form.get("grupo_numero") or "").strip(),
        "grupo_descricao": (request.form.get("grupo_descricao") or "").strip(),
        "norma_id": (request.form.get("norma_id") or "").strip(),
        "add_to_matrix": request.form.get("add_to_matrix"),
    }

    def _render_modal_error(message: str):
        if message:
            flash(message, "error")
        modal_context = _build_matriz_new_activity_modal_context(
            conn,
            matriz,
            active_tab,
            form_data=form_data,
            is_open=True,
        )
        return _render_matriz_form(
            conn,
            matriz=matriz,
            active_tab=active_tab,
            readonly=readonly,
            new_activity_modal=modal_context,
        )

    normas = _get_matriz_active_normas_for_axis(conn, matriz_id, axis)
    if not normas:
        return _render_modal_error(
            f"Esta matriz não possui norma ativa de {axis} vinculada para criar uma nova atividade."
        )

    norma_by_id = {int(row["id"]): row for row in normas}
    norma_id_raw = form_data["norma_id"]
    norma = None
    if norma_id_raw:
        if not norma_id_raw.isdigit():
            return _render_modal_error("Selecione uma norma/regulamento base válida.")
        norma = norma_by_id.get(int(norma_id_raw))
        if not norma:
            return _render_modal_error("Selecione uma norma compatível com esta matriz e com o eixo atual.")
    elif len(normas) == 1:
        norma = normas[0]
    else:
        return _render_modal_error("Selecione explicitamente a norma/regulamento base para esta atividade.")

    nome = form_data["nome"]
    if not nome:
        return _render_modal_error("Informe o nome da atividade.")

    if activity_type == "Acadêmica Complementar":
        grupo_numero = form_data["grupo_numero"]
        if not grupo_numero.isdigit():
            return _render_modal_error("Informe um número de grupo válido para a atividade AAC.")
        grupo_raw = _build_grupo_label(grupo_numero, form_data["grupo_descricao"])
    else:
        grupo_raw = "NA"
    grupo = _normalize_atividade_grupo(activity_type, grupo_raw)
    if activity_type != "Extensão Universitária" and not grupo:
        return _render_modal_error("Informe o grupo da atividade.")

    add_to_matrix = str(request.form.get("add_to_matrix") or "").strip().lower() in {"1", "true", "on", "yes"}
    form_data["add_to_matrix"] = add_to_matrix

    try:
        atividade_cursor = conn.execute(
            """
            INSERT INTO atividades (
                grupo,
                nome,
                descricao,
                limite_horas,
                tipo_atividade,
                tem_limitacao,
                tipo_limitacao,
                limite_horas_total,
                limite_horas_semestral
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                grupo,
                nome,
                None,
                None,
                activity_type,
                0,
                "total",
                None,
                None,
            ),
        )
        atividade_id = atividade_cursor.lastrowid

        base_cursor = conn.execute(
            """
            INSERT INTO atividade_base (nome_conceito, descricao, status)
            VALUES (?, ?, 'ativo')
            """,
            (nome, None),
        )
        base_id = base_cursor.lastrowid

        conn.execute(
            """
            INSERT INTO atividade_legacy_map (atividade_id_legacy, atividade_base_id, status)
            VALUES (?, ?, 'mapeada')
            """,
            (atividade_id, base_id),
        )

        if add_to_matrix:
            conn.execute(
                "INSERT INTO matrizes_atividades_itens (matriz_id, atividade_id) VALUES (?, ?)",
                (matriz_id, atividade_id),
            )

        next_num = get_next_numero_versao(conn, base_id)
        versao_cursor = conn.execute(
            """
            INSERT INTO atividade_versao (
                atividade_base_id,
                norma_id,
                codigo_normativo,
                eixo,
                grupo,
                numero_versao,
                status
            ) VALUES (?, ?, ?, ?, ?, ?, 'ativa')
            """,
            (
                base_id,
                norma["id"],
                norma["codigo"],
                norma["eixo"],
                grupo,
                next_num,
            ),
        )
        versao_id = versao_cursor.lastrowid

        if add_to_matrix:
            conn.execute(
                "INSERT INTO matriz_atividade_versao_item (matriz_id, atividade_versao_id) VALUES (?, ?)",
                (matriz_id, versao_id),
            )

        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        error_message = str(exc).lower()
        if "unique constraint failed: atividades.nome" in error_message:
            return _render_modal_error("Já existe atividade com este nome.")
        if "unique constraint failed: atividade_base.nome_conceito" in error_message:
            return _render_modal_error("Já existe atividade-base com este nome.")
        if "unique constraint failed: atividade_legacy_map.atividade_id_legacy" in error_message:
            return _render_modal_error("Falha ao mapear a atividade criada para a atividade-base.")
        if "unique constraint failed: atividade_versao.atividade_base_id, atividade_versao.numero_versao" in error_message:
            return _render_modal_error("Conflito ao atribuir número de versão. Tente novamente.")
        return _render_modal_error(f"Erro de integridade ao criar atividade: {exc}")
    except Exception as exc:
        conn.rollback()
        return _render_modal_error(f"Erro ao criar atividade: {exc}")

    if add_to_matrix:
        flash("Atividade criada e adicionada à matriz com sucesso.", "success")
    else:
        flash("Atividade criada com sucesso.", "success")
    return redirect(url_for("admin_editar_matriz", matriz_id=matriz_id, tab=active_tab))


# ===================== Rota Admin: Criar nova versão de atividade via card da matriz (D7.5D) =====================

@app.route(
    "/admin/matrizes/<int:matriz_id>/atividades/<int:atividade_id>/nova-versao",
    methods=["POST"],
)
@admin_required
def admin_matriz_nova_versao_card(matriz_id: int, atividade_id: int):
    """
    Relinka a matriz para uma versão operacional existente da atividade.

    Fluxo:
      A. Resolve atividade_base: atividade_id → base_id.
      B. Valida versao_id: deve existir, pertencer à mesma base_id.
      C. Relinka somente a matriz atual via _set_versao_da_matriz_para_base.

    Não cria atividade_versao — apenas escolhe entre as existentes.
    Não altera: outras matrizes, requisições, transições.
    CSRF obrigatório. Rollback total em erro intermediário.
    """
    conn = get_db_connection()
    ensure_atividade_versioning_schema(conn)
    ensure_matriz_atividade_links_table(conn)

    active_tab = (request.form.get("active_tab") or "").strip().lower()
    if active_tab not in {"aac", "aea"}:
        active_tab = "aac"

    def _redirect_matrix():
        return redirect(url_for("admin_editar_matriz", matriz_id=matriz_id, tab=active_tab))

    matriz = conn.execute("SELECT * FROM matrizes_atividades WHERE id = ?", (matriz_id,)).fetchone()
    if not matriz:
        flash("Matriz não encontrada.", "error")
        return redirect(url_for("admin_matrizes"))

    legacy_map = conn.execute(
        "SELECT atividade_base_id FROM atividade_legacy_map WHERE atividade_id_legacy = ?",
        (atividade_id,),
    ).fetchone()
    if not legacy_map:
        flash("Atividade não mapeada para uma atividade-base.", "error")
        return _redirect_matrix()
    base_id = legacy_map["atividade_base_id"]

    in_scope = conn.execute(
        "SELECT 1 FROM matrizes_atividades_itens WHERE matriz_id = ? AND atividade_id = ?",
        (matriz_id, atividade_id),
    ).fetchone() is not None
    if not in_scope:
        flash("A atividade não está vinculada a esta matriz.", "error")
        return _redirect_matrix()

    versao_id_raw = (request.form.get("versao_id") or "").strip()
    if not versao_id_raw or not versao_id_raw.isdigit():
        flash("Selecione uma versão existente.", "error")
        return _redirect_matrix()
    versao_id = int(versao_id_raw)

    target_versao = conn.execute(
        "SELECT id, atividade_base_id, numero_versao FROM atividade_versao WHERE id = ?",
        (versao_id,),
    ).fetchone()
    if not target_versao:
        flash("Versão não encontrada.", "error")
        return _redirect_matrix()
    if target_versao["atividade_base_id"] != base_id:
        flash("A versão selecionada não pertence a esta atividade.", "error")
        return _redirect_matrix()

    vinculo = get_vinculo_versao_da_matriz(conn, matriz_id, base_id)
    if vinculo and vinculo["atividade_versao_id"] == versao_id:
        flash("Esta versão já está vinculada a esta matriz.", "info")
        return _redirect_matrix()

    try:
        _set_versao_da_matriz_para_base(conn, matriz_id, base_id, versao_id)
        conn.commit()
        flash(
            f"v{target_versao['numero_versao']} selecionada para esta matriz.",
            "success",
        )
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        flash(f"Erro de integridade ao escolher versão: {exc}", "error")
    except Exception as exc:
        conn.rollback()
        flash(f"Erro ao escolher versão: {exc}", "error")

    return _redirect_matrix()


@app.route("/admin/matrizes/excluir", methods=["POST"])
@admin_required
def admin_excluir_matrizes():
    conn = get_db_connection()
    ensure_matrizes_atividades_table(conn)
    ensure_matriz_atividade_links_table(conn)

    matriz_ids = []
    for raw_value in request.form.getlist("matriz_ids"):
        if str(raw_value).strip().isdigit():
            matriz_ids.append(int(raw_value))
    matriz_ids = sorted(set(matriz_ids))
    if not matriz_ids:
        flash("Selecione ao menos uma matriz para excluir.", "error")
        return redirect(url_for("admin_matrizes"))

    placeholders = ", ".join("?" for _ in matriz_ids)
    conn.execute(f"DELETE FROM matrizes_atividades WHERE id IN ({placeholders})", matriz_ids)
    conn.commit()
    flash("Matrizes excluídas com sucesso.", "success")
    return redirect(url_for("admin_matrizes"))


@app.route("/admin/matrizes/<int:matriz_id>/excluir", methods=["POST"])
@admin_required
def admin_excluir_matriz(matriz_id: int):
    conn = get_db_connection()
    ensure_matrizes_atividades_table(conn)
    ensure_matriz_atividade_links_table(conn)

    deleted = conn.execute("DELETE FROM matrizes_atividades WHERE id = ?", (matriz_id,)).rowcount
    conn.commit()
    if deleted:
        flash("Matriz excluída com sucesso.", "success")
    else:
        flash("Matriz não encontrada.", "error")
    return redirect(url_for("admin_matrizes"))


# ===================== Rotas Admin: Vínculo Matriz → atividade_versao (D7.2B4) =====================

@app.route("/admin/matrizes/<int:matriz_id>/versoes")
@admin_required
def admin_matriz_versoes(matriz_id: int):
    """
    Página admin para gerenciar vínculos explícitos matriz→atividade_versao.

    Para cada atividade_base no escopo legado da matriz mostra:
      - vínculo atual (se houver);
      - versões ativas disponíveis (somente ativas, cujas normas estão em matriz_norma).

    GET-only — sem escrita. Escrita via POST /definir e POST /remover.
    Não usa fallback para primeira ativa. Sem inferência de versão.
    """
    conn = get_db_connection()
    ensure_atividade_versioning_schema(conn)
    matriz = conn.execute("SELECT * FROM matrizes_atividades WHERE id = ?", (matriz_id,)).fetchone()
    if not matriz:
        flash("Matriz não encontrada.", "error")
        return redirect(url_for("admin_matrizes"))

    bases = get_bases_escopo_matriz(conn, matriz_id)
    bases_info = []
    for base in bases:
        vinculo = get_vinculo_versao_da_matriz(conn, matriz_id, base["id"])
        versoes_disponiveis = get_versoes_ativas_por_base_na_matriz(conn, matriz_id, base["id"])
        bases_info.append({
            "base": base,
            "vinculo": vinculo,
            "versoes_disponiveis": versoes_disponiveis,
        })

    return render_template(
        "admin_matriz_versoes.html",
        matriz=matriz,
        bases_info=bases_info,
    )


@app.route("/admin/matrizes/<int:matriz_id>/versoes/definir", methods=["POST"])
@admin_required
def admin_matriz_versoes_definir(matriz_id: int):
    """
    Define (substitui) o vínculo matriz→atividade_versao para uma atividade_base.

    Validações server-side:
      1. Matriz existe.
      2. atividade_base existe.
      3. atividade_versao existe.
      4. atividade_versao pertence à atividade_base informada.
      5. atividade_versao.status == 'ativa'.
      6. atividade_base no escopo legado da matriz (matrizes_atividades_itens + atividade_legacy_map).
      7. norma_id da versão está em matriz_norma para esta matriz.

    Operação "set": remove vínculo anterior da mesma matriz+base e insere novo.
    Nunca cria ambiguidade nova (invariante por matriz+base).
    Rollback + flash em falha.
    """
    conn = get_db_connection()
    ensure_atividade_versioning_schema(conn)

    matriz = conn.execute("SELECT * FROM matrizes_atividades WHERE id = ?", (matriz_id,)).fetchone()
    if not matriz:
        flash("Matriz não encontrada.", "error")
        return redirect(url_for("admin_matrizes"))

    base_id_raw = (request.form.get("base_id") or "").strip()
    versao_id_raw = (request.form.get("versao_id") or "").strip()

    if not base_id_raw.isdigit() or not versao_id_raw.isdigit():
        flash("Parâmetros inválidos.", "error")
        return redirect(url_for("admin_matriz_versoes", matriz_id=matriz_id))

    base_id = int(base_id_raw)
    versao_id = int(versao_id_raw)

    base = get_atividade_base(conn, base_id)
    if not base:
        flash("Atividade-base não encontrada.", "error")
        return redirect(url_for("admin_matriz_versoes", matriz_id=matriz_id))

    versao = get_atividade_versao_by_id(conn, versao_id)
    if not versao:
        flash("Versão não encontrada.", "error")
        return redirect(url_for("admin_matriz_versoes", matriz_id=matriz_id))

    if versao["atividade_base_id"] != base_id:
        flash("A versão selecionada não pertence à atividade-base informada.", "error")
        return redirect(url_for("admin_matriz_versoes", matriz_id=matriz_id))

    if versao["status"] != "ativa":
        flash("Apenas versões com status 'ativa' podem ser vinculadas à matriz.", "error")
        return redirect(url_for("admin_matriz_versoes", matriz_id=matriz_id))

    in_scope = conn.execute(
        """
        SELECT 1
          FROM matrizes_atividades_itens mai
          JOIN atividade_legacy_map alm ON alm.atividade_id_legacy = mai.atividade_id
         WHERE mai.matriz_id = ?
           AND alm.atividade_base_id = ?
         LIMIT 1
        """,
        (matriz_id, base_id),
    ).fetchone() is not None
    if not in_scope:
        flash("A atividade-base não está no escopo legado desta matriz.", "error")
        return redirect(url_for("admin_matriz_versoes", matriz_id=matriz_id))

    norma_in_matriz = conn.execute(
        "SELECT 1 FROM matriz_norma WHERE matriz_id = ? AND norma_id = ?",
        (matriz_id, versao["norma_id"]),
    ).fetchone() is not None
    if not norma_in_matriz:
        flash("A norma desta versão não está vinculada a esta matriz.", "error")
        return redirect(url_for("admin_matriz_versoes", matriz_id=matriz_id))

    try:
        _set_versao_da_matriz_para_base(conn, matriz_id, base_id, versao_id)
        conn.commit()
        flash("Versão definida com sucesso.", "success")
    except Exception as exc:
        conn.rollback()
        flash(f"Erro ao definir versão: {exc}", "error")

    return redirect(url_for("admin_matriz_versoes", matriz_id=matriz_id))


@app.route("/admin/matrizes/<int:matriz_id>/versoes/remover", methods=["POST"])
@admin_required
def admin_matriz_versoes_remover(matriz_id: int):
    """
    Remove o vínculo matriz→atividade_versao para uma atividade_base.

    Validações server-side:
      1. Matriz existe.
      2. atividade_base existe.

    Idempotente: se não houver vínculo, retorna info sem erro.
    Rollback + flash em falha.
    """
    conn = get_db_connection()
    ensure_atividade_versioning_schema(conn)

    matriz = conn.execute("SELECT * FROM matrizes_atividades WHERE id = ?", (matriz_id,)).fetchone()
    if not matriz:
        flash("Matriz não encontrada.", "error")
        return redirect(url_for("admin_matrizes"))

    base_id_raw = (request.form.get("base_id") or "").strip()
    if not base_id_raw.isdigit():
        flash("Parâmetros inválidos.", "error")
        return redirect(url_for("admin_matriz_versoes", matriz_id=matriz_id))

    base_id = int(base_id_raw)

    base = get_atividade_base(conn, base_id)
    if not base:
        flash("Atividade-base não encontrada.", "error")
        return redirect(url_for("admin_matriz_versoes", matriz_id=matriz_id))

    try:
        rows_deleted = _remover_versao_da_matriz_para_base(conn, matriz_id, base_id)
        conn.commit()
        if rows_deleted:
            flash("Vínculo removido com sucesso.", "success")
        else:
            flash("Não havia vínculo para remover.", "info")
    except Exception as exc:
        conn.rollback()
        flash(f"Erro ao remover vínculo: {exc}", "error")

    return redirect(url_for("admin_matriz_versoes", matriz_id=matriz_id))


# ===================== Rotas Admin: Catálogo Versionado (read-only) =====================

@app.route("/admin/catalogo-versoes")
@admin_required
def admin_catalogo_versoes():
    """
    Lista todas as atividade_base com contagem de versões.
    GET-only, sem escrita no banco.
    """
    conn = get_db_connection()
    bases = get_atividade_base_list(conn)
    return render_template(
        "admin_catalogo_versoes.html",
        bases=bases,
    )


@app.route("/admin/catalogo-versoes/<int:base_id>")
@admin_required
def admin_catalogo_versao_detalhe(base_id: int):
    """
    Detalhe de uma atividade_base com todas as versões vinculadas.
    GET-only, sem escrita no banco.
    """
    conn = get_db_connection()
    base = get_atividade_base(conn, base_id)
    if not base:
        flash("Atividade-base não encontrada.", "error")
        return redirect(url_for("admin_catalogo_versoes"))
    versoes = get_versoes_por_base(conn, base_id)
    transicoes_origem = {
        row["from_atividade_versao_id"]
        for row in conn.execute(
            """
            SELECT DISTINCT from_atividade_versao_id
              FROM atividade_transicao
             WHERE from_atividade_versao_id IS NOT NULL
            """
        ).fetchall()
    }
    substituicao_candidatas = {}
    for origem in versoes:
        origem_id = origem["id"]
        origem_bloqueada = (
            origem["status"] != "ativa"
            or (origem["uso_em_matrizes"] or 0) > 0
            or origem_id in transicoes_origem
        )
        if origem_bloqueada:
            substituicao_candidatas[origem_id] = []
            continue
        substituicao_candidatas[origem_id] = [
            {
                "id": destino["id"],
                "codigo_normativo": destino["codigo_normativo"],
                "eixo": destino["eixo"],
            }
            for destino in versoes
            if destino["id"] != origem_id
            and destino["status"] == "ativa"
            and destino["eixo"] == origem["eixo"]
            and destino["id"] not in transicoes_origem
        ]
    transicoes_historico = get_atividade_transicoes_por_base(conn, base_id)
    return render_template(
        "admin_catalogo_versao_detalhe.html",
        base=base,
        versoes=versoes,
        substituicao_candidatas=substituicao_candidatas,
        transicoes_historico=transicoes_historico,
    )


@app.route("/admin/normas-atividade")
@admin_required
def admin_normas_atividade():
    """
    Lista todas as norma_atividade com contagem de versões vinculadas.
    GET-only, sem escrita no banco.
    """
    conn = get_db_connection()
    normas = get_norma_list(conn)
    return render_template(
        "admin_normas_atividade.html",
        normas=normas,
    )


@app.route("/admin/mapeamento-legado")
@admin_required
def admin_mapeamento_legado():
    """
    Lista atividades legadas com status de mapeamento para atividade_base.
    GET-only, sem inferência automática por nome, sem escrita no banco.
    """
    conn = get_db_connection()
    status_filter = (request.args.get("status") or "").strip().lower()
    mapa = get_legacy_map_list(conn)
    # Filtro opcional por status (pendente, mapeada, revisar, sem_mapa)
    if status_filter in ("pendente", "mapeada", "revisar", "sem_mapa"):
        if status_filter == "sem_mapa":
            mapa = [m for m in mapa if m["mapa_id"] is None]
        else:
            mapa = [m for m in mapa if (m["mapa_status"] or "") == status_filter]
    return render_template(
        "admin_mapeamento_legado.html",
        mapa=mapa,
        status_filter=status_filter,
    )


@app.route("/admin/catalogo-versoes/nova-base", methods=["GET", "POST"])
@admin_required
def admin_catalogo_nova_base():
    """
    Formulário para criar uma nova atividade_base.
    POST valida e insere; em sucesso redireciona para o detalhe da base criada.
    """
    if request.method == "POST":
        nome_conceito = (request.form.get("nome_conceito") or "").strip()
        descricao = (request.form.get("descricao") or "").strip()
        status = (request.form.get("status") or "").strip()

        if not nome_conceito:
            flash("Nome da atividade-base é obrigatório.", "error")
            return render_template("admin_catalogo_base_form.html",
                                   nome_conceito=nome_conceito,
                                   descricao=descricao,
                                   status=status)

        if status not in ("ativo", "inativo"):
            flash("Status deve ser 'ativo' ou 'inativo'.", "error")
            return render_template("admin_catalogo_base_form.html",
                                   nome_conceito=nome_conceito,
                                   descricao=descricao,
                                   status=status)

        conn = get_db_connection()

        existing = conn.execute(
            "SELECT id FROM atividade_base WHERE LOWER(nome_conceito) = LOWER(?)",
            (nome_conceito,),
        ).fetchone()
        if existing:
            flash("Já existe uma atividade-base com este nome.", "error")
            return render_template("admin_catalogo_base_form.html",
                                   nome_conceito=nome_conceito,
                                   descricao=descricao,
                                   status=status)

        try:
            conn.execute(
                "INSERT INTO atividade_base (nome_conceito, descricao, status) VALUES (?, ?, ?)",
                (nome_conceito, descricao or None, status),
            )
            conn.commit()
            base_id = conn.execute(
                "SELECT id FROM atividade_base WHERE nome_conceito = ?",
                (nome_conceito,),
            ).fetchone()["id"]
            flash("Atividade-base criada com sucesso.", "success")
            return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))
        except Exception as exc:
            flash(f"Erro ao criar atividade-base: {exc}", "error")
            return render_template("admin_catalogo_base_form.html",
                                   nome_conceito=nome_conceito,
                                   descricao=descricao,
                                   status=status)

    return render_template("admin_catalogo_base_form.html",
                           nome_conceito="",
                           descricao="",
                           status="ativo")


@app.route("/admin/normas-atividade/nova", methods=["GET", "POST"])
@admin_required
def admin_norma_nova():
    """
    Formulário para criar uma nova norma_atividade.
    POST valida e insere; em sucesso redireciona para a listagem de normas.
    """
    if request.method == "POST":
        codigo = (request.form.get("codigo") or "").strip()
        eixo = (request.form.get("eixo") or "").strip()
        revisao = (request.form.get("revisao") or "").strip()
        nome = (request.form.get("nome") or "").strip()
        descricao = (request.form.get("descricao") or "").strip()
        status = (request.form.get("status") or "").strip()

        def _render_form(msg):
            if msg:
                flash(msg, "error")
            return render_template("admin_norma_form.html",
                                   codigo=codigo, eixo=eixo,
                                   revisao=revisao, nome=nome,
                                   descricao=descricao, status=status)

        if not codigo:
            return _render_form("Código da norma é obrigatório.")
        if eixo not in ("AAC", "AEU"):
            return _render_form("Eixo deve ser 'AAC' ou 'AEU'.")
        if not revisao:
            return _render_form("Revisão é obrigatória.")
        if status not in ("ativa", "inativa"):
            return _render_form("Status deve ser 'ativa' ou 'inativa'.")

        conn = get_db_connection()

        existing = conn.execute(
            "SELECT id FROM norma_atividade WHERE LOWER(codigo) = LOWER(?)",
            (codigo,),
        ).fetchone()
        if existing:
            return _render_form("Já existe uma norma com este código.")

        try:
            conn.execute(
                """
                INSERT INTO norma_atividade (codigo, eixo, revisao, nome, descricao, status)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (codigo, eixo, revisao, nome or None, descricao or None, status),
            )
            conn.commit()
            flash("Norma de atividade criada com sucesso.", "success")
            return redirect(url_for("admin_normas_atividade"))
        except Exception as exc:
            return _render_form(f"Erro ao criar norma: {exc}")

    return render_template("admin_norma_form.html",
                           codigo="", eixo="AAC", revisao="",
                           nome="", descricao="", status="ativa")


@app.route("/admin/catalogo-versoes/<int:base_id>/nova-versao", methods=["GET", "POST"])
@admin_required
def admin_catalogo_nova_versao(base_id: int):
    """
    Formulário para criar uma nova atividade_versao em rascunho
    vinculada a uma atividade_base e uma norma_atividade.
    POST valida e insere; em sucesso redireciona para o detalhe da base.
    """
    conn = get_db_connection()
    base = get_atividade_base(conn, base_id)
    if not base:
        flash("Atividade-base não encontrada.", "error")
        return redirect(url_for("admin_catalogo_versoes"))

    normas = get_norma_list(conn)
    versoes_anteriores = (
        get_versoes_da_base_por_eixo(conn, base_id, "AAC")
        + get_versoes_da_base_por_eixo(conn, base_id, "AEU")
    )

    form_action = url_for("admin_catalogo_nova_versao", base_id=base_id)
    form_title = "Nova versão"
    submit_label = "Criar versão em rascunho"

    if request.method == "POST":
        norma_id_raw = (request.form.get("norma_id") or "").strip()
        grupo = (request.form.get("grupo") or "").strip()
        ch_por_evento_raw = (request.form.get("ch_por_evento") or "").strip()
        limite_semestre_raw = (request.form.get("limite_semestre") or "").strip()
        limite_total_raw = (request.form.get("limite_total") or "").strip()
        observacao_aluno = (request.form.get("observacao_aluno") or "").strip()
        observacao_admin = (request.form.get("observacao_admin") or "").strip()
        vigencia_inicio = (request.form.get("vigencia_inicio") or "").strip()
        vigencia_fim = (request.form.get("vigencia_fim") or "").strip()
        versao_anterior_id_raw = (request.form.get("versao_anterior_id") or "").strip()

        def _render_form(msg):
            if msg:
                flash(msg, "error")
            return render_template(
                "admin_catalogo_versao_form.html",
                base=base,
                normas=normas,
                versoes_anteriores=versoes_anteriores,
                norma_id=norma_id_raw,
                grupo=grupo,
                ch_por_evento=ch_por_evento_raw,
                limite_semestre=limite_semestre_raw,
                limite_total=limite_total_raw,
                observacao_aluno=observacao_aluno,
                observacao_admin=observacao_admin,
                vigencia_inicio=vigencia_inicio,
                vigencia_fim=vigencia_fim,
                versao_anterior_id=versao_anterior_id_raw,
                form_action=form_action,
                form_title=form_title,
                submit_label=submit_label,
            )

        if not norma_id_raw:
            return _render_form("Norma é obrigatória.")
        try:
            norma_id = int(norma_id_raw)
        except (TypeError, ValueError):
            return _render_form("Norma inválida.")

        norma = get_norma_by_id(conn, norma_id)
        if not norma:
            return _render_form("Norma não encontrada.")
        if norma["status"] != "ativa":
            return _render_form("Norma deve estar ativa para criar uma versão.")

        eixo = norma["eixo"]
        codigo_normativo = norma["codigo"]

        # validação numérica
        def _parse_float(raw, nome):
            if not raw:
                return None
            try:
                v = float(raw)
                if v < 0:
                    return nome
                return v
            except (TypeError, ValueError):
                return nome

        ch_por_evento = _parse_float(ch_por_evento_raw, "ch_por_evento")
        limite_semestre = _parse_float(limite_semestre_raw, "limite_semestre")
        limite_total = _parse_float(limite_total_raw, "limite_total")
        for maybe_err in (ch_por_evento, limite_semestre, limite_total):
            if isinstance(maybe_err, str):
                return _render_form(f"{maybe_err} deve ser um número válido e maior ou igual a zero.")

        versao_anterior_id = None
        if versao_anterior_id_raw:
            try:
                versao_anterior_id = int(versao_anterior_id_raw)
            except (TypeError, ValueError):
                return _render_form("Versão anterior inválida.")
            prev = conn.execute(
                "SELECT atividade_base_id, eixo FROM atividade_versao WHERE id = ?",
                (versao_anterior_id,),
            ).fetchone()
            if not prev:
                return _render_form("Versão anterior não encontrada.")
            if prev["atividade_base_id"] != base_id:
                return _render_form("Versão anterior deve pertencer à mesma atividade-base.")
            if prev["eixo"] != eixo:
                return _render_form("Versão anterior deve ter o mesmo eixo da norma selecionada.")

        try:
            next_num = get_next_numero_versao(conn, base_id)
            conn.execute(
                """
                INSERT INTO atividade_versao (
                    atividade_base_id, norma_id, codigo_normativo, eixo, grupo,
                    ch_por_evento, limite_semestre, limite_total,
                    observacao_aluno, observacao_admin,
                    vigencia_inicio, vigencia_fim, numero_versao, status, versao_anterior_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'rascunho', ?)
                """,
                (
                    base_id, norma_id, codigo_normativo, eixo, grupo or None,
                    ch_por_evento, limite_semestre, limite_total,
                    observacao_aluno or None, observacao_admin or None,
                    vigencia_inicio or None, vigencia_fim or None, next_num, versao_anterior_id,
                ),
            )
            conn.commit()
            flash("Versão criada com sucesso em rascunho.", "success")
            return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))
        except Exception as exc:
            return _render_form(f"Erro ao criar versão: {exc}")

    return render_template(
        "admin_catalogo_versao_form.html",
        base=base,
        normas=normas,
        versoes_anteriores=versoes_anteriores,
        norma_id="",
        grupo="",
        ch_por_evento="",
        limite_semestre="",
        limite_total="",
        observacao_aluno="",
        observacao_admin="",
        vigencia_inicio="",
        vigencia_fim="",
        versao_anterior_id="",
        form_action=form_action,
        form_title=form_title,
        submit_label=submit_label,
    )


@app.route(
    "/admin/catalogo-versoes/<int:base_id>/versoes/<int:versao_id>/editar",
    methods=["GET", "POST"],
)
@admin_required
def admin_catalogo_editar_versao(base_id: int, versao_id: int):
    """
    Formulário para editar uma atividade_versao existente.
    Permitido apenas enquanto status = 'rascunho' e sem nenhum uso registrado
    (matriz_atividade_versao_item, requisicoes, atividade_transicao).
    POST valida e atualiza; em sucesso redireciona para o detalhe da base.
    """
    conn = get_db_connection()
    base = get_atividade_base(conn, base_id)
    if not base:
        flash("Atividade-base não encontrada.", "error")
        return redirect(url_for("admin_catalogo_versoes"))

    versao = get_atividade_versao_by_id(conn, versao_id)
    if not versao or versao["atividade_base_id"] != base_id:
        flash("Versão não encontrada para esta atividade-base.", "error")
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))

    if versao["status"] != "rascunho":
        flash("Apenas versões em rascunho podem ser editadas.", "error")
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))

    uso = get_atividade_versao_usage_counts(conn, versao_id)
    if uso["total"] > 0:
        flash("Esta versão já está em uso e não pode mais ser editada.", "error")
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))

    normas = get_norma_list(conn)
    versoes_anteriores = [
        v
        for v in (
            get_versoes_da_base_por_eixo(conn, base_id, "AAC")
            + get_versoes_da_base_por_eixo(conn, base_id, "AEU")
        )
        if v["id"] != versao_id
    ]

    form_action = url_for("admin_catalogo_editar_versao", base_id=base_id, versao_id=versao_id)
    form_title = f"Editar versão — {versao['codigo_normativo']}"
    submit_label = "Salvar alterações"

    def _display_number(value):
        if value is None:
            return ""
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)

    if request.method == "POST":
        norma_id_raw = (request.form.get("norma_id") or "").strip()
        grupo = (request.form.get("grupo") or "").strip()
        ch_por_evento_raw = (request.form.get("ch_por_evento") or "").strip()
        limite_semestre_raw = (request.form.get("limite_semestre") or "").strip()
        limite_total_raw = (request.form.get("limite_total") or "").strip()
        observacao_aluno = (request.form.get("observacao_aluno") or "").strip()
        observacao_admin = (request.form.get("observacao_admin") or "").strip()
        vigencia_inicio = (request.form.get("vigencia_inicio") or "").strip()
        vigencia_fim = (request.form.get("vigencia_fim") or "").strip()
        versao_anterior_id_raw = (request.form.get("versao_anterior_id") or "").strip()

        def _render_form(msg):
            if msg:
                flash(msg, "error")
            return render_template(
                "admin_catalogo_versao_form.html",
                base=base,
                normas=normas,
                versoes_anteriores=versoes_anteriores,
                norma_id=norma_id_raw,
                grupo=grupo,
                ch_por_evento=ch_por_evento_raw,
                limite_semestre=limite_semestre_raw,
                limite_total=limite_total_raw,
                observacao_aluno=observacao_aluno,
                observacao_admin=observacao_admin,
                vigencia_inicio=vigencia_inicio,
                vigencia_fim=vigencia_fim,
                versao_anterior_id=versao_anterior_id_raw,
                form_action=form_action,
                form_title=form_title,
                submit_label=submit_label,
            )

        if not norma_id_raw:
            return _render_form("Norma é obrigatória.")
        try:
            norma_id = int(norma_id_raw)
        except (TypeError, ValueError):
            return _render_form("Norma inválida.")

        norma = get_norma_by_id(conn, norma_id)
        if not norma:
            return _render_form("Norma não encontrada.")
        if norma["status"] != "ativa":
            return _render_form("Norma deve estar ativa para editar a versão.")

        eixo = norma["eixo"]
        codigo_normativo = norma["codigo"]

        # validação numérica
        def _parse_float(raw, nome):
            if not raw:
                return None
            try:
                v = float(raw)
                if v < 0:
                    return nome
                return v
            except (TypeError, ValueError):
                return nome

        ch_por_evento = _parse_float(ch_por_evento_raw, "ch_por_evento")
        limite_semestre = _parse_float(limite_semestre_raw, "limite_semestre")
        limite_total = _parse_float(limite_total_raw, "limite_total")
        for maybe_err in (ch_por_evento, limite_semestre, limite_total):
            if isinstance(maybe_err, str):
                return _render_form(f"{maybe_err} deve ser um número válido e maior ou igual a zero.")

        versao_anterior_id = None
        if versao_anterior_id_raw:
            try:
                versao_anterior_id = int(versao_anterior_id_raw)
            except (TypeError, ValueError):
                return _render_form("Versão anterior inválida.")
            if versao_anterior_id == versao_id:
                return _render_form("Versão anterior não pode ser a própria versão.")
            prev = conn.execute(
                "SELECT atividade_base_id, eixo FROM atividade_versao WHERE id = ?",
                (versao_anterior_id,),
            ).fetchone()
            if not prev:
                return _render_form("Versão anterior não encontrada.")
            if prev["atividade_base_id"] != base_id:
                return _render_form("Versão anterior deve pertencer à mesma atividade-base.")
            if prev["eixo"] != eixo:
                return _render_form("Versão anterior deve ter o mesmo eixo da norma selecionada.")

        try:
            conn.execute(
                """
                UPDATE atividade_versao
                   SET norma_id = ?,
                       codigo_normativo = ?,
                       eixo = ?,
                       grupo = ?,
                       ch_por_evento = ?,
                       limite_semestre = ?,
                       limite_total = ?,
                       observacao_aluno = ?,
                       observacao_admin = ?,
                       vigencia_inicio = ?,
                       vigencia_fim = ?,
                       versao_anterior_id = ?
                 WHERE id = ?
                """,
                (
                    norma_id, codigo_normativo, eixo, grupo or None,
                    ch_por_evento, limite_semestre, limite_total,
                    observacao_aluno or None, observacao_admin or None,
                    vigencia_inicio or None, vigencia_fim or None, versao_anterior_id,
                    versao_id,
                ),
            )
            conn.commit()
            flash("Versão atualizada com sucesso.", "success")
            return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))
        except Exception as exc:
            return _render_form(f"Erro ao atualizar versão: {exc}")

    return render_template(
        "admin_catalogo_versao_form.html",
        base=base,
        normas=normas,
        versoes_anteriores=versoes_anteriores,
        norma_id=str(versao["norma_id"]),
        grupo=versao["grupo"] or "",
        ch_por_evento=_display_number(versao["ch_por_evento"]),
        limite_semestre=_display_number(versao["limite_semestre"]),
        limite_total=_display_number(versao["limite_total"]),
        observacao_aluno=versao["observacao_aluno"] or "",
        observacao_admin=versao["observacao_admin"] or "",
        vigencia_inicio=versao["vigencia_inicio"] or "",
        vigencia_fim=versao["vigencia_fim"] or "",
        versao_anterior_id=(
            "" if versao["versao_anterior_id"] is None else str(versao["versao_anterior_id"])
        ),
        form_action=form_action,
        form_title=form_title,
        submit_label=submit_label,
    )


@app.route(
    "/admin/catalogo-versoes/<int:base_id>/versoes/<int:versao_id>/ativar",
    methods=["POST"],
)
@admin_required
def admin_catalogo_ativar_versao(base_id: int, versao_id: int):
    """
    Ativação mínima de uma atividade_versao em rascunho.

    Permite mudar status = 'rascunho' -> 'ativa' por ação administrativa
    explícita. Validações server-side:
      - atividade_base existe
      - atividade_versao existe e pertence ao base_id da URL
      - status atual == 'rascunho'
      - norma_atividade vinculada existe e está ativa

    Operação: UPDATE atividade_versao SET status = 'ativa'
    WHERE id = ? AND status = 'rascunho'. Se rowcount != 1, rollback.

    Não cria entrada em matriz_atividade_versao_item, não altera
    requisicoes, atividade_transicao, snapshot, cálculo ou aluno.
    Não usa fallback silencioso nem primeira ativa.
    """
    conn = get_db_connection()
    base = get_atividade_base(conn, base_id)
    if not base:
        flash("Atividade-base não encontrada.", "error")
        return redirect(url_for("admin_catalogo_versoes"))

    versao = get_atividade_versao_by_id(conn, versao_id)
    if not versao or versao["atividade_base_id"] != base_id:
        flash("Versão não encontrada para esta atividade-base.", "error")
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))

    if versao["status"] != "rascunho":
        flash("Apenas versões em rascunho podem ser ativadas.", "error")
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))

    norma = get_norma_by_id(conn, versao["norma_id"])
    if not norma:
        flash("Não é possível ativar: a norma vinculada não existe.", "error")
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))
    if norma["status"] != "ativa":
        flash(
            "Não é possível ativar: a norma vinculada não está ativa.",
            "error",
        )
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))

    try:
        cur = conn.execute(
            "UPDATE atividade_versao "
            "SET status = 'ativa' "
            "WHERE id = ? AND status = 'rascunho'",
            (versao_id,),
        )
        if cur.rowcount != 1:
            conn.rollback()
            flash(
                "Ativação não aplicada: a versão não está mais em rascunho.",
                "error",
            )
            return redirect(
                url_for("admin_catalogo_versao_detalhe", base_id=base_id)
            )
        conn.commit()
        flash("Versão ativada com sucesso.", "success")
    except Exception as exc:
        conn.rollback()
        flash(f"Erro ao ativar versão: {exc}", "error")

    return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))


@app.route(
    "/admin/catalogo-versoes/<int:base_id>/versoes/<int:versao_id>/substituir",
    methods=["POST"],
)
@admin_required
def admin_catalogo_substituir_versao(base_id: int, versao_id: int):
    """
    Substitui explicitamente uma atividade_versao ativa por outra ativa
    da mesma atividade-base e do mesmo eixo.
    """
    conn = get_db_connection()
    ensure_atividade_versioning_schema(conn)

    base = get_atividade_base(conn, base_id)
    if not base:
        flash("Atividade-base nÃ£o encontrada.", "error")
        return redirect(url_for("admin_catalogo_versoes"))

    origem = get_atividade_versao_by_id(conn, versao_id)
    if not origem or origem["atividade_base_id"] != base_id:
        flash("VersÃ£o de origem nÃ£o encontrada para esta atividade-base.", "error")
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))

    if origem["status"] != "ativa":
        flash("Apenas versÃµes ativas podem ser substituÃ­das.", "error")
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))

    origem_usage = get_atividade_versao_usage_counts(conn, versao_id)
    if origem_usage["matriz_atividade_versao_item"] > 0:
        flash(
            "NÃ£o Ã© possÃ­vel substituir: esta versÃ£o estÃ¡ vinculada a matriz.",
            "error",
        )
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))
    if origem_usage["atividade_transicao_origem"] > 0:
        flash(
            "NÃ£o Ã© possÃ­vel substituir: a versÃ£o de origem jÃ¡ possui transiÃ§Ã£o registrada.",
            "error",
        )
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))

    to_versao_id_raw = (request.form.get("to_versao_id") or "").strip()
    if not to_versao_id_raw:
        flash("Selecione a versÃ£o de destino para substituir.", "error")
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))
    try:
        to_versao_id = int(to_versao_id_raw)
    except (TypeError, ValueError):
        flash("VersÃ£o de destino invÃ¡lida.", "error")
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))

    if to_versao_id == versao_id:
        flash("A versÃ£o de destino deve ser diferente da origem.", "error")
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))

    destino = get_atividade_versao_by_id(conn, to_versao_id)
    if not destino:
        flash("VersÃ£o de destino nÃ£o encontrada.", "error")
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))
    if destino["status"] != "ativa":
        flash("A versÃ£o de destino deve estar ativa.", "error")
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))
    if destino["atividade_base_id"] != base_id:
        flash("A versÃ£o de destino deve pertencer Ã  mesma atividade-base.", "error")
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))
    if destino["eixo"] != origem["eixo"]:
        flash("A versÃ£o de destino deve ter o mesmo eixo da origem.", "error")
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))

    destino_usage = get_atividade_versao_usage_counts(conn, to_versao_id)
    if destino_usage["atividade_transicao_origem"] > 0:
        flash(
            "NÃ£o Ã© possÃ­vel substituir: a versÃ£o de destino jÃ¡ possui transiÃ§Ã£o registrada como origem.",
            "error",
        )
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))

    try:
        cur = conn.execute(
            "UPDATE atividade_versao SET status = 'substituida' "
            "WHERE id = ? AND status = 'ativa'",
            (versao_id,),
        )
        if cur.rowcount != 1:
            conn.rollback()
            flash(
                "SubstituiÃ§Ã£o nÃ£o aplicada: a versÃ£o de origem nÃ£o estÃ¡ mais ativa.",
                "error",
            )
            return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))

        conn.execute(
            """
            INSERT INTO atividade_transicao (
                from_atividade_versao_id,
                to_atividade_versao_id,
                tipo_transicao
            ) VALUES (?, ?, 'mesmo_eixo')
            """,
            (versao_id, to_versao_id),
        )
        conn.commit()
        flash("VersÃ£o substituÃ­da com sucesso.", "success")
    except Exception as exc:
        conn.rollback()
        flash(f"Erro ao substituir versÃ£o: {exc}", "error")

    return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))


@app.route(
    "/admin/catalogo-versoes/<int:base_id>/versoes/<int:versao_id>/inativar",
    methods=["POST"],
)
@admin_required
def admin_catalogo_inativar_versao(base_id: int, versao_id: int):
    """
    Inativação administrativa de uma atividade_versao ativa.

    Permite a transição status = 'ativa' → 'inativa'.
    A versão deixa de ser considerada ativa pelo resolvedor sem qualquer
    alteração no resolvedor, writer, requisicoes, snapshot, cálculo ou aluno.

    Bloqueio B1 — Rejeita se houver vínculo em matriz_atividade_versao_item.
    O admin deve remover o vínculo na tela de versões da matriz primeiro.

    Não remove vínculos, não cria atividade_transicao, não altera resolvedor,
    não faz fallback, não escolhe substituta, sem efeito colateral silencioso.
    """
    conn = get_db_connection()
    ensure_atividade_versioning_schema(conn)

    base = get_atividade_base(conn, base_id)
    if not base:
        flash("Atividade-base não encontrada.", "error")
        return redirect(url_for("admin_catalogo_versoes"))

    versao = get_atividade_versao_by_id(conn, versao_id)
    if not versao or versao["atividade_base_id"] != base_id:
        flash("Versão não encontrada para esta atividade-base.", "error")
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))

    if versao["status"] != "ativa":
        flash("Apenas versões ativas podem ser inativadas.", "error")
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))

    usage = get_atividade_versao_usage_counts(conn, versao_id)
    if usage["matriz_atividade_versao_item"] > 0:
        flash(
            f"Não é possível inativar: esta versão está vinculada a "
            f"{usage['matriz_atividade_versao_item']} matriz(es). "
            "Remova o vínculo na tela de versões da matriz antes de inativar.",
            "error",
        )
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))

    try:
        cur = conn.execute(
            "UPDATE atividade_versao SET status = 'inativa'"
            " WHERE id = ? AND status = 'ativa'",
            (versao_id,),
        )
        if cur.rowcount != 1:
            conn.rollback()
            flash("Inativação não aplicada: a versão não está mais ativa.", "error")
            return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))
        conn.commit()
        flash("Versão inativada com sucesso.", "success")
    except Exception as exc:
        conn.rollback()
        flash(f"Erro ao inativar versão: {exc}", "error")

    return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))


@app.route(
    "/admin/catalogo-versoes/<int:base_id>/versoes/<int:versao_id>/descontinuar",
    methods=["POST"],
)
@admin_required
def admin_catalogo_descontinuar_versao(base_id: int, versao_id: int):
    """
    Descontinuação administrativa de uma atividade_versao ativa.

    Permite a transição status = 'ativa' → 'descontinuada'.
    A versão deixa de ser considerada ativa pelo resolvedor sem qualquer
    alteração no resolvedor, writer, requisicoes, snapshot, cálculo ou aluno.

    Bloqueio B1 — Rejeita se houver vínculo em matriz_atividade_versao_item.
    O admin deve remover o vínculo na tela de versões da matriz primeiro.

    Não remove vínculos, não cria atividade_transicao, não altera resolvedor,
    não faz fallback, não escolhe substituta, sem efeito colateral silencioso.
    """
    conn = get_db_connection()
    ensure_atividade_versioning_schema(conn)

    base = get_atividade_base(conn, base_id)
    if not base:
        flash("Atividade-base não encontrada.", "error")
        return redirect(url_for("admin_catalogo_versoes"))

    versao = get_atividade_versao_by_id(conn, versao_id)
    if not versao or versao["atividade_base_id"] != base_id:
        flash("Versão não encontrada para esta atividade-base.", "error")
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))

    if versao["status"] != "ativa":
        flash("Apenas versões ativas podem ser descontinuadas.", "error")
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))

    usage = get_atividade_versao_usage_counts(conn, versao_id)
    if usage["matriz_atividade_versao_item"] > 0:
        flash(
            f"Não é possível descontinuar: esta versão está vinculada a "
            f"{usage['matriz_atividade_versao_item']} matriz(es). "
            "Remova o vínculo na tela de versões da matriz antes de descontinuar.",
            "error",
        )
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))

    try:
        cur = conn.execute(
            "UPDATE atividade_versao SET status = 'descontinuada'"
            " WHERE id = ? AND status = 'ativa'",
            (versao_id,),
        )
        if cur.rowcount != 1:
            conn.rollback()
            flash(
                "Descontinuação não aplicada: a versão não está mais ativa.", "error"
            )
            return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))
        conn.commit()
        flash("Versão descontinuada com sucesso.", "success")
    except Exception as exc:
        conn.rollback()
        flash(f"Erro ao descontinuar versão: {exc}", "error")

    return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))


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


def _access_defaults_map(conn) -> dict[str, str]:
    from app.auth import DEFAULT_ACCESS_PASSWORDS, canonicalize_access_level

    ensure_usuario_access_schema(conn)
    defaults = dict(DEFAULT_ACCESS_PASSWORDS)
    rows = conn.execute("SELECT nivel_acesso, senha_padrao FROM configuracoes_acesso").fetchall()
    for row in rows:
        nivel = canonicalize_access_level(row["nivel_acesso"])
        defaults[nivel] = row["senha_padrao"]
    return defaults


def _default_password_for_user_type(conn, user_type: str) -> str:
    from app.auth import default_access_level_for_user_type

    nivel_acesso = default_access_level_for_user_type(user_type)
    return _access_defaults_map(conn).get(nivel_acesso, "admin123")


def create_usuario_with_default_password(conn, nome: str, email: str, user_type: str):
    senha_padrao = _default_password_for_user_type(conn, user_type)
    return create_usuario_with_default_access(conn, nome, email, hash_password(senha_padrao), user_type)


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
