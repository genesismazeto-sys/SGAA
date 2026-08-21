import os
import sys
from pathlib import Path

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from app import db as app_db_module
import main


ADMIN_PAGES = [
    "/admin/dashboard",
    "/admin/alunos",
    "/admin/cursos",
    "/admin/turmas",
    "/admin/atividades",
    "/admin/requisicoes",
    "/admin/arquivos",
    "/admin/banco-dados",
    "/admin/acesso",
]


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


def _table_exists(conn, table_name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _table_columns(conn, table_name: str) -> set[str]:
    return {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }


def test_release_clean_database_installation_and_idempotence(tmp_path):
    app = main.app
    project_root = Path(BASE).resolve()
    tmp_root = (tmp_path / "release_clean_install").resolve()
    tmp_root.mkdir(parents=True, exist_ok=True)

    temp_database = (tmp_root / "release_clean_database.db").resolve()
    temp_uploads = (tmp_root / "uploads").resolve()
    temp_local_backups = (tmp_root / "backups_local").resolve()
    temp_cloud_backups = (tmp_root / "backups_cloud").resolve()
    temp_uploads.mkdir(parents=True, exist_ok=True)
    temp_local_backups.mkdir(parents=True, exist_ok=True)
    temp_cloud_backups.mkdir(parents=True, exist_ok=True)

    original_database = main.DATABASE
    original_env_database = os.environ.get("APP_DATABASE")
    original_config_database_path = app.config.get("DATABASE_PATH")
    original_upload_folder = app.config.get("UPLOAD_FOLDER")
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
        app.config["LOCAL_BACKUP_DIR"] = str(temp_local_backups)
        app.config["CLOUD_BACKUP_DIR"] = str(temp_cloud_backups)
        app.config["EXTERNAL_BACKUP_ENABLED"] = False
        app.config["BOOTSTRAP_DEFAULT_ADMIN"] = True
        app.config["BOOTSTRAP_ADMIN_EMAIL"] = "admin@ej.edu.br"
        app.config["BOOTSTRAP_ADMIN_PASSWORD"] = "admin123"
        app.config["TESTING"] = True

        # Travas obrigatórias: qualquer desvio fora de tmp_path falha antes do init_db.
        effective_paths = {
            "APP_DATABASE": os.environ.get("APP_DATABASE"),
            "main.DATABASE": main.DATABASE,
            "app_db_module.DATABASE": app_db_module.DATABASE,
            "DATABASE_PATH": app.config.get("DATABASE_PATH"),
        }
        guard_errors: list[str] = []
        for label, raw_value in effective_paths.items():
            if not raw_value:
                guard_errors.append(f"{label} não definido")
                continue
            resolved = Path(str(raw_value)).resolve()
            if not _path_is_within(resolved, tmp_root):
                guard_errors.append(
                    f"{label} fora de tmp_path: {resolved} (tmp_path={tmp_root})"
                )
            if resolved != temp_database:
                guard_errors.append(
                    f"{label} não aponta para o banco temporário esperado: {resolved} != {temp_database}"
                )
        assert not guard_errors, "Trava de segurança falhou antes do init_db: " + " | ".join(guard_errors)

        assert not temp_database.exists(), (
            "Banco temporário deve iniciar inexistente para simular instalação limpa. "
            f"Caminho: {temp_database}"
        )

        with app.app_context():
            try:
                main.close_db_connection(None)
            except Exception:
                pass

            main.init_db()
            assert temp_database.exists(), f"init_db não criou o banco esperado: {temp_database}"

            conn = main.get_db_connection()
            tables = {
                row["name"]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }

            required_tables = {
                "usuarios",
                "alunos",
                "cursos",
                "turmas",
                "atividade_base",
                "atividade_versao",
                "norma_atividade",
                "matriz_atividade_versao_item",
                "requisicoes",
                "requisicao_arquivos",
                "configuracoes_acesso",
                "usuarios_permissoes_acesso",
                "configuracoes_app",
                "configuracoes_backup",
                "cloud_accounts",
                "backup_logs",
                "cloud_drive_settings",
            }
            missing_tables = sorted(required_tables - tables)
            assert not missing_tables, f"Tabelas essenciais ausentes no banco limpo: {missing_tables}"

            usuarios_columns = _table_columns(conn, "usuarios")
            assert {
                "id",
                "nome",
                "email",
                "senha",
                "tipo",
                "nivel_acesso",
                "foto_perfil",
            }.issubset(usuarios_columns), f"Colunas essenciais ausentes em usuarios: {usuarios_columns}"

            alunos_columns = _table_columns(conn, "alunos")
            assert "foto_perfil" in alunos_columns, "Coluna crítica ausente: alunos.foto_perfil"
            assert {
                "usuario_id",
                "nome",
                "matricula",
                "email",
                "turma_id",
                "status",
            }.issubset(alunos_columns), f"Colunas essenciais ausentes em alunos: {alunos_columns}"

            acesso_columns = _table_columns(conn, "usuarios_permissoes_acesso")
            assert {
                "usuario_id",
                "recurso",
                "escopo",
            }.issubset(acesso_columns), (
                "Campos essenciais de acesso ausentes em usuarios_permissoes_acesso"
            )

            requisicoes_columns = _table_columns(conn, "requisicoes")
            assert {
                "aluno_id",
                "atividade_versao_id",
                "data_solicitacao",
                "data_evento",
                "horas_solicitadas",
                "status",
                "nome_evento",
                "regra_snapshot_json",
                "codigo_normativo_snapshot",
                "data_processamento",
                "admin_id",
            }.issubset(requisicoes_columns), (
                f"Colunas essenciais ausentes em requisicoes: {requisicoes_columns}"
            )

            req_files_columns = _table_columns(conn, "requisicao_arquivos")
            assert {
                "requisicao_id",
                "label",
                "filename",
                "criado_em",
            }.issubset(req_files_columns), (
                f"Colunas essenciais ausentes em requisicao_arquivos: {req_files_columns}"
            )

            main.ensure_admin_arquivos_table(conn)
            conn.commit()
            assert _table_exists(conn, "admin_arquivos"), "Tabela admin_arquivos não foi criada no banco limpo"
            admin_arquivos_columns = _table_columns(conn, "admin_arquivos")
            assert {
                "id",
                "titulo",
                "filename",
                "visivel",
                "criado_em",
            }.issubset(admin_arquivos_columns), (
                f"Colunas essenciais ausentes em admin_arquivos: {admin_arquivos_columns}"
            )

            admin_row = conn.execute(
                "SELECT id, email, tipo, nivel_acesso FROM usuarios WHERE LOWER(email)=?",
                ("admin@ej.edu.br",),
            ).fetchone()
            assert admin_row is not None, "Admin inicial não foi criado em banco limpo"
            assert admin_row["tipo"] == "admin"
            assert admin_row["nivel_acesso"] == "admin_total"

            admin_count_before = conn.execute(
                "SELECT COUNT(*) FROM usuarios WHERE LOWER(email)=?",
                ("admin@ej.edu.br",),
            ).fetchone()[0]
            geral_count_before = conn.execute(
                "SELECT COUNT(*) FROM cursos WHERE codigo='GERAL'",
            ).fetchone()[0]
            access_rows_before = conn.execute(
                "SELECT COUNT(*) FROM configuracoes_acesso",
            ).fetchone()[0]

        client = app.test_client()
        login_response = client.post(
            "/login",
            data={"email": "admin@ej.edu.br", "senha": "admin123"},
            follow_redirects=False,
        )
        assert login_response.status_code in (302, 303), (
            f"Falha no login com admin inicial. status={login_response.status_code}"
        )
        redirect_target = login_response.headers.get("Location") or ""
        assert "/login" not in redirect_target, (
            f"Login não autenticou admin inicial. redirect={redirect_target}"
        )
        with client.session_transaction() as sess:
            assert sess.get("user_type") == "admin"
            assert sess.get("user_id") is not None

        for route_path in ADMIN_PAGES:
            response = client.get(route_path, follow_redirects=False)
            assert response.status_code == 200, (
                f"Página admin não abriu corretamente em instalação limpa: {route_path} status={response.status_code}"
            )

        with app.app_context():
            # Segunda execução do init_db: deve ser idempotente e sem duplicações críticas.
            try:
                main.close_db_connection(None)
            except Exception:
                pass
            main.init_db()

            conn2 = main.get_db_connection()
            admin_count_after = conn2.execute(
                "SELECT COUNT(*) FROM usuarios WHERE LOWER(email)=?",
                ("admin@ej.edu.br",),
            ).fetchone()[0]
            geral_count_after = conn2.execute(
                "SELECT COUNT(*) FROM cursos WHERE codigo='GERAL'",
            ).fetchone()[0]
            access_rows_after = conn2.execute(
                "SELECT COUNT(*) FROM configuracoes_acesso",
            ).fetchone()[0]

        assert admin_count_before == 1
        assert admin_count_after == 1
        assert geral_count_before == 1
        assert geral_count_after == 1
        assert access_rows_after == access_rows_before

        after_fingerprints = _collect_db_fingerprints(project_root, tmp_root)
        _assert_no_external_db_changes(before_fingerprints, after_fingerprints)

        # Confirmações explícitas exigidas para auditoria de segurança do teste.
        assert _path_is_within(temp_database, tmp_root), (
            f"Banco temporário fora de tmp_path: {temp_database}"
        )
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
