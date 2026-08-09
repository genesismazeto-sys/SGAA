import io
import json
import logging
import os
import shutil
import sys
import zipfile

import pytest


BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main


def _login_as_user(client, user_id, user_name, user_type="admin"):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["user_type"] = user_type
        sess["user_name"] = user_name


@pytest.fixture
def admin_client(tmp_path):
    original_testing = main.app.config.get("TESTING")
    original_local_backup_dir = main.app.config.get("LOCAL_BACKUP_DIR")
    original_cloud_backup_dir = main.app.config.get("CLOUD_BACKUP_DIR")
    original_cloud_sync_interval = main.app.config.get("CLOUD_SYNC_INTERVAL_SECONDS")
    original_documents_folder = main.app.config.get("DOCUMENTOS_ALUNOS_FOLDER")
    original_backup_settings = None

    main.app.config["TESTING"] = True
    main.app.config["LOCAL_BACKUP_DIR"] = str(tmp_path / "local")
    main.app.config["CLOUD_BACKUP_DIR"] = str(tmp_path / "cloud")
    main.app.config["CLOUD_SYNC_INTERVAL_SECONDS"] = 0
    main.app.config["DOCUMENTOS_ALUNOS_FOLDER"] = str(tmp_path / "documentos_alunos")
    os.makedirs(main.app.config["DOCUMENTOS_ALUNOS_FOLDER"], exist_ok=True)

    with main.app.app_context():
        main.init_db()
        conn = main.get_db_connection()
        original_backup_settings = main.get_backup_settings(conn)
        main.save_backup_settings(
            conn,
            {
                "local_backup_dir": main.app.config["LOCAL_BACKUP_DIR"],
                "cloud_backup_dir": main.app.config["CLOUD_BACKUP_DIR"],
                "cloud_sync_interval_seconds": str(main.app.config["CLOUD_SYNC_INTERVAL_SECONDS"]),
                "external_backup_url": original_backup_settings.get("external_backup_url") or "",
                "external_backup_token": original_backup_settings.get("external_backup_token") or "",
                "external_backup_enabled": original_backup_settings.get("external_backup_enabled") or "0",
            },
        )
        conn.commit()

    client = main.app.test_client()
    login_response = client.post(
        "/login",
        data={"email": "admin@ej.edu.br", "senha": "admin123"},
        follow_redirects=False,
    )
    assert login_response.status_code in (302, 303)
    try:
        yield client
    finally:
        with main.app.app_context():
            if original_backup_settings is not None:
                conn = main.get_db_connection()
                main.save_backup_settings(conn, original_backup_settings)
                conn.commit()
        main.app.config["TESTING"] = original_testing
        main.app.config["LOCAL_BACKUP_DIR"] = original_local_backup_dir
        main.app.config["CLOUD_BACKUP_DIR"] = original_cloud_backup_dir
        main.app.config["CLOUD_SYNC_INTERVAL_SECONDS"] = original_cloud_sync_interval
        main.app.config["DOCUMENTOS_ALUNOS_FOLDER"] = original_documents_folder


def test_manual_backup_creates_local_and_cloud_snapshots(admin_client):
    response = admin_client.post("/admin/banco-dados/backup", follow_redirects=True)

    local_snapshots = os.listdir(os.path.join(main.app.config["LOCAL_BACKUP_DIR"], "snapshots"))
    cloud_snapshots = os.listdir(os.path.join(main.app.config["CLOUD_BACKUP_DIR"], "snapshots"))

    assert response.status_code == 200
    assert any(name.endswith(".db") for name in local_snapshots)
    assert any(name.endswith(".json") for name in local_snapshots)
    assert any(name.endswith(".db") for name in cloud_snapshots)
    assert any(name.endswith(".json") for name in cloud_snapshots)


def test_backup_settings_can_be_updated_and_page_exposes_recovery_ui(admin_client, tmp_path):
    local_dir = str(tmp_path / "destino-local")
    cloud_dir = str(tmp_path / "destino-nuvem")
    response = admin_client.post(
        "/admin/banco-dados/configuracoes",
        data={
            "local_backup_dir": local_dir,
            "cloud_backup_dir": cloud_dir,
            "cloud_sync_interval_seconds": "15",
            "external_backup_url": "https://example.com/api/backups",
            "external_backup_token": "token-teste",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Recuperar banco de dados" in html
    assert "Carregar arquivo" in html
    assert 'id="restore-upload-form"' in html
    assert local_dir in html
    assert cloud_dir in html

    with main.app.app_context():
        conn = main.get_db_connection()
        persisted_rows = conn.execute(
            "SELECT chave, valor FROM configuracoes_backup WHERE chave IN ('local_backup_dir', 'cloud_backup_dir', 'cloud_sync_interval_seconds')"
        ).fetchall()
        persisted = {row["chave"]: row["valor"] for row in persisted_rows}

    assert persisted["local_backup_dir"] == local_dir
    assert persisted["cloud_backup_dir"] == cloud_dir
    assert persisted["cloud_sync_interval_seconds"] == "15"


def test_snapshot_can_be_downloaded_and_deleted(admin_client):
    backup_response = admin_client.post("/admin/banco-dados/backup", follow_redirects=True)
    assert backup_response.status_code == 200

    local_snapshot_dir = os.path.join(main.app.config["LOCAL_BACKUP_DIR"], "snapshots")
    manifests = sorted(
        [os.path.join(local_snapshot_dir, name) for name in os.listdir(local_snapshot_dir) if name.endswith(".json")]
    )
    selected_manifest = manifests[-1]

    download_response = admin_client.get(
        "/admin/banco-dados/download",
        query_string={"manifest_path": selected_manifest},
        follow_redirects=False,
    )
    assert download_response.status_code == 200
    assert "attachment;" in (download_response.headers.get("Content-Disposition") or "")
    download_response.close()

    with open(selected_manifest, "r", encoding="utf-8") as handle:
        manifest_payload = json.load(handle)
    snapshot_db_path = manifest_payload["database_path"]

    delete_response = admin_client.post(
        "/admin/banco-dados/excluir",
        data={"manifest_path": selected_manifest},
        follow_redirects=True,
    )
    assert delete_response.status_code == 200
    assert not os.path.exists(selected_manifest)
    assert not os.path.exists(snapshot_db_path)


def test_restore_restores_basic_database_state(admin_client):
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "INSERT INTO atividades (grupo, nome) VALUES (?, ?)",
            ("99 - Backup", "Atividade Backup"),
        )
        conn.commit()

    backup_response = admin_client.post("/admin/banco-dados/backup", follow_redirects=True)
    assert backup_response.status_code == 200

    local_snapshot_dir = os.path.join(main.app.config["LOCAL_BACKUP_DIR"], "snapshots")
    manifests = sorted(
        [os.path.join(local_snapshot_dir, name) for name in os.listdir(local_snapshot_dir) if name.endswith(".json")]
    )
    selected_manifest = manifests[-1]

    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("DELETE FROM atividades WHERE nome = ?", ("Atividade Backup",))
        conn.commit()

    restore_response = admin_client.post(
        "/admin/banco-dados/restaurar",
        data={"manifest_path": selected_manifest},
        follow_redirects=True,
    )

    with main.app.app_context():
        restored = main.get_db_connection().execute(
            "SELECT 1 FROM atividades WHERE nome = ?",
            ("Atividade Backup",),
        ).fetchone()

    assert restore_response.status_code == 200
    assert restored is not None


def test_restore_upload_restores_basic_database_state_from_official_zip(admin_client):
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "INSERT INTO atividades (grupo, nome) VALUES (?, ?)",
            ("98 - Backup", "Atividade Backup ZIP"),
        )
        conn.commit()

    backup_artifacts = main.create_sqlite_backup_zip(main.DATABASE)
    try:
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute("DELETE FROM atividades WHERE nome = ?", ("Atividade Backup ZIP",))
            conn.commit()

        with open(str(backup_artifacts["zip_path"]), "rb") as handle:
            restore_response = admin_client.post(
                "/admin/banco-dados/restaurar/upload",
                data={"backup_file": (handle, str(backup_artifacts["file_name"]))},
                content_type="multipart/form-data",
                follow_redirects=True,
            )

        with main.app.app_context():
            restored = main.get_db_connection().execute(
                "SELECT 1 FROM atividades WHERE nome = ?",
                ("Atividade Backup ZIP",),
            ).fetchone()

        assert restore_response.status_code == 200
        assert restored is not None
    finally:
        main.cleanup_backup_artifacts(backup_artifacts)


@pytest.mark.parametrize("suffix", [".db", ".sqlite", ".sqlite3"])
def test_restore_upload_accepts_direct_sqlite_files_and_creates_safety_snapshot(admin_client, tmp_path, suffix, caplog):
    marker_name = f"Atividade Backup Direto {suffix}"

    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "INSERT INTO atividades (grupo, nome) VALUES (?, ?)",
            ("97 - Backup", marker_name),
        )
        conn.commit()

    direct_copy = tmp_path / f"restore-direto{suffix}"
    shutil.copy2(main.DATABASE, direct_copy)

    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("DELETE FROM atividades WHERE nome = ?", (marker_name,))
        conn.commit()

    caplog.clear()
    with caplog.at_level(logging.INFO):
        with open(str(direct_copy), "rb") as handle:
            restore_response = admin_client.post(
                "/admin/banco-dados/restaurar/upload",
                data={"backup_file": (handle, direct_copy.name)},
                content_type="multipart/form-data",
                follow_redirects=True,
            )

    with main.app.app_context():
        restored = main.get_db_connection().execute(
            "SELECT 1 FROM atividades WHERE nome = ?",
            (marker_name,),
        ).fetchone()

    assert restore_response.status_code == 200
    assert restored is not None
    assert any(
        "Snapshot de banco criado em" in record.getMessage() for record in caplog.records
    ), "Restore por upload deve criar snapshot automático pre-restore"


def test_restore_upload_rejects_zip_with_path_traversal(admin_client, tmp_path):
    malicious_zip = tmp_path / "malicious-backup.zip"
    with zipfile.ZipFile(malicious_zip, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("../fora.db", b"SQLite format 3\x00malicious")

    with open(str(malicious_zip), "rb") as handle:
        response = admin_client.post(
            "/admin/banco-dados/restaurar/upload",
            data={"backup_file": (handle, malicious_zip.name)},
            content_type="multipart/form-data",
            follow_redirects=True,
        )

    assert response.status_code == 200
    assert "caminho inseguro" in response.get_data(as_text=True).lower()


def test_database_module_requires_explicit_permission_for_consultivo_admin(tmp_path, monkeypatch):
    monkeypatch.setitem(main.app.config, "TESTING", True)
    main.app.config["LOCAL_BACKUP_DIR"] = str(tmp_path / "local")
    main.app.config["CLOUD_BACKUP_DIR"] = str(tmp_path / "cloud")
    main.app.config["CLOUD_SYNC_INTERVAL_SECONDS"] = 0

    with main.app.app_context():
        main.init_db()
        conn = main.get_db_connection()
        main.ensure_usuario_access_schema(conn)
        conn.execute(
            "DELETE FROM usuarios WHERE email = ?",
            ("consultivo.banco@ej.edu.br",),
        )
        cursor = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?)",
            (
                "Consultivo Banco",
                "consultivo.banco@ej.edu.br",
                main.hash_password("consultivo123"),
                "admin",
                "consultivo",
            ),
        )
        usuario_id = cursor.lastrowid
        conn.commit()

    client = main.app.test_client()
    _login_as_user(client, usuario_id, "Consultivo Banco")

    denied_response = client.get("/admin/banco-dados", follow_redirects=False)

    assert denied_response.status_code in (302, 303)
    assert denied_response.headers["Location"].endswith("/admin/dashboard")

    denied_restore_upload = client.post(
        "/admin/banco-dados/restaurar/upload",
        data={"backup_file": (io.BytesIO(b"nao-importa"), "restore.db")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert denied_restore_upload.status_code in (302, 303)
    assert denied_restore_upload.headers["Location"].endswith("/admin/dashboard")

    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "INSERT INTO usuarios_permissoes_acesso (usuario_id, recurso, escopo) VALUES (?, ?, ?)",
            (usuario_id, "banco_dados", "view"),
        )
        conn.commit()

    allowed_response = client.get("/admin/banco-dados", follow_redirects=False)

    assert allowed_response.status_code == 200
    assert "Banco de dados" in allowed_response.get_data(as_text=True)
    assert 'restore-upload-form' not in allowed_response.get_data(as_text=True)