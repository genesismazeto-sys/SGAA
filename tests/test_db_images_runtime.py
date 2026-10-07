# coding: utf-8
"""STORAGE S1 runtime: database-backed profile photos and report screenshots.

New writes go to ``usuarios_foto`` / ``alunos_foto`` / ``reportes_captura`` in
the owning transaction -- never to a file -- and are served by
``images.profile_photo`` / ``images.reporte_captura`` with the verified type,
Content-Length, a SHA-256 ETag, ``nosniff`` and private caching.  Owners are
enforced per request; a legacy path still populated before the importer runs
is served through a narrow fallback that never wins over a database row.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import uuid

import pytest
from PIL import Image

import main
from app.user_accounts import create_usuario_with_access_level
from tests.session_support import stamp_auth_version
from tests.versioned_test_support import isolated_versioned_app_env

PASSWORD = "Senha-S1-imagens"


@pytest.fixture
def env(tmp_path):
    import app.auth as auth

    auth._login_attempts.clear()
    auth._login_attempts_by_account.clear()
    with isolated_versioned_app_env(tmp_path, "s1-images.db") as environment:
        environment["tmp_path"] = tmp_path
        yield environment
    auth._login_attempts.clear()
    auth._login_attempts_by_account.clear()


def _image(fmt="PNG", size=(64, 48), color=(200, 40, 40), mode="RGB") -> bytes:
    buffer = io.BytesIO()
    Image.new(mode, size, color).save(buffer, fmt)
    return buffer.getvalue()


def _admin(level="admin_total", overrides=()) -> tuple[int, str]:
    token = uuid.uuid4().hex[:8]
    email = f"s1-admin-{token}@example.invalid"
    with main.app.app_context():
        conn = main.get_db_connection()
        uid = int(create_usuario_with_access_level(
            conn, f"Admin S1 {token}", email, main.hash_password(PASSWORD), "admin", level,
            credential_state="personal",
        ).lastrowid)
        for recurso, escopo in overrides:
            conn.execute(
                "INSERT INTO usuarios_permissoes_acesso(usuario_id,recurso,escopo) VALUES(?,?,?)",
                (uid, recurso, escopo),
            )
        conn.commit()
    return uid, email


def _aluno() -> tuple[int, int, str]:
    token = uuid.uuid4().hex[:8]
    email = f"s1-aluno-{token}@example.invalid"
    with main.app.app_context():
        conn = main.get_db_connection()
        uid = int(create_usuario_with_access_level(
            conn, f"Aluno S1 {token}", email, main.hash_password(PASSWORD), "aluno", "usuario",
            credential_state="personal",
        ).lastrowid)
        aluno_id = conn.execute(
            "INSERT INTO alunos(usuario_id,nome,matricula,email,status) VALUES(?,?,?,?,'Ativo') RETURNING id",
            (uid, f"Aluno S1 {token}", f"S1-{token}", email),
        ).fetchone()[0]
        conn.commit()
    return uid, int(aluno_id), email


def _session(client, uid, user_type, name="S1"):
    with client.session_transaction() as sess:
        sess.clear()
        sess["user_id"] = uid
        sess["user_type"] = user_type
        sess["user_name"] = name
        stamp_auth_version(sess)


def _query(sql, params=()):
    with main.app.app_context():
        return main.get_db_connection().execute(sql, params).fetchall()


def _files_under(*roots):
    return [p for root in roots for p in root.rglob("*") if p.is_file()]


def _roots(env):
    return env["tmp_path"] / "uploads", env["tmp_path"] / "documentos_alunos"


def _post_admin_profile(client, email, **extra):
    data = {"nome": "Admin S1", "email": email, "remove_foto": "0", **extra}
    return client.post("/admin/meus_dados", data=data, content_type="multipart/form-data")


def _post_aluno_profile(client, email, matricula, **extra):
    data = {"nome": "Aluno S1", "email": email, "matricula": matricula, "remove_foto": "0", **extra}
    return client.post("/aluno/meus_dados", data=data, content_type="multipart/form-data")


def _assert_image_headers(response, content: bytes, mime: str):
    assert response.status_code == 200
    assert response.mimetype == mime
    assert response.data == content
    assert response.headers["Content-Length"] == str(len(content))
    assert response.headers["ETag"] == f'"{hashlib.sha256(content).hexdigest()}"'
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Cache-Control"] == "private, no-cache"
    assert response.headers["Content-Disposition"] == "inline"  # no filename
    assert "Cookie" in response.headers.get("Vary", "")


# --- administrator profile photo ---------------------------------------------------


def test_admin_photo_add_replace_remove_and_read(env):
    client = env["client"]
    uid, email = _admin()
    _session(client, uid, "admin")
    uploads, documents = _roots(env)

    assert client.get("/perfil/foto").status_code == 404  # nothing yet
    response = _post_admin_profile(client, email, foto_perfil=(io.BytesIO(_image()), "eu.png"))
    assert response.status_code == 302
    [row] = _query("SELECT mime_type, sha256, conteudo FROM usuarios_foto WHERE usuario_id=?", (uid,))
    assert row["mime_type"] == "image/jpeg"
    with client.session_transaction() as sess:
        assert sess["foto_perfil"] == row["sha256"][:16]
    _assert_image_headers(client.get("/perfil/foto"), bytes(row["conteudo"]), "image/jpeg")
    assert _query("SELECT foto_perfil FROM usuarios WHERE id=?", (uid,))[0][0] is None

    # The header and Meus dados point at the database route with the version marker.
    html = client.get("/admin/meus_dados").get_data(as_text=True)
    assert f'/perfil/foto?v={row["sha256"][:16]}' in html
    assert "/uploads/" not in html

    # Replace: still exactly one row, new content.
    _post_admin_profile(client, email, foto_perfil=(io.BytesIO(_image(color=(1, 2, 250))), "nova.jpg"))
    rows = _query("SELECT sha256 FROM usuarios_foto WHERE usuario_id=?", (uid,))
    assert len(rows) == 1 and rows[0]["sha256"] != row["sha256"]

    # Remove: the row goes, the route answers 404, the session marker is gone.
    _post_admin_profile(client, email, remove_foto="1")
    assert _query("SELECT count(*) FROM usuarios_foto WHERE usuario_id=?", (uid,))[0][0] == 0
    assert client.get("/perfil/foto").status_code == 404
    with client.session_transaction() as sess:
        assert "foto_perfil" not in sess
    assert _files_under(uploads, documents) == []


def test_invalid_and_oversized_admin_photos_change_nothing_but_the_profile_commits(env):
    client = env["client"]
    uid, email = _admin()
    _session(client, uid, "admin")
    response = _post_admin_profile(client, email, nome="Admin Renomeado",
                                   foto_perfil=(io.BytesIO(b"texto qualquer"), "foto.png"))
    assert response.status_code == 302
    assert _query("SELECT nome FROM usuarios WHERE id=?", (uid,))[0][0] == "Admin Renomeado"
    big = b"\x89PNG\r\n\x1a\n" + b"\x00" * (2 * 1024 * 1024)
    _post_admin_profile(client, email, foto_perfil=(io.BytesIO(big), "grande.png"))
    with client.session_transaction() as sess:
        flashes = [str(message) for _category, message in sess.get("_flashes", [])]
    assert any("Foto inválida" in message for message in flashes)
    assert any("Arquivo muito grande. Tamanho máximo: 2.0 MB." in message for message in flashes)
    assert _query("SELECT count(*) FROM usuarios_foto WHERE usuario_id=?", (uid,))[0][0] == 0


def test_admin_photo_keeps_the_former_arquivos_view_gate(env):
    client = env["client"]
    uid, email = _admin("administrativo", overrides=(("arquivos", "none"),))
    _session(client, uid, "admin")
    _post_admin_profile(client, email, foto_perfil=(io.BytesIO(_image()), "eu.png"))
    assert _query("SELECT count(*) FROM usuarios_foto WHERE usuario_id=?", (uid,))[0][0] == 1
    assert client.get("/perfil/foto").status_code == 403


# --- student profile photo -----------------------------------------------------------


def test_student_photo_add_replace_remove_read_and_isolation(env):
    client = env["client"]
    uid, aluno_id, email = _aluno()
    other_uid, other_aluno_id, other_email = _aluno()
    matricula = _query("SELECT matricula FROM alunos WHERE id=?", (aluno_id,))[0][0]
    _session(client, uid, "aluno")

    response = _post_aluno_profile(client, email, matricula,
                                   foto_perfil=(io.BytesIO(_image("PNG", mode="RGBA", color=(1, 2, 3, 90))), "x.jpg"))
    assert response.status_code == 302
    [row] = _query("SELECT mime_type, sha256, conteudo FROM alunos_foto WHERE aluno_id=?", (aluno_id,))
    assert row["mime_type"] == "image/png"  # real transparency keeps PNG
    _assert_image_headers(client.get("/perfil/foto"), bytes(row["conteudo"]), "image/png")
    assert f'/perfil/foto?v={row["sha256"][:16]}' in client.get("/aluno/meus_dados").get_data(as_text=True)

    # Another student sees only their own (absent) photo; there is no id to change.
    _session(client, other_uid, "aluno")
    assert client.get("/perfil/foto").status_code == 404
    assert client.get(f"/perfil/foto?aluno_id={aluno_id}").status_code == 404

    _session(client, uid, "aluno")
    _post_aluno_profile(client, email, matricula, foto_perfil=(io.BytesIO(_image("JPEG")), "y.png"))
    rows = _query("SELECT mime_type FROM alunos_foto WHERE aluno_id=?", (aluno_id,))
    assert [r[0] for r in rows] == ["image/jpeg"]
    _post_aluno_profile(client, email, matricula, remove_foto="1")
    assert _query("SELECT count(*) FROM alunos_foto WHERE aluno_id=?", (aluno_id,))[0][0] == 0
    assert _files_under(*_roots(env)) == []


def test_profile_photo_requires_a_session(env):
    response = env["client"].get("/perfil/foto")
    assert response.status_code == 302 and "/login" in response.headers["Location"]


def test_deleting_the_owner_cascades_the_photo(env):
    client = env["client"]
    uid, aluno_id, email = _aluno()
    matricula = _query("SELECT matricula FROM alunos WHERE id=?", (aluno_id,))[0][0]
    _session(client, uid, "aluno")
    _post_aluno_profile(client, email, matricula, foto_perfil=(io.BytesIO(_image()), "x.png"))
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("DELETE FROM alunos WHERE id=?", (aluno_id,))
        conn.commit()
    assert _query("SELECT count(*) FROM alunos_foto WHERE aluno_id=?", (aluno_id,))[0][0] == 0


# --- login session marker -------------------------------------------------------------


def test_login_stores_a_version_marker_never_a_path(env):
    client = env["client"]
    uid, email = _admin()
    _session(client, uid, "admin")
    _post_admin_profile(client, email, foto_perfil=(io.BytesIO(_image()), "eu.png"))
    digest = _query("SELECT sha256 FROM usuarios_foto WHERE usuario_id=?", (uid,))[0][0]
    with client.session_transaction() as sess:
        sess.clear()
    client.post("/login", data={"email": email, "senha": PASSWORD})
    with client.session_transaction() as sess:
        assert sess["user_id"] == uid and sess["foto_perfil"] == digest[:16]
    page = client.get("/admin/meus_dados").get_data(as_text=True)
    assert f'src="/perfil/foto?v={digest[:16]}"' in page


# --- report screenshots ----------------------------------------------------------------


def _student_report(client, email_uid, titulo, captura=None):
    data = {"categoria": "Outro", "titulo": titulo, "descricao": "Descricao S1"}
    if captura is not None:
        data["captura_tela"] = captura
    return client.post("/aluno/reportar", data=data, content_type="multipart/form-data")


@pytest.mark.parametrize(("fmt", "mime"), [("PNG", "image/png"), ("JPEG", "image/jpeg"), ("WEBP", "image/webp")])
def test_report_screenshot_create_read_authorize_and_delete(env, fmt, mime):
    client = env["client"]
    uid, aluno_id, _email = _aluno()
    other_uid, _other_aluno, _ = _aluno()
    shot = _image(fmt, size=(320, 200))
    _session(client, uid, "aluno")
    titulo = f"Reporte S1 {uuid.uuid4().hex[:6]}"
    assert _student_report(client, uid, titulo, (io.BytesIO(shot), "captura.bin")).status_code == 302
    [rep] = _query("SELECT id, screenshot_filename FROM reportes WHERE titulo=?", (titulo,))
    assert rep["screenshot_filename"] is None
    [cap] = _query("SELECT mime_type, conteudo FROM reportes_captura WHERE reporte_id=?", (rep["id"],))
    assert cap["mime_type"] == mime and bytes(cap["conteudo"]) == shot  # stored as uploaded
    url = f"/reportes/{rep['id']}/captura"

    # Listing JSON carries a URL, never a path or filename.
    page = client.get("/aluno/reportar").get_data(as_text=True)
    data = json.loads(re.search(r'id="meus-reportes-data"[^>]*>(.*?)</script>', page, re.S).group(1))
    [entry] = [r for r in data if r["id"] == rep["id"]]
    assert entry["screenshot_url"].startswith(url + "?v=")
    assert "screenshot_filename" not in entry and "captura.bin" not in page

    _assert_image_headers(client.get(url), shot, mime)
    _session(client, other_uid, "aluno")
    assert client.get(url).status_code == 404  # another student cannot probe it
    admin_uid, _ = _admin()
    _session(client, admin_uid, "admin")
    _assert_image_headers(client.get(url), shot, mime)
    admin_html = client.get("/admin/reportes").get_data(as_text=True)
    assert url + "?v=" in admin_html

    assert client.post(f"/admin/reportes/{rep['id']}/deletar").status_code == 302
    assert _query("SELECT count(*) FROM reportes_captura WHERE reporte_id=?", (rep["id"],))[0][0] == 0
    assert client.get(url).status_code == 404
    assert _files_under(*_roots(env)) == []


def test_report_screenshot_admin_gate_needs_reportes_and_arquivos_view(env):
    client = env["client"]
    uid, aluno_id, _ = _aluno()
    _session(client, uid, "aluno")
    titulo = f"Reporte gate {uuid.uuid4().hex[:6]}"
    _student_report(client, uid, titulo, (io.BytesIO(_image()), "c.png"))
    reporte_id = _query("SELECT id FROM reportes WHERE titulo=?", (titulo,))[0][0]
    for overrides in ((("arquivos", "none"),), (("reportes", "none"),)):
        admin_uid, _ = _admin("administrativo", overrides=overrides)
        _session(client, admin_uid, "admin")
        assert client.get(f"/reportes/{reporte_id}/captura").status_code == 403, overrides
    with client.session_transaction() as sess:
        sess.clear()
    assert client.get(f"/reportes/{reporte_id}/captura").status_code == 302


def test_admin_created_report_stores_screenshot_in_the_same_transaction(env):
    client = env["client"]
    _uid, aluno_id, _ = _aluno()
    admin_uid, _ = _admin()
    _session(client, admin_uid, "admin")
    titulo = f"Reporte admin {uuid.uuid4().hex[:6]}"
    response = client.post("/admin/reportes/novo", data={
        "aluno_id": str(aluno_id), "categoria": "Outro", "titulo": titulo, "descricao": "D",
        "captura_tela": (io.BytesIO(_image("WEBP")), "a.webp"),
    }, content_type="multipart/form-data")
    assert response.status_code == 302
    [row] = _query(
        "SELECT r.id, c.mime_type FROM reportes r JOIN reportes_captura c ON c.reporte_id = r.id WHERE r.titulo=?",
        (titulo,),
    )
    assert row["mime_type"] == "image/webp"


def test_invalid_or_oversized_screenshots_create_no_report(env):
    client = env["client"]
    uid, _aluno_id, _ = _aluno()
    _session(client, uid, "aluno")
    for captura, message in (
        ((io.BytesIO(b"<html>not an image</html>"), "captura.png"), "PNG, JPG, JPEG ou WEBP"),
        (
            (io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"\x00" * (4 * 1024 * 1024)), "enorme.png"),
            "Arquivo muito grande. Tamanho máximo: 4.0 MB.",
        ),
    ):
        titulo = f"Reporte invalido {uuid.uuid4().hex[:6]}"
        response = _student_report(client, uid, titulo, captura)
        assert response.status_code == 200
        assert message in response.get_data(as_text=True)
        assert titulo in response.get_data(as_text=True)  # the form keeps what was typed
        assert _query("SELECT count(*) FROM reportes WHERE titulo=?", (titulo,))[0][0] == 0
    admin_uid, _ = _admin()
    _session(client, admin_uid, "admin")
    titulo = f"Reporte admin invalido {uuid.uuid4().hex[:6]}"
    client.post("/admin/reportes/novo", data={
        "aluno_id": str(_aluno_id), "categoria": "Outro", "titulo": titulo, "descricao": "D",
        "captura_tela": (io.BytesIO(b"GIF89a....."), "a.png"),
    }, content_type="multipart/form-data")
    assert _query("SELECT count(*) FROM reportes WHERE titulo=?", (titulo,))[0][0] == 0


# --- conditional requests ----------------------------------------------------------------


def test_matching_if_none_match_gets_304_without_body(env):
    client = env["client"]
    uid, email = _admin()
    _session(client, uid, "admin")
    _post_admin_profile(client, email, foto_perfil=(io.BytesIO(_image()), "eu.png"))
    first = client.get("/perfil/foto")
    etag = first.headers["ETag"]
    again = client.get("/perfil/foto", headers={"If-None-Match": etag})
    assert again.status_code == 304 and again.data == b""
    assert again.headers["ETag"] == etag
    assert again.headers["Cache-Control"] == "private, no-cache"
    assert client.get("/perfil/foto", headers={"If-None-Match": '"other"'}).status_code == 200


# --- legacy fallback ----------------------------------------------------------------------


def test_legacy_path_is_served_until_imported_but_never_over_a_database_row(env):
    client = env["client"]
    uid, aluno_id, email = _aluno()
    _uploads, documents = _roots(env)
    legacy_rel = f"aluno_{aluno_id} - aluno-s1/perfil/foto-perfil-antiga.png"
    legacy_path = documents / legacy_rel
    legacy_path.parent.mkdir(parents=True)
    legacy = _image("PNG", color=(5, 200, 5))
    legacy_path.write_bytes(legacy)
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("UPDATE alunos SET foto_perfil=? WHERE id=?", (legacy_rel, aluno_id))
        conn.commit()

    # Login records a non-path marker for the legacy reference.
    client.post("/login", data={"email": email, "senha": PASSWORD})
    with client.session_transaction() as sess:
        marker = sess["foto_perfil"]
    assert marker.startswith("legacy-") and "aluno_" not in marker and "/" not in marker
    _assert_image_headers(client.get("/perfil/foto"), legacy, "image/png")

    # A database row always wins over the still-populated legacy path.
    newer = _image("JPEG", color=(9, 9, 200))
    with main.app.app_context():
        conn = main.get_db_connection()
        from app.db_images import ALUNOS_FOTO
        from app.image_validation import detect_image, SCREENSHOT_FORMATS

        stored = detect_image(newer, formats=SCREENSHOT_FORMATS, max_pixels=10**6)
        conn.execute(
            "INSERT INTO alunos_foto(aluno_id,mime_type,size_bytes,sha256,width,height,conteudo)"
            " VALUES(?,?,?,?,?,?,?)",
            (aluno_id, stored.mime_type, stored.size_bytes, stored.sha256, stored.width, stored.height, newer),
        )
        conn.commit()
        assert ALUNOS_FOTO.table == "alunos_foto"
    _assert_image_headers(client.get("/perfil/foto"), newer, "image/jpeg")
    assert legacy_path.read_bytes() == legacy  # the legacy file is never touched


def test_legacy_fallback_refuses_non_images_and_escaping_paths(env):
    client = env["client"]
    uid, aluno_id, _email = _aluno()
    _uploads, documents = _roots(env)
    bad_rel = f"aluno_{aluno_id} - x/perfil/falso.png"
    (documents / bad_rel).parent.mkdir(parents=True)
    (documents / bad_rel).write_bytes(b"<script>alert(1)</script>")
    _session(client, uid, "aluno")
    for reference in (bad_rel, "../../fora.png", f"aluno_{aluno_id} - x/perfil/ausente.png"):
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute("UPDATE alunos SET foto_perfil=? WHERE id=?", (reference, aluno_id))
            conn.commit()
        assert client.get("/perfil/foto").status_code == 404, reference


def test_legacy_screenshot_reference_is_served_to_its_owner(env):
    client = env["client"]
    uid, aluno_id, _ = _aluno()
    _session(client, uid, "aluno")
    titulo = f"Reporte legado {uuid.uuid4().hex[:6]}"
    _student_report(client, uid, titulo)
    reporte_id = _query("SELECT id FROM reportes WHERE titulo=?", (titulo,))[0][0]
    _uploads, documents = _roots(env)
    rel = f"aluno_{aluno_id} - x/reportes/reporte{aluno_id}-captura.webp"
    (documents / rel).parent.mkdir(parents=True)
    shot = _image("WEBP")
    (documents / rel).write_bytes(shot)
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("UPDATE reportes SET screenshot_filename=? WHERE id=?", (rel, reporte_id))
        conn.commit()
    page = client.get("/aluno/reportar").get_data(as_text=True)
    assert f"/reportes/{reporte_id}/captura?v=legacy-" in page and rel not in page
    _assert_image_headers(client.get(f"/reportes/{reporte_id}/captura"), shot, "image/webp")


def test_uploaded_file_still_serves_legacy_student_documents_for_admin(env):
    """UT-17 coverage carried forward: the unchanged ``uploaded_file`` endpoint
    keeps serving pre-v13 files from DOCUMENTOS_ALUNOS_FOLDER to an admin."""
    client = env["client"]
    _uid, aluno_id, _ = _aluno()
    uploads, documents = _roots(env)
    rel = f"aluno_{aluno_id} - x/reportes/antigo.png"
    (documents / rel).parent.mkdir(parents=True)
    (documents / rel).write_bytes(_image())
    admin_uid, _ = _admin()
    _session(client, admin_uid, "admin")
    served = client.get(f"/uploads/{rel}")
    assert served.status_code == 200 and served.data == _image()
    assert not (uploads / rel).exists()
