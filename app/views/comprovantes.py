from __future__ import annotations

import io
import mimetypes
import os

from flask import Blueprint, abort, current_app, redirect, send_file, session, url_for

from app.comprovantes import (
    ComprovanteError,
    authorize_request_comprovante_actor,
    handle_storage_authorization_failure,
    resolve_google_storage,
)
from app.db import get_db_connection
from app.storage.contracts import StorageError
from app.student_documents import resolve_student_document_path


bp_comprovantes = Blueprint("comprovantes", __name__)
INLINE_MIME_TYPES = frozenset({"application/pdf", "image/png", "image/jpeg"})


def _secure_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "private, no-store"
    return response


@bp_comprovantes.get("/comprovantes/<int:attachment_id>/open")
def open_comprovante(attachment_id: int):
    if not session.get("user_id"):
        return redirect(url_for("login"))
    conn = get_db_connection()
    row = conn.execute(
        """SELECT ra.*
             FROM requisicao_arquivos ra
             JOIN requisicoes r ON r.id=ra.requisicao_id
            WHERE ra.id=?""",
        (int(attachment_id),),
    ).fetchone()
    if not row:
        abort(404)
    try:
        authorize_request_comprovante_actor(
            conn,
            request_id=int(row["requisicao_id"]),
            actor_user_id=int(session["user_id"]),
            admin_scope="view",
        )
    except ComprovanteError:
        abort(403)
    if row["storage_status"] not in {"active", "legacy_active"}:
        abort(404)
    stored_name = os.path.basename(str(row["filename"] or "comprovante"))
    if row["provider"] == "google":
        try:
            storage = resolve_google_storage(conn)
            content = storage.download(str(row["remote_file_id"]))
        except StorageError as exc:
            handle_storage_authorization_failure(conn, exc)
            return "Não foi possível abrir o comprovante com segurança.", 503
        mime_type = str(row["mime_type"] or "application/octet-stream").lower()
        return _secure_headers(
            send_file(
                io.BytesIO(content),
                mimetype=mime_type,
                as_attachment=mime_type not in INLINE_MIME_TYPES,
                download_name=stored_name,
                conditional=False,
                max_age=0,
            )
        )
    if row["provider"] != "local_legacy":
        abort(404)
    roots = (
        current_app.config.get("DOCUMENTOS_ALUNOS_FOLDER"),
        current_app.config.get("UPLOAD_FOLDER"),
    )
    for root in roots:
        if not root:
            continue
        try:
            path = resolve_student_document_path(str(root), str(row["filename"]))
        except ValueError:
            abort(403)
        if os.path.isfile(path):
            mime_type = str(
                row["mime_type"]
                or mimetypes.guess_type(stored_name)[0]
                or "application/octet-stream"
            ).lower()
            return _secure_headers(
                send_file(
                    path,
                    mimetype=mime_type,
                    as_attachment=mime_type not in INLINE_MIME_TYPES,
                    download_name=stored_name,
                    conditional=False,
                    max_age=0,
                )
            )
    abort(404)


__all__ = ["INLINE_MIME_TYPES", "bp_comprovantes", "open_comprovante"]
