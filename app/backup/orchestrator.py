# coding: utf-8
"""Orquestração canônica de backup (dono único pós-UT-5).

Este módulo passou a deter os corpos que antes viviam em main.py:
sincronização de snapshot em nuvem, política de retenção local, upload para
drives (Google/OneDrive), envio ao servidor externo, leitura de configurações
de runtime e resolução segura de manifestos.

Contratos de fronteira:

* **Sem dependência de main.** Nada aqui importa ``main`` nem toca em
  ``main.app``. A configuração de aplicação é lida via ``flask.current_app``,
  portanto **toda a API pública deste módulo exige um application context
  ativo** (e nenhum request context).
* **Caminho do banco resolvido em tempo de chamada.** Nunca
  ``from app.db import DATABASE``; sempre ``_app_db.DATABASE`` no momento da
  chamada, para que rebind (testes/runtime) jamais fique obsoleto.
* **Camadas inferiores reutilizadas sem expansão.** ``app.db_maintenance``,
  ``app.backup_settings`` e ``app.cloud_drives`` mantêm seus algoritmos; o
  módulo ``app.cloud_drives`` é acessado por indireção (``_cd.<fn>``) para
  preservar a interceptação por monkeypatch do objeto-módulo.
* **Sem mensagens de usuário.** O catálogo pt-BR e as validações que carregam
  texto continuam em main.py. Aqui só há logging técnico, no canal já
  estabelecido ``logging.getLogger("main")``.
"""
import datetime
import logging
import os
import sqlite3

from flask import current_app, g

import app.cloud_drives as _cd
import app.cloud_connections as _cloud_connections
from app import db as _app_db
from app.backup_settings import (
    _apply_backup_settings_to_app,
    _backup_settings_defaults,
    ensure_backup_settings_schema,
    get_backup_settings,
)
from app.db_maintenance import (
    apply_retention_policy,
    create_database_snapshot,
    delete_database_snapshot,
    get_schema_status,
    list_database_backups,
    maybe_sync_database_to_cloud,
    upload_snapshot_to_external_server,
)
from app.paths import _path_within_root


logger = logging.getLogger("main")


# ===================== Configurações de runtime =====================


def _get_runtime_backup_settings(conn=None):
    temp_conn = None
    if conn is None:
        temp_conn = sqlite3.connect(_app_db.DATABASE)
        temp_conn.row_factory = sqlite3.Row
        conn = temp_conn
    try:
        try:
            settings = get_backup_settings(conn)
        except sqlite3.OperationalError:
            settings = _backup_settings_defaults()
        _apply_backup_settings_to_app(settings)
        return settings
    finally:
        if temp_conn is not None:
            temp_conn.close()


def _database_backup_locations(settings=None):
    settings = settings or _backup_settings_defaults()
    return {
        "local": settings.get("local_backup_dir") or current_app.config.get("LOCAL_BACKUP_DIR"),
        "cloud": settings.get("cloud_backup_dir") or current_app.config.get("CLOUD_BACKUP_DIR"),
    }


def _resolve_allowed_backup_manifest_path(manifest_path: str) -> str | None:
    candidate = os.path.abspath(manifest_path or "")
    for root in _database_backup_locations(_get_runtime_backup_settings()).values():
        if _path_within_root(candidate, root):
            return candidate
    return None


# ===================== Política de retenção =====================


_RETENTION_WINDOWS_META = [
    {"key": "w0", "label": "Últimas 24 h", "period_hours": 24, "default_interval": "2", "default_slots": "12"},
    {"key": "w1", "label": "Últimos 7 dias", "period_hours": 168, "default_interval": "24", "default_slots": "7"},
    {"key": "w2", "label": "Últimas 4 semanas", "period_hours": 672, "default_interval": "168", "default_slots": "4"},
    {"key": "w3", "label": "Últimos 12 meses", "period_hours": 8760, "default_interval": "730", "default_slots": "12"},
]


def _retention_policy_defaults() -> dict[str, str]:
    defaults = {}
    for w in _RETENTION_WINDOWS_META:
        defaults[f"retention_{w['key']}_interval_hours"] = w["default_interval"]
        defaults[f"retention_{w['key']}_slots"] = w["default_slots"]
    return defaults


def get_retention_policy(conn) -> dict[str, str]:
    defaults = _retention_policy_defaults()
    try:
        rows = conn.execute(
            "SELECT chave, valor FROM configuracoes_backup WHERE chave LIKE 'retention_%'"
        ).fetchall()
        settings = dict(defaults)
        for row in rows:
            settings[str(row["chave"])] = str(row["valor"])
        return settings
    except sqlite3.OperationalError:
        return defaults


def _build_retention_policy_windows(settings: dict[str, str]) -> list[dict]:
    windows = []
    for w in _RETENTION_WINDOWS_META:
        windows.append({
            "period_hours": w["period_hours"],
            "interval_hours": float(settings.get(f"retention_{w['key']}_interval_hours") or w["default_interval"]),
            "slots": int(settings.get(f"retention_{w['key']}_slots") or w["default_slots"]),
        })
    return windows


def _run_retention_cleanup(conn=None) -> dict:
    temp_conn = None
    if conn is None:
        temp_conn = sqlite3.connect(_app_db.DATABASE)
        temp_conn.row_factory = sqlite3.Row
        conn = temp_conn
    try:
        settings = _get_runtime_backup_settings(conn)
        retention_settings = get_retention_policy(conn)
        policy = _build_retention_policy_windows(retention_settings)
        locations = _database_backup_locations(settings)
        # Each location keeps its own series under the same policy -- as remote
        # retention does per provider -- so the local snapshot and the cloud
        # folder copy taken by one backup never compete for a single slot.
        # ``created_at`` has one-second resolution and the policy's sort is
        # stable, so snapshots are handed over newest-first by file name
        # (which carries microseconds): a same-second tie keeps the newest.
        to_delete: list[str] = []
        for label, root in locations.items():
            snapshots = sorted(
                list_database_backups({label: root}),
                key=lambda snap: (
                    str(snap.get("created_at") or ""),
                    os.path.basename(str(snap.get("manifest_path") or "")),
                ),
                reverse=True,
            )
            for mp in apply_retention_policy(snapshots, policy):
                if mp not in to_delete:
                    to_delete.append(mp)
        deleted: list[str] = []
        errors: list[str] = []
        for mp in to_delete:
            safe_mp = _resolve_allowed_backup_manifest_path(mp)
            if not safe_mp or not os.path.exists(safe_mp):
                continue
            try:
                delete_database_snapshot(safe_mp, logger=logger)
                deleted.append(safe_mp)
            except Exception as exc:
                errors.append(str(exc))
        if deleted:
            logger.info("Política de retenção removeu %d snapshot(s).", len(deleted))
        return {"deleted": deleted, "errors": errors}
    finally:
        if temp_conn is not None:
            temp_conn.close()


# ===================== Configurações de drives =====================


def _drive_settings_defaults() -> dict[str, str]:
    return {
        "gdrive_enabled": "0",
        "gdrive_dest_folder": "Backups/sistema",
        "gdrive_access_token": "",
        "gdrive_refresh_token": "",
        "gdrive_expires_at": "",
        "gdrive_account_email": "",
        "gdrive_last_upload_at": "",
        "gdrive_last_upload_error": "",
        "onedrive_enabled": "0",
        "onedrive_dest_folder": "Backups/sistema",
        "onedrive_access_token": "",
        "onedrive_refresh_token": "",
        "onedrive_expires_at": "",
        "onedrive_account_email": "",
        "onedrive_last_upload_at": "",
        "onedrive_last_upload_error": "",
    }


def get_drive_settings(conn) -> dict[str, str]:
    defaults = _drive_settings_defaults()
    try:
        rows = conn.execute(
            "SELECT chave, valor FROM configuracoes_backup"
            " WHERE chave LIKE 'gdrive_%' OR chave LIKE 'onedrive_%'"
        ).fetchall()
        settings = dict(defaults)
        for row in rows:
            settings[str(row["chave"])] = str(row["valor"])
        return settings
    except sqlite3.OperationalError:
        return defaults


def _save_drive_config(conn, updates: dict[str, str]) -> None:
    ensure_backup_settings_schema(conn)
    from app.sql_dialect import current_utc_text

    for chave, valor in updates.items():
        conn.execute(
            f"""
            INSERT INTO configuracoes_backup (chave, valor, atualizado_em)
            VALUES (?, ?, {current_utc_text(conn)})
            ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor, atualizado_em = {current_utc_text(conn)}
            """,
            (chave, str(valor)),
        )


# ===================== Resultado por destino =====================
#
# Cada destino de um backup (pasta em nuvem, Google Drive, OneDrive, servidor
# externo) relata o próprio desfecho de forma independente. Os estados são
# técnicos -- o texto para o usuário é escolhido pela view, que é quem detém o
# catálogo de mensagens.

OUTCOME_SUCCESS = "success"
OUTCOME_NOT_CONFIGURED = "skipped_not_configured"
OUTCOME_NOT_ENABLED = "skipped_not_enabled"
OUTCOME_UNCHANGED = "unchanged"
OUTCOME_DEFERRED = "deferred"
OUTCOME_FAILED = "failed"

DRIVE_PROVIDERS = ("google", "onedrive")


def _destination_outcome(status: str, reason: str = "") -> dict[str, str]:
    return {"status": status, "reason": reason}


def _cloud_folder_outcome(sync_result: dict | None) -> dict[str, str]:
    """Traduz o resultado de ``maybe_sync_database_to_cloud`` para um desfecho.

    Só a pasta em nuvem tem semântica de "sem alterações" (assinatura do banco)
    e de adiamento (intervalo mínimo) -- e ambas só valem sem ``force``.
    """
    result = sync_result or {}
    reason = str(result.get("reason") or "")
    if not result.get("skipped"):
        if result.get("ok"):
            return _destination_outcome(OUTCOME_SUCCESS)
        return _destination_outcome(OUTCOME_FAILED, reason)
    if reason == "cloud_backup_disabled":
        return _destination_outcome(OUTCOME_NOT_CONFIGURED, reason)
    if reason == "unchanged":
        return _destination_outcome(OUTCOME_UNCHANGED, reason)
    return _destination_outcome(OUTCOME_DEFERRED, reason)


def _provider_failure_outcome(exc: Exception) -> dict[str, str]:
    debug_code = str(getattr(exc, "debug_code", "") or "")
    if debug_code == "APPLICATION_CREDENTIALS_MISSING":
        return _destination_outcome(OUTCOME_NOT_CONFIGURED, debug_code)
    return _destination_outcome(OUTCOME_FAILED, debug_code or type(exc).__name__)


def _external_backup_outcome(external_result: dict | None) -> dict[str, str]:
    result = external_result or {}
    reason = str(result.get("reason") or "")
    if result.get("ok") and not result.get("skipped"):
        return _destination_outcome(OUTCOME_SUCCESS)
    if result.get("error"):
        return _destination_outcome(OUTCOME_FAILED, reason)
    if reason == "external_disabled":
        return _destination_outcome(OUTCOME_NOT_ENABLED, reason)
    return _destination_outcome(OUTCOME_NOT_CONFIGURED, reason)


def _maybe_upload_to_drives(snapshot_path: str, conn=None) -> dict[str, dict[str, str]]:
    """Upload snapshot to enabled cloud drive providers, then apply remote retention.

    Each provider is attempted independently and reports its own outcome:
    a failure in one never prevents or rewrites the other. Remote retention
    runs only for a provider whose upload succeeded, against that provider.
    """
    outcomes: dict[str, dict[str, str]] = {}
    temp_conn = None
    if conn is None:
        temp_conn = sqlite3.connect(_app_db.DATABASE)
        temp_conn.row_factory = sqlite3.Row
        conn = temp_conn
    try:
        drive_settings = get_drive_settings(conn)
        retention_settings = get_retention_policy(conn)
        policy = _build_retention_policy_windows(retention_settings)

        for provider in DRIVE_PROVIDERS:
            prefix = "gdrive" if provider == "google" else "onedrive"
            enabled = str(drive_settings.get(f"{prefix}_enabled") or "0") in {"1", "true"}
            if not enabled:
                outcomes[provider] = _destination_outcome(OUTCOME_NOT_ENABLED)
                continue

            dest_folder = drive_settings.get(f"{prefix}_dest_folder") or "Backups/sistema"
            try:
                token, _account_email = _cloud_connections.get_authenticated_access_token(
                    conn, provider
                )

                if provider == "google":
                    _cd.google_upload(token, snapshot_path, dest_folder)
                else:
                    _cd.onedrive_upload(token, snapshot_path, dest_folder)
                # The provider holds the file from here on; later bookkeeping
                # cannot turn this into a failed upload.
                outcomes[provider] = _destination_outcome(OUTCOME_SUCCESS)

                now_iso = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
                _save_drive_config(conn, {
                    f"{prefix}_last_upload_at": now_iso,
                    f"{prefix}_last_upload_error": "",
                })
                conn.commit()
                logger.info("Drive upload [%s] concluído: %s", provider, snapshot_path)

                try:
                    _cd.apply_retention_to_drive(
                        provider, token=token, dest_folder=dest_folder,
                        policy=policy, logger=logger,
                    )
                except Exception as exc:
                    logger.warning("Retenção remota [%s] falhou: %s", provider, exc)

            except Exception as exc:
                if outcomes.get(provider, {}).get("status") == OUTCOME_SUCCESS:
                    logger.warning(
                        "Drive upload [%s] concluído, mas o registro local falhou: %s",
                        provider,
                        exc,
                    )
                    continue
                logger.warning("Drive upload [%s] falhou: %s", provider, exc)
                outcomes[provider] = _provider_failure_outcome(exc)
                try:
                    _save_drive_config(conn, {f"{prefix}_last_upload_error": str(exc)[:200]})
                    conn.commit()
                except Exception:
                    pass
    finally:
        if temp_conn is not None:
            temp_conn.close()
    return outcomes


# ===================== Snapshot: nuvem e servidor externo =====================


def _upload_snapshot_if_external_enabled(snapshot: dict[str, object], settings: dict[str, str]):
    if str(settings.get("external_backup_enabled") or "0") not in {"1", "true", "True"}:
        return {"ok": False, "skipped": True, "reason": "external_disabled"}

    server_url = (settings.get("external_backup_url") or "").strip()
    if not server_url:
        return {"ok": False, "skipped": True, "reason": "external_url_missing"}

    result = upload_snapshot_to_external_server(
        str(snapshot["database_path"]),
        str(snapshot["manifest_path"]),
        server_url=server_url,
        token=(settings.get("external_backup_token") or "").strip() or None,
        logger=logger,
    )
    return {"ok": True, "skipped": False, "result": result}


def _maybe_sync_database_snapshot(force: bool = False, conn=None):
    settings = _get_runtime_backup_settings(conn)
    cloud_root = settings.get("cloud_backup_dir") or current_app.config.get("CLOUD_BACKUP_DIR")
    if not cloud_root:
        return {"ok": False, "skipped": True, "reason": "cloud_backup_disabled"}

    temp_conn = None
    if conn is None:
        conn = getattr(g, "db", None)
    if conn is None and not force:
        return {"ok": True, "skipped": True, "reason": "no_open_connection"}
    if conn is None:
        temp_conn = sqlite3.connect(_app_db.DATABASE)
        temp_conn.row_factory = sqlite3.Row
        conn = temp_conn
    try:
        return maybe_sync_database_to_cloud(
            _app_db.DATABASE,
            cloud_root,
            schema_status=get_schema_status(conn),
            min_interval_seconds=int(settings.get("cloud_sync_interval_seconds") or current_app.config.get("CLOUD_SYNC_INTERVAL_SECONDS", 300)),
            force=force,
            logger=logger,
        )
    finally:
        if temp_conn is not None:
            temp_conn.close()


# ===================== Ciclo composto canônico =====================


def _distribute_snapshot(snapshot_path: str, *, force: bool, conn=None) -> dict:
    """Envia um snapshot local já criado a cada destino, de forma independente.

    Ordem: pasta em nuvem, Google Drive, OneDrive e, só depois de todos os
    envios, a retenção local. Nenhum destino é pré-requisito de outro: a pasta
    em nuvem ausente, adiada ou com falha não impede os provedores, e a falha
    de um provedor não impede nem reescreve o outro.

    Retorna ``outcomes`` (um desfecho por destino) mais os resultados brutos da
    pasta em nuvem e da retenção.
    """
    outcomes: dict[str, dict[str, str]] = {}

    sync_result = None
    try:
        sync_result = _maybe_sync_database_snapshot(force=force, conn=conn)
        outcomes["cloud_folder"] = _cloud_folder_outcome(sync_result)
    except Exception as exc:
        logger.warning("Cópia para a pasta em nuvem falhou: %s", exc)
        outcomes["cloud_folder"] = _destination_outcome(OUTCOME_FAILED, type(exc).__name__)

    try:
        outcomes.update(_maybe_upload_to_drives(snapshot_path, conn=conn) or {})
    except Exception as exc:
        logger.warning("Upload para drives falhou: %s", exc)
        for provider in DRIVE_PROVIDERS:
            outcomes.setdefault(
                provider, _destination_outcome(OUTCOME_FAILED, type(exc).__name__)
            )

    retention_result = None
    try:
        retention_result = _run_retention_cleanup(conn=conn)
    except Exception as exc:
        logger.warning("Falha ao aplicar política de retenção após backup: %s", exc)

    return {
        "outcomes": outcomes,
        "sync": sync_result,
        "retention": retention_result,
    }


def run_backup_cycle(*, force: bool = False, conn=None) -> dict:
    """Ciclo automático canônico de backup (não-request).

    Precondição explícita: **application context ativo** (nenhum request
    context é necessário nem usado).

        1. cria o snapshot local -- o único pré-requisito, porque é o artefato
           que os destinos recebem; uma falha aqui propaga para quem chama;
        2. distribui esse snapshot com :func:`_distribute_snapshot`: pasta em
           nuvem (se configurada), Google Drive e OneDrive (cada um só se o seu
           "Incluir no backup automático" estiver ligado), cada destino de
           forma independente, e então a retenção local.

    ``force`` vale só para a pasta em nuvem, o único destino com semântica de
    "sem alterações"/intervalo mínimo. O upload ao servidor externo **não** faz
    parte deste ciclo: continua sendo um primitivo composto pela rota manual de
    "Banco de Dados".
    """
    temp_conn = None
    if conn is None:
        temp_conn = sqlite3.connect(_app_db.DATABASE)
        temp_conn.row_factory = sqlite3.Row
        conn = temp_conn
    try:
        settings = _get_runtime_backup_settings(conn)
        snapshot = create_database_snapshot(
            _app_db.DATABASE,
            settings.get("local_backup_dir") or current_app.config.get("LOCAL_BACKUP_DIR"),
            schema_status=get_schema_status(conn),
            reason="auto-backup",
            origin="local",
            logger=logger,
        )
        database_path = str(snapshot["database_path"])
        distribution = _distribute_snapshot(database_path, force=force, conn=conn)
    finally:
        if temp_conn is not None:
            temp_conn.close()

    return {
        "snapshot": snapshot,
        "outcomes": distribution["outcomes"],
        "sync": distribution["sync"],
        "retention": distribution["retention"],
        "drive_upload_source_path": database_path,
    }
