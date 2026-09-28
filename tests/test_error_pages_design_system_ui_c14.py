"""UI-C14: the SGAA error pages share one Design System owner.

Before: 400 and 500 were standalone pages with page-local ``<style>`` clones
of the card, badge, note and button (raw hex colours); 404 extended the admin
chrome and linked every user to the admin dashboard; 403 had no page at all,
so ``abort(403)`` fell through to Werkzeug's bare English page.

After: ``templates/error_page.html`` is the single owner and each code only
fills its blocks. Every surface is an existing DS owner -- the public-page
shell (``.login-page`` / ``.login-card``), the semantic status pill, the
shared info notice, the shared buttons -- and the only local CSS arranges
them without any colour of its own.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from flask import abort, render_template, session
from werkzeug.routing import Rule

import main
from tests.canonical_matrix_test_support import login_admin
from tests.versioned_test_support import isolated_versioned_app_env

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = PROJECT_ROOT / "templates"
SHARED = TEMPLATES / "error_page.html"
CODES = ("400", "403", "404", "500")
CSRF_MESSAGE = (
    "A página ficou desatualizada ou sua sessão expirou. "
    "Volte para a tela anterior, recarregue a página e tente novamente."
)
EXPECTED = {
    "400": "Não foi possível concluir a ação",
    "403": "Acesso negado",
    "404": "Página não encontrada",
    "500": "Erro interno",
}
RAW_COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(")
LAYOUT_ONLY_PROPERTIES = {"margin-bottom", "text-align", "display", "flex-wrap", "justify-content", "gap"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _probe(monkeypatch, path, view):
    endpoint = "ui_c14_probe_" + path.strip("/").replace("-", "_")
    rule = Rule(path, endpoint=endpoint, methods={"GET"})
    main.app.url_map.add(rule)
    main.app.view_functions[endpoint] = view

    def cleanup():
        main.app.view_functions.pop(endpoint, None)
        main.app.url_map._rules.remove(rule)
        main.app.url_map._rules_by_endpoint.pop(endpoint, None)
        main.app.url_map.update()

    return cleanup


def _assert_shared_shell(html: str, code: str) -> None:
    assert '<main class="login-page request-error-page"' in html
    assert 'class="login-card request-error-card"' in html
    assert f'<span class="badge status-pill status-negative request-error-status">Erro {code}</span>' in html
    assert f'class="login-title request-error-title">{EXPECTED[code]}</h1>' in html
    assert 'class="login-subtitle request-error-copy"' in html
    assert "/static/vendor/lucide.min.js" in html


def _buttons(html: str) -> list[str]:
    return re.findall(r'<a class="btn[^"]*"[^>]*>.*?</a>', html, re.S)


@pytest.fixture
def csrf_env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "ui-c14-csrf.db") as env:
        login_admin(env["client"])
        original = {
            key: main.app.config.get(key)
            for key in ("WTF_CSRF_ENABLED", "WTF_CSRF_CHECK_DEFAULT")
        }
        main.app.config.update(WTF_CSRF_ENABLED=True, WTF_CSRF_CHECK_DEFAULT=True)
        try:
            yield env
        finally:
            main.app.config.update(original)


# ==========================================================================
# Every code renders through its real handler, on the shared owner
# ==========================================================================


def test_400_is_the_csrf_handler_unchanged(csrf_env):
    response = csrf_env["client"].post(
        "/admin/adicionar_matriz",
        data={"nome": "sem token"},
        headers={"Referer": "http://localhost/admin/matrizes"},
    )
    html = response.get_data(as_text=True)

    assert response.status_code == 400
    _assert_shared_shell(html, "400")
    assert CSRF_MESSAGE in html
    assert "novo token de segurança antes de reenviar" in html
    assert '<div class="flash flash-info request-error-note" role="note">' in html
    from flask_wtf.csrf import CSRFError

    handlers = {
        exc_cls: fn
        for spec in main.app.error_handler_spec.values()
        for by_code in (spec or {}).values()
        for exc_cls, fn in (by_code or {}).items()
    }
    assert handlers[CSRFError].__module__ == "app"
    assert handlers[CSRFError].__name__ == "_handle_csrf_error"


def test_403_renders_the_shared_page_instead_of_werkzeugs(monkeypatch):
    cleanup = _probe(monkeypatch, "/ui-c14-forbidden-probe", lambda: abort(403))
    try:
        response = main.app.test_client().get("/ui-c14-forbidden-probe")
    finally:
        cleanup()
    html = response.get_data(as_text=True)

    assert response.status_code == 403
    _assert_shared_shell(html, "403")
    assert "Você não tem permissão para acessar este conteúdo." in html
    assert "Forbidden" not in html


def test_404_renders_the_shared_page():
    response = main.app.test_client().get("/ui-c14-no-such-page")
    html = response.get_data(as_text=True)

    assert response.status_code == 404
    _assert_shared_shell(html, "404")
    assert "A URL acessada não existe. Verifique o endereço ou volte para a área inicial." in html


def test_500_renders_the_shared_page(monkeypatch):
    monkeypatch.setitem(main.app.config, "PROPAGATE_EXCEPTIONS", False)
    monkeypatch.setitem(main.app.config, "TESTING", False)

    def boom():
        raise RuntimeError("ui-c14 500 probe")

    cleanup = _probe(monkeypatch, "/ui-c14-internal-probe", boom)
    try:
        response = main.app.test_client().get("/ui-c14-internal-probe")
    finally:
        cleanup()
    html = response.get_data(as_text=True)

    assert response.status_code == 500
    _assert_shared_shell(html, "500")
    assert "Ocorreu um erro interno no servidor. Tente novamente em instantes." in html
    assert "ui-c14 500 probe" not in html


# ==========================================================================
# No page-local clones, no raw colours
# ==========================================================================


def test_code_templates_only_fill_the_shared_owner():
    for code in CODES:
        text = (TEMPLATES / f"{code}.html").read_text(encoding="utf-8")
        assert text.startswith('{% extends "error_page.html" %}'), code
        assert "<style" not in text and "style=" not in text, code
        assert "<html" not in text and "<link" not in text, code


def test_shared_owner_carries_no_colour_and_no_component_clone():
    text = SHARED.read_text(encoding="utf-8")
    styles = re.findall(r"<style[^>]*>(.*?)</style>", text, re.S)
    assert len(styles) == 1
    assert RAW_COLOUR.findall(styles[0]) == []
    assert "style=" not in text
    declared = set(re.findall(r"([a-z-]+)\s*:", styles[0]))
    assert declared <= LAYOUT_ONLY_PROPERTIES, declared - LAYOUT_ONLY_PROPERTIES
    for retired in ("request-error-badge", "request-error-shell", "request-error-track", "a.btn", ".card {"):
        assert retired not in text, retired


@pytest.mark.parametrize("code", CODES)
def test_actions_use_the_shared_button_contract(code):
    with main.app.test_request_context("/x", headers={"Referer": "/admin/matrizes"}):
        html = render_template(f"{code}.html", mensagem=None)
    buttons = _buttons(html)
    assert buttons, code
    for button in buttons:
        assert re.match(r'<a class="btn( primary)?" href="[^"]+">', button), button
        assert '<i class="lucide" data-lucide="' in button
        assert '<span class="btn-label">' in button
    assert 'class="btn primary"' in buttons[0]


# ==========================================================================
# Navigation
# ==========================================================================


def test_400_keeps_back_as_primary_and_home_as_secondary():
    with main.app.test_request_context("/x", headers={"Referer": "/admin/matrizes"}):
        html = render_template("400.html", mensagem="m")
    back, home = _buttons(html)
    assert 'class="btn primary" href="/admin/matrizes"' in back and "Abrir tela anterior" in back
    assert 'class="btn" href="/"' in home and "Ir para o início" in home


@pytest.mark.parametrize(
    "user_type, expected",
    [(None, "/"), ("admin", "/admin/dashboard"), ("aluno", "/aluno/dashboard")],
)
@pytest.mark.parametrize("code", CODES)
def test_home_follows_the_signed_in_user(code, user_type, expected):
    """404 used to send every user -- students included -- to the admin dashboard."""
    with main.app.test_request_context("/x"):
        if user_type:
            session["user_type"] = user_type
        html = render_template(f"{code}.html", mensagem=None)
    home = [b for b in _buttons(html) if "Ir para o início" in b]
    assert len(home) == 1
    assert f'href="{expected}"' in home[0]
    assert "admin_dashboard" not in html
