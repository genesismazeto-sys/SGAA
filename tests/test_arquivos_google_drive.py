from __future__ import annotations

import base64
import hashlib
import io
import sqlite3
import struct
import zlib
from pathlib import Path

import pytest
from flask import Flask
from pypdf import PdfWriter
from werkzeug.datastructures import FileStorage

from app.arquivos import (
    ArquivoError,
    create_arquivo,
    delete_arquivo,
    prepare_arquivo,
    read_arquivo_content,
    retry_arquivo_cleanup,
    update_arquivo,
)
from app.prod1_schema import (
    _physical_schema_signature,
    bootstrap_prod1_schema,
    migrate_prod1_v2_to_v3,
    migrate_prod1_v3_to_v4,
    migrate_prod1_v4_to_v5,
)
from app.storage.contracts import RemoteObject, StorageTransientError
from tests.hermetic_prod1_fixtures import build_canonical_v2_database


def _valid_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    target = io.BytesIO()
    writer.write(target)
    return target.getvalue()


def _encrypted_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.encrypt("secret")
    target = io.BytesIO()
    writer.write(target)
    return target.getvalue()


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


PDF = _valid_pdf()
PNG = (
    b"\x89PNG\r\n\x1a\n"
    + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    + _png_chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff"))
    + _png_chunk(b"IEND", b"")
)
JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAMCAgMCAgMDAwMEAwMEBQgFBQQEBQoH"
    "BwYIDAoMDAsKCwsNDhIQDQ4RDgsLEBYQERMUFRUVDA8XGBYUGBIUFRT/2wBDAQME"
    "BAUEBQkFBQkUDQsNFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQU"
    "FBQUFBQUFBQUFBQUFBT/wAARCAABAAEDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEA"
    "AAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIh"
    "MUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6"
    "Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZ"
    "mqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx"
    "8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREA"
    "AgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAV"
    "YnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hp"
    "anN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPE"
    "xcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD9"
    "U6KKKAP/2Q=="
)


def _file(content: bytes, name: str) -> FileStorage:
    return FileStorage(stream=io.BytesIO(content), filename=name)


class FakeManagedStorage:
    provider = "google"

    def __init__(self):
        self.folders = {}
        self.folder_calls = []
        self.files = {}
        self.upload_calls = []
        self.find_calls = []
        self.trashed = []
        self.fail_upload = False
        self.fail_trash = False
        self.on_trash = None
        self.bad_sha = False

    def ensure_folder(self, *, parent_id, kind, semantic_id, display_name):
        self.folder_calls.append((parent_id, kind, semantic_id, display_name))
        key = (parent_id, kind, semantic_id)
        return self.folders.setdefault(key, f"folder-{len(self.folders) + 1}")

    def upload(self, **payload):
        self.upload_calls.append(payload)
        if self.fail_upload:
            raise StorageTransientError("upload failed")
        existing = next(
            (item for item in self.files.values() if item["operation_key"] == payload["operation_key"]),
            None,
        )
        if existing:
            return RemoteObject(
                existing["id"], payload["parent_id"], existing["name"],
                len(existing["content"]), existing["sha256"], True,
            )
        file_id = f"remote-{len(self.files) + 1}"
        digest = hashlib.sha256(payload["content"]).hexdigest()
        self.files[file_id] = {
            "id": file_id,
            "name": payload["stored_filename"],
            "content": payload["content"],
            "sha256": digest,
            "operation_key": payload["operation_key"],
            "properties": payload["semantic_properties"],
        }
        return RemoteObject(
            file_id, payload["parent_id"], payload["stored_filename"],
            len(payload["content"]), "0" * 64 if self.bad_sha else digest, False,
        )

    def find_operation(self, *, parent_id, operation_key, object_kind):
        self.find_calls.append((parent_id, operation_key, object_kind))
        existing = next(
            (item for item in self.files.values() if item["operation_key"] == operation_key),
            None,
        )
        if existing is None:
            return None
        return RemoteObject(
            existing["id"], parent_id, existing["name"],
            len(existing["content"]), existing["sha256"], True,
        )

    def trash(self, file_id):
        if self.on_trash:
            self.on_trash(file_id)
        if self.fail_trash:
            raise StorageTransientError("trash failed")
        self.trashed.append(file_id)

    def untrash(self, file_id):
        return None

    def download(self, file_id):
        return self.files[file_id]["content"]


@pytest.fixture()
def service_env(tmp_path):
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        UPLOAD_FOLDER=str(tmp_path / "uploads"),
        MAX_CONTENT_LENGTH=16 * 1024 * 1024,
    )
    storage = FakeManagedStorage()
    app.extensions["arquivo_storage"] = storage
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    bootstrap_prod1_schema(conn)
    conn.execute(
        "INSERT INTO usuarios(id,nome,email,senha,tipo) VALUES(1,'Admin','admin@example.test','x','admin')"
    )
    conn.commit()
    with app.app_context():
        yield conn, storage, app
    conn.close()


def _create(conn, content=PDF, name="arquivo.pdf", operation="operation-1") -> int:
    return create_arquivo(
        conn,
        file_storage=_file(content, name),
        titulo="Arquivo",
        descricao="Descrição",
        visivel=1,
        uploader_user_id=1,
        operation_key=operation,
        max_file_bytes=16 * 1024 * 1024,
    )


def test_clean_v5_bootstrap_has_single_arquivos_contract():
    conn = sqlite3.connect(":memory:")
    bootstrap_prod1_schema(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 5
    columns = {row[1] for row in conn.execute("PRAGMA table_info(admin_arquivos)")}
    assert {
        "provider", "remote_file_id", "remote_parent_id", "mime_type", "size_bytes",
        "sha256", "uploaded_at", "uploader_user_id", "operation_key", "storage_status",
        "failure_code", "prior_provider", "prior_locator", "cleanup_started_at",
    } <= columns


def test_v5_bootstrap_and_migration_consume_single_arquivos_ddl_authority():
    root = Path(__file__).resolve().parents[1]
    schema_source = (root / "app" / "prod1_schema.py").read_text(encoding="utf-8")
    migration_source = (root / "app" / "prod1_arquivos_v5.py").read_text(encoding="utf-8")
    authority_source = (root / "app" / "prod1_arquivos_ddl.py").read_text(encoding="utf-8")
    assert "CREATE TABLE admin_arquivos" not in schema_source
    assert "CREATE TABLE admin_arquivos (" not in migration_source
    assert authority_source.count("CREATE TABLE admin_arquivos") == 1
    assert "canonical_prod1_object_sql" in migration_source


def test_v4_to_v5_preserves_legacy_row_and_matches_clean_bootstrap():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    build_canonical_v2_database(conn)
    migrate_prod1_v2_to_v3(conn)
    migrate_prod1_v3_to_v4(conn)
    cursor = conn.execute(
        "INSERT INTO admin_arquivos(titulo,filename,original_filename) VALUES('Legado','admin_arquivos/old.pdf','old.pdf')"
    )
    legacy_id = cursor.lastrowid
    conn.commit()
    migrate_prod1_v4_to_v5(conn)
    row = conn.execute("SELECT * FROM admin_arquivos WHERE id=?", (legacy_id,)).fetchone()
    assert (row["provider"], row["storage_status"], row["filename"]) == (
        "local_legacy", "legacy_active", "admin_arquivos/old.pdf"
    )
    assert row["remote_file_id"] is None and row["operation_key"] is None
    expected = sqlite3.connect(":memory:")
    bootstrap_prod1_schema(expected)
    assert _physical_schema_signature(conn) == _physical_schema_signature(expected)


def test_v5_rejects_incomplete_active_and_invalid_recovery_states(service_env):
    conn, _storage, _app = service_env
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO admin_arquivos(titulo,filename,provider,storage_status) VALUES('X','x.pdf','google','active')"
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO admin_arquivos(titulo,filename,provider,storage_status,cleanup_started_at) VALUES('X','x.pdf','local_legacy','deletion_pending',NULL)"
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """INSERT INTO admin_arquivos(
                   titulo,filename,original_filename,provider,remote_file_id,remote_parent_id,
                   mime_type,size_bytes,sha256,uploaded_at,uploader_user_id,operation_key,
                   storage_status,cleanup_started_at)
               VALUES('X','x.pdf','x.pdf','google','r','p','application/pdf',1,?,
                      '2026-09-06T00:00:00Z',1,'op','replacement_cleanup_pending',
                      '2026-09-06T00:00:00Z')""",
            ("a" * 64,),
        )


def test_v5_enforces_active_google_fields_and_storage_uniqueness(service_env):
    conn, _storage, _app = service_env
    arquivo_id = _create(conn)
    for assignment in (
        "remote_file_id=''",
        "remote_parent_id=''",
        "mime_type='text/plain'",
        "size_bytes=0",
        "sha256='bad'",
        "uploaded_at='bad'",
        "uploader_user_id=NULL",
        "operation_key=''",
    ):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(f"UPDATE admin_arquivos SET {assignment} WHERE id=?", (arquivo_id,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """INSERT INTO admin_arquivos(
                   titulo,filename,original_filename,provider,remote_file_id,remote_parent_id,
                   mime_type,size_bytes,sha256,uploaded_at,uploader_user_id,operation_key,storage_status)
               SELECT 'Duplicate',filename,original_filename,provider,remote_file_id,'other-parent',
                      mime_type,size_bytes,sha256,uploaded_at,uploader_user_id,'other-operation','active'
                 FROM admin_arquivos WHERE id=?""",
            (arquivo_id,),
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """INSERT INTO admin_arquivos(
                   titulo,filename,original_filename,provider,remote_file_id,remote_parent_id,
                   mime_type,size_bytes,sha256,uploaded_at,uploader_user_id,operation_key,storage_status)
               SELECT 'Duplicate',filename,original_filename,provider,'other-remote','other-parent',
                      mime_type,size_bytes,sha256,uploaded_at,uploader_user_id,operation_key,'active'
                 FROM admin_arquivos WHERE id=?""",
            (arquivo_id,),
        )


@pytest.mark.parametrize(
    ("content", "name", "mime"),
    [(PDF, "file.pdf", "application/pdf"), (PNG, "file.png", "image/png"), (JPEG, "file.jpg", "image/jpeg")],
)
def test_upload_validates_and_activates_directly_under_arquivos(service_env, content, name, mime):
    conn, storage, _app = service_env
    arquivo_id = _create(conn, content, name, operation=f"op-{name}")
    row = conn.execute("SELECT * FROM admin_arquivos WHERE id=?", (arquivo_id,)).fetchone()
    assert (row["provider"], row["storage_status"], row["mime_type"]) == ("google", "active", mime)
    assert (row["size_bytes"], row["sha256"]) == (len(content), hashlib.sha256(content).hexdigest())
    assert storage.folder_calls[-2:] == [
        ("root", "product_root", "sgaa", "SGAA"),
        ("folder-1", "domain_root", "arquivos", "ARQUIVOS"),
    ]
    assert storage.upload_calls[-1]["parent_id"] == "folder-2"
    assert storage.upload_calls[-1]["object_kind"] == "arquivo"
    assert storage.upload_calls[-1]["semantic_properties"] == {"sgaaArquivo": str(arquivo_id)}


@pytest.mark.parametrize(
    ("content", "name", "code"),
    [
        (_encrypted_pdf(), "secret.pdf", "MALFORMED_FILE"),
        (b"", "empty.pdf", "MALFORMED_FILE"),
        (b"not-pdf", "bad.pdf", "MALFORMED_FILE"),
        (PNG, "wrong.pdf", "MIME_MISMATCH"),
        (PDF, "bad.exe", "UNSUPPORTED_FILE_TYPE"),
    ],
)
def test_invalid_upload_is_rejected_before_provider_access(service_env, content, name, code):
    conn, storage, _app = service_env
    with pytest.raises(ArquivoError) as captured:
        _create(conn, content, name, operation=f"invalid-{code}-{name}")
    assert captured.value.code == code
    assert storage.folder_calls == [] and storage.upload_calls == []
    assert conn.execute("SELECT COUNT(*) FROM admin_arquivos").fetchone()[0] == 0


def test_create_retry_reuses_stable_operation_without_duplicate(service_env):
    conn, storage, _app = service_env
    first = _create(conn, operation="stable-op")
    second = _create(conn, operation="stable-op")
    assert first == second
    assert len(storage.files) == 1
    assert conn.execute("SELECT COUNT(*) FROM admin_arquivos").fetchone()[0] == 1


def test_remote_integrity_failure_never_activates_and_retains_locator(service_env):
    conn, storage, _app = service_env
    storage.bad_sha = True
    with pytest.raises(ArquivoError) as captured:
        _create(conn)
    assert captured.value.code == "REMOTE_INTEGRITY_MISMATCH"
    row = conn.execute("SELECT * FROM admin_arquivos").fetchone()
    assert row["storage_status"] == "reconciliation_required"
    assert (row["remote_file_id"], row["remote_parent_id"]) == ("remote-1", "folder-2")


def test_google_replacement_promotes_then_cleans_prior_object(service_env):
    conn, storage, app = service_env
    arquivo_id = _create(conn, operation="original-op")
    old_remote = conn.execute(
        "SELECT remote_file_id FROM admin_arquivos WHERE id=?", (arquivo_id,)
    ).fetchone()[0]
    observed = []
    storage.on_trash = lambda file_id: observed.append(
        tuple(conn.execute(
            "SELECT storage_status,prior_provider,prior_locator,remote_file_id FROM admin_arquivos WHERE id=?",
            (arquivo_id,),
        ).fetchone())
    )
    assert update_arquivo(
        conn,
        arquivo_id=arquivo_id,
        file_storage=_file(PNG, "new.png"),
        titulo="Novo",
        descricao=None,
        visivel=1,
        uploader_user_id=1,
        operation_key="replacement-op",
        max_file_bytes=app.config["MAX_CONTENT_LENGTH"],
        upload_root=app.config["UPLOAD_FOLDER"],
    )
    row = conn.execute("SELECT * FROM admin_arquivos WHERE id=?", (arquivo_id,)).fetchone()
    assert observed == [("replacement_cleanup_pending", "google", old_remote, "remote-2")]
    assert row["storage_status"] == "active" and row["prior_locator"] is None
    assert storage.trashed == [old_remote]


def test_failed_replacement_cleanup_retains_locator_and_retry(service_env):
    conn, storage, app = service_env
    arquivo_id = _create(conn, operation="original-op")
    old_remote = conn.execute(
        "SELECT remote_file_id FROM admin_arquivos WHERE id=?", (arquivo_id,)
    ).fetchone()[0]
    storage.fail_trash = True
    assert not update_arquivo(
        conn,
        arquivo_id=arquivo_id,
        file_storage=_file(PNG, "new.png"),
        titulo="Novo",
        descricao=None,
        visivel=1,
        uploader_user_id=1,
        operation_key="replacement-op",
        max_file_bytes=app.config["MAX_CONTENT_LENGTH"],
        upload_root=app.config["UPLOAD_FOLDER"],
    )
    row = conn.execute("SELECT * FROM admin_arquivos WHERE id=?", (arquivo_id,)).fetchone()
    assert (row["storage_status"], row["prior_provider"], row["prior_locator"]) == (
        "replacement_cleanup_pending", "google", old_remote
    )
    storage.fail_trash = False
    assert retry_arquivo_cleanup(conn, arquivo_id, upload_root=app.config["UPLOAD_FOLDER"])
    row = conn.execute("SELECT * FROM admin_arquivos WHERE id=?", (arquivo_id,)).fetchone()
    assert row["storage_status"] == "active" and row["prior_locator"] is None


def test_replacement_upload_identity_is_durable_and_same_operation_resumes(service_env):
    conn, storage, app = service_env
    arquivo_id = _create(conn, operation="original-op")
    old_remote = conn.execute(
        "SELECT remote_file_id FROM admin_arquivos WHERE id=?", (arquivo_id,)
    ).fetchone()[0]
    storage.fail_upload = True
    with pytest.raises(ArquivoError):
        update_arquivo(
            conn,
            arquivo_id=arquivo_id,
            file_storage=_file(PNG, "new.png"),
            titulo="Novo",
            descricao=None,
            visivel=1,
            uploader_user_id=1,
            operation_key="durable-replacement",
            max_file_bytes=app.config["MAX_CONTENT_LENGTH"],
            upload_root=app.config["UPLOAD_FOLDER"],
        )
    row = conn.execute("SELECT * FROM admin_arquivos WHERE id=?", (arquivo_id,)).fetchone()
    assert row["remote_file_id"] == old_remote
    assert row["operation_key"] == "durable-replacement"
    assert row["failure_code"] == "REPLACEMENT_UPLOAD_STORAGE_TRANSIENT"
    assert (
        row["replacement_mime_type"],
        row["replacement_size_bytes"],
        row["replacement_sha256"],
    ) == ("image/png", len(PNG), hashlib.sha256(PNG).hexdigest())
    with pytest.raises(ArquivoError) as blocked:
        delete_arquivo(conn, arquivo_id, upload_root=app.config["UPLOAD_FOLDER"])
    assert blocked.value.code == "REPLACEMENT_RETRY_REQUIRED"

    storage.fail_upload = False
    assert update_arquivo(
        conn,
        arquivo_id=arquivo_id,
        file_storage=_file(PNG, "new.png"),
        titulo="Novo",
        descricao=None,
        visivel=1,
        uploader_user_id=1,
        operation_key="durable-replacement",
        max_file_bytes=app.config["MAX_CONTENT_LENGTH"],
        upload_root=app.config["UPLOAD_FOLDER"],
    )
    assert conn.execute(
        "SELECT storage_status,failure_code FROM admin_arquivos WHERE id=?", (arquivo_id,)
    ).fetchone()[:] == ("active", None)


@pytest.mark.parametrize(
    ("column", "conflicting_value"),
    [
        ("replacement_sha256", "f" * 64),
        ("replacement_size_bytes", len(PNG) + 1),
        ("replacement_mime_type", "image/jpeg"),
    ],
)
def test_replacement_operation_rejects_each_payload_identity_conflict_without_provider_call(
    service_env, column, conflicting_value
):
    conn, storage, app = service_env
    arquivo_id = _create(conn, operation="original-op")
    storage.fail_upload = True
    with pytest.raises(ArquivoError):
        update_arquivo(
            conn,
            arquivo_id=arquivo_id,
            file_storage=_file(PNG, "new.png"),
            titulo="Novo",
            descricao=None,
            visivel=1,
            uploader_user_id=1,
            operation_key="bound-replacement",
            max_file_bytes=app.config["MAX_CONTENT_LENGTH"],
            upload_root=app.config["UPLOAD_FOLDER"],
        )
    conn.execute(
        f"UPDATE admin_arquivos SET {column}=? WHERE id=?",
        (conflicting_value, arquivo_id),
    )
    conn.commit()
    storage.fail_upload = False
    provider_calls = (len(storage.folder_calls), len(storage.upload_calls), len(storage.trashed))
    served_before = tuple(conn.execute(
        "SELECT provider,remote_file_id,mime_type,size_bytes,sha256 FROM admin_arquivos WHERE id=?",
        (arquivo_id,),
    ).fetchone())
    with pytest.raises(ArquivoError) as captured:
        update_arquivo(
            conn,
            arquivo_id=arquivo_id,
            file_storage=_file(PNG, "new.png"),
            titulo="Novo",
            descricao=None,
            visivel=1,
            uploader_user_id=1,
            operation_key="bound-replacement",
            max_file_bytes=app.config["MAX_CONTENT_LENGTH"],
            upload_root=app.config["UPLOAD_FOLDER"],
        )
    assert captured.value.code == "OPERATION_KEY_CONFLICT"
    assert (len(storage.folder_calls), len(storage.upload_calls), len(storage.trashed)) == provider_calls
    assert tuple(conn.execute(
        "SELECT provider,remote_file_id,mime_type,size_bytes,sha256 FROM admin_arquivos WHERE id=?",
        (arquivo_id,),
    ).fetchone()) == served_before


def test_replacement_operation_cannot_be_replayed_with_distinct_valid_payload(service_env):
    conn, storage, app = service_env
    arquivo_id = _create(conn, operation="original-op")
    storage.fail_upload = True
    with pytest.raises(ArquivoError):
        update_arquivo(
            conn,
            arquivo_id=arquivo_id,
            file_storage=_file(PNG, "intended.png"),
            titulo="Novo",
            descricao=None,
            visivel=1,
            uploader_user_id=1,
            operation_key="immutable-payload",
            max_file_bytes=app.config["MAX_CONTENT_LENGTH"],
            upload_root=app.config["UPLOAD_FOLDER"],
        )
    storage.fail_upload = False
    provider_calls = (len(storage.folder_calls), len(storage.upload_calls), len(storage.trashed))
    served_before = tuple(conn.execute(
        "SELECT remote_file_id,mime_type,size_bytes,sha256 FROM admin_arquivos WHERE id=?",
        (arquivo_id,),
    ).fetchone())
    with pytest.raises(ArquivoError) as captured:
        update_arquivo(
            conn,
            arquivo_id=arquivo_id,
            file_storage=_file(JPEG, "different.jpg"),
            titulo="Outro",
            descricao=None,
            visivel=0,
            uploader_user_id=1,
            operation_key="immutable-payload",
            max_file_bytes=app.config["MAX_CONTENT_LENGTH"],
            upload_root=app.config["UPLOAD_FOLDER"],
        )
    assert captured.value.code == "OPERATION_KEY_CONFLICT"
    assert (len(storage.folder_calls), len(storage.upload_calls), len(storage.trashed)) == provider_calls
    assert tuple(conn.execute(
        "SELECT remote_file_id,mime_type,size_bytes,sha256 FROM admin_arquivos WHERE id=?",
        (arquivo_id,),
    ).fetchone()) == served_before


def test_malformed_new_replacement_cannot_reconcile_or_mutate_prior_cleanup(
    service_env, monkeypatch
):
    conn, storage, app = service_env
    arquivo_id = _create(conn, operation="original-op")
    storage.fail_trash = True
    assert not update_arquivo(
        conn,
        arquivo_id=arquivo_id,
        file_storage=_file(PNG, "valid.png"),
        titulo="Novo",
        descricao=None,
        visivel=1,
        uploader_user_id=1,
        operation_key="previous-replacement",
        max_file_bytes=app.config["MAX_CONTENT_LENGTH"],
        upload_root=app.config["UPLOAD_FOLDER"],
    )
    storage.fail_trash = False
    storage.trashed.clear()
    storage.upload_calls.clear()
    local_deletes = []
    monkeypatch.setattr("app.arquivos._remove_local", lambda *args: local_deletes.append(args))
    served_before = tuple(conn.execute(
        "SELECT * FROM admin_arquivos WHERE id=?", (arquivo_id,)
    ).fetchone())
    with pytest.raises(ArquivoError) as captured:
        update_arquivo(
            conn,
            arquivo_id=arquivo_id,
            file_storage=_file(b"not-a-pdf", "malformed.pdf"),
            titulo="Outro",
            descricao=None,
            visivel=0,
            uploader_user_id=1,
            operation_key="new-replacement",
            max_file_bytes=app.config["MAX_CONTENT_LENGTH"],
            upload_root=app.config["UPLOAD_FOLDER"],
        )
    assert captured.value.code == "MALFORMED_FILE"
    assert storage.trashed == [] and storage.upload_calls == [] and local_deletes == []
    assert tuple(conn.execute(
        "SELECT * FROM admin_arquivos WHERE id=?", (arquivo_id,)
    ).fetchone()) == served_before


def test_malformed_legacy_replacement_never_deletes_local_prior(service_env, tmp_path):
    conn, storage, app = service_env
    upload_root = tmp_path / "legacy-root"
    prior_path = upload_root / "admin_arquivos" / "prior.pdf"
    prior_path.parent.mkdir(parents=True)
    prior_path.write_bytes(PDF)
    cursor = conn.execute(
        """INSERT INTO admin_arquivos(titulo,filename,original_filename)
           VALUES('Legado','admin_arquivos/prior.pdf','prior.pdf')"""
    )
    conn.commit()
    with pytest.raises(ArquivoError) as captured:
        update_arquivo(
            conn,
            arquivo_id=cursor.lastrowid,
            file_storage=_file(b"malformed", "bad.pdf"),
            titulo="Outro",
            descricao=None,
            visivel=0,
            uploader_user_id=1,
            operation_key="invalid-legacy-replacement",
            max_file_bytes=app.config["MAX_CONTENT_LENGTH"],
            upload_root=str(upload_root),
        )
    assert captured.value.code == "MALFORMED_FILE"
    assert prior_path.read_bytes() == PDF
    assert storage.folder_calls == [] and storage.upload_calls == [] and storage.trashed == []


def test_replacement_activation_failure_reuses_remote_on_retry(service_env):
    conn, storage, app = service_env
    arquivo_id = _create(conn, operation="original-op")
    conn.execute(
        """CREATE TRIGGER block_arquivo_replacement
           BEFORE UPDATE OF storage_status ON admin_arquivos
           WHEN NEW.storage_status='replacement_cleanup_pending'
           BEGIN SELECT RAISE(ABORT,'blocked'); END"""
    )
    conn.commit()
    kwargs = dict(
        conn=conn,
        arquivo_id=arquivo_id,
        file_storage=_file(PNG, "new.png"),
        titulo="Novo",
        descricao=None,
        visivel=1,
        uploader_user_id=1,
        operation_key="activation-retry",
        max_file_bytes=app.config["MAX_CONTENT_LENGTH"],
        upload_root=app.config["UPLOAD_FOLDER"],
    )
    with pytest.raises(ArquivoError) as captured:
        update_arquivo(**kwargs)
    assert captured.value.code == "REPLACEMENT_ACTIVATION_PENDING"
    assert len(storage.files) == 2
    conn.execute("DROP TRIGGER block_arquivo_replacement")
    conn.commit()
    kwargs["file_storage"] = _file(PNG, "new.png")
    assert update_arquivo(**kwargs)
    assert len(storage.files) == 2


def test_legacy_replace_read_and_delete_use_confined_local_path(service_env, tmp_path):
    conn, storage, app = service_env
    upload_root = tmp_path / "uploads"
    local_path = upload_root / "admin_arquivos" / "legacy.pdf"
    local_path.parent.mkdir(parents=True)
    local_path.write_bytes(PDF)
    cursor = conn.execute(
        "INSERT INTO admin_arquivos(titulo,filename,original_filename) VALUES('Legado','admin_arquivos/legacy.pdf','legacy.pdf')"
    )
    arquivo_id = cursor.lastrowid
    conn.commit()
    row = conn.execute("SELECT * FROM admin_arquivos WHERE id=?", (arquivo_id,)).fetchone()
    assert read_arquivo_content(conn, row, upload_root=app.config["UPLOAD_FOLDER"])[0] == PDF
    assert update_arquivo(
        conn,
        arquivo_id=arquivo_id,
        file_storage=_file(PNG, "new.png"),
        titulo="Novo",
        descricao=None,
        visivel=1,
        uploader_user_id=1,
        operation_key="legacy-replacement",
        max_file_bytes=app.config["MAX_CONTENT_LENGTH"],
        upload_root=app.config["UPLOAD_FOLDER"],
    )
    assert not local_path.exists()
    delete_arquivo(conn, arquivo_id, upload_root=app.config["UPLOAD_FOLDER"])
    assert storage.trashed == ["remote-1"]
    assert conn.execute("SELECT 1 FROM admin_arquivos WHERE id=?", (arquivo_id,)).fetchone() is None


def test_delete_marks_pending_before_trash_and_failure_preserves_custody(service_env):
    conn, storage, app = service_env
    arquivo_id = _create(conn)
    locator = conn.execute(
        "SELECT remote_file_id FROM admin_arquivos WHERE id=?", (arquivo_id,)
    ).fetchone()[0]
    observed = []
    storage.on_trash = lambda file_id: observed.append(
        tuple(conn.execute(
            "SELECT storage_status,remote_file_id FROM admin_arquivos WHERE id=?", (arquivo_id,)
        ).fetchone())
    )
    storage.fail_trash = True
    with pytest.raises(ArquivoError):
        delete_arquivo(conn, arquivo_id, upload_root=app.config["UPLOAD_FOLDER"])
    row = conn.execute("SELECT * FROM admin_arquivos WHERE id=?", (arquivo_id,)).fetchone()
    assert observed == [("deletion_pending", locator)]
    assert row["storage_status"] == "deletion_pending" and row["remote_file_id"] == locator
    storage.fail_trash = False
    delete_arquivo(conn, arquivo_id, upload_root=app.config["UPLOAD_FOLDER"])
    assert conn.execute("SELECT 1 FROM admin_arquivos WHERE id=?", (arquivo_id,)).fetchone() is None


def test_delete_process_death_leaves_durable_resumable_state(service_env):
    conn, storage, app = service_env
    arquivo_id = _create(conn)

    def stop_after_remote_action(_file_id):
        raise SystemExit("simulated process death")

    storage.on_trash = stop_after_remote_action
    with pytest.raises(SystemExit):
        delete_arquivo(conn, arquivo_id, upload_root=app.config["UPLOAD_FOLDER"])
    row = conn.execute(
        "SELECT storage_status,remote_file_id,cleanup_started_at FROM admin_arquivos WHERE id=?",
        (arquivo_id,),
    ).fetchone()
    assert row["storage_status"] == "deletion_pending"
    assert row["remote_file_id"] and row["cleanup_started_at"]
    storage.on_trash = None
    delete_arquivo(conn, arquivo_id, upload_root=app.config["UPLOAD_FOLDER"])
    assert conn.execute("SELECT 1 FROM admin_arquivos WHERE id=?", (arquivo_id,)).fetchone() is None


def _insert_locatorless_pending(conn, *, operation, failure_code=None, parent_id=None):
    cursor = conn.execute(
        """INSERT INTO admin_arquivos(
               titulo,filename,original_filename,provider,remote_parent_id,mime_type,
               size_bytes,sha256,uploaded_at,uploader_user_id,operation_key,
               storage_status,failure_code)
           VALUES('Pendente','pending.pdf','pending.pdf','google',?,'application/pdf',
                  ?,?,'2026-09-06T00:00:00Z',1,?,'pending',?)""",
        (parent_id, len(PDF), hashlib.sha256(PDF).hexdigest(), operation, failure_code),
    )
    conn.commit()
    return int(cursor.lastrowid)


def test_locatorless_definitively_local_pending_delete_needs_no_provider(service_env):
    conn, storage, app = service_env
    arquivo_id = _insert_locatorless_pending(conn, operation="never-started")
    delete_arquivo(conn, arquivo_id, upload_root=app.config["UPLOAD_FOLDER"])
    assert conn.execute("SELECT 1 FROM admin_arquivos WHERE id=?", (arquivo_id,)).fetchone() is None
    assert storage.find_calls == [] and storage.trashed == []


def test_locatorless_uncertain_pending_delete_reconciles_exact_remote_before_discard(
    service_env
):
    conn, storage, app = service_env
    arquivo_id = _insert_locatorless_pending(
        conn,
        operation="uncertain-upload",
        failure_code="UPLOAD_IN_PROGRESS",
        parent_id="folder-2",
    )
    storage.files["remote-uncertain"] = {
        "id": "remote-uncertain",
        "name": "pending.pdf",
        "content": PDF,
        "sha256": hashlib.sha256(PDF).hexdigest(),
        "operation_key": "uncertain-upload",
        "properties": {"sgaaArquivo": str(arquivo_id)},
    }
    observed = []
    storage.on_trash = lambda _file_id: observed.append(tuple(conn.execute(
        "SELECT storage_status,remote_file_id FROM admin_arquivos WHERE id=?",
        (arquivo_id,),
    ).fetchone()))
    delete_arquivo(conn, arquivo_id, upload_root=app.config["UPLOAD_FOLDER"])
    assert storage.find_calls == [("folder-2", "uncertain-upload", "arquivo")]
    assert observed == [("deletion_pending", "remote-uncertain")]
    assert storage.trashed == ["remote-uncertain"]
    assert conn.execute("SELECT 1 FROM admin_arquivos WHERE id=?", (arquivo_id,)).fetchone() is None


def test_locatorless_uncertain_pending_delete_discards_only_after_negative_reconciliation(
    service_env
):
    conn, storage, app = service_env
    arquivo_id = _insert_locatorless_pending(
        conn,
        operation="uncertain-missing",
        failure_code="UPLOAD_IN_PROGRESS",
        parent_id="folder-2",
    )
    delete_arquivo(conn, arquivo_id, upload_root=app.config["UPLOAD_FOLDER"])
    assert storage.find_calls == [("folder-2", "uncertain-missing", "arquivo")]
    assert storage.trashed == []
    assert conn.execute("SELECT 1 FROM admin_arquivos WHERE id=?", (arquivo_id,)).fetchone() is None


def test_v4_to_v5_preserves_admin_arquivos_autoincrement_high_water():
    conn = sqlite3.connect(":memory:")
    build_canonical_v2_database(conn)
    migrate_prod1_v2_to_v3(conn)
    migrate_prod1_v3_to_v4(conn)
    for suffix in (1, 2, 3):
        conn.execute(
            "INSERT INTO admin_arquivos(titulo,filename) VALUES(?,?)",
            (f"Arquivo {suffix}", f"arquivo-{suffix}.pdf"),
        )
    conn.execute("DELETE FROM admin_arquivos WHERE id=3")
    conn.commit()
    assert conn.execute(
        "SELECT seq FROM sqlite_sequence WHERE name='admin_arquivos'"
    ).fetchone()[0] == 3
    migrate_prod1_v4_to_v5(conn)
    cursor = conn.execute(
        "INSERT INTO admin_arquivos(titulo,filename) VALUES('Depois','depois.pdf')"
    )
    assert cursor.lastrowid == 4


def test_message_catalog_product_delta_is_exact_while_baseline_debt_remains_visible():
    from utils import messages

    expected_service_keys = {
        "msg_03838cf4375b19ba", "msg_37e2b83d1d482dda", "msg_3a41da0ccaf4fb87",
        "msg_4352c3bedf64fdb3", "msg_50e2ec3c13d4bacf", "msg_5d39cfef2de1d430",
        "msg_6018c93006bce7f1", "msg_6742934d48d39daa", "msg_7e6360ffea8471f8",
        "msg_99d8117a515eb70c", "msg_a0d4d710aec2a890", "msg_a425dc0cf589a059",
        "msg_c32c18c64199702d", "msg_cd0d9c70d8a4bfe2", "msg_cf503b5361e8df6d",
        "msg_d5d74776a47ddd0f", "msg_e273eba2773adfcb", "msg_eb3e6fcd30b0a8bb",
        "msg_fb247154b41ecbce",
    }
    preexisting_shared_keys = {
        "msg_22d5360a88fd9875",
        "msg_73e5da794b4422db",
        "msg_f31086760fc761bb",
    }
    catalog = messages._message_catalog()
    service_keys = {
        key
        for key, entry in catalog.items()
        if any(usage["source_path"] == "app/arquivos.py" for usage in entry["usages"])
    }
    assert service_keys == expected_service_keys | preexisting_shared_keys
    assert "msg_adc145990771728c" in catalog
    assert "msg_68e61511e6b7b342" not in catalog
    head_actual, head_expected, legitimate_net_delta = 526, 537, 19
    assert len(catalog) == head_actual + legitimate_net_delta == 545
    assert head_expected + legitimate_net_delta == 556
    assert (head_expected + legitimate_net_delta) - len(catalog) == 11


def test_legacy_path_escape_is_rejected(service_env, tmp_path):
    conn, _storage, app = service_env
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(PDF)
    cursor = conn.execute(
        "INSERT INTO admin_arquivos(titulo,filename,original_filename) VALUES('Bad','../outside.pdf','outside.pdf')"
    )
    row = conn.execute("SELECT * FROM admin_arquivos WHERE id=?", (cursor.lastrowid,)).fetchone()
    with pytest.raises(ArquivoError) as captured:
        read_arquivo_content(conn, row, upload_root=app.config["UPLOAD_FOLDER"])
    assert captured.value.code == "INVALID_LOCAL_PATH"
    assert outside.exists()
