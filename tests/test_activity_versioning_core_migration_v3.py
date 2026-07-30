import ast
import inspect
import sqlite3
from pathlib import Path

import pytest

from app import db_maintenance


V3_NAME = "normalize_activity_versioning_core"
CORE_TABLES = ("atividade_base", "norma_atividade", "atividade_versao")
CORE_TRIGGERS = (
    "trg_atividade_versao_eixo_norma_insert",
    "trg_atividade_versao_prev_same_eixo_insert",
    "trg_atividade_versao_prev_same_eixo_update",
    "trg_atividade_versao_eixo_norma_update",
    "trg_atividade_versao_num_pos_insert",
    "trg_atividade_versao_num_pos_update",
)
CORE_INDEXES = {
    "idx_norma_atividade_codigo": ("norma_atividade", ("codigo",), False),
    "idx_norma_atividade_eixo": ("norma_atividade", ("eixo",), False),
    "idx_atividade_versao_base": ("atividade_versao", ("atividade_base_id",), False),
    "idx_atividade_versao_norma": ("atividade_versao", ("norma_id",), False),
    "idx_atividade_versao_base_num": (
        "atividade_versao",
        ("atividade_base_id", "numero_versao"),
        True,
    ),
    "idx_atividade_versao_eixo": ("atividade_versao", ("eixo",), False),
    "idx_atividade_versao_status": ("atividade_versao", ("status",), False),
}
LEAF_TABLES = (
    "atividade_transicao",
    "matriz_norma",
    "matriz_atividade_versao_item",
    "atividade_legacy_map",
)
LEAF_TRIGGERS = (
    "trg_atividade_transicao_aac_para_aeu_insert",
    "trg_atividade_transicao_aac_para_aeu_update",
)
LEAF_INDEXES = (
    "idx_atividade_transicao_from",
    "idx_atividade_transicao_to",
    "idx_atividade_transicao_tipo",
    "idx_matriz_norma_matriz",
    "idx_matriz_norma_norma",
    "idx_matriz_atividade_versao_item_matriz",
    "idx_matriz_atividade_versao_item_versao",
    "idx_atividade_legacy_map_base",
)


ATIVIDADES_DDL = """
CREATE TABLE atividades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    grupo TEXT NOT NULL,
    nome TEXT NOT NULL UNIQUE,
    descricao TEXT,
    limite_horas INTEGER,
    tipo_atividade TEXT NOT NULL DEFAULT 'Acadêmica Complementar'
        CHECK(tipo_atividade IN ('Acadêmica Complementar', 'Extensão Universitária')),
    tem_limitacao BOOLEAN DEFAULT 0,
    tipo_limitacao TEXT CHECK(tipo_limitacao IN ('total', 'semestral')),
    limite_horas_total INTEGER,
    limite_horas_semestral INTEGER,
    documentos_json TEXT
)
"""

ATIVIDADE_BASE_DDL = """
CREATE TABLE atividade_base (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome_conceito TEXT NOT NULL UNIQUE,
    descricao TEXT,
    status TEXT NOT NULL DEFAULT 'ativo' CHECK(status IN ('ativo', 'inativo')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

NORMA_ATIVIDADE_DDL = """
CREATE TABLE norma_atividade (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT NOT NULL UNIQUE,
    eixo TEXT NOT NULL CHECK(eixo IN ('AAC', 'AEU')),
    revisao TEXT NOT NULL,
    nome TEXT,
    descricao TEXT,
    status TEXT NOT NULL DEFAULT 'ativa' CHECK(status IN ('ativa', 'inativa')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

VERSAO_PREFIX = """
CREATE TABLE atividade_versao (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    atividade_base_id INTEGER NOT NULL,
    norma_id INTEGER NOT NULL,
    codigo_normativo TEXT NOT NULL,
    eixo TEXT NOT NULL CHECK(eixo IN ('AAC', 'AEU')),
    grupo TEXT,
    ch_por_evento REAL,
    limite_semestre REAL,
    limite_total REAL,
    observacao_aluno TEXT,
    observacao_admin TEXT,
    documentos_json TEXT,
    vigencia_inicio TEXT,
    vigencia_fim TEXT,
"""

VERSAO_SUFFIX = """
    status TEXT NOT NULL DEFAULT 'rascunho'
        CHECK(status IN ('rascunho', 'ativa', 'inativa', 'descontinuada', 'substituida')),
    versao_anterior_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(atividade_base_id) REFERENCES atividade_base(id) ON DELETE RESTRICT,
    FOREIGN KEY(norma_id) REFERENCES norma_atividade(id) ON DELETE RESTRICT,
    FOREIGN KEY(versao_anterior_id) REFERENCES atividade_versao(id) ON DELETE RESTRICT
"""


class InjectedFailure(RuntimeError):
    pass


class ExecuteProbe:
    def __init__(self, connection, fail_token=None):
        self.connection = connection
        self.fail_token = fail_token
        self.statements = []
        self.failed = False

    @property
    def in_transaction(self):
        return self.connection.in_transaction

    def execute(self, sql, *args):
        normalized = " ".join(str(sql).split()).upper()
        self.statements.append(normalized)
        if (
            self.fail_token
            and self.fail_token in normalized
            and not self.failed
        ):
            self.failed = True
            raise InjectedFailure(self.fail_token)
        return self.connection.execute(sql, *args)

    def __getattr__(self, name):
        return getattr(self.connection, name)


def _connection():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _create_prerequisites(conn, *, requisicoes_version_column=True):
    conn.execute(ATIVIDADES_DDL)
    conn.execute(
        "INSERT INTO atividades(id, grupo, nome, documentos_json) "
        "VALUES(101, 'G', 'Legacy activity', '[\"pdf\"]')"
    )
    conn.execute(
        "CREATE TABLE cursos(id INTEGER PRIMARY KEY, nome TEXT NOT NULL, "
        "codigo TEXT NOT NULL UNIQUE, duracao_periodos INTEGER NOT NULL, "
        "periodo TEXT NOT NULL DEFAULT 'diurno', "
        "status TEXT NOT NULL DEFAULT 'ativo')"
    )
    conn.execute(
        "INSERT INTO cursos(id, nome, codigo, duracao_periodos) "
        "VALUES(1, 'Curso', 'CURSO', 8)"
    )
    conn.execute(
        "CREATE TABLE matrizes_atividades("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, curso_id INTEGER NOT NULL, "
        "nome TEXT NOT NULL, versao TEXT NOT NULL, descricao TEXT, "
        "status TEXT NOT NULL DEFAULT 'rascunho', data_inicio_vigencia TEXT, "
        "data_fim_vigencia TEXT, horas_aac_obrigatorias INTEGER NOT NULL DEFAULT 160, "
        "horas_extensao_obrigatorias INTEGER NOT NULL DEFAULT 80, "
        "matriz_origem_id INTEGER, created_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    conn.execute(
        "INSERT INTO matrizes_atividades(id, curso_id, nome, versao) "
        "VALUES(11, 1, 'Matriz', '1')"
    )
    version_column = ", atividade_versao_id INTEGER" if requisicoes_version_column else ""
    conn.execute(f"CREATE TABLE requisicoes(id INTEGER PRIMARY KEY{version_column})")


def _create_version_table(conn, variant):
    if variant == "missing_numero":
        tail = VERSAO_SUFFIX + ", UNIQUE(atividade_base_id, norma_id))"
    elif variant == "old_unique_base_norma":
        tail = (
            "    numero_versao INTEGER NOT NULL DEFAULT 1,\n"
            + VERSAO_SUFFIX
            + ", UNIQUE(atividade_base_id, norma_id))"
        )
    elif variant == "default_zero":
        tail = (
            "    numero_versao INTEGER NOT NULL DEFAULT 0,\n"
            + VERSAO_SUFFIX
            + ")"
        )
    elif variant == "partial_index":
        tail = (
            "    numero_versao INTEGER NOT NULL DEFAULT 1 "
            "CHECK(numero_versao >= 1),\n"
            + VERSAO_SUFFIX
            + ")"
        )
    elif variant == "canonical":
        tail = (
            "    numero_versao INTEGER NOT NULL DEFAULT 1 "
            "CHECK(numero_versao >= 1),\n"
            + VERSAO_SUFFIX
            + ")"
        )
    else:
        raise AssertionError(variant)
    conn.execute(VERSAO_PREFIX + tail)
    if variant == "partial_index":
        conn.execute(
            "CREATE UNIQUE INDEX idx_atividade_versao_base_num "
            "ON atividade_versao(atividade_base_id, numero_versao) "
            "WHERE numero_versao >= 1"
        )
    elif variant == "canonical":
        conn.execute(
            "CREATE UNIQUE INDEX idx_atividade_versao_base_num "
            "ON atividade_versao(atividade_base_id, numero_versao)"
        )


def _record_v1_v2(conn):
    conn.execute(
        "CREATE TABLE schema_migrations("
        "version INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, "
        "applied_at TEXT NOT NULL DEFAULT (datetime('now')), details_json TEXT)"
    )
    conn.executemany(
        "INSERT INTO schema_migrations(version, name) VALUES(?, ?)",
        ((1, "baseline_schema_management"), (2, "normalize_atividades_schema")),
    )
    conn.execute("PRAGMA user_version = 2")


def _seed_legacy_core(
    conn,
    variant="missing_numero",
    *,
    record_v1_v2=True,
    requisicoes_version_column=True,
):
    _create_prerequisites(
        conn, requisicoes_version_column=requisicoes_version_column
    )
    conn.execute(ATIVIDADE_BASE_DDL)
    conn.execute(NORMA_ATIVIDADE_DDL)
    _create_version_table(conn, variant)
    conn.executemany(
        "INSERT INTO atividade_base(id, nome_conceito, descricao) VALUES(?, ?, ?)",
        ((1, "Base 1", "D1"), (2, "Base 2", "D2")),
    )
    conn.executemany(
        "INSERT INTO norma_atividade(id, codigo, eixo, revisao, nome) "
        "VALUES(?, ?, ?, ?, ?)",
        (
            (1, "N-1", "AAC", "R1", "Norma 1"),
            (2, "N-2", "AAC", "R2", "Norma 2"),
        ),
    )
    shared = (
        "id, atividade_base_id, norma_id, codigo_normativo, eixo, grupo, "
        "ch_por_evento, limite_semestre, limite_total, observacao_aluno, "
        "observacao_admin, documentos_json, vigencia_inicio, vigencia_fim, "
        "status, versao_anterior_id, created_at"
    )
    rows = (
        (1, 1, 1, "N-1", "AAC", "G1", 10, 11, 12, "OA1", "OD1", '["a"]', "2024-01", None, "ativa", None, "2024-01-01"),
        (2, 1, 2, "N-2", "AAC", "G2", 20, 21, 22, "OA2", "OD2", None, "2024-02", "2025-02", "rascunho", 1, "2024-02-01"),
        (5, 2, 1, "N-1", "AAC", "G3", 30, 31, 32, "OA3", "OD3", "", None, None, "inativa", None, "2024-03-01"),
    )
    if variant == "missing_numero":
        conn.executemany(
            f"INSERT INTO atividade_versao({shared}) VALUES({','.join('?' for _ in range(17))})",
            rows,
        )
    else:
        conn.executemany(
            f"INSERT INTO atividade_versao({shared}, numero_versao) "
            f"VALUES({','.join('?' for _ in range(18))})",
            tuple(row + (number,) for row, number in zip(rows, (1, 2, 1))),
        )
    conn.execute(
        "UPDATE sqlite_sequence SET seq=40 WHERE name='atividade_versao'"
    )
    db_maintenance.ensure_atividade_versioning_leaf_tables(conn)
    db_maintenance.ensure_atividade_versioning_leaf_triggers(conn)
    db_maintenance.ensure_atividade_versioning_leaf_indexes(conn)
    conn.execute(
        "INSERT INTO atividade_transicao("
        "id, from_atividade_versao_id, to_atividade_versao_id, tipo_transicao, "
        "justificativa, created_at) VALUES(21, 1, 2, 'mesmo_eixo', 'keep', '2024-04-01')"
    )
    conn.execute(
        "INSERT INTO matriz_norma(id, matriz_id, norma_id, created_at) "
        "VALUES(22, 11, 1, '2024-04-02')"
    )
    conn.execute(
        "INSERT INTO matriz_atividade_versao_item("
        "id, matriz_id, atividade_versao_id, created_at) "
        "VALUES(23, 11, 2, '2024-04-03')"
    )
    conn.execute(
        "INSERT INTO atividade_legacy_map("
        "id, atividade_id_legacy, atividade_base_id, status, created_at) "
        "VALUES(24, 101, 1, 'mapeada', '2024-04-04')"
    )
    if requisicoes_version_column:
        conn.execute(
            "INSERT INTO requisicoes(id, atividade_versao_id) VALUES(25, 1)"
        )
    if record_v1_v2:
        _record_v1_v2(conn)
    conn.commit()


def _migration_rows(conn):
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone():
        return ()
    return tuple(
        (row["version"], row["name"])
        for row in conn.execute(
            "SELECT version, name FROM schema_migrations ORDER BY version"
        )
    )


def _snapshot(conn):
    objects = tuple(
        tuple(row)
        for row in conn.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_autoindex%' ORDER BY type, name"
        )
    )
    data = {}
    for table in (
        "atividade_base",
        "norma_atividade",
        "atividade_versao",
        "atividade_transicao",
        "matriz_norma",
        "matriz_atividade_versao_item",
        "atividade_legacy_map",
        "requisicoes",
        "schema_migrations",
        "sqlite_sequence",
    ):
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone():
            data[table] = tuple(
                tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY 1")
            )
    return objects, data


def _named_objects(conn, object_type):
    return tuple(
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type=? AND name NOT LIKE 'sqlite_autoindex%' "
            "ORDER BY name",
            (object_type,),
        )
    )


def test_registry_is_exactly_v1_v2_v3_without_historical_rewrite():
    assert db_maintenance.SCHEMA_VERSION == 3
    assert tuple((version, name) for version, name, _ in db_maintenance.SCHEMA_MIGRATIONS) == (
        (1, "baseline_schema_management"),
        (2, "normalize_atividades_schema"),
        (3, V3_NAME),
    )


def test_fresh_early_checkpoint_skips_v3_then_direct_owner_and_final_pass_record_it():
    conn = _connection()
    try:
        assert db_maintenance.apply_early_schema_migrations(conn)["schema_version"] == 0
        _create_prerequisites(conn)
        db_maintenance.ensure_atividade_versioning_schema(conn)
        assert _migration_rows(conn) == ()
        result = db_maintenance.apply_schema_migrations(conn)
        assert result["schema_version"] == 3
        assert _migration_rows(conn) == (
            (1, "baseline_schema_management"),
            (2, "normalize_atividades_schema"),
            (3, V3_NAME),
        )
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
    finally:
        conn.close()


@pytest.mark.parametrize(
    "variant",
    (
        "missing_numero",
        "old_unique_base_norma",
        "default_zero",
        "partial_index",
        "canonical",
    ),
)
def test_v3_normalizes_every_supported_legacy_variant_and_preserves_all_data(variant):
    conn = _connection()
    try:
        _seed_legacy_core(conn, variant)
        parents_before = tuple(
            tuple(row)
            for row in conn.execute(
                "SELECT * FROM atividade_base ORDER BY id"
            )
        ), tuple(
            tuple(row)
            for row in conn.execute(
                "SELECT * FROM norma_atividade ORDER BY id"
            )
        )
        children_before = {
            table: tuple(
                tuple(row)
                for row in conn.execute(
                    "SELECT id, atividade_versao_id FROM requisicoes ORDER BY id"
                    if table == "requisicoes"
                    else f"SELECT * FROM {table} ORDER BY id"
                )
            )
            for table in (
                "atividade_transicao",
                "matriz_norma",
                "matriz_atividade_versao_item",
                "atividade_legacy_map",
                "requisicoes",
            )
        }

        result = db_maintenance.apply_early_schema_migrations(conn)

        assert result["applied_now"] == [3]
        assert _migration_rows(conn)[-1] == (3, V3_NAME)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert parents_before == (
            tuple(tuple(row) for row in conn.execute("SELECT * FROM atividade_base ORDER BY id")),
            tuple(tuple(row) for row in conn.execute("SELECT * FROM norma_atividade ORDER BY id")),
        )
        assert children_before == {
            table: tuple(
                tuple(row)
                for row in conn.execute(
                    "SELECT id, atividade_versao_id FROM requisicoes ORDER BY id"
                    if table == "requisicoes"
                    else f"SELECT * FROM {table} ORDER BY id"
                )
            )
            for table in children_before
        }
        versions = tuple(
            tuple(row)
            for row in conn.execute(
                "SELECT id, atividade_base_id, norma_id, codigo_normativo, eixo, grupo, "
                "ch_por_evento, limite_semestre, limite_total, observacao_aluno, "
                "observacao_admin, documentos_json, vigencia_inicio, vigencia_fim, "
                "numero_versao, status, versao_anterior_id, created_at "
                "FROM atividade_versao ORDER BY id"
            )
        )
        assert versions == (
            (1, 1, 1, "N-1", "AAC", "G1", 10.0, 11.0, 12.0, "OA1", "OD1", '["a"]', "2024-01", None, 1, "ativa", None, "2024-01-01"),
            (2, 1, 2, "N-2", "AAC", "G2", 20.0, 21.0, 22.0, "OA2", "OD2", None, "2024-02", "2025-02", 2, "rascunho", 1, "2024-02-01"),
            (5, 2, 1, "N-1", "AAC", "G3", 30.0, 31.0, 32.0, "OA3", "OD3", "", None, None, 1, "inativa", None, "2024-03-01"),
        )
        assert conn.execute(
            "SELECT seq FROM sqlite_sequence WHERE name='atividade_versao'"
        ).fetchone()[0] == 40
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='atividade_versao_new'"
        ).fetchone()
        assert set(CORE_TRIGGERS) <= set(_named_objects(conn, "trigger"))
        assert set(LEAF_TRIGGERS) <= set(_named_objects(conn, "trigger"))
        assert set(CORE_INDEXES) <= set(_named_objects(conn, "index"))
        assert set(LEAF_INDEXES) <= set(_named_objects(conn, "index"))
        for name, (table, columns, unique) in CORE_INDEXES.items():
            row = next(
                row for row in conn.execute(f"PRAGMA index_list({table})") if row[1] == name
            )
            assert bool(row[2]) is unique
            assert row[4] == 0
            assert tuple(
                index_row[2]
                for index_row in conn.execute(f"PRAGMA index_info({name})")
            ) == columns
        assert {
            row[1] for row in conn.execute("PRAGMA table_info(requisicoes)")
        } >= {
            "atividade_versao_id",
            "regra_snapshot_json",
            "codigo_normativo_snapshot",
        }
    finally:
        conn.close()


@pytest.mark.parametrize(
    ("mutation", "match"),
    (
        ("extra_column", "unsupported activity-versioning core"),
        ("missing_parent", "partial activity-versioning core"),
        ("orphan_temp", "preexisting atividade_versao_new"),
        ("invalid_number", "invalid numero_versao"),
    ),
)
def test_unsupported_partial_or_contradictory_core_hard_stops_before_mutation(
    mutation, match
):
    conn = _connection()
    try:
        _seed_legacy_core(conn, "canonical")
        if mutation == "extra_column":
            conn.execute("ALTER TABLE atividade_versao ADD COLUMN alien TEXT")
        elif mutation == "missing_parent":
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute("DROP TABLE norma_atividade")
            conn.execute("PRAGMA foreign_keys = ON")
        elif mutation == "orphan_temp":
            conn.execute("CREATE TABLE atividade_versao_new(residue TEXT)")
            conn.execute("INSERT INTO atividade_versao_new VALUES('keep')")
        else:
            conn.execute("PRAGMA ignore_check_constraints = ON")
            conn.execute("UPDATE atividade_versao SET numero_versao=0 WHERE id=1")
            conn.execute("PRAGMA ignore_check_constraints = OFF")
        conn.commit()
        probe = ExecuteProbe(conn)
        with pytest.raises(db_maintenance.SchemaMigrationStateError, match=match):
            db_maintenance.apply_early_schema_migrations(probe)
        forbidden = (
            "PRAGMA FOREIGN_KEYS = OFF",
            "BEGIN IMMEDIATE",
            "CREATE TABLE ATIVIDADE_VERSAO_NEW",
            "INSERT INTO SCHEMA_MIGRATIONS",
            "PRAGMA USER_VERSION = 3",
        )
        assert not any(
            token in statement
            for statement in probe.statements
            for token in forbidden
        )
        if mutation == "orphan_temp":
            assert conn.execute("SELECT * FROM atividade_versao_new").fetchone()[0] == "keep"
    finally:
        conn.close()


def test_recorded_v3_physical_contradiction_hard_stops_before_mutation():
    conn = _connection()
    try:
        _seed_legacy_core(conn, "canonical")
        conn.execute(
            "INSERT INTO schema_migrations(version, name) VALUES(3, ?)", (V3_NAME,)
        )
        conn.execute("PRAGMA user_version = 3")
        conn.commit()
        probe = ExecuteProbe(conn)
        with pytest.raises(
            db_maintenance.SchemaMigrationStateError, match="recorded v3"
        ):
            db_maintenance.apply_early_schema_migrations(probe)
        assert not any(
            token in statement
            for statement in probe.statements
            for token in ("PRAGMA FOREIGN_KEYS = OFF", "BEGIN IMMEDIATE")
        )
    finally:
        conn.close()


@pytest.mark.parametrize(
    ("fail_token", "has_compat_column"),
    (
        ("CREATE TABLE ATIVIDADE_VERSAO_NEW", True),
        ("INSERT INTO ATIVIDADE_VERSAO_NEW", True),
        ("DROP TABLE ATIVIDADE_VERSAO", True),
        ("ALTER TABLE ATIVIDADE_VERSAO_NEW RENAME", True),
        ("DELETE FROM SQLITE_SEQUENCE", True),
        ("CREATE TRIGGER IF NOT EXISTS TRG_ATIVIDADE_VERSAO", True),
        ("CREATE INDEX IF NOT EXISTS IDX_NORMA_ATIVIDADE_CODIGO", True),
        ("ALTER TABLE REQUISICOES ADD COLUMN ATIVIDADE_VERSAO_ID", False),
        ("INSERT INTO SCHEMA_MIGRATIONS", True),
        ("PRAGMA USER_VERSION = 3", True),
    ),
)
def test_each_material_failure_rolls_back_schema_data_metadata_and_fk_state(
    fail_token, has_compat_column
):
    conn = _connection()
    try:
        _seed_legacy_core(
            conn,
            "missing_numero",
            requisicoes_version_column=has_compat_column,
        )
        before = _snapshot(conn)
        probe = ExecuteProbe(conn, fail_token)
        with pytest.raises(InjectedFailure):
            db_maintenance.apply_early_schema_migrations(probe)
        assert probe.failed, fail_token
        assert _snapshot(conn) == before
        assert _migration_rows(conn) == (
            (1, "baseline_schema_management"),
            (2, "normalize_atividades_schema"),
        )
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert not conn.in_transaction
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='atividade_versao_new'"
        ).fetchone()
    finally:
        conn.close()


def test_public_orchestrator_is_caller_owned_non_destructive_and_exactly_ordered():
    function = db_maintenance.ensure_atividade_versioning_schema
    source = inspect.getsource(function)
    lowered = source.lower()
    for forbidden in (
        ".commit(",
        ".rollback(",
        "savepoint",
        "executescript",
        "pragma foreign_keys",
        "drop table",
        "alter table atividade_versao rename",
    ):
        assert forbidden not in lowered
    tree = ast.parse(source)
    calls = [
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    expected = (
        "ensure_matriz_atividade_links_table",
        "ensure_activity_versioning_core_tables",
        "ensure_atividade_versioning_leaf_tables",
        "ensure_activity_versioning_core_triggers",
        "ensure_atividade_versioning_leaf_triggers",
        "ensure_requisicoes_versioning_compatibility_schema",
        "ensure_activity_versioning_core_indexes",
        "ensure_atividade_versioning_leaf_indexes",
        "ensure_requisicoes_versioning_compatibility_index",
    )
    positions = [calls.index(name) for name in expected]
    assert positions == sorted(positions)


def test_v3_migration_does_not_commit_or_rollback_unrelated_caller_work():
    conn = _connection()
    try:
        _seed_legacy_core(conn, "canonical", record_v1_v2=False)
        conn.execute("CREATE TABLE unrelated(value TEXT)")
        conn.commit()
        conn.execute("BEGIN")
        conn.execute("INSERT INTO unrelated VALUES('caller-owned')")
        with pytest.raises(RuntimeError, match="active transaction"):
            db_maintenance.apply_early_schema_migrations(conn)
        assert conn.in_transaction
        assert conn.execute("SELECT value FROM unrelated").fetchone()[0] == "caller-owned"
        conn.rollback()
        assert conn.execute("SELECT COUNT(*) FROM unrelated").fetchone()[0] == 0
    finally:
        conn.close()


def test_source_owns_v3_and_main_no_longer_defines_legacy_rebuild_symbols():
    project_root = Path(__file__).resolve().parents[1]
    main_tree = ast.parse((project_root / "main.py").read_text(encoding="utf-8"))
    maintenance_tree = ast.parse(
        (project_root / "app" / "db_maintenance.py").read_text(encoding="utf-8")
    )
    legacy = {
        "_needs_atividade_versao_migration",
        "_needs_atividade_versao_default_fix",
        "_needs_index_hardening",
        "_recreate_atividade_versao",
        "_migrate_atividade_versao_to_numero_versao",
        "_fix_atividade_versao_default",
        "ensure_atividade_versioning_schema",
    }
    main_functions = {
        node.name for node in main_tree.body if isinstance(node, ast.FunctionDef)
    }
    maintenance_functions = {
        node.name for node in maintenance_tree.body if isinstance(node, ast.FunctionDef)
    }
    assert not (legacy & main_functions)
    assert "ensure_atividade_versioning_schema" in maintenance_functions
    assert "_VERSAO_NEW_DDL" not in {
        target.id
        for node in main_tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
