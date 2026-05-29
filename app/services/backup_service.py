import datetime
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile

from app.db_maintenance import SCHEMA_VERSION, get_schema_status


class BackupServiceError(RuntimeError):
    pass


RESTORE_SQLITE_EXTENSIONS = {".db", ".sqlite", ".sqlite3"}
RESTORE_PACKAGE_EXTENSIONS = RESTORE_SQLITE_EXTENSIONS | {".zip"}
ESSENTIAL_RESTORE_TABLES = {"usuarios", "alunos", "atividades", "requisicoes"}


def _calculate_file_sha256(file_path: str) -> str:
    digest = hashlib.sha256()
    with open(file_path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_created_zip(zip_path: str, *, expected_member: str, source_file_path: str) -> dict[str, object]:
    if not zip_path or not os.path.exists(zip_path):
        raise BackupServiceError("Arquivo ZIP de backup não foi gerado.")
    if os.path.getsize(zip_path) <= 0:
        raise BackupServiceError("Arquivo ZIP de backup foi gerado vazio.")
    if not zipfile.is_zipfile(zip_path):
        raise BackupServiceError("Arquivo gerado não é um ZIP válido.")

    try:
        with zipfile.ZipFile(zip_path, mode="r") as archive:
            members = archive.namelist()
            if members != [expected_member]:
                raise BackupServiceError(
                    "ZIP de backup inválido: conteúdo inesperado no arquivo gerado."
                )
            bad_member = archive.testzip()
            if bad_member:
                raise BackupServiceError(
                    f"ZIP de backup corrompido: falha de CRC em {bad_member}."
                )
            info = archive.getinfo(expected_member)
    except KeyError as exc:
        raise BackupServiceError(
            "ZIP de backup inválido: arquivo SQLite não encontrado dentro do ZIP."
        ) from exc
    except (OSError, zipfile.BadZipFile) as exc:
        raise BackupServiceError(f"Falha ao validar integridade do ZIP: {exc}") from exc

    source_size = os.path.getsize(source_file_path)
    if info.file_size != source_size:
        raise BackupServiceError(
            "ZIP de backup inválido: o tamanho do banco no arquivo compactado não confere."
        )

    return {
        "archive_member": expected_member,
        "db_file_size": source_size,
        "zip_sha256": _calculate_file_sha256(zip_path),
    }


def create_sqlite_backup_zip(source_db_path: str) -> dict[str, object]:
    """Create a consistent SQLite backup, compress it, and validate the ZIP."""
    if not source_db_path or not os.path.exists(source_db_path):
        raise BackupServiceError("Banco SQLite não encontrado para gerar backup.")

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    work_dir = tempfile.mkdtemp(prefix="sgaa-backup-")
    db_name = f"sgaa_{timestamp}.db"
    db_copy_path = os.path.join(work_dir, db_name)

    source_conn = sqlite3.connect(source_db_path)
    target_conn = sqlite3.connect(db_copy_path)
    try:
        source_conn.backup(target_conn)
        target_conn.commit()
    except sqlite3.Error as exc:
        raise BackupServiceError(f"Falha ao criar cópia consistente do banco: {exc}") from exc
    finally:
        target_conn.close()
        source_conn.close()

    zip_name = f"backup_sgaa_{timestamp}.zip"
    zip_path = os.path.join(work_dir, zip_name)
    try:
        with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(db_copy_path, arcname=db_name)
    except OSError as exc:
        raise BackupServiceError(f"Falha ao compactar backup em ZIP: {exc}") from exc

    zip_validation = _validate_created_zip(
        zip_path,
        expected_member=db_name,
        source_file_path=db_copy_path,
    )

    return {
        "zip_path": zip_path,
        "file_name": zip_name,
        "file_size": os.path.getsize(zip_path),
        "work_dir": work_dir,
        **zip_validation,
    }


def _normalize_restore_member_name(member_name: str) -> str:
    normalized = os.path.normpath(str(member_name or "")).replace("\\", "/").lstrip("/")
    parts = normalized.split("/")
    if normalized in {"", ".", ".."} or any(part in {"", ".", ".."} for part in parts):
        raise BackupServiceError("ZIP de backup inválido: caminho inseguro detectado no pacote.")
    return normalized


def _validate_optional_restore_manifest(payload) -> dict[str, object] | None:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise BackupServiceError("Manifesto do pacote de backup inválido.")
    return payload


def _validate_restore_database_file(database_path: str) -> dict[str, object]:
    if not database_path or not os.path.exists(database_path):
        raise BackupServiceError("Arquivo SQLite do backup não foi encontrado.")

    with open(database_path, "rb") as handle:
        header = handle.read(16)
    if header != b"SQLite format 3\x00":
        raise BackupServiceError("Arquivo enviado não é um banco SQLite válido.")

    try:
        conn = sqlite3.connect(database_path)
    except sqlite3.Error as exc:
        raise BackupServiceError(f"Não foi possível abrir o banco SQLite enviado: {exc}") from exc

    try:
        tables = {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        missing_tables = sorted(ESSENTIAL_RESTORE_TABLES - tables)
        if missing_tables:
            raise BackupServiceError(
                "Backup do banco inválido: tabelas essenciais ausentes: "
                + ", ".join(missing_tables)
                + "."
            )

        schema_status = get_schema_status(conn)
        schema_version = int(schema_status.get("schema_version") or 0)
        if schema_version > SCHEMA_VERSION:
            raise BackupServiceError(
                "Backup do banco usa um schema mais novo do que esta versão do sistema suporta."
            )
    except sqlite3.Error as exc:
        raise BackupServiceError(f"Não foi possível validar o schema do banco enviado: {exc}") from exc
    finally:
        conn.close()

    return {
        "database_path": database_path,
        "schema_status": schema_status,
        "schema_version": int(schema_status.get("schema_version") or 0),
    }


def extract_restore_database_artifact(
    source_path: str,
    *,
    work_dir: str | None = None,
) -> dict[str, object]:
    if not source_path or not os.path.exists(source_path):
        raise BackupServiceError("Arquivo enviado para restauração não foi encontrado.")

    safe_work_dir = work_dir or tempfile.mkdtemp(prefix="sgaa-restore-upload-")
    os.makedirs(safe_work_dir, exist_ok=True)

    source_ext = os.path.splitext(source_path)[1].lower()
    if source_ext not in RESTORE_PACKAGE_EXTENSIONS:
        raise BackupServiceError(
            "Formato de arquivo não suportado para restauração. Use ZIP, .db, .sqlite ou .sqlite3."
        )

    if source_ext in RESTORE_SQLITE_EXTENSIONS:
        validation = _validate_restore_database_file(source_path)
        return {
            "work_dir": safe_work_dir,
            "database_path": validation["database_path"],
            "schema_status": validation["schema_status"],
            "schema_version": validation["schema_version"],
            "source_kind": "sqlite",
            "manifest": None,
        }

    if not zipfile.is_zipfile(source_path):
        raise BackupServiceError("Arquivo ZIP de backup inválido.")

    manifest_payload = None
    with zipfile.ZipFile(source_path, mode="r") as archive:
        members = [info for info in archive.infolist() if not info.is_dir()]
        if not members:
            raise BackupServiceError("ZIP de backup inválido: pacote vazio.")

        sqlite_members: list[tuple[zipfile.ZipInfo, str]] = []
        manifest_members: list[tuple[zipfile.ZipInfo, str]] = []
        for info in members:
            safe_name = _normalize_restore_member_name(info.filename)
            ext = os.path.splitext(safe_name)[1].lower()
            if ext in RESTORE_SQLITE_EXTENSIONS:
                sqlite_members.append((info, safe_name))
            elif ext == ".json":
                manifest_members.append((info, safe_name))
            else:
                raise BackupServiceError(
                    "ZIP de backup inválido: pacote deve conter apenas o banco SQLite e um manifesto opcional."
                )

        if len(sqlite_members) != 1:
            raise BackupServiceError(
                "ZIP de backup inválido: o pacote deve conter exatamente um banco SQLite."
            )
        if len(manifest_members) > 1:
            raise BackupServiceError(
                "ZIP de backup inválido: o pacote deve conter no máximo um manifesto JSON."
            )

        sqlite_info, sqlite_name = sqlite_members[0]
        database_path = os.path.join(safe_work_dir, os.path.basename(sqlite_name))
        with archive.open(sqlite_info, mode="r") as source_handle, open(database_path, "wb") as target_handle:
            shutil.copyfileobj(source_handle, target_handle)

        if manifest_members:
            manifest_info, _manifest_name = manifest_members[0]
            with archive.open(manifest_info, mode="r") as manifest_handle:
                try:
                    manifest_payload = json.load(manifest_handle)
                except json.JSONDecodeError as exc:
                    raise BackupServiceError("Manifesto do pacote de backup inválido.") from exc
            manifest_payload = _validate_optional_restore_manifest(manifest_payload)

    validation = _validate_restore_database_file(database_path)
    return {
        "work_dir": safe_work_dir,
        "database_path": validation["database_path"],
        "schema_status": validation["schema_status"],
        "schema_version": validation["schema_version"],
        "source_kind": "zip",
        "manifest": manifest_payload,
    }


def cleanup_backup_artifacts(artifacts: dict[str, object] | None) -> None:
    if not artifacts:
        return
    work_dir = str(artifacts.get("work_dir") or "").strip()
    if work_dir and os.path.isdir(work_dir):
        shutil.rmtree(work_dir, ignore_errors=True)
