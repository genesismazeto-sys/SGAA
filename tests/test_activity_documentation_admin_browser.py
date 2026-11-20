"""Documentação exigida in a real Chromium, administrator side: the guidance and
the DOCX templates of a draft version are maintained on the version form, and a
frozen version shows them read-only.

The page talks to a real HTTP server on 127.0.0.1 serving the application on
an isolated SQLite database -- not to intercepted requests, whose post data
never carries a file part -- so uploads go through Chromium's own multipart
form and downloads are saved by Chromium into a temporary folder: the bytes
compared are the bytes a user sends and gets.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
import time
from pathlib import Path

import pytest
from werkzeug.serving import make_server

import main
from app.activity_documentation import read_required_documents
from tests.canonical_matrix_test_support import login_admin
from tests.docx_test_support import ANEXO_3_TITULO, ANEXO_5_TITULO, make_docx
from tests.test_activity_documentation_student import insert_template
from tests.versioned_test_support import isolated_versioned_app_env

cdp = pytest.importorskip("tests.cdp_browser_support")
BINARY = cdp.find_chromium()
browser_only = pytest.mark.skipif(BINARY is None, reason="no Chromium binary for the browser harness")

#: Opt-in screenshots for review (outside the repository): SGAA_EVIDENCE_DIR.
EVIDENCE = os.environ.get("SGAA_EVIDENCE_DIR")

ANEXO_3 = make_docx("Anexo 3 — Leitura de livro/filme (arquivo sintético de teste)")
ANEXO_5 = make_docx(
    "Anexo 5 — Atividades de monitoria, apoio institucional e visitas técnicas (arquivo sintético de teste)"
)
ANEXO_5_REV6 = make_docx("Anexo 5 — ACC rev6 (arquivo sintético de teste)")


class LiveServer:
    """The application on a real, threaded HTTP server bound to 127.0.0.1."""

    def __init__(self, app):
        self._server = make_server("127.0.0.1", 0, app, threaded=True)
        self.url = f"http://127.0.0.1:{self._server.server_port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def close(self):
        self._server.shutdown()
        self._thread.join(timeout=10)


class Session(cdp.BrowserSession):
    """The shared Chromium driver pointed at a live server, with file inputs and downloads.

    Request interception is switched off: the browser talks to the server
    itself. The test client's session cookie (set by the login helper) is
    handed to Chromium for the server's origin.
    """

    def __init__(self, client, binary, download_dir: Path, base_url: str):
        super().__init__(client, binary)
        self.call("Fetch.disable")
        self.base_url = base_url
        self.download_dir = download_dir
        name = main.app.config.get("SESSION_COOKIE_NAME", "session")
        cookie = client.get_cookie(name)
        assert cookie is not None, "log in through the test client before opening the browser"
        self.call("Network.setCookie", {"name": name, "value": cookie.value, "url": base_url, "httpOnly": True})
        self.call("Browser.setDownloadBehavior", {"behavior": "allow", "downloadPath": str(download_dir)})

    def goto(self, path, ready="document.readyState === 'complete'"):
        self.call("Page.navigate", {"url": self.base_url + path})
        self.pump(0.2)
        self.wait_for(ready)

    def set_files(self, selector, *paths):
        root = self.call("DOM.getDocument", {"depth": 0})["root"]["nodeId"]
        node = self.call("DOM.querySelector", {"nodeId": root, "selector": selector})["nodeId"]
        assert node, selector
        self.call("DOM.setFileInputFiles", {"nodeId": node, "files": [str(path) for path in paths]})

    def downloaded(self, name, timeout=15.0):
        target = self.download_dir / name
        deadline = time.time() + timeout
        while time.time() < deadline:
            if target.exists() and not list(self.download_dir.glob("*.crdownload")):
                return target.read_bytes()
            self.pump(0.1)
        raise TimeoutError(name)

    def capture_viewport(self, name):
        """Evidence of exactly what is on screen now (no metrics change, no scroll reset)."""
        if not EVIDENCE:
            return
        data = self.call("Page.captureScreenshot", {"format": "png"})["data"]
        Path(EVIDENCE).mkdir(parents=True, exist_ok=True)
        (Path(EVIDENCE) / f"{name}.png").write_bytes(base64.b64decode(data))

    def screenshot(self, name, *, width=1440, height=900, full=True):
        if not EVIDENCE:
            return
        self.call("Emulation.setDeviceMetricsOverride",
                  {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": width < 720})
        self.pump(0.4)
        params = {"format": "png", "captureBeyondViewport": full}
        if full:
            size = self.evaluate("({w: document.documentElement.scrollWidth, h: document.documentElement.scrollHeight})")
            params["clip"] = {"x": 0, "y": 0, "width": size["w"], "height": size["h"], "scale": 1}
        data = self.call("Page.captureScreenshot", params)["data"]
        Path(EVIDENCE).mkdir(parents=True, exist_ok=True)
        (Path(EVIDENCE) / f"{name}.png").write_bytes(base64.b64decode(data))
        self.call("Emulation.setDeviceMetricsOverride",
                  {"width": 1440, "height": 900, "deviceScaleFactor": 1, "mobile": False})


def _open(session, path):
    session.goto(path)
    session.evaluate(
        "window.__errors = []; window.addEventListener('error', e => window.__errors.push(String(e.message)));"
        " window.confirm = () => true; true"
    )
    if EVIDENCE:
        session.wait_for("document.fonts ? document.fonts.status === 'loaded' : true")


def _js(value):
    return json.dumps(value, ensure_ascii=False)


def _type(session, selector, text):
    session.click_in_view(selector)
    session.evaluate(
        "(() => { const el = document.querySelector(%s); el.value = %s;"
        " el.dispatchEvent(new Event('input', {bubbles: true})); el.dispatchEvent(new Event('change', {bubbles: true}));"
        " return true; })()" % (_js(selector), _js(text))
    )


def _submit_and_wait(session, selector):
    """Click a submit button and wait for the next page to finish loading."""
    session.evaluate("window.__leaving = true; true")
    session.click_in_view(selector)
    session.wait_for("!window.__leaving && document.readyState === 'complete'", timeout=20)
    session.evaluate(
        "window.__errors = []; window.addEventListener('error', e => window.__errors.push(String(e.message)));"
        " window.confirm = () => true; true"
    )


def _texts(session, selector):
    return session.evaluate(
        "Array.from(document.querySelectorAll(%s)).map(el => (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')"
        " ? el.value : el.textContent.trim())" % _js(selector)
    )


@pytest.fixture
def workspace(tmp_path):
    with isolated_versioned_app_env(tmp_path, "documentation-browser.db") as environment:
        downloads = tmp_path / "downloads"
        downloads.mkdir()
        files = tmp_path / "uploads-from-disk"
        files.mkdir()
        for name, content in (("Anexo 3.docx", ANEXO_3), ("Anexo 5.docx", ANEXO_5),
                              ("Anexo 5 - ACC rev6.docx", ANEXO_5_REV6),
                              ("Com macro.docx", make_docx(vba_project=True))):
            (files / name).write_bytes(content)
        server = LiveServer(main.app)
        environment.update(downloads=downloads, files=files, base_url=server.url)
        try:
            yield environment
        finally:
            server.close()


def _draft_version():
    with main.app.app_context():
        conn = main.get_db_connection()
        base_id = conn.execute(
            "INSERT INTO atividade_base (nome_conceito, descricao, status) VALUES (?, ?, 'ativo') RETURNING id",
            ("Palestra com documentação", "Atividade de teste"),
        ).fetchone()[0]
        version_id = conn.execute(
            """INSERT INTO atividade_versao (atividade_base_id, eixo, grupo, ch_por_evento, documentos_json,
                   numero_versao, status) VALUES (?, 'AAC', '1 - Eventos', 2, '[]', 1, 'rascunho') RETURNING id""",
            (base_id,),
        ).fetchone()[0]
        conn.commit()
    return base_id, version_id


def _stored(version_id):
    with main.app.app_context():
        conn = main.get_db_connection()
        version = conn.execute("SELECT documentos_json FROM atividade_versao WHERE id = ?", (version_id,)).fetchone()
        rows = conn.execute(
            "SELECT m.titulo, m.status, a.sha256 FROM atividade_versao_modelos m"
            " JOIN modelo_documento_arquivos a ON a.id = m.arquivo_id WHERE m.atividade_versao_id = ? ORDER BY m.id",
            (version_id,),
        ).fetchall()
    return read_required_documents(version["documentos_json"]), [tuple(row) for row in rows]


def _sha(content):
    return hashlib.sha256(content).hexdigest()


@browser_only
def test_admin_maintains_the_documentation_of_a_draft_in_the_browser(workspace):
    base_id, version_id = _draft_version()
    edit_url = f"/admin/catalogo-versoes/{base_id}/versoes/{version_id}/editar"
    login_admin(workspace["client"])
    session = Session(workspace["client"], BINARY, workspace["downloads"], workspace["base_url"])
    try:
        _open(session, edit_url)
        assert _texts(session, "[data-doc-empty]") == ["Nenhum comprovante exigido cadastrado."]
        # A. Comprovantes exigidos: add three, move the third up, remove the second.
        for text in ("Certificado de participação", "Lista de presença", "Relatório da atividade (Anexo 3)"):
            session.click_in_view("[data-doc-add]")
            _type(session, "#documentos-exigidos-list li:last-child [name=documentos_exigidos]", text)
        session.click_in_view("#documentos-exigidos-list li:nth-child(3) [data-doc-move='-1']")
        session.click_in_view("#documentos-exigidos-list li:nth-child(3) [data-doc-remove]")
        assert _texts(session, "#documentos-exigidos-list [name=documentos_exigidos]") == [
            "Certificado de participação", "Relatório da atividade (Anexo 3)",
        ]
        assert _texts(session, "#documentos-exigidos-list .doc-list-index") == ["1", "2"]
        # Unsaved changes hold the template actions (they would reload the page).
        assert session.evaluate("document.querySelector('[data-templates-dirty]').hidden") is False
        assert session.evaluate("document.querySelector(\"button[form='modelo-novo-form']\").disabled") is True
        _submit_and_wait(session, "#btn-salvar-versao")
        assert _stored(version_id)[0] == ["Certificado de participação", "Relatório da atividade (Anexo 3)"]
        _open(session, edit_url)
        assert _texts(session, "#documentos-exigidos-list [name=documentos_exigidos]") == [
            "Certificado de participação", "Relatório da atividade (Anexo 3)",
        ]
        assert session.evaluate("document.querySelector('[data-templates-dirty]').hidden") is True

        # B. Modelos: two uploads through the browser's own multipart form.
        for title, filename in ((ANEXO_3_TITULO, "Anexo 3.docx"),
                                ("", "Anexo 5.docx")):
            _type(session, "input[form='modelo-novo-form'][name='modelo_titulo']", title)
            session.set_files("input[form='modelo-novo-form'][type='file']", workspace["files"] / filename)
            session.pump(0.2)
            assert _texts(session, ".doc-template-new [data-file-name]") == [filename]
            _submit_and_wait(session, "button[form='modelo-novo-form']")
            assert "Modelo adicionado." in session.evaluate("document.body.innerText")
        assert _texts(session, ".doc-templates > .doc-template-list .doc-template-title") == [
            ANEXO_3_TITULO, "Anexo 5",
        ]
        # A macro document is refused with the reason, and nothing is stored.
        session.set_files("input[form='modelo-novo-form'][type='file']", workspace["files"] / "Com macro.docx")
        _submit_and_wait(session, "button[form='modelo-novo-form']")
        assert "macros" in session.evaluate("document.body.innerText")
        assert len(_stored(version_id)[1]) == 2
        session.screenshot("admin-versao-documentacao-desktop")
        session.screenshot("admin-versao-documentacao-390", width=390, height=844)

        # Download: the browser saves exactly the uploaded bytes.
        session.click_in_view(".doc-template[data-modelo-id] a[aria-label='Baixar modelo %s']" % ANEXO_3_TITULO)
        assert session.downloaded("Anexo 3.docx") == ANEXO_3

        # Replace the second template's file and title; withdraw the first.
        second = session.evaluate("document.querySelectorAll('.doc-template-list li.doc-template')[1].dataset.modeloId")
        session.click_in_view(f"li[data-modelo-id='{second}'] [data-template-toggle]")
        assert session.evaluate(f"document.getElementById('modelo-editor-{second}').hidden") is False
        _type(session, f"input[form='modelo-atualizar-{second}'][name='modelo_titulo']", ANEXO_5_TITULO)
        session.set_files(f"input[form='modelo-atualizar-{second}'][type='file']",
                          workspace["files"] / "Anexo 5 - ACC rev6.docx")
        _submit_and_wait(session, f"button[form='modelo-atualizar-{second}']")
        first = session.evaluate("document.querySelectorAll('.doc-template-list li.doc-template')[0].dataset.modeloId")
        _submit_and_wait(session, f"button[form='modelo-retirar-{first}']")
        assert _texts(session, ".doc-templates > .doc-template-list .doc-template-title") == [ANEXO_5_TITULO]
        assert "Histórico de modelos (2)" in session.evaluate("document.body.innerText")
        documentos, rows = _stored(version_id)
        assert rows == [
            (ANEXO_3_TITULO, "retirado", _sha(ANEXO_3)),
            ("Anexo 5", "substituido", _sha(ANEXO_5)),
            (ANEXO_5_TITULO, "ativo", _sha(ANEXO_5_REV6)),
        ]
        session.screenshot("admin-versao-modelos-historico")

        # Activated, the version is frozen: everything is read-only, the files still download.
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute("UPDATE atividade_versao SET status = 'ativa' WHERE id = ?", (version_id,))
            conn.commit()
        _open(session, edit_url)
        assert session.evaluate("document.querySelector('[data-doc-add]')") is None
        assert session.evaluate("document.querySelector('[form=modelo-novo-form]')") is None
        assert "crie uma nova versão" in session.evaluate("document.body.innerText").lower()
        assert _texts(session, "#documentos-exigidos-list [name=documentos_exigidos]") == documentos
        assert session.evaluate("Array.from(document.querySelectorAll('#documentos-exigidos-list [name=documentos_exigidos]')).every(i => i.matches(':disabled'))")
        session.screenshot("admin-versao-congelada")
        assert session.evaluate("window.__errors") == []
    finally:
        session.close()


#: The longest fill-in annex title of the ACC rev6 regulation, as an
#: administrator would give it. The file itself is a synthetic test document.
LONG_ANNEX_TITLE = ANEXO_5_TITULO


@browser_only
def test_a_template_title_stays_readable_on_the_version_form_at_any_width(workspace):
    """The template rows follow the width their list gets: from 768 px up the
    sidebar is back and the form column is narrow, where a one-line title was
    cut away entirely beside its three buttons. A title wraps instead, and the
    buttons move below it when the list is narrow."""
    base_id, version_id = _draft_version()
    with main.app.app_context():
        conn = main.get_db_connection()
        insert_template(conn, version_id, LONG_ANNEX_TITLE,
                        make_docx("Arquivo sintético de teste; não é o formulário oficial do Regulamento."), slot=1)
        conn.commit()
    login_admin(workspace["client"])
    session = Session(workspace["client"], BINARY, workspace["downloads"], workspace["base_url"])
    try:
        _open(session, f"/admin/catalogo-versoes/{base_id}/versoes/{version_id}/editar")
        for width, height, stacked in ((1440, 900, False), (768, 1024, True), (390, 844, True)):
            session.call("Emulation.setDeviceMetricsOverride",
                         {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": width < 768})
            session.pump(0.4)
            row = session.evaluate(
                "(() => { const li = document.querySelector('.doc-templates > .doc-template-list li.doc-template');"
                " const t = li.querySelector('.doc-template-title'), m = li.querySelector('.doc-template-meta');"
                " const a = li.querySelector('.doc-template-actions');"
                " const tr = t.getBoundingClientRect(), ar = a.getBoundingClientRect();"
                " return {title: t.textContent.trim(), titleCut: t.scrollWidth - t.clientWidth,"
                " metaCut: m.scrollWidth - m.clientWidth, overflow: li.scrollWidth - li.clientWidth,"
                " sizeLines: m.querySelector('.doc-template-meta-tail').getClientRects().length,"
                " sizeWrap: getComputedStyle(m.querySelector('.doc-template-meta-tail')).whiteSpace,"
                " actionsBelow: ar.top >= tr.bottom - 1, actionsBeside: ar.left >= tr.right - 1}; })()"
            )
            assert row["title"] == LONG_ANNEX_TITLE
            assert row["titleCut"] <= 0 and row["metaCut"] <= 0 and row["overflow"] <= 0, (width, row)
            # The file name wraps; its size stays whole (never "990" / "B").
            assert row["sizeLines"] == 1 and row["sizeWrap"] == "nowrap", (width, row)
            assert row["actionsBelow"] is stacked, (width, row)
            assert row["actionsBelow"] or row["actionsBeside"], (width, row)
        assert session.evaluate("window.__errors") == []
    finally:
        session.close()
