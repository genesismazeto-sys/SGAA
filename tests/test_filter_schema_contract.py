import json
import os
import re
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main


SCRIPT_PATTERN = re.compile(
    r'<script\s+id="filter-schema-data"\s+type="application/json">(.*?)</script>',
    re.DOTALL,
)


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


def _login_aluno(client, usuario_id: int, nome: str):
    with client.session_transaction() as sess:
        sess["user_id"] = usuario_id
        sess["user_type"] = "aluno"
        sess["user_name"] = nome


def _extract_filter_schema(html: str):
    match = SCRIPT_PATTERN.search(html)
    assert match is not None, "filter-schema-data script not found"
    payload = (match.group(1) or "[]").strip()
    schema = json.loads(payload)
    assert isinstance(schema, list)
    return schema


def _assert_entries_define_type(schema, endpoint: str):
    for entry in schema:
        if not isinstance(entry, dict):
            continue
        if "param" not in entry:
            continue
        assert "type" in entry, f"Missing type for param={entry.get('param')} on {endpoint}"
        assert str(entry.get("type") or "").strip(), f"Empty type for param={entry.get('param')} on {endpoint}"


def _ensure_turma_id() -> int:
    with main.app.app_context():
        conn = main.get_db_connection()
        main.ensure_turmas_matriz_schema(conn)

        turma = conn.execute("SELECT id FROM turmas ORDER BY id LIMIT 1").fetchone()
        if turma:
            return int(turma["id"])

        curso = conn.execute("SELECT id, codigo FROM cursos ORDER BY id LIMIT 1").fetchone()
        assert curso is not None
        turma_codigo = main.gerar_codigo_turma(curso["codigo"], 999)
        conn.execute("DELETE FROM turmas WHERE codigo = ?", (turma_codigo,))
        turma_id = conn.execute(
            """
            INSERT INTO turmas (
                nome, turno, status, numero, curso_id, matriz_id,
                ano_inicio, semestre_inicio, ano_fim, semestre_fim, codigo
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (turma_codigo, "Noite", "Ativa", 999, curso["id"], None, 2028, 1, 2031, 2, turma_codigo),
        ).fetchone()["id"]
        conn.commit()
        return int(turma_id)


def _ensure_aluno_usuario() -> int:
    email = "contract.filter.schema.aluno@teste.local"
    matricula = "FILTER-CONTRACT-ALUNO"

    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("DELETE FROM alunos WHERE matricula = ?", (matricula,))
        conn.execute("DELETE FROM usuarios WHERE email = ?", (email,))

        usuario_id = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo) VALUES (?, ?, ?, ?) RETURNING id",
            ("Aluno Contrato Filtro", email, main.hash_password("aluno123"), "aluno"),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, status) VALUES (?, ?, ?, ?, ?)",
            (usuario_id, "Aluno Contrato Filtro", matricula, email, "Ativo"),
        )
        conn.commit()
        return int(usuario_id)


def test_admin_filter_schema_entries_have_explicit_type(client):
    _login_admin(client)
    turma_id = _ensure_turma_id()

    endpoints = [
        "/admin/cursos",
        "/admin/arquivos",
        "/admin/atividades",
        "/admin/alunos",
        "/admin/turmas",
        f"/admin/turma/{turma_id}",
        "/admin/matrizes",
        "/admin/reportes",
        "/admin/alertas",
        "/admin/acesso",
    ]

    for endpoint in endpoints:
        response = client.get(endpoint)
        assert response.status_code == 200, f"Unexpected status for {endpoint}: {response.status_code}"
        schema = _extract_filter_schema(response.get_data(as_text=True))
        _assert_entries_define_type(schema, endpoint)


def test_aluno_filter_schema_entries_have_explicit_type(client):
    usuario_id = _ensure_aluno_usuario()
    _login_aluno(client, usuario_id, "Aluno Contrato Filtro")

    endpoints = [
        "/aluno/arquivos",
        "/aluno/requisicoes",
    ]

    for endpoint in endpoints:
        response = client.get(endpoint)
        assert response.status_code == 200, f"Unexpected status for {endpoint}: {response.status_code}"
        schema = _extract_filter_schema(response.get_data(as_text=True))
        _assert_entries_define_type(schema, endpoint)
