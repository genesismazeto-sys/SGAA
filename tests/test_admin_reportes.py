import io
import os
import sys
import uuid
from pathlib import Path

import pytest


BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main


@pytest.fixture(scope="module")
def client():
    app = main.app
    with app.app_context():
        main.init_db()
    with app.test_client() as client:
        yield client


def _login_admin(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["user_type"] = "admin"
        sess["user_name"] = "Administrador"


def _login_admin_by_id(client, user_id: int, user_name: str):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["user_type"] = "admin"
        sess["user_name"] = user_name


def _login_aluno(client, usuario_id, nome):
    with client.session_transaction() as sess:
        sess["user_id"] = usuario_id
        sess["user_type"] = "aluno"
        sess["user_name"] = nome
        sess["perfil"] = "Aluno"


@pytest.fixture
def report_creation_student():
    token = uuid.uuid4().hex[:8]
    email = f"admin.report.creation.{token}@ej.edu.br"
    matricula = f"ARC-{token}"
    with main.app.app_context():
        conn = main.get_db_connection()
        usuario_id = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?)",
            (f"Aluno Criação {token}", email, main.hash_password("aluno123"), "aluno", "usuario"),
        ).lastrowid
        aluno_id = conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, status) VALUES (?, ?, ?, ?, ?)",
            (usuario_id, f"Aluno Criação {token}", matricula, email, "Ativo"),
        ).lastrowid
        conn.commit()
    try:
        yield {
            "aluno_id": aluno_id,
            "usuario_id": usuario_id,
            "email": email,
            "matricula": matricula,
            "student_dirname": f"aluno_{aluno_id} - aluno-criacao-{token}",
        }
    finally:
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute("DELETE FROM reportes WHERE aluno_id = ?", (aluno_id,))
            conn.execute("DELETE FROM alunos WHERE id = ?", (aluno_id,))
            conn.execute("DELETE FROM usuarios WHERE id = ?", (usuario_id,))
            conn.commit()


def _post_admin_report(client, student, **overrides):
    data = {
        "aluno_id": str(student["aluno_id"]),
        "categoria": "Bug na plataforma",
        "titulo": "Reporte administrativo",
        "descricao": "Descrição do reporte administrativo.",
    }
    data.update(overrides)
    return client.post("/admin/reportes/novo", data=data, follow_redirects=False)


def test_admin_can_create_report_for_selected_student_with_initial_state(client, report_creation_student):
    _login_admin(client)
    response = _post_admin_report(
        client,
        report_creation_student,
        titulo="  Reporte administrativo selecionado  ",
        descricao="  Descrição administrativa trimada.  ",
    )

    assert response.status_code in (302, 303)
    assert response.headers["Location"].endswith("/admin/reportes")
    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT aluno_id, titulo, descricao, categoria, status, admin_id FROM reportes WHERE aluno_id = ? ORDER BY id DESC LIMIT 1",
            (report_creation_student["aluno_id"],),
        ).fetchone()
    assert dict(row) == {
        "aluno_id": report_creation_student["aluno_id"],
        "titulo": "Reporte administrativo selecionado",
        "descricao": "Descrição administrativa trimada.",
        "categoria": "Bug na plataforma",
        "status": "Novo",
        "admin_id": None,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("aluno_id", ""),
        ("aluno_id", "999999999"),
        ("categoria", "Categoria inventada"),
        ("titulo", "   "),
        ("titulo", "x" * 121),
        ("descricao", "   "),
    ],
)
def test_admin_report_creation_rejects_invalid_required_values(client, report_creation_student, field, value):
    _login_admin(client)
    response = _post_admin_report(client, report_creation_student, **{field: value})

    assert response.status_code in (302, 303)
    assert "novo=1" in response.headers["Location"]
    with main.app.app_context():
        count = main.get_db_connection().execute(
            "SELECT COUNT(*) FROM reportes WHERE aluno_id = ?", (report_creation_student["aluno_id"],)
        ).fetchone()[0]
    assert count == 0


def test_admin_report_creation_stores_valid_screenshot(client, report_creation_student):
    _login_admin(client)
    title = f"Reporte screenshot {uuid.uuid4().hex[:8]}"
    response = client.post(
        "/admin/reportes/novo",
        data={
            "aluno_id": str(report_creation_student["aluno_id"]),
            "categoria": "Outro",
            "titulo": title,
            "descricao": "Reporte com screenshot.",
            "captura_tela": (io.BytesIO(b"\x89PNG\r\n\x1a\nadmin"), "admin-shot.PNG"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert response.status_code in (302, 303)
    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT screenshot_filename FROM reportes WHERE titulo = ?", (title,)
        ).fetchone()
    assert row and row["screenshot_filename"]
    saved = Path(main.app.config["DOCUMENTOS_ALUNOS_FOLDER"]) / Path(row["screenshot_filename"])
    assert saved.is_file()
    assert saved.suffix == ".png"


def test_admin_report_creation_rejects_invalid_screenshot_extension(client, report_creation_student):
    _login_admin(client)
    response = client.post(
        "/admin/reportes/novo",
        data={
            "aluno_id": str(report_creation_student["aluno_id"]),
            "categoria": "Outro",
            "titulo": "Reporte screenshot inválido",
            "descricao": "Descrição.",
            "captura_tela": (io.BytesIO(b"not an image"), "admin-shot.gif"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert response.status_code in (302, 303)
    assert "novo=1" in response.headers["Location"]
    with main.app.app_context():
        count = main.get_db_connection().execute(
            "SELECT COUNT(*) FROM reportes WHERE aluno_id = ?", (report_creation_student["aluno_id"],)
        ).fetchone()[0]
    assert count == 0


def test_admin_report_creation_removes_only_new_screenshot_after_insert_failure(client, report_creation_student):
    _login_admin(client)
    document_root = Path(main.app.config["DOCUMENTOS_ALUNOS_FOLDER"])
    existing = document_root / report_creation_student["student_dirname"] / "reportes" / "keep.txt"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text("unrelated", encoding="utf-8")

    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            """
            CREATE TRIGGER reportes_admin_test_insert_failure
            BEFORE INSERT ON reportes
            WHEN NEW.titulo LIKE 'FAIL-CLEANUP-%'
            BEGIN
                SELECT RAISE(ABORT, 'forced report insert failure');
            END
            """
        )
        conn.commit()
    try:
        response = client.post(
            "/admin/reportes/novo",
            data={
                "aluno_id": str(report_creation_student["aluno_id"]),
                "categoria": "Outro",
                "titulo": "FAIL-CLEANUP-report",
                "descricao": "Descrição.",
                "captura_tela": (io.BytesIO(b"\x89PNG\r\n\x1a\nfailed"), "failed.png"),
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        assert response.status_code in (302, 303)
        assert "novo=1" in response.headers["Location"]
        assert existing.is_file()
        report_files = [path for path in existing.parent.iterdir() if path.is_file()]
        assert report_files == [existing]
    finally:
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute("DROP TRIGGER IF EXISTS reportes_admin_test_insert_failure")
            conn.commit()


def test_view_only_admin_cannot_create_report(client, report_creation_student):
    consultivo_email = f"admin.report.consultivo.{uuid.uuid4().hex[:8]}@ej.edu.br"
    with main.app.app_context():
        conn = main.get_db_connection()
        main.ensure_usuario_access_schema(conn)
        consultivo_id = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?)",
            ("Consultivo Reporte Criação", consultivo_email, main.hash_password("admin123"), "admin", "consultivo"),
        ).lastrowid
        conn.commit()
    try:
        _login_admin_by_id(client, consultivo_id, "Consultivo Reporte Criação")
        page = client.get("/admin/reportes")
        assert page.status_code == 200
        assert 'id="btn-novo-reporte"' not in page.get_data(as_text=True)
        denied = _post_admin_report(client, report_creation_student)
        assert denied.status_code in (301, 302, 303, 307, 308, 403)
    finally:
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute("DELETE FROM usuarios WHERE id = ?", (consultivo_id,))
            conn.commit()


def test_unauthenticated_admin_report_creation_is_blocked(client, report_creation_student):
    with client.session_transaction() as sess:
        sess.clear()
    response = _post_admin_report(client, report_creation_student)
    assert response.status_code in (301, 302, 303, 307, 308)
    assert "/login" in (response.headers.get("Location") or "")


def test_admin_report_creation_requires_csrf_when_enabled(client, report_creation_student):
    _login_admin(client)
    original_enabled = main.app.config.get("WTF_CSRF_ENABLED")
    original_check_default = main.app.config.get("WTF_CSRF_CHECK_DEFAULT")
    main.app.config.update(WTF_CSRF_ENABLED=True, WTF_CSRF_CHECK_DEFAULT=True)
    try:
        response = _post_admin_report(client, report_creation_student)
        assert response.status_code == 400
    finally:
        main.app.config.update(
            WTF_CSRF_ENABLED=original_enabled,
            WTF_CSRF_CHECK_DEFAULT=original_check_default,
        )


def test_admin_reportes_displays_dates_in_brazilian_format(client):
    with main.app.app_context():
        conn = main.get_db_connection()
        main.ensure_reportes_table(conn)
        conn.execute("DELETE FROM reportes WHERE titulo = ?", ("Reporte data BR",))
        conn.execute("DELETE FROM alunos WHERE matricula = ?", ("REP-2026-01",))
        conn.execute("DELETE FROM usuarios WHERE email = ?", ("reporte.data.br@ej.edu.br",))
        user_cursor = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?)",
            (
                "Aluno Reporte Data",
                "reporte.data.br@ej.edu.br",
                main.hash_password("aluno123"),
                "aluno",
                "usuario",
            ),
        )
        usuario_id = user_cursor.lastrowid
        aluno_cursor = conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, status) VALUES (?, ?, ?, ?, ?)",
            (usuario_id, "Aluno Reporte Data", "REP-2026-01", "reporte.data.br@ej.edu.br", "Ativo"),
        )
        aluno_id = aluno_cursor.lastrowid
        conn.execute(
            """
            INSERT INTO reportes (aluno_id, titulo, descricao, categoria, status, criado_em, atualizado_em)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                aluno_id,
                "Reporte data BR",
                "Falha com data formatada.",
                "Bug na plataforma",
                "Novo",
                "2026-04-27 13:45:00",
                "2026-04-28 08:15:00",
            ),
        )
        conn.commit()

    _login_admin(client)
    response = client.get("/admin/reportes")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "27/04/2026" in html
    assert "28/04/2026" in html
    assert '"criado_em_fmt": "27/04/2026"' in html
    assert '"atualizado_em_fmt": "28/04/2026"' in html
    assert '"criado_em": "2026-04-27 13:45:00"' not in html
    assert '"atualizado_em": "2026-04-28 08:15:00"' not in html


def test_aluno_reportes_displays_dates_in_brazilian_format(client):
    with main.app.app_context():
        conn = main.get_db_connection()
        main.ensure_reportes_table(conn)
        conn.execute("DELETE FROM reportes WHERE titulo = ?", ("Reporte aluno data BR",))
        conn.execute("DELETE FROM alunos WHERE matricula = ?", ("REP-2026-02",))
        conn.execute("DELETE FROM usuarios WHERE email = ?", ("reporte.aluno.data.br@ej.edu.br",))
        user_cursor = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?)",
            (
                "Aluno Reporte Data BR",
                "reporte.aluno.data.br@ej.edu.br",
                main.hash_password("aluno123"),
                "aluno",
                "usuario",
            ),
        )
        usuario_id = user_cursor.lastrowid
        aluno_cursor = conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, status) VALUES (?, ?, ?, ?, ?)",
            (usuario_id, "Aluno Reporte Data BR", "REP-2026-02", "reporte.aluno.data.br@ej.edu.br", "Ativo"),
        )
        aluno_id = aluno_cursor.lastrowid
        conn.execute(
            """
            INSERT INTO reportes (aluno_id, titulo, descricao, categoria, status, criado_em, atualizado_em)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                aluno_id,
                "Reporte aluno data BR",
                "Falha com data formatada para o aluno.",
                "Bug na plataforma",
                "Em análise",
                "2026-04-29 10:20:00",
                "2026-04-30 18:05:00",
            ),
        )
        conn.commit()

    _login_aluno(client, usuario_id, "Aluno Reporte Data BR")
    response = client.get("/aluno/reportar")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "29/04/2026" in html
    assert "30/04/2026" in html
    assert '"criado_em_fmt": "29/04/2026"' in html
    assert '"atualizado_em_fmt": "30/04/2026"' in html
    assert '"criado_em": "2026-04-29 10:20:00"' not in html
    assert '"atualizado_em": "2026-04-30 18:05:00"' not in html


def test_admin_reportes_filter_schema_and_typed_filters(client):
    title_a = "Reporte Filtro Tipado A"
    title_b = "Reporte Filtro Tipado B"
    email_a = "reporte.filtro.a@ej.edu.br"
    email_b = "reporte.filtro.b@ej.edu.br"
    matricula_a = "RPF-A-001"
    matricula_b = "RPF-B-001"

    with main.app.app_context():
        conn = main.get_db_connection()
        main.ensure_reportes_table(conn)
        conn.execute("DELETE FROM reportes WHERE titulo IN (?, ?)", (title_a, title_b))
        conn.execute("DELETE FROM alunos WHERE matricula IN (?, ?)", (matricula_a, matricula_b))
        conn.execute("DELETE FROM usuarios WHERE email IN (?, ?)", (email_a, email_b))

        user_a = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?)",
            ("Aluno Filtro Reporte A", email_a, main.hash_password("aluno123"), "aluno", "usuario"),
        ).lastrowid
        user_b = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?)",
            ("Aluno Filtro Reporte B", email_b, main.hash_password("aluno123"), "aluno", "usuario"),
        ).lastrowid

        aluno_a = conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, status) VALUES (?, ?, ?, ?, ?)",
            (user_a, "Aluno Filtro Reporte A", matricula_a, email_a, "Ativo"),
        ).lastrowid
        aluno_b = conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, status) VALUES (?, ?, ?, ?, ?)",
            (user_b, "Aluno Filtro Reporte B", matricula_b, email_b, "Ativo"),
        ).lastrowid

        conn.execute(
            """
            INSERT INTO reportes (aluno_id, titulo, descricao, categoria, status, criado_em, atualizado_em)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                aluno_a,
                title_a,
                "Descricao filtro A",
                "Bug na plataforma",
                "Novo",
                "2026-04-10 12:00:00",
                "2026-04-11 12:00:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO reportes (aluno_id, titulo, descricao, categoria, status, criado_em, atualizado_em)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                aluno_b,
                title_b,
                "Descricao filtro B",
                "Lentidão",
                "Resolvido",
                "2026-05-05 12:00:00",
                "2026-05-06 12:00:00",
            ),
        )
        conn.commit()

    _login_admin(client)

    try:
        response = client.get(
            "/admin/reportes",
            query_string={
                "aluno": "Reporte A",
                "matricula": "RPF-A",
                "titulo": "Tipado A",
                "status": "Novo",
                "categoria": "Bug na plataforma",
                "criado_em_min": "2026-04-01",
                "criado_em_max": "2026-04-30",
            },
        )
        assert response.status_code == 200
        html = response.get_data(as_text=True)

        assert '"param": "aluno"' in html
        assert '"param": "matricula"' in html
        assert '"param": "titulo"' in html
        assert '"param": "criado_em"' in html
        assert '"type": "text_contains"' in html
        assert '"type": "date_range"' in html
        assert '"type": "multi_select"' in html

        assert title_a in html
        assert title_b not in html
    finally:
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute("DELETE FROM reportes WHERE titulo IN (?, ?)", (title_a, title_b))
            conn.execute("DELETE FROM alunos WHERE matricula IN (?, ?)", (matricula_a, matricula_b))
            conn.execute("DELETE FROM usuarios WHERE email IN (?, ?)", (email_a, email_b))
            conn.commit()


def test_admin_reportes_status_update_uses_correct_post_route_and_respects_permissions(client):
    token = uuid.uuid4().hex[:8]
    aluno_email = f"reporte.status.aluno.{token}@ej.edu.br"
    aluno_matricula = f"RPS-{token}"
    consultivo_email = f"reporte.status.consultivo.{token}@ej.edu.br"
    reporte_titulo = f"Reporte status route {token}"

    with main.app.app_context():
        conn = main.get_db_connection()
        main.ensure_reportes_table(conn)
        main.ensure_usuario_access_schema(conn)

        conn.execute("DELETE FROM reportes WHERE titulo = ?", (reporte_titulo,))
        conn.execute("DELETE FROM alunos WHERE matricula = ?", (aluno_matricula,))
        conn.execute("DELETE FROM usuarios WHERE email IN (?, ?)", (aluno_email, consultivo_email))

        aluno_user_id = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?)",
            (
                "Aluno Reporte Status",
                aluno_email,
                main.hash_password("aluno123"),
                "aluno",
                "usuario",
            ),
        ).lastrowid
        aluno_id = conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, status) VALUES (?, ?, ?, ?, ?)",
            (aluno_user_id, "Aluno Reporte Status", aluno_matricula, aluno_email, "Ativo"),
        ).lastrowid

        reporte_id = conn.execute(
            """
            INSERT INTO reportes (aluno_id, titulo, descricao, categoria, status, criado_em, atualizado_em)
            VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            """,
            (aluno_id, reporte_titulo, "Descricao status", "Bug na plataforma", "Novo"),
        ).lastrowid

        consultivo_id = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?)",
            (
                "Consultivo Reporte Status",
                consultivo_email,
                main.hash_password("admin123"),
                "admin",
                "consultivo",
            ),
        ).lastrowid
        conn.commit()

    try:
        _login_admin(client)

        page_admin = client.get("/admin/reportes")
        assert page_admin.status_code == 200
        html_admin = page_admin.get_data(as_text=True)
        assert "const canReportesEdit = true;" in html_admin
        assert "const canReportesFull = true;" in html_admin

        update_response = client.post(
            f"/admin/reportes/{reporte_id}/status",
            data={"status": "Em análise"},
            follow_redirects=False,
        )
        assert update_response.status_code != 405
        assert update_response.status_code in (302, 303)
        assert "/admin/reportes" in (update_response.headers.get("Location") or "")

        with main.app.app_context():
            conn = main.get_db_connection()
            status_after_admin = conn.execute(
                "SELECT status FROM reportes WHERE id = ?",
                (reporte_id,),
            ).fetchone()
        assert status_after_admin is not None
        assert status_after_admin["status"] == "Em análise"

        _login_admin_by_id(client, consultivo_id, "Consultivo Reporte Status")

        page_consultivo = client.get("/admin/reportes")
        assert page_consultivo.status_code == 200
        html_consultivo = page_consultivo.get_data(as_text=True)
        assert "const canReportesEdit = false;" in html_consultivo
        assert 'reporte-modal-status-block" hidden' in html_consultivo
        assert "Salvar status" not in html_consultivo

        denied_response = client.post(
            f"/admin/reportes/{reporte_id}/status",
            data={"status": "Resolvido"},
            follow_redirects=False,
        )
        assert denied_response.status_code != 405
        if denied_response.status_code == 403:
            pass
        else:
            assert denied_response.status_code in (301, 302, 303, 307, 308)
            assert "/admin/dashboard" in (denied_response.headers.get("Location") or "")

        with main.app.app_context():
            conn = main.get_db_connection()
            status_after_denied = conn.execute(
                "SELECT status FROM reportes WHERE id = ?",
                (reporte_id,),
            ).fetchone()
        assert status_after_denied is not None
        assert status_after_denied["status"] == "Em análise"
    finally:
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute("DELETE FROM reportes WHERE titulo = ?", (reporte_titulo,))
            conn.execute("DELETE FROM alunos WHERE matricula = ?", (aluno_matricula,))
            conn.execute("DELETE FROM usuarios WHERE email IN (?, ?)", (aluno_email, consultivo_email))
            conn.commit()


def test_aluno_report_screenshot_is_saved_in_documentos_alunos_and_served_for_admin(client, tmp_path):
    token = uuid.uuid4().hex[:8]
    aluno_email = f"reporte.arquivo.aluno.{token}@ej.edu.br"
    aluno_matricula = f"RPA-{token}"
    reporte_titulo = f"Reporte arquivo {token}"
    upload_root = tmp_path / "uploads"
    documents_root = tmp_path / "documentos_alunos"
    upload_root.mkdir(parents=True, exist_ok=True)
    documents_root.mkdir(parents=True, exist_ok=True)

    original_upload_folder = main.app.config.get("UPLOAD_FOLDER")
    original_documents_folder = main.app.config.get("DOCUMENTOS_ALUNOS_FOLDER")
    main.app.config["UPLOAD_FOLDER"] = str(upload_root)
    main.app.config["DOCUMENTOS_ALUNOS_FOLDER"] = str(documents_root)

    with main.app.app_context():
        conn = main.get_db_connection()
        main.ensure_reportes_table(conn)
        conn.execute("DELETE FROM reportes WHERE titulo = ?", (reporte_titulo,))
        conn.execute("DELETE FROM alunos WHERE matricula = ?", (aluno_matricula,))
        conn.execute("DELETE FROM usuarios WHERE email = ?", (aluno_email,))
        usuario_id = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?)",
            ("Aluno Reporte Arquivo", aluno_email, main.hash_password("aluno123"), "aluno", "usuario"),
        ).lastrowid
        conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, status) VALUES (?, ?, ?, ?, ?)",
            (usuario_id, "Aluno Reporte Arquivo", aluno_matricula, aluno_email, "Ativo"),
        )
        conn.commit()

    try:
        _login_aluno(client, usuario_id, "Aluno Reporte Arquivo")
        response = client.post(
            "/aluno/reportar",
            data={
                "categoria": "Bug na plataforma",
                "titulo": reporte_titulo,
                "descricao": "Reporte com captura",
                "captura_tela": (io.BytesIO(b"\x89PNG\r\n\x1a\nreport"), "captura.png"),
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        assert response.status_code in (302, 303)

        with main.app.app_context():
            conn = main.get_db_connection()
            reporte = conn.execute(
                "SELECT screenshot_filename FROM reportes WHERE titulo = ? ORDER BY id DESC LIMIT 1",
                (reporte_titulo,),
            ).fetchone()
        assert reporte is not None
        rel_path = reporte["screenshot_filename"]
        assert rel_path
        assert os.path.isfile(os.path.join(str(documents_root), rel_path))
        assert not os.path.exists(os.path.join(str(upload_root), rel_path))

        _login_admin(client)
        served = client.get(f"/uploads/{rel_path}", follow_redirects=False)
        assert served.status_code == 200
    finally:
        main.app.config["UPLOAD_FOLDER"] = original_upload_folder
        main.app.config["DOCUMENTOS_ALUNOS_FOLDER"] = original_documents_folder
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute("DELETE FROM reportes WHERE titulo = ?", (reporte_titulo,))
            conn.execute("DELETE FROM alunos WHERE matricula = ?", (aluno_matricula,))
            conn.execute("DELETE FROM usuarios WHERE email = ?", (aluno_email,))
            conn.commit()
