from __future__ import annotations

import sqlite3

import pytest
from werkzeug.security import generate_password_hash

from app.prod1_password_foundation_v8 import migrate_prod1_v7_to_v8
from app.prod1_schema import (
    PASSWORD_FOUNDATION_MARKER,
    SCHEMA_VERSION,
    Prod1SchemaError,
    _PROD1_V7_SIGNATURE_SHA256,
    _PROD1_V8_SIGNATURE_SHA256,
    _validate_prod1_v8_schema,
    _physical_schema_digest,
    bootstrap_prod1_schema,
    validate_prod1_schema,
)
from tests.prod1_v11_support import revert_prod1_v11_to_v10


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _test_hash(password: str) -> str:
    return generate_password_hash(password, method="pbkdf2:sha256:1")


def _build_v8(conn: sqlite3.Connection) -> None:
    """Revert the v11, v10 then v9 deltas and prove the frozen v8 shape.

    The bootstrap now produces v11, so v8 -- which this suite characterises --
    is reached by undoing the v11 table rebuild and then removing exactly the
    one column each of v10 and v9 added.
    """
    bootstrap_prod1_schema(conn)
    revert_prod1_v11_to_v10(conn)
    conn.execute("ALTER TABLE senha_tokens DROP COLUMN sent_at")
    conn.execute("DELETE FROM schema_migrations WHERE version=10")
    conn.execute("ALTER TABLE usuario_credenciais DROP COLUMN acesso_ativo")
    conn.execute("DELETE FROM schema_migrations WHERE version=9")
    conn.execute("PRAGMA user_version=8")
    conn.commit()
    assert _physical_schema_digest(conn) == _PROD1_V8_SIGNATURE_SHA256


def _build_v7(conn: sqlite3.Connection) -> None:
    """Revert only the additive v8 delta and prove the frozen v7 shape."""
    _build_v8(conn)
    conn.execute("DROP TABLE senha_tokens")
    conn.execute("DROP TABLE usuario_credenciais")
    conn.execute(
        "DELETE FROM configuracoes_app WHERE chave='default_passwords_enabled'"
    )
    conn.execute("DELETE FROM schema_migrations WHERE version=8")
    conn.execute("PRAGMA user_version=7")
    conn.commit()
    assert _physical_schema_digest(conn) == _PROD1_V7_SIGNATURE_SHA256


def _seed_v7_users(conn: sqlite3.Connection) -> dict[str, int]:
    defaults = {
        "admin_total": "admin123",
        "administrativo": "admin123",
        "consultivo": "consultivo123",
        "usuario": "aluno123",
        "usuario_teste": "teste123",
    }
    conn.executemany(
        "INSERT INTO configuracoes_acesso(nivel_acesso,senha_padrao) VALUES(?,?)",
        defaults.items(),
    )
    cases = (
        ("admin_default", "admin", "admin_total", "admin123"),
        ("coordinator_default", "admin", "administrativo", "admin123"),
        ("consultant_personal", "admin", "consultivo", "personal-secret"),
        ("student_default", "aluno", "usuario", "aluno123"),
        ("test_student_default", "aluno", "usuario_teste", "teste123"),
        # Matching another profile's current default does not make this
        # consultant a default-credential account.
        ("cross_profile_personal", "admin", "consultivo", "admin123"),
    )
    ids: dict[str, int] = {}
    for label, user_type, level, password in cases:
        cursor = conn.execute(
            "INSERT INTO usuarios(nome,email,senha,tipo,nivel_acesso) VALUES(?,?,?,?,?)",
            (label, f"{label}@example.test", _test_hash(password), user_type, level),
        )
        ids[label] = int(cursor.lastrowid)
    conn.commit()
    return ids


def _password_rows(conn: sqlite3.Connection) -> list[tuple[int, str]]:
    return [
        (int(row[0]), str(row[1]))
        for row in conn.execute("SELECT id,senha FROM usuarios ORDER BY id")
    ]


def _credential_rows(conn: sqlite3.Connection) -> list[tuple[int, str, int]]:
    return [
        (int(row[0]), str(row[1]), int(row[2]))
        for row in conn.execute(
            "SELECT usuario_id,estado,auth_version FROM usuario_credenciais ORDER BY usuario_id"
        )
    ]


def test_v7_to_v8_migration_preserves_hashes_and_classifies_current_defaults():
    conn = _connect()
    _build_v7(conn)
    ids = _seed_v7_users(conn)
    passwords_before = _password_rows(conn)
    user_count_before = conn.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]

    status = migrate_prod1_v7_to_v8(conn)

    assert status["schema_version"] == 8, "the v7->v8 step yields v8"
    assert SCHEMA_VERSION == 11, "the current head is v11"
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 8
    assert conn.execute(
        "SELECT name FROM schema_migrations WHERE version=8"
    ).fetchone()[0] == PASSWORD_FOUNDATION_MARKER
    assert conn.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == user_count_before
    assert _password_rows(conn) == passwords_before
    states = {
        int(row[0]): (str(row[1]), int(row[2]))
        for row in conn.execute(
            "SELECT usuario_id,estado,auth_version FROM usuario_credenciais"
        )
    }
    assert states == {
        ids["admin_default"]: ("default", 1),
        ids["coordinator_default"]: ("default", 1),
        ids["consultant_personal"]: ("personal", 1),
        ids["student_default"]: ("default", 1),
        ids["test_student_default"]: ("default", 1),
        ids["cross_profile_personal"]: ("personal", 1),
    }
    assert conn.execute(
        "SELECT valor FROM configuracoes_app WHERE chave='default_passwords_enabled'"
    ).fetchone()[0] == "1"
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_v8_physical_contract_tables_columns_index_and_constraints():
    conn = _connect()
    _build_v8(conn)
    assert _physical_schema_digest(conn) == _PROD1_V8_SIGNATURE_SHA256
    # v8 is a predecessor now: it is recognised by its own frozen contract,
    # not by validate_prod1_schema, which describes the v9 head.
    _validate_prod1_v8_schema(conn)

    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert {"usuario_credenciais", "senha_tokens"} <= tables
    assert [row[1] for row in conn.execute("PRAGMA table_info(usuario_credenciais)")] == [
        "usuario_id", "estado", "auth_version", "atualizado_em"
    ]
    assert [row[1] for row in conn.execute("PRAGMA table_info(senha_tokens)")] == [
        "id", "usuario_id", "purpose", "token_hash", "created_at",
        "expires_at", "consumed_at", "invalidated_at",
    ]
    assert "idx_senha_tokens_usuario_purpose" in {
        row[1] for row in conn.execute("PRAGMA index_list(senha_tokens)")
    }
    assert conn.execute("PRAGMA foreign_key_list(usuario_credenciais)").fetchone()[2] == "usuarios"
    assert conn.execute("PRAGMA foreign_key_list(senha_tokens)").fetchone()[2] == "usuarios"

    user_id = conn.execute(
        "INSERT INTO usuarios(nome,email,senha,tipo,nivel_acesso) VALUES('U','u@example.test','x','admin','admin_total')"
    ).lastrowid
    conn.execute(
        "INSERT INTO usuario_credenciais(usuario_id,estado) VALUES(?, 'default')",
        (user_id,),
    )
    assert conn.execute(
        "SELECT auth_version FROM usuario_credenciais WHERE usuario_id=?", (user_id,)
    ).fetchone()[0] == 1
    conn.execute(
        "INSERT INTO senha_tokens(usuario_id,purpose,token_hash,expires_at) VALUES(?,?,?,?)",
        (user_id, "first_access", "unique-token", "2099-01-01T00:00:00Z"),
    )
    second_user_id = conn.execute(
        "INSERT INTO usuarios(nome,email,senha,tipo,nivel_acesso) VALUES('U2','u2@example.test','x','admin','admin_total')"
    ).lastrowid
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO usuario_credenciais(usuario_id,estado) VALUES(?, 'unknown')",
            (second_user_id,),
        )
    conn.rollback()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO senha_tokens(usuario_id,purpose,token_hash,expires_at) VALUES(?,?,?,?)",
            (user_id, "other", "other-token", "2099-01-01T00:00:00Z"),
        )
    conn.rollback()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO senha_tokens(usuario_id,purpose,token_hash,expires_at) VALUES(?,?,?,?)",
            (user_id, "password_reset", "unique-token", "2099-01-01T00:00:00Z"),
        )
    conn.rollback()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO senha_tokens(usuario_id,purpose,token_hash,expires_at) VALUES(?,?,?,?)",
            (999999, "password_reset", "foreign-token", "2099-01-01T00:00:00Z"),
        )


def test_v8_bootstrap_is_idempotent_without_data_or_state_mutation():
    conn = _connect()
    _build_v7(conn)
    _seed_v7_users(conn)
    bootstrap_prod1_schema(conn)
    before = (
        _password_rows(conn),
        _credential_rows(conn),
        list(conn.execute("SELECT chave,valor FROM configuracoes_app ORDER BY chave")),
    )

    first = bootstrap_prod1_schema(conn)
    second = bootstrap_prod1_schema(conn)

    assert first == second
    assert before == (
        _password_rows(conn),
        _credential_rows(conn),
        list(conn.execute("SELECT chave,valor FROM configuracoes_app ORDER BY chave")),
    )


def test_v8_migration_rejects_non_v7_without_mutation():
    conn = _connect()
    bootstrap_prod1_schema(conn)
    before = list(conn.iterdump())
    with pytest.raises(Prod1SchemaError):
        migrate_prod1_v7_to_v8(conn)
    assert list(conn.iterdump()) == before
