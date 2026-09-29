"""UI-B36: the root administrator cannot move its own e-mail from "Meus dados".

Root identity IS an address: ``resolve_root_admin_id`` looks for the admin
holding the configured ``BOOTSTRAP_ADMIN_EMAIL``. Admin > Meus dados used to
save whatever address root typed, after which nothing resolved as root any
more -- root protections and the master-key path were gone until somebody put
the address back. Acesso already refused that move; Meus dados did not.

Now, for root only, Meus dados shows the address read-only (the same shared
treatment as the student's Matrícula/Turma) and the server refuses a crafted
change with Acesso's existing message, writing nothing. Every other field and
the password behave exactly as before, ordinary accounts still change their
own address (with UI-B32's link retirement), and ``migrate_root_admin_email``
stays the one supported way to move root.

Everything runs on disposable databases with the synthetic root configuration
from ``tests/root_admin_test_config.py``; ``.env`` is never read or written.
"""

from __future__ import annotations

import re
import uuid

import pytest

import main
from app.password_tokens import PURPOSE_PASSWORD_RESET, issue_password_token, resolve_password_token
from app.root_admin import migrate_root_admin_email, resolve_root_admin_id, root_admin_email
from app.security.passwords import check_password, hash_password
from app.user_accounts import CREDENTIAL_STATE_PERSONAL, create_usuario_with_access_level
from tests.canonical_request_test_support import student_identity
from tests.root_admin_test_config import TEST_ROOT_ADMIN_EMAIL, TEST_ROOT_MASTER_KEY
from tests.session_support import stamp_auth_version
from tests.versioned_test_support import isolated_versioned_app_env


REFUSAL = "O e-mail do administrador raiz não pode ser alterado por esta tela."
EMAIL_INPUT = re.compile(r'<input\b[^>]*\bname="email"[^>]*>')


@pytest.fixture
def env(tmp_path):
    import app.auth as auth

    auth._login_attempts.clear()
    auth._login_attempts_by_account.clear()
    try:
        with isolated_versioned_app_env(tmp_path, "ui-b36.db") as environment:
            yield environment
    finally:
        auth._login_attempts.clear()
        auth._login_attempts_by_account.clear()


# ----------------------------------------------------------------- helpers


def _conn():
    return main.get_db_connection()


def _root_id() -> int:
    with main.app.app_context():
        root_id = resolve_root_admin_id(_conn())
    assert root_id is not None
    return root_id


def _login(client, email: str, senha: str) -> int | None:
    import app.auth as auth

    auth._login_attempts.clear()
    auth._login_attempts_by_account.clear()
    client.get("/logout")
    client.post("/login", data={"email": email, "senha": senha}, follow_redirects=False)
    with client.session_transaction() as session:
        return session.get("user_id")


def _login_root(client) -> int:
    root_id = _root_id()
    assert _login(client, root_admin_email(), TEST_ROOT_MASTER_KEY) == root_id
    return root_id


def _issue_reset(usuario_id: int) -> str:
    with main.app.app_context():
        conn = _conn()
        raw, _row = issue_password_token(conn, usuario_id, PURPOSE_PASSWORD_RESET)
        conn.commit()
    return raw


def _link_usable(raw: str) -> bool:
    with main.app.app_context():
        return resolve_password_token(_conn(), raw, purpose=PURPOSE_PASSWORD_RESET) is not None


def _snapshot(usuario_id: int) -> dict:
    with main.app.app_context():
        conn = _conn()
        user = conn.execute(
            "SELECT nome, email, senha, tipo, nivel_acesso FROM usuarios WHERE id=?", (usuario_id,)
        ).fetchone()
        cred = conn.execute(
            "SELECT estado, auth_version, acesso_ativo FROM usuario_credenciais WHERE usuario_id=?",
            (usuario_id,),
        ).fetchone()
        tokens = [tuple(row) for row in conn.execute(
            "SELECT id, purpose, consumed_at, invalidated_at FROM senha_tokens WHERE usuario_id=? ORDER BY id",
            (usuario_id,),
        )]
    return {**dict(user), **dict(cred), "tokens": tokens}


def _post(client, nome: str, email: str, senha: str = ""):
    return client.post(
        "/admin/meus_dados", data={"nome": nome, "email": email, "senha": senha}, follow_redirects=False
    )


def _email_input(html: str) -> str:
    inputs = EMAIL_INPUT.findall(html)
    assert len(inputs) == 1, inputs
    return inputs[0]


def _is_read_only(tag: str) -> bool:
    return (
        re.search(r'\sreadonly\b', tag) is not None
        and 'aria-readonly="true"' in tag
        and 'class="control is-readonly"' in tag
    )


def _ordinary_admin(email: str | None = None) -> tuple[int, str]:
    email = email or f"b36-admin-{uuid.uuid4().hex[:8]}@example.invalid"
    with main.app.app_context():
        conn = _conn()
        uid = int(create_usuario_with_access_level(
            conn, "Admin Comum B36", email, hash_password("Admin#B36"),
            "admin", "admin_total", credential_state=CREDENTIAL_STATE_PERSONAL,
        ).lastrowid)
        conn.commit()
    return uid, email


def _session_as(client, uid: int, user_type: str) -> None:
    with client.session_transaction() as session:
        session.clear()
        session.update(user_id=uid, user_type=user_type, user_name="B36")
        stamp_auth_version(session, uid)


# ------------------------------------------------------------ 1. the page


def test_root_sees_its_email_read_only_and_the_rest_editable(env):
    client = env["client"]
    _login_root(client)

    html = client.get("/admin/meus_dados").get_data(as_text=True)

    email = _email_input(html)
    assert _is_read_only(email), email
    assert f'value="{root_admin_email()}"' in email, "the address must stay visible"
    for name in ("nome", "senha"):
        tag = re.search(rf'<input\b[^>]*\bname="{name}"[^>]*>', html).group(0)
        assert "readonly" not in tag, f"{name} must stay editable for root"


def test_the_read_only_email_copies_the_matricula_sibling(env):
    """Same shared treatment as the form's existing read-only field -- nothing more."""
    client = env["client"]
    _session_as(client, int(student_identity()["usuario_id"]), "aluno")
    matricula = re.search(
        r'<input\b[^>]*\bname="matricula"[^>]*>', client.get("/aluno/meus_dados").get_data(as_text=True)
    ).group(0)
    _login_root(client)
    email = _email_input(client.get("/admin/meus_dados").get_data(as_text=True))

    def shape(tag: str) -> str:
        return re.sub(r'\s(type|name|value)="[^"]*"', "", tag)

    assert shape(email) == shape(matricula)
    assert "title=" not in email


def test_ordinary_admin_and_student_keep_an_editable_email(env):
    client = env["client"]
    uid, _email = _ordinary_admin()
    _session_as(client, uid, "admin")
    admin_email = _email_input(client.get("/admin/meus_dados").get_data(as_text=True))
    assert "readonly" not in admin_email and "is-readonly" not in admin_email

    _session_as(client, int(student_identity()["usuario_id"]), "aluno")
    aluno_email = _email_input(client.get("/aluno/meus_dados").get_data(as_text=True))
    assert "readonly" not in aluno_email and "is-readonly" not in aluno_email


# ---------------------------------------------------- 2. server authority


@pytest.mark.parametrize("target", ("sequestro@example.test", "outra.raiz@example.invalid"))
def test_a_crafted_post_cannot_move_the_root_address(env, target):
    client = env["client"]
    root_id = _login_root(client)
    link = _issue_reset(root_id)
    before = _snapshot(root_id)

    # Everything a hostile form could carry at once: nothing of it may land.
    response = _post(client, "Nome Trocado", target, "Senha-Sequestro-B36")

    assert response.status_code == 200
    assert REFUSAL in response.get_data(as_text=True)
    assert _snapshot(root_id) == before, "the refused submission wrote something"
    assert _link_usable(link), "a refused change must not retire root's links"
    assert _root_id() == root_id, "root no longer resolves"
    assert client.get("/admin/meus_dados").status_code == 200, "root's own session ended"
    assert _login(main.app.test_client(), root_admin_email(), TEST_ROOT_MASTER_KEY) == root_id
    assert _login(main.app.test_client(), target, TEST_ROOT_MASTER_KEY) is None


def test_a_malformed_address_from_root_is_still_reported_as_malformed(env):
    client = env["client"]
    root_id = _login_root(client)
    before = _snapshot(root_id)

    response = _post(client, before["nome"], "raiz@sem-dominio")

    assert response.status_code == 200
    assert "E-mail inválido." in response.get_data(as_text=True)
    assert _snapshot(root_id) == before


@pytest.mark.parametrize("variant", ("upper", "padded"))
def test_resubmitting_the_same_mailbox_never_rewrites_the_stored_address(env, variant):
    client = env["client"]
    root_id = _login_root(client)
    link = _issue_reset(root_id)
    before = _snapshot(root_id)
    submitted = root_admin_email().upper() if variant == "upper" else f"  {root_admin_email()} "

    assert _post(client, "Raiz Renomeada", submitted).status_code == 302

    after = _snapshot(root_id)
    assert after["email"] == before["email"], "root's stored address was rewritten"
    assert after["nome"] == "Raiz Renomeada"
    assert _link_usable(link)
    assert _root_id() == root_id


def test_root_still_updates_its_other_fields(env):
    client = env["client"]
    root_id = _login_root(client)
    link = _issue_reset(root_id)
    before = _snapshot(root_id)

    assert _post(client, "Raiz Com Outro Nome", root_admin_email()).status_code == 302

    after = _snapshot(root_id)
    assert after["nome"] == "Raiz Com Outro Nome"
    for key in ("email", "senha", "estado", "auth_version", "acesso_ativo", "tokens"):
        assert after[key] == before[key], key
    assert _link_usable(link)
    with client.session_transaction() as session:
        assert session["user_name"] == "Raiz Com Outro Nome"


def test_root_password_change_is_unchanged_and_keeps_the_address(env):
    client = env["client"]
    root_id = _login_root(client)
    before = _snapshot(root_id)

    assert _post(client, before["nome"], root_admin_email(), "Raiz-Pessoal-B36").status_code == 302

    after = _snapshot(root_id)
    assert after["email"] == before["email"]
    assert after["estado"] == "personal"
    assert after["auth_version"] == before["auth_version"] + 1
    assert after["acesso_ativo"] == before["acesso_ativo"]
    assert check_password(after["senha"], "Raiz-Pessoal-B36")
    assert client.get("/admin/meus_dados").status_code == 200, "the acting session is restamped"
    assert _login(main.app.test_client(), root_admin_email(), "Raiz-Pessoal-B36") == root_id
    assert _login(main.app.test_client(), root_admin_email(), TEST_ROOT_MASTER_KEY) == root_id, (
        "the master key is independent of root's personal password"
    )


# ------------------------------------------------- 3. ordinary accounts


def test_an_ordinary_admin_still_changes_its_address_and_old_links_die(env):
    client = env["client"]
    uid, old = _ordinary_admin()
    root_id = _root_id()
    _session_as(client, uid, "admin")
    link = _issue_reset(uid)
    before = _snapshot(uid)
    new = f"novo-{uuid.uuid4().hex[:8]}@example.invalid"

    assert _post(client, "Admin Comum B36", new).status_code == 302

    after = _snapshot(uid)
    assert after["email"] == new != old
    assert not _link_usable(link), "UI-B32: a link in the old mailbox must die"
    for key in ("senha", "estado", "auth_version", "acesso_ativo"):
        assert after[key] == before[key], key
    assert client.get("/admin/meus_dados").status_code == 200, "an address is not a credential"
    assert _root_id() == root_id


# --------------------------------------------- 4. the supported root move


def test_the_root_migration_is_still_the_way_to_move_root(env, monkeypatch):
    client = env["client"]
    root_id = _root_id()
    old_link = _issue_reset(root_id)
    before = _snapshot(root_id)
    new_root = "raiz-migrada@sgaa-tests.invalid"
    assert root_admin_email() == TEST_ROOT_ADMIN_EMAIL

    # Offline procedure: move the row while the old address is configured,
    # then point the configuration at the new one.
    with main.app.app_context():
        conn = _conn()
        result = migrate_root_admin_email(conn, target_email=new_root)
        conn.commit()
    assert result["migrated"] is True and result["root_id"] == root_id
    monkeypatch.setitem(main.app.config, "BOOTSTRAP_ADMIN_EMAIL", new_root)
    monkeypatch.setenv("APP_BOOTSTRAP_ADMIN_EMAIL", new_root)

    after = _snapshot(root_id)
    assert after["email"] == new_root
    for key in ("nome", "senha", "tipo", "nivel_acesso", "estado", "auth_version", "acesso_ativo"):
        assert after[key] == before[key], key
    assert not _link_usable(old_link), "UI-B32: the migration retires links in the old mailbox"
    assert _root_id() == root_id
    assert _login(main.app.test_client(), TEST_ROOT_ADMIN_EMAIL, TEST_ROOT_MASTER_KEY) is None
    assert _login(client, new_root, TEST_ROOT_MASTER_KEY) == root_id

    # The lock follows the identity to its new address.
    email = _email_input(client.get("/admin/meus_dados").get_data(as_text=True))
    assert _is_read_only(email) and f'value="{new_root}"' in email
    response = _post(client, after["nome"], TEST_ROOT_ADMIN_EMAIL)
    assert REFUSAL in response.get_data(as_text=True)
    assert _snapshot(root_id)["email"] == new_root


# ------------------------------------------------------ 5. the paint


cdp = pytest.importorskip("tests.cdp_browser_support")
BINARY = cdp.find_chromium()


@pytest.mark.skipif(BINARY is None, reason="no Chromium binary for the browser harness")
def test_root_email_paints_with_the_shared_read_only_tokens(env):
    client = env["client"]
    _login_root(client)
    session = cdp.BrowserSession(client, BINARY)
    try:
        session.goto("/admin/meus_dados")
        state = session.evaluate(
            """(() => {
              const probe = (value) => { const d = document.createElement('div');
                d.style.color = value; d.style.background = value; document.body.appendChild(d);
                const c = getComputedStyle(d); const out = [c.color, c.backgroundColor]; d.remove(); return out; };
              const email = document.querySelector('input[name="email"]');
              const nome = document.querySelector('input[name="nome"]');
              return JSON.stringify({
                readonlyBg: probe('var(--field-readonly-bg)')[1],
                secondary: probe('var(--text-secondary)')[0],
                emailReadOnly: email.readOnly,
                emailCard: getComputedStyle(email.closest('.field-card')).backgroundColor,
                emailColor: getComputedStyle(email).color,
                nomeReadOnly: nome.readOnly,
                nomeCard: getComputedStyle(nome.closest('.field-card')).backgroundColor,
              });
            })()"""
        )
    finally:
        session.close()
    import json

    state = json.loads(state)
    assert state["emailReadOnly"] is True
    assert state["emailCard"] == state["readonlyBg"]
    assert state["emailColor"] == state["secondary"]
    assert state["nomeReadOnly"] is False
    assert state["nomeCard"] != state["readonlyBg"]
