import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from app import db as app_db_module
import main
from tests.fc10_test_helpers import add_exact_snapshot_authority


@pytest.fixture(scope="module")
def client():
    app = main.app
    with app.app_context():
        main.init_db()
        yield app.test_client()


def _login_aluno(client, usuario_id: int, nome: str):
    with client.session_transaction() as sess:
        sess["user_id"] = usuario_id
        sess["user_type"] = "aluno"
        sess["user_name"] = nome


@pytest.fixture()
def isolated_dashboard_client(tmp_path):
    app = main.app
    temp_database = tmp_path / "aluno_dashboard_matrix_clean.db"

    original_database = main.DATABASE
    original_app_db_database = app_db_module.DATABASE
    original_env_database = os.environ.get("APP_DATABASE")
    original_config_database_path = app.config.get("DATABASE_PATH")
    original_testing = app.config.get("TESTING")

    os.environ["APP_DATABASE"] = str(temp_database)
    main.DATABASE = str(temp_database)
    app_db_module.DATABASE = str(temp_database)
    app.config["DATABASE_PATH"] = str(temp_database)
    app.config["TESTING"] = True

    with app.app_context():
        try:
            main.close_db_connection(None)
        except Exception:
            pass
        main.init_db()

    client = app.test_client()

    try:
        yield client
    finally:
        with app.app_context():
            try:
                main.close_db_connection(None)
            except Exception:
                pass

        main.DATABASE = original_database
        app_db_module.DATABASE = original_app_db_database
        if original_config_database_path is None:
            app.config.pop("DATABASE_PATH", None)
        else:
            app.config["DATABASE_PATH"] = original_config_database_path

        if original_env_database is None:
            os.environ.pop("APP_DATABASE", None)
        else:
            os.environ["APP_DATABASE"] = original_env_database

        app.config["TESTING"] = original_testing


def test_aluno_dashboard_clean_db_with_turma_matriz_returns_200(isolated_dashboard_client):
    client = isolated_dashboard_client
    email = "aluno.dashboard.matriz@teste.local"
    matricula = "MAT-DASH-001"
    curso_codigo = "MDASH"
    turma_codigo = "MDASH-T01"

    with main.app.app_context():
        conn = main.get_db_connection()

        links_table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='matrizes_atividades_itens'"
        ).fetchone()
        assert links_table_exists is not None

        conn.execute(
            "INSERT INTO cursos (nome, codigo, duracao_periodos, status) VALUES (?, ?, ?, ?)",
            ("Curso Dashboard Matriz", curso_codigo, 8, "ativo"),
        )
        curso_id = conn.execute(
            "SELECT id FROM cursos WHERE codigo = ?",
            (curso_codigo,),
        ).fetchone()["id"]

        conn.execute(
            """
            INSERT INTO matrizes_atividades (
                curso_id, nome, versao, status, data_inicio_vigencia,
                horas_aac_obrigatorias, horas_extensao_obrigatorias, descricao
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (curso_id, "Matriz Dashboard", "2026.1", "vigente", "2026-01-01", 160, 80, "Teste"),
        )
        matriz_id = conn.execute(
            "SELECT id FROM matrizes_atividades WHERE curso_id = ? ORDER BY id DESC LIMIT 1",
            (curso_id,),
        ).fetchone()["id"]

        conn.execute(
            """
            INSERT INTO turmas (
                nome, ano, semestre, turno, status, numero, curso_id, matriz_id,
                ano_inicio, semestre_inicio, ano_fim, semestre_fim, codigo
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                turma_codigo,
                2026,
                1,
                "Manha",
                "Ativa",
                1,
                curso_id,
                matriz_id,
                2026,
                1,
                2029,
                2,
                turma_codigo,
            ),
        )
        turma_id = conn.execute(
            "SELECT id FROM turmas WHERE codigo = ?",
            (turma_codigo,),
        ).fetchone()["id"]

        conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?)",
            ("Aluno Dashboard Matriz", email, main.hash_password("aluno123"), "aluno", "usuario"),
        )
        usuario_id = conn.execute(
            "SELECT id FROM usuarios WHERE email = ?",
            (email,),
        ).fetchone()["id"]

        conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status) VALUES (?, ?, ?, ?, ?, ?)",
            (usuario_id, "Aluno Dashboard Matriz", matricula, email, turma_id, "Ativo"),
        )
        conn.commit()

    _login_aluno(client, usuario_id, "Aluno Dashboard Matriz")

    response = client.get("/aluno/dashboard", follow_redirects=False)
    assert response.status_code == 200


def test_aluno_nova_requisicao_obeys_turma_matrix_scope(client):
    allowed_name = "AAC Matriz Permitida Automatizada"
    blocked_name = "AAC Matriz Bloqueada Automatizada"
    email = "aluno.matriz.scope@teste.local"
    matricula = "MAT-SCOPE-001"

    with main.app.app_context():
        conn = main.get_db_connection()
        main.ensure_matrizes_atividades_table(conn)
        main.ensure_matriz_atividade_links_table(conn)
        main.ensure_turmas_matriz_schema(conn)

        curso = conn.execute("SELECT id, codigo FROM cursos ORDER BY id LIMIT 1").fetchone()
        assert curso is not None

        conn.execute("DELETE FROM requisicoes WHERE aluno_id IN (SELECT id FROM alunos WHERE matricula = ?)", (matricula,))
        conn.execute("DELETE FROM alunos WHERE matricula = ?", (matricula,))
        conn.execute("DELETE FROM usuarios WHERE email = ?", (email,))
        conn.execute("DELETE FROM atividades WHERE nome IN (?, ?)", (allowed_name, blocked_name))
        conn.execute("DELETE FROM matrizes_atividades WHERE nome = ?", ("Matriz Aluno Scope",))
        conn.execute("DELETE FROM turmas WHERE codigo = ?", (main.gerar_codigo_turma(curso["codigo"], 77),))

        allowed_id = conn.execute(
            """
            INSERT INTO atividades (
                grupo, nome, limite_horas, tipo_atividade, tem_limitacao, tipo_limitacao,
                limite_horas_total, limite_horas_semestral, documentos_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            ("1 - Grupo Scope", allowed_name, None, "Acadêmica Complementar", 0, None, None, None, None),
        ).fetchone()["id"]
        blocked_id = conn.execute(
            """
            INSERT INTO atividades (
                grupo, nome, limite_horas, tipo_atividade, tem_limitacao, tipo_limitacao,
                limite_horas_total, limite_horas_semestral, documentos_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            ("1 - Grupo Scope", blocked_name, None, "Acadêmica Complementar", 0, None, None, None, None),
        ).fetchone()["id"]
        matriz_id = conn.execute(
            """
            INSERT INTO matrizes_atividades (
                curso_id, nome, versao, status, data_inicio_vigencia,
                horas_aac_obrigatorias, horas_extensao_obrigatorias, descricao
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (curso["id"], "Matriz Aluno Scope", "2027.1", "vigente", "2027-01-01", 160, 80, "Teste de escopo"),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO matrizes_atividades_itens (matriz_id, atividade_id) VALUES (?, ?)",
            (matriz_id, allowed_id),
        )
        snapshot_version_id = add_exact_snapshot_authority(
            conn,
            matriz_id=matriz_id,
            atividade_id=allowed_id,
            prefix="aluno-matrix-scope",
        )
        turma_codigo = main.gerar_codigo_turma(curso["codigo"], 77)
        turma_id = conn.execute(
            """
            INSERT INTO turmas (
                nome, ano, semestre, turno, status, numero, curso_id, matriz_id,
                ano_inicio, semestre_inicio, ano_fim, semestre_fim, codigo
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (turma_codigo, None, None, "Noite", "Ativa", 77, curso["id"], matriz_id, 2027, 1, 2030, 2, turma_codigo),
        ).fetchone()["id"]
        usuario_id = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo) VALUES (?, ?, ?, ?) RETURNING id",
            ("Aluno Scope", email, main.hash_password("aluno123"), "aluno"),
        ).fetchone()["id"]
        aluno_id = conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status) VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
            (usuario_id, "Aluno Scope", matricula, email, turma_id, "Ativo"),
        ).fetchone()["id"]
        conn.commit()

    _login_aluno(client, usuario_id, "Aluno Scope")

    page = client.get("/aluno/nova-requisicao?tipo=Acadêmica%20Complementar")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert allowed_name in html
    assert blocked_name not in html

    blocked_post = client.post(
        "/aluno/nova-requisicao?tipo=Acadêmica%20Complementar",
        data={
            "atividade_id": str(blocked_id),
            "nome_evento": "Evento fora da matriz",
            "data_evento": "2027-05-10",
            "horas_solicitadas": "4",
            "observacao": "Teste",
        },
        follow_redirects=True,
    )
    assert blocked_post.status_code == 200
    assert "não está disponível para a matriz da sua turma" in blocked_post.get_data(as_text=True)

    allowed_post = client.post(
        "/aluno/nova-requisicao?tipo=Acadêmica%20Complementar",
        data={
            "atividade_id": str(allowed_id),
            "nome_evento": "Evento permitido",
            "data_evento": "2027-05-10",
            "horas_solicitadas": "4",
            "observacao": "Teste permitido",
        },
        follow_redirects=False,
    )
    assert allowed_post.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        reqs = conn.execute(
            "SELECT atividade_id FROM requisicoes WHERE aluno_id = ? ORDER BY id",
            (aluno_id,),
        ).fetchall()
        atividade_ids = [row["atividade_id"] for row in reqs]
        assert blocked_id not in atividade_ids
        assert allowed_id in atividade_ids
        conn.execute("DELETE FROM requisicoes WHERE aluno_id = ?", (aluno_id,))
        conn.execute("DELETE FROM alunos WHERE id = ?", (aluno_id,))
        conn.execute("DELETE FROM usuarios WHERE id = ?", (usuario_id,))
        conn.execute("DELETE FROM turmas WHERE id = ?", (turma_id,))
        version_row = conn.execute(
            "SELECT atividade_base_id, norma_id FROM atividade_versao WHERE id = ?",
            (snapshot_version_id,),
        ).fetchone()
        conn.execute(
            "DELETE FROM matriz_atividade_versao_item WHERE atividade_versao_id = ?",
            (snapshot_version_id,),
        )
        conn.execute("DELETE FROM matriz_norma WHERE matriz_id = ?", (matriz_id,))
        conn.execute("DELETE FROM atividade_legacy_map WHERE atividade_id_legacy = ?", (allowed_id,))
        conn.execute("DELETE FROM atividade_versao WHERE id = ?", (snapshot_version_id,))
        conn.execute("DELETE FROM norma_atividade WHERE id = ?", (version_row["norma_id"],))
        conn.execute("DELETE FROM atividade_base WHERE id = ?", (version_row["atividade_base_id"],))
        conn.execute("DELETE FROM matrizes_atividades WHERE id = ?", (matriz_id,))
        conn.execute("DELETE FROM atividades WHERE id IN (?, ?)", (allowed_id, blocked_id))
        conn.commit()


def test_aluno_minhas_requisicoes_uses_actions_menu_for_delete(client):
    atividade_nome = "Atividade Req Toolbar Aluno"
    email = "aluno.req.toolbar@teste.local"
    matricula = "REQ-TOOLBAR-001"

    with main.app.app_context():
        conn = main.get_db_connection()
        main.ensure_turmas_matriz_schema(conn)

        curso = conn.execute("SELECT id, codigo FROM cursos ORDER BY id LIMIT 1").fetchone()
        assert curso is not None

        conn.execute("DELETE FROM requisicoes WHERE aluno_id IN (SELECT id FROM alunos WHERE matricula = ?)", (matricula,))
        conn.execute("DELETE FROM alunos WHERE matricula = ?", (matricula,))
        conn.execute("DELETE FROM usuarios WHERE email = ?", (email,))
        conn.execute("DELETE FROM atividades WHERE nome = ?", (atividade_nome,))
        conn.execute("DELETE FROM turmas WHERE codigo = ?", (main.gerar_codigo_turma(curso["codigo"], 88),))

        atividade_id = conn.execute(
            """
            INSERT INTO atividades (
                grupo, nome, limite_horas, tipo_atividade, tem_limitacao, tipo_limitacao,
                limite_horas_total, limite_horas_semestral, documentos_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            ("1 - Grupo Req", atividade_nome, None, "Acadêmica Complementar", 0, None, None, None, None),
        ).fetchone()["id"]
        turma_codigo = main.gerar_codigo_turma(curso["codigo"], 88)
        turma_id = conn.execute(
            """
            INSERT INTO turmas (
                nome, ano, semestre, turno, status, numero, curso_id, matriz_id,
                ano_inicio, semestre_inicio, ano_fim, semestre_fim, codigo
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (turma_codigo, None, None, "Noite", "Ativa", 88, curso["id"], None, 2027, 1, 2030, 2, turma_codigo),
        ).fetchone()["id"]
        usuario_id = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo) VALUES (?, ?, ?, ?) RETURNING id",
            ("Aluno Req Toolbar", email, main.hash_password("aluno123"), "aluno"),
        ).fetchone()["id"]
        aluno_id = conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status) VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
            (usuario_id, "Aluno Req Toolbar", matricula, email, turma_id, "Ativo"),
        ).fetchone()["id"]
        conn.execute(
            """
            INSERT INTO requisicoes (
                aluno_id, atividade_id, data_solicitacao, data_evento, horas_solicitadas, horas_deferidas,
                status, nome_evento, observacao
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (aluno_id, atividade_id, "2027-06-10", "2027-06-10", 4, 0, "Pendente", "Evento Toolbar", "Teste"),
        )
        conn.commit()

    _login_aluno(client, usuario_id, "Aluno Req Toolbar")

    try:
        page = client.get("/aluno/requisicoes")
        assert page.status_code == 200
        html = page.get_data(as_text=True)

        assert 'id="btn-aluno-req-actions"' in html
        assert 'id="aluno-req-actions-menu"' in html
        assert 'id="aluno-req-action-select-all"' in html
        assert 'class="btn toolbar-select-all"' not in html
        assert 'class="btn toolbar-bulk-delete"' not in html
        assert 'data-action="delete"' not in html
        assert "enableSelectAllButton: false" in html
        assert "enableBulkDelete: false" in html
        assert "toolbarSelector: '#impressoes-toolbar'" in html
        assert "rowsRootSelector: '#minhas-requisicoes-list'" in html
        assert "?delete=1" in html
    finally:
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute("DELETE FROM requisicoes WHERE aluno_id = ?", (aluno_id,))
            conn.execute("DELETE FROM alunos WHERE id = ?", (aluno_id,))
            conn.execute("DELETE FROM usuarios WHERE id = ?", (usuario_id,))
            conn.execute("DELETE FROM turmas WHERE id = ?", (turma_id,))
            conn.execute("DELETE FROM atividades WHERE id = ?", (atividade_id,))
            conn.commit()
