"""Design System: the shared select picker (UI batch 4, item 3).

components/select.css owns how every single-choice <select> opens. Where the
customizable select exists, the select opens a CSS picker anchored to its own
field (the whole .field-card when it is the card's only control, otherwise
the select itself), at least as wide as that field, wrapping long names,
flipping above when there is no room below, with the SGAA radius, border,
shadow and soft blue selection. The closed control renders exactly as the
native fallback does. Without the feature the @supports block is skipped and
every select keeps the browser popup.

Exceptions: `multiple`, `size` list boxes, `[hidden]` data carriers and
`data-select-native` (the turma status arrow, whose badge is script-owned, and
the Progress title select, whose content-sized width would follow the choice).
`.select--plain` keeps the closed look of a page that draws no chevron.
"""
from __future__ import annotations

import base64
import io
import json
import re
from pathlib import Path

import pytest

import main
from tests.canonical_request_test_support import login_admin, student_identity
from tests.cdp_browser_support import BrowserSession, find_chromium
from tests.session_support import stamp_auth_version
from tests.versioned_test_support import isolated_versioned_app_env
from tools import ds_css as ds

ROOT = Path(__file__).resolve().parents[1]
SELECT_CSS = ROOT / "static" / "css" / "components" / "select.css"
CHROMIUM = find_chromium()
browser = pytest.mark.skipif(CHROMIUM is None, reason="no headless Chromium available")
LONG_NAME = (
    "Participação como ouvinte em congressos, seminários, simpósios, jornadas, fóruns, "
    "encontros e conferências de caráter acadêmico, científico ou profissional"
)


@pytest.fixture()
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "ds-select.db") as value:
        yield value


def _sql(query, params=()):
    with main.app.app_context():
        conn = main.get_db_connection()
        rows = conn.execute(query, params).fetchall()
        conn.commit()
        return rows


def _as_student(client):
    identity = student_identity()
    with client.session_transaction() as session:
        session.clear()
        session.update(user_id=identity["usuario_id"], user_type="aluno", user_name="Aluno")
        stamp_auth_version(session)
    return identity


def _templates():
    return sorted((ROOT / "templates").rglob("*.html"))


# ------------------------------------------------------------------ static


def test_select_css_loads_everywhere_after_the_form_composition():
    macro = (ROOT / "templates" / "components" / "design_system_css.html").read_text(encoding="utf-8")
    sheets = re.findall(r"'(css/[\w/.-]+\.css)'", macro)
    assert sheets.index("css/components/select.css") > sheets.index("css/components/form.css")
    assert sheets[-1] == "css/components/select.css"


def test_both_shells_serve_select_css_under_one_bumped_version(env):
    client = env["client"]
    login_admin(client)
    admin = client.get("/admin/dashboard").get_data(as_text=True)
    _as_student(client)
    aluno = client.get("/aluno/dashboard").get_data(as_text=True)
    for html in (admin, aluno):
        versions = set(re.findall(r'/static/css/components/select\.css\?v=([\w.-]+)', html))
        assert versions and versions != {"20261016-ui-batch3-v1"}, versions
        assert set(re.findall(r'/static/css/[\w/.-]+\.css\?v=([\w.-]+)', html)) == versions


def test_the_picker_has_one_owner():
    """No page restyles ::picker(select) or switches appearance on its own."""
    for path in _templates():
        text = path.read_text(encoding="utf-8")
        assert "::picker" not in text and "base-select" not in text, path.name
        assert not re.search(r"appearance\s*:\s*none", text), path.name  # .select--plain replaced them
    for path in (ROOT / "static" / "css").rglob("*.css"):
        if path != SELECT_CSS:
            assert "::picker" not in path.read_text(encoding="utf-8"), path.name


def test_eligibility_excludes_list_boxes_data_carriers_and_script_owned_controls():
    css = SELECT_CSS.read_text(encoding="utf-8")
    eligible = re.findall(r"select:not\(([^)]*)\)", css)
    assert eligible and set(eligible) == {"[multiple], [size], [hidden], [data-select-native]"}
    status_arrows = [m for path in _templates()
                     for m in re.findall(r"<select[^>]*data-status-arrow[^>]*>", path.read_text(encoding="utf-8"))]
    assert len(status_arrows) == 3 and all("data-select-native" in tag for tag in status_arrows)
    progress = (ROOT / "templates" / "aluno_progresso.html").read_text(encoding="utf-8")
    assert re.search(r'<select id="progresso-tipo"[^>]*data-select-native', progress)
    native = sorted({path.name for path in _templates() if "data-select-native" in path.read_text(encoding="utf-8")})
    assert native == ["admin_adicionar_turma.html", "admin_editar_turma.html", "aluno_progresso.html"]
    plain = sorted(path.name for path in _templates() if "select--plain" in path.read_text(encoding="utf-8"))
    assert plain == ["admin_detalhes_turma.html", "admin_reportes.html", "aluno_reportar.html"]


def _select_padding_declarations():
    sources = [(path, path.read_text(encoding="utf-8")) for path in (ROOT / "static" / "css").rglob("*.css")]
    for path in _templates():
        text = path.read_text(encoding="utf-8")
        sources += [(path, block) for block in re.findall(r"<style[^>]*>(.*?)</style>", text, re.S | re.I)]
    for path, css in sources:
        for decl in ds.parse_declarations(css, path.name):
            if decl.prop in ("padding", "padding-right", "padding-inline-end"):
                yield path.name, decl


def test_every_select_family_that_sets_padding_reserves_the_arrow_room():
    """The 16px the native menulist keeps before its chevron is a token each
    family adds to its own end padding, so long labels clip exactly where the
    native control clips them, in both modes."""
    families = {}
    for name, decl in _select_padding_declarations():
        selector = decl.selector
        targets_select = re.search(r"(^|[\s>+~(])select(?![\w-])", selector) or ".db-select" in selector
        if selector == ".field-card .control" or (targets_select and "option" not in selector and "::" not in selector):
            families[(name, selector)] = decl.value
    # Native by design: the status arrow and the Progress title select (data-select-native),
    # and the plain turma switcher, which draws its own chevron.
    exempt = {("turma-alunos.css", ".status-arrow"), ("modern-style.css", ".progresso-type-select"),
              ("admin_detalhes_turma.html", ".turma-select-shell select")}
    missing = {key: value for key, value in families.items()
               if "--select-arrow-room" not in value and key not in exempt}
    assert not missing, missing
    # The DS primitives and every page family were found.
    for expected in (".field-card .control", ".app-main .toolbar .filters select",
                     ".access-form-field select", ".access-scope-card select", ".db-select",
                     ".diag-field select", ".reporte-modal-status-form select", ".db-field select", ".cfg-field select"):
        assert any(selector == expected for _, selector in families), expected


# ----------------------------------------------------------------- browser

PAGES_ADMIN = ["/admin/acesso", "/admin/adicionar_atividade", "/admin/adicionar_turma", "/admin/banco-dados",
               "/admin/catalogo-versoes/{base}", "/admin/catalogo-versoes/{base}/versoes/{versao}/editar",
               "/admin/diagnostico/atividades-versionadas/view", "/admin/editar_turma/{turma}", "/admin/reportes",
               "/admin/requisicoes", "/admin/requisicoes/nova", "/admin/turma/{turma}", "/admin/turmas"]
PAGES_ALUNO = ["/aluno/nova-requisicao", "/aluno/progresso", "/aluno/reportar"]

# Reveal every modal holding a select, as the visual catalogue does (`hidden`).
REVEAL = """(() => { for (const s of document.querySelectorAll('select')) { const m = s.closest('.modal-overlay[hidden], [id$=-modal][hidden]');
  if (m) m.removeAttribute('hidden'); } return true; })()"""
STATES = """JSON.stringify(Array.from(document.querySelectorAll('select')).map(s => { const cs = getComputedStyle(s); const b = s.getBoundingClientRect();
  return {id: s.id || s.name || s.className, appearance: cs.appearance, display: cs.display, hidden: s.hidden,
          optOut: s.hasAttribute('data-select-native'), rendered: b.width > 0 && b.height > 0, rect: [b.left, b.top, b.width, b.height]}; }))"""


def _ids():
    return {"turma": _sql("SELECT id FROM turmas ORDER BY id LIMIT 1")[0][0],
            "base": _sql("SELECT atividade_base_id FROM atividade_versao ORDER BY id LIMIT 1")[0][0],
            "versao": _sql("SELECT id FROM atividade_versao ORDER BY id LIMIT 1")[0][0]}


def _session(client, width=1440, height=900):
    session = BrowserSession(client, CHROMIUM)
    session.call("Emulation.setDeviceMetricsOverride",
                 {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False})
    return session


def _neutralize(session):
    # A browser without the customizable select: the @supports block is skipped.
    session.response_rewrites["/static/css/components/select.css"] = lambda body: body.replace(
        b"@supports (appearance: base-select)", b"@supports (appearance: sgaa-unsupported-probe)")


def _walk(client, pages, visit):
    ids = _ids()
    for role, paths in (("admin", PAGES_ADMIN), ("aluno", PAGES_ALUNO)):
        (login_admin if role == "admin" else _as_student)(client)
        for path in paths:
            if path in pages:
                visit(path.format(**ids))


@browser
def test_every_rendered_select_is_enhanced_except_the_documented_exceptions(env):
    client = env["client"]
    session = _session(client)
    seen = []
    try:
        def visit(path):
            session.goto(path)
            session.evaluate(REVEAL)
            for state in json.loads(session.evaluate(STATES)):
                seen.append((path, state))
        _walk(client, PAGES_ADMIN + PAGES_ALUNO, visit)
    finally:
        session.close()
    rendered = [(p, s) for p, s in seen if s["rendered"]]
    assert len(rendered) >= 60
    for path, state in seen:
        if state["hidden"]:
            # Data carriers stay out of the layout (the UA [hidden] rule is not overridden).
            assert state["display"] == "none" and not state["rendered"], (path, state)
        elif state["optOut"]:
            assert state["appearance"] != "base-select", (path, state)
        elif state["rendered"]:
            assert state["appearance"] == "base-select", (path, state)
    assert any(state["optOut"] and state["rendered"] for _, state in seen)  # the status arrow was covered
    assert any(state["hidden"] for _, state in seen)  # and the hidden substitution lists


def _closed(client, path, mode, width):
    session = _session(client, width)
    if mode == "native":
        _neutralize(session)
    try:
        session.goto(path)
        session.evaluate(REVEAL)
        session.pump(0.3)
        session.evaluate("document.activeElement && document.activeElement.blur(); true")
        states = [s for s in json.loads(session.evaluate(STATES)) if s["rendered"]]
        size = json.loads(session.evaluate(
            "JSON.stringify([Math.max(document.documentElement.scrollWidth, innerWidth), Math.max(document.documentElement.scrollHeight, innerHeight)])"))
        shot = session.call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True,
                                                       "clip": {"x": 0, "y": 0, "width": size[0], "height": size[1], "scale": 1}})
        scroll = session.evaluate("scrollY")
    finally:
        session.close()
    from PIL import Image
    image = Image.open(io.BytesIO(base64.b64decode(shot["data"]))).convert("L")
    crops = []
    for state in states:
        left, top, width_, height = state["rect"]
        crops.append(image.crop((int(left) - 2, int(top + scroll) - 2, int(left + width_) + 2, int(top + scroll + height) + 2)))
    return states, crops


@browser
@pytest.mark.parametrize("width", [1440, 1280, 768, 640])
def test_closed_selects_render_like_the_native_fallback(env, width):
    """Same boxes, same label position and clip, same chevron: at most a few
    anti-aliasing pixels of the chevron differ (the CSS mask vs the painted
    native arrow)."""
    from PIL import ImageChops
    client = env["client"]
    pages = ["/admin/acesso", "/admin/adicionar_atividade", "/admin/adicionar_turma", "/admin/banco-dados", "/admin/turmas",
             "/admin/catalogo-versoes/{base}/versoes/{versao}/editar", "/admin/turma/{turma}",
             "/aluno/nova-requisicao", "/aluno/progresso", "/aluno/reportar"]
    compared = 0

    def visit(path):
        nonlocal compared
        enhanced, enhanced_crops = _closed(client, path, "enhanced", width)
        native, native_crops = _closed(client, path, "native", width)
        assert [s["id"] for s in enhanced] == [s["id"] for s in native], path
        for e, n, ce, cn in zip(enhanced, native, enhanced_crops, native_crops):
            assert e["appearance"] != n["appearance"] or e["optOut"], (path, e, n)
            assert all(abs(a - b) < 0.01 for a, b in zip(e["rect"], n["rect"])), (path, e, n)
            differing = sum(1 for value in ImageChops.difference(ce, cn).get_flattened_data() if value > 24)
            assert differing <= 4, (path, e["id"], differing)
            compared += 1
    _walk(client, pages, visit)
    assert compared >= 30


PICKER = """JSON.stringify((() => {
  const s = document.querySelector(%s);
  const card = s.closest('.field-card');
  const single = !!card && s.parentElement === card && card.querySelectorAll(':scope > .control').length === 1;
  const a = (single ? card : s).getBoundingClientRect(), sr = s.getBoundingClientRect();
  const hit = (x, y) => { const e = document.elementFromPoint(x, y); return !!e && (e === s || s.contains(e)); };
  const cx = sr.left + Math.min(sr.width / 2, 30);
  const below = hit(cx, a.bottom + 10), above = hit(cx, a.top - 10);
  let t = null, b = null;
  if (below) { for (let y = Math.ceil(a.bottom) + 1; y < innerHeight; y++) { if (hit(cx, y)) { if (t === null) t = y; b = y + 1; } else if (t !== null) break; } }
  if (above) { for (let y = Math.floor(a.top) - 1; y >= 0; y--) { if (hit(cx, y)) { if (b === null) b = y + 1; t = y; } else if (b !== null) break; } }
  let l = null, r = null;
  if (t !== null) { const my = (t + b) / 2; for (let x = 0; x < innerWidth; x++) if (hit(x, my)) { if (l === null) l = x; r = x + 1; } }
  const shown = Array.from(s.options).filter(o => getComputedStyle(o).display !== 'none').map(o => o.getBoundingClientRect());
  return {open: s.matches(':open'), single, value: s.value, picker: t === null ? null : {l, r, t, b},
          anchor: {l: a.left, r: a.right, t: a.top, b: a.bottom}, vw: innerWidth, vh: innerHeight,
          optionsInside: r !== null && shown.filter(o => o.width > 0).every(o => o.left >= l - 0.5 && o.right <= r + 0.5),
          openCount: document.querySelectorAll('select:open').length};
})())"""


def _key(session, key, code, vk):
    session.call("Input.dispatchKeyEvent", {"type": "rawKeyDown", "key": key, "code": code, "windowsVirtualKeyCode": vk})
    session.call("Input.dispatchKeyEvent", {"type": "keyUp", "key": key, "code": code, "windowsVirtualKeyCode": vk})
    session.pump(0.25)


def _open(session, selector):
    session.evaluate(f"document.querySelector({json.dumps(selector)}).scrollIntoView({{block: 'center'}}); true")
    session.pump(0.2)
    session.click(selector)
    session.pump(0.35)
    return json.loads(session.evaluate(PICKER % json.dumps(selector)))


def _assert_anchored(state, single):
    picker, anchor = state["picker"], state["anchor"]
    assert state["open"] and picker is not None and state["single"] is single, state
    assert state["openCount"] == 1, state
    assert abs(picker["l"] - anchor["l"]) <= 1, state  # aligned with its own field
    if single:
        assert abs(picker["r"] - anchor["r"]) <= 1, state  # exactly as wide as the card
    else:
        assert picker["r"] >= anchor["r"] - 1, state  # at least as wide as the select
    if picker["t"] >= anchor["b"] - 1:
        assert 0 <= picker["t"] - anchor["b"] <= 8, state
    else:
        assert 0 <= anchor["t"] - picker["b"] <= 8, state
    assert picker["l"] >= 0 and picker["r"] <= state["vw"] and picker["t"] >= 0 and picker["b"] <= state["vh"], state
    assert state["optionsInside"], state


@browser
@pytest.mark.parametrize("width", [1440, 1366, 1280, 768, 640])
def test_each_picker_opens_against_its_own_field_one_at_a_time(env, width):
    client = env["client"]
    login_admin(client)
    session = _session(client, width)
    try:
        # Two split cards side by side: each select opens against itself, never the card or its neighbour.
        session.goto("/admin/adicionar_atividade")
        for selector in ("#tipo_limit_card", "#ch_por_evento_mode", "#tipo_atividade_sel"):
            state = _open(session, selector)
            _assert_anchored(state, single=selector == "#tipo_atividade_sel")
            _key(session, "Escape", "Escape", 27)
            assert json.loads(session.evaluate(PICKER % json.dumps(selector)))["open"] is False
        # Never two lists at once: a click outside an open picker light-dismisses it
        # (or, where the open list covers the neighbour, lands in the list); either
        # way the neighbour then opens against its own select.
        assert _open(session, "#tipo_limit_card")["open"]
        session.click("#ch_por_evento_mode")
        session.pump(0.3)
        assert session.evaluate("document.querySelectorAll('select:open').length") <= 1
        if not session.evaluate("document.querySelector('#ch_por_evento_mode').matches(':open')"):
            session.click("#ch_por_evento_mode")
            session.pump(0.35)
        _assert_anchored(json.loads(session.evaluate(PICKER % json.dumps("#ch_por_evento_mode"))), single=False)
        _key(session, "Escape", "Escape", 27)

        # Inside a modal: on top of it, aligned with its own bordered select.
        session.goto("/admin/acesso")
        session.pump(0.4)  # let the page script initialise before revealing its modal
        session.evaluate("document.getElementById('access-modal').removeAttribute('hidden'); true")
        session.pump(0.3)
        for selector in ("#access-level", "select[name=scope_alertas]"):
            _assert_anchored(_open(session, selector), single=False)
            _key(session, "Escape", "Escape", 27)
    finally:
        session.close()


@browser
@pytest.mark.parametrize("width,height", [(1440, 460), (640, 460)])
def test_picker_flips_above_when_there_is_no_room_below(env, width, height):
    client = env["client"]
    _as_student(client)
    session = _session(client, width, height)
    try:
        session.goto("/aluno/nova-requisicao")
        session.evaluate(
            "(() => { const t = document.getElementById('tipo_atividade_select'); t.value = 'Acadêmica Complementar';"
            " t.dispatchEvent(new Event('change')); const n = document.getElementById('grupo_num'); n.value = '1';"
            " n.dispatchEvent(new Event('change')); return true; })()")
        session.evaluate("window.scrollTo(0, document.body.scrollHeight); true")
        session.evaluate("document.getElementById('atividade_versao_id_select').scrollIntoView({block: 'end'}); true")
        session.pump(0.2)
        session.click("#atividade_versao_id_select")
        session.pump(0.35)
        state = json.loads(session.evaluate(PICKER % json.dumps("#atividade_versao_id_select")))
        assert state["picker"]["b"] <= state["anchor"]["t"] + 1, state  # opened above the field
        _assert_anchored(state, single=True)
    finally:
        session.close()


@browser
def test_modal_choice_by_mouse_updates_the_value_and_fires_change(env):
    client = env["client"]
    login_admin(client)
    session = _session(client)
    try:
        session.goto("/admin/turmas")
        session.evaluate("document.getElementById('importar-turmas-modal').removeAttribute('hidden');"
                         " window.__changes = 0; document.getElementById('on_conflict').addEventListener('change', () => window.__changes++); true")
        _assert_anchored(_open(session, "#on_conflict"), single=True)
        target = session.evaluate("Array.from(document.getElementById('on_conflict').options).find(o => !o.selected).value")
        session.click(f'#on_conflict option[value="{target}"]')
        session.pump(0.3)
        state = json.loads(session.evaluate(PICKER % json.dumps("#on_conflict")))
        assert state["open"] is False and state["value"] == target, state
        assert session.evaluate("window.__changes") == 1
    finally:
        session.close()


@browser
def test_disabled_options_and_disabled_selects_keep_their_semantics(env):
    client = env["client"]
    login_admin(client)
    session = _session(client)
    try:
        session.goto("/admin/adicionar_atividade")
        session.evaluate("(() => { const s = document.getElementById('tipo_limit_card'); s.options[1].disabled = true; return true; })()")
        start = session.evaluate("document.getElementById('tipo_limit_card').value")
        _open(session, "#tipo_limit_card")
        option = json.loads(session.evaluate(
            "JSON.stringify((() => { const o = document.getElementById('tipo_limit_card').options[1];"
            " return {color: getComputedStyle(o).color, value: o.value}; })())"))
        session.click("#tipo_limit_card option:nth-child(2)")
        session.pump(0.3)
        assert session.evaluate("document.getElementById('tipo_limit_card').value") == start
        tertiary = session.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--text-tertiary').trim()")
        assert option["color"] != session.evaluate(
            "getComputedStyle(document.getElementById('tipo_limit_card').options[0]).color") and tertiary
        _key(session, "Escape", "Escape", 27)

        session.evaluate("document.getElementById('tipo_limit_card').disabled = true; true")
        session.click("#tipo_limit_card")
        session.pump(0.3)
        assert session.evaluate("document.getElementById('tipo_limit_card').matches(':open')") is False
    finally:
        session.close()


@browser
def test_plain_variant_draws_no_chevron_and_keeps_its_native_look(env):
    client = env["client"]
    _as_student(client)
    for mode in ("enhanced", "native"):
        session = _session(client)
        if mode == "native":
            _neutralize(session)
        try:
            session.goto("/aluno/reportar")
            state = json.loads(session.evaluate(
                "JSON.stringify((() => { const s = document.querySelector('select[name=categoria]');"
                " return {appearance: getComputedStyle(s).appearance, icon: getComputedStyle(s, '::picker-icon').display,"
                " inset: getComputedStyle(s, '::before').display}; })())"))
        finally:
            session.close()
        if mode == "enhanced":
            assert state == {"appearance": "base-select", "icon": "none", "inset": "none"}, state
        else:
            assert state["appearance"] == "none", state


@browser
def test_native_fallback_keeps_the_browser_select_and_its_keyboard(env):
    client = env["client"]
    login_admin(client)
    session = _session(client)
    _neutralize(session)
    try:
        session.goto("/admin/adicionar_atividade")
        appearances = json.loads(session.evaluate(
            "JSON.stringify(Array.from(document.querySelectorAll('select')).map(s => getComputedStyle(s).appearance))"))
        assert appearances and set(appearances) == {"auto"}, appearances
        session.evaluate("document.getElementById('tipo_limit_card').focus(); true")
        before = session.evaluate("document.getElementById('tipo_limit_card').selectedIndex")
        _key(session, "ArrowDown", "ArrowDown", 40)
        assert session.evaluate("document.getElementById('tipo_limit_card').selectedIndex") == before + 1
        assert session.evaluate("document.getElementById('tipo_limit_card').matches(':open')") is False
    finally:
        session.close()


@browser
def test_escape_closes_only_the_picker_and_then_the_modal_as_natively(env):
    """A native popup swallows its keys; the in-page picker must too, or the
    Escape that closes the list also closes the modal around it."""
    client = env["client"]
    login_admin(client)
    session = _session(client)
    try:
        session.goto("/admin/acesso")
        session.pump(0.4)
        session.evaluate("document.getElementById('access-modal').removeAttribute('hidden');"
                         " window.__keys = []; document.addEventListener('keydown', e => window.__keys.push(e.key)); true")
        session.pump(0.3)
        assert _open(session, "#access-level")["open"]
        _key(session, "Escape", "Escape", 27)
        assert session.evaluate("document.querySelector('#access-level').matches(':open')") is False
        assert session.evaluate("document.getElementById('access-modal').hidden") is False
        assert session.evaluate("window.__keys") == []  # the page never heard the picker's Escape
        assert session.evaluate("document.activeElement.id") == "access-level"
        _key(session, "Escape", "Escape", 27)  # picker closed: the page's own Escape applies again
        assert session.evaluate("document.getElementById('access-modal').hidden") is True
    finally:
        session.close()


@browser
@pytest.mark.parametrize("width", [1440, 1280, 768, 640])
def test_progress_title_select_keeps_one_width_whichever_type_is_chosen(env, width):
    """The documented native exception: the content-sized Progress title select
    must not change width with its selection."""
    client = env["client"]
    _as_student(client)
    session = _session(client, width)
    boxes = {}
    try:
        for query in ("?tipo=aac", "?tipo=extensao"):
            session.goto("/aluno/progresso" + query)
            boxes[query] = json.loads(session.evaluate(
                "JSON.stringify((() => { const s = document.getElementById('progresso-tipo'); const b = s.getBoundingClientRect();"
                " return {label: s.options[s.selectedIndex].text, appearance: getComputedStyle(s).appearance, box: [b.left, b.top, b.width, b.height]}; })())"))
    finally:
        session.close()
    aac, ext = boxes["?tipo=aac"], boxes["?tipo=extensao"]
    assert aac["label"] == "Acadêmicas Complementares" and ext["label"] == "Extensão Universitária"
    assert aac["appearance"] == ext["appearance"] == "auto"
    assert aac["box"] == ext["box"], boxes
