# coding: utf-8
"""Backup automático: "o backup é devido agora?" (UI-C13).

A periodicidade é a do SGAA, não a do Windows. O dono é a configuração já
existente ``cloud_sync_interval_seconds`` ("Intervalo de verificação (s)" em
Banco de dados → Destinos e sincronização; ``0 = ao alterar``) -- o mesmo
portão que governava o ciclo automático antes da UT-5: um backup automático só
acontece quando o banco mudou **e** já passou esse intervalo desde o último.

O agendador do Windows apenas acorda o SGAA num ritmo fixo de verificação
(``app.backup.task_scheduler``); quem decide é :func:`evaluate_due`. Mudar o
intervalo no SGAA muda o comportamento no próximo despertar, sem tocar na
tarefa.

Estado persistido: um JSON por pasta de backup local
(``.sgaa-automatic-backup-state`` -- sem extensão ``.json`` para nunca se
passar por manifesto de snapshot), indexado pelo caminho absoluto do banco --
fora do banco de propósito, porque escrever no banco mudaria o próprio
conteúdo que decide "mudou?". Só é escrito sob :func:`backup_cycle_lock`.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import logging
import os
import sqlite3
from logging.handlers import RotatingFileHandler

from flask import current_app

from app import db as _app_db
from app.backup import orchestrator as _orchestrator
from app.backup.lock import BackupCycleBusy, backup_cycle_lock

logger = logging.getLogger("main")

STATE_FILENAME = ".sgaa-automatic-backup-state"
RUN_LOG_FILENAME = "backup-automatico.log"

#: Folga para o relógio do despertar: o snapshot anterior foi datado alguns
#: segundos depois do despertar que o criou, então sem folga um intervalo de
#: 600 s com despertar de 5 min cairia sempre no despertar seguinte (15 min).
DUE_GRACE_SECONDS = 60

#: Tabelas que o próprio ciclo escreve (datas de envio, renovação de token,
#: log de envio). Ficam fora da impressão digital do conteúdo; do contrário
#: cada backup "mudaria" o banco e o seguinte nunca seria pulado.
_BOOKKEEPING_TABLES = frozenset(
    {"configuracoes_backup", "cloud_accounts", "backup_logs", "cloud_drive_settings"}
)


# ===================== Periodicidade configurada =====================


def configured_interval_seconds(settings: dict) -> int:
    """O intervalo configurado no SGAA; ``ValueError`` se não for um inteiro >= 0."""
    raw = str(settings.get("cloud_sync_interval_seconds") or "").strip()
    if raw == "":
        raw = str(current_app.config.get("CLOUD_SYNC_INTERVAL_SECONDS", 600))
    value = int(raw)
    if value < 0:
        raise ValueError("intervalo negativo")
    return value


# ===================== Conteúdo do banco =====================


def database_content_digest(database_path: str) -> str:
    """Impressão digital lógica do banco: esquema + linhas, sem as tabelas de controle.

    Lida pelo SQLite (inclui o que ainda está no WAL) e estável entre
    checkpoints; abrir, ler ou fazer snapshot não a altera.
    """
    conn = sqlite3.connect(database_path)
    try:
        conn.execute("PRAGMA query_only = ON")
        digest = hashlib.sha256()
        objects = conn.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall()
        for kind, name, sql in objects:
            digest.update(repr((kind, name, sql)).encode("utf-8"))
        for kind, name, _sql in objects:
            if kind != "table" or name.startswith("sqlite_") or name in _BOOKKEEPING_TABLES:
                continue
            digest.update(b"\x00table\x00" + name.encode("utf-8"))
            quoted = '"' + name.replace('"', '""') + '"'
            for row in conn.execute(f"SELECT * FROM {quoted}"):
                digest.update(repr(tuple(row)).encode("utf-8"))
        return digest.hexdigest()
    finally:
        conn.close()


# ===================== Estado persistido =====================


def _database_key(database_path: str) -> str:
    return os.path.normcase(os.path.abspath(str(database_path)))


def _state_path(local_backup_dir: str) -> str:
    return os.path.join(os.path.abspath(str(local_backup_dir)), STATE_FILENAME)


def read_state(local_backup_dir: str, database_path: str) -> dict:
    """Estado do backup automático deste banco (``{}`` se nunca houve)."""
    try:
        with open(_state_path(local_backup_dir), "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    entry = (data.get("databases") or {}).get(_database_key(database_path))
    return dict(entry) if isinstance(entry, dict) else {}


def _write_state(local_backup_dir: str, database_path: str, entry: dict) -> None:
    path = _state_path(local_backup_dir)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    databases = data.get("databases") if isinstance(data.get("databases"), dict) else {}
    databases[_database_key(database_path)] = entry
    data["databases"] = databases
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    os.replace(temporary, path)


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)


def _iso(moment: datetime.datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def _parse_iso(value) -> datetime.datetime | None:
    try:
        return datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


# ===================== Decisão =====================


def evaluate_due(state: dict, digest: str, interval_seconds: int, now: datetime.datetime) -> tuple[bool, str]:
    """``(devido, motivo)`` segundo o intervalo do SGAA e a mudança de conteúdo.

    Motivos: ``first_run``, ``changed``, ``unchanged`` (pulado), ``interval``
    (mudou, mas o intervalo ainda não passou).
    """
    last_backup_at = _parse_iso(state.get("last_backup_at"))
    if last_backup_at is None or not state.get("last_digest"):
        return True, "first_run"
    if state.get("last_digest") == digest:
        return False, "unchanged"
    elapsed = (now - last_backup_at).total_seconds()
    if elapsed + DUE_GRACE_SECONDS < interval_seconds:
        return False, "interval"
    return True, "changed"


# ===================== Execução =====================


def configure_run_log() -> str:
    """Log durável dos ciclos da CLI, ao lado do ``app.log`` (arquivo próprio).

    Mesmo diretório (``APP_LOG_DIR`` ou ``<repo>/logs``) e formato do log da
    aplicação, mas outro arquivo: dois processos rotacionando o mesmo arquivo
    no Windows falham.
    """
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    logs_dir = (os.getenv("APP_LOG_DIR") or "").strip() or os.path.join(project_root, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    path = os.path.join(logs_dir, RUN_LOG_FILENAME)
    if not any(
        isinstance(handler, RotatingFileHandler) and getattr(handler, "baseFilename", "") == os.path.abspath(path)
        for handler in logger.handlers
    ):
        handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return path


def _outcome_summary(outcomes: dict) -> str:
    return ", ".join(
        f"{destination}={(outcome or {}).get('status') or 'n/d'}"
        + (f"({(outcome or {}).get('reason')})" if (outcome or {}).get("reason") else "")
        for destination, outcome in (outcomes or {}).items()
    ) or "n/d"


def run_automatic_cycle(*, trigger: str, now: datetime.datetime | None = None) -> dict:
    """Um despertar do backup automático, sob o bloqueio de ciclo.

    ``trigger="scheduled"`` consulta :func:`evaluate_due` e pode pular;
    ``trigger="cli"`` (``python -m app.backup.sync`` sem opção) executa sempre,
    como antes. Exige application context. Retorna ``{"ran": bool, "reason":
    str, "result": dict | None}``; levanta :class:`BackupCycleBusy` se outro
    ciclo estiver em andamento, e deixa falhas do ciclo propagarem.
    """
    moment = now or _utc_now()
    database_path = _app_db.DATABASE
    settings = _orchestrator._get_runtime_backup_settings()
    local_dir = settings.get("local_backup_dir") or current_app.config.get("LOCAL_BACKUP_DIR")
    interval = configured_interval_seconds(settings)
    scheduled = trigger == "scheduled"
    logger.info(
        "Backup automático: início (gatilho=%s, intervalo configurado=%ss, banco=%s).",
        trigger,
        interval,
        database_path,
    )
    with backup_cycle_lock(local_dir):
        state = read_state(local_dir, database_path)
        digest = database_content_digest(database_path)
        if scheduled:
            due, reason = evaluate_due(state, digest, interval, moment)
        else:
            due, reason = True, "cli"
        if not due:
            state.update(last_check_at=_iso(moment), last_result=reason)
            _write_state(local_dir, database_path, state)
            logger.info("Backup automático: não devido (%s); nada foi feito.", reason)
            return {"ran": False, "reason": reason, "result": None}

        logger.info("Backup automático: devido (%s); executando o ciclo.", reason)
        try:
            result = _orchestrator.run_backup_cycle(force=not scheduled)
        except Exception as exc:
            state.update(last_check_at=_iso(moment), last_result="failed", last_error=type(exc).__name__)
            _write_state(local_dir, database_path, state)
            raise
        snapshot_path = str((result.get("snapshot") or {}).get("database_path") or "")
        state = {
            "last_backup_at": _iso(moment),
            "last_digest": digest,
            "last_check_at": _iso(moment),
            "last_result": "backup",
            "last_trigger": trigger,
            "last_snapshot": snapshot_path,
            "last_outcomes": {
                destination: (outcome or {}).get("status")
                for destination, outcome in (result.get("outcomes") or {}).items()
            },
        }
        _write_state(local_dir, database_path, state)
        logger.info(
            "Backup automático: concluído (snapshot=%s; destinos: %s; retenção removeu %d).",
            snapshot_path or "n/d",
            _outcome_summary(result.get("outcomes") or {}),
            len((result.get("retention") or {}).get("deleted") or []),
        )
        return {"ran": True, "reason": reason, "result": result}


__all__ = [
    "BackupCycleBusy",
    "DUE_GRACE_SECONDS",
    "RUN_LOG_FILENAME",
    "STATE_FILENAME",
    "configure_run_log",
    "configured_interval_seconds",
    "database_content_digest",
    "evaluate_due",
    "read_state",
    "run_automatic_cycle",
]
