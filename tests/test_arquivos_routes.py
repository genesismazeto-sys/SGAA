from __future__ import annotations

import secrets

import pytest

import main
from app.arquivos import create_arquivo, update_arquivo
from tests.test_arquivos_google_drive import FakeManagedStorage, PDF, PNG, _file


@pytest.fixture()
def route_env(tmp_path):
    app = main.app
    upload_root = tmp_path / "uploads"
    upload_root.mkdir()
    storage = FakeManagedStorage()
    previous_upload_root = app.config.get("UPLOAD_FOLDER")
    previous_storage = app.extensions.get("arquivo_storage")
    app.config["UPLOAD_FOLDER"] = str(upload_root)
    app.extensions["arquivo_storage"] = storage
    created_ids = []
    with app.app_context():
        main.init_db()
    client = app.test_client()
    try:
        yield client, storage, upload_root, created_ids
    finally:
        with app.app_context():
            conn = main.get_db_connection()
            if created_ids:
                placeholders = ",".join("?" for _ in created_ids)
                conn.execute(
                    f"DELETE FROM admin_arquivos WHERE id IN ({placeholders})",
                    tuple(created_ids),
                )
                conn.commit()
        app.config["UPLOAD_FOLDER"] = previous_upload_root
        if previous_storage is None:
            app.extensions.pop("arquivo_storage", None)
        else:
            app.extensions["arquivo_storage"] = previous_storage


def _login_student(client):
    with client.session_transaction() as session:
        session["user_id"] = 999999
        session["user_type"] = "aluno"
        session["user_name"] = "Student"


def _login_admin_actor(client, user_id):
    with client.session_transaction() as session:
        session["user_id"] = user_id
        session["user_type"] = "admin"
        session["user_name"] = "Admin actor"


def _create_google(created_ids, *, visible: int, content=PDF, name="student.pdf"):
    with main.app.app_context():
        conn = main.get_db_connection()
        arquivo_id = create_arquivo(
            conn,
            file_storage=_file(content, name),
            titulo=f"Arquivo {secrets.token_hex(5)}",
            descricao=None,
            visivel=visible,
            uploader_user_id=1,
            operation_key=f"route-{secrets.token_urlsafe(16)}",
            max_file_bytes=main.app.config["MAX_CONTENT_LENGTH"],
        )
    created_ids.append(arquivo_id)
    return arquivo_id


def _set_visibility(conn, arquivo_id, visible, *, title="Visibility transition"):
    update_arquivo(
        conn,
        arquivo_id=arquivo_id,
        file_storage=None,
        titulo=title,
        descricao=None,
        visivel=visible,
        uploader_user_id=1,
        operation_key=None,
        max_file_bytes=main.app.config["MAX_CONTENT_LENGTH"],
        upload_root=main.app.config["UPLOAD_FOLDER"],
    )


def test_student_google_visibility_inline_download_and_no_drive_id_bypass(route_env):
    client, _storage, _upload_root, created_ids = route_env
    visible_id = _create_google(created_ids, visible=1)
    hidden_id = _create_google(created_ids, visible=0, content=PNG, name="hidden.png")
    _login_student(client)

    listing = client.get("/aluno/arquivos")
    assert listing.status_code == 200
    assert f'/aluno/arquivos/ver/{visible_id}'.encode() in listing.data
    assert f'/aluno/arquivos/ver/{hidden_id}'.encode() not in listing.data

    inline = client.get(f"/aluno/arquivos/ver/{visible_id}")
    assert inline.status_code == 200 and inline.data == PDF
    assert inline.mimetype == "application/pdf"
    assert inline.headers["X-Content-Type-Options"] == "nosniff"
    assert inline.headers["Cache-Control"] == "private, no-store"
    assert "inline" in inline.headers["Content-Disposition"]

    download = client.get(f"/aluno/arquivos/download/{visible_id}")
    assert download.status_code == 200 and download.data == PDF
    assert "attachment" in download.headers["Content-Disposition"]
    assert download.headers["Cache-Control"] == "private, no-store"

    assert client.get(f"/aluno/arquivos/ver/{hidden_id}").status_code == 302
    assert client.get("/aluno/arquivos/ver/remote-1").status_code == 404


def test_student_hidden_only_listing_is_empty_without_provider_access(route_env):
    client, storage, _upload_root, created_ids = route_env
    hidden_id = _create_google(created_ids, visible=1, content=PNG, name="hidden-only.png")
    for name in ("download_calls", "trash_calls", "untrash_calls"):
        setattr(storage, name, [])
    original_download = storage.download
    original_trash = storage.trash
    original_untrash = storage.untrash
    storage.download = lambda file_id: (storage.download_calls.append(file_id), original_download(file_id))[1]
    storage.trash = lambda file_id: (storage.trash_calls.append(file_id), original_trash(file_id))[1]
    storage.untrash = lambda file_id: (storage.untrash_calls.append(file_id), original_untrash(file_id))[1]
    _login_student(client)
    with main.app.app_context():
        conn = main.get_db_connection()
        assert client.get("/aluno/arquivos").status_code == 200
        assert f"/aluno/arquivos/ver/{hidden_id}".encode() in client.get("/aluno/arquivos").data
        _set_visibility(conn, hidden_id, 0)
        provider_calls = {
            name: len(getattr(storage, name))
            for name in ("folder_calls", "upload_calls", "find_calls", "download_calls", "trash_calls", "untrash_calls")
        }

    listing = client.get("/aluno/arquivos")

    assert listing.status_code == 200
    assert f"/aluno/arquivos/ver/{hidden_id}".encode() not in listing.data
    assert client.get(f"/aluno/arquivos/ver/{hidden_id}").status_code == 302
    assert client.get(f"/aluno/arquivos/download/{hidden_id}").status_code == 302
    assert {
        name: len(getattr(storage, name))
        for name in provider_calls
    } == provider_calls

    _login_admin_actor(client, 1)
    assert client.get("/admin/arquivos").status_code == 200
    assert f"data-arquivo-id=\"{hidden_id}\"".encode() in client.get("/admin/arquivos").data

    _login_student(client)
    with main.app.app_context():
        _set_visibility(main.get_db_connection(), hidden_id, 1)
    assert f"/aluno/arquivos/ver/{hidden_id}".encode() in client.get("/aluno/arquivos").data


def test_student_legacy_inline_download_and_path_escape(route_env):
    client, _storage, upload_root, created_ids = route_env
    nested = upload_root / "admin_arquivos"
    nested.mkdir()
    (nested / "legacy.pdf").write_bytes(PDF)
    outside = upload_root.parent / "outside.pdf"
    outside.write_bytes(PDF)
    with main.app.app_context():
        conn = main.get_db_connection()
        good = conn.execute(
            "INSERT INTO admin_arquivos(titulo,filename,original_filename) VALUES('Legacy','admin_arquivos/legacy.pdf','legacy.pdf')"
        ).lastrowid
        bad = conn.execute(
            "INSERT INTO admin_arquivos(titulo,filename,original_filename) VALUES('Escape','../outside.pdf','outside.pdf')"
        ).lastrowid
        conn.commit()
    created_ids.extend((good, bad))
    _login_student(client)

    inline = client.get(f"/aluno/arquivos/ver/{good}")
    download = client.get(f"/aluno/arquivos/download/{good}")
    assert inline.status_code == 200 and inline.data == PDF
    assert download.status_code == 200 and "attachment" in download.headers["Content-Disposition"]
    assert client.get(f"/aluno/arquivos/ver/{bad}").status_code == 302
    assert outside.exists()


def test_student_local_legacy_visibility_transition(route_env, monkeypatch):
    client, _storage, upload_root, created_ids = route_env
    legacy_path = upload_root / "admin_arquivos" / "transition.pdf"
    legacy_path.parent.mkdir()
    legacy_path.write_bytes(PDF)
    with main.app.app_context():
        conn = main.get_db_connection()
        arquivo_id = conn.execute(
            "INSERT INTO admin_arquivos(titulo,filename,original_filename) VALUES(?,?,?)",
            ("Legacy transition", "admin_arquivos/transition.pdf", "transition.pdf"),
        ).lastrowid
        conn.commit()
    created_ids.append(arquivo_id)
    _login_student(client)
    assert client.get("/aluno/arquivos").status_code == 200
    assert f"/aluno/arquivos/ver/{arquivo_id}".encode() in client.get("/aluno/arquivos").data
    _login_admin_actor(client, 1)
    with main.app.app_context():
        _set_visibility(main.get_db_connection(), arquivo_id, 0, title="Legacy transition")
    _login_student(client)
    fail_hidden_read = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("hidden local read"))
    monkeypatch.setattr("app.arquivos.read_arquivo_content", fail_hidden_read)
    monkeypatch.setattr("app.views.aluno.read_arquivo_content", fail_hidden_read)
    assert client.get("/aluno/arquivos").status_code == 200
    assert f"/aluno/arquivos/ver/{arquivo_id}".encode() not in client.get("/aluno/arquivos").data
    assert client.get(f"/aluno/arquivos/ver/{arquivo_id}").status_code == 302
    assert client.get(f"/aluno/arquivos/download/{arquivo_id}").status_code == 302
    with main.app.app_context():
        _set_visibility(main.get_db_connection(), arquivo_id, 1, title="Legacy transition")
    assert f"/aluno/arquivos/ver/{arquivo_id}".encode() in client.get("/aluno/arquivos").data


def test_student_hidden_replacement_cleanup_is_excluded_without_provider_calls(route_env):
    client, storage, _upload_root, created_ids = route_env
    arquivo_id = _create_google(created_ids, visible=1, content=PNG, name="replacement-state.png")
    for name in ("download_calls", "trash_calls", "untrash_calls"):
        setattr(storage, name, [])
    original_download = storage.download
    original_trash = storage.trash
    original_untrash = storage.untrash
    storage.download = lambda file_id: (storage.download_calls.append(file_id), original_download(file_id))[1]
    storage.trash = lambda file_id: (storage.trash_calls.append(file_id), original_trash(file_id))[1]
    storage.untrash = lambda file_id: (storage.untrash_calls.append(file_id), original_untrash(file_id))[1]
    storage.fail_trash = True
    with main.app.app_context():
        conn = main.get_db_connection()
        assert not update_arquivo(
            conn,
            arquivo_id=arquivo_id,
            file_storage=_file(PDF, "replacement-state-new.pdf"),
            titulo="Replacement state",
            descricao=None,
            visivel=1,
            uploader_user_id=1,
            operation_key="replacement-state-transition",
            max_file_bytes=main.app.config["MAX_CONTENT_LENGTH"],
            upload_root=main.app.config["UPLOAD_FOLDER"],
        )
        _set_visibility(conn, arquivo_id, 0, title="Replacement state")
    _login_student(client)
    provider_calls = {
        name: len(getattr(storage, name))
        for name in ("folder_calls", "upload_calls", "find_calls", "download_calls", "trash_calls", "untrash_calls")
    }
    assert client.get("/aluno/arquivos").status_code == 200
    assert f"/aluno/arquivos/ver/{arquivo_id}".encode() not in client.get("/aluno/arquivos").data
    assert client.get(f"/aluno/arquivos/ver/{arquivo_id}").status_code == 302
    assert client.get(f"/aluno/arquivos/download/{arquivo_id}").status_code == 302
    assert {
        name: len(getattr(storage, name))
        for name in provider_calls
    } == provider_calls


def test_admin_coordinator_and_consultant_preserve_arquivos_rbac(route_env):
    client, _storage, _upload_root, created_ids = route_env
    actor_ids = {}
    with main.app.app_context():
        conn = main.get_db_connection()
        for level in ("admin_total", "administrativo", "consultivo"):
            actor_ids[level] = conn.execute(
                """INSERT INTO usuarios(nome,email,senha,tipo,nivel_acesso)
                   VALUES(?,?,?,'admin',?) RETURNING id""",
                (level, f"arquivo-{level}-{secrets.token_hex(4)}@example.test", "x", level),
            ).fetchone()["id"]
        conn.commit()
    try:
        for level, user_id in actor_ids.items():
            _login_admin_actor(client, user_id)
            assert client.get("/admin/arquivos").status_code == 200, level

        with main.app.app_context():
            conn = main.get_db_connection()
            consultant_target = conn.execute(
                "INSERT INTO admin_arquivos(titulo,filename) VALUES('Consultant target','missing.pdf')"
            ).lastrowid
            coordinator_target = conn.execute(
                "INSERT INTO admin_arquivos(titulo,filename) VALUES('Coordinator target','missing.pdf')"
            ).lastrowid
            admin_target = conn.execute(
                "INSERT INTO admin_arquivos(titulo,filename) VALUES('Admin target','missing.pdf')"
            ).lastrowid
            conn.commit()
        created_ids.extend((consultant_target, coordinator_target, admin_target))

        _login_admin_actor(client, actor_ids["consultivo"])
        denied = client.post(f"/admin/arquivos/{consultant_target}/deletar")
        assert denied.status_code == 302 and denied.headers["Location"].endswith("/admin/dashboard")
        with main.app.app_context():
            assert main.get_db_connection().execute(
                "SELECT 1 FROM admin_arquivos WHERE id=?", (consultant_target,)
            ).fetchone()

        for level, target in (
            ("administrativo", coordinator_target),
            ("admin_total", admin_target),
        ):
            _login_admin_actor(client, actor_ids[level])
            allowed = client.post(f"/admin/arquivos/{target}/deletar")
            assert allowed.status_code == 302 and allowed.headers["Location"].endswith("/admin/arquivos")
            with main.app.app_context():
                assert main.get_db_connection().execute(
                    "SELECT 1 FROM admin_arquivos WHERE id=?", (target,)
                ).fetchone() is None
    finally:
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.executemany("DELETE FROM usuarios WHERE id=?", [(value,) for value in actor_ids.values()])
            conn.commit()
