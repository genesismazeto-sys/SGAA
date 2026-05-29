import os
import re
import sys
import uuid
import io
from urllib.parse import quote

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


def _extract_form_csrf_token(html: str, form_id: str) -> str:
    marker = f'id="{form_id}"'
    start_idx = html.find(marker)
    assert start_idx != -1, f"Formulario {form_id} nao encontrado"
    end_idx = html.find("</form>", start_idx)
    assert end_idx != -1, f"Formulario {form_id} sem fechamento"
    form_block = html[start_idx:end_idx]
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', form_block)
    assert match is not None, f"Token CSRF ausente no formulario {form_id}"
    return str(match.group(1))


def _extract_enclosing_form_block(html: str, marker: str) -> str:
    marker_idx = html.find(marker)
    assert marker_idx != -1, f"Marcador {marker} nao encontrado no HTML"
    form_start = html.rfind("<form", 0, marker_idx)
    assert form_start != -1, "Tag <form nao encontrada antes do marcador"
    form_end = html.find("</form>", marker_idx)
    assert form_end != -1, "Fechamento </form> nao encontrado para o marcador"
    return html[form_start:form_end]


def _extract_hidden_value(form_block: str, field_name: str) -> str:
    match = re.search(
        rf'name="{re.escape(field_name)}"\s+value="([^"]+)"',
        form_block,
        re.IGNORECASE,
    )
    assert match is not None, f"Campo oculto {field_name} nao encontrado"
    return str(match.group(1))


def _extract_meta_csrf_token(html: str) -> str:
    match = re.search(r'<meta\s+name="csrf-token"\s+content="([^"]+)"', html, re.IGNORECASE)
    assert match is not None, "Meta csrf-token nao encontrada"
    return str(match.group(1))


def _seed_admin_entities(conn, token: str) -> dict[str, int]:
    main.ensure_admin_alertas_table(conn)
    main.ensure_reportes_table(conn)

    admin_id = conn.execute(
        "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?)",
        (
            f"Admin CSRF {token}",
            f"admin.release.csrf.{token}@teste.local",
            main.hash_password("admin123"),
            "admin",
            "admin_total",
        ),
    ).lastrowid

    aluno_email = f"release.reportes.csrf.aluno.{token}@teste.local"
    aluno_matricula = f"REL-CSRF-{token}"

    aluno_user_id = conn.execute(
        "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?)",
        ("Aluno Release CSRF", aluno_email, main.hash_password("aluno123"), "aluno", "usuario"),
    ).lastrowid
    aluno_id = conn.execute(
        "INSERT INTO alunos (usuario_id, nome, matricula, email, status) VALUES (?, ?, ?, ?, ?)",
        (aluno_user_id, "Aluno Release CSRF", aluno_matricula, aluno_email, "Ativo"),
    ).lastrowid

    atividade_id = conn.execute(
        """
        INSERT INTO atividades (grupo, nome, descricao, limite_horas, tipo_atividade, tem_limitacao)
        VALUES (?, ?, ?, ?, ?, 0)
        """,
        (
            "1 - Grupo CSRF",
            f"Atividade CSRF {token}",
            "Atividade para validar CSRF em requisicoes",
            40,
            "Acad\u00eamica Complementar",
        ),
    ).lastrowid

    requisicao_delete_id = conn.execute(
        """
        INSERT INTO requisicoes
            (aluno_id, atividade_id, data_solicitacao, data_evento, horas_solicitadas, nome_evento, status, observacao)
        VALUES (?, ?, datetime('now'), ?, ?, ?, ?, ?)
        """,
        (
            aluno_id,
            atividade_id,
            "2026-05-10",
            8,
            f"Requisicao Delete CSRF {token}",
            "Pendente",
            "Teste CSRF requisicoes",
        ),
    ).lastrowid

    reporte_status_id = conn.execute(
        """
        INSERT INTO reportes (aluno_id, titulo, descricao, categoria, status, criado_em, atualizado_em)
        VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        """,
        (aluno_id, f"Reporte Status CSRF {token}", "Atualizar status", "Bug na plataforma", "Novo"),
    ).lastrowid
    reporte_delete_id = conn.execute(
        """
        INSERT INTO reportes (aluno_id, titulo, descricao, categoria, status, criado_em, atualizado_em)
        VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        """,
        (aluno_id, f"Reporte Delete CSRF {token}", "Excluir reporte", "Outro", "Novo"),
    ).lastrowid
    conn.commit()

    return {
        "admin_id": int(admin_id),
        "reporte_status_id": int(reporte_status_id),
        "reporte_delete_id": int(reporte_delete_id),
        "requisicao_delete_id": int(requisicao_delete_id),
    }


@pytest.fixture()
def isolated_client_csrf(tmp_path):
    app = main.app
    temp_database = tmp_path / "release_admin_actions_csrf.db"
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


def test_release_admin_post_actions_require_active_csrf_token(isolated_client_csrf):
    client = isolated_client_csrf
    token = uuid.uuid4().hex[:8]

    with main.app.app_context():
        conn = main.get_db_connection()
        seeded = _seed_admin_entities(conn, token)

    _login_admin_user(client, seeded["admin_id"], f"Admin CSRF {token}")

    # Mensagens: salvar e resetar com CSRF ativo.
    mensagens_page = client.get("/admin/mensagens")
    assert mensagens_page.status_code == 200
    mensagens_html = mensagens_page.get_data(as_text=True)
    mensagens_form = _extract_enclosing_form_block(mensagens_html, 'name="message_key"')
    mensagens_csrf = _extract_hidden_value(mensagens_form, "csrf_token")
    message_key = _extract_hidden_value(mensagens_form, "message_key")
    message_url_key = quote(message_key, safe="")
    custom_message = f"Mensagem CSRF {token}"

    missing_message_save_csrf = client.post(
        "/admin/mensagens/salvar",
        data={"message_key": message_key, "message_text": custom_message},
        follow_redirects=False,
    )
    assert missing_message_save_csrf.status_code == 400

    ok_message_save = client.post(
        "/admin/mensagens/salvar",
        data={
            "message_key": message_key,
            "message_text": custom_message,
            "csrf_token": mensagens_csrf,
        },
        follow_redirects=False,
    )
    assert ok_message_save.status_code in (302, 303)
    assert "/admin/mensagens" in (ok_message_save.headers.get("Location") or "")

    with main.app.app_context():
        conn = main.get_db_connection()
        saved_override = conn.execute(
            "SELECT texto FROM mensagens_editaveis WHERE chave = ?",
            (message_key,),
        ).fetchone()
    assert saved_override is not None
    assert saved_override["texto"] == custom_message

    missing_message_reset_csrf = client.post(
        f"/admin/mensagens/{message_url_key}/reset",
        follow_redirects=False,
    )
    assert missing_message_reset_csrf.status_code == 400

    ok_message_reset = client.post(
        f"/admin/mensagens/{message_url_key}/reset",
        data={"csrf_token": mensagens_csrf},
        follow_redirects=False,
    )
    assert ok_message_reset.status_code in (302, 303)
    assert "/admin/mensagens" in (ok_message_reset.headers.get("Location") or "")

    with main.app.app_context():
        conn = main.get_db_connection()
        reset_override = conn.execute(
            "SELECT 1 FROM mensagens_editaveis WHERE chave = ?",
            (message_key,),
        ).fetchone()
    assert reset_override is None

    # Reportes: status e exclusao.
    page = client.get("/admin/reportes")
    assert page.status_code == 200
    html = page.get_data(as_text=True)

    status_csrf = _extract_form_csrf_token(html, "rm-status-form")
    delete_csrf = _extract_form_csrf_token(html, "rm-delete-form")
    assert status_csrf
    assert delete_csrf

    missing_status_csrf = client.post(
        f"/admin/reportes/{seeded['reporte_status_id']}/status",
        data={"status": "Em análise"},
        follow_redirects=False,
    )
    assert missing_status_csrf.status_code == 400

    with main.app.app_context():
        conn = main.get_db_connection()
        unchanged_status = conn.execute(
            "SELECT status FROM reportes WHERE id = ?",
            (seeded["reporte_status_id"],),
        ).fetchone()
    assert unchanged_status is not None
    assert unchanged_status["status"] == "Novo"

    ok_status = client.post(
        f"/admin/reportes/{seeded['reporte_status_id']}/status",
        data={"status": "Resolvido", "csrf_token": status_csrf},
        follow_redirects=False,
    )
    assert ok_status.status_code in (302, 303)
    assert "/admin/reportes" in (ok_status.headers.get("Location") or "")

    with main.app.app_context():
        conn = main.get_db_connection()
        updated_status = conn.execute(
            "SELECT status FROM reportes WHERE id = ?",
            (seeded["reporte_status_id"],),
        ).fetchone()
    assert updated_status is not None
    assert updated_status["status"] == "Resolvido"

    missing_delete_csrf = client.post(
        f"/admin/reportes/{seeded['reporte_delete_id']}/deletar",
        follow_redirects=False,
    )
    assert missing_delete_csrf.status_code == 400

    with main.app.app_context():
        conn = main.get_db_connection()
        still_exists = conn.execute(
            "SELECT 1 FROM reportes WHERE id = ?",
            (seeded["reporte_delete_id"],),
        ).fetchone()
    assert still_exists is not None

    ok_delete = client.post(
        f"/admin/reportes/{seeded['reporte_delete_id']}/deletar",
        data={"csrf_token": delete_csrf},
        follow_redirects=False,
    )
    assert ok_delete.status_code in (302, 303)
    assert "/admin/reportes" in (ok_delete.headers.get("Location") or "")

    with main.app.app_context():
        conn = main.get_db_connection()
        removed = conn.execute(
            "SELECT 1 FROM reportes WHERE id = ?",
            (seeded["reporte_delete_id"],),
        ).fetchone()
    assert removed is None

    # Configuracoes: salvar tempo-resposta com CSRF ativo.
    cfg_page = client.get("/admin/configuracoes")
    assert cfg_page.status_code == 200
    cfg_html = cfg_page.get_data(as_text=True)
    cfg_csrf = _extract_form_csrf_token(cfg_html, "response-settings-form")

    missing_cfg_csrf = client.post(
        "/admin/configuracoes/tempo-resposta",
        data={"response_goal_days": "11", "response_metrics_reset_at": ""},
        follow_redirects=False,
    )
    assert missing_cfg_csrf.status_code == 400

    ok_cfg = client.post(
        "/admin/configuracoes/tempo-resposta",
        data={
            "response_goal_days": "11",
            "response_metrics_reset_at": "",
            "csrf_token": cfg_csrf,
        },
        follow_redirects=False,
    )
    assert ok_cfg.status_code in (302, 303)
    assert "/admin/configuracoes" in (ok_cfg.headers.get("Location") or "")

    with main.app.app_context():
        conn = main.get_db_connection()
        cfg_settings = main.get_response_time_settings(conn)
    assert int(cfg_settings["response_goal_days"]) == 11

    # Alertas: salvar (form), alternar (fetch/header) e excluir (fetch/header).
    alertas_page = client.get("/admin/alertas")
    assert alertas_page.status_code == 200
    alertas_html = alertas_page.get_data(as_text=True)
    alertas_form_csrf = _extract_form_csrf_token(alertas_html, "admin-alerta-form")
    alertas_meta_csrf = _extract_meta_csrf_token(alertas_html)
    alerta_title = f"Alerta CSRF {token}"

    missing_alerta_save_csrf = client.post(
        "/admin/alertas/salvar",
        data={
            "titulo": alerta_title,
            "mensagem": "Mensagem alerta csrf",
            "bg_color": "#e3eefd",
            "border_color": "#7e95b2",
            "visivel": "1",
        },
        follow_redirects=False,
    )
    assert missing_alerta_save_csrf.status_code == 400

    ok_alerta_save = client.post(
        "/admin/alertas/salvar",
        data={
            "titulo": alerta_title,
            "mensagem": "Mensagem alerta csrf",
            "bg_color": "#e3eefd",
            "border_color": "#7e95b2",
            "visivel": "1",
            "csrf_token": alertas_form_csrf,
        },
        follow_redirects=False,
    )
    assert ok_alerta_save.status_code in (302, 303)
    assert "/admin/alertas" in (ok_alerta_save.headers.get("Location") or "")

    with main.app.app_context():
        conn = main.get_db_connection()
        alerta_row = conn.execute(
            "SELECT id, visivel FROM admin_alertas WHERE titulo = ? ORDER BY id DESC LIMIT 1",
            (alerta_title,),
        ).fetchone()
    assert alerta_row is not None
    alerta_id = int(alerta_row["id"])
    assert int(alerta_row["visivel"]) == 1

    missing_alerta_toggle_csrf = client.post(
        f"/admin/alertas/{alerta_id}/alternar",
        follow_redirects=False,
    )
    assert missing_alerta_toggle_csrf.status_code == 400

    ok_alerta_toggle = client.post(
        f"/admin/alertas/{alerta_id}/alternar",
        headers={"X-CSRFToken": alertas_meta_csrf},
        follow_redirects=False,
    )
    assert ok_alerta_toggle.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        alerta_toggled = conn.execute(
            "SELECT visivel FROM admin_alertas WHERE id = ?",
            (alerta_id,),
        ).fetchone()
    assert alerta_toggled is not None
    assert int(alerta_toggled["visivel"]) == 0

    missing_alerta_delete_csrf = client.post(
        f"/admin/alertas/{alerta_id}/deletar",
        follow_redirects=False,
    )
    assert missing_alerta_delete_csrf.status_code == 400

    ok_alerta_delete = client.post(
        f"/admin/alertas/{alerta_id}/deletar",
        headers={"X-CSRFToken": alertas_meta_csrf},
        follow_redirects=False,
    )
    assert ok_alerta_delete.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        alerta_removed = conn.execute(
            "SELECT 1 FROM admin_alertas WHERE id = ?",
            (alerta_id,),
        ).fetchone()
    assert alerta_removed is None

    # Requisicoes: excluir via fluxo fetch com header CSRF.
    req_page = client.get("/admin/requisicoes")
    assert req_page.status_code == 200
    req_html = req_page.get_data(as_text=True)
    req_meta_csrf = _extract_meta_csrf_token(req_html)

    missing_req_delete_csrf = client.post(
        f"/admin/requisicoes/{seeded['requisicao_delete_id']}/excluir",
        follow_redirects=False,
    )
    assert missing_req_delete_csrf.status_code == 400

    ok_req_delete = client.post(
        f"/admin/requisicoes/{seeded['requisicao_delete_id']}/excluir",
        headers={"X-Requested-With": "XMLHttpRequest", "X-CSRFToken": req_meta_csrf},
        follow_redirects=False,
    )
    assert ok_req_delete.status_code == 204

    with main.app.app_context():
        conn = main.get_db_connection()
        req_removed = conn.execute(
            "SELECT 1 FROM requisicoes WHERE id = ?",
            (seeded["requisicao_delete_id"],),
        ).fetchone()
    assert req_removed is None

    # Banco de dados: acao sensivel de retencao com CSRF.
    banco_page = client.get("/admin/banco-dados")
    assert banco_page.status_code == 200
    banco_html = banco_page.get_data(as_text=True)
    retention_csrf = _extract_form_csrf_token(banco_html, "retention-form")
    restore_upload_csrf = _extract_form_csrf_token(banco_html, "restore-upload-form")
    retention_payload = {
        "retention_w0_interval_hours": "3",
        "retention_w0_slots": "8",
        "retention_w1_interval_hours": "24",
        "retention_w1_slots": "6",
        "retention_w2_interval_hours": "168",
        "retention_w2_slots": "3",
        "retention_w3_interval_hours": "730",
        "retention_w3_slots": "10",
    }

    missing_retention_csrf = client.post(
        "/admin/banco-dados/retencao",
        data=retention_payload,
        follow_redirects=False,
    )
    assert missing_retention_csrf.status_code == 400

    ok_retention = client.post(
        "/admin/banco-dados/retencao",
        data={**retention_payload, "csrf_token": retention_csrf},
        follow_redirects=False,
    )
    assert ok_retention.status_code in (302, 303)
    assert "/admin/banco-dados" in (ok_retention.headers.get("Location") or "")

    missing_restore_upload_csrf = client.post(
        "/admin/banco-dados/restaurar/upload",
        data={"backup_file": (io.BytesIO(b"not-sqlite"), "restore.db")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert missing_restore_upload_csrf.status_code == 400

    ok_restore_upload = client.post(
        "/admin/banco-dados/restaurar/upload",
        data={
            "csrf_token": restore_upload_csrf,
            "backup_file": (io.BytesIO(b"not-sqlite"), "restore.db"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert ok_restore_upload.status_code in (302, 303)
    assert "/admin/banco-dados" in (ok_restore_upload.headers.get("Location") or "")

    with main.app.app_context():
        conn = main.get_db_connection()
        retention_settings = main.get_retention_policy(conn)
    assert retention_settings["retention_w0_interval_hours"] == "3"
    assert retention_settings["retention_w0_slots"] == "8"