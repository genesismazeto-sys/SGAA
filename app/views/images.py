"""Delivery of database-backed images (prod-1/v13).

Two GET endpoints; neither takes a path, and neither lets one owner reach
another owner's image by changing a parameter:

``/perfil/foto``
    The signed-in user's own profile photo (administrator -> ``usuarios_foto``,
    student -> ``alunos_foto``).  There is no id in the URL; the owner is the
    session.  An administrator additionally needs ``arquivos`` view, the same
    gate the shared upload endpoint applied to avatars before v13.

``/reportes/<id>/captura``
    A report screenshot.  A student reaches only screenshots of their own
    reports (anything else is 404, so ids cannot be probed); an administrator
    needs ``reportes`` view AND ``arquivos`` view -- the former gate
    (``arquivos`` view on the upload endpoint) kept and narrowed to administrators
    who may see reports at all.

Responses carry the verified MIME type, Content-Length, an ETag equal to the
content SHA-256, ``X-Content-Type-Options: nosniff`` and
``Cache-Control: private, no-cache``; a matching ``If-None-Match`` gets 304.
No filename is sent.
"""

from __future__ import annotations

from flask import Blueprint, Response, abort, current_app, redirect, request, session, url_for

from app.admin_access import _admin_can, _get_current_admin_access_context
from app.db import get_db_connection
from app.db_images import REPORTES_CAPTURA, legacy_marker, load_image, profile_owner


bp_images = Blueprint("images", __name__)


def reporte_captura_url(reporte_id, captura_sha256, legacy_reference) -> str | None:
    """Screenshot URL for a report listing row, or None when it has none.

    ``captura_sha256`` comes from a ``LEFT JOIN reportes_captura`` (never the
    content); the legacy path only signals that a pre-v13 file may exist.
    Neither the path nor any filename reaches the page.
    """
    if captura_sha256:
        version = str(captura_sha256)[:16]
    elif str(legacy_reference or "").strip():
        version = legacy_marker(str(legacy_reference).strip())
    else:
        return None
    return url_for("images.reporte_captura", reporte_id=int(reporte_id), v=version)


def _image_response(conn, spec, owner_id):
    image = load_image(
        conn,
        spec,
        owner_id,
        upload_root=current_app.config.get("UPLOAD_FOLDER"),
        documents_root=current_app.config.get("DOCUMENTOS_ALUNOS_FOLDER"),
    )
    if image is None:
        abort(404)
    response = Response(image.content, mimetype=image.mime_type)
    response.set_etag(image.sha256)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "private, no-cache"
    response.headers["Content-Disposition"] = "inline"
    response.vary.add("Cookie")
    return response.make_conditional(request)


@bp_images.get("/perfil/foto")
def profile_photo():
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))
    user_type = session.get("user_type")
    if user_type == "admin":
        context = _get_current_admin_access_context(force_reload=True)
        if not _admin_can("arquivos", "view", context):
            abort(403)
    elif user_type != "aluno":
        abort(403)
    conn = get_db_connection()
    owner = profile_owner(conn, user_type, user_id)
    if owner is None:
        abort(404)
    return _image_response(conn, *owner)


@bp_images.get("/reportes/<int:reporte_id>/captura")
def reporte_captura(reporte_id: int):
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))
    user_type = session.get("user_type")
    conn = get_db_connection()
    if user_type == "admin":
        context = _get_current_admin_access_context(force_reload=True)
        if not (_admin_can("reportes", "view", context) and _admin_can("arquivos", "view", context)):
            abort(403)
        row = conn.execute("SELECT id FROM reportes WHERE id = ?", (int(reporte_id),)).fetchone()
    elif user_type == "aluno":
        row = conn.execute(
            "SELECT r.id FROM reportes r JOIN alunos a ON a.id = r.aluno_id"
            " WHERE r.id = ? AND a.usuario_id = ?",
            (int(reporte_id), int(user_id)),
        ).fetchone()
    else:
        abort(403)
    if row is None:
        abort(404)
    return _image_response(conn, REPORTES_CAPTURA, int(reporte_id))


__all__ = ["bp_images", "profile_photo", "reporte_captura", "reporte_captura_url"]
