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


SIMPLE_EXPECTED = {
    3: 2.0,
    4: 2.0,
    17: 2.0,
    18: 2.0,
    9: 4.0,
    10: 4.0,
    12: 5.0,
    14: 5.0,
    41: 5.0,
    42: 5.0,
    47: 5.0,
    25: 10.0,
    26: 10.0,
    37: 10.0,
    38: 10.0,
    46: 10.0,
    5: 20.0,
    6: 20.0,
    7: 20.0,
    8: 20.0,
    39: 20.0,
    40: 20.0,
}

BLOCKED_IDS = {11, 13, 27, 28, 35, 36, 43, 44, 45, 48, 52, 54, 56, 57, 58, 59}


@pytest.fixture()
def diagnostic_database(tmp_path):
    with isolated_versioned_app_env(tmp_path, "d5_structured_hours.db") as env:
        yield env["db_path"]


@pytest.fixture()
def isolated_legacy_client(tmp_path):
    app = main.app
    temp_database = tmp_path / "phase_d5_legacy_flow.db"
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
    curso_codigo = f"D5-{suffix}"
    turma_codigo = f"{curso_codigo}-T01"
    aluno_email = f"d5.aluno.{suffix}@teste.local"
    atividade_nome = f"Atividade D5 {suffix}"

    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "INSERT INTO cursos (nome, codigo, duracao_periodos, status) VALUES (?, ?, ?, ?)",
            ("Curso D5", curso_codigo, 8, "ativo"),
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
            (curso_id, f"Matriz D5 {suffix}", "1", "vigente", "2026-01-01"),
        ).fetchone()["id"]

        conn.execute(
            """
            INSERT INTO turmas (nome, ano, semestre, turno, status, numero, curso_id, matriz_id, codigo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("Turma D5", 2026, 1, "Manha", "Ativa", 1, curso_id, matriz_id, turma_codigo),
        )
        turma_id = conn.execute(
            "SELECT id FROM turmas WHERE codigo = ?",
            (turma_codigo,),
        ).fetchone()["id"]

        conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?)",
            ("Aluno D5", aluno_email, main.hash_password("aluno123"), "aluno", "usuario"),
        )
        usuario_id = conn.execute(
            "SELECT id FROM usuarios WHERE email = ?",
            (aluno_email,),
        ).fetchone()["id"]

        conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status) VALUES (?, ?, ?, ?, ?, ?)",
            (usuario_id, "Aluno D5", f"{turma_codigo}.001", aluno_email, turma_id, "Ativo"),
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
            ("1 - Grupo D5", atividade_nome, "Fluxo legado D5", 40, "Acadêmica Complementar", 0),
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
    }


def test_phase_d5_structured_hours_fill_only_simple_ids(diagnostic_database):
    with main.app.app_context():
        conn = main.get_db_connection()
        rows = conn.execute(
            "SELECT id, ch_por_evento FROM atividade_versao ORDER BY id"
        ).fetchall()

    rows_by_id = {row["id"]: row["ch_por_evento"] for row in rows}

    assert len(rows_by_id) == 59
    assert len(SIMPLE_EXPECTED) == 22
    for atividade_versao_id, expected in SIMPLE_EXPECTED.items():
        assert rows_by_id[atividade_versao_id] == expected
    for atividade_versao_id in BLOCKED_IDS:
        assert rows_by_id[atividade_versao_id] is None


def test_phase_d5_structured_hours_keep_documentos_textual_only(diagnostic_database):
    turma_id = _get_turma_id_by_code("PPA-T11")

    with main.app.app_context():
        conn = main.get_db_connection()
        total = conn.execute("SELECT COUNT(*) FROM atividade_versao").fetchone()[0]
        docs_null = conn.execute(
            "SELECT COUNT(*) FROM atividade_versao WHERE documentos_json IS NULL"
        ).fetchone()[0]
        obs_aluno = conn.execute(
            "SELECT COUNT(*) FROM atividade_versao WHERE TRIM(COALESCE(observacao_aluno, '')) <> ''"
        ).fetchone()[0]
        obs_admin = conn.execute(
            "SELECT COUNT(*) FROM atividade_versao WHERE TRIM(COALESCE(observacao_admin, '')) <> ''"
        ).fetchone()[0]
        payload = main.listar_atividades_versionadas_por_turma(conn, turma_id)

    assert total == 59
    assert docs_null == 59
    assert obs_aluno == 59
    assert obs_admin == 59
    assert payload["totais"]["geral"] == 31
    assert all("documentos_json" not in item for item in payload["atividades"])


def test_phase_d5_3_puntual_observation_and_limit_sanitization(diagnostic_database):
    expected_texts = {
        48: {
            "observacao_aluno": "5h por filme/peça, limite de 50h por semestre. Recomenda-se bilhete/ingresso e relatório conforme modelo da atividade, com mínimo de 2 páginas.",
            "observacao_admin": "Aplicar 5h por filme/peça, até o limite de 50h por semestre. Validar relatório no modelo da atividade, com mínimo de 2 páginas, além do ingresso/comprovação.",
        },
        52: {
            "observacao_aluno": "No regime histórico AAC-rev5, esta atividade é contabilizada como AAC. Limite de 40h por semestre. Recomenda-se declaração ou certificado contendo nome do aluno, identificação do projeto, período e carga horária.",
            "observacao_admin": "Manter enquadramento histórico como AAC para matriz antiga. Aplicar limite de 40h por semestre. Validar comprovação do projeto e evitar migração automática para AEU neste regime.",
        },
        54: {
            "observacao_aluno": "No regime histórico AAC-rev5, esta atividade é contabilizada como AAC. Limite de 40h por semestre. Recomenda-se declaração da entidade contendo período, atividades desenvolvidas e carga horária.",
            "observacao_admin": "Manter enquadramento histórico como AAC para matriz antiga. Aplicar limite de 40h por semestre. Validar declaração da entidade, atividades desenvolvidas e carga horária comprovada.",
        },
    }

    with main.app.app_context():
        conn = main.get_db_connection()
        rows = conn.execute(
            """
            SELECT id, ch_por_evento, limite_total, observacao_aluno, observacao_admin
              FROM atividade_versao
             WHERE id IN (48, 52, 54, 59)
             ORDER BY id
            """
        ).fetchall()
        qmark_aluno = conn.execute(
            "SELECT COUNT(*) FROM atividade_versao WHERE observacao_aluno LIKE '%?%'"
        ).fetchone()[0]
        qmark_admin = conn.execute(
            "SELECT COUNT(*) FROM atividade_versao WHERE observacao_admin LIKE '%?%'"
        ).fetchone()[0]

    rows_by_id = {row["id"]: row for row in rows}

    for atividade_versao_id, expected in expected_texts.items():
        assert rows_by_id[atividade_versao_id]["observacao_aluno"] == expected["observacao_aluno"]
        assert rows_by_id[atividade_versao_id]["observacao_admin"] == expected["observacao_admin"]

    assert rows_by_id[59]["limite_total"] == 40
    assert rows_by_id[59]["ch_por_evento"] is None
    assert qmark_aluno == 0
    assert qmark_admin == 0


def test_phase_d5_legacy_flow_still_uses_atividade_id(isolated_legacy_client):
    seed = _seed_legacy_flow_context()

    with isolated_legacy_client.session_transaction() as sess:
        sess["user_id"] = seed["usuario_id"]
        sess["user_type"] = "aluno"
        sess["user_name"] = "Aluno D5"

    response = isolated_legacy_client.post(
        "/aluno/nova-requisicao",
        data={
            "atividade_id": str(seed["atividade_id"]),
            "nome_evento": "Evento D5 Legado",
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
            (seed["aluno_id"], "Evento D5 Legado"),
        ).fetchone()

    assert req is None
