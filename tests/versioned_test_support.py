from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

import main
from app import db as app_db_module


SIMPLE_HOURS_BY_VERSION_ID = {
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


LEGACY_ACTIVITY_DATA = {
    1: ("Visitas técnicas ou culturais", "Acadêmica Complementar"),
    2: ("Curso de curta duração em aviação", "Acadêmica Complementar"),
    3: ("Participação em eventos técnico-científicos", "Acadêmica Complementar"),
    4: ("Monitoria acadêmica supervisionada", "Acadêmica Complementar"),
    5: ("Curso livre com aderência à área", "Acadêmica Complementar"),
    6: ("Atividade correlata fora do escopo da matriz", "Acadêmica Complementar"),
    7: ("Publicação de resumo em congresso", "Acadêmica Complementar"),
    8: ("Atividade disponível apenas na matriz nova", "Acadêmica Complementar"),
    9: ("Minicurso temático complementar", "Acadêmica Complementar"),
    10: ("Seminário avançado de formação", "Acadêmica Complementar"),
    11: ("Participação em liga acadêmica", "Acadêmica Complementar"),
    12: ("Curso de software aeronáutico", "Acadêmica Complementar"),
    13: ("Atividade complementar com avaliação especial", "Acadêmica Complementar"),
    14: ("Projeto de inovação aplicada", "Acadêmica Complementar"),
    15: ("Oficina de competências profissionais", "Acadêmica Complementar"),
    16: ("Acompanhamento de laboratório temático", "Acadêmica Complementar"),
    17: ("Palestra institucional certificada", "Acadêmica Complementar"),
    18: ("Workshop de curta duração", "Acadêmica Complementar"),
    19: ("Participação em banca simulada", "Acadêmica Complementar"),
    20: ("Curso de atualização tecnológica", "Acadêmica Complementar"),
    21: ("Atividade cultural com relatório", "Acadêmica Complementar"),
    22: ("Acompanhamento de projeto aplicado", "Acadêmica Complementar"),
    23: ("Capacitação em segurança operacional", "Acadêmica Complementar"),
    24: ("Atividade de integração com o setor produtivo", "Acadêmica Complementar"),
    25: ("Programa de mentoria acadêmica", "Acadêmica Complementar"),
    26: ("Horas de voo em simulador", "Acadêmica Complementar"),
    27: ("Participação em projetos de extensão", "Acadêmica Complementar"),
    28: ("Trabalho voluntário em organizações do terceiro setor", "Acadêmica Complementar"),
    29: ("Participação em projetos de apoio institucional", "Extensão Universitária"),
    30: ("Projeto extensionista com impacto comunitário", "Extensão Universitária"),
    31: ("Ação solidária universitária", "Extensão Universitária"),
}


def _version_observations(version_id: int) -> tuple[str, str]:
    if version_id == 2:
        return (
            "Recomenda-se certificado de conclusão contendo identificação do curso, instituição, data de conclusão e carga horária.",
            "Validar se o curso é de curta duração e ligado à área da aviação, evitando dupla contagem com formação profissional quando for a mesma evidência.",
        )
    if version_id == 48:
        return (
            "5h por filme/peça, limite de 50h por semestre. Recomenda-se bilhete/ingresso e relatório conforme modelo da atividade, com mínimo de 2 páginas.",
            "Aplicar 5h por filme/peça, até o limite de 50h por semestre. Validar relatório no modelo da atividade, com mínimo de 2 páginas, além do ingresso/comprovação.",
        )
    if version_id == 52:
        return (
            "No regime histórico AAC-rev5, esta atividade é contabilizada como AAC. Limite de 40h por semestre. Recomenda-se declaração ou certificado contendo nome do aluno, identificação do projeto, período e carga horária.",
            "Manter enquadramento histórico como AAC para matriz antiga. Aplicar limite de 40h por semestre. Validar comprovação do projeto e evitar migração automática para AEU neste regime.",
        )
    if version_id == 54:
        return (
            "No regime histórico AAC-rev5, esta atividade é contabilizada como AAC. Limite de 40h por semestre. Recomenda-se declaração da entidade contendo período, atividades desenvolvidas e carga horária.",
            "Manter enquadramento histórico como AAC para matriz antiga. Aplicar limite de 40h por semestre. Validar declaração da entidade, atividades desenvolvidas e carga horária comprovada.",
        )
    return (
        f"Orientação textual para o aluno na atividade versionada {version_id}.",
        f"Orientação textual para análise administrativa da atividade versionada {version_id}.",
    )


def _matrix10_limits(version_id: int) -> tuple[float | None, float | None]:
    if version_id == 1:
        return 40.0, None
    if version_id == 2:
        return None, 100.0
    if version_id == 3:
        return 20.0, None
    return None, None


def seed_reference_versioned_dataset(conn) -> None:
    curso_id = conn.execute(
        """
        INSERT INTO cursos (nome, codigo, duracao_periodos, periodo, status)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("Programa Piloto de Aviação", "PPA", 8, "integral", "ativo"),
    ).lastrowid

    conn.execute(
        """
        INSERT INTO matrizes_atividades (
            id, curso_id, nome, versao, status, horas_aac_obrigatorias, horas_extensao_obrigatorias
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (1, curso_id, "Matriz PPA", "T10", "vigente", 200, 100),
    )
    conn.execute(
        """
        INSERT INTO matrizes_atividades (
            id, curso_id, nome, versao, status, horas_aac_obrigatorias, horas_extensao_obrigatorias
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (2, curso_id, "Matriz PPA", "T11", "vigente", 200, 100),
    )

    conn.execute(
        """
        INSERT INTO turmas (
            id, nome, turno, status, numero, curso_id, matriz_id,
            ano_inicio, semestre_inicio, ano_fim, semestre_fim, codigo
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (1, "PPA-T10", "Manhã", "Ativa", 10, curso_id, 1, 2025, 2, 2028, 1, "PPA-T10"),
    )
    conn.execute(
        """
        INSERT INTO turmas (
            id, nome, turno, status, numero, curso_id, matriz_id,
            ano_inicio, semestre_inicio, ano_fim, semestre_fim, codigo
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (2, "PPA-T11", "Manhã", "Ativa", 11, curso_id, 2, 2026, 1, 2028, 2, "PPA-T11"),
    )

    conn.executemany(
        """
        INSERT INTO norma_atividade (id, codigo, eixo, revisao, nome, status)
        VALUES (?, ?, ?, ?, ?, 'ativa')
        """,
        (
            (1, "AAC-rev5", "AAC", "rev5", "AAC regulamento antigo"),
            (2, "AAC-rev6", "AAC", "rev6", "AAC regulamento novo"),
            (3, "AEU-rev1", "AEU", "rev1", "AEU versão inicial"),
        ),
    )

    base_rows = [
        (
            base_id,
            LEGACY_ACTIVITY_DATA.get(base_id, (f"Base conceitual {base_id:02d}", ""))[0],
            f"Base sintética para atividade versionada {base_id:02d}.",
            "ativo",
        )
        for base_id in range(1, 33)
    ]
    conn.executemany(
        """
        INSERT INTO atividade_base (id, nome_conceito, descricao, status)
        VALUES (?, ?, ?, ?)
        """,
        base_rows,
    )

    version_rows = []
    matrix10_version_ids = []
    matrix11_version_ids = []

    # Tracks next numero_versao per base_id so explicit seeds match migration output.
    _nv: dict[int, int] = {}

    def _nv_next(b: int) -> int:
        n = _nv.get(b, 0) + 1
        _nv[b] = n
        return n

    matrix10_base_ids = [2, 1] + list(range(3, 29))
    for version_id, base_id in zip(range(1, 29), matrix10_base_ids):
        limit_semestre, limite_total = _matrix10_limits(version_id)
        observacao_aluno, observacao_admin = _version_observations(version_id)
        version_rows.append(
            (
                version_id,
                base_id,
                1,
                "AAC-rev5",
                "AAC",
                "1 - AAC histórico",
                SIMPLE_HOURS_BY_VERSION_ID.get(version_id),
                limit_semestre,
                limite_total,
                observacao_aluno,
                observacao_admin,
                None,
                _nv_next(base_id),
                "ativa",
            )
        )
        matrix10_version_ids.append(version_id)

    matrix11_aac_bases = list(range(1, 26)) + [32]
    for version_id, base_id in zip(range(29, 55), matrix11_aac_bases):
        observacao_aluno, observacao_admin = _version_observations(version_id)
        version_rows.append(
            (
                version_id,
                base_id,
                2,
                "AAC-rev6",
                "AAC",
                "1 - AAC vigente",
                SIMPLE_HOURS_BY_VERSION_ID.get(version_id),
                None,
                None,
                observacao_aluno,
                observacao_admin,
                None,
                _nv_next(base_id),
                "ativa",
            )
        )
        matrix11_version_ids.append(version_id)

    for version_id, base_id in zip(range(55, 60), range(27, 32)):
        observacao_aluno, observacao_admin = _version_observations(version_id)
        limite_total = 40.0 if version_id == 59 else None
        version_rows.append(
            (
                version_id,
                base_id,
                3,
                "AEU-rev1",
                "AEU",
                "2 - Extensão vigente",
                SIMPLE_HOURS_BY_VERSION_ID.get(version_id),
                None,
                limite_total,
                observacao_aluno,
                observacao_admin,
                None,
                _nv_next(base_id),
                "ativa",
            )
        )
        matrix11_version_ids.append(version_id)

    conn.executemany(
        """
        INSERT INTO atividade_versao (
            id, atividade_base_id, norma_id, codigo_normativo, eixo, grupo,
            ch_por_evento, limite_semestre, limite_total, observacao_aluno,
            observacao_admin, documentos_json, numero_versao, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        version_rows,
    )

    conn.executemany(
        "INSERT INTO matriz_norma (matriz_id, norma_id) VALUES (?, ?)",
        [(1, 1), (2, 2), (2, 3)],
    )
    conn.executemany(
        "INSERT INTO matriz_atividade_versao_item (matriz_id, atividade_base_id, atividade_versao_id) VALUES (?, ?, ?)",
        [(1, version_rows[version_id - 1][1], version_id) for version_id in matrix10_version_ids]
        + [(2, version_rows[version_id - 1][1], version_id) for version_id in matrix11_version_ids],
    )

    conn.execute(
        """
        INSERT INTO usuarios (nome, email, senha, tipo)
        VALUES (?, ?, ?, ?)
        """,
        ("Aluno Base Versionado", "aluno.base.versionado@example.com", main.hash_password("aluno123"), "aluno"),
    )
    usuario_id = conn.execute(
        "SELECT id FROM usuarios WHERE email = ?",
        ("aluno.base.versionado@example.com",),
    ).fetchone()["id"]
    conn.execute(
        """
        INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            usuario_id,
            "Aluno Base Versionado",
            "PPA.TESTE.0001",
            "aluno.base.versionado@example.com",
            2,
            "Ativo",
        ),
    )
    conn.commit()


@contextmanager
def isolated_versioned_app_env(tmp_path, database_name: str):
    app = main.app
    temp_database = tmp_path / database_name
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

    try:
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
            conn = main.get_db_connection()
            seed_reference_versioned_dataset(conn)

        client = app.test_client()
        yield {
            "client": client,
            "db_path": Path(temp_database),
            "uploads_path": temp_uploads,
            "documents_path": temp_documents,
            "local_backups_path": temp_local_backups,
            "cloud_backups_path": temp_cloud_backups,
        }
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
