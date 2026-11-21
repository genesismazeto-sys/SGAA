"""UI-B47 in a real Chromium: Desmarcar sinalização de e-mail from the Ações menu.

A live local server on an isolated database with fictitious data (the harness
of tests/test_activity_documentation_admin_browser.py). The mail transport is
faked and only fictitious ``example.test`` recipients are accepted. Covered at
1440 x 900 and 390 x 844: a flagged selection offers the item and an unflagged
one does not; the confirmation clears the flag, which stays cleared after a
reload; a page left open across a new decision is refused as stale and the
newer flag survives; a new decision raises its own flag; Enviar e-mail still
sends. Screenshots are opt-in (SGAA_EVIDENCE_DIR), outside the repository.
"""
from __future__ import annotations

import json

import main
import app.request_email_dispatch as dispatch_module
import app.services.mail_service as mail_service
from app.request_email_notifications import pending_event_ids
from app.user_accounts import create_usuario_with_access_level, get_usuario_auth_version
from tests.canonical_matrix_test_support import login_admin
from tests.canonical_request_test_support import create_admin_request
from tests.test_activity_documentation_admin_browser import (
    BINARY,
    EVIDENCE,
    Session,
    browser_only,
    workspace,  # noqa: F401  (pytest fixture)
)

STUDENT = ("Mariana Costa Ribeiro", "mariana.ribeiro@example.test")
EVENTS = {
    "dismiss_desktop": "Congresso brasileiro de enfermagem",
    "dismiss_phone": "Semana acadêmica de saúde coletiva",
    "unflagged": "Curso de primeiros socorros",
    "send": "Monitoria de anatomia humana",
    "stale": "Jornada de iniciação científica",
}
JUSTIFICATION = "O comprovante não informa a carga horária do evento."
MENU_ITEM = "#req-action-email-dismiss"
MODAL = "#req-email-dismiss-modal"
VIEWPORTS = (("desktop", 1440, 900), ("phone", 390, 844))


def _js(value):
    return json.dumps(value, ensure_ascii=False)


def _prepare(client, monkeypatch):
    """Fictitious student, five requests, a default e-mail model and a fake transport."""
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("UPDATE alunos SET nome=?, email=? WHERE matricula='PPA.TESTE.0001'", STUDENT)
        conn.execute("UPDATE usuarios SET nome=? WHERE email='aluno.base.versionado@example.com'", STUDENT[:1])
        conn.execute("DELETE FROM configuracoes_presets WHERE tipo='emails'")
        conn.execute(
            "INSERT INTO configuracoes_presets(tipo,preset_id,titulo,texto,assunto,is_default)"
            " VALUES('emails',1,'Resposta da coordenação',"
            "'{saudacao}, {aluno.primeironome}.\n\n{requisicoes}\n\nAtenciosamente, coordenação.',"
            "'Resultado das suas requisições',1)"
        )
        conn.commit()
    ids = {}
    for key, name in EVENTS.items():
        _response, row = create_admin_request(client, name=name)
        ids[key] = row["id"]
        if key != "unflagged":
            _decide(client, ids[key], "Deferida")
    sent = []

    def fake_send(conn_, message):
        assert message.to_address.endswith("@example.test"), "only fictitious recipients"
        sent.append(message.to_address)
        return {"http_status": 202}

    monkeypatch.setattr(dispatch_module, "send_text_email", fake_send)
    monkeypatch.setattr(mail_service, "mail_transport_status", lambda conn_: {
        "ready": True, "message": "", "reason": "", "provider_connected": True})
    return ids, sent


def _decide(client, req_id, status):
    data = {"status": status}
    if status == "Indeferida":
        data["observacao"] = JUSTIFICATION
    assert client.post(f"/admin/processar_requisicao/{req_id}", data=data).status_code == 302


def _new_decision(client, req_id, status="Indeferida"):
    _decide(client, req_id, "Pendente")
    _decide(client, req_id, status)


def _pending():
    with main.app.app_context():
        return pending_event_ids(main.get_db_connection())


def _open(session, width, height):
    phone = width < 768
    session.call("Emulation.setDeviceMetricsOverride",
                 {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": phone})
    session.call("Emulation.setTouchEmulationEnabled", {"enabled": phone, "maxTouchPoints": 5 if phone else 1})
    session.goto("/admin/requisicoes")
    _arm(session)


def _arm(session):
    session.evaluate("window.__errors = []; window.addEventListener('error', e => window.__errors.push(String(e.message))); true")
    if EVIDENCE:
        # Evidence is read with the served font: Inter is requested, then every face settles.
        session.evaluate("document.fonts.load('500 14px Inter').then(() => document.fonts.ready).then(() => true)")


def _reload(session, action):
    """Run ``action`` (which reloads the page) and wait for the new document."""
    session.evaluate("window.__leaving = true; true")
    action()
    session.wait_for("!window.__leaving && document.readyState === 'complete'", timeout=20)
    _arm(session)


def _row(req_id):
    return f'#requisicoes-list .impresso-card[data-req-id="{req_id}"]'


def _select(session, req_id):
    selector = _row(req_id) + " > .cell:nth-child(2)"
    if not session.evaluate("document.querySelector(%s).classList.contains('selected')" % _js(_row(req_id))):
        session.click_in_view(selector)
    assert session.evaluate("document.querySelector(%s).classList.contains('selected')" % _js(_row(req_id)))


def _menu(session):
    session.click_in_view("#btn-req-actions")
    session.wait_for("!document.getElementById('req-actions-menu').hidden")
    session.pump(0.2)
    return session.evaluate("""(() => {
      const item = document.querySelector(%s), send = document.getElementById('req-action-email');
      const box = item.getBoundingClientRect(), menu = document.getElementById('req-actions-menu').getBoundingClientRect();
      // Nothing (the selected row's floating bar included) may sit over the item.
      const menuEl = document.getElementById('req-actions-menu');
      const hitsInside = (el, owner) => {
        const b = el.getBoundingClientRect();
        return [0.1, 0.5, 0.9].every(f => owner.contains(document.elementFromPoint(b.left + b.width * f, b.top + b.height / 2)));
      };
      const hits = [0.1, 0.5, 0.9].map(f => document.elementFromPoint(box.left + box.width * f, box.top + box.height / 2));
      const shownItems = Array.from(menuEl.querySelectorAll('.menu-item')).filter(el => el.getClientRects().length);
      // What is drawn, not the attribute: the menu's item rule outranks [hidden].
      const drawn = item.getClientRects().length > 0 && getComputedStyle(item).display !== 'none';
      return {drawn, disabled: item.disabled, label: item.textContent.trim(),
              visible: drawn && box.width > 0 && box.right <= innerWidth + 0.5 && box.bottom <= innerHeight + 0.5,
              uncovered: drawn && hits.every(el => el && item.contains(el)),
              menuInView: menu.left >= -0.5 && menu.right <= innerWidth + 0.5,
              menuUncovered: shownItems.every(el => hitsInside(el, menuEl)),
              // Every label on one line: the menu is sized with the item it shows.
              // (a Range over the text: the label span is a flex item, one box however it wraps).
              singleLine: shownItems.every(el => { const t = el.querySelector('span');
                if (!t) return true; const r = document.createRange(); r.selectNodeContents(t);
                return new Set(Array.from(r.getClientRects()).map(b => Math.round(b.top))).size === 1; }),
              sendDisabled: send.disabled};
    })()""" % _js(MENU_ITEM))


def _close_menu(session):
    session.evaluate("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'})); true")
    session.pump(0.1)


def _flag_state(session, req_id):
    return session.evaluate("""(() => {
      const row = document.querySelector(%s);
      return {pending: row.getAttribute('data-email-pending'), event: row.getAttribute('data-email-event-id'),
              icon: !!row.querySelector('.req-email-pending')};
    })()""" % _js(_row(req_id)))


def _modal(session):
    return session.evaluate("""(() => {
      const m = document.querySelector(%s), card = m.querySelector('.modal-card').getBoundingClientRect();
      const error = document.getElementById('req-email-dismiss-error');
      const buttons = Array.from(m.querySelectorAll('.modal-footer .btn')).filter(b => !b.hidden);
      // The selected row's floating bar stacks above the dialog layer: it must step aside.
      const bar = document.getElementById('pedido-actions-float');
      const barShown = !!bar && getComputedStyle(bar).visibility !== 'hidden';
      return {open: !m.hidden, barShown, text: document.getElementById('req-email-dismiss-text').textContent,
              error: error.hidden ? '' : error.textContent, confirmDisabled: document.getElementById('req-email-dismiss-confirm').disabled,
              cardInView: card.left >= -0.5 && card.right <= innerWidth + 0.5,
              buttons: buttons.map(b => ({label: b.textContent.trim(), primary: b.classList.contains('primary'),
                                          left: b.getBoundingClientRect().left, width: b.getBoundingClientRect().width})),
              align: getComputedStyle(document.getElementById('req-email-dismiss-text')).textAlign};
    })()""" % _js(MODAL))


def _flash(session):
    return session.evaluate("Array.from(document.querySelectorAll('.flash')).map(f => f.textContent.trim())")


def _shot(session, name):
    session.capture_viewport(name)


def _dismiss_and_reload(session, req_id, tag):
    _select(session, req_id)
    menu = _menu(session)
    assert menu["visible"] and menu["uncovered"] and not menu["disabled"], menu
    assert menu["label"] == "Desmarcar sinalização de e-mail" and menu["menuInView"] and menu["menuUncovered"], menu
    assert menu["singleLine"], menu
    _shot(session, f"{tag}_02_menu_com_sinalizacao")
    session.click_in_view(MENU_ITEM)
    session.wait_for("!document.querySelector(%s).hidden" % _js(MODAL))
    session.pump(0.2)
    modal = _modal(session)
    assert modal["open"] and modal["cardInView"] and not modal["confirmDisabled"] and not modal["barShown"], modal
    assert f"da requisição {req_id} será removida" in modal["text"] and "Nenhum e-mail será enviado" in modal["text"]
    assert [b["label"] for b in modal["buttons"]] == ["Cancelar", "Desmarcar"] and modal["buttons"][-1]["primary"]
    assert modal["align"] == "justify", modal
    _shot(session, f"{tag}_03_confirmacao")
    _reload(session, lambda: session.click_in_view("#req-email-dismiss-confirm"))
    assert _flag_state(session, req_id) == {"pending": "0", "event": "", "icon": False}
    assert "Sinalização de e-mail removida. Nenhum e-mail foi enviado." in _flash(session)
    _shot(session, f"{tag}_04_apos_desmarcar")
    _reload(session, lambda: session.evaluate("location.reload(); true"))
    assert _flag_state(session, req_id) == {"pending": "0", "event": "", "icon": False}
    assert _flash(session) == []
    _shot(session, f"{tag}_05_apos_recarregar")


@browser_only
def test_dismissing_the_pending_email_flag_in_a_real_browser(workspace, monkeypatch):
    client = workspace["client"]
    login_admin(client)
    ids, sent = _prepare(client, monkeypatch)
    client.get("/admin/requisicoes")   # consume the set-up's flashes before the browser takes the session
    session = Session(client, BINARY, workspace["downloads"], workspace["base_url"])
    try:
        for tag, width, height in VIEWPORTS:
            _open(session, width, height)
            if EVIDENCE:
                assert session.evaluate("document.fonts.check('500 14px Inter')"), "Inter did not load"

            # No pending e-mail: the item is not offered (Enviar e-mail stays disabled).
            _select(session, ids["unflagged"])
            menu = _menu(session)
            assert not menu["drawn"] and menu["disabled"] and menu["sendDisabled"], menu
            _shot(session, f"{tag}_01_sem_sinalizacao_menu")
            _close_menu(session)

            # A flagged request: offered, confirmed, cleared, still cleared after a reload.
            target = ids["dismiss_desktop" if tag == "desktop" else "dismiss_phone"]
            before = _pending()
            _dismiss_and_reload(session, target, tag)
            after = _pending()
            assert target not in after and {k: v for k, v in before.items() if k != target} == after

            # A page left open across a new decision: refused, nothing changed, the newer flag kept.
            shown = _flag_state(session, ids["stale"])["event"]
            _new_decision(client, ids["stale"])
            newer = _pending()[ids["stale"]]
            assert str(newer) != shown
            _select(session, ids["stale"])
            assert _menu(session)["visible"]
            session.click_in_view(MENU_ITEM)
            session.wait_for("!document.querySelector(%s).hidden" % _js(MODAL))
            session.click_in_view("#req-email-dismiss-confirm")
            session.wait_for("!document.getElementById('req-email-dismiss-error').hidden")
            modal = _modal(session)
            assert modal["error"].startswith("A sinalização de e-mail mudou desde que a página foi aberta")
            assert modal["confirmDisabled"], modal
            _shot(session, f"{tag}_06_desatualizada")
            assert _pending()[ids["stale"]] == newer
            session.click_in_view("#req-email-dismiss-cancel")
            _reload(session, lambda: session.evaluate("location.reload(); true"))
            assert _flag_state(session, ids["stale"]) == {"pending": "1", "event": str(newer), "icon": True}

        # A new decision on a dismissed request raises its own flag, offered again.
        _new_decision(client, ids["dismiss_desktop"])
        _open(session, 1440, 900)
        state = _flag_state(session, ids["dismiss_desktop"])
        assert state["pending"] == "1" and state["icon"] and state["event"] == str(_pending()[ids["dismiss_desktop"]])
        _select(session, ids["dismiss_desktop"])
        assert _menu(session)["visible"]
        _shot(session, "desktop_07_nova_decisao_sinalizada")
        _close_menu(session)

        # Enviar e-mail is unchanged: preview, explicit send, the flag gone after the reload.
        _select(session, ids["send"])
        _menu(session)
        session.click_in_view("#req-action-email")
        session.wait_for("!document.getElementById('req-email-confirm').disabled", timeout=20)
        _shot(session, "desktop_08_enviar_email_previa")
        _reload(session, lambda: session.click_in_view("#req-email-confirm"))
        assert sent == [STUDENT[1]]
        assert _flag_state(session, ids["send"]) == {"pending": "0", "event": "", "icon": False}
        with main.app.app_context():
            assert main.get_db_connection().execute(
                "SELECT estado FROM requisicao_email_eventos WHERE requisicao_id=? ORDER BY id DESC",
                (ids["send"],)).fetchone()[0] == "sent"
        _shot(session, "desktop_09_enviar_email_enviado")
        assert session.evaluate("window.__errors") == []
    finally:
        session.close()

    # A view-only administrator never sees the item, even on a flagged request.
    with main.app.app_context():
        conn = main.get_db_connection()
        consultor = int(create_usuario_with_access_level(
            conn, "Consultora da coordenação", "consultora@example.test", "test-hash", "admin", "consultivo",
            credential_state="personal").lastrowid)
        conn.commit()
        auth_version = get_usuario_auth_version(conn, consultor)
    with client.session_transaction() as flask_session:
        flask_session.update(user_id=consultor, user_type="admin", user_name="Consultora", auth_version=auth_version)
        flask_session.pop("_flashes", None)
    viewer = Session(client, BINARY, workspace["downloads"], workspace["base_url"])
    try:
        _open(viewer, 1440, 900)
        assert _flag_state(viewer, ids["dismiss_desktop"])["pending"] == "1"
        # The page's read-only rules decide whether this profile selects rows or opens
        # the menu; the clicks are the user's, and the item must stay undrawn either way.
        viewer.click_in_view(_row(ids["dismiss_desktop"]) + " > .cell:nth-child(2)")
        viewer.click_in_view("#btn-req-actions")
        viewer.pump(0.3)
        _shot(viewer, "desktop_10_consultivo_sem_acao")      # what this profile sees
        # This profile's page never opens the menu; open it by force so the check cannot pass vacuously.
        viewer.evaluate("document.getElementById('req-actions-menu').hidden = false; true")
        assert viewer.evaluate("document.getElementById('req-actions-menu').getClientRects().length") > 0
        assert viewer.evaluate("document.querySelector(%s).getClientRects().length" % _js(MENU_ITEM)) == 0
        assert viewer.evaluate("window.__errors") == []
    finally:
        viewer.close()
