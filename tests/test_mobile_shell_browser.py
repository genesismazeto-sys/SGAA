"""MOBILE-01 in a real Chromium: the shell on a phone, and the desktop shell left as it was.

Below 768px the sidebar is a drawer opened by the header's menu button, and the
content column takes the whole width; from 768px up the shell is the desktop
one. The pages are served by a live local server on an isolated database with
fictitious data (the harness of tests/test_activity_documentation_admin_browser.py),
in phone emulation (mobile viewport, touch) at 320, 360, 390 and 430px.

Horizontal scrolling is allowed only where it is intended: the list grids
(``.impressoes-cards-scroll``) scroll sideways inside their own box. Nothing
else may run past the viewport, and the content column never does.

The direct comprovante upload runs end to end on the phone too: the browser's
signed-TUS request goes to the synthetic storage host of
tests/canonical_request_documents_support.py, answered by the session into the
in-memory canonical store -- no real host, key, account or document.
"""
from __future__ import annotations

import base64
import json

import main
from app.storage.supabase_store import storage_browser_origin
from tests.canonical_request_documents_support import TEST_SUPABASE_URL, canonical_documents
from tests.canonical_matrix_test_support import login_admin
from tests.canonical_request_test_support import login_student, student_identity
from tests.test_activity_documentation_admin_browser import (
    BINARY,
    ANEXO_3,
    EVIDENCE,
    Session,
    _draft_version,
    _type,
    browser_only,
    workspace,  # noqa: F401  (pytest fixture)
)
from tests.test_activity_documentation_student_browser import _choose, _seed_student_catalogue
from tests.test_comprovantes_google_drive import PDF, FakeStorage

PHONES = ((320, 640), (360, 740), (390, 844), (430, 932))

LAYOUT_JS = r"""
(() => {
  const vw = innerWidth, vh = innerHeight;
  const side = document.getElementById('app-sidebar');
  const main = document.getElementById('conteudo');
  const track = document.querySelector('.app-track');
  const toggle = document.getElementById('app-menu-toggle');
  const header = document.querySelector('.app-header');
  const sr = side.getBoundingClientRect();
  const visible = el => { const s = getComputedStyle(el); return s.display !== 'none' && s.visibility !== 'hidden'; };
  // Anything past the viewport that is not inside an element scrolling sideways on purpose.
  const loose = [];
  for (const el of main.querySelectorAll('*')) {
    if (!visible(el)) continue;
    const b = el.getBoundingClientRect();
    if (!b.width || (b.right <= vw + 0.5 && b.left >= -0.5)) continue;
    let p = el.parentElement, scrolled = false;
    for (; p && p !== main; p = p.parentElement) {
      const o = getComputedStyle(p).overflowX;
      if (o === 'auto' || o === 'scroll' || o === 'hidden' || o === 'clip') { scrolled = true; break; }
    }
    if (!scrolled) loose.push((el.id ? '#' + el.id : el.className || el.tagName).toString().slice(0, 60));
  }
  const scrollers = Array.from(main.querySelectorAll('*')).filter(el => {
    const o = getComputedStyle(el).overflowX;
    return (o === 'auto' || o === 'scroll') && el.scrollWidth > el.clientWidth + 1 && visible(el);
  }).map(el => el.className.toString());
  const wrapped = Array.from(main.querySelectorAll('form label, .row-label, .field-label')).filter(el => {
    if (!visible(el) || !el.textContent.trim() || el.querySelector('input, select, textarea, div, ul')) return false;
    const r = document.createRange(); r.selectNodeContents(el);
    return new Set(Array.from(r.getClientRects()).filter(x => x.width > 0.5).map(x => Math.round(x.top))).size > 1;
  }).map(el => el.textContent.trim());
  const active = document.activeElement;
  return {
    vw, vh,
    sidebarLeft: Math.round(sr.left), sidebarRight: Math.round(sr.right), sidebarWidth: Math.round(sr.width),
    sidebarVisible: visible(side),
    toggleShown: getComputedStyle(toggle).display !== 'none', expanded: toggle.getAttribute('aria-expanded'),
    open: document.querySelector('.app-layout').classList.contains('is-nav-open'),
    inert: !!main.inert,
    mainLeft: Math.round(main.getBoundingClientRect().left), trackWidth: Math.round(track.getBoundingClientRect().width),
    docOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    mainOverflow: main.scrollWidth - main.clientWidth,
    headerOverflow: header.scrollWidth - header.clientWidth,
    loose, scrollers, wrapped,
    focus: active === toggle ? 'toggle' : (active && active.closest && active.closest('#app-sidebar') ? 'sidebar' : 'other'),
  };
})()
"""


def _viewport(session, width, height):
    phone = width < 768
    session.call("Emulation.setDeviceMetricsOverride",
                 {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": phone})
    session.call("Emulation.setTouchEmulationEnabled", {"enabled": phone, "maxTouchPoints": 5 if phone else 1})
    session.pump(0.3)


def _open(session, path):
    session.goto(path)
    session.evaluate("window.__errors = []; window.addEventListener('error', e => window.__errors.push(String(e.message)));"
                     " true")
    session.pump(0.3)


def _layout(session):
    return session.evaluate(LAYOUT_JS)


def _tap(session, x, y):
    for kind, buttons in (("mousePressed", 1), ("mouseReleased", 0)):
        session.call("Input.dispatchMouseEvent",
                     {"type": kind, "x": x, "y": y, "button": "left", "buttons": buttons, "clickCount": 1})
    session.pump(0.4)


def _escape(session):
    for kind in ("keyDown", "keyUp"):
        session.call("Input.dispatchKeyEvent",
                     {"type": kind, "key": "Escape", "code": "Escape", "windowsVirtualKeyCode": 27})
    session.pump(0.4)


def _evidence(session, name):
    if EVIDENCE:
        session.wait_for("document.fonts ? document.fonts.status === 'loaded' : true")
        session.capture_viewport(name)


def _assert_phone_page(layout, *, scrollers=()):
    """The phone contract of one page at one width."""
    assert layout["toggleShown"] is True, layout
    assert layout["sidebarRight"] <= 0 and not layout["sidebarVisible"], layout
    assert layout["mainLeft"] == 0 and layout["trackWidth"] >= layout["vw"] - 32 - 1, layout
    assert layout["docOverflow"] <= 0 and layout["mainOverflow"] <= 0 and layout["headerOverflow"] <= 0, layout
    assert layout["loose"] == [], layout
    assert all(any(name in s for name in scrollers) for s in layout["scrollers"]), layout
    assert layout["wrapped"] == [], layout


def _dialog(session, overlay):
    return session.evaluate(
        "(() => { const o = document.getElementById(%s); const c = o.querySelector('.modal-card') || o.firstElementChild;"
        " const r = c.getBoundingClientRect(); const b = c.querySelector('.modal-body');"
        " return {open: !o.hidden, left: r.left, right: r.right, top: r.top, bottom: r.bottom,"
        " vw: innerWidth, vh: innerHeight, bodyScroll: b ? getComputedStyle(b).overflowY : null}; })()"
        % json.dumps(overlay)
    )


def _inside(box):
    return box["left"] >= 0 and box["top"] >= 0 and box["right"] <= box["vw"] and box["bottom"] <= box["vh"]


@browser_only
def test_on_a_phone_the_menu_is_a_drawer_and_the_student_can_request_and_navigate(workspace):
    catalogue = _seed_student_catalogue()
    login_student(workspace["client"])
    session = Session(workspace["client"], BINARY, workspace["downloads"], workspace["base_url"])
    try:
        for width, height in PHONES:
            _viewport(session, width, height)
            _open(session, "/aluno/nova-requisicao")
            _choose(session, catalogue["group"], catalogue["with_docs"]["id"])
            layout = _layout(session)
            _assert_phone_page(layout)
            assert (layout["toggleShown"], layout["expanded"], layout["inert"]) == (True, "false", False), layout
            # The guidance of the chosen activity is on screen width, never past it.
            block = session.evaluate(
                "(() => { const b = document.getElementById('orientacao-comprovantes'); const r = b.getBoundingClientRect();"
                " return {hidden: b.hidden, left: r.left, right: r.right, vw: innerWidth}; })()")
            assert not block["hidden"] and block["left"] >= 0 and block["right"] <= block["vw"], block
            if width == 390:
                _evidence(session, "mobile-aluno-nova-requisicao-390")

            # The menu opens over the content, takes the focus and makes the content inert ...
            session.click("#app-menu-toggle")
            session.pump(0.4)
            opened = _layout(session)
            assert (opened["open"], opened["expanded"], opened["inert"], opened["focus"]) == (True, "true", True, "sidebar")
            assert opened["sidebarLeft"] == 0 and opened["sidebarVisible"] and opened["sidebarRight"] < width, opened
            if width == 390:
                _evidence(session, "mobile-aluno-menu-aberto-390")
            # ... Escape closes it and gives the focus back to the button ...
            _escape(session)
            closed = _layout(session)
            assert (closed["open"], closed["expanded"], closed["inert"], closed["focus"]) == (False, "false", False, "toggle")
            # ... and so does a tap on the scrim beside the drawer.
            session.click("#app-menu-toggle")
            session.pump(0.4)
            _tap(session, width - 12, height // 2)
            assert _layout(session)["open"] is False

        # Navigation through the drawer: the next page opens with the menu closed.
        _viewport(session, 390, 844)
        _open(session, "/aluno/nova-requisicao")
        session.click("#app-menu-toggle")
        session.pump(0.4)
        session.evaluate("window.__leaving = true; true")
        session.click("#app-sidebar a[href='/aluno/requisicoes']")
        session.wait_for("!window.__leaving && document.readyState === 'complete'", timeout=20)
        session.pump(0.3)
        assert session.evaluate("location.pathname") == "/aluno/requisicoes"
        listing = _layout(session)
        assert listing["open"] is False and listing["expanded"] == "false"
        _assert_phone_page(listing, scrollers=("impressoes-cards-scroll",))

        # The template downloads on the phone, and a fictitious request goes through.
        _open(session, "/aluno/nova-requisicao")
        _choose(session, catalogue["group"], catalogue["with_docs"]["id"])
        session.click_in_view(".doc-guidance-download")
        assert session.downloaded("Anexo 3.docx") == ANEXO_3
        # The Comprovantes card and its Anexar control stay on screen.
        attach = session.evaluate(
            "(() => { const r = document.querySelector('[data-upload-card] .chip-right').getBoundingClientRect();"
            " return {left: r.left, right: r.right, width: r.width, vw: innerWidth}; })()")
        assert attach["left"] >= 0 and attach["right"] <= attach["vw"] and attach["width"] > 0, attach
        _type(session, "input[name='nome_evento']", "Palestra no celular")
        _type(session, "input[name='horas_solicitadas']", "2")
        _type(session, "input[name='data_evento']", "2026-09-06")
        assert session.evaluate("window.__errors") == []
        session.evaluate("window.__leaving = true; true")
        session.click_in_view("form[data-direct-upload] button[type='submit']")
        session.wait_for("!window.__leaving && document.readyState === 'complete'", timeout=20)
        assert "Requisição enviada com sucesso." in session.evaluate("document.body.innerText")
        with main.app.app_context():
            row = main.get_db_connection().execute(
                "SELECT status, atividade_versao_id, aluno_id FROM requisicoes WHERE nome_evento = 'Palestra no celular'"
            ).fetchone()
        assert (row["status"], row["atividade_versao_id"], row["aluno_id"]) == (
            "Pendente", catalogue["with_docs"]["id"], student_identity()["aluno_id"])
    finally:
        session.close()


@browser_only
def test_admin_pages_and_dialogs_fit_a_phone(workspace):
    base_id, version_id = _draft_version()
    login_admin(workspace["client"])
    session = Session(workspace["client"], BINARY, workspace["downloads"], workspace["base_url"])
    lists = ("impressoes-cards-scroll",)
    try:
        for width, height in ((320, 640), (390, 844)):
            _viewport(session, width, height)
            for path, scrollers in (("/admin/acesso", lists), ("/admin/atividades", lists), ("/admin/reportes", lists),
                                    (f"/admin/catalogo-versoes/{base_id}/nova-versao", ()),
                                    (f"/admin/catalogo-versoes/{base_id}/versoes/{version_id}/editar", ())):
                _open(session, path)
                _assert_phone_page(_layout(session), scrollers=scrollers)
                if width == 390 and path == "/admin/acesso":
                    _evidence(session, "mobile-admin-acesso-390")

            # Novo acesso: the dialog stays inside the screen and scrolls inside its own body.
            _open(session, "/admin/acesso")
            session.click_in_view("#btn-acesso-adicionar")
            session.pump(0.4)
            box = _dialog(session, "access-modal")
            assert box["open"] and _inside(box) and box["bodyScroll"] == "auto", box
            if width == 390:
                _evidence(session, "mobile-admin-acesso-novo-390")
            session.click("#access-modal-cancel")
            session.pump(0.3)
            assert _dialog(session, "access-modal")["open"] is False

            # Reportes: the new-report dialog and the sort popover both fit.
            _open(session, "/admin/reportes")
            session.click_in_view("#btn-novo-reporte")
            session.pump(0.4)
            box = _dialog(session, "novo-reporte-modal")
            assert box["open"] and _inside(box), box
            _escape(session)
            assert _dialog(session, "novo-reporte-modal")["open"] is False
            session.click_in_view("#sort-field")
            session.pump(0.4)
            menu = session.evaluate(
                "(() => { const m = document.getElementById('sort-menu'); const r = m.getBoundingClientRect();"
                " return {hidden: m.hidden, left: r.left, right: r.right, top: r.top, bottom: r.bottom,"
                " vw: innerWidth, vh: innerHeight}; })()")
            assert not menu["hidden"] and _inside(menu), menu
        assert session.evaluate("window.__errors") == []
    finally:
        session.close()


@browser_only
def test_from_768_the_desktop_shell_is_unchanged(workspace):
    login_admin(workspace["client"])
    session = Session(workspace["client"], BINARY, workspace["downloads"], workspace["base_url"])
    try:
        for width, height in ((768, 1024), (1366, 768)):
            _viewport(session, width, height)
            _open(session, "/admin/acesso")
            layout = _layout(session)
            assert layout["toggleShown"] is False and layout["sidebarVisible"], layout
            assert (layout["sidebarLeft"], layout["sidebarWidth"], layout["mainLeft"]) == (0, 240, 240), layout
            # The hidden button cannot put the desktop page under a drawer.
            session.evaluate("document.getElementById('app-menu-toggle').click(); true")
            session.pump(0.3)
            after = _layout(session)
            assert (after["open"], after["inert"], after["expanded"]) == (False, False, "false"), after
            assert session.evaluate("document.querySelector('.logo-text').textContent.trim()") == (
                "SGAA - Sistema de Gerenciamento de Atividades Acadêmicas")
    finally:
        session.close()


STORAGE_ORIGIN = storage_browser_origin(TEST_SUPABASE_URL)


class _TusSession(Session):
    """The live-server session that also answers the synthetic storage host.

    The browser's signed-TUS upload (``direct-upload.js``) goes to the synthetic
    Supabase project of tests/canonical_request_documents_support.py; this session
    answers its CORS preflight and its creation-with-upload POST and hands the bytes
    to the in-memory canonical store, so no real host, key or account is involved.
    """

    def __init__(self, *args, store, **kwargs):
        super().__init__(*args, **kwargs)
        self.store = store
        self.tus = []
        self.call("Fetch.enable", {"patterns": [{"urlPattern": STORAGE_ORIGIN + "/*", "requestStage": "Request"}]})

    def _serve(self, params):
        request = params["request"]
        headers = {k.lower(): v for k, v in request.get("headers", {}).items()}
        body = b"".join(base64.b64decode(e.get("bytes", "")) for e in request.get("postDataEntries") or [])
        self.tus.append(request["method"])
        response_headers = [
            {"name": "Access-Control-Allow-Origin", "value": self.base_url},
            {"name": "Access-Control-Allow-Methods", "value": "POST, PATCH, HEAD, OPTIONS"},
            {"name": "Access-Control-Allow-Headers", "value": "*"},
            {"name": "Access-Control-Expose-Headers", "value": "Location, Upload-Offset, Upload-Length, Tus-Resumable"},
            {"name": "Tus-Resumable", "value": "1.0.0"},
        ]
        code = 204
        if request["method"] == "POST":
            metadata = dict(item.split(" ", 1) for item in headers["upload-metadata"].split(","))
            metadata = {key: base64.b64decode(value).decode() for key, value in metadata.items()}
            self.store.complete_resumable_upload(
                token=headers["x-signature"], bucket=metadata["bucketName"], object_name=metadata["objectName"],
                content=body, content_type=metadata["contentType"])
            code = 201
            response_headers += [{"name": "Location", "value": STORAGE_ORIGIN + "/upload/resumable/test-1"},
                                 {"name": "Upload-Offset", "value": str(len(body))}]
        self.send("Fetch.fulfillRequest", {"requestId": params["requestId"], "responseCode": code,
                                           "responseHeaders": response_headers, "body": ""})


@browser_only
def test_on_a_phone_a_comprovante_uploads_directly_and_the_request_goes_through(workspace):
    """The direct upload of a comprovante from a 390px phone, end to end and isolated."""
    catalogue = _seed_student_catalogue()
    original_storage = main.app.extensions.get("comprovante_storage")
    original_csp = main.app.config["CONTENT_SECURITY_POLICY"]
    main.app.extensions["comprovante_storage"] = FakeStorage()
    pdf = workspace["files"] / "comprovante.pdf"
    pdf.write_bytes(PDF)
    try:
        with canonical_documents(main.app) as store:
            # Production composes connect-src with the configured storage origin at
            # startup; this app started before the synthetic configuration existed.
            main.app.config["CONTENT_SECURITY_POLICY"] = original_csp.replace(
                "connect-src 'self'", f"connect-src 'self' {STORAGE_ORIGIN}", 1)
            login_student(workspace["client"])
            session = _TusSession(workspace["client"], BINARY, workspace["downloads"], workspace["base_url"],
                                  store=store)
            try:
                _viewport(session, 390, 844)
                _open(session, "/aluno/nova-requisicao")
                _choose(session, catalogue["group"], catalogue["with_docs"]["id"])
                session.set_files("#comprovantes_files", pdf)
                session.wait_for("document.querySelector('[data-direct-upload-list] li')?.dataset.state === 'verified'",
                                 timeout=20)
                assert session.tus == ["OPTIONS", "POST"]
                _assert_phone_page(_layout(session))
                _evidence(session, "mobile-aluno-comprovante-enviado-390")
                _type(session, "input[name='nome_evento']", "Palestra com comprovante no celular")
                _type(session, "input[name='horas_solicitadas']", "2")
                _type(session, "input[name='data_evento']", "2026-09-06")
                assert session.evaluate("window.__errors") == []
                session.evaluate("window.__leaving = true; true")
                session.click_in_view("form[data-direct-upload] button[type='submit']")
                session.wait_for("!window.__leaving && document.readyState === 'complete'", timeout=20)
                assert "Requisição enviada com sucesso." in session.evaluate("document.body.innerText")
            finally:
                session.close()
            with main.app.app_context():
                conn = main.get_db_connection()
                request = conn.execute("SELECT id, status FROM requisicoes WHERE nome_evento = ?",
                                       ("Palestra com comprovante no celular",)).fetchone()
                attachments = conn.execute("SELECT count(*) FROM requisicao_arquivos WHERE requisicao_id = ?",
                                           (request["id"],)).fetchone()[0]
            assert (request["status"], attachments) == ("Pendente", 1)
            assert [content for content, _mime in store.objects.values()] == [PDF]
    finally:
        main.app.config["CONTENT_SECURITY_POLICY"] = original_csp
        if original_storage is None:
            main.app.extensions.pop("comprovante_storage", None)
        else:
            main.app.extensions["comprovante_storage"] = original_storage
