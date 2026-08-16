import os
import sqlite3
import sys
from datetime import datetime, timedelta

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from app import db as app_db_module
import main


@pytest.fixture()
def client(tmp_path):
    app = main.app
    temp_database = tmp_path / "admin_dashboard_request_alert.db"
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


def _login_admin(client, usuario_id: int, nome: str):
    with client.session_transaction() as sess:
        sess["user_id"] = usuario_id
        sess["user_type"] = "admin"
        sess["user_name"] = nome


def _seed_pending_request(conn, suffix: str, status: str = "Pendente") -> int:
    curso = conn.execute("SELECT id, codigo FROM cursos ORDER BY id LIMIT 1").fetchone()
    assert curso is not None
    next_turma_numero = conn.execute("SELECT COALESCE(MAX(numero), 0) + 1 AS next_num FROM turmas").fetchone()["next_num"]

    atividade_id = conn.execute(
        """
        INSERT INTO atividades (
            grupo, nome, limite_horas, tipo_atividade, tem_limitacao, tipo_limitacao,
            limite_horas_total, limite_horas_semestral, documentos_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        (
            "1 - Grupo Teste",
            f"AAC Admin Alert {suffix}",
            None,
            "Acadêmica Complementar",
            0,
            None,
            None,
            None,
            None,
        ),
    ).fetchone()["id"]

    turma_codigo = main.gerar_codigo_turma(curso["codigo"], next_turma_numero)
    turma_id = conn.execute(
        """
        INSERT INTO turmas (
            nome, ano, semestre, turno, status, numero, curso_id, matriz_id,
            ano_inicio, semestre_inicio, ano_fim, semestre_fim, codigo
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        (turma_codigo, None, None, "Noite", "Ativa", next_turma_numero, curso["id"], None, 2030, 1, 2033, 2, turma_codigo),
    ).fetchone()["id"]

    aluno_user_id = conn.execute(
        "INSERT INTO usuarios (nome, email, senha, tipo) VALUES (?, ?, ?, ?) RETURNING id",
        (f"Aluno {suffix}", f"aluno.{suffix}@teste.local", main.hash_password("aluno123"), "aluno"),
    ).fetchone()["id"]

    aluno_id = conn.execute(
        "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status) VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
        (aluno_user_id, f"Aluno {suffix}", f"MAT-{suffix}", f"aluno.{suffix}@teste.local", turma_id, "Ativo"),
    ).fetchone()["id"]

    return conn.execute(
        """
        INSERT INTO requisicoes (
            aluno_id, atividade_id, data_solicitacao, data_evento, horas_solicitadas,
            nome_evento, status, horas_deferidas, observacao, arquivo_comprovante,
            data_processamento, admin_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        (
            aluno_id,
            atividade_id,
            "2030-05-10 11:00:00",
            "2030-05-10",
            6,
            f"Evento {suffix}",
            status,
            None,
            None,
            None,
            None,
            None,
        ),
    ).fetchone()["id"]


def _insert_matrix(conn, curso_id: int, suffix: str, horas_aac: int, horas_aeu: int) -> int:
    return conn.execute(
        """
        INSERT INTO matrizes_atividades (
            curso_id, nome, versao, status, horas_aac_obrigatorias, horas_extensao_obrigatorias
        ) VALUES (?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        (curso_id, f"Matriz {suffix}", f"v{suffix}", "ativa", horas_aac, horas_aeu),
    ).fetchone()["id"]


@pytest.mark.parametrize(
    ("access_level", "expected_kind", "email_suffix"),
    [
        ("administrativo", "coordinator_new_request", "coordenador"),
        ("admin_total", "admin_new_request", "admin"),
    ],
)
def test_admin_dashboard_shows_new_request_alert_only_once_per_user(
    client,
    access_level: str,
    expected_kind: str,
    email_suffix: str,
):
    conn = _open_test_db()
    try:
        usuario_id = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?) RETURNING id",
            (
                f"Admin {email_suffix}",
                f"{email_suffix}@teste.local",
                main.hash_password("admin123"),
                "admin",
                access_level,
            ),
        ).fetchone()["id"]
        req_id = _seed_pending_request(conn, email_suffix)
        conn.commit()
    finally:
        conn.close()

    _login_admin(client, usuario_id, f"Admin {email_suffix}")

    first_dashboard = client.get("/admin/dashboard")
    assert first_dashboard.status_code == 200
    first_html = first_dashboard.data.decode("utf-8")
    assert "Há novas solicitações aguardando análise." in first_html
    assert 'href="/admin/requisicoes"' in first_html
    assert f'data-bg-color="{main.AUTO_ALERT_YELLOW_BG}"' in first_html
    assert f'data-border-color="{main.AUTO_ALERT_YELLOW_BORDER}"' in first_html

    conn = _open_test_db()
    try:
        receipt = conn.execute(
            """
            SELECT seen_at
              FROM requisicao_alerta_receipts
             WHERE requisicao_id = ?
               AND usuario_id = ?
               AND alert_kind = ?
            """,
            (req_id, usuario_id, expected_kind),
        ).fetchone()
        assert receipt is not None
        assert receipt["seen_at"] is not None
    finally:
        conn.close()

    second_dashboard = client.get("/admin/dashboard")
    assert second_dashboard.status_code == 200
    second_html = second_dashboard.data.decode("utf-8")
    assert "Há novas solicitações aguardando análise." not in second_html


def test_admin_dashboard_prioritizes_turma_view_and_removes_redundant_cards(client):
    conn = _open_test_db()
    try:
        usuario_id = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?) RETURNING id",
            (
                "Admin Dashboard",
                "dashboard@teste.local",
                main.hash_password("admin123"),
                "admin",
                "admin_total",
            ),
        ).fetchone()["id"]

        _seed_pending_request(conn, "t1")
        _seed_pending_request(conn, "t2")
        _seed_pending_request(conn, "t3")
        conn.commit()
    finally:
        conn.close()

    _login_admin(client, usuario_id, "Admin Dashboard")

    response = client.get("/admin/dashboard")
    assert response.status_code == 200
    html = response.data.decode("utf-8")

    assert "Requisições" in html
    assert "3 pendentes de 3 requisições" not in html
    assert "Taxa média de resposta" in html
    assert "Dias" in html
    assert "Abaixo da meta (10 dias)" in html
    assert "0 devolvidas em aberto" in html
    assert "Cadastrados" in html
    assert "3 turmas" in html
    assert "AAC 3 · AEU 0" in html
    assert "Acompanhamento:" in html
    assert "Dados" in html
    assert "Alunos ativos" in html
    assert "1º período" in html
    assert "Cumprimento" in html
    assert "N/A" in html
    assert "Relação entre número de alunos percentual total atingido" in html
    assert "75 a 100%" in html
    assert "0 a 25%" in html
    assert 'class="dashboard-turma-summary"' not in html
    assert 'class="dashboard-turma-summary-label">Pendentes' not in html
    assert 'class="dashboard-turma-summary-label">Alunos' not in html
    assert 'class="kpi-title">PPA-' not in html
    assert 'dashboard-turma-action' in html

    assert "A fazer agora" not in html
    assert "Atividades por Tipo" not in html
    assert "Resumo rápido" not in html
    assert "Requisições por tipo" not in html
    assert '<span class="kpi-title">Turmas</span>' not in html
    assert "1,0 por turma" not in html
    assert "Com AAC" not in html
    assert "Com AEU" not in html
    assert "Acompanhamento consolidado da turma" not in html
    assert "Acompanhamento por turma" not in html
    assert "<section class=\"content-block dashboard-section\">" not in html


def test_admin_dashboard_shows_open_returned_requests_count(client):
    conn = _open_test_db()
    try:
        usuario_id = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?) RETURNING id",
            (
                "Admin Devolvidas",
                "dashboard-devolvidas@teste.local",
                main.hash_password("admin123"),
                "admin",
                "admin_total",
            ),
        ).fetchone()["id"]

        _seed_pending_request(conn, "pend-1")
        _seed_pending_request(conn, "dev-1", status="Devolvida")
        _seed_pending_request(conn, "dev-2", status="Devolvida")
        conn.commit()
    finally:
        conn.close()

    _login_admin(client, usuario_id, "Admin Devolvidas")

    response = client.get("/admin/dashboard")
    assert response.status_code == 200
    html = response.data.decode("utf-8")

    assert "1 pendentes de 3 requisições" not in html
    assert "2 devolvidas em aberto" in html


def test_admin_dashboard_highlights_average_pending_response_above_goal(client):
    conn = _open_test_db()
    try:
        usuario_id = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?) RETURNING id",
            (
                "Admin Tempo Medio",
                "dashboard-tempo-medio@teste.local",
                main.hash_password("admin123"),
                "admin",
                "admin_total",
            ),
        ).fetchone()["id"]

        req1 = _seed_pending_request(conn, "avg-1")
        req2 = _seed_pending_request(conn, "avg-2")
        conn.execute(
            "UPDATE requisicoes SET data_solicitacao = ? WHERE id = ?",
            ((datetime.now() - timedelta(days=12)).strftime("%Y-%m-%d %H:%M:%S"), req1),
        )
        conn.execute(
            "UPDATE requisicoes SET data_solicitacao = ? WHERE id = ?",
            ((datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d %H:%M:%S"), req2),
        )
        conn.commit()
    finally:
        conn.close()

    _login_admin(client, usuario_id, "Admin Tempo Medio")

    response = client.get("/admin/dashboard")
    assert response.status_code == 200
    html = response.data.decode("utf-8")

    assert "Taxa média de resposta" in html
    assert "Acima da meta (10 dias)" in html
    assert "dashboard-kpi-value-danger" in html


def test_admin_configuracoes_page_saves_and_resets_response_time_settings(client):
    conn = _open_test_db()
    try:
        usuario_id = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?) RETURNING id",
            (
                "Admin Configuracoes",
                "dashboard-config@teste.local",
                main.hash_password("admin123"),
                "admin",
                "admin_total",
            ),
        ).fetchone()["id"]
        conn.commit()
    finally:
        conn.close()

    _login_admin(client, usuario_id, "Admin Configuracoes")

    page = client.get("/admin/configuracoes")
    assert page.status_code == 200
    html = page.data.decode("utf-8")
    assert "Configurações" in html
    assert 'href="/admin/configuracoes"' in html
    assert 'name="response_goal_days"' in html
    assert 'name="response_metrics_reset_at"' in html
    assert "Resetar contagem" in html

    save_response = client.post(
        "/admin/configuracoes/tempo-resposta",
        data={
            "response_goal_days": "7",
            "response_metrics_reset_at": "2026-04-15",
        },
        follow_redirects=False,
    )
    assert save_response.status_code in (302, 303)
    assert save_response.headers["Location"].endswith("/admin/configuracoes")

    conn = _open_test_db()
    try:
        settings = main.get_response_time_settings(conn)
        assert settings["response_goal_days"] == 7
        assert settings["response_metrics_reset_at"] == "2026-04-15"
    finally:
        conn.close()

    reset_response = client.post("/admin/configuracoes/tempo-resposta/reset", follow_redirects=False)
    assert reset_response.status_code in (302, 303)
    assert reset_response.headers["Location"].endswith("/admin/configuracoes")

    conn = _open_test_db()
    try:
        settings = main.get_response_time_settings(conn)
        assert settings["response_metrics_reset_at"] == datetime.now().date().isoformat()
    finally:
        conn.close()


def test_admin_dashboard_uses_custom_response_goal_and_reset_start(client):
    conn = _open_test_db()
    try:
        usuario_id = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?) RETURNING id",
            (
                "Admin Meta Personalizada",
                "dashboard-meta-personalizada@teste.local",
                main.hash_password("admin123"),
                "admin",
                "admin_total",
            ),
        ).fetchone()["id"]

        req_old = _seed_pending_request(conn, "meta-old")
        req_new = _seed_pending_request(conn, "meta-new")
        conn.execute(
            "UPDATE requisicoes SET data_solicitacao = ? WHERE id = ?",
            ((datetime.now() - timedelta(days=20)).strftime("%Y-%m-%d %H:%M:%S"), req_old),
        )
        conn.execute(
            "UPDATE requisicoes SET data_solicitacao = ? WHERE id = ?",
            ((datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"), req_new),
        )
        main.save_app_settings(
            conn,
            {
                "response_goal_days": "5",
                "response_metrics_reset_at": (datetime.now() - timedelta(days=3)).date().isoformat(),
            },
        )
        conn.commit()
    finally:
        conn.close()

    _login_admin(client, usuario_id, "Admin Meta Personalizada")

    response = client.get("/admin/dashboard")
    assert response.status_code == 200
    html = response.data.decode("utf-8")

    assert "Taxa média de resposta" in html
    assert "Abaixo da meta (5 dias)" in html
    assert "Nenhuma atrasada há mais de 5 dias" in html
    assert "Acima da meta (5 dias)" not in html


def test_admin_dashboard_shows_na_without_progress_for_non_applicable_turma_metrics(client):
    conn = _open_test_db()
    try:
        usuario_id = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?) RETURNING id",
            (
                "Admin N A",
                "dashboard-na@teste.local",
                main.hash_password("admin123"),
                "admin",
                "admin_total",
            ),
        ).fetchone()["id"]

        _seed_pending_request(conn, "na")
        turma = conn.execute(
            "SELECT id, codigo, curso_id FROM turmas ORDER BY id DESC LIMIT 1"
        ).fetchone()
        matriz_id = _insert_matrix(conn, turma["curso_id"], "na", horas_aac=160, horas_aeu=0)
        conn.execute("UPDATE turmas SET matriz_id = ? WHERE id = ?", (matriz_id, turma["id"]))
        conn.commit()
    finally:
        conn.close()

    _login_admin(client, usuario_id, "Admin N A")

    response = client.get("/admin/dashboard")
    assert response.status_code == 200
    html = response.data.decode("utf-8")

    assert "N/A" in html
    assert f'aria-label="Progresso AAC da turma {turma["codigo"]}"' in html
    assert f'aria-label="Progresso AEU da turma {turma["codigo"]}"' not in html
