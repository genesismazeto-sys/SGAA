"""prod-1/v12: Extensão falls back to 160 h, like Acadêmica (UI-B33).

The SGAA default for both kinds of complementary hours is 160 h, but the 80 h
Extensão default of the first baseline survived in three places: the
``DEFAULT_CURSO_TOTAL_HORAS_AEU`` constant and the column DEFAULT of
``cursos.total_horas_aeu`` and ``matrizes_atividades.horas_extensao_
obrigatorias``. Nova Curso inserts without hours, so every new course took the
database's 80. v12 moves both DEFAULTs to 160 through a table rebuild; every
stored value -- including an 80 -- is kept exactly, and nothing is backfilled.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

import main
from app.academics import DEFAULT_CURSO_TOTAL_HORAS_AAC, DEFAULT_CURSO_TOTAL_HORAS_AEU
from app.db import DEFAULT_HORAS_ACADEMICA, DEFAULT_HORAS_EXTENSAO
from app.prod1_extension_hours_v12 import _V12_DETAILS_JSON, migrate_prod1_v11_to_v12
from app.prod1_schema import (
    EXTENSION_HOURS_DEFAULT_MARKER,
    PROD1_SCHEMA_SQL,
    SCHEMA_VERSION,
    Prod1SchemaError,
    _PROD1_V11_SIGNATURE_SHA256,
    _PROD1_V12_SIGNATURE_SHA256,
    _physical_schema_digest,
    _validate_prod1_v11_schema,
    _validate_prod1_v12_schema,
    bootstrap_prod1_schema,
    validate_prod1_schema,
)
from tests.canonical_matrix_test_support import login_admin
from tests.prod1_v12_support import revert_prod1_v12_to_v11
from tests.prod1_v13_support import revert_prod1_v13_to_v12
from tests.versioned_test_support import isolated_versioned_app_env


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _column_default(conn, table: str, column: str) -> str:
    return next(
        str(row[4]) for row in conn.execute(f"PRAGMA table_info({table})") if row[1] == column
    )


def _head() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    bootstrap_prod1_schema(conn)
    return conn


def _v11_with_rows() -> sqlite3.Connection:
    """A v11 database holding 80 / 120 / 160 courses and matrices, with an
    AUTOINCREMENT gap left by a deleted row."""
    conn = _head()
    revert_prod1_v12_to_v11(conn)
    _validate_prod1_v11_schema(conn)
    for code, aeu in (("C-80", 80), ("C-120", 120), ("C-160", 160), ("C-GONE", 80)):
        conn.execute(
            "INSERT INTO cursos (nome,codigo,duracao_periodos,total_horas_aac,total_horas_aeu)"
            " VALUES (?,?,8,160,?)",
            (f"Curso {code}", code, aeu),
        )
    curso_id = conn.execute("SELECT id FROM cursos WHERE codigo='C-80'").fetchone()[0]
    for name, aeu in (("M-80", 80), ("M-120", 120), ("M-160", 160), ("M-GONE", 0)):
        conn.execute(
            "INSERT INTO matrizes_atividades (curso_id,nome,horas_aac_obrigatorias,horas_extensao_obrigatorias)"
            " VALUES (?,?,160,?)",
            (curso_id, name, aeu),
        )
    matriz_id = conn.execute("SELECT id FROM matrizes_atividades WHERE nome='M-80'").fetchone()[0]
    conn.execute(
        "INSERT INTO turmas (nome,codigo,numero,curso_id,matriz_id,status,ano_inicio,semestre_inicio)"
        " VALUES ('T','C-80-T01',1,?,?,'Ativa',2026,1)",
        (curso_id, matriz_id),
    )
    conn.execute("DELETE FROM cursos WHERE codigo='C-GONE'")
    conn.execute("DELETE FROM matrizes_atividades WHERE nome='M-GONE'")
    conn.commit()
    return conn


def _dump(conn) -> dict:
    out = {
        table: [tuple(row) for row in conn.execute(f'SELECT * FROM "{table}" ORDER BY 1')]
        for (table,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            " AND name<>'schema_migrations' ORDER BY name"
        )
    }
    out["sqlite_sequence"] = sorted(tuple(row) for row in conn.execute("SELECT name,seq FROM sqlite_sequence"))
    return out


# --- A. defaults for new rows --------------------------------------------------


def test_head_schema_and_constants_default_extension_to_160():
    conn = _head()
    # v13 only adds the image tables; without them the head is v12 exactly.
    assert SCHEMA_VERSION == 15
    shape = _head()
    revert_prod1_v13_to_v12(shape)
    assert _physical_schema_digest(shape) == _PROD1_V12_SIGNATURE_SHA256
    assert _column_default(conn, "cursos", "total_horas_aac") == "160"
    assert _column_default(conn, "cursos", "total_horas_aeu") == "160"
    assert _column_default(conn, "matrizes_atividades", "horas_aac_obrigatorias") == "160"
    assert _column_default(conn, "matrizes_atividades", "horas_extensao_obrigatorias") == "160"
    assert (DEFAULT_CURSO_TOTAL_HORAS_AAC, DEFAULT_CURSO_TOTAL_HORAS_AEU) == (160, 160)
    assert (DEFAULT_HORAS_ACADEMICA, DEFAULT_HORAS_EXTENSAO) == (160, 160)

    conn.execute("INSERT INTO cursos (nome,codigo,duracao_periodos) VALUES ('Novo','NOVO',8)")
    curso_id = conn.execute("SELECT id FROM cursos WHERE codigo='NOVO'").fetchone()[0]
    conn.execute("INSERT INTO matrizes_atividades (curso_id,nome) VALUES (?, 'Nova')", (curso_id,))
    assert conn.execute("SELECT total_horas_aac,total_horas_aeu FROM cursos").fetchone() == (160, 160)
    assert conn.execute(
        "SELECT horas_aac_obrigatorias,horas_extensao_obrigatorias FROM matrizes_atividades"
    ).fetchone() == (160, 160)


def test_nova_curso_and_the_bootstrap_course_get_160_160(tmp_path):
    with isolated_versioned_app_env(tmp_path, "b33-nova-curso.db") as env:
        login_admin(env["client"])
        response = env["client"].post(
            "/admin/cursos/adicionar",
            data={"nome": "Curso Novo", "codigo": "CURSO-NOVO", "duracao_periodos": "8", "status": "ativo"},
        )
        assert response.status_code == 302
        with main.app.app_context():
            conn = main.get_db_connection()
            assert tuple(conn.execute(
                "SELECT total_horas_aac,total_horas_aeu FROM cursos WHERE codigo='CURSO-NOVO'"
            ).fetchone()) == (160, 160)
            # init_db seeds "Geral" on an empty database from the constants.
            assert tuple(conn.execute(
                "SELECT total_horas_aac,total_horas_aeu FROM cursos WHERE codigo='GERAL'"
            ).fetchone()) == (160, 160)


# --- B. an explicit 80 stays 80 -------------------------------------------------


def test_an_explicitly_configured_80_is_kept(tmp_path):
    conn = _head()
    conn.execute(
        "INSERT INTO cursos (nome,codigo,duracao_periodos,total_horas_aeu) VALUES ('Oitenta','OITENTA',8,80)"
    )
    curso_id = conn.execute("SELECT id FROM cursos WHERE codigo='OITENTA'").fetchone()[0]
    conn.execute(
        "INSERT INTO matrizes_atividades (curso_id,nome,horas_extensao_obrigatorias) VALUES (?, 'M', 80)",
        (curso_id,),
    )
    assert conn.execute("SELECT total_horas_aeu FROM cursos WHERE id=?", (curso_id,)).fetchone()[0] == 80
    assert conn.execute("SELECT horas_extensao_obrigatorias FROM matrizes_atividades").fetchone()[0] == 80


# --- C. migration from v11 ------------------------------------------------------


def test_migration_keeps_every_value_and_changes_only_future_defaults():
    conn = _v11_with_rows()
    before = _dump(conn)
    assert _column_default(conn, "cursos", "total_horas_aeu") == "80"

    result = migrate_prod1_v11_to_v12(conn)

    assert result["schema_version"] == 12
    _validate_prod1_v12_schema(conn)
    assert _physical_schema_digest(conn) == _PROD1_V12_SIGNATURE_SHA256
    assert _dump(conn) == before  # every row, id and AUTOINCREMENT counter
    assert [
        row[0] for row in conn.execute("SELECT total_horas_aeu FROM cursos ORDER BY id")
    ] == [80, 120, 160]
    assert [
        row[0] for row in conn.execute("SELECT horas_extensao_obrigatorias FROM matrizes_atividades ORDER BY id")
    ] == [80, 120, 160]
    assert conn.execute(
        "SELECT version,name,details_json FROM schema_migrations WHERE version=12"
    ).fetchone() == (12, EXTENSION_HOURS_DEFAULT_MARKER, _V12_DETAILS_JSON)
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert {row[1] for row in conn.execute("PRAGMA index_list(matrizes_atividades)")} == {
        "idx_matrizes_status",
        "idx_matrizes_curso",
    }

    # New rows after the migration: 160, and the deleted ids are not reused.
    conn.execute("INSERT INTO cursos (nome,codigo,duracao_periodos) VALUES ('Depois','DEPOIS',8)")
    new = conn.execute("SELECT id,total_horas_aeu FROM cursos WHERE codigo='DEPOIS'").fetchone()
    assert new[1] == 160
    assert new[0] == max(seq for name, seq in before["sqlite_sequence"] if name == "cursos") + 1


def test_migration_does_not_invent_counters_for_tables_that_never_had_a_row():
    """INSERT...SELECT creates a sqlite_sequence row even when it copies
    nothing; the rebuild must not leave one behind for an empty table."""
    conn = _head()
    revert_prod1_v12_to_v11(conn)
    counters = "SELECT name,seq FROM sqlite_sequence WHERE name IN ('cursos','matrizes_atividades')"
    assert conn.execute(counters).fetchall() == []

    migrate_prod1_v11_to_v12(conn)

    assert conn.execute(counters).fetchall() == []


def test_migration_is_reversible_to_the_frozen_v11_contract():
    conn = _v11_with_rows()
    before = _dump(conn)
    migrate_prod1_v11_to_v12(conn)

    revert_prod1_v12_to_v11(conn)

    _validate_prod1_v11_schema(conn)
    assert _physical_schema_digest(conn) == _PROD1_V11_SIGNATURE_SHA256
    assert _dump(conn) == before


def test_migration_is_idempotent_through_the_dispatcher():
    conn = _v11_with_rows()
    first = bootstrap_prod1_schema(conn)
    snapshot = _dump(conn)
    second = bootstrap_prod1_schema(conn)
    assert first["schema_version"] == second["schema_version"] == 15
    assert _dump(conn) == snapshot
    assert len(conn.execute("SELECT * FROM schema_migrations").fetchall()) == 15
    with pytest.raises(Prod1SchemaError, match="prod-1/v11"):
        migrate_prod1_v11_to_v12(conn)


def test_a_failed_migration_leaves_v11_untouched(monkeypatch):
    conn = _v11_with_rows()
    before = _dump(conn)
    import app.prod1_schema as prod1_schema

    def _boom(_conn):
        raise Prod1SchemaError("injected failure after the rebuild")

    monkeypatch.setattr(prod1_schema, "_validate_prod1_v12_schema", _boom)
    with pytest.raises(Prod1SchemaError, match="injected"):
        migrate_prod1_v11_to_v12(conn)

    assert conn.execute("PRAGMA user_version").fetchone()[0] == 11
    assert _physical_schema_digest(conn) == _PROD1_V11_SIGNATURE_SHA256
    assert _dump(conn) == before
    assert bool(conn.execute("PRAGMA foreign_keys").fetchone()[0])


def test_bootstrap_and_migration_record_the_same_marker_text():
    assert _V12_DETAILS_JSON in PROD1_SCHEMA_SQL
    assert validate_prod1_schema(_head())["schema_version"] == 15


# --- D. no application path falls back to 80 -------------------------------------


def test_no_live_80_hour_extension_default_remains():
    """The only DEFAULT 80 left in application code is the historical v2->v3
    rebuild, which must reproduce the frozen v3 schema byte for byte."""
    hits = []
    for path in [PROJECT_ROOT / "main.py", *(PROJECT_ROOT / "app").rglob("*.py")]:
        if "__pycache__" in path.parts:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if re.search(r"INTEGER NOT NULL DEFAULT\s+80\b|HORAS_AEU\s*=\s*80\b", line):
                hits.append((path.relative_to(PROJECT_ROOT).as_posix(), line.strip()))
    assert hits == [
        (
            "app/prod1_schema.py",
            "horas_extensao_obrigatorias INTEGER NOT NULL DEFAULT 80 CHECK(horas_extensao_obrigatorias>=0),",
        )
    ]
    source = (PROJECT_ROOT / "app" / "prod1_schema.py").read_text(encoding="utf-8")
    v3_block = source[source.index("_MATRIZES_ATIVIDADES_V3_SQL = "):source.index("def migrate_prod1_v2_to_v3")]
    assert "DEFAULT 80" in v3_block


# --- E. hours calculations still read the matrix, never a default ------------------


def test_student_goal_still_comes_from_the_matrix_value(tmp_path):
    """A matrix that deliberately requires 80 h of Extensão still shows 80."""
    with isolated_versioned_app_env(tmp_path, "b33-student-goal.db") as env:
        with main.app.app_context():
            conn = main.get_db_connection()
            aluno = conn.execute(
                "SELECT a.usuario_id, COALESCE(a.matriz_id, t.matriz_id) AS matriz_id"
                "  FROM alunos a LEFT JOIN turmas t ON t.id=a.turma_id"
                " WHERE a.matricula='PPA.TESTE.0001'"
            ).fetchone()
            conn.execute(
                "UPDATE matrizes_atividades SET horas_aac_obrigatorias=160, horas_extensao_obrigatorias=80"
                " WHERE id=?",
                (aluno["matriz_id"],),
            )
            conn.commit()
        from tests.canonical_request_test_support import login_student

        login_student(env["client"])
        html = env["client"].get("/aluno/dashboard").get_data(as_text=True)
        assert "/240 h" in html
        assert "/80 h" in html
