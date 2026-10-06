# coding: utf-8
"""HUMAN-TEXT-ORDER: one authority for alphabetical order and search of human text.

Observed defect: on Admin > Acesso "Éverto Luza Mognon" was listed after
"Wandrew ...". The list ordered by ``LOWER(u.nome)``: SQLite's LOWER() folds
ASCII only and the comparison is binary UTF-8, so "É" (0xC3 0x89) sorted after
every ASCII letter. Other lists had the same machine order (``LOWER``,
``COLLATE NOCASE``, ``str.casefold``), and several searches were
accent-sensitive ("joao" did not find "João" server-side; "moni" did not find
"Monitoria voluntária" client-side).

Contract, owned once by ``app/text.py`` (``human_text_key``) and mirrored on
the client by ``static/js/human-text.js``:

* order and search compare NFKD text without combining marks, casefolded,
  whitespace collapsed -- "Éverto" sorts with E, "everto" finds it;
* stored and displayed text is never rewritten;
* ties are deterministic (raw text in Python, the row id in SQL);
* e-mails, codes, matrículas and enum values keep their own semantics.

SQL sees the authority as ``COLLATE PTBR_NOACCENT`` and ``PTBR_FOLD(x)``,
registered on every request connection by ``app.db.get_db_connection``.
"""
from __future__ import annotations

import html as html_module
import itertools
import re
import sqlite3
import unicodedata
from pathlib import Path

import pytest

import main
from app.text import (
    human_text_contains,
    human_text_key,
    ptbr_sqlite_collation,
    ptbr_text_sort_key,
    register_human_text_sql,
)
from tests.canonical_request_test_support import create_admin_request, login_admin
from tests.versioned_test_support import isolated_versioned_app_env

ROOT = Path(__file__).resolve().parents[1]
EVERTO = "Éverto Luza Mognon"


# --------------------------------------------------------------------------
# The authority
# --------------------------------------------------------------------------


def test_everto_sorts_in_the_e_block_before_felipe():
    names = ["Wandrew Silva", "Felipe Souza", EVERTO, "Victor Hugo", "Eduardo Lima", "Ana Paula"]
    assert sorted(names, key=ptbr_text_sort_key) == [
        "Ana Paula", "Eduardo Lima", EVERTO, "Felipe Souza", "Victor Hugo", "Wandrew Silva",
    ]


def test_sql_collation_orders_the_same_way():
    conn = sqlite3.connect(":memory:")
    try:
        register_human_text_sql(conn)
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, nome TEXT)")
        conn.executemany("INSERT INTO t (nome) VALUES (?)",
                         [("Wandrew",), ("Felipe",), ("Éverto",), ("Eduardo",), ("álvaro",), ("Bruno",)])
        rows = [r[0] for r in conn.execute("SELECT nome FROM t ORDER BY nome COLLATE PTBR_NOACCENT, id")]
        binary = [r[0] for r in conn.execute("SELECT nome FROM t ORDER BY LOWER(nome)")]
    finally:
        conn.close()
    assert rows == ["álvaro", "Bruno", "Eduardo", "Éverto", "Felipe", "Wandrew"]
    # The defect this replaces: ASCII-only LOWER() + binary order puts every
    # accented initial after "w".
    assert binary == ["Bruno", "Eduardo", "Felipe", "Wandrew", "Éverto", "álvaro"]


@pytest.mark.parametrize("variant", ["éverto", "Éverto", "EVERTO", "everto", "ÉVERTO", "  Éverto  "])
def test_casing_and_accents_share_one_key(variant):
    assert human_text_key(variant) == "everto"


@pytest.mark.parametrize(
    ("accented", "plain"),
    [
        ("Álvaro", "Alvaro"), ("Cauã", "Caua"), ("João", "Joao"), ("Mário", "Mario"),
        ("José", "Jose"), ("Conceição", "Conceicao"), ("Açúcar", "Acucar"), ("Ítalo", "Italo"),
        ("Ônix", "Onix"), ("Úrsula", "Ursula"), ("Müller", "Muller"), ("Gonçalves", "Goncalves"),
    ],
)
def test_accents_do_not_decide_alphabetical_position(accented, plain):
    assert human_text_key(accented) == human_text_key(plain)
    assert ptbr_sqlite_collation(accented, plain) == 0


@pytest.mark.parametrize(
    ("letters", "base"),
    [("ÁÀÂÃÄ", "a"), ("ÉÈÊË", "e"), ("ÍÌÎÏ", "i"), ("ÓÒÔÕÖ", "o"), ("ÚÙÛÜ", "u"), ("Ç", "c")],
)
def test_every_portuguese_diacritic_folds_to_its_base_letter(letters, base):
    for letter in letters + letters.lower():
        assert human_text_key(letter) == base, letter


def test_unicode_composition_does_not_matter():
    composed = unicodedata.normalize("NFC", EVERTO)
    decomposed = unicodedata.normalize("NFD", EVERTO)
    assert composed != decomposed
    assert human_text_key(composed) == human_text_key(decomposed) == "everto luza mognon"


def test_ties_are_deterministic_whatever_the_input_order():
    values = ["Éverto", "Everto", "EVERTO", "everto"]
    results = {tuple(sorted(p, key=ptbr_text_sort_key)) for p in itertools.permutations(values)}
    assert len(results) == 1


def test_the_key_never_rewrites_the_value():
    value = EVERTO
    human_text_key(value)
    ptbr_text_sort_key(value)
    assert value == "Éverto Luza Mognon"
    assert ptbr_text_sort_key(value)[2] == "Éverto Luza Mognon"


@pytest.mark.parametrize(
    ("needle", "haystack"),
    [("everto", EVERTO), ("joao", "João Moreira"), ("caua", "Cauã Schott"), ("mario", "Mário Vinícius"),
     ("MONI", "Monitoria voluntária."), ("voluntaria", "Monitoria voluntária."), ("éverto", "Everto Sem Acento")],
)
def test_search_ignores_case_and_accents(needle, haystack):
    assert human_text_contains(haystack, needle)


def test_search_still_discriminates():
    assert not human_text_contains("Jonas Silva", "joao")
    assert not human_text_contains("Cauã", "cauan")


def test_sql_fold_function_is_registered_on_request_connections(tmp_path):
    with isolated_versioned_app_env(tmp_path, "human-fold.db"):
        with main.app.app_context():
            conn = main.get_db_connection()
            assert conn.execute("SELECT PTBR_FOLD('Éverto  LUZA')").fetchone()[0] == "everto luza"
            assert conn.execute("SELECT PTBR_FOLD(NULL)").fetchone()[0] == ""
            assert conn.execute(
                "SELECT CASE WHEN 'Éverto' = 'EVERTO' COLLATE PTBR_NOACCENT THEN 1 ELSE 0 END"
            ).fetchone()[0] == 1


def test_technical_fields_keep_their_own_semantics():
    """E-mails, matrículas and codes are not human text: no accent folding."""
    # PG-READINESS-U5-D (D-5): the filter helpers now take the caller-owned
    # connection explicitly; the technical/human split is unchanged.
    acesso = (ROOT / "app/views/admin/acesso.py").read_text(encoding="utf-8")
    assert 'append_text_contains_condition(where, params, "u.email", email_filter, connection=conn)' in acesso
    assert 'append_text_contains_condition(where, params, "a.matricula", matricula_filter, connection=conn)' in acesso
    assert '"email": "LOWER(u.email)",' in acesso
    cursos = (ROOT / "app/views/admin/alunos_turmas_cursos.py").read_text(encoding="utf-8")
    assert 'append_text_contains_condition(where, params, "c.codigo", codigo_filter, connection=conn)' in cursos
    assert 'append_text_contains_condition(where, params, "u.email", email_filter, connection=conn)' in cursos
    # Negative control: technical fields never go through the human-text fold.
    for source in (acesso, cursos):
        for field in ("u.email", "a.matricula", "c.codigo", "t.codigo"):
            assert f'append_human_text_contains_condition(where, params, "{field}"' not in source
            assert f'human_text_contains_sql("{field}"' not in source


# --------------------------------------------------------------------------
# Server-side surfaces
# --------------------------------------------------------------------------


def _admin_names(html: str) -> list[str]:
    return [html_module.unescape(n) for n in re.findall(r'data-user-nome="([^"]*)"', html)]


def _first_cells(html: str, list_id: str, index: int = 0) -> list[str]:
    """Text of cell ``index`` of every rendered row of one card list."""
    body = html.split(f'id="{list_id}"', 1)[1]
    body = body.split("<script", 1)[0]
    rows = re.split(r'<div class="impresso-card[^"]*"\s+role="listitem"', body)[1:]
    texts = []
    for row in rows:
        cells = re.findall(r'<div class="cell[^"]*"[^>]*>(.*?)</div>', row, re.S)
        texts.append(html_module.unescape(re.sub(r"<[^>]+>", "", cells[index]).strip()))
    return texts


def _seed_admin(conn, nome: str, email: str) -> int:
    from app.user_accounts import create_usuario_with_access_level

    return int(create_usuario_with_access_level(
        conn, nome, email, main.hash_password("x"), "admin", "admin_total", credential_state="personal",
    ).lastrowid)


def _seed_aluno(conn, nome: str, email: str, matricula: str) -> int:
    usuario_id = conn.execute(
        "INSERT INTO usuarios (nome, email, senha, tipo) VALUES (?, ?, ?, 'aluno')",
        (nome, email, main.hash_password("x")),
    ).lastrowid
    return int(conn.execute(
        "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, matriz_id, status)"
        " VALUES (?, ?, ?, ?, 2, 2, 'Ativo')",
        (usuario_id, nome, matricula, email),
    ).lastrowid)


ORDER_FIXTURE = [
    ("Wandrew Ordem", "wandrew.ordem@example.test"),
    ("Felipe Ordem", "felipe.ordem@example.test"),
    (EVERTO, "everto.ordem@example.test"),
    ("Victor Ordem", "victor.ordem@example.test"),
    ("Eduardo Ordem", "eduardo.ordem@example.test"),
    ("João Ordem", "joao.ordem@example.test"),
]


@pytest.fixture
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "human-text.db") as environment:
        login_admin(environment["client"])
        yield environment


def test_acesso_places_everto_in_the_e_block_and_keeps_the_text(env):
    with main.app.app_context():
        conn = main.get_db_connection()
        for nome, email in ORDER_FIXTURE:
            _seed_admin(conn, nome, email)
        conn.commit()

    html = env["client"].get("/admin/acesso").get_data(as_text=True)
    names = [n for n in _admin_names(html) if n in {nome for nome, _ in ORDER_FIXTURE}]
    assert names == ["Eduardo Ordem", EVERTO, "Felipe Ordem", "João Ordem", "Victor Ordem", "Wandrew Ordem"]
    everything = _admin_names(html)
    assert everything[-1] != EVERTO, "Éverto is still last"
    # Display text is preserved byte-for-byte.
    assert f'data-user-nome="{EVERTO}"' in html
    assert f"<strong>{EVERTO}</strong>" in html

    desc = _admin_names(env["client"].get("/admin/acesso?s=nome&dir=desc").get_data(as_text=True))
    desc = [n for n in desc if n in {nome for nome, _ in ORDER_FIXTURE}]
    assert desc == list(reversed(names))


def test_acesso_server_search_ignores_accents_and_case(env):
    with main.app.app_context():
        conn = main.get_db_connection()
        for nome, email in ORDER_FIXTURE:
            _seed_admin(conn, nome, email)
        conn.commit()
    client = env["client"]
    for query, expected in (("everto", EVERTO), ("ÉVERTO", EVERTO), ("joao", "João Ordem")):
        for param in ("q", "nome"):
            names = _admin_names(client.get(f"/admin/acesso?{param}={query}").get_data(as_text=True))
            assert names == [expected], (param, query, names)
    # A technical field keeps its own semantics: the e-mail filter is a plain
    # case-insensitive contains, exactly as before.
    names = _admin_names(client.get("/admin/acesso?email=EVERTO.ORDEM@").get_data(as_text=True))
    assert names == [EVERTO]


def test_alunos_list_order_and_name_filter(env):
    with main.app.app_context():
        conn = main.get_db_connection()
        for index, (nome, email) in enumerate(ORDER_FIXTURE):
            _seed_aluno(conn, nome, email, f"HT.{index:03d}")
        conn.commit()
    client = env["client"]
    ours = {nome for nome, _ in ORDER_FIXTURE}
    names = [n for n in _first_cells(client.get("/admin/alunos").get_data(as_text=True), "alunos-list") if n in ours]
    assert names == ["Eduardo Ordem", EVERTO, "Felipe Ordem", "João Ordem", "Victor Ordem", "Wandrew Ordem"]
    filtered = _first_cells(client.get("/admin/alunos?nome=everto").get_data(as_text=True), "alunos-list")
    assert filtered == [EVERTO]


def test_atividades_order_and_name_filter(env):
    with main.app.app_context():
        conn = main.get_db_connection()
        for nome in ("Ética profissional", "Estágio supervisionado", "Feira técnica", "Monitoria voluntária."):
            base_id = conn.execute(
                "INSERT INTO atividade_base (nome_conceito, status) VALUES (?, 'ativo')", (nome,)
            ).lastrowid
            conn.execute(
                "INSERT INTO atividade_versao (atividade_base_id, eixo, grupo, numero_versao, status)"
                " VALUES (?, 'AAC', '4 - Ordem humana', 1, 'ativa')", (base_id,),
            )
        conn.commit()
    client = env["client"]
    html = client.get("/admin/atividades?s=nome&dir=asc").get_data(as_text=True)
    names = [html_module.unescape(n) for n in re.findall(r'data-atividade-nome="([^"]*)"', html)]
    picked = [n for n in names if n in {"Ética profissional", "Estágio supervisionado", "Feira técnica"}]
    assert picked == ["Estágio supervisionado", "Ética profissional", "Feira técnica"]
    for query in ("moni", "monitoria", "Monitoria", "MONITORIA", "voluntaria"):
        filtered = client.get(f"/admin/atividades?nome={query}").get_data(as_text=True)
        assert 'data-atividade-nome="Monitoria voluntária."' in filtered, query
    # A legitimate filter still excludes it.
    excluded = client.get(
        "/admin/atividades?nome=moni&tipo=Extens%C3%A3o+Universit%C3%A1ria"
    ).get_data(as_text=True)
    assert 'data-atividade-nome="Monitoria voluntária."' not in excluded


def test_cursos_and_matrizes_order_by_the_human_key(env):
    with main.app.app_context():
        conn = main.get_db_connection()
        for codigo, nome in (("ZZ1", "Ética Aeronáutica"), ("ZZ2", "Engenharia"), ("ZZ3", "Física")):
            conn.execute(
                "INSERT INTO cursos (nome, codigo, duracao_periodos, periodo, status) VALUES (?, ?, 4, 'integral', 'ativo')",
                (nome, codigo),
            )
        conn.commit()
    client = env["client"]
    names = _first_cells(client.get("/admin/cursos?s=nome&dir=asc").get_data(as_text=True), "cursos-list", 1)
    picked = [n for n in names if n in {"Engenharia", "Ética Aeronáutica", "Física"}]
    assert picked == ["Engenharia", "Ética Aeronáutica", "Física"]
    assert _first_cells(client.get("/admin/cursos?nome=etica").get_data(as_text=True), "cursos-list", 1) == [
        "Ética Aeronáutica"
    ]


def _curso_options(html: str) -> list[tuple[str, bool]]:
    select = html.split('<select class="control" name="curso_id" required>', 1)[1].split("</select>", 1)[0]
    return [
        (html_module.unescape(re.sub(r"\s+", " ", text).strip()), "selected" in attrs)
        for attrs, text in re.findall(r"<option([^>]*)>(.*?)</option>", select, re.S)
    ]


def test_turma_add_and_edit_curso_selects_use_human_order(env):
    """The Curso <select> of Adicionar Turma and Editar Turma, for N courses.

    Binary ``ORDER BY nome`` put every accented initial after "Z":
    Meteorologia, Programa..., Álgebra..., Ética... -- the human order is
    Álgebra, Ética, Meteorologia, Programa. Inactive courses stay out.
    """
    with main.app.app_context():
        conn = main.get_db_connection()
        for nome, codigo, status in (
            ("Meteorologia", "MET", "ativo"),
            ("Ética Operacional", "ETI", "ativo"),
            ("Álgebra Aeronáutica", "ALG", "ativo"),
            ("Ábaco Desativado", "ABA", "inativo"),
        ):
            conn.execute(
                "INSERT INTO cursos (nome, codigo, duracao_periodos, periodo, status) VALUES (?, ?, 4, 'integral', ?)",
                (nome, codigo, status),
            )
        conn.commit()
        binary = [r[0] for r in conn.execute("SELECT nome FROM cursos WHERE status='ativo' ORDER BY nome")]
        turma_id, turma_curso = conn.execute("SELECT id, curso_id FROM turmas ORDER BY id LIMIT 1").fetchone()
        turma_curso_nome = conn.execute("SELECT nome FROM cursos WHERE id=?", (turma_curso,)).fetchone()[0]
    # The defect: binary order puts the accented initials after every ASCII one.
    assert binary[-2:] == ["Álgebra Aeronáutica", "Ética Operacional"]

    # The fixture database also carries its default active courses ("Geral",
    # "Programa Piloto de Aviação"); the human order interleaves them by letter.
    expected = ["Álgebra Aeronáutica", "Ética Operacional", "Geral", "Meteorologia", "Programa Piloto de Aviação"]
    assert sorted(binary, key=ptbr_text_sort_key) == expected
    with main.app.test_request_context():
        from flask import url_for

        add_url = url_for("admin_adicionar_turma")
        edit_url = url_for("admin_editar_turma", turma_id=turma_id)
    client = env["client"]

    def names(options):
        return [re.sub(r" \([^)]*\)$", "", text) for text, _ in options]

    add_options = _curso_options(client.get(add_url).get_data(as_text=True))
    edit_options = _curso_options(client.get(edit_url).get_data(as_text=True))
    for options in (add_options, edit_options):
        assert names(options) == expected
        # Original text, accents intact; the inactive course stays out.
        assert "Álgebra Aeronáutica (ALG)" in [text for text, _ in options]
        assert "Ábaco Desativado" not in names(options)
    # The edit form still pre-selects the Turma's own Curso, and only it.
    assert [name for name, (_, selected) in zip(names(edit_options), edit_options) if selected] == [turma_curso_nome]


def test_reportes_aluno_filter_and_requisicoes_search(env):
    client = env["client"]
    _response, created = create_admin_request(client, name="Human text request")
    assert created is not None
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("UPDATE alunos SET nome=? WHERE id=(SELECT MIN(id) FROM alunos)", (EVERTO,))
        aluno_id = conn.execute("SELECT MIN(id) FROM alunos").fetchone()[0]
        conn.execute(
            "INSERT INTO reportes (aluno_id, titulo, descricao, categoria) VALUES (?, 'Relatório ótico', 'x', 'Bug na plataforma')",
            (aluno_id,),
        )
        conn.commit()
    for url in ("/admin/reportes?aluno=everto", "/admin/reportes?titulo=relatorio%20otico", "/admin/reportes?q=EVERTO"):
        assert "Relatório ótico" in client.get(url).get_data(as_text=True), url
    assert "Relatório ótico" not in client.get("/admin/reportes?aluno=joao").get_data(as_text=True)
    html = client.get("/admin/requisicoes?q=everto").get_data(as_text=True)
    assert EVERTO in html and 'data-req-id="' in html
    assert 'data-req-id="' not in client.get("/admin/requisicoes?q=zzzz-nada").get_data(as_text=True)


def test_non_alphabetical_orders_are_unchanged(env):
    with main.app.app_context():
        conn = main.get_db_connection()
        for nome, email in ORDER_FIXTURE:
            _seed_admin(conn, nome, email)
        conn.commit()
    client = env["client"]
    # E-mail order stays a plain lower-case order of the address.
    html = client.get("/admin/acesso?s=email&dir=asc").get_data(as_text=True)
    emails = [e for e in re.findall(r'data-user-email="([^"]*)"', html) if e.endswith("ordem@example.test")]
    assert emails == sorted(emails)
    # Atividades by version count keeps numbers first.
    html = client.get("/admin/atividades?s=versoes&dir=desc").get_data(as_text=True)
    counts = [int(c) for c in _first_cells(html, "atividades-list", 3)]
    assert counts and counts == sorted(counts, reverse=True)


# --------------------------------------------------------------------------
# Client side: the browser mirror and the live search
# --------------------------------------------------------------------------

cdp = pytest.importorskip("tests.cdp_browser_support")
BINARY = cdp.find_chromium()
browser_only = pytest.mark.skipif(BINARY is None, reason="no Chromium binary for the browser harness")

PARITY_FIXTURE = [
    EVERTO, "ÉVERTO", "éverto", "João", "Cauã", "Mário", "Conceição", "ÁÀÂÃÄ éèêë íìîï óòôõö úùûü ç",
    unicodedata.normalize("NFD", "Éverto"), "  Muitos   espaços  ", "1º semestre", "Monitoria voluntária.",
]


@pytest.fixture
def page(env):
    with main.app.app_context():
        conn = main.get_db_connection()
        for nome, email in ORDER_FIXTURE:
            _seed_admin(conn, nome, email)
        conn.commit()
    session = cdp.BrowserSession(env["client"], BINARY)
    try:
        yield session
    finally:
        session.close()


def _type(session, selector: str, text: str) -> None:
    import json

    session.evaluate(
        "(() => { const i = document.querySelector(%s); i.value = %s;"
        " i.dispatchEvent(new Event('input', {bubbles: true})); return true; })()"
        % (json.dumps(selector), json.dumps(text))
    )


VISIBLE_NAMES = """(() => Array.from(document.querySelectorAll('#acesso-list .impresso-card[role="listitem"]'))
  .filter(r => r.getClientRects().length).map(r => r.dataset.userNome))()"""


@browser_only
def test_browser_key_is_the_python_key(page):
    page.goto("/admin/acesso")
    import json

    browser = page.evaluate(
        "(() => %s.map(v => window.SGAAHumanText.key(v)))()" % json.dumps(PARITY_FIXTURE)
    )
    assert browser == [human_text_key(value) for value in PARITY_FIXTURE]


@browser_only
def test_acesso_live_search_finds_accented_names_without_accents(page):
    page.goto("/admin/acesso")
    rendered = page.evaluate(VISIBLE_NAMES)
    ours = [n for n in rendered if n in {nome for nome, _ in ORDER_FIXTURE}]
    assert ours == ["Eduardo Ordem", EVERTO, "Felipe Ordem", "João Ordem", "Victor Ordem", "Wandrew Ordem"]
    for query, expected in (("everto", [EVERTO]), ("EVERTO", [EVERTO]), ("joao ordem", ["João Ordem"])):
        _type(page, "#busca-acesso", query)
        assert page.evaluate(VISIBLE_NAMES) == expected, query
