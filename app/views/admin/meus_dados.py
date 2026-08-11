# coding: utf-8
"""UT-14: dono canonico do cohort "Meus Dados".

1 simbolo relocado de main.py por MOVE-VERBATIM (1 rota: admin_meus_dados).
Nenhuma importacao de main; registra apenas rotas legadas via
LegacyRouteSpec.
"""

from __future__ import annotations

import sqlite3

from flask import (
    Blueprint,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from app.auth import admin_required
from app.db import get_db_connection
from app.db_maintenance import ensure_usuario_profile_schema
from app.security.passwords import hash_password
from app.uploads import save_upload
from app.views.admin import LegacyRouteSpec, configure_legacy_routes
from utils.messages import flash


@admin_required
def admin_meus_dados():
    conn = get_db_connection()
    ensure_usuario_profile_schema(conn)
    usuario_id = session["user_id"]
    profile = conn.execute(
        "SELECT nome, email, foto_perfil FROM usuarios WHERE id = ?",
        (usuario_id,),
    ).fetchone()

    if not profile:
        flash("Usuário não encontrado.", "error")
        return redirect(url_for("admin_dashboard"))

    if request.method == "POST":
        nome = request.form["nome"]
        email = request.form["email"]
        senha = request.form.get("senha")

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

            remove_foto = request.form.get("remove_foto") == "1"
            foto_file = request.files.get("foto_perfil")
            if remove_foto:
                conn.execute("UPDATE usuarios SET foto_perfil = NULL WHERE id = ?", (usuario_id,))
                session.pop("foto_perfil", None)
            elif foto_file and foto_file.filename:
                try:
                    foto_rel = save_upload(
                        foto_file,
                        {"png", "jpg", "jpeg"},
                        prefix="avatar",
                        subdir=f"avatars/usuario_{usuario_id}",
                    )
                    if foto_rel:
                        conn.execute(
                            "UPDATE usuarios SET foto_perfil = ? WHERE id = ?",
                            (foto_rel, usuario_id),
                        )
                        session["foto_perfil"] = foto_rel
                except ValueError:
                    flash("Foto inválida. Use PNG ou JPG.", "error")

            conn.commit()
            flash("Seus dados foram atualizados com sucesso.", "success")
            return redirect(url_for("admin_meus_dados"))
        except sqlite3.IntegrityError as exc:
            if "UNIQUE constraint failed: usuarios.email" in str(exc):
                flash("Erro: Já existe outro usuário com este e-mail.", "error")
            else:
                flash(f"Erro ao atualizar dados: {exc}", "error")
        except Exception as exc:
            flash(f"Erro inesperado ao atualizar dados: {exc}", "error")

    return render_template(
        "aluno_meus_dados.html",
        base_template="base.html",
        profile=profile,
        show_student_fields=False,
        cancel_url=url_for("admin_dashboard"),
        turmas=[],
    )


bp_admin_meus_dados = Blueprint(
    "admin_meus_dados_blueprint",
    __name__,
)

LEGACY_ROUTE_SPECS = configure_legacy_routes(
    bp_admin_meus_dados,
    (
        LegacyRouteSpec(
            "/admin/meus_dados",
            "admin_meus_dados",
            admin_meus_dados,
            ("GET", "POST"),
        ),
    ),
)
