from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "tools" / "d73d_normative_importer_dryrun.py"
FIXTURE_PATH = ROOT / "normative_fixtures" / "d73c_normative_fixture.yaml"
REAL_DB_PATH = ROOT / "database.db"


def _run_cli(*args: object, fixture_path: Path = FIXTURE_PATH) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(SCRIPT_PATH),
        "--fixture",
        str(fixture_path),
        *[str(arg) for arg in args],
    ]
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    return subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )


def _database_signature(path: Path) -> tuple[int, str] | None:
    if not path.exists():
        return None
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return path.stat().st_size, digest


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def test_cli_reads_yaml_and_preserves_real_database_signature():
    before_signature = _database_signature(REAL_DB_PATH)

    result = _run_cli()

    assert result.returncode == 0, result.stderr
    assert "Status: ok" in result.stdout
    assert "Normas: inseridas=3 skipped=0 final=3" in result.stdout
    assert "Versoes: inseridas=61 skipped=0 final=61" in result.stdout

    after_signature = _database_signature(REAL_DB_PATH)
    assert after_signature == before_signature


def test_json_cli_populates_isolated_db_with_expected_counts_and_constraints(tmp_path):
    db_path = tmp_path / "normative_dryrun.sqlite3"

    result = _run_cli("--db", db_path, "--report", "json")

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "ok"
    assert report["inserted"] == {
        "normas": 3,
        "bases": 32,
        "versoes": 61,
        "transicoes": 1,
    }
    assert report["skipped"] == {
        "normas": 0,
        "bases": 0,
        "versoes": 0,
        "transicoes": 0,
    }
    assert report["final_counts"] == {
        "norma_atividade": 3,
        "atividade_base": 32,
        "atividade_versao": 61,
        "atividade_transicao": 1,
    }
    assert report["db"]["temporary"] is False
    assert report["db"]["cleaned_up"] is False

    with _connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM norma_atividade").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM atividade_base").fetchone()[0] == 32
        assert conn.execute("SELECT COUNT(*) FROM atividade_versao").fetchone()[0] == 61
        assert conn.execute("SELECT COUNT(*) FROM atividade_transicao").fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM atividade_versao WHERE status <> 'rascunho'"
        ).fetchone()[0] == 0

        removed_expectations = {
            "Trabalho voluntário em organizações do terceiro setor": "AAC-rev6",
            "Horas de voo em simulador": "AAC-rev6",
        }
        for activity_name, norma_codigo in removed_expectations.items():
            total = conn.execute(
                """
                SELECT COUNT(*)
                  FROM atividade_versao av
                  JOIN atividade_base ab ON ab.id = av.atividade_base_id
                  JOIN norma_atividade na ON na.id = av.norma_id
                 WHERE ab.nome_conceito = ? AND na.codigo = ?
                """,
                (activity_name, norma_codigo),
            ).fetchone()[0]
            assert total == 0

        new_activity_names = [
            "Organização de eventos extensionistas",
            "Participação em eventos extensionistas",
            "Cursos, oficinas ou palestras oferecidos à comunidade externa",
        ]
        for activity_name in new_activity_names:
            normas = {
                row["codigo"]
                for row in conn.execute(
                    """
                    SELECT na.codigo
                      FROM atividade_versao av
                      JOIN atividade_base ab ON ab.id = av.atividade_base_id
                      JOIN norma_atividade na ON na.id = av.norma_id
                     WHERE ab.nome_conceito = ?
                    """,
                    (activity_name,),
                ).fetchall()
            }
            assert normas == {"AEU-rev1"}

        transition = conn.execute(
            """
            SELECT
                src.eixo AS from_eixo,
                dst.eixo AS to_eixo,
                src.atividade_base_id AS from_base_id,
                dst.atividade_base_id AS to_base_id
              FROM atividade_transicao t
              JOIN atividade_versao src ON src.id = t.from_atividade_versao_id
              JOIN atividade_versao dst ON dst.id = t.to_atividade_versao_id
            """
        ).fetchone()
        assert transition["from_eixo"] == "AAC"
        assert transition["to_eixo"] == "AEU"
        assert transition["from_base_id"] == transition["to_base_id"]

        assert conn.execute(
            """
            SELECT COUNT(*)
              FROM atividade_versao av
              JOIN norma_atividade na ON na.id = av.norma_id
             WHERE av.eixo <> na.eixo
            """
        ).fetchone()[0] == 0


def test_import_is_idempotent_on_same_explicit_db(tmp_path):
    db_path = tmp_path / "idempotent_dryrun.sqlite3"

    first_result = _run_cli("--db", db_path, "--report", "json")
    second_result = _run_cli("--db", db_path, "--report", "json")

    assert first_result.returncode == 0, first_result.stderr
    assert second_result.returncode == 0, second_result.stderr

    second_report = json.loads(second_result.stdout)
    assert second_report["inserted"] == {
        "normas": 0,
        "bases": 0,
        "versoes": 0,
        "transicoes": 0,
    }
    assert second_report["skipped"] == {
        "normas": 3,
        "bases": 32,
        "versoes": 61,
        "transicoes": 1,
    }
    assert second_report["final_counts"] == {
        "norma_atividade": 3,
        "atividade_base": 32,
        "atividade_versao": 61,
        "atividade_transicao": 1,
    }


def test_invalid_fixture_aborts_without_partial_insertion(tmp_path):
    broken_fixture_path = tmp_path / "invalid_fixture.yaml"
    target_db_path = tmp_path / "invalid_fixture.sqlite3"

    fixture_data = yaml.safe_load(FIXTURE_PATH.read_text(encoding="utf-8"))
    fixture_data["atividades"][0]["versoes"][0]["ch_regra_condicional"] = "vocabulário_invalido"
    broken_fixture_path.write_text(
        yaml.safe_dump(fixture_data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    result = _run_cli("--db", target_db_path, fixture_path=broken_fixture_path)

    assert result.returncode != 0
    assert "ch_regra_condicional inválido" in result.stderr

    if target_db_path.exists():
        with _connect(target_db_path) as conn:
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            relevant_tables = {
                "norma_atividade",
                "atividade_base",
                "atividade_versao",
                "atividade_transicao",
            }
            assert not (tables & relevant_tables)


def test_cli_rejects_any_db_target_named_database_db(tmp_path):
    forbidden_path = tmp_path / "database.db"

    result = _run_cli("--db", forbidden_path)

    assert result.returncode != 0
    assert "database.db" in result.stderr
    assert not forbidden_path.exists()
