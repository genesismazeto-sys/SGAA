"""First-production baseline: schema, epoch, Matrix, snapshot and status contracts."""

import hashlib
import json
import sqlite3

import pytest

from app.db_maintenance import create_database_snapshot, restore_database_snapshot
from app.prod1_schema import (
    EXPECTED_TABLES,
    LEGACY_INDEXES,
    LEGACY_TABLES,
    REQUEST_STATUSES,
    SCHEMA_EPOCH,
    SCHEMA_VERSION,
    Prod1SchemaError,
    bootstrap_prod1_schema,
    validate_prod1_schema,
)


def _connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _signature(path):
    return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_size


def _seed_graph(conn):
    course = conn.execute(
        "INSERT INTO cursos(nome,codigo,duracao_periodos) VALUES('Curso','PG',8) RETURNING id"
    ).fetchone()[0]
    matrix = conn.execute(
        "INSERT INTO matrizes_atividades(curso_id,nome) VALUES(?,'Matriz') RETURNING id", (course,)
    ).fetchone()[0]
    base = conn.execute("INSERT INTO atividade_base(nome_conceito) VALUES('Pesquisa') RETURNING id").fetchone()[0]
    other = conn.execute("INSERT INTO atividade_base(nome_conceito) VALUES('Extensão') RETURNING id").fetchone()[0]
    v1 = conn.execute(
        "INSERT INTO atividade_versao(atividade_base_id,eixo,grupo,status,numero_versao) VALUES(?,'AAC','1','ativa',1) RETURNING id",
        (base,),
    ).fetchone()[0]
    v2 = conn.execute(
        "INSERT INTO atividade_versao(atividade_base_id,eixo,grupo,status,numero_versao) VALUES(?,'AAC','1','ativa',2) RETURNING id",
        (base,),
    ).fetchone()[0]
    wrong = conn.execute(
        "INSERT INTO atividade_versao(atividade_base_id,eixo,grupo,status,numero_versao) VALUES(?,'AAC','2','ativa',1) RETURNING id",
        (other,),
    ).fetchone()[0]
    return matrix, base, other, v1, v2, wrong


def test_empty_bootstrap_is_prod1_and_idempotent(tmp_path):
    conn = _connect(tmp_path / "prod1.db")
    first = bootstrap_prod1_schema(conn)
    second = bootstrap_prod1_schema(conn)
    assert first == second
    assert first == {"schema_epoch": "prod-1", "schema_version": 3, "baseline_marker": "first_production_baseline", "table_count": 26}
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    indexes = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert tables == EXPECTED_TABLES
    assert not tables & LEGACY_TABLES
    assert not indexes & LEGACY_INDEXES


@pytest.mark.parametrize("version", [1, 2, 3])
def test_nonempty_development_database_is_rejected_without_mutation(tmp_path, version):
    path = tmp_path / f"development-v{version}.db"
    conn = _connect(path)
    conn.execute("CREATE TABLE atividades(id INTEGER PRIMARY KEY, nome TEXT)")
    conn.execute(f"PRAGMA user_version={version}")
    conn.commit()
    before = _signature(path)
    with pytest.raises(Prod1SchemaError):
        bootstrap_prod1_schema(conn)
    conn.close()
    assert _signature(path) == before


def test_unknown_epoch_is_rejected_without_mutation(tmp_path):
    path = tmp_path / "unknown.db"
    conn = _connect(path)
    bootstrap_prod1_schema(conn)
    conn.execute("UPDATE schema_migrations SET schema_epoch='future-2'")
    conn.commit()
    before = _signature(path)
    with pytest.raises(Prod1SchemaError):
        validate_prod1_schema(conn)
    conn.close()
    assert _signature(path) == before


def test_exact_matrix_version_and_base_membership_constraints(tmp_path):
    conn = _connect(tmp_path / "matrix.db")
    bootstrap_prod1_schema(conn)
    matrix, base, other, v1, v2, wrong = _seed_graph(conn)
    conn.execute("INSERT INTO matriz_atividade_versao_item(matriz_id,atividade_base_id,atividade_versao_id) VALUES(?,?,?)", (matrix, base, v1))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO matriz_atividade_versao_item(matriz_id,atividade_base_id,atividade_versao_id) VALUES(?,?,?)", (matrix, base, v2))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO matriz_atividade_versao_item(matriz_id,atividade_base_id,atividade_versao_id) VALUES(?,?,?)", (matrix, base, wrong))


def test_request_requires_version_and_valid_immutable_snapshot(tmp_path):
    conn = _connect(tmp_path / "request.db")
    bootstrap_prod1_schema(conn)
    _, _, _, version, _, _ = _seed_graph(conn)
    snapshot = json.dumps({"schema_version": "prod-1-request-v2"})
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO requisicoes(data_solicitacao,data_evento,horas_solicitadas,status,regra_snapshot_json) VALUES('2026-01-01','2026-01-01',1,'Pendente',?)", (snapshot,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO requisicoes(atividade_versao_id,data_solicitacao,data_evento,horas_solicitadas,status,regra_snapshot_json) VALUES(?,'2026-01-01','2026-01-01',1,'Pendente','not-json')", (version,))
    request_id = conn.execute("INSERT INTO requisicoes(atividade_versao_id,data_solicitacao,data_evento,horas_solicitadas,status,regra_snapshot_json) VALUES(?,'2026-01-01','2026-01-01',1,'Pendente',?) RETURNING id", (version, snapshot)).fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE requisicoes SET regra_snapshot_json='{}' WHERE id=?", (request_id,))


def test_database_and_application_status_contract_are_exact(tmp_path):
    conn = _connect(tmp_path / "status.db")
    bootstrap_prod1_schema(conn)
    _, _, _, version, _, _ = _seed_graph(conn)
    for status in REQUEST_STATUSES:
        conn.execute("INSERT INTO requisicoes(atividade_versao_id,data_solicitacao,data_evento,horas_solicitadas,status,regra_snapshot_json) VALUES(?,'2026-01-01','2026-01-01',1,?,'{}')", (version, status))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO requisicoes(atividade_versao_id,data_solicitacao,data_evento,horas_solicitadas,status,regra_snapshot_json) VALUES(?,'2026-01-01','2026-01-01',1,'Cancelada','{}')", (version,))


def test_backup_and_restore_accept_only_current_prod1(tmp_path):
    source = tmp_path / "source.db"
    conn = _connect(source)
    bootstrap_prod1_schema(conn)
    conn.close()
    result = create_database_snapshot(str(source), str(tmp_path / "backups"))
    assert result["schema_epoch"] == SCHEMA_EPOCH
    assert result["schema_version"] == SCHEMA_VERSION
    restored = tmp_path / "restored.db"
    restore_database_snapshot(result["database_path"], str(restored))
    restored_conn = _connect(restored)
    assert validate_prod1_schema(restored_conn)["schema_epoch"] == SCHEMA_EPOCH
    restored_conn.close()


def test_restore_rejects_incompatible_source_before_target_mutation(tmp_path):
    source, target = tmp_path / "legacy.db", tmp_path / "target.bin"
    conn = _connect(source)
    conn.execute("CREATE TABLE atividades(id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    target.write_bytes(b"unchanged-target")
    before = target.read_bytes()
    with pytest.raises(Prod1SchemaError):
        restore_database_snapshot(str(source), str(target))
    assert target.read_bytes() == before
