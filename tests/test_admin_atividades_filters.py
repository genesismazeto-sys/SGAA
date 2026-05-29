import os
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
    with app.test_client() as client:
        yield client


def _login_admin(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["user_type"] = "admin"
        sess["user_name"] = "Administrador"


def test_admin_atividades_uses_shared_filter_schema_and_backend_filters(client):
    limited_name = "AAC Filtro Padrao Limitada"
    unlimited_name = "AAC Filtro Padrao Sem Limite"
    extension_name = "AEA Filtro Padrao"

    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("DELETE FROM atividades WHERE nome IN (?, ?, ?)", (limited_name, unlimited_name, extension_name))
        conn.execute(
            """
            INSERT INTO atividades (
                grupo, nome, limite_horas, tipo_atividade, tem_limitacao, tipo_limitacao,
                limite_horas_total, limite_horas_semestral, documentos_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("77 - Grupo Filtro", limited_name, None, "Acadêmica Complementar", 1, "total", 12, None, None),
        )
        conn.execute(
            """
            INSERT INTO atividades (
                grupo, nome, limite_horas, tipo_atividade, tem_limitacao, tipo_limitacao,
                limite_horas_total, limite_horas_semestral, documentos_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("78 - Grupo Filtro", unlimited_name, None, "Acadêmica Complementar", 0, None, None, None, None),
        )
        conn.execute(
            """
            INSERT INTO atividades (
                grupo, nome, limite_horas, tipo_atividade, tem_limitacao, tipo_limitacao,
                limite_horas_total, limite_horas_semestral, documentos_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("79 - Grupo Extensao", extension_name, None, "Extensão Universitária", 0, None, None, None, None),
        )
        conn.commit()

    _login_admin(client)

    try:
        page = client.get("/admin/atividades")
        assert page.status_code == 200
        html = page.get_data(as_text=True)
        assert 'id="filter-schema-data"' in html
        assert 'class="popover filter-popover"' in html
        assert "window.initToolbarFilterMenu?.({" in html
        assert '"param": "limitacao"' in html
        assert '"param": "tipo"' in html
        assert '"param": "nome"' in html
        assert '"param": "grupo"' in html
        assert '"type": "text_contains"' in html
        assert "77 - Grupo Filtro" in html

        limited_page = client.get("/admin/atividades?limitacao=limitadas")
        assert limited_page.status_code == 200
        limited_html = limited_page.get_data(as_text=True)
        assert limited_name in limited_html
        assert unlimited_name not in limited_html

        extension_page = client.get("/admin/atividades?tipo=Extens%C3%A3o+Universit%C3%A1ria")
        assert extension_page.status_code == 200
        extension_html = extension_page.get_data(as_text=True)
        assert extension_name in extension_html
        assert limited_name not in extension_html

        nome_page = client.get("/admin/atividades?nome=Padrao+Sem+Limite")
        assert nome_page.status_code == 200
        nome_html = nome_page.get_data(as_text=True)
        assert unlimited_name in nome_html
        assert limited_name not in nome_html
    finally:
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute("DELETE FROM atividades WHERE nome IN (?, ?, ?)", (limited_name, unlimited_name, extension_name))
            conn.commit()


def test_admin_atividades_uses_shared_sort_param_s(client):
    first_name = "AAA Ordenacao Atividades"
    second_name = "ZZZ Ordenacao Atividades"

    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("DELETE FROM atividades WHERE nome IN (?, ?)", (first_name, second_name))
        conn.execute(
            """
            INSERT INTO atividades (
                grupo, nome, limite_horas, tipo_atividade, tem_limitacao, tipo_limitacao,
                limite_horas_total, limite_horas_semestral, documentos_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("88 - Grupo Ordenacao", first_name, None, "Acadêmica Complementar", 0, None, None, None, None),
        )
        conn.execute(
            """
            INSERT INTO atividades (
                grupo, nome, limite_horas, tipo_atividade, tem_limitacao, tipo_limitacao,
                limite_horas_total, limite_horas_semestral, documentos_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("88 - Grupo Ordenacao", second_name, None, "Acadêmica Complementar", 0, None, None, None, None),
        )
        conn.commit()

    _login_admin(client)

    try:
        page = client.get("/admin/atividades?s=nome&dir=desc")
        assert page.status_code == 200
        html = page.get_data(as_text=True)
        assert second_name in html
        assert first_name in html
        assert html.index(second_name) < html.index(first_name)
    finally:
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute("DELETE FROM atividades WHERE nome IN (?, ?)", (first_name, second_name))
            conn.commit()