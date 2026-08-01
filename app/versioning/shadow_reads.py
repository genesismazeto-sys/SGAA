from __future__ import annotations

import base64
import datetime
import json
import logging
import os
from pathlib import Path
import re
import traceback

from app.versioning import resolver as resolver_service


PROJECT_ROOT = Path(__file__).resolve().parents[2]
logger = logging.getLogger("main")


def is_versioned_resolver_shadow_read_enabled() -> bool:
    return str(os.getenv("SGAA_VERSIONED_RESOLVER_SHADOW_READ", "0")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

def _versioned_shadow_read_dedicated_log_path() -> str:
    log_dir = (os.getenv("APP_LOG_DIR") or "").strip() or os.path.join(
        os.fspath(PROJECT_ROOT), "logs"
    )
    return os.path.join(log_dir, "versioned_shadow_reads.log")

def _serialize_shadow_read_log_value(value) -> str:
    if value is None:
        return "null"
    text = str(value).strip()
    return text if text else "null"

def _build_versioned_shadow_read_event_line(
    *,
    origin,
    req_id,
    aluno_id,
    atividade_id_legacy,
    status,
    atividade_versao_id,
    codigo_normativo,
    eixo,
    warnings,
    reason,
    timestamp=None,
    exception_type=None,
    exception_message=None,
    exception_traceback=None,
) -> str:
    warnings_json = json.dumps(warnings or [], ensure_ascii=False)
    base = (
        "event=versioned_resolver_shadow_read "
        f"origin={_serialize_shadow_read_log_value(origin)} "
        f"req_id={_serialize_shadow_read_log_value(req_id)} "
        f"aluno_id={_serialize_shadow_read_log_value(aluno_id)} "
        f"atividade_id_legacy={_serialize_shadow_read_log_value(atividade_id_legacy)} "
        f"status={_serialize_shadow_read_log_value(status)} "
        f"atividade_versao_id={_serialize_shadow_read_log_value(atividade_versao_id)} "
        f"codigo_normativo={_serialize_shadow_read_log_value(codigo_normativo)} "
        f"eixo={_serialize_shadow_read_log_value(eixo)} "
        f"warnings={warnings_json} "
        f"reason={_serialize_shadow_read_log_value(reason)}"
    )
    suffix_parts: list[str] = []
    if timestamp:
        suffix_parts.append(f"timestamp={_serialize_shadow_read_log_value(timestamp)}")
    if exception_type:
        suffix_parts.append(f"exception_type={_serialize_shadow_read_log_value(exception_type)}")
    if exception_message is not None and str(exception_message) != "":
        encoded_msg = base64.b64encode(str(exception_message).encode("utf-8")).decode("ascii")
        suffix_parts.append(f"exception_message_b64={encoded_msg}")
    if exception_traceback is not None and str(exception_traceback) != "":
        encoded_tb = base64.b64encode(str(exception_traceback).encode("utf-8")).decode("ascii")
        suffix_parts.append(f"exception_traceback_b64={encoded_tb}")
    if suffix_parts:
        return base + " " + " ".join(suffix_parts)
    return base

def _append_versioned_shadow_read_event_line(event_line: str) -> None:
    log_path = _versioned_shadow_read_dedicated_log_path()
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as log_file:
            log_file.write(f"{event_line}\n")
    except Exception:
        # Diagnostico em modo sombra nunca deve bloquear o fluxo operacional.
        try:
            logger.warning(
                "event=versioned_resolver_shadow_read_sink_error log_path=%s reason=write_failed",
                log_path,
            )
        except Exception:
            pass

def maybe_run_versioned_resolver_shadow_read(
    conn,
    *,
    origin: str,
    aluno_id,
    atividade_id_legacy,
    req_id=None,
):
    if not is_versioned_resolver_shadow_read_enabled():
        return None

    try:
        event_timestamp = datetime.datetime.now().isoformat(timespec="microseconds")
    except Exception:
        event_timestamp = None

    try:
        result = resolver_service.resolver_versao_por_aluno(
            conn,
            aluno_id=aluno_id,
            atividade_id_legacy=atividade_id_legacy,
            strict_legacy_scope=True,
        )
    except Exception as exc:
        try:
            exc_type = type(exc).__name__
        except Exception:
            exc_type = "Exception"
        try:
            exc_message = str(exc)
        except Exception:
            exc_message = ""
        try:
            exc_traceback = traceback.format_exc()
        except Exception:
            exc_traceback = ""
        event_line = _build_versioned_shadow_read_event_line(
            origin=origin,
            req_id=req_id,
            aluno_id=aluno_id,
            atividade_id_legacy=atividade_id_legacy,
            status="error",
            atividade_versao_id=None,
            codigo_normativo=None,
            eixo=None,
            warnings=[],
            reason="resolver_exception",
            timestamp=event_timestamp,
            exception_type=exc_type,
            exception_message=exc_message,
            exception_traceback=exc_traceback,
        )
        _append_versioned_shadow_read_event_line(event_line)
        try:
            logger.exception(event_line)
        except Exception:
            pass
        return None

    event_line = _build_versioned_shadow_read_event_line(
        origin=origin,
        req_id=req_id,
        aluno_id=aluno_id,
        atividade_id_legacy=atividade_id_legacy,
        status=result.get("status"),
        atividade_versao_id=result.get("atividade_versao_id"),
        codigo_normativo=result.get("codigo_normativo"),
        eixo=result.get("eixo"),
        warnings=result.get("warnings") or [],
        reason=result.get("reason"),
        timestamp=event_timestamp,
    )
    _append_versioned_shadow_read_event_line(event_line)
    try:
        logger.info(event_line)
    except Exception:
        pass
    return result

def _normalize_shadow_read_scalar(value):
    text = str(value or "").strip()
    if not text or text.lower() in {"null", "none"}:
        return None
    return text

def _normalize_shadow_read_int(value):
    scalar = _normalize_shadow_read_scalar(value)
    if scalar is None:
        return None
    try:
        return int(scalar)
    except Exception:
        return None

def _parse_shadow_read_warnings(raw_warnings) -> list[str]:
    scalar = _normalize_shadow_read_scalar(raw_warnings)
    if not scalar:
        return []

    try:
        parsed = json.loads(scalar)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    except Exception:
        pass

    compact = scalar.strip()
    if compact.startswith("[") and compact.endswith("]"):
        compact = compact[1:-1].strip()
    if not compact:
        return []

    return [
        piece.strip().strip("\"'")
        for piece in compact.split(",")
        if piece.strip().strip("\"'")
    ]

def _parse_versioned_shadow_read_event_line(line: str):
    marker = "event=versioned_resolver_shadow_read"
    if marker not in line:
        return None

    payload = line[line.index("event="):].strip()
    token_pairs: dict[str, str] = {}
    for match in re.finditer(r"(\w+)=((?:(?!\s\w+=).)*)", payload):
        token_pairs[match.group(1)] = match.group(2).strip()

    if token_pairs.get("event") != "versioned_resolver_shadow_read":
        return None

    origin = _normalize_shadow_read_scalar(token_pairs.get("origin"))
    status = _normalize_shadow_read_scalar(token_pairs.get("status"))
    if not origin or not status:
        # Linha incompleta/malformada: ignora sem falhar endpoint.
        return None

    warnings = _parse_shadow_read_warnings(token_pairs.get("warnings"))

    exception_message = None
    exception_message_b64 = _normalize_shadow_read_scalar(
        token_pairs.get("exception_message_b64")
    )
    if exception_message_b64:
        try:
            exception_message = base64.b64decode(
                exception_message_b64.encode("ascii")
            ).decode("utf-8")
        except Exception:
            exception_message = None

    exception_traceback = None
    exception_traceback_b64 = _normalize_shadow_read_scalar(
        token_pairs.get("exception_traceback_b64")
    )
    if exception_traceback_b64:
        try:
            exception_traceback = base64.b64decode(
                exception_traceback_b64.encode("ascii")
            ).decode("utf-8")
        except Exception:
            exception_traceback = None

    return {
        "origin": origin,
        "req_id": _normalize_shadow_read_int(token_pairs.get("req_id")),
        "aluno_id": _normalize_shadow_read_int(token_pairs.get("aluno_id")),
        "atividade_id_legacy": _normalize_shadow_read_int(token_pairs.get("atividade_id_legacy")),
        "status": status,
        "atividade_versao_id": _normalize_shadow_read_int(token_pairs.get("atividade_versao_id")),
        "codigo_normativo": _normalize_shadow_read_scalar(token_pairs.get("codigo_normativo")),
        "eixo": _normalize_shadow_read_scalar(token_pairs.get("eixo")),
        "warnings": warnings,
        "has_warnings": bool(warnings),
        "reason": _normalize_shadow_read_scalar(token_pairs.get("reason")),
        "timestamp": _normalize_shadow_read_scalar(token_pairs.get("timestamp")),
        "exception_type": _normalize_shadow_read_scalar(token_pairs.get("exception_type")),
        "exception_message": exception_message,
        "exception_traceback": exception_traceback,
    }

def _collect_versioned_shadow_read_log_paths() -> list[str]:
    dedicated_path = os.path.abspath(_versioned_shadow_read_dedicated_log_path())
    base_paths: list[str] = [dedicated_path]
    for handler in logger.handlers:
        handler_path = getattr(handler, "baseFilename", None)
        if handler_path:
            base_paths.append(os.path.abspath(handler_path))

    base_paths.append(os.path.join(os.fspath(PROJECT_ROOT), "logs", "app.log"))

    dedup_base_paths: list[str] = []
    seen: set[str] = set()
    for candidate in base_paths:
        normalized = os.path.abspath(candidate)
        if normalized in seen:
            continue
        seen.add(normalized)
        dedup_base_paths.append(normalized)

    # Mantém ordem cronológica aproximada: rotacionado imediato antes do log atual.
    expanded_paths: list[str] = []
    for base_path in dedup_base_paths:
        if os.path.abspath(base_path) != dedicated_path:
            expanded_paths.append(f"{base_path}.1")
        expanded_paths.append(base_path)
    return expanded_paths

def _resolve_versioned_shadow_read_log_sources() -> dict[str, object]:
    dedicated_path = os.path.abspath(_versioned_shadow_read_dedicated_log_path())
    candidate_paths = _collect_versioned_shadow_read_log_paths()
    dedicated_exists = os.path.exists(dedicated_path)

    if dedicated_exists:
        return {
            "source_mode": "dedicated",
            "dedicated_path": dedicated_path,
            "dedicated_exists": True,
            "paths_to_read": [dedicated_path],
            "candidate_paths": candidate_paths,
        }

    fallback_paths = [
        os.path.abspath(path)
        for path in candidate_paths
        if os.path.abspath(path) != dedicated_path
    ]
    if not fallback_paths:
        fallback_paths = [dedicated_path]

    return {
        "source_mode": "fallback_app_log",
        "dedicated_path": dedicated_path,
        "dedicated_exists": False,
        "paths_to_read": fallback_paths,
        "candidate_paths": candidate_paths,
    }

def _shadow_read_event_dedup_key(event: dict[str, object]) -> tuple[object, ...]:
    return (
        event.get("origin"),
        event.get("req_id"),
        event.get("aluno_id"),
        event.get("atividade_id_legacy"),
        event.get("status"),
        event.get("atividade_versao_id"),
        event.get("codigo_normativo"),
        event.get("eixo"),
        event.get("reason"),
    )

def _parse_shadow_read_bool_filter(raw_value):
    text = str(raw_value or "").strip().lower()
    if not text:
        return None
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None

def _shadow_read_event_matches_filters(event, filters: dict[str, object]) -> bool:
    origin = filters.get("origin")
    if origin and event.get("origin") != origin:
        return False

    status = filters.get("status")
    if status and event.get("status") != status:
        return False

    codigo_normativo = filters.get("codigo_normativo")
    if codigo_normativo and event.get("codigo_normativo") != codigo_normativo:
        return False

    eixo = filters.get("eixo")
    if eixo and event.get("eixo") != eixo:
        return False

    aluno_id = filters.get("aluno_id")
    if aluno_id is not None and event.get("aluno_id") != aluno_id:
        return False

    atividade_id_legacy = filters.get("atividade_id_legacy")
    if atividade_id_legacy is not None and event.get("atividade_id_legacy") != atividade_id_legacy:
        return False

    has_warnings = filters.get("has_warnings")
    if has_warnings is not None and bool(event.get("has_warnings")) != has_warnings:
        return False

    return True

def _read_versioned_shadow_read_events(
    *,
    limit: int,
    filters: dict[str, object],
    source_info: dict[str, object] | None = None,
):
    events_raw: list[dict[str, object]] = []
    effective_source_info = source_info or _resolve_versioned_shadow_read_log_sources()
    log_paths = [str(path) for path in effective_source_info.get("paths_to_read", [])]
    found_any_log_file = False

    for log_path in log_paths:
        if not os.path.exists(log_path):
            continue
        found_any_log_file = True
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as log_file:
                for line in log_file:
                    event = _parse_versioned_shadow_read_event_line(line)
                    if not event:
                        continue
                    if _shadow_read_event_matches_filters(event, filters):
                        events_raw.append(event)
        except Exception:
            # Diagnóstico é melhor-esforço e jamais deve quebrar o endpoint.
            continue

    raw_count = len(events_raw)
    events_desc = list(reversed(events_raw))
    deduped_events: list[dict[str, object]] = []
    seen_keys: set[tuple[object, ...]] = set()
    for event in events_desc:
        dedup_key = _shadow_read_event_dedup_key(event)
        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)
        deduped_events.append(event)

    deduplicated_count = raw_count - len(deduped_events)
    return (
        deduped_events[:limit],
        (not found_any_log_file),
        raw_count,
        deduplicated_count,
        str(effective_source_info.get("source_mode") or "fallback_app_log"),
        log_paths,
    )

__all__ = [
    "is_versioned_resolver_shadow_read_enabled",
    "maybe_run_versioned_resolver_shadow_read",
]
