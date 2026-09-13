"""Single DDL authority for the prod-1 ``configuracoes_presets`` table.

Both creation paths consume this constant:

* ``app.prod1_schema.PROD1_SCHEMA_SQL`` interpolates it during bootstrap;
* ``presets_api.ensure_presets_schema`` executes it when the table is absent.

The text carries no trailing semicolon so that it is byte-identical to the
statement SQLite persists in ``sqlite_master.sql``; both paths therefore yield
the same physical schema signature under ``validate_prod1_schema``.
"""

CONFIGURACOES_PRESETS_TABLE_SQL = """CREATE TABLE configuracoes_presets (
 tipo TEXT NOT NULL CHECK(tipo IN ('respostas','emails')), preset_id INTEGER NOT NULL,
 titulo TEXT NOT NULL, texto TEXT NOT NULL DEFAULT '',
 atualizado_em TEXT NOT NULL DEFAULT (datetime('now')), PRIMARY KEY(tipo,preset_id)
)"""

__all__ = ["CONFIGURACOES_PRESETS_TABLE_SQL"]
