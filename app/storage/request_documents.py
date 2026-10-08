"""Canonical request documents (STORAGE S3-A): direct upload, verify, attach.

DRIVE_AVAILABILITY_MUST_NOT_BLOCK_REQUEST_SUBMISSION -- for NEW request
documents.  Nothing in this module reaches Google: the canonical store is
Supabase Storage (injected at ``app.extensions["canonical_object_store"]``,
otherwise built lazily from the environment) and the Drive mirror stays
``pending`` for S4.

PROTOCOL
    1. A request form renders a server-issued ``comprovantes_submission_id``
       (128-bit, kept in a small bounded set in the session, 2-hour window).
    2. ``issue_request_document``: per deliberately selected file the browser
       declares ``upload_slot_id`` (opaque 128-bit), filename, MIME, size and
       SHA-256.  The server authorizes actor / target / status, pre-checks the
       declaration and the submission's declared total, issues (or replays)
       the intent for ``<submission_id>:<upload_slot_id>`` and -- outside the
       transaction -- mints a signed upload capability for the SERVER-chosen
       bucket / key.  The browser uploads straight to Supabase (signed TUS).
    3. ``finalize_request_document``: outside any write transaction the
       server stats and reads the stored object (bounded at 16 MiB), hashes
       it, sniffs and structurally validates it, and compares it with the
       declaration and the Storage metadata; then, in a short transaction, the
       intent is marked verified or rejected.  Browser-reported metadata is
       never an input.
    4. ``attach_request_documents``: inside the caller's business write
       transaction, every submitted intent is locked and re-checked (actor,
       purpose, submission, target, state, window), the VERIFIED total of the
       submission is bounded, the business authorization is re-run, and each
       intent is consumed into a ``storage_objects`` row and a canonical
       ``requisicao_arquivos`` row (``provider='supabase'``).  No network call
       happens inside the transaction.

Capability values (signed tokens / URLs) are returned once and never stored
or logged.  Errors carry a fixed ``[A-Z0-9_]`` code, a user message and an
HTTP status -- never provider text.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from types import SimpleNamespace

from flask import current_app

from app.comprovante_file_validation import MIME_BY_EXTENSION, detect_supported_mime
from app.comprovante_hierarchy import stored_filename
from app.comprovantes import ComprovanteError, _authorize_comprovante_upload
from app.db import write_transaction
from app.prod1_storage_ddl import BUSINESS_DOCUMENT_MAX_BYTES, BUSINESS_DOCUMENT_MIME_TYPES
from app.storage import custody_common
from app.storage import upload_intents as intents
from app.storage.custody_common import CustodyError
from app.storage.object_store import (
    STORAGE_ALREADY_EXISTS,
    STORAGE_OBJECT_MISSING,
    STORAGE_OBJECT_TOO_LARGE,
    CanonicalStoreError,
)
from app.storage.supabase_store import (
    TUS_CHUNK_BYTES,
    SupabaseObjectStore,
    configured_bucket,
    configured_project_url,
    configured_publishable_key,
    resumable_upload_endpoint,
)

CANONICAL_STORE_EXTENSION = "canonical_object_store"
PURPOSE = "comprovante"
SUBMISSION_FIELD = "comprovantes_submission_id"
INTENT_IDS_FIELD = "comprovantes_intent_ids"
LEGACY_FILE_FIELD = "comprovantes_files"
INTENT_TTL_SECONDS = 2 * 60 * 60
SUBMISSION_TTL_SECONDS = INTENT_TTL_SECONDS
SUBMISSION_SESSION_KEY = "comprovantes_submissions"
MAX_LIVE_SUBMISSIONS = 12
MAX_INTENTS_PER_SUBMISSION = 20
SIGNED_DOWNLOAD_TTL_SECONDS = 60

STORAGE_UNAVAILABLE_MESSAGE = "O armazenamento está indisponível. Tente novamente."
AUTHENTICATION_REQUIRED_MESSAGE = "Faça login novamente."

_HEX128 = re.compile(r"^[0-9a-f]{32}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class RequestDocumentError(RuntimeError):
    """A refused request-document operation: fixed code, user message, HTTP status."""

    def __init__(
        self, code: str, user_message: str, status: int = 400, *,
        state: str | None = None, intent_id: str | None = None,
    ):
        super().__init__(code)
        self.code = code
        self.user_message = user_message
        self.status = status
        self.state = state
        self.intent_id = intent_id


def _now() -> str:
    # The adjudicated clock seam: always through the module attribute.
    return custody_common.utc_now_text()


def canonical_store():
    """The injected canonical store, else a lazily configured Supabase store."""
    store = current_app.extensions.get(CANONICAL_STORE_EXTENSION)
    if store is not None:
        return store
    return SupabaseObjectStore.from_environment()


# ---------------------------------------------------------------------------
# submissions (session-bound, bounded, 2-hour window)
# ---------------------------------------------------------------------------


def _live_submissions(session_obj, now: str) -> dict:
    raw = session_obj.get(SUBMISSION_SESSION_KEY)
    live = {}
    if isinstance(raw, dict):
        for sid, entry in raw.items():
            if not (isinstance(sid, str) and _HEX128.fullmatch(sid)):
                continue
            if not (isinstance(entry, (list, tuple)) and len(entry) == 2):
                continue
            issued_at, user_id = entry
            try:
                expired = custody_common.add_seconds(str(issued_at), SUBMISSION_TTL_SECONDS) <= now
            except ValueError:
                continue
            if not expired:
                live[sid] = [str(issued_at), int(user_id)]
    return live


def issue_submission(session_obj, user_id: int) -> str:
    """A fresh 128-bit submission id for one rendered request form."""
    now = _now()
    live = _live_submissions(session_obj, now)
    while len(live) >= MAX_LIVE_SUBMISSIONS:
        live.pop(min(live, key=lambda sid: live[sid][0]))
    submission_id = secrets.token_hex(16)
    live[submission_id] = [now, int(user_id)]
    session_obj[SUBMISSION_SESSION_KEY] = live
    session_obj.modified = True
    return submission_id


def submission_is_live(session_obj, submission_id, user_id: int) -> bool:
    if not (isinstance(submission_id, str) and _HEX128.fullmatch(submission_id)):
        return False
    live = _live_submissions(session_obj, _now())
    entry = live.get(submission_id)
    return entry is not None and entry[1] == int(user_id)


def _require_submission(session_obj, submission_id, user_id: int) -> str:
    if not submission_is_live(session_obj, submission_id, user_id):
        raise RequestDocumentError(
            "SUBMISSION_INVALID",
            "O formulário expirou. Recarregue a página e selecione os comprovantes novamente.",
            403,
        )
    return submission_id


# ---------------------------------------------------------------------------
# actor / target authorization
# ---------------------------------------------------------------------------


def _actor_type(conn, actor_user_id: int) -> str:
    row = conn.execute("SELECT tipo FROM usuarios WHERE id=?", (int(actor_user_id),)).fetchone()
    return str(row["tipo"] if row else "").strip().lower()


def _authorize_target(conn, *, actor_user_id: int, requisicao_id: int | None) -> None:
    """Who may attach to which target -- re-run at issue, finalize and attach."""
    if requisicao_id is not None:
        exists = conn.execute("SELECT 1 FROM requisicoes WHERE id=?", (int(requisicao_id),)).fetchone()
        if not exists:
            raise RequestDocumentError("REQUEST_NOT_FOUND", "Requisição não encontrada.", 404)
        try:
            _authorize_comprovante_upload(conn, int(requisicao_id), int(actor_user_id))
        except ComprovanteError as exc:
            raise RequestDocumentError(exc.code, exc.user_message, 403) from None
        return
    actor_type = _actor_type(conn, actor_user_id)
    if actor_type == "aluno":
        if conn.execute("SELECT 1 FROM alunos WHERE usuario_id=?", (int(actor_user_id),)).fetchone():
            return
    elif actor_type == "admin":
        from app.admin_access import _admin_can, _load_admin_access_context

        if _admin_can("requisicoes", "edit", _load_admin_access_context(conn, int(actor_user_id))):
            return
    raise RequestDocumentError("ACCESS_DENIED", "Acesso negado.", 403)


# ---------------------------------------------------------------------------
# intent reads
# ---------------------------------------------------------------------------


def _intent_row(conn, intent_id, *, lock: bool = False):
    if not (isinstance(intent_id, str) and _HEX128.fullmatch(intent_id)):
        return None
    return intents._load(conn, intent_id, lock=lock)


def _owned_intent(conn, intent_id, actor_user_id: int, *, lock: bool = False):
    intent = _intent_row(conn, intent_id, lock=lock)
    if intent is None or intent.actor_user_id != int(actor_user_id) or intent.purpose != PURPOSE:
        raise RequestDocumentError("INTENT_NOT_FOUND", "Envio não encontrado.", 404)
    return intent


# ---------------------------------------------------------------------------
# 2. issue
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UploadCapability:
    intent_id: str
    tus_endpoint: str
    upload_token: str
    apikey: str  # the browser-safe sb_publishable_ key, never a secret
    bucket: str
    object_name: str
    expires_at: str

    def as_json(self) -> dict:
        return {
            "intent_id": self.intent_id,
            "tus_endpoint": self.tus_endpoint,
            "upload_token": self.upload_token,
            "apikey": self.apikey,
            "bucket": self.bucket,
            "object_name": self.object_name,
            "chunk_size": TUS_CHUNK_BYTES,
            "expires_at": self.expires_at,
        }

    def __repr__(self) -> str:  # the token never reaches a repr / log
        return f"UploadCapability(intent_id={self.intent_id!r})"


def _original_basename(value) -> str:
    return str(value or "").replace("\\", "/").rsplit("/", 1)[-1].strip()[:255]


def _declared_int(value):
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def issue_request_document(conn, session_obj, *, actor_user_id: int, payload) -> UploadCapability:
    if not isinstance(payload, dict):
        raise RequestDocumentError("INVALID_REQUEST", "Pedido inválido.")
    if payload.get("purpose") != PURPOSE:
        raise RequestDocumentError("PURPOSE_NOT_SUPPORTED", "Tipo de envio não suportado.")
    submission_id = _require_submission(session_obj, payload.get("submission_id"), actor_user_id)
    slot = payload.get("upload_slot_id")
    if not (isinstance(slot, str) and _HEX128.fullmatch(slot)):
        raise RequestDocumentError("INVALID_UPLOAD_SLOT", "Identificador de envio inválido.")
    raw_target = payload.get("requisicao_id")
    requisicao_id = None
    if raw_target not in (None, ""):
        requisicao_id = _declared_int(raw_target)
        if requisicao_id is None or requisicao_id <= 0:
            raise RequestDocumentError("INVALID_TARGET", "Requisição inválida.")
    _authorize_target(conn, actor_user_id=actor_user_id, requisicao_id=requisicao_id)

    original = _original_basename(payload.get("filename"))
    extension = original.rsplit(".", 1)[-1].lower() if "." in original else ""
    expected_mime = MIME_BY_EXTENSION.get(extension)
    declared_mime = payload.get("mime_type")
    if not expected_mime or declared_mime not in BUSINESS_DOCUMENT_MIME_TYPES:
        raise RequestDocumentError(
            "UNSUPPORTED_FILE_TYPE", f"{original or 'arquivo'}: envie somente arquivos PDF, PNG ou JPEG."
        )
    if declared_mime != expected_mime:
        raise RequestDocumentError("MIME_MISMATCH", f"A extensão de {original} não corresponde ao tipo do arquivo.")
    size = _declared_int(payload.get("size_bytes"))
    if size is None or size <= 0:
        raise RequestDocumentError("MALFORMED_FILE", f"{original} está vazio ou malformado.")
    if size > BUSINESS_DOCUMENT_MAX_BYTES:
        raise RequestDocumentError("FILE_TOO_LARGE", f"{original} excede o limite de 16 MiB.", 413)
    declared_sha = payload.get("sha256")
    if not (isinstance(declared_sha, str) and _SHA256.fullmatch(declared_sha)):
        raise RequestDocumentError("INVALID_DECLARATION", "Declaração do arquivo inválida.")

    operation_id = f"{submission_id}:{slot}"
    now = _now()
    others = conn.execute(
        "SELECT count(*), COALESCE(sum(declared_size_bytes),0) FROM storage_upload_intents"
        " WHERE actor_user_id=? AND purpose=? AND operation_id LIKE ? AND operation_id<>?"
        " AND state IN ('issued','verified') AND expires_at>?",
        (int(actor_user_id), PURPOSE, f"{submission_id}:%", operation_id, now),
    ).fetchone()
    if int(others[0]) >= MAX_INTENTS_PER_SUBMISSION:
        raise RequestDocumentError("TOO_MANY_FILES", "Muitos comprovantes neste envio.")
    if int(others[1]) + size > BUSINESS_DOCUMENT_MAX_BYTES:
        raise RequestDocumentError(
            "SUBMISSION_TOO_LARGE", "O total dos comprovantes excede o limite de 16 MiB.", 413
        )
    bucket = configured_bucket()
    endpoint = resumable_upload_endpoint(configured_project_url())
    apikey = configured_publishable_key()
    try:
        with write_transaction(conn):
            intent = intents.issue_intent(
                conn, actor_user_id=int(actor_user_id), purpose=PURPOSE, operation_id=operation_id,
                bucket=bucket, declared_mime_type=declared_mime, declared_size_bytes=size,
                declared_sha256=declared_sha, now=now, original_filename=original,
                requisicao_id=requisicao_id, ttl_seconds=INTENT_TTL_SECONDS,
            )
    except CustodyError as exc:
        if exc.code == intents.INTENT_OPERATION_CONFLICT:
            raise RequestDocumentError(
                "INTENT_OPERATION_CONFLICT", "Este envio já pertence a outro arquivo.", 409
            ) from None
        raise RequestDocumentError(exc.code, "Envio recusado.", 409) from None
    if intent.state != "issued":
        raise RequestDocumentError(
            "UPLOAD_ALREADY_FINALIZED", "Este arquivo já foi enviado.", 409, state=intent.state
        )
    # Outside the transaction: the capability is minted, never stored.
    try:
        signed = canonical_store().create_signed_upload(intent.storage_bucket, intent.storage_key)
    except CanonicalStoreError as exc:
        if exc.code == STORAGE_ALREADY_EXISTS:  # uploaded already: the browser only finalizes
            raise RequestDocumentError(
                "UPLOAD_ALREADY_RECEIVED", "O arquivo já foi recebido; conclua o envio.", 409,
                state="issued", intent_id=intent.id,
            ) from None
        raise
    return UploadCapability(
        intent_id=intent.id, tus_endpoint=endpoint, upload_token=signed.token, apikey=apikey,
        bucket=intent.storage_bucket, object_name=intent.storage_key, expires_at=intent.expires_at,
    )


# ---------------------------------------------------------------------------
# 3. finalize (bounded server-side verification)
# ---------------------------------------------------------------------------


def _verify_stored_object(store, intent) -> str | None:
    """None when the stored object matches the declaration; else a rejection code.

    Raises ``CanonicalStoreError`` for a missing object / provider outage (the
    intent stays ``issued`` and the browser may retry).
    """
    stat = store.stat(intent.storage_bucket, intent.storage_key)
    if stat.size_bytes > BUSINESS_DOCUMENT_MAX_BYTES:
        return "FILE_TOO_LARGE"
    try:
        content = store.read(intent.storage_bucket, intent.storage_key, max_bytes=BUSINESS_DOCUMENT_MAX_BYTES)
    except CanonicalStoreError as exc:
        if exc.code == STORAGE_OBJECT_TOO_LARGE:
            return "FILE_TOO_LARGE"
        raise
    if not content:
        return "MALFORMED_FILE"
    if len(content) != intent.declared_size_bytes or hashlib.sha256(content).hexdigest() != intent.declared_sha256:
        return "STORAGE_INTEGRITY_MISMATCH"
    sniffed = detect_supported_mime(content)
    if sniffed is None:
        return "MALFORMED_FILE"
    if sniffed != intent.declared_mime_type:
        return "MIME_MISMATCH"
    if stat.mime_type != intent.declared_mime_type:
        return "CONTENT_TYPE_MISMATCH"
    return None


_REJECTION_MESSAGES = {
    "FILE_TOO_LARGE": "O arquivo excede o limite de 16 MiB.",
    "MALFORMED_FILE": "O arquivo está vazio, protegido ou malformado.",
    "STORAGE_INTEGRITY_MISMATCH": "O arquivo recebido não corresponde ao arquivo selecionado.",
    "MIME_MISMATCH": "O conteúdo do arquivo não corresponde ao tipo declarado.",
    "CONTENT_TYPE_MISMATCH": "O tipo do arquivo armazenado não corresponde ao declarado.",
}


def _state_refusal(intent, now: str) -> RequestDocumentError | None:
    if intent.state in ("issued", "verified") and intent.expires_at <= now:
        return RequestDocumentError("INTENT_EXPIRED", "O envio expirou. Selecione o arquivo novamente.", 410,
                                    state=intent.state)
    if intent.state not in ("issued", "verified"):
        return RequestDocumentError("INTENT_STATE_INVALID", "Este envio não pode mais ser concluído.", 409,
                                    state=intent.state)
    return None


def finalize_request_document(conn, *, actor_user_id: int, intent_id) -> str:
    """Verify one uploaded object; returns ``'verified'`` (idempotent on replay)."""
    intent = _owned_intent(conn, intent_id, actor_user_id)
    refusal = _state_refusal(intent, _now())
    if refusal is not None:
        raise refusal
    if intent.state == "verified":
        return "verified"
    _authorize_target(conn, actor_user_id=actor_user_id, requisicao_id=intent.requisicao_id)

    store = canonical_store()
    try:
        rejection = _verify_stored_object(store, intent)
    except CanonicalStoreError as exc:
        if exc.code == STORAGE_OBJECT_MISSING:
            raise RequestDocumentError(
                "UPLOAD_NOT_FOUND", "O arquivo ainda não foi recebido. Tente novamente.", 409, state="issued"
            ) from None
        raise RequestDocumentError(
            "STORAGE_UNAVAILABLE", STORAGE_UNAVAILABLE_MESSAGE, 503, state="issued"
        ) from None

    now = _now()
    try:
        with write_transaction(conn):
            current = _owned_intent(conn, intent_id, actor_user_id, lock=True)
            if current.state == "verified" and current.expires_at > now:
                return "verified"
            refusal = _state_refusal(current, now)
            if refusal is not None:
                raise refusal
            if rejection is None:
                result = intents.mark_verified(
                    conn, intent_id=current.id, actor_user_id=int(actor_user_id),
                    observed_size_bytes=current.declared_size_bytes,
                    observed_sha256=current.declared_sha256, now=now,
                )
                if result.state != "verified":  # pragma: no cover - the check above proved equality
                    rejection = "STORAGE_INTEGRITY_MISMATCH"
            else:
                intents.reject_intent(conn, intent_id=current.id, rejection_code=rejection, now=now)
    except CustodyError:
        current = _owned_intent(conn, intent_id, actor_user_id)
        if current.state == "verified" and current.expires_at > _now():
            return "verified"  # a parallel finalizer won the same transition
        raise _state_refusal(current, _now()) or RequestDocumentError(
            "INTENT_STATE_INVALID", "Este envio não pode mais ser concluído.", 409, state=current.state
        ) from None
    if rejection is not None:
        raise RequestDocumentError(rejection, _REJECTION_MESSAGES[rejection], 422, state="rejected")
    return "verified"


# ---------------------------------------------------------------------------
# 4. attach (inside the caller's business write transaction)
# ---------------------------------------------------------------------------


def submitted_intent_ids(form) -> list[str]:
    ids: list[str] = []
    for raw in form.getlist(INTENT_IDS_FIELD):
        value = str(raw or "").strip()
        if value and value not in ids:
            ids.append(value)
    return ids


def has_file_parts(files) -> bool:
    """True when the request carries any non-empty file part (bytes through the app)."""
    for name in files:
        for item in files.getlist(name):
            if item is not None and (getattr(item, "filename", "") or "").strip():
                return True
    return False


def _binding_refused() -> RequestDocumentError:
    return RequestDocumentError(
        "DOCUMENT_BINDING_REFUSED",
        "Os comprovantes enviados não pertencem a esta requisição. Selecione-os novamente.",
        409,
    )


def attach_request_documents(
    conn, *, actor_user_id: int, request_id: int, submission_id: str | None, intent_ids, create: bool
) -> list[int]:
    """Consume verified intents into canonical attachments; the CALLER owns the transaction."""
    custody_common.require_write_transaction(conn)
    ids = list(intent_ids or [])
    if not ids:
        return []
    if not (isinstance(submission_id, str) and _HEX128.fullmatch(submission_id)):
        raise _binding_refused()
    if len(ids) > MAX_INTENTS_PER_SUBMISSION:
        raise RequestDocumentError("TOO_MANY_FILES", "Muitos comprovantes neste envio.")
    now = _now()
    locked = []
    for intent_id in ids:
        intent = _intent_row(conn, intent_id, lock=True)
        if (
            intent is None
            or intent.actor_user_id != int(actor_user_id)
            or intent.purpose != PURPOSE
            or not intent.operation_id.startswith(f"{submission_id}:")
            or intent.state != "verified"
            or intent.expires_at <= now
            or (intent.requisicao_id is not None if create else intent.requisicao_id != int(request_id))
        ):
            raise _binding_refused()
        locked.append(intent)
    if sum(intent.declared_size_bytes for intent in locked) > BUSINESS_DOCUMENT_MAX_BYTES:
        raise RequestDocumentError(
            "SUBMISSION_TOO_LARGE", "O total dos comprovantes excede o limite de 16 MiB.", 413
        )
    try:
        _authorize_comprovante_upload(conn, int(request_id), int(actor_user_id))
    except ComprovanteError as exc:
        raise RequestDocumentError(exc.code, exc.user_message, 403) from None
    activity = conn.execute(
        """SELECT base.nome_conceito, version.numero_versao
             FROM requisicoes r
             JOIN atividade_versao version ON version.id=r.atividade_versao_id
             JOIN atividade_base base ON base.id=version.atividade_base_id
            WHERE r.id=?""",
        (int(request_id),),
    ).fetchone()
    uploaded_at = f"{now[:10]}T{now[11:]}Z"
    attached = []
    for intent in locked:
        _consumed, object_id = intents.consume_intent(
            conn, intent_id=intent.id, actor_user_id=int(actor_user_id), purpose=PURPOSE,
            operation_id=intent.operation_id, now=now,
        )
        original = intent.original_filename or "comprovante"
        item = SimpleNamespace(
            uploaded_at=uploaded_at, operation_key=intent.operation_id,
            extension=original.rsplit(".", 1)[-1].lower() if "." in original else "pdf",
        )
        name = stored_filename(int(request_id), activity[0], activity[1], item)
        row = conn.execute(
            """INSERT INTO requisicao_arquivos (
                   requisicao_id,filename,provider,storage_status,original_filename,mime_type,
                   size_bytes,sha256,uploaded_at,uploader_user_id,operation_key,storage_object_id)
               VALUES (?,?,'supabase','active',?,?,?,?,?,?,?,?) RETURNING id""",
            (
                int(request_id), name, original, intent.declared_mime_type, intent.declared_size_bytes,
                intent.declared_sha256, uploaded_at, int(actor_user_id), intent.operation_id, int(object_id),
            ),
        ).fetchone()
        attached.append(int(row[0]))
    return attached


def find_completed_submission(conn, *, actor_user_id: int, intent_ids) -> int | None:
    """The request a replayed (response-lost) submission already created, if any."""
    ids = list(intent_ids or [])
    if not ids:
        return None
    request_ids = set()
    for intent_id in ids:
        intent = _intent_row(conn, intent_id)
        if intent is None or intent.actor_user_id != int(actor_user_id) or intent.state != "consumed":
            return None
        row = conn.execute(
            "SELECT requisicao_id FROM requisicao_arquivos WHERE storage_object_id=? AND provider='supabase'",
            (int(intent.storage_object_id),),
        ).fetchone()
        if row is None:
            return None
        request_ids.add(int(row[0]))
    return request_ids.pop() if len(request_ids) == 1 else None


# ---------------------------------------------------------------------------
# canonical read
# ---------------------------------------------------------------------------


def canonical_download_url(conn, attachment, *, download: bool) -> str:
    """A short-lived signed URL for an ACTIVE canonical attachment (caller authorized)."""
    if attachment["storage_status"] not in ("active", "legacy_active"):
        raise RequestDocumentError("ATTACHMENT_NOT_FOUND", "Comprovante não encontrado.", 404)
    obj = conn.execute(
        "SELECT storage_bucket,storage_key,lifecycle_state FROM storage_objects WHERE id=?",
        (int(attachment["storage_object_id"]),),
    ).fetchone()
    if obj is None or obj["lifecycle_state"] != "active":
        raise RequestDocumentError("ATTACHMENT_NOT_FOUND", "Comprovante não encontrado.", 404)
    download_name = None
    if download:
        from werkzeug.utils import secure_filename

        download_name = secure_filename(str(attachment["original_filename"] or "")) or None
        if download_name is None:
            download_name = secure_filename(str(attachment["filename"] or "")) or "comprovante"
    try:
        signed = canonical_store().create_signed_download(
            obj["storage_bucket"], obj["storage_key"],
            expires_in=SIGNED_DOWNLOAD_TTL_SECONDS, download_name=download_name,
        )
    except CanonicalStoreError as exc:
        if exc.code in (STORAGE_OBJECT_MISSING,):
            raise RequestDocumentError("ATTACHMENT_NOT_FOUND", "Comprovante não encontrado.", 404) from None
        raise RequestDocumentError(
            "STORAGE_UNAVAILABLE", "Não foi possível abrir o comprovante com segurança.", 503
        ) from None
    return signed.url


__all__ = [
    "CANONICAL_STORE_EXTENSION",
    "INTENT_IDS_FIELD",
    "INTENT_TTL_SECONDS",
    "LEGACY_FILE_FIELD",
    "RequestDocumentError",
    "SIGNED_DOWNLOAD_TTL_SECONDS",
    "AUTHENTICATION_REQUIRED_MESSAGE",
    "STORAGE_UNAVAILABLE_MESSAGE",
    "SUBMISSION_FIELD",
    "UploadCapability",
    "attach_request_documents",
    "canonical_download_url",
    "canonical_store",
    "finalize_request_document",
    "find_completed_submission",
    "has_file_parts",
    "issue_request_document",
    "issue_submission",
    "submission_is_live",
    "submitted_intent_ids",
]
