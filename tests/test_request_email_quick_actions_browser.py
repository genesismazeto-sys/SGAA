"""UI-B49 in a real Chromium: quick actions from the pending-email icon.

A live local server on an isolated database with fictitious data (the harness
of tests/test_activity_documentation_admin_browser.py); the mail transport is
faked and must never be reached here. At 1440 x 900 and 390 x 844: the blue
and the red icon open the same three-action dialog for their own request,
whatever rows are selected; Cancelar and Escape change nothing and give focus
back to the icon; Desmarcar clears that request's flag only; a stale row keeps
its newer flag; Enviar opens the existing preview and sends nothing; a
read-only profile cannot activate anything; the icon has not moved. The Ações
menu path is tests/test_request_email_flag_dismissal_browser.py. Screenshots
are opt-in (SGAA_EVIDENCE_DIR), outside the repository.
"""
from __future__ import annotations

import json

import main
import app.request_email_dispatch as dispatch_module
import app.services.mail_service as mail_service
from app.request_email_notifications import attach_events_to_send, failed_request_ids, pending_event_ids
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
    "desktop": "Congresso brasileiro de enfermagem",
    "phone": "Semana acadêmica de saúde coletiva",
    "failed": "Monitoria de anatomia humana",
    "failed_dismiss": "Visita técnica ao hospital universitário",
    "send": "Jornada de iniciação científica",
    "stale": "Oficina de escrita acadêmica",
    "kept": "Palestra sobre ética profissional",
    "unflagged": "Curso de primeiros socorros",
}
MODAL = "#req-email-quick-modal"
PENDING_LABEL = "E-mail pendente de envio"
FAILED_LABEL = "E-mail pendente — última tentativa falhou."


def _js(value):
    return json.dumps(value, ensure_ascii=False)


def _decide(client, req_id, status):
    data = {"status": status}
    if status == "Indeferida":
        data["observacao"] = "O comprovante não informa a carga horária do evento."
    assert client.post(f"/admin/processar_requisicao/{req_id}", data=data).status_code == 302


def _pending():
    with main.app.app_context():
        return pending_event_ids(main.get_db_connection())


def _prepare(client, monkeypatch):
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("UPDATE alunos SET nome=?, email=? WHERE matricula='PPA.TESTE.0001'", STUDENT)
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
            _decide(client, row["id"], "Deferida")
    with main.app.app_context():
        conn = main.get_db_connection()
        for key in ("failed", "failed_dismiss"):
            envio = conn.execute(
                "INSERT INTO email_envios(aluno_id,destinatario,assunto,corpo,status,tentativas,ultimo_erro,"
                "idempotency_key) SELECT aluno_id, ?, 'Resultado das suas requisições', 'Corpo', 'failed', 1, "
                "'Falha simulada.', ? FROM requisicoes WHERE id=? RETURNING id",
                (STUDENT[1], f"quick-{key}", ids[key]),
            ).fetchone()[0]
            attach_events_to_send(conn, event_ids=[pending_event_ids(conn, [ids[key]])[ids[key]]],
                                  email_envio_id=envio)
        conn.commit()
    sent = []
    monkeypatch.setattr(dispatch_module, "send_text_email", lambda conn_, message: sent.append(message) or {})
    monkeypatch.setattr(mail_service, "mail_transport_status", lambda conn_: {
        "ready": True, "message": "", "reason": "", "provider_connected": True})
    client.get("/admin/requisicoes")   # consume the set-up's flashes before the browser takes the session
    return ids, sent


def _row(req_id):
    return f'#requisicoes-list .impresso-card[data-req-id="{req_id}"]'


def _icon(req_id):
    return _row(req_id) + " .req-email-flag"


def _arm(session):
    session.evaluate("window.__errors = []; window.addEventListener('error', e => window.__errors.push(String(e.message))); true")
    if EVIDENCE:
        session.evaluate("document.fonts.load('500 14px Inter').then(() => document.fonts.ready).then(() => true)")


def _open(session, width, height):
    phone = width < 768
    session.call("Emulation.setDeviceMetricsOverride",
                 {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": phone})
    session.call("Emulation.setTouchEmulationEnabled", {"enabled": phone, "maxTouchPoints": 5 if phone else 1})
    session.goto("/admin/requisicoes")
    _arm(session)


def _reload(session, action):
    session.evaluate("window.__leaving = true; true")
    action()
    session.wait_for("!window.__leaving && document.readyState === 'complete'", timeout=20)
    _arm(session)


def _selected(session):
    return session.evaluate(
        "Array.from(document.querySelectorAll('#requisicoes-list .impresso-card.selected')).map(r => r.getAttribute('data-req-id'))")


def _click_row(session, req_id, *, shift=False):
    session.click_in_view(_row(req_id) + " > .cell:nth-child(2)", modifiers=8 if shift else 0)


def _geometry(session):
    """Every pending icon's box against its cell and row (§2 of the SPEC: 7 / 7 / 9 / 9)."""
    return session.evaluate("""Array.from(document.querySelectorAll('#requisicoes-list .impresso-card:not(.header)'))
      .filter(r => r.querySelector('.req-email-pending')).map(r => {
        const i = r.querySelector('.req-email-pending').getBoundingClientRect();
        const c = r.querySelector('.req-email-cell').getBoundingClientRect(), row = r.getBoundingClientRect();
        return [+(i.left - c.left).toFixed(2), +(c.right - i.right).toFixed(2),
                +(i.top - row.top).toFixed(2), +(row.bottom - i.bottom).toFixed(2), i.width, i.height];
      })""")


def _dialog(session):
    return session.evaluate("""(() => {
      const m = document.querySelector(%s), card = m.querySelector('.modal-card').getBoundingClientRect();
      const footer = m.querySelector('.modal-footer'), fb = footer.getBoundingClientRect(), cs = getComputedStyle(footer);
      const buttons = Array.from(footer.querySelectorAll('.btn')).filter(b => !b.hidden);
      const rects = buttons.map(b => b.getBoundingClientRect());
      const inner = [fb.left + parseFloat(cs.paddingLeft), fb.right - parseFloat(cs.paddingRight)];
      const bar = document.getElementById('pedido-actions-float');
      const error = document.getElementById('req-email-quick-error');
      return {open: !m.hidden, title: document.getElementById('req-email-quick-label').textContent.trim(),
              text: document.getElementById('req-email-quick-text').textContent.trim(),
              error: error.hidden ? '' : error.textContent.trim(),
              labels: buttons.map(b => b.textContent.trim()), primaryLast: buttons[buttons.length - 1].classList.contains('primary'),
              disabled: buttons.map(b => b.disabled),
              gaps: [Math.min(...rects.map(r => r.left)) - inner[0], inner[1] - Math.max(...rects.map(r => r.right))],
              tops: rects.map(r => Math.round(r.top)), fill: rects.reduce((a, r) => a + r.width, 0),
              inner: inner[1] - inner[0],
              cardInView: card.left >= -0.5 && card.right <= innerWidth + 0.5,
              focus: document.activeElement && document.activeElement.id,
              barShown: !!bar && getComputedStyle(bar).visibility !== 'hidden'};
    })()""" % _js(MODAL))


def _wait_open(session):
    session.wait_for("!document.querySelector(%s).hidden" % _js(MODAL))
    session.pump(0.2)


def _flag_in_row(session, req_id):
    """Whatever the row still shows of the flag: any icon (blue or red), its button, its data."""
    return session.evaluate("""(() => {
      const r = document.querySelector(%s);
      return {icons: r.querySelectorAll('.req-email-pending').length, red: r.querySelectorAll('.req-email-pending.is-error').length,
              buttons: r.querySelectorAll('.req-email-flag').length,
              pending: r.getAttribute('data-email-pending'), event: r.getAttribute('data-email-event-id')};
    })()""" % _js(_row(req_id)))


NO_FLAG = {"icons": 0, "red": 0, "buttons": 0, "pending": "0", "event": ""}


def _failed_ids():
    with main.app.app_context():
        return failed_request_ids(main.get_db_connection())


def _closed(session):
    return session.evaluate("document.querySelector(%s).hidden" % _js(MODAL))


def _shot(session, name):
    session.capture_viewport(name)


@browser_only
def test_quick_actions_from_the_pending_email_icon(workspace, monkeypatch):
    client = workspace["client"]
    login_admin(client)
    ids, sent = _prepare(client, monkeypatch)
    session = Session(client, BINARY, workspace["downloads"], workspace["base_url"])
    try:
        for tag, width, height in (("desktop", 1440, 900), ("phone", 390, 844)):
            _open(session, width, height)
            if EVIDENCE:
                assert session.evaluate("document.fonts.check('500 14px Inter')"), "Inter did not load"
            assert all(g == [7, 7, 9, 9, 14, 14] for g in _geometry(session)), _geometry(session)

            # A selection elsewhere is left exactly as it is.
            _click_row(session, ids["kept"])
            _click_row(session, ids["unflagged"], shift=True)
            selection = _selected(session)
            assert str(ids["kept"]) in selection and str(ids[tag]) not in selection, selection

            # Blue icon: the three-action dialog for this request.
            before = _pending()
            session.click_in_view(_icon(ids[tag]))
            _wait_open(session)
            dialog = _dialog(session)
            assert dialog["title"] == PENDING_LABEL and dialog["text"] == f"Requisição {ids[tag]} · {STUDENT[0]}"
            assert dialog["labels"] == ["Cancelar", "Desmarcar", "Enviar"] and dialog["primaryLast"], dialog
            assert dialog["focus"] == "req-email-quick-send" and not dialog["barShown"] and dialog["cardInView"]
            if tag == "desktop":
                assert abs(dialog["gaps"][0] - dialog["gaps"][1]) <= 2, dialog      # centred
            else:
                assert len(set(dialog["tops"])) == 1 and dialog["fill"] >= dialog["inner"] - 2 * 8 - 1, dialog
            assert _selected(session) == selection
            _shot(session, f"{tag}_dialogo")

            # Cancelar: nothing changes; the focus returns to the icon.
            session.click_in_view("#req-email-quick-cancel")
            assert _closed(session) and _pending() == before and _selected(session) == selection
            assert session.evaluate("document.activeElement === document.querySelector(%s)" % _js(_icon(ids[tag])))

            # Red icon: the same dialog, titled as a failed attempt; Escape closes it.
            session.click_in_view(_icon(ids["failed"]))
            _wait_open(session)
            dialog = _dialog(session)
            assert dialog["title"] == FAILED_LABEL and dialog["labels"] == ["Cancelar", "Desmarcar", "Enviar"]
            _shot(session, f"{tag}_dialogo_falha")
            session.call("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Escape", "code": "Escape", "windowsVirtualKeyCode": 27})
            session.call("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Escape", "code": "Escape", "windowsVirtualKeyCode": 27})
            session.pump(0.1)
            assert _closed(session) and _pending() == before

            # A stale row: refused, the newer flag kept, Desmarcar disabled, Enviar still offered.
            shown = session.evaluate("document.querySelector(%s).getAttribute('data-email-event-id')" % _js(_row(ids["stale"])))
            _decide(client, ids["stale"], "Pendente")
            _decide(client, ids["stale"], "Indeferida")
            newer = _pending()[ids["stale"]]
            assert str(newer) != shown
            session.click_in_view(_icon(ids["stale"]))
            _wait_open(session)
            session.click_in_view("#req-email-quick-dismiss")
            session.wait_for("!document.getElementById('req-email-quick-error').hidden")
            dialog = _dialog(session)
            assert dialog["error"].startswith("A sinalização de e-mail mudou desde que a página foi aberta")
            assert dialog["disabled"] == [False, True, False], dialog
            assert _pending()[ids["stale"]] == newer
            session.click_in_view("#req-email-quick-cancel")

            # Desmarcar, by keyboard: only this request's flag goes; no second confirmation.
            session.evaluate("document.querySelector(%s).focus(); true" % _js(_icon(ids[tag])))
            session.press_enter()
            _wait_open(session)
            expected = {k: v for k, v in _pending().items() if k != ids[tag]}
            _reload(session, lambda: session.click_in_view("#req-email-quick-dismiss"))
            assert _pending() == expected
            assert _flag_in_row(session, ids[tag]) == NO_FLAG       # gone, not turned red
            assert "Sinalização de e-mail removida. Nenhum e-mail foi enviado." in session.evaluate(
                "Array.from(document.querySelectorAll('.flash')).map(f => f.textContent.trim())")
            _reload(session, lambda: session.evaluate("location.reload(); true"))
            assert _flag_in_row(session, ids[tag]) == NO_FLAG

        # Enviar: the existing preview opens, and nothing is sent until its own Enviar.
        _open(session, 1440, 900)
        session.click_in_view(_icon(ids["send"]))
        _wait_open(session)
        session.click_in_view("#req-email-quick-send")
        session.wait_for("!document.getElementById('req-email-modal').hidden")
        session.wait_for("!document.getElementById('req-email-confirm').disabled", timeout=20)
        assert _closed(session)
        assert session.evaluate("document.getElementById('req-email-summary').textContent").startswith("1 requisição")
        session.pump(1.0)
        assert sent == [] and ids["send"] in _pending()
        session.click_in_view("#req-email-cancel")
        assert sent == [] and ids["send"] in _pending()

        # Red icon (last attempt failed): Desmarcar removes it too, and it stays gone.
        _open(session, 1440, 900)
        state = _flag_in_row(session, ids["failed_dismiss"])
        assert state["icons"] == state["red"] == state["buttons"] == 1, state
        session.click_in_view(_icon(ids["failed_dismiss"]))
        _wait_open(session)
        assert _dialog(session)["title"] == FAILED_LABEL
        _shot(session, "desktop_vermelho_antes_de_desmarcar")
        _reload(session, lambda: session.click_in_view("#req-email-quick-dismiss"))
        assert _flag_in_row(session, ids["failed_dismiss"]) == NO_FLAG
        assert ids["failed_dismiss"] not in _pending() and ids["failed_dismiss"] not in _failed_ids()
        _shot(session, "desktop_vermelho_apos_desmarcar")
        _reload(session, lambda: session.evaluate("location.reload(); true"))
        assert _flag_in_row(session, ids["failed_dismiss"]) == NO_FLAG
        assert session.evaluate("window.__errors") == []
    finally:
        session.close()

    # A read-only profile: the icon is a status indicator and nothing opens.
    with main.app.app_context():
        conn = main.get_db_connection()
        consultor = int(create_usuario_with_access_level(
            conn, "Consultora da coordenação", "consultora@example.test", "test-hash", "admin", "consultivo",
            credential_state="personal").lastrowid)
        conn.commit()
        version = get_usuario_auth_version(conn, consultor)
    with client.session_transaction() as flask_session:
        flask_session.update(user_id=consultor, user_type="admin", user_name="Consultora", auth_version=version)
        flask_session.pop("_flashes", None)
    viewer = Session(client, BINARY, workspace["downloads"], workspace["base_url"])
    try:
        _open(viewer, 1440, 900)
        assert viewer.evaluate("document.querySelectorAll('.req-email-flag').length") == 0
        assert viewer.evaluate("document.querySelectorAll('.req-email-pending[role=\"img\"]').length") >= 2
        before = _pending()
        viewer.click_in_view(_row(ids["failed"]) + " .req-email-pending")
        viewer.pump(0.3)
        assert _closed(viewer) and _pending() == before
        assert all(g == [7, 7, 9, 9, 14, 14] for g in _geometry(viewer)), _geometry(viewer)
        assert viewer.evaluate("window.__errors") == []
    finally:
        viewer.close()
