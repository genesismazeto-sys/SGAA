import io
import json
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


POST_FORM_RE = re.compile(
    r"(<form\b[^>]*\bmethod\s*=\s*[\"']?post[\"']?[^>]*>.*?</form>)",
    re.IGNORECASE | re.DOTALL,
)
CSRF_INPUT_RE = re.compile(r'name="csrf_token"\s+value="([^"]+)"')
META_CSRF_RE = re.compile(r'<meta\s+name="csrf-token"\s+content="([^"]+)"', re.IGNORECASE)


def _extract_post_forms(html: str) -> list[str]:
    return [str(block) for block in POST_FORM_RE.findall(html or "")]


def _extract_form_by_id(html: str, form_id: str) -> str:
    marker = f'id="{form_id}"'
    start_idx = html.find(marker)
    assert start_idx != -1, f"Formulario com id={form_id} nao encontrado"
    form_start = html.rfind("<form", 0, start_idx)
    assert form_start != -1, "Tag <form nao encontrada antes do id esperado"
    form_end = html.find("</form>", start_idx)
    assert form_end != -1, "Fechamento </form> nao encontrado"
    return html[form_start:form_end]


def _extract_form_by_action(html: str, action_fragment: str) -> str:
    action_idx = html.find(action_fragment)
    assert action_idx != -1, f"Formulario com action contendo {action_fragment} nao encontrado"
    form_start = html.rfind("<form", 0, action_idx)
    assert form_start != -1, "Tag <form nao encontrada antes do action esperado"
    form_end = html.find("</form>", action_idx)
    assert form_end != -1, "Fechamento </form> nao encontrado"
    return html[form_start:form_end]


def _extract_csrf_token(form_block: str) -> str:
    match = CSRF_INPUT_RE.search(form_block or "")
    assert match is not None, "Token CSRF nao encontrado no formulario"
    return str(match.group(1))


def _count_csrf_tokens(form_block: str) -> int:
    return len(re.findall(r'name="csrf_token"\s+value="[^"]+"', form_block or ""))


def _extract_meta_csrf_token(html: str) -> str:
    match = META_CSRF_RE.search(html or "")
    assert match is not None, "Meta csrf-token nao encontrada"
    return str(match.group(1))


def _login_admin_user(client, user_id: int, user_name: str) -> None:
    with client.session_transaction() as sess:
        sess["user_id"] = int(user_id)
        sess["user_type"] = "admin"
        sess["user_name"] = user_name
        sess["access_level"] = "admin_total"
        sess["perfil"] = "Admin"


def _create_support_turma(conn, suffix: str) -> int:
    main.ensure_turmas_matriz_schema(conn)
    main.ensure_matrizes_atividades_table(conn)

    curso_codigo = f"CSRF-P0-{suffix}"
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
            "Matriz para testes de CSRF",
        ),
    ).fetchone()["id"]

    turma_codigo = main.gerar_codigo_turma(curso_codigo, 1)
    turma_id = conn.execute(
        """
        INSERT INTO turmas (
            nome, ano, semestre, turno, status, numero, curso_id, matriz_id,
            ano_inicio, semestre_inicio, ano_fim, semestre_fim, codigo
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        (
            turma_codigo,
            None,
            None,
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
                f"Admin CSRF P0 {suffix}",
                f"admin.p0.csrf.{suffix}@teste.local",
                main.hash_password("admin12345"),
                "admin",
                "admin_total",
            ),
        ).lastrowid
        turma_id = _create_support_turma(conn, suffix)
    return int(admin_id), int(turma_id)


def _seed_aluno_user(suffix: str, turma_id: int, senha: str, *, email_prefix: str = "aluno") -> tuple[int, str]:
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
    return usuario_id, email


def _seed_requisicao_for_student(suffix: str, turma_id: int, aluno_usuario_id: int) -> tuple[int, int]:
    with main.app.app_context():
        conn = main.get_db_connection()
        atividade_id = conn.execute(
            """
            INSERT INTO atividades (
                grupo, nome, descricao, limite_horas, tipo_atividade, tem_limitacao
            ) VALUES (?, ?, ?, ?, ?, 0)
            """,
            (
                "1 - Grupo CSRF",
                f"Atividade Requisicao CSRF {suffix}",
                "Atividade para testes de requisicao admin",
                40,
                "Acadêmica Complementar",
            ),
        ).lastrowid
        aluno = conn.execute(
            "SELECT id FROM alunos WHERE usuario_id = ?",
            (aluno_usuario_id,),
        ).fetchone()
        assert aluno is not None
        req_id = conn.execute(
            """
            INSERT INTO requisicoes (
                aluno_id, atividade_id, data_solicitacao, data_evento,
                horas_solicitadas, nome_evento, status, observacao
            ) VALUES (?, ?, datetime('now'), ?, ?, ?, ?, ?)
            """,
            (
                int(aluno["id"]),
                int(atividade_id),
                "2028-09-12",
                6,
                f"Requisicao Admin CSRF {suffix}",
                "Pendente",
                "Criada para teste",
            ),
        ).lastrowid
        conn.commit()
    return int(atividade_id), int(req_id)


@pytest.fixture()
def isolated_client_csrf(tmp_path):
    app = main.app
    temp_database = tmp_path / "csrf_admin_flows.db"
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


@pytest.mark.parametrize("shadow_read_flag", [None, "1"])
def test_admin_pages_post_forms_have_single_csrf_token(
    isolated_client_csrf,
    monkeypatch,
    shadow_read_flag,
):
    client = isolated_client_csrf
    suffix = uuid.uuid4().hex[:8]

    if shadow_read_flag is None:
        monkeypatch.delenv("SGAA_VERSIONED_RESOLVER_SHADOW_READ", raising=False)
    else:
        monkeypatch.setenv("SGAA_VERSIONED_RESOLVER_SHADOW_READ", shadow_read_flag)

    admin_id, turma_id = _seed_admin_and_support_turma(suffix)
    _seed_aluno_user(suffix, turma_id, "alunoInicial!123", email_prefix="aluno.pages")
    _login_admin_user(client, admin_id, f"Admin CSRF P0 {suffix}")

    pages = [
        "/admin/meus_dados",
        "/admin/acesso",
        "/admin/adicionar_aluno",
        "/admin/alertas",
        "/admin/configuracoes",
        "/admin/mensagens",
        "/admin/banco-dados",
    ]

    for page in pages:
        response = client.get(page)
        assert response.status_code == 200, f"GET {page} deve retornar 200"
        html = response.get_data(as_text=True)
        forms = _extract_post_forms(html)
        assert forms, f"{page} deve conter ao menos um formulario POST"
        for form_block in forms:
            assert _count_csrf_tokens(form_block) == 1, f"{page} deve ter exatamente 1 csrf_token por formulario POST"


@pytest.mark.parametrize("shadow_read_flag", [None, "1"])
def test_admin_meus_dados_password_change_requires_and_accepts_csrf(
    isolated_client_csrf,
    monkeypatch,
    shadow_read_flag,
):
    client = isolated_client_csrf
    suffix = uuid.uuid4().hex[:8]
    admin_email = f"admin.p0.csrf.{suffix}@teste.local"
    old_password = "admin12345"
    new_password = "NovaSenha!123"

    if shadow_read_flag is None:
        monkeypatch.delenv("SGAA_VERSIONED_RESOLVER_SHADOW_READ", raising=False)
    else:
        monkeypatch.setenv("SGAA_VERSIONED_RESOLVER_SHADOW_READ", shadow_read_flag)

    admin_id, _ = _seed_admin_and_support_turma(suffix)
    _login_admin_user(client, admin_id, f"Admin CSRF P0 {suffix}")

    page = client.get("/admin/meus_dados")
    assert page.status_code == 200
    form_block = _extract_post_forms(page.get_data(as_text=True))[0]
    assert _count_csrf_tokens(form_block) == 1
    csrf_token = _extract_csrf_token(form_block)

    missing = client.post(
        "/admin/meus_dados",
        data={
            "nome": f"Admin CSRF P0 {suffix}",
            "email": admin_email,
            "senha": new_password,
            "remove_foto": "0",
        },
        follow_redirects=False,
    )
    assert missing.status_code == 400

    valid = client.post(
        "/admin/meus_dados",
        data={
            "nome": f"Admin CSRF P0 {suffix}",
            "email": admin_email,
            "senha": new_password,
            "remove_foto": "0",
            "csrf_token": csrf_token,
        },
        follow_redirects=False,
    )
    assert valid.status_code in (302, 303)
    assert "/admin/meus_dados" in (valid.headers.get("Location") or "")

    with main.app.app_context():
        conn = main.get_db_connection()
        usuario = conn.execute("SELECT senha FROM usuarios WHERE id = ?", (admin_id,)).fetchone()
        assert usuario is not None
        assert main.check_password(usuario["senha"], new_password)
        assert not main.check_password(usuario["senha"], old_password)
        assert not main.check_password(usuario["senha"], "")

    logout_response = client.get("/logout", follow_redirects=False)
    assert logout_response.status_code in (302, 303)
    assert "/login" in (logout_response.headers.get("Location") or "")

    old_login = client.post(
        "/login",
        data={"email": admin_email, "senha": old_password},
        follow_redirects=False,
    )
    assert old_login.status_code == 200
    with client.session_transaction() as sess:
        assert sess.get("user_id") is None

    new_login = client.post(
        "/login",
        data={"email": admin_email, "senha": new_password},
        follow_redirects=False,
    )
    assert new_login.status_code in (302, 303)
    assert "/admin/dashboard" in (new_login.headers.get("Location") or "")


@pytest.mark.parametrize("shadow_read_flag", [None, "1"])
def test_admin_fetch_mutation_requires_csrf_header(
    isolated_client_csrf,
    monkeypatch,
    shadow_read_flag,
):
    client = isolated_client_csrf
    suffix = uuid.uuid4().hex[:8]

    if shadow_read_flag is None:
        monkeypatch.delenv("SGAA_VERSIONED_RESOLVER_SHADOW_READ", raising=False)
    else:
        monkeypatch.setenv("SGAA_VERSIONED_RESOLVER_SHADOW_READ", shadow_read_flag)

    admin_id, _ = _seed_admin_and_support_turma(suffix)
    _login_admin_user(client, admin_id, f"Admin CSRF P0 {suffix}")

    alertas_page = client.get("/admin/alertas")
    assert alertas_page.status_code == 200
    html = alertas_page.get_data(as_text=True)
    form_block = _extract_form_by_id(html, "admin-alerta-form")
    form_token = _extract_csrf_token(form_block)
    meta_token = _extract_meta_csrf_token(html)

    create = client.post(
        "/admin/alertas/salvar",
        data={
            "titulo": f"Alerta CSRF {suffix}",
            "mensagem": "Mensagem CSRF para toggle",
            "bg_color": "#123abc",
            "border_color": "#0f4b8a",
            "visivel": "1",
            "csrf_token": form_token,
        },
        follow_redirects=False,
    )
    assert create.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        alerta = conn.execute(
            "SELECT id FROM admin_alertas WHERE titulo = ?",
            (f"Alerta CSRF {suffix}",),
        ).fetchone()
        assert alerta is not None
        alerta_id = int(alerta["id"])

    missing = client.post(f"/admin/alertas/{alerta_id}/alternar", follow_redirects=False)
    assert missing.status_code == 400

    valid = client.post(
        f"/admin/alertas/{alerta_id}/alternar",
        headers={"X-CSRFToken": meta_token, "X-Requested-With": "XMLHttpRequest"},
        follow_redirects=False,
    )
    assert valid.status_code in (302, 303)


@pytest.mark.parametrize("shadow_read_flag", [None, "1"])
def test_admin_redefine_student_password_and_student_login(
    isolated_client_csrf,
    monkeypatch,
    shadow_read_flag,
):
    client = isolated_client_csrf
    suffix = uuid.uuid4().hex[:8]
    senha_inicial = "SenhaInicial!123"
    senha_nova = "SenhaNova!321"

    if shadow_read_flag is None:
        monkeypatch.delenv("SGAA_VERSIONED_RESOLVER_SHADOW_READ", raising=False)
    else:
        monkeypatch.setenv("SGAA_VERSIONED_RESOLVER_SHADOW_READ", shadow_read_flag)

    admin_id, turma_id = _seed_admin_and_support_turma(suffix)
    aluno_id, aluno_email = _seed_aluno_user(suffix, turma_id, senha_inicial, email_prefix="aluno.redef")
    _login_admin_user(client, admin_id, f"Admin CSRF P0 {suffix}")

    acesso_page = client.get("/admin/acesso")
    assert acesso_page.status_code == 200
    password_form_block = _extract_form_by_id(acesso_page.get_data(as_text=True), "access-password-form")
    assert _count_csrf_tokens(password_form_block) == 1
    csrf_token = _extract_csrf_token(password_form_block)

    missing = client.post(
        "/admin/acesso/definir-senha",
        data={"usuario_ids": [str(aluno_id)], "nova_senha": senha_nova},
        headers={"X-Requested-With": "XMLHttpRequest"},
        follow_redirects=False,
    )
    assert missing.status_code == 400

    valid = client.post(
        "/admin/acesso/definir-senha",
        data={"usuario_ids": [str(aluno_id)], "nova_senha": senha_nova, "csrf_token": csrf_token},
        headers={"X-Requested-With": "XMLHttpRequest"},
        follow_redirects=False,
    )
    assert valid.status_code == 200
    payload = valid.get_json() or {}
    assert payload.get("ok") is True

    with main.app.app_context():
        conn = main.get_db_connection()
        usuario = conn.execute("SELECT senha FROM usuarios WHERE id = ?", (aluno_id,)).fetchone()
        assert usuario is not None
        assert main.check_password(usuario["senha"], senha_nova)
        assert not main.check_password(usuario["senha"], senha_inicial)
        assert not main.check_password(usuario["senha"], "")

    with client.session_transaction() as sess:
        sess.clear()

    login_response = client.post(
        "/login",
        data={"email": aluno_email, "senha": senha_nova},
        follow_redirects=False,
    )
    assert login_response.status_code in (302, 303)
    assert "/aluno/dashboard" in (login_response.headers.get("Location") or "")


@pytest.mark.parametrize("shadow_read_flag", [None, "1"])
def test_admin_add_aluno_blank_password_uses_default_and_not_empty_hash(
    isolated_client_csrf,
    monkeypatch,
    shadow_read_flag,
):
    client = isolated_client_csrf
    suffix = uuid.uuid4().hex[:8]
    email = f"aluno.sem.senha.{suffix}@teste.local"
    matricula = f"MATRIC-{suffix}".upper()

    if shadow_read_flag is None:
        monkeypatch.delenv("SGAA_VERSIONED_RESOLVER_SHADOW_READ", raising=False)
    else:
        monkeypatch.setenv("SGAA_VERSIONED_RESOLVER_SHADOW_READ", shadow_read_flag)

    admin_id, turma_id = _seed_admin_and_support_turma(suffix)
    _login_admin_user(client, admin_id, f"Admin CSRF P0 {suffix}")

    add_page = client.get("/admin/adicionar_aluno")
    assert add_page.status_code == 200
    form_block = _extract_post_forms(add_page.get_data(as_text=True))[0]
    assert _count_csrf_tokens(form_block) == 1
    csrf_token = _extract_csrf_token(form_block)

    missing = client.post(
        "/admin/adicionar_aluno",
        data={
            "nome": f"Aluno Sem Senha {suffix}",
            "email": email,
            "senha": "",
            "matricula": matricula,
            "turma_id": str(turma_id),
            "status": "Ativo",
        },
        follow_redirects=False,
    )
    assert missing.status_code == 400

    valid = client.post(
        "/admin/adicionar_aluno",
        data={
            "nome": f"Aluno Sem Senha {suffix}",
            "email": email,
            "senha": "",
            "matricula": matricula,
            "turma_id": str(turma_id),
            "status": "Ativo",
            "csrf_token": csrf_token,
        },
        follow_redirects=False,
    )
    assert valid.status_code in (302, 303)
    assert "/admin/alunos" in (valid.headers.get("Location") or "")

    with main.app.app_context():
        conn = main.get_db_connection()
        senha_padrao_aluno = main._default_password_for_user_type(conn, "aluno")
        usuario = conn.execute("SELECT id, senha FROM usuarios WHERE email = ?", (email,)).fetchone()
        assert usuario is not None
        assert main.check_password(usuario["senha"], senha_padrao_aluno)
        assert not main.check_password(usuario["senha"], "")
        usuario_id = int(usuario["id"])

    with client.session_transaction() as sess:
        sess.clear()

    login_response = client.post(
        "/login",
        data={"email": email, "senha": senha_padrao_aluno},
        follow_redirects=False,
    )
    assert login_response.status_code in (302, 303)
    assert "/aluno/dashboard" in (login_response.headers.get("Location") or "")

    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("DELETE FROM alunos WHERE usuario_id = ?", (usuario_id,))
        conn.execute("DELETE FROM usuarios WHERE id = ?", (usuario_id,))
        conn.commit()


@pytest.mark.parametrize("shadow_read_flag", [None, "1"])
def test_admin_api_presets_requires_and_accepts_csrf(
    isolated_client_csrf,
    monkeypatch,
    shadow_read_flag,
):
    client = isolated_client_csrf
    suffix = uuid.uuid4().hex[:8]

    if shadow_read_flag is None:
        monkeypatch.delenv("SGAA_VERSIONED_RESOLVER_SHADOW_READ", raising=False)
    else:
        monkeypatch.setenv("SGAA_VERSIONED_RESOLVER_SHADOW_READ", shadow_read_flag)

    admin_id, turma_id = _seed_admin_and_support_turma(suffix)
    aluno_id, _ = _seed_aluno_user(suffix, turma_id, "AlunoPreset!123", email_prefix="aluno.preset")
    _seed_requisicao_for_student(suffix, turma_id, aluno_id)
    _login_admin_user(client, admin_id, f"Admin CSRF P0 {suffix}")

    page = client.get("/admin/requisicoes")
    assert page.status_code == 200
    meta_token = _extract_meta_csrf_token(page.get_data(as_text=True))

    payload = {
        "respostas": [{"id": 1, "titulo": f"Resposta {suffix}", "texto": "Conteúdo teste"}],
        "emails": [{"id": 7, "titulo": f"Email {suffix}", "texto": "Corpo teste"}],
    }

    missing = client.post(
        "/admin/api/presets",
        data=json.dumps(payload),
        content_type="application/json",
        follow_redirects=False,
    )
    assert missing.status_code == 400

    valid = client.post(
        "/admin/api/presets",
        data=json.dumps(payload),
        content_type="application/json",
        headers={"X-CSRFToken": meta_token},
        follow_redirects=False,
    )
    assert valid.status_code == 200
    assert valid.get_json() == {"ok": True}


@pytest.mark.parametrize("shadow_read_flag", [None, "1"])
def test_admin_importar_requisicoes_page_and_post_require_csrf(
    isolated_client_csrf,
    monkeypatch,
    shadow_read_flag,
):
    client = isolated_client_csrf
    suffix = uuid.uuid4().hex[:8]

    if shadow_read_flag is None:
        monkeypatch.delenv("SGAA_VERSIONED_RESOLVER_SHADOW_READ", raising=False)
    else:
        monkeypatch.setenv("SGAA_VERSIONED_RESOLVER_SHADOW_READ", shadow_read_flag)

    admin_id, _ = _seed_admin_and_support_turma(suffix)
    _login_admin_user(client, admin_id, f"Admin CSRF P0 {suffix}")

    page = client.get("/admin/importar_requisicoes")
    assert page.status_code == 200
    form_block = _extract_post_forms(page.get_data(as_text=True))[0]
    assert _count_csrf_tokens(form_block) == 1
    csrf_token = _extract_csrf_token(form_block)

    missing = client.post(
        "/admin/importar_requisicoes",
        data={"usar_arquivo_padrao": "on"},
        follow_redirects=False,
    )
    assert missing.status_code == 400

    valid = client.post(
        "/admin/importar_requisicoes",
        data={"usar_arquivo_padrao": "on", "csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert valid.status_code == 200


@pytest.mark.parametrize("shadow_read_flag", [None, "1"])
def test_admin_requisicao_edit_requires_and_accepts_csrf(
    isolated_client_csrf,
    monkeypatch,
    shadow_read_flag,
):
    client = isolated_client_csrf
    suffix = uuid.uuid4().hex[:8]

    if shadow_read_flag is None:
        monkeypatch.delenv("SGAA_VERSIONED_RESOLVER_SHADOW_READ", raising=False)
    else:
        monkeypatch.setenv("SGAA_VERSIONED_RESOLVER_SHADOW_READ", shadow_read_flag)

    admin_id, turma_id = _seed_admin_and_support_turma(suffix)
    aluno_id, _ = _seed_aluno_user(suffix, turma_id, "AlunoReqEdit!123", email_prefix="aluno.reqedit")
    atividade_id, req_id = _seed_requisicao_for_student(suffix, turma_id, aluno_id)
    _login_admin_user(client, admin_id, f"Admin CSRF P0 {suffix}")

    page = client.get("/admin/requisicoes")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    form_block = _extract_form_by_id(html, "req-form")
    assert _count_csrf_tokens(form_block) == 1
    csrf_token = _extract_csrf_token(form_block)

    missing = client.post(
        f"/admin/requisicoes/{req_id}/editar",
        data={
            "atividade_id": str(atividade_id),
            "nome_evento": f"Evento sem CSRF {suffix}",
            "horas_solicitadas": "8",
            "data_evento": "2028-09-20",
            "observacao": "Tentativa sem token",
        },
        follow_redirects=False,
    )
    assert missing.status_code == 400

    valid = client.post(
        f"/admin/requisicoes/{req_id}/editar",
        data={
            "atividade_id": str(atividade_id),
            "nome_evento": f"Evento com CSRF {suffix}",
            "horas_solicitadas": "8",
            "data_evento": "2028-09-20",
            "observacao": "Atualizado com token",
            "csrf_token": csrf_token,
        },
        follow_redirects=False,
    )
    assert valid.status_code in (302, 303)
    assert "/admin/requisicoes" in (valid.headers.get("Location") or "")

    with main.app.app_context():
        conn = main.get_db_connection()
        updated = conn.execute(
            "SELECT nome_evento, observacao FROM requisicoes WHERE id = ?",
            (req_id,),
        ).fetchone()
        assert updated is not None
        assert updated["nome_evento"] == f"Evento com CSRF {suffix}"
        assert updated["observacao"] == "Atualizado com token"


@pytest.mark.parametrize("shadow_read_flag", [None, "1"])
def test_logout_get_is_safe_and_post_requires_csrf(
    isolated_client_csrf,
    monkeypatch,
    shadow_read_flag,
):
    client = isolated_client_csrf
    suffix = uuid.uuid4().hex[:8]

    if shadow_read_flag is None:
        monkeypatch.delenv("SGAA_VERSIONED_RESOLVER_SHADOW_READ", raising=False)
    else:
        monkeypatch.setenv("SGAA_VERSIONED_RESOLVER_SHADOW_READ", shadow_read_flag)

    admin_id, _ = _seed_admin_and_support_turma(suffix)
    _login_admin_user(client, admin_id, f"Admin CSRF P0 {suffix}")

    missing = client.post("/logout", follow_redirects=False)
    assert missing.status_code == 400

    page = client.get("/admin/meus_dados")
    assert page.status_code == 200
    form_block = _extract_post_forms(page.get_data(as_text=True))[0]
    csrf_token = _extract_csrf_token(form_block)

    valid = client.post(
        "/logout",
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert valid.status_code in (302, 303)
    assert "/login" in (valid.headers.get("Location") or "")

    _login_admin_user(client, admin_id, f"Admin CSRF P0 {suffix}")
    safe_get = client.get("/logout", follow_redirects=False)
    assert safe_get.status_code in (302, 303)
    assert "/login" in (safe_get.headers.get("Location") or "")
