from __future__ import annotations

import logging

from flask import Blueprint, jsonify, make_response, render_template, request

from app.auth import admin_required
from app.db import get_db_connection
from app.versioning import resolver as resolver_service
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
                   m.status
              FROM turmas t
              LEFT JOIN matrizes_atividades m ON m.id = t.matriz_id
          ORDER BY COALESCE(t.codigo, t.nome, '')
            """
        ).fetchall()
    ]

# "Sem matriz" is a Turma state the administrator chooses, not a lookup error.
_TURMA_SEM_MATRIZ = "turma has no matrix"


def _readable_listing(listing: dict[str, object]) -> dict[str, object]:
    """The resolver's listing when it names something to read; otherwise its reason as a LookupError.

    The resolver reports an identifier that names no Turma or Matriz as a
    status, never as an exception. A Turma without a linked Matriz is read: its
    listing is empty (``matriz`` None, no activities).
    """
    if listing["status"] == "resolved" or listing.get("reason") == _TURMA_SEM_MATRIZ:
        return listing
    if listing.get("reason") == "turma not found":
        raise LookupError("Turma não encontrada para leitura diagnóstica.")
    raise LookupError("Matriz não encontrada para leitura diagnóstica.")


def _consulta_diagnostica(conn) -> tuple[dict[str, object], dict[str, object] | None]:
    """The query of both diagnostic routes: ``(consulta, listing)``.

    No identifier is the index (``listing`` None). Precedence: turma_id, then
    turma_codigo, then matriz_id. An identifier that names no Turma or Matriz
    raises LookupError, which both routes answer with 404.
    """
    turma_id = request.args.get("turma_id", type=int)
    matriz_id = request.args.get("matriz_id", type=int)
    turma_codigo = (request.args.get("turma_codigo") or "").strip()

    if turma_id:
        consulta = {"modo": "turma", "turma_id": turma_id}
    elif turma_codigo:
        turma = conn.execute("SELECT id FROM turmas WHERE codigo = ?", (turma_codigo,)).fetchone()
        if not turma:
            raise LookupError("Turma não encontrada para leitura diagnóstica.")
        consulta = {"modo": "turma_codigo", "turma_codigo": turma_codigo, "turma_id": turma["id"]}
    elif matriz_id:
        listing = resolver_service.listar_atividades_versionadas_por_matriz(conn, matriz_id)
        return {"modo": "matriz", "matriz_id": matriz_id}, _readable_listing(listing)
    else:
        return {"modo": "indice"}, None

    listing = _readable_listing(
        resolver_service.listar_atividades_versionadas_por_turma(conn, consulta["turma_id"])
    )
    consulta["matriz_id"] = listing["matriz"]["id"] if listing["matriz"] else None
    return consulta, listing


@admin_required
def admin_diagnostico_atividades_versionadas():
    conn = get_db_connection()

    try:
        consulta, payload = _consulta_diagnostica(conn)
        if payload is not None:
            payload["consulta"] = consulta
            return jsonify({"ok": True, **payload})

        turmas_disponiveis = _diagnostico_versionado_turmas_disponiveis(conn)
        return jsonify(
            {
                "ok": True,
                "consulta": consulta,
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
def admin_diagnostico_atividades_versionadas_view():
    conn = get_db_connection()
    status_code = 200
    payload = None
    consulta = {"modo": "indice"}
    message = "Informe turma_id, turma_codigo ou matriz_id para carregar a visualização diagnóstica."

    try:
        consulta, payload = _consulta_diagnostica(conn)
        if payload is not None and payload.get("reason") == _TURMA_SEM_MATRIZ:
            turma = payload["turma"]
            message = f"Turma {turma['codigo'] or turma['nome']}: sem matriz vinculada."
            payload = None
        elif payload is not None:
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
            lookup_failed=status_code != 200,
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
    ),
)


__all__ = [
    "LEGACY_ROUTE_SPECS",
    "admin_diagnostico_atividades_versionadas",
    "admin_diagnostico_atividades_versionadas_view",
    "bp_admin_versioning",
]
