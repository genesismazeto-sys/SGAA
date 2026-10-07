# coding: utf-8
"""UT-14: dono canonico do cohort "Meus Dados".

1 simbolo relocado de main.py por MOVE-VERBATIM (1 rota: admin_meus_dados).
Nenhuma importacao de main; registra apenas rotas legadas via
LegacyRouteSpec.
"""

from __future__ import annotations

from flask import (
    Blueprint,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from app.auth import admin_required
from app.db import (
    get_db_connection,
    integrity_constraint_name,
    is_integrity_error,
    is_unique_violation,
)
from app.db_images import USUARIOS_FOTO, delete_image, image_marker, store_image
from app.db_maintenance import ensure_usuario_profile_schema
from app.image_validation import (
    PROFILE_PHOTO_MAX_UPLOAD_BYTES,
    ImageRejected,
    ImageTooLarge,
    normalize_profile_photo,
    read_upload_limited,
)
from app.presentation import _format_bytes_label
from app.root_admin import RootAdminEmailLocked, is_root_admin
from app.security.passwords import hash_password
from app.user_accounts import (
    CREDENTIAL_STATE_PERSONAL,
    InvalidEmailError,
    get_usuario_auth_version,
    require_valid_email,
    set_usuario_email,
    set_usuario_password_hash,
)
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

    # Root identity is keyed to the root's address (app/root_admin.py), so this
    # screen shows it read-only and never writes it; it moves only through
    # migrate_root_admin_email.
    email_locked = is_root_admin(conn, usuario_id)

    if request.method == "POST":
        nome = request.form["nome"]
        email = request.form["email"]
        senha = request.form.get("senha")

        try:
            require_valid_email(email)
            if email_locked and email.strip().casefold() != str(profile["email"] or "").strip().casefold():
                raise RootAdminEmailLocked()
            hashed_password = hash_password(senha) if senha else None
            conn.execute("UPDATE usuarios SET nome = ? WHERE id = ?", (nome, usuario_id))
            if not email_locked:
                set_usuario_email(conn, usuario_id, email)
            if hashed_password:
                set_usuario_password_hash(
                    conn,
                    usuario_id,
                    hashed_password,
                    credential_state=CREDENTIAL_STATE_PERSONAL,
                )

            session["user_name"] = nome

            remove_foto = request.form.get("remove_foto") == "1"
            foto_file = request.files.get("foto_perfil")
            if remove_foto:
                delete_image(conn, USUARIOS_FOTO, usuario_id)
                session.pop("foto_perfil", None)
            elif foto_file and foto_file.filename:
                try:
                    foto = normalize_profile_photo(
                        read_upload_limited(foto_file, PROFILE_PHOTO_MAX_UPLOAD_BYTES)
                    )
                except ImageTooLarge:
                    flash(f"Arquivo muito grande. Tamanho máximo: {_format_bytes_label(PROFILE_PHOTO_MAX_UPLOAD_BYTES)}.", "error")
                except ImageRejected:
                    flash("Foto inválida. Use PNG ou JPG.", "error")
                else:
                    store_image(conn, USUARIOS_FOTO, usuario_id, foto)
                    session["foto_perfil"] = foto.version

            conn.commit()
            if senha:
                session["auth_version"] = get_usuario_auth_version(conn, usuario_id)
            flash("Seus dados foram atualizados com sucesso.", "success")
            return redirect(url_for("admin_meus_dados"))
        except InvalidEmailError as exc:
            flash(str(exc), "error")
        except RootAdminEmailLocked:
            flash("O e-mail do administrador raiz não pode ser alterado por esta tela.", "error")
        except Exception as exc:
            if is_integrity_error(exc):
                conn.rollback()
                if is_unique_violation(exc) and integrity_constraint_name(exc) == "usuarios.email":
                    flash("Erro: Já existe outro usuário com este e-mail.", "error")
                else:
                    flash(f"Erro ao atualizar dados: {exc}", "error")
            else:
                flash(f"Erro inesperado ao atualizar dados: {exc}", "error")

    return render_template(
        "aluno_meus_dados.html",
        base_template="base.html",
        profile=profile,
        foto_versao=image_marker(conn, USUARIOS_FOTO, usuario_id),
        show_student_fields=False,
        email_readonly=email_locked,
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
