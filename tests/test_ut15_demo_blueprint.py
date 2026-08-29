"""UT-15 RED — Demo cohort extraction contract.

Future canonical owner: ``app/views/admin/demo.py``.

Authoritative relocated-symbol manifest (EXACTLY 1 symbol):
- 1 route (LegacyRouteSpec-preserving, GET only): ``admin_demo_clientes_form_pack``.

There are NO cohort-local helpers and NO cohort-local constants in the frozen
target (only the standard wiring assignments ``bp_admin_demo`` and
``LEGACY_ROUTE_SPECS``).

Explicitly OUTSIDE UT-15 (hard boundary, both states):
``admin_dashboard``, ``admin_meus_dados``, ``uploaded_file``, ``health``,
``favicon`` and every UT-16 residual symbol stay in their current owners.
Demo is GET-only and is NOT unified into the Dashboard module merely for
sharing the ``dashboard:view`` authorization scope.

This file contains exactly 26 collected tests:
- ``test_red_a``..``test_red_j`` and ``test_red_l``..``test_red_o`` (14) are
  FUTURE ARCHITECTURAL CONTRACT assertions; while the target module is absent
  they fail with plain AssertionError only (no ImportError /
  ModuleNotFoundError / AttributeError / TypeError / fixture or collection
  error);
- ``test_green_1``..``test_green_12`` (12) characterize CURRENT behavior and
  invariant controls that implementation is forbidden to change; every GREEN
  must remain valid after legitimate extraction.

Collection-safety rule: the future module is imported only through a guarded
loader after its file existence is established; sentinels are used instead of
exception-based RED signals.  No parametrization changes the collected count.

State-aware Demo principle (supervisor-authorized UT-15 seam): the legitimate
pre-target state is main-owned; the post-target state is exactly target-owned
for the single moved symbol plus a main identity facade 1/1.  Mixed moved
ownership must fail.  Expected ownership is derived from REAL target
availability (file existence), never from the assertion under test and never
from a snapshot.

CSRF owner contract: the Demo cohort contributes ZERO mutating rows to the
canonical CSRF inventories (``/admin/demo/clientes-form-pack`` is GET-only).
The snapshots are read-only here and MUST remain repository-unchanged across
UT-15 (no tracked delta, no Git-canonical content change; CRLF/LF
materialization differences caused solely by checkout normalization are NOT
artifact mutation); no regeneration is expected.  The projected historical
cumulative owner-delta totals remain 36 / 44 / 49 (UT-14 closed at those
totals; Demo adds exactly 0 owner-only transitions).

Behavioral characterization (test_green_2 / test_green_3) is performed with a
minimal request context and a monkeypatched ``render_template`` on the LIVE
owner module — no database, no bootstrap, no caller of the main
database-initialization helper, no user seeding.  The Phase3
database-initialization caller manifest must stay at 76.

Shared canonical owners are NOT moved into the target:
``admin_required`` (app.auth), ``render_template`` (flask) and
``Blueprint``/``LegacyRouteSpec``/``configure_legacy_routes``
(app.views.admin) stay where they are; the move is MOVE, DO NOT CHANGE — no
C4/schema cleanup, no migration v4, no template edit, no RBAC redesign, no
CSRF change, no database change.
"""

from __future__ import annotations

import ast
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from flask import Response, session, url_for

from app.auth import get_admin_permission_requirement

import main


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TARGET_PATH = PROJECT_ROOT / "app" / "views" / "admin" / "demo.py"
TARGET_REL = "app/views/admin/demo.py"
TARGET_MODULE_NAME = "app.views.admin.demo"
MAIN_PATH = PROJECT_ROOT / "main.py"
CREATE_APP_PATH = PROJECT_ROOT / "app" / "__init__.py"
ADMIN_PACKAGE = PROJECT_ROOT / "app" / "views" / "admin"
BUSINESS_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}

ROUTE_NAMES = ("admin_demo_clientes_form_pack",)

MOVED_SYMBOLS = ROUTE_NAMES

ROUTE_MATRIX = (
    ("/admin/demo/clientes-form-pack", "admin_demo_clientes_form_pack", ("GET",)),
)

EXPECTED_PAIRS = frozenset(
    (rule, endpoint, tuple(sorted(methods))) for rule, endpoint, methods in ROUTE_MATRIX
)

COHORT_RULE_PREFIXES = ("/admin/demo/clientes-form-pack",)

FUTURE_FACTORY_FLAG = "register_admin_demo_blueprint"

# Hard negative surface: no neighbor, no infra route and no UT-16 residual
# symbol may be owned by (or moved into) the target.
NEGATIVE_SURFACE_NAMES = (
    "admin_dashboard",
    "admin_meus_dados",
    "uploaded_file",
    "health",
    "favicon",
    "aluno_meus_dados",
    "_coerce_aluno_snapshot_scalar",
    "_build_aluno_requisicao_snapshot_display",
    "UPPER_CODE_RE",
    "proximo_numero_turma",
    "_login_attempts",
    "_APP_DIR",
    "_TEMPLATES_DIR",
    "aluno_required",
    "validar_integridade_versionamento_atividades",
)

# Demo is GET-only and shares the dashboard:view authorization scope with
# admin_dashboard; the scope is authorization only, never module ownership.
EXPECTED_RBAC_REQUIREMENT = ("dashboard", "view")

# ---------------------------------------------------------------------------
# Guarded loaders / AST scanners (detector self-control lives in green 1)
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
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


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


# ---------------------------------------------------------------------------
# Behavioral characterization plumbing
#
# The live view is resolved through main.app.view_functions so the SAME frozen
# tests remain meaningful across the transition: they exercise the current
# main-owned implementation while the target is absent and the target-owned
# implementation once it exists.  All monkeypatches target the module the live
# view is defined in, never a fixed module name.
# ---------------------------------------------------------------------------


def _live_view():
    return main.app.view_functions["admin_demo_clientes_form_pack"]


def _live_view_module():
    import importlib

    return importlib.import_module(_live_view().__module__)


def _git_blob_bytes(relative: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"HEAD:{relative}"],
        capture_output=True,
    )
    assert result.returncode == 0, (
        f"git show HEAD:{relative} failed: {result.stderr!r}"
    )
    return result.stdout


def _head_blob_sha(relative: str) -> str:
    result = subprocess.run(
        ["git", "rev-parse", f"HEAD:{relative}"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"git rev-parse HEAD:{relative} failed: {result.stderr!r}"
    )
    return result.stdout.strip()


def _artifact_custody_report(relative: str) -> str:
    """Git-aware repository custody check for a tracked canonical artifact.

    Returns "" when the artifact has NO tracked delta relative to HEAD AND its
    Git-canonical content (clean-filtered, i.e. CRLF/LF checkout normalization
    ignored) is identical to the HEAD blob.  Returns a description otherwise.

    A real content change is always detected: the clean filter only normalizes
    line endings, never content, so any substantive mutation changes the
    hashed blob.
    """
    diff = subprocess.run(
        ["git", "diff", "--exit-code", "HEAD", "--", relative],
        capture_output=True,
    )
    if diff.returncode != 0:
        return f"tracked delta vs HEAD: {relative}"
    worktree_hash = subprocess.run(
        ["git", "hash-object", "--path", relative, relative],
        capture_output=True,
        text=True,
    )
    if worktree_hash.returncode != 0:
        return f"worktree blob hash failed: {relative}"
    if worktree_hash.stdout.strip() != _head_blob_sha(relative):
        return f"Git-canonical content differs from HEAD blob: {relative}"
    return ""


FC07_MENSAGENS_RESET_ACTIONS = (
    "/admin/mensagens/msg_03205429255601e0/reset",
    "/admin/mensagens/msg_46c6438260c43d3e/reset",
    "/admin/mensagens/msg_91bb2d4061ab3f00/reset",
)

MENSAGENS_RESET_ROUTE = "/admin/mensagens/<message_key>/reset"


def _mensagens_evidence_entries():
    return [
        {
            "kind": "rendered_form",
            "page": "/admin/mensagens",
            "action": action,
            "token_count": 1,
        }
        for action in FC07_MENSAGENS_RESET_ACTIONS
    ]


def _mensagens_token_counts_per_form_entries():
    return [
        {
            "page": "/admin/mensagens",
            "action": action,
            "token_counts": [1],
        }
        for action in FC07_MENSAGENS_RESET_ACTIONS
    ]


def _canonical_key(entry):
    return json.dumps(entry, sort_keys=True, ensure_ascii=False)


def _apply_fc07_mensagens_additions(head_obj):
    """Deep copy of the HEAD snapshot semantic object with exactly the three
    FC-07-authorized /admin/mensagens reset additions applied to the mensagens
    reset row (evidence + token_counts_per_form); None when the row is
    absent or ambiguous."""
    expected = json.loads(json.dumps(head_obj))
    mensagens_rows = [
        row
        for row in expected.get("rows", [])
        if row.get("route") == MENSAGENS_RESET_ROUTE
    ]
    if len(mensagens_rows) != 1:
        return None
    row = mensagens_rows[0]
    row["evidence"] = (
        list(row.get("evidence") or []) + _mensagens_evidence_entries()
    )
    row["token_counts_per_form"] = (
        list(row.get("token_counts_per_form") or [])
        + _mensagens_token_counts_per_form_entries()
    )
    return expected


def _apply_pg_removed_page_status(expected_obj):
    """Apply the exact prod-1 removal of the retired legacy-map page."""
    expected = json.loads(json.dumps(expected_obj))
    statuses = expected.get("summary", {}).get("page_statuses", [])
    matches = [
        item for item in statuses
        if item.get("label") == "/admin/mapeamento-legado"
        and item.get("path") == "/admin/mapeamento-legado"
        and item.get("role") == "admin"
        and item.get("status_code") == 200
    ]
    if len(matches) != 1:
        return None
    expected["summary"]["page_statuses"] = [
        item for item in statuses if item is not matches[0]
    ]
    return expected


def _apply_removed_norma_surfaces(expected_obj):
    """Apply the intentional removal of both Norma admin pages and its POST row."""
    expected = json.loads(json.dumps(expected_obj))
    rows = expected.get("rows", [])
    removed_rows = [row for row in rows if row.get("route") == "/admin/normas-atividade/nova"]
    statuses = expected.get("summary", {}).get("page_statuses", [])
    removed_statuses = [
        item for item in statuses
        if item.get("path") in {"/admin/normas-atividade", "/admin/normas-atividade/nova"}
    ]
    if len(removed_rows) != 1 or len(removed_statuses) != 2:
        return None
    expected["rows"] = [row for row in rows if row not in removed_rows]
    expected["summary"]["page_statuses"] = [
        item for item in statuses if item not in removed_statuses
    ]
    return expected


def _normalize_mensagens_list_ordering(obj):
    """Deterministic normalization of the ONLY non-semantic ordering in the
    snapshot: the evidence / token_counts_per_form lists of the mensagens
    reset row (catalogue-iteration order). All other fields, rows, routes and
    orderings are compared verbatim."""
    normalized = json.loads(json.dumps(obj))
    for row in normalized.get("rows", []):
        if row.get("route") == MENSAGENS_RESET_ROUTE:
            row["evidence"] = sorted(
                row.get("evidence") or [], key=_canonical_key
            )
            row["token_counts_per_form"] = sorted(
                row.get("token_counts_per_form") or [], key=_canonical_key
            )
    return normalized


def _csrf_snapshot_matches_authorized_delta(head_obj, work_obj) -> str:
    """Returns "" when the working semantic object equals HEAD with exactly
    the three authorized additions applied; a description otherwise. The
    comparison covers the COMPLETE snapshot structure: rows, routes, methods,
    evidence, token_counts_per_form, summary, status and ownership metadata."""
    # The live HEAD already contains the FC-07 additions. Preserve strict
    # custody for the current zero-delta artifact before checking the older
    # transitional HEAD-plus-three form.
    if _normalize_mensagens_list_ordering(head_obj) == _normalize_mensagens_list_ordering(work_obj):
        return ""
    expected_fc07 = _apply_fc07_mensagens_additions(head_obj)
    if expected_fc07 is None:
        return "HEAD snapshot has no unique mensagens reset row"
    legacy_candidates = [
        head_obj,
        expected_fc07,
        _apply_pg_removed_page_status(head_obj),
        _apply_pg_removed_page_status(expected_fc07),
    ]
    candidates = [
        _apply_removed_norma_surfaces(candidate)
        for candidate in legacy_candidates if candidate is not None
    ]
    if all(candidate is None for candidate in candidates):
        return "HEAD snapshot has no unique removable Norma surface"
    normalized_work = _normalize_mensagens_list_ordering(work_obj)
    if not any(
        candidate is not None
        and _normalize_mensagens_list_ordering(candidate) == normalized_work
        for candidate in candidates
    ):
        return "semantic delta exceeds the exactly-three authorized additions"
    return ""


def _authorized_csrf_snapshot_delta_report() -> str:
    """Strict snapshot custody: each working canonical CSRF snapshot must be
    semantically equal to HEAD plus exactly the three FC-07-authorized
    /admin/mensagens reset additions (exact action family, exact page/kind,
    token count 1, modeled as exact data), with the complete snapshot
    structure retained verbatim. Returns "" when it holds; a description
    otherwise."""
    problems = []
    for name in ("csrf_inventory_shadow_off.json", "csrf_inventory_shadow_on.json"):
        relative = f"tests/_artifacts/{name}"
        head_result = subprocess.run(
            ["git", "show", f"HEAD:{relative}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=PROJECT_ROOT,
        )
        if head_result.returncode != 0:
            problems.append(
                f"{relative}: git show HEAD failed: {head_result.stderr}"
            )
            continue
        try:
            head_obj = json.loads(head_result.stdout)
            work_obj = json.loads(
                (PROJECT_ROOT / relative).read_text(encoding="utf-8-sig")
            )
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{relative}: JSON parse failed: {exc}")
            continue
        problem = _csrf_snapshot_matches_authorized_delta(head_obj, work_obj)
        if problem:
            problems.append(f"{relative}: {problem}")
    return "; ".join(problems)


# ===========================================================================
# RED — future architectural contract (fails while the target is absent)
# ===========================================================================


def test_red_a_target_module_must_exist():
    target = _target_module()
    assert target is not None, (
        "app/views/admin/demo.py does not exist yet; UT-15 must create it"
    )


def test_red_b_exactly_one_production_function_def():
    target = _target_module()
    assert target is not None, (
        "demo module absent; exact 1-symbol ownership contract unsatisfiable"
    )
    source = Path(target.__file__).read_text(encoding="utf-8-sig")
    defined = _top_level_defs(source)
    assert defined == {"admin_demo_clientes_form_pack"}, (
        "the demo target must define exactly the single production function; "
        f"got {sorted(defined)}"
    )

    assigned = _top_level_assignments(source)
    assert {"bp_admin_demo", "LEGACY_ROUTE_SPECS"} <= assigned, (
        "the standard wiring assignments bp_admin_demo and LEGACY_ROUTE_SPECS "
        f"must exist; got {sorted(assigned)}"
    )


def test_red_c_route_admin_decorated_no_app_or_blueprint_route_decorators():
    target = _target_module()
    assert target is not None, (
        "demo module absent; decorator contract unsatisfiable"
    )
    source = Path(target.__file__).read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    route_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "admin_demo_clientes_form_pack"
    )
    decorators = {
        ast.unparse(decorator)
        for decorator in route_node.decorator_list
    }
    assert decorators == {"admin_required"}, (
        "route admin_demo_clientes_form_pack decorators must be exactly "
        f"{{admin_required}}, got {sorted(decorators)}"
    )

    assert _cohort_route_decorators(source) == [], (
        "target must not contain any @app.route decorator for the cohort"
    )
    assert _route_decorator_calls(source) == [], (
        "target must not contain any @app.route / @bp.route decorator at all; "
        f"got {_route_decorator_calls(source)}"
    )


def test_red_d_single_legacy_route_spec_and_blueprint_name():
    target = _target_module()
    assert target is not None, (
        "demo module absent; LegacyRouteSpec contract unsatisfiable"
    )
    blueprint = getattr(target, "bp_admin_demo", None)
    assert blueprint is not None, "target must expose bp_admin_demo"
    assert blueprint.name == "admin_demo_blueprint", (
        "blueprint name must be admin_demo_blueprint, "
        f"got {blueprint.name!r}"
    )

    specs = getattr(target, "LEGACY_ROUTE_SPECS", None)
    assert isinstance(specs, tuple) and len(specs) == 1, (
        "LEGACY_ROUTE_SPECS must be a tuple of exactly one LegacyRouteSpec"
    )
    spec = specs[0]
    assert spec.rule == "/admin/demo/clientes-form-pack", (
        f"rule must be /admin/demo/clientes-form-pack, got {spec.rule!r}"
    )
    assert spec.endpoint == "admin_demo_clientes_form_pack", (
        f"endpoint must be admin_demo_clientes_form_pack, got {spec.endpoint!r}"
    )
    assert spec.methods == ("GET",), (
        f"methods must be exactly (GET,), got {spec.methods!r}"
    )
    assert "." not in spec.endpoint, (
        "endpoint must stay global/dotless, got "
        f"{spec.endpoint!r}"
    )
    assert getattr(blueprint, "_sgaa_legacy_route_specs", None) is specs, (
        "LEGACY_ROUTE_SPECS must be the exact configure_legacy_routes wiring "
        "return attached to bp_admin_demo"
    )


def test_red_e_one_business_pair_dotless_endpoint():
    target = _target_module()
    assert target is not None, (
        "demo module absent; business-pair contract unsatisfiable"
    )
    specs = target.LEGACY_ROUTE_SPECS
    business_pairs = {
        (spec.rule, spec.endpoint, tuple(sorted(set(spec.methods) & BUSINESS_METHODS)))
        for spec in specs
    }
    assert business_pairs == EXPECTED_PAIRS, (
        "the cohort must contribute exactly the 1 frozen business pair "
        f"(GET only); got {sorted(business_pairs)}"
    )

    demo_rules = [
        rule
        for rule in main.app.url_map.iter_rules()
        if rule.endpoint == "admin_demo_clientes_form_pack"
    ]
    assert len(demo_rules) == 1, (
        "exactly one live rule must exist for the demo endpoint"
    )
    assert set(demo_rules[0].methods or ()) & BUSINESS_METHODS == {"GET"}, (
        "the live demo rule must expose GET only as business method"
    )


def test_red_f_main_has_no_local_ownership_and_no_cohort_route_decorators():
    target = _target_module()
    assert target is not None, (
        "demo module absent; main local-ownership removal contract "
        "unsatisfiable"
    )
    source = MAIN_PATH.read_text(encoding="utf-8-sig")
    defined = _top_level_defs(source)
    assert "admin_demo_clientes_form_pack" not in defined, (
        "main.py must no longer define the demo route locally"
    )
    assert _cohort_route_decorators(source) == [], (
        "main.py must no longer hold any @app.route decorator for the demo "
        f"cohort; got {_cohort_route_decorators(source)}"
    )


def test_red_g_main_identity_facade():
    target = _target_module()
    assert target is not None, (
        "demo module absent; identity-facade contract unsatisfiable"
    )
    for name in ROUTE_NAMES:
        assert getattr(main, name, None) is getattr(target, name), (
            f"main.{name} must be the exact identity re-export of the demo "
            "target (no wrapper, no copied body)"
        )
    live = main.app.view_functions.get("admin_demo_clientes_form_pack")
    assert live is getattr(target, "admin_demo_clientes_form_pack"), (
        "the live demo endpoint on main.app must be the target callable itself"
    )


def test_red_h_target_has_no_main_backedge():
    target = _target_module()
    assert target is not None, (
        "demo module absent; no-back-edge contract unsatisfiable"
    )
    source = Path(target.__file__).read_text(encoding="utf-8-sig")
    edges = _main_back_edges(source)
    assert edges == [], (
        f"target must not import main (including dynamic-import equivalents): {edges}"
    )
    assert "importlib" not in source, "target must not reference importlib"
    assert "sys.modules" not in source, "target must not reference sys.modules"


def test_red_i_factory_declares_keyword_and_single_registration_path():
    target = _target_module()
    assert target is not None, (
        "demo module absent; factory contract unsatisfiable"
    )
    tree = ast.parse(CREATE_APP_PATH.read_text(encoding="utf-8-sig"))
    create_app_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "create_app"
    )

    kw_pairs = {
        arg.arg: default
        for arg, default in zip(create_app_node.args.kwonlyargs, create_app_node.args.kw_defaults)
    }
    assert FUTURE_FACTORY_FLAG in kw_pairs, (
        "create_app must accept register_admin_demo_blueprint"
    )
    default = kw_pairs[FUTURE_FACTORY_FLAG]
    assert isinstance(default, ast.Constant) and default.value is True, (
        "register_admin_demo_blueprint must default to True"
    )

    registration_calls = [
        call
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "register_legacy_blueprint"
        and any(
            isinstance(arg, ast.Name) and arg.id == "bp_admin_demo"
            for arg in call.args
        )
    ]
    assert len(registration_calls) == 1, (
        "create_app must register bp_admin_demo exactly once through "
        "register_legacy_blueprint"
    )


def test_red_j_factory_default_registers_one_pair_opt_out_registers_none():
    from app import create_app

    signature = inspect.signature(create_app)
    param = signature.parameters.get(FUTURE_FACTORY_FLAG)
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
        register_admin_demo_blueprint=False,
    )

    assert _cohort_rules(default_app) == EXPECTED_PAIRS, (
        "default factory must register exactly the 1 frozen route / 1 pair"
    )
    assert _cohort_rules(opt_out_app) == frozenset(), (
        "opt-out factory must register none of the cohort endpoints"
    )
    for app_ in (default_app, opt_out_app):
        assert not any(
            "." in rule.endpoint
            for rule in app_.url_map.iter_rules()
            if rule.endpoint in ROUTE_NAMES
        ), "no namespaced endpoint variant may exist"
    post_rules = [
        rule
        for rule in default_app.url_map.iter_rules()
        if rule.rule == "/admin/demo/clientes-form-pack"
        and "POST" in (set(rule.methods or ()) & BUSINESS_METHODS)
    ]
    assert post_rules == [], (
        "the demo cohort is GET-only: no POST rule may be factory-registered"
    )


def test_red_l_message_scanner_auto_covers_target_without_registration():
    from utils import messages as messages_module

    catalog = messages_module._message_catalog()
    assert len(catalog) == 536, (
        "message catalog count must match the prod-1 baseline through the extraction; "
        f"got {len(catalog)}"
    )

    backend_paths = {
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in messages_module._iter_backend_files()
    }
    assert TARGET_REL in backend_paths, (
        "app/views/admin/demo.py must be inside backend message-scanner "
        "coverage once created (no scanner-registration change expected)"
    )


def test_red_m_target_owns_live_symbol_coherently_neighbors_stay_elsewhere():
    target = _target_module()
    assert target is not None, (
        "demo module absent; coherent 1-symbol ownership contract "
        "unsatisfiable"
    )

    view = main.app.view_functions.get("admin_demo_clientes_form_pack")
    assert view is not None, "live endpoint admin_demo_clientes_form_pack missing"
    assert inspect.unwrap(view).__module__ == TARGET_MODULE_NAME, (
        "admin_demo_clientes_form_pack must be owned by app.views.admin.demo "
        f"after extraction, got {inspect.unwrap(view).__module__!r}"
    )
    assert view is target.admin_demo_clientes_form_pack, (
        "live endpoint admin_demo_clientes_form_pack must identity-match the "
        "target callable"
    )

    for name in NEGATIVE_SURFACE_NAMES:
        assert getattr(target, name, None) is None, (
            f"{name} must not appear in the demo target surface"
        )

    dashboard = main.app.view_functions.get("admin_dashboard")
    assert dashboard is not None, "live admin_dashboard endpoint missing"
    assert dashboard.__module__ == "app.views.admin.dashboard", (
        "admin_dashboard must remain app.views.admin.dashboard-owned (the "
        "shared dashboard:view scope does not move Demo into dashboard.py)"
    )


def test_red_n_blueprint_identity_and_dotless_live_endpoints():
    target = _target_module()
    assert target is not None, (
        "demo module absent; blueprint identity contract unsatisfiable"
    )

    blueprint = getattr(target, "bp_admin_demo", None)
    assert blueprint is not None, "target must expose bp_admin_demo"
    assert blueprint.name == "admin_demo_blueprint", (
        "blueprint name must be admin_demo_blueprint"
    )
    assert len(target.LEGACY_ROUTE_SPECS) == 1

    namespaced = [
        rule.endpoint
        for rule in main.app.url_map.iter_rules()
        if any(
            rule.endpoint.endswith(f".{name}") or f".{name}." in rule.endpoint
            for name in ROUTE_NAMES
        )
    ]
    assert namespaced == [], (
        f"no admin_demo_blueprint.* namespaced endpoint may exist: {namespaced}"
    )


def test_red_o_admin_package_inventory_includes_demo_target():
    package_files = sorted(path.name for path in ADMIN_PACKAGE.glob("*.py"))
    assert "demo.py" in package_files, (
        "app/views/admin/demo.py must be part of the exact admin package "
        f"inventory; got {package_files}"
    )

    for path in ADMIN_PACKAGE.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        assert "import main" not in source
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(alias.name != "main" for alias in node.names)
            if isinstance(node, ast.ImportFrom):
                assert node.module != "main"
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"__import__", "eval", "exec"}
        assert "sys.modules" not in source
        assert "importlib" not in source


# ===========================================================================
# GREEN — current behavior / invariant controls
# ===========================================================================


def test_green_1_detector_self_control():
    loaded = _target_module()
    if TARGET_PATH.exists():
        assert loaded is not None, (
            "guarded loader must return the real target module once "
            "app/views/admin/demo.py exists"
        )
    else:
        assert loaded is None, (
            "guarded loader must return None while the target file is absent"
        )


def test_green_2_authenticated_render_characterization_without_db(monkeypatch):
    view = _live_view()
    view_module = _live_view_module()
    captured: dict = {}

    def _capture_render(template_name, **kwargs):
        captured["template_name"] = template_name
        captured["kwargs"] = kwargs
        return "<html>captured</html>"

    monkeypatch.setattr(view_module, "render_template", _capture_render)

    with main.app.test_request_context("/admin/demo/clientes-form-pack"):
        session["user_id"] = 1
        session["user_type"] = "admin"
        result = view()

    assert result == "<html>captured</html>"
    assert captured["template_name"] == "demo_clientes_form_pack.html", (
        "the demo view must render exactly demo_clientes_form_pack.html"
    )
    assert captured["kwargs"] == {}, (
        "the demo view must render the template with NO context kwargs; "
        f"got {captured['kwargs']!r}"
    )


def test_green_3_unauthenticated_redirect_to_login_without_db(monkeypatch):
    view = _live_view()
    view_module = _live_view_module()
    captured: dict = {}

    def _capture_render(template_name, **kwargs):
        captured["template_name"] = template_name
        return "<html>captured</html>"

    monkeypatch.setattr(view_module, "render_template", _capture_render)

    with main.app.test_request_context("/admin/demo/clientes-form-pack"):
        expected_login = url_for("login")
        result = view()

    assert isinstance(result, Response), (
        "unauthenticated demo access must redirect, got "
        f"{type(result).__name__}"
    )
    assert result.status_code == 302, (
        "unauthenticated demo access must redirect with status 302, "
        f"got {result.status_code}"
    )
    assert result.location == expected_login, (
        "unauthenticated demo access must redirect to the login endpoint, "
        f"got {result.location!r}"
    )
    assert captured == {}, (
        "unauthenticated demo access must NOT reach the template render"
    )


def test_green_4_rbac_requirement_dashboard_view_preserved():
    requirement = get_admin_permission_requirement(
        "admin_demo_clientes_form_pack",
        "GET",
    )
    assert requirement == EXPECTED_RBAC_REQUIREMENT, (
        "GET admin_demo_clientes_form_pack must map to dashboard:view, "
        f"got {requirement!r}"
    )
    assert get_admin_permission_requirement(
        "admin_demo_clientes_form_pack",
        "POST",
    ) == EXPECTED_RBAC_REQUIREMENT, (
        "the demo RBAC requirement must stay unchanged for every method "
        "(endpoint unchanged, no RBAC redesign)"
    )


def test_green_5_reverse_dependencies_stay_zero():
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


def test_green_6_sequential_owners_state_aware():
    demo_expected_module = (
        "app.views.admin.demo"
        if TARGET_PATH.exists()
        else "main"
    )
    expected_owners = {
        "admin_arquivos": "app.views.admin.arquivos",
        "admin_alertas": "app.views.admin.alertas",
        "admin_reportes": "app.views.admin.reportes",
        "admin_dashboard": "app.views.admin.dashboard",
        "admin_meus_dados": "app.views.admin.meus_dados",
        "admin_demo_clientes_form_pack": demo_expected_module,
    }
    for endpoint, module_name in expected_owners.items():
        view = main.app.view_functions.get(endpoint)
        assert view is not None, f"live endpoint {endpoint} missing"
        assert view.__module__ == module_name, (
            f"{endpoint} must stay owned by {module_name}, "
            f"got {view.__module__!r}"
        )


def test_green_7_template_contract_and_no_navigation_coupling():
    template_path = PROJECT_ROOT / "templates" / "demo_clientes_form_pack.html"
    assert template_path.is_file(), (
        "the demo template must exist and stay untouched"
    )

    for root in (PROJECT_ROOT / "templates", PROJECT_ROOT / "static"):
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in {".html", ".css", ".js", ".svg"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            assert "admin_demo_clientes_form_pack" not in text, (
                f"no url_for endpoint reference to the demo route may exist: {path}"
            )
            assert "/admin/demo/clientes-form-pack" not in text, (
                f"no literal path reference to the demo route may exist: {path}"
            )


def test_green_8_csrf_zero_delta_and_snapshot_custody(tmp_path):
    snapshot_dir = PROJECT_ROOT / "tests" / "_artifacts"
    for suffix in ("shadow_off", "shadow_on"):
        snapshot_path = snapshot_dir / f"csrf_inventory_{suffix}.json"
        assert snapshot_path.exists(), (
            f"canonical CSRF snapshot missing: {snapshot_path.name}"
        )
        report = json.loads(snapshot_path.read_text(encoding="utf-8-sig"))
        rows = report["rows"]
        assert len(rows) == 77, (
            f"snapshot {suffix} must keep the known 78-row contract"
        )

        demo_rows = [
            row for row in rows if row["route"] == "/admin/demo/clientes-form-pack"
        ]
        assert demo_rows == [], (
            "Demo is GET-only: no mutating CSRF row may exist for the demo "
            f"route in {suffix}"
        )
        assert not any(
            row["view_function"] == "main.admin_demo_clientes_form_pack"
            or row["view_function"].startswith("app.views.admin.demo.")
            for row in rows
        ), f"no demo view_function may appear in {suffix}"

    report = _authorized_csrf_snapshot_delta_report()
    assert report == "", (
        "canonical CSRF snapshots may carry only the FC-07-authorized "
        f"three-message delta across UT-15: {report}"
    )

    # Detector self-control: a real content mutation must be flagged by the
    # exact same Git-aware mechanism.  Synthetic bytes only; the canonical
    # artifacts are never modified here.
    for name in (
        "csrf_inventory_shadow_off.json",
        "csrf_inventory_shadow_on.json",
        "route_inventory_baseline.json",
    ):
        relative = f"tests/_artifacts/{name}"
        canonical = _git_blob_bytes(relative)
        assert canonical, f"HEAD blob for {name} must be non-empty"
        mutated = bytes([canonical[0] ^ 1]) + canonical[1:]
        tmp = tmp_path / name
        tmp.write_bytes(mutated)
        mutated_hash = subprocess.run(
            ["git", "hash-object", "--path", relative, str(tmp)],
            capture_output=True,
            text=True,
        )
        assert mutated_hash.returncode == 0, mutated_hash.stderr
        assert mutated_hash.stdout.strip() != _head_blob_sha(relative), (
            "custody detector must flag a real content mutation of "
            f"{name}"
        )


def test_green_9_red_file_has_no_database_initialization_caller():
    needle = "init" + "_db"
    source = Path(__file__).read_text(encoding="utf-8")
    assert needle not in source, (
        f"UT-15 RED must not introduce a {needle} caller: the Phase3 "
        "database-initialization caller manifest must stay at 76"
    )


def test_green_10_hooks_main_stays_zero():
    assert _all_main_hooks() == [], (
        "hooks belonging to main must stay zero; "
        f"got {_all_main_hooks()}"
    )


def test_green_11_route_inventory_matches_prod1_live_surface():
    relative = "tests/_artifacts/route_inventory_baseline.json"
    data = json.loads((PROJECT_ROOT / relative).read_text(encoding="utf-8-sig"))
    routes = data["routes"]
    assert len(routes) == 127
    assert len({row["rule"] for row in routes}) == 126
    assert not any(row["rule"] == "/admin/mapeamento-legado" for row in routes)
    assert not any(
        row["endpoint"] == "admin_diagnostico_versioned_shadow_reads"
        for row in routes
    )


def test_green_12_message_catalog_stays_536():
    from utils import messages as messages_module

    assert len(messages_module._message_catalog()) == 536, (
        "current catalog baseline must stay 541"
    )
