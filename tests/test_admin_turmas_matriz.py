import os
import sqlite3
import sys

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


def test_admin_turma_persists_and_displays_matrix(client):
    matrix_name = "Matriz Turma Automatizada"
    turma_codigo = None

    with main.app.app_context():
        conn = main.get_db_connection()
        main.ensure_matrizes_atividades_table(conn)
        main.ensure_turmas_matriz_schema(conn)
        curso = conn.execute("SELECT id, codigo FROM cursos ORDER BY id LIMIT 1").fetchone()
        assert curso is not None
        turma_codigo = main.gerar_codigo_turma(curso["codigo"], 99)
        conn.execute("DELETE FROM turmas WHERE codigo = ?", (turma_codigo,))
        conn.execute("DELETE FROM matrizes_atividades WHERE nome = ?", (matrix_name,))
        cursor = conn.execute(
            """
            INSERT INTO matrizes_atividades (
                curso_id,
                nome,
                versao,
                status,
                data_inicio_vigencia,
                horas_aac_obrigatorias,
                horas_extensao_obrigatorias,
                descricao
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (curso["id"], matrix_name, "2027.1", "vigente", "2027-01-01", 160, 80, "Matriz para teste de turma"),
        )
        matriz_id = cursor.lastrowid
        conn.commit()

    _login_admin(client)

    add_page = client.get("/admin/adicionar_turma")
    assert add_page.status_code == 200
    add_html = add_page.get_data(as_text=True)
    assert matrix_name in add_html

    create = client.post(
        "/admin/adicionar_turma",
        data={
            "curso_id": curso["id"],
            "numero_turma": 99,
            "matriz_id": matriz_id,
            "ano_inicio": 2027,
            "semestre_inicio": 1,
            "ano_fim": 2030,
            "semestre_fim": 2,
            "turno": "Noite",
            "status": "Ativa",
        },
        follow_redirects=False,
    )
    assert create.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        turma = conn.execute(
            "SELECT id, matriz_id, curso_id FROM turmas WHERE codigo = ?",
            (turma_codigo,),
        ).fetchone()
        assert turma is not None
        assert turma["matriz_id"] == matriz_id
        turma_id = turma["id"]

    listing = client.get("/admin/turmas")
    assert listing.status_code == 200
    listing_html = listing.get_data(as_text=True)
    assert matrix_name in listing_html

    detail = client.get(f"/admin/turma/{turma_id}")
    assert detail.status_code == 200
    assert matrix_name in detail.get_data(as_text=True)

    edit = client.post(
        f"/admin/editar_turma/{turma_id}",
        data={
            "curso_id": curso["id"],
            "numero_turma": 99,
            "matriz_id": matriz_id,
            "ano_inicio": 2027,
            "semestre_inicio": 1,
            "ano_fim": 2030,
            "semestre_fim": 2,
            "turno": "Integral",
            "status": "Inativa",
        },
        follow_redirects=False,
    )
    assert edit.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        updated = conn.execute(
            "SELECT turno, status, matriz_id FROM turmas WHERE id = ?",
            (turma_id,),
        ).fetchone()
        assert updated is not None
        assert updated["turno"] == "Integral"
        assert updated["status"] == "Inativa"
        assert updated["matriz_id"] == matriz_id
        conn.execute("DELETE FROM turmas WHERE id = ?", (turma_id,))
        conn.execute("DELETE FROM matrizes_atividades WHERE id = ?", (matriz_id,))
        conn.commit()


def test_admin_turma_orders_accented_names_like_portuguese(client):
    turma_codigo = None
    turma_id = None
    emails = ["sort.eduarda@example.com", "sort.everto@example.com"]
    matriculas = ["SORT-001", "SORT-002"]

    conn = sqlite3.connect(main.DATABASE, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        main.ensure_turmas_matriz_schema(conn)
        curso = conn.execute("SELECT id, codigo FROM cursos ORDER BY id LIMIT 1").fetchone()
        assert curso is not None
        turma_codigo = main.gerar_codigo_turma(curso["codigo"], 998)

        conn.execute("DELETE FROM alunos WHERE matricula IN (?, ?)", matriculas)
        conn.execute("DELETE FROM usuarios WHERE email IN (?, ?)", emails)
        conn.execute("DELETE FROM turmas WHERE codigo = ?", (turma_codigo,))

        cursor = conn.execute(
            """
            INSERT INTO turmas (nome, ano, semestre, turno, status, numero, curso_id, matriz_id, ano_inicio, semestre_inicio, ano_fim, semestre_fim, codigo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (turma_codigo, None, None, "Noite", "Ativa", 998, curso["id"], None, 2027, 1, 2030, 2, turma_codigo),
        )
        turma_id = cursor.lastrowid

        user_eduarda = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo) VALUES (?, ?, ?, ?)",
            ("Eduarda Teste Ordenacao", emails[0], main.hash_password("teste123"), "aluno"),
        ).lastrowid
        user_everto = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo) VALUES (?, ?, ?, ?)",
            ("Éverto Teste Ordenacao", emails[1], main.hash_password("teste123"), "aluno"),
        ).lastrowid

        conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status) VALUES (?, ?, ?, ?, ?, ?)",
            (user_everto, "Éverto Teste Ordenacao", matriculas[1], emails[1], turma_id, "Ativo"),
        )
        conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status) VALUES (?, ?, ?, ?, ?, ?)",
            (user_eduarda, "Eduarda Teste Ordenacao", matriculas[0], emails[0], turma_id, "Ativo"),
        )
        conn.commit()
    finally:
        conn.close()

    _login_admin(client)

    try:
        edit_page = client.get(f"/admin/editar_turma/{turma_id}")
        assert edit_page.status_code == 200
        edit_html = edit_page.get_data(as_text=True)
        assert edit_html.index("Eduarda Teste Ordenacao") < edit_html.index("Éverto Teste Ordenacao")

        detail_page = client.get(f"/admin/turma/{turma_id}")
        assert detail_page.status_code == 200
        detail_html = detail_page.get_data(as_text=True)
        assert detail_html.index("Eduarda Teste Ordenacao") < detail_html.index("Éverto Teste Ordenacao")
    finally:
        conn = sqlite3.connect(main.DATABASE, timeout=30)
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            if turma_id is not None:
                conn.execute("DELETE FROM alunos WHERE turma_id = ?", (turma_id,))
                conn.execute("DELETE FROM turmas WHERE id = ?", (turma_id,))
            conn.execute("DELETE FROM usuarios WHERE email IN (?, ?)", emails)
            conn.commit()
        finally:
            conn.close()


def test_admin_turma_detail_exposes_status_filter_matching_displayed_status(client):
    turma_codigo = None
    turma_id = None
    emails = ["filter.ativo@example.com", "filter.inativo@example.com"]
    matriculas = ["FILTER-ATIVO", "FILTER-INATIVO"]

    conn = sqlite3.connect(main.DATABASE, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        main.ensure_turmas_matriz_schema(conn)
        curso = conn.execute("SELECT id, codigo FROM cursos ORDER BY id LIMIT 1").fetchone()
        assert curso is not None
        turma_codigo = main.gerar_codigo_turma(curso["codigo"], 996)

        conn.execute("DELETE FROM alunos WHERE matricula IN (?, ?)", matriculas)
        conn.execute("DELETE FROM usuarios WHERE email IN (?, ?)", emails)
        conn.execute("DELETE FROM turmas WHERE codigo = ?", (turma_codigo,))

        cursor = conn.execute(
            """
            INSERT INTO turmas (nome, ano, semestre, turno, status, numero, curso_id, matriz_id, ano_inicio, semestre_inicio, ano_fim, semestre_fim, codigo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (turma_codigo, None, None, "Noite", "Ativa", 996, curso["id"], None, 2027, 1, 2030, 2, turma_codigo),
        )
        turma_id = cursor.lastrowid

        user_ativo = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo) VALUES (?, ?, ?, ?)",
            ("Aluno Filtro Ativo", emails[0], main.hash_password("teste123"), "aluno"),
        ).lastrowid
        user_inativo = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo) VALUES (?, ?, ?, ?)",
            ("Aluno Filtro Inativo", emails[1], main.hash_password("teste123"), "aluno"),
        ).lastrowid

        conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status) VALUES (?, ?, ?, ?, ?, ?)",
            (user_ativo, "Aluno Filtro Ativo", matriculas[0], emails[0], turma_id, "Ativo"),
        )
        conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status) VALUES (?, ?, ?, ?, ?, ?)",
            (user_inativo, "Aluno Filtro Inativo", matriculas[1], emails[1], turma_id, "Inativo"),
        )
        conn.commit()
    finally:
        conn.close()

    _login_admin(client)

    try:
        detail_page = client.get(f"/admin/turma/{turma_id}")
        assert detail_page.status_code == 200
        detail_html = detail_page.get_data(as_text=True)
        assert '"param": "status"' in detail_html
        assert '"type": "multi_select"' in detail_html
        assert '"value": "Ativo"' in detail_html
        assert '"value": "Inativo"' in detail_html
        assert "Aluno Filtro Ativo" in detail_html
        assert "Aluno Filtro Inativo" in detail_html
        assert "Inativo" in detail_html

        active_only = client.get(f"/admin/turma/{turma_id}?status=Ativo")
        assert active_only.status_code == 200
        active_html = active_only.get_data(as_text=True)
        assert "Aluno Filtro Ativo" in active_html
        assert "Aluno Filtro Inativo" not in active_html

        inactive_only = client.get(f"/admin/turma/{turma_id}?status=Inativo")
        assert inactive_only.status_code == 200
        inactive_html = inactive_only.get_data(as_text=True)
        assert "Aluno Filtro Ativo" not in inactive_html
        assert "Aluno Filtro Inativo" in inactive_html
    finally:
        conn = sqlite3.connect(main.DATABASE, timeout=30)
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            if turma_id is not None:
                conn.execute("DELETE FROM alunos WHERE turma_id = ?", (turma_id,))
                conn.execute("DELETE FROM turmas WHERE id = ?", (turma_id,))
            conn.execute("DELETE FROM usuarios WHERE email IN (?, ?)", emails)
            conn.commit()
        finally:
            conn.close()


def test_admin_turma_detail_populates_hour_totals_and_sorts_by_them(client):
    turma_codigo = None
    turma_id = None
    atividade_aac = "Atividade AAC Turma Detail"
    atividade_ae = "Atividade AE Turma Detail"
    emails = ["hours.alto@example.com", "hours.baixo@example.com"]
    matriculas = ["HOURS-ALTO", "HOURS-BAIXO"]

    conn = sqlite3.connect(main.DATABASE, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        main.ensure_turmas_matriz_schema(conn)
        curso = conn.execute("SELECT id, codigo FROM cursos ORDER BY id LIMIT 1").fetchone()
        assert curso is not None
        turma_codigo = main.gerar_codigo_turma(curso["codigo"], 995)

        conn.execute("DELETE FROM requisicoes WHERE nome_evento IN (?, ?, ?)", ("Evento AAC Alto", "Evento AAC Baixo", "Evento AE Alto"))
        conn.execute("DELETE FROM atividades WHERE nome IN (?, ?)", (atividade_aac, atividade_ae))
        conn.execute("DELETE FROM alunos WHERE matricula IN (?, ?)", matriculas)
        conn.execute("DELETE FROM usuarios WHERE email IN (?, ?)", emails)
        conn.execute("DELETE FROM turmas WHERE codigo = ?", (turma_codigo,))

        cursor = conn.execute(
            """
            INSERT INTO turmas (nome, ano, semestre, turno, status, numero, curso_id, matriz_id, ano_inicio, semestre_inicio, ano_fim, semestre_fim, codigo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (turma_codigo, None, None, "Noite", "Ativa", 995, curso["id"], None, 2027, 1, 2030, 2, turma_codigo),
        )
        turma_id = cursor.lastrowid

        atividade_aac_id = conn.execute(
            "INSERT INTO atividades (grupo, nome, tipo_atividade) VALUES (?, ?, ?)",
            ("92 - Grupo Detail", atividade_aac, "Acadêmica Complementar"),
        ).lastrowid
        atividade_ae_id = conn.execute(
            "INSERT INTO atividades (grupo, nome, tipo_atividade) VALUES (?, ?, ?)",
            ("93 - Grupo Detail", atividade_ae, "Extensão Universitária"),
        ).lastrowid

        user_alto = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo) VALUES (?, ?, ?, ?)",
            ("Aluno Horas Altas", emails[0], main.hash_password("teste123"), "aluno"),
        ).lastrowid
        user_baixo = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo) VALUES (?, ?, ?, ?)",
            ("Aluno Horas Baixas", emails[1], main.hash_password("teste123"), "aluno"),
        ).lastrowid

        aluno_alto_id = conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status) VALUES (?, ?, ?, ?, ?, ?)",
            (user_alto, "Aluno Horas Altas", matriculas[0], emails[0], turma_id, "Ativo"),
        ).lastrowid
        aluno_baixo_id = conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status) VALUES (?, ?, ?, ?, ?, ?)",
            (user_baixo, "Aluno Horas Baixas", matriculas[1], emails[1], turma_id, "Ativo"),
        ).lastrowid

        conn.execute(
            """
            INSERT INTO requisicoes (aluno_id, atividade_id, data_solicitacao, data_evento, horas_solicitadas, horas_deferidas, status, nome_evento)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (aluno_alto_id, atividade_aac_id, "2026-05-01 10:00:00", "2026-04-20", 12, 10, "Deferida", "Evento AAC Alto"),
        )
        conn.execute(
            """
            INSERT INTO requisicoes (aluno_id, atividade_id, data_solicitacao, data_evento, horas_solicitadas, horas_deferidas, status, nome_evento)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (aluno_alto_id, atividade_ae_id, "2026-05-02 10:00:00", "2026-04-21", 9, 8, "Deferida Parcialmente", "Evento AE Alto"),
        )
        conn.execute(
            """
            INSERT INTO requisicoes (aluno_id, atividade_id, data_solicitacao, data_evento, horas_solicitadas, horas_deferidas, status, nome_evento)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (aluno_baixo_id, atividade_aac_id, "2026-05-03 10:00:00", "2026-04-22", 4, 3, "Deferida", "Evento AAC Baixo"),
        )
        conn.commit()
    finally:
        conn.close()

    _login_admin(client)

    try:
        detail_page = client.get(f"/admin/turma/{turma_id}?s=total_aac&dir=desc")
        assert detail_page.status_code == 200
        detail_html = detail_page.get_data(as_text=True)
        assert "10" in detail_html
        assert "8" in detail_html
        assert "3" in detail_html
        assert detail_html.index("Aluno Horas Altas") < detail_html.index("Aluno Horas Baixas")

        ae_sorted = client.get(f"/admin/turma/{turma_id}?s=total_ae&dir=desc")
        assert ae_sorted.status_code == 200
        ae_html = ae_sorted.get_data(as_text=True)
        assert ae_html.index("Aluno Horas Altas") < ae_html.index("Aluno Horas Baixas")
    finally:
        conn = sqlite3.connect(main.DATABASE, timeout=30)
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            conn.execute("DELETE FROM requisicoes WHERE nome_evento IN (?, ?, ?)", ("Evento AAC Alto", "Evento AAC Baixo", "Evento AE Alto"))
            conn.execute("DELETE FROM atividades WHERE nome IN (?, ?)", (atividade_aac, atividade_ae))
            if turma_id is not None:
                conn.execute("DELETE FROM alunos WHERE turma_id = ?", (turma_id,))
                conn.execute("DELETE FROM turmas WHERE id = ?", (turma_id,))
            conn.execute("DELETE FROM usuarios WHERE email IN (?, ?)", emails)
            conn.commit()
        finally:
            conn.close()


def test_admin_turma_resequences_matriculas_by_alphabetical_order(client):
    matrix_name = "Matriz Turma Sequencial"
    turma_codigo = None
    turma_id = None
    matriz_id = None
    emails = ["seq.eduarda@example.com", "seq.everto@example.com"]
    nomes = ["Éverto Teste Sequencia", "Eduarda Teste Sequencia"]

    with main.app.app_context():
        conn = main.get_db_connection()
        main.ensure_matrizes_atividades_table(conn)
        main.ensure_turmas_matriz_schema(conn)
        curso = conn.execute("SELECT id, codigo FROM cursos ORDER BY id LIMIT 1").fetchone()
        assert curso is not None
        turma_codigo = main.gerar_codigo_turma(curso["codigo"], 997)

        conn.execute("DELETE FROM alunos WHERE email IN (?, ?)", emails)
        conn.execute("DELETE FROM usuarios WHERE email IN (?, ?)", emails)
        conn.execute("DELETE FROM turmas WHERE codigo = ?", (turma_codigo,))
        conn.execute("DELETE FROM matrizes_atividades WHERE nome = ?", (matrix_name,))
        cursor = conn.execute(
            """
            INSERT INTO matrizes_atividades (
                curso_id,
                nome,
                versao,
                status,
                data_inicio_vigencia,
                horas_aac_obrigatorias,
                horas_extensao_obrigatorias,
                descricao
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (curso["id"], matrix_name, "2027.2", "vigente", "2027-07-01", 160, 80, "Matriz para teste de sequencia"),
        )
        matriz_id = cursor.lastrowid
        conn.commit()

    _login_admin(client)

    try:
        create = client.post(
            "/admin/adicionar_turma",
            data={
                "curso_id": curso["id"],
                "numero_turma": 997,
                "matriz_id": matriz_id,
                "ano_inicio": 2027,
                "semestre_inicio": 2,
                "ano_fim": 2030,
                "semestre_fim": 1,
                "turno": "Noite",
                "status": "Ativa",
                "aluno_nome[]": nomes,
                "aluno_email[]": emails,
                "aluno_matricula[]": ["ABS-277", "ABS-003"],
                "aluno_situacao[]": ["ATIVO", "ATIVO"],
            },
            follow_redirects=False,
        )
        assert create.status_code in (302, 303)

        with main.app.app_context():
            conn = main.get_db_connection()
            turma = conn.execute("SELECT id FROM turmas WHERE codigo = ?", (turma_codigo,)).fetchone()
            assert turma is not None
            turma_id = turma["id"]
            alunos = conn.execute(
                "SELECT nome, matricula FROM alunos WHERE turma_id = ?",
                (turma_id,),
            ).fetchall()
            usuarios = conn.execute(
                "SELECT email, nivel_acesso FROM usuarios WHERE email IN (?, ?)",
                emails,
            ).fetchall()
            matriculas_por_nome = {row["nome"]: row["matricula"] for row in alunos}
            acessos_por_email = {row["email"]: row["nivel_acesso"] for row in usuarios}

        assert matriculas_por_nome["Eduarda Teste Sequencia"] == f"{turma_codigo}.001"
        assert matriculas_por_nome["Éverto Teste Sequencia"] == f"{turma_codigo}.002"
        assert acessos_por_email == {
            emails[0]: "usuario",
            emails[1]: "usuario",
        }
    finally:
        with main.app.app_context():
            conn = main.get_db_connection()
            if turma_id is not None:
                conn.execute("DELETE FROM alunos WHERE turma_id = ?", (turma_id,))
                conn.execute("DELETE FROM turmas WHERE id = ?", (turma_id,))
            conn.execute("DELETE FROM usuarios WHERE email IN (?, ?)", emails)
            if matriz_id is not None:
                conn.execute("DELETE FROM matrizes_atividades WHERE id = ?", (matriz_id,))
            conn.commit()


def test_admin_adicionar_turma_uses_configured_default_student_password(client):
    matrix_name = "Matriz Turma Senha Default Add"
    turma_codigo = None
    turma_id = None
    matriz_id = None
    email = "default.pass.add@example.com"
    senha_padrao = "usuarioPadrao321"
    previous_default = None

    with main.app.app_context():
        conn = main.get_db_connection()
        main.ensure_turmas_matriz_schema(conn)
        main.ensure_usuario_access_schema(conn)
        main.ensure_matrizes_atividades_table(conn)
        curso = conn.execute("SELECT id, codigo FROM cursos ORDER BY id LIMIT 1").fetchone()
        assert curso is not None
        turma_codigo = main.gerar_codigo_turma(curso["codigo"], 993)

        previous_default_row = conn.execute(
            "SELECT senha_padrao FROM configuracoes_acesso WHERE nivel_acesso = ?",
            ("usuario",),
        ).fetchone()
        assert previous_default_row is not None
        previous_default = previous_default_row["senha_padrao"]

        conn.execute("DELETE FROM alunos WHERE email = ?", (email,))
        conn.execute("DELETE FROM usuarios WHERE email = ?", (email,))
        conn.execute("DELETE FROM turmas WHERE codigo = ?", (turma_codigo,))
        conn.execute("DELETE FROM matrizes_atividades WHERE nome = ?", (matrix_name,))
        conn.execute(
            "UPDATE configuracoes_acesso SET senha_padrao = ? WHERE nivel_acesso = ?",
            (senha_padrao, "usuario"),
        )
        matriz_id = conn.execute(
            """
            INSERT INTO matrizes_atividades (
                curso_id,
                nome,
                versao,
                status,
                data_inicio_vigencia,
                horas_aac_obrigatorias,
                horas_extensao_obrigatorias,
                descricao
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (curso["id"], matrix_name, "2027.4", "vigente", "2027-01-01", 160, 80, "Matriz para teste de senha default add"),
        ).fetchone()["id"]
        conn.commit()

    _login_admin(client)

    try:
        create = client.post(
            "/admin/adicionar_turma",
            data={
                "curso_id": curso["id"],
                "numero_turma": 993,
                "matriz_id": matriz_id,
                "ano_inicio": 2027,
                "semestre_inicio": 1,
                "ano_fim": 2030,
                "semestre_fim": 2,
                "turno": "Noite",
                "status": "Ativa",
                "aluno_nome[]": ["Aluno Senha Padrao Add"],
                "aluno_email[]": [email],
                "aluno_matricula[]": ["TMP-ADD-001"],
                "aluno_situacao[]": ["ATIVO"],
            },
            follow_redirects=False,
        )
        assert create.status_code in (302, 303)

        with main.app.app_context():
            conn = main.get_db_connection()
            turma = conn.execute("SELECT id FROM turmas WHERE codigo = ?", (turma_codigo,)).fetchone()
            assert turma is not None
            turma_id = turma["id"]
            usuario = conn.execute(
                "SELECT senha, nivel_acesso FROM usuarios WHERE email = ?",
                (email,),
            ).fetchone()
            assert usuario is not None
            assert usuario["nivel_acesso"] == "usuario"
            assert main.check_password(usuario["senha"], senha_padrao)
    finally:
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute("DELETE FROM alunos WHERE email = ?", (email,))
            conn.execute("DELETE FROM usuarios WHERE email = ?", (email,))
            if turma_id is not None:
                conn.execute("DELETE FROM turmas WHERE id = ?", (turma_id,))
            if matriz_id is not None:
                conn.execute("DELETE FROM matrizes_atividades WHERE id = ?", (matriz_id,))
            if previous_default is not None:
                conn.execute(
                    "UPDATE configuracoes_acesso SET senha_padrao = ? WHERE nivel_acesso = ?",
                    (previous_default, "usuario"),
                )
            conn.commit()


def test_admin_editar_turma_uses_configured_default_student_password(client):
    matrix_name = "Matriz Turma Senha Default Edit"
    turma_codigo = None
    turma_id = None
    matriz_id = None
    email = "default.pass.edit@example.com"
    senha_padrao = "usuarioPadrao654"
    previous_default = None

    with main.app.app_context():
        conn = main.get_db_connection()
        main.ensure_turmas_matriz_schema(conn)
        main.ensure_usuario_access_schema(conn)
        main.ensure_matrizes_atividades_table(conn)
        curso = conn.execute("SELECT id, codigo FROM cursos ORDER BY id LIMIT 1").fetchone()
        assert curso is not None
        turma_codigo = main.gerar_codigo_turma(curso["codigo"], 992)

        previous_default_row = conn.execute(
            "SELECT senha_padrao FROM configuracoes_acesso WHERE nivel_acesso = ?",
            ("usuario",),
        ).fetchone()
        assert previous_default_row is not None
        previous_default = previous_default_row["senha_padrao"]

        conn.execute("DELETE FROM alunos WHERE email = ?", (email,))
        conn.execute("DELETE FROM usuarios WHERE email = ?", (email,))
        conn.execute("DELETE FROM turmas WHERE codigo = ?", (turma_codigo,))
        conn.execute("DELETE FROM matrizes_atividades WHERE nome = ?", (matrix_name,))
        conn.execute(
            "UPDATE configuracoes_acesso SET senha_padrao = ? WHERE nivel_acesso = ?",
            (senha_padrao, "usuario"),
        )
        matriz_id = conn.execute(
            """
            INSERT INTO matrizes_atividades (
                curso_id,
                nome,
                versao,
                status,
                data_inicio_vigencia,
                horas_aac_obrigatorias,
                horas_extensao_obrigatorias,
                descricao
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (curso["id"], matrix_name, "2027.5", "vigente", "2027-07-01", 160, 80, "Matriz para teste de senha default edit"),
        ).fetchone()["id"]
        turma_id = conn.execute(
            """
            INSERT INTO turmas (nome, ano, semestre, turno, status, numero, curso_id, matriz_id, ano_inicio, semestre_inicio, ano_fim, semestre_fim, codigo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (turma_codigo, None, None, "Noite", "Ativa", 992, curso["id"], matriz_id, 2027, 1, 2030, 2, turma_codigo),
        ).fetchone()["id"]
        conn.commit()

    _login_admin(client)

    try:
        edit = client.post(
            f"/admin/editar_turma/{turma_id}",
            data={
                "curso_id": curso["id"],
                "numero_turma": 992,
                "matriz_id": matriz_id,
                "ano_inicio": 2027,
                "semestre_inicio": 1,
                "ano_fim": 2030,
                "semestre_fim": 2,
                "turno": "Noite",
                "status": "Ativa",
                "aluno_nome[]": ["Aluno Senha Padrao Edit"],
                "aluno_email[]": [email],
                "aluno_matricula[]": ["TMP-EDIT-001"],
                "aluno_situacao[]": ["ATIVO"],
            },
            follow_redirects=False,
        )
        assert edit.status_code in (302, 303)

        with main.app.app_context():
            conn = main.get_db_connection()
            usuario = conn.execute(
                "SELECT senha, nivel_acesso FROM usuarios WHERE email = ?",
                (email,),
            ).fetchone()
            assert usuario is not None
            assert usuario["nivel_acesso"] == "usuario"
            assert main.check_password(usuario["senha"], senha_padrao)
    finally:
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute("DELETE FROM alunos WHERE email = ?", (email,))
            conn.execute("DELETE FROM usuarios WHERE email = ?", (email,))
            if turma_id is not None:
                conn.execute("DELETE FROM turmas WHERE id = ?", (turma_id,))
            if matriz_id is not None:
                conn.execute("DELETE FROM matrizes_atividades WHERE id = ?", (matriz_id,))
            if previous_default is not None:
                conn.execute(
                    "UPDATE configuracoes_acesso SET senha_padrao = ? WHERE nivel_acesso = ?",
                    (previous_default, "usuario"),
                )
            conn.commit()


def test_admin_turma_detail_marks_current_turma_in_dropdown(client):
    turma_codigo_atual = None
    turma_codigo_outra = None
    turma_atual_id = None

    with main.app.app_context():
        conn = main.get_db_connection()
        main.ensure_turmas_matriz_schema(conn)
        curso = conn.execute("SELECT id, codigo FROM cursos ORDER BY id LIMIT 1").fetchone()
        assert curso is not None
        turma_codigo_atual = main.gerar_codigo_turma(curso["codigo"], 996)
        turma_codigo_outra = main.gerar_codigo_turma(curso["codigo"], 995)

        conn.execute("DELETE FROM turmas WHERE codigo IN (?, ?)", (turma_codigo_atual, turma_codigo_outra))
        conn.execute(
            """
            INSERT INTO turmas (nome, ano, semestre, turno, status, numero, curso_id, matriz_id, ano_inicio, semestre_inicio, ano_fim, semestre_fim, codigo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (turma_codigo_outra, None, None, "Manhã", "Ativa", 995, curso["id"], None, 2027, 1, 2030, 2, turma_codigo_outra),
        )
        turma_atual_id = conn.execute(
            """
            INSERT INTO turmas (nome, ano, semestre, turno, status, numero, curso_id, matriz_id, ano_inicio, semestre_inicio, ano_fim, semestre_fim, codigo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (turma_codigo_atual, None, None, "Noite", "Ativa", 996, curso["id"], None, 2027, 1, 2030, 2, turma_codigo_atual),
        ).fetchone()["id"]
        conn.commit()

    _login_admin(client)

    try:
        detail_page = client.get(f"/admin/turma/{turma_atual_id}")
        assert detail_page.status_code == 200
        html = detail_page.get_data(as_text=True)
        expected_option = f'<option value="/admin/turma/{turma_atual_id}" selected>'
        assert expected_option in html
        assert turma_codigo_atual in html
        assert turma_codigo_outra in html
    finally:
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute("DELETE FROM turmas WHERE codigo IN (?, ?)", (turma_codigo_atual, turma_codigo_outra))
            conn.commit()


def test_admin_editar_turma_relinks_existing_aluno_by_email_without_unique_error(client):
    turma_codigo = None
    turma_id = None
    matriz_id = None
    matrix_name = "Matriz Turma Relink"
    email = "relink.aluno@example.com"
    matricula_antiga = "RELINK-OLD-001"
    matricula_nova = "RELINK-NEW-001"

    with main.app.app_context():
        conn = main.get_db_connection()
        main.ensure_turmas_matriz_schema(conn)
        curso = conn.execute("SELECT id, codigo FROM cursos ORDER BY id LIMIT 1").fetchone()
        assert curso is not None
        turma_codigo = main.gerar_codigo_turma(curso["codigo"], 994)

        conn.execute("DELETE FROM matrizes_atividades WHERE nome = ?", (matrix_name,))
        conn.execute("DELETE FROM alunos WHERE matricula IN (?, ?)", (matricula_antiga, matricula_nova))
        conn.execute("DELETE FROM usuarios WHERE email = ?", (email,))
        conn.execute("DELETE FROM turmas WHERE codigo = ?", (turma_codigo,))

        matriz_id = conn.execute(
            """
            INSERT INTO matrizes_atividades (
                curso_id,
                nome,
                versao,
                status,
                data_inicio_vigencia,
                horas_aac_obrigatorias,
                horas_extensao_obrigatorias,
                descricao
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (curso["id"], matrix_name, "2027.3", "vigente", "2027-08-01", 160, 80, "Matriz para teste de relink"),
        ).fetchone()["id"]

        turma_id = conn.execute(
            """
            INSERT INTO turmas (nome, ano, semestre, turno, status, numero, curso_id, matriz_id, ano_inicio, semestre_inicio, ano_fim, semestre_fim, codigo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (turma_codigo, None, None, "Noite", "Ativa", 994, curso["id"], matriz_id, 2027, 1, 2030, 2, turma_codigo),
        ).fetchone()["id"]
        usuario_id = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?)",
            ("Aluno Relink", email, main.hash_password("teste123"), "aluno", "administrativo"),
        ).lastrowid
        conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status) VALUES (?, ?, ?, ?, ?, ?)",
            (usuario_id, "Aluno Relink", matricula_antiga, email, turma_id, "Ativo"),
        )
        conn.commit()

    _login_admin(client)

    try:
        unlink = client.post(
            f"/admin/editar_turma/{turma_id}",
            data={
                "curso_id": curso["id"],
                "numero_turma": 994,
                "matriz_id": matriz_id,
                "ano_inicio": 2027,
                "semestre_inicio": 1,
                "ano_fim": 2030,
                "semestre_fim": 2,
                "turno": "Noite",
                "status": "Ativa",
            },
            follow_redirects=False,
        )
        assert unlink.status_code in (302, 303)

        relink = client.post(
            f"/admin/editar_turma/{turma_id}",
            data={
                "curso_id": curso["id"],
                "numero_turma": 994,
                "matriz_id": matriz_id,
                "ano_inicio": 2027,
                "semestre_inicio": 1,
                "ano_fim": 2030,
                "semestre_fim": 2,
                "turno": "Noite",
                "status": "Ativa",
                "aluno_nome[]": ["Aluno Relink"],
                "aluno_email[]": [email],
                "aluno_matricula[]": [matricula_nova],
                "aluno_situacao[]": ["ATIVO"],
            },
            follow_redirects=False,
        )
        assert relink.status_code in (302, 303)

        with main.app.app_context():
            conn = main.get_db_connection()
            aluno = conn.execute(
                "SELECT turma_id, email, matricula FROM alunos WHERE email = ?",
                (email,),
            ).fetchall()
            usuario = conn.execute(
                "SELECT nivel_acesso FROM usuarios WHERE email = ?",
                (email,),
            ).fetchone()
            assert len(aluno) == 1
            assert aluno[0]["turma_id"] == turma_id
            assert aluno[0]["matricula"] == f"{turma_codigo}.001"
            assert usuario is not None
            assert usuario["nivel_acesso"] == "usuario"
    finally:
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute("DELETE FROM alunos WHERE matricula IN (?, ?, ?)", (matricula_antiga, matricula_nova, f"{turma_codigo}.001"))
            conn.execute("DELETE FROM usuarios WHERE email = ?", (email,))
            conn.execute("DELETE FROM turmas WHERE codigo = ?", (turma_codigo,))
            if matriz_id is not None:
                conn.execute("DELETE FROM matrizes_atividades WHERE id = ?", (matriz_id,))
            conn.commit()