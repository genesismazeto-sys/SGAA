import logging
import os
import sqlite3
from flask import current_app, g

from app.backup_settings import (
    bind_backup_settings_runtime_app,
    ensure_backup_settings_schema,
)
from app.academics import (
    DEFAULT_CURSO_TOTAL_HORAS_AAC,
    DEFAULT_CURSO_TOTAL_HORAS_AEU,
    gerar_codigo_turma,
)
from app.db_maintenance import (
    apply_early_schema_migrations,
    apply_schema_migrations,
    ensure_atividade_versioning_schema,
    ensure_matriz_atividade_links_table,
    ensure_matrizes_atividades_table,
    ensure_reportes_table,
    ensure_requisicao_arquivos_table,
    ensure_requisicao_alert_receipts_table,
    ensure_usuario_access_schema,
    ensure_usuario_profile_schema,
)
from app.security.passwords import hash_password
from app.text import ptbr_sqlite_collation
from app.prod1_schema import validate_prod1_schema
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATABASE = os.getenv("APP_DATABASE", os.path.join(PROJECT_ROOT, "database.db"))
logger = logging.getLogger(__name__)

DEFAULT_RESPONSE_GOAL_DAYS = 10
DEFAULT_RETURN_RESPONSE_DAYS = 7
DEFAULT_HORAS_ACADEMICA = 160
DEFAULT_HORAS_EXTENSAO = 160


def get_db_connection():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        try:
            g.db.create_collation("PTBR_NOACCENT", ptbr_sqlite_collation)
        except Exception:
            pass
        try:
            g.db.execute("PRAGMA foreign_keys = ON")
            g.db.execute("PRAGMA synchronous = NORMAL")
        except Exception:
            pass
    return g.db


def close_db_connection(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def _app_settings_defaults() -> dict[str, str]:
    return {
        "response_goal_days": str(DEFAULT_RESPONSE_GOAL_DAYS),
        "response_metrics_reset_at": "",
        "return_response_days": str(DEFAULT_RETURN_RESPONSE_DAYS),
        "auto_indefer_devolvida": "0",
        "horas_padrao_academica": str(DEFAULT_HORAS_ACADEMICA),
        "horas_padrao_extensao": str(DEFAULT_HORAS_EXTENSAO),
    }


def ensure_app_settings_schema(conn) -> None:
    validate_prod1_schema(conn)
    for chave, valor in _app_settings_defaults().items():
        conn.execute(
            "INSERT OR IGNORE INTO configuracoes_app (chave, valor) VALUES (?, ?)",
            (chave, valor),
        )


def ensure_cloud_backup_schema(conn) -> None:
    validate_prod1_schema(conn)


def ensure_turmas_matriz_schema(conn) -> None:
    validate_prod1_schema(conn)


def init_db():
    """Bootstrap or validate the empty-only first-production database."""
    runtime_app = current_app._get_current_object()
    bind_backup_settings_runtime_app(runtime_app)
    conn = get_db_connection()

    apply_early_schema_migrations(conn, logger=logger)
    conn.execute("PRAGMA journal_mode = WAL")

    # The prod-1 bootstrap owns physical schema; these calls only seed defaults.
    ensure_usuario_access_schema(conn)
    ensure_app_settings_schema(conn)
    ensure_backup_settings_schema(conn)

    existe_curso = conn.execute("SELECT 1 FROM cursos LIMIT 1").fetchone()
    if not existe_curso:
        conn.execute(
            """
            INSERT INTO cursos (
                nome, codigo, duracao_periodos,
                total_horas_aac, total_horas_aeu, status
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "Geral", "GERAL", 8,
                DEFAULT_CURSO_TOTAL_HORAS_AAC,
                DEFAULT_CURSO_TOTAL_HORAS_AEU,
                "ativo",
            ),
        )

    admin_email = (
        current_app.config.get("BOOTSTRAP_ADMIN_EMAIL") or "admin@ej.edu.br"
    ).strip().lower()
    bootstrap_admin = bool(current_app.config.get("BOOTSTRAP_DEFAULT_ADMIN"))
    bootstrap_password = (
        current_app.config.get("BOOTSTRAP_ADMIN_PASSWORD") or ""
    ).strip()
    admin_exists = conn.execute(
        "SELECT 1 FROM usuarios WHERE LOWER(email) = ?", (admin_email,)
    ).fetchone()
    if not admin_exists and bootstrap_admin and bootstrap_password:
        conn.execute(
            """
            INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "Administrador", admin_email, hash_password(bootstrap_password),
                "admin", "admin_total",
            ),
        )
    elif not admin_exists and not bootstrap_admin:
        logger.warning(
            "Nenhum usuário admin existente e bootstrap automático desabilitado. "
            "Crie um admin manualmente antes do primeiro login produtivo."
        )
    conn.commit()
