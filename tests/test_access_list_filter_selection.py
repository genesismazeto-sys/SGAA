"""Acesso list: the Situação filter and the shared row selection.

Fictitious accounts in an isolated database only; no mail is sent.

* The filter uses the access lifecycle derived by app/access_onboarding.py --
  never alunos.status -- and is applied before pagination, so totals and pages
  are the filtered ones. Revoked accounts stay out of the list unless the
  filter names Revogado, and then they are listed read-only.
* static/js/toolbar-filters.js selects only rows the administrator can see:
  a Shift range, "Selecionar tudo" and the counter follow the rows visible now,
  a row hidden by the search leaves the selection, and Shift+click does not
  drag a native text selection across the list (proved in real Chromium).
"""
from __future__ import annotations

import json
import re
from contextlib import contextmanager

import pytest
from flask import template_rendered

import main
from app import access_onboarding
from app.access_onboarding import ACCESS_STATUSES, filter_usuario_ids_by_access_status
from app.password_tokens import issue_password_token, mark_password_token_sent
from app.status_presentation import (
    ACCESS_STATUS_ATIVO,
    ACCESS_STATUS_DISPONIBILIZADO,
    ACCESS_STATUS_EXPIRADO,
    ACCESS_STATUS_PENDENTE,
    ACCESS_STATUS_REVOGADO,
)
from app.user_accounts import (
    create_usuario_pending,
    create_usuario_with_access_level,
    set_usuario_access_active,
)
from tests.canonical_matrix_test_support import login_admin
from tests.versioned_test_support import isolated_versioned_app_env


def _pending(conn, nome, email):
    return int(create_usuario_pending(conn, nome, email, "admin").lastrowid)


def _sent_link(conn, usuario_id, *, expired=False):
    _, token_id = issue_password_token(conn, usuario_id, "first_access")
    mark_password_token_sent(conn, token_id)
    if expired:
        conn.execute(
            "UPDATE senha_tokens SET expires_at='2020-01-01 00:00:00',"
            " created_at='2019-12-29 00:00:00', sent_at='2019-12-29 00:00:00' WHERE id=?",
            (token_id,),
        )


def _seed_states(conn):
    """Twelve Pendente, two Disponibilizado, one each of the other states."""
    ids = {}
    for number in range(1, 13):
        ids[f"pendente{number:02d}"] = _pending(conn, f"Filtro Pendente {number:02d}", f"pend{number:02d}@example.test")
    for letter in "AB":
        ids[f"disp{letter}"] = _pending(conn, f"Filtro Disponivel {letter}", f"disp{letter.lower()}@example.test")
        _sent_link(conn, ids[f"disp{letter}"])
    ids["expirado"] = _pending(conn, "Filtro Expirado A", "exp@example.test")
    _sent_link(conn, ids["expirado"], expired=True)
    ids["ativo"] = int(create_usuario_with_access_level(
        conn, "Filtro Ativo A", "ativo@example.test", "test-hash", "admin", "consultivo",
        credential_state="personal",
    ).lastrowid)
    ids["revogado"] = _pending(conn, "Filtro Revogado A", "revog@example.test")
    set_usuario_access_active(conn, ids["revogado"], False)
    return ids


@pytest.fixture
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "access-filter.db") as environment:
        with main.app.app_context():
            conn = main.get_db_connection()
            ids = _seed_states(conn)
            conn.commit()
        login_admin(environment["client"])
        yield {**environment, "ids": ids}


def _html(env, query):
    response = env["client"].get("/admin/acesso" + query)
    assert response.status_code == 200, response.status_code
    return response.get_data(as_text=True)


def _names(html):
    return re.findall(r'data-user-nome="([^"]*)"', html)


@contextmanager
def _render_context():
    """The context the Acesso list was rendered with (page, total_pages, total)."""
    seen = []

    def record(sender, template, context, **extra):
        if template.name == "admin_acesso.html":
            seen.append(context)

    template_rendered.connect(record, main.app)
    try:
        yield seen
    finally:
        template_rendered.disconnect(record, main.app)


def _page(env, query):
    """(names, (page, total_pages, total)) of one Acesso list request."""
    with _render_context() as seen:
        html = _html(env, query)
    context = seen[-1]
    return _names(html), (context["page"], context["total_pages"], context["total"])


def _users_payload(html):
    raw = re.search(r'<script id="access-users-data" type="application/json">(.*?)</script>', html, re.S)
    return json.loads(raw.group(1))


# --------------------------------------------------------------------------
# Server side: the filter, before pagination
# --------------------------------------------------------------------------


def test_the_filter_offers_the_five_lifecycle_states_in_order(env):
    html = _html(env, "")
    schema = json.loads(re.search(r'<script id="filter-schema-data" type="application/json">(.*?)</script>', html, re.S).group(1))
    situacao = next(group for group in schema if group["param"] == "situacao")
    assert situacao["label"] == "Situação"
    assert situacao["type"] == "multi_select"
    assert [entry["value"] for entry in situacao["values"]] == [
        "Pendente", "Disponibilizado", "Expirado", "Ativo", "Revogado",
    ]
    assert list(ACCESS_STATUSES) == [entry["value"] for entry in situacao["values"]]


def test_filter_is_applied_before_pagination(env):
    names, paging = _page(env, "?nome=Filtro&per_page=5&page=1")
    # Alphabetically the first page holds Ativo, Disponivel A/B, Expirado and
    # one Pendente: filtering only this page would leave a single row.
    assert names == [
        "Filtro Ativo A", "Filtro Disponivel A", "Filtro Disponivel B",
        "Filtro Expirado A", "Filtro Pendente 01",
    ]
    assert paging == (1, 4, 16)

    names, paging = _page(env, "?nome=Filtro&situacao=Pendente&per_page=5&page=1")
    assert names == [f"Filtro Pendente {n:02d}" for n in range(1, 6)]
    assert paging == (1, 3, 12)
    names, paging = _page(env, "?nome=Filtro&situacao=Pendente&per_page=5&page=2")
    assert names == [f"Filtro Pendente {n:02d}" for n in range(6, 11)]
    names, paging = _page(env, "?nome=Filtro&situacao=Pendente&per_page=5&page=3")
    assert names == ["Filtro Pendente 11", "Filtro Pendente 12"]
    assert paging == (3, 3, 12)
    names, paging = _page(env, "?nome=Filtro&situacao=Pendente&per_page=5&page=4")
    assert names == [] and paging == (4, 3, 12)
    # Without pagination the whole filtered list renders, with the same total.
    names, paging = _page(env, "?nome=Filtro&situacao=Pendente")
    assert len(names) == 12 and paging[2] == 12


def test_every_listed_row_carries_the_requested_state(env):
    expected = {
        ACCESS_STATUS_DISPONIBILIZADO: ["Filtro Disponivel A", "Filtro Disponivel B"],
        ACCESS_STATUS_EXPIRADO: ["Filtro Expirado A"],
        ACCESS_STATUS_ATIVO: ["Filtro Ativo A"],
        ACCESS_STATUS_REVOGADO: ["Filtro Revogado A"],
    }
    for status, names in expected.items():
        html = _html(env, f"?nome=Filtro&situacao={status}")
        assert _names(html) == names, status
        pills = re.findall(r'status-badge status-pill status-\w+">([^<]+)</span>', html)
        assert pills == [status] * len(names), (status, pills)


def test_multiple_values_are_a_union_paged_as_one_list(env):
    names, paging = _page(env, "?nome=Filtro&situacao=Disponibilizado&situacao=Expirado&per_page=2&page=1")
    assert names == ["Filtro Disponivel A", "Filtro Disponivel B"]
    assert paging == (1, 2, 3)
    names, paging = _page(env, "?nome=Filtro&situacao=Disponibilizado&situacao=Expirado&per_page=2&page=2")
    assert names == ["Filtro Expirado A"]
    assert paging == (2, 2, 3)
    # The comma form the shared filter parser also accepts.
    names, _ = _page(env, "?nome=Filtro&situacao=Disponibilizado,Expirado")
    assert names == ["Filtro Disponivel A", "Filtro Disponivel B", "Filtro Expirado A"]


def test_values_are_matched_case_insensitively_and_unknown_values_match_nothing(env):
    assert _names(_html(env, "?nome=Filtro&situacao=ativo")) == ["Filtro Ativo A"]
    html = _html(env, "?nome=Filtro&situacao=Inexistente")
    assert _names(html) == []
    assert "Nenhum acesso encontrado." in html
    # An unknown value next to a known one does not widen anything.
    assert _names(_html(env, "?nome=Filtro&situacao=Ativo&situacao=xyz")) == ["Filtro Ativo A"]


def test_revoked_accounts_are_listed_only_when_requested_and_read_only(env):
    default = _names(_html(env, "?nome=Filtro"))
    assert "Filtro Revogado A" not in default and len(default) == 16
    # Any filter that does not name Revogado keeps the default policy.
    for status in (ACCESS_STATUS_PENDENTE, ACCESS_STATUS_ATIVO):
        assert "Filtro Revogado A" not in _names(_html(env, f"?nome=Filtro&situacao={status}"))

    html = _html(env, "?nome=Filtro&situacao=Revogado&situacao=Ativo")
    assert _names(html) == ["Filtro Ativo A", "Filtro Revogado A"]
    revoked_id = env["ids"]["revogado"]
    row = re.search(rf'<div class="impresso-card[^"]*" role="listitem"[^>]*data-user-id="{revoked_id}"[^>]*>', html).group(0)
    assert row.startswith('<div class="impresso-card toolbar-selection-disabled"')
    for attribute in ("data-email-url", "data-delete-url", "data-reset-url"):
        assert f'{attribute}=""' in row, attribute
    assert 'data-user-revoked="1"' in row
    payload = _users_payload(html)
    assert payload[str(revoked_id)]["isRevoked"] is True
    assert payload[str(revoked_id)]["canApplyDefaultPassword"] is False
    active = re.search(rf'<div class="impresso-card[^"]*" role="listitem"[^>]*data-user-id="{env["ids"]["ativo"]}"[^>]*>', html).group(0)
    assert "toolbar-selection-disabled" not in active and 'data-email-url="/admin/acesso/' in active
    assert 'data-user-revoked="0"' in active


def test_listing_revoked_accounts_still_sends_them_no_mail(env, monkeypatch):
    import app.password_email as password_email

    sent = []
    monkeypatch.setattr(password_email, "send_text_email", lambda conn, message: sent.append(message))
    _html(env, "?situacao=Revogado")
    response = env["client"].post(
        "/admin/acesso/email-lote", json={"action": "preview", "ids": [env["ids"]["revogado"]]}
    )
    assert response.json["targets"][0]["category"] == "ineligible"
    single = env["client"].post(f"/admin/acesso/{env['ids']['revogado']}/senha-por-email")
    assert single.status_code == 302
    assert not sent


def test_situacao_combines_with_nome_nivel_perfil_and_turma(env):
    client = env["client"]
    # A student access in Turma 1, created through the public form: blank
    # password -> pending.
    response = client.post("/admin/acesso/salvar", data={
        "nome": "Filtro Aluno Turma", "email": "aluno.turma@example.test", "nivel_acesso": "usuario",
        "matricula": "FT-001", "status": "Ativo", "turma_id": "1",
    })
    assert response.status_code == 302
    assert _names(_html(env, "?nome=Filtro&situacao=Pendente&turma_id=1")) == ["Filtro Aluno Turma"]
    assert _names(_html(env, "?nome=Filtro&situacao=Pendente&turma_id=2")) == []
    assert _names(_html(env, "?nome=Filtro&situacao=Ativo&turma_id=1")) == []
    assert _names(_html(env, "?nome=Filtro&situacao=Pendente&tipo=aluno")) == ["Filtro Aluno Turma"]
    assert _names(_html(env, "?nome=Filtro&situacao=Ativo&nivel=consultivo")) == ["Filtro Ativo A"]
    assert _names(_html(env, "?nome=Filtro&situacao=Pendente&nivel=consultivo")) == []
    assert _names(_html(env, "?nome=Pendente%201&situacao=Pendente")) == [
        "Filtro Pendente 10", "Filtro Pendente 11", "Filtro Pendente 12",
    ]
    # Sorting applies to the filtered list too.
    assert _names(_html(env, "?nome=Filtro%20Disp&situacao=Disponibilizado&s=nome&dir=desc")) == [
        "Filtro Disponivel B", "Filtro Disponivel A",
    ]


def test_owner_filter_keeps_order_dedupes_and_resolves_in_batches(env, monkeypatch):
    ids = env["ids"]
    monkeypatch.setattr(access_onboarding, "_FILTER_BATCH_SIZE", 2)
    calls = []
    original = access_onboarding.access_status_map

    def recording(conn, usuario_ids):
        calls.append(list(usuario_ids))
        return original(conn, usuario_ids)

    monkeypatch.setattr(access_onboarding, "access_status_map", recording)
    order = [ids["expirado"], ids["pendente03"], ids["ativo"], ids["pendente01"], ids["pendente03"], ids["revogado"]]
    with main.app.app_context():
        conn = main.get_db_connection()
        assert filter_usuario_ids_by_access_status(conn, order, {ACCESS_STATUS_PENDENTE}) == [
            ids["pendente03"], ids["pendente01"],
        ]
        assert filter_usuario_ids_by_access_status(conn, order, {ACCESS_STATUS_REVOGADO, ACCESS_STATUS_EXPIRADO}) == [
            ids["expirado"], ids["revogado"],
        ]
        assert filter_usuario_ids_by_access_status(conn, order, {None, "pendente"}) == []
        assert filter_usuario_ids_by_access_status(conn, [], {ACCESS_STATUS_PENDENTE}) == []
    assert all(len(batch) <= 2 for batch in calls) and len(calls) >= 3


# --------------------------------------------------------------------------
# Real Chromium: selection follows what is visible
# --------------------------------------------------------------------------

cdp = pytest.importorskip("tests.cdp_browser_support")
BINARY = cdp.find_chromium()
browser_only = pytest.mark.skipif(BINARY is None, reason="no Chromium binary for the browser harness")
SHIFT = 8  # CDP Input modifier bit


@pytest.fixture
def page(tmp_path):
    with isolated_versioned_app_env(tmp_path, "access-selection.db") as environment:
        ids = {}
        with main.app.app_context():
            conn = main.get_db_connection()
            # Odd rows carry "grupox" in the e-mail, so a search for it leaves
            # every other row visible -- the gaps a stale index used to sweep.
            for number in range(1, 9):
                tag = "grupox" if number % 2 else "outro"
                ids[number] = _pending(conn, f"Faixa {number:02d}", f"faixa{number:02d}.{tag}@example.test")
            ids[9] = _pending(conn, "Faixa 09", "faixa09.grupox@example.test")
            set_usuario_access_active(conn, ids[9], False)
            conn.commit()
        login_admin(environment["client"])
        session = cdp.BrowserSession(environment["client"], BINARY)
        session.ids = ids
        try:
            yield session
        finally:
            session.close()


def _center(session, selector):
    box = session.evaluate(
        "(() => { const el = document.querySelector(%s); el.scrollIntoView({block: 'center'});"
        " const r = el.getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2,"
        " left: r.left, right: r.right}; })()" % json.dumps(selector)
    )
    session.pump(0.3)  # let the scroll event settle before the press
    return box


def _mouse(session, x, y, kind, modifiers=0, buttons=1):
    session.call("Input.dispatchMouseEvent", {
        "type": kind, "x": x, "y": y, "button": "left", "buttons": buttons, "clickCount": 1,
        "modifiers": modifiers,
    })


def _click_row(session, number, *, shift=False):
    session.click_in_view(
        f'#acesso-list [data-user-id="{session.ids[number]}"] .cell:nth-child(2)',
        modifiers=SHIFT if shift else 0,
    )


def _selected(session):
    ids = session.evaluate(
        "Array.from(document.querySelectorAll('#acesso-list .impresso-card.selected')).map(r => Number(r.dataset.userId))"
    )
    by_id = {value: key for key, value in session.ids.items()}
    return sorted(by_id[value] for value in ids)


def _search(session, text):
    session.evaluate(
        "(() => { const i = document.querySelector('#busca-acesso'); i.value = %s;"
        " i.dispatchEvent(new Event('input', {bubbles: true})); return true; })()" % json.dumps(text)
    )
    session.pump(0.1)


def _hint(session):
    return session.evaluate("document.querySelector('#access-actions-hint').textContent.trim()")


def _select_all(session, *, expect_label="Selecionar tudo"):
    """Use the actions menu's select-all item, opening the menu only if closed."""
    if session.evaluate("document.querySelector('#access-actions-menu').hidden"):
        session.click_in_view("#btn-acesso-actions")
    assert session.evaluate("!document.querySelector('#access-actions-menu').hidden")
    assert _text_of(session, "#access-action-select-all") == expect_label
    session.click("#access-action-select-all")
    session.pump(0.2)


def _text_of(session, selector):
    return session.evaluate("document.querySelector(%s).textContent.trim()" % json.dumps(selector))


def _clear_by_outside_click(session):
    session.click_in_view("h1.main-title")


def _text_selection(session):
    return session.evaluate("window.getSelection().toString()")


@browser_only
def test_shift_range_after_search_selects_only_visible_rows(page):
    page.goto("/admin/acesso?nome=Faixa")
    _search(page, "grupox")
    _click_row(page, 1)
    _click_row(page, 7, shift=True)
    assert _selected(page) == [1, 3, 5, 7]
    assert _hint(page) == "4 acesso(s) selecionado(s)."
    # Reverse direction from a fresh anchor works on the same visible list.
    _clear_by_outside_click(page)
    assert _selected(page) == []
    _click_row(page, 5)
    _click_row(page, 1, shift=True)
    assert _selected(page) == [1, 3, 5]


@browser_only
def test_rows_hidden_by_a_new_search_leave_the_selection(page):
    page.goto("/admin/acesso?nome=Faixa")
    _search(page, "grupox")
    _select_all(page)
    assert _selected(page) == [1, 3, 5, 7]
    _search(page, "faixa03")
    assert _selected(page) == [3]
    assert _hint(page) == "1 acesso(s) selecionado(s)."
    # Clearing the search shows the rows again, but does not resurrect them.
    _search(page, "")
    assert _selected(page) == [3]
    # "Selecionar tudo" anchored row 1, which the search hid: that anchor was
    # dropped, so Shift+click 6 starts a new anchor there, and the next Shift
    # range runs over every row visible now.
    _click_row(page, 6, shift=True)
    assert _selected(page) == [3, 6]
    _click_row(page, 4, shift=True)
    assert _selected(page) == [3, 4, 5, 6]


@browser_only
def test_a_hidden_anchor_is_dropped_not_reused(page):
    page.goto("/admin/acesso?nome=Faixa")
    _click_row(page, 2)
    _search(page, "grupox")  # hides row 2, the anchor
    assert _selected(page) == []
    assert _hint(page) == "Selecione uma ou mais linhas para habilitar as ações."
    _click_row(page, 7, shift=True)
    assert _selected(page) == [7]


@browser_only
def test_select_all_takes_only_visible_eligible_rows(page):
    page.goto("/admin/acesso?nome=Faixa&situacao=Pendente&situacao=Revogado")
    assert page.evaluate("document.querySelectorAll('#acesso-list .toolbar-selection-disabled').length") == 1
    _select_all(page)
    assert _selected(page) == [1, 2, 3, 4, 5, 6, 7, 8]  # never the revoked row 9
    _select_all(page, expect_label="Desselecionar")
    assert _selected(page) == []
    _search(page, "grupox")
    _select_all(page)
    assert _selected(page) == [1, 3, 5, 7]
    # The revoked row is visible but read-only: neither a click nor a Shift
    # range across it selects it.
    _click_row(page, 9)
    assert 9 not in _selected(page)
    _search(page, "")
    _click_row(page, 8)
    _click_row(page, 9, shift=True)
    assert _selected(page) == [8]


@browser_only
def test_shift_click_does_not_select_text_but_dragging_still_does(page):
    page.goto("/admin/acesso?nome=Faixa")
    # Control: in this browser a click then Shift+click on ordinary text DOES
    # extend a native selection, so the empty selection below is meaningful.
    page.click_in_view(".access-summary-card .profile-name")
    page.click_in_view(".access-summary-card:nth-child(3) small", modifiers=SHIFT)
    assert _text_selection(page).strip()

    _click_row(page, 2)
    _click_row(page, 6, shift=True)
    assert _selected(page) == [2, 3, 4, 5, 6]
    assert _text_selection(page) == ""
    # The pressed row still takes focus, as an ordinary click would.
    assert page.evaluate("document.activeElement.dataset.userId") == str(page.ids[6])

    # Press-and-drag across a name still selects its text.
    name = _center(page, f'#acesso-list [data-user-id="{page.ids[4]}"] .cell:nth-child(1) strong')
    _mouse(page, name["left"] + 1, name["y"], "mousePressed")
    _mouse(page, name["right"] - 1, name["y"], "mouseMoved")
    _mouse(page, name["right"] - 1, name["y"], "mouseReleased", buttons=0)
    assert "Faixa 0" in _text_selection(page)
    assert _selected(page) == [2, 3, 4, 5, 6]  # the drag left the selection alone


def _drag_across(session, selector):
    """Press at the left edge of selector, drag to its right edge, release."""
    box = _center(session, selector)
    _mouse(session, box["left"] + 1, box["y"], "mousePressed")
    _mouse(session, (box["left"] + box["right"]) / 2, box["y"], "mouseMoved")
    _mouse(session, box["right"] - 1, box["y"], "mouseMoved")
    _mouse(session, box["right"] - 1, box["y"], "mouseReleased", buttons=0)
    session.pump(0.1)


def _double_click(session, selector):
    box = _center(session, selector)
    for count in (1, 2):
        session.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": box["x"], "y": box["y"], "button": "left", "buttons": 1, "clickCount": count})
        session.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": box["x"], "y": box["y"], "button": "left", "buttons": 0, "clickCount": count})
    session.pump(0.1)


@browser_only
def test_dragging_to_copy_text_never_marks_or_unmarks_the_card(page):
    page.goto("/admin/acesso?nome=Faixa")
    name = lambda n: f'#acesso-list [data-user-id="{page.ids[n]}"] .cell:nth-child(1) strong'
    email = lambda n: f'#acesso-list [data-user-id="{page.ids[n]}"] .cell:nth-child(2)'
    # An unselected card stays unselected; the text is really selected.
    _drag_across(page, name(3))
    assert _text_selection(page).strip() == "Faixa 03"
    assert _selected(page) == []
    # A selected card stays selected.
    _click_row(page, 5)
    assert _selected(page) == [5]
    _drag_across(page, email(5))
    assert "faixa05" in _text_selection(page)
    assert _selected(page) == [5]
    # A drag over another card neither adds it nor drops the current one.
    _drag_across(page, name(6))
    assert _selected(page) == [5]
    # A plain click still toggles; Shift still ranges from the anchor.
    _click_row(page, 5)
    assert _selected(page) == []
    _click_row(page, 2)
    _click_row(page, 4, shift=True)
    assert _selected(page) == [2, 3, 4]
    # A double-click on a word selects the word and stays two ordinary clicks
    # for the cards, exactly as before: the first selects only row 7, the
    # second toggles it off. Only a press that travelled is treated as copying.
    _double_click(page, name(7))
    assert _text_selection(page).strip() in {"Faixa", "07"}
    assert _selected(page) == []


@browser_only
def test_keyboard_text_selection_in_the_search_field_is_untouched(page):
    page.goto("/admin/acesso?nome=Faixa")
    page.evaluate("(() => { const i = document.querySelector('#busca-acesso'); i.focus(); i.value = 'grupox'; i.setSelectionRange(6, 6); return true; })()")
    for _ in range(3):
        page.call("Input.dispatchKeyEvent", {"type": "rawKeyDown", "key": "ArrowLeft", "code": "ArrowLeft", "windowsVirtualKeyCode": 37, "modifiers": SHIFT})
        page.call("Input.dispatchKeyEvent", {"type": "keyUp", "key": "ArrowLeft", "code": "ArrowLeft", "windowsVirtualKeyCode": 37, "modifiers": SHIFT})
    assert page.evaluate("(() => { const i = document.querySelector('#busca-acesso'); return [i.selectionStart, i.selectionEnd]; })()") == [3, 6]


# --------------------------------------------------------------------------
# The shared component on another screen: ordinary selection is unchanged
# --------------------------------------------------------------------------


@pytest.fixture
def cursos_page(tmp_path):
    with isolated_versioned_app_env(tmp_path, "shared-selection.db") as environment:
        with main.app.app_context():
            conn = main.get_db_connection()
            for number in range(1, 5):
                conn.execute(
                    "INSERT INTO cursos (nome, codigo, duracao_periodos, periodo, status)"
                    " VALUES (?, ?, 4, 'integral', 'ativo')",
                    (f"Rota Curso {number}", f"RT{number}"),
                )
            conn.commit()
        login_admin(environment["client"])
        session = cdp.BrowserSession(environment["client"], BINARY)
        try:
            yield session
        finally:
            session.close()


def _curso(number):
    return f'#cursos-list [data-curso-nome="Rota Curso {number}"]'


def _selected_cursos(session):
    return session.evaluate(
        "Array.from(document.querySelectorAll('#cursos-list .impresso-card.selected'))"
        ".map(r => Number(r.dataset.cursoNome.slice(-1))).sort()"
    )


@browser_only
def test_another_screen_keeps_click_toggle_shift_and_select_all(cursos_page):
    page = cursos_page
    page.goto("/admin/cursos?nome=Rota")
    page.evaluate("window.__errors = []; window.addEventListener('error', e => window.__errors.push(String(e.message))); true")
    page.click_in_view(_curso(1))
    page.click_in_view(_curso(3), modifiers=SHIFT)
    assert _selected_cursos(page) == [1, 2, 3]
    page.click_in_view(_curso(2))  # a plain click on a selected row removes it
    assert _selected_cursos(page) == [1, 3]
    page.click_in_view(_curso(4))  # a plain click elsewhere selects only that row
    assert _selected_cursos(page) == [4]

    page.click_in_view("#btn-cursos-actions")
    assert _text_of(page, "#cursos-action-select-all") == "Selecionar tudo"
    page.click("#cursos-action-select-all")
    page.pump(0.2)
    assert _selected_cursos(page) == [1, 2, 3, 4]
    assert _text_of(page, "#cursos-action-select-all") == "Desselecionar"
    assert page.evaluate("document.querySelector('#cursos-action-delete').disabled") is False
    page.click("#cursos-action-select-all")
    page.pump(0.2)
    assert _selected_cursos(page) == []

    # The live search here hides rows the same way: the selection follows.
    page.click("#cursos-action-select-all")
    page.pump(0.2)
    page.evaluate(
        "(() => { const i = document.querySelector('#busca-impressoes'); i.value = 'rota curso 4';"
        " i.dispatchEvent(new Event('input', {bubbles: true})); return true; })()"
    )
    page.pump(0.1)
    assert _selected_cursos(page) == [4]
    # Dragging across a row's text to copy it does not toggle that row here
    # either (the shared component owns it).
    page.evaluate(
        "(() => { const i = document.querySelector('#busca-impressoes'); i.value = '';"
        " i.dispatchEvent(new Event('input', {bubbles: true})); return true; })()"
    )
    box = _center(page, _curso(2) + " .cell:nth-child(2)")
    _mouse(page, box["left"] + 1, box["y"], "mousePressed")
    _mouse(page, box["right"] - 1, box["y"], "mouseMoved")
    _mouse(page, box["right"] - 1, box["y"], "mouseReleased", buttons=0)
    page.pump(0.1)
    assert page.evaluate("window.getSelection().toString()").strip()
    assert _selected_cursos(page) == [4]
    assert page.evaluate("window.__errors") == []


BAR_STATE = """(() => Object.fromEntries([...document.querySelectorAll('#pedido-actions-float .act-btn')]
  .map(b => [b.dataset.action, {disabled: b.disabled, tooltip: b.dataset.uiTooltip || '', label: b.getAttribute('aria-label')}])))()"""


def _hover_row(session, number):
    box = _center(session, f'#acesso-list [data-user-id="{session.ids[number]}"] .cell:nth-child(2)')
    _mouse(session, box["x"], box["y"], "mouseMoved", buttons=0)
    session.pump(0.2)
    return session.evaluate(BAR_STATE)


@browser_only
def test_the_row_bar_is_read_only_on_a_revoked_row_and_its_hints_follow_the_row(page):
    page.goto("/admin/acesso?nome=Faixa&situacao=Pendente&situacao=Revogado")
    pending = _hover_row(page, 1)
    assert pending["edit"] == {"disabled": False, "tooltip": "Editar", "label": "Editar acesso"}
    assert pending["delete"]["disabled"] is False  # e-mail stays off: no transport in this fixture

    revoked = _hover_row(page, 9)
    assert all(state["disabled"] for state in revoked.values()), revoked
    for action in ("edit", "email", "delete"):
        assert "Acesso revogado: somente consulta." in revoked[action]["tooltip"], (action, revoked[action])
        assert "Acesso revogado: somente consulta." in revoked[action]["label"], (action, revoked[action])
    # The default-password reason comes from its owner and is shown too.
    assert revoked["reset"]["tooltip"].startswith("Aplicar senha padrão — ")

    again = _hover_row(page, 2)
    assert again["edit"] == {"disabled": False, "tooltip": "Editar", "label": "Editar acesso"}
    assert again["reset"]["tooltip"] == "Aplicar senha padrão"


# --------------------------------------------------------------------------
# Pagination: the shared navigation renders and keeps every filter value
# --------------------------------------------------------------------------


def _seed_pages(conn):
    """28 Pendente and 3 Expirado accounts, all named "Pagina", + one Ativo."""
    for number in range(1, 29):
        _pending(conn, f"Pagina Pendente {number:02d}", f"pg.pend{number:02d}@example.test")
    for number in range(1, 4):
        usuario_id = _pending(conn, f"Pagina Expirado {number:02d}", f"pg.exp{number:02d}@example.test")
        _sent_link(conn, usuario_id, expired=True)
    create_usuario_with_access_level(
        conn, "Pagina Ativo 01", "pg.ativo@example.test", "test-hash", "admin", "consultivo",
        credential_state="personal",
    )


@pytest.fixture
def paged(env):
    with main.app.app_context():
        conn = main.get_db_connection()
        _seed_pages(conn)
        conn.commit()
    return env


def _nav(html):
    match = re.search(r'<nav class="pagination"[^>]*>(.*?)</nav>', html, re.S)
    if not match:
        return None
    body = match.group(1)
    links = {rel: href.replace("&amp;", "&") for href, rel in re.findall(r'<a class="btn" href="([^"]+)" rel="(prev|next)">', body)}
    summary = re.search(r"Página (\d+) de (\d+) • Total (\d+)", body)
    return {"links": links, "summary": tuple(int(value) for value in summary.groups())}


def test_the_navigation_renders_with_more_than_one_page(paged):
    html = _html(paged, "?nome=Pagina&situacao=Pendente&situacao=Expirado&per_page=25&page=1")
    # One ordered list: the three Expirado sort before the Pendente ones.
    assert _names(html) == [f"Pagina Expirado {n:02d}" for n in range(1, 4)] + [
        f"Pagina Pendente {n:02d}" for n in range(1, 23)
    ]
    nav = _nav(html)
    assert nav["summary"] == (1, 2, 31)
    assert set(nav["links"]) == {"next"}
    # Every filter value -- both situações included -- reaches the next page.
    next_link = nav["links"]["next"]
    for fragment in ("nome=Pagina", "situacao=Pendente", "situacao=Expirado", "page=2", "per_page=25"):
        assert fragment in next_link, (fragment, next_link)

    second = _html(paged, next_link[len("/admin/acesso"):])
    assert _names(second) == [f"Pagina Pendente {n:02d}" for n in range(23, 29)]
    nav = _nav(second)
    assert nav["summary"] == (2, 2, 31) and set(nav["links"]) == {"prev"}
    back = _html(paged, nav["links"]["prev"][len("/admin/acesso"):])
    assert _names(back) == _names(html)


def test_a_single_page_and_the_default_list_render_no_navigation(paged):
    assert _nav(_html(paged, "?nome=Pagina&situacao=Expirado&per_page=25&page=1")) is None
    # Without page/per_page the list is not paginated at all, as before.
    default = _html(paged, "?nome=Pagina")
    assert _nav(default) is None and len(_names(default)) == 32


@pytest.mark.parametrize("path", [
    "/admin/alunos", "/admin/turmas", "/admin/requisicoes", "/admin/reportes",
    "/admin/alertas", "/admin/arquivos",
])
def test_other_screens_render_with_the_macro_in_context(env, path):
    # Paged with one row per page: the navigation appears wherever the view
    # has more than one page, and no screen fails to render.
    response = env["client"].get(path + "?per_page=1&page=1")
    assert response.status_code == 200, path
    html = response.get_data(as_text=True)
    nav = _nav(html)
    if nav is not None:
        assert nav["summary"][0] == 1 and set(nav["links"]) == {"next"}
    assert _nav(env["client"].get(path).get_data(as_text=True)) is None, path


@pytest.fixture
def paged_page(tmp_path):
    with isolated_versioned_app_env(tmp_path, "access-pages.db") as environment:
        with main.app.app_context():
            conn = main.get_db_connection()
            _seed_pages(conn)
            conn.commit()
        login_admin(environment["client"])
        session = cdp.BrowserSession(environment["client"], BINARY)
        try:
            yield session
        finally:
            session.close()


PAGE_STATE = """(() => ({
  search: location.search,
  rows: document.querySelectorAll('#acesso-list .impresso-card[role=listitem]').length,
  first: document.querySelector('#acesso-list .impresso-card[role=listitem]')?.dataset.userNome,
  summary: document.querySelector('nav.pagination [data-pagination-summary]')?.textContent.trim(),
  filterBadge: document.querySelector('#filter-badge')?.textContent.trim(),
}))()"""


def _follow(session, selector):
    before = session.evaluate("location.href")
    session.click_in_view(selector)
    session.wait_for("location.href !== %s && document.readyState === 'complete'" % json.dumps(before))
    session.pump(0.2)
    return session.evaluate(PAGE_STATE)


@browser_only
def test_the_browser_moves_between_filtered_pages_and_keeps_the_filter(paged_page):
    page = paged_page
    page.goto("/admin/acesso?nome=Pagina&situacao=Pendente&situacao=Expirado&per_page=25&page=1")
    first = page.evaluate(PAGE_STATE)
    assert (first["rows"], first["first"], first["summary"]) == (25, "Pagina Expirado 01", "Página 1 de 2 • Total 31")
    second = _follow(page, 'nav.pagination a[rel="next"]')
    assert "situacao=Pendente" in second["search"] and "situacao=Expirado" in second["search"]
    assert "page=2" in second["search"]
    assert (second["rows"], second["first"], second["summary"]) == (6, "Pagina Pendente 23", "Página 2 de 2 • Total 31")
    # The filter menu still reads both situações (plus the name) as applied.
    assert second["filterBadge"] == "3"
    back = _follow(page, 'nav.pagination a[rel="prev"]')
    assert (back["rows"], back["first"], back["summary"]) == (25, "Pagina Expirado 01", "Página 1 de 2 • Total 31")


def test_every_pagination_call_names_a_real_endpoint_and_reads_its_context():
    # The macro never rendered before (imported without context), so a wrong
    # endpoint name could sit unnoticed; with it rendering, one is a
    # BuildError the moment a list has a second page.
    from pathlib import Path

    endpoints = {rule.endpoint for rule in main.app.url_map.iter_rules()}
    calls = []
    for template in sorted((Path(main.app.root_path).parent / "templates").glob("*.html")):
        source = template.read_text(encoding="utf-8")
        names = re.findall(r"paginate\('([^']+)'\)", source)
        if names:
            assert "import paginate with context" in source, template.name
        calls.extend((template.name, name) for name in names)
    assert len(calls) >= 9, calls
    assert [call for call in calls if call[1] not in endpoints] == []
