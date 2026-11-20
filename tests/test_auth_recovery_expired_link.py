"""A dead password link offers a new one at once, with no administrator involved.

The page of an invalid, expired or already used link (``/redefinir-senha``,
``/primeiro-acesso``) renders the design-system recovery card
(``templates/components/auth_recovery.html``): the title "Link expirado", the
danger alert, the configured validity of the link, an e-mail field and
"Enviar novo link", which posts to the public self-service recovery
(``/esqueci-minha-senha``) and states the validity of the reset link that
recovery sends. The address is pre-filled only when the link expired untouched
less than ``PREFILL_AFTER_EXPIRY`` ago and its account may still recover
(``app.password_recovery.expired_link_email``); every other case leaves it
blank. Fictitious accounts, isolated database, simulated mail transport only.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

import main
import app.password_email as password_email
import app.password_tokens as password_tokens
from app.password_recovery import PREFILL_AFTER_EXPIRY
from app.password_recovery_limiter import clear_password_recovery_attempts
from app.password_tokens import PURPOSE_FIRST_ACCESS, PURPOSE_PASSWORD_RESET, issue_password_token
from app.user_accounts import (
    CREDENTIAL_STATE_PERSONAL,
    create_usuario_pending,
    set_usuario_access_active,
    set_usuario_email,
    set_usuario_password_hash,
)
from tests.versioned_test_support import isolated_versioned_app_env

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALERT = "Este link é inválido, expirou ou já foi utilizado."
NEUTRAL = (
    "Se houver uma conta associada a este e-mail, enviaremos as instruções "
    "para redefinição da senha."
)
ALUNO_EMAIL = "aluno.base.versionado@example.com"
PENDING_EMAIL = "lucas.pereira@example.com"
PATHS = {PURPOSE_PASSWORD_RESET: "/redefinir-senha", PURPOSE_FIRST_ACCESS: "/primeiro-acesso"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(password_email, "password_email_status", lambda conn: {"ready": True})
    monkeypatch.setattr(password_email, "get_public_base_url", lambda: "https://sgaa.example.test")

    def fake_send(conn, message):
        assert message.to_address.endswith("@example.com"), "only fictitious recipients"
        sent.append(message)
        return {"ok": True}

    monkeypatch.setattr(password_email, "send_text_email", fake_send)
    clear_password_recovery_attempts()
    with isolated_versioned_app_env(tmp_path, "auth-recovery.db") as environment:
        with main.app.app_context():
            conn = main.get_db_connection()
            aluno = conn.execute(
                "SELECT usuario_id, turma_id, matriz_id FROM alunos WHERE matricula='PPA.TESTE.0001'"
            ).fetchone()
            ids = {"aluno": int(aluno["usuario_id"])}
            set_usuario_password_hash(conn, ids["aluno"], main.hash_password("Antiga#2026"),
                                      credential_state=CREDENTIAL_STATE_PERSONAL)
            ids["pending"] = int(create_usuario_pending(conn, "Lucas Andrade Pereira", PENDING_EMAIL, "aluno").lastrowid)
            conn.execute(
                "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, matriz_id, status)"
                " VALUES (?,?,?,?,?,?,?)",
                (ids["pending"], "Lucas Andrade Pereira", "PPA.TESTE.0003", PENDING_EMAIL,
                 aluno["turma_id"], aluno["matriz_id"], "Ativo"),
            )
            conn.commit()
        yield {**environment, "ids": ids, "sent": sent}
    clear_password_recovery_attempts()


def _issue(usuario_id, purpose, *, expired=False, expired_ago=dt.timedelta(hours=2)):
    with main.app.app_context():
        conn = main.get_db_connection()
        raw_token, token_id = issue_password_token(conn, usuario_id, purpose)
        if expired:
            _expire(conn, token_id, expired_ago)
        conn.commit()
    return raw_token, token_id


def _expire(conn, token_id, ago=dt.timedelta(hours=2)):
    past = (dt.datetime.now(dt.timezone.utc) - ago).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE senha_tokens SET expires_at=? WHERE id=?", (past, token_id))


def _get(client, purpose, raw_token):
    return client.get(f"{PATHS[purpose]}?token={raw_token}")


def _prefill(html):
    match = re.search(r'<input type="email" id="recovery-email" name="email" value="([^"]*)"', html)
    assert match, "the recovery card has no e-mail field"
    return match.group(1)


def _visible(html):
    return re.sub(r"<[^>]+>", "", html)


def _token_from(message):
    link = next(line for line in message.body_text.splitlines() if "token=" in line)
    parts = urlsplit(link.strip())
    return parts.path, parse_qs(parts.query)["token"][0]


def _token_row(token_id):
    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT consumed_at, invalidated_at FROM senha_tokens WHERE id=?", (token_id,)
        ).fetchone()
        return tuple(row)


# --------------------------------------------------------------------------
# The card
# --------------------------------------------------------------------------


def test_an_expired_reset_link_renders_the_recovery_card(env):
    raw_token, _ = _issue(env["ids"]["aluno"], PURPOSE_PASSWORD_RESET, expired=True)
    response = _get(env["client"], PURPOSE_PASSWORD_RESET, raw_token)
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "<title>Link expirado</title>" in html
    assert '<h1 class="login-title">Link expirado</h1>' in html
    assert "Crie uma nova senha pessoal" not in html and "login-subtitle" not in html
    assert re.search(r'<div class="auth-alert" role="alert">\s*<svg[^>]*icon-tabler-alert-circle[^>]*auth-alert-icon', html)
    assert "css/components/auth-alert.css" in html
    assert f"<p>{ALERT}</p>" in html
    assert ("O link de redefinição de senha é válido por 1 hora e pode ser utilizado apenas uma vez. "
            'Informe seu <span class="auth-recovery-nowrap">e-mail</span> para receber um novo link.') in html
    assert '<form method="POST" action="/esqueci-minha-senha" class="login-form">' in html
    assert '<button type="submit">Enviar novo link</button>' in html
    assert '<a class="login-forgot-link" href="/login">Voltar para o login</a>' in html
    assert 'class="auth-recovery-logo"' in html
    assert "css/components/auth-recovery.css" in html
    # The dead token is not carried anywhere in the page.
    assert 'name="token"' not in html and raw_token not in html.split("</head>", 1)[1]
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "strict-origin"


def test_an_expired_untouched_link_prefills_its_own_address(env):
    raw_token, _ = _issue(env["ids"]["aluno"], PURPOSE_PASSWORD_RESET, expired=True)
    html = _get(env["client"], PURPOSE_PASSWORD_RESET, raw_token).get_data(as_text=True)
    assert _prefill(html) == ALUNO_EMAIL
    assert " autofocus" not in html.split('id="recovery-email"', 1)[1].split(">", 1)[0]


def test_the_prefill_lasts_until_the_window_after_expiry_closes(env):
    assert PREFILL_AFTER_EXPIRY == dt.timedelta(hours=24)
    inside, _ = _issue(env["ids"]["aluno"], PURPOSE_PASSWORD_RESET, expired=True,
                       expired_ago=PREFILL_AFTER_EXPIRY - dt.timedelta(minutes=5))
    html = _get(env["client"], PURPOSE_PASSWORD_RESET, inside).get_data(as_text=True)
    assert _prefill(html) == ALUNO_EMAIL


def test_the_prefilled_address_cannot_break_out_of_its_attribute(env):
    # Written past the e-mail rule on purpose: the template must escape it.
    raw_token, _ = _issue(env["ids"]["aluno"], PURPOSE_PASSWORD_RESET, expired=True)
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("UPDATE usuarios SET email=? WHERE id=?", ('a"><b>x@example.com', env["ids"]["aluno"]))
        conn.commit()
    html = _get(env["client"], PURPOSE_PASSWORD_RESET, raw_token).get_data(as_text=True)
    assert _prefill(html) == "a&#34;&gt;&lt;b&gt;x@example.com"
    assert '"><b>' not in html


def test_a_valid_link_still_renders_the_password_form(env):
    raw_token, _ = _issue(env["ids"]["aluno"], PURPOSE_PASSWORD_RESET)
    html = _get(env["client"], PURPOSE_PASSWORD_RESET, raw_token).get_data(as_text=True)
    assert "Crie uma nova senha pessoal para sua conta." in html
    assert 'name="token"' in html and "Link expirado" not in html and ALERT not in html


# --------------------------------------------------------------------------
# When the address stays blank
# --------------------------------------------------------------------------


def _used(env):
    # Used, then opened again once its validity is over: consumption alone blanks it.
    raw_token, token_id = _issue(env["ids"]["aluno"], PURPOSE_PASSWORD_RESET)
    with main.app.app_context():
        conn = main.get_db_connection()
        password_tokens.consume_password_token_and_set_password(
            conn, raw_token, PURPOSE_PASSWORD_RESET, main.hash_password("Nova#2026"))
        _expire(conn, token_id)
        conn.commit()
    return PURPOSE_PASSWORD_RESET, raw_token


def _superseded(env):
    old, old_id = _issue(env["ids"]["aluno"], PURPOSE_PASSWORD_RESET)
    _issue(env["ids"]["aluno"], PURPOSE_PASSWORD_RESET)  # invalidates the live one
    with main.app.app_context():
        conn = main.get_db_connection()
        _expire(conn, old_id)
        conn.commit()
    return PURPOSE_PASSWORD_RESET, old


def _address_changed(env):
    raw_token, _ = _issue(env["ids"]["aluno"], PURPOSE_PASSWORD_RESET, expired=True)
    with main.app.app_context():
        conn = main.get_db_connection()
        set_usuario_email(conn, env["ids"]["aluno"], "mariana.ribeiro@example.com")
        conn.commit()
    return PURPOSE_PASSWORD_RESET, raw_token


def _access_inactive(env):
    # Only the access flag moves, so the eligibility layer is what blanks it.
    raw_token, _ = _issue(env["ids"]["aluno"], PURPOSE_PASSWORD_RESET, expired=True)
    with main.app.app_context():
        conn = main.get_db_connection()
        set_usuario_access_active(conn, env["ids"]["aluno"], False)
        conn.commit()
    return PURPOSE_PASSWORD_RESET, raw_token


def _student_inactive(env):
    raw_token, _ = _issue(env["ids"]["aluno"], PURPOSE_PASSWORD_RESET, expired=True)
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("UPDATE alunos SET status='Inativo' WHERE usuario_id=?", (env["ids"]["aluno"],))
        conn.commit()
    return PURPOSE_PASSWORD_RESET, raw_token


def _expired_long_ago(env):
    raw_token, _ = _issue(env["ids"]["aluno"], PURPOSE_PASSWORD_RESET, expired=True,
                          expired_ago=PREFILL_AFTER_EXPIRY + dt.timedelta(minutes=5))
    return PURPOSE_PASSWORD_RESET, raw_token


def _unknown(env):
    return PURPOSE_PASSWORD_RESET, "A" * 43


def _malformed(env):
    return PURPOSE_PASSWORD_RESET, "not-a-token"


def _other_purpose(env):
    raw_token, _ = _issue(env["ids"]["aluno"], PURPOSE_PASSWORD_RESET, expired=True)
    return PURPOSE_FIRST_ACCESS, raw_token


def _live_but_not_redeemable(env):
    # A live first-access link of an account that already holds a password.
    raw_token, _ = _issue(env["ids"]["aluno"], PURPOSE_FIRST_ACCESS)
    return PURPOSE_FIRST_ACCESS, raw_token


@pytest.mark.parametrize(
    "case",
    [_used, _superseded, _address_changed, _access_inactive, _student_inactive,
     _expired_long_ago, _unknown, _malformed, _other_purpose, _live_but_not_redeemable],
    ids=lambda case: case.__name__.strip("_"),
)
def test_the_address_stays_blank_unless_identification_is_safe(env, case):
    purpose, raw_token = case(env)
    response = _get(env["client"], purpose, raw_token)
    html = response.get_data(as_text=True)
    assert response.status_code == 200 and "Link expirado" in html and ALERT in html
    assert _prefill(html) == ""
    assert "@example.com" not in html.split("</head>", 1)[1]


# --------------------------------------------------------------------------
# The validity is that of the link the resend sends
# --------------------------------------------------------------------------


@pytest.mark.parametrize("purpose", [PURPOSE_PASSWORD_RESET, PURPOSE_FIRST_ACCESS])
@pytest.mark.parametrize(
    ("ttl", "expected"),
    [
        (dt.timedelta(minutes=60), "1 hora"),
        (dt.timedelta(hours=2), "2 horas"),
        (dt.timedelta(minutes=90), "90 minutos"),
        (dt.timedelta(days=1), "1 dia"),
        (dt.timedelta(days=7), "7 dias"),
    ],
)
def test_the_card_states_the_configured_validity_of_a_reset_link(env, monkeypatch, purpose, ttl, expected):
    monkeypatch.setitem(password_tokens.PASSWORD_TOKEN_TTLS, PURPOSE_PASSWORD_RESET, ttl)
    html = _get(env["client"], purpose, "A" * 43).get_data(as_text=True)
    assert f"O link de redefinição de senha é válido por {expected} e pode ser utilizado apenas uma vez." in html


def test_a_dead_first_access_link_states_the_link_it_will_receive(env, monkeypatch):
    # The resend mails a reset link: the first-access validity is not what the user gets.
    monkeypatch.setitem(password_tokens.PASSWORD_TOKEN_TTLS, PURPOSE_FIRST_ACCESS, dt.timedelta(days=3))
    html = _get(env["client"], PURPOSE_FIRST_ACCESS, "A" * 43).get_data(as_text=True)
    assert "válido por 1 hora e" in html and "3 dias" not in html


def test_the_shipped_validity_is_the_configured_one(env):
    assert password_tokens.PASSWORD_RESET_TTL == dt.timedelta(minutes=60)
    for purpose in (PURPOSE_PASSWORD_RESET, PURPOSE_FIRST_ACCESS):
        html = _get(env["client"], purpose, "A" * 43).get_data(as_text=True)
        assert "O link de redefinição de senha é válido por 1 hora e" in html


# --------------------------------------------------------------------------
# Self-service: from the card to a working password, anonymously
# --------------------------------------------------------------------------


def _resend_and_redeem(env, email, password):
    client = env["client"]
    before = len(env["sent"])
    answer = client.post("/esqueci-minha-senha", data={"email": email}).get_data(as_text=True)
    assert NEUTRAL in _visible(answer)
    assert len(env["sent"]) == before + 1
    message = env["sent"][-1]
    assert message.to_address == email and message.subject == "Redefinição de senha do SGAA"
    path, new_token = _token_from(message)
    assert path == "/redefinir-senha"
    redeemed = client.post(path, data={"token": new_token, "senha": password, "confirmacao_senha": password})
    assert redeemed.status_code == 302 and redeemed.headers["Location"].endswith("/login")
    login = client.post("/login", data={"email": email, "senha": password})
    assert login.status_code == 302 and "/aluno/" in login.headers["Location"]


def test_an_expired_reset_link_leads_to_a_new_password_without_an_administrator(env):
    raw_token, _ = _issue(env["ids"]["aluno"], PURPOSE_PASSWORD_RESET, expired=True)
    html = _get(env["client"], PURPOSE_PASSWORD_RESET, raw_token).get_data(as_text=True)
    _resend_and_redeem(env, _prefill(html), "Outra#2026")


def test_an_expired_first_access_link_leads_to_a_first_password_without_an_administrator(env):
    raw_token, _ = _issue(env["ids"]["pending"], PURPOSE_FIRST_ACCESS, expired=True)
    html = _get(env["client"], PURPOSE_FIRST_ACCESS, raw_token).get_data(as_text=True)
    assert "O link de redefinição de senha é válido por 1 hora" in html
    assert _prefill(html) == PENDING_EMAIL
    _resend_and_redeem(env, PENDING_EMAIL, "Primeira#2026")
    with main.app.app_context():
        state = main.get_db_connection().execute(
            "SELECT estado FROM usuario_credenciais WHERE usuario_id=?", (env["ids"]["pending"],)).fetchone()[0]
    assert state == CREDENTIAL_STATE_PERSONAL


def test_a_link_that_expires_while_the_form_is_open_keeps_its_prefill(env):
    raw_token, token_id = _issue(env["ids"]["aluno"], PURPOSE_PASSWORD_RESET)
    assert 'name="token"' in _get(env["client"], PURPOSE_PASSWORD_RESET, raw_token).get_data(as_text=True)
    with main.app.app_context():
        conn = main.get_db_connection()
        _expire(conn, token_id)
        conn.commit()
    response = env["client"].post("/redefinir-senha", data={
        "token": raw_token, "senha": "Tarde#2026", "confirmacao_senha": "Tarde#2026"})
    html = response.get_data(as_text=True)
    assert response.status_code == 200 and "Link expirado" in html
    assert _prefill(html) == ALUNO_EMAIL
    assert _token_row(token_id) == (None, None)  # nothing consumed


def test_the_resend_form_passes_production_https_csrf(env):
    """Production CSRF over HTTPS refuses a POST without a same-origin Referer.

    The dead link's page keeps ``strict-origin`` (its URL carries the token), so
    the card's form sends the bare origin; every other CSRF refusal holds.
    """
    origin = "https://sgaa.example.test"
    own = {"Referer": f"{origin}/"}
    saved = {key: main.app.config.get(key) for key in ("WTF_CSRF_ENABLED", "WTF_CSRF_SSL_STRICT")}
    raw_token, _ = _issue(env["ids"]["aluno"], PURPOSE_PASSWORD_RESET, expired=True)
    try:
        main.app.config.update(WTF_CSRF_ENABLED=True, WTF_CSRF_SSL_STRICT=True)
        client = env["client"]
        page = client.get(f"/redefinir-senha?token={raw_token}", base_url=origin)
        html = page.get_data(as_text=True)
        assert page.headers["Referrer-Policy"] == "strict-origin"
        assert '<meta name="referrer" content="strict-origin" />' in html
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
        form = {"csrf_token": csrf, "email": _prefill(html)}
        for headers, data in (
            ({}, form),
            ({"Referer": "https://attacker.example/"}, form),
            (own, {"email": form["email"]}),
            (own, {**form, "csrf_token": "forged"}),
        ):
            refused = client.post("/esqueci-minha-senha", data=data, headers=headers, base_url=origin)
            assert refused.status_code == 400, (headers, sorted(data))
        assert env["sent"] == []
        accepted = client.post("/esqueci-minha-senha", data=form, headers=own, base_url=origin)
        assert accepted.status_code == 200 and NEUTRAL in _visible(accepted.get_data(as_text=True))
        assert [message.to_address for message in env["sent"]] == [ALUNO_EMAIL]
    finally:
        main.app.config.update(saved)


# --------------------------------------------------------------------------
# Design-system contract
# --------------------------------------------------------------------------


def _source(relative):
    return (PROJECT_ROOT / relative).read_text(encoding="utf-8")


def test_the_recovery_state_has_one_design_system_owner():
    component = _source("templates/components/auth_recovery.html")
    page = _source("templates/set_password.html")
    assert "macro expired_link_card" in component and ALERT in component
    # The page delegates the whole state; it carries no copy of it.
    assert "auth_recovery.expired_link_card(" in page
    assert ALERT not in page and "auth-recovery-" not in page
    assert "Link expirado" in component
    # Its banner is the shared auth alert, not an implementation of its own.
    assert "import auth_feedback" in component and "auth_feedback('Este link" in component
    assert "class=\"auth-alert" not in component


def test_the_recovery_stylesheet_uses_tokens_and_justifies_wrapped_text():
    css = _source("static/css/components/auth-recovery.css")
    rules = dict(re.findall(r"(?m)^([^\s/@{}][^{]*)\{([^}]*)\}", css))
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)), (
        "the recovery state takes its colours from tokens.css only")
    assert "text-align:justify" in rules[".auth-recovery-lead"]
    assert "text-align-last:start" in rules[".auth-recovery-lead"]
    assert not any("alert" in s for s in rules), "the banner belongs to components/auth-alert.css"
    assert not any("login-card" in s or "login-page" in s for s in rules), "the auth shell is not re-opened"
