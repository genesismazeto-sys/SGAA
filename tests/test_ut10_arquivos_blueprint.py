"""UT-10 RED — Arquivos cohort extraction contract.

Future canonical owner: ``app/views/admin/arquivos.py``.

Authoritative relocated-symbol manifest (9 symbols):
- 5 routes (LegacyRouteSpec-preserving);
- 4 cohort-exclusive helpers;
- 0 cohort-exclusive constants.

This file contains exactly 26 collected tests:
- tests ``test_red_a``..``test_red_o`` are FUTURE ARCHITECTURAL CONTRACT
  assertions; while the target module is absent they fail with plain
  AssertionError only (no ImportError / ModuleNotFoundError / AttributeError /
  TypeError / fixture or collection error);
- tests ``test_green_1``..``test_green_11`` characterize CURRENT behavior and
  invariant controls that implementation is forbidden to change.

Collection-safety rule: the future module is imported only through a guarded
loader after its file existence is established; sentinels are used instead of
exception-based RED signals. No parametrization changes the collected count.

B7-P retirement substitution (EXECUTION_PROTOCOL.md §8, UT-10 row):
``test_b7p_zero_route_movement_all_twelve_handlers_remain_main_local`` in
tests/test_phase4_arquivos_alertas_shared_owners.py is the frozen pre-
extraction assertion; the Arquivos half of it is replaced here by the RED
contract (test_red_b / test_red_c / test_red_f / test_red_g / test_red_n),
while the Alertas/Reportes half is preserved and re-characterized as a
GREEN control that must survive extraction unchanged
(test_green_8_non_ut10_handlers_remain_main_owned). The implementation phase
may retire/reconcile only the Arquivos half of the frozen B7-P assertion.

CSRF owner contract (test_red_k): the three mutating Arquivos handlers are
currently encoded in both canonical CSRF inventories as main-owned; after
extraction they must be ``app.views.admin.arquivos.<function>``. The
snapshots are read-only here; regeneration is a coherent-pair step of the
implementation phase, never part of RED.
"""

from __future__ import annotations

import ast
from copy import deepcopy
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
TARGET_PATH = PROJECT_ROOT / "app" / "views" / "admin" / "arquivos.py"
TARGET_REL = "app/views/admin/arquivos.py"
TARGET_MODULE_NAME = "app.views.admin.arquivos"
MAIN_PATH = PROJECT_ROOT / "main.py"
CREATE_APP_PATH = PROJECT_ROOT / "app" / "__init__.py"
BUSINESS_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}

FROZEN_ENTRY_AUTH_SHA256 = (
    "f5aac76c78252cd9c3d48ae3d1a438a1fdc2bc008d12dd60c9bab336e26b51ce"
)

ROUTE_NAMES = (
    "admin_arquivos",
    "admin_adicionar_arquivo",
    "admin_editar_arquivo",
    "admin_visualizar_arquivo",
    "admin_deletar_arquivo",
)

HELPER_NAMES = (
    "_redirect_admin_arquivos_return",
    "_list_admin_arquivos_rows",
    "_save_admin_arquivo_payload",
    "_best_effort_remove_admin_arquivo_file",
)

CONSTANT_NAMES: tuple[str, ...] = ()

MOVED_SYMBOLS = ROUTE_NAMES + HELPER_NAMES + CONSTANT_NAMES

ROUTE_MATRIX = (
    ("/admin/arquivos", "admin_arquivos", ("GET",)),
    ("/admin/arquivos/adicionar", "admin_adicionar_arquivo", ("POST",)),
    (
        "/admin/arquivos/<int:arquivo_id>/editar",
        "admin_editar_arquivo",
        ("GET", "POST"),
    ),
    ("/admin/arquivos/<int:arquivo_id>/visualizar", "admin_visualizar_arquivo", ("GET",)),
    ("/admin/arquivos/<int:arquivo_id>/deletar", "admin_deletar_arquivo", ("POST",)),
)

EXPECTED_PAIRS = frozenset(
    (rule, endpoint, tuple(sorted(methods))) for rule, endpoint, methods in ROUTE_MATRIX
)

RBAC_MATRIX = {
    "admin_arquivos": ("arquivos", "view"),
    "admin_adicionar_arquivo": ("arquivos", "edit"),
    "admin_editar_arquivo": ("arquivos", "edit"),
    "admin_visualizar_arquivo": ("arquivos", "view"),
    "admin_deletar_arquivo": ("arquivos", "full"),
}

COHORT_RULE_PREFIXES = ("/admin/arquivos",)

# Non-UT10 handlers that must remain main-owned through UT-10: Reportes (3)
# always; Alertas (4) only while app/views/admin/alertas.py does not exist
# (UT-11 legitimately moves them to their own canonical owner). Frozen
# substitute for the non-Arquivos half of
# test_b7p_zero_route_movement_all_twelve_handlers...
NON_UT10_MAIN_OWNED_HANDLERS = (
    "admin_alertas",
    "admin_salvar_alerta",
    "admin_alternar_alerta",
    "admin_deletar_alerta",
    "admin_reportes",
    "admin_reportes_atualizar_status",
    "admin_reportes_deletar",
)

REPORTES_MAIN_OWNED_HANDLERS = (
    "admin_reportes",
    "admin_reportes_atualizar_status",
    "admin_reportes_deletar",
)

ALERTAS_MAIN_OWNED_HANDLERS = (
    "admin_alertas",
    "admin_salvar_alerta",
    "admin_alternar_alerta",
    "admin_deletar_alerta",
)

THREE_POST_URLS = (
    "/admin/arquivos/adicionar",
    "/admin/arquivos/1/editar",
    "/admin/arquivos/1/deletar",
)

ARQUIVOS_POST_ROUTE_ENDPOINTS = {
    "/admin/arquivos/adicionar": "admin_adicionar_arquivo",
    "/admin/arquivos/<int:arquivo_id>/editar": "admin_editar_arquivo",
    "/admin/arquivos/<int:arquivo_id>/deletar": "admin_deletar_arquivo",
}

FROZEN_ARQUIVOS_ROW_SHAPE = {
    "/admin/arquivos/<int:arquivo_id>/deletar": {
        "csrf_in_html": None,
        "evidence": [
            {
                "kind": "dynamic_form",
                "page": "/admin/arquivos",
                "attr": "data-delete-url",
                "action": "/admin/arquivos/1/deletar",
                "token_mode": "helper_or_hidden",
            },
            {
                "kind": "dynamic_form",
                "page": "/admin/arquivos",
                "action": "/admin/arquivos/0/deletar",
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
        "route": "/admin/arquivos/<int:arquivo_id>/deletar",
        "status": "ok_dynamic_form_token",
        "template_related": [],
        "token_counts_per_form": [],
    },
    "/admin/arquivos/<int:arquivo_id>/editar": {
        "csrf_in_html": None,
        "evidence": [
            {
                "kind": "dynamic_form",
                "page": "/admin/arquivos",
                "action": "/admin/arquivos/0/editar",
                "token_mode": "helper_or_hidden",
            }
        ],
        "fetch_sends_token": None,
        "has_dynamic_form": True,
        "has_fetch_post": False,
        "has_post_form": False,
        "method": "POST",
        "notes": [],
        "requires_login": "admin",
        "risk": [],
        "route": "/admin/arquivos/<int:arquivo_id>/editar",
        "status": "ok_dynamic_form_token",
        "template_related": [],
        "token_counts_per_form": [],
    },
    "/admin/arquivos/adicionar": {
        "csrf_in_html": True,
        "evidence": [
            {
                "kind": "rendered_form",
                "page": "/admin/arquivos",
                "action": "/admin/arquivos/adicionar",
                "token_count": 1,
            }
        ],
        "fetch_sends_token": None,
        "has_dynamic_form": False,
        "has_fetch_post": False,
        "has_post_form": True,
        "method": "POST",
        "notes": [],
        "requires_login": "admin",
        "risk": [],
        "route": "/admin/arquivos/adicionar",
        "status": "ok_rendered_form_token",
        "template_related": [],
        "token_counts_per_form": [
            {
                "page": "/admin/arquivos",
                "action": "/admin/arquivos/adicionar",
                "token_counts": [1],
            }
        ],
    },
}

C1_ARQUIVOS_EDIT_ROUTE = "/admin/arquivos/<int:arquivo_id>/editar"
C1_ARQUIVOS_DELETE_ROUTE = "/admin/arquivos/<int:arquivo_id>/deletar"
C1_ARQUIVOS_EDIT_EVIDENCE = [
    {
        "action": "/admin/arquivos/1/editar",
        "kind": "rendered_form",
        "page": "/admin/arquivos?edit_arquivo",
        "token_count": 1,
    },
    {
        "action": "/admin/arquivos/0/editar",
        "kind": "dynamic_form",
        "page": "/admin/arquivos?edit_arquivo",
        "token_mode": "helper_or_hidden",
    },
]
C1_ARQUIVOS_DELETE_EVIDENCE = [
    {
        "action": "/admin/arquivos/1/deletar",
        "attr": "data-delete-url",
        "kind": "dynamic_form",
        "page": "/admin/arquivos?edit_arquivo",
        "token_mode": "helper_or_hidden",
    },
    {
        "action": "/admin/arquivos/0/deletar",
        "kind": "dynamic_form",
        "page": "/admin/arquivos?edit_arquivo",
        "token_mode": "helper_or_hidden",
    },
]
C1_ARQUIVOS_EDIT_TOKEN_COUNTS = [
    {
        "action": "/admin/arquivos/1/editar",
        "page": "/admin/arquivos?edit_arquivo",
        "token_counts": [1],
    }
]


def _normalize_ut10_c1_row(row):
    route = row.get("route")
    assert route in FROZEN_ARQUIVOS_ROW_SHAPE
    historical = FROZEN_ARQUIVOS_ROW_SHAPE[route]
    normalized = dict(row)

    if route == C1_ARQUIVOS_DELETE_ROUTE:
        assert row["evidence"] == historical["evidence"] + C1_ARQUIVOS_DELETE_EVIDENCE
        normalized["evidence"] = historical["evidence"]
    elif route == C1_ARQUIVOS_EDIT_ROUTE:
        assert row["csrf_in_html"] is True
        assert row["evidence"] == historical["evidence"] + C1_ARQUIVOS_EDIT_EVIDENCE
        assert row["has_post_form"] is True
        assert row["status"] == "ok_rendered_form_token"
        assert row["token_counts_per_form"] == C1_ARQUIVOS_EDIT_TOKEN_COUNTS
        normalized.update(
            {
                "csrf_in_html": historical["csrf_in_html"],
                "evidence": historical["evidence"],
                "has_post_form": historical["has_post_form"],
                "status": historical["status"],
                "token_counts_per_form": historical["token_counts_per_form"],
            }
        )

    return normalized


def _assert_ut10_historical_row_shape(row):
    normalized = _normalize_ut10_c1_row(row)
    shape = dict(normalized)
    shape.pop("view_function")
    assert shape == FROZEN_ARQUIVOS_ROW_SHAPE[row["route"]]

# ---------------------------------------------------------------------------
# Guarded loaders / AST scanners (detector self-control lives in green test 1)
# ---------------------------------------------------------------------------


def _target_module():
    """Return the future module, or None while its file does not exist.

    The import is performed only after file existence is established, so a
    missing target yields None (asserted by callers) instead of an
    ImportError-based RED signal.
    """
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
            if rule.startswith(COHORT_RULE_PREFIXES):
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
# RED — future architectural contract (A..O)
# ===========================================================================


def test_red_a_target_module_file_exists():
    assert TARGET_PATH.exists(), (
        "app/views/admin/arquivos.py does not exist yet; UT-10 must create it"
    )


def test_red_b_target_owns_exact_nine_symbols_zero_constants():
    target = _target_module()
    assert target is not None, "arquivos module absent; 9-symbol ownership contract unsatisfiable"

    source = Path(target.__file__).read_text(encoding="utf-8-sig")
    top_level = _top_level_defs(source)
    assigned = _top_level_assignments(source)

    assert top_level == set(ROUTE_NAMES) | set(HELPER_NAMES), (
        f"target top-level functions must be exactly the 9 moved callables; "
        f"missing={sorted((set(ROUTE_NAMES) | set(HELPER_NAMES)) - top_level)} "
        f"extra={sorted(top_level - (set(ROUTE_NAMES) | set(HELPER_NAMES)))}"
    )
    assert not (set(CONSTANT_NAMES) - assigned), (
        "the Arquivos cohort moves zero constants; none may be defined or "
        "redefined inside the target"
    )


def test_red_c_five_routes_admin_decorated_no_route_decorators():
    target = _target_module()
    assert target is not None, "arquivos module absent; route-ownership contract unsatisfiable"

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


def test_red_d_exactly_five_specs_six_pairs_frozen_matrix():
    target = _target_module()
    assert target is not None, "arquivos module absent; LegacyRouteSpec contract unsatisfiable"

    specs = getattr(target, "LEGACY_ROUTE_SPECS", None)
    assert isinstance(specs, tuple), "target must expose an immutable LEGACY_ROUTE_SPECS tuple"
    assert len(specs) == 5, f"expected 5 LegacyRouteSpecs, got {len(specs)}"

    encoded = {(spec.rule, spec.endpoint, spec.methods) for spec in specs}
    assert encoded == EXPECTED_PAIRS, (
        f"spec set mismatch: missing={sorted(EXPECTED_PAIRS - encoded)} "
        f"extra={sorted(encoded - EXPECTED_PAIRS)}"
    )
    assert sum(len(spec.methods) for spec in specs) == 6, (
        "specs must represent exactly 6 endpoint/method pairs"
    )
    assert {spec.view_func for spec in specs} == {
        getattr(target, name) for name in ROUTE_NAMES
    }, "every spec must reference the target-owned route function"
    assert all("." not in spec.endpoint for spec in specs), (
        "no namespaced endpoint allowed"
    )


def test_red_e_spec_endpoints_resolve_two_view_three_edit_one_full():
    target = _target_module()
    assert target is not None, "arquivos module absent; RBAC-from-specs contract unsatisfiable"

    specs = getattr(target, "LEGACY_ROUTE_SPECS", None)
    assert isinstance(specs, tuple) and len(specs) == 5, (
        "RBAC derivation requires the frozen five LegacyRouteSpecs"
    )

    scope_counts = {"view": 0, "edit": 0, "full": 0}
    for spec in specs:
        for method in spec.methods:
            requirement = get_admin_permission_requirement(spec.endpoint, method)
            assert requirement is not None, (
                f"{spec.endpoint} {method} must resolve a requirement"
            )
            resource, scope = requirement
            assert resource == "arquivos", (
                f"{spec.endpoint} must be governed by the arquivos resource, got {resource}"
            )
            assert scope in scope_counts, f"unexpected scope {scope} for {spec.endpoint}"
            scope_counts[scope] += 1
    assert scope_counts == {"view": 2, "edit": 3, "full": 1}, (
        "frozen endpoint identities must derive exactly 2 view / 3 edit / 1 full, "
        f"got {scope_counts}"
    )
    assert get_admin_permission_requirement("admin_arquivos", "GET") == ("arquivos", "view"), (
        "admin_arquivos GET must resolve to (arquivos, view)"
    )


def test_red_f_main_has_no_local_ownership_and_no_cohort_route_decorators():
    source = MAIN_PATH.read_text(encoding="utf-8-sig")
    defined = _top_level_defs(source)

    assert not (set(ROUTE_NAMES) | set(HELPER_NAMES)) & defined, (
        "main.py must no longer locally define moved callables: "
        f"{sorted((set(ROUTE_NAMES) | set(HELPER_NAMES)) & defined)}"
    )
    assert _cohort_route_decorators(source) == [], (
        "main.py must no longer register any Arquivos @app.route decorator"
    )


def test_red_g_main_facade_nine_of_nine_identity_no_wrappers():
    target = _target_module()
    assert target is not None, "arquivos module absent; main compatibility contract unsatisfiable"

    for name in MOVED_SYMBOLS:
        assert hasattr(main, name), f"main.{name} missing from the compatibility facade"
        assert getattr(main, name) is getattr(target, name), (
            f"main.{name} must be the identical object exported by arquivos "
            "(identity re-export, no wrapper)"
        )

def test_red_h_target_has_no_main_backedge():
    target = _target_module()
    assert target is not None, "arquivos module absent; no-back-edge contract unsatisfiable"

    source = Path(target.__file__).read_text(encoding="utf-8-sig")
    edges = _main_back_edges(source)
    assert edges == [], (
        "target must not import main (including dynamic-import equivalents): "
        f"{edges}"
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
    assert "register_admin_arquivos_blueprint" in kw_pairs, (
        "create_app must accept register_admin_arquivos_blueprint"
    )
    default = kw_pairs["register_admin_arquivos_blueprint"]
    assert isinstance(default, ast.Constant) and default.value is True, (
        "register_admin_arquivos_blueprint must default to True"
    )

    registration_calls = [
        call
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "register_legacy_blueprint"
        and any(
            isinstance(arg, ast.Name) and arg.id == "bp_admin_arquivos"
            for arg in call.args
        )
    ]
    assert len(registration_calls) == 1, (
        "create_app must register bp_admin_arquivos exactly once through "
        "register_legacy_blueprint"
    )


def test_red_j_factory_default_registers_five_opt_out_registers_none():
    from app import create_app

    signature = inspect.signature(create_app)
    param = signature.parameters.get("register_admin_arquivos_blueprint")
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
        register_admin_arquivos_blueprint=False,
    )

    default_rules = {
        (rule.rule, rule.endpoint) for rule in default_app.url_map.iter_rules()
    }
    assert _cohort_rules(default_app) == EXPECTED_PAIRS, (
        "default factory must register exactly the 5 frozen routes / 6 pairs"
    )
    assert _cohort_rules(opt_out_app) == frozenset(), (
        "opt-out factory must register none of the 5 cohort endpoints"
    )
    assert not any(
        rule.endpoint.startswith("admin_arquivos_blueprint.") or "." in rule.endpoint
        for rule in default_app.url_map.iter_rules()
        if rule.endpoint in ROUTE_NAMES
    ), "no namespaced endpoint variant may exist"
    assert len(default_rules) > 0, "default factory sanity check"


def test_red_k_csrf_snapshots_show_exactly_three_arquivos_owner_only_deltas():
    snapshot_dir = PROJECT_ROOT / "tests" / "_artifacts"
    for suffix in ("shadow_off", "shadow_on"):
        snapshot_path = snapshot_dir / f"csrf_inventory_{suffix}.json"
        assert snapshot_path.exists(), (
            f"canonical CSRF snapshot missing: {snapshot_path.name}"
        )
        report = json.loads(snapshot_path.read_text(encoding="utf-8-sig"))
        rows = report["rows"]
        assert len(rows) == 78, (
            "known cumulative current snapshot contract: 78 mutating rows "
            f"per snapshot, got {len(rows)}"
        )

        partition = [
            row for row in rows if row["route"] in ARQUIVOS_POST_ROUTE_ENDPOINTS
        ]
        assert len(partition) == 3, (
            "exactly three Arquivos POST rows per snapshot, "
            f"got {len(partition)} in {suffix}"
        )

        for row in partition:
            endpoint = ARQUIVOS_POST_ROUTE_ENDPOINTS[row["route"]]
            expected_owner = f"app.views.admin.arquivos.{endpoint}"
            assert row["view_function"] == expected_owner, (
                f"Arquivos owner delta unsatisfied in {suffix}: route={row['route']} "
                f"observed={row['view_function']!r} expected={expected_owner!r} "
                "(currently main.<function>, must become "
                "app.views.admin.arquivos.<function>)"
            )
            assert _assert_ut10_historical_row_shape(row) is None, (
                f"only view_function may change for Arquivos partition row "
                f"{row['route']} in {suffix}"
            )

        edit_row = next(
            row for row in partition if row["route"] == C1_ARQUIVOS_EDIT_ROUTE
        )
        for invalid_token_count in (0, 2):
            mutated = deepcopy(edit_row)
            rendered = next(
                evidence
                for evidence in mutated["evidence"]
                if evidence.get("kind") == "rendered_form"
            )
            rendered["token_count"] = invalid_token_count
            with pytest.raises(AssertionError):
                _assert_ut10_historical_row_shape(mutated)

        adicionar_row = next(
            row
            for row in partition
            if row["route"] == "/admin/arquivos/adicionar"
        )
        mutated_adicionar = deepcopy(adicionar_row)
        mutated_adicionar["evidence"] = list(mutated_adicionar["evidence"]) + [
            {"kind": "dynamic_form", "page": "/admin/arquivos?edit_arquivo"}
        ]
        with pytest.raises(AssertionError):
            _assert_ut10_historical_row_shape(mutated_adicionar)

        unrelated_row = deepcopy(
            next(
                row
                for row in rows
                if row["route"] not in ARQUIVOS_POST_ROUTE_ENDPOINTS
            )
        )
        unrelated_row["evidence"] = list(unrelated_row["evidence"]) + [
            {"kind": "dynamic_form", "page": "/synthetic-unrelated"}
        ]
        with pytest.raises(AssertionError):
            _assert_ut10_historical_row_shape(unrelated_row)

        unrelated = [
            row["route"]
            for row in rows
            if "app.views.admin.arquivos" in row["view_function"]
            and row["route"] not in ARQUIVOS_POST_ROUTE_ENDPOINTS
        ]
        assert unrelated == [], (
            f"owner delta must be confined to the three Arquivos rows: {unrelated}"
        )


def test_red_l_message_scanner_auto_covers_target_without_registration():
    from utils import messages

    catalog = messages._message_catalog()
    assert len(catalog) == 536, (
        "message catalog count must remain 536 through the extraction; "
        f"got {len(catalog)}"
    )

    backend_paths = {
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in messages._iter_backend_files()
    }
    assert TARGET_REL in backend_paths, (
        "app/views/admin/arquivos.py must be inside backend message-scanner "
        "coverage once created (no scanner-registration change expected)"
    )


def test_red_m_admin_arquivos_resolves_cohort_helpers_from_target_globals():
    target = _target_module()
    assert target is not None, (
        "arquivos module absent; cohort-helper resolution contract unsatisfiable"
    )

    view = inspect.unwrap(target.admin_arquivos)
    assert view.__module__ == TARGET_MODULE_NAME, (
        "admin_arquivos function module owner must be app.views.admin.arquivos, "
        f"got {view.__module__!r}"
    )
    loader = view.__globals__.get("_list_admin_arquivos_rows")
    assert loader is target._list_admin_arquivos_rows, (
        "admin_arquivos must resolve the cohort helper "
        "_list_admin_arquivos_rows from its own globals"
    )


def test_red_n_blueprint_identity_and_dotless_live_endpoints():
    target = _target_module()
    assert target is not None, "arquivos module absent; blueprint identity contract unsatisfiable"

    blueprint = getattr(target, "bp_admin_arquivos", None)
    assert blueprint is not None, "target must expose bp_admin_arquivos"
    assert blueprint.name == "admin_arquivos_blueprint", (
        f"blueprint name must be admin_arquivos_blueprint, got {blueprint.name!r}"
    )

    live = {
        rule.endpoint: main.app.view_functions[rule.endpoint]
        for rule in main.app.url_map.iter_rules()
        if rule.endpoint in ROUTE_NAMES
    }
    assert len(live) == 5, "exactly five live Arquivos endpoints required"
    for name in ROUTE_NAMES:
        assert live[name] is getattr(target, name), (
            f"live endpoint {name} must identity-match the target callable"
        )

    namespaced = [
        endpoint
        for endpoint in main.app.view_functions
        if endpoint.startswith("admin_arquivos_blueprint.")
    ]
    assert namespaced == [], (
        f"no admin_arquivos_blueprint.* namespaced endpoint may exist: {namespaced}"
    )


def test_red_o_extracted_helper_security_contract_under_app_context(tmp_path, monkeypatch):
    target = _target_module()
    assert target is not None, (
        "arquivos module absent; extracted-helper security/owner contract "
        "unsatisfiable"
    )

    helper = getattr(target, "_best_effort_remove_admin_arquivo_file", None)
    assert callable(helper), (
        "target must own _best_effort_remove_admin_arquivo_file"
    )
    assert inspect.unwrap(helper).__module__ == TARGET_MODULE_NAME, (
        "helper module owner must be app.views.admin.arquivos, "
        f"got {inspect.unwrap(helper).__module__!r}"
    )
    assert main._best_effort_remove_admin_arquivo_file is helper, (
        "main must re-export the helper by identity (no wrapper)"
    )

    upload_root = tmp_path / "uploads"
    upload_root.mkdir(parents=True, exist_ok=True)

    outside_file = tmp_path / "outside-file.pdf"
    outside_file.write_bytes(b"outside")

    external_dir = tmp_path / "external"
    external_dir.mkdir(parents=True, exist_ok=True)
    secret_file = external_dir / "secret.pdf"
    secret_file.write_bytes(b"secret")

    nested_dir = upload_root / "admin_arquivos"
    nested_dir.mkdir(parents=True, exist_ok=True)
    nested_file = nested_dir / "x.pdf"
    nested_file.write_bytes(b"legitimate")

    monkeypatch.setitem(main.app.config, "UPLOAD_FOLDER", str(upload_root))

    with main.app.app_context():
        helper(os.path.join("..", "outside-file.pdf"))
        helper(str(secret_file))
        helper(os.path.join("admin_arquivos", "x.pdf"))

    assert outside_file.exists(), (
        "helper must refuse ../ traversal and keep the external file"
    )
    assert secret_file.exists(), (
        "helper must refuse an absolute external path and keep the file"
    )
    assert not nested_file.exists(), (
        "helper must delete a legitimate in-root nested file"
    )


# ===========================================================================
# GREEN — current behavior / invariant controls
# ===========================================================================


def test_green_1_detector_self_control():
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


def test_green_2_live_route_matrix_five_routes_six_pairs():
    rules = [
        rule
        for rule in main.app.url_map.iter_rules()
        if rule.endpoint in ROUTE_NAMES
    ]
    assert len(rules) == 5, f"expected 5 live cohort rules, got {len(rules)}"
    assert _cohort_rules(main.app) == EXPECTED_PAIRS, (
        "live url_map must match the frozen 6-pair matrix"
    )


def test_green_3_rbac_exact_matches_and_live_endpoint_set():
    for endpoint, (resource, scope) in RBAC_MATRIX.items():
        method = (
            "POST"
            if endpoint not in {"admin_arquivos", "admin_visualizar_arquivo"}
            else "GET"
        )
        assert get_admin_permission_requirement(endpoint, method) == (resource, scope), (
            f"{endpoint} {method} must resolve to ({resource}, {scope})"
        )
    assert get_admin_permission_requirement("admin_editar_arquivo", "POST") == (
        "arquivos",
        "edit",
    ), "admin_editar_arquivo POST must resolve to (arquivos, edit)"

    live_endpoints = {
        endpoint
        for endpoint in main.app.view_functions
        if endpoint.startswith("admin_") and "arquivo" in endpoint
    }
    assert live_endpoints == set(ROUTE_NAMES), (
        "exactly the five frozen admin Arquivos endpoints must be live; "
        f"no unrelated endpoint admitted; got {sorted(live_endpoints)}"
    )


def test_green_4_global_invariants_routes_endpoints_rbac_hooks():
    rules = list(main.app.url_map.iter_rules())
    assert len(rules) == 131, f"routes must stay 131, got {len(rules)}"
    assert len(main.app.view_functions) == 130, (
        f"distinct endpoints must stay 130, got {len(main.app.view_functions)}"
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

    assert len(messages._message_catalog()) == 536, (
        "current catalog baseline must be 536"
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
    assert "app/views/admin/acesso.py" in backend_paths, (
        "sanity: an existing admin view module must be inside scanner coverage"
    )


def test_green_6_schema_version_three_no_migration_v4():
    from app.db_maintenance import SCHEMA_MIGRATIONS, SCHEMA_VERSION

    assert SCHEMA_VERSION == 3, f"SCHEMA_VERSION must stay 3, got {SCHEMA_VERSION}"
    versions = {version for version, _name, _fn in SCHEMA_MIGRATIONS}
    assert versions == {1, 2, 3}, (
        "migration registry must contain exactly v1/v2/v3, no v4; "
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


def test_green_8_reportes_main_owned_and_alertas_conditional_on_owner():
    source = MAIN_PATH.read_text(encoding="utf-8-sig")
    defined = _top_level_defs(source)

    # Reportes: main-owned only while their canonical owner does not exist.
    # Once app/views/admin/reportes.py exists, they must be owned exactly by
    # that module and main must expose them through the identity facade only.
    reportes_path = PROJECT_ROOT / "app" / "views" / "admin" / "reportes.py"
    if reportes_path.exists():
        import importlib

        reportes = importlib.import_module("app.views.admin.reportes")
        for name in REPORTES_MAIN_OWNED_HANDLERS:
            assert getattr(main, name, None) is getattr(reportes, name, None), (
                f"main.{name} must identity-re-export reportes.{name} "
                "(no wrapper, no local definition)"
            )
            view = main.app.view_functions.get(name)
            assert view is not None, f"live endpoint {name} missing"
            assert view.__module__ == "app.views.admin.reportes", (
                f"{name} must be owned by app.views.admin.reportes, "
                f"got {view.__module__!r}"
            )
    else:
        for name in REPORTES_MAIN_OWNED_HANDLERS:
            assert name in defined, (
                f"{name} must still be locally defined in main.py "
                "while app/views/admin/reportes.py is absent"
            )
            view = main.app.view_functions.get(name)
            assert view is not None, f"live endpoint {name} missing"
            assert view.__module__ == "main", (
                f"{name} must remain main-owned, got {view.__module__!r}"
            )

    # Alertas: main-owned only while their canonical owner does not exist.
    # Once app/views/admin/alertas.py exists, they must be owned exactly by
    # that module and main must expose them through the identity facade only.
    alertas_path = PROJECT_ROOT / "app" / "views" / "admin" / "alertas.py"
    if alertas_path.exists():
        import importlib

        alertas = importlib.import_module("app.views.admin.alertas")
        for name in ALERTAS_MAIN_OWNED_HANDLERS:
            assert getattr(main, name, None) is getattr(alertas, name, None), (
                f"main.{name} must identity-re-export alertas.{name} "
                "(no wrapper, no local definition)"
            )
            view = main.app.view_functions.get(name)
            assert view is not None, f"live endpoint {name} missing"
            assert view.__module__ == "app.views.admin.alertas", (
                f"{name} must be owned by app.views.admin.alertas, "
                f"got {view.__module__!r}"
            )
    else:
        for name in ALERTAS_MAIN_OWNED_HANDLERS:
            assert name in defined, (
                f"{name} must still be locally defined in main.py "
                "while app/views/admin/alertas.py is absent"
            )
            view = main.app.view_functions.get(name)
            assert view is not None, f"live endpoint {name} missing"
            assert view.__module__ == "main", (
                f"{name} must remain main-owned, got {view.__module__!r}"
            )


def test_green_9_uploaded_file_boundary_main_owned_outside_cohort():
    # UT-17 seam (TEST_CONTRACT_SEAM / LEGITIMATE_UT17_COCHANGE): the
    # permanent fact is that uploaded_file was never part of the UT-10
    # Arquivos cohort; only its ownership/location evolves.  Pre-target the
    # handler is main-owned; post-target it is exactly app.views.files-owned
    # with main reduced to an identity facade and the rule kept unique.
    assert "uploaded_file" not in MOVED_SYMBOLS, (
        "uploaded_file must never be part of the Arquivos cohort"
    )

    files_path = PROJECT_ROOT / "app" / "views" / "files.py"
    target = None
    if files_path.exists():
        import importlib

        target = importlib.import_module("app.views.files")

    source = MAIN_PATH.read_text(encoding="utf-8-sig")
    view = main.app.view_functions.get("uploaded_file")
    assert view is not None, "live endpoint uploaded_file missing"

    if target is None:
        assert "uploaded_file" in _top_level_defs(source), (
            "uploaded_file must remain locally defined in main.py"
        )
        assert view.__module__ == "main", (
            f"uploaded_file must remain main-owned, got {view.__module__!r}"
        )
    else:
        assert "uploaded_file" not in _top_level_defs(source), (
            "uploaded_file must no longer be locally defined in main.py"
        )
        assert view is target.uploaded_file, (
            "live uploaded_file must identity-match app.views.files.uploaded_file"
        )
        assert view.__module__ == "app.views.files", (
            f"uploaded_file must be owned by app.views.files, got {view.__module__!r}"
        )
        assert main.uploaded_file is target.uploaded_file, (
            "main.uploaded_file must be an exact identity re-export"
        )

    rules = [
        rule
        for rule in main.app.url_map.iter_rules()
        if rule.endpoint == "uploaded_file"
    ]
    assert len(rules) == 1 and rules[0].rule == "/uploads/<path:filename>", (
        "uploaded_file rule must stay /uploads/<path:filename>"
    )


def test_green_10_csrf_governance_three_posts_400_get_redirects():
    app = main.app
    original_csrf = app.config.get("WTF_CSRF_ENABLED")
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        for url in THREE_POST_URLS:
            response = app.test_client().post(url)
            assert response.status_code == 400, (
                f"unsafe Arquivos method {url} must be CSRF-governed (400 "
                f"without token), got {response.status_code}"
            )
        response = app.test_client().get("/admin/arquivos")
        assert response.status_code in (302, 303), (
            "Arquivos GET must remain outside CSRF and redirect "
            f"unauthenticated, got {response.status_code}"
        )
    finally:
        if original_csrf is None:
            app.config.pop("WTF_CSRF_ENABLED", None)
        else:
            app.config["WTF_CSRF_ENABLED"] = original_csrf


def test_green_11_auth_and_admin_access_unchanged_controls():
    data = (PROJECT_ROOT / "app" / "auth.py").read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    assert digest == FROZEN_ENTRY_AUTH_SHA256, (
        "app/auth.py must remain byte-identical to the UT-10 ENTRY frozen "
        f"hash {FROZEN_ENTRY_AUTH_SHA256}; got {digest}"
    )

    import app.admin_access as admin_access_module

    source = Path(admin_access_module.__file__).read_text(encoding="utf-8-sig")
    top_level = _top_level_defs(source)
    assert top_level == {
        "_fetch_user_access_overrides",
        "_build_access_scope_groups_for_level",
        "_load_admin_access_context",
        "_get_current_admin_access_context",
        "_admin_can",
    }, f"app/admin_access.py must keep exactly the five canonical helpers; got {top_level}"
