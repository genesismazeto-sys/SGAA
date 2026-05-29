import os
import sqlite3
import sys
from pathlib import Path


BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main


def _legacy_setup(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE cursos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            codigo TEXT NOT NULL UNIQUE
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE atividades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            grupo TEXT NOT NULL,
            nome TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE requisicoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            aluno_id INTEGER,
            atividade_id INTEGER NOT NULL,
            data_solicitacao TEXT NOT NULL,
            data_evento TEXT NOT NULL,
            horas_solicitadas REAL NOT NULL,
            status TEXT NOT NULL,
            observacao TEXT
        )
        """
    )

    conn.execute(
        "INSERT INTO cursos (nome, codigo) VALUES (?, ?)",
        ("Curso Legado", "LEG"),
    )
    conn.execute(
        "INSERT INTO atividades (grupo, nome) VALUES (?, ?)",
        ("1 - Grupo legado", "Atividade legado"),
    )
    conn.execute(
        """
        INSERT INTO requisicoes (
            aluno_id, atividade_id, data_solicitacao, data_evento, horas_solicitadas, status, observacao
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (11, 1, "2026-05-23 10:00:00", "2026-05-20", 8.0, "Pendente", "registro legado"),
    )
    conn.commit()


def _table_columns(conn: sqlite3.Connection, table_name: str) -> list[str]:
    return [row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()]


def _index_count(conn: sqlite3.Connection, index_name: str) -> int:
    return conn.execute(
        """
        SELECT COUNT(*)
          FROM sqlite_master
         WHERE type = 'index'
           AND name = ?
        """,
        (index_name,),
    ).fetchone()[0]


def test_requisicoes_schema_versioning_idempotence(tmp_path):
    db_path = Path(tmp_path) / "requisicoes_legacy_idempotence.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    try:
        _legacy_setup(conn)

        cols_before = _table_columns(conn, "requisicoes")
        assert "atividade_versao_id" not in cols_before
        assert "regra_snapshot_json" not in cols_before
        assert "codigo_normativo_snapshot" not in cols_before

        legacy_before = conn.execute(
            """
            SELECT id, atividade_id, status, observacao
              FROM requisicoes
             ORDER BY id
            """
        ).fetchall()
        assert len(legacy_before) == 1

        main.ensure_atividade_versioning_schema(conn)
        conn.commit()

        cols_after_first = _table_columns(conn, "requisicoes")
        assert "atividade_versao_id" in cols_after_first
        assert "regra_snapshot_json" in cols_after_first
        assert "codigo_normativo_snapshot" in cols_after_first
        assert cols_after_first.count("atividade_versao_id") == 1
        assert cols_after_first.count("regra_snapshot_json") == 1
        assert cols_after_first.count("codigo_normativo_snapshot") == 1
        assert _index_count(conn, "idx_requisicoes_atividade_versao_id") == 1

        row_after_first = conn.execute(
            """
            SELECT id, atividade_id, status, observacao,
                   atividade_versao_id, regra_snapshot_json, codigo_normativo_snapshot
              FROM requisicoes
             ORDER BY id
            """
        ).fetchone()
        assert row_after_first is not None
        assert row_after_first["id"] == legacy_before[0]["id"]
        assert row_after_first["atividade_id"] == legacy_before[0]["atividade_id"]
        assert row_after_first["status"] == legacy_before[0]["status"]
        assert row_after_first["observacao"] == legacy_before[0]["observacao"]
        assert row_after_first["atividade_versao_id"] is None
        assert row_after_first["regra_snapshot_json"] is None
        assert row_after_first["codigo_normativo_snapshot"] is None

        # Segunda execução: deve permanecer estável e sem efeitos colaterais.
        main.ensure_atividade_versioning_schema(conn)
        conn.commit()

        cols_after_second = _table_columns(conn, "requisicoes")
        assert cols_after_second.count("atividade_versao_id") == 1
        assert cols_after_second.count("regra_snapshot_json") == 1
        assert cols_after_second.count("codigo_normativo_snapshot") == 1
        assert _index_count(conn, "idx_requisicoes_atividade_versao_id") == 1

        row_after_second = conn.execute(
            """
            SELECT id, atividade_id, status, observacao,
                   atividade_versao_id, regra_snapshot_json, codigo_normativo_snapshot
              FROM requisicoes
             ORDER BY id
            """
        ).fetchone()
        assert row_after_second is not None
        assert row_after_second["id"] == legacy_before[0]["id"]
        assert row_after_second["atividade_id"] == legacy_before[0]["atividade_id"]
        assert row_after_second["status"] == legacy_before[0]["status"]
        assert row_after_second["observacao"] == legacy_before[0]["observacao"]
        assert row_after_second["atividade_versao_id"] is None
        assert row_after_second["regra_snapshot_json"] is None
        assert row_after_second["codigo_normativo_snapshot"] is None
    finally:
        conn.close()
