"""UI-B23: several comprovantes per request, explicit removal, field guidance.

Trace (before this change): the input already declared ``multiple`` and both
student handlers already read ``getlist("comprovantes_files")`` into one
``requisicao_arquivos`` row per file, so storage was never limited to one.
The limit was the page: a second picker interaction replaced the native
FileList (silently dropping the first choice), two or more files collapsed
into "N arquivos selecionados" with the names only in a stripped ``title``,
and no stored comprovante could be removed individually.

Contract now (STORAGE S3-A: request documents upload straight to canonical
storage -- static/js/direct-upload.js -- and the form posts only the verified
intent ids, never file bytes):
* picking appends; every selected file gets its own upload slot and is listed
  with its own remove button; the form cannot be submitted until every listed
  file is verified or removed, and a submit never carries file parts;
* a stored comprovante is removed only when its id is submitted in
  ``remover_comprovantes`` -- an omitted list keeps every file, and an id that
  is not a current attachment of this request refuses the whole edit;
* an invalid file is refused before any upload and the message names it;
* "Nome do evento" / "Data do evento" guidance is visible whenever the form is
  editable, tied to its control with aria-describedby.
"""
from __future__ import annotations

import json
import re
import struct
import zlib
from pathlib import Path

import pytest

import main
from tests.canonical_request_documents_support import (
    INTENT_IDS_FIELD,
    SUBMISSION_FIELD,
    canonical_documents,
    form_submission,
    issue,
    upload_verified,
)
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
            with canonical_documents(main.app) as canonical:
                yield {**environment, "storage": storage, "canonical": canonical}
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


def _create(env, files, name="Palestra B23"):
    """A request whose documents went through the canonical direct-upload protocol."""
    student = _as_student(env)
    submission = form_submission(env["client"], "/aluno/nova-requisicao")
    intent_ids = [
        upload_verified(env["client"], env["canonical"], submission, content, filename)
        for content, filename in files
    ]
    response = env["client"].post(
        "/aluno/nova-requisicao",
        data={
            "atividade_versao_id": str(_version(student)),
            "nome_evento": name,
            "data_evento": "2026-09-06",
            "horas_solicitadas": "2",
            SUBMISSION_FIELD: submission,
            INTENT_IDS_FIELD: intent_ids,
        },
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
        submission = form_submission(env["client"], f"/aluno/requisicoes/{request_id}?edit=1")
        payload[SUBMISSION_FIELD] = submission
        payload[INTENT_IDS_FIELD] = [
            upload_verified(env["client"], env["canonical"], submission, content, filename,
                            requisicao_id=request_id)
            for content, filename in files
        ]
    return env["client"].post(f"/aluno/requisicoes/{request_id}", data=payload)


def _flashes(client):
    with client.session_transaction() as session:
        return [message for _category, message in session.get("_flashes", [])]


# --------------------------------------------------------------- several files


def test_two_proofs_in_one_request_persist_and_are_visible_everywhere(env):
    response, request = _create(env, [(PDF, "certificado.pdf"), (PNG, "foto-evento.png")])
    assert response.status_code == 302 and request is not None
    rows = _attachments(request["id"])
    assert [row["original_filename"] for row in rows] == ["certificado.pdf", "foto-evento.png"]
    assert {row["provider"] for row in rows} == {"supabase"}
    assert len(env["canonical"].objects) == 2 and env["storage"].files == {}

    client = env["client"]
    edit_page = client.get(f"/aluno/requisicoes/{request['id']}?edit=1").get_data(as_text=True)
    detail_page = client.get(f"/aluno/requisicoes/{request['id']}").get_data(as_text=True)
    for row in rows:
        url = f"/comprovantes/{row['id']}/open"
        assert url in edit_page and url in detail_page
        assert client.get(url).status_code == 302  # signed canonical URL, never a proxied body
    assert "certificado.pdf" in edit_page and "foto-evento.png" in edit_page

    _as_admin(env)
    direct = client.get(f"/admin/requisicao/{request['id']}").get_data(as_text=True)
    process = client.get(f"/admin/processar_requisicao/{request['id']}").get_data(as_text=True)
    api = client.get(f"/admin/api/requisicao/{request['id']}").get_json()
    assert len(api["anexos"]) == 2
    for row in rows:
        url = f"/comprovantes/{row['id']}/open"
        assert url in direct and url in process
        assert client.get(url).status_code == 302


def test_same_filename_with_different_content_is_kept_twice_without_collision(env):
    _response, request = _create(env, [(PNG, "comprovante.png"), (PNG_OTHER, "comprovante.png")])
    rows = _attachments(request["id"])
    assert [row["original_filename"] for row in rows] == ["comprovante.png", "comprovante.png"]
    assert len({row["filename"] for row in rows}) == 2
    assert len({row["sha256"] for row in rows}) == 2


def test_one_invalid_file_is_refused_before_any_upload_and_names_it(env):
    """The refusal happens at issue time, per file, naming it; nothing is uploaded or created.

    (Submission stays blocked in the browser while a listed file is unresolved --
    see the direct-upload browser test below.)"""
    _as_student(env)
    submission = form_submission(env["client"], "/aluno/nova-requisicao")
    refused = issue(env["client"], submission, b"texto", "planilha.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert refused.status_code == 400
    assert refused.get_json()["message"] == "planilha.xlsx: envie somente arquivos PDF, PNG ou JPEG."
    assert env["canonical"].calls == [] and env["storage"].upload_calls == []
    with main.app.app_context():
        assert _db().execute("SELECT count(*) FROM storage_upload_intents").fetchone()[0] == 0
        assert _db().execute("SELECT count(*) FROM requisicoes WHERE nome_evento='Lote invalido'").fetchone()[0] == 0


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
    assert _edit(env, request["id"], {"remover_comprovantes": str(first["id"])}).status_code == 302
    assert [row["id"] for row in _attachments(request["id"])] == [second["id"]]
    assert env["storage"].trashed == []  # canonical removal never touches Drive
    with main.app.app_context():
        removed = dict(_db().execute("SELECT * FROM requisicao_arquivos WHERE id=?", (first["id"],)).fetchone())
        lifecycle = _db().execute(
            "SELECT lifecycle_state FROM storage_objects WHERE id=?", (removed["storage_object_id"],)
        ).fetchone()[0]
    assert removed["storage_status"] == "trashed" and removed["storage_object_id"] == first["storage_object_id"]
    assert lifecycle == "retired" and len(env["canonical"].objects) == 2  # retired, never deleted
    assert _edit(env, request["id"], {}, files=[(PDF, "c.pdf")]).status_code == 302
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
    _response, other = _create(env, [(PDF, "outro.pdf")], name="Outra B23")
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
    """Legacy Google custody control: a pre-S3 Drive comprovante keeps its Drive removal."""
    from tests.test_comprovantes_routes import _legacy_google_attachment

    request, (first, second) = stored_pair
    legacy = _legacy_google_attachment(env, request["id"])
    env["storage"].fail_trash = True
    _edit(env, request["id"], {"nome_evento": "Edicao salva", "remover_comprovantes": str(legacy["id"])})
    assert [row["id"] for row in _attachments(request["id"])] == [first["id"], second["id"], legacy["id"]]
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


DIRECT_STATE = """JSON.stringify((() => {
  const input = document.getElementById('comprovantes_files');
  const form = input.form;
  return {
    enabled: !input.disabled,
    named: input.hasAttribute('name'),
    listed: Array.from(form.querySelectorAll('[data-direct-upload-list] li > span')).map(s => s.textContent.split(' — ')[0]),
    submitDisabled: Array.from(form.querySelectorAll('button[type="submit"]')).every(b => b.disabled),
    intents: Array.from(form.querySelectorAll('input[name="comprovantes_intent_ids"]')).map(i => i.value),
  };
})())"""


def _issue_bodies(session):
    return [json.loads(body) for method, path, body in session.requests
            if method == "POST" and path == "/storage/upload-intents"]


@browser
def test_direct_upload_picks_append_with_their_own_slots_and_block_submit_until_verified(env, files):
    """S3-A replaces the FileList picker for new files: each pick is declared to the
    application (slot + SHA-256, no bytes) and uploads straight to canonical storage;
    the harness blocks every non-local host, so these uploads never complete and the
    form must stay unsubmittable."""
    import hashlib

    _as_student(env)
    session = BrowserSession(env["client"], CHROMIUM)
    try:
        session.goto("/aluno/nova-requisicao")
        session.call("DOM.getDocument", {})
        state = json.loads(session.evaluate(DIRECT_STATE))
        assert state["enabled"] is True, "direct-upload.js enables the picker"
        assert state["named"] is False and state["listed"] == []
        # Guidance is on screen without any click or hover.
        visible = session.evaluate(
            "['nome-evento-orientacao','data-evento-orientacao'].every(id => {"
            " const el = document.getElementById(id); const r = el.getBoundingClientRect();"
            " return r.height > 0 && getComputedStyle(el).visibility === 'visible'; })"
        )
        assert visible is True

        _pick(session, [files / "a.pdf"])
        _pick(session, [files / "b.png"])
        session.wait_for("document.querySelectorAll('[data-direct-upload-list] li').length === 2")
        for _ in range(40):
            if len(_issue_bodies(session)) >= 2:
                break
            session.pump(0.1)
        bodies = _issue_bodies(session)
        assert [body["filename"] for body in bodies] == ["a.pdf", "b.png"]
        assert [body["sha256"] for body in bodies] == [
            hashlib.sha256(PDF).hexdigest(), hashlib.sha256(PNG).hexdigest()
        ]
        slots = [body["upload_slot_id"] for body in bodies]
        assert all(re.fullmatch(r"[0-9a-f]{32}", slot) for slot in slots) and len(set(slots)) == 2
        assert all(body["purpose"] == "comprovante" and body["size_bytes"] > 0 for body in bodies)

        state = json.loads(session.evaluate(DIRECT_STATE))
        assert state["listed"] == ["a.pdf", "b.png"]
        assert state["submitDisabled"] is True and state["intents"] == []

        session.evaluate(
            "(() => { const li = Array.from(document.querySelectorAll('[data-direct-upload-list] li'))"
            ".find(item => item.textContent.startsWith('a.pdf'));"
            " const buttons = li.querySelectorAll('button'); buttons[buttons.length - 1].click(); return true; })()"
        )
        state = json.loads(session.evaluate(DIRECT_STATE))
        assert state["listed"] == ["b.png"] and state["submitDisabled"] is True
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
def test_a_browser_submit_never_carries_file_bytes(env, files):
    """The browser never posts a file to the application.

    A pending (unverified) document blocks the submit event; even a forced
    ``form.submit()`` posts only the business fields and the submission id --
    the picker has no form name, so no file part can exist.
    """
    student = _as_student(env)
    version = _version(student)
    session = BrowserSession(env["client"], CHROMIUM)
    try:
        session.goto("/aluno/nova-requisicao")
        _pick(session, [files / "b.png"])
        session.wait_for("document.querySelectorAll('[data-direct-upload-list] li').length === 1")
        fill = (
            "const f = document.getElementById('comprovantes_files').form;"
            " const sel = f.querySelector('#atividade_versao_id_select'); sel.disabled = false;"
            " const opt = document.createElement('option'); opt.value = '%s'; sel.appendChild(opt); sel.value = '%s';"
            " f.querySelector('[name=nome_evento]').value = 'Envio pelo navegador';"
            " f.querySelector('[name=data_evento]').value = '2026-09-06';"
            " f.querySelector('[name=horas_solicitadas]').value = '2';" % (version, version)
        )
        session.requests.clear()
        session.evaluate("(() => { %s f.requestSubmit(); return true; })()" % fill)
        session.pump(1.0)
        blocked = [path for method, path, _body in session.requests if method == "POST" and path == "/aluno/nova-requisicao"]
        session.requests.clear()
        session.evaluate("(() => { %s f.submit(); return true; })()" % fill)
        session.pump(2.0)
        posts = [body for method, path, body in session.requests if method == "POST" and path == "/aluno/nova-requisicao"]
    finally:
        session.close()
    assert blocked == [], "an unresolved document must block the submit event"
    assert len(posts) == 1
    assert "filename=" not in posts[0] and "comprovantes_files" not in posts[0]
    assert "comprovantes_submission_id=" in posts[0]
