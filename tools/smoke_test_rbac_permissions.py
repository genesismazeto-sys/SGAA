import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from typing import Any


BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)


@dataclass
class CheckResult:
    profile: str
    check: str
    ok: bool
    status: int
    location: str
    detail: str


def _is_dashboard_redirect(status: int, location: str) -> bool:
    if status not in (301, 302, 303, 307, 308):
        return False
    return "/admin/dashboard" in (location or "")


def _is_denied(status: int, location: str) -> bool:
    return status == 403 or _is_dashboard_redirect(status, location)


def _make_request(client, method: str, path: str, **kwargs):
    method_fn = getattr(client, method.lower())
    kwargs.setdefault("follow_redirects", False)
    return method_fn(path, **kwargs)


def _login_as_admin(client, user_id: int, user_name: str) -> None:
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["user_name"] = user_name
        sess["user_type"] = "admin"


def _record_access_check(results: list[CheckResult], profile: str, label: str, response, expect_allowed: bool) -> None:
    status = response.status_code
    location = response.headers.get("Location", "")
    denied = _is_denied(status, location)
    allowed = (not denied) and status < 500
    ok = allowed if expect_allowed else denied
    detail = "allowed" if allowed else "denied"
    results.append(
        CheckResult(
            profile=profile,
            check=label,
            ok=ok,
            status=status,
            location=location,
            detail=detail,
        )
    )


def _record_ui_check(results: list[CheckResult], profile: str, label: str, ok: bool, detail: str) -> None:
    results.append(
        CheckResult(
            profile=profile,
            check=label,
            ok=ok,
            status=200,
            location="",
            detail=detail,
        )
    )


def _contains_all(html: str, needles: list[str]) -> bool:
    return all(needle in html for needle in needles)


def _contains_none(html: str, needles: list[str]) -> bool:
    return all(needle not in html for needle in needles)


def _setup_environment(temp_root: str, test_db: str) -> None:
    os.environ["APP_DATABASE"] = test_db
    os.environ["APP_ENV"] = "testing"
    os.environ["DISABLE_CSRF"] = "1"
    os.environ["APP_BOOTSTRAP_DEFAULT_ADMIN"] = "0"
    os.environ["APP_SECRET_KEY"] = "rbac-smoke-secret-key-only-for-tests-1234567890"
    os.environ["APP_LOCAL_BACKUP_DIR"] = os.path.join(temp_root, "backups", "local")
    os.environ["APP_CLOUD_BACKUP_DIR"] = ""
    os.environ["APP_CLOUD_SYNC_INTERVAL_SECONDS"] = "0"
    os.environ["APP_EXTERNAL_BACKUP_ENABLED"] = "0"


def _create_admin_user(main_module, conn, name: str, email: str, access_level: str) -> int:
    cursor = conn.execute(
        "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?)",
        (name, email, main_module.hash_password("x"), "admin", access_level),
    )
    return int(cursor.lastrowid)


def run() -> int:
    temp_root = tempfile.mkdtemp(prefix="rbac-smoke-")
    test_db = os.path.join(temp_root, "rbac_smoke.db")
    uploads_dir = os.path.join(temp_root, "uploads")
    os.makedirs(uploads_dir, exist_ok=True)

    _setup_environment(temp_root, test_db)

    try:
        import main  # noqa: PLC0415
    except Exception as exc:  # pragma: no cover - script mode
        print(json.dumps({"ok": False, "phase": "import", "error": str(exc)}, ensure_ascii=False, indent=2))
        shutil.rmtree(temp_root, ignore_errors=True)
        return 2

    main.DATABASE = test_db
    main.app.config["DATABASE_PATH"] = test_db
    main.app.config["TESTING"] = True
    main.app.config["UPLOAD_FOLDER"] = uploads_dir
    main.app.config["LOCAL_BACKUP_DIR"] = os.path.join(temp_root, "backups", "local")
    main.app.config["CLOUD_BACKUP_DIR"] = ""
    main.app.config["CLOUD_SYNC_INTERVAL_SECONDS"] = 0
    main.app.config["EXTERNAL_BACKUP_ENABLED"] = False

    results: list[CheckResult] = []

    with main.app.app_context():
        main.init_db()
        conn = main.get_db_connection()
        main.ensure_usuario_access_schema(conn)
        main.ensure_admin_alertas_table(conn)
        main.ensure_admin_arquivos_table(conn)

        admin_total_id = _create_admin_user(main, conn, "RBAC Admin Total", "rbac.admin_total@example.com", "admin_total")
        administrativo_id = _create_admin_user(main, conn, "RBAC Administrativo", "rbac.administrativo@example.com", "administrativo")
        consultivo_id = _create_admin_user(main, conn, "RBAC Consultivo", "rbac.consultivo@example.com", "consultivo")
        arquivos_none_id = _create_admin_user(main, conn, "RBAC Arquivos None", "rbac.arquivos_none@example.com", "admin_total")

        conn.execute(
            "INSERT INTO usuarios_permissoes_acesso (usuario_id, recurso, escopo) VALUES (?, ?, ?)",
            (arquivos_none_id, "arquivos", "none"),
        )

        cursor = conn.execute(
            "INSERT INTO admin_alertas (titulo, mensagem, bg_color, border_color, visivel) VALUES (?, ?, ?, ?, ?)",
            ("Alerta RBAC 1", "Mensagem RBAC 1", "#e3eefd", "#b6cff5", 1),
        )
        alerta_toggle_id = int(cursor.lastrowid)

        cursor = conn.execute(
            "INSERT INTO admin_alertas (titulo, mensagem, bg_color, border_color, visivel) VALUES (?, ?, ?, ?, ?)",
            ("Alerta RBAC 2", "Mensagem RBAC 2", "#e3eefd", "#b6cff5", 1),
        )
        alerta_delete_id = int(cursor.lastrowid)

        upload_relpath = "rbac_uploads/documento_rbac.pdf"
        upload_abspath = os.path.join(uploads_dir, upload_relpath)
        os.makedirs(os.path.dirname(upload_abspath), exist_ok=True)
        with open(upload_abspath, "wb") as file_handle:
            file_handle.write(b"%PDF-1.4\n% RBAC smoke file\n")

        conn.execute(
            "INSERT INTO admin_arquivos (titulo, descricao, filename, original_filename, visivel) VALUES (?, ?, ?, ?, ?)",
            ("Arquivo RBAC", "Arquivo para smoke RBAC", upload_relpath, "documento_rbac.pdf", 1),
        )

        conn.commit()

    client = main.app.test_client()

    endpoint_specs: dict[str, list[dict[str, Any]]] = {
        "admin_total": [
            {"label": "configuracoes_get", "method": "GET", "path": "/admin/configuracoes", "allow": True},
            {
                "label": "configuracoes_post",
                "method": "POST",
                "path": "/admin/configuracoes/tempo-resposta",
                "allow": True,
                "kwargs": {"data": {"response_goal_days": "10", "response_metrics_reset_at": ""}},
            },
            {"label": "mensagens_get", "method": "GET", "path": "/admin/mensagens", "allow": True},
            {
                "label": "mensagens_post",
                "method": "POST",
                "path": "/admin/mensagens/salvar",
                "allow": True,
                "kwargs": {"data": {"message_key": "login_success", "message_text": "Mensagem RBAC"}},
            },
            {"label": "presets_get", "method": "GET", "path": "/admin/api/presets", "allow": True},
            {
                "label": "presets_post",
                "method": "POST",
                "path": "/admin/api/presets",
                "allow": True,
                "kwargs": {"data": json.dumps({"respostas": [], "emails": []}), "content_type": "application/json"},
            },
            {"label": "alerta_toggle", "method": "POST", "path": f"/admin/alertas/{alerta_toggle_id}/alternar", "allow": True},
            {"label": "alerta_delete", "method": "POST", "path": f"/admin/alertas/{alerta_delete_id}/deletar", "allow": True},
            {
                "label": "banco_retencao",
                "method": "POST",
                "path": "/admin/banco-dados/retencao",
                "allow": True,
                "kwargs": {"data": {}},
            },
            {
                "label": "banco_drive_settings",
                "method": "POST",
                "path": "/admin/banco-dados/drive-settings",
                "allow": True,
                "kwargs": {"data": {"provider": "google", "gdrive_dest_folder": "Backups/sistema", "gdrive_enabled": "1"}},
            },
            {
                "label": "banco_oauth_start",
                "method": "GET",
                "path": "/admin/banco-dados/oauth/start?provider=google",
                "allow": True,
            },
            {"label": "cloud_folder_get", "method": "GET", "path": "/admin/backup/cloud-folder/google", "allow": True},
            {"label": "auth_callback", "method": "GET", "path": "/auth/callback", "allow": True},
            {"label": "google_callback", "method": "GET", "path": "/google/callback", "allow": True},
            {"label": "onedrive_callback", "method": "GET", "path": "/onedrive/callback", "allow": True},
        ],
        "administrativo": [
            {"label": "configuracoes_get", "method": "GET", "path": "/admin/configuracoes", "allow": False},
            {
                "label": "configuracoes_post",
                "method": "POST",
                "path": "/admin/configuracoes/tempo-resposta",
                "allow": False,
                "kwargs": {"data": {"response_goal_days": "10", "response_metrics_reset_at": ""}},
            },
            {"label": "mensagens_get", "method": "GET", "path": "/admin/mensagens", "allow": False},
            {
                "label": "mensagens_post",
                "method": "POST",
                "path": "/admin/mensagens/salvar",
                "allow": False,
                "kwargs": {"data": {"message_key": "login_success", "message_text": "Mensagem RBAC"}},
            },
            {"label": "presets_get", "method": "GET", "path": "/admin/api/presets", "allow": True},
            {
                "label": "presets_post",
                "method": "POST",
                "path": "/admin/api/presets",
                "allow": True,
                "kwargs": {"data": json.dumps({"respostas": [], "emails": []}), "content_type": "application/json"},
            },
            {"label": "alerta_toggle", "method": "POST", "path": f"/admin/alertas/{alerta_toggle_id}/alternar", "allow": True},
            {"label": "banco_retencao", "method": "POST", "path": "/admin/banco-dados/retencao", "allow": False, "kwargs": {"data": {}}},
            {
                "label": "banco_drive_settings",
                "method": "POST",
                "path": "/admin/banco-dados/drive-settings",
                "allow": False,
                "kwargs": {"data": {"provider": "google", "gdrive_dest_folder": "Backups/sistema", "gdrive_enabled": "1"}},
            },
            {
                "label": "banco_oauth_start",
                "method": "GET",
                "path": "/admin/banco-dados/oauth/start?provider=google",
                "allow": False,
            },
            {"label": "cloud_folder_get", "method": "GET", "path": "/admin/backup/cloud-folder/google", "allow": False},
            {"label": "auth_callback", "method": "GET", "path": "/auth/callback", "allow": False},
            {"label": "google_callback", "method": "GET", "path": "/google/callback", "allow": False},
            {"label": "onedrive_callback", "method": "GET", "path": "/onedrive/callback", "allow": False},
        ],
        "consultivo": [
            {"label": "configuracoes_get", "method": "GET", "path": "/admin/configuracoes", "allow": False},
            {
                "label": "configuracoes_post",
                "method": "POST",
                "path": "/admin/configuracoes/tempo-resposta",
                "allow": False,
                "kwargs": {"data": {"response_goal_days": "10", "response_metrics_reset_at": ""}},
            },
            {"label": "mensagens_get", "method": "GET", "path": "/admin/mensagens", "allow": False},
            {
                "label": "mensagens_post",
                "method": "POST",
                "path": "/admin/mensagens/salvar",
                "allow": False,
                "kwargs": {"data": {"message_key": "login_success", "message_text": "Mensagem RBAC"}},
            },
            {"label": "presets_get", "method": "GET", "path": "/admin/api/presets", "allow": True},
            {
                "label": "presets_post",
                "method": "POST",
                "path": "/admin/api/presets",
                "allow": False,
                "kwargs": {"data": json.dumps({"respostas": [], "emails": []}), "content_type": "application/json"},
            },
            {"label": "alerta_toggle", "method": "POST", "path": f"/admin/alertas/{alerta_toggle_id}/alternar", "allow": False},
            {"label": "alerta_delete", "method": "POST", "path": f"/admin/alertas/{alerta_toggle_id}/deletar", "allow": False},
            {"label": "banco_retencao", "method": "POST", "path": "/admin/banco-dados/retencao", "allow": False, "kwargs": {"data": {}}},
            {
                "label": "banco_drive_settings",
                "method": "POST",
                "path": "/admin/banco-dados/drive-settings",
                "allow": False,
                "kwargs": {"data": {"provider": "google", "gdrive_dest_folder": "Backups/sistema", "gdrive_enabled": "1"}},
            },
            {
                "label": "banco_oauth_start",
                "method": "GET",
                "path": "/admin/banco-dados/oauth/start?provider=google",
                "allow": False,
            },
            {"label": "cloud_folder_get", "method": "GET", "path": "/admin/backup/cloud-folder/google", "allow": False},
            {"label": "auth_callback", "method": "GET", "path": "/auth/callback", "allow": False},
            {"label": "google_callback", "method": "GET", "path": "/google/callback", "allow": False},
            {"label": "onedrive_callback", "method": "GET", "path": "/onedrive/callback", "allow": False},
        ],
        "arquivos_none": [
            {"label": "admin_arquivos_get", "method": "GET", "path": "/admin/arquivos", "allow": False},
            {"label": "uploads_direct", "method": "GET", "path": f"/uploads/{upload_relpath}", "allow": False},
        ],
    }

    user_map = {
        "admin_total": (admin_total_id, "RBAC Admin Total"),
        "administrativo": (administrativo_id, "RBAC Administrativo"),
        "consultivo": (consultivo_id, "RBAC Consultivo"),
        "arquivos_none": (arquivos_none_id, "RBAC Arquivos None"),
    }

    for profile_name, checks in endpoint_specs.items():
        user_id, user_name = user_map[profile_name]
        _login_as_admin(client, user_id, user_name)
        for spec in checks:
            kwargs = dict(spec.get("kwargs") or {})
            response = _make_request(client, spec["method"], spec["path"], **kwargs)
            _record_access_check(results, profile_name, spec["label"], response, bool(spec["allow"]))

    _login_as_admin(client, consultivo_id, "RBAC Consultivo")

    dashboard_response = client.get("/admin/dashboard", follow_redirects=False)
    if dashboard_response.status_code == 200:
        html = dashboard_response.get_data(as_text=True)
        sidebar_ok = _contains_none(html, ["/admin/configuracoes", "/admin/mensagens"])
        _record_ui_check(
            results,
            "consultivo",
            "ui_sidebar_config_mensagens_hidden",
            sidebar_ok,
            "links hidden" if sidebar_ok else "links visible",
        )
    else:
        _record_ui_check(results, "consultivo", "ui_sidebar_config_mensagens_hidden", False, "dashboard not accessible")

    ui_specs = [
        {
            "label": "ui_alertas_write_hidden",
            "path": "/admin/alertas",
            "must_not": ["id=\"btn-alerta-adicionar\"", "id=\"admin-alerta-save\""],
            "must_have": ["id=\"alertas-action-delete\" hidden disabled"],
        },
        {
            "label": "ui_arquivos_write_hidden",
            "path": "/admin/arquivos",
            "must_not": ["id=\"btn-admin-arquivos-adicionar\"", "form=\"admin-arquivo-form\""],
            "must_have": ["id=\"arquivos-action-delete\" hidden disabled"],
        },
        {
            "label": "ui_reportes_write_hidden",
            "path": "/admin/reportes",
            "must_not": ["Salvar status"],
            "must_have": ["reporte-modal-status-block\" hidden"],
        },
        {
            "label": "ui_requisicoes_write_hidden",
            "path": "/admin/requisicoes",
            "must_not": ["href=\"/admin/requisicoes/nova\""],
            "must_have": [
                "id=\"req-action-edit\"",
                "id=\"req-action-process\"",
                "id=\"req-action-delete\"",
                "const canRequisicoesEdit = false;",
                "const canRequisicoesFull = false;",
            ],
        },
    ]

    for ui_spec in ui_specs:
        response = client.get(ui_spec["path"], follow_redirects=False)
        if response.status_code != 200:
            _record_ui_check(results, "consultivo", ui_spec["label"], False, f"status {response.status_code}")
            continue
        html = response.get_data(as_text=True)
        has_required = _contains_all(html, ui_spec["must_have"])
        has_no_forbidden = _contains_none(html, ui_spec["must_not"])
        ok = has_required and has_no_forbidden
        detail = "ok" if ok else "missing expected hide guards"
        _record_ui_check(results, "consultivo", ui_spec["label"], ok, detail)

    failures = [
        {
            "profile": item.profile,
            "check": item.check,
            "status": item.status,
            "location": item.location,
            "detail": item.detail,
        }
        for item in results
        if not item.ok
    ]

    summary = {
        "ok": not failures,
        "total_checks": len(results),
        "passed": len(results) - len(failures),
        "failed": len(failures),
        "failures": failures,
    }

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("RBAC CORRIGIDO." if not failures else "RBAC AINDA COM INCONSISTENCIAS.")

    shutil.rmtree(temp_root, ignore_errors=True)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(run())
