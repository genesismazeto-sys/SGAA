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


@pytest.fixture()
def diagnostic_database(tmp_path):
    with isolated_versioned_app_env(tmp_path, "resolver_diagnostic.db") as env:
        yield env["db_path"]


@pytest.fixture()
def isolated_legacy_client(tmp_path):
    app = main.app
    temp_database = tmp_path / "resolver_legacy_flow.db"
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


def _get_turma_id_by_code(codigo: str) -> int:
    with main.app.app_context():
        conn = main.get_db_connection()
        row = conn.execute("SELECT id FROM turmas WHERE codigo = ?", (codigo,)).fetchone()
    assert row is not None, f"Turma {codigo} não encontrada."
    return row["id"]


def _seed_legacy_flow_context():
    token = uuid.uuid4().hex[:8]
    matricula = f"D6R{token.upper()}"
    with main.app.app_context():
        conn = main.get_db_connection()
        user_email = f"resolver.{token}@example.com"

        conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo) VALUES (?, ?, ?, ?)",
            (f"Aluno Resolver {token}", user_email, "hash", "aluno"),
        )
        usuario_id = conn.execute(
            "SELECT id FROM usuarios WHERE email = ?",
            (user_email,),
        ).fetchone()["id"]

        conn.execute(
            """
            INSERT INTO alunos (nome, matricula, email, turma, usuario_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (f"Aluno Resolver {token}", matricula, user_email, "PPA-T11", usuario_id),
        )
        aluno_id = conn.execute(
            "SELECT id FROM alunos WHERE matricula = ?",
            (matricula,),
        ).fetchone()["id"]

        atividade_nome = f"Atividade Resolver {token}"
        conn.execute(
            """
            INSERT INTO atividades (grupo, nome, descricao, limite_horas, tipo_atividade, tem_limitacao)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("1 - Grupo Resolver", atividade_nome, "Fluxo legado resolver", 40, "Acadêmica Complementar", 0),
        )
        atividade_id = conn.execute(
            "SELECT id FROM atividades WHERE nome = ?",
            (atividade_nome,),
        ).fetchone()["id"]
        conn.commit()

    return {
        "usuario_id": usuario_id,
        "aluno_id": aluno_id,
        "atividade_id": atividade_id,
    }


def test_resolver_ppa_t10_strict_and_permissive(diagnostic_database):
    turma_id = _get_turma_id_by_code("PPA-T10")

    with main.app.app_context():
        conn = main.get_db_connection()

        r1 = main.resolver_versao(
            conn,
            turma_id=turma_id,
            atividade_id_legacy=1,
            strict_legacy_scope=True,
        )
        assert r1["status"] == "resolved"
        assert r1["codigo_normativo"] == "AAC-rev5"
        assert r1["eixo"] == "AAC"
        assert r1["legacy_scope_ok"] is True

        r6_strict = main.resolver_versao(
            conn,
            turma_id=turma_id,
            atividade_id_legacy=6,
            strict_legacy_scope=True,
        )
        assert r6_strict["status"] == "legacy_activity_not_in_matrix"
        assert r6_strict["legacy_scope_ok"] is False

        r6_perm = main.resolver_versao(
            conn,
            turma_id=turma_id,
            atividade_id_legacy=6,
            strict_legacy_scope=False,
        )
        assert r6_perm["status"] == "resolved"
        assert r6_perm["codigo_normativo"] == "AAC-rev5"
        assert r6_perm["legacy_scope_ok"] is False
        assert "legacy_activity_outside_matrix_scope" in r6_perm["warnings"]

        r8 = main.resolver_versao(
            conn,
            turma_id=turma_id,
            atividade_id_legacy=8,
            strict_legacy_scope=True,
        )
        assert r8["status"] == "base_without_version_for_matrix"

        r27_strict = main.resolver_versao(
            conn,
            turma_id=turma_id,
            atividade_id_legacy=27,
            strict_legacy_scope=True,
        )
        assert r27_strict["status"] == "legacy_activity_not_in_matrix"

        r27_perm = main.resolver_versao(
            conn,
            turma_id=turma_id,
            atividade_id_legacy=27,
            strict_legacy_scope=False,
        )
        assert r27_perm["status"] == "resolved"
        assert r27_perm["codigo_normativo"] == "AAC-rev5"
        assert r27_perm["legacy_scope_ok"] is False
        assert "legacy_activity_outside_matrix_scope" in r27_perm["warnings"]

        r28_strict = main.resolver_versao(
            conn,
            turma_id=turma_id,
            atividade_id_legacy=28,
            strict_legacy_scope=True,
        )
        assert r28_strict["status"] == "legacy_activity_not_in_matrix"

        r28_perm = main.resolver_versao(
            conn,
            turma_id=turma_id,
            atividade_id_legacy=28,
            strict_legacy_scope=False,
        )
        assert r28_perm["status"] == "resolved"
        assert r28_perm["codigo_normativo"] == "AAC-rev5"
        assert r28_perm["legacy_scope_ok"] is False
        assert "legacy_activity_outside_matrix_scope" in r28_perm["warnings"]


def test_resolver_ppa_t11_strict_and_permissive(diagnostic_database):
    turma_id = _get_turma_id_by_code("PPA-T11")

    with main.app.app_context():
        conn = main.get_db_connection()

        r1 = main.resolver_versao(
            conn,
            turma_id=turma_id,
            atividade_id_legacy=1,
            strict_legacy_scope=True,
        )
        assert r1["status"] == "resolved"
        assert r1["codigo_normativo"] == "AAC-rev6"
        assert r1["eixo"] == "AAC"

        r6_strict = main.resolver_versao(
            conn,
            turma_id=turma_id,
            atividade_id_legacy=6,
            strict_legacy_scope=True,
        )
        assert r6_strict["status"] == "legacy_activity_not_in_matrix"

        r6_perm = main.resolver_versao(
            conn,
            turma_id=turma_id,
            atividade_id_legacy=6,
            strict_legacy_scope=False,
        )
        assert r6_perm["status"] == "resolved"
        assert r6_perm["codigo_normativo"] == "AAC-rev6"
        assert r6_perm["legacy_scope_ok"] is False
        assert "legacy_activity_outside_matrix_scope" in r6_perm["warnings"]

        r8 = main.resolver_versao(
            conn,
            turma_id=turma_id,
            atividade_id_legacy=8,
            strict_legacy_scope=True,
        )
        assert r8["status"] == "resolved"
        assert r8["codigo_normativo"] == "AAC-rev6"
        assert r8["eixo"] == "AAC"

        for atividade_legacy in (27, 28, 29, 30, 31):
            resolved = main.resolver_versao(
                conn,
                turma_id=turma_id,
                atividade_id_legacy=atividade_legacy,
                strict_legacy_scope=True,
            )
            assert resolved["status"] == "resolved"
            assert resolved["codigo_normativo"] == "AEU-rev1"
            assert resolved["eixo"] == "AEU"


def test_resolver_reports_missing_map_and_ambiguous_candidates(diagnostic_database):
    turma_id = _get_turma_id_by_code("PPA-T11")

    with main.app.app_context():
        conn = main.get_db_connection()
        turma = conn.execute(
            "SELECT id, curso_id, matriz_id FROM turmas WHERE id = ?",
            (turma_id,),
        ).fetchone()
        matriz = main.get_effective_matriz_for_turma(
            conn,
            turma["curso_id"],
            turma["matriz_id"],
        )
        matriz_id = matriz["id"]

        not_mapped = main.resolver_versao_por_matriz(
            conn,
            matriz_id=matriz_id,
            atividade_id_legacy=999999,
            strict_legacy_scope=False,
        )
        assert not_mapped["status"] == "legacy_activity_without_base_map"
        assert not_mapped["legacy_scope_ok"] is False

        base_id = conn.execute(
            """
            SELECT atividade_base_id
              FROM atividade_legacy_map
             WHERE atividade_id_legacy = 1
            """
        ).fetchone()["atividade_base_id"]

        novo_codigo = f"AAC-rev6-amb-{uuid.uuid4().hex[:8]}"
        conn.execute(
            """
            INSERT INTO norma_atividade (codigo, eixo, revisao, nome, status)
            VALUES (?, 'AAC', 'amb', ?, 'ativa')
            """,
            (novo_codigo, f"Norma ambígua {novo_codigo}"),
        )
        norma_id = conn.execute(
            "SELECT id FROM norma_atividade WHERE codigo = ?",
            (novo_codigo,),
        ).fetchone()["id"]
        conn.execute(
            """
            INSERT INTO matriz_norma (matriz_id, norma_id)
            VALUES (?, ?)
            """,
            (matriz_id, norma_id),
        )
        conn.execute(
            """
            INSERT INTO atividade_versao
            (
                atividade_base_id, norma_id, codigo_normativo, eixo,
                observacao_aluno, observacao_admin, status
            )
            VALUES (?, ?, ?, 'AAC', ?, ?, 'ativa')
            """,
            (
                base_id,
                norma_id,
                novo_codigo,
                "Candidata ambígua aluno",
                "Candidata ambígua admin",
            ),
        )
        nova_versao_id = conn.execute(
            """
            SELECT id
              FROM atividade_versao
             WHERE atividade_base_id = ? AND norma_id = ?
            """,
            (base_id, norma_id),
        ).fetchone()["id"]
        conn.execute(
            """
            INSERT INTO matriz_atividade_versao_item (matriz_id, atividade_versao_id)
            VALUES (?, ?)
            """,
            (matriz_id, nova_versao_id),
        )
        conn.commit()

        ambiguous = main.resolver_versao_por_matriz(
            conn,
            matriz_id=matriz_id,
            atividade_id_legacy=1,
            strict_legacy_scope=True,
        )
        assert ambiguous["status"] == "ambiguous_version"
        assert ambiguous["atividade_base_id"] == base_id
        assert "multiple_valid_candidates" in ambiguous["warnings"]


def test_resolver_reports_matrix_without_norma_and_version_inactive(diagnostic_database):
    turma_id = _get_turma_id_by_code("PPA-T11")

    with main.app.app_context():
        conn = main.get_db_connection()
        turma = conn.execute(
            "SELECT curso_id FROM turmas WHERE id = ?",
            (turma_id,),
        ).fetchone()
        curso_id = turma["curso_id"]

        conn.execute(
            """
            INSERT INTO matrizes_atividades (curso_id, nome, versao, status)
            VALUES (?, ?, ?, ?)
            """,
            (curso_id, "Matriz sem norma resolver", "resolver-no-norma", "rascunho"),
        )
        matriz_sem_norma = conn.execute(
            """
            SELECT id
              FROM matrizes_atividades
             WHERE nome = ? AND versao = ?
            """,
            ("Matriz sem norma resolver", "resolver-no-norma"),
        ).fetchone()["id"]

        conn.execute(
            "INSERT INTO matrizes_atividades_itens (matriz_id, atividade_id) VALUES (?, ?)",
            (matriz_sem_norma, 1),
        )
        conn.execute(
            "INSERT INTO matriz_atividade_versao_item (matriz_id, atividade_versao_id) VALUES (?, ?)",
            (matriz_sem_norma, 2),
        )
        conn.commit()

        missing_norma = main.resolver_versao_por_matriz(
            conn,
            matriz_id=matriz_sem_norma,
            atividade_id_legacy=1,
            strict_legacy_scope=True,
        )
        assert missing_norma["status"] == "matrix_without_norma"

        conn.execute(
            """
            INSERT INTO matrizes_atividades (curso_id, nome, versao, status)
            VALUES (?, ?, ?, ?)
            """,
            (curso_id, "Matriz inativa resolver", "resolver-inativa", "rascunho"),
        )
        matriz_inativa = conn.execute(
            """
            SELECT id
              FROM matrizes_atividades
             WHERE nome = ? AND versao = ?
            """,
            ("Matriz inativa resolver", "resolver-inativa"),
        ).fetchone()["id"]

        novo_codigo = f"AAC-rev6-inativa-{uuid.uuid4().hex[:8]}"
        conn.execute(
            """
            INSERT INTO norma_atividade (codigo, eixo, revisao, nome, status)
            VALUES (?, 'AAC', 'inativa', ?, 'ativa')
            """,
            (novo_codigo, f"Norma inativa {novo_codigo}"),
        )
        norma_id = conn.execute(
            "SELECT id FROM norma_atividade WHERE codigo = ?",
            (novo_codigo,),
        ).fetchone()["id"]

        base_id = conn.execute(
            "SELECT atividade_base_id FROM atividade_legacy_map WHERE atividade_id_legacy = 1"
        ).fetchone()["atividade_base_id"]

        conn.execute(
            """
            INSERT INTO atividade_versao
            (
                atividade_base_id, norma_id, codigo_normativo, eixo,
                observacao_aluno, observacao_admin, status
            )
            VALUES (?, ?, ?, 'AAC', ?, ?, 'inativa')
            """,
            (
                base_id,
                norma_id,
                novo_codigo,
                "Versão inativa aluno",
                "Versão inativa admin",
            ),
        )
        versao_inativa_id = conn.execute(
            """
            SELECT id
              FROM atividade_versao
             WHERE atividade_base_id = ? AND norma_id = ?
            """,
            (base_id, norma_id),
        ).fetchone()["id"]

        conn.execute(
            "INSERT INTO matriz_norma (matriz_id, norma_id) VALUES (?, ?)",
            (matriz_inativa, norma_id),
        )
        conn.execute(
            "INSERT INTO matrizes_atividades_itens (matriz_id, atividade_id) VALUES (?, ?)",
            (matriz_inativa, 1),
        )
        conn.execute(
            "INSERT INTO matriz_atividade_versao_item (matriz_id, atividade_versao_id) VALUES (?, ?)",
            (matriz_inativa, versao_inativa_id),
        )
        conn.commit()

        inactive = main.resolver_versao_por_matriz(
            conn,
            matriz_id=matriz_inativa,
            atividade_id_legacy=1,
            strict_legacy_scope=True,
        )
        assert inactive["status"] == "version_inactive"


def test_resolver_is_read_only_and_output_has_no_documentos_json(diagnostic_database):
    turma_id = _get_turma_id_by_code("PPA-T11")

    with main.app.app_context():
        conn = main.get_db_connection()
        aluno_row = conn.execute(
            """
            SELECT a.id AS aluno_id
              FROM alunos a
              JOIN turmas t ON t.id = a.turma_id
             WHERE t.id = ?
             ORDER BY a.id
             LIMIT 1
            """,
            (turma_id,),
        ).fetchone()
        assert aluno_row is not None

        before_changes = conn.total_changes
        before_requisicoes = conn.execute("SELECT COUNT(*) AS c FROM requisicoes").fetchone()["c"]
        before_requisicoes_versionadas = conn.execute(
            "SELECT COUNT(*) AS c FROM requisicoes WHERE atividade_versao_id IS NOT NULL"
        ).fetchone()["c"]

        resolved = main.resolver_versao(
            conn,
            turma_id=turma_id,
            atividade_id_legacy=1,
            strict_legacy_scope=True,
        )
        resolved_aluno = main.resolver_versao_por_aluno(
            conn,
            aluno_id=aluno_row["aluno_id"],
            atividade_id_legacy=1,
            strict_legacy_scope=True,
        )

        after_requisicoes = conn.execute("SELECT COUNT(*) AS c FROM requisicoes").fetchone()["c"]
        after_requisicoes_versionadas = conn.execute(
            "SELECT COUNT(*) AS c FROM requisicoes WHERE atividade_versao_id IS NOT NULL"
        ).fetchone()["c"]
        after_changes = conn.total_changes

    assert resolved["status"] == "resolved"
    assert resolved_aluno["status"] == "resolved"
    assert "documentos_json" not in resolved
    assert "documentos_json" not in resolved_aluno
    assert after_changes == before_changes
    assert after_requisicoes == before_requisicoes
    assert after_requisicoes_versionadas == before_requisicoes_versionadas


def test_resolver_legacy_flow_still_uses_atividade_id(isolated_legacy_client):
    seed = _seed_legacy_flow_context()

    with isolated_legacy_client.session_transaction() as sess:
        sess["user_id"] = seed["usuario_id"]
        sess["user_type"] = "aluno"
        sess["user_name"] = "Aluno Resolver"

    response = isolated_legacy_client.post(
        "/aluno/nova-requisicao",
        data={
            "atividade_id": str(seed["atividade_id"]),
            "nome_evento": "Evento Resolver Legado",
            "data_evento": "2026-06-10",
            "horas_solicitadas": "4",
            "observacao": "Fluxo legado mantido",
        },
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)

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
            (seed["aluno_id"], "Evento Resolver Legado"),
        ).fetchone()

    assert req is not None
    assert req["atividade_id"] == seed["atividade_id"]
    assert req["atividade_versao_id"] is None
    assert (req["status"] or "").lower() != "indeferido"
