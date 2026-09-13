"""
Matrix form bottom action (Voltar/Cancelar) must leave the matrix editor.

Regression guard: the composition tabs (Lista de AAC / Lista de AEU) used to
point the bottom action at admin_editar_matriz with the CURRENT tab, so
"Voltar" simply reloaded the very page the user was trying to leave.

Covers, for all three tabs (dados / aac / aea):
 1. the bottom action href resolves to the Matrizes list;
 2. the bottom action href is NOT the current editor URL;
 3. the tab links still navigate inside the same Matrix.
"""
import os
import re
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main


BACK_ACTION_RE = re.compile(
    r'<div class="form-actions center">\s*<a class="btn" href="([^"]*)"[^>]*>(.*?)</a>',
    re.DOTALL,
)


@pytest.fixture(scope="module")
def client():
    app = main.app
    with app.app_context():
        main.init_db()
        yield app.test_client()


def _login_admin(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["user_type"] = "admin"
        sess["user_name"] = "Administrador"


@pytest.fixture(scope="module")
def matriz_id():
    matrix_name = "Matriz Teste Voltar Navegacao"
    with main.app.app_context():
        conn = main.get_db_connection()
        main.ensure_matrizes_atividades_table(conn)
        main.ensure_matriz_atividade_links_table(conn)
        curso = conn.execute("SELECT id FROM cursos ORDER BY id LIMIT 1").fetchone()
        assert curso is not None
        conn.execute("DELETE FROM matrizes_atividades WHERE nome = ?", (matrix_name,))
        created = conn.execute(
            """INSERT INTO matrizes_atividades (
                   curso_id, nome, status, data_inicio_vigencia, data_fim_vigencia,
                   horas_aac_obrigatorias, horas_extensao_obrigatorias, descricao
               ) VALUES (?, ?, 'rascunho', '2026-01-01', '2026-12-31', 180, 90, ?)
               RETURNING id""",
            (curso["id"], matrix_name, "Regressao de navegacao"),
        ).fetchone()["id"]
        conn.commit()

    yield created

    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("DELETE FROM matrizes_atividades WHERE id = ?", (created,))
        conn.commit()


@pytest.mark.parametrize("tab", ["dados", "aac", "aea"])
def test_matriz_form_back_action_returns_to_matrix_list(client, matriz_id, tab):
    _login_admin(client)

    current_url = f"/admin/editar_matriz/{matriz_id}?tab={tab}"
    response = client.get(current_url)
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    match = BACK_ACTION_RE.search(html)
    assert match is not None, f"bottom form action not rendered for tab={tab}"
    href, label = match.group(1), match.group(2)

    assert "Voltar" in label or "Cancelar" in label

    # Leaves the editor: never the page we are standing on.
    assert href != current_url
    assert f"/admin/editar_matriz/{matriz_id}" not in href

    # Resolves to the Matrizes list.
    with main.app.test_request_context():
        assert href == main.url_for("admin_matrizes")

    # Tabs still navigate inside the same Matrix.
    assert f'href="/admin/editar_matriz/{matriz_id}?tab=aac"' in html
    assert f'href="/admin/editar_matriz/{matriz_id}?tab=aea"' in html
    assert f'href="/admin/editar_matriz/{matriz_id}?tab=dados"' in html
