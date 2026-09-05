from __future__ import annotations

import datetime
import re
import sqlite3

from flask import Blueprint, redirect, render_template, request, url_for

from app.activity_catalog import (
    _canonicalize_tipo_limitacao,
    get_next_numero_versao,
)
from app.admin_access import _admin_can, _get_current_admin_access_context
from app.auth import admin_required
from app.db import get_db_connection
from app.db_maintenance import (
    ensure_atividade_versioning_schema,
    ensure_matriz_atividade_links_table,
    ensure_matrizes_atividades_table,
)
from app.matrix_scope import (
    AcademicGraphFrozenError,
    MATRIZ_STATUS_META,
    _matriz_status_label,
    is_matrix_assigned,
)
from app.web.filters import (
    append_conditions_sql,
    append_text_contains_condition,
    get_date_range_query,
    get_multi_query_values,
    get_number_range_query,
    get_text_query_value,
)
from app.web.pagination import get_pagination, wants_pagination
from utils.messages import flash

from app.views.admin import LegacyRouteSpec, configure_legacy_routes


def get_vinculo_versao_da_matriz(conn, matriz_id: int, base_id: int):
    """
    Retorna o vínculo atual (matriz_atividade_versao_item) para uma matriz+base.
    Deve existir no máximo um por matriz+base (invariante garantido pelo set).
    Retorna None se não houver vínculo.
    Estritamente read-only.
    """
    return conn.execute(
        """
        SELECT
            mavi.id                AS item_id,
            mavi.atividade_versao_id,
            av.numero_versao,
            av.eixo,
            av.status              AS versao_status,
            av.atividade_base_id
          FROM matriz_atividade_versao_item mavi
          JOIN atividade_versao av ON av.id = mavi.atividade_versao_id
         WHERE mavi.matriz_id = ?
           AND av.atividade_base_id = ?
         LIMIT 1
        """,
        (matriz_id, base_id),
    ).fetchone()


def _set_versao_da_matriz_para_base(conn, matriz_id: int, base_id: int, versao_id: int) -> None:
    """
    Define (substitui) o vínculo matriz→atividade_versao para uma atividade_base.
    Operação "set": remove qualquer vínculo anterior da mesma matriz+base antes de inserir.
    Garante no máximo um vínculo por matriz+base — nunca cria ambiguidade.
    Não commita — responsabilidade do chamador.
    """
    if is_matrix_assigned(conn, matriz_id):
        raise AcademicGraphFrozenError("assigned_matrix_version_link")
    conn.execute(
        """
        DELETE FROM matriz_atividade_versao_item
         WHERE matriz_id = ?
           AND atividade_versao_id IN (
               SELECT id FROM atividade_versao WHERE atividade_base_id = ?
           )
        """,
        (matriz_id, base_id),
    )
    conn.execute(
        "INSERT INTO matriz_atividade_versao_item (matriz_id, atividade_base_id, atividade_versao_id) VALUES (?, ?, ?)",
        (matriz_id, base_id, versao_id),
    )


def get_card_version_menu_data(conn, matriz_id: int, activity_ids: list) -> dict:
    """
    Para cada versão vinculada à matriz, retorna a versão atual vinculada
    e todas as versões disponíveis da mesma base (para escolha/relink).
    Retorna dict str(versao_id) → {base_id, versao_id, numero_versao, eixo, versoes}.
    Itens sem vínculo explícito de versão na matriz não são incluídos.
    Estritamente read-only.
    """
    if not activity_ids:
        return {}
    placeholders = ", ".join("?" for _ in activity_ids)
    rows = conn.execute(
        f"""
        SELECT
            item.atividade_versao_id AS selected_id,
            item.atividade_base_id AS base_id,
            av.id AS versao_id,
            av.numero_versao,
            av.eixo
          FROM matriz_atividade_versao_item item
          JOIN atividade_versao av ON av.id=item.atividade_versao_id
         WHERE item.matriz_id = ?
           AND item.atividade_versao_id IN ({placeholders})
        """,
        [matriz_id] + list(activity_ids),
    ).fetchall()

    result = {}
    for row in rows:
        current_versao_id = row["versao_id"]
        versoes_rows = conn.execute(
            """
            SELECT av.id, av.numero_versao, av.status
              FROM atividade_versao av
             WHERE av.atividade_base_id = ?
               AND av.status = 'ativa'
               AND av.eixo = ?
             ORDER BY av.numero_versao DESC
            """,
            (row["base_id"], row["eixo"]),
        ).fetchall()
        versoes = [
            {
                "id": v["id"],
                "numero_versao": v["numero_versao"],
                "status": v["status"],
                "is_current": v["id"] == current_versao_id,
            }
            for v in versoes_rows
        ]
        alternative_count = sum(1 for version in versoes if not version["is_current"])
        result[str(row["selected_id"])] = {
            "base_id": row["base_id"],
            "versao_id": current_versao_id,
            "numero_versao": row["numero_versao"],
            "eixo": row["eixo"],
            "versoes": versoes,
            "alternative_count": alternative_count,
            "availability_message": (
                "A versão atual é a única versão ativa elegível."
                if versoes and alternative_count == 0
                else "Nenhuma versão ativa elegível está disponível para esta atividade."
                if not versoes
                else ""
            ),
        }
    return result


@admin_required
def admin_matrizes():
    page, per_page, offset = get_pagination(default_per_page=25)
    q = (request.args.get("q") or "").strip()
    sort_field = (request.args.get("s") or "nome").strip().lower()
    sort_dir = (request.args.get("dir") or "asc").strip().lower()
    nome_filter = get_text_query_value("nome")
    inicio_min, inicio_max = get_date_range_query("data_inicio_vigencia")
    fim_min, fim_max = get_date_range_query("data_fim_vigencia")
    horas_aac_min, horas_aac_max = get_number_range_query("horas_aac_obrigatorias")
    horas_extensao_min, horas_extensao_max = get_number_range_query("horas_extensao_obrigatorias")
    status_filters = {item.lower() for item in get_multi_query_values("status") if item}
    curso_filters = {
        int(item)
        for item in get_multi_query_values("curso_id")
        if str(item).strip().isdigit()
    }

    conn = get_db_connection()
    ensure_matrizes_atividades_table(conn)
    ensure_matriz_atividade_links_table(conn)

    where = []
    params = []
    if q:
        like = f"%{q}%"
        where.append(
            "(COALESCE(m.nome, '') LIKE ? OR COALESCE(c.nome, '') LIKE ?)"
        )
        params.extend([like, like])
    append_text_contains_condition(where, params, "m.nome", nome_filter)
    if status_filters:
        placeholders = ", ".join("?" for _ in status_filters)
        where.append(f"LOWER(COALESCE(m.status, 'rascunho')) IN ({placeholders})")
        params.extend(sorted(status_filters))
    if curso_filters:
        placeholders = ", ".join("?" for _ in curso_filters)
        where.append(f"m.curso_id IN ({placeholders})")
        params.extend(sorted(curso_filters))
    if horas_aac_min is not None:
        where.append("COALESCE(m.horas_aac_obrigatorias, 0) >= ?")
        params.append(horas_aac_min)
    if horas_aac_max is not None:
        where.append("COALESCE(m.horas_aac_obrigatorias, 0) <= ?")
        params.append(horas_aac_max)
    if horas_extensao_min is not None:
        where.append("COALESCE(m.horas_extensao_obrigatorias, 0) >= ?")
        params.append(horas_extensao_min)
    if horas_extensao_max is not None:
        where.append("COALESCE(m.horas_extensao_obrigatorias, 0) <= ?")
        params.append(horas_extensao_max)
    if inicio_min:
        where.append("date(m.data_inicio_vigencia) >= date(?)")
        params.append(inicio_min)
    if inicio_max:
        where.append("date(m.data_inicio_vigencia) <= date(?)")
        params.append(inicio_max)
    if fim_min:
        where.append("date(m.data_fim_vigencia) >= date(?)")
        params.append(fim_min)
    if fim_max:
        where.append("date(m.data_fim_vigencia) <= date(?)")
        params.append(fim_max)

    order_map = {
        "nome": "LOWER(COALESCE(m.nome, ''))",
        "curso": "LOWER(COALESCE(c.nome, ''))",
        "vigencia": "COALESCE(m.data_inicio_vigencia, ''), COALESCE(m.data_fim_vigencia, '')",
        "status": "LOWER(COALESCE(m.status, 'rascunho'))",
        "horas_aac_obrigatorias": "m.horas_aac_obrigatorias",
        "horas_extensao_obrigatorias": "m.horas_extensao_obrigatorias",
    }
    order_sql = order_map.get(sort_field, order_map["nome"])
    direction = "DESC" if sort_dir == "desc" else "ASC"

    base_from = " FROM matrizes_atividades m LEFT JOIN cursos c ON c.id = m.curso_id"
    where_sql = append_conditions_sql(False, where)
    total = conn.execute("SELECT COUNT(*)" + base_from + where_sql, params).fetchone()[0]

    query = (
        "SELECT m.*, COALESCE(c.nome, 'Curso não encontrado') AS curso_nome, COALESCE(c.codigo, '') AS curso_codigo"
        + base_from
        + where_sql
        + f" ORDER BY {order_sql} {direction}, m.id DESC"
    )
    query_params = list(params)
    apply_limit = wants_pagination()
    if apply_limit:
        query += " LIMIT ? OFFSET ?"
        query_params.extend([per_page, offset])
    rows = conn.execute(query, query_params).fetchall()

    cursos = conn.execute("SELECT id, nome, codigo FROM cursos ORDER BY LOWER(nome), id").fetchall()
    filter_schema = [
        {
            "param": "nome",
            "label": "Nome",
            "type": "text_contains",
            "placeholder": "Contém no nome",
        },
        {
            "param": "curso_id",
            "label": "Curso",
            "type": "multi_select",
            "values": [
                {
                    "value": str(curso["id"]),
                    "label": f"{curso['nome']} ({curso['codigo']})" if curso["codigo"] else curso["nome"],
                }
                for curso in cursos
            ],
        },
        {
            "param": "data_inicio_vigencia",
            "label": "Vigência inicial",
            "type": "date_range",
            "min_label": "De",
            "max_label": "Até",
        },
        {
            "param": "data_fim_vigencia",
            "label": "Vigência final",
            "type": "date_range",
            "min_label": "De",
            "max_label": "Até",
        },
        {
            "param": "horas_aac_obrigatorias",
            "label": "AAC (h)",
            "type": "number_range",
            "min_label": "Mínimo",
            "max_label": "Máximo",
        },
        {
            "param": "horas_extensao_obrigatorias",
            "label": "Extensão (h)",
            "type": "number_range",
            "min_label": "Mínimo",
            "max_label": "Máximo",
        },
        {
            "param": "status",
            "label": "Status",
            "type": "multi_select",
            "values": [
                {"value": "rascunho", "label": "Rascunho"},
                {"value": "vigente", "label": "Vigente"},
                {"value": "encerrada", "label": "Encerrada"},
            ],
        },
    ]
    matrizes = [
        {
            "id": row["id"],
            "nome": row["nome"],
            "curso": row["curso_nome"],
            "vigencia": _matriz_vigencia_label(row),
            "horas_aac_obrigatorias": row["horas_aac_obrigatorias"] or 0,
            "horas_extensao_obrigatorias": row["horas_extensao_obrigatorias"] or 0,
            "status": _matriz_status_label(row["status"]),
            "status_badge_type": _matriz_status_badge_type(row["status"]),
            "view_url": url_for("admin_editar_matriz", matriz_id=row["id"], tab="dados"),
            "edit_url": url_for("admin_editar_matriz", matriz_id=row["id"], tab="dados"),
            "delete_url": url_for("admin_excluir_matriz", matriz_id=row["id"]),
            "manage_academicas_url": url_for("admin_editar_matriz", matriz_id=row["id"], tab="aac"),
            "manage_extensao_url": url_for("admin_editar_matriz", matriz_id=row["id"], tab="aea"),
        }
        for row in rows
    ]
    total_pages = (total + per_page - 1) // per_page if apply_limit and per_page else 1
    return render_template(
        "admin_matrizes.html",
        matrizes=matrizes,
        filter_schema=filter_schema,
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages,
    )


def _matriz_status_badge_type(status: str | None) -> str:
    normalized = (status or "rascunho").strip().lower()
    return MATRIZ_STATUS_META.get(normalized, MATRIZ_STATUS_META["rascunho"])["badge_type"]


def _matriz_vigencia_label(row) -> str:
    def _format_date_ptbr(value: str) -> str:
        raw = (value or "").strip()
        if not raw:
            return ""
        base = raw[:10]
        try:
            return datetime.datetime.strptime(base, "%Y-%m-%d").strftime("%d/%m/%Y")
        except ValueError:
            return raw

    inicio = _format_date_ptbr(row["data_inicio_vigencia"])
    fim = _format_date_ptbr(row["data_fim_vigencia"])
    if inicio and fim:
        return f"{inicio} a {fim}"
    if inicio:
        return f"A partir de {inicio}"
    if fim:
        return f"Até {fim}"
    return "-"


def _matriz_activity_type_for_tab(active_tab: str) -> str | None:
    if active_tab == "aac":
        return "Acadêmica Complementar"
    if active_tab == "aea":
        return "Extensão Universitária"
    return None


def _matriz_axis_for_tab(active_tab: str) -> str | None:
    if active_tab == "aac":
        return "AAC"
    if active_tab == "aea":
        return "AEU"
    return None


def _matriz_transfer_meta(active_tab: str) -> dict[str, str]:
    if active_tab == "aea":
        return {
            "help_text": "Selecione cada atividade de extensão e sua versão exata para esta matriz.",
            "available_title": "Atividades de extensão disponíveis",
            "selected_title": "Atividades de extensão vinculadas",
            "empty_available": "Nenhuma atividade de extensão disponível.",
            "empty_selected": "Nenhuma atividade de extensão vinculada.",
        }
    return {
        "help_text": "Selecione cada atividade acadêmica complementar e sua versão exata para esta matriz.",
        "available_title": "Atividades AAC disponíveis",
        "selected_title": "Atividades AAC vinculadas",
        "empty_available": "Nenhuma atividade AAC disponível.",
        "empty_selected": "Nenhuma atividade AAC vinculada.",
    }


def _matriz_activity_rule_summary(row) -> str:
    if not row["tem_limitacao"]:
        return "Sem limitação"
    tipo_limitacao = _canonicalize_tipo_limitacao(row["tipo_limitacao"])
    if tipo_limitacao == "total" and row["limite_horas_total"] is not None:
        return f"Limite total: {row['limite_horas_total']} h"
    if tipo_limitacao == "semestral" and row["limite_horas_semestral"] is not None:
        return f"Limite semestral: {row['limite_horas_semestral']} h"
    if row["limite_horas"] is not None:
        return f"Limite base: {row['limite_horas']} h"
    return "Com limitação"


def _matriz_transfer_lists(conn, matriz_id: int, active_tab: str):
    activity_type = _matriz_activity_type_for_tab(active_tab)
    if not activity_type:
        return [], [], []

    selected_by_base = {
        row["atividade_base_id"]: row["atividade_versao_id"]
        for row in conn.execute(
            """SELECT atividade_base_id, atividade_versao_id
                 FROM matriz_atividade_versao_item
                WHERE matriz_id = ?""",
            (matriz_id,),
        ).fetchall()
    }
    rows = conn.execute(
        """
        SELECT
            v.id, v.atividade_base_id, v.numero_versao, b.nome_conceito AS nome,
            COALESCE(NULLIF(TRIM(v.grupo), ''), 'Sem grupo') AS grupo,
            COALESCE(v.limite_semestre,v.limite_total) AS limite_horas,
            (v.limite_total IS NOT NULL OR v.limite_semestre IS NOT NULL) AS tem_limitacao,
            CASE WHEN v.limite_semestre IS NOT NULL THEN 'semestral' ELSE 'total' END AS tipo_limitacao,
            v.limite_total AS limite_horas_total,
            v.limite_semestre AS limite_horas_semestral
        FROM atividade_versao v
        JOIN atividade_base b ON b.id=v.atividade_base_id
        WHERE v.eixo=? AND v.status='ativa'
        ORDER BY LOWER(b.nome_conceito), v.numero_versao, v.id
        """,
        ('AAC' if activity_type == 'Acadêmica Complementar' else 'AEU',),
    ).fetchall()

    available_by_base = {}
    eligible_versions_by_base = {}
    selected = []
    groups = set()
    for row in rows:
        groups.add(row["grupo"])
        version = {
            "id": row["id"],
            "numero_versao": row["numero_versao"],
            "grupo": row["grupo"],
            "rule_summary": _matriz_activity_rule_summary(row),
        }
        base_id = row["atividade_base_id"]
        eligible_versions_by_base.setdefault(base_id, []).append(version)
        if selected_by_base.get(base_id) == row["id"]:
            selected_item = {
                **version,
                "base_id": base_id,
                "nome": row["nome"],
            }
            selected_item["search_blob"] = " ".join(
                [
                    str(selected_item["nome"] or "").strip().lower(),
                    f"v{selected_item['numero_versao']}",
                    str(selected_item["grupo"] or "").strip().lower(),
                    str(selected_item["rule_summary"] or "").strip().lower(),
                ]
            ).strip()
            selected.append(selected_item)
            continue
        if base_id in selected_by_base:
            continue

        item = available_by_base.setdefault(
            base_id,
            {
                "base_id": base_id,
                "nome": row["nome"],
                "eligible_versions": [],
            },
        )
        item["eligible_versions"].append(version)

    for item in selected:
        versions = eligible_versions_by_base[item["base_id"]]
        item["eligible_versions"] = versions
        item["group_values"] = sorted(
            {version["grupo"] for version in versions},
            key=lambda value: value.lower(),
        )

    available = []
    for item in available_by_base.values():
        versions = item["eligible_versions"]
        default_version = versions[-1]
        item.update(
            {
                "id": default_version["id"],
                "numero_versao": default_version["numero_versao"],
                "grupo": default_version["grupo"],
                "rule_summary": default_version["rule_summary"],
                "group_values": sorted(
                    {version["grupo"] for version in versions},
                    key=lambda value: value.lower(),
                ),
            }
        )
        item["search_blob"] = " ".join(
            [
                str(item["nome"] or "").strip().lower(),
                *(
                    " ".join(
                        [
                            f"v{version['numero_versao']}",
                            str(version["grupo"] or "").strip().lower(),
                            str(version["rule_summary"] or "").strip().lower(),
                        ]
                    )
                    for version in versions
                ),
            ]
        ).strip()
        available.append(item)

    return available, selected, sorted(groups, key=lambda value: value.lower())


def _matriz_counts(conn, matriz_id: int) -> tuple[int, int]:
    counts = {"Acadêmica Complementar": 0, "Extensão Universitária": 0}
    rows = conn.execute(
        """
        SELECT CASE v.eixo WHEN 'AAC' THEN 'Acadêmica Complementar' ELSE 'Extensão Universitária' END AS tipo_atividade, COUNT(*) AS total
        FROM matriz_atividade_versao_item mi
        JOIN atividade_versao v ON v.id = mi.atividade_versao_id
        WHERE mi.matriz_id = ? GROUP BY v.eixo
        """,
        (matriz_id,),
    ).fetchall()
    for row in rows:
        counts[row["tipo_atividade"]] = row["total"]
    return counts["Acadêmica Complementar"], counts["Extensão Universitária"]


_MATRIZ_ERR_INVALID_PARAMS = "invalid_params"
_MATRIZ_ERR_FROZEN = "frozen_matrix"
_MATRIZ_ERROR_TEXT = {
    _MATRIZ_ERR_INVALID_PARAMS: "Parâmetros inválidos.",
    _MATRIZ_ERR_FROZEN: "Parâmetros inválidos.",
}


def _render_matriz_form(
    conn,
    matriz=None,
    active_tab: str = "dados",
    readonly: bool = False,
):
    cursos = conn.execute("SELECT id, nome, codigo FROM cursos ORDER BY LOWER(nome), id").fetchall()
    matriz_id = matriz["id"] if matriz else None
    activity_tabs_enabled = bool(matriz_id)
    if active_tab not in {"dados", "aac", "aea"}:
        active_tab = "dados"
    if not activity_tabs_enabled:
        active_tab = "dados"

    academicas_count = 0
    extensao_count = 0
    transfer_available = []
    transfer_selected = []
    transfer_groups = []
    is_academically_frozen = is_matrix_assigned(conn, matriz_id) if matriz_id else False
    interaction_locked = readonly or is_academically_frozen
    if matriz_id:
        academicas_count, extensao_count = _matriz_counts(conn, matriz_id)
        if active_tab in {"aac", "aea"}:
            transfer_available, transfer_selected, transfer_groups = _matriz_transfer_lists(conn, matriz_id, active_tab)

    card_version_menu_data = {}
    if matriz_id and active_tab in {"aac", "aea"} and not interaction_locked:
        selected_ids = [item["id"] for item in transfer_selected]
        if selected_ids:
            try:
                raw_menu = get_card_version_menu_data(conn, matriz_id, selected_ids)
                for lid_str, entry in raw_menu.items():
                    entry["form_action"] = url_for(
                        "admin_matriz_nova_versao_card",
                        matriz_id=matriz_id,
                        atividade_id=int(lid_str),
                    )
                card_version_menu_data = raw_menu
            except Exception:
                card_version_menu_data = {}

    return render_template(
        "admin_matriz_form.html",
        matriz_title="Nova matriz de atividades" if not matriz_id else "Editar matriz de atividades",
        active_tab=active_tab,
        matriz_id=matriz_id,
        cursos=cursos,
        matriz=matriz,
        submit_label="Salvar matriz" if not matriz_id else "Salvar alterações",
        back_url=url_for("admin_matrizes"),
        cancel_label="Voltar",
        activity_tabs_enabled=activity_tabs_enabled,
        academicas_count=academicas_count,
        extensao_count=extensao_count,
        manage_academicas_url=url_for("admin_editar_matriz", matriz_id=matriz_id, tab="aac") if matriz_id else "",
        manage_extensao_url=url_for("admin_editar_matriz", matriz_id=matriz_id, tab="aea") if matriz_id else "",
        transfer_meta=_matriz_transfer_meta(active_tab),
        transfer_available=transfer_available,
        transfer_selected=transfer_selected,
        transfer_groups=transfer_groups,
        card_version_menu_data=card_version_menu_data,
        is_academically_frozen=is_academically_frozen,
        interaction_locked=interaction_locked,
        readonly=readonly,
    )


def _matriz_payload_from_request(conn):
    curso_id = request.form.get("curso_id", type=int)
    nome = (request.form.get("nome") or "").strip()
    status = (request.form.get("status") or "rascunho").strip().lower()
    data_inicio_vigencia = (request.form.get("data_inicio_vigencia") or "").strip() or None
    data_fim_vigencia = (request.form.get("data_fim_vigencia") or "").strip() or None
    horas_aac_obrigatorias = request.form.get("horas_aac_obrigatorias", type=int)
    horas_extensao_obrigatorias = request.form.get("horas_extensao_obrigatorias", type=int)
    descricao = (request.form.get("descricao") or "").strip() or None

    if not curso_id:
        return None, "Selecione um curso para a matriz."
    curso = conn.execute("SELECT id FROM cursos WHERE id = ?", (curso_id,)).fetchone()
    if not curso:
        return None, "Curso inválido para a matriz."
    if not nome:
        return None, "Informe o nome da matriz."
    if status not in MATRIZ_STATUS_META:
        return None, "Status de matriz inválido."
    if horas_aac_obrigatorias is None or horas_aac_obrigatorias < 0:
        return None, "Informe uma carga horária AAC válida."
    if horas_extensao_obrigatorias is None or horas_extensao_obrigatorias < 0:
        return None, "Informe uma carga horária de extensão válida."
    if data_inicio_vigencia and data_fim_vigencia and data_fim_vigencia < data_inicio_vigencia:
        return None, "A data final de vigência não pode ser anterior à inicial."

    return {
        "curso_id": curso_id,
        "nome": nome,
        "status": status,
        "data_inicio_vigencia": data_inicio_vigencia,
        "data_fim_vigencia": data_fim_vigencia,
        "horas_aac_obrigatorias": horas_aac_obrigatorias,
        "horas_extensao_obrigatorias": horas_extensao_obrigatorias,
        "descricao": descricao,
    }, None


def _ensure_default_versao_link(conn, matriz_id: int, activity_id: int) -> None:
    """
    Link the exact active activity_id selected by the caller when its base is unlinked.
    No-op when the exact version is ineligible or the base already has a link.
    Does not commit — caller's responsibility.
    """
    row = conn.execute("SELECT atividade_base_id FROM atividade_versao WHERE id=? AND status='ativa'", (activity_id,)).fetchone()
    if not row:
        return
    base_id = row["atividade_base_id"]
    if get_vinculo_versao_da_matriz(conn, matriz_id, base_id):
        return
    _set_versao_da_matriz_para_base(conn, matriz_id, base_id, activity_id)


def _validated_matrix_activity_selection(conn, raw_values: list[str], axis: str) -> list[int] | None:
    selected_ids = []
    seen_ids = set()
    for raw_value in raw_values:
        value = str(raw_value).strip()
        if not value.isdigit():
            return None
        activity_id = int(value)
        if activity_id in seen_ids:
            return None
        seen_ids.add(activity_id)
        selected_ids.append(activity_id)

    if not selected_ids:
        return []

    placeholders = ", ".join("?" for _ in selected_ids)
    rows = conn.execute(
        f"""
        SELECT id, atividade_base_id
          FROM atividade_versao
         WHERE id IN ({placeholders})
           AND eixo=?
           AND status='ativa'
        """,
        selected_ids + [axis],
    ).fetchall()
    if len(rows) != len(selected_ids):
        return None
    base_ids = [row["atividade_base_id"] for row in rows]
    if len(set(base_ids)) != len(base_ids):
        return None
    return sorted(selected_ids)


def _save_matriz_activity_links(conn, matriz_id: int, active_tab: str):
    activity_type = _matriz_activity_type_for_tab(active_tab)
    if not activity_type:
        return False
    if is_matrix_assigned(conn, matriz_id):
        return None

    axis = 'AAC' if activity_type == 'Acadêmica Complementar' else 'AEU'
    valid_ids = _validated_matrix_activity_selection(
        conn,
        request.form.getlist("selected_activity_ids"),
        axis,
    )
    if valid_ids is None:
        return _MATRIZ_ERR_INVALID_PARAMS

    conn.execute(
        """
        DELETE FROM matriz_atividade_versao_item
         WHERE matriz_id=? AND atividade_versao_id IN
               (SELECT id FROM atividade_versao WHERE eixo=?)
        """,
        (matriz_id, axis),
    )
    if valid_ids:
        for activity_id in valid_ids:
            _ensure_default_versao_link(conn, matriz_id, activity_id)

    conn.commit()
    return True


@admin_required
def admin_adicionar_matriz():
    conn = get_db_connection()
    ensure_matrizes_atividades_table(conn)
    ensure_matriz_atividade_links_table(conn)

    if request.method == "POST":
        payload, error_message = _matriz_payload_from_request(conn)
        if error_message:
            flash(error_message, "error")
            return _render_matriz_form(conn)
        cursor = conn.execute(
            """
            INSERT INTO matrizes_atividades (
                curso_id,
                nome,
                status,
                data_inicio_vigencia,
                data_fim_vigencia,
                horas_aac_obrigatorias,
                horas_extensao_obrigatorias,
                descricao
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["curso_id"],
                payload["nome"],
                payload["status"],
                payload["data_inicio_vigencia"],
                payload["data_fim_vigencia"],
                payload["horas_aac_obrigatorias"],
                payload["horas_extensao_obrigatorias"],
                payload["descricao"],
            ),
        )
        conn.commit()
        flash("Matriz criada com sucesso.", "success")
        return redirect(url_for("admin_editar_matriz", matriz_id=cursor.lastrowid, tab="dados"))

    return _render_matriz_form(conn)


@admin_required
def admin_editar_matriz(matriz_id: int):
    conn = get_db_connection()
    ensure_matrizes_atividades_table(conn)
    ensure_matriz_atividade_links_table(conn)

    matriz = conn.execute("SELECT * FROM matrizes_atividades WHERE id = ?", (matriz_id,)).fetchone()
    if not matriz:
        flash("Matriz não encontrada.", "error")
        return redirect(url_for("admin_matrizes"))

    auth_context = _get_current_admin_access_context()
    readonly = not _admin_can("matrizes", "edit", auth_context)

    active_tab = (request.values.get("tab") or request.values.get("active_tab") or "dados").strip().lower()
    if active_tab not in {"dados", "aac", "aea"}:
        active_tab = "dados"

    if request.method == "POST":
        if active_tab == "dados":
            payload, error_message = _matriz_payload_from_request(conn)
            if error_message:
                flash(error_message, "error")
                matriz = conn.execute("SELECT * FROM matrizes_atividades WHERE id = ?", (matriz_id,)).fetchone()
                return _render_matriz_form(conn, matriz=matriz, active_tab="dados", readonly=readonly)

            protected_fields = (
                "curso_id",
                "status",
                "data_inicio_vigencia",
                "data_fim_vigencia",
                "horas_aac_obrigatorias",
                "horas_extensao_obrigatorias",
            )
            if is_matrix_assigned(conn, matriz_id) and any(
                payload[field] != matriz[field] for field in protected_fields
            ):
                flash(_MATRIZ_ERROR_TEXT[_MATRIZ_ERR_FROZEN], "error")
                return redirect(url_for("admin_editar_matriz", matriz_id=matriz_id, tab="dados"))

            try:
                conn.execute(
                    """
                    UPDATE matrizes_atividades
                    SET curso_id = ?,
                        nome = ?,
                        status = ?,
                        data_inicio_vigencia = ?,
                        data_fim_vigencia = ?,
                        horas_aac_obrigatorias = ?,
                        horas_extensao_obrigatorias = ?,
                        descricao = ?
                    WHERE id = ?
                    """,
                    (
                        payload["curso_id"],
                        payload["nome"],
                        payload["status"],
                        payload["data_inicio_vigencia"],
                        payload["data_fim_vigencia"],
                        payload["horas_aac_obrigatorias"],
                        payload["horas_extensao_obrigatorias"],
                        payload["descricao"],
                        matriz_id,
                    ),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                conn.rollback()
                flash(_MATRIZ_ERROR_TEXT[_MATRIZ_ERR_INVALID_PARAMS], "error")
                return redirect(url_for("admin_editar_matriz", matriz_id=matriz_id, tab="dados"))
            flash("Matriz atualizada com sucesso.", "success")
            return redirect(url_for("admin_editar_matriz", matriz_id=matriz_id, tab="dados"))

        save_result = _save_matriz_activity_links(conn, matriz_id, active_tab)
        if save_result is True:
            flash("Lista da matriz atualizada com sucesso.", "success")
        elif save_result is None:
            flash(_MATRIZ_ERROR_TEXT[_MATRIZ_ERR_FROZEN], "error")
        elif save_result == _MATRIZ_ERR_INVALID_PARAMS:
            flash(_MATRIZ_ERROR_TEXT[_MATRIZ_ERR_INVALID_PARAMS], "error")
        else:
            flash("Aba de gestão de atividades inválida.", "error")
        return redirect(url_for("admin_editar_matriz", matriz_id=matriz_id, tab=active_tab))

    matriz = conn.execute("SELECT * FROM matrizes_atividades WHERE id = ?", (matriz_id,)).fetchone()
    return _render_matriz_form(conn, matriz=matriz, active_tab=active_tab, readonly=readonly)


# ===================== Rota Admin: Criar nova versão de atividade via card da matriz (D7.5D) =====================

@admin_required
def admin_matriz_nova_versao_card(matriz_id: int, atividade_id: int):
    """
    Relinka a matriz para uma versão operacional existente da atividade.

    Fluxo:
      A. Resolve atividade_base: atividade_id → base_id.
      B. Valida versao_id: deve existir, pertencer à mesma base_id.
      C. Relinka somente a matriz atual via _set_versao_da_matriz_para_base.

    Não cria atividade_versao — apenas escolhe entre as existentes.
    Não altera: outras matrizes, requisições, transições.
    CSRF obrigatório. Rollback total em erro intermediário.
    """
    conn = get_db_connection()
    ensure_atividade_versioning_schema(conn)
    ensure_matriz_atividade_links_table(conn)

    active_tab = (request.form.get("active_tab") or "").strip().lower()
    if active_tab not in {"aac", "aea"}:
        active_tab = "aac"
    axis = _matriz_axis_for_tab(active_tab)

    def _redirect_matrix():
        return redirect(url_for("admin_editar_matriz", matriz_id=matriz_id, tab=active_tab))

    matriz = conn.execute("SELECT * FROM matrizes_atividades WHERE id = ?", (matriz_id,)).fetchone()
    if not matriz:
        flash("Matriz não encontrada.", "error")
        return redirect(url_for("admin_matrizes"))

    selected = conn.execute(
        """SELECT item.atividade_base_id, current.eixo
             FROM matriz_atividade_versao_item item
             JOIN atividade_versao current ON current.id=item.atividade_versao_id
            WHERE item.matriz_id=? AND item.atividade_versao_id=?""",
        (matriz_id, atividade_id),
    ).fetchone()
    if not selected:
        flash("A versão da atividade não está vinculada a esta matriz.", "error")
        return _redirect_matrix()
    base_id = selected["atividade_base_id"]

    versao_id_raw = (request.form.get("versao_id") or "").strip()
    if not versao_id_raw or not versao_id_raw.isdigit():
        flash("Selecione uma versão existente.", "error")
        return _redirect_matrix()
    versao_id = int(versao_id_raw)

    target_versao = conn.execute(
        "SELECT id, atividade_base_id, numero_versao, status, eixo FROM atividade_versao WHERE id = ?",
        (versao_id,),
    ).fetchone()
    if not target_versao:
        flash("Versão não encontrada.", "error")
        return _redirect_matrix()
    if target_versao["atividade_base_id"] != base_id:
        flash("A versão selecionada não pertence a esta atividade.", "error")
        return _redirect_matrix()
    if target_versao["status"] != "ativa":
        flash("Apenas versões ativas podem ser selecionadas para esta matriz.", "error")
        return _redirect_matrix()
    if target_versao["eixo"] != selected["eixo"] or target_versao["eixo"] != axis:
        flash("A versão selecionada pertence ao eixo oposto desta lista.", "error")
        return _redirect_matrix()

    vinculo = get_vinculo_versao_da_matriz(conn, matriz_id, base_id)
    if vinculo and vinculo["atividade_versao_id"] == versao_id:
        flash("Esta versão já está vinculada a esta matriz.", "info")
        return _redirect_matrix()

    try:
        _set_versao_da_matriz_para_base(conn, matriz_id, base_id, versao_id)
        conn.commit()
        flash(
            f"v{target_versao['numero_versao']} selecionada para esta matriz.",
            "success",
        )
    except AcademicGraphFrozenError:
        conn.rollback()
        flash(_MATRIZ_ERROR_TEXT[_MATRIZ_ERR_FROZEN], "error")
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        flash(f"Erro de integridade ao escolher versão: {exc}", "error")
    except Exception as exc:
        conn.rollback()
        flash(f"Erro ao escolher versão: {exc}", "error")

    return _redirect_matrix()


@admin_required
def admin_excluir_matrizes():
    conn = get_db_connection()
    ensure_matrizes_atividades_table(conn)
    ensure_matriz_atividade_links_table(conn)

    matriz_ids = []
    for raw_value in request.form.getlist("matriz_ids"):
        if str(raw_value).strip().isdigit():
            matriz_ids.append(int(raw_value))
    matriz_ids = sorted(set(matriz_ids))
    if not matriz_ids:
        flash("Selecione ao menos uma matriz para excluir.", "error")
        return redirect(url_for("admin_matrizes"))

    placeholders = ", ".join("?" for _ in matriz_ids)
    if conn.execute(
        f"SELECT 1 FROM turmas WHERE matriz_id IN ({placeholders}) LIMIT 1",
        matriz_ids,
    ).fetchone() is not None:
        flash(_MATRIZ_ERROR_TEXT[_MATRIZ_ERR_FROZEN], "error")
        return redirect(url_for("admin_matrizes"))

    conn.execute(f"DELETE FROM matrizes_atividades WHERE id IN ({placeholders})", matriz_ids)
    conn.commit()
    flash("Matrizes excluídas com sucesso.", "success")
    return redirect(url_for("admin_matrizes"))


@admin_required
def admin_excluir_matriz(matriz_id: int):
    conn = get_db_connection()
    ensure_matrizes_atividades_table(conn)
    ensure_matriz_atividade_links_table(conn)

    if is_matrix_assigned(conn, matriz_id):
        flash(_MATRIZ_ERROR_TEXT[_MATRIZ_ERR_FROZEN], "error")
        return redirect(url_for("admin_matrizes"))

    deleted = conn.execute("DELETE FROM matrizes_atividades WHERE id = ?", (matriz_id,)).rowcount
    conn.commit()
    if deleted:
        flash("Matriz excluída com sucesso.", "success")
    else:
        flash("Matriz não encontrada.", "error")
    return redirect(url_for("admin_matrizes"))


bp_admin_matrizes = Blueprint("admin_matrizes_blueprint", __name__)

LEGACY_ROUTE_SPECS = configure_legacy_routes(
    bp_admin_matrizes,
    (
        LegacyRouteSpec("/admin/matrizes", "admin_matrizes", admin_matrizes, ("GET",)),
        LegacyRouteSpec(
            "/admin/adicionar_matriz",
            "admin_adicionar_matriz",
            admin_adicionar_matriz,
            ("GET", "POST"),
        ),
        LegacyRouteSpec(
            "/admin/editar_matriz/<int:matriz_id>",
            "admin_editar_matriz",
            admin_editar_matriz,
            ("GET", "POST"),
        ),
        LegacyRouteSpec(
            "/admin/matrizes/excluir",
            "admin_excluir_matrizes",
            admin_excluir_matrizes,
            ("POST",),
        ),
        LegacyRouteSpec(
            "/admin/matrizes/<int:matriz_id>/excluir",
            "admin_excluir_matriz",
            admin_excluir_matriz,
            ("POST",),
        ),
        LegacyRouteSpec(
            "/admin/matrizes/<int:matriz_id>/atividades/<int:atividade_id>/nova-versao",
            "admin_matriz_nova_versao_card",
            admin_matriz_nova_versao_card,
            ("POST",),
        ),
    ),
)


__all__ = [
    "LEGACY_ROUTE_SPECS",
    "admin_adicionar_matriz",
    "admin_editar_matriz",
    "admin_excluir_matriz",
    "admin_excluir_matrizes",
    "admin_matriz_nova_versao_card",
    "admin_matrizes",
    "bp_admin_matrizes",
    "get_card_version_menu_data",
    "get_vinculo_versao_da_matriz",
    "_ensure_default_versao_link",
    "_matriz_activity_rule_summary",
    "_matriz_activity_type_for_tab",
    "_matriz_axis_for_tab",
    "_matriz_counts",
    "_matriz_payload_from_request",
    "_matriz_status_badge_type",
    "_matriz_transfer_lists",
    "_matriz_transfer_meta",
    "_matriz_vigencia_label",
    "_render_matriz_form",
    "_save_matriz_activity_links",
    "_set_versao_da_matriz_para_base",
]
