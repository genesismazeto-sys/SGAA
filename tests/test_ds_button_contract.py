"""Design System: one section card and one button contract (DS-CONSISTENCY-01).

Owner decisions of 2026-11-21 (docs/design-system/README.md §2.8, §2.9, §3.1):

* the section card (.cfg-card head / body / footer) is defined once, in
  components/section-card.css;
* a group of action buttons is a .btn-row (components/actions.css): on the
  desktop right-aligned, data-entry forms centered; the primary is the
  rightmost button and blue (`btn primary`); on the phone the buttons fill
  their line -- no empty space beside them;
* every modal footer is right-aligned by modal.css, never by a page;
* the request decisions read Indeferir, Deferir Parcialmente, Deferir wherever
  they appear;
* status pills carry statuses only.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import main
from tests.canonical_request_test_support import login_admin, student_identity
from tests.cdp_browser_support import BrowserSession, find_chromium
from tests.session_support import stamp_auth_version
from tests.versioned_test_support import isolated_versioned_app_env

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"
COMPONENTS = ROOT / "static" / "css" / "components"
CHROMIUM = find_chromium()
browser = pytest.mark.skipif(CHROMIUM is None, reason="no headless Chromium available")
DEMO = "demo_clientes_form_pack.html"  # an unlinked form demonstration, outside the contract


def _templates():
    return [p for p in sorted(TEMPLATES.rglob("*.html")) if p.name != DEMO]


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ------------------------------------------------------------------ static


def test_both_components_load_globally_before_the_select_picker():
    macro = _text(TEMPLATES / "components" / "design_system_css.html")
    sheets = re.findall(r"'(css/[\w/.-]+\.css)'", macro)
    for sheet in ("css/components/section-card.css", "css/components/actions.css"):
        assert sheet in sheets, sheet
        assert sheets.index(sheet) > sheets.index("css/modern-style.css"), sheet


def test_the_section_card_is_defined_once():
    """A page may restyle a card's surface through a scoped selector, never redefine the anatomy."""
    anatomy = re.compile(r"(?m)^\s*\.cfg-(?:card|card-head|card-body|card-footer|section-label|chips|chip|"
                         r"footer-left|footer-note|footer-actions)\s*\{")
    offenders = [p.name for p in _templates() if anatomy.search(_text(p))]
    offenders += [p.name for p in (ROOT / "static" / "css").rglob("*.css")
                  if p.name != "section-card.css" and anatomy.search(_text(p))]
    assert offenders == [], offenders
    assert anatomy.search(_text(COMPONENTS / "section-card.css"))


def test_the_btn_primary_class_does_not_exist_and_is_never_used():
    """`btn-primary` is not a DS class: a button carrying it renders white (owner, 2026-11-21)."""
    class_use = re.compile(r"""class\s*=\s*["'][^"']*\bbtn-primary\b|classList\.(?:add|toggle)\(\s*['"]btn-primary""")
    offenders = [p.name for p in _templates() if class_use.search(_text(p))]
    offenders += [p.name for p in (ROOT / "static" / "js").rglob("*.js")
                  if "vendor" not in p.parts and class_use.search(_text(p))]
    assert offenders == [], offenders


def test_modal_footers_take_their_alignment_from_the_component():
    modal_css = _text(COMPONENTS / "modal.css")
    footer = re.search(r"\.modal-footer\{([^}]*)\}", modal_css).group(1)
    assert "justify-content:flex-end" in footer.replace(" ", "")
    local = re.compile(r"(?m)^\s*([^{}\n]*\.modal-footer)\s*\{([^}]*)\}")
    offenders = []
    for path in _templates() + [p for p in COMPONENTS.glob("*.css") if p.name != "modal.css"] + [ROOT / "static" / "css" / "modern-style.css"]:
        for selector, body in local.findall(_text(path)):
            if "justify-content" in body and selector.strip() != "#reporte-modal .modal-footer":
                offenders.append((path.name, selector.strip()))
    assert offenders == [], offenders


def test_every_modal_footer_is_a_button_row():
    """The report detail modal keeps Excluir apart on the left; its right group is the row."""
    for path in _templates():
        source = _text(path)
        for tag in re.findall(r'<div class="modal-footer[^"]*"[^>]*>', source):
            if "req-footer" in tag:  # its rows are the button rows
                continue
            if path.name == "admin_reportes.html" and tag == '<div class="modal-footer">':
                assert '<div class="modal-footer-actions btn-row">' in source
                continue
            assert "btn-row" in tag, (path.name, tag)
    rows = re.findall(r'<div class="req-footer-row [^"]*"', _text(TEMPLATES / "admin_requisicoes.html"))
    assert len(rows) == 4 and all("btn-row" in row for row in rows), rows


def test_every_data_entry_form_action_row_is_a_button_row():
    offenders = [(p.name, tag) for p in _templates()
                 for tag in re.findall(r'class="form-actions[^"]*"', _text(p)) if "btn-row" not in tag]
    assert offenders == [], offenders


def test_the_request_decisions_read_one_order_everywhere():
    page = _text(TEMPLATES / "admin_processar_requisicao.html")
    modal = _text(TEMPLATES / "admin_requisicoes.html")
    page_order = re.findall(r'data-process-status="([^"]+)"', page)[:3]
    assert page_order == ["Indeferida", "Deferida Parcialmente", "Deferida"], page_order
    process_row = modal.split('id="m_footer_process_row"', 1)[1].split("</div>", 1)[0]
    assert re.findall(r'data-action="([^"]+)"', process_row) == ["indeferir", "deferir_parte", "deferir"]


def test_labels_levels_and_counts_are_chips_not_status_pills():
    diag = _text(TEMPLATES / "admin_diagnostico_atividades_versionadas_view.html")
    assert "status-pill" not in diag
    acesso = _text(TEMPLATES / "admin_acesso.html")
    for tag in re.findall(r"<span[^>]*data-(?:email-tally|resource-effective-pill)=[^>]*>", acesso):
        assert 'class="cfg-chip"' in tag and "status-pill" not in tag, tag


# ----------------------------------------------------------------- browser

PAGES_ADMIN = ["/admin/configuracoes", "/admin/banco-dados", "/admin/acesso", "/admin/alertas", "/admin/atividades",
               "/admin/turmas", "/admin/reportes", "/admin/requisicoes", "/admin/adicionar_aluno",
               "/admin/arquivos", "/admin/adicionar_turma", "/admin/cursos/adicionar", "/admin/processar_requisicao/{req}",
               "/admin/catalogo-versoes/{base}",
               "/admin/importar_requisicoes", "/admin/diagnostico/atividades-versionadas/view?turma_id={turma}",
               "/admin/catalogo-versoes/{base}/versoes/{versao}/editar"]
PAGES_ALUNO = ["/aluno/reportar", "/aluno/nova-requisicao", "/aluno/requisicoes"]

# Open every modal and every mode row of the request modal: their footers are measured too.
REVEAL = """(() => { document.querySelectorAll('.modal-overlay[hidden], [id$=-modal][hidden]').forEach(m => m.removeAttribute('hidden'));
  document.querySelectorAll('.req-footer-row[hidden]').forEach(r => { r.hidden = false; r.style.display = ''; });
  return true; })()"""

# Every visible action row: the .btn-row groups, and the list toolbar's two groups on the phone.
MEASURE = r"""((phone) => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(e).visibility !== 'hidden'; };
  const out = [];
  const rows = [...document.querySelectorAll('.btn-row')];
  if (phone) rows.push(...document.querySelectorAll('.app-main .toolbar .actions'));
  for (const row of rows) {
    if (!vis(row)) continue;
    const box = row.getBoundingClientRect(), cs = getComputedStyle(row);
    const inner = {l: box.left + parseFloat(cs.paddingLeft) + parseFloat(cs.borderLeftWidth),
                   r: box.right - parseFloat(cs.paddingRight) - parseFloat(cs.borderRightWidth)};
    const items = [...row.querySelectorAll(':scope > *, :scope > form > .btn, :scope > form > button')]
      .filter(e => e.tagName !== 'FORM' && e.tagName !== 'INPUT' && vis(e));
    if (!items.length) continue;
    const rects = items.map(e => e.getBoundingClientRect());
    const lines = {};
    rects.forEach((r, i) => { const k = Math.round(r.top / 4); (lines[k] = lines[k] || []).push(i); });
    const label = (row.className + ' @ ' + items.map(e => (e.innerText || '').trim().split('\n')[0]).join(' | ')).slice(0, 160);
    const primary = items.findIndex(e => e.matches('.btn.primary'));
    const last = rects.reduce((best, r, i) => (r.right > rects[best].right + 1 || (Math.abs(r.right - rects[best].right) <= 1 && r.top < rects[best].top - 1)) ? i : best, 0);
    // Space between neighbouring buttons on one line, and how far the buttons sit from a dialog's edges.
    let gap = null;
    Object.values(lines).forEach(ix => { const xs = ix.map(i => rects[i]).sort((a, b) => a.left - b.left);
      for (let i = 1; i < xs.length; i++) { const g = xs[i].left - xs[i - 1].right; gap = gap === null ? g : Math.min(gap, g); } });
    const card = row.closest('.modal-card');
    let edge = null, formDialog = false, cardSides = null;
    if (card) {
      const c = card.getBoundingClientRect();
      edge = Math.min(...rects.map(r => Math.min(r.left - c.left, c.right - r.right, c.bottom - r.bottom)));
      // In a dialog, the centre is the dialog's, not the row's (a content-sized row is always 'centred').
      cardSides = [Math.min(...rects.map(r => r.left)) - c.left, c.right - Math.max(...rects.map(r => r.right))];
      // A dialog with fields to fill is a form: its buttons sit in the centre (owner, 2026-11-21).
      formDialog = !card.closest('#reporte-modal') && [...card.querySelectorAll(
        'input:not([type=hidden]):not([type=checkbox]):not([type=radio]), select, textarea, .file-card')].some(vis);
    }
    out.push({label, center: row.matches('.btn-row--center, .form-actions.center'), gap, edge, formDialog, cardSides,
              toolbar: !!row.closest('.toolbar'),
              lines: Object.values(lines).map(ix => ({l: Math.min(...ix.map(i => rects[i].left)) - inner.l,
                                                    r: inner.r - Math.max(...ix.map(i => rects[i].right))})),
              primary, primaryRect: primary >= 0 ? [rects[primary].top, rects[primary].right] : null,
              rightmost: last, count: items.length, primaryCount: items.filter(e => e.matches('.btn.primary')).length});
  }
  return JSON.stringify(out);
})"""


@pytest.fixture()
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "ds-buttons.db") as value:
        yield value


def _sql(query, params=()):
    with main.app.app_context():
        conn = main.get_db_connection()
        rows = conn.execute(query, params).fetchall()
        conn.commit()
        return rows


def _ids():
    return {"turma": _sql("SELECT id FROM turmas ORDER BY id LIMIT 1")[0][0],
            "base": _sql("SELECT atividade_base_id FROM atividade_versao ORDER BY id LIMIT 1")[0][0],
            "versao": _sql("SELECT id FROM atividade_versao ORDER BY id LIMIT 1")[0][0],
            "req": (_sql("SELECT id FROM requisicoes ORDER BY id LIMIT 1") or [[1]])[0][0]}


def _as_student(client):
    identity = student_identity()
    with client.session_transaction() as session:
        session.clear()
        session.update(user_id=identity["usuario_id"], user_type="aluno", user_name="Aluno")
        stamp_auth_version(session)
    return identity


def _session(client, width):
    session = BrowserSession(client, CHROMIUM)
    session.call("Emulation.setDeviceMetricsOverride",
                 {"width": width, "height": 900 if width >= 768 else 844, "deviceScaleFactor": 1, "mobile": False})
    return session


def _offenders(rows, phone):
    """The contract, row by row. Returns the rows that break it, with the reason."""
    bad = []
    for row in rows:
        if row["primaryCount"] > 1:
            bad.append(("more than one primary", row["label"]))
        # Desktop: the list toolbar joins its controls (--btn-gap); every other row keeps its buttons 8px apart
        # or more, inside the dialog's edges. The phone is left as it is (owner, 2026-11-21).
        if not phone and not row["toolbar"] and row["gap"] is not None and row["gap"] < 7.5:
            bad.append(("buttons without their gap", row["label"], row["gap"]))
        if not phone and row["edge"] is not None and row["edge"] < 8:
            bad.append(("buttons against the dialog's edge", row["label"], row["edge"]))
        if not phone and row["formDialog"] and not row["center"]:
            bad.append(("desktop: a form dialog's buttons not centered", row["label"]))
        if phone:
            holes = [ln for ln in row["lines"] if ln["l"] > 1.5 or ln["r"] > 1.5]
            if holes:
                bad.append(("phone: empty space beside the buttons", row["label"], holes))
        else:
            line = row["lines"][0]
            if len(row["lines"]) == 1:
                if row["center"] and abs(line["l"] - line["r"]) > 2:
                    bad.append(("desktop: form actions not centered", row["label"], line))
                sides = row.get("cardSides")
                if row["center"] and sides and abs(sides[0] - sides[1]) > 4:
                    bad.append(("desktop: a dialog's buttons not in its centre", row["label"], sides))
                if not row["center"] and line["r"] > 1.5:
                    bad.append(("desktop: buttons not on the right", row["label"], line))
            if row["primary"] >= 0 and row["count"] > 1 and row["primary"] != row["rightmost"]:
                bad.append(("desktop: the primary is not the rightmost button", row["label"]))
    return bad


def _measure(client, width, inject_css=None):
    ids = _ids()
    rows = []
    session = _session(client, width)
    try:
        for role, paths in (("admin", PAGES_ADMIN), ("aluno", PAGES_ALUNO)):
            (login_admin if role == "admin" else _as_student)(client)
            for path in paths:
                session.goto(path.format(**ids))
                if inject_css:
                    session.evaluate("(() => { const s = document.createElement('style'); s.textContent = %s;"
                                     " document.head.appendChild(s); return true; })()" % json.dumps(inject_css))
                session.evaluate(REVEAL)
                session.pump(0.2)
                for row in json.loads(session.evaluate(MEASURE + f"({'true' if width < 768 else 'false'})")):
                    row["label"] = f"{path} :: {row['label']}"
                    rows.append(row)
    finally:
        session.close()
    return rows


@browser
@pytest.mark.parametrize("width", [1440, 390])
def test_every_action_row_follows_the_button_contract(env, width):
    rows = _measure(env["client"], width)
    assert len(rows) >= 30, len(rows)  # the walk reached the modals and the forms
    assert _offenders(rows, phone=width < 768) == []


@browser
def test_the_contract_check_catches_a_row_with_empty_space_and_a_left_primary(env):
    """Negative controls: undo the contract on a footer and on a modal and the check must fail."""
    phone = _measure(env["client"], 390, inject_css=".cfg-footer-actions > .btn{ flex:0 0 auto !important; }")
    assert any("empty space" in bad[0] and "cfg-footer-actions" in bad[1] for bad in _offenders(phone, phone=True))
    desk = _measure(env["client"], 1440, inject_css=".modal-footer.btn-row{ justify-content:center !important; }"
                                                    " .modal-footer.btn-row > .btn.primary{ order:-1; }")
    reasons = {bad[0] for bad in _offenders(desk, phone=False)}
    assert "desktop: buttons not on the right" in reasons
    assert "desktop: the primary is not the rightmost button" in reasons
