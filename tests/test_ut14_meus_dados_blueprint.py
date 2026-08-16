"""UT-14 RED — Meus Dados cohort extraction contract.

Future canonical owner: ``app/views/admin/meus_dados.py``.

Authoritative relocated-symbol manifest (EXACTLY 1 symbol):
- 1 route (LegacyRouteSpec-preserving, GET + POST): ``admin_meus_dados``.

There are NO cohort-local helpers and NO cohort-local constants in the frozen
target (only the standard wiring assignments ``bp_admin_meus_dados`` and
``LEGACY_ROUTE_SPECS``).

Explicitly OUTSIDE UT-14 (hard boundary, both states):
``admin_demo_clientes_form_pack`` stays main-owned; ``admin_dashboard``,
``uploaded_file``, ``health``, ``favicon``, the aluno profile routes and every
UT-16 residual symbol stay in their current owners.

This file contains exactly 27 collected tests:
- ``test_red_a``..``test_red_o`` (15) are FUTURE ARCHITECTURAL CONTRACT
  assertions; while the target module is absent they fail with plain
  AssertionError only (no ImportError / ModuleNotFoundError / AttributeError /
  TypeError / fixture or collection error);
- ``test_green_1``..``test_green_12`` (12) characterize CURRENT behavior and
  invariant controls that implementation is forbidden to change; every GREEN
  must remain valid after legitimate extraction.

Collection-safety rule: the future module is imported only through a guarded
loader after its file existence is established; sentinels are used instead of
exception-based RED signals.  No parametrization changes the collected count.

State-aware Meus Dados principle (supervisor-authorized UT-14 seam): the
legitimate pre-target state is main-owned; the post-target state is exactly
target-owned for the single moved symbol plus a main identity facade 1/1.
Mixed moved ownership must fail.  Expected ownership is derived from REAL
target availability (file existence), never from the assertion under test and
never from a snapshot.

CSRF owner contract (test_red_k): the single mutating row
(POST /admin/meus_dados) is currently encoded in both canonical CSRF
inventories as ``main.admin_meus_dados``; after extraction it must become
``app.views.admin.meus_dados.admin_meus_dados``.  The snapshots are read-only
here; regeneration is a coherent-pair step of the implementation phase, never
part of RED.  The projected historical cumulative owner-delta totals after
UT-14 are 36 / 44 / 49 (UT-13 closed at 35 / 43 / 48 with a zero-delta
Dashboard partition; UT-14 contributes exactly 1 owner-only transition).

Shared canonical owners are NOT moved into the target:
``get_db_connection`` (app.db), ``ensure_usuario_profile_schema``
(app.db_maintenance), ``hash_password`` (app.security.passwords),
``save_upload`` (app.uploads), ``flash`` (utils.messages) and
``admin_required`` (app.auth) stay where they are; the move is
MOVE, DO NOT CHANGE -- no C4/schema cleanup, no migration v4, request-path
side effects (``ensure_usuario_profile_schema`` on every GET,
``session["user_name"]`` set before avatar handling, avatar-ValueError
continue-toward-commit, no explicit rollback, exactly one ``conn.commit()``
on the success path) are preserved.

Historical seam authority (supervisor pre-authorized UT-14 implementation-time
cochanges in EXACTLY tests/test_ut13_dashboard_blueprint.py,
tests/test_ut12_reportes_blueprint.py and
tests/test_phase4_requisicoes_blueprint.py -- classified
TEST_CONTRACT_SEAM / LEGITIMATE_UT14_COCHANGE; retire only stale
meus_dados-main residency expectations; never weaken
Dashboard/Reportes/Alertas/Arquivos protections and never reopen
UT-10/UT-11/UT-12/UT-13 files).
"""

from __future__ import annotations

import ast
import inspect
import io
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from app import db as app_db_module
from app.auth import get_admin_permission_requirement
from flask import session

import main


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TARGET_PATH = PROJECT_ROOT / "app" / "views" / "admin" / "meus_dados.py"
TARGET_REL = "app/views/admin/meus_dados.py"
TARGET_MODULE_NAME = "app.views.admin.meus_dados"
DEMO_TARGET_PATH = PROJECT_ROOT / "app" / "views" / "admin" / "demo.py"
MAIN_PATH = PROJECT_ROOT / "main.py"
CREATE_APP_PATH = PROJECT_ROOT / "app" / "__init__.py"
ADMIN_PACKAGE = PROJECT_ROOT / "app" / "views" / "admin"
BUSINESS_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}

ROUTE_NAMES = ("admin_meus_dados",)

MOVED_SYMBOLS = ROUTE_NAMES

ROUTE_MATRIX = (
    ("/admin/meus_dados", "admin_meus_dados", ("GET", "POST")),
)

EXPECTED_PAIRS = frozenset(
    (rule, endpoint, tuple(sorted(methods))) for rule, endpoint, methods in ROUTE_MATRIX
)

COHORT_RULE_PREFIXES = ("/admin/meus_dados",)

FUTURE_FACTORY_FLAG = "register_admin_meus_dados_blueprint"

# Hard negative surface: no neighbor, no infra route, no aluno profile route
# and no UT-16 residual symbol may be owned by (or moved into) the target.
NEGATIVE_SURFACE_NAMES = (
    "admin_demo_clientes_form_pack",
    "admin_dashboard",
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

# Frozen non-owner shape of the canonical CSRF inventory row for
# POST /admin/meus_dados (both shadow_off and shadow_on).  Only
# ``view_function`` may transition with UT-14 ownership.
FROZEN_MEUS_DADOS_ROW_SHAPE = {
    "route": "/admin/meus_dados",
    "method": "POST",
    "template_related": ["aluno_meus_dados.html"],
    "requires_login": "admin",
    "has_post_form": True,
    "csrf_in_html": True,
    "token_counts_per_form": [
        {"page": "/admin/meus_dados", "action": "/admin/meus_dados", "token_counts": [1]}
    ],
    "has_fetch_post": False,
    "fetch_sends_token": None,
    "has_dynamic_form": False,
    "risk": [],
    "notes": [],
    "evidence": [
        {"kind": "rendered_form", "page": "/admin/meus_dados", "action": "/admin/meus_dados", "token_count": 1}
    ],
    "status": "ok_rendered_form_token",
}


# ---------------------------------------------------------------------------
# Guarded loaders / AST scanners (detector self-control lives in green 1)
# ---------------------------------------------------------------------------


def _target_module():
    if not TARGET_PATH.exists():
        return None
    import importlib

    return importlib.import_module(TARGET_MODULE_NAME)


def _demo_target_module():
    if not DEMO_TARGET_PATH.exists():
        return None
    import importlib

    return importlib.import_module("app.views.admin.demo")


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
    return main.app.view_functions["admin_meus_dados"]


def _live_view_module():
    import importlib

    return importlib.import_module(_live_view().__module__)


class _CommitCounter:
    def __init__(self, conn, calls: dict):
        object.__setattr__(self, "_conn", conn)
        object.__setattr__(self, "_calls", calls)

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def commit(self):
        self._calls["commits"] = self._calls.get("commits", 0) + 1
        return self._conn.commit()


def _prepare_behavior_env(tmp_path, monkeypatch) -> int:
    """Isolated DB + upload root on a tmp_path; returns an admin user id."""
    db_path = tmp_path / "ut14_behavior.db"
    monkeypatch.setenv("APP_DATABASE", str(db_path))
    monkeypatch.setattr(main, "DATABASE", str(db_path))
    monkeypatch.setattr(app_db_module, "DATABASE", str(db_path))
    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir(exist_ok=True)
    monkeypatch.setitem(main.app.config, "UPLOAD_FOLDER", str(uploads_dir))

    with main.app.app_context():
        main.init_db()
        conn = main.get_db_connection()
        admin_id = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                "Admin UT14",
                "admin.ut14@teste.local",
                main.hash_password("admin12345"),
                "admin",
                "admin_total",
            ),
        ).lastrowid
        conn.commit()
    return int(admin_id)


# ===========================================================================
# RED — future architectural contract (A..O)
# ===========================================================================


def test_red_a_target_module_file_exists():
    assert TARGET_PATH.exists(), (
        "app/views/admin/meus_dados.py does not exist yet; UT-14 must create it"
    )


def test_red_b_target_owns_exact_one_route_no_helpers_no_constant():
    target = _target_module()
    assert target is not None, (
        "meus_dados module absent; 1-symbol ownership contract unsatisfiable"
    )

    source = Path(target.__file__).read_text(encoding="utf-8-sig")
    top_level = _top_level_defs(source)
    assigned = _top_level_assignments(source)

    assert top_level == set(MOVED_SYMBOLS), (
        f"target top-level functions must be exactly the moved callable; "
        f"missing={sorted(set(MOVED_SYMBOLS) - top_level)} "
        f"extra={sorted(top_level - set(MOVED_SYMBOLS))}"
    )
    assert len(MOVED_SYMBOLS) == 1, (
        f"moved-symbol target must be exactly 1, got {len(MOVED_SYMBOLS)}"
    )
    assert assigned == {"bp_admin_meus_dados", "LEGACY_ROUTE_SPECS"}, (
        "target must expose exactly the standard blueprint/spec wiring as "
        f"top-level assignments; no cohort-local constant admitted; got {assigned}"
    )
    for name in MOVED_SYMBOLS:
        obj = getattr(target, name, None)
        assert obj is not None, f"target.{name} missing"
        if callable(obj):
            assert inspect.unwrap(obj).__module__ == TARGET_MODULE_NAME, (
                f"target.{name} must be defined in app.views.admin.meus_dados, "
                f"got {inspect.unwrap(obj).__module__!r}"
            )


def test_red_c_one_route_admin_decorated_no_route_decorators():
    target = _target_module()
    assert target is not None, (
        "meus_dados module absent; route-ownership contract unsatisfiable"
    )

    source = Path(target.__file__).read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert "admin_meus_dados" in functions
    decorators = {ast.unparse(item) for item in functions["admin_meus_dados"].decorator_list}
    assert decorators == {"admin_required"}, (
        f"route admin_meus_dados decorators must be exactly {{admin_required}}, "
        f"got {decorators}"
    )
    assert _route_decorator_calls(source) == [], (
        "target must not contain any @app.route / @bp.route decorators; "
        "routes register through LegacyRouteSpec"
    )


def test_red_d_exactly_one_spec_two_pairs_frozen_matrix():
    target = _target_module()
    assert target is not None, (
        "meus_dados module absent; LegacyRouteSpec contract unsatisfiable"
    )

    specs = getattr(target, "LEGACY_ROUTE_SPECS", None)
    assert isinstance(specs, tuple), (
        "target must expose an immutable LEGACY_ROUTE_SPECS tuple"
    )
    assert len(specs) == 1, f"expected 1 LegacyRouteSpec, got {len(specs)}"

    encoded = {(spec.rule, spec.endpoint, spec.methods) for spec in specs}
    assert encoded == EXPECTED_PAIRS, (
        f"spec set mismatch: missing={sorted(EXPECTED_PAIRS - encoded)} "
        f"extra={sorted(encoded - EXPECTED_PAIRS)}"
    )
    assert sum(len(spec.methods) for spec in specs) == 2, (
        "specs must represent exactly 2 business endpoint/method pairs (GET "
        "and POST); HEAD must not be absorbed as a separate pair"
    )
    assert {spec.view_func for spec in specs} == {
        getattr(target, name) for name in ROUTE_NAMES
    }, "every spec must reference the target-owned route function"
    assert all("." not in spec.endpoint for spec in specs), (
        "no namespaced endpoint allowed"
    )


def test_red_e_spec_endpoint_resolves_meus_dados_rbac():
    target = _target_module()
    assert target is not None, (
        "meus_dados module absent; RBAC-from-specs contract unsatisfiable"
    )

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
            expected = (
                ("meus_dados", "view") if method == "GET" else ("meus_dados", "edit")
            )
            assert requirement == expected, (
                f"{spec.endpoint} {method} must be governed by {expected}, "
                f"got {requirement}"
            )
    assert get_admin_permission_requirement("admin_meus_dados", "GET") == (
        "meus_dados",
        "view",
    ), "admin_meus_dados GET must resolve to (meus_dados, view)"
    assert get_admin_permission_requirement("admin_meus_dados", "POST") == (
        "meus_dados",
        "edit",
    ), "admin_meus_dados POST must resolve to (meus_dados, edit)"


def test_red_f_main_has_no_local_ownership_and_no_cohort_route_decorators():
    source = MAIN_PATH.read_text(encoding="utf-8-sig")
    defined = _top_level_defs(source)

    assert not (set(MOVED_SYMBOLS) & defined), (
        "main.py must no longer locally define moved callables: "
        f"{sorted(set(MOVED_SYMBOLS) & defined)}"
    )
    assert _cohort_route_decorators(source) == [], (
        "main.py must no longer register /admin/meus_dados via @app.route"
    )


def test_red_g_main_facade_exact_identity_no_wrappers():
    target = _target_module()
    assert target is not None, (
        "meus_dados module absent; main compatibility contract unsatisfiable"
    )

    for name in MOVED_SYMBOLS:
        assert hasattr(main, name), (
            f"main.{name} missing from the compatibility facade"
        )
        assert getattr(main, name) is getattr(target, name), (
            f"main.{name} must be the identical object exported by meus_dados "
            "(identity re-export, no wrapper, no copied implementation)"
        )


def test_red_h_target_has_no_main_backedge():
    target = _target_module()
    assert target is not None, (
        "meus_dados module absent; no-back-edge contract unsatisfiable"
    )

    source = Path(target.__file__).read_text(encoding="utf-8-sig")
    edges = _main_back_edges(source)
    assert edges == [], (
        f"target must not import main (including dynamic-import equivalents): {edges}"
    )


def test_red_i_factory_declares_keyword_and_single_registration_path():
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
        "create_app must accept register_admin_meus_dados_blueprint"
    )
    default = kw_pairs[FUTURE_FACTORY_FLAG]
    assert isinstance(default, ast.Constant) and default.value is True, (
        "register_admin_meus_dados_blueprint must default to True"
    )

    registration_calls = [
        call
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "register_legacy_blueprint"
        and any(
            isinstance(arg, ast.Name) and arg.id == "bp_admin_meus_dados"
            for arg in call.args
        )
    ]
    assert len(registration_calls) == 1, (
        "create_app must register bp_admin_meus_dados exactly once through "
        "register_legacy_blueprint"
    )


def test_red_j_factory_default_registers_two_pairs_opt_out_registers_none():
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
        register_admin_meus_dados_blueprint=False,
    )

    assert _cohort_rules(default_app) == EXPECTED_PAIRS, (
        "default factory must register exactly the 1 frozen route / 2 pairs"
    )
    assert _cohort_rules(opt_out_app) == frozenset(), (
        "opt-out factory must register none of the cohort endpoints"
    )
    for app_ in (default_app, opt_out_app):
        live_endpoints = {rule.endpoint for rule in app_.url_map.iter_rules()}
        demo_registered = "admin_demo_clientes_form_pack" in live_endpoints
        # UT-15 seam: Demo is a main-owned hard boundary pre-target (never
        # factory-registered); once app/views/admin/demo.py exists it becomes
        # factory-registered by default.  Neither factory app below opts the
        # Demo blueprint out, so presence must follow the real target.
        assert demo_registered is DEMO_TARGET_PATH.exists(), (
            "UT-15 seam: Demo factory presence must follow the real demo.py "
            "target availability (absent -> main-owned/not registered; "
            "present -> default factory registers it), got "
            f"registered={demo_registered!r}"
        )
        assert not any(
            "." in rule.endpoint
            for rule in app_.url_map.iter_rules()
            if rule.endpoint in ROUTE_NAMES
        ), "no namespaced endpoint variant may exist"


def test_red_k_csrf_owner_state_aware_and_frozen_row_shape():
    snapshot_dir = PROJECT_ROOT / "tests" / "_artifacts"
    expected_owner = (
        "app.views.admin.meus_dados.admin_meus_dados"
        if TARGET_PATH.exists()
        else "main.admin_meus_dados"
    )
    owners_seen: set[str] = set()
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

        meus_dados_rows = [row for row in rows if row["route"] == "/admin/meus_dados"]
        assert len(meus_dados_rows) == 1, (
            "admin_meus_dados POST must stay the single tracked row "
            f"in {suffix}"
        )
        row = meus_dados_rows[0]
        assert row["method"] == "POST"
        assert row["view_function"] == expected_owner, (
            "admin_meus_dados CSRF inventory owner must follow the real "
            "UT-14 target availability: expected "
            f"{expected_owner!r}, got {row['view_function']!r}"
        )
        shape = dict(row)
        shape.pop("view_function")
        assert shape == FROZEN_MEUS_DADOS_ROW_SHAPE, (
            f"only the view_function owner may differ for the meus_dados CSRF "
            f"row in {suffix}"
        )
        owners_seen.add(row["view_function"])

    assert len(owners_seen) == 1, (
        "shadow_on / shadow_off must remain coherent (same owner for the "
        f"meus_dados row), got {sorted(owners_seen)}"
    )


def test_red_l_message_scanner_auto_covers_target_without_registration():
    from utils import messages as messages_module

    catalog = messages_module._message_catalog()
    assert len(catalog) == 539, (
        "message catalog count must remain 539 through the extraction; "
        f"got {len(catalog)}"
    )

    backend_paths = {
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in messages_module._iter_backend_files()
    }
    assert TARGET_REL in backend_paths, (
        "app/views/admin/meus_dados.py must be inside backend message-scanner "
        "coverage once created (no scanner-registration change expected)"
    )


def test_red_m_target_owns_live_symbol_coherently_neighbors_stay_elsewhere():
    target = _target_module()
    assert target is not None, (
        "meus_dados module absent; coherent 1-symbol ownership contract "
        "unsatisfiable"
    )

    view = main.app.view_functions.get("admin_meus_dados")
    assert view is not None, "live endpoint admin_meus_dados missing"
    assert inspect.unwrap(view).__module__ == TARGET_MODULE_NAME, (
        "admin_meus_dados must be owned by app.views.admin.meus_dados after "
        f"extraction, got {inspect.unwrap(view).__module__!r}"
    )
    assert view is target.admin_meus_dados, (
        "live endpoint admin_meus_dados must identity-match the target callable"
    )

    for name in NEGATIVE_SURFACE_NAMES:
        assert getattr(target, name, None) is None, (
            f"{name} must not appear in the meus_dados target surface"
        )

    demo = main.app.view_functions.get("admin_demo_clientes_form_pack")
    assert demo is not None, "live demo endpoint missing"
    demo_target = _demo_target_module()
    if demo_target is not None:
        assert inspect.unwrap(demo).__module__ == "app.views.admin.demo", (
            "admin_demo_clientes_form_pack must be owned by "
            "app.views.admin.demo once the real demo.py target exists, "
            f"got {inspect.unwrap(demo).__module__!r}"
        )
        assert demo is demo_target.admin_demo_clientes_form_pack, (
            "live demo endpoint must identity-match the demo target callable"
        )
    else:
        assert demo.__module__ == "main", (
            "admin_demo_clientes_form_pack must remain main-owned pre-target "
            f"(UT-15 seam), got {demo.__module__!r}"
        )


def test_red_n_blueprint_identity_and_dotless_live_endpoints():
    target = _target_module()
    assert target is not None, (
        "meus_dados module absent; blueprint identity contract unsatisfiable"
    )

    blueprint = getattr(target, "bp_admin_meus_dados", None)
    assert blueprint is not None, "target must expose bp_admin_meus_dados"
    assert blueprint.name == "admin_meus_dados_blueprint", (
        f"blueprint name must be admin_meus_dados_blueprint, got {blueprint.name!r}"
    )

    live = {
        rule.endpoint: main.app.view_functions[rule.endpoint]
        for rule in main.app.url_map.iter_rules()
        if rule.endpoint in ROUTE_NAMES
    }
    assert len(live) == 1, "exactly one live meus_dados endpoint required"
    for name in ROUTE_NAMES:
        assert live[name] is getattr(target, name), (
            f"live endpoint {name} must identity-match the target callable"
        )

    namespaced = [
        endpoint
        for endpoint in main.app.view_functions
        if endpoint.startswith("admin_meus_dados_blueprint.")
    ]
    assert namespaced == [], (
        f"no admin_meus_dados_blueprint.* namespaced endpoint may exist: {namespaced}"
    )


def test_red_o_admin_package_inventory_includes_meus_dados_target():
    package_files = sorted(path.name for path in ADMIN_PACKAGE.glob("*.py"))
    assert "meus_dados.py" in package_files, (
        "app/views/admin/meus_dados.py must be part of the exact admin package "
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
            "app/views/admin/meus_dados.py exists"
        )
    else:
        assert loaded is None, (
            "guarded loader must return None while the target file is absent"
        )


def test_green_2_live_route_matrix_one_rule_two_methods():
    matching = [
        rule
        for rule in main.app.url_map.iter_rules()
        if rule.endpoint == "admin_meus_dados"
    ]
    assert len(matching) == 1, (
        "exactly one live rule must exist for admin_meus_dados"
    )
    rule = matching[0]
    assert rule.rule == "/admin/meus_dados"
    methods = set(rule.methods or ()) & BUSINESS_METHODS
    assert methods == {"GET", "POST"}, (
        f"live business methods must be {{GET, POST}}, got {sorted(methods)}"
    )
    assert main.app.view_functions["admin_meus_dados"] is not None


def test_green_3_rbac_exact_matches_and_live_endpoint_set():
    assert get_admin_permission_requirement("admin_meus_dados", "GET") == (
        "meus_dados",
        "view",
    )
    assert get_admin_permission_requirement("admin_meus_dados", "POST") == (
        "meus_dados",
        "edit",
    )
    live_endpoints = {
        endpoint
        for endpoint in main.app.view_functions
        if endpoint.startswith("admin_meus_dados")
    }
    assert live_endpoints == set(ROUTE_NAMES), (
        "exactly the frozen admin_meus_dados endpoint must be live; "
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


def test_green_5_message_catalog_schema_and_reverse_dependencies():
    from utils import messages as messages_module

    assert len(messages_module._message_catalog()) == 539, (
        "current catalog baseline must be 539"
    )

    from app.db_maintenance import SCHEMA_MIGRATIONS, SCHEMA_VERSION

    assert SCHEMA_VERSION == 3, f"SCHEMA_VERSION must stay 3, got {SCHEMA_VERSION}"
    versions = {version for version, _name, _fn in SCHEMA_MIGRATIONS}
    assert versions == {1, 2, 3}, (
        "migration registry must contain exactly v1/v2/v3, no v4; "
        f"got {sorted(versions)}"
    )

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


def test_green_6_sequential_owners_unchanged():
    demo_expected_module = (
        "app.views.admin.demo"
        if DEMO_TARGET_PATH.exists()
        else "main"
    )
    expected_owners = {
        "admin_arquivos": "app.views.admin.arquivos",
        "admin_alertas": "app.views.admin.alertas",
        "admin_reportes": "app.views.admin.reportes",
        "admin_dashboard": "app.views.admin.dashboard",
        "admin_demo_clientes_form_pack": demo_expected_module,
    }
    for endpoint, module_name in expected_owners.items():
        view = main.app.view_functions.get(endpoint)
        assert view is not None, f"live endpoint {endpoint} missing"
        assert view.__module__ == module_name, (
            f"{endpoint} must stay owned by {module_name}, "
            f"got {view.__module__!r}"
        )


def test_green_7_get_characterization_and_not_found(tmp_path, monkeypatch):
    admin_id = _prepare_behavior_env(tmp_path, monkeypatch)
    view = _live_view()
    view_module = _live_view_module()
    captured: dict = {}

    def _capture_render(template_name, **kwargs):
        captured["template_name"] = template_name
        captured["kwargs"] = kwargs
        return "<html>captured</html>"

    monkeypatch.setattr(view_module, "render_template", _capture_render)

    with main.app.test_request_context("/admin/meus_dados"):
        session["user_id"] = admin_id
        session["user_type"] = "admin"
        result = view()

    assert result == "<html>captured</html>"
    assert captured["template_name"] == "aluno_meus_dados.html"
    kwargs = captured["kwargs"]
    assert kwargs["base_template"] == "base.html"
    assert kwargs["show_student_fields"] is False
    assert kwargs["cancel_url"] == "/admin/dashboard"
    assert kwargs["turmas"] == []
    profile = kwargs["profile"]
    assert set(profile.keys()) == {"nome", "email", "foto_perfil"}, (
        "profile SELECT shape must be exactly (nome, email, foto_perfil)"
    )
    assert profile["nome"] == "Admin UT14"
    assert profile["email"] == "admin.ut14@teste.local"
    assert profile["foto_perfil"] is None

    captured.clear()
    with main.app.test_request_context("/admin/meus_dados"):
        session["user_id"] = 999999
        session["user_type"] = "admin"
        result = view()
        flashes = list(session.get("_flashes") or [])

    assert result.status_code == 302
    assert result.location == "/admin/dashboard"
    assert any(cat == "error" and "Usuário" in str(msg) for cat, msg in flashes), (
        f"not-found must flash an error, got {flashes}"
    )
    assert captured == {}, "not-found must redirect BEFORE rendering"


def test_green_8_post_password_and_no_password_branches(tmp_path, monkeypatch):
    admin_id = _prepare_behavior_env(tmp_path, monkeypatch)
    view = _live_view()
    view_module = _live_view_module()
    calls: dict = {"commits": 0}
    original_get_db_connection = view_module.get_db_connection

    def _wrapped_get_db_connection():
        return _CommitCounter(original_get_db_connection(), calls)

    monkeypatch.setattr(view_module, "get_db_connection", _wrapped_get_db_connection)

    with main.app.test_request_context(
        "/admin/meus_dados",
        method="POST",
        data={
            "nome": "Novo Admin UT14",
            "email": "novo.email@teste.local",
            "senha": "NovaSenha!123",
            "remove_foto": "0",
        },
    ):
        session["user_id"] = admin_id
        session["user_type"] = "admin"
        result = view()
        flashes = list(session.get("_flashes") or [])
        user_name = session.get("user_name")

    assert result.status_code == 302
    assert result.location == "/admin/meus_dados"
    assert calls["commits"] == 1, "exactly one successful-path commit expected"
    assert user_name == "Novo Admin UT14"
    assert any(cat == "success" and "atualizados" in str(msg) for cat, msg in flashes), (
        f"success flash expected, got {flashes}"
    )

    with main.app.app_context():
        conn = main.get_db_connection()
        row = conn.execute(
            "SELECT nome, email, senha FROM usuarios WHERE id = ?", (admin_id,)
        ).fetchone()
    assert row["nome"] == "Novo Admin UT14"
    assert row["email"] == "novo.email@teste.local"
    assert main.check_password(row["senha"], "NovaSenha!123"), (
        "password UPDATE shape must store the new hashed password"
    )
    assert not main.check_password(row["senha"], "admin12345")

    calls["commits"] = 0
    with main.app.test_request_context(
        "/admin/meus_dados",
        method="POST",
        data={
            "nome": "Admin Sem Senha",
            "email": "novo.email@teste.local",
            "remove_foto": "0",
        },
    ):
        session["user_id"] = admin_id
        session["user_type"] = "admin"
        result = view()

    assert result.status_code == 302
    assert calls["commits"] == 1, (
        "no-password branch must still commit exactly once"
    )
    with main.app.app_context():
        conn = main.get_db_connection()
        row = conn.execute("SELECT senha FROM usuarios WHERE id = ?", (admin_id,)).fetchone()
    assert main.check_password(row["senha"], "NovaSenha!123"), (
        "no-password UPDATE shape must NOT touch senha"
    )


def test_green_9_avatar_removal_and_session_pop(tmp_path, monkeypatch):
    admin_id = _prepare_behavior_env(tmp_path, monkeypatch)
    view = _live_view()
    view_module = _live_view_module()
    calls: dict = {"commits": 0}
    old_foto = f"avatars/usuario_{admin_id}/avatar-old.png"

    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "UPDATE usuarios SET foto_perfil = ? WHERE id = ?",
            (old_foto, admin_id),
        )
        conn.commit()

    original_get_db_connection = view_module.get_db_connection

    def _wrapped_get_db_connection():
        return _CommitCounter(original_get_db_connection(), calls)

    monkeypatch.setattr(view_module, "get_db_connection", _wrapped_get_db_connection)

    with main.app.test_request_context(
        "/admin/meus_dados",
        method="POST",
        data={
            "nome": "Admin UT14",
            "email": "admin.ut14@teste.local",
            "remove_foto": "1",
        },
    ):
        session["user_id"] = admin_id
        session["user_type"] = "admin"
        session["foto_perfil"] = old_foto
        result = view()
        foto_after = session.get("foto_perfil")

    assert result.status_code == 302
    assert calls["commits"] == 1
    assert foto_after is None, "session foto_perfil must be popped on removal"
    with main.app.app_context():
        conn = main.get_db_connection()
        row = conn.execute(
            "SELECT foto_perfil FROM usuarios WHERE id = ?", (admin_id,)
        ).fetchone()
    assert row["foto_perfil"] is None, "avatar removal must NULL the DB column"


def test_green_10_avatar_upload_and_valueerror_continues_to_commit(tmp_path, monkeypatch):
    admin_id = _prepare_behavior_env(tmp_path, monkeypatch)
    view = _live_view()
    view_module = _live_view_module()
    calls: dict = {"commits": 0}
    original_get_db_connection = view_module.get_db_connection

    def _wrapped_get_db_connection():
        return _CommitCounter(original_get_db_connection(), calls)

    monkeypatch.setattr(view_module, "get_db_connection", _wrapped_get_db_connection)

    with main.app.test_request_context(
        "/admin/meus_dados",
        method="POST",
        data={
            "nome": "Admin UT14",
            "email": "admin.ut14@teste.local",
            "remove_foto": "0",
            "foto_perfil": (io.BytesIO(b"png-bytes"), "minhafoto.png"),
        },
        content_type="multipart/form-data",
    ):
        session["user_id"] = admin_id
        session["user_type"] = "admin"
        result = view()
        foto_after = session.get("foto_perfil")

    assert result.status_code == 302
    assert calls["commits"] == 1
    assert foto_after is not None, "successful upload must set session foto_perfil"
    foto_after_norm = foto_after.replace("\\", "/")
    assert foto_after_norm.startswith(f"avatars/usuario_{admin_id}/"), foto_after
    assert "avatar-" in foto_after, "save_upload prefix must be avatar-"
    with main.app.app_context():
        conn = main.get_db_connection()
        row = conn.execute(
            "SELECT foto_perfil FROM usuarios WHERE id = ?", (admin_id,)
        ).fetchone()
    assert row["foto_perfil"] == foto_after
    assert (tmp_path / "uploads" / foto_after).is_file(), (
        "avatar must be persisted below the upload root"
    )

    # Disallowed extension -> save_upload raises ValueError inside the route;
    # the flash is recorded, the profile transaction STILL commits and the
    # success redirect still happens (MOVE, DO NOT CHANGE -- pre-existing debt).
    calls["commits"] = 0
    with main.app.test_request_context(
        "/admin/meus_dados",
        method="POST",
        data={
            "nome": "Admin Foto Ruim",
            "email": "admin.ut14@teste.local",
            "remove_foto": "0",
            "foto_perfil": (io.BytesIO(b"text-bytes"), "foto.txt"),
        },
        content_type="multipart/form-data",
    ):
        session["user_id"] = admin_id
        session["user_type"] = "admin"
        result = view()
        flashes = list(session.get("_flashes") or [])
        user_name = session.get("user_name")

    assert result.status_code == 302
    assert result.location == "/admin/meus_dados"
    assert calls["commits"] == 1, (
        "avatar ValueError must NOT abort the profile transaction (pre-existing "
        "behavior preserved)"
    )
    assert user_name == "Admin Foto Ruim", (
        "session user_name must be set before avatar handling (pre-existing timing)"
    )
    assert any(cat == "error" and "Foto inválida" in str(msg) for cat, msg in flashes), (
        f"invalid-avatar flash expected, got {flashes}"
    )
    assert any(cat == "success" and "atualizados" in str(msg) for cat, msg in flashes), (
        f"success flash must still fire, got {flashes}"
    )
    with main.app.app_context():
        conn = main.get_db_connection()
        row = conn.execute(
            "SELECT nome, foto_perfil FROM usuarios WHERE id = ?", (admin_id,)
        ).fetchone()
    assert row["nome"] == "Admin Foto Ruim"


def test_green_11_integrity_error_and_broad_exception_handled_render(tmp_path, monkeypatch):
    admin_id = _prepare_behavior_env(tmp_path, monkeypatch)
    view = _live_view()
    view_module = _live_view_module()
    captured: dict = {}

    def _capture_render(template_name, **kwargs):
        captured["template_name"] = template_name
        captured["kwargs"] = kwargs
        return "<html>captured</html>"

    monkeypatch.setattr(view_module, "render_template", _capture_render)

    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                "Outro Usuario",
                "duplicado@teste.local",
                main.hash_password("outra12345"),
                "admin",
                "administrativo",
            ),
        )
        conn.commit()

    with main.app.test_request_context(
        "/admin/meus_dados",
        method="POST",
        data={
            "nome": "Admin UT14",
            "email": "duplicado@teste.local",
            "remove_foto": "0",
        },
    ):
        session["user_id"] = admin_id
        session["user_type"] = "admin"
        result = view()
        flashes = list(session.get("_flashes") or [])

    assert result == "<html>captured</html>", (
        "handled IntegrityError must fall through to the final render"
    )
    assert captured["template_name"] == "aluno_meus_dados.html"
    assert any(cat == "error" and "e-mail" in str(msg) for cat, msg in flashes), (
        f"UNIQUE usuarios.email classification flash expected, got {flashes}"
    )
    with main.app.app_context():
        conn = main.get_db_connection()
        row = conn.execute("SELECT email FROM usuarios WHERE id = ?", (admin_id,)).fetchone()
    assert row["email"] == "admin.ut14@teste.local", (
        "failed commit must not persist the change"
    )

    # Broad exception: any Exception inside the try is flashed and the route
    # falls through to the same final render (MOVE, DO NOT CHANGE).
    def _boom(password):
        raise RuntimeError("boom-ut14")

    monkeypatch.setattr(view_module, "hash_password", _boom)
    captured.clear()
    with main.app.test_request_context(
        "/admin/meus_dados",
        method="POST",
        data={
            "nome": "Admin UT14",
            "email": "admin.ut14@teste.local",
            "senha": "x",
            "remove_foto": "0",
        },
    ):
        session["user_id"] = admin_id
        session["user_type"] = "admin"
        result = view()
        flashes = list(session.get("_flashes") or [])

    assert result == "<html>captured</html>"
    assert captured["template_name"] == "aluno_meus_dados.html"
    assert any(cat == "error" and "Erro inesperado" in str(msg) for cat, msg in flashes), (
        f"broad-exception flash expected, got {flashes}"
    )


def test_green_12_template_and_frontend_endpoint_contract():
    base_html = (PROJECT_ROOT / "templates" / "base.html").read_text(encoding="utf-8")
    assert "url_for('admin_meus_dados')" in base_html, (
        "base.html must keep the endpoint-based profile/sidebar links"
    )

    meus_dados_html = (
        PROJECT_ROOT / "templates" / "aluno_meus_dados.html"
    ).read_text(encoding="utf-8")
    assert '<form method="post" enctype="multipart/form-data">' in meus_dados_html, (
        "form must keep posting to the current path (no explicit action)"
    )
    assert 'name="foto_perfil"' in meus_dados_html
    assert 'name="remove_foto"' in meus_dados_html
    assert "cancel_url" in meus_dados_html, "cancel link must keep using cancel_url"
    assert "url_for('uploaded_file'" in meus_dados_html, (
        "avatar display must keep using the main-owned uploaded_file endpoint"
    )

    aluno_views_src = (PROJECT_ROOT / "app" / "views" / "aluno.py").read_text(
        encoding="utf-8"
    )
    assert '"aluno_meus_dados.html"' in aluno_views_src, (
        "template remains shared with the aluno profile route"
    )
