"""Admin -> Reportes: the actions menu's batch selection, in a real Chromium.

"Selecionar tudo" toggles between selecting every visible report card and
clearing the selection; a search or filter decides what is visible, the
counter and the actions follow the selection. No test here confirms a
deletion: the delete action is only inspected, never completed.
"""
from __future__ import annotations

import json

import pytest

import main
from tests.canonical_matrix_test_support import login_admin
from tests.versioned_test_support import isolated_versioned_app_env

cdp = pytest.importorskip("tests.cdp_browser_support")
BINARY = cdp.find_chromium()
browser_only = pytest.mark.skipif(BINARY is None, reason="no Chromium binary for the browser harness")
SHIFT = 8  # CDP Input modifier bit
EMPTY_HINT = "Selecione uma ou mais linhas para habilitar as ações."


def _seed_reports(conn):
    """Six reports; odd ones carry "grupox" in the title, so a search for it
    leaves every other card visible."""
    main.ensure_reportes_table(conn)
    ids = {}
    for number in range(1, 7):
        tag = "grupox" if number % 2 else "outro"
        usuario_id = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, 'x', 'aluno', 'usuario')",
            (f"Aluno Lote {number:02d}", f"lote{number:02d}@example.test"),
        ).lastrowid
        aluno_id = conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, status) VALUES (?, ?, ?, ?, 'Ativo')",
            (usuario_id, f"Aluno Lote {number:02d}", f"LOTE-{number:02d}", f"lote{number:02d}@example.test"),
        ).lastrowid
        ids[number] = conn.execute(
            "INSERT INTO reportes (aluno_id, titulo, descricao, categoria, status) VALUES (?, ?, 'x', 'Bug na plataforma', 'Novo')",
            (aluno_id, f"Assunto {tag} {number:02d}"),
        ).lastrowid
    return ids


@pytest.fixture
def page(tmp_path):
    with isolated_versioned_app_env(tmp_path, "reportes-selection.db") as environment:
        with main.app.app_context():
            conn = main.get_db_connection()
            ids = _seed_reports(conn)
            conn.commit()
        login_admin(environment["client"])
        session = cdp.BrowserSession(environment["client"], BINARY)
        session.ids = ids
        try:
            _open(session, "/admin/reportes")
            yield session
            assert session.evaluate("window.__errors") == []
            # Nothing was deleted: no confirmation was accepted, no POST was made.
            assert not [r for r in session.requests if r[0] == "POST"]
        finally:
            session.close()


def _open(session, path):
    """Load a page, record its script errors and decline every confirmation."""
    session.goto(path)
    session.evaluate(
        "window.__errors = []; window.addEventListener('error', e => window.__errors.push(String(e.message)));"
        " window.confirm = () => { window.__confirmed = (window.__confirmed || 0) + 1; return false; }; true"
    )


def _card(session, number):
    return f'#reportes-list [data-reporte-id="{session.ids[number]}"]'


def _selected(session):
    ids = session.evaluate(
        "Array.from(document.querySelectorAll('#reportes-list .impresso-card.selected')).map(r => Number(r.dataset.reporteId))"
    )
    by_id = {value: key for key, value in session.ids.items()}
    return sorted(by_id[value] for value in ids)


def _text_of(session, selector):
    return session.evaluate("document.querySelector(%s).textContent.trim()" % json.dumps(selector))


def _menu_open(session):
    return not session.evaluate("document.querySelector('#reportes-actions-menu').hidden")


def _open_menu(session):
    if not _menu_open(session):
        session.click_in_view("#btn-reportes-actions")
    assert _menu_open(session)


def _select_all_item(session, *, expect_label):
    _open_menu(session)
    assert _text_of(session, "#reportes-action-select-all") == expect_label
    session.click("#reportes-action-select-all")
    session.pump(0.2)


def _menu_state(session):
    """Counter and actions as the administrator sees them in the open menu."""
    _open_menu(session)
    return {
        "label": _text_of(session, "#reportes-action-select-all"),
        "hint": _text_of(session, "#reportes-actions-hint"),
        "delete_disabled": session.evaluate("document.querySelector('#reportes-action-delete').disabled"),
    }


def _search(session, text):
    """Type into the search as a user does: clicking the field first, which
    also closes an open actions menu (reopening it re-reads the selection)."""
    session.click_in_view("#busca-reportes")
    session.evaluate(
        "(() => { const i = document.querySelector('#busca-reportes'); i.value = %s;"
        " i.dispatchEvent(new Event('input', {bubbles: true})); return true; })()" % json.dumps(text)
    )
    session.pump(0.1)


@browser_only
def test_select_all_selects_every_visible_card_then_clears(page):
    assert _menu_state(page) == {"label": "Selecionar tudo", "hint": EMPTY_HINT, "delete_disabled": True}
    _select_all_item(page, expect_label="Selecionar tudo")
    assert _selected(page) == [1, 2, 3, 4, 5, 6]
    assert _menu_state(page) == {
        "label": "Desselecionar", "hint": "6 reporte(s) selecionado(s).", "delete_disabled": False,
    }
    _select_all_item(page, expect_label="Desselecionar")
    assert _selected(page) == []
    assert _menu_state(page) == {"label": "Selecionar tudo", "hint": EMPTY_HINT, "delete_disabled": True}


@browser_only
def test_select_all_after_a_search_takes_only_the_visible_cards(page):
    _search(page, "grupox")
    _select_all_item(page, expect_label="Selecionar tudo")
    assert _selected(page) == [1, 3, 5]
    assert page.evaluate(
        "Array.from(document.querySelectorAll('#reportes-list .impresso-card.selected')).every(r => r.offsetParent !== null)"
    )
    assert _menu_state(page)["hint"] == "3 reporte(s) selecionado(s)."
    # Clearing the search shows the other cards again, unselected; the
    # selection no longer covers every visible card, so the item offers to
    # select them all again.
    _search(page, "")
    assert _selected(page) == [1, 3, 5]
    assert _menu_state(page)["label"] == "Selecionar tudo"
    _select_all_item(page, expect_label="Selecionar tudo")
    assert _selected(page) == [1, 2, 3, 4, 5, 6]


@browser_only
def test_select_all_under_a_filter_and_a_search_takes_only_what_both_leave(page):
    _open(page, "/admin/reportes?titulo=grupox")
    assert page.evaluate("document.querySelectorAll('#reportes-list [data-reporte-id]').length") == 3
    _select_all_item(page, expect_label="Selecionar tudo")
    assert _selected(page) == [1, 3, 5]
    _search(page, "lote 03")
    assert _selected(page) == [3]
    assert _menu_state(page) == {
        "label": "Desselecionar", "hint": "1 reporte(s) selecionado(s).", "delete_disabled": False,
    }


@browser_only
def test_cards_hidden_after_selection_leave_it_and_the_counter(page):
    _select_all_item(page, expect_label="Selecionar tudo")
    _search(page, "assunto outro")
    assert _selected(page) == [2, 4, 6]
    assert _menu_state(page) == {
        "label": "Desselecionar", "hint": "3 reporte(s) selecionado(s).", "delete_disabled": False,
    }
    _search(page, "nenhum reporte assim")
    assert _selected(page) == []
    assert _menu_state(page) == {"label": "Selecionar tudo", "hint": EMPTY_HINT, "delete_disabled": True}


def _click_card(session, number, *, shift=False):
    session.click_in_view(_card(session, number) + " .cell:nth-child(2)", modifiers=SHIFT if shift else 0)


def _modal_open(session):
    return not session.evaluate("document.getElementById('reporte-modal').hidden")


def _mouse(session, x, y, kind, buttons=1):
    session.call("Input.dispatchMouseEvent", {
        "type": kind, "x": x, "y": y, "button": "left", "buttons": buttons, "clickCount": 1,
    })


def _box(session, selector):
    box = session.evaluate(
        "(() => { const el = document.querySelector(%s); el.scrollIntoView({block: 'center'});"
        " const r = el.getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2,"
        " left: r.left, right: r.right}; })()" % json.dumps(selector)
    )
    session.pump(0.3)
    return box


@browser_only
def test_a_click_toggles_one_card_and_shift_extends_without_opening_the_detail(page):
    _click_card(page, 2)
    assert _selected(page) == [2]
    assert not _modal_open(page)
    assert _menu_state(page)["hint"] == "1 reporte(s) selecionado(s)."
    page.click_in_view("#btn-reportes-actions")  # close the menu again
    _click_card(page, 2)
    assert _selected(page) == []
    _click_card(page, 1)
    _click_card(page, 4, shift=True)
    assert _selected(page) == [1, 2, 3, 4]
    assert page.evaluate("window.getSelection().toString()") == ""
    assert not _modal_open(page)
    # A click outside the list clears it; after a search a Shift range then
    # runs over the visible cards only.
    page.click_in_view("h1.main-title")
    assert _selected(page) == []
    _search(page, "grupox")
    _click_card(page, 1)
    _click_card(page, 5, shift=True)
    assert _selected(page) == [1, 3, 5]
    assert _menu_state(page) == {
        "label": "Desselecionar", "hint": "3 reporte(s) selecionado(s).", "delete_disabled": False,
    }


@browser_only
def test_dragging_to_copy_text_neither_selects_nor_opens_the_card(page):
    title = _box(page, _card(page, 3) + " .cell:nth-child(5)")
    _mouse(page, title["left"] + 1, title["y"], "mousePressed")
    _mouse(page, (title["left"] + title["right"]) / 2, title["y"], "mouseMoved")
    _mouse(page, title["right"] - 1, title["y"], "mouseMoved")
    _mouse(page, title["right"] - 1, title["y"], "mouseReleased", buttons=0)
    page.pump(0.1)
    assert "Assunto" in page.evaluate("window.getSelection().toString()")
    assert _selected(page) == []
    assert not _modal_open(page)


@browser_only
def test_the_detail_still_opens_from_the_row_bar_and_the_keyboard(page):
    card = _box(page, _card(page, 2) + " .cell:nth-child(2)")
    _mouse(page, card["x"], card["y"], "mouseMoved", buttons=0)
    page.pump(0.2)
    assert page.evaluate("document.getElementById('pedido-actions-float').classList.contains('is-visible')")
    page.click('#pedido-actions-float [data-action="view"]')
    page.pump(0.2)
    assert _modal_open(page)
    assert _text_of(page, "#rm-title-text") == "Assunto outro 02"
    page.click("#reporte-modal-close")
    page.pump(0.1)
    assert not _modal_open(page)
    page.evaluate("document.querySelector(%s).focus(); true" % json.dumps(_card(page, 4)))
    page.press_enter()
    page.pump(0.2)
    assert _modal_open(page)
    assert _text_of(page, "#rm-title-text") == "Assunto outro 04"


@browser_only
def test_delete_is_offered_for_the_selection_but_not_completed_here(page):
    _search(page, "grupox")
    _select_all_item(page, expect_label="Selecionar tudo")
    _open_menu(page)
    page.click("#reportes-action-delete")
    page.pump(0.2)
    # The bulk delete asked about exactly the visible selection; the stubbed
    # confirmation declined, so the fixture's no-POST check also holds.
    assert page.evaluate("window.__confirmed") == 1
    assert _selected(page) == [1, 3, 5]
