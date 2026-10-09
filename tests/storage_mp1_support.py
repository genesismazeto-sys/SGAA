"""Shared MP-1 (storage convergence) fixtures -- TEST ONLY.

Engine-neutral seeders (``?`` placeholders: SQLite, and PostgreSQL through
``app.db._PostgresConnectionAdapter``), a deterministic fake of the managed
Google Drive storage with the ``appProperties`` semantics the mirror relies on,
and a controllable clock.  Every person-like value is synthetic.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import threading
from types import SimpleNamespace

from app.storage.contracts import RemoteObject, StorageError
from tests.canonical_store_fake import InMemoryObjectStore

BUCKET = "sgaa-documentos"
ACCOUNT_KEY = "a1" * 32
OTHER_ACCOUNT_KEY = "b2" * 32
T0 = "2026-10-09 12:00:00"
ADMIN_ID = 1
STUDENT_USER_ID = 2
STUDENT_ID = 1
REQUEST_ID = 1
TURMA_ID = 1


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def request_snapshot(axis: str = "AAC") -> str:
    return json.dumps(
        {
            "atividade_base_id": 1, "atividade_versao_id": 1, "atividade_versao_numero": 1, "eixo": axis,
            "matriz_id_efetiva": 1, "schema_version": "prod-1-request-v2", "ch_por_evento": None,
            "limite_semestre": None, "limite_total": None, "nome_exibivel": "Conceito",
            "tipo_atividade": "Acadêmica Complementar", "grupo": "1", "documentos_json": "[]",
        },
        ensure_ascii=False,
    )


#: A minimal business dataset: one admin, one student in one turma, one request
#: (frozen turma snapshot, valid processing snapshot), one active Google
#: connection bound to ``ACCOUNT_KEY``.
SEED_SQL = (
    ("INSERT INTO cursos(id,nome,codigo,duracao_periodos) VALUES(1,'Curso','CUR',8)", ()),
    ("INSERT INTO matrizes_atividades(id,curso_id,nome) VALUES(1,1,'Matriz')", ()),
    ("INSERT INTO turmas(id,nome,numero,curso_id,ano_inicio,semestre_inicio,codigo,matriz_id)"
     " VALUES(1,'Turma 1',1,1,2026,1,'T-2026-1',1)", ()),
    ("INSERT INTO usuarios(id,nome,email,senha,tipo) VALUES(1,'Admin','mp1.admin@example.test','x','admin')", ()),
    ("INSERT INTO usuarios(id,nome,email,senha,tipo) VALUES(2,'Aluno','mp1.aluno@example.test','x','aluno')", ()),
    ("INSERT INTO alunos(id,usuario_id,nome,matricula,email,turma_id)"
     " VALUES(1,2,'Aluno Sintetico','MAT-1','mp1.aluno@example.test',1)", ()),
    ("INSERT INTO atividade_base(id,nome_conceito) VALUES(1,'Conceito')", ()),
    ("INSERT INTO atividade_versao(id,atividade_base_id,eixo,numero_versao,status) VALUES(1,1,'AAC',1,'ativa')", ()),
    ("INSERT INTO requisicoes(id,aluno_id,atividade_versao_id,data_solicitacao,data_evento,horas_solicitadas,"
     "status,regra_snapshot_json,turma_id_snapshot,turma_codigo_snapshot)"
     " VALUES(1,1,1,'2026-09-05','2026-09-05',2,'Pendente',?,1,'T-2026-1')", (request_snapshot(),)),
    ("INSERT INTO cloud_accounts(id,provider,token_json,active,provider_account_key) VALUES(1,'google','{}',1,?)",
     (ACCOUNT_KEY,)),
)

#: Tables whose identity the PostgreSQL template advances past the seeded ids.
SEEDED_TABLES = ("cursos", "matrizes_atividades", "turmas", "usuarios", "alunos", "atividade_base",
                 "atividade_versao", "requisicoes", "cloud_accounts")


def seed_business(conn) -> None:
    for sql, params in SEED_SQL:
        conn.execute(sql, params)


def insert_object(conn, *, key: str, content: bytes, mime: str = "application/pdf", now: str = T0,
                  origin: str = "direct_upload", uploader: int | None = ADMIN_ID, **drive) -> int:
    columns = {
        "storage_backend": "supabase", "storage_bucket": BUCKET, "storage_key": key, "sha256": sha256(content),
        "size_bytes": len(content), "mime_type": mime, "uploader_user_id": uploader, "origin": origin,
        "content_verified_at": now, "created_at": now, **drive,
    }
    names = ",".join(columns)
    marks = ",".join("?" for _ in columns)
    return int(conn.execute(
        f"INSERT INTO storage_objects({names}) VALUES({marks}) RETURNING id", tuple(columns.values())
    ).fetchone()[0])


def seed_canonical_request_document(conn, store, *, key: str, content: bytes, mime: str = "application/pdf",
                                    operation_key: str = "sub:slot", filename: str = "REQ-000001__Conceito.pdf",
                                    now: str = T0, request_id: int = REQUEST_ID) -> tuple[int, int]:
    """A committed-shape canonical comprovante + its object (the fake store holds the bytes)."""
    object_id = insert_object(conn, key=key, content=content, mime=mime, now=now)
    row_id = int(conn.execute(
        "INSERT INTO requisicao_arquivos(requisicao_id,filename,provider,storage_status,original_filename,"
        "mime_type,size_bytes,sha256,uploaded_at,uploader_user_id,operation_key,storage_object_id)"
        " VALUES(?,?,'supabase','active','prova.pdf',?,?,?,?,?,?,?) RETURNING id",
        (request_id, filename, mime, len(content), sha256(content), "2026-10-09T12:00:00Z", ADMIN_ID,
         operation_key, object_id),
    ).fetchone()[0])
    if store is not None:
        store.objects[(BUCKET, key)] = (content, mime)
    return row_id, object_id


def seed_canonical_arquivo(conn, store, *, key: str, content: bytes, mime: str = "application/pdf",
                           operation_key: str = "arq:slot", filename: str = "ARQ-abc-manual.pdf",
                           now: str = T0) -> tuple[int, int]:
    object_id = insert_object(conn, key=key, content=content, mime=mime, now=now)
    row_id = int(conn.execute(
        "INSERT INTO admin_arquivos(titulo,filename,original_filename,visivel,provider,mime_type,size_bytes,"
        "sha256,uploaded_at,uploader_user_id,operation_key,storage_status,storage_object_id)"
        " VALUES('Manual',?,'manual.pdf',1,'supabase',?,?,?,?,?,?,'active',?) RETURNING id",
        (filename, mime, len(content), sha256(content), now, ADMIN_ID, operation_key, object_id),
    ).fetchone()[0])
    if store is not None:
        store.objects[(BUCKET, key)] = (content, mime)
    return row_id, object_id


def object_state(conn, object_id: int) -> dict:
    row = conn.execute(
        "SELECT drive_sync_state, drive_file_id, drive_parent_id, drive_account_key, drive_attempts,"
        " drive_last_error_code, drive_next_attempt_at, lease_token, lifecycle_state FROM storage_objects WHERE id=?",
        (int(object_id),),
    ).fetchone()
    keys = ("state", "file_id", "parent_id", "account_key", "attempts", "error", "next_attempt", "lease",
            "lifecycle")
    return dict(zip(keys, tuple(row)))


@contextlib.contextmanager
def sqlite_storage_env(tmp_path, monkeypatch, *, drive=None, store=None):
    """A seeded file-backed SQLite v15 database behind ``app.db.get_db_connection``,
    a bare Flask app context carrying the canonical-store and Drive fakes, and
    the custody clock pinned to ``T0``."""
    import sqlite3

    from flask import Flask

    import app.db as app_db
    from app.prod1_schema import bootstrap_prod1_schema
    from app.storage import custody_common
    from app.storage.drive_mirror import DRIVE_STORAGE_EXTENSION
    from tests.canonical_store_fake import InMemoryObjectStore

    database = tmp_path / "mp1-storage.db"
    raw = sqlite3.connect(database)
    raw.execute("PRAGMA foreign_keys=ON")
    bootstrap_prod1_schema(raw)
    seed_business(raw)
    raw.commit()
    raw.close()
    monkeypatch.setattr(app_db, "DATABASE", str(database))
    flask_app = Flask("mp1_storage_tests")
    flask_app.config["TESTING"] = True
    store = InMemoryObjectStore() if store is None else store
    drive = FakeDrive() if drive is None else drive
    flask_app.extensions["canonical_object_store"] = store
    flask_app.extensions[DRIVE_STORAGE_EXTENSION] = drive
    clock = Clock(T0)
    monkeypatch.setattr(custody_common, "utc_now_text", clock)
    with flask_app.app_context():
        conn = app_db.get_db_connection()
        try:
            yield SimpleNamespace(app=flask_app, conn=conn, store=store, drive=drive, clock=clock,
                                  database=database, tmp_path=tmp_path)
        finally:
            app_db.close_db_connection(None)


class Clock:
    def __init__(self, now: str = T0) -> None:
        self.now = now

    def __call__(self) -> str:
        return self.now

    def advance(self, seconds: int) -> None:
        from app.storage.custody_common import add_seconds

        self.now = add_seconds(self.now, seconds)


class Tripwire(BaseException):
    """A forbidden provider mutation was attempted.

    A ``BaseException`` on purpose: no ``except Exception`` in the code under
    test (the mirror's per-item isolation, for one) can swallow it, and the
    double records the call BEFORE raising, so a test sees the attempt either way.
    """


class DriveTouched(Tripwire):
    """A forbidden Drive mutation was attempted."""


class GuardedStore(InMemoryObjectStore):
    """The canonical fake with every write / delete as a recording tripwire (I2)."""

    def _forbidden(self, name):
        self.calls.append(name)
        raise Tripwire(f"canonical {name}")

    def upload(self, *args, **kwargs):
        self._forbidden("upload")

    def delete(self, *args, **kwargs):
        self._forbidden("delete")

    def create_signed_upload(self, *args, **kwargs):
        self._forbidden("create_signed_upload")


class FakeDrive:
    """Managed Drive storage double with the production ``appProperties`` semantics.

    * ``ensure_folder`` is idempotent per (parent, kind, semantic id);
    * ``upload`` first finds a non-trashed file of the same parent, kind and
      ``sgaaOperation`` (reuse), else creates one; ``find_operation`` likewise;
    * ``trash`` / ``untrash`` / ``delete`` are tripwires unless ``allow_trash``;
    * ``fail_next(method, exc)`` raises ``exc`` on the next call of ``method``;
    * ``corrupt_next_upload`` makes the next created file report a wrong SHA-256.
    """

    provider = "google"

    def __init__(self, *, allow_trash: bool = False) -> None:
        self.folders: dict[tuple[str, str, str], str] = {}
        self.files: dict[str, dict] = {}
        self.calls: list[str] = []
        self.allow_trash = allow_trash
        self._failures: dict[str, list[BaseException]] = {}
        self.corrupt_next_upload = False
        # Concurrent workers (E-PG2) share one fake: find-or-create is atomic here
        # exactly as Drive's own uniqueness is per operation.
        self._lock = threading.RLock()

    def fail_next(self, method: str, exc: BaseException) -> None:
        self._failures.setdefault(method, []).append(exc)

    def _enter(self, method: str) -> None:
        with self._lock:
            self.calls.append(method)
            queued = self._failures.get(method)
            if queued:
                raise queued.pop(0)

    def ensure_folder(self, *, parent_id, kind, semantic_id, display_name):
        self._enter("ensure_folder")
        key = (str(parent_id), str(kind), str(semantic_id))
        with self._lock:
            return self.folders.setdefault(key, f"folder-{len(self.folders) + 1}")

    def _matches(self, parent_id, operation_key, object_kind):
        return [
            item for item in self.files.values()
            if not item["trashed"] and item["parent_id"] == parent_id
            and item["properties"].get("sgaaOperation") == operation_key
            and item["properties"].get("sgaaKind") == object_kind
        ]

    @staticmethod
    def _remote(item, *, reused):
        return RemoteObject(item["id"], item["parent_id"], item["name"], len(item["content"]),
                            item["sha256"], reused)

    def add_file(self, *, parent_id, name, content, operation_key, object_kind, semantic=None, file_id=None):
        """Plant a file as a previous uploader left it (legacy adoption vectors)."""
        file_id = file_id or f"drvfile{len(self.files) + 1}"
        self.files[file_id] = dict(
            id=file_id, parent_id=parent_id, name=name, content=bytes(content), sha256=sha256(content),
            trashed=False, properties={"sgaaManaged": "true", "sgaaKind": object_kind,
                                       "sgaaOperation": operation_key, **(semantic or {})},
        )
        return file_id

    def find_operation(self, *, parent_id, operation_key, object_kind):
        self._enter("find_operation")
        matches = self._matches(parent_id, operation_key, object_kind)
        if len(matches) > 1:
            from app.storage.contracts import StorageConflictError

            raise StorageConflictError("duplicate")
        return self._remote(matches[0], reused=True) if matches else None

    def upload(self, *, parent_id, stored_filename, content, mime_type, operation_key, object_kind,
               semantic_properties):
        self._enter("upload")
        with self._lock:
            return self._upload(parent_id, stored_filename, content, mime_type, operation_key, object_kind,
                                semantic_properties)

    def _upload(self, parent_id, stored_filename, content, mime_type, operation_key, object_kind,
                semantic_properties):
        matches = self._matches(parent_id, operation_key, object_kind)
        if len(matches) > 1:
            from app.storage.contracts import StorageConflictError

            raise StorageConflictError("duplicate")
        if matches:
            return self._remote(matches[0], reused=True)
        file_id = self.add_file(parent_id=parent_id, name=stored_filename, content=content,
                                operation_key=operation_key, object_kind=object_kind,
                                semantic=dict(semantic_properties))
        self.files[file_id]["mime_type"] = mime_type
        if self.corrupt_next_upload:
            self.corrupt_next_upload = False
            self.files[file_id]["sha256"] = "0" * 64
        return self._remote(self.files[file_id], reused=False)

    def download(self, file_id):
        self._enter("download")
        item = self.files.get(str(file_id))
        if item is None or item["trashed"]:
            raise StorageError("missing")
        return item["content"]

    def describe_file(self, file_id):
        self._enter("describe_file")
        item = self.files.get(str(file_id))
        if item is None or item["trashed"]:
            return None
        return self._remote(item, reused=True)

    def trash(self, file_id):
        self._enter("trash")
        if not self.allow_trash:
            raise DriveTouched(f"trash {file_id}")
        self.files[str(file_id)]["trashed"] = True

    def untrash(self, file_id):
        self._enter("untrash")
        if not self.allow_trash:
            raise DriveTouched(f"untrash {file_id}")
        self.files[str(file_id)]["trashed"] = False

    def delete(self, file_id):  # the managed contract has no delete: always a tripwire
        self.calls.append("delete")
        raise DriveTouched(f"delete {file_id}")


__all__ = [
    "ACCOUNT_KEY", "ADMIN_ID", "BUCKET", "Clock", "DriveTouched", "FakeDrive", "GuardedStore", "Tripwire", "OTHER_ACCOUNT_KEY", "REQUEST_ID",
    "SEED_SQL", "SEEDED_TABLES", "STUDENT_ID", "STUDENT_USER_ID", "T0", "TURMA_ID", "insert_object", "sqlite_storage_env",
    "object_state", "request_snapshot", "seed_business", "seed_canonical_arquivo",
    "seed_canonical_request_document", "sha256",
]
