"""Root administrator identity, break-glass recovery, and lockout protection.

The flaw this closes: the one account able to administer everything else can
be left without a usable password credential -- ``pending`` since prod-1/v11,
which is exactly where a root administrator lands when its database migrated
with the retired ``default_passwords_enabled`` switch off. The root
administrator therefore has a second, independent authentication path -- and
must not be removable, revocable or demotable through ordinary access
management.

Everything here runs on disposable databases. The canonical database is never
opened for writing, and the break-glass credential is never sent anywhere.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

import main
from app.root_admin import (
    DEFAULT_ROOT_ADMIN_EMAIL,
    LEGACY_ROOT_ADMIN_EMAIL,
    RootAdminEmailCollision,
    is_root_admin,
    migrate_root_admin_email,
    resolve_root_admin_id,
    root_admin_email,
    root_master_key_configured,
    verify_root_master_key,
)
from app.security.passwords import check_password, hash_password
from app.user_accounts import (
    CREDENTIAL_STATE_DEFAULT,
    CREDENTIAL_STATE_PENDING,
    CREDENTIAL_STATE_PERSONAL,
    create_usuario_with_access_level,
)
from tests.root_admin_test_config import TEST_ROOT_ADMIN_EMAIL, TEST_ROOT_MASTER_KEY
from tests.versioned_test_support import isolated_versioned_app_env


ROOT = Path(__file__).resolve().parents[1]
# Synthetic: tests/conftest.py configures APP_ROOT_MASTER_KEY_HASH from it.
MASTER_KEY = TEST_ROOT_MASTER_KEY
CONFIGURED_DEFAULT = "admin123"


# ----------------------------------------------------------------- helpers


def _make_root_pending() -> None:
    """The canonical post-v11 shape: root holds no usable password credential."""
    with main.app.app_context():
        conn = main.get_db_connection()
        root_id = resolve_root_admin_id(conn)
        if root_id is not None:
            conn.execute(
                "UPDATE usuario_credenciais SET estado=? WHERE usuario_id=?",
                (CREDENTIAL_STATE_PENDING, root_id),
            )
            conn.commit()


def _set_root_state(state: str) -> None:
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "UPDATE usuario_credenciais SET estado=? WHERE usuario_id=?",
            (state, resolve_root_admin_id(conn)),
        )
        conn.commit()


def _root_id() -> int | None:
    with main.app.app_context():
        return resolve_root_admin_id(main.get_db_connection())


@pytest.fixture(autouse=True)
def _isolate_login_rate_limiter():
    """Keep this module's many login attempts out of the shared limiter.

    ``_login_attempts`` / ``_login_attempts_by_account`` are module-level dicts
    keyed by IP and account, and every test client shares 127.0.0.1. Without
    this, a file that deliberately exercises wrong passwords would leave later
    suites rate-limited (observed: an unrelated login asserting 200 got 429).
    """
    from app.auth import _login_attempts, _login_attempts_by_account

    _login_attempts.clear()
    _login_attempts_by_account.clear()
    yield
    _login_attempts.clear()
    _login_attempts_by_account.clear()


def _login(client, email: str, senha: str) -> int | None:
    """Attempt a real login; return the authenticated usuarios.id or None.

    The limiter is reset per attempt so each assertion is about credentials.
    That the limiter still guards the master-key branch is asserted separately,
    by ``test_master_key_login_is_rate_limited_like_any_other``.
    """
    from app.auth import _login_attempts, _login_attempts_by_account

    _login_attempts.clear()
    _login_attempts_by_account.clear()
    client.get("/logout")
    client.post("/login", data={"email": email, "senha": senha}, follow_redirects=False)
    with client.session_transaction() as session:
        return session.get("user_id")


def _seed_admin(email: str, senha: str) -> int:
    with main.app.app_context():
        conn = main.get_db_connection()
        cursor = create_usuario_with_access_level(
            conn, "Segundo Admin", email, hash_password(senha), "admin", "admin_total",
            credential_state=CREDENTIAL_STATE_PERSONAL,
        )
        conn.commit()
        return int(cursor.lastrowid)


# ------------------------------------------------------------ 1. IDENTITY


def test_fresh_bootstrap_uses_the_real_root_address(tmp_path):
    with isolated_versioned_app_env(tmp_path, "root-bootstrap.db"):
        with main.app.app_context():
            conn = main.get_db_connection()
            admins = [
                dict(row)
                for row in conn.execute(
                    "SELECT id, email, tipo FROM usuarios WHERE tipo='admin' ORDER BY id"
                )
            ]
        assert admins, "a fresh database must seed an administrator"
        emails = {row["email"] for row in admins}
        assert TEST_ROOT_ADMIN_EMAIL in emails
        assert LEGACY_ROOT_ADMIN_EMAIL not in emails, (
            "a fresh install still creates the fictitious placeholder address"
        )
        assert _root_id() == admins[0]["id"]


def test_root_address_is_configuration_not_a_personal_source_default():
    # The real root address is configured per installation; the source only
    # carries a reserved, non-deliverable placeholder for unconfigured installs.
    assert DEFAULT_ROOT_ADMIN_EMAIL == "root-admin@example.invalid"
    assert DEFAULT_ROOT_ADMIN_EMAIL.endswith(".invalid")
    assert LEGACY_ROOT_ADMIN_EMAIL == "admin@ej.edu.br"
    # The suite runs with its own configured address, and root resolves to it.
    assert root_admin_email() == TEST_ROOT_ADMIN_EMAIL
    source = (ROOT / "app" / "__init__.py").read_text(encoding="utf-8")
    assert 'os.getenv("APP_BOOTSTRAP_ADMIN_EMAIL", "admin@ej.edu.br")' not in source, (
        "the placeholder address is still the shipped bootstrap default"
    )


def test_legacy_installation_keeps_a_root_admin(tmp_path):
    """An already-deployed database must not lose root when the default moves."""
    with isolated_versioned_app_env(tmp_path, "root-legacy.db") as env:
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute(
                "UPDATE usuarios SET email = ? WHERE id = (SELECT MIN(id) FROM usuarios WHERE tipo='admin')",
                (LEGACY_ROOT_ADMIN_EMAIL,),
            )
            conn.commit()
        legacy_id = _root_id()
        assert legacy_id is not None, (
            "moving the shipped default stripped root from an existing install"
        )
        _make_root_pending()
        assert _login(env["client"], LEGACY_ROOT_ADMIN_EMAIL, MASTER_KEY) == legacy_id


def test_a_non_admin_holding_the_root_address_is_never_root(tmp_path):
    """The real collision: an aluno already owns the target address."""
    with isolated_versioned_app_env(tmp_path, "root-collision.db") as env:
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute(
                "UPDATE usuarios SET email = ? WHERE id = (SELECT MIN(id) FROM usuarios WHERE tipo='admin')",
                (LEGACY_ROOT_ADMIN_EMAIL,),
            )
            aluno = create_usuario_with_access_level(
                conn, "Aluno Colisao", TEST_ROOT_ADMIN_EMAIL,
                hash_password("aluno-secret"), "aluno", "usuario",
                credential_state=CREDENTIAL_STATE_PERSONAL,
            )
            conn.commit()
            aluno_id = int(aluno.lastrowid)
            assert not is_root_admin(conn, aluno_id)

        assert _root_id() != aluno_id
        _make_root_pending()
        assert _login(env["client"], TEST_ROOT_ADMIN_EMAIL, MASTER_KEY) is None, (
            "an aluno holding the root address authenticated with the master key"
        )


# ---------------------------------------------------------- 2. MASTER KEY


@pytest.mark.parametrize(
    "state",
    [CREDENTIAL_STATE_PENDING, CREDENTIAL_STATE_DEFAULT, CREDENTIAL_STATE_PERSONAL],
)
def test_master_key_authenticates_root_in_every_credential_state(tmp_path, state):
    with isolated_versioned_app_env(tmp_path, f"root-mk-{state}.db") as env:
        _set_root_state(state)
        root_id = _root_id()
        assert _login(env["client"], root_admin_email(), MASTER_KEY) == root_id


def test_master_key_survives_a_personal_password_change(tmp_path):
    with isolated_versioned_app_env(tmp_path, "root-mk-personal.db") as env:
        _make_root_pending()
        root_id = _root_id()
        email = root_admin_email()

        # Change the root personal password through the ordinary product path.
        client = env["client"]
        assert _login(client, email, MASTER_KEY) == root_id
        response = client.post(
            "/admin/acesso/definir-senha",
            data={"usuario_ids": str(root_id), "nova_senha": "nova-raiz-secreta"},
            follow_redirects=False,
        )
        assert response.status_code in (200, 302, 303)

        with main.app.app_context():
            estado = main.get_db_connection().execute(
                "SELECT estado FROM usuario_credenciais WHERE usuario_id=?", (root_id,)
            ).fetchone()["estado"]
        assert estado == CREDENTIAL_STATE_PERSONAL

        # Both paths now work.
        assert _login(client, email, "nova-raiz-secreta") == root_id
        assert _login(client, email, MASTER_KEY) == root_id, (
            "changing the root personal password disabled the break-glass key"
        )


def test_wrong_password_still_fails_for_root(tmp_path):
    with isolated_versioned_app_env(tmp_path, "root-mk-wrong.db") as env:
        _make_root_pending()
        assert _login(env["client"], root_admin_email(), "not-the-key") is None
        assert _login(env["client"], root_admin_email(), MASTER_KEY.upper()) is None
        assert _login(env["client"], root_admin_email(), "") is None


def test_root_shared_default_obeys_the_credential_state(tmp_path):
    """The master key is the exception; the shared default is not.

    A root whose bootstrap provisioned the default (``default``) may use it;
    once root is ``pending`` the very same stored hash no longer authenticates.
    """
    with isolated_versioned_app_env(tmp_path, "root-default-state.db") as env:
        root_id = _root_id()
        _set_root_state(CREDENTIAL_STATE_DEFAULT)
        assert _login(env["client"], root_admin_email(), CONFIGURED_DEFAULT) == root_id
        _make_root_pending()
        assert _login(env["client"], root_admin_email(), CONFIGURED_DEFAULT) is None
        assert _login(env["client"], root_admin_email(), MASTER_KEY) == root_id


# ------------------------------------------------------------- 3. ROOT ONLY


def test_secondary_admin_cannot_use_the_master_key(tmp_path):
    with isolated_versioned_app_env(tmp_path, "root-second.db") as env:
        _seed_admin("segundo@example.test", "segundo-secret")
        assert _login(env["client"], "segundo@example.test", MASTER_KEY) is None, (
            "a second administrator authenticated with the root break-glass key"
        )
        # Its own password still works, so the account is not simply broken.
        assert _login(env["client"], "segundo@example.test", "segundo-secret") is not None


def test_student_cannot_use_the_master_key(tmp_path):
    with isolated_versioned_app_env(tmp_path, "root-student-mk.db") as env:
        with main.app.app_context():
            conn = main.get_db_connection()
            create_usuario_with_access_level(
                conn, "Aluno", "aluno-mk@example.test", hash_password("aluno-secret"),
                "aluno", "usuario", credential_state=CREDENTIAL_STATE_PERSONAL,
            )
            conn.commit()
        assert _login(env["client"], "aluno-mk@example.test", MASTER_KEY) is None


def test_master_key_is_not_special_cased_by_role():
    """Root-ness is identity, never `nivel_acesso == admin`."""
    source = (ROOT / "app" / "root_admin.py").read_text(encoding="utf-8")
    resolve = re.search(r"def resolve_root_admin_id\(conn\).*?(?=\ndef )", source, re.S)
    assert resolve, "resolve_root_admin_id disappeared"
    assert "nivel_acesso" not in resolve.group(0), (
        "root identity must not be derived from an access level"
    )
    assert "tipo = 'admin'" in resolve.group(0), (
        "root resolution must require an admin row, or an aluno holding the "
        "address would become root"
    )


# ------------------------------------------------------------- 4. SESSION


def test_master_key_login_creates_an_ordinary_authenticated_session(tmp_path):
    with isolated_versioned_app_env(tmp_path, "root-session.db") as env:
        _make_root_pending()
        root_id = _root_id()
        client = env["client"]
        assert _login(client, root_admin_email(), MASTER_KEY) == root_id

        with main.app.app_context():
            expected = int(
                main.get_db_connection().execute(
                    "SELECT auth_version FROM usuario_credenciais WHERE usuario_id=?",
                    (root_id,),
                ).fetchone()["auth_version"]
            )
        with client.session_transaction() as session:
            assert session.get("user_type") == "admin"
            assert session.get("access_level") == "admin_total"
            assert session.get("auth_version") == expected, (
                "the master-key session did not stamp the durable auth_version"
            )
        assert client.get("/admin/acesso").status_code == 200


def test_master_key_session_still_obeys_auth_version_invalidation(tmp_path):
    with isolated_versioned_app_env(tmp_path, "root-authversion.db") as env:
        _make_root_pending()
        root_id = _root_id()
        client = env["client"]
        assert _login(client, root_admin_email(), MASTER_KEY) == root_id
        assert client.get("/admin/acesso").status_code == 200

        # A credential write elsewhere bumps auth_version; the stamped session
        # must stop being accepted.
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute(
                "UPDATE usuario_credenciais SET auth_version = auth_version + 1 WHERE usuario_id=?",
                (root_id,),
            )
            conn.commit()
        response = client.get("/admin/acesso", follow_redirects=False)
        assert response.status_code in (302, 303), (
            "a master-key session bypassed auth_version invalidation"
        )


def test_master_key_login_is_rate_limited_like_any_other(tmp_path):
    source = (ROOT / "app" / "views" / "core.py").read_text(encoding="utf-8")
    login = re.search(r"def login\(\):(.*?)\ndef logout\(\)", source, re.S)
    assert login, "login handler disappeared"
    body = login.group(1)
    limiter = body.index("_login_rate_limited")
    master = body.index("master_key_login")
    assert limiter < master, (
        "the master-key branch runs before the rate limiter, so it is not "
        "covered by it"
    )
    assert body.count("E-mail ou senha") == 1, (
        "the master-key branch must not introduce a distinguishable failure "
        "message"
    )


# ------------------------------------------------------------ 5. SECURITY


def test_master_key_plaintext_is_absent_from_the_repository():
    """The product never carries the secret -- not even the test one."""
    offenders = []
    for path in list((ROOT / "app").rglob("*.py")) + list((ROOT / "templates").rglob("*.html")):
        if MASTER_KEY in path.read_text(encoding="utf-8", errors="replace"):
            offenders.append(path.relative_to(ROOT).as_posix())
    assert not offenders, f"the break-glass plaintext is committed in {offenders}"


def test_source_ships_no_master_key_hash():
    """The break-glass hash is configuration, never a source fallback."""
    import re

    import app.root_admin as root_admin

    assert not hasattr(root_admin, "_DEFAULT_ROOT_MASTER_KEY_HASH")
    offenders = [
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "app").rglob("*.py")
        if re.search(r"pbkdf2:sha256:\d+\$", path.read_text(encoding="utf-8", errors="replace"))
    ]
    assert not offenders, f"a password hash literal is committed in {offenders}"


def test_configured_master_key_hash_verifies_only_the_configured_key():
    assert root_master_key_configured()
    assert verify_root_master_key(MASTER_KEY)
    assert not verify_root_master_key(CONFIGURED_DEFAULT)
    assert not verify_root_master_key(MASTER_KEY + "x")
    assert not verify_root_master_key("")


def test_missing_master_key_hash_disables_only_the_break_glass_path(tmp_path, monkeypatch):
    """No APP_ROOT_MASTER_KEY_HASH: no master key -- and nothing else lost."""
    monkeypatch.delenv("APP_ROOT_MASTER_KEY_HASH", raising=False)
    monkeypatch.delitem(main.app.config, "ROOT_MASTER_KEY_HASH", raising=False)
    assert not root_master_key_configured()
    assert not verify_root_master_key(MASTER_KEY)

    with isolated_versioned_app_env(tmp_path, "root-mk-unconfigured.db") as env:
        client = env["client"]
        root_id = _root_id()
        assert root_id is not None, "root identity must not depend on the master key"

        # The break-glass path is closed in every state, pending included.
        _make_root_pending()
        assert _login(client, root_admin_email(), MASTER_KEY) is None

        # The ordinary personal-password path is untouched.
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute(
                "UPDATE usuarios SET senha=? WHERE id=?",
                (hash_password("raiz-pessoal-secreta"), root_id),
            )
            conn.execute(
                "UPDATE usuario_credenciais SET estado=? WHERE usuario_id=?",
                (CREDENTIAL_STATE_PERSONAL, root_id),
            )
            conn.commit()
            # ...and so is every root protection.
            assert is_root_admin(conn, root_id)
        assert _login(client, root_admin_email(), "raiz-pessoal-secreta") == root_id
        assert _login(client, root_admin_email(), MASTER_KEY) is None


def test_master_key_never_reaches_the_database_or_the_page(tmp_path):
    with isolated_versioned_app_env(tmp_path, "root-nosecret.db") as env:
        _make_root_pending()
        client = env["client"]
        assert _login(client, root_admin_email(), MASTER_KEY) == _root_id()
        html = client.get("/admin/acesso").get_data(as_text=True)
        assert MASTER_KEY not in html, "the recovery credential is rendered"

        with main.app.app_context():
            conn = main.get_db_connection()
            defaults = [
                str(row["senha_padrao"])
                for row in conn.execute("SELECT senha_padrao FROM configuracoes_acesso")
            ]
            assert MASTER_KEY not in defaults, (
                "the recovery credential was written into configuracoes_acesso"
            )
            # It must not have become the root's stored password either.
            stored = str(
                conn.execute(
                    "SELECT senha FROM usuarios WHERE id=?", (_root_id(),)
                ).fetchone()["senha"]
            )
            assert not check_password(stored, MASTER_KEY), (
                "the master key was persisted as the root's ordinary password"
            )


def test_master_key_login_is_not_logged(tmp_path, caplog):
    import logging

    with isolated_versioned_app_env(tmp_path, "root-nolog.db") as env:
        _make_root_pending()
        with caplog.at_level(logging.DEBUG):
            assert _login(env["client"], root_admin_email(), MASTER_KEY) == _root_id()
        emitted = "\n".join(record.getMessage() for record in caplog.records)
        assert MASTER_KEY not in emitted, "the recovery credential reached the logs"


def test_panel_announces_nothing_about_the_recovery_path(tmp_path):
    """The break-glass path is an authentication contract, not a panel notice.

    Rejected at acceptance: the Senhas padrão panel must carry no root-recovery
    row at all -- not the text, not an icon, not a wrapper. The security
    behaviour it used to describe is asserted elsewhere in this file and is
    unaffected by its absence.
    """
    with isolated_versioned_app_env(tmp_path, "root-indication.db") as env:
        _make_root_pending()
        client = env["client"]
        _login(client, root_admin_email(), MASTER_KEY)
        html = client.get("/admin/acesso").get_data(as_text=True)

        assert MASTER_KEY not in html
        for banned in (
            "Administrador raiz protegido",
            "acesso de recuperação",
            "root_admin_present",
            "break-glass",
        ):
            assert banned not in html, f"the rejected root notice is back: {banned!r}"

        # The panel is exactly its parts -- recovery status, the configured
        # values, one Salvar -- and (since prod-1/v11) no activation switch.
        panel = html.split('class="access-defaults-head"', 1)[1].split("</form>", 1)[0]
        assert "Ativar senhas padrão" not in panel
        assert "Recuperação por e-mail:" in panel
        assert panel.count("access-defaults-footer") == 1
        assert "form-note" not in panel, (
            "a note row is rendered inside the Senhas padrão panel"
        )
        # The footer follows the cards directly -- no leftover row, no empty
        # strip where the rejected note used to sit.
        assert re.search(
            r"</div>\s*</div>\s*<div class=\"access-defaults-footer\">", panel
        ), "something is rendered between the default-password cards and the footer"


# --------------------------------------------------- 6. LOCKOUT PROTECTION


def test_root_cannot_be_deleted(tmp_path):
    with isolated_versioned_app_env(tmp_path, "root-nodelete.db") as env:
        _make_root_pending()
        root_id = _root_id()
        client = env["client"]
        _login(client, root_admin_email(), MASTER_KEY)

        # Delete it while authenticated as somebody else, so the self-delete
        # guard is not what refuses.
        other_id = _seed_admin("outro@example.test", "outro-secret")
        _login(client, "outro@example.test", "outro-secret")

        response = client.post(f"/admin/acesso/{root_id}/deletar", follow_redirects=True)
        assert response.status_code == 200
        assert "administrador raiz não pode ser excluído" in response.get_data(as_text=True)

        with main.app.app_context():
            assert main.get_db_connection().execute(
                "SELECT 1 FROM usuarios WHERE id=?", (root_id,)
            ).fetchone() is not None, "the root administrator was deleted"
        assert other_id != root_id


def test_root_cannot_be_revoked(tmp_path):
    with isolated_versioned_app_env(tmp_path, "root-norevoke.db") as env:
        _make_root_pending()
        root_id = _root_id()
        client = env["client"]
        _seed_admin("outro2@example.test", "outro-secret")
        _login(client, "outro2@example.test", "outro-secret")

        response = client.post(
            f"/admin/acesso/{root_id}/deletar", data={"modo": "revogar"}, follow_redirects=True
        )
        assert "administrador raiz não pode ser excluído nem revogado" in response.get_data(as_text=True)

        # Still able to recover.
        assert _login(client, root_admin_email(), MASTER_KEY) == root_id


def test_root_cannot_be_demoted(tmp_path):
    with isolated_versioned_app_env(tmp_path, "root-nodemote.db") as env:
        _make_root_pending()
        root_id = _root_id()
        client = env["client"]
        _login(client, root_admin_email(), MASTER_KEY)

        response = client.post(
            "/admin/acesso/salvar",
            data={
                "usuario_id": str(root_id),
                "nome": "Administrador",
                "email": root_admin_email(),
                "nivel_acesso": "consultivo",
            },
            follow_redirects=True,
        )
        assert "não pode ser rebaixado" in response.get_data(as_text=True)
        with main.app.app_context():
            nivel = main.get_db_connection().execute(
                "SELECT nivel_acesso FROM usuarios WHERE id=?", (root_id,)
            ).fetchone()["nivel_acesso"]
        assert nivel == "admin_total", "the root administrator was demoted"


def test_root_email_cannot_be_changed_through_access_management(tmp_path):
    with isolated_versioned_app_env(tmp_path, "root-noemail.db") as env:
        _make_root_pending()
        root_id = _root_id()
        client = env["client"]
        _login(client, root_admin_email(), MASTER_KEY)

        response = client.post(
            "/admin/acesso/salvar",
            data={
                "usuario_id": str(root_id),
                "nome": "Administrador",
                "email": "sequestrado@example.test",
                "nivel_acesso": "admin_total",
            },
            follow_redirects=True,
        )
        assert "e-mail do administrador raiz não pode ser alterado" in response.get_data(as_text=True)
        with main.app.app_context():
            email = main.get_db_connection().execute(
                "SELECT email FROM usuarios WHERE id=?", (root_id,)
            ).fetchone()["email"]
        assert email == root_admin_email()
        assert _login(client, root_admin_email(), MASTER_KEY) == root_id


def test_root_personal_password_change_is_still_allowed(tmp_path):
    """Protection must not turn into a straitjacket."""
    with isolated_versioned_app_env(tmp_path, "root-pwchange.db") as env:
        _make_root_pending()
        root_id = _root_id()
        client = env["client"]
        _login(client, root_admin_email(), MASTER_KEY)
        response = client.post(
            "/admin/acesso/salvar",
            data={
                "usuario_id": str(root_id),
                "nome": "Administrador",
                "email": root_admin_email(),
                "nivel_acesso": "admin_total",
                "senha": "outra-raiz",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert _login(client, root_admin_email(), "outra-raiz") == root_id
        assert _login(client, root_admin_email(), MASTER_KEY) == root_id


def test_root_delete_affordance_is_withheld_in_the_ui(tmp_path):
    with isolated_versioned_app_env(tmp_path, "root-ui.db") as env:
        _make_root_pending()
        root_id = _root_id()
        client = env["client"]
        _login(client, root_admin_email(), MASTER_KEY)
        html = client.get("/admin/acesso").get_data(as_text=True)

        row = re.search(
            r'data-user-id="%d"[^>]*' % root_id, html
        )
        assert row, "the root row is not rendered"
        assert f"/admin/acesso/{root_id}/deletar" not in html, (
            "the UI still offers a delete URL for the root administrator"
        )


# ---------------------------------------------------------- 7. MIGRATION


def _canonical_like_connection() -> sqlite3.Connection:
    from app.prod1_schema import bootstrap_prod1_schema

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    bootstrap_prod1_schema(conn)
    create_usuario_with_access_level(
        conn, "Administrador", LEGACY_ROOT_ADMIN_EMAIL, hash_password("admin123"),
        "admin", "admin_total", credential_state=CREDENTIAL_STATE_DEFAULT,
    )
    conn.commit()
    return conn


def test_migration_preserves_identity_and_dependencies(monkeypatch):
    monkeypatch.setenv("APP_BOOTSTRAP_ADMIN_EMAIL", TEST_ROOT_ADMIN_EMAIL)
    conn = _canonical_like_connection()
    root_id = resolve_root_admin_id(conn)
    before = dict(conn.execute("SELECT * FROM usuarios WHERE id=?", (root_id,)).fetchone())
    credential_before = dict(
        conn.execute("SELECT * FROM usuario_credenciais WHERE usuario_id=?", (root_id,)).fetchone()
    )

    result = migrate_root_admin_email(conn)
    conn.commit()

    assert result["migrated"] is True
    after = dict(conn.execute("SELECT * FROM usuarios WHERE id=?", (root_id,)).fetchone())
    assert after["id"] == before["id"] == root_id, "usuarios.id changed"
    assert after["email"] == TEST_ROOT_ADMIN_EMAIL
    for column in ("nome", "senha", "tipo", "nivel_acesso"):
        assert after[column] == before[column], f"{column} changed during migration"

    credential_after = dict(
        conn.execute("SELECT * FROM usuario_credenciais WHERE usuario_id=?", (root_id,)).fetchone()
    )
    assert credential_after == credential_before, (
        "an address change must not touch the credential or auth_version"
    )
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert resolve_root_admin_id(conn) == root_id


def test_migration_refuses_a_collision_without_mutating(monkeypatch):
    monkeypatch.setenv("APP_BOOTSTRAP_ADMIN_EMAIL", TEST_ROOT_ADMIN_EMAIL)
    conn = _canonical_like_connection()
    root_id = resolve_root_admin_id(conn)
    holder = create_usuario_with_access_level(
        conn, "Aluno Teste 2", TEST_ROOT_ADMIN_EMAIL, hash_password("x"),
        "aluno", "usuario", credential_state=CREDENTIAL_STATE_PERSONAL,
    )
    conn.commit()
    holder_id = int(holder.lastrowid)

    with pytest.raises(RootAdminEmailCollision) as captured:
        migrate_root_admin_email(conn)

    assert captured.value.holder_id == holder_id
    assert captured.value.holder_tipo == "aluno"
    assert str(
        conn.execute("SELECT email FROM usuarios WHERE id=?", (root_id,)).fetchone()["email"]
    ) == LEGACY_ROOT_ADMIN_EMAIL, "the root address was mutated despite the collision"
    assert str(
        conn.execute("SELECT email FROM usuarios WHERE id=?", (holder_id,)).fetchone()["email"]
    ) == TEST_ROOT_ADMIN_EMAIL, "the colliding account was silently reassigned"


# ---------------------------------------------------------- 8. REVOCATION


def _seed_uploader(client) -> int:
    response = client.post(
        "/admin/acesso/salvar",
        data={
            "nome": "Com Historico", "email": "historico@example.test",
            "nivel_acesso": "administrativo", "senha": "hist-secret",
        },
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    with main.app.app_context():
        conn = main.get_db_connection()
        usuario_id = int(
            conn.execute(
                "SELECT id FROM usuarios WHERE email='historico@example.test'"
            ).fetchone()["id"]
        )
        conn.execute(
            "INSERT INTO admin_arquivos (titulo,filename,uploader_user_id) VALUES (?,?,?)",
            ("Enviado por este acesso", "f.pdf", usuario_id),
        )
        conn.commit()
    return usuario_id


def test_revocation_ends_login_but_preserves_the_record(tmp_path):
    with isolated_versioned_app_env(tmp_path, "revoke-basic.db") as env:
        client = env["client"]
        _login(client, root_admin_email(), MASTER_KEY)
        usuario_id = _seed_uploader(client)

        assert _login(client, "historico@example.test", "hist-secret") == usuario_id
        _login(client, root_admin_email(), MASTER_KEY)

        response = client.post(
            f"/admin/acesso/{usuario_id}/deletar", data={"modo": "revogar"}, follow_redirects=True
        )
        assert "Acesso revogado" in response.get_data(as_text=True)

        with main.app.app_context():
            conn = main.get_db_connection()
            assert conn.execute(
                "SELECT 1 FROM usuarios WHERE id=?", (usuario_id,)
            ).fetchone() is not None, "revocation deleted the row it was meant to preserve"
            assert int(
                conn.execute(
                    "SELECT COUNT(*) FROM admin_arquivos WHERE uploader_user_id=?", (usuario_id,)
                ).fetchone()[0]
            ) == 1, "revocation destroyed the upload attribution"
            assert conn.execute("PRAGMA foreign_key_check").fetchall() == []

        assert _login(client, "historico@example.test", "hist-secret") is None, (
            "the revoked account can still authenticate"
        )


def test_revocation_kills_sessions_and_pending_tokens(tmp_path):
    with isolated_versioned_app_env(tmp_path, "revoke-sessions.db") as env:
        client = env["client"]
        _login(client, root_admin_email(), MASTER_KEY)
        usuario_id = _seed_uploader(client)

        with main.app.app_context():
            conn = main.get_db_connection()
            before_version = int(
                conn.execute(
                    "SELECT auth_version FROM usuario_credenciais WHERE usuario_id=?", (usuario_id,)
                ).fetchone()["auth_version"]
            )
            from app.password_tokens import PURPOSE_FIRST_ACCESS, issue_password_token

            issue_password_token(conn, usuario_id, PURPOSE_FIRST_ACCESS)
            conn.commit()

        client.post(
            f"/admin/acesso/{usuario_id}/deletar", data={"modo": "revogar"}, follow_redirects=True
        )

        with main.app.app_context():
            conn = main.get_db_connection()
            after_version = int(
                conn.execute(
                    "SELECT auth_version FROM usuario_credenciais WHERE usuario_id=?", (usuario_id,)
                ).fetchone()["auth_version"]
            )
            live_tokens = int(
                conn.execute(
                    "SELECT COUNT(*) FROM senha_tokens WHERE usuario_id=? "
                    "AND consumed_at IS NULL AND invalidated_at IS NULL",
                    (usuario_id,),
                ).fetchone()[0]
            )
        assert after_version > before_version, "revocation did not invalidate live sessions"
        assert live_tokens == 0, "a pending password token survived revocation"


def test_excluir_acesso_is_a_revocation_for_a_referenced_account(tmp_path):
    """One access-removal model: never a physical delete, never an FK error."""
    with isolated_versioned_app_env(tmp_path, "revoke-hint.db") as env:
        client = env["client"]
        _login(client, root_admin_email(), MASTER_KEY)
        usuario_id = _seed_uploader(client)

        response = client.post(f"/admin/acesso/{usuario_id}/deletar", follow_redirects=True)
        body = response.get_data(as_text=True)
        assert "Acesso revogado" in body
        assert "FOREIGN KEY constraint failed" not in body
        with main.app.app_context():
            conn = main.get_db_connection()
            assert conn.execute(
                "SELECT 1 FROM usuarios WHERE id=?", (usuario_id,)
            ).fetchone() is not None
            assert int(
                conn.execute(
                    "SELECT acesso_ativo FROM usuario_credenciais WHERE usuario_id=?",
                    (usuario_id,),
                ).fetchone()["acesso_ativo"]
            ) == 0
