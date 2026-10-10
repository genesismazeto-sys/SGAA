"""Authenticated HTTP front for scheduled storage jobs (a WSGI application).

A hosted runtime has no operator shell to run ``python -m app.storage.cli
mirror-run``; a scheduler (Vercel Cron, ``pg_cron`` + ``pg_net``, a CI job,
``curl`` from anywhere) calls this front instead.  It is deliberately NOT a
route of the web application: it is its own WSGI callable that a platform
deploys as its own function, so the web function never loads the Drive worker
(MP-1 invariant I3, ``tests/test_storage_mp1_web_isolation.py``) and the web
route, RBAC and CSRF inventories do not grow.

CONTRACT
    ``GET`` or ``POST`` ``/internal/scheduler/mirror`` with
    ``Authorization: Bearer <CRON_SECRET>`` runs ONE bounded mirror pass
    (``drive_mirror.run_mirror_pass``) and answers a value-free JSON report:

        200  the pass ran (including "nothing due")
        503  not runnable: canonical store or Drive unavailable (``result_code``)
        500  unexpected failure (a fixed code, never exception text)
        401  missing / wrong credential
        405  other method
        404  any other path, or the front is disabled

    The front is DISABLED -- every request is a 404 -- unless ``CRON_SECRET``
    is accepted by ``hosting.cron_secret`` (at least
    ``hosting.CRON_SECRET_MIN_LENGTH`` ASCII characters).  Nothing is
    read from the query string, no cookie or session is ever consulted, the
    comparison is constant-time over SHA-256 digests, and no application,
    database or provider is touched before authentication succeeds.

    ``SCHEDULER_MIRROR_BATCH`` (default 5, at most 25) bounds the objects per
    invocation; ``SCHEDULER_MIRROR_LEASE_SECONDS`` (default 300) sizes the
    lease, which should cover the function's maximum duration: an invocation
    killed mid-pass leaves its claims ``syncing`` until the lease expires and
    MP-1 releases them into ``retry``.  Platform cron delivery is at-least-once
    and may overlap: leases, fences and find-by-operation (MP-1) make duplicate
    and concurrent invocations safe.

Entrypoint: ``app.storage.scheduler:application``.  This module is a storage
background tool: nothing in the web runtime imports it.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import threading

from app import hosting
from app.storage import mirror_outbox

logger = logging.getLogger(__name__)

ROUTE_MIRROR = "/internal/scheduler/mirror"
BATCH_ENV = "SCHEDULER_MIRROR_BATCH"
LEASE_ENV = "SCHEDULER_MIRROR_LEASE_SECONDS"
DEFAULT_BATCH = 5
MAX_BATCH = 25
DEFAULT_LEASE_SECONDS = mirror_outbox.DEFAULT_LEASE_SECONDS

SCHEDULER_STARTUP_FAILED = "SCHEDULER_STARTUP_FAILED"
SCHEDULER_JOB_FAILED = "SCHEDULER_JOB_FAILED"

_BEARER = "Bearer "
_app_lock = threading.Lock()
_app = None


def _build_app():
    """The Flask application the job runs under (a seam for tests)."""
    from app import create_app

    return create_app()


def _flask_app():
    global _app
    with _app_lock:
        if _app is None:
            _app = _build_app()
        return _app


def _bounded_env(name: str, default: int, low: int, high: int) -> int:
    raw = str(os.environ.get(name) or "").strip()
    # At most nine digits: a longer value is out of every range, and ``int`` of a
    # very long digit string raises.
    if raw.isascii() and raw.isdigit() and len(raw) <= 9:
        return min(max(int(raw), low), high)
    return default


def _authorized(header: str, secret: str) -> bool:
    if not header.startswith(_BEARER):
        return False
    # WSGI hands a header over latin-1 decoded; encode it back the same way.  The secret is ASCII.
    presented = hashlib.sha256(header[len(_BEARER):].encode("latin-1", "replace")).digest()
    expected = hashlib.sha256(secret.encode("ascii")).digest()
    return hmac.compare_digest(presented, expected)


def _run_mirror() -> tuple[int, dict]:
    from app.db import close_db_connection, get_db_connection
    from app.storage import drive_mirror

    try:
        flask_app = _flask_app()
    except Exception as exc:
        logger.error("scheduler startup failed (%s)", type(exc).__name__)
        return 500, {"result_code": SCHEDULER_STARTUP_FAILED}
    batch = _bounded_env(BATCH_ENV, DEFAULT_BATCH, 1, MAX_BATCH)
    lease = _bounded_env(
        LEASE_ENV, DEFAULT_LEASE_SECONDS, 2 * drive_mirror.LEASE_SAFETY_SECONDS, mirror_outbox.MAX_LEASE_SECONDS
    )
    try:
        with flask_app.app_context():
            try:
                result = drive_mirror.run_mirror_pass(get_db_connection(), limit=batch, lease_seconds=lease)
            finally:
                close_db_connection(None)
    except Exception as exc:
        # Exception text may carry a locator or a provider message: only the class is logged.
        logger.error("scheduler job mirror failed (%s)", type(exc).__name__)
        return 500, {"result_code": SCHEDULER_JOB_FAILED}
    status = 200 if result.result_code == drive_mirror.RESULT_OK else 503
    return status, result.as_dict()


def _respond(start_response, status: int, body: dict | None = None, *, headers=()):
    payload = json.dumps(body if body is not None else {}, sort_keys=True).encode("utf-8")
    reasons = {200: "OK", 401: "Unauthorized", 404: "Not Found", 405: "Method Not Allowed",
               500: "Internal Server Error", 503: "Service Unavailable"}
    start_response(
        f"{status} {reasons[status]}",
        [("Content-Type", "application/json"), ("Content-Length", str(len(payload))),
         ("Cache-Control", "no-store"), *headers],
    )
    return [payload]


def application(environ, start_response):
    secret = hosting.cron_secret()
    if secret is None or environ.get("PATH_INFO") != ROUTE_MIRROR:
        return _respond(start_response, 404)
    if environ.get("REQUEST_METHOD") not in ("GET", "POST"):
        return _respond(start_response, 405, headers=[("Allow", "GET, POST")])
    if not _authorized(str(environ.get("HTTP_AUTHORIZATION") or ""), secret):
        return _respond(start_response, 401, headers=[("WWW-Authenticate", "Bearer")])
    status, report = _run_mirror()
    return _respond(start_response, status, {"command": "mirror", **report})


__all__ = [
    "DEFAULT_BATCH",
    "MAX_BATCH",
    "ROUTE_MIRROR",
    "SCHEDULER_JOB_FAILED",
    "SCHEDULER_STARTUP_FAILED",
    "application",
]
