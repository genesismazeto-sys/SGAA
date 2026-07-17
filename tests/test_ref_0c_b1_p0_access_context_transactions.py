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


def _make_atividades_schema_out_of_order() -> None:
    """Force the lazy rebuild path without changing data or using a real DB."""
    with main.app.app_context():
        conn = main.get_db_connection()
        rows = conn.execute(
            """
            SELECT id, grupo, nome, descricao, limite_horas, tipo_atividade,
                   tem_limitacao, tipo_limitacao, limite_horas_total,
                   limite_horas_semestral
              FROM atividades
            """
        ).fetchall()
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("DROP TABLE atividades")
        conn.execute(
            """
            CREATE TABLE atividades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                grupo TEXT NOT NULL,
                nome TEXT NOT NULL UNIQUE,
                descricao TEXT,
                limite_horas INTEGER,
                tipo_atividade TEXT NOT NULL,
                tem_limitacao BOOLEAN DEFAULT 0,
                tipo_limitacao TEXT,
                limite_horas_semestral INTEGER,
                limite_horas_total INTEGER
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO atividades (
                id, grupo, nome, descricao, limite_horas, tipo_atividade,
                tem_limitacao, tipo_limitacao, limite_horas_total,
                limite_horas_semestral
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [tuple(row) for row in rows],
        )
        conn.commit()
        conn.execute("PRAGMA foreign_keys = ON")


def test_mapped_rebuild_route_runs_after_gate_without_lock_or_fk_ddl_failure(versioned_env, monkeypatch):
    _make_atividades_schema_out_of_order()
    client = versioned_env["client"]
    _login(client, 1)
    original_rebuild = main.ensure_atividades_schema_current
    rebuild_calls = []

    def checked_rebuild(conn):
        rebuild_calls.append(conn.in_transaction)
        return original_rebuild(conn)

    monkeypatch.setattr(main, "ensure_atividades_schema_current", checked_rebuild)

    activity_name = f"P0 rebuilt activity {uuid.uuid4().hex}"
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
    assert rebuild_calls == [False]
    with main.app.app_context():
        columns = tuple(
            row["name"]
            for row in main.get_db_connection().execute("PRAGMA table_info(atividades)").fetchall()
        )
    assert columns == main.ATIVIDADES_SCHEMA_COLUMNS


def test_gate_keeps_mapped_route_allow_and_deny_results(versioned_env):
    client = versioned_env["client"]
    _login(client, _make_consultivo())
    denied = client.get("/admin/catalogo-versoes/nova-base")
    assert denied.status_code == 302
    assert denied.headers["Location"].endswith("/admin/dashboard")

    _login(client, 1)
    allowed = client.get("/admin/catalogo-versoes/nova-base")
    assert allowed.status_code == 200
