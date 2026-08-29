import datetime
import json
import os
import secrets
import shutil
import sqlite3
import tempfile
import threading
import time
from pathlib import Path
from urllib import error as urllib_error
from urllib import request as urllib_request

from app.academics import (
    DEFAULT_CURSO_TOTAL_HORAS_AAC,
    DEFAULT_CURSO_TOTAL_HORAS_AEU,
)
from app.auth import DEFAULT_ACCESS_PASSWORDS, default_access_level_for_user_type
from app.prod1_schema import (
    BASELINE_MARKER,
    LATEST_MIGRATION_MARKER,
    NORMA_REMOVAL_MARKER,
    SCHEMA_EPOCH,
    SCHEMA_VERSION,
    Prod1SchemaError,
    bootstrap_prod1_schema,
    get_prod1_schema_status,
)


SchemaMigrationStateError = Prod1SchemaError


def ensure_backup_settings_structural_schema(conn) -> None:
    """Validate central prod-1 ownership of backup settings."""
    _require_prod1_tables(conn, "configuracoes_backup")


def ensure_usuario_access_structural_schema(conn) -> None:
    """Validate central prod-1 ownership of access schema."""
    _require_prod1_tables(conn, "usuarios", "configuracoes_acesso", "usuarios_permissoes_acesso")


def seed_usuario_access_default_data(conn) -> None:
    """Insert the five historical access defaults without overwriting custom values."""
    for nivel_acesso, senha_padrao in DEFAULT_ACCESS_PASSWORDS.items():
        # NOTA: senhas "padrão" históricas são gravadas SOMENTE na primeira inicialização.
        # Em ambientes onde não houver linha pré-existente, mantemos os valores acima
        # para preservar o fluxo administrativo. NUNCA reutilize esses valores em
        # produção; reescreva-os via interface após o primeiro login.
        conn.execute(
            "INSERT OR IGNORE INTO configuracoes_acesso (nivel_acesso, senha_padrao) VALUES (?, ?)",
            (nivel_acesso, senha_padrao),
        )


def normalize_usuario_access_startup_data(conn) -> None:
    """Normalize only the accepted startup-wide historical access states."""
    conn.execute(
        "UPDATE usuarios SET nivel_acesso = ? WHERE tipo = 'admin' AND (nivel_acesso IS NULL OR TRIM(nivel_acesso) = '')",
        (default_access_level_for_user_type("admin"),),
    )
    conn.execute(
        "UPDATE usuarios SET nivel_acesso = ? WHERE tipo = 'aluno' AND (nivel_acesso IS NULL OR TRIM(nivel_acesso) = '')",
        (default_access_level_for_user_type("aluno"),),
    )
    conn.execute(
        "UPDATE usuarios SET nivel_acesso = ? WHERE tipo = 'aluno' AND LOWER(TRIM(COALESCE(nivel_acesso, ''))) = 'administrativo'",
        (default_access_level_for_user_type("aluno"),),
    )
    # NOTA: permanece ausente o UPDATE incondicional que promovia
    # o e-mail "admin@ej.edu.br" a admin_total a cada execução.


def ensure_usuario_access_schema(conn) -> None:
    """Ensure access schema and startup data without finalizing caller work.

    Releasing this helper-owned savepoint persists its work on a clean
    connection. Under an existing transaction, the caller retains commit and
    rollback ownership.
    """
    conn.execute("SAVEPOINT ensure_usuario_access_schema")
    try:
        ensure_usuario_access_structural_schema(conn)
        seed_usuario_access_default_data(conn)
        normalize_usuario_access_startup_data(conn)
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT ensure_usuario_access_schema")
        conn.execute("RELEASE SAVEPOINT ensure_usuario_access_schema")
        raise
    else:
        conn.execute("RELEASE SAVEPOINT ensure_usuario_access_schema")


def ensure_reportes_table(conn) -> None:
    _require_prod1_tables(conn, "reportes")


def ensure_requisicao_arquivos_table(conn) -> None:
    _require_prod1_tables(conn, "requisicao_arquivos")


def ensure_usuario_profile_schema(conn) -> None:
    _require_prod1_tables(conn, "usuarios", "alunos")


def ensure_requisicao_alert_receipts_table(conn) -> None:
    _require_prod1_tables(conn, "requisicao_alerta_receipts")


def ensure_admin_arquivos_table(conn) -> None:
    _require_prod1_tables(conn, "admin_arquivos")


def ensure_admin_alertas_table(conn) -> None:
    _require_prod1_tables(conn, "admin_alertas")


_AUTO_SYNC_LOCK = threading.Lock()
_AUTO_SYNC_STATE = {
    "last_signature": None,
    "last_synced_at": 0.0,
}


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


SCHEMA_MIGRATIONS = (
    (1, BASELINE_MARKER, bootstrap_prod1_schema),
    (2, NORMA_REMOVAL_MARKER, bootstrap_prod1_schema),
    (3, LATEST_MIGRATION_MARKER, bootstrap_prod1_schema),
)


def ensure_schema_migrations_table(conn: sqlite3.Connection) -> None:
    """Validate the prod-1 marker; schema creation belongs to the baseline bootstrap."""
    get_prod1_schema_status(conn)


def apply_schema_migrations(
    conn: sqlite3.Connection, logger=None, through_version: int | None = None
) -> dict[str, object]:
    if through_version not in (None, SCHEMA_VERSION):
        raise ValueError("prod-1 supports only migration to the current schema")
    before = get_schema_version(conn)
    status = bootstrap_prod1_schema(conn)
    return {
        "applied": [SCHEMA_VERSION] if before < SCHEMA_VERSION else [],
        "schema_epoch": SCHEMA_EPOCH,
        "schema_version": SCHEMA_VERSION,
        "target_schema_version": SCHEMA_VERSION,
    }


def apply_early_schema_migrations(conn: sqlite3.Connection, logger=None) -> dict[str, object]:
    return apply_schema_migrations(conn, logger=logger)


def get_schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0]) if row else 0


def get_schema_status(conn: sqlite3.Connection) -> dict[str, object]:
    status = get_prod1_schema_status(conn)
    return {
        "schema_epoch": status["schema_epoch"],
        "schema_version": status["schema_version"],
        "target_schema_epoch": SCHEMA_EPOCH,
        "target_schema_version": SCHEMA_VERSION,
        "latest_migration": status["migration"],
    }


def _ensure_directory(path: str | None) -> str | None:
    if not path:
        return None
    os.makedirs(path, exist_ok=True)
    return path


def _database_change_signature(database_path: str) -> str:
    parts: list[str] = []
    for suffix in ("", "-wal", "-shm"):
        candidate = database_path + suffix
        if not os.path.exists(candidate):
            continue
        stat = os.stat(candidate)
        parts.append(f"{suffix}:{stat.st_mtime_ns}:{stat.st_size}")
    return "|".join(parts)


def _snapshot_database(source_db_path: str, destination_db_path: str) -> None:
    os.makedirs(os.path.dirname(destination_db_path), exist_ok=True)
    source_conn = sqlite3.connect(source_db_path)
    target_conn = sqlite3.connect(destination_db_path)
    try:
        source_conn.backup(target_conn)
        target_conn.commit()
    finally:
        target_conn.close()
        source_conn.close()


def _read_backup_schema_status(database_path: str) -> dict[str, object]:
    uri = Path(database_path).resolve().as_uri() + "?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    try:
        return get_prod1_schema_status(conn)
    finally:
        conn.close()


def create_database_snapshot(
    source_db_path: str,
    target_root: str,
    *,
    schema_status: dict[str, object] | None = None,
    reason: str = "manual",
    origin: str = "local",
    logger=None,
    extra_metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    verified_schema_status = _read_backup_schema_status(source_db_path)
    if schema_status:
        if (
            schema_status.get("schema_epoch") != SCHEMA_EPOCH
            or int(schema_status.get("schema_version", -1)) != SCHEMA_VERSION
        ):
            raise SchemaMigrationStateError("backup schema metadata is not prod-1/v1")
    schema_status = verified_schema_status
    target_root = _ensure_directory(target_root) or target_root
    snapshots_dir = _ensure_directory(os.path.join(target_root, "snapshots"))
    latest_dir = _ensure_directory(os.path.join(target_root, "latest"))
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    basename = f"database-{timestamp}-{secrets.token_hex(3)}"
    snapshot_db_path = os.path.join(snapshots_dir, f"{basename}.db")
    snapshot_manifest_path = os.path.join(snapshots_dir, f"{basename}.json")

    _snapshot_database(source_db_path, snapshot_db_path)

    manifest = {
        "snapshot_id": basename,
        "created_at": _utc_now_iso(),
        "reason": reason,
        "origin": origin,
        "database_path": snapshot_db_path,
        "database_name": os.path.basename(source_db_path),
        "schema_epoch": SCHEMA_EPOCH,
        "schema_version": SCHEMA_VERSION,
        "schema_status": schema_status,
        "source_database_path": source_db_path,
    }
    if extra_metadata:
        manifest["extra_metadata"] = extra_metadata

    with open(snapshot_manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)

    latest_db_path = os.path.join(latest_dir, "database_latest.db")
    latest_manifest_path = os.path.join(latest_dir, "database_latest.json")
    shutil.copy2(snapshot_db_path, latest_db_path)
    with open(latest_manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)

    if logger is not None:
        logger.info("Snapshot de banco criado em %s", snapshot_db_path)

    return {
        **manifest,
        "manifest_path": snapshot_manifest_path,
        "latest_database_path": latest_db_path,
        "latest_manifest_path": latest_manifest_path,
    }


def upload_snapshot_to_external_server(
    snapshot_db_path: str,
    manifest_path: str,
    *,
    server_url: str,
    token: str | None = None,
    timeout_seconds: int = 30,
    logger=None,
) -> dict[str, object]:
    boundary = f"----backup-{secrets.token_hex(12)}"
    body = bytearray()

    def _append_bytes(value: bytes) -> None:
        body.extend(value)

    def _append_field(name: str, value: str) -> None:
        _append_bytes(f"--{boundary}\r\n".encode("utf-8"))
        _append_bytes(
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode("utf-8")
        )

    def _append_file(field_name: str, file_path: str, content_type: str) -> None:
        filename = os.path.basename(file_path)
        _append_bytes(f"--{boundary}\r\n".encode("utf-8"))
        _append_bytes(
            (
                f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode("utf-8")
        )
        with open(file_path, "rb") as handle:
            body.extend(handle.read())
        _append_bytes(b"\r\n")

    _append_field("source", "sistema-atividades-complementares")
    _append_file("database", snapshot_db_path, "application/vnd.sqlite3")
    _append_file("manifest", manifest_path, "application/json")
    _append_bytes(f"--{boundary}--\r\n".encode("utf-8"))

    request_obj = urllib_request.Request(server_url, data=bytes(body), method="POST")
    request_obj.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    request_obj.add_header("Accept", "application/json, text/plain, */*")
    if token:
        request_obj.add_header("Authorization", f"Bearer {token}")

    try:
        with urllib_request.urlopen(request_obj, timeout=timeout_seconds) as response:
            payload = response.read().decode("utf-8", errors="replace")
            result = {"status_code": response.getcode(), "body": payload}
            if logger is not None:
                logger.info("Snapshot enviado ao servidor externo %s com status %s", server_url, response.getcode())
            return result
    except urllib_error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        if logger is not None:
            logger.warning("Falha HTTP ao enviar snapshot para servidor externo %s: %s", server_url, exc)
        raise RuntimeError(f"Servidor externo respondeu {exc.code}: {detail or exc.reason}") from exc
    except urllib_error.URLError as exc:
        if logger is not None:
            logger.warning("Falha de conexão ao enviar snapshot para servidor externo %s: %s", server_url, exc)
        raise RuntimeError(f"Não foi possível conectar ao servidor externo: {exc.reason}") from exc


def delete_database_snapshot(manifest_path: str, logger=None) -> None:
    with open(manifest_path, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)

    db_path = manifest.get("database_path") or ""
    snapshot_id = manifest.get("snapshot_id") or os.path.splitext(os.path.basename(manifest_path))[0]
    root_dir = os.path.dirname(os.path.dirname(manifest_path))
    latest_manifest_path = os.path.join(root_dir, "latest", "database_latest.json")
    latest_db_path = os.path.join(root_dir, "latest", "database_latest.db")

    if os.path.exists(latest_manifest_path):
        try:
            with open(latest_manifest_path, "r", encoding="utf-8") as handle:
                latest_manifest = json.load(handle)
        except (OSError, json.JSONDecodeError):
            latest_manifest = None
        latest_snapshot_id = None if not latest_manifest else latest_manifest.get("snapshot_id") or os.path.splitext(os.path.basename(latest_manifest_path))[0]
        if latest_snapshot_id == snapshot_id:
            for candidate in (latest_manifest_path, latest_db_path):
                try:
                    os.remove(candidate)
                except OSError:
                    pass

    for candidate in (manifest_path, db_path):
        if not candidate:
            continue
        try:
            os.remove(candidate)
        except OSError:
            pass

    if logger is not None:
        logger.info("Snapshot removido: %s", manifest_path)


def list_database_backups(locations: dict[str, str | None]) -> list[dict[str, object]]:
    backups: list[dict[str, object]] = []
    for location_label, root in locations.items():
        if not root:
            continue
        snapshots_dir = os.path.join(root, "snapshots")
        if not os.path.isdir(snapshots_dir):
            continue
        for entry in os.listdir(snapshots_dir):
            if not entry.endswith(".json"):
                continue
            manifest_path = os.path.join(snapshots_dir, entry)
            try:
                with open(manifest_path, "r", encoding="utf-8") as handle:
                    manifest = json.load(handle)
            except (OSError, json.JSONDecodeError):
                continue
            db_path = manifest.get("database_path")
            backups.append(
                {
                    "location": location_label,
                    "manifest_path": manifest_path,
                    "database_path": db_path,
                    "created_at": manifest.get("created_at"),
                    "reason": manifest.get("reason"),
                    "origin": manifest.get("origin"),
                    "schema_status": manifest.get("schema_status") or {},
                    "size_bytes": os.path.getsize(db_path) if db_path and os.path.exists(db_path) else None,
                }
            )
    backups.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return backups


def maybe_sync_database_to_cloud(
    source_db_path: str,
    cloud_root: str | None,
    *,
    schema_status: dict[str, object] | None = None,
    min_interval_seconds: int = 300,
    force: bool = False,
    logger=None,
) -> dict[str, object]:
    if not cloud_root:
        return {"ok": False, "skipped": True, "reason": "cloud_backup_disabled"}

    signature = _database_change_signature(source_db_path)
    now = time.time()
    with _AUTO_SYNC_LOCK:
        last_signature = _AUTO_SYNC_STATE.get("last_signature")
        last_synced_at = float(_AUTO_SYNC_STATE.get("last_synced_at") or 0.0)
        if not force and last_signature == signature:
            return {"ok": True, "skipped": True, "reason": "unchanged"}
        if not force and last_synced_at and (now - last_synced_at) < max(0, min_interval_seconds):
            return {"ok": True, "skipped": True, "reason": "cooldown"}

        snapshot = create_database_snapshot(
            source_db_path,
            cloud_root,
            schema_status=schema_status,
            reason="auto-sync" if not force else "forced-sync",
            origin="cloud",
            logger=logger,
        )
        _AUTO_SYNC_STATE["last_signature"] = signature
        _AUTO_SYNC_STATE["last_synced_at"] = now
        return {"ok": True, "skipped": False, "snapshot": snapshot}


def apply_retention_policy(
    snapshots: list[dict],
    policy: list[dict],
) -> list[str]:
    """Return manifest_paths that should be deleted to enforce the GFS retention policy.

    Each policy window: {period_hours, interval_hours, slots}.
    Snapshots with reason == "manual-backup" are never included in the delete list.
    """
    now = datetime.datetime.now(datetime.timezone.utc)

    parsed: list[dict] = []
    for snap in snapshots:
        raw = (snap.get("created_at") or "").replace("Z", "+00:00")
        try:
            dt = datetime.datetime.fromisoformat(raw)
        except ValueError:
            continue
        parsed.append({**snap, "_dt": dt})

    parsed.sort(key=lambda x: x["_dt"], reverse=True)

    kept: set[str] = set()
    for window in policy:
        try:
            period_h = float(window["period_hours"])
            interval_h = float(window["interval_hours"])
            slots = int(window["slots"])
        except (KeyError, TypeError, ValueError):
            continue
        if interval_h <= 0 or slots <= 0:
            continue

        cutoff = now - datetime.timedelta(hours=period_h)
        buckets: dict[int, dict] = {}
        for snap in parsed:
            if snap.get("reason") == "manual-backup":
                continue  # manual backups don't consume window slots
            if snap["_dt"] < cutoff:
                continue
            age_h = (now - snap["_dt"]).total_seconds() / 3600.0
            bucket_idx = int(age_h / interval_h)
            if bucket_idx not in buckets:
                buckets[bucket_idx] = snap

        for i, (_, snap) in enumerate(sorted(buckets.items())):
            if i >= slots:
                break
            mp = snap.get("manifest_path") or ""
            if mp:
                kept.add(mp)

    to_delete: list[str] = []
    for snap in parsed:
        mp = snap.get("manifest_path") or ""
        if not mp:
            continue
        if snap.get("reason") == "manual-backup":
            continue
        if mp not in kept:
            to_delete.append(mp)
    return to_delete


def restore_database_snapshot(source_snapshot_path: str, target_db_path: str, logger=None) -> None:
    _read_backup_schema_status(source_snapshot_path)
    temp_dir = os.path.dirname(target_db_path) or os.getcwd()
    temp_handle = tempfile.NamedTemporaryFile(prefix="restore-", suffix=".db", dir=temp_dir, delete=False)
    temp_handle.close()
    temp_target_path = temp_handle.name
    source_conn = sqlite3.connect(source_snapshot_path)
    target_conn = sqlite3.connect(temp_target_path)
    try:
        source_conn.backup(target_conn)
        target_conn.commit()
    finally:
        target_conn.close()
        source_conn.close()

    for suffix in ("-wal", "-shm"):
        try:
            os.remove(target_db_path + suffix)
        except OSError:
            pass
    os.replace(temp_target_path, target_db_path)
    if logger is not None:
        logger.info("Banco restaurado a partir de %s", source_snapshot_path)


def _require_prod1_tables(conn: sqlite3.Connection, *names: str) -> None:
    present = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    missing = set(names) - present
    if missing:
        raise SchemaMigrationStateError(
            f"prod-1 schema objects missing: {sorted(missing)!r}"
        )


def ensure_matrizes_atividades_table(conn) -> None:
    """Compatibility name retained for callers; validates and never mutates schema."""
    _require_prod1_tables(conn, "matrizes_atividades")


def ensure_matriz_atividade_links_table(conn) -> None:
    """Validate sole exact-version matrix authority; performs no DDL."""
    _require_prod1_tables(conn, "matriz_atividade_versao_item")


def ensure_atividade_versioning_leaf_tables(conn) -> None:
    _require_prod1_tables(
        conn,
        "matriz_atividade_versao_item",
        "atividade_transicao",
    )


def ensure_atividade_versioning_leaf_triggers(conn) -> None:
    expected = {
        "trg_atividade_transicao_aac_para_aeu_insert",
        "trg_atividade_transicao_aac_para_aeu_update",
    }
    present = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        )
    }
    if not expected <= present:
        raise SchemaMigrationStateError("prod-1 activity transition triggers missing")


def ensure_atividade_versioning_leaf_indexes(conn) -> None:
    expected = {
        "idx_matriz_atividade_versao_item_matriz",
        "idx_matriz_atividade_versao_item_base",
        "idx_matriz_atividade_versao_item_versao",
        "idx_atividade_transicao_from",
        "idx_atividade_transicao_to",
        "idx_atividade_transicao_tipo",
    }
    present = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )
    }
    if not expected <= present:
        raise SchemaMigrationStateError("prod-1 activity versioning indexes missing")


def ensure_atividade_versioning_schema(conn) -> None:
    """Validate the central prod-1 activity graph; performs no schema mutation."""
    get_prod1_schema_status(conn)
