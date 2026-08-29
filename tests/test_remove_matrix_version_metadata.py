"""REMOVE-MATRIX-VERSION-METADATA-1 — v3 schema/migration and UI contracts.

Covers the canonical removal of matrix-own version metadata (versao) and
dead matrix lineage (matriz_origem_id) while preserving activity versioning,
matrix→activity-version links, assigned-matrix freeze and request snapshots.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import main
from app.matrix_scope import _matriz_option_label
from app.prod1_schema import (
    LATEST_MIGRATION_MARKER,
    _PROD1_V2_SIGNATURE_SHA256,
    _physical_schema_digest,
    Prod1SchemaError,
    bootstrap_prod1_schema,
    validate_prod1_schema,
)
from app.versioning import resolver
from app.versioning.snapshots import (
    SnapshotProcessingAuthority,
    read_requisicao_snapshot_for_processing,
)
from tests.canonical_matrix_test_support import current_version_id, login_admin, seed_matrix_graph
from tests.hermetic_prod1_fixtures import (
    _columns,
    _markers,
    _table_names,
    build_canonical_v2_database,
    seed_v2_business_data,
)
from tests.versioned_test_support import isolated_versioned_app_env

REMOVED_MATRIX_FIELDS = {"versao", "matriz_origem_id"}
RESIDUAL_RUNTIME_PATTERNS = (
    "m.versao",
    "matriz_versao",
    "versao_filter",
    "matriz_origem_id",
    'name="versao"',
    "Versão da matriz",
)


def _matrix_columns(conn):
    return {row[1] for row in conn.execute("PRAGMA table_info(matrizes_atividades)")}


@pytest.fixture()
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "rmv-matrix-version.db") as value:
        yield value


# ---------------------------------------------------------------------------
# UI / runtime contracts
# ---------------------------------------------------------------------------

def test_matrix_create_succeeds_without_versao(env):
    login_admin(env["client"])
    response = env["client"].post(
        "/admin/adicionar_matriz",
        data={
            "curso_id": 1,
            "nome": "Matriz sem versao propria",
            "status": "vigente",
            "data_inicio_vigencia": "2026-01-01",
            "horas_aac_obrigatorias": 160,
            "horas_extensao_obrigatorias": 80,
        },
    )
    assert response.status_code in (302, 303)
    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT * FROM matrizes_atividades WHERE nome='Matriz sem versao propria'"
        ).fetchone()
        assert row is not None
        assert row["status"] == "vigente"
        assert row["horas_aac_obrigatorias"] == 160


def test_matrix_edit_succeeds_without_versao(env):
    login_admin(env["client"])
    with main.app.app_context():
        conn = main.get_db_connection()
        seed = seed_matrix_graph(conn, name="Matriz edit sem versao")
        matrix_id = seed["matrix_id"]
    response = env["client"].post(
        f"/admin/editar_matriz/{matrix_id}",
        data={
            "active_tab": "dados",
            "curso_id": 1,
            "nome": "Matriz edit sem versao renomeada",
            "status": "vigente",
            "horas_aac_obrigatorias": 120,
            "horas_extensao_obrigatorias": 60,
        },
    )
    assert response.status_code in (302, 303)
    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT * FROM matrizes_atividades WHERE id=?", (matrix_id,)
        ).fetchone()
        assert row["nome"] == "Matriz edit sem versao renomeada"
        assert row["horas_aac_obrigatorias"] == 120


def test_matrix_form_and_list_have_no_versao_surface(env):
    login_admin(env["client"])
    form = env["client"].get("/admin/adicionar_matriz")
    form_html = form.get_data(as_text=True)
    assert 'name="versao"' not in form_html
    assert "row-label\">Versão" not in form_html

    listing = env["client"].get("/admin/matrizes")
    listing_html = listing.get_data(as_text=True)
    assert 'data-field="versao"' not in listing_html
    assert '"param": "versao"' not in listing_html
    assert "{'text':'Versão'" not in listing_html
    assert "Buscar por nome, curso ou versão" not in listing_html


def test_global_matrix_search_no_longer_depends_on_versao(env):
    login_admin(env["client"])
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "INSERT INTO matrizes_atividades (curso_id,nome,status) VALUES (1,'Matriz Busca Token X','rascunho')"
        )
        conn.execute(
            "INSERT INTO matrizes_atividades (curso_id,nome,status) VALUES (1,'Matriz Busca Outra','rascunho')"
        )
        conn.commit()
    response = env["client"].get("/admin/matrizes", query_string={"q": "Token X"})
    html = response.get_data(as_text=True)
    assert "Matriz Busca Token X" in html
    assert "Matriz Busca Outra" not in html


def test_matrix_labels_remain_useful_without_versao():
    label = _matriz_option_label({"nome": "01.2025", "status": "vigente"})
    assert label == "01.2025 | Vigente"
    versioning_label = resolver._versioning_matriz_option_label({"nome": "01.2025", "status": "vigente"})
    assert versioning_label == "01.2025 | Vigente"


def test_turma_assignment_uses_matrix_id_not_textual_version(env):
    with main.app.app_context():
        conn = main.get_db_connection()
        curso_id = conn.execute("SELECT id FROM cursos ORDER BY id LIMIT 1").fetchone()["id"]
        m1 = conn.execute(
            "INSERT INTO matrizes_atividades (curso_id,nome,status) VALUES (?,'Nome duplicado','vigente') RETURNING id",
            (curso_id,),
        ).fetchone()[0]
        m2 = conn.execute(
            "INSERT INTO matrizes_atividades (curso_id,nome,status) VALUES (?,'Nome duplicado','rascunho') RETURNING id",
            (curso_id,),
        ).fetchone()[0]
        assert m1 != m2
        conn.execute(
            """INSERT INTO turmas (nome,status,numero,curso_id,ano_inicio,semestre_inicio,codigo,matriz_id)
               VALUES ('Dup-Nome','Ativa',77,?,2026,1,'DUP77',?)""",
            (curso_id, m2),
        )
        conn.commit()
        from app.matrix_scope import get_effective_matriz_for_turma

        effective = get_effective_matriz_for_turma(conn, curso_id, m2)
        assert effective["id"] == m2
        assert effective["nome"] == "Nome duplicado"


def test_assigned_matrix_freeze_remains_unchanged(env):
    login_admin(env["client"])
    with main.app.app_context():
        conn = main.get_db_connection()
        seed = seed_matrix_graph(conn, name="Matriz frozen sem versao")
        curso_id = seed["course_id"]
        matrix_id = seed["matrix_id"]
        conn.execute(
            """INSERT INTO turmas (nome,status,numero,curso_id,ano_inicio,semestre_inicio,codigo,matriz_id)
               VALUES ('Frozen-MV','Ativa',78,?,2026,1,'FRZ78',?)""",
            (curso_id, matrix_id),
        )
        conn.commit()
    response = env["client"].post(
        f"/admin/editar_matriz/{matrix_id}",
        data={
            "active_tab": "dados",
            "curso_id": curso_id,
            "nome": "Matriz frozen sem versao",
            "status": "encerrada",
            "horas_aac_obrigatorias": 100,
            "horas_extensao_obrigatorias": 50,
        },
        follow_redirects=True,
    )
    assert "Parâmetros inválidos." in response.get_data(as_text=True)
    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT status FROM matrizes_atividades WHERE id=?", (matrix_id,)
        ).fetchone()
        assert row["status"] == "rascunho"


def test_exact_activity_version_links_remain_unchanged(env):
    login_admin(env["client"])
    with main.app.app_context():
        conn = main.get_db_connection()
        seed = seed_matrix_graph(conn, name="Matriz links exatos")
        assert current_version_id(conn, seed) == seed["v1"]
        resolved = resolver.resolver_versao_por_matriz(
            conn, matriz_id=seed["matrix_id"], atividade_versao_id=seed["v1"]
        )
        assert resolved["status"] == "resolved"
        assert resolved["atividade_base_id"] == seed["base_id"]


# ---------------------------------------------------------------------------
# Schema v3 + v2→v3 migration contracts
# ---------------------------------------------------------------------------

def test_fresh_bootstrap_is_v3_without_matrix_version_fields(tmp_path):
    conn = sqlite3.connect(tmp_path / "fresh-v3.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    result = bootstrap_prod1_schema(conn)
    assert result["schema_version"] == 3
    assert REMOVED_MATRIX_FIELDS.isdisjoint(_matrix_columns(conn))
    markers = conn.execute("SELECT version,name FROM schema_migrations ORDER BY version").fetchall()
    assert [tuple(row) for row in markers] == [
        (1, "first_production_baseline"),
        (2, "remove_norma_domain"),
        (3, LATEST_MIGRATION_MARKER),
    ]
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()


def test_second_bootstrap_on_v3_is_idempotent(tmp_path):
    conn = sqlite3.connect(tmp_path / "idempotent-v3.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    first = bootstrap_prod1_schema(conn)
    second = bootstrap_prod1_schema(conn)
    assert first["schema_version"] == second["schema_version"] == 3
    assert validate_prod1_schema(conn)["schema_version"] == 3
    assert len(conn.execute("SELECT * FROM schema_migrations").fetchall()) == 3
    conn.close()


def test_canonical_populated_v2_migrates_to_v3(tmp_path):
    """Hermetic canonical prod-1/v2 → v3 through the real production bootstrap.

    The v2 database is generated under tmp_path by running the REAL v1→v2
    migration over the hermetic canonical v1 builder (proven against both
    production signature constants). No operational database is read or copied.
    """
    conn = sqlite3.connect(tmp_path / "hermetic-populated-v2.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    build_canonical_v2_database(conn)
    ids = seed_v2_business_data(conn)

    surviving = {
        "id", "curso_id", "nome", "descricao", "status", "data_inicio_vigencia",
        "data_fim_vigencia", "horas_aac_obrigatorias", "horas_extensao_obrigatorias", "created_at",
    }
    matrices_before = [dict(row) for row in conn.execute("SELECT * FROM matrizes_atividades ORDER BY id")]
    mavi_before = [
        tuple(row) for row in conn.execute(
            "SELECT matriz_id,atividade_base_id,atividade_versao_id FROM matriz_atividade_versao_item ORDER BY id"
        )
    ]
    turmas_before = [tuple(row) for row in conn.execute("SELECT id,nome,matriz_id FROM turmas ORDER BY id")]
    reqs_before = [
        tuple(row) for row in conn.execute(
            "SELECT id,aluno_id,atividade_versao_id,regra_snapshot_json FROM requisicoes ORDER BY id"
        )
    ]

    result = bootstrap_prod1_schema(conn)
    assert result["schema_version"] == 3
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
    assert REMOVED_MATRIX_FIELDS.isdisjoint(_matrix_columns(conn))
    assert _markers(conn) == [
        (1, "first_production_baseline", "prod-1"),
        (2, "remove_norma_domain", "prod-1"),
        (3, LATEST_MIGRATION_MARKER, "prod-1"),
    ]
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []

    matrices_after = [dict(row) for row in conn.execute("SELECT * FROM matrizes_atividades ORDER BY id")]
    assert [{key: row[key] for key in surviving} for row in matrices_after] == [
        {key: row[key] for key in surviving} for row in matrices_before
    ]
    assert [row["id"] for row in matrices_after] == [row["id"] for row in matrices_before]

    mavi_after = [
        tuple(row) for row in conn.execute(
            "SELECT matriz_id,atividade_base_id,atividade_versao_id FROM matriz_atividade_versao_item ORDER BY id"
        )
    ]
    assert mavi_after == mavi_before

    turmas_after = [tuple(row) for row in conn.execute("SELECT id,nome,matriz_id FROM turmas ORDER BY id")]
    assert turmas_after == turmas_before

    reqs_after = [
        tuple(row) for row in conn.execute(
            "SELECT id,aluno_id,atividade_versao_id,regra_snapshot_json FROM requisicoes ORDER BY id"
        )
    ]
    assert reqs_after == reqs_before
    snapshot_after = json.loads(reqs_after[0][3])
    assert snapshot_after["matriz_id_efetiva"] == ids["m1"]

    read = read_requisicao_snapshot_for_processing(
        conn.execute("SELECT * FROM requisicoes WHERE id=?", (ids["req_id"],)).fetchone()
    )
    assert read.authority is SnapshotProcessingAuthority.VALID_AUTHORITATIVE_SNAPSHOT
    assert read.rule.matriz_id_efetiva == ids["m1"]

    second = bootstrap_prod1_schema(conn)
    assert second["schema_version"] == 3
    conn.close()


def test_tampered_canonical_v2_fails_closed(tmp_path):
    """A tampered v2 physical schema must fail closed without partial migration."""
    conn = sqlite3.connect(tmp_path / "hermetic-tampered-v2.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    build_canonical_v2_database(conn)
    seed_v2_business_data(conn)
    matrix_rows_before = [dict(row) for row in conn.execute("SELECT * FROM matrizes_atividades ORDER BY id")]
    req_rows_before = [tuple(row) for row in conn.execute(
        "SELECT id,aluno_id,atividade_versao_id,regra_snapshot_json FROM requisicoes ORDER BY id"
    )]

    conn.execute("CREATE TABLE _tamper_probe(id INTEGER PRIMARY KEY)")
    conn.commit()

    with pytest.raises(Prod1SchemaError):
        bootstrap_prod1_schema(conn)

    assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
    assert _markers(conn) == [
        (1, "first_production_baseline", "prod-1"),
        (2, "remove_norma_domain", "prod-1"),
    ]
    assert {"versao", "matriz_origem_id"} <= _matrix_columns(conn)
    assert [dict(row) for row in conn.execute("SELECT * FROM matrizes_atividades ORDER BY id")] == matrix_rows_before
    assert [tuple(row) for row in conn.execute(
        "SELECT id,aluno_id,atividade_versao_id,regra_snapshot_json FROM requisicoes ORDER BY id"
    )] == req_rows_before
    assert "_tamper_probe" in _table_names(conn)
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    conn.close()


class _MarkerInsertFailConnection(sqlite3.Connection):
    """Test-only connection that injects a failure at the v3 marker insert.

    Used to prove the REAL v2→v3 migration rolls back completely when a
    statement fails after the matrizes_atividades rebuild has begun.
    """

    def execute(self, sql, parameters=()):
        if (
            isinstance(sql, str)
            and "INSERT INTO schema_migrations" in sql
            and parameters
            and parameters[0] == 3
        ):
            raise sqlite3.OperationalError("injected v3 marker failure")
        return super().execute(sql, parameters)


def test_injected_failure_rolls_back_v2_to_v3(tmp_path):
    """An injected failure after the rebuild must roll back to pristine v2."""
    path = tmp_path / "hermetic-rollback-v2.db"
    setup = sqlite3.connect(path)
    setup.row_factory = sqlite3.Row
    setup.execute("PRAGMA foreign_keys=ON")
    build_canonical_v2_database(setup)
    seed_v2_business_data(setup)
    matrix_rows_before = [dict(row) for row in setup.execute("SELECT * FROM matrizes_atividades ORDER BY id")]
    mavi_before = [tuple(row) for row in setup.execute(
        "SELECT matriz_id,atividade_base_id,atividade_versao_id FROM matriz_atividade_versao_item ORDER BY id"
    )]
    setup.close()

    conn = sqlite3.connect(path, factory=_MarkerInsertFailConnection)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    with pytest.raises(sqlite3.OperationalError):
        bootstrap_prod1_schema(conn)

    assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
    assert _markers(conn) == [
        (1, "first_production_baseline", "prod-1"),
        (2, "remove_norma_domain", "prod-1"),
    ]
    assert {"versao", "matriz_origem_id"} <= _matrix_columns(conn)
    assert [dict(row) for row in conn.execute("SELECT * FROM matrizes_atividades ORDER BY id")] == matrix_rows_before
    assert [tuple(row) for row in conn.execute(
        "SELECT matriz_id,atividade_base_id,atividade_versao_id FROM matriz_atividade_versao_item ORDER BY id"
    )] == mavi_before
    assert _physical_schema_digest(conn) == _PROD1_V2_SIGNATURE_SHA256
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()


def test_v2_marker_with_v3_physical_shape_fails_closed(tmp_path):
    conn = sqlite3.connect(tmp_path / "fake-v2.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    bootstrap_prod1_schema(conn)
    conn.execute("PRAGMA user_version=2")
    conn.commit()
    with pytest.raises(Prod1SchemaError):
        bootstrap_prod1_schema(conn)
    conn.close()


def test_runtime_sources_have_no_matrix_version_residue():
    root = Path(main.__file__).resolve().parent
    runtime_paths = [root / "main.py"]
    for directory in (root / "app", root / "templates", root / "tools"):
        runtime_paths.extend(path for path in directory.rglob("*") if path.suffix in {".py", ".html", ".js"})
    runtime_paths.remove(root / "app" / "prod1_schema.py")

    residuals = {}
    for path in runtime_paths:
        text = path.read_text(encoding="utf-8").casefold()
        hits = [term for term in RESIDUAL_RUNTIME_PATTERNS if term in text]
        if hits:
            residuals[str(path.relative_to(root))] = hits
    assert residuals == {}

    migration_source = (root / "app" / "prod1_schema.py").read_text(encoding="utf-8").casefold()
    assert migration_source.count("matriz_origem_id") == 2
    assert migration_source.count("matrizes_atividades.versao") == 2
    assert "matrizes_atividades.matriz_origem_id" in migration_source
