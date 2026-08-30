"""Regression contracts for the approved admin list geometries."""

from pathlib import Path
import re

import main

from tests.canonical_matrix_test_support import login_admin
from tests.versioned_test_support import isolated_versioned_app_env


ROOT = Path(__file__).resolve().parents[1]


def test_matrix_list_template_and_grid_have_the_same_six_columns():
    template = (ROOT / "templates" / "admin_matrizes.html").read_text(encoding="utf-8")
    css = (ROOT / "static" / "css" / "components" / "list-cards.css").read_text(
        encoding="utf-8"
    )

    header = re.search(r"cl\.header\(\[(.*?)\]\)\s*}}", template, re.DOTALL)
    row = re.search(r"cl\.row\(\[(.*?)\],\s*\{", template, re.DOTALL)
    grid = re.search(r"\.imp-matrizes\s*\{\s*--imp-cols:(.*?)\s*};", css, re.DOTALL)

    assert header is not None
    assert row is not None
    assert grid is not None

    assert re.findall(r"'text':'([^']+)'", header.group(1)) == [
        "Nome",
        "Curso",
        "Vigência",
        "AAC",
        "Extensão",
        "Status",
    ]
    assert row.group(1).count("'content':") == 6
    assert "matriz.versao" not in row.group(1)
    assert re.findall(r"/\*\s*([^*]+?)\s*\*/", grid.group(1)) == [
        "Nome",
        "Curso",
        "Vigência",
        "AAC",
        "Extensão",
        "Status",
    ]
    assert grid.group(1).count("minmax(") == 6


def test_activity_list_template_and_grid_have_the_same_five_columns():
    template = (ROOT / "templates" / "admin_atividades.html").read_text(encoding="utf-8")
    css = (ROOT / "static" / "css" / "components" / "list-cards.css").read_text(
        encoding="utf-8"
    )

    list_markup = template.split('id="atividades-list"', 1)[1].split("{% endfor %}", 1)[0]
    header = list_markup.split("{% if atividades", 1)[0]
    row = list_markup.split("{% for a in atividades %}", 1)[1]
    grid = re.search(r"\.imp-atividades\s*\{\s*--imp-cols:(.*?)\s*};", css, re.DOTALL)

    assert re.findall(r'<div class="cell [^"]+">([^<]+)</div>', header) == [
        "Tipo",
        "Nome",
        "Grupo",
        "Versões",
        "Limitações",
    ]
    assert row.count('<div class="cell ') == 5
    assert "a.total_versoes" in row
    assert "matriz.versao" not in list_markup
    assert grid is not None
    assert re.findall(r"/\*\s*([^*]+?)\s*\*/", grid.group(1)) == [
        "Tipo",
        "Nome",
        "Grupo",
        "Versões",
        "Limitações",
    ]
    assert grid.group(1).count("minmax(") == 5


def test_course_list_template_and_grid_have_the_same_six_columns():
    template = (ROOT / "templates" / "admin_cursos.html").read_text(encoding="utf-8")
    css = (ROOT / "static" / "css" / "components" / "list-cards.css").read_text(
        encoding="utf-8"
    )

    header = re.search(r"cl\.header\(\[(.*?)\]\)\s*}}", template, re.DOTALL)
    row = re.search(r"cl\.row\(\[(.*?)\],\s*\{", template, re.DOTALL)
    grid = re.search(r"\.imp-cursos\s*\{\s*--imp-cols:(.*?)\s*};", css, re.DOTALL)

    assert header is not None
    assert row is not None
    assert grid is not None
    assert re.findall(r"'text':'([^']+)'", header.group(1)) == [
        "Código",
        "Nome",
        "Duração",
        "Turmas",
        "Alunos",
        "Status",
    ]
    assert row.group(1).count("'content':") == 6
    assert "c.nome or '-'" in row.group(1)
    assert "'class':'left ellipsis'" in row.group(1)
    assert re.findall(r"/\*\s*([^*]+?)\s*\*/", grid.group(1)) == [
        "Código",
        "Nome",
        "Duração",
        "Turmas",
        "Alunos",
        "Status",
    ]
    assert grid.group(1).count("minmax(") == 6


def test_activity_list_shows_total_versions_for_each_base_row(tmp_path):
    with isolated_versioned_app_env(tmp_path, "activity-list-geometry.db") as env:
        login_admin(env["client"])
        with main.app.app_context():
            conn = main.get_db_connection()
            base_id = conn.execute(
                "INSERT INTO atividade_base(nome_conceito) VALUES(?) RETURNING id",
                ("Atividade multiversao para geometria",),
            ).fetchone()[0]
            conn.executemany(
                """INSERT INTO atividade_versao
                   (atividade_base_id,eixo,grupo,numero_versao,status)
                   VALUES (?,'AAC','99 - Geometria',?,'rascunho')""",
                [(base_id, 1), (base_id, 2), (base_id, 3)],
            )
            conn.commit()

        html = env["client"].get(
            "/admin/atividades", query_string={"nome": "Atividade multiversao para geometria"}
        ).get_data(as_text=True)
        matching_rows = [
            segment
            for segment in html.split('<div class="impresso-card" role="listitem"')
            if f'data-base-id="{base_id}"' in segment
        ]

        assert len(matching_rows) == 3
        for row in matching_rows:
            cells = re.findall(r'<div class="cell[^"]*"[^>]*>(.*?)</div>', row, re.DOTALL)
            assert len(cells) == 5
            assert cells[3].strip() == "3"
