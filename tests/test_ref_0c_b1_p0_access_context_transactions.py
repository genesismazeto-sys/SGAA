"""Focused transaction-ownership regression tests for REF-0C-B1-P0.

These tests use only temporary databases.  They cover the access-schema helper
because authorization-context reads call it on the Flask request connection.
"""
from __future__ import annotations

import sqlite3
import uuid

import pytest

import main
from tests.versioned_test_support import isolated_versioned_app_env


def _new_access_connection(tmp_path):
    conn = sqlite3.connect(tmp_path / "access_context.db")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE usuarios (
            id INTEGER PRIMARY KEY,
            nome TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            senha TEXT NOT NULL,
            tipo TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def test_access_schema_on_clean_connection_closes_its_own_transaction_and_persists(tmp_path):
    conn = _new_access_connection(tmp_path)
    try:
        assert conn.in_transaction is False
        main.ensure_usuario_access_schema(conn)
        assert conn.in_transaction is False
    finally:
        conn.close()

    reopened = sqlite3.connect(tmp_path / "access_context.db")
    try:
        columns = {row[1] for row in reopened.execute("PRAGMA table_info(usuarios)")}
        defaults = reopened.execute("SELECT COUNT(*) FROM configuracoes_acesso").fetchone()[0]
        assert "nivel_acesso" in columns
        assert defaults == 5
    finally:
        reopened.close()


def test_access_schema_preserves_caller_owned_transaction(tmp_path):
    conn = _new_access_connection(tmp_path)
    observer = sqlite3.connect(tmp_path / "access_context.db")
    try:
        conn.execute("CREATE TABLE caller_work (value TEXT NOT NULL)")
        conn.commit()
        conn.execute("INSERT INTO caller_work (value) VALUES ('pending')")
        assert conn.in_transaction is True

        main.ensure_usuario_access_schema(conn)

        assert conn.in_transaction is True
        assert observer.execute("SELECT COUNT(*) FROM caller_work").fetchone()[0] == 0
        conn.rollback()
        assert observer.execute("SELECT COUNT(*) FROM caller_work").fetchone()[0] == 0
    finally:
        observer.close()
        conn.close()


def test_repeated_access_context_loads_are_idempotent_and_transaction_neutral(tmp_path):
    conn = _new_access_connection(tmp_path)
    try:
        main.ensure_usuario_access_schema(conn)
        conn.execute(
            "INSERT INTO usuarios (id, nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?, ?)",
            (1, "Admin", "admin@example.com", "hash", "admin", "admin_total"),
        )
        conn.commit()

        first = main._load_admin_access_context(conn, 1)
        assert conn.in_transaction is False
        second = main._load_admin_access_context(conn, 1)
        assert conn.in_transaction is False
        assert first["effective_scopes"] == second["effective_scopes"]
        assert conn.execute("SELECT COUNT(*) FROM configuracoes_acesso").fetchone()[0] == 5
    finally:
        conn.close()


@pytest.fixture()
def versioned_env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "p0_transaction_hygiene.db") as env:
        yield env


def _login(client, user_id: int) -> None:
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["user_type"] = "admin"
        sess["user_name"] = "Transaction Hygiene Test"


def _make_consultivo() -> int:
    with main.app.app_context():
        conn = main.get_db_connection()
        user_id = conn.execute(
            """
            INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso)
            VALUES (?, ?, ?, 'admin', 'consultivo') RETURNING id
            """,
            ("Consultivo", f"p0.{uuid.uuid4().hex}@example.com", main.hash_password("pass")),
        ).fetchone()["id"]
        conn.commit()
    return user_id


def test_mapped_route_uses_bootstrapped_v2_without_recurring_atividades_ddl(
    versioned_env, monkeypatch
):
    client = versioned_env["client"]
    _login(client, 1)
    expected_columns = (
        "id",
        "grupo",
        "nome",
        "descricao",
        "limite_horas",
        "tipo_atividade",
        "tem_limitacao",
        "tipo_limitacao",
        "limite_horas_total",
        "limite_horas_semestral",
        "documentos_json",
    )
    assert not hasattr(main, "ensure_atividades_schema_current")

    with main.app.app_context():
        conn = main.get_db_connection()
        columns_before = tuple(
            row["name"] for row in conn.execute("PRAGMA table_info(atividades)")
        )
        migrations_before = tuple(
            tuple(row)
            for row in conn.execute(
                "SELECT version, name FROM schema_migrations ORDER BY version"
            ).fetchall()
        )
        user_version_before = conn.execute("PRAGMA user_version").fetchone()[0]
    assert columns_before == expected_columns
    assert migrations_before[-1] == (3, "normalize_activity_versioning_core")
    assert user_version_before == 3

    original_get_db_connection = main.get_db_connection
    statements = []

    def traced_connection():
        conn = original_get_db_connection()
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(main, "get_db_connection", traced_connection)

    activity_name = f"P0 versioned activity {uuid.uuid4().hex}"
    response = client.post(
        "/admin/matrizes/1/atividades/nova/aac",
        data={
            "nome": activity_name,
            "grupo_numero": "7",
            "grupo_descricao": "P0 transaction hygiene",
            "add_to_matrix": "1",
        },
    )

    assert response.status_code == 302
    forbidden_atividades_ddl = (
        "ALTER TABLE ATIVIDADES",
        "DROP TABLE ATIVIDADES",
        "CREATE TABLE ATIVIDADES__NEW",
        "INSERT INTO SCHEMA_MIGRATIONS",
        "PRAGMA USER_VERSION =",
        "PRAGMA FOREIGN_KEYS = OFF",
    )
    normalized_statements = tuple(" ".join(sql.split()).upper() for sql in statements)
    assert not any(
        token in sql for token in forbidden_atividades_ddl for sql in normalized_statements
    )
    with main.app.app_context():
        conn = original_get_db_connection()
        columns_after = tuple(
            row["name"] for row in conn.execute("PRAGMA table_info(atividades)")
        )
        migrations_after = tuple(
            tuple(row)
            for row in conn.execute(
                "SELECT version, name FROM schema_migrations ORDER BY version"
            ).fetchall()
        )
        user_version_after = conn.execute("PRAGMA user_version").fetchone()[0]
        created = conn.execute(
            "SELECT COUNT(*) FROM atividades WHERE nome = ?", (activity_name,)
        ).fetchone()[0]
    assert columns_after == columns_before
    assert migrations_after == migrations_before
    assert user_version_after == user_version_before
    assert created == 1


def test_gate_keeps_mapped_route_allow_and_deny_results(versioned_env):
    client = versioned_env["client"]
    _login(client, _make_consultivo())
    denied = client.get("/admin/catalogo-versoes/nova-base")
    assert denied.status_code == 302
    assert denied.headers["Location"].endswith("/admin/dashboard")

    _login(client, 1)
    allowed = client.get("/admin/catalogo-versoes/nova-base")
    assert allowed.status_code == 200
