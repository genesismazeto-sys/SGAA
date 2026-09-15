import sqlite3

from app.prod1_schema import (
    ARQUIVOS_GOOGLE_DRIVE_MARKER,
    SCHEMA_VERSION,
    STUDENT_MATRIX_AUTHORITY_MARKER,
    bootstrap_prod1_schema,
    migrate_prod1_v2_to_v3,
    migrate_prod1_v3_to_v4,
    migrate_prod1_v4_to_v5,
)
from tests.hermetic_prod1_fixtures import (
    build_canonical_v2_database,
    seed_v2_business_data,
)


def _build_hermetic_v5_database(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    build_canonical_v2_database(conn)
    seeded_ids = seed_v2_business_data(conn)
    migrate_prod1_v2_to_v3(conn)
    migrate_prod1_v3_to_v4(conn)
    migrate_prod1_v4_to_v5(conn)

    assert conn.execute("PRAGMA user_version").fetchone()[0] == 5
    assert "matriz_id" not in {
        row["name"] for row in conn.execute("PRAGMA table_info(alunos)")
    }
    assert conn.execute(
        "SELECT name FROM schema_migrations WHERE version=5"
    ).fetchone()["name"] == ARQUIVOS_GOOGLE_DRIVE_MARKER
    assert conn.execute(
        "SELECT 1 FROM schema_migrations WHERE version=?", (SCHEMA_VERSION,)
    ).fetchone() is None
    return conn, seeded_ids


def test_current_schema_is_v6_with_nullable_indexed_student_matrix_fk():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    bootstrap_prod1_schema(conn)
    # AM1's student-Matrix authority survives later epochs; the current head is v7.
    assert SCHEMA_VERSION == 7
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 7
    columns = {row["name"]: row for row in conn.execute("PRAGMA table_info(alunos)")}
    assert columns["matriz_id"]["notnull"] == 0
    fks = conn.execute("PRAGMA foreign_key_list(alunos)").fetchall()
    assert any(row["from"] == "matriz_id" and row["table"] == "matrizes_atividades" and row["on_update"] == "CASCADE" and row["on_delete"] == "RESTRICT" for row in fks)
    indexes = {row["name"] for row in conn.execute("PRAGMA index_list(alunos)")}
    assert "idx_alunos_matriz_id" in indexes


def test_v5_to_v6_copy_backfills_only_current_valid_turma_default(tmp_path):
    target = tmp_path / "hermetic-v5.db"
    conn, seeded_ids = _build_hermetic_v5_database(target)

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
    requests_before = [
        tuple(row)
        for row in conn.execute(
            "SELECT id,atividade_versao_id,regra_snapshot_json,turma_id_snapshot,turma_codigo_snapshot FROM requisicoes ORDER BY id"
        )
    ]
    versions_before = [
        tuple(row) for row in conn.execute("SELECT * FROM atividade_versao ORDER BY id")
    ]
    assert requests_before
    assert versions_before
    conn.commit()

    result = bootstrap_prod1_schema(conn)
    assert result["schema_version"] == SCHEMA_VERSION
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    rows = conn.execute(
        "SELECT id,matriz_id FROM alunos WHERE id IN (?,?,?,?) ORDER BY id", student_ids
    ).fetchall()
    assert [row["matriz_id"] for row in rows] == [m1, None, None, None]
    assert conn.execute(
        "SELECT matriz_id FROM alunos WHERE id=?", (seeded_ids["aluno_id"],)
    ).fetchone()["matriz_id"] == seeded_ids["m1"]
    # AM1's marker is recorded at its own version (6); later epochs append
    # their own rows rather than rewriting this one.
    assert conn.execute(
        "SELECT version,name FROM schema_migrations WHERE version=?", (6,)
    ).fetchone()["name"] == STUDENT_MATRIX_AUTHORITY_MARKER
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert [
        tuple(row)
        for row in conn.execute(
            "SELECT id,atividade_versao_id,regra_snapshot_json,turma_id_snapshot,turma_codigo_snapshot FROM requisicoes ORDER BY id"
        )
    ] == requests_before
    assert [
        tuple(row) for row in conn.execute("SELECT * FROM atividade_versao ORDER BY id")
    ] == versions_before

    conn.execute(
        "UPDATE alunos SET matriz_id=? WHERE id=?", (m1, student_ids[-1])
    )
    conn.commit()
    assert bootstrap_prod1_schema(conn)["schema_version"] == SCHEMA_VERSION
    assert conn.execute(
        "SELECT matriz_id FROM alunos WHERE id=?", (student_ids[-1],)
    ).fetchone()["matriz_id"] == m1
    assert conn.execute(
        "SELECT COUNT(*) FROM schema_migrations WHERE version=?", (SCHEMA_VERSION,)
    ).fetchone()[0] == 1
    conn.close()
