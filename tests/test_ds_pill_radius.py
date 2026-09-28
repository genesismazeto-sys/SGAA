"""DS-PILL-RADIUS: semantic pills and badges share one 4px corner token.

Owner: ``--pill-radius`` (4px) in ``static/css/foundation/tokens.css`` -- its own
token, deliberately separate from the field/card ``--radius``. Consumers:

* shared: ``.badge`` and ``.badge.status-pill`` (modern-style.css) -- every
  status pill, the error-page status label (UI-C14) and plain count badges;
  the Cursos list badge in components/list-cards.css;
* page-local status-label families that restate the pill: Banco de dados
  ``.db-badge`` / ``.db-origin-pill`` / provider-head ``.db-badge``, Atividades
  filter-count badge and local ``.badge``, Requisições local ``.badge``,
  Importar atividades ``.status-chip``, Diagnóstico ``.diag-badge`` /
  ``.diag-chip`` / ``.diag-pill``, Mensagens ``.message-badge``.

Out of scope and guarded as unchanged: circles (status-pill dots, avatars, the
floating-bar selection counter ``.act-count``), switches, buttons, icon
buttons, the floating-bar buttons and the Requisições placeholder-insert chips
(``.presets-ph``, which are buttons). Padding, height, colours and text are not
touched by this item.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOKENS = ROOT / "static" / "css" / "foundation" / "tokens.css"
MODERN = ROOT / "static" / "css" / "modern-style.css"

# Fully-rounded corners that legitimately stay round: each is a circle or a
# control, never a semantic label. (owner, selector) -> reason.
ROUND_ALLOWED = {
    ("static/css/modern-style.css", ".user-avatar"): "avatar circle",
    ("static/css/modern-style.css", "#avatar-box"): "avatar circle",
    ("static/css/modern-style.css", ".badge.status-pill::before"): "status dot",
    ("templates/admin_banco_dados.html", ".db-provider-head .db-badge::before"): "status dot",
    ("templates/admin_requisicoes.html", ".pedido-actions-float .act-count"): "selection counter circle",
    ("templates/admin_requisicoes.html", ".presets-ph"): "placeholder-insert button",
}

# Every rule that consumes the pill token, by owner. A new consumer is a
# deliberate addition to this list; a control consuming it is a defect.
PILL_CONSUMERS = {
    "static/css/modern-style.css": {".badge", ".badge.status-pill"},
    "static/css/components/list-cards.css": {".imp-cursos .badge.status-badge"},
    "templates/admin_atividades.html": {".filter-count-badge", ".badge"},
    "templates/admin_banco_dados.html": {".db-badge", ".db-origin-pill", ".db-provider-head .db-badge"},
    "templates/admin_diagnostico_atividades_versionadas_view.html": {".diag-badge", ".diag-chip", ".diag-pill"},
    "templates/admin_importar_atividades.html": {".status-chip"},
    "templates/admin_mensagens.html": {".message-badge"},
    "templates/admin_requisicoes.html": {".badge"},
}


def _stylesheets():
    for path in sorted((ROOT / "static" / "css").rglob("*.css")):
        yield path.relative_to(ROOT).as_posix(), path.read_text(encoding="utf-8")
    for path in sorted((ROOT / "templates").rglob("*.html")):
        text = path.read_text(encoding="utf-8")
        blocks = re.findall(r"<style[^>]*>(.*?)</style>", text, re.S | re.I)
        if blocks:
            yield path.relative_to(ROOT).as_posix(), "\n".join(blocks)


def _radius_rules():
    """(owner, selector, border-radius value) for every rule that sets one."""
    for owner, css in _stylesheets():
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        for selector, body in re.findall(r"([^{};]+)\{([^{}]*)\}", css):
            match = re.search(r"border-radius\s*:\s*([^;]+)", body)
            if match:
                yield owner, " ".join(selector.split()), match.group(1).strip()


def _rule(css: str, selector: str) -> str:
    match = re.search(r"(?m)^" + re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert match, selector
    return match.group(1)


def _radius(body: str) -> str:
    return re.search(r"border-radius\s*:\s*([^;]+)", body).group(1).strip()


# ------------------------------------------------------------------ static


def test_one_pill_radius_token_of_4px():
    tokens = TOKENS.read_text(encoding="utf-8")
    assert re.findall(r"--pill-radius\s*:\s*([^;]+);", tokens) == ["4px"]
    # One owner: no badge/status/chip/pill-corner synonym beside it.
    assert re.findall(r"--[a-z-]*radius[a-z-]*\s*:", tokens) == ["--radius:", "--pill-radius:"]


def test_shared_pill_owners_consume_the_token():
    css = MODERN.read_text(encoding="utf-8")
    assert _radius(_rule(css, ".badge")) == "var(--pill-radius)"
    assert _radius(_rule(css, ".badge.status-pill")) == "var(--pill-radius)"
    list_cards = (ROOT / "static/css/components/list-cards.css").read_text(encoding="utf-8")
    assert "border-radius:var(--pill-radius)" in _rule(list_cards, ".imp-cursos .badge.status-badge")


def test_no_stylesheet_restores_a_fully_rounded_pill():
    offenders = [
        (owner, selector, value)
        for owner, selector, value in _radius_rules()
        if re.search(r"\b\d{3,}px|\b50%", value) and (owner, selector) not in ROUND_ALLOWED
    ]
    assert offenders == [], offenders


def test_every_badge_or_status_pill_rule_uses_the_pill_token():
    """A page-local ``.badge`` / ``.status-pill`` restatement cannot pick its own corner."""
    offenders = []
    for owner, selector, value in _radius_rules():
        for part in selector.split(","):
            last = part.strip().split(" ")[-1]
            if "::" in last:
                continue
            if re.search(r"\.badge(?![\w-])|\.status-pill(?![\w-])", last) and value != "var(--pill-radius)":
                offenders.append((owner, part.strip(), value))
    assert offenders == [], offenders


def test_pill_token_is_consumed_only_by_the_declared_pill_family():
    consumers: dict[str, set[str]] = {}
    for owner, selector, value in _radius_rules():
        if "var(--pill-radius)" in value:
            consumers.setdefault(owner, set()).add(selector)
    assert consumers == PILL_CONSUMERS
    for owner, selectors in consumers.items():
        for selector in selectors:
            assert not re.search(r"btn|switch|toggle|avatar|swatch|::", selector), (owner, selector)


def test_controls_and_circles_keep_their_own_corners():
    css = MODERN.read_text(encoding="utf-8")
    assert "border-radius:var(--radius)" in _rule(css, ".btn").replace(" ", "")
    assert _radius(_rule(css, ".user-avatar")) == "50%"
    assert _radius(_rule(css, "#avatar-box")) == "50%"
    assert _radius(_rule(css, ".badge.status-pill::before")) == "50%"
    form = (ROOT / "static/css/components/form.css").read_text(encoding="utf-8")
    assert _radius(_rule(form, ".toggle-switch-slider")) == "3px"
    floating = (ROOT / "static/css/components/actions-float.css").read_text(encoding="utf-8")
    assert "border-radius: 6px" in _rule(floating, "#pedido-actions-float .act-btn")


# ----------------------------------------------------------------- browser

cdp = pytest.importorskip("tests.cdp_browser_support")
BINARY = cdp.find_chromium()

# Appended to each page so the page's own cascade (shared + page-local rules)
# is measured on every family, whether or not the seeded data renders one.
_PROBE = """
(() => {
  const host = document.createElement('div');
  host.id = 'ds-pill-probe';
  host.innerHTML = `
    <span data-probe="badge" class="badge">3</span>
    <span data-probe="status-pill" class="badge status-pill status-positive">Ativo</span>
    <span data-probe="status-badge" class="badge status-badge status-pill status-neutral" data-status-badge>Ativo</span>
    <button data-probe="btn" class="btn" type="button">Salvar</button>
    <label data-probe="switch" class="toggle-switch"><input type="checkbox"><span class="toggle-switch-slider"></span></label>`;
  document.body.appendChild(host);
  const radius = (el, pseudo) => getComputedStyle(el, pseudo || null).borderTopLeftRadius;
  const out = {};
  host.querySelectorAll('[data-probe]').forEach(el => { out[el.dataset.probe] = radius(el); });
  out['switch-slider'] = radius(host.querySelector('.toggle-switch-slider'));
  out['form-css'] = !!document.querySelector('link[href*="components/form.css"]');
  out['status-dot'] = radius(host.querySelector('.status-pill'), '::before');
  const real = {};
  document.querySelectorAll(%s).forEach(el => {
    if (host.contains(el)) return;
    const key = el.className.trim().split(/\\s+/)[0];
    (real[key] = real[key] || []).push(radius(el));
  });
  out.real = real;
  return JSON.stringify(out);
})()
"""

_REAL = ".badge, .status-pill, .db-badge, .db-origin-pill, .status-chip, .filter-count-badge, .request-error-status"


@pytest.mark.skipif(BINARY is None, reason="no Chromium binary for the browser harness")
def test_representative_pills_resolve_to_4px_and_controls_do_not(tmp_path):
    import main
    from tests.session_support import existing_admin_user_id, stamp_auth_version
    from tests.versioned_test_support import isolated_versioned_app_env

    with isolated_versioned_app_env(tmp_path, "ds-pill-radius.db") as env:
        client = env["client"]
        with main.app.app_context():
            uid = existing_admin_user_id()
        with client.session_transaction() as session:
            session.clear()
            session.update(user_id=uid, user_type="admin", user_name="DS pill probe")
            stamp_auth_version(session, uid)

        session = cdp.BrowserSession(client, BINARY)
        try:
            measured = {}
            for path in (
                "/admin/banco-dados",
                "/admin/requisicoes",
                "/admin/atividades",
                "/admin/turmas",
                "/admin/pagina-inexistente-ds-pill",
            ):
                session.goto(path)
                measured[path] = json.loads(session.evaluate(_PROBE % json.dumps(_REAL)))
        finally:
            session.close()

    for path, values in measured.items():
        assert values["badge"] == "4px", (path, values)
        assert values["status-pill"] == "4px", (path, values)
        assert values["status-badge"] == "4px", (path, values)
        assert values["status-dot"] == "50%", (path, values)
        assert values["btn"] == "4px", (path, values)  # --radius, unchanged
        if values["form-css"]:  # the switch owner is only loaded where forms are
            assert values["switch-slider"] == "3px", (path, values)
        for family, radii in values["real"].items():
            assert set(radii) == {"4px"}, (path, family, radii)

    # Real, rendered semantic labels were measured, not only the probes.
    banco = measured["/admin/banco-dados"]["real"]
    assert banco.get("badge") and banco.get("db-badge"), banco
    assert measured["/admin/atividades"]["real"].get("filter-count-badge"), measured["/admin/atividades"]
    assert measured["/admin/pagina-inexistente-ds-pill"]["real"].get("badge"), measured
    assert sum(values["form-css"] for values in measured.values()) >= 3, measured
