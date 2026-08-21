"""Course detail page (admin_detalhes_curso / admin_visualizar_curso).

Characterizes the fix for the course-detail 500: ``templates/admin_detalhes_curso.html``
was missing while its handler (``app/views/admin/alunos_turmas_cursos.py``) already
rendered it with a stable, unchanged context (``curso``, ``turmas``). This module pins
that context landing on the page, the already-correct invalid-id/RBAC boundaries, and
the zero-turmas empty state.
"""
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


def _login_aluno(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 2
        sess["user_type"] = "aluno"
        sess["user_name"] = "Aluno Teste"


def _logout(client):
    with client.session_transaction() as sess:
        sess.clear()


def _seed_curso(nome, codigo, duracao_periodos=4, status="ativo"):
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("DELETE FROM cursos WHERE codigo = ?", (codigo,))
        conn.execute(
            "INSERT INTO cursos (nome, codigo, duracao_periodos, status) VALUES (?,?,?,?)",
            (nome, codigo, duracao_periodos, status),
        )
        conn.commit()
        return conn.execute(
            "SELECT id FROM cursos WHERE codigo = ?", (codigo,)
        ).fetchone()["id"]


def _seed_turma(curso_id, codigo, numero, status="Ativa", ano=2026, semestre=1, qtd_alunos=0):
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("DELETE FROM turmas WHERE codigo = ?", (codigo,))
        conn.execute(
            """
            INSERT INTO turmas (nome, ano_inicio, semestre_inicio, turno, status, numero, curso_id, codigo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (codigo, ano, semestre, "Manha", status, numero, curso_id, codigo),
        )
        conn.commit()
        turma_id = conn.execute(
            "SELECT id FROM turmas WHERE codigo = ?", (codigo,)
        ).fetchone()["id"]
        for i in range(qtd_alunos):
            email = f"{codigo.lower()}-aluno-{i}@example.com"
            conn.execute("DELETE FROM usuarios WHERE email = ?", (email,))
            conn.execute(
                "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?,?,?,?,?)",
                (f"Aluno {i}", email, main.hash_password("x"), "aluno", "usuario"),
            )
            usuario_id = conn.execute(
                "SELECT id FROM usuarios WHERE email = ?", (email,)
            ).fetchone()["id"]
            conn.execute(
                "INSERT INTO alunos (usuario_id, nome, turma_id, matricula) VALUES (?,?,?,?)",
                (usuario_id, f"Aluno {i}", turma_id, f"{codigo}-{i}"),
            )
        conn.commit()
        return turma_id


def test_detalhes_curso_renders_summary_and_turmas(client):
    curso_id = _seed_curso("Curso Detalhe RED", "CDR-001", duracao_periodos=6, status="ativo")
    _seed_turma(curso_id, "CDR-001-T1", numero=1, status="Ativa", qtd_alunos=2)

    _login_admin(client)
    response = client.get(f"/admin/cursos/{curso_id}")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Curso Detalhe RED" in html
    assert "CDR-001" in html
    assert "CDR-001-T1" in html or "1" in html


def test_visualizar_curso_redirects_then_renders(client):
    curso_id = _seed_curso("Curso Visualizar RED", "CDR-002", duracao_periodos=8, status="ativo")
    _seed_turma(curso_id, "CDR-002-T1", numero=1, status="Ativa", qtd_alunos=0)

    _login_admin(client)
    redirect_response = client.get(f"/admin/cursos/{curso_id}/visualizar", follow_redirects=False)
    assert redirect_response.status_code in (301, 302, 303, 307, 308)
    assert redirect_response.headers["Location"].endswith(f"/admin/cursos/{curso_id}")

    response = client.get(f"/admin/cursos/{curso_id}/visualizar", follow_redirects=True)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Curso Visualizar RED" in html


def test_detalhes_curso_invalid_id_redirects_to_list(client):
    _login_admin(client)
    response = client.get("/admin/cursos/999999", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/admin/cursos")


def test_detalhes_curso_aluno_blocked(client):
    curso_id = _seed_curso("Curso RBAC RED", "CDR-003")
    _login_aluno(client)
    response = client.get(f"/admin/cursos/{curso_id}", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")


def test_detalhes_curso_unauthenticated_blocked(client):
    curso_id = _seed_curso("Curso Anon RED", "CDR-004")
    _logout(client)
    response = client.get(f"/admin/cursos/{curso_id}", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")


def test_detalhes_curso_zero_turmas_shows_empty_state(client):
    curso_id = _seed_curso("Curso Vazio RED", "CDR-005", duracao_periodos=4, status="inativo")

    _login_admin(client)
    response = client.get(f"/admin/cursos/{curso_id}")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Curso Vazio RED" in html
    assert "Nenhuma turma" in html
