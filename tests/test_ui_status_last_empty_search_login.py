# coding: utf-8
"""UI consistency front: Status last, empty search state, Atividades search, login.

1. STATUS IS ALWAYS THE LAST COLUMN. Violations found by the audit: the
   activity Versões grid (``... Limitação · Status · Matrizes``), admin
   Reportes (``... Título · Status · Data``) and both Banco de dados
   provider-log tables (``... Tamanho · Status · Erro``). Each now ends in
   Status; the card grids opt into the shared DS status-column contract
   (``.cell.status-col`` + ``var(--imp-status-col)``), whose track reserves the
   domain's LONGEST label. Requisições already had Status last but its
   ``minmax(120px, 160px)`` track clipped "Deferida Parcialmente" below 1920px;
   it adopts the same contract.
2. ZERO RESULTS SHOW NO COLUMN HEADERS. The server side already followed
   DS-EMPTY-TABLE-STATE (``cl.collection``); the client-side live search kept
   the header row above "Nenhum resultado encontrado.". It now hides the
   header with the rows and shows the shared ``.table-empty`` message.
3. ATIVIDADES SEARCH. Rows carry ``data-search-text="{{ a.nome }}"`` and the
   live search used that attribute RAW, so the query ("moni", normalised) was
   compared against "Monitoria voluntária." with its capital M and accent.
   Every row haystack now goes through the human-text key.
4. LOGIN. The identity field declares ``autocomplete="username"`` and the
   password ``autocomplete="current-password"``; nothing on the page says
   ``autocomplete="off"``. Set/reset-password forms are untouched.
"""
from __future__ import annotations

import html as html_module
import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

import main
from app.status_presentation import REQUEST_STATUS_TONES
from app.views.admin.reportes import REPORTE_STATUS_OPTIONS
from tests.canonical_request_test_support import create_admin_request, login_admin, login_student
from tests.versioned_test_support import isolated_versioned_app_env

ROOT = Path(__file__).resolve().parents[1]
LIST_CSS = (ROOT / "static/css/components/list-cards.css").read_text(encoding="utf-8")
VERSION_STATUS_LABELS = ("Ativa", "Rascunho", "Inativa", "Descontinuada", "Substituída")
STATUS_LABELS = {"Status", "Situação"}


# --------------------------------------------------------------------------
# Rendered header rows (card grids and <table>s)
# --------------------------------------------------------------------------


class _Headers(HTMLParser):
    """Collect every header row: `.impresso-card.header` cells and `<thead>` cells."""

    def __init__(self):
        super().__init__()
        self.rows: list[list[str]] = []
        self._depth = 0
        self._row_depth = None
        self._cell = None
        self._in_thead = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = (attrs.get("class") or "").split()
        if tag == "div":
            self._depth += 1
            if "impresso-card" in classes and "header" in classes:
                self._row_depth = self._depth
                self.rows.append([])
            elif self._row_depth is not None and "cell" in classes and self._depth == self._row_depth + 1:
                self._cell = []
        elif tag == "thead":
            self._in_thead = True
            self.rows.append([])
        elif tag == "th" and self._in_thead:
            self._cell = []

    def handle_endtag(self, tag):
        if tag == "div":
            if self._cell is not None and self._row_depth is not None and self._depth == self._row_depth + 1:
                self.rows[-1].append("".join(self._cell).strip())
                self._cell = None
            if self._row_depth is not None and self._depth == self._row_depth:
                self._row_depth = None
            self._depth -= 1
        elif tag == "th" and self._cell is not None:
            self.rows[-1].append("".join(self._cell).strip())
            self._cell = None
        elif tag == "thead":
            self._in_thead = False

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def _header_rows(html: str) -> list[list[str]]:
    parser = _Headers()
    parser.feed(html)
    return [row for row in parser.rows if row]


def _status_rows(html: str) -> list[list[str]]:
    return [row for row in _header_rows(html) if STATUS_LABELS & set(row)]


@pytest.fixture
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "ui-status-last.db") as environment:
        login_admin(environment["client"])
        yield environment


def _populate(env) -> dict:
    client = env["client"]
    _response, created = create_admin_request(client, name="Status last populated")
    assert created is not None
    with main.app.app_context():
        conn = main.get_db_connection()
        aluno_id = conn.execute("SELECT MIN(id) FROM alunos").fetchone()[0]
        for status in REPORTE_STATUS_OPTIONS:
            conn.execute(
                "INSERT INTO reportes (aluno_id, titulo, descricao, categoria, status) VALUES (?, ?, 'x', 'Bug na plataforma', ?)",
                (aluno_id, f"Reporte {status}", status),
            )
        conn.execute("INSERT INTO admin_alertas (titulo, mensagem) VALUES ('Alerta', 'Mensagem')")
        conn.execute(
            "INSERT INTO backup_logs (provider, file_name, file_size, status, error_message) VALUES"
            " ('google', 'ok.db', 1024, 'sucesso', NULL), ('google', 'fail.db', 0, 'erro', 'invalid_grant'),"
            " ('onedrive', 'od.db', 2048, 'sucesso', NULL)"
        )
        base_id = conn.execute(
            "INSERT INTO atividade_base (nome_conceito, status) VALUES ('Atividade com cinco status', 'ativo')"
        ).lastrowid
        for numero, status in enumerate(("ativa", "rascunho", "inativa", "descontinuada", "substituida"), 1):
            conn.execute(
                "INSERT INTO atividade_versao (atividade_base_id, eixo, grupo, numero_versao, status)"
                " VALUES (?, 'AAC', '1 - Grupo', ?, ?)",
                (base_id, numero, status),
            )
        turma_id, curso_id = conn.execute(
            "SELECT t.id, t.curso_id FROM turmas t JOIN alunos a ON a.turma_id = t.id LIMIT 1"
        ).fetchone()
        conn.commit()
    return {"base_id": base_id, "turma_id": turma_id, "curso_id": curso_id}


ADMIN_STATUS_PAGES = [
    "/admin/alunos", "/admin/turmas", "/admin/cursos", "/admin/matrizes", "/admin/requisicoes",
    "/admin/reportes", "/admin/alertas", "/admin/acesso", "/admin/banco-dados",
]


def test_every_rendered_status_column_is_the_last_one(env):
    ids = _populate(env)
    client = env["client"]
    pages = ADMIN_STATUS_PAGES + [
        f"/admin/turma/{ids['turma_id']}", f"/admin/cursos/{ids['curso_id']}",
        f"/admin/catalogo-versoes/{ids['base_id']}",
    ]
    seen = {}
    for url in pages:
        response = client.get(url)
        assert response.status_code == 200, url
        rows = _status_rows(response.get_data(as_text=True))
        assert rows, f"{url}: no header row with a Status column rendered"
        for row in rows:
            assert row[-1] in STATUS_LABELS, f"{url}: Status is not last in {row}"
        seen[url] = rows

    with client.session_transaction() as session:
        session.clear()
    login_student(client)
    for url in ("/aluno/requisicoes", "/aluno/reportar"):
        rows = _status_rows(client.get(url).get_data(as_text=True))
        assert rows and all(row[-1] == "Status" for row in rows), (url, rows)

    # The three audited violations, exactly.
    versions = seen[f"/admin/catalogo-versoes/{ids['base_id']}"]
    assert ["Versão", "Tipo", "Carga horária por evento", "Limitação", "Matrizes", "Status"] in versions
    assert seen["/admin/reportes"] == [["#", "Aluno", "Matrícula", "Categoria", "Título", "Data", "Status"]]
    assert seen["/admin/banco-dados"] == [["Data", "Provedor", "Arquivo", "Tamanho", "Erro", "Status"]] * 2


def test_moved_status_cells_are_the_last_cell_of_every_row_and_carry_the_contract(env):
    ids = _populate(env)
    client = env["client"]

    versions = client.get(f"/admin/catalogo-versoes/{ids['base_id']}").get_data(as_text=True)
    rows = re.findall(r'data-has-substitution="[01]">(.*?)\n            </div>', versions, re.S)
    assert len(rows) == 5
    for row in rows:
        cells = re.findall(r'<div class="cell([^"]*)"', row)
        assert len(cells) == 6 and cells[-1].strip() == "status-col", cells
        assert "status-pill" in row.split('class="cell status-col"', 1)[1]
    labels = re.findall(r'<div class="cell status-col">\s*<span class="badge status-badge status-pill status-\w+">([^<]+)</span>', versions)
    assert sorted(labels) == sorted(VERSION_STATUS_LABELS)
    assert '<div class="cell status-col">Status</div>' in versions

    reportes = client.get("/admin/reportes").get_data(as_text=True)
    assert '<div class="cell status-col">Status</div>' in reportes
    report_rows = re.findall(r'data-reporte-id="\d+"[^>]*>(.*?)\n        </div>', reportes, re.S)
    assert len(report_rows) == len(REPORTE_STATUS_OPTIONS)
    for row in report_rows:
        cells = re.findall(r'<div class="cell([^"]*)"', row)
        assert len(cells) == 7 and cells[-1].strip() == "status-col", cells
        assert "status-pill" in row.split('class="cell status-col"', 1)[1]

    requisicoes = client.get("/admin/requisicoes").get_data(as_text=True)
    assert '<div class="cell status-col">Status</div>' in requisicoes
    assert re.search(r'<div class="cell status-col">\s*<span class="badge status-badge status-pill', requisicoes)

    banco = client.get("/admin/banco-dados").get_data(as_text=True)
    for table in re.findall(r'<div class="db-table-wrap db-provider-log">(.*?)</table>', banco, re.S):
        for body_row in re.findall(r"<tr>(.*?)</tr>", table.split("<tbody>", 1)[1], re.S):
            cells = re.findall(r"<td>(.*?)</td>", body_row, re.S)
            assert len(cells) == 6 and "db-badge" in cells[-1], cells
            assert "db-badge" not in cells[-2]


def _declared_chars(source: str, scope: str) -> int:
    match = re.search(rf"\.{scope}\s*\{{\s*--imp-status-col-chars:\s*(\d+)\s*;", source)
    assert match, f"{scope} declares no --imp-status-col-chars"
    return int(match.group(1))


def test_status_tracks_reserve_the_longest_label_their_domain_supports():
    versions = (ROOT / "templates/admin_catalogo_versao_detalhe.html").read_text(encoding="utf-8")
    reportes = (ROOT / "templates/admin_reportes.html").read_text(encoding="utf-8")
    assert _declared_chars(LIST_CSS, "imp-req") == len(max(REQUEST_STATUS_TONES, key=len)) == 21
    assert _declared_chars(reportes, "imp-reportes") == len(max(REPORTE_STATUS_OPTIONS, key=len)) == 10
    assert _declared_chars(versions, "imp-version-detail") == len(max(VERSION_STATUS_LABELS, key=len)) == 13
    # Each grid's last track is the shared token, never a flexible or guessed width.
    for source, scope in ((LIST_CSS, "imp-req"), (reportes, "imp-reportes"), (versions, "imp-version-detail")):
        block = source[source.index("--imp-cols", source.index(f".{scope}")):]
        block = block[: block.index(";")]
        tracks = re.sub(r"/\*.*?\*/", "", block, flags=re.S).split(":", 1)[1].replace("}", "").strip()
        assert tracks.endswith("var(--imp-status-col)"), (scope, tracks)
        assert re.search(rf"\.{scope}\s*\{{[^}}]*--imp-list-min-width:calc\(\d+px \+ var\(--imp-status-col\)\)", source), scope


def test_version_labels_cover_the_whole_schema_domain():
    """The 13-character reservation is pinned to the whole version-status domain:
    every status the atividade_versao CHECK allows has a label in the template."""
    schema = (ROOT / "app/prod1_schema.py").read_text(encoding="utf-8")
    table = schema[schema.index("CREATE TABLE atividade_versao"):]
    domain = re.search(r"status TEXT NOT NULL DEFAULT 'rascunho' CHECK\(status IN \(([^)]*)\)\)", table).group(1)
    keys = re.findall(r"'([^']+)'", domain)
    template = (ROOT / "templates/admin_catalogo_versao_detalhe.html").read_text(encoding="utf-8")
    label_map = template[template.index("{% set status_label = {"):]
    label_map = label_map[: label_map.index("}")]
    labels = dict(re.findall(r"'(\w+)': '([^']+)'", label_map))
    assert set(labels) == set(keys)
    assert set(labels.values()) == set(VERSION_STATUS_LABELS)


# --------------------------------------------------------------------------
# Login semantics for password managers
# --------------------------------------------------------------------------


class _Inputs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.forms: list[dict] = []
        self.inputs: list[dict] = []

    def handle_starttag(self, tag, attrs):
        if tag == "form":
            self.forms.append(dict(attrs))
        elif tag in {"input", "button"}:
            self.inputs.append({"tag": tag, **dict(attrs)})


def test_login_declares_username_and_current_password(tmp_path):
    with isolated_versioned_app_env(tmp_path, "login-semantics.db") as environment:
        html = environment["client"].get("/login").get_data(as_text=True)
    parser = _Inputs()
    parser.feed(html)
    assert len(parser.forms) == 1 and parser.forms[0].get("method", "").upper() == "POST"
    assert "autocomplete" not in parser.forms[0]
    by_id = {item.get("id"): item for item in parser.inputs if item.get("id")}
    assert by_id["email"]["type"] == "email" and by_id["email"]["name"] == "email"
    assert by_id["email"]["autocomplete"] == "username"
    assert by_id["senha"]["type"] == "password" and by_id["senha"]["name"] == "senha"
    assert by_id["senha"]["autocomplete"] == "current-password"
    assert [i for i in parser.inputs if i.get("type") == "password"] == [by_id["senha"]]
    assert any(i["tag"] == "button" and i.get("type") == "submit" for i in parser.inputs)
    assert 'autocomplete="off"' not in html


def test_new_password_forms_keep_their_own_autocomplete():
    set_password = (ROOT / "templates/set_password.html").read_text(encoding="utf-8")
    assert set_password.count('autocomplete="new-password"') == 2
    forgot = (ROOT / "templates/forgot_password.html").read_text(encoding="utf-8")
    assert 'autocomplete="email"' in forgot


# --------------------------------------------------------------------------
# Client side: empty search state and the Atividades search (real browser)
# --------------------------------------------------------------------------

cdp = pytest.importorskip("tests.cdp_browser_support")
BINARY = cdp.find_chromium()
browser_only = pytest.mark.skipif(BINARY is None, reason="no Chromium binary for the browser harness")

SEARCH = """((inputSel, rootSel, query) => {
  const input = document.querySelector(inputSel);
  const root = document.querySelector(rootSel);
  input.value = query;
  input.dispatchEvent(new Event('input', {bubbles: true}));
  const shown = el => !!el && el.getClientRects().length > 0;
  return {
    names: Array.from(root.querySelectorAll('.impresso-card[role="listitem"]')).filter(shown)
      .map(r => r.dataset.atividadeNome || r.textContent.trim().split('\\n')[0].trim()),
    headers: Array.from(root.querySelectorAll('.impresso-card.header')).filter(shown).length,
    empty: Array.from(root.querySelectorAll('.table-empty')).filter(shown).map(e => [e.className, e.textContent.trim()]),
  };
})(%s, %s, %s)"""

LIVE_SEARCH_PAGES = [
    ("/admin/atividades", "#busca-impressoes", "#atividades-list"),
    ("/admin/alunos", "#busca-impressoes", "#alunos-list"),
    ("/admin/acesso", "#busca-acesso", "#acesso-list"),
    ("/admin/requisicoes", "#busca-impressoes", "#requisicoes-list"),
    ("/admin/reportes", "#busca-reportes", "#reportes-list"),
    ("/admin/turmas", "#busca-impressoes", "#turmas-list"),
]


@pytest.fixture
def browser(env):
    _populate(env)
    with main.app.app_context():
        conn = main.get_db_connection()
        base_id = conn.execute(
            "INSERT INTO atividade_base (nome_conceito, status) VALUES ('Monitoria voluntária.', 'ativo')"
        ).lastrowid
        conn.execute(
            "INSERT INTO atividade_versao (atividade_base_id, eixo, grupo, numero_versao, status)"
            " VALUES (?, 'AAC', '4 - Atividades de monitoria', 1, 'ativa')",
            (base_id,),
        )
        conn.commit()
    session = cdp.BrowserSession(env["client"], BINARY)
    try:
        yield session
    finally:
        session.close()


def _search(session, path, input_sel, root_sel, query):
    return session.evaluate(SEARCH % (json.dumps(input_sel), json.dumps(root_sel), json.dumps(query)))


TRACK = """((sel) => {
  const scroll = document.querySelector(sel);
  const header = Array.from(scroll.querySelectorAll('.impresso-card.header > .cell')).pop();
  const pills = Array.from(scroll.querySelectorAll('.impresso-card[role="listitem"] .cell.status-col > .status-pill'));
  return {
    token: getComputedStyle(scroll).getPropertyValue('--imp-status-col').replace(/\\s+/g, ' ').trim(),
    track: header.getBoundingClientRect().width,
    clipped: pills.filter(p => p.getBoundingClientRect().right > p.parentElement.getBoundingClientRect().right + 0.5
                          || p.scrollWidth > p.clientWidth + 0.5).length,
    pills: pills.length,
  };
})(%s)"""


@browser_only
def test_each_status_track_is_computed_from_its_own_domain(browser, env):
    """The track resolves on the list element, so the list's own character
    count applies (computed on :root, every list silently got 21)."""
    with main.app.app_context():
        base_id = main.get_db_connection().execute(
            "SELECT id FROM atividade_base WHERE nome_conceito='Atividade com cinco status'"
        ).fetchone()[0]
    widths = {}
    for path, scope, chars in (
        ("/admin/reportes", ".imp-reportes", 10),
        (f"/admin/catalogo-versoes/{base_id}", ".imp-version-detail", 13),
        ("/admin/acesso", ".imp-acesso", 15),
        ("/admin/requisicoes", ".imp-req", 21),
    ):
        browser.goto(path)
        result = browser.evaluate(TRACK % json.dumps(scope))
        assert result["token"].startswith(f"calc( {chars} * 1ch") or result["token"].startswith(f"calc({chars} * 1ch"), result
        assert result["pills"] and result["clipped"] == 0, (path, result)
        widths[chars] = result["track"]
    assert widths[10] < widths[13] < widths[15] < widths[21]


@browser_only
@pytest.mark.parametrize("query", ["moni", "monitoria", "Monitoria", "MONITORIA"])
def test_atividades_live_search_finds_monitoria(browser, query):
    browser.goto("/admin/atividades")
    result = _search(browser, "/admin/atividades", "#busca-impressoes", "#atividades-list", query)
    # The seeded catalogue also has "Monitoria acadêmica supervisionada": every
    # Monitoria matches, and nothing else does.
    assert "Monitoria voluntária." in result["names"], result
    assert result["names"] and all(name.startswith("Monitoria ") for name in result["names"]), result
    assert result["headers"] == 1 and result["empty"] == []


@browser_only
@pytest.mark.parametrize("query", ["voluntaria", "Voluntária", "VOLUNTÁRIA"])
def test_atividades_live_search_is_accent_insensitive(browser, query):
    browser.goto("/admin/atividades")
    result = _search(browser, "/admin/atividades", "#busca-impressoes", "#atividades-list", query)
    assert result["names"] == ["Monitoria voluntária."], result


@browser_only
def test_atividades_live_search_respects_an_explicit_filter(browser):
    browser.goto("/admin/atividades?tipo=Extens%C3%A3o+Universit%C3%A1ria")
    result = _search(browser, "", "#busca-impressoes", "#atividades-list", "moni")
    assert result["names"] == [] and result["headers"] == 0
    assert result["empty"] == [["toolbar-live-search-empty table-empty", "Nenhum resultado encontrado."]]


@browser_only
@pytest.mark.parametrize(("path", "input_sel", "root_sel"), LIVE_SEARCH_PAGES)
def test_zero_search_results_show_only_the_empty_state(browser, path, input_sel, root_sel):
    browser.goto(path)
    before = _search(browser, path, input_sel, root_sel, "")
    assert before["names"] and before["headers"] == 1 and before["empty"] == [], before

    none = _search(browser, path, input_sel, root_sel, "zzzz-sem-resultado")
    assert none["names"] == [] and none["headers"] == 0, none
    assert none["empty"] == [["toolbar-live-search-empty table-empty", "Nenhum resultado encontrado."]]

    back = _search(browser, path, input_sel, root_sel, "")
    assert back == before
