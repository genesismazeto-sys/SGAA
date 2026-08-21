import os
import re
import sys
import uuid

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from app import db as app_db_module
import main


def _extract_form_block(html: str, action: str) -> str:
    marker = f'action="{action}"'
    start_idx = html.find(marker)
    assert start_idx != -1, f"Formulario com action={action} nao encontrado"
    form_start = html.rfind("<form", 0, start_idx)
    assert form_start != -1, "Tag <form nao encontrada antes do action esperado"
    form_end = html.find("</form>", start_idx)
    assert form_end != -1, "Fechamento </form> nao encontrado"
    return html[form_start:form_end]


def _extract_csrf_token(form_block: str) -> str:
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', form_block)
    assert match is not None, "Token CSRF nao encontrado no formulario"
    return str(match.group(1))


def _extract_first_post_form_block(html: str) -> str:
    match = re.search(r"(<form\b[^>]*\bmethod\s*=\s*[\"']?post[\"']?[^>]*>.*?</form>)", html, re.IGNORECASE | re.DOTALL)
    assert match is not None, "Formulario POST nao encontrado na pagina"
    return str(match.group(1))


def _extract_form_block_by_id(html: str, form_id: str) -> str:
    marker = f'id="{form_id}"'
    start_idx = html.find(marker)
    assert start_idx != -1, f"Formulario com id={form_id} nao encontrado"
    form_start = html.rfind("<form", 0, start_idx)
    assert form_start != -1, "Tag <form nao encontrada antes do id esperado"
    form_end = html.find("</form>", start_idx)
    assert form_end != -1, "Fechamento </form> nao encontrado"
    return html[form_start:form_end]


def _login_admin_user(client, user_id: int, user_name: str) -> None:
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["user_type"] = "admin"
        sess["user_name"] = user_name
        sess["access_level"] = "admin_total"
        sess["perfil"] = "Admin"


def _create_support_turma(conn, suffix: str) -> int:
    main.ensure_turmas_matriz_schema(conn)
    main.ensure_matrizes_atividades_table(conn)

    curso_codigo = f"CSRF-ALUNO-{suffix}"
    conn.execute(
        "INSERT INTO cursos (nome, codigo, duracao_periodos, status) VALUES (?, ?, ?, ?)",
        (f"Curso CSRF {suffix}", curso_codigo, 8, "ativo"),
    )
    curso_id = conn.execute(
        "SELECT id FROM cursos WHERE codigo = ?",
        (curso_codigo,),
    ).fetchone()["id"]

    matriz_id = conn.execute(
        """
        INSERT INTO matrizes_atividades (
            curso_id, nome, versao, status, data_inicio_vigencia,
            horas_aac_obrigatorias, horas_extensao_obrigatorias, descricao
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        (
            curso_id,
            f"Matriz CSRF {suffix}",
            "2026.2",
            "vigente",
            "2026-07-01",
            120,
            60,
            "Matriz para validar CSRF no cadastro de aluno",
        ),
    ).fetchone()["id"]

    turma_codigo = main.gerar_codigo_turma(curso_codigo, 1)
    turma_id = conn.execute(
        """
        INSERT INTO turmas (
            nome, turno, status, numero, curso_id, matriz_id,
            ano_inicio, semestre_inicio, ano_fim, semestre_fim, codigo
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        (
            turma_codigo,
            "Manha",
            "Ativa",
            1,
            curso_id,
            matriz_id,
            2026,
            1,
            2029,
            2,
            turma_codigo,
        ),
    ).fetchone()["id"]
    conn.commit()
    return int(turma_id)


def _seed_admin_and_support_turma(suffix: str) -> tuple[int, int]:
    with main.app.app_context():
        conn = main.get_db_connection()
        main.ensure_usuario_access_schema(conn)
        admin_id = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?)",
            (
                f"Admin CSRF {suffix}",
                f"admin.csrf.{suffix}@teste.local",
                main.hash_password("admin12345"),
                "admin",
                "admin_total",
            ),
        ).lastrowid
        turma_id = _create_support_turma(conn, suffix)
    return int(admin_id), int(turma_id)


def _seed_aluno_user(suffix: str, turma_id: int, senha: str, *, email_prefix: str = "aluno") -> tuple[int, str, str]:
    email = f"{email_prefix}.{suffix}@teste.local"
    matricula = f"AL-{suffix}".upper()
    with main.app.app_context():
        conn = main.get_db_connection()
        cursor = main.create_usuario_with_default_access(
            conn,
            f"Aluno CSRF {suffix}",
            email,
            main.hash_password(senha),
            "aluno",
        )
        usuario_id = int(cursor.lastrowid)
        conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status) VALUES (?, ?, ?, ?, ?, ?)",
            (usuario_id, f"Aluno CSRF {suffix}", matricula, email, turma_id, "Ativo"),
        )
        conn.commit()
    return usuario_id, email, matricula


@pytest.fixture()
def isolated_client_csrf(tmp_path):
    app = main.app
    temp_database = tmp_path / "admin_add_aluno_csrf.db"
    temp_uploads = tmp_path / "uploads"
    temp_uploads.mkdir(parents=True, exist_ok=True)

    original_database = main.DATABASE
    original_env_database = os.environ.get("APP_DATABASE")
    original_config_database_path = app.config.get("DATABASE_PATH")
    original_upload_folder = app.config.get("UPLOAD_FOLDER")
    original_documents_folder = app.config.get("DOCUMENTOS_ALUNOS_FOLDER")
    original_local_backup_dir = app.config.get("LOCAL_BACKUP_DIR")
    original_cloud_backup_dir = app.config.get("CLOUD_BACKUP_DIR")
    original_cloud_sync_interval = app.config.get("CLOUD_SYNC_INTERVAL_SECONDS")
    original_external_backup_enabled = app.config.get("EXTERNAL_BACKUP_ENABLED")
    original_testing = app.config.get("TESTING")
    original_wtf_csrf_enabled = app.config.get("WTF_CSRF_ENABLED")
    original_wtf_csrf_check_default = app.config.get("WTF_CSRF_CHECK_DEFAULT")

    os.environ["APP_DATABASE"] = str(temp_database)
    main.DATABASE = str(temp_database)
    app_db_module.DATABASE = str(temp_database)
    app.config["DATABASE_PATH"] = str(temp_database)
    app.config["TESTING"] = True
    app.config["UPLOAD_FOLDER"] = str(temp_uploads)
    app.config["DOCUMENTOS_ALUNOS_FOLDER"] = str(tmp_path / "documentos_alunos")
    app.config["LOCAL_BACKUP_DIR"] = str(tmp_path / "backups" / "local")
    app.config["CLOUD_BACKUP_DIR"] = ""
    app.config["CLOUD_SYNC_INTERVAL_SECONDS"] = 0
    app.config["EXTERNAL_BACKUP_ENABLED"] = False
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
        yield client
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

        app.config["UPLOAD_FOLDER"] = original_upload_folder
        app.config["DOCUMENTOS_ALUNOS_FOLDER"] = original_documents_folder
        app.config["LOCAL_BACKUP_DIR"] = original_local_backup_dir
        app.config["CLOUD_BACKUP_DIR"] = original_cloud_backup_dir
        app.config["CLOUD_SYNC_INTERVAL_SECONDS"] = original_cloud_sync_interval
        app.config["EXTERNAL_BACKUP_ENABLED"] = original_external_backup_enabled
        app.config["TESTING"] = original_testing
        app.config["WTF_CSRF_ENABLED"] = original_wtf_csrf_enabled
        app.config["WTF_CSRF_CHECK_DEFAULT"] = original_wtf_csrf_check_default

        if original_env_database is None:
            os.environ.pop("APP_DATABASE", None)
        else:
            os.environ["APP_DATABASE"] = original_env_database


def test_admin_add_aluno_requires_and_accepts_valid_csrf(
    isolated_client_csrf,
    monkeypatch,
):
    client = isolated_client_csrf
    suffix = uuid.uuid4().hex[:8]

    with main.app.app_context():
        conn = main.get_db_connection()
        main.ensure_usuario_access_schema(conn)
        admin_id = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?)",
            (
                f"Admin Add Aluno {suffix}",
                f"admin.add.aluno.{suffix}@teste.local",
                main.hash_password("admin12345"),
                "admin",
                "admin_total",
            ),
        ).lastrowid
        turma_id = _create_support_turma(conn, suffix)

    _login_admin_user(client, int(admin_id), f"Admin Add Aluno {suffix}")

    get_response = client.get("/admin/adicionar_aluno")
    assert get_response.status_code == 200

    html = get_response.get_data(as_text=True)
    form_block = _extract_form_block(html, "/admin/adicionar_aluno")
    token_count = len(re.findall(r'name="csrf_token"\s+value="[^"]+"', form_block))
    assert token_count == 1, "Formulario nao deve duplicar csrf_token"

    csrf_token = _extract_csrf_token(form_block)

    missing_response = client.post(
        "/admin/adicionar_aluno",
        data={
            "nome": "Aluno Sem Token",
            "email": f"sem.token.{suffix}@teste.local",
            "senha": "abc12345",
            "matricula": f"NO-CSRF-{suffix}",
            "turma_id": str(turma_id),
            "status": "Ativo",
        },
        follow_redirects=False,
    )
    assert missing_response.status_code == 400

    valid_email = f"com.token.{suffix}@teste.local"
    valid_response = client.post(
        "/admin/adicionar_aluno",
        data={
            "nome": "Aluno Com Token",
            "email": valid_email,
            "senha": "abc12345",
            "matricula": f"WITH-CSRF-{suffix}",
            "turma_id": str(turma_id),
            "status": "Ativo",
            "csrf_token": csrf_token,
        },
        follow_redirects=False,
    )
    assert valid_response.status_code in (302, 303)
    assert "/admin/alunos" in (valid_response.headers.get("Location") or "")

    with main.app.app_context():
        conn = main.get_db_connection()
        usuario = conn.execute(
            "SELECT id, tipo FROM usuarios WHERE email = ?",
            (valid_email,),
        ).fetchone()
        assert usuario is not None
        aluno = conn.execute(
            "SELECT usuario_id, email, turma_id, status FROM alunos WHERE usuario_id = ?",
            (usuario["id"],),
        ).fetchone()

    assert usuario["tipo"] == "aluno"
    assert aluno is not None
    assert aluno["email"] == valid_email
    assert aluno["turma_id"] == turma_id
    assert aluno["status"] == "Ativo"


def test_admin_add_aluno_blank_password_uses_default_and_allows_login(
    isolated_client_csrf,
    monkeypatch,
):
    client = isolated_client_csrf
    suffix = uuid.uuid4().hex[:8]

    admin_id, turma_id = _seed_admin_and_support_turma(suffix)
    _login_admin_user(client, admin_id, f"Admin CSRF {suffix}")

    get_response = client.get("/admin/adicionar_aluno")
    assert get_response.status_code == 200
    form_block = _extract_form_block(get_response.get_data(as_text=True), "/admin/adicionar_aluno")
    csrf_token = _extract_csrf_token(form_block)

    aluno_email = f"aluno.default.{suffix}@teste.local"
    create_response = client.post(
        "/admin/adicionar_aluno",
        data={
            "nome": f"Aluno Sem Senha {suffix}",
            "email": aluno_email,
            "senha": "",
            "matricula": f"DEF-{suffix}".upper(),
            "turma_id": str(turma_id),
            "status": "Ativo",
            "csrf_token": csrf_token,
        },
        follow_redirects=False,
    )
    assert create_response.status_code in (302, 303)
    assert "/admin/alunos" in (create_response.headers.get("Location") or "")

    with main.app.app_context():
        conn = main.get_db_connection()
        usuario = conn.execute(
            "SELECT id, senha FROM usuarios WHERE email = ?",
            (aluno_email,),
        ).fetchone()
        assert usuario is not None
        senha_padrao_aluno = main._default_password_for_user_type(conn, "aluno")
        assert main.check_password(usuario["senha"], senha_padrao_aluno)

    with client.session_transaction() as sess:
        sess.clear()

    login_response = client.post(
        "/login",
        data={"email": aluno_email, "senha": senha_padrao_aluno},
        follow_redirects=False,
    )
    assert login_response.status_code in (302, 303)
    assert "/aluno/dashboard" in (login_response.headers.get("Location") or "")


def test_admin_editar_aluno_password_requires_and_accepts_valid_csrf(
    isolated_client_csrf,
    monkeypatch,
):
    client = isolated_client_csrf
    suffix = uuid.uuid4().hex[:8]
    senha_inicial = "Inicial123!"
    senha_nova = "NovaSenha987!"

    admin_id, turma_id = _seed_admin_and_support_turma(suffix)
    usuario_id, aluno_email, matricula = _seed_aluno_user(suffix, turma_id, senha_inicial, email_prefix="aluno.edit")
    _login_admin_user(client, admin_id, f"Admin CSRF {suffix}")

    get_response = client.get(f"/admin/editar_aluno/{usuario_id}")
    assert get_response.status_code == 200

    html = get_response.get_data(as_text=True)
    form_block = _extract_first_post_form_block(html)
    token_count = len(re.findall(r'name="csrf_token"\s+value="[^"]+"', form_block))
    assert token_count == 1, "Formulario de edicao de aluno deve conter exatamente 1 token CSRF"
    csrf_token = _extract_csrf_token(form_block)

    post_payload = {
        "nome": f"Aluno Editado {suffix}",
        "email": aluno_email,
        "matricula": matricula,
        "turma_id": str(turma_id),
        "status": "Ativo",
        "senha": senha_nova,
    }

    missing_response = client.post(
        f"/admin/editar_aluno/{usuario_id}",
        data=post_payload,
        follow_redirects=False,
    )
    assert missing_response.status_code == 400

    valid_response = client.post(
        f"/admin/editar_aluno/{usuario_id}",
        data={**post_payload, "csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert valid_response.status_code in (302, 303)
    assert "/admin/alunos" in (valid_response.headers.get("Location") or "")

    with main.app.app_context():
        conn = main.get_db_connection()
        usuario = conn.execute(
            "SELECT senha FROM usuarios WHERE id = ?",
            (usuario_id,),
        ).fetchone()
        assert usuario is not None
        assert main.check_password(usuario["senha"], senha_nova)
        assert not main.check_password(usuario["senha"], senha_inicial)

    with client.session_transaction() as sess:
        sess.clear()

    login_response = client.post(
        "/login",
        data={"email": aluno_email, "senha": senha_nova},
        follow_redirects=False,
    )
    assert login_response.status_code in (302, 303)
    assert "/aluno/dashboard" in (login_response.headers.get("Location") or "")


def test_admin_acesso_definir_senha_requires_csrf_and_allows_student_login(
    isolated_client_csrf,
    monkeypatch,
):
    client = isolated_client_csrf
    suffix = uuid.uuid4().hex[:8]
    senha_inicial = "SenhaInicial456!"
    senha_nova = "SenhaNova654!"

    admin_id, turma_id = _seed_admin_and_support_turma(suffix)
    usuario_id, aluno_email, _ = _seed_aluno_user(suffix, turma_id, senha_inicial, email_prefix="aluno.acesso")
    _login_admin_user(client, admin_id, f"Admin CSRF {suffix}")

    acesso_response = client.get("/admin/acesso")
    assert acesso_response.status_code == 200

    acesso_html = acesso_response.get_data(as_text=True)
    password_form_block = _extract_form_block_by_id(acesso_html, "access-password-form")
    token_count = len(re.findall(r'name="csrf_token"\s+value="[^"]+"', password_form_block))
    assert token_count == 1, "Formulario de nova senha em admin/acesso deve conter exatamente 1 token CSRF"
    csrf_token = _extract_csrf_token(password_form_block)

    missing_response = client.post(
        "/admin/acesso/definir-senha",
        data={"usuario_ids": [str(usuario_id)], "nova_senha": senha_nova},
        headers={"X-Requested-With": "XMLHttpRequest"},
        follow_redirects=False,
    )
    assert missing_response.status_code == 400

    valid_response = client.post(
        "/admin/acesso/definir-senha",
        data={
            "usuario_ids": [str(usuario_id)],
            "nova_senha": senha_nova,
            "csrf_token": csrf_token,
        },
        headers={"X-Requested-With": "XMLHttpRequest"},
        follow_redirects=False,
    )
    assert valid_response.status_code == 200
    payload = valid_response.get_json() or {}
    assert payload.get("ok") is True

    with main.app.app_context():
        conn = main.get_db_connection()
        usuario = conn.execute(
            "SELECT senha FROM usuarios WHERE id = ?",
            (usuario_id,),
        ).fetchone()
        assert usuario is not None
        assert main.check_password(usuario["senha"], senha_nova)
        assert not main.check_password(usuario["senha"], senha_inicial)

    with client.session_transaction() as sess:
        sess.clear()

    login_response = client.post(
        "/login",
        data={"email": aluno_email, "senha": senha_nova},
        follow_redirects=False,
    )
    assert login_response.status_code in (302, 303)
    assert "/aluno/dashboard" in (login_response.headers.get("Location") or "")


def test_admin_acesso_resetar_senha_requires_csrf_and_sets_default_password(
    isolated_client_csrf,
    monkeypatch,
):
    client = isolated_client_csrf
    suffix = uuid.uuid4().hex[:8]
    senha_inicial = "SenhaInicial456!"

    admin_id, turma_id = _seed_admin_and_support_turma(suffix)
    usuario_id, aluno_email, _ = _seed_aluno_user(suffix, turma_id, senha_inicial, email_prefix="aluno.reset")
    _login_admin_user(client, admin_id, f"Admin CSRF {suffix}")

    acesso_response = client.get("/admin/acesso")
    assert acesso_response.status_code == 200
    password_form_block = _extract_form_block_by_id(acesso_response.get_data(as_text=True), "access-password-form")
    csrf_token = _extract_csrf_token(password_form_block)

    missing_response = client.post(
        f"/admin/acesso/{usuario_id}/resetar-senha",
        follow_redirects=False,
    )
    assert missing_response.status_code == 400

    valid_response = client.post(
        f"/admin/acesso/{usuario_id}/resetar-senha",
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert valid_response.status_code in (302, 303)
    assert "/admin/acesso" in (valid_response.headers.get("Location") or "")

    with main.app.app_context():
        conn = main.get_db_connection()
        senha_padrao_aluno = main._default_password_for_user_type(conn, "aluno")
        usuario = conn.execute(
            "SELECT senha FROM usuarios WHERE id = ?",
            (usuario_id,),
        ).fetchone()
        assert usuario is not None
        assert main.check_password(usuario["senha"], senha_padrao_aluno)
        assert not main.check_password(usuario["senha"], senha_inicial)

    with client.session_transaction() as sess:
        sess.clear()

    login_response = client.post(
        "/login",
        data={"email": aluno_email, "senha": senha_padrao_aluno},
        follow_redirects=False,
    )
    assert login_response.status_code in (302, 303)
    assert "/aluno/dashboard" in (login_response.headers.get("Location") or "")
