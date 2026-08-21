import os
import re
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main


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


def test_admin_matrizes_list_create_transfer_and_delete(client):
    matrix_name = "Matriz Teste Automatizada"
    activity_name = "AAC Teste Matriz Automatizada"

    with main.app.app_context():
        conn = main.get_db_connection()
        main.ensure_matrizes_atividades_table(conn)
        main.ensure_matriz_atividade_links_table(conn)
        curso = conn.execute("SELECT id FROM cursos ORDER BY id LIMIT 1").fetchone()
        assert curso is not None
        norma_id = conn.execute(
            """INSERT INTO norma_atividade(codigo,eixo,revisao,nome,status)
                 VALUES ('AAC-matrix-test','AAC','test','Norma matrix test','ativa') RETURNING id"""
        ).fetchone()["id"]
        conn.execute("DELETE FROM matrizes_atividades WHERE nome = ?", (matrix_name,))
        base_id = conn.execute(
            "INSERT INTO atividade_base(nome_conceito,descricao,status) VALUES (?,?,'ativo') RETURNING id",
            (activity_name, "Automated matrix test"),
        ).fetchone()["id"]
        activity_id = conn.execute(
            """INSERT INTO atividade_versao
                   (atividade_base_id,norma_id,codigo_normativo,eixo,grupo,limite_total,numero_versao,status)
                 VALUES (?,?,'AAC-test','AAC','99 - Grupo Automatizado',16,1,'ativa') RETURNING id""",
            (base_id, norma_id),
        ).fetchone()["id"]
        conn.commit()

    _login_admin(client)

    listing = client.get("/admin/matrizes")
    assert listing.status_code == 200
    assert "Matrizes de atividades" in listing.get_data(as_text=True)

    create = client.post(
        "/admin/adicionar_matriz",
        data={
            "curso_id": curso["id"],
            "nome": matrix_name,
            "versao": "2026.1",
            "status": "vigente",
            "data_inicio_vigencia": "2026-01-01",
            "data_fim_vigencia": "2026-12-31",
            "horas_aac_obrigatorias": 180,
            "horas_extensao_obrigatorias": 90,
            "descricao": "Fluxo automatizado de matrizes",
        },
        follow_redirects=False,
    )
    assert create.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        matriz = conn.execute(
            "SELECT id, status, horas_aac_obrigatorias, horas_extensao_obrigatorias FROM matrizes_atividades WHERE nome = ?",
            (matrix_name,),
        ).fetchone()
        assert matriz is not None
        assert matriz["status"] == "vigente"
        assert matriz["horas_aac_obrigatorias"] == 180
        assert matriz["horas_extensao_obrigatorias"] == 90
        matriz_id = matriz["id"]
        conn.execute("INSERT INTO matriz_norma(matriz_id,norma_id) VALUES (?,?)", (matriz_id, norma_id))
        conn.commit()

    edit_tab = client.get(f"/admin/editar_matriz/{matriz_id}?tab=aac")
    assert edit_tab.status_code == 200
    edit_tab_html = edit_tab.get_data(as_text=True)
    assert activity_name in edit_tab_html
    assert "transfer_meta.toast_message" not in edit_tab_html
    assert "window.showToast?.('', 'success');" not in edit_tab_html

    save_transfer = client.post(
        f"/admin/editar_matriz/{matriz_id}?tab=aac",
        data={
            "active_tab": "aac",
            "selected_activity_ids": [str(activity_id)],
        },
        follow_redirects=True,
    )
    assert save_transfer.status_code == 200
    save_transfer_html = save_transfer.get_data(as_text=True)
    assert "Lista da matriz atualizada com sucesso." in save_transfer_html
    assert not re.search(r'<div class="flash flash-success">\s*</div>', save_transfer_html)

    with main.app.app_context():
        conn = main.get_db_connection()
        linked = conn.execute(
            "SELECT 1 FROM matriz_atividade_versao_item WHERE matriz_id = ? AND atividade_versao_id = ?",
            (matriz_id, activity_id),
        ).fetchone()
        assert linked is not None

    delete = client.post(f"/admin/matrizes/{matriz_id}/excluir", follow_redirects=False)
    assert delete.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        removed_matriz = conn.execute("SELECT 1 FROM matrizes_atividades WHERE id = ?", (matriz_id,)).fetchone()
        removed_link = conn.execute(
            "SELECT 1 FROM matriz_atividade_versao_item WHERE matriz_id = ? AND atividade_versao_id = ?",
            (matriz_id, activity_id),
        ).fetchone()
        conn.execute("DELETE FROM atividade_versao WHERE id = ?", (activity_id,))
        conn.execute("DELETE FROM atividade_base WHERE id = ?", (base_id,))
        conn.execute("DELETE FROM norma_atividade WHERE id = ?", (norma_id,))
        conn.commit()
        assert removed_matriz is None
        assert removed_link is None


def test_flash_component_ignores_blank_messages(client):
    _login_admin(client)

    with client.session_transaction() as sess:
        sess["_flashes"] = [
            ("success", "   "),
            ("success", "Mensagem válida"),
            ("warning", None),
        ]

    response = client.get("/admin/matrizes")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "Mensagem válida" in html
    assert not re.search(r'<div class="flash flash-success">\s*</div>', html)
    assert not re.search(r'<div class="flash flash-warning">\s*</div>', html)


def test_base_show_toast_ignores_blank_messages(client):
    _login_admin(client)

    response = client.get("/admin/matrizes")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "const text = window.appResolveRuntimeMessage(msg);" in html
    assert "if (!text) {" in html


def test_admin_matrizes_filter_schema_and_typed_filters(client):
    suffix = os.urandom(3).hex().upper()
    matrix_a = f"Matriz Filtro Tipado A {suffix}"
    matrix_b = f"Matriz Filtro Tipado B {suffix}"

    _login_admin(client)

    with main.app.app_context():
        conn = main.get_db_connection()
        curso = conn.execute("SELECT id FROM cursos ORDER BY id LIMIT 1").fetchone()
        assert curso is not None
        curso_id = curso["id"]

    create_a = client.post(
        "/admin/adicionar_matriz",
        data={
            "curso_id": curso_id,
            "nome": matrix_a,
            "versao": "2026.1",
            "status": "vigente",
            "data_inicio_vigencia": "2026-01-10",
            "data_fim_vigencia": "2026-12-20",
            "horas_aac_obrigatorias": 180,
            "horas_extensao_obrigatorias": 80,
            "descricao": "Matriz de filtro tipado A",
        },
        follow_redirects=False,
    )
    assert create_a.status_code in (302, 303)

    create_b = client.post(
        "/admin/adicionar_matriz",
        data={
            "curso_id": curso_id,
            "nome": matrix_b,
            "versao": "2025.2",
            "status": "rascunho",
            "data_inicio_vigencia": "2025-02-01",
            "data_fim_vigencia": "2025-11-30",
            "horas_aac_obrigatorias": 120,
            "horas_extensao_obrigatorias": 40,
            "descricao": "Matriz de filtro tipado B",
        },
        follow_redirects=False,
    )
    assert create_b.status_code in (302, 303)

    try:
        response = client.get(
            "/admin/matrizes",
            query_string={
                "nome": "Tipado A",
                "versao": "2026",
                "status": "vigente",
                "data_inicio_vigencia_min": "2026-01-01",
                "horas_aac_obrigatorias_min": "170",
                "horas_extensao_obrigatorias_max": "90",
            },
        )
        assert response.status_code == 200
        html = response.get_data(as_text=True)

        assert '"param": "nome"' in html
        assert '"param": "versao"' in html
        assert '"param": "data_inicio_vigencia"' in html
        assert '"param": "horas_aac_obrigatorias"' in html
        assert '"type": "text_contains"' in html
        assert '"type": "number_range"' in html
        assert '"type": "date_range"' in html

        assert matrix_a in html
        assert matrix_b not in html
    finally:
        matrix_ids = []
        with main.app.app_context():
            conn = main.get_db_connection()
            rows = conn.execute(
                "SELECT id FROM matrizes_atividades WHERE nome IN (?, ?)",
                (matrix_a, matrix_b),
            ).fetchall()
            matrix_ids = [row["id"] for row in rows]

        for matrix_id in matrix_ids:
            client.post(f"/admin/matrizes/{matrix_id}/excluir", follow_redirects=False)
