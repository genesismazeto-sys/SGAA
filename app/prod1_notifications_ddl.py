"""Single DDL authority for the prod-1/v7 request e-mail notification outbox.

Both creation paths consume these constants:

* ``app.prod1_schema.PROD1_SCHEMA_SQL`` interpolates them during bootstrap;
* ``app.prod1_notifications_v7`` executes them when migrating v6 -> v7.

Each ``CREATE TABLE`` text carries no trailing semicolon so that it is
byte-identical to the statement SQLite persists in ``sqlite_master.sql``; both
paths therefore yield the same physical schema signature under
``validate_prod1_schema``.

Model
-----
``email_envios``
    One row per *outgoing student e-mail*.  Owns the rendered subject/body
    snapshot actually handed to the transport, so a retry re-sends exactly what
    was confirmed rather than re-rendering against mutated presets.

``requisicao_email_eventos``
    One row per *explicit final-decision generation* of a request.  A request
    accumulates several rows over its lifetime (decide -> reopen -> decide
    again).  ``email_envio_id`` is nullable, which models the
    "one e-mail owns many decision generations" cardinality without a third
    join table.

The partial unique index ``ux_req_email_eventos_pendente`` is the invariant
that makes "the request's *current* pending generation" well defined: at most
one ``pending`` row may exist per request at any time.
"""

EMAIL_ENVIOS_TABLE_SQL = """CREATE TABLE email_envios (
 id INTEGER PRIMARY KEY AUTOINCREMENT, aluno_id INTEGER NOT NULL,
 destinatario TEXT NOT NULL, preset_id INTEGER, preset_titulo TEXT,
 assunto TEXT NOT NULL, corpo TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'prepared'
  CHECK(status IN ('prepared','sending','sent','failed','indeterminate')),
 tentativas INTEGER NOT NULL DEFAULT 0 CHECK(tentativas>=0),
 ultimo_erro TEXT, provider_message_id TEXT, idempotency_key TEXT NOT NULL UNIQUE,
 criado_em TEXT NOT NULL DEFAULT (datetime('now')), enviado_em TEXT,
 FOREIGN KEY(aluno_id) REFERENCES alunos(id) ON DELETE RESTRICT ON UPDATE CASCADE
)"""

REQUISICAO_EMAIL_EVENTOS_TABLE_SQL = """CREATE TABLE requisicao_email_eventos (
 id INTEGER PRIMARY KEY AUTOINCREMENT, requisicao_id INTEGER NOT NULL,
 aluno_id INTEGER NOT NULL, destinatario_snapshot TEXT,
 status_decisao TEXT NOT NULL
  CHECK(status_decisao IN ('Deferida','Deferida Parcialmente','Indeferida')),
 horas_solicitadas REAL NOT NULL CHECK(horas_solicitadas>=0),
 horas_deferidas REAL CHECK(horas_deferidas IS NULL OR horas_deferidas>=0),
 justificativa TEXT, atividade_nome TEXT, nome_evento TEXT,
 data_solicitacao TEXT NOT NULL, decidido_em TEXT NOT NULL,
 estado TEXT NOT NULL DEFAULT 'pending'
  CHECK(estado IN ('pending','sent','superseded')),
 email_envio_id INTEGER, criado_em TEXT NOT NULL DEFAULT (datetime('now')),
 enviado_em TEXT, superseded_em TEXT,
 FOREIGN KEY(requisicao_id) REFERENCES requisicoes(id) ON DELETE CASCADE ON UPDATE CASCADE,
 FOREIGN KEY(aluno_id) REFERENCES alunos(id) ON DELETE RESTRICT ON UPDATE CASCADE,
 FOREIGN KEY(email_envio_id) REFERENCES email_envios(id) ON DELETE RESTRICT ON UPDATE CASCADE
)"""

NOTIFICATIONS_V7_INDEXES_SQL = (
    "CREATE UNIQUE INDEX ux_req_email_eventos_pendente"
    " ON requisicao_email_eventos(requisicao_id) WHERE estado='pending'",
    "CREATE INDEX idx_req_email_eventos_req"
    " ON requisicao_email_eventos(requisicao_id,estado)",
    "CREATE INDEX idx_req_email_eventos_envio"
    " ON requisicao_email_eventos(email_envio_id)",
    "CREATE INDEX idx_req_email_eventos_aluno"
    " ON requisicao_email_eventos(aluno_id,estado)",
    "CREATE INDEX idx_email_envios_aluno"
    " ON email_envios(aluno_id,criado_em DESC)",
    "CREATE INDEX idx_email_envios_status" " ON email_envios(status)",
)

NOTIFICATIONS_V7_SCHEMA_OBJECTS_SQL = ";\n".join(
    (
        EMAIL_ENVIOS_TABLE_SQL,
        REQUISICAO_EMAIL_EVENTOS_TABLE_SQL,
        *NOTIFICATIONS_V7_INDEXES_SQL,
    )
) + ";"

NOTIFICATIONS_V7_TABLES = ("email_envios", "requisicao_email_eventos")

__all__ = [
    "EMAIL_ENVIOS_TABLE_SQL",
    "NOTIFICATIONS_V7_INDEXES_SQL",
    "NOTIFICATIONS_V7_SCHEMA_OBJECTS_SQL",
    "NOTIFICATIONS_V7_TABLES",
    "REQUISICAO_EMAIL_EVENTOS_TABLE_SQL",
]
