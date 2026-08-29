"""Test-only hermetic builders for canonical historical prod-1 schemas.

These builders reconstruct the exact historical physical contracts
(prod-1/v1 Norma-era and prod-1/v2 post-Norma) from canonical historical DDL
and the REAL production migration entries, entirely under test/temp storage.

They never read, copy or write the operational ``database.db``.

The v1 DDL lives in ``hermetic_prod1_v1_schema.sql`` (byte-exact copy of the
historical canonical bootstrap script) and is proven to satisfy the production
v1 physical-signature detector (``_PROD1_V1_SIGNATURE_SHA256``) before any
fixture is handed to a test.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.prod1_schema import (
    BASELINE_MARKER,
    MATRIX_VERSION_REMOVAL_MARKER,
    NORMA_REMOVAL_MARKER,
    SCHEMA_EPOCH,
    _PROD1_V1_SIGNATURE_SHA256,
    _PROD1_V2_SIGNATURE_SHA256,
    _physical_schema_digest,
    migrate_prod1_v1_to_v2,
)

V1_SCHEMA_SQL_PATH = Path(__file__).with_name("hermetic_prod1_v1_schema.sql")


def load_v1_schema_sql() -> str:
    return V1_SCHEMA_SQL_PATH.read_text(encoding="utf-8")


def _markers(conn) -> list[tuple[int, str, str]]:
    return [
        (int(row[0]), str(row[1]), str(row[2]))
        for row in conn.execute(
            "SELECT version,name,schema_epoch FROM schema_migrations ORDER BY version"
        )
    ]


def _table_names(conn) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def _columns(conn, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


def build_canonical_v1_database(conn: sqlite3.Connection) -> None:
    """Create a genuine canonical prod-1/v1 database on the given connection.

    Executes the exact historical v1 DDL and independently proves, through the
    production signature detector, that the resulting physical schema matches
    the canonical v1 contract. No signature faking or validation bypass.
    """
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(load_v1_schema_sql())
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    assert _markers(conn) == [(1, BASELINE_MARKER, SCHEMA_EPOCH)]
    assert _physical_schema_digest(conn) == _PROD1_V1_SIGNATURE_SHA256


def seed_v1_business_data(conn: sqlite3.Connection) -> dict[str, int]:
    """Populate the canonical v1 schema with Norma-era business rows.

    Includes norma_atividade/matriz_norma links, a v1 request snapshot with
    codigo_normativo_snapshot, a non-null matrix lineage row and two turmas.
    All IDs are returned for preservation checks.
    """
    curso_id = conn.execute(
        """INSERT INTO cursos (nome,codigo,duracao_periodos,total_horas_aac,total_horas_aeu,periodo,status)
           VALUES ('Curso Fixture V1','FIX1',8,160,80,'diurno','ativo') RETURNING id"""
    ).fetchone()[0]
    norma1 = conn.execute(
        "INSERT INTO norma_atividade (codigo,eixo,revisao,nome,status) VALUES ('N-001','AAC','rev1','Norma AAC V1','ativa') RETURNING id"
    ).fetchone()[0]
    norma2 = conn.execute(
        "INSERT INTO norma_atividade (codigo,eixo,revisao,nome,status) VALUES ('N-002','AEU','rev1','Norma AEU V1','ativa') RETURNING id"
    ).fetchone()[0]
    base1 = conn.execute(
        "INSERT INTO atividade_base (nome_conceito,descricao,status) VALUES ('Base Fixture V1 A','base v1','ativo') RETURNING id"
    ).fetchone()[0]
    base2 = conn.execute(
        "INSERT INTO atividade_base (nome_conceito,descricao,status) VALUES ('Base Fixture V1 B','base v1','ativo') RETURNING id"
    ).fetchone()[0]
    v1a = conn.execute(
        """INSERT INTO atividade_versao
               (atividade_base_id,norma_id,codigo_normativo,eixo,grupo,ch_por_evento,limite_semestre,numero_versao,status)
             VALUES (?,?,'N-001','AAC','1 - FixV1',4,20,1,'ativa') RETURNING id""",
        (base1, norma1),
    ).fetchone()[0]
    v1b = conn.execute(
        """INSERT INTO atividade_versao
               (atividade_base_id,norma_id,codigo_normativo,eixo,grupo,ch_por_evento,numero_versao,status,versao_anterior_id)
             VALUES (?,?,'N-001','AAC','1 - FixV1',4,2,'ativa',?) RETURNING id""",
        (base1, norma1, v1a),
    ).fetchone()[0]
    v2a = conn.execute(
        """INSERT INTO atividade_versao
               (atividade_base_id,norma_id,codigo_normativo,eixo,grupo,ch_por_evento,numero_versao,status)
             VALUES (?,?,'N-002','AEU','2 - FixV1',5,1,'ativa') RETURNING id""",
        (base2, norma2),
    ).fetchone()[0]
    m1 = conn.execute(
        """INSERT INTO matrizes_atividades
               (curso_id,nome,versao,status,horas_aac_obrigatorias,horas_extensao_obrigatorias)
             VALUES (?,'Matriz Fixture V1 A','2026.1','vigente',100,50) RETURNING id""",
        (curso_id,),
    ).fetchone()[0]
    m2 = conn.execute(
        """INSERT INTO matrizes_atividades (curso_id,nome,versao,matriz_origem_id,status)
             VALUES (?,'Matriz Fixture V1 B','2026.2',?,'rascunho') RETURNING id""",
        (curso_id, m1),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO matriz_norma (matriz_id,norma_id) VALUES (?,?)", (m1, norma1)
    )
    conn.execute(
        "INSERT INTO matriz_norma (matriz_id,norma_id) VALUES (?,?)", (m1, norma2)
    )
    conn.execute(
        "INSERT INTO matriz_norma (matriz_id,norma_id) VALUES (?,?)", (m2, norma1)
    )
    conn.execute(
        "INSERT INTO matriz_atividade_versao_item (matriz_id,atividade_base_id,atividade_versao_id) VALUES (?,?,?)",
        (m1, base1, v1a),
    )
    conn.execute(
        "INSERT INTO matriz_atividade_versao_item (matriz_id,atividade_base_id,atividade_versao_id) VALUES (?,?,?)",
        (m1, base2, v2a),
    )
    conn.execute(
        "INSERT INTO matriz_atividade_versao_item (matriz_id,atividade_base_id,atividade_versao_id) VALUES (?,?,?)",
        (m2, base1, v1b),
    )
    turma1 = conn.execute(
        """INSERT INTO turmas (nome,turno,status,numero,curso_id,ano_inicio,semestre_inicio,codigo,matriz_id)
           VALUES ('FIXV1-T1','Manha','Ativa',1,?,2026,1,'FIXV1-T1',?) RETURNING id""",
        (curso_id, m1),
    ).fetchone()[0]
    turma2 = conn.execute(
        """INSERT INTO turmas (nome,turno,status,numero,curso_id,ano_inicio,semestre_inicio,codigo,matriz_id)
           VALUES ('FIXV1-T2','Tarde','Ativa',2,?,2026,1,'FIXV1-T2',?) RETURNING id""",
        (curso_id, m2),
    ).fetchone()[0]
    usuario_id = conn.execute(
        "INSERT INTO usuarios (nome,email,senha,tipo) VALUES ('Aluno V1','aluno.v1@fixture.local','x','aluno') RETURNING id"
    ).fetchone()[0]
    aluno_id = conn.execute(
        """INSERT INTO alunos (usuario_id,nome,matricula,email,turma_id,status)
           VALUES (?,'Aluno V1','FIXV1.0001','aluno.v1@fixture.local',?,'Ativo') RETURNING id""",
        (usuario_id, turma1),
    ).fetchone()[0]
    snapshot_v1 = {
        "atividade_base_id": base1,
        "atividade_versao_id": v1a,
        "atividade_versao_numero": 1,
        "norma_id": norma1,
        "codigo_normativo": "N-001",
        "eixo": "AAC",
        "grupo": "1 - FixV1",
        "ch_por_evento": 4,
        "limite_semestre": 20,
        "limite_total": None,
        "documentos_json": "[]",
        "observacao_aluno": None,
        "observacao_admin": None,
        "vigencia_inicio": None,
        "vigencia_fim": None,
        "versao_status": "ativa",
        "matriz_id_efetiva": m1,
        "nome_exibivel": "Base Fixture V1 A",
        "tipo_atividade": "Acadêmica Complementar",
        "flow_origin": "fixture_v1",
        "schema_version": "prod-1-request-v1",
        "snapshot_written_at": "2026-08-29T00:00:00Z",
    }
    req1 = conn.execute(
        """INSERT INTO requisicoes
               (aluno_id,atividade_versao_id,data_solicitacao,data_evento,horas_solicitadas,status,
                regra_snapshot_json,codigo_normativo_snapshot)
             VALUES (?,?,'2026-08-29','2026-08-30',4.0,'Pendente',?,'N-001') RETURNING id""",
        (aluno_id, v1a, json.dumps(snapshot_v1)),
    ).fetchone()[0]
    conn.commit()
    return {
        "curso_id": curso_id,
        "norma1": norma1,
        "norma2": norma2,
        "base1": base1,
        "base2": base2,
        "v1a": v1a,
        "v1b": v1b,
        "v2a": v2a,
        "m1": m1,
        "m2": m2,
        "turma1": turma1,
        "turma2": turma2,
        "usuario_id": usuario_id,
        "aluno_id": aluno_id,
        "req1": req1,
    }


def build_canonical_v2_database(conn: sqlite3.Connection) -> None:
    """Create a genuine canonical prod-1/v2 database on the given connection.

    The v2 contract is obtained by running the REAL production v1→v2 migration
    over a hermetic canonical v1 database, then proving the result satisfies
    the production v2 physical-signature detector. No historical DDL is
    duplicated and no active database is involved.
    """
    build_canonical_v1_database(conn)
    migrate_prod1_v1_to_v2(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
    assert _markers(conn) == [
        (1, BASELINE_MARKER, SCHEMA_EPOCH),
        (2, NORMA_REMOVAL_MARKER, SCHEMA_EPOCH),
    ]
    assert _physical_schema_digest(conn) == _PROD1_V2_SIGNATURE_SHA256


def seed_v2_business_data(conn: sqlite3.Connection) -> dict[str, int]:
    """Populate the canonical v2 schema with natively-v2 business rows.

    Includes multiple matrices (one with non-null matriz_origem_id), a
    turma→matrix relationship, exact matrix→activity-version links and a
    prod-1-request-v2 request snapshot.
    """
    curso_id = conn.execute(
        """INSERT INTO cursos (nome,codigo,duracao_periodos,total_horas_aac,total_horas_aeu,periodo,status)
           VALUES ('Curso Fixture V2','FIX2',8,160,80,'diurno','ativo') RETURNING id"""
    ).fetchone()[0]
    m1 = conn.execute(
        """INSERT INTO matrizes_atividades
               (curso_id,nome,versao,status,horas_aac_obrigatorias,horas_extensao_obrigatorias)
             VALUES (?,'Matriz Fixture V2 A','2026.1','vigente',100,50) RETURNING id""",
        (curso_id,),
    ).fetchone()[0]
    m2 = conn.execute(
        """INSERT INTO matrizes_atividades (curso_id,nome,versao,matriz_origem_id,status)
             VALUES (?,'Matriz Fixture V2 B','2026.2',?,'vigente') RETURNING id""",
        (curso_id, m1),
    ).fetchone()[0]
    m3 = conn.execute(
        """INSERT INTO matrizes_atividades (curso_id,nome,versao,status)
             VALUES (?,'Matriz Fixture V2 C','2026.3','rascunho') RETURNING id""",
        (curso_id,),
    ).fetchone()[0]
    base_a = conn.execute(
        "INSERT INTO atividade_base (nome_conceito,descricao,status) VALUES ('Base Fixture V2 A','base v2','ativo') RETURNING id"
    ).fetchone()[0]
    base_b = conn.execute(
        "INSERT INTO atividade_base (nome_conceito,descricao,status) VALUES ('Base Fixture V2 B','base v2','ativo') RETURNING id"
    ).fetchone()[0]
    v_a = conn.execute(
        """INSERT INTO atividade_versao
               (atividade_base_id,eixo,grupo,ch_por_evento,numero_versao,status)
             VALUES (?,'AAC','1 - FixV2',4,1,'ativa') RETURNING id""",
        (base_a,),
    ).fetchone()[0]
    v_b = conn.execute(
        """INSERT INTO atividade_versao
               (atividade_base_id,eixo,grupo,ch_por_evento,numero_versao,status)
             VALUES (?,'AEU','2 - FixV2',5,1,'ativa') RETURNING id""",
        (base_b,),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO matriz_atividade_versao_item (matriz_id,atividade_base_id,atividade_versao_id) VALUES (?,?,?)",
        (m1, base_a, v_a),
    )
    conn.execute(
        "INSERT INTO matriz_atividade_versao_item (matriz_id,atividade_base_id,atividade_versao_id) VALUES (?,?,?)",
        (m1, base_b, v_b),
    )
    conn.execute(
        "INSERT INTO matriz_atividade_versao_item (matriz_id,atividade_base_id,atividade_versao_id) VALUES (?,?,?)",
        (m2, base_a, v_a),
    )
    turma_id = conn.execute(
        """INSERT INTO turmas (nome,turno,status,numero,curso_id,ano_inicio,semestre_inicio,codigo,matriz_id)
           VALUES ('FIXV2-T1','Manha','Ativa',1,?,2026,1,'FIXV2-T1',?) RETURNING id""",
        (curso_id, m1),
    ).fetchone()[0]
    usuario_id = conn.execute(
        "INSERT INTO usuarios (nome,email,senha,tipo) VALUES ('Aluno V2','aluno.v2@fixture.local','x','aluno') RETURNING id"
    ).fetchone()[0]
    aluno_id = conn.execute(
        """INSERT INTO alunos (usuario_id,nome,matricula,email,turma_id,status)
           VALUES (?,'Aluno V2','FIXV2.0001','aluno.v2@fixture.local',?,'Ativo') RETURNING id""",
        (usuario_id, turma_id),
    ).fetchone()[0]
    snapshot_v2 = {
        "atividade_base_id": base_a,
        "atividade_versao_id": v_a,
        "atividade_versao_numero": 1,
        "eixo": "AAC",
        "matriz_id_efetiva": m1,
        "schema_version": "prod-1-request-v2",
        "ch_por_evento": 4,
        "limite_semestre": None,
        "limite_total": None,
        "nome_exibivel": "Base Fixture V2 A",
        "tipo_atividade": "Acadêmica Complementar",
        "grupo": "1 - FixV2",
        "documentos_json": "[]",
    }
    req_id = conn.execute(
        """INSERT INTO requisicoes
               (aluno_id,atividade_versao_id,data_solicitacao,data_evento,horas_solicitadas,status,regra_snapshot_json)
             VALUES (?,?,'2026-08-29','2026-08-30',4.0,'Pendente',?) RETURNING id""",
        (aluno_id, v_a, json.dumps(snapshot_v2)),
    ).fetchone()[0]
    conn.commit()
    return {
        "curso_id": curso_id,
        "m1": m1,
        "m2": m2,
        "m3": m3,
        "base_a": base_a,
        "base_b": base_b,
        "v_a": v_a,
        "v_b": v_b,
        "turma_id": turma_id,
        "usuario_id": usuario_id,
        "aluno_id": aluno_id,
        "req_id": req_id,
    }


__all__ = [
    "build_canonical_v1_database",
    "build_canonical_v2_database",
    "load_v1_schema_sql",
    "seed_v1_business_data",
    "seed_v2_business_data",
]
