"""UI-B05 -- Cursos > Ver curso.

Reported: the course view rendered an "unusual horizontal band" diverging from
the other SGAA detail screens.

Cause: the page put its course facts inside ``<section class="content-block">``
-- the shared *dashboard summary card* (``--surface`` fill, ``--border-strong``
hairline, ``--radius``, 16px padding, ``--shadow-md``) -- with the
``.content-block-header`` that names every other card built from it omitted, so
what remained was untitled chrome; its ``justify-content:space-between`` body
then pinned the items to the left, centre and right page edges. The page also
never adopted the detail-header contract, so it carried a raw ``.main-title``
and a generic ``<- Voltar`` stranded at the bottom.

Reference chosen by the user: **Turma detail**
(``templates/admin_detalhes_turma.html``) -- the closest sibling surface
(entity + list of its children) and never reported. Its metadata strip carries
no card chrome: a small secondary label above its value, blocks reading from
the left, title and Back on one line.
"""

from __future__ import annotations

import os
import re
import sys
import uuid
from pathlib import Path

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main  # noqa: E402
from tests.session_support import stamp_auth_version  # noqa: E402

ROOT = Path(BASE)
COURSE_DETAIL = ROOT / "templates" / "admin_detalhes_curso.html"
COURSE_LIST = ROOT / "templates" / "admin_cursos.html"
TURMA_DETAIL = ROOT / "templates" / "admin_detalhes_turma.html"
HEADER_MACRO = ROOT / "templates" / "components" / "detail_header.html"
HEADER_CSS = ROOT / "static" / "css" / "components" / "detail-header.css"
GLOBAL_CSS = ROOT / "static" / "css" / "modern-style.css"
COURSE_VIEW = ROOT / "app" / "views" / "admin" / "alunos_turmas_cursos.py"

RAW_COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(")

# Label, then value: the order the strip must render them in.
EXPECTED_FIELDS = ["Código", "Duração", "Turmas", "Alunos", "Status"]


@pytest.fixture(scope="module")
def client():
    with main.app.app_context():
        main.init_db()
    with main.app.test_client() as test_client:
        yield test_client


def _login_admin(test_client):
    with test_client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["user_type"] = "admin"
        sess["user_name"] = "Administrador"
        sess["access_level"] = "admin_total"
        stamp_auth_version(sess)


def _login_aluno(test_client):
    with test_client.session_transaction() as sess:
        sess["user_id"] = 2
        sess["user_type"] = "aluno"
        sess["user_name"] = "Aluno Teste"
        stamp_auth_version(sess)


def _unique(prefix):
    """Letter-only: ``validar_codigo_curso`` accepts A-Z and ``-`` only, and the
    edit test below round-trips a code through the real validator."""
    suffix = "".join(chr(ord("A") + byte % 26) for byte in uuid.uuid4().bytes[:4])
    return f"{prefix}-{suffix}"


def _seed_curso(codigo, nome, duracao_periodos=6, status="ativo"):
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("DELETE FROM cursos WHERE codigo = ?", (codigo,))
        conn.execute(
            "INSERT INTO cursos (nome, codigo, duracao_periodos, status) VALUES (?,?,?,?)",
            (nome, codigo, duracao_periodos, status),
        )
        conn.commit()
        return conn.execute(
            "SELECT id FROM cursos WHERE codigo = ?", (codigo,)
        ).fetchone()["id"]


def _seed_turma(curso_id, codigo, numero, status="Ativa", alunos=0):
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("DELETE FROM turmas WHERE codigo = ?", (codigo,))
        conn.execute(
            "INSERT INTO turmas (nome, ano_inicio, semestre_inicio, turno, status, "
            "numero, curso_id, codigo) VALUES (?,?,?,?,?,?,?,?)",
            (codigo, 2026, 1, "Manha", status, numero, curso_id, codigo),
        )
        turma_id = conn.execute(
            "SELECT id FROM turmas WHERE codigo = ?", (codigo,)
        ).fetchone()["id"]
        for index in range(alunos):
            email = f"{codigo.lower()}-{index}@example.com"
            conn.execute("DELETE FROM usuarios WHERE email = ?", (email,))
            conn.execute(
                "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) "
                "VALUES (?,?,?,?,?)",
                (f"Aluno {index}", email, main.hash_password("x"), "aluno", "usuario"),
            )
            usuario_id = conn.execute(
                "SELECT id FROM usuarios WHERE email = ?", (email,)
            ).fetchone()["id"]
            conn.execute(
                "INSERT INTO alunos (usuario_id, nome, turma_id, matricula) VALUES (?,?,?,?)",
                (usuario_id, f"Aluno {index}", turma_id, f"{codigo}-{index}"),
            )
        conn.commit()


@pytest.fixture(scope="module")
def populated(client):
    """Two turmas carrying 2 + 3 alunos, so the derived counts are falsifiable."""
    _login_admin(client)
    codigo = _unique("UIBPOP")
    curso_id = _seed_curso(codigo, "Curso UI-B05 Populado", duracao_periodos=6)
    _seed_turma(curso_id, f"{codigo}-TA", numero=1, status="Ativa", alunos=2)
    _seed_turma(curso_id, f"{codigo}-TB", numero=2, status="Inativa", alunos=3)
    response = client.get(f"/admin/cursos/{curso_id}")
    assert response.status_code == 200, response.status_code
    return {
        "id": curso_id,
        "codigo": codigo,
        "nome": "Curso UI-B05 Populado",
        "html": response.get_data(as_text=True),
    }


@pytest.fixture(scope="module")
def template_source():
    return COURSE_DETAIL.read_text(encoding="utf-8")


def _class_tokens(html, token):
    """Exact class-token matches. ``content-block`` is a prefix of
    ``content-block-body``, so a substring test would pass while the card
    wrapper was still on the page."""
    return [
        attr for attr in re.findall(r'class="([^"]*)"', html) if token in attr.split()
    ]


def _strip(html):
    match = re.search(r'<div class="detail-meta-strip">(.*?)\n</div>', html, re.S)
    assert match, "the course page renders no metadata strip"
    return match.group(1)


# ==========================================================================
# A. The rejected band is gone
# ==========================================================================


def test_the_untitled_summary_card_band_is_gone(populated, template_source):
    html = populated["html"]
    assert _class_tokens(html, "content-block") == [], (
        "the dashboard summary card that painted the band is still on the page"
    )
    assert "content-block" not in template_source
    assert not re.search(r"<style[^>]*>", template_source, re.I), (
        "the course page grew a local <style> block"
    )

    # Those five declarations are what drew the band, and they live on
    # .content-block -- which the page no longer uses. The dashboards keep it.
    card = re.search(r"\n\.content-block\{(.*?)\}", GLOBAL_CSS.read_text(encoding="utf-8"), re.S)
    assert card
    for declaration in (
        "background:var(--surface)",
        "border:1px solid var(--border-strong)",
        "box-shadow:var(--shadow-md)",
    ):
        assert declaration in card.group(1).replace("\n", " "), declaration


def test_the_strip_carries_no_card_chrome(populated):
    """The Turma treatment: no fill, no border, no radius, no shadow, no padding."""
    css = GLOBAL_CSS.read_text(encoding="utf-8")
    for selector in (".detail-meta-strip", ".detail-meta-block", ".detail-meta-value"):
        rule = re.search(re.escape(selector) + r"\{(.*?)\}", css, re.S)
        assert rule, f"missing rule: {selector}"
        body = rule.group(1)
        for forbidden in ("background:", "border:", "border-radius:", "box-shadow:"):
            assert forbidden not in body, f"{selector} paints chrome: {forbidden}"

    # And nothing on the page re-introduces it inline.
    for style in re.findall(r'style="([^"]*)"', populated["html"]):
        assert not RAW_COLOUR.search(style), style


# ==========================================================================
# B. The strip matches the Turma detail treatment
# ==========================================================================


def test_label_sits_above_its_value_like_turma(populated):
    """Turma renders label-then-value; the old card rendered value-then-label."""
    strip = _strip(populated["html"])
    blocks = re.findall(r'<div class="detail-meta-block">(.*?)</div>', strip, re.S)
    assert len(blocks) == len(EXPECTED_FIELDS), blocks

    for block, expected in zip(blocks, EXPECTED_FIELDS):
        label = re.search(r'<span class="detail-meta-label">([^<]+)</span>', block)
        assert label and label.group(1) == expected, (block, expected)
        value = re.search(r'<span class="(detail-meta-value|badge[^"]*)"', block)
        assert value, f"{expected} has no value element"
        assert block.index("detail-meta-label") < block.index(value.group(1)), (
            f"{expected} renders its value above its label"
        )

    # Same vertical rhythm as the reference strip.
    css = GLOBAL_CSS.read_text(encoding="utf-8")
    assert "gap:5px" in re.search(r"\.detail-meta-block\{(.*?)\}", css, re.S).group(1)
    turma = TURMA_DETAIL.read_text(encoding="utf-8")
    assert "gap:5px" in re.search(r"\.turma-meta-block\{(.*?)\}", turma, re.S).group(1)


def test_the_blocks_read_from_the_left_not_spread_to_the_page_edges(populated):
    """The specific geometry that produced the rejected band."""
    css = GLOBAL_CSS.read_text(encoding="utf-8")
    strip = re.search(r"\.detail-meta-strip\{(.*?)\}", css, re.S).group(1)
    assert "justify-content" not in strip, (
        "space-between across a full track is what scattered the old items"
    )
    assert "flex-wrap:wrap" in strip, "the strip must wrap rather than overflow"
    assert "column-gap" in strip and "row-gap" in strip

    badge = re.search(r"\.detail-meta-block \.badge\{(.*?)\}", css, re.S)
    assert badge and "width:max-content" in badge.group(1), (
        "the status pill would otherwise stretch to its block's width"
    )


def test_the_strip_is_shared_css_not_a_course_local_component():
    css = GLOBAL_CSS.read_text(encoding="utf-8")
    assert ".detail-meta-strip{" in css
    # Surface-named, reusable -- no Cursos-only selector anywhere.
    assert not re.search(r"^\s*\.curso-[\w-]*\s*\{", css, re.M)
    assert not re.search(r"\.detail-meta-[\w-]*[^{]*curso", css)
    assert not RAW_COLOUR.search(
        css[css.index(".detail-meta-strip{"): css.index(".detail-meta-strip{") + 1200]
    ), "a raw colour entered the strip"


# ==========================================================================
# C. Header and back action
# ==========================================================================


def test_header_and_single_back_action(populated, template_source):
    html = populated["html"]
    header = re.search(r'<header class="detail-header">(.*?)</header>', html, re.S)
    assert header, "Ver curso does not render the shared detail header"

    assert html.count('detail-header__title"') == 1
    assert html.count("detail-header__back") == 1
    assert html.count('data-lucide="arrow-left"') == 1, "a second back action survives"
    assert len(_class_tokens(html, "main-title")) == 1
    assert populated["nome"] in header.group(1)

    back = re.search(r'<a class="btn detail-header__back"(.*?)</a>', html, re.S).group(1)
    assert 'href="/admin/cursos"' in back
    with main.app.test_request_context():
        from flask import url_for

        assert url_for("admin_cursos") in back

    # Title left, Back right on one line -- the Turma topbar shape.
    assert html.index("detail-header__title") < html.index("detail-header__back")
    assert re.search(
        r"\.detail-header__back\{[^}]*justify-self:end", HEADER_CSS.read_text(encoding="utf-8")
    )
    assert "from 'components/detail_header.html' import detail_header" in template_source
    assert 'class="btn detail-header__back"' in HEADER_MACRO.read_text(encoding="utf-8")

    # The rejected stranded footer anchor is gone from the markup.
    assert not re.search(r"</div>\s*\n\s*<a class=\"btn\" href=", template_source)


# ==========================================================================
# D. The added facts are real, derived data using the list's own vocabulary
# ==========================================================================


def test_turmas_and_alunos_are_derived_from_the_pages_own_rows(populated):
    strip = _strip(populated["html"])
    values = dict(
        zip(
            re.findall(r'<span class="detail-meta-label">([^<]+)</span>', strip),
            re.findall(r'<span class="detail-meta-value">([^<]+)</span>', strip)
            + ["<badge>"],
        )
    )
    assert values["Turmas"] == "2", values
    assert values["Alunos"] == "5", values  # 2 + 3, summed from the rendered rows
    assert values["Código"] == populated["codigo"]
    assert values["Duração"] == "6 períodos"

    # Status stays a pill, with the classes it already had.
    assert "badge success status-badge status-pill status-positive" in strip
    assert ">Ativo<" in strip


def test_the_two_added_labels_come_from_the_course_list_vocabulary():
    """Turmas/Alunos are not invented wording -- the list header already uses them."""
    listing = COURSE_LIST.read_text(encoding="utf-8")
    for label in ("Turmas", "Alunos", "Código", "Duração", "Status"):
        assert f"'text':'{label}'" in listing, label


def test_counts_hold_when_the_course_has_no_turmas(client):
    codigo = _unique("UIBVAZIO")
    curso_id = _seed_curso(codigo, "Curso UI-B05 Vazio", duracao_periodos=4, status="inativo")
    _login_admin(client)
    html = client.get(f"/admin/cursos/{curso_id}").get_data(as_text=True)

    strip = _strip(html)
    values = re.findall(r'<span class="detail-meta-value">([^<]+)</span>', strip)
    assert values[-2:] == ["0", "0"], values
    assert "Nenhuma turma cadastrada." in html
    assert ">Inativo<" in html


def _listing(html):
    match = re.search(
        r'<div class="impressoes-cards-scroll imp-curso-turmas"(.*?)\n</div>', html, re.S
    )
    assert match, "the turmas list left the page"
    return match.group(1)


def test_turmas_list_puts_status_last_like_every_other_sgaa_list(populated):
    """It rendered Nº · **Status** · Ano/Semestre · Alunos -- Status in slot 2."""
    headers = re.findall(r'<div class="cell center">([^<\n]+)</div>', _listing(populated["html"]))
    assert headers[:4] == ["Nº", "Ano/Semestre", "Alunos", "Status"], headers[:4]
    assert _listing(populated["html"]).count('role="listitem"') == 2

    # The convention, read off the lists nobody reported.
    for name in ("admin_cursos", "admin_turmas"):
        labels = re.findall(
            r"\{'text':'([^']+)'", (ROOT / "templates" / f"{name}.html").read_text(encoding="utf-8")
        )
        assert labels and labels[-1] == "Status", (name, labels)


def test_every_column_track_can_grow_to_fill_the_row(populated):
    """The defect: all four tracks had a fixed px maximum.

    72 + 104 + 120 + 100 = 396px of grid inside a `width:100% !important` card,
    so the columns bunched on the left and the rest of the row stayed empty.
    """
    css = (ROOT / "static" / "css" / "components" / "list-cards.css").read_text(encoding="utf-8")
    cols = re.search(r"\.imp-curso-turmas \{ --imp-cols:(.*?)\};", css, re.S)
    assert cols, "the course turmas column definition disappeared"

    maxima = re.findall(r"minmax\(\s*[\d.]+px\s*,\s*([^)]+)\)", cols.group(1))
    assert len(maxima) == 4, maxima
    for maximum in maxima:
        assert maximum.strip().endswith("fr"), (
            f"track max {maximum.strip()!r} is a fixed width, so the row cannot fill: {maxima}"
        )

    # Not a lone exception: the accepted lists are built the same way.
    for scope in (".imp-turmas", ".imp-cursos"):
        block = re.search(re.escape(scope) + r" \{ --imp-cols:(.*?)\};", css, re.S)
        assert block and "fr" in block.group(1), scope


def test_ano_semestre_renders_real_data_not_an_em_dash(populated):
    """It read t.semestre / t.ano; the turmas table has semestre_inicio /
    ano_inicio, so `SELECT t.*` never produced them and every row was '—'."""
    listing = _listing(populated["html"])
    cards = re.split(r'<div class="impresso-card " role="listitem"', listing)[1:]
    assert cards, "no turma rows rendered"

    for card in cards:
        cells = re.findall(r'<div class="cell center">(.*?)</div>', card, re.S)
        periodo = " ".join(re.sub(r"<[^>]+>", " ", cells[1]).split())
        assert re.fullmatch(r"\dS-\d{4}", periodo), f"Ano/Semestre is {periodo!r}"

    template = COURSE_DETAIL.read_text(encoding="utf-8")
    assert "t.semestre_inicio" in template and "t.ano_inicio" in template
    # The comment explaining the bug names the old fields, so read the markup
    # with Jinja comments stripped.
    markup = re.sub(r"\{#.*?#\}", "", template, flags=re.S)
    assert not re.search(r"t\.semestre\b", markup), "the phantom column is back"
    assert not re.search(r"t\.ano\b", markup), "the phantom column is back"

    with main.app.app_context():
        columns = {
            row[1]
            for row in main.get_db_connection().execute("PRAGMA table_info(turmas)")
        }
    assert {"ano_inicio", "semestre_inicio"} <= columns
    assert "semestre" not in columns and "ano" not in columns


# ==========================================================================
# E. Presentation-only: routes, context and edit behaviour unchanged
# ==========================================================================


def test_route_surface_and_view_context_are_untouched(client, populated):
    source = COURSE_VIEW.read_text(encoding="utf-8")
    assert (
        'return render_template("admin_detalhes_curso.html", curso=curso, turmas=turmas)'
        in source
    ), "the handler's render context changed; UI-B05 is presentation-only"

    _login_admin(client)
    redirected = client.get(
        f"/admin/cursos/{populated['id']}/visualizar", follow_redirects=False
    )
    assert redirected.status_code in (301, 302, 303, 307, 308)
    assert redirected.headers["Location"].endswith(f"/admin/cursos/{populated['id']}")

    missing = client.get("/admin/cursos/999999", follow_redirects=False)
    assert missing.status_code == 302
    assert missing.headers["Location"].endswith("/admin/cursos")


def test_permissions_are_unchanged(client, populated):
    _login_aluno(client)
    blocked = client.get(f"/admin/cursos/{populated['id']}", follow_redirects=False)
    assert blocked.status_code == 302
    assert blocked.headers["Location"].endswith("/login")

    with client.session_transaction() as sess:
        sess.clear()
    anonymous = client.get(f"/admin/cursos/{populated['id']}", follow_redirects=False)
    assert anonymous.status_code == 302
    assert anonymous.headers["Location"].endswith("/login")


def test_editing_a_course_still_works(client):
    codigo = _unique("UIBEDIT")
    curso_id = _seed_curso(codigo, "Curso UI-B05 Editavel", duracao_periodos=4)
    _login_admin(client)
    assert client.get(f"/admin/cursos/{curso_id}/editar").status_code == 200

    previous = main.app.config.get("WTF_CSRF_ENABLED")
    main.app.config["WTF_CSRF_ENABLED"] = False
    try:
        saved = client.post(
            f"/admin/cursos/{curso_id}/editar",
            data={
                "nome": "Curso UI-B05 Renomeado",
                "codigo": codigo,
                "duracao_periodos": "8",
                "status": "ativo",
            },
            follow_redirects=False,
        )
    finally:
        main.app.config["WTF_CSRF_ENABLED"] = previous

    assert saved.status_code == 302
    assert saved.headers["Location"].endswith("/admin/cursos")
    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT nome, duracao_periodos FROM cursos WHERE id = ?", (curso_id,)
        ).fetchone()
    assert row["nome"] == "Curso UI-B05 Renomeado"
    assert row["duracao_periodos"] == 8

    html = client.get(f"/admin/cursos/{curso_id}").get_data(as_text=True)
    assert "Curso UI-B05 Renomeado" in html
    assert "8 períodos" in html


# ==========================================================================
# F. Responsiveness: shared contracts only, no course-only breakpoint
# ==========================================================================


def test_no_course_only_breakpoint_and_the_strip_narrows_by_wrapping(template_source):
    assert "@media" not in template_source and "@container" not in template_source

    css = GLOBAL_CSS.read_text(encoding="utf-8")
    start = css.index(".detail-meta-strip{")
    assert "@media" not in css[start:start + 1200]
    assert "@container" not in css[start:start + 1200]

    header_css = HEADER_CSS.read_text(encoding="utf-8")
    narrow = re.search(r"@container track \(max-width:480px\)\{(.*?)\n\}", header_css, re.S)
    assert narrow, "the shared header lost its narrow-width contract"
    assert "justify-self:start" in narrow.group(1)

    # Long values shorten rather than push the strip wide (Turma's own rule).
    value = re.search(r"\.detail-meta-value\{(.*?)\}", css, re.S).group(1)
    assert "text-overflow:ellipsis" in value and "min-width:0" in value


# ==========================================================================
# G. "Ver curso" is the edit form with the edit taken away
# ==========================================================================

EDIT_FORM = ROOT / "templates" / "admin_editar_curso.html"
ATIVIDADE_FORM = ROOT / "templates" / "admin_editar_atividade.html"
VERSAO_FORM = ROOT / "templates" / "admin_catalogo_versao_form.html"
FORM_CSS = ROOT / "static" / "css" / "components" / "form.css"


@pytest.fixture(scope="module")
def curso_forms(client):
    """The same course rendered in both modes, from the one template."""
    _login_admin(client)
    codigo = _unique("UIBFORM")
    curso_id = _seed_curso(codigo, "Curso UI-B05 Form", duracao_periodos=7)
    pages = {}
    for mode, url in (
        ("view", f"/admin/cursos/{curso_id}/editar?view=1"),
        ("edit", f"/admin/cursos/{curso_id}/editar"),
    ):
        response = client.get(url)
        assert response.status_code == 200, (mode, response.status_code)
        pages[mode] = response.get_data(as_text=True)
    pages["id"] = curso_id
    pages["codigo"] = codigo
    return pages


def _fieldset_attrs(html):
    match = re.search(r'<fieldset class="form-fieldset"([^>]*)>', html)
    assert match, "the form lost its fieldset"
    return match.group(1).strip()


def test_ver_curso_is_the_edit_form_not_a_second_page(curso_forms):
    """Same template, same fields, same order -- only editability differs."""
    assert "Ver Curso" in curso_forms["view"]
    assert "Editar Curso" in curso_forms["edit"]

    def fields(html):
        form = html[html.index("<form method=\"POST\">"): html.index("</form>")]
        return re.findall(r'<label class="row-label">([^<]+)</label>', form), re.findall(
            r'name="([^"]+)"', form
        )

    assert fields(curso_forms["view"]) == fields(curso_forms["edit"]), (
        "view and edit render different fields"
    )
    labels, names = fields(curso_forms["view"])
    assert labels == ["Nome", "Código", "Duração (períodos)", "Status"], labels
    assert names == ["nome", "codigo", "duracao_periodos", "status"], names
    assert curso_forms["codigo"] in curso_forms["view"]


def test_view_mode_uses_the_shared_read_only_region_contract(curso_forms):
    """disabled + aria-readonly is what components/form.css keys the
    read-only card background on (UI-B10). Anything else is a lookalike."""
    attrs = _fieldset_attrs(curso_forms["view"])
    assert "disabled" in attrs and 'aria-readonly="true"' in attrs, attrs
    assert _fieldset_attrs(curso_forms["edit"]) == "", "the edit form is not editable"

    css = FORM_CSS.read_text(encoding="utf-8")
    rule = re.search(
        r'fieldset\[disabled\]\[aria-readonly="true"\] \.field-card'
        r'[^{]*\{([^}]*)\}',
        css,
        re.S,
    )
    assert rule, "the shared read-only region contract disappeared"
    assert "background:var(--field-readonly-bg)" in rule.group(1), (
        "the read-only card background must come from the DS token"
    )

    # No page-local imitation of it.
    template = EDIT_FORM.read_text(encoding="utf-8")
    assert not re.search(r"<style[^>]*>", template, re.I)
    assert not RAW_COLOUR.search(template)

    # Same marker the two accepted read-only surfaces already carry.
    for reference in (ATIVIDADE_FORM, VERSAO_FORM):
        assert 'disabled aria-readonly="true"' in reference.read_text(encoding="utf-8"), (
            reference.name
        )


def test_view_mode_has_no_footer_buttons_only_the_header_back(curso_forms):
    view = curso_forms["view"]
    assert "form-actions" not in view, "view mode still renders footer buttons"
    assert ">Salvar<" not in view and ">Cancelar</a>" not in view
    assert 'type="submit"' not in view, "a submit control survives in view mode"

    back = re.search(r'<a class="btn detail-header__back"(.*?)</a>', view, re.S)
    assert back, "view mode has no page-level Back action in the header"
    assert 'href="/admin/cursos"' in back.group(1)
    assert view.count("detail-header__back") == 1
    assert view.count('data-lucide="arrow-left"') == 1


def test_edit_mode_centres_salvar_and_cancelar(curso_forms):
    """It rendered a bare .form-actions; every accepted form uses .center."""
    edit = curso_forms["edit"]
    assert re.findall(r'<div class="(form-actions[^"]*)">', edit) == ["form-actions center"]
    actions = edit[edit.index('class="form-actions center"'):]
    assert ">Cancelar</a>" in actions
    assert 'type="submit"' in actions and ">Salvar<" in actions
    # Cancel first, primary last -- the order the accepted forms use.
    assert actions.index("Cancelar") < actions.index("Salvar")

    css = (ROOT / "static" / "css" / "modern-style.css").read_text(encoding="utf-8")
    rule = re.search(r"\.form-actions\.center\{([^}]*)\}", css)
    assert rule and "justify-content:center" in rule.group(1), (
        "the centring must come from the shared modifier"
    )
    # Not invented here: the accepted forms already use the same modifier.
    for reference in (ATIVIDADE_FORM, VERSAO_FORM):
        assert 'class="form-actions center"' in reference.read_text(encoding="utf-8"), (
            reference.name
        )


def test_the_list_ver_action_opens_the_form_in_view_mode():
    listing = (ROOT / "templates" / "admin_cursos.html").read_text(encoding="utf-8")
    view_branch = listing[listing.index("if (action === 'view')"): listing.index("action === 'edit'")]
    assert "admin_editar_curso" in view_branch, (
        "Ver still points at the old course-detail redirect"
    )
    assert "{ view: 1 }" in view_branch
    assert "admin_visualizar_curso" not in view_branch

    # The same idiom the surfaces that were never reported already use.
    for name in ("admin_alunos", "admin_atividades", "admin_detalhes_turma"):
        assert "{ view: 1 }" in (ROOT / "templates" / f"{name}.html").read_text(encoding="utf-8"), name


def test_view_mode_does_not_change_the_edit_handler(client, curso_forms):
    """Presentation only: saving from edit mode still works, unchanged."""
    curso_id = curso_forms["id"]
    previous = main.app.config.get("WTF_CSRF_ENABLED")
    main.app.config["WTF_CSRF_ENABLED"] = False
    try:
        saved = client.post(
            f"/admin/cursos/{curso_id}/editar",
            data={
                "nome": "Curso UI-B05 Form Salvo",
                "codigo": curso_forms["codigo"],
                "duracao_periodos": "9",
                "status": "inativo",
            },
            follow_redirects=False,
        )
    finally:
        main.app.config["WTF_CSRF_ENABLED"] = previous

    assert saved.status_code == 302
    assert saved.headers["Location"].endswith("/admin/cursos")
    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT nome, duracao_periodos, status FROM cursos WHERE id = ?", (curso_id,)
        ).fetchone()
    assert (row["nome"], row["duracao_periodos"], row["status"]) == (
        "Curso UI-B05 Form Salvo",
        9,
        "inativo",
    )


def test_form_fieldset_reset_is_owned_by_the_shared_stylesheet():
    """The defect: the class was copied, the CSS was not.

    A bare <fieldset> brings the browser's border/padding/margin and is not a
    grid, so the Cursos form rendered a box around itself and lost the 12px
    row spacing. The reset lived only inside two page <style> blocks.
    """
    css = FORM_CSS.read_text(encoding="utf-8")
    rule = re.search(r"\n\.form-fieldset\{([^}]*)\}", css)
    assert rule, ".form-fieldset has no owner in the shared stylesheet"
    declarations = {d.strip() for d in rule.group(1).split(";") if d.strip()}
    for required in ("border:0", "padding:0", "margin:0", "display:grid", "row-gap:12px"):
        assert required in declarations, f"missing {required}: {declarations}"

    # Sole ownership: no template may declare the component again. The two
    # page-local copies were identical to the values above and were deleted
    # once this owner existed -- which is why the move cannot restyle the two
    # accepted read-only surfaces: nothing else matches the selector, so
    # neither order nor specificity has anything to resolve against.
    duplicates = [
        path.name
        for path in (ROOT / "templates").rglob("*.html")
        if re.search(r"\.form-fieldset\s*\{", path.read_text(encoding="utf-8"))
    ]
    assert duplicates == [], f"page-local copies of .form-fieldset are back: {duplicates}"
    assert len(re.findall(r"\n\.form-fieldset\s*\{", css)) == 1

    # Companions that genuinely cannot be hoisted stay page-local, untouched:
    # the bare-disabled guard (forbidden here by UI-B10) and the compound-card
    # .is-off-chunk cancellation, which is editing-affordance semantics.
    for reference in (ATIVIDADE_FORM, VERSAO_FORM):
        source = reference.read_text(encoding="utf-8")
        assert ".form-fieldset[disabled]{ opacity:1; }" in source, reference.name
        assert (
            '.form-fieldset[disabled][aria-readonly="true"] .is-off-chunk{ opacity:1; }'
            in source
        ), reference.name

    # Only the geometry reset is hoisted: UI-B10 forbids this stylesheet from
    # keying on a bare disabled fieldset, so that companion stays page-local.
    rules_only = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    assert not re.search(r"\.form-fieldset\[disabled\]\s*\{", rules_only), (
        "a bare disabled-fieldset rule entered the shared stylesheet"
    )

    # And the course form still declares no CSS of its own.
    assert not re.search(r"<style[^>]*>", EDIT_FORM.read_text(encoding="utf-8"), re.I)
