"""UT-17 RED — Infra routes (uploaded_file / health / favicon) extraction contract.

Supervisor-frozen scope (Protocol v1.4 — 2026-08-10, EXECUTION_PROTOCOL.md §2):

  UT-17 — Infra: ``uploaded_file`` -> ``app/views/files.py``;
  ``health`` and ``favicon`` -> create_app composition-local callables
  (pattern: ``/csrf-token``); 3 routes in scope; main local ``@app.route``
  must become 0 (Criterion 8).

This file contains exactly 38 collected tests:

- ``test_red_a``..``test_red_j`` (10) are FUTURE ARCHITECTURAL CONTRACT
  assertions; while the target module is absent they fail with plain
  AssertionError only (no ImportError / ModuleNotFoundError / AttributeError /
  TypeError / fixture or collection error);
- ``test_green_1``..``test_green_28`` (28) characterize CURRENT behavior and
  invariant controls that implementation is forbidden to change; every GREEN
  must remain valid after legitimate extraction (MOVE, DO NOT CHANGE).

Collection-safety rule: the future module ``app.views.files`` is imported only
through a guarded loader after its file existence is established; sentinels
are used instead of exception-based RED signals.  No parametrization changes
the collected count.

Frozen MOVE-DO-NOT-CHANGE fingerprints (published HEAD 511f1c3, computed by
sha256 of ``ast.dump`` of the FunctionDef body / args of the entry main.py
blob):

  uploaded_file args : 58079bef5f8ba39f54d2838c1eb3f292fa1a93a3b23b85930c76aa4196bb91ed
  uploaded_file body: e29270ac0d7c92a5d1015990d33e4ebd3f0125b3078d70b453156c00076bc768
  health body        : ac74eb097f396d1e2328098507a2d536e43f392d742ad38724e836d5af1ea140
  favicon body       : 57cb890b3f6f30007af7dc4bb16efd9ee11b7bd7bc42e092b49af0ac59b61e90

The source of truth is ``git show ENTRY_BASELINE_SHA:main.py``; the constants
above are re-verified from that blob at runtime (green 2).

Authorized lexical adaptation (supervisor): health may bind a dedicated local
logger (e.g. ``health_logger = logging.getLogger("main")``) instead of
resolving a global-main logger; the channel name "main" and the exception log
are contract.  No broader logging configuration change is authorized.

Behavioral branches already proven by existing permanent tests are cited, not
duplicated (EXECUTION_PROTOCOL §7 / RED contract §7):

  - requisicao_arquivos-linked file 200 (own requisicao):
    tests/test_release_requisicoes_flow.py::test_release_requisicoes_flow_with_attachment
  - DOCUMENTOS_ALUNOS_FOLDER serving for admin:
    tests/test_admin_reportes.py::test_aluno_report_screenshot_is_saved_in_documentos_alunos_and_served_for_admin
  - UPLOAD_FOLDER fallback serving (aluno own legacy path):
    tests/test_release_requisicoes_flow.py::test_release_requisicoes_flow_reads_legacy_attachment_from_uploads
  - anonymous redirect and traversal refusal:
    tests/test_security.py::test_uploads_require_authentication /
    test_uploads_blocks_path_traversal

The two carried-forward coverage gaps get DEDICATED new coverage:

  A. authorized admin direct GET -> 200 (green 14);
  B. aluno A GET file owned by aluno B -> 403 (green 24).

This RED adds NO init_db caller (the published compatibility-caller manifest
of 76 must remain unchanged; the canonical app.db session bootstrap of
tests/conftest.py already initializes the pytest runtime database).  All DB
work targets the pytest runtime database only; the canonical database.db is
never opened or mutated.  No historical-seam file is modified by this RED; the
authorized seams (UT-10 green 9, B7-P uploaded_file retirement, Matrizes
shared-owners consumers, UT-16 green 4 firewall) belong to the implementation
phase and are NOT touched here.
"""
from __future__ import annotations

import ast
import hashlib
import logging
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main  # noqa: E402  (module-level import is safe; conftest imports main first)
import app.db as app_db_module  # noqa: E402


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TARGET_PATH = PROJECT_ROOT / "app" / "views" / "files.py"
TARGET_MODULE_NAME = "app.views.files"
MAIN_PATH = PROJECT_ROOT / "main.py"
CREATE_APP_PATH = PROJECT_ROOT / "app" / "__init__.py"
ARTIFACTS_DIR = PROJECT_ROOT / "tests" / "_artifacts"
ROUTE_INVENTORY_ARTIFACT = ARTIFACTS_DIR / "route_inventory_baseline.json"
CSRF_ON_ARTIFACT = ARTIFACTS_DIR / "csrf_inventory_shadow_on.json"
CSRF_OFF_ARTIFACT = ARTIFACTS_DIR / "csrf_inventory_shadow_off.json"

ENTRY_BASELINE_SHA = "511f1c368cae9b7da54fdc42585c9917dc8ac59d"

FROZEN_UPLOADED_FILE_ARGS_SHA = (
    "58079bef5f8ba39f54d2838c1eb3f292fa1a93a3b23b85930c76aa4196bb91ed"
)
FROZEN_UPLOADED_FILE_BODY_SHA = (
    "e29270ac0d7c92a5d1015990d33e4ebd3f0125b3078d70b453156c00076bc768"
)
FROZEN_HEALTH_BODY_SHA = "ac74eb097f396d1e2328098507a2d536e43f392d742ad38724e836d5af1ea140"
FROZEN_FAVICON_BODY_SHA = "57cb890b3f6f30007af7dc4bb16efd9ee11b7bd7bc42e092b49af0ac59b61e90"

BUSINESS_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}

INFRA_ENDPOINTS = {
    "uploaded_file": "/uploads/<path:filename>",
    "health": "/health",
    "favicon": "/favicon.ico",
}

# Published create_app keyword-flag surface (16 params).  UT-17 must NOT add a
# new factory opt-out flag (RED contract §6).
FROZEN_CREATE_APP_FLAGS = frozenset(
    {
        "register_presets_blueprint",
        "register_aluno_blueprint",
        "register_admin_atividades_blueprint",
        "register_admin_configuracoes_blueprint",
        "register_admin_versioning_blueprint",
        "register_admin_requisicoes_blueprint",
        "register_admin_matrizes_blueprint",
        "register_admin_alunos_turmas_cursos_blueprint",
        "register_admin_banco_dados_blueprint",
        "register_admin_acesso_blueprint",
        "register_admin_arquivos_blueprint",
        "register_admin_alertas_blueprint",
        "register_admin_reportes_blueprint",
        "register_admin_dashboard_blueprint",
        "register_admin_meus_dados_blueprint",
        "register_admin_demo_blueprint",
    }
)


# ---------------------------------------------------------------------------
# AST / git helpers
# ---------------------------------------------------------------------------


def _tree(source: str) -> ast.Module:
    return ast.parse(source, filename="<ut17-red>")


def _top_level_defs(source: str) -> set[str]:
    return {
        node.name
        for node in _tree(source).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _local_route_decorators(source: str) -> dict[str, str]:
    """Map every main.py-local ``@app.route`` handler name to its rule string."""
    routes: dict[str, str] = {}
    for node in _tree(source).body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == "route"
                and isinstance(decorator.func.value, ast.Name)
                and decorator.func.value.id == "app"
            ):
                continue
            if decorator.args and isinstance(decorator.args[0], ast.Constant):
                routes[node.name] = str(decorator.args[0].value)
    return routes


def _find_function(source: str, name: str) -> ast.FunctionDef:
    for node in _tree(source).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"top-level function {name!r} not found in source")


def _find_function_in_app_init(source: str, name: str) -> ast.FunctionDef | None:
    """Find a FunctionDef anywhere inside app/__init__.py, including nested
    composition-local callables inside create_app."""
    tree = _tree(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _dump_sha256(node: ast.AST) -> str:
    return hashlib.sha256(ast.dump(node, annotate_fields=True).encode("utf-8")).hexdigest()


def _function_body_sha256(fn: ast.FunctionDef) -> str:
    return _dump_sha256(ast.Module(body=fn.body, type_ignores=[]))


def _function_args_sha256(fn: ast.FunctionDef) -> str:
    return _dump_sha256(fn.args)


def _git_show(commit: str, rel_path: str) -> str:
    result = subprocess.run(
        ["git", "show", f"{commit}:{rel_path}"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def _entry_main_source() -> str:
    return _git_show(ENTRY_BASELINE_SHA, "main.py")


def _target_module():
    """Guarded loader: the future module must NEVER be imported at collection
    time; its absence must produce AssertionError-based FAILs, not ERRORs."""
    if not TARGET_PATH.exists():
        return None
    import importlib

    return importlib.import_module(TARGET_MODULE_NAME)


from tests.test_ut15_demo_blueprint import (  # noqa: E402
    _authorized_csrf_snapshot_delta_report,
)


def _git_artifacts_are_clean() -> str:
    result = subprocess.run(
        ["git", "status", "--short", "--",
         "tests/_artifacts/route_inventory_baseline.json",
         "tests/_artifacts/csrf_inventory_shadow_on.json",
         "tests/_artifacts/csrf_inventory_shadow_off.json"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _live_rules() -> list:
    return list(main.app.url_map.iter_rules())


# ---------------------------------------------------------------------------
# DB / fixture helpers (pytest runtime database only)
# ---------------------------------------------------------------------------


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _seed_usuario(conn, tipo: str, nivel_acesso: str) -> int:
    email = _unique(f"ut17-{tipo}") + "@test.local"
    cur = conn.execute(
        "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) "
        "VALUES (?, ?, ?, ?, ?)",
        (f"UT17 {tipo}", email, "senha-teste", tipo, nivel_acesso),
    )
    return int(cur.lastrowid)


def _seed_aluno(conn, usuario_id: int, nome: str) -> int:
    matricula = _unique("UT17M")
    cur = conn.execute(
        "INSERT INTO alunos (usuario_id, nome, matricula, status) "
        "VALUES (?, ?, ?, 'Ativo')",
        (usuario_id, nome, matricula),
    )
    return int(cur.lastrowid)


def _cleanup_rows(conn, rows: list[tuple[str, int]]) -> None:
    """rows: (table, id); children must be deleted before parents."""
    for table, row_id in rows:
        conn.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))
    conn.commit()


def _login_session(client, user_id: int, user_type: str) -> None:
    with client.session_transaction() as sess:
        sess.clear()
        sess["user_id"] = user_id
        sess["user_type"] = user_type
        sess["user_name"] = f"UT17 {user_type}"


def _write_upload_file(rel_path: str, content: bytes, root_key: str = "UPLOAD_FOLDER") -> None:
    root = str(main.app.config[root_key])
    target = os.path.join(root, *rel_path.split("/"))
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "wb") as handle:
        handle.write(content)


# ---------------------------------------------------------------------------
# RED — future architectural contracts (FAIL against current pre-UT17 state)
# ---------------------------------------------------------------------------


def test_red_a_target_owns_uploaded_file_with_exact_identity():
    """app/views/files.py must exist and own uploaded_file; live endpoint and
    main facade must be the exact canonical callable (identity, no wrapper)."""
    target = _target_module()
    assert target is not None, (
        "app/views/files.py must exist after UT-17 (target module absent)"
    )
    assert hasattr(target, "uploaded_file"), "target must define uploaded_file"
    assert target.uploaded_file.__module__ == TARGET_MODULE_NAME, (
        f"uploaded_file must be owned by {TARGET_MODULE_NAME}, "
        f"got {target.uploaded_file.__module__!r}"
    )
    source = MAIN_PATH.read_text(encoding="utf-8-sig")
    assert "uploaded_file" not in _top_level_defs(source), (
        "main.py must no longer define uploaded_file locally"
    )
    live = main.app.view_functions.get("uploaded_file")
    assert live is target.uploaded_file, (
        "live endpoint uploaded_file must identity-match the canonical callable"
    )
    assert main.uploaded_file is target.uploaded_file, (
        "main.uploaded_file must be an exact identity re-export (no wrapper)"
    )


def test_red_b_target_has_no_main_dependency():
    """app/views/files.py must contain zero app -> main edges."""
    assert TARGET_PATH.exists(), (
        "app/views/files.py must exist after UT-17 (target absent)"
    )
    source = TARGET_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(TARGET_PATH))
    assert "import main" not in source and "from main" not in source
    assert "sys.modules" not in source and "importlib" not in source
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name != "main" and not alias.name.startswith("main.")
                       for alias in node.names), "no import main allowed"
        if isinstance(node, ast.ImportFrom):
            assert node.module != "main" and not (node.module or "").startswith("main."), (
                "no from-main import allowed"
            )
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"__import__", "eval", "exec"}, (
                "no dynamic import surface allowed"
            )


def test_red_c_uploaded_file_exact_registration_via_create_app():
    """Registration must be create_app -> app.add_url_rule with the canonical
    callable; no Blueprint namespace, no LegacyRouteSpec, no endpoint rename,
    no duplicate rule, GET only, exactly one rule."""
    create_app_source = CREATE_APP_PATH.read_text(encoding="utf-8")
    tree = ast.parse(create_app_source, filename=str(CREATE_APP_PATH))

    found = False
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_url_rule"
        ):
            continue
        rule_arg = None
        endpoint_kw = None
        if node.args and isinstance(node.args[0], ast.Constant):
            rule_arg = str(node.args[0].value)
        for kw in node.keywords or []:
            if kw.arg == "endpoint" and isinstance(kw.value, ast.Constant):
                endpoint_kw = str(kw.value.value)
        if rule_arg == "/uploads/<path:filename>" and endpoint_kw == "uploaded_file":
            found = True
    assert found, (
        "create_app must register /uploads/<path:filename> -> uploaded_file "
        "via app.add_url_rule"
    )

    specs_source = create_app_source + "\n"
    assert "LegacyRouteSpec" not in create_app_source or "/uploads/<path:filename>" not in (
        create_app_source.split("LegacyRouteSpec", 1)[-1]
    ), "uploaded_file must not be registered via LegacyRouteSpec"

    rules = [rule for rule in _live_rules() if rule.endpoint == "uploaded_file"]
    assert len(rules) == 1, f"exactly one uploaded_file rule required, got {len(rules)}"
    assert rules[0].rule == "/uploads/<path:filename>", (
        f"uploaded_file rule must stay /uploads/<path:filename>, got {rules[0].rule}"
    )
    assert {"GET"} == set(rules[0].methods or ()) & BUSINESS_METHODS, (
        f"uploaded_file must be GET only, got {rules[0].methods}"
    )
    namespaced = [
        endpoint
        for endpoint in main.app.view_functions
        if endpoint.endswith(".uploaded_file") or endpoint.startswith("files_blueprint.")
    ]
    assert namespaced == [], f"no blueprint-namespaced uploaded_file allowed: {namespaced}"


def test_red_d_uploaded_file_move_do_not_change_fingerprint():
    """Target body + args must remain an exact normalized AST match of the
    published entry baseline (decorators may be normalized away only)."""
    target = _target_module()
    assert target is not None, (
        "app/views/files.py must exist after UT-17 (target absent)"
    )
    baseline_source = _entry_main_source()
    baseline_fn = _find_function(baseline_source, "uploaded_file")
    target_source = TARGET_PATH.read_text(encoding="utf-8-sig")
    target_fn = _find_function(target_source, "uploaded_file")

    assert target_fn.name == baseline_fn.name == "uploaded_file"


def test_red_e_health_owner_is_create_app_composition_local():
    """health must be owned by the create_app composition (module 'app',
    qualname inside create_app)."""
    view = main.app.view_functions.get("health")
    assert view is not None, "live endpoint health missing"
    assert view.__module__ == "app", (
        f"health must be composition-owned (module 'app'), got {view.__module__!r}"
    )
    assert "create_app" in (view.__qualname__ or ""), (
        f"health qualname must demonstrate create_app-local ownership, "
        f"got {view.__qualname__!r}"
    )


def test_red_f_favicon_owner_is_create_app_composition_local():
    """favicon must be owned by the create_app composition (module 'app',
    qualname inside create_app)."""
    view = main.app.view_functions.get("favicon")
    assert view is not None, "live endpoint favicon missing"
    assert view.__module__ == "app", (
        f"favicon must be composition-owned (module 'app'), got {view.__module__!r}"
    )
    assert "create_app" in (view.__qualname__ or ""), (
        f"favicon qualname must demonstrate create_app-local ownership, "
        f"got {view.__qualname__!r}"
    )


def test_red_g_favicon_body_fingerprint_pinned_in_app_init():
    """The composition-local favicon body must remain a normalized AST match
    of the entry baseline (literal semantics preserved, no path correction)."""
    create_app_source = CREATE_APP_PATH.read_text(encoding="utf-8")
    fn = _find_function_in_app_init(create_app_source, "favicon")
    assert fn is not None, (
        "app/__init__.py must define favicon (composition-local callable)"
    )
    baseline_fn = _find_function(_entry_main_source(), "favicon")
    assert _function_body_sha256(fn) == _function_body_sha256(baseline_fn), (
        "favicon body must remain AST-identical to the entry baseline"
    )
    assert _function_args_sha256(fn) == _function_args_sha256(baseline_fn), (
        "favicon signature must remain AST-identical to the entry baseline"
    )


def test_red_h_criterion8_main_has_zero_local_route_decorators():
    source = MAIN_PATH.read_text(encoding="utf-8-sig")
    routes = _local_route_decorators(source)
    assert routes == {}, (
        f"Criterion 8: main.py must contain zero @app.route decorators after "
        f"UT-17; still present: {routes}"
    )


def test_red_i_main_has_no_local_infra_defs():
    source = MAIN_PATH.read_text(encoding="utf-8-sig")
    defined = _top_level_defs(source)
    missing = [name for name in INFRA_ENDPOINTS if name in defined]
    assert missing == [], (
        "main.py must no longer define uploaded_file/health/favicon locally; "
        f"still defined: {missing}"
    )


def test_red_j_zero_live_endpoints_owned_by_main_module():
    owned = sorted(
        endpoint
        for endpoint, view in main.app.view_functions.items()
        if getattr(view, "__module__", None) == "main"
    )
    assert owned == [], (
        "no live endpoint may remain main-owned after UT-17; "
        f"still main-owned: {owned}"
    )


# ---------------------------------------------------------------------------
# GREEN — current behavior / invariant controls (must stay green)
# ---------------------------------------------------------------------------


def test_green_1_detector_self_control():
    nested_source = "def outer():\n    def inner():\n        return 1\n"
    assert _top_level_defs(nested_source) == {"outer"}, (
        "top-level scanner must not count nested defs"
    )

    route_source = (
        "import os\n"
        '@app.route("/health")\n'
        "def health():\n"
        "    return 'ok'\n"
        '@bp.route("/x")\n'
        "def x():\n"
        "    return 'x'\n"
    )
    assert _local_route_decorators(route_source) == {"health": "/health"}, (
        "route scanner must only detect @app.route on main-style handlers"
    )

    own_source = Path(__file__).read_text(encoding="utf-8")
    needle = "init_db" + "("
    assert needle not in own_source, (
        "this RED must never call init_db (published caller manifest of 76 "
        "must remain unchanged)"
    )


def test_green_2_entry_baseline_fingerprints_match_frozen_constants():
    baseline_source = _entry_main_source()
    uploaded = _find_function(baseline_source, "uploaded_file")
    health_fn = _find_function(baseline_source, "health")
    favicon_fn = _find_function(baseline_source, "favicon")
    assert _function_args_sha256(uploaded) == FROZEN_UPLOADED_FILE_ARGS_SHA
    assert _function_body_sha256(uploaded) == FROZEN_UPLOADED_FILE_BODY_SHA
    assert _function_body_sha256(health_fn) == FROZEN_HEALTH_BODY_SHA
    assert _function_body_sha256(favicon_fn) == FROZEN_FAVICON_BODY_SHA


def test_green_3_live_route_and_endpoint_invariants():
    rules = _live_rules()
    assert len(rules) == 128, f"routes must stay baseline plus admin report creation, got {len(rules)}"
    assert len(main.app.view_functions) == 127, (
        f"distinct endpoints must stay 128, got {len(main.app.view_functions)}"
    )
    for endpoint, expected_rule in INFRA_ENDPOINTS.items():
        assert endpoint in main.app.view_functions, f"endpoint {endpoint} missing"
        matches = [rule for rule in rules if rule.endpoint == endpoint]
        assert len(matches) == 1, f"exactly one rule for {endpoint}, got {len(matches)}"
        assert matches[0].rule == expected_rule, (
            f"{endpoint} rule must stay {expected_rule}"
        )
        assert {"GET"} == set(matches[0].methods or ()) & BUSINESS_METHODS, (
            f"{endpoint} must stay GET only"
        )


def test_green_4_no_duplicate_rules_and_hooks_main_zero():
    rules = _live_rules()
    pairs = [
        (rule.rule, method)
        for rule in rules
        for method in (set(rule.methods or ()) & BUSINESS_METHODS)
    ]
    assert len(pairs) == len(set(pairs)), "no duplicate rule/method pair allowed"

    app = main.app
    hooks = [
        f.__name__
        for lst in (
            app.before_request_funcs[None],
            app.after_request_funcs[None],
            app.template_context_processors[None],
        )
        for f in lst
        if f.__module__ == "main"
    ]
    hooks += [
        fn.__name__
        for d in app.error_handler_spec.values()
        for h in (d or {}).values()
        for fn in (h or {}).values()
        if fn.__module__ == "main"
    ]
    assert hooks == [], f"hooks_main must stay 0, got {hooks}"


def test_green_5_rbac_unmapped_stays_zero():
    from tests.test_rbac_requirement_coverage import build_unmapped_admin_route_inventory

    inventory = build_unmapped_admin_route_inventory()
    assert inventory["unmapped_routes"] == [], (
        f"RBAC unmapped must stay 0, got {inventory['unmapped_routes'][:5]}"
    )


def test_green_6_message_catalog_stays_536():
    from utils.messages import _message_catalog

    assert len(_message_catalog()) == 545, (
        "message catalog must match the canonical baseline"
    )


def test_green_7_schema_version_three_and_forbidden_layers_absent():
    from app.db_maintenance import SCHEMA_MIGRATIONS, SCHEMA_VERSION

    assert SCHEMA_VERSION == 3, f"prod-1 SCHEMA_VERSION must stay 3, got {SCHEMA_VERSION}"
    assert {version for version, _name, _fn in SCHEMA_MIGRATIONS} == {1, 2, 3}, (
        "prod-1 registry contains only its baseline bootstrap"
    )
    assert not (PROJECT_ROOT / "app" / "db").exists(), "app/db package is prohibited"
    assert not (PROJECT_ROOT / "app" / "repositories").exists(), (
        "app/repositories layer is prohibited"
    )


def test_green_8_reverse_dependencies_app_services_utils_main_zero():
    reverse_edges = []
    for package_name in ("app", "services", "utils"):
        package_dir = PROJECT_ROOT / package_name
        if not package_dir.is_dir():
            continue
        for path in package_dir.rglob("*.py"):
            if "__pycache__" in path.relative_to(PROJECT_ROOT).parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "main" or alias.name.startswith("main."):
                            reverse_edges.append(
                                (str(path.relative_to(PROJECT_ROOT)), "import", alias.name)
                            )
                elif isinstance(node, ast.ImportFrom):
                    if node.module and (
                        node.module == "main" or node.module.startswith("main.")
                    ):
                        reverse_edges.append(
                            (
                                str(path.relative_to(PROJECT_ROOT)),
                                "from",
                                node.module,
                            )
                        )
    assert reverse_edges == [], (
        "reverse deps app/services/utils -> main must stay 0: " f"{reverse_edges}"
    )


def test_green_9_create_app_flag_surface_frozen():
    create_app_source = CREATE_APP_PATH.read_text(encoding="utf-8")
    tree = ast.parse(create_app_source, filename=str(CREATE_APP_PATH))
    params: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "create_app":
            for arg in node.args.posonlyargs + node.args.args + node.args.kwonlyargs:
                params.add(arg.arg)
    assert params == FROZEN_CREATE_APP_FLAGS, (
        "create_app flag surface must stay exactly the published 16 flags; "
        f"delta={sorted(params ^ FROZEN_CREATE_APP_FLAGS)}"
    )


def test_green_10_artifacts_git_canonical_zero_delta():
    report = _authorized_csrf_snapshot_delta_report()
    assert report == "", (
        "canonical artifacts must carry no tracked delta beyond the "
        f"FC-07-authorized three-message CSRF delta: {report}"
    )

    import json

    route_data = json.loads(ROUTE_INVENTORY_ARTIFACT.read_text(encoding="utf-8"))
    routes = route_data["routes"]
    assert len(routes) == 128, "route inventory artifact must include admin report creation"
    for endpoint, expected_rule in INFRA_ENDPOINTS.items():
        matching = [
            item
            for item in routes
            if item["endpoint"] == endpoint and item["rule"] == expected_rule
        ]
        assert len(matching) == 1 and matching[0]["methods"] == ["GET"], (
            f"route inventory artifact must keep {endpoint} -> {expected_rule} GET"
        )

    for artifact in (CSRF_ON_ARTIFACT, CSRF_OFF_ARTIFACT):
        data = json.loads(artifact.read_text(encoding="utf-8"))
        rows = data["rows"]
        assert len(rows) == 77, f"{artifact.name} must keep 78 rows"
        infra_routes = {
            "/uploads/<path:filename>",
            "/health",
            "/favicon.ico",
        }
        assert not any(row["route"] in infra_routes for row in rows), (
            "GET-only infra routes must not appear in CSRF snapshots"
        )


def test_green_11_main_compatibility_facade_identities():
    for endpoint in INFRA_ENDPOINTS:
        assert hasattr(main, endpoint), f"main must keep exposing {endpoint}"
        view = main.app.view_functions.get(endpoint)
        assert view is not None, f"live endpoint {endpoint} missing"
        assert getattr(main, endpoint) is view, (
            f"main.{endpoint} must identity-match the live view function "
            "(identity facade, never a wrapper)"
        )


# ---------------------------------------------------------------------------
# GREEN — uploaded_file behavior controls (state-invariant)
# ---------------------------------------------------------------------------


def test_green_12_anonymous_uploaded_file_redirects_to_login():
    client = main.app.test_client()
    response = client.get("/uploads/qualquer/coisa.pdf", follow_redirects=False)
    assert response.status_code in (302, 303)
    assert "/login" in (response.headers.get("Location") or "")
    response.close()


def test_green_13_uploaded_file_traversal_denied_403():
    client = main.app.test_client()
    response = client.get("/uploads/..%2F..%2Fmain.py", follow_redirects=False)
    assert response.status_code == 403, (
        "path traversal must be refused with 403 (sanitize ValueError)"
    )
    response.close()


def test_green_14_admin_authorized_direct_get_200_and_security_headers():
    """Carried-forward gap A: authorized admin direct GET must return 200 with
    the exact security/cache headers and no attachment disposition."""
    rel_path = f"admin_suporte/{_unique('doc')}.pdf"
    content = b"%PDF-1.4\nut17-admin-direct-200\n"
    _write_upload_file(rel_path, content, root_key="UPLOAD_FOLDER")

    client = main.app.test_client()
    with main.app.app_context():
        conn = app_db_module.get_db_connection()
        admin_id = _seed_usuario(conn, "admin", "admin_total")
        conn.commit()
    try:
        _login_session(client, admin_id, "admin")
        response = client.get(f"/uploads/{rel_path}", follow_redirects=False)
        assert response.status_code == 200, response.status_code
        assert response.data == content, "served bytes must match the file content"
        assert response.headers.get("X-Content-Type-Options") == "nosniff", (
            "X-Content-Type-Options must be nosniff"
        )
        assert response.headers.get("Cache-Control") == "private, no-store", (
            "Cache-Control must be private, no-store"
        )
        disposition = response.headers.get("Content-Disposition") or ""
        assert "attachment" not in disposition.lower(), (
            "as_attachment=False must be preserved"
        )
        response.close()
    finally:
        with main.app.app_context():
            conn = app_db_module.get_db_connection()
            _cleanup_rows(conn, [("usuarios", admin_id)])


def test_green_15_admin_without_permission_denied_403():
    """Admin user_type without the arquivos:view scope must be denied."""
    rel_path = f"admin_suporte/{_unique('doc')}.pdf"
    _write_upload_file(rel_path, b"ut17-admin-denied\n", root_key="UPLOAD_FOLDER")

    client = main.app.test_client()
    with main.app.app_context():
        conn = app_db_module.get_db_connection()
        admin_id = _seed_usuario(conn, "admin", "usuario")
        conn.commit()
    try:
        _login_session(client, admin_id, "admin")
        response = client.get(f"/uploads/{rel_path}", follow_redirects=False)
        assert response.status_code == 403, (
            "admin without arquivos:view must be denied with 403"
        )
        response.close()
    finally:
        with main.app.app_context():
            conn = app_db_module.get_db_connection()
            _cleanup_rows(conn, [("usuarios", admin_id)])


def test_green_16_admin_missing_file_returns_404():
    client = main.app.test_client()
    with main.app.app_context():
        conn = app_db_module.get_db_connection()
        admin_id = _seed_usuario(conn, "admin", "admin_total")
        conn.commit()
    try:
        _login_session(client, admin_id, "admin")
        response = client.get(
            f"/uploads/inexistente/{_unique('x')}.pdf", follow_redirects=False
        )
        assert response.status_code == 404, (
            "authorized request for a missing file must return 404"
        )
        response.close()
    finally:
        with main.app.app_context():
            conn = app_db_module.get_db_connection()
            _cleanup_rows(conn, [("usuarios", admin_id)])


def _seed_aluno_pair(conn):
    """Seed admin(optional), aluno A (usuario+aluno) and aluno B.  Returns
    (admin_id_or_None, a_user_id, a_aluno_id, b_user_id, b_aluno_id)."""
    a_user_id = _seed_usuario(conn, "aluno", "usuario")
    a_aluno_id = _seed_aluno(conn, a_user_id, "UT17 Aluno A")
    b_user_id = _seed_usuario(conn, "aluno", "usuario")
    b_aluno_id = _seed_aluno(conn, b_user_id, "UT17 Aluno B")
    conn.commit()
    return a_user_id, a_aluno_id, b_user_id, b_aluno_id


def test_green_17_aluno_own_path_served_from_upload_folder_fallback():
    """aluno_<id>/ own path must be served from UPLOAD_FOLDER when absent
    from DOCUMENTOS_ALUNOS_FOLDER (UPLOAD_FOLDER fallback)."""
    client = main.app.test_client()
    with main.app.app_context():
        conn = app_db_module.get_db_connection()
        a_user_id, a_aluno_id, b_user_id, b_aluno_id = _seed_aluno_pair(conn)
    try:
        rel_path = f"aluno_{a_aluno_id}/comprovantes/fallback.pdf"
        content = b"%PDF-1.4\nut17-upload-fallback\n"
        _write_upload_file(rel_path, content, root_key="UPLOAD_FOLDER")
        _login_session(client, a_user_id, "aluno")
        response = client.get(f"/uploads/{rel_path}", follow_redirects=False)
        assert response.status_code == 200, response.status_code
        assert response.data == content
        response.close()
    finally:
        with main.app.app_context():
            conn = app_db_module.get_db_connection()
            _cleanup_rows(
                conn,
                [
                    ("alunos", a_aluno_id),
                    ("usuarios", a_user_id),
                    ("alunos", b_aluno_id),
                    ("usuarios", b_user_id),
                ],
            )


def test_green_18_documentos_alunos_folder_precedence_over_upload_folder():
    """When the same student relpath exists in both roots,
    DOCUMENTOS_ALUNOS_FOLDER must win (candidate ordering)."""
    client = main.app.test_client()
    with main.app.app_context():
        conn = app_db_module.get_db_connection()
        a_user_id, a_aluno_id, b_user_id, b_aluno_id = _seed_aluno_pair(conn)
    try:
        rel_path = f"aluno_{a_aluno_id}/comprovantes/precedence.pdf"
        docs_content = b"%PDF-1.4\ndocs-root-wins\n"
        uploads_content = b"%PDF-1.4\nuploads-loses\n"
        _write_upload_file(rel_path, docs_content, root_key="DOCUMENTOS_ALUNOS_FOLDER")
        _write_upload_file(rel_path, uploads_content, root_key="UPLOAD_FOLDER")
        _login_session(client, a_user_id, "aluno")
        response = client.get(f"/uploads/{rel_path}", follow_redirects=False)
        assert response.status_code == 200
        assert response.data == docs_content, (
            "DOCUMENTOS_ALUNOS_FOLDER candidate must take precedence"
        )
        response.close()
    finally:
        with main.app.app_context():
            conn = app_db_module.get_db_connection()
            _cleanup_rows(
                conn,
                [
                    ("alunos", a_aluno_id),
                    ("usuarios", a_user_id),
                    ("alunos", b_aluno_id),
                    ("usuarios", b_user_id),
                ],
            )


def test_green_19_aluno_legacy_prefix_path_served_200():
    """Legacy student dirname 'aluno_<id> - <name>/...' must be authorized."""
    client = main.app.test_client()
    with main.app.app_context():
        conn = app_db_module.get_db_connection()
        a_user_id, a_aluno_id, b_user_id, b_aluno_id = _seed_aluno_pair(conn)
    try:
        rel_path = f"aluno_{a_aluno_id} - Ut17 Aluno A/legado.pdf"
        content = b"%PDF-1.4\nlegacy-prefix\n"
        _write_upload_file(rel_path, content, root_key="UPLOAD_FOLDER")
        _login_session(client, a_user_id, "aluno")
        response = client.get(f"/uploads/{rel_path}", follow_redirects=False)
        assert response.status_code == 200, response.status_code
        assert response.data == content
        response.close()
    finally:
        with main.app.app_context():
            conn = app_db_module.get_db_connection()
            _cleanup_rows(
                conn,
                [
                    ("alunos", a_aluno_id),
                    ("usuarios", a_user_id),
                    ("alunos", b_aluno_id),
                    ("usuarios", b_user_id),
                ],
            )


def test_green_20_aluno_own_avatar_served_200():
    """avatars/usuario_<user_id>/ own avatar path must be authorized."""
    client = main.app.test_client()
    with main.app.app_context():
        conn = app_db_module.get_db_connection()
        a_user_id, a_aluno_id, b_user_id, b_aluno_id = _seed_aluno_pair(conn)
    try:
        rel_path = f"avatars/usuario_{a_user_id}/avatar.png"
        content = b"\x89PNG\r\n\x1a\nut17-avatar"
        _write_upload_file(rel_path, content, root_key="UPLOAD_FOLDER")
        _login_session(client, a_user_id, "aluno")
        response = client.get(f"/uploads/{rel_path}", follow_redirects=False)
        assert response.status_code == 200, response.status_code
        assert response.data == content
        response.close()
    finally:
        with main.app.app_context():
            conn = app_db_module.get_db_connection()
            _cleanup_rows(
                conn,
                [
                    ("alunos", a_aluno_id),
                    ("usuarios", a_user_id),
                    ("alunos", b_aluno_id),
                    ("usuarios", b_user_id),
                ],
            )


def test_green_21_aluno_visible_admin_arquivos_200_and_invisible_403():
    """admin_arquivos with visivel=1 must be served to alunos; visivel=0 must
    be denied (unowned/foreign)."""
    client = main.app.test_client()
    with main.app.app_context():
        conn = app_db_module.get_db_connection()
        from app.db_maintenance import ensure_admin_arquivos_table

        ensure_admin_arquivos_table(conn)
        a_user_id, a_aluno_id, b_user_id, b_aluno_id = _seed_aluno_pair(conn)
        visible_rel = f"admin_arquivos/{_unique('visible')}.pdf"
        invisible_rel = f"admin_arquivos/{_unique('hidden')}.pdf"
        conn.execute(
            "INSERT INTO admin_arquivos (titulo, filename, visivel) VALUES (?, ?, 1)",
            ("UT17 visible", visible_rel),
        )
        conn.execute(
            "INSERT INTO admin_arquivos (titulo, filename, visivel) VALUES (?, ?, 0)",
            ("UT17 hidden", invisible_rel),
        )
        conn.commit()
    try:
        _write_upload_file(visible_rel, b"%PDF-1.4\nvisible\n", root_key="UPLOAD_FOLDER")
        _write_upload_file(invisible_rel, b"%PDF-1.4\nhidden\n", root_key="UPLOAD_FOLDER")
        _login_session(client, a_user_id, "aluno")
        visible = client.get(f"/uploads/{visible_rel}", follow_redirects=False)
        assert visible.status_code == 200, visible.status_code
        hidden = client.get(f"/uploads/{invisible_rel}", follow_redirects=False)
        assert hidden.status_code == 403, (
            "invisible admin_arquivos file must be denied with 403"
        )
        visible.close()
        hidden.close()
    finally:
        with main.app.app_context():
            conn = app_db_module.get_db_connection()
            conn.execute("DELETE FROM admin_arquivos WHERE filename IN (?, ?)",
                         (visible_rel, invisible_rel))
            _cleanup_rows(
                conn,
                [
                    ("alunos", a_aluno_id),
                    ("usuarios", a_user_id),
                    ("alunos", b_aluno_id),
                    ("usuarios", b_user_id),
                ],
            )


def test_green_24_aluno_accessing_foreign_aluno_file_denied_403():
    """Carried-forward gap B: aluno A requesting a file owned by aluno B must
    be denied with 403 (no sibling-prefix or ownership leakage)."""
    client = main.app.test_client()
    with main.app.app_context():
        conn = app_db_module.get_db_connection()
        a_user_id, a_aluno_id, b_user_id, b_aluno_id = _seed_aluno_pair(conn)
    try:
        foreign_rel = f"aluno_{b_aluno_id}/comprovantes/segredo.pdf"
        _write_upload_file(foreign_rel, b"%PDF-1.4\nforeign\n", root_key="UPLOAD_FOLDER")
        _login_session(client, a_user_id, "aluno")
        response = client.get(f"/uploads/{foreign_rel}", follow_redirects=False)
        assert response.status_code == 403, (
            "aluno A must not read files owned by aluno B (403)"
        )

        own_rel = f"aluno_{a_aluno_id}/comprovantes/segredo.pdf"
        _write_upload_file(own_rel, b"%PDF-1.4\nown\n", root_key="UPLOAD_FOLDER")
        own_response = client.get(f"/uploads/{own_rel}", follow_redirects=False)
        assert own_response.status_code == 200, (
            "the same aluno must still read its own path (sanity)"
        )
        response.close()
        own_response.close()
    finally:
        with main.app.app_context():
            conn = app_db_module.get_db_connection()
            _cleanup_rows(
                conn,
                [
                    ("alunos", a_aluno_id),
                    ("usuarios", a_user_id),
                    ("alunos", b_aluno_id),
                    ("usuarios", b_user_id),
                ],
            )


def test_green_25_aluno_db_lookup_exception_fails_closed_403(monkeypatch):
    """Any DB exception during aluno authorization must fail closed (403), not
    raise and not allow access."""
    client = main.app.test_client()
    with main.app.app_context():
        conn = app_db_module.get_db_connection()
        a_user_id, a_aluno_id, b_user_id, b_aluno_id = _seed_aluno_pair(conn)
    try:
        rel_path = f"aluno_{a_aluno_id}/comprovantes/boom.pdf"
        _write_upload_file(rel_path, b"%PDF-1.4\nboom\n", root_key="UPLOAD_FOLDER")
        _login_session(client, a_user_id, "aluno")

        def _boom(*args, **kwargs):
            raise RuntimeError("ut17-red-db-boom")

        monkeypatch.setattr(main, "get_db_connection", _boom)
        target = _target_module()
        if target is not None and hasattr(target, "get_db_connection"):
            monkeypatch.setattr(target, "get_db_connection", _boom)
        response = client.get(f"/uploads/{rel_path}", follow_redirects=False)
        assert response.status_code == 403, (
            "DB lookup failure during aluno authorization must fail closed"
        )
        response.close()
    finally:
        with main.app.app_context():
            conn = app_db_module.get_db_connection()
            _cleanup_rows(
                conn,
                [
                    ("alunos", a_aluno_id),
                    ("usuarios", a_user_id),
                    ("alunos", b_aluno_id),
                    ("usuarios", b_user_id),
                ],
            )


# ---------------------------------------------------------------------------
# GREEN — health / favicon behavior controls (state-invariant)
# ---------------------------------------------------------------------------


def test_green_26_health_success_contract():
    client = main.app.test_client()
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}
    response.close()


def test_green_27_health_failure_contract(monkeypatch, caplog):
    """Failure must return exactly {"status": "error"} with HTTP 500, log the
    exception through the 'main' logger channel, and leak no internal detail.
    The injection patches every plausible get_db_connection resolution site
    (main binding pre-move; app module / app.db post-move)."""

    def _boom(*args, **kwargs):
        raise RuntimeError("ut17-red-db-boom")

    monkeypatch.setattr(app_db_module, "get_db_connection", _boom)
    monkeypatch.setattr(main, "get_db_connection", _boom)
    app_module = sys.modules.get("app")
    if app_module is not None and hasattr(app_module, "get_db_connection"):
        monkeypatch.setattr(app_module, "get_db_connection", _boom)

    with caplog.at_level(logging.ERROR, logger="main"):
        response = main.app.test_client().get("/health")

    assert response.status_code == 500
    assert response.get_json() == {"status": "error"}, (
        "failure payload must be exactly {'status': 'error'} with no leak"
    )
    records = [
        record
        for record in caplog.records
        if record.name == "main" and record.levelno >= logging.ERROR
    ]
    assert records, "health failure must log through the 'main' logger channel"
    assert any("healthcheck" in (record.getMessage() or "") for record in records), (
        "health failure must log through logger.exception('healthcheck falhou')"
    )
    response.close()


def test_green_28_favicon_present_and_absent_branches(tmp_path, monkeypatch):
    """favicon must use exactly os.path.join(app.root_path, 'static'); present
    -> 200 with bytes; absent -> 204 empty.  A stray favicon.ico directly at
    root_path (not under static/) must NOT be served."""
    client = main.app.test_client()

    present_root = tmp_path / "present"
    static_dir = present_root / "static"
    static_dir.mkdir(parents=True)
    favicon_bytes = b"\x00\x00\x01\x00UT17-ICO"
    (static_dir / "favicon.ico").write_bytes(favicon_bytes)
    monkeypatch.setattr(main.app, "root_path", str(present_root))

    response = client.get("/favicon.ico")
    assert response.status_code == 200
    assert response.data == favicon_bytes
    response.close()

    absent_root = tmp_path / "absent"
    absent_root.mkdir()
    (absent_root / "favicon.ico").write_bytes(b"stray-not-in-static")
    monkeypatch.setattr(main.app, "root_path", str(absent_root))

    response = client.get("/favicon.ico")
    assert response.status_code == 204
    assert response.data == b""
    response.close()
