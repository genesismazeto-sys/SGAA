"""UI-C08 (Matriz): a Matriz linked to a Turma stays in Editar, partially.

Authoritative rule (``admin_editar_matriz`` + ``app.matrix_scope.is_matrix_assigned``):
when a Turma or a student points at the Matriz, Nome and Descrição still save,
while Curso, Status, both validity dates and both required-hour fields are
frozen, and the AAC/AEA composition cannot change.

UI contract: the page keeps "Editar" (real edits remain) but the six frozen
fields use the shared read-only contract -- selects ``disabled aria-readonly``
with their existing hidden mirrors carrying the unchanged value, inputs
``readonly aria-readonly`` -- and the frozen composition tabs expose no mutation
control and no redundant bottom Voltar (the header Back owns navigation).
An unlinked Matriz is unchanged.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

import pytest

import main
from tests.canonical_matrix_test_support import current_version_id, login_admin, seed_matrix_graph
from tests.versioned_test_support import isolated_versioned_app_env

FROZEN_INPUTS = ("data_inicio_vigencia", "data_fim_vigencia", "horas_aac_obrigatorias", "horas_extensao_obrigatorias")
FROZEN_SELECTS = ("curso_id", "status")
STATE_COLUMNS = "curso_id,nome,status,data_inicio_vigencia,data_fim_vigencia,horas_aac_obrigatorias,horas_extensao_obrigatorias,descricao"


@pytest.fixture
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "ui-c08-matriz.db") as environment:
        with main.app.app_context():
            conn = main.get_db_connection()
            linked = seed_matrix_graph(conn, name="UI-C08 vinculada")
            free = seed_matrix_graph(conn, name="UI-C08 livre")
            for seed in (linked, free):
                conn.execute(
                    "UPDATE matrizes_atividades SET data_inicio_vigencia='2026-01-01',"
                    " data_fim_vigencia='2026-12-31', descricao='Descricao original' WHERE id=?",
                    (seed["matrix_id"],),
                )
            conn.execute(
                "INSERT INTO turmas (nome,turno,status,numero,curso_id,ano_inicio,semestre_inicio,codigo,matriz_id)"
                " VALUES ('Turma UI-C08','Noturno','Ativa',1,?,2026,1,'T-UI-C08',?)",
                (linked["course_id"], linked["matrix_id"]),
            )
            conn.commit()
        login_admin(environment["client"])
        yield environment["client"], linked, free


def _state(matrix_id: int) -> dict:
    with main.app.app_context():
        row = main.get_db_connection().execute(
            f"SELECT {STATE_COLUMNS} FROM matrizes_atividades WHERE id=?", (matrix_id,)
        ).fetchone()
        return dict(row)


def _dados(client, matrix_id: int) -> str:
    response = client.get(f"/admin/editar_matriz/{matrix_id}?tab=dados")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    start = html.index('<input type="hidden" name="active_tab" value="dados">')
    start = html.rindex("<form", 0, start)
    return html[start: html.index("</form>", start) + len("</form>")]


class _BrowserForm(HTMLParser):
    """What a browser submits: enabled controls only (selected option, text, hidden)."""

    def __init__(self):
        super().__init__()
        self.data: list[tuple[str, str]] = []
        self._select = None
        self._textarea = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "input" and "name" in a and "disabled" not in a and a.get("type") != "submit":
            self.data.append((a["name"], a.get("value") or ""))
        elif tag == "select" and "disabled" not in a:
            self._select = a.get("name")
        elif tag == "option" and self._select and "selected" in a:
            self.data.append((self._select, a.get("value") or ""))
        elif tag == "textarea" and "disabled" not in a:
            self._textarea = [a.get("name"), ""]

    def handle_data(self, data):
        if self._textarea is not None:
            self._textarea[1] += data

    def handle_endtag(self, tag):
        if tag == "select":
            self._select = None
        elif tag == "textarea" and self._textarea is not None:
            self.data.append(tuple(self._textarea))
            self._textarea = None


def _browser_submission(form_html: str, **overrides) -> dict:
    parser = _BrowserForm()
    parser.feed(form_html)
    data = dict(parser.data)
    data.update(overrides)
    return data


def _tag(form_html: str, element: str, name: str) -> str:
    match = re.search(r"<%s\b[^>]*\bname=\"%s\"[^>]*>" % (element, name), form_html)
    assert match, (element, name)
    return match.group(0)


# ==========================================================================
# LINKED
# ==========================================================================


def test_linked_dados_freezes_six_fields_and_keeps_nome_descricao_editable(env):
    client, linked, _free = env
    form = _dados(client, linked["matrix_id"])

    assert not re.search(r'<fieldset class="form-fieldset"[^>]*disabled', form)
    for name in FROZEN_SELECTS:
        tag = _tag(form, "select", name)
        assert 'disabled aria-readonly="true"' in tag, name
        assert 'tabindex="-1"' not in tag, name
        assert len(re.findall(r'<input type="hidden" name="%s" value="[^"]+">' % name, form)) == 1, name
    for name in FROZEN_INPUTS:
        tag = _tag(form, "input", name)
        assert 'readonly aria-readonly="true"' in tag, name
        assert "disabled" not in tag, name
    for element, name in (("input", "nome"), ("textarea", "descricao")):
        tag = _tag(form, element, name)
        assert "readonly" not in tag and "disabled" not in tag, name
    assert 'type="submit"' in form


def test_linked_save_of_nome_and_descricao_succeeds_and_keeps_frozen_values(env):
    client, linked, _free = env
    matrix_id = linked["matrix_id"]
    before = _state(matrix_id)
    data = _browser_submission(_dados(client, matrix_id), nome="UI-C08 renomeada", descricao="Nova descricao")

    response = client.post(f"/admin/editar_matriz/{matrix_id}", data=data, follow_redirects=False)
    assert response.status_code in (302, 303)
    after = _state(matrix_id)
    assert after["nome"] == "UI-C08 renomeada"
    assert after["descricao"] == "Nova descricao"
    for column in ("curso_id", "status", *FROZEN_INPUTS):
        assert after[column] == before[column], column


@pytest.mark.parametrize(
    "field, value",
    [("status", "vigente"), ("horas_aac_obrigatorias", "999"), ("data_fim_vigencia", "2030-01-01"), ("curso_id", "999999")],
)
def test_linked_crafted_change_of_a_frozen_field_is_still_refused(env, field, value):
    client, linked, _free = env
    matrix_id = linked["matrix_id"]
    before = _state(matrix_id)
    data = _browser_submission(_dados(client, matrix_id), nome="Nao deve salvar", **{field: value})

    client.post(f"/admin/editar_matriz/{matrix_id}", data=data, follow_redirects=False)
    assert _state(matrix_id) == before


@pytest.mark.parametrize("tab", ["aac", "aea"])
def test_linked_composition_tabs_expose_no_mutation(env, tab):
    client, linked, _free = env
    html = client.get(f"/admin/editar_matriz/{linked['matrix_id']}?tab={tab}").get_data(as_text=True)
    start = html.index('<section class="matriz-tab-panel"')
    panel = html[start: html.index("<script", start)]  # the whole tab, footer included

    assert 'data-readonly="1"' in panel
    assert "<form" not in panel
    for marker in ('data-move=', 'data-side=', 'name="selected_activity_ids"', "card-version-menu-btn",
                   'type="submit"', 'class="form-actions'):
        assert marker not in panel, marker
    assert "data-close-version-modal" not in html
    assert "Esta Matriz está vinculada a uma Turma" in panel
    assert 'class="btn detail-header__back"' in html


def test_linked_composition_post_is_still_refused(env):
    client, linked, _free = env
    matrix_id = linked["matrix_id"]
    with main.app.app_context():
        before = current_version_id(main.get_db_connection(), linked)
    client.post(
        f"/admin/editar_matriz/{matrix_id}",
        data={"active_tab": "aac", "selected_activity_ids": []},
        follow_redirects=False,
    )
    with main.app.app_context():
        assert current_version_id(main.get_db_connection(), linked) == before


# ==========================================================================
# UNLINKED
# ==========================================================================


def test_unlinked_dados_is_fully_editable_and_saves_protected_fields(env):
    client, _linked, free = env
    matrix_id = free["matrix_id"]
    form = _dados(client, matrix_id)
    for name in FROZEN_SELECTS:
        tag = _tag(form, "select", name)
        assert "disabled" not in tag and "aria-readonly" not in tag, name
        assert f'<input type="hidden" name="{name}"' not in form, name
    for name in FROZEN_INPUTS:
        assert "readonly" not in _tag(form, "input", name), name

    data = _browser_submission(form, status="vigente", horas_aac_obrigatorias="120", nome="UI-C08 livre editada")
    response = client.post(f"/admin/editar_matriz/{matrix_id}", data=data, follow_redirects=False)
    assert response.status_code in (302, 303)
    after = _state(matrix_id)
    assert (after["status"], after["horas_aac_obrigatorias"], after["nome"]) == ("vigente", 120, "UI-C08 livre editada")


def test_unlinked_composition_keeps_its_mutation_controls(env):
    client, _linked, free = env
    html = client.get(f"/admin/editar_matriz/{free['matrix_id']}?tab=aac").get_data(as_text=True)
    panel = html[html.index('<section class="matriz-tab-panel"'):]
    assert '<form method="POST" class="matriz-transfer-form" data-transfer-root data-readonly="0">' in panel
    assert 'data-move=">"' in panel and 'name="selected_activity_ids"' in panel
    footer = re.search(r'<div class="form-actions center">(.*?)</div>', panel, re.S)
    assert footer and "Cancelar" in footer.group(1) and 'type="submit"' in footer.group(1)
