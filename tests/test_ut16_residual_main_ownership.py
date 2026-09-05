"""UT-16 RED — Residual Main Ownership extraction contract (Criterion 9).

Supervisor-frozen scope (adjudication of the UT-16 entry census):

GROUP A — Aluno snapshot display duplicates (main-local, dead, divergent):
  ``_coerce_aluno_snapshot_scalar``, ``_build_aluno_requisicao_snapshot_display``
  canonical owner already exists: ``app/views/aluno.py``.
  NO main compatibility facade required (census proved zero consumers of
  main's copies).

GROUP B — Cursos/Turmas constant duplicate (main-local, dead, identical):
  ``UPPER_CODE_RE``
  canonical owner already exists: ``app/views/admin/alunos_turmas_cursos.py``.
  NO main compatibility facade required.

GROUP C — Versioning integrity (MOVE, DO NOT CHANGE):
  ``validar_integridade_versionamento_atividades``
  current owner: ``main.py`` (real 103-line implementation, live behavioral
  consumers call through ``main``);
  required canonical target: ``app/versioning/integrity.py``;
  main must retain an EXACT IDENTITY re-export:
  ``main.validar_integridade_versionamento_atividades is
  app.versioning.integrity.validar_integridade_versionamento_atividades``.
  The function contains user-facing message strings and
  ``utils.messages._iter_backend_files()`` does NOT scan ``app/versioning/**``
  (verified: it covers main.py + an explicit list + ``app/views/**`` only),
  so implementation must register ``app/versioning/integrity.py`` in
  ``_iter_backend_files()``; the message catalog must stay exactly 536 (the
  strings move with the function; no add/remove/change).

Explicitly NOT authorized (must remain in main; any RED expectation that
requires them to disappear is wrong): ``proximo_numero_turma``,
``_login_attempts``, ``_APP_DIR``, ``_TEMPLATES_DIR``, ``admin_required``,
``aluno_required``, ``_client_ip``, ``_login_rate_limited``,
``_register_login_attempt``, ``login``, ``logout``, ``index``,
``_rebind_legacy_core_exports``, ``_rebind_legacy_aluno_exports``,
``logger``, ``_log_fmt``, ``app``, ``uploaded_file``, ``health``,
``favicon``.  D-3 remains deferred.  UT-17 remains untouched.

MOVE-DO-NOT-CHANGE fingerprint: the RED pins the canonical implementation of
``validar_integridade_versionamento_atividades`` to the normalized AST
fingerprint of the HEAD baseline.  BASELINE_FP_SHA was computed at RED R1
from ``git show HEAD:main.py`` (entry HEAD ``d217c40f…``) as:

  sha256(ast.unparse(FunctionDef of validar_integridade_versionamento_atividades
  parsed from the HEAD main.py blob, with decorator_list cleared))

Recompute for verification:
  git show HEAD:main.py | python -c "<parse; unparse; sha256>"
Expected: ``c6ad435ba8a5ccd970c67e5e8f8e6fb17b1cc83fa63be366b4518410bb2a235d``.

Allowed differences for the target implementation: module location;
future/type imports if necessary; the main compatibility re-export.  NO SQL
change, NO message change, NO exception change, NO return-value change, NO
``raise_on_error`` semantic change.

This file contains exactly 15 collected tests:
- ``test_red_a``..``test_red_g`` (7) are FUTURE ARCHITECTURAL CONTRACT
  assertions; while the target module is absent they fail with plain
  AssertionError only (no ImportError / ModuleNotFoundError / AttributeError /
  TypeError / fixture or collection error);
- ``test_green_1``..``test_green_8`` (8) characterize CURRENT behavior and
  invariant controls that implementation is forbidden to change.

Collection-safety rule: the future module is imported only through a guarded
loader after its file existence is established; sentinels are used instead of
exception-based RED signals.  No parametrization changes the collected count.
"""

from __future__ import annotations

import ast
import copy
import hashlib
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

from app.auth import get_admin_permission_requirement
from app.views import aluno as aluno_view_module

import main


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TARGET_PATH = PROJECT_ROOT / "app" / "versioning" / "integrity.py"

from tests.test_ut15_demo_blueprint import (  # noqa: E402
    _authorized_csrf_snapshot_delta_report,
)
TARGET_REL = "app/versioning/integrity.py"
TARGET_MODULE_NAME = "app.versioning.integrity"
MAIN_PATH = PROJECT_ROOT / "main.py"
ALUNO_VIEW_PATH = PROJECT_ROOT / "app" / "views" / "aluno.py"
ATC_VIEW_PATH = PROJECT_ROOT / "app" / "views" / "admin" / "alunos_turmas_cursos.py"
BUSINESS_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}

# Baseline normalized AST fingerprint (SHA-256 of ast.unparse of the
# FunctionDef with decorators cleared) of the HEAD main.py implementation of
# validar_integridade_versionamento_atividades — see module docstring.
BASELINE_FP_SHA = "c6ad435ba8a5ccd970c67e5e8f8e6fb17b1cc83fa63be366b4518410bb2a235d"

GROUP_A_NAMES = (
    "_coerce_aluno_snapshot_scalar",
    "_build_aluno_requisicao_snapshot_display",
)
FROZEN_GROUP_A_NAMES = ("_coerce_aluno_snapshot_scalar",)
F3_SNAPSHOT_DISPLAY_NAME = "_build_aluno_requisicao_snapshot_display"

GROUP_B_NAME = "UPPER_CODE_RE"

VERSIONING_FUNC_NAME = "validar_integridade_versionamento_atividades"

# Residue explicitly NOT part of UT-16: source presence stays expected.
NON_UT16_MAIN_DEFS = (
    "proximo_numero_turma",
    "admin_required",
    "aluno_required",
    "_client_ip",
    "_login_rate_limited",
    "_register_login_attempt",
    "login",
    "logout",
    "index",
    "_rebind_legacy_core_exports",
    "_rebind_legacy_aluno_exports",
)
NON_UT16_MAIN_ASSIGNS = ("_login_attempts", "_APP_DIR", "_TEMPLATES_DIR")

# ---------------------------------------------------------------------------
# Guarded loaders / AST helpers
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


def _top_level_assign_names(source: str) -> set[str]:
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


def _git_blob_bytes(relative: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"HEAD:{relative}"],
        capture_output=True,
    )
    assert result.returncode == 0, (
        f"git show HEAD:{relative} failed: {result.stderr!r}"
    )
    return result.stdout


def _function_fingerprint_sha(source: str, name: str) -> str:
    tree = ast.parse(source)
    node = next(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    )
    clone = copy.deepcopy(node)
    clone.decorator_list = []
    return hashlib.sha256(ast.unparse(clone).encode("utf-8")).hexdigest()


def _assignment_fingerprint(source: str, name: str) -> str:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return hashlib.sha256(ast.unparse(node).encode("utf-8")).hexdigest()
    raise AssertionError(f"top-level assignment {name} not found in source")


def _local_route_decorators(source: str) -> set[str]:
    tree = ast.parse(source)
    rules: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and isinstance(decorator.func.value, ast.Name)
                and decorator.func.value.id == "app"
                and decorator.func.attr == "route"
                and decorator.args
                and isinstance(decorator.args[0], ast.Constant)
            ):
                rules.add(str(decorator.args[0].value))
    return rules


# ===========================================================================
# RED — future architectural contract (fails while the target is absent)
# ===========================================================================


def test_red_a_target_module_must_exist():
    target = _target_module()
    assert target is not None, (
        "app/versioning/integrity.py does not exist yet; UT-16 must create it"
    )


def test_red_b_target_surface_exactly_one_domain_function():
    target = _target_module()
    assert target is not None, (
        "integrity module absent; exact surface contract unsatisfiable"
    )
    source = Path(target.__file__).read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    defined = _top_level_defs(source)
    assert defined == {VERSIONING_FUNC_NAME}, (
        "the integrity target must define exactly the single versioning "
        f"integrity function; got {sorted(defined)}"
    )
    assert not any(
        isinstance(node, ast.ClassDef) for node in tree.body
    ), "no ClassDef may exist in the integrity target"

    assert not any(
        isinstance(node, ast.ImportFrom) and (node.module or "").startswith("flask")
        for node in ast.walk(tree)
    ), "the integrity target must not import from flask"
    assert "Blueprint" not in source, "no Blueprint may exist in the target"
    assert "request" not in source, "no request coupling may exist in the target"
    assert "session" not in source, "no session coupling may exist in the target"


def test_red_c_move_do_not_change_fingerprint():
    target = _target_module()
    assert target is not None, (
        "integrity module absent; MOVE-DO-NOT-CHANGE contract unsatisfiable"
    )
    source = Path(target.__file__).read_text(encoding="utf-8-sig")
    fingerprint = _function_fingerprint_sha(source, VERSIONING_FUNC_NAME)
    assert fingerprint == BASELINE_FP_SHA, (
        "validar_integridade_versionamento_atividades must match the frozen "
        "HEAD baseline AST fingerprint (MOVE, DO NOT CHANGE): expected "
        f"{BASELINE_FP_SHA}, got {fingerprint}"
    )


def test_red_d_target_has_no_main_backedge_no_ddl_and_preserved_signature():
    target = _target_module()
    assert target is not None, (
        "integrity module absent; no-back-edge contract unsatisfiable"
    )
    source = Path(target.__file__).read_text(encoding="utf-8-sig")
    assert "import main" not in source
    assert "__import__" not in source
    assert "importlib" not in source
    assert "sys.modules" not in source
    assert "CREATE TABLE" not in source
    assert "ALTER TABLE" not in source
    assert "SCHEMA_VERSION" not in source
    assert ".commit(" not in source
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name != "main" for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            assert node.module != "main"

    signature = inspect.signature(target.validar_integridade_versionamento_atividades)
    parameters = list(signature.parameters.items())
    assert [name for name, _ in parameters] == ["conn", "raise_on_error"]
    assert parameters[1][1].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters[1][1].default is True, (
        "raise_on_error must keep its default True (no semantic change)"
    )


def test_red_e_main_local_ownership_removed():
    source = MAIN_PATH.read_text(encoding="utf-8-sig")
    defined = _top_level_defs(source)
    assert not (set(GROUP_A_NAMES) | {VERSIONING_FUNC_NAME}) & defined, (
        "main.py must no longer locally define the Group A duplicates or the "
        "versioning integrity function; remaining local defs include "
        f"{sorted(defined & (set(GROUP_A_NAMES) | {VERSIONING_FUNC_NAME}))}"
    )
    assigned = _top_level_assign_names(source)
    assert GROUP_B_NAME not in assigned, (
        "main.py must no longer locally assign UPPER_CODE_RE"
    )


def test_red_f_main_identity_facade_for_versioning_integrity():
    target = _target_module()
    assert target is not None, (
        "integrity module absent; identity-facade contract unsatisfiable"
    )
    assert getattr(main, VERSIONING_FUNC_NAME, None) is getattr(
        target, VERSIONING_FUNC_NAME
    ), (
        "main.validar_integridade_versionamento_atividades must be the exact "
        "identity re-export of the app.versioning.integrity target (no "
        "wrapper, no copied body)"
    )
    # Group A/B need NO main facade: their absence from main is proven by
    # red_e (local ownership); attribute visibility is not asserted.


def test_red_g_message_scanner_covers_target_exactly_once_catalog_stays():
    from utils import messages as messages_module

    backend_paths = [
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in messages_module._iter_backend_files()
    ]
    assert backend_paths == sorted(set(backend_paths)), (
        "scanner file set must stay deterministic and duplicate-free"
    )
    assert backend_paths.count(TARGET_REL) == 1, (
        "app/versioning/integrity.py must be registered exactly once in "
        "utils.messages._iter_backend_files()"
    )
    assert len(messages_module._message_catalog()) == 537, (
        "message catalog must stay exactly 537 through the move (strings "
        f"move with the function); got {len(messages_module._message_catalog())}"
    )


# ===========================================================================
# GREEN — current behavior / invariant controls
# ===========================================================================


def test_green_1_detector_self_control():
    loaded = _target_module()
    if TARGET_PATH.exists():
        assert loaded is not None, (
            "guarded loader must return the real target module once "
            "app/versioning/integrity.py exists"
        )
    else:
        assert loaded is None, (
            "guarded loader must return None while the target file is absent"
        )


def test_green_2_canonical_owners_unchanged_against_head():
    # The scalar coercion helper was unaffected by F3 and remains protected by
    # the original UT-16 move-without-rewrite fingerprint.
    for name in FROZEN_GROUP_A_NAMES:
        current = _function_fingerprint_sha(
            ALUNO_VIEW_PATH.read_text(encoding="utf-8-sig"), name
        )
        baseline = _function_fingerprint_sha(
            _git_blob_bytes("app/views/aluno.py").decode("utf-8"), name
        )
        assert current == baseline, (
            f"app/views/aluno.py::{name} must stay unchanged through UT-16 "
            "(no rewrite incentive); the canonical owner is the app-side "
            "implementation"
        )

    # F3 intentionally changed the snapshot display helper. Protect the
    # surviving UT-16 ownership boundary structurally and its historical
    # authority behavior semantically, never by refreshing a body/hash oracle.
    aluno_source = ALUNO_VIEW_PATH.read_text(encoding="utf-8-sig")
    main_source = MAIN_PATH.read_text(encoding="utf-8-sig")
    assert F3_SNAPSHOT_DISPLAY_NAME in _top_level_defs(aluno_source)
    assert F3_SNAPSHOT_DISPLAY_NAME not in _top_level_defs(main_source)
    assert not hasattr(main, F3_SNAPSHOT_DISPLAY_NAME), (
        "Group A needs no main compatibility facade"
    )
    snapshot_display = getattr(aluno_view_module, F3_SNAPSHOT_DISPLAY_NAME)
    assert snapshot_display.__module__ == "app.views.aluno"

    aluno_tree = ast.parse(aluno_source)
    assert not any(
        isinstance(node, ast.Import)
        and any(alias.name == "main" for alias in node.names)
        for node in ast.walk(aluno_tree)
    )
    assert not any(
        isinstance(node, ast.ImportFrom) and node.module == "main"
        for node in ast.walk(aluno_tree)
    )
    display_node = next(
        node
        for node in aluno_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == F3_SNAPSHOT_DISPLAY_NAME
    )
    assert display_node.decorator_list == [], (
        "snapshot presentation helper must not acquire route/hook authority"
    )
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "execute"
        for node in ast.walk(display_node)
    ), "historical display must not query a legacy or mutable catalogue authority"

    frozen_snapshot = {
        "atividade_versao_numero": 2,
        "eixo": "AAC",
        "grupo": "3 - Congelado",
        "nome_exibivel": "Nome histórico",
        "tipo_atividade": "Acadêmica Complementar",
        "snapshot_written_at": "2026-01-01T00:00:00Z",
        "flow_origin": "student",
    }
    current_catalogue = {
        "numero_versao": 99,
        "eixo": "AEU",
        "grupo": "9 - Mutável",
    }
    display = snapshot_display(
        atividade_versao_id=10,
        regra_snapshot_json=json.dumps(frozen_snapshot),
        versao_row=current_catalogue,
    )
    assert display["snapshot_vn"] == 2
    assert display["snapshot_eixo"] == "AAC"
    assert display["snapshot_grupo"] == "3 - Congelado"
    assert display["snapshot_written_at"] == "2026-01-01T00:00:00Z"
    assert display["snapshot_flow_origin"] == "student"
    assert not {
        "AEU", "9 - Mutável", 99
    } & set(display.values())
    assert snapshot_display(
        atividade_versao_id=None,
        regra_snapshot_json=None,
        versao_row=current_catalogue,
    ) is None, "mutable current state alone is not historical authority"

    current_const = _assignment_fingerprint(
        ATC_VIEW_PATH.read_text(encoding="utf-8-sig"), GROUP_B_NAME
    )
    baseline_const = _assignment_fingerprint(
        _git_blob_bytes("app/views/admin/alunos_turmas_cursos.py").decode("utf-8"),
        GROUP_B_NAME,
    )
    assert current_const == baseline_const, (
        "app/views/admin/alunos_turmas_cursos.py::UPPER_CODE_RE must stay "
        "unchanged through UT-16"
    )


def test_green_3_non_ut16_residue_remains_expected():
    source = MAIN_PATH.read_text(encoding="utf-8-sig")
    defined = _top_level_defs(source)
    for name in NON_UT16_MAIN_DEFS:
        assert name in defined, (
            f"{name} is NOT part of UT-16 and must remain present in main.py"
        )
    assigned = _top_level_assign_names(source)
    for name in NON_UT16_MAIN_ASSIGNS:
        assert name in assigned, (
            f"{name} is NOT part of UT-16 and must remain present in main.py"
        )


def test_green_4_ut17_firewall_three_routes_unchanged():
    # UT-17 seam (TEST_CONTRACT_SEAM / LEGITIMATE_UT17_COCHANGE): state-aware
    # transition of the UT-17 firewall.  Pre-target (app/views/files.py
    # absent) the main local @app.route set is exactly the three UT-17 infra
    # routes; post-target it is exactly EMPTY (Criterion 8 final state).
    source = MAIN_PATH.read_text(encoding="utf-8-sig")
    rules = _local_route_decorators(source)
    if (PROJECT_ROOT / "app" / "views" / "files.py").exists():
        assert rules == set(), (
            "UT-17 final state: main local @app.route set must be empty "
            f"(Criterion 8); got {rules}"
        )
    else:
        assert rules == {
            "/uploads/<path:filename>",
            "/health",
            "/favicon.ico",
        }, (
            "UT-16 must not touch the UT-17 firewall: main local @app.route set "
            f"must remain exactly uploaded_file/health/favicon; got {rules}"
        )


def test_green_5_architecture_invariants():
    app = main.app
    routes = list(app.url_map.iter_rules())
    assert len(routes) == 127, f"routes must match the retired catalog surface, got {len(routes)}"
    assert len(app.view_functions) == 126, (
        f"distinct endpoints must match prod-1, got {len(app.view_functions)}"
    )
    unmapped = [
        (rule.rule, method)
        for rule in routes
        for method in (set(rule.methods or ()) & BUSINESS_METHODS)
        if str(rule.endpoint).startswith("admin")
        and get_admin_permission_requirement(rule.endpoint, method) is None
    ]
    assert unmapped == [], f"RBAC unmapped must stay 0, got {unmapped[:5]}"
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


def test_green_6_artifact_repository_custody():
    report = _authorized_csrf_snapshot_delta_report()
    assert report == "", (
        "canonical CSRF snapshots may carry only the FC-07-authorized "
        f"three-message delta: {report}"
    )
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


def test_green_7_behavioral_compat_signature_through_main():
    view = main.validar_integridade_versionamento_atividades
    assert callable(view)
    signature = inspect.signature(view)
    parameters = list(signature.parameters.items())
    assert [name for name, _ in parameters] == ["conn", "raise_on_error"], (
        "main-path behavioral consumers (test_activity_versioning_phase_b_"
        "schema.py) must keep the exact call shape"
    )
    assert parameters[1][1].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters[1][1].default is True


def test_green_8_red_file_adds_no_database_initialization_caller():
    needle = "init" + "_db"
    source = Path(__file__).read_text(encoding="utf-8")
    assert needle not in source, (
        "UT-16 RED must not introduce a database-initialization caller: the "
        "Phase3 caller manifest must stay at 76"
    )
