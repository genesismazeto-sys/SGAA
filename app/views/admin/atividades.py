from __future__ import annotations

import csv
import json
import logging
import os
import re
import secrets
import sqlite3

from flask import (
    Blueprint,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from werkzeug.utils import secure_filename

from app.activity_catalog import (
    _build_grupo_label,
    _canonicalize_tipo_limitacao,
    _parse_non_negative_form_number,
    _normalize_atividade_grupo,
    apply_activity_version_semantic_changes,
    apply_latest_activity_version_semantic_changes,
    can_activity_version_be_mutated_in_place,
    create_activity_with_initial_version,
    get_atividade_base,
    get_atividade_base_list,
    get_atividade_transicoes_por_base,
    get_atividade_versao_by_id,
    get_atividade_versao_usage_counts,
    get_latest_atividade_versao_for_base,
    get_next_numero_versao,
    get_versoes_da_base_por_eixo,
    get_versoes_por_base,
    parse_documentos_json,
    rename_current_activity_group_versions,
)
from app.auth import admin_required
from app.db import get_db_connection
from app.db_maintenance import (
    ensure_atividade_versioning_schema,
    ensure_matriz_atividade_links_table,
)
from app.matrix_scope import (
    ACADEMIC_GRAPH_FROZEN_MESSAGE,
    ACADEMIC_VERSION_FROZEN_MESSAGE,
    is_activity_base_referenced_by_assigned_matrix,
    is_activity_version_referenced_by_assigned_matrix,
)
from app.uploads import ALLOWED_CSV, save_upload
from app.text import normalize_header
from app.views.admin import LegacyRouteSpec, configure_legacy_routes
from app.web.filters import (
    append_conditions_sql,
    append_text_contains_condition,
    get_multi_query_values,
    get_text_query_value,
)
from app.web.pagination import get_pagination, wants_pagination
from utils.messages import flash


ATIVIDADES_IMPORT_REQUIRED_HEADERS = (
    "nome",
    "tipo_atividade",
    "grupo_numero",
    "grupo_descricao",
    "tem_limitacao",
    "tipo_limitacao",
    "limite_horas_total",
    "limite_horas_semestral",
)


def _canonical_activity_rows_sql() -> str:
    return """SELECT v.id, v.atividade_base_id AS base_id, v.grupo,
                     b.nome_conceito AS nome, b.descricao,
                     v.ch_por_evento AS horas_sugeridas,
                     CASE v.eixo WHEN 'AAC' THEN 'Acadêmica Complementar' ELSE 'Extensão Universitária' END AS tipo_atividade,
                     (v.limite_total IS NOT NULL OR v.limite_semestre IS NOT NULL) AS tem_limitacao,
                     CASE WHEN v.limite_semestre IS NOT NULL THEN 'semestral' ELSE 'total' END AS tipo_limitacao,
                     v.limite_total AS limite_horas_total,
                     v.limite_semestre AS limite_horas_semestral,
                     v.documentos_json
                FROM atividade_versao v JOIN atividade_base b ON b.id=v.atividade_base_id"""


def _normalize_import_header_name(text: str) -> str:
    return normalize_header(text).replace("-", "_").replace(" ", "_")


def _canonicalize_tipo_atividade(value: str) -> str | None:
    normalized = normalize_header(value).replace("_", " ")
    if normalized in {"academica complementar", "academica", "aac"}:
        return "Acadêmica Complementar"
    if normalized in {"extensao universitaria", "extensao universitária", "extensao", "aeu"}:
        return "Extensão Universitária"
    return None


def _parse_csv_boolean(value) -> bool | None:
    normalized = normalize_header(value or "").replace("_", " ")
    if normalized in {"", "0", "false", "nao", "não", "no", "n"}:
        return False
    if normalized in {"1", "true", "sim", "yes", "y", "s"}:
        return True
    return None


def _parse_optional_positive_int(value):
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        raise ValueError("valor_invalido")
    if parsed <= 0:
        raise ValueError("valor_invalido")
    return parsed


def _format_preview_limitacao(tem_limitacao: bool, tipo_limitacao: str | None, limite_total, limite_semestral) -> str:
    if not tem_limitacao:
        return "Sem limitação"
    if tipo_limitacao == "total" and limite_total is not None:
        return f"Total: {limite_total}h"
    if tipo_limitacao == "semestral" and limite_semestral is not None:
        return f"Semestral: {limite_semestral}h"
    return "Com limitação"


def _ensure_grupos_def_table(conn) -> None:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='grupos_def'").fetchone():
        raise RuntimeError("prod-1 schema missing grupos_def")


def _upsert_grupo_definition(conn, tipo_atividade: str, grupo_numero: str, grupo_descricao: str) -> None:
    _ensure_grupos_def_table(conn)
    numero = int(grupo_numero)
    descricao = (grupo_descricao or "").strip()
    updated = conn.execute(
        "UPDATE grupos_def SET descricao = ? WHERE tipo_atividade = ? AND numero = ?",
        (descricao, tipo_atividade, numero),
    )
    if updated.rowcount == 0:
        conn.execute(
            "INSERT INTO grupos_def (tipo_atividade, numero, descricao) VALUES (?, ?, ?)",
            (tipo_atividade, numero, descricao),
        )


def _atividades_import_preview_dir() -> str:
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], "atividades_import_previews")
    os.makedirs(path, exist_ok=True)
    return path


def _atividades_import_preview_path(preview_key: str) -> str:
    safe_key = secure_filename(preview_key)
    return os.path.join(_atividades_import_preview_dir(), f"{safe_key}.json")


def _store_atividades_import_preview(payload: dict) -> str:
    preview_key = secrets.token_urlsafe(16)
    with open(_atividades_import_preview_path(preview_key), "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
    return preview_key


def _load_atividades_import_preview(preview_key: str) -> dict | None:
    path = _atividades_import_preview_path(preview_key)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _delete_atividades_import_preview(preview_key: str) -> None:
    path = _atividades_import_preview_path(preview_key)
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def _delete_upload_relpath(rel_path: str | None) -> None:
    if not rel_path:
        return
    abs_path = os.path.join(current_app.config["UPLOAD_FOLDER"], rel_path)
    try:
        if os.path.exists(abs_path):
            os.remove(abs_path)
    except OSError:
        pass


def _display_number(value):
    """Formata número REAL para exibição no formulário (inteiros sem sufixo .0)."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _tipo_atividade_from_eixo(eixo) -> str:
    return "Extensão Universitária" if str(eixo or "").strip().upper() == "AEU" else "Acadêmica Complementar"


def _eixo_from_tipo_atividade(tipo_atividade) -> str | None:
    canonical = _canonicalize_tipo_atividade(str(tipo_atividade or ""))
    if canonical == "Acadêmica Complementar":
        return "AAC"
    if canonical == "Extensão Universitária":
        return "AEU"
    return None


def _canonical_version_observacoes(values) -> str:
    """Project the two legacy columns into the single R4 visible field.

    Existing split values are not rewritten by merely rendering or saving a
    different field.  The admin value is the read source, with the student
    value as compatibility fallback.  An intentional Observações change is
    dual-written by the caller so both legacy consumers receive the same new
    canonical value.
    """
    values = dict(values)
    admin = str(values.get("observacao_admin") or "").strip()
    aluno = str(values.get("observacao_aluno") or "").strip()
    return admin or aluno


def _limitation_form_values(values) -> tuple[str, str]:
    values = dict(values)
    if values.get("limite_semestre") is not None:
        return "semestral", _display_number(values.get("limite_semestre"))
    if values.get("limite_total") is not None:
        return "total", _display_number(values.get("limite_total"))
    return "", ""


def _normalized_version_form_payload(values) -> dict:
    """Normalize exactly the eight visible R4 field concepts."""
    values = dict(values)

    def _num(value):
        if value is None or str(value).strip() == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _txt(value):
        text = str(value or "").strip()
        return text or None

    tipo = _canonicalize_tipo_atividade(str(values.get("tipo_atividade") or ""))
    grupo = "NA" if tipo == "Extensão Universitária" else _txt(values.get("grupo"))
    tipo_limitacao = str(values.get("tipo_limitacao") or "").strip().lower()
    if tipo_limitacao not in {"total", "semestral"}:
        tipo_limitacao = None
    limite_valor = _num(values.get("limite_valor")) if tipo_limitacao else None
    ch_mode_raw = values.get("ch_por_evento_mode")
    ch_enabled = (
        ch_mode_raw == "enabled"
        if ch_mode_raw is not None
        else _num(values.get("ch_por_evento")) is not None
    )
    prev_raw = str(values.get("versao_anterior_id") or "").strip()
    try:
        versao_anterior_id = int(prev_raw) if prev_raw else None
    except (TypeError, ValueError):
        versao_anterior_id = None
    return {
        "tipo_atividade": tipo,
        "grupo": grupo,
        "nome": _txt(values.get("nome")),
        "descricao": _txt(values.get("descricao")),
        "tipo_limitacao": tipo_limitacao,
        "limite_valor": limite_valor,
        "ch_por_evento_mode": "enabled" if ch_enabled else "disabled",
        "ch_por_evento": _num(values.get("ch_por_evento")) if ch_enabled else None,
        "observacoes": _txt(values.get("observacoes")),
        "versao_anterior_id": versao_anterior_id,
    }


def _build_version_form_initial_payload(base, version, *, predecessor_id=None) -> dict:
    tipo_limitacao, limite_valor = _limitation_form_values(version)
    return _normalized_version_form_payload(
        {
            "tipo_atividade": _tipo_atividade_from_eixo(version["eixo"]),
            "grupo": version["grupo"],
            "nome": base["nome_conceito"],
            "descricao": base["descricao"],
            "tipo_limitacao": tipo_limitacao,
            "limite_valor": limite_valor,
            "ch_por_evento": version["ch_por_evento"],
            "observacoes": _canonical_version_observacoes(version),
            "versao_anterior_id": predecessor_id,
        }
    )


def _build_grupos_por_tipo_for_activity_form(conn) -> dict:
    """Use the same group-number/description source as canonical Activity UI."""
    grupos = {}
    try:
        rows = conn.execute(
            "SELECT tipo_atividade, numero, descricao FROM grupos_def"
        ).fetchall()
        for row in rows:
            grupos.setdefault(row[0], {})[str(row[1])] = (row[2] or "").strip()
    except Exception:
        pass
    rows = conn.execute(
        "SELECT CASE eixo WHEN 'AAC' THEN 'Acadêmica Complementar' "
        "ELSE 'Extensão Universitária' END, grupo FROM atividade_versao "
        "WHERE grupo IS NOT NULL AND TRIM(grupo) <> ''"
    ).fetchall()
    for row in rows:
        label = (row[1] or "").strip()
        match = re.match(r"^\s*(\d+)\s*(?:-\s*(.*))?$", label)
        if not match:
            continue
        tipo, numero = row[0], match.group(1)
        descricao = (match.group(2) or "").strip()
        tipo_grupos = grupos.setdefault(tipo, {})
        if numero not in tipo_grupos or (not tipo_grupos[numero] and descricao):
            tipo_grupos[numero] = descricao
    return grupos


def _resolve_nova_versao_prefill(conn, base_id: int, from_raw) -> tuple[dict, str | None]:
    """
    FC-07 — Resolve o estado inicial do formulário de nova versão.

    `?from=<atividade_versao_id>` copia os campos editáveis do predecessor
    (mesma atividade-base) e o pré-seleciona como versao_anterior_id.

    Estritamente read-only. Fontes inválidas (malformadas, inexistentes ou de
    outra atividade-base) retornam o formulário em branco junto da mensagem de
    erro para flash pelo chamador (mesmo padrão de _render_form no POST).
    """
    base = get_atividade_base(conn, base_id)
    blank = {
        "tipo_atividade": "Acadêmica Complementar",
        "grupo": "",
        "nome": base["nome_conceito"] if base else "",
        "descricao": (base["descricao"] or "") if base else "",
        "tipo_limitacao": "",
        "limite_valor": "",
        "ch_por_evento": "",
        "observacoes": "",
        "versao_anterior_id": "",
    }
    raw = (from_raw or "").strip()
    if not raw:
        return blank, None
    try:
        origem_id = int(raw)
    except (TypeError, ValueError):
        return blank, "Versão anterior inválida."
    origem = get_atividade_versao_by_id(conn, origem_id)
    if not origem:
        return blank, "Versão anterior não encontrada."
    if origem["atividade_base_id"] != base_id:
        return blank, "Versão anterior deve pertencer à mesma atividade-base."
    tipo_limitacao, limite_valor = _limitation_form_values(origem)
    return ({
        "tipo_atividade": _tipo_atividade_from_eixo(origem["eixo"]),
        "grupo": origem["grupo"] or "",
        "nome": base["nome_conceito"] if base else "",
        "descricao": (base["descricao"] or "") if base else "",
        "tipo_limitacao": tipo_limitacao,
        "limite_valor": limite_valor,
        "ch_por_evento": _display_number(origem["ch_por_evento"]),
        "observacoes": _canonical_version_observacoes(origem),
        "versao_anterior_id": str(origem["id"]),
    }, None)


def _build_atividades_import_preview(csv_abspath: str, csv_relpath: str, mode: str) -> tuple[dict, dict | None]:
    conn = get_db_connection()
    existing_rows = conn.execute("SELECT id, nome_conceito AS nome FROM atividade_base").fetchall()
    existing_by_name = {str(row["nome"]): row["id"] for row in existing_rows}

    preview = {
        "ok": True,
        "missing_headers": [],
        "rows": [],
        "summary": {
            "linhas_lidas": 0,
            "criar": 0,
            "atualizar": 0,
            "ignorar": 0,
            "erros": 0,
        },
    }

    with open(csv_abspath, "r", encoding="utf-8-sig", newline="") as handle:
        sample = handle.read(2048)
        handle.seek(0)
        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=";,").delimiter
        except csv.Error:
            delimiter = ";" if sample.count(";") >= sample.count(",") else ","
        reader = csv.DictReader(handle, delimiter=delimiter)
        header_map = {_normalize_import_header_name(header): header for header in (reader.fieldnames or [])}
        missing_headers = [header for header in ATIVIDADES_IMPORT_REQUIRED_HEADERS if header not in header_map]
        if missing_headers:
            preview["ok"] = False
            preview["missing_headers"] = missing_headers
            return preview, None

        action_rows = []
        for line_number, row in enumerate(reader, start=2):
            if not any(str(value or "").strip() for value in row.values()):
                continue

            preview["summary"]["linhas_lidas"] += 1
            errors = []

            def cell(name: str) -> str:
                return str(row.get(header_map[name], "") or "").strip()

            nome = cell("nome")
            tipo_atividade = _canonicalize_tipo_atividade(cell("tipo_atividade"))
            grupo_numero = cell("grupo_numero")
            grupo_descricao = cell("grupo_descricao")
            tem_limitacao = _parse_csv_boolean(cell("tem_limitacao"))
            tipo_limitacao = _canonicalize_tipo_limitacao(cell("tipo_limitacao"))
            limite_total = None
            limite_semestral = None

            if not nome:
                errors.append("Nome é obrigatório")
            if not grupo_numero.isdigit():
                errors.append("Grupo deve ter número válido")
            if not tipo_atividade:
                errors.append("Tipo de atividade inválido")
            if tem_limitacao is None:
                errors.append("Campo tem_limitacao inválido")

            if tem_limitacao:
                if tipo_limitacao not in {"total", "semestral"}:
                    errors.append("Tipo de limitação inválido")
                try:
                    limite_total = _parse_optional_positive_int(cell("limite_horas_total"))
                    limite_semestral = _parse_optional_positive_int(cell("limite_horas_semestral"))
                except ValueError:
                    errors.append("Limites devem ser inteiros positivos")
                if tipo_limitacao == "total" and limite_total is None:
                    errors.append("Limite total é obrigatório")
                if tipo_limitacao == "semestral" and limite_semestral is None:
                    errors.append("Limite semestral é obrigatório")
            else:
                tipo_limitacao = "total"

            grupo = _build_grupo_label(grupo_numero, grupo_descricao)
            action = None
            situacao = "Erro"
            existing_id = existing_by_name.get(nome)
            if errors:
                preview["summary"]["erros"] += 1
            elif existing_id:
                if mode == "upsert":
                    action = "update"
                    situacao = "Atualizar"
                    preview["summary"]["atualizar"] += 1
                else:
                    action = "ignore"
                    situacao = "Ignorar"
                    preview["summary"]["ignorar"] += 1
            else:
                action = "create"
                situacao = "Criar"
                preview["summary"]["criar"] += 1

            payload = None
            if action in {"create", "update"}:
                payload = {
                    "action": action,
                    "existing_id": existing_id,
                    "nome": nome,
                    "grupo": grupo,
                    "grupo_numero": grupo_numero,
                    "grupo_descricao": grupo_descricao,
                    "tipo_atividade": tipo_atividade,
                    "tem_limitacao": bool(tem_limitacao),
                    "tipo_limitacao": tipo_limitacao,
                    "limite_horas_total": limite_total,
                    "limite_horas_semestral": limite_semestral,
                }
                action_rows.append(payload)

            preview["rows"].append(
                {
                    "line_number": line_number,
                    "nome": nome,
                    "tipo_atividade": tipo_atividade or cell("tipo_atividade"),
                    "grupo": grupo,
                    "limitacao": _format_preview_limitacao(bool(tem_limitacao), tipo_limitacao, limite_total, limite_semestral),
                    "situacao": situacao,
                    "errors": errors,
                }
            )

    storage_payload = {
        "mode": mode,
        "csv_relpath": csv_relpath,
        "rows": action_rows,
    }
    return preview, storage_payload


@admin_required
def admin_atividades():
    """Lista atividades com filtro por tipo e docs.
    Backend-only: adiciona paginação opcional e COUNT consistente.
    """
    page, per_page, offset = get_pagination(default_per_page=50)
    tipo_filters = [value.strip() for value in get_multi_query_values('tipo') if value.strip() and value.strip() != 'Todas']
    grupo_filters = [value.strip() for value in get_multi_query_values('grupo') if value.strip()]
    limitacao_filters = [value.strip().lower() for value in get_multi_query_values('limitacao') if value.strip()]
    nome_filter = get_text_query_value('nome')
    tipo_filtro = tipo_filters[0] if len(tipo_filters) == 1 else 'Todas'
    sort_field = (request.args.get('s') or '').strip().lower()
    sort_dir = 'DESC' if (request.args.get('dir') or 'asc').strip().lower() == 'desc' else 'ASC'
    conn = get_db_connection()
    base_from = (
        " FROM (" + _canonical_activity_rows_sql() + ") canonical_activity"
        " JOIN (SELECT atividade_base_id, COUNT(*) AS total_versoes"
        "         FROM atividade_versao GROUP BY atividade_base_id) version_counts"
        "   ON version_counts.atividade_base_id = canonical_activity.base_id"
    )
    where = []
    params = []
    append_text_contains_condition(where, params, 'nome', nome_filter)
    if tipo_filters:
        placeholders = ", ".join("?" for _ in tipo_filters)
        where.append(f"COALESCE(tipo_atividade, 'Acadêmica Complementar') IN ({placeholders})")
        params.extend(tipo_filters)
    if grupo_filters:
        placeholders = ", ".join("?" for _ in grupo_filters)
        where.append(f"COALESCE(TRIM(grupo), '') IN ({placeholders})")
        params.extend(grupo_filters)
    if limitacao_filters:
        clauses = []
        if 'limitadas' in limitacao_filters:
            clauses.append("COALESCE(tem_limitacao, 0) = 1")
        if 'sem_limite' in limitacao_filters:
            clauses.append("COALESCE(tem_limitacao, 0) = 0")
        if clauses:
            where.append("(" + " OR ".join(clauses) + ")")
    where_sql = append_conditions_sql(False, where)
    sort_map = {
        'nome': f" ORDER BY nome COLLATE NOCASE {sort_dir}, tipo_atividade COLLATE NOCASE ASC, grupo COLLATE NOCASE ASC",
        'grupo': f" ORDER BY grupo COLLATE NOCASE {sort_dir}, nome COLLATE NOCASE ASC",
        'tipo_atividade': f" ORDER BY tipo_atividade COLLATE NOCASE {sort_dir}, grupo COLLATE NOCASE ASC, nome COLLATE NOCASE ASC",
        'limitacao': (
            " ORDER BY "
            f"COALESCE(tem_limitacao, 0) {sort_dir}, "
            f"CASE WHEN tipo_limitacao = 'total' THEN COALESCE(limite_horas_total, 0) "
            f"WHEN tipo_limitacao = 'semestral' THEN COALESCE(limite_horas_semestral, 0) "
            f"ELSE 0 END {sort_dir}, "
            "nome COLLATE NOCASE ASC"
        ),
    }
    order_sql = sort_map.get(sort_field)
    if not order_sql:
        order_sql = " ORDER BY tipo_atividade, grupo, nome" if (not where) else " ORDER BY grupo, nome"
    query = (
        "SELECT canonical_activity.*, version_counts.total_versoes"
        + base_from + where_sql + order_sql
    )
    count_sql = "SELECT COUNT(*)" + base_from + where_sql
    total = conn.execute(count_sql, params).fetchone()[0]
    apply_limit = wants_pagination()
    exec_params = list(params)
    if apply_limit:
        query += " LIMIT ? OFFSET ?"
        exec_params += [per_page, offset]
    atividades = conn.execute(query, exec_params).fetchall()
    # Load documentos obrigatórios per canonical version (tolerant parser).
    docs_por_atividade = {}
    for activity in atividades:
        docs_por_atividade[activity['id']] = parse_documentos_json(activity['documentos_json'])
    # Build grupos_por_tipo including explicit definitions from grupos_def table
    def build_grupos_por_tipo_from_db(c):
        grupos = {}
        try:
            rows = c.execute("SELECT tipo_atividade, numero, descricao FROM grupos_def").fetchall()
            for r in rows:
                tipo, num, desc = r[0], str(r[1]), (r[2] or '').strip()
                grupos.setdefault(tipo, {})[num] = desc
        except Exception:
            pass
        # Also derive from canonical versions for missing entries.
        rows2 = conn.execute(
            "SELECT CASE eixo WHEN 'AAC' THEN 'Acadêmica Complementar' ELSE 'Extensão Universitária' END AS tipo_atividade, grupo FROM atividade_versao WHERE grupo IS NOT NULL AND TRIM(grupo) <> ''"
        ).fetchall()
        for r in rows2:
            tipo = r[0]
            label = (r[1] or '').strip()
            m = re.match(r'^\s*(\d+)\s*-\s*(.*)$', label)
            if m:
                num = m.group(1)
                desc = (m.group(2) or '').strip()
            else:
                m2 = re.match(r'^\s*(\d+)\s*$', label)
                if not m2:
                    continue
                num = m2.group(1)
                desc = ''
            if tipo not in grupos:
                grupos[tipo] = {}
            if num not in grupos[tipo] or (not grupos[tipo][num] and desc):
                grupos[tipo][num] = desc
        return grupos
    grupos_por_tipo = build_grupos_por_tipo_from_db(conn)
    grupos_filtro = conn.execute(
        """
        SELECT DISTINCT COALESCE(NULLIF(TRIM(grupo), ''), '') AS grupo
          FROM (""" + _canonical_activity_rows_sql() + """) canonical_activity
         WHERE COALESCE(NULLIF(TRIM(grupo), ''), '') <> ''
      ORDER BY LOWER(COALESCE(grupo, '')) ASC
        """
    ).fetchall()
    filter_schema = [
        {
            "param": "tipo",
            "label": "Tipo",
            "type": "multi_select",
            "values": [
                {"value": "Acadêmica Complementar", "label": "Acadêmica Complementar"},
                {"value": "Extensão Universitária", "label": "Extensão Universitária"},
            ],
        },
        {
            "param": "nome",
            "label": "Nome",
            "type": "text_contains",
            "placeholder": "Contém no nome",
        },
        {
            "param": "limitacao",
            "label": "Limitação",
            "type": "multi_select",
            "values": [
                {"value": "limitadas", "label": "Apenas com limitação"},
                {"value": "sem_limite", "label": "Sem limitação"},
            ],
        },
        {
            "param": "grupo",
            "label": "Grupo",
            "type": "multi_select",
            "values": [
                {"value": row["grupo"], "label": row["grupo"]}
                for row in grupos_filtro
            ],
        },
    ]
    total_pages = (total + per_page - 1) // per_page if apply_limit and per_page else 1
    return render_template("admin_atividades.html", atividades=atividades, tipo_atual=tipo_filtro, grupos_por_tipo=grupos_por_tipo, docs_por_atividade=docs_por_atividade, page=page, per_page=per_page, total=total, total_pages=total_pages, filter_schema=filter_schema)


@admin_required
def admin_atividades_academicas():
    """Lista atividades do tipo Acadêmica Complementar com paginação opcional."""
    page, per_page, offset = get_pagination(default_per_page=50)
    conn = get_db_connection()
    base_from = " FROM (" + _canonical_activity_rows_sql() + ") canonical_activity WHERE tipo_atividade = 'Acadêmica Complementar'"
    query = "SELECT *" + base_from + " ORDER BY grupo, nome"
    count_sql = "SELECT COUNT(*)" + base_from
    total = conn.execute(count_sql).fetchone()[0]
    apply_limit = wants_pagination()
    params_exec = []
    if apply_limit:
        query += " LIMIT ? OFFSET ?"
        params_exec += [per_page, offset]
    atividades = conn.execute(query, params_exec).fetchall()
    total_pages = (total + per_page - 1) // per_page if apply_limit and per_page else 1
    return render_template("admin_atividades_academicas.html", atividades=atividades, page=page, per_page=per_page, total=total, total_pages=total_pages)


@admin_required
def admin_atividades_extensao():
    """Lista atividades do tipo Extensão Universitária com paginação opcional."""
    page, per_page, offset = get_pagination(default_per_page=50)
    conn = get_db_connection()
    base_from = " FROM (" + _canonical_activity_rows_sql() + ") canonical_activity WHERE tipo_atividade = 'Extensão Universitária'"
    query = "SELECT *" + base_from + " ORDER BY grupo, nome"
    count_sql = "SELECT COUNT(*)" + base_from
    total = conn.execute(count_sql).fetchone()[0]
    apply_limit = wants_pagination()
    params_exec = []
    if apply_limit:
        query += " LIMIT ? OFFSET ?"
        params_exec += [per_page, offset]
    atividades = conn.execute(query, params_exec).fetchall()
    total_pages = (total + per_page - 1) // per_page if apply_limit and per_page else 1
    return render_template("admin_atividades_extensao.html", atividades=atividades, page=page, per_page=per_page, total=total, total_pages=total_pages)


@admin_required
def admin_adicionar_atividade():
    """Create one coherent atividade_base + active atividade_versao v1."""

    conn = get_db_connection()

    def _render(message=None):
        if message:
            flash(message, "error")
        return render_template(
            "admin_adicionar_atividade.html",
            grupos_por_tipo=_build_grupos_por_tipo_for_activity_form(conn),
        )

    if request.method == "POST":
        tipo_atividade = (request.form.get("tipo_atividade") or "").strip()
        axis = _eixo_from_tipo_atividade(tipo_atividade)
        grupo = _normalize_atividade_grupo(tipo_atividade, request.form.get("grupo"))
        nome = (request.form.get("nome") or "").strip()
        descricao = (request.form.get("descricao") or "").strip() or None
        tipo_limitacao = (request.form.get("tipo_limitacao") or "").strip()
        limite_valor_raw = (request.form.get("limite_valor") or "").strip()
        ch_por_evento_raw = (request.form.get("ch_por_evento") or "").strip()
        ch_mode_raw = request.form.get("ch_por_evento_mode")
        ch_enabled = (
            ch_mode_raw == "enabled"
            if ch_mode_raw is not None
            else bool(ch_por_evento_raw)
        )
        observacoes = (request.form.get("observacoes") or "").strip() or None

        if axis is None:
            return _render("Erro: selecione um Tipo válido.")
        if not grupo:
            return _render("Erro: selecione o Grupo (nº/descrição).")
        if not nome:
            return _render("Erro: informe o Nome da atividade.")
        if tipo_limitacao not in {"", "total", "semestral"}:
            return _render("Erro: selecione uma Limitação / Tempo limite válida.")

        try:
            ch_por_evento = (
                _parse_non_negative_form_number(
                    ch_por_evento_raw,
                    "a Carga horária por evento",
                    required=True,
                )
                if ch_enabled
                else None
            )
            limite_valor = _parse_non_negative_form_number(
                limite_valor_raw,
                "o tempo limite",
                required=bool(tipo_limitacao),
            )
        except ValueError as exc:
            return _render(f"Erro: {exc}")

        limite_total = limite_valor if tipo_limitacao == "total" else None
        limite_semestre = limite_valor if tipo_limitacao == "semestral" else None

        dup = conn.execute("SELECT id FROM atividade_base WHERE nome_conceito = ?", (nome,)).fetchone()
        if dup:
            return _render(f"Erro: Já existe atividade com este nome (ID {dup['id']}).")

        try:
            base_id, _versao_id = create_activity_with_initial_version(
                conn,
                nome=nome,
                descricao=descricao,
                eixo=axis,
                grupo=grupo,
                ch_por_evento=ch_por_evento,
                limite_semestre=limite_semestre,
                limite_total=limite_total,
                observacoes=observacoes,
            )
            conn.commit()
            flash("Atividade adicionada com sucesso.", "success")
            return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))
        except sqlite3.IntegrityError as e:
            conn.rollback()
            msg = str(e).lower()
            if 'not null constraint failed' in msg and 'atividade_versao.grupo' in msg:
                flash("Erro: selecione um número de grupo válido.", "error")
            elif 'unique' in msg and 'nome' in msg:
                flash("Erro: Atividade com este nome já existe.", "error")
            else:
                flash(f"Erro de integridade: {e}", "error")
        except Exception as exc:
            conn.rollback()
            flash(f"Erro ao adicionar atividade: {exc}", "error")
        return _render()

    return _render()


@admin_required
def admin_editar_atividade(atividade_id):
    """Compatibility entrypoint for the canonical exact-version editor."""
    conn = get_db_connection()
    version = get_atividade_versao_by_id(conn, atividade_id)
    if version is None:
        flash("Atividade não encontrada.", "error")
        return redirect(url_for("admin_atividades"))
    return redirect(
        url_for(
            "admin_catalogo_editar_versao",
            base_id=version["atividade_base_id"],
            versao_id=version["id"],
        )
    )


@admin_required
def admin_deletar_atividade(atividade_id):
    conn = get_db_connection()
    atividade = conn.execute("SELECT v.id,v.atividade_base_id,b.nome_conceito AS nome FROM atividade_versao v JOIN atividade_base b ON b.id=v.atividade_base_id WHERE v.id=?", (atividade_id,)).fetchone()
    if not atividade:
        flash("Atividade não encontrada.", "error")
        return redirect(url_for("admin_atividades"))

    requisicoes_em_uso = conn.execute(
        "SELECT COUNT(*) FROM requisicoes WHERE atividade_versao_id = ?",
        (atividade_id,),
    ).fetchone()[0]
    if requisicoes_em_uso:
        sufixo = "requisição" if requisicoes_em_uso == 1 else "requisições"
        flash(
            f"Não é possível excluir a atividade porque ela está vinculada a {requisicoes_em_uso} {sufixo}.",
            "error",
        )
        return redirect(url_for("admin_atividades"))

    if is_activity_base_referenced_by_assigned_matrix(conn, atividade['atividade_base_id']):
        flash(ACADEMIC_GRAPH_FROZEN_MESSAGE, "error")
        return redirect(url_for("admin_atividades"))

    try:
        ensure_matriz_atividade_links_table(conn)
        conn.execute("DELETE FROM matriz_atividade_versao_item WHERE atividade_versao_id = ?", (atividade_id,))
        conn.execute("DELETE FROM atividade_versao WHERE id = ?", (atividade_id,))
        if not conn.execute("SELECT 1 FROM atividade_versao WHERE atividade_base_id=?", (atividade['atividade_base_id'],)).fetchone():
            conn.execute("DELETE FROM atividade_base WHERE id=?", (atividade['atividade_base_id'],))
        conn.commit()
        flash("Atividade deletada com sucesso.", "success")
    except sqlite3.IntegrityError:
        conn.rollback()
        logging.exception("Erro de integridade ao deletar atividade %s", atividade_id)
        flash("Não foi possível excluir a atividade porque ela possui vínculos em uso no sistema.", "error")
    except Exception:
        conn.rollback()
        logging.exception("Erro inesperado ao deletar atividade %s", atividade_id)
        flash("Erro interno ao deletar atividade.", "error")
    return redirect(url_for("admin_atividades"))


@admin_required
def admin_atividades_importar_preview():
    mode = (request.form.get("mode") or request.args.get("mode") or "create_only").strip() or "create_only"
    if request.method == "POST":
        arquivo = request.files.get("csv_arquivo")
        if not arquivo or not getattr(arquivo, "filename", ""):
            flash("Selecione um arquivo CSV para validar.", "error")
            return render_template("admin_importar_atividades.html", preview=None, preview_key="", mode=mode)
        try:
            rel_path = save_upload(arquivo, ALLOWED_CSV, prefix="atividades", subdir="atividades_imports")
        except ValueError:
            flash("Envie um arquivo CSV válido.", "error")
            return render_template("admin_importar_atividades.html", preview=None, preview_key="", mode=mode)

        abs_path = os.path.join(current_app.config["UPLOAD_FOLDER"], rel_path)
        preview, storage_payload = _build_atividades_import_preview(abs_path, rel_path, mode)
        preview_key = ""
        if storage_payload is not None:
            preview_key = _store_atividades_import_preview(storage_payload)
        else:
            _delete_upload_relpath(rel_path)
        return render_template("admin_importar_atividades.html", preview=preview, preview_key=preview_key, mode=mode)
    return render_template("admin_importar_atividades.html", preview=None, preview_key="", mode=mode)


@admin_required
def admin_atividades_importar_confirmar():
    preview_key = (request.form.get("preview_key") or "").strip()
    payload = _load_atividades_import_preview(preview_key) if preview_key else None
    if not payload:
        flash("Preview de importação não encontrado ou expirado. Gere um novo preview.", "error")
        return redirect(url_for("admin_atividades", import_csv=1))

    conn = get_db_connection()
    created = 0
    updated = 0
    csv_relpath = payload.get("csv_relpath")
    try:
        for row in payload.get("rows", []):
            _upsert_grupo_definition(conn, row["tipo_atividade"], row["grupo_numero"], row["grupo_descricao"])
            if row.get("action") == "create":
                axis = 'AAC' if row['tipo_atividade'] == 'Acadêmica Complementar' else 'AEU'
                base_id = conn.execute("INSERT INTO atividade_base(nome_conceito,status) VALUES(?,'ativo') RETURNING id", (row['nome'],)).fetchone()[0]
                conn.execute("""INSERT INTO atividade_versao
                    (atividade_base_id,eixo,grupo,limite_total,limite_semestre,numero_versao,status)
                    VALUES(?,?,?,?,?,1,'ativa')""",
                    (base_id,axis,row['grupo'],row['limite_horas_total'],row['limite_horas_semestral']))
                created += 1
            elif row.get("action") == "update":
                axis = 'AAC' if row['tipo_atividade'] == 'Acadêmica Complementar' else 'AEU'
                try:
                    apply_latest_activity_version_semantic_changes(
                        conn,
                        row["existing_id"],
                        {
                            "grupo": row['grupo'],
                            "limite_total": row['limite_horas_total'],
                            "limite_semestre": row['limite_horas_semestral'],
                        },
                        expected_axis=axis,
                    )
                except ValueError as exc:
                    raise sqlite3.IntegrityError(str(exc)) from exc
                updated += 1
        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        flash(f"Falha ao confirmar importação: {exc}", "error")
        _delete_atividades_import_preview(preview_key)
        _delete_upload_relpath(csv_relpath)
        return redirect(url_for("admin_atividades", import_csv=1))

    _delete_atividades_import_preview(preview_key)
    _delete_upload_relpath(csv_relpath)
    flash(f"Importação concluída. Criadas: {created}. Atualizadas: {updated}.", "success")
    return redirect(url_for("admin_atividades"))


@admin_required
def admin_grupos_renomear():
    try:
        data = request.get_json(force=True) or {}
        tipo = (data.get('tipo_atividade') or '').strip()
        numero = str(data.get('numero') or '').strip()
        descricao = (data.get('descricao') or '').strip()
        if not tipo:
            return jsonify({ 'ok': False, 'error': 'tipo_atividade requerido' }), 400
        if not numero.isdigit():
            return jsonify({ 'ok': False, 'error': 'numero inválido' }), 400
        novo_label = f"{numero} - {descricao}" if descricao else numero
        conn = get_db_connection()
        _ensure_grupos_def_table(conn)
        eixo = 'AAC' if tipo == 'Acadêmica Complementar' else 'AEU'
        mutations = rename_current_activity_group_versions(
            conn,
            eixo=eixo,
            group_number=numero,
            new_label=novo_label,
        )
        updated = len(mutations)
        successors = sum(item["mode"] == "successor" for item in mutations)
        # upsert definition (compatible): try update, if none affected then insert
        cur2 = conn.execute(
            "UPDATE grupos_def SET descricao = ? WHERE tipo_atividade = ? AND numero = ?",
            (descricao, tipo, int(numero))
        )
        if cur2.rowcount == 0:
            conn.execute(
                "INSERT INTO grupos_def (tipo_atividade, numero, descricao) VALUES (?,?,?)",
                (tipo, int(numero), descricao)
            )
        conn.commit()
        return jsonify({ 'ok': True, 'updated': updated, 'successors': successors, 'label': novo_label })
    except Exception as e:
        logging.exception('Erro ao renomear grupo')
        return jsonify({ 'ok': False, 'error': 'erro_interno' }), 500


@admin_required
def admin_grupos_excluir():
    try:
        data = request.get_json(force=True) or {}
        tipo = (data.get('tipo_atividade') or '').strip()
        numero = str(data.get('numero') or '').strip()
        if not tipo:
            return jsonify({'ok': False, 'error': 'tipo_atividade requerido'}), 400
        if not numero.isdigit():
            return jsonify({'ok': False, 'error': 'numero inválido'}), 400

        conn = get_db_connection()
        _ensure_grupos_def_table(conn)

        prefixo = f"{numero}%"
        em_uso = conn.execute(
            """
            SELECT 1
              FROM atividade_versao
             WHERE eixo = ?
               AND grupo IS NOT NULL
               AND TRIM(grupo) <> ''
               AND TRIM(grupo) LIKE ?
             LIMIT 1
            """,
            ('AAC' if tipo == 'Acadêmica Complementar' else 'AEU', prefixo),
        ).fetchone()
        if em_uso:
            return jsonify({'ok': False, 'error': 'grupo_em_uso'}), 409

        cur = conn.execute(
            "DELETE FROM grupos_def WHERE tipo_atividade = ? AND numero = ?",
            (tipo, int(numero)),
        )
        conn.commit()
        return jsonify({'ok': True, 'deleted': cur.rowcount})
    except Exception:
        logging.exception('Erro ao excluir grupo')
        return jsonify({'ok': False, 'error': 'erro_interno'}), 500


@admin_required
def admin_catalogo_versoes():
    """
    Lista todas as atividade_base com contagem de versões.
    GET-only, sem escrita no banco.
    """
    conn = get_db_connection()
    bases = get_atividade_base_list(conn)
    return render_template(
        "admin_catalogo_versoes.html",
        bases=bases,
    )


@admin_required
def admin_catalogo_versao_detalhe(base_id: int):
    """
    Detalhe de uma atividade_base com todas as versões vinculadas.
    GET-only, sem escrita no banco.
    """
    conn = get_db_connection()
    base = get_atividade_base(conn, base_id)
    if not base:
        flash("Atividade-base não encontrada.", "error")
        return redirect(url_for("admin_catalogo_versoes"))
    versoes = get_versoes_por_base(conn, base_id)
    transicoes_origem = {
        row["from_atividade_versao_id"]
        for row in conn.execute(
            """
            SELECT DISTINCT from_atividade_versao_id
              FROM atividade_transicao
             WHERE from_atividade_versao_id IS NOT NULL
            """
        ).fetchall()
    }
    substituicao_candidatas = {}
    for origem in versoes:
        origem_id = origem["id"]
        origem_bloqueada = (
            origem["status"] != "ativa"
            or (origem["uso_em_matrizes"] or 0) > 0
            or origem_id in transicoes_origem
        )
        if origem_bloqueada:
            substituicao_candidatas[origem_id] = []
            continue
        substituicao_candidatas[origem_id] = [
            {
                "id": destino["id"],
                "eixo": destino["eixo"],
                "numero_versao": destino["numero_versao"],
            }
            for destino in versoes
            if destino["id"] != origem_id
            and destino["status"] == "ativa"
            and destino["eixo"] == origem["eixo"]
            and destino["id"] not in transicoes_origem
        ]
    transicoes_historico = get_atividade_transicoes_por_base(conn, base_id)
    nova_versao_url = url_for("admin_catalogo_nova_versao", base_id=base_id)
    if versoes:
        nova_versao_url = url_for(
            "admin_catalogo_nova_versao",
            base_id=base_id,
            **{"from": versoes[0]["id"]},
        )
    return render_template(
        "admin_catalogo_versao_detalhe.html",
        base=base,
        versoes=versoes,
        substituicao_candidatas=substituicao_candidatas,
        transicoes_historico=transicoes_historico,
        nova_versao_url=nova_versao_url,
    )


@admin_required
def admin_catalogo_nova_base():
    """Retire the incomplete base-only creator in favor of canonical Add Activity."""
    return redirect(url_for("admin_adicionar_atividade"))


@admin_required
def admin_catalogo_nova_versao(base_id: int):
    """Create the next version through the authoritative eight-field R4 form."""
    conn = get_db_connection()
    base = get_atividade_base(conn, base_id)
    if not base:
        flash("Atividade-base não encontrada.", "error")
        return redirect(url_for("admin_catalogo_versoes"))

    latest = get_latest_atividade_versao_for_base(conn, base_id)
    next_num = get_next_numero_versao(conn, base_id)
    form_action = url_for("admin_catalogo_nova_versao", base_id=base_id)
    form_title = f"Nova versão (será v{next_num})"
    submit_label = "Salvar nova versão"

    from_raw = (request.args.get("from") or "").strip()
    source = None
    source_error = None
    if not from_raw and latest is not None:
        from_raw = str(latest["id"])
    if from_raw:
        try:
            from_id = int(from_raw)
        except (TypeError, ValueError):
            source_error = "Versão anterior inválida."
        else:
            candidate_source = get_atividade_versao_by_id(conn, from_id)
            if candidate_source is None:
                source_error = "Versão anterior não encontrada."
            elif candidate_source["atividade_base_id"] != base_id:
                source_error = "Versão anterior deve pertencer à mesma atividade-base."
            else:
                source = candidate_source
    versoes_anteriores = [source] if source is not None else []
    grupos_por_tipo = _build_grupos_por_tipo_for_activity_form(conn)

    initial_payload = (
        _build_version_form_initial_payload(base, source, predecessor_id=source["id"])
        if source is not None else None
    )

    def _render_form(msg, values):
        if msg:
            flash(msg, "error")
        ch_mode = values.get("ch_por_evento_mode")
        ch_por_evento_enabled = (
            ch_mode == "enabled"
            if ch_mode is not None
            else str(values.get("ch_por_evento") or "").strip() != ""
        )
        versao_anterior_label = "Sem versão anterior"
        if source is not None:
            versao_anterior_label = f"v{source['numero_versao']}"
        return render_template(
            "admin_catalogo_versao_form.html",
            base=base,
            versoes_anteriores=versoes_anteriores,
            grupos_por_tipo=grupos_por_tipo,
            tipo_atividade=values["tipo_atividade"],
            tipo_locked=False,
            grupo=values["grupo"],
            nome=values["nome"],
            descricao=values["descricao"],
            tipo_limitacao=values["tipo_limitacao"],
            limite_valor=values["limite_valor"],
            ch_por_evento=values["ch_por_evento"],
            ch_por_evento_enabled=ch_por_evento_enabled,
            observacoes=values["observacoes"],
            versao_anterior_id=values["versao_anterior_id"],
            is_clone_create=True,
            versao_anterior_label=versao_anterior_label,
            form_snapshot_json=(
                json.dumps(initial_payload, ensure_ascii=False)
                if initial_payload is not None else None
            ),
            next_num=next_num,
            form_action=form_action,
            form_title=form_title,
            submit_label=submit_label,
            readonly=False,
        )

    if request.method == "POST":
        values = {
            "tipo_atividade": (request.form.get("tipo_atividade") or "").strip(),
            "grupo": (request.form.get("grupo") or "").strip(),
            "nome": (request.form.get("nome") or "").strip(),
            "descricao": (request.form.get("descricao") or "").strip(),
            "tipo_limitacao": (request.form.get("tipo_limitacao") or "").strip(),
            "limite_valor": (request.form.get("limite_valor") or "").strip(),
            "ch_por_evento": (request.form.get("ch_por_evento") or "").strip(),
            "ch_por_evento_mode": request.form.get("ch_por_evento_mode"),
            "observacoes": (request.form.get("observacoes") or "").strip(),
            "versao_anterior_id": (request.form.get("versao_anterior_id") or "").strip(),
        }

        def _render(msg):
            return _render_form(msg, values)

        eixo = _eixo_from_tipo_atividade(values["tipo_atividade"])
        if eixo is None:
            return _render("Selecione um Tipo válido.")
        grupo = _normalize_atividade_grupo(values["tipo_atividade"], values["grupo"])
        values["grupo"] = grupo or ""
        if not grupo:
            return _render("Selecione o Grupo (nº/descrição).")
        if not values["nome"]:
            return _render("Informe o Nome da atividade.")

        try:
            ch_enabled = (
                values["ch_por_evento_mode"] == "enabled"
                if values["ch_por_evento_mode"] is not None
                else bool(values["ch_por_evento"])
            )
            ch_por_evento = (
                _parse_non_negative_form_number(
                    values["ch_por_evento"],
                    "a Carga horária por evento",
                    required=True,
                )
                if ch_enabled
                else None
            )
            if not ch_enabled:
                values["ch_por_evento"] = ""
            tipo_limitacao = values["tipo_limitacao"]
            if tipo_limitacao not in {"", "total", "semestral"}:
                return _render("Selecione uma Limitação / Tempo limite válida.")
            limite_valor = _parse_non_negative_form_number(
                values["limite_valor"], "o tempo limite", required=bool(tipo_limitacao)
            )
        except ValueError as exc:
            return _render(str(exc))
        limite_semestre = limite_valor if tipo_limitacao == "semestral" else None
        limite_total = limite_valor if tipo_limitacao == "total" else None

        versao_anterior_id = None
        if values["versao_anterior_id"]:
            try:
                versao_anterior_id = int(values["versao_anterior_id"])
            except (TypeError, ValueError):
                return _render("Versão anterior inválida.")
            predecessor = get_atividade_versao_by_id(conn, versao_anterior_id)
            if predecessor is None:
                return _render("Versão anterior não encontrada.")
            if predecessor["atividade_base_id"] != base_id:
                return _render("Versão anterior deve pertencer à mesma atividade-base.")
        if source is not None and versao_anterior_id != int(source["id"]):
            return _render("A versão de origem deve permanecer selecionada como Versão anterior.")
        if source is None and versao_anterior_id is not None:
            return _render("A primeira versão não pode declarar predecessora.")

        candidate_payload = _normalized_version_form_payload(values)
        if initial_payload is not None and candidate_payload == initial_payload:
            return _render(
                "Nenhuma alteração efetiva informada. Altere ao menos um campo para criar a nova versão."
            )

        duplicate = conn.execute(
            "SELECT id FROM atividade_base WHERE nome_conceito = ? AND id <> ?",
            (values["nome"], base_id),
        ).fetchone()
        if duplicate:
            return _render("Já existe atividade com este Nome.")

        cross_axis = source is not None and source["eixo"] != eixo
        if cross_axis and not (source["eixo"] == "AAC" and eixo == "AEU"):
            return _render("A arquitetura atual permite transição de Tipo apenas de AAC para AEU.")

        observacoes = values["observacoes"] or None
        if source is not None and initial_payload["observacoes"] == candidate_payload["observacoes"]:
            observacao_aluno = source["observacao_aluno"]
            observacao_admin = source["observacao_admin"]
        else:
            observacao_aluno = observacoes
            observacao_admin = observacoes

        try:
            next_num = get_next_numero_versao(conn, base_id)
            conn.execute(
                "UPDATE atividade_base SET nome_conceito = ?, descricao = ? WHERE id = ?",
                (values["nome"], values["descricao"] or None, base_id),
            )
            new_version_id = conn.execute(
                """
                INSERT INTO atividade_versao (
                    atividade_base_id, eixo, grupo,
                    ch_por_evento, limite_semestre, limite_total,
                    observacao_aluno, observacao_admin, documentos_json,
                    vigencia_inicio, vigencia_fim, numero_versao, status, versao_anterior_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'rascunho', ?)
                RETURNING id
                """,
                (
                    base_id, eixo, grupo or None,
                    ch_por_evento, limite_semestre, limite_total,
                    observacao_aluno, observacao_admin,
                    source["documentos_json"] if source else "[]",
                    source["vigencia_inicio"] if source else None,
                    source["vigencia_fim"] if source else None,
                    next_num,
                    None if cross_axis else versao_anterior_id,
                ),
            ).fetchone()[0]
            if cross_axis:
                conn.execute(
                    """
                    INSERT INTO atividade_transicao (
                        from_atividade_versao_id, to_atividade_versao_id,
                        tipo_transicao, justificativa
                    ) VALUES (?, ?, 'aac_para_aeu', ?)
                    """,
                    (
                        source["id"],
                        new_version_id,
                        "Alteração de Tipo AAC para AEU na criação de nova versão.",
                    ),
                )
            conn.commit()
            flash("Versão criada com sucesso em rascunho.", "success")
            return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))
        except Exception as exc:
            conn.rollback()
            return _render(f"Erro ao criar versão: {exc}")

    prefill, prefill_error = _resolve_nova_versao_prefill(
        conn, base_id, from_raw
    )
    return _render_form(source_error or prefill_error, prefill)


def _versao_status_label(status: str | None) -> str:
    """Rótulo amigável de status de atividade_versao para o seletor de versões."""
    labels = {
        "rascunho": "Rascunho",
        "ativa": "Ativa",
        "inativa": "Inativa",
        "descontinuada": "Descontinuada",
        "substituida": "Substituída",
    }
    return labels.get(str(status or "").strip().lower(), str(status or "rascunho"))


def _get_versoes_para_switcher(conn, base_id: int) -> list[dict]:
    """Todas as versões da mesma atividade_base, na ordem canônica (numero_versao)."""
    rows = conn.execute(
        """
        SELECT id, numero_versao, status, eixo
          FROM atividade_versao
         WHERE atividade_base_id = ?
         ORDER BY numero_versao ASC, id ASC
        """,
        (base_id,),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "numero_versao": row["numero_versao"],
            "status": row["status"],
            "status_label": _versao_status_label(row["status"]),
        }
        for row in rows
    ]


@admin_required
def admin_catalogo_editar_versao(base_id: int, versao_id: int):
    """Edit/view one exact version through the same eight-field R4 form."""
    conn = get_db_connection()
    base = get_atividade_base(conn, base_id)
    if not base:
        flash("Atividade-base não encontrada.", "error")
        return redirect(url_for("admin_catalogo_versoes"))

    versao = get_atividade_versao_by_id(conn, versao_id)
    if not versao or versao["atividade_base_id"] != base_id:
        flash("Versão não encontrada para esta atividade-base.", "error")
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))

    versao_switcher = _get_versoes_para_switcher(conn, base_id)
    versao_atual_id = int(versao_id)
    nova_versao_url = url_for(
        "admin_catalogo_nova_versao",
        base_id=base_id,
        **{"from": str(versao_id)},
    )

    versao_anterior_label = "Sem versão anterior"
    if versao["versao_anterior_id"] is not None:
        _prev = get_atividade_versao_by_id(conn, versao["versao_anterior_id"])
        if _prev is not None:
            versao_anterior_label = f"v{_prev['numero_versao']}"

    # Modo explícito somente-leitura (?view=1), consistente com as convenções
    # SGAA existentes (admin_editar_atividade usa o mesmo parâmetro).  Força
    # leitura mesmo para rascunhos editáveis e nunca expõe ação de salvar.
    view_mode = (request.args.get("view") or "").strip().lower() in {
        "1", "true", "yes", "on",
    }
    readonly = view_mode or not can_activity_version_be_mutated_in_place(conn, versao_id)

    versoes_anteriores = [
        v
        for v in (
            get_versoes_da_base_por_eixo(conn, base_id, "AAC")
            + get_versoes_da_base_por_eixo(conn, base_id, "AEU")
        )
        if v["id"] != versao_id
    ]

    form_action = url_for("admin_catalogo_editar_versao", base_id=base_id, versao_id=versao_id)
    _num = versao["numero_versao"]
    form_title = f"Ver versão v{_num}" if readonly else f"Editar versão v{_num}"
    submit_label = "Salvar alterações"
    grupos_por_tipo = _build_grupos_por_tipo_for_activity_form(conn)
    tipo_limitacao, limite_valor = _limitation_form_values(versao)
    initial_values = {
        "tipo_atividade": _tipo_atividade_from_eixo(versao["eixo"]),
        "grupo": versao["grupo"] or "",
        "nome": base["nome_conceito"],
        "descricao": base["descricao"] or "",
        "tipo_limitacao": tipo_limitacao,
        "limite_valor": limite_valor,
        "ch_por_evento": _display_number(versao["ch_por_evento"]),
        "observacoes": _canonical_version_observacoes(versao),
        "versao_anterior_id": (
            "" if versao["versao_anterior_id"] is None
            else str(versao["versao_anterior_id"])
        ),
    }
    initial_payload = _normalized_version_form_payload(initial_values)

    def _render_form(msg, values, *, force_readonly=False):
        if msg:
            flash(msg, "error")
        ch_mode = values.get("ch_por_evento_mode")
        ch_por_evento_enabled = (
            ch_mode == "enabled"
            if ch_mode is not None
            else str(values.get("ch_por_evento") or "").strip() != ""
        )
        return render_template(
            "admin_catalogo_versao_form.html",
            base=base,
            versoes_anteriores=versoes_anteriores,
            grupos_por_tipo=grupos_por_tipo,
            tipo_atividade=values["tipo_atividade"],
            tipo_locked=True,
            grupo=values["grupo"],
            nome=values["nome"],
            descricao=values["descricao"],
            tipo_limitacao=values["tipo_limitacao"],
            limite_valor=values["limite_valor"],
            ch_por_evento=values["ch_por_evento"],
            ch_por_evento_enabled=ch_por_evento_enabled,
            observacoes=values["observacoes"],
            versao_anterior_id=values["versao_anterior_id"],
            form_action=form_action,
            form_title=form_title,
            submit_label=submit_label,
            readonly=readonly or force_readonly,
            versao_switcher=versao_switcher,
            versao_atual_id=versao_atual_id,
            nova_versao_url=nova_versao_url,
            versao_anterior_label=versao_anterior_label,
            form_snapshot_json=(
                None if readonly else json.dumps(initial_payload, ensure_ascii=False)
            ),
        )

    if request.method == "POST":
        if readonly:
            message = (
                "Apenas versões em rascunho podem ser editadas."
                if versao["status"] != "rascunho"
                else (
                    "Modo de visualização: a edição desta versão não está disponível."
                    if view_mode
                    else "Esta versão já está em uso e não pode mais ser editada."
                )
            )
            flash(message, "error")
            return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))

        values = {
            "tipo_atividade": (request.form.get("tipo_atividade") or "").strip(),
            "grupo": (request.form.get("grupo") or "").strip(),
            "nome": (request.form.get("nome") or "").strip(),
            "descricao": (request.form.get("descricao") or "").strip(),
            "tipo_limitacao": (request.form.get("tipo_limitacao") or "").strip(),
            "limite_valor": (request.form.get("limite_valor") or "").strip(),
            "ch_por_evento": (request.form.get("ch_por_evento") or "").strip(),
            "ch_por_evento_mode": request.form.get("ch_por_evento_mode"),
            "observacoes": (request.form.get("observacoes") or "").strip(),
            "versao_anterior_id": (request.form.get("versao_anterior_id") or "").strip(),
        }

        def _render(msg):
            return _render_form(msg, values)

        eixo = _eixo_from_tipo_atividade(values["tipo_atividade"])
        if eixo != versao["eixo"]:
            return _render("Para alterar o Tipo, crie uma nova versão a partir desta versão.")
        grupo = _normalize_atividade_grupo(values["tipo_atividade"], values["grupo"])
        values["grupo"] = grupo or ""
        if not grupo:
            return _render("Selecione o Grupo (nº/descrição).")
        if not values["nome"]:
            return _render("Informe o Nome da atividade.")

        try:
            ch_enabled = (
                values["ch_por_evento_mode"] == "enabled"
                if values["ch_por_evento_mode"] is not None
                else bool(values["ch_por_evento"])
            )
            ch_por_evento = (
                _parse_non_negative_form_number(
                    values["ch_por_evento"],
                    "a Carga horária por evento",
                    required=True,
                )
                if ch_enabled
                else None
            )
            if not ch_enabled:
                values["ch_por_evento"] = ""
            tipo_limitacao = values["tipo_limitacao"]
            if tipo_limitacao not in {"", "total", "semestral"}:
                return _render("Selecione uma Limitação / Tempo limite válida.")
            limite_valor = _parse_non_negative_form_number(
                values["limite_valor"], "o tempo limite", required=bool(tipo_limitacao)
            )
        except ValueError as exc:
            return _render(str(exc))
        limite_semestre = limite_valor if tipo_limitacao == "semestral" else None
        limite_total = limite_valor if tipo_limitacao == "total" else None

        versao_anterior_id = None
        if values["versao_anterior_id"]:
            try:
                versao_anterior_id = int(values["versao_anterior_id"])
            except (TypeError, ValueError):
                return _render("Versão anterior inválida.")
            if versao_anterior_id == versao_id:
                return _render("Versão anterior não pode ser a própria versão.")
            prev = conn.execute(
                "SELECT atividade_base_id, eixo FROM atividade_versao WHERE id = ?",
                (versao_anterior_id,),
            ).fetchone()
            if not prev:
                return _render("Versão anterior não encontrada.")
            if prev["atividade_base_id"] != base_id:
                return _render("Versão anterior deve pertencer à mesma atividade-base.")
            if prev["eixo"] != eixo:
                return _render("Versão anterior deve ter o mesmo Tipo da versão.")

        candidate_payload = _normalized_version_form_payload(values)
        if candidate_payload == initial_payload:
            return _render("Nenhuma alteração efetiva informada.")

        duplicate = conn.execute(
            "SELECT id FROM atividade_base WHERE nome_conceito = ? AND id <> ?",
            (values["nome"], base_id),
        ).fetchone()
        if duplicate:
            return _render("Já existe atividade com este Nome.")

        observacoes_changed = (
            candidate_payload["observacoes"] != initial_payload["observacoes"]
        )
        changes = {
            "eixo": eixo,
            "grupo": grupo or None,
            "ch_por_evento": ch_por_evento,
            "limite_semestre": limite_semestre,
            "limite_total": limite_total,
            "versao_anterior_id": versao_anterior_id,
        }
        if observacoes_changed:
            observacoes = values["observacoes"] or None
            changes["observacao_aluno"] = observacoes
            changes["observacao_admin"] = observacoes

        try:
            conn.execute(
                "UPDATE atividade_base SET nome_conceito = ?, descricao = ? WHERE id = ?",
                (values["nome"], values["descricao"] or None, base_id),
            )
            apply_activity_version_semantic_changes(
                conn,
                versao_id,
                changes,
                create_successor_if_frozen=False,
            )
            conn.commit()
            flash("Versão atualizada com sucesso.", "success")
            return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))
        except Exception as exc:
            conn.rollback()
            return _render(f"Erro ao atualizar versão: {exc}")

    return _render_form(None, initial_values)


@admin_required
def admin_catalogo_ativar_versao(base_id: int, versao_id: int):
    """
    Ativação mínima de uma atividade_versao em rascunho.

    Permite mudar status = 'rascunho' -> 'ativa' por ação administrativa
    explícita. Validações server-side:
      - atividade_base existe
      - atividade_versao existe e pertence ao base_id da URL
      - status atual == 'rascunho'

    Operação: UPDATE atividade_versao SET status = 'ativa'
    WHERE id = ? AND status = 'rascunho'. Se rowcount != 1, rollback.

    Não cria entrada em matriz_atividade_versao_item, não altera
    requisicoes, atividade_transicao, snapshot, cálculo ou aluno.
    Não usa fallback silencioso nem primeira ativa.
    """
    conn = get_db_connection()
    base = get_atividade_base(conn, base_id)
    if not base:
        flash("Atividade-base não encontrada.", "error")
        return redirect(url_for("admin_catalogo_versoes"))

    versao = get_atividade_versao_by_id(conn, versao_id)
    if not versao or versao["atividade_base_id"] != base_id:
        flash("Versão não encontrada para esta atividade-base.", "error")
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))

    if versao["status"] != "rascunho":
        flash("Apenas versões em rascunho podem ser ativadas.", "error")
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))

    if is_activity_version_referenced_by_assigned_matrix(conn, versao_id):
        flash(ACADEMIC_VERSION_FROZEN_MESSAGE, "error")
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))

    try:
        cur = conn.execute(
            "UPDATE atividade_versao "
            "SET status = 'ativa' "
            "WHERE id = ? AND status = 'rascunho'",
            (versao_id,),
        )
        if cur.rowcount != 1:
            conn.rollback()
            flash(
                "Ativação não aplicada: a versão não está mais em rascunho.",
                "error",
            )
            return redirect(
                url_for("admin_catalogo_versao_detalhe", base_id=base_id)
            )
        conn.commit()
        flash("Versão ativada com sucesso.", "success")
    except Exception as exc:
        conn.rollback()
        flash(f"Erro ao ativar versão: {exc}", "error")

    return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))


@admin_required
def admin_catalogo_inativar_versao(base_id: int, versao_id: int):
    """
    Inativação administrativa de uma atividade_versao ativa.

    Permite a transição status = 'ativa' → 'inativa'.
    A versão deixa de ser considerada ativa pelo resolvedor sem qualquer
    alteração no resolvedor, writer, requisicoes, snapshot, cálculo ou aluno.

    Bloqueio B1 — Rejeita se houver vínculo em matriz_atividade_versao_item.
    O admin deve remover o vínculo na tela de versões da matriz primeiro.

    Não remove vínculos, não cria atividade_transicao, não altera resolvedor,
    não faz fallback, não escolhe substituta, sem efeito colateral silencioso.
    """
    conn = get_db_connection()
    ensure_atividade_versioning_schema(conn)

    base = get_atividade_base(conn, base_id)
    if not base:
        flash("Atividade-base não encontrada.", "error")
        return redirect(url_for("admin_catalogo_versoes"))

    versao = get_atividade_versao_by_id(conn, versao_id)
    if not versao or versao["atividade_base_id"] != base_id:
        flash("Versão não encontrada para esta atividade-base.", "error")
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))

    if versao["status"] != "ativa":
        flash("Apenas versões ativas podem ser inativadas.", "error")
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))

    usage = get_atividade_versao_usage_counts(conn, versao_id)
    if usage["matriz_atividade_versao_item"] > 0:
        flash(
            f"Não é possível inativar: esta versão está vinculada a "
            f"{usage['matriz_atividade_versao_item']} matriz(es). "
            "Remova o vínculo na tela de versões da matriz antes de inativar.",
            "error",
        )
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))

    try:
        cur = conn.execute(
            "UPDATE atividade_versao SET status = 'inativa'"
            " WHERE id = ? AND status = 'ativa'",
            (versao_id,),
        )
        if cur.rowcount != 1:
            conn.rollback()
            flash("Inativação não aplicada: a versão não está mais ativa.", "error")
            return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))
        conn.commit()
        flash("Versão inativada com sucesso.", "success")
    except Exception as exc:
        conn.rollback()
        flash(f"Erro ao inativar versão: {exc}", "error")

    return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))


@admin_required
def admin_catalogo_descontinuar_versao(base_id: int, versao_id: int):
    """
    Descontinuação administrativa de uma atividade_versao ativa.

    Permite a transição status = 'ativa' → 'descontinuada'.
    A versão deixa de ser considerada ativa pelo resolvedor sem qualquer
    alteração no resolvedor, writer, requisicoes, snapshot, cálculo ou aluno.

    Bloqueio B1 — Rejeita se houver vínculo em matriz_atividade_versao_item.
    O admin deve remover o vínculo na tela de versões da matriz primeiro.

    Não remove vínculos, não cria atividade_transicao, não altera resolvedor,
    não faz fallback, não escolhe substituta, sem efeito colateral silencioso.
    """
    conn = get_db_connection()
    ensure_atividade_versioning_schema(conn)

    base = get_atividade_base(conn, base_id)
    if not base:
        flash("Atividade-base não encontrada.", "error")
        return redirect(url_for("admin_catalogo_versoes"))

    versao = get_atividade_versao_by_id(conn, versao_id)
    if not versao or versao["atividade_base_id"] != base_id:
        flash("Versão não encontrada para esta atividade-base.", "error")
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))

    if versao["status"] != "ativa":
        flash("Apenas versões ativas podem ser descontinuadas.", "error")
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))

    usage = get_atividade_versao_usage_counts(conn, versao_id)
    if usage["matriz_atividade_versao_item"] > 0:
        flash(
            f"Não é possível descontinuar: esta versão está vinculada a "
            f"{usage['matriz_atividade_versao_item']} matriz(es). "
            "Remova o vínculo na tela de versões da matriz antes de descontinuar.",
            "error",
        )
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))

    try:
        cur = conn.execute(
            "UPDATE atividade_versao SET status = 'descontinuada'"
            " WHERE id = ? AND status = 'ativa'",
            (versao_id,),
        )
        if cur.rowcount != 1:
            conn.rollback()
            flash(
                "Descontinuação não aplicada: a versão não está mais ativa.", "error"
            )
            return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))
        conn.commit()
        flash("Versão descontinuada com sucesso.", "success")
    except Exception as exc:
        conn.rollback()
        flash(f"Erro ao descontinuar versão: {exc}", "error")

    return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))


@admin_required
def admin_catalogo_substituir_versao(base_id: int, versao_id: int):
    """
    Substitui explicitamente uma atividade_versao ativa por outra ativa
    da mesma atividade-base e do mesmo eixo.
    """
    conn = get_db_connection()
    ensure_atividade_versioning_schema(conn)

    base = get_atividade_base(conn, base_id)
    if not base:
        flash("Atividade-base nÃ£o encontrada.", "error")
        return redirect(url_for("admin_catalogo_versoes"))

    origem = get_atividade_versao_by_id(conn, versao_id)
    if not origem or origem["atividade_base_id"] != base_id:
        flash("VersÃ£o de origem nÃ£o encontrada para esta atividade-base.", "error")
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))

    if origem["status"] != "ativa":
        flash("Apenas versÃµes ativas podem ser substituÃ­das.", "error")
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))

    origem_usage = get_atividade_versao_usage_counts(conn, versao_id)
    if origem_usage["matriz_atividade_versao_item"] > 0:
        flash(
            "NÃ£o Ã© possÃ­vel substituir: esta versÃ£o estÃ¡ vinculada a matriz.",
            "error",
        )
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))
    if origem_usage["atividade_transicao_origem"] > 0:
        flash(
            "NÃ£o Ã© possÃ­vel substituir: a versÃ£o de origem jÃ¡ possui transiÃ§Ã£o registrada.",
            "error",
        )
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))

    to_versao_id_raw = (request.form.get("to_versao_id") or "").strip()
    if not to_versao_id_raw:
        flash("Selecione a versÃ£o de destino para substituir.", "error")
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))
    try:
        to_versao_id = int(to_versao_id_raw)
    except (TypeError, ValueError):
        flash("VersÃ£o de destino invÃ¡lida.", "error")
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))

    if to_versao_id == versao_id:
        flash("A versÃ£o de destino deve ser diferente da origem.", "error")
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))

    destino = get_atividade_versao_by_id(conn, to_versao_id)
    if not destino:
        flash("VersÃ£o de destino nÃ£o encontrada.", "error")
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))
    if destino["status"] != "ativa":
        flash("A versÃ£o de destino deve estar ativa.", "error")
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))
    if destino["atividade_base_id"] != base_id:
        flash("A versÃ£o de destino deve pertencer Ã  mesma atividade-base.", "error")
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))
    if destino["eixo"] != origem["eixo"]:
        flash("A versÃ£o de destino deve ter o mesmo eixo da origem.", "error")
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))

    destino_usage = get_atividade_versao_usage_counts(conn, to_versao_id)
    if destino_usage["atividade_transicao_origem"] > 0:
        flash(
            "NÃ£o Ã© possÃ­vel substituir: a versÃ£o de destino jÃ¡ possui transiÃ§Ã£o registrada como origem.",
            "error",
        )
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))

    try:
        cur = conn.execute(
            "UPDATE atividade_versao SET status = 'substituida' "
            "WHERE id = ? AND status = 'ativa'",
            (versao_id,),
        )
        if cur.rowcount != 1:
            conn.rollback()
            flash(
                "SubstituiÃ§Ã£o nÃ£o aplicada: a versÃ£o de origem nÃ£o estÃ¡ mais ativa.",
                "error",
            )
            return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))

        conn.execute(
            """
            INSERT INTO atividade_transicao (
                from_atividade_versao_id,
                to_atividade_versao_id,
                tipo_transicao
            ) VALUES (?, ?, 'mesmo_eixo')
            """,
            (versao_id, to_versao_id),
        )
        conn.commit()
        flash("VersÃ£o substituÃ­da com sucesso.", "success")
    except Exception as exc:
        conn.rollback()
        flash(f"Erro ao substituir versÃ£o: {exc}", "error")

    return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))


bp_admin_atividades = Blueprint("admin_atividades_blueprint", __name__)

LEGACY_ROUTE_SPECS = configure_legacy_routes(
    bp_admin_atividades,
    (
        LegacyRouteSpec(
            '/admin/atividades',
            'admin_atividades',
            admin_atividades,
            ('GET',),
        ),
        LegacyRouteSpec(
            '/admin/atividades/academicas',
            'admin_atividades_academicas',
            admin_atividades_academicas,
            ('GET',),
        ),
        LegacyRouteSpec(
            '/admin/atividades/extensao',
            'admin_atividades_extensao',
            admin_atividades_extensao,
            ('GET',),
        ),
        LegacyRouteSpec(
            '/admin/adicionar_atividade',
            'admin_adicionar_atividade',
            admin_adicionar_atividade,
            ('GET', 'POST'),
        ),
        LegacyRouteSpec(
            '/admin/editar_atividade/<int:atividade_id>',
            'admin_editar_atividade',
            admin_editar_atividade,
            ('GET', 'POST'),
        ),
        LegacyRouteSpec(
            '/admin/deletar_atividade/<int:atividade_id>',
            'admin_deletar_atividade',
            admin_deletar_atividade,
            ('POST',),
        ),
        LegacyRouteSpec(
            '/admin/atividades/importar/preview',
            'admin_atividades_importar_preview',
            admin_atividades_importar_preview,
            ('GET', 'POST'),
        ),
        LegacyRouteSpec(
            '/admin/atividades/importar/confirmar',
            'admin_atividades_importar_confirmar',
            admin_atividades_importar_confirmar,
            ('POST',),
        ),
        LegacyRouteSpec(
            '/admin/grupos/renomear',
            'admin_grupos_renomear',
            admin_grupos_renomear,
            ('POST',),
        ),
        LegacyRouteSpec(
            '/admin/grupos/excluir',
            'admin_grupos_excluir',
            admin_grupos_excluir,
            ('POST',),
        ),
        LegacyRouteSpec(
            '/admin/catalogo-versoes',
            'admin_catalogo_versoes',
            admin_catalogo_versoes,
            ('GET',),
        ),
        LegacyRouteSpec(
            '/admin/catalogo-versoes/<int:base_id>',
            'admin_catalogo_versao_detalhe',
            admin_catalogo_versao_detalhe,
            ('GET',),
        ),
        LegacyRouteSpec(
            '/admin/catalogo-versoes/nova-base',
            'admin_catalogo_nova_base',
            admin_catalogo_nova_base,
            ('GET', 'POST'),
        ),
        LegacyRouteSpec(
            '/admin/catalogo-versoes/<int:base_id>/nova-versao',
            'admin_catalogo_nova_versao',
            admin_catalogo_nova_versao,
            ('GET', 'POST'),
        ),
        LegacyRouteSpec(
            '/admin/catalogo-versoes/<int:base_id>/versoes/<int:versao_id>/editar',
            'admin_catalogo_editar_versao',
            admin_catalogo_editar_versao,
            ('GET', 'POST'),
        ),
        LegacyRouteSpec(
            '/admin/catalogo-versoes/<int:base_id>/versoes/<int:versao_id>/ativar',
            'admin_catalogo_ativar_versao',
            admin_catalogo_ativar_versao,
            ('POST',),
        ),
        LegacyRouteSpec(
            '/admin/catalogo-versoes/<int:base_id>/versoes/<int:versao_id>/inativar',
            'admin_catalogo_inativar_versao',
            admin_catalogo_inativar_versao,
            ('POST',),
        ),
        LegacyRouteSpec(
            '/admin/catalogo-versoes/<int:base_id>/versoes/<int:versao_id>/descontinuar',
            'admin_catalogo_descontinuar_versao',
            admin_catalogo_descontinuar_versao,
            ('POST',),
        ),
        LegacyRouteSpec(
            '/admin/catalogo-versoes/<int:base_id>/versoes/<int:versao_id>/substituir',
            'admin_catalogo_substituir_versao',
            admin_catalogo_substituir_versao,
            ('POST',),
        ),
    ),
)


__all__ = [
    'ATIVIDADES_IMPORT_REQUIRED_HEADERS',
    '_normalize_import_header_name',
    '_canonicalize_tipo_atividade',
    '_canonicalize_tipo_limitacao',
    '_parse_csv_boolean',
    '_parse_optional_positive_int',
    '_build_grupo_label',
    '_format_preview_limitacao',
    '_ensure_grupos_def_table',
    '_upsert_grupo_definition',
    '_atividades_import_preview_dir',
    '_atividades_import_preview_path',
    '_store_atividades_import_preview',
    '_load_atividades_import_preview',
    '_delete_atividades_import_preview',
    '_delete_upload_relpath',
    '_build_atividades_import_preview',
    'admin_atividades',
    'admin_atividades_academicas',
    'admin_atividades_extensao',
    'admin_adicionar_atividade',
    'admin_editar_atividade',
    'admin_deletar_atividade',
    'admin_atividades_importar_preview',
    'admin_atividades_importar_confirmar',
    'admin_grupos_renomear',
    'admin_grupos_excluir',
    'admin_catalogo_versoes',
    'admin_catalogo_versao_detalhe',
    'admin_catalogo_nova_base',
    'admin_catalogo_nova_versao',
    'admin_catalogo_editar_versao',
    'admin_catalogo_ativar_versao',
    'admin_catalogo_inativar_versao',
    'admin_catalogo_descontinuar_versao',
    'admin_catalogo_substituir_versao',
    'LEGACY_ROUTE_SPECS',
    'bp_admin_atividades',
]
