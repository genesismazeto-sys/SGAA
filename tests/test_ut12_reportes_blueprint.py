"""UT-12 RED — Reportes cohort extraction contract.

Future canonical owner: ``app/views/admin/reportes.py``.

Authoritative relocated-symbol manifest (6 symbols):
- 4 routes (LegacyRouteSpec-preserving);
- 1 cohort-exclusive helper (``_reporte_status_badge_type``);
- 1 cohort-exclusive constant (``REPORTE_STATUS_OPTIONS``).

This file contains exactly 26 collected tests:
- tests ``test_red_a``..``test_red_n`` are FUTURE ARCHITECTURAL CONTRACT
  assertions; while the target module is absent they fail with plain
  AssertionError only (no ImportError / ModuleNotFoundError / AttributeError /
  TypeError / fixture or collection error);
- tests ``test_green_1``..``test_green_12`` characterize CURRENT behavior and
  invariant controls that implementation is forbidden to change.

Collection-safety rule: the future module is imported only through a guarded
loader after its file existence is established; sentinels are used instead of
exception-based RED signals.  No parametrization changes the collected count.

B7-P retirement substitution (EXECUTION_PROTOCOL.md §8, UT-12 row):
``test_b7p_reportes_ownership_unchanged`` and
``test_b7p_non_ut11_reportes_handlers_remain_main_local`` in
tests/test_phase4_arquivos_alertas_shared_owners.py are the frozen
pre-extraction assertions; their protection migrates here via the RED
contract (test_red_b / test_red_c / test_red_f / test_red_g / test_red_h /
test_red_m / test_red_n), while the Dashboard half of the split stays
characterized as a GREEN control that must survive extraction unchanged
(test_green_8_dashboard_ownership_state_aware; the Dashboard later-cohort
ownership became state-aware at UT-13).  The implementation phase may
retire/reconcile only the Reportes half of the frozen B7-P assertions.

CSRF owner contract (test_red_k): the two mutating Reportes handlers are
currently encoded in both canonical CSRF inventories as main-owned; after
extraction they must be ``app.views.admin.reportes.<function>``.  The
snapshots are read-only here; regeneration is a coherent-pair step of the
implementation phase, never part of RED.

Shared canonical owners are NOT moved into the target:
``ensure_reportes_table`` (app.db_maintenance) and ``REPORTE_CATEGORY_OPTIONS``
(app.reporting) stay where they are; the routes retain their exact
schema-ensure behavior (UT-12 is MOVE, DO NOT CHANGE — no C4/schema
cleanup, no migration v4).
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import os
import sys
from pathlib import Path

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from app.auth import get_admin_permission_requirement

import main


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TARGET_PATH = PROJECT_ROOT / "app" / "views" / "admin" / "reportes.py"
TARGET_REL = "app/views/admin/reportes.py"
TARGET_MODULE_NAME = "app.views.admin.reportes"
MEUS_DADOS_TARGET_PATH = PROJECT_ROOT / "app" / "views" / "admin" / "meus_dados.py"
DEMO_TARGET_PATH = PROJECT_ROOT / "app" / "views" / "admin" / "demo.py"
MAIN_PATH = PROJECT_ROOT / "main.py"
CREATE_APP_PATH = PROJECT_ROOT / "app" / "__init__.py"
BUSINESS_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}

ROUTE_NAMES = (
    "admin_reportes",
    "admin_reportes_novo",
    "admin_reportes_atualizar_status",
    "admin_reportes_deletar",
)

HELPER_NAMES = ("_reporte_status_badge_type",)

CONSTANT_NAMES = ("REPORTE_STATUS_OPTIONS",)

MOVED_SYMBOLS = ROUTE_NAMES + HELPER_NAMES + CONSTANT_NAMES

ROUTE_MATRIX = (
    ("/admin/reportes", "admin_reportes", ("GET",)),
    (
        "/admin/reportes/novo",
        "admin_reportes_novo",
        ("POST",),
    ),
    (
        "/admin/reportes/<int:reporte_id>/status",
        "admin_reportes_atualizar_status",
        ("POST",),
    ),
    (
        "/admin/reportes/<int:reporte_id>/deletar",
        "admin_reportes_deletar",
        ("POST",),
    ),
)

EXPECTED_PAIRS = frozenset(
    (rule, endpoint, tuple(sorted(methods))) for rule, endpoint, methods in ROUTE_MATRIX
)

RBAC_MATRIX = {
    "admin_reportes": ("reportes", "view"),
    "admin_reportes_novo": ("reportes", "edit"),
    "admin_reportes_atualizar_status": ("reportes", "edit"),
    "admin_reportes_deletar": ("reportes", "full"),
}

SCOPE_COUNTS = {"view": 1, "edit": 2, "full": 1}

COHORT_RULE_PREFIXES = ("/admin/reportes",)

DASHBOARD_ROUTE_NAMES = (
    "admin_dashboard",
    "admin_demo_clientes_form_pack",
    "admin_meus_dados",
)

TWO_POST_URLS = (
    "/admin/reportes/novo",
    "/admin/reportes/1/status",
    "/admin/reportes/1/deletar",
)

REPORTES_POST_ROUTE_ENDPOINTS = {
    "/admin/reportes/<int:reporte_id>/status": "admin_reportes_atualizar_status",
    "/admin/reportes/<int:reporte_id>/deletar": "admin_reportes_deletar",
}

FROZEN_REPORTE_STATUS_OPTIONS = (
    "Novo",
    "Em análise",
    "Resolvido",
)

FROZEN_REPORTES_ROW_SHAPE = {
    "/admin/reportes/<int:reporte_id>/deletar": {
        "csrf_in_html": None,
        "evidence": [
            {
                "kind": "dynamic_form",
                "page": "/admin/reportes",
                "attr": "data-delete-url",
                "action": "/admin/reportes/1/deletar",
                "token_mode": "helper_or_hidden",
            },
        ],
        "fetch_sends_token": None,
        "has_dynamic_form": True,
        "has_fetch_post": False,
        "has_post_form": False,
        "method": "POST",
        "notes": [],
        "requires_login": "admin",
        "risk": [],
        "route": "/admin/reportes/<int:reporte_id>/deletar",
        "status": "ok_dynamic_form_token",
        "template_related": [],
        "token_counts_per_form": [],
    },
    "/admin/reportes/<int:reporte_id>/status": {
        "csrf_in_html": None,
        "evidence": [],
        "fetch_sends_token": None,
        "has_dynamic_form": False,
        "has_fetch_post": False,
        "has_post_form": False,
        "method": "POST",
        "notes": [
            "tests/test_release_admin_actions_csrf.py::test_release_admin_post_actions_require_active_csrf_token",
        ],
        "requires_login": "admin",
        "risk": [],
        "route": "/admin/reportes/<int:reporte_id>/status",
        "status": "ok_specific_regression_test",
        "template_related": [],
        "token_counts_per_form": [],
    },
}

# ---------------------------------------------------------------------------
# Guarded loaders / AST scanners (detector self-control lives in green test 1)
# ---------------------------------------------------------------------------


def _target_module():
    if not TARGET_PATH.exists():
        return None
    import importlib

    return importlib.import_module(TARGET_MODULE_NAME)


def _top_level_defs(source: str) -> set[str]:
    tree = ast.parse(source)
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _top_level_assignments(source: str) -> set[str]:
    tree = ast.parse(source)
    names = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _top_level_import_sources(source: str) -> set[str]:
    tree = ast.parse(source)
    sources = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            sources.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            sources.add(node.module or "")
    return sources


def _cohort_route_decorators(source: str) -> list[str]:
    tree = ast.parse(source)
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and isinstance(decorator.func.value, ast.Name)
                and decorator.func.value.id == "app"
                and decorator.func.attr == "route"
                and decorator.args
                and isinstance(decorator.args[0], ast.Constant)
            ):
                continue
            rule = str(decorator.args[0].value)
            if any(rule.startswith(prefix) for prefix in COHORT_RULE_PREFIXES):
                hits.append(rule)
    return hits


def _route_decorator_calls(source: str) -> list[str]:
    tree = ast.parse(source)
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute):
                if decorator.func.attr == "route":
                    hits.append(ast.unparse(decorator))
    return hits


def _main_back_edges(source: str) -> list[tuple[str, str, int]]:
    tree = ast.parse(source)
    edges: list[tuple[str, str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "main" or alias.name.startswith("main."):
                    edges.append(("import", alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.module and (node.module == "main" or node.module.startswith("main.")):
                edges.append(("from", node.module, node.lineno))
        elif isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id in {"importlib", "import_module"}
            ):
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and str(arg.value) == "main":
                        edges.append(("dynamic-import", "main", node.lineno))
            if (
                isinstance(func, ast.Name)
                and func.id == "__import__"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and str(node.args[0].value) == "main"
            ):
                edges.append(("__import__", "main", node.lineno))
        elif isinstance(node, ast.Subscript):
            value = node.value
            if (
                isinstance(value, ast.Attribute)
                and isinstance(value.value, ast.Name)
                and value.value.id == "sys"
                and value.attr == "modules"
                and isinstance(node.slice, ast.Constant)
                and str(node.slice.value) == "main"
            ):
                edges.append(("sys.modules", "main", node.lineno))
    return edges


def _cohort_rules(app):
    return {
        (
            rule.rule,
            rule.endpoint,
            tuple(sorted(set(rule.methods or ()) & BUSINESS_METHODS)),
        )
        for rule in app.url_map.iter_rules()
        if rule.endpoint in ROUTE_NAMES
    }


def _all_main_hooks() -> list[str]:
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
    return hooks


# ===========================================================================
# RED — future architectural contract (A..N)
# ===========================================================================


def test_red_a_target_module_file_exists():
    assert TARGET_PATH.exists(), (
        "app/views/admin/reportes.py does not exist yet; UT-12 must create it"
    )


def test_red_b_target_owns_exact_five_symbols_one_constant():
    target = _target_module()
    assert target is not None, (
        "reportes module absent; 5-symbol ownership contract unsatisfiable"
    )

    source = Path(target.__file__).read_text(encoding="utf-8-sig")
    top_level = _top_level_defs(source)
    assigned = _top_level_assignments(source)

    assert top_level == set(ROUTE_NAMES) | set(HELPER_NAMES), (
        f"target top-level functions must be exactly the 4 moved callables; "
        f"missing={sorted((set(ROUTE_NAMES) | set(HELPER_NAMES)) - top_level)} "
        f"extra={sorted(top_level - (set(ROUTE_NAMES) | set(HELPER_NAMES)))}"
    )
    assert "REPORTE_STATUS_OPTIONS" in assigned, (
        "target must define REPORTE_STATUS_OPTIONS as a top-level assignment"
    )
    for name in ROUTE_NAMES + HELPER_NAMES:
        obj = getattr(target, name, None)
        assert obj is not None, f"target.{name} missing"
        if callable(obj):
            assert inspect.unwrap(obj).__module__ == TARGET_MODULE_NAME, (
                f"target.{name} must be defined in app.views.admin.reportes, "
                f"got {inspect.unwrap(obj).__module__!r}"
            )


def test_red_c_three_routes_admin_decorated_no_route_decorators():
    target = _target_module()
    assert target is not None, "reportes module absent; route-ownership contract unsatisfiable"

    source = Path(target.__file__).read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert set(ROUTE_NAMES) <= set(functions)
    for name in ROUTE_NAMES:
        decorators = {ast.unparse(item) for item in functions[name].decorator_list}
        assert decorators == {"admin_required"}, (
            f"route {name} decorators must be exactly {{admin_required}}, got {decorators}"
        )
    assert _route_decorator_calls(source) == [], (
        "target must not contain any @app.route / @bp.route decorators; "
        "routes register through LegacyRouteSpec"
    )


def test_red_d_exactly_three_specs_three_pairs_frozen_matrix():
    target = _target_module()
    assert target is not None, "reportes module absent; LegacyRouteSpec contract unsatisfiable"

    specs = getattr(target, "LEGACY_ROUTE_SPECS", None)
    assert isinstance(specs, tuple), "target must expose an immutable LEGACY_ROUTE_SPECS tuple"
    assert len(specs) == 4, f"expected 4 LegacyRouteSpecs, got {len(specs)}"

    encoded = {(spec.rule, spec.endpoint, spec.methods) for spec in specs}
    assert encoded == EXPECTED_PAIRS, (
        f"spec set mismatch: missing={sorted(EXPECTED_PAIRS - encoded)} "
        f"extra={sorted(encoded - EXPECTED_PAIRS)}"
    )
    assert sum(len(spec.methods) for spec in specs) == 4, (
        "specs must represent exactly 4 endpoint/method pairs"
    )
    assert {spec.view_func for spec in specs} == {
        getattr(target, name) for name in ROUTE_NAMES
    }, "every spec must reference the target-owned route function"
    assert all("." not in spec.endpoint for spec in specs), (
        "no namespaced endpoint allowed"
    )


def test_red_e_spec_endpoints_resolve_one_view_one_edit_one_full():
    target = _target_module()
    assert target is not None, "reportes module absent; RBAC-from-specs contract unsatisfiable"

    specs = getattr(target, "LEGACY_ROUTE_SPECS", None)
    assert isinstance(specs, tuple) and len(specs) == 4, (
        "RBAC derivation requires the four Reportes LegacyRouteSpecs"
    )

    scope_counts = {"view": 0, "edit": 0, "full": 0}
    for spec in specs:
        for method in spec.methods:
            requirement = get_admin_permission_requirement(spec.endpoint, method)
            assert requirement is not None, (
                f"{spec.endpoint} {method} must resolve a requirement"
            )
            resource, scope = requirement
            assert resource == "reportes", (
                f"{spec.endpoint} must be governed by the reportes resource, got {resource}"
            )
            assert scope in scope_counts, f"unexpected scope {scope} for {spec.endpoint}"
            scope_counts[scope] += 1
    assert scope_counts == SCOPE_COUNTS, (
        "frozen endpoint identities must derive exactly 1 view / 1 edit / 1 full, "
        f"got {scope_counts}"
    )
    assert get_admin_permission_requirement("admin_reportes", "GET") == ("reportes", "view"), (
        "admin_reportes GET must resolve to (reportes, view)"
    )


def test_red_f_main_has_no_local_ownership_and_no_cohort_route_decorators():
    source = MAIN_PATH.read_text(encoding="utf-8-sig")
    defined = _top_level_defs(source)
    assigned = _top_level_assignments(source)

    assert not (set(ROUTE_NAMES) | set(HELPER_NAMES)) & defined, (
        "main.py must no longer locally define moved callables: "
        f"{sorted((set(ROUTE_NAMES) | set(HELPER_NAMES)) & defined)}"
    )
    assert "REPORTE_STATUS_OPTIONS" not in assigned, (
        "main.py must no longer locally assign REPORTE_STATUS_OPTIONS for the "
        "Reportes implementation (identity re-export only)"
    )
    assert _cohort_route_decorators(source) == [], (
        "main.py must no longer register any Reportes @app.route decorator"
    )


def test_red_g_main_facade_five_of_five_identity_no_wrappers():
    target = _target_module()
    assert target is not None, "reportes module absent; main compatibility contract unsatisfiable"

    for name in MOVED_SYMBOLS:
        assert hasattr(main, name), f"main.{name} missing from the compatibility facade"
        assert getattr(main, name) is getattr(target, name), (
            f"main.{name} must be the identical object exported by reportes "
            "(identity re-export, no wrapper, no copied constant)"
        )


def test_red_h_target_has_no_main_backedge():
    target = _target_module()
    assert target is not None, "reportes module absent; no-back-edge contract unsatisfiable"

    source = Path(target.__file__).read_text(encoding="utf-8-sig")
    edges = _main_back_edges(source)
    assert edges == [], (
        f"target must not import main (including dynamic-import equivalents): {edges}"
    )


def test_red_i_factory_declares_keyword_and_single_registration_path():
    tree = ast.parse(CREATE_APP_PATH.read_text(encoding="utf-8-sig"))
    create_app = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "create_app"
    )

    kw_pairs = {
        arg.arg: default
        for arg, default in zip(create_app.args.kwonlyargs, create_app.args.kw_defaults)
    }
    assert "register_admin_reportes_blueprint" in kw_pairs, (
        "create_app must accept register_admin_reportes_blueprint"
    )
    default = kw_pairs["register_admin_reportes_blueprint"]
    assert isinstance(default, ast.Constant) and default.value is True, (
        "register_admin_reportes_blueprint must default to True"
    )

    registration_calls = [
        call
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "register_legacy_blueprint"
        and any(
            isinstance(arg, ast.Name) and arg.id == "bp_admin_reportes"
            for arg in call.args
        )
    ]
    assert len(registration_calls) == 1, (
        "create_app must register bp_admin_reportes exactly once through "
        "register_legacy_blueprint"
    )


def test_red_j_factory_default_registers_three_opt_out_registers_none():
    from app import create_app

    signature = inspect.signature(create_app)
    param = signature.parameters.get("register_admin_reportes_blueprint")
    assert param is not None, (
        "factory parameter missing; default/opt-out contract unsatisfiable"
    )
    assert param.default is True, (
        "factory parameter must default to True"
    )

    default_app = create_app(
        register_presets_blueprint=False,
        register_aluno_blueprint=False,
    )
    opt_out_app = create_app(
        register_presets_blueprint=False,
        register_aluno_blueprint=False,
        register_admin_reportes_blueprint=False,
    )

    default_rules = {
        (rule.rule, rule.endpoint) for rule in default_app.url_map.iter_rules()
    }
    assert _cohort_rules(default_app) == EXPECTED_PAIRS, (
        "default factory must register exactly the 3 frozen routes / 3 pairs"
    )
    assert _cohort_rules(opt_out_app) == frozenset(), (
        "opt-out factory must register none of the 3 cohort endpoints"
    )
    assert not any(
        rule.endpoint.startswith("admin_reportes_blueprint.") or "." in rule.endpoint
        for rule in default_app.url_map.iter_rules()
        if rule.endpoint in ROUTE_NAMES
    ), "no namespaced endpoint variant may exist"
    assert len(default_rules) > 0, "default factory sanity check"


def test_red_k_csrf_snapshots_show_exactly_two_reportes_owner_only_deltas():
    snapshot_dir = PROJECT_ROOT / "tests" / "_artifacts"
    for suffix in ("shadow_off", "shadow_on"):
        snapshot_path = snapshot_dir / f"csrf_inventory_{suffix}.json"
        assert snapshot_path.exists(), (
            f"canonical CSRF snapshot missing: {snapshot_path.name}"
        )
        report = json.loads(snapshot_path.read_text(encoding="utf-8-sig"))
        rows = report["rows"]
        assert len(rows) == 77, (
            "known cumulative current snapshot contract: 78 mutating rows "
            f"per snapshot, got {len(rows)}"
        )

        partition = [
            row for row in rows if row["route"] in REPORTES_POST_ROUTE_ENDPOINTS
        ]
        assert len(partition) == 2, (
            "exactly two Reportes POST rows per snapshot, "
            f"got {len(partition)} in {suffix}"
        )

        for row in partition:
            endpoint = REPORTES_POST_ROUTE_ENDPOINTS[row["route"]]
            expected_owner = f"app.views.admin.reportes.{endpoint}"
            assert row["view_function"] == expected_owner, (
                f"Reportes owner delta unsatisfied in {suffix}: route={row['route']} "
                f"observed={row['view_function']!r} expected={expected_owner!r} "
                "(currently main.<function>, must become "
                "app.views.admin.reportes.<function>)"
            )
            shape = dict(row)
            shape.pop("view_function")
            assert shape == FROZEN_REPORTES_ROW_SHAPE[row["route"]], (
                f"only view_function may change for Reportes partition row "
                f"{row['route']} in {suffix}"
            )

        unrelated = [
            row["route"]
            for row in rows
            if "app.views.admin.reportes" in row["view_function"]
            and row["route"] not in REPORTES_POST_ROUTE_ENDPOINTS
        ]
        assert unrelated == [], (
            f"owner delta must be confined to the two Reportes rows: {unrelated}"
        )


def test_red_l_message_scanner_auto_covers_target_without_registration():
    from utils import messages

    catalog = messages._message_catalog()
    assert len(catalog) == 537, (
        "message catalog count must match the prod-1 baseline through the extraction; "
        f"got {len(catalog)}"
    )

    backend_paths = {
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in messages._iter_backend_files()
    }
    assert TARGET_REL in backend_paths, (
        "app/views/admin/reportes.py must be inside backend message-scanner "
        "coverage once created (no scanner-registration change expected)"
    )


def test_red_m_target_owns_reportes_routes_and_dashboard_split_state_aware():
    target = _target_module()
    assert target is not None, (
        "reportes module absent; Reportes-vs-Dashboard split contract unsatisfiable"
    )

    for name in ROUTE_NAMES:
        view = main.app.view_functions.get(name)
        assert view is not None, f"live endpoint {name} missing"
        assert inspect.unwrap(view).__module__ == TARGET_MODULE_NAME, (
            f"{name} must be owned by app.views.admin.reportes after extraction, "
            f"got {inspect.unwrap(view).__module__!r}"
        )
        assert view is getattr(target, name), (
            f"live endpoint {name} must identity-match the target callable"
        )

    # UT-13 seam: only the Dashboard later-cohort ownership is state-aware.
    # Expected state derives from REAL dashboard target availability.
    dashboard_path = PROJECT_ROOT / "app" / "views" / "admin" / "dashboard.py"
    if dashboard_path.exists():
        import importlib

        dashboard = importlib.import_module("app.views.admin.dashboard")
        view = main.app.view_functions.get("admin_dashboard")
        assert view is not None, "live Dashboard endpoint admin_dashboard missing"
        assert view.__module__ == "app.views.admin.dashboard", (
            "admin_dashboard must be owned by app.views.admin.dashboard after "
            f"UT-13 extraction, got {view.__module__!r}"
        )
        assert view is dashboard.admin_dashboard, (
            "live admin_dashboard must identity-match the dashboard target callable"
        )
    else:
        view = main.app.view_functions.get("admin_dashboard")
        assert view is not None, "live Dashboard endpoint admin_dashboard missing"
        assert view.__module__ == "main", (
            "admin_dashboard must remain main-owned pre-target, "
            f"got {view.__module__!r}"
        )

    for name in ("admin_demo_clientes_form_pack", "admin_meus_dados"):
        view = main.app.view_functions.get(name)
        assert view is not None, f"live Dashboard neighbor endpoint {name} missing"
        expected_module = (
            "app.views.admin.meus_dados"
            if name == "admin_meus_dados" and MEUS_DADOS_TARGET_PATH.exists()
            else "app.views.admin.demo"
            if name == "admin_demo_clientes_form_pack" and DEMO_TARGET_PATH.exists()
            else "main"
        )
        assert view.__module__ == expected_module, (
            f"Dashboard neighbor {name} must be owned by {expected_module!r} "
            f"(UT-14/UT-15 state-aware), got {view.__module__!r}"
        )


def test_red_n_blueprint_identity_and_dotless_live_endpoints():
    target = _target_module()
    assert target is not None, (
        "reportes module absent; blueprint identity contract unsatisfiable"
    )

    blueprint = getattr(target, "bp_admin_reportes", None)
    assert blueprint is not None, "target must expose bp_admin_reportes"
    assert blueprint.name == "admin_reportes_blueprint", (
        f"blueprint name must be admin_reportes_blueprint, got {blueprint.name!r}"
    )

    live = {
        rule.endpoint: main.app.view_functions[rule.endpoint]
        for rule in main.app.url_map.iter_rules()
        if rule.endpoint in ROUTE_NAMES
    }
    assert len(live) == 4, "exactly four live Reportes endpoints required"
    for name in ROUTE_NAMES:
        assert live[name] is getattr(target, name), (
            f"live endpoint {name} must identity-match the target callable"
        )

    namespaced = [
        endpoint
        for endpoint in main.app.view_functions
        if endpoint.startswith("admin_reportes_blueprint.")
    ]
    assert namespaced == [], (
        f"no admin_reportes_blueprint.* namespaced endpoint may exist: {namespaced}"
    )


# ===========================================================================
# GREEN — current behavior / invariant controls
# ===========================================================================


def test_green_1_detector_self_control():
    loaded = _target_module()
    if TARGET_PATH.exists():
        assert loaded is not None, (
            "guarded loader must return the real target module once "
            "app/views/admin/reportes.py exists"
        )
        assert loaded.__name__ == TARGET_MODULE_NAME, (
            "guarded loader must resolve the real imported target module, "
            f"got {loaded!r}"
        )
        assert not hasattr(loaded, "_ut12_synthetic_future_production"), (
            "guarded loader must never expose a synthesized fake module"
        )
    else:
        assert loaded is None, (
            "guarded loader must return None while app/views/admin/reportes.py "
            "is absent"
        )

    nested_source = "def outer():\n    def inner():\n        return 1\n"
    assert _top_level_defs(nested_source) == {"outer"}, (
        "top-level scanner must not count nested defs"
    )

    import_source = (
        "import os\n"
        "from app.auth import admin_required\n"
        "import app.cloud_drives as _cd\n"
    )
    sources = _top_level_import_sources(import_source)
    assert {"os", "app.auth", "app.cloud_drives"} <= sources, (
        "import-source scanner must distinguish plain and from-import sources"
    )

    dynamic_source = "import importlib\nmodule = importlib.import_module('main')\n"
    assert "main" not in _top_level_import_sources(dynamic_source), (
        "import-source scanner must not report dynamic importlib calls as "
        "top-level import sources"
    )

    synthetic_backedge = (
        "import main\n"
        "from main import app\n"
        "import importlib\n"
        "x = importlib.import_module('main')\n"
        "y = __import__('main')\n"
        "z = sys.modules['main']\n"
    )
    edges = _main_back_edges(synthetic_backedge)
    kinds = {kind for kind, _, _ in edges}
    assert {
        "import",
        "from",
        "dynamic-import",
        "__import__",
        "sys.modules",
    } <= kinds, (
        "back-edge detector must flag plain import, from import, "
        "importlib.import_module('main'), __import__('main') and "
        f"sys.modules['main']; detected={sorted(kinds)}"
    )
    assert _main_back_edges("def f():\n    return 1\n") == [], (
        "back-edge detector must stay silent on a clean source"
    )


def test_green_2_live_route_matrix_three_routes_three_pairs():
    rules = [
        rule
        for rule in main.app.url_map.iter_rules()
        if rule.endpoint in ROUTE_NAMES
    ]
    assert len(rules) == 4, f"expected 4 live cohort rules, got {len(rules)}"
    assert _cohort_rules(main.app) == EXPECTED_PAIRS, (
        "live url_map must match the frozen 3-pair matrix"
    )


def test_green_3_rbac_exact_matches_and_live_endpoint_set():
    for endpoint, (resource, scope) in RBAC_MATRIX.items():
        method = "GET" if endpoint == "admin_reportes" else "POST"
        assert get_admin_permission_requirement(endpoint, method) == (resource, scope), (
            f"{endpoint} {method} must resolve to ({resource}, {scope})"
        )

    live_endpoints = {
        endpoint
        for endpoint in main.app.view_functions
        if endpoint.startswith("admin_reportes")
    }
    assert live_endpoints == set(ROUTE_NAMES), (
        "exactly the three frozen admin reportes endpoints must be live; "
        f"no unrelated endpoint admitted; got {sorted(live_endpoints)}"
    )


def test_green_4_global_invariants_routes_endpoints_rbac_hooks():
    rules = list(main.app.url_map.iter_rules())
    assert len(rules) == 128, f"routes must match prod-1 plus admin report creation, got {len(rules)}"
    assert len(main.app.view_functions) == 127, (
        f"distinct endpoints must match prod-1, got {len(main.app.view_functions)}"
    )

    business = {"GET", "POST", "PUT", "PATCH", "DELETE"}
    unmapped = [
        (rule.rule, method)
        for rule in rules
        if rule.rule.startswith("/admin")
        for method in (set(rule.methods or ()) & business)
        if get_admin_permission_requirement(rule.endpoint, method) is None
    ]
    assert unmapped == [], f"RBAC unmapped must stay 0, got {unmapped}"

    assert _all_main_hooks() == [], (
        f"hooks_main must stay 0, got {_all_main_hooks()}"
    )


def test_green_5_message_catalog_536_and_views_recursive_scanner_coverage():
    from utils import messages

    assert len(messages._message_catalog()) == 537, (
        "current catalog baseline must be 537"
    )

    backend_paths = {
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in messages._iter_backend_files()
    }
    views_files = {
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in (PROJECT_ROOT / "app" / "views").rglob("*.py")
        if "__pycache__" not in path.relative_to(PROJECT_ROOT).parts
    }
    assert views_files <= backend_paths, (
        "scanner must recursively cover every app/views/**/*.py file: "
        f"uncovered={sorted(views_files - backend_paths)}"
    )
    assert "app/views/admin/arquivos.py" in backend_paths, (
        "sanity: an existing admin view module must be inside scanner coverage"
    )


def test_green_6_schema_is_exactly_prod1_v1():
    from app.db_maintenance import SCHEMA_MIGRATIONS, SCHEMA_VERSION

    assert SCHEMA_VERSION == 3, f"prod-1 SCHEMA_VERSION must be 3, got {SCHEMA_VERSION}"
    versions = {version for version, _name, _fn in SCHEMA_MIGRATIONS}
    assert versions == {1, 2, 3}, (
        "prod-1 registry must contain only the baseline bootstrap; "
        f"got {sorted(versions)}"
    )


def test_green_7_reverse_deps_app_services_utils_main_zero():
    reverse_edges = []
    for package_name in ("app", "services", "utils"):
        package_dir = PROJECT_ROOT / package_name
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
        "reverse deps app/services/utils -> main must stay 0: "
        f"{reverse_edges}"
    )


def test_green_8_dashboard_ownership_state_aware():
    # UT-13 seam: the Dashboard cohort is target-owned when
    # app/views/admin/dashboard.py exists; the neighbors stay main-owned in
    # both states.
    dashboard_path = PROJECT_ROOT / "app" / "views" / "admin" / "dashboard.py"
    if dashboard_path.exists():
        import importlib

        dashboard = importlib.import_module("app.views.admin.dashboard")
        view = main.app.view_functions.get("admin_dashboard")
        assert view is not None, "live Dashboard endpoint admin_dashboard missing"
        assert view is dashboard.admin_dashboard, (
            "live admin_dashboard must identity-match the dashboard target"
        )
        assert view.__module__ == "app.views.admin.dashboard", (
            "admin_dashboard must be owned by app.views.admin.dashboard after "
            f"UT-13 extraction, got {view.__module__!r}"
        )
    else:
        view = main.app.view_functions.get("admin_dashboard")
        assert view is not None, "live Dashboard endpoint admin_dashboard missing"
        assert view.__module__ == "main", (
            "admin_dashboard must remain main-owned pre-target, "
            f"got {view.__module__!r}"
        )

    for name in ("admin_demo_clientes_form_pack", "admin_meus_dados"):
        view = main.app.view_functions.get(name)
        assert view is not None, f"live Dashboard neighbor endpoint {name} missing"
        expected_module = (
            "app.views.admin.meus_dados"
            if name == "admin_meus_dados" and MEUS_DADOS_TARGET_PATH.exists()
            else "app.views.admin.demo"
            if name == "admin_demo_clientes_form_pack" and DEMO_TARGET_PATH.exists()
            else "main"
        )
        assert view.__module__ == expected_module, (
            f"Dashboard neighbor {name} must be owned by {expected_module!r} "
            f"(UT-14/UT-15 state-aware), got {view.__module__!r}"
        )


def test_green_9_arquivos_and_alertas_remain_extracted_shared_owners_not_moved():
    arquivos_routes = (
        "admin_arquivos",
        "admin_adicionar_arquivo",
        "admin_editar_arquivo",
        "admin_visualizar_arquivo",
        "admin_deletar_arquivo",
    )
    for name in arquivos_routes:
        view = main.app.view_functions.get(name)
        assert view is not None, f"live endpoint {name} missing"
        assert view.__module__ == "app.views.admin.arquivos", (
            f"{name} must remain owned by app.views.admin.arquivos, "
            f"got {view.__module__!r}"
        )

    alertas_routes = (
        "admin_alertas",
        "admin_salvar_alerta",
        "admin_alternar_alerta",
        "admin_deletar_alerta",
    )
    for name in alertas_routes:
        view = main.app.view_functions.get(name)
        assert view is not None, f"live endpoint {name} missing"
        assert view.__module__ == "app.views.admin.alertas", (
            f"{name} must remain owned by app.views.admin.alertas, "
            f"got {view.__module__!r}"
        )

    assert "ensure_reportes_table" not in MOVED_SYMBOLS, (
        "ensure_reportes_table is a shared canonical owner, not part of "
        "the Reportes moved cohort"
    )
    assert "REPORTE_CATEGORY_OPTIONS" not in MOVED_SYMBOLS, (
        "REPORTE_CATEGORY_OPTIONS is a shared canonical owner "
        "(app.reporting), not part of the Reportes moved cohort"
    )
    ensure = getattr(main, "ensure_reportes_table", None)
    assert ensure is not None and ensure.__module__ == "app.db_maintenance", (
        f"ensure_reportes_table must stay owned by app.db_maintenance, "
        f"got {getattr(ensure, '__module__', None)!r}"
    )


def test_green_10_reportes_helper_and_constant_behavior_characterization():
    badge = main._reporte_status_badge_type
    assert badge(None) == "warning", "None must map to warning"
    assert badge("") == "warning", "empty string must map to warning"
    assert badge("  ") == "warning", "whitespace-only must map to warning"
    assert badge("Novo") == "danger", "Novo must map to danger"
    assert badge("Em análise") == "warning", "Em analise must map to warning"
    assert badge("Resolvido") == "success", "Resolvido must map to success"
    assert badge("qualquer outro") == "danger", "unknown non-empty must map to danger"
    assert badge("  Resolvido  ") == "success", "whitespace-padded Resolvido must map to success"

    assert main.REPORTE_STATUS_OPTIONS == FROZEN_REPORTE_STATUS_OPTIONS, (
        "REPORTE_STATUS_OPTIONS values/order must stay frozen"
    )
    assert isinstance(main.REPORTE_STATUS_OPTIONS, tuple), (
        "REPORTE_STATUS_OPTIONS must be a tuple"
    )
    assert len(main.REPORTE_STATUS_OPTIONS) == 3, (
        "REPORTE_STATUS_OPTIONS must keep exactly 3 entries"
    )
    assert main.REPORTE_STATUS_OPTIONS[0] == "Novo", (
        "first status option must be Novo"
    )


def test_green_11_csrf_governance_two_posts_400_get_redirects():
    app = main.app
    original_csrf = app.config.get("WTF_CSRF_ENABLED")
    original_check_default = app.config.get("WTF_CSRF_CHECK_DEFAULT")
    app.config["WTF_CSRF_ENABLED"] = True
    app.config["WTF_CSRF_CHECK_DEFAULT"] = True
    try:
        for url in TWO_POST_URLS:
            response = app.test_client().post(url)
            assert response.status_code == 400, (
                f"unsafe Reportes method {url} must be CSRF-governed (400 "
                f"without token), got {response.status_code}"
            )
        response = app.test_client().get("/admin/reportes")
        assert response.status_code in (302, 303), (
            "Reportes GET must remain outside CSRF and redirect "
            f"unauthenticated, got {response.status_code}"
        )
    finally:
        if original_csrf is None:
            app.config.pop("WTF_CSRF_ENABLED", None)
        else:
            app.config["WTF_CSRF_ENABLED"] = original_csrf
        if original_check_default is None:
            app.config.pop("WTF_CSRF_CHECK_DEFAULT", None)
        else:
            app.config["WTF_CSRF_CHECK_DEFAULT"] = original_check_default


def test_green_12_csrf_partition_tracked_disjoint_and_cumulative_expectation():
    # Future cumulative totals (documented expectation, not re-implemented
    # here): alunos/turmas/cursos contract 33 -> 35; matrizes 41 -> 43;
    # requisicoes 46 -> 48. The Reportes partition below proves exactly 2
    # owner-only rows, disjoint from every already-moved cohort.
    #
    # Expected owner state is derived from REAL target availability, not from
    # the snapshot itself: while reportes.py is absent the two rows must be
    # main-owned (entry state); once it exists they must all be target-owned
    # (post-extraction state). The two rows must move as ONE coherent
    # cohort -- mixed main/target ownership is rejected.
    target_owns = TARGET_PATH.exists()
    expected_owners = {
        route: (
            f"app.views.admin.reportes.{REPORTES_POST_ROUTE_ENDPOINTS[route]}"
            if target_owns
            else f"main.{REPORTES_POST_ROUTE_ENDPOINTS[route]}"
        )
        for route in REPORTES_POST_ROUTE_ENDPOINTS
    }

    snapshot_dir = PROJECT_ROOT / "tests" / "_artifacts"
    for suffix in ("shadow_off", "shadow_on"):
        snapshot_path = snapshot_dir / f"csrf_inventory_{suffix}.json"
        report = json.loads(snapshot_path.read_text(encoding="utf-8-sig"))
        rows = report["rows"]
        assert len(rows) == 77, f"snapshot {suffix} must keep 78 rows"

        partition = [
            row for row in rows if row["route"] in REPORTES_POST_ROUTE_ENDPOINTS
        ]
        assert len(partition) == 2, (
            "Reportes mutating partition must be exactly 2 rows, "
            f"got {len(partition)} in {suffix}"
        )
        for row in partition:
            assert row["method"] == "POST", (
                f"Reportes tracked row {row['route']} must be POST"
            )
            expected = expected_owners[row["route"]]
            assert row["view_function"] == expected, (
                f"Reportes row {row['route']} must be owned coherently by "
                f"{expected!r}, got {row['view_function']!r}"
            )
            shape = dict(row)
            shape.pop("view_function")
            assert shape == FROZEN_REPORTES_ROW_SHAPE[row["route"]], (
                f"only view_function may differ for Reportes partition row "
                f"{row['route']} in {suffix}"
            )

        owners = {row["view_function"] for row in partition}
        assert len(owners) == len(partition), (
            "the two Reportes rows must carry two distinct endpoints "
            f"in {suffix}"
        )
        assert all(vf.startswith("main.") for vf in owners) or all(
            vf.startswith("app.views.admin.reportes.") for vf in owners
        ), (
            "Reportes rows must belong to ONE coherent owner state (all "
            f"main.* or all app.views.admin.reportes.*), got {sorted(owners)}"
        )

        moved_routes = {
            row["route"]
            for row in rows
            if row["view_function"].startswith("app.views.admin.")
            and row["route"] not in REPORTES_POST_ROUTE_ENDPOINTS
        }
        assert {row["route"] for row in partition}.isdisjoint(moved_routes), (
            "Reportes cohort must be disjoint from all OTHER already-moved "
            f"cohorts in {suffix}"
        )
