"""UI-C01 -- Matrizes de Atividades: Ver follows the shared read-only contract.

The defect: the list's "Ver" and "Editar" carried the SAME url, so for any
account allowed to edit, Ver *was* the editor -- editable white fields, the
transfer controls, the version modal and a working Salvar that persisted.

Ver is now the same template and the same GET route with ``?view=1`` (the
idiom Cursos / Atividades already use), rendered through:

* the shared READ-ONLY REGION contract (``fieldset.form-fieldset`` with
  ``disabled aria-readonly="true"``, painted by components/form.css);
* no mutation-only controls or JS writers at all (omitted, not disabled);
* the shared ``detail_header`` Back action and no footer.

Editar keeps every mutation affordance and its accepted Save/Cancel footer.
"""
from __future__ import annotations

import html as html_module
import re
import uuid
from pathlib import Path

import pytest

import main
from app.user_accounts import create_usuario_with_access_level
from tests.canonical_matrix_test_support import current_version_id, login_admin, seed_matrix_graph
from tests.session_support import stamp_auth_version
from tests.versioned_test_support import isolated_versioned_app_env

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "admin_matriz_form.html"
FORM_CSS = ROOT / "static" / "css" / "components" / "form.css"

TABS = ("dados", "aac", "aea")

# Client-side writers of the composition. None may even be defined in Ver.
MUTATION_JS_HOOKS = (
    "function moveItems(",
    "function syncHiddenInputs(",
    "function openVersionModal(",
    "querySelectorAll('[data-move]')",
    "[data-open-version-modal]",
)


def _matrix_state(conn, matrix_id: int):
    row = conn.execute("SELECT * FROM matrizes_atividades WHERE id=?", (matrix_id,)).fetchone()
    links = conn.execute(
        """SELECT matriz_id, atividade_base_id, atividade_versao_id
             FROM matriz_atividade_versao_item WHERE matriz_id=?
            ORDER BY atividade_base_id""",
        (matrix_id,),
    ).fetchall()
    return tuple(row), [tuple(link) for link in links]


@pytest.fixture(scope="module")
def pages(tmp_path_factory):
    """One matrix, rendered in Ver and in Editar for every tab, plus the list."""
    tmp_path = tmp_path_factory.mktemp("ui-c01")
    with isolated_versioned_app_env(tmp_path, "ui-c01.db") as env:
        with main.app.app_context():
            conn = main.get_db_connection()
            seed = seed_matrix_graph(conn, name="UI-C01 Ver Editar")
            conn.execute(
                """UPDATE matrizes_atividades
                      SET data_inicio_vigencia='2026-01-01', data_fim_vigencia='2026-12-31',
                          descricao='Descricao UI-C01'
                    WHERE id=?""",
                (seed["matrix_id"],),
            )
            conn.commit()
            before = _matrix_state(conn, seed["matrix_id"])
        login_admin(env["client"])

        rendered = {"seed": seed}
        listing = env["client"].get("/admin/matrizes")
        assert listing.status_code == 200
        rendered["list"] = listing.get_data(as_text=True)
        for tab in TABS:
            for mode, suffix in (("view", "&view=1"), ("edit", "")):
                response = env["client"].get(
                    f"/admin/editar_matriz/{seed['matrix_id']}?tab={tab}{suffix}"
                )
                assert response.status_code == 200, (mode, tab, response.status_code)
                rendered[(mode, tab)] = html_module.unescape(response.get_data(as_text=True))

        with main.app.app_context():
            rendered["after_get"] = _matrix_state(main.get_db_connection(), seed["matrix_id"])
        rendered["before"] = before
        yield rendered


def _fieldset_attrs(html: str) -> str:
    match = re.search(r'<fieldset class="form-fieldset"([^>]*)>', html)
    assert match, "the Dados form lost its fieldset"
    return match.group(1).strip()


def _dados_form(html: str) -> str:
    start = html.index('<form method="POST">')
    return html[start: html.index("</form>", start)]


# --------------------------------------------------------------------- list

def test_list_ver_and_editar_are_different_urls(pages):
    matrix_id = pages["seed"]["matrix_id"]
    row = re.search(rf'data-matriz-id="{matrix_id}"[^>]*', pages["list"]).group(0)
    view_url = re.search(r'data-view-url="([^"]*)"', row).group(1)
    edit_url = re.search(r'data-edit-url="([^"]*)"', row).group(1)
    assert view_url != edit_url, "Ver still opens the editor"
    assert "view=1" in view_url and "tab=dados" in view_url
    assert "view=" not in edit_url
    assert view_url.split("?")[0] == edit_url.split("?")[0] == f"/admin/editar_matriz/{matrix_id}"


# --------------------------------------------------------------------- Ver

def test_ver_declares_view_mode_in_title_and_shared_header(pages):
    for tab in TABS:
        view = pages[("view", tab)]
        assert "<title>Ver matriz de atividades" in view or "Ver matriz de atividades</title>" in view
        header = re.search(r'<header class="detail-header">(.*?)</header>', view, re.S)
        assert header, f"Ver {tab} does not use the shared detail_header"
        assert "Ver matriz de atividades" in header.group(1)
        back = re.search(r'<a class="btn detail-header__back" href="([^"]*)"', header.group(1))
        assert back and back.group(1) == "/admin/matrizes"
        assert view.count("detail-header__back") == 1


def test_ver_dados_uses_the_shared_read_only_region(pages):
    view = pages[("view", "dados")]
    attrs = _fieldset_attrs(view)
    assert "disabled" in attrs and 'aria-readonly="true"' in attrs, attrs

    # Every data control sits inside the region, so none needs its own marker.
    form = _dados_form(view)
    fieldset = form[form.index('<fieldset class="form-fieldset"'): form.index("</fieldset>")]
    for name in (
        "curso_id", "nome", "status", "data_inicio_vigencia", "data_fim_vigencia",
        "horas_aac_obrigatorias", "horas_extensao_obrigatorias", "descricao",
    ):
        assert f'name="{name}"' in fieldset, name
    assert "readonly aria-readonly" not in form


def test_ver_has_no_save_and_no_footer(pages):
    for tab in TABS:
        view = pages[("view", tab)]
        assert 'type="submit"' not in view, tab
        assert "form-actions" not in view, f"Ver {tab} still renders a footer"
        assert ">Salvar" not in view and "Salvar alterações" not in view
        assert ">Cancelar</a>" not in view


@pytest.mark.parametrize("tab", ["aac", "aea"])
def test_ver_composition_renders_no_mutation_controls(pages, tab):
    view = pages[("view", tab)]
    assert 'data-transfer-root data-readonly="1"' in view
    assert '<form method="POST" class="matriz-transfer-form"' not in view
    for forbidden in (
        "data-move=",
        'data-side="available"',
        'data-side="selected"',
        'name="selected_activity_ids"',
        'data-role="selected-hidden-inputs"',
        "data-open-version-modal",
        'id="matriz-version-modal"',
        'id="matriz-version-form"',
        'aria-label="Mover atividades entre as listas"',
        'class="matriz-tab-help"',
    ):
        assert forbidden not in view, f"Ver {tab} still carries {forbidden}"
    # An editor in Ver is not told their access is limited -- it is not.
    assert "Seu acesso a esta Matriz é somente para consulta." not in view


def test_ver_still_shows_the_composition(pages):
    view = pages[("view", "aac")]
    seed = pages["seed"]
    selected = view[view.index('data-role="selected-list"'): view.index('data-empty="selected"')]
    assert f'data-activity-id="{seed["v1"]}"' in selected
    assert 'class="version-identifier version-badge"' in selected
    assert "UI-C01 Ver Editar activity" in selected


def test_ver_tabs_stay_in_ver(pages):
    matrix_id = pages["seed"]["matrix_id"]
    for tab in TABS:
        view = pages[("view", tab)]
        for target in TABS:
            assert f'href="/admin/editar_matriz/{matrix_id}?tab={target}&view=1"' in view, (tab, target)


@pytest.mark.parametrize("tab", TABS)
def test_ver_defines_no_mutation_js(pages, tab):
    view = pages[("view", tab)]
    for hook in MUTATION_JS_HOOKS:
        assert hook not in view, f"Ver {tab} still defines {hook}"


def test_rendering_ver_leaves_the_matrix_unchanged(pages):
    assert pages["after_get"] == pages["before"]


# ------------------------------------------------------------------ Editar

def test_editar_dados_stays_editable_with_save_and_cancel(pages):
    edit = pages[("edit", "dados")]
    assert _fieldset_attrs(edit) == "", "the edit form is not editable"
    assert "Editar matriz de atividades" in edit
    actions = edit[edit.index('<div class="form-actions center">'):]
    assert 'href="/admin/matrizes">Voltar</a>' in actions
    assert 'type="submit"' in actions and "Salvar alterações" in actions


def test_ver_and_editar_share_the_same_fields(pages):
    def fields(html):
        form = _dados_form(html)
        return (
            re.findall(r'<label class="row-label">([^<]+)</label>', form),
            re.findall(r'name="([^"]+)"', form),
        )

    assert fields(pages[("view", "dados")]) == fields(pages[("edit", "dados")])


@pytest.mark.parametrize("tab", ["aac", "aea"])
def test_editar_composition_keeps_every_mutation_control(pages, tab):
    edit = pages[("edit", tab)]
    assert '<form method="POST" class="matriz-transfer-form" data-transfer-root data-readonly="0">' in edit
    for move in ('data-move=">"', 'data-move=">>"', 'data-move="<"', 'data-move="<<"'):
        assert move in edit, move
    assert 'data-role="selected-hidden-inputs"' in edit
    assert '<span class="btn-label">Salvar</span>' in edit
    assert ">Cancelar</a>" in edit
    for hook in ("function moveItems(", "function syncHiddenInputs("):
        assert hook in edit, hook


def test_editar_aac_keeps_selection_and_version_modal(pages):
    edit = pages[("edit", "aac")]
    assert 'data-side="selected"' in edit
    assert 'name="selected_activity_ids"' in edit
    assert "data-open-version-modal" in edit
    assert 'id="matriz-version-form"' in edit
    assert "function openVersionModal(" in edit


def test_editar_tabs_do_not_carry_view_mode(pages):
    matrix_id = pages["seed"]["matrix_id"]
    edit = pages[("edit", "aac")]
    for target in TABS:
        assert f'href="/admin/editar_matriz/{matrix_id}?tab={target}"' in edit
    assert "view=1" not in edit


# ------------------------------------------------------------------ backend

def test_editar_still_persists(tmp_path):
    with isolated_versioned_app_env(tmp_path, "ui-c01-edit.db") as env:
        with main.app.app_context():
            seed = seed_matrix_graph(main.get_db_connection(), name="UI-C01 edit persists")
        login_admin(env["client"])
        response = env["client"].post(
            f"/admin/editar_matriz/{seed['matrix_id']}?tab=aac",
            data={"active_tab": "aac", "selected_activity_ids": [str(seed["v2"])]},
        )
        assert response.status_code == 302
        with main.app.app_context():
            assert current_version_id(main.get_db_connection(), seed) == seed["v2"]


def test_entering_through_ver_does_not_bypass_write_rbac(tmp_path):
    with isolated_versioned_app_env(tmp_path, "ui-c01-rbac.db") as env:
        with main.app.app_context():
            conn = main.get_db_connection()
            seed = seed_matrix_graph(conn, name="UI-C01 consultive")
            user_id = create_usuario_with_access_level(
                conn,
                "UI-C01 consultive",
                f"ui-c01-{uuid.uuid4().hex[:8]}@example.com",
                main.hash_password("ui-c01-test"),
                "admin",
                "consultivo",
                credential_state="personal",
            ).lastrowid
            conn.commit()
            before = _matrix_state(conn, seed["matrix_id"])
        with env["client"].session_transaction() as session:
            session.update(user_id=user_id, user_type="admin", user_name="UI-C01 consultive")
            stamp_auth_version(session)

        page = env["client"].get(f"/admin/editar_matriz/{seed['matrix_id']}?tab=dados&view=1")
        assert page.status_code == 200
        assert 'disabled aria-readonly="true"' in page.get_data(as_text=True)

        for suffix in ("&view=1", ""):
            denied = env["client"].post(
                f"/admin/editar_matriz/{seed['matrix_id']}?tab=aac{suffix}",
                data={"active_tab": "aac", "selected_activity_ids": [str(seed["v2"])]},
            )
            assert denied.status_code == 302
            assert denied.headers["Location"].endswith("/admin/dashboard")
            denied = env["client"].post(
                f"/admin/matrizes/{seed['matrix_id']}/atividades/{seed['v1']}/nova-versao",
                data={"active_tab": "aac", "versao_id": str(seed["v2"])},
            )
            assert denied.status_code == 302
            assert denied.headers["Location"].endswith("/admin/dashboard")
        with main.app.app_context():
            assert _matrix_state(main.get_db_connection(), seed["matrix_id"]) == before

        # The account-limited notice still reaches the editor URL for viewers.
        page = env["client"].get(f"/admin/editar_matriz/{seed['matrix_id']}?tab=aac")
        assert "Seu acesso a esta Matriz é somente para consulta." in page.get_data(as_text=True)


# ----------------------------------------------------------------------- DS

def test_read_only_appearance_is_owned_by_the_shared_stylesheet():
    template = TEMPLATE.read_text(encoding="utf-8")
    css = FORM_CSS.read_text(encoding="utf-8")

    rule = re.search(
        r'fieldset\[disabled\]\[aria-readonly="true"\] \.field-card[^{]*\{([^}]*)\}', css, re.S
    )
    assert rule and "background:var(--field-readonly-bg)" in rule.group(1)

    # No page-local copy or imitation of the contract.
    style = re.search(r"<style>(.*?)</style>", template, re.S).group(1)
    assert not re.search(r"\.form-fieldset\s*[\{\[]", template)
    assert "--field-readonly-bg" not in style
    assert "is-readonly" not in style, "page-local read-only styling for the composition is back"
    assert not re.search(r"fieldset|\[disabled\]|\[readonly\]", style)
    assert not re.search(r"matriz-view|view-readonly", template)
    assert '<fieldset class="form-fieldset" {% if readonly %}disabled aria-readonly="true"{% endif %}>' in template
