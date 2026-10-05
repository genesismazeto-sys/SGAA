# coding: utf-8
"""PostgreSQL-readiness Unit 5-A: current-state schema authority focus gate.

U5-A must deliver, before any runtime dialect sweep:

A. one PostgreSQL current-state schema authority for the logical prod-1/v12
   schema;
B. explicit provisioning outside request handling;
C. PostgreSQL schema metadata / contract digest authority;
D. a read-only PostgreSQL schema validator;
E. ``init_db`` on PostgreSQL changed from "not implemented" to validation only;
F. runtime ensure/introspection paths that are engine-aware and execute no
   PostgreSQL DDL.

These tests encode the contract on the *published* HEAD; they fail there because
``app.pg_schema`` and the validation boundary do not exist yet.  The SQLite
canonical schema built from ``PROD1_SCHEMA_SQL`` is the behavioural reference:
table/column/FK/index/trigger parity is derived from it, never invented here.

Cross-check note: the canonical prod-1/v12 SQLite database carries **six**
partial unique indexes (``ux_admin_arquivos_operation_key``,
``ux_admin_arquivos_provider_remote_file``, ``ux_configuracoes_presets_default``,
``ux_req_arquivos_operation_key``, ``ux_req_arquivos_provider_remote_file``,
``ux_req_email_eventos_pendente``); the unit brief's "5" is a documentation
shortfall, and this gate pins the physical canonical truth of six.
"""
import hashlib
import inspect
import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

import main  # noqa: F401  (canonical runtime; conftest redirects APP_DATABASE)
from app import db as app_db
from app import db_maintenance
from app.prod1_schema import (
    EXPECTED_TABLES,
    PROD1_SCHEMA_SQL,
    SCHEMA_EPOCH,
    SCHEMA_VERSION,
    validate_prod1_schema,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

_SQLITE_TO_PG_TYPE = {
    "TEXT": "text",
    "INTEGER": "integer",
    "REAL": "double precision",
}

#: Physical canonical truth of prod-1/v12 (six, not the brief's five).
_CANONICAL_PARTIAL_UNIQUE_INDEXES = {
    "ux_admin_arquivos_operation_key",
    "ux_admin_arquivos_provider_remote_file",
    "ux_configuracoes_presets_default",
    "ux_req_arquivos_operation_key",
    "ux_req_arquivos_provider_remote_file",
    "ux_req_email_eventos_pendente",
}

_IDENTITY_PK_COUNT = 21
_CANONICAL_APP_TABLE_COUNT = 30
_CANONICAL_EXPLICIT_INDEX_COUNT = 49
_CANONICAL_TRIGGER_COUNT = 11


def _pg():
    try:
        from app import pg_schema
    except ImportError as exc:  # pragma: no cover - RED on published HEAD
        raise AssertionError(
            "app.pg_schema PostgreSQL current-state schema authority is not "
            "implemented"
        ) from exc
    return pg_schema


def _canonical_sqlite() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(PROD1_SCHEMA_SQL)
    return conn


def _sqlite_columns(conn, table):
    rows = conn.execute(f'PRAGMA table_xinfo("{table}")').fetchall()
    return [
        (
            str(row["name"]),
            str(row["type"]),
            int(row["notnull"]),
            int(row["pk"]),
            row["dflt_value"],
        )
        for row in rows
        if int(row["hidden"]) == 0
    ]


def _sqlite_foreign_keys(conn, table):
    grouped = {}
    for row in conn.execute(f'PRAGMA foreign_key_list("{table}")').fetchall():
        entry = grouped.setdefault(
            int(row["id"]),
            {
                "columns": [],
                "references_table": str(row["table"]),
                "references_columns": [],
                "on_update": str(row["on_update"]),
                "on_delete": str(row["on_delete"]),
            },
        )
        entry["columns"].append(str(row["from"]))
        entry["references_columns"].append(str(row["to"]))
    return list(grouped.values())


def _normalize_fragment(value):
    text = re.sub(r"::(?:text|character varying|bpchar)", "", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^\((.*)\)$", r"\1", text)
    return text


def _sqlite_explicit_indexes(conn):
    indexes = {}
    for row in conn.execute(
        "SELECT name, tbl_name, sql FROM sqlite_master "
        "WHERE type='index' AND sql IS NOT NULL AND name NOT LIKE 'sqlite_%'"
    ).fetchall():
        name = str(row["name"])
        rows = conn.execute(f'PRAGMA index_xinfo("{name}")').fetchall()
        columns = [
            str(entry["name"])
            for entry in rows
            if int(entry["key"]) == 1 and entry["name"] is not None
        ]
        descending = [
            bool(int(entry["desc"]))
            for entry in rows
            if int(entry["key"]) == 1 and entry["name"] is not None
        ]
        predicate = None
        sql = str(row["sql"] or "")
        match = re.search(r"\bWHERE\b(.*)$", sql, re.IGNORECASE | re.DOTALL)
        if match:
            predicate = _normalize_fragment(match.group(1))
        unique = bool(re.match(r"^\s*CREATE\s+UNIQUE\s+INDEX", sql, re.IGNORECASE))
        indexes[name] = {
            "table": str(row["tbl_name"]),
            "unique": unique,
            "columns": columns,
            "descending": descending,
            "predicate": predicate,
        }
    return indexes


def _sqlite_triggers(conn):
    return {
        str(row["name"]): str(row["tbl_name"])
        for row in conn.execute(
            "SELECT name, tbl_name FROM sqlite_master WHERE type='trigger'"
        ).fetchall()
    }


def _sqlite_index_constraints(conn, table, origin):
    """Columns of SQLite PK or UNIQUE-constraint indexes for ``table``."""
    constraints = []
    for row in conn.execute(f'PRAGMA index_list("{table}")').fetchall():
        if str(row["origin"]) != origin:
            continue
        columns = [
            str(info["name"])
            for info in conn.execute(
                f'PRAGMA index_info("{row["name"]}")'
            ).fetchall()
        ]
        constraints.append(columns)
    return constraints


class _RecordingPgConnection:
    """Minimal psycopg-shaped connection used to trace the runtime boundary."""

    def __init__(self):
        self.statements = []
        self.closed = False

    @property
    def info(self):
        import types

        return types.SimpleNamespace(
            transaction_status=types.SimpleNamespace(name="IDLE")
        )

    def execute(self, sql, params=None):
        self.statements.append(str(sql))
        return self

    def rollback(self):
        self.statements.append("ROLLBACK")

    def commit(self):
        self.statements.append("COMMIT")

    def close(self):
        self.closed = True


# ---------------------------------------------------------------------------
# A/B. authority and census
# ---------------------------------------------------------------------------


def test_pg_authority_application_table_census_matches_v12():
    pg = _pg()
    assert set(pg.PG_APPLICATION_TABLES) == set(EXPECTED_TABLES)
    assert len(pg.PG_APPLICATION_TABLES) == _CANONICAL_APP_TABLE_COUNT
    assert pg.PG_SCHEMA_META_TABLE == "pg_schema_meta"
    assert set(pg.PG_SCHEMA_TABLES) == set(EXPECTED_TABLES) | {"pg_schema_meta"}
    assert set(pg.PG_TABLE_SPECS) == set(pg.PG_SCHEMA_TABLES)
    assert pg.PG_SCHEMA_EPOCH == SCHEMA_EPOCH
    assert pg.PG_SCHEMA_VERSION == SCHEMA_VERSION


def test_pg_authority_contains_no_sqlite_only_constructs():
    pg = _pg()
    text = pg.PG_SCHEMA_SQL_TEXT.upper()
    for token in (
        "AUTOINCREMENT",
        "PRAGMA",
        "SQLITE_MASTER",
        "EXECUTESCRIPT",
        "PTBR_NOACCENT",
        "COLLATE PTBR",
        "RAISE(ABORT",
        "RAISE (ABORT",
    ):
        assert token not in text, f"SQLite-only construct in PostgreSQL DDL: {token}"
    # PG 15 compatibility: PG16-only IS JSON syntax must not be required and the
    # SQLite JSON functions must not leak into the authority.
    assert " IS JSON" not in text
    assert "JSON_VALID(" not in text
    assert "JSON_TYPE(" not in text
    assert "SGAA_JSON_IS_VALID" in text
    assert "SGAA_JSON_IS_OBJECT" in text


def test_datetime_text_valid_is_stable_because_timestamp_input_is_stable():
    """``normalized::timestamp`` input is STABLE (DateStyle-dependent).

    This helper must never be declared IMMUTABLE again: PostgreSQL timestamp
    input is STABLE, and an IMMUTABLE declaration would let the planner
    constant-fold the check under a changing DateStyle.  STABLE is the
    least-permissive truthful volatility; the helper reads no database state
    and is not VOLATILE.
    """
    pg = _pg()
    definition = next(
        statement
        for statement in pg.PG_SCHEMA_STATEMENTS
        if f"CREATE FUNCTION {pg.PG_DATETIME_VALID_FUNCTION}" in statement
    )
    assert "normalized::timestamp" in definition
    volatility = re.search(
        r"RETURNS boolean\s+LANGUAGE plpgsql\s+([A-Z]+)", definition
    )
    assert volatility, definition
    assert volatility.group(1) == "STABLE"
    assert "IMMUTABLE" not in definition


def test_all_30_tables_and_columns_match_canonical_sqlite_v12():
    conn = _canonical_sqlite()
    pg = _pg()
    for table in pg.PG_APPLICATION_TABLES:
        sqlite_columns = _sqlite_columns(conn, table)
        spec_columns = pg.PG_TABLE_SPECS[table]["columns"]
        assert [column["name"] for column in spec_columns] == [
            entry[0] for entry in sqlite_columns
        ], f"column order/name mismatch for {table}"
        for spec, (name, sqlite_type, notnull, pk, default) in zip(
            spec_columns, sqlite_columns
        ):
            assert spec["type"] == _SQLITE_TO_PG_TYPE[sqlite_type.upper()], (
                f"type mismatch for {table}.{name}: {spec['type']}"
            )
            # PostgreSQL PRIMARY KEY forces NOT NULL; SQLite only reports the
            # explicit NOT NULL flag, so a primary-key column is not-null in
            # the logical contract of both engines.
            assert bool(spec["not_null"]) == (bool(notnull) or bool(pk)), (
                f"nullability mismatch for {table}.{name}"
            )
            if spec.get("identity"):
                assert spec["identity"] == "BY DEFAULT"
                assert default is None
                continue
            if default is None:
                assert spec["default"] is None, f"unexpected default for {table}.{name}"
                continue
            if "datetime(" in str(default) or str(default).upper() == "CURRENT_TIMESTAMP":
                assert spec["default"] == "sgaa_utcnow_text()", (
                    f"timestamp default for {table}.{name} must use sgaa_utcnow_text()"
                )
            else:
                assert spec["default"] == str(default), (
                    f"default mismatch for {table}.{name}: {spec['default']!r}"
                )


# ---------------------------------------------------------------------------
# C/D. identity and explicit stable names
# ---------------------------------------------------------------------------


def test_identity_pks_are_by_default_not_always():
    pg = _pg()
    identity_columns = [
        (table, column["name"], column["identity"])
        for table, spec in pg.PG_TABLE_SPECS.items()
        for column in spec["columns"]
        if column.get("identity")
    ]
    assert len(identity_columns) == _IDENTITY_PK_COUNT
    assert all(kind == "BY DEFAULT" for _, _, kind in identity_columns)
    text = pg.PG_SCHEMA_SQL_TEXT
    assert text.count("GENERATED BY DEFAULT AS IDENTITY") == _IDENTITY_PK_COUNT
    assert "GENERATED ALWAYS" not in text.upper()


def test_every_constraint_has_an_explicit_stable_name():
    pg = _pg()
    names = []
    for table, spec in pg.PG_TABLE_SPECS.items():
        pk = spec["primary_key"]
        assert pk["name"] == f"{table}_pkey"
        names.append(pk["name"])
        for unique in spec["uniques"]:
            assert unique["name"].startswith("uq_"), unique["name"]
            names.append(unique["name"])
        for check in spec["checks"]:
            assert check["name"].startswith("ck_"), check["name"]
            names.append(check["name"])
        for foreign_key in spec["foreign_keys"]:
            assert foreign_key["name"].startswith("fk_"), foreign_key["name"]
            names.append(foreign_key["name"])
    assert len(names) == len(set(names)), "duplicated PostgreSQL constraint name"
    for name in names:
        assert len(name) <= 63, f"constraint name exceeds NAMEDATALEN: {name}"
        assert re.search(rf"\b{re.escape(name)}\b", pg.PG_SCHEMA_SQL_TEXT), name
    assert set(pg.PG_CONSTRAINT_MAP) == set(names)
    for name, entry in pg.PG_CONSTRAINT_MAP.items():
        assert entry["kind"] in {
            "primary_key",
            "unique",
            "check",
            "foreign_key",
        }, name
        assert entry["table"] in pg.PG_TABLE_SPECS, name


def test_existing_explicit_index_names_are_preserved():
    conn = _canonical_sqlite()
    sqlite_indexes = _sqlite_explicit_indexes(conn)
    pg = _pg()
    assert len(sqlite_indexes) == _CANONICAL_EXPLICIT_INDEX_COUNT
    assert set(pg.PG_EXPLICIT_INDEXES) == set(sqlite_indexes)
    for name, spec in pg.PG_EXPLICIT_INDEXES.items():
        assert name.startswith(("idx_", "ux_")), name
        expected = sqlite_indexes[name]
        assert spec["table"] == expected["table"], name
        assert list(spec["columns"]) == expected["columns"], name
        assert list(spec.get("descending", [])) == expected["descending"], name
        assert bool(spec["unique"]) == expected["unique"], name
        actual_predicate = (
            _normalize_fragment(spec["predicate"]) if spec["predicate"] else None
        )
        assert actual_predicate == expected["predicate"], name


def test_partial_unique_indexes_match_canonical_sqlite_v12():
    pg = _pg()
    partial = {
        name: spec
        for name, spec in pg.PG_EXPLICIT_INDEXES.items()
        if spec["predicate"]
    }
    assert set(partial) == _CANONICAL_PARTIAL_UNIQUE_INDEXES
    for name, spec in partial.items():
        assert spec["unique"] is True, name
        assert f"CREATE UNIQUE INDEX {name}" in pg.PG_SCHEMA_SQL_TEXT, name


def test_all_material_fk_actions_match_canonical_sqlite_v12():
    conn = _canonical_sqlite()
    pg = _pg()
    for table in pg.PG_APPLICATION_TABLES:
        sqlite_fks = _sqlite_foreign_keys(conn, table)
        spec_fks = pg.PG_TABLE_SPECS[table]["foreign_keys"]
        assert len(spec_fks) == len(sqlite_fks), f"foreign-key count for {table}"
        for spec in spec_fks:
            matches = [
                fk
                for fk in sqlite_fks
                if fk["columns"] == list(spec["columns"])
                and fk["references_table"] == spec["references_table"]
            ]
            assert matches, f"no SQLite foreign key matches {spec['name']}"
            sqlite_fk = matches[0]
            assert list(spec["references_columns"]) == sqlite_fk["references_columns"]
            assert spec["on_delete"] == sqlite_fk["on_delete"], spec["name"]
            assert spec["on_update"] == sqlite_fk["on_update"], spec["name"]


def test_all_material_uniques_and_pks_match_canonical_sqlite_v12():
    conn = _canonical_sqlite()
    pg = _pg()
    for table in pg.PG_APPLICATION_TABLES:
        spec = pg.PG_TABLE_SPECS[table]
        sqlite_pk = [
            str(row["name"])
            for row in sorted(
                (
                    row
                    for row in conn.execute(
                        f'PRAGMA table_xinfo("{table}")'
                    ).fetchall()
                    if int(row["pk"]) > 0
                ),
                key=lambda row: int(row["pk"]),
            )
        ]
        assert list(spec["primary_key"]["columns"]) == sqlite_pk, (
            f"primary key mismatch for {table}"
        )
        sqlite_uniques = sorted(
            _sqlite_index_constraints(conn, table, "u")
        )
        spec_uniques = sorted(
            [list(unique["columns"]) for unique in spec["uniques"]]
        )
        assert spec_uniques == sqlite_uniques, (
            f"unique constraint mismatch for {table}: "
            f"{spec_uniques!r} != {sqlite_uniques!r}"
        )


def test_composite_fk_declared_for_matrix_items():
    pg = _pg()
    composite = [
        fk
        for fk in pg.PG_TABLE_SPECS["matriz_atividade_versao_item"]["foreign_keys"]
        if len(fk["columns"]) == 2
    ]
    assert len(composite) == 1
    fk = composite[0]
    assert tuple(fk["columns"]) == ("atividade_versao_id", "atividade_base_id")
    assert fk["references_table"] == "atividade_versao"
    assert tuple(fk["references_columns"]) == ("id", "atividade_base_id")


def test_all_eleven_triggers_are_translated_with_contract():
    conn = _canonical_sqlite()
    sqlite_triggers = _sqlite_triggers(conn)
    assert len(sqlite_triggers) == _CANONICAL_TRIGGER_COUNT
    pg = _pg()
    assert len(pg.PG_TRIGGERS) == _CANONICAL_TRIGGER_COUNT
    assert {trigger["name"] for trigger in pg.PG_TRIGGERS} == set(sqlite_triggers)
    for trigger in pg.PG_TRIGGERS:
        assert trigger["table"] == sqlite_triggers[trigger["name"]]
        assert trigger["timing"] == "BEFORE"
        assert set(trigger["events"]) <= {"INSERT", "UPDATE"}
        assert trigger["function"] in pg.PG_SCHEMA_SQL_TEXT
        assert f"CREATE TRIGGER {trigger['name']}" in pg.PG_SCHEMA_SQL_TEXT
        assert f"EXECUTE FUNCTION {trigger['function']}" in pg.PG_SCHEMA_SQL_TEXT
    assert "ERRCODE" in pg.PG_SCHEMA_SQL_TEXT
    assert pg.PG_BUSINESS_RULE_SQLSTATE


# ---------------------------------------------------------------------------
# C. metadata / digest
# ---------------------------------------------------------------------------


def test_pg_schema_meta_uses_stable_singleton_identity():
    pg = _pg()
    spec = pg.PG_TABLE_SPECS["pg_schema_meta"]
    assert list(spec["primary_key"]["columns"]) == ["id"]
    column_names = [column["name"] for column in spec["columns"]]
    assert "contract_sha256" in column_names
    assert all(
        "contract_sha256" not in unique["columns"] for unique in spec["uniques"]
    )
    assert pg.PG_SCHEMA_META_ID == 1
    assert "PRIMARY KEY (id)" in pg.PG_SCHEMA_SQL_TEXT
    singleton_checks = [check for check in spec["checks"] if check["name"] == "ck_pg_schema_meta_singleton"]
    assert singleton_checks
    assert "id = 1" in " ".join(check["expression"] for check in singleton_checks)


def test_contract_digest_is_deterministic_and_application_owned():
    pg = _pg()
    first = pg.pg_contract_sha256()
    second = pg.pg_contract_sha256()
    assert first == second == pg.PG_CONTRACT_SHA256
    assert re.fullmatch(r"[0-9a-f]{64}", first)
    payload = json.dumps(
        pg.pg_contract_payload(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    assert hashlib.sha256(payload.encode("utf-8")).hexdigest() == first
    assert "pg_catalog" not in payload
    assert "pg_get_constraintdef" not in payload


def test_pg_schema_migrations_rows_are_documented_baseline_metadata():
    pg = _pg()
    assert pg.PG_SCHEMA_MIGRATIONS_SEMANTICS == "baseline_metadata"
    assert "baseline metadata" in (pg.__doc__ or "").lower()
    conn = _canonical_sqlite()
    sqlite_rows = conn.execute(
        "SELECT version, name, details_json FROM schema_migrations ORDER BY version"
    ).fetchall()
    seed = [tuple(row) for row in pg.PG_SCHEMA_MIGRATIONS_SEED]
    assert [(version, name) for version, name, _ in seed] == [
        (int(row["version"]), str(row["name"])) for row in sqlite_rows
    ]
    assert [details for _, _, details in seed] == [
        row["details_json"] for row in sqlite_rows
    ]


# ---------------------------------------------------------------------------
# E/F. runtime boundary
# ---------------------------------------------------------------------------


def test_init_db_postgres_path_validates_and_executes_no_sqlite_work(monkeypatch):
    pg = _pg()
    validated = []

    def fake_validate(connection):
        validated.append(connection)
        return {"schema_epoch": pg.PG_SCHEMA_EPOCH, "schema_version": pg.PG_SCHEMA_VERSION}

    monkeypatch.setattr(pg, "validate_pg_schema", fake_validate)
    monkeypatch.setattr(
        app_db, "DATABASE_URL", "postgresql://sgaa:sgaa@127.0.0.1:5432/sgaa"
    )
    connection = _RecordingPgConnection()
    monkeypatch.setattr(app_db, "get_db_connection", lambda: connection)

    def forbidden(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("SQLite schema work must not run on PostgreSQL")

    monkeypatch.setattr(app_db, "apply_early_schema_migrations", forbidden)
    monkeypatch.setattr(app_db, "apply_schema_migrations", forbidden)

    import app.prod1_schema as prod1_schema

    monkeypatch.setattr(prod1_schema, "bootstrap_prod1_schema", forbidden)

    app_db.init_db()
    assert validated == [connection]
    for statement in connection.statements:
        assert not re.search(r"\b(CREATE|ALTER|DROP)\b", statement, re.IGNORECASE), statement
        assert "PRAGMA" not in statement.upper(), statement
        assert "sqlite_master" not in statement, statement
    assert "ROLLBACK" in connection.statements


def test_provisioning_is_explicit_cli_only_and_not_in_runtime_paths():
    pg = _pg()
    assert "__main__" in inspect.getsource(pg)
    assert hasattr(pg, "main")
    init_source = inspect.getsource(app_db.init_db)
    assert "validate_pg_schema" in init_source
    assert "provision_pg_schema" not in init_source
    assert "provision_database" not in init_source
    assert "bootstrap_prod1_schema" not in init_source
    for module in (app_db, db_maintenance):
        source = inspect.getsource(module)
        assert "pg_schema import provision" not in source
        assert "pg_schema.provision" not in source


def test_runtime_ensure_functions_are_engine_aware_and_never_provision():
    pg = _pg()
    from presets_api import ensure_presets_schema

    functions = (
        app_db.ensure_app_settings_schema,
        app_db.ensure_cloud_backup_schema,
        app_db.ensure_turmas_matriz_schema,
        db_maintenance._require_prod1_tables,
        db_maintenance.ensure_usuario_access_schema,
        db_maintenance.ensure_atividade_versioning_schema,
        ensure_presets_schema,
    )
    for function in functions:
        source = inspect.getsource(function)
        assert (
            "postgres" in source.lower()
            or "database_engine" in source
            or "require_pg_tables" in source
        ), f"{function.__name__} is not engine-aware"
        assert "provision_pg_schema" not in source, f"{function.__name__} can provision"
        assert "provision_database" not in source, f"{function.__name__} can provision"


def test_sqlite_runtime_import_does_not_load_pg_schema():
    code = (
        "import sys; import app.db; "
        "assert 'app.pg_schema' not in sys.modules, 'pg_schema imported eagerly'; "
        "print('SQLITE_IMPORT_OK')"
    )
    completed = subprocess.run(
        [sys.executable, "-B", "-c", code],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    assert "SQLITE_IMPORT_OK" in completed.stdout


def test_pg_schema_authority_has_no_flask_dependency():
    pg = _pg()
    source = inspect.getsource(pg)
    assert "import flask" not in source
    assert "from flask" not in source


# ---------------------------------------------------------------------------
# N. SQLite remains the unchanged default authority
# ---------------------------------------------------------------------------


def test_sqlite_v12_authority_is_unchanged():
    conn = _canonical_sqlite()
    status = validate_prod1_schema(conn)
    assert status["schema_epoch"] == SCHEMA_EPOCH
    assert status["schema_version"] == SCHEMA_VERSION == 12
    assert len(_sqlite_explicit_indexes(conn)) == _CANONICAL_EXPLICIT_INDEX_COUNT
    assert len(_sqlite_triggers(conn)) == _CANONICAL_TRIGGER_COUNT
    tables = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    }
    assert tables == set(EXPECTED_TABLES)
