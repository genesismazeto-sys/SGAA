# coding: utf-8
"""UT-9: dono canonico do cohort "Acesso".

Owner of the Acesso cohort (9 routes and 3 helpers). Nenhuma importacao de
main; registra apenas rotas legadas via LegacyRouteSpec.
"""

from __future__ import annotations

import logging
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
from app.access_default_password import (
    default_password_eligibility,
    default_password_eligibility_map,
)
from app.access_onboarding import access_status_map
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
from app.password_email import issue_and_send_password_email, password_email_status
from app.password_tokens import PURPOSE_FIRST_ACCESS, PURPOSE_PASSWORD_RESET
from app.student_matrix import StudentMatrixError, matrix_for_turma_assignment
from app.root_admin import is_root_admin, resolve_root_admin_id
from app.user_accounts import (
    CREDENTIAL_STATE_DEFAULT,
    CREDENTIAL_STATE_PENDING,
    CREDENTIAL_STATE_PERSONAL,
    _access_defaults_map,
    create_usuario_with_access_level,
    get_usuario_auth_version,
    invalidate_usuario_password_tokens,
    set_usuario_access_active,
    set_usuario_password_hash,
    set_usuarios_password_hash,
    unusable_password_hash,
    usuario_access_is_active,
)
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


logger = logging.getLogger(__name__)


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


def _revoke_usuario_access(conn, usuario_id: int) -> None:
    """End an account's ability to authenticate without deleting the row.

    This is the domain operation behind "Excluir acesso" for any account that
    history still references (an upload's ``uploader_user_id``, for instance).
    The usuarios row -- and every attribution pointing at it -- survives
    intact; what goes is the ability to log in:

    * ``acesso_ativo`` becomes 0.  This is the durable fact, checked at login
      before any password comparison can matter, so a revoked account is
      refused even with a correct personal or applied default password;
    * the same write bumps ``auth_version``, which the session guard reads on
      every request, so live sessions die on their next request;
    * outstanding first-access/reset tokens are invalidated, so a password
      e-mail already in flight cannot hand the account back;
    * the stored hash is replaced by an unusable random value and the state
      becomes ``pending``, so nothing is left that could match even if the
      status were later misread.

    Reactivation is an explicit administrative act -- see
    ``_reactivate_usuario_access``.  The caller owns the transaction.
    """
    set_usuario_password_hash(
        conn,
        usuario_id,
        unusable_password_hash(),
        credential_state=CREDENTIAL_STATE_PENDING,
    )
    invalidate_usuario_password_tokens(conn, [usuario_id])
    set_usuario_access_active(conn, usuario_id, False)


def _reactivate_usuario_access(conn, usuario_id: int, *, senha: str, nivel_acesso: str) -> None:
    """Explicitly restore login capability to a previously revoked account.

    Reactivation always defines the credential state outright rather than
    inheriting whatever the revoked row happened to carry.  An explicit
    password makes the account ``personal``; without one it is ``pending``,
    exactly as a newly created account would be -- so the first-access e-mail
    is the coherent way back in, and "Aplicar senha padrão" the explicit
    alternative.

    Any token issued before revocation stays invalid: this re-issues nothing.
    """
    if senha:
        senha_hash = hash_password(senha)
        credential_state = CREDENTIAL_STATE_PERSONAL
    else:
        senha_hash = unusable_password_hash()
        credential_state = CREDENTIAL_STATE_PENDING
    set_usuario_password_hash(conn, usuario_id, senha_hash, credential_state=credential_state)
    invalidate_usuario_password_tokens(conn, [usuario_id])
    set_usuario_access_active(conn, usuario_id, True)


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

    # Counts describe the active surface, matching the list below.
    summary_rows = conn.execute(
        """
        SELECT u.nivel_acesso AS nivel_acesso, COUNT(*) AS total
          FROM usuarios u
          LEFT JOIN usuario_credenciais c ON c.usuario_id = u.id
         WHERE COALESCE(c.acesso_ativo, 1) = 1
         GROUP BY u.nivel_acesso
        """
    ).fetchall()
    summary = {"admin_total": 0, "consultivo": 0, "administrativo": 0, "usuario": 0, "usuario_teste": 0}
    for row in summary_rows:
        summary[canonicalize_access_level(row["nivel_acesso"])] = row["total"]

    access_defaults = _access_defaults_map(conn)
    mail_status = password_email_status(conn)
    turmas = conn.execute(
        "SELECT id, COALESCE(codigo, nome) AS nome FROM turmas ORDER BY nome"
    ).fetchall()

    base_from = """
        FROM usuarios u
        LEFT JOIN alunos a ON a.usuario_id = u.id
        LEFT JOIN turmas t ON t.id = a.turma_id
        LEFT JOIN usuario_credenciais c ON c.usuario_id = u.id
    """
    # A revoked access is not an ordinary access: it is history kept for
    # attribution. The active list therefore excludes it, while the identity
    # stays findable by the re-creation path in admin_acesso_salvar, which
    # reuses it rather than minting a duplicate.
    where = ["COALESCE(c.acesso_ativo, 1) = 1"]
    params = []
    if q:
        like = f"%{q}%"
        where.append(
            "(u.nome LIKE ? OR u.email LIKE ? OR COALESCE(a.matricula, '') LIKE ? OR COALESCE(t.codigo, t.nome, '') LIKE ?)"
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
            COALESCE(t.codigo, t.nome, '') AS turma_label,
            c.estado AS credential_state,
            c.auth_version
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
    root_admin_id = resolve_root_admin_id(conn)
    # Access/onboarding lifecycle for the whole page in two queries -- never one
    # per row. Owner: app/access_onboarding.py, which derives it from durable
    # credential and confirmed-delivery evidence alone.
    access_status_by_id = access_status_map(conn, [row["id"] for row in rows])
    # Whether "Aplicar senha padrão" is offered, per row, from the single owner
    # the endpoint also consults -- app/access_default_password.py. The action
    # bar must never re-derive this from the level or the pill.
    default_password_by_id = default_password_eligibility_map(
        conn, [row["id"] for row in rows]
    )
    users = []
    users_payload = {}
    for row in rows:
        nivel = canonicalize_access_level(row["nivel_acesso"])
        default_password = default_password_by_id[row["id"]]
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
                "is_root_admin": row["id"] == root_admin_id,
                "scope_summary": access_context.get("scope_groups", []),
                # Distinct key from "aluno_status": that one is the academic
                # Ativo/Inativo, this one is the login lifecycle. They must never
                # be read for each other.
                "access_status": access_status_by_id.get(row["id"], ""),
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
            # The root administrator is the recovery path: the UI must not
            # offer to delete, revoke or demote it.  The backend refuses
            # regardless -- this only keeps the affordance honest.
            "isRootAdmin": row["id"] == root_admin_id,
            "canCustomize": not is_student,
            "accessOverrides": access_context.get("overrides", {}),
            "effectiveScopes": access_context.get("effective_scopes", {}),
            "scopeGroups": access_context.get("scope_groups", []),
            "credentialState": row["credential_state"],
            # Mirrors the Situação pill: only a pending account is still being
            # onboarded; one holding a usable credential gets a reset link.
            "emailActionLabel": (
                "Enviar acesso"
                if row["credential_state"] == CREDENTIAL_STATE_PENDING
                else "Redefinir por e-mail"
            ),
            "emailActionUrl": url_for("admin_acesso_senha_por_email", usuario_id=row["id"]),
            # Authoritative, not a hint: the action bar renders exactly this.
            # The reason travels with it so a disabled action can say why
            # instead of looking broken.
            "canApplyDefaultPassword": default_password.allowed,
            "applyDefaultPasswordReason": default_password.reason,
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
        mail_status=mail_status,
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
    # Configuration only.  Saving writes configuracoes_acesso and nothing else:
    # no usuarios.senha hash and no credential state moves.  An account opts
    # into the shared default only through "Aplicar senha padrão", which hashes
    # the value configured at THAT moment into the account's own row -- so an
    # edit here reaches an account only when the default is (re)applied to it.
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

    # Re-creating access for somebody whose access was revoked must reuse the
    # preserved identity, never mint a second one.  The revoked usuarios row
    # still owns the UNIQUE e-mail and is still the uploader of record for its
    # history, so a fresh INSERT would both collide and orphan that history.
    # Matching on e-mail OR matrícula covers the two ways an admin identifies
    # the same person on this screen.
    reactivating = False
    if not usuario_id:
        revoked = conn.execute(
            """
            SELECT u.id AS id
              FROM usuarios u
              JOIN usuario_credenciais c ON c.usuario_id = u.id
              LEFT JOIN alunos a ON a.usuario_id = u.id
             WHERE c.acesso_ativo = 0
               AND (LOWER(u.email) = LOWER(?)
                    OR (? <> '' AND a.matricula = ?))
             ORDER BY u.id
             LIMIT 1
            """,
            (email, matricula, matricula),
        ).fetchone()
        if revoked:
            usuario_id = int(revoked["id"])
            reactivating = True

    dup_email = conn.execute(
        "SELECT id FROM usuarios WHERE LOWER(email) = LOWER(?) AND (? IS NULL OR id <> ?)",
        (email, usuario_id, usuario_id),
    ).fetchone()
    if dup_email:
        flash("Já existe um usuário com este e-mail.", "error")
        return redirect(url_for("admin_acesso"))

    # The root administrator is the system's only recovery path.  Its password
    # may be changed freely -- the break-glass credential is independent of it
    # -- but its identity may not be moved or demoted here: the root identity
    # is keyed to the configured address, so editing that address through this
    # screen would silently leave the installation with no root at all.
    if usuario_id and is_root_admin(conn, usuario_id):
        root_row = conn.execute(
            "SELECT email FROM usuarios WHERE id = ?", (usuario_id,)
        ).fetchone()
        if root_row and email != str(root_row["email"] or "").strip().lower():
            flash(
                "O e-mail do administrador raiz não pode ser alterado por esta tela.",
                "error",
            )
            return redirect(url_for("admin_acesso"))
        if user_type != "admin" or nivel_acesso != "admin_total":
            flash(
                "O administrador raiz não pode ser rebaixado: é a única via de recuperação do sistema.",
                "error",
            )
            return redirect(url_for("admin_acesso"))

    turma_label = _turma_label_by_id(conn, turma_id)

    try:
        if usuario_id:
            usuario = conn.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
            if not usuario:
                flash("Usuário não encontrado.", "error")
                return redirect(url_for("admin_acesso"))
            conn.execute(
                "UPDATE usuarios SET nome = ?, email = ?, tipo = ?, nivel_acesso = ? WHERE id = ?",
                (nome, email, user_type, nivel_acesso, usuario_id),
            )
            if reactivating:
                # Reactivation states the credential outright instead of
                # inheriting whatever the revoked row carried, and leaves every
                # pre-revocation token invalid.
                _reactivate_usuario_access(
                    conn, usuario_id, senha=senha, nivel_acesso=nivel_acesso
                )
            elif senha:
                set_usuario_password_hash(
                    conn,
                    usuario_id,
                    hash_password(senha),
                    credential_state=CREDENTIAL_STATE_PERSONAL,
                )
        else:
            # A blank password creates a "pending" account: it exists, it is
            # listed, and it cannot authenticate until its first-access e-mail
            # is completed (-> personal) or an administrator explicitly applies
            # the profile default (-> default).  It never receives the shared
            # default implicitly.
            if senha:
                senha_hash = hash_password(senha)
                credential_state = CREDENTIAL_STATE_PERSONAL
            else:
                senha_hash = unusable_password_hash()
                credential_state = CREDENTIAL_STATE_PENDING
            cursor = create_usuario_with_access_level(
                conn,
                nome,
                email,
                senha_hash,
                user_type,
                nivel_acesso,
                credential_state=credential_state,
            )
            usuario_id = cursor.lastrowid

        aluno_existente = conn.execute("SELECT id, turma_id, matriz_id FROM alunos WHERE usuario_id = ?", (usuario_id,)).fetchone()
        if user_type == "aluno":
            if not aluno_existente:
                # Deleting an access detaches its aluno instead of destroying
                # it, so the academic record outlives the login and keeps its
                # UNIQUE matrícula/e-mail. Re-creating the access must adopt
                # that record -- otherwise the insert below collides with it
                # and the person is stranded without a login forever.
                detached = conn.execute(
                    """
                    SELECT id, turma_id, matriz_id FROM alunos
                     WHERE usuario_id IS NULL
                       AND (matricula = ? OR LOWER(COALESCE(email, '')) = LOWER(?))
                     ORDER BY (matricula = ?) DESC, id
                     LIMIT 1
                    """,
                    (matricula, email, matricula),
                ).fetchone()
                if detached:
                    conn.execute(
                        "UPDATE alunos SET usuario_id = ? WHERE id = ?",
                        (usuario_id, detached["id"]),
                    )
                    aluno_existente = detached
            # NULL-safe: `usuario_id <> ?` silently skips detached rows, whose
            # matrícula is exactly the one that would collide on INSERT.
            dup_matricula = conn.execute(
                "SELECT id FROM alunos WHERE matricula = ? AND (usuario_id IS NULL OR usuario_id <> ?)",
                (matricula, usuario_id),
            ).fetchone()
            if dup_matricula:
                conn.rollback()
                flash("Já existe um aluno com esta matrícula.", "error")
                return redirect(url_for("admin_acesso"))
            if aluno_existente:
                matriz_id = matrix_for_turma_assignment(
                    conn,
                    current_matriz_id=aluno_existente["matriz_id"],
                    turma_id=turma_id,
                    current_turma_id=aluno_existente["turma_id"],
                )
                conn.execute(
                    """
                    UPDATE alunos
                       SET nome = ?, email = ?, matricula = ?, turma_id = ?, matriz_id = ?, status = ?
                     WHERE usuario_id = ?
                    """,
                    (nome, email, matricula, turma_id, matriz_id, status_aluno, usuario_id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, matriz_id, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        usuario_id,
                        nome,
                        matricula,
                        email,
                        turma_id,
                        matrix_for_turma_assignment(
                            conn, current_matriz_id=None, turma_id=turma_id
                        ),
                        status_aluno,
                    ),
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
    except (sqlite3.IntegrityError, StudentMatrixError) as exc:
        conn.rollback()
        flash(f"Falha ao salvar acesso: {exc}", "error")
        return redirect(url_for("admin_acesso"))

    if usuario_id == session.get("user_id"):
        if senha:
            session["auth_version"] = get_usuario_auth_version(conn, usuario_id)
        session["user_type"] = user_type
        session["access_level"] = nivel_acesso
        session["perfil"] = access_level_label(nivel_acesso)
        if user_type != "admin":
            session.clear()
            flash("Seu perfil foi alterado. Faça login novamente para continuar.", "success")
            return redirect(url_for("login"))

    if reactivating:
        flash("Acesso reativado e vinculado ao registro existente.", "success")
        return redirect(url_for("admin_acesso"))
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
    # The backend is authoritative regardless of what the action bar offered.
    # Same owner, same ladder as the row descriptor: root protection and revoked
    # access are decided in app/access_default_password.py, and the refusal
    # carries that module's reason verbatim.
    eligibility = default_password_eligibility(conn, usuario_id)
    if not eligibility.allowed:
        flash(eligibility.reason, "error")
        return redirect(url_for("admin_acesso"))
    # The current configured default is applied deliberately, without comparing
    # the hash it replaces: this is an administrative credential reset, so the
    # re-salt, the auth_version bump and the token invalidation below are the
    # point even when the resulting plaintext is unchanged.  Valid from pending,
    # personal and default alike; re-applying is how a default account picks up
    # a since-edited profile value.
    defaults = _access_defaults_map(conn)
    nivel = canonicalize_access_level(usuario["nivel_acesso"])
    nova_senha = defaults.get(nivel, "admin123")
    set_usuario_password_hash(
        conn,
        usuario_id,
        hash_password(nova_senha),
        credential_state=CREDENTIAL_STATE_DEFAULT,
    )
    conn.commit()
    if usuario_id == session.get("user_id"):
        session["auth_version"] = get_usuario_auth_version(conn, usuario_id)
    flash(f"Senha padrão aplicada ao acesso de {usuario['nome']}.", "success")
    return redirect(url_for("admin_acesso"))


@admin_required
def admin_acesso_senha_por_email(usuario_id):
    conn = get_db_connection()
    usuario = conn.execute(
        """
        SELECT u.id,u.nome,u.email,c.estado
          FROM usuarios u
          JOIN usuario_credenciais c ON c.usuario_id=u.id
         WHERE u.id=?
        """,
        (usuario_id,),
    ).fetchone()
    if not usuario:
        flash("Usuário não encontrado.", "error")
        return redirect(url_for("admin_acesso"))

    # A revoked account has no login to restore by e-mail. Sending one would
    # hand back access that an administrator deliberately ended, so the
    # reactivation has to come first and explicitly.
    if not usuario_access_is_active(conn, usuario_id):
        flash(
            "Este acesso está revogado. Reative-o antes de enviar e-mail de senha.",
            "error",
        )
        return redirect(url_for("admin_acesso"))

    # First access is onboarding, and only a pending account is still being
    # onboarded.  An account holding a usable credential -- personal, or an
    # applied default -- is sent a reset link; both end in "personal".
    purpose = (
        PURPOSE_FIRST_ACCESS
        if usuario["estado"] == CREDENTIAL_STATE_PENDING
        else PURPOSE_PASSWORD_RESET
    )
    outcome = issue_and_send_password_email(
        conn,
        usuario_id=usuario_id,
        recipient=str(usuario["email"] or ""),
        user_name=str(usuario["nome"] or ""),
        purpose=purpose,
    )
    if outcome.status == "sent":
        flash("E-mail de acesso enviado com sucesso.", "success")
    elif outcome.status == "indeterminate":
        flash(outcome.detail, "warning")
    else:
        flash(outcome.detail or "Não foi possível enviar o e-mail de acesso.", "error")
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

    set_usuarios_password_hash(
        conn,
        usuario_ids,
        hash_password(nova_senha),
        credential_state=CREDENTIAL_STATE_PERSONAL,
    )
    conn.commit()
    if session.get("user_id") in usuario_ids:
        session["auth_version"] = get_usuario_auth_version(conn, session["user_id"])

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

    if not conn.execute("SELECT 1 FROM usuarios WHERE id = ?", (usuario_id,)).fetchone():
        flash("Usuário não encontrado.", "error")
        return redirect(url_for("admin_acesso"))

    # Neither removal nor revocation may reach the root administrator: both
    # destroy the only path back into a locked-out installation.
    if is_root_admin(conn, usuario_id):
        flash(
            "O administrador raiz não pode ser excluído nem revogado: é a única via de recuperação do sistema.",
            "error",
        )
        return redirect(url_for("admin_acesso"))

    # "Excluir acesso" means: remove the ability to log in. It is ONE operation
    # -- revocation -- not "delete if the row looks disposable, revoke
    # otherwise". A single model is what makes the outcome predictable:
    #
    #   * the person survives. A linked aluno keeps its matrícula, turma,
    #     matriz, horas, requisições and history, and stays linked, because the
    #     identity it points at is preserved rather than destroyed;
    #   * history stays truthful. An upload's uploader_user_id still resolves
    #     to the account that really performed it -- the custody triggers and
    #     the RESTRICT reference are never fought;
    #   * re-creating access later reuses this identity instead of minting a
    #     duplicate (see admin_acesso_salvar).
    #
    # Physical deletion is deliberately not part of these semantics.
    try:
        _revoke_usuario_access(conn, usuario_id)
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        debug_code = f"ACCESS_DELETE_{usuario_id}"
        logger.warning(
            "event=access_revoke_failed usuario_id=%s code=%s",
            int(usuario_id),
            debug_code,
        )
        flash(
            f"Não foi possível excluir o acesso porque há registros vinculados a ele. Código de suporte: {debug_code}",
            "error",
        )
        return redirect(url_for("admin_acesso"))
    if usuario_id == session.get("user_id"):
        session.clear()
    flash("Acesso revogado: o login foi encerrado e o histórico foi preservado.", "success")
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
            "/admin/acesso/<int:usuario_id>/senha-por-email",
            "admin_acesso_senha_por_email",
            admin_acesso_senha_por_email,
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
    "_reactivate_usuario_access",
    "_revoke_usuario_access",
    "_turma_label_by_id",
    "admin_acesso",
    "admin_acesso_deletar",
    "admin_acesso_definir_senha",
    "admin_acesso_resetar_senha",
    "admin_acesso_senha_por_email",
    "admin_acesso_salvar",
    "admin_acesso_salvar_senhas_default",
    "bp_admin_acesso",
]
