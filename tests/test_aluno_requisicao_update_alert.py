import os
import sqlite3
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from app import db as app_db_module
import main


@pytest.fixture()
def client(tmp_path):
    app = main.app
    temp_database = tmp_path / "aluno_requisicao_update_alert.db"
    original_database = main.DATABASE
    original_env = os.environ.get("APP_DATABASE")

    os.environ["APP_DATABASE"] = str(temp_database)
    main.DATABASE = str(temp_database)
    app_db_module.DATABASE = str(temp_database)

    with app.app_context():
        try:
            main.close_db_connection(None)
        except Exception:
            pass
        main.init_db()
        yield app.test_client()
        try:
            main.close_db_connection(None)
        except Exception:
            pass

    main.DATABASE = original_database
    app_db_module.DATABASE = original_database
    if original_env is None:
        os.environ.pop("APP_DATABASE", None)
    else:
        os.environ["APP_DATABASE"] = original_env


def _open_test_db():
    conn = sqlite3.connect(main.DATABASE, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def _login_admin(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["user_type"] = "admin"
        sess["user_name"] = "Administrador"


def _login_aluno(client, usuario_id: int, nome: str):
    with client.session_transaction() as sess:
        sess["user_id"] = usuario_id
        sess["user_type"] = "aluno"
        sess["user_name"] = nome


def test_aluno_dashboard_shows_request_update_alert_only_once(client):
    conn = _open_test_db()
    try:
        curso = conn.execute("SELECT id, codigo FROM cursos ORDER BY id LIMIT 1").fetchone()
        assert curso is not None

        atividade_id = conn.execute(
            """
            INSERT INTO atividades (
                grupo, nome, limite_horas, tipo_atividade, tem_limitacao, tipo_limitacao,
                limite_horas_total, limite_horas_semestral, documentos_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            ("1 - Grupo Teste", "AAC Alerta Atualizacao", None, "Acadêmica Complementar", 0, None, None, None, None),
        ).fetchone()["id"]
        matriz_id = conn.execute(
            """
            INSERT INTO matrizes_atividades (curso_id, nome, versao, status, data_inicio_vigencia)
            VALUES (?, ?, ?, ?, ?)
            RETURNING id
            """,
            (curso["id"], "Matriz Alerta Atualizacao", "1", "vigente", "2030-01-01"),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO matrizes_atividades_itens (matriz_id, atividade_id) VALUES (?, ?)",
            (matriz_id, atividade_id),
        )
        turma_codigo = main.gerar_codigo_turma(curso["codigo"], 96)
        turma_id = conn.execute(
            """
            INSERT INTO turmas (
                nome, ano, semestre, turno, status, numero, curso_id, matriz_id,
                ano_inicio, semestre_inicio, ano_fim, semestre_fim, codigo
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (turma_codigo, None, None, "Noite", "Ativa", 96, curso["id"], matriz_id, 2030, 1, 2033, 2, turma_codigo),
        ).fetchone()["id"]
        usuario_id = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo) VALUES (?, ?, ?, ?) RETURNING id",
            ("Aluno Alerta", "aluno.alerta@teste.local", main.hash_password("aluno123"), "aluno"),
        ).fetchone()["id"]
        aluno_id = conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status) VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
            (usuario_id, "Aluno Alerta", "MAT-ALERTA-001", "aluno.alerta@teste.local", turma_id, "Ativo"),
        ).fetchone()["id"]
        req_id = conn.execute(
            """
            INSERT INTO requisicoes (
                aluno_id, atividade_id, data_solicitacao, data_evento, horas_solicitadas,
                nome_evento, status, horas_deferidas, observacao, arquivo_comprovante,
                data_processamento, admin_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (aluno_id, atividade_id, "2030-05-10 10:00:00", "2030-05-10", 8, "Evento Alerta", "Pendente", None, None, None, None, None),
        ).fetchone()["id"]
        conn.commit()
    finally:
        conn.close()

    _login_admin(client)
    response = client.post(
        f"/admin/processar_requisicao/{req_id}",
        data={"status": "Deferida", "observacao": "Processada"},
        follow_redirects=False,
    )
    assert response.status_code == 302

    conn = _open_test_db()
    try:
        row = conn.execute(
            "SELECT aluno_update_notified_at, aluno_update_seen_at, status FROM requisicoes WHERE id = ?",
            (req_id,),
        ).fetchone()
        assert row is not None
        assert row["status"] == "Deferida"
        assert row["aluno_update_notified_at"] is not None
        assert row["aluno_update_seen_at"] is None
    finally:
        conn.close()

    _login_aluno(client, usuario_id, "Aluno Alerta")
    first_dashboard = client.get("/aluno/dashboard")
    assert first_dashboard.status_code == 200
    first_html = first_dashboard.data.decode("utf-8")
    expected_alert = main.resolve_user_message("Houve atualizações nas suas solicitações.")
    assert expected_alert in first_html
    assert 'href="/aluno/requisicoes"' in first_html
    assert f'data-bg-color="{main.AUTO_ALERT_YELLOW_BG}"' in first_html
    assert f'data-border-color="{main.AUTO_ALERT_YELLOW_BORDER}"' in first_html

    conn = _open_test_db()
    try:
        row = conn.execute(
            "SELECT aluno_update_seen_at FROM requisicoes WHERE id = ?",
            (req_id,),
        ).fetchone()
        assert row is not None
        assert row["aluno_update_seen_at"] is not None
    finally:
        conn.close()

    second_dashboard = client.get("/aluno/dashboard")
    assert second_dashboard.status_code == 200
    second_html = second_dashboard.data.decode("utf-8")
    assert expected_alert not in second_html
