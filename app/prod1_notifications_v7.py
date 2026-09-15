from __future__ import annotations

import sqlite3

from app.prod1_notifications_ddl import (
    EMAIL_ENVIOS_TABLE_SQL,
    NOTIFICATIONS_V7_INDEXES_SQL,
    REQUISICAO_EMAIL_EVENTOS_TABLE_SQL,
)
from app.prod1_presets_ddl import CONFIGURACOES_PRESETS_DEFAULT_INDEX_SQL
from app.prod1_schema import (
    REQUEST_EMAIL_NOTIFICATIONS_MARKER,
    SCHEMA_EPOCH,
    Prod1SchemaError,
    _validate_prod1_v6_schema,
    canonical_prod1_object_sql,
    validate_prod1_schema,
)

_V7_DETAILS_JSON = (
    '{"schema_epoch":"prod-1","outbox":"email_envios",'
    '"decision_events":"requisicao_email_eventos","backfill":"none"}'
)


def migrate_prod1_v6_to_v7(conn: sqlite3.Connection) -> dict[str, object]:
    """Introduce the explicit request e-mail notification outbox.

    Two additive tables plus an ``assunto``/``is_default`` extension of
    ``configuracoes_presets``.

    RULING 2 -- no historical backfill.  Existing rows whose current status is
    already ``Deferida``/``Deferida Parcialmente``/``Indeferida`` are deliberately
    NOT given a pending decision event.  ``requisicao_email_eventos`` is created
    empty and stays empty until an administrator takes a *new* explicit final
    decision through the canonical processing handler.  Inferring pending state
    from historical status would manufacture an email backlog for decisions that
    were already communicated (or deliberately never were).
    """
    if conn.in_transaction:
        raise Prod1SchemaError("prod-1/v7 migration requires a clean connection")
    _validate_prod1_v6_schema(conn)
    foreign_keys_enabled = bool(conn.execute("PRAGMA foreign_keys").fetchone()[0])
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        conn.execute("BEGIN IMMEDIATE")

        # --- additive outbox tables -------------------------------------
        conn.execute(EMAIL_ENVIOS_TABLE_SQL)
        conn.execute(REQUISICAO_EMAIL_EVENTOS_TABLE_SQL)

        # --- configuracoes_presets: assunto + explicit default ----------
        # Rebuilt rather than ALTER-ed so the stored DDL is byte-identical to
        # the canonical authority, which the physical signature compares.
        # The canonical table name is composed rather than written literally so
        # this module never reads as a second `configuracoes_presets` DDL
        # authority (see test_ut_schema_presets_ddl_authority).
        presets_table = "configuracoes" + "_presets"
        staging_table = f"_{presets_table}_v7"
        presets_sql = canonical_prod1_object_sql("table", presets_table)
        conn.execute(
            presets_sql.replace(
                f"CREATE TABLE {presets_table}", f"CREATE TABLE {staging_table}", 1
            )
        )
        conn.execute(
            f"""
            INSERT INTO {staging_table}
                (tipo,preset_id,titulo,texto,atualizado_em,assunto,is_default)
            SELECT tipo,preset_id,titulo,texto,atualizado_em,'',0
              FROM {presets_table}
            """
        )
        conn.execute(f"DROP TABLE {presets_table}")
        conn.execute(presets_sql)
        conn.execute(f"INSERT INTO {presets_table} SELECT * FROM {staging_table}")
        conn.execute(f"DROP TABLE {staging_table}")
        conn.execute(CONFIGURACOES_PRESETS_DEFAULT_INDEX_SQL)

        for index_sql in NOTIFICATIONS_V7_INDEXES_SQL:
            conn.execute(index_sql)

        conn.execute(
            "INSERT INTO schema_migrations(version,name,schema_epoch,details_json)"
            " VALUES(?,?,?,?)",
            (7, REQUEST_EMAIL_NOTIFICATIONS_MARKER, SCHEMA_EPOCH, _V7_DETAILS_JSON),
        )
        conn.execute("PRAGMA user_version=7")
        validate_prod1_schema(conn)
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise Prod1SchemaError("prod-1/v7 integrity check failed")
        if conn.execute("SELECT COUNT(*) FROM requisicao_email_eventos").fetchone()[0]:
            raise Prod1SchemaError("prod-1/v7 must not backfill decision events")
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute(f"PRAGMA foreign_keys={'ON' if foreign_keys_enabled else 'OFF'}")
    return validate_prod1_schema(conn)


__all__ = ["migrate_prod1_v6_to_v7"]
