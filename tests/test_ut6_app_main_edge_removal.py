"""UT-6 — RED contracts for the removal of the app -> main reverse dependency cycle.

Entry-state architecture (the defect this file freezes as RED):

    E1  app/views/core.py     -> main   (lazy ``import main``)
    E2  app/views/aluno.py    -> main   (lazy ``import main``)
    E3  utils/messages.py     -> main   (``sys.modules.get("main")`` + attribute access)

Required transition:

    architectural reverse dependencies : 3 -> 0
    literal ``main`` import edges      : 2 -> 0

This module contains NO production implementation. Every future-state assertion is
built defensively so that pytest can always *collect* the file: missing future
modules/attributes fail at assertion time, never at import time.
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Packages that must never depend on the ``main`` module.
SCANNED_PACKAGES = ("app", "services", "utils")

# Roots that count as first-party for the app/web/urls.py purity contract.
FIRST_PARTY_ROOTS = frozenset({"app", "main", "services", "utils"})

# Mechanisms that constitute a *literal* ``main`` import edge (contract §18).
LITERAL_IMPORT_MECHANISMS = frozenset(
    {
        "import main",
        "from main import",
    }
)

MESSAGE_KEY = "msg_b340e19ed2686d57"
MESSAGE_DEFAULT_TEXT = "Houve atualizações nas suas solicitações."
MESSAGE_CATALOG_SIZE = 536

FUTURE_URLS_MODULE = "app.web.urls"
FUTURE_REQUISITIONS_MODULE = "app.requisitions"


# ---------------------------------------------------------------------------
# CONTRACT A — structural main-dependency detector
# ---------------------------------------------------------------------------


def _is_main_module_name(name: str) -> bool:
    """True for the root ``main`` module or any of its submodules."""
    return name == "main" or name.startswith("main.")


def _is_main_literal(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and _is_main_module_name(node.value)
    )


class MainDependencyVisitor(ast.NodeVisitor):
    """Detect statically resolvable executable dependencies on the ``main`` module.

    Recognised mechanisms:

    1.  ``import main``                     8.  ``sys.modules.pop("main", ...)``
    2.  ``import main.sub``                 9.  ``"main" in sys.modules``
    3.  ``from main import x``             10.  ``importlib.import_module("main")``
    4.  ``from main.sub import x``         11.  aliased/bare ``import_module("main")``
    5.  ``sys.modules["main"]``            12.  ``__import__("main")``
    6.  ``sys.modules.get("main")``        13.  ``getattr(<main value>, ...)``
    7.  ``sys.modules.setdefault("main")`` 14.  ``<main value>.attr``

    Straightforward aliasing is tracked (``import sys as _sys``,
    ``from sys import modules``, ``import importlib as il``,
    ``from importlib import import_module as im``) together with variables assigned
    from a detected main-module resolver.  Arbitrary dataflow is explicitly out of
    scope; only statically resolvable forms are covered.
    """

    _DICT_LOOKUP_METHODS = frozenset({"get", "setdefault", "pop"})

    def __init__(self, rel_path: str) -> None:
        self.rel_path = rel_path
        self.findings: list[dict[str, object]] = []
        self.sys_aliases: set[str] = set()
        self.sys_modules_aliases: set[str] = set()
        self.importlib_aliases: set[str] = set()
        self.import_module_aliases: set[str] = set()
        # Names statically bound to the ``main`` module object.
        self.main_values: set[str] = set()

    # -- recording ---------------------------------------------------------

    def _record(self, node: ast.AST, mechanism: str) -> None:
        self.findings.append(
            {
                "path": self.rel_path,
                "line": getattr(node, "lineno", 0),
                "mechanism": mechanism,
            }
        )

    # -- static resolvers --------------------------------------------------

    def _is_sys_modules(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Attribute) and node.attr == "modules":
            return isinstance(node.value, ast.Name) and node.value.id in self.sys_aliases
        return isinstance(node, ast.Name) and node.id in self.sys_modules_aliases

    def _is_import_module_callable(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Attribute) and node.attr == "import_module":
            return isinstance(node.value, ast.Name) and node.value.id in self.importlib_aliases
        if isinstance(node, ast.Name):
            return node.id in self.import_module_aliases or node.id == "import_module"
        return False

    def _resolver_mechanism(self, node: ast.AST) -> str | None:
        """Mechanism string when ``node`` *resolves* the main module, else None."""
        if isinstance(node, ast.Subscript) and self._is_sys_modules(node.value):
            if _is_main_literal(node.slice):
                return 'sys.modules["main"]'
            return None

        if isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr in self._DICT_LOOKUP_METHODS
                and self._is_sys_modules(func.value)
                and node.args
                and _is_main_literal(node.args[0])
            ):
                return f'sys.modules.{func.attr}("main")'
            if (
                self._is_import_module_callable(func)
                and node.args
                and _is_main_literal(node.args[0])
            ):
                return 'importlib.import_module("main")'
            if (
                isinstance(func, ast.Name)
                and func.id == "__import__"
                and node.args
                and _is_main_literal(node.args[0])
            ):
                return '__import__("main")'
        return None

    def _main_value_mechanism(self, node: ast.AST) -> str | None:
        """Mechanism when ``node`` *evaluates to* the main module, else None."""
        resolver = self._resolver_mechanism(node)
        if resolver is not None:
            return resolver
        if isinstance(node, ast.Name) and node.id in self.main_values:
            return f"main-module value `{node.id}`"
        return None

    # -- imports -----------------------------------------------------------

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if _is_main_module_name(alias.name):
                self._record(node, "import main")
                self.main_values.add(alias.asname or alias.name.split(".")[0])
            elif alias.name == "sys":
                self.sys_aliases.add(alias.asname or "sys")
            elif alias.name == "importlib" or alias.name.startswith("importlib."):
                if alias.asname and alias.name == "importlib":
                    self.importlib_aliases.add(alias.asname)
                elif not alias.asname:
                    self.importlib_aliases.add("importlib")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        if node.level == 0 and _is_main_module_name(module):
            self._record(node, "from main import")
        elif node.level == 0 and module == "sys":
            for alias in node.names:
                if alias.name == "modules":
                    self.sys_modules_aliases.add(alias.asname or "modules")
        elif node.level == 0 and module == "importlib":
            for alias in node.names:
                if alias.name == "import_module":
                    self.import_module_aliases.add(alias.asname or "import_module")
        self.generic_visit(node)

    # -- resolution / usage sites -----------------------------------------

    def visit_Subscript(self, node: ast.Subscript) -> None:
        self.generic_visit(node)
        mechanism = self._resolver_mechanism(node)
        if mechanism is not None:
            self._record(node, mechanism)

    def visit_Call(self, node: ast.Call) -> None:
        self.generic_visit(node)
        mechanism = self._resolver_mechanism(node)
        if mechanism is not None:
            self._record(node, mechanism)
            return
        if isinstance(node.func, ast.Name) and node.func.id == "getattr" and node.args:
            target = self._main_value_mechanism(node.args[0])
            if target is not None:
                self._record(node, f"getattr on {target}")

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self.generic_visit(node)
        target = self._main_value_mechanism(node.value)
        if target is not None:
            self._record(node, f"attribute access `.{node.attr}` on {target}")

    def visit_Compare(self, node: ast.Compare) -> None:
        self.generic_visit(node)
        for operator, comparator in zip(node.ops, node.comparators):
            if isinstance(operator, (ast.In, ast.NotIn)) and self._is_sys_modules(comparator):
                if _is_main_literal(node.left):
                    verb = "in" if isinstance(operator, ast.In) else "not in"
                    self._record(node, f'"main" {verb} sys.modules')

    # -- binding propagation ----------------------------------------------

    def _bind(self, target: ast.AST, mechanism: str | None) -> None:
        if not isinstance(target, ast.Name):
            return
        if mechanism is not None:
            self.main_values.add(target.id)
        else:
            self.main_values.discard(target.id)

    def visit_Assign(self, node: ast.Assign) -> None:
        self.generic_visit(node)
        mechanism = self._main_value_mechanism(node.value)
        for target in node.targets:
            self._bind(target, mechanism)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self.generic_visit(node)
        mechanism = self._main_value_mechanism(node.value) if node.value is not None else None
        self._bind(node.target, mechanism)

    def _visit_scope_definition(self, node: ast.AST) -> None:
        name = getattr(node, "name", None)
        if isinstance(name, str):
            # A local definition named ``main`` shadows any module binding.
            self.main_values.discard(name)
        self.generic_visit(node)

    visit_FunctionDef = _visit_scope_definition
    visit_AsyncFunctionDef = _visit_scope_definition
    visit_ClassDef = _visit_scope_definition


def scan_source(source: str, rel_path: str) -> list[dict[str, object]]:
    """Run the detector over a source string."""
    tree = ast.parse(source, filename=rel_path)
    visitor = MainDependencyVisitor(rel_path)
    visitor.visit(tree)
    return visitor.findings


def _read_source(path: Path) -> str:
    # At least one production file carries a UTF-8 BOM
    # (app/services/google_drive_service.py).
    return path.read_text(encoding="utf-8-sig")


def iter_scanned_files() -> list[Path]:
    files: list[Path] = []
    for package in SCANNED_PACKAGES:
        package_dir = PROJECT_ROOT / package
        if not package_dir.is_dir():
            continue
        for path in sorted(package_dir.rglob("*.py")):
            relative = path.relative_to(PROJECT_ROOT)
            if "__pycache__" in relative.parts:
                continue
            files.append(path)
    return files


def scan_production_tree() -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for path in iter_scanned_files():
        rel_path = path.relative_to(PROJECT_ROOT).as_posix()
        findings.extend(scan_source(_read_source(path), rel_path))
    return findings


def scan_function(path: Path, function_name: str) -> list[dict[str, object]]:
    """Detector findings whose line falls inside ``function_name`` of ``path``."""
    rel_path = path.relative_to(PROJECT_ROOT).as_posix()
    source = _read_source(path)
    tree = ast.parse(source, filename=rel_path)

    target: ast.AST | None = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            target = node
            break
    assert target is not None, f"{rel_path} does not define {function_name}()"

    start = target.lineno
    end = getattr(target, "end_lineno", start)
    return [
        finding
        for finding in scan_source(source, rel_path)
        if start <= int(finding["line"]) <= end
    ]


def format_findings(findings: list[dict[str, object]]) -> str:
    if not findings:
        return "<none>"
    return "\n".join(
        f"  {finding['path']}:{finding['line']}: {finding['mechanism']}" for finding in findings
    )


def literal_import_findings(findings: list[dict[str, object]]) -> list[dict[str, object]]:
    return [finding for finding in findings if finding["mechanism"] in LITERAL_IMPORT_MECHANISMS]


# ---------------------------------------------------------------------------
# CONTRACT A — detector self-discrimination (synthetic controls)
# ---------------------------------------------------------------------------

POSITIVE_CONTROLS: list[tuple[str, str]] = [
    ("import main", "import main\n"),
    ("import main submodule", "import main.helpers\n"),
    ("from main import", "from main import get_db_connection\n"),
    ("from main submodule import", "from main.helpers import thing\n"),
    ("aliased import main", "import main as _main\n"),
    ("sys.modules subscript", 'import sys\nvalue = sys.modules["main"]\n'),
    ("sys.modules.get", 'import sys\nvalue = sys.modules.get("main")\n'),
    ("sys.modules.setdefault", 'import sys\nsys.modules.setdefault("main", None)\n'),
    ("sys.modules.pop", 'import sys\nsys.modules.pop("main", None)\n'),
    ("membership in sys.modules", 'import sys\nflag = "main" in sys.modules\n'),
    ("membership not in sys.modules", 'import sys\nflag = "main" not in sys.modules\n'),
    (
        "aliased sys membership",
        'import sys as _sys\nflag = "main" in _sys.modules\n',
    ),
    (
        "from sys import modules",
        'from sys import modules\nvalue = modules.get("main")\n',
    ),
    (
        "importlib.import_module",
        'import importlib\nvalue = importlib.import_module("main")\n',
    ),
    (
        "aliased importlib.import_module",
        'import importlib as il\nvalue = il.import_module("main")\n',
    ),
    (
        "bare import_module",
        'from importlib import import_module\nvalue = import_module("main")\n',
    ),
    (
        "aliased bare import_module",
        'from importlib import import_module as im\nvalue = im("main")\n',
    ),
    ("dunder import", '__import__("main")\n'),
    (
        "attribute access on resolved value",
        'import sys\nresolved = sys.modules.get("main")\nfn = resolved.get_db_connection\n',
    ),
    (
        "getattr on resolved value",
        'import sys\n'
        'resolved = sys.modules.get("main")\n'
        'fn = getattr(resolved, "get_db_connection")\n',
    ),
]

NEGATIVE_CONTROL_SOURCE = '''"""Module docstring that mentions import main and from main import x."""

import logging
import sys

# A comment that mentions import main and sys.modules["main"] on purpose.

logging.getLogger("main")
logger = logging.getLogger("main")
text = "main"
other = {"main": 1}
paths = ["main.py"]


def main():
    """Entry point named main; not the main module."""
    return 0


def run():
    logging.getLogger("main").info("main")
    if text == "main":
        return main()
    return None


class Runner:
    name = "main"

    def main(self):
        return logging.getLogger("main")


if text == "never":
    raise SystemExit(main())
'''

# Exact shapes of the three entry-state edges, replicated synthetically so the
# detector keeps proving it can see them after production is fixed.
ENTRY_EDGE_SHAPES: list[tuple[str, str]] = [
    (
        "E1/E2 lazy import main helper",
        "def _get_main_helpers():\n"
        "    import main  # type: ignore\n"
        "\n"
        "    return {\n"
        '        "aluno_url": main.aluno_url,\n'
        '        "get_db_connection": main.get_db_connection,\n'
        '        "logger": main.logger,\n'
        "    }\n",
    ),
    (
        "E3 sys.modules.get bridge",
        "import sys\n"
        "\n"
        "def _connection():\n"
        '    main_module = sys.modules.get("main")\n'
        '    if main_module is not None and hasattr(main_module, "get_db_connection"):\n'
        "        return main_module.get_db_connection()\n"
        "    return None\n",
    ),
]


@pytest.mark.parametrize("label,source", POSITIVE_CONTROLS, ids=[c[0] for c in POSITIVE_CONTROLS])
def test_contract_a_detector_positive_controls(label: str, source: str) -> None:
    """Synthetic positive controls: every listed mechanism must be detected."""
    findings = scan_source(source, f"<positive:{label}>")
    assert findings, f"detector missed positive control {label!r}:\n{source}"
    for finding in findings:
        assert finding["mechanism"], f"empty mechanism for {label!r}"
        assert int(finding["line"]) >= 1, f"missing line for {label!r}"


def test_contract_a_detector_negative_controls() -> None:
    """Synthetic negative controls: none of these are architectural dependencies."""
    findings = scan_source(NEGATIVE_CONTROL_SOURCE, "<negative>")
    assert findings == [], (
        "detector produced false positives on the negative control:\n"
        + format_findings(findings)
    )


@pytest.mark.parametrize(
    "label,source", ENTRY_EDGE_SHAPES, ids=[shape[0] for shape in ENTRY_EDGE_SHAPES]
)
def test_contract_a_detector_recognises_entry_edge_shapes(label: str, source: str) -> None:
    """The detector must discriminate the exact E1/E2/E3 shapes, including E3."""
    findings = scan_source(source, f"<entry-shape:{label}>")
    assert findings, f"detector failed to recognise entry edge shape {label!r}"


def test_contract_a_detector_does_not_flag_the_logging_channel_named_main() -> None:
    """``logging.getLogger("main")`` is a logging channel name, not a module edge."""
    findings = scan_source(
        'import logging\nlogger = logging.getLogger("main")\nlogger.info("main")\n',
        "<logging-channel>",
    )
    assert findings == [], (
        "detector wrongly rejected the logging channel name:\n" + format_findings(findings)
    )


def test_contract_a_production_tree_has_no_main_dependency() -> None:
    """RED: app/, services/ and utils/ must not depend on the ``main`` module."""
    findings = scan_production_tree()
    assert findings == [], (
        "architectural reverse dependencies on `main` (path:line: mechanism):\n"
        + format_findings(findings)
        + f"\n\nfiles: {sorted({str(f['path']) for f in findings})}"
    )


def test_contract_a_production_tree_has_no_literal_main_import() -> None:
    """RED: no literal ``import main`` / ``from main import`` edge may survive."""
    findings = literal_import_findings(scan_production_tree())
    assert findings == [], (
        "literal `main` import edges (path:line: mechanism):\n" + format_findings(findings)
    )


# ---------------------------------------------------------------------------
# CONTRACT B — cold import purity
# ---------------------------------------------------------------------------


def _run_isolated(code: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["APP_DATABASE"] = str(tmp_path / "ut6_isolated.db")
    environment.setdefault("APP_ENV", "testing")
    environment.setdefault("DISABLE_CSRF", "1")
    environment.setdefault(
        "APP_SECRET_KEY",
        "test-secret-key-for-pytest-only-do-not-use-anywhere-else-1234567890",
    )
    return subprocess.run(
        [sys.executable, "-B", "-c", code],
        cwd=str(PROJECT_ROOT),
        env=environment,
        capture_output=True,
        text=True,
    )


_COLD_IMPORT_TEMPLATE = (
    "import sys; "
    "assert 'main' not in sys.modules, 'main preloaded before cold import'; "
    "import importlib; "
    "[importlib.import_module(name) for name in {modules!r}]; "
    "assert 'main' not in sys.modules, 'importing the modules loaded main'"
)

CURRENT_COLD_IMPORT_MODULES = [
    "app.requisitions",
    "app.views.core",
    "app.views.aluno",
    "utils.messages",
]

FUTURE_COLD_IMPORT_MODULES = ["app.web.urls"] + CURRENT_COLD_IMPORT_MODULES


def test_contract_b_cold_import_of_current_modules_does_not_load_main(tmp_path: Path) -> None:
    """GREEN control: today's lazy imports already keep ``main`` out of sys.modules."""
    result = _run_isolated(
        _COLD_IMPORT_TEMPLATE.format(modules=CURRENT_COLD_IMPORT_MODULES), tmp_path
    )
    assert result.returncode == 0, result.stderr


def test_contract_b_cold_import_of_future_modules_does_not_load_main(tmp_path: Path) -> None:
    """RED: the future ``app.web.urls`` owner must import cleanly without ``main``."""
    result = _run_isolated(
        _COLD_IMPORT_TEMPLATE.format(modules=FUTURE_COLD_IMPORT_MODULES), tmp_path
    )
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# CONTRACT C — future compatibility identities
# ---------------------------------------------------------------------------


def _optional_module(name: str):
    """Import ``name`` without breaking collection when it does not exist yet."""
    try:
        return importlib.import_module(name)
    except Exception as exc:  # pragma: no cover - defensive, reported at assert time
        return exc


def _require_module(name: str):
    module = _optional_module(name)
    assert not isinstance(module, BaseException), f"{name} is not importable yet: {module!r}"
    return module


_MISSING = object()


def _attr(module: object, name: str) -> object:
    return getattr(module, name, _MISSING)


IDENTITY_CONTRACTS: list[tuple[str, str, str]] = [
    (FUTURE_URLS_MODULE, "aluno_url", "C"),
    (FUTURE_URLS_MODULE, "USE_ALUNO_BLUEPRINT", "C"),
    (FUTURE_REQUISITIONS_MODULE, "get_student_request_update_alert", "C"),
    (FUTURE_REQUISITIONS_MODULE, "mark_student_request_updates_seen", "C"),
    (FUTURE_REQUISITIONS_MODULE, "AUTO_ALERT_YELLOW_BG", "C"),
    (FUTURE_REQUISITIONS_MODULE, "AUTO_ALERT_YELLOW_BORDER", "C"),
]


@pytest.mark.parametrize(
    "module_name,symbol",
    [(module_name, symbol) for module_name, symbol, _ in IDENTITY_CONTRACTS],
    ids=[f"{module_name}:{symbol}" for module_name, symbol, _ in IDENTITY_CONTRACTS],
)
def test_contract_c_main_reexports_are_identical_to_the_future_owner(
    module_name: str, symbol: str
) -> None:
    """RED: ``main.<symbol>`` must be the *same object* exposed by the new owner."""
    main = _require_module("main")
    owner = _require_module(module_name)

    owned = _attr(owner, symbol)
    assert owned is not _MISSING, f"{module_name} does not expose {symbol} yet"

    exported = _attr(main, symbol)
    assert exported is not _MISSING, f"main no longer exposes {symbol}"

    assert exported is owned, (
        f"main.{symbol} is not the object owned by {module_name}.{symbol} "
        f"({exported!r} is not {owned!r})"
    )


def test_contract_c_auto_alert_colour_values_are_preserved() -> None:
    """RED: the moved colour constants must keep their canonical values."""
    owner = _require_module(FUTURE_REQUISITIONS_MODULE)
    assert _attr(owner, "AUTO_ALERT_YELLOW_BG") == "#fef4c0"
    assert _attr(owner, "AUTO_ALERT_YELLOW_BORDER") == "#c9a227"


# ---------------------------------------------------------------------------
# CONTRACT C2 — body ownership
# ---------------------------------------------------------------------------


def top_level_owned_names(path: Path) -> set[str]:
    """Top-level definitions/assignments — imports and re-exports are NOT ownership."""
    tree = ast.parse(_read_source(path), filename=path.name)
    owned: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            owned.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    owned.add(target.id)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.value is not None:
                owned.add(node.target.id)
    return owned


OWNERSHIP_CONTRACTS: list[tuple[str, str]] = [
    ("app/web/urls.py", "USE_ALUNO_BLUEPRINT"),
    ("app/web/urls.py", "aluno_url"),
    ("app/requisitions.py", "get_student_request_update_alert"),
    ("app/requisitions.py", "mark_student_request_updates_seen"),
    ("app/requisitions.py", "AUTO_ALERT_YELLOW_BG"),
    ("app/requisitions.py", "AUTO_ALERT_YELLOW_BORDER"),
]

MOVED_SYMBOLS = sorted({symbol for _, symbol in OWNERSHIP_CONTRACTS})


@pytest.mark.parametrize(
    "rel_path,symbol", OWNERSHIP_CONTRACTS, ids=[f"{p}:{s}" for p, s in OWNERSHIP_CONTRACTS]
)
def test_contract_c2_future_owner_holds_the_body(rel_path: str, symbol: str) -> None:
    """RED: the new module must physically own the definition, not re-export it."""
    path = PROJECT_ROOT / rel_path
    assert path.is_file(), f"{rel_path} does not exist yet"
    assert symbol in top_level_owned_names(path), (
        f"{rel_path} does not own a top-level definition/assignment for {symbol}"
    )


@pytest.mark.parametrize("symbol", MOVED_SYMBOLS)
def test_contract_c2_main_no_longer_owns_the_moved_symbol(symbol: str) -> None:
    """RED: main.py may re-export the moved symbols but must not define them."""
    owned = top_level_owned_names(PROJECT_ROOT / "main.py")
    assert symbol not in owned, (
        f"main.py still owns a top-level definition/assignment for {symbol}"
    )


def test_contract_c2_future_urls_module_has_no_first_party_import() -> None:
    """RED: app/web/urls.py must be a leaf — no first-party import dependency."""
    path = PROJECT_ROOT / "app" / "web" / "urls.py"
    assert path.is_file(), "app/web/urls.py does not exist yet"

    tree = ast.parse(_read_source(path), filename="app/web/urls.py")
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in FIRST_PARTY_ROOTS:
                    offenders.append(f"line {node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                offenders.append(f"line {node.lineno}: relative import (level {node.level})")
            elif (node.module or "").split(".")[0] in FIRST_PARTY_ROOTS:
                offenders.append(f"line {node.lineno}: from {node.module} import ...")
    assert offenders == [], "app/web/urls.py has first-party imports:\n" + "\n".join(offenders)


# ---------------------------------------------------------------------------
# CONTRACT D — app/views/core.py helper
# ---------------------------------------------------------------------------

CORE_HELPER_KEYS = {
    "aluno_url",
    "get_db_connection",
    "logger",
}


def test_contract_d_core_helper_key_contract_is_preserved() -> None:
    """Preservation control: the helper key set must never drift."""
    core_views = _require_module("app.views.core")
    helpers = core_views._get_main_helpers()
    assert set(helpers) == CORE_HELPER_KEYS


def test_contract_d_core_helper_has_no_main_dependency() -> None:
    """RED: app/views/core.py::_get_main_helpers must not depend on ``main``."""
    findings = scan_function(PROJECT_ROOT / "app" / "views" / "core.py", "_get_main_helpers")
    assert findings == [], (
        "app/views/core.py::_get_main_helpers still depends on `main`:\n"
        + format_findings(findings)
    )


def test_contract_d_core_module_exposes_the_main_logging_channel() -> None:
    """RED: core must own a module-level logger bound to the "main" channel name."""
    core_views = _require_module("app.views.core")
    logger = _attr(core_views, "logger")
    assert logger is not _MISSING, "app/views/core.py does not expose a module-level `logger`"
    assert logger is logging.getLogger("main")
    assert logger.name == "main"


# ---------------------------------------------------------------------------
# CONTRACT E — app/views/aluno.py helper
# ---------------------------------------------------------------------------

ALUNO_HELPER_KEYS = {
    "get_student_request_update_alert",
    "mark_student_request_updates_seen",
}


def test_contract_e_aluno_helper_key_contract_is_preserved() -> None:
    """Preservation control: the helper key set must never drift."""
    aluno_views = _require_module("app.views.aluno")
    helpers = aluno_views._get_main_helpers()
    assert set(helpers) == ALUNO_HELPER_KEYS


def test_contract_e_aluno_helper_has_no_main_dependency() -> None:
    """RED: app/views/aluno.py::_get_main_helpers must not depend on ``main``."""
    findings = scan_function(PROJECT_ROOT / "app" / "views" / "aluno.py", "_get_main_helpers")
    assert findings == [], (
        "app/views/aluno.py::_get_main_helpers still depends on `main`:\n"
        + format_findings(findings)
    )


# ---------------------------------------------------------------------------
# CONTRACT F — aluno_url parity
# ---------------------------------------------------------------------------

ALUNO_URL_BEHAVIOUR_CONTROL = "tests/test_aluno_compat_exports.py"


def test_contract_f_aluno_url_behaviour_control_remains_the_canonical_owner() -> None:
    """The existing green control keeps owning aluno_url behaviour; do not duplicate it."""
    control = PROJECT_ROOT / ALUNO_URL_BEHAVIOUR_CONTROL
    assert control.is_file(), f"missing canonical behaviour control {ALUNO_URL_BEHAVIOUR_CONTROL}"
    assert "aluno_url" in control.read_text(encoding="utf-8-sig")


def test_contract_f_aluno_url_resolution_still_uses_the_blueprint_flag() -> None:
    """RED: the moved aluno_url must read the flag owned by app/web/urls.py."""
    urls = _require_module(FUTURE_URLS_MODULE)
    aluno_url = _attr(urls, "aluno_url")
    assert callable(aluno_url), f"{FUTURE_URLS_MODULE}.aluno_url is not callable"

    use_blueprint = _attr(urls, "USE_ALUNO_BLUEPRINT")
    assert use_blueprint is True, (
        f"{FUTURE_URLS_MODULE}.USE_ALUNO_BLUEPRINT must preserve the canonical value True"
    )

    main = _require_module("main")
    app = _attr(main, "app")
    assert app is not _MISSING, "main.app is unavailable"
    with app.test_request_context():
        assert aluno_url("aluno_minhas_requisicoes") == _attr(main, "aluno_url")(
            "aluno_minhas_requisicoes"
        )


# ---------------------------------------------------------------------------
# CONTRACT G — student alert parity (ownership/identity only)
# ---------------------------------------------------------------------------

ALERT_BEHAVIOUR_CONTROLS = (
    "tests/test_aluno_requisicao_update_alert.py",
    "tests/test_admin_dashboard_request_alert.py",
)


@pytest.mark.parametrize("rel_path", ALERT_BEHAVIOUR_CONTROLS)
def test_contract_g_alert_behaviour_controls_remain_authoritative(rel_path: str) -> None:
    """The existing end-to-end alert suites stay authoritative; do not duplicate them."""
    control = PROJECT_ROOT / rel_path
    assert control.is_file(), f"missing canonical alert behaviour control {rel_path}"


def test_contract_g_alert_message_text_is_unchanged_after_the_move() -> None:
    """RED: the moved alert builder must keep the exact message literal."""
    path = PROJECT_ROOT / "app" / "requisitions.py"
    assert path.is_file(), "app/requisitions.py does not exist"
    source = _read_source(path)
    assert MESSAGE_DEFAULT_TEXT in source, (
        "app/requisitions.py does not own the alert message literal "
        f"{MESSAGE_DEFAULT_TEXT!r}"
    )


def test_contract_g_alert_helpers_are_owned_by_requisitions() -> None:
    """RED: both alert helpers must be reachable from the new owner module."""
    owner = _require_module(FUTURE_REQUISITIONS_MODULE)
    for symbol in ("get_student_request_update_alert", "mark_student_request_updates_seen"):
        assert callable(_attr(owner, symbol)), (
            f"{FUTURE_REQUISITIONS_MODULE}.{symbol} is not available yet"
        )


# ---------------------------------------------------------------------------
# CONTRACT H — message catalog future owner
# ---------------------------------------------------------------------------


def _messages_module():
    return _require_module("utils.messages")


def _backend_relative_paths() -> list[str]:
    messages = _messages_module()
    root = Path(messages.PROJECT_ROOT)
    return [path.relative_to(root).as_posix() for path in messages._iter_backend_files()]


def _catalog_entry() -> dict:
    catalog = _messages_module()._message_catalog()
    entry = catalog.get(MESSAGE_KEY)
    assert entry is not None, f"catalog key {MESSAGE_KEY} is missing"
    return entry


def test_contract_h_catalog_size_is_preserved() -> None:
    """GREEN control: moving the sink must not change the catalog size."""
    assert len(_messages_module()._message_catalog()) == MESSAGE_CATALOG_SIZE


def test_contract_h_catalog_entry_default_text_is_preserved() -> None:
    """GREEN control: the message literal must not drift."""
    assert _catalog_entry()["default_text"] == MESSAGE_DEFAULT_TEXT


def test_contract_h_requisitions_is_scanned_as_a_backend_file() -> None:
    """RED: utils.messages must scan the new sink owner app/requisitions.py."""
    relative_paths = _backend_relative_paths()
    assert "app/requisitions.py" in relative_paths, (
        "app/requisitions.py is not scanned by utils.messages._iter_backend_files():\n"
        + "\n".join(f"  {path}" for path in relative_paths)
    )


def test_contract_h_catalog_usage_owner_is_requisitions() -> None:
    """RED: the catalog usage must resolve to app/requisitions.py, not main.py."""
    entry = _catalog_entry()
    usages = entry.get("usages") or []
    owners = sorted({str(usage.get("source_path")) for usage in usages})
    assert owners == ["app/requisitions.py"], (
        f"catalog usage owner for {MESSAGE_KEY} is {owners} (expected ['app/requisitions.py'])"
    )


def test_contract_h_catalog_usage_kind_and_source_function() -> None:
    """RED: the usage produced by the new owner must keep kind/source_function."""
    entry = _catalog_entry()
    matching = [
        usage
        for usage in (entry.get("usages") or [])
        if str(usage.get("source_path")) == "app/requisitions.py"
    ]
    assert matching, (
        f"no usage of {MESSAGE_KEY} is attributed to app/requisitions.py; "
        f"current usages: {entry.get('usages')}"
    )
    usage = matching[0]
    assert usage.get("kind") == "payload"
    assert usage.get("source_function") == "get_student_request_update_alert"


# ---------------------------------------------------------------------------
# CONTRACT H2 — display context non-drift
# ---------------------------------------------------------------------------

# Pinned from the current canonical values (no new expectation invented).
EXPECTED_DISPLAY_AREA = "Sistema"
EXPECTED_DISPLAY_FLOW = "Gerir get Student Request Update Alert"
EXPECTED_DISPLAY_STATE = "atualização"
EXPECTED_DISPLAY_TITLE = "Sistema > gerir get Student Request Update Alert > atualização"


def _display_context() -> dict:
    return _messages_module()._display_context_for_entry(_catalog_entry())


def test_contract_h2_display_area_is_preserved() -> None:
    """The move must not change the display area of the catalog entry."""
    assert _display_context()["display_area"] == EXPECTED_DISPLAY_AREA


def test_contract_h2_display_title_and_state_are_preserved() -> None:
    """Pin the currently canonical display title/state to demonstrate non-drift."""
    display = _display_context()
    assert display["display_flow"] == EXPECTED_DISPLAY_FLOW
    assert display["display_state"] == EXPECTED_DISPLAY_STATE
    assert display["display_title"] == EXPECTED_DISPLAY_TITLE


# ---------------------------------------------------------------------------
# CONTRACT I — create_app / startup cycle safety
# ---------------------------------------------------------------------------


def test_contract_i_create_app_does_not_load_main(tmp_path: Path) -> None:
    """Preservation control: building the app must never import ``main``."""
    code = (
        "import sys; "
        "assert 'main' not in sys.modules, 'main preloaded before create_app'; "
        "import app; "
        "application = app.create_app(); "
        "assert application is not None; "
        "assert 'main' not in sys.modules, 'create_app() imported main'"
    )
    result = _run_isolated(code, tmp_path)
    assert result.returncode == 0, result.stderr


_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")


def _canonical_database_state() -> tuple[int | None, str | None, set[str]]:
    """Size, digest and sidecar set of the canonical database."""
    canonical = PROJECT_ROOT / "database.db"
    if not canonical.is_file():
        return None, None, set()
    digest = hashlib.sha256(canonical.read_bytes()).hexdigest()
    sidecars = {
        suffix
        for suffix in _SIDECAR_SUFFIXES
        if canonical.with_name(canonical.name + suffix).exists()
    }
    return canonical.stat().st_size, digest, sidecars


def test_contract_i_create_app_leaves_the_canonical_database_untouched(tmp_path: Path) -> None:
    """Preservation control: the isolated app build must not mutate database.db.

    Only the *delta* is asserted: the canonical database is opened in WAL mode by
    other tooling, so pre-existing sidecars are ambient state this control does
    not own.  What it does own is that ``create_app()`` neither mutates the file
    nor introduces a new sidecar.
    """
    size_before, digest_before, sidecars_before = _canonical_database_state()

    code = "import app; app.create_app()"
    result = _run_isolated(code, tmp_path)
    assert result.returncode == 0, result.stderr

    size_after, digest_after, sidecars_after = _canonical_database_state()
    assert size_after == size_before
    assert digest_after == digest_before, "create_app() mutated the canonical database"
    assert sidecars_after <= sidecars_before, (
        "create_app() opened the canonical database; new sidecars: "
        f"{sorted(sidecars_after - sidecars_before)}"
    )
