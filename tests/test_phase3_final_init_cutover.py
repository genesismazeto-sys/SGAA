import ast
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from flask import Flask

from app import db as app_db
from app import db_maintenance


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAIN_PATH = PROJECT_ROOT / "main.py"
APP_DB_PATH = PROJECT_ROOT / "app" / "db.py"


class _CommitTrackingConnection:
    def __init__(self, connection):
        self.connection = connection
        self.commit_attempts = 0
        self.successful_commits = 0
        self.rollback_attempts = 0
        self.fail_sql_fragment = None
        self.fail_commit = False
        self.failure_in_transaction = None

    @property
    def in_transaction(self):
        return self.connection.in_transaction

    def execute(self, sql, parameters=()):
        if self.fail_sql_fragment and self.fail_sql_fragment in sql:
            self.failure_in_transaction = self.connection.in_transaction
            raise RuntimeError("injected core table failure")
        return self.connection.execute(sql, parameters)

    def commit(self):
        self.commit_attempts += 1
        if self.fail_commit:
            self.failure_in_transaction = self.connection.in_transaction
            raise RuntimeError("injected final commit failure")
        self.connection.commit()
        self.successful_commits += 1

    def rollback(self):
        self.rollback_attempts += 1
        return self.connection.rollback()

    def __getattr__(self, name):
        return getattr(self.connection, name)


def _runtime_app(database_path):
    app = Flask("phase3-final-init-cutover")
    app.config.update(
        TESTING=True,
        DATABASE_PATH=str(database_path),
        LOCAL_BACKUP_DIR=str(database_path.parent / "local"),
        CLOUD_BACKUP_DIR=str(database_path.parent / "cloud"),
        CLOUD_SYNC_INTERVAL_SECONDS=600,
        EXTERNAL_BACKUP_URL="",
        EXTERNAL_BACKUP_TOKEN="",
        EXTERNAL_BACKUP_ENABLED=False,
        BOOTSTRAP_DEFAULT_ADMIN=False,
    )
    return app


def _schema_snapshot(connection):
    tables = tuple(
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    )
    indexes = tuple(
        row[0]
        for row in connection.execute(
            """
            SELECT name
              FROM sqlite_master
             WHERE type='index' AND name NOT LIKE 'sqlite_autoindex_%'
          ORDER BY name
            """
        ).fetchall()
    )
    rows = {
        table: connection.execute(
            f'SELECT COUNT(*) FROM "{table.replace(chr(34), chr(34) * 2)}"'
        ).fetchone()[0]
        for table in tables
    }
    migrations = ()
    if "schema_migrations" in tables:
        migrations = tuple(
            tuple(row)
            for row in connection.execute(
                "SELECT version, name FROM schema_migrations ORDER BY version"
            ).fetchall()
        )
    return {
        "tables": tables,
        "indexes": indexes,
        "rows": rows,
        "schema_migrations": migrations,
        "user_version": connection.execute("PRAGMA user_version").fetchone()[0],
        "foreign_keys": connection.execute("PRAGMA foreign_keys").fetchone()[0],
    }


EMPTY_DURABLE_STATE = {
    "tables": (),
    "indexes": (),
    "rows": {},
    "schema_migrations": (),
    "user_version": 0,
    "foreign_keys": 1,
}
ACCESS_DURABLE_STATE = {
    "tables": (
        "configuracoes_acesso",
        "sqlite_sequence",
        "usuarios",
        "usuarios_permissoes_acesso",
    ),
    "indexes": (
        "idx_usuarios_email",
        "idx_usuarios_permissoes_usuario",
    ),
    "rows": {
        "configuracoes_acesso": 5,
        "sqlite_sequence": 0,
        "usuarios": 0,
        "usuarios_permissoes_acesso": 0,
    },
    "schema_migrations": (),
    "user_version": 0,
    "foreign_keys": 1,
}
APP_SETTINGS_STRUCTURAL_DURABLE_STATE = {
    **ACCESS_DURABLE_STATE,
    "tables": (
        "configuracoes_acesso",
        "configuracoes_app",
        "sqlite_sequence",
        "usuarios",
        "usuarios_permissoes_acesso",
    ),
    "rows": {
        **ACCESS_DURABLE_STATE["rows"],
        "configuracoes_app": 0,
    },
}


def _top_level_functions(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def test_app_db_is_sole_init_owner_and_main_exports_owner_identity():
    app_functions = _top_level_functions(APP_DB_PATH)
    main_functions = _top_level_functions(MAIN_PATH)

    assert app_functions.count("init_db") == 1
    assert "init_db" not in main_functions
    assert "_init_db_impl" not in app_functions
    assert "_get_main_db_helpers" not in app_functions

    source = APP_DB_PATH.read_text(encoding="utf-8")
    assert "import main" not in source
    assert "sys.modules" not in source
    assert "importlib" not in source

    import main

    assert main.init_db is app_db.init_db
    assert main.get_preferred_matriz_for_curso is app_db.get_preferred_matriz_for_curso


def test_preferred_matrix_owner_preserves_exact_selection_contract():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        assert app_db.get_preferred_matriz_for_curso(conn, None) is None
        assert app_db.get_preferred_matriz_for_curso(conn, 0) is None
        assert app_db.get_preferred_matriz_for_curso(conn, 1) is None

        rows = (
            (1, "Other", "1", "arquivada", "2030-01-01"),
            (1, "Draft", "1", "rascunho", "2031-01-01"),
            (1, "Active old", "1", "ativa", "2025-01-01"),
            (1, "Current low id", "1", "vigente", "2026-01-01"),
            (1, "Current high id", "1", "ATIVA", "2026-01-01"),
            (2, "Other course", "1", "ativa", "2099-01-01"),
        )
        conn.executemany(
            """
            INSERT INTO matrizes_atividades
                (curso_id, nome, versao, status, data_inicio_vigencia)
            VALUES (?, ?, ?, ?, ?)
            """,
            rows,
        )

        selected = app_db.get_preferred_matriz_for_curso(conn, 1)
        assert isinstance(selected, sqlite3.Row)
        assert selected["nome"] == "Current high id"
    finally:
        conn.close()


def test_factory_init_is_complete_explicit_and_does_not_import_main(tmp_path):
    database_path = tmp_path / "factory-init.db"
    code = r'''
import os
import sqlite3
import sys
from pathlib import Path

assert "main" not in sys.modules
from app import create_app
import app.backup_settings as backup_settings
import app.db as db

assert "main" not in sys.modules
app = create_app()
app.config.update(
    TESTING=True,
    DATABASE_PATH=os.environ["APP_DATABASE"],
    LOCAL_BACKUP_DIR=str(Path(os.environ["APP_DATABASE"]).parent / "local"),
    CLOUD_BACKUP_DIR=str(Path(os.environ["APP_DATABASE"]).parent / "cloud"),
    CLOUD_SYNC_INTERVAL_SECONDS=777,
    EXTERNAL_BACKUP_URL="",
    EXTERNAL_BACKUP_TOKEN="",
    EXTERNAL_BACKUP_ENABLED=False,
    BOOTSTRAP_DEFAULT_ADMIN=False,
)
with app.app_context():
    db.init_db()
    assert backup_settings._get_backup_settings_runtime_app() is app
    conn = db.get_db_connection()
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    required = {
        "usuarios", "alunos", "turmas", "atividades", "requisicoes",
        "requisicao_arquivos", "reportes", "cursos", "configuracoes_acesso",
        "configuracoes_app", "configuracoes_backup", "cloud_accounts",
        "backup_logs", "cloud_drive_settings", "matrizes_atividades",
        "atividade_base", "atividade_versao", "schema_migrations",
    }
    assert required <= tables, sorted(required - tables)
    versions = tuple(
        row[0]
        for row in conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
    )
    assert versions == (1, 2, 3)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
    db.init_db()
assert "main" not in sys.modules
'''
    environment = os.environ.copy()
    environment.update(
        APP_DATABASE=str(database_path),
        PYTHONUTF8="1",
        PYTHONDONTWRITEBYTECODE="1",
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", code],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert database_path.is_file()
    assert not database_path.with_name(database_path.name + "-wal").exists()
    assert not database_path.with_name(database_path.name + "-shm").exists()


def test_seed_tool_uses_factory_owner_without_main_and_is_idempotent(tmp_path):
    database_path = tmp_path / "seed-tool.db"
    code = r'''
import os
import importlib.util
import sqlite3
import sys
from pathlib import Path

assert "main" not in sys.modules
tool_path = Path.cwd() / "tools" / "seed_demo_data.py"
spec = importlib.util.spec_from_file_location("sg_aa_seed_demo_data", tool_path)
assert spec is not None and spec.loader is not None
seed_demo_data = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed_demo_data)

seed_demo_data.seed()
seed_demo_data.seed()
assert "main" not in sys.modules

conn = sqlite3.connect(os.environ["APP_DATABASE"])
try:
    assert conn.execute(
        "SELECT COUNT(*) FROM cursos WHERE codigo IN ('TAC', 'ENGPROD', 'ADM')"
    ).fetchone()[0] == 3
    assert conn.execute(
        "SELECT COUNT(*) FROM usuarios WHERE email LIKE 'aluno%@example.com'"
    ).fetchone()[0] == 3
    assert conn.execute(
        "SELECT COUNT(*) FROM alunos WHERE matricula IN ('2025001', '2025002', '2025003')"
    ).fetchone()[0] == 3
finally:
    conn.close()
'''
    environment = os.environ.copy()
    environment.update(
        APP_DATABASE=str(database_path),
        PYTHONUTF8="1",
        PYTHONDONTWRITEBYTECODE="1",
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", code],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("Seed demo concluído.") == 2
    assert database_path.is_file()
    assert not database_path.with_name(database_path.name + "-wal").exists()
    assert not database_path.with_name(database_path.name + "-shm").exists()


def test_app_db_logger_is_module_owned_without_handler_configuration():
    source = APP_DB_PATH.read_text(encoding="utf-8")
    assert "logging.getLogger(__name__)" in source
    assert "RotatingFileHandler" not in source
    assert "addHandler" not in source
    assert app_db.logger.name == "app.db"


@pytest.mark.parametrize(
    ("stage", "expected_in_transaction", "expected_durable_state"),
    (
        ("before_early_migration", False, EMPTY_DURABLE_STATE),
        ("after_early_migration", False, EMPTY_DURABLE_STATE),
        ("during_core_table_creation", False, EMPTY_DURABLE_STATE),
        ("during_settings_ensure", False, ACCESS_DURABLE_STATE),
        ("during_matrix_schema", True, APP_SETTINGS_STRUCTURAL_DURABLE_STATE),
        (
            "before_final_migration_pass",
            True,
            APP_SETTINGS_STRUCTURAL_DURABLE_STATE,
        ),
        (
            "immediately_before_final_commit",
            True,
            APP_SETTINGS_STRUCTURAL_DURABLE_STATE,
        ),
    ),
)
def test_bootstrap_failure_postconditions_match_each_accepted_transaction_owner(
    monkeypatch,
    tmp_path,
    stage,
    expected_in_transaction,
    expected_durable_state,
):
    database_path = tmp_path / f"failure-{stage}.db"
    raw = sqlite3.connect(database_path)
    raw.row_factory = sqlite3.Row
    raw.execute("PRAGMA foreign_keys = ON")
    tracked = _CommitTrackingConnection(raw)
    monkeypatch.setattr(app_db, "get_db_connection", lambda: tracked)
    injection_state = {}

    original_early = app_db.apply_early_schema_migrations

    def injected_failure(*args, **kwargs):
        injection_state["in_transaction"] = tracked.in_transaction
        raise RuntimeError(f"injected {stage}")

    if stage == "before_early_migration":
        monkeypatch.setattr(app_db, "apply_early_schema_migrations", injected_failure)
    elif stage == "after_early_migration":
        def fail_after_early(*args, **kwargs):
            original_early(*args, **kwargs)
            injection_state["in_transaction"] = tracked.in_transaction
            raise RuntimeError(f"injected {stage}")

        monkeypatch.setattr(app_db, "apply_early_schema_migrations", fail_after_early)
    elif stage == "during_core_table_creation":
        tracked.fail_sql_fragment = "CREATE TABLE IF NOT EXISTS usuarios"
    elif stage == "during_settings_ensure":
        monkeypatch.setattr(app_db, "ensure_app_settings_schema", injected_failure)
    elif stage == "during_matrix_schema":
        monkeypatch.setattr(app_db, "ensure_turmas_matriz_schema", injected_failure)
    elif stage == "before_final_migration_pass":
        monkeypatch.setattr(app_db, "apply_schema_migrations", injected_failure)
    elif stage == "immediately_before_final_commit":
        tracked.fail_commit = True

    app = _runtime_app(database_path)
    with app.app_context(), pytest.raises(RuntimeError, match="injected"):
        app_db.init_db()

    observed_injection_state = (
        tracked.failure_in_transaction
        if tracked.failure_in_transaction is not None
        else injection_state["in_transaction"]
    )
    assert observed_injection_state is expected_in_transaction
    assert tracked.in_transaction is expected_in_transaction
    assert raw.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert tracked.successful_commits == 0
    if stage == "immediately_before_final_commit":
        assert tracked.commit_attempts == 1
    else:
        assert tracked.commit_attempts == 0

    caller_visible_state = _schema_snapshot(raw)
    observer = sqlite3.connect(database_path)
    observer.execute("PRAGMA foreign_keys = ON")
    try:
        observer_while_failing_connection_is_open = _schema_snapshot(observer)
    finally:
        observer.close()

    assert observer_while_failing_connection_is_open == expected_durable_state
    if expected_in_transaction:
        assert set(caller_visible_state["tables"]) > set(
            expected_durable_state["tables"]
        )
    else:
        assert caller_visible_state == expected_durable_state

    raw.close()
    verification = sqlite3.connect(database_path)
    verification.execute("PRAGMA foreign_keys = ON")
    try:
        assert _schema_snapshot(verification) == expected_durable_state
    finally:
        verification.close()


def test_early_migration_commit_survives_later_bootstrap_failure_without_partial_bootstrap(
    monkeypatch, tmp_path
):
    database_path = tmp_path / "legacy-early-commit.db"
    raw = sqlite3.connect(database_path)
    raw.row_factory = sqlite3.Row
    raw.execute("PRAGMA foreign_keys = ON")
    raw.execute(
        """
        CREATE TABLE atividades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            grupo TEXT NOT NULL,
            nome TEXT NOT NULL UNIQUE,
            limite_horas INTEGER
        )
        """
    )
    raw.execute(
        "INSERT INTO atividades (grupo, nome, limite_horas) VALUES (?, ?, ?)",
        ("1", "Legacy", 10),
    )
    raw.commit()

    tracked = _CommitTrackingConnection(raw)
    monkeypatch.setattr(app_db, "get_db_connection", lambda: tracked)

    def fail_settings(*args, **kwargs):
        raise RuntimeError("injected post-migration bootstrap failure")

    monkeypatch.setattr(app_db, "ensure_app_settings_schema", fail_settings)
    app = _runtime_app(database_path)
    with app.app_context(), pytest.raises(RuntimeError, match="post-migration"):
        app_db.init_db()

    assert tracked.successful_commits == 1
    assert tracked.commit_attempts == 1
    assert tracked.in_transaction is False
    assert raw.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    raw.close()

    verification = sqlite3.connect(database_path)
    verification.row_factory = sqlite3.Row
    verification.execute("PRAGMA foreign_keys = ON")
    try:
        state = _schema_snapshot(verification)
        assert state["tables"] == (
            "atividades",
            "configuracoes_acesso",
            "schema_migrations",
            "sqlite_sequence",
            "usuarios",
            "usuarios_permissoes_acesso",
        )
        assert state["indexes"] == (
            "idx_usuarios_email",
            "idx_usuarios_permissoes_usuario",
        )
        assert state["schema_migrations"] == (
            (1, "baseline_schema_management"),
            (2, "normalize_atividades_schema"),
        )
        assert state["user_version"] == 2
        assert state["foreign_keys"] == 1
        assert state["rows"]["configuracoes_acesso"] == 5
        assert state["rows"]["usuarios"] == 0
        assert len(verification.execute("PRAGMA table_info(atividades)").fetchall()) == 11
    finally:
        verification.close()


def test_failure_inside_early_migration_rolls_back_only_the_isolated_unit(
    monkeypatch, tmp_path
):
    database_path = tmp_path / "legacy-early-rollback.db"
    raw = sqlite3.connect(database_path)
    raw.row_factory = sqlite3.Row
    raw.execute("PRAGMA foreign_keys = ON")
    raw.execute(
        """
        CREATE TABLE atividades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            grupo TEXT NOT NULL,
            nome TEXT NOT NULL UNIQUE,
            limite_horas INTEGER
        )
        """
    )
    raw.execute(
        "INSERT INTO atividades (grupo, nome, limite_horas) VALUES (?, ?, ?)",
        ("1", "Legacy", 10),
    )
    raw.commit()

    tracked = _CommitTrackingConnection(raw)
    monkeypatch.setattr(app_db, "get_db_connection", lambda: tracked)
    migrations_with_failing_v2 = []
    for version, name, migration in db_maintenance.SCHEMA_MIGRATIONS:
        if version == 2:

            def fail_after_v2_work(connection, original=migration):
                original(connection)
                raise RuntimeError("injected inside early migration v2")

            migrations_with_failing_v2.append((version, name, fail_after_v2_work))
        else:
            migrations_with_failing_v2.append((version, name, migration))
    monkeypatch.setattr(
        db_maintenance, "SCHEMA_MIGRATIONS", tuple(migrations_with_failing_v2)
    )

    app = _runtime_app(database_path)
    with app.app_context(), pytest.raises(RuntimeError, match="inside early"):
        app_db.init_db()

    expected = {
        "tables": ("atividades", "sqlite_sequence"),
        "indexes": (),
        "rows": {"atividades": 1, "sqlite_sequence": 1},
        "schema_migrations": (),
        "user_version": 0,
        "foreign_keys": 1,
    }
    assert tracked.in_transaction is False
    assert tracked.commit_attempts == 0
    assert tracked.successful_commits == 0
    assert tracked.rollback_attempts == 1
    assert _schema_snapshot(raw) == expected

    observer = sqlite3.connect(database_path)
    observer.execute("PRAGMA foreign_keys = ON")
    try:
        assert _schema_snapshot(observer) == expected
        assert tuple(
            row[1] for row in observer.execute("PRAGMA table_info(atividades)")
        ) == ("id", "grupo", "nome", "limite_horas")
    finally:
        observer.close()
        raw.close()


def test_failure_after_successful_early_migration_preserves_only_committed_versions(
    monkeypatch, tmp_path
):
    database_path = tmp_path / "legacy-after-early-commit.db"
    raw = sqlite3.connect(database_path)
    raw.row_factory = sqlite3.Row
    raw.execute("PRAGMA foreign_keys = ON")
    raw.execute(
        """
        CREATE TABLE atividades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            grupo TEXT NOT NULL,
            nome TEXT NOT NULL UNIQUE,
            limite_horas INTEGER
        )
        """
    )
    raw.execute(
        "INSERT INTO atividades (grupo, nome, limite_horas) VALUES (?, ?, ?)",
        ("1", "Legacy", 10),
    )
    raw.commit()

    tracked = _CommitTrackingConnection(raw)
    monkeypatch.setattr(app_db, "get_db_connection", lambda: tracked)
    original_early = app_db.apply_early_schema_migrations

    def fail_after_early_commit(*args, **kwargs):
        original_early(*args, **kwargs)
        raise RuntimeError("injected after successful early migration")

    monkeypatch.setattr(
        app_db, "apply_early_schema_migrations", fail_after_early_commit
    )
    app = _runtime_app(database_path)
    with app.app_context(), pytest.raises(RuntimeError, match="after successful"):
        app_db.init_db()

    expected = {
        "tables": ("atividades", "schema_migrations", "sqlite_sequence"),
        "indexes": (),
        "rows": {
            "atividades": 1,
            "schema_migrations": 2,
            "sqlite_sequence": 1,
        },
        "schema_migrations": (
            (1, "baseline_schema_management"),
            (2, "normalize_atividades_schema"),
        ),
        "user_version": 2,
        "foreign_keys": 1,
    }
    assert tracked.in_transaction is False
    assert tracked.commit_attempts == 1
    assert tracked.successful_commits == 1
    assert tracked.rollback_attempts == 0
    assert _schema_snapshot(raw) == expected

    raw.close()
    observer = sqlite3.connect(database_path)
    observer.execute("PRAGMA foreign_keys = ON")
    try:
        assert _schema_snapshot(observer) == expected
        assert len(observer.execute("PRAGMA table_info(atividades)").fetchall()) == 11
    finally:
        observer.close()
