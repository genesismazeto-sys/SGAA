from __future__ import annotations

import datetime
import json
import logging
import os

from app.versioning import resolver as resolver_service


logger = logging.getLogger("main")


def is_versioned_requisicao_snapshot_display_enabled() -> bool:
    return str(os.getenv("SGAA_VERSIONED_REQUISICAO_SNAPSHOT_DISPLAY", "0")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

def is_versioned_requisicao_snapshot_write_enabled() -> bool:
    return str(os.getenv("SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE", "0")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

def _load_versioned_requisicao_snapshot_rule_row(
    conn,
    *,
    atividade_versao_id,
    atividade_id_legacy,
):
    return conn.execute(
        """
        SELECT av.id AS atividade_versao_id,
               av.atividade_base_id,
               av.codigo_normativo,
               av.eixo,
               av.grupo,
               av.ch_por_evento,
               av.limite_semestre,
               av.limite_total,
               av.status AS versao_status,
               ab.nome_conceito AS atividade_base_nome,
               COALESCE(
                   a.nome,
                   (
                       SELECT a2.nome
                         FROM atividade_legacy_map alm2
                         JOIN atividades a2 ON a2.id = alm2.atividade_id_legacy
                        WHERE alm2.atividade_base_id = av.atividade_base_id
                     ORDER BY alm2.atividade_id_legacy
                        LIMIT 1
                   ),
                   ab.nome_conceito
               ) AS nome_exibivel,
               COALESCE(
                   a.nome,
                   (
                       SELECT a2.nome
                         FROM atividade_legacy_map alm2
                         JOIN atividades a2 ON a2.id = alm2.atividade_id_legacy
                        WHERE alm2.atividade_base_id = av.atividade_base_id
                     ORDER BY alm2.atividade_id_legacy
                        LIMIT 1
                   )
               ) AS nome_legacy,
               COALESCE(
                   a.tipo_atividade,
                   (
                       SELECT a2.tipo_atividade
                         FROM atividade_legacy_map alm2
                         JOIN atividades a2 ON a2.id = alm2.atividade_id_legacy
                        WHERE alm2.atividade_base_id = av.atividade_base_id
                     ORDER BY alm2.atividade_id_legacy
                        LIMIT 1
                   )
               ) AS tipo_atividade_legacy
          FROM atividade_versao av
          JOIN atividade_base ab ON ab.id = av.atividade_base_id
          LEFT JOIN atividade_legacy_map alm
            ON alm.atividade_base_id = av.atividade_base_id
           AND alm.atividade_id_legacy = ?
          LEFT JOIN atividades a ON a.id = alm.atividade_id_legacy
         WHERE av.id = ?
        """,
        (atividade_id_legacy, atividade_versao_id),
    ).fetchone()

def _build_versioned_requisicao_snapshot_payload(
    *,
    flow_origin: str,
    atividade_id_legacy,
    resolver_result,
    rule_row,
) -> dict[str, object]:
    snapshot_written_at = (
        datetime.datetime.now(datetime.timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    return {
        "atividade_base_id": resolver_result.get("atividade_base_id"),
        "atividade_id_legacy": atividade_id_legacy,
        "atividade_versao_id": resolver_result.get("atividade_versao_id"),
        "ch_por_evento": rule_row["ch_por_evento"],
        "codigo_normativo": resolver_result.get("codigo_normativo") or rule_row["codigo_normativo"],
        "eixo": resolver_result.get("eixo") or rule_row["eixo"],
        "flow_origin": flow_origin,
        "grupo": rule_row["grupo"],
        "legacy_scope_ok": resolver_result.get("legacy_scope_ok"),
        "limite_semestre": rule_row["limite_semestre"],
        "limite_total": rule_row["limite_total"],
        "matriz_id_efetiva": resolver_result.get("matriz_id_efetiva"),
        "nome_exibivel": rule_row["nome_exibivel"],
        "nome_legacy": rule_row["nome_legacy"],
        "resolver_status": resolver_result.get("status"),
        "resolver_warnings": list(resolver_result.get("warnings") or []),
        "schema_version": "d6.4.0-v1",
        "snapshot_written_at": snapshot_written_at,
        "tipo_atividade_legacy": rule_row["tipo_atividade_legacy"],
        "versao_status": rule_row["versao_status"],
    }

def _get_turma_explicit_matriz_id_for_snapshot(conn, aluno_id: int | None) -> int | None:
    """Returns turma.matriz_id only when explicitly set for the aluno's turma.

    No fallback to preferred matriz for the curso — that is a heuristic that must
    not silently determine which version gets stamped on a requisição operacional.
    Used exclusively by the versioned snapshot writer; not by legacy scoping.
    """
    if not aluno_id:
        return None
    row = conn.execute(
        """
        SELECT t.matriz_id
          FROM alunos a
          LEFT JOIN turmas t ON t.id = a.turma_id
         WHERE a.id = ?
        """,
        (aluno_id,),
    ).fetchone()
    if not row:
        return None
    return row["matriz_id"]

def maybe_write_versioned_requisicao_snapshot(
    conn,
    *,
    flow_origin: str,
    req_id,
    aluno_id,
    atividade_id_legacy,
):
    if not is_versioned_requisicao_snapshot_write_enabled():
        return None

    # Strict check: turma must have an explicit matriz_id for the versioned stamp.
    # Fallback to preferred matriz is deliberately excluded — it is a heuristic and
    # must not silently determine which version gets stamped on a requisição.
    explicit_matriz_id = _get_turma_explicit_matriz_id_for_snapshot(conn, aluno_id)
    if not explicit_matriz_id:
        try:
            logger.info(
                "event=versioned_requisicao_snapshot_skip origin=%s req_id=%s aluno_id=%s "
                "atividade_id_legacy=%s status=turma_without_explicit_matrix",
                flow_origin,
                req_id,
                aluno_id,
                atividade_id_legacy,
            )
        except Exception:
            pass
        return None

    try:
        resolver_result = resolver_service.resolver_versao_por_aluno(
            conn,
            aluno_id=aluno_id,
            atividade_id_legacy=atividade_id_legacy,
            strict_legacy_scope=True,
        )
    except Exception:
        try:
            logger.exception(
                "event=versioned_requisicao_snapshot_exception origin=%s req_id=%s aluno_id=%s atividade_id_legacy=%s",
                flow_origin,
                req_id,
                aluno_id,
                atividade_id_legacy,
            )
        except Exception:
            pass
        return None

    if resolver_result.get("status") != "resolved":
        try:
            logger.warning(
                "event=versioned_requisicao_snapshot_skip origin=%s req_id=%s aluno_id=%s atividade_id_legacy=%s status=%s reason=%s",
                flow_origin,
                req_id,
                aluno_id,
                atividade_id_legacy,
                resolver_result.get("status"),
                resolver_result.get("reason"),
            )
        except Exception:
            pass
        return resolver_result

    atividade_versao_id = resolver_result.get("atividade_versao_id")
    if not atividade_versao_id:
        try:
            logger.warning(
                "event=versioned_requisicao_snapshot_skip origin=%s req_id=%s aluno_id=%s atividade_id_legacy=%s status=resolved reason=missing_atividade_versao_id",
                flow_origin,
                req_id,
                aluno_id,
                atividade_id_legacy,
            )
        except Exception:
            pass
        return resolver_result

    rule_row = _load_versioned_requisicao_snapshot_rule_row(
        conn,
        atividade_versao_id=atividade_versao_id,
        atividade_id_legacy=atividade_id_legacy,
    )
    if not rule_row:
        try:
            logger.warning(
                "event=versioned_requisicao_snapshot_skip origin=%s req_id=%s aluno_id=%s atividade_id_legacy=%s status=resolved reason=missing_rule_row",
                flow_origin,
                req_id,
                aluno_id,
                atividade_id_legacy,
            )
        except Exception:
            pass
        return resolver_result

    payload = _build_versioned_requisicao_snapshot_payload(
        flow_origin=flow_origin,
        atividade_id_legacy=atividade_id_legacy,
        resolver_result=resolver_result,
        rule_row=rule_row,
    )
    snapshot_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    conn.execute(
        """
        UPDATE requisicoes
           SET atividade_versao_id = ?,
               regra_snapshot_json = ?,
               codigo_normativo_snapshot = ?
         WHERE id = ?
        """,
        (
            atividade_versao_id,
            snapshot_json,
            resolver_result.get("codigo_normativo") or rule_row["codigo_normativo"],
            req_id,
        ),
    )
    try:
        logger.info(
            "event=versioned_requisicao_snapshot_written origin=%s req_id=%s aluno_id=%s atividade_id_legacy=%s atividade_versao_id=%s codigo_normativo=%s",
            flow_origin,
            req_id,
            aluno_id,
            atividade_id_legacy,
            atividade_versao_id,
            resolver_result.get("codigo_normativo") or rule_row["codigo_normativo"],
        )
    except Exception:
        pass
    return resolver_result


_ADMIN_REQUISICAO_SNAPSHOT_DIAGNOSTIC_FIELDS = (
    "codigo_normativo",
    "eixo",
    "grupo",
    "ch_por_evento",
    "limite_semestre",
    "limite_total",
    "nome_exibivel",
    "nome_legacy",
    "tipo_atividade_legacy",
    "flow_origin",
    "snapshot_written_at",
    "resolver_status",
    "resolver_warnings",
    "legacy_scope_ok",
    "atividade_id_legacy",
    "atividade_base_id",
    "matriz_id_efetiva",
    "versao_status",
)


def _snapshot_diagnostic_row_value(row, key):
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get(key)
    try:
        return row[key]
    except Exception:
        return None

def _normalize_snapshot_diagnostic_scalar(value):
    if value is None:
        return None
    if isinstance(value, (dict, list, tuple, set)):
        return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value

def _has_versioned_requisicao_snapshot(row) -> bool:
    atividade_versao_id = _snapshot_diagnostic_row_value(row, "atividade_versao_id")
    codigo_normativo_snapshot = _snapshot_diagnostic_row_value(row, "codigo_normativo_snapshot")
    if atividade_versao_id not in (None, ""):
        return True
    return bool(str(codigo_normativo_snapshot or "").strip())

def _build_admin_requisicao_snapshot_diagnostic(row) -> dict[str, object] | None:
    if not _has_versioned_requisicao_snapshot(row):
        return None

    atividade_versao_id = _snapshot_diagnostic_row_value(row, "atividade_versao_id")
    codigo_normativo_snapshot = str(
        _snapshot_diagnostic_row_value(row, "codigo_normativo_snapshot") or ""
    ).strip()
    raw_snapshot = _snapshot_diagnostic_row_value(row, "regra_snapshot_json")

    diagnostic: dict[str, object] = {
        "snapshot_versionado_presente": True,
        "diagnostico_disponivel": False,
    }
    if atividade_versao_id not in (None, ""):
        diagnostic["atividade_versao_id"] = atividade_versao_id
    if codigo_normativo_snapshot:
        diagnostic["codigo_normativo_snapshot"] = codigo_normativo_snapshot

    if raw_snapshot is None:
        return diagnostic
    raw_snapshot = str(raw_snapshot).strip()
    if not raw_snapshot:
        return diagnostic

    try:
        payload = json.loads(raw_snapshot)
    except (TypeError, ValueError, json.JSONDecodeError):
        return diagnostic

    if not isinstance(payload, dict):
        return diagnostic

    diagnostic["diagnostico_disponivel"] = True
    parsed_atividade_versao_id = payload.get("atividade_versao_id")
    if "atividade_versao_id" not in diagnostic and parsed_atividade_versao_id not in (None, ""):
        diagnostic["atividade_versao_id"] = parsed_atividade_versao_id

    for key in _ADMIN_REQUISICAO_SNAPSHOT_DIAGNOSTIC_FIELDS:
        value = payload.get(key)
        if key == "resolver_warnings":
            if value is None:
                continue
            if isinstance(value, list):
                warnings = [str(item).strip() for item in value if str(item).strip()]
            else:
                normalized = str(value).strip()
                warnings = [normalized] if normalized else []
            diagnostic[key] = warnings
            continue
        value = _normalize_snapshot_diagnostic_scalar(value)
        if value is None:
            continue
        diagnostic[key] = value

    return diagnostic

__all__ = [
    "is_versioned_requisicao_snapshot_display_enabled",
    "is_versioned_requisicao_snapshot_write_enabled",
    "maybe_write_versioned_requisicao_snapshot",
]
