# coding: utf-8
"""UT-SCHEMA-PRESETS -- single DDL authority for `configuracoes_presets`.

`configuracoes_presets` is a prod-1 physical-contract table, so its DDL text is
load-bearing: `validate_prod1_schema` compares the normalized `sqlite_master`
SQL.  Historically two independent `CREATE TABLE` statements existed -- the
canonical one in `PROD1_SCHEMA_SQL` and a lazy one in
`presets_api.ensure_presets_schema` -- and a database created through the lazy
path was rejected with `prod-1 physical schema contract mismatch`.

These tests pin the single-authority architecture: one canonical statement,
consumed by both the bootstrap path and the lazy path.
"""
import re
import sqlite3
from pathlib import Path

import pytest

import presets_api
from app.prod1_presets_ddl import CONFIGURACOES_PRESETS_TABLE_SQL
from app.prod1_schema import (
    PROD1_SCHEMA_SQL,
    SCHEMA_VERSION,
    Prod1SchemaError,
    canonical_prod1_object_sql,
    validate_prod1_schema,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
AUTHORITY_MODULE = REPO_ROOT / "app" / "prod1_presets_ddl.py"
PRESETS_TABLE_DDL_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"'`\[]?configuracoes_presets\b",
    re.IGNORECASE,
)


def _production_sources():
    """First-party Python modules only -- no tests, fixtures or generated content."""
    sources = [REPO_ROOT / "main.py", REPO_ROOT / "presets_api.py"]
    sources.extend(
        path
        for path in sorted((REPO_ROOT / "app").rglob("*.py"))
        if "__pycache__" not in path.parts
    )
    return sources


def _bootstrapped_database(path):
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(PROD1_SCHEMA_SQL)
    conn.commit()
    return conn


def _stored_presets_ddl(conn):
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
        (presets_api.PRESETS_TABLE,),
    ).fetchone()
    return row[0] if row else None


# --------------------------------------------------------------------------
# A. exactly one production DDL authority
# --------------------------------------------------------------------------


def test_configuracoes_presets_has_exactly_one_production_ddl_authority():
    owners = {
        path.relative_to(REPO_ROOT).as_posix()
        for path in _production_sources()
        if PRESETS_TABLE_DDL_RE.search(path.read_text(encoding="utf-8"))
    }
    assert owners == {AUTHORITY_MODULE.relative_to(REPO_ROOT).as_posix()}


def test_presets_api_holds_no_literal_create_table_authority():
    """Regression guard: the lazy path must never regrow its own DDL."""
    source = (REPO_ROOT / "presets_api.py").read_text(encoding="utf-8")

    assert not PRESETS_TABLE_DDL_RE.search(source)
    assert "CONFIGURACOES_PRESETS_TABLE_SQL" in source


def test_prod1_schema_consumes_the_presets_authority_constant():
    """Bootstrap must interpolate the constant, not restate the table."""
    source = (REPO_ROOT / "app" / "prod1_schema.py").read_text(encoding="utf-8")

    assert not PRESETS_TABLE_DDL_RE.search(source)
    assert "__CONFIGURACOES_PRESETS_TABLE__" in source
    assert CONFIGURACOES_PRESETS_TABLE_SQL in PROD1_SCHEMA_SQL


def test_authority_constant_matches_the_text_sqlite_persists():
    """No trailing semicolon: the constant is exactly the stored DDL text."""
    assert not CONFIGURACOES_PRESETS_TABLE_SQL.rstrip().endswith(";")
    assert canonical_prod1_object_sql(
        "table", presets_api.PRESETS_TABLE
    ) == CONFIGURACOES_PRESETS_TABLE_SQL


# --------------------------------------------------------------------------
# B. full bootstrap creates the canonical table
# --------------------------------------------------------------------------


def test_bootstrap_creates_canonical_presets_table(tmp_path):
    conn = _bootstrapped_database(tmp_path / "bootstrap.db")
    try:
        assert _stored_presets_ddl(conn) == CONFIGURACOES_PRESETS_TABLE_SQL
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        validate_prod1_schema(conn)
    finally:
        conn.close()


# --------------------------------------------------------------------------
# C. existing table -> no-op
# --------------------------------------------------------------------------


def test_ensure_presets_schema_is_a_no_op_on_an_existing_canonical_table(tmp_path):
    conn = _bootstrapped_database(tmp_path / "existing.db")
    try:
        conn.execute(
            "INSERT INTO configuracoes_presets(tipo,preset_id,titulo,texto)"
            " VALUES('respostas',1,'Preservado','Texto preservado')"
        )
        conn.commit()
        rows_before = conn.execute(
            "SELECT tipo,preset_id,titulo,texto,atualizado_em FROM configuracoes_presets"
        ).fetchall()
        ddl_before = _stored_presets_ddl(conn)

        presets_api.ensure_presets_schema(conn)

        assert (
            conn.execute(
                "SELECT tipo,preset_id,titulo,texto,atualizado_em FROM configuracoes_presets"
            ).fetchall()
            == rows_before
        )
        assert _stored_presets_ddl(conn) == ddl_before
        validate_prod1_schema(conn)
    finally:
        conn.close()


def test_ensure_presets_schema_never_rewrites_an_existing_table(tmp_path):
    """A no-op must issue no DDL at all -- no DROP, rebuild or normalization."""
    conn = _bootstrapped_database(tmp_path / "audit.db")
    executed = []
    try:
        conn.set_trace_callback(executed.append)
        presets_api.ensure_presets_schema(conn)
        conn.set_trace_callback(None)
    finally:
        conn.close()

    assert len(executed) == 1
    assert executed[0].lstrip().upper().startswith("SELECT")
    joined = " ".join(executed).upper()
    for forbidden in ("CREATE", "DROP", "DELETE", "ALTER", "INSERT", "UPDATE"):
        assert forbidden not in joined


# --------------------------------------------------------------------------
# D + E. absent table -> canonical recreate accepted by the real validator
# --------------------------------------------------------------------------


def test_ensure_presets_schema_recreates_the_canonical_physical_definition(tmp_path):
    conn = _bootstrapped_database(tmp_path / "absent.db")
    try:
        canonical_ddl = _stored_presets_ddl(conn)
        conn.execute("DROP TABLE configuracoes_presets")
        conn.commit()
        assert _stored_presets_ddl(conn) is None
        with pytest.raises(Prod1SchemaError):
            validate_prod1_schema(conn)

        presets_api.ensure_presets_schema(conn)
        conn.commit()

        assert _stored_presets_ddl(conn) == canonical_ddl
        validate_prod1_schema(conn)
    finally:
        conn.close()


def test_recreated_presets_table_keeps_canonical_constraints(tmp_path):
    """Structural proof: CHECK, defaults and composite PK survive the recreate."""
    conn = _bootstrapped_database(tmp_path / "constraints.db")
    try:
        conn.execute("DROP TABLE configuracoes_presets")
        conn.commit()
        presets_api.ensure_presets_schema(conn)
        conn.commit()

        columns = [
            (row[1], row[2], row[3], row[5])
            for row in conn.execute("PRAGMA table_info(configuracoes_presets)")
        ]
        assert columns == [
            ("tipo", "TEXT", 1, 1),
            ("preset_id", "INTEGER", 1, 2),
            ("titulo", "TEXT", 1, 0),
            ("texto", "TEXT", 1, 0),
            ("atualizado_em", "TEXT", 1, 0),
            # prod-1/v7: outbound subject + explicit default designation.
            ("assunto", "TEXT", 1, 0),
            ("is_default", "INTEGER", 1, 0),
        ]

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO configuracoes_presets(tipo,preset_id,titulo)"
                " VALUES('invalido',1,'t')"
            )
        conn.execute(
            "INSERT INTO configuracoes_presets(tipo,preset_id,titulo) VALUES('emails',1,'t')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO configuracoes_presets(tipo,preset_id,titulo)"
                " VALUES('emails',1,'duplicado')"
            )
        assert conn.execute(
            "SELECT texto, atualizado_em IS NOT NULL FROM configuracoes_presets"
        ).fetchone() == ("", 1)
    finally:
        conn.close()
