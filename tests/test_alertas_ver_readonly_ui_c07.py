"""UI-C07: Alertas Ver uses the shared read-only Design System.

Ver and Editar share one modal, switched by ``setModalMode``. Ver used to paint
its own read-only look -- ``#f8fafc`` on the controls, pipette buttons faded to
``opacity:.5`` -- which also overrode form.css's read-only contract.

Now Título/Mensagem take the shared paint (``.field-card:has(.control[readonly])``
-> ``--field-readonly-bg``, ``--text-secondary``) and declare ``aria-readonly``;
the colour hex fields, which are not ``.field-card``, restate the same tokens;
the pipettes (mutation-only) are omitted in Ver; swatches stay visible but
inert; the form carries no ``action`` in Ver. Editar is unchanged, and the
recipient preview still shows the MESSAGE only (UI-B04).

The browser half drives real headless Chromium through the Flask test client
(no app port) and skips where that harness or a Chromium binary is absent.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest

import main
from app.user_accounts import create_usuario_with_access_level
from tests.session_support import stamp_auth_version
from tests.versioned_test_support import isolated_versioned_app_env

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "admin_alertas.html"
RAW_COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(")
TITLE = "Título interno UI-C07"
MESSAGE = "Mensagem ao destinatário UI-C07"


def _style(text: str) -> str:
    return "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", text, re.S))


# ==========================================================================
# Static contract
# ==========================================================================


def test_local_read_only_clones_are_gone():
    style = _style(TEMPLATE.read_text(encoding="utf-8"))
    assert "#f8fafc" not in style
    assert ".modal-card.is-readonly .control" not in style
    assert not re.search(r"\.alerta-pick-btn\{[^}]*opacity", style.replace(" ", ""))
    assert "is-readonly .alerta-pick-btn" not in style
    assert ".swatch-option" not in style


def test_colour_read_only_rules_use_only_shared_tokens():
    style = _style(TEMPLATE.read_text(encoding="utf-8"))
    rules = re.findall(r"(\.alerta-color-input-group:has\(\.alerta-color-hex\[readonly\]\)\{[^}]*\}|"
                       r"\.alerta-color-hex\[readonly\]\{[^}]*\})", style)
    assert len(rules) == 2
    assert "var(--field-readonly-bg)" in rules[0]
    assert "var(--text-secondary)" in rules[1]
    for rule in rules:
        assert not RAW_COLOUR.findall(rule), rule
        assert "opacity" not in rule


# ==========================================================================
# Browser behaviour
# ==========================================================================


cdp = pytest.importorskip("tests.cdp_browser_support")
BINARY = cdp.find_chromium()
browser_only = pytest.mark.skipif(BINARY is None, reason="no Chromium binary for the browser harness")


@pytest.fixture
def page(tmp_path):
    with isolated_versioned_app_env(tmp_path, "ui-c07.db") as env:
        token = uuid.uuid4().hex[:8]
        with main.app.app_context():
            conn = main.get_db_connection()
            uid = int(create_usuario_with_access_level(
                conn, f"UI-C07 {token}", f"ui-c07-{token}@example.invalid",
                main.hash_password("ui-c07"), "admin", "admin_total", credential_state="personal",
            ).lastrowid)
            from app.db_maintenance import ensure_admin_alertas_table

            ensure_admin_alertas_table(conn)
            conn.execute(
                "INSERT INTO admin_alertas (titulo, mensagem, bg_color, border_color, visivel)"
                " VALUES (?,?,?,?,1)",
                (TITLE, MESSAGE, "#fef3c7", "#f59e0b"),
            )
            conn.commit()
        client = env["client"]
        with client.session_transaction() as session:
            session.clear()
            session.update(user_id=uid, user_type="admin", user_name="UI-C07")
            stamp_auth_version(session, uid)
        session = cdp.BrowserSession(client, BINARY)
        try:
            session.goto("/admin/alertas")
            yield session
        finally:
            session.close()


def _open(session, mode: str) -> None:
    session.evaluate(
        "(() => { const row = document.querySelector('#alertas-list .impresso-card[data-alerta-id]');"
        " row.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));"
        f" document.querySelector('#pedido-actions-float [data-action=\"{mode}\"]').click(); return true; }})()"
    )
    session.wait_for("!document.getElementById('admin-alerta-modal').hidden")


STATE = """(() => {
  const $ = (id) => document.getElementById(id);
  const token = (() => { const d = document.createElement('div');
    d.style.background = 'var(--field-readonly-bg)'; document.body.appendChild(d);
    const c = getComputedStyle(d).backgroundColor; d.remove(); return c; })();
  const card = (el) => getComputedStyle(el.closest('.field-card')).backgroundColor;
  const visible = (el) => !!el && !el.hidden && getComputedStyle(el).display !== 'none';
  const swatches = Array.from(document.querySelectorAll('#alerta-bg-grid .palette-swatch:not([hidden])'));
  return JSON.stringify({
    token,
    readonlyClass: document.querySelector('#admin-alerta-modal .modal-card').classList.contains('is-readonly'),
    tituloRO: $('admin-alerta-titulo').readOnly, tituloAria: $('admin-alerta-titulo').getAttribute('aria-readonly'),
    mensagemRO: $('admin-alerta-mensagem').readOnly, mensagemAria: $('admin-alerta-mensagem').getAttribute('aria-readonly'),
    tituloCard: card($('admin-alerta-titulo')), mensagemCard: card($('admin-alerta-mensagem')),
    tituloBg: getComputedStyle($('admin-alerta-titulo')).backgroundColor,
    hexRO: $('admin-alerta-bg-hex').readOnly && $('admin-alerta-border-hex').readOnly,
    hexGroup: getComputedStyle($('admin-alerta-bg-hex').closest('.alerta-color-input-group')).backgroundColor,
    pickVisible: visible($('open-bg-picker')) || visible($('open-border-picker')),
    pickOpacity: getComputedStyle($('open-bg-picker')).opacity,
    swatchesDisabled: swatches.every((b) => b.disabled), swatchCount: swatches.length,
    saveVisible: visible($('admin-alerta-save')),
    action: $('admin-alerta-form').getAttribute('action'),
    bg: $('admin-alerta-bg').value, previewText: $('alerta-preview-text').textContent.trim(),
    previewBg: getComputedStyle($('alerta-preview')).backgroundColor,
  });
})()"""


def _state(session) -> dict:
    import json

    return json.loads(session.evaluate(STATE))


@browser_only
def test_ver_uses_the_shared_read_only_paint_and_cannot_mutate(page):
    _open(page, "view")
    state = _state(page)

    assert state["readonlyClass"]
    assert state["tituloRO"] and state["tituloAria"] == "true"
    assert state["mensagemRO"] and state["mensagemAria"] == "true"
    assert state["tituloCard"] == state["token"] == state["mensagemCard"]
    assert state["tituloBg"] in ("rgba(0, 0, 0, 0)", "transparent")
    assert state["hexRO"] and state["hexGroup"] == state["token"]
    assert not state["pickVisible"]
    assert state["swatchesDisabled"] and state["swatchCount"] >= 2
    assert not state["saveVisible"]
    assert state["action"] is None

    before = state["bg"]
    page.evaluate(
        "(() => { const s = Array.from(document.querySelectorAll('#alerta-bg-grid .palette-swatch:not([hidden])'))"
        ".find((b) => b.dataset.color !== document.getElementById('admin-alerta-bg').value);"
        " s.click(); document.getElementById('open-bg-picker').click(); return true; })()"
    )
    sent = len(page.requests)
    page.evaluate("document.getElementById('admin-alerta-form').requestSubmit(); true")
    page.pump(0.4)
    after = _state(page)
    assert after["bg"] == before
    assert [r for r in page.requests[sent:] if r[0] == "POST"] == []

    # Recipient preview: MESSAGE only, never the internal title.
    assert after["previewText"] == MESSAGE
    assert TITLE not in page.evaluate("document.getElementById('alerta-preview').textContent")


@browser_only
def test_editar_stays_fully_interactive(page):
    _open(page, "edit")
    state = _state(page)

    assert not state["readonlyClass"]
    assert not state["tituloRO"] and state["tituloAria"] is None
    assert not state["mensagemRO"] and state["mensagemAria"] is None
    assert state["tituloCard"] != state["token"]
    assert state["pickVisible"] and state["pickOpacity"] == "1"
    assert not state["swatchesDisabled"]
    assert state["saveVisible"]
    assert state["action"] and state["action"].endswith("/alertas/salvar")

    before = state["bg"]
    page.evaluate(
        "(() => { const s = Array.from(document.querySelectorAll('#alerta-bg-grid .palette-swatch:not([hidden])'))"
        ".find((b) => b.dataset.color !== document.getElementById('admin-alerta-bg').value);"
        " s.click(); const m = document.getElementById('admin-alerta-mensagem'); m.value = 'Nova mensagem';"
        " m.dispatchEvent(new Event('input')); return true; })()"
    )
    after = _state(page)
    assert after["bg"] != before
    assert after["previewBg"] != state["previewBg"]
    assert after["previewText"] == "Nova mensagem"


@browser_only
def test_editar_after_ver_restores_the_writable_target(page):
    _open(page, "view")
    page.evaluate("document.getElementById('admin-alerta-cancelar').click(); true")
    _open(page, "edit")
    state = _state(page)
    assert state["action"] and state["action"].endswith("/alertas/salvar")
    assert state["pickVisible"] and state["saveVisible"]
