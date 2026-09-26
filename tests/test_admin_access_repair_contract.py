"""Admin > Acesso post-landing defect repairs.

Four reported defects, one lane each:

1. the Novo acesso blank-password help text must match the account it
   actually creates -- since prod-1/v11 always a ``pending`` account that
   waits for its first access (the global default-password switch is retired);
2. the modal's icon/text note must use a shared DS contract, not markup with
   no rule anywhere;
3. "Enviar acesso" must not dereference the hover state after an await;
4. "Excluir acesso" must remove the login account only -- never the academic
   aluno -- and must never surface a raw SQLite message.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import app.password_email as password_email
import main
from app.password_tokens import PURPOSE_FIRST_ACCESS, PURPOSE_PASSWORD_RESET
from app.security.passwords import check_password
from app.user_accounts import CREDENTIAL_STATE_PENDING, CREDENTIAL_STATE_PERSONAL
from tests.canonical_matrix_test_support import login_admin
from tests.versioned_test_support import isolated_versioned_app_env


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "admin_acesso.html"
FORM_CSS = ROOT / "static" / "css" / "components" / "form.css"
DS_CSS_MACRO = ROOT / "templates" / "components" / "design_system_css.html"

CONFIGURED_DEFAULT = "admin123"


def _create_access(client, *, email: str, senha: str | None) -> int:
    payload = {
        "nome": "Repair Subject",
        "email": email,
        "nivel_acesso": "administrativo",
        "senha": senha or "",
    }
    response = client.post("/admin/acesso/salvar", data=payload, follow_redirects=False)
    assert response.status_code in (302, 303), response.status_code
    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT id FROM usuarios WHERE LOWER(email)=LOWER(?)", (email,)
        ).fetchone()
    assert row is not None, f"account {email} was not created"
    return int(row["id"])


def _credential_state(usuario_id: int) -> str:
    with main.app.app_context():
        return str(
            main.get_db_connection().execute(
                "SELECT estado FROM usuario_credenciais WHERE usuario_id=?", (usuario_id,)
            ).fetchone()["estado"]
        )


def _stored_hash(usuario_id: int) -> str:
    with main.app.app_context():
        return str(
            main.get_db_connection().execute(
                "SELECT senha FROM usuarios WHERE id=?", (usuario_id,)
            ).fetchone()["senha"]
        )


# --------------------------------------------------------------- 1. CREATION


@pytest.mark.parametrize(
    "explicit_password", [None, "chosen-secret"], ids=["blank", "explicit"]
)
def test_creation_matrix_credential_state_and_login_capability(tmp_path, explicit_password):
    """The two cells of the Novo acesso matrix, proved on stored state.

    Credential state is read from usuario_credenciais, never inferred from
    plaintext equality; login capability is proved by checking the stored hash
    against the shared default rather than by trusting the state column.
    """
    with isolated_versioned_app_env(tmp_path, "access-create-matrix.db") as env:
        login_admin(env["client"])

        email = f"matrix-{int(bool(explicit_password))}@example.test"
        usuario_id = _create_access(env["client"], email=email, senha=explicit_password)
        stored = _stored_hash(usuario_id)

        if explicit_password:
            assert _credential_state(usuario_id) == CREDENTIAL_STATE_PERSONAL
            assert check_password(stored, explicit_password)
            assert not check_password(stored, CONFIGURED_DEFAULT)
        else:
            # Blank means "no credential yet": pending, which is what routes
            # the e-mail action to first_access. The account is never born
            # with the shared default -- not even as a dormant hash.
            assert _credential_state(usuario_id) == CREDENTIAL_STATE_PENDING
            assert not check_password(stored, CONFIGURED_DEFAULT)
            assert not check_password(stored, "")


def test_blank_password_account_cannot_authenticate(tmp_path):
    """The blank account is listed but genuinely cannot log in."""
    with isolated_versioned_app_env(tmp_path, "access-create-nologin.db") as env:
        login_admin(env["client"])
        email = "no-login@example.test"
        _create_access(env["client"], email=email, senha=None)

        env["client"].get("/logout")
        response = env["client"].post(
            "/login",
            data={"email": email, "senha": CONFIGURED_DEFAULT},
            follow_redirects=False,
        )
        with env["client"].session_transaction() as session:
            assert session.get("user_id") is None, (
                "the shared default password authenticated an account created "
                "without a password"
            )
        assert response.status_code in (200, 302, 303)


def test_blank_password_help_text_promises_first_access(tmp_path):
    """Defect 1: the help text must not promise a default that will not apply."""
    with isolated_versioned_app_env(tmp_path, "access-help-text.db") as env:
        login_admin(env["client"])
        html = env["client"].get("/admin/acesso").get_data(as_text=True)

        help_match = re.search(
            r'<small id="access-password-help">(.*?)</small>', html, re.S
        )
        assert help_match, "the password help element disappeared"
        rendered_help = help_match.group(1)
        assert "primeiro acesso" in rendered_help
        assert "senha padrão" not in rendered_help

        templates_match = re.search(
            r'<script id="access-message-templates"[^>]*>(.*?)</script>', html, re.S
        )
        assert templates_match, "the access message templates block disappeared"
        templates_json = templates_match.group(1)
        # Both modes ship, because the client re-renders the help per mode.
        assert "passwordHelpCreate" in templates_json
        assert "passwordHelpEdit" in templates_json
        assert "aplica a senha padrão" not in templates_json
        assert "NoDefault" not in templates_json


def test_help_text_script_has_no_switch_branch():
    """The client-side re-render depends on the mode only."""
    source = TEMPLATE.read_text(encoding="utf-8")
    sync = re.search(r"function syncDefaultHint\(mode\)\{(.*?)\n    \}", source, re.S)
    assert sync, "syncDefaultHint disappeared"
    body = sync.group(1)
    assert "defaultPasswordsEnabled" not in body
    assert "passwordHelpCreate" in body
    assert "passwordHelpEdit" in body


# ------------------------------------------------------------- 2. DESIGN SYS


def test_modal_note_uses_a_shared_design_system_contract():
    """Defect 2: the icon/text note had no rule anywhere, so it read as touching."""
    template = TEMPLATE.read_text(encoding="utf-8")
    css = FORM_CSS.read_text(encoding="utf-8")

    # Match the class as markup / as a selector, not as prose in a comment.
    assert not re.search(r'class="[^"]*\baccess-note\b', template), (
        "the page-local, never-defined .access-note hook is back in the markup"
    )
    assert not re.search(r"^\s*\.access-note[\s{,]", css, re.M), (
        "a rule for the retired .access-note hook was added instead of reusing "
        "the shared note contract"
    )
    assert not re.search(r'class="[^"]*\baccess-default-note\b', template), (
        "a second undefined local note class is back"
    )
    assert 'class="form-note"' in template, "the note no longer uses the shared class"

    rule = re.search(r"\.form-note\{(.*?)\}", css, re.S)
    assert rule, ".form-note must be owned by components/form.css"
    body = rule.group(1)
    # The icon/text row contract: centred cross-axis with an explicit gap.
    assert "display:flex" in body
    assert "align-items:center" in body
    assert re.search(r"gap:\s*\d", body), "the note must declare an icon/text gap"

    icon = re.search(r"\.form-note\s*>\s*\.lucide\{(.*?)\}", css, re.S)
    assert icon, "the note icon must be sized, or it inherits a 24px lucide default"
    assert "width:16px" in icon.group(1) and "height:16px" in icon.group(1)


def test_form_css_is_loaded_by_the_shared_design_system_macro():
    """The note's owner must already be on the page — no page-local <link>."""
    macro = DS_CSS_MACRO.read_text(encoding="utf-8")
    assert "css/components/form.css" in macro
    template = TEMPLATE.read_text(encoding="utf-8")
    assert "components/form.css" not in template, (
        "admin_acesso.html re-links a design-system stylesheet the shared "
        "macro already owns"
    )


# ------------------------------------------- 2b. PERMISSION SCOPE INDICATORS

GLOBAL_CSS = ROOT / "static" / "css" / "modern-style.css"

# The shared primitive every Novo acesso permission card must render. The scope
# ("Nenhum" / "Leitura" / "Edição" / "Total") is an access-level value, not a
# status, so the tone is the neutral one for all cards: a success/caution tone
# would claim a judgement the value does not carry.
SCOPE_PILL_CLASS = "badge status-pill status-neutral"


def _scope_pill_tags(html: str) -> list[str]:
    return re.findall(
        r"<span\b([^>]*\bdata-resource-effective-pill=[^>]*)>", html
    )


def test_scope_pill_has_no_page_local_visual_contract():
    """The yellow "Total" pill was a page-local badge family, not the DS one."""
    template = TEMPLATE.read_text(encoding="utf-8")

    assert "access-scope-pill" not in template, (
        "the page-local .access-scope-pill badge family is back in "
        "admin_acesso.html — the scope indicator must reuse the shared "
        "DS pill instead of declaring its own background/color/radius"
    )
    # The dead local access-level badge families went with it; a second local
    # badge contract is how the first one came back last time.
    for retired in ("access-level-badge", "access-base-badge"):
        assert retired not in template, f"local badge family .{retired} is back"

    # No new local pill/badge rule may be declared by this page at all.
    style_blocks = re.findall(r"<style[^>]*>(.*?)</style>", template, re.S | re.I)
    assert style_blocks, "admin_acesso.html lost its <style> block entirely"
    local_css = "\n".join(style_blocks)
    offenders = re.findall(r"^\s*(\.[\w-]*(?:pill|badge)[\w-]*[^{]*)\{", local_css, re.M)
    assert not offenders, (
        "admin_acesso.html declares its own pill/badge rules again: "
        f"{[o.strip() for o in offenders]}"
    )


def test_scope_pill_primitive_is_owned_by_the_global_design_system():
    """The adopted classes must resolve to a real, shared rule."""
    css = GLOBAL_CSS.read_text(encoding="utf-8")
    assert re.search(r"^\.badge\{", css, re.M), ".badge must be owned by modern-style.css"
    assert re.search(r"^\.badge\.status-pill\{", css, re.M), (
        ".badge.status-pill must be owned by modern-style.css"
    )
    assert re.search(r"^\.badge\.status-pill\.status-neutral\{", css, re.M), (
        "the neutral access-level tone must exist in the shared design system"
    )


def test_scope_pill_javascript_never_rewrites_the_shared_class():
    """The class contract must be static; only the label and data value move."""
    source = TEMPLATE.read_text(encoding="utf-8")
    sync = re.search(r"function syncPolicyFields\(\)\{(.*?)\n    \}\n", source, re.S)
    assert sync, "syncPolicyFields disappeared"
    body = sync.group(1)

    assert not re.search(r"effectivePill\.(className|classList)", body), (
        "syncPolicyFields still swaps the pill's classes per scope, which is "
        "how the per-scope colour palette was reintroduced"
    )
    assert "effectivePill.textContent" in body, "the pill no longer receives its label"
    assert "effectivePill.dataset.scope" in body, (
        "the scope value must stay machine-readable on the element"
    )
    # "Total" is the label the defect report named; it must still be the text
    # written into the shared pill, not a renamed or restyled variant.
    assert re.search(r"full:\s*'Total'", source), "the 'Total' scope label changed"


def test_every_novo_acesso_permission_card_renders_the_same_shared_pill(tmp_path):
    """Rendered proof: all 15 cards, one identical DS contract, no inline style."""
    from app.auth import ACCESS_RESOURCE_ORDER

    with isolated_versioned_app_env(tmp_path, "access-scope-pill-ds.db") as env:
        login_admin(env["client"])
        response = env["client"].get("/admin/acesso")
        assert response.status_code == 200, response.status_code
        html = response.get_data(as_text=True)

    tags = _scope_pill_tags(html)
    assert len(tags) == len(ACCESS_RESOURCE_ORDER), (
        f"expected one scope pill per permission card "
        f"({len(ACCESS_RESOURCE_ORDER)}), rendered {len(tags)}"
    )

    classes = {
        (re.search(r'class="([^"]*)"', tag).group(1) if 'class="' in tag else "")
        for tag in tags
    }
    assert classes == {SCOPE_PILL_CLASS}, (
        "permission cards do not share one DS class contract: "
        f"{sorted(classes)}"
    )

    inline = [tag for tag in tags if "style=" in tag]
    assert not inline, f"scope pills carry inline styling: {inline}"

    resources = {
        re.search(r'data-resource-effective-pill="([^"]*)"', tag).group(1)
        for tag in tags
    }
    assert resources == set(ACCESS_RESOURCE_ORDER), (
        f"scope pills cover the wrong resources: {sorted(resources ^ set(ACCESS_RESOURCE_ORDER))}"
    )

    assert "access-scope-pill" not in html, (
        "the retired page-local pill class still reaches the browser"
    )


# ------------------------------------------------------------- 3. EMAIL PATH


def test_action_bar_never_dereferences_hover_state_after_await():
    """Defect 3: the exact shape of the reported null emailUrl crash.

    hideBar() nulls `currentData` 180ms after the pointer leaves, which lands
    while the confirmation modal is awaited. Any read of `currentData` after
    an await in that handler is the reported TypeError.
    """
    source = TEMPLATE.read_text(encoding="utf-8")
    handler = re.search(
        r"bar\.addEventListener\('click', async \(e\) => \{(.*?)\n    \}\);", source, re.S
    )
    assert handler, "the action-bar click handler disappeared"
    body = handler.group(1)

    assert "const target = currentData;" in body, (
        "the action descriptor must be snapshotted at click time"
    )
    after_snapshot = body.split("const target = currentData;", 1)[1]
    leaked = re.findall(r"currentData\.\w+", after_snapshot)
    assert not leaked, (
        "the handler still reads the mutable hover state after snapshotting: "
        f"{sorted(set(leaked))} — these are null dereferences once the "
        "confirmation modal has been awaited"
    )


@pytest.fixture(scope="module")
def action_bar_harness() -> dict:
    """Run the real shipped action-bar script under node.

    The static test above pins the shape of the repair; this one proves the
    behaviour, by replaying the exact interleaving that produced the reported
    crash. Skipped when node is unavailable; the static lane still runs.
    """
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("node is unavailable; the static action-bar contract still runs")
    harness = ROOT / "tests" / "js" / "acesso_action_bar_harness.js"
    proc = subprocess.run(
        [node, str(harness), str(ROOT)], capture_output=True, text=True, timeout=120
    )
    assert proc.returncode == 0, f"harness failed:\n{proc.stderr}"
    return {item["scenario"]: item for item in json.loads(proc.stdout)}


def test_send_access_survives_the_bar_hiding_mid_confirmation(action_bar_harness):
    """The reported crash, replayed: hide the bar while the confirm is open."""
    result = action_bar_harness["email-hidden-mid-confirm"]
    assert result.get("phase") != "init", result.get("error")
    assert result["crashed"] is None, (
        f"the e-mail action still throws when the action bar hides during the "
        f"confirmation: {result['crashed']}"
    )
    assert result["submissions"] == [
        {"method": "POST", "action": "/admin/acesso/7/senha-por-email"}
    ], "the confirmed send did not reach the endpoint"


def test_send_access_works_with_the_bar_still_visible(action_bar_harness):
    result = action_bar_harness["email-bar-still-visible"]
    assert result["crashed"] is None
    assert result["submissions"] == [
        {"method": "POST", "action": "/admin/acesso/7/senha-por-email"}
    ]


def test_apply_default_password_survives_the_same_interleaving(action_bar_harness):
    """The reset action awaited the same modal and had the same latent bug."""
    result = action_bar_harness["reset-hidden-mid-confirm"]
    assert result["crashed"] is None, result["crashed"]
    assert result["submissions"] == [
        {"method": "POST", "action": "/admin/acesso/7/resetar-senha"}
    ]


def test_harness_reproduces_the_pre_repair_crash(action_bar_harness):
    """A harness that cannot reproduce the defect proves nothing about the fix."""
    result = action_bar_harness["selfcheck-pre-repair-read-crashes"]
    assert result["crashed"] == "Cannot read properties of null (reading 'emailUrl')", (
        "the harness no longer reproduces the reported crash, so the passing "
        f"scenarios above are not evidence: {result['crashed']!r}"
    )
    assert result["submissions"] == []


def test_email_action_requires_mail_capability_client_side():
    source = TEMPLATE.read_text(encoding="utf-8")
    assert "if (!target.emailUrl || !mailAvailable) return;" in source, (
        "the e-mail action must not fire while the mail transport is unavailable"
    )


def _seed_recipient(client, *, email: str) -> int:
    return _create_access(client, email=email, senha=None)


def test_send_access_email_succeeds_from_the_real_admin_action(tmp_path, monkeypatch):
    """Defect 3, end to end: the actual Admin > Acesso action delivers a mail.

    The provider is captured, never contacted.
    """
    captured: list[object] = []
    with isolated_versioned_app_env(tmp_path, "access-email-sent.db") as env:
        login_admin(env["client"])
        usuario_id = _seed_recipient(env["client"], email="send-ok@example.test")

        monkeypatch.setattr(password_email, "password_email_status", lambda _conn: {"ready": True})
        monkeypatch.setattr(
            password_email, "get_public_base_url", lambda: "https://sgaa.example.test"
        )
        monkeypatch.setattr(
            password_email,
            "send_text_email",
            lambda _conn, message: captured.append(message),
        )

        response = env["client"].post(
            f"/admin/acesso/{usuario_id}/senha-por-email", follow_redirects=True
        )
        assert response.status_code == 200
        body = response.get_data(as_text=True)

        assert len(captured) == 1, "the admin action did not reach the mail transport"
        message = captured[0]
        assert message.to_address == "send-ok@example.test"
        # A brand-new account that never had a personal password gets the
        # first-access link, not a reset link.
        assert "/primeiro-acesso?token=" in message.body_text
        assert "/redefinir-senha?token=" not in message.body_text
        assert "enviado com sucesso" in body

        with main.app.app_context():
            tokens = main.get_db_connection().execute(
                "SELECT purpose FROM senha_tokens WHERE usuario_id=? "
                "AND consumed_at IS NULL AND invalidated_at IS NULL",
                (usuario_id,),
            ).fetchall()
        assert [str(row["purpose"]) for row in tokens] == [PURPOSE_FIRST_ACCESS]


def test_personal_credential_state_sends_a_reset_not_a_first_access(tmp_path, monkeypatch):
    captured: list[object] = []
    with isolated_versioned_app_env(tmp_path, "access-email-reset.db") as env:
        login_admin(env["client"])
        usuario_id = _create_access(
            env["client"], email="send-reset@example.test", senha="chosen-secret"
        )
        assert _credential_state(usuario_id) == CREDENTIAL_STATE_PERSONAL

        monkeypatch.setattr(password_email, "password_email_status", lambda _conn: {"ready": True})
        monkeypatch.setattr(
            password_email, "get_public_base_url", lambda: "https://sgaa.example.test"
        )
        monkeypatch.setattr(
            password_email,
            "send_text_email",
            lambda _conn, message: captured.append(message),
        )

        env["client"].post(f"/admin/acesso/{usuario_id}/senha-por-email", follow_redirects=True)
        assert len(captured) == 1
        assert "/redefinir-senha?token=" in captured[0].body_text

        with main.app.app_context():
            purposes = [
                str(row["purpose"])
                for row in main.get_db_connection().execute(
                    "SELECT purpose FROM senha_tokens WHERE usuario_id=? "
                    "AND consumed_at IS NULL AND invalidated_at IS NULL",
                    (usuario_id,),
                ).fetchall()
            ]
        assert purposes == [PURPOSE_PASSWORD_RESET]


def test_send_access_email_reports_unavailable_without_issuing_a_token(tmp_path, monkeypatch):
    with isolated_versioned_app_env(tmp_path, "access-email-unavailable.db") as env:
        login_admin(env["client"])
        usuario_id = _seed_recipient(env["client"], email="send-unavailable@example.test")

        monkeypatch.setattr(
            password_email,
            "password_email_status",
            lambda _conn: {"ready": False, "message": "Envio de e-mail indisponível."},
        )
        response = env["client"].post(
            f"/admin/acesso/{usuario_id}/senha-por-email", follow_redirects=True
        )
        assert response.status_code == 200
        assert "indisponível" in response.get_data(as_text=True)

        with main.app.app_context():
            active = int(
                main.get_db_connection().execute(
                    "SELECT COUNT(*) FROM senha_tokens WHERE usuario_id=? "
                    "AND consumed_at IS NULL AND invalidated_at IS NULL",
                    (usuario_id,),
                ).fetchone()[0]
            )
        assert active == 0, "an unavailable transport must not mint a token"


def test_send_access_email_for_unknown_user_is_handled(tmp_path):
    with isolated_versioned_app_env(tmp_path, "access-email-missing.db") as env:
        login_admin(env["client"])
        response = env["client"].post(
            "/admin/acesso/999999/senha-por-email", follow_redirects=True
        )
        assert response.status_code == 200
        assert "não encontrado" in response.get_data(as_text=True)


def test_send_access_email_requires_authentication(tmp_path):
    with isolated_versioned_app_env(tmp_path, "access-email-rbac.db") as env:
        response = env["client"].post(
            "/admin/acesso/1/senha-por-email", follow_redirects=False
        )
        assert response.status_code in (302, 303, 401, 403)
        assert "/admin/acesso" not in (response.headers.get("Location") or "")


# ----------------------------------------------------------------- 4. DELETE


def _seed_student(client, *, email: str, matricula: str) -> tuple[int, int]:
    response = client.post(
        "/admin/acesso/salvar",
        data={
            "nome": "Academic Subject",
            "email": email,
            "nivel_acesso": "usuario",
            "senha": "student-secret",
            "matricula": matricula,
            "status": "Ativo",
        },
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT u.id AS usuario_id, a.id AS aluno_id FROM usuarios u "
            "JOIN alunos a ON a.usuario_id=u.id WHERE LOWER(u.email)=LOWER(?)",
            (email,),
        ).fetchone()
    assert row is not None, "the student account was not created"
    return int(row["usuario_id"]), int(row["aluno_id"])


def _credential_row(usuario_id: int):
    with main.app.app_context():
        return dict(
            main.get_db_connection().execute(
                "SELECT estado, auth_version, acesso_ativo FROM usuario_credenciais WHERE usuario_id=?",
                (usuario_id,),
            ).fetchone()
        )


def _login(client, email: str, senha: str) -> int | None:
    from app.auth import _login_attempts, _login_attempts_by_account

    _login_attempts.clear()
    _login_attempts_by_account.clear()
    client.get("/logout")
    client.post("/login", data={"email": email, "senha": senha}, follow_redirects=False)
    with client.session_transaction() as session:
        return session.get("user_id")


def test_excluir_acesso_revokes_and_preserves_the_academic_aluno(tmp_path):
    """One model: "Excluir acesso" ends the login, the person survives."""
    with isolated_versioned_app_env(tmp_path, "access-revoke-student.db") as env:
        login_admin(env["client"])
        usuario_id, aluno_id = _seed_student(
            env["client"], email="academic@example.test", matricula="DEL-0001"
        )

        with main.app.app_context():
            conn = main.get_db_connection()
            before = dict(
                conn.execute(
                    "SELECT usuario_id,nome,matricula,email,turma_id,matriz_id,status "
                    "FROM alunos WHERE id=?",
                    (aluno_id,),
                ).fetchone()
            )
            alunos_before = int(conn.execute("SELECT COUNT(*) FROM alunos").fetchone()[0])

        response = env["client"].post(
            f"/admin/acesso/{usuario_id}/deletar", follow_redirects=True
        )
        assert response.status_code == 200
        assert "Acesso revogado" in response.get_data(as_text=True)

        with main.app.app_context():
            conn = main.get_db_connection()
            # The identity is preserved, not destroyed: history points at it.
            assert conn.execute(
                "SELECT 1 FROM usuarios WHERE id=?", (usuario_id,)
            ).fetchone() is not None, "revocation deleted the usuarios row"

            after = dict(
                conn.execute(
                    "SELECT usuario_id,nome,matricula,email,turma_id,matriz_id,status "
                    "FROM alunos WHERE id=?",
                    (aluno_id,),
                ).fetchone()
            )
            assert after == before, "an academic field changed during access revocation"
            assert after["usuario_id"] == usuario_id, "the aluno lost its identity link"
            assert int(conn.execute("SELECT COUNT(*) FROM alunos").fetchone()[0]) == alunos_before
            assert conn.execute("PRAGMA foreign_key_check").fetchall() == []

        assert _credential_row(usuario_id)["acesso_ativo"] == 0


def test_revoked_account_cannot_authenticate_either_way(tmp_path):
    """Durable status beats password origin."""
    with isolated_versioned_app_env(tmp_path, "access-revoke-login.db") as env:
        client = env["client"]
        login_admin(client)
        usuario_id, _aluno_id = _seed_student(
            client, email="revoked@example.test", matricula="DEL-0010"
        )
        assert _login(client, "revoked@example.test", "student-secret") == usuario_id

        login_admin(client)
        client.post(f"/admin/acesso/{usuario_id}/deletar", follow_redirects=True)

        assert _credential_row(usuario_id)["acesso_ativo"] == 0
        assert _login(client, "revoked@example.test", "student-secret") is None, (
            "a revoked account authenticated with its correct personal password"
        )
        assert _login(client, "revoked@example.test", CONFIGURED_DEFAULT) is None


def test_revocation_bumps_auth_version_and_kills_tokens(tmp_path, monkeypatch):
    with isolated_versioned_app_env(tmp_path, "access-revoke-tokens.db") as env:
        client = env["client"]
        login_admin(client)
        usuario_id = _seed_recipient(client, email="with-token@example.test")
        assert _credential_state(usuario_id) == CREDENTIAL_STATE_PENDING
        before_version = _credential_row(usuario_id)["auth_version"]

        monkeypatch.setattr(password_email, "password_email_status", lambda _conn: {"ready": True})
        monkeypatch.setattr(
            password_email, "get_public_base_url", lambda: "https://sgaa.example.test"
        )
        monkeypatch.setattr(password_email, "send_text_email", lambda _conn, _message: None)
        client.post(f"/admin/acesso/{usuario_id}/senha-por-email", follow_redirects=True)

        with main.app.app_context():
            assert int(
                main.get_db_connection().execute(
                    "SELECT COUNT(*) FROM senha_tokens WHERE usuario_id=? "
                    "AND consumed_at IS NULL AND invalidated_at IS NULL",
                    (usuario_id,),
                ).fetchone()[0]
            ) == 1

        client.post(f"/admin/acesso/{usuario_id}/deletar", follow_redirects=True)

        after = _credential_row(usuario_id)
        assert after["acesso_ativo"] == 0
        # Revocation leaves no usable credential behind: pending, unusable hash.
        assert after["estado"] == CREDENTIAL_STATE_PENDING
        assert after["auth_version"] > before_version, (
            "revocation did not invalidate live sessions"
        )
        with main.app.app_context():
            assert int(
                main.get_db_connection().execute(
                    "SELECT COUNT(*) FROM senha_tokens WHERE usuario_id=? "
                    "AND consumed_at IS NULL AND invalidated_at IS NULL",
                    (usuario_id,),
                ).fetchone()[0]
            ) == 0, "a pending password token survived revocation"


def test_revoked_account_is_refused_a_password_email(tmp_path, monkeypatch):
    captured: list[object] = []
    with isolated_versioned_app_env(tmp_path, "access-revoke-noemail.db") as env:
        client = env["client"]
        login_admin(client)
        usuario_id = _seed_recipient(client, email="noemail@example.test")
        client.post(f"/admin/acesso/{usuario_id}/deletar", follow_redirects=True)

        monkeypatch.setattr(password_email, "password_email_status", lambda _conn: {"ready": True})
        monkeypatch.setattr(
            password_email, "get_public_base_url", lambda: "https://sgaa.example.test"
        )
        monkeypatch.setattr(
            password_email, "send_text_email", lambda _conn, message: captured.append(message)
        )
        response = client.post(
            f"/admin/acesso/{usuario_id}/senha-por-email", follow_redirects=True
        )
        assert "revogado" in response.get_data(as_text=True)
        assert captured == [], "a revoked account was sent a password e-mail"


def test_revoked_account_is_hidden_from_the_active_list(tmp_path):
    with isolated_versioned_app_env(tmp_path, "access-revoke-hidden.db") as env:
        client = env["client"]
        login_admin(client)
        usuario_id, _aluno_id = _seed_student(
            client, email="hidden@example.test", matricula="DEL-0020"
        )
        assert "hidden@example.test" in client.get("/admin/acesso").get_data(as_text=True)

        client.post(f"/admin/acesso/{usuario_id}/deletar", follow_redirects=True)
        html = client.get("/admin/acesso").get_data(as_text=True)
        assert "hidden@example.test" not in html, (
            "a revoked access still appears as an ordinary active access"
        )


def test_revocation_preserves_historical_upload_attribution(tmp_path):
    """The reason deletion was wrong: attribution must stay truthful."""
    with isolated_versioned_app_env(tmp_path, "access-revoke-upload.db") as env:
        client = env["client"]
        login_admin(client)
        usuario_id, _aluno_id = _seed_student(
            client, email="uploader@example.test", matricula="DEL-0003"
        )
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute(
                "INSERT INTO admin_arquivos (titulo,filename,uploader_user_id) VALUES (?,?,?)",
                ("Enviado por este acesso", "file.pdf", usuario_id),
            )
            conn.commit()

        response = client.post(
            f"/admin/acesso/{usuario_id}/deletar", follow_redirects=True
        )
        body = response.get_data(as_text=True)
        assert "Acesso revogado" in body
        assert "FOREIGN KEY constraint failed" not in body

        with main.app.app_context():
            conn = main.get_db_connection()
            assert int(
                conn.execute(
                    "SELECT COUNT(*) FROM admin_arquivos WHERE uploader_user_id=?",
                    (usuario_id,),
                ).fetchone()[0]
            ) == 1, "revocation broke the uploader attribution"
            assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_reactivation_reuses_the_preserved_identity(tmp_path):
    """Re-creating access for the same person must not duplicate anything."""
    with isolated_versioned_app_env(tmp_path, "access-reactivate.db") as env:
        client = env["client"]
        login_admin(client)
        usuario_id, aluno_id = _seed_student(
            client, email="relink@example.test", matricula="DEL-0002"
        )
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute(
                "INSERT INTO admin_arquivos (titulo,filename,uploader_user_id) VALUES (?,?,?)",
                ("Historico", "h.pdf", usuario_id),
            )
            conn.commit()
            before = dict(
                conn.execute(
                    "SELECT nome,matricula,turma_id,matriz_id,status FROM alunos WHERE id=?",
                    (aluno_id,),
                ).fetchone()
            )

        client.post(f"/admin/acesso/{usuario_id}/deletar", follow_redirects=True)
        assert _credential_row(usuario_id)["acesso_ativo"] == 0

        response = env["client"].post(
            "/admin/acesso/salvar",
            data={
                "nome": "Academic Subject", "email": "relink@example.test",
                "nivel_acesso": "usuario", "senha": "nova-senha-pessoal",
                "matricula": "DEL-0002", "status": "Ativo",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200
        body = response.get_data(as_text=True)
        assert "Já existe um usuário com este e-mail" not in body, "reactivation hit UNIQUE"
        assert "reativado" in body

        with main.app.app_context():
            conn = main.get_db_connection()
            assert int(
                conn.execute(
                    "SELECT COUNT(*) FROM usuarios WHERE LOWER(email)='relink@example.test'"
                ).fetchone()[0]
            ) == 1, "reactivation created a duplicate usuario"
            assert int(
                conn.execute(
                    "SELECT COUNT(*) FROM alunos WHERE matricula='DEL-0002'"
                ).fetchone()[0]
            ) == 1, "reactivation created a duplicate aluno"
            row = conn.execute(
                "SELECT u.id AS uid, a.id AS aid FROM usuarios u JOIN alunos a ON a.usuario_id=u.id "
                "WHERE LOWER(u.email)='relink@example.test'"
            ).fetchone()
            assert int(row["uid"]) == usuario_id, "a new identity was minted"
            assert int(row["aid"]) == aluno_id, "the aluno was not relinked"
            after = dict(
                conn.execute(
                    "SELECT nome,matricula,turma_id,matriz_id,status FROM alunos WHERE id=?",
                    (aluno_id,),
                ).fetchone()
            )
            assert after == before, "academic data changed across revoke/reactivate"
            assert int(
                conn.execute(
                    "SELECT COUNT(*) FROM admin_arquivos WHERE uploader_user_id=?", (usuario_id,)
                ).fetchone()[0]
            ) == 1, "reactivation lost the historical uploader attribution"
            assert conn.execute("PRAGMA foreign_key_check").fetchall() == []

        credential = _credential_row(usuario_id)
        assert credential["acesso_ativo"] == 1
        assert credential["estado"] == CREDENTIAL_STATE_PERSONAL
        assert _login(client, "relink@example.test", "nova-senha-pessoal") == usuario_id


def test_reactivation_does_not_revive_stale_tokens(tmp_path, monkeypatch):
    with isolated_versioned_app_env(tmp_path, "access-reactivate-tokens.db") as env:
        client = env["client"]
        login_admin(client)
        usuario_id = _seed_recipient(client, email="stale@example.test")

        monkeypatch.setattr(password_email, "password_email_status", lambda _conn: {"ready": True})
        monkeypatch.setattr(
            password_email, "get_public_base_url", lambda: "https://sgaa.example.test"
        )
        monkeypatch.setattr(password_email, "send_text_email", lambda _conn, _message: None)
        client.post(f"/admin/acesso/{usuario_id}/senha-por-email", follow_redirects=True)

        client.post(f"/admin/acesso/{usuario_id}/deletar", follow_redirects=True)
        client.post(
            "/admin/acesso/salvar",
            data={
                "nome": "Repair Subject", "email": "stale@example.test",
                "nivel_acesso": "administrativo", "senha": "outra-pessoal",
            },
            follow_redirects=True,
        )

        with main.app.app_context():
            live = int(
                main.get_db_connection().execute(
                    "SELECT COUNT(*) FROM senha_tokens WHERE usuario_id=? "
                    "AND consumed_at IS NULL AND invalidated_at IS NULL",
                    (usuario_id,),
                ).fetchone()[0]
            )
        assert live == 0, "a pre-revocation token became valid again after reactivation"


def test_access_removal_never_surfaces_raw_sqlite_text(tmp_path):
    """Defect 6 retained: SQLite internals never reach the user."""
    source = (ROOT / "app" / "views" / "admin" / "acesso.py").read_text(encoding="utf-8")
    handler = re.search(
        r"def admin_acesso_deletar\(usuario_id\):(.*?)\n\nbp_admin_acesso", source, re.S
    )
    assert handler, "admin_acesso_deletar disappeared"
    body = handler.group(1)

    assert "DELETE FROM alunos" not in body, "access removal deletes the academic aluno"
    assert "DELETE FROM usuarios" not in body, (
        "access removal still physically deletes the identity history references"
    )
    assert "_revoke_usuario_access" in body
    assert "{exc}" not in body, "the raw SQLite exception is interpolated into the UI"

    with isolated_versioned_app_env(tmp_path, "access-raw-text.db") as env:
        login_admin(env["client"])
        usuario_id, _aluno_id = _seed_student(
            env["client"], email="rawtext@example.test", matricula="DEL-0004"
        )
        body = env["client"].post(
            f"/admin/acesso/{usuario_id}/deletar", follow_redirects=True
        ).get_data(as_text=True)
        assert "FOREIGN KEY constraint failed" not in body
        assert "IntegrityError" not in body
        assert "sqlite3" not in body


def test_self_delete_is_refused(tmp_path):
    with isolated_versioned_app_env(tmp_path, "access-delete-self.db") as env:
        login_admin(env["client"])
        response = env["client"].post("/admin/acesso/1/deletar", follow_redirects=True)
        assert "não pode excluir o próprio acesso" in response.get_data(as_text=True)
        with main.app.app_context():
            assert main.get_db_connection().execute(
                "SELECT 1 FROM usuarios WHERE id=1"
            ).fetchone() is not None
