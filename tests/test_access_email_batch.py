"""Targeted access-mail tests: disposable accounts and a simulated transport only."""
from __future__ import annotations

import base64
import copy
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

import main
import app.password_email as password_email
from app import import_previews
from app.password_tokens import issue_password_token, mark_password_token_sent
from app.services.mail_service import MailTransportError
from app.user_accounts import create_usuario_pending, create_usuario_with_access_level, set_usuario_access_active
from tests.canonical_matrix_test_support import login_admin
from tests.versioned_test_support import isolated_versioned_app_env

URL = "/admin/acesso/email-lote"


@pytest.fixture
def batch_env(tmp_path, monkeypatch):
    sent = []
    block = {"entered": threading.Event(), "release": threading.Event(), "enabled": False}
    monkeypatch.setattr(password_email, "password_email_status", lambda conn: {"ready": True})
    monkeypatch.setattr("app.views.admin.acesso.password_email_status", lambda conn: {"ready": True})
    monkeypatch.setattr(password_email, "get_public_base_url", lambda: "https://sgaa.example.test")

    def fake_send(conn, message):
        assert message.to_address.endswith("@example.test"), "only fictitious recipients are allowed"
        sent.append(message)
        if block["enabled"]:
            block["entered"].set()
            assert block["release"].wait(10)
        if message.to_address.startswith("fail@"):
            raise MailTransportError("Falha simulada.")
        if message.to_address.startswith("unknown@"):
            raise MailTransportError("Resposta simulada incerta.", indeterminate=True)
        return {"ok": True}

    monkeypatch.setattr(password_email, "send_text_email", fake_send)
    with isolated_versioned_app_env(tmp_path, "access-email-batch.db") as env:
        with main.app.app_context():
            conn = main.get_db_connection()
            ids = {}
            for name in ("pending", "sent", "active", "expired", "invalid", "revoked", "fail", "unknown", "unselected"):
                if name == "active":
                    cursor = create_usuario_with_access_level(conn, "Batch active", "active@example.test", "test-hash", "admin", "consultivo", credential_state="personal")
                else:
                    cursor = create_usuario_pending(conn, f"Batch {name}", f"{name}@example.test", "admin")
                ids[name] = int(cursor.lastrowid)
            for name in ("sent", "expired"):
                _, token_id = issue_password_token(conn, ids[name], "first_access")
                mark_password_token_sent(conn, token_id)
                if name == "expired":
                    conn.execute("UPDATE senha_tokens SET expires_at='2020-01-01 00:00:00',created_at='2019-12-29 00:00:00',sent_at='2019-12-29 00:00:00' WHERE id=?", (token_id,))
            conn.execute("UPDATE usuarios SET email='invalid' WHERE id=?", (ids["invalid"],))
            set_usuario_access_active(conn, ids["revoked"], False)
            conn.commit()
        login_admin(env["client"])
        yield {**env, "ids": ids, "sent": sent, "block": block}


def preview(env, *names):
    response = env["client"].post(URL, json={"action": "preview", "ids": [env["ids"][name] for name in names]})
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.json


def send(env, operation, name, category):
    return env["client"].post(URL, json={"action": "send", "operation": operation, "id": env["ids"][name], "category": category})


def test_mixed_preview_cancel_and_selected_ids_only(batch_env):
    env = batch_env
    plan = preview(env, "pending", "sent", "active", "expired", "invalid", "revoked")
    assert [target["category"] for target in plan["targets"]] == ["first_access", "resend", "password_reset", "first_access", "ineligible", "ineligible"]
    assert not env["sent"]
    assert send(env, plan["operation"], "unselected", "first_access").status_code == 400
    assert send(env, plan["operation"], "active", "first_access").status_code == 400
    assert send(env, plan["operation"], "invalid", "ineligible").status_code == 400
    response = env["client"].post(URL, json={"action": "cancel", "operation": plan["operation"]})
    assert response.status_code == 200
    assert send(env, plan["operation"], "pending", "first_access").status_code == 409
    assert not env["sent"]


def test_partial_results_tokens_and_passwords_preserved(batch_env):
    env = batch_env
    with main.app.app_context():
        conn = main.get_db_connection()
        before = [tuple(row) for row in conn.execute("SELECT u.id,u.senha,c.estado,c.auth_version FROM usuarios u JOIN usuario_credenciais c ON c.usuario_id=u.id ORDER BY u.id")]
    plan = preview(env, "pending", "sent", "active", "expired", "fail", "unknown")
    expected = {"pending": "sent", "sent": "sent", "active": "sent", "expired": "sent", "fail": "failed", "unknown": "indeterminate"}
    for name, status in expected.items():
        category = "password_reset" if name == "active" else "resend" if name == "sent" else "first_access"
        result = send(env, plan["operation"], name, category)
        assert result.status_code == 200
        assert result.json["status"] == status
        assert result.json["access_status"] == ("Ativo" if name == "active" else "Disponibilizado" if status == "sent" else "Pendente")
        # Replaying the exact request returns its durable result without sending.
        assert send(env, plan["operation"], name, category).json == result.json
    assert len(env["sent"]) == 6
    assert "redefinir-senha?token=" in next(message.body_text for message in env["sent"] if message.to_address.startswith("active@"))
    with main.app.app_context():
        conn = main.get_db_connection()
        after = [tuple(row) for row in conn.execute("SELECT u.id,u.senha,c.estado,c.auth_version FROM usuarios u JOIN usuario_credenciais c ON c.usuario_id=u.id ORDER BY u.id")]
        assert after == before
        for name in ("pending", "sent", "active", "expired", "fail", "unknown"):
            tokens = conn.execute("SELECT * FROM senha_tokens WHERE usuario_id=? ORDER BY id", (env["ids"][name],)).fetchall()
            last = tokens[-1]
            assert last["purpose"] == ("password_reset" if name == "active" else "first_access")
            assert bool(last["sent_at"]) == (expected[name] == "sent")
            assert bool(last["invalidated_at"]) == (name == "fail")
            if name == "sent":
                assert tokens[0]["invalidated_at"] is not None
        assert conn.execute("SELECT COUNT(*) FROM senha_tokens WHERE usuario_id=?", (env["ids"]["unselected"],)).fetchone()[0] == 0


@pytest.mark.parametrize("change", ["revoke", "email", "credential", "token"])
def test_state_changed_after_confirmation_is_refused(batch_env, change):
    env = batch_env
    plan = preview(env, "pending")
    with main.app.app_context():
        conn = main.get_db_connection()
        user_id = env["ids"]["pending"]
        if change == "revoke":
            set_usuario_access_active(conn, user_id, False)
        elif change == "email":
            conn.execute("UPDATE usuarios SET email='changed@example.test' WHERE id=?", (user_id,))
        elif change == "credential":
            conn.execute("UPDATE usuario_credenciais SET estado='personal' WHERE usuario_id=?", (user_id,))
        else:
            issue_password_token(conn, user_id, "first_access")
        conn.commit()
    assert send(env, plan["operation"], "pending", "first_access").json["status"] == "stale"
    assert not env["sent"]


def test_concurrent_replay_and_worker_loss_never_resend(batch_env):
    env = batch_env
    plan = preview(env, "pending")
    env["block"]["enabled"] = True
    cookie = env["client"].get_cookie("session").value

    def first_request():
        client = main.app.test_client()
        client.set_cookie("session", cookie)
        return client.post(URL, json={"action": "send", "operation": plan["operation"], "id": env["ids"]["pending"], "category": "first_access"})

    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(first_request)
        try:
            assert env["block"]["entered"].wait(10)
            duplicate = send(env, plan["operation"], "pending", "first_access")
            assert duplicate.json["status"] == "indeterminate"
            assert len(env["sent"]) == 1
        finally:
            env["block"]["release"].set()
        assert pending.result().json["status"] == "sent"
    # A worker that dies after reservation leaves a durable uncertain result.
    other = preview(env, "unknown")
    with main.app.app_context():
        conn = main.get_db_connection()
        payload = import_previews.load(conn, usuario_id=1, token=other["operation"])
        reserved = copy.deepcopy(payload)
        reserved["items"][str(env["ids"]["unknown"])]["state"] = "processing"
        assert import_previews.replace(conn, usuario_id=1, token=other["operation"], expected=payload, payload=reserved)
    assert send(env, other["operation"], "unknown", "first_access").json["status"] == "indeterminate"
    assert len(env["sent"]) == 1


def test_production_csrf_authorization_and_preview_ownership(batch_env, monkeypatch):
    env = batch_env
    origin = "https://sgaa.example.test"
    monkeypatch.setitem(main.app.config, "WTF_CSRF_ENABLED", True)
    monkeypatch.setitem(main.app.config, "WTF_CSRF_CHECK_DEFAULT", True)
    monkeypatch.setitem(main.app.config, "WTF_CSRF_SSL_STRICT", True)
    # Move the existing fictitious administrator session to the HTTPS hostname.
    env["client"].set_cookie("session", env["client"].get_cookie("session").value, domain="sgaa.example.test")
    page = env["client"].get("/admin/acesso", base_url=origin)
    csrf = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', page.text).group(1)
    body = {"action": "preview", "ids": [env["ids"]["pending"]]}
    good_headers = {"X-CSRFToken": csrf, "Referer": origin + "/"}
    for headers in ({}, {"X-CSRFToken": "forged", "Referer": origin + "/"}, {"X-CSRFToken": csrf}, {"X-CSRFToken": csrf, "Referer": "https://attacker.example/"}):
        assert env["client"].post(URL, json=body, base_url=origin, headers=headers).status_code == 400
    plan = env["client"].post(URL, json=body, base_url=origin, headers=good_headers)
    assert plan.status_code == 200
    dispatch = {"action": "send", "operation": plan.json["operation"], "id": env["ids"]["pending"], "category": "first_access"}
    assert env["client"].post(URL, json=dispatch, base_url=origin, headers={"Referer": origin + "/"}).status_code == 400
    assert env["client"].post(URL, json=dispatch, base_url=origin, headers=good_headers).json["status"] == "sent"
    # A non-admin session cannot use the operation even with valid CSRF.
    with env["client"].session_transaction(base_url=origin) as session:
        session["user_type"] = "aluno"
    assert env["client"].post(URL, json=body, base_url=origin, headers=good_headers).status_code in (302, 403)
    assert len(env["sent"]) == 1


def test_invalid_recipient_does_not_invalidate_previous_link(batch_env):
    env = batch_env
    with main.app.app_context():
        conn = main.get_db_connection()
        before = conn.execute("SELECT COUNT(*) FROM senha_tokens").fetchone()[0]
        outcome = password_email.issue_and_send_password_email(conn, usuario_id=env["ids"]["sent"], recipient="invalid", user_name="test", purpose="first_access")
        assert outcome.status == "failed"
        assert conn.execute("SELECT COUNT(*) FROM senha_tokens").fetchone()[0] == before
        assert conn.execute("SELECT invalidated_at FROM senha_tokens WHERE usuario_id=?", (env["ids"]["sent"],)).fetchone()[0] is None


def test_preview_validation_missing_accounts_and_owner_isolation(batch_env):
    env = batch_env
    for ids in ([], ["1"], [True], [-1], [1] * 501):
        assert env["client"].post(URL, json={"action": "preview", "ids": ids}).status_code == 400
    plan = env["client"].post(URL, json={"action": "preview", "ids": [999999, env["ids"]["pending"]]}).json
    assert plan["targets"][0]["category"] == "ineligible"
    assert "não encontrado" in plan["targets"][0]["reason"]
    with main.app.app_context():
        conn = main.get_db_connection()
        assert import_previews.load(conn, usuario_id=env["ids"]["pending"], token=plan["operation"]) is None
        conn.execute("DELETE FROM usuario_credenciais WHERE usuario_id=?", (env["ids"]["pending"],))
        conn.commit()
    assert preview(env, "pending")["targets"][0]["category"] == "ineligible"
    assert not env["sent"]


# --------------------------------------------------------------------------
# Real Chromium (tests/cdp_browser_support): every request the page makes is
# answered by the test client, so the simulated transport above is the only
# "provider" and only fictitious @example.test recipients exist.
# --------------------------------------------------------------------------

cdp = pytest.importorskip("tests.cdp_browser_support")
BINARY = cdp.find_chromium()
browser_only = pytest.mark.skipif(BINARY is None, reason="no Chromium binary for the browser harness")
SHIFT = 8  # CDP Input modifier bit


class _SendGate(cdp.BrowserSession):
    """A page whose ``hold_at``-th send (0-based) is left unanswered.

    Freezing one request is what lets a test read the dialog mid-batch, as an
    administrator sees it while the provider is still answering.
    """

    def __init__(self, client, binary):
        self.hold_at = None
        self.sends = 0
        self.held = None
        super().__init__(client, binary)

    def _serve(self, params):
        request = params["request"]
        body = request.get("postData") or "".join(
            base64.b64decode(entry.get("bytes", "")).decode("utf-8")
            for entry in request.get("postDataEntries") or ()
        )
        if request["url"].endswith(URL) and '"action":"send"' in body:
            if self.sends == self.hold_at and self.held is None:
                self.held = params
                return
            self.sends += 1
        super()._serve(params)

    def wait_for_held(self, timeout=15.0):
        deadline = time.time() + timeout
        while self.held is None:
            assert time.time() < deadline, "the send to hold never arrived"
            self.pump(0.05)

    def release(self):
        held, self.held, self.hold_at = self.held, None, None
        self.sends += 1
        super()._serve(held)


@pytest.fixture
def page(batch_env):
    session = _SendGate(batch_env["client"], BINARY)
    try:
        yield session
    finally:
        session.close()


def _text(page, selector):
    return page.evaluate("document.querySelector(%s).textContent" % json.dumps(selector))


def _prop(page, selector, name):
    return page.evaluate("document.querySelector(%s)[%s]" % (json.dumps(selector), json.dumps(name)))


def _wait_text(page, selector, fragment, timeout=20.0):
    page.wait_for(
        "(document.querySelector(%s)?.textContent || '').includes(%s)" % (json.dumps(selector), json.dumps(fragment)),
        timeout=timeout,
    )


def _row(env, name):
    return f'#acesso-list [data-user-id="{env["ids"][name]}"] .cell:nth-child(2)'


def _row_ids(page, *, selected=False):
    return page.evaluate(
        "Array.from(document.querySelectorAll('#acesso-list .impresso-card%s[data-user-id]'))"
        ".map(r => Number(r.dataset.userId))" % (".selected" if selected else "")
    )


def _menu(page, item):
    """Click an item of the actions menu, opening the menu only if it is closed."""
    if page.evaluate("document.querySelector('#access-actions-menu').hidden"):
        page.click_in_view("#btn-acesso-actions")
    assert page.evaluate("!document.querySelector('#access-actions-menu').hidden")
    page.click(item)
    page.pump(0.2)


def _select_exactly(page, env, names):
    """Select exactly these rows with real clicks: select all, drop the rest."""
    if _row_ids(page, selected=True):
        page.click_in_view("h1.main-title")  # an outside click clears the selection
    _menu(page, "#access-action-select-all")
    wanted = {env["ids"][name] for name in names}
    for user_id in _row_ids(page):
        if user_id not in wanted:
            page.click_in_view(f'#acesso-list [data-user-id="{user_id}"] .cell:nth-child(2)')
    assert sorted(_row_ids(page, selected=True)) == sorted(wanted)


def _open_email(page):
    _menu(page, "#access-action-email")
    _wait_text(page, "#access-email-summary", "Escolha as categorias")


def _check(page, selector):
    page.click_in_view(selector)
    assert _prop(page, selector, "checked") is True


@browser_only
def test_chromium_real_batch_flow(batch_env, page, monkeypatch):
    env = batch_env
    monkeypatch.setitem(main.app.config, "WTF_CSRF_ENABLED", True)
    monkeypatch.setitem(main.app.config, "WTF_CSRF_CHECK_DEFAULT", True)
    page.goto("/admin/acesso")
    page.evaluate("window.__errors = []; window.addEventListener('error', e => window.__errors.push(String(e.message))); true")
    _select_exactly(page, env, ("pending", "sent", "active", "fail", "unknown", "invalid"))
    _open_email(page)
    assert "6 usuário(s) selecionado(s). Escolha" in _text(page, "#access-email-summary")
    counts = {key: _text(page, f'[data-email-count="{key}"]') for key in ("first_access", "resend", "password_reset")}
    assert counts == {"first_access": "3", "resend": "1", "password_reset": "1"}
    assert "Destinatário ausente ou inválido" in _text(page, "#access-email-results")
    # Only first access is preselected: the categories that reach an account
    # that already has access, or replace a live link, wait to be chosen.
    checked = {key: _prop(page, f'#access-email-categories input[value="{key}"]', "checked") for key in counts}
    assert checked == {"first_access": True, "resend": False, "password_reset": False}
    assert _prop(page, "#access-email-replace", "hidden") is True
    page.click_in_view("#access-email-cancel")
    page.wait_for("document.querySelector('#access-email-modal').hidden")
    assert not env["sent"]

    _open_email(page)
    page.wait_for("!document.querySelector('#access-email-submit').disabled")
    _check(page, '#access-email-categories input[value="resend"]')
    _check(page, '#access-email-categories input[value="password_reset"]')
    assert "já possuem acesso" in _text(page, "#access-email-categories")
    assert "será invalidado" in _text(page, "#access-email-categories")
    # Choosing them is not enough: the invalidation is acknowledged separately.
    assert _prop(page, "#access-email-replace", "hidden") is False
    warning = _text(page, "#access-email-replace-text")
    assert "Reenvio para 1 usuário(s)" in warning and "Redefinição para 1 conta(s)" in warning
    assert _prop(page, "#access-email-submit", "disabled") is True
    _check(page, "#access-email-replace-ack")
    assert _prop(page, "#access-email-submit", "disabled") is False
    document_id = page.evaluate("window.__batchDocument = Math.random()")
    # Real double click: disabled synchronously before the first await.
    page.evaluate("(() => { const el = document.querySelector('#access-email-submit'); el.click(); el.click(); return true; })()")
    _wait_text(page, "#access-email-summary", "Concluído: 3 confirmado(s), 1 falha(s)")
    assert "1 indeterminado(s), 0 não incluído(s), 1 não elegível(is)" in _text(page, "#access-email-summary")
    assert len(env["sent"]) == 5
    assert page.evaluate("window.__batchDocument") == document_id
    for name in ("pending", "sent"):
        assert _text(page, f'#acesso-list [data-user-id="{env["ids"][name]}"] .status-pill') == "Disponibilizado"
    assert _text(page, f'#acesso-list [data-user-id="{env["ids"]["active"]}"] .status-pill') == "Ativo"
    assert _text(page, "#access-email-progress-state") == "Concluído com pendências"

    # A fresh, explicit single-recipient operation for an expired link.
    page.click_in_view("#access-email-cancel")
    _select_exactly(page, env, ("expired",))
    _open_email(page)
    assert "1 usuário(s) selecionado(s). Escolha" in _text(page, "#access-email-summary")
    assert _text(page, '[data-email-count="first_access"]') == "1"
    page.click_in_view('#access-email-categories input[value="first_access"]')
    assert _prop(page, "#access-email-submit", "disabled") is True
    _check(page, '#access-email-categories input[value="first_access"]')
    # First access alone replaces no live link: nothing extra to acknowledge.
    assert _prop(page, "#access-email-replace", "hidden") is True
    page.click_in_view("#access-email-submit")
    _wait_text(page, "#access-email-summary", "Concluído: 1 confirmado(s)")
    assert len(env["sent"]) == 6
    assert _text(page, f'#acesso-list [data-user-id="{env["ids"]["expired"]}"] .status-pill') == "Disponibilizado"

    # Include only the reset, explicitly leaving both resend recipients out.
    page.click_in_view("#access-email-cancel")
    _select_exactly(page, env, ("active", "sent", "expired"))
    _open_email(page)
    assert "3 usuário(s) selecionado(s). Escolha" in _text(page, "#access-email-summary")
    assert _prop(page, "#access-email-submit", "disabled") is True
    _check(page, '#access-email-categories input[value="password_reset"]')
    assert _prop(page, "#access-email-submit", "disabled") is True
    _check(page, "#access-email-replace-ack")
    page.click_in_view("#access-email-submit")
    _wait_text(page, "#access-email-summary", "Concluído: 1 confirmado(s), 0 falha(s)")
    assert "2 não incluído(s)" in _text(page, "#access-email-summary")
    assert len(env["sent"]) == 7
    assert "Categoria não incluída" in _text(page, "#access-email-results")
    assert page.evaluate("window.__errors") == []


@browser_only
def test_chromium_active_accounts_are_never_included_by_default(batch_env, page):
    env = batch_env
    page.goto("/admin/acesso")
    _select_exactly(page, env, ("pending", "active", "sent"))
    _open_email(page)
    assert _text(page, '[data-email-count="password_reset"]') == "1"
    assert _prop(page, '#access-email-categories input[value="password_reset"]', "checked") is False
    assert _prop(page, '#access-email-categories input[value="resend"]', "checked") is False
    page.click_in_view("#access-email-submit")
    _wait_text(page, "#access-email-summary", "Concluído:")
    assert [message.to_address for message in env["sent"]] == ["pending@example.test"]
    assert "2 não incluído(s)" in _text(page, "#access-email-summary")
    with main.app.app_context():
        conn = main.get_db_connection()
        assert conn.execute(
            "SELECT COUNT(*) FROM senha_tokens WHERE usuario_id=?", (env["ids"]["active"],)
        ).fetchone()[0] == 0


def _seed_batch(count):
    with main.app.app_context():
        conn = main.get_db_connection()
        for number in range(1, count + 1):
            create_usuario_pending(conn, f"Lote {number:02d}", f"lote{number:02d}@example.test", "admin")
        conn.commit()


PROGRESS_STATE = """(() => {
  const q = s => document.querySelector(s);
  const section = q('#access-email-progress'), track = q('#access-email-progress-track');
  const body = q('#access-email-modal .modal-body'), cs = getComputedStyle(body);
  const tally = k => q(`[data-email-tally="${k}"] strong`).textContent;
  const box = section.getBoundingClientRect();
  return {
    hidden: section.hidden, state: section.dataset.state,
    label: q('#access-email-progress-label').textContent, percent: q('#access-email-progress-percent').textContent,
    now: track.getAttribute('aria-valuenow'), max: track.getAttribute('aria-valuemax'),
    valuetext: track.getAttribute('aria-valuetext'), role: track.getAttribute('role'),
    pill: q('#access-email-progress-state').textContent, pillClass: q('#access-email-progress-state').className,
    sent: tally('sent'), failed: tally('failed'), indeterminate: tally('indeterminate'),
    fill: q('#access-email-progress-track .progress-bar').getBoundingClientRect().width,
    trackW: track.clientWidth, sectionW: box.width, sectionTop: box.top, sectionBottom: box.bottom,
    bodyContentW: body.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight),
    innerH: innerHeight, docOverflowX: document.documentElement.scrollWidth - innerWidth,
    nativeProgress: document.querySelectorAll('#access-email-modal progress').length,
  };
})()"""


@browser_only
@pytest.mark.parametrize(
    ("count", "width", "height", "announcements"),
    # Announcements: the start, every send before the last one of a short
    # batch (each tenth of a long one), and the final summary.
    [(1, 1440, 900, 2), (4, 390, 844, 5), (30, 1440, 900, 11)],
    ids=["one-desktop", "several-phone", "many-desktop"],
)
def test_chromium_progress_reports_each_send_and_the_final_state(batch_env, page, count, width, height, announcements):
    env = batch_env
    _seed_batch(count)
    page.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": width < 600})
    page.goto("/admin/acesso")
    page.evaluate(
        "(() => { const i = document.querySelector('#busca-acesso'); i.value = 'lote';"
        " i.dispatchEvent(new Event('input', {bubbles: true})); return true; })()"
    )
    _menu(page, "#access-action-select-all")  # only the rows the search left visible
    _open_email(page)
    assert f"{count} usuário(s) selecionado(s)." in _text(page, "#access-email-summary")
    page.evaluate(
        "(() => { window.__said = []; const live = document.querySelector('#access-email-progress-live');"
        " new MutationObserver(() => window.__said.push(live.textContent))"
        ".observe(live, {childList: true, characterData: true, subtree: true}); return true; })()"
    )
    halfway = count // 2
    page.hold_at = halfway
    page.click_in_view("#access-email-submit")
    page.wait_for_held()
    page.pump(0.4)  # the DS fill animates its width

    mid = page.evaluate(PROGRESS_STATE)
    assert mid["nativeProgress"] == 0
    assert mid["hidden"] is False and mid["role"] == "progressbar" and mid["state"] == "running"
    assert mid["label"] == f"Enviando {halfway + 1} de {count}"
    assert (mid["now"], mid["max"]) == (str(halfway), str(count))
    assert mid["valuetext"] == f"{halfway} de {count} envio(s) processado(s)"
    assert mid["percent"] == f"{round(halfway * 100 / count)}%"
    assert abs(mid["fill"] / mid["trackW"] - halfway / count) < 0.02
    assert mid["pill"] == "Em andamento" and "status-info" in mid["pillClass"]
    assert (mid["sent"], mid["failed"], mid["indeterminate"]) == (str(halfway), "0", "0")
    # The full width of the dialog body, in view, with no sideways page scroll.
    assert abs(mid["sectionW"] - mid["bodyContentW"]) < 1 and mid["sectionW"] > 300
    assert mid["sectionTop"] >= 0 and mid["sectionBottom"] <= mid["innerH"]
    assert mid["docOverflowX"] <= 0

    page.release()
    page.wait_for("document.querySelector('#access-email-progress').dataset.state !== 'running'", timeout=60)
    page.pump(0.4)
    end = page.evaluate(PROGRESS_STATE)
    assert end["state"] == "done-ok"
    assert end["label"] == f"Envio concluído: {count} de {count} processado(s)"
    assert (end["now"], end["max"], end["percent"]) == (str(count), str(count), "100%")
    assert abs(end["fill"] - end["trackW"]) < 1
    assert end["pill"] == "Concluído" and "status-positive" in end["pillClass"]
    assert (end["sent"], end["failed"], end["indeterminate"]) == (str(count), "0", "0")
    assert f"Concluído: {count} confirmado(s), 0 falha(s)" in _text(page, "#access-email-summary")
    assert len(env["sent"]) == count
    said = page.evaluate("window.__said")
    assert len(said) == announcements, said
    assert said[0] == f"Envio iniciado: {count} destinatário(s)." and said[-1].startswith("Concluído:")


@browser_only
def test_chromium_failures_mark_the_final_state_as_needing_attention(batch_env, page):
    env = batch_env
    page.goto("/admin/acesso")
    _select_exactly(page, env, ("pending", "fail", "unknown"))
    _open_email(page)
    page.click_in_view("#access-email-submit")
    page.wait_for("document.querySelector('#access-email-progress').dataset.state !== 'running'", timeout=30)
    end = page.evaluate(PROGRESS_STATE)
    assert end["state"] == "done-attention"
    assert end["pill"] == "Concluído com pendências" and "status-caution" in end["pillClass"]
    assert (end["sent"], end["failed"], end["indeterminate"]) == ("1", "1", "1")
    tones = page.evaluate(
        "['sent', 'failed', 'indeterminate'].map(k => document.querySelector(`[data-email-tally=\"${k}\"]`).className)"
    )
    assert "status-positive" in tones[0] and "status-negative" in tones[1] and "status-caution" in tones[2]
    assert len(env["sent"]) == 3
