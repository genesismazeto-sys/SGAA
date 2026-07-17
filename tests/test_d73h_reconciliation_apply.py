from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "tools" / "d73h_reconciliation_apply.py"
FIXTURE_PATH = ROOT / "normative_fixtures" / "d73c_normative_fixture.yaml"
TARGET_ACTIVITY_NAME = "Visitas técnicas ou cursos coordenados pelos professores"


def _run_cli(*args: object, fixture_path: Path = FIXTURE_PATH) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(SCRIPT_PATH),
        "--fixture",
        str(fixture_path),
        *[str(arg) for arg in args],
    ]
    return subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _database_signature(path: Path) -> tuple[int, str]:
    return path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _remove_target_from_copy(path: Path) -> None:
    with _connect(path) as conn:
        base_rows = conn.execute(
            """
            SELECT id, status
              FROM atividade_base
             WHERE nome_conceito = ?
            """,
            (TARGET_ACTIVITY_NAME,),
        ).fetchall()
        if not base_rows:
            return

        assert len(base_rows) == 1
        base_id = base_rows[0]["id"]
        version_rows = conn.execute(
            """
            SELECT id, codigo_normativo, eixo, status
              FROM atividade_versao
             WHERE atividade_base_id = ?
             ORDER BY id
            """,
            (base_id,),
        ).fetchall()
        assert len(version_rows) == 2
        assert [row["codigo_normativo"] for row in version_rows] == ["AAC-rev5", "AAC-rev6"]
        assert {row["eixo"] for row in version_rows} == {"AAC"}
        assert {row["status"] for row in version_rows} == {"rascunho"}

        version_ids = [row["id"] for row in version_rows]
        placeholders = ",".join("?" for _ in version_ids)
        matrix_count = conn.execute(
            f"SELECT COUNT(*) FROM matriz_atividade_versao_item WHERE atividade_versao_id IN ({placeholders})",
            version_ids,
        ).fetchone()[0]
        req_count = conn.execute(
            f"SELECT COUNT(*) FROM requisicoes WHERE atividade_versao_id IN ({placeholders})",
            version_ids,
        ).fetchone()[0]
        transition_count = conn.execute(
            f"""
            SELECT COUNT(*)
              FROM atividade_transicao
             WHERE from_atividade_versao_id IN ({placeholders})
                OR to_atividade_versao_id IN ({placeholders})
            """,
            [*version_ids, *version_ids],
        ).fetchone()[0]
        assert matrix_count == 0
        assert req_count == 0
        assert transition_count == 0

        conn.execute(f"DELETE FROM atividade_versao WHERE id IN ({placeholders})", version_ids)
        conn.execute("DELETE FROM atividade_base WHERE id = ?", (base_id,))
        conn.commit()


def _prepare_copy_and_backup(tmp_path: Path, source_db: Path, source_backup: Path) -> tuple[Path, Path]:
    db_copy = tmp_path / "apply_target.sqlite3"
    backup = tmp_path / "apply_backup.sqlite3"
    shutil.copy2(source_db, db_copy)
    shutil.copy2(source_backup, backup)
    _remove_target_from_copy(db_copy)
    _remove_target_from_copy(backup)
    return db_copy, backup


def _table_count(path: Path, table_name: str) -> int:
    with _connect(path) as conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])


def _runtime_snapshot(path: Path) -> list[dict[str, object]]:
    with _connect(path) as conn:
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT
                    av.id,
                    ab.nome_conceito AS base_nome,
                    n.codigo AS norma_codigo,
                    av.status
                  FROM atividade_versao av
                  JOIN atividade_base ab ON ab.id = av.atividade_base_id
                  JOIN norma_atividade n ON n.id = av.norma_id
                 WHERE n.codigo LIKE 'NRM-RT%' OR ab.nome_conceito LIKE 'Runtime Base%'
                 ORDER BY av.id
                """
            ).fetchall()
        ]


def _run_apply(db_copy: Path, backup: Path) -> subprocess.CompletedProcess[str]:
    return _run_cli(
        "--db-copy",
        db_copy,
        "--apply",
        "--backup-path",
        backup,
        "--backup-confirmed",
        "--allow-create-visitas-professores",
        "--report",
        "json",
    )


def _prepare_post_apply_copy_and_backup(tmp_path: Path, source_db: Path, source_backup: Path) -> tuple[Path, Path, dict[str, object]]:
    db_copy, backup = _prepare_copy_and_backup(tmp_path, source_db, source_backup)
    result = _run_apply(db_copy, backup)
    assert result.returncode == 0, result.stderr
    return db_copy, backup, json.loads(result.stdout)


@pytest.mark.d73h_historical
def test_plan_mode_does_not_alter_live_database_signature(d73h_sources):
    source_path = d73h_sources["source_db"]
    before_signature = _database_signature(source_path)

    result = _run_cli("--db-copy", source_path, "--plan")

    assert result.returncode == 0, result.stderr
    assert "Status: ok" in result.stdout
    after_signature = _database_signature(source_path)
    assert after_signature == before_signature


@pytest.mark.d73h_historical
def test_plan_mode_json_reports_one_base_and_two_versions_planned(tmp_path, d73h_sources):
    db_copy, _backup = _prepare_copy_and_backup(tmp_path, d73h_sources["source_db"], d73h_sources["source_backup"])

    result = _run_cli("--db-copy", db_copy, "--plan", "--report", "json")

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "ok"
    assert report["mode"] == "plan"
    assert report["disposition"] == "create"
    assert report["planned_counts"] == {
        "atividade_base": 1,
        "atividade_versao": 2,
    }
    tables = [action["table"] for action in report["planned_actions"]]
    assert tables.count("atividade_base") == 1
    assert tables.count("atividade_versao") == 2


@pytest.mark.d73h_historical
def test_plan_mode_json_reports_already_exists_on_controlled_post_apply_copy(tmp_path, d73h_sources):
    db_copy, _backup, _first_report = _prepare_post_apply_copy_and_backup(tmp_path, d73h_sources["source_db"], d73h_sources["source_backup"])

    result = _run_cli("--db-copy", db_copy, "--plan", "--report", "json")

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "ok"
    assert report["mode"] == "plan"
    assert report["disposition"] in {"already_exists", "noop", "skipped"}
    assert report["planned_counts"] == {
        "atividade_base": 0,
        "atividade_versao": 0,
    }
    assert report["planned_actions"] == []


@pytest.mark.d73h_historical
def test_apply_refuses_without_backup_confirmed(tmp_path, d73h_sources):
    db_copy, backup = _prepare_copy_and_backup(tmp_path, d73h_sources["source_db"], d73h_sources["source_backup"])

    result = _run_cli(
        "--db-copy",
        db_copy,
        "--apply",
        "--backup-path",
        backup,
        "--allow-create-visitas-professores",
    )

    assert result.returncode != 0
    assert "--backup-confirmed" in result.stderr


@pytest.mark.d73h_historical
def test_apply_refuses_without_backup_path(tmp_path, d73h_sources):
    db_copy, _backup = _prepare_copy_and_backup(tmp_path, d73h_sources["source_db"], d73h_sources["source_backup"])

    result = _run_cli(
        "--db-copy",
        db_copy,
        "--apply",
        "--backup-confirmed",
        "--allow-create-visitas-professores",
    )

    assert result.returncode != 0
    assert "--backup-path" in result.stderr


@pytest.mark.d73h_historical
def test_apply_refuses_without_allow_create_flag(tmp_path, d73h_sources):
    db_copy, backup = _prepare_copy_and_backup(tmp_path, d73h_sources["source_db"], d73h_sources["source_backup"])

    result = _run_cli(
        "--db-copy",
        db_copy,
        "--apply",
        "--backup-path",
        backup,
        "--backup-confirmed",
    )

    assert result.returncode != 0
    assert "--allow-create-visitas-professores" in result.stderr


@pytest.mark.d73h_historical
def test_apply_refuses_live_db_and_forbidden_database_db_basename(tmp_path, d73h_sources):
    from tools.d73h_reconciliation_apply import connect_apply_copy, GuardRailError

    source_db = d73h_sources["source_db"]
    source_backup = d73h_sources["source_backup"]

    tmp_db = tmp_path / "test.sqlite3"
    shutil.copy2(source_db, tmp_db)
    with pytest.raises(GuardRailError, match="live database"):
        connect_apply_copy(tmp_db, live_db_path=tmp_db)

    forbidden_copy = tmp_path / "database.db"
    forbidden_backup = tmp_path / "backup.sqlite3"
    shutil.copy2(source_db, forbidden_copy)
    shutil.copy2(source_backup, forbidden_backup)
    forbidden_result = _run_cli(
        "--db-copy",
        forbidden_copy,
        "--apply",
        "--backup-path",
        forbidden_backup,
        "--backup-confirmed",
        "--allow-create-visitas-professores",
    )

    assert forbidden_result.returncode != 0
    assert "basename 'database.db'" in forbidden_result.stderr


@pytest.mark.d73h_historical
def test_apply_on_copy_creates_exactly_one_base_and_two_versions_and_reports_created_ids(tmp_path, d73h_sources):
    db_copy, backup = _prepare_copy_and_backup(tmp_path, d73h_sources["source_db"], d73h_sources["source_backup"])

    result = _run_apply(db_copy, backup)

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "ok"
    assert report["mode"] == "apply"
    assert report["created_ids"]["atividade_base"] is not None
    assert len(report["created_ids"]["atividade_versao"]) == 2
    assert report["after_counts"]["atividade_base"] == report["before_counts"]["atividade_base"] + 1
    assert report["after_counts"]["atividade_versao"] == report["before_counts"]["atividade_versao"] + 2
    assert report["final_counts"] == report["after_counts"]

    with _connect(db_copy) as conn:
        base_rows = conn.execute(
            """
            SELECT id, nome_conceito, descricao, status
              FROM atividade_base
             WHERE nome_conceito = ?
            """,
            (TARGET_ACTIVITY_NAME,),
        ).fetchall()
        assert len(base_rows) == 1
        base_id = base_rows[0]["id"]
        assert base_id == report["created_ids"]["atividade_base"]
        version_rows = conn.execute(
            """
            SELECT av.id, av.norma_id, n.codigo AS norma_codigo, av.status, av.eixo
              FROM atividade_versao av
              JOIN norma_atividade n ON n.id = av.norma_id
             WHERE av.atividade_base_id = ?
             ORDER BY av.id
            """,
            (base_id,),
        ).fetchall()
        assert [row["id"] for row in version_rows] == report["created_ids"]["atividade_versao"]
        assert [row["norma_codigo"] for row in version_rows] == ["AAC-rev5", "AAC-rev6"]
        assert [row["norma_id"] for row in version_rows] == [1, 2]
        assert {row["status"] for row in version_rows} == {"rascunho"}
        assert {row["eixo"] for row in version_rows} == {"AAC"}


@pytest.mark.d73h_historical
def test_apply_does_not_alter_norma_atividade(tmp_path, d73h_sources):
    db_copy, backup = _prepare_copy_and_backup(tmp_path, d73h_sources["source_db"], d73h_sources["source_backup"])
    before_count = _table_count(db_copy, "norma_atividade")

    result = _run_apply(db_copy, backup)

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["after_counts"]["norma_atividade"] == before_count
    assert _table_count(db_copy, "norma_atividade") == before_count


@pytest.mark.d73h_historical
def test_apply_does_not_alter_atividade_transicao(tmp_path, d73h_sources):
    db_copy, backup = _prepare_copy_and_backup(tmp_path, d73h_sources["source_db"], d73h_sources["source_backup"])
    before_count = _table_count(db_copy, "atividade_transicao")

    result = _run_apply(db_copy, backup)

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["after_counts"]["atividade_transicao"] == before_count
    assert _table_count(db_copy, "atividade_transicao") == before_count


@pytest.mark.d73h_historical
def test_apply_does_not_alter_matriz_atividade_versao_item(tmp_path, d73h_sources):
    db_copy, backup = _prepare_copy_and_backup(tmp_path, d73h_sources["source_db"], d73h_sources["source_backup"])
    before_count = _table_count(db_copy, "matriz_atividade_versao_item")

    result = _run_apply(db_copy, backup)

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["after_counts"]["matriz_atividade_versao_item"] == before_count
    assert _table_count(db_copy, "matriz_atividade_versao_item") == before_count


@pytest.mark.d73h_historical
def test_apply_does_not_alter_requisicoes(tmp_path, d73h_sources):
    db_copy, backup = _prepare_copy_and_backup(tmp_path, d73h_sources["source_db"], d73h_sources["source_backup"])
    before_count = _table_count(db_copy, "requisicoes")

    result = _run_apply(db_copy, backup)

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["after_counts"]["requisicoes"] == before_count
    assert _table_count(db_copy, "requisicoes") == before_count


@pytest.mark.d73h_historical
def test_apply_does_not_touch_runtime_nrm_rt_items(tmp_path, d73h_sources):
    db_copy, backup = _prepare_copy_and_backup(tmp_path, d73h_sources["source_db"], d73h_sources["source_backup"])
    before_runtime = _runtime_snapshot(db_copy)

    result = _run_apply(db_copy, backup)

    assert result.returncode == 0, result.stderr
    after_runtime = _runtime_snapshot(db_copy)
    assert after_runtime == before_runtime


@pytest.mark.d73h_historical
def test_apply_json_report_contains_created_ids_and_final_counts(tmp_path, d73h_sources):
    db_copy, backup = _prepare_copy_and_backup(tmp_path, d73h_sources["source_db"], d73h_sources["source_backup"])

    result = _run_apply(db_copy, backup)

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert "created_ids" in report
    assert "after_counts" in report
    assert "final_counts" in report
    assert report["final_counts"] == report["after_counts"]
    assert report["created_ids"]["atividade_base"] is not None
    assert len(report["created_ids"]["atividade_versao"]) == 2


@pytest.mark.d73h_historical
def test_apply_is_idempotent_on_same_copy(tmp_path, d73h_sources):
    db_copy, backup = _prepare_copy_and_backup(tmp_path, d73h_sources["source_db"], d73h_sources["source_backup"])

    first_result = _run_apply(db_copy, backup)
    second_result = _run_apply(db_copy, backup)

    assert first_result.returncode == 0, first_result.stderr
    assert second_result.returncode == 0, second_result.stderr

    second_report = json.loads(second_result.stdout)
    assert second_report["status"] == "ok"
    assert second_report["noop"] is True
    assert second_report["after_counts"] == second_report["before_counts"]
    assert second_report["planned_counts"] == {
        "atividade_base": 0,
        "atividade_versao": 0,
    }


@pytest.mark.d73h_historical
def test_apply_fails_if_existing_target_base_is_conflicting(tmp_path, d73h_sources):
    db_copy, backup = _prepare_copy_and_backup(tmp_path, d73h_sources["source_db"], d73h_sources["source_backup"])

    with _connect(db_copy) as conn:
        conn.execute(
            """
            INSERT INTO atividade_base (nome_conceito, descricao, status)
            VALUES (?, ?, 'ativo')
            """,
            (
                TARGET_ACTIVITY_NAME,
                "Descrição conflitante",
            ),
        )
        conn.commit()

    result = _run_apply(db_copy, backup)

    assert result.returncode != 0
    assert "conflicting" in result.stderr.lower() or "partial" in result.stderr.lower()


@pytest.mark.d73h_historical
def test_apply_fails_if_fixture_is_missing_target_activity(tmp_path, d73h_sources):
    broken_fixture = tmp_path / "broken_fixture.yaml"
    data = yaml.safe_load(FIXTURE_PATH.read_text(encoding="utf-8"))
    data["atividades"] = [
        item for item in data["atividades"] if item.get("codigo_atividade") != "VISITAS_TECNICAS_PROFESSORES"
    ]
    broken_fixture.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    db_copy, backup = _prepare_copy_and_backup(tmp_path, d73h_sources["source_db"], d73h_sources["source_backup"])

    result = _run_cli(
        "--db-copy",
        db_copy,
        "--apply",
        "--backup-path",
        backup,
        "--backup-confirmed",
        "--allow-create-visitas-professores",
        fixture_path=broken_fixture,
    )

    assert result.returncode != 0
    assert "VISITAS_TECNICAS_PROFESSORES" in result.stderr


def test_cli_refuses_unknown_force_flag_as_out_of_scope_operation(tmp_path):
    dummy_path = tmp_path / "dummy.sqlite3"
    result = _run_cli("--db-copy", dummy_path, "--plan", "--force")

    assert result.returncode != 0
    assert "unrecognized arguments: --force" in result.stderr
