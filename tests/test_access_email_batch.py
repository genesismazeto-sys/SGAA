"""Targeted access-mail tests: disposable accounts and a simulated transport only."""
from __future__ import annotations

import copy
import re
import threading
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


def test_chromium_real_batch_flow(batch_env, monkeypatch, tmp_path):
    from playwright.sync_api import sync_playwright, expect
    from werkzeug.serving import make_server

    env = batch_env
    monkeypatch.setitem(main.app.config, "WTF_CSRF_ENABLED", True)
    monkeypatch.setitem(main.app.config, "WTF_CSRF_CHECK_DEFAULT", True)
    monkeypatch.setitem(main.app.config, "WTF_CSRF_SSL_STRICT", True)
    server = make_server("127.0.0.1", 0, main.app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            context.add_cookies([{"name": "session", "value": env["client"].get_cookie("session").value, "url": base}])
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("https://**/*", lambda route: route.abort())
            page.goto(base + "/admin/acesso")
            names = ("pending", "sent", "active", "fail", "unknown", "invalid")
            page.locator('#btn-acesso-actions').click()
            page.locator('#access-action-select-all').click()
            selected_ids = {env["ids"][name] for name in names}
            # The existing selector uses Shift ranges and click-to-remove.
            # Select all through its menu, then remove every unwanted row.
            for row in page.locator('#acesso-list [data-user-id]').all():
                if int(row.get_attribute('data-user-id')) not in selected_ids:
                    row.click()
            page.locator('#btn-acesso-actions').click()
            page.locator('#access-action-email').click()
            expect(page.locator('#access-email-summary')).to_contain_text("6 usuário(s) selecionado(s). Escolha")
            expect(page.locator('[data-email-count="first_access"]')).to_have_text("3")
            expect(page.locator('[data-email-count="resend"]')).to_have_text("1")
            expect(page.locator('[data-email-count="password_reset"]')).to_have_text("1")
            expect(page.locator('#access-email-results')).to_contain_text("Destinatário ausente ou inválido")
            page.locator('#access-email-cancel').click()
            expect(page.locator('#access-email-modal')).to_be_hidden()
            assert not env["sent"]
            page.locator('#btn-acesso-actions').click()
            page.locator('#access-action-email').click()
            expect(page.locator('#access-email-submit')).to_be_enabled()
            page.locator('#access-email-categories input[value="resend"]').check()
            page.locator('#access-email-categories input[value="password_reset"]').check()
            expect(page.locator('#access-email-categories')).to_contain_text("já possuem acesso")
            expect(page.locator('#access-email-categories')).to_contain_text("será invalidado")
            document_id = page.evaluate("window.__batchDocument = Math.random()")
            # Real double click: disabled synchronously before the first await.
            page.locator('#access-email-submit').evaluate("el => { el.click(); el.click(); }")
            expect(page.locator('#access-email-summary')).to_contain_text("Concluído: 3 confirmado(s), 1 falha(s)", timeout=20000)
            expect(page.locator('#access-email-summary')).to_contain_text("1 indeterminado(s), 0 não incluído(s), 1 não elegível(is)")
            assert len(env["sent"]) == 5
            assert page.evaluate("window.__batchDocument") == document_id
            for name in ("pending", "sent"):
                expect(page.locator(f'#acesso-list [data-user-id="{env["ids"][name]}"] .status-pill')).to_have_text("Disponibilizado")
            expect(page.locator(f'#acesso-list [data-user-id="{env["ids"]["active"]}"] .status-pill')).to_have_text("Ativo")
            page.screenshot(path=str(tmp_path / "access-email-batch-chromium.png"))
            # Start a fresh, explicit single-recipient operation for an expired link.
            page.locator('#access-email-cancel').click()
            page.locator('#btn-acesso-actions').click()
            page.locator('#access-action-select-all').click()
            page.locator('#access-action-select-all').click()
            page.locator('#btn-acesso-actions').click()
            page.locator(f'#acesso-list [data-user-id="{env["ids"]["expired"]}"]').click()
            page.locator('#btn-acesso-actions').click()
            page.locator('#access-action-email').click()
            expect(page.locator('#access-email-summary')).to_contain_text("1 usuário(s) selecionado(s). Escolha")
            expect(page.locator('[data-email-count="first_access"]')).to_have_text("1")
            page.locator('#access-email-categories input[value="first_access"]').uncheck()
            expect(page.locator('#access-email-submit')).to_be_disabled()
            page.locator('#access-email-categories input[value="first_access"]').check()
            page.locator('#access-email-submit').click()
            expect(page.locator('#access-email-summary')).to_contain_text("Concluído: 1 confirmado(s)")
            assert len(env["sent"]) == 6
            expect(page.locator(f'#acesso-list [data-user-id="{env["ids"]["expired"]}"] .status-pill')).to_have_text("Disponibilizado")
            # Include only reset, explicitly leaving both resend recipients out.
            page.locator('#access-email-cancel').click()
            page.locator('#btn-acesso-actions').click()
            page.locator('#access-action-select-all').click()
            included_ids = {env["ids"][name] for name in ("active", "sent", "expired")}
            for row in page.locator('#acesso-list [data-user-id]').all():
                if int(row.get_attribute('data-user-id')) not in included_ids:
                    row.click()
            page.locator('#btn-acesso-actions').click()
            page.locator('#access-action-email').click()
            expect(page.locator('#access-email-summary')).to_contain_text("3 usuário(s) selecionado(s). Escolha")
            expect(page.locator('#access-email-submit')).to_be_disabled()
            page.locator('#access-email-categories input[value="password_reset"]').check()
            page.locator('#access-email-submit').click()
            expect(page.locator('#access-email-summary')).to_contain_text("Concluído: 1 confirmado(s), 0 falha(s)")
            expect(page.locator('#access-email-summary')).to_contain_text("2 não incluído(s)")
            assert len(env["sent"]) == 7
            expect(page.locator('#access-email-results')).to_contain_text("Categoria não incluída")
            assert not errors, errors
            browser.close()
    finally:
        server.shutdown()
        thread.join(5)
