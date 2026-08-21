# coding: utf-8
from __future__ import annotations

import csv
import logging
import os
import re
import sqlite3
import traceback
from datetime import date
from urllib.parse import urlsplit

from flask import (
    Blueprint,
    current_app as app,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from app.academics import (
    build_turma_aluno_matricula,
    gerar_codigo_turma,
    resequence_turma_aluno_matriculas,
    resequence_turma_aluno_matriculas_for_ids,
)
from app.auth import admin_required
from app.db import (
    ensure_turmas_matriz_schema,
    ensure_usuario_access_schema,
    get_db_connection,
)
from app.db_maintenance import ensure_matrizes_atividades_table
from app.matrix_scope import _matriz_option_label, get_effective_matriz_for_turma
from app.security.passwords import hash_password
from app.text import normalize_header, ptbr_text_sort_key
from app.versioning.request_history import list_approved_request_history
from app.uploads import ALLOWED_CSV, save_upload
from app.user_accounts import (
    _access_defaults_map,
    _default_password_for_user_type,
    create_usuario_with_default_access,
    create_usuario_with_default_password,
    normalize_usuario_access_for_user_type,
)
from app.web.filters import (
    append_conditions_sql,
    append_text_contains_condition,
    get_int_multi_query_values,
    get_multi_query_values,
    get_number_range_query,
    get_text_query_value,
)
from app.web.pagination import get_pagination, wants_pagination
from app.web.request import _is_ajax_request
from utils.messages import flash, resolve_user_message

from app.views.admin import LegacyRouteSpec, configure_legacy_routes


logger = logging.getLogger("main")

UPPER_CODE_RE = re.compile(r'^[A-Z-]+$')  # letras maiúsculas + hífen (ex.: PPA-NOT)


def resolve_existing_aluno_by_identifiers(conn, matricula, email):
    matricula = (matricula or "").strip()
    email = (email or "").strip()

    aluno_por_matricula = None
    aluno_por_email = None
    if matricula:
        aluno_por_matricula = conn.execute(
            "SELECT id, nome, matricula, email, usuario_id FROM alunos WHERE matricula = ?",
            (matricula,),
        ).fetchone()
    if email:
        aluno_por_email = conn.execute(
            "SELECT id, nome, matricula, email, usuario_id FROM alunos WHERE email = ?",
            (email,),
        ).fetchone()

    if aluno_por_matricula and aluno_por_email and aluno_por_matricula["id"] != aluno_por_email["id"]:
        raise ValueError("Conflito entre matrícula e e-mail: os dados informados pertencem a alunos diferentes.")
    return aluno_por_matricula or aluno_por_email


def _matrizes_by_curso(conn) -> dict[str, list[dict[str, object]]]:
    ensure_matrizes_atividades_table(conn)
    rows = conn.execute(
        """
        SELECT id, curso_id, nome, versao, status, data_inicio_vigencia
          FROM matrizes_atividades
         WHERE curso_id IS NOT NULL
      ORDER BY curso_id,
               CASE LOWER(COALESCE(status, ''))
                   WHEN 'ativa' THEN 0
                   WHEN 'vigente' THEN 0
                   WHEN 'rascunho' THEN 1
                   ELSE 2
               END,
               COALESCE(data_inicio_vigencia, '') DESC,
               id DESC
        """
    ).fetchall()
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        grouped.setdefault(str(row["curso_id"]), []).append(
            {"id": row["id"], "label": _matriz_option_label(row)}
        )
    return grouped


def _resolve_turma_matriz_id(conn, curso_id: int | None, posted_matriz_id: int | None):
    if not posted_matriz_id:
        return None, "Selecione uma matriz para a turma."
    matriz = conn.execute(
        "SELECT * FROM matrizes_atividades WHERE id = ? AND curso_id = ?",
        (posted_matriz_id, curso_id),
    ).fetchone()
    if not matriz:
        return None, "A matriz selecionada não pertence ao curso informado."
    return matriz["id"], None


def _periodo_label_for_turma_row(turma) -> str:
    inicio = None
    fim = None
    if turma["semestre_inicio"] and turma["ano_inicio"]:
        inicio = f"{turma['semestre_inicio']}S-{turma['ano_inicio']}"
    if turma["semestre_fim"] and turma["ano_fim"]:
        fim = f"{turma['semestre_fim']}S-{turma['ano_fim']}"
    if inicio and fim:
        return f"{inicio} a {fim}"
    if inicio:
        return inicio
    if fim:
        return fim
    return "-"


def _turma_effective_matriz_label(conn, turma) -> str:
    matriz = get_effective_matriz_for_turma(conn, turma["curso_id"], turma["matriz_id"])
    return _matriz_option_label(matriz) if matriz else "-"


def validar_codigo_curso(codigo: str) -> bool:
    return bool(UPPER_CODE_RE.fullmatch((codigo or "").strip()))


def semestre_atual_hoje() -> int:
    m = date.today().month
    return 1 if m <= 6 else 2


def proximo_numero_turma_por_curso(curso_id: int) -> int:
    row = get_db_connection().execute("SELECT COALESCE(MAX(numero), 0) AS mx FROM turmas WHERE curso_id = ?", (curso_id,)).fetchone()
    return (row["mx"] or 0) + 1


def curso_mais_populoso_id() -> int | None:
    row = get_db_connection().execute("""
        SELECT c.id
        FROM cursos c
        LEFT JOIN turmas t ON t.curso_id = c.id
        LEFT JOIN alunos a ON a.turma_id = t.id
        GROUP BY c.id
        ORDER BY COUNT(a.id) DESC, c.id ASC
        LIMIT 1
    """).fetchone()
    return row["id"] if row else None


@admin_required
def admin_cursos():
    """Lista de cursos com totais de turmas/alunos.
    Backend-only: adiciona paginação opcional, sem alterar UI por padrão.
    """
    page, per_page, offset = get_pagination(default_per_page=25)
    sort_field = (request.args.get("s") or "nome").strip().lower()
    sort_dir = (request.args.get("dir") or "asc").strip().lower()
    status_filters = [value.strip().lower() for value in get_multi_query_values("status") if value.strip()]
    codigo_filter = get_text_query_value("codigo")
    nome_filter = get_text_query_value("nome")
    duracao_min, duracao_max = get_number_range_query("duracao_periodos")
    qtd_turmas_min, qtd_turmas_max = get_number_range_query("qtd_turmas")
    qtd_alunos_min, qtd_alunos_max = get_number_range_query("qtd_alunos")
    conn = get_db_connection()
    base_from = (
        " FROM cursos c"
        " LEFT JOIN turmas t ON t.curso_id = c.id"
        " LEFT JOIN alunos a ON a.turma_id = t.id"
    )
    select_cols = (
        "SELECT c.*, COUNT(DISTINCT t.id) AS qtd_turmas, COUNT(a.id) AS qtd_alunos"
    )
    where = []
    params = []
    append_text_contains_condition(where, params, "c.codigo", codigo_filter)
    append_text_contains_condition(where, params, "c.nome", nome_filter)
    if status_filters:
        placeholders = ", ".join("?" for _ in status_filters)
        where.append(f"LOWER(COALESCE(c.status, '')) IN ({placeholders})")
        params.extend(status_filters)
    if duracao_min is not None:
        where.append("COALESCE(c.duracao_periodos, 0) >= ?")
        params.append(duracao_min)
    if duracao_max is not None:
        where.append("COALESCE(c.duracao_periodos, 0) <= ?")
        params.append(duracao_max)

    having = []
    having_params = []
    if qtd_turmas_min is not None:
        having.append("COUNT(DISTINCT t.id) >= ?")
        having_params.append(qtd_turmas_min)
    if qtd_turmas_max is not None:
        having.append("COUNT(DISTINCT t.id) <= ?")
        having_params.append(qtd_turmas_max)
    if qtd_alunos_min is not None:
        having.append("COUNT(a.id) >= ?")
        having_params.append(qtd_alunos_min)
    if qtd_alunos_max is not None:
        having.append("COUNT(a.id) <= ?")
        having_params.append(qtd_alunos_max)

    where_sql = append_conditions_sql(False, where)
    order_map = {
        "codigo": "LOWER(COALESCE(c.codigo, ''))",
        "nome": "LOWER(COALESCE(c.nome, ''))",
        "duracao_periodos": "COALESCE(c.duracao_periodos, 0)",
        "status": "LOWER(COALESCE(c.status, ''))",
    }
    order_sql = order_map.get(sort_field, order_map["nome"])
    direction = "DESC" if sort_dir == "desc" else "ASC"

    having_sql = (" HAVING " + " AND ".join(having)) if having else ""
    grouped_sql = base_from + where_sql + " GROUP BY c.id" + having_sql
    query = select_cols + grouped_sql + f" ORDER BY {order_sql} {direction}, c.id ASC"
    count_sql = "SELECT COUNT(*) FROM (SELECT c.id" + grouped_sql + ") cursos_filtrados"
    total = conn.execute(count_sql, params + having_params).fetchone()[0]
    apply_limit = wants_pagination()
    params_exec = list(params) + list(having_params)
    if apply_limit:
        query += " LIMIT ? OFFSET ?"
        params_exec += [per_page, offset]
    cursos = conn.execute(query, params_exec).fetchall()
    total_pages = (total + per_page - 1) // per_page if apply_limit and per_page else 1
    filter_schema = [
        {
            "param": "codigo",
            "label": "Código",
            "type": "text_contains",
            "placeholder": "Contém no código",
        },
        {
            "param": "nome",
            "label": "Nome",
            "type": "text_contains",
            "placeholder": "Contém no nome",
        },
        {
            "param": "duracao_periodos",
            "label": "Duração",
            "type": "number_range",
            "min_label": "Mínimo",
            "max_label": "Máximo",
        },
        {
            "param": "qtd_turmas",
            "label": "Turmas",
            "type": "number_range",
            "min_label": "Mínimo",
            "max_label": "Máximo",
        },
        {
            "param": "qtd_alunos",
            "label": "Alunos",
            "type": "number_range",
            "min_label": "Mínimo",
            "max_label": "Máximo",
        },
        {
            "param": "status",
            "label": "Status",
            "type": "multi_select",
            "values": [
                {"value": "ativo", "label": "Ativo"},
                {"value": "inativo", "label": "Inativo"},
            ],
        }
    ]
    return render_template(
        "admin_cursos.html",
        cursos=cursos,
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages,
        filter_schema=filter_schema,
    )


@admin_required
def admin_adicionar_curso():
    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        codigo = (request.form.get("codigo") or "").strip().upper()
        duracao_periodos = request.form.get("duracao_periodos", type=int)
        status = request.form.get("status", "ativo")

        if not nome:
            flash("Nome do curso é obrigatório.", "error")
            return redirect(url_for("admin_adicionar_curso"))
        if not validar_codigo_curso(codigo):
            flash("Código do curso deve conter apenas letras maiúsculas e hífen (A-Z e -).", "error")
            return redirect(url_for("admin_adicionar_curso"))
        if not duracao_periodos or duracao_periodos <= 0:
            flash("Duração em períodos deve ser maior que zero.", "error")
            return redirect(url_for("admin_adicionar_curso"))

        conn = get_db_connection()
        try:
            # Não recebemos mais 'periodo' via formulário; usar default do banco
            conn.execute(
                """
                INSERT INTO cursos (nome, codigo, duracao_periodos, status)
                VALUES (?,?,?,?)
                """,
                (nome, codigo, duracao_periodos, status)
            )
            conn.commit()
            flash("Curso criado com sucesso.", "success")
            return redirect(url_for("admin_cursos"))
        except sqlite3.IntegrityError as e:
            if "UNIQUE constraint failed: cursos.codigo" in str(e):
                flash("Já existe um curso com este código.", "error")
            else:
                flash(f"Erro ao criar curso: {e}", "error")
    return render_template("admin_adicionar_curso.html")


@admin_required
def admin_editar_curso(curso_id):
    conn = get_db_connection()
    curso = conn.execute("SELECT * FROM cursos WHERE id=?", (curso_id,)).fetchone()
    if not curso:
        flash("Curso não encontrado.", "error")
        return redirect(url_for("admin_cursos"))

    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        codigo_novo = (request.form.get("codigo") or "").strip().upper()
        duracao_periodos = request.form.get("duracao_periodos", type=int)
        status = request.form.get("status", "ativo")

        if not nome:
            flash("Nome do curso é obrigatório.", "error")
            return redirect(url_for("admin_editar_curso", curso_id=curso_id))
        if not validar_codigo_curso(codigo_novo):
            flash("Código do curso deve conter apenas letras maiúsculas e hífen.", "error")
            return redirect(url_for("admin_editar_curso", curso_id=curso_id))
        if not duracao_periodos or duracao_periodos <= 0:
            flash("Duração em períodos deve ser maior que zero.", "error")
            return redirect(url_for("admin_editar_curso", curso_id=curso_id))

        try:
            codigo_antigo = curso["codigo"]
            # Não alteramos mais 'periodo' em edição
            conn.execute(
                """
                UPDATE cursos SET nome=?, codigo=?, duracao_periodos=?, status=? WHERE id=?
                """,
                (nome, codigo_novo, duracao_periodos, status, curso_id)
            )

            # Regerar codigos de turmas vinculadas se o código do curso mudou
            if codigo_novo != codigo_antigo:
                turmas = conn.execute("SELECT id, numero FROM turmas WHERE curso_id=?", (curso_id,)).fetchall()
                for t in turmas:
                    novo = gerar_codigo_turma(codigo_novo, t["numero"])
                    try:
                        conn.execute("UPDATE turmas SET codigo=? WHERE id=?", (novo, t["id"]))
                    except sqlite3.IntegrityError:
                        # evitar colisão improvável
                        conn.execute("UPDATE turmas SET codigo=? WHERE id=?", (f"{novo}-{t['id']}", t["id"]))
            conn.commit()
            flash("Curso atualizado com sucesso.", "success")
            return redirect(url_for("admin_cursos"))
        except sqlite3.IntegrityError as e:
            if "UNIQUE constraint failed: cursos.codigo" in str(e):
                flash("Já existe um curso com este código.", "error")
            else:
                flash(f"Erro ao atualizar curso: {e}", "error")

    return render_template("admin_editar_curso.html", curso=curso)


@admin_required
def admin_detalhes_curso(curso_id):
    conn = get_db_connection()
    curso = conn.execute("SELECT * FROM cursos WHERE id=?", (curso_id,)).fetchone()
    if not curso:
        flash("Curso não encontrado.", "error")
        return redirect(url_for("admin_cursos"))

    turmas = conn.execute("""
        SELECT t.*,
               COUNT(a.id) AS qtd_alunos
          FROM turmas t
     LEFT JOIN alunos a ON a.turma_id = t.id
         WHERE t.curso_id = ?
      GROUP BY t.id
      ORDER BY t.numero
    """, (curso_id,)).fetchall()

    return render_template("admin_detalhes_curso.html", curso=curso, turmas=turmas)


@admin_required
def admin_visualizar_curso(curso_id):
    return redirect(url_for("admin_detalhes_curso", curso_id=curso_id))


def _safe_return_to_target(default_endpoint: str, **values) -> str:
    return_to = (request.form.get("return_to") or request.args.get("return_to") or "").strip()
    if return_to:
        parsed = urlsplit(return_to)
        if not parsed.scheme and not parsed.netloc and return_to.startswith("/") and not return_to.startswith("//"):
            return return_to
    return url_for(default_endpoint, **values)


@admin_required
def admin_deletar_curso(curso_id):
    conn = get_db_connection()
    try:
        # Se houver FK/ON, o SQLite impedirá excluir com turmas vinculadas.
        conn.execute("DELETE FROM cursos WHERE id = ?", (curso_id,))
        conn.commit()
        flash("Curso excluído com sucesso.", "success")
    except Exception as e:
        flash(f"Erro ao excluir curso: {e}", "error")
    return redirect(url_for("admin_cursos"))


@admin_required
def admin_alunos():
    page, per_page, offset = get_pagination(default_per_page=25)
    sort_field = (request.args.get("s") or "nome").strip().lower()
    sort_dir = (request.args.get("dir") or "asc").strip().lower()
    status_filters = [value.strip() for value in get_multi_query_values("status") if value.strip()]
    curso_filters = get_int_multi_query_values("curso_id")
    turma_filters = get_int_multi_query_values("turma_id")
    pendencia_filters = [value.strip().lower() for value in get_multi_query_values("pendencias") if value.strip()]
    nome_filter = get_text_query_value("nome")
    email_filter = get_text_query_value("email")
    pendentes_min, pendentes_max = get_number_range_query("pendentes")
    conn = get_db_connection()
    base_from = """
        FROM usuarios u
        JOIN alunos a ON u.id = a.usuario_id
        LEFT JOIN turmas t ON t.id = a.turma_id
        LEFT JOIN cursos c ON c.id = t.curso_id
        LEFT JOIN (
            SELECT r.aluno_id, COUNT(*) AS pendentes
            FROM requisicoes r
            WHERE r.status = 'Pendente'
            GROUP BY r.aluno_id
        ) p ON p.aluno_id = a.id
    """
    select_cols = """
        SELECT
            u.id AS usuario_id,
            u.nome,
            u.email,
            a.matricula,
            c.nome AS curso_nome,
            COALESCE(t.codigo, t.nome) AS turma,
            a.turma_id,
            a.status,
            COALESCE(p.pendentes, 0) AS pendentes
    """
    where = []
    params = []
    append_text_contains_condition(where, params, "u.nome", nome_filter)
    append_text_contains_condition(where, params, "u.email", email_filter)
    if status_filters:
        placeholders = ", ".join("?" for _ in status_filters)
        where.append(f"COALESCE(a.status, 'Ativo') IN ({placeholders})")
        params.extend(status_filters)
    if curso_filters:
        placeholders = ", ".join("?" for _ in curso_filters)
        where.append(f"t.curso_id IN ({placeholders})")
        params.extend(curso_filters)
    if turma_filters:
        placeholders = ", ".join("?" for _ in turma_filters)
        where.append(f"a.turma_id IN ({placeholders})")
        params.extend(turma_filters)
    pendencia_modes = {value for value in pendencia_filters if value in {"com_pendencias", "sem_pendencias"}}
    if pendencia_modes == {"com_pendencias"}:
        where.append("COALESCE(p.pendentes, 0) > 0")
    elif pendencia_modes == {"sem_pendencias"}:
        where.append("COALESCE(p.pendentes, 0) = 0")
    if pendentes_min is not None:
        where.append("COALESCE(p.pendentes, 0) >= ?")
        params.append(pendentes_min)
    if pendentes_max is not None:
        where.append("COALESCE(p.pendentes, 0) <= ?")
        params.append(pendentes_max)

    where_sql = append_conditions_sql(False, where)
    order_map = {
        "nome": "COALESCE(u.nome, '') COLLATE PTBR_NOACCENT",
        "matricula": "COALESCE(a.matricula, '') COLLATE PTBR_NOACCENT",
        "email": "COALESCE(u.email, '') COLLATE PTBR_NOACCENT",
        "curso_nome": "COALESCE(c.nome, '') COLLATE PTBR_NOACCENT",
        "turma": "COALESCE(t.codigo, t.nome, '') COLLATE PTBR_NOACCENT",
        "status": "COALESCE(a.status, '') COLLATE PTBR_NOACCENT",
        "pendentes": "COALESCE(p.pendentes, 0)",
    }
    order_sql = order_map.get(sort_field, order_map["nome"])
    direction = "DESC" if sort_dir == "desc" else "ASC"
    query = select_cols + base_from + where_sql + f" ORDER BY {order_sql} {direction}, u.id ASC"
    # counting rows (same FROM, no ORDER)
    count_sql = "SELECT COUNT(*) " + base_from + where_sql
    total = conn.execute(count_sql, params).fetchone()[0]
    apply_limit = wants_pagination()
    params_exec = list(params)
    if apply_limit:
        query += " LIMIT ? OFFSET ?"
        params_exec += [per_page, offset]
    alunos = conn.execute(query, params_exec).fetchall()
    total_pages = (total + per_page - 1) // per_page if apply_limit and per_page else 1
    cursos = conn.execute("SELECT id, nome, codigo FROM cursos ORDER BY COALESCE(nome, '') COLLATE PTBR_NOACCENT, id").fetchall()
    turmas = conn.execute(
        """
        SELECT t.id, t.codigo, t.nome, t.numero, c.nome AS curso_nome
          FROM turmas t
          LEFT JOIN cursos c ON c.id = t.curso_id
            ORDER BY COALESCE(c.nome, '') COLLATE PTBR_NOACCENT,
                             COALESCE(t.numero, 0),
                             COALESCE(t.codigo, t.nome, '') COLLATE PTBR_NOACCENT,
                             t.id
        """
    ).fetchall()
    filter_schema = [
        {
            "param": "nome",
            "label": "Nome",
            "type": "text_contains",
            "placeholder": "Contém no nome",
        },
        {
            "param": "email",
            "label": "E-mail",
            "type": "text_contains",
            "placeholder": "Contém no e-mail",
        },
        {
            "param": "status",
            "label": "Status",
            "type": "multi_select",
            "values": [
                {"value": "Ativo", "label": "Ativo"},
                {"value": "Inativo", "label": "Inativo"},
            ],
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
            "param": "turma_id",
            "label": "Turma",
            "type": "multi_select",
            "values": [
                {
                    "value": str(turma["id"]),
                    "label": turma["codigo"]
                    or turma["nome"]
                    or (f"Turma {turma['numero']}" if turma["numero"] else "Turma sem código"),
                }
                for turma in turmas
            ],
        },
        {
            "param": "pendentes",
            "label": "Solicitações pendentes",
            "type": "number_range",
            "min_label": "Mínimo",
            "max_label": "Máximo",
        },
        {
            "param": "pendencias",
            "label": "Pendências",
            "type": "multi_select",
            "values": [
                {"value": "com_pendencias", "label": "Com pendências"},
                {"value": "sem_pendencias", "label": "Sem pendências"},
            ],
        },
    ]
    return render_template(
        "admin_alunos.html",
        alunos=alunos,
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages,
        filter_schema=filter_schema,
    )


@admin_required
def admin_adicionar_aluno():
    conn = get_db_connection()
    ensure_usuario_access_schema(conn)
    return_to = (request.form.get("return_to") or request.args.get("return_to") or "").strip()
    turma_default_id = request.form.get("turma_id", type=int) if request.method == "POST" else request.args.get("turma_id", type=int)
    if request.method == "POST":
        nome = request.form["nome"]
        email = request.form["email"]
        senha = (request.form.get("senha") or "").strip()
        matricula = request.form["matricula"]
        turma_id = request.form.get("turma_id", type=int)
        status = request.form["status"]

        try:
            senha_final = senha or _default_password_for_user_type(conn, "aluno")
            hashed_password = hash_password(senha_final)
            cursor = create_usuario_with_default_access(conn, nome, email, hashed_password, "aluno")
            usuario_id = cursor.lastrowid
            conn.execute("INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status) VALUES (?, ?, ?, ?, ?, ?)",
                         (usuario_id, nome, matricula, email, turma_id, status))
            resequence_turma_aluno_matriculas_for_ids(conn, turma_id)
            conn.commit()
            flash("Aluno adicionado com sucesso.", "success")
            return redirect(_safe_return_to_target("admin_alunos"))
        except sqlite3.IntegrityError as e:
            if "UNIQUE constraint failed: usuarios.email" in str(e):
                flash("Erro: Já existe um usuário com este e-mail.", "error")
            elif "UNIQUE constraint failed: alunos.matricula" in str(e):
                flash("Erro: Já existe um aluno com esta matrícula.", "error")
            else:
                flash(f"Erro ao adicionar aluno: {e}", "error")
        except Exception as e:
            flash(f"Erro inesperado ao adicionar aluno: {e}", "error")

    # Compat: templates antigos esperam (id, nome). Exibo código como "nome".
    turmas = conn.execute("""
        SELECT t.id, COALESCE(t.codigo, t.nome) AS nome
          FROM turmas t
         WHERE t.status='Ativa'
      ORDER BY t.ano_inicio DESC, t.semestre_inicio DESC, nome
    """).fetchall()
    return render_template(
        "admin_adicionar_aluno.html",
        turmas=turmas,
        turma_default_id=turma_default_id,
        return_to=return_to,
    )


@admin_required
def admin_editar_aluno(usuario_id):
    conn = get_db_connection()
    aluno = conn.execute("""
      SELECT u.id as usuario_id, u.nome, u.email, a.matricula, a.turma_id, a.status\x20
      FROM usuarios u\x20
      JOIN alunos a ON u.id = a.usuario_id\x20
      WHERE u.id = ?
    """, (usuario_id,)).fetchone()
    if not aluno:
        flash("Aluno não encontrado.", "error")
        return redirect(url_for("admin_alunos"))

    if request.method == "POST":
        nome = request.form["nome"]
        email = request.form["email"]
        matricula = request.form["matricula"]
        turma_id = request.form.get("turma_id", type=int)
        status = request.form["status"]
        senha = request.form.get("senha")
        turma_id_anterior = aluno["turma_id"]

        try:
            if senha:
                hashed_password = hash_password(senha)
                conn.execute("UPDATE usuarios SET nome = ?, email = ?, senha = ? WHERE id = ?", (nome, email, hashed_password, usuario_id))
            else:
                conn.execute("UPDATE usuarios SET nome = ?, email = ? WHERE id = ?", (nome, email, usuario_id))
            conn.execute("UPDATE alunos SET nome = ?, matricula = ?, email = ?, turma_id = ?, status = ? WHERE usuario_id = ?",
                         (nome, matricula, email, turma_id, status, usuario_id))
            resequence_turma_aluno_matriculas_for_ids(conn, turma_id_anterior, turma_id)
            conn.commit()
            flash("Aluno atualizado com sucesso.", "success")
            return redirect(url_for("admin_alunos"))
        except sqlite3.IntegrityError as e:
            if "UNIQUE constraint failed: usuarios.email" in str(e):
                flash("Erro: Já existe outro usuário com este e-mail.", "error")
            elif "UNIQUE constraint failed: alunos.matricula" in str(e):
                flash("Erro: Já existe outro aluno com esta matrícula.", "error")
            else:
                flash(f"Erro ao atualizar aluno: {e}", "error")
        except Exception as e:
            flash(f"Erro inesperado ao atualizar aluno: {e}", "error")

    turmas = conn.execute("""
        SELECT t.id, COALESCE(t.codigo, t.nome) AS nome
          FROM turmas t
         WHERE t.status='Ativa'
      ORDER BY t.ano_inicio DESC, t.semestre_inicio DESC, nome
    """).fetchall()
    return render_template("admin_editar_aluno.html", aluno=aluno, turmas=turmas)


@admin_required
def admin_deletar_aluno(usuario_id):
    conn = get_db_connection()
    try:
        aluno = conn.execute("SELECT turma_id FROM alunos WHERE usuario_id = ?", (usuario_id,)).fetchone()
        deleted_aluno = conn.execute("DELETE FROM alunos WHERE usuario_id = ?", (usuario_id,))
        deleted_usuario = conn.execute("DELETE FROM usuarios WHERE id = ?", (usuario_id,))
        if deleted_aluno.rowcount == 0 and deleted_usuario.rowcount == 0:
            raise LookupError("Aluno não encontrado para exclusão.")
        resequence_turma_aluno_matriculas_for_ids(conn, aluno["turma_id"] if aluno else None)
        conn.commit()
        if _is_ajax_request():
            return jsonify({"ok": True, "deleted": usuario_id})
        flash("Aluno deletado com sucesso.", "success")
    except Exception as e:
        conn.rollback()
        if _is_ajax_request():
            return jsonify({"ok": False, "error": str(e)}), 500
        flash(f"Erro ao deletar aluno: {e}", "error")
    return redirect(_safe_return_to_target("admin_alunos"))


@admin_required
def admin_alterar_status_alunos():
    selected_alunos_ids = request.form.getlist("selected_alunos")
    novo_status = request.form["novo_status"]

    if not selected_alunos_ids:
        flash("Nenhum aluno selecionado para alteração de status.", "warning")
        return redirect(url_for("admin_alunos"))

    conn = get_db_connection()
    try:
        placeholders = ", ".join(["?" for _ in selected_alunos_ids])
        query = f"UPDATE alunos SET status = ? WHERE usuario_id IN ({placeholders})"
        conn.execute(query, (novo_status, *selected_alunos_ids))
        conn.commit()
        flash(f"Status de {len(selected_alunos_ids)} aluno(s) alterado(s) para '{novo_status}' com sucesso.", "success")
    except Exception as e:
        flash(f"Erro ao alterar status dos alunos: {e}", "error")
        logger.error(f"Erro ao alterar status em massa: {e}")
        traceback.print_exc()
    return redirect(url_for("admin_alunos"))


@admin_required
def admin_turmas():
    page, per_page, offset = get_pagination(default_per_page=25)
    sort_field = (request.args.get("s") or "curso_nome").strip().lower()
    sort_dir = (request.args.get("dir") or "asc").strip().lower()
    status_filters = [value.strip() for value in get_multi_query_values("status") if value.strip()]
    curso_filters = get_int_multi_query_values("curso_id")
    codigo_filter = get_text_query_value("codigo")
    matriz_filter = get_text_query_value("matriz")
    numero_min, numero_max = get_number_range_query("numero")
    qtd_alunos_min, qtd_alunos_max = get_number_range_query("qtd_alunos")
    conn = get_db_connection()
    ensure_turmas_matriz_schema(conn)
    base_from = """
        FROM turmas t
   LEFT JOIN cursos c ON c.id = t.curso_id
   LEFT JOIN alunos a ON a.turma_id = t.id
   LEFT JOIN matrizes_atividades tm
          ON tm.id = t.matriz_id
         AND tm.curso_id = t.curso_id
    """
    select_cols = """
        SELECT t.id, t.nome, t.ano_inicio AS ano, t.semestre_inicio AS semestre, t.turno, t.status, t.numero,
               t.ano_inicio, t.semestre_inicio, t.ano_fim, t.semestre_fim, t.codigo,
               t.matriz_id, c.nome AS curso_nome, c.codigo AS curso_codigo, c.duracao_periodos,
               tm.nome AS matriz_nome, tm.versao AS matriz_versao, tm.status AS matriz_status,
               COUNT(a.id) AS qtd_alunos
    """
    where = []
    params = []
    append_text_contains_condition(where, params, "t.codigo", codigo_filter)
    append_text_contains_condition(where, params, "tm.nome", matriz_filter)
    if status_filters:
        placeholders = ", ".join("?" for _ in status_filters)
        where.append(f"COALESCE(t.status, 'Ativa') IN ({placeholders})")
        params.extend(status_filters)
    if curso_filters:
        placeholders = ", ".join("?" for _ in curso_filters)
        where.append(f"t.curso_id IN ({placeholders})")
        params.extend(curso_filters)
    if numero_min is not None:
        where.append("COALESCE(t.numero, 0) >= ?")
        params.append(numero_min)
    if numero_max is not None:
        where.append("COALESCE(t.numero, 0) <= ?")
        params.append(numero_max)

    having = []
    having_params = []
    if qtd_alunos_min is not None:
        having.append("COUNT(a.id) >= ?")
        having_params.append(qtd_alunos_min)
    if qtd_alunos_max is not None:
        having.append("COUNT(a.id) <= ?")
        having_params.append(qtd_alunos_max)

    where_sql = append_conditions_sql(False, where)
    order_map = {
        "codigo": "LOWER(COALESCE(t.codigo, ''))",
        "curso_nome": "LOWER(COALESCE(c.nome, ''))",
        "matriz_nome": "LOWER(COALESCE(tm.nome, ''))",
        "numero": "COALESCE(t.numero, 0)",
        "status": "LOWER(COALESCE(t.status, ''))",
    }
    order_sql = order_map.get(sort_field, order_map["curso_nome"])
    direction = "DESC" if sort_dir == "desc" else "ASC"

    having_sql = (" HAVING " + " AND ".join(having)) if having else ""
    grouped_sql = base_from + where_sql + " GROUP BY t.id" + having_sql
    query = select_cols + grouped_sql + f" ORDER BY {order_sql} {direction}, t.id ASC"
    count_sql = "SELECT COUNT(*) FROM (SELECT t.id" + grouped_sql + ") turmas_filtradas"
    total = conn.execute(count_sql, params + having_params).fetchone()[0]
    apply_limit = wants_pagination()
    params_exec = list(params) + list(having_params)
    if apply_limit:
        query += " LIMIT ? OFFSET ?"
        params_exec += [per_page, offset]
    turmas = conn.execute(query, params_exec).fetchall()
    total_pages = (total + per_page - 1) // per_page if apply_limit and per_page else 1
    cursos = conn.execute("SELECT id, nome, codigo FROM cursos ORDER BY LOWER(nome), id").fetchall()
    filter_schema = [
        {
            "param": "codigo",
            "label": "Código",
            "type": "text_contains",
            "placeholder": "Contém no código",
        },
        {
            "param": "status",
            "label": "Status",
            "type": "multi_select",
            "values": [
                {"value": "Ativa", "label": "Ativa"},
                {"value": "Inativa", "label": "Inativa"},
            ],
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
            "param": "matriz",
            "label": "Matriz",
            "type": "text_contains",
            "placeholder": "Contém no nome da matriz",
        },
        {
            "param": "numero",
            "label": "Nº Turma",
            "type": "number_range",
            "min_label": "Mínimo",
            "max_label": "Máximo",
        },
        {
            "param": "qtd_alunos",
            "label": "Alunos",
            "type": "number_range",
            "min_label": "Mínimo",
            "max_label": "Máximo",
        },
    ]
    return render_template(
        "admin_turmas.html",
        turmas=turmas,
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages,
        filter_schema=filter_schema,
    )


@admin_required
def admin_adicionar_turma():
    conn = get_db_connection()
    ensure_turmas_matriz_schema(conn)
    ensure_usuario_access_schema(conn)

    cursos = conn.execute("SELECT id, nome, codigo, duracao_periodos FROM cursos WHERE status='ativo' ORDER BY nome").fetchall()
    default_curso_id = curso_mais_populoso_id() or (cursos[0]["id"] if cursos else None)
    matrizes_by_curso = _matrizes_by_curso(conn)
    default_matriz_id = None

    if request.method == "POST":
        curso_id = request.form.get("curso_id", type=int)
        matriz_id, matriz_error = _resolve_turma_matriz_id(conn, curso_id, request.form.get("matriz_id", type=int))
        ano_inicio = request.form.get("ano_inicio", type=int) or date.today().year
        semestre_inicio = request.form.get("semestre_inicio", type=int) or semestre_atual_hoje()
        ano_fim = request.form.get("ano_fim", type=int)
        semestre_fim = request.form.get("semestre_fim", type=int)
        turno = request.form.get("turno") or ""
        status = request.form.get("status", "Ativa")
        numero = request.form.get("numero_turma", type=int)
        if numero is None:
            numero = request.form.get("numero", type=int)

        if not curso_id:
            flash("Selecione um curso.", "error")
            return redirect(url_for("admin_adicionar_turma"))

        curso = conn.execute("SELECT * FROM cursos WHERE id=?", (curso_id,)).fetchone()
        if not curso:
            flash("Curso inválido.", "error")
            return redirect(url_for("admin_adicionar_turma"))
        if matriz_error:
            flash(matriz_error, "error")
            return redirect(url_for("admin_adicionar_turma"))

        if not numero:
            numero = proximo_numero_turma_por_curso(curso_id)

        codigo = gerar_codigo_turma(curso["codigo"], numero)

        # validar unicidades
        existe1 = conn.execute("SELECT 1 FROM turmas WHERE curso_id=? AND numero=?", (curso_id, numero)).fetchone()
        if existe1:
            flash("Já existe uma turma com esse número neste curso.", "error")
            return redirect(url_for("admin_adicionar_turma"))
        existe2 = conn.execute("SELECT 1 FROM turmas WHERE codigo=?", (codigo,)).fetchone()
        if existe2:
            flash("Código de turma já existente.", "error")
            return redirect(url_for("admin_adicionar_turma"))

        try:
            cur = conn.execute(
                """
                INSERT INTO turmas (nome, turno, status, numero, curso_id, matriz_id, ano_inicio, semestre_inicio, ano_fim, semestre_fim, codigo)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (codigo, turno, status, numero, curso_id, matriz_id, ano_inicio, semestre_inicio, ano_fim, semestre_fim, codigo)
            )
            turma_id = cur.lastrowid

            # Processar alunos do formulário (cadastro em massa inline)
            nomes = request.form.getlist("aluno_nome[]")
            emails = request.form.getlist("aluno_email[]")
            mats  = request.form.getlist("aluno_matricula[]")
            sits  = request.form.getlist("aluno_situacao[]")

            def map_status_db(s):
                return "Ativo" if (s or "").upper() == "ATIVO" else "Inativo"

            if nomes or emails or mats:
                for i in range(max(len(nomes), len(emails), len(mats))):
                    nome_i = (nomes[i] if i < len(nomes) else "").strip()
                    email_i = (emails[i] if i < len(emails) else "").strip()
                    mat_i = (mats[i] if i < len(mats) else "").strip()
                    sit_i = (sits[i] if i < len(sits) else "ATIVO").strip().upper()
                    if not (nome_i or email_i or mat_i):
                        continue
                    if not mat_i:
                        # exigir matrícula para evitar violar NOT NULL/UNIQUE
                        continue
                    # Se houver usuário com este email, reusar; se não, criar apenas se email existir
                    usuario_id = None
                    if email_i:
                        u = conn.execute("SELECT id FROM usuarios WHERE email=?", (email_i,)).fetchone()
                        if u:
                            usuario_id = u[0] if isinstance(u, tuple) else u["id"]
                            normalize_usuario_access_for_user_type(conn, usuario_id)
                        else:
                            # criar usuário aluno com a senha padrão configurada para o nível usuario
                            try:
                                c2 = create_usuario_with_default_password(
                                    conn,
                                    nome_i or email_i.split("@")[0],
                                    email_i,
                                    "aluno",
                                )
                                usuario_id = c2.lastrowid
                            except sqlite3.IntegrityError:
                                # email pode existir em outra conta; não cria usuário, segue sem
                                usuario_id = None
                    # Upsert em alunos pela matrícula
                    # Upsert em alunos por matrícula ou e-mail para reaproveitar cadastros já existentes.
                    a = resolve_existing_aluno_by_identifiers(conn, mat_i, email_i)
                    if a:
                        conn.execute(
                            "UPDATE alunos SET nome=?, matricula=?, email=?, turma_id=?, status=? WHERE id=?",
                            (nome_i or a["nome"], mat_i, email_i or None, turma_id, map_status_db(sit_i), a["id"])
                        )
                        if usuario_id:
                            conn.execute("UPDATE alunos SET usuario_id=? WHERE id=?", (usuario_id, a["id"]))
                    else:
                        conn.execute(
                            "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status) VALUES (?,?,?,?,?,?)",
                            (usuario_id, nome_i or "", mat_i, email_i or None, turma_id, map_status_db(sit_i))
                        )

            resequence_turma_aluno_matriculas_for_ids(conn, turma_id)

            conn.commit()
            flash("Turma criada com sucesso.", "success")
            return redirect(url_for("admin_turmas"))
        except (sqlite3.IntegrityError, ValueError) as e:
            flash(f"Erro ao criar turma: {e}", "error")

    suggested = proximo_numero_turma_por_curso(default_curso_id) if default_curso_id else 1
    return render_template("admin_adicionar_turma.html",
                           cursos=cursos,
                           matrizes_by_curso=matrizes_by_curso,
                           matriz_default_id=default_matriz_id,
                           curso_default_id=default_curso_id,
                           proximo_numero=suggested,
                           ano_sugerido=date.today().year,
                           semestre_sugerido=semestre_atual_hoje())


@admin_required
def admin_editar_turma(turma_id):
    conn = get_db_connection()
    ensure_turmas_matriz_schema(conn)
    ensure_usuario_access_schema(conn)
    turma = conn.execute("SELECT * FROM turmas WHERE id = ?", (turma_id,)).fetchone()
    if not turma:
        flash("Turma não encontrada.", "error")
        return redirect(url_for("admin_turmas"))

    cursos = conn.execute("SELECT id, nome, codigo, duracao_periodos FROM cursos WHERE status='ativo' ORDER BY nome").fetchall()
    matrizes_by_curso = _matrizes_by_curso(conn)

    if request.method == "POST":
        curso_id = request.form.get("curso_id", type=int)
        matriz_id, matriz_error = _resolve_turma_matriz_id(conn, curso_id, request.form.get("matriz_id", type=int))
        ano_inicio = request.form.get("ano_inicio", type=int)
        semestre_inicio = request.form.get("semestre_inicio", type=int)
        ano_fim = request.form.get("ano_fim", type=int)
        semestre_fim = request.form.get("semestre_fim", type=int)
        turno = request.form.get("turno") or ""
        status = request.form.get("status", "Ativa")
        numero = request.form.get("numero_turma", type=int)
        if numero is None:
            numero = request.form.get("numero", type=int)

        if not curso_id:
            flash("Selecione um curso.", "error")
            return redirect(url_for("admin_editar_turma", turma_id=turma_id))

        curso = conn.execute("SELECT * FROM cursos WHERE id=?", (curso_id,)).fetchone()
        if not curso:
            flash("Curso inválido.", "error")
            return redirect(url_for("admin_editar_turma", turma_id=turma_id))
        if matriz_error:
            flash(matriz_error, "error")
            return redirect(url_for("admin_editar_turma", turma_id=turma_id))

        if not numero:
            numero = proximo_numero_turma_por_curso(curso_id)

        codigo_novo = gerar_codigo_turma(curso["codigo"], numero)

        # validar unicidades (ignorando a própria turma)
        existe1 = conn.execute("SELECT 1 FROM turmas WHERE curso_id=? AND numero=? AND id<>?", (curso_id, numero, turma_id)).fetchone()
        if existe1:
            flash("Já existe uma turma com esse número neste curso.", "error")
            return redirect(url_for("admin_editar_turma", turma_id=turma_id))
        existe2 = conn.execute("SELECT 1 FROM turmas WHERE codigo=? AND id<>?", (codigo_novo, turma_id)).fetchone()
        if existe2:
            flash("Código de turma já existente.", "error")
            return redirect(url_for("admin_editar_turma", turma_id=turma_id))

        try:
            conn.execute(
                """
                UPDATE turmas
                   SET nome=?, turno=?, status=?, numero=?, curso_id=?, matriz_id=?, ano_inicio=?, semestre_inicio=?, ano_fim=?, semestre_fim=?, codigo=?
                 WHERE id=?
                """,
                (codigo_novo, turno, status, numero, curso_id, matriz_id, ano_inicio, semestre_inicio, ano_fim, semestre_fim, codigo_novo, turma_id)
            )

            # Atualizar alunos vinculados via formulário
            nomes = request.form.getlist("aluno_nome[]")
            emails = request.form.getlist("aluno_email[]")
            mats  = request.form.getlist("aluno_matricula[]")
            sits  = request.form.getlist("aluno_situacao[]")

            def map_status_db(s):
                return "Ativo" if (s or "").upper() == "ATIVO" else "Inativo"

            posted_mats = set()
            for i in range(max(len(nomes), len(emails), len(mats))):
                nome_i = (nomes[i] if i < len(nomes) else "").strip()
                email_i = (emails[i] if i < len(emails) else "").strip()
                mat_i = (mats[i] if i < len(mats) else "").strip()
                sit_i = (sits[i] if i < len(sits) else "ATIVO").strip().upper()
                if not (nome_i or email_i or mat_i):
                    continue
                if not mat_i:
                    continue
                posted_mats.add(mat_i)
                # encontrar ou criar usuario se email presente
                usuario_id = None
                if email_i:
                    u = conn.execute("SELECT id FROM usuarios WHERE email=?", (email_i,)).fetchone()
                    if u:
                        usuario_id = u[0] if isinstance(u, tuple) else u["id"]
                        normalize_usuario_access_for_user_type(conn, usuario_id)
                    else:
                        try:
                            c2 = create_usuario_with_default_password(
                                conn,
                                nome_i or email_i.split("@")[0],
                                email_i,
                                "aluno",
                            )
                            usuario_id = c2.lastrowid
                        except sqlite3.IntegrityError:
                            usuario_id = None
                # upsert por matrícula ou e-mail para reaproveitar alunos já cadastrados e apenas relinkar a turma.
                a = resolve_existing_aluno_by_identifiers(conn, mat_i, email_i)
                if a:
                    conn.execute(
                        "UPDATE alunos SET nome=?, matricula=?, email=?, turma_id=?, status=? WHERE id=?",
                        (nome_i or a["nome"], mat_i, email_i or None, turma_id, map_status_db(sit_i), a["id"])
                    )
                    if usuario_id:
                        conn.execute("UPDATE alunos SET usuario_id=? WHERE id=?", (usuario_id, a["id"]))
                else:
                    conn.execute(
                        "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status) VALUES (?,?,?,?,?,?)",
                        (usuario_id, nome_i or "", mat_i, email_i or None, turma_id, map_status_db(sit_i))
                    )

            # Desvincular alunos que foram removidos da lista
            atuais = conn.execute("SELECT matricula FROM alunos WHERE turma_id = ?", (turma_id,)).fetchall()
            atuais_set = {(r[0] if isinstance(r, tuple) else r["matricula"]) for r in atuais}
            to_unlink = atuais_set - posted_mats
            for m in to_unlink:
                conn.execute("UPDATE alunos SET turma_id = NULL WHERE matricula = ?", (m,))

            resequence_turma_aluno_matriculas_for_ids(conn, turma_id)

            conn.commit()
            flash("Turma atualizada com sucesso.", "success")
            return redirect(url_for("admin_turmas"))
        except (sqlite3.IntegrityError, ValueError) as e:
            flash(f"Erro ao atualizar turma: {e}", "error")

    # Carregar alunos da turma para edição inline
    alunos = conn.execute(
        "SELECT nome, email, matricula, status FROM alunos WHERE turma_id = ?",
        (turma_id,)
    ).fetchall()
    alunos = sorted(alunos, key=lambda row: ptbr_text_sort_key(row["nome"]))
    effective_matriz = get_effective_matriz_for_turma(conn, turma["curso_id"], turma["matriz_id"])
    return render_template(
        "admin_editar_turma.html",
        turma=turma,
        cursos=cursos,
        alunos=alunos,
        matrizes_by_curso=matrizes_by_curso,
        matriz_default_id=effective_matriz["id"] if effective_matriz else None,
    )


@admin_required
def admin_deletar_turma(turma_id):
    conn = get_db_connection()
    try:
        alunos_vinc = conn.execute("SELECT COUNT(*) FROM alunos WHERE turma_id = ?", (turma_id,)).fetchone()[0]
        if alunos_vinc:
            flash("Não é possível excluir: há alunos vinculados a esta turma.", "error")
            return redirect(url_for("admin_turmas"))

        conn.execute("DELETE FROM turmas WHERE id=?", (turma_id,))
        conn.commit()
        flash("Turma deletada com sucesso.", "success")
    except Exception as e:
        flash(f"Erro ao deletar turma: {e}", "error")
    return redirect(url_for("admin_turmas"))


@admin_required
def admin_detalhes_turma(turma_id):
    conn = get_db_connection()
    ensure_turmas_matriz_schema(conn)
    sort_field = (request.args.get("s") or "nome").strip().lower()
    sort_dir = (request.args.get("dir") or "asc").strip().lower()
    status_filter_map = {"ativo": "Ativo", "inativo": "Inativo"}
    status_filters = {
        status_filter_map[value.strip().lower()]
        for value in get_multi_query_values("status")
        if value.strip().lower() in status_filter_map
    }
    turma = conn.execute("""
        SELECT t.*, c.nome AS curso_nome, c.codigo AS curso_codigo, c.duracao_periodos,
               tm.nome AS matriz_nome, tm.versao AS matriz_versao, tm.status AS matriz_status
          FROM turmas t
          LEFT JOIN cursos c ON c.id = t.curso_id
           LEFT JOIN matrizes_atividades tm
                  ON tm.id = t.matriz_id
                 AND tm.curso_id = t.curso_id
         WHERE t.id=?
    """, (turma_id,)).fetchone()
    if not turma:
        flash("Turma não encontrada.", "error")
        return redirect(url_for("admin_turmas"))
    alunos = conn.execute(
        """
        SELECT
            u.id AS usuario_id,
            u.nome,
            u.email,
            a.matricula,
            a.status,
            a.id AS aluno_id
        FROM alunos a
        JOIN usuarios u ON u.id = a.usuario_id
        WHERE a.turma_id = ?
        """,
        (turma_id,),
    ).fetchall()
    approved_totals = {}
    for history in list_approved_request_history(conn, turma_id=turma_id):
        totals = approved_totals.setdefault(
            history.aluno_id, {"AAC": 0.0, "AEU": 0.0}
        )
        totals[history.eixo] += history.approved_hours
    alunos_normalizados = []
    for row in alunos:
        aluno = {key: row[key] for key in row.keys()}
        aluno["status"] = "Ativo" if str(row["status"] or "").strip().lower() == "ativo" else "Inativo"
        totals = approved_totals.get(row["aluno_id"], {})
        aluno["total_aac"] = float(totals.get("AAC", 0) or 0)
        aluno["total_ae"] = float(totals.get("AEU", 0) or 0)
        if status_filters and aluno["status"] not in status_filters:
            continue
        alunos_normalizados.append(aluno)

    sort_map = {
        "usuario_id": lambda row: int(row["usuario_id"] or 0),
        "nome": lambda row: ptbr_text_sort_key(row["nome"]),
        "email": lambda row: ptbr_text_sort_key(row["email"] or ""),
        "matricula": lambda row: ptbr_text_sort_key(row["matricula"] or ""),
        "total_aac": lambda row: float(row["total_aac"] or 0),
        "total_ae": lambda row: float(row["total_ae"] or 0),
        "status": lambda row: ptbr_text_sort_key(row["status"]),
    }
    order_key = sort_map.get(sort_field, sort_map["nome"])
    alunos = sorted(alunos_normalizados, key=order_key, reverse=(sort_dir == "desc"))
    all_turmas = conn.execute(
        """
        SELECT t.id, t.codigo, t.numero, c.nome AS curso_nome
          FROM turmas t
          LEFT JOIN cursos c ON c.id = t.curso_id
      ORDER BY LOWER(COALESCE(c.nome, '')), COALESCE(t.numero, 0), LOWER(COALESCE(t.codigo, t.nome, '')), t.id
        """
    ).fetchall()
    filter_schema = [
        {
            "param": "status",
            "label": "Status",
            "type": "multi_select",
            "values": [
                {"value": "Ativo", "label": "Ativo"},
                {"value": "Inativo", "label": "Inativo"},
            ],
        }
    ]
    return render_template(
        "admin_detalhes_turma.html",
        turma=turma,
        alunos=alunos,
        all_turmas=all_turmas,
        filter_schema=filter_schema,
        periodo_label=_periodo_label_for_turma_row(turma),
        matriz_label=_turma_effective_matriz_label(conn, turma),
    )


# ====== Importar Alunos (CSV) para uma Turma ======

@admin_required
def admin_turmas_importar():
    if request.method == "GET":
        # Fluxo oficial de importacao acontece no modal de /admin/turmas.
        return redirect(url_for("admin_turmas"))

    conn = get_db_connection()

    if request.method == "POST":
        turma_id = request.form.get("turma_id", type=int)
        arquivo = request.files.get("csv_arquivo")

        if not turma_id:
            flash("Selecione a turma de destino.", "error")
            return redirect(url_for("admin_turmas_importar"))
        if not arquivo or arquivo.filename == "":
            flash("Selecione um arquivo CSV.", "error")
            return redirect(url_for("admin_turmas_importar"))

        # Salva arquivo
        try:
            filename = save_upload(arquivo, ALLOWED_CSV, prefix=f"turma{turma_id}", subdir=f"turmas_imports")
        except ValueError:
            flash("Envie um arquivo CSV válido.", "error")
            return redirect(url_for("admin_turmas_importar"))
        path = os.path.join(app.config["UPLOAD_FOLDER"], filename)

        sucesso, nao_encontrados, erros = 0, 0, 0
        try:
            with open(path, "r", encoding="utf-8-sig", newline="") as f:
                # Detecta delimitador
                sample = f.read(2048)
                f.seek(0)
                try:
                    dialect = csv.Sniffer().sniff(sample)
                except csv.Error:
                    dialect = csv.excel
                reader = csv.DictReader(f, dialect=dialect)

                # Normaliza nomes de colunas
                field_map = {normalize_header(h): h for h in reader.fieldnames or []}
                col_matricula = field_map.get("matricula")
                col_email = field_map.get("email")

                if not (col_matricula or col_email):
                    flash("O CSV precisa ter a coluna 'matrícula' ou 'email'.", "error")
                    return redirect(url_for("admin_turmas_importar"))

                for row in reader:
                    try:
                        matricula = (row.get(col_matricula, "") if col_matricula else "").strip()
                        email = (row.get(col_email, "") if col_email else "").strip()

                        achou = None
                        if matricula:
                            achou = conn.execute("SELECT usuario_id FROM alunos WHERE matricula = ?", (matricula,)).fetchone()
                        if not achou and email:
                            achou = conn.execute("SELECT usuario_id FROM alunos WHERE email = ?", (email,)).fetchone()

                        if achou:
                            conn.execute("UPDATE alunos SET turma_id = ? WHERE usuario_id = ?", (turma_id, achou["usuario_id"]))
                            sucesso += 1
                        else:
                            nao_encontrados += 1
                    except Exception:
                        erros += 1

            resequence_turma_aluno_matriculas_for_ids(conn, turma_id)
            conn.commit()
            msg = resolve_user_message(f"Importação concluída. Vinculados: {sucesso}.")
            if nao_encontrados:
                msg += " " + resolve_user_message(f"Não encontrados: {nao_encontrados}.")
            if erros:
                msg += " " + resolve_user_message(f"Linhas com erro: {erros}.")
            flash(msg, "success")
            return redirect(url_for("admin_turmas"))
        except Exception as e:
            logger.error(f"Erro ao importar CSV de turmas: {e}")
            traceback.print_exc()
            flash(f"Falha ao processar CSV: {e}", "error")
            return redirect(url_for("admin_turmas_importar"))


bp_admin_alunos_turmas_cursos = Blueprint("admin_alunos_turmas_cursos_blueprint", __name__)

LEGACY_ROUTE_SPECS = configure_legacy_routes(
    bp_admin_alunos_turmas_cursos,
    (
        LegacyRouteSpec("/admin/cursos", "admin_cursos", admin_cursos, ("GET",)),
        LegacyRouteSpec(
            "/admin/cursos/adicionar",
            "admin_adicionar_curso",
            admin_adicionar_curso,
            ("GET", "POST"),
        ),
        LegacyRouteSpec(
            "/admin/cursos/<int:curso_id>/editar",
            "admin_editar_curso",
            admin_editar_curso,
            ("GET", "POST"),
        ),
        LegacyRouteSpec(
            "/admin/cursos/<int:curso_id>",
            "admin_detalhes_curso",
            admin_detalhes_curso,
            ("GET",),
        ),
        LegacyRouteSpec(
            "/admin/cursos/<int:curso_id>/visualizar",
            "admin_visualizar_curso",
            admin_visualizar_curso,
            ("GET",),
        ),
        LegacyRouteSpec(
            "/admin/deletar_curso/<int:curso_id>",
            "admin_deletar_curso",
            admin_deletar_curso,
            ("POST",),
        ),
        LegacyRouteSpec("/admin/alunos", "admin_alunos", admin_alunos, ("GET",)),
        LegacyRouteSpec(
            "/admin/adicionar_aluno",
            "admin_adicionar_aluno",
            admin_adicionar_aluno,
            ("GET", "POST"),
        ),
        LegacyRouteSpec(
            "/admin/editar_aluno/<int:usuario_id>",
            "admin_editar_aluno",
            admin_editar_aluno,
            ("GET", "POST"),
        ),
        LegacyRouteSpec(
            "/admin/deletar_aluno/<int:usuario_id>",
            "admin_deletar_aluno",
            admin_deletar_aluno,
            ("POST",),
        ),
        LegacyRouteSpec(
            "/admin/alterar_status_alunos",
            "admin_alterar_status_alunos",
            admin_alterar_status_alunos,
            ("POST",),
        ),
        LegacyRouteSpec("/admin/turmas", "admin_turmas", admin_turmas, ("GET",)),
        LegacyRouteSpec(
            "/admin/adicionar_turma",
            "admin_adicionar_turma",
            admin_adicionar_turma,
            ("GET", "POST"),
        ),
        LegacyRouteSpec(
            "/admin/editar_turma/<int:turma_id>",
            "admin_editar_turma",
            admin_editar_turma,
            ("GET", "POST"),
        ),
        LegacyRouteSpec(
            "/admin/deletar_turma/<int:turma_id>",
            "admin_deletar_turma",
            admin_deletar_turma,
            ("POST",),
        ),
        LegacyRouteSpec(
            "/admin/turma/<int:turma_id>",
            "admin_detalhes_turma",
            admin_detalhes_turma,
            ("GET",),
        ),
        LegacyRouteSpec(
            "/admin/turmas/importar",
            "admin_turmas_importar",
            admin_turmas_importar,
            ("GET", "POST"),
        ),
    ),
)


__all__ = [
    "LEGACY_ROUTE_SPECS",
    "admin_adicionar_aluno",
    "admin_adicionar_curso",
    "admin_adicionar_turma",
    "admin_alunos",
    "admin_alterar_status_alunos",
    "admin_cursos",
    "admin_deletar_aluno",
    "admin_deletar_curso",
    "admin_deletar_turma",
    "admin_detalhes_curso",
    "admin_detalhes_turma",
    "admin_editar_aluno",
    "admin_editar_curso",
    "admin_editar_turma",
    "admin_turmas",
    "admin_turmas_importar",
    "admin_visualizar_curso",
    "bp_admin_alunos_turmas_cursos",
    "curso_mais_populoso_id",
    "proximo_numero_turma_por_curso",
    "resolve_existing_aluno_by_identifiers",
    "semestre_atual_hoje",
    "validar_codigo_curso",
    "_matrizes_by_curso",
    "_periodo_label_for_turma_row",
    "_resolve_turma_matriz_id",
    "_safe_return_to_target",
    "_turma_effective_matriz_label",
]
