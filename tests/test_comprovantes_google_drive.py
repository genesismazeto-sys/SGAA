from __future__ import annotations

import hashlib
import base64
import json
import sqlite3
import struct
import zlib
from io import BytesIO

import pytest
from flask import Flask
from werkzeug.datastructures import FileStorage

from app.comprovantes import (
    ComprovanteError,
    authorize_request_comprovante_actor,
    delete_request_with_comprovantes,
    prepare_comprovante_batch,
    resolve_google_storage,
    upload_comprovantes,
)
from app.prod1_schema import (
    bootstrap_prod1_schema,
    canonical_prod1_object_sql,
    migrate_prod1_v2_to_v3,
    migrate_prod1_v3_to_v4,
    _physical_schema_signature,
)
from app.storage.contracts import (
    RemoteObject,
    StorageAuthorizationError,
    StorageConfigurationError,
    StorageTransientError,
)
from tests.hermetic_prod1_fixtures import (
    build_canonical_v1_database,
    build_canonical_v2_database,
    seed_v2_business_data,
)


def _valid_pdf_bytes():
    header = b"%PDF-1.4\n"
    objects = (
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Count 1 /Kids [3 0 R] >>\nendobj\n",
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R "
        b"/MediaBox [0 0 72 72] /Resources << >> >>\nendobj\n",
    )
    offsets = []
    payload = header
    for obj in objects:
        offsets.append(len(payload))
        payload += obj
    xref = len(payload)
    payload += b"xref\n0 4\n0000000000 65535 f \n"
    payload += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    payload += (
        b"trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n"
        + str(xref).encode()
        + b"\n%%EOF\n"
    )
    return payload


def _png_chunk(kind, data):
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


PDF = _valid_pdf_bytes()
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


class FakeStorage:
    provider = "google"

    def __init__(self):
        self.folders = {}
        self.folder_calls = []
        self.files = {}
        self.upload_calls = []
        self.trashed = []
        self.untrashed = []
        self.fail_upload_at = None
        self.fail_folder = False
        self.fail_auth = False
        self.fail_trash = False
        self.fail_untrash = False
        self.process_death_after_trash = False
        self.bad_sha = False
        self.missing_sha = False

    def ensure_folder(self, *, parent_id, kind, semantic_id, display_name):
        if self.fail_folder:
            raise StorageTransientError("folder failed")
        key = (parent_id, kind, semantic_id)
        self.folder_calls.append((parent_id, kind, semantic_id, display_name))
        return self.folders.setdefault(key, f"folder-{len(self.folders) + 1}")

    def upload(
        self, *, parent_id, stored_filename, content, mime_type,
        operation_key, request_id, attachment_id,
    ):
        self.upload_calls.append(operation_key)
        if self.fail_auth:
            raise StorageAuthorizationError("reconnect")
        if self.fail_upload_at == len(self.upload_calls):
            raise StorageTransientError("transient")
        existing = next(
            (item for item in self.files.values() if item["operation_key"] == operation_key),
            None,
        )
        if existing:
            return RemoteObject(
                existing["id"], parent_id, existing["name"], existing["size"],
                existing["sha256"], True,
            )
        file_id = f"remote-{len(self.files) + 1}"
        digest = hashlib.sha256(content).hexdigest()
        payload = {
            "id": file_id,
            "parent_id": parent_id,
            "name": stored_filename,
            "size": len(content),
            "sha256": None if self.missing_sha else ("0" * 64 if self.bad_sha else digest),
            "operation_key": operation_key,
            "content": content,
        }
        self.files[file_id] = payload
        return RemoteObject(
            file_id, parent_id, stored_filename, len(content), payload["sha256"], False
        )

    def trash(self, file_id):
        if self.fail_trash:
            raise StorageTransientError("trash failed")
        self.trashed.append(file_id)
        if self.process_death_after_trash:
            raise SystemExit("simulated process death after remote trash")

    def untrash(self, file_id):
        if self.fail_untrash:
            raise StorageTransientError("untrash failed")
        self.untrashed.append(file_id)

    def download(self, file_id):
        return self.files[file_id]["content"]


def _file(content, name, content_type="application/octet-stream"):
    return FileStorage(stream=BytesIO(content), filename=name, content_type=content_type)


def _snapshot(axis="AAC", version=2, name="Conferências"):
    return json.dumps(
        {
            "atividade_base_id": 1,
            "atividade_versao_id": 1,
            "atividade_versao_numero": version,
            "eixo": axis,
            "matriz_id_efetiva": 1,
            "schema_version": "prod-1-request-v2",
            "ch_por_evento": None,
            "limite_semestre": None,
            "limite_total": None,
            "nome_exibivel": name,
            "tipo_atividade": "Acadêmica Complementar" if axis == "AAC" else "Extensão Universitária",
            "grupo": "1",
            "documentos_json": "[]",
        },
        ensure_ascii=False,
    )


def _database(*, frozen_turma=True):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    bootstrap_prod1_schema(conn)
    conn.execute(
        "INSERT INTO cursos(id,nome,codigo,duracao_periodos) VALUES(1,'Curso','CUR',8)"
    )
    conn.execute(
        "INSERT INTO matrizes_atividades(id,curso_id,nome) VALUES(1,1,'Matriz')"
    )
    conn.execute(
        """INSERT INTO turmas(id,nome,numero,curso_id,ano_inicio,semestre_inicio,codigo,matriz_id)
           VALUES(1,'Turma 1',1,1,2026,1,'T-2026-1',1)"""
    )
    conn.execute(
        "INSERT INTO usuarios(id,nome,email,senha,tipo) VALUES(1,'Aluno','a@example.test','x','aluno')"
    )
    conn.execute(
        """INSERT INTO alunos(id,usuario_id,nome,matricula,email,turma_id)
           VALUES(1,1,'Nome Antigo','MAT-1','a@example.test',1)"""
    )
    conn.execute("INSERT INTO atividade_base(id,nome_conceito) VALUES(1,'Conferências')")
    conn.execute(
        """INSERT INTO atividade_versao(id,atividade_base_id,eixo,numero_versao,status)
           VALUES(1,1,'AAC',2,'ativa')"""
    )
    if frozen_turma:
        conn.execute(
            """INSERT INTO requisicoes(
               id,aluno_id,atividade_versao_id,data_solicitacao,data_evento,
               horas_solicitadas,status,regra_snapshot_json,
               turma_id_snapshot,turma_codigo_snapshot)
           VALUES(1,1,1,'2026-09-05','2026-09-05',2,'Pendente',?,1,'T-2026-1')""",
            (_snapshot(),),
        )
    else:
        conn.execute(
            """INSERT INTO requisicoes(
                   id,aluno_id,atividade_versao_id,data_solicitacao,data_evento,
                   horas_solicitadas,status,regra_snapshot_json)
               VALUES(1,1,1,'2026-09-05','2026-09-05',2,'Pendente',?)""",
            (_snapshot(),),
        )
    conn.commit()
    return conn


def _batch(name="proof.pdf", content=PDF, key="batch-1"):
    return prepare_comprovante_batch([_file(content, name)], batch_key=key)


def test_v3_to_v4_preserves_legacy_attachment_identity_and_does_not_backfill_turma(tmp_path):
    conn = sqlite3.connect(tmp_path / "v3.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    build_canonical_v2_database(conn)
    seed_v2_business_data(conn)
    migrate_prod1_v2_to_v3(conn)
    request_id = conn.execute("SELECT id FROM requisicoes ORDER BY id LIMIT 1").fetchone()[0]
    cursor = conn.execute(
        "INSERT INTO requisicao_arquivos(requisicao_id,label,filename) VALUES(?,?,?)",
        (request_id, "original", "aluno_1/requisicoes/legacy.pdf"),
    )
    attachment_id = cursor.lastrowid
    conn.commit()

    result = migrate_prod1_v3_to_v4(conn)

    assert result["schema_version"] == 4
    request_row = conn.execute(
        "SELECT turma_id_snapshot,turma_codigo_snapshot FROM requisicoes WHERE id=?",
        (request_id,),
    ).fetchone()
    assert tuple(request_row) == (None, None)
    row = conn.execute("SELECT * FROM requisicao_arquivos WHERE id=?", (attachment_id,)).fetchone()
    assert (row["id"], row["requisicao_id"], row["filename"], row["provider"], row["storage_status"]) == (
        attachment_id, request_id, "aluno_1/requisicoes/legacy.pdf", "local_legacy", "legacy_active"
    )


@pytest.mark.parametrize(
    ("content", "filename", "mime"),
    [
        (PDF, "proof.pdf", "application/pdf"),
        (PNG, "proof.png", "image/png"),
        (JPEG, "proof.jpeg", "image/jpeg"),
    ],
)
def test_byte_validation_accepts_only_matching_supported_formats(content, filename, mime):
    item = prepare_comprovante_batch([_file(content, filename)], batch_key="valid")[0]
    assert item.mime_type == mime
    assert item.size == len(content)
    assert item.sha256 == hashlib.sha256(content).hexdigest()


@pytest.mark.parametrize(
    ("content", "filename", "code"),
    [
        (PDF, "proof.exe", "UNSUPPORTED_FILE_TYPE"),
        (PNG, "proof.pdf", "MIME_MISMATCH"),
        (b"not-pdf", "proof.pdf", "MALFORMED_FILE"),
    ],
)
def test_byte_validation_rejects_unsupported_mismatch_and_malformed(content, filename, code):
    with pytest.raises(ComprovanteError) as captured:
        prepare_comprovante_batch([_file(content, filename)], batch_key="invalid")
    assert captured.value.code == code


def test_invalid_member_rejects_complete_batch_before_storage():
    with pytest.raises(ComprovanteError):
        prepare_comprovante_batch(
            [_file(PDF, "valid.pdf"), _file(b"bad", "invalid.pdf")], batch_key="all-or-none"
        )


@pytest.mark.parametrize(
    ("content", "filename"),
    [
        (b"%PDF-1.4\n%%EOF", "marker.pdf"),
        (
            b"%PDF-1.4\n1 0 obj<< /Type /Catalog >>endobj\nxref\n"
            b"trailer<< /Root 1 0 R >>\nstartxref\n44\n%%EOF\n",
            "fabricated-xref.pdf",
        ),
        (b"\x89PNG\r\n\x1a\n" + b"IHDR" + b"IEND", "marker.png"),
        (b"\xff\xd8\xff\xd9", "marker.jpg"),
        (PDF[:-8], "truncated.pdf"),
        (PNG[:-6], "truncated.png"),
        (JPEG[:-2], "truncated.jpeg"),
    ],
)
def test_marker_only_and_truncated_supported_files_are_rejected(content, filename):
    with pytest.raises(ComprovanteError) as captured:
        prepare_comprovante_batch([_file(content, filename)], batch_key="malformed")
    assert captured.value.code == "MALFORMED_FILE"


def test_file_size_and_malicious_name_contract():
    item = prepare_comprovante_batch([_file(PDF, "../../evil.pdf")], batch_key="safe")[0]
    assert item.original_filename == "evil.pdf"
    with pytest.raises(ComprovanteError) as captured:
        prepare_comprovante_batch([_file(PDF + b"x" * 10, "large.pdf")], batch_key="large", max_file_bytes=len(PDF))
    assert captured.value.code == "FILE_TOO_LARGE"
    bounded = prepare_comprovante_batch(
        [_file(PDF, "bounded.pdf")], batch_key="x" * 1000
    )[0]
    assert len(bounded.operation_key.encode("ascii")) <= 124


def test_upload_persists_full_custody_and_uses_snapshot_hierarchy():
    conn = _database()
    storage = FakeStorage()
    rows = upload_comprovantes(
        conn, request_id=1, uploader_user_id=1, batch=_batch(), storage=storage
    )
    row = rows[0]
    assert row["provider"] == "google"
    assert row["remote_file_id"] == "remote-1"
    assert row["remote_parent_id"]
    assert row["original_filename"] == "proof.pdf"
    assert row["filename"].startswith("REQ-000001__Conferencias__v2__")
    assert row["mime_type"] == "application/pdf"
    assert row["size_bytes"] == len(PDF)
    assert row["sha256"] == hashlib.sha256(PDF).hexdigest()
    assert row["uploader_user_id"] == 1
    assert row["uploaded_at"].endswith("Z")
    assert row["operation_key"].startswith("batch-1:0:")
    assert row["storage_status"] == "active"
    assert [call[1:3] for call in storage.folder_calls] == [
        ("product_root", "sgaa"),
        ("domain_root", "comprovantes"),
        ("turma", "1"),
        ("request_axis", "AAC"),
        ("student", "1"),
    ]


def test_historical_axis_and_student_identity_do_not_follow_mutable_display_state():
    conn = _database()
    conn.execute("UPDATE atividade_versao SET eixo='AEU' WHERE id=1")
    conn.execute("UPDATE alunos SET nome='Nome Novo',matricula='MAT-NEW' WHERE id=1")
    conn.commit()
    storage = FakeStorage()
    upload_comprovantes(conn, request_id=1, uploader_user_id=1, batch=_batch(), storage=storage)
    axis = [call for call in storage.folder_calls if call[1] == "request_axis"]
    assert axis[0][2:] == ("AAC", "AAC")
    assert [call for call in storage.folder_calls if call[1] == "student"][0][2] == "1"


def test_legacy_request_freezes_current_turma_once_then_reuses_it():
    conn = _database(frozen_turma=False)
    conn.execute(
        """INSERT INTO turmas(id,nome,numero,curso_id,ano_inicio,semestre_inicio,codigo,matriz_id)
           VALUES(2,'Turma 2',2,1,2026,2,'T-2026-2',1)"""
    )
    conn.commit()
    first = FakeStorage()
    upload_comprovantes(conn, request_id=1, uploader_user_id=1, batch=_batch(key="first"), storage=first)
    conn.execute("UPDATE alunos SET turma_id=2 WHERE id=1")
    conn.commit()
    upload_comprovantes(conn, request_id=1, uploader_user_id=1, batch=_batch(key="second"), storage=first)
    frozen = conn.execute(
        "SELECT turma_id_snapshot,turma_codigo_snapshot FROM requisicoes WHERE id=1"
    ).fetchone()
    assert tuple(frozen) == (1, "T-2026-1")
    assert {call[2:] for call in first.folder_calls if call[1] == "turma"} == {("1", "T-2026-1")}
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "UPDATE requisicoes SET turma_id_snapshot=2,turma_codigo_snapshot='T-2026-2' WHERE id=1"
        )


def test_same_operation_is_idempotent_but_distinct_operation_same_hash_is_allowed():
    conn = _database()
    storage = FakeStorage()
    first = upload_comprovantes(
        conn, request_id=1, uploader_user_id=1, batch=_batch(key="same"), storage=storage
    )
    upload_comprovantes(conn, request_id=1, uploader_user_id=1, batch=_batch(key="same"), storage=storage)
    assert len(storage.upload_calls) == 1
    second = upload_comprovantes(
        conn, request_id=1, uploader_user_id=1, batch=_batch(key="distinct"), storage=storage
    )
    assert len(storage.upload_calls) == 2
    assert first[0]["sha256"] == second[0]["sha256"]
    assert first[0]["filename"] != second[0]["filename"]
    assert conn.execute(
        "SELECT count(*) FROM requisicao_arquivos WHERE storage_status='active'"
    ).fetchone()[0] == 2


def test_later_upload_failure_trashes_prior_remote_and_leaves_no_active_row():
    conn = _database()
    storage = FakeStorage()
    storage.fail_upload_at = 2
    batch = prepare_comprovante_batch(
        [_file(PDF, "one.pdf"), _file(PNG, "two.png")], batch_key="failure"
    )
    with pytest.raises(ComprovanteError) as captured:
        upload_comprovantes(conn, request_id=1, uploader_user_id=1, batch=batch, storage=storage)
    assert captured.value.retryable
    assert storage.trashed == ["remote-1"]
    assert conn.execute(
        "SELECT count(*) FROM requisicao_arquivos WHERE storage_status='active'"
    ).fetchone()[0] == 0


def test_folder_creation_failure_leaves_no_remote_or_active_attachment():
    conn = _database()
    storage = FakeStorage()
    storage.fail_folder = True
    with pytest.raises(ComprovanteError) as captured:
        upload_comprovantes(conn, request_id=1, uploader_user_id=1, batch=_batch(), storage=storage)
    assert captured.value.retryable
    assert storage.upload_calls == []


def test_domain_rejects_foreign_student_before_any_drive_access():
    conn = _database()
    conn.execute(
        """INSERT INTO usuarios(id,nome,email,senha,tipo)
           VALUES(2,'Outro','outro@example.test','x','aluno')"""
    )
    conn.execute(
        """INSERT INTO alunos(id,usuario_id,nome,matricula,email,turma_id)
           VALUES(2,2,'Outro','MAT-2','outro@example.test',1)"""
    )
    conn.commit()
    storage = FakeStorage()
    with pytest.raises(ComprovanteError) as captured:
        upload_comprovantes(
            conn,
            request_id=1,
            uploader_user_id=2,
            batch=_batch(key="foreign-domain"),
            storage=storage,
        )
    assert captured.value.code == "ACCESS_DENIED"
    assert storage.folder_calls == []
    assert storage.upload_calls == []


def test_domain_enforces_admin_view_edit_full_scope_matrix():
    conn = _database()
    conn.execute(
        """INSERT INTO usuarios(id,nome,email,senha,tipo,nivel_acesso)
           VALUES(2,'Consultor','consultor@example.test','x','admin','consultivo')"""
    )
    conn.commit()
    authorize_request_comprovante_actor(
        conn, request_id=1, actor_user_id=2, admin_scope="view"
    )
    storage = FakeStorage()
    with pytest.raises(ComprovanteError) as upload_denied:
        upload_comprovantes(
            conn,
            request_id=1,
            uploader_user_id=2,
            batch=_batch(key="consultivo-upload"),
            storage=storage,
        )
    assert upload_denied.value.code == "ACCESS_DENIED"
    app = Flask(__name__)
    app.config.update(DOCUMENTOS_ALUNOS_FOLDER="", UPLOAD_FOLDER="")
    with app.app_context(), pytest.raises(ComprovanteError) as delete_denied:
        delete_request_with_comprovantes(
            conn, request_id=1, actor_user_id=2, storage=storage
        )
    assert delete_denied.value.code == "ACCESS_DENIED"
    assert storage.folder_calls == []
    assert conn.execute(
        "SELECT count(*) FROM requisicao_arquivos WHERE storage_status='active'"
    ).fetchone()[0] == 0


def test_drive_access_token_401_does_not_deactivate_durable_google_authorization():
    conn = _database()
    conn.execute(
        """INSERT INTO cloud_accounts(provider,account_email,token_json,active)
           VALUES('google','owner@example.test','encrypted-placeholder',1)"""
    )
    conn.commit()
    storage = FakeStorage()
    storage.fail_auth = True
    with pytest.raises(ComprovanteError) as captured:
        upload_comprovantes(conn, request_id=1, uploader_user_id=1, batch=_batch(), storage=storage)
    assert captured.value.code == "AUTH_RECONNECT_REQUIRED"
    assert conn.execute(
        "SELECT active FROM cloud_accounts WHERE provider='google'"
    ).fetchone()[0] == 1


@pytest.mark.parametrize(
    ("debug_code", "expected_active"),
    [("AUTH_RECONNECT_REQUIRED", 0), ("APPLICATION_CREDENTIALS_INVALID", 1)],
)
def test_canonical_401_refresh_deactivates_only_definitive_revocation(
    monkeypatch, debug_code, expected_active
):
    from app import cloud_connections
    from app.services.google_drive_service import GoogleDriveServiceError

    conn = _database()
    cursor = conn.execute(
        """INSERT INTO cloud_accounts(provider,account_email,token_json,active)
           VALUES('google','owner@example.test','encrypted-placeholder',1)"""
    )
    account_id = int(cursor.lastrowid)
    conn.commit()
    monkeypatch.setattr(
        cloud_connections,
        "get_application_credential_status",
        lambda provider: {"configured": True},
    )
    monkeypatch.setattr(
        cloud_connections,
        "get_active_cloud_account",
        lambda _conn, _provider: {
            "id": account_id,
            "account_email": "owner@example.test",
            "token_json": "token-json",
            "token_json_available": True,
        },
    )

    def reject_refresh(*, token_json):
        raise GoogleDriveServiceError("rejected", debug_code=debug_code)

    monkeypatch.setattr(cloud_connections, "refresh_google_access_token", reject_refresh)
    app = Flask(__name__)
    app.config["APP_ENV"] = "testing"
    with app.app_context(), pytest.raises(cloud_connections.CloudConnectionError):
        cloud_connections.recover_authenticated_access_token_after_401(conn, "google")
    assert conn.execute(
        "SELECT active FROM cloud_accounts WHERE id=?", (account_id,)
    ).fetchone()[0] == expected_active


def test_canonical_401_refresh_rotates_access_without_revoking_account(monkeypatch):
    from app import cloud_connections

    conn = _database()
    cursor = conn.execute(
        """INSERT INTO cloud_accounts(provider,account_email,token_json,active)
           VALUES('google','owner@example.test','encrypted-placeholder',1)"""
    )
    account_id = int(cursor.lastrowid)
    conn.commit()
    monkeypatch.setattr(
        cloud_connections,
        "get_application_credential_status",
        lambda provider: {"configured": True},
    )
    monkeypatch.setattr(
        cloud_connections,
        "get_active_cloud_account",
        lambda _conn, _provider: {
            "id": account_id,
            "account_email": "owner@example.test",
            "token_json": "old-token-json",
            "token_json_available": True,
        },
    )
    monkeypatch.setattr(
        cloud_connections,
        "refresh_google_access_token",
        lambda **kwargs: ("fresh-access", "new-token-json", ""),
    )
    persisted = []
    monkeypatch.setattr(
        cloud_connections,
        "update_cloud_account_token",
        lambda _conn, **kwargs: persisted.append(kwargs),
    )
    app = Flask(__name__)
    app.config["APP_ENV"] = "testing"
    with app.app_context():
        token, identity = cloud_connections.recover_authenticated_access_token_after_401(
            conn, "google"
        )
    assert token == "fresh-access" and identity == "owner@example.test"
    assert persisted[0]["token_json"] == "new-token-json"
    assert conn.execute(
        "SELECT active FROM cloud_accounts WHERE id=?", (account_id,)
    ).fetchone()[0] == 1


def test_application_credential_failure_does_not_deactivate_user_authorization(monkeypatch):
    conn = _database()
    conn.execute(
        """INSERT INTO cloud_accounts(provider,account_email,token_json,active)
           VALUES('google','owner@example.test','encrypted-placeholder',1)"""
    )
    conn.commit()
    from app import cloud_connections

    def missing_credentials(_conn, _provider):
        raise cloud_connections.CloudConnectionError(
            "missing", debug_code="APPLICATION_CREDENTIALS_MISSING"
        )

    monkeypatch.setattr(
        cloud_connections, "get_authenticated_access_token", missing_credentials
    )
    app = Flask(__name__)
    app.config["APP_ENV"] = "testing"
    with app.app_context(), pytest.raises(StorageConfigurationError):
        resolve_google_storage(conn)
    assert conn.execute(
        "SELECT active FROM cloud_accounts WHERE provider='google'"
    ).fetchone()[0] == 1


def test_compensation_failure_is_durable_reconciliation_state():
    conn = _database()
    storage = FakeStorage()
    storage.fail_upload_at = 2
    storage.fail_trash = True
    batch = prepare_comprovante_batch(
        [_file(PDF, "one.pdf"), _file(PNG, "two.png")], batch_key="reconcile"
    )
    with pytest.raises(ComprovanteError) as captured:
        upload_comprovantes(conn, request_id=1, uploader_user_id=1, batch=batch, storage=storage)
    assert captured.value.reconciliation_required
    statuses = {
        row[0] for row in conn.execute("SELECT storage_status FROM requisicao_arquivos")
    }
    assert "reconciliation_required" in statuses
    assert "active" not in statuses


def test_checksum_mismatch_never_activates_and_trashes_exact_object():
    conn = _database()
    storage = FakeStorage()
    storage.bad_sha = True
    with pytest.raises(ComprovanteError):
        upload_comprovantes(conn, request_id=1, uploader_user_id=1, batch=_batch(), storage=storage)
    assert storage.trashed == ["remote-1"]
    assert conn.execute(
        "SELECT count(*) FROM requisicao_arquivos WHERE storage_status='active'"
    ).fetchone()[0] == 0


def test_missing_google_checksum_never_activates():
    conn = _database()
    storage = FakeStorage()
    storage.missing_sha = True
    with pytest.raises(ComprovanteError):
        upload_comprovantes(conn, request_id=1, uploader_user_id=1, batch=_batch(), storage=storage)
    assert storage.trashed == ["remote-1"]
    row = conn.execute(
        "SELECT storage_status,remote_file_id FROM requisicao_arquivos"
    ).fetchone()
    assert tuple(row) == ("failed", "remote-1")


def test_integrity_compensation_failure_keeps_exact_remote_evidence():
    conn = _database()
    storage = FakeStorage()
    storage.bad_sha = True
    storage.fail_trash = True
    with pytest.raises(ComprovanteError) as captured:
        upload_comprovantes(conn, request_id=1, uploader_user_id=1, batch=_batch(), storage=storage)
    assert captured.value.reconciliation_required
    row = conn.execute(
        "SELECT storage_status,remote_file_id,remote_parent_id FROM requisicao_arquivos"
    ).fetchone()
    assert tuple(row) == ("reconciliation_required", "remote-1", "folder-5")


def test_remote_success_then_db_activation_failure_compensates_exact_object():
    conn = _database()
    conn.execute(
        """CREATE TRIGGER block_attachment_activation
           BEFORE UPDATE OF storage_status ON requisicao_arquivos
           WHEN NEW.storage_status='active'
           BEGIN SELECT RAISE(ABORT,'activation blocked'); END"""
    )
    conn.commit()
    storage = FakeStorage()
    with pytest.raises(ComprovanteError):
        upload_comprovantes(conn, request_id=1, uploader_user_id=1, batch=_batch(), storage=storage)
    assert storage.trashed == ["remote-1"]
    row = conn.execute("SELECT storage_status,remote_file_id FROM requisicao_arquivos").fetchone()
    assert tuple(row) == ("failed", "remote-1")


def test_edit_finalization_failure_preserves_request_and_compensates_remote():
    conn = _database()
    storage = FakeStorage()

    def fail_scalar_update():
        conn.execute("UPDATE requisicoes SET observacao='must rollback' WHERE id=1")
        raise sqlite3.IntegrityError("scalar update blocked")

    with pytest.raises(ComprovanteError):
        upload_comprovantes(
            conn,
            request_id=1,
            uploader_user_id=1,
            batch=_batch(key="edit-finalization"),
            storage=storage,
            finalize_db=fail_scalar_update,
        )
    assert storage.trashed == ["remote-1"]
    assert conn.execute("SELECT observacao FROM requisicoes WHERE id=1").fetchone()[0] is None
    row = conn.execute("SELECT storage_status,remote_file_id FROM requisicao_arquivos").fetchone()
    assert tuple(row) == ("failed", "remote-1")


def test_request_deletion_trashes_before_cascade_and_remote_failure_blocks_delete(tmp_path):
    app = Flask(__name__)
    app.config.update(
        DOCUMENTOS_ALUNOS_FOLDER=str(tmp_path / "documents"),
        UPLOAD_FOLDER=str(tmp_path / "uploads"),
    )
    conn = _database()
    storage = FakeStorage()
    upload_comprovantes(conn, request_id=1, uploader_user_id=1, batch=_batch(), storage=storage)
    storage.fail_trash = True
    with app.app_context(), pytest.raises(ComprovanteError):
        delete_request_with_comprovantes(
            conn, request_id=1, actor_user_id=1, storage=storage
        )
    assert conn.execute("SELECT 1 FROM requisicoes WHERE id=1").fetchone()
    storage.fail_trash = False
    with app.app_context():
        delete_request_with_comprovantes(
            conn, request_id=1, actor_user_id=1, storage=storage
        )
    assert not conn.execute("SELECT 1 FROM requisicoes WHERE id=1").fetchone()
    assert storage.trashed[-1] == "remote-1"


def test_process_death_after_remote_trash_leaves_durable_resumable_delete_state(tmp_path):
    app = Flask(__name__)
    app.config.update(DOCUMENTOS_ALUNOS_FOLDER=str(tmp_path), UPLOAD_FOLDER=str(tmp_path))
    conn = _database()
    storage = FakeStorage()
    upload_comprovantes(conn, request_id=1, uploader_user_id=1, batch=_batch(), storage=storage)
    storage.process_death_after_trash = True
    with app.app_context(), pytest.raises(SystemExit):
        delete_request_with_comprovantes(
            conn, request_id=1, actor_user_id=1, storage=storage
        )
    row = conn.execute(
        """SELECT storage_status,delete_previous_status,delete_started_at,remote_file_id
             FROM requisicao_arquivos WHERE requisicao_id=1"""
    ).fetchone()
    assert row["storage_status"] == "deletion_pending"
    assert row["delete_previous_status"] == "active"
    assert row["delete_started_at"] and row["remote_file_id"] == "remote-1"
    assert conn.execute("SELECT 1 FROM requisicoes WHERE id=1").fetchone()

    storage.process_death_after_trash = False
    with app.app_context():
        delete_request_with_comprovantes(
            conn, request_id=1, actor_user_id=1, storage=storage
        )
    assert not conn.execute("SELECT 1 FROM requisicoes WHERE id=1").fetchone()


def test_db_delete_failure_attempts_untrash(tmp_path):
    app = Flask(__name__)
    app.config.update(DOCUMENTOS_ALUNOS_FOLDER=str(tmp_path), UPLOAD_FOLDER=str(tmp_path))
    conn = _database()
    storage = FakeStorage()
    upload_comprovantes(conn, request_id=1, uploader_user_id=1, batch=_batch(), storage=storage)
    conn.execute(
        """CREATE TRIGGER block_request_delete BEFORE DELETE ON requisicoes
           BEGIN SELECT RAISE(ABORT,'blocked'); END"""
    )
    conn.commit()
    with app.app_context(), pytest.raises(ComprovanteError) as captured:
        delete_request_with_comprovantes(
            conn, request_id=1, actor_user_id=1, storage=storage
        )
    assert captured.value.code == "DB_DELETE_FAILED"
    assert storage.untrashed == ["remote-1"]
    assert conn.execute("SELECT 1 FROM requisicoes WHERE id=1").fetchone()


def test_failed_untrash_is_durable_reconciliation_state(tmp_path):
    app = Flask(__name__)
    app.config.update(DOCUMENTOS_ALUNOS_FOLDER=str(tmp_path), UPLOAD_FOLDER=str(tmp_path))
    conn = _database()
    storage = FakeStorage()
    upload_comprovantes(conn, request_id=1, uploader_user_id=1, batch=_batch(), storage=storage)
    conn.execute(
        """CREATE TRIGGER block_request_delete BEFORE DELETE ON requisicoes
           BEGIN SELECT RAISE(ABORT,'blocked'); END"""
    )
    conn.commit()
    storage.fail_untrash = True
    with app.app_context(), pytest.raises(ComprovanteError) as captured:
        delete_request_with_comprovantes(
            conn, request_id=1, actor_user_id=1, storage=storage
        )
    assert captured.value.reconciliation_required
    row = conn.execute(
        "SELECT storage_status,failure_code FROM requisicao_arquivos WHERE requisicao_id=1"
    ).fetchone()
    assert tuple(row) == ("reconciliation_required", "REMOTE_RESTORE_FAILED")


def test_request_deletion_blocks_uncertain_remote_identity(tmp_path):
    app = Flask(__name__)
    app.config.update(DOCUMENTOS_ALUNOS_FOLDER=str(tmp_path), UPLOAD_FOLDER=str(tmp_path))
    conn = _database()
    conn.execute(
        """INSERT INTO requisicao_arquivos(
               requisicao_id,filename,provider,operation_key,storage_status)
           VALUES(1,'pending.pdf','google','pending-delete','pending')"""
    )
    conn.commit()
    with app.app_context(), pytest.raises(ComprovanteError) as captured:
        delete_request_with_comprovantes(
            conn, request_id=1, actor_user_id=1, storage=FakeStorage()
        )
    assert captured.value.reconciliation_required
    assert conn.execute("SELECT 1 FROM requisicoes WHERE id=1").fetchone()


def test_legacy_local_deletion_uses_actual_captured_path(tmp_path):
    documents = tmp_path / "documents"
    uploads = tmp_path / "uploads"
    actual = documents / "aluno_1" / "requisicoes" / "legacy.pdf"
    actual.parent.mkdir(parents=True)
    actual.write_bytes(PDF)
    app = Flask(__name__)
    app.config.update(DOCUMENTOS_ALUNOS_FOLDER=str(documents), UPLOAD_FOLDER=str(uploads))
    conn = _database()
    conn.execute(
        """INSERT INTO requisicao_arquivos(requisicao_id,label,filename)
           VALUES(1,'legacy','aluno_1/requisicoes/legacy.pdf')"""
    )
    conn.commit()
    with app.app_context():
        delete_request_with_comprovantes(conn, request_id=1, actor_user_id=1)
    assert not actual.exists()


def test_schema_constraints_reject_incomplete_active_google_and_duplicate_identity():
    conn = _database()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """INSERT INTO requisicao_arquivos(
                   requisicao_id,filename,provider,storage_status)
               VALUES(1,'bad.pdf','google','active')"""
        )
    conn.execute(
        """INSERT INTO requisicao_arquivos(
               requisicao_id,filename,provider,remote_file_id,remote_parent_id,
               original_filename,mime_type,size_bytes,sha256,uploaded_at,
               uploader_user_id,operation_key,storage_status)
           VALUES(1,'ok.pdf','google','remote-x','parent','ok.pdf','application/pdf',1,
                  ?, '2026-09-06T00:00:00Z',1,'operation-x','active')""",
        ("a" * 64,),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """INSERT INTO requisicao_arquivos(
                   requisicao_id,filename,provider,remote_file_id,remote_parent_id,
                   original_filename,mime_type,size_bytes,sha256,uploaded_at,
                   uploader_user_id,operation_key,storage_status)
               VALUES(1,'other.pdf','google','remote-x','parent','other.pdf','application/pdf',1,
                      ?, '2026-09-06T00:00:00Z',1,'operation-y','active')""",
            ("b" * 64,),
        )


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("filename", " "),
        ("remote_file_id", " "),
        ("remote_parent_id", ""),
        ("original_filename", " "),
        ("mime_type", None),
        ("mime_type", "text/html"),
        ("size_bytes", 0),
        ("sha256", "a" * 63),
        ("uploaded_at", " "),
        ("uploaded_at", "not-a-timestamp"),
        ("operation_key", ""),
        ("operation_key", "x" * 125),
        ("uploader_user_id", 99999),
    ],
)
def test_schema_rejects_each_invalid_active_google_custody_value(field, invalid):
    conn = _database()
    payload = {
        "filename": "ok.pdf",
        "remote_file_id": "remote-valid",
        "remote_parent_id": "parent-valid",
        "original_filename": "ok.pdf",
        "mime_type": "application/pdf",
        "size_bytes": 1,
        "sha256": "a" * 64,
        "uploaded_at": "2026-09-06T00:00:00Z",
        "uploader_user_id": 1,
        "operation_key": "operation-valid",
    }
    payload[field] = invalid
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """INSERT INTO requisicao_arquivos(
                   requisicao_id,filename,provider,remote_file_id,remote_parent_id,
                   original_filename,mime_type,size_bytes,sha256,uploaded_at,
                   uploader_user_id,operation_key,storage_status)
               VALUES(1,:filename,'google',:remote_file_id,:remote_parent_id,
                      :original_filename,:mime_type,:size_bytes,:sha256,:uploaded_at,
                      :uploader_user_id,:operation_key,'active')""",
            payload,
        )


def _schema_signature(conn):
    return _physical_schema_signature(conn)


@pytest.mark.parametrize("source_version", [1, 2, 3])
def test_clean_bootstrap_and_each_supported_migration_share_exact_v4_ddl(source_version):
    expected = sqlite3.connect(":memory:")
    bootstrap_prod1_schema(expected)
    candidate = sqlite3.connect(":memory:")
    if source_version == 1:
        build_canonical_v1_database(candidate)
    else:
        build_canonical_v2_database(candidate)
        if source_version == 3:
            migrate_prod1_v2_to_v3(candidate)
    bootstrap_prod1_schema(candidate)
    assert _schema_signature(candidate) == _schema_signature(expected)


def test_v4_migration_consumes_the_single_bootstrap_ddl_authority():
    source = __import__("pathlib").Path(
        __import__("app.prod1_comprovantes_v4", fromlist=["x"]).__file__
    ).read_text(encoding="utf-8")
    assert "_REQUISICOES_V4_SQL" not in source
    assert "_REQUISICAO_ARQUIVOS_V4_SQL" not in source
    assert "CREATE TRIGGER trg_" not in source
    assert "canonical_prod1_object_sql" in source
    assert canonical_prod1_object_sql("table", "requisicao_arquivos")
