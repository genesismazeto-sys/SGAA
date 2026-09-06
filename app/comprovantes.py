from __future__ import annotations

import datetime
import hashlib
import os
import re
import secrets
from dataclasses import dataclass
from typing import Callable

from flask import current_app
import app.cloud_connections as cloud_connections
from app.admin_access import _admin_can, _load_admin_access_context
from app.comprovante_file_validation import MIME_BY_EXTENSION, detect_supported_mime
from app.comprovante_hierarchy import ensure_request_hierarchy, stored_filename
from app.requisition_policy import (
    can_student_delete_requisition,
    can_student_edit_requisition,
)
from app.storage.contracts import (
    ComprovanteStorage,
    RemoteObject,
    StorageAuthorizationError,
    StorageConfigurationError,
    StorageError,
    StorageIntegrityError,
)
from app.storage.google_drive import GoogleDriveComprovanteStorage
from app.student_documents import resolve_student_document_path
from app.versioning.snapshots import (
    SnapshotProcessingAuthority,
    read_requisicao_snapshot_for_processing,
)


DEFAULT_MAX_FILE_BYTES = 16 * 1024 * 1024


class ComprovanteError(RuntimeError):
    def __init__(
        self,
        user_message: str,
        *,
        code: str = "COMPROVANTE_ERROR",
        retryable: bool = False,
        reconciliation_required: bool = False,
    ):
        super().__init__(user_message)
        self.user_message = user_message
        self.code = code
        self.retryable = retryable
        self.reconciliation_required = reconciliation_required


@dataclass(frozen=True)
class RequestTurmaSnapshot:
    turma_id: int
    turma_codigo: str


@dataclass(frozen=True)
class PreparedComprovante:
    original_filename: str
    extension: str
    mime_type: str
    content: bytes
    size: int
    sha256: str
    label: str | None
    operation_key: str
    uploaded_at: str


def _utc_now() -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def new_comprovante_operation_id() -> str:
    return secrets.token_urlsafe(24)


def _original_basename(value: str) -> str:
    return str(value or "").replace("\\", "/").rsplit("/", 1)[-1].strip()[:255]


def prepare_comprovante_batch(
    files,
    *,
    labels=None,
    batch_key: str | None = None,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> list[PreparedComprovante]:
    """Read and validate the complete selected batch before any provider call."""
    selected = [item for item in (files or []) if item and getattr(item, "filename", "")]
    if not selected:
        return []
    # Drive appProperties values are limited to 124 bytes; keep the derived key
    # bounded after adding the item index and content discriminator.
    normalized_batch_key = re.sub(r"[^A-Za-z0-9_.:-]", "-", str(batch_key or ""))[:72]
    if not normalized_batch_key:
        normalized_batch_key = secrets.token_urlsafe(24)
    normalized_labels = list(labels or [])
    prepared: list[PreparedComprovante] = []
    timestamp = _utc_now()
    for index, file_storage in enumerate(selected):
        original = _original_basename(file_storage.filename)
        extension = original.rsplit(".", 1)[-1].lower() if "." in original else ""
        expected_mime = MIME_BY_EXTENSION.get(extension)
        if not expected_mime:
            raise ComprovanteError(
                "Envie somente arquivos PDF, PNG ou JPEG.", code="UNSUPPORTED_FILE_TYPE"
            )
        stream = getattr(file_storage, "stream", file_storage)
        content = stream.read(int(max_file_bytes) + 1)
        try:
            stream.seek(0)
        except (AttributeError, OSError):
            pass
        if len(content) > int(max_file_bytes):
            raise ComprovanteError(
                "Um dos comprovantes excede o limite técnico de 16 MiB.",
                code="FILE_TOO_LARGE",
            )
        actual_mime = detect_supported_mime(content)
        if actual_mime is None:
            raise ComprovanteError(
                "Um dos comprovantes está vazio ou malformado.", code="MALFORMED_FILE"
            )
        if actual_mime != expected_mime:
            raise ComprovanteError(
                "A extensão de um comprovante não corresponde ao conteúdo do arquivo.",
                code="MIME_MISMATCH",
            )
        digest = hashlib.sha256(content).hexdigest()
        operation_key = f"{normalized_batch_key}:{index}:{digest[:16]}"
        prepared.append(
            PreparedComprovante(
                original_filename=original,
                extension=extension,
                mime_type=actual_mime,
                content=content,
                size=len(content),
                sha256=digest,
                label=(normalized_labels[index] if index < len(normalized_labels) else None),
                operation_key=operation_key,
                uploaded_at=timestamp,
            )
        )
    return prepared


def capture_student_turma_snapshot(conn, aluno_id: int) -> RequestTurmaSnapshot:
    row = conn.execute(
        """SELECT a.turma_id,t.codigo
             FROM alunos a
             JOIN turmas t ON t.id=a.turma_id
            WHERE a.id=?""",
        (int(aluno_id),),
    ).fetchone()
    if not row or row["turma_id"] is None or not str(row["codigo"] or "").strip():
        raise ComprovanteError(
            "O aluno precisa estar vinculado a uma turma válida.", code="TURMA_REQUIRED"
        )
    return RequestTurmaSnapshot(int(row["turma_id"]), str(row["codigo"]).strip())


def find_completed_request_retry(
    conn, *, aluno_id: int, batch: list[PreparedComprovante]
) -> int | None:
    """Resolve a replayed create operation without creating a second request."""
    if not batch:
        return None
    matches = []
    for item in batch:
        row = conn.execute(
            """SELECT ra.requisicao_id,ra.sha256,ra.storage_status,r.aluno_id
                 FROM requisicao_arquivos ra
                 JOIN requisicoes r ON r.id=ra.requisicao_id
                WHERE ra.operation_key=?""",
            (item.operation_key,),
        ).fetchone()
        if row:
            matches.append((row, item))
    if not matches:
        return None
    if len(matches) != len(batch):
        raise ComprovanteError(
            "A operação anterior ainda não foi concluída.",
            code="OPERATION_RETRY_INCOMPLETE",
            retryable=True,
        )
    request_ids = {int(row["requisicao_id"]) for row, _item in matches}
    coherent = (
        len(request_ids) == 1
        and all(int(row["aluno_id"]) == int(aluno_id) for row, _item in matches)
        and all(str(row["sha256"] or "") == item.sha256 for row, item in matches)
        and all(row["storage_status"] == "active" for row, _item in matches)
    )
    if not coherent:
        raise ComprovanteError(
            "A identidade da operação não corresponde à requisição enviada.",
            code="OPERATION_KEY_CONFLICT",
        )
    return request_ids.pop()


def resolve_google_storage(conn) -> ComprovanteStorage:
    override = current_app.extensions.get("comprovante_storage")
    if override is not None:
        return override(conn) if callable(override) else override
    try:
        access_token, _identity = cloud_connections.get_authenticated_access_token(conn, "google")
    except cloud_connections.CloudConnectionError as exc:
        if exc.debug_code == "AUTH_RECONNECT_REQUIRED":
            raise StorageAuthorizationError(
                "A autorização do Google Drive precisa ser renovada."
            ) from exc
        if exc.debug_code.startswith("APPLICATION_CREDENTIAL"):
            raise StorageConfigurationError(
                "As credenciais do aplicativo Google não estão configuradas corretamente."
            ) from exc
        raise StorageError("Não foi possível acessar o Google Drive.") from exc
    def recover_access_token() -> str:
        try:
            recovered, _identity = (
                cloud_connections.recover_authenticated_access_token_after_401(
                    conn, "google"
                )
            )
            return recovered
        except cloud_connections.CloudConnectionError as exc:
            if exc.debug_code == "AUTH_RECONNECT_REQUIRED":
                raise StorageAuthorizationError(
                    "A autorização do Google Drive precisa ser renovada."
                ) from exc
            if exc.debug_code.startswith("APPLICATION_CREDENTIAL"):
                raise StorageConfigurationError(
                    "As credenciais do aplicativo Google não estão configuradas corretamente."
                ) from exc
            raise StorageError("Não foi possível renovar o acesso ao Google Drive.") from exc

    return GoogleDriveComprovanteStorage(
        access_token, access_token_refresher=recover_access_token
    )


def handle_storage_authorization_failure(conn, exc: Exception) -> None:
    # Durable revocation is owned exclusively by the canonical refresh lifecycle.
    return None


def authorize_request_comprovante_actor(
    conn, *, request_id: int, actor_user_id: int, admin_scope: str
) -> str:
    actor = conn.execute(
        "SELECT id,tipo FROM usuarios WHERE id=?", (int(actor_user_id),)
    ).fetchone()
    if not actor:
        raise ComprovanteError("Acesso negado.", code="ACCESS_DENIED")
    actor_type = str(actor["tipo"] or "").strip().lower()
    if actor_type == "aluno":
        owns = conn.execute(
            """SELECT 1 FROM requisicoes r
                 JOIN alunos a ON a.id=r.aluno_id
                WHERE r.id=? AND a.usuario_id=?""",
            (int(request_id), int(actor_user_id)),
        ).fetchone()
        if owns:
            return actor_type
    elif actor_type == "admin":
        context = _load_admin_access_context(conn, int(actor_user_id))
        if _admin_can("requisicoes", admin_scope, context):
            return actor_type
    raise ComprovanteError("Acesso negado.", code="ACCESS_DENIED")


def _request_context(conn, request_id: int):
    row = conn.execute(
        """SELECT r.*,a.nome AS aluno_nome,a.matricula AS aluno_matricula,
                  a.turma_id AS aluno_turma_id,t.codigo AS aluno_turma_codigo
             FROM requisicoes r
             JOIN alunos a ON a.id=r.aluno_id
        LEFT JOIN turmas t ON t.id=a.turma_id
            WHERE r.id=?""",
        (int(request_id),),
    ).fetchone()
    if not row:
        raise ComprovanteError("Requisição não encontrada.", code="REQUEST_NOT_FOUND")
    snapshot = read_requisicao_snapshot_for_processing(row)
    if snapshot.authority is not SnapshotProcessingAuthority.VALID_AUTHORITATIVE_SNAPSHOT:
        raise ComprovanteError(
            "O registro histórico da requisição está indisponível.", code="INVALID_REQUEST_SNAPSHOT"
        )
    turma_id = row["turma_id_snapshot"]
    turma_code = row["turma_codigo_snapshot"]
    if turma_id is None and turma_code is None:
        frozen = capture_student_turma_snapshot(conn, int(row["aluno_id"]))
        conn.execute(
            "UPDATE requisicoes SET turma_id_snapshot=?,turma_codigo_snapshot=? WHERE id=?",
            (frozen.turma_id, frozen.turma_codigo, int(request_id)),
        )
        turma_id, turma_code = frozen.turma_id, frozen.turma_codigo
    if turma_id is None or not str(turma_code or "").strip():
        raise ComprovanteError(
            "A requisição não possui contexto de turma válido.", code="TURMA_SNAPSHOT_INVALID"
        )
    return row, snapshot.payload or {}, int(turma_id), str(turma_code).strip()


def _mark_batch_failure(
    conn,
    attachment_ids: list[int],
    code: str,
    reconciliation: set[int],
    uploaded: list[tuple[int, RemoteObject, str]],
):
    remote_evidence = {attachment_id: (remote, uploaded_at) for attachment_id, remote, uploaded_at in uploaded}
    for attachment_id in attachment_ids:
        status = "reconciliation_required" if attachment_id in reconciliation else "failed"
        evidence = remote_evidence.get(attachment_id)
        if evidence:
            remote, uploaded_at = evidence
            conn.execute(
                """UPDATE requisicao_arquivos
                      SET remote_file_id=?,remote_parent_id=?,uploaded_at=?,
                          storage_status=?,failure_code=?
                    WHERE id=?""",
                (
                    remote.file_id, remote.parent_id, uploaded_at,
                    status, str(code)[:80], int(attachment_id),
                ),
            )
        else:
            conn.execute(
                "UPDATE requisicao_arquivos SET storage_status=?,failure_code=? WHERE id=?",
                (status, str(code)[:80], int(attachment_id)),
            )
    conn.commit()


def _compensate(
    storage: ComprovanteStorage, uploaded: list[tuple[int, RemoteObject, str]]
) -> set[int]:
    failed: set[int] = set()
    for attachment_id, remote, _uploaded_at in reversed(uploaded):
        try:
            storage.trash(remote.file_id)
        except Exception:
            failed.add(int(attachment_id))
    return failed


def _preflight_existing_operations(conn, request_id: int, batch):
    existing_by_key = {}
    for item in batch:
        existing = conn.execute(
            "SELECT * FROM requisicao_arquivos WHERE operation_key=?",
            (item.operation_key,),
        ).fetchone()
        if not existing:
            continue
        if (
            int(existing["requisicao_id"]) != int(request_id)
            or str(existing["sha256"] or "") != item.sha256
        ):
            raise ComprovanteError(
                "A identidade da operação já pertence a outro comprovante.",
                code="OPERATION_KEY_CONFLICT",
            )
        existing_by_key[item.operation_key] = existing
    active = [row for row in existing_by_key.values() if row["storage_status"] == "active"]
    if active and len(active) != len(batch):
        raise ComprovanteError(
            "A operação anterior está em estado parcial inconsistente.",
            code="OPERATION_RETRY_INCOMPLETE",
            retryable=True,
        )
    completed = (
        [dict(existing_by_key[item.operation_key]) for item in batch]
        if len(active) == len(batch)
        else None
    )
    return existing_by_key, completed


def _authorize_comprovante_upload(conn, request_id: int, actor_user_id: int) -> None:
    actor_type = authorize_request_comprovante_actor(
        conn,
        request_id=request_id,
        actor_user_id=actor_user_id,
        admin_scope="edit",
    )
    state = conn.execute(
        "SELECT status,data_processamento FROM requisicoes WHERE id=?", (request_id,)
    ).fetchone()
    student_allowed = bool(
        state
        and actor_type == "aluno"
        and can_student_edit_requisition(state["status"], state["data_processamento"])
    )
    admin_allowed = bool(
        state and actor_type == "admin" and state["status"] == "Pendente"
    )
    if not student_allowed and not admin_allowed:
        raise ComprovanteError("A requisição não pode receber comprovantes.", code="EDIT_DENIED")


def upload_comprovantes(
    conn,
    *,
    request_id: int,
    uploader_user_id: int,
    batch: list[PreparedComprovante],
    storage: ComprovanteStorage | None = None,
    finalize_db: Callable[[], object] | None = None,
) -> list[dict]:
    if not batch:
        return []
    _authorize_comprovante_upload(conn, int(request_id), int(uploader_user_id))
    existing_by_key, completed = _preflight_existing_operations(conn, request_id, batch)
    if completed is not None:
        return completed
    storage = storage or resolve_google_storage(conn)
    request_row, snapshot_payload, turma_id, turma_code = _request_context(conn, request_id)
    pending: list[tuple[int, PreparedComprovante, str]] = []
    try:
        for item in batch:
            existing = existing_by_key.get(item.operation_key)
            if existing:
                attachment_id = int(existing["id"])
                stored_name = str(existing["filename"])
                conn.execute(
                    """UPDATE requisicao_arquivos
                          SET storage_status='pending',failure_code=NULL,label=?,original_filename=?,
                              mime_type=?,size_bytes=?,sha256=?,uploader_user_id=?
                        WHERE id=?""",
                    (
                        item.label,
                        item.original_filename,
                        item.mime_type,
                        item.size,
                        item.sha256,
                        int(uploader_user_id),
                        attachment_id,
                    ),
                )
            else:
                stored_name = stored_filename(request_id, snapshot_payload, item)
                cursor = conn.execute(
                    """INSERT INTO requisicao_arquivos (
                           requisicao_id,label,filename,provider,original_filename,mime_type,
                           size_bytes,sha256,uploader_user_id,operation_key,storage_status)
                       VALUES (?,?,?,'google',?,?,?,?,?,?,'pending')""",
                    (
                        int(request_id), item.label, stored_name, item.original_filename,
                        item.mime_type, item.size, item.sha256, int(uploader_user_id),
                        item.operation_key,
                    ),
                )
                attachment_id = int(cursor.lastrowid)
            pending.append((attachment_id, item, stored_name))
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    uploaded: list[tuple[int, RemoteObject, str]] = []
    attachment_ids = [item[0] for item in pending]
    try:
        parent_id = ensure_request_hierarchy(
            storage,
            request_row=request_row,
            snapshot_payload=snapshot_payload,
            turma_id=turma_id,
            turma_code=turma_code,
        )
        for attachment_id, item, stored_name in pending:
            remote = storage.upload(
                parent_id=parent_id,
                stored_filename=stored_name,
                content=item.content,
                mime_type=item.mime_type,
                operation_key=item.operation_key,
                request_id=int(request_id),
                attachment_id=attachment_id,
            )
            uploaded.append((attachment_id, remote, item.uploaded_at))
            if not remote.file_id or remote.parent_id != parent_id:
                raise StorageIntegrityError("O Google Drive retornou custódia remota inválida.")
            conn.execute(
                """UPDATE requisicao_arquivos
                      SET remote_file_id=?,remote_parent_id=?,uploaded_at=?,
                          storage_status='uploaded',failure_code=NULL
                    WHERE id=?""",
                (remote.file_id, remote.parent_id, item.uploaded_at, attachment_id),
            )
            conn.commit()
            if (
                remote.size != item.size
                or not remote.sha256
                or remote.sha256.lower() != item.sha256
            ):
                raise StorageIntegrityError("O Google Drive retornou conteúdo divergente.")
        if finalize_db is not None:
            finalize_db()
        conn.execute(
            f"UPDATE requisicao_arquivos SET storage_status='active',failure_code=NULL "
            f"WHERE id IN ({','.join('?' for _ in attachment_ids)})",
            attachment_ids,
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        reconciliation = _compensate(storage, uploaded)
        try:
            _mark_batch_failure(
                conn,
                attachment_ids,
                getattr(exc, "code", "UPLOAD_FAILED"),
                reconciliation,
                uploaded,
            )
        except Exception:
            conn.rollback()
            reconciliation.update(attachment_ids)
        handle_storage_authorization_failure(conn, exc)
        raise ComprovanteError(
            "Não foi possível armazenar os comprovantes com segurança.",
            code=getattr(exc, "code", "UPLOAD_FAILED"),
            retryable=bool(getattr(exc, "retryable", False)),
            reconciliation_required=bool(reconciliation),
        ) from exc
    rows = conn.execute(
        f"SELECT * FROM requisicao_arquivos WHERE id IN ({','.join('?' for _ in attachment_ids)}) ORDER BY id",
        attachment_ids,
    ).fetchall()
    return [dict(row) for row in rows]


def _restore_trashed(storage: ComprovanteStorage, file_ids: list[str]) -> set[str]:
    failed: set[str] = set()
    for file_id in reversed(file_ids):
        try:
            storage.untrash(file_id)
        except Exception:
            failed.add(file_id)
    return failed


def _begin_delete_intent(conn, request_id: int) -> list:
    started_at = _utc_now()
    conn.execute(
        """UPDATE requisicao_arquivos
              SET delete_previous_status=storage_status,
                  delete_started_at=?,storage_status='deletion_pending',failure_code=NULL
            WHERE requisicao_id=? AND provider='google' AND remote_file_id IS NOT NULL
              AND storage_status NOT IN ('deletion_pending','trashed')""",
        (started_at, int(request_id)),
    )
    conn.commit()
    return conn.execute(
        """SELECT * FROM requisicao_arquivos
            WHERE requisicao_id=? AND provider='google' AND remote_file_id IS NOT NULL
         ORDER BY id""",
        (int(request_id),),
    ).fetchall()


def _restore_delete_intent(conn, storage: ComprovanteStorage, rows) -> set[str]:
    failed: set[str] = set()
    for row in reversed(rows):
        file_id = str(row["remote_file_id"] or "")
        if not file_id:
            continue
        try:
            storage.untrash(file_id)
        except Exception:
            failed.add(file_id)
    for row in rows:
        file_id = str(row["remote_file_id"] or "")
        if file_id in failed:
            conn.execute(
                """UPDATE requisicao_arquivos
                      SET storage_status='reconciliation_required',
                          failure_code='REMOTE_RESTORE_FAILED'
                    WHERE id=?""",
                (int(row["id"]),),
            )
        else:
            previous = str(row["delete_previous_status"] or "active")
            conn.execute(
                """UPDATE requisicao_arquivos
                      SET storage_status=?,failure_code=NULL,
                          delete_previous_status=NULL,delete_started_at=NULL
                    WHERE id=?""",
                (previous, int(row["id"])),
            )
    conn.commit()
    return failed


def _mark_remote_reconciliation(conn, file_ids: set[str], code: str) -> None:
    if not file_ids:
        return
    placeholders = ",".join("?" for _ in file_ids)
    conn.execute(
        f"""UPDATE requisicao_arquivos
               SET storage_status='reconciliation_required',failure_code=?
             WHERE provider='google' AND remote_file_id IN ({placeholders})""",
        (code, *sorted(file_ids)),
    )
    conn.commit()


def _remove_legacy_files(rows, roots) -> None:
    removed: set[str] = set()
    for row in rows:
        if row["provider"] != "local_legacy" or not row["filename"]:
            continue
        filename = str(row["filename"])
        if filename in removed:
            continue
        removed.add(filename)
        for root in roots:
            if not root:
                continue
            try:
                candidate = resolve_student_document_path(str(root), filename)
            except ValueError:
                continue
            if os.path.isfile(candidate):
                try:
                    os.remove(candidate)
                except OSError:
                    pass
                break


def delete_request_with_comprovantes(
    conn,
    *,
    request_id: int,
    actor_user_id: int,
    storage: ComprovanteStorage | None = None,
) -> None:
    query = "SELECT id FROM requisicoes WHERE id=?"
    params: tuple[object, ...] = (int(request_id),)
    if not conn.execute(query, params).fetchone():
        raise ComprovanteError("Requisição não encontrada.", code="REQUEST_NOT_FOUND")
    actor_type = authorize_request_comprovante_actor(
        conn,
        request_id=int(request_id),
        actor_user_id=int(actor_user_id),
        admin_scope="full",
    )
    if actor_type == "aluno":
        state = conn.execute(
            "SELECT status,data_processamento FROM requisicoes WHERE id=?",
            (int(request_id),),
        ).fetchone()
        if not state or not can_student_delete_requisition(
            state["status"], state["data_processamento"]
        ):
            raise ComprovanteError("A requisição não pode ser excluída.", code="DELETE_DENIED")
    rows = conn.execute(
        "SELECT * FROM requisicao_arquivos WHERE requisicao_id=? ORDER BY id",
        (int(request_id),),
    ).fetchall()
    uncertain = [
        row for row in rows
        if row["provider"] == "google"
        and row["storage_status"] in {"pending", "uploaded", "reconciliation_required"}
        and not row["remote_file_id"]
    ]
    if uncertain:
        raise ComprovanteError(
            "A requisição possui custódia remota pendente de reconciliação.",
            code="REMOTE_ID_RECONCILIATION_REQUIRED",
            reconciliation_required=True,
        )
    google_rows = [
        row for row in rows if row["provider"] == "google" and row["remote_file_id"]
    ]
    if google_rows:
        storage = storage or resolve_google_storage(conn)
    delete_rows = _begin_delete_intent(conn, int(request_id)) if google_rows else []
    try:
        for row in delete_rows:
            if row["storage_status"] == "trashed":
                continue
            remote_id = str(row["remote_file_id"] or "")
            if not remote_id:
                raise StorageIntegrityError("Comprovante ativo sem identidade remota.")
            storage.trash(remote_id)  # type: ignore[union-attr]
            conn.execute(
                """UPDATE requisicao_arquivos
                      SET storage_status='trashed',failure_code=NULL
                    WHERE id=?""",
                (int(row["id"]),),
            )
            conn.commit()
    except Exception as exc:
        restore_failed = (
            _restore_delete_intent(conn, storage, delete_rows)
            if storage and delete_rows
            else set()
        )
        try:
            _mark_remote_reconciliation(conn, restore_failed, "REMOTE_RESTORE_FAILED")
        except Exception:
            conn.rollback()
        handle_storage_authorization_failure(conn, exc)
        raise ComprovanteError(
            "Não foi possível remover os comprovantes do Google Drive; a requisição foi preservada.",
            code=getattr(exc, "code", "REMOTE_TRASH_FAILED"),
            reconciliation_required=bool(restore_failed),
        ) from exc
    try:
        cursor = conn.execute(query.replace("SELECT id", "DELETE"), params)
        if cursor.rowcount != 1:
            raise ComprovanteError("Requisição não encontrada.", code="REQUEST_NOT_FOUND")
        conn.commit()
    except Exception as exc:
        conn.rollback()
        restore_failed = (
            _restore_delete_intent(conn, storage, delete_rows)
            if storage and delete_rows
            else set()
        )
        try:
            _mark_remote_reconciliation(conn, restore_failed, "REMOTE_RESTORE_FAILED")
        except Exception:
            conn.rollback()
        raise ComprovanteError(
            "O banco recusou a exclusão; a restauração remota foi tentada.",
            code="DB_DELETE_FAILED",
            reconciliation_required=bool(restore_failed),
        ) from exc
    _remove_legacy_files(
        rows,
        (
            current_app.config.get("DOCUMENTOS_ALUNOS_FOLDER"),
            current_app.config.get("UPLOAD_FOLDER"),
        ),
    )


__all__ = [
    "ComprovanteError",
    "PreparedComprovante",
    "RequestTurmaSnapshot",
    "authorize_request_comprovante_actor",
    "capture_student_turma_snapshot",
    "delete_request_with_comprovantes",
    "find_completed_request_retry",
    "handle_storage_authorization_failure",
    "new_comprovante_operation_id",
    "prepare_comprovante_batch",
    "resolve_google_storage",
    "upload_comprovantes",
]
