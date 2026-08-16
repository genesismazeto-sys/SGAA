"""End-to-end CSRF coverage for critical user-facing flows.

A R1 do P0-CSRF validou apenas presenca de token no HTML final renderizado.
O middleware `_inject_csrf_into_html` em app/__init__.py injeta o token em forms
POST sem token, entao a R1 considerou OK rotas cujo template nao tinha token
explicito. Esta suite eleva a barra: extrai o token do HTML final, submete o
POST real (multipart quando o form usa) e exige resposta funcional (302 e
registro criado no banco temporario), nao apenas ausencia de 400.

Cobre:
- /aluno/nova-requisicao e /aluno/nova_requisicao (mesma view, dois paths)
- POST sem csrf_token deve retornar 400
- POST com csrf_token extraido do HTML deve criar a requisicao
- Variante com upload de comprovante (multipart real)
- Variante de admin criando requisicao para aluno
- Cada teste roda com SGAA_VERSIONED_RESOLVER_SHADOW_READ desligado e =1
"""

from __future__ import annotations

import io
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
from tests.fc10_test_helpers import add_exact_snapshot_authority


POST_FORM_RE = re.compile(
    r"(<form\b[^>]*\bmethod\s*=\s*[\"']?post[\"']?[^>]*>.*?</form>)",
    re.IGNORECASE | re.DOTALL,
)
CSRF_INPUT_RE = re.compile(r'name="csrf_token"\s+value="([^"]+)"')
FORM_ACTION_RE = re.compile(r'\baction\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
FORM_ENCTYPE_RE = re.compile(r'\benctype\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)


def _extract_first_post_form(html: str) -> str:
    match = POST_FORM_RE.search(html or "")
    assert match is not None, "Nenhum <form method=post> encontrado no HTML renderizado"
    return str(match.group(0))


def _extract_csrf_token(form_block: str) -> str:
    match = CSRF_INPUT_RE.search(form_block or "")
    assert match is not None, (
        "Token CSRF nao encontrado dentro do <form method=post> renderizado"
    )
    return str(match.group(1))


def _extract_form_action(form_block: str, fallback: str) -> str:
    match = FORM_ACTION_RE.search(form_block.split(">", 1)[0])
    if match:
        return str(match.group(1))
    return fallback


def _extract_form_enctype(form_block: str) -> str:
    match = FORM_ENCTYPE_RE.search(form_block.split(">", 1)[0])
    return (match.group(1) if match else "application/x-www-form-urlencoded").lower()


def _login_admin(client, user_id: int, user_name: str) -> None:
    with client.session_transaction() as sess:
        sess["user_id"] = int(user_id)
        sess["user_type"] = "admin"
        sess["user_name"] = user_name
        sess["access_level"] = "admin_total"
        sess["perfil"] = "Admin"


def _login_aluno(client, user_id: int, user_name: str) -> None:
    with client.session_transaction() as sess:
        sess["user_id"] = int(user_id)
        sess["user_type"] = "aluno"
        sess["user_name"] = user_name


def _seed_curso_matriz_turma(conn, suffix: str) -> tuple[int, int, int]:
    main.ensure_turmas_matriz_schema(conn)
    main.ensure_matrizes_atividades_table(conn)
    main.ensure_matriz_atividade_links_table(conn)

    curso_codigo = f"E2E-CSRF-{suffix}"
    conn.execute(
        "INSERT INTO cursos (nome, codigo, duracao_periodos, status) VALUES (?, ?, ?, ?)",
        (f"Curso E2E {suffix}", curso_codigo, 8, "ativo"),
    )
    curso_id = int(
        conn.execute(
            "SELECT id FROM cursos WHERE codigo = ?",
            (curso_codigo,),
        ).fetchone()["id"]
    )
    matriz_id = int(
        conn.execute(
            """
            INSERT INTO matrizes_atividades (
                curso_id, nome, versao, status, data_inicio_vigencia,
                horas_aac_obrigatorias, horas_extensao_obrigatorias, descricao
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (
                curso_id,
                f"Matriz E2E {suffix}",
                "2026.2",
                "vigente",
                "2026-07-01",
                120,
                60,
                "Matriz E2E para testes de CSRF",
            ),
        ).fetchone()["id"]
    )
    turma_codigo = main.gerar_codigo_turma(curso_codigo, 1)
    turma_id = int(
        conn.execute(
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
    )
    conn.commit()
    return curso_id, matriz_id, turma_id


def _seed_atividade_linked_to_matriz(
    conn,
    suffix: str,
    matriz_id: int,
    *,
    tipo: str = "Acadêmica Complementar",
) -> int:
    atividade_id = int(
        conn.execute(
            """
            INSERT INTO atividades (
                grupo, nome, descricao, limite_horas, tipo_atividade, tem_limitacao
            ) VALUES (?, ?, ?, ?, ?, 0)
            """,
            (
                "1 - Grupo E2E",
                f"Atividade E2E {suffix}",
                "Atividade E2E para CSRF",
                40,
                tipo,
            ),
        ).lastrowid
    )
    conn.execute(
        "INSERT INTO matrizes_atividades_itens (matriz_id, atividade_id) VALUES (?, ?)",
        (matriz_id, atividade_id),
    )
    add_exact_snapshot_authority(
        conn,
        matriz_id=matriz_id,
        atividade_id=atividade_id,
        prefix=f"csrf-e2e-{suffix}",
    )
    conn.commit()
    return atividade_id


def _seed_aluno(conn, suffix: str, turma_id: int, senha: str) -> tuple[int, int, str]:
    email = f"aluno.e2e.{suffix}@teste.local"
    cursor = main.create_usuario_with_default_access(
        conn,
        f"Aluno E2E {suffix}",
        email,
        main.hash_password(senha),
        "aluno",
    )
    usuario_id = int(cursor.lastrowid)
    conn.execute(
        """
        INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            usuario_id,
            f"Aluno E2E {suffix}",
            f"E2E-{suffix}".upper(),
            email,
            turma_id,
            "Ativo",
        ),
    )
    aluno_id = int(
        conn.execute(
            "SELECT id FROM alunos WHERE usuario_id = ?",
            (usuario_id,),
        ).fetchone()["id"]
    )
    conn.commit()
    return usuario_id, aluno_id, email


def _seed_admin(conn, suffix: str) -> int:
    main.ensure_usuario_access_schema(conn)
    admin_id = int(
        conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?)",
            (
                f"Admin E2E {suffix}",
                f"admin.e2e.{suffix}@teste.local",
                main.hash_password("admin12345"),
                "admin",
                "admin_total",
            ),
        ).lastrowid
    )
    conn.commit()
    return admin_id


@pytest.fixture()
def isolated_client_e2e(tmp_path):
    app = main.app
    temp_database = tmp_path / "csrf_e2e.db"
    temp_uploads = tmp_path / "uploads"
    temp_documentos = tmp_path / "documentos_alunos"
    temp_uploads.mkdir(parents=True, exist_ok=True)
    temp_documentos.mkdir(parents=True, exist_ok=True)

    saved = {
        "DATABASE": main.DATABASE,
        "ENV_DATABASE": os.environ.get("APP_DATABASE"),
        "DATABASE_PATH": app.config.get("DATABASE_PATH"),
        "UPLOAD_FOLDER": app.config.get("UPLOAD_FOLDER"),
        "DOCUMENTOS_ALUNOS_FOLDER": app.config.get("DOCUMENTOS_ALUNOS_FOLDER"),
        "LOCAL_BACKUP_DIR": app.config.get("LOCAL_BACKUP_DIR"),
        "CLOUD_BACKUP_DIR": app.config.get("CLOUD_BACKUP_DIR"),
        "CLOUD_SYNC_INTERVAL_SECONDS": app.config.get("CLOUD_SYNC_INTERVAL_SECONDS"),
        "EXTERNAL_BACKUP_ENABLED": app.config.get("EXTERNAL_BACKUP_ENABLED"),
        "TESTING": app.config.get("TESTING"),
        "WTF_CSRF_ENABLED": app.config.get("WTF_CSRF_ENABLED"),
        "WTF_CSRF_CHECK_DEFAULT": app.config.get("WTF_CSRF_CHECK_DEFAULT"),
    }

    os.environ["APP_DATABASE"] = str(temp_database)
    main.DATABASE = str(temp_database)
    app_db_module.DATABASE = str(temp_database)
    app.config["DATABASE_PATH"] = str(temp_database)
    app.config["TESTING"] = True
    app.config["UPLOAD_FOLDER"] = str(temp_uploads)
    app.config["DOCUMENTOS_ALUNOS_FOLDER"] = str(temp_documentos)
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

        main.DATABASE = saved["DATABASE"]
        app_db_module.DATABASE = saved["DATABASE"]
        if saved["DATABASE_PATH"] is None:
            app.config.pop("DATABASE_PATH", None)
        else:
            app.config["DATABASE_PATH"] = saved["DATABASE_PATH"]
        app.config["UPLOAD_FOLDER"] = saved["UPLOAD_FOLDER"]
        app.config["DOCUMENTOS_ALUNOS_FOLDER"] = saved["DOCUMENTOS_ALUNOS_FOLDER"]
        app.config["LOCAL_BACKUP_DIR"] = saved["LOCAL_BACKUP_DIR"]
        app.config["CLOUD_BACKUP_DIR"] = saved["CLOUD_BACKUP_DIR"]
        app.config["CLOUD_SYNC_INTERVAL_SECONDS"] = saved["CLOUD_SYNC_INTERVAL_SECONDS"]
        app.config["EXTERNAL_BACKUP_ENABLED"] = saved["EXTERNAL_BACKUP_ENABLED"]
        app.config["TESTING"] = saved["TESTING"]
        app.config["WTF_CSRF_ENABLED"] = saved["WTF_CSRF_ENABLED"]
        app.config["WTF_CSRF_CHECK_DEFAULT"] = saved["WTF_CSRF_CHECK_DEFAULT"]

        if saved["ENV_DATABASE"] is None:
            os.environ.pop("APP_DATABASE", None)
        else:
            os.environ["APP_DATABASE"] = saved["ENV_DATABASE"]


def _set_shadow_read(monkeypatch, flag: str | None) -> None:
    if flag is None:
        monkeypatch.delenv("SGAA_VERSIONED_RESOLVER_SHADOW_READ", raising=False)
    else:
        monkeypatch.setenv("SGAA_VERSIONED_RESOLVER_SHADOW_READ", flag)


def _setup_aluno_with_aac(suffix: str):
    with main.app.app_context():
        conn = main.get_db_connection()
        _curso_id, matriz_id, turma_id = _seed_curso_matriz_turma(conn, suffix)
        atividade_id = _seed_atividade_linked_to_matriz(
            conn, suffix, matriz_id, tipo="Acadêmica Complementar"
        )
        usuario_id, aluno_id, _email = _seed_aluno(
            conn, suffix, turma_id, "AlunoE2E!123"
        )
    return usuario_id, aluno_id, atividade_id


@pytest.mark.parametrize("path", ["/aluno/nova-requisicao", "/aluno/nova_requisicao"])
@pytest.mark.parametrize("shadow_read_flag", [None, "1"])
def test_aluno_can_create_aac_request_without_csrf_400(
    isolated_client_e2e, monkeypatch, shadow_read_flag, path
):
    """Fluxo real: aluno abre tela, extrai token do HTML final, submete POST.

    Garantias:
    - POST sem csrf_token -> 400 (protecao CSRF nao foi afrouxada).
    - POST com csrf_token extraido do HTML final -> redirect 302 (sem 400).
    - Requisicao realmente criada no banco temporario para o aluno seedado.
    - Funciona para ambas as variantes do path (com hifen e com underscore).
    - Funciona com SGAA_VERSIONED_RESOLVER_SHADOW_READ desligado e =1.
    """
    _set_shadow_read(monkeypatch, shadow_read_flag)
    client = isolated_client_e2e
    suffix = uuid.uuid4().hex[:8]
    usuario_id, aluno_id, atividade_id = _setup_aluno_with_aac(suffix)
    _login_aluno(client, usuario_id, f"Aluno E2E {suffix}")

    page = client.get(path, follow_redirects=False)
    assert page.status_code == 200, (
        f"GET {path} deve devolver 200 (recebeu {page.status_code})"
    )
    html = page.get_data(as_text=True)
    form_block = _extract_first_post_form(html)
    enctype = _extract_form_enctype(form_block)
    assert "multipart/form-data" in enctype, (
        f"O form de nova requisicao deve ser multipart/form-data, recebeu {enctype}"
    )
    csrf_token = _extract_csrf_token(form_block)
    action = _extract_form_action(form_block, fallback=path)

    base_payload = {
        "tipo_atividade": "Acadêmica Complementar",
        "grupo": "1 - Grupo E2E",
        "atividade_id": str(atividade_id),
        "nome_evento": f"Evento E2E {suffix}",
        "horas_solicitadas": "8",
        "data_evento": "2028-09-12",
        "observacao": f"Submissao E2E {suffix}",
    }

    missing = client.post(
        action,
        data=base_payload,
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert missing.status_code == 400, (
        f"POST sem csrf_token em {action} deve retornar 400 (recebeu {missing.status_code})"
    )

    valid_payload = dict(base_payload)
    valid_payload["csrf_token"] = csrf_token
    valid = client.post(
        action,
        data=valid_payload,
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert valid.status_code in (302, 303), (
        f"POST com csrf_token em {action} deve redirecionar 302/303 "
        f"(recebeu {valid.status_code}, body={valid.get_data(as_text=True)[:400]!r})"
    )
    assert "/aluno/" in (valid.headers.get("Location") or ""), (
        f"Redirect esperado para area do aluno, recebeu {valid.headers.get('Location')!r}"
    )

    with main.app.app_context():
        conn = main.get_db_connection()
        rows = conn.execute(
            "SELECT id, aluno_id, nome_evento, horas_solicitadas, status FROM requisicoes "
            "WHERE aluno_id = ? AND nome_evento = ?",
            (aluno_id, base_payload["nome_evento"]),
        ).fetchall()
        assert len(rows) == 1, (
            f"Esperava 1 requisicao criada para aluno {aluno_id} com nome "
            f"{base_payload['nome_evento']}, encontrou {len(rows)}"
        )
        created = rows[0]
        assert int(created["aluno_id"]) == aluno_id
        assert float(created["horas_solicitadas"]) == 8.0
        assert created["status"] == "Pendente"


@pytest.mark.parametrize("shadow_read_flag", [None, "1"])
def test_aluno_can_create_aac_request_with_attachment_without_csrf_400(
    isolated_client_e2e, monkeypatch, shadow_read_flag
):
    """Mesmo fluxo, agora exercitando o upload real de comprovante multipart."""
    _set_shadow_read(monkeypatch, shadow_read_flag)
    client = isolated_client_e2e
    suffix = uuid.uuid4().hex[:8]
    usuario_id, aluno_id, atividade_id = _setup_aluno_with_aac(suffix)
    _login_aluno(client, usuario_id, f"Aluno E2E {suffix}")

    page = client.get("/aluno/nova-requisicao", follow_redirects=False)
    assert page.status_code == 200
    form_block = _extract_first_post_form(page.get_data(as_text=True))
    csrf_token = _extract_csrf_token(form_block)
    action = _extract_form_action(form_block, fallback="/aluno/nova-requisicao")

    pdf_bytes = b"%PDF-1.4\n%fake pdf for csrf e2e\n%%EOF"

    missing = client.post(
        action,
        data={
            "tipo_atividade": "Acadêmica Complementar",
            "grupo": "1 - Grupo E2E",
            "atividade_id": str(atividade_id),
            "nome_evento": f"Evento Anexo E2E {suffix}",
            "horas_solicitadas": "5",
            "data_evento": "2028-10-04",
            "observacao": "Submissao com anexo sem token",
            "comprovantes_files": (io.BytesIO(pdf_bytes), f"comprovante-{suffix}.pdf"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert missing.status_code == 400, (
        f"POST multipart sem csrf_token deve retornar 400 (recebeu {missing.status_code})"
    )

    valid = client.post(
        action,
        data={
            "csrf_token": csrf_token,
            "tipo_atividade": "Acadêmica Complementar",
            "grupo": "1 - Grupo E2E",
            "atividade_id": str(atividade_id),
            "nome_evento": f"Evento Anexo E2E {suffix}",
            "horas_solicitadas": "5",
            "data_evento": "2028-10-04",
            "observacao": "Submissao com anexo com token",
            "comprovantes_files": (io.BytesIO(pdf_bytes), f"comprovante-{suffix}.pdf"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert valid.status_code in (302, 303), (
        f"POST multipart com csrf_token deve redirecionar 302/303 "
        f"(recebeu {valid.status_code}, body={valid.get_data(as_text=True)[:400]!r})"
    )

    with main.app.app_context():
        conn = main.get_db_connection()
        row = conn.execute(
            "SELECT id, arquivo_comprovante FROM requisicoes "
            "WHERE aluno_id = ? AND nome_evento = ?",
            (aluno_id, f"Evento Anexo E2E {suffix}"),
        ).fetchone()
        assert row is not None, "Requisicao com anexo nao foi criada"
        req_id = int(row["id"])
        anexos = conn.execute(
            "SELECT filename FROM requisicao_arquivos WHERE requisicao_id = ?",
            (req_id,),
        ).fetchall()
        assert len(anexos) >= 1, "Anexo nao foi registrado em requisicao_arquivos"
        assert row["arquivo_comprovante"], (
            "Coluna arquivo_comprovante deveria refletir o primeiro anexo salvo"
        )


@pytest.mark.parametrize("shadow_read_flag", [None, "1"])
def test_admin_can_create_request_for_student_without_csrf_400(
    isolated_client_e2e, monkeypatch, shadow_read_flag
):
    """Admin abre /admin/requisicoes/nova, extrai token, POST cria requisicao."""
    _set_shadow_read(monkeypatch, shadow_read_flag)
    client = isolated_client_e2e
    suffix = uuid.uuid4().hex[:8]

    with main.app.app_context():
        conn = main.get_db_connection()
        _curso_id, matriz_id, turma_id = _seed_curso_matriz_turma(conn, suffix)
        atividade_id = _seed_atividade_linked_to_matriz(
            conn, suffix, matriz_id, tipo="Acadêmica Complementar"
        )
        usuario_id, aluno_id, _email = _seed_aluno(
            conn, suffix, turma_id, "AlunoE2E!123"
        )
        admin_id = _seed_admin(conn, suffix)

    _login_admin(client, admin_id, f"Admin E2E {suffix}")

    page = client.get(
        f"/admin/requisicoes?open_new=1&aluno_id={aluno_id}", follow_redirects=False
    )
    assert page.status_code == 200, (
        f"GET /admin/requisicoes?open_new=1&aluno_id={aluno_id} esperava 200, "
        f"recebeu {page.status_code}"
    )
    html = page.get_data(as_text=True)
    # Achar o form cujo action aponta para /admin/requisicoes/nova
    nova_action_re = re.compile(
        r'<form\b[^>]*\baction\s*=\s*["\']([^"\']*?/admin/requisicoes/nova[^"\']*)["\'][^>]*>.*?</form>',
        re.IGNORECASE | re.DOTALL,
    )
    nova_match = nova_action_re.search(html)
    assert nova_match is not None, (
        "Nao foi possivel localizar <form action=.../admin/requisicoes/nova...> "
        "na pagina /admin/requisicoes"
    )
    form_block = nova_match.group(0)
    action = nova_match.group(1)
    csrf_token = _extract_csrf_token(form_block)

    base = {
        "aluno_id": str(aluno_id),
        "atividade_id": str(atividade_id),
        "nome_evento": f"Req Admin E2E {suffix}",
        "horas_solicitadas": "10",
        "data_evento": "2028-11-01",
        "observacao": "Criada por admin no E2E",
    }

    missing = client.post(
        action,
        data=base,
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert missing.status_code == 400, (
        f"POST sem csrf_token em {action} deve retornar 400 (recebeu {missing.status_code})"
    )

    payload_ok = dict(base)
    payload_ok["csrf_token"] = csrf_token
    valid = client.post(
        action,
        data=payload_ok,
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert valid.status_code in (200, 302, 303), (
        f"POST com csrf_token em {action} esperava 200/302/303 "
        f"(recebeu {valid.status_code}, body={valid.get_data(as_text=True)[:400]!r})"
    )

    with main.app.app_context():
        conn = main.get_db_connection()
        row = conn.execute(
            "SELECT id FROM requisicoes WHERE aluno_id = ? AND nome_evento = ?",
            (aluno_id, base["nome_evento"]),
        ).fetchone()
        assert row is not None, (
            f"Esperava requisicao criada por admin para aluno {aluno_id}, "
            "mas nada foi inserido"
        )


def test_aluno_aac_post_returns_400_when_session_cleared_between_get_and_post(
    isolated_client_e2e, monkeypatch
):
    """Documenta a hipotese provavel do 400 visto em producao.

    O middleware injeta csrf_token no HTML final. POST com token valido
    funciona (provado em outros testes). Mas se a sessao for invalidada
    entre o GET e o POST (logout em outra aba, expiracao de session
    cookie, reinicializacao do servidor, etc.), o token capturado fica
    stale e Flask-WTF rejeita com 400.

    Esse teste reproduz o cenario chamando sess.clear() entre o GET e o
    POST, e exige 400 com a mesma mensagem do handler global. Serve como
    regressao caso futuras refatoracoes alterem esse comportamento.
    """
    monkeypatch.delenv("SGAA_VERSIONED_RESOLVER_SHADOW_READ", raising=False)
    client = isolated_client_e2e
    suffix = uuid.uuid4().hex[:8]
    usuario_id, _aluno_id, atividade_id = _setup_aluno_with_aac(suffix)
    _login_aluno(client, usuario_id, f"Aluno E2E {suffix}")

    page = client.get("/aluno/nova-requisicao", follow_redirects=False)
    assert page.status_code == 200
    form_block = _extract_first_post_form(page.get_data(as_text=True))
    csrf_token = _extract_csrf_token(form_block)
    action = _extract_form_action(form_block, fallback="/aluno/nova-requisicao")

    # Simula invalidacao de sessao entre GET (token gerado) e POST (token velho).
    with client.session_transaction() as sess:
        sess.clear()
    _login_aluno(client, usuario_id, f"Aluno E2E {suffix}")

    stale_post = client.post(
        action,
        data={
            "csrf_token": csrf_token,
            "tipo_atividade": "Acadêmica Complementar",
            "grupo": "1 - Grupo E2E",
            "atividade_id": str(atividade_id),
            "nome_evento": f"Evento Stale {suffix}",
            "horas_solicitadas": "8",
            "data_evento": "2028-09-12",
            "observacao": "Submissao com token stale",
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert stale_post.status_code == 400, (
        "POST com token capturado em sessao invalidada deve retornar 400 "
        f"(recebeu {stale_post.status_code})"
    )
    body = stale_post.get_data(as_text=True)
    assert (
        "desatualizada" in body
        or "sess" in body.lower()
        or "CSRF" in body
    ), (
        "A resposta 400 deveria carregar a mensagem do handler de CSRFError, "
        f"recebeu: {body[:300]!r}"
    )


def test_csrf_token_endpoint_returns_401_for_anonymous(isolated_client_e2e):
    """O endpoint de refresh nao deve expor token sem sessao autenticada."""
    client = isolated_client_e2e
    resp = client.get("/csrf-token", follow_redirects=False)
    assert resp.status_code == 401, (
        f"Esperava 401 para anonimo, recebeu {resp.status_code}"
    )
    payload = resp.get_json() or {}
    assert payload.get("error") == "unauthorized"


def test_csrf_token_endpoint_returns_fresh_token_for_authenticated_aluno(
    isolated_client_e2e,
):
    """Aluno logado consegue refrescar o token e usa-lo no proximo POST."""
    client = isolated_client_e2e
    suffix = uuid.uuid4().hex[:8]
    usuario_id, aluno_id, atividade_id = _setup_aluno_with_aac(suffix)
    _login_aluno(client, usuario_id, f"Aluno E2E {suffix}")

    # GET inicial estabelece sessao e token; o endpoint depende dela.
    page = client.get("/aluno/nova-requisicao")
    assert page.status_code == 200

    resp = client.get(
        "/csrf-token",
        headers={"X-Requested-With": "XMLHttpRequest"},
        follow_redirects=False,
    )
    assert resp.status_code == 200, (
        f"Esperava 200 para aluno logado, recebeu {resp.status_code}"
    )
    payload = resp.get_json() or {}
    fresh_token = payload.get("csrf_token")
    assert isinstance(fresh_token, str) and len(fresh_token) >= 16, (
        f"Token devolvido invalido: {fresh_token!r}"
    )
    # Cache nao deve guardar o token
    cache_control = (resp.headers.get("Cache-Control") or "").lower()
    assert "no-store" in cache_control, (
        f"Cache-Control inadequado para endpoint de token: {cache_control!r}"
    )

    # O token devolvido deve funcionar para criar uma requisicao.
    valid = client.post(
        "/aluno/nova-requisicao",
        data={
            "csrf_token": fresh_token,
            "tipo_atividade": "Acadêmica Complementar",
            "grupo": "1 - Grupo E2E",
            "atividade_id": str(atividade_id),
            "nome_evento": f"Evento Refresh {suffix}",
            "horas_solicitadas": "4",
            "data_evento": "2028-09-12",
            "observacao": "Criada com token refrescado",
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert valid.status_code in (302, 303), (
        f"POST com token refrescado deve redirecionar 302/303 "
        f"(recebeu {valid.status_code})"
    )

    with main.app.app_context():
        conn = main.get_db_connection()
        row = conn.execute(
            "SELECT id FROM requisicoes WHERE aluno_id = ? AND nome_evento = ?",
            (aluno_id, f"Evento Refresh {suffix}"),
        ).fetchone()
        assert row is not None, "Requisicao com token refrescado nao foi criada"


def test_csrf_token_endpoint_returns_stable_token_within_session(
    isolated_client_e2e,
):
    """Refrescar o token na mesma sessao mantem o token anterior valido."""
    client = isolated_client_e2e
    suffix = uuid.uuid4().hex[:8]
    usuario_id, aluno_id, atividade_id = _setup_aluno_with_aac(suffix)
    _login_aluno(client, usuario_id, f"Aluno E2E {suffix}")

    page = client.get("/aluno/nova-requisicao")
    form_block = _extract_first_post_form(page.get_data(as_text=True))
    initial_token = _extract_csrf_token(form_block)

    refreshed = client.get("/csrf-token").get_json() or {}
    refreshed_token = refreshed.get("csrf_token")
    assert refreshed_token, "Endpoint nao devolveu csrf_token"

    # POST usando o token INICIAL (capturado na primeira renderizacao) deve
    # continuar valido apos o refresh - refrescar nao pode invalidar tokens
    # ja emitidos para a mesma sessao.
    valid_initial = client.post(
        "/aluno/nova-requisicao",
        data={
            "csrf_token": initial_token,
            "tipo_atividade": "Acadêmica Complementar",
            "grupo": "1 - Grupo E2E",
            "atividade_id": str(atividade_id),
            "nome_evento": f"Evento Token Inicial {suffix}",
            "horas_solicitadas": "3",
            "data_evento": "2028-09-13",
            "observacao": "Token inicial apos refresh",
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert valid_initial.status_code in (302, 303), (
        f"POST com token inicial deve ser aceito apos /csrf-token; "
        f"recebeu {valid_initial.status_code}"
    )

    # POST usando o token REFRESCADO tambem deve funcionar.
    valid_refreshed = client.post(
        "/aluno/nova-requisicao",
        data={
            "csrf_token": refreshed_token,
            "tipo_atividade": "Acadêmica Complementar",
            "grupo": "1 - Grupo E2E",
            "atividade_id": str(atividade_id),
            "nome_evento": f"Evento Token Refrescado {suffix}",
            "horas_solicitadas": "5",
            "data_evento": "2028-09-14",
            "observacao": "Token refrescado",
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert valid_refreshed.status_code in (302, 303), (
        f"POST com token refrescado deve ser aceito; "
        f"recebeu {valid_refreshed.status_code}"
    )

    with main.app.app_context():
        conn = main.get_db_connection()
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM requisicoes WHERE aluno_id = ?",
            (aluno_id,),
        ).fetchone()
        assert int(count["n"]) == 2, (
            f"Esperava 2 requisicoes (token inicial + refrescado), "
            f"encontrou {count['n']}"
        )


def test_csrf_time_limit_matches_session_lifetime_by_default():
    """Token nao pode expirar antes da sessao que o emitiu.

    A causa raiz reportada do 400 era WTF_CSRF_TIME_LIMIT=7200s (2h) menor
    que PERMANENT_SESSION_LIFETIME (8h em producao, 24h em dev). Confirma que
    o default agora acompanha a vida da sessao. Operadores ainda podem
    sobrescrever via env CSRF_TIME_LIMIT.
    """
    csrf_limit = int(main.app.config["WTF_CSRF_TIME_LIMIT"])
    session_lifetime = int(
        main.app.config["PERMANENT_SESSION_LIFETIME"].total_seconds()
    )
    assert csrf_limit >= session_lifetime, (
        f"WTF_CSRF_TIME_LIMIT ({csrf_limit}s) deve ser maior ou igual a "
        f"PERMANENT_SESSION_LIFETIME ({session_lifetime}s) para evitar "
        "tokens expirando antes da sessao."
    )


@pytest.mark.parametrize("shadow_read_flag", [None, "1"])
def test_admin_can_change_own_password_e2e_real_submit(
    isolated_client_e2e, monkeypatch, shadow_read_flag
):
    """Sanidade: confirma que o E2E de admin meus_dados continua valido.

    Cobre o mesmo fluxo do test_csrf_admin_flows.py, mas com extracao do action
    do form e POST direto via action declarado para detectar regressao caso o
    template passe a usar action explicito diferente do path original.
    """
    _set_shadow_read(monkeypatch, shadow_read_flag)
    client = isolated_client_e2e
    suffix = uuid.uuid4().hex[:8]
    new_password = "NovaSenhaE2E!123"

    with main.app.app_context():
        conn = main.get_db_connection()
        _seed_curso_matriz_turma(conn, suffix)
        admin_id = _seed_admin(conn, suffix)

    _login_admin(client, admin_id, f"Admin E2E {suffix}")

    page = client.get("/admin/meus_dados", follow_redirects=False)
    assert page.status_code == 200
    form_block = _extract_first_post_form(page.get_data(as_text=True))
    csrf_token = _extract_csrf_token(form_block)
    action = _extract_form_action(form_block, fallback="/admin/meus_dados")

    missing = client.post(
        action,
        data={
            "nome": f"Admin E2E {suffix}",
            "email": f"admin.e2e.{suffix}@teste.local",
            "senha": new_password,
            "remove_foto": "0",
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert missing.status_code == 400

    valid = client.post(
        action,
        data={
            "nome": f"Admin E2E {suffix}",
            "email": f"admin.e2e.{suffix}@teste.local",
            "senha": new_password,
            "remove_foto": "0",
            "csrf_token": csrf_token,
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert valid.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        row = conn.execute(
            "SELECT senha FROM usuarios WHERE id = ?", (admin_id,)
        ).fetchone()
        assert row is not None
        assert main.check_password(row["senha"], new_password)
        assert not main.check_password(row["senha"], "admin12345")
        assert not main.check_password(row["senha"], "")
