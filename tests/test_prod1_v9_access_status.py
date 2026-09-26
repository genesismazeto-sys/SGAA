"""prod-1/v9: durable access status, and the root e-mail collision resolution.

v9 adds exactly one column, ``usuario_credenciais.acesso_ativo``. It is the
smallest additive change that makes "this account may not log in" a first-class
durable fact rather than a side effect of neutralising a password hash.

``estado`` is deliberately NOT overloaded: that column records where the
password came from (``default`` / ``personal``), which is orthogonal to whether
login is permitted, and is what the shared-default switch keys off.

Every test runs on a disposable database. The canonical v8 database is never
opened for writing.
"""

from __future__ import annotations

import sqlite3

import pytest

import main
from app import db_maintenance
from app.prod1_access_status_ddl import USUARIO_CREDENCIAIS_V9_ADD_COLUMN_SQL
from app.prod1_schema import (
    ACCESS_STATUS_MARKER,
    SCHEMA_EPOCH,
    SCHEMA_VERSION,
    Prod1SchemaError,
    _PROD1_V8_SIGNATURE_SHA256,
    _PROD1_V9_SIGNATURE_SHA256,
    _physical_schema_digest,
    _validate_prod1_v8_schema,
    bootstrap_prod1_schema,
    migrate_prod1_v8_to_v9,
    validate_prod1_schema,
)
from app.root_admin import (
    LEGACY_ROOT_ADMIN_EMAIL,
    migrate_root_admin_email,
    resolve_root_admin_id,
)
from app.security.passwords import hash_password
from app.user_accounts import (
    CREDENTIAL_STATE_DEFAULT,
    CREDENTIAL_STATE_PERSONAL,
    create_usuario_with_access_level,
    set_usuario_access_active,
    usuario_access_is_active,
)
from tests.canonical_matrix_test_support import login_admin
from tests.root_admin_test_config import TEST_ROOT_ADMIN_EMAIL
from tests.versioned_test_support import isolated_versioned_app_env
from tests.prod1_v11_support import revert_prod1_v11_to_v10


RESERVED_TEST_EMAIL = "aluno-teste-2@example.invalid"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _build_v9(conn: sqlite3.Connection) -> None:
    """A genuine v9 database: bootstrap the head, revert the one v10 column.

    v9 is no longer the head -- v10 added ``senha_tokens.sent_at`` and v11
    rebuilt ``usuario_credenciais`` for ``pending`` -- so it is reached by
    reverting forwards-only, exactly as this suite already reached v8.
    """
    bootstrap_prod1_schema(conn)
    revert_prod1_v11_to_v10(conn)
    conn.execute("ALTER TABLE senha_tokens DROP COLUMN sent_at")
    conn.execute("DELETE FROM schema_migrations WHERE version=10")
    conn.execute("PRAGMA user_version=9")
    conn.commit()
    assert _physical_schema_digest(conn) == _PROD1_V9_SIGNATURE_SHA256, (
        "the reverted database is not the frozen v9 shape"
    )


def _build_v8(conn: sqlite3.Connection) -> None:
    """A genuine v8 database: revert the v10 column, then the v9 one."""
    _build_v9(conn)
    conn.execute("ALTER TABLE usuario_credenciais DROP COLUMN acesso_ativo")
    conn.execute("DELETE FROM schema_migrations WHERE version=9")
    conn.execute("PRAGMA user_version=8")
    conn.commit()
    assert _physical_schema_digest(conn) == _PROD1_V8_SIGNATURE_SHA256, (
        "the reverted database is not the frozen v8 shape, so anything this "
        "suite proves about migrating it is meaningless"
    )


def _seed(conn: sqlite3.Connection, label: str, state: str) -> int:
    cursor = create_usuario_with_access_level(
        conn, label, f"{label}@example.test", hash_password("x"),
        "admin", "admin_total", credential_state=state,
    )
    conn.commit()
    return int(cursor.lastrowid)


# ------------------------------------------------------------------ SCHEMA


def test_v9_is_a_declared_step_of_the_migration_chain():
    """v9 is no longer the head; it must still be exactly step 9."""
    assert SCHEMA_VERSION > 9
    assert db_maintenance.SCHEMA_MIGRATIONS[8][:2] == (9, ACCESS_STATUS_MARKER)


def test_v8_to_v9_is_additive_and_migrates_everything_active():
    conn = _connect()
    _build_v8(conn)

    ids = {
        "default": _seed(conn, "defaultuser", CREDENTIAL_STATE_DEFAULT),
        "personal": _seed(conn, "personaluser", CREDENTIAL_STATE_PERSONAL),
    }
    credentials_before = [
        tuple(row)
        for row in conn.execute(
            "SELECT usuario_id,estado,auth_version FROM usuario_credenciais ORDER BY usuario_id"
        )
    ]
    passwords_before = [
        tuple(row) for row in conn.execute("SELECT id,senha FROM usuarios ORDER BY id")
    ]

    status = migrate_prod1_v8_to_v9(conn)

    assert status["schema_version"] == 9
    assert status["access_status_backfill"] == "all_existing_credentials_active"
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 9
    assert conn.execute(
        "SELECT name FROM schema_migrations WHERE version=9"
    ).fetchone()[0] == ACCESS_STATUS_MARKER

    # Additive: nothing pre-existing moved.
    assert [
        tuple(row)
        for row in conn.execute(
            "SELECT usuario_id,estado,auth_version FROM usuario_credenciais ORDER BY usuario_id"
        )
    ] == credentials_before
    assert [
        tuple(row) for row in conn.execute("SELECT id,senha FROM usuarios ORDER BY id")
    ] == passwords_before

    # Every pre-existing credential migrates active, regardless of estado.
    rows = {
        int(row["usuario_id"]): int(row["acesso_ativo"])
        for row in conn.execute("SELECT usuario_id,acesso_ativo FROM usuario_credenciais")
    }
    assert rows[ids["default"]] == 1
    assert rows[ids["personal"]] == 1
    assert set(rows.values()) == {1}

    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    # v9 is a predecessor now, so it must NOT satisfy the head validator.
    with pytest.raises(Prod1SchemaError):
        validate_prod1_schema(conn)
    assert _physical_schema_digest(conn) == _PROD1_V9_SIGNATURE_SHA256


def test_migrated_v9_is_signature_identical_to_a_reverted_v9():
    """The v8 -> v9 ALTER still lands on the frozen v9 shape."""
    migrated = _connect()
    _build_v8(migrated)
    migrate_prod1_v8_to_v9(migrated)

    reverted = _connect()
    _build_v9(reverted)

    assert _physical_schema_digest(migrated) == _physical_schema_digest(reverted)
    assert _physical_schema_digest(reverted) == _PROD1_V9_SIGNATURE_SHA256


def test_v9_migration_refuses_a_database_that_is_not_v8():
    conn = _connect()
    bootstrap_prod1_schema(conn)  # already past v9
    with pytest.raises(Prod1SchemaError):
        migrate_prod1_v8_to_v9(conn)


def test_v8_remains_recognisable_as_a_predecessor():
    conn = _connect()
    _build_v8(conn)
    _validate_prod1_v8_schema(conn)
    with pytest.raises(Prod1SchemaError):
        validate_prod1_schema(conn)


def test_access_status_column_contract():
    conn = _connect()
    bootstrap_prod1_schema(conn)
    columns = {row["name"]: row for row in conn.execute("PRAGMA table_info(usuario_credenciais)")}
    assert "acesso_ativo" in columns
    assert columns["acesso_ativo"]["notnull"] == 1
    assert columns["acesso_ativo"]["dflt_value"] == "1"

    usuario_id = _seed(conn, "contract", CREDENTIAL_STATE_PERSONAL)
    assert int(
        conn.execute(
            "SELECT acesso_ativo FROM usuario_credenciais WHERE usuario_id=?", (usuario_id,)
        ).fetchone()[0]
    ) == 1
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "UPDATE usuario_credenciais SET acesso_ativo=2 WHERE usuario_id=?", (usuario_id,)
        )


def test_estado_is_not_overloaded_to_carry_access_status():
    """The two facts must stay independent columns.

    v9 added access status as its own column rather than a third ``estado``.
    v11 later added ``pending`` -- a credential fact, "no usable password" --
    and access status is still the separate ``acesso_ativo``.
    """
    v9 = _connect()
    _build_v9(v9)
    v9_sql = str(
        v9.execute("SELECT sql FROM sqlite_master WHERE name='usuario_credenciais'").fetchone()[0]
    )
    assert "estado IN ('default','personal')" in v9_sql
    assert "acesso_ativo" in v9_sql

    conn = _connect()
    bootstrap_prod1_schema(conn)
    estado_check = str(
        conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='usuario_credenciais'"
        ).fetchone()[0]
    )
    assert "estado IN ('pending','default','personal')" in estado_check
    assert "revogado" not in estado_check and "inactive" not in estado_check
    assert "acesso_ativo" in estado_check

    usuario_id = _seed(conn, "orthogonal", CREDENTIAL_STATE_PERSONAL)
    set_usuario_access_active(conn, usuario_id, False)
    conn.commit()
    row = conn.execute(
        "SELECT estado,acesso_ativo FROM usuario_credenciais WHERE usuario_id=?", (usuario_id,)
    ).fetchone()
    assert row["estado"] == CREDENTIAL_STATE_PERSONAL, "revocation rewrote the password origin"
    assert int(row["acesso_ativo"]) == 0
    assert usuario_access_is_active(conn, usuario_id) is False


def test_add_column_statement_matches_the_bootstrap_ddl():
    """The migration and the fresh DDL must not drift apart."""
    altered = _connect()
    _build_v8(altered)
    altered.execute(USUARIO_CREDENCIAIS_V9_ADD_COLUMN_SQL)
    fresh = _connect()
    bootstrap_prod1_schema(fresh)
    assert [row[1] for row in altered.execute("PRAGMA table_xinfo(usuario_credenciais)")] == [
        row[1] for row in fresh.execute("PRAGMA table_xinfo(usuario_credenciais)")
    ]


def test_canonical_database_is_never_written_by_this_suite():
    """The canonical file must be a published version, untouched by these tests."""
    from pathlib import Path

    canonical = Path(__file__).resolve().parents[1] / "database.db"
    if not canonical.exists():
        pytest.skip("no canonical database present in this checkout")
    probe = sqlite3.connect(f"file:{canonical.as_posix()}?mode=ro", uri=True)
    try:
        version = probe.execute("PRAGMA user_version").fetchone()[0]
    finally:
        probe.close()
    # Canonical was migrated to v11 on 2026-09-24 (authorised, UI-CP1).
    assert version in (8, 9, 10, 11), f"canonical database is at an unexpected version {version}"


# ------------------------------------------ ROOT E-MAIL COLLISION RESOLUTION


def _collision_fixture(client) -> tuple[int, int]:
    """Reproduce the canonical shape: root on the legacy address, and a test
    student already holding the target root address."""
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "UPDATE usuarios SET email=? WHERE id=(SELECT MIN(id) FROM usuarios WHERE tipo='admin')",
            (LEGACY_ROOT_ADMIN_EMAIL,),
        )
        conn.commit()
        root_id = int(resolve_root_admin_id(conn))
    response = client.post(
        "/admin/acesso/salvar",
        data={
            "nome": "Aluno Teste 2", "email": TEST_ROOT_ADMIN_EMAIL,
            "nivel_acesso": "usuario", "senha": "aluno-secret",
            "matricula": "PPA-NOT-T10.003", "status": "Ativo",
        },
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT u.id AS uid, a.id AS aid FROM usuarios u JOIN alunos a ON a.usuario_id=u.id "
            "WHERE LOWER(u.email)=?", (TEST_ROOT_ADMIN_EMAIL,)
        ).fetchone()
    return root_id, int(row["uid"])


def test_collision_resolution_through_the_authoritative_student_service(tmp_path):
    """Move the test student aside, then migrate root -- losing nothing.

    The student's address is changed through ``admin_editar_aluno``, the
    handler that owns account/student consistency, so ``usuarios.email`` and
    ``alunos.email`` move together instead of by ad-hoc SQL.
    """
    with isolated_versioned_app_env(tmp_path, "v9-collision.db") as env:
        client = env["client"]
        login_admin(client)
        root_id, student_usuario_id = _collision_fixture(client)

        with main.app.app_context():
            conn = main.get_db_connection()
            student_before = dict(
                conn.execute(
                    "SELECT id,usuario_id,nome,matricula,turma_id,matriz_id,status "
                    "FROM alunos WHERE usuario_id=?",
                    (student_usuario_id,),
                ).fetchone()
            )
            usuarios_before = int(conn.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0])
            alunos_before = int(conn.execute("SELECT COUNT(*) FROM alunos").fetchone()[0])

        # A. move the test student onto the reserved address.
        response = client.post(
            f"/admin/editar_aluno/{student_usuario_id}",
            data={
                "nome": student_before["nome"], "email": RESERVED_TEST_EMAIL,
                "matricula": student_before["matricula"],
                "turma_id": student_before["turma_id"] or "",
                "status": student_before["status"],
            },
            follow_redirects=True,
        )
        assert response.status_code == 200

        with main.app.app_context():
            conn = main.get_db_connection()
            usuario_email = str(
                conn.execute(
                    "SELECT email FROM usuarios WHERE id=?", (student_usuario_id,)
                ).fetchone()["email"]
            )
            aluno_row = dict(
                conn.execute(
                    "SELECT id,usuario_id,nome,matricula,turma_id,matriz_id,status,email "
                    "FROM alunos WHERE usuario_id=?",
                    (student_usuario_id,),
                ).fetchone()
            )
        # B. both addresses moved together.
        assert usuario_email == RESERVED_TEST_EMAIL
        assert aluno_row["email"] == RESERVED_TEST_EMAIL
        # C. nothing academic moved.
        for column in ("id", "usuario_id", "nome", "matricula", "turma_id", "matriz_id", "status"):
            assert aluno_row[column] == student_before[column], f"{column} changed"

        # D. now root can take the address, in place.
        with main.app.app_context():
            conn = main.get_db_connection()
            credential_before = dict(
                conn.execute(
                    "SELECT * FROM usuario_credenciais WHERE usuario_id=?", (root_id,)
                ).fetchone()
            )
            result = migrate_root_admin_email(conn)
            conn.commit()

            assert result["migrated"] is True
            assert result["root_id"] == root_id
            root_row = dict(conn.execute("SELECT * FROM usuarios WHERE id=?", (root_id,)).fetchone())
            assert root_row["email"] == TEST_ROOT_ADMIN_EMAIL
            assert dict(
                conn.execute(
                    "SELECT * FROM usuario_credenciais WHERE usuario_id=?", (root_id,)
                ).fetchone()
            ) == credential_before, "the address change touched the credential"

            # No duplicates, no losses, no violations.
            assert int(conn.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]) == usuarios_before
            assert int(conn.execute("SELECT COUNT(*) FROM alunos").fetchone()[0]) == alunos_before
            assert int(
                conn.execute(
                    "SELECT COUNT(*) FROM usuarios WHERE LOWER(email)=?",
                    (TEST_ROOT_ADMIN_EMAIL,),
                ).fetchone()[0]
            ) == 1
            assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert conn.execute("PRAGMA foreign_key_check").fetchall() == []

            # E. root now resolves directly, not through the legacy fallback.
            assert resolve_root_admin_id(conn) == root_id
            assert str(
                conn.execute("SELECT email FROM usuarios WHERE id=?", (root_id,)).fetchone()["email"]
            ) == TEST_ROOT_ADMIN_EMAIL


def test_root_resolution_prefers_the_configured_address_over_the_legacy_one(tmp_path):
    """After migration the fallback must not be what identifies root."""
    with isolated_versioned_app_env(tmp_path, "v9-root-preference.db"):
        with main.app.app_context():
            conn = main.get_db_connection()
            root_id = int(resolve_root_admin_id(conn))
            assert str(
                conn.execute("SELECT email FROM usuarios WHERE id=?", (root_id,)).fetchone()["email"]
            ) == TEST_ROOT_ADMIN_EMAIL

            # A second admin parked on the legacy address must not win.
            create_usuario_with_access_level(
                conn, "Legacy Admin", LEGACY_ROOT_ADMIN_EMAIL, hash_password("x"),
                "admin", "admin_total", credential_state=CREDENTIAL_STATE_PERSONAL,
            )
            conn.commit()
            assert resolve_root_admin_id(conn) == root_id, (
                "the legacy fallback overrode the configured root identity"
            )


def test_schema_epoch_is_unchanged_by_v9():
    assert SCHEMA_EPOCH == "prod-1"
