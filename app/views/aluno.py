from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import sqlite3
from typing import Any

from flask import (
    Blueprint,
    abort,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)

from app.academics import DEFAULT_CURSO_TOTAL_HORAS_AAC, DEFAULT_CURSO_TOTAL_HORAS_AEU
from app.admin_alerts import list_active_admin_alertas
from app.admin_files import get_admin_arquivo
from app.auth import aluno_required
from app.db_maintenance import (
    ensure_admin_arquivos_table,
    ensure_requisicao_arquivos_table,
    ensure_reportes_table,
    ensure_usuario_profile_schema,
)
from app.matrix_scope import get_effective_matriz_for_turma
from app.versioning.request_history import (
    APPROVED_STATUSES,
    SnapshotProcessingAuthority,
    filter_historical_request_rows,
    list_approved_request_history,
    list_exact_matrix_activity_catalogue,
    read_historical_request,
    read_request_presentation,
)
from app.presentation import format_date_ptbr
from app.reporting import REPORTE_CATEGORY_OPTIONS
from app.requisition_policy import can_student_delete_requisition, can_student_edit_requisition
from app.security.passwords import hash_password
from app.db import get_db_connection
from app.student_documents import (
    remove_student_document,
    resolve_student_document_path,
    save_student_document,
)
from app.uploads import ALLOWED_ATTACHMENTS, ALLOWED_REPORTE_SCREENSHOTS
from app.web.filters import (
    get_date_range_query,
    get_multi_query_values,
    get_number_range_query,
    get_text_query_value,
)
from app.web.pagination import get_pagination, wants_pagination
from app.versioning import (
    prepare_versioned_requisicao_snapshot,
    RequisicaoSnapshotError,
)
from utils.messages import flash

# UT-6: os helpers de alerta de atualização passaram a ter dono canônico em
# app/requisitions.py; o nome da função é mantido por contrato de teste.
def _get_main_helpers():
    from app.requisitions import (
        get_student_request_update_alert,
        mark_student_request_updates_seen,
    )

    return {
        "get_student_request_update_alert": get_student_request_update_alert,
        "mark_student_request_updates_seen": mark_student_request_updates_seen,
    }


bp_aluno = Blueprint("aluno", __name__)

AAC_ACTIVITY_TYPE = "Acadêmica Complementar"
EXT_ACTIVITY_TYPE = "Extensão Universitária"


def _aluno_url(endpoint_name: str, **values):
    return url_for(f"aluno.{endpoint_name}", **values)


def _is_allowed_attachment(filename: str, allowed: set[str]) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed


def _coerce_aluno_snapshot_scalar(value: Any) -> str | None:
    """Converte um campo escalar do payload do snapshot em string segura.

    Aceita apenas tipos escalares (str/int/float); qualquer outro tipo
    (dict/list/tuple/set) é descartado para evitar vazamento de estrutura
    complexa para o template do aluno. Strings vazias viram None.
    """
    if value is None:
        return None
    if isinstance(value, (dict, list, tuple, set)):
        return None
    if isinstance(value, str):
        trimmed = value.strip()
        return trimmed or None
    return value


def _build_aluno_requisicao_snapshot_display(
    *,
    atividade_versao_id: Any,
    regra_snapshot_json: Any,
    versao_row: Any | None,
) -> dict[str, Any] | None:
    """Extrai um payload read-only de snapshot para o template do aluno.

    Retorna None quando não houver snapshot registrado. Quando o payload
    JSON for inválido, faz fallback silencioso usando apenas os campos
    disponíveis no banco, sem nunca lançar exceção.
    """
    has_atividade_versao_id = atividade_versao_id not in (None, "")
    if not has_atividade_versao_id:
        return None

    display: dict[str, Any] = {
        "snapshot_versionado_presente": True,
        "snapshot_vn": None,
        "snapshot_eixo": None,
        "snapshot_grupo": None,
        "snapshot_written_at": None,
        "snapshot_flow_origin": None,
    }

    raw_snapshot = regra_snapshot_json
    parsed: dict[str, Any] | None = None
    if raw_snapshot is not None:
        try:
            candidate = json.loads(str(raw_snapshot))
            if isinstance(candidate, dict):
                parsed = candidate
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed = None

    if parsed is not None:
        for key, target in (
            ("snapshot_eixo", "eixo"),
            ("snapshot_grupo", "grupo"),
            ("snapshot_written_at", "snapshot_written_at"),
            ("snapshot_flow_origin", "flow_origin"),
        ):
            display[key] = _coerce_aluno_snapshot_scalar(parsed.get(target))

        payload_vn = parsed.get("atividade_versao_numero")
        if payload_vn is not None:
            try:
                display["snapshot_vn"] = int(payload_vn)
            except (TypeError, ValueError):
                pass

    # Current catalogue data is only a corruption/legacy-display fallback. A
    # valid persisted snapshot always wins for historical presentation.
    if versao_row is not None:
        if display["snapshot_vn"] is None:
            numero_versao = versao_row["numero_versao"] if "numero_versao" in versao_row.keys() else None
            if numero_versao is not None:
                try:
                    display["snapshot_vn"] = int(numero_versao)
                except (TypeError, ValueError):
                    pass
        for key, source in (
            ("snapshot_eixo", "eixo"),
            ("snapshot_grupo", "grupo"),
        ):
            if display[key] is None and source in versao_row.keys():
                display[key] = _coerce_aluno_snapshot_scalar(versao_row[source])

    return display


def _get_aluno_scope(conn, usuario_id: int):
    return conn.execute(
        """
        SELECT a.id AS aluno_id,
               a.turma_id,
               t.curso_id AS turma_curso_id,
               t.matriz_id AS turma_matriz_id
          FROM alunos a
          LEFT JOIN turmas t ON t.id = a.turma_id
         WHERE a.usuario_id = ?
        """,
        (usuario_id,),
    ).fetchone()


def _get_effective_matriz_for_usuario(conn, usuario_id: int):
    aluno_scope = _get_aluno_scope(conn, usuario_id)
    if not aluno_scope:
        return None, None
    matriz = get_effective_matriz_for_turma(
        conn,
        aluno_scope["turma_curso_id"],
        aluno_scope["turma_matriz_id"],
    )
    return aluno_scope, matriz


def _list_atividades_for_usuario(
    conn,
    usuario_id: int,
    tipo_filtro: str,
    include_activity_id: int | None = None,
):
    aluno_scope, matriz = _get_effective_matriz_for_usuario(conn, usuario_id)
    if not aluno_scope:
        return None, None, []
    if not matriz:
        return aluno_scope, None, []

    atividades = list_exact_matrix_activity_catalogue(conn, matriz["id"])
    if tipo_filtro != "Todas":
        atividades = [
            atividade
            for atividade in atividades
            if atividade["tipo_atividade"] == tipo_filtro
        ]

    listed_ids = {atividade["id"] for atividade in atividades}
    if include_activity_id and include_activity_id not in listed_ids:
        current = conn.execute(
            """SELECT v.id, v.id AS atividade_versao_id, v.atividade_base_id,
                      b.nome_conceito AS nome,
                      CASE v.eixo WHEN 'AAC' THEN 'Acadêmica Complementar' ELSE 'Extensão Universitária' END AS tipo_atividade,
                      v.grupo, v.ch_por_evento,
                      v.limite_total AS limite_horas_total,
                      v.limite_semestre AS limite_horas_semestral,
                      v.documentos_json,
                      (v.limite_total IS NOT NULL OR v.limite_semestre IS NOT NULL) AS tem_limitacao,
                      CASE WHEN v.limite_semestre IS NOT NULL THEN 'semestral' ELSE 'total' END AS tipo_limitacao,
                      COALESCE(v.limite_semestre,v.limite_total) AS limite_horas
                 FROM atividade_versao v JOIN atividade_base b ON b.id=v.atividade_base_id
                WHERE v.id=?""", (include_activity_id,)
        ).fetchone()
        if current and (
            tipo_filtro == "Todas" or current["tipo_atividade"] == tipo_filtro
        ):
            atividades.append({key: current[key] for key in current.keys()})

    atividades.sort(
        key=lambda atividade: (
            str(atividade.get("tipo_atividade") or ""),
            str(atividade.get("grupo") or ""),
            str(atividade.get("nome") or ""),
        )
    )
    return aluno_scope, matriz, atividades


def _is_activity_allowed_for_usuario(
    conn,
    usuario_id: int,
    atividade_id: int,
    current_activity_id: int | None = None,
) -> bool:
    _, matriz = _get_effective_matriz_for_usuario(conn, usuario_id)
    if not matriz:
        return False
    if current_activity_id and atividade_id == current_activity_id:
        return True
    row = conn.execute(
        "SELECT 1 FROM matriz_atividade_versao_item WHERE matriz_id = ? AND atividade_versao_id = ?",
        (matriz["id"], atividade_id),
    ).fetchone()
    return row is not None


def _parse_iso_date(value: Any) -> datetime.date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    candidate = raw[:10]
    try:
        return datetime.datetime.strptime(candidate, "%Y-%m-%d").date()
    except ValueError:
        return None


def _get_semestre(data: datetime.date) -> str:
    ano = data.year
    semestre = 1 if data.month <= 6 else 2
    return f"{ano}/{semestre}"


def _semestre_sort_key(label: str) -> tuple[int, int]:
    ano_raw, _, semestre_raw = str(label or "").partition("/")
    try:
        return int(ano_raw), int(semestre_raw)
    except ValueError:
        return (9999, 9)


def _extract_grupo_numero(grupo: str | None) -> int | None:
    raw = str(grupo or "").strip()
    if not raw:
        return None
    match = re.search(r"\d+", raw)
    if not match:
        return None
    try:
        return int(match.group())
    except ValueError:
        return None


def _format_hours_number(value: Any) -> str:
    try:
        numeric = float(value or 0)
    except (TypeError, ValueError):
        return "0"
    if numeric.is_integer():
        return str(int(numeric))
    return f"{numeric:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def _format_hours_label(value: Any) -> str:
    return f"{_format_hours_number(value)}h"


def _format_progresso_grupo(tipo_atividade: str | None, grupo: str | None) -> str:
    if (tipo_atividade or "").strip() != AAC_ACTIVITY_TYPE:
        return "-"
    grupo_numero = _extract_grupo_numero(grupo)
    if grupo_numero is None:
        return "-"
    return str(grupo_numero)


def _format_progresso_limite(row) -> str:
    if not bool(row["tem_limitacao"]):
        return "-"
    labels = []
    if row["limite_horas_semestral"] is not None:
        labels.append(f"{_format_hours_number(row['limite_horas_semestral'])}h/sem")
    if row["limite_horas_total"] is not None:
        labels.append(f"{_format_hours_number(row['limite_horas_total'])}h total")
    return "; ".join(labels) or "-"


def _build_progress_activity(row) -> dict[str, Any]:
    grupo_numero = _extract_grupo_numero(row["grupo"])
    limite_total = row["limite_horas_total"]
    limite_semestral = row["limite_horas_semestral"]
    try:
        limite_total_num = float(limite_total) if limite_total is not None else None
    except (TypeError, ValueError):
        limite_total_num = None
    try:
        limite_semestral_num = float(limite_semestral) if limite_semestral is not None else None
    except (TypeError, ValueError):
        limite_semestral_num = None
    return {
        "atividade_id": row["id"],
        "nome": row["nome"],
        "tipo_atividade": row["tipo_atividade"],
        "grupo": _format_progresso_grupo(row["tipo_atividade"], row["grupo"]),
        "limite": _format_progresso_limite(row),
        "tem_limitacao": bool(row["tem_limitacao"]),
        "tipo_limitacao": row["tipo_limitacao"],
        "limite_horas_total": limite_total_num,
        "limite_horas_semestral": limite_semestral_num,
        "semestres": {},
        "semestres_fmt": {},
        "semestres_limitados": {},
        "total": 0.0,
        "total_fmt": _format_hours_label(0),
        "total_limitado": False,
        "_tipo_ordem": 0 if row["tipo_atividade"] == AAC_ACTIVITY_TYPE else 1,
        "_grupo_ordem": grupo_numero if grupo_numero is not None else 9999,
        "_nome_ordem": str(row["nome"] or "").casefold(),
    }


def _build_aluno_progresso_payload(conn, usuario_id: int) -> dict[str, Any] | None:
    aluno_scope, matriz = _get_effective_matriz_for_usuario(conn, usuario_id)
    if not aluno_scope:
        return None

    aluno_id = aluno_scope["aluno_id"]
    atividades_por_id: dict[object, dict[str, Any]] = {}

    def _version_progress_identity(version_id, fallback):
        # Catalogue and history are projections of the same exact semantic
        # unit. Different versions of one base intentionally remain distinct.
        return ("version", int(version_id)) if version_id is not None else fallback

    atividades_catalogo = []
    tipos_matriz: set[str] = set()
    if matriz:
        atividades_catalogo = list_exact_matrix_activity_catalogue(conn, matriz["id"])
        tipos_matriz = {str(row["tipo_atividade"] or "").strip() for row in atividades_catalogo if row["tipo_atividade"]}

    for row in atividades_catalogo or []:
        key = _version_progress_identity(
            row["atividade_versao_id"],
            ("unversioned-catalogue", row["id"]),
        )
        atividades_por_id[key] = _build_progress_activity(row)

    historical_rows = conn.execute(
        """
        SELECT r.*, student.turma_id
          FROM requisicoes r
          LEFT JOIN alunos student ON student.id = r.aluno_id
         WHERE r.aluno_id = ?
      ORDER BY r.id
        """,
        (aluno_id,),
    ).fetchall()
    for raw_row in historical_rows:
        row = read_request_presentation(raw_row)
        key = _version_progress_identity(
            row.atividade_versao_id,
            ("unversioned-history", row.request_id),
        )
        if key in atividades_por_id:
            continue
        atividades_por_id[key] = _build_progress_activity(
            {
                "id": row.atividade_versao_id,
                "nome": row.nome,
                "tipo_atividade": row.tipo_atividade,
                "grupo": row.grupo,
                "tem_limitacao": row.limite_total is not None
                or row.limite_semestre is not None,
                "tipo_limitacao": (
                    "semestral" if row.limite_semestre is not None else "total"
                ),
                "limite_horas_total": row.limite_total,
                "limite_horas_semestral": row.limite_semestre,
            }
        )

    semestre_atual = _semestre_sort_key(_get_semestre(datetime.date.today()))
    semestres_detectados: set[str] = set()
    requisicoes_aprovadas = list_approved_request_history(conn, aluno_id=aluno_id)
    for row in requisicoes_aprovadas:
        data_evento = _parse_iso_date(row.data_evento)
        if not data_evento:
            continue
        semestre = _get_semestre(data_evento)
        if _semestre_sort_key(semestre) > semestre_atual:
            continue
        horas_numericas = row.approved_hours
        key = _version_progress_identity(
            row.atividade_versao_id,
            ("unversioned-history", row.request_id),
        )
        atividade = atividades_por_id.get(key)
        if atividade is None:
            rule_row = {
                "id": row.atividade_versao_id,
                "nome": row.nome,
                "tipo_atividade": row.tipo_atividade,
                "grupo": row.grupo,
                "tem_limitacao": row.limite_total is not None
                or row.limite_semestre is not None,
                "tipo_limitacao": (
                    "semestral" if row.limite_semestre is not None else "total"
                ),
                "limite_horas_total": row.limite_total,
                "limite_horas_semestral": row.limite_semestre,
            }
            atividade = _build_progress_activity(rule_row)
            atividades_por_id[key] = atividade
        semestres_detectados.add(semestre)
        atividade["semestres"][semestre] = round(atividade["semestres"].get(semestre, 0.0) + horas_numericas, 2)

    semestres = sorted(semestres_detectados, key=_semestre_sort_key)
    atividades = []
    for atividade in atividades_por_id.values():
        semestre_values = {
            semestre: round(float(atividade["semestres"].get(semestre, 0.0) or 0.0), 2)
            for semestre in semestres
        }
        total = round(sum(semestre_values.values()), 2)
        semestres_limitados = {}
        if atividade["tem_limitacao"] and atividade["limite_horas_semestral"] is not None:
            limite_semestral = float(atividade["limite_horas_semestral"])
            semestres_limitados = {
                semestre: (valor >= limite_semestral and limite_semestral > 0)
                for semestre, valor in semestre_values.items()
            }
        else:
            semestres_limitados = {semestre: False for semestre in semestres}
        atividade["semestres"] = semestre_values
        atividade["semestres_fmt"] = {
            semestre: _format_hours_label(valor)
            for semestre, valor in semestre_values.items()
        }
        atividade["semestres_limitados"] = semestres_limitados
        atividade["total"] = total
        atividade["total_fmt"] = _format_hours_label(total)
        atividade["total_limitado"] = bool(
            atividade["tem_limitacao"]
            and atividade["limite_horas_total"] is not None
            and atividade["limite_horas_total"] > 0
            and total >= float(atividade["limite_horas_total"])
        )
        atividades.append(atividade)

    atividades.sort(
        key=lambda atividade: (
            atividade["_tipo_ordem"],
            atividade["_grupo_ordem"],
            atividade["_nome_ordem"],
            atividade["atividade_id"],
        )
    )
    for atividade in atividades:
        atividade.pop("_tipo_ordem", None)
        atividade.pop("_grupo_ordem", None)
        atividade.pop("_nome_ordem", None)

    tipos_visiveis = {str(atividade["tipo_atividade"] or "").strip() for atividade in atividades if atividade["tipo_atividade"]}
    return {
        "semestres": semestres,
        "atividades": atividades,
        "has_extensao_na_matriz": EXT_ACTIVITY_TYPE in tipos_matriz,
        "has_aac_visivel": AAC_ACTIVITY_TYPE in tipos_visiveis,
        "has_extensao_visivel": EXT_ACTIVITY_TYPE in tipos_visiveis,
    }


@bp_aluno.route("/aluno/dashboard")
@aluno_required
def aluno_dashboard():
    helpers = _get_main_helpers()
    get_student_request_update_alert = helpers["get_student_request_update_alert"]
    mark_student_request_updates_seen = helpers["mark_student_request_updates_seen"]
    conn = get_db_connection()
    usuario_id = session.get("user_id")

    aluno_info = conn.execute(
        """
        SELECT a.*, t.id AS turma_rel_id, t.curso_id AS turma_curso_id, t.matriz_id AS turma_matriz_id,
               c.nome AS curso_nome, c.codigo AS curso_codigo,
               m.nome AS matriz_nome,
               m.horas_aac_obrigatorias, m.horas_extensao_obrigatorias
          FROM alunos a
          LEFT JOIN turmas t ON t.id = a.turma_id
          LEFT JOIN cursos c ON c.id = t.curso_id
          LEFT JOIN matrizes_atividades m ON m.id = t.matriz_id
         WHERE a.usuario_id = ?
        """,
        (usuario_id,),
    ).fetchone()
    if not aluno_info:
        flash("Dados do aluno não encontrados.", "error")
        return redirect(url_for("login"))

    matriz_aluno = get_effective_matriz_for_turma(conn, aluno_info["turma_curso_id"], aluno_info["turma_matriz_id"])
    meta_horas_academicas = (
        matriz_aluno["horas_aac_obrigatorias"]
        if matriz_aluno and matriz_aluno["horas_aac_obrigatorias"] is not None
        else None
    )
    meta_horas_extensao = (
        matriz_aluno["horas_extensao_obrigatorias"]
        if matriz_aluno and matriz_aluno["horas_extensao_obrigatorias"] is not None
        else None
    )
    meta_total_horas_fmt = (
        _format_hours_number(meta_horas_academicas + meta_horas_extensao)
        if meta_horas_academicas is not None and meta_horas_extensao is not None
        else "-"
    )

    requisicoes_rows = conn.execute(
        """
        SELECT r.*, a.turma_id
        FROM requisicoes r
        LEFT JOIN alunos a ON a.id = r.aluno_id
        WHERE r.aluno_id = ?
        ORDER BY r.data_solicitacao DESC
        """,
        (aluno_info["id"],),
    ).fetchall()

    requisicoes = []
    for row in requisicoes_rows:
        item = {key: row[key] for key in row.keys()}
        history = read_request_presentation(row)
        item["atividade_nome"] = history.nome
        item["tipo_atividade"] = history.tipo_atividade
        item["grupo"] = history.grupo
        item["horas_aprovadas"] = history.approved_hours
        requisicoes.append(item)

    approved = [
        req for req in requisicoes if req["status"] in APPROVED_STATUSES
    ]
    totals_by_type = {}
    totals_by_group = {}
    for req in approved:
        totals_by_type[req["tipo_atividade"]] = (
            totals_by_type.get(req["tipo_atividade"], 0.0) + req["horas_aprovadas"]
        )
        group_key = (req["grupo"], req["tipo_atividade"])
        totals_by_group[group_key] = (
            totals_by_group.get(group_key, 0.0) + req["horas_aprovadas"]
        )
    horas_por_tipo = [
        {"tipo_atividade": key, "total_horas": value}
        for key, value in totals_by_type.items()
    ]
    horas_por_grupo = [
        {"grupo": key[0], "tipo_atividade": key[1], "total_horas": value}
        for key, value in totals_by_group.items()
    ]

    atividades_matriz = (
        list_exact_matrix_activity_catalogue(conn, matriz_aluno["id"])
        if matriz_aluno
        else []
    )
    limites_por_grupo = {
        row["grupo"]: row["limite_horas"]
        for row in atividades_matriz
    }

    total_horas_academicas = sum(
        req["horas_aprovadas"]
        for req in requisicoes
        if req["status"] in ("Deferida", "Deferida Parcialmente") and req["tipo_atividade"] == "Acadêmica Complementar"
    )
    total_horas_extensao = sum(
        req["horas_aprovadas"]
        for req in requisicoes
        if req["status"] in ("Deferida", "Deferida Parcialmente") and req["tipo_atividade"] == "Extensão Universitária"
    )

    total_reqs = len(requisicoes)
    pendentes = sum(1 for req in requisicoes if req["status"] == "Pendente")
    pendentes_acad = sum(1 for req in requisicoes if req["status"] == "Pendente" and req["tipo_atividade"] == "Acadêmica Complementar")
    pendentes_ext = sum(1 for req in requisicoes if req["status"] == "Pendente" and req["tipo_atividade"] == "Extensão Universitária")

    hoje = datetime.date.today()
    corrigiveis_lista = []
    for req in requisicoes:
        if req["status"] != "Indeferida":
            continue
        dp_raw = req["data_processamento"]
        if not dp_raw:
            continue
        try:
            if len(dp_raw) > 10:
                dp_date = datetime.datetime.strptime(dp_raw[:19], "%Y-%m-%d %H:%M:%S").date()
            else:
                dp_date = datetime.datetime.strptime(dp_raw, "%Y-%m-%d").date()
        except Exception:
            try:
                dp_date = datetime.datetime.strptime(dp_raw[:10], "%Y-%m-%d").date()
            except Exception:
                dp_date = None
        if not dp_date:
            continue
        dias_passados = (hoje - dp_date).days
        dias_restantes = 30 - dias_passados
        if dias_restantes <= 0:
            continue
        data_expira = (dp_date + datetime.timedelta(days=30)).strftime("%d/%m/%Y")
        corrigiveis_lista.append(
            {
                "id": req["id"],
                "nome": req["atividade_nome"],
                "tipo_atividade": req["tipo_atividade"],
                "dias_restantes": dias_restantes,
                "data_expira": data_expira,
            }
        )

    corrigiveis = len(corrigiveis_lista)
    deferidas = sum(1 for req in requisicoes if req["status"] in ("Deferida", "Deferida Parcialmente"))
    indeferidas = sum(1 for req in requisicoes if req["status"] == "Indeferida")
    horas_deferidas_total = sum(req["horas_aprovadas"] for req in requisicoes if req["status"] in ("Deferida", "Deferida Parcialmente"))
    aprov_pct = (deferidas / total_reqs * 100.0) if total_reqs else 0.0
    pend_pct = (pendentes / total_reqs * 100.0) if total_reqs else 0.0

    corrigiveis_acad = sorted(
        [item for item in corrigiveis_lista if item["tipo_atividade"] == "Acadêmica Complementar"],
        key=lambda item: item["dias_restantes"],
    )
    corrigiveis_ext = sorted(
        [item for item in corrigiveis_lista if item["tipo_atividade"] == "Extensão Universitária"],
        key=lambda item: item["dias_restantes"],
    )

    periodicidades_por_grupo = {}
    try:
        for row in atividades_matriz:
            if row["tipo_limitacao"] == "semestral":
                periodicidades_por_grupo[row["grupo"]] = "semestral"
    except Exception:
        pass

    limitacoes_acad = []
    limitacoes_ext = []
    for row in horas_por_grupo or []:
        limite = limites_por_grupo.get(row["grupo"])
        total_horas = float(row["total_horas"] or 0)
        if not limite or limite <= 0 or total_horas <= 0:
            continue
        pct = int((total_horas * 100) // limite) if limite > 0 else 0
        item = {
            "grupo": row["grupo"],
            "tipo_atividade": row["tipo_atividade"],
            "consumido": total_horas,
            "limite": limite,
            "consumido_fmt": _format_hours_number(total_horas),
            "limite_fmt": _format_hours_number(limite),
            "periodicidade": periodicidades_por_grupo.get(row["grupo"]),
            "pct": min(100, pct),
        }
        if row["tipo_atividade"] == AAC_ACTIVITY_TYPE:
            limitacoes_acad.append(item)
        elif row["tipo_atividade"] == EXT_ACTIVITY_TYPE:
            limitacoes_ext.append(item)

    requisicoes_recentes_acad = []
    requisicoes_recentes_ext = []
    for req in requisicoes[:8]:
        item = {
            "id": req["id"],
            "atividade_nome": req["atividade_nome"],
            "data_evento_fmt": format_date_ptbr(req["data_evento"]),
            "horas_solicitadas": _format_hours_number(req["horas_solicitadas"]),
            "horas_deferidas_fmt": _format_hours_number(req["horas_aprovadas"]),
            "status": req["status"],
        }
        if req["tipo_atividade"] == AAC_ACTIVITY_TYPE:
            requisicoes_recentes_acad.append(item)
        elif req["tipo_atividade"] == EXT_ACTIVITY_TYPE:
            requisicoes_recentes_ext.append(item)

    requisicoes_recentes = requisicoes[:8]
    alertas_ativos = list(list_active_admin_alertas(conn))
    update_alert = get_student_request_update_alert(conn, aluno_info["id"])
    if update_alert:
        alertas_ativos.insert(0, update_alert["alerta"])
        mark_student_request_updates_seen(conn, update_alert["requisicao_ids"])
        conn.commit()

    return render_template(
        "aluno_dashboard.html",
        aluno=aluno_info,
        requisicoes=requisicoes,
        requisicoes_recentes=requisicoes_recentes,
        horas_por_tipo=horas_por_tipo,
        horas_por_grupo=horas_por_grupo,
        limites_por_grupo=limites_por_grupo,
        total_horas_academicas=total_horas_academicas,
        total_horas_extensao=total_horas_extensao,
        total_horas_academicas_fmt=_format_hours_number(total_horas_academicas),
        total_horas_extensao_fmt=_format_hours_number(total_horas_extensao),
         meta_horas_academicas_fmt=(
             _format_hours_number(meta_horas_academicas)
             if meta_horas_academicas is not None
             else "-"
         ),
         meta_horas_extensao_fmt=(
             _format_hours_number(meta_horas_extensao)
             if meta_horas_extensao is not None
             else "-"
         ),
         meta_total_horas_fmt=meta_total_horas_fmt,
        meta_horas_academicas=meta_horas_academicas,
        meta_horas_extensao=meta_horas_extensao,
        total_reqs=total_reqs,
        pendentes=pendentes,
        corrigiveis=corrigiveis,
        pendentes_acad=pendentes_acad,
        pendentes_ext=pendentes_ext,
        deferidas=deferidas,
        indeferidas=indeferidas,
        horas_deferidas_total=horas_deferidas_total,
        aprov_pct=aprov_pct,
        pend_pct=pend_pct,
        corrigiveis_acad=corrigiveis_acad,
        corrigiveis_ext=corrigiveis_ext,
        periodicidades_por_grupo=periodicidades_por_grupo,
        limitacoes_acad=limitacoes_acad,
        limitacoes_ext=limitacoes_ext,
        requisicoes_recentes_acad=requisicoes_recentes_acad,
        requisicoes_recentes_ext=requisicoes_recentes_ext,
        alertas_ativos=alertas_ativos,
    )


@bp_aluno.route("/aluno/progresso")
@aluno_required
def aluno_progresso():
    conn = get_db_connection()
    usuario_id = session.get("user_id")
    payload = _build_aluno_progresso_payload(conn, usuario_id)
    if not payload:
        flash("Dados do aluno não encontrados.", "error")
        return redirect(url_for("login"))

    wants_json = (request.args.get("format") or "").strip().lower() == "json"
    accepts_json = request.accept_mimetypes["application/json"] > request.accept_mimetypes["text/html"]
    if wants_json or accepts_json:
        return jsonify(payload)

    atividades = payload["atividades"]
    tipo_map = {
        "aac": AAC_ACTIVITY_TYPE,
        "academica": AAC_ACTIVITY_TYPE,
        "academicas": AAC_ACTIVITY_TYPE,
        "ext": EXT_ACTIVITY_TYPE,
        "extensao": EXT_ACTIVITY_TYPE,
        "extensão": EXT_ACTIVITY_TYPE,
    }
    requested_type = tipo_map.get((request.args.get("tipo") or "").strip().lower())
    tipos_visiveis = {atividade["tipo_atividade"] for atividade in atividades}
    if requested_type not in tipos_visiveis:
        requested_type = AAC_ACTIVITY_TYPE if AAC_ACTIVITY_TYPE in tipos_visiveis else None
    if requested_type is None and EXT_ACTIVITY_TYPE in tipos_visiveis:
        requested_type = EXT_ACTIVITY_TYPE
    if requested_type is None:
        requested_type = AAC_ACTIVITY_TYPE

    atividades_exibidas = [
        atividade for atividade in atividades if atividade["tipo_atividade"] == requested_type
    ]
    aac_atividades_count = sum(
        1 for atividade in atividades if atividade["tipo_atividade"] == AAC_ACTIVITY_TYPE
    )
    aeu_atividades_count = sum(
        1 for atividade in atividades if atividade["tipo_atividade"] == EXT_ACTIVITY_TYPE
    )
    mostrar_menu_tipos = bool(
        payload["has_extensao_na_matriz"]
        and payload["has_aac_visivel"]
        and payload["has_extensao_visivel"]
    )
    tipo_options = [
        {"value": "aac", "label": "Acadêmicas Complementares", "tipo": AAC_ACTIVITY_TYPE},
        {"value": "extensao", "label": "Extensão Universitária", "tipo": EXT_ACTIVITY_TYPE},
    ]
    tipo_option_map = {item["tipo"]: item for item in tipo_options}
    current_option = tipo_option_map.get(requested_type, tipo_options[0])
    descricao_por_tipo = {
        AAC_ACTIVITY_TYPE: "Atividades AAC aplicáveis à matriz da turma e histórico já utilizado pelo aluno.",
        EXT_ACTIVITY_TYPE: "Atividades de extensão aplicáveis à matriz da turma e histórico preservado do aluno.",
    }

    return render_template(
        "aluno_progresso.html",
        semestres=payload["semestres"],
        atividades=atividades,
        atividades_exibidas=atividades_exibidas,
        mostrar_menu_tipos=mostrar_menu_tipos,
        tipo_progresso_atual=requested_type,
        tipo_progresso_valor=current_option["value"],
        tipo_progresso_titulo=current_option["label"],
        tipo_progresso_descricao=descricao_por_tipo.get(requested_type, descricao_por_tipo[AAC_ACTIVITY_TYPE]),
        tipo_progresso_opcoes=tipo_options,
        aac_atividades_count=aac_atividades_count,
        aeu_atividades_count=aeu_atividades_count,
    )


@bp_aluno.route("/aluno/meus_dados", methods=["GET", "POST"])
@aluno_required
def aluno_meus_dados():
    conn = get_db_connection()
    ensure_usuario_profile_schema(conn)
    usuario_id = session["user_id"]
    aluno = conn.execute(
        """
        SELECT a.id AS aluno_id,
               u.nome,
               u.email,
               a.matricula,
               a.turma_id,
               a.foto_perfil,
               COALESCE(t.codigo, t.nome, '') AS turma
          FROM usuarios u
          JOIN alunos a ON u.id = a.usuario_id
          LEFT JOIN turmas t ON t.id = a.turma_id
         WHERE u.id = ?
        """,
        (usuario_id,),
    ).fetchone()

    if request.method == "POST":
        nome = request.form["nome"]
        email = request.form["email"]
        matricula = request.form["matricula"]
        turma_id_raw = request.form.get("turma_id")
        senha = request.form.get("senha")

        # Valida turma_id: deve ser inteiro positivo correspondente a uma turma existente.
        # Mant\u00e9m a turma atual quando nenhum valor v\u00e1lido for enviado.
        current_turma_id = aluno["turma_id"] if aluno and "turma_id" in aluno.keys() else None
        turma_id = current_turma_id
        if turma_id_raw not in (None, "", "0"):
            try:
                candidate = int(turma_id_raw)
                if candidate > 0:
                    exists = conn.execute(
                        "SELECT 1 FROM turmas WHERE id = ? AND status = 'Ativa'",
                        (candidate,),
                    ).fetchone()
                    if exists:
                        turma_id = candidate
                    else:
                        flash("Turma selecionada inv\u00e1lida; mantida a anterior.", "warning")
            except (TypeError, ValueError):
                flash("Turma selecionada inv\u00e1lida; mantida a anterior.", "warning")

        try:
            if senha:
                hashed_password = hash_password(senha)
                conn.execute(
                    "UPDATE usuarios SET nome = ?, email = ?, senha = ? WHERE id = ?",
                    (nome, email, hashed_password, usuario_id),
                )
            else:
                conn.execute(
                    "UPDATE usuarios SET nome = ?, email = ? WHERE id = ?",
                    (nome, email, usuario_id),
                )
            session["user_name"] = nome

            conn.execute(
                "UPDATE alunos SET nome = ?, matricula = ?, email = ?, turma_id = ? WHERE usuario_id = ?",
                (nome, matricula, email, turma_id, usuario_id),
            )

            remove_foto = request.form.get("remove_foto") == "1"
            foto_file = request.files.get("foto_perfil")
            if remove_foto:
                conn.execute("UPDATE alunos SET foto_perfil = NULL WHERE usuario_id = ?", (usuario_id,))
                session.pop("foto_perfil", None)
            elif foto_file and foto_file.filename:
                try:
                    foto_rel = save_student_document(
                        foto_file,
                        {"png", "jpg", "jpeg"},
                        root_folder=current_app.config["DOCUMENTOS_ALUNOS_FOLDER"],
                        student_id=aluno["aluno_id"],
                        student_name=nome,
                        category="perfil",
                        prefix="foto-perfil",
                    )
                    if foto_rel:
                        conn.execute(
                            "UPDATE alunos SET foto_perfil = ? WHERE usuario_id = ?",
                            (foto_rel, usuario_id),
                        )
                        session["foto_perfil"] = foto_rel
                except ValueError:
                    flash("Foto inválida. Use PNG ou JPG.", "error")
            conn.commit()
            flash("Seus dados foram atualizados com sucesso.", "success")
            return redirect(_aluno_url("aluno_dashboard"))
        except sqlite3.IntegrityError as exc:
            if "UNIQUE constraint failed: usuarios.email" in str(exc):
                flash("Erro: Já existe outro usuário com este e-mail.", "error")
            elif "UNIQUE constraint failed: alunos.matricula" in str(exc):
                flash("Erro: Já existe outro aluno com esta matrícula.", "error")
            else:
                flash(f"Erro ao atualizar dados: {exc}", "error")
        except Exception as exc:
            flash(f"Erro inesperado ao atualizar dados: {exc}", "error")

    turmas = conn.execute(
        """
        SELECT t.id, COALESCE(t.codigo, t.nome) AS nome
          FROM turmas t
         WHERE t.status='Ativa'
      ORDER BY t.ano_inicio DESC, t.semestre_inicio DESC, nome
        """
    ).fetchall()
    return render_template(
        "aluno_meus_dados.html",
        base_template="base_aluno.html",
        profile=aluno,
        show_student_fields=True,
        cancel_url=_aluno_url("aluno_dashboard"),
        turmas=turmas,
    )


@bp_aluno.route("/aluno/arquivos")
@aluno_required
def aluno_arquivos():
    page, per_page, offset = get_pagination(default_per_page=25)
    q = (request.args.get("q") or "").strip()
    titulo_filter = get_text_query_value("titulo")
    descricao_filter = get_text_query_value("descricao")
    data_upload_min, data_upload_max = get_date_range_query("data_upload")
    tipo_values = [
        str(value or "").strip().lower()
        for value in get_multi_query_values("tipo")
        if str(value or "").strip()
    ]
    sort_field = (request.args.get("s") or "").strip().lower()
    sort_dir = (request.args.get("dir") or "asc").strip().lower()

    conn = get_db_connection()
    ensure_admin_arquivos_table(conn)
    arquivos = []
    rows = conn.execute(
        """
        SELECT id,
               titulo,
               descricao,
               filename,
               original_filename,
               COALESCE(strftime('%d/%m/%Y', criado_em), '-') AS data_upload,
               criado_em
          FROM admin_arquivos
         WHERE visivel = 1
      ORDER BY datetime(criado_em) DESC, id DESC
        """
    ).fetchall()

    tipos_disponiveis = set()
    for row in rows:
        original_filename = row["original_filename"] or row["filename"] or ""
        tipo = os.path.splitext(original_filename)[1].lstrip(".").upper() or "Arquivo"
        tipos_disponiveis.add(tipo)
        arquivos.append(
            {
                "id": row["id"],
                "titulo": row["titulo"],
                "descricao": row["descricao"],
                "filename": row["filename"],
                "original_filename": original_filename,
                "data_upload": row["data_upload"],
                "criado_em": row["criado_em"],
                "tipo": tipo,
            }
        )

    if q:
        q_norm = q.casefold()
        arquivos = [
            arquivo
            for arquivo in arquivos
            if q_norm in str(arquivo.get("titulo") or "").casefold()
            or q_norm in str(arquivo.get("descricao") or "").casefold()
            or q_norm in str(arquivo.get("original_filename") or "").casefold()
        ]

    if tipo_values:
        tipos_filtrados = set(tipo_values)
        arquivos = [
            arquivo
            for arquivo in arquivos
            if str(arquivo.get("tipo") or "").strip().lower() in tipos_filtrados
        ]

    if titulo_filter:
        filtro = titulo_filter.casefold()
        arquivos = [
            arquivo
            for arquivo in arquivos
            if filtro in str(arquivo.get("titulo") or "").casefold()
        ]

    if descricao_filter:
        filtro = descricao_filter.casefold()
        arquivos = [
            arquivo
            for arquivo in arquivos
            if filtro in str(arquivo.get("descricao") or "").casefold()
        ]

    if data_upload_min or data_upload_max:
        filtrados = []
        for arquivo in arquivos:
            created_date = str(arquivo.get("criado_em") or "")[:10]
            if data_upload_min and (not created_date or created_date < data_upload_min):
                continue
            if data_upload_max and (not created_date or created_date > data_upload_max):
                continue
            filtrados.append(arquivo)
        arquivos = filtrados

    sort_map = {
        "titulo": lambda arquivo: str(arquivo.get("titulo") or "").casefold(),
        "descricao": lambda arquivo: str(arquivo.get("descricao") or "").casefold(),
        "data_upload": lambda arquivo: str(arquivo.get("criado_em") or ""),
        "tipo": lambda arquivo: str(arquivo.get("tipo") or "").casefold(),
    }
    if sort_field in sort_map:
        arquivos.sort(key=sort_map[sort_field], reverse=(sort_dir == "desc"))

    total = len(arquivos)
    apply_limit = wants_pagination()
    if apply_limit:
        arquivos = arquivos[offset : offset + per_page]
    total_pages = (total + per_page - 1) // per_page if apply_limit and per_page else 1

    filter_schema = [
        {
            "param": "titulo",
            "label": "Título",
            "type": "text_contains",
            "placeholder": "Contém no título",
        },
        {
            "param": "descricao",
            "label": "Descrição",
            "type": "text_contains",
            "placeholder": "Contém na descrição",
        },
        {
            "param": "data_upload",
            "label": "Data de upload",
            "type": "date_range",
            "min_label": "De",
            "max_label": "Até",
        },
    ]
    if tipos_disponiveis:
        filter_schema.append(
            {
                "param": "tipo",
                "label": "Tipo",
                "type": "multi_select",
                "values": [{"value": tipo, "label": tipo} for tipo in sorted(tipos_disponiveis)],
            }
        )

    return render_template(
        "aluno_arquivos.html",
        arquivos=arquivos,
        filter_schema=filter_schema,
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages,
    )


@bp_aluno.route("/aluno/arquivos/ver/<int:arquivo_id>")
@aluno_required
def aluno_visualizar_arquivo(arquivo_id: int):
    conn = get_db_connection()
    arquivo = get_admin_arquivo(conn, arquivo_id)
    if not arquivo or not arquivo["visivel"]:
        flash("Arquivo não encontrado.", "error")
        return redirect(_aluno_url("aluno_arquivos"))
    return redirect(url_for("uploaded_file", filename=arquivo["filename"]))


@bp_aluno.route("/aluno/arquivos/download/<int:arquivo_id>")
@aluno_required
def aluno_baixar_arquivo(arquivo_id: int):
    conn = get_db_connection()
    arquivo = get_admin_arquivo(conn, arquivo_id)
    if not arquivo or not arquivo["visivel"]:
        flash("Arquivo não encontrado.", "error")
        return redirect(_aluno_url("aluno_arquivos"))

    safe_rel = os.path.normpath(arquivo["filename"]).lstrip("/")
    base = os.path.abspath(current_app.config["UPLOAD_FOLDER"])
    abs_path = os.path.abspath(os.path.join(base, safe_rel))
    if not abs_path.startswith(base):
        abort(403)

    rel_dir = os.path.dirname(safe_rel)
    rel_name = os.path.basename(safe_rel)
    resp = send_from_directory(
        os.path.join(current_app.config["UPLOAD_FOLDER"], rel_dir),
        rel_name,
        as_attachment=True,
        download_name=arquivo["original_filename"] or rel_name,
    )
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Cache-Control", "private, max-age=3600")
    return resp


@bp_aluno.route("/aluno/reportar", methods=["GET", "POST"])
@aluno_required
def aluno_reportar():
    screenshot_extensions = ALLOWED_REPORTE_SCREENSHOTS
    categoria_options = REPORTE_CATEGORY_OPTIONS

    conn = get_db_connection()
    ensure_reportes_table(conn)
    usuario_id = session.get("user_id")
    aluno = conn.execute(
        "SELECT id, nome, matricula FROM alunos WHERE usuario_id = ?",
        (usuario_id,),
    ).fetchone()
    if not aluno:
        flash("Dados do aluno não encontrados.", "error")
        return redirect(_aluno_url("aluno_dashboard"))

    form_data = {
        "categoria": categoria_options[0],
        "titulo": "",
        "descricao": "",
    }

    if request.method == "POST":
        categoria = (request.form.get("categoria") or "").strip()
        titulo = (request.form.get("titulo") or "").strip()
        descricao = (request.form.get("descricao") or "").strip()
        captura_tela = request.files.get("captura_tela")

        form_data = {
            "categoria": categoria or categoria_options[0],
            "titulo": titulo,
            "descricao": descricao,
        }

        if categoria not in categoria_options:
            categoria = categoria_options[0]

        if not titulo or not descricao:
            flash("Informe o título e descreva o problema encontrado.", "error")
        else:
            screenshot_filename = None
            if captura_tela and getattr(captura_tela, "filename", ""):
                try:
                    screenshot_filename = save_student_document(
                        captura_tela,
                        screenshot_extensions,
                        root_folder=current_app.config["DOCUMENTOS_ALUNOS_FOLDER"],
                        student_id=aluno["id"],
                        student_name=aluno["nome"],
                        category="reportes",
                        prefix=f"reporte{aluno['id']}",
                    )
                except ValueError:
                    flash("A captura deve estar em PNG, JPG, JPEG ou WEBP.", "error")
                    reportes_rows = conn.execute(
                        """
                        SELECT id, titulo, descricao, categoria, screenshot_filename, status, criado_em, atualizado_em
                          FROM reportes
                         WHERE aluno_id = ?
                      ORDER BY datetime(criado_em) DESC, id DESC
                        """,
                        (aluno["id"],),
                    ).fetchall()
                    reportes = [
                        {
                            "id": row["id"],
                            "titulo": row["titulo"],
                            "descricao": row["descricao"],
                            "categoria": row["categoria"],
                            "screenshot_filename": row["screenshot_filename"],
                            "status": row["status"],
                            "criado_em_fmt": format_date_ptbr(row["criado_em"]),
                            "atualizado_em_fmt": format_date_ptbr(row["atualizado_em"]),
                        }
                        for row in reportes_rows
                    ]
                    return render_template(
                        "aluno_reportar.html",
                        aluno=aluno,
                        form_data=form_data,
                        categoria_options=categoria_options,
                        reportes=reportes,
                    )

            conn.execute(
                """
                INSERT INTO reportes (aluno_id, titulo, descricao, categoria, screenshot_filename, status)
                VALUES (?, ?, ?, ?, ?, 'Novo')
                """,
                (aluno["id"], titulo, descricao, categoria, screenshot_filename),
            )
            conn.commit()
            flash("Reporte registrado para acompanhamento.", "success")
            return redirect(_aluno_url("aluno_reportar"))

    reportes_rows = conn.execute(
        """
        SELECT id, titulo, descricao, categoria, screenshot_filename, status, criado_em, atualizado_em
          FROM reportes
         WHERE aluno_id = ?
      ORDER BY datetime(criado_em) DESC, id DESC
        """,
        (aluno["id"],),
    ).fetchall()
    reportes = [
        {
            "id": row["id"],
            "titulo": row["titulo"],
            "descricao": row["descricao"],
            "categoria": row["categoria"],
            "screenshot_filename": row["screenshot_filename"],
            "status": row["status"],
            "criado_em_fmt": format_date_ptbr(row["criado_em"]),
            "atualizado_em_fmt": format_date_ptbr(row["atualizado_em"]),
        }
        for row in reportes_rows
    ]
    return render_template(
        "aluno_reportar.html",
        aluno=aluno,
        form_data=form_data,
        categoria_options=categoria_options,
        reportes=reportes,
    )


@bp_aluno.route("/aluno/requisicoes")
@aluno_required
def aluno_minhas_requisicoes():
    """Mesma lógica original, apenas movida de main.py para o blueprint."""
    page, per_page, offset = get_pagination(default_per_page=20)
    conn = get_db_connection()
    user_id = session.get("user_id")
    arow = conn.execute("SELECT id FROM alunos WHERE usuario_id = ?", (user_id,)).fetchone()
    if not arow:
        flash("Aluno não encontrado.", "error")
        return redirect(_aluno_url("aluno_dashboard"))
    aluno_id = arow["id"]

    q = (request.args.get("q") or "").strip()
    status_filters = [value for value in get_multi_query_values("status") if value]
    tipo_filters = [value for value in get_multi_query_values("tipo") if value]
    grupo_filters = [value for value in get_multi_query_values("grupo") if value]
    atividade_filters = [value for value in get_multi_query_values("atividade") if value]
    processamento_filters = {
        value.strip().lower()
        for value in get_multi_query_values("processamento")
        if value.strip().lower() in {"com_data", "sem_data"}
    }
    data_evento_min, data_evento_max = get_date_range_query("data_evento")
    data_processamento_min, data_processamento_max = get_date_range_query("data_processamento")
    horas_solicitadas_min, horas_solicitadas_max = get_number_range_query("horas_solicitadas", caster=float)
    horas_deferidas_min, horas_deferidas_max = get_number_range_query("horas_deferidas", caster=float)
    sort = (request.args.get("sort") or "").strip().lower()
    dir_ = (request.args.get("dir") or "desc").strip().lower()
    dir_sql = "DESC" if dir_ == "desc" else "ASC"

    select_cols = (
        "SELECT r.id, r.aluno_id, r.data_evento, r.data_processamento, r.horas_solicitadas, r.horas_deferidas, r.status, "
        "r.atividade_versao_id, r.regra_snapshot_json, "
        "av.numero_versao AS av_numero_versao, "
        "av.eixo AS av_eixo, av.grupo AS av_grupo "
    )
    base_from = (
        "FROM requisicoes r "
        "JOIN atividade_versao av ON av.id = r.atividade_versao_id "
        "WHERE r.aluno_id = ?"
    )
    params: list[Any] = [aluno_id]
    where_parts: list[str] = []
    if status_filters:
        placeholders = ", ".join("?" for _ in status_filters)
        where_parts.append(f"COALESCE(r.status, '') IN ({placeholders})")
        params.extend(status_filters)
    if data_evento_min:
        where_parts.append("date(r.data_evento) >= date(?)")
        params.append(data_evento_min)
    if data_evento_max:
        where_parts.append("date(r.data_evento) <= date(?)")
        params.append(data_evento_max)
    if data_processamento_min:
        where_parts.append("date(r.data_processamento) >= date(?)")
        params.append(data_processamento_min)
    if data_processamento_max:
        where_parts.append("date(r.data_processamento) <= date(?)")
        params.append(data_processamento_max)
    if horas_solicitadas_min is not None:
        where_parts.append("COALESCE(r.horas_solicitadas, 0) >= ?")
        params.append(horas_solicitadas_min)
    if horas_solicitadas_max is not None:
        where_parts.append("COALESCE(r.horas_solicitadas, 0) <= ?")
        params.append(horas_solicitadas_max)
    if horas_deferidas_min is not None:
        where_parts.append("COALESCE(r.horas_deferidas, 0) >= ?")
        params.append(horas_deferidas_min)
    if horas_deferidas_max is not None:
        where_parts.append("COALESCE(r.horas_deferidas, 0) <= ?")
        params.append(horas_deferidas_max)
    if processamento_filters:
        processamento_clauses = []
        if "com_data" in processamento_filters:
            processamento_clauses.append("(r.data_processamento IS NOT NULL AND TRIM(r.data_processamento) <> '')")
        if "sem_data" in processamento_filters:
            processamento_clauses.append("(r.data_processamento IS NULL OR TRIM(r.data_processamento) = '')")
        if processamento_clauses:
            where_parts.append("(" + " OR ".join(processamento_clauses) + ")")

    where_sql = ""
    if where_parts:
        where_sql = " AND " + " AND ".join(where_parts)

    sort_map = {
        "data_evento": "r.data_evento",
        "horas_solicitadas": "r.horas_solicitadas",
        "horas_deferidas": "COALESCE(r.horas_deferidas, r.horas_solicitadas)",
        "status": "r.status",
        "processado_em": "r.data_processamento",
    }
    historical_sort_fields = {
        "tipo_atividade": "tipo_atividade",
        "grupo": "grupo",
        "atividade_nome": "nome",
    }
    order_col = sort_map.get(sort, "r.data_evento")
    query = select_cols + base_from + where_sql + f" ORDER BY {order_col} {dir_sql}, r.id DESC"
    rows = conn.execute(query, params).fetchall()
    selected_rows = filter_historical_request_rows(
        rows,
        tipo_filters=tipo_filters,
        grupo_filters=grupo_filters,
        atividade_filters=atividade_filters,
        query=q,
    )
    historical_sort = historical_sort_fields.get(sort)
    if historical_sort:
        selected_rows.sort(
            key=lambda item: str(getattr(item[1], historical_sort) or "").casefold(),
            reverse=dir_sql == "DESC",
        )
    total = len(selected_rows)
    apply_limit = wants_pagination()
    if apply_limit:
        selected_rows = selected_rows[offset : offset + per_page]

    requisicoes = []
    for r, history in selected_rows:
        versao_row = None
        if r["av_numero_versao"] is not None:
            versao_row = {
                "numero_versao": r["av_numero_versao"],
                "eixo": r["av_eixo"],
                "grupo": r["av_grupo"],
            }
        snapshot_display = _build_aluno_requisicao_snapshot_display(
            atividade_versao_id=r["atividade_versao_id"],
            regra_snapshot_json=r["regra_snapshot_json"],
            versao_row=versao_row,
        )
        requisicoes.append(
            {
                "id": r["id"],
                "data_evento": r["data_evento"],
                "data_processamento": r["data_processamento"],
                "horas_solicitadas": r["horas_solicitadas"],
                "horas_deferidas": r["horas_deferidas"],
                "status": r["status"],
                "atividade_nome": history.nome,
                "tipo_atividade": history.tipo_atividade,
                "grupo": history.grupo,
                "snapshot": snapshot_display,
                "can_edit": can_student_edit_requisition(r["status"], r["data_processamento"]),
                "can_delete": can_student_delete_requisition(r["status"], r["data_processamento"]),
            }
        )

    filter_rows = conn.execute(
        """
        SELECT r.* FROM requisicoes r
         WHERE r.aluno_id = ?
        """,
        (aluno_id,),
    ).fetchall()

    filter_history = [read_request_presentation(row) for row in filter_rows]
    tipos_disponiveis = sorted({row.tipo_atividade for row in filter_history if row.tipo_atividade})
    grupos_disponiveis = sorted({row.grupo for row in filter_history if row.grupo})
    atividades_disponiveis = sorted({row.nome for row in filter_history if row.nome})
    status_disponiveis = sorted(
        {row.status for row in filter_history if row.status},
        key=lambda value: [
            "Pendente",
            "Deferida",
            "Deferida Parcialmente",
            "Indeferida",
            "Devolvida",
            "Encerrada",
        ].index(value) if value in {
            "Pendente",
            "Deferida",
            "Deferida Parcialmente",
            "Indeferida",
            "Devolvida",
            "Encerrada",
        } else 999,
    )

    filter_schema = [
        {
            "param": "data_evento",
            "label": "Solicitado em",
            "type": "date_range",
            "min_label": "De",
            "max_label": "Até",
        },
        {
            "param": "data_processamento",
            "label": "Processado em",
            "type": "date_range",
            "min_label": "De",
            "max_label": "Até",
        },
        {
            "param": "horas_solicitadas",
            "label": "Horas solicitadas",
            "type": "number_range",
            "min_label": "Mín",
            "max_label": "Máx",
            "step": "0.01",
        },
        {
            "param": "horas_deferidas",
            "label": "Horas deferidas",
            "type": "number_range",
            "min_label": "Mín",
            "max_label": "Máx",
            "step": "0.01",
        },
        {
            "param": "processamento",
            "label": "Estado do processamento",
            "type": "multi_select",
            "values": [
                {"value": "com_data", "label": "Com processamento"},
                {"value": "sem_data", "label": "Sem processamento"},
            ],
        },
    ]
    if tipos_disponiveis:
        filter_schema.append(
            {
                "param": "tipo",
                "label": "Tipo",
                "type": "multi_select",
                "values": [{"value": value, "label": value} for value in tipos_disponiveis],
            }
        )
    if grupos_disponiveis:
        filter_schema.append(
            {
                "param": "grupo",
                "label": "Grupo",
                "type": "multi_select",
                "values": [{"value": value, "label": value} for value in grupos_disponiveis],
            }
        )
    if atividades_disponiveis:
        filter_schema.append(
            {
                "param": "atividade",
                "label": "Atividade",
                "type": "multi_select",
                "values": [{"value": value, "label": value} for value in atividades_disponiveis],
            }
        )
    if status_disponiveis:
        filter_schema.append(
            {
                "param": "status",
                "label": "Status",
                "type": "multi_select",
                "values": [{"value": value, "label": value} for value in status_disponiveis],
            }
        )

    total_pages = (total + per_page - 1) // per_page if apply_limit and per_page else 1
    return render_template(
        "aluno_minhas_requisicoes.html",
        requisicoes=requisicoes,
        filter_schema=filter_schema,
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages,
    )


@bp_aluno.route("/aluno/nova-requisicao", methods=["GET", "POST"])
@bp_aluno.route("/aluno/nova_requisicao", methods=["GET", "POST"])
@aluno_required
def aluno_nova_requisicao():
    allowed_attachments = ALLOWED_ATTACHMENTS

    conn = get_db_connection()
    tipo_filtro = request.args.get("tipo", "Acadêmica Complementar")
    usuario_id = session["user_id"]
    aluno_scope, _, atividades = _list_atividades_for_usuario(conn, usuario_id, tipo_filtro)
    if not aluno_scope:
        flash("Dados do aluno não encontrados.", "error")
        return redirect(url_for("login"))

    if request.method == "POST":
        aluno_id = aluno_scope["aluno_id"]

        versao_id_raw = (request.form.get("atividade_versao_id") or "").strip()
        versao_id = int(versao_id_raw) if versao_id_raw.isdigit() else None
        nome_evento = request.form.get("nome_evento")
        data_evento = request.form["data_evento"]
        horas_solicitadas = float(request.form["horas_solicitadas"])
        observacao = request.form.get("observacao")

        if not versao_id:
            flash("Selecione uma atividade válida.", "error")
            return render_template(
                "aluno_nova_requisicao.html",
                atividades=atividades,
                tipo_atual=tipo_filtro,
            )
        if not _is_activity_allowed_for_usuario(conn, usuario_id, versao_id):
            flash("A atividade selecionada não está disponível para a matriz da sua turma.", "error")
            return render_template(
                "aluno_nova_requisicao.html",
                atividades=atividades,
                tipo_atual=tipo_filtro,
            )

        arquivos = request.files.getlist("comprovantes_files") or []
        labels = request.form.getlist("comprovantes_labels") or []
        data_solicitacao = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        created_document_paths = []

        try:
            prepared_snapshot = prepare_versioned_requisicao_snapshot(
                conn,
                flow_origin="aluno_create",
                aluno_id=aluno_id,
                atividade_versao_id=versao_id,
            )
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO requisicoes
                (aluno_id, atividade_versao_id, data_solicitacao, data_evento,
                 horas_solicitadas, nome_evento, status, observacao,
                 regra_snapshot_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    aluno_id,
                    prepared_snapshot.atividade_versao_id,
                    data_solicitacao,
                    data_evento,
                    horas_solicitadas,
                    nome_evento,
                    "Pendente",
                    observacao,
                    prepared_snapshot.snapshot_json,
                ),
            )
            req_id = cur.lastrowid

            ensure_requisicao_arquivos_table(conn)

            first_saved = None
            student_name = session.get("user_name") or f"aluno-{aluno_id}"
            for idx, arquivo in enumerate(arquivos):
                if not arquivo or not getattr(arquivo, "filename", ""):
                    continue
                if not _is_allowed_attachment(arquivo.filename, allowed_attachments):
                    current_app.logger.warning(
                        "Arquivo ignorado por extensão não permitida: %s",
                        arquivo.filename,
                    )
                    continue
                saved = save_student_document(
                    arquivo,
                    allowed_attachments,
                    root_folder=current_app.config["DOCUMENTOS_ALUNOS_FOLDER"],
                    student_id=aluno_id,
                    student_name=student_name,
                    category="requisicoes",
                    prefix=f"req{req_id}",
                )
                if saved:
                    created_document_paths.append(saved)
                    if first_saved is None:
                        first_saved = saved
                label_val = labels[idx] if labels and idx < len(labels) else None
                conn.execute(
                    "INSERT INTO requisicao_arquivos (requisicao_id, label, filename) VALUES (?, ?, ?)",
                    (req_id, label_val, saved),
                )

            conn.commit()
            created_document_paths.clear()
            flash("Requisição enviada com sucesso.", "success")
            return redirect(_aluno_url("aluno_dashboard"))
        except RequisicaoSnapshotError as exc:
            try:
                conn.rollback()
            except Exception:
                current_app.logger.exception("Falha ao reverter requisição do aluno")
            for rel_path in created_document_paths:
                try:
                    remove_student_document(
                        current_app.config["DOCUMENTOS_ALUNOS_FOLDER"], rel_path
                    )
                except Exception:
                    current_app.logger.exception("Falha ao compensar arquivo de comprovante")
            flash(exc.user_message, "error")
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                current_app.logger.exception("Falha ao reverter requisição do aluno")
            for rel_path in created_document_paths:
                try:
                    remove_student_document(
                        current_app.config["DOCUMENTOS_ALUNOS_FOLDER"], rel_path
                    )
                except Exception:
                    current_app.logger.exception("Falha ao compensar arquivo de comprovante")
            flash(f"Erro ao enviar requisição: {exc}", "error")
            current_app.logger.exception("Erro ao enviar requisição")

    return render_template(
        "aluno_nova_requisicao.html",
        atividades=atividades,
        tipo_atual=tipo_filtro,
    )


@bp_aluno.route("/aluno/requisicoes/<int:req_id>", methods=["GET", "POST"])
@aluno_required
def aluno_requisicao_detalhe(req_id: int):
    conn = get_db_connection()
    user_id = session.get("user_id")
    arow = conn.execute("SELECT id FROM alunos WHERE usuario_id = ?", (user_id,)).fetchone()
    if not arow:
        flash("Aluno não encontrado.", "error")
        return redirect(_aluno_url("aluno_dashboard"))
    aluno_id = arow["id"]

    delete_flag = (request.args.get("delete") or "").strip() == "1"
    if request.method == "POST" and delete_flag:
        row = conn.execute(
            "SELECT id, status, data_processamento FROM requisicoes WHERE id=? AND aluno_id=?",
            (req_id, aluno_id),
        ).fetchone()
        if not row:
            flash("Requisição não encontrada ou não pertence ao aluno.", "error")
            return redirect(_aluno_url("aluno_minhas_requisicoes"))
        if not can_student_delete_requisition(row["status"], row["data_processamento"]):
            flash("Essa requisição não pode ser excluída. Apenas visualização disponível.", "error")
            return redirect(_aluno_url("aluno_requisicao_detalhe", req_id=req_id, view=1))

        anexos_rows = conn.execute(
            "SELECT filename FROM requisicao_arquivos WHERE requisicao_id=?",
            (req_id,),
        ).fetchall()
        try:
            conn.execute(
                "DELETE FROM requisicao_arquivos WHERE requisicao_id=?",
                (req_id,),
            )
            conn.execute(
                "DELETE FROM requisicoes WHERE id=? AND aluno_id=?",
                (req_id, aluno_id),
            )
            conn.commit()
        except Exception:
            flash("Não foi possível excluir a requisição.", "error")
            return redirect(_aluno_url("aluno_minhas_requisicoes"))

        try:
            roots = (
                current_app.config.get("DOCUMENTOS_ALUNOS_FOLDER"),
                current_app.config.get("UPLOAD_FOLDER"),
            )
            filenames_to_remove = [row["filename"] for row in anexos_rows if row["filename"]]
            removed_relpaths: set[str] = set()
            for rel_path in filenames_to_remove:
                if not rel_path or rel_path in removed_relpaths:
                    continue
                removed_relpaths.add(rel_path)
                for root in roots:
                    if not root:
                        continue
                    try:
                        candidate_path = resolve_student_document_path(root, rel_path)
                    except ValueError:
                        continue
                    if os.path.isfile(candidate_path):
                        try:
                            os.remove(candidate_path)
                        except Exception:
                            pass
                        break

            upload_root = current_app.config.get("UPLOAD_FOLDER")
            if upload_root:
                req_dir = os.path.join(upload_root, f"aluno_{aluno_id}", f"req_{req_id}")
                if os.path.isdir(req_dir):
                    shutil.rmtree(req_dir, ignore_errors=True)
        except Exception:
            pass
        flash("Requisição excluída.", "success")
        return redirect(_aluno_url("aluno_minhas_requisicoes"))

    if request.method == "POST" and not delete_flag:
        rec = conn.execute(
            "SELECT status, data_processamento, atividade_versao_id, regra_snapshot_json "
            "FROM requisicoes WHERE id=? AND aluno_id=?",
            (req_id, aluno_id),
        ).fetchone()
        if not rec:
            flash("Requisição não encontrada.", "error")
            return redirect(_aluno_url("aluno_minhas_requisicoes"))
        can_edit = can_student_edit_requisition(rec["status"], rec["data_processamento"])
        if not can_edit:
            flash(
                "Edição só permitida enquanto Pendente ou Devolvida (até 14 dias).",
                "error",
            )
            return redirect(_aluno_url("aluno_requisicao_detalhe", req_id=req_id))

        nome_evento = request.form.get("nome_evento")
        horas_solicitadas_raw = request.form.get("horas_solicitadas")
        data_evento_raw = request.form.get("data_evento")
        observacao = request.form.get("observacao")
        atividade_id_new = request.form.get("atividade_versao_id")

        # D8.2B — contrato de edição após snapshot versionado.
        # Quando a requisição já tem um snapshot versionado registrado no
        # momento da criação, o aluno NÃO pode trocar a atividade. O snapshot é
        # um registro imutável do momento da criação: a edição não o recalcula
        # nem o limpa. As demais edições (nome do evento, horas, data,
        # observação, anexos) seguem permitidas normalmente. Requisições sem
        # snapshot preservam o comportamento legado de troca de atividade,
        # mantendo a validação de atividade permitida pela matriz.
        snapshot_versionado_presente = (
            (rec["atividade_versao_id"] is not None and str(rec["atividade_versao_id"]).strip() != "")
            or (str(rec["regra_snapshot_json"] or "").strip() != "")
        )
        if (
            snapshot_versionado_presente
            and atividade_id_new
            and atividade_id_new.isdigit()
            and int(atividade_id_new) != rec["atividade_versao_id"]
        ):
            flash(
                "Esta solicitação já possui uma versão de atividade registrada. "
                "Para trocar a atividade, crie uma nova solicitação.",
                "error",
            )
            return redirect(_aluno_url("aluno_requisicao_detalhe", req_id=req_id))

        try:
            horas_solicitadas = (
                float(horas_solicitadas_raw)
                if horas_solicitadas_raw not in (None, "")
                else None
            )
        except Exception:
            horas_solicitadas = None
        data_evento_norm: str | None = None
        if data_evento_raw:
            s = str(data_evento_raw).strip()
            if "/" in s:
                parts = s.split("/")
                if len(parts) >= 3:
                    try:
                        data_evento_norm = f"{parts[2]}-{int(parts[1]):02d}-{int(parts[0]):02d}"
                    except Exception:
                        data_evento_norm = None
            elif "-" in s:
                data_evento_norm = s.split(" ")[0][:10]

        arquivos = request.files.getlist("comprovantes_files") or []
        labels = request.form.getlist("comprovantes_labels") or []
        filenames_saved: list[str] = []
        first_saved: str | None = None
        student_name = session.get("user_name") or f"aluno-{aluno_id}"
        for idx, f in enumerate(arquivos):
            if not f or not getattr(f, "filename", ""):
                continue
            try:
                saved = save_student_document(
                    f,
                    ALLOWED_ATTACHMENTS,
                    root_folder=current_app.config["DOCUMENTOS_ALUNOS_FOLDER"],
                    student_id=aluno_id,
                    student_name=student_name,
                    category="requisicoes",
                    prefix=f"req{req_id}",
                )
                if saved:
                    if first_saved is None:
                        first_saved = saved
                    label_val = (
                        labels[idx] if labels and idx < len(labels) else None
                    )
                    conn.execute(
                        "INSERT INTO requisicao_arquivos (requisicao_id, label, filename) VALUES (?, ?, ?)",
                        (req_id, label_val, saved),
                    )
                    filenames_saved.append(saved)
            except Exception:
                # log permanece em main.logger; aqui só ignoramos erro pontual
                pass

        set_parts = ["observacao = ?"]
        params: list[Any] = [observacao]
        if nome_evento is not None:
            set_parts.append("nome_evento = ?")
            params.append(nome_evento)
        if horas_solicitadas is not None:
            set_parts.append("horas_solicitadas = ?")
            params.append(horas_solicitadas)
        if data_evento_norm:
            set_parts.append("data_evento = ?")
            params.append(data_evento_norm)
        if set_parts:
            params.extend([req_id, aluno_id])
            sql = (
                "UPDATE requisicoes SET "
                + ", ".join(set_parts)
                + " WHERE id = ? AND aluno_id = ?"
            )
            try:
                conn.execute(sql, tuple(params))
                conn.commit()
                flash("Requisição atualizada.", "success")
            except Exception:
                flash("Falha ao atualizar requisição.", "error")
        return redirect(_aluno_url("aluno_requisicao_detalhe", req_id=req_id))

    row = conn.execute(
        """
        SELECT r.*,
               av.numero_versao AS av_numero_versao,
               av.eixo AS av_eixo,
               av.grupo AS av_grupo
          FROM requisicoes r
          JOIN atividade_versao av ON av.id = r.atividade_versao_id
         WHERE r.id = ? AND r.aluno_id = ?
        """,
        (req_id, aluno_id),
    ).fetchone()
    if not row:
        flash("Requisição não encontrada.", "error")
        return redirect(_aluno_url("aluno_minhas_requisicoes"))

    versao_row = None
    if row["av_numero_versao"] is not None:
        versao_row = {
            "numero_versao": row["av_numero_versao"],
            "eixo": row["av_eixo"],
            "grupo": row["av_grupo"],
        }
    snapshot_display = _build_aluno_requisicao_snapshot_display(
        atividade_versao_id=row["atividade_versao_id"] if "atividade_versao_id" in row.keys() else None,
        regra_snapshot_json=row["regra_snapshot_json"] if "regra_snapshot_json" in row.keys() else None,
        versao_row=versao_row,
    )
    history = read_request_presentation(row)

    detalhe = {
        "id": row["id"],
        "atividade_nome": history.nome,
        "tipo_atividade": history.tipo_atividade,
        "grupo": history.grupo,
        "data_evento": row["data_evento"],
        "data_solicitacao": row["data_solicitacao"],
        "status": row["status"],
        "horas_solicitadas": row["horas_solicitadas"],
        "horas_deferidas": row["horas_deferidas"],
        "observacao": row["observacao"],
        "arquivo_comprovante": None,
        "data_processamento": row["data_processamento"],
        "nome_evento": row["nome_evento"] if "nome_evento" in row.keys() else None,
        "snapshot": snapshot_display,
    }

    edit_flag = (request.args.get("edit") or "").strip().lower() in {"1", "true", "yes", "y"}
    view_flag = (request.args.get("view") or "").strip().lower() in {"1", "true", "yes", "y"}
    if edit_flag or view_flag:
        tipo_filtro = detalhe["tipo_atividade"] or "Acadêmica Complementar"
        _, _, atividades = _list_atividades_for_usuario(
            conn,
            user_id,
            tipo_filtro,
            include_activity_id=row["atividade_versao_id"],
        )

        data_iso10 = ""
        try:
            s = str(detalhe["data_evento"] or "").strip()
            if s:
                if "-" in s:
                    data_iso10 = s.split(" ")[0][:10]
                elif "/" in s:
                    px = s.split("/")
                    if len(px) >= 3:
                        data_iso10 = f"{px[2]}-{int(px[1]):02d}-{int(px[0]):02d}"
        except Exception:
            data_iso10 = ""
        grupo_raw = detalhe["grupo"] or ""
        grupo_num = (
            grupo_raw.split(" - ")[0].strip()
            if " - " in grupo_raw
            else grupo_raw.strip()
        )
        init = {
            "tipo_atividade": detalhe["tipo_atividade"],
            "grupo": detalhe["grupo"],
            "grupo_num": grupo_num,
            "atividade_versao_id": row["atividade_versao_id"],
            "nome_evento": row["nome_evento"],
            "horas_solicitadas": detalhe["horas_solicitadas"],
            "data_evento": data_iso10,
            "observacao": detalhe["observacao"],
        }
        anexos: list[dict[str, Any]] = []
        try:
            anexos_rows = conn.execute(
                "SELECT id, label, filename, criado_em FROM requisicao_arquivos WHERE requisicao_id = ? ORDER BY id",
                (req_id,),
            ).fetchall()
            for ax in anexos_rows:
                anexos.append(
                    {
                        "id": ax["id"],
                        "label": ax["label"] or "Comprovante",
                        "filename": ax["filename"],
                        "criado_em": ax["criado_em"],
                    }
                )
        except Exception:
            pass
        return render_template(
            "aluno_nova_requisicao.html",
            atividades=atividades,
            tipo_atual=tipo_filtro,
            mode=("view_readonly" if view_flag else "edit"),
            init=init,
            anexos=anexos,
        )

    return render_template("aluno_requisicao_detalhe.html", r=detalhe)

