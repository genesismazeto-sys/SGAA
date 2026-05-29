import os
import sqlite3
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


def test_admin_cursos_filter_button_has_schema_and_filters_status(client):
    course_codes = ["FLT-ATIVO", "FLT-INATIVO"]

    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("DELETE FROM cursos WHERE codigo IN (?, ?)", course_codes)
        conn.execute(
            "INSERT INTO cursos (nome, codigo, duracao_periodos, status) VALUES (?, ?, ?, ?)",
            ("Curso Filtro Ativo", course_codes[0], 8, "ativo"),
        )
        conn.execute(
            "INSERT INTO cursos (nome, codigo, duracao_periodos, status) VALUES (?, ?, ?, ?)",
            ("Curso Filtro Inativo", course_codes[1], 12, "inativo"),
        )
        conn.commit()

    _login_admin(client)

    try:
        response = client.get("/admin/cursos?status=ativo")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert '"param": "status"' in html
        assert '"param": "codigo"' in html
        assert '"param": "nome"' in html
        assert '"param": "duracao_periodos"' in html
        assert '"param": "qtd_turmas"' in html
        assert '"param": "qtd_alunos"' in html
        assert '"type": "text_contains"' in html
        assert '"type": "number_range"' in html
        assert "Curso Filtro Ativo" in html
        assert "Curso Filtro Inativo" not in html

        range_response = client.get("/admin/cursos?duracao_periodos_max=8")
        assert range_response.status_code == 200
        range_html = range_response.get_data(as_text=True)
        assert "Curso Filtro Ativo" in range_html
        assert "Curso Filtro Inativo" not in range_html

        text_response = client.get("/admin/cursos?nome=Inativo")
        assert text_response.status_code == 200
        text_html = text_response.get_data(as_text=True)
        assert "Curso Filtro Inativo" in text_html
        assert "Curso Filtro Ativo" not in text_html
    finally:
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute("DELETE FROM cursos WHERE codigo IN (?, ?)", course_codes)
            conn.commit()


def test_admin_alunos_filter_button_has_schema_and_filters_status_course_turma_and_pendencias(client):
    course_codes = ["ALF-A", "ALF-B"]
    turma_codes = ["ALF-A-T01", "ALF-B-T01"]
    emails = ["toolbar.aluno.ativo@example.com", "toolbar.aluno.inativo@example.com"]
    matriculas = ["ALF-A-001", "ALF-B-001"]

    with main.app.app_context():
        conn = main.get_db_connection()
        main.ensure_turmas_matriz_schema(conn)
        conn.execute("DELETE FROM alunos WHERE matricula IN (?, ?)", matriculas)
        conn.execute("DELETE FROM usuarios WHERE email IN (?, ?)", emails)
        conn.execute("DELETE FROM turmas WHERE codigo IN (?, ?)", turma_codes)
        conn.execute("DELETE FROM cursos WHERE codigo IN (?, ?)", course_codes)

        conn.execute(
            "INSERT INTO cursos (nome, codigo, duracao_periodos, status) VALUES (?, ?, ?, ?)",
            ("Curso Toolbar A", course_codes[0], 8, "ativo"),
        )
        conn.execute(
            "INSERT INTO cursos (nome, codigo, duracao_periodos, status) VALUES (?, ?, ?, ?)",
            ("Curso Toolbar B", course_codes[1], 8, "ativo"),
        )
        curso_a = conn.execute("SELECT id FROM cursos WHERE codigo = ?", (course_codes[0],)).fetchone()["id"]
        curso_b = conn.execute("SELECT id FROM cursos WHERE codigo = ?", (course_codes[1],)).fetchone()["id"]

        conn.execute(
            """
            INSERT INTO turmas (nome, ano, semestre, turno, status, numero, curso_id, matriz_id, ano_inicio, semestre_inicio, ano_fim, semestre_fim, codigo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (turma_codes[0], None, None, "Noite", "Ativa", 1, curso_a, None, 2027, 1, 2030, 2, turma_codes[0]),
        )
        conn.execute(
            """
            INSERT INTO turmas (nome, ano, semestre, turno, status, numero, curso_id, matriz_id, ano_inicio, semestre_inicio, ano_fim, semestre_fim, codigo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (turma_codes[1], None, None, "Noite", "Ativa", 1, curso_b, None, 2027, 1, 2030, 2, turma_codes[1]),
        )
        turma_a = conn.execute("SELECT id FROM turmas WHERE codigo = ?", (turma_codes[0],)).fetchone()["id"]
        turma_b = conn.execute("SELECT id FROM turmas WHERE codigo = ?", (turma_codes[1],)).fetchone()["id"]

        user_a = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo) VALUES (?, ?, ?, ?)",
            ("Aluno Toolbar Ativo", emails[0], main.hash_password("teste123"), "aluno"),
        ).lastrowid
        user_b = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo) VALUES (?, ?, ?, ?)",
            ("Aluno Toolbar Inativo", emails[1], main.hash_password("teste123"), "aluno"),
        ).lastrowid

        conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status) VALUES (?, ?, ?, ?, ?, ?)",
            (user_a, "Aluno Toolbar Ativo", matriculas[0], emails[0], turma_a, "Ativo"),
        )
        conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status) VALUES (?, ?, ?, ?, ?, ?)",
            (user_b, "Aluno Toolbar Inativo", matriculas[1], emails[1], turma_b, "Inativo"),
        )
        conn.commit()

    _login_admin(client)

    try:
        with main.app.app_context():
            conn = main.get_db_connection()
            atividade_id = conn.execute(
                """
                INSERT INTO atividades (grupo, nome, limite_horas, tipo_atividade, tem_limitacao, tipo_limitacao, limite_horas_total, limite_horas_semestral, documentos_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                RETURNING id
                """,
                ("99 - Toolbar", "Atividade Toolbar Pendencia", None, "Acadêmica Complementar", 0, None, None, None, None),
            ).fetchone()["id"]
            aluno_id = conn.execute("SELECT id FROM alunos WHERE matricula = ?", (matriculas[0],)).fetchone()["id"]
            conn.execute(
                """
                INSERT INTO requisicoes (aluno_id, atividade_id, data_solicitacao, data_evento, horas_solicitadas, nome_evento, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (aluno_id, atividade_id, "2026-01-10", "2026-01-09", 4, "Evento Toolbar", "Pendente"),
            )
            conn.commit()

        response = client.get(
            f"/admin/alunos?status=Ativo&curso_id={curso_a}&turma_id={turma_a}&pendencias=com_pendencias&nome=Toolbar+Ativo&pendentes_min=1"
        )
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert '"param": "nome"' in html
        assert '"param": "email"' in html
        assert '"param": "status"' in html
        assert '"param": "curso_id"' in html
        assert '"param": "turma_id"' in html
        assert '"param": "pendentes"' in html
        assert '"param": "pendencias"' in html
        assert '"type": "text_contains"' in html
        assert '"type": "number_range"' in html
        assert "Aluno Toolbar Ativo" in html
        assert "Aluno Toolbar Inativo" not in html

        email_response = client.get("/admin/alunos?email=inativo@example.com")
        assert email_response.status_code == 200
        email_html = email_response.get_data(as_text=True)
        assert "Aluno Toolbar Inativo" in email_html
        assert "Aluno Toolbar Ativo" not in email_html
    finally:
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute("DELETE FROM requisicoes WHERE nome_evento = ?", ("Evento Toolbar",))
            conn.execute("DELETE FROM atividades WHERE nome = ?", ("Atividade Toolbar Pendencia",))
            conn.execute("DELETE FROM alunos WHERE matricula IN (?, ?)", matriculas)
            conn.execute("DELETE FROM usuarios WHERE email IN (?, ?)", emails)
            conn.execute("DELETE FROM turmas WHERE codigo IN (?, ?)", turma_codes)
            conn.execute("DELETE FROM cursos WHERE codigo IN (?, ?)", course_codes)
            conn.commit()


def test_admin_turmas_filter_button_has_schema_and_filters_status_and_course(client):
    course_codes = ["TRM-A", "TRM-B"]
    turma_codes = ["TRM-A-T01", "TRM-B-T01"]

    with main.app.app_context():
        conn = main.get_db_connection()
        main.ensure_turmas_matriz_schema(conn)
        conn.execute("DELETE FROM turmas WHERE codigo IN (?, ?)", turma_codes)
        conn.execute("DELETE FROM cursos WHERE codigo IN (?, ?)", course_codes)

        conn.execute(
            "INSERT INTO cursos (nome, codigo, duracao_periodos, status) VALUES (?, ?, ?, ?)",
            ("Curso Turma A", course_codes[0], 8, "ativo"),
        )
        conn.execute(
            "INSERT INTO cursos (nome, codigo, duracao_periodos, status) VALUES (?, ?, ?, ?)",
            ("Curso Turma B", course_codes[1], 8, "ativo"),
        )
        curso_a = conn.execute("SELECT id FROM cursos WHERE codigo = ?", (course_codes[0],)).fetchone()["id"]
        curso_b = conn.execute("SELECT id FROM cursos WHERE codigo = ?", (course_codes[1],)).fetchone()["id"]

        conn.execute(
            """
            INSERT INTO turmas (nome, ano, semestre, turno, status, numero, curso_id, matriz_id, ano_inicio, semestre_inicio, ano_fim, semestre_fim, codigo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (turma_codes[0], None, None, "Manhã", "Ativa", 1, curso_a, None, 2027, 1, 2030, 2, turma_codes[0]),
        )
        conn.execute(
            """
            INSERT INTO turmas (nome, ano, semestre, turno, status, numero, curso_id, matriz_id, ano_inicio, semestre_inicio, ano_fim, semestre_fim, codigo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (turma_codes[1], None, None, "Noite", "Inativa", 2, curso_b, None, 2027, 1, 2030, 2, turma_codes[1]),
        )
        conn.commit()

    _login_admin(client)

    try:
        response = client.get(f"/admin/turmas?status=Ativa&curso_id={curso_a}")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert '"param": "codigo"' in html
        assert '"param": "status"' in html
        assert '"param": "curso_id"' in html
        assert '"param": "matriz"' in html
        assert '"param": "numero"' in html
        assert '"param": "qtd_alunos"' in html
        assert '"type": "text_contains"' in html
        assert '"type": "number_range"' in html
        assert turma_codes[0] in html
        assert turma_codes[1] not in html

        numero_response = client.get("/admin/turmas?codigo=TRM-B&numero_min=2&numero_max=2")
        assert numero_response.status_code == 200
        numero_html = numero_response.get_data(as_text=True)
        assert turma_codes[1] in numero_html
        assert turma_codes[0] not in numero_html
    finally:
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute("DELETE FROM turmas WHERE codigo IN (?, ?)", turma_codes)
            conn.execute("DELETE FROM cursos WHERE codigo IN (?, ?)", course_codes)
            conn.commit()


def test_admin_alunos_delete_preserves_filtered_turma_view(client):
    course_code = "DEL-TURMA"
    turma_code = "DEL-TURMA-T11"
    emails = ["delete.t11.1@example.com", "delete.t11.2@example.com"]
    matriculas = ["DEL-T11-001", "DEL-T11-002"]

    with main.app.app_context():
        conn = main.get_db_connection()
        main.ensure_turmas_matriz_schema(conn)
        conn.execute("DELETE FROM alunos WHERE matricula IN (?, ?)", matriculas)
        conn.execute("DELETE FROM usuarios WHERE email IN (?, ?)", emails)
        conn.execute("DELETE FROM turmas WHERE codigo = ?", (turma_code,))
        conn.execute("DELETE FROM cursos WHERE codigo = ?", (course_code,))

        conn.execute(
            "INSERT INTO cursos (nome, codigo, duracao_periodos, status) VALUES (?, ?, ?, ?)",
            ("Curso Delete Turma", course_code, 8, "ativo"),
        )
        curso_id = conn.execute("SELECT id FROM cursos WHERE codigo = ?", (course_code,)).fetchone()["id"]
        turma_id = conn.execute(
            """
            INSERT INTO turmas (nome, ano, semestre, turno, status, numero, curso_id, matriz_id, ano_inicio, semestre_inicio, ano_fim, semestre_fim, codigo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (turma_code, None, None, "Noite", "Ativa", 11, curso_id, None, 2027, 1, 2030, 2, turma_code),
        ).fetchone()["id"]

        usuario_ids = []
        for idx, email in enumerate(emails, start=1):
            usuario_id = conn.execute(
                "INSERT INTO usuarios (nome, email, senha, tipo) VALUES (?, ?, ?, ?)",
                (f"Aluno Delete {idx}", email, main.hash_password("teste123"), "aluno"),
            ).lastrowid
            usuario_ids.append(usuario_id)
            conn.execute(
                "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status) VALUES (?, ?, ?, ?, ?, ?)",
                (usuario_id, f"Aluno Delete {idx}", matriculas[idx - 1], email, turma_id, "Ativo"),
            )
        conn.commit()

    _login_admin(client)

    try:
        filtered_path = f"/admin/alunos?turma_id={turma_id}"
        filtered_page = client.get(filtered_path)
        assert filtered_page.status_code == 200
        html = filtered_page.get_data(as_text=True)
        assert "Aluno Delete 1" in html
        assert "Aluno Delete 2" in html

        for usuario_id in usuario_ids:
            delete_response = client.post(
                f"/admin/deletar_aluno/{usuario_id}",
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
            assert delete_response.status_code == 200
            assert delete_response.is_json
            assert delete_response.get_json()["ok"] is True

        after_delete = client.get(filtered_path)
        assert after_delete.status_code == 200
        after_html = after_delete.get_data(as_text=True)
        assert "Aluno Delete 1" not in after_html
        assert "Aluno Delete 2" not in after_html
        assert "Nenhum aluno encontrado." in after_html
    finally:
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute("DELETE FROM alunos WHERE matricula IN (?, ?)", matriculas)
            conn.execute("DELETE FROM usuarios WHERE email IN (?, ?)", emails)
            conn.execute("DELETE FROM turmas WHERE codigo = ?", (turma_code,))
            conn.execute("DELETE FROM cursos WHERE codigo = ?", (course_code,))
            conn.commit()
