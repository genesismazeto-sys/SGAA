# coding: utf-8
"""UT-9: dono canonico do cohort "Acesso".

9 simbolos relocados de main.py por MOVE-VERBATIM (6 rotas, 3 helpers e 0
constantes). Nenhuma importacao de main; registra apenas rotas legadas via
LegacyRouteSpec.
"""

from __future__ import annotations

import sqlite3

from flask import (
    Blueprint,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from app.academics import resequence_turma_aluno_matriculas_for_ids
from app.admin_access import _load_admin_access_context
from app.auth import (
    ACCESS_LEVEL_META,
    ACCESS_RESOURCE_GROUPS,
    ACCESS_RESOURCE_ORDER,
    ACCESS_RESOURCES_META,
    access_level_label,
    access_level_to_user_type,
    admin_required,
    canonicalize_access_level,
    merge_resource_scopes,
    normalize_permission_scope,
    permission_scope_label,
)
from app.db import get_db_connection
from app.db_maintenance import (
    ensure_usuario_access_schema,
    ensure_usuario_profile_schema,
)
from app.security.passwords import hash_password
from app.user_accounts import _access_defaults_map
from app.views.admin import LegacyRouteSpec, configure_legacy_routes
from app.web.filters import (
    append_conditions_sql,
    append_text_contains_condition,
    get_int_multi_query_values,
    get_multi_query_values,
    get_text_query_value,
)
from app.web.pagination import get_pagination, wants_pagination
from app.web.request import _is_ajax_request
from utils.messages import flash


def _persist_user_access_overrides(conn, usuario_id: int, access_level: str, overrides: dict[str, str]) -> None:
    ensure_usuario_access_schema(conn)
    defaults = merge_resource_scopes(access_level)
    conn.execute("DELETE FROM usuarios_permissoes_acesso WHERE usuario_id = ?", (usuario_id,))
    for recurso in ACCESS_RESOURCE_ORDER:
        if recurso not in overrides:
            continue
        escopo = normalize_permission_scope(overrides[recurso], defaults.get(recurso, "none"))
        if escopo == defaults.get(recurso, "none"):
            continue
        conn.execute(
            "INSERT INTO usuarios_permissoes_acesso (usuario_id, recurso, escopo) VALUES (?, ?, ?)",
            (usuario_id, recurso, escopo),
        )


def _parse_access_overrides_from_form(form) -> dict[str, str]:
    overrides = {}
    for recurso in ACCESS_RESOURCE_ORDER:
        value = (form.get(f"scope_{recurso}") or "").strip()
        if not value or value == "inherit":
            continue
        overrides[recurso] = normalize_permission_scope(value, "none")
    return overrides


def _turma_label_by_id(conn, turma_id: int | None) -> str:
    if not turma_id:
        return ""
    row = conn.execute(
        "SELECT COALESCE(codigo, nome) AS label FROM turmas WHERE id = ?",
        (turma_id,),
    ).fetchone()
    return (row["label"] or "") if row else ""


@admin_required
def admin_acesso():
    page, per_page, offset = get_pagination(default_per_page=25)
    q = (request.args.get("q") or "").strip()
    sort_field = (request.args.get("s") or "nome").strip().lower()
    sort_dir = (request.args.get("dir") or "asc").strip().lower()
    nome_filter = get_text_query_value("nome")
    email_filter = get_text_query_value("email")
    matricula_filter = get_text_query_value("matricula")
    turma_filters = get_int_multi_query_values("turma_id")
    nivel_filters = {canonicalize_access_level(item) for item in get_multi_query_values("nivel")}
    tipo_filters = {str(item or "").strip().lower() for item in get_multi_query_values("tipo")}

    conn = get_db_connection()
    ensure_usuario_access_schema(conn)
    ensure_usuario_profile_schema(conn)

    summary_rows = conn.execute(
        "SELECT nivel_acesso, COUNT(*) AS total FROM usuarios GROUP BY nivel_acesso"
    ).fetchall()
    summary = {"admin_total": 0, "consultivo": 0, "administrativo": 0, "usuario": 0, "usuario_teste": 0}
    for row in summary_rows:
        summary[canonicalize_access_level(row["nivel_acesso"])] = row["total"]

    access_defaults = _access_defaults_map(conn)
    turmas = conn.execute(
        "SELECT id, COALESCE(codigo, nome) AS nome FROM turmas ORDER BY nome"
    ).fetchall()

    base_from = """
        FROM usuarios u
        LEFT JOIN alunos a ON a.usuario_id = u.id
        LEFT JOIN turmas t ON t.id = a.turma_id
    """
    where = []
    params = []
    if q:
        like = f"%{q}%"
        where.append(
            "(u.nome LIKE ? OR u.email LIKE ? OR COALESCE(a.matricula, '') LIKE ? OR COALESCE(t.codigo, t.nome, a.turma, '') LIKE ?)"
        )
        params.extend([like, like, like, like])
    append_text_contains_condition(where, params, "u.nome", nome_filter)
    append_text_contains_condition(where, params, "u.email", email_filter)
    append_text_contains_condition(where, params, "a.matricula", matricula_filter)
    if turma_filters:
        placeholders = ", ".join("?" for _ in turma_filters)
        where.append(f"a.turma_id IN ({placeholders})")
        params.extend(turma_filters)
    if nivel_filters:
        placeholders = ", ".join("?" for _ in nivel_filters)
        where.append(f"u.nivel_acesso IN ({placeholders})")
        params.extend(sorted(nivel_filters))
    if tipo_filters:
        placeholders = ", ".join("?" for _ in tipo_filters)
        where.append(f"u.tipo IN ({placeholders})")
        params.extend(sorted(tipo_filters))

    where_sql = append_conditions_sql(False, where)
    order_map = {
        "nome": "LOWER(u.nome)",
        "email": "LOWER(u.email)",
        "nivel": "LOWER(u.nivel_acesso)",
        "perfil": "LOWER(u.tipo)",
        "matricula": "LOWER(COALESCE(a.matricula, ''))",
    }
    order_col = order_map.get(sort_field, order_map["nome"])
    direction = "DESC" if sort_dir == "desc" else "ASC"
    count_sql = "SELECT COUNT(*) " + base_from + where_sql
    total = conn.execute(count_sql, params).fetchone()[0]
    query = (
        """
        SELECT
            u.id,
            u.nome,
            u.email,
            u.tipo,
            u.nivel_acesso,
            a.id AS aluno_id,
            a.matricula,
            a.status AS aluno_status,
            a.turma_id,
            COALESCE(t.codigo, t.nome, a.turma, '') AS turma_label
        """
        + base_from
        + where_sql
        + f" ORDER BY {order_col} {direction}, u.id DESC"
    )
    params_exec = list(params)
    apply_limit = wants_pagination()
    if apply_limit:
        query += " LIMIT ? OFFSET ?"
        params_exec += [per_page, offset]

    rows = conn.execute(query, params_exec).fetchall()
    current_user_id = session.get("user_id")
    users = []
    users_payload = {}
    for row in rows:
        nivel = canonicalize_access_level(row["nivel_acesso"])
        tipo = (row["tipo"] or "admin").strip().lower()
        is_student = tipo == "aluno"
        access_context = _load_admin_access_context(conn, row["id"]) if not is_student else {
            "is_admin": False,
            "overrides": {},
            "effective_scopes": {},
            "scope_groups": [],
        }
        users.append(
            {
                "id": row["id"],
                "nome": row["nome"],
                "email": row["email"],
                "tipo": tipo,
                "tipo_label": "Aluno" if is_student else "Admin",
                "nivel_acesso": nivel,
                "nivel_label": access_level_label(nivel),
                "matricula": row["matricula"] if is_student else "",
                "turma_id": row["turma_id"] if is_student else "",
                "turma_label": row["turma_label"] if is_student else "",
                "aluno_status": row["aluno_status"] if is_student else "Ativo",
                "has_aluno": bool(row["aluno_id"]) and is_student,
                "is_current_user": row["id"] == current_user_id,
                "scope_summary": access_context.get("scope_groups", []),
            }
        )
        users_payload[str(row["id"])] = {
            "id": row["id"],
            "nome": row["nome"],
            "email": row["email"],
            "tipo": tipo,
            "level": nivel,
            "matricula": row["matricula"] if is_student else "",
            "turmaId": row["turma_id"] if is_student else "",
            "turmaLabel": row["turma_label"] if is_student else "",
            "status": row["aluno_status"] if is_student else "Ativo",
            "isSelf": row["id"] == current_user_id,
            "canCustomize": not is_student,
            "accessOverrides": access_context.get("overrides", {}),
            "effectiveScopes": access_context.get("effective_scopes", {}),
            "scopeGroups": access_context.get("scope_groups", []),
        }

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
            "param": "matricula",
            "label": "Matrícula",
            "type": "text_contains",
            "placeholder": "Contém na matrícula",
        },
        {
            "param": "turma_id",
            "label": "Turma",
            "type": "multi_select",
            "values": [
                {"value": str(turma["id"]), "label": turma["nome"]}
                for turma in turmas
            ],
        },
        {
            "param": "nivel",
            "label": "Nível",
            "type": "multi_select",
            "values": [
                {"value": "admin_total", "label": "Admin"},
                {"value": "consultivo", "label": "Consultor"},
                {"value": "administrativo", "label": "Coordenador"},
                {"value": "usuario", "label": "Usuário"},
                {"value": "usuario_teste", "label": "Usuário teste"},
            ],
        },
        {
            "param": "tipo",
            "label": "Perfil base",
            "type": "multi_select",
            "values": [
                {"value": "admin", "label": "Admin"},
                {"value": "aluno", "label": "Aluno"},
            ],
        },
    ]
    access_resource_groups = []
    for group_label, resources in ACCESS_RESOURCE_GROUPS:
        access_resource_groups.append(
            {
                "label": group_label,
                "items": [
                    {
                        "resource": resource,
                        "label": ACCESS_RESOURCES_META[resource]["label"],
                    }
                    for resource in resources
                ],
            }
        )
    access_scope_options = [
        {"value": "inherit", "label": "Herdar perfil"},
        {"value": "none", "label": permission_scope_label("none")},
        {"value": "view", "label": permission_scope_label("view")},
        {"value": "edit", "label": permission_scope_label("edit")},
        {"value": "full", "label": permission_scope_label("full")},
    ]
    access_level_choices = [
        {"value": value, "label": meta["label"]}
        for value, meta in ACCESS_LEVEL_META.items()
    ]
    access_profile_defaults = {
        level: merge_resource_scopes(level)
        for level in ACCESS_LEVEL_META
    }
    total_pages = (total + per_page - 1) // per_page if apply_limit and per_page else 1
    return render_template(
        "admin_acesso.html",
        summary=summary,
        access_defaults=access_defaults,
        access_level_choices=access_level_choices,
        access_profile_defaults=access_profile_defaults,
        access_resource_groups=access_resource_groups,
        access_scope_options=access_scope_options,
        turmas=turmas,
        users=users,
        users_payload=users_payload,
        filter_schema=filter_schema,
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages,
    )


@admin_required
def admin_acesso_salvar_senhas_default():
    conn = get_db_connection()
    ensure_usuario_access_schema(conn)
    updates = {
        "admin_total": (request.form.get("default_admin_total") or "").strip(),
        "consultivo": (request.form.get("default_consultivo") or "").strip(),
        "administrativo": (request.form.get("default_administrativo") or "").strip(),
        "usuario": (request.form.get("default_usuario") or "").strip(),
        "usuario_teste": (request.form.get("default_usuario_teste") or "").strip(),
    }
    if not all(updates.values()):
        flash("Todas as senhas default precisam ser informadas.", "error")
        return redirect(url_for("admin_acesso"))
    for nivel, senha_padrao in updates.items():
        conn.execute(
            """
            INSERT INTO configuracoes_acesso (nivel_acesso, senha_padrao)
            VALUES (?, ?)
            ON CONFLICT(nivel_acesso) DO UPDATE SET senha_padrao = excluded.senha_padrao
            """,
            (nivel, senha_padrao),
        )
    conn.commit()
    flash("Senhas padrão atualizadas com sucesso.", "success")
    return redirect(url_for("admin_acesso"))


@admin_required
def admin_acesso_salvar():
    conn = get_db_connection()
    ensure_usuario_access_schema(conn)
    ensure_usuario_profile_schema(conn)

    usuario_id = request.form.get("usuario_id", type=int)
    nome = (request.form.get("nome") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    nivel_acesso = canonicalize_access_level(request.form.get("nivel_acesso"))
    user_type = access_level_to_user_type(nivel_acesso)
    senha = (request.form.get("senha") or "").strip()
    matricula = (request.form.get("matricula") or "").strip()
    status_aluno = (request.form.get("status") or "Ativo").strip()
    turma_id = request.form.get("turma_id", type=int)
    access_overrides = _parse_access_overrides_from_form(request.form) if user_type == "admin" else {}

    if not nome or not email:
        flash("Nome e e-mail são obrigatórios.", "error")
        return redirect(url_for("admin_acesso"))
    if user_type == "aluno" and not matricula:
        flash("Matrícula é obrigatória para perfis de aluno.", "error")
        return redirect(url_for("admin_acesso"))
    if status_aluno not in {"Ativo", "Inativo"}:
        status_aluno = "Ativo"

    dup_email = conn.execute(
        "SELECT id FROM usuarios WHERE LOWER(email) = LOWER(?) AND (? IS NULL OR id <> ?)",
        (email, usuario_id, usuario_id),
    ).fetchone()
    if dup_email:
        flash("Já existe um usuário com este e-mail.", "error")
        return redirect(url_for("admin_acesso"))

    turma_label = _turma_label_by_id(conn, turma_id)
    defaults = _access_defaults_map(conn)

    try:
        if usuario_id:
            usuario = conn.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
            if not usuario:
                flash("Usuário não encontrado.", "error")
                return redirect(url_for("admin_acesso"))
            if senha:
                conn.execute(
                    "UPDATE usuarios SET nome = ?, email = ?, tipo = ?, nivel_acesso = ?, senha = ? WHERE id = ?",
                    (nome, email, user_type, nivel_acesso, hash_password(senha), usuario_id),
                )
            else:
                conn.execute(
                    "UPDATE usuarios SET nome = ?, email = ?, tipo = ?, nivel_acesso = ? WHERE id = ?",
                    (nome, email, user_type, nivel_acesso, usuario_id),
                )
        else:
            senha_final = senha or defaults.get(nivel_acesso, "admin123")
            cursor = conn.execute(
                "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?)",
                (nome, email, hash_password(senha_final), user_type, nivel_acesso),
            )
            usuario_id = cursor.lastrowid

        aluno_existente = conn.execute("SELECT id, turma_id FROM alunos WHERE usuario_id = ?", (usuario_id,)).fetchone()
        if user_type == "aluno":
            dup_matricula = conn.execute(
                "SELECT id FROM alunos WHERE matricula = ? AND usuario_id <> ?",
                (matricula, usuario_id),
            ).fetchone()
            if dup_matricula:
                conn.rollback()
                flash("Já existe um aluno com esta matrícula.", "error")
                return redirect(url_for("admin_acesso"))
            if aluno_existente:
                conn.execute(
                    """
                    UPDATE alunos
                       SET nome = ?, email = ?, matricula = ?, turma = ?, turma_id = ?, status = ?
                     WHERE usuario_id = ?
                    """,
                    (nome, email, matricula, turma_label or None, turma_id, status_aluno, usuario_id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO alunos (usuario_id, nome, matricula, email, turma, turma_id, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (usuario_id, nome, matricula, email, turma_label or None, turma_id, status_aluno),
                )
        elif aluno_existente:
            conn.execute(
                "UPDATE alunos SET nome = ?, email = ? WHERE usuario_id = ?",
                (nome, email, usuario_id),
            )

        if user_type == "aluno":
            resequence_turma_aluno_matriculas_for_ids(
                conn,
                aluno_existente["turma_id"] if aluno_existente else None,
                turma_id,
            )
        elif aluno_existente:
            resequence_turma_aluno_matriculas_for_ids(conn, aluno_existente["turma_id"])

        _persist_user_access_overrides(conn, usuario_id, nivel_acesso, access_overrides if user_type == "admin" else {})

        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        flash(f"Falha ao salvar acesso: {exc}", "error")
        return redirect(url_for("admin_acesso"))

    if usuario_id == session.get("user_id"):
        session["user_type"] = user_type
        session["access_level"] = nivel_acesso
        session["perfil"] = access_level_label(nivel_acesso)
        if user_type != "admin":
            session.clear()
            flash("Seu perfil foi alterado. Faça login novamente para continuar.", "success")
            return redirect(url_for("login"))

    flash("Acesso salvo com sucesso.", "success")
    return redirect(url_for("admin_acesso"))


@admin_required
def admin_acesso_resetar_senha(usuario_id):
    conn = get_db_connection()
    ensure_usuario_access_schema(conn)
    usuario = conn.execute("SELECT id, nome, nivel_acesso FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    if not usuario:
        flash("Usuário não encontrado.", "error")
        return redirect(url_for("admin_acesso"))
    defaults = _access_defaults_map(conn)
    nivel = canonicalize_access_level(usuario["nivel_acesso"])
    nova_senha = defaults.get(nivel, "admin123")
    conn.execute("UPDATE usuarios SET senha = ? WHERE id = ?", (hash_password(nova_senha), usuario_id))
    conn.commit()
    flash(f"Senha de {usuario['nome']} resetada para o padrão do nível.", "success")
    return redirect(url_for("admin_acesso"))


@admin_required
def admin_acesso_definir_senha():
    usuario_ids = []
    for raw_value in request.form.getlist("usuario_ids"):
        if str(raw_value).strip().isdigit():
            usuario_ids.append(int(raw_value))
    usuario_ids = sorted(set(usuario_ids))
    nova_senha = (request.form.get("nova_senha") or "").strip()

    if not usuario_ids:
        if _is_ajax_request():
            return jsonify({"ok": False, "error": "missing-users"}), 400
        flash("Selecione ao menos um acesso para definir a nova senha.", "error")
        return redirect(url_for("admin_acesso"))

    if not nova_senha:
        if _is_ajax_request():
            return jsonify({"ok": False, "error": "missing-password"}), 400
        flash("Informe a nova senha.", "error")
        return redirect(url_for("admin_acesso"))

    conn = get_db_connection()
    placeholders = ", ".join("?" for _ in usuario_ids)
    rows = conn.execute(
        f"SELECT id, nome FROM usuarios WHERE id IN ({placeholders})",
        usuario_ids,
    ).fetchall()
    found_ids = {row["id"] for row in rows}
    missing_ids = [usuario_id for usuario_id in usuario_ids if usuario_id not in found_ids]
    if missing_ids:
        if _is_ajax_request():
            return jsonify({"ok": False, "error": "not-found", "missing_ids": missing_ids}), 404
        flash("Um ou mais acessos selecionados não foram encontrados.", "error")
        return redirect(url_for("admin_acesso"))

    conn.execute(
        f"UPDATE usuarios SET senha = ? WHERE id IN ({placeholders})",
        [hash_password(nova_senha), *usuario_ids],
    )
    conn.commit()

    if _is_ajax_request():
        return jsonify({"ok": True, "updated": len(usuario_ids)})

    flash("Nova senha aplicada com sucesso.", "success")
    return redirect(url_for("admin_acesso"))


@admin_required
def admin_acesso_deletar(usuario_id):
    if usuario_id == session.get("user_id"):
        flash("Você não pode excluir o próprio acesso.", "error")
        return redirect(url_for("admin_acesso"))

    conn = get_db_connection()
    ensure_usuario_profile_schema(conn)
    try:
        aluno = conn.execute("SELECT turma_id FROM alunos WHERE usuario_id = ?", (usuario_id,)).fetchone()
        conn.execute("DELETE FROM alunos WHERE usuario_id = ?", (usuario_id,))
        conn.execute("DELETE FROM usuarios WHERE id = ?", (usuario_id,))
        resequence_turma_aluno_matriculas_for_ids(conn, aluno["turma_id"] if aluno else None)
        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        flash(f"Não foi possível excluir o acesso: {exc}", "error")
        return redirect(url_for("admin_acesso"))
    flash("Acesso excluído com sucesso.", "success")
    return redirect(url_for("admin_acesso"))


bp_admin_acesso = Blueprint("admin_acesso_blueprint", __name__)

LEGACY_ROUTE_SPECS = configure_legacy_routes(
    bp_admin_acesso,
    (
        LegacyRouteSpec(
            "/admin/acesso",
            "admin_acesso",
            admin_acesso,
            ("GET",),
        ),
        LegacyRouteSpec(
            "/admin/acesso/senhas-default",
            "admin_acesso_salvar_senhas_default",
            admin_acesso_salvar_senhas_default,
            ("POST",),
        ),
        LegacyRouteSpec(
            "/admin/acesso/salvar",
            "admin_acesso_salvar",
            admin_acesso_salvar,
            ("POST",),
        ),
        LegacyRouteSpec(
            "/admin/acesso/<int:usuario_id>/resetar-senha",
            "admin_acesso_resetar_senha",
            admin_acesso_resetar_senha,
            ("POST",),
        ),
        LegacyRouteSpec(
            "/admin/acesso/definir-senha",
            "admin_acesso_definir_senha",
            admin_acesso_definir_senha,
            ("POST",),
        ),
        LegacyRouteSpec(
            "/admin/acesso/<int:usuario_id>/deletar",
            "admin_acesso_deletar",
            admin_acesso_deletar,
            ("POST",),
        ),
    ),
)


__all__ = [
    "LEGACY_ROUTE_SPECS",
    "_parse_access_overrides_from_form",
    "_persist_user_access_overrides",
    "_turma_label_by_id",
    "admin_acesso",
    "admin_acesso_deletar",
    "admin_acesso_definir_senha",
    "admin_acesso_resetar_senha",
    "admin_acesso_salvar",
    "admin_acesso_salvar_senhas_default",
    "bp_admin_acesso",
]
