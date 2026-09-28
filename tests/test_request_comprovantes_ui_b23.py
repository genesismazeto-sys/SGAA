"""UI-B23: several comprovantes per request, explicit removal, field guidance.

Trace (before this change): the input already declared ``multiple`` and both
student handlers already read ``getlist("comprovantes_files")`` into one
``requisicao_arquivos`` row per file, so storage was never limited to one.
The limit was the page: a second picker interaction replaced the native
FileList (silently dropping the first choice), two or more files collapsed
into "N arquivos selecionados" with the names only in a stripped ``title``,
and no stored comprovante could be removed individually.

Contract now:
* picking appends; every selected file is listed with its own remove button;
  the submitted FileList is exactly the listed files (static/js/comprovantes-picker.js);
* a stored comprovante is removed only when its id is submitted in
  ``remover_comprovantes`` -- an omitted list keeps every file, and an id that
  is not a current attachment of this request refuses the whole edit;
* one invalid file refuses the whole batch and the message names it;
* "Nome do evento" / "Data do evento" guidance is visible whenever the form is
  editable, tied to its control with aria-describedby.
"""
from __future__ import annotations

import json
import re
import struct
import zlib
from io import BytesIO
from pathlib import Path

import pytest

import main
from tests.cdp_browser_support import BrowserSession, find_chromium
from tests.test_comprovantes_google_drive import PDF, PNG, FakeStorage, _png_chunk
from tests.session_support import stamp_auth_version
from tests.versioned_test_support import isolated_versioned_app_env

PNG_OTHER = (
    b"\x89PNG\r\n\x1a\n"
    + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    + _png_chunk(b"IDAT", zlib.compress(b"\x00\x10\x20\x30"))
    + _png_chunk(b"IEND", b"")
)

NOME_GUIDANCE = (
    "Informe o nome exatamente como consta no comprovante — não o nome genérico da atividade "
    "no regulamento. Ex.: em uma palestra, informe o título da palestra; em horas de voo, o curso "
    "ao qual as horas se referem. Divergências podem resultar em indeferimento sumário."
)
DATA_GUIDANCE = (
    "Informe a data em que a atividade ocorreu, conforme o comprovante — não a data da solicitação. "
    "Em atividades continuadas, informe a data da última atividade realizada."
)


@pytest.fixture
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "ui-b23.db") as environment:
        storage = FakeStorage()
        original = main.app.extensions.get("comprovante_storage")
        main.app.extensions["comprovante_storage"] = storage
        try:
            yield {**environment, "storage": storage}
        finally:
            if original is None:
                main.app.extensions.pop("comprovante_storage", None)
            else:
                main.app.extensions["comprovante_storage"] = original


def _db():
    return main.get_db_connection()


def _student():
    with main.app.app_context():
        return dict(_db().execute(
            """SELECT a.id,a.usuario_id,a.turma_id FROM alunos a JOIN usuarios u ON u.id=a.usuario_id
                WHERE u.tipo='aluno' ORDER BY a.id LIMIT 1"""
        ).fetchone())


def _version(student):
    with main.app.app_context():
        return _db().execute(
            """SELECT item.atividade_versao_id FROM turmas t
                 JOIN matriz_atividade_versao_item item ON item.matriz_id=t.matriz_id
                 JOIN atividade_versao v ON v.id=item.atividade_versao_id
                WHERE t.id=? AND v.status='ativa' ORDER BY item.id LIMIT 1""",
            (student["turma_id"],),
        ).fetchone()[0]


def _login(client, user_id, user_type, access_level=None):
    with client.session_transaction() as session:
        session.clear()
        session.update(user_id=int(user_id), user_type=user_type)
        if access_level:
            session["access_level"] = access_level
        stamp_auth_version(session)


def _as_student(env):
    student = _student()
    _login(env["client"], student["usuario_id"], "aluno")
    return student


def _as_admin(env):
    with main.app.app_context():
        admin = _db().execute(
            "SELECT id,nivel_acesso FROM usuarios WHERE tipo='admin' ORDER BY id LIMIT 1"
        ).fetchone()
    _login(env["client"], admin["id"], "admin", admin["nivel_acesso"])


def _create(env, files, name="Palestra B23", operation="b23-create"):
    student = _as_student(env)
    response = env["client"].post(
        "/aluno/nova-requisicao",
        data={
            "atividade_versao_id": str(_version(student)),
            "nome_evento": name,
            "data_evento": "2026-09-06",
            "horas_solicitadas": "2",
            "comprovantes_operation_id": operation,
            "comprovantes_files": [(BytesIO(content), filename) for content, filename in files],
        },
        content_type="multipart/form-data",
    )
    with main.app.app_context():
        row = _db().execute("SELECT * FROM requisicoes WHERE nome_evento=? ORDER BY id DESC LIMIT 1", (name,)).fetchone()
    return response, (dict(row) if row else None)


def _attachments(request_id, statuses=("active", "legacy_active")):
    with main.app.app_context():
        marks = ",".join("?" for _ in statuses)
        return [dict(r) for r in _db().execute(
            f"SELECT * FROM requisicao_arquivos WHERE requisicao_id=? AND storage_status IN ({marks}) ORDER BY id",
            (request_id, *statuses),
        )]


def _edit(env, request_id, data, files=()):
    payload = dict(data)
    if files:
        payload["comprovantes_files"] = [(BytesIO(content), filename) for content, filename in files]
    return env["client"].post(
        f"/aluno/requisicoes/{request_id}", data=payload, content_type="multipart/form-data"
    )


def _flashes(client):
    with client.session_transaction() as session:
        return [message for _category, message in session.get("_flashes", [])]


# --------------------------------------------------------------- several files


def test_two_proofs_in_one_request_persist_and_are_visible_everywhere(env):
    response, request = _create(env, [(PDF, "certificado.pdf"), (PNG, "foto-evento.png")])
    assert response.status_code == 302 and request is not None
    rows = _attachments(request["id"])
    assert [row["original_filename"] for row in rows] == ["certificado.pdf", "foto-evento.png"]
    assert {row["provider"] for row in rows} == {"google"}
    assert len(env["storage"].files) == 2

    client = env["client"]
    edit_page = client.get(f"/aluno/requisicoes/{request['id']}?edit=1").get_data(as_text=True)
    detail_page = client.get(f"/aluno/requisicoes/{request['id']}").get_data(as_text=True)
    for row in rows:
        url = f"/comprovantes/{row['id']}/open"
        assert url in edit_page and url in detail_page
        assert client.get(url).status_code == 200
    assert "certificado.pdf" in edit_page and "foto-evento.png" in edit_page

    _as_admin(env)
    direct = client.get(f"/admin/requisicao/{request['id']}").get_data(as_text=True)
    process = client.get(f"/admin/processar_requisicao/{request['id']}").get_data(as_text=True)
    api = client.get(f"/admin/api/requisicao/{request['id']}").get_json()
    assert len(api["anexos"]) == 2
    for row in rows:
        url = f"/comprovantes/{row['id']}/open"
        assert url in direct and url in process
        assert client.get(url).status_code == 200


def test_same_filename_with_different_content_is_kept_twice_without_collision(env):
    _response, request = _create(env, [(PNG, "comprovante.png"), (PNG_OTHER, "comprovante.png")])
    rows = _attachments(request["id"])
    assert [row["original_filename"] for row in rows] == ["comprovante.png", "comprovante.png"]
    assert len({row["filename"] for row in rows}) == 2
    assert len({row["sha256"] for row in rows}) == 2


def test_one_invalid_file_refuses_the_whole_batch_and_names_it(env):
    response, request = _create(env, [(PDF, "valido.pdf"), (b"texto", "planilha.xlsx")], name="Lote invalido")
    assert response.status_code == 200
    assert request is None, "no request may be created from a refused batch"
    assert env["storage"].upload_calls == []
    assert "planilha.xlsx: envie somente arquivos PDF, PNG ou JPEG." in response.get_data(as_text=True)


# ------------------------------------------------------------------- edit


@pytest.fixture
def stored_pair(env):
    _response, request = _create(env, [(PDF, "a.pdf"), (PNG, "b.png")], name="Edicao B23")
    rows = _attachments(request["id"])
    assert [row["original_filename"] for row in rows] == ["a.pdf", "b.png"]
    return request, rows


def test_editing_another_field_keeps_every_comprovante(env, stored_pair):
    request, rows = stored_pair
    response = _edit(env, request["id"], {"nome_evento": "Edicao B23 renomeada", "comprovantes_operation_id": "b23-e1"})
    assert response.status_code == 302
    assert [row["id"] for row in _attachments(request["id"])] == [row["id"] for row in rows]
    assert env["storage"].trashed == []


def test_explicit_removal_trashes_only_the_named_file_then_a_new_file_is_added(env, stored_pair):
    request, (first, second) = stored_pair
    assert _edit(env, request["id"], {"remover_comprovantes": str(first["id"]), "comprovantes_operation_id": "b23-e2"}).status_code == 302
    assert [row["id"] for row in _attachments(request["id"])] == [second["id"]]
    assert env["storage"].trashed == [first["remote_file_id"]]
    with main.app.app_context():
        removed = dict(_db().execute("SELECT * FROM requisicao_arquivos WHERE id=?", (first["id"],)).fetchone())
    assert removed["storage_status"] == "trashed" and removed["delete_previous_status"] == "active"
    assert _edit(env, request["id"], {"comprovantes_operation_id": "b23-e3"}, files=[(PDF, "c.pdf")]).status_code == 302
    assert [row["original_filename"] for row in _attachments(request["id"])] == ["b.png", "c.pdf"]


def test_the_edit_page_lists_stored_files_with_named_remove_buttons(env, stored_pair):
    request, rows = stored_pair
    html = env["client"].get(f"/aluno/requisicoes/{request['id']}?edit=1").get_data(as_text=True)
    listing = html.split('id="comprovantes-list"', 1)[1].split("</ul>", 1)[0]
    for row in rows:
        assert f'data-existing-id="{row["id"]}"' in listing
        assert f'aria-label="Remover comprovante {row["original_filename"]}"' in listing
    assert listing.count('<button type="button" class="file-list-remove"') == 2
    assert 'data-file-list="comprovantes-list"' in html and "js/comprovantes-picker.js" in html
    view = env["client"].get(f"/aluno/requisicoes/{request['id']}?view=1").get_data(as_text=True)
    assert "file-list-remove" not in view and 'id="comprovantes_files"' not in view


def test_a_foreign_attachment_id_refuses_the_whole_edit(env, stored_pair):
    request, rows = stored_pair
    _response, other = _create(env, [(PDF, "outro.pdf")], name="Outra B23", operation="b23-other")
    foreign = _attachments(other["id"])[0]
    before = _attachments(request["id"]) + _attachments(other["id"])
    response = _edit(env, request["id"], {"nome_evento": "vazou", "remover_comprovantes": str(foreign["id"])})
    assert response.status_code == 302
    assert _attachments(request["id"]) + _attachments(other["id"]) == before
    with main.app.app_context():
        assert _db().execute("SELECT nome_evento FROM requisicoes WHERE id=?", (request["id"],)).fetchone()[0] == "Edicao B23"
    assert env["storage"].trashed == []
    for bad in ("abc", "999999"):
        _edit(env, request["id"], {"remover_comprovantes": bad})
        assert _attachments(request["id"]) == [row for row in before if row["requisicao_id"] == request["id"]]


def test_another_students_request_cannot_be_touched(env, stored_pair):
    request, rows = stored_pair
    with main.app.app_context():
        conn = _db()
        from app.user_accounts import create_usuario_with_access_level

        uid = int(create_usuario_with_access_level(
            conn, "Outro B23", "outro-b23@example.invalid", main.hash_password("x"),
            "aluno", "usuario", credential_state="personal",
        ).lastrowid)
        conn.execute(
            "INSERT INTO alunos(usuario_id,nome,matricula,email,turma_id,matriz_id,status) "
            "SELECT ?, 'Outro B23', 'B23-OUTRO', 'outro-b23@example.invalid', turma_id, NULL, 'Ativo' FROM alunos WHERE id=?",
            (uid, _student()["id"]),
        )
        conn.commit()
    _login(env["client"], uid, "aluno")
    _edit(env, request["id"], {"remover_comprovantes": str(rows[0]["id"])})
    assert [row["id"] for row in _attachments(request["id"])] == [row["id"] for row in rows]
    assert env["storage"].trashed == []


def test_a_remote_trash_failure_keeps_the_file_and_the_saved_edit(env, stored_pair):
    request, (first, second) = stored_pair
    env["storage"].fail_trash = True
    _edit(env, request["id"], {"nome_evento": "Edicao salva", "remover_comprovantes": str(first["id"])})
    assert [row["id"] for row in _attachments(request["id"])] == [first["id"], second["id"]]
    with main.app.app_context():
        assert _db().execute("SELECT nome_evento FROM requisicoes WHERE id=?", (request["id"],)).fetchone()[0] == "Edicao salva"
    messages = _flashes(env["client"])
    assert "Requisição atualizada." in messages
    assert any("foram mantidos" in message for message in messages)


def test_a_legacy_local_comprovante_is_removed_with_its_file(env, stored_pair):
    request, rows = stored_pair
    documents = Path(env["documents_path"])
    (documents / "legado.pdf").write_bytes(PDF)
    with main.app.app_context():
        conn = _db()
        legacy_id = conn.execute(
            "INSERT INTO requisicao_arquivos(requisicao_id,filename,original_filename,provider,storage_status) "
            "VALUES (?,?,?,'local_legacy','legacy_active')",
            (request["id"], "legado.pdf", "legado.pdf"),
        ).lastrowid
        conn.commit()
    _edit(env, request["id"], {"remover_comprovantes": str(legacy_id)})
    assert [row["id"] for row in _attachments(request["id"])] == [row["id"] for row in rows]
    assert not (documents / "legado.pdf").exists()


def test_removal_outside_the_edit_window_writes_nothing(env, stored_pair):
    request, rows = stored_pair
    with main.app.app_context():
        conn = _db()
        conn.execute("UPDATE requisicoes SET status='Deferida', data_processamento='2026-01-01' WHERE id=?", (request["id"],))
        conn.commit()
    _edit(env, request["id"], {"remover_comprovantes": str(rows[0]["id"])})
    assert [row["id"] for row in _attachments(request["id"])] == [row["id"] for row in rows]
    assert env["storage"].trashed == []


# --------------------------------------------------------------- guidance


def _text(html):
    return re.sub(r"\s+", " ", html)


def test_guidance_is_rendered_with_the_fillable_form_and_tied_to_its_field(env, stored_pair):
    request, _rows = stored_pair
    client = env["client"]
    for url in ("/aluno/nova-requisicao", f"/aluno/requisicoes/{request['id']}?edit=1"):
        html = _text(client.get(url).get_data(as_text=True))
        assert f'id="nome-evento-orientacao"><i class="lucide" data-lucide="info" aria-hidden="true"></i><span>{NOME_GUIDANCE}</span>' in html, url
        assert f'id="data-evento-orientacao"><i class="lucide" data-lucide="info" aria-hidden="true"></i><span>{DATA_GUIDANCE}</span>' in html, url
        assert 'name="nome_evento"' in html and 'aria-describedby="nome-evento-orientacao"' in html
        assert 'aria-describedby="data-evento-orientacao"' in html
        assert html.count('class="form-note form-note--guide"') == 2
    view = client.get(f"/aluno/requisicoes/{request['id']}?view=1").get_data(as_text=True)
    assert "form-note--guide" not in view and "orientacao" not in view


def test_guidance_and_file_list_are_owned_by_form_css_with_tokens_only():
    css = (Path(__file__).resolve().parents[1] / "static/css/components/form.css").read_text(encoding="utf-8")
    block = css.split("FIELD GUIDANCE", 1)[1].split("TRAILING CHIP", 1)[0]
    assert ".form-note.form-note--guide{" in block and ".file-list-remove{" in block
    assert re.findall(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", block.split("*/", 1)[1]) == []
    assert "--field-invalid" not in block.split("*/", 1)[1]


# ---------------------------------------------------------------- browser

CHROMIUM = find_chromium()
browser = pytest.mark.skipif(CHROMIUM is None, reason="no headless Chromium available")

LIST_STATE = """JSON.stringify((() => {
  const input = document.getElementById('comprovantes_files');
  const list = document.getElementById('comprovantes-list');
  return {
    files: Array.from(input.files).map(f => f.name),
    listed: Array.from(list.querySelectorAll('.file-list-item')).map(li => li.querySelector('.file-list-name').textContent),
    buttons: Array.from(list.querySelectorAll('.file-list-remove')).map(b => b.getAttribute('aria-label')),
    hidden: list.hidden,
    summary: document.querySelector('[data-file-name]').textContent,
    removals: Array.from(document.querySelectorAll('input[name="remover_comprovantes"]')).map(i => i.value),
  };
})())"""


def _pick(session, paths):
    node = session.call("Runtime.evaluate", {"expression": "document.getElementById('comprovantes_files')"})
    session.call("DOM.setFileInputFiles", {"files": [str(p) for p in paths], "objectId": node["result"]["objectId"]})
    session.pump(0.3)


@pytest.fixture
def files(tmp_path):
    folder = tmp_path / "picks"
    folder.mkdir()
    (folder / "a.pdf").write_bytes(PDF)
    (folder / "b.png").write_bytes(PNG)
    return folder


@browser
def test_picker_appends_dedupes_and_removes_before_submit(env, files):
    _as_student(env)
    session = BrowserSession(env["client"], CHROMIUM)
    try:
        session.goto("/aluno/nova-requisicao")
        session.call("DOM.getDocument", {})
        state = json.loads(session.evaluate(LIST_STATE))
        assert state["hidden"] is True and state["files"] == []
        # Guidance is on screen without any click or hover.
        visible = session.evaluate(
            "['nome-evento-orientacao','data-evento-orientacao'].every(id => {"
            " const el = document.getElementById(id); const r = el.getBoundingClientRect();"
            " return r.height > 0 && getComputedStyle(el).visibility === 'visible'; })"
        )
        assert visible is True

        _pick(session, [files / "a.pdf"])
        _pick(session, [files / "b.png"])
        state = json.loads(session.evaluate(LIST_STATE))
        assert state["files"] == ["a.pdf", "b.png"], "a second pick must not discard the first"
        assert state["listed"] == ["a.pdf", "b.png"]
        assert state["buttons"] == ["Remover comprovante a.pdf", "Remover comprovante b.png"]
        assert state["summary"] == "2 arquivos selecionados"

        _pick(session, [files / "a.pdf"])
        assert json.loads(session.evaluate(LIST_STATE))["files"] == ["a.pdf", "b.png"], "same file twice is kept once"

        session.click('#comprovantes-list .file-list-remove[aria-label="Remover comprovante a.pdf"]')
        state = json.loads(session.evaluate(LIST_STATE))
        assert state["files"] == ["b.png"] and state["listed"] == ["b.png"]
        assert state["summary"] == "1 arquivo selecionado"
        assert session.evaluate("document.activeElement.getAttribute('aria-label')") == "Remover comprovante b.png"
    finally:
        session.close()


@browser
def test_stored_file_removal_is_only_a_marked_id_until_submit(env, stored_pair):
    request, (first, second) = stored_pair
    session = BrowserSession(env["client"], CHROMIUM)
    try:
        session.goto(f"/aluno/requisicoes/{request['id']}?edit=1")
        state = json.loads(session.evaluate(LIST_STATE))
        assert state["listed"] == ["a.pdf", "b.png"] and state["hidden"] is False
        session.click('#comprovantes-list .file-list-remove[aria-label="Remover comprovante a.pdf"]')
        state = json.loads(session.evaluate(LIST_STATE))
        assert state["listed"] == ["b.png"] and state["removals"] == [str(first["id"])]
        # Nothing is removed until the form is sent.
        assert [row["id"] for row in _attachments(request["id"])] == [first["id"], second["id"]]
    finally:
        session.close()


@browser
def test_a_browser_submit_sends_exactly_the_listed_files(env, files):
    """The real multipart the browser posts carries exactly the listed files.

    (Chrome's Fetch interception, which serves these pages from the test
    client, forwards the file *parts* but not their bytes, so persistence of
    the files themselves is proven by the server-side tests above.)
    """
    student = _as_student(env)
    version = _version(student)
    session = BrowserSession(env["client"], CHROMIUM)
    try:
        session.goto("/aluno/nova-requisicao")
        _pick(session, [files / "a.pdf"])
        _pick(session, [files / "b.png"])
        session.click('#comprovantes-list .file-list-remove[aria-label="Remover comprovante a.pdf"]')
        session.requests.clear()
        session.evaluate(
            "(() => { const f = document.querySelector('form[enctype]');"
            " const sel = f.querySelector('#atividade_versao_id_select'); sel.disabled = false;"
            " const opt = document.createElement('option'); opt.value = '%s'; sel.appendChild(opt); sel.value = '%s';"
            " f.querySelector('[name=nome_evento]').value = 'Envio pelo navegador';"
            " f.querySelector('[name=data_evento]').value = '2026-09-06';"
            " f.querySelector('[name=horas_solicitadas]').value = '2';"
            " f.submit(); return true; })()" % (version, version)
        )
        session.pump(2.0)
        posts = [body for method, path, body in session.requests if method == "POST" and path == "/aluno/nova-requisicao"]
    finally:
        session.close()
    assert len(posts) == 1
    assert re.findall(r'name="comprovantes_files"; filename="([^"]*)"', posts[0]) == ["b.png"]
