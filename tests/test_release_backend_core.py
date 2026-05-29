import os
import sys
import io
import re

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from app import db as app_db_module
import main


ADMIN_ROUTES = [
    "/admin/dashboard",
    "/admin/alunos",
    "/admin/cursos",
    "/admin/turmas",
    "/admin/requisicoes",
    "/admin/atividades",
    "/admin/arquivos",
    "/admin/reportes",
]

ALUNO_ROUTES = [
    "/aluno/dashboard",
    "/aluno/requisicoes",
    "/aluno/meus_dados",
    "/aluno/arquivos",
]


def _seed_aluno(conn):
    suffix = str(os.getpid())
    curso_codigo = f"REL{suffix}"
    turma_codigo = f"{curso_codigo}-1"
    email = f"release.aluno.{suffix}@teste.local"
    senha = "aluno123"

    conn.execute(
        "INSERT INTO cursos (nome, codigo, duracao_periodos, status) VALUES (?, ?, ?, ?)",
        ("Curso Release", curso_codigo, 8, "ativo"),
    )
    curso_id = conn.execute(
        "SELECT id FROM cursos WHERE codigo = ?",
        (curso_codigo,),
    ).fetchone()["id"]

    conn.execute(
        """
        INSERT INTO turmas (nome, ano, semestre, turno, status, numero, curso_id, codigo)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("Turma Release", 2026, 1, "Manha", "Ativa", 1, curso_id, turma_codigo),
    )
    turma_id = conn.execute(
        "SELECT id FROM turmas WHERE codigo = ?",
        (turma_codigo,),
    ).fetchone()["id"]

    conn.execute(
        "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?)",
        ("Aluno Release", email, main.hash_password(senha), "aluno", "usuario"),
    )
    usuario_id = conn.execute(
        "SELECT id FROM usuarios WHERE email = ?",
        (email,),
    ).fetchone()["id"]

    conn.execute(
        "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status) VALUES (?, ?, ?, ?, ?, ?)",
        (usuario_id, "Aluno Release", f"REL.{suffix}", email, turma_id, "Ativo"),
    )
    conn.commit()

    return email, senha


def _assert_ok(response, path):
    assert response.status_code == 200, (
        f"{path} retornou {response.status_code} em vez de 200"
    )


def _extract_csrf_token(html: str) -> str:
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    assert match is not None, "Token CSRF nao encontrado no HTML"
    return str(match.group(1))


def _seed_turma_import_data(conn):
    main.ensure_turmas_matriz_schema(conn)

    curso_codigo = "RELIMP"
    turma_codigo = main.gerar_codigo_turma(curso_codigo, 1)
    aluno_email = "release.import.aluno@teste.local"
    aluno_matricula = "REL-IMPORT-001"

    conn.execute(
        "INSERT INTO cursos (nome, codigo, duracao_periodos, status) VALUES (?, ?, ?, ?)",
        ("Curso Importacao Release", curso_codigo, 8, "ativo"),
    )
    curso_id = conn.execute(
        "SELECT id FROM cursos WHERE codigo = ?",
        (curso_codigo,),
    ).fetchone()["id"]

    conn.execute(
        """
        INSERT INTO turmas (nome, ano, semestre, turno, status, numero, curso_id, codigo)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("Turma Importacao Release", 2026, 1, "Manha", "Ativa", 1, curso_id, turma_codigo),
    )
    turma_id = conn.execute(
        "SELECT id FROM turmas WHERE codigo = ?",
        (turma_codigo,),
    ).fetchone()["id"]

    conn.execute(
        "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?)",
        (
            "Aluno Importacao Release",
            aluno_email,
            main.hash_password("aluno123"),
            "aluno",
            "usuario",
        ),
    )
    usuario_id = conn.execute(
        "SELECT id FROM usuarios WHERE email = ?",
        (aluno_email,),
    ).fetchone()["id"]

    conn.execute(
        "INSERT INTO alunos (usuario_id, nome, matricula, email, status) VALUES (?, ?, ?, ?, ?)",
        (usuario_id, "Aluno Importacao Release", aluno_matricula, aluno_email, "Ativo"),
    )
    conn.commit()

    return turma_id, aluno_matricula, aluno_email


@pytest.fixture()
def isolated_client(tmp_path):
    app = main.app
    temp_database = tmp_path / "release_backend_core.db"

    original_database = main.DATABASE
    original_env_database = os.environ.get("APP_DATABASE")
    original_config_database_path = app.config.get("DATABASE_PATH")

    os.environ["APP_DATABASE"] = str(temp_database)
    main.DATABASE = str(temp_database)
    app_db_module.DATABASE = str(temp_database)
    app.config["DATABASE_PATH"] = str(temp_database)
    app.config["TESTING"] = True

    with app.app_context():
        try:
            main.close_db_connection(None)
        except Exception:
            pass
        main.init_db()

    client = app.test_client()

    try:
        yield client, str(temp_database)
    finally:
        with app.app_context():
            try:
                main.close_db_connection(None)
            except Exception:
                pass

        main.DATABASE = original_database
        app_db_module.DATABASE = original_database
        if original_config_database_path is None:
            app.config.pop("DATABASE_PATH", None)
        else:
            app.config["DATABASE_PATH"] = original_config_database_path

        if original_env_database is None:
            os.environ.pop("APP_DATABASE", None)
        else:
            os.environ["APP_DATABASE"] = original_env_database


@pytest.fixture()
def isolated_client_csrf(tmp_path):
    app = main.app
    temp_database = tmp_path / "release_backend_core_csrf.db"

    original_database = main.DATABASE
    original_env_database = os.environ.get("APP_DATABASE")
    original_config_database_path = app.config.get("DATABASE_PATH")
    original_testing = app.config.get("TESTING")
    original_wtf_csrf_enabled = app.config.get("WTF_CSRF_ENABLED")
    original_wtf_csrf_check_default = app.config.get("WTF_CSRF_CHECK_DEFAULT")

    os.environ["APP_DATABASE"] = str(temp_database)
    main.DATABASE = str(temp_database)
    app_db_module.DATABASE = str(temp_database)
    app.config["DATABASE_PATH"] = str(temp_database)
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = True
    app.config["WTF_CSRF_CHECK_DEFAULT"] = True

    with app.app_context():
        try:
            main.close_db_connection(None)
        except Exception:
            pass
        main.init_db()

    client = app.test_client()

    try:
        yield client, str(temp_database)
    finally:
        with app.app_context():
            try:
                main.close_db_connection(None)
            except Exception:
                pass

        main.DATABASE = original_database
        app_db_module.DATABASE = original_database
        if original_config_database_path is None:
            app.config.pop("DATABASE_PATH", None)
        else:
            app.config["DATABASE_PATH"] = original_config_database_path

        app.config["TESTING"] = original_testing
        app.config["WTF_CSRF_ENABLED"] = original_wtf_csrf_enabled
        app.config["WTF_CSRF_CHECK_DEFAULT"] = original_wtf_csrf_check_default

        if original_env_database is None:
            os.environ.pop("APP_DATABASE", None)
        else:
            os.environ["APP_DATABASE"] = original_env_database


def test_release_backend_core_database_starts_clean(isolated_client):
    _, temp_database = isolated_client

    assert os.path.exists(temp_database)
    assert os.path.basename(temp_database) == "release_backend_core.db"

    with main.app.app_context():
        conn = main.get_db_connection()
        usuarios_count = conn.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]
        alunos_count = conn.execute("SELECT COUNT(*) FROM alunos").fetchone()[0]

    # Banco inicial deve ter somente seed mínimo (admin) e nenhum aluno criado.
    assert usuarios_count >= 1
    assert alunos_count == 0


def test_release_backend_core_admin_login_and_pages(isolated_client):
    client, _ = isolated_client

    login_get = client.get("/login")
    _assert_ok(login_get, "/login")

    admin_login = client.post(
        "/login",
        data={"email": "admin@ej.edu.br", "senha": "admin123"},
        follow_redirects=False,
    )
    assert admin_login.status_code in (302, 303)

    for path in ADMIN_ROUTES:
        response = client.get(path, follow_redirects=False)
        _assert_ok(response, path)


def test_release_backend_core_aluno_login_and_pages(isolated_client):
    client, _ = isolated_client

    with main.app.app_context():
        conn = main.get_db_connection()
        aluno_email, aluno_password = _seed_aluno(conn)

    aluno_login = client.post(
        "/login",
        data={"email": aluno_email, "senha": aluno_password},
        follow_redirects=False,
    )
    assert aluno_login.status_code in (302, 303)

    for path in ALUNO_ROUTES:
        response = client.get(path, follow_redirects=False)
        _assert_ok(response, path)


def test_release_backend_core_turmas_import_get_redirect_and_post_csrf(isolated_client_csrf):
    client, _ = isolated_client_csrf

    with main.app.app_context():
        conn = main.get_db_connection()
        turma_id, aluno_matricula, aluno_email = _seed_turma_import_data(conn)

    admin_login = client.post(
        "/login",
        data={"email": "admin@ej.edu.br", "senha": "admin123"},
        follow_redirects=False,
    )
    assert admin_login.status_code in (302, 303)

    get_import_page = client.get("/admin/turmas/importar", follow_redirects=False)
    assert get_import_page.status_code in (302, 303)
    assert "/admin/turmas" in (get_import_page.headers.get("Location") or "")

    csv_content = f"matricula;email\n{aluno_matricula};\n"
    post_without_csrf = client.post(
        "/admin/turmas/importar",
        data={
            "turma_id": str(turma_id),
            "csv_arquivo": (io.BytesIO(csv_content.encode("utf-8")), "alunos.csv"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert post_without_csrf.status_code == 400

    turmas_page = client.get("/admin/turmas", follow_redirects=False)
    assert turmas_page.status_code == 200
    csrf_token = _extract_csrf_token(turmas_page.get_data(as_text=True))

    post_with_csrf = client.post(
        "/admin/turmas/importar",
        data={
            "turma_id": str(turma_id),
            "csrf_token": csrf_token,
            "csv_arquivo": (io.BytesIO(csv_content.encode("utf-8")), "alunos.csv"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert post_with_csrf.status_code in (302, 303)
    assert "/admin/turmas" in (post_with_csrf.headers.get("Location") or "")

    with main.app.app_context():
        conn = main.get_db_connection()
        aluno = conn.execute(
            "SELECT turma_id FROM alunos WHERE email = ?",
            (aluno_email,),
        ).fetchone()
    assert aluno is not None
    assert aluno["turma_id"] == turma_id


def test_release_backend_core_turmas_import_rbac_requires_admin(isolated_client_csrf):
    client, _ = isolated_client_csrf

    sem_login = client.get("/admin/turmas/importar", follow_redirects=False)
    assert sem_login.status_code in (302, 303)
    assert "/login" in (sem_login.headers.get("Location") or "")

    with main.app.app_context():
        conn = main.get_db_connection()
        aluno_email, aluno_password = _seed_aluno(conn)

    aluno_login = client.post(
        "/login",
        data={"email": aluno_email, "senha": aluno_password},
        follow_redirects=False,
    )
    assert aluno_login.status_code in (302, 303)

    aluno_get_import = client.get("/admin/turmas/importar", follow_redirects=False)
    assert aluno_get_import.status_code in (302, 303)
    assert "/login" in (aluno_get_import.headers.get("Location") or "")
