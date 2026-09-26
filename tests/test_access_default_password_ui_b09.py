# coding: utf-8
"""UI-B09: the "Aplicar senha padrão" enablement contract (prod-1/v11 model).

Three things are under test and they are deliberately separated:

1. THE LADDER (``app/access_default_password.py``) -- a pure function of two
   facts, so every cell of the eligibility matrix is pinned directly;

2. THE ENDPOINT (``admin_acesso_resetar_senha``) -- the backend is
   authoritative. Each protected row of the matrix is driven through the real
   route against a real database and the refusal is proved by the *absence* of
   a write, never by the flash alone;

3. THE DESCRIPTOR (``users_payload`` + ``templates/admin_acesso.html``) -- the
   action bar renders the backend's answer and nothing else. The frontend
   assertions read the descriptor the server actually emits, plus the wiring
   in the template, because there is no browser in this environment.

THE GLOBAL SWITCH IS GONE. Until prod-1/v11 a ``default_passwords_enabled``
setting sat above the ladder. It is retired: the only disabled reasons left are
genuine account constraints (root, revoked), and a stale legacy settings row is
proved to have no effect.

THE MATRIX IS TOTAL. Every row that the action bar offers, the endpoint
applies; every row the endpoint refuses, the action bar disables. ``estado`` is
not an input: applying the shared default to a ``pending``, ``personal`` or
``default`` account is the same explicit administrative credential reset --
fresh salt, auth_version bump, tokens killed -- and
``test_list_render_never_verifies_a_password_hash`` guards the consequence that
eligibility never touches PBKDF2.

Every test uses a disposable database. The canonical database is never written.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import werkzeug.security

import main
from app.access_default_password import (
    REASON_REVOKED,
    REASON_ROOT_ADMIN,
    decide_default_password_eligibility,
    default_password_eligibility,
    default_password_eligibility_map,
)
from app.access_onboarding import access_status_for_usuario
from app.password_tokens import PURPOSE_FIRST_ACCESS, issue_password_token
from app.root_admin import resolve_root_admin_id
from app.security.passwords import check_password, hash_password
from app.status_presentation import ACCESS_STATUS_ATIVO, ACCESS_STATUS_PENDENTE
from app.user_accounts import (
    CREDENTIAL_STATE_DEFAULT,
    CREDENTIAL_STATE_PENDING,
    CREDENTIAL_STATE_PERSONAL,
    create_usuario_with_access_level,
    set_usuario_access_active,
    unusable_password_hash,
)
from tests.versioned_test_support import isolated_versioned_app_env


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ACESSO_TEMPLATE = PROJECT_ROOT / "templates" / "admin_acesso.html"
ELIGIBILITY_MODULE = PROJECT_ROOT / "app" / "access_default_password.py"
ACTIONS_FLOAT_CSS = PROJECT_ROOT / "static" / "css" / "components" / "actions-float.css"

#: The profile every seeded account uses, and its shipped configured default.
LEVEL = "consultivo"
CONFIGURED_DEFAULT = "consultivo123"


# --------------------------------------------------------------------------- #
# 1. The ladder, as a pure function
# --------------------------------------------------------------------------- #


def test_root_outranks_revocation():
    for acesso_ativo in (0, 1, None):
        decision = decide_default_password_eligibility(
            is_root_admin=True, acesso_ativo=acesso_ativo
        )
        assert (decision.allowed, decision.reason) == (False, REASON_ROOT_ADMIN)


def test_revoked_and_credential_less_accounts_are_refused():
    for acesso_ativo in (0, None):
        decision = decide_default_password_eligibility(
            is_root_admin=False, acesso_ativo=acesso_ativo
        )
        assert (decision.allowed, decision.reason) == (False, REASON_REVOKED)


def test_ordinary_active_account_is_eligible():
    decision = decide_default_password_eligibility(is_root_admin=False, acesso_ativo=1)
    assert (decision.allowed, decision.reason) == (True, "")


def test_the_ladder_takes_no_switch_no_credential_state_and_no_hash():
    """Structural: eligibility depends on the account's two durable facts only."""
    import inspect

    parameters = set(
        inspect.signature(decide_default_password_eligibility).parameters
    )
    assert parameters == {"is_root_admin", "acesso_ativo"}


def test_every_refusal_states_a_reason_and_every_approval_states_none():
    cells = [
        dict(is_root_admin=True, acesso_ativo=1),
        dict(is_root_admin=False, acesso_ativo=0),
        dict(is_root_admin=False, acesso_ativo=1),
    ]
    for cell in cells:
        decision = decide_default_password_eligibility(**cell)
        assert bool(decision.reason) is not decision.allowed


# --------------------------------------------------------------------------- #
# Fixtures for the database-backed rows
# --------------------------------------------------------------------------- #


def _login_root_admin(client) -> int:
    """Sign in as the root administrator: it may ACT, it may not be a target."""
    with main.app.app_context():
        conn = main.get_db_connection()
        admin_id = resolve_root_admin_id(conn)
        assert admin_id is not None, "the isolated database has no root admin"
        auth_version = int(
            conn.execute(
                "SELECT auth_version FROM usuario_credenciais WHERE usuario_id=?",
                (admin_id,),
            ).fetchone()[0]
        )
    with client.session_transaction() as session:
        session.clear()
        session.update(
            user_id=admin_id,
            user_type="admin",
            user_name="UI-B09",
            access_level="admin_total",
            auth_version=auth_version,
        )
    return admin_id


def _seed(conn, email: str, *, senha: str | None, state: str) -> int:
    cursor = create_usuario_with_access_level(
        conn,
        "UI-B09 subject",
        email,
        hash_password(senha) if senha is not None else unusable_password_hash(),
        "admin",
        LEVEL,
        credential_state=state,
    )
    conn.commit()
    return int(cursor.lastrowid)


def _credential(conn, usuario_id: int) -> dict:
    row = conn.execute(
        """
        SELECT u.senha AS senha, c.estado AS estado,
               c.auth_version AS auth_version, c.acesso_ativo AS acesso_ativo
          FROM usuarios u
          JOIN usuario_credenciais c ON c.usuario_id = u.id
         WHERE u.id = ?
        """,
        (usuario_id,),
    ).fetchone()
    return dict(row)


def _apply(client, usuario_id: int):
    return client.post(
        f"/admin/acesso/{usuario_id}/resetar-senha", follow_redirects=False
    )


def _descriptor(client, usuario_id: int) -> dict:
    """The row descriptor the server actually ships to the action bar."""
    page = client.get("/admin/acesso")
    assert page.status_code == 200
    match = re.search(
        r'<script id="access-users-data" type="application/json">(.*?)</script>',
        page.get_data(as_text=True),
        re.S,
    )
    assert match, "the page no longer ships the users payload"
    return json.loads(match.group(1)).get(str(usuario_id), {})


# --------------------------------------------------------------------------- #
# 2. Every ordinary active account is offered and applied -- from any state
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "state,senha,case",
    [
        # The new normal source: an account created without a password.
        (CREDENTIAL_STATE_PENDING, None, "pending"),
        (CREDENTIAL_STATE_PERSONAL, "uma-senha-pessoal", "personal"),
        (CREDENTIAL_STATE_DEFAULT, "um-padrao-antigo", "default-stale"),
        # The stored hash ALREADY is the current configured default, and the
        # action is still offered and still applied.
        (CREDENTIAL_STATE_DEFAULT, CONFIGURED_DEFAULT, "default-already-current"),
    ],
)
def test_ordinary_active_account_is_offered_and_applied(tmp_path, state, senha, case):
    with isolated_versioned_app_env(tmp_path, f"b09-{case}.db") as env:
        with main.app.app_context():
            conn = main.get_db_connection()
            usuario_id = _seed(conn, f"{case}@example.test", senha=senha, state=state)
            before = _credential(conn, usuario_id)
            assert default_password_eligibility(conn, usuario_id).allowed is True
        _login_root_admin(env["client"])

        descriptor = _descriptor(env["client"], usuario_id)
        assert descriptor["canApplyDefaultPassword"] is True
        assert descriptor["applyDefaultPasswordReason"] == ""

        assert _apply(env["client"], usuario_id).status_code in (302, 303)
        with main.app.app_context():
            after = _credential(main.get_db_connection(), usuario_id)

        assert check_password(after["senha"], CONFIGURED_DEFAULT)
        assert after["estado"] == CREDENTIAL_STATE_DEFAULT
        # The reset happened even when the plaintext did not change: fresh salt,
        # and a bump that ends every live session.
        assert after["senha"] != before["senha"]
        assert after["auth_version"] == before["auth_version"] + 1
        if senha is not None and senha != CONFIGURED_DEFAULT:
            # The credential it replaced no longer authenticates.
            assert not check_password(after["senha"], senha)


def test_a_stale_legacy_switch_row_has_no_effect(tmp_path):
    """A leftover ``default_passwords_enabled='0'`` row decides nothing."""
    with isolated_versioned_app_env(tmp_path, "b09-legacy-row.db") as env:
        with main.app.app_context():
            conn = main.get_db_connection()
            usuario_id = _seed(
                conn, "legacy-row@example.test", senha=None, state=CREDENTIAL_STATE_PENDING
            )
            conn.execute(
                "INSERT INTO configuracoes_app(chave,valor) VALUES('default_passwords_enabled','0')"
            )
            conn.commit()
            assert default_password_eligibility(conn, usuario_id).allowed is True
        _login_root_admin(env["client"])

        descriptor = _descriptor(env["client"], usuario_id)
        assert descriptor["canApplyDefaultPassword"] is True
        assert _apply(env["client"], usuario_id).status_code in (302, 303)
        with main.app.app_context():
            after = _credential(main.get_db_connection(), usuario_id)
        assert after["estado"] == CREDENTIAL_STATE_DEFAULT
        assert check_password(after["senha"], CONFIGURED_DEFAULT)


def test_changing_the_configured_default_rehashes_nobody_and_the_action_is_the_fix(
    tmp_path,
):
    """An account can hold an OLDER configured default; the action moves it."""
    with isolated_versioned_app_env(tmp_path, "b09-stale-default.db") as env:
        with main.app.app_context():
            conn = main.get_db_connection()
            usuario_id = _seed(
                conn,
                "stale@example.test",
                senha=CONFIGURED_DEFAULT,
                state=CREDENTIAL_STATE_DEFAULT,
            )
            conn.execute(
                "UPDATE configuracoes_acesso SET senha_padrao=? WHERE nivel_acesso=?",
                ("novo-padrao-2026", LEVEL),
            )
            conn.commit()
            # The premise: no existing hash was touched by that write.
            assert check_password(
                _credential(conn, usuario_id)["senha"], CONFIGURED_DEFAULT
            )

        _login_root_admin(env["client"])
        assert _apply(env["client"], usuario_id).status_code in (302, 303)

        with main.app.app_context():
            after = _credential(main.get_db_connection(), usuario_id)
        assert check_password(after["senha"], "novo-padrao-2026")
        assert not check_password(after["senha"], CONFIGURED_DEFAULT)


# --------------------------------------------------------------------------- #
# 3. PROTECTED ROWS
# --------------------------------------------------------------------------- #


def test_root_administrator_is_protected_on_both_layers(tmp_path):
    with isolated_versioned_app_env(tmp_path, "b09-root.db") as env:
        admin_id = _login_root_admin(env["client"])
        with main.app.app_context():
            conn = main.get_db_connection()
            before = _credential(conn, admin_id)
            eligibility = default_password_eligibility(conn, admin_id)
        assert (eligibility.allowed, eligibility.reason) == (False, REASON_ROOT_ADMIN)

        descriptor = _descriptor(env["client"], admin_id)
        assert descriptor["canApplyDefaultPassword"] is False
        assert descriptor["applyDefaultPasswordReason"] == REASON_ROOT_ADMIN

        assert _apply(env["client"], admin_id).status_code in (302, 303)
        with main.app.app_context():
            # The only recovery path into the installation is untouched.
            assert _credential(main.get_db_connection(), admin_id) == before


def test_revoked_access_is_refused(tmp_path):
    with isolated_versioned_app_env(tmp_path, "b09-revoked.db") as env:
        with main.app.app_context():
            conn = main.get_db_connection()
            usuario_id = _seed(
                conn,
                "revoked@example.test",
                senha="uma-senha-pessoal",
                state=CREDENTIAL_STATE_PERSONAL,
            )
            set_usuario_access_active(conn, usuario_id, False)
            conn.commit()
            before = _credential(conn, usuario_id)
            eligibility = default_password_eligibility(conn, usuario_id)
            mapped = default_password_eligibility_map(conn, [usuario_id])[usuario_id]
        assert (eligibility.allowed, eligibility.reason) == (False, REASON_REVOKED)
        assert (mapped.allowed, mapped.reason) == (False, REASON_REVOKED)

        _login_root_admin(env["client"])
        assert _apply(env["client"], usuario_id).status_code in (302, 303)
        with main.app.app_context():
            assert _credential(main.get_db_connection(), usuario_id) == before


# --------------------------------------------------------------------------- #
# 4. FRONTEND / BACKEND AGREEMENT IS TOTAL
# --------------------------------------------------------------------------- #


def test_no_row_is_offered_by_the_bar_and_refused_by_the_endpoint(tmp_path):
    """Drive the whole matrix at once and compare the two layers row by row."""
    with isolated_versioned_app_env(tmp_path, "b09-matrix.db") as env:
        with main.app.app_context():
            conn = main.get_db_connection()
            root_id = resolve_root_admin_id(conn)
            pending_id = _seed(
                conn, "m-pending@example.test", senha=None, state=CREDENTIAL_STATE_PENDING
            )
            personal_id = _seed(
                conn, "m-personal@example.test", senha="p", state=CREDENTIAL_STATE_PERSONAL
            )
            default_id = _seed(
                conn,
                "m-default@example.test",
                senha=CONFIGURED_DEFAULT,
                state=CREDENTIAL_STATE_DEFAULT,
            )
            revoked_id = _seed(
                conn, "m-revoked@example.test", senha="r", state=CREDENTIAL_STATE_PERSONAL
            )
            set_usuario_access_active(conn, revoked_id, False)
            conn.commit()
            ids = [root_id, pending_id, personal_id, default_id, revoked_id]
            backend = {
                usuario_id: default_password_eligibility(conn, usuario_id).allowed
                for usuario_id in ids
            }

        _login_root_admin(env["client"])
        for usuario_id in ids:
            descriptor = _descriptor(env["client"], usuario_id)
            if descriptor:
                # Revoked accounts are not listed at all, so they ship no
                # descriptor and the bar can never reach them.
                assert descriptor["canApplyDefaultPassword"] == backend[usuario_id]

        assert backend == {
            root_id: False,
            pending_id: True,
            personal_id: True,
            default_id: True,
            revoked_id: False,
        }


# --------------------------------------------------------------------------- #
# 5. PERFORMANCE: eligibility is cheap state inspection
# --------------------------------------------------------------------------- #


def test_list_render_never_verifies_a_password_hash(tmp_path, monkeypatch):
    """O(rows) state inspection, never O(rows x PBKDF2).

    ``app.security.passwords.check_password`` imports ``check_password_hash``
    inside its body, so patching it at the werkzeug module intercepts every
    verification however the caller imported it.
    """
    with isolated_versioned_app_env(tmp_path, "b09-perf.db") as env:
        with main.app.app_context():
            conn = main.get_db_connection()
            for index in range(8):
                _seed(
                    conn,
                    f"perf-{index}@example.test",
                    senha=CONFIGURED_DEFAULT,
                    state=CREDENTIAL_STATE_DEFAULT,
                )
            conn.commit()
        _login_root_admin(env["client"])

        calls: list[str] = []
        original = werkzeug.security.check_password_hash

        def _counting(pwhash, password):
            calls.append(str(pwhash)[:16])
            return original(pwhash, password)

        monkeypatch.setattr(werkzeug.security, "check_password_hash", _counting)

        page = env["client"].get("/admin/acesso")
        assert page.status_code == 200
        assert calls == [], f"{len(calls)} password verifications during render"


def test_the_eligibility_owner_does_not_reach_for_password_verification():
    """Structural companion to the behavioural guard above.

    The module may not even import the machinery that would let it compare a
    password, nor the settings module the retired switch lived in, and none of
    its SQL may read the stored hash.
    """
    import ast

    source = ELIGIBILITY_MODULE.read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            imported.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    # The hashing/verification module and the configured-default lookup are the
    # two doors to a per-row PBKDF2 cost. Neither is open.
    assert "app.security.passwords" not in imported, imported
    assert "app.user_accounts" not in imported, imported
    assert "app.settings" not in imported, imported

    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "check_password" not in called
    assert "_access_defaults_map" not in called

    # No SQL in this module may select the password column or read settings.
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if "SELECT" in node.value.upper():
                assert "senha" not in node.value.lower(), node.value
                assert "configuracoes_app" not in node.value.lower(), node.value


# --------------------------------------------------------------------------- #
# 6. SIDE EFFECTS ON SUCCESS
# --------------------------------------------------------------------------- #


def test_success_side_effects_are_complete_and_bounded(tmp_path):
    """Everything the action promises, and nothing it does not."""
    with isolated_versioned_app_env(tmp_path, "b09-side-effects.db") as env:
        with main.app.app_context():
            conn = main.get_db_connection()
            usuario_id = _seed(
                conn,
                "effects@example.test",
                senha=None,
                state=CREDENTIAL_STATE_PENDING,
            )
            # An aluno record and a live onboarding token, both of which the
            # action must treat very differently.
            conn.execute(
                """
                INSERT INTO alunos (usuario_id, nome, matricula, email, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                (usuario_id, "UI-B09 subject", "B09-0001", "effects@example.test", "Ativo"),
            )
            _raw, token_id = issue_password_token(conn, usuario_id, PURPOSE_FIRST_ACCESS)
            conn.commit()
            before = _credential(conn, usuario_id)
            aluno_before = dict(
                conn.execute(
                    "SELECT nome,matricula,email,status FROM alunos WHERE usuario_id=?",
                    (usuario_id,),
                ).fetchone()
            )
            assert access_status_for_usuario(conn, usuario_id) == ACCESS_STATUS_PENDENTE

        _login_root_admin(env["client"])
        assert _apply(env["client"], usuario_id).status_code in (302, 303)

        with main.app.app_context():
            conn = main.get_db_connection()
            after = _credential(conn, usuario_id)
            token = conn.execute(
                "SELECT consumed_at,invalidated_at FROM senha_tokens WHERE id=?",
                (token_id,),
            ).fetchone()
            aluno_after = dict(
                conn.execute(
                    "SELECT nome,matricula,email,status FROM alunos WHERE usuario_id=?",
                    (usuario_id,),
                ).fetchone()
            )
            status = access_status_for_usuario(conn, usuario_id)

        # the currently configured default for the profile, hashed
        assert check_password(after["senha"], CONFIGURED_DEFAULT)
        # credential state
        assert after["estado"] == CREDENTIAL_STATE_DEFAULT
        # sessions die: the guard compares this stamp
        assert after["auth_version"] == before["auth_version"] + 1
        # access itself is not revoked by applying a password
        assert int(after["acesso_ativo"]) == 1
        # an onboarding link already in flight cannot survive a credential write
        assert token["invalidated_at"] is not None
        assert token["consumed_at"] is None
        # business data is none of this action's concern
        assert aluno_after == aluno_before
        # an explicitly applied default is a usable credential: Ativo
        assert status == ACCESS_STATUS_ATIVO


def test_onboarding_status_follows_the_applied_credential(tmp_path):
    """personal (Ativo) -> default stays Ativo; the credential is still usable."""
    with isolated_versioned_app_env(tmp_path, "b09-onboarding.db") as env:
        with main.app.app_context():
            conn = main.get_db_connection()
            usuario_id = _seed(
                conn,
                "was-ativo@example.test",
                senha="uma-senha-pessoal",
                state=CREDENTIAL_STATE_PERSONAL,
            )
            conn.commit()
            assert access_status_for_usuario(conn, usuario_id) == ACCESS_STATUS_ATIVO

        _login_root_admin(env["client"])
        assert _apply(env["client"], usuario_id).status_code in (302, 303)

        with main.app.app_context():
            assert (
                access_status_for_usuario(main.get_db_connection(), usuario_id)
                == ACCESS_STATUS_ATIVO
            )


# --------------------------------------------------------------------------- #
# 7. FRONTEND WIRING
# --------------------------------------------------------------------------- #


def test_action_bar_reads_the_descriptor_and_never_re_derives_eligibility():
    source = ACESSO_TEMPLATE.read_text(encoding="utf-8")

    # The click guard consults the descriptor; the page-global switch is gone.
    assert "if (!target.canApplyDefaultPassword || !target.resetUrl) return;" in source
    assert "defaultPasswordsEnabled" not in source
    assert "default_passwords_enabled" not in source

    # showBar sets the button per row, the way it already does for delete/email.
    reset_block = source[source.index("const resetBtn = bar.querySelector") :]
    reset_block = reset_block[: reset_block.index("function hideBar")]
    assert "resetBtn.disabled = !allowed;" in reset_block
    assert "aria-disabled" in reset_block
    assert "resetBtn.setAttribute('title', hint);" in reset_block
    assert "resetBtn.setAttribute('aria-label', hint);" in reset_block

    # The descriptor is built fail-closed: absent payload means no action.
    assert "?.canApplyDefaultPassword === true" in source


def test_reset_buttons_render_with_no_server_side_disabled_state():
    """Enablement is per row, from the descriptor -- never a page-level flag."""
    source = ACESSO_TEMPLATE.read_text(encoding="utf-8")
    menu_item = re.search(r'<button[^>]*id="access-action-reset"[^>]*>', source).group(0)
    assert "disabled" not in menu_item
    bar_button = re.search(r'<button[^>]*data-action="reset"[^>]*>', source).group(0)
    assert "disabled" not in bar_button
    assert "{%" not in bar_button


def test_bulk_action_uses_the_same_authority_as_the_floating_bar():
    source = ACESSO_TEMPLATE.read_text(encoding="utf-8")
    assert "function getSelectedRowsForDefaultPassword()" in source
    # The menu item enables only when EVERY selected row is eligible, the rule
    # "Excluir" already uses.
    assert (
        "actionResetButton.disabled = !selectedResettable || selectedResettable !== selectedCount;"
        in source
    )


def test_disabled_presentation_is_shared_by_the_bar_not_by_one_consumer():
    css = ACTIONS_FLOAT_CSS.read_text(encoding="utf-8")
    assert "#pedido-actions-float .act-btn:disabled" in css
    assert "#pedido-actions-float.atividades-actions-float .act-btn:disabled" not in css
    # The promoted declarations, unchanged -- no new colour, no new opacity.
    assert "opacity:.45; cursor:not-allowed;" in css


def test_reason_vocabulary_is_exactly_the_two_account_constraints():
    import app.access_default_password as owner

    reasons = [
        value
        for name, value in vars(owner).items()
        if name.startswith("REASON_") and isinstance(value, str)
    ]
    assert set(reasons) == {REASON_ROOT_ADMIN, REASON_REVOKED}
    assert REASON_ROOT_ADMIN == "Ação indisponível para o administrador raiz."
    assert REASON_REVOKED == "Acesso revogado."
    source = ELIGIBILITY_MODULE.read_text(encoding="utf-8")
    # The retired reasons no longer represent a disabled state anywhere.
    assert "Ative as senhas padrão" not in source
    assert "já utiliza a senha padrão atual" not in source
    for reason in reasons:
        assert reason == reason.strip() and reason
        assert len(reason) <= 60, reason
        # A reason is shown to an administrator: it must not leak the secret.
        assert CONFIGURED_DEFAULT not in reason
