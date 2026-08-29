from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

import main
from app.prod1_schema import bootstrap_prod1_schema
from app.versioning.snapshots import (
    SnapshotProcessingAuthority,
    prepare_versioned_requisicao_snapshot,
    read_requisicao_snapshot_for_processing,
)
from tests.canonical_matrix_test_support import current_version_id, login_admin, seed_matrix_graph
from tests.versioned_test_support import isolated_versioned_app_env


REMOVED_SCHEMA_NAMES = {"norma_atividade", "matriz_norma"}
REMOVED_FIELDS = {"norma_id", "codigo_normativo", "codigo_normativo_snapshot"}
REMOVED_RUNTIME_TERMS = (
    "norma_atividade",
    "matriz_norma",
    "norma_id",
    "codigo_normativo",
    "aac-rev",
    "aeu-rev",
    "normas-atividade",
    "normas aplicáveis",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_prod1_v2_has_no_norma_schema_or_routes(tmp_path):
    with isolated_versioned_app_env(tmp_path, "schema-v2.db") as env:
        with main.app.app_context():
            conn = main.get_db_connection()
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            assert not tables & REMOVED_SCHEMA_NAMES
            assert REMOVED_FIELDS.isdisjoint({row[1] for row in conn.execute("PRAGMA table_info(atividade_versao)")})
            assert "codigo_normativo_snapshot" not in {row[1] for row in conn.execute("PRAGMA table_info(requisicoes)")}
            assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
        assert env["client"].get("/admin/normas-atividade").status_code == 404
        assert env["client"].get("/admin/normas-atividade/nova").status_code == 404


def test_runtime_and_ui_sources_have_no_removed_norma_authority():
    root = Path(main.__file__).resolve().parent
    runtime_paths = [root / "main.py"]
    for directory in (root / "app", root / "templates", root / "tools"):
        runtime_paths.extend(path for path in directory.rglob("*") if path.suffix in {".py", ".html", ".js"})
    runtime_paths.remove(root / "app" / "prod1_schema.py")

    residuals = {}
    for path in runtime_paths:
        text = path.read_text(encoding="utf-8").casefold()
        hits = [term for term in REMOVED_RUNTIME_TERMS if term in text]
        if hits:
            residuals[str(path.relative_to(root))] = hits
    assert residuals == {}

    migration_source = (root / "app" / "prod1_schema.py").read_text(encoding="utf-8").casefold()
    assert "drop table matriz_norma" in migration_source
    assert "drop table norma_atividade" in migration_source


def test_activity_version_creation_preserves_axis_number_and_lineage(tmp_path):
    with isolated_versioned_app_env(tmp_path, "activity-v2.db") as env:
        client = env["client"]
        login_admin(client)
        with main.app.app_context():
            conn = main.get_db_connection()
            base_id = conn.execute(
                "INSERT INTO atividade_base(nome_conceito,status) VALUES('Sem dominio regulatorio','ativo') RETURNING id"
            ).fetchone()[0]
            conn.commit()
        first = client.post(
            f"/admin/catalogo-versoes/{base_id}/nova-versao",
            data={"eixo": "AEU", "grupo": "NA", "ch_por_evento": "4"},
        )
        assert first.status_code == 302
        with main.app.app_context():
            conn = main.get_db_connection()
            v1 = conn.execute("SELECT * FROM atividade_versao WHERE atividade_base_id=?", (base_id,)).fetchone()
            assert (v1["numero_versao"], v1["eixo"], v1["versao_anterior_id"]) == (1, "AEU", None)
        second = client.post(
            f"/admin/catalogo-versoes/{base_id}/nova-versao",
            data={
                "eixo": "AAC",
                "grupo": "NA",
                "ch_por_evento": "6",
                "versao_anterior_id": str(v1["id"]),
            },
        )
        assert second.status_code == 302
        with main.app.app_context():
            rows = main.get_db_connection().execute(
                "SELECT * FROM atividade_versao WHERE atividade_base_id=? ORDER BY numero_versao", (base_id,)
            ).fetchall()
            assert [(row["numero_versao"], row["eixo"]) for row in rows] == [(1, "AEU"), (2, "AEU")]
            assert rows[1]["versao_anterior_id"] == rows[0]["id"]


def test_matrix_exact_version_relink_axis_status_and_freeze(tmp_path):
    with isolated_versioned_app_env(tmp_path, "matrix-v2.db") as env:
        client = env["client"]
        login_admin(client)
        with main.app.app_context():
            conn = main.get_db_connection()
            seed = seed_matrix_graph(conn, name="Remove domain matrix")
            wrong_axis = conn.execute(
                """INSERT INTO atividade_versao
                       (atividade_base_id,eixo,grupo,numero_versao,status)
                     VALUES (?,'AEU','NA',4,'ativa') RETURNING id""",
                (seed["base_id"],),
            ).fetchone()[0]
            conn.commit()

        endpoint = f"/admin/matrizes/{seed['matrix_id']}/versoes/definir"
        assert client.post(endpoint, data={"base_id": seed["base_id"], "versao_id": seed["v2"]}).status_code == 302
        with main.app.app_context():
            assert current_version_id(main.get_db_connection(), seed) == seed["v2"]
        client.post(endpoint, data={"base_id": seed["base_id"], "versao_id": seed["v3_inactive"]})
        client.post(endpoint, data={"base_id": seed["base_id"], "versao_id": wrong_axis})
        with main.app.app_context():
            conn = main.get_db_connection()
            assert current_version_id(conn, seed) == seed["v2"]
            conn.execute(
                """INSERT INTO turmas
                       (nome,status,numero,curso_id,ano_inicio,semestre_inicio,codigo,matriz_id)
                     VALUES ('Frozen Matrix','Ativa',991,?,2026,1,'FROZEN-991',?)""",
                (seed["course_id"], seed["matrix_id"]),
            )
            conn.commit()
        client.post(endpoint, data={"base_id": seed["base_id"], "versao_id": seed["v1"]})
        with main.app.app_context():
            assert current_version_id(main.get_db_connection(), seed) == seed["v2"]


def test_request_snapshot_is_exact_version_snapshot_only_and_norma_free(tmp_path):
    with isolated_versioned_app_env(tmp_path, "snapshot-v2.db"):
        with main.app.app_context():
            conn = main.get_db_connection()
            aluno_id = conn.execute("SELECT id FROM alunos WHERE matricula='PPA.TESTE.0001'").fetchone()[0]
            prepared = prepare_versioned_requisicao_snapshot(
                conn, flow_origin="canonical_test", aluno_id=aluno_id, atividade_versao_id=29
            )
            payload = prepared.payload
            assert payload["schema_version"] == "prod-1-request-v2"
            assert REMOVED_FIELDS.isdisjoint(payload)
            assert payload["atividade_versao_id"] == 29
            frozen = json.loads(prepared.snapshot_json)
            conn.execute("UPDATE atividade_versao SET limite_total=999 WHERE id=29")
            assert json.loads(prepared.snapshot_json) == frozen
            read = read_requisicao_snapshot_for_processing(
                {"atividade_versao_id": 29, "regra_snapshot_json": prepared.snapshot_json}
            )
            assert read.authority is SnapshotProcessingAuthority.VALID_AUTHORITATIVE_SNAPSHOT
            assert read.rule.atividade_versao_id == 29


def test_real_v1_copy_migrates_transactionally_and_preserves_business_rows(tmp_path):
    source = Path(main.__file__).resolve().parent / "database.db"
    assert source.exists()
    source_hash = _sha256(source)
    target = tmp_path / "disposable-v1.db"
    shutil.copyfile(source, target)

    before = sqlite3.connect(target)
    before.row_factory = sqlite3.Row
    version_rows = [dict(row) for row in before.execute(
        """SELECT id,atividade_base_id,eixo,grupo,ch_por_evento,limite_semestre,
                  limite_total,observacao_aluno,observacao_admin,documentos_json,
                  vigencia_inicio,vigencia_fim,numero_versao,status,
                  versao_anterior_id,created_at FROM atividade_versao ORDER BY id"""
    )]
    base_rows = [dict(row) for row in before.execute("SELECT * FROM atividade_base ORDER BY id")]
    before.close()

    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    result = bootstrap_prod1_schema(conn)
    assert result["schema_version"] == 2
    assert [dict(row) for row in conn.execute("SELECT * FROM atividade_base ORDER BY id")] == base_rows
    assert [dict(row) for row in conn.execute(
        """SELECT id,atividade_base_id,eixo,grupo,ch_por_evento,limite_semestre,
                  limite_total,observacao_aluno,observacao_admin,documentos_json,
                  vigencia_inicio,vigencia_fim,numero_versao,status,
                  versao_anterior_id,created_at FROM atividade_versao ORDER BY id"""
    )] == version_rows
    assert conn.execute("SELECT COUNT(*) FROM atividade_base").fetchone()[0] == 27
    assert conn.execute("SELECT COUNT(*) FROM atividade_versao").fetchone()[0] == 27
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()
    assert _sha256(source) == source_hash
