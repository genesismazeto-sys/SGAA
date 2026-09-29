"""Canonical prod-1/v12 extension-hours schema objects.

v12 changes one column DEFAULT in each of two tables: Extensão falls back to
160 h, the same as Acadêmica Complementar.

    cursos.total_horas_aeu                         DEFAULT 80 -> DEFAULT 160
    matrizes_atividades.horas_extensao_obrigatorias DEFAULT 80 -> DEFAULT 160

THE CONTRACT
    The SGAA default for both kinds of complementary hours is 160 h: it is what
    ``configuracoes_app.horas_padrao_extensao`` ships with (``app.db``) and what
    the Matriz form pre-fills. The 80 h Extensão default was a leftover of the
    first baseline and reached new rows only where an INSERT omitted the column
    -- Nova Curso does exactly that for ``cursos`` -- so the database, not the
    application, was deciding the value.

    A DEFAULT applies to future rows only. Every stored value is kept exactly
    as it is: a course or matrix that holds 80 keeps 80. Nothing is backfilled.

WHY A TABLE REBUILD AND NOT AN ALTER
    SQLite cannot change a column DEFAULT in place, so both tables are rebuilt
    from these statements, the same text the bootstrap executes: a migrated
    database and a freshly bootstrapped one store identical DDL and reach the
    same physical signature. Column order, types, CHECK constraints, foreign
    keys and the two ``matrizes_atividades`` indexes are unchanged.
"""

from __future__ import annotations


CURSOS_V12_TABLE_SQL = """CREATE TABLE cursos (
 id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL, codigo TEXT NOT NULL UNIQUE,
 duracao_periodos INTEGER NOT NULL CHECK(duracao_periodos>0),
 total_horas_aac INTEGER NOT NULL DEFAULT 160 CHECK(total_horas_aac>=0),
 total_horas_aeu INTEGER NOT NULL DEFAULT 160 CHECK(total_horas_aeu>=0),
 periodo TEXT NOT NULL DEFAULT 'diurno',
 status TEXT NOT NULL DEFAULT 'ativo' CHECK(status IN ('ativo','inativo'))
)"""

MATRIZES_ATIVIDADES_V12_TABLE_SQL = """CREATE TABLE matrizes_atividades (
 id INTEGER PRIMARY KEY AUTOINCREMENT, curso_id INTEGER NOT NULL, nome TEXT NOT NULL,
 descricao TEXT,
 status TEXT NOT NULL DEFAULT 'rascunho' CHECK(status IN ('rascunho','vigente','encerrada','ativa','inativa')),
 data_inicio_vigencia TEXT, data_fim_vigencia TEXT,
 horas_aac_obrigatorias INTEGER NOT NULL DEFAULT 160 CHECK(horas_aac_obrigatorias>=0),
 horas_extensao_obrigatorias INTEGER NOT NULL DEFAULT 160 CHECK(horas_extensao_obrigatorias>=0),
 created_at TEXT NOT NULL DEFAULT (datetime('now')),
 FOREIGN KEY(curso_id) REFERENCES cursos(id) ON DELETE RESTRICT
)"""

MATRIZES_ATIVIDADES_INDEX_SQL = (
    "CREATE INDEX idx_matrizes_curso ON matrizes_atividades(curso_id)",
    "CREATE INDEX idx_matrizes_status ON matrizes_atividades(status)",
)

CURSOS_COLUMNS = (
    "id", "nome", "codigo", "duracao_periodos", "total_horas_aac",
    "total_horas_aeu", "periodo", "status",
)
MATRIZES_ATIVIDADES_COLUMNS = (
    "id", "curso_id", "nome", "descricao", "status", "data_inicio_vigencia",
    "data_fim_vigencia", "horas_aac_obrigatorias", "horas_extensao_obrigatorias",
    "created_at",
)


__all__ = [
    "CURSOS_COLUMNS",
    "CURSOS_V12_TABLE_SQL",
    "MATRIZES_ATIVIDADES_COLUMNS",
    "MATRIZES_ATIVIDADES_INDEX_SQL",
    "MATRIZES_ATIVIDADES_V12_TABLE_SQL",
]
