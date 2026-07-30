from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

import main
from app import db as app_db
from app import db_maintenance


TARGET_COLUMNS = (
    "id",
    "grupo",
    "nome",
    "descricao",
    "limite_horas",
    "tipo_atividade",
    "tem_limitacao",
    "tipo_limitacao",
    "limite_horas_total",
    "limite_horas_semestral",
    "documentos_json",
)
TARGET_TABLE_INFO = (
    ("id", "INTEGER", 0, None, 1),
    ("grupo", "TEXT", 1, None, 0),
    ("nome", "TEXT", 1, None, 0),
    ("descricao", "TEXT", 0, None, 0),
    ("limite_horas", "INTEGER", 0, None, 0),
    ("tipo_atividade", "TEXT", 1, "'Acadêmica Complementar'", 0),
    ("tem_limitacao", "BOOLEAN", 0, "0", 0),
    ("tipo_limitacao", "TEXT", 0, None, 0),
    ("limite_horas_total", "INTEGER", 0, None, 0),
    ("limite_horas_semestral", "INTEGER", 0, None, 0),
    ("documentos_json", "TEXT", 0, None, 0),
)


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _table_exists(conn, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _columns(conn) -> tuple[str, ...]:
    return tuple(row["name"] for row in conn.execute("PRAGMA table_info(atividades)"))


def _table_info(conn) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (row["name"], row["type"], row["notnull"], row["dflt_value"], row["pk"])
        for row in conn.execute("PRAGMA table_info(atividades)")
    )


def _migration_rows(conn) -> tuple[tuple[int, str], ...]:
    if not _table_exists(conn, "schema_migrations"):
        return ()
    return tuple(
        (int(row[0]), str(row[1]))
        for row in conn.execute(
            "SELECT version, name FROM schema_migrations ORDER BY version"
        )
    )


def _create_current_schema(conn) -> None:
    conn.execute(
        """
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
    )


def _create_ten_column_schema(conn) -> None:
    conn.execute(
        """
        CREATE TABLE atividades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            grupo TEXT NOT NULL,
            nome TEXT NOT NULL UNIQUE,
            descricao TEXT,
            limite_horas INTEGER,
            tipo_atividade TEXT,
            tem_limitacao BOOLEAN DEFAULT 0,
            tipo_limitacao TEXT,
            limite_horas_total INTEGER,
            limite_horas_semestral INTEGER
        )
        """
    )


def _create_legacy_without_descricao(conn) -> None:
    conn.execute(
        """
        CREATE TABLE atividades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            grupo TEXT NOT NULL,
            nome TEXT NOT NULL UNIQUE,
            limite_horas INTEGER,
            tipo_atividade TEXT,
            tem_limitacao BOOLEAN,
            tipo_limitacao TEXT,
            limite_horas_total INTEGER,
            limite_horas_semestral INTEGER
        )
        """
    )


def _record_v1(conn) -> None:
    db_maintenance.ensure_schema_migrations_table(conn)
    conn.execute(
        "INSERT INTO schema_migrations(version, name) VALUES (?, ?)",
        (1, "baseline_schema_management"),
    )


def _seed_fk_dependents(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE alunos(id INTEGER PRIMARY KEY);
        CREATE TABLE usuarios(id INTEGER PRIMARY KEY);
        CREATE TABLE requisicoes(
            id INTEGER PRIMARY KEY,
            aluno_id INTEGER,
            atividade_id INTEGER NOT NULL,
            admin_id INTEGER,
            FOREIGN KEY(atividade_id) REFERENCES atividades(id) ON DELETE RESTRICT ON UPDATE CASCADE
        );
        CREATE TABLE cursos(id INTEGER PRIMARY KEY);
        CREATE TABLE matrizes_atividades(
            id INTEGER PRIMARY KEY,
            curso_id INTEGER NOT NULL REFERENCES cursos(id)
        );
        CREATE TABLE matrizes_atividades_itens(
            id INTEGER PRIMARY KEY,
            matriz_id INTEGER NOT NULL REFERENCES matrizes_atividades(id) ON DELETE CASCADE,
            atividade_id INTEGER NOT NULL REFERENCES atividades(id) ON DELETE CASCADE
        );
        CREATE TABLE atividade_base(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome_conceito TEXT NOT NULL UNIQUE,
            descricao TEXT,
            status TEXT NOT NULL DEFAULT 'ativo' CHECK(status IN ('ativo', 'inativo')),
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE atividade_legacy_map(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            atividade_id_legacy INTEGER NOT NULL UNIQUE,
            atividade_base_id INTEGER,
            status TEXT NOT NULL DEFAULT 'pendente'
                CHECK(status IN ('pendente', 'mapeada', 'revisar')),
            observacao_admin TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(atividade_id_legacy) REFERENCES atividades(id) ON DELETE RESTRICT,
            FOREIGN KEY(atividade_base_id) REFERENCES atividade_base(id) ON DELETE SET NULL
        );
        INSERT INTO cursos VALUES(1);
        INSERT INTO matrizes_atividades VALUES(1, 1);
        INSERT INTO atividade_base(id, nome_conceito) VALUES(1, 'Base legado');
        INSERT INTO requisicoes VALUES(1, NULL, 7, NULL);
        INSERT INTO matrizes_atividades_itens VALUES(1, 1, 7);
        INSERT INTO atividade_legacy_map(
            id, atividade_id_legacy, atividade_base_id
        ) VALUES(1, 7, 1);
        """
    )


def _child_rows(conn) -> dict[str, tuple[tuple[object, ...], ...]]:
    return {
        table: tuple(tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY id"))
        for table in (
            "requisicoes",
            "matrizes_atividades_itens",
            "atividade_legacy_map",
        )
    }


class _ExecuteProbe:
    def __init__(self, conn: sqlite3.Connection, *, fail_stage: str | None = None):
        self._conn = conn
        self.fail_stage = fail_stage
        self.rebuild_creates = 0
        self.statements: list[str] = []

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def execute(self, sql, parameters=()):
        normalized = " ".join(str(sql).split()).upper()
        self.statements.append(normalized)
        stage = None
        if "CREATE TABLE ATIVIDADES__NEW" in normalized:
            self.rebuild_creates += 1
            stage = "create"
        elif normalized.startswith("INSERT INTO ATIVIDADES__NEW"):
            stage = "copy"
        elif normalized.startswith("DROP TABLE ATIVIDADES"):
            stage = "drop"
        elif normalized.startswith("ALTER TABLE ATIVIDADES__NEW RENAME"):
            stage = "rename"
        elif normalized.startswith("INSERT INTO SCHEMA_MIGRATIONS") and parameters:
            if int(parameters[0]) == 2:
                stage = "metadata"
        elif normalized.startswith("PRAGMA USER_VERSION = 2"):
            stage = "user_version"
        cursor = self._conn.execute(sql, parameters)
        if stage is not None and stage == self.fail_stage:
            raise RuntimeError(f"injected failure after {stage}")
        return cursor


class _ForeignKeysCannotDisable(_ExecuteProbe):
    def execute(self, sql, parameters=()):
        normalized = " ".join(str(sql).split()).upper()
        if normalized == "PRAGMA FOREIGN_KEYS = OFF":
            self.statements.append(normalized)
            return self._conn.execute("SELECT 1")
        return super().execute(sql, parameters)


def test_registry_preserves_v1_v2_and_bounded_runner_reports_actual_version():
    assert db_maintenance.SCHEMA_VERSION == 3
    assert tuple((version, name) for version, name, _ in db_maintenance.SCHEMA_MIGRATIONS) == (
        (1, "baseline_schema_management"),
        (2, "normalize_atividades_schema"),
        (3, "normalize_activity_versioning_core"),
    )
    assert len({version for version, _, _ in db_maintenance.SCHEMA_MIGRATIONS}) == 3

    conn = _connection()
    try:
        _create_current_schema(conn)
        result_v1 = db_maintenance.apply_schema_migrations(conn, through_version=1)
        assert result_v1["schema_version"] == 1
        assert result_v1["target_schema_version"] == 3
        assert result_v1["applied_now"] == [1]
        assert _migration_rows(conn) == ((1, "baseline_schema_management"),)

        result_v2 = db_maintenance.apply_schema_migrations(conn, through_version=2)
        assert result_v2["schema_version"] == 2
        assert result_v2["target_schema_version"] == 3
        assert result_v2["applied_now"] == [2]
        assert _migration_rows(conn) == (
            (1, "baseline_schema_management"),
            (2, "normalize_atividades_schema"),
        )
    finally:
        conn.close()


def test_absent_atividades_is_not_prematurely_recorded_by_early_checkpoint():
    conn = _connection()
    try:
        result = db_maintenance.apply_early_schema_migrations(conn)
        assert result["schema_version"] == 0
        assert result["applied_now"] == []
        assert not _table_exists(conn, "schema_migrations")
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
        assert conn.in_transaction is False
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        conn.close()


def test_ten_column_upgrade_adds_documentos_json_and_preserves_data():
    conn = _connection()
    try:
        _create_ten_column_schema(conn)
        conn.execute(
            """
            INSERT INTO atividades(
                id, grupo, nome, descricao, limite_horas, tipo_atividade,
                tem_limitacao, tipo_limitacao, limite_horas_total,
                limite_horas_semestral
            ) VALUES(7, 'G', 'Nome', 'Descrição', 12, '', NULL, 'total', 9, 3)
            """
        )
        _record_v1(conn)
        conn.commit()

        result = db_maintenance.apply_early_schema_migrations(conn)

        assert result["applied_now"] == [2]
        assert _columns(conn) == TARGET_COLUMNS
        assert _table_info(conn) == TARGET_TABLE_INFO
        assert dict(conn.execute("SELECT * FROM atividades WHERE id=7").fetchone()) == {
            "id": 7,
            "grupo": "G",
            "nome": "Nome",
            "descricao": "Descrição",
            "limite_horas": 12,
            "tipo_atividade": "Acadêmica Complementar",
            "tem_limitacao": 0,
            "tipo_limitacao": "total",
            "limite_horas_total": 9,
            "limite_horas_semestral": 3,
            "documentos_json": None,
        }
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.in_transaction is False
    finally:
        conn.close()


@pytest.mark.parametrize(
    ("documentos_json", "expected"),
    [
        ('{"arquivo":"certificado.pdf"}', '{"arquivo":"certificado.pdf"}'),
        ("", ""),
        (None, None),
        ('{"texto":"ação ☃ 漢字"}', '{"texto":"ação ☃ 漢字"}'),
    ],
)
def test_current_eleven_column_shape_records_v2_without_rebuild(
    documentos_json, expected
):
    conn = _connection()
    try:
        _create_current_schema(conn)
        conn.execute(
            """
            INSERT INTO atividades(
                id, grupo, nome, descricao, limite_horas, tipo_atividade,
                tem_limitacao, tipo_limitacao, limite_horas_total,
                limite_horas_semestral, documentos_json
            ) VALUES(7, 'G', 'Nome', NULL, 12, 'Acadêmica Complementar', 0, NULL, NULL, NULL, ?)
            """,
            (documentos_json,),
        )
        conn.commit()
        probe = _ExecuteProbe(conn)

        db_maintenance.apply_early_schema_migrations(probe)

        assert probe.rebuild_creates == 0
        assert conn.execute(
            "SELECT documentos_json FROM atividades WHERE id=7"
        ).fetchone()[0] == expected
        assert _migration_rows(conn) == (
            (1, "baseline_schema_management"),
            (2, "normalize_atividades_schema"),
        )
    finally:
        conn.close()


def test_legacy_missing_descricao_normalizes_blank_and_null_tipo_atividade():
    conn = _connection()
    try:
        _create_legacy_without_descricao(conn)
        conn.executemany(
            """
            INSERT INTO atividades(
                id, grupo, nome, limite_horas, tipo_atividade, tem_limitacao,
                tipo_limitacao, limite_horas_total, limite_horas_semestral
            ) VALUES(?, 'G', ?, 10, ?, ?, NULL, NULL, NULL)
            """,
            ((1, "Blank", "", None), (2, "Null", None, None)),
        )
        conn.commit()

        db_maintenance.apply_early_schema_migrations(conn)

        rows = tuple(
            tuple(row)
            for row in conn.execute(
                "SELECT id, descricao, tipo_atividade, tem_limitacao FROM atividades ORDER BY id"
            )
        )
        assert rows == (
            (1, None, "Acadêmica Complementar", 0),
            (2, None, "Acadêmica Complementar", 0),
        )
    finally:
        conn.close()


def test_path_b_preserves_all_discovered_fk_children_and_sequence():
    conn = _connection()
    try:
        _create_ten_column_schema(conn)
        conn.execute(
            """
            INSERT INTO atividades(
                id, grupo, nome, descricao, limite_horas, tipo_atividade,
                tem_limitacao, tipo_limitacao, limite_horas_total,
                limite_horas_semestral
            ) VALUES(7, 'G', 'Nome', 'Desc', 12, 'Acadêmica Complementar', 0, NULL, NULL, NULL)
            """
        )
        conn.execute("UPDATE sqlite_sequence SET seq=41 WHERE name='atividades'")
        _seed_fk_dependents(conn)
        _record_v1(conn)
        conn.commit()
        children_before = _child_rows(conn)

        db_maintenance.apply_early_schema_migrations(conn)

        assert _child_rows(conn) == children_before
        assert tuple(conn.execute("PRAGMA foreign_key_check")) == ()
        assert conn.execute(
            "SELECT seq FROM sqlite_sequence WHERE name='atividades'"
        ).fetchone()[0] == 41
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        conn.close()


def test_path_a_deferred_foreign_keys_can_cascade_child_loss_with_clean_check():
    conn = _connection()
    try:
        conn.execute("CREATE TABLE atividades(id INTEGER PRIMARY KEY)")
        conn.execute(
            """
            CREATE TABLE atividade_child(
                id INTEGER PRIMARY KEY,
                atividade_id INTEGER NOT NULL
                    REFERENCES atividades(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute("INSERT INTO atividades VALUES(7)")
        conn.execute("INSERT INTO atividade_child VALUES(1, 7)")
        conn.commit()

        conn.execute("BEGIN IMMEDIATE")
        conn.execute("PRAGMA defer_foreign_keys = ON")
        conn.execute("DROP TABLE atividades")

        assert conn.execute("SELECT COUNT(*) FROM atividade_child").fetchone()[0] == 0
        assert tuple(conn.execute("PRAGMA foreign_key_check")) == ()

        conn.rollback()
        assert conn.execute("SELECT COUNT(*) FROM atividades").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM atividade_child").fetchone()[0] == 1
    finally:
        conn.close()


@pytest.mark.parametrize(
    "stage", ("create", "copy", "drop", "rename", "metadata", "user_version")
)
def test_path_b_failure_is_atomic_at_every_physical_and_metadata_stage(stage):
    conn = _connection()
    try:
        _create_ten_column_schema(conn)
        conn.execute(
            """
            INSERT INTO atividades(
                id, grupo, nome, descricao, limite_horas, tipo_atividade,
                tem_limitacao, tipo_limitacao, limite_horas_total,
                limite_horas_semestral
            ) VALUES(7, 'G', 'Nome', 'Desc', 12, 'Acadêmica Complementar', 0, NULL, NULL, NULL)
            """
        )
        _seed_fk_dependents(conn)
        _record_v1(conn)
        conn.commit()
        columns_before = _columns(conn)
        activity_before = tuple(conn.execute("SELECT * FROM atividades WHERE id=7").fetchone())
        children_before = _child_rows(conn)
        probe = _ExecuteProbe(conn, fail_stage=stage)

        with pytest.raises(RuntimeError, match=f"after {stage}"):
            db_maintenance.apply_early_schema_migrations(probe)

        assert conn.in_transaction is False
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert _columns(conn) == columns_before
        assert tuple(conn.execute("SELECT * FROM atividades WHERE id=7").fetchone()) == activity_before
        assert _child_rows(conn) == children_before
        assert _migration_rows(conn) == ((1, "baseline_schema_management"),)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
        assert not _table_exists(conn, "atividades__new")
        assert tuple(conn.execute("PRAGMA foreign_key_check")) == ()
    finally:
        conn.close()


def test_path_b_rejects_existing_transaction_without_committing_or_rolling_back_caller_work():
    conn = _connection()
    try:
        _create_ten_column_schema(conn)
        conn.execute("CREATE TABLE caller_work(value TEXT NOT NULL)")
        conn.commit()
        conn.execute("INSERT INTO caller_work VALUES('pending')")
        assert conn.in_transaction is True

        with pytest.raises(RuntimeError, match="active transaction"):
            db_maintenance.apply_early_schema_migrations(conn)

        assert conn.in_transaction is True
        assert conn.execute("SELECT value FROM caller_work").fetchone()[0] == "pending"
        assert _migration_rows(conn) == ()
        conn.rollback()
        assert conn.execute("SELECT COUNT(*) FROM caller_work").fetchone()[0] == 0
    finally:
        conn.close()


def test_path_b_fails_before_begin_when_foreign_keys_cannot_be_disabled():
    conn = _connection()
    try:
        _create_ten_column_schema(conn)
        conn.commit()
        probe = _ForeignKeysCannotDisable(conn)

        with pytest.raises(RuntimeError, match="disable foreign key"):
            db_maintenance.apply_early_schema_migrations(probe)

        assert conn.in_transaction is False
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert _columns(conn) != TARGET_COLUMNS
        assert _migration_rows(conn) == ()
    finally:
        conn.close()


def test_unknown_source_shape_is_rejected_before_destructive_rebuild():
    conn = _connection()
    try:
        _create_ten_column_schema(conn)
        conn.execute("ALTER TABLE atividades ADD COLUMN unknown_legacy_data TEXT")
        conn.execute(
            "INSERT INTO atividades(id, grupo, nome, limite_horas, unknown_legacy_data) "
            "VALUES(7, 'G', 'Nome', 12, 'preserve-me')"
        )
        conn.commit()
        probe = _ExecuteProbe(conn)

        with pytest.raises(RuntimeError, match="unsupported atividades schema"):
            db_maintenance.apply_early_schema_migrations(probe)

        assert not any(sql.startswith("DROP TABLE ATIVIDADES") for sql in probe.statements)
        assert "unknown_legacy_data" in _columns(conn)
        assert conn.execute(
            "SELECT unknown_legacy_data FROM atividades WHERE id=7"
        ).fetchone()[0] == "preserve-me"
        assert _migration_rows(conn) == ()
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
    finally:
        conn.close()


def test_preexisting_temporary_table_is_a_hard_stop_without_cleanup_or_drop():
    conn = _connection()
    try:
        _create_ten_column_schema(conn)
        conn.execute("CREATE TABLE atividades__new(residue TEXT)")
        conn.execute("INSERT INTO atividades__new VALUES('preserve-residue')")
        conn.commit()
        probe = _ExecuteProbe(conn)

        with pytest.raises(RuntimeError, match="preexisting atividades__new"):
            db_maintenance.apply_early_schema_migrations(probe)

        assert not any(sql.startswith("DROP TABLE ATIVIDADES") for sql in probe.statements)
        assert _table_exists(conn, "atividades")
        assert _table_exists(conn, "atividades__new")
        assert conn.execute("SELECT residue FROM atividades__new").fetchone()[0] == "preserve-residue"
        assert _migration_rows(conn) == ()
    finally:
        conn.close()


def test_v2_is_one_time_and_later_physical_drift_fails_instead_of_repairing():
    conn = _connection()
    try:
        _create_ten_column_schema(conn)
        conn.commit()
        first = _ExecuteProbe(conn)
        db_maintenance.apply_early_schema_migrations(first)
        assert first.rebuild_creates == 1

        second = _ExecuteProbe(conn)
        result = db_maintenance.apply_early_schema_migrations(second)
        assert result["applied_now"] == []
        assert second.rebuild_creates == 0

        conn.execute("ALTER TABLE atividades ADD COLUMN unauthorized_drift TEXT")
        conn.commit()
        drift = _ExecuteProbe(conn)
        with pytest.raises(RuntimeError, match="recorded v2"):
            db_maintenance.apply_early_schema_migrations(drift)
        assert drift.rebuild_creates == 0
        assert "unauthorized_drift" in _columns(conn)
        assert _migration_rows(conn)[-1] == (2, "normalize_atividades_schema")
    finally:
        conn.close()


def test_user_version_v2_with_legacy_schema_is_a_hard_stop_before_rebuild():
    conn = _connection()
    try:
        _create_ten_column_schema(conn)
        conn.execute("PRAGMA user_version = 2")
        conn.commit()
        probe = _ExecuteProbe(conn)

        with pytest.raises(RuntimeError, match="user_version.*physical schema"):
            db_maintenance.apply_early_schema_migrations(probe)

        forbidden = (
            "PRAGMA FOREIGN_KEYS",
            "BEGIN IMMEDIATE",
            "CREATE TABLE ATIVIDADES__NEW",
            "INSERT INTO SCHEMA_MIGRATIONS",
            "PRAGMA USER_VERSION =",
        )
        assert not any(
            token in statement
            for statement in probe.statements
            for token in forbidden
        )
        assert probe.rebuild_creates == 0
        assert _columns(conn) != TARGET_COLUMNS
        assert _migration_rows(conn) == ()
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        conn.close()


def _run_init_on_temp_database(tmp_path: Path, init_name: str, legacy: bool):
    database_path = tmp_path / f"{init_name}_{'legacy' if legacy else 'fresh'}.db"
    if legacy:
        seed = sqlite3.connect(database_path)
        seed.row_factory = sqlite3.Row
        _create_ten_column_schema(seed)
        seed.execute(
            """
            INSERT INTO atividades(
                id, grupo, nome, descricao, limite_horas, tipo_atividade,
                tem_limitacao, tipo_limitacao, limite_horas_total,
                limite_horas_semestral
            ) VALUES(7, 'G', 'Legado', 'Desc', 12, '', NULL, NULL, NULL, NULL)
            """
        )
        seed.commit()
        seed.close()

    original_main_database = main.DATABASE
    original_app_database = app_db.DATABASE
    original_env_database = os.environ.get("APP_DATABASE")
    original_config_database = main.app.config.get("DATABASE_PATH")
    try:
        os.environ["APP_DATABASE"] = str(database_path)
        main.DATABASE = str(database_path)
        app_db.DATABASE = str(database_path)
        main.app.config["DATABASE_PATH"] = str(database_path)
        with main.app.app_context():
            app_db.close_db_connection(None)
            if init_name == "main":
                main.init_db()
            else:
                app_db.init_db()
            conn = app_db.get_db_connection()
            columns = _columns(conn)
            info = _table_info(conn)
            migrations = _migration_rows(conn)
            user_version = conn.execute("PRAGMA user_version").fetchone()[0]
            legacy_row = (
                dict(conn.execute("SELECT * FROM atividades WHERE id=7").fetchone())
                if legacy
                else None
            )
            app_db.close_db_connection(None)
        return columns, info, migrations, user_version, legacy_row
    finally:
        main.DATABASE = original_main_database
        app_db.DATABASE = original_app_database
        main.app.config["DATABASE_PATH"] = original_config_database
        if original_env_database is None:
            os.environ.pop("APP_DATABASE", None)
        else:
            os.environ["APP_DATABASE"] = original_env_database


@pytest.mark.parametrize("legacy", (False, True))
def test_dual_init_paths_converge_only_the_atividades_schema_and_metadata(tmp_path, legacy):
    main_result = _run_init_on_temp_database(tmp_path, "main", legacy)
    app_result = _run_init_on_temp_database(tmp_path, "app_db", legacy)

    assert main_result[:4] == app_result[:4] == (
        TARGET_COLUMNS,
        TARGET_TABLE_INFO,
        (
            (1, "baseline_schema_management"),
            (2, "normalize_atividades_schema"),
            (3, "normalize_activity_versioning_core"),
        ),
        3,
    )
    if legacy:
        for result in (main_result, app_result):
            row = result[4]
            assert row["id"] == 7
            assert row["nome"] == "Legado"
            assert row["descricao"] == "Desc"
            assert row["tipo_atividade"] == "Acadêmica Complementar"
            assert row["tem_limitacao"] == 0
            assert row["documentos_json"] is None
