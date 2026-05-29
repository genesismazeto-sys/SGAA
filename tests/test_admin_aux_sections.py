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


def test_admin_alertas_crud(client):
    titulo = "Alerta de teste automatizado"
    bg_color = "#123abc"

    with main.app.app_context():
        conn = main.get_db_connection()
        main.ensure_admin_alertas_table(conn)
        conn.execute("DELETE FROM admin_alertas WHERE titulo = ?", (titulo,))
        conn.commit()

    _login_admin(client)

    create = client.post(
        "/admin/alertas/salvar",
        data={
            "titulo": titulo,
            "mensagem": "Mensagem do alerta automatizado",
            "bg_color": bg_color,
            "visivel": "1",
        },
        follow_redirects=False,
    )
    assert create.status_code in (302, 303)

    page = client.get("/admin/alertas")
    assert page.status_code == 200
    assert titulo in page.get_data(as_text=True)

    with main.app.app_context():
        conn = main.get_db_connection()
        alerta = conn.execute(
            "SELECT id, visivel, bg_color, border_color FROM admin_alertas WHERE titulo = ?",
            (titulo,),
        ).fetchone()
        assert alerta is not None
        alerta_id = alerta["id"]
        assert alerta["bg_color"] == bg_color
        assert alerta["border_color"] == main._alerta_border_for(bg_color)

    toggle = client.post(f"/admin/alertas/{alerta_id}/alternar", follow_redirects=False)
    assert toggle.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        toggled = conn.execute("SELECT visivel FROM admin_alertas WHERE id = ?", (alerta_id,)).fetchone()
        assert toggled is not None
        assert toggled["visivel"] == 0

    delete = client.post(f"/admin/alertas/{alerta_id}/deletar", follow_redirects=False)
    assert delete.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        removed = conn.execute("SELECT 1 FROM admin_alertas WHERE id = ?", (alerta_id,)).fetchone()
        assert removed is None


def test_admin_alertas_exposes_js_permissions_for_floating_actions(client):
    _login_admin(client)

    response = client.get("/admin/alertas")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "const canAlertasEdit = true;" in html
    assert "const canAlertasFull = true;" in html


def test_admin_acesso_defaults_and_create_delete(client):
    email = "consultivo.teste.automatizado@ej.edu.br"
    senha_default = "consultivo_temp_456"

    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("DELETE FROM alunos WHERE email = ?", (email,))
        conn.execute("DELETE FROM usuarios WHERE email = ?", (email,))
        conn.commit()

    _login_admin(client)

    save_defaults = client.post(
        "/admin/acesso/senhas-default",
        data={
            "default_admin_total": "admin123",
            "default_consultivo": senha_default,
            "default_administrativo": "admin123",
            "default_usuario": "aluno123",
            "default_usuario_teste": "teste123",
        },
        follow_redirects=False,
    )
    assert save_defaults.status_code in (302, 303)

    create = client.post(
        "/admin/acesso/salvar",
        data={
            "nome": "Consultivo Automatizado",
            "email": email,
            "nivel_acesso": "consultivo",
            "senha": "",
        },
        follow_redirects=False,
    )
    assert create.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        user = conn.execute(
            "SELECT id, tipo, nivel_acesso, senha FROM usuarios WHERE email = ?",
            (email,),
        ).fetchone()
        assert user is not None
        assert user["tipo"] == "admin"
        assert user["nivel_acesso"] == "consultivo"
        assert main.check_password(user["senha"], senha_default)
        user_id = user["id"]

    delete = client.post(f"/admin/acesso/{user_id}/deletar", follow_redirects=False)
    assert delete.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        removed = conn.execute("SELECT 1 FROM usuarios WHERE id = ?", (user_id,)).fetchone()
        assert removed is None


def test_admin_acesso_page_enables_shared_row_selection(client):
    _login_admin(client)

    response = client.get("/admin/acesso")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "enableSelectAllButton: false" in html
    assert "enableBulkDelete: false" in html
    assert "toolbarSelector: '#acesso-toolbar'" in html
    assert "rowsRootSelector: '#acesso-list'" in html
    assert 'id="btn-acesso-actions"' in html
    assert 'id="access-actions-menu"' in html
    assert 'id="access-action-select-all"' in html
    assert 'id="access-password-modal"' in html
    assert 'id="access-action-new-password"' in html
    assert 'data-user-is-self="1"' in html
    assert 'data-delete-url=""' in html


def test_admin_list_pages_render_actions_menu_for_selection(client):
    _login_admin(client)

    expectations = [
        (
            "/admin/alertas",
            'id="btn-alertas-actions"',
            'id="alertas-actions-menu"',
            'id="alertas-action-select-all"',
            "toolbarSelector: '#alertas-toolbar'",
            "rowsRootSelector: '#alertas-list'",
        ),
        (
            "/admin/arquivos",
            'id="btn-arquivos-actions"',
            'id="arquivos-actions-menu"',
            'id="arquivos-action-select-all"',
            "toolbarSelector: '#admin-arquivos-toolbar'",
            "rowsRootSelector: '#arquivos-list'",
        ),
        (
            "/admin/matrizes",
            'id="btn-matrizes-actions"',
            'id="matrizes-actions-menu"',
            'id="matrizes-action-select-all"',
            None,
            None,
        ),
        (
            "/admin/atividades",
            'id="btn-atividades-actions"',
            'id="atividades-actions-menu"',
            'id="atividades-action-select-all"',
            "toolbarSelector: '#impressoes-toolbar'",
            "rowsRootSelector: '#atividades-list'",
        ),
        (
            "/admin/alunos",
            'id="btn-alunos-actions"',
            'id="alunos-actions-menu"',
            'id="alunos-action-select-all"',
            "toolbarSelector: '#impressoes-toolbar'",
            "rowsRootSelector: '#alunos-list'",
        ),
        (
            "/admin/turmas",
            'id="btn-turmas-actions"',
            'id="turmas-actions-menu"',
            'id="turmas-action-select-all"',
            "toolbarSelector: '#impressoes-toolbar'",
            "rowsRootSelector: '#turmas-list'",
        ),
        (
            "/admin/cursos",
            'id="btn-cursos-actions"',
            'id="cursos-actions-menu"',
            'id="cursos-action-select-all"',
            "toolbarSelector: '#impressoes-toolbar'",
            "rowsRootSelector: '#cursos-list'",
        ),
    ]

    for path, button_id, menu_id, select_all_id, toolbar_selector, rows_selector in expectations:
        response = client.get(path)
        assert response.status_code == 200
        html = response.get_data(as_text=True)

        assert button_id in html
        assert menu_id in html
        assert select_all_id in html
        assert 'class="btn toolbar-select-all"' not in html
        assert 'class="btn toolbar-bulk-delete"' not in html
        if path != "/admin/matrizes":
            assert "enableSelectAllButton: false" in html
            assert "enableBulkDelete: false" in html
        if toolbar_selector:
            assert toolbar_selector in html
        if rows_selector:
            assert rows_selector in html
        if path == "/admin/atividades":
            assert 'id="btn-grupos"' in html
            assert 'id="btn-importar-csv-atividades"' in html
        if path in {"/admin/atividades", "/admin/alunos", "/admin/turmas", "/admin/cursos"}:
            assert 'data-action="delete"' not in html


def test_admin_acesso_definir_senha_updates_selected_user_password(client):
    email = "senha.manual.automatizada@ej.edu.br"
    senha_inicial = "inicial123"
    nova_senha = "novaSenha987"

    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("DELETE FROM alunos WHERE email = ?", (email,))
        conn.execute("DELETE FROM usuarios WHERE email = ?", (email,))
        usuario_id = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?) RETURNING id",
            (
                "Senha Manual Automatizada",
                email,
                main.hash_password(senha_inicial),
                "admin",
                "consultivo",
            ),
        ).fetchone()["id"]
        conn.commit()

    _login_admin(client)

    try:
        response = client.post(
            "/admin/acesso/definir-senha",
            data={
                "usuario_ids": [str(usuario_id)],
                "nova_senha": nova_senha,
            },
            follow_redirects=False,
        )
        assert response.status_code in (302, 303)

        with main.app.app_context():
            conn = main.get_db_connection()
            user = conn.execute("SELECT senha FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
            assert user is not None
            assert main.check_password(user["senha"], nova_senha)
    finally:
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute("DELETE FROM usuarios WHERE id = ?", (usuario_id,))
            conn.commit()


def test_login_normalizes_contaminated_student_access_level(client):
    email = "aluno.contaminado.login@ej.edu.br"
    matricula = "CONT-LOGIN-001"

    with main.app.app_context():
        conn = main.get_db_connection()
        main.ensure_usuario_access_schema(conn)
        conn.execute("DELETE FROM alunos WHERE matricula = ? OR email = ?", (matricula, email))
        conn.execute("DELETE FROM usuarios WHERE email = ?", (email,))
        usuario_id = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?) RETURNING id",
            (
                "Aluno Contaminado Login",
                email,
                main.hash_password("aluno123"),
                "aluno",
                "administrativo",
            ),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, status) VALUES (?, ?, ?, ?, ?)",
            (usuario_id, "Aluno Contaminado Login", matricula, email, "Ativo"),
        )
        conn.commit()

    try:
        response = client.post(
            "/login",
            data={"email": email, "senha": "aluno123"},
            follow_redirects=False,
        )
        assert response.status_code in (302, 303)
        assert response.headers["Location"].endswith("/aluno/dashboard")

        with client.session_transaction() as sess:
            assert sess["user_type"] == "aluno"
            assert sess["access_level"] == "usuario"

        with main.app.app_context():
            conn = main.get_db_connection()
            usuario = conn.execute(
                "SELECT tipo, nivel_acesso FROM usuarios WHERE email = ?",
                (email,),
            ).fetchone()
            assert usuario is not None
            assert usuario["tipo"] == "aluno"
            assert usuario["nivel_acesso"] == "usuario"
    finally:
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute("DELETE FROM alunos WHERE matricula = ? OR email = ?", (matricula, email))
            conn.execute("DELETE FROM usuarios WHERE email = ?", (email,))
            conn.commit()


def test_admin_alertas_filter_schema_and_typed_filters(client):
    title_a = "Alerta Filtro Tipado A"
    title_b = "Alerta Filtro Tipado B"
    color_a = "#e3eefd"
    color_b = "#fef4c0"

    with main.app.app_context():
        conn = main.get_db_connection()
        main.ensure_admin_alertas_table(conn)
        conn.execute("DELETE FROM admin_alertas WHERE titulo IN (?, ?)", (title_a, title_b))
        conn.execute(
            "INSERT INTO admin_alertas (titulo, mensagem, bg_color, border_color, visivel) VALUES (?, ?, ?, ?, ?)",
            (title_a, "Mensagem A", color_a, main._alerta_border_for(color_a), 1),
        )
        conn.execute(
            "INSERT INTO admin_alertas (titulo, mensagem, bg_color, border_color, visivel) VALUES (?, ?, ?, ?, ?)",
            (title_b, "Mensagem B", color_b, main._alerta_border_for(color_b), 0),
        )
        conn.commit()

    _login_admin(client)

    try:
        response = client.get(
            "/admin/alertas",
            query_string={
                "titulo": "Tipado A",
                "bg_color": color_a,
                "status": "ativo",
            },
        )
        assert response.status_code == 200
        html = response.get_data(as_text=True)

        assert '"param": "titulo"' in html
        assert '"param": "bg_color"' in html
        assert '"param": "status"' in html
        assert '"type": "text_contains"' in html
        assert '"type": "multi_select"' in html

        assert title_a in html
        assert title_b not in html
    finally:
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute("DELETE FROM admin_alertas WHERE titulo IN (?, ?)", (title_a, title_b))
            conn.commit()


def test_admin_acesso_filter_schema_and_typed_filters(client):
    course_code = "ACC-FLT"
    turma_code = "ACC-FLT-T01"
    email_a = "acesso.filtro.aluno1@ej.edu.br"
    email_b = "acesso.filtro.aluno2@ej.edu.br"
    matricula_a = "ACC-FLT-001"
    matricula_b = "ACC-FLT-002"

    with main.app.app_context():
        conn = main.get_db_connection()
        main.ensure_turmas_matriz_schema(conn)
        main.ensure_usuario_access_schema(conn)

        conn.execute("DELETE FROM alunos WHERE matricula IN (?, ?)", (matricula_a, matricula_b))
        conn.execute("DELETE FROM usuarios WHERE email IN (?, ?)", (email_a, email_b))
        conn.execute("DELETE FROM turmas WHERE codigo = ?", (turma_code,))
        conn.execute("DELETE FROM cursos WHERE codigo = ?", (course_code,))

        conn.execute(
            "INSERT INTO cursos (nome, codigo, duracao_periodos, status) VALUES (?, ?, ?, ?)",
            ("Curso Acesso Filtro", course_code, 8, "ativo"),
        )
        curso_id = conn.execute("SELECT id FROM cursos WHERE codigo = ?", (course_code,)).fetchone()["id"]
        turma_id = conn.execute(
            """
            INSERT INTO turmas (nome, ano, semestre, turno, status, numero, curso_id, matriz_id, ano_inicio, semestre_inicio, ano_fim, semestre_fim, codigo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (turma_code, None, None, "Noite", "Ativa", 1, curso_id, None, 2027, 1, 2030, 2, turma_code),
        ).fetchone()["id"]

        user_a = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?)",
            ("Acesso Filtro Aluno 1", email_a, main.hash_password("aluno123"), "aluno", "usuario"),
        ).lastrowid
        user_b = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?)",
            ("Acesso Filtro Aluno 2", email_b, main.hash_password("aluno123"), "aluno", "usuario"),
        ).lastrowid

        conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, turma, turma_id, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_a, "Acesso Filtro Aluno 1", matricula_a, email_a, turma_code, turma_id, "Ativo"),
        )
        conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, turma, turma_id, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_b, "Acesso Filtro Aluno 2", matricula_b, email_b, None, None, "Ativo"),
        )
        conn.commit()

    _login_admin(client)

    try:
        response = client.get(
            "/admin/acesso",
            query_string={
                "nome": "Aluno 1",
                "email": "aluno1",
                "matricula": "ACC-FLT-001",
                "turma_id": str(turma_id),
                "tipo": "aluno",
                "nivel": "usuario",
            },
        )
        assert response.status_code == 200
        html = response.get_data(as_text=True)

        assert '"param": "nome"' in html
        assert '"param": "email"' in html
        assert '"param": "matricula"' in html
        assert '"param": "turma_id"' in html
        assert '"type": "text_contains"' in html
        assert '"type": "multi_select"' in html

        assert "Acesso Filtro Aluno 1" in html
        assert "Acesso Filtro Aluno 2" not in html
    finally:
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute("DELETE FROM alunos WHERE matricula IN (?, ?)", (matricula_a, matricula_b))
            conn.execute("DELETE FROM usuarios WHERE email IN (?, ?)", (email_a, email_b))
            conn.execute("DELETE FROM turmas WHERE codigo = ?", (turma_code,))
            conn.execute("DELETE FROM cursos WHERE codigo = ?", (course_code,))
            conn.commit()