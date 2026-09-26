"""prod-1/v7 outbox governance retained under the current v8 schema."""

from __future__ import annotations

import sqlite3

import pytest

from app.prod1_schema import (
    EXPECTED_TABLES,
    REQUEST_EMAIL_NOTIFICATIONS_MARKER,
    SCHEMA_EPOCH,
    SCHEMA_VERSION,
    Prod1SchemaError,
    _physical_schema_digest,
    _PROD1_V6_SIGNATURE_SHA256,
    bootstrap_prod1_schema,
    validate_prod1_schema,
)
from app.prod1_notifications_v7 import migrate_prod1_v6_to_v7
from tests.prod1_v11_support import revert_prod1_v11_to_v10


def _fresh() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def test_current_schema_version_is_nine():
    assert SCHEMA_VERSION == 11


def test_expected_tables_include_outbox():
    assert {"email_envios", "requisicao_email_eventos"} <= EXPECTED_TABLES


def test_clean_bootstrap_is_valid_head():
    conn = _fresh()
    status = bootstrap_prod1_schema(conn)
    assert status["schema_version"] == SCHEMA_VERSION == 11
    assert status["schema_epoch"] == SCHEMA_EPOCH
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 11


def test_v7_marker_recorded():
    conn = _fresh()
    bootstrap_prod1_schema(conn)
    markers = [
        (int(r[0]), str(r[1]))
        for r in conn.execute("SELECT version,name FROM schema_migrations ORDER BY version")
    ]
    assert (7, REQUEST_EMAIL_NOTIFICATIONS_MARKER) in markers


def _build_v6(conn: sqlite3.Connection) -> None:
    """Materialize a genuine prod-1/v6 database by reverting the v7 delta.

    The result must hash to ``_PROD1_V6_SIGNATURE_SHA256``; ``test_reverted_v6
    _matches_frozen_signature`` asserts exactly that, so this helper cannot
    silently drift into fabricating a shape the real gate would reject.
    """
    bootstrap_prod1_schema(conn)
    # The bootstrap head is v11; undo its credential rebuild, then drop the
    # later markers. v10's column lives on senha_tokens, which this helper
    # removes wholesale below.
    revert_prod1_v11_to_v10(conn)
    conn.execute("DELETE FROM schema_migrations WHERE version=10")
    conn.execute("ALTER TABLE usuario_credenciais DROP COLUMN acesso_ativo")
    conn.execute("DELETE FROM schema_migrations WHERE version=9")
    conn.execute("DROP TABLE senha_tokens")
    conn.execute("DROP TABLE usuario_credenciais")
    conn.execute(
        "DELETE FROM configuracoes_app WHERE chave='default_passwords_enabled'"
    )
    conn.execute("DELETE FROM schema_migrations WHERE version=8")
    conn.execute("DROP TABLE requisicao_email_eventos")
    conn.execute("DROP TABLE email_envios")
    conn.execute("DROP INDEX ux_configuracoes_presets_default")
    conn.execute(
        """CREATE TABLE _presets_v6 (
 tipo TEXT NOT NULL CHECK(tipo IN ('respostas','emails')), preset_id INTEGER NOT NULL,
 titulo TEXT NOT NULL, texto TEXT NOT NULL DEFAULT '',
 atualizado_em TEXT NOT NULL DEFAULT (datetime('now')), PRIMARY KEY(tipo,preset_id)
)"""
    )
    conn.execute(
        "INSERT INTO _presets_v6(tipo,preset_id,titulo,texto,atualizado_em)"
        " SELECT tipo,preset_id,titulo,texto,atualizado_em FROM configuracoes_presets"
    )
    conn.execute("DROP TABLE configuracoes_presets")
    conn.execute(
        """CREATE TABLE configuracoes_presets (
 tipo TEXT NOT NULL CHECK(tipo IN ('respostas','emails')), preset_id INTEGER NOT NULL,
 titulo TEXT NOT NULL, texto TEXT NOT NULL DEFAULT '',
 atualizado_em TEXT NOT NULL DEFAULT (datetime('now')), PRIMARY KEY(tipo,preset_id)
)"""
    )
    conn.execute("INSERT INTO configuracoes_presets SELECT * FROM _presets_v6")
    conn.execute("DROP TABLE _presets_v6")
    conn.execute("DELETE FROM schema_migrations WHERE version=7")
    conn.execute("PRAGMA user_version=6")
    conn.commit()


def test_reverted_v6_matches_frozen_signature():
    conn = _fresh()
    _build_v6(conn)
    assert _physical_schema_digest(conn) == _PROD1_V6_SIGNATURE_SHA256


def test_v6_to_v7_migration_round_trip():
    """A real v6 database migrates forward and validates as v7."""
    conn = _fresh()
    _build_v6(conn)
    conn.execute(
        "INSERT INTO configuracoes_presets(tipo,preset_id,titulo,texto)"
        " VALUES('respostas',1,'Justificativa legada','texto legado')"
    )
    conn.execute(
        "INSERT INTO configuracoes_presets(tipo,preset_id,titulo,texto)"
        " VALUES('emails',1,'Modelo legado','corpo legado')"
    )
    conn.commit()

    status = migrate_prod1_v6_to_v7(conn)

    assert status["schema_version"] == 7
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 7
    # Legacy preset rows survive, with safe defaults for the new columns.
    legacy = conn.execute(
        "SELECT titulo,texto,assunto,is_default FROM configuracoes_presets"
        " WHERE tipo='emails' AND preset_id=1"
    ).fetchone()
    assert legacy["titulo"] == "Modelo legado"
    assert legacy["texto"] == "corpo legado"
    assert legacy["assunto"] == ""
    assert legacy["is_default"] == 0
    justification = conn.execute(
        "SELECT titulo,texto FROM configuracoes_presets WHERE tipo='respostas' AND preset_id=1"
    ).fetchone()
    assert justification["titulo"] == "Justificativa legada"
    # And no notification history was invented.
    assert conn.execute("SELECT COUNT(*) FROM requisicao_email_eventos").fetchone()[0] == 0


def test_migration_does_not_backfill_existing_final_requests():
    """RULING 2 on a populated v6 database."""
    from tests.request_email_support import seed_activity, seed_request, seed_student

    conn = _fresh()
    _build_v6(conn)
    versao = seed_activity(conn)
    aluno = seed_student(conn, nome="Maria", matricula="2026010", email="maria@x.com")
    for status in ("Deferida", "Deferida Parcialmente", "Indeferida", "Encerrada"):
        seed_request(conn, aluno_id=aluno, versao_id=versao, status=status)
    conn.commit()

    migrate_prod1_v6_to_v7(conn)

    assert conn.execute("SELECT COUNT(*) FROM requisicao_email_eventos").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM email_envios").fetchone()[0] == 0


def test_v6_signature_constant_is_pinned():
    # The frozen predecessor digest must be a real 64-char sha256, not a
    # placeholder, otherwise the v6 gate would accept anything.
    assert len(_PROD1_V6_SIGNATURE_SHA256) == 64
    assert set(_PROD1_V6_SIGNATURE_SHA256) <= set("0123456789abcdef")


def test_migration_rejects_non_v6_database():
    conn = _fresh()
    bootstrap_prod1_schema(conn)  # already current v8
    with pytest.raises(Prod1SchemaError):
        migrate_prod1_v6_to_v7(conn)


def test_current_bootstraps_match_physically(tmp_path):
    """Two current bootstraps must be physically identical."""
    from tests.request_email_support import new_v7_connection

    fresh = new_v7_connection()
    reference = _physical_schema_digest(fresh)

    other = _fresh()
    bootstrap_prod1_schema(other)
    assert _physical_schema_digest(other) == reference


def test_no_historical_backfill_of_pending_events():
    """RULING 2: existing final decisions must not become e-mail-pending."""
    from tests.request_email_support import seed_activity, seed_request, seed_student

    conn = _fresh()
    bootstrap_prod1_schema(conn)
    versao = seed_activity(conn)
    aluno = seed_student(conn, nome="João Silva", matricula="2026001", email="joao@x.com")
    for status in ("Deferida", "Deferida Parcialmente", "Indeferida"):
        seed_request(conn, aluno_id=aluno, versao_id=versao, status=status)
    conn.commit()

    # Historical rows exist with final statuses...
    assert conn.execute(
        "SELECT COUNT(*) FROM requisicoes WHERE status<>'Pendente'"
    ).fetchone()[0] == 3
    # ...and yet nothing is pending, because status alone never creates events.
    assert conn.execute("SELECT COUNT(*) FROM requisicao_email_eventos").fetchone()[0] == 0


def test_only_one_pending_event_per_request_is_possible():
    from tests.request_email_support import seed_activity, seed_request, seed_student

    conn = _fresh()
    bootstrap_prod1_schema(conn)
    versao = seed_activity(conn)
    aluno = seed_student(conn, nome="Ana", matricula="2026002", email="ana@x.com")
    req = seed_request(conn, aluno_id=aluno, versao_id=versao)
    insert = (
        "INSERT INTO requisicao_email_eventos"
        "(requisicao_id,aluno_id,status_decisao,horas_solicitadas,"
        " data_solicitacao,decidido_em,estado)"
        " VALUES(?,?,'Deferida',10,'2026-03-10','2026-04-01','pending')"
    )
    conn.execute(insert, (req, aluno))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(insert, (req, aluno))


def test_presets_gain_subject_and_default_columns():
    conn = _fresh()
    bootstrap_prod1_schema(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(configuracoes_presets)")}
    assert {"assunto", "is_default"} <= cols


def test_only_one_default_email_preset_allowed():
    conn = _fresh()
    bootstrap_prod1_schema(conn)
    conn.execute(
        "INSERT INTO configuracoes_presets(tipo,preset_id,titulo,texto,assunto,is_default)"
        " VALUES('emails',1,'A','corpo','assunto',1)"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO configuracoes_presets(tipo,preset_id,titulo,texto,assunto,is_default)"
            " VALUES('emails',2,'B','corpo','assunto',1)"
        )


def test_validate_rejects_unexpected_table():
    conn = _fresh()
    bootstrap_prod1_schema(conn)
    conn.execute("CREATE TABLE intruso(id INTEGER PRIMARY KEY)")
    with pytest.raises(Prod1SchemaError):
        validate_prod1_schema(conn)
