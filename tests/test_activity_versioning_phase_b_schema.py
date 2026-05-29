import os
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest


BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main
from app import db as app_db_module


def _table_exists(conn, table_name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _table_columns(conn, table_name: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


@contextmanager
def _temporary_database_binding(tmp_path, filename: str):
    app = main.app
    temp_database = (tmp_path / filename).resolve()

    original_database = main.DATABASE
    original_env_database = os.environ.get("APP_DATABASE")
    original_config_database_path = app.config.get("DATABASE_PATH")
    original_testing = app.config.get("TESTING")
    original_app_db_database = app_db_module.DATABASE

    try:
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

        yield temp_database
    finally:
        with app.app_context():
            try:
                main.close_db_connection(None)
            except Exception:
                pass

        if original_env_database is None:
            os.environ.pop("APP_DATABASE", None)
        else:
            os.environ["APP_DATABASE"] = original_env_database
        main.DATABASE = original_database
        app_db_module.DATABASE = original_app_db_database
        app.config["DATABASE_PATH"] = original_config_database_path
        app.config["TESTING"] = original_testing


def _seed_normas_basicas(conn) -> dict[str, int]:
    conn.executemany(
        """
        INSERT INTO norma_atividade (codigo, eixo, revisao, nome, status)
        VALUES (?, ?, ?, ?, 'ativa')
        """,
        (
            ("AAC-rev5", "AAC", "rev5", "AAC regulamento antigo"),
            ("AAC-rev6", "AAC", "rev6", "AAC regulamento novo"),
            ("AEU-rev1", "AEU", "rev1", "AEU versão inicial"),
        ),
    )
    return {
        row["codigo"]: row["id"]
        for row in conn.execute("SELECT id, codigo FROM norma_atividade").fetchall()
    }


def _insert_atividade_base(conn, nome_conceito: str, descricao: str = "Base de atividade para testes") -> int:
    return conn.execute(
        "INSERT INTO atividade_base (nome_conceito, descricao) VALUES (?, ?)",
        (nome_conceito, descricao),
    ).lastrowid


def _insert_atividade_versao(
    conn,
    *,
    atividade_base_id: int,
    norma_id: int,
    codigo_normativo: str,
    eixo: str,
    grupo: str = "1 - Grupo teste",
    status: str = "ativa",
    versao_anterior_id: int | None = None,
) -> int:
    return conn.execute(
        """
        INSERT INTO atividade_versao (
            atividade_base_id, norma_id, codigo_normativo, eixo, grupo, status, versao_anterior_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (atividade_base_id, norma_id, codigo_normativo, eixo, grupo, status, versao_anterior_id),
    ).lastrowid


def _insert_matriz_basica(conn, nome: str = "Matriz Fase B.1", versao: str = "2026.1") -> int:
    curso_id = conn.execute("SELECT id FROM cursos WHERE codigo = 'GERAL'").fetchone()[0]
    return conn.execute(
        """
        INSERT INTO matrizes_atividades (curso_id, nome, versao, status)
        VALUES (?, ?, ?, 'ativa')
        """,
        (curso_id, nome, versao),
    ).lastrowid


def test_phase_b_schema_creates_additive_tables_and_columns(tmp_path):
    with _temporary_database_binding(tmp_path, "phase_b_additive_schema.db"):
        with main.app.app_context():
            main.init_db()
            conn = main.get_db_connection()

            required_tables = {
                "atividade_base",
                "norma_atividade",
                "atividade_versao",
                "atividade_transicao",
                "matriz_norma",
                "matriz_atividade_versao_item",
                "atividade_legacy_map",
            }
            for table_name in required_tables:
                assert _table_exists(conn, table_name), f"Tabela ausente: {table_name}"

            requisicoes_columns = _table_columns(conn, "requisicoes")
            assert {
                "atividade_versao_id",
                "regra_snapshot_json",
                "codigo_normativo_snapshot",
            }.issubset(requisicoes_columns)

            # Fluxo legado deve permanecer: tabela antiga de vínculo continua disponível.
            assert _table_exists(conn, "matrizes_atividades_itens")


def test_phase_b_allows_normas_and_versions_with_constraints(tmp_path):
    with _temporary_database_binding(tmp_path, "phase_b_normas_e_versoes.db"):
        with main.app.app_context():
            main.init_db()
            conn = main.get_db_connection()

            norma_ids = _seed_normas_basicas(conn)
            cur = conn.execute(
                "INSERT INTO atividade_base (nome_conceito, descricao) VALUES (?, ?)",
                ("Palestra acadêmica externa", "Base de atividade para testes"),
            )
            base_id = cur.lastrowid

            conn.execute(
                """
                INSERT INTO atividade_versao (
                    atividade_base_id, norma_id, codigo_normativo, eixo, grupo, status
                ) VALUES (?, ?, ?, ?, ?, 'ativa')
                """,
                (base_id, norma_ids["AAC-rev5"], "AAC-rev5", "AAC", "1 - Grupo teste"),
            )
            conn.execute(
                """
                INSERT INTO atividade_versao (
                    atividade_base_id, norma_id, codigo_normativo, eixo, grupo, status
                ) VALUES (?, ?, ?, ?, ?, 'ativa')
                """,
                (base_id, norma_ids["AAC-rev6"], "AAC-rev6", "AAC", "1 - Grupo teste"),
            )

            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO atividade_versao (
                        atividade_base_id, norma_id, codigo_normativo, eixo, grupo, status
                    ) VALUES (?, ?, ?, ?, ?, 'ativa')
                    """,
                    (base_id, norma_ids["AAC-rev6"], "AAC-rev6", "AAC", "1 - Grupo teste"),
                )

            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO atividade_versao (
                        atividade_base_id, norma_id, codigo_normativo, eixo, grupo, status
                    ) VALUES (?, ?, ?, ?, ?, 'ativa')
                    """,
                    (base_id, norma_ids["AEU-rev1"], "AEU-rev1", "AAC", "0 - Grupo teste"),
                )


def test_phase_b_requires_justification_for_aac_para_aeu_transition(tmp_path):
    with _temporary_database_binding(tmp_path, "phase_b_transicoes.db"):
        with main.app.app_context():
            main.init_db()
            conn = main.get_db_connection()

            norma_ids = _seed_normas_basicas(conn)
            base_id = conn.execute(
                "INSERT INTO atividade_base (nome_conceito, descricao) VALUES (?, ?)",
                ("Projetos de extensão", "Base para transição histórica AAC -> AEU"),
            ).lastrowid

            from_id = conn.execute(
                """
                INSERT INTO atividade_versao (
                    atividade_base_id, norma_id, codigo_normativo, eixo, grupo, status
                ) VALUES (?, ?, ?, ?, ?, 'ativa')
                """,
                (base_id, norma_ids["AAC-rev5"], "AAC-rev5", "AAC", "2 - Extensão antiga"),
            ).lastrowid
            to_id = conn.execute(
                """
                INSERT INTO atividade_versao (
                    atividade_base_id, norma_id, codigo_normativo, eixo, grupo, status
                ) VALUES (?, ?, ?, ?, ?, 'ativa')
                """,
                (base_id, norma_ids["AEU-rev1"], "AEU-rev1", "AEU", "0 - Extensão universitária"),
            ).lastrowid

            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO atividade_transicao (
                        from_atividade_versao_id, to_atividade_versao_id, tipo_transicao
                    ) VALUES (?, ?, ?)
                    """,
                    (from_id, to_id, "aac_para_aeu"),
                )

            conn.execute(
                """
                INSERT INTO atividade_transicao (
                    from_atividade_versao_id, to_atividade_versao_id, tipo_transicao, justificativa
                ) VALUES (?, ?, ?, ?)
                """,
                (from_id, to_id, "aac_para_aeu", "Separação normativa entre AAC e AEU"),
            )
            total = conn.execute("SELECT COUNT(*) FROM atividade_transicao").fetchone()[0]
            assert total == 1


def test_phase_b_keeps_legacy_requisicoes_flow_and_nullable_snapshot_fields(tmp_path):
    with _temporary_database_binding(tmp_path, "phase_b_requisicoes_legacy.db"):
        with main.app.app_context():
            main.init_db()
            conn = main.get_db_connection()

            usuario_id = conn.execute(
                "INSERT INTO usuarios (nome, email, senha, tipo) VALUES (?, ?, ?, ?)",
                ("Aluno Teste", "aluno.phaseb@teste.local", "hash", "aluno"),
            ).lastrowid
            aluno_id = conn.execute(
                "INSERT INTO alunos (usuario_id, nome, matricula, email) VALUES (?, ?, ?, ?)",
                (usuario_id, "Aluno Teste", "PHASEB-001", "aluno.phaseb@teste.local"),
            ).lastrowid
            atividade_id = conn.execute(
                """
                INSERT INTO atividades (grupo, nome, descricao, limite_horas, tipo_atividade, tem_limitacao, tipo_limitacao, limite_horas_total, limite_horas_semestral, documentos_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "1 - Grupo teste",
                    "Atividade legado sem versionamento",
                    "Fluxo legado",
                    5,
                    "Acadêmica Complementar",
                    0,
                    "total",
                    None,
                    None,
                    None,
                ),
            ).lastrowid

            req_id = conn.execute(
                """
                INSERT INTO requisicoes (
                    aluno_id, atividade_id, data_solicitacao, data_evento, horas_solicitadas, nome_evento, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (aluno_id, atividade_id, "2026-05-22 10:00:00", "2026-05-22", 2.0, "Evento legado", "Pendente"),
            ).lastrowid
            conn.commit()

            row = conn.execute(
                """
                SELECT atividade_versao_id, regra_snapshot_json, codigo_normativo_snapshot
                  FROM requisicoes
                 WHERE id = ?
                """,
                (req_id,),
            ).fetchone()
            assert row is not None
            assert row["atividade_versao_id"] is None
            assert row["regra_snapshot_json"] is None
            assert row["codigo_normativo_snapshot"] is None


def test_phase_b1_validation_fails_when_same_base_has_active_aac_and_aeu_without_transition(tmp_path):
    with _temporary_database_binding(tmp_path, "phase_b1_missing_transition.db"):
        with main.app.app_context():
            main.init_db()
            conn = main.get_db_connection()

            norma_ids = _seed_normas_basicas(conn)
            base_id = _insert_atividade_base(conn, "Base sem transição AAC/AEU")
            _insert_atividade_versao(
                conn,
                atividade_base_id=base_id,
                norma_id=norma_ids["AAC-rev5"],
                codigo_normativo="AAC-rev5",
                eixo="AAC",
            )
            _insert_atividade_versao(
                conn,
                atividade_base_id=base_id,
                norma_id=norma_ids["AEU-rev1"],
                codigo_normativo="AEU-rev1",
                eixo="AEU",
            )

            with pytest.raises(ValueError, match="sem transi"):
                main.validar_integridade_versionamento_atividades(conn)


def test_phase_b1_validation_passes_with_valid_aac_para_aeu_transition(tmp_path):
    with _temporary_database_binding(tmp_path, "phase_b1_valid_transition.db"):
        with main.app.app_context():
            main.init_db()
            conn = main.get_db_connection()

            norma_ids = _seed_normas_basicas(conn)
            base_id = _insert_atividade_base(conn, "Base com transição válida")
            from_id = _insert_atividade_versao(
                conn,
                atividade_base_id=base_id,
                norma_id=norma_ids["AAC-rev5"],
                codigo_normativo="AAC-rev5",
                eixo="AAC",
            )
            to_id = _insert_atividade_versao(
                conn,
                atividade_base_id=base_id,
                norma_id=norma_ids["AEU-rev1"],
                codigo_normativo="AEU-rev1",
                eixo="AEU",
            )
            conn.execute(
                """
                INSERT INTO atividade_transicao (
                    from_atividade_versao_id, to_atividade_versao_id, tipo_transicao, justificativa
                ) VALUES (?, ?, 'aac_para_aeu', ?)
                """,
                (from_id, to_id, "Migração normativa justificada"),
            )

            assert main.validar_integridade_versionamento_atividades(conn) == []


def test_phase_b1_validation_passes_for_new_aeu_base_without_aac_history(tmp_path):
    with _temporary_database_binding(tmp_path, "phase_b1_new_aeu_base.db"):
        with main.app.app_context():
            main.init_db()
            conn = main.get_db_connection()

            norma_ids = _seed_normas_basicas(conn)
            base_id = _insert_atividade_base(conn, "Base exclusivamente AEU")
            _insert_atividade_versao(
                conn,
                atividade_base_id=base_id,
                norma_id=norma_ids["AEU-rev1"],
                codigo_normativo="AEU-rev1",
                eixo="AEU",
            )

            assert main.validar_integridade_versionamento_atividades(conn) == []


def test_phase_b1_validation_passes_for_two_aac_versions_in_same_base(tmp_path):
    with _temporary_database_binding(tmp_path, "phase_b1_two_aac_versions.db"):
        with main.app.app_context():
            main.init_db()
            conn = main.get_db_connection()

            norma_ids = _seed_normas_basicas(conn)
            base_id = _insert_atividade_base(conn, "Base com duas versões AAC")
            _insert_atividade_versao(
                conn,
                atividade_base_id=base_id,
                norma_id=norma_ids["AAC-rev5"],
                codigo_normativo="AAC-rev5",
                eixo="AAC",
            )
            _insert_atividade_versao(
                conn,
                atividade_base_id=base_id,
                norma_id=norma_ids["AAC-rev6"],
                codigo_normativo="AAC-rev6",
                eixo="AAC",
            )

            assert main.validar_integridade_versionamento_atividades(conn) == []


def test_phase_b1_validation_fails_for_cross_base_aac_para_aeu_transition(tmp_path):
    with _temporary_database_binding(tmp_path, "phase_b1_cross_base_transition.db"):
        with main.app.app_context():
            main.init_db()
            conn = main.get_db_connection()

            norma_ids = _seed_normas_basicas(conn)
            base_aac_id = _insert_atividade_base(conn, "Base AAC")
            base_aeu_id = _insert_atividade_base(conn, "Base AEU")
            from_id = _insert_atividade_versao(
                conn,
                atividade_base_id=base_aac_id,
                norma_id=norma_ids["AAC-rev5"],
                codigo_normativo="AAC-rev5",
                eixo="AAC",
            )
            to_id = _insert_atividade_versao(
                conn,
                atividade_base_id=base_aeu_id,
                norma_id=norma_ids["AEU-rev1"],
                codigo_normativo="AEU-rev1",
                eixo="AEU",
            )
            conn.execute(
                """
                INSERT INTO atividade_transicao (
                    from_atividade_versao_id, to_atividade_versao_id, tipo_transicao, justificativa
                ) VALUES (?, ?, 'aac_para_aeu', ?)
                """,
                (from_id, to_id, "Transição inválida entre bases"),
            )

            with pytest.raises(ValueError, match="atividade_base divergente"):
                main.validar_integridade_versionamento_atividades(conn)


def test_phase_b1_rejects_invalid_transition_type(tmp_path):
    with _temporary_database_binding(tmp_path, "phase_b1_invalid_transition_type.db"):
        with main.app.app_context():
            main.init_db()
            conn = main.get_db_connection()

            norma_ids = _seed_normas_basicas(conn)
            base_id = _insert_atividade_base(conn, "Base para tipo inválido")
            from_id = _insert_atividade_versao(
                conn,
                atividade_base_id=base_id,
                norma_id=norma_ids["AAC-rev5"],
                codigo_normativo="AAC-rev5",
                eixo="AAC",
            )

            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO atividade_transicao (
                        from_atividade_versao_id, tipo_transicao
                    ) VALUES (?, ?)
                    """,
                    (from_id, "tipo_invalido"),
                )


def test_phase_b1_rejects_duplicate_matriz_norma(tmp_path):
    with _temporary_database_binding(tmp_path, "phase_b1_duplicate_matriz_norma.db"):
        with main.app.app_context():
            main.init_db()
            conn = main.get_db_connection()

            norma_ids = _seed_normas_basicas(conn)
            matriz_id = _insert_matriz_basica(conn)
            conn.execute(
                "INSERT INTO matriz_norma (matriz_id, norma_id) VALUES (?, ?)",
                (matriz_id, norma_ids["AAC-rev5"]),
            )

            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO matriz_norma (matriz_id, norma_id) VALUES (?, ?)",
                    (matriz_id, norma_ids["AAC-rev5"]),
                )


def test_phase_b1_rejects_duplicate_matriz_atividade_versao_item(tmp_path):
    with _temporary_database_binding(tmp_path, "phase_b1_duplicate_matriz_versao_item.db"):
        with main.app.app_context():
            main.init_db()
            conn = main.get_db_connection()

            norma_ids = _seed_normas_basicas(conn)
            matriz_id = _insert_matriz_basica(conn)
            base_id = _insert_atividade_base(conn, "Base para matriz/versão")
            versao_id = _insert_atividade_versao(
                conn,
                atividade_base_id=base_id,
                norma_id=norma_ids["AAC-rev5"],
                codigo_normativo="AAC-rev5",
                eixo="AAC",
            )
            conn.execute(
                """
                INSERT INTO matriz_atividade_versao_item (matriz_id, atividade_versao_id)
                VALUES (?, ?)
                """,
                (matriz_id, versao_id),
            )

            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO matriz_atividade_versao_item (matriz_id, atividade_versao_id)
                    VALUES (?, ?)
                    """,
                    (matriz_id, versao_id),
                )


def test_phase_b_init_db_works_on_existing_legacy_database(tmp_path):
    with _temporary_database_binding(tmp_path, "phase_b_existing_legacy.db") as temp_db:
        legacy_conn = sqlite3.connect(temp_db)
        try:
            legacy_conn.execute(
                """
                CREATE TABLE usuarios (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nome TEXT NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    senha TEXT NOT NULL,
                    tipo TEXT NOT NULL CHECK(tipo IN ("admin", "aluno"))
                )
                """
            )
            legacy_conn.execute(
                """
                CREATE TABLE alunos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    usuario_id INTEGER UNIQUE,
                    nome TEXT NOT NULL,
                    matricula TEXT UNIQUE NOT NULL,
                    email TEXT UNIQUE
                )
                """
            )
            legacy_conn.execute(
                """
                CREATE TABLE turmas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nome TEXT NOT NULL UNIQUE,
                    ano INTEGER,
                    semestre INTEGER,
                    turno TEXT,
                    status TEXT
                )
                """
            )
            legacy_conn.execute(
                """
                CREATE TABLE atividades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    grupo TEXT NOT NULL,
                    nome TEXT NOT NULL UNIQUE,
                    limite_horas INTEGER
                )
                """
            )
            legacy_conn.execute(
                """
                CREATE TABLE requisicoes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    aluno_id INTEGER,
                    atividade_id INTEGER NOT NULL,
                    data_solicitacao TEXT NOT NULL,
                    data_evento TEXT NOT NULL,
                    horas_solicitadas REAL NOT NULL,
                    status TEXT NOT NULL
                )
                """
            )
            legacy_conn.execute(
                """
                INSERT INTO atividades (grupo, nome, limite_horas)
                VALUES ('1 - Grupo legado', 'Atividade legado pré-migração', 4)
                """
            )
            legacy_conn.commit()
        finally:
            legacy_conn.close()

        with main.app.app_context():
            main.init_db()
            conn = main.get_db_connection()
            assert _table_exists(conn, "atividade_versao")
            assert _table_exists(conn, "matriz_norma")
            assert _table_exists(conn, "atividade_legacy_map")
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM atividades WHERE nome = ?",
                    ("Atividade legado pré-migração",),
                ).fetchone()[0]
                == 1
            )
