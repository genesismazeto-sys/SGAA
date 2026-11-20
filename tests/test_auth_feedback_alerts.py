"""Every feedback state of the public authentication pages is the shared DS alert.

``templates/components/auth_alert.html`` (styles ``components/auth-alert.css``,
DS README §2.6g) renders one banner in three tones: danger (refusals and
errors), positive (a confirmed success) and info (a neutral notice that
confirms nothing). Login flashes, the recovery request's acknowledgement, the
set-password form's errors and the dead-link card all use it; instructions and
field hints never do. Wording and authentication behaviour are unchanged.
Fictitious accounts, isolated database, simulated mail transport only.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import main
import app.password_email as password_email
from app.auth import _clear_login_attempts
from app.password_recovery_limiter import clear_password_recovery_attempts
from app.password_tokens import PURPOSE_PASSWORD_RESET, issue_password_token
from app.user_accounts import CREDENTIAL_STATE_PERSONAL, set_usuario_password_hash
from tests.versioned_test_support import isolated_versioned_app_env

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALUNO_EMAIL = "aluno.base.versionado@example.com"
PASSWORD = "Antiga#2026"
AUTH_PAGES = ("login.html", "forgot_password.html", "set_password.html")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(password_email, "password_email_status", lambda conn: {"ready": True})
    monkeypatch.setattr(password_email, "get_public_base_url", lambda: "https://sgaa.example.test")
    monkeypatch.setattr(password_email, "send_text_email", lambda conn, message: {"ok": True})
    _clear_login_attempts()
    clear_password_recovery_attempts()
    with isolated_versioned_app_env(tmp_path, "auth-feedback.db") as environment:
        with main.app.app_context():
            conn = main.get_db_connection()
            usuario_id = int(conn.execute(
                "SELECT usuario_id FROM alunos WHERE matricula='PPA.TESTE.0001'").fetchone()[0])
            set_usuario_password_hash(conn, usuario_id, main.hash_password(PASSWORD),
                                      credential_state=CREDENTIAL_STATE_PERSONAL)
            conn.commit()
        yield {**environment, "usuario_id": usuario_id}
    _clear_login_attempts()
    clear_password_recovery_attempts()


def _alert(html, tone, icon, text):
    """The banner of ``tone`` with its icon and exactly ``text`` (visible)."""
    classes, role = {
        "danger": ("auth-alert", "alert"),
        "positive": ("auth-alert auth-alert--positive", "status"),
        "info": ("auth-alert auth-alert--info", "status"),
    }[tone]
    match = re.search(
        rf'<div class="{classes}" role="{role}">\s*<svg[^>]*icon-tabler-{icon}[^>]*auth-alert-icon[^>]*>.*?</svg>\s*<p>(.*?)</p>\s*</div>',
        html,
        re.DOTALL,
    )
    assert match, f"no {tone} alert in the page"
    assert re.sub(r"<[^>]+>", "", match.group(1)) == text
    return match


def _source(relative):
    return (PROJECT_ROOT / relative).read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# Login
# --------------------------------------------------------------------------


def test_wrong_credentials_are_the_danger_alert_in_the_login_form(env):
    response = env["client"].post("/login", data={"email": ALUNO_EMAIL, "senha": "errada-1"})
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    alert = _alert(html, "danger", "alert-circle", "E-mail ou senha inválidos.")
    # Same slot as before: inside the form, after the password, before "Lembrar-me".
    assert html.index('id="senha"') < alert.start() < html.index('class="login-form-meta"')
    form = html[html.index('<form method="POST" action="/login"'):html.index("</form>")]
    assert alert.group(0) in form
    # The approved login: original logo, heading and subtitle.
    assert 'alt="Logo" width="100"' in html and '<h1 class="login-title">SGAA</h1>' in html


def test_a_new_password_lands_on_login_with_the_positive_alert(env):
    with main.app.app_context():
        conn = main.get_db_connection()
        raw_token, _ = issue_password_token(conn, env["usuario_id"], PURPOSE_PASSWORD_RESET)
        conn.commit()
    response = env["client"].post(
        "/redefinir-senha",
        data={"token": raw_token, "senha": "Nova#2026", "confirmacao_senha": "Nova#2026"},
        follow_redirects=True,
    )
    html = response.get_data(as_text=True)
    assert response.request.path == "/login"
    _alert(html, "positive", "circle-check", "Senha definida com sucesso. Entre com sua nova senha.")


def test_signing_out_is_the_info_alert(env):
    client = env["client"]
    assert client.post("/login", data={"email": ALUNO_EMAIL, "senha": PASSWORD}).status_code == 302
    html = client.get("/logout", follow_redirects=True).get_data(as_text=True)
    _alert(html, "info", "info-circle", "Você foi desconectado.")


@pytest.mark.parametrize(
    ("category", "tone", "icon"),
    [("error", "danger", "alert-circle"), ("danger", "danger", "alert-circle"),
     ("success", "positive", "circle-check"), ("info", "info", "info-circle"),
     ("warning", "info", "info-circle"), ("message", "info", "info-circle")],
)
def test_a_flash_category_picks_its_tone_and_unknown_ones_stay_neutral(category, tone, icon):
    template = main.app.jinja_env.from_string(
        "{% from 'components/auth_alert.html' import flash_feedback %}{{ flash_feedback(category, 'Aviso.') }}"
    )
    with main.app.app_context():
        _alert(template.render(category=category), tone, icon, "Aviso.")


def test_a_message_is_escaped(env):
    template = main.app.jinja_env.from_string(
        "{% from 'components/auth_alert.html' import auth_feedback %}{{ auth_feedback(m) }}"
    )
    with main.app.app_context():
        html = template.render(m='<b>x</b> e-mail "y"')
    assert "<b>" not in html and "&lt;b&gt;x&lt;/b&gt;" in html
    assert '<span class="auth-alert-nowrap">e-mail</span>' in html


# --------------------------------------------------------------------------
# Password recovery and set-password
# --------------------------------------------------------------------------


def test_the_recovery_acknowledgement_is_the_neutral_info_alert(env):
    html = env["client"].post("/esqueci-minha-senha", data={"email": ALUNO_EMAIL}).get_data(as_text=True)
    _alert(
        html, "info", "info-circle",
        "Se houver uma conta associada a este e-mail, enviaremos as instruções para redefinição da senha.",
    )
    # It confirms no delivery: no success tone, no check mark.
    assert "auth-alert--positive" not in html and "icon-tabler-circle-check" not in html


def test_set_password_errors_are_the_danger_alert_inside_the_form(env):
    with main.app.app_context():
        conn = main.get_db_connection()
        raw_token, token_id = issue_password_token(conn, env["usuario_id"], PURPOSE_PASSWORD_RESET)
        conn.commit()
    client = env["client"]
    for data, text in (
        ({"senha": "", "confirmacao_senha": ""}, "Informe a nova senha."),
        ({"senha": "Uma#2026", "confirmacao_senha": "Outra#2026"}, "As senhas informadas não coincidem."),
    ):
        html = client.post("/redefinir-senha", data={"token": raw_token, **data}).get_data(as_text=True)
        alert = _alert(html, "danger", "alert-circle", text)
        form = html[html.index('<form method="POST" action="/redefinir-senha"'):html.index("</form>")]
        assert alert.group(0) in form
    with main.app.app_context():
        consumed = main.get_db_connection().execute(
            "SELECT consumed_at FROM senha_tokens WHERE id=?", (token_id,)).fetchone()[0]
    assert consumed is None


# --------------------------------------------------------------------------
# Design-system contract
# --------------------------------------------------------------------------


def test_every_auth_page_uses_the_shared_alert_and_no_line_feedback_remains():
    for name in AUTH_PAGES:
        page = _source(f"templates/{name}")
        assert "css/components/auth-alert.css" in page, name
        assert "login-feedback" not in page, name
        assert 'class="auth-alert' not in page, f"{name} must call the component, not copy it"
    assert "login-feedback" not in _source("static/css/modern-style.css"), "the line style is retired"
    for path in sorted((PROJECT_ROOT / "templates").rglob("*.html")):
        assert "login-feedback" not in path.read_text(encoding="utf-8"), path.name


def test_the_alert_stylesheet_takes_every_colour_from_tokens():
    css = _source("static/css/components/auth-alert.css")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL))
    rules = dict(re.findall(r"(?m)^([^\s/@{}][^{]*)\{([^}]*)\}", css))
    tones = {
        ".auth-alert": "danger",
        ".auth-alert.auth-alert--positive": "status-positive",
        ".auth-alert.auth-alert--info": "info",
    }
    for selector, family in tones.items():
        body = rules[selector].replace(" ", "")
        for part in ("bg", "border", "text"):
            assert f"--auth-alert-{part}:var(--{family}-{part})" in body, (selector, part)
    base = rules[".auth-alert"].replace(" ", "")
    for declaration in ("border:1pxsolidvar(--auth-alert-border)", "background:var(--auth-alert-bg)",
                        "color:var(--auth-alert-text)", "border-radius:var(--radius)"):
        assert declaration in base
    text = rules[".auth-alert p"].replace(" ", "")
    assert "text-align:justify" in text and "text-align-last:start" in text
    assert "margin:0" in rules[".login-form > .auth-alert"].replace(" ", "")
    assert not any("login-card" in s or "login-page" in s for s in rules), "the auth shell is not re-opened"
