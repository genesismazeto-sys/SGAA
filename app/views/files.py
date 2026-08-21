"""Canonical owner of the legacy public file-serving endpoint ``uploaded_file``.

UT-17: MOVE, DO NOT CHANGE — body AST-identical to the removed
``main.py`` route (fingerprints pinned by ``tests/test_ut17_infra_routes.py``).
The lexical name ``app`` is bound to the Flask ``current_app`` proxy so the
moved body keeps its original ``app.config`` / ``app.root_path`` spelling
without importing ``main``.
"""

import os

from flask import (
    abort,
    current_app as app,
    redirect,
    send_from_directory,
    session,
    url_for,
)

from app.admin_access import _admin_can, _get_current_admin_access_context
from app.db import get_db_connection
from app.student_documents import (
    resolve_student_document_path,
    sanitize_student_document_relpath,
)


def uploaded_file(filename):
    """Serve arquivos do diretório de uploads com controle de acesso.

    Regras:
      - Sem sessão ativa -> redireciona para login.
            - Admin -> requer escopo `arquivos:view`.
      - Aluno -> só pode ler:
          * próprios uploads em `aluno_<aluno_id>/...`
          * próprio avatar em `avatars/usuario_<user_id>/...`
          * arquivos publicados em admin_arquivos com visivel = 1
          * arquivos referenciados em suas próprias requisições
      - Caso contrário -> 403.
    """
    # Normalização + path-traversal guard
    try:
        safe_rel = sanitize_student_document_relpath(filename)
    except ValueError:
        abort(403)

    user_id = session.get("user_id")
    user_type = session.get("user_type")
    if not user_id:
        # Sem sessão, redireciona em vez de 401 para fluxo natural via browser
        return redirect(url_for("login"))

    rel_norm = safe_rel.replace("\\", "/")
    is_student_document_relpath = rel_norm.startswith("aluno_")
    allowed = False
    if user_type == "admin":
        auth_context = _get_current_admin_access_context(force_reload=True)
        allowed = _admin_can("arquivos", "view", auth_context)
    elif user_type == "aluno":
        try:
            conn = get_db_connection()
            arow = conn.execute(
                "SELECT id FROM alunos WHERE usuario_id = ?", (user_id,)
            ).fetchone()
            aluno_id = arow["id"] if arow else None
            if aluno_id and (
                rel_norm.startswith(f"aluno_{aluno_id}/")
                or rel_norm.startswith(f"aluno_{aluno_id} - ")
            ):
                allowed = True
            elif rel_norm.startswith(f"avatars/usuario_{user_id}/"):
                allowed = True
            else:
                # Arquivos publicados pelo admin (visíveis ao aluno)
                row = conn.execute(
                    "SELECT 1 FROM admin_arquivos WHERE filename = ? AND visivel = 1",
                    (rel_norm,),
                ).fetchone()
                if row:
                    allowed = True
                elif aluno_id:
                    # Anexos vinculados a requisições do próprio aluno
                    row = conn.execute(
                        """
                        SELECT 1 FROM requisicao_arquivos ra
                          JOIN requisicoes r ON r.id = ra.requisicao_id
                         WHERE ra.filename = ? AND r.aluno_id = ?
                         LIMIT 1
                        """,
                        (rel_norm, aluno_id),
                    ).fetchone()
                    if row:
                        allowed = True
        except Exception:
            allowed = False

    if not allowed:
        abort(403)

    candidate_paths = []
    if is_student_document_relpath:
        docs_root = app.config.get("DOCUMENTOS_ALUNOS_FOLDER")
        if docs_root:
            try:
                candidate_paths.append(resolve_student_document_path(docs_root, rel_norm))
            except ValueError:
                abort(403)
    try:
        candidate_paths.append(resolve_student_document_path(app.config["UPLOAD_FOLDER"], rel_norm))
    except ValueError:
        abort(403)

    target_path = next((path for path in candidate_paths if os.path.isfile(path)), None)
    if not target_path:
        abort(404)

    rel_dir = os.path.dirname(target_path)
    rel_name = os.path.basename(target_path)
    resp = send_from_directory(
        rel_dir,
        rel_name,
        as_attachment=False,
    )
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    # Não cachear arquivos sensíveis em proxies/dispositivos compartilhados
    resp.headers["Cache-Control"] = "private, no-store"
    return resp
