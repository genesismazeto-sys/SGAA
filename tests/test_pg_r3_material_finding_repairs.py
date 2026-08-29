"""R3 semantic contracts for the six accepted independent-review findings."""
from __future__ import annotations

import hashlib
import io
import json
import re
import sqlite3

import pytest

import main
from app.activity_catalog import apply_activity_version_semantic_changes
from app.prod1_schema import (
    PROD1_SCHEMA_SQL,
    SCHEMA_EPOCH,
    SCHEMA_VERSION,
    Prod1SchemaError,
    bootstrap_prod1_schema,
    validate_prod1_schema,
)
from app.services.backup_service import BackupServiceError, validate_manifest_backed_restore
from app.views.aluno import (
    _build_aluno_progresso_payload,
    _build_aluno_requisicao_snapshot_display,
)
from tests.canonical_request_test_support import (
    create_admin_request,
    login_admin,
    login_student,
    student_identity,
)
from tests.versioned_test_support import isolated_versioned_app_env


def _connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _signature(path):
    return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_size


def _mutated_prod1_sql(kind: str) -> str:
    sql = PROD1_SCHEMA_SQL
    replacements = {
        "missing_required_column": (
            " horas_solicitadas REAL NOT NULL CHECK(horas_solicitadas>=0), nome_evento TEXT,\n",
            " horas_solicitadas REAL NOT NULL CHECK(horas_solicitadas>=0),\n",
        ),
        "wrong_nullability": (
            " atividade_versao_id INTEGER NOT NULL,\n data_solicitacao",
            " atividade_versao_id INTEGER,\n data_solicitacao",
        ),
        "missing_foreign_key": (
            " FOREIGN KEY(atividade_versao_id) REFERENCES atividade_versao(id) ON DELETE RESTRICT ON UPDATE CASCADE,\n",
            " CHECK(atividade_versao_id>0),\n",
        ),
        "wrong_composite_foreign_key": (
            " FOREIGN KEY(atividade_versao_id,atividade_base_id) REFERENCES atividade_versao(id,atividade_base_id) ON DELETE RESTRICT,",
            " FOREIGN KEY(atividade_versao_id) REFERENCES atividade_versao(id) ON DELETE RESTRICT,",
        ),
        "missing_unique": (
            " UNIQUE(matriz_id,atividade_base_id), UNIQUE(matriz_id,atividade_versao_id)",
            " UNIQUE(matriz_id,atividade_versao_id)",
        ),
        "missing_canonical_index": (
            "CREATE INDEX idx_requisicoes_atividade_versao_id ON requisicoes(atividade_versao_id);\n",
            "",
        ),
        "altered_request_status_check": (
            "'Devolvida','Encerrada'))",
            "'Devolvida','Encerrada','Cancelada'))",
        ),
    }
    if kind == "missing_snapshot_trigger":
        mutated, count = re.subn(
            r"CREATE TRIGGER trg_requisicoes_snapshot_immutable\s+.*?END;\s*",
            "",
            sql,
            count=1,
            flags=re.DOTALL,
        )
        assert count == 1
        return mutated
    old, new = replacements[kind]
    assert sql.count(old) == 1, kind
    return sql.replace(old, new, 1)


@pytest.mark.parametrize(
    "corruption",
    [
        "missing_required_column",
        "wrong_nullability",
        "missing_foreign_key",
        "wrong_composite_foreign_key",
        "missing_unique",
        "missing_canonical_index",
        "missing_snapshot_trigger",
        "altered_request_status_check",
    ],
)
def test_f1_complete_physical_validation_rejects_representative_corruption_without_mutation(
    tmp_path, corruption
):
    path = tmp_path / f"malformed-{corruption}.db"
    conn = _connect(path)
    conn.executescript(_mutated_prod1_sql(corruption))
    before = _signature(path)
    with pytest.raises(Prod1SchemaError, match="physical schema contract"):
        validate_prod1_schema(conn)
    assert _signature(path) == before
    conn.close()


@pytest.mark.parametrize("corruption", ["legacy_object", "wrong_epoch", "wrong_version"])
def test_f1_validation_rejects_forbidden_object_and_marker_corruption(tmp_path, corruption):
    path = tmp_path / f"labelled-{corruption}.db"
    conn = _connect(path)
    bootstrap_prod1_schema(conn)
    if corruption == "legacy_object":
        conn.execute("CREATE TABLE atividades(id INTEGER PRIMARY KEY)")
    elif corruption == "wrong_epoch":
        conn.execute("UPDATE schema_migrations SET schema_epoch='future-2'")
    else:
        conn.execute("PRAGMA user_version=1")
    conn.commit()
    before = _signature(path)
    with pytest.raises(Prod1SchemaError):
        validate_prod1_schema(conn)
    assert _signature(path) == before
    conn.close()


def _seed_frozen_version(conn):
    course = conn.execute(
        "INSERT INTO cursos(nome,codigo,duracao_periodos) VALUES('Curso','R3',8) RETURNING id"
    ).fetchone()[0]
    matrix = conn.execute(
        "INSERT INTO matrizes_atividades(curso_id,nome) VALUES(?,'Matriz') RETURNING id",
        (course,),
    ).fetchone()[0]
    conn.execute(
        """INSERT INTO turmas(nome,numero,curso_id,ano_inicio,semestre_inicio,codigo,matriz_id)
           VALUES('R3-Turma',1,?,2026,1,'R3-T1',?)""",
        (course, matrix),
    )
    base = conn.execute(
        "INSERT INTO atividade_base(nome_conceito,descricao) VALUES('R3 Base','descrição') RETURNING id"
    ).fetchone()[0]
    version = conn.execute(
        """INSERT INTO atividade_versao(
               atividade_base_id,eixo,grupo,ch_por_evento,
               limite_semestre,limite_total,observacao_aluno,documentos_json,status
           ) VALUES(?,'AAC','1 - Antigo',2,10,20,'preservar','["doc"]','ativa') RETURNING id""",
        (base,),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO matriz_atividade_versao_item(matriz_id,atividade_base_id,atividade_versao_id) VALUES(?,?,?)",
        (matrix, base, version),
    )
    snapshot = json.dumps({"frozen": "unchanged"}, sort_keys=True)
    request_id = conn.execute(
        """INSERT INTO requisicoes(
               atividade_versao_id,data_solicitacao,data_evento,horas_solicitadas,status,
               regra_snapshot_json)
           VALUES(?,'2026-01-01','2026-01-01',2,'Pendente',?) RETURNING id""",
        (version, snapshot),
    ).fetchone()[0]
    conn.commit()
    return base, matrix, version, request_id, snapshot


def test_f2_canonical_owner_updates_draft_but_copies_frozen_version_to_successor(tmp_path):
    conn = _connect(tmp_path / "freeze.db")
    bootstrap_prod1_schema(conn)
    base, matrix, frozen_id, request_id, snapshot = _seed_frozen_version(conn)
    predecessor = dict(conn.execute("SELECT * FROM atividade_versao WHERE id=?", (frozen_id,)).fetchone())

    result = apply_activity_version_semantic_changes(
        conn, frozen_id, {"grupo": "1 - Novo", "limite_total": 99}
    )
    conn.commit()

    assert result["mode"] == "successor"
    assert dict(conn.execute("SELECT * FROM atividade_versao WHERE id=?", (frozen_id,)).fetchone()) == predecessor
    successor = conn.execute("SELECT * FROM atividade_versao WHERE id=?", (result["version_id"],)).fetchone()
    assert successor["atividade_base_id"] == base
    assert successor["versao_anterior_id"] == frozen_id
    assert successor["numero_versao"] == predecessor["numero_versao"] + 1
    assert successor["status"] == "rascunho"
    assert successor["grupo"] == "1 - Novo" and successor["limite_total"] == 99
    assert successor["ch_por_evento"] == predecessor["ch_por_evento"]
    assert successor["observacao_aluno"] == predecessor["observacao_aluno"]
    assert conn.execute(
        "SELECT atividade_versao_id FROM matriz_atividade_versao_item WHERE matriz_id=?", (matrix,)
    ).fetchone()[0] == frozen_id
    request_row = conn.execute(
        "SELECT atividade_versao_id,regra_snapshot_json FROM requisicoes WHERE id=?", (request_id,)
    ).fetchone()
    assert tuple(request_row) == (frozen_id, snapshot)

    draft_id = conn.execute(
        """INSERT INTO atividade_versao(
               atividade_base_id,eixo,grupo,numero_versao,status)
           SELECT atividade_base_id,eixo,'2',numero_versao+2,'rascunho'
             FROM atividade_versao WHERE id=? RETURNING id""",
        (frozen_id,),
    ).fetchone()[0]
    draft_result = apply_activity_version_semantic_changes(conn, draft_id, {"grupo": "2 - Editável"})
    assert draft_result == {"mode": "updated", "version_id": draft_id, "predecessor_id": None}
    assert conn.execute("SELECT grupo FROM atividade_versao WHERE id=?", (draft_id,)).fetchone()[0] == "2 - Editável"


@pytest.fixture()
def versioned_env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "r3-routes.db") as value:
        yield value


def test_f2_csv_import_and_group_rename_preserve_assigned_predecessors(versioned_env):
    client = versioned_env["client"]
    login_admin(client)
    with main.app.app_context():
        conn = main.get_db_connection()
        original = dict(conn.execute("SELECT * FROM atividade_versao WHERE id=1").fetchone())
        base_name = conn.execute("SELECT nome_conceito FROM atividade_base WHERE id=?", (original["atividade_base_id"],)).fetchone()[0]
        current_original = dict(conn.execute(
            "SELECT * FROM atividade_versao WHERE atividade_base_id=? ORDER BY numero_versao DESC,id DESC LIMIT 1",
            (original["atividade_base_id"],),
        ).fetchone())
        matrix_version = conn.execute(
            "SELECT atividade_versao_id FROM matriz_atividade_versao_item WHERE atividade_versao_id=1"
        ).fetchone()[0]

    csv_payload = "\n".join([
        "nome;tipo_atividade;grupo_numero;grupo_descricao;tem_limitacao;tipo_limitacao;limite_horas_total;limite_horas_semestral",
        f"{base_name};Acadêmica Complementar;1;Importado;sim;total;77;",
    ])
    preview = client.post(
        "/admin/atividades/importar/preview",
        data={"mode": "upsert", "csv_arquivo": (io.BytesIO(csv_payload.encode()), "r3.csv")},
        content_type="multipart/form-data",
    )
    match = re.search(r'name="preview_key" value="([^"]+)"', preview.get_data(as_text=True))
    assert preview.status_code == 200 and match
    assert client.post(
        "/admin/atividades/importar/confirmar", data={"preview_key": match.group(1)}
    ).status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        assert dict(conn.execute("SELECT * FROM atividade_versao WHERE id=1").fetchone()) == original
        imported = conn.execute(
            "SELECT * FROM atividade_versao WHERE atividade_base_id=? ORDER BY numero_versao DESC LIMIT 1",
            (original["atividade_base_id"],),
        ).fetchone()
        assert imported["id"] != current_original["id"]
        assert imported["versao_anterior_id"] == current_original["id"]
        assert imported["grupo"] == "1 - Importado" and imported["limite_total"] == 77
        assert conn.execute(
            "SELECT atividade_versao_id FROM matriz_atividade_versao_item WHERE atividade_versao_id=1"
        ).fetchone()[0] == matrix_version

    rename = client.post(
        "/admin/grupos/renomear",
        json={"tipo_atividade": "Acadêmica Complementar", "numero": "1", "descricao": "Renomeado"},
    )
    assert rename.status_code == 200 and rename.get_json()["ok"] is True
    with main.app.app_context():
        conn = main.get_db_connection()
        assert dict(conn.execute("SELECT * FROM atividade_versao WHERE id=1").fetchone()) == original
        assert conn.execute(
            "SELECT atividade_versao_id FROM matriz_atividade_versao_item WHERE atividade_versao_id=1"
        ).fetchone()[0] == 1


def test_f2_generic_admin_edit_creates_successor_without_rebinding_matrix_or_request(versioned_env):
    client = versioned_env["client"]
    login_admin(client)
    _, request_row = create_admin_request(client, "R3 frozen generic edit", version_id=29)
    assert request_row
    with main.app.app_context():
        conn = main.get_db_connection()
        original = dict(conn.execute("SELECT * FROM atividade_versao WHERE id=29").fetchone())
        base = dict(conn.execute(
            "SELECT * FROM atividade_base WHERE id=?", (original["atividade_base_id"],)
        ).fetchone())
        frozen_snapshot = conn.execute(
            "SELECT regra_snapshot_json FROM requisicoes WHERE id=?", (request_row["id"],)
        ).fetchone()[0]

    response = client.post(
        "/admin/editar_atividade/29",
        data={
            "nome": base["nome_conceito"],
            "descricao": base["descricao"] or "",
            "tipo_atividade": "Acadêmica Complementar",
            "grupo": "1 - Edição futura",
            "limite_horas": "6",
            "tem_limitacao": "1",
            "tipo_limitacao": "total",
            "limite_horas_total": "88",
            "limite_horas_semestral": "",
            "documentos_json": '["novo-doc"]',
        },
    )
    assert response.status_code in (302, 303)
    with main.app.app_context():
        conn = main.get_db_connection()
        assert dict(conn.execute("SELECT * FROM atividade_versao WHERE id=29").fetchone()) == original
        successor = conn.execute(
            "SELECT * FROM atividade_versao WHERE atividade_base_id=? ORDER BY numero_versao DESC,id DESC LIMIT 1",
            (original["atividade_base_id"],),
        ).fetchone()
        assert successor["id"] != 29 and successor["versao_anterior_id"] == 29
        assert successor["status"] == "rascunho"
        assert successor["grupo"] == "1 - Edição futura"
        assert successor["limite_total"] == 88
        assert conn.execute(
            "SELECT atividade_versao_id FROM matriz_atividade_versao_item WHERE atividade_base_id=? AND matriz_id=2",
            (original["atividade_base_id"],),
        ).fetchone()[0] == 29
        persisted_request = conn.execute(
            "SELECT atividade_versao_id,regra_snapshot_json FROM requisicoes WHERE id=?",
            (request_row["id"],),
        ).fetchone()
        assert tuple(persisted_request) == (29, frozen_snapshot)


def test_f3_snapshot_display_is_snapshot_first_even_when_catalogue_differs():
    snapshot = {
        "atividade_versao_numero": 2,
        "eixo": "AAC",
        "grupo": "3 - Congelado",
        "snapshot_written_at": "2026-01-01T00:00:00Z",
        "flow_origin": "student",
    }
    current = sqlite3.Row
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE current(numero_versao,eixo,grupo)")
    current = conn.execute(
        "SELECT 9 AS numero_versao,'AEU' AS eixo,'9 - Mutável' AS grupo"
    ).fetchone()
    display = _build_aluno_requisicao_snapshot_display(
        atividade_versao_id=10,
        regra_snapshot_json=json.dumps(snapshot),
        versao_row=current,
    )
    assert display == {
        "snapshot_versionado_presente": True,
        "snapshot_vn": 2,
        "snapshot_eixo": "AAC",
        "snapshot_grupo": "3 - Congelado",
        "snapshot_written_at": "2026-01-01T00:00:00Z",
        "snapshot_flow_origin": "student",
    }


def test_f3_student_list_and_detail_do_not_leak_mutated_catalogue_values(versioned_env):
    client = versioned_env["client"]
    login_admin(client)
    _, request_row = create_admin_request(client, "R3 snapshot presentation", version_id=29)
    assert request_row
    frozen = json.loads(request_row["regra_snapshot_json"])
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "UPDATE atividade_base SET nome_conceito='LIVE NAME LEAK' WHERE id=?",
            (frozen["atividade_base_id"],),
        )
        conn.execute(
            "UPDATE atividade_versao SET grupo='LIVE-GROUP',numero_versao=99 WHERE id=29"
        )
        conn.commit()
    login_student(client)
    pages = [
        client.get("/aluno/requisicoes"),
        client.get(f"/aluno/requisicoes/{request_row['id']}"),
    ]
    for page in pages:
        html = page.get_data(as_text=True)
        assert page.status_code == 200
        assert frozen["nome_exibivel"] in html
        assert frozen["grupo"] in html
        assert "LIVE NAME LEAK" not in html
        assert "LIVE-GROUP" not in html


def test_f4_progress_merges_current_and_history_for_same_exact_version(versioned_env):
    client = versioned_env["client"]
    login_admin(client)
    response, request_row = create_admin_request(client, "R3 merged progress", version_id=29)
    assert response.status_code in (302, 303) and request_row
    assert client.post(
        f"/admin/processar_requisicao/{request_row['id']}",
        data={"status": "Deferida", "horas_deferidas": "4", "observacao": "ok"},
    ).status_code in (302, 303)
    identity = student_identity()
    with main.app.app_context():
        conn = main.get_db_connection()
        old = conn.execute(
            """SELECT v.*,b.nome_conceito FROM atividade_versao v
                 JOIN atividade_base b ON b.id=v.atividade_base_id WHERE v.id=1"""
        ).fetchone()
        old_snapshot = {
            "atividade_base_id": old["atividade_base_id"],
            "atividade_versao_id": old["id"],
            "atividade_versao_numero": old["numero_versao"],
            "eixo": old["eixo"],
            "matriz_id_efetiva": 1,
            "schema_version": "prod-1-request-v2",
            "ch_por_evento": old["ch_por_evento"],
            "limite_semestre": old["limite_semestre"],
            "limite_total": old["limite_total"],
            "nome_exibivel": old["nome_conceito"],
            "tipo_atividade": "Acadêmica Complementar",
            "grupo": old["grupo"],
            "documentos_json": old["documentos_json"] or "[]",
        }
        conn.execute(
            """INSERT INTO requisicoes(
                   aluno_id,atividade_versao_id,data_solicitacao,data_evento,
                   horas_solicitadas,status,horas_deferidas,regra_snapshot_json,nome_evento)
               VALUES(?,1,'2026-01-01','2026-01-01',2,'Deferida',2,?,?)""",
            (identity["aluno_id"], json.dumps(old_snapshot), "R3 old history"),
        )
        conn.commit()
        payload = _build_aluno_progresso_payload(conn, identity["usuario_id"])
    exact = [item for item in payload["atividades"] if item["atividade_id"] == 29]
    assert len(exact) == 1
    assert exact[0]["total"] == 4
    assert any(item["atividade_id"] == 1 for item in payload["atividades"])


@pytest.mark.parametrize(
    "manifest",
    [
        {"schema_epoch": "legacy", "schema_version": 1},
        {"schema_epoch": SCHEMA_EPOCH, "schema_version": 99},
        {"schema_version": SCHEMA_VERSION},
        {"schema_epoch": SCHEMA_EPOCH},
    ],
)
def test_f5_manifest_metadata_is_required_and_must_match_runtime(tmp_path, manifest):
    database = tmp_path / "valid.db"
    conn = _connect(database)
    bootstrap_prod1_schema(conn)
    conn.close()
    with pytest.raises(BackupServiceError):
        validate_manifest_backed_restore(str(database), manifest)


def test_f5_manifest_and_complete_database_validation_are_both_required(tmp_path):
    valid = tmp_path / "valid.db"
    conn = _connect(valid)
    bootstrap_prod1_schema(conn)
    conn.close()
    manifest = {"schema_epoch": SCHEMA_EPOCH, "schema_version": SCHEMA_VERSION}
    accepted = validate_manifest_backed_restore(str(valid), manifest)
    assert accepted["schema_status"]["schema_epoch"] == SCHEMA_EPOCH

    malformed = tmp_path / "malformed.db"
    conn = _connect(malformed)
    conn.executescript(_mutated_prod1_sql("missing_snapshot_trigger"))
    conn.close()
    with pytest.raises(BackupServiceError):
        validate_manifest_backed_restore(str(malformed), manifest)

    legacy = tmp_path / "legacy.db"
    conn = _connect(legacy)
    conn.execute("CREATE TABLE atividades(id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    with pytest.raises(BackupServiceError):
        validate_manifest_backed_restore(str(legacy), manifest)
