from __future__ import annotations

import logging
import os

from flask import Blueprint, jsonify, make_response, render_template, request

from app.auth import admin_required
from app.db import get_db_connection
from app.versioning import resolver as resolver_service
from app.versioning import shadow_reads
from app.views.admin import LegacyRouteSpec, configure_legacy_routes


logger = logging.getLogger("main")


def _diagnostico_versionado_turmas_disponiveis(conn) -> list[dict[str, object]]:
    return [
        {
            "id": row["turma_id"],
            "codigo": row["turma_codigo"],
            "nome": row["turma_nome"],
            "matriz_id": row["matriz_id"],
            "matriz_label": (
                resolver_service._versioning_matriz_option_label(row)
                if row["matriz_id"] is not None
                else None
            ),
            "periodo_label": resolver_service._versioning_periodo_label_for_turma_row(row),
        }
        for row in conn.execute(
            """
            SELECT t.id AS turma_id,
                   t.codigo AS turma_codigo,
                   t.nome AS turma_nome,
                   t.matriz_id,
                   t.ano_inicio,
                   t.semestre_inicio,
                   t.ano_fim,
                   t.semestre_fim,
                   m.nome,
                   m.versao,
                   m.status
              FROM turmas t
              LEFT JOIN matrizes_atividades m ON m.id = t.matriz_id
          ORDER BY COALESCE(t.codigo, t.nome, '')
            """
        ).fetchall()
    ]

@admin_required
def admin_diagnostico_atividades_versionadas():
    conn = get_db_connection()
    turma_id = request.args.get("turma_id", type=int)
    matriz_id = request.args.get("matriz_id", type=int)
    turma_codigo = (request.args.get("turma_codigo") or "").strip()

    try:
        if turma_id:
            payload = resolver_service.listar_atividades_versionadas_por_turma(conn, turma_id)
            payload["consulta"] = {"modo": "turma", "turma_id": turma_id, "matriz_id": payload["matriz"]["id"]}
            return jsonify({"ok": True, **payload})

        if turma_codigo:
            turma = conn.execute("SELECT id FROM turmas WHERE codigo = ?", (turma_codigo,)).fetchone()
            if not turma:
                raise LookupError("Turma não encontrada para leitura diagnóstica.")
            payload = resolver_service.listar_atividades_versionadas_por_turma(conn, turma["id"])
            payload["consulta"] = {
                "modo": "turma_codigo",
                "turma_codigo": turma_codigo,
                "turma_id": turma["id"],
                "matriz_id": payload["matriz"]["id"],
            }
            return jsonify({"ok": True, **payload})

        if matriz_id:
            payload = resolver_service.listar_atividades_versionadas_por_matriz(conn, matriz_id)
            payload["consulta"] = {"modo": "matriz", "matriz_id": matriz_id}
            return jsonify({"ok": True, **payload})

        turmas_disponiveis = _diagnostico_versionado_turmas_disponiveis(conn)
        return jsonify(
            {
                "ok": True,
                "consulta": {"modo": "indice"},
                "message": "Informe turma_id, turma_codigo ou matriz_id para consultar o modelo versionado em paralelo.",
                "turmas_disponiveis": turmas_disponiveis,
            }
        )
    except LookupError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 404
    except RuntimeError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 503
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400

@admin_required
def admin_diagnostico_versioned_shadow_reads():
    origin = (request.args.get("origin") or "").strip() or None
    status = (request.args.get("status") or "").strip() or None
    codigo_normativo = (request.args.get("codigo_normativo") or "").strip() or None
    eixo = (request.args.get("eixo") or "").strip() or None
    aluno_id = request.args.get("aluno_id", type=int)
    atividade_id_legacy = request.args.get("atividade_id_legacy", type=int)
    has_warnings = shadow_reads._parse_shadow_read_bool_filter(request.args.get("has_warnings"))

    raw_limit = request.args.get("limit", type=int)
    limit = raw_limit if raw_limit is not None else 100
    if limit <= 0:
        limit = 100
    limit = min(limit, 500)

    filters = {
        "origin": origin,
        "status": status,
        "aluno_id": aluno_id,
        "atividade_id_legacy": atividade_id_legacy,
        "codigo_normativo": codigo_normativo,
        "eixo": eixo,
        "has_warnings": has_warnings,
    }

    source_info = shadow_reads._resolve_versioned_shadow_read_log_sources()
    dedicated_log_path = str(source_info.get("dedicated_path") or os.path.abspath(shadow_reads._versioned_shadow_read_dedicated_log_path()))
    dedicated_log_exists = bool(source_info.get("dedicated_exists"))
    log_paths = [str(path) for path in source_info.get("paths_to_read", [])]
    source_mode = str(source_info.get("source_mode") or "fallback_app_log")
    logger_level = logging.getLevelName(logger.getEffectiveLevel())
    events, log_not_found, raw_count, deduplicated_count, read_source_mode, read_paths = shadow_reads._read_versioned_shadow_read_events(
        limit=limit,
        filters=filters,
        source_info=source_info,
    )
    if read_source_mode:
        source_mode = read_source_mode
    if read_paths:
        log_paths = [str(path) for path in read_paths]
    return jsonify(
        {
            "diagnostico": "versioned_shadow_reads",
            "source": "log",
            "source_mode": source_mode,
            "count": len(events),
            "raw_count": raw_count,
            "deduplicated_count": deduplicated_count,
            "limit": limit,
            "filters": {key: value for key, value in filters.items() if value is not None},
            "log_not_found": log_not_found,
            "dedicated_log_path": dedicated_log_path,
            "dedicated_log_exists": dedicated_log_exists,
            "dedicated_log_in_paths": dedicated_log_path in set(log_paths),
            "log_paths": log_paths,
            "logger_level": logger_level,
            "handler_count": len(logger.handlers),
            "events": events,
        }
    )

@admin_required
def admin_diagnostico_atividades_versionadas_view():
    conn = get_db_connection()
    turma_id = request.args.get("turma_id", type=int)
    matriz_id = request.args.get("matriz_id", type=int)
    turma_codigo = (request.args.get("turma_codigo") or "").strip()
    status_code = 200
    payload = None
    consulta = {"modo": "indice"}
    message = "Informe turma_id, turma_codigo ou matriz_id para carregar a visualização diagnóstica."

    try:
        if turma_id:
            payload = resolver_service.listar_atividades_versionadas_por_turma(conn, turma_id)
            consulta = {"modo": "turma", "turma_id": turma_id, "matriz_id": payload["matriz"]["id"]}
            message = ""
        elif turma_codigo:
            turma = conn.execute("SELECT id FROM turmas WHERE codigo = ?", (turma_codigo,)).fetchone()
            if not turma:
                raise LookupError("Turma não encontrada para leitura diagnóstica.")
            payload = resolver_service.listar_atividades_versionadas_por_turma(conn, turma["id"])
            consulta = {
                "modo": "turma_codigo",
                "turma_codigo": turma_codigo,
                "turma_id": turma["id"],
                "matriz_id": payload["matriz"]["id"],
            }
            message = ""
        elif matriz_id:
            payload = resolver_service.listar_atividades_versionadas_por_matriz(conn, matriz_id)
            consulta = {"modo": "matriz", "matriz_id": matriz_id}
            message = ""
    except LookupError as exc:
        status_code = 404
        message = str(exc)
    except RuntimeError as exc:
        status_code = 503
        message = str(exc)
    except ValueError as exc:
        status_code = 400
        message = str(exc)

    response = make_response(
        render_template(
            "admin_diagnostico_atividades_versionadas_view.html",
            payload=payload,
            consulta=consulta,
            message=message,
            turmas_disponiveis=_diagnostico_versionado_turmas_disponiveis(conn),
        ),
        status_code,
    )
    return response

bp_admin_versioning = Blueprint("admin_versioning_blueprint", __name__)

LEGACY_ROUTE_SPECS = configure_legacy_routes(
    bp_admin_versioning,
    (
        LegacyRouteSpec(
            "/admin/diagnostico/atividades-versionadas",
            "admin_diagnostico_atividades_versionadas",
            admin_diagnostico_atividades_versionadas,
            ("GET",),
        ),
        LegacyRouteSpec(
            "/admin/diagnostico/atividades-versionadas/view",
            "admin_diagnostico_atividades_versionadas_view",
            admin_diagnostico_atividades_versionadas_view,
            ("GET",),
        ),
        LegacyRouteSpec(
            "/admin/diagnostico/versioned-shadow-reads",
            "admin_diagnostico_versioned_shadow_reads",
            admin_diagnostico_versioned_shadow_reads,
            ("GET",),
        ),
    ),
)


__all__ = [
    "LEGACY_ROUTE_SPECS",
    "admin_diagnostico_atividades_versionadas",
    "admin_diagnostico_atividades_versionadas_view",
    "admin_diagnostico_versioned_shadow_reads",
    "bp_admin_versioning",
]
