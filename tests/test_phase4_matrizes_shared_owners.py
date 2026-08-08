"""PHASE 4-B5-P — shared-owner contract for the admin-access helpers.

RED-only target: the canonical neutral owner ``app.admin_access`` does not exist
yet and ``main.py`` still defines the five access-context helpers locally.  Once
production moves them, this module must prove, statically and dynamically, that:

  * ``app.admin_access`` defines exactly the five helpers with no route decorators;
  * ``main.py`` imports/re-exports all five by direct object identity and defines
    zero local bodies for them;
  * the module is side-effect free on isolated import (subprocess filesystem
    before/after discipline) and has zero static/dynamic edges to ``main``;
  * no new import cycle appears among ``app.admin_access``, ``app.auth``,
    ``app.db`` and ``app.db_maintenance`` (preserving the existing
    ``app.db_maintenance -> app.auth`` direction);
  * the helper behavior is preserved byte-for-byte from ``main.py`` (SQL,
    normalization, canonical auth functions, transaction neutrality);
  * every current ``main`` consumer resolves the same global callable identities.

All database work uses only temporary/in-memory SQLite connections.  The
institutional database is never opened and no network is used.
"""
from __future__ import annotations

import ast
import inspect
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAIN_PATH = PROJECT_ROOT / "main.py"
ADMIN_ACCESS_PATH = PROJECT_ROOT / "app" / "admin_access.py"
AUTH_PATH = PROJECT_ROOT / "app" / "auth.py"
DB_PATH = PROJECT_ROOT / "app" / "db.py"
DB_MAINTENANCE_PATH = PROJECT_ROOT / "app" / "db_maintenance.py"

ADMIN_ACCESS_HELPERS = {
    "_fetch_user_access_overrides",
    "_build_access_scope_groups_for_level",
    "_load_admin_access_context",
    "_get_current_admin_access_context",
    "_admin_can",
}

# These two write/form helpers must remain local to main.py and absent from
# app.admin_access (they are explicitly out of scope for B5-P).
RELATED_LOCAL_HELPERS = {
    "_persist_user_access_overrides",
    "_parse_access_overrides_from_form",
}

# Every main.py top-level function that directly references one of the five
# helpers as a global.  No wrapper is allowed: each consumer must resolve the
# canonical app.admin_access identity through its __globals__.
# The two Matrizes consumers (admin_editar_matriz, admin_matriz_nova_atividade)
# moved to app.views.admin.matrizes (PHASE 4-B5-R1); the remaining consumers
# below stay in main.py.
#
# UT-3 moves enforce_admin_access_control -> app.web.authz_gate and
# inject_admin_access_helpers -> app.web.context (see
# tests/test_ut3_app_hooks.py). Those two are no longer expected as main.py
# consumers; their canonical-owner identity is asserted separately by
# test_moved_admin_access_consumers_resolve_canonical_identities_in_future_owner_modules
# below, against their future owner modules.
CONSUMER_NAMES = {
    "admin_acesso",
    "uploaded_file",
}
CONSUMER_HELPER_USES = {
    "admin_acesso": {"_load_admin_access_context"},
    "uploaded_file": {"_get_current_admin_access_context", "_admin_can"},
}

# UT-3 future owners for the moved pair, keyed by function name.
MOVED_CONSUMER_HELPER_USES = {
    "enforce_admin_access_control": {"_get_current_admin_access_context", "_admin_can"},
    "inject_admin_access_helpers": {"_get_current_admin_access_context", "_admin_can"},
}
MOVED_CONSUMER_OWNER_MODULE = {
    "enforce_admin_access_control": "app.web.authz_gate",
    "inject_admin_access_helpers": "app.web.context",
}

# The two Matrizes handlers that consume the admin-access context helpers now
# live in app.views.admin.matrizes and must still resolve the canonical
# app.admin_access identities through their module globals.
MATRIZES_MODULE_CONSUMERS = {
    "admin_editar_matriz": {"_get_current_admin_access_context", "_admin_can"},
    "admin_matriz_nova_atividade": {"_get_current_admin_access_context", "_admin_can"},
}

# All Matrizes route handlers moved to app.views.admin.matrizes (PHASE 4-B5-R1).
# This is now a full Matrizes blueprint extraction.
MATRIZES_ROUTE_NAMES = {
    "admin_matrizes",
    "admin_adicionar_matriz",
    "admin_editar_matriz",
    "admin_matriz_nova_atividade",
    "admin_matriz_nova_versao_card",
    "admin_excluir_matrizes",
    "admin_excluir_matriz",
    "admin_matriz_versoes",
    "admin_matriz_versoes_definir",
    "admin_matriz_versoes_remover",
}

NON_ADMIN_CONTEXT = {
    "is_admin": False,
    "access_level": None,
    "access_level_label": None,
    "overrides": {},
    "effective_scopes": {},
    "scope_groups": [],
}


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))


def _top_level_functions(path: Path) -> set[str]:
    return {
        node.name
        for node in _tree(path).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _top_level_bodies(path: Path) -> set[str]:
    return {
        node.name
        for node in _tree(path).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }


def _all_function_names(path: Path) -> set[str]:
    return {
        node.name
        for node in ast.walk(_tree(path))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _imports_from(path: Path, module_name: str) -> set[str]:
    result: set[str] = set()
    for node in _tree(path).body:
        if isinstance(node, ast.ImportFrom) and node.module == module_name:
            result.update(alias.asname or alias.name for alias in node.names)
    return result


def _discover_consumers(path: Path, helpers: set[str]) -> dict[str, set[str]]:
    """Map every top-level main.py function to the helper globals it references."""
    consumers: dict[str, set[str]] = {}
    for node in _tree(path).body:
        if isinstance(node, ast.FunctionDef):
            used = {
                child.id
                for child in ast.walk(node)
                if isinstance(child, ast.Name) and child.id in helpers
            }
            if used:
                consumers[node.name] = used
    return consumers


# ---------------------------------------------------------------------------
# Connection spies
# ---------------------------------------------------------------------------


class TrackingConnection(sqlite3.Connection):
    commit_count = 0
    rollback_count = 0
    close_count = 0

    def commit(self):
        self.commit_count += 1
        return super().commit()

    def rollback(self):
        self.rollback_count += 1
        return super().rollback()

    def close(self):
        self.close_count += 1
        return super().close()


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _SpyConnection:
    """Records the exact SQL/params passed to execute and returns canned rows."""

    def __init__(self, rows):
        self._rows = rows
        self.executed: list[tuple[str, tuple]] = []

    def execute(self, sql, params=()):
        self.executed.append((sql, params))
        return _FakeCursor(self._rows)


def _norm_sql(statements: list[str]) -> list[str]:
    return [" ".join(line.split()) for line in statements]


def _create_access_tables(conn) -> None:
    conn.execute(
        "CREATE TABLE usuarios (id INTEGER PRIMARY KEY, tipo TEXT, nivel_acesso TEXT)"
    )
    conn.execute(
        "CREATE TABLE usuarios_permissoes_acesso ("
        "usuario_id INTEGER, recurso TEXT, escopo TEXT, PRIMARY KEY (usuario_id, recurso))"
    )
    conn.commit()


# ---------------------------------------------------------------------------
# 1. app.admin_access exists with exactly the five helpers and no routes
# ---------------------------------------------------------------------------


def test_admin_access_module_is_importable():
    from app import admin_access

    assert admin_access.__name__ == "app.admin_access"


def test_admin_access_module_defines_exactly_five_helpers_without_routes():
    from app import admin_access

    source = Path(admin_access.__file__).read_text(encoding="utf-8-sig")
    tree = ast.parse(source, filename=str(admin_access.__file__))
    bodies = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    assert bodies == ADMIN_ACCESS_HELPERS
    assert "@app.route" not in source
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                assert "route" not in ast.unparse(decorator)


# ---------------------------------------------------------------------------
# 2/3. main.py defines zero local bodies and re-exports all five by identity
# ---------------------------------------------------------------------------


def test_main_ast_has_zero_local_definitions_for_five_helpers():
    assert not ADMIN_ACCESS_HELPERS & _all_function_names(MAIN_PATH)
    assert not ADMIN_ACCESS_HELPERS & _top_level_functions(MAIN_PATH)


def test_main_imports_all_five_from_app_admin_access():
    assert ADMIN_ACCESS_HELPERS <= _imports_from(MAIN_PATH, "app.admin_access")


def test_main_reexports_five_helpers_by_direct_identity():
    import main
    from app import admin_access

    for name in ADMIN_ACCESS_HELPERS:
        assert getattr(main, name) is getattr(admin_access, name)
        assert getattr(main, name).__module__ == "app.admin_access"


# ---------------------------------------------------------------------------
# 4. app.admin_access has zero static/dynamic edges to main
# ---------------------------------------------------------------------------


def test_admin_access_has_zero_edges_to_main():
    source = ADMIN_ACCESS_PATH.read_text(encoding="utf-8")
    assert "import main" not in source
    tree = ast.parse(source, filename=str(ADMIN_ACCESS_PATH))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name != "main" for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.module != "main"
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"__import__", "eval", "exec"}
    assert "sys.modules" not in source
    assert "importlib" not in source


# ---------------------------------------------------------------------------
# 5. No new import cycle among admin_access / auth / db / db_maintenance
# ---------------------------------------------------------------------------


def _module_edges(paths: dict[str, Path]) -> set[tuple[str, str]]:
    edges: set[tuple[str, str]] = set()
    for module_name, path in paths.items():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module in paths:
                edges.add((module_name, node.module))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imported = alias.name or ""
                    for tracked in paths:
                        if imported == tracked or imported.startswith(tracked + "."):
                            edges.add((module_name, tracked))
    return edges


def _has_cycle(nodes: set[str], edges: set[tuple[str, str]]) -> bool:
    state: dict[str, int] = {}

    def visit(node: str) -> bool:
        state[node] = 1
        for src, dst in edges:
            if src == node and dst in nodes:
                if state.get(dst, 0) == 1:
                    return True
                if state.get(dst, 0) == 0 and visit(dst):
                    return True
        state[node] = 2
        return False

    return any(state.get(node, 0) == 0 and visit(node) for node in nodes)


def test_no_new_import_cycle_among_canonical_access_modules():
    paths = {
        "app.admin_access": ADMIN_ACCESS_PATH,
        "app.auth": AUTH_PATH,
        "app.db": DB_PATH,
        "app.db_maintenance": DB_MAINTENANCE_PATH,
    }
    edges = _module_edges(paths)

    # Existing preserved direction.
    assert ("app.db_maintenance", "app.auth") in edges

    # Prohibited directions through this unit.
    assert ("app.auth", "app.db_maintenance") not in edges
    assert ("app.auth", "app.admin_access") not in edges

    # The four-module graph must remain acyclic.
    assert not _has_cycle(set(paths), edges)


# ---------------------------------------------------------------------------
# 6. Isolated subprocess import is side-effect free
# ---------------------------------------------------------------------------


def test_admin_access_isolated_import_is_side_effect_free(tmp_path):
    runtime = tmp_path / "isolated-admin-access"
    runtime.mkdir(parents=True, exist_ok=True)
    code = r"""
import json
import os
from pathlib import Path
import socket
import sqlite3
import sys

root = Path(os.environ["PHASE4_IMPORT_ROOT"])
root.mkdir(exist_ok=True)

def forbidden(*args, **kwargs):
    raise AssertionError("import-time side effect")

sqlite3.connect = forbidden
socket.create_connection = forbidden
socket.socket.connect = forbidden

from flask import Flask

def forbidden_flask_init(*args, **kwargs):
    raise AssertionError("Flask application constructed at import time")

Flask.__init__ = forbidden_flask_init

before = sorted(path.name for path in root.iterdir())
assert "main" not in sys.modules
import app.admin_access as module
assert "main" not in sys.modules
assert module.__name__ == "app.admin_access"
after = sorted(path.name for path in root.iterdir())
assert before == after == []
assert not Path(os.environ["APP_DATABASE"]).exists()
print(json.dumps({
    "main_imported": False,
    "filesystem_delta": [],
    "database_created": False,
    "flask_app_constructed": False,
}))
"""
    environment = os.environ.copy()
    environment.update(
        {
            "PHASE4_IMPORT_ROOT": str(runtime),
            "APP_DATABASE": str(runtime / "never-created.sqlite3"),
            "APP_UPLOAD_FOLDER": str(runtime / "uploads"),
            "APP_DOCUMENTOS_ALUNOS_FOLDER": str(runtime / "documentos"),
            "APP_LOG_DIR": str(runtime / "logs"),
            "APP_LOCAL_BACKUP_DIR": str(runtime / "backups" / "local"),
            "APP_CLOUD_BACKUP_DIR": str(runtime / "backups" / "cloud"),
            "APP_ENV": "testing",
            "APP_SECRET_KEY": "phase4-matrizes-import-test-secret-key-0000000000",
            "PYTHONPATH": str(PROJECT_ROOT),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUTF8": "1",
        }
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", code],
        cwd=runtime,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {
        "main_imported": False,
        "filesystem_delta": [],
        "database_created": False,
        "flask_app_constructed": False,
    }


# ---------------------------------------------------------------------------
# 7. _fetch_user_access_overrides exact behavior
# ---------------------------------------------------------------------------


def test_fetch_overrides_falsy_id_returns_empty_without_ensure_or_query(monkeypatch):
    from app import admin_access

    ensure_calls = []
    monkeypatch.setattr(admin_access, "ensure_usuario_access_schema", lambda conn: ensure_calls.append(conn))
    spy = _SpyConnection([])

    for falsy in (None, 0, ""):
        assert admin_access._fetch_user_access_overrides(spy, falsy) == {}

    assert ensure_calls == []
    assert spy.executed == []


def test_fetch_overrides_truthy_id_calls_ensure_once_preserves_sql_and_normalizes(monkeypatch):
    from app import admin_access
    from app.auth import ACCESS_RESOURCES_META, normalize_permission_scope

    ensure_calls = []
    monkeypatch.setattr(admin_access, "ensure_usuario_access_schema", lambda conn: ensure_calls.append(conn))
    rows = [
        {"recurso": " matrizes ", "escopo": "Edição"},
        {"recurso": "ALUNOS", "escopo": "leitura"},
        {"recurso": "not_a_resource", "escopo": "full"},
        {"recurso": None, "escopo": "view"},
        {"recurso": "", "escopo": "full"},
    ]
    spy = _SpyConnection(rows)

    result = admin_access._fetch_user_access_overrides(spy, 7)

    assert ensure_calls == [spy]
    assert spy.executed == [
        ("SELECT recurso, escopo FROM usuarios_permissoes_acesso WHERE usuario_id = ?", (7,))
    ]
    assert result == {"matrizes": "edit", "alunos": "view"}
    assert result["matrizes"] == normalize_permission_scope("Edição", "none")
    assert result["alunos"] == normalize_permission_scope("leitura", "none")
    for skipped in ("not_a_resource", None, ""):
        assert skipped not in result
    assert all(resource in ACCESS_RESOURCES_META for resource in result)


# ---------------------------------------------------------------------------
# 8. _build_access_scope_groups_for_level exact shape/ordering/metadata
# ---------------------------------------------------------------------------


def test_build_access_scope_groups_for_level_matches_canonical_pipeline():
    from app import admin_access
    from app.auth import (
        ACCESS_RESOURCE_GROUPS,
        build_access_scope_groups,
        merge_resource_scopes,
        permission_scope_label,
    )

    level = "administrativo"
    overrides = {"acesso": "full"}
    defaults = merge_resource_scopes(level)
    effective = merge_resource_scopes(level, overrides)

    groups = admin_access._build_access_scope_groups_for_level(level, overrides)

    expected = []
    for group in build_access_scope_groups(effective):
        items = []
        for item in group["items"]:
            resource = item["resource"]
            default_scope = defaults.get(resource, "none")
            override_scope = overrides.get(resource)
            items.append(
                {
                    **item,
                    "default_scope": default_scope,
                    "default_scope_label": permission_scope_label(default_scope),
                    "override_scope": override_scope,
                    "override_scope_label": (
                        permission_scope_label(override_scope) if override_scope else None
                    ),
                }
            )
        expected.append({"label": group["label"], "items": items})

    assert groups == expected
    assert [group["label"] for group in groups] == [
        label for label, _ in ACCESS_RESOURCE_GROUPS
    ]
    flat = [item["resource"] for group in groups for item in group["items"]]
    grouped_flat = [resource for _, resources in ACCESS_RESOURCE_GROUPS for resource in resources]
    assert flat == grouped_flat

    item_keys = {
        "resource",
        "label",
        "scope",
        "scope_label",
        "default_scope",
        "default_scope_label",
        "override_scope",
        "override_scope_label",
    }
    assert all(set(item) == item_keys for group in groups for item in group["items"])

    acesso_item = next(
        item for group in groups for item in group["items"] if item["resource"] == "acesso"
    )
    assert acesso_item["default_scope"] == "none"
    assert acesso_item["default_scope_label"] == permission_scope_label("none")
    assert acesso_item["override_scope"] == "full"
    assert acesso_item["override_scope_label"] == permission_scope_label("full")

    no_override = admin_access._build_access_scope_groups_for_level("consultivo", {})
    for group in no_override:
        for item in group["items"]:
            assert item["override_scope"] is None
            assert item["override_scope_label"] is None


# ---------------------------------------------------------------------------
# 9. _load_admin_access_context exact behavior + transaction neutrality
# ---------------------------------------------------------------------------


def test_load_admin_access_context_behavior_and_transaction_neutrality(tmp_path, monkeypatch):
    import main  # noqa: F401  (module must remain importable; no DB access here)
    from app import admin_access
    from app.auth import ACCESS_LEVEL_META, ACCESS_RESOURCE_GROUPS, merge_resource_scopes

    conn = sqlite3.connect(str(tmp_path / "admin_access_context.db"), factory=TrackingConnection)
    conn.row_factory = sqlite3.Row
    _create_access_tables(conn)

    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    ensure_calls = []
    monkeypatch.setattr(admin_access, "ensure_usuario_access_schema", lambda c: ensure_calls.append(c))
    try:
        # Falsy id: no ensure, no query, no commit/rollback/close.
        for falsy in (None, 0, ""):
            ensure_calls.clear()
            statements.clear()
            conn.commit_count = conn.rollback_count = conn.close_count = 0
            result = admin_access._load_admin_access_context(conn, falsy)
            assert result == NON_ADMIN_CONTEXT
            assert ensure_calls == []
            assert statements == []
            assert conn.commit_count == conn.rollback_count == conn.close_count == 0
            assert conn.in_transaction is False

        # Non-admin result: ensure called once, no overrides query.
        conn.execute(
            "INSERT INTO usuarios (id, tipo, nivel_acesso) VALUES (?, ?, ?)",
            (1, "aluno", "usuario"),
        )
        conn.commit()
        ensure_calls.clear()
        statements.clear()
        conn.commit_count = conn.rollback_count = conn.close_count = 0
        result = admin_access._load_admin_access_context(conn, 1)
        assert result == NON_ADMIN_CONTEXT
        assert len(ensure_calls) == 1
        norm = _norm_sql(statements)
        # set_trace_callback expands bound parameters, so "?" renders as literal 1.
        assert norm == ["SELECT id, tipo, nivel_acesso FROM usuarios WHERE id = 1"]
        assert conn.commit_count == conn.rollback_count == conn.close_count == 0
        assert conn.in_transaction is False

        # Admin result: canonicalization, overrides, effective scopes, groups.
        conn.execute(
            "INSERT INTO usuarios (id, tipo, nivel_acesso) VALUES (?, ?, ?)",
            (2, "admin", "consultivo"),
        )
        conn.execute(
            "INSERT INTO usuarios_permissoes_acesso (usuario_id, recurso, escopo) VALUES (?, ?, ?)",
            (2, "acesso", "full"),
        )
        conn.execute(
            "INSERT INTO usuarios_permissoes_acesso (usuario_id, recurso, escopo) VALUES (?, ?, ?)",
            (2, "not_a_resource", "full"),
        )
        conn.commit()
        ensure_calls.clear()
        statements.clear()
        conn.commit_count = conn.rollback_count = conn.close_count = 0
        result = admin_access._load_admin_access_context(conn, 2)
        assert set(result) == set(NON_ADMIN_CONTEXT)
        assert result["is_admin"] is True
        assert result["access_level"] == "consultivo"
        assert result["access_level_label"] == ACCESS_LEVEL_META["consultivo"]["label"]
        assert result["overrides"] == {"acesso": "full"}
        assert result["effective_scopes"] == merge_resource_scopes(
            "consultivo", {"acesso": "full"}
        )
        assert [group["label"] for group in result["scope_groups"]] == [
            label for label, _ in ACCESS_RESOURCE_GROUPS
        ]
        assert len(ensure_calls) == 2  # once in _load, once in _fetch_user_access_overrides
        norm = _norm_sql(statements)
        assert set(norm) == {
            "SELECT id, tipo, nivel_acesso FROM usuarios WHERE id = 2",
            "SELECT recurso, escopo FROM usuarios_permissoes_acesso WHERE usuario_id = 2",
        }
        assert conn.commit_count == conn.rollback_count == conn.close_count == 0
        assert conn.in_transaction is False
        assert ensure_calls == [conn, conn]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 10. _get_current_admin_access_context cache / force_reload / session behavior
# ---------------------------------------------------------------------------


def test_get_current_context_non_admin_does_not_touch_db(monkeypatch):
    import main
    from app import admin_access
    from flask import g, session

    touched = []

    def unexpected(*args, **kwargs):
        touched.append(1)
        raise AssertionError("db/load must not run for non-admin session")

    monkeypatch.setattr(admin_access, "_load_admin_access_context", unexpected)
    monkeypatch.setattr(admin_access, "get_db_connection", unexpected)

    with main.app.test_request_context():
        g.pop("admin_access_context", None)
        session.clear()
        session["user_type"] = "aluno"

        result = admin_access._get_current_admin_access_context()

        assert result == NON_ADMIN_CONTEXT
        assert touched == []
        assert g.admin_access_context is result


def test_get_current_context_admin_cache_force_reload_and_connection_timing(monkeypatch):
    import main
    from app import admin_access
    from flask import g, session

    loads = []
    connections = []

    def fake_load(conn, usuario_id=None):
        loads.append((conn, usuario_id))
        return {
            "is_admin": True,
            "access_level": "admin_total",
            "effective_scopes": {"matrizes": "full"},
        }

    def fake_db_connection():
        connections.append(1)
        return "CONN_OBJECT"

    monkeypatch.setattr(admin_access, "_load_admin_access_context", fake_load)
    monkeypatch.setattr(admin_access, "get_db_connection", fake_db_connection)

    with main.app.test_request_context():
        g.pop("admin_access_context", None)
        session.clear()
        session["user_type"] = "admin"
        session["user_id"] = 42

        first = admin_access._get_current_admin_access_context()
        assert first["is_admin"] is True
        assert loads == [("CONN_OBJECT", 42)]
        assert connections == [1]
        assert g.admin_access_context is first

        second = admin_access._get_current_admin_access_context()
        assert second is first
        assert loads == [("CONN_OBJECT", 42)]
        assert connections == [1]

        forced = admin_access._get_current_admin_access_context(force_reload=True)
        assert forced is not first
        assert loads == [("CONN_OBJECT", 42), ("CONN_OBJECT", 42)]
        assert connections == [1, 1]
        assert g.admin_access_context is forced


# ---------------------------------------------------------------------------
# 11. _admin_can exact behavior
# ---------------------------------------------------------------------------


def test_admin_can_falsy_resource_avoids_lookup(monkeypatch):
    from app import admin_access

    def forbidden(*args, **kwargs):
        raise AssertionError("automatic lookup must not run for falsy resource")

    monkeypatch.setattr(admin_access, "_get_current_admin_access_context", forbidden)
    assert admin_access._admin_can(None) is False
    assert admin_access._admin_can("") is False
    assert admin_access._admin_can(0) is False


def test_admin_can_explicit_context_honored_without_automatic_lookup(monkeypatch):
    from app import admin_access

    def forbidden(*args, **kwargs):
        raise AssertionError("explicit context must bypass automatic lookup")

    monkeypatch.setattr(admin_access, "_get_current_admin_access_context", forbidden)
    context = {"is_admin": True, "effective_scopes": {"matrizes": "edit"}}
    assert admin_access._admin_can("matrizes", "view", context) is True
    assert admin_access._admin_can("matrizes", "edit", context) is True
    assert admin_access._admin_can("matrizes", "full", context) is False
    assert admin_access._admin_can("alunos", "view", context) is False
    # permission_scope_satisfies normalization is honored.
    assert admin_access._admin_can("matrizes", "Edição", context) is True


def test_admin_can_automatic_lookup_and_non_admin(monkeypatch):
    from app import admin_access

    context = {"is_admin": True, "effective_scopes": {"arquivos": "full"}}
    monkeypatch.setattr(admin_access, "_get_current_admin_access_context", lambda: context)
    assert admin_access._admin_can("arquivos", "view") is True
    assert admin_access._admin_can("arquivos", "full") is True

    non_admin = {"is_admin": False, "effective_scopes": {"arquivos": "full"}}
    assert admin_access._admin_can("arquivos", "view", non_admin) is False
    monkeypatch.setattr(admin_access, "_get_current_admin_access_context", lambda: non_admin)
    assert admin_access._admin_can("arquivos", "view") is False
    assert admin_access._admin_can("banco_dados", "view") is False


# ---------------------------------------------------------------------------
# 12. Current main consumers resolve the same global callable identities
# ---------------------------------------------------------------------------


def test_current_main_consumers_resolve_canonical_identities_for_every_use():
    import main
    from app import admin_access

    consumers = _discover_consumers(MAIN_PATH, ADMIN_ACCESS_HELPERS)
    assert set(consumers) == CONSUMER_NAMES
    assert consumers == CONSUMER_HELPER_USES

    for name, used in consumers.items():
        func = inspect.unwrap(getattr(main, name))
        assert func.__module__ == "main"
        for helper in used:
            assert func.__globals__[helper] is getattr(admin_access, helper)


def test_moved_admin_access_consumers_resolve_canonical_identities_in_future_owner_modules():
    """UT-3 RED: enforce_admin_access_control/inject_admin_access_helpers must
    resolve the canonical app.admin_access identities from their future owner
    modules (app.web.authz_gate / app.web.context), not from main.

    At RED stage neither owner module exists yet, so this import itself is
    the intended failure -- not a weaker "string import present" check.
    """
    import importlib

    from app import admin_access

    for name, used in MOVED_CONSUMER_HELPER_USES.items():
        module_name = MOVED_CONSUMER_OWNER_MODULE[name]
        owner_module = importlib.import_module(module_name)
        func = inspect.unwrap(getattr(owner_module, name))
        assert func.__module__ == module_name
        for helper in used:
            assert func.__globals__[helper] is getattr(admin_access, helper)


def test_matrizes_module_consumers_resolve_canonical_identities_for_every_use():
    from app import admin_access
    from app.views.admin import matrizes

    for name, used in MATRIZES_MODULE_CONSUMERS.items():
        func = inspect.unwrap(getattr(matrizes, name))
        assert func.__module__ == "app.views.admin.matrizes"
        for helper in used:
            assert func.__globals__[helper] is getattr(admin_access, helper)


# ---------------------------------------------------------------------------
# 13. Persist/parse helpers remain local in main and absent from admin_access
# ---------------------------------------------------------------------------


def test_persist_and_parse_helpers_remain_local_in_main_and_absent_from_admin_access():
    main_names = _top_level_functions(MAIN_PATH)
    assert RELATED_LOCAL_HELPERS <= main_names
    admin_bodies = _top_level_bodies(ADMIN_ACCESS_PATH)
    assert not RELATED_LOCAL_HELPERS & admin_bodies


# ---------------------------------------------------------------------------
# 14. Route decorators absent from admin_access; Matrizes handlers live in the
#     canonical blueprint module (PHASE 4-B5-R1 extraction)
# ---------------------------------------------------------------------------


def test_matrizes_route_handlers_live_in_blueprint_module_and_no_routes_in_admin_access():
    import main
    from app import admin_access
    from app.views.admin import matrizes

    assert not MATRIZES_ROUTE_NAMES & _top_level_bodies(Path(admin_access.__file__))
    assert not MATRIZES_ROUTE_NAMES & _top_level_functions(MAIN_PATH)
    assert MATRIZES_ROUTE_NAMES <= _top_level_functions(Path(matrizes.__file__))

    for endpoint in MATRIZES_ROUTE_NAMES:
        view = main.app.view_functions.get(endpoint)
        assert view is not None, endpoint
        assert view is getattr(matrizes, endpoint), endpoint
        assert view.__module__ == "app.views.admin.matrizes", endpoint
