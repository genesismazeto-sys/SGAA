import datetime
import hashlib
import json
import os
import secrets
import sqlite3
import sys
from pathlib import Path

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from app import db as app_db_module
from tests.conftest import PYTEST_RUNTIME_ROOT
import main


def _dir_inventory(directory):
    if not directory.is_dir():
        return {}
    inventory = {}
    for fpath in sorted(directory.rglob("*")):
        if fpath.is_file():
            rel = str(fpath.relative_to(directory))
            data = fpath.read_bytes()
            inventory[rel] = {
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
    return inventory


@pytest.fixture()
def smoke_env(monkeypatch):
    sub_root = Path(str(PYTEST_RUNTIME_ROOT)).resolve() / secrets.token_hex(8)
    sub_root.mkdir(parents=True, exist_ok=True)
    sub_root.resolve().relative_to(PYTEST_RUNTIME_ROOT.resolve())

    temp_database = sub_root / "test.db"
    temp_uploads = sub_root / "uploads"
    temp_documents = sub_root / "documentos_alunos"
    temp_local_backup = sub_root / "backups" / "local"
    temp_cloud_backup = sub_root / "backups" / "cloud"
    temp_logs = sub_root / "logs"

    for p in [temp_uploads, temp_documents, temp_local_backup, temp_cloud_backup, temp_logs]:
        p.mkdir(parents=True, exist_ok=True)

    orig_database = main.DATABASE
    orig_app_db = app_db_module.DATABASE
    orig_cfg_db_path = main.app.config.get("DATABASE_PATH")
    orig_cfg_upload = main.app.config.get("UPLOAD_FOLDER")
    orig_cfg_documents = main.app.config.get("DOCUMENTOS_ALUNOS_FOLDER")
    orig_cfg_local_backup = main.app.config.get("LOCAL_BACKUP_DIR")
    orig_cfg_cloud_backup = main.app.config.get("CLOUD_BACKUP_DIR")
    orig_cfg_bootstrap = main.app.config.get("BOOTSTRAP_DEFAULT_ADMIN")
    orig_cfg_testing = main.app.config.get("TESTING")

    monkeypatch.setenv("APP_DATABASE", str(temp_database))
    monkeypatch.setenv("APP_UPLOAD_FOLDER", str(temp_uploads))
    monkeypatch.setenv("APP_DOCUMENTOS_ALUNOS_FOLDER", str(temp_documents))
    monkeypatch.setenv("APP_LOCAL_BACKUP_DIR", str(temp_local_backup))
    monkeypatch.setenv("APP_CLOUD_BACKUP_DIR", str(temp_cloud_backup))
    monkeypatch.setenv("APP_LOG_DIR", str(temp_logs))
    monkeypatch.setenv("APP_BOOTSTRAP_DEFAULT_ADMIN", "0")

    monkeypatch.setattr(main, "DATABASE", str(temp_database))
    monkeypatch.setattr(app_db_module, "DATABASE", str(temp_database))

    main.app.config["DATABASE_PATH"] = str(temp_database)
    main.app.config["UPLOAD_FOLDER"] = str(temp_uploads)
    main.app.config["DOCUMENTOS_ALUNOS_FOLDER"] = str(temp_documents)
    main.app.config["LOCAL_BACKUP_DIR"] = str(temp_local_backup)
    main.app.config["CLOUD_BACKUP_DIR"] = str(temp_cloud_backup)
    main.app.config["BOOTSTRAP_DEFAULT_ADMIN"] = False
    main.app.config["TESTING"] = True

    with main.app.app_context():
        main.close_db_connection(None)
        main.init_db()

    with main.app.app_context():
        conn = main.get_db_connection()
        admin_pass = main.hash_password("admin123")
        conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?)",
            ("Admin Total", "admin_total@ej.edu.br", admin_pass, "admin", "admin_total"),
        )
        conn.commit()
        admin_id = conn.execute(
            "SELECT id FROM usuarios WHERE email = ?", ("admin_total@ej.edu.br",)
        ).fetchone()["id"]

    client = main.app.test_client()

    try:
        yield client, sub_root, admin_id
    finally:
        with main.app.app_context():
            main.close_db_connection(None)

        main.app.config["DATABASE_PATH"] = orig_cfg_db_path
        main.app.config["UPLOAD_FOLDER"] = orig_cfg_upload
        main.app.config["DOCUMENTOS_ALUNOS_FOLDER"] = orig_cfg_documents
        main.app.config["LOCAL_BACKUP_DIR"] = orig_cfg_local_backup
        main.app.config["CLOUD_BACKUP_DIR"] = orig_cfg_cloud_backup
        main.app.config["BOOTSTRAP_DEFAULT_ADMIN"] = orig_cfg_bootstrap
        main.app.config["TESTING"] = orig_cfg_testing
        main.DATABASE = orig_database
        app_db_module.DATABASE = orig_app_db


def test_admin_login_flow(smoke_env):
    client, sub_root, admin_id = smoke_env

    resp = client.get("/login")
    assert resp.status_code == 200

    resp = client.post(
        "/login",
        data={"email": "admin_total@ej.edu.br", "senha": "admin123"},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)
    assert resp.headers.get("Location") == "/admin/dashboard"

    resp = client.get("/admin/dashboard", follow_redirects=False)
    assert resp.status_code == 200


def test_aluno_login_flow(smoke_env):
    client, sub_root, admin_id = smoke_env
    suffix = secrets.token_hex(8)
    aluno_email = f"aluno.{suffix}@teste.local"
    aluno_pass = "aluno123"

    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "INSERT INTO cursos (nome, codigo, duracao_periodos, status) VALUES (?, ?, ?, ?)",
            ("Curso Teste", f"CT{suffix}", 8, "ativo"),
        )
        curso = conn.execute("SELECT id, codigo FROM cursos ORDER BY id DESC LIMIT 1").fetchone()
        curso_id = curso["id"]
        curso_codigo = curso["codigo"]

        conn.execute(
            "INSERT INTO turmas (nome, ano, semestre, turno, status, numero, curso_id, codigo) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("Turma Teste", 2026, 1, "Manha", "Ativa", 1, curso_id, f"{curso_codigo}-1"),
        )
        turma = conn.execute("SELECT id FROM turmas ORDER BY id DESC LIMIT 1").fetchone()
        turma_id = turma["id"]

        hashed = main.hash_password(aluno_pass)
        conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?)",
            ("Aluno Teste", aluno_email, hashed, "aluno", "usuario"),
        )
        usuario = conn.execute("SELECT id FROM usuarios ORDER BY id DESC LIMIT 1").fetchone()

        conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status) VALUES (?, ?, ?, ?, ?, ?)",
            (usuario["id"], "Aluno Teste", f"MAT.{suffix}", aluno_email, turma_id, "Ativo"),
        )
        conn.commit()

    resp = client.post(
        "/login",
        data={"email": aluno_email, "senha": aluno_pass},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)
    assert resp.headers.get("Location") == "/aluno/dashboard"

    resp = client.get("/aluno/dashboard", follow_redirects=False)
    assert resp.status_code == 200


def test_criacao_requisicao_sem_anexo(smoke_env):
    client, sub_root, admin_id = smoke_env
    upload_dir = sub_root / "uploads"
    documents_dir = sub_root / "documentos_alunos"
    suffix = secrets.token_hex(8)
    aluno_email = f"aluno.req.{suffix}@teste.local"
    aluno_pass = "aluno123"

    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "INSERT INTO cursos (nome, codigo, duracao_periodos, status) VALUES (?, ?, ?, ?)",
            ("Curso Req", f"REQ{suffix}", 8, "ativo"),
        )
        curso = conn.execute("SELECT id, codigo FROM cursos ORDER BY id DESC LIMIT 1").fetchone()
        curso_id = curso["id"]
        curso_codigo = curso["codigo"]

        conn.execute(
            "INSERT INTO turmas (nome, ano, semestre, turno, status, numero, curso_id, codigo) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("Turma Req", 2026, 1, "Manha", "Ativa", 1, curso_id, f"{curso_codigo}-1"),
        )
        turma = conn.execute("SELECT id FROM turmas ORDER BY id DESC LIMIT 1").fetchone()

        conn.execute(
            "INSERT INTO atividades (grupo, nome, descricao, limite_horas, tipo_atividade, tem_limitacao) VALUES (?, ?, ?, ?, ?, ?)",
            ("1 - Grupo Teste", f"Atividade Teste {suffix}", "Descricao", 60, "Acadêmica Complementar", 0),
        )
        atividade = conn.execute("SELECT id FROM atividades ORDER BY id DESC LIMIT 1").fetchone()
        atividade_id = atividade["id"]

        hashed = main.hash_password(aluno_pass)
        conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?)",
            ("Aluno Req", aluno_email, hashed, "aluno", "usuario"),
        )
        usuario = conn.execute("SELECT id FROM usuarios ORDER BY id DESC LIMIT 1").fetchone()

        conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status) VALUES (?, ?, ?, ?, ?, ?)",
            (usuario["id"], "Aluno Req", f"REQ.{suffix}", aluno_email, turma["id"], "Ativo"),
        )
        aluno = conn.execute("SELECT id FROM alunos ORDER BY id DESC LIMIT 1").fetchone()
        aluno_id = aluno["id"]
        conn.commit()

        pre_count = conn.execute("SELECT COUNT(*) FROM requisicoes").fetchone()[0]

    pre_upload_inv = _dir_inventory(upload_dir)
    pre_docs_inv = _dir_inventory(documents_dir)

    resp = client.post(
        "/login",
        data={"email": aluno_email, "senha": aluno_pass},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)

    resp = client.post(
        "/aluno/nova-requisicao",
        data={
            "atividade_id": str(atividade_id),
            "nome_evento": "Evento Teste Sem Anexo",
            "data_evento": "2026-07-15",
            "horas_solicitadas": "8",
            "observacao": "Criada pelo teste",
        },
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)

    post_upload_inv = _dir_inventory(upload_dir)
    post_docs_inv = _dir_inventory(documents_dir)
    assert pre_upload_inv == post_upload_inv
    assert pre_docs_inv == post_docs_inv
    assert pre_upload_inv == {}
    assert pre_docs_inv == {}

    with main.app.app_context():
        conn = main.get_db_connection()
        post_count = conn.execute("SELECT COUNT(*) FROM requisicoes").fetchone()[0]
        assert post_count - pre_count == 1

        req = conn.execute(
            "SELECT * FROM requisicoes ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert req is not None
        assert req["aluno_id"] == aluno_id
        assert req["atividade_id"] == atividade_id
        assert req["status"] == "Pendente"
        assert float(req["horas_solicitadas"]) == 8.0
        assert req["nome_evento"] == "Evento Teste Sem Anexo"
        assert req["data_evento"] == "2026-07-15"
        assert req["observacao"] == "Criada pelo teste"
        assert req["arquivo_comprovante"] is None
        assert req["admin_id"] is None
        assert req["horas_deferidas"] is None
        assert req["data_processamento"] is None
        assert req["aluno_update_notified_at"] is None
        assert req["aluno_update_seen_at"] is None

        anexos_count = conn.execute(
            "SELECT COUNT(*) FROM requisicao_arquivos WHERE requisicao_id = ?", (req["id"],)
        ).fetchone()[0]
        assert anexos_count == 0


def test_processamento_requisicao_pendente(smoke_env):
    client, sub_root, admin_id = smoke_env

    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "INSERT INTO cursos (nome, codigo, duracao_periodos, status) VALUES (?, ?, ?, ?)",
            ("Curso Proc", f"PRC{secrets.token_hex(4)}", 8, "ativo"),
        )
        curso = conn.execute("SELECT id, codigo FROM cursos ORDER BY id DESC LIMIT 1").fetchone()
        curso_id = curso["id"]
        curso_codigo = curso["codigo"]

        conn.execute(
            "INSERT INTO turmas (nome, ano, semestre, turno, status, numero, curso_id, codigo) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("Turma Proc", 2026, 1, "Manha", "Ativa", 1, curso_id, f"{curso_codigo}-1"),
        )
        turma = conn.execute("SELECT id FROM turmas ORDER BY id DESC LIMIT 1").fetchone()

        conn.execute(
            "INSERT INTO atividades (grupo, nome, descricao, limite_horas, tipo_atividade, tem_limitacao) VALUES (?, ?, ?, ?, ?, ?)",
            ("1 - Grupo Proc", f"Atividade Proc {secrets.token_hex(4)}", "Desc", 60, "Acadêmica Complementar", 0),
        )
        atividade = conn.execute("SELECT id FROM atividades ORDER BY id DESC LIMIT 1").fetchone()

        aluno_pass = main.hash_password("aluno123")
        conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?)",
            ("Aluno Proc", f"aluno.proc.{secrets.token_hex(4)}@teste.local", aluno_pass, "aluno", "usuario"),
        )
        usuario = conn.execute("SELECT id FROM usuarios ORDER BY id DESC LIMIT 1").fetchone()

        conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status) VALUES (?, ?, ?, ?, ?, ?)",
            (usuario["id"], "Aluno Proc", f"PRC.{secrets.token_hex(4)}", f"aluno.proc.{secrets.token_hex(4)}@teste.local", turma["id"], "Ativo"),
        )
        aluno = conn.execute("SELECT id FROM alunos ORDER BY id DESC LIMIT 1").fetchone()

        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "INSERT INTO requisicoes (aluno_id, atividade_id, data_solicitacao, data_evento, horas_solicitadas, nome_evento, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (aluno["id"], atividade["id"], now, "2026-08-01", 10, "Evento Processar", "Pendente"),
        )
        req = conn.execute("SELECT id FROM requisicoes ORDER BY id DESC LIMIT 1").fetchone()
        req_id = req["id"]
        conn.commit()

    resp = client.post(
        "/login",
        data={"email": "admin_total@ej.edu.br", "senha": "admin123"},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)

    resp = client.post(
        f"/admin/processar_requisicao/{req_id}",
        data={
            "status": "Deferida Parcialmente",
            "horas_deferidas": "6",
            "observacao": "Processado no teste",
        },
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        req = conn.execute("SELECT * FROM requisicoes WHERE id = ?", (req_id,)).fetchone()
    assert req is not None
    assert req["status"] == "Deferida Parcialmente"
    assert float(req["horas_deferidas"]) == 6.0
    assert req["observacao"] == "Processado no teste"
    assert req["admin_id"] == admin_id
    assert req["data_processamento"] is not None
    assert req["aluno_update_notified_at"] is not None
    assert req["aluno_update_notified_at"] == req["data_processamento"]
    assert req["aluno_update_seen_at"] is None


def test_backup_local(smoke_env, monkeypatch):
    client, sub_root, admin_id = smoke_env
    local_backup_dir = sub_root / "backups" / "local"
    cloud_backup_dir = sub_root / "backups" / "cloud"

    resp = client.post(
        "/login",
        data={"email": "admin_total@ej.edu.br", "senha": "admin123"},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)

    marker_name = f"Backup Marker {secrets.token_hex(8)}"
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "INSERT INTO atividades (grupo, nome) VALUES (?, ?)",
            ("99 - Teste", marker_name),
        )
        conn.commit()
        marker_row = conn.execute(
            "SELECT id FROM atividades WHERE nome = ?", (marker_name,)
        ).fetchone()
        assert marker_row is not None
        marker_id = marker_row["id"]

        conn.execute("DELETE FROM configuracoes_backup")
        main.save_backup_settings(conn, {
            "local_backup_dir": str(local_backup_dir),
            "cloud_backup_dir": "",
            "external_backup_enabled": "0",
        })
        main.app.config["CLOUD_BACKUP_DIR"] = ""
        conn.execute(
            "INSERT OR REPLACE INTO configuracoes_backup (chave, valor) VALUES (?, ?)",
            ("gdrive_enabled", "0"),
        )
        conn.execute(
            "INSERT OR REPLACE INTO configuracoes_backup (chave, valor) VALUES (?, ?)",
            ("onedrive_enabled", "0"),
        )
        conn.commit()

    call_log = []

    def _spy_maybe_sync(*args, **kwargs):
        call_log.append(("maybe_sync_database_to_cloud", args, kwargs))
        return {"ok": True, "skipped": True, "reason": "spy"}

    def _spy_upload_external(*args, **kwargs):
        call_log.append(("upload_snapshot_to_external_server", args, kwargs))
        return {"ok": False, "skipped": True, "reason": "spy"}

    def _spy_refresh_google(*args, **kwargs):
        call_log.append(("refresh_google_if_needed", args, kwargs))
        return ({}, {})

    def _spy_refresh_onedrive(*args, **kwargs):
        call_log.append(("refresh_onedrive_if_needed", args, kwargs))
        return ({}, {})

    def _spy_google_upload(*args, **kwargs):
        call_log.append(("google_upload", args, kwargs))
        return None

    def _spy_onedrive_upload(*args, **kwargs):
        call_log.append(("onedrive_upload", args, kwargs))
        return None

    def _spy_apply_retention(*args, **kwargs):
        call_log.append(("apply_retention_to_drive", args, kwargs))
        return {"deleted": [], "errors": []}

    # UT-5 RED retarget: maybe_sync_database_to_cloud / upload_snapshot_to_external_server
    # move behind app.backup.orchestrator; patching the stale main aliases would
    # silently stop intercepting these calls once the route delegates to the new
    # owner. Import inside the test body so app.backup absence is a clean,
    # test-local RED (ModuleNotFoundError) rather than a collection failure for
    # the whole file. The app.cloud_drives MODULE-object monkeypatches below are
    # left as-is: they still intercept the same module object regardless of who
    # calls into it (main today, app.backup.orchestrator after UT-5).
    from app.backup import orchestrator as backup_orchestrator

    monkeypatch.setattr(backup_orchestrator, "maybe_sync_database_to_cloud", _spy_maybe_sync)
    monkeypatch.setattr(backup_orchestrator, "upload_snapshot_to_external_server", _spy_upload_external)
    monkeypatch.setattr(main._cd, "refresh_google_if_needed", _spy_refresh_google)
    monkeypatch.setattr(main._cd, "refresh_onedrive_if_needed", _spy_refresh_onedrive)
    monkeypatch.setattr(main._cd, "google_upload", _spy_google_upload)
    monkeypatch.setattr(main._cd, "onedrive_upload", _spy_onedrive_upload)
    monkeypatch.setattr(main._cd, "apply_retention_to_drive", _spy_apply_retention)

    resp = client.post("/admin/banco-dados/backup", follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert resp.headers.get("Location") == "/admin/banco-dados"

    snapshots_dir = local_backup_dir / "snapshots"
    assert snapshots_dir.is_dir()

    db_files = sorted(snapshots_dir.glob("*.db"))
    json_files = sorted(snapshots_dir.glob("*.json"))
    assert len(db_files) == 1, f"Expected 1 .db file, got {len(db_files)}"
    assert len(json_files) == 1, f"Expected 1 .json file, got {len(json_files)}"

    with open(str(json_files[0]), "r", encoding="utf-8") as f:
        manifest = json.load(f)

    Path(str(json_files[0])).resolve().relative_to(local_backup_dir.resolve())
    Path(str(json_files[0])).resolve().relative_to(sub_root.resolve())

    snapshot_db_path = manifest["database_path"]
    Path(snapshot_db_path).resolve().relative_to(local_backup_dir.resolve())
    Path(snapshot_db_path).resolve().relative_to(sub_root.resolve())

    assert os.path.exists(snapshot_db_path)

    snap_conn = sqlite3.connect(snapshot_db_path)
    try:
        snap_conn.row_factory = sqlite3.Row
        marker = snap_conn.execute(
            "SELECT id, nome FROM atividades WHERE id = ?", (marker_id,)
        ).fetchone()
        assert marker is not None
        assert marker["id"] == marker_id
        assert marker["nome"] == marker_name
    finally:
        snap_conn.close()

    assert call_log == [], f"Network calls were made: {call_log}"
