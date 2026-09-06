from __future__ import annotations

from io import BytesIO
import re

import pytest

import main
from tests.test_comprovante_file_validation import (
    AMPLIFICATION_PNG,
    CATALOGLESS_PDF,
    MALFORMED_ADAM7_PNG,
    REVERSE_AMPLIFICATION_PNG,
)
from tests.test_comprovantes_google_drive import (
    FakeStorage,
    JPEG,
    PDF,
    PNG,
)
from tests.versioned_test_support import isolated_versioned_app_env


@pytest.fixture
def comprovante_env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "comprovantes-routes.db") as env:
        storage = FakeStorage()
        original = main.app.extensions.get("comprovante_storage")
        main.app.extensions["comprovante_storage"] = storage
        try:
            yield {**env, "storage": storage}
        finally:
            if original is None:
                main.app.extensions.pop("comprovante_storage", None)
            else:
                main.app.extensions["comprovante_storage"] = original


def _student(conn):
    return conn.execute(
        """SELECT a.id,a.usuario_id,a.turma_id
             FROM alunos a JOIN usuarios u ON u.id=a.usuario_id
            WHERE u.tipo='aluno' ORDER BY a.id LIMIT 1"""
    ).fetchone()


def _active_version(conn, student):
    return conn.execute(
        """SELECT item.atividade_versao_id
             FROM turmas t
             JOIN matriz_atividade_versao_item item ON item.matriz_id=t.matriz_id
             JOIN atividade_versao version ON version.id=item.atividade_versao_id
            WHERE t.id=? AND version.status='ativa'
         ORDER BY item.id LIMIT 1""",
        (student["turma_id"],),
    ).fetchone()[0]


def _login(client, *, user_id, user_type, access_level=None):
    with client.session_transaction() as sess:
        sess["user_id"] = int(user_id)
        sess["user_type"] = user_type
        if access_level:
            sess["access_level"] = access_level


def _student_create(env, operation="route-create"):
    with main.app.app_context():
        conn = main.get_db_connection()
        student = _student(conn)
        version_id = _active_version(conn, student)
    _login(env["client"], user_id=student["usuario_id"], user_type="aluno")
    response = env["client"].post(
        "/aluno/nova-requisicao",
        data={
            "atividade_versao_id": str(version_id),
            "nome_evento": "Comprovante route",
            "data_evento": "2026-09-06",
            "horas_solicitadas": "2",
            "comprovantes_operation_id": operation,
            "comprovantes_files": (BytesIO(PDF), "proof.pdf"),
        },
        content_type="multipart/form-data",
    )
    with main.app.app_context():
        conn = main.get_db_connection()
        request_row = conn.execute(
            "SELECT * FROM requisicoes WHERE nome_evento='Comprovante route' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        attachment = conn.execute(
            "SELECT * FROM requisicao_arquivos WHERE requisicao_id=? ORDER BY id DESC LIMIT 1",
            (request_row["id"],),
        ).fetchone() if request_row else None
    return response, student, request_row, attachment


def test_student_create_writes_google_only_with_frozen_request_turma(comprovante_env):
    response, student, request_row, attachment = _student_create(comprovante_env)
    assert response.status_code == 302
    assert request_row["turma_id_snapshot"] == student["turma_id"]
    assert request_row["turma_codigo_snapshot"]
    assert attachment["provider"] == "google"
    assert attachment["storage_status"] == "active"
    assert not any(comprovante_env["documents_path"].rglob("proof.pdf"))
    assert not any(comprovante_env["uploads_path"].rglob("proof.pdf"))


@pytest.mark.parametrize(
    ("content", "filename"),
    [
        (MALFORMED_ADAM7_PNG, "adam7.png"),
        (AMPLIFICATION_PNG, "amplification.png"),
        (REVERSE_AMPLIFICATION_PNG, "reverse-amplification.png"),
        (CATALOGLESS_PDF, "catalogless.pdf"),
        (b"%PDF-1.4\n%%EOF", "marker.pdf"),
        (b"\x89PNG\r\n\x1a\n", "marker.png"),
        (b"\xff\xd8\xff\xd9", "marker.jpg"),
        (PDF[:-8], "truncated.pdf"),
        (PNG[:-6], "truncated.png"),
        (JPEG[:-2], "truncated.jpg"),
    ],
    ids=[
        "malformed-adam7",
        "amplification",
        "reverse-amplification",
        "catalogless-pdf",
        "marker-pdf",
        "marker-png",
        "marker-jpeg",
        "truncated-pdf",
        "truncated-png",
        "truncated-jpeg",
    ],
)
def test_rejected_file_causes_zero_provider_calls(comprovante_env, content, filename):
    with main.app.app_context():
        conn = main.get_db_connection()
        student = _student(conn)
        version_id = _active_version(conn, student)
    _login(
        comprovante_env["client"],
        user_id=student["usuario_id"],
        user_type="aluno",
    )
    response = comprovante_env["client"].post(
        "/aluno/nova-requisicao",
        data={
            "atividade_versao_id": str(version_id),
            "nome_evento": "Invalid proof",
            "data_evento": "2026-09-06",
            "horas_solicitadas": "2",
            "comprovantes_operation_id": "invalid-file",
            "comprovantes_files": (BytesIO(content), filename),
        },
        content_type="multipart/form-data",
    )
    storage = comprovante_env["storage"]
    assert response.status_code == 200
    assert storage.folder_calls == []
    assert storage.upload_calls == []
    with main.app.app_context():
        conn = main.get_db_connection()
        active_rows = conn.execute(
            "SELECT count(*) FROM requisicao_arquivos WHERE storage_status='active'"
        ).fetchone()[0]
    assert active_rows == 0


def test_successful_student_create_client_retry_does_not_duplicate_request_or_remote(comprovante_env):
    first, _student_row, request_row, _attachment = _student_create(
        comprovante_env, operation="stable-client-operation"
    )
    second, _student_row, replayed_request, _attachment = _student_create(
        comprovante_env, operation="stable-client-operation"
    )
    assert first.status_code == second.status_code == 302
    assert replayed_request["id"] == request_row["id"]
    with main.app.app_context():
        conn = main.get_db_connection()
        assert conn.execute(
            "SELECT count(*) FROM requisicoes WHERE nome_evento='Comprovante route'"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT count(*) FROM requisicao_arquivos WHERE requisicao_id=?",
            (request_row["id"],),
        ).fetchone()[0] == 1
    assert len(comprovante_env["storage"].files) == 1


def test_independent_get_forms_are_distinct_intentional_operations(comprovante_env):
    with main.app.app_context():
        student = _student(main.get_db_connection())
    _login(comprovante_env["client"], user_id=student["usuario_id"], user_type="aluno")
    first_get = comprovante_env["client"].get("/aluno/nova-requisicao")
    second_get = comprovante_env["client"].get("/aluno/nova-requisicao")
    pattern = rb'name="comprovantes_operation_id" value="([^"]+)"'
    first_key = re.search(pattern, first_get.data).group(1)
    second_key = re.search(pattern, second_get.data).group(1)
    assert first_key != second_key

    _student_create(comprovante_env, operation=first_key.decode())
    _student_create(comprovante_env, operation=second_key.decode())
    with main.app.app_context():
        conn = main.get_db_connection()
        assert conn.execute(
            "SELECT count(*) FROM requisicoes WHERE nome_evento='Comprovante route'"
        ).fetchone()[0] == 2
    assert len(comprovante_env["storage"].files) == 2


def test_student_edit_uses_the_same_google_service(comprovante_env):
    _response, student, request_row, first = _student_create(comprovante_env)
    response = comprovante_env["client"].post(
        f"/aluno/requisicoes/{request_row['id']}",
        data={
            "observacao": "updated",
            "comprovantes_operation_id": "route-edit",
            "comprovantes_files": (BytesIO(PDF), "second.pdf"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    with main.app.app_context():
        rows = main.get_db_connection().execute(
            "SELECT provider,storage_status FROM requisicao_arquivos WHERE requisicao_id=?",
            (request_row["id"],),
        ).fetchall()
    assert len(rows) == 2
    assert {(row["provider"], row["storage_status"]) for row in rows} == {("google", "active")}


def test_admin_create_and_edit_use_google_and_existing_rbac(comprovante_env):
    with main.app.app_context():
        conn = main.get_db_connection()
        student = _student(conn)
        version_id = _active_version(conn, student)
        admin = conn.execute(
            "SELECT id,nivel_acesso FROM usuarios WHERE tipo='admin' ORDER BY id LIMIT 1"
        ).fetchone()
    _login(
        comprovante_env["client"], user_id=admin["id"], user_type="admin",
        access_level=admin["nivel_acesso"],
    )
    create = comprovante_env["client"].post(
        "/admin/requisicoes/nova",
        data={
            "aluno_id": str(student["id"]),
            "atividade_versao_id": str(version_id),
            "nome_evento": "Admin cloud request",
            "data_evento": "2026-09-06",
            "horas_solicitadas": "2",
            "comprovantes_operation_id": "admin-create",
            "comprovantes_files": (BytesIO(PDF), "admin.pdf"),
        },
        content_type="multipart/form-data",
    )
    assert create.status_code == 302
    with main.app.app_context():
        request_id = main.get_db_connection().execute(
            "SELECT id FROM requisicoes WHERE nome_evento='Admin cloud request'"
        ).fetchone()[0]
    edit = comprovante_env["client"].post(
        f"/admin/requisicoes/{request_id}/editar",
        data={
            "nome_evento": "Admin cloud request",
            "data_evento": "2026-09-06",
            "horas_solicitadas": "2",
            "comprovantes_operation_id": "admin-edit",
            "comprovantes_files": (BytesIO(PDF), "admin-second.pdf"),
        },
        content_type="multipart/form-data",
    )
    assert edit.status_code == 302
    with main.app.app_context():
        rows = main.get_db_connection().execute(
            "SELECT provider,storage_status FROM requisicao_arquivos WHERE requisicao_id=?",
            (request_id,),
        ).fetchall()
    assert len(rows) == 2
    assert all(row["provider"] == "google" and row["storage_status"] == "active" for row in rows)


def test_open_uses_local_attachment_id_and_enforces_student_ownership(comprovante_env):
    _response, student, request_row, attachment = _student_create(comprovante_env)
    own = comprovante_env["client"].get(f"/comprovantes/{attachment['id']}/open")
    assert own.status_code == 200 and own.data == PDF
    assert own.headers["X-Content-Type-Options"] == "nosniff"
    assert own.headers["Cache-Control"] == "private, no-store"
    assert own.headers["Content-Type"].startswith("application/pdf")
    with main.app.app_context():
        conn = main.get_db_connection()
        cursor = conn.execute(
            "INSERT INTO usuarios(nome,email,senha,tipo,nivel_acesso) "
            "VALUES('Other','other@example.test','x','aluno','aluno')"
        )
        other_user = cursor.lastrowid
        conn.execute(
            "INSERT INTO alunos(usuario_id,nome,matricula,email,turma_id) VALUES(?,?,?,?,?)",
            (other_user, "Other", "OTHER-1", "other@example.test", student["turma_id"]),
        )
        conn.commit()
    _login(comprovante_env["client"], user_id=other_user, user_type="aluno")
    assert comprovante_env["client"].get(
        f"/comprovantes/{attachment['id']}/open"
    ).status_code == 403
    assert comprovante_env["client"].get(
        f"/comprovantes/{attachment['remote_file_id']}/open"
    ).status_code == 404


def test_open_anonymous_redirects_and_admin_view_scope_allows(comprovante_env):
    _response, _student_row, _request_row, attachment = _student_create(comprovante_env)
    with comprovante_env["client"].session_transaction() as sess:
        sess.clear()
    anonymous = comprovante_env["client"].get(
        f"/comprovantes/{attachment['id']}/open"
    )
    assert anonymous.status_code == 302 and "/login" in anonymous.headers["Location"]
    with main.app.app_context():
        admin = main.get_db_connection().execute(
            "SELECT id,nivel_acesso FROM usuarios WHERE tipo='admin' ORDER BY id LIMIT 1"
        ).fetchone()
    _login(
        comprovante_env["client"], user_id=admin["id"], user_type="admin",
        access_level=admin["nivel_acesso"],
    )
    assert comprovante_env["client"].get(
        f"/comprovantes/{attachment['id']}/open"
    ).status_code == 200


def test_legacy_local_attachment_remains_readable_by_local_id(comprovante_env):
    _response, _student_row, request_row, _cloud = _student_create(comprovante_env)
    relative = "aluno_1/requisicoes/legacy.pdf"
    absolute = comprovante_env["documents_path"] / relative
    absolute.parent.mkdir(parents=True, exist_ok=True)
    absolute.write_bytes(PDF)
    with main.app.app_context():
        conn = main.get_db_connection()
        cursor = conn.execute(
            "INSERT INTO requisicao_arquivos(requisicao_id,label,filename) VALUES(?,?,?)",
            (request_row["id"], "Legacy", relative),
        )
        legacy_id = cursor.lastrowid
        conn.commit()
    response = comprovante_env["client"].get(f"/comprovantes/{legacy_id}/open")
    assert response.status_code == 200 and response.data == PDF
    assert response.headers["Cache-Control"] == "private, no-store"


def test_inline_allowlist_forces_every_other_legacy_type_to_attachment(comprovante_env):
    _response, _student_row, request_row, cloud_pdf = _student_create(comprovante_env)
    cases = [
        ("valid.png", PNG, "image/png", True),
        ("valid.jpg", JPEG, "image/jpeg", True),
        ("unsafe.html", b"<script>unsafe</script>", "text/html", False),
    ]
    attachment_ids = []
    with main.app.app_context():
        conn = main.get_db_connection()
        for filename, content, mime_type, inline in cases:
            relative = f"aluno_1/requisicoes/{filename}"
            path = comprovante_env["documents_path"] / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            cursor = conn.execute(
                """INSERT INTO requisicao_arquivos(
                       requisicao_id,label,filename,mime_type)
                   VALUES(?,?,?,?)""",
                (request_row["id"], filename, relative, mime_type),
            )
            attachment_ids.append((cursor.lastrowid, inline))
        conn.commit()
    pdf = comprovante_env["client"].get(f"/comprovantes/{cloud_pdf['id']}/open")
    assert pdf.headers["Content-Disposition"].startswith("inline")
    for attachment_id, inline in attachment_ids:
        response = comprovante_env["client"].get(
            f"/comprovantes/{attachment_id}/open"
        )
        expected = "inline" if inline else "attachment"
        assert response.headers["Content-Disposition"].startswith(expected)
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["Cache-Control"] == "private, no-store"


def test_student_admin_detail_process_and_api_surfaces_use_local_attachment_url(comprovante_env):
    _response, _student_row, request_row, attachment = _student_create(comprovante_env)
    student_detail = comprovante_env["client"].get(
        f"/aluno/requisicoes/{request_row['id']}"
    )
    expected_path = f"/comprovantes/{attachment['id']}/open"
    assert expected_path.encode() in student_detail.data
    with main.app.app_context():
        admin = main.get_db_connection().execute(
            "SELECT id,nivel_acesso FROM usuarios WHERE tipo='admin' ORDER BY id LIMIT 1"
        ).fetchone()
    _login(
        comprovante_env["client"], user_id=admin["id"], user_type="admin",
        access_level=admin["nivel_acesso"],
    )
    direct = comprovante_env["client"].get(f"/admin/requisicao/{request_row['id']}")
    process = comprovante_env["client"].get(
        f"/admin/processar_requisicao/{request_row['id']}"
    )
    api = comprovante_env["client"].get(
        f"/admin/api/requisicao/{request_row['id']}"
    )
    assert expected_path.encode() in direct.data
    assert expected_path.encode() in process.data
    assert api.status_code == 200
    assert api.get_json()["anexos"][0]["url"].endswith(expected_path)
