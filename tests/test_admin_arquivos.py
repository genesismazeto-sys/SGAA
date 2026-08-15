import io
import json
import os
import re
import sys
from html import unescape

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main


@pytest.fixture()
def client():
    app = main.app
    with app.app_context():
        main.init_db()
        yield app.test_client()


def _login_admin(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["user_type"] = "admin"
        sess["user_name"] = "Administrador"


def test_admin_arquivos_page_and_crud_flow(client, tmp_path):
    titulo = "Arquivo Admin Teste"
    titulo_editado = "Arquivo Admin Editado"

    upload_root = tmp_path / "uploads"
    documents_root = tmp_path / "documentos_alunos"
    upload_root.mkdir(parents=True, exist_ok=True)
    documents_root.mkdir(parents=True, exist_ok=True)
    original_upload_folder = main.app.config.get("UPLOAD_FOLDER")
    original_documents_folder = main.app.config.get("DOCUMENTOS_ALUNOS_FOLDER")
    main.app.config["UPLOAD_FOLDER"] = str(upload_root)
    main.app.config["DOCUMENTOS_ALUNOS_FOLDER"] = str(documents_root)

    try:
        _login_admin(client)

        with main.app.app_context():
            conn = main.get_db_connection()
            main.ensure_admin_arquivos_table(conn)
            existing = conn.execute("SELECT id, filename FROM admin_arquivos WHERE titulo IN (?, ?)", (titulo, titulo_editado)).fetchall()
            for row in existing:
                conn.execute("DELETE FROM admin_arquivos WHERE id = ?", (row["id"],))
                main._best_effort_remove_admin_arquivo_file(row["filename"])
            conn.commit()

        page_response = client.get("/admin/arquivos")
        assert page_response.status_code == 200
        html = page_response.data.decode("utf-8")
        assert "/admin/arquivos/adicionar" in html
        assert "/admin/arquivos/0/editar" in html
        assert "/admin/arquivos/0/deletar" in html

        create_response = client.post(
            "/admin/arquivos/adicionar",
            data={
                "titulo": titulo,
                "descricao": "Descricao inicial",
                "visivel": "1",
                "arquivo": (io.BytesIO(b"arquivo-admin"), "arquivo-admin.pdf"),
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        assert create_response.status_code == 302
        assert create_response.headers["Location"].endswith("/admin/arquivos")

        with main.app.app_context():
            conn = main.get_db_connection()
            created = conn.execute(
                "SELECT id, titulo, descricao, filename, original_filename, visivel FROM admin_arquivos WHERE titulo = ? ORDER BY id DESC LIMIT 1",
                (titulo,),
            ).fetchone()
            assert created is not None
            arquivo_id = created["id"]
            assert created["original_filename"] == "arquivo-admin.pdf"
            assert created["visivel"] == 1
            saved_upload_path = upload_root / str(created["filename"])
            saved_docs_path = documents_root / str(created["filename"])
            assert saved_upload_path.is_file()
            assert not saved_docs_path.exists()

        edit_page_response = client.get(f"/admin/arquivos/{arquivo_id}/editar")
        assert edit_page_response.status_code == 302
        assert f"edit_arquivo={arquivo_id}" in edit_page_response.headers["Location"]

        edit_response = client.post(
            f"/admin/arquivos/{arquivo_id}/editar",
            data={
                "titulo": titulo_editado,
                "descricao": "Descricao editada",
                "visivel": "0",
            },
            follow_redirects=False,
        )
        assert edit_response.status_code == 302
        assert edit_response.headers["Location"].endswith("/admin/arquivos")

        with main.app.app_context():
            conn = main.get_db_connection()
            edited = conn.execute(
                "SELECT titulo, descricao, visivel, filename FROM admin_arquivos WHERE id = ?",
                (arquivo_id,),
            ).fetchone()
            assert edited is not None
            assert edited["titulo"] == titulo_editado
            assert edited["descricao"] == "Descricao editada"
            assert edited["visivel"] == 0
            filename = edited["filename"]

        view_response = client.get(f"/admin/arquivos/{arquivo_id}/visualizar")
        assert view_response.status_code == 302
        assert "/uploads/" in view_response.headers["Location"]
        assert filename.replace('\\', '/') in view_response.headers["Location"]

        delete_response = client.post(f"/admin/arquivos/{arquivo_id}/deletar", follow_redirects=False)
        assert delete_response.status_code == 302
        assert delete_response.headers["Location"].endswith("/admin/arquivos")

        with main.app.app_context():
            conn = main.get_db_connection()
            deleted = conn.execute("SELECT id FROM admin_arquivos WHERE id = ?", (arquivo_id,)).fetchone()
            assert deleted is None
    finally:
        main.app.config["UPLOAD_FOLDER"] = original_upload_folder
        main.app.config["DOCUMENTOS_ALUNOS_FOLDER"] = original_documents_folder


def test_admin_arquivos_edit_flow_reaches_render_target_and_exposes_edit_payload(client):
    """C-1 RED: GET /admin/arquivos/<id>/editar -> 302 -> ?edit_arquivo=<id> -> 200.

    The public edit flow must reach the render target and expose the seeded
    record as JSON in script#admin-arquivo-edit-data. The unmodified production
    tree fails this test because the edit target serializes a sqlite3.Row
    through | tojson (TypeError -> 500).
    """
    titulo = "Arquivo Edit Flow Red"
    original_filename = "edit-flow-red.pdf"
    filename = "admin_arquivos/edit_flow_red.pdf"
    descricao = "Descricao edit flow red"

    _login_admin(client)

    with main.app.app_context():
        conn = main.get_db_connection()
        main.ensure_admin_arquivos_table(conn)
        conn.execute("DELETE FROM admin_arquivos WHERE titulo = ?", (titulo,))
        conn.execute(
            """
            INSERT INTO admin_arquivos (titulo, descricao, filename, original_filename, visivel, criado_em)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (titulo, descricao, filename, original_filename, 1, "2026-03-01 10:00:00"),
        )
        conn.commit()
        arquivo_id = conn.execute(
            "SELECT id FROM admin_arquivos WHERE titulo = ?", (titulo,)
        ).fetchone()["id"]

    response = client.get(f"/admin/arquivos/{arquivo_id}/editar", follow_redirects=True)

    assert response.status_code == 200, (
        "edit flow render target must be HTTP 200; "
        f"got {response.status_code} for /admin/arquivos?edit_arquivo={arquivo_id}"
    )
    html = response.get_data(as_text=True)

    match = re.search(
        r'<script id="admin-arquivo-edit-data" type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    assert match, "script#admin-arquivo-edit-data must be present on the edit render target"
    payload = json.loads(unescape(match.group(1)))
    assert payload is not None, "edit payload must not be null for a valid arquivo id"
    assert payload["id"] == arquivo_id
    assert payload["titulo"] == titulo
    assert payload["descricao"] == descricao
    assert payload["filename"] == filename
    assert payload["original_filename"] == original_filename
    assert payload["visivel"] == 1


def test_admin_arquivos_edit_flow_nonexistent_id_renders_without_payload(client):
    """C-1 negative control: an unknown edit target stays 200 with a null payload."""
    _login_admin(client)

    response = client.get("/admin/arquivos", query_string={"edit_arquivo": 999999})
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    match = re.search(
        r'<script id="admin-arquivo-edit-data" type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    assert match, "script#admin-arquivo-edit-data must be present on the plain list page"
    payload = json.loads(unescape(match.group(1)))
    assert payload is None


def test_admin_arquivos_filter_schema_and_typed_filters(client):
    titulo_a = "Arquivo Filtro Tipado A"
    titulo_b = "Arquivo Filtro Tipado B"

    _login_admin(client)

    with main.app.app_context():
        conn = main.get_db_connection()
        main.ensure_admin_arquivos_table(conn)
        conn.execute("DELETE FROM admin_arquivos WHERE titulo IN (?, ?)", (titulo_a, titulo_b))
        conn.execute(
            """
            INSERT INTO admin_arquivos (titulo, descricao, filename, original_filename, visivel, criado_em)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                titulo_a,
                "Descricao filtro alfa",
                "admin_arquivos/filtro_tipado_a.pdf",
                "filtro-tipado-a.pdf",
                1,
                "2026-01-10 10:00:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO admin_arquivos (titulo, descricao, filename, original_filename, visivel, criado_em)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                titulo_b,
                "Descricao filtro beta",
                "admin_arquivos/filtro_tipado_b.png",
                "filtro-tipado-b.png",
                0,
                "2026-02-15 10:00:00",
            ),
        )
        conn.commit()

    response = client.get(
        "/admin/arquivos",
        query_string={
            "titulo": "Tipado A",
            "descricao": "alfa",
            "tipo": "PDF",
            "data_upload_min": "2026-01-01",
            "data_upload_max": "2026-01-31",
            "visivel": "1",
        },
    )
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert '"param": "titulo"' in html
    assert '"param": "tipo"' in html
    assert '"param": "descricao"' in html
    assert '"param": "data_upload"' in html
    assert '"param": "visivel"' in html
    assert '"type": "text_contains"' in html
    assert '"type": "date_range"' in html
    assert '"type": "multi_select"' in html

    assert titulo_a in html
    assert titulo_b not in html


def test_best_effort_remove_admin_arquivo_file_rejects_parent_traversal(tmp_path, monkeypatch):
    upload_root = tmp_path / "uploads"
    upload_root.mkdir(parents=True, exist_ok=True)
    outside_file = tmp_path / "outside-file.pdf"
    outside_file.write_bytes(b"outside")

    monkeypatch.setitem(main.app.config, "UPLOAD_FOLDER", str(upload_root))

    with main.app.app_context():
        main._best_effort_remove_admin_arquivo_file(os.path.join("..", "outside-file.pdf"))

    assert outside_file.exists(), "helper deleted a file outside UPLOAD_FOLDER via parent traversal"


def test_best_effort_remove_admin_arquivo_file_rejects_absolute_external_path(tmp_path, monkeypatch):
    upload_root = tmp_path / "uploads"
    upload_root.mkdir(parents=True, exist_ok=True)
    external_dir = tmp_path / "external"
    external_dir.mkdir(parents=True, exist_ok=True)
    secret_file = external_dir / "secret.pdf"
    secret_file.write_bytes(b"secret")

    monkeypatch.setitem(main.app.config, "UPLOAD_FOLDER", str(upload_root))

    with main.app.app_context():
        main._best_effort_remove_admin_arquivo_file(str(secret_file))

    assert secret_file.exists(), "helper deleted a file outside UPLOAD_FOLDER via absolute path"


def test_best_effort_remove_admin_arquivo_file_removes_nested_in_root_file(tmp_path, monkeypatch):
    upload_root = tmp_path / "uploads"
    nested_dir = upload_root / "admin_arquivos"
    nested_dir.mkdir(parents=True, exist_ok=True)
    nested_file = nested_dir / "x.pdf"
    nested_file.write_bytes(b"legitimate")

    monkeypatch.setitem(main.app.config, "UPLOAD_FOLDER", str(upload_root))

    with main.app.app_context():
        main._best_effort_remove_admin_arquivo_file(os.path.join("admin_arquivos", "x.pdf"))

    assert not nested_file.exists(), "helper failed to clean up a legitimate in-root file"
