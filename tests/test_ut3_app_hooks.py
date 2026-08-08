"""UT-3 RED contract — app/web hook migration (authz_gate, context, errors).

Proves, before implementation, the FUTURE app-hook architecture:

  A. before_request owner/order: csrf_protect (flask_wtf) then
     enforce_admin_access_control @ app.web.authz_gate.
  B. context processor owner/order: inject_admin_access_helpers then
     inject_editable_message_templates, both @ app.web.context.
  C. error handler owners: 404/500/413 @ app.web.errors; CSRFError stays @ app.
  D. exactly one main-owned Flask hook remains:
     _legacy_post_response_backup_sync.
  E. preserved boundary control (GREEN before and after UT-3):
     app/admin_access.py defines exactly 5 top-level helpers.
  F. utils.messages._iter_backend_files() future ownership: includes
     app/web/authz_gate.py and app/web/errors.py (both gain a message-catalog
     sink once _admin_access_denied_response / handle_large_upload move);
     does not require app/web/context.py (no sink there).
  G. _format_bytes_label canonical owner becomes app.presentation.

At RED stage (current UT-2 tree), sections A-D, F and G fail for the
intended reason: the new owner modules (app/web/authz_gate.py,
app/web/context.py, app/web/errors.py) do not exist yet and
_format_bytes_label / the hooks still live in main.py. Section E is a
preserved-boundary control and must stay GREEN throughout.

After UT-3 implementation, all assertions below must be GREEN.
"""
from __future__ import annotations

import ast
import importlib
from pathlib import Path

import main

PROJECT_ROOT = Path(__file__).resolve().parents[1]

MAIN_OWNED_HOOKS_FUTURE = {"_legacy_post_response_backup_sync"}


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


# ═══════════════════════════════════════════════════════════════════
# A. before_request owner and order
# ═══════════════════════════════════════════════════════════════════


def test_before_request_owner_and_order_future_authz_gate():
    hooks = [(f.__name__, f.__module__) for f in main.app.before_request_funcs[None]]
    names = [name for name, _module in hooks]
    modules = dict(hooks)

    assert "csrf_protect" in names, hooks
    assert "enforce_admin_access_control" in names, hooks
    assert names.index("csrf_protect") < names.index("enforce_admin_access_control"), (
        f"expected csrf_protect before enforce_admin_access_control, got order {names}"
    )
    assert modules["csrf_protect"] == "flask_wtf.csrf", modules
    assert modules["enforce_admin_access_control"] == "app.web.authz_gate", (
        f"enforce_admin_access_control still owned by {modules['enforce_admin_access_control']!r}; "
        "UT-3 expects app.web.authz_gate"
    )


# ═══════════════════════════════════════════════════════════════════
# B. context processor owner and order
# ═══════════════════════════════════════════════════════════════════


def test_context_processor_owner_and_order_future_web_context():
    hooks = [(f.__name__, f.__module__) for f in main.app.template_context_processors[None]]
    names = [name for name, _module in hooks]
    modules = dict(hooks)

    assert "inject_admin_access_helpers" in names, hooks
    assert "inject_editable_message_templates" in names, hooks
    assert names.index("inject_admin_access_helpers") < names.index("inject_editable_message_templates"), (
        f"expected inject_admin_access_helpers before inject_editable_message_templates, got order {names}"
    )
    assert modules["inject_admin_access_helpers"] == "app.web.context", (
        f"inject_admin_access_helpers still owned by {modules['inject_admin_access_helpers']!r}; "
        "UT-3 expects app.web.context"
    )
    assert modules["inject_editable_message_templates"] == "app.web.context", (
        f"inject_editable_message_templates still owned by {modules['inject_editable_message_templates']!r}; "
        "UT-3 expects app.web.context"
    )


# ═══════════════════════════════════════════════════════════════════
# C. error handler owners
# ═══════════════════════════════════════════════════════════════════


def test_error_handler_owners_future_web_errors():
    from flask_wtf.csrf import CSRFError
    from werkzeug.exceptions import InternalServerError, NotFound, RequestEntityTooLarge

    handlers = {}
    for d in main.app.error_handler_spec.values():
        for h in (d or {}).values():
            for exc_cls, fn in (h or {}).items():
                handlers[exc_cls] = fn

    assert handlers[NotFound].__module__ == "app.web.errors", (
        f"404 handler still owned by {handlers[NotFound].__module__!r}; UT-3 expects app.web.errors"
    )
    assert handlers[InternalServerError].__module__ == "app.web.errors", (
        f"500 handler still owned by {handlers[InternalServerError].__module__!r}; UT-3 expects app.web.errors"
    )
    assert handlers[RequestEntityTooLarge].__module__ == "app.web.errors", (
        f"413 handler still owned by {handlers[RequestEntityTooLarge].__module__!r}; UT-3 expects app.web.errors"
    )

    # CSRFError handler is out of UT-3 scope; it stays owned by app/__init__.py.
    assert handlers[CSRFError].__module__ == "app"
    assert handlers[CSRFError].__name__ == "_handle_csrf_error"


# ═══════════════════════════════════════════════════════════════════
# D. hooks_main == 1, exact main-owned set
# ═══════════════════════════════════════════════════════════════════


def test_hooks_main_is_exactly_one_legacy_backup_sync():
    main_hooks = _all_main_hooks()
    assert len(main_hooks) == 1, main_hooks
    assert set(main_hooks) == MAIN_OWNED_HOOKS_FUTURE, main_hooks


# ═══════════════════════════════════════════════════════════════════
# E. app/admin_access.py hard guard — preserved boundary, GREEN throughout
# ═══════════════════════════════════════════════════════════════════


def test_admin_access_module_defines_exactly_five_top_level_symbols():
    admin_access_path = PROJECT_ROOT / "app" / "admin_access.py"
    tree = ast.parse(admin_access_path.read_text(encoding="utf-8-sig"), filename=str(admin_access_path))
    bodies = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    assert len(bodies) == 5, bodies


# ═══════════════════════════════════════════════════════════════════
# F. message scanner future ownership (utils.messages._iter_backend_files)
# ═══════════════════════════════════════════════════════════════════


def test_message_scanner_includes_future_authz_gate_and_errors_owners(monkeypatch):
    """UT-3 RED: the backend message scanner must cover app/web/authz_gate.py
    (owns _admin_access_denied_response's resolve_user_message/flash sinks)
    and app/web/errors.py (owns handle_large_upload's flash sink).

    _iter_backend_files() filters its hardcoded list by Path.is_file(); the
    future files do not exist yet during RED, so Path.is_file is patched
    permissive here to isolate the assertion to the function's *file list*
    (does it know about these paths at all) rather than filesystem state.
    Neither future file is created on disk by this test.
    """
    from utils import messages

    monkeypatch.setattr(Path, "is_file", lambda self: True)
    scanned = {
        path.relative_to(messages.PROJECT_ROOT).as_posix()
        for path in messages._iter_backend_files()
    }
    assert "app/web/authz_gate.py" in scanned, sorted(scanned)
    assert "app/web/errors.py" in scanned, sorted(scanned)


# app.web.context (inject_admin_access_helpers / inject_editable_message_templates)
# has no resolve_user_message/flash call of its own -- it only forwards an
# already-resolved catalog -- so the scanner is not required to cover it.
# No assertion is made either way for app/web/context.py: this test file only
# pins the two files that DO need coverage (authz_gate.py, errors.py).


def test_message_catalog_count_stays_536_green_control():
    """Preserved invariant (must stay GREEN at RED entry and after UT-3)."""
    from utils import messages

    messages._message_catalog.cache_clear()
    assert len(messages._message_catalog()) == 536


# ═══════════════════════════════════════════════════════════════════
# G. _format_bytes_label canonical owner becomes app.presentation
# ═══════════════════════════════════════════════════════════════════


def test_format_bytes_label_canonical_owner_is_app_presentation():
    presentation = importlib.import_module("app.presentation")
    assert hasattr(presentation, "_format_bytes_label"), (
        "app.presentation does not define _format_bytes_label yet; "
        "UT-3 expects it to be the canonical owner"
    )
    assert presentation._format_bytes_label.__module__ == "app.presentation"


def test_main_format_bytes_label_is_reexport_of_app_presentation():
    presentation = importlib.import_module("app.presentation")
    assert main._format_bytes_label is presentation._format_bytes_label, (
        "main._format_bytes_label must be a direct re-export of "
        "app.presentation._format_bytes_label (no wrapper/body duplication)"
    )
