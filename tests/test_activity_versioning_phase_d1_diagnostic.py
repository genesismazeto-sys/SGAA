import os
import sys
import uuid

import pytest


BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main
from app import db as app_db_module
from tests.versioned_test_support import isolated_versioned_app_env


def _set_admin_session(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["user_type"] = "admin"
        sess["user_name"] = "Administrador"


@pytest.fixture()
def diagnostic_client(tmp_path):
    with isolated_versioned_app_env(tmp_path, "diagnostic_versioned.db") as env:
        yield env["client"]


@pytest.fixture()
def isolated_legacy_client(tmp_path):
    app = main.app
    temp_database = tmp_path / "phase_d1_legacy_flow.db"
    temp_uploads = tmp_path / "uploads"
    temp_documents = tmp_path / "documentos_alunos"
    temp_local_backups = tmp_path / "local_backups"
    temp_cloud_backups = tmp_path / "cloud_backups"
    temp_uploads.mkdir(parents=True, exist_ok=True)
    temp_documents.mkdir(parents=True, exist_ok=True)
    temp_local_backups.mkdir(parents=True, exist_ok=True)
    temp_cloud_backups.mkdir(parents=True, exist_ok=True)

    original_database = main.DATABASE
    original_app_db_database = app_db_module.DATABASE
    original_env_database = os.environ.get("APP_DATABASE")
    original_config_database_path = app.config.get("DATABASE_PATH")
    original_upload_folder = app.config.get("UPLOAD_FOLDER")
    original_documents_folder = app.config.get("DOCUMENTOS_ALUNOS_FOLDER")
    original_local_backup_dir = app.config.get("LOCAL_BACKUP_DIR")
    original_cloud_backup_dir = app.config.get("CLOUD_BACKUP_DIR")
    original_testing = app.config.get("TESTING")

    os.environ["APP_DATABASE"] = str(temp_database)
    main.DATABASE = str(temp_database)
    app_db_module.DATABASE = str(temp_database)
    app.config["DATABASE_PATH"] = str(temp_database)
    app.config["UPLOAD_FOLDER"] = str(temp_uploads)
    app.config["DOCUMENTOS_ALUNOS_FOLDER"] = str(temp_documents)
    app.config["LOCAL_BACKUP_DIR"] = str(temp_local_backups)
    app.config["CLOUD_BACKUP_DIR"] = str(temp_cloud_backups)
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
        if original_env_database is None:
            os.environ.pop("APP_DATABASE", None)
        else:
            os.environ["APP_DATABASE"] = original_env_database
        app.config["DATABASE_PATH"] = original_config_database_path
        app.config["UPLOAD_FOLDER"] = original_upload_folder
        app.config["DOCUMENTOS_ALUNOS_FOLDER"] = original_documents_folder
        app.config["LOCAL_BACKUP_DIR"] = original_local_backup_dir
        app.config["CLOUD_BACKUP_DIR"] = original_cloud_backup_dir
        app.config["TESTING"] = original_testing


def _get_turma_id_by_code(code: str) -> int:
    with main.app.app_context():
        conn = main.get_db_connection()
        row = conn.execute("SELECT id FROM turmas WHERE codigo = ?", (code,)).fetchone()
        assert row is not None
        return row["id"]


def _seed_legacy_flow_context():
    suffix = uuid.uuid4().hex[:8]
    curso_codigo = f"D1-{suffix}"
    turma_codigo = f"{curso_codigo}-T01"
    aluno_email = f"d1.aluno.{suffix}@teste.local"
    atividade_nome = f"Atividade D1 {suffix}"

    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "INSERT INTO cursos (nome, codigo, duracao_periodos, status) VALUES (?, ?, ?, ?)",
            ("Curso D1", curso_codigo, 8, "ativo"),
        )
        curso_id = conn.execute(
            "SELECT id FROM cursos WHERE codigo = ?",
            (curso_codigo,),
        ).fetchone()["id"]
        matriz_id = conn.execute(
            """
            INSERT INTO matrizes_atividades (curso_id, nome, versao, status, data_inicio_vigencia)
            VALUES (?, ?, ?, ?, ?)
            RETURNING id
            """,
            (curso_id, f"Matriz D1 {suffix}", "1", "vigente", "2026-01-01"),
        ).fetchone()["id"]

        conn.execute(
            """
            INSERT INTO turmas (nome, ano, semestre, turno, status, numero, curso_id, matriz_id, codigo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("Turma D1", 2026, 1, "Manha", "Ativa", 1, curso_id, matriz_id, turma_codigo),
        )
        turma_id = conn.execute(
            "SELECT id FROM turmas WHERE codigo = ?",
            (turma_codigo,),
        ).fetchone()["id"]

        conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?)",
            ("Aluno D1", aluno_email, main.hash_password("aluno123"), "aluno", "usuario"),
        )
        usuario_id = conn.execute(
            "SELECT id FROM usuarios WHERE email = ?",
            (aluno_email,),
        ).fetchone()["id"]

        conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status) VALUES (?, ?, ?, ?, ?, ?)",
            (usuario_id, "Aluno D1", f"{turma_codigo}.001", aluno_email, turma_id, "Ativo"),
        )
        aluno_id = conn.execute(
            "SELECT id FROM alunos WHERE usuario_id = ?",
            (usuario_id,),
        ).fetchone()["id"]

        conn.execute(
            """
            INSERT INTO atividades (grupo, nome, descricao, limite_horas, tipo_atividade, tem_limitacao)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("1 - Grupo D1", atividade_nome, "Fluxo legado D1", 40, "Acadêmica Complementar", 0),
        )
        atividade_id = conn.execute(
            "SELECT id FROM atividades WHERE nome = ?",
            (atividade_nome,),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO matrizes_atividades_itens (matriz_id, atividade_id) VALUES (?, ?)",
            (matriz_id, atividade_id),
        )
        conn.commit()

    return {
        "usuario_id": usuario_id,
        "aluno_id": aluno_id,
        "atividade_id": atividade_id,
        "atividade_nome": atividade_nome,
    }


def _assert_observacoes_d2_present_and_textual(items):
    assert items
    assert all((item["observacao_aluno"] or "").strip() for item in items)
    assert all((item["observacao_admin"] or "").strip() for item in items)
    # O diagnóstico da D1 expõe apenas texto orientativo; sem checklist/trava documental.
    assert all("documentos_json" not in item for item in items)


def test_phase_d1_helper_lists_expected_versioned_activities_for_ppa_t10(diagnostic_client):
    turma_id = _get_turma_id_by_code("PPA-T10")

    with main.app.app_context():
        conn = main.get_db_connection()
        payload = main.listar_atividades_versionadas_por_turma(conn, turma_id)

    assert payload["turma"]["codigo"] == "PPA-T10"
    assert payload["totais"]["geral"] == 28
    assert payload["totais"]["por_eixo"]["AAC"] == 28
    assert payload["totais"]["por_eixo"]["AEU"] == 0
    assert {item["norma"] for item in payload["atividades"]} == {"AAC-rev5"}
    assert {item["eixo"] for item in payload["atividades"]} == {"AAC"}

    nomes = {item["nome_exibivel"] for item in payload["atividades"]}
    assert "Visitas técnicas ou culturais" in nomes
    assert "Participação em projetos de extensão" in nomes
    assert "Trabalho voluntário em organizações do terceiro setor" in nomes
    assert "Horas de voo em simulador" in nomes
    assert "Participação em projetos de apoio institucional" not in nomes
    _assert_observacoes_d2_present_and_textual(payload["atividades"])

    with main.app.app_context():
        conn = main.get_db_connection()
        total = conn.execute("SELECT COUNT(*) AS c FROM atividade_versao").fetchone()["c"]
        docs_null = conn.execute(
            "SELECT COUNT(*) AS c FROM atividade_versao WHERE documentos_json IS NULL"
        ).fetchone()["c"]

    assert total == 59
    assert docs_null == 59


def test_phase_d1_helper_lists_expected_versioned_activities_for_ppa_t11(diagnostic_client):
    turma_id = _get_turma_id_by_code("PPA-T11")

    with main.app.app_context():
        conn = main.get_db_connection()
        payload = main.listar_atividades_versionadas_por_turma(conn, turma_id)

    assert payload["turma"]["codigo"] == "PPA-T11"
    assert payload["totais"]["geral"] == 31
    assert payload["totais"]["por_eixo"]["AAC"] == 26
    assert payload["totais"]["por_eixo"]["AEU"] == 5
    assert {item["norma"] for item in payload["atividades"]} == {"AAC-rev6", "AEU-rev1"}

    nomes = {item["nome_exibivel"] for item in payload["atividades"]}
    assert "Visitas técnicas ou culturais" in nomes
    assert "Horas de voo em simulador" not in nomes

    legacy_aeu = {
        item["atividade_id_legacy"]: item
        for item in payload["atividades"]
        if item["atividade_id_legacy"] in {27, 28, 29, 30, 31}
    }
    assert set(legacy_aeu) == {27, 28, 29, 30, 31}
    assert all(item["norma"] == "AEU-rev1" for item in legacy_aeu.values())
    assert all(item["eixo"] == "AEU" for item in legacy_aeu.values())
    _assert_observacoes_d2_present_and_textual(payload["atividades"])


def test_phase_d1_endpoint_supports_turma_and_matriz_queries(diagnostic_client):
    _set_admin_session(diagnostic_client)
    turma_id = _get_turma_id_by_code("PPA-T10")

    turma_response = diagnostic_client.get(
        f"/admin/diagnostico/atividades-versionadas?turma_id={turma_id}"
    )
    assert turma_response.status_code == 200
    turma_data = turma_response.get_json()
    assert turma_data["ok"] is True
    assert turma_data["consulta"]["modo"] == "turma"
    assert turma_data["turma"]["codigo"] == "PPA-T10"
    assert len(turma_data["por_eixo"]["AAC"]) == 28
    assert turma_data["por_eixo"]["AEU"] == []
    _assert_observacoes_d2_present_and_textual(turma_data["por_eixo"]["AAC"])
    assert "bloqueio_documental" not in turma_data
    assert "checklist_obrigatorio" not in turma_data

    matriz_id = turma_data["matriz"]["id"]
    matriz_response = diagnostic_client.get(
        f"/admin/diagnostico/atividades-versionadas?matriz_id={matriz_id}"
    )
    assert matriz_response.status_code == 200
    matriz_data = matriz_response.get_json()
    assert matriz_data["ok"] is True
    assert matriz_data["consulta"]["modo"] == "matriz"
    assert matriz_data["matriz"]["id"] == matriz_id
    assert matriz_data["turma"] is None
    assert any(turma["codigo"] == "PPA-T10" for turma in matriz_data["turmas_vinculadas"])
    _assert_observacoes_d2_present_and_textual(matriz_data["atividades"])


def test_phase_d1_legacy_flow_keeps_using_atividade_id(isolated_legacy_client):
    seed = _seed_legacy_flow_context()

    with isolated_legacy_client.session_transaction() as sess:
        sess["user_id"] = seed["usuario_id"]
        sess["user_type"] = "aluno"
        sess["user_name"] = "Aluno D1"

    response = isolated_legacy_client.post(
        "/aluno/nova-requisicao",
        data={
            "atividade_id": str(seed["atividade_id"]),
            "nome_evento": "Evento D1 Legado",
            "data_evento": "2026-05-10",
            "horas_solicitadas": "6",
            "observacao": "Fluxo legado preservado",
        },
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert "não está disponível para a matriz da sua turma" in response.get_data(as_text=True)

    with main.app.app_context():
        conn = main.get_db_connection()
        req = conn.execute(
            """
            SELECT atividade_id, atividade_versao_id, status
              FROM requisicoes
             WHERE aluno_id = ? AND nome_evento = ?
             ORDER BY id DESC
             LIMIT 1
            """,
            (seed["aluno_id"], "Evento D1 Legado"),
        ).fetchone()

    assert req is None


def test_phase_d3_view_requires_admin(diagnostic_client):
    response = diagnostic_client.get(
        "/admin/diagnostico/atividades-versionadas/view?turma_codigo=PPA-T10",
        follow_redirects=False,
    )
    assert response.status_code in (301, 302, 303)
    assert "/login" in (response.headers.get("Location") or "")


def test_phase_d3_view_not_in_main_menu(diagnostic_client):
    _set_admin_session(diagnostic_client)
    response = diagnostic_client.get("/admin/dashboard")
    assert response.status_code == 200

    html = response.get_data(as_text=True)
    assert "/admin/diagnostico/atividades-versionadas/view" not in html


def test_phase_d3_view_renders_ppa_t10_with_observacoes(diagnostic_client):
    _set_admin_session(diagnostic_client)
    response = diagnostic_client.get(
        "/admin/diagnostico/atividades-versionadas/view?turma_codigo=PPA-T10"
    )
    assert response.status_code == 200

    html = response.get_data(as_text=True)
    assert "Diagnóstico Administrativo - Atividades Versionadas" in html
    assert 'data-total-geral="28"' in html
    assert 'data-total-aac="28"' in html
    assert 'data-total-aeu="0"' in html
    assert "AAC-rev5 (AAC)" in html
    assert "Visitas técnicas ou culturais" in html
    assert "Participação em projetos de extensão" in html
    assert (
        "Recomenda-se certificado de conclusão contendo identificação do curso, instituição, data de conclusão e carga horária."
        in html
    )
    assert (
        "Validar se o curso é de curta duração e ligado à área da aviação, evitando dupla contagem com formação profissional quando for a mesma evidência."
        in html
    )
    assert "Sem checklist obrigatório e sem bloqueio documental nesta tela." in html
    assert (
        "Os campos estruturados de carga/limite ainda estão em conferência. Nesta tela diagnóstica, as observações textuais são a referência editorial; não há uso operacional automático."
        in html
    )
    assert "CH/evento estruturada" in html
    assert "Limite semestre estruturado" in html
    assert "Limite total estruturado" in html
    assert ">40h<" in html
    assert ">20h<" in html
    assert ">100h<" in html
    assert "40.0" not in html
    assert "20.0" not in html
    assert "100.0" not in html
    assert "documentos_json" not in html
    assert "checklist_obrigatorio" not in html
    assert "bloqueio_documental" not in html


def test_phase_d3_view_renders_ppa_t11_split_aac_aeu(diagnostic_client):
    _set_admin_session(diagnostic_client)
    response = diagnostic_client.get(
        "/admin/diagnostico/atividades-versionadas/view?turma_codigo=PPA-T11"
    )
    assert response.status_code == 200

    html = response.get_data(as_text=True)
    assert 'data-total-geral="31"' in html
    assert 'data-total-aac="26"' in html
    assert 'data-total-aeu="5"' in html
    assert "AAC - 26 atividade(s)" in html
    assert "AEU - 5 atividade(s)" in html
    assert "AAC-rev6 (AAC)" in html
    assert "AEU-rev1 (AEU)" in html
    assert "Visitas técnicas ou culturais" in html
    assert "Horas de voo em simulador" not in html
    assert "40.0" not in html
    assert "20.0" not in html
