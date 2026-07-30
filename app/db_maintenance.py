import datetime
import json
import os
import secrets
import shutil
import sqlite3
import tempfile
import threading
import time
from typing import Callable
from urllib import error as urllib_error
from urllib import request as urllib_request

from app.academics import (
    DEFAULT_CURSO_TOTAL_HORAS_AAC,
    DEFAULT_CURSO_TOTAL_HORAS_AEU,
)
from app.auth import DEFAULT_ACCESS_PASSWORDS, default_access_level_for_user_type


SCHEMA_VERSION = 3

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
    "documentos_json",
)
_ATIVIDADES_REQUIRED_LEGACY_COLUMNS = {"id", "grupo", "nome", "limite_horas"}
_ATIVIDADES_TARGET_TABLE_INFO = (
    ("id", "INTEGER", 0, None, 1),
    ("grupo", "TEXT", 1, None, 0),
    ("nome", "TEXT", 1, None, 0),
    ("descricao", "TEXT", 0, None, 0),
    ("limite_horas", "INTEGER", 0, None, 0),
    ("tipo_atividade", "TEXT", 1, "'Acadêmica Complementar'", 0),
    ("tem_limitacao", "BOOLEAN", 0, "0", 0),
    ("tipo_limitacao", "TEXT", 0, None, 0),
    ("limite_horas_total", "INTEGER", 0, None, 0),
    ("limite_horas_semestral", "INTEGER", 0, None, 0),
    ("documentos_json", "TEXT", 0, None, 0),
)
_THROUGH_VERSION_ERROR = "through_version must be non-negative"


class SchemaMigrationStateError(RuntimeError):
    """Internal schema-migration state contradiction, never a UI message."""


def ensure_backup_settings_structural_schema(conn) -> None:
    """Ensure only the physical backup-settings table."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS configuracoes_backup (
            chave TEXT PRIMARY KEY,
            valor TEXT NOT NULL,
            atualizado_em TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )


def ensure_usuario_access_structural_schema(conn) -> None:
    """Ensure only the structural access-schema objects."""
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


def seed_usuario_access_default_data(conn) -> None:
    """Insert the five historical access defaults without overwriting custom values."""
    for nivel_acesso, senha_padrao in DEFAULT_ACCESS_PASSWORDS.items():
        # NOTA: senhas "padrão" históricas são gravadas SOMENTE na primeira inicialização.
        # Em ambientes onde não houver linha pré-existente, mantemos os valores acima
        # para preservar o fluxo administrativo. NUNCA reutilize esses valores em
        # produção; reescreva-os via interface após o primeiro login.
        conn.execute(
            "INSERT OR IGNORE INTO configuracoes_acesso (nivel_acesso, senha_padrao) VALUES (?, ?)",
            (nivel_acesso, senha_padrao),
        )


def normalize_usuario_access_startup_data(conn) -> None:
    """Normalize only the accepted startup-wide historical access states."""
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
    # NOTA: permanece ausente o UPDATE incondicional que promovia
    # o e-mail "admin@ej.edu.br" a admin_total a cada execução.


def ensure_usuario_access_schema(conn) -> None:
    """Ensure access schema and startup data without finalizing caller work.

    Releasing this helper-owned savepoint persists its work on a clean
    connection. Under an existing transaction, the caller retains commit and
    rollback ownership.
    """
    conn.execute("SAVEPOINT ensure_usuario_access_schema")
    try:
        ensure_usuario_access_structural_schema(conn)
        seed_usuario_access_default_data(conn)
        normalize_usuario_access_startup_data(conn)
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT ensure_usuario_access_schema")
        conn.execute("RELEASE SAVEPOINT ensure_usuario_access_schema")
        raise
    else:
        conn.execute("RELEASE SAVEPOINT ensure_usuario_access_schema")


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


_AUTO_SYNC_LOCK = threading.Lock()
_AUTO_SYNC_STATE = {
    "last_signature": None,
    "last_synced_at": 0.0,
}


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _migration_v1_baseline(conn: sqlite3.Connection) -> None:
    """Marca o schema atual como baseline versionado.

    As tabelas e ajustes continuam sendo garantidos pelo bootstrap atual.
    A partir daqui, upgrades futuros podem ser adicionados de forma explícita.
    """


def _schema_object_exists(conn, object_type: str, name: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = ? AND name = ?",
            (object_type, name),
        ).fetchone()
        is not None
    )


def _atividades_table_info(conn):
    return tuple(
        (row[1], str(row[2]).upper(), int(row[3]), row[4], int(row[5]))
        for row in conn.execute("PRAGMA table_info(atividades)").fetchall()
    )


def _atividades_has_unique_nome(conn) -> bool:
    for row in conn.execute("PRAGMA index_list(atividades)").fetchall():
        if not int(row[2]):
            continue
        index_name = str(row[1]).replace('"', '""')
        columns = tuple(
            index_row[2]
            for index_row in conn.execute(f'PRAGMA index_info("{index_name}")').fetchall()
        )
        if columns == ("nome",):
            return True
    return False


def _atividades_schema_is_current(conn) -> bool:
    if not _schema_object_exists(conn, "table", "atividades"):
        return False
    if _atividades_table_info(conn) != _ATIVIDADES_TARGET_TABLE_INFO:
        return False
    if not _atividades_has_unique_nome(conn):
        return False
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'atividades'"
    ).fetchone()
    normalized = "".join(str(row[0] or "").lower().split()) if row else ""
    return all(
        fragment in normalized
        for fragment in (
            "check(tipo_atividadein('acadêmicacomplementar','extensãouniversitária'))",
            "check(tipo_limitacaoin('total','semestral'))",
        )
    )


def _validate_recorded_atividades_v2(conn) -> None:
    if _schema_object_exists(conn, "table", "atividades__new"):
        raise SchemaMigrationStateError(
            "recorded v2 contradicts physical schema: orphan atividades__new table"
        )
    if not _atividades_schema_is_current(conn):
        raise SchemaMigrationStateError(
            "recorded v2 contradicts physical schema: atividades is not canonical"
        )


def _create_atividades_v2_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE atividades__new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            grupo TEXT NOT NULL,
            nome TEXT NOT NULL UNIQUE,
            descricao TEXT,
            limite_horas INTEGER,
            tipo_atividade TEXT NOT NULL DEFAULT 'Acadêmica Complementar'
                CHECK(tipo_atividade IN ('Acadêmica Complementar', 'Extensão Universitária')),
            tem_limitacao BOOLEAN DEFAULT 0,
            tipo_limitacao TEXT CHECK(tipo_limitacao IN ('total', 'semestral')),
            limite_horas_total INTEGER,
            limite_horas_semestral INTEGER,
            documentos_json TEXT
        )
        """
    )


def _migration_v2_normalize_atividades_schema(conn) -> None:
    if not _schema_object_exists(conn, "table", "atividades"):
        raise SchemaMigrationStateError("atividades must exist before migration v2")
    if _schema_object_exists(conn, "table", "atividades__new"):
        raise SchemaMigrationStateError("unexpected preexisting atividades__new table")
    if _atividades_schema_is_current(conn):
        return

    source_columns = tuple(row[1] for row in conn.execute("PRAGMA table_info(atividades)"))
    source_set = set(source_columns)
    unexpected = source_set - set(ATIVIDADES_SCHEMA_COLUMNS)
    missing_required = _ATIVIDADES_REQUIRED_LEGACY_COLUMNS - source_set
    if unexpected or missing_required:
        raise SchemaMigrationStateError(
            "unsupported atividades schema for v2: "
            f"unexpected={sorted(unexpected)!r}, missing={sorted(missing_required)!r}"
        )

    sequence_row = None
    if _schema_object_exists(conn, "table", "sqlite_sequence"):
        sequence_row = conn.execute(
            "SELECT seq FROM sqlite_sequence WHERE name = 'atividades'"
        ).fetchone()
    previous_sequence = int(sequence_row[0]) if sequence_row is not None else None

    def source_or_null(name: str) -> str:
        return f'"{name}"' if name in source_set else "NULL"

    tipo_atividade = (
        "COALESCE(NULLIF(TRIM(tipo_atividade), ''), 'Acadêmica Complementar')"
        if "tipo_atividade" in source_set
        else "'Acadêmica Complementar'"
    )
    tem_limitacao = (
        "COALESCE(tem_limitacao, 0)" if "tem_limitacao" in source_set else "0"
    )
    copy_expressions = (
        '"id"',
        '"grupo"',
        '"nome"',
        source_or_null("descricao"),
        '"limite_horas"',
        tipo_atividade,
        tem_limitacao,
        source_or_null("tipo_limitacao"),
        source_or_null("limite_horas_total"),
        source_or_null("limite_horas_semestral"),
        source_or_null("documentos_json"),
    )

    _create_atividades_v2_table(conn)
    conn.execute(
        f"""
        INSERT INTO atividades__new ({', '.join(ATIVIDADES_SCHEMA_COLUMNS)})
        SELECT {', '.join(copy_expressions)}
          FROM atividades
         ORDER BY id
        """
    )
    conn.execute("DROP TABLE atividades")
    conn.execute("ALTER TABLE atividades__new RENAME TO atividades")

    max_id = int(conn.execute("SELECT COALESCE(MAX(id), 0) FROM atividades").fetchone()[0])
    desired_sequence = max(max_id, previous_sequence or 0)
    conn.execute(
        "DELETE FROM sqlite_sequence WHERE name IN ('atividades', 'atividades__new')"
    )
    if desired_sequence:
        conn.execute(
            "INSERT INTO sqlite_sequence(name, seq) VALUES ('atividades', ?)",
            (desired_sequence,),
        )

    if not _atividades_schema_is_current(conn):
        raise SchemaMigrationStateError(
            "atividades v2 rebuild did not produce the canonical schema"
        )
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise SchemaMigrationStateError(
            f"foreign key violations after atividades v2: {violations!r}"
        )


_ACTIVITY_VERSIONING_CORE_TABLES = (
    "atividade_base",
    "norma_atividade",
    "atividade_versao",
)
_ACTIVITY_VERSIONING_LEAF_TABLES = (
    "atividade_transicao",
    "matriz_norma",
    "matriz_atividade_versao_item",
    "atividade_legacy_map",
)
_ACTIVITY_VERSIONING_CORE_TRIGGERS = (
    "trg_atividade_versao_eixo_norma_insert",
    "trg_atividade_versao_prev_same_eixo_insert",
    "trg_atividade_versao_prev_same_eixo_update",
    "trg_atividade_versao_eixo_norma_update",
    "trg_atividade_versao_num_pos_insert",
    "trg_atividade_versao_num_pos_update",
)
_ACTIVITY_VERSIONING_LEAF_TRIGGERS = (
    "trg_atividade_transicao_aac_para_aeu_insert",
    "trg_atividade_transicao_aac_para_aeu_update",
)
_ACTIVITY_VERSIONING_CORE_INDEXES = {
    "idx_norma_atividade_codigo": (
        "norma_atividade",
        ("codigo",),
        False,
    ),
    "idx_norma_atividade_eixo": ("norma_atividade", ("eixo",), False),
    "idx_atividade_versao_base": (
        "atividade_versao",
        ("atividade_base_id",),
        False,
    ),
    "idx_atividade_versao_norma": (
        "atividade_versao",
        ("norma_id",),
        False,
    ),
    "idx_atividade_versao_base_num": (
        "atividade_versao",
        ("atividade_base_id", "numero_versao"),
        True,
    ),
    "idx_atividade_versao_eixo": ("atividade_versao", ("eixo",), False),
    "idx_atividade_versao_status": (
        "atividade_versao",
        ("status",),
        False,
    ),
}
_ACTIVITY_VERSIONING_LEAF_INDEXES = (
    "idx_atividade_transicao_from",
    "idx_atividade_transicao_to",
    "idx_atividade_transicao_tipo",
    "idx_matriz_norma_matriz",
    "idx_matriz_norma_norma",
    "idx_matriz_atividade_versao_item_matriz",
    "idx_matriz_atividade_versao_item_versao",
    "idx_atividade_legacy_map_base",
)
_ACTIVITY_VERSIONING_PARENT_COLUMNS = {
    "atividade_base": (
        "id",
        "nome_conceito",
        "descricao",
        "status",
        "created_at",
    ),
    "norma_atividade": (
        "id",
        "codigo",
        "eixo",
        "revisao",
        "nome",
        "descricao",
        "status",
        "created_at",
    ),
}
_ACTIVITY_VERSIONING_VERSAO_COLUMNS = (
    "id",
    "atividade_base_id",
    "norma_id",
    "codigo_normativo",
    "eixo",
    "grupo",
    "ch_por_evento",
    "limite_semestre",
    "limite_total",
    "observacao_aluno",
    "observacao_admin",
    "documentos_json",
    "vigencia_inicio",
    "vigencia_fim",
    "numero_versao",
    "status",
    "versao_anterior_id",
    "created_at",
)
_ACTIVITY_VERSIONING_VERSAO_LEGACY_COLUMNS = (
    "id",
    "atividade_base_id",
    "norma_id",
    "codigo_normativo",
    "eixo",
    "grupo",
    "ch_por_evento",
    "limite_semestre",
    "limite_total",
    "observacao_aluno",
    "observacao_admin",
    "documentos_json",
    "vigencia_inicio",
    "vigencia_fim",
    "status",
    "versao_anterior_id",
    "created_at",
)


def _schema_object_sql(conn, object_type: str, name: str) -> str:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = ? AND name = ?",
        (object_type, name),
    ).fetchone()
    return str(row[0] or "") if row else ""


def _table_column_names(conn, table_name: str) -> tuple[str, ...]:
    escaped = table_name.replace('"', '""')
    return tuple(
        str(row[1])
        for row in conn.execute(f'PRAGMA table_info("{escaped}")').fetchall()
    )


def _activity_versioning_recorded_versions(conn) -> tuple[int, ...]:
    if not _schema_object_exists(conn, "table", "schema_migrations"):
        return ()
    return tuple(
        int(row[0])
        for row in conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
    )


def _activity_versioning_source_variant(conn) -> str:
    if _schema_object_exists(conn, "table", "atividade_versao_new"):
        raise SchemaMigrationStateError(
            "preexisting atividade_versao_new table blocks migration v3"
        )

    present_core = {
        table
        for table in _ACTIVITY_VERSIONING_CORE_TABLES
        if _schema_object_exists(conn, "table", table)
    }
    present_leaf = {
        table
        for table in _ACTIVITY_VERSIONING_LEAF_TABLES
        if _schema_object_exists(conn, "table", table)
    }
    present_parents = present_core.intersection(_ACTIVITY_VERSIONING_PARENT_COLUMNS)
    for table in present_parents:
        expected_columns = _ACTIVITY_VERSIONING_PARENT_COLUMNS[table]
        actual_columns = _table_column_names(conn, table)
        if actual_columns != expected_columns:
            raise SchemaMigrationStateError(
                "unsupported activity-versioning core: "
                f"{table} columns={actual_columns!r}"
            )
        normalized_parent = "".join(
            _schema_object_sql(conn, "table", table).lower().split()
        )
        required_fragments = {
            "atividade_base": (
                "nome_conceitotextnotnullunique",
                "check(statusin('ativo','inativo'))",
            ),
            "norma_atividade": (
                "codigotextnotnullunique",
                "check(eixoin('aac','aeu'))",
                "check(statusin('ativa','inativa'))",
            ),
        }[table]
        if not all(fragment in normalized_parent for fragment in required_fragments):
            raise SchemaMigrationStateError(
                f"unsupported activity-versioning parent constraints: {table}"
            )

    if "atividade_versao" not in present_core:
        unsupported_leaf = present_leaf - {"atividade_legacy_map"}
        if unsupported_leaf or (present_leaf and "atividade_base" not in present_core):
            raise SchemaMigrationStateError(
                "partial activity-versioning core cannot be completed safely: "
                f"leaf={sorted(present_leaf)!r}"
            )
        if "atividade_legacy_map" in present_leaf:
            expected_map_columns = (
                "id",
                "atividade_id_legacy",
                "atividade_base_id",
                "status",
                "observacao_admin",
                "created_at",
            )
            if _table_column_names(conn, "atividade_legacy_map") != expected_map_columns:
                raise SchemaMigrationStateError(
                    "unsupported partial atividade_legacy_map schema"
                )
        return "absent"

    if present_core != set(_ACTIVITY_VERSIONING_CORE_TABLES):
        raise SchemaMigrationStateError(
            "partial activity-versioning core: "
            f"present={sorted(present_core)!r}"
        )

    columns = _table_column_names(conn, "atividade_versao")
    if columns not in (
        _ACTIVITY_VERSIONING_VERSAO_COLUMNS,
        _ACTIVITY_VERSIONING_VERSAO_LEGACY_COLUMNS,
    ):
        raise SchemaMigrationStateError(
            "unsupported activity-versioning core: "
            f"atividade_versao columns={columns!r}"
        )

    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise SchemaMigrationStateError(
            "activity-versioning core has foreign key violations: "
            f"{violations!r}"
        )

    if columns == _ACTIVITY_VERSIONING_VERSAO_LEGACY_COLUMNS:
        return "missing_numero"

    invalid = conn.execute(
        "SELECT id FROM atividade_versao "
        "WHERE numero_versao IS NULL OR numero_versao < 1 "
        "ORDER BY id LIMIT 1"
    ).fetchone()
    if invalid is not None:
        raise SchemaMigrationStateError(
            f"invalid numero_versao in atividade_versao id={int(invalid[0])}"
        )
    duplicate = conn.execute(
        "SELECT atividade_base_id, numero_versao "
        "FROM atividade_versao GROUP BY atividade_base_id, numero_versao "
        "HAVING COUNT(*) > 1 LIMIT 1"
    ).fetchone()
    if duplicate is not None:
        raise SchemaMigrationStateError(
            "duplicate atividade_versao numbering for "
            f"base={int(duplicate[0])}, numero={int(duplicate[1])}"
        )

    normalized = "".join(
        _schema_object_sql(conn, "table", "atividade_versao")
        .lower()
        .replace('"', "")
        .split()
    )
    index_row = next(
        (
            row
            for row in conn.execute(
                "PRAGMA index_list(atividade_versao)"
            ).fetchall()
            if str(row[1]) == "idx_atividade_versao_base_num"
        ),
        None,
    )
    named_index_is_canonical = False
    if index_row is not None:
        index_columns = tuple(
            row[2]
            for row in conn.execute(
                "PRAGMA index_info(idx_atividade_versao_base_num)"
            ).fetchall()
        )
        named_index_is_canonical = (
            int(index_row[2]) == 1
            and int(index_row[4]) == 0
            and index_columns == ("atividade_base_id", "numero_versao")
        )
    canonical_fragments = (
        "numero_versaointegernotnulldefault1check(numero_versao>=1)",
        "foreignkey(versao_anterior_id)referencesatividade_versao(id)ondeleterestrict",
        "statusin('rascunho','ativa','inativa','descontinuada','substituida')",
    )
    if all(fragment in normalized for fragment in canonical_fragments):
        return "canonical" if named_index_is_canonical else "canonical_needs_objects"
    return "legacy_numero"


def _create_activity_versioning_core_tables(conn) -> None:
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


def ensure_activity_versioning_core_tables(conn) -> None:
    _create_activity_versioning_core_tables(conn)


def ensure_activity_versioning_core_triggers(conn) -> None:
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


def ensure_requisicoes_versioning_compatibility_schema(conn) -> None:
    if not _schema_object_exists(conn, "table", "requisicoes"):
        raise SchemaMigrationStateError(
            "requisicoes must exist before activity-versioning schema"
        )
    columns = set(_table_column_names(conn, "requisicoes"))
    additions = (
        ("atividade_versao_id", "INTEGER"),
        ("regra_snapshot_json", "TEXT"),
        ("codigo_normativo_snapshot", "TEXT"),
    )
    for name, sql_type in additions:
        if name not in columns:
            conn.execute(
                f"ALTER TABLE requisicoes ADD COLUMN {name} {sql_type}"
            )


def ensure_activity_versioning_core_indexes(conn) -> None:
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_norma_atividade_codigo "
        "ON norma_atividade(codigo)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_norma_atividade_eixo "
        "ON norma_atividade(eixo)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_atividade_versao_base "
        "ON atividade_versao(atividade_base_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_atividade_versao_norma "
        "ON atividade_versao(norma_id)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_atividade_versao_base_num "
        "ON atividade_versao(atividade_base_id, numero_versao)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_atividade_versao_eixo "
        "ON atividade_versao(eixo)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_atividade_versao_status "
        "ON atividade_versao(status)"
    )


def ensure_requisicoes_versioning_compatibility_index(conn) -> None:
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_requisicoes_atividade_versao_id "
        "ON requisicoes(atividade_versao_id)"
    )


def _drop_activity_versioning_rebuild_sensitive_objects(conn) -> None:
    for trigger_name in _ACTIVITY_VERSIONING_LEAF_TRIGGERS:
        conn.execute(f'DROP TRIGGER IF EXISTS "{trigger_name}"')
    conn.execute("DROP INDEX IF EXISTS idx_atividade_versao_base_num")


def _rebuild_activity_versioning_core_v3(conn, variant: str) -> None:
    sequence_row = None
    if _schema_object_exists(conn, "table", "sqlite_sequence"):
        sequence_row = conn.execute(
            "SELECT seq FROM sqlite_sequence WHERE name = 'atividade_versao'"
        ).fetchone()
    previous_sequence = int(sequence_row[0]) if sequence_row else 0

    _drop_activity_versioning_rebuild_sensitive_objects(conn)
    conn.execute(
        """
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
        )
        """
    )
    number_expression = (
        "ROW_NUMBER() OVER (PARTITION BY atividade_base_id ORDER BY id)"
        if variant == "missing_numero"
        else "numero_versao"
    )
    conn.execute(
        f"""
        INSERT INTO atividade_versao_new (
            id, atividade_base_id, norma_id, codigo_normativo, eixo, grupo,
            ch_por_evento, limite_semestre, limite_total, observacao_aluno,
            observacao_admin, documentos_json, vigencia_inicio, vigencia_fim,
            numero_versao, status, versao_anterior_id, created_at
        )
        SELECT
            id, atividade_base_id, norma_id, codigo_normativo, eixo, grupo,
            ch_por_evento, limite_semestre, limite_total, observacao_aluno,
            observacao_admin, documentos_json, vigencia_inicio, vigencia_fim,
            {number_expression}, status, versao_anterior_id, created_at
        FROM atividade_versao
        ORDER BY id
        """
    )
    conn.execute("DROP TABLE atividade_versao")
    conn.execute(
        "ALTER TABLE atividade_versao_new RENAME TO atividade_versao"
    )
    max_id = int(
        conn.execute(
            "SELECT COALESCE(MAX(id), 0) FROM atividade_versao"
        ).fetchone()[0]
    )
    desired_sequence = max(previous_sequence, max_id)
    conn.execute(
        "DELETE FROM sqlite_sequence "
        "WHERE name IN ('atividade_versao', 'atividade_versao_new')"
    )
    if desired_sequence:
        conn.execute(
            "INSERT INTO sqlite_sequence(name, seq) "
            "VALUES('atividade_versao', ?)",
            (desired_sequence,),
        )


def _validate_activity_versioning_v3(conn) -> None:
    variant = _activity_versioning_source_variant(conn)
    if variant != "canonical":
        raise SchemaMigrationStateError(
            "activity-versioning v3 core is not canonical: "
            f"state={variant}"
        )
    missing_triggers = tuple(
        name
        for name in _ACTIVITY_VERSIONING_CORE_TRIGGERS
        if not _schema_object_exists(conn, "trigger", name)
    )
    if missing_triggers:
        raise SchemaMigrationStateError(
            f"activity-versioning v3 missing core triggers: {missing_triggers!r}"
        )
    for name, (table, columns, unique) in _ACTIVITY_VERSIONING_CORE_INDEXES.items():
        row = next(
            (
                row
                for row in conn.execute(f"PRAGMA index_list({table})").fetchall()
                if str(row[1]) == name
            ),
            None,
        )
        if row is None:
            raise SchemaMigrationStateError(
                f"activity-versioning v3 missing core index: {name}"
            )
        actual_columns = tuple(
            index_row[2]
            for index_row in conn.execute(f'PRAGMA index_info("{name}")').fetchall()
        )
        if (
            bool(row[2]) is not unique
            or int(row[4]) != 0
            or actual_columns != columns
        ):
            raise SchemaMigrationStateError(
                f"activity-versioning v3 noncanonical core index: {name}"
            )
    missing_leaf = tuple(
        name
        for name in (
            *_ACTIVITY_VERSIONING_LEAF_TABLES,
            *_ACTIVITY_VERSIONING_LEAF_TRIGGERS,
            *_ACTIVITY_VERSIONING_LEAF_INDEXES,
        )
        if not any(
            _schema_object_exists(conn, object_type, name)
            for object_type in ("table", "trigger", "index")
        )
    )
    if missing_leaf:
        raise SchemaMigrationStateError(
            f"activity-versioning v3 missing B8 leaf objects: {missing_leaf!r}"
        )
    requisicoes_columns = set(_table_column_names(conn, "requisicoes"))
    required_columns = {
        "atividade_versao_id",
        "regra_snapshot_json",
        "codigo_normativo_snapshot",
    }
    if not required_columns <= requisicoes_columns:
        raise SchemaMigrationStateError(
            "activity-versioning v3 missing requisicoes compatibility columns"
        )
    if not _schema_object_exists(
        conn, "index", "idx_requisicoes_atividade_versao_id"
    ):
        raise SchemaMigrationStateError(
            "activity-versioning v3 missing requisicoes compatibility index"
        )
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise SchemaMigrationStateError(
            f"foreign key violations after activity-versioning v3: {violations!r}"
        )


def _validate_recorded_activity_versioning_v3(conn) -> None:
    try:
        _validate_activity_versioning_v3(conn)
    except SchemaMigrationStateError as exc:
        raise SchemaMigrationStateError(
            f"recorded v3 contradicts physical schema: {exc}"
        ) from exc


def _migration_v3_normalize_activity_versioning_core(conn) -> None:
    variant = _activity_versioning_source_variant(conn)
    if variant == "absent":
        raise SchemaMigrationStateError(
            "activity-versioning core must exist before migration v3"
        )
    if variant != "canonical":
        _rebuild_activity_versioning_core_v3(conn, variant)
    ensure_atividade_versioning_leaf_tables(conn)
    ensure_activity_versioning_core_triggers(conn)
    ensure_atividade_versioning_leaf_triggers(conn)
    ensure_requisicoes_versioning_compatibility_schema(conn)
    ensure_activity_versioning_core_indexes(conn)
    ensure_atividade_versioning_leaf_indexes(conn)
    ensure_requisicoes_versioning_compatibility_index(conn)
    _validate_activity_versioning_v3(conn)


SCHEMA_MIGRATIONS: tuple[tuple[int, str, Callable[[sqlite3.Connection], None]], ...] = (
    (1, "baseline_schema_management", _migration_v1_baseline),
    (2, "normalize_atividades_schema", _migration_v2_normalize_atividades_schema),
    (3, "normalize_activity_versioning_core", _migration_v3_normalize_activity_versioning_core),
)


def ensure_schema_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (datetime('now')),
            details_json TEXT
        )
        """
    )


def apply_schema_migrations(
    conn: sqlite3.Connection, logger=None, through_version: int | None = None
) -> dict[str, object]:
    ensure_schema_migrations_table(conn)
    applied_rows = tuple(
        (int(row[0]), str(row[1]))
        for row in conn.execute(
            "SELECT version, name FROM schema_migrations ORDER BY version"
        ).fetchall()
    )
    registry_names = {version: name for version, name, _ in SCHEMA_MIGRATIONS}
    applied_versions = {version for version, _ in applied_rows}
    unknown = applied_versions - set(registry_names)
    if unknown:
        raise SchemaMigrationStateError(
            f"unknown recorded schema migrations: {sorted(unknown)!r}"
        )
    for version, name in applied_rows:
        if name != registry_names[version]:
            raise SchemaMigrationStateError(
                f"schema migration v{version} name mismatch: {name!r}"
            )
    if applied_versions and applied_versions != set(
        range(1, max(applied_versions) + 1)
    ):
        raise SchemaMigrationStateError(
            f"schema migration history contains gaps: {sorted(applied_versions)!r}"
        )

    target_version = SCHEMA_VERSION
    if through_version is not None:
        requested = int(through_version)
        if requested < 0:
            raise ValueError(_THROUGH_VERSION_ERROR)
        target_version = min(requested, SCHEMA_VERSION)

    applied_now: list[int] = []
    for version, name, migration in SCHEMA_MIGRATIONS:
        if version > target_version:
            continue
        if version in applied_versions:
            if version == 2:
                _validate_recorded_atividades_v2(conn)
            if version == 3:
                _validate_recorded_activity_versioning_v3(conn)
            continue
        migration(conn)
        if version == 2:
            _validate_recorded_atividades_v2(conn)
        if version == 3:
            _validate_activity_versioning_v3(conn)
        conn.execute(
            "INSERT INTO schema_migrations (version, name, details_json) VALUES (?, ?, ?)",
            (
                version,
                name,
                json.dumps({"recorded_at": _utc_now_iso()}, ensure_ascii=False),
            ),
        )
        applied_now.append(version)
        if logger is not None:
            logger.info("Schema migration v%s aplicada: %s", version, name)

    current_row = conn.execute(
        "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
    ).fetchone()
    current_version = int(current_row[0]) if current_row is not None else 0
    conn.execute(f"PRAGMA user_version = {current_version}")
    return {
        "schema_version": current_version,
        "target_schema_version": SCHEMA_VERSION,
        "applied_now": applied_now,
    }


def apply_early_schema_migrations(conn: sqlite3.Connection, logger=None) -> dict[str, object]:
    """Apply existing-database migrations in one isolated pre-bootstrap transaction."""
    if conn.in_transaction:
        raise SchemaMigrationStateError(
            "early schema migration requires no active transaction"
        )

    recorded = _activity_versioning_recorded_versions(conn)
    recorded_user_version = get_schema_version(conn)
    if recorded_user_version > SCHEMA_VERSION:
        raise SchemaMigrationStateError(
            f"unsupported user_version {recorded_user_version} exceeds schema registry"
        )
    core_variant = _activity_versioning_source_variant(conn)
    has_atividades = _schema_object_exists(conn, "table", "atividades")
    if 3 in recorded or recorded_user_version >= 3:
        if 3 not in recorded:
            raise SchemaMigrationStateError(
                "user_version v3 contradicts schema migration registry"
            )
        _validate_recorded_activity_versioning_v3(conn)

    if not has_atividades:
        if 2 in recorded or recorded_user_version >= 2:
            raise SchemaMigrationStateError(
                "recorded v2 contradicts physical schema: atividades table is absent"
            )
        if core_variant != "absent":
            raise SchemaMigrationStateError(
                "partial activity-versioning core: atividades table is absent"
            )
        return {
            "schema_version": max(recorded, default=0),
            "target_schema_version": SCHEMA_VERSION,
            "applied_now": [],
        }

    has_recorded_v2 = 2 in recorded
    if (
        recorded_user_version >= 2
        and not has_recorded_v2
        and not _atividades_schema_is_current(conn)
    ):
        raise SchemaMigrationStateError(
            "user_version v2 contradicts physical schema: atividades is not canonical"
        )

    through_version = 2 if core_variant == "absent" else SCHEMA_VERSION
    if core_variant != "absent":
        required_prerequisites = (
            "requisicoes",
            "matrizes_atividades",
        )
        missing = tuple(
            name
            for name in required_prerequisites
            if not _schema_object_exists(conn, "table", name)
        )
        if missing:
            raise SchemaMigrationStateError(
                "partial activity-versioning core: missing prerequisites "
                f"{missing!r}"
            )

    original_foreign_keys = int(conn.execute("PRAGMA foreign_keys").fetchone()[0])
    conn.execute("PRAGMA foreign_keys = OFF")
    if int(conn.execute("PRAGMA foreign_keys").fetchone()[0]) != 0:
        raise SchemaMigrationStateError(
            "could not disable foreign key enforcement before migration"
        )

    transaction_started = False
    try:
        conn.execute("BEGIN IMMEDIATE")
        transaction_started = True
        result = apply_schema_migrations(
            conn, logger=logger, through_version=through_version
        )
        conn.commit()
        transaction_started = False
        return result
    except Exception:
        if transaction_started and conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.execute(f"PRAGMA foreign_keys = {original_foreign_keys}")
        restored = int(conn.execute("PRAGMA foreign_keys").fetchone()[0])
        if restored != original_foreign_keys:
            raise SchemaMigrationStateError(
                "could not restore original foreign key enforcement state"
            )


def get_schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0]) if row else 0


def get_schema_status(conn: sqlite3.Connection) -> dict[str, object]:
    ensure_schema_migrations_table(conn)
    latest = conn.execute(
        "SELECT version, name, applied_at FROM schema_migrations ORDER BY version DESC LIMIT 1"
    ).fetchone()
    return {
        "schema_version": get_schema_version(conn),
        "target_schema_version": SCHEMA_VERSION,
        "latest_migration": {
            "version": int(latest[0]),
            "name": latest[1],
            "applied_at": latest[2],
        }
        if latest
        else None,
    }


def _ensure_directory(path: str | None) -> str | None:
    if not path:
        return None
    os.makedirs(path, exist_ok=True)
    return path


def _database_change_signature(database_path: str) -> str:
    parts: list[str] = []
    for suffix in ("", "-wal", "-shm"):
        candidate = database_path + suffix
        if not os.path.exists(candidate):
            continue
        stat = os.stat(candidate)
        parts.append(f"{suffix}:{stat.st_mtime_ns}:{stat.st_size}")
    return "|".join(parts)


def _snapshot_database(source_db_path: str, destination_db_path: str) -> None:
    os.makedirs(os.path.dirname(destination_db_path), exist_ok=True)
    source_conn = sqlite3.connect(source_db_path)
    target_conn = sqlite3.connect(destination_db_path)
    try:
        source_conn.backup(target_conn)
        target_conn.commit()
    finally:
        target_conn.close()
        source_conn.close()


def create_database_snapshot(
    source_db_path: str,
    target_root: str,
    *,
    schema_status: dict[str, object] | None = None,
    reason: str = "manual",
    origin: str = "local",
    logger=None,
    extra_metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    target_root = _ensure_directory(target_root) or target_root
    snapshots_dir = _ensure_directory(os.path.join(target_root, "snapshots"))
    latest_dir = _ensure_directory(os.path.join(target_root, "latest"))
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    basename = f"database-{timestamp}-{secrets.token_hex(3)}"
    snapshot_db_path = os.path.join(snapshots_dir, f"{basename}.db")
    snapshot_manifest_path = os.path.join(snapshots_dir, f"{basename}.json")

    _snapshot_database(source_db_path, snapshot_db_path)

    manifest = {
        "snapshot_id": basename,
        "created_at": _utc_now_iso(),
        "reason": reason,
        "origin": origin,
        "database_path": snapshot_db_path,
        "database_name": os.path.basename(source_db_path),
        "schema_status": schema_status or {},
        "source_database_path": source_db_path,
    }
    if extra_metadata:
        manifest["extra_metadata"] = extra_metadata

    with open(snapshot_manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)

    latest_db_path = os.path.join(latest_dir, "database_latest.db")
    latest_manifest_path = os.path.join(latest_dir, "database_latest.json")
    shutil.copy2(snapshot_db_path, latest_db_path)
    with open(latest_manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)

    if logger is not None:
        logger.info("Snapshot de banco criado em %s", snapshot_db_path)

    return {
        **manifest,
        "manifest_path": snapshot_manifest_path,
        "latest_database_path": latest_db_path,
        "latest_manifest_path": latest_manifest_path,
    }


def upload_snapshot_to_external_server(
    snapshot_db_path: str,
    manifest_path: str,
    *,
    server_url: str,
    token: str | None = None,
    timeout_seconds: int = 30,
    logger=None,
) -> dict[str, object]:
    boundary = f"----backup-{secrets.token_hex(12)}"
    body = bytearray()

    def _append_bytes(value: bytes) -> None:
        body.extend(value)

    def _append_field(name: str, value: str) -> None:
        _append_bytes(f"--{boundary}\r\n".encode("utf-8"))
        _append_bytes(
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode("utf-8")
        )

    def _append_file(field_name: str, file_path: str, content_type: str) -> None:
        filename = os.path.basename(file_path)
        _append_bytes(f"--{boundary}\r\n".encode("utf-8"))
        _append_bytes(
            (
                f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode("utf-8")
        )
        with open(file_path, "rb") as handle:
            body.extend(handle.read())
        _append_bytes(b"\r\n")

    _append_field("source", "sistema-atividades-complementares")
    _append_file("database", snapshot_db_path, "application/vnd.sqlite3")
    _append_file("manifest", manifest_path, "application/json")
    _append_bytes(f"--{boundary}--\r\n".encode("utf-8"))

    request_obj = urllib_request.Request(server_url, data=bytes(body), method="POST")
    request_obj.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    request_obj.add_header("Accept", "application/json, text/plain, */*")
    if token:
        request_obj.add_header("Authorization", f"Bearer {token}")

    try:
        with urllib_request.urlopen(request_obj, timeout=timeout_seconds) as response:
            payload = response.read().decode("utf-8", errors="replace")
            result = {"status_code": response.getcode(), "body": payload}
            if logger is not None:
                logger.info("Snapshot enviado ao servidor externo %s com status %s", server_url, response.getcode())
            return result
    except urllib_error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        if logger is not None:
            logger.warning("Falha HTTP ao enviar snapshot para servidor externo %s: %s", server_url, exc)
        raise RuntimeError(f"Servidor externo respondeu {exc.code}: {detail or exc.reason}") from exc
    except urllib_error.URLError as exc:
        if logger is not None:
            logger.warning("Falha de conexão ao enviar snapshot para servidor externo %s: %s", server_url, exc)
        raise RuntimeError(f"Não foi possível conectar ao servidor externo: {exc.reason}") from exc


def delete_database_snapshot(manifest_path: str, logger=None) -> None:
    with open(manifest_path, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)

    db_path = manifest.get("database_path") or ""
    snapshot_id = manifest.get("snapshot_id") or os.path.splitext(os.path.basename(manifest_path))[0]
    root_dir = os.path.dirname(os.path.dirname(manifest_path))
    latest_manifest_path = os.path.join(root_dir, "latest", "database_latest.json")
    latest_db_path = os.path.join(root_dir, "latest", "database_latest.db")

    if os.path.exists(latest_manifest_path):
        try:
            with open(latest_manifest_path, "r", encoding="utf-8") as handle:
                latest_manifest = json.load(handle)
        except (OSError, json.JSONDecodeError):
            latest_manifest = None
        latest_snapshot_id = None if not latest_manifest else latest_manifest.get("snapshot_id") or os.path.splitext(os.path.basename(latest_manifest_path))[0]
        if latest_snapshot_id == snapshot_id:
            for candidate in (latest_manifest_path, latest_db_path):
                try:
                    os.remove(candidate)
                except OSError:
                    pass

    for candidate in (manifest_path, db_path):
        if not candidate:
            continue
        try:
            os.remove(candidate)
        except OSError:
            pass

    if logger is not None:
        logger.info("Snapshot removido: %s", manifest_path)


def list_database_backups(locations: dict[str, str | None]) -> list[dict[str, object]]:
    backups: list[dict[str, object]] = []
    for location_label, root in locations.items():
        if not root:
            continue
        snapshots_dir = os.path.join(root, "snapshots")
        if not os.path.isdir(snapshots_dir):
            continue
        for entry in os.listdir(snapshots_dir):
            if not entry.endswith(".json"):
                continue
            manifest_path = os.path.join(snapshots_dir, entry)
            try:
                with open(manifest_path, "r", encoding="utf-8") as handle:
                    manifest = json.load(handle)
            except (OSError, json.JSONDecodeError):
                continue
            db_path = manifest.get("database_path")
            backups.append(
                {
                    "location": location_label,
                    "manifest_path": manifest_path,
                    "database_path": db_path,
                    "created_at": manifest.get("created_at"),
                    "reason": manifest.get("reason"),
                    "origin": manifest.get("origin"),
                    "schema_status": manifest.get("schema_status") or {},
                    "size_bytes": os.path.getsize(db_path) if db_path and os.path.exists(db_path) else None,
                }
            )
    backups.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return backups


def maybe_sync_database_to_cloud(
    source_db_path: str,
    cloud_root: str | None,
    *,
    schema_status: dict[str, object] | None = None,
    min_interval_seconds: int = 300,
    force: bool = False,
    logger=None,
) -> dict[str, object]:
    if not cloud_root:
        return {"ok": False, "skipped": True, "reason": "cloud_backup_disabled"}

    signature = _database_change_signature(source_db_path)
    now = time.time()
    with _AUTO_SYNC_LOCK:
        last_signature = _AUTO_SYNC_STATE.get("last_signature")
        last_synced_at = float(_AUTO_SYNC_STATE.get("last_synced_at") or 0.0)
        if not force and last_signature == signature:
            return {"ok": True, "skipped": True, "reason": "unchanged"}
        if not force and last_synced_at and (now - last_synced_at) < max(0, min_interval_seconds):
            return {"ok": True, "skipped": True, "reason": "cooldown"}

        snapshot = create_database_snapshot(
            source_db_path,
            cloud_root,
            schema_status=schema_status,
            reason="auto-sync" if not force else "forced-sync",
            origin="cloud",
            logger=logger,
        )
        _AUTO_SYNC_STATE["last_signature"] = signature
        _AUTO_SYNC_STATE["last_synced_at"] = now
        return {"ok": True, "skipped": False, "snapshot": snapshot}


def apply_retention_policy(
    snapshots: list[dict],
    policy: list[dict],
) -> list[str]:
    """Return manifest_paths that should be deleted to enforce the GFS retention policy.

    Each policy window: {period_hours, interval_hours, slots}.
    Snapshots with reason == "manual-backup" are never included in the delete list.
    """
    now = datetime.datetime.now(datetime.timezone.utc)

    parsed: list[dict] = []
    for snap in snapshots:
        raw = (snap.get("created_at") or "").replace("Z", "+00:00")
        try:
            dt = datetime.datetime.fromisoformat(raw)
        except ValueError:
            continue
        parsed.append({**snap, "_dt": dt})

    parsed.sort(key=lambda x: x["_dt"], reverse=True)

    kept: set[str] = set()
    for window in policy:
        try:
            period_h = float(window["period_hours"])
            interval_h = float(window["interval_hours"])
            slots = int(window["slots"])
        except (KeyError, TypeError, ValueError):
            continue
        if interval_h <= 0 or slots <= 0:
            continue

        cutoff = now - datetime.timedelta(hours=period_h)
        buckets: dict[int, dict] = {}
        for snap in parsed:
            if snap.get("reason") == "manual-backup":
                continue  # manual backups don't consume window slots
            if snap["_dt"] < cutoff:
                continue
            age_h = (now - snap["_dt"]).total_seconds() / 3600.0
            bucket_idx = int(age_h / interval_h)
            if bucket_idx not in buckets:
                buckets[bucket_idx] = snap

        for i, (_, snap) in enumerate(sorted(buckets.items())):
            if i >= slots:
                break
            mp = snap.get("manifest_path") or ""
            if mp:
                kept.add(mp)

    to_delete: list[str] = []
    for snap in parsed:
        mp = snap.get("manifest_path") or ""
        if not mp:
            continue
        if snap.get("reason") == "manual-backup":
            continue
        if mp not in kept:
            to_delete.append(mp)
    return to_delete


def restore_database_snapshot(source_snapshot_path: str, target_db_path: str, logger=None) -> None:
    temp_dir = os.path.dirname(target_db_path) or os.getcwd()
    temp_handle = tempfile.NamedTemporaryFile(prefix="restore-", suffix=".db", dir=temp_dir, delete=False)
    temp_handle.close()
    temp_target_path = temp_handle.name
    source_conn = sqlite3.connect(source_snapshot_path)
    target_conn = sqlite3.connect(temp_target_path)
    try:
        source_conn.backup(target_conn)
        target_conn.commit()
    finally:
        target_conn.close()
        source_conn.close()

    for suffix in ("-wal", "-shm"):
        try:
            os.remove(target_db_path + suffix)
        except OSError:
            pass
    os.replace(temp_target_path, target_db_path)
    if logger is not None:
        logger.info("Banco restaurado a partir de %s", source_snapshot_path)


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


def ensure_atividade_versioning_leaf_tables(conn) -> None:
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


def ensure_atividade_versioning_leaf_triggers(conn) -> None:
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


def ensure_atividade_versioning_leaf_indexes(conn) -> None:
    conn.execute("CREATE INDEX IF NOT EXISTS idx_atividade_transicao_from ON atividade_transicao(from_atividade_versao_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_atividade_transicao_to ON atividade_transicao(to_atividade_versao_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_atividade_transicao_tipo ON atividade_transicao(tipo_transicao)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_matriz_norma_matriz ON matriz_norma(matriz_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_matriz_norma_norma ON matriz_norma(norma_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_matriz_atividade_versao_item_matriz ON matriz_atividade_versao_item(matriz_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_matriz_atividade_versao_item_versao ON matriz_atividade_versao_item(atividade_versao_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_atividade_legacy_map_base ON atividade_legacy_map(atividade_base_id)")


def ensure_atividade_versioning_schema(conn) -> None:
    """Ensure canonical activity-versioning objects under caller transaction ownership."""
    recorded = _activity_versioning_recorded_versions(conn)
    if 3 in recorded:
        _validate_recorded_activity_versioning_v3(conn)
    variant = _activity_versioning_source_variant(conn)
    if variant not in ("absent", "canonical"):
        raise SchemaMigrationStateError(
            "activity-versioning core requires isolated migration v3 before ensure: "
            f"state={variant}"
        )

    ensure_matriz_atividade_links_table(conn)
    ensure_activity_versioning_core_tables(conn)
    ensure_atividade_versioning_leaf_tables(conn)
    ensure_activity_versioning_core_triggers(conn)
    ensure_atividade_versioning_leaf_triggers(conn)
    ensure_requisicoes_versioning_compatibility_schema(conn)
    ensure_activity_versioning_core_indexes(conn)
    ensure_atividade_versioning_leaf_indexes(conn)
    ensure_requisicoes_versioning_compatibility_index(conn)

    if 3 in recorded:
        _validate_recorded_activity_versioning_v3(conn)