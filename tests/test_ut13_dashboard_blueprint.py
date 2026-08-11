"""UT-13 RED — Dashboard cohort extraction contract.

Future canonical owner: ``app/views/admin/dashboard.py``.

Authoritative relocated-symbol manifest (EXACTLY 10 symbols):
- 1 route (LegacyRouteSpec-preserving): ``admin_dashboard``;
- 9 cohort-exclusive helpers:
  ``_build_admin_dashboard_turma_cards``, ``periodo_corrente``,
  ``_format_dashboard_hours``, ``_format_dashboard_average``,
  ``_format_dashboard_days``, ``_calculate_pending_response_metrics``,
  ``get_admin_new_request_alert``, ``mark_admin_new_request_alert_seen``,
  ``_admin_request_alert_kind``.

There is NO cohort-local constant in the frozen target (only the standard
wiring assignments ``bp_admin_dashboard`` and ``LEGACY_ROUTE_SPECS``).

Explicitly OUTSIDE UT-13 (hard boundary, both states):
``admin_demo_clientes_form_pack`` stays main-owned; ``admin_meus_dados``
stayed main-owned throughout UT-13 and is the UT-14 cohort (the meus_dados
clauses in this file are UT-14 seams, state-aware on the real
``app/views/admin/meus_dados.py`` target availability);
``UPPER_CODE_RE``, ``proximo_numero_turma`` and
``validar_integridade_versionamento_atividades`` also stay main-owned.

This file contains exactly 30 collected tests:
- ``test_red_a``..``test_red_j`` and ``test_red_l``..``test_red_o`` (14) are
  FUTURE ARCHITECTURAL CONTRACT assertions; while the target module is absent
  they fail with plain AssertionError only (no ImportError /
  ModuleNotFoundError / AttributeError / TypeError / fixture or collection
  error);
- ``test_green_1``..``test_green_16`` characterize CURRENT behavior and
  invariant controls that implementation is forbidden to change; every GREEN
  must remain valid after legitimate extraction.

There is deliberately NO ``test_red_k``: the Dashboard cohort contributes zero
mutating CSRF inventory rows, so CSRF is not an owner-delta RED class (the
zero-delta partition is a GREEN control, ``test_green_14``); no artificial
failing CSRF assertion is created.

Collection-safety rule: the future module is imported only through a guarded
loader after its file existence is established; sentinels are used instead of
exception-based RED signals.  No parametrization changes the collected count.

State-aware Dashboard principle (replaces the historical "Dashboard stays in
main" protections): the legitimate pre-target state is main-owned; the
post-target state is exactly target-owned for all 10 moved symbols plus a
main identity facade 10/10.  Mixed moved ownership must fail.  Expected
ownership is derived from REAL target availability (file existence), never
from the assertion under test and never from a snapshot.

CSRF owner contract: the Dashboard cohort contributes ZERO mutating rows to
the canonical CSRF inventories (``/admin/dashboard`` is GET-only).  The
snapshots are read-only here; no regeneration is expected and the projected
historical cumulative totals remain 35 / 43 / 48.  CSRF is therefore NOT a
RED ownership-delta class; the zero-delta partition is a GREEN control.

Historical seam authority (Phase 3 only, NOT executed here): the supervisor
pre-authorized narrow UT-13 implementation-time cochanges in EXACTLY
tests/test_ut12_reportes_blueprint.py,
tests/test_phase4_alunos_turmas_cursos_blueprint.py,
tests/test_phase4_alunos_turmas_cursos_shared_owners.py,
tests/test_phase4_requisicoes_blueprint.py,
tests/test_phase4_arquivos_alertas_shared_owners.py and
tests/test_phase4_configuracoes_blueprint.py — classified
TEST_CONTRACT_SEAM / LEGITIMATE_UT13_COCHANGE (retire only stale
Dashboard-main residency expectations; never weaken Reportes/Alertas/Arquivos
protections and never reopen UT-10/UT-11 files).

Shared canonical owners are NOT moved into the target: ``list_active_admin_alertas``
(app.admin_alerts), ``ensure_requisicao_alert_receipts_table``
(app.db_maintenance), ``ensure_turmas_matriz_schema`` (app.db),
``get_effective_matriz_for_turma`` (app.matrix_scope),
``DEFAULT_CURSO_TOTAL_HORAS_AAC/AEU`` (app.academics),
``auto_indefer_devolvidas`` (app.requisitions),
``get_response_time_settings`` (app.settings),
``_parse_optional_processing_datetime`` (app.requisition_policy),
``canonicalize_access_level``/``default_access_level_for_user_type``/
``admin_required`` (app.auth) and ``resolve_user_message`` (utils.messages)
stay where they are; the move is MOVE, DO NOT CHANGE — no C4/schema cleanup,
no migration v4, SCHEMA_VERSION stays 3, request-path side effects
(conn.commit() in GET, g._adm_dash_metrics cache, bootstrap-on-read) are
preserved.
"""

from __future__ import annotations

import ast
import datetime
import inspect
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from app.auth import get_admin_permission_requirement

import main


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TARGET_PATH = PROJECT_ROOT / "app" / "views" / "admin" / "dashboard.py"
TARGET_REL = "app/views/admin/dashboard.py"
TARGET_MODULE_NAME = "app.views.admin.dashboard"
MEUS_DADOS_TARGET_PATH = PROJECT_ROOT / "app" / "views" / "admin" / "meus_dados.py"
DEMO_TARGET_PATH = PROJECT_ROOT / "app" / "views" / "admin" / "demo.py"
MAIN_PATH = PROJECT_ROOT / "main.py"
CREATE_APP_PATH = PROJECT_ROOT / "app" / "__init__.py"
ADMIN_PACKAGE = PROJECT_ROOT / "app" / "views" / "admin"
BUSINESS_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}

ROUTE_NAMES = ("admin_dashboard",)

HELPER_NAMES = (
    "_build_admin_dashboard_turma_cards",
    "periodo_corrente",
    "_format_dashboard_hours",
    "_format_dashboard_average",
    "_format_dashboard_days",
    "_calculate_pending_response_metrics",
    "get_admin_new_request_alert",
    "mark_admin_new_request_alert_seen",
    "_admin_request_alert_kind",
)

MOVED_SYMBOLS = ROUTE_NAMES + HELPER_NAMES

# UT-14 seam: admin_meus_dados left the Dashboard neighbor set (it is the
# UT-14 cohort, governed by tests/test_ut14_meus_dados_blueprint.py);
# admin_demo_clientes_form_pack remains the hard-boundary neighbor.
NEIGHBOR_ROUTE_NAMES = (
    "admin_demo_clientes_form_pack",
)

ROUTE_MATRIX = (
    ("/admin/dashboard", "admin_dashboard", ("GET",)),
)

EXPECTED_PAIRS = frozenset(
    (rule, endpoint, tuple(sorted(methods))) for rule, endpoint, methods in ROUTE_MATRIX
)

RBAC_MATRIX = {
    "admin_dashboard": ("dashboard", "view"),
    "admin_demo_clientes_form_pack": ("dashboard", "view"),
    "admin_meus_dados": ("meus_dados", "view"),
}

NEIGHBOR_RBAC_POST = {
    "admin_meus_dados": ("meus_dados", "edit"),
}

COHORT_RULE_PREFIXES = ("/admin/dashboard",)

DASHBOARD_RULE = "/admin/dashboard"

CARD_KEY_SET = frozenset(
    {
        "id",
        "label",
        "total_alunos",
        "total_alunos_ativos",
        "periodo_atual_label",
        "aac_hours_fmt",
        "aeu_hours_fmt",
        "ch_total_fmt",
        "aac_applicable",
        "aeu_applicable",
        "aac_pct",
        "aeu_pct",
        "total_applicable",
        "total_pct",
        "attainment_buckets",
        "attainment_avg_pct_label",
        "attainment_donut_gradient",
        "pendentes",
    }
)

SUMMARY_KEY_SET = frozenset(
    {
        "total_turmas",
        "total_turmas_ativas",
        "turmas_com_aac",
        "turmas_com_aeu",
        "media_alunos_por_turma_fmt",
    }
)

TOTAL_GERAL_KEY_SET = frozenset(
    {
        "label",
        "total_alunos",
        "aac_applicable",
        "aeu_applicable",
        "aac_pct",
        "aeu_pct",
        "ch_total_fmt",
        "pendentes",
    }
)

# Existing factory blueprint flags (pre-UT13), used by the state-aware
# neighbor-safety GREEN control.
EXISTING_FACTORY_FLAGS = (
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
)

FUTURE_FACTORY_FLAG = "register_admin_dashboard_blueprint"


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


def _top_level_import_sources(source: str) -> set[str]:
    tree = ast.parse(source)
    sources: set[str] = set()
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


def _make_temp_conn(tmp_path) -> sqlite3.Connection:
    """Minimal schema mirroring the columns the Dashboard closure queries."""
    conn = sqlite3.connect(tmp_path / "dashboard_behavior.db")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE turmas ("
        "id INTEGER PRIMARY KEY, nome TEXT, codigo TEXT, status TEXT, "
        "curso_id INTEGER, matriz_id INTEGER, ano_inicio INTEGER, "
        "semestre_inicio INTEGER)"
    )
    conn.execute(
        "CREATE TABLE alunos (id INTEGER PRIMARY KEY, turma_id INTEGER, status TEXT)"
    )
    conn.execute(
        "CREATE TABLE atividades (id INTEGER PRIMARY KEY, tipo_atividade TEXT)"
    )
    conn.execute(
        "CREATE TABLE requisicoes ("
        "id INTEGER PRIMARY KEY, aluno_id INTEGER, atividade_id INTEGER, "
        "status TEXT, data_solicitacao TEXT, horas_solicitadas REAL, "
        "horas_deferidas REAL)"
    )
    conn.commit()
    return conn


# ===========================================================================
# RED — future architectural contract (A..O)
# ===========================================================================


def test_red_a_target_module_file_exists():
    assert TARGET_PATH.exists(), (
        "app/views/admin/dashboard.py does not exist yet; UT-13 must create it"
    )


def test_red_b_target_owns_exact_ten_symbols_no_constant():
    target = _target_module()
    assert target is not None, (
        "dashboard module absent; 10-symbol ownership contract unsatisfiable"
    )

    source = Path(target.__file__).read_text(encoding="utf-8-sig")
    top_level = _top_level_defs(source)
    assigned = _top_level_assignments(source)

    assert top_level == set(MOVED_SYMBOLS), (
        f"target top-level functions must be exactly the 10 moved callables; "
        f"missing={sorted(set(MOVED_SYMBOLS) - top_level)} "
        f"extra={sorted(top_level - set(MOVED_SYMBOLS))}"
    )
    assert len(MOVED_SYMBOLS) == 10, (
        f"moved-symbol target must be exactly 10, got {len(MOVED_SYMBOLS)}"
    )
    assert assigned == {"bp_admin_dashboard", "LEGACY_ROUTE_SPECS"}, (
        "target must expose exactly the standard blueprint/spec wiring as "
        f"top-level assignments; no cohort-local constant admitted; got {assigned}"
    )
    for name in MOVED_SYMBOLS:
        obj = getattr(target, name, None)
        assert obj is not None, f"target.{name} missing"
        if callable(obj):
            assert inspect.unwrap(obj).__module__ == TARGET_MODULE_NAME, (
                f"target.{name} must be defined in app.views.admin.dashboard, "
                f"got {inspect.unwrap(obj).__module__!r}"
            )


def test_red_c_one_route_admin_decorated_no_route_decorators():
    target = _target_module()
    assert target is not None, "dashboard module absent; route-ownership contract unsatisfiable"

    source = Path(target.__file__).read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert "admin_dashboard" in functions
    decorators = {ast.unparse(item) for item in functions["admin_dashboard"].decorator_list}
    assert decorators == {"admin_required"}, (
        f"route admin_dashboard decorators must be exactly {{admin_required}}, got {decorators}"
    )
    assert _route_decorator_calls(source) == [], (
        "target must not contain any @app.route / @bp.route decorators; "
        "routes register through LegacyRouteSpec"
    )


def test_red_d_exactly_one_spec_one_pair_frozen_matrix():
    target = _target_module()
    assert target is not None, "dashboard module absent; LegacyRouteSpec contract unsatisfiable"

    specs = getattr(target, "LEGACY_ROUTE_SPECS", None)
    assert isinstance(specs, tuple), "target must expose an immutable LEGACY_ROUTE_SPECS tuple"
    assert len(specs) == 1, f"expected 1 LegacyRouteSpec, got {len(specs)}"

    encoded = {(spec.rule, spec.endpoint, spec.methods) for spec in specs}
    assert encoded == EXPECTED_PAIRS, (
        f"spec set mismatch: missing={sorted(EXPECTED_PAIRS - encoded)} "
        f"extra={sorted(encoded - EXPECTED_PAIRS)}"
    )
    assert sum(len(spec.methods) for spec in specs) == 1, (
        "specs must represent exactly 1 endpoint/method pair; HEAD must not be "
        "absorbed as a separate pair"
    )
    assert {spec.view_func for spec in specs} == {
        getattr(target, name) for name in ROUTE_NAMES
    }, "every spec must reference the target-owned route function"
    assert all("." not in spec.endpoint for spec in specs), (
        "no namespaced endpoint allowed"
    )


def test_red_e_spec_endpoint_resolves_dashboard_view():
    target = _target_module()
    assert target is not None, "dashboard module absent; RBAC-from-specs contract unsatisfiable"

    specs = getattr(target, "LEGACY_ROUTE_SPECS", None)
    assert isinstance(specs, tuple) and len(specs) == 1, (
        "RBAC derivation requires the frozen single LegacyRouteSpec"
    )

    for spec in specs:
        for method in spec.methods:
            requirement = get_admin_permission_requirement(spec.endpoint, method)
            assert requirement is not None, (
                f"{spec.endpoint} {method} must resolve a requirement"
            )
            assert requirement == ("dashboard", "view"), (
                f"{spec.endpoint} must be governed by (dashboard, view), got {requirement}"
            )
    assert get_admin_permission_requirement("admin_dashboard", "GET") == ("dashboard", "view"), (
        "admin_dashboard GET must resolve to (dashboard, view)"
    )


def test_red_f_main_has_no_local_ownership_and_no_cohort_route_decorators():
    source = MAIN_PATH.read_text(encoding="utf-8-sig")
    defined = _top_level_defs(source)

    assert not (set(MOVED_SYMBOLS) & defined), (
        "main.py must no longer locally define moved callables: "
        f"{sorted(set(MOVED_SYMBOLS) & defined)}"
    )
    assert _cohort_route_decorators(source) == [], (
        "main.py must no longer register /admin/dashboard via @app.route"
    )


def test_red_g_main_facade_ten_of_ten_identity_no_wrappers():
    target = _target_module()
    assert target is not None, "dashboard module absent; main compatibility contract unsatisfiable"

    for name in MOVED_SYMBOLS:
        assert hasattr(main, name), f"main.{name} missing from the compatibility facade"
        assert getattr(main, name) is getattr(target, name), (
            f"main.{name} must be the identical object exported by dashboard "
            "(identity re-export, no wrapper, no copied implementation)"
        )


def test_red_h_target_has_no_main_backedge():
    target = _target_module()
    assert target is not None, "dashboard module absent; no-back-edge contract unsatisfiable"

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
    assert FUTURE_FACTORY_FLAG in kw_pairs, (
        "create_app must accept register_admin_dashboard_blueprint"
    )
    default = kw_pairs[FUTURE_FACTORY_FLAG]
    assert isinstance(default, ast.Constant) and default.value is True, (
        "register_admin_dashboard_blueprint must default to True"
    )

    registration_calls = [
        call
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "register_legacy_blueprint"
        and any(
            isinstance(arg, ast.Name) and arg.id == "bp_admin_dashboard"
            for arg in call.args
        )
    ]
    assert len(registration_calls) == 1, (
        "create_app must register bp_admin_dashboard exactly once through "
        "register_legacy_blueprint"
    )


def test_red_j_factory_default_registers_one_opt_out_registers_none():
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
        register_admin_dashboard_blueprint=False,
    )

    default_rules = {
        (rule.rule, rule.endpoint) for rule in default_app.url_map.iter_rules()
    }
    assert _cohort_rules(default_app) == EXPECTED_PAIRS, (
        "default factory must register exactly the 1 frozen route / 1 pair"
    )
    assert _cohort_rules(opt_out_app) == frozenset(), (
        "opt-out factory must register none of the 1 cohort endpoints"
    )
    assert not any(
        "." in rule.endpoint
        for rule in default_app.url_map.iter_rules()
        if rule.endpoint in ROUTE_NAMES
    ), "no namespaced endpoint variant may exist"
    assert len(default_rules) > 0, "default factory sanity check"

    for app_ in (default_app, opt_out_app):
        live_endpoints = {rule.endpoint for rule in app_.url_map.iter_rules()}
        assert "admin_reportes" in live_endpoints, (
            "factory opt-out must never remove the Reportes cohort"
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
        "app/views/admin/dashboard.py must be inside backend message-scanner "
        "coverage once created (no scanner-registration change expected)"
    )


def test_red_m_target_owns_all_ten_live_symbols_coherently():
    target = _target_module()
    assert target is not None, (
        "dashboard module absent; coherent 10-symbol ownership contract unsatisfiable"
    )

    for name in HELPER_NAMES:
        obj = getattr(target, name, None)
        assert obj is not None, f"target.{name} missing"
        assert inspect.unwrap(obj).__module__ == TARGET_MODULE_NAME, (
            f"target.{name} must be defined in app.views.admin.dashboard, "
            f"got {inspect.unwrap(obj).__module__!r}"
        )

    view = main.app.view_functions.get("admin_dashboard")
    assert view is not None, "live endpoint admin_dashboard missing"
    assert inspect.unwrap(view).__module__ == TARGET_MODULE_NAME, (
        "admin_dashboard must be owned by app.views.admin.dashboard after "
        f"extraction, got {inspect.unwrap(view).__module__!r}"
    )
    assert view is target.admin_dashboard, (
        "live endpoint admin_dashboard must identity-match the target callable"
    )

    # Mixed ownership of the 10-symbol cohort is rejected by construction:
    # every moved symbol above must be target-owned.  The neighbor routes must
    # NOT appear on the future Dashboard target surface.
    for name in NEIGHBOR_ROUTE_NAMES:
        assert getattr(target, name, None) is None, (
            f"{name} must not appear in the Dashboard target moved-symbol surface"
        )


def test_red_n_blueprint_identity_and_dotless_live_endpoints():
    target = _target_module()
    assert target is not None, (
        "dashboard module absent; blueprint identity contract unsatisfiable"
    )

    blueprint = getattr(target, "bp_admin_dashboard", None)
    assert blueprint is not None, "target must expose bp_admin_dashboard"
    assert blueprint.name == "admin_dashboard_blueprint", (
        f"blueprint name must be admin_dashboard_blueprint, got {blueprint.name!r}"
    )

    live = {
        rule.endpoint: main.app.view_functions[rule.endpoint]
        for rule in main.app.url_map.iter_rules()
        if rule.endpoint in ROUTE_NAMES
    }
    assert len(live) == 1, "exactly one live Dashboard endpoint required"
    for name in ROUTE_NAMES:
        assert live[name] is getattr(target, name), (
            f"live endpoint {name} must identity-match the target callable"
        )

    namespaced = [
        endpoint
        for endpoint in main.app.view_functions
        if endpoint.startswith("admin_dashboard_blueprint.")
    ]
    assert namespaced == [], (
        f"no admin_dashboard_blueprint.* namespaced endpoint may exist: {namespaced}"
    )


def test_red_o_admin_package_inventory_includes_dashboard_target():
    package_files = sorted(path.name for path in ADMIN_PACKAGE.glob("*.py"))
    assert "dashboard.py" in package_files, (
        "app/views/admin/dashboard.py must be part of the exact admin package "
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
            "app/views/admin/dashboard.py exists"
        )
        assert loaded.__name__ == TARGET_MODULE_NAME, (
            "guarded loader must resolve the real imported target module, "
            f"got {loaded!r}"
        )
        assert not hasattr(loaded, "_ut13_synthetic_future_production"), (
            "guarded loader must never expose a synthesized fake module"
        )
    else:
        assert loaded is None, (
            "guarded loader must return None while app/views/admin/dashboard.py "
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


def test_green_2_live_route_matrix_exactly_one_route_one_pair():
    rules = [
        rule
        for rule in main.app.url_map.iter_rules()
        if rule.endpoint in ROUTE_NAMES
    ]
    assert len(rules) == 1, f"expected 1 live cohort rule, got {len(rules)}"
    assert _cohort_rules(main.app) == EXPECTED_PAIRS, (
        "live url_map must match the frozen 1-pair matrix; HEAD must not be "
        "absorbed as a separate pair"
    )
    assert all(rule.endpoint == "admin_dashboard" for rule in rules), (
        "live Dashboard endpoint must be the dotless legacy name admin_dashboard"
    )


def test_green_3_rbac_exact_matches_and_live_endpoint_set():
    for endpoint, (resource, scope) in RBAC_MATRIX.items():
        method = "GET"
        assert get_admin_permission_requirement(endpoint, method) == (resource, scope), (
            f"{endpoint} {method} must resolve to ({resource}, {scope})"
        )
    for endpoint, (resource, scope) in NEIGHBOR_RBAC_POST.items():
        assert get_admin_permission_requirement(endpoint, "POST") == (resource, scope), (
            f"{endpoint} POST must resolve to ({resource}, {scope})"
        )

    live_endpoints = {
        endpoint
        for endpoint in main.app.view_functions
        if endpoint.startswith("admin_dashboard")
    }
    assert live_endpoints == set(ROUTE_NAMES), (
        "exactly the frozen admin_dashboard endpoint must be live; "
        f"no unrelated endpoint admitted; got {sorted(live_endpoints)}"
    )


def test_green_4_global_invariants_routes_endpoints_rbac_hooks():
    rules = list(main.app.url_map.iter_rules())
    assert len(rules) == 131, f"routes must stay 131, got {len(rules)}"
    assert len(main.app.view_functions) == 130, (
        f"distinct endpoints must stay 130, got {len(main.app.view_functions)}"
    )

    unmapped = [
        (rule.rule, method)
        for rule in rules
        if rule.rule.startswith("/admin")
        for method in (set(rule.methods or ()) & BUSINESS_METHODS)
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
    assert "app/views/admin/alertas.py" in backend_paths, (
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


def test_green_8_neighbor_routes_hard_boundary_main_owned():
    for name in NEIGHBOR_ROUTE_NAMES:
        view = main.app.view_functions.get(name)
        assert view is not None, f"live neighbor endpoint {name} missing"
        # UT-15 seam (TEST_CONTRACT_SEAM / LEGITIMATE_UT15_COCHANGE):
        # Demo is never owned by the Dashboard module.  Its owner follows the
        # real app/views/admin/demo.py target availability: main pre-target,
        # app.views.admin.demo post-target (main keeps the identity facade).
        expected_module = (
            "app.views.admin.demo"
            if name == "admin_demo_clientes_form_pack" and DEMO_TARGET_PATH.exists()
            else "main"
        )
        assert view.__module__ == expected_module, (
            f"{name} must be owned by {expected_module!r} (UT-13 hard "
            f"boundary: never the Dashboard module), got {view.__module__!r}"
        )


def test_green_9_extracted_cohorts_and_canonical_dependency_owners():
    from app import (
        academics,
        admin_alerts,
        auth,
        db,
        db_maintenance,
        matrix_scope,
        requisition_policy,
        requisitions,
        settings,
    )
    from utils import messages

    assert main.list_active_admin_alertas is admin_alerts.list_active_admin_alertas, (
        "list_active_admin_alertas must stay owned by app.admin_alerts"
    )
    assert (
        main.ensure_requisicao_alert_receipts_table
        is db_maintenance.ensure_requisicao_alert_receipts_table
    ), "ensure_requisicao_alert_receipts_table must stay owned by app.db_maintenance"
    assert main.ensure_turmas_matriz_schema is db.ensure_turmas_matriz_schema, (
        "ensure_turmas_matriz_schema must stay owned by app.db"
    )
    assert main.get_effective_matriz_for_turma is matrix_scope.get_effective_matriz_for_turma, (
        "get_effective_matriz_for_turma must stay owned by app.matrix_scope"
    )
    assert main.DEFAULT_CURSO_TOTAL_HORAS_AAC == academics.DEFAULT_CURSO_TOTAL_HORAS_AAC, (
        "DEFAULT_CURSO_TOTAL_HORAS_AAC must stay owned by app.academics"
    )
    assert main.DEFAULT_CURSO_TOTAL_HORAS_AEU == academics.DEFAULT_CURSO_TOTAL_HORAS_AEU, (
        "DEFAULT_CURSO_TOTAL_HORAS_AEU must stay owned by app.academics"
    )
    assert main.auto_indefer_devolvidas is requisitions.auto_indefer_devolvidas, (
        "auto_indefer_devolvidas must stay owned by app.requisitions"
    )
    assert main.get_response_time_settings is settings.get_response_time_settings, (
        "get_response_time_settings must stay owned by app.settings"
    )
    assert (
        main._parse_optional_processing_datetime
        is requisition_policy._parse_optional_processing_datetime
    ), "_parse_optional_processing_datetime must stay owned by app.requisition_policy"
    assert main.canonicalize_access_level is auth.canonicalize_access_level, (
        "canonicalize_access_level must stay owned by app.auth"
    )
    assert (
        main.default_access_level_for_user_type
        is auth.default_access_level_for_user_type
    ), "default_access_level_for_user_type must stay owned by app.auth"
    assert auth.admin_required.__module__ == "app.auth", (
        "admin_required must stay owned by app.auth"
    )
    assert main.resolve_user_message is messages.resolve_user_message, (
        "resolve_user_message must stay owned by utils.messages"
    )

    reportes_routes = (
        "admin_reportes",
        "admin_reportes_atualizar_status",
        "admin_reportes_deletar",
    )
    for name in reportes_routes:
        view = main.app.view_functions.get(name)
        assert view is not None, f"live Reportes endpoint {name} missing"
        assert view.__module__ == "app.views.admin.reportes", (
            f"{name} must remain owned by app.views.admin.reportes, "
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
        assert view is not None, f"live Alertas endpoint {name} missing"
        assert view.__module__ == "app.views.admin.alertas", (
            f"{name} must remain owned by app.views.admin.alertas, "
            f"got {view.__module__!r}"
        )

    arquivos_routes = (
        "admin_arquivos",
        "admin_adicionar_arquivo",
        "admin_editar_arquivo",
        "admin_visualizar_arquivo",
        "admin_deletar_arquivo",
    )
    for name in arquivos_routes:
        view = main.app.view_functions.get(name)
        assert view is not None, f"live Arquivos endpoint {name} missing"
        assert view.__module__ == "app.views.admin.arquivos", (
            f"{name} must remain owned by app.views.admin.arquivos, "
            f"got {view.__module__!r}"
        )


def test_green_10_dashboard_pure_helper_behavior_characterization():
    assert main.periodo_corrente(None, 1) == 1, (
        "periodo_corrente must return 1 when ano_inicio is missing"
    )
    assert main.periodo_corrente(2020, None) == 1, (
        "periodo_corrente must return 1 when semestre_inicio is missing"
    )
    assert main.periodo_corrente(2026, 1, ref=datetime.date(2026, 1, 1)) == 1
    assert main.periodo_corrente(2026, 2, ref=datetime.date(2026, 1, 1)) == 1
    assert main.periodo_corrente(2025, 2, ref=datetime.date(2026, 8, 10)) == 3
    assert main.periodo_corrente(2024, 1, ref=datetime.date(2026, 8, 10)) == 6

    assert main._format_dashboard_hours(12.0) == "12"
    assert main._format_dashboard_hours(12.5) == "12.5"
    assert main._format_dashboard_hours(123.456) == "123.5"
    assert main._format_dashboard_hours(0) == "0"
    assert main._format_dashboard_hours(None) == "0"

    assert main._format_dashboard_average(12.34) == "12,3"
    assert main._format_dashboard_average(7.0) == "7,0"
    assert main._format_dashboard_average(0) == "0,0"
    assert main._format_dashboard_average(None) == "0,0"

    assert main._format_dashboard_days(7.0) == "7"
    assert main._format_dashboard_days(7.56) == "7,6"
    assert main._format_dashboard_days(None) == "0"
    assert main._format_dashboard_days(0) == "0"


def test_green_11_alert_kind_request_alert_and_receipts_behavior(tmp_path):
    from app.db_maintenance import ensure_requisicao_alert_receipts_table

    conn = _make_temp_conn(tmp_path)
    ensure_requisicao_alert_receipts_table(conn)
    conn.execute(
        "INSERT INTO requisicoes (id, aluno_id, status, data_solicitacao) "
        "VALUES (1, 10, 'Pendente', '2026-01-01 10:00:00')"
    )
    conn.execute(
        "INSERT INTO requisicoes (id, aluno_id, status, data_solicitacao) "
        "VALUES (2, 10, 'Pendente', '2026-01-01 10:00:00')"
    )
    conn.execute(
        "INSERT INTO requisicoes (id, aluno_id, status, data_solicitacao) "
        "VALUES (3, 10, 'Deferida', '2026-01-02 10:00:00')"
    )
    conn.commit()

    assert main._admin_request_alert_kind("admin_total") == "admin_new_request"
    assert main._admin_request_alert_kind("administrativo") == "coordinator_new_request"
    assert main._admin_request_alert_kind("consultivo") is None
    assert main._admin_request_alert_kind(None) == "admin_new_request", (
        "fallback canonicalization of an empty level must resolve to the admin "
        "default (admin_total) -> admin_new_request"
    )

    with main.app.test_request_context("/admin/dashboard"):
        assert main.get_admin_new_request_alert(conn, None, "admin_total") is None, (
            "request alert must be None without a usuario_id"
        )
        assert main.get_admin_new_request_alert(conn, 1, "consultivo") is None, (
            "request alert must be None when no alert kind resolves"
        )

        alert = main.get_admin_new_request_alert(conn, 1, "admin_total")
        assert alert is not None, "pending un-seen requisitions must surface an alert"
        assert alert["requisicao_ids"] == [2, 1], (
            "pending ids must come ordered by data_solicitacao DESC, id DESC"
        )
        assert alert["alerta"]["mensagem"] == "Há novas solicitações aguardando análise."
        assert alert["alerta"]["bg_color"] == "#fef4c0"
        assert alert["alerta"]["border_color"] == "#c9a227"
        assert alert["alerta"]["href"] == "/admin/requisicoes"

        main.mark_admin_new_request_alert_seen(conn, [2, 1], 1, "admin_total")
        assert main.get_admin_new_request_alert(conn, 1, "admin_total") is None, (
            "after receipts are written the alert must disappear"
        )
        main.mark_admin_new_request_alert_seen(conn, [2, 1], 1, "admin_total")
        receipt_rows = conn.execute(
            "SELECT * FROM requisicao_alerta_receipts"
        ).fetchall()
        assert len(receipt_rows) == 2, (
            "INSERT OR IGNORE receipts must stay idempotent"
        )
        assert all(row["usuario_id"] == 1 for row in receipt_rows)
        assert all(row["alert_kind"] == "admin_new_request" for row in receipt_rows)
        assert all(row["seen_at"] for row in receipt_rows)

        coordinator_alert = main.get_admin_new_request_alert(conn, 1, "administrativo")
        assert coordinator_alert is not None, (
            "administrativo receipts are namespaced by a distinct alert_kind"
        )
        assert coordinator_alert["requisicao_ids"] == [2, 1]

        assert main.get_admin_new_request_alert(conn, 1, "whatever-nonexistent") is None, (
            "an unknown level falls back to the admin default alert kind whose "
            "receipts were already written"
        )
        conn.close()


def test_green_12_pending_response_metrics_behavior(tmp_path):
    conn = _make_temp_conn(tmp_path)

    avg, overdue = main._calculate_pending_response_metrics(conn, goal_days=30)
    assert (avg, overdue) == (0.0, 0), (
        "no pending rows must produce (0.0, 0)"
    )

    conn.execute(
        "INSERT INTO requisicoes (id, status, data_solicitacao) "
        "VALUES (1, 'Pendente', '2020-01-01 10:00:00')"
    )
    conn.execute(
        "INSERT INTO requisicoes (id, status, data_solicitacao) "
        "VALUES (2, 'Pendente', '2020-01-01 10:00:00')"
    )
    conn.commit()

    avg, overdue = main._calculate_pending_response_metrics(conn, goal_days=30)
    assert overdue == 2, "both old pending rows must count as overdue"
    assert avg > 30.0, "average age of the old rows must exceed the 30-day goal"

    _, overdue_far = main._calculate_pending_response_metrics(conn, goal_days=365000)
    assert overdue_far == 0, "a sufficiently high goal must clear overdue count"

    avg_reset, _ = main._calculate_pending_response_metrics(
        conn, goal_days=30, reset_at="2024-01-01"
    )
    assert avg_reset < avg, (
        "reset_at must shift the effective start for older requests"
    )

    avg_garbage, _ = main._calculate_pending_response_metrics(
        conn, goal_days=30, reset_at="not-a-date"
    )
    assert avg_garbage == pytest.approx(avg, rel=1e-9), (
        "an unparseable reset_at must behave exactly like no reset_at"
    )
    conn.close()


def test_green_13_turma_cards_behavior(tmp_path):
    conn = _make_temp_conn(tmp_path)

    cards, total_geral, summary = main._build_admin_dashboard_turma_cards(conn)
    assert cards == []
    assert total_geral is None
    assert set(summary) == SUMMARY_KEY_SET
    assert summary == {
        "total_turmas": 0,
        "total_turmas_ativas": 0,
        "turmas_com_aac": 0,
        "turmas_com_aeu": 0,
        "media_alunos_por_turma_fmt": "0,0",
    }

    conn.execute(
        "INSERT INTO turmas (id, nome, codigo, status, ano_inicio, semestre_inicio) "
        "VALUES (1, 'Turma A', 'TUR-A', 'Ativa', 2024, 1)"
    )
    conn.execute(
        "INSERT INTO alunos (id, turma_id, status) VALUES (1, 1, 'Ativo')"
    )
    conn.execute(
        "INSERT INTO atividades (id, tipo_atividade) "
        "VALUES (1, 'Acadêmica Complementar')"
    )
    conn.execute(
        "INSERT INTO requisicoes (id, aluno_id, atividade_id, status, horas_deferidas) "
        "VALUES (1, 1, 1, 'Pendente', NULL)"
    )
    conn.execute(
        "INSERT INTO requisicoes (id, aluno_id, atividade_id, status, horas_deferidas) "
        "VALUES (2, 1, 1, 'Deferida', 40)"
    )
    conn.commit()

    cards, total_geral, summary = main._build_admin_dashboard_turma_cards(conn)
    assert len(cards) == 1
    card = cards[0]
    assert set(card) == CARD_KEY_SET, (
        "turma card must expose exactly the frozen 18-key shape"
    )
    assert card["label"] == "TUR-A"
    assert card["total_alunos"] == 1
    assert card["total_alunos_ativos"] == 1
    assert card["pendentes"] == 1
    assert card["aac_hours_fmt"] == "40"
    assert card["aeu_hours_fmt"] == "0"
    assert card["ch_total_fmt"] == "40"
    assert card["aac_pct"] == int((40 * 100) // 160)
    assert card["aeu_pct"] == 0
    assert card["total_pct"] == int((40 * 100) // (160 + 80))
    assert card["total_applicable"] is True
    assert card["aac_applicable"] is True
    assert card["aeu_applicable"] is True
    assert card["periodo_atual_label"] == f"{main.periodo_corrente(2024, 1)}º período", (
        "card period label must be computed from ano_inicio/semestre_inicio via "
        "periodo_corrente"
    )
    expected_avg_pct = int(
        round(min(100.0, (40.0 * 100.0) / (160 + 80)))
    )
    assert card["attainment_avg_pct_label"] == f"{expected_avg_pct}%"
    assert card["attainment_donut_gradient"].startswith("conic-gradient(")
    assert card["attainment_buckets"][4]["count"] == 1, (
        "the single active aluno at <25% attainment must land in the last bucket"
    )

    assert set(summary) == SUMMARY_KEY_SET
    assert summary == {
        "total_turmas": 1,
        "total_turmas_ativas": 1,
        "turmas_com_aac": 1,
        "turmas_com_aeu": 1,
        "media_alunos_por_turma_fmt": "1,0",
    }
    assert total_geral is not None, (
        "an odd turma-card count must produce a Total Geral card"
    )
    assert set(total_geral) == TOTAL_GERAL_KEY_SET
    assert total_geral["label"] == "Total Geral"
    assert total_geral["total_alunos"] == 1
    assert total_geral["aac_pct"] == int((40 * 100) // 160)
    assert total_geral["aeu_pct"] == 0
    assert total_geral["ch_total_fmt"] == "40"
    assert total_geral["pendentes"] == 1

    conn.execute(
        "INSERT INTO turmas (id, nome, codigo, status) "
        "VALUES (2, 'Turma B', 'TUR-B', 'Inativa')"
    )
    conn.commit()
    cards, total_geral, summary = main._build_admin_dashboard_turma_cards(conn)
    assert len(cards) == 2
    assert total_geral is None, (
        "an even turma-card count must NOT produce a Total Geral card"
    )
    assert summary["total_turmas"] == 2
    assert summary["total_turmas_ativas"] == 1
    assert summary["turmas_com_aac"] == 1
    assert summary["turmas_com_aeu"] == 1
    conn.close()


def test_green_14_csrf_zero_dashboard_partition_and_cumulative_projection():
    # Dashboard cohort contributes ZERO mutating rows: /admin/dashboard is
    # GET-only.  The historical cumulative owner-delta projections therefore
    # remain 35 (alunos/turmas/cursos), 43 (matrizes) and 48 (requisicoes) --
    # no regeneration of the canonical snapshots is authorized or expected.
    snapshot_dir = PROJECT_ROOT / "tests" / "_artifacts"
    for suffix in ("shadow_off", "shadow_on"):
        snapshot_path = snapshot_dir / f"csrf_inventory_{suffix}.json"
        assert snapshot_path.exists(), (
            f"canonical CSRF snapshot missing: {snapshot_path.name}"
        )
        report = json.loads(snapshot_path.read_text(encoding="utf-8-sig"))
        rows = report["rows"]
        assert len(rows) == 78, (
            f"snapshot {suffix} must keep the known 78-row contract"
        )

        dashboard_rows = [row for row in rows if row["route"] == DASHBOARD_RULE]
        assert dashboard_rows == [], (
            "Dashboard route must contribute zero mutating CSRF rows in "
            f"{suffix}; got {dashboard_rows}"
        )
        assert not any(
            row["view_function"] == "main.admin_dashboard"
            or row["view_function"].startswith("app.views.admin.dashboard.")
            for row in rows
        ), f"no admin_dashboard view_function may appear in {suffix}"

        meus_dados_rows = [
            row for row in rows if row["route"] == "/admin/meus_dados"
        ]
        assert len(meus_dados_rows) == 1, (
            "admin_meus_dados POST must stay the single tracked row "
            f"in {suffix}"
        )
        assert meus_dados_rows[0]["method"] == "POST"
        # UT-14 seam: the meus_dados CSRF owner is state-aware on the real
        # UT-14 target availability (absent -> main-owned; present ->
        # app.views.admin.meus_dados.admin_meus_dados).  Snapshots are
        # read-only here; regeneration is a coherent-pair step of the
        # UT-14 implementation phase, never part of RED.
        expected_meus_dados_owner = (
            "app.views.admin.meus_dados.admin_meus_dados"
            if MEUS_DADOS_TARGET_PATH.exists()
            else "main.admin_meus_dados"
        )
        assert meus_dados_rows[0]["view_function"] == expected_meus_dados_owner, (
            "admin_meus_dados CSRF inventory owner must follow the real "
            "UT-14 target availability: expected "
            f"{expected_meus_dados_owner!r}, got {meus_dados_rows[0]['view_function']!r}"
        )


def test_green_15_dashboard_get_is_not_csrf_governed_and_redirects_unauth():
    response = main.app.test_client().get("/admin/dashboard", follow_redirects=False)
    assert response.status_code in (302, 303), (
        "GET /admin/dashboard must stay outside CSRF governance and redirect "
        f"unauthenticated users, got {response.status_code}"
    )


def test_green_16_factory_opt_out_neighbor_leakage_state_aware():
    from app import create_app

    kwargs = {flag: False for flag in EXISTING_FACTORY_FLAGS}
    if TARGET_PATH.exists():
        kwargs[FUTURE_FACTORY_FLAG] = False
    if DEMO_TARGET_PATH.exists():
        kwargs["register_admin_demo_blueprint"] = False

    app = create_app(
        register_presets_blueprint=False,
        register_aluno_blueprint=False,
        **kwargs,
    )
    live_endpoints = {rule.endpoint for rule in app.url_map.iter_rules()}
    for name in NEIGHBOR_ROUTE_NAMES:
        assert name not in live_endpoints, (
            f"{name} must never leak into a flags-off factory app (pre-target "
            "it is main-owned and factory-absent; post-target it must be "
            "removable through its own factory flag), got a registered "
            "endpoint"
        )
    assert "admin_dashboard" not in live_endpoints, (
        "the Dashboard cohort endpoint must not be factory-registered while "
        "main-owned (pre-target) or when opted out (post-target)"
    )
