# coding: utf-8
"""MP-1 invariant I3: the storage background tools are unreachable from the web runtime.

The Drive mirror worker, the census / cross-check and the legacy convergence
call Google and Supabase synchronously; they are operator commands
(``python -m app.storage.cli``).  If any runtime module imported them, a
request could end up waiting on Drive -- the breach of
DRIVE_AVAILABILITY_MUST_NOT_BLOCK_REQUEST_SUBMISSION /
..._ADMIN_ARQUIVOS_CANONICAL_OPERATION this guard prevents.  Only the
background set itself (and the CLI that fronts it) may import its members.
Absolute imports, relative imports and dotted-name strings (``importlib``)
all count.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKGROUND = frozenset({
    "app.storage.cli",
    "app.storage.drive_mirror",
    "app.storage.legacy_convergence",
    "app.storage.storage_audit",
})


def _module_name(path: Path) -> str:
    relative = path.relative_to(ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _hits(name: str) -> set[str]:
    return {member for member in BACKGROUND if name == member or name.startswith(member + ".")}


def background_imports(source: str, module: str = "") -> set[str]:
    """Every BACKGROUND module a source (``module``, for relative imports) reaches."""
    found = set()
    package = module.rsplit(".", 1)[0] if module else ""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found |= _hits(alias.name)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                anchor = package.split(".") if package else []
                anchor = anchor[: len(anchor) - (node.level - 1)] if node.level > 1 else anchor
                base = ".".join(part for part in (*anchor, base) if part)
            found |= _hits(base)
            for alias in node.names:
                found |= _hits(f"{base}.{alias.name}" if base else alias.name)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            found |= _hits(node.value.strip())
    return found


def _runtime_sources():
    for base in (ROOT / "app", ROOT / "services", ROOT / "utils"):
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" not in path.parts and _module_name(path) not in BACKGROUND:
                yield path
    yield ROOT / "main.py"


def test_no_runtime_module_imports_a_storage_background_tool():
    offenders = {
        str(path.relative_to(ROOT)): sorted(found)
        for path in _runtime_sources()
        if (found := background_imports(path.read_text(encoding="utf-8-sig"), _module_name(path)))
    }
    assert offenders == {}


def test_scanner_negative_control_detects_every_import_form():
    for source, module in (
        ("from app.storage import drive_mirror", ""),
        ("from app.storage.storage_audit import cross_check", ""),
        ("import app.storage.legacy_convergence", ""),
        ("import app.storage.cli as cli", ""),
        ("def f():\n    from app.storage import storage_audit\n", ""),
        ("from . import drive_mirror", "app.storage.request_documents"),
        ("from .storage_audit import census", "app.storage.request_documents"),
        ("from ..storage import cli", "app.views.files"),
        ("importlib.import_module('app.storage.drive_mirror')", ""),
    ):
        assert background_imports(source, module), source
    for source, module in (
        ("from app.storage import mirror_outbox, request_documents", ""),
        ("from app.storage.drive_mirrors import x", ""),
        ("from . import mirror_outbox", "app.storage.request_documents"),
        ("label = 'app.storage'", ""),
    ):
        assert background_imports(source, module) == set(), source


def test_scanner_sees_the_actual_background_importers():
    cli = (ROOT / "app" / "storage" / "cli.py").read_text(encoding="utf-8-sig")
    assert "app.storage.drive_mirror" in background_imports(cli, "app.storage.cli")
