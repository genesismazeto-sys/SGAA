# coding: utf-8
"""PostgreSQL-readiness Unit 5-B: runtime SQL dialect + error normalization.

U5-B closes the ordinary-runtime dialect gap left by U5-A:

* one engine-neutral SQL dialect surface (``app.sql_dialect``) owns the
  recurring SQLite/PostgreSQL fragments (current UTC text, date extraction,
  datetime ordering, date display, JSON text extraction, newline);
* ``INSERT OR IGNORE`` runtime seeds become portable
  ``INSERT ... ON CONFLICT DO NOTHING``;
* PostgreSQL constraint names are normalised to the same neutral logical
  identity the SQLite runtime already reports, and SQLSTATE ``SG001`` trigger
  refusals classify as integrity/business errors;
* PostgreSQL application-data defaults are seeded idempotently without schema
  DDL and without stealing caller transaction ownership;
* runtime schema-status is engine-aware (``pg_schema_meta``, never
  ``sqlite_master``/``PRAGMA``).

No PostgreSQL server is required: PostgreSQL paths are exercised through
psycopg-shaped recording doubles and SQL-shape assertions.  SQLite behaviour is
proved against real SQLite connections.
"""
import ast
import inspect
import sqlite3
import types
from pathlib import Path

import psycopg.errors
import pytest

import main  # noqa: F401  (canonical runtime; conftest redirects APP_DATABASE)
from app import db as app_db
from app import sql_dialect

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Runtime modules U5-B cleaned; the static gate must find no unapproved
#: SQLite-only SQL token in their string literals.
_GATE_MODULES = (
    "app/settings.py",
    "app/user_accounts.py",
    "app/password_tokens.py",
    "app/access_onboarding.py",
    "app/cloud_connections.py",
    "app/request_email_dispatch.py",
    "app/requisitions.py",
    "app/admin_alerts.py",
    "app/activity_catalog.py",
    "app/backup_settings.py",
    "app/views/admin/reportes.py",
    "app/views/admin/banco_dados.py",
    "app/views/admin/dashboard.py",
    "app/views/admin/arquivos.py",
    "app/views/admin/requisicoes.py",
    "app/views/admin/matrizes.py",
    "app/views/aluno.py",
    "utils/messages.py",
)

#: Files intentionally allowed to contain SQLite-only SQL, each with a concrete
#: owner reason.  This is a narrow, documented exemption -- not a blanket
#: allowlist.
_GATE_EXEMPTIONS = {
    "app/sql_dialect.py": "engine-neutral dialect owner (SQLite branch intentional)",
    "app/db.py": "canonical SQLite connection setup (engine-guarded PRAGMA)",
    "app/db_maintenance.py": "SQLite schema/migration+backup authority and engine-guarded validation",
    # U5-D moved this file's PTBR/NOCASE ordering into app.sql_dialect; the
    # exemption now covers only the engine-guarded sqlite_master probe.
    "app/views/admin/atividades.py": "engine-guarded grupos_def check (sqlite_master probe)",
    "app/versioning/integrity.py": "UT-16 frozen MOVE-DO-NOT-CHANGE fingerprint; not PG-reachable",
    "app/backup/automatic.py": "SQLite backup engine",
    "app/backup/orchestrator.py": "SQLite backup engine",
    "app/services/backup_service.py": "SQLite backup engine",
    "presets_api.py": "SQLite presets schema authority (sqlite_master create-if-absent)",
}

_FORBIDDEN_TOKENS = (
    "datetime('now')",
    "strftime(",
    "json_extract(",
    "INSERT OR IGNORE",
    "COLLATE NOCASE",
    "sqlite_master",
    "PRAGMA",
    # U5-D: SQLite-only human-text SQL, owned by app.sql_dialect only.
    "COLLATE PTBR",
    "PTBR_FOLD(",
    "INSTR(",
)


def _is_exempt(relative: str) -> bool:
    if relative in _GATE_EXEMPTIONS:
        return True
    name = Path(relative).name
    return name.startswith("prod1_")


class _PgFakeCursor:
    def __init__(self, connection, sql, params):
        self._connection = connection
        self._sql = sql
        self._params = params
        self.rowcount = 1
        self.description = None

    def fetchone(self):
        sql = self._sql.lower()
        if "current_schema()" in sql:
            return (self._connection.current_schema,)
        if "pg_schema_meta" in sql and "from pg_schema_meta" in sql:
            return self._connection.meta_row
        if "from schema_migrations" in sql:
            return self._connection.migration_row
        if "sgaa_utcnow_text" in sql:
            return (self._connection.utc_now,)
        return None

    def fetchall(self):
        sql = self._sql.lower()
        if "pg_catalog.pg_class" in sql:
            return [(table,) for table in sorted(self._connection.tables)]
        if "current_schema()" in sql:
            return [(self._connection.current_schema,)]
        if "pg_schema_meta" in sql and "from pg_schema_meta" in sql:
            return [self._connection.meta_row]
        if "from schema_migrations" in sql:
            return [self._connection.migration_row]
        return []

    def __iter__(self):
        return iter(self.fetchall())


class _PgRecordingConnection:
    """psycopg-shaped recording double: records SQL, never executes it."""

    def __init__(self, *, tables=(), current_schema="public", utc_now="2026-10-05 12:00:00"):
        self.statements = []
        self.commits = 0
        self.rollbacks = 0
        self.tables = set(tables)
        self.current_schema = current_schema
        self.utc_now = utc_now
        # The contract digest must match the authority for status reads.
        from app.pg_schema import PG_CONTRACT_SHA256

        self.meta_row = (1, "prod-1", 12, PG_CONTRACT_SHA256, "2026-01-01 00:00:00")
        self.migration_row = (
            "extension_hours_default",
            "2026-01-01 00:00:00",
            '{"schema_epoch":"prod-1"}',
        )

    @property
    def info(self):
        return types.SimpleNamespace(
            transaction_status=types.SimpleNamespace(name="IDLE")
        )

    def execute(self, sql, params=None):
        self.statements.append((str(sql), params))
        return _PgFakeCursor(self, str(sql), params)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


def _pg_connection(*tables):
    return _PgRecordingConnection(tables=tables)


def _statements(connection):
    return [sql for sql, _ in connection.statements]


def _assert_no_sqlite_only(connection):
    for sql in _statements(connection):
        lowered = sql.lower()
        for token in _FORBIDDEN_TOKENS:
            assert token.lower() not in lowered, f"SQLite-only token {token!r} in: {sql}"


# ---------------------------------------------------------------------------
# 1. dialect surface
# ---------------------------------------------------------------------------


def test_dialect_current_utc_text_engine_specific():
    sqlite_conn = sqlite3.connect(":memory:")
    try:
        assert sql_dialect.current_utc_text(sqlite_conn) == "datetime('now')"
    finally:
        sqlite_conn.close()
    assert sql_dialect.current_utc_text(_pg_connection()) == "sgaa_utcnow_text()"


def test_dialect_date_compare_is_bound_and_engine_specific():
    sqlite_conn = sqlite3.connect(":memory:")
    try:
        sqlite_fragment = sql_dialect.date_compare(sqlite_conn, "r.data_evento", ">=")
    finally:
        sqlite_conn.close()
    assert sqlite_fragment == "date(r.data_evento) >= date(?)"
    pg_fragment = sql_dialect.date_compare(_pg_connection(), "r.data_evento", ">=")
    assert pg_fragment.count("?") == 1
    assert "sgaa_datetime_text_valid" in pg_fragment
    assert "date(" not in pg_fragment
    assert "::timestamp" not in pg_fragment


def test_dialect_datetime_order_engine_specific():
    sqlite_conn = sqlite3.connect(":memory:")
    try:
        assert sql_dialect.datetime_order(sqlite_conn, "criado_em") == "datetime(criado_em)"
    finally:
        sqlite_conn.close()
    assert sql_dialect.datetime_order(_pg_connection(), "criado_em") == "COALESCE(criado_em, '')"


def test_dialect_format_date_ptbr_engine_specific():
    sqlite_conn = sqlite3.connect(":memory:")
    try:
        assert (
            sql_dialect.format_date_ptbr(sqlite_conn, "criado_em")
            == "strftime('%d/%m/%Y', criado_em)"
        )
    finally:
        sqlite_conn.close()
    pg_fragment = sql_dialect.format_date_ptbr(_pg_connection(), "criado_em")
    assert "to_char" in pg_fragment
    assert "sgaa_datetime_text_valid" in pg_fragment


def test_dialect_json_text_engine_specific_and_key_validated():
    sqlite_conn = sqlite3.connect(":memory:")
    try:
        assert (
            sql_dialect.json_text(sqlite_conn, "regra_snapshot_json", "eixo")
            == "json_extract(regra_snapshot_json, '$.eixo')"
        )
    finally:
        sqlite_conn.close()
    pg_fragment = sql_dialect.json_text(_pg_connection(), "regra_snapshot_json", "eixo")
    assert pg_fragment == "((regra_snapshot_json)::jsonb ->> 'eixo')"
    with pytest.raises(ValueError):
        sql_dialect.json_text(_pg_connection(), "c", "eixo'; DROP TABLE usuarios; --")


def test_dialect_newline_and_days_before_now():
    sqlite_conn = sqlite3.connect(":memory:")
    try:
        assert sql_dialect.newline(sqlite_conn) == "char(10)"
        fragment = sql_dialect.datetime_before_now_days(sqlite_conn, "data_processamento")
    finally:
        sqlite_conn.close()
    assert fragment == "datetime(data_processamento) <= datetime('now', '-' || ? || ' days')"
    pg = _pg_connection()
    assert sql_dialect.newline(pg) == "chr(10)"
    pg_fragment = sql_dialect.datetime_before_now_days(pg, "data_processamento")
    assert pg_fragment.count("?") == 1
    assert "make_interval" in pg_fragment
    assert "sgaa_utcnow_text()" in pg_fragment


def test_dialect_returns_only_fixed_fragments_no_interpolated_values():
    """Every fragment uses ``?`` placeholders, never a formatted value."""
    for fragment in (
        sql_dialect.date_compare(_pg_connection(), "col", ">="),
        sql_dialect.datetime_before_now_days(_pg_connection(), "col"),
    ):
        assert fragment.count("?") == 1


def test_dialect_rejects_non_identifier_columns():
    pg = _pg_connection()
    for bad in ("col; DROP TABLE usuarios", "col) --", "col'", "a.b.c"):
        with pytest.raises(ValueError):
            sql_dialect.date_compare(pg, bad, ">=")
        with pytest.raises(ValueError):
            sql_dialect.datetime_order(pg, bad)
        with pytest.raises(ValueError):
            sql_dialect.format_date_ptbr(pg, bad)
        with pytest.raises(ValueError):
            sql_dialect.json_text(pg, bad, "eixo")


def test_date_compare_supports_every_currently_used_operator():
    """The allowlist is exactly the operators production callers use."""
    assert sql_dialect._ALLOWED_DATE_COMPARISON_OPERATORS == frozenset({">=", "<="})
    for operator in sorted(sql_dialect._ALLOWED_DATE_COMPARISON_OPERATORS):
        sqlite_conn = sqlite3.connect(":memory:")
        try:
            sqlite_fragment = sql_dialect.date_compare(
                sqlite_conn, "r.data_evento", operator
            )
        finally:
            sqlite_conn.close()
        pg_fragment = sql_dialect.date_compare(
            _pg_connection(), "r.data_evento", operator
        )
        for fragment in (sqlite_fragment, pg_fragment):
            assert operator in fragment
            assert fragment.count("?") == 1


@pytest.mark.parametrize(
    "hostile",
    [
        ">= ?; SELECT pg_sleep(1); --",
        ">=; DROP TABLE x",
        "LIKE",
        "IS",
        "",
        " ",
        " >= ",
        ">=\t",
        ">= AND",
        "= 1 OR 1=1 --",
        "==",
        "!=",
        "<",
        ">",
        "=",
        ">= ?",
        "IN",
        "BETWEEN",
    ],
)
def test_date_compare_rejects_unapproved_operators_before_sql(hostile):
    pg = _pg_connection()
    before = len(pg.statements)
    with pytest.raises(ValueError):
        sql_dialect.date_compare(pg, "r.data_evento", hostile)
    # Rejection happens before any SQL is constructed or recorded/executed.
    assert len(pg.statements) == before

    sqlite_conn = sqlite3.connect(":memory:")
    try:
        with pytest.raises(ValueError):
            sql_dialect.date_compare(sqlite_conn, "r.data_evento", hostile)
    finally:
        sqlite_conn.close()


def test_date_compare_bound_date_value_is_a_parameter_not_interpolation():
    for operator in (">=", "<="):
        fragment = sql_dialect.date_compare(_pg_connection(), "r.data_evento", operator)
        assert fragment.count("?") == 1
        assert "2026" not in fragment
        # The only character sequence after the operator is the bound placeholder.
        assert fragment.rstrip().endswith("?")


# ---------------------------------------------------------------------------
# 2. constraint-name normalization + SG001
# ---------------------------------------------------------------------------


def _pg_unique(constraint_name):
    return psycopg.errors.UniqueViolation(
        f'duplicate key value violates unique constraint "{constraint_name}"'
    )


@pytest.mark.parametrize(
    "pg_name,identity",
    [
        ("uq_usuarios_email", "usuarios.email"),
        ("uq_alunos_matricula", "alunos.matricula"),
        ("uq_alunos_email", "alunos.email"),
        ("uq_alunos_usuario_id", "alunos.usuario_id"),
        ("uq_cursos_codigo", "cursos.codigo"),
        ("uq_atividade_base_nome_conceito", "atividade_base.nome_conceito"),
        ("uq_turmas_nome", "turmas.nome"),
        ("uq_turmas_codigo", "turmas.codigo"),
        ("uq_turmas_curso_id_numero", "turmas.curso_id, turmas.numero"),
        ("uq_senha_tokens_token_hash", "senha_tokens.token_hash"),
        (
            "uq_atividade_versao_atividade_base_id_numero_versao",
            "atividade_versao.atividade_base_id, atividade_versao.numero_versao",
        ),
        (
            "uq_atividade_versao_id_atividade_base_id",
            "atividade_versao.id, atividade_versao.atividade_base_id",
        ),
    ],
)
def test_postgres_explicit_constraint_names_normalize_to_neutral_identity(pg_name, identity):
    exc = _pg_unique(pg_name)
    assert app_db.is_unique_violation(exc) is True
    assert app_db.integrity_constraint_name(exc) == identity


def test_sqlite_and_postgres_errors_share_neutral_identity():
    sqlite_exc = sqlite3.IntegrityError("UNIQUE constraint failed: cursos.codigo")
    pg_exc = _pg_unique("uq_cursos_codigo")
    assert app_db.integrity_constraint_name(sqlite_exc) == "cursos.codigo"
    assert app_db.integrity_constraint_name(pg_exc) == "cursos.codigo"


def test_unknown_postgres_constraint_name_stays_diagnosable():
    exc = _pg_unique("usuarios_email_key")
    assert app_db.integrity_constraint_name(exc) == "usuarios_email_key"


def test_sg001_classifies_as_business_integrity_not_unique():
    class _Sg001Error(psycopg.errors.RaiseException):
        sqlstate = "SG001"

    exc = _Sg001Error("Mudança de eixo exige atividade_transicao")
    assert app_db.is_integrity_error(exc) is True
    assert app_db.is_unique_violation(exc) is False
    classified = app_db.classify_database_error(exc)
    assert isinstance(classified, app_db.DatabaseIntegrityError)
    assert classified.is_unique is False
    assert "Mudança de eixo exige atividade_transicao" in str(classified)
    assert classified.__cause__ is exc


def test_sg001_is_read_from_exception_sqlstate_surface():
    class _SqlstateSg001Error(Exception):
        sqlstate = "SG001"

    exc = _SqlstateSg001Error("Mudança de eixo exige atividade_transicao")
    assert app_db._pg_sqlstate(exc) == "SG001"
    assert app_db.is_integrity_error(exc) is True
    assert app_db.is_unique_violation(exc) is False


def test_sg001_is_read_from_diag_sqlstate_surface():
    exc = Exception("trigger refusal")
    exc.diag = types.SimpleNamespace(sqlstate="SG001")
    assert app_db._pg_sqlstate(exc) == "SG001"
    assert app_db.is_integrity_error(exc) is True
    assert app_db.is_unique_violation(exc) is False


def test_sg001_constant_matches_schema_authority():
    from app import pg_schema

    assert app_db._PG_BUSINESS_RULE_SQLSTATE == pg_schema.PG_BUSINESS_RULE_SQLSTATE


def test_psycopg_unique_violation_classified_through_structured_type():
    exc = psycopg.errors.UniqueViolation(
        'duplicate key value violates unique constraint "uq_cursos_codigo"'
    )
    classified = app_db.classify_database_error(exc)
    assert isinstance(classified, app_db.DatabaseIntegrityError)
    assert classified.is_unique is True


@pytest.mark.parametrize(
    "exc",
    [
        ValueError("application token SG001"),
        RuntimeError("23505 duplicate"),
        Exception("SG999 boom"),
        KeyError("SG001"),
        ValueError("duplicate key value violates unique constraint"),
        ValueError("UNIQUE constraint failed: usuarios.email"),
    ],
)
def test_arbitrary_exception_text_is_never_interpreted_as_sqlstate(exc):
    assert app_db._pg_sqlstate(exc) is None
    assert app_db.classify_database_error(exc) is None
    assert app_db.is_integrity_error(exc) is False
    assert app_db.is_unique_violation(exc) is False


def test_unknown_structured_postgres_sqlstate_remains_diagnosable():
    class _UnknownState(psycopg.errors.DatabaseError):
        sqlstate = "XX000"

    exc = _UnknownState("internal error")
    assert app_db._pg_sqlstate(exc) == "XX000"
    classified = app_db.classify_database_error(exc)
    assert isinstance(classified, app_db.DatabaseAdapterError)
    assert app_db.is_integrity_error(exc) is False
    assert app_db.is_operational_error(exc) is False


# ---------------------------------------------------------------------------
# 3. route classifier cleanup
# ---------------------------------------------------------------------------


def test_atividades_route_uses_exact_neutral_nome_conceito_identity():
    source = (REPO_ROOT / "app/views/admin/atividades.py").read_text(encoding="utf-8")
    assert 'constraint == "atividade_base.nome_conceito"' in source
    assert '"nome" in constraint' not in source
    assert "atividade_versao.grupo" not in source


def test_route_modules_do_not_learn_postgres_constraint_names():
    from app.pg_schema import PG_CONSTRAINT_MAP

    for relative in (
        "app/views/aluno.py",
        "app/views/admin/meus_dados.py",
        "app/views/admin/alunos_turmas_cursos.py",
        "app/views/admin/atividades.py",
    ):
        source = (REPO_ROOT / relative).read_text(encoding="utf-8")
        for literal in _string_literals(source):
            for name in PG_CONSTRAINT_MAP:
                assert name not in literal, (
                    f"PostgreSQL constraint name {name!r} in {relative}: {literal!r}"
                )


# ---------------------------------------------------------------------------
# 4. INSERT OR IGNORE -> ON CONFLICT DO NOTHING
# ---------------------------------------------------------------------------


def test_no_runtime_insert_or_ignore_remains_in_cleaned_modules():
    for relative in (
        "app/db.py",
        "app/db_maintenance.py",
        "app/backup_settings.py",
        "app/views/admin/dashboard.py",
    ):
        source = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert "INSERT OR IGNORE" not in source, relative


def test_app_settings_seed_is_idempotent_and_preserves_custom_values():
    from app.prod1_schema import PROD1_SCHEMA_SQL

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(PROD1_SCHEMA_SQL)
        app_db.ensure_app_settings_schema(conn)
        first = {
            row["chave"]: row["valor"]
            for row in conn.execute("SELECT chave, valor FROM configuracoes_app").fetchall()
        }
        assert first["response_goal_days"] == str(app_db.DEFAULT_RESPONSE_GOAL_DAYS)
        conn.execute(
            "UPDATE configuracoes_app SET valor='99' WHERE chave='response_goal_days'"
        )
        app_db.ensure_app_settings_schema(conn)
        preserved = conn.execute(
            "SELECT valor FROM configuracoes_app WHERE chave='response_goal_days'"
        ).fetchone()[0]
        assert preserved == "99"
        count = conn.execute("SELECT COUNT(*) FROM configuracoes_app").fetchone()[0]
        assert count == len(app_db._app_settings_defaults())
    finally:
        conn.close()


def test_app_settings_seed_postgres_emits_on_conflict_do_nothing():
    from app.pg_schema import PG_APPLICATION_TABLES

    conn = _pg_connection(*PG_APPLICATION_TABLES)
    app_db.ensure_app_settings_schema(conn)
    inserts = [sql for sql in _statements(conn) if "insert into configuracoes_app" in sql.lower()]
    assert inserts, "PostgreSQL ensure_app_settings_schema must seed the defaults"
    for sql in inserts:
        assert "ON CONFLICT DO NOTHING" in sql
    _assert_no_sqlite_only(conn)
    assert conn.commits == 0, "the ensure path must not steal commit ownership"


def test_usuario_access_seed_postgres_emits_portable_idempotent_dml():
    from app.db_maintenance import ensure_usuario_access_schema
    from app.pg_schema import PG_APPLICATION_TABLES

    conn = _pg_connection(*PG_APPLICATION_TABLES)
    ensure_usuario_access_schema(conn)
    inserts = [sql for sql in _statements(conn) if "insert into configuracoes_acesso" in sql.lower()]
    assert inserts
    for sql in inserts:
        assert "ON CONFLICT DO NOTHING" in sql
    _assert_no_sqlite_only(conn)
    assert conn.commits == 0


def test_backup_settings_seed_postgres_emits_portable_idempotent_dml(monkeypatch):
    from app import backup_settings
    from app.pg_schema import PG_APPLICATION_TABLES

    monkeypatch.setattr(
        backup_settings, "_backup_settings_defaults", lambda: {"local_backup_dir": ""}
    )
    monkeypatch.setattr(backup_settings, "_apply_backup_settings_to_app", lambda settings: None)
    conn = _pg_connection(*PG_APPLICATION_TABLES)
    backup_settings.ensure_backup_settings_schema(conn)
    inserts = [sql for sql in _statements(conn) if "insert into configuracoes_backup" in sql.lower()]
    assert inserts
    for sql in inserts:
        assert "ON CONFLICT DO NOTHING" in sql
    _assert_no_sqlite_only(conn)


# ---------------------------------------------------------------------------
# 5. current-time / date / datetime / strftime translations
# ---------------------------------------------------------------------------


def test_settings_save_uses_database_utc_text_on_both_engines(monkeypatch):
    from app import settings

    monkeypatch.setattr(settings, "ensure_app_settings_schema", lambda conn: None)

    sqlite_conn = sqlite3.connect(":memory:")
    sqlite_conn.row_factory = sqlite3.Row
    try:
        sqlite_conn.execute(
            "CREATE TABLE configuracoes_app (chave TEXT PRIMARY KEY, valor TEXT NOT NULL, atualizado_em TEXT)"
        )
        settings.save_app_settings(sqlite_conn, {"response_goal_days": "12"})
        stored = sqlite_conn.execute(
            "SELECT valor, atualizado_em FROM configuracoes_app WHERE chave='response_goal_days'"
        ).fetchone()
        assert stored["valor"] == "12"
        assert stored["atualizado_em"] is not None
    finally:
        sqlite_conn.close()

    pg = _pg_connection()
    settings.save_app_settings(pg, {"response_goal_days": "12"})
    dml = [sql for sql in _statements(pg) if "insert into configuracoes_app" in sql.lower()]
    assert dml and "sgaa_utcnow_text()" in dml[0]
    _assert_no_sqlite_only(pg)


def test_user_credential_and_token_writes_use_dialect(monkeypatch):
    from app import password_tokens, user_accounts

    pg = _pg_connection()
    user_accounts.set_usuario_credential_state(pg, 7, "personal")
    user_accounts.set_usuario_access_active(pg, 7, False)
    user_accounts.invalidate_usuario_password_tokens(pg, [7])
    password_tokens.invalidate_password_token(pg, 3)
    combined = "\n".join(_statements(pg))
    assert "sgaa_utcnow_text()" in combined
    _assert_no_sqlite_only(pg)


def test_access_onboarding_reads_engine_neutral_db_clock():
    from app import access_onboarding

    sqlite_conn = sqlite3.connect(":memory:")
    try:
        assert access_onboarding._db_now(sqlite_conn)
    finally:
        sqlite_conn.close()
    pg = _pg_connection()
    assert access_onboarding._db_now(pg) == "2026-10-05 12:00:00"


def test_requisitions_auto_indefer_uses_dialect_fragments(monkeypatch):
    from app import requisitions

    pg = _pg_connection()
    monkeypatch.setattr(
        requisitions,
        "get_response_time_settings",
        lambda conn: {"auto_indefer_devolvida": True, "return_response_days": 7},
    )
    requisitions.auto_indefer_devolvidas(pg)
    dml = [sql for sql in _statements(pg) if "update requisicoes" in sql.lower()]
    assert dml
    assert "chr(10)" in dml[0]
    assert "make_interval" in dml[0]
    assert "sgaa_utcnow_text()" in dml[0]
    _assert_no_sqlite_only(pg)


def test_date_and_datetime_and_strftime_owners_use_dialect():
    for relative, fragment in (
        ("app/views/admin/reportes.py", "date_compare("),
        ("app/views/admin/requisicoes.py", "date_compare("),
        ("app/views/admin/matrizes.py", "date_compare("),
        ("app/views/aluno.py", "date_compare("),
        ("app/views/admin/arquivos.py", "format_date_ptbr("),
        ("app/views/admin/banco_dados.py", "datetime_order("),
        ("app/admin_alerts.py", "datetime_order("),
        ("app/activity_catalog.py", "datetime_order("),
    ):
        source = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert fragment in source, f"{relative} must use {fragment}"


def test_json_extraction_owner_uses_dialect():
    source = (REPO_ROOT / "app/views/admin/dashboard.py").read_text(encoding="utf-8")
    assert "json_text(" in source
    assert "json_extract(" not in source


def test_presets_legacy_migration_uses_dialect_utc_text():
    source = (REPO_ROOT / "presets_api.py").read_text(encoding="utf-8")
    assert "current_utc_text(conn)" in source
    assert "datetime('now')" not in source


# ---------------------------------------------------------------------------
# 6. PG schema status boundary
# ---------------------------------------------------------------------------


def test_get_schema_status_postgres_uses_pg_authority_without_sqlite_introspection():
    from app.db_maintenance import get_schema_status

    conn = _pg_connection("usuarios")
    status = get_schema_status(conn)
    assert status["schema_epoch"] == "prod-1"
    assert status["schema_version"] == 12
    assert status["target_schema_version"] == 12
    assert "latest_migration" in status
    lowered = "\n".join(_statements(conn)).lower()
    assert "sqlite_master" not in lowered
    assert "pragma" not in lowered


def test_sqlite_get_schema_status_unchanged(tmp_path):
    from app import db_maintenance
    from app.prod1_schema import PROD1_SCHEMA_SQL

    db_path = tmp_path / "status.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(PROD1_SCHEMA_SQL)
        status = db_maintenance.get_schema_status(conn)
        assert status["schema_epoch"] == "prod-1"
        assert status["schema_version"] == 12
        assert status["target_schema_version"] == 12
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 7. static no-leakage gate
# ---------------------------------------------------------------------------


def _string_literals(source: str):
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value
        elif isinstance(node, ast.JoinedStr):
            for part in node.values:
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    yield part.value


def test_u5b_static_no_leakage_gate():
    scanned = 0
    for relative in _GATE_MODULES:
        if _is_exempt(relative):
            continue
        source = (REPO_ROOT / relative).read_text(encoding="utf-8")
        for literal in _string_literals(source):
            lowered = literal.lower()
            for token in _FORBIDDEN_TOKENS:
                assert token.lower() not in lowered, (
                    f"{relative}: SQLite-only token {token!r} in SQL literal: {literal!r}"
                )
        scanned += 1
    assert scanned == len(_GATE_MODULES)


def test_gate_exemptions_are_documented_and_narrow():
    for relative, reason in _GATE_EXEMPTIONS.items():
        assert (REPO_ROOT / relative).exists(), relative
        assert reason, relative
    # A cleaned module must never be silently exempted.
    assert not (set(_GATE_MODULES) & set(_GATE_EXEMPTIONS))


# ---------------------------------------------------------------------------
# 8. U5-C / U5-D hard boundaries
# ---------------------------------------------------------------------------


def test_u5c_activity_version_locking_unchanged():
    from app import activity_catalog

    db_source = (REPO_ROOT / "app/db.py").read_text(encoding="utf-8")
    assert "FOR NO KEY UPDATE" in db_source
    catalog_source = (REPO_ROOT / "app/activity_catalog.py").read_text(encoding="utf-8")
    assert "MAX(numero_versao)" in catalog_source or "get_next_numero_versao" in catalog_source


#: U5-D owners: the only dialect code allowed to spell the SQLite human-text SQL.
_U5D_OWNERS = {
    "human_text_order": ("COLLATE PTBR_NOACCENT",),
    "human_text_contains": ("INSTR(PTBR_FOLD(",),
    "ascii_nocase_order": ("COLLATE NOCASE",),
}
#: SQLite-only human-text SQL, looked up in string literals (identifiers such as
#: ``_ASCII_NOCASE_EXPRESSIONS`` are not SQL).
_U5D_RAW_TOKENS = ("COLLATE PTBR", "PTBR_FOLD(", "INSTR(", "COLLATE NOCASE")


def _literals_with_u5d_tokens(source):
    return sorted(
        {
            token
            for literal in _string_literals(source)
            for token in _U5D_RAW_TOKENS
            if token.lower() in literal.lower()
        }
    )


def _dialect_source_outside(owner_names):
    source = (REPO_ROOT / "app/sql_dialect.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    lines = source.splitlines()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in owner_names:
            for index in range(node.lineno - 1, node.end_lineno):
                lines[index] = ""
    return "\n".join(lines)


def test_u5d_ptbr_constructs_owned_by_the_dialect():
    """Pre-U5-D this pin held the boundary "U5-B did not absorb PTBR": the
    SQLite-only human-text SQL stayed in atividades.py and out of the dialect.
    U5-D moved it into dedicated sql_dialect owners; the enduring invariant is
    that it now lives ONLY in those owners' SQLite branches."""
    atividades = (REPO_ROOT / "app/views/admin/atividades.py").read_text(encoding="utf-8")
    assert "COLLATE PTBR_NOACCENT" not in atividades
    assert "COLLATE NOCASE" not in atividades
    assert "human_text_order(" in atividades and "ascii_nocase_order(" in atividades
    text_source = (REPO_ROOT / "app/text.py").read_text(encoding="utf-8")
    assert 'create_collation("PTBR_NOACCENT"' in text_source  # SQLite registration kept
    for name, tokens in _U5D_OWNERS.items():
        owner_source = inspect.getsource(getattr(sql_dialect, name))
        for token in tokens:
            assert token in owner_source, (name, token)
    remainder = _dialect_source_outside(_U5D_OWNERS)
    assert _literals_with_u5d_tokens(remainder) == [], "raw human-text SQL outside the U5-D owners"


def test_u5d_dialect_boundary_check_is_not_vacuous():
    # Negative control: without excluding the owners every token is found, so
    # the remainder check above is what proves confinement.
    whole = _dialect_source_outside(())
    assert _literals_with_u5d_tokens(whole) == sorted(_U5D_RAW_TOKENS)


def test_u5d_gate_tokens_catch_raw_human_text_sql():
    """Negative control for the strengthened gate tokens (D-4 ratchet)."""
    samples = {
        "COLLATE PTBR": "SELECT 1 ORDER BY nome COLLATE PTBR_NOACCENT",
        "PTBR_FOLD(": "SELECT PTBR_FOLD(nome)",
        "INSTR(": "WHERE instr(PTBR_FOLD(nome), ?) > 0",
        "COLLATE NOCASE": "ORDER BY grupo collate nocase",
    }
    for token, literal in samples.items():
        source = f"X = {literal!r}\n"
        flagged = [
            t for value in _string_literals(source) for t in _FORBIDDEN_TOKENS
            if t.lower() in value.lower()
        ]
        assert token in flagged, (token, flagged)
    assert not [
        t for value in _string_literals("X = 'ORDER BY LOWER(u.email)'\n")
        for t in _FORBIDDEN_TOKENS if t.lower() in value.lower()
    ]
