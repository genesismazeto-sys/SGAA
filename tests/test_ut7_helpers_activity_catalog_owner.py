"""UT-7 RED — helpers ``matrizes`` -> ``app.activity_catalog``.

RED-only mission: the canonical owner move is NOT yet implemented.  This module
freezes the future architecture contract so that it fails ONLY on the
ownership/import-direction assertions, while the behavior baseline (frozen from
the current accepted helpers) stays GREEN.  Mixed discrimination is intended:

    behavior baseline  = GREEN  (proves current behavior is the reference)
    architecture       = RED    (proves the owner move does not exist yet)

Contract targets:

  A. CANONICAL OWNER — ``app.activity_catalog`` must define both helpers as
     top-level functions.  Currently FAILS: they are defined in
     ``app.views.admin.atividades``.

  B. OLD OWNER IS FACADE — ``app.views.admin.atividades`` must not define them
     (it may only import/re-export).  Currently FAILS: both local defs exist.

  C. MATRIZES EDGE REMOVED — ``app.views.admin.matrizes`` must import neither
     helper from ``app.views.admin.atividades``.  Currently FAILS: line 36
     imports both.

  D. MATRIZES CONSUMES CANONICAL OWNER — ``app.views.admin.matrizes`` must
     import both helpers from ``app.activity_catalog``.  Currently FAILS.

  E. FACADE / IDENTITY — after the move:
       views._build_grupo_label  is catalog._build_grupo_label
       views._canonicalize_tipo_limitacao is catalog._canonicalize_tipo_limitacao
       main._build_grupo_label   is catalog._build_grupo_label
       main._canonicalize_tipo_limitacao is catalog._canonicalize_tipo_limitacao
     All lookups are getattr-guarded with a sentinel so the absent canonical
     attributes produce a normal assertion failure, never AttributeError.

  F. BEHAVIOR PRESERVATION — a frozen expected-value table based on measured
     current behavior.  Must PASS at RED time against the existing
     atividades-owned helpers.

No production file is modified, no existing test is modified, and the module
never relies on ImportError / AttributeError / collection failure.
"""
from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = PROJECT_ROOT / "app" / "activity_catalog.py"
VIEW_PATH = PROJECT_ROOT / "app" / "views" / "admin" / "atividades.py"
MATRIZES_PATH = PROJECT_ROOT / "app" / "views" / "admin" / "matrizes.py"

TARGET_HELPERS = frozenset({"_build_grupo_label", "_canonicalize_tipo_limitacao"})

_MISSING = object()


# ---------------------------------------------------------------------------
# Minimal AST detectors (module-level, reusable for self-control)
# ---------------------------------------------------------------------------


def _top_level_functions(tree: ast.Module) -> set[str]:
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _imports_from(tree: ast.Module, module_name: str) -> set[str]:
    return {
        alias.asname or alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == module_name
        for alias in node.names
    }


def _file_tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))


# ---------------------------------------------------------------------------
# Self-control: prove the detectors distinguish the shapes they must see
# ---------------------------------------------------------------------------


def test_detector_self_controls_distinguish_def_and_import_forms():
    source = """\
def top_level():
    def nested():
        pass

from app.activity_catalog import get_atividade_base, _build_grupo_label as alias_label
from app.views.admin.atividades import _build_grupo_label
"""
    tree = ast.parse(source, filename="<self-control>")

    top = _top_level_functions(tree)
    assert top == {"top_level"}, "nested def must not be reported as top-level"

    catalog_imports = _imports_from(tree, "app.activity_catalog")
    atividades_imports = _imports_from(tree, "app.views.admin.atividades")
    assert catalog_imports == {"get_atividade_base", "alias_label"}
    assert atividades_imports == {"_build_grupo_label"}
    assert catalog_imports != atividades_imports


# ---------------------------------------------------------------------------
# A. Canonical owner — app.activity_catalog (RED until implemented)
# ---------------------------------------------------------------------------


def test_canonical_owner_activity_catalog_defines_both_helpers():
    defined = _top_level_functions(_file_tree(CATALOG_PATH))
    missing = sorted(TARGET_HELPERS - defined)
    assert not missing, (
        "app.activity_catalog must define (top-level): %s; missing: %s"
        % (", ".join(sorted(TARGET_HELPERS)), ", ".join(missing))
    )


# ---------------------------------------------------------------------------
# B. Old owner is a facade, not the definition owner (RED until implemented)
# ---------------------------------------------------------------------------


def test_old_owner_atividades_is_facade_not_definition_owner():
    defined = _top_level_functions(_file_tree(VIEW_PATH))
    still_local = sorted(TARGET_HELPERS & defined)
    assert not still_local, (
        "app.views.admin.atividades must not define (top-level): %s; "
        "still defined locally: %s" % (", ".join(sorted(TARGET_HELPERS)), ", ".join(still_local))
    )


# ---------------------------------------------------------------------------
# C. Matrizes no longer imports the helpers from atividades (RED)
# ---------------------------------------------------------------------------


def test_matrizes_has_no_import_edge_to_atividades_for_helpers():
    from_atividades = _imports_from(_file_tree(MATRIZES_PATH), "app.views.admin.atividades")
    imported = sorted(from_atividades & TARGET_HELPERS)
    assert not imported, (
        "app.views.admin.matrizes must not import these helpers from "
        "app.views.admin.atividades; still imported: %s" % ", ".join(imported)
    )


# ---------------------------------------------------------------------------
# D. Matrizes consumes the canonical owner (RED)
# ---------------------------------------------------------------------------


def test_matrizes_imports_both_helpers_from_canonical_owner():
    from_catalog = _imports_from(_file_tree(MATRIZES_PATH), "app.activity_catalog")
    missing = sorted(TARGET_HELPERS - from_catalog)
    assert not missing, (
        "app.views.admin.matrizes must import from app.activity_catalog: %s; "
        "missing: %s" % (", ".join(sorted(TARGET_HELPERS)), ", ".join(missing))
    )


# ---------------------------------------------------------------------------
# E. Facade / identity contract (getattr-guarded; RED)
# ---------------------------------------------------------------------------


def test_facade_and_main_reexports_resolve_canonical_identity():
    import main
    from app import activity_catalog as catalog
    from app.views.admin import atividades as views

    for name in sorted(TARGET_HELPERS):
        canonical = getattr(catalog, name, _MISSING)
        views_attr = getattr(views, name, _MISSING)
        main_attr = getattr(main, name, _MISSING)

        assert canonical is not _MISSING, (
            "%s must be defined by app.activity_catalog (canonical owner)" % name
        )
        assert views_attr is not _MISSING, (
            "app.views.admin.atividades must expose %s (facade re-export)" % name
        )
        assert main_attr is not _MISSING, "main must expose %s (re-export)" % name
        assert views_attr is canonical, (
            "app.views.admin.atividades.%s must be the canonical identity" % name
        )
        assert main_attr is canonical, "main.%s must be the canonical identity" % name


# ---------------------------------------------------------------------------
# F. Behavior baseline — frozen from measured current behavior (must stay GREEN)
# ---------------------------------------------------------------------------


def test_behavior_baseline_build_grupo_label_frozen_table():
    from app.views.admin.atividades import _build_grupo_label as build_grupo_label

    cases = [
        ("7", "Grupo Novo", "7 - Grupo Novo"),
        ("7", "", "7"),
        (None, None, ""),
        (7, " Grupo ", "7 - Grupo"),
    ]
    for numero, descricao, expected in cases:
        assert build_grupo_label(numero, descricao) == expected, (numero, descricao)


def test_behavior_baseline_canonicalize_tipo_limitacao_frozen_table():
    from app.views.admin.atividades import _canonicalize_tipo_limitacao as canonicalize_tipo_limitacao

    # NOTE: " total_ " is measured as None (normalize_header collapses
    # whitespace first, then replace("_", " ") leaves a trailing space).
    cases = [
        ("total", "total"),
        ("TOTAL", "total"),
        (" total_ ", None),
        (" total ", "total"),
        ("  TOTAL  ", "total"),
        ("semestral", "semestral"),
        ("Semestral", "semestral"),
        (" semestral ", "semestral"),
        ("SEMESTRAL ", "semestral"),
        ("", None),
        (None, None),
        ("tudo", None),
        (123, None),
    ]
    for value, expected in cases:
        assert canonicalize_tipo_limitacao(value) == expected, value
