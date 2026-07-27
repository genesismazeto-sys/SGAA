import ast
import importlib
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DB_PATH = PROJECT_ROOT / "app" / "db.py"
DB_MAINTENANCE_PATH = PROJECT_ROOT / "app" / "db_maintenance.py"
MAIN_PATH = PROJECT_ROOT / "main.py"
CONTRACT_PATH = PROJECT_ROOT / "docs" / "refactor" / "PHASE3_SCHEMA_STARTUP_TRANSACTION_CONTRACT.md"
CONTRACT_RELPATH = "docs/refactor/PHASE3_SCHEMA_STARTUP_TRANSACTION_CONTRACT.md"

EXPECTED_DIRECT_MAINTENANCE_IMPORTS = (
    "apply_schema_migrations",
    "ensure_matriz_atividade_links_table",
    "ensure_matrizes_atividades_table",
    "ensure_reportes_table",
    "ensure_requisicao_alert_receipts_table",
    "ensure_usuario_access_schema",
    "ensure_usuario_profile_schema",
)

EXPECTED_LAZY_BRIDGE = (
    "ensure_atividades_schema_current",
    "ensure_atividade_versioning_schema",
    "ensure_backup_settings_schema",
    "get_preferred_matriz_for_curso",
    "logger",
)

EXPECTED_MAIN_INIT_CALLERS = {
    "main.py": ("_restore_database_from_source", "<module>"),
    "tests/test_activity_versioning_phase_b_schema.py": (
        "test_phase_b_schema_creates_additive_tables_and_columns",
        "test_phase_b_allows_normas_and_versions_with_constraints",
        "test_phase_b_requires_justification_for_aac_para_aeu_transition",
        "test_phase_b_keeps_legacy_requisicoes_flow_and_nullable_snapshot_fields",
        "test_phase_b1_validation_fails_when_same_base_has_active_aac_and_aeu_without_transition",
        "test_phase_b1_validation_passes_with_valid_aac_para_aeu_transition",
        "test_phase_b1_validation_passes_for_new_aeu_base_without_aac_history",
        "test_phase_b1_validation_passes_for_two_aac_versions_in_same_base",
        "test_phase_b1_validation_fails_for_cross_base_aac_para_aeu_transition",
        "test_phase_b1_rejects_invalid_transition_type",
        "test_phase_b1_rejects_duplicate_matriz_norma",
        "test_phase_b1_rejects_duplicate_matriz_atividade_versao_item",
        "test_phase_b_init_db_works_on_existing_legacy_database",
    ),
    "tests/test_activity_versioning_phase_d1_diagnostic.py": ("isolated_legacy_client",),
    "tests/test_activity_versioning_phase_d5_structured_hours.py": ("isolated_legacy_client",),
    "tests/test_activity_versioning_resolver.py": ("isolated_legacy_client",),
    "tests/test_admin_activity_version_catalog_create.py": ("client",),
    "tests/test_admin_activity_version_catalog_readonly.py": ("client",),
    "tests/test_admin_activity_version_catalog_version_activate.py": ("client",),
    "tests/test_admin_activity_version_catalog_version_edit.py": ("client",),
    "tests/test_admin_activity_version_catalog_version_form.py": ("client",),
    "tests/test_admin_add_aluno_csrf.py": ("isolated_client_csrf",),
    "tests/test_admin_arquivos.py": ("client",),
    "tests/test_admin_atividade_delete.py": ("client",),
    "tests/test_admin_atividade_description.py": ("client",),
    "tests/test_admin_atividades_filters.py": ("client",),
    "tests/test_admin_atividades_import.py": ("client",),
    "tests/test_admin_aux_sections.py": ("client",),
    "tests/test_admin_dashboard_request_alert.py": ("client",),
    "tests/test_admin_database_backups.py": (
        "admin_client",
        "test_database_module_requires_explicit_permission_for_consultivo_admin",
    ),
    "tests/test_admin_matrizes.py": ("client",),
    "tests/test_admin_matrizes_csrf_ui.py": ("client",),
    "tests/test_admin_messages.py": ("client",),
    "tests/test_admin_reportes.py": ("client",),
    "tests/test_admin_requisicao_api_scope.py": ("client",),
    "tests/test_admin_requisicao_create.py": ("client",),
    "tests/test_admin_requisicao_list_scope.py": ("client",),
    "tests/test_admin_requisicao_matrix_scope.py": ("client",),
    "tests/test_admin_requisicao_process_ui.py": ("client",),
    "tests/test_admin_snapshot_diagnostics.py": ("client",),
    "tests/test_admin_toolbar_filters.py": ("client",),
    "tests/test_admin_turmas_matriz.py": ("client",),
    "tests/test_admin_version_visibility_ui.py": ("client",),
    "tests/test_aluno_matrix_scope.py": ("client", "isolated_dashboard_client"),
    "tests/test_aluno_progresso.py": ("client",),
    "tests/test_aluno_requisicao_update_alert.py": ("client",),
    "tests/test_aluno_toolbar_filters.py": ("client",),
    "tests/test_app_basic.py": ("client",),
    "tests/test_csrf_admin_flows.py": ("isolated_client_csrf",),
    "tests/test_csrf_e2e_critical_flows.py": ("isolated_client_e2e",),
    "tests/test_csrf_inventory_audit.py": ("_setup_isolated_csrf_clients",),
    "tests/test_db_schema_maintenance.py": ("test_init_db_registers_schema_version",),
    "tests/test_filter_schema_contract.py": ("client",),
    "tests/test_pagination.py": ("setup_module",),
    "tests/test_phase_0_smoke_flows.py": ("smoke_env",),
    "tests/test_release_admin_actions.py": ("isolated_client",),
    "tests/test_release_admin_actions_csrf.py": ("isolated_client_csrf",),
    "tests/test_release_admin_crud.py": ("isolated_client",),
    "tests/test_release_backend_core.py": ("isolated_client", "isolated_client_csrf"),
    "tests/test_release_backup_restore_local.py": ("test_release_backup_restore_local_isolated",),
    "tests/test_release_clean_database.py": (
        "test_release_clean_database_installation_and_idempotence",
        "test_release_clean_database_installation_and_idempotence",
    ),
    "tests/test_release_requisicoes_flow.py": ("isolated_client",),
    "tests/test_security.py": ("client",),
    "tests/versioned_test_support.py": ("isolated_versioned_app_env",),
    "tools/smoke_test.py": ("<module>",),
    "tools/smoke_test_admin.py": ("<module>",),
    "tools/smoke_test_rbac_permissions.py": ("run",),
}

EXPECTED_BOOTSTRAP_EVENTS = (
    "lazy-map",
    *(f"lazy:{name}" for name in EXPECTED_LAZY_BRIDGE),
    "connection",
    "table:usuarios",
    "helper:ensure_usuario_access_schema",
    "helper:ensure_usuario_profile_schema",
    "helper:ensure_backup_settings_schema",
    "table:alunos",
    "table:turmas",
    "table:atividades",
    "table:requisicoes",
    "table:requisicao_arquivos",
    "helper:ensure_reportes_table",
    "helper:ensure_atividades_schema_current",
    "helper:ensure_requisicao_alert_receipts_table",
    "table:cursos",
    "helper:ensure_matrizes_atividades_table",
    "helper:ensure_matriz_atividade_links_table",
    "helper:ensure_atividade_versioning_schema",
    "helper:get_preferred_matriz_for_curso",
    "helper:apply_schema_migrations",
    "commit",
)

CONTRACT_SECTIONS = (
    "## 1. Scope and purpose",
    "## 2. Current connection authority",
    "## 3. Current dual-init entry-point inventory",
    "## 4. Exact caller inventory",
    "## 5. app.db bootstrap sequence",
    "## 6. Schema-owner matrix",
    "## 7. Remaining lazy-bridge matrix",
    "## 8. Migration baseline",
    "## 9. Transaction-boundary matrix",
    "## 10. Known exceptions and technical debt",
    "## 11. Current versus target architecture",
    "## 12. Later owning phases",
    "## 13. Canonical-database safety rules",
    "## 14. Contract change procedure",
    "## 15. Prohibited interpretations",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _tree(path: Path) -> ast.Module:
    return ast.parse(_read(path), filename=str(path))


def _top_level_function(tree: ast.Module, name: str) -> ast.FunctionDef:
    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(matches) == 1
    return matches[0]


def _top_level_names(tree: ast.Module):
    functions = {
        node.name for node in tree.body if isinstance(node, ast.FunctionDef)
    }
    assignments = set()
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        assignments.update(target.id for target in targets if isinstance(target, ast.Name))
    return functions, assignments


def _imported_names(tree: ast.Module, module: str) -> tuple[str, ...]:
    imports = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == module:
            imports.extend(alias.asname or alias.name for alias in node.names)
    return tuple(imports)


def _dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_name(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _dict_return_contract(function: ast.FunctionDef):
    returns = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)
    ]
    assert len(returns) == 1
    mapping = returns[0].value
    keys = tuple(key.value for key in mapping.keys if isinstance(key, ast.Constant))
    values = tuple(_dotted_name(value) for value in mapping.values)
    return keys, values


def _lazy_retrievals(function: ast.FunctionDef):
    entries = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        value = node.value
        if not (
            isinstance(target, ast.Name)
            and isinstance(value, ast.Subscript)
            and isinstance(value.value, ast.Name)
            and value.value.id == "helpers"
            and isinstance(value.slice, ast.Constant)
            and isinstance(value.slice.value, str)
        ):
            continue
        entries.append((node.lineno, target.id, value.slice.value))
    return tuple((target, key) for _, target, key in sorted(entries))


class _InitCallerVisitor(ast.NodeVisitor):
    def __init__(self, relative_path: str, imports: dict[str, tuple[str, str | None]]):
        self.relative_path = relative_path
        self.imports = imports
        self.scope = ["<module>"]
        self.app_context_depth = 0
        self.calls = []

    def visit_FunctionDef(self, node):
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_With(self, node):
        has_app_context = any(
            "app_context" in ast.unparse(item.context_expr) for item in node.items
        )
        self.app_context_depth += int(has_app_context)
        for statement in node.body:
            self.visit(statement)
        self.app_context_depth -= int(has_app_context)

    visit_AsyncWith = visit_With

    def visit_Call(self, node):
        target = self._target(node.func)
        if target:
            self.calls.append(
                (target, self.scope[-1], node.lineno, self.app_context_depth > 0)
            )
        self.generic_visit(node)

    def _target(self, function):
        if isinstance(function, ast.Name):
            if function.id == "_init_db_impl" and self.relative_path == "app/db.py":
                return "app.db._init_db_impl"
            if function.id != "init_db":
                return None
            origin = self.imports.get(function.id)
            if self.relative_path == "main.py" or origin == ("main", "init_db"):
                return "main.init_db"
            if origin == ("app.db", "init_db"):
                return "app.db.init_db"
            return None
        if not (
            isinstance(function, ast.Attribute)
            and function.attr == "init_db"
            and isinstance(function.value, ast.Name)
        ):
            return None
        base = function.value.id
        origin = self.imports.get(base)
        if base == "main" or origin == ("main", None):
            return "main.init_db"
        if origin == ("app.db", None):
            return "app.db.init_db"
        return None


def _tracked_python_files() -> tuple[str, ...]:
    result = subprocess.run(
        ["git", "ls-files", "*.py"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return tuple(path.replace("\\", "/") for path in result.stdout.splitlines())


def _init_callers():
    records = defaultdict(list)
    for relative_path in _tracked_python_files():
        tree = _tree(PROJECT_ROOT / relative_path)
        imports = {}
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports[alias.asname or alias.name] = (alias.name, None)
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imports[alias.asname or alias.name] = (node.module or "", alias.name)
        visitor = _InitCallerVisitor(relative_path, imports)
        visitor.visit(tree)
        for target, scope, line, owns_context in visitor.calls:
            records[target].append((relative_path, scope, line, owns_context))
    return records


def _string_fragments(node: ast.AST) -> str:
    return " ".join(
        child.value
        for child in ast.walk(node)
        if isinstance(child, ast.Constant) and isinstance(child.value, str)
    )


def _direct_calls(function: ast.FunctionDef) -> tuple[str, ...]:
    return tuple(
        name
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        for name in [_dotted_name(node.func)]
        if name is not None
    )


def _transaction_facts(path: Path, function_name: str):
    function = _top_level_function(_tree(path), function_name)
    calls = [node for node in ast.walk(function) if isinstance(node, ast.Call)]
    names = [_dotted_name(node.func) for node in calls]
    sql = "\n".join(
        _string_fragments(node.args[0])
        for node in calls
        if node.args
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"execute", "executescript"}
    ).upper()
    return {
        "commit_method": names.count("conn.commit"),
        "rollback_method": names.count("conn.rollback"),
        "executescript": names.count("conn.executescript"),
        "savepoint": "SAVEPOINT ENSURE_USUARIO_ACCESS_SCHEMA" in sql,
        "rollback_sql": "ROLLBACK TO SAVEPOINT" in sql,
        "begin_sql": "BEGIN;" in sql,
        "commit_sql": "COMMIT;" in sql,
        "foreign_keys_pragma": "PRAGMA FOREIGN_KEYS" in sql,
    }


def _bootstrap_events():
    tree = _tree(APP_DB_PATH)
    function = _top_level_function(tree, "_init_db_impl")
    events = []
    helper_names = {
        "ensure_usuario_access_schema",
        "ensure_usuario_profile_schema",
        "ensure_backup_settings_schema",
        "ensure_reportes_table",
        "ensure_atividades_schema_current",
        "ensure_requisicao_alert_receipts_table",
        "ensure_matrizes_atividades_table",
        "ensure_matriz_atividade_links_table",
        "ensure_atividade_versioning_schema",
        "get_preferred_matriz_for_curso",
        "apply_schema_migrations",
    }
    for node in ast.walk(function):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if (
                isinstance(target, ast.Name)
                and target.id == "helpers"
                and isinstance(node.value, ast.Call)
                and _dotted_name(node.value.func) == "_get_main_db_helpers"
            ):
                events.append((node.lineno, node.col_offset, "lazy-map"))
            elif (
                isinstance(target, ast.Name)
                and isinstance(node.value, ast.Subscript)
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id == "helpers"
                and isinstance(node.value.slice, ast.Constant)
            ):
                events.append(
                    (node.lineno, node.col_offset, f"lazy:{node.value.slice.value}")
                )
        if not isinstance(node, ast.Call):
            continue
        name = _dotted_name(node.func)
        if name == "get_db_connection":
            events.append((node.lineno, node.col_offset, "connection"))
        elif name in helper_names:
            events.append((node.lineno, node.col_offset, f"helper:{name}"))
        elif name == "conn.commit":
            events.append((node.lineno, node.col_offset, "commit"))
        elif name == "conn.execute" and node.args:
            sql = _string_fragments(node.args[0]).upper()
            for table in (
                "usuarios",
                "alunos",
                "turmas",
                "atividades",
                "requisicoes",
                "requisicao_arquivos",
                "cursos",
            ):
                if f"CREATE TABLE IF NOT EXISTS {table.upper()} " in " ".join(sql.split()):
                    events.append((node.lineno, node.col_offset, f"table:{table}"))
    return tuple(event for _, _, event in sorted(events))


def test_connection_authority_exports_pragmas_and_local_sync_noop():
    app_tree = _tree(APP_DB_PATH)
    main_tree = _tree(MAIN_PATH)
    app_functions, app_assignments = _top_level_names(app_tree)
    main_functions, main_assignments = _top_level_names(main_tree)

    assert {"get_db_connection", "close_db_connection", "_sync_database_from_main"} <= app_functions
    assert "DATABASE" in app_assignments
    assert not ({"get_db_connection", "close_db_connection"} & main_functions)
    assert "DATABASE" not in main_assignments
    assert {"DATABASE", "get_db_connection", "close_db_connection"} <= set(
        _imported_names(main_tree, "app.db")
    )

    sync = _top_level_function(app_tree, "_sync_database_from_main")
    assert len(sync.body) == 1
    assert isinstance(sync.body[0], ast.Return)
    assert isinstance(sync.body[0].value, ast.Name)
    assert sync.body[0].value.id == "DATABASE"

    connection_source = ast.get_source_segment(_read(APP_DB_PATH), _top_level_function(app_tree, "get_db_connection"))
    assert connection_source is not None
    assert "sqlite3.Row" in connection_source
    assert "PTBR_NOACCENT" in connection_source
    assert "PRAGMA foreign_keys = ON" in connection_source
    assert "PRAGMA journal_mode = WAL" in connection_source
    assert "PRAGMA synchronous = NORMAL" in connection_source

    app_db = importlib.import_module("app.db")
    main = importlib.import_module("main")
    assert main.DATABASE is app_db.DATABASE
    assert main.get_db_connection is app_db.get_db_connection
    assert main.close_db_connection is app_db.close_db_connection
    assert Path(app_db.DATABASE).resolve() != (PROJECT_ROOT / "database.db").resolve()


def test_dual_init_entry_points_and_exact_caller_manifest():
    app_functions, _ = _top_level_names(_tree(APP_DB_PATH))
    main_functions, _ = _top_level_names(_tree(MAIN_PATH))
    assert {"init_db", "_init_db_impl"} <= app_functions
    assert "init_db" in main_functions

    records = _init_callers()
    actual_main = defaultdict(list)
    for path, scope, _, _ in records["main.init_db"]:
        actual_main[path].append(scope)
    assert {path: tuple(scopes) for path, scopes in actual_main.items()} == EXPECTED_MAIN_INIT_CALLERS
    assert sum(map(len, EXPECTED_MAIN_INIT_CALLERS.values())) == 73

    assert [(path, scope) for path, scope, _, _ in records["app.db.init_db"]] == [
        ("tools/seed_demo_data.py", "seed")
    ]
    assert [(path, scope) for path, scope, _, _ in records["app.db._init_db_impl"]] == [
        ("app/db.py", "init_db")
    ]

    no_explicit_context = {
        (target, path, scope)
        for target, entries in records.items()
        for path, scope, _, owns_context in entries
        if not owns_context
    }
    assert no_explicit_context == {
        ("main.init_db", "main.py", "_restore_database_from_source"),
        ("app.db._init_db_impl", "app/db.py", "init_db"),
    }


def test_exact_direct_import_set_and_five_entry_lazy_bridge():
    app_tree = _tree(APP_DB_PATH)
    assert _imported_names(app_tree, "app.db_maintenance") == EXPECTED_DIRECT_MAINTENANCE_IMPORTS

    lazy_function = _top_level_function(app_tree, "_get_main_db_helpers")
    keys, values = _dict_return_contract(lazy_function)
    assert keys == EXPECTED_LAZY_BRIDGE
    assert values == tuple(f"main.{name}" for name in EXPECTED_LAZY_BRIDGE)

    init_function = _top_level_function(app_tree, "_init_db_impl")
    assert _lazy_retrievals(init_function) == tuple((name, name) for name in EXPECTED_LAZY_BRIDGE)
    assert not (set(EXPECTED_LAZY_BRIDGE) & set(EXPECTED_DIRECT_MAINTENANCE_IMPORTS))


def test_app_db_bootstrap_semantic_order_and_single_final_commit():
    assert _bootstrap_events() == EXPECTED_BOOTSTRAP_EVENTS
    assert EXPECTED_BOOTSTRAP_EVENTS.index("helper:ensure_matrizes_atividades_table") < EXPECTED_BOOTSTRAP_EVENTS.index(
        "helper:ensure_matriz_atividade_links_table"
    ) < EXPECTED_BOOTSTRAP_EVENTS.index("helper:ensure_atividade_versioning_schema")
    assert EXPECTED_BOOTSTRAP_EVENTS.index("helper:apply_schema_migrations") < EXPECTED_BOOTSTRAP_EVENTS.index("commit")
    assert EXPECTED_BOOTSTRAP_EVENTS.count("commit") == 1


def test_schema_migration_metadata_and_historical_baseline_marker():
    tree = _tree(DB_MAINTENANCE_PATH)
    version_nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "SCHEMA_VERSION" for target in node.targets)
    ]
    assert len(version_nodes) == 1
    assert ast.literal_eval(version_nodes[0].value) == 1

    migration_nodes = [
        node
        for node in tree.body
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "SCHEMA_MIGRATIONS"
                for target in node.targets
            )
        )
        or (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "SCHEMA_MIGRATIONS"
        )
    ]
    assert len(migration_nodes) == 1
    migrations = migration_nodes[0].value
    assert isinstance(migrations, (ast.Tuple, ast.List))
    assert len(migrations.elts) == 1
    version, name, function = migrations.elts[0].elts
    assert ast.literal_eval(version) == 1
    assert ast.literal_eval(name) == "baseline_schema_management"
    assert isinstance(function, ast.Name) and function.id == "_migration_v1_baseline"

    baseline = _top_level_function(tree, "_migration_v1_baseline")
    assert len(baseline.body) == 1
    assert isinstance(baseline.body[0], ast.Expr)
    assert isinstance(baseline.body[0].value, ast.Constant)
    assert "baseline versionado" in baseline.body[0].value.value
    assert "bootstrap atual" in baseline.body[0].value.value

    ensure_table = _top_level_function(tree, "ensure_schema_migrations_table")
    table_sql = " ".join(_string_fragments(ensure_table).split()).upper()
    assert "CREATE TABLE IF NOT EXISTS SCHEMA_MIGRATIONS" in table_sql
    assert "VERSION INTEGER PRIMARY KEY" in table_sql
    assert "NAME TEXT NOT NULL" in table_sql
    assert "APPLIED_AT TEXT NOT NULL DEFAULT" in table_sql

    apply = _top_level_function(tree, "apply_schema_migrations")
    apply_source = ast.get_source_segment(_read(DB_MAINTENANCE_PATH), apply)
    assert apply_source is not None
    assert "SELECT version FROM schema_migrations" in apply_source
    assert "for version, name, migration in SCHEMA_MIGRATIONS" in apply_source
    assert "migration(conn)" in apply_source
    assert "INSERT INTO schema_migrations" in apply_source
    assert "PRAGMA user_version" in apply_source


def test_transaction_boundaries_and_known_exceptions_are_explicit():
    caller_owned = {
        DB_MAINTENANCE_PATH: (
            "ensure_schema_migrations_table",
            "apply_schema_migrations",
            "ensure_reportes_table",
            "ensure_usuario_profile_schema",
            "ensure_requisicao_alert_receipts_table",
            "ensure_usuario_access_structural_schema",
            "seed_usuario_access_default_data",
            "normalize_usuario_access_startup_data",
            "ensure_matrizes_atividades_table",
            "ensure_matriz_atividade_links_table",
        ),
        MAIN_PATH: (
            "ensure_app_settings_schema",
            "ensure_backup_settings_schema",
            "ensure_cloud_backup_schema",
            "ensure_turmas_matriz_schema",
            "get_preferred_matriz_for_curso",
        ),
    }
    neutral = {
        "commit_method": 0,
        "rollback_method": 0,
        "executescript": 0,
        "savepoint": False,
        "rollback_sql": False,
        "begin_sql": False,
        "commit_sql": False,
        "foreign_keys_pragma": False,
    }
    for path, names in caller_owned.items():
        for name in names:
            assert _transaction_facts(path, name) == neutral, f"{path.name}:{name}"

    assert _transaction_facts(APP_DB_PATH, "_init_db_impl") == {
        **neutral,
        "commit_method": 1,
    }
    assert _transaction_facts(MAIN_PATH, "init_db") == {
        **neutral,
        "commit_method": 1,
    }
    assert _transaction_facts(APP_DB_PATH, "init_db") == neutral

    access = _transaction_facts(DB_MAINTENANCE_PATH, "ensure_usuario_access_schema")
    assert access == {**neutral, "savepoint": True, "rollback_sql": True}

    atividades = _transaction_facts(MAIN_PATH, "ensure_atividades_schema_current")
    assert atividades == {**neutral, "foreign_keys_pragma": True}

    recreate = _transaction_facts(MAIN_PATH, "_recreate_atividade_versao")
    assert recreate == {
        **neutral,
        "executescript": 1,
        "begin_sql": True,
        "commit_sql": True,
        "foreign_keys_pragma": True,
    }

    main_tree = _tree(MAIN_PATH)
    versioning_calls = _direct_calls(_top_level_function(main_tree, "ensure_atividade_versioning_schema"))
    assert "_migrate_atividade_versao_to_numero_versao" in versioning_calls
    assert "_fix_atividade_versao_default" in versioning_calls
    for delegate in (
        "_migrate_atividade_versao_to_numero_versao",
        "_fix_atividade_versao_default",
    ):
        calls = _direct_calls(_top_level_function(main_tree, delegate))
        assert calls.count("_recreate_atividade_versao") == 1


def test_db_maintenance_import_isolated_and_contract_tests_are_static(tmp_path):
    database_path = tmp_path / "must_not_be_created.db"
    code = (
        "import sys; "
        "assert 'main' not in sys.modules; "
        "import app.db_maintenance as module; "
        "assert module.SCHEMA_VERSION == 1; "
        "assert 'main' not in sys.modules"
    )
    environment = os.environ.copy()
    environment["APP_DATABASE"] = str(database_path)
    result = subprocess.run(
        [sys.executable, "-B", "-c", code],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert not database_path.exists()

    this_tree = _tree(Path(__file__))
    connect_calls = [
        node
        for node in ast.walk(this_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "connect"
    ]
    assert connect_calls == []


def test_canonical_contract_document_and_governance_registration():
    assert CONTRACT_PATH.is_file()
    contract = _read(CONTRACT_PATH)
    for section in CONTRACT_SECTIONS:
        assert contract.count(section) == 1
    assert "current does not mean ideal" in contract
    assert "frozen does not mean permanent" in contract
    assert "compatibility export does not mean defining ownership" in contract
    assert "baseline migration does not define the complete physical schema" in contract

    index = _read(PROJECT_ROOT / "docs" / "DOCUMENTATION_INDEX.md")
    ledger = _read(PROJECT_ROOT / "docs" / "refactor" / "ARCHITECTURE_REFACTOR_LEDGER.md")
    state = _read(PROJECT_ROOT / "PROJECT_STATE.md")
    handoff = _read(PROJECT_ROOT / "AGENT_HANDOFF.md")
    assert CONTRACT_RELPATH in index
    assert (
        index.count(
            "| `PHASE3_SCHEMA_STARTUP_TRANSACTION_CONTRACT.md` | PHASE 3-B5/B6 |"
        )
        == 1
    )
    assert ledger.count(CONTRACT_RELPATH) == 1
    assert CONTRACT_RELPATH in state
    assert CONTRACT_RELPATH in handoff
    assert "PHASE 3-B6 intentional revision" in contract
    assert "The exact five entries" in contract
    assert "Resolved by PHASE 3-B6" in contract
    assert "PHASE 3-B7" in index
