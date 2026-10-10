# coding: utf-8
"""prod-1/v13 (STORAGE S1): database-backed image side tables.

A. SQLite authority: a fresh bootstrap is v13 with the three tables; v12 ->
   v13 is purely additive (every row, id and AUTOINCREMENT counter kept), is
   idempotent through the dispatcher, rolls back completely on failure and is
   reversible to the frozen v12 digest.
B. one constraint vector decides acceptance for every image table; SQLite
   (always) and PostgreSQL (E-PG1, ``SGAA_PG_TEST_URL``) must give the same
   verdict for each candidate row.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
from urllib.parse import urlsplit, urlunsplit

import pytest

from app import pg_schema
from app.prod1_images_ddl import IMAGES_V13_TABLES, IMAGES_V13_TABLE_SQL
from app.prod1_images_v13 import _V13_DETAILS_JSON, migrate_prod1_v12_to_v13
from app.prod1_schema import (
    EXPECTED_TABLES,
    IMAGE_STORAGE_MARKER,
    PROD1_SCHEMA_SQL,
    SCHEMA_VERSION,
    Prod1SchemaError,
    _PROD1_V12_SIGNATURE_SHA256,
    _PROD1_V13_SIGNATURE_SHA256,
    _normalize_schema_sql,
    _physical_schema_digest,
    _validate_prod1_v12_schema,
    bootstrap_prod1_schema,
    validate_prod1_schema,
)
from tests.prod1_v13_support import revert_prod1_v13_to_v12
from tests.prod1_v14_support import revert_prod1_v14_to_v13
from tests.prod1_v14_support import revert_prod1_v14_to_v13
from tests.prod1_v14_support import revert_prod1_v14_to_v13

PG_URL = os.environ.get("SGAA_PG_TEST_URL", "").strip()
RUN_PREFIX = f"sgaa_s1img_test_{secrets.token_hex(4)}_"


def _head() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    bootstrap_prod1_schema(conn)
    return conn


def _v12_with_rows() -> sqlite3.Connection:
    conn = _head()
    revert_prod1_v13_to_v12(conn)
    _validate_prod1_v12_schema(conn)
    conn.execute(
        "INSERT INTO usuarios(id,nome,email,senha,tipo,nivel_acesso,foto_perfil)"
        " VALUES(5,'Admin','a@x.test','x','admin','admin_total','avatars/usuario_5/a.png')"
    )
    conn.execute("INSERT INTO usuarios(id,nome,email,senha,tipo,nivel_acesso) VALUES(8,'Al','b@x.test','x','aluno','usuario')")
    conn.execute(
        "INSERT INTO alunos(id,usuario_id,nome,matricula,foto_perfil) VALUES(3,8,'Al','M3','aluno_3 - al/perfil/p.jpg')"
    )
    conn.execute(
        "INSERT INTO reportes(id,aluno_id,titulo,descricao,screenshot_filename)"
        " VALUES(7,3,'t','d','aluno_3 - al/reportes/s.png')"
    )
    conn.execute("INSERT INTO reportes(id,aluno_id,titulo,descricao) VALUES(9,3,'t2','d2')")
    conn.execute("DELETE FROM reportes WHERE id=9")  # leaves an AUTOINCREMENT gap
    conn.commit()
    return conn


def _dump(conn) -> dict:
    tables = [
        name for (name,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        if name not in IMAGES_V13_TABLES and name != "schema_migrations"
    ]
    out = {t: [tuple(r) for r in conn.execute(f'SELECT * FROM "{t}" ORDER BY rowid')] for t in tables}
    out["sqlite_sequence"] = sorted(tuple(r) for r in conn.execute("SELECT name,seq FROM sqlite_sequence"))
    return out


# --- A. SQLite authority -----------------------------------------------------------


def test_fresh_bootstrap_is_v13_with_exactly_the_three_image_tables():
    conn = _head()
    status = validate_prod1_schema(conn)
    # v14 only adds the canonical-storage objects and v15 only the canonical
    # document custody; without them the head is v13 exactly.
    assert SCHEMA_VERSION == status["schema_version"] == 16
    assert status["table_count"] == 38
    assert set(IMAGES_V13_TABLES) <= EXPECTED_TABLES
    shape = _head()
    revert_prod1_v14_to_v13(shape)
    assert _physical_schema_digest(shape) == _PROD1_V13_SIGNATURE_SHA256
    for table, sql in zip(IMAGES_V13_TABLES, IMAGES_V13_TABLE_SQL):
        stored = conn.execute("SELECT sql FROM sqlite_master WHERE name=?", (table,)).fetchone()[0]
        assert _normalize_schema_sql(stored) == _normalize_schema_sql(sql)
    assert conn.execute(
        "SELECT version,name,details_json FROM schema_migrations WHERE version=13"
    ).fetchone() == (13, IMAGE_STORAGE_MARKER, _V13_DETAILS_JSON)
    assert _V13_DETAILS_JSON in PROD1_SCHEMA_SQL
    # Additive: the legacy path columns are still there.
    for table, column in (("usuarios", "foto_perfil"), ("alunos", "foto_perfil"), ("reportes", "screenshot_filename")):
        assert column in {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def test_v12_to_v13_is_additive_and_preserves_every_row_and_counter():
    conn = _v12_with_rows()
    before = _dump(conn)
    result = migrate_prod1_v12_to_v13(conn)
    assert result["schema_version"] == 13 and result["image_storage"] == "database"
    assert _physical_schema_digest(conn) == _PROD1_V13_SIGNATURE_SHA256
    assert _dump(conn) == before  # legacy references included: no backfill
    for table in IMAGES_V13_TABLES:
        assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    new_id = conn.execute("INSERT INTO reportes(aluno_id,titulo,descricao) VALUES(3,'n','n') RETURNING id").fetchone()[0]
    assert new_id == 10  # the deleted id 9 is not reused


def test_v13_migration_is_idempotent_through_the_dispatcher_and_refuses_non_v12():
    conn = _v12_with_rows()
    first = bootstrap_prod1_schema(conn)
    snapshot = _dump(conn)
    second = bootstrap_prod1_schema(conn)
    assert first["schema_version"] == second["schema_version"] == 16
    assert _dump(conn) == snapshot
    with pytest.raises(Prod1SchemaError, match="prod-1/v12"):
        migrate_prod1_v12_to_v13(conn)


def test_a_failed_v13_migration_leaves_v12_untouched(monkeypatch):
    conn = _v12_with_rows()
    before = _dump(conn)
    import app.prod1_schema as prod1_schema

    def _boom(_conn):
        raise Prod1SchemaError("injected failure after the image tables were created")

    monkeypatch.setattr(prod1_schema, "_validate_prod1_v13_schema", _boom)
    with pytest.raises(Prod1SchemaError, match="injected"):
        migrate_prod1_v12_to_v13(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 12
    assert _physical_schema_digest(conn) == _PROD1_V12_SIGNATURE_SHA256
    assert _dump(conn) == before


def test_v13_is_reversible_to_the_frozen_v12_contract():
    conn = _v12_with_rows()
    before = _dump(conn)
    migrate_prod1_v12_to_v13(conn)
    revert_prod1_v13_to_v12(conn)
    _validate_prod1_v12_schema(conn)
    assert _dump(conn) == before


def test_owner_delete_cascades_and_one_row_per_owner():
    conn = _head()
    conn.execute("INSERT INTO usuarios(id,nome,email,senha,tipo) VALUES(1,'A','a@x.test','x','admin')")
    row = _row(b"abc")
    _insert(conn, "usuarios_foto", 1, row)
    with pytest.raises(sqlite3.IntegrityError):
        _insert(conn, "usuarios_foto", 1, row)
    conn.execute("DELETE FROM usuarios WHERE id=1")
    assert conn.execute("SELECT count(*) FROM usuarios_foto").fetchone()[0] == 0


# --- B. one constraint vector, both engines --------------------------------------------


def _row(content=b"0123456789", **overrides):
    row = {
        "mime_type": "image/png",
        "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "width": 10,
        "height": 10,
        "conteudo": content,
    }
    row.update(overrides)
    return row


_OWNER_COLUMN = {"usuarios_foto": "usuario_id", "alunos_foto": "aluno_id", "reportes_captura": "reporte_id"}
_BIG_PROFILE = b"p" * (1024 * 1024 + 1)
_BIG_SHOT = b"s" * (4 * 1024 * 1024 + 1)

#: (table, row, accepted)
CANDIDATES = [
    *[(t, _row(), True) for t in IMAGES_V13_TABLES],
    *[(t, _row(mime_type="image/jpeg"), True) for t in IMAGES_V13_TABLES],
    ("usuarios_foto", _row(mime_type="image/webp"), False),
    ("alunos_foto", _row(mime_type="image/webp"), False),
    ("reportes_captura", _row(mime_type="image/webp"), True),
    *[(t, _row(mime_type="image/gif"), False) for t in IMAGES_V13_TABLES],
    *[(t, _row(size_bytes=11), False) for t in IMAGES_V13_TABLES],
    *[(t, _row(b"", size_bytes=0), False) for t in IMAGES_V13_TABLES],
    *[(t, _row(sha256=_row()["sha256"].upper()), False) for t in IMAGES_V13_TABLES],
    *[(t, _row(sha256="a" * 63), False) for t in IMAGES_V13_TABLES],
    *[(t, _row(sha256="g" * 64), False) for t in IMAGES_V13_TABLES],
    *[(t, _row(width=0), False) for t in IMAGES_V13_TABLES],
    *[(t, _row(height=-1), False) for t in IMAGES_V13_TABLES],
    ("usuarios_foto", _row(width=513), False),
    ("alunos_foto", _row(height=513), False),
    ("usuarios_foto", _row(width=512, height=512), True),
    ("reportes_captura", _row(width=1920, height=20000), True),
    ("reportes_captura", _row(width=20001), False),
    ("usuarios_foto", _row(_BIG_PROFILE), False),
    ("alunos_foto", _row(b"p" * (1024 * 1024)), True),
    ("reportes_captura", _row(_BIG_PROFILE), True),
    ("reportes_captura", _row(_BIG_SHOT), False),
]


def _insert(conn, table, owner_id, row, *, marker="?"):
    columns = [_OWNER_COLUMN[table], *row]
    values = [owner_id, *row.values()]
    conn.execute(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join([marker] * len(columns))})",
        values,
    )


def _sqlite_verdicts():
    conn = _head()
    conn.execute("INSERT INTO usuarios(id,nome,email,senha,tipo) VALUES(1,'A','a@x.test','x','admin')")
    conn.execute("INSERT INTO alunos(id,usuario_id,nome,matricula) VALUES(1,1,'A','M1')")
    conn.execute("INSERT INTO reportes(id,aluno_id,titulo,descricao) VALUES(1,1,'t','d')")
    verdicts = []
    for table, row, _expected in CANDIDATES:
        conn.execute("SAVEPOINT candidate")
        try:
            _insert(conn, table, 1, row)
            verdicts.append(True)
        except sqlite3.IntegrityError:
            verdicts.append(False)
        conn.execute("ROLLBACK TO candidate")
        conn.execute("RELEASE candidate")
    return verdicts


def test_sqlite_constraints_match_the_contract_vector():
    assert _sqlite_verdicts() == [expected for _t, _r, expected in CANDIDATES]


def test_sqlite_refuses_text_content_even_with_matching_length():
    conn = _head()
    conn.execute("INSERT INTO usuarios(id,nome,email,senha,tipo) VALUES(1,'A','a@x.test','x','admin')")
    with pytest.raises(sqlite3.IntegrityError):
        _insert(conn, "usuarios_foto", 1, _row(conteudo="0123456789"))
    with pytest.raises(sqlite3.IntegrityError):
        _insert(conn, "usuarios_foto", 99, _row())  # no such owner


def test_pg_contract_declares_the_same_tables_and_bytea():
    for table in IMAGES_V13_TABLES:
        spec = pg_schema.PG_TABLE_SPECS[table]
        assert [c["name"] for c in spec["columns"]] == [
            _OWNER_COLUMN[table], "mime_type", "size_bytes", "sha256", "width", "height", "conteudo", "atualizado_em",
        ]
        assert {c["name"]: c["type"] for c in spec["columns"]}["conteudo"] == "bytea"
        assert spec["primary_key"]["columns"] == [_OWNER_COLUMN[table]]
        [fk] = spec["foreign_keys"]
        assert (fk["on_delete"], fk["on_update"], fk["references_columns"]) == ("CASCADE", "CASCADE", ["id"])
        assert not any(c["identity"] for c in spec["columns"])
    assert pg_schema.PG_SCHEMA_VERSION == SCHEMA_VERSION == 16
    assert pg_schema.PG_SCHEMA_MIGRATIONS_SEED[12][:2] == (13, IMAGE_STORAGE_MARKER)
    assert pg_schema.PG_SCHEMA_MIGRATIONS_SEED[12][2] == _V13_DETAILS_JSON


@pytest.fixture(scope="module")
def pg_image_database():
    psycopg = pytest.importorskip("psycopg")
    if not PG_URL:
        pytest.skip("SGAA_PG_TEST_URL is not configured -- REAL-PG EVIDENCE: ABSENT")
    admin = psycopg.connect(PG_URL, autocommit=True, connect_timeout=10)
    database = f"{RUN_PREFIX}{secrets.token_hex(3)}"
    admin.execute(f'CREATE DATABASE "{database}"')
    parts = urlsplit(PG_URL)
    url = urlunsplit((parts.scheme, parts.netloc, "/" + database, "connect_timeout=10", ""))
    try:
        conn = psycopg.connect(url, autocommit=False)
        try:
            assert pg_schema.provision_pg_schema(conn)["status"] == "provisioned"
            conn.commit()
            yield conn
        finally:
            conn.close()
    finally:
        try:
            admin.execute(f'DROP DATABASE IF EXISTS "{database}"')
        except psycopg.errors.ObjectInUse:
            admin.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
        leftovers = admin.execute(
            "SELECT count(*) FROM pg_database WHERE starts_with(datname, %s)", (RUN_PREFIX,)
        ).fetchone()[0]
        admin.close()
        assert leftovers == 0


def test_postgresql_constraints_give_the_same_verdicts(pg_image_database):
    import psycopg

    conn = pg_image_database
    pg_schema.validate_pg_schema(conn)
    conn.execute("INSERT INTO usuarios(id,nome,email,senha,tipo) VALUES(1,'A','a@x.test','x','admin')")
    conn.execute("INSERT INTO alunos(id,usuario_id,nome,matricula) VALUES(1,1,'A','M1')")
    conn.execute("INSERT INTO reportes(id,aluno_id,titulo,descricao) VALUES(1,1,'t','d')")
    verdicts = []
    for table, row, _expected in CANDIDATES:
        conn.execute("SAVEPOINT candidate")
        try:
            _insert(conn, table, 1, row, marker="%s")
            verdicts.append(True)
        except psycopg.errors.IntegrityError:
            verdicts.append(False)
        conn.execute("ROLLBACK TO SAVEPOINT candidate")
    assert verdicts == _sqlite_verdicts() == [expected for _t, _r, expected in CANDIDATES]
    # bytea round-trips byte for byte, and the owner delete cascades.
    content = bytes(range(256)) * 3
    _insert(conn, "alunos_foto", 1, _row(content), marker="%s")
    assert bytes(conn.execute("SELECT conteudo FROM alunos_foto WHERE aluno_id=1").fetchone()[0]) == content
    conn.execute("DELETE FROM alunos WHERE id=1")
    assert conn.execute("SELECT count(*) FROM alunos_foto").fetchone()[0] == 0
    conn.rollback()
