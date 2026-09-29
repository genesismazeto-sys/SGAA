"""DS-EMPTY-TABLE-STATE: an empty ordinary list/table shows only its message.

Observed defect (Reportes, zero reports): the column-header row
"# · Data · Categoria · Título · Status" still rendered, with
"Nenhum reporte enviado ainda." beneath it.  Other lists did the same, and
three ``<table>`` surfaces put the message in a fake ``<tr><td colspan>`` row
under visible headers.

Contract, owned once by ``components/card_list.html`` ``collection``:

* rows      -> the caller renders: column-header row + rows (grid or table);
* zero rows -> only the surface's own empty-state message, in the shared DS
  ``.table-empty`` class -- no header row, no fake colspan row.

Each surface keeps its established wording.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

import main
from tests.canonical_request_test_support import create_admin_request, login_admin, login_student
from tests.versioned_test_support import isolated_versioned_app_env

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"

HEADER_MARKERS = re.compile(r'cl\.header\(|class="impresso-card header|<thead')
CALL_TAGS = re.compile(r"\{%-?\s*(call\b[^%]*?|endcall)\s*-?%\}")

# Tables that stay outside the owner, each for a stated reason, pinned by count
# so a new table in the same file cannot slip in unexamined.
NON_COLLECTION_THEADS = {
    # Retention: a configuration grid over the fixed GFS windows (always shown).
    # Provider logs and snapshot history: already rendered only when rows exist
    # ({% if google_backup_logs %} / {% if backups %} with its own .db-note).
    "admin_banco_dados.html": 4,
    # Per-eixo diagnostic table: already rendered only when the eixo has items,
    # otherwise its own .diag-empty paragraph.
    "admin_diagnostico_atividades_versionadas_view.html": 1,
    # Import preview: a step of the CSV import form, not a stored collection.
    "admin_importar_atividades.html": 1,
    # Not rendered by any view.
    "admin_turma_form.html": 1,
}


def _enclosing_calls(source: str, position: int) -> list[str]:
    stack: list[str] = []
    for match in CALL_TAGS.finditer(source, 0, position):
        tag = match.group(1)
        if tag == "endcall":
            stack.pop()
        else:
            stack.append(tag)
    return stack


# --------------------------------------------------------------------------
# The shared owner
# --------------------------------------------------------------------------


def _render(source: str, **context) -> str:
    with main.app.app_context():
        return main.app.jinja_env.from_string(source).render(**context)


COLLECTION = (
    "{% import 'components/card_list.html' as cl %}"
    "{% call cl.collection(rows, 'Nenhum item aqui.') %}HEADER{% for r in rows %}[{{ r }}]{% endfor %}{% endcall %}"
)


@pytest.mark.parametrize("rows", [[], None])
def test_zero_rows_render_only_the_message(rows):
    assert _render(COLLECTION, rows=rows).strip() == '<div class="table-empty">Nenhum item aqui.</div>'


def test_undefined_rows_render_only_the_message():
    assert _render(COLLECTION).strip() == '<div class="table-empty">Nenhum item aqui.</div>'


def test_rows_render_header_and_rows_and_no_message():
    assert _render(COLLECTION, rows=["a", "b"]).strip() == "HEADER[a][b]"


def test_every_list_header_row_is_owned_by_the_collection_contract():
    offenders = []
    thead_counts: dict[str, int] = {}
    for path in sorted(TEMPLATES.rglob("*.html")):
        rel = path.relative_to(TEMPLATES).as_posix()
        if rel == "components/card_list.html":
            continue  # defines header(); callers are what is checked
        source = path.read_text(encoding="utf-8")
        for match in HEADER_MARKERS.finditer(source):
            if any(tag.startswith("call cl.collection(") for tag in _enclosing_calls(source, match.start())):
                continue
            if match.group(0) == "<thead" and rel in NON_COLLECTION_THEADS:
                thead_counts[rel] = thead_counts.get(rel, 0) + 1
                continue
            line = source.count("\n", 0, match.start()) + 1
            offenders.append(f"{rel}:{line} {match.group(0)}")
    assert offenders == [], "header rows outside cl.collection: " + ", ".join(offenders)
    assert thead_counts == NON_COLLECTION_THEADS


def test_no_template_puts_an_empty_message_in_a_fake_row():
    offenders = []
    for path in sorted(TEMPLATES.rglob("*.html")):
        source = path.read_text(encoding="utf-8")
        for match in re.finditer(r"<td[^>]*colspan[^>]*>\s*Nenhu", source):
            offenders.append(f"{path.relative_to(TEMPLATES).as_posix()}:{source.count(chr(10), 0, match.start()) + 1}")
    assert offenders == []


# --------------------------------------------------------------------------
# Rendered surfaces
# --------------------------------------------------------------------------

# url, empty-state message, list container id, action-menu button id
ADMIN_LISTS = [
    ("/admin/alunos", "Nenhum aluno encontrado.", "alunos-list", "btn-alunos-actions"),
    ("/admin/turmas", "Nenhuma turma cadastrada.", "turmas-list", "btn-turmas-actions"),
    ("/admin/cursos", "Nenhum curso cadastrado.", "cursos-list", "btn-cursos-actions"),
    ("/admin/matrizes", "Nenhuma matriz cadastrada.", "matrizes-list", "btn-matrizes-actions"),
    ("/admin/atividades", "Nenhuma atividade encontrada.", "atividades-list", "btn-atividades-actions"),
    ("/admin/requisicoes", "Nenhuma requisição encontrada.", "requisicoes-list", "btn-req-actions"),
    ("/admin/reportes", "Nenhum reporte encontrado com os filtros atuais.", "reportes-list", "btn-reportes-actions"),
    ("/admin/alertas", "Nenhum alerta cadastrado.", "alertas-list", "btn-alertas-actions"),
    ("/admin/arquivos", "Nenhum arquivo cadastrado.", "arquivos-list", "btn-arquivos-actions"),
]


def _db(env):
    conn = sqlite3.connect(str(env["db_path"]))
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _assert_empty_state(html: str, message: str, where: str):
    assert f'<div class="table-empty">{message}</div>' in html, where
    assert "impresso-card header" not in html, f"{where}: header row rendered with zero rows"
    assert "<thead" not in html, f"{where}: table header rendered with zero rows"
    assert "colspan" not in html, f"{where}: fake colspan row"


def _assert_populated(html: str, message: str, where: str):
    assert "impresso-card header" in html, f"{where}: header row missing"
    assert re.search(r'class="impresso-card[^"]*"[^>]*role="listitem"', html), f"{where}: no row"
    assert 'class="table-empty"' not in html and message not in html, f"{where}: empty message with rows"


@pytest.fixture
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "ds-empty-table.db") as environment:
        login_admin(environment["client"])
        yield environment


def _populate(env):
    client = env["client"]
    _response, created = create_admin_request(client, name="DS empty populated")
    assert created is not None
    conn = _db(env)
    aluno_id = conn.execute("SELECT id FROM alunos ORDER BY id LIMIT 1").fetchone()[0]
    conn.execute("INSERT INTO reportes(aluno_id,titulo,descricao,categoria) VALUES (?,?,?,?)",
                 (aluno_id, "Reporte DS", "Descrição", "Bug na plataforma"))
    conn.execute("INSERT INTO admin_alertas(titulo,mensagem) VALUES ('Alerta DS','Mensagem')")
    conn.execute("INSERT INTO admin_arquivos(titulo,filename,original_filename) VALUES ('Arquivo DS','ds.pdf','ds.pdf')")
    conn.commit()
    conn.close()
    return created


def _wipe_everything(env):
    conn = _db(env)
    conn.execute("PRAGMA foreign_keys=OFF")
    for table in (
        "requisicao_alerta_receipts", "requisicao_arquivos", "requisicao_email_eventos", "email_envios",
        "requisicoes", "reportes", "admin_arquivos", "admin_alertas", "alunos", "turmas",
        "matriz_atividade_versao_item", "matrizes_atividades", "atividade_transicao", "atividade_versao",
        "atividade_base", "cursos",
    ):
        conn.execute(f"DELETE FROM {table}")
    conn.execute("DELETE FROM usuario_credenciais WHERE usuario_id IN (SELECT id FROM usuarios WHERE tipo<>'admin')")
    conn.execute("DELETE FROM usuarios WHERE tipo<>'admin'")
    conn.commit()
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()


def test_admin_lists_with_rows_keep_their_headers(env):
    _populate(env)
    client = env["client"]
    for url, message, list_id, actions in ADMIN_LISTS:
        html = client.get(url).get_data(as_text=True)
        _assert_populated(html, message, url)
        assert f'id="{list_id}"' in html and f'id="{actions}"' in html, url


def test_admin_lists_with_zero_rows_show_only_their_message(env):
    _wipe_everything(env)
    client = env["client"]
    for url, message, list_id, actions in ADMIN_LISTS:
        response = client.get(url)
        assert response.status_code == 200, url
        html = response.get_data(as_text=True)
        _assert_empty_state(html, message, url)
        # The list container (JS binds to it) and the action menu survive.
        assert f'id="{list_id}"' in html and f'id="{actions}"' in html, url
    acesso = client.get("/admin/acesso?q=zzzz-sem-resultado").get_data(as_text=True)
    _assert_empty_state(acesso, "Nenhum acesso encontrado.", "/admin/acesso")
    assert 'id="acesso-list"' in acesso and 'id="btn-acesso-actions"' in acesso
    for url in ("/admin/atividades/academicas", "/admin/atividades/extensao"):
        _assert_empty_state(client.get(url).get_data(as_text=True), "Nenhuma atividade encontrada.", url)


def test_detail_lists_follow_the_same_contract(env):
    client = env["client"]
    conn = _db(env)
    turma_id, curso_id = conn.execute(
        "SELECT t.id, t.curso_id FROM turmas t JOIN alunos a ON a.turma_id=t.id ORDER BY t.id LIMIT 1"
    ).fetchone()
    base_id = conn.execute("SELECT id FROM atividade_base ORDER BY id LIMIT 1").fetchone()[0]
    empty_curso = conn.execute(
        "INSERT INTO cursos(codigo,nome,duracao_periodos,status) VALUES ('DSVAZIO','Curso vazio DS',4,'ativo')"
    ).lastrowid
    empty_turma = conn.execute(
        "INSERT INTO turmas(nome,codigo,curso_id,matriz_id,numero,semestre_inicio,ano_inicio,status) "
        "SELECT 'DS vazia','DSVAZIA',curso_id,matriz_id,99,1,2026,'Ativa' FROM turmas WHERE id=?", (turma_id,)
    ).lastrowid
    conn.commit()
    conn.close()

    populated_turma = client.get(f"/admin/turma/{turma_id}").get_data(as_text=True)
    _assert_populated(populated_turma, "Nenhum aluno vinculado a esta turma.", "turma")
    _assert_empty_state(client.get(f"/admin/turma/{empty_turma}").get_data(as_text=True),
                        "Nenhum aluno vinculado a esta turma.", "turma vazia")

    populated_curso = client.get(f"/admin/cursos/{curso_id}").get_data(as_text=True)
    _assert_populated(populated_curso, "Nenhuma turma cadastrada.", "curso")
    _assert_empty_state(client.get(f"/admin/cursos/{empty_curso}").get_data(as_text=True),
                        "Nenhuma turma cadastrada.", "curso vazio")

    versions = client.get(f"/admin/catalogo-versoes/{base_id}").get_data(as_text=True)
    assert "impresso-card header" in versions  # versions exist
    assert '<div class="table-empty">Nenhuma transição registrada.</div>' in versions
    assert '<table class="table transition-table">' not in versions  # no transitions -> no table header


# --------------------------------------------------------------------------
# Student surfaces, incl. the observed Reportes defect
# --------------------------------------------------------------------------

STUDENT_LISTS = [
    ("/aluno/reportar", "Nenhum reporte enviado ainda.", "meus-reportes-list"),
    ("/aluno/requisicoes", "Nenhuma requisição encontrada.", "minhas-requisicoes-list"),
    ("/aluno/arquivos", "Nenhum arquivo disponível.", "aluno-arquivos-list"),
]


def _as_student(env):
    client = env["client"]
    with client.session_transaction() as session:
        session.clear()
    login_student(client)
    return client


def test_student_reportes_with_zero_reports_shows_only_the_message(env):
    client = _as_student(env)
    html = client.get("/aluno/reportar").get_data(as_text=True)
    listing = html.split('id="meus-reportes-list"', 1)[1].split("</div>\n    </div>", 1)[0]
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", listing)).strip()
    assert text.endswith("Nenhum reporte enviado ainda.")
    for column in ("Data", "Categoria", "Titulo", "Status"):
        assert f'<div class="cell center">{column}</div>' not in html
        assert f'<div class="cell left">{column}</div>' not in html
    # The report form above the list is untouched.
    assert 'name="titulo"' in html and 'name="categoria"' in html


def test_student_lists_follow_the_contract_in_both_states(env):
    client = _as_student(env)
    for url, message, list_id in STUDENT_LISTS:
        html = client.get(url).get_data(as_text=True)
        _assert_empty_state(html, message, url)
        assert f'id="{list_id}"' in html, url

    with client.session_transaction() as session:
        session.clear()
    login_admin(client)
    _populate(env)
    client = _as_student(env)
    for url, message, list_id in STUDENT_LISTS:
        html = client.get(url).get_data(as_text=True)
        _assert_populated(html, message, url)
        assert f'id="{list_id}"' in html, url
    assert 'id="btn-aluno-req-actions"' in client.get("/aluno/requisicoes").get_data(as_text=True)


LIST_TABLE = (
    "{% set cols = [{'key': 'id', 'label': '#'}, {'key': 'nome', 'label': 'Nome'}] %}"
    "{% include 'components/list_table.html' %}"
)


@pytest.mark.parametrize("rows", [[], None])
def test_list_table_component_with_zero_rows_shows_only_its_message(rows):
    # components/list_table.html applies the contract itself. (Its only page
    # consumer, the aluno Painel "Requisições Recentes" blocks, was removed by
    # UI-B29; the component is kept as a DS table.)
    html = _render(LIST_TABLE, rows=rows)
    _assert_empty_state(html, "Nenhum item encontrado.", "list_table vazio")


def test_list_table_component_with_rows_renders_header_and_rows():
    html = _render(LIST_TABLE, rows=[{"id": 7, "nome": "Linha"}])
    assert re.findall(r"<th>([^<]*)</th>", html) == ["#", "Nome"]
    assert "<td>7</td>" in html and "<td>Linha</td>" in html
    assert "table-empty" not in html and "Nenhum item encontrado." not in html


def test_progresso_section_without_activities_shows_only_its_message(env):
    client = _as_student(env)
    populated = client.get("/aluno/progresso").get_data(as_text=True)
    assert "<thead" in populated and "table-empty" not in populated

    conn = _db(env)
    conn.execute("DELETE FROM matriz_atividade_versao_item")
    conn.commit()
    conn.close()
    html = client.get("/aluno/progresso").get_data(as_text=True)
    _assert_empty_state(html, "Nenhuma atividade disponivel nesta secao.", "progresso")
