"""UI-C03 -- the Requisições modal in Ver can never submit.

The defect (UI-C02, S3): Editar wrote ``form.action`` for R1 and nothing ever
cleared it. Ver only *hid* the submit button, and a hidden default button still
fires on implicit submission -- so Enter in any read-only field of Ver POSTed
the viewed request's values to R1's edit endpoint, overwriting R1 and nulling
its observação.

The contract now:

* the form is rendered with no action; only Criar/Editar assign one, and
  Editar also names its target in ``edit_target_id``;
* every other mode, and every close, removes the action, clears the target and
  disables the submit button (a *disabled* default button is what blocks
  implicit submission);
* the edit endpoint refuses a POST whose ``edit_target_id`` is not the request
  in its URL, so a stale form cannot write even if a browser got one out.

Browser tests drive real headless Chromium with trusted key/mouse input; every
request the page makes is answered by the Flask test client on an isolated
database (tests/cdp_browser_support.py -- no application port is opened).
"""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

import pytest

import main
from app.user_accounts import create_usuario_with_access_level
from tests.canonical_request_test_support import create_admin_request, login_admin
from tests.cdp_browser_support import BrowserSession, find_chromium
from tests.session_support import stamp_auth_version
from tests.versioned_test_support import isolated_versioned_app_env

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "admin_requisicoes.html"


def _rows(conn):
    return [tuple(r) for r in conn.execute("SELECT * FROM requisicoes ORDER BY id").fetchall()]


def _seed_two(client):
    login_admin(client)
    _r, r1 = create_admin_request(client, name=f"C03 R1 {uuid.uuid4().hex[:6]}")
    _r, r2 = create_admin_request(client, name=f"C03 R2 {uuid.uuid4().hex[:6]}")
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("UPDATE requisicoes SET observacao='OBS R1' WHERE id=?", (r1["id"],))
        conn.execute(
            "UPDATE requisicoes SET observacao='OBS R2', horas_solicitadas=7 WHERE id=?", (r2["id"],)
        )
        conn.commit()
    return r1["id"], r2["id"]


def _snapshot():
    with main.app.app_context():
        return _rows(main.get_db_connection())


def _row(req_id):
    with main.app.app_context():
        return dict(
            main.get_db_connection()
            .execute("SELECT nome_evento,horas_solicitadas,data_evento,observacao FROM requisicoes WHERE id=?", (req_id,))
            .fetchone()
        )


def _consultor(client):
    with main.app.app_context():
        conn = main.get_db_connection()
        uid = create_usuario_with_access_level(
            conn,
            "C03 consultor",
            f"c03-{uuid.uuid4().hex[:8]}@example.invalid",
            main.hash_password("c03"),
            "admin",
            "consultivo",
            credential_state="personal",
        ).lastrowid
        conn.commit()
    with client.session_transaction() as session:
        session.update(user_id=uid, user_type="admin", user_name="C03 consultor")
        stamp_auth_version(session)


# ================================================================ server side

def _edit_payload(nome, target):
    data = {"nome_evento": nome, "horas_solicitadas": "3", "data_evento": "2026-05-02", "observacao": "editada"}
    if target is not None:
        data["edit_target_id"] = str(target)
    return data


def test_edit_with_its_own_target_updates_only_that_request(tmp_path):
    with isolated_versioned_app_env(tmp_path, "c03-edit.db") as env:
        r1, r2 = _seed_two(env["client"])
        before_r2 = _row(r2)
        response = env["client"].post(f"/admin/requisicoes/{r1}/editar", data=_edit_payload("R1 editada", r1))
        assert response.status_code == 302
        assert _row(r1) == {
            "nome_evento": "R1 editada", "horas_solicitadas": 3.0,
            "data_evento": "2026-05-02", "observacao": "editada",
        }
        assert _row(r2) == before_r2


@pytest.mark.parametrize("target", [None, "", "R2"])
def test_a_stale_or_untargeted_edit_post_writes_nothing(tmp_path, target):
    """The exact payload Ver used to send (no target, observação absent) and a
    form filled for another request are both refused before any write."""
    with isolated_versioned_app_env(tmp_path, "c03-stale.db") as env:
        r1, r2 = _seed_two(env["client"])
        before = _snapshot()
        data = {"nome_evento": "vazou de R2", "horas_solicitadas": "7", "data_evento": "2026-05-01"}
        if target is not None:
            data["edit_target_id"] = str(r2) if target == "R2" else target
        response = env["client"].post(f"/admin/requisicoes/{r1}/editar", data=data, follow_redirects=True)
        assert "Falha ao atualizar requisição." in response.get_data(as_text=True)
        assert _snapshot() == before
        assert _row(r1)["observacao"] == "OBS R1"


def test_view_only_account_cannot_edit_even_with_a_valid_target(tmp_path):
    with isolated_versioned_app_env(tmp_path, "c03-rbac.db") as env:
        r1, _r2 = _seed_two(env["client"])
        before = _snapshot()
        _consultor(env["client"])
        assert env["client"].get("/admin/requisicoes").status_code == 200
        assert env["client"].get(f"/admin/api/requisicao/{r1}").status_code == 200
        denied = env["client"].post(f"/admin/requisicoes/{r1}/editar", data=_edit_payload("x", r1))
        assert denied.status_code == 302 and denied.headers["Location"].endswith("/admin/dashboard")
        assert _snapshot() == before


def test_rendering_the_list_and_the_modal_payload_is_read_only(tmp_path):
    with isolated_versioned_app_env(tmp_path, "c03-get.db") as env:
        r1, r2 = _seed_two(env["client"])
        before = _snapshot()
        env["client"].get("/admin/requisicoes")
        env["client"].get(f"/admin/api/requisicao/{r1}")
        env["client"].get(f"/admin/api/requisicao/{r2}")
        assert _snapshot() == before


def test_template_contract():
    source = TEMPLATE.read_text(encoding="utf-8")
    form_tag = re.search(r'<form id="req-form"[^>]*>', source).group(0)
    assert "action=" not in form_tag, "the modal form must not be rendered with a live action"
    assert '<input type="hidden" name="edit_target_id" id="m_edit_target_id" value="">' in source
    # Ver and Processar clear the target; close clears it; Criar/Editar re-arm only with a match.
    assert source.count("clearWritableTarget();") >= 5
    assert "createSubmit.disabled = true" in source
    assert "`/admin/requisicoes/${targetId}/editar`, targetId)" in source
    # "Abrir" (open an existing receipt) is a read action and is no longer dimmed in Ver.
    assert "chip.style.pointerEvents" not in source and "chip.style.opacity" not in source


# ================================================================ browser side

CHROMIUM = find_chromium()
browser = pytest.mark.skipif(CHROMIUM is None, reason="no headless Chromium available")

READY = "document.readyState === 'complete' && !!window.__openExistingReqModal"
STATE = """JSON.stringify((() => {
  const m = document.getElementById('req-modal');
  const f = document.getElementById('req-form');
  const b = document.getElementById('m_create_submit');
  return {mode: m.getAttribute('data-mode'), hidden: m.hidden, reqId: m.dataset.reqId || null,
          action: f.getAttribute('action'), target: document.getElementById('m_edit_target_id').value,
          submitDisabled: b.disabled, submitHidden: b.hidden};
})())"""
NOT_WRITABLE = {"action": None, "target": "", "submitDisabled": True, "submitHidden": True}


@pytest.fixture
def page(tmp_path):
    with isolated_versioned_app_env(tmp_path, "c03-browser.db") as env:
        r1, r2 = _seed_two(env["client"])
        session = BrowserSession(env["client"], CHROMIUM)
        try:
            session.goto("/admin/requisicoes", READY)
            session.evaluate(
                "window.__submits = []; document.addEventListener('submit',"
                " e => window.__submits.push(e.target.id), true); true"
            )
            yield session, env, r1, r2
        finally:
            session.close()


def _state(session):
    return json.loads(session.evaluate(STATE))


def _open(session, req_id, mode):
    session.evaluate(f"window.__openExistingReqModal('{req_id}', '{mode}')")
    session.wait_for(
        "(() => { const m = document.getElementById('req-modal');"
        f" return !m.hidden && m.getAttribute('data-mode') === '{mode}' && m.dataset.reqId === '{req_id}'; }})()"
    )


def _close(session):
    session.evaluate("document.getElementById('req-modal-close').click()")
    session.wait_for("document.getElementById('req-modal').hidden")


def _enter_in(session, name):
    focused = session.evaluate(
        f"(() => {{ const el = document.querySelector('#req-form [name={name}]'); el.focus();"
        " return document.activeElement === el && el.readOnly; })()"
    )
    assert focused, f"{name} is not a focused read-only field"
    sent = len(session.requests)
    session.press_enter()
    session.pump(1.0)
    return [r for r in session.requests[sent:] if r[0] != "GET"]


def _assert_view_is_inert(session, name="nome_evento"):
    assert {k: _state(session)[k] for k in NOT_WRITABLE} == NOT_WRITABLE
    assert _enter_in(session, name) == [], "Ver sent a mutation request"
    assert session.evaluate("JSON.stringify(window.__submits)") == "[]", "a submit event fired in Ver"


@browser
def test_a_edit_r1_close_view_r2_enter_posts_nothing(page):
    session, _env, r1, r2 = page
    before = _snapshot()
    _open(session, r1, "edit")
    assert _state(session)["action"] == f"/admin/requisicoes/{r1}/editar"
    _close(session)
    _open(session, r2, "view")
    for field in ("nome_evento", "horas_solicitadas", "data_evento"):
        _assert_view_is_inert(session, field)
    assert _snapshot() == before


@browser
def test_b_switching_straight_from_edit_to_view_drops_the_target(page):
    session, _env, r1, r2 = page
    before = _snapshot()
    _open(session, r1, "edit")
    _open(session, r2, "view")  # no close in between
    _assert_view_is_inert(session)
    assert _snapshot() == before


@browser
def test_c_view_from_a_fresh_page_load_cannot_submit(page):
    session, _env, _r1, r2 = page
    before = _snapshot()
    assert _state(session)["action"] is None, "the page loaded with a live form action"
    _open(session, r2, "view")
    _assert_view_is_inert(session)
    assert _snapshot() == before


@browser
def test_d_view_then_edit_rebuilds_the_target_and_save_updates_only_r1(page):
    session, _env, r1, r2 = page
    before_r2 = _row(r2)
    _open(session, r2, "view")
    _close(session)
    _open(session, r1, "edit")
    state = _state(session)
    assert state["action"] == f"/admin/requisicoes/{r1}/editar" and state["target"] == str(r1)
    assert state["submitDisabled"] is False and state["submitHidden"] is False
    session.evaluate("document.querySelector('#req-form [name=nome_evento]').value = 'R1 via Salvar'; true")
    sent = len(session.requests)
    session.click("#m_create_submit")
    session.wait_for("document.readyState === 'complete' && !!window.__openExistingReqModal")
    session.pump(0.5)
    posts = [r for r in session.requests[sent:] if r[0] == "POST"]
    assert [p[1] for p in posts] == [f"/admin/requisicoes/{r1}/editar"]
    # STORAGE S3-A: the request form no longer posts multipart (no file bytes);
    # the browser sends it url-encoded, naming the same edit target.
    assert f"edit_target_id={r1}" in posts[0][2].split("&")
    assert _row(r1)["nome_evento"] == "R1 via Salvar"
    assert _row(r1)["observacao"] == "OBS R1", "a normal edit must keep observação"
    assert _row(r2) == before_r2


@browser
def test_e_edit_r1_close_edit_r2_targets_r2_only(page):
    session, _env, r1, r2 = page
    before_r1 = _row(r1)
    _open(session, r1, "edit")
    _close(session)
    _open(session, r2, "edit")
    state = _state(session)
    assert state["action"] == f"/admin/requisicoes/{r2}/editar" and state["target"] == str(r2)
    session.evaluate("document.querySelector('#req-form [name=nome_evento]').value = 'R2 editada'; true")
    sent = len(session.requests)
    session.click("#m_create_submit")
    session.wait_for("document.readyState === 'complete' && !!window.__openExistingReqModal")
    session.pump(0.5)
    assert [r[1] for r in session.requests[sent:] if r[0] == "POST"] == [f"/admin/requisicoes/{r2}/editar"]
    assert _row(r2)["nome_evento"] == "R2 editada"
    assert _row(r1) == before_r1


@browser
def test_f_view_only_account_can_view_and_cannot_submit(tmp_path):
    with isolated_versioned_app_env(tmp_path, "c03-browser-rbac.db") as env:
        _r1, r2 = _seed_two(env["client"])
        before = _snapshot()
        _consultor(env["client"])
        session = BrowserSession(env["client"], CHROMIUM)
        try:
            session.goto("/admin/requisicoes", READY)
            session.evaluate(
                "window.__submits = []; document.addEventListener('submit',"
                " e => window.__submits.push(e.target.id), true); true"
            )
            session.evaluate(f"window.__openExistingReqModal('{r2}', 'edit')")  # downgraded to view
            session.wait_for(
                "(() => { const m = document.getElementById('req-modal');"
                " return !m.hidden && m.getAttribute('data-mode') === 'view'; })()"
            )
            assert session.evaluate("document.querySelector('#req-form [name=nome_evento]').value").startswith("C03 R2")
            _assert_view_is_inert(session)
        finally:
            session.close()
        assert _snapshot() == before


@browser
def test_h_abrir_stays_available_in_view(page):
    """'Abrir' only calls window.open on an existing receipt -- a read action."""
    session, _env, _r1, r2 = page

    def with_receipt(payload: bytes) -> bytes:
        data = json.loads(payload)
        data["anexos"] = [{"label": "Certificado", "filename": "certificado.pdf", "url": "/comprovantes/1/open"}]
        return json.dumps(data).encode()

    session.response_rewrites[f"/admin/api/requisicao/{r2}"] = with_receipt
    session.evaluate("window.__opened = []; window.open = (u) => { window.__opened.push(u); return null; }; true")
    _open(session, r2, "view")
    chip = "#m_comprovantes_container .chip-right"
    style = json.loads(session.evaluate(
        f"JSON.stringify((() => {{ const c = getComputedStyle(document.querySelector('{chip}'));"
        " return {pe: c.pointerEvents, op: c.opacity}; })())"
    ))
    assert style == {"pe": "auto", "op": "1"}
    session.click(chip)
    session.pump(0.2)
    assert session.evaluate("JSON.stringify(window.__opened)") == '["/comprovantes/1/open"]'
    assert [r for r in session.requests if r[0] != "GET"] == []


@browser
def test_i_j_close_leaves_no_target_and_ver_changes_no_field(page):
    session, _env, r1, r2 = page
    before = _snapshot()
    for req_id, mode in ((r1, "edit"), (r2, "view"), (r1, "process"), (r2, "edit")):
        _open(session, req_id, mode)
        _close(session)
        state = _state(session)
        assert {k: state[k] for k in NOT_WRITABLE} == NOT_WRITABLE, (mode, state)
        assert state["mode"] is None and state["reqId"] is None, (mode, state)
    # Process mode is not Editar either: its enabled fields cannot submit the form.
    _open(session, r1, "process")
    assert {k: _state(session)[k] for k in NOT_WRITABLE} == NOT_WRITABLE
    assert session.evaluate("JSON.stringify(window.__submits)") == "[]"
    assert _snapshot() == before
