import sqlite3
import shutil
from pathlib import Path

from app.prod1_schema import SCHEMA_VERSION, bootstrap_prod1_schema


def test_current_schema_is_v6_with_nullable_indexed_student_matrix_fk():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    bootstrap_prod1_schema(conn)
    assert SCHEMA_VERSION == 6
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 6
    columns = {row["name"]: row for row in conn.execute("PRAGMA table_info(alunos)")}
    assert columns["matriz_id"]["notnull"] == 0
    fks = conn.execute("PRAGMA foreign_key_list(alunos)").fetchall()
    assert any(row["from"] == "matriz_id" and row["table"] == "matrizes_atividades" and row["on_update"] == "CASCADE" and row["on_delete"] == "RESTRICT" for row in fks)
    indexes = {row["name"] for row in conn.execute("PRAGMA index_list(alunos)")}
    assert "idx_alunos_matriz_id" in indexes


def test_v5_to_v6_copy_backfills_only_current_valid_turma_default(tmp_path):
    source = Path(__file__).resolve().parents[1] / "database.db"
    target = tmp_path / "prod-copy.db"
    shutil.copy2(source, target)
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")

    c1 = conn.execute(
        "INSERT INTO cursos(nome,codigo,duracao_periodos) VALUES('Mig C1','MIG1',8)"
    ).lastrowid
    c2 = conn.execute(
        "INSERT INTO cursos(nome,codigo,duracao_periodos) VALUES('Mig C2','MIG2',8)"
    ).lastrowid
    m1 = conn.execute(
        "INSERT INTO matrizes_atividades(curso_id,nome) VALUES(?,'Mig M1')", (c1,)
    ).lastrowid
    m2 = conn.execute(
        "INSERT INTO matrizes_atividades(curso_id,nome) VALUES(?,'Mig M2')", (c2,)
    ).lastrowid
    valid_turma = conn.execute(
        "INSERT INTO turmas(nome,numero,curso_id,matriz_id,ano_inicio,semestre_inicio,codigo) VALUES('Mig T1',1,?,?,2026,1,'MIG1-T1')",
        (c1, m1),
    ).lastrowid
    no_default_turma = conn.execute(
        "INSERT INTO turmas(nome,numero,curso_id,matriz_id,ano_inicio,semestre_inicio,codigo) VALUES('Mig T2',2,?,NULL,2026,1,'MIG1-T2')",
        (c1,),
    ).lastrowid
    incompatible_turma = conn.execute(
        "INSERT INTO turmas(nome,numero,curso_id,matriz_id,ano_inicio,semestre_inicio,codigo) VALUES('Mig T3',3,?,?,2026,1,'MIG1-T3')",
        (c1, m2),
    ).lastrowid
    student_ids = [
        conn.execute("INSERT INTO alunos(nome,matricula,turma_id) VALUES('Valid','MIG-A1',?)", (valid_turma,)).lastrowid,
        conn.execute("INSERT INTO alunos(nome,matricula,turma_id) VALUES('No default','MIG-A2',?)", (no_default_turma,)).lastrowid,
        conn.execute("INSERT INTO alunos(nome,matricula,turma_id) VALUES('Wrong default','MIG-A3',?)", (incompatible_turma,)).lastrowid,
        conn.execute("INSERT INTO alunos(nome,matricula,turma_id) VALUES('No turma','MIG-A4',NULL)").lastrowid,
    ]
    requests_before = conn.execute(
        "SELECT id,atividade_versao_id,regra_snapshot_json,turma_id_snapshot,turma_codigo_snapshot FROM requisicoes ORDER BY id"
    ).fetchall()
    versions_before = conn.execute(
        "SELECT * FROM atividade_versao ORDER BY id"
    ).fetchall()
    conn.commit()

    result = bootstrap_prod1_schema(conn)
    assert result["schema_version"] == 6
    rows = conn.execute(
        "SELECT id,matriz_id FROM alunos WHERE id IN (?,?,?,?) ORDER BY id", student_ids
    ).fetchall()
    assert [row["matriz_id"] for row in rows] == [m1, None, None, None]
    assert conn.execute("SELECT version,name FROM schema_migrations WHERE version=6").fetchone()["name"] == "student_matrix_authority"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert conn.execute(
        "SELECT id,atividade_versao_id,regra_snapshot_json,turma_id_snapshot,turma_codigo_snapshot FROM requisicoes ORDER BY id"
    ).fetchall() == requests_before
    assert conn.execute("SELECT * FROM atividade_versao ORDER BY id").fetchall() == versions_before
    assert bootstrap_prod1_schema(conn)["schema_version"] == 6
    assert conn.execute("SELECT COUNT(*) FROM schema_migrations WHERE version=6").fetchone()[0] == 1
    conn.close()
