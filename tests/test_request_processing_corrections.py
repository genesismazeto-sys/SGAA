"""Processing corrections on synthetic data, including real Chromium flows."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import pytest
import main

from app.request_email_notifications import load_pending_events, pending_request_ids
from app.request_email_recovery import recover_return_notification
from app.request_email_render import render_request_block
from app.requisitions import auto_indefer_devolvidas
from tests.request_email_support import install_email_preset
from tests.test_request_rectification_flow import (
    REASON, _as_admin, _browser, _db, _events, _no_file_request, _process,
    _row, _set_days, browser, env,
)


def screenshot(session, name):
    """Optional visual evidence, always outside the repository and synthetic."""
    directory = os.environ.get("SGAA_PROCESSING_SCREENSHOTS")
    if directory:
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        result = session.call("Page.captureScreenshot", {"format": "png"})
        (path / name).write_bytes(base64.b64decode(result["data"]))


def test_return_snapshot_preview_and_automatic_expiry(env):
    request_id = _no_file_request(env, "Synthetic return")
    assert _process(env, request_id, status="Devolvida", observacao=REASON).status_code == 302
    with main.app.app_context():
        conn = _db()
        assert pending_request_ids(conn) == {request_id}
        block = render_request_block(load_pending_events(conn, [request_id]))
        assert "Resultado: Devolvida para retificação" in block and REASON in block
        assert "Indeferida" not in block
        conn.execute("UPDATE requisicoes SET data_processamento='2000-01-01' WHERE id=?", (request_id,))
        conn.commit()
    _set_days(5, auto=True)
    with main.app.app_context():
        conn = _db()
        assert auto_indefer_devolvidas(conn) == 1
        assert pending_request_ids(conn) == set()
    assert _events(request_id) == [{"status_decisao": "Devolvida", "estado": "superseded"}]


def test_legacy_recovery_is_bounded_opt_in_and_idempotent(env):
    request_id = _no_file_request(env, "Synthetic legacy return")
    assert _process(env, request_id, status="Devolvida", observacao=REASON).status_code == 302
    stamp = _row(request_id)["data_processamento"]
    with main.app.app_context():
        conn = _db()
        # Simulate a pre-fix decision without touching real data.
        conn.execute("DELETE FROM requisicao_email_eventos WHERE requisicao_id=?", (request_id,))
        conn.commit()
        args = {"request_id": request_id, "decided_at": stamp}
        assert recover_return_notification(conn, **args) == "eligible"
        assert pending_request_ids(conn) == set()
        assert recover_return_notification(conn, request_id=request_id, decided_at="2000-01-01", apply=True) == "ineligible"
        assert recover_return_notification(conn, **args, apply=True) == "recovered"
        assert recover_return_notification(conn, **args, apply=True) == "ineligible"
        assert len(load_pending_events(conn, [request_id])) == 1


@browser
def test_readable_locked_modes_and_attachment_labels_in_chromium(env):
    request_id = _no_file_request(env, "Synthetic readable details")
    _as_admin(env)
    session = _browser(env)
    try:
        session.goto("/admin/requisicoes")
        session.evaluate(f"window.__openExistingReqModal({request_id}, 'process')")
        session.wait_for("!document.getElementById('req-modal').hidden")
        for mode in ("process", "view"):
            session.evaluate(f"window.__setReqModalMode('{mode}')")
            fields = json.loads(session.evaluate("""JSON.stringify([
              'm_aluno_id_select','m_tipo_atividade_select','m_grupo_num',
              'm_atividade_versao_id_select','#req-form input[name=nome_evento]','#m_card-horas input','#m_card-data input'
            ].map(id => {const e=id.startsWith('#')?document.querySelector(id):document.getElementById(id), s=getComputedStyle(e);
              return {id, locked:e.disabled || e.readOnly, colour:s.color, fill:s.webkitTextFillColor, opacity:s.opacity};}))"""))
            assert all(f["locked"] and f["opacity"] == "1" for f in fields), fields
            assert len({f["colour"] for f in fields}) == 1, fields
            assert all(f["fill"] == f["colour"] for f in fields), fields
        screenshot(session, "readable-details.png")
        name = 'certificado "real" <1>.pdf'
        docs = [{"label": "Comprovante", "filename": name, "url": "/documento/1"},
                {"label": "Outro", "filename": "segundo.pdf", "url": "/documento/2"}]
        for count, labels in ((0, ["Comprovantes"]), (1, ["Comprovante"]), (2, ["Comprovante 1", "Comprovante 2"])):
            session.evaluate(f"window.__renderAnexos({json.dumps(docs[:count])})")
            assert json.loads(session.evaluate("JSON.stringify([...document.querySelectorAll('#m_comprovantes_container .row-label')].map(e=>e.textContent))")) == labels
            if count:
                assert session.evaluate("document.querySelector('#m_comprovantes_container [data-file-name]').textContent") == name
                screenshot(session, f"attachments-{count}.png")
        session.evaluate("window.__setReqModalMode('edit')")
        assert session.evaluate("!document.getElementById('req-modal').classList.contains('form-readonly-readable') && !document.querySelector('#req-form input[name=nome_evento]').readOnly")
    finally:
        session.close()


@browser
@pytest.mark.parametrize("width", [1280, 390])
def test_save_preset_then_use_it_without_reload(env, width):
    request_id = _no_file_request(env, "Synthetic preset")
    _as_admin(env)
    session = _browser(env, width)
    try:
        session.goto("/admin/requisicoes")
        session.evaluate("window.__loadJustPresetsOnce()")
        session.click("#req-presets-btn")
        session.wait_for("!document.getElementById('preset-add').disabled")
        session.click("#preset-add")
        session.evaluate("""(() => {
          const t=document.getElementById('preset-title-input'), b=document.getElementById('preset-textarea');
          t.value='Modelo imediato'; t.dispatchEvent(new Event('input'));
          b.value='Justificativa recém-persistida.'; b.dispatchEvent(new Event('input'));
        })()""")
        session.click("#presets-save")
        session.wait_for("!document.getElementById('presets-save').disabled")
        with main.app.app_context():
            assert _db().execute("SELECT texto FROM configuracoes_presets WHERE titulo='Modelo imediato'").fetchone()[0] == "Justificativa recém-persistida."
        layout = json.loads(session.evaluate("""JSON.stringify((() => {
          const s=document.getElementById('presets-save'), c=document.getElementById('req-presets-ok');
          return {primary:s.classList.contains('primary'), secondary:!c.classList.contains('primary'),
            heights:[s.clientHeight,c.clientHeight], colours:[getComputedStyle(s).backgroundColor,getComputedStyle(c).backgroundColor],
            fits:[s,c].every(b=>{const r=b.getBoundingClientRect();return r.left>=0 && r.right<=innerWidth && b.scrollWidth<=b.clientWidth;})};
        })())"""))
        assert layout["primary"] and layout["secondary"] and layout["fits"], layout
        assert layout["heights"][0] == layout["heights"][1] and layout["colours"][0] != layout["colours"][1], layout
        screenshot(session, f"presets-{width}.png")
        session.click("#req-presets-ok")
        session.evaluate(f"window.__openExistingReqModal({request_id}, 'process')")
        session.wait_for("[...document.querySelectorAll('#m_just_select option')].some(o=>o.textContent==='Modelo imediato')")
        session.evaluate("""(() => {const s=document.getElementById('m_just_select');
          s.value=[...s.options].find(o=>o.textContent==='Modelo imediato').value;
          window.__applyJustSelectionBehavior();})()""")
        assert session.evaluate("document.getElementById('m_justificativa').value") == "Justificativa recém-persistida."
    finally:
        session.close()


@browser
@pytest.mark.parametrize("status", ["Devolvida", "Indeferida", "Deferida", "Deferida Parcialmente"])
def test_explicit_decision_preview_and_send_in_chromium(env, monkeypatch, status):
    import app.request_email_dispatch as dispatch
    import app.services.mail_service as mail
    sent = []
    monkeypatch.setattr(dispatch, "send_text_email", lambda conn, message: sent.append(message) or {"status": "sent", "http_status": 202})
    monkeypatch.setattr(mail, "mail_transport_status", lambda conn: {
        "ready": True, "message": "Synthetic transport", "reason": "ready", "provider_connected": True,
    })
    request_id = _no_file_request(env, "Synthetic decision " + status)
    with main.app.app_context():
        conn = _db()
        conn.execute("DELETE FROM configuracoes_presets WHERE tipo='emails'")
        install_email_preset(conn)
        conn.commit()
    _as_admin(env)
    session = _browser(env)
    try:
        session.goto("/admin/requisicoes")
        session.evaluate(f"window.__openExistingReqModal({request_id}, 'process')")
        action = "deferir" if status == "Deferida" else "deferir_parte" if status == "Deferida Parcialmente" else "indeferir"
        session.click(f'#m_footer_actions [data-action="{action}"]')
        if status != "Deferida":
            session.evaluate(f"document.getElementById('m_justificativa').value={json.dumps(REASON)}")
        if status == "Deferida Parcialmente":
            session.evaluate("document.getElementById('m_horas_deferidas').value='1'")
        session.click("#m_footer_confirm")
        if action == "indeferir":
            session.wait_for("!document.getElementById('rejection-decision-dialog').hidden")
            session.click(f'[data-rejection-choice="{status}"]')
        session.wait_for(f"!!document.querySelector('[data-req-id=\"{request_id}\"][data-email-pending=\"1\"]')")
        assert _row(request_id)["status"] == status
        assert sent == []
        session.evaluate(f"window.openRequisicoesEmailConfirm([{request_id}])")
        session.wait_for("!document.getElementById('req-email-confirm').disabled")
        body = session.evaluate("document.getElementById('req-email-preview').textContent")
        expected = "Devolvida para retificação" if status == "Devolvida" else status
        assert f"Resultado: {expected}" in body
        if status != "Deferida":
            assert REASON in body
        assert sent == []
        session.evaluate("document.getElementById('req-email-preview-wrap').open=true")
        screenshot(session, f"email-{status}.png")
        session.click("#req-email-confirm")
        session.wait_for("!document.getElementById('req-email-result').hidden")
        assert len(sent) == 1
        assert _events(request_id) == [{"status_decisao": status, "estado": "sent"}]
        # Repeated confirmation cannot deliver the same generation twice.
        response = env["client"].post("/admin/requisicoes/email/enviar", json={"requisicao_ids": [request_id]})
        assert response.status_code == 409 and len(sent) == 1
    finally:
        session.close()


@browser
def test_preset_read_write_race_and_failure_do_not_publish_a_draft(env):
    _as_admin(env)
    session = _browser(env)
    try:
        session.goto("/admin/requisicoes")
        result = session.evaluate("""(async () => {
          const original=window.fetch, store=window.__reqPresetStore;
          let releaseRead, releaseSave;
          const old={respostas:[{id:1,titulo:'Antigo',texto:'Antigo'}],emails:[]};
          const fresh={respostas:[{id:2,titulo:'Novo',texto:'Confirmado'}],emails:[]};
          window.fetch=(_url,opts) => opts?.method==='POST'
            ? new Promise(resolve=>releaseSave=()=>resolve(new Response('{"ok":true}')))
            : new Promise(resolve=>releaseRead=()=>resolve(new Response(JSON.stringify(old))));
          const read=store.load(true), save=store.save(fresh,{});
          const before=(window.__justPresets||[]).some(p=>p.titulo==='Novo');
          releaseSave(); await save; releaseRead(); const loaded=await read;
          window.fetch=async()=>new Response('{"ok":false}',{status:500});
          let failed=false;try{await store.save(old,{})}catch(e){failed=true}
          const after=await store.load(); window.fetch=original;
          return JSON.stringify({before, loaded, after, failed});
        })()""")
        value = json.loads(result)
        assert value["before"] is False and value["failed"] is True
        assert value["loaded"]["respostas"][0]["titulo"] == "Novo"
        assert value["after"] == value["loaded"]
    finally:
        session.close()


@browser
def test_preset_ui_confirms_only_persistence_and_close_discards_draft(env):
    _as_admin(env)
    session = _browser(env)
    try:
        session.goto("/admin/requisicoes")
        session.click("#req-presets-btn")
        session.wait_for("!document.getElementById('preset-add').disabled")
        session.click("#preset-add")
        session.evaluate("""(() => {
          window.savedToasts=[]; window.showToast=(message,type)=>savedToasts.push(type);
          const title=document.getElementById('preset-title-input');
          title.value='Unsaved synthetic draft';title.dispatchEvent(new Event('input'));
          window.originalPresetFetch=window.fetch;
          window.fetch=(url,opts)=>opts?.method==='POST'
            ?new Promise(resolve=>window.failPresetSave=()=>resolve(new Response('{"ok":false}',{status:500})))
            :window.originalPresetFetch(url,opts);
        })()""")
        session.click("#presets-save")
        session.wait_for("typeof window.failPresetSave==='function'")
        assert session.evaluate("JSON.stringify(window.savedToasts)") == "[]"
        assert session.evaluate("document.getElementById('presets-save').disabled")
        session.evaluate("window.failPresetSave()")
        session.wait_for("window.savedToasts.includes('error')")
        assert session.evaluate("!window.savedToasts.includes('success')")
        session.evaluate("window.fetch=window.originalPresetFetch")
        session.click("#req-presets-ok")
        session.click("#req-presets-btn")
        session.wait_for("!document.getElementById('preset-add').disabled")
        assert not session.evaluate("document.getElementById('presets-list').textContent.includes('Unsaved synthetic draft')")
        with main.app.app_context():
            assert _db().execute("SELECT 1 FROM configuracoes_presets WHERE titulo='Unsaved synthetic draft'").fetchone() is None
    finally:
        session.close()
