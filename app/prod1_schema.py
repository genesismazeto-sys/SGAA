from __future__ import annotations

import json
import hashlib
import re
import sqlite3

SCHEMA_EPOCH = "prod-1"
SCHEMA_VERSION = 2
BASELINE_MARKER = "first_production_baseline"
LATEST_MIGRATION_MARKER = "remove_norma_domain"
REQUEST_STATUSES = (
    "Pendente", "Deferida", "Deferida Parcialmente",
    "Indeferida", "Devolvida", "Encerrada",
)

EXPECTED_TABLES = frozenset({
    "admin_alertas", "admin_arquivos", "alunos", "atividade_base",
    "atividade_transicao", "atividade_versao", "backup_logs", "cloud_accounts",
    "cloud_drive_settings", "configuracoes_acesso", "configuracoes_app",
    "configuracoes_backup", "configuracoes_presets", "cursos", "grupos_def",
    "matriz_atividade_versao_item", "matrizes_atividades",
    "mensagens_editaveis", "reportes",
    "requisicao_alerta_receipts", "requisicao_arquivos", "requisicoes",
    "schema_migrations", "turmas", "usuarios", "usuarios_permissoes_acesso",
})
LEGACY_TABLES = frozenset({"atividades", "atividade_legacy_map", "matrizes_atividades_itens"})
LEGACY_INDEXES = frozenset({
    "idx_atividade_legacy_map_base", "idx_matriz_itens_matriz",
    "idx_matriz_itens_atividade", "idx_reqs_atividade",
})


class Prod1SchemaError(RuntimeError):
    """Database is neither empty nor a valid SGAA prod-1 database."""


PROD1_SCHEMA_SQL = r"""
CREATE TABLE schema_migrations (
 version INTEGER PRIMARY KEY, name TEXT NOT NULL, schema_epoch TEXT NOT NULL,
 applied_at TEXT NOT NULL DEFAULT (datetime('now')), details_json TEXT
);
CREATE TABLE usuarios (
 id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
 senha TEXT NOT NULL, tipo TEXT NOT NULL CHECK(tipo IN ('admin','aluno')),
 nivel_acesso TEXT NOT NULL DEFAULT 'administrativo', foto_perfil TEXT
);
CREATE TABLE configuracoes_acesso (nivel_acesso TEXT PRIMARY KEY, senha_padrao TEXT NOT NULL);
CREATE TABLE usuarios_permissoes_acesso (
 usuario_id INTEGER NOT NULL, recurso TEXT NOT NULL, escopo TEXT NOT NULL,
 PRIMARY KEY(usuario_id,recurso),
 FOREIGN KEY(usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE ON UPDATE CASCADE
);
CREATE TABLE configuracoes_app (
 chave TEXT PRIMARY KEY, valor TEXT NOT NULL,
 atualizado_em TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE configuracoes_backup (
 chave TEXT PRIMARY KEY, valor TEXT NOT NULL,
 atualizado_em TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE configuracoes_presets (
 tipo TEXT NOT NULL CHECK(tipo IN ('respostas','emails')), preset_id INTEGER NOT NULL,
 titulo TEXT NOT NULL, texto TEXT NOT NULL DEFAULT '',
 atualizado_em TEXT NOT NULL DEFAULT (datetime('now')), PRIMARY KEY(tipo,preset_id)
);
CREATE TABLE cloud_accounts (
 id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT NOT NULL, account_email TEXT,
 token_json TEXT NOT NULL, connected_at TEXT DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT, active INTEGER DEFAULT 1
);
CREATE TABLE backup_logs (
 id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT, file_name TEXT, file_size INTEGER,
 status TEXT, error_message TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE cloud_drive_settings (
 id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT NOT NULL UNIQUE, folder_id TEXT,
 folder_name TEXT, folder_path_label TEXT, drive_id TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE mensagens_editaveis (
 chave TEXT PRIMARY KEY, texto TEXT NOT NULL,
 atualizado_em TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE cursos (
 id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL, codigo TEXT NOT NULL UNIQUE,
 duracao_periodos INTEGER NOT NULL CHECK(duracao_periodos>0),
 total_horas_aac INTEGER NOT NULL DEFAULT 160 CHECK(total_horas_aac>=0),
 total_horas_aeu INTEGER NOT NULL DEFAULT 80 CHECK(total_horas_aeu>=0),
 periodo TEXT NOT NULL DEFAULT 'diurno',
 status TEXT NOT NULL DEFAULT 'ativo' CHECK(status IN ('ativo','inativo'))
);
CREATE TABLE matrizes_atividades (
 id INTEGER PRIMARY KEY AUTOINCREMENT, curso_id INTEGER NOT NULL, nome TEXT NOT NULL,
 versao TEXT NOT NULL, descricao TEXT,
 status TEXT NOT NULL DEFAULT 'rascunho' CHECK(status IN ('rascunho','vigente','encerrada','ativa','inativa')),
 data_inicio_vigencia TEXT, data_fim_vigencia TEXT,
 horas_aac_obrigatorias INTEGER NOT NULL DEFAULT 160 CHECK(horas_aac_obrigatorias>=0),
 horas_extensao_obrigatorias INTEGER NOT NULL DEFAULT 80 CHECK(horas_extensao_obrigatorias>=0),
 matriz_origem_id INTEGER, created_at TEXT NOT NULL DEFAULT (datetime('now')),
 FOREIGN KEY(curso_id) REFERENCES cursos(id) ON DELETE RESTRICT,
 FOREIGN KEY(matriz_origem_id) REFERENCES matrizes_atividades(id) ON DELETE RESTRICT
);
CREATE TABLE turmas (
 id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL UNIQUE, turno TEXT,
 status TEXT NOT NULL DEFAULT 'Ativa' CHECK(status IN ('Ativa','Inativa')),
 numero INTEGER NOT NULL, curso_id INTEGER NOT NULL, ano_inicio INTEGER NOT NULL,
 semestre_inicio INTEGER NOT NULL CHECK(semestre_inicio IN (1,2)), codigo TEXT NOT NULL UNIQUE,
 matriz_id INTEGER, ano_fim INTEGER, semestre_fim INTEGER CHECK(semestre_fim IN (1,2)),
 FOREIGN KEY(curso_id) REFERENCES cursos(id) ON DELETE RESTRICT,
 FOREIGN KEY(matriz_id) REFERENCES matrizes_atividades(id) ON DELETE RESTRICT,
 UNIQUE(curso_id,numero)
);
CREATE TABLE alunos (
 id INTEGER PRIMARY KEY AUTOINCREMENT, usuario_id INTEGER UNIQUE, nome TEXT NOT NULL,
 matricula TEXT UNIQUE NOT NULL, email TEXT UNIQUE, turma_id INTEGER, foto_perfil TEXT,
 status TEXT DEFAULT 'Ativo' CHECK(status IN ('Ativo','Inativo')),
 FOREIGN KEY(usuario_id) REFERENCES usuarios(id) ON DELETE SET NULL ON UPDATE CASCADE,
 FOREIGN KEY(turma_id) REFERENCES turmas(id) ON DELETE RESTRICT ON UPDATE CASCADE
);
CREATE TABLE grupos_def (
 tipo_atividade TEXT NOT NULL CHECK(tipo_atividade IN ('Acadêmica Complementar','Extensão Universitária')),
 numero INTEGER NOT NULL CHECK(numero>0), descricao TEXT,
 PRIMARY KEY(tipo_atividade,numero)
);
CREATE TABLE atividade_base (
 id INTEGER PRIMARY KEY AUTOINCREMENT, nome_conceito TEXT NOT NULL UNIQUE, descricao TEXT,
 status TEXT NOT NULL DEFAULT 'ativo' CHECK(status IN ('ativo','inativo')),
 created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE atividade_versao (
 id INTEGER PRIMARY KEY AUTOINCREMENT, atividade_base_id INTEGER NOT NULL,
 eixo TEXT NOT NULL CHECK(eixo IN ('AAC','AEU')), grupo TEXT,
 ch_por_evento REAL CHECK(ch_por_evento IS NULL OR ch_por_evento>=0),
 limite_semestre REAL CHECK(limite_semestre IS NULL OR limite_semestre>=0),
 limite_total REAL CHECK(limite_total IS NULL OR limite_total>=0),
 observacao_aluno TEXT, observacao_admin TEXT,
 documentos_json TEXT CHECK(documentos_json IS NULL OR json_valid(documentos_json)),
 vigencia_inicio TEXT, vigencia_fim TEXT,
 numero_versao INTEGER NOT NULL DEFAULT 1 CHECK(numero_versao>=1),
 status TEXT NOT NULL DEFAULT 'rascunho' CHECK(status IN ('rascunho','ativa','inativa','descontinuada','substituida')),
 versao_anterior_id INTEGER, created_at TEXT NOT NULL DEFAULT (datetime('now')),
 FOREIGN KEY(atividade_base_id) REFERENCES atividade_base(id) ON DELETE RESTRICT,
 FOREIGN KEY(versao_anterior_id) REFERENCES atividade_versao(id) ON DELETE RESTRICT,
 UNIQUE(atividade_base_id,numero_versao), UNIQUE(id,atividade_base_id)
);
CREATE TABLE atividade_transicao (
 id INTEGER PRIMARY KEY AUTOINCREMENT, from_atividade_versao_id INTEGER,
 to_atividade_versao_id INTEGER,
 tipo_transicao TEXT NOT NULL CHECK(tipo_transicao IN ('mesmo_eixo','aac_para_aeu','nova_aeu','descontinuada','sem_transicao')),
 justificativa TEXT, observacao_admin TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now')),
 FOREIGN KEY(from_atividade_versao_id) REFERENCES atividade_versao(id) ON DELETE RESTRICT,
 FOREIGN KEY(to_atividade_versao_id) REFERENCES atividade_versao(id) ON DELETE RESTRICT,
 CHECK(from_atividade_versao_id IS NOT NULL OR to_atividade_versao_id IS NOT NULL),
 CHECK(from_atividade_versao_id IS NULL OR to_atividade_versao_id IS NULL OR from_atividade_versao_id<>to_atividade_versao_id)
);
CREATE TABLE matriz_atividade_versao_item (
 id INTEGER PRIMARY KEY AUTOINCREMENT, matriz_id INTEGER NOT NULL,
 atividade_base_id INTEGER NOT NULL, atividade_versao_id INTEGER NOT NULL,
 created_at TEXT NOT NULL DEFAULT (datetime('now')),
 FOREIGN KEY(matriz_id) REFERENCES matrizes_atividades(id) ON DELETE CASCADE,
 FOREIGN KEY(atividade_base_id) REFERENCES atividade_base(id) ON DELETE RESTRICT,
 FOREIGN KEY(atividade_versao_id,atividade_base_id) REFERENCES atividade_versao(id,atividade_base_id) ON DELETE RESTRICT,
 UNIQUE(matriz_id,atividade_base_id), UNIQUE(matriz_id,atividade_versao_id)
);
CREATE TABLE requisicoes (
 id INTEGER PRIMARY KEY AUTOINCREMENT, aluno_id INTEGER, atividade_versao_id INTEGER NOT NULL,
 data_solicitacao TEXT NOT NULL, data_evento TEXT NOT NULL,
 horas_solicitadas REAL NOT NULL CHECK(horas_solicitadas>=0), nome_evento TEXT,
 status TEXT NOT NULL CHECK(status IN ('Pendente','Deferida','Deferida Parcialmente','Indeferida','Devolvida','Encerrada')),
 horas_deferidas REAL CHECK(horas_deferidas IS NULL OR horas_deferidas>=0), observacao TEXT,
 data_processamento TEXT, admin_id INTEGER, aluno_update_notified_at TEXT,
 aluno_update_seen_at TEXT,
 regra_snapshot_json TEXT NOT NULL CHECK(json_valid(regra_snapshot_json) AND json_type(regra_snapshot_json)='object'),
 FOREIGN KEY(aluno_id) REFERENCES alunos(id) ON DELETE SET NULL ON UPDATE CASCADE,
 FOREIGN KEY(atividade_versao_id) REFERENCES atividade_versao(id) ON DELETE RESTRICT ON UPDATE CASCADE,
 FOREIGN KEY(admin_id) REFERENCES usuarios(id) ON DELETE SET NULL ON UPDATE CASCADE
);
CREATE TABLE requisicao_arquivos (
 id INTEGER PRIMARY KEY AUTOINCREMENT, requisicao_id INTEGER NOT NULL, label TEXT,
 filename TEXT NOT NULL, criado_em TEXT DEFAULT (datetime('now')),
 FOREIGN KEY(requisicao_id) REFERENCES requisicoes(id) ON DELETE CASCADE
);
CREATE TABLE requisicao_alerta_receipts (
 id INTEGER PRIMARY KEY AUTOINCREMENT, requisicao_id INTEGER NOT NULL,
 usuario_id INTEGER NOT NULL, alert_kind TEXT NOT NULL,
 seen_at TEXT NOT NULL DEFAULT (datetime('now')),
 FOREIGN KEY(requisicao_id) REFERENCES requisicoes(id) ON DELETE CASCADE ON UPDATE CASCADE,
 FOREIGN KEY(usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE ON UPDATE CASCADE,
 UNIQUE(requisicao_id,usuario_id,alert_kind)
);
CREATE TABLE reportes (
 id INTEGER PRIMARY KEY AUTOINCREMENT, aluno_id INTEGER NOT NULL, titulo TEXT NOT NULL,
 descricao TEXT NOT NULL, categoria TEXT NOT NULL DEFAULT 'Bug na plataforma',
 screenshot_filename TEXT, status TEXT NOT NULL DEFAULT 'Novo' CHECK(status IN ('Novo','Em análise','Resolvido')),
 criado_em TEXT NOT NULL DEFAULT (datetime('now')), atualizado_em TEXT NOT NULL DEFAULT (datetime('now')),
 admin_id INTEGER,
 FOREIGN KEY(aluno_id) REFERENCES alunos(id) ON DELETE CASCADE ON UPDATE CASCADE,
 FOREIGN KEY(admin_id) REFERENCES usuarios(id) ON DELETE SET NULL ON UPDATE CASCADE
);
CREATE TABLE admin_arquivos (
 id INTEGER PRIMARY KEY AUTOINCREMENT, titulo TEXT NOT NULL, descricao TEXT,
 filename TEXT NOT NULL, original_filename TEXT, visivel INTEGER NOT NULL DEFAULT 1 CHECK(visivel IN (0,1)),
 criado_em TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE admin_alertas (
 id INTEGER PRIMARY KEY AUTOINCREMENT, titulo TEXT, mensagem TEXT NOT NULL,
 bg_color TEXT NOT NULL DEFAULT '#eff6ff', border_color TEXT NOT NULL DEFAULT '#bfdbfe',
 visivel INTEGER NOT NULL DEFAULT 1 CHECK(visivel IN (0,1)), criado_em TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_usuarios_email ON usuarios(email);
CREATE INDEX idx_usuarios_permissoes_usuario ON usuarios_permissoes_acesso(usuario_id);
CREATE INDEX idx_cloud_accounts_provider_active ON cloud_accounts(provider,active,id DESC);
CREATE INDEX idx_backup_logs_provider_created ON backup_logs(provider,created_at DESC,id DESC);
CREATE INDEX idx_turmas_status ON turmas(status); CREATE INDEX idx_turmas_curso ON turmas(curso_id);
CREATE INDEX idx_turmas_matriz ON turmas(matriz_id); CREATE INDEX idx_alunos_usuario_id ON alunos(usuario_id);
CREATE INDEX idx_alunos_matricula ON alunos(matricula); CREATE INDEX idx_alunos_email ON alunos(email);
CREATE INDEX idx_alunos_turma_id ON alunos(turma_id); CREATE INDEX idx_atividade_versao_base ON atividade_versao(atividade_base_id);
CREATE INDEX idx_atividade_versao_eixo ON atividade_versao(eixo);
CREATE INDEX idx_atividade_versao_status ON atividade_versao(status); CREATE INDEX idx_atividade_transicao_from ON atividade_transicao(from_atividade_versao_id);
CREATE INDEX idx_atividade_transicao_to ON atividade_transicao(to_atividade_versao_id); CREATE INDEX idx_atividade_transicao_tipo ON atividade_transicao(tipo_transicao);
CREATE INDEX idx_matrizes_curso ON matrizes_atividades(curso_id); CREATE INDEX idx_matrizes_status ON matrizes_atividades(status);
CREATE INDEX idx_matriz_atividade_versao_item_matriz ON matriz_atividade_versao_item(matriz_id);
CREATE INDEX idx_matriz_atividade_versao_item_base ON matriz_atividade_versao_item(atividade_base_id);
CREATE INDEX idx_matriz_atividade_versao_item_versao ON matriz_atividade_versao_item(atividade_versao_id);
CREATE INDEX idx_reqs_aluno ON requisicoes(aluno_id); CREATE INDEX idx_reqs_status ON requisicoes(status);
CREATE INDEX idx_requisicoes_atividade_versao_id ON requisicoes(atividade_versao_id);
CREATE INDEX idx_reqs_aluno_update_pending ON requisicoes(aluno_id,aluno_update_seen_at,aluno_update_notified_at);
CREATE INDEX idx_req_arquivos_req ON requisicao_arquivos(requisicao_id);
CREATE INDEX idx_req_alert_receipts_user_kind ON requisicao_alerta_receipts(usuario_id,alert_kind);
CREATE INDEX idx_req_alert_receipts_req ON requisicao_alerta_receipts(requisicao_id);
CREATE INDEX idx_reportes_aluno_id ON reportes(aluno_id); CREATE INDEX idx_reportes_status ON reportes(status);
CREATE INDEX idx_reportes_criado_em ON reportes(criado_em); CREATE INDEX idx_admin_arquivos_visivel ON admin_arquivos(visivel);
CREATE INDEX idx_admin_arquivos_criado_em ON admin_arquivos(criado_em); CREATE INDEX idx_admin_alertas_visivel ON admin_alertas(visivel);

CREATE TRIGGER trg_atividade_versao_prev_same_eixo_insert BEFORE INSERT ON atividade_versao
FOR EACH ROW WHEN NEW.versao_anterior_id IS NOT NULL AND EXISTS(SELECT 1 FROM atividade_versao p WHERE p.id=NEW.versao_anterior_id AND p.eixo<>NEW.eixo)
BEGIN SELECT RAISE(ABORT,'Mudança de eixo exige atividade_transicao'); END;
CREATE TRIGGER trg_atividade_versao_prev_same_eixo_update BEFORE UPDATE OF versao_anterior_id,eixo ON atividade_versao
FOR EACH ROW WHEN NEW.versao_anterior_id IS NOT NULL AND EXISTS(SELECT 1 FROM atividade_versao p WHERE p.id=NEW.versao_anterior_id AND p.eixo<>NEW.eixo)
BEGIN SELECT RAISE(ABORT,'Mudança de eixo exige atividade_transicao'); END;
CREATE TRIGGER trg_atividade_transicao_aac_para_aeu_insert BEFORE INSERT ON atividade_transicao
FOR EACH ROW WHEN NEW.tipo_transicao='aac_para_aeu' BEGIN
 SELECT CASE WHEN NEW.justificativa IS NULL OR TRIM(NEW.justificativa)='' THEN RAISE(ABORT,'Transição aac_para_aeu exige justificativa') END;
 SELECT CASE WHEN NEW.from_atividade_versao_id IS NULL OR NEW.to_atividade_versao_id IS NULL THEN RAISE(ABORT,'Transição aac_para_aeu exige from/to atividade_versao') END;
 SELECT CASE WHEN (SELECT eixo FROM atividade_versao WHERE id=NEW.from_atividade_versao_id)<>'AAC' OR (SELECT eixo FROM atividade_versao WHERE id=NEW.to_atividade_versao_id)<>'AEU' THEN RAISE(ABORT,'Transição aac_para_aeu exige eixo AAC -> AEU') END;
END;
CREATE TRIGGER trg_atividade_transicao_aac_para_aeu_update BEFORE UPDATE OF tipo_transicao,justificativa,from_atividade_versao_id,to_atividade_versao_id ON atividade_transicao
FOR EACH ROW WHEN NEW.tipo_transicao='aac_para_aeu' BEGIN
 SELECT CASE WHEN NEW.justificativa IS NULL OR TRIM(NEW.justificativa)='' THEN RAISE(ABORT,'Transição aac_para_aeu exige justificativa') END;
 SELECT CASE WHEN NEW.from_atividade_versao_id IS NULL OR NEW.to_atividade_versao_id IS NULL THEN RAISE(ABORT,'Transição aac_para_aeu exige from/to atividade_versao') END;
 SELECT CASE WHEN (SELECT eixo FROM atividade_versao WHERE id=NEW.from_atividade_versao_id)<>'AAC' OR (SELECT eixo FROM atividade_versao WHERE id=NEW.to_atividade_versao_id)<>'AEU' THEN RAISE(ABORT,'Transição aac_para_aeu exige eixo AAC -> AEU') END;
END;
CREATE TRIGGER trg_requisicoes_snapshot_immutable
BEFORE UPDATE OF atividade_versao_id,regra_snapshot_json ON requisicoes
FOR EACH ROW WHEN NEW.atividade_versao_id<>OLD.atividade_versao_id OR NEW.regra_snapshot_json<>OLD.regra_snapshot_json
BEGIN SELECT RAISE(ABORT,'request snapshot authority is immutable'); END;

INSERT INTO schema_migrations(version,name,schema_epoch,details_json)
VALUES(1,'first_production_baseline','prod-1','{"schema_epoch":"prod-1"}');
INSERT INTO schema_migrations(version,name,schema_epoch,details_json)
VALUES(2,'remove_norma_domain','prod-1','{"schema_epoch":"prod-1","removed_domain":"norma"}');
PRAGMA user_version=2;
"""


def _names(conn: sqlite3.Connection, kind: str) -> set[str]:
    return {str(row[0]) for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type=? AND name NOT LIKE 'sqlite_%'", (kind,)
    )}


def _user_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def _marker(conn: sqlite3.Connection):
    if "schema_migrations" not in _names(conn, "table"):
        return None
    cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(schema_migrations)")}
    if not {"version", "name", "schema_epoch"} <= cols:
        return None
    return [(int(r[0]), str(r[1]), str(r[2])) for r in conn.execute(
        "SELECT version,name,schema_epoch FROM schema_migrations ORDER BY version"
    )]


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _normalize_schema_sql(value: str | None) -> str | None:
    """Normalize formatting while preserving every schema-relevant token."""
    if value is None:
        return None
    return re.sub(r"\s+", " ", value.strip().rstrip(";")).strip()


def _physical_schema_signature(conn: sqlite3.Connection) -> dict[str, object]:
    """Return a deterministic semantic signature of the SQLite schema.

    The reference signature is generated from ``PROD1_SCHEMA_SQL`` itself, so
    bootstrap and validation cannot silently acquire independent authorities.
    """
    objects = conn.execute(
        """SELECT type,name,tbl_name,sql
             FROM sqlite_master
            WHERE type IN ('table','index','trigger')
              AND name NOT LIKE 'sqlite_%'
         ORDER BY type,name"""
    ).fetchall()
    tables = sorted(str(row[1]) for row in objects if row[0] == "table")
    table_details: dict[str, object] = {}
    for table in tables:
        quoted = _quote_identifier(table)
        columns = [
            tuple(row)
            for row in conn.execute(f"PRAGMA table_xinfo({quoted})").fetchall()
        ]
        foreign_keys = [
            tuple(row)
            for row in conn.execute(f"PRAGMA foreign_key_list({quoted})").fetchall()
        ]
        indexes = []
        for index_row in conn.execute(f"PRAGMA index_list({quoted})").fetchall():
            index_name = str(index_row[1])
            index_quoted = _quote_identifier(index_name)
            index_sql_row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='index' AND name=?",
                (index_name,),
            ).fetchone()
            indexes.append(
                {
                    "metadata": tuple(index_row),
                    "columns": [
                        tuple(row)
                        for row in conn.execute(
                            f"PRAGMA index_xinfo({index_quoted})"
                        ).fetchall()
                    ],
                    "sql": _normalize_schema_sql(
                        index_sql_row[0] if index_sql_row else None
                    ),
                }
            )
        indexes.sort(key=lambda item: str(item["metadata"][1]))
        table_sql = next(
            (row[3] for row in objects if row[0] == "table" and row[1] == table),
            None,
        )
        table_details[table] = {
            "sql": _normalize_schema_sql(table_sql),
            "columns": columns,
            "foreign_keys": foreign_keys,
            "indexes": indexes,
        }
    triggers = [
        (str(row[1]), str(row[2]), _normalize_schema_sql(row[3]))
        for row in objects
        if row[0] == "trigger"
    ]
    return {"tables": table_details, "triggers": triggers}


_EXPECTED_PHYSICAL_SIGNATURE: dict[str, object] | None = None
_PROD1_V1_SIGNATURE_SHA256 = "58b2e8b5dadc8381e03350cb3972a9590844f88c56e1f793e4036e4e6481a877"


def _expected_physical_schema_signature() -> dict[str, object]:
    global _EXPECTED_PHYSICAL_SIGNATURE
    if _EXPECTED_PHYSICAL_SIGNATURE is None:
        reference = sqlite3.connect(":memory:")
        try:
            reference.execute("PRAGMA foreign_keys=ON")
            reference.executescript(PROD1_SCHEMA_SQL)
            _EXPECTED_PHYSICAL_SIGNATURE = _physical_schema_signature(reference)
        finally:
            reference.close()
    return _EXPECTED_PHYSICAL_SIGNATURE


def _physical_schema_digest(conn: sqlite3.Connection) -> str:
    payload = json.dumps(
        _physical_schema_signature(conn),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _validate_prod1_v1_schema(conn: sqlite3.Connection) -> None:
    """Recognize the sole supported previous physical contract exactly."""
    if _user_version(conn) != 1:
        raise Prod1SchemaError("prod-1/v1 user_version mismatch")
    if _marker(conn) != [(1, BASELINE_MARKER, SCHEMA_EPOCH)]:
        raise Prod1SchemaError("prod-1/v1 baseline marker mismatch")
    if _physical_schema_digest(conn) != _PROD1_V1_SIGNATURE_SHA256:
        raise Prod1SchemaError("prod-1/v1 physical schema contract mismatch")
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise Prod1SchemaError(f"prod-1/v1 foreign key violations: {violations!r}")


_ATIVIDADE_VERSAO_V2_SQL = """
CREATE TABLE _atividade_versao_v2 (
 id INTEGER PRIMARY KEY AUTOINCREMENT, atividade_base_id INTEGER NOT NULL,
 eixo TEXT NOT NULL CHECK(eixo IN ('AAC','AEU')), grupo TEXT,
 ch_por_evento REAL CHECK(ch_por_evento IS NULL OR ch_por_evento>=0),
 limite_semestre REAL CHECK(limite_semestre IS NULL OR limite_semestre>=0),
 limite_total REAL CHECK(limite_total IS NULL OR limite_total>=0),
 observacao_aluno TEXT, observacao_admin TEXT,
 documentos_json TEXT CHECK(documentos_json IS NULL OR json_valid(documentos_json)),
 vigencia_inicio TEXT, vigencia_fim TEXT,
 numero_versao INTEGER NOT NULL DEFAULT 1 CHECK(numero_versao>=1),
 status TEXT NOT NULL DEFAULT 'rascunho' CHECK(status IN ('rascunho','ativa','inativa','descontinuada','substituida')),
 versao_anterior_id INTEGER, created_at TEXT NOT NULL DEFAULT (datetime('now')),
 FOREIGN KEY(atividade_base_id) REFERENCES atividade_base(id) ON DELETE RESTRICT,
 FOREIGN KEY(versao_anterior_id) REFERENCES atividade_versao(id) ON DELETE RESTRICT,
 UNIQUE(atividade_base_id,numero_versao), UNIQUE(id,atividade_base_id)
)
"""

_REQUISICOES_V2_SQL = """
CREATE TABLE _requisicoes_v2 (
 id INTEGER PRIMARY KEY AUTOINCREMENT, aluno_id INTEGER, atividade_versao_id INTEGER NOT NULL,
 data_solicitacao TEXT NOT NULL, data_evento TEXT NOT NULL,
 horas_solicitadas REAL NOT NULL CHECK(horas_solicitadas>=0), nome_evento TEXT,
 status TEXT NOT NULL CHECK(status IN ('Pendente','Deferida','Deferida Parcialmente','Indeferida','Devolvida','Encerrada')),
 horas_deferidas REAL CHECK(horas_deferidas IS NULL OR horas_deferidas>=0), observacao TEXT,
 data_processamento TEXT, admin_id INTEGER, aluno_update_notified_at TEXT,
 aluno_update_seen_at TEXT,
 regra_snapshot_json TEXT NOT NULL CHECK(json_valid(regra_snapshot_json) AND json_type(regra_snapshot_json)='object'),
 FOREIGN KEY(aluno_id) REFERENCES alunos(id) ON DELETE SET NULL ON UPDATE CASCADE,
 FOREIGN KEY(atividade_versao_id) REFERENCES atividade_versao(id) ON DELETE RESTRICT ON UPDATE CASCADE,
 FOREIGN KEY(admin_id) REFERENCES usuarios(id) ON DELETE SET NULL ON UPDATE CASCADE
)
"""


def migrate_prod1_v1_to_v2(conn: sqlite3.Connection) -> dict[str, object]:
    """Transactionally remove Norma while preserving every surviving row identity."""
    if conn.in_transaction:
        raise Prod1SchemaError("prod-1/v2 migration requires a clean connection")
    _validate_prod1_v1_schema(conn)
    foreign_keys_enabled = bool(conn.execute("PRAGMA foreign_keys").fetchone()[0])
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        conn.execute("BEGIN IMMEDIATE")
        for name in (
            "trg_requisicoes_snapshot_immutable",
            "trg_atividade_versao_eixo_norma_insert",
            "trg_atividade_versao_eixo_norma_update",
            "trg_atividade_versao_prev_same_eixo_insert",
            "trg_atividade_versao_prev_same_eixo_update",
            "idx_requisicoes_atividade_versao_id",
            "idx_reqs_aluno",
            "idx_reqs_status",
            "idx_reqs_aluno_update_pending",
            "idx_atividade_versao_base",
            "idx_atividade_versao_norma",
            "idx_atividade_versao_eixo",
            "idx_atividade_versao_status",
        ):
            kind = "TRIGGER" if name.startswith("trg_") else "INDEX"
            conn.execute(f"DROP {kind} IF EXISTS {_quote_identifier(name)}")

        conn.execute(_REQUISICOES_V2_SQL)
        conn.execute(
            """INSERT INTO _requisicoes_v2 (
                   id,aluno_id,atividade_versao_id,data_solicitacao,data_evento,
                   horas_solicitadas,nome_evento,status,horas_deferidas,observacao,
                   data_processamento,admin_id,aluno_update_notified_at,
                   aluno_update_seen_at,regra_snapshot_json)
               SELECT id,aluno_id,atividade_versao_id,data_solicitacao,data_evento,
                      horas_solicitadas,nome_evento,status,horas_deferidas,observacao,
                      data_processamento,admin_id,aluno_update_notified_at,
                      aluno_update_seen_at,
                      json_set(
                          json_remove(
                              regra_snapshot_json,
                              '$.norma_id','$.codigo_normativo',
                              '$.norma_codigo','$.norma_revisao'
                          ),
                          '$.schema_version','prod-1-request-v2'
                      )
                 FROM requisicoes"""
        )
        conn.execute("DROP TABLE requisicoes")
        conn.execute(_REQUISICOES_V2_SQL.replace("_requisicoes_v2", "requisicoes", 1))
        conn.execute(
            """INSERT INTO requisicoes (
                   id,aluno_id,atividade_versao_id,data_solicitacao,data_evento,
                   horas_solicitadas,nome_evento,status,horas_deferidas,observacao,
                   data_processamento,admin_id,aluno_update_notified_at,
                   aluno_update_seen_at,regra_snapshot_json)
               SELECT id,aluno_id,atividade_versao_id,data_solicitacao,data_evento,
                      horas_solicitadas,nome_evento,status,horas_deferidas,observacao,
                      data_processamento,admin_id,aluno_update_notified_at,
                      aluno_update_seen_at,regra_snapshot_json
                 FROM _requisicoes_v2"""
        )
        conn.execute("DROP TABLE _requisicoes_v2")

        conn.execute(_ATIVIDADE_VERSAO_V2_SQL)
        conn.execute(
            """INSERT INTO _atividade_versao_v2 (
                   id,atividade_base_id,eixo,grupo,ch_por_evento,limite_semestre,
                   limite_total,observacao_aluno,observacao_admin,documentos_json,
                   vigencia_inicio,vigencia_fim,numero_versao,status,
                   versao_anterior_id,created_at)
               SELECT id,atividade_base_id,eixo,grupo,ch_por_evento,limite_semestre,
                      limite_total,observacao_aluno,observacao_admin,documentos_json,
                      vigencia_inicio,vigencia_fim,numero_versao,status,
                      versao_anterior_id,created_at
                 FROM atividade_versao"""
        )
        conn.execute("DROP TABLE atividade_versao")
        conn.execute(_ATIVIDADE_VERSAO_V2_SQL.replace("_atividade_versao_v2", "atividade_versao", 1))
        conn.execute(
            """INSERT INTO atividade_versao (
                   id,atividade_base_id,eixo,grupo,ch_por_evento,limite_semestre,
                   limite_total,observacao_aluno,observacao_admin,documentos_json,
                   vigencia_inicio,vigencia_fim,numero_versao,status,
                   versao_anterior_id,created_at)
               SELECT id,atividade_base_id,eixo,grupo,ch_por_evento,limite_semestre,
                      limite_total,observacao_aluno,observacao_admin,documentos_json,
                      vigencia_inicio,vigencia_fim,numero_versao,status,
                      versao_anterior_id,created_at
                 FROM _atividade_versao_v2"""
        )
        conn.execute("DROP TABLE _atividade_versao_v2")
        conn.execute("DROP TABLE matriz_norma")
        conn.execute("DROP TABLE norma_atividade")

        surviving_schema = (
            "CREATE INDEX idx_atividade_versao_base ON atividade_versao(atividade_base_id)",
            "CREATE INDEX idx_atividade_versao_eixo ON atividade_versao(eixo)",
            "CREATE INDEX idx_atividade_versao_status ON atividade_versao(status)",
            "CREATE INDEX idx_reqs_aluno ON requisicoes(aluno_id)",
            "CREATE INDEX idx_reqs_status ON requisicoes(status)",
            "CREATE INDEX idx_requisicoes_atividade_versao_id ON requisicoes(atividade_versao_id)",
            "CREATE INDEX idx_reqs_aluno_update_pending ON requisicoes(aluno_id,aluno_update_seen_at,aluno_update_notified_at)",
            """CREATE TRIGGER trg_atividade_versao_prev_same_eixo_insert BEFORE INSERT ON atividade_versao
               FOR EACH ROW WHEN NEW.versao_anterior_id IS NOT NULL AND EXISTS(SELECT 1 FROM atividade_versao p WHERE p.id=NEW.versao_anterior_id AND p.eixo<>NEW.eixo)
               BEGIN SELECT RAISE(ABORT,'Mudança de eixo exige atividade_transicao'); END""",
            """CREATE TRIGGER trg_atividade_versao_prev_same_eixo_update BEFORE UPDATE OF versao_anterior_id,eixo ON atividade_versao
               FOR EACH ROW WHEN NEW.versao_anterior_id IS NOT NULL AND EXISTS(SELECT 1 FROM atividade_versao p WHERE p.id=NEW.versao_anterior_id AND p.eixo<>NEW.eixo)
               BEGIN SELECT RAISE(ABORT,'Mudança de eixo exige atividade_transicao'); END""",
            """CREATE TRIGGER trg_requisicoes_snapshot_immutable
               BEFORE UPDATE OF atividade_versao_id,regra_snapshot_json ON requisicoes
               FOR EACH ROW WHEN NEW.atividade_versao_id<>OLD.atividade_versao_id OR NEW.regra_snapshot_json<>OLD.regra_snapshot_json
               BEGIN SELECT RAISE(ABORT,'request snapshot authority is immutable'); END""",
        )
        for statement in surviving_schema:
            conn.execute(statement)
        conn.execute(
            "INSERT INTO schema_migrations(version,name,schema_epoch,details_json) VALUES(?,?,?,?)",
            (2, LATEST_MIGRATION_MARKER, SCHEMA_EPOCH, '{"schema_epoch":"prod-1","removed_domain":"norma"}'),
        )
        conn.execute("PRAGMA user_version=2")
        validate_prod1_schema(conn)
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise Prod1SchemaError("prod-1/v2 integrity check failed")
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute(f"PRAGMA foreign_keys={'ON' if foreign_keys_enabled else 'OFF'}")
    return validate_prod1_schema(conn)


def validate_prod1_schema(conn: sqlite3.Connection) -> dict[str, object]:
    tables = _names(conn, "table")
    missing, unexpected = EXPECTED_TABLES - tables, tables - EXPECTED_TABLES
    if _user_version(conn) != SCHEMA_VERSION:
        raise Prod1SchemaError("prod-1 user_version mismatch")
    expected_markers = [
        (1, BASELINE_MARKER, SCHEMA_EPOCH),
        (2, LATEST_MIGRATION_MARKER, SCHEMA_EPOCH),
    ]
    if _marker(conn) != expected_markers:
        raise Prod1SchemaError("prod-1 migration marker mismatch")
    if missing or unexpected:
        raise Prod1SchemaError(f"prod-1 table census mismatch: missing={sorted(missing)!r} unexpected={sorted(unexpected)!r}")
    if tables & LEGACY_TABLES or _names(conn, "index") & LEGACY_INDEXES:
        raise Prod1SchemaError("legacy activity schema is forbidden in prod-1")
    actual_signature = _physical_schema_signature(conn)
    expected_signature = _expected_physical_schema_signature()
    if actual_signature != expected_signature:
        raise Prod1SchemaError("prod-1 physical schema contract mismatch")
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise Prod1SchemaError(f"prod-1 foreign key violations: {violations!r}")
    return {"schema_epoch": SCHEMA_EPOCH, "schema_version": SCHEMA_VERSION,
            "baseline_marker": BASELINE_MARKER, "table_count": len(tables)}


def bootstrap_prod1_schema(conn: sqlite3.Connection) -> dict[str, object]:
    if _names(conn, "table") or _names(conn, "index") or _names(conn, "trigger") or _user_version(conn):
        if _user_version(conn) == 1:
            return migrate_prod1_v1_to_v2(conn)
        try:
            return validate_prod1_schema(conn)
        except Prod1SchemaError as exc:
            raise Prod1SchemaError("nonempty database is not a supported prod-1 database") from exc
    try:
        conn.executescript("BEGIN IMMEDIATE;\n" + PROD1_SCHEMA_SQL + "\nCOMMIT;")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    return validate_prod1_schema(conn)


def get_prod1_schema_status(conn: sqlite3.Connection) -> dict[str, object]:
    status = validate_prod1_schema(conn)
    row = conn.execute(
        "SELECT applied_at,details_json FROM schema_migrations WHERE version=?",
        (SCHEMA_VERSION,),
    ).fetchone()
    details = None
    if row and row[1]:
        try: details = json.loads(row[1])
        except (TypeError, ValueError): pass
    return {**status, "migration": {"version": SCHEMA_VERSION, "name": LATEST_MIGRATION_MARKER,
        "schema_epoch": SCHEMA_EPOCH, "applied_at": row[0] if row else None, "details": details}}
