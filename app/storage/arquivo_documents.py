"""Canonical admin ARQUIVOS documents (STORAGE S3-B): direct upload, attach, read, delete.

DRIVE_AVAILABILITY_MUST_NOT_BLOCK_ADMIN_ARQUIVOS_CANONICAL_OPERATION.  Nothing
in this module reaches Google: NEW and REPLACED ARQUIVOS documents are
canonical Supabase Storage objects uploaded by the browser (the S3-A signed
TUS machinery of ``app.storage.request_documents`` is reused, never copied),
and the Drive mirror stays ``pending`` for S4.  Legacy Google / local rows keep
their legacy paths in ``app.arquivos`` until S5.

PROTOCOL
    1. ``GET /admin/arquivos`` renders a server-issued ``arquivos_submission_id``
       (128-bit, own session namespace, 2-hour window).
    2. ``issue_arquivo_document`` (``POST /storage/upload-intents``, purpose
       ``admin_arquivo``): admin with ``arquivos:edit``; create target NULL or
       a replaceable target row; intent ``<submission_id>:<upload_slot_id>``;
       for a replacement the content custody the row has NOW is bound to the
       intent in the server-signed session (a digest -- no provider locator
       reaches the browser).
    3. ``finalize_arquivo_document`` (``POST .../finalize``): the shared S3-A
       bounded verification.
    4. ``create_arquivo_from_intent`` / ``edit_arquivo`` (business POSTs):
       metadata + submission + exactly ONE verified intent, never bytes.  One
       write transaction, no network call: lock the target row FIRST, then the
       intent; re-check authorization, custody and state; consume; insert or
       update the canonical row; retire a replaced canonical object.

LOCK ORDER (replacement issue, replace, canonical AND legacy delete):
``admin_arquivos`` row, then target intents.

CANONICAL STATE: ``provider='supabase'``, ``storage_status='active'``,
``storage_object_id`` set, no Drive locator, no cleanup bookkeeping; a legacy
source's locator is kept as ``prior_provider`` / ``prior_locator`` residue
for S5 and its bytes are never touched here.  No canonical object is ever
physically deleted (retire only).
"""

from __future__ import annotations

import hashlib
import re
import secrets

from werkzeug.utils import secure_filename

from app.admin_access import _admin_can, _load_admin_access_context
from app.arquivos import ArquivoError, update_arquivo
from app.comprovante_file_validation import MIME_BY_EXTENSION
from app.db import write_transaction
from app.prod1_document_custody_ddl import LEGACY_LOCAL_LOCATOR_MAX_LENGTH
from app.prod1_storage_ddl import BUSINESS_DOCUMENT_MAX_BYTES, BUSINESS_DOCUMENT_MIME_TYPES
from app.storage import custody_common
from app.storage import mirror_outbox
from app.storage import request_documents as documents
from app.storage import upload_intents as intents
from app.storage.custody_common import CustodyError
from app.storage.object_store import STORAGE_OBJECT_MISSING, CanonicalStoreError
from app.storage.supabase_store import (
    configured_bucket,
    configured_project_url,
    configured_publishable_key,
    resumable_upload_endpoint,
)

PURPOSE = "admin_arquivo"
TARGET_FIELD = "admin_arquivo_id"
SUBMISSION_FIELD = "arquivos_submission_id"
INTENT_IDS_FIELD = "arquivos_intent_ids"
SUBMISSION_SESSION_KEY = "arquivos_submissions"
INTENT_TTL_SECONDS = documents.INTENT_TTL_SECONDS
SUBMISSION_TTL_SECONDS = INTENT_TTL_SECONDS
MAX_LIVE_SUBMISSIONS = 12
MAX_INTENTS_PER_SUBMISSION = 20
SIGNED_DOWNLOAD_TTL_SECONDS = documents.SIGNED_DOWNLOAD_TTL_SECONDS

NOT_FOUND_MESSAGE = "Arquivo não encontrado."
TITLE_REQUIRED_MESSAGE = "Informe o nome do arquivo."
FILE_REQUIRED_MESSAGE = "Selecione um arquivo para enviar."
DIRECT_UPLOAD_REQUIRED_MESSAGE = (
    "O arquivo é enviado diretamente pelo navegador e exige JavaScript. "
    "Recarregue a página e selecione o arquivo novamente."
)
SUBMISSION_EXPIRED_MESSAGE = "O formulário expirou. Recarregue a página e selecione o arquivo novamente."
SINGLE_FILE_MESSAGE = "Envie exatamente um arquivo."
BINDING_REFUSED_MESSAGE = "O arquivo enviado não pertence a esta operação. Selecione-o novamente."
STALE_CUSTODY_MESSAGE = (
    "O arquivo foi alterado por outra operação depois que esta substituição começou. "
    "Recarregue a página e tente novamente."
)
NOT_REPLACEABLE_MESSAGE = (
    "Este arquivo está em um estado legado pendente e não pode ser substituído agora."
)
UPLOAD_IN_PROGRESS_MESSAGE = (
    "Há um envio de substituição em andamento para este arquivo. Conclua-o ou aguarde a expiração."
)

_HEX128 = re.compile(r"^[0-9a-f]{32}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DRIVE_ID = re.compile(r"^[A-Za-z0-9_-]{1,256}$")


def _now() -> str:
    # The adjudicated clock seam: always through the module attribute.
    return custody_common.utc_now_text()


def _uploaded_at(now: str) -> str:
    return f"{now[:10]}T{now[11:]}Z"


# ---------------------------------------------------------------------------
# submissions (own session namespace) + bound replacement custody
# ---------------------------------------------------------------------------


def _live_submissions(session_obj, now: str) -> dict:
    raw = session_obj.get(SUBMISSION_SESSION_KEY)
    live = {}
    if isinstance(raw, dict):
        for sid, entry in raw.items():
            if not (isinstance(sid, str) and _HEX128.fullmatch(sid)):
                continue
            if not (isinstance(entry, (list, tuple)) and len(entry) == 3 and isinstance(entry[2], dict)):
                continue
            issued_at, user_id, bindings = entry
            try:
                expired = custody_common.add_seconds(str(issued_at), SUBMISSION_TTL_SECONDS) <= now
            except ValueError:
                continue
            if not expired:
                live[sid] = [str(issued_at), int(user_id), {str(k): str(v) for k, v in bindings.items()}]
    return live


def issue_submission(session_obj, user_id: int) -> str:
    """A fresh 128-bit ARQUIVOS submission id for one rendered admin form."""
    now = _now()
    live = _live_submissions(session_obj, now)
    while len(live) >= MAX_LIVE_SUBMISSIONS:
        live.pop(min(live, key=lambda sid: live[sid][0]))
    submission_id = secrets.token_hex(16)
    live[submission_id] = [now, int(user_id), {}]
    session_obj[SUBMISSION_SESSION_KEY] = live
    session_obj.modified = True
    return submission_id


def _live_entry(session_obj, submission_id, user_id: int):
    if not (isinstance(submission_id, str) and _HEX128.fullmatch(submission_id)):
        return None
    entry = _live_submissions(session_obj, _now()).get(submission_id)
    return entry if entry is not None and entry[1] == int(user_id) else None


def _bind_custody(session_obj, submission_id: str, intent_id: str, fingerprint: str) -> None:
    """Record (once) the custody a replacement intent was issued against."""
    live = _live_submissions(session_obj, _now())
    entry = live.get(submission_id)
    if entry is None:  # pragma: no cover - checked by the caller in the same request
        return
    entry[2].setdefault(intent_id, fingerprint)
    session_obj[SUBMISSION_SESSION_KEY] = live
    session_obj.modified = True


def custody_fingerprint(row) -> str:
    """Server-only digest of the content custody a row holds (no locator exposed)."""
    if row["storage_object_id"] is not None:
        identity = f"supabase\0{int(row['storage_object_id'])}"
    elif row["provider"] == "google":
        identity = f"google\0{row['remote_file_id'] or ''}"
    else:
        identity = f"{row['provider']}\0{row['filename'] or ''}"
    return hashlib.sha256(f"{int(row['id'])}\0{identity}".encode("utf-8")).hexdigest()


def _local_locator_ok(locator: str) -> bool:
    return (
        bool(locator.strip()) and locator.strip() == locator
        and len(locator) <= LEGACY_LOCAL_LOCATOR_MAX_LENGTH
        and locator[:1] not in ("/", "\\") and ":" not in locator and ".." not in locator
    )


def is_replaceable(row) -> bool:
    """Canonical replacement sources: canonical / google active / local legacy_active only."""
    if str(row["failure_code"] or "").startswith("REPLACEMENT_"):
        return False
    provider, status = row["provider"], row["storage_status"]
    if provider == "supabase":
        return status == "active" and row["storage_object_id"] is not None
    if row["storage_object_id"] is not None or row["failure_code"] is not None:
        return False
    if row["prior_provider"] is not None or row["cleanup_started_at"] is not None:
        return False
    if provider == "google":
        return status == "active" and bool(_DRIVE_ID.fullmatch(str(row["remote_file_id"] or "")))
    if provider == "local_legacy":
        return (
            status == "legacy_active" and row["operation_key"] is None
            and _local_locator_ok(str(row["filename"] or ""))
        )
    return False


# ---------------------------------------------------------------------------
# authorization
# ---------------------------------------------------------------------------


def _can_edit_arquivos(conn, actor_user_id: int) -> bool:
    row = conn.execute("SELECT tipo FROM usuarios WHERE id=?", (int(actor_user_id),)).fetchone()
    if row is None or str(row["tipo"] or "").strip().lower() != "admin":
        return False
    return _admin_can("arquivos", "edit", _load_admin_access_context(conn, int(actor_user_id)))


def _authorize_actor(conn, actor_user_id: int) -> None:
    if not _can_edit_arquivos(conn, actor_user_id):
        raise documents.RequestDocumentError("ACCESS_DENIED", "Acesso negado.", 403)


def _lock_row(conn, arquivo_id: int):
    suffix = " FOR UPDATE" if custody_common.is_postgres(conn) else ""
    return conn.execute(f"SELECT * FROM admin_arquivos WHERE id=?{suffix}", (int(arquivo_id),)).fetchone()


# ---------------------------------------------------------------------------
# 2. issue / 3. finalize (the shared S3-A routes dispatch here by purpose)
# ---------------------------------------------------------------------------


def _declared_int(value):
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def issue_arquivo_document(conn, session_obj, *, actor_user_id: int, payload) -> documents.UploadCapability:
    if not isinstance(payload, dict) or payload.get("purpose") != PURPOSE:
        raise documents.RequestDocumentError("INVALID_REQUEST", "Pedido inválido.")
    _authorize_actor(conn, actor_user_id)
    submission_id = payload.get("submission_id")
    if _live_entry(session_obj, submission_id, actor_user_id) is None:
        raise documents.RequestDocumentError("SUBMISSION_INVALID", SUBMISSION_EXPIRED_MESSAGE, 403)
    slot = payload.get("upload_slot_id")
    if not (isinstance(slot, str) and _HEX128.fullmatch(slot)):
        raise documents.RequestDocumentError("INVALID_UPLOAD_SLOT", "Identificador de envio inválido.")

    target_row = None
    arquivo_id = None
    if TARGET_FIELD in payload and payload[TARGET_FIELD] is not None:
        arquivo_id = _declared_int(payload[TARGET_FIELD])
        if arquivo_id is None or arquivo_id <= 0:
            raise documents.RequestDocumentError("INVALID_TARGET", "Arquivo inválido.")
        target_row = conn.execute("SELECT * FROM admin_arquivos WHERE id=?", (arquivo_id,)).fetchone()
        if target_row is None:
            raise documents.RequestDocumentError("ARQUIVO_NOT_FOUND", NOT_FOUND_MESSAGE, 404)
        if not is_replaceable(target_row):
            raise documents.RequestDocumentError("ARQUIVO_NOT_REPLACEABLE", NOT_REPLACEABLE_MESSAGE, 409)

    original = str(payload.get("filename") or "").replace("\\", "/").rsplit("/", 1)[-1].strip()[:255]
    extension = original.rsplit(".", 1)[-1].lower() if "." in original else ""
    expected_mime = MIME_BY_EXTENSION.get(extension)
    declared_mime = payload.get("mime_type")
    if not expected_mime or declared_mime not in BUSINESS_DOCUMENT_MIME_TYPES:
        raise documents.RequestDocumentError(
            "UNSUPPORTED_FILE_TYPE", "Envie somente arquivos PDF, PNG ou JPEG.")
    if declared_mime != expected_mime:
        raise documents.RequestDocumentError(
            "MIME_MISMATCH", "A extensão não corresponde ao conteúdo do arquivo.")
    if not secure_filename(original):
        raise documents.RequestDocumentError("INVALID_FILENAME", "O nome do arquivo é inválido.")
    size = _declared_int(payload.get("size_bytes"))
    if size is None or size <= 0:
        raise documents.RequestDocumentError("MALFORMED_FILE", "O arquivo está vazio ou malformado.")
    if size > BUSINESS_DOCUMENT_MAX_BYTES:
        raise documents.RequestDocumentError("FILE_TOO_LARGE", "O arquivo excede o limite de 16 MiB.", 413)
    declared_sha = payload.get("sha256")
    if not (isinstance(declared_sha, str) and _SHA256.fullmatch(declared_sha)):
        raise documents.RequestDocumentError("INVALID_DECLARATION", "Declaração do arquivo inválida.")

    operation_id = f"{submission_id}:{slot}"
    now = _now()
    others = conn.execute(
        "SELECT count(*) FROM storage_upload_intents WHERE actor_user_id=? AND purpose=?"
        " AND operation_id LIKE ? AND operation_id<>? AND state IN ('issued','verified') AND expires_at>?",
        (int(actor_user_id), PURPOSE, f"{submission_id}:%", operation_id, now),
    ).fetchone()
    if int(others[0]) >= MAX_INTENTS_PER_SUBMISSION:
        raise documents.RequestDocumentError("TOO_MANY_FILES", SINGLE_FILE_MESSAGE)
    bucket = configured_bucket()
    endpoint = resumable_upload_endpoint(configured_project_url())
    apikey = configured_publishable_key()
    try:
        with write_transaction(conn):
            if arquivo_id is not None:
                # Re-check the target under its row lock (row first, then the intent):
                # a delete that already entered its deletion state wins, and a delete
                # that comes later sees this intent as LIVE and refuses.
                target_row = _lock_row(conn, arquivo_id)
                if target_row is None:
                    raise documents.RequestDocumentError("ARQUIVO_NOT_FOUND", NOT_FOUND_MESSAGE, 404)
                if not is_replaceable(target_row):
                    raise documents.RequestDocumentError("ARQUIVO_NOT_REPLACEABLE", NOT_REPLACEABLE_MESSAGE, 409)
            intent = intents.issue_intent(
                conn, actor_user_id=int(actor_user_id), purpose=PURPOSE, operation_id=operation_id,
                bucket=bucket, declared_mime_type=declared_mime, declared_size_bytes=size,
                declared_sha256=declared_sha, now=now, original_filename=original,
                admin_arquivo_id=arquivo_id, ttl_seconds=INTENT_TTL_SECONDS,
            )
    except CustodyError as exc:
        if exc.code == intents.INTENT_OPERATION_CONFLICT:
            raise documents.RequestDocumentError(
                "INTENT_OPERATION_CONFLICT", "Este envio já pertence a outro arquivo.", 409
            ) from None
        raise documents.RequestDocumentError(exc.code, "Envio recusado.", 409) from None
    if target_row is not None:
        _bind_custody(session_obj, submission_id, intent.id, custody_fingerprint(target_row))
    return documents.mint_capability(intent, endpoint=endpoint, apikey=apikey)


def owns_arquivo_intent(conn, intent_id, actor_user_id: int) -> bool:
    """True only for the actor's own ``admin_arquivo`` intent (otherwise S3-A's not-found)."""
    if not (isinstance(intent_id, str) and _HEX128.fullmatch(intent_id)):
        return False
    intent = intents._load(conn, intent_id, lock=False)
    return intent is not None and intent.purpose == PURPOSE and intent.actor_user_id == int(actor_user_id)


def finalize_arquivo_document(conn, *, actor_user_id: int, intent_id) -> str:
    return documents.finalize_intent(
        conn, actor_user_id=actor_user_id, intent_id=intent_id, purpose=PURPOSE,
        authorize=lambda _intent: _authorize_actor(conn, actor_user_id),
    )


# ---------------------------------------------------------------------------
# 4. business attach (create / replace) and metadata edit
# ---------------------------------------------------------------------------


def _refuse_file_parts(files) -> None:
    if documents.has_file_parts(files):
        raise ArquivoError(DIRECT_UPLOAD_REQUIRED_MESSAGE, code="DIRECT_UPLOAD_REQUIRED")


def _single_intent(form) -> str:
    ids: list[str] = []
    for raw in form.getlist(INTENT_IDS_FIELD):
        value = str(raw or "").strip()
        if value and value not in ids:
            ids.append(value)
    if not ids:
        raise ArquivoError(FILE_REQUIRED_MESSAGE, code="FILE_REQUIRED")
    if len(ids) > 1:
        raise ArquivoError(SINGLE_FILE_MESSAGE, code="TOO_MANY_FILES")
    return ids[0]


def _metadata(form):
    titulo = str(form.get("titulo") or "").strip()
    if not titulo:
        raise ArquivoError(TITLE_REQUIRED_MESSAGE, code="TITLE_REQUIRED")
    descricao = str(form.get("descricao") or "").strip() or None
    visivel = 0 if str(form.get("visivel", "1")).strip().lower() in {"0", "false"} else 1
    return titulo, descricao, visivel


def _binding_refused() -> ArquivoError:
    return ArquivoError(BINDING_REFUSED_MESSAGE, code="DOCUMENT_BINDING_REFUSED")


def _locked_verified_intent(conn, intent_id: str, *, actor_user_id: int, submission_id: str,
                            arquivo_id: int | None, now: str):
    intent = intents._load(conn, intent_id, lock=True)
    if (
        intent is None
        or intent.actor_user_id != int(actor_user_id)
        or intent.purpose != PURPOSE
        or not intent.operation_id.startswith(f"{submission_id}:")
        or intent.state != "verified"
        or intent.expires_at <= now
        or intent.admin_arquivo_id != arquivo_id
    ):
        raise _binding_refused()
    return intent


def _stored_filename(intent) -> str:
    original = intent.original_filename or "arquivo"
    suffix = hashlib.sha256(intent.operation_id.encode("utf-8")).hexdigest()[:12]
    return f"ARQ-{suffix}-{secure_filename(original) or 'arquivo'}"[:255]


def _replayed_row(conn, intent_id: str, *, actor_user_id: int, arquivo_id: int | None):
    """The row a SAME already-consumed intent produced (lost-response replay), if any."""
    if not (isinstance(intent_id, str) and _HEX128.fullmatch(intent_id)):
        return None
    intent = intents._load(conn, intent_id, lock=False)
    if (
        intent is None or intent.state != "consumed" or intent.purpose != PURPOSE
        or intent.actor_user_id != int(actor_user_id) or intent.storage_object_id is None
    ):
        return None
    row = conn.execute(
        "SELECT id FROM admin_arquivos WHERE storage_object_id=? AND provider='supabase'",
        (int(intent.storage_object_id),),
    ).fetchone()
    if row is None or (arquivo_id is not None and int(row["id"]) != int(arquivo_id)):
        return None
    return int(row["id"])


def create_arquivo_from_intent(conn, session_obj, *, actor_user_id: int, form, files) -> int:
    """Create one canonical ARQUIVOS row from ONE verified create intent."""
    _refuse_file_parts(files)
    titulo, descricao, visivel = _metadata(form)
    intent_id = _single_intent(form)
    replayed = _replayed_row(conn, intent_id, actor_user_id=actor_user_id, arquivo_id=None)
    if replayed is not None:
        return replayed
    submission_id = str(form.get(SUBMISSION_FIELD) or "").strip()
    if _live_entry(session_obj, submission_id, actor_user_id) is None:
        raise ArquivoError(SUBMISSION_EXPIRED_MESSAGE, code="SUBMISSION_INVALID")
    now = _now()
    try:
        with write_transaction(conn):
            if not _can_edit_arquivos(conn, actor_user_id):
                raise ArquivoError("Acesso negado.", code="ACCESS_DENIED")
            intent = _locked_verified_intent(conn, intent_id, actor_user_id=actor_user_id,
                                             submission_id=submission_id, arquivo_id=None, now=now)
            _consumed, object_id = intents.consume_intent(
                conn, intent_id=intent.id, actor_user_id=int(actor_user_id), purpose=PURPOSE,
                operation_id=intent.operation_id, now=now,
            )
            row = conn.execute(
                """INSERT INTO admin_arquivos (
                       titulo,descricao,filename,original_filename,visivel,provider,mime_type,size_bytes,
                       sha256,uploaded_at,uploader_user_id,operation_key,storage_status,storage_object_id)
                   VALUES (?,?,?,?,?,'supabase',?,?,?,?,?,?,'active',?) RETURNING id""",
                (
                    titulo, descricao, _stored_filename(intent), intent.original_filename or "arquivo",
                    visivel, intent.declared_mime_type, intent.declared_size_bytes, intent.declared_sha256,
                    _uploaded_at(now), int(actor_user_id), intent.operation_id, int(object_id),
                ),
            ).fetchone()
    except CustodyError:
        raise _binding_refused() from None
    return int(row[0])


def _replace(conn, session_obj, *, actor_user_id: int, arquivo_id: int, form, intent_id: str,
             titulo: str, descricao, visivel: int) -> None:
    if _replayed_row(conn, intent_id, actor_user_id=actor_user_id, arquivo_id=arquivo_id) is not None:
        return
    submission_id = str(form.get(SUBMISSION_FIELD) or "").strip()
    entry = _live_entry(session_obj, submission_id, actor_user_id)
    if entry is None:
        raise ArquivoError(SUBMISSION_EXPIRED_MESSAGE, code="SUBMISSION_INVALID")
    expected = entry[2].get(intent_id)
    if expected is None:
        raise _binding_refused()
    now = _now()
    try:
        with write_transaction(conn):
            if not _can_edit_arquivos(conn, actor_user_id):
                raise ArquivoError("Acesso negado.", code="ACCESS_DENIED")
            row = _lock_row(conn, arquivo_id)  # lock order: row first, then intents
            if row is None:
                raise ArquivoError(NOT_FOUND_MESSAGE, code="NOT_FOUND")
            if custody_fingerprint(row) != expected:
                raise ArquivoError(STALE_CUSTODY_MESSAGE, code="STALE_CUSTODY", retryable=True)
            if not is_replaceable(row):
                raise ArquivoError(NOT_REPLACEABLE_MESSAGE, code="ARQUIVO_NOT_REPLACEABLE")
            intent = _locked_verified_intent(conn, intent_id, actor_user_id=actor_user_id,
                                             submission_id=submission_id, arquivo_id=int(arquivo_id), now=now)
            _consumed, object_id = intents.consume_intent(
                conn, intent_id=intent.id, actor_user_id=int(actor_user_id), purpose=PURPOSE,
                operation_id=intent.operation_id, now=now,
            )
            values = (
                titulo, descricao, visivel, _stored_filename(intent), intent.original_filename or "arquivo",
                intent.declared_mime_type, intent.declared_size_bytes, intent.declared_sha256,
                _uploaded_at(now), int(actor_user_id), intent.operation_id, int(object_id),
            )
            common = """titulo=?,descricao=?,visivel=?,filename=?,original_filename=?,mime_type=?,size_bytes=?,
                        sha256=?,uploaded_at=?,uploader_user_id=?,operation_key=?,storage_object_id=?"""
            if row["provider"] == "supabase":
                old_object_id = int(row["storage_object_id"])
                conn.execute(f"UPDATE admin_arquivos SET {common},failure_code=NULL WHERE id=?",
                             (*values, int(arquivo_id)))
                state = conn.execute("SELECT lifecycle_state FROM storage_objects WHERE id=?",
                                     (old_object_id,)).fetchone()
                if state is not None and state["lifecycle_state"] == "active":
                    mirror_outbox.retire_object(conn, object_id=old_object_id, now=now)
            else:
                prior_locator = row["remote_file_id"] if row["provider"] == "google" else row["filename"]
                conn.execute(
                    f"""UPDATE admin_arquivos
                           SET {common},provider='supabase',storage_status='active',
                               remote_file_id=NULL,remote_parent_id=NULL,failure_code=NULL,
                               replacement_mime_type=NULL,replacement_size_bytes=NULL,replacement_sha256=NULL,
                               prior_provider=?,prior_locator=?,cleanup_started_at=NULL
                         WHERE id=?""",
                    (*values, row["provider"], str(prior_locator), int(arquivo_id)),
                )
    except CustodyError:
        raise _binding_refused() from None


def edit_arquivo(conn, session_obj, *, actor_user_id: int, arquivo_id: int, form, files,
                 max_file_bytes: int, upload_root: str) -> bool:
    """The edit POST: a verified replacement intent, or a metadata-only edit (any custody)."""
    _refuse_file_parts(files)
    has_intent = any(str(raw or "").strip() for raw in form.getlist(INTENT_IDS_FIELD))
    if not has_intent:
        return update_arquivo(
            conn, arquivo_id=int(arquivo_id), file_storage=None, titulo=form.get("titulo"),
            descricao=form.get("descricao"), visivel=form.get("visivel", "1"),
            uploader_user_id=int(actor_user_id), operation_key=None, max_file_bytes=int(max_file_bytes),
            upload_root=upload_root,
        )
    titulo, descricao, visivel = _metadata(form)
    _replace(conn, session_obj, actor_user_id=actor_user_id, arquivo_id=int(arquivo_id), form=form,
             intent_id=_single_intent(form), titulo=titulo, descricao=descricao, visivel=visivel)
    return True


# ---------------------------------------------------------------------------
# canonical read / delete
# ---------------------------------------------------------------------------


def is_canonical(row) -> bool:
    """Canonical custody wins whenever a canonical reference exists."""
    return row is not None and row["storage_object_id"] is not None


def canonical_download_url(conn, row, *, download: bool) -> str:
    """A 60-second signed private URL for a canonical row's ACTIVE object (caller authorized)."""
    obj = conn.execute(
        "SELECT storage_bucket,storage_key,lifecycle_state FROM storage_objects WHERE id=?",
        (int(row["storage_object_id"]),),
    ).fetchone()
    if obj is None or obj["lifecycle_state"] != "active":
        raise ArquivoError(NOT_FOUND_MESSAGE, code="NOT_FOUND")
    download_name = None
    if download:
        download_name = (secure_filename(str(row["original_filename"] or ""))
                         or secure_filename(str(row["filename"] or "")) or "arquivo")
    try:
        signed = documents.canonical_store().create_signed_download(
            obj["storage_bucket"], obj["storage_key"],
            expires_in=SIGNED_DOWNLOAD_TTL_SECONDS, download_name=download_name,
        )
    except CanonicalStoreError as exc:
        if exc.code == STORAGE_OBJECT_MISSING:
            raise ArquivoError(NOT_FOUND_MESSAGE, code="NOT_FOUND") from None
        raise ArquivoError(documents.STORAGE_UNAVAILABLE_MESSAGE, code="STORAGE_UNAVAILABLE",
                           retryable=True) from None
    return signed.url


def lock_for_delete(conn, arquivo_id: int):
    """THE ARQUIVOS delete gate, for EVERY replacement target (canonical AND legacy).

    The caller owns the write transaction.  Lock order: the ``admin_arquivos``
    row FIRST, then its target intents.  Refused while a target
    ``admin_arquivo`` intent is LIVE = issued / verified AND unexpired:
    live replacement work may still upload / attach, so its tracking must not
    vanish through the FK cascade.  Rejected, expired, consumed and
    past-expiry intents never block (they are not cleanup ownership).
    Returns the locked row.
    """
    row = _lock_row(conn, arquivo_id)
    if row is None:
        raise ArquivoError(NOT_FOUND_MESSAGE, code="NOT_FOUND")
    lock = " FOR UPDATE" if custody_common.is_postgres(conn) else ""
    live = conn.execute(
        "SELECT id FROM storage_upload_intents WHERE purpose=? AND admin_arquivo_id=?"
        f" AND state IN ('issued','verified') AND expires_at>?{lock}",
        (PURPOSE, int(arquivo_id), _now()),
    ).fetchall()
    if live:
        raise ArquivoError(UPLOAD_IN_PROGRESS_MESSAGE, code="UPLOAD_IN_PROGRESS", retryable=True)
    return row


def delete_canonical_arquivo(conn, arquivo_id: int) -> None:
    """Retire the canonical object and delete the row -- behind ``lock_for_delete``.

    Legacy residue bytes are untouched.
    """
    now = _now()
    with write_transaction(conn):
        row = lock_for_delete(conn, arquivo_id)
        object_id = int(row["storage_object_id"])
        state = conn.execute("SELECT lifecycle_state FROM storage_objects WHERE id=?", (object_id,)).fetchone()
        if state is not None and state["lifecycle_state"] == "active":
            mirror_outbox.retire_object(conn, object_id=object_id, now=now)
        conn.execute("DELETE FROM admin_arquivos WHERE id=?", (int(arquivo_id),))


__all__ = [
    "INTENT_IDS_FIELD",
    "PURPOSE",
    "SUBMISSION_FIELD",
    "TARGET_FIELD",
    "canonical_download_url",
    "create_arquivo_from_intent",
    "custody_fingerprint",
    "delete_canonical_arquivo",
    "edit_arquivo",
    "finalize_arquivo_document",
    "is_canonical",
    "is_replaceable",
    "issue_arquivo_document",
    "issue_submission",
    "lock_for_delete",
    "owns_arquivo_intent",
]
