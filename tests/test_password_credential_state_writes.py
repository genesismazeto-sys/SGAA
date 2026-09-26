from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from werkzeug.security import generate_password_hash

from app.prod1_schema import bootstrap_prod1_schema
from app.user_accounts import (
    CREDENTIAL_STATE_DEFAULT,
    CREDENTIAL_STATE_PERSONAL,
    create_usuario_with_access_level,
    create_usuario_with_default_password,
    rehash_usuario_password,
    set_usuario_password_hash,
)


ROOT = Path(__file__).resolve().parents[1]


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    bootstrap_prod1_schema(conn)
    conn.executemany(
        "INSERT INTO configuracoes_acesso(nivel_acesso,senha_padrao) VALUES(?,?)",
        (
            ("admin_total", "admin123"),
            ("administrativo", "admin123"),
            ("consultivo", "consultivo123"),
            ("usuario", "aluno123"),
            ("usuario_teste", "teste123"),
        ),
    )
    conn.commit()
    return conn


def _hash(password: str) -> str:
    return generate_password_hash(password, method="pbkdf2:sha256:1")


def _credential(conn: sqlite3.Connection, user_id: int) -> tuple[str, int]:
    row = conn.execute(
        "SELECT estado,auth_version FROM usuario_credenciais WHERE usuario_id=?",
        (user_id,),
    ).fetchone()
    return str(row[0]), int(row[1])


def test_account_creation_boundaries_classify_default_and_explicit_passwords():
    conn = _connect()
    default_user = create_usuario_with_default_password(
        conn, "Default student", "default@example.test", "aluno"
    ).lastrowid
    personal_user = create_usuario_with_access_level(
        conn,
        "Personal admin",
        "personal@example.test",
        _hash("personal-password"),
        "admin",
        "consultivo",
        credential_state=CREDENTIAL_STATE_PERSONAL,
    ).lastrowid

    assert _credential(conn, int(default_user)) == (CREDENTIAL_STATE_DEFAULT, 1)
    assert _credential(conn, int(personal_user)) == (CREDENTIAL_STATE_PERSONAL, 1)


def test_password_write_and_state_update_share_caller_transaction():
    conn = _connect()
    user_id = int(
        create_usuario_with_default_password(
            conn, "Rollback student", "rollback@example.test", "aluno"
        ).lastrowid
    )
    conn.commit()
    before_hash = conn.execute(
        "SELECT senha FROM usuarios WHERE id=?", (user_id,)
    ).fetchone()[0]
    before_credential = _credential(conn, user_id)

    conn.execute("BEGIN")
    set_usuario_password_hash(
        conn,
        user_id,
        _hash("new-personal-password"),
        credential_state=CREDENTIAL_STATE_PERSONAL,
    )
    assert _credential(conn, user_id) == (CREDENTIAL_STATE_PERSONAL, 2)
    conn.rollback()

    assert conn.execute(
        "SELECT senha FROM usuarios WHERE id=?", (user_id,)
    ).fetchone()[0] == before_hash
    assert _credential(conn, user_id) == before_credential


def test_reset_and_arbitrary_write_states_and_rehash_preservation():
    conn = _connect()
    user_id = int(
        create_usuario_with_default_password(
            conn, "State student", "state@example.test", "aluno"
        ).lastrowid
    )
    set_usuario_password_hash(
        conn,
        user_id,
        _hash("personal-password"),
        credential_state=CREDENTIAL_STATE_PERSONAL,
    )
    assert _credential(conn, user_id) == (CREDENTIAL_STATE_PERSONAL, 2)

    rehash_usuario_password(conn, user_id, _hash("personal-password"))
    assert _credential(conn, user_id) == (CREDENTIAL_STATE_PERSONAL, 3)

    set_usuario_password_hash(
        conn,
        user_id,
        _hash("aluno123"),
        credential_state=CREDENTIAL_STATE_DEFAULT,
    )
    assert _credential(conn, user_id) == (CREDENTIAL_STATE_DEFAULT, 4)


def test_production_password_write_sites_use_the_shared_boundary():
    expected_calls = {
        "app/db.py": "create_usuario_with_access_level",
        "app/services/student_import_service.py": "create_usuario_pending",
        "app/views/admin/acesso.py": "set_usuario_password_hash",
        "app/views/admin/alunos_turmas_cursos.py": "set_usuario_password_hash",
        "app/views/admin/meus_dados.py": "set_usuario_password_hash",
        "app/views/aluno.py": "set_usuario_password_hash",
        "app/views/core.py": "rehash_usuario_password",
    }
    for relative, call in expected_calls.items():
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert call in source
        assert re.search(r"UPDATE\s+usuarios\s+SET\s+senha\s*=", source, re.I) is None

    boundary = (ROOT / "app/user_accounts.py").read_text(encoding="utf-8")
    assert "UPDATE usuarios SET senha = ?" in boundary
    assert "set_usuario_credential_state" in boundary
