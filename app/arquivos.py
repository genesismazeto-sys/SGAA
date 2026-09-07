from __future__ import annotations

import datetime
import hashlib
import mimetypes
import os
import secrets
import sqlite3
from dataclasses import dataclass

from flask import current_app
from werkzeug.utils import secure_filename

from app.file_validation import MIME_BY_EXTENSION, detect_supported_mime
from app.storage.contracts import (
    ManagedObjectStorage,
    RemoteObject,
    StorageConflictError,
    StorageError,
    StorageIntegrityError,
)
from app.storage.google_connection import resolve_google_managed_storage
from app.student_documents import resolve_student_document_path


class ArquivoError(RuntimeError):
    def __init__(self, user_message: str, *, code: str = "ARQUIVO_ERROR", retryable: bool = False):
        super().__init__(user_message)
        self.user_message = user_message
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class PreparedArquivo:
    original_filename: str
    stored_filename: str
    mime_type: str
    content: bytes
    size: int
    sha256: str
    uploaded_at: str


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_arquivo_operation_id() -> str:
    return secrets.token_urlsafe(24)


def _bounded_operation_key(value: str | None) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > 124:
        raise ArquivoError("A identidade da operação de arquivo é inválida.", code="INVALID_OPERATION_KEY")
    return normalized


def _visibility(value: object) -> int:
    return 0 if str(value).strip().lower() in {"0", "false"} else 1


def prepare_arquivo(file_storage, *, operation_key: str, max_file_bytes: int) -> PreparedArquivo:
    if not file_storage or not getattr(file_storage, "filename", ""):
        raise ArquivoError("Selecione um arquivo para enviar.", code="FILE_REQUIRED")
    original = str(file_storage.filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()[:255]
    safe_original = secure_filename(original)
    if not safe_original:
        raise ArquivoError("O nome do arquivo é inválido.", code="INVALID_FILENAME")
    extension = safe_original.rsplit(".", 1)[-1].lower() if "." in safe_original else ""
    expected_mime = MIME_BY_EXTENSION.get(extension)
    if not expected_mime:
        raise ArquivoError("Envie somente arquivos PDF, PNG ou JPEG.", code="UNSUPPORTED_FILE_TYPE")
    stream = getattr(file_storage, "stream", file_storage)
    content = stream.read(int(max_file_bytes) + 1)
    try:
        stream.seek(0)
    except (AttributeError, OSError):
        pass
    if len(content) > int(max_file_bytes):
        raise ArquivoError("O arquivo excede o limite técnico de 16 MiB.", code="FILE_TOO_LARGE")
    actual_mime = detect_supported_mime(content)
    if actual_mime is None:
        raise ArquivoError("O arquivo está vazio, malformado ou protegido por senha.", code="MALFORMED_FILE")
    if actual_mime != expected_mime:
        raise ArquivoError("A extensão não corresponde ao conteúdo do arquivo.", code="MIME_MISMATCH")
    operation = _bounded_operation_key(operation_key)
    suffix = hashlib.sha256(operation.encode("utf-8")).hexdigest()[:12]
    stored = f"ARQ-{suffix}-{safe_original}"[:255]
    return PreparedArquivo(
        original_filename=original,
        stored_filename=stored,
        mime_type=actual_mime,
        content=content,
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        uploaded_at=_utc_now(),
    )


def resolve_arquivo_storage(conn) -> ManagedObjectStorage:
    return resolve_google_managed_storage(conn, extension_key="arquivo_storage")


def _ensure_arquivos_root(storage: ManagedObjectStorage) -> str:
    parent = storage.ensure_folder(
        parent_id="root", kind="product_root", semantic_id="sgaa", display_name="SGAA"
    )
    return storage.ensure_folder(
        parent_id=parent, kind="domain_root", semantic_id="arquivos", display_name="ARQUIVOS"
    )


def _verify_remote(item: PreparedArquivo, remote: RemoteObject) -> None:
    if remote.size != item.size or remote.sha256 != item.sha256:
        raise StorageIntegrityError("O arquivo remoto não corresponde ao conteúdo enviado.")


def _storage_failure_state(exc: StorageError) -> str:
    if exc.retryable or isinstance(exc, (StorageConflictError, StorageIntegrityError)):
        return "reconciliation_required"
    return "failed"


def _raise_storage(exc: StorageError) -> None:
    raise ArquivoError(str(exc), code=exc.code, retryable=exc.retryable) from exc


def _upload_google_arquivo(
    storage: ManagedObjectStorage,
    item: PreparedArquivo,
    *,
    parent_id: str,
    arquivo_id: int,
    operation: str,
) -> RemoteObject:
    return storage.upload(
        parent_id=parent_id,
        stored_filename=item.stored_filename,
        content=item.content,
        mime_type=item.mime_type,
        operation_key=operation,
        object_kind="arquivo",
        semantic_properties={"sgaaArquivo": str(arquivo_id)},
    )


def create_arquivo(
    conn,
    *,
    file_storage,
    titulo: str,
    descricao: str | None,
    visivel: int,
    uploader_user_id: int,
    operation_key: str,
    max_file_bytes: int,
) -> int:
    titulo = str(titulo or "").strip()
    if not titulo:
        raise ArquivoError("Informe o nome do arquivo.", code="TITLE_REQUIRED")
    operation = _bounded_operation_key(operation_key)
    item = prepare_arquivo(file_storage, operation_key=operation, max_file_bytes=max_file_bytes)
    existing = conn.execute(
        "SELECT * FROM admin_arquivos WHERE operation_key=?", (operation,)
    ).fetchone()
    if existing:
        if str(existing["sha256"] or "") != item.sha256:
            raise ArquivoError("A identidade da operação pertence a outro arquivo.", code="OPERATION_KEY_CONFLICT")
        arquivo_id = int(existing["id"])
        if existing["storage_status"] == "active":
            return arquivo_id
        conn.execute(
            "UPDATE admin_arquivos SET storage_status='pending' WHERE id=?",
            (arquivo_id,),
        )
    else:
        cursor = conn.execute(
            """INSERT INTO admin_arquivos (
                   titulo,descricao,filename,original_filename,visivel,provider,
                   mime_type,size_bytes,sha256,uploaded_at,uploader_user_id,
                   operation_key,storage_status)
               VALUES (?,?,?,?,?,'google',?,?,?,?,?,?,'pending')""",
            (
                titulo, str(descricao or "").strip() or None, item.stored_filename,
                item.original_filename, _visibility(visivel), item.mime_type, item.size,
                item.sha256, item.uploaded_at, int(uploader_user_id), operation,
            ),
        )
        arquivo_id = int(cursor.lastrowid)
    conn.commit()
    upload_started = False
    try:
        storage = resolve_arquivo_storage(conn)
        parent_id = _ensure_arquivos_root(storage)
        conn.execute(
            """UPDATE admin_arquivos
                  SET remote_parent_id=?,failure_code='UPLOAD_IN_PROGRESS'
                WHERE id=?""",
            (parent_id, arquivo_id),
        )
        conn.commit()
        upload_started = True
        remote = _upload_google_arquivo(
            storage,
            item,
            parent_id=parent_id,
            arquivo_id=arquivo_id,
            operation=operation,
        )
        conn.execute(
            "UPDATE admin_arquivos SET remote_file_id=?,remote_parent_id=? WHERE id=?",
            (remote.file_id, remote.parent_id, arquivo_id),
        )
        conn.commit()
        _verify_remote(item, remote)
        conn.execute(
            """UPDATE admin_arquivos
                  SET remote_file_id=?,remote_parent_id=?,storage_status='active',failure_code=NULL
                WHERE id=?""",
            (remote.file_id, remote.parent_id, arquivo_id),
        )
        conn.commit()
        return arquivo_id
    except StorageError as exc:
        conn.execute(
            "UPDATE admin_arquivos SET storage_status=?,failure_code=? WHERE id=?",
            (_storage_failure_state(exc) if upload_started else "failed", exc.code, arquivo_id),
        )
        conn.commit()
        _raise_storage(exc)
    except sqlite3.Error as exc:
        conn.rollback()
        conn.execute(
            "UPDATE admin_arquivos SET storage_status='reconciliation_required',failure_code='ACTIVATION_DB_PENDING' WHERE id=?",
            (arquivo_id,),
        )
        conn.commit()
        raise ArquivoError(
            "A ativação do arquivo remoto aguarda reconciliação.",
            code="ACTIVATION_DB_PENDING",
            retryable=True,
        ) from exc


def _remove_local(upload_root: str, locator: str) -> None:
    try:
        path = resolve_student_document_path(upload_root, locator)
    except ValueError as exc:
        raise ArquivoError(
            "O caminho do arquivo local é inválido.", code="INVALID_LOCAL_PATH"
        ) from exc
    try:
        os.remove(path)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise ArquivoError(
            "Não foi possível remover o arquivo local com segurança.",
            code="LOCAL_DELETE_FAILED",
            retryable=True,
        ) from exc


def remove_legacy_arquivo_file(upload_root: str, locator: str) -> None:
    """Remove one historical ARQUIVOS object through canonical containment."""
    _remove_local(upload_root, locator)


def _cleanup_locator(storage: ManagedObjectStorage | None, *, provider: str, locator: str, upload_root: str) -> None:
    if provider == "google":
        if storage is None:
            raise StorageError("O armazenamento Google não está disponível.")
        storage.trash(locator)
        return
    if provider == "local_legacy":
        _remove_local(upload_root, locator)
        return
    raise ArquivoError("Provedor de arquivo inválido.", code="INVALID_PROVIDER")


def retry_arquivo_cleanup(conn, arquivo_id: int, *, upload_root: str) -> bool:
    row = conn.execute("SELECT * FROM admin_arquivos WHERE id=?", (int(arquivo_id),)).fetchone()
    if not row or row["storage_status"] != "replacement_cleanup_pending":
        return True
    try:
        storage = resolve_arquivo_storage(conn) if row["prior_provider"] == "google" else None
        _cleanup_locator(
            storage,
            provider=str(row["prior_provider"]),
            locator=str(row["prior_locator"]),
            upload_root=upload_root,
        )
    except (StorageError, ArquivoError) as exc:
        conn.execute(
            "UPDATE admin_arquivos SET failure_code=? WHERE id=?",
            (getattr(exc, "code", "CLEANUP_FAILED"), int(arquivo_id)),
        )
        conn.commit()
        return False
    conn.execute(
        """UPDATE admin_arquivos
              SET storage_status='active',failure_code=NULL,prior_provider=NULL,
                  prior_locator=NULL,cleanup_started_at=NULL
            WHERE id=?""",
        (int(arquivo_id),),
    )
    conn.commit()
    return True


def _update_arquivo_metadata(
    conn, *, arquivo_id: int, titulo: str, descricao: str | None, visivel: int
) -> None:
    conn.execute(
        "UPDATE admin_arquivos SET titulo=?,descricao=?,visivel=? WHERE id=?",
        (titulo, str(descricao or "").strip() or None, _visibility(visivel), int(arquivo_id)),
    )
    conn.commit()


def _reserve_replacement_operation(
    conn,
    *,
    row,
    arquivo_id: int,
    operation: str,
    item: PreparedArquivo,
    titulo: str,
    descricao: str | None,
    visivel: int,
) -> bool:
    replacement_pending = str(row["failure_code"] or "").startswith("REPLACEMENT_")
    if replacement_pending and str(row["operation_key"] or "") != operation:
        raise ArquivoError(
            "A substituição pendente deve ser repetida com a mesma identidade de operação.",
            code="REPLACEMENT_RETRY_REQUIRED",
            retryable=True,
        )
    operation_owner = conn.execute(
        """SELECT id,mime_type,size_bytes,sha256,replacement_mime_type,
                  replacement_size_bytes,replacement_sha256
             FROM admin_arquivos WHERE operation_key=?""",
        (operation,),
    ).fetchone()
    if operation_owner and int(operation_owner["id"]) != int(arquivo_id):
        raise ArquivoError(
            "A identidade da operação pertence a outro arquivo.",
            code="OPERATION_KEY_CONFLICT",
        )
    if replacement_pending:
        intended_identity = (
            str(row["replacement_mime_type"] or ""),
            int(row["replacement_size_bytes"] or 0),
            str(row["replacement_sha256"] or ""),
        )
        submitted_identity = (item.mime_type, item.size, item.sha256)
        if intended_identity != submitted_identity:
            raise ArquivoError(
                "A identidade da operação pertence a outro arquivo.",
                code="OPERATION_KEY_CONFLICT",
            )
        return True
    if operation_owner:
        active_identity = (
            str(operation_owner["mime_type"] or ""),
            int(operation_owner["size_bytes"] or 0),
            str(operation_owner["sha256"] or ""),
        )
        if active_identity != (item.mime_type, item.size, item.sha256):
            raise ArquivoError(
                "A identidade da operação pertence a outro arquivo.",
                code="OPERATION_KEY_CONFLICT",
            )
        _update_arquivo_metadata(
            conn,
            arquivo_id=arquivo_id,
            titulo=titulo,
            descricao=descricao,
            visivel=visivel,
        )
        return False
    conn.execute(
        """UPDATE admin_arquivos
              SET operation_key=?,failure_code='REPLACEMENT_UPLOAD_PENDING',
                  replacement_mime_type=?,replacement_size_bytes=?,replacement_sha256=?
            WHERE id=?""",
        (operation, item.mime_type, item.size, item.sha256, int(arquivo_id)),
    )
    conn.commit()
    return True


def _promote_replacement(
    conn,
    *,
    row,
    arquivo_id: int,
    item: PreparedArquivo,
    remote: RemoteObject,
    operation: str,
    titulo: str,
    descricao: str | None,
    visivel: int,
    uploader_user_id: int,
) -> None:
    prior_provider = str(row["provider"])
    prior_locator = str(
        row["remote_file_id"] if prior_provider == "google" else row["filename"]
    )
    try:
        conn.execute(
            """UPDATE admin_arquivos
                  SET titulo=?,descricao=?,visivel=?,filename=?,original_filename=?,
                      provider='google',remote_file_id=?,remote_parent_id=?,mime_type=?,
                      size_bytes=?,sha256=?,uploaded_at=?,uploader_user_id=?,operation_key=?,
                      storage_status='replacement_cleanup_pending',failure_code=NULL,
                      replacement_mime_type=NULL,replacement_size_bytes=NULL,
                      replacement_sha256=NULL,
                      prior_provider=?,prior_locator=?,cleanup_started_at=?
                WHERE id=?""",
            (
                titulo, str(descricao or "").strip() or None, _visibility(visivel),
                item.stored_filename, item.original_filename, remote.file_id, remote.parent_id,
                item.mime_type, item.size, item.sha256, item.uploaded_at, int(uploader_user_id),
                operation, prior_provider, prior_locator, _utc_now(), int(arquivo_id),
            ),
        )
        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        conn.execute(
            "UPDATE admin_arquivos SET failure_code='REPLACEMENT_ACTIVATION_PENDING' WHERE id=?",
            (int(arquivo_id),),
        )
        conn.commit()
        raise ArquivoError(
            "A substituição remota aguarda reconciliação.",
            code="REPLACEMENT_ACTIVATION_PENDING",
            retryable=True,
        ) from exc


def update_arquivo(
    conn,
    *,
    arquivo_id: int,
    file_storage,
    titulo: str,
    descricao: str | None,
    visivel: int,
    uploader_user_id: int,
    operation_key: str | None,
    max_file_bytes: int,
    upload_root: str,
) -> bool:
    row = conn.execute("SELECT * FROM admin_arquivos WHERE id=?", (int(arquivo_id),)).fetchone()
    if not row:
        raise ArquivoError("Arquivo não encontrado.", code="NOT_FOUND")
    titulo = str(titulo or "").strip()
    if not titulo:
        raise ArquivoError("Informe o nome do arquivo.", code="TITLE_REQUIRED")
    if not file_storage or not getattr(file_storage, "filename", ""):
        cleanup_ok = retry_arquivo_cleanup(conn, arquivo_id, upload_root=upload_root)
        _update_arquivo_metadata(
            conn,
            arquivo_id=arquivo_id,
            titulo=titulo,
            descricao=descricao,
            visivel=visivel,
        )
        return cleanup_ok

    operation = _bounded_operation_key(operation_key)
    item = prepare_arquivo(file_storage, operation_key=operation, max_file_bytes=max_file_bytes)
    if row["storage_status"] == "replacement_cleanup_pending":
        current_identity = (
            str(row["mime_type"] or ""),
            int(row["size_bytes"] or 0),
            str(row["sha256"] or ""),
        )
        if str(row["operation_key"] or "") == operation and current_identity == (
            item.mime_type,
            item.size,
            item.sha256,
        ):
            return retry_arquivo_cleanup(conn, arquivo_id, upload_root=upload_root)
        raise ArquivoError(
            "A limpeza da substituição anterior ainda está pendente.",
            code="CLEANUP_PENDING",
            retryable=True,
        )
    if not _reserve_replacement_operation(
        conn,
        row=row,
        arquivo_id=arquivo_id,
        operation=operation,
        item=item,
        titulo=titulo,
        descricao=descricao,
        visivel=visivel,
    ):
        return True
    try:
        storage = resolve_arquivo_storage(conn)
        parent_id = _ensure_arquivos_root(storage)
        remote = _upload_google_arquivo(
            storage,
            item,
            parent_id=parent_id,
            arquivo_id=arquivo_id,
            operation=operation,
        )
        _verify_remote(item, remote)
    except StorageError as exc:
        conn.execute(
            "UPDATE admin_arquivos SET failure_code=? WHERE id=?",
            (f"REPLACEMENT_UPLOAD_{exc.code}", int(arquivo_id)),
        )
        conn.commit()
        _raise_storage(exc)
    _promote_replacement(
        conn,
        row=row,
        arquivo_id=arquivo_id,
        item=item,
        remote=remote,
        operation=operation,
        titulo=titulo,
        descricao=descricao,
        visivel=visivel,
        uploader_user_id=uploader_user_id,
    )
    return retry_arquivo_cleanup(conn, arquivo_id, upload_root=upload_root)


def _delete_locatorless_google_row(conn, row) -> bool:
    arquivo_id = int(row["id"])
    uncertain = (
        row["storage_status"] == "reconciliation_required"
        or str(row["failure_code"] or "") == "UPLOAD_IN_PROGRESS"
    )
    if not uncertain:
        conn.execute("DELETE FROM admin_arquivos WHERE id=?", (arquivo_id,))
        conn.commit()
        return True
    parent_id = str(row["remote_parent_id"] or "")
    operation = str(row["operation_key"] or "")
    if not parent_id or not operation:
        raise ArquivoError(
            "A exclusão do arquivo aguarda reconciliação.",
            code="PENDING_CUSTODY_INVALID",
            retryable=True,
        )
    try:
        storage = resolve_arquivo_storage(conn)
        remote = storage.find_operation(
            parent_id=parent_id,
            operation_key=operation,
            object_kind="arquivo",
        )
    except StorageError as exc:
        conn.execute(
            """UPDATE admin_arquivos
                  SET storage_status='reconciliation_required',failure_code=?
                WHERE id=?""",
            (exc.code, arquivo_id),
        )
        conn.commit()
        _raise_storage(exc)
    if remote is None:
        conn.execute("DELETE FROM admin_arquivos WHERE id=?", (arquivo_id,))
        conn.commit()
        return True
    conn.execute(
        """UPDATE admin_arquivos
              SET remote_file_id=?,remote_parent_id=?,storage_status='deletion_pending',
                  failure_code=NULL,cleanup_started_at=?
            WHERE id=?""",
        (remote.file_id, remote.parent_id, _utc_now(), arquivo_id),
    )
    conn.commit()
    return False


def delete_arquivo(conn, arquivo_id: int, *, upload_root: str) -> None:
    row = conn.execute("SELECT * FROM admin_arquivos WHERE id=?", (int(arquivo_id),)).fetchone()
    if not row:
        raise ArquivoError("Arquivo não encontrado.", code="NOT_FOUND")
    if str(row["failure_code"] or "").startswith("REPLACEMENT_"):
        raise ArquivoError(
            "A substituição pendente deve ser reconciliada antes da exclusão.",
            code="REPLACEMENT_RETRY_REQUIRED",
            retryable=True,
        )
    if row["storage_status"] == "replacement_cleanup_pending":
        if not retry_arquivo_cleanup(conn, arquivo_id, upload_root=upload_root):
            raise ArquivoError("A limpeza da substituição anterior ainda está pendente.", code="CLEANUP_PENDING", retryable=True)
        row = conn.execute("SELECT * FROM admin_arquivos WHERE id=?", (int(arquivo_id),)).fetchone()
    if str(row["provider"]) == "google" and not str(row["remote_file_id"] or ""):
        if _delete_locatorless_google_row(conn, row):
            return
        row = conn.execute("SELECT * FROM admin_arquivos WHERE id=?", (int(arquivo_id),)).fetchone()
    if row["storage_status"] != "deletion_pending":
        conn.execute(
            "UPDATE admin_arquivos SET storage_status='deletion_pending',failure_code=NULL,cleanup_started_at=? WHERE id=?",
            (_utc_now(), int(arquivo_id)),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM admin_arquivos WHERE id=?", (int(arquivo_id),)).fetchone()
    provider = str(row["provider"])
    locator = str(row["remote_file_id"] if provider == "google" else row["filename"])
    try:
        storage = resolve_arquivo_storage(conn) if provider == "google" else None
        _cleanup_locator(storage, provider=provider, locator=locator, upload_root=upload_root)
    except (StorageError, ArquivoError) as exc:
        conn.execute(
            "UPDATE admin_arquivos SET failure_code=? WHERE id=?",
            (getattr(exc, "code", "DELETE_FAILED"), int(arquivo_id)),
        )
        conn.commit()
        if isinstance(exc, StorageError):
            _raise_storage(exc)
        raise
    try:
        conn.execute("DELETE FROM admin_arquivos WHERE id=?", (int(arquivo_id),))
        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        conn.execute(
            "UPDATE admin_arquivos SET failure_code='DELETE_DB_PENDING' WHERE id=?",
            (int(arquivo_id),),
        )
        conn.commit()
        raise ArquivoError(
            "A exclusão do arquivo aguarda reconciliação.",
            code="DELETE_DB_PENDING",
            retryable=True,
        ) from exc


def read_arquivo_content(conn, row, *, upload_root: str) -> tuple[bytes, str, str]:
    provider = str(row["provider"] or "local_legacy")
    original = str(row["original_filename"] or row["filename"] or "arquivo")
    download_name = secure_filename(original) or "arquivo"
    if provider == "local_legacy":
        try:
            path = resolve_student_document_path(upload_root, str(row["filename"]))
        except ValueError as exc:
            raise ArquivoError(
                "O caminho do arquivo local é inválido.", code="INVALID_LOCAL_PATH"
            ) from exc
        try:
            with open(path, "rb") as local_file:
                content = local_file.read()
        except FileNotFoundError as exc:
            raise ArquivoError("Arquivo não encontrado.", code="FILE_NOT_FOUND") from exc
        mime_type = MIME_BY_EXTENSION.get(download_name.rsplit(".", 1)[-1].lower()) or mimetypes.guess_type(download_name)[0]
        if mime_type not in set(MIME_BY_EXTENSION.values()):
            raise ArquivoError("Tipo de arquivo não suportado.", code="UNSUPPORTED_FILE_TYPE")
        return content, mime_type, download_name
    if provider != "google" or row["storage_status"] not in {"active", "replacement_cleanup_pending"}:
        raise ArquivoError("O arquivo ainda não está disponível.", code="STORAGE_NOT_ACTIVE", retryable=True)
    try:
        content = resolve_arquivo_storage(conn).download(str(row["remote_file_id"]))
    except StorageError as exc:
        _raise_storage(exc)
    if len(content) != int(row["size_bytes"] or -1) or hashlib.sha256(content).hexdigest() != str(row["sha256"] or ""):
        raise ArquivoError("O arquivo remoto falhou na verificação de integridade.", code="REMOTE_INTEGRITY_MISMATCH")
    return content, str(row["mime_type"]), download_name


__all__ = [
    "ArquivoError", "PreparedArquivo", "create_arquivo", "delete_arquivo",
    "new_arquivo_operation_id", "prepare_arquivo", "read_arquivo_content",
    "remove_legacy_arquivo_file", "resolve_arquivo_storage", "retry_arquivo_cleanup",
    "update_arquivo",
]
