from __future__ import annotations

import io
import mimetypes
import os

from flask import Blueprint, abort, current_app, jsonify, redirect, request, send_file, session, url_for

from app.comprovantes import (
    ComprovanteError,
    authorize_request_comprovante_actor,
    handle_storage_authorization_failure,
    resolve_google_storage,
)
from app.db import get_db_connection
from app.storage import arquivo_documents
from app.storage import request_documents as documents
from app.storage.contracts import StorageError
from app.storage.object_store import STORAGE_CONFIG_MISSING, CanonicalStoreError
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
    if row["storage_object_id"] is not None:
        # Canonical custody wins whenever a canonical reference exists: the
        # browser is sent to a 60-second signed private URL; no body here.
        try:
            url = documents.canonical_download_url(
                conn, row, download=(request.args.get("download") or "").strip() == "1"
            )
        except documents.RequestDocumentError as exc:
            if exc.status == 404:
                abort(404)
            return _secure_headers(current_app.response_class(exc.user_message, status=503))
        response = redirect(url, code=302)
        response.headers["Referrer-Policy"] = "no-referrer"
        return _secure_headers(response)
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


def _no_store_json(body: dict, status: int):
    response = jsonify(body)
    response.status_code = status
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def _document_error(exc: "documents.RequestDocumentError"):
    body = {"error": exc.code, "message": exc.user_message}
    if exc.state:
        body["state"] = exc.state
    if exc.intent_id:
        body["intent_id"] = exc.intent_id
    return _no_store_json(body, exc.status)


def _store_error(exc: CanonicalStoreError):
    code = "STORAGE_NOT_CONFIGURED" if exc.code == STORAGE_CONFIG_MISSING else "STORAGE_UNAVAILABLE"
    return _no_store_json({"error": code, "message": documents.STORAGE_UNAVAILABLE_MESSAGE}, 503)


def _upload_actor() -> int | None:
    if session.get("user_type") not in ("aluno", "admin") or not session.get("user_id"):
        return None
    return int(session["user_id"])


@bp_comprovantes.post("/storage/upload-intents")
def issue_upload_intent():
    """Issue (or replay) one request-document upload intent + signed TUS capability."""
    actor = _upload_actor()
    if actor is None:
        return _no_store_json(
            {"error": "AUTHENTICATION_REQUIRED", "message": documents.AUTHENTICATION_REQUIRED_MESSAGE}, 401
        )
    conn = get_db_connection()
    payload = request.get_json(silent=True)
    try:
        # STORAGE S3-B: the same route serves admin ARQUIVOS, dispatched on purpose.
        if isinstance(payload, dict) and payload.get("purpose") == arquivo_documents.PURPOSE:
            capability = arquivo_documents.issue_arquivo_document(
                conn, session, actor_user_id=actor, payload=payload
            )
        else:
            capability = documents.issue_request_document(
                conn, session, actor_user_id=actor, payload=payload
            )
    except documents.RequestDocumentError as exc:
        return _document_error(exc)
    except CanonicalStoreError as exc:
        return _store_error(exc)
    return _no_store_json(capability.as_json(), 201)


@bp_comprovantes.post("/storage/upload-intents/<intent_id>/finalize")
def finalize_upload_intent(intent_id: str):
    """Verify the uploaded object server-side; only the path id is an input."""
    actor = _upload_actor()
    if actor is None:
        return _no_store_json(
            {"error": "AUTHENTICATION_REQUIRED", "message": documents.AUTHENTICATION_REQUIRED_MESSAGE}, 401
        )
    conn = get_db_connection()
    try:
        # An actor's own ARQUIVOS intent finalizes as ARQUIVOS; anything else
        # (unknown or foreign) keeps the S3-A indistinguishable not-found.
        if arquivo_documents.owns_arquivo_intent(conn, intent_id, actor):
            state = arquivo_documents.finalize_arquivo_document(conn, actor_user_id=actor, intent_id=intent_id)
        else:
            state = documents.finalize_request_document(conn, actor_user_id=actor, intent_id=intent_id)
    except documents.RequestDocumentError as exc:
        return _document_error(exc)
    except CanonicalStoreError as exc:
        return _store_error(exc)
    return _no_store_json({"intent_id": intent_id, "state": state}, 200)


__all__ = [
    "INLINE_MIME_TYPES",
    "bp_comprovantes",
    "finalize_upload_intent",
    "issue_upload_intent",
    "open_comprovante",
]
