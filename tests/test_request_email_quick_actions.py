"""UI-B49: the pending-email icon opens quick actions for administrators who may edit.

Template contract on an isolated application database with fictitious data:
who gets an actionable icon, what the read-only icon stays, and the dialog's
fixed three actions in a centred row. Behaviour is proven in a real browser by
tests/test_request_email_quick_actions_browser.py.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import main
from app.request_email_notifications import attach_events_to_send, pending_event_ids
from app.user_accounts import create_usuario_with_access_level, get_usuario_auth_version
from tests.canonical_matrix_test_support import login_admin
from tests.canonical_request_test_support import create_admin_request
from tests.versioned_test_support import isolated_versioned_app_env

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "email-quick-actions.db") as environment:
        login_admin(environment["client"])
        yield environment


def _flagged(client, name, *, failed=False):
    _response, row = create_admin_request(client, name=name)
    assert client.post(f"/admin/processar_requisicao/{row['id']}", data={"status": "Deferida"}).status_code == 302
    with main.app.app_context():
        conn = main.get_db_connection()
        event = pending_event_ids(conn, [row["id"]])[row["id"]]
        if failed:
            envio = conn.execute(
                "INSERT INTO email_envios(aluno_id,destinatario,assunto,corpo,status,tentativas,ultimo_erro,"
                "idempotency_key) VALUES(?, 'aluno@example.test', 'Resultado', 'Corpo', 'failed', 1, "
                "'Falha simulada.', ?) RETURNING id", (row["aluno_id"], f"quick-{row['id']}"),
            ).fetchone()[0]
            attach_events_to_send(conn, event_ids=[event], email_envio_id=envio)
            conn.commit()
    return row["id"]


def _cell(page, req_id):
    row = re.search(r'<div class="impresso-card[^"]*"[^>]*data-req-id="%d".*?(?=<div class="impresso-card|\Z)' % req_id,
                    page, re.S)
    assert row, req_id
    return re.search(r'<div class="cell center req-email-cell">(.*?)</div>', row.group(0), re.S).group(1)


def test_an_editor_gets_an_actionable_icon_for_both_variants(env):
    client = env["client"]
    pending = _flagged(client, "Semana acadêmica de saúde coletiva")
    failed = _flagged(client, "Congresso brasileiro de enfermagem", failed=True)
    page = client.get("/admin/requisicoes").get_data(as_text=True)
    for req_id, label, icon in ((pending, "E-mail pendente de envio", "mail"),
                                (failed, "E-mail pendente — última tentativa falhou.", "mail-warning")):
        cell = _cell(page, req_id)
        assert re.search(r'<button type="button" class="req-email-flag" data-email-quick aria-haspopup="dialog"\s+'
                         r'aria-label="%s" title="%s">' % (re.escape(label), re.escape(label)), cell), cell
        assert f'data-lucide="{icon}" aria-hidden="true"' in cell
        assert 'role="img"' not in cell


def test_a_read_only_profile_keeps_a_plain_status_icon(env):
    client = env["client"]
    req_id = _flagged(client, "Curso de primeiros socorros")
    with main.app.app_context():
        conn = main.get_db_connection()
        consultor = int(create_usuario_with_access_level(
            conn, "Consultora da coordenação", "consultora@example.test", "test-hash", "admin", "consultivo",
            credential_state="personal").lastrowid)
        conn.commit()
        version = get_usuario_auth_version(conn, consultor)
    with client.session_transaction() as session:
        session.update(user_id=consultor, user_type="admin", user_name="Consultora", auth_version=version)
    page = client.get("/admin/requisicoes").get_data(as_text=True)
    cell = _cell(page, req_id)
    assert 'role="img" aria-label="E-mail pendente de envio" title="E-mail pendente de envio"' in cell
    assert "<button" not in cell and 'class="req-email-flag"' not in page


def test_the_dialog_offers_exactly_three_actions_in_a_centred_row(env):
    page = env["client"].get("/admin/requisicoes").get_data(as_text=True)
    dialog = page.split('<div id="req-email-quick-modal"')[1].split("<!-- Modal:")[0]
    footer = re.search(r'<div class="modal-footer btn-row btn-row--center">(.*?)</div>', dialog, re.S).group(1)
    buttons = re.findall(r'<button class="(btn(?: primary)?)" id="([^"]+)" type="button">([^<]+)</button>', footer)
    assert [(cls, label) for cls, _id, label in buttons] == [
        ("btn", "Cancelar"), ("btn", "Desmarcar"), ("btn primary", "Enviar")]
    assert 'role="dialog" aria-modal="true"' in dialog


def test_a_modal_footer_centres_only_when_it_opts_in():
    actions = (ROOT / "static" / "css" / "components" / "actions.css").read_text(encoding="utf-8")
    modal = (ROOT / "static" / "css" / "components" / "modal.css").read_text(encoding="utf-8")
    assert ".modal-footer.btn-row--center{ justify-content:center; }" in actions
    # Every other modal footer keeps the component's right alignment.
    assert ".modal-footer{ display:flex; gap:8px; justify-content:flex-end;" in modal
