# coding: utf-8
"""STORAGE S1 on real PostgreSQL (E-PG1): database-backed image runtime.

Runs only with ``SGAA_PG_TEST_URL`` (a role with CREATE DATABASE); otherwise
the module skips (REAL-PG EVIDENCE: ABSENT).  One disposable database (random
per-run prefix) is provisioned through ``app.pg_schema``, ``app.db.DATABASE_URL``
points the real ``main.app`` at it, and it is dropped at teardown with the
accepted guard model.  A SQLite tripwire refuses any SQLite connection during
a request; every write is confirmed by an independent autocommit observer.

Covered on PostgreSQL: the ``INSERT ... ON CONFLICT DO UPDATE`` upsert with a
``bytea`` parameter, ``INSERT ... RETURNING id`` + image row in one
transaction, the ``LEFT JOIN reportes_captura`` listings, delivery with ETag /
304, owner isolation, photo removal and ``ON DELETE CASCADE``.
"""
from __future__ import annotations

import hashlib
import io
import os
import secrets
import sqlite3
from urllib.parse import urlsplit, urlunsplit

import pytest
from PIL import Image

PG_URL = os.environ.get("SGAA_PG_TEST_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not PG_URL, reason="SGAA_PG_TEST_URL is not configured -- REAL-PG EVIDENCE: ABSENT"
)

psycopg = pytest.importorskip("psycopg")

from app import db as app_db  # noqa: E402
from app import pg_schema  # noqa: E402

RUN_PREFIX = f"sgaa_s1rt_test_{secrets.token_hex(4)}_"
PROTECTED_DATABASES = frozenset({"postgres", "template0", "template1", "sgaa_qual"})
ADMIN_EMAIL = "s1rt.admin@example.test"
STUDENT_EMAIL = "s1rt.aluno@example.test"
OTHER_EMAIL = "s1rt.outro@example.test"
PASSWORD = "s1rt-senha"


def _url(database):
    parts = urlsplit(PG_URL)
    return urlunsplit((parts.scheme, parts.netloc, "/" + database, "connect_timeout=10", ""))


def _connect(url, *, autocommit=False):
    return psycopg.connect(url, prepare_threshold=None, autocommit=autocommit, connect_timeout=10)


def _image(fmt="PNG", color=(10, 20, 200), size=(90, 60)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, fmt)
    return buffer.getvalue()


class _Env:
    pass


@pytest.fixture(scope="module")
def env():
    import flask
    import main
    from app.security.passwords import hash_password
    from app.user_accounts import create_usuario_with_access_level

    admin = _connect(PG_URL, autocommit=True)
    database = f"{RUN_PREFIX}{secrets.token_hex(3)}"
    admin.execute(f'CREATE DATABASE "{database}"')
    patcher = pytest.MonkeyPatch()
    observer = None
    try:
        url = _url(database)
        connection = _connect(url)
        try:
            assert pg_schema.provision_pg_schema(connection)["status"] == "provisioned"
            connection.commit()
        finally:
            connection.close()
        observer = _connect(url, autocommit=True)
        patcher.setattr(app_db, "DATABASE_URL", url)
        patcher.setitem(main.app.config, "TESTING", True)
        assert app_db.database_backend() == "postgres"

        e = _Env()
        e.app, e.observer, e.database = main.app, observer, database
        production = app_db._connect_postgres()
        try:
            e.ids = {}
            for nome, email, kind, level in (
                ("S1 Admin", ADMIN_EMAIL, "admin", "admin_total"),
                ("S1 Aluno", STUDENT_EMAIL, "aluno", "usuario"),
                ("S1 Outro", OTHER_EMAIL, "aluno", "usuario"),
            ):
                cursor = create_usuario_with_access_level(
                    production, nome, email, hash_password(PASSWORD), kind, level, credential_state="personal",
                )
                e.ids[email] = int(cursor.usuario_id)
            production.commit()
        finally:
            production.close()
        e.alunos = {}
        for email, matricula in ((STUDENT_EMAIL, "S1RT-1"), (OTHER_EMAIL, "S1RT-2")):
            e.alunos[email] = observer.execute(
                "INSERT INTO alunos(usuario_id,nome,matricula,email,status) VALUES(%s,%s,%s,%s,'Ativo') RETURNING id",
                (e.ids[email], "S1 Aluno", matricula, email),
            ).fetchone()[0]

        e.sqlite_calls = []
        real_connect = sqlite3.connect

        def _tripwire(*args, **kwargs):
            if flask.has_request_context():
                e.sqlite_calls.append(flask.request.path)
                raise AssertionError("SQLite connection opened during a real-PG request")
            return real_connect(*args, **kwargs)

        patcher.setattr(sqlite3, "connect", _tripwire)
        try:
            yield e
        finally:
            with main.app.app_context():
                app_db.close_db_connection(None)
    finally:
        patcher.undo()
        if observer is not None and not observer.closed:
            observer.close()
        assert database not in PROTECTED_DATABASES and database.startswith(RUN_PREFIX)
        try:
            admin.execute(f'DROP DATABASE IF EXISTS "{database}"')
        except psycopg.errors.ObjectInUse:
            admin.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
        leftovers = admin.execute(
            "SELECT count(*) FROM pg_database WHERE starts_with(datname, %s)", (RUN_PREFIX,)
        ).fetchone()[0]
        admin.close()
        assert leftovers == 0


def _login(env, email):
    client = env.app.test_client()
    response = client.post("/login", data={"email": email, "senha": PASSWORD})
    assert response.status_code == 302
    return client


def test_profile_photo_upsert_read_304_and_remove_on_postgresql(env):
    client = _login(env, ADMIN_EMAIL)
    uid = env.ids[ADMIN_EMAIL]
    for color in ((200, 0, 0), (0, 200, 0)):  # insert, then the ON CONFLICT update
        response = client.post(
            "/admin/meus_dados",
            data={"nome": "S1 Admin", "email": ADMIN_EMAIL, "remove_foto": "0",
                  "foto_perfil": (io.BytesIO(_image(color=color)), "eu.png")},
            content_type="multipart/form-data",
        )
        assert response.status_code == 302
        rows = env.observer.execute(
            "SELECT sha256, conteudo, octet_length(conteudo) = size_bytes,"
            " encode(sha256(conteudo), 'hex') = sha256 FROM usuarios_foto WHERE usuario_id=%s",
            (uid,),
        ).fetchall()
        assert len(rows) == 1 and rows[0][2] and rows[0][3]
        served = client.get("/perfil/foto")
        assert served.status_code == 200 and served.mimetype == "image/jpeg"
        assert served.data == bytes(rows[0][1])
        assert served.headers["ETag"] == f'"{rows[0][0]}"'
        assert client.get("/perfil/foto", headers={"If-None-Match": served.headers["ETag"]}).status_code == 304
    response = client.post(
        "/admin/meus_dados",
        data={"nome": "S1 Admin", "email": ADMIN_EMAIL, "remove_foto": "1"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    assert env.observer.execute("SELECT count(*) FROM usuarios_foto").fetchone()[0] == 0
    assert client.get("/perfil/foto").status_code == 404
    assert env.sqlite_calls == []


def test_report_screenshot_transaction_isolation_and_cascade_on_postgresql(env):
    student = _login(env, STUDENT_EMAIL)
    shot = _image("WEBP", size=(400, 300))
    titulo = f"S1RT {secrets.token_hex(3)}"
    response = student.post(
        "/aluno/reportar",
        data={"categoria": "Outro", "titulo": titulo, "descricao": "d",
              "captura_tela": (io.BytesIO(shot), "c.webp")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    reporte_id, filename = env.observer.execute(
        "SELECT id, screenshot_filename FROM reportes WHERE titulo=%s", (titulo,)
    ).fetchone()
    assert filename is None
    stored = env.observer.execute(
        "SELECT mime_type, conteudo, sha256 FROM reportes_captura WHERE reporte_id=%s", (reporte_id,)
    ).fetchone()
    assert stored[0] == "image/webp" and bytes(stored[1]) == shot
    assert stored[2] == hashlib.sha256(shot).hexdigest()
    page = student.get("/aluno/reportar").get_data(as_text=True)
    assert f"/reportes/{reporte_id}/captura?v={stored[2][:16]}" in page
    assert student.get(f"/reportes/{reporte_id}/captura").data == shot

    assert _login(env, OTHER_EMAIL).get(f"/reportes/{reporte_id}/captura").status_code == 404
    admin = _login(env, ADMIN_EMAIL)
    assert f"/reportes/{reporte_id}/captura?v=" in admin.get("/admin/reportes").get_data(as_text=True)
    assert admin.get(f"/reportes/{reporte_id}/captura").data == shot
    assert admin.post(f"/admin/reportes/{reporte_id}/deletar").status_code == 302
    assert env.observer.execute(
        "SELECT count(*) FROM reportes_captura WHERE reporte_id=%s", (reporte_id,)
    ).fetchone()[0] == 0

    # An invalid screenshot leaves no report row behind.
    bad = f"S1RT bad {secrets.token_hex(3)}"
    student.post("/aluno/reportar", data={"categoria": "Outro", "titulo": bad, "descricao": "d",
                                          "captura_tela": (io.BytesIO(b"not an image"), "x.png")},
                 content_type="multipart/form-data")
    assert env.observer.execute("SELECT count(*) FROM reportes WHERE titulo=%s", (bad,)).fetchone()[0] == 0
    assert env.sqlite_calls == []


def test_student_photo_and_domain_checks_on_postgresql(env):
    from app import pg_migrate_from_sqlite as pathb

    student = _login(env, STUDENT_EMAIL)
    response = student.post(
        "/aluno/meus_dados",
        data={"nome": "S1 Aluno", "email": STUDENT_EMAIL, "matricula": "S1RT-1", "remove_foto": "0",
              "foto_perfil": (io.BytesIO(_image("JPEG", size=(1200, 900))), "eu.jpg")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    width, height = env.observer.execute(
        "SELECT width, height FROM alunos_foto WHERE aluno_id=%s", (env.alunos[STUDENT_EMAIL],)
    ).fetchone()
    assert (width, height) == (512, 384)
    assert student.get("/perfil/foto").mimetype == "image/jpeg"
    assert _login(env, OTHER_EMAIL).get("/perfil/foto").status_code == 404
    results = pathb.run_domain_checks(env.observer)
    assert {name: count for name, count in results.items() if count} == {}
    assert len(results) == 64  # v13: 49; v14 adds 7 storage checks and 7 net FK-orphan checks; v16: +1 FK orphan
    env.observer.execute("DELETE FROM alunos WHERE id=%s", (env.alunos[STUDENT_EMAIL],))
    assert env.observer.execute("SELECT count(*) FROM alunos_foto").fetchone()[0] == 0
    assert env.sqlite_calls == []
