from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from flask import Blueprint, jsonify, make_response, render_template, request, url_for

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
_TURMA_NAO_ENCONTRADA = "Turma não encontrada para leitura diagnóstica."
_MATRIZ_NAO_ENCONTRADA = "Matriz não encontrada para leitura diagnóstica."

# ASCII digits only, as app.student_matrix.parse_submitted_matriz_id reads a
# submitted Matrix: int() would also accept "1_0", Unicode digits and "+1".
_QUERY_ID_RE = re.compile(r"-?[0-9]+")

# A form field drops CR and LF from its value and the HTML parser turns NUL
# into U+FFFD. The page shows these as U+FFFD itself, so what the form sends
# back is what the page shows: still the same Turma code, or still invalid.
_NOT_A_FIELD_CHARACTER = str.maketrans({"\r": "\ufffd", "\n": "\ufffd", "\x00": "\ufffd"})


@dataclass(frozen=True)
class _Leitura:
    """The one reading of a diagnostic query, shared by both routes and the page.

    Every parameter follows one policy: surrounding whitespace is trimmed, a
    blank occurrence supplies nothing, and the first nonblank occurrence is the
    value. Every nonblank ``turma_id`` and ``matriz_id`` occurrence must be an
    ASCII decimal integer a row id can hold, other than zero (never generated
    by either engine, never resolved here); the first one that is not rejects
    the query (``turma_id`` is checked first), whatever precedence would select.
    A negative id is a stored id like any other.

    ``campos`` is each parameter as the page's form fields and JSON link carry
    it: the value read (an id in canonical decimal), the first rejected
    occurrence of a rejected id, or blank. Read again, it selects the same
    resource or fails in the same way, so the page, its link and its
    unmodified form never diverge.
    """

    turma_id: int | None
    turma_codigo: str | None
    matriz_id: int | None
    rejeicao: str | None
    campos: dict[str, str]


def _nonblank_values(name: str) -> list[str]:
    return [value for value in (raw.strip() for raw in request.args.getlist(name)) if value]


def _is_query_id(value: str) -> bool:
    if _QUERY_ID_RE.fullmatch(value) is None:
        return False
    try:
        identifier = int(value)
    except ValueError:
        # Python caps decimal-to-int conversion; no row id is that long.
        return False
    return identifier != 0 and resolver_service._is_row_id(identifier)


def _ler_consulta() -> _Leitura:
    ids: dict[str, int | None] = {}
    campos: dict[str, str] = {}
    rejeicao = None
    for name, not_found in (("turma_id", _TURMA_NAO_ENCONTRADA), ("matriz_id", _MATRIZ_NAO_ENCONTRADA)):
        values = _nonblank_values(name)
        rejected = next((value for value in values if not _is_query_id(value)), None)
        if rejected is not None:
            rejeicao = rejeicao or not_found
            ids[name] = None
            campos[name] = rejected.translate(_NOT_A_FIELD_CHARACTER)
        else:
            ids[name] = int(values[0]) if values else None
            campos[name] = str(ids[name]) if values else ""
    codigos = _nonblank_values("turma_codigo")
    turma_codigo = codigos[0] if codigos else None
    campos["turma_codigo"] = (turma_codigo or "").translate(_NOT_A_FIELD_CHARACTER)
    return _Leitura(ids["turma_id"], turma_codigo, ids["matriz_id"], rejeicao, campos)


def _json_url(leitura: _Leitura) -> str:
    """The JSON route for the same reading: the page's "Abrir JSON diagnóstico" link."""
    return url_for(
        "admin_diagnostico_atividades_versionadas",
        **{
            name: leitura.campos[name]
            for name in ("turma_id", "turma_codigo", "matriz_id")
            if leitura.campos[name]
        },
    )


def _readable_listing(listing: dict[str, object]) -> dict[str, object]:
    """The resolver's listing when it names something to read; otherwise its reason as a LookupError.

    The resolver reports an identifier that names no Turma or Matriz as a
    status, never as an exception. A Turma without a linked Matriz is read: its
    listing is empty (``matriz`` None, no activities).
    """
    if listing["status"] == "resolved" or listing.get("reason") == _TURMA_SEM_MATRIZ:
        return listing
    if listing.get("reason") == "turma not found":
        raise LookupError(_TURMA_NAO_ENCONTRADA)
    raise LookupError(_MATRIZ_NAO_ENCONTRADA)


def _consulta_diagnostica(conn, leitura: _Leitura) -> tuple[dict[str, object], dict[str, object] | None]:
    """The lookup of both diagnostic routes: ``(consulta, listing)``.

    No identifier is the index (``listing`` None). Precedence: turma_id, then
    turma_codigo, then matriz_id; only the selected one is looked up. A
    rejected reading, or a selected identifier that names no Turma or Matriz,
    raises LookupError, which both routes answer with 404.
    """
    if leitura.rejeicao is not None:
        raise LookupError(leitura.rejeicao)

    if leitura.turma_id is not None:
        consulta = {"modo": "turma", "turma_id": leitura.turma_id}
    elif leitura.turma_codigo is not None:
        turma = conn.execute("SELECT id FROM turmas WHERE codigo = ?", (leitura.turma_codigo,)).fetchone()
        if not turma:
            raise LookupError(_TURMA_NAO_ENCONTRADA)
        consulta = {"modo": "turma_codigo", "turma_codigo": leitura.turma_codigo, "turma_id": turma["id"]}
    elif leitura.matriz_id is not None:
        listing = resolver_service.listar_atividades_versionadas_por_matriz(conn, leitura.matriz_id)
        return {"modo": "matriz", "matriz_id": leitura.matriz_id}, _readable_listing(listing)
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
        consulta, payload = _consulta_diagnostica(conn, _ler_consulta())
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
    leitura = _ler_consulta()
    status_code = 200
    payload = None
    consulta = {"modo": "indice"}
    message = "Informe turma_id, turma_codigo ou matriz_id para carregar a visualização diagnóstica."

    try:
        consulta, payload = _consulta_diagnostica(conn, leitura)
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
            campos=leitura.campos,
            json_url=_json_url(leitura),
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
