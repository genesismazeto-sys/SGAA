"""Single DDL authority for the prod-1 ``configuracoes_presets`` table.

Both creation paths consume this constant:

* ``app.prod1_schema.PROD1_SCHEMA_SQL`` interpolates it during bootstrap;
* ``presets_api.ensure_presets_schema`` executes it when the table is absent.

The text carries no trailing semicolon so that it is byte-identical to the
statement SQLite persists in ``sqlite_master.sql``; both paths therefore yield
the same physical schema signature under ``validate_prod1_schema``.

prod-1/v7 columns
-----------------
``titulo`` stays what it has always been -- the *internal* model label shown in
the Pré-definições picker.  It is deliberately **not** the outgoing subject.

``assunto``
    The real outbound e-mail subject.  Empty for ``respostas`` rows, which have
    no outbound identity.

``is_default``
    Explicit designation of the single e-mail model the Requisições send action
    uses.  ``ux_configuracoes_presets_default`` enforces at most one default per
    ``tipo``, so the default is never inferred from row order or smallest id.
"""

CONFIGURACOES_PRESETS_TABLE_SQL = """CREATE TABLE configuracoes_presets (
 tipo TEXT NOT NULL CHECK(tipo IN ('respostas','emails')), preset_id INTEGER NOT NULL,
 titulo TEXT NOT NULL, texto TEXT NOT NULL DEFAULT '',
 atualizado_em TEXT NOT NULL DEFAULT (datetime('now')),
 assunto TEXT NOT NULL DEFAULT '',
 is_default INTEGER NOT NULL DEFAULT 0 CHECK(is_default IN (0,1)),
 PRIMARY KEY(tipo,preset_id)
)"""

CONFIGURACOES_PRESETS_DEFAULT_INDEX_SQL = (
    "CREATE UNIQUE INDEX ux_configuracoes_presets_default"
    " ON configuracoes_presets(tipo) WHERE is_default=1"
)

__all__ = [
    "CONFIGURACOES_PRESETS_DEFAULT_INDEX_SQL",
    "CONFIGURACOES_PRESETS_TABLE_SQL",
]
