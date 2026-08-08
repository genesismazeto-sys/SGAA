# coding: utf-8
"""UT-3 R1 — direct-script entrypoint logger identity contract (finding UT3-01).

``app/web/authz_gate.py`` and ``app/web/errors.py`` deliberately bind to
``logging.getLogger("main")`` because the RotatingFileHandler, level and
formatter for the application channel are configured exactly once, in
``main.py``.

The rest of the UT-3 suite only ever reaches ``main`` through ``import main``,
where ``__name__ == "main"`` and the two names coincide by accident.  Under the
shipped entrypoint::

    python main.py

``__name__ == "__main__"``, so an entrypoint-dependent
``logging.getLogger(__name__)`` in ``main.py`` configures the ``"__main__"``
logger instead and the migrated modules end up detached from the file handler:
RBAC shadow-audit evidence and ``internal_error`` 500 tracebacks are never
persisted to ``app.log``.

These tests execute ``main.py`` with real ``__name__ == "__main__"`` semantics
(``runpy.run_path(..., run_name="__main__")``) and pin the runtime object
identity of the resulting logger.  They are deliberately not source-text
assertions.

Isolation: ``init_db`` and ``Flask.run`` — the only two statements in the
shipped ``__main__`` tail — are neutralised, so no server is started and no
database is touched; ``APP_LOG_DIR`` is redirected to a per-test ``tmp_path``
so the handler built by the executed module writes only there.  Every handler
the execution adds is closed and removed on teardown.
"""
from __future__ import annotations

import logging
import runpy
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAIN_PY = PROJECT_ROOT / "main.py"

# The channel app/web/authz_gate.py and app/web/errors.py bind to.
CANONICAL_LOGGER_NAME = "main"

# The name an entrypoint-dependent getLogger(__name__) would produce under
# `python main.py`; asserted against so the RED failure names the actual defect.
DIRECT_SCRIPT_DUNDER_NAME = "__main__"


def _watched_loggers() -> list[logging.Logger]:
    return [
        logging.getLogger(),
        logging.getLogger(CANONICAL_LOGGER_NAME),
        logging.getLogger(DIRECT_SCRIPT_DUNDER_NAME),
    ]


def _file_sinks(logger: logging.Logger) -> list[str]:
    return [
        Path(h.baseFilename).resolve().as_posix()
        for h in logger.handlers
        if isinstance(h, logging.FileHandler)
    ]


@pytest.fixture
def direct_script_main(tmp_path, monkeypatch):
    """Run ``main.py`` as ``__main__`` and yield ``(namespace, log_dir)``.

    ``namespace`` is the executed module's globals, so ``namespace["logger"]``
    is the exact logger object the direct-script entrypoint configured.
    """
    import app.db as app_db
    from flask import Flask

    log_dir = tmp_path / "direct_entrypoint_logs"
    log_dir.mkdir()
    monkeypatch.setenv("APP_LOG_DIR", str(log_dir))

    # Shipped __main__ tail is `with app.app_context(): init_db()` followed by
    # `app.run(...)`.  Neutralise both: no listening socket, no schema writes,
    # no WAL/SHM/journal.  main.py binds init_db at import time via
    # `from app.db import ...`, so patching the canonical owner is enough.
    monkeypatch.setattr(app_db, "init_db", lambda *args, **kwargs: None)
    monkeypatch.setattr(Flask, "run", lambda *args, **kwargs: None)

    saved = [(lg, list(lg.handlers), lg.level) for lg in _watched_loggers()]
    try:
        namespace = runpy.run_path(str(MAIN_PY), run_name=DIRECT_SCRIPT_DUNDER_NAME)
        yield namespace, log_dir
    finally:
        for lg, handlers, level in saved:
            added = [h for h in lg.handlers if h not in handlers]
            lg.handlers = handlers
            lg.setLevel(level)
            for handler in added:
                handler.close()


def test_direct_script_execution_really_runs_under_dunder_main(direct_script_main):
    """Guard the harness itself: prove we exercised the shipped entrypoint."""
    namespace, _log_dir = direct_script_main

    assert namespace["__name__"] == DIRECT_SCRIPT_DUNDER_NAME
    assert "logger" in namespace, "main.py did not define a module-level logger"


def test_direct_script_configures_canonical_main_logger(direct_script_main):
    """UT3-01: the configured logger must be ``"main"``, not ``"__main__"``."""
    namespace, _log_dir = direct_script_main
    configured = namespace["logger"]

    assert configured.name == CANONICAL_LOGGER_NAME, (
        f"main.py executed as {DIRECT_SCRIPT_DUNDER_NAME!r} configured logger "
        f"{configured.name!r}; app/web/authz_gate.py and app/web/errors.py bind to "
        f"{CANONICAL_LOGGER_NAME!r}, so the shipped `python main.py` entrypoint "
        "leaves them detached from the configured handler (UT3-01)."
    )
    assert configured is logging.getLogger(CANONICAL_LOGGER_NAME)


def test_direct_script_logger_is_shared_by_migrated_web_modules(direct_script_main):
    """authz_gate/errors must be the *same object*, not merely same-named."""
    from app.web import authz_gate, errors

    namespace, _log_dir = direct_script_main
    configured = namespace["logger"]

    assert authz_gate.logger is configured, (
        f"app.web.authz_gate.logger is {authz_gate.logger.name!r} but the direct-script "
        f"entrypoint configured {configured.name!r}: RBAC shadow-audit evidence would "
        "not reach the configured file handler."
    )
    assert errors.logger is configured, (
        f"app.web.errors.logger is {errors.logger.name!r} but the direct-script "
        f"entrypoint configured {configured.name!r}: internal_error 500 tracebacks "
        "would not reach the configured file handler."
    )


def test_direct_script_file_handler_belongs_to_canonical_logger(direct_script_main):
    """The RotatingFileHandler must hang off ``"main"``, not a sibling logger."""
    namespace, log_dir = direct_script_main
    configured = namespace["logger"]
    canonical = logging.getLogger(CANONICAL_LOGGER_NAME)
    expected_sink = (log_dir / "app.log").resolve().as_posix()

    owned = [
        h
        for h in canonical.handlers
        if isinstance(h, RotatingFileHandler)
        and Path(h.baseFilename).resolve().as_posix() == expected_sink
    ]
    assert owned, (
        f"no RotatingFileHandler for {expected_sink!r} on logger "
        f"{CANONICAL_LOGGER_NAME!r}; it landed on "
        f"{ {lg.name: _file_sinks(lg) for lg in _watched_loggers()} } instead."
    )
    assert configured is canonical
    assert owned[0] in configured.handlers


def test_error_through_migrated_logger_reaches_direct_script_file_sink(direct_script_main):
    """End-to-end: ERROR via app.web.errors.logger lands in the configured sink."""
    from app.web import errors

    _namespace, log_dir = direct_script_main
    sink = log_dir / "app.log"
    marker = "UT3-R1-DIRECT-ENTRYPOINT-SINK-MARKER"

    errors.logger.error(marker)
    for handler in errors.logger.handlers:
        handler.flush()

    assert sink.is_file(), f"direct-script entrypoint never created {sink}"
    contents = sink.read_text(encoding="utf-8")
    assert marker in contents, (
        f"marker emitted through app.web.errors.logger ({errors.logger.name!r}) did not "
        f"reach the sink configured by the direct-script entrypoint ({sink}); "
        f"handler placement was "
        f"{ {lg.name: _file_sinks(lg) for lg in _watched_loggers()} }."
    )
