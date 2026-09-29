"""An e-mail change retires every link sent to the previous address (UI-B32).

First-access and password-reset links live in ``senha_tokens``, bound only to
``usuario_id``; the address they were mailed to is ``usuarios.email`` at send
time and is never stored with them. So when an account's e-mail changed, a link
already sitting in the OLD mailbox kept granting access to the account that had
moved away from it -- through import, the Turma roster, Editar Aluno, Acesso
and both "Meus dados" screens alike.

``app.user_accounts.set_usuario_email`` is now the one writer of that column: a
real change invalidates every outstanding link of the account through the
existing revocation (``invalidated_at``), exactly what a password change does.
Nothing else moves -- password hash, ``estado``, ``acesso_ativo`` and
``auth_version`` stay put, so live sessions continue (an address is not a
credential) and no new link is sent. A rejected or conflicting change rolls the
revocation back with it.
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import pytest

import main
from app.password_tokens import (
    PURPOSE_FIRST_ACCESS,
    PURPOSE_PASSWORD_RESET,
    issue_password_token,
    resolve_password_token,
)
from app.root_admin import migrate_root_admin_email, resolve_root_admin_id, root_admin_email
from app.security.passwords import hash_password
from app.user_accounts import (
    CREDENTIAL_STATE_PERSONAL,
    create_usuario_pending,
    create_usuario_with_access_level,
    get_usuario_auth_version,
    set_usuario_access_active,
    set_usuario_email,
)
from tests.canonical_matrix_test_support import login_admin
from tests.canonical_request_test_support import login_student, student_identity
from tests.session_support import stamp_auth_version
from tests.versioned_test_support import isolated_versioned_app_env


TURMA_ID = 1  # seeded PPA-T10
OLD = "old@example.com"
NEW = "new@example.com"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _conn():
    return main.get_db_connection()


def _seed_student(email=OLD, matricula="EX-0001", *, personal=False) -> int:
    with main.app.app_context():
        conn = _conn()
        if personal:
            usuario_id = create_usuario_with_access_level(
                conn, "Aluna Existente", email, hash_password("Senha#2026"),
                "aluno", "usuario", credential_state=CREDENTIAL_STATE_PERSONAL,
            ).lastrowid
        else:
            usuario_id = create_usuario_pending(conn, "Aluna Existente", email, "aluno").lastrowid
        conn.execute(
            "INSERT INTO alunos (usuario_id,nome,email,matricula,turma_id,status)"
            " VALUES (?,?,?,?,?,'Ativo')",
            (usuario_id, "Aluna Existente", email, matricula, TURMA_ID),
        )
        conn.commit()
        return int(usuario_id)


def _issue(usuario_id: int, purpose: str) -> str:
    with main.app.app_context():
        conn = _conn()
        raw, _ = issue_password_token(conn, usuario_id, purpose)
        conn.commit()
        return raw


def _usable(raw: str, purpose: str) -> bool:
    with main.app.app_context():
        return resolve_password_token(_conn(), raw, purpose=purpose) is not None


def _credential(usuario_id: int) -> dict:
    with main.app.app_context():
        conn = _conn()
        row = dict(conn.execute(
            "SELECT * FROM usuario_credenciais WHERE usuario_id=?", (usuario_id,)
        ).fetchone())
        row["senha"] = conn.execute("SELECT senha FROM usuarios WHERE id=?", (usuario_id,)).fetchone()[0]
        return row


def _email(usuario_id: int) -> str:
    with main.app.app_context():
        return _conn().execute("SELECT email FROM usuarios WHERE id=?", (usuario_id,)).fetchone()[0]


def _redeem(client, purpose: str, raw: str):
    path = "/primeiro-acesso" if purpose == PURPOSE_FIRST_ACCESS else "/redefinir-senha"
    return client.post(
        path,
        data={"token": raw, "senha": "Nova#Senha2026", "confirmacao_senha": "Nova#Senha2026"},
    )


def _curso_id() -> int:
    with main.app.app_context():
        return _conn().execute("SELECT curso_id FROM turmas WHERE id=?", (TURMA_ID,)).fetchone()[0]


def _editar_aluno(client, usuario_id: int, email: str, **extra):
    return client.post(
        f"/admin/editar_aluno/{usuario_id}",
        data={
            "nome": "Aluna Existente",
            "email": email,
            "matricula": "EX-0001",
            "turma_id": str(TURMA_ID),
            "status": "Ativo",
            "senha": "",
            **extra,
        },
    )


def _editar_turma(client, rows):
    return client.post(
        f"/admin/editar_turma/{TURMA_ID}",
        data={
            "curso_id": str(_curso_id()),
            "numero_turma": "10",
            "ano_inicio": "2025",
            "semestre_inicio": "2",
            "turno": "Noite",
            "status": "Ativa",
            "matriz_id": "",
            "aluno_nome[]": [r[0] for r in rows],
            "aluno_email[]": [r[1] for r in rows],
            "aluno_matricula[]": [r[2] for r in rows],
            "aluno_situacao[]": ["ATIVO"] * len(rows),
            "aluno_importado[]": ["0"] * len(rows),
        },
    )


def _import(client, rows):
    text = "Aluno,E-mail,Matricula\n" + "".join(f"{a},{e},{m}\n" for a, e, m in rows)
    return client.post(
        "/admin/turmas/importar",
        data={
            "turma_id": str(TURMA_ID),
            "csv_arquivo": (io.BytesIO(text.encode("utf-8")), "alunos.csv"),
        },
    )


def _acesso(client, usuario_id: int, email: str):
    return client.post(
        "/admin/acesso/salvar",
        data={
            "usuario_id": str(usuario_id),
            "nome": "Aluna Existente",
            "email": email,
            "nivel_acesso": "usuario",
            "senha": "",
            "matricula": "EX-0001",
            "status": "Ativo",
            "turma_id": str(TURMA_ID),
        },
    )


# --- every entry point retires the old links --------------------------------

ENTRY_POINTS = {
    "editar-aluno": lambda client, uid: _editar_aluno(client, uid, NEW),
    "editar-turma-roster": lambda client, uid: _editar_turma(
        client, [("Aluna Existente", NEW, "EX-0001")]
    ),
    "import": lambda client, uid: _import(client, [("Aluna Existente", NEW, "EX-0001")]),
    "acesso": lambda client, uid: _acesso(client, uid, NEW),
}


@pytest.mark.parametrize("entry_point", sorted(ENTRY_POINTS))
def test_first_access_link_to_the_old_address_dies(tmp_path, entry_point):
    with isolated_versioned_app_env(tmp_path, f"b32-fa-{entry_point}.db") as env:
        usuario_id = _seed_student()
        login_admin(env["client"])
        old_link = _issue(usuario_id, PURPOSE_FIRST_ACCESS)
        before = _credential(usuario_id)
        assert _usable(old_link, PURPOSE_FIRST_ACCESS)

        response = ENTRY_POINTS[entry_point](env["client"], usuario_id)

        assert response.status_code == 302
        assert _email(usuario_id) == NEW
        assert not _usable(old_link, PURPOSE_FIRST_ACCESS)
        # Password hash, estado (still pending), acesso_ativo and auth_version.
        assert _credential(usuario_id) == before
        # The old mailbox's link cannot set a password over HTTP either.
        assert _redeem(env["client"], PURPOSE_FIRST_ACCESS, old_link).status_code == 200
        assert _credential(usuario_id) == before


@pytest.mark.parametrize("entry_point", sorted(ENTRY_POINTS))
def test_password_reset_link_to_the_old_address_dies(tmp_path, entry_point):
    with isolated_versioned_app_env(tmp_path, f"b32-pr-{entry_point}.db") as env:
        usuario_id = _seed_student(personal=True)
        login_admin(env["client"])
        old_link = _issue(usuario_id, PURPOSE_PASSWORD_RESET)
        before = _credential(usuario_id)

        response = ENTRY_POINTS[entry_point](env["client"], usuario_id)

        assert response.status_code == 302
        assert not _usable(old_link, PURPOSE_PASSWORD_RESET)
        assert _credential(usuario_id) == before  # still personal, same hash
        assert _redeem(env["client"], PURPOSE_PASSWORD_RESET, old_link).status_code == 200
        assert _credential(usuario_id) == before


def test_a_link_issued_after_the_change_works_normally(tmp_path):
    with isolated_versioned_app_env(tmp_path, "b32-new-link.db") as env:
        usuario_id = _seed_student()
        login_admin(env["client"])
        old_link = _issue(usuario_id, PURPOSE_FIRST_ACCESS)
        assert _editar_aluno(env["client"], usuario_id, NEW).status_code == 302

        new_link = _issue(usuario_id, PURPOSE_FIRST_ACCESS)

        assert _usable(new_link, PURPOSE_FIRST_ACCESS)
        assert _redeem(env["client"], PURPOSE_FIRST_ACCESS, new_link).status_code == 302
        assert _credential(usuario_id)["estado"] == "personal"
        assert not _usable(old_link, PURPOSE_FIRST_ACCESS)


def test_self_service_student_change_retires_links_without_signing_out(tmp_path):
    with isolated_versioned_app_env(tmp_path, "b32-aluno-dados.db") as env:
        identity = login_student(env["client"])
        usuario_id = identity["usuario_id"]
        old_link = _issue(usuario_id, PURPOSE_PASSWORD_RESET)
        before = _credential(usuario_id)

        response = env["client"].post(
            "/aluno/meus_dados",
            data={
                "nome": "Aluno Base Versionado",
                "email": "aluno.novo@example.com",
                "matricula": "PPA.TESTE.0001",
                "senha": "",
            },
        )

        assert response.status_code == 302
        assert not _usable(old_link, PURPOSE_PASSWORD_RESET)
        assert _credential(usuario_id) == before
        # Same auth_version: the student's own session is still valid.
        assert env["client"].get("/aluno/meus_dados").status_code == 200


def test_self_service_admin_change_retires_links_without_signing_out(tmp_path):
    with isolated_versioned_app_env(tmp_path, "b32-admin-dados.db") as env:
        with main.app.app_context():
            conn = _conn()
            usuario_id = create_usuario_with_access_level(
                conn, "Outro Admin", "outro.admin@example.com", hash_password("Admin#2026"),
                "admin", "admin_total", credential_state=CREDENTIAL_STATE_PERSONAL,
            ).lastrowid
            conn.commit()
        with env["client"].session_transaction() as session:
            session.update(user_id=usuario_id, user_type="admin", user_name="Outro Admin")
            stamp_auth_version(session)
        old_link = _issue(usuario_id, PURPOSE_PASSWORD_RESET)
        before = _credential(usuario_id)

        response = env["client"].post(
            "/admin/meus_dados",
            data={"nome": "Outro Admin", "email": "outro.novo@example.com", "senha": ""},
        )

        assert response.status_code == 302
        assert not _usable(old_link, PURPOSE_PASSWORD_RESET)
        assert _credential(usuario_id) == before
        assert env["client"].get("/admin/meus_dados").status_code == 200


# --- what does NOT retire a link ---------------------------------------------


@pytest.mark.parametrize(
    "submitted",
    (OLD, "OLD@Example.COM", f"  {OLD} "),
    ids=("same", "case-only", "padded"),
)
def test_saving_the_same_mailbox_keeps_the_link(tmp_path, submitted):
    """SGAA e-mail identity is case- and whitespace-insensitive everywhere
    (LOWER(email) lookups, Acesso lowercases), so rewriting the same mailbox
    does not kill the link sitting in it."""
    with isolated_versioned_app_env(tmp_path, "b32-same.db") as env:
        usuario_id = _seed_student()
        login_admin(env["client"])
        link = _issue(usuario_id, PURPOSE_FIRST_ACCESS)

        assert _editar_aluno(env["client"], usuario_id, submitted).status_code == 302
        assert _import(env["client"], [("Aluna Existente", OLD, "EX-0001")]).status_code == 302

        assert _usable(link, PURPOSE_FIRST_ACCESS)


def test_a_revoked_account_stays_revoked_after_an_email_change(tmp_path):
    with isolated_versioned_app_env(tmp_path, "b32-revoked.db") as env:
        usuario_id = _seed_student(personal=True)
        with main.app.app_context():
            conn = _conn()
            set_usuario_access_active(conn, usuario_id, False)
            conn.commit()
        login_admin(env["client"])
        before = _credential(usuario_id)
        assert before["acesso_ativo"] == 0

        assert _editar_aluno(env["client"], usuario_id, NEW).status_code == 302

        assert _email(usuario_id) == NEW
        assert _credential(usuario_id) == before


# --- rollback: a refused change leaves the link exactly as it was -------------


def _other_account(email="outra@example.com", matricula="EX-0002") -> int:
    return _seed_student(email=email, matricula=matricula)


ROLLBACKS = {
    "editar-aluno-duplicate": lambda client, uid: _editar_aluno(client, uid, "outra@example.com"),
    "editar-aluno-invalid": lambda client, uid: _editar_aluno(client, uid, "new@example"),
    # Row 2's matrícula and e-mail belong to two different students: the
    # import fails AFTER row 1 already changed the e-mail in the transaction.
    "import-later-row-conflict": lambda client, uid: _import(
        client,
        [("Aluna Existente", NEW, "EX-0001"), ("Conflito", "outra@example.com", "EX-0003")],
    ),
    "editar-turma-later-row-invalid": lambda client, uid: _editar_turma(
        client,
        [("Aluna Existente", NEW, "EX-0001"), ("Outra Pessoa", "outra@example", "EX-0002")],
    ),
    "acesso-duplicate": lambda client, uid: _acesso(client, uid, "outra@example.com"),
}


@pytest.mark.parametrize("case", sorted(ROLLBACKS))
def test_a_refused_change_leaves_the_link_valid(tmp_path, case):
    with isolated_versioned_app_env(tmp_path, f"b32-rollback-{case}.db") as env:
        usuario_id = _seed_student()
        _other_account()
        _other_account("terceira@example.com", "EX-0003")
        login_admin(env["client"])
        link = _issue(usuario_id, PURPOSE_FIRST_ACCESS)
        with main.app.app_context():
            tokens_before = [tuple(r) for r in _conn().execute("SELECT * FROM senha_tokens ORDER BY id")]

        ROLLBACKS[case](env["client"], usuario_id)

        assert _email(usuario_id) == OLD
        assert _usable(link, PURPOSE_FIRST_ACCESS)
        with main.app.app_context():
            assert [tuple(r) for r in _conn().execute("SELECT * FROM senha_tokens ORDER BY id")] == tokens_before


# --- root ---------------------------------------------------------------------


def test_root_protections_and_root_links_are_unchanged(tmp_path):
    with isolated_versioned_app_env(tmp_path, "b32-root.db") as env:
        login_admin(env["client"])
        with main.app.app_context():
            root_id = resolve_root_admin_id(_conn())
        root_link = _issue(root_id, PURPOSE_PASSWORD_RESET)
        before = _credential(root_id)

        # Acesso still refuses to move the root address.
        response = env["client"].post(
            "/admin/acesso/salvar",
            data={
                "usuario_id": str(root_id),
                "nome": "Administrador",
                "email": "someone.else@example.com",
                "nivel_acesso": "admin_total",
                "senha": "",
            },
        )
        assert response.status_code == 302
        with env["client"].session_transaction() as session:
            assert (
                "error",
                "O e-mail do administrador raiz não pode ser alterado por esta tela.",
            ) in session.get("_flashes", [])
        # Imported student data cannot target the root account.
        _import(env["client"], [("Intruso", root_admin_email(), "EX-7777")])

        assert _email(root_id) == root_admin_email()
        assert _usable(root_link, PURPOSE_PASSWORD_RESET)
        assert _credential(root_id) == before


def test_root_address_migration_retires_old_links_and_nothing_else(monkeypatch):
    from tests.test_root_admin_contract import TEST_ROOT_ADMIN_EMAIL, _canonical_like_connection

    monkeypatch.setenv("APP_BOOTSTRAP_ADMIN_EMAIL", TEST_ROOT_ADMIN_EMAIL)
    conn = _canonical_like_connection()
    root_id = resolve_root_admin_id(conn)
    link, _ = issue_password_token(conn, root_id, PURPOSE_PASSWORD_RESET)
    conn.commit()
    credential_before = dict(
        conn.execute("SELECT * FROM usuario_credenciais WHERE usuario_id=?", (root_id,)).fetchone()
    )

    assert migrate_root_admin_email(conn)["migrated"] is True
    conn.commit()

    assert resolve_password_token(conn, link, purpose=PURPOSE_PASSWORD_RESET) is None
    assert dict(
        conn.execute("SELECT * FROM usuario_credenciais WHERE usuario_id=?", (root_id,)).fetchone()
    ) == credential_before
    assert resolve_root_admin_id(conn) == root_id


# --- the helper and its single-writer contract --------------------------------


def test_helper_reports_the_change_and_leaves_consumed_tokens_alone(tmp_path):
    with isolated_versioned_app_env(tmp_path, "b32-helper.db"):
        usuario_id = _seed_student()
        link = _issue(usuario_id, PURPOSE_FIRST_ACCESS)
        with main.app.app_context():
            conn = _conn()
            version = get_usuario_auth_version(conn, usuario_id)
            assert set_usuario_email(conn, usuario_id, "Old@Example.com") is False
            assert resolve_password_token(conn, link, purpose=PURPOSE_FIRST_ACCESS) is not None
            assert set_usuario_email(conn, usuario_id, NEW) is True
            assert resolve_password_token(conn, link, purpose=PURPOSE_FIRST_ACCESS) is None
            assert get_usuario_auth_version(conn, usuario_id) == version
            conn.rollback()
            assert _email(usuario_id) == OLD


def test_no_other_code_writes_the_account_email():
    """A future writer that bypassed the helper would silently reopen UI-B32."""
    pattern = re.compile(r"UPDATE\s+usuarios\s+SET[^\"']*\bemail\b", re.IGNORECASE)
    offenders = []
    for path in [PROJECT_ROOT / "main.py", *(PROJECT_ROOT / "app").rglob("*.py")]:
        if "__pycache__" in path.parts:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if pattern.search(line):
                offenders.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}:{number}")
    assert [item for item in offenders if not item.startswith("app/user_accounts.py:")] == []
    assert len(offenders) == 1
