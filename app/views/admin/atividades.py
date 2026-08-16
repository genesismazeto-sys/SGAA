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
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)
from werkzeug.utils import secure_filename

from app.activity_catalog import (
    _build_grupo_label,
    _canonicalize_tipo_limitacao,
    _normalize_atividade_grupo,
    get_atividade_base,
    get_atividade_base_list,
    get_atividade_transicoes_por_base,
    get_atividade_versao_by_id,
    get_atividade_versao_usage_counts,
    get_legacy_map_list,
    get_next_numero_versao,
    get_norma_by_id,
    get_norma_list,
    get_versoes_da_base_por_eixo,
    get_versoes_por_base,
    parse_documentos_json,
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
    is_activity_referenced_by_assigned_matrix,
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


logger = logging.getLogger("main")


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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS grupos_def (
            tipo_atividade TEXT NOT NULL,
            numero INTEGER NOT NULL,
            descricao TEXT,
            PRIMARY KEY (tipo_atividade, numero)
        )
        """
    )


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


def _resolve_nova_versao_prefill(conn, base_id: int, from_raw) -> tuple[dict, str | None]:
    """
    FC-07 — Resolve o estado inicial do formulário de nova versão.

    `?from=<atividade_versao_id>` copia os campos editáveis do predecessor
    (mesma atividade-base) e o pré-seleciona como versao_anterior_id.

    Estritamente read-only. Fontes inválidas (malformadas, inexistentes ou de
    outra atividade-base) retornam o formulário em branco junto da mensagem de
    erro para flash pelo chamador (mesmo padrão de _render_form no POST).
    """
    blank = {
        "norma_id": "",
        "grupo": "",
        "ch_por_evento": "",
        "limite_semestre": "",
        "limite_total": "",
        "observacao_aluno": "",
        "observacao_admin": "",
        "vigencia_inicio": "",
        "vigencia_fim": "",
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
    return (
        {
            "norma_id": str(origem["norma_id"]),
            "grupo": origem["grupo"] or "",
            "ch_por_evento": _display_number(origem["ch_por_evento"]),
            "limite_semestre": _display_number(origem["limite_semestre"]),
            "limite_total": _display_number(origem["limite_total"]),
            "observacao_aluno": origem["observacao_aluno"] or "",
            "observacao_admin": origem["observacao_admin"] or "",
            "vigencia_inicio": origem["vigencia_inicio"] or "",
            "vigencia_fim": origem["vigencia_fim"] or "",
            "versao_anterior_id": str(origem["id"]),
        },
        None,
    )


def _build_atividades_import_preview(csv_abspath: str, csv_relpath: str, mode: str) -> tuple[dict, dict | None]:
    conn = get_db_connection()
    existing_rows = conn.execute("SELECT id, nome FROM atividades").fetchall()
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
    base_from = " FROM atividades"
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
        "SELECT *, (SELECT atividade_base_id FROM atividade_legacy_map"
        " WHERE atividade_id_legacy = id) AS base_id"
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
    # Load documentos obrigatórios per atividade (tolerant parser)
    docs_por_atividade = {}
    try:
        cols = [c[1] for c in conn.execute("PRAGMA table_info(atividades)").fetchall()]
        if 'documentos_json' in cols:
            for a in atividades:
                docs_por_atividade[a['id']] = parse_documentos_json(a.get('documentos_json') if isinstance(a, dict) else a['documentos_json'])
    except Exception:
        pass
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
        # also derive from atividades for missing entries
        rows2 = conn.execute(
            "SELECT tipo_atividade, grupo FROM atividades WHERE grupo IS NOT NULL AND TRIM(grupo) <> ''"
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
          FROM atividades
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
    base_from = " FROM atividades WHERE tipo_atividade = 'Acadêmica Complementar'"
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
    base_from = " FROM atividades WHERE tipo_atividade = 'Extensão Universitária'"
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
    # Build mapping of existing group numbers -> description per activity type
    def build_grupos_por_tipo(conn):
        rows = conn.execute(
            "SELECT tipo_atividade, grupo FROM atividades WHERE grupo IS NOT NULL AND TRIM(grupo) <> ''"
        ).fetchall()
        grupos = {}
        for r in rows:
            tipo = r[0]
            label = (r[1] or '').strip()
            m = re.match(r'^\s*(\d+)\s*-\s*(.*)$', label)
            if m:
                num = m.group(1)
                desc = (m.group(2) or '').strip()
            else:
                m2 = re.match(r'^\s*(\d+)\s*$', label)
                if not m2:
                    # ignore labels without numeric prefix for this mapping
                    continue
                num = m2.group(1)
                desc = ''
            if tipo not in grupos:
                grupos[tipo] = {}
            # prefer first non-empty description seen
            if num not in grupos[tipo] or (not grupos[tipo][num] and desc):
                grupos[tipo][num] = desc
        # merge explicit definitions from grupos_def if present
        try:
            rows2 = conn.execute("SELECT tipo_atividade, numero, descricao FROM grupos_def").fetchall()
            for r2 in rows2:
                tipo2, num2, desc2 = r2[0], str(r2[1]), (r2[2] or '').strip()
                if tipo2 not in grupos:
                    grupos[tipo2] = {}
                # explicit def has priority
                grupos[tipo2][num2] = desc2
        except Exception:
            pass
        return grupos

    if request.method == "POST":
        grupo = _normalize_atividade_grupo(request.form.get("tipo_atividade"), request.form.get("grupo"))
        nome = (request.form.get("nome") or "").strip()
        descricao = (request.form.get("descricao") or "").strip() or None
        # Campo opcional: pode não vir do formulário
        limite_horas_raw = request.form.get("limite_horas")
        try:
            limite_horas = int(limite_horas_raw) if (limite_horas_raw is not None and str(limite_horas_raw).strip() != "") else None
        except (TypeError, ValueError):
            limite_horas = None
        tipo_atividade = request.form["tipo_atividade"]
        # Hidden chega como '0'/'1'; evite tratar '0' como truthy
        tem_limitacao = 1 if (request.form.get("tem_limitacao") or "0") in ("1", "true", "on", "yes") else 0
        tipo_limitacao = request.form.get("tipo_limitacao") if tem_limitacao else None
        limite_horas_total = request.form.get("limite_horas_total") if tem_limitacao and tipo_limitacao == "total" else None
        limite_horas_semestral = request.form.get("limite_horas_semestral") if tem_limitacao and tipo_limitacao == "semestral" else None
        # Se há limitação, exigir tipo_limitacao válido
        if tem_limitacao and tipo_limitacao not in ("total", "semestral"):
            flash("Erro: selecione o tipo de limitação (Total ou Semestral).", "error")
            conn = get_db_connection()
            grupos_por_tipo = build_grupos_por_tipo(conn)
            return render_template("admin_adicionar_atividade.html", grupos_por_tipo=grupos_por_tipo)
        # Satisfaz o CHECK da coluna: quando não há limitação, persistimos um valor válido
        if not tem_limitacao:
            tipo_limitacao = "total"
            limite_horas_total = None
            limite_horas_semestral = None

        conn = get_db_connection()
        # Validações básicas
        if not grupo:
            flash("Erro: selecione o Grupo (nº/descrição).", "error")
            grupos_por_tipo = build_grupos_por_tipo(conn)
            return render_template("admin_adicionar_atividade.html", grupos_por_tipo=grupos_por_tipo)
        if not nome:
            flash("Erro: informe o Nome da atividade.", "error")
            grupos_por_tipo = build_grupos_por_tipo(conn)
            return render_template("admin_adicionar_atividade.html", grupos_por_tipo=grupos_por_tipo)
        # Checagem explícita de duplicidade por nome (escopo global)
        dup = conn.execute("SELECT id, tipo_atividade, grupo FROM atividades WHERE nome = ?", (nome,)).fetchone()
        if dup:
            flash(f"Erro: Já existe atividade com este nome (ID {dup['id']}, Tipo: {dup['tipo_atividade']}, Grupo: {dup['grupo']}).", "error")
            grupos_por_tipo = build_grupos_por_tipo(conn)
            return render_template("admin_adicionar_atividade.html", grupos_por_tipo=grupos_por_tipo)
        try:
            conn.execute(
                """
                INSERT INTO atividades
                (grupo, nome, descricao, limite_horas, tipo_atividade, tem_limitacao, tipo_limitacao, limite_horas_total, limite_horas_semestral, documentos_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    grupo,
                    nome,
                    descricao,
                    limite_horas,
                    tipo_atividade,
                    tem_limitacao,
                    tipo_limitacao,
                    limite_horas_total,
                    limite_horas_semestral,
                    request.form.get("documentos_json") or None,
                ),
            )
            conn.commit()
            flash("Atividade adicionada com sucesso.", "success")
            return redirect(url_for("admin_atividades"))
        except sqlite3.IntegrityError as e:
            msg = str(e).lower()
            if 'not null constraint failed' in msg and 'atividades.grupo' in msg:
                flash("Erro: selecione um número de grupo válido.", "error")
            elif 'unique' in msg and 'nome' in msg:
                flash("Erro: Atividade com este nome já existe.", "error")
            else:
                flash(f"Erro de integridade: {e}", "error")
        grupos_por_tipo = build_grupos_por_tipo(conn)
        return render_template("admin_adicionar_atividade.html", grupos_por_tipo=grupos_por_tipo)
    # GET
    conn = get_db_connection()
    grupos_por_tipo = build_grupos_por_tipo(conn)
    return render_template("admin_adicionar_atividade.html", grupos_por_tipo=grupos_por_tipo)


@admin_required
def admin_editar_atividade(atividade_id):
    # Força recarregar o template a cada requisição (evita servir versão antiga em dev)
    try:
        current_app.jinja_env.cache.clear()
    except Exception:
        pass
    conn = get_db_connection()
    atividade = conn.execute("SELECT * FROM atividades WHERE id = ?", (atividade_id,)).fetchone()
    if not atividade:
        flash("Atividade não encontrada.", "error")
        return redirect(url_for("admin_atividades"))
    # Docs salvos (normalizados) para inicializar chips no template
    try:
        atividade_docs_saved = parse_documentos_json(atividade['documentos_json'] if 'documentos_json' in atividade.keys() else None)
    except Exception:
        atividade_docs_saved = []

    # Build mapping of existing group numbers -> description per activity type (for UI parity with 'Adicionar')
    def build_grupos_por_tipo(c):
        grupos = {}
        # explicit definitions first
        try:
            rows = c.execute("SELECT tipo_atividade, numero, descricao FROM grupos_def").fetchall()
            for r in rows:
                tipo, num, desc = r[0], str(r[1]), (r[2] or '').strip()
                grupos.setdefault(tipo, {})[num] = desc
        except Exception:
            pass
        # derive from atividades for gaps
        rows2 = c.execute(
            "SELECT tipo_atividade, grupo FROM atividades WHERE grupo IS NOT NULL AND TRIM(grupo) <> ''"
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

    if request.method == "POST":
        # Use .get to avoid BadRequestKeyError if inputs are missing
        grupo = _normalize_atividade_grupo(request.form.get("tipo_atividade"), request.form.get("grupo"))
        nome = request.form.get("nome", "")
        descricao = (request.form.get("descricao") or "").strip() or None
        limite_horas_raw = request.form.get("limite_horas")
        try:
            limite_horas = int(limite_horas_raw) if (limite_horas_raw is not None and str(limite_horas_raw).strip() != "") else None
        except (TypeError, ValueError):
            limite_horas = None
        tipo_atividade = request.form.get("tipo_atividade", "")
        tem_limitacao = 1 if (request.form.get("tem_limitacao") or "0") in ("1", "true", "on", "yes") else 0
        tipo_limitacao = request.form.get("tipo_limitacao") if tem_limitacao else None
        limite_horas_total = request.form.get("limite_horas_total") if tem_limitacao and tipo_limitacao == "total" else None
        limite_horas_semestral = request.form.get("limite_horas_semestral") if tem_limitacao and tipo_limitacao == "semestral" else None
        # Se há limitação, exigir tipo_limitacao válido
        if tem_limitacao and tipo_limitacao not in ("total", "semestral"):
            flash("Erro: selecione o tipo de limitação (Total ou Semestral).", "error")
            return render_template("admin_editar_atividade.html", atividade=atividade)
        # Satisfaz o CHECK da coluna: quando não há limitação, persistimos um valor válido
        if not tem_limitacao:
            tipo_limitacao = "total"
            limite_horas_total = None
            limite_horas_semestral = None

        # Checagem explícita de duplicidade por nome (escopo global), ignorando a própria
        dup = conn.execute("SELECT id, tipo_atividade, grupo FROM atividades WHERE nome = ? AND id <> ?", (nome, atividade_id)).fetchone()
        if dup:
            flash(f"Erro: Já existe atividade com este nome (ID {dup['id']}, Tipo: {dup['tipo_atividade']}, Grupo: {dup['grupo']}).", "error")
            grupos_por_tipo = build_grupos_por_tipo(conn)
            # Repassa lista de documentos a partir do que veio do form (ou salvos)
            atividade_docs = parse_documentos_json(request.form.get("documentos_json") or (atividade['documentos_json'] if 'documentos_json' in atividade.keys() else None))
            try:
                logger.info("[admin_editar_atividade POST dup] id=%s raw=%r parsed=%s", atividade_id, request.form.get("documentos_json"), atividade_docs)
            except Exception:
                pass
            resp = make_response(render_template("admin_editar_atividade.html", atividade=atividade, grupos_por_tipo=grupos_por_tipo, atividade_docs=atividade_docs))
            resp.headers['X-Template-Editar-Version'] = 'editar-atividade-20251012-02'
            return resp
        # Validações básicas
        if not grupo:
            flash("Erro: selecione o Grupo (nº/descrição).", "error")
            grupos_por_tipo = build_grupos_por_tipo(conn)
            atividade_docs = parse_documentos_json(request.form.get("documentos_json") or (atividade['documentos_json'] if 'documentos_json' in atividade.keys() else None))
            try:
                logger.info("[admin_editar_atividade POST grupo_vazio] id=%s raw=%r parsed=%s", atividade_id, request.form.get("documentos_json"), atividade_docs)
            except Exception:
                pass
            resp = make_response(render_template("admin_editar_atividade.html", atividade=atividade, grupos_por_tipo=grupos_por_tipo, atividade_docs=atividade_docs))
            resp.headers['X-Template-Editar-Version'] = 'editar-atividade-20251012-02'
            return resp
        if not nome:
            flash("Erro: informe o Nome da atividade.", "error")
            grupos_por_tipo = build_grupos_por_tipo(conn)
            atividade_docs = parse_documentos_json(request.form.get("documentos_json") or (atividade['documentos_json'] if 'documentos_json' in atividade.keys() else None))
            try:
                logger.info("[admin_editar_atividade POST nome_vazio] id=%s raw=%r parsed=%s", atividade_id, request.form.get("documentos_json"), atividade_docs)
            except Exception:
                pass
            resp = make_response(render_template("admin_editar_atividade.html", atividade=atividade, grupos_por_tipo=grupos_por_tipo, atividade_docs=atividade_docs))
            resp.headers['X-Template-Editar-Version'] = 'editar-atividade-20251012-02'
            return resp

        try:
            conn.execute("""
                UPDATE atividades
                SET grupo = ?, nome = ?, descricao = ?, limite_horas = ?, tipo_atividade = ?,
                    tem_limitacao = ?, tipo_limitacao = ?, limite_horas_total = ?, limite_horas_semestral = ?, documentos_json = ?
                WHERE id = ?
            """, (grupo, nome, descricao, limite_horas, tipo_atividade, tem_limitacao, tipo_limitacao, limite_horas_total, limite_horas_semestral, request.form.get("documentos_json") or None, atividade_id))
            conn.commit()
            flash("Atividade atualizada com sucesso.", "success")
            return redirect(url_for("admin_atividades"))
        except sqlite3.IntegrityError as e:
            msg = str(e).lower()
            if 'not null constraint failed' in msg and 'atividades.grupo' in msg:
                flash("Erro: selecione um número de grupo válido.", "error")
            elif 'unique' in msg and 'nome' in msg:
                flash("Erro: Atividade com este nome já existe.", "error")
            else:
                flash(f"Erro de integridade: {e}", "error")
    grupos_por_tipo = build_grupos_por_tipo(conn)
    try:
        logger.info("[admin_editar_atividade GET] id=%s raw=%r parsed=%s", atividade_id, (atividade['documentos_json'] if 'documentos_json' in atividade.keys() else None), atividade_docs_saved)
        try:
            src, fname, uptodate = current_app.jinja_loader.get_source(current_app.jinja_env, 'admin_editar_atividade.html')
            logger.info("[tmpl] editar path=%s uptodate=%s has_marker=%s", fname, uptodate, ('editar-atividade-20251012-02' in src))
        except Exception as e2:
            logger.warning("[tmpl] get_source error: %s", e2)
    except Exception:
        pass
    resp = make_response(render_template("admin_editar_atividade.html", atividade=atividade, grupos_por_tipo=grupos_por_tipo, atividade_docs=atividade_docs_saved))
    resp.headers['X-Template-Editar-Version'] = 'editar-atividade-20251012-02'
    return resp


@admin_required
def admin_deletar_atividade(atividade_id):
    conn = get_db_connection()
    atividade = conn.execute("SELECT id, nome FROM atividades WHERE id = ?", (atividade_id,)).fetchone()
    if not atividade:
        flash("Atividade não encontrada.", "error")
        return redirect(url_for("admin_atividades"))

    requisicoes_em_uso = conn.execute(
        "SELECT COUNT(*) FROM requisicoes WHERE atividade_id = ?",
        (atividade_id,),
    ).fetchone()[0]
    if requisicoes_em_uso:
        sufixo = "requisição" if requisicoes_em_uso == 1 else "requisições"
        flash(
            f"Não é possível excluir a atividade porque ela está vinculada a {requisicoes_em_uso} {sufixo}.",
            "error",
        )
        return redirect(url_for("admin_atividades"))

    if is_activity_referenced_by_assigned_matrix(conn, atividade_id):
        flash(ACADEMIC_GRAPH_FROZEN_MESSAGE, "error")
        return redirect(url_for("admin_atividades"))

    try:
        ensure_matriz_atividade_links_table(conn)
        conn.execute("DELETE FROM matrizes_atividades_itens WHERE atividade_id = ?", (atividade_id,))
        conn.execute("DELETE FROM atividades WHERE id = ?", (atividade_id,))
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
                conn.execute(
                    """
                    INSERT INTO atividades (
                        grupo,
                        nome,
                        limite_horas,
                        tipo_atividade,
                        tem_limitacao,
                        tipo_limitacao,
                        limite_horas_total,
                        limite_horas_semestral,
                        documentos_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["grupo"],
                        row["nome"],
                        None,
                        row["tipo_atividade"],
                        1 if row["tem_limitacao"] else 0,
                        row["tipo_limitacao"],
                        row["limite_horas_total"],
                        row["limite_horas_semestral"],
                        None,
                    ),
                )
                created += 1
            elif row.get("action") == "update":
                conn.execute(
                    """
                    UPDATE atividades
                       SET grupo = ?,
                           tipo_atividade = ?,
                           tem_limitacao = ?,
                           tipo_limitacao = ?,
                           limite_horas_total = ?,
                           limite_horas_semestral = ?
                     WHERE id = ?
                    """,
                    (
                        row["grupo"],
                        row["tipo_atividade"],
                        1 if row["tem_limitacao"] else 0,
                        row["tipo_limitacao"],
                        row["limite_horas_total"],
                        row["limite_horas_semestral"],
                        row["existing_id"],
                    ),
                )
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
        # ensure grupos_def table exists
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS grupos_def (
                tipo_atividade TEXT NOT NULL,
                numero INTEGER NOT NULL,
                descricao TEXT,
                PRIMARY KEY (tipo_atividade, numero)
            )
            """
        )
        cur = conn.execute("SELECT id, grupo FROM atividades WHERE tipo_atividade = ? AND grupo IS NOT NULL AND TRIM(grupo) <> ''", (tipo,))
        rows = cur.fetchall()
        def parse_num(s):
            m = re.match(r'^\s*(\d+)', (s or '').strip())
            return m.group(1) if m else None
        updated = 0
        for r in rows:
            gid, g = r[0], r[1]
            n = parse_num(g)
            if n == numero and (g or '').strip() != novo_label:
                conn.execute("UPDATE atividades SET grupo = ? WHERE id = ?", (novo_label, gid))
                updated += 1
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
        return jsonify({ 'ok': True, 'updated': updated, 'label': novo_label })
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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS grupos_def (
                tipo_atividade TEXT NOT NULL,
                numero INTEGER NOT NULL,
                descricao TEXT,
                PRIMARY KEY (tipo_atividade, numero)
            )
            """
        )

        prefixo = f"{numero}%"
        em_uso = conn.execute(
            """
            SELECT 1
              FROM atividades
             WHERE tipo_atividade = ?
               AND grupo IS NOT NULL
               AND TRIM(grupo) <> ''
               AND TRIM(grupo) LIKE ?
             LIMIT 1
            """,
            (tipo, prefixo),
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
                "codigo_normativo": destino["codigo_normativo"],
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
def admin_normas_atividade():
    """
    Lista todas as norma_atividade com contagem de versões vinculadas.
    GET-only, sem escrita no banco.
    """
    conn = get_db_connection()
    normas = get_norma_list(conn)
    return render_template(
        "admin_normas_atividade.html",
        normas=normas,
    )


@admin_required
def admin_mapeamento_legado():
    """
    Lista atividades legadas com status de mapeamento para atividade_base.
    GET-only, sem inferência automática por nome, sem escrita no banco.
    """
    conn = get_db_connection()
    status_filter = (request.args.get("status") or "").strip().lower()
    mapa = get_legacy_map_list(conn)
    # Filtro opcional por status (pendente, mapeada, revisar, sem_mapa)
    if status_filter in ("pendente", "mapeada", "revisar", "sem_mapa"):
        if status_filter == "sem_mapa":
            mapa = [m for m in mapa if m["mapa_id"] is None]
        else:
            mapa = [m for m in mapa if (m["mapa_status"] or "") == status_filter]
    return render_template(
        "admin_mapeamento_legado.html",
        mapa=mapa,
        status_filter=status_filter,
    )


@admin_required
def admin_catalogo_nova_base():
    """
    Formulário para criar uma nova atividade_base.
    POST valida e insere; em sucesso redireciona para o detalhe da base criada.
    """
    if request.method == "POST":
        nome_conceito = (request.form.get("nome_conceito") or "").strip()
        descricao = (request.form.get("descricao") or "").strip()
        status = (request.form.get("status") or "").strip()

        if not nome_conceito:
            flash("Nome da atividade-base é obrigatório.", "error")
            return render_template("admin_catalogo_base_form.html",
                                   nome_conceito=nome_conceito,
                                   descricao=descricao,
                                   status=status)

        if status not in ("ativo", "inativo"):
            flash("Status deve ser 'ativo' ou 'inativo'.", "error")
            return render_template("admin_catalogo_base_form.html",
                                   nome_conceito=nome_conceito,
                                   descricao=descricao,
                                   status=status)

        conn = get_db_connection()

        existing = conn.execute(
            "SELECT id FROM atividade_base WHERE LOWER(nome_conceito) = LOWER(?)",
            (nome_conceito,),
        ).fetchone()
        if existing:
            flash("Já existe uma atividade-base com este nome.", "error")
            return render_template("admin_catalogo_base_form.html",
                                   nome_conceito=nome_conceito,
                                   descricao=descricao,
                                   status=status)

        try:
            conn.execute(
                "INSERT INTO atividade_base (nome_conceito, descricao, status) VALUES (?, ?, ?)",
                (nome_conceito, descricao or None, status),
            )
            conn.commit()
            base_id = conn.execute(
                "SELECT id FROM atividade_base WHERE nome_conceito = ?",
                (nome_conceito,),
            ).fetchone()["id"]
            flash("Atividade-base criada com sucesso.", "success")
            return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))
        except Exception as exc:
            flash(f"Erro ao criar atividade-base: {exc}", "error")
            return render_template("admin_catalogo_base_form.html",
                                   nome_conceito=nome_conceito,
                                   descricao=descricao,
                                   status=status)

    return render_template("admin_catalogo_base_form.html",
                           nome_conceito="",
                           descricao="",
                           status="ativo")


@admin_required
def admin_norma_nova():
    """
    Formulário para criar uma nova norma_atividade.
    POST valida e insere; em sucesso redireciona para a listagem de normas.
    """
    if request.method == "POST":
        codigo = (request.form.get("codigo") or "").strip()
        eixo = (request.form.get("eixo") or "").strip()
        revisao = (request.form.get("revisao") or "").strip()
        nome = (request.form.get("nome") or "").strip()
        descricao = (request.form.get("descricao") or "").strip()
        status = (request.form.get("status") or "").strip()

        def _render_form(msg):
            if msg:
                flash(msg, "error")
            return render_template("admin_norma_form.html",
                                   codigo=codigo, eixo=eixo,
                                   revisao=revisao, nome=nome,
                                   descricao=descricao, status=status)

        if not codigo:
            return _render_form("Código da norma é obrigatório.")
        if eixo not in ("AAC", "AEU"):
            return _render_form("Eixo deve ser 'AAC' ou 'AEU'.")
        if not revisao:
            return _render_form("Revisão é obrigatória.")
        if status not in ("ativa", "inativa"):
            return _render_form("Status deve ser 'ativa' ou 'inativa'.")

        conn = get_db_connection()

        existing = conn.execute(
            "SELECT id FROM norma_atividade WHERE LOWER(codigo) = LOWER(?)",
            (codigo,),
        ).fetchone()
        if existing:
            return _render_form("Já existe uma norma com este código.")

        try:
            conn.execute(
                """
                INSERT INTO norma_atividade (codigo, eixo, revisao, nome, descricao, status)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (codigo, eixo, revisao, nome or None, descricao or None, status),
            )
            conn.commit()
            flash("Norma de atividade criada com sucesso.", "success")
            return redirect(url_for("admin_normas_atividade"))
        except Exception as exc:
            return _render_form(f"Erro ao criar norma: {exc}")

    return render_template("admin_norma_form.html",
                           codigo="", eixo="AAC", revisao="",
                           nome="", descricao="", status="ativa")


@admin_required
def admin_catalogo_nova_versao(base_id: int):
    """
    Formulário para criar uma nova atividade_versao em rascunho
    vinculada a uma atividade_base e uma norma_atividade.
    POST valida e insere; em sucesso redireciona para o detalhe da base.
    """
    conn = get_db_connection()
    base = get_atividade_base(conn, base_id)
    if not base:
        flash("Atividade-base não encontrada.", "error")
        return redirect(url_for("admin_catalogo_versoes"))

    normas = get_norma_list(conn)
    versoes_anteriores = (
        get_versoes_da_base_por_eixo(conn, base_id, "AAC")
        + get_versoes_da_base_por_eixo(conn, base_id, "AEU")
    )

    next_num = get_next_numero_versao(conn, base_id)
    form_action = url_for("admin_catalogo_nova_versao", base_id=base_id)
    form_title = f"Nova versão (será v{next_num})"
    submit_label = "Criar versão em rascunho"

    if request.method == "POST":
        norma_id_raw = (request.form.get("norma_id") or "").strip()
        grupo = (request.form.get("grupo") or "").strip()
        ch_por_evento_raw = (request.form.get("ch_por_evento") or "").strip()
        limite_semestre_raw = (request.form.get("limite_semestre") or "").strip()
        limite_total_raw = (request.form.get("limite_total") or "").strip()
        observacao_aluno = (request.form.get("observacao_aluno") or "").strip()
        observacao_admin = (request.form.get("observacao_admin") or "").strip()
        vigencia_inicio = (request.form.get("vigencia_inicio") or "").strip()
        vigencia_fim = (request.form.get("vigencia_fim") or "").strip()
        versao_anterior_id_raw = (request.form.get("versao_anterior_id") or "").strip()

        def _render_form(msg):
            if msg:
                flash(msg, "error")
            return render_template(
                "admin_catalogo_versao_form.html",
                base=base,
                normas=normas,
                versoes_anteriores=versoes_anteriores,
                norma_id=norma_id_raw,
                grupo=grupo,
                ch_por_evento=ch_por_evento_raw,
                limite_semestre=limite_semestre_raw,
                limite_total=limite_total_raw,
                observacao_aluno=observacao_aluno,
                observacao_admin=observacao_admin,
                vigencia_inicio=vigencia_inicio,
                vigencia_fim=vigencia_fim,
                versao_anterior_id=versao_anterior_id_raw,
                form_action=form_action,
                form_title=form_title,
                submit_label=submit_label,
            )

        if not norma_id_raw:
            return _render_form("Norma é obrigatória.")
        try:
            norma_id = int(norma_id_raw)
        except (TypeError, ValueError):
            return _render_form("Norma inválida.")

        norma = get_norma_by_id(conn, norma_id)
        if not norma:
            return _render_form("Norma não encontrada.")
        if norma["status"] != "ativa":
            return _render_form("Norma deve estar ativa para criar uma versão.")

        eixo = norma["eixo"]
        codigo_normativo = norma["codigo"]

        # validação numérica
        def _parse_float(raw, nome):
            if not raw:
                return None
            try:
                v = float(raw)
                if v < 0:
                    return nome
                return v
            except (TypeError, ValueError):
                return nome

        ch_por_evento = _parse_float(ch_por_evento_raw, "ch_por_evento")
        limite_semestre = _parse_float(limite_semestre_raw, "limite_semestre")
        limite_total = _parse_float(limite_total_raw, "limite_total")
        for maybe_err in (ch_por_evento, limite_semestre, limite_total):
            if isinstance(maybe_err, str):
                return _render_form(f"{maybe_err} deve ser um número válido e maior ou igual a zero.")

        versao_anterior_id = None
        if versao_anterior_id_raw:
            try:
                versao_anterior_id = int(versao_anterior_id_raw)
            except (TypeError, ValueError):
                return _render_form("Versão anterior inválida.")
            prev = conn.execute(
                "SELECT atividade_base_id, eixo FROM atividade_versao WHERE id = ?",
                (versao_anterior_id,),
            ).fetchone()
            if not prev:
                return _render_form("Versão anterior não encontrada.")
            if prev["atividade_base_id"] != base_id:
                return _render_form("Versão anterior deve pertencer à mesma atividade-base.")
            if prev["eixo"] != eixo:
                return _render_form("Versão anterior deve ter o mesmo eixo da norma selecionada.")

        try:
            next_num = get_next_numero_versao(conn, base_id)
            conn.execute(
                """
                INSERT INTO atividade_versao (
                    atividade_base_id, norma_id, codigo_normativo, eixo, grupo,
                    ch_por_evento, limite_semestre, limite_total,
                    observacao_aluno, observacao_admin,
                    vigencia_inicio, vigencia_fim, numero_versao, status, versao_anterior_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'rascunho', ?)
                """,
                (
                    base_id, norma_id, codigo_normativo, eixo, grupo or None,
                    ch_por_evento, limite_semestre, limite_total,
                    observacao_aluno or None, observacao_admin or None,
                    vigencia_inicio or None, vigencia_fim or None, next_num, versao_anterior_id,
                ),
            )
            conn.commit()
            flash("Versão criada com sucesso em rascunho.", "success")
            return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))
        except Exception as exc:
            return _render_form(f"Erro ao criar versão: {exc}")

    prefill, prefill_error = _resolve_nova_versao_prefill(conn, base_id, request.args.get("from"))
    if prefill_error:
        flash(prefill_error, "error")
    return render_template(
        "admin_catalogo_versao_form.html",
        base=base,
        normas=normas,
        versoes_anteriores=versoes_anteriores,
        norma_id=prefill["norma_id"],
        grupo=prefill["grupo"],
        ch_por_evento=prefill["ch_por_evento"],
        limite_semestre=prefill["limite_semestre"],
        limite_total=prefill["limite_total"],
        observacao_aluno=prefill["observacao_aluno"],
        observacao_admin=prefill["observacao_admin"],
        vigencia_inicio=prefill["vigencia_inicio"],
        vigencia_fim=prefill["vigencia_fim"],
        versao_anterior_id=prefill["versao_anterior_id"],
        form_action=form_action,
        form_title=form_title,
        submit_label=submit_label,
    )


@admin_required
def admin_catalogo_editar_versao(base_id: int, versao_id: int):
    """
    Formulário para editar uma atividade_versao existente.
    Permitido apenas enquanto status = 'rascunho' e sem nenhum uso registrado
    (matriz_atividade_versao_item, requisicoes, atividade_transicao).
    POST valida e atualiza; em sucesso redireciona para o detalhe da base.
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
        flash("Apenas versões em rascunho podem ser editadas.", "error")
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))

    uso = get_atividade_versao_usage_counts(conn, versao_id)
    if (
        uso["requisicoes"]
        or uso["atividade_transicao_origem"]
        or uso["atividade_transicao_destino"]
        or is_activity_version_referenced_by_assigned_matrix(conn, versao_id)
    ):
        flash("Esta versão já está em uso e não pode mais ser editada.", "error")
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))

    normas = get_norma_list(conn)
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
    form_title = f"Editar versão v{_num}" if _num else f"Editar versão — {versao['codigo_normativo']}"
    submit_label = "Salvar alterações"

    def _display_number(value):
        if value is None:
            return ""
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)

    if request.method == "POST":
        norma_id_raw = (request.form.get("norma_id") or "").strip()
        grupo = (request.form.get("grupo") or "").strip()
        ch_por_evento_raw = (request.form.get("ch_por_evento") or "").strip()
        limite_semestre_raw = (request.form.get("limite_semestre") or "").strip()
        limite_total_raw = (request.form.get("limite_total") or "").strip()
        observacao_aluno = (request.form.get("observacao_aluno") or "").strip()
        observacao_admin = (request.form.get("observacao_admin") or "").strip()
        vigencia_inicio = (request.form.get("vigencia_inicio") or "").strip()
        vigencia_fim = (request.form.get("vigencia_fim") or "").strip()
        versao_anterior_id_raw = (request.form.get("versao_anterior_id") or "").strip()

        def _render_form(msg):
            if msg:
                flash(msg, "error")
            return render_template(
                "admin_catalogo_versao_form.html",
                base=base,
                normas=normas,
                versoes_anteriores=versoes_anteriores,
                norma_id=norma_id_raw,
                grupo=grupo,
                ch_por_evento=ch_por_evento_raw,
                limite_semestre=limite_semestre_raw,
                limite_total=limite_total_raw,
                observacao_aluno=observacao_aluno,
                observacao_admin=observacao_admin,
                vigencia_inicio=vigencia_inicio,
                vigencia_fim=vigencia_fim,
                versao_anterior_id=versao_anterior_id_raw,
                form_action=form_action,
                form_title=form_title,
                submit_label=submit_label,
            )

        if not norma_id_raw:
            return _render_form("Norma é obrigatória.")
        try:
            norma_id = int(norma_id_raw)
        except (TypeError, ValueError):
            return _render_form("Norma inválida.")

        norma = get_norma_by_id(conn, norma_id)
        if not norma:
            return _render_form("Norma não encontrada.")
        if norma["status"] != "ativa":
            return _render_form("Norma deve estar ativa para editar a versão.")

        eixo = norma["eixo"]
        codigo_normativo = norma["codigo"]

        # validação numérica
        def _parse_float(raw, nome):
            if not raw:
                return None
            try:
                v = float(raw)
                if v < 0:
                    return nome
                return v
            except (TypeError, ValueError):
                return nome

        ch_por_evento = _parse_float(ch_por_evento_raw, "ch_por_evento")
        limite_semestre = _parse_float(limite_semestre_raw, "limite_semestre")
        limite_total = _parse_float(limite_total_raw, "limite_total")
        for maybe_err in (ch_por_evento, limite_semestre, limite_total):
            if isinstance(maybe_err, str):
                return _render_form(f"{maybe_err} deve ser um número válido e maior ou igual a zero.")

        versao_anterior_id = None
        if versao_anterior_id_raw:
            try:
                versao_anterior_id = int(versao_anterior_id_raw)
            except (TypeError, ValueError):
                return _render_form("Versão anterior inválida.")
            if versao_anterior_id == versao_id:
                return _render_form("Versão anterior não pode ser a própria versão.")
            prev = conn.execute(
                "SELECT atividade_base_id, eixo FROM atividade_versao WHERE id = ?",
                (versao_anterior_id,),
            ).fetchone()
            if not prev:
                return _render_form("Versão anterior não encontrada.")
            if prev["atividade_base_id"] != base_id:
                return _render_form("Versão anterior deve pertencer à mesma atividade-base.")
            if prev["eixo"] != eixo:
                return _render_form("Versão anterior deve ter o mesmo eixo da norma selecionada.")

        try:
            conn.execute(
                """
                UPDATE atividade_versao
                   SET norma_id = ?,
                       codigo_normativo = ?,
                       eixo = ?,
                       grupo = ?,
                       ch_por_evento = ?,
                       limite_semestre = ?,
                       limite_total = ?,
                       observacao_aluno = ?,
                       observacao_admin = ?,
                       vigencia_inicio = ?,
                       vigencia_fim = ?,
                       versao_anterior_id = ?
                 WHERE id = ?
                """,
                (
                    norma_id, codigo_normativo, eixo, grupo or None,
                    ch_por_evento, limite_semestre, limite_total,
                    observacao_aluno or None, observacao_admin or None,
                    vigencia_inicio or None, vigencia_fim or None, versao_anterior_id,
                    versao_id,
                ),
            )
            conn.commit()
            flash("Versão atualizada com sucesso.", "success")
            return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))
        except Exception as exc:
            return _render_form(f"Erro ao atualizar versão: {exc}")

    return render_template(
        "admin_catalogo_versao_form.html",
        base=base,
        normas=normas,
        versoes_anteriores=versoes_anteriores,
        norma_id=str(versao["norma_id"]),
        grupo=versao["grupo"] or "",
        ch_por_evento=_display_number(versao["ch_por_evento"]),
        limite_semestre=_display_number(versao["limite_semestre"]),
        limite_total=_display_number(versao["limite_total"]),
        observacao_aluno=versao["observacao_aluno"] or "",
        observacao_admin=versao["observacao_admin"] or "",
        vigencia_inicio=versao["vigencia_inicio"] or "",
        vigencia_fim=versao["vigencia_fim"] or "",
        versao_anterior_id=(
            "" if versao["versao_anterior_id"] is None else str(versao["versao_anterior_id"])
        ),
        form_action=form_action,
        form_title=form_title,
        submit_label=submit_label,
    )


@admin_required
def admin_catalogo_ativar_versao(base_id: int, versao_id: int):
    """
    Ativação mínima de uma atividade_versao em rascunho.

    Permite mudar status = 'rascunho' -> 'ativa' por ação administrativa
    explícita. Validações server-side:
      - atividade_base existe
      - atividade_versao existe e pertence ao base_id da URL
      - status atual == 'rascunho'
      - norma_atividade vinculada existe e está ativa

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

    norma = get_norma_by_id(conn, versao["norma_id"])
    if not norma:
        flash("Não é possível ativar: a norma vinculada não existe.", "error")
        return redirect(url_for("admin_catalogo_versao_detalhe", base_id=base_id))
    if norma["status"] != "ativa":
        flash(
            "Não é possível ativar: a norma vinculada não está ativa.",
            "error",
        )
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
            '/admin/normas-atividade',
            'admin_normas_atividade',
            admin_normas_atividade,
            ('GET',),
        ),
        LegacyRouteSpec(
            '/admin/mapeamento-legado',
            'admin_mapeamento_legado',
            admin_mapeamento_legado,
            ('GET',),
        ),
        LegacyRouteSpec(
            '/admin/catalogo-versoes/nova-base',
            'admin_catalogo_nova_base',
            admin_catalogo_nova_base,
            ('GET', 'POST'),
        ),
        LegacyRouteSpec(
            '/admin/normas-atividade/nova',
            'admin_norma_nova',
            admin_norma_nova,
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
    'admin_normas_atividade',
    'admin_mapeamento_legado',
    'admin_catalogo_nova_base',
    'admin_norma_nova',
    'admin_catalogo_nova_versao',
    'admin_catalogo_editar_versao',
    'admin_catalogo_ativar_versao',
    'admin_catalogo_inativar_versao',
    'admin_catalogo_descontinuar_versao',
    'admin_catalogo_substituir_versao',
    'LEGACY_ROUTE_SPECS',
    'bp_admin_atividades',
]
