import io
import os
import sys
import uuid

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from app import db as app_db_module
import main


def _login_admin_user(client, user_id: int, user_name: str) -> None:
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["user_type"] = "admin"
        sess["user_name"] = user_name


def _create_admin_user(conn, *, name: str, email: str, access_level: str) -> int:
    return int(
        conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?)",
            (name, email, main.hash_password("admin123"), "admin", access_level),
        ).lastrowid
    )


def _seed_operational_entities(conn, token: str) -> dict[str, int]:
    main.ensure_admin_alertas_table(conn)
    main.ensure_reportes_table(conn)
    main.ensure_admin_arquivos_table(conn)
    main.ensure_usuario_access_schema(conn)

    aluno_email = f"release.admin.actions.aluno.{token}@teste.local"
    aluno_matricula = f"REL-ACT-{token}"

    curso_id = conn.execute(
        "INSERT INTO cursos (nome, codigo, duracao_periodos, status) VALUES (?, ?, ?, ?) RETURNING id",
        (f"Curso Release Actions {token}", f"RELACT{token.upper()}", 8, "ativo"),
    ).fetchone()["id"]
    matriz_id = conn.execute(
        "INSERT INTO matrizes_atividades (curso_id, nome, versao, status, data_inicio_vigencia) VALUES (?, ?, ?, ?, ?) RETURNING id",
        (curso_id, f"Matriz Release Actions {token}", "1", "vigente", "2026-01-01"),
    ).fetchone()["id"]
    turma_id = conn.execute(
        "INSERT INTO turmas (nome, status, numero, curso_id, matriz_id, codigo) VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
        (f"Turma Release Actions {token}", "Ativa", 1, curso_id, matriz_id, f"RELACT-{token}"),
    ).fetchone()["id"]

    aluno_user_id = conn.execute(
        "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?)",
        ("Aluno Release Acoes", aluno_email, main.hash_password("aluno123"), "aluno", "usuario"),
    ).lastrowid
    aluno_id = conn.execute(
        "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status) VALUES (?, ?, ?, ?, ?, ?)",
        (aluno_user_id, "Aluno Release Acoes", aluno_matricula, aluno_email, turma_id, "Ativo"),
    ).lastrowid
    atividade_id = conn.execute(
        """
        INSERT INTO atividades (grupo, nome, descricao, limite_horas, tipo_atividade, tem_limitacao)
        VALUES (?, ?, ?, ?, ?, 0)
        """,
        (
            "1 - Grupo Release Actions",
            f"Atividade Release Actions {token}",
            "Atividade para validar acoes administrativas",
            40,
                "Acad\u00eamica Complementar",
        ),
    ).lastrowid
    conn.execute(
        "INSERT INTO matrizes_atividades_itens (matriz_id, atividade_id) VALUES (?, ?)",
        (matriz_id, atividade_id),
    )

    alerta_toggle_id = conn.execute(
        "INSERT INTO admin_alertas (titulo, mensagem, bg_color, border_color, visivel) VALUES (?, ?, ?, ?, ?)",
        (f"Alerta Toggle {token}", "Toggle", "#e3eefd", "#7e95b2", 1),
    ).lastrowid
    alerta_edit_id = conn.execute(
        "INSERT INTO admin_alertas (titulo, mensagem, bg_color, border_color, visivel) VALUES (?, ?, ?, ?, ?)",
        (f"Alerta Edit {token}", "Editar", "#fef4c0", "#c9a227", 1),
    ).lastrowid
    alerta_delete_id = conn.execute(
        "INSERT INTO admin_alertas (titulo, mensagem, bg_color, border_color, visivel) VALUES (?, ?, ?, ?, ?)",
        (f"Alerta Delete {token}", "Excluir", "#dcfaeb", "#4ea86a", 1),
    ).lastrowid

    reporte_status_id = conn.execute(
        """
        INSERT INTO reportes (aluno_id, titulo, descricao, categoria, status, criado_em, atualizado_em)
        VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        """,
        (aluno_id, f"Reporte Status {token}", "Atualizar status", "Bug na plataforma", "Novo"),
    ).lastrowid
    reporte_delete_id = conn.execute(
        """
        INSERT INTO reportes (aluno_id, titulo, descricao, categoria, status, criado_em, atualizado_em)
        VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        """,
        (aluno_id, f"Reporte Delete {token}", "Excluir", "Lentidao", "Novo"),
    ).lastrowid

    req_existing_id = conn.execute(
        """
        INSERT INTO requisicoes (aluno_id, atividade_id, data_solicitacao, data_evento, horas_solicitadas, nome_evento, status, observacao)
        VALUES (?, ?, datetime('now'), ?, ?, ?, ?, ?)
        """,
        (aluno_id, atividade_id, "2026-05-10", 6, f"Evento Existente {token}", "Pendente", "Seed de permissao"),
    ).lastrowid

    conn.commit()

    return {
        "aluno_id": int(aluno_id),
        "atividade_id": int(atividade_id),
        "alerta_toggle_id": int(alerta_toggle_id),
        "alerta_edit_id": int(alerta_edit_id),
        "alerta_delete_id": int(alerta_delete_id),
        "reporte_status_id": int(reporte_status_id),
        "reporte_delete_id": int(reporte_delete_id),
        "req_existing_id": int(req_existing_id),
    }


def _assert_denied(response) -> None:
    location = response.headers.get("Location", "")
    if response.status_code == 403:
        return
    assert response.status_code in (301, 302, 303, 307, 308)
    assert "/admin/dashboard" in location


@pytest.fixture()
def isolated_client(tmp_path):
    app = main.app
    temp_database = tmp_path / "release_admin_actions.db"
    temp_uploads = tmp_path / "uploads"
    temp_uploads.mkdir(parents=True, exist_ok=True)

    original_database = main.DATABASE
    original_env_database = os.environ.get("APP_DATABASE")
    original_config_database_path = app.config.get("DATABASE_PATH")
    original_upload_folder = app.config.get("UPLOAD_FOLDER")
    original_local_backup_dir = app.config.get("LOCAL_BACKUP_DIR")
    original_cloud_backup_dir = app.config.get("CLOUD_BACKUP_DIR")
    original_cloud_sync_interval = app.config.get("CLOUD_SYNC_INTERVAL_SECONDS")
    original_external_backup_enabled = app.config.get("EXTERNAL_BACKUP_ENABLED")

    os.environ["APP_DATABASE"] = str(temp_database)
    main.DATABASE = str(temp_database)
    app_db_module.DATABASE = str(temp_database)
    app.config["DATABASE_PATH"] = str(temp_database)
    app.config["TESTING"] = True
    app.config["UPLOAD_FOLDER"] = str(temp_uploads)
    app.config["LOCAL_BACKUP_DIR"] = str(tmp_path / "backups" / "local")
    app.config["CLOUD_BACKUP_DIR"] = ""
    app.config["CLOUD_SYNC_INTERVAL_SECONDS"] = 0
    app.config["EXTERNAL_BACKUP_ENABLED"] = False

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
        app.config["LOCAL_BACKUP_DIR"] = original_local_backup_dir
        app.config["CLOUD_BACKUP_DIR"] = original_cloud_backup_dir
        app.config["CLOUD_SYNC_INTERVAL_SECONDS"] = original_cloud_sync_interval
        app.config["EXTERNAL_BACKUP_ENABLED"] = original_external_backup_enabled

        if original_env_database is None:
            os.environ.pop("APP_DATABASE", None)
        else:
            os.environ["APP_DATABASE"] = original_env_database


def test_release_admin_actions_admin_total_write_flows(isolated_client):
    client = isolated_client
    token = uuid.uuid4().hex[:8]

    with main.app.app_context():
        conn = main.get_db_connection()
        seeded = _seed_operational_entities(conn, token)

    _login_admin_user(client, 1, "Administrador")

    # Alertas: ativar/desativar, editar e excluir.
    toggle_resp = client.post(f"/admin/alertas/{seeded['alerta_toggle_id']}/alternar", follow_redirects=False)
    assert toggle_resp.status_code in (302, 303)

    edit_resp = client.post(
        "/admin/alertas/salvar",
        data={
            "alerta_id": str(seeded["alerta_edit_id"]),
            "titulo": f"Alerta Editado {token}",
            "mensagem": "Mensagem editada no release",
            "bg_color": "#e3eefd",
            "border_color": "#7e95b2",
            "visivel": "1",
        },
        follow_redirects=False,
    )
    assert edit_resp.status_code in (302, 303)

    delete_alert_resp = client.post(
        f"/admin/alertas/{seeded['alerta_delete_id']}/deletar",
        follow_redirects=False,
    )
    assert delete_alert_resp.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        toggled = conn.execute(
            "SELECT visivel FROM admin_alertas WHERE id = ?",
            (seeded["alerta_toggle_id"],),
        ).fetchone()
        edited = conn.execute(
            "SELECT titulo, mensagem FROM admin_alertas WHERE id = ?",
            (seeded["alerta_edit_id"],),
        ).fetchone()
        removed = conn.execute(
            "SELECT 1 FROM admin_alertas WHERE id = ?",
            (seeded["alerta_delete_id"],),
        ).fetchone()
    assert toggled is not None and int(toggled["visivel"]) == 0
    assert edited is not None and edited["titulo"] == f"Alerta Editado {token}"
    assert removed is None

    # Reportes: atualizar status e excluir sem 405.
    status_resp = client.post(
        f"/admin/reportes/{seeded['reporte_status_id']}/status",
        data={"status": "Em análise"},
        follow_redirects=False,
    )
    assert status_resp.status_code != 405
    assert status_resp.status_code in (302, 303)

    delete_reporte_resp = client.post(
        f"/admin/reportes/{seeded['reporte_delete_id']}/deletar",
        follow_redirects=False,
    )
    assert delete_reporte_resp.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        reporte_updated = conn.execute(
            "SELECT status FROM reportes WHERE id = ?",
            (seeded["reporte_status_id"],),
        ).fetchone()
        reporte_deleted = conn.execute(
            "SELECT 1 FROM reportes WHERE id = ?",
            (seeded["reporte_delete_id"],),
        ).fetchone()
    assert reporte_updated is not None and reporte_updated["status"] == "Em análise"
    assert reporte_deleted is None

    # Arquivos: adicionar, editar e excluir.
    arquivo_titulo = f"Arquivo release {token}"
    add_file_resp = client.post(
        "/admin/arquivos/adicionar",
        data={
            "titulo": arquivo_titulo,
            "descricao": "Arquivo criado no release actions",
            "visivel": "1",
            "arquivo": (io.BytesIO(b"%PDF-1.4\n% release admin actions\n"), f"release-{token}.pdf"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert add_file_resp.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        arquivo = conn.execute(
            "SELECT id FROM admin_arquivos WHERE titulo = ? ORDER BY id DESC LIMIT 1",
            (arquivo_titulo,),
        ).fetchone()
    assert arquivo is not None
    arquivo_id = int(arquivo["id"])

    edit_file_resp = client.post(
        f"/admin/arquivos/{arquivo_id}/editar",
        data={
            "titulo": f"Arquivo release editado {token}",
            "descricao": "Descricao editada",
            "visivel": "0",
        },
        follow_redirects=False,
    )
    assert edit_file_resp.status_code in (302, 303)

    delete_file_resp = client.post(f"/admin/arquivos/{arquivo_id}/deletar", follow_redirects=False)
    assert delete_file_resp.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        arquivo_deleted = conn.execute("SELECT 1 FROM admin_arquivos WHERE id = ?", (arquivo_id,)).fetchone()
    assert arquivo_deleted is None

    # Requisicoes: nova, processar e excluir.
    req_event_name = f"Evento Release Actions {token}"
    create_req_resp = client.post(
        "/admin/requisicoes/nova",
        data={
            "aluno_id": str(seeded["aluno_id"]),
            "atividade_id": str(seeded["atividade_id"]),
            "nome_evento": req_event_name,
            "horas_solicitadas": "8",
            "data_evento": "2026-05-15",
            "observacao": "Criada no release actions",
        },
        follow_redirects=False,
    )
    assert create_req_resp.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        req_created = conn.execute(
            "SELECT id, status FROM requisicoes WHERE nome_evento = ? ORDER BY id DESC LIMIT 1",
            (req_event_name,),
        ).fetchone()
    assert req_created is not None
    req_created_id = int(req_created["id"])

    process_req_resp = client.post(
        f"/admin/processar_requisicao/{req_created_id}",
        data={
            "status": "Devolvida",
            "observacao": "Processada no release actions",
            "horas_deferidas": "",
        },
        follow_redirects=False,
    )
    assert process_req_resp.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        req_processed = conn.execute(
            "SELECT status FROM requisicoes WHERE id = ?",
            (req_created_id,),
        ).fetchone()
    assert req_processed is not None and req_processed["status"] == "Devolvida"

    delete_req_resp = client.post(f"/admin/requisicoes/{req_created_id}/excluir", follow_redirects=False)
    assert delete_req_resp.status_code == 204

    with main.app.app_context():
        conn = main.get_db_connection()
        req_deleted = conn.execute("SELECT 1 FROM requisicoes WHERE id = ?", (req_created_id,)).fetchone()
    assert req_deleted is None


def test_release_admin_actions_permissions_and_hidden_writes_for_consultivo(isolated_client):
    client = isolated_client
    token = uuid.uuid4().hex[:8]

    with main.app.app_context():
        conn = main.get_db_connection()
        seeded = _seed_operational_entities(conn, token)
        consultivo_id = _create_admin_user(
            conn,
            name=f"Consultivo Release {token}",
            email=f"consultivo.release.{token}@teste.local",
            access_level="consultivo",
        )
        conn.commit()

    _login_admin_user(client, consultivo_id, "Consultivo Release")

    reportes_page = client.get("/admin/reportes", follow_redirects=False)
    assert reportes_page.status_code == 200
    reportes_html = reportes_page.get_data(as_text=True)
    assert "const canReportesEdit = false;" in reportes_html
    assert 'reporte-modal-status-block" hidden' in reportes_html
    assert "Salvar status" not in reportes_html

    denied_alert_toggle = client.post(f"/admin/alertas/{seeded['alerta_toggle_id']}/alternar", follow_redirects=False)
    _assert_denied(denied_alert_toggle)

    denied_alert_delete = client.post(f"/admin/alertas/{seeded['alerta_delete_id']}/deletar", follow_redirects=False)
    _assert_denied(denied_alert_delete)

    denied_report_status = client.post(
        f"/admin/reportes/{seeded['reporte_status_id']}/status",
        data={"status": "Resolvido"},
        follow_redirects=False,
    )
    assert denied_report_status.status_code != 405
    _assert_denied(denied_report_status)

    with main.app.app_context():
        conn = main.get_db_connection()
        report_status = conn.execute(
            "SELECT status FROM reportes WHERE id = ?",
            (seeded["reporte_status_id"],),
        ).fetchone()
    assert report_status is not None and report_status["status"] == "Novo"

    denied_report_delete = client.post(
        f"/admin/reportes/{seeded['reporte_delete_id']}/deletar",
        follow_redirects=False,
    )
    _assert_denied(denied_report_delete)

    denied_file_add = client.post(
        "/admin/arquivos/adicionar",
        data={
            "titulo": f"Arquivo negado {token}",
            "descricao": "Sem permissao",
            "visivel": "1",
            "arquivo": (io.BytesIO(b"%PDF-1.4\n% denied\n"), f"denied-{token}.pdf"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    _assert_denied(denied_file_add)

    denied_req_new = client.post(
        "/admin/requisicoes/nova",
        data={
            "aluno_id": str(seeded["aluno_id"]),
            "atividade_id": str(seeded["atividade_id"]),
            "nome_evento": f"Evento Negado {token}",
            "horas_solicitadas": "4",
            "data_evento": "2026-06-10",
            "observacao": "Nao deveria criar",
        },
        follow_redirects=False,
    )
    _assert_denied(denied_req_new)

    denied_req_process = client.post(
        f"/admin/processar_requisicao/{seeded['req_existing_id']}",
        data={"status": "Devolvida", "observacao": "Negado", "horas_deferidas": ""},
        follow_redirects=False,
    )
    _assert_denied(denied_req_process)

    denied_req_delete = client.post(
        f"/admin/requisicoes/{seeded['req_existing_id']}/excluir",
        follow_redirects=False,
    )
    _assert_denied(denied_req_delete)

    denied_banco_retencao = client.post("/admin/banco-dados/retencao", data={}, follow_redirects=False)
    _assert_denied(denied_banco_retencao)

    denied_mensagens_salvar = client.post(
        "/admin/mensagens/salvar",
        data={"message_key": "login_success", "message_text": "Sem permissao"},
        follow_redirects=False,
    )
    _assert_denied(denied_mensagens_salvar)

    denied_mensagens_resetar = client.post(
        "/admin/mensagens/login_success/reset",
        follow_redirects=False,
    )
    _assert_denied(denied_mensagens_resetar)

    denied_config_save = client.post(
        "/admin/configuracoes/tempo-resposta",
        data={"response_goal_days": "10", "response_metrics_reset_at": ""},
        follow_redirects=False,
    )
    _assert_denied(denied_config_save)
