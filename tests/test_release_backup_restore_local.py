import os
import sys
import uuid
from pathlib import Path

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from app import db as app_db_module
from app.student_documents import build_student_documents_rel_dir
import main


def _path_is_within(path_value: Path, root: Path) -> bool:
    try:
        path_value.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _collect_db_fingerprints(project_root: Path, allowed_tmp_root: Path) -> dict[str, tuple[int, int]]:
    fingerprints: dict[str, tuple[int, int]] = {}
    for db_file in project_root.rglob("*.db"):
        resolved = db_file.resolve()
        if _path_is_within(resolved, allowed_tmp_root):
            continue
        stat = resolved.stat()
        fingerprints[str(resolved)] = (int(stat.st_size), int(stat.st_mtime_ns))
    return fingerprints


def _assert_no_external_db_changes(
    before: dict[str, tuple[int, int]],
    after: dict[str, tuple[int, int]],
) -> None:
    created = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    modified = sorted(path for path in set(before).intersection(after) if before[path] != after[path])
    assert not created and not removed and not modified, (
        "Nenhum .db fora de tmp_path pode ser alterado. "
        f"created={created[:5]} removed={removed[:5]} modified={modified[:5]}"
    )


def _assert_paths_guard(tmp_root: Path, mapping: dict[str, object]) -> dict[str, Path]:
    resolved: dict[str, Path] = {}
    errors: list[str] = []
    for label, raw in mapping.items():
        value = str(raw or "").strip()
        if not value:
            errors.append(f"{label} não definido")
            continue
        path_obj = Path(value).resolve()
        resolved[label] = path_obj
        if not _path_is_within(path_obj, tmp_root):
            errors.append(f"{label} fora de tmp_path: {path_obj} (tmp_path={tmp_root})")

    assert not errors, "Trava de segurança falhou: " + " | ".join(errors)
    return resolved


def _seed_restore_dataset(documents_root: Path) -> dict[str, object]:
    suffix = uuid.uuid4().hex[:8]
    curso_codigo = f"BKP-{suffix}"
    turma_codigo = f"{curso_codigo}-T01"
    aluno_email = f"backup.restore.aluno.{suffix}@teste.local"
    atividade_nome = f"Atividade Backup Restore {suffix}"
    requisicao_evento = f"Evento Backup Restore {suffix}"

    with main.app.app_context():
        conn = main.get_db_connection()

        conn.execute(
            "INSERT INTO cursos (nome, codigo, duracao_periodos, status) VALUES (?, ?, ?, ?)",
            ("Curso Backup Restore", curso_codigo, 8, "ativo"),
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
            ("Turma Backup Restore", 2026, 1, "Manha", "Ativa", 1, curso_id, turma_codigo),
        )
        turma_id = conn.execute(
            "SELECT id FROM turmas WHERE codigo = ?",
            (turma_codigo,),
        ).fetchone()["id"]

        conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?)",
            (
                "Aluno Backup Restore",
                aluno_email,
                main.hash_password("aluno123"),
                "aluno",
                "usuario",
            ),
        )
        aluno_usuario_id = conn.execute(
            "SELECT id FROM usuarios WHERE email = ?",
            (aluno_email,),
        ).fetchone()["id"]

        conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status) VALUES (?, ?, ?, ?, ?, ?)",
            (
                aluno_usuario_id,
                "Aluno Backup Restore",
                f"{turma_codigo}.001",
                aluno_email,
                turma_id,
                "Ativo",
            ),
        )
        aluno_id = conn.execute(
            "SELECT id FROM alunos WHERE usuario_id = ?",
            (aluno_usuario_id,),
        ).fetchone()["id"]

        conn.execute(
            "INSERT INTO atividades (grupo, nome, descricao, limite_horas, tem_limitacao) VALUES (?, ?, ?, ?, ?)",
            ("1 - Grupo Backup", atividade_nome, "Teste backup restore", 40, 0),
        )
        atividade_id = conn.execute(
            "SELECT id FROM atividades WHERE nome = ?",
            (atividade_nome,),
        ).fetchone()["id"]

        conn.execute(
            """
            INSERT INTO requisicoes (
                aluno_id, atividade_id, data_solicitacao, data_evento,
                horas_solicitadas, nome_evento, status, observacao, arquivo_comprovante
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                aluno_id,
                atividade_id,
                "2026-05-01 10:00:00",
                "2026-04-30",
                12.0,
                requisicao_evento,
                "Pendente",
                "Criada para teste de backup/restore",
                None,
            ),
        )
        requisicao_id = conn.execute(
            "SELECT id FROM requisicoes WHERE nome_evento = ?",
            (requisicao_evento,),
        ).fetchone()["id"]

        rel_dir = build_student_documents_rel_dir(aluno_id, "Aluno Backup Restore", "requisicoes")
        rel_anexo = f"{rel_dir}/req{requisicao_id}-comprovante-backup.pdf"
        abs_anexo = (documents_root / rel_anexo).resolve()
        abs_anexo.parent.mkdir(parents=True, exist_ok=True)
        abs_anexo.write_bytes(b"%PDF-1.4\nbackup-restore-test\n")

        conn.execute(
            "INSERT INTO requisicao_arquivos (requisicao_id, label, filename) VALUES (?, ?, ?)",
            (requisicao_id, "Comprovante", rel_anexo),
        )
        conn.execute(
            "UPDATE requisicoes SET arquivo_comprovante = ? WHERE id = ?",
            (rel_anexo, requisicao_id),
        )
        conn.commit()

    return {
        "curso_codigo": curso_codigo,
        "turma_codigo": turma_codigo,
        "aluno_email": aluno_email,
        "atividade_nome": atividade_nome,
        "requisicao_evento": requisicao_evento,
        "anexo_relpath": rel_anexo,
        "anexo_abspath": abs_anexo,
    }


def test_release_backup_restore_local_isolated(tmp_path):
    app = main.app
    project_root = Path(BASE).resolve()

    tmp_root = (tmp_path / "release_backup_restore_local").resolve()
    tmp_root.mkdir(parents=True, exist_ok=True)

    temp_database = (tmp_root / "release_backup_restore_local.db").resolve()
    temp_uploads = (tmp_root / "uploads").resolve()
    temp_documents = (tmp_root / "documentos_alunos").resolve()
    temp_local_backups = (tmp_root / "backups_local").resolve()
    temp_cloud_backups = (tmp_root / "backups_cloud").resolve()
    temp_uploads.mkdir(parents=True, exist_ok=True)
    temp_documents.mkdir(parents=True, exist_ok=True)
    temp_local_backups.mkdir(parents=True, exist_ok=True)
    temp_cloud_backups.mkdir(parents=True, exist_ok=True)

    original_database = main.DATABASE
    original_env_database = os.environ.get("APP_DATABASE")
    original_config_database_path = app.config.get("DATABASE_PATH")
    original_upload_folder = app.config.get("UPLOAD_FOLDER")
    original_documents_folder = app.config.get("DOCUMENTOS_ALUNOS_FOLDER")
    original_local_backup_dir = app.config.get("LOCAL_BACKUP_DIR")
    original_cloud_backup_dir = app.config.get("CLOUD_BACKUP_DIR")
    original_external_backup_enabled = app.config.get("EXTERNAL_BACKUP_ENABLED")
    original_bootstrap_default_admin = app.config.get("BOOTSTRAP_DEFAULT_ADMIN")
    original_bootstrap_admin_email = app.config.get("BOOTSTRAP_ADMIN_EMAIL")
    original_bootstrap_admin_password = app.config.get("BOOTSTRAP_ADMIN_PASSWORD")
    original_testing = app.config.get("TESTING")

    before_fingerprints = _collect_db_fingerprints(project_root, tmp_root)

    try:
        os.environ["APP_DATABASE"] = str(temp_database)
        main.DATABASE = str(temp_database)
        app_db_module.DATABASE = str(temp_database)
        app.config["DATABASE_PATH"] = str(temp_database)
        app.config["UPLOAD_FOLDER"] = str(temp_uploads)
        app.config["DOCUMENTOS_ALUNOS_FOLDER"] = str(temp_documents)
        app.config["LOCAL_BACKUP_DIR"] = str(temp_local_backups)
        app.config["CLOUD_BACKUP_DIR"] = str(temp_cloud_backups)
        app.config["EXTERNAL_BACKUP_ENABLED"] = False
        app.config["BOOTSTRAP_DEFAULT_ADMIN"] = True
        app.config["BOOTSTRAP_ADMIN_EMAIL"] = "admin@ej.edu.br"
        app.config["BOOTSTRAP_ADMIN_PASSWORD"] = "admin123"
        app.config["TESTING"] = True

        # Trava inicial: banco efetivo precisa apontar para tmp_path e para o arquivo esperado.
        db_guard = _assert_paths_guard(
            tmp_root,
            {
                "APP_DATABASE": os.environ.get("APP_DATABASE"),
                "main.DATABASE": main.DATABASE,
                "app_db_module.DATABASE": app_db_module.DATABASE,
                "DATABASE_PATH": app.config.get("DATABASE_PATH"),
            },
        )
        for label, path_value in db_guard.items():
            assert path_value == temp_database, (
                f"{label} não aponta para o banco temporário esperado: {path_value} != {temp_database}"
            )

        # Trava inicial: uploads e diretórios de backup também devem ficar dentro de tmp_path.
        _assert_paths_guard(
            tmp_root,
            {
                "UPLOAD_FOLDER": app.config.get("UPLOAD_FOLDER"),
                "DOCUMENTOS_ALUNOS_FOLDER": app.config.get("DOCUMENTOS_ALUNOS_FOLDER"),
                "LOCAL_BACKUP_DIR": app.config.get("LOCAL_BACKUP_DIR"),
                "CLOUD_BACKUP_DIR": app.config.get("CLOUD_BACKUP_DIR"),
            },
        )

        with app.app_context():
            try:
                main.close_db_connection(None)
            except Exception:
                pass
            main.init_db()

        assert temp_database.exists(), f"Banco temporário não criado por init_db: {temp_database}"

        client = app.test_client()
        login_response = client.post(
            "/login",
            data={"email": "admin@ej.edu.br", "senha": "admin123"},
            follow_redirects=False,
        )
        assert login_response.status_code in (302, 303)
        login_target = login_response.headers.get("Location") or ""
        assert "/login" not in login_target, f"Login admin falhou: redirect={login_target}"

        # Usa a rota real para persistir a configuração de backup local no runtime/DB.
        save_settings_response = client.post(
            "/admin/banco-dados/configuracoes",
            data={
                "local_backup_dir": str(temp_local_backups),
                "cloud_backup_dir": str(temp_cloud_backups),
                "cloud_sync_interval_seconds": "0",
                "external_backup_url": "",
                "external_backup_token": "",
                "external_backup_enabled": "0",
            },
            follow_redirects=False,
        )
        assert save_settings_response.status_code in (302, 303)

        with app.app_context():
            conn = main.get_db_connection()
            persisted_settings = main.get_backup_settings(conn)
            effective_guard = _assert_paths_guard(
                tmp_root,
                {
                    "DATABASE_PATH": app.config.get("DATABASE_PATH"),
                    "UPLOAD_FOLDER": app.config.get("UPLOAD_FOLDER"),
                    "DOCUMENTOS_ALUNOS_FOLDER": app.config.get("DOCUMENTOS_ALUNOS_FOLDER"),
                    "LOCAL_BACKUP_DIR(app)": app.config.get("LOCAL_BACKUP_DIR"),
                    "CLOUD_BACKUP_DIR(app)": app.config.get("CLOUD_BACKUP_DIR"),
                    "local_backup_dir(db)": persisted_settings.get("local_backup_dir"),
                    "cloud_backup_dir(db)": persisted_settings.get("cloud_backup_dir"),
                },
            )
            assert effective_guard["local_backup_dir(db)"] == temp_local_backups
            assert effective_guard["cloud_backup_dir(db)"] == temp_cloud_backups

        sentinel_document = (
            temp_documents / "aluno_999 - documento-legado" / "perfil" / "foto-manter.txt"
        ).resolve()
        sentinel_document.parent.mkdir(parents=True, exist_ok=True)
        sentinel_document.write_text("nao apagar", encoding="utf-8")

        seeded = _seed_restore_dataset(temp_documents)

        local_snapshot_dir = (temp_local_backups / "snapshots").resolve()
        local_snapshot_dir.mkdir(parents=True, exist_ok=True)
        manifests_before = {
            p.resolve()
            for p in local_snapshot_dir.glob("*.json")
        }

        # Travas obrigatórias imediatamente antes do backup/restauração.
        _assert_paths_guard(
            tmp_root,
            {
                "DATABASE_PATH": app.config.get("DATABASE_PATH"),
                "UPLOAD_FOLDER": app.config.get("UPLOAD_FOLDER"),
                "DOCUMENTOS_ALUNOS_FOLDER": app.config.get("DOCUMENTOS_ALUNOS_FOLDER"),
                "LOCAL_BACKUP_DIR": app.config.get("LOCAL_BACKUP_DIR"),
            },
        )

        backup_response = client.post("/admin/banco-dados/backup", follow_redirects=False)
        assert backup_response.status_code in (302, 303)

        manifests_after = {
            p.resolve()
            for p in local_snapshot_dir.glob("*.json")
        }
        new_manifests = sorted(manifests_after - manifests_before, key=lambda p: p.stat().st_mtime_ns)
        assert new_manifests, "Nenhum manifesto de backup local foi criado"

        selected_manifest = new_manifests[-1]
        assert _path_is_within(selected_manifest, tmp_root), (
            f"Manifesto de backup fora de tmp_path: {selected_manifest}"
        )

        with selected_manifest.open("r", encoding="utf-8") as handle:
            import json

            manifest_payload = json.load(handle)

        snapshot_db_path = Path(str(manifest_payload.get("database_path") or "")).resolve()
        assert snapshot_db_path.exists(), f"Arquivo de backup não encontrado: {snapshot_db_path}"
        assert _path_is_within(snapshot_db_path, tmp_root), (
            f"Arquivo de backup fora de tmp_path: {snapshot_db_path}"
        )

        # Simula perda de dados no banco temporário para validar restauração real.
        with app.app_context():
            conn = main.get_db_connection()
            conn.execute(
                "DELETE FROM requisicao_arquivos WHERE requisicao_id IN (SELECT id FROM requisicoes WHERE nome_evento = ?)",
                (seeded["requisicao_evento"],),
            )
            conn.execute("DELETE FROM requisicoes WHERE nome_evento = ?", (seeded["requisicao_evento"],))
            conn.execute("DELETE FROM atividades WHERE nome = ?", (seeded["atividade_nome"],))
            conn.execute("DELETE FROM alunos WHERE email = ?", (seeded["aluno_email"],))
            conn.execute("DELETE FROM usuarios WHERE email = ?", (seeded["aluno_email"],))
            conn.execute("DELETE FROM turmas WHERE codigo = ?", (seeded["turma_codigo"],))
            conn.execute("DELETE FROM cursos WHERE codigo = ?", (seeded["curso_codigo"],))
            conn.commit()

            vanished_course = conn.execute(
                "SELECT 1 FROM cursos WHERE codigo = ?",
                (seeded["curso_codigo"],),
            ).fetchone()
            vanished_req = conn.execute(
                "SELECT 1 FROM requisicoes WHERE nome_evento = ?",
                (seeded["requisicao_evento"],),
            ).fetchone()
            assert vanished_course is None and vanished_req is None

        # Revalida travas antes da restauração; em caso de falha, a rota não será chamada.
        _assert_paths_guard(
            tmp_root,
            {
                "DATABASE_PATH": app.config.get("DATABASE_PATH"),
                "UPLOAD_FOLDER": app.config.get("UPLOAD_FOLDER"),
                "DOCUMENTOS_ALUNOS_FOLDER": app.config.get("DOCUMENTOS_ALUNOS_FOLDER"),
                "LOCAL_BACKUP_DIR": app.config.get("LOCAL_BACKUP_DIR"),
            },
        )

        restore_response = client.post(
            "/admin/banco-dados/restaurar",
            data={"manifest_path": str(selected_manifest)},
            follow_redirects=False,
        )
        assert restore_response.status_code in (302, 303)

        with app.app_context():
            conn = main.get_db_connection()
            restored_course = conn.execute(
                "SELECT id, codigo FROM cursos WHERE codigo = ?",
                (seeded["curso_codigo"],),
            ).fetchone()
            restored_turma = conn.execute(
                "SELECT id, codigo, curso_id FROM turmas WHERE codigo = ?",
                (seeded["turma_codigo"],),
            ).fetchone()
            restored_aluno = conn.execute(
                "SELECT id, email, turma_id FROM alunos WHERE email = ?",
                (seeded["aluno_email"],),
            ).fetchone()
            restored_atividade = conn.execute(
                "SELECT id, nome FROM atividades WHERE nome = ?",
                (seeded["atividade_nome"],),
            ).fetchone()
            restored_requisicao = conn.execute(
                "SELECT id, nome_evento, status, arquivo_comprovante FROM requisicoes WHERE nome_evento = ?",
                (seeded["requisicao_evento"],),
            ).fetchone()

            assert restored_course is not None
            assert restored_turma is not None
            assert restored_aluno is not None
            assert restored_atividade is not None
            assert restored_requisicao is not None
            assert restored_turma["curso_id"] == restored_course["id"]
            assert restored_aluno["turma_id"] == restored_turma["id"]
            assert restored_requisicao["status"] == "Pendente"

            restored_file = conn.execute(
                "SELECT filename FROM requisicao_arquivos WHERE requisicao_id = ? ORDER BY id LIMIT 1",
                (restored_requisicao["id"],),
            ).fetchone()
            assert restored_file is not None
            restored_relpath = restored_file["filename"]

        expected_attachment = (temp_documents / str(restored_relpath)).resolve()
        assert expected_attachment.exists()
        assert _path_is_within(expected_attachment, tmp_root)
        assert sentinel_document.exists(), "Restauração não pode remover documentos_alunos existentes"

        for route_path in ("/admin/dashboard", "/admin/banco-dados", "/admin/requisicoes"):
            page_response = client.get(route_path, follow_redirects=False)
            assert page_response.status_code == 200, (
                f"Página pós-restauração indisponível: {route_path} status={page_response.status_code}"
            )

        after_fingerprints = _collect_db_fingerprints(project_root, tmp_root)
        _assert_no_external_db_changes(before_fingerprints, after_fingerprints)

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

        if original_upload_folder is None:
            app.config.pop("UPLOAD_FOLDER", None)
        else:
            app.config["UPLOAD_FOLDER"] = original_upload_folder

        if original_documents_folder is None:
            app.config.pop("DOCUMENTOS_ALUNOS_FOLDER", None)
        else:
            app.config["DOCUMENTOS_ALUNOS_FOLDER"] = original_documents_folder

        if original_local_backup_dir is None:
            app.config.pop("LOCAL_BACKUP_DIR", None)
        else:
            app.config["LOCAL_BACKUP_DIR"] = original_local_backup_dir

        if original_cloud_backup_dir is None:
            app.config.pop("CLOUD_BACKUP_DIR", None)
        else:
            app.config["CLOUD_BACKUP_DIR"] = original_cloud_backup_dir

        app.config["EXTERNAL_BACKUP_ENABLED"] = original_external_backup_enabled
        app.config["BOOTSTRAP_DEFAULT_ADMIN"] = original_bootstrap_default_admin
        app.config["BOOTSTRAP_ADMIN_EMAIL"] = original_bootstrap_admin_email
        app.config["BOOTSTRAP_ADMIN_PASSWORD"] = original_bootstrap_admin_password
        app.config["TESTING"] = original_testing

        if original_env_database is None:
            os.environ.pop("APP_DATABASE", None)
        else:
            os.environ["APP_DATABASE"] = original_env_database
