import os
import sys
import uuid

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


def test_admin_requisicao_processing_ui_uses_labeled_action_rows(client):
    suffix = uuid.uuid4().hex[:8]
    activity_name = f"AAC UI Processamento {suffix}"
    email = f"admin.process.ui.{suffix}@teste.local"
    matricula = f"MAT-PROCESS-UI-{suffix}"

    with main.app.app_context():
        conn = main.get_db_connection()
        try:
            curso = conn.execute("SELECT id, codigo FROM cursos ORDER BY id LIMIT 1").fetchone()
            assert curso is not None
            turma_codigo = main.gerar_codigo_turma(curso["codigo"], 94)

            conn.execute(
                "DELETE FROM requisicao_arquivos WHERE requisicao_id IN (SELECT id FROM requisicoes WHERE aluno_id IN (SELECT id FROM alunos WHERE matricula = ?))",
                (matricula,),
            )
            conn.execute("DELETE FROM requisicoes WHERE aluno_id IN (SELECT id FROM alunos WHERE matricula = ?)", (matricula,))
            conn.execute("DELETE FROM alunos WHERE matricula = ?", (matricula,))
            conn.execute("DELETE FROM usuarios WHERE email = ?", (email,))
            conn.execute("DELETE FROM turmas WHERE codigo = ?", (turma_codigo,))
            conn.execute("DELETE FROM atividades WHERE nome = ?", (activity_name,))

            atividade_id = conn.execute(
                """
                INSERT INTO atividades (
                    grupo, nome, limite_horas, tipo_atividade, tem_limitacao, tipo_limitacao,
                    limite_horas_total, limite_horas_semestral, documentos_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                RETURNING id
                """,
                ("9 - Grupo UI", activity_name, None, "Acadêmica Complementar", 0, None, None, None, None),
            ).fetchone()["id"]
            turma_id = conn.execute(
                """
                INSERT INTO turmas (
                    nome, ano, semestre, turno, status, numero, curso_id, matriz_id,
                    ano_inicio, semestre_inicio, ano_fim, semestre_fim, codigo
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                RETURNING id
                """,
                (turma_codigo, None, None, "Noite", "Ativa", 94, curso["id"], None, 2030, 1, 2033, 2, turma_codigo),
            ).fetchone()["id"]
            usuario_id = conn.execute(
                "INSERT INTO usuarios (nome, email, senha, tipo) VALUES (?, ?, ?, ?) RETURNING id",
                ("Aluno Process UI", email, main.hash_password("aluno123"), "aluno"),
            ).fetchone()["id"]
            aluno_id = conn.execute(
                "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status) VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
                (usuario_id, "Aluno Process UI", matricula, email, turma_id, "Ativo"),
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
                (aluno_id, atividade_id, "2030-03-10 10:00:00", "2030-03-10", 8, "Evento UI", "Pendente", None, None, None, None, None),
            ).fetchone()["id"]
            conn.commit()
        finally:
            conn.close()

    _login_admin(client)

    list_response = client.get("/admin/requisicoes")
    assert list_response.status_code == 200
    list_html = list_response.data.decode("utf-8")
    assert 'id="m_footer_process_row" hidden' in list_html
    assert 'id="m_footer_post_row" hidden' in list_html
    assert 'id="m_footer_secondary_row" hidden' in list_html
    assert 'data-action="indeferir"' in list_html
    assert 'data-action="deferir_parte"' in list_html
    assert 'data-action="deferir"' in list_html
    assert 'data-action="encerrar"' in list_html
    assert 'data-action="devolver"' in list_html
    assert 'data-action="reabrir"' in list_html
    assert '>Indeferir<' in list_html
    assert '>Deferir Parcialmente<' in list_html
    assert '>Deferir<' in list_html
    assert '>Encerrar<' in list_html
    assert '>Devolver<' in list_html
    assert '>Reabrir<' in list_html
    assert '>Cancelar<' in list_html
    assert '>Confirmar<' in list_html
    assert '>Voltar<' in list_html
    # Estrutura JS: fluxo de dois passos (selecionar ação → confirmar)
    assert "window.__setSaveButton = function(label, action)" in list_html
    assert "window.__setReqModalMode = function(mode, statusHint)" in list_html
    assert "window.__enterProcessConfirm = function(selectedAction)" in list_html
    assert "window.__exitProcessConfirm = function(statusHint)" in list_html
    assert "let pendingAction = null;" in list_html
    assert "async function executeConfirmedAction()" in list_html
    assert "const ACTION_KEYS = new Set(" in list_html
    assert "const isPending = !s || s.includes('pend') || s.includes('aguard');" in list_html
    assert "setFooterRowVisibility(processRow,   isPending);" in list_html
    assert "setFooterRowVisibility(postRow,      !isPending);" in list_html
    assert "reabrir: 'Pendente'" in list_html

    process_response = client.get(f"/admin/processar_requisicao/{req_id}")
    assert process_response.status_code == 200
    process_html = process_response.data.decode("utf-8")
    assert 'class="process-action-buttons"' in process_html
    assert 'class="process-form-actions"' in process_html
    assert 'data-process-status="Indeferida"' in process_html
    assert 'data-process-status="Deferida Parcialmente"' in process_html
    assert 'data-process-status="Deferida"' in process_html
    assert '>Indeferir<' in process_html
    assert '>Deferir Parcialmente<' in process_html
    assert '>Deferir<' in process_html
    assert '>Salvar<' in process_html
    assert '>Voltar<' in process_html


def test_admin_processar_requisicao_reabrir_persists_pending_status(client):
    suffix = uuid.uuid4().hex[:8]
    activity_name = f"AAC UI Reabrir {suffix}"
    email = f"admin.reabrir.{suffix}@teste.local"
    matricula = f"MAT-REABRIR-{suffix}"

    with main.app.app_context():
        conn = main.get_db_connection()
        try:
            curso = conn.execute("SELECT id, codigo FROM cursos ORDER BY id LIMIT 1").fetchone()
            assert curso is not None
            turma_codigo = main.gerar_codigo_turma(curso["codigo"], 95)

            atividade_id = conn.execute(
                """
                INSERT INTO atividades (
                    grupo, nome, limite_horas, tipo_atividade, tem_limitacao, tipo_limitacao,
                    limite_horas_total, limite_horas_semestral, documentos_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                RETURNING id
                """,
                ("10 - Grupo UI", activity_name, None, "Acadêmica Complementar", 0, None, None, None, None),
            ).fetchone()["id"]
            turma_id = conn.execute(
                """
                INSERT INTO turmas (
                    nome, ano, semestre, turno, status, numero, curso_id, matriz_id,
                    ano_inicio, semestre_inicio, ano_fim, semestre_fim, codigo
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                RETURNING id
                """,
                (turma_codigo, None, None, "Noite", "Ativa", 95, curso["id"], None, 2030, 1, 2033, 2, turma_codigo),
            ).fetchone()["id"]
            usuario_id = conn.execute(
                "INSERT INTO usuarios (nome, email, senha, tipo) VALUES (?, ?, ?, ?) RETURNING id",
                ("Aluno Reabrir UI", email, main.hash_password("aluno123"), "aluno"),
            ).fetchone()["id"]
            aluno_id = conn.execute(
                "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status) VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
                (usuario_id, "Aluno Reabrir UI", matricula, email, turma_id, "Ativo"),
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
                (aluno_id, atividade_id, "2030-04-10 10:00:00", "2030-04-10", 6, "Evento Reabrir", "Indeferida", None, "Motivo", None, "2030-04-11 11:00:00", 1),
            ).fetchone()["id"]
            conn.commit()
        finally:
            conn.close()

    _login_admin(client)

    response = client.post(
        f"/admin/processar_requisicao/{req_id}",
        data={"status": "Pendente", "observacao": "Reaberta"},
        follow_redirects=False,
    )
    assert response.status_code == 302

    with main.app.app_context():
        conn = main.get_db_connection()
        try:
            row = conn.execute(
                "SELECT status, data_processamento, admin_id, horas_deferidas, observacao FROM requisicoes WHERE id = ?",
                (req_id,),
            ).fetchone()
            assert row is not None
            assert row["status"] == "Pendente"
            assert row["data_processamento"] is None
            assert row["admin_id"] is None
            assert row["horas_deferidas"] is None
            assert row["observacao"] == "Reaberta"
        finally:
            conn.close()