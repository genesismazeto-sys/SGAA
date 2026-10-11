# coding: utf-8
"""Canonical owner of the hosted pre-opening admission gate (MP-3 SPEC amendment A15).

WHY THIS EXISTS
    Between the production deployment and the opening (MP-3 states C9 to C11) the
    hosted application holds the institution's real data, and only the operator may
    use it: to smoke it, to connect Google and to prove the mirror.  "Not announced"
    is not a control.  While ``SGAA_ADMISSION=operator`` every request that does not
    present the operator credential is refused HERE, before CSRF, the session, any
    view or any database access -- so an ordinary student or staff member cannot
    write anything, not even a login attempt.  Lifting the gate (``SGAA_ADMISSION=open``
    and a redeploy) is the opening itself (gate GO).

WHAT IT IS NOT
    Not a second authorization layer: it knows no user, role or route.  It is a
    deployment-state switch of the hosted runtime contract (``app.hosting``); once the
    operator is through it, the application's own authentication and RBAC decide
    everything, exactly as after the opening.

THE OPERATOR CREDENTIAL
    ``SGAA_OPERATOR_TOKEN`` (at least 32 characters), placed in the platform by the
    user and never seen by the executor.  Tools send it in the ``X-SGAA-Operator-Token``
    header.  A browser presents it once on ``/operator-admission`` (a POST form with the
    application's CSRF protection) and receives an HttpOnly, Secure cookie that holds its
    issue time and an HMAC of that time and the token under the application's secret key --
    never the token itself; the server refuses it eight hours after issue.

ALWAYS REACHABLE
    ``/health`` (read-only), static files and the admission form.  Everything else
    answers 503 with ``X-SGAA-Admission: closed`` and no cookie.

THE OPENING (MP-3 A15, A17)
    ``SGAA_ADMISSION=open`` with no gate is for a workstation or a test only.  In production
    (and on any serverless platform) it also requires ``SGAA_OPENING_REFERENCE``, the hash of
    the cutover ledger's reference entry, and it admits users ONLY while the PROD database
    holds the authorization the ledger wrote with that entry (``app.hosting``: the row carries
    the entry; it must hash to the reference, name this database's live identity, this process's
    code and this platform project, and not be revoked).  The check runs before anything else,
    is re-read at most every ``OPENING_CHECK_SECONDS``, and fails closed: a missing, forged,
    revoked or foreign authorization -- or a database that cannot be asked -- is answered like
    a closed deployment (503 ``X-SGAA-Admission: closed``).  A well-formed value alone opens
    nothing.  Every response of an open deployment announces ``X-SGAA-Opening: <tag>``.

THE CODE IDENTITY
    Every response of a hosted production process names the code it runs
    (``X-SGAA-Code``: ``app.hosting.runtime_code_sha256`` of its own files), so the deploy
    tool and the ledger observe what each deployment address actually serves.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time

from flask import Response, current_app, redirect, request

from app import hosting

ADMISSION_HEADER = "X-SGAA-Operator-Token"
ADMISSION_STATE_HEADER = "X-SGAA-Admission"
ADMISSION_CLOSED = "closed"
ADMISSION_COOKIE = "sgaa_operator"
ADMISSION_PATH = "/operator-admission"
ADMISSION_COOKIE_SECONDS = 8 * 60 * 60
ADMISSION_OPENING_HEADER = "X-SGAA-Opening"
ADMISSION_CODE_HEADER = hosting.CODE_HEADER
#: How long an open process trusts its last reading of the authorization (a revocation takes effect
#: within this time on every running instance).
OPENING_CHECK_SECONDS = 15
_COOKIE_CLOCK_SKEW_SECONDS = 60
_ALWAYS_REACHABLE = frozenset({"/health", ADMISSION_PATH})
_OPEN_REACHABLE = frozenset({"/health"})
_HMAC_CONTEXT = b"sgaa-operator-admission\x00"

logger = logging.getLogger("main")

_CLOSED_PAGE = (
    "<!doctype html><html lang=\"pt-BR\"><head><meta charset=\"utf-8\"><title>SGAA</title></head>"
    "<body><main><h1>SGAA</h1><p>O sistema ainda não está aberto.</p></main></body></html>"
)
_FORM_PAGE = (
    "<!doctype html><html lang=\"pt-BR\"><head><meta charset=\"utf-8\"><title>SGAA</title></head>"
    "<body><main><h1>SGAA</h1><form method=\"post\" action=\"" + ADMISSION_PATH + "\">"
    "<label for=\"token\">Credencial do operador</label> "
    "<input type=\"password\" id=\"token\" name=\"token\" autocomplete=\"off\" required> "
    "<button type=\"submit\">Entrar</button></form></main></body></html>"
)


def cookie_for(secret_key, token: str, issued: int) -> str:
    """The admission cookie value: its issue time and an HMAC of that time and the token."""
    key = secret_key.encode("utf-8") if isinstance(secret_key, str) else bytes(secret_key)
    mac = hmac.new(key, _HMAC_CONTEXT + str(issued).encode("ascii") + b"\x00" + token.encode("ascii"), hashlib.sha256)
    return f"{issued}.{mac.hexdigest()}"


def _cookie_value(token: str, issued: int) -> str:
    return cookie_for(current_app.secret_key, token, issued)


def _cookie_valid(cookie: str, token: str) -> bool:
    issued, _, _mac = cookie.partition(".")
    if not issued.isdigit() or len(issued) > 12:
        return False
    age = int(time.time()) - int(issued)
    if age > ADMISSION_COOKIE_SECONDS or age < -_COOKIE_CLOCK_SKEW_SECONDS:
        return False
    return hmac.compare_digest(cookie.encode("ascii", "replace"), _cookie_value(token, int(issued)).encode("ascii"))


def _token() -> str:
    return current_app.config["SGAA_OPERATOR_TOKEN"]


def operator_presented() -> bool:
    """Whether this request carries the operator credential (header or admission cookie)."""
    token = _token()
    presented = request.headers.get(ADMISSION_HEADER, "")
    if presented and hmac.compare_digest(presented.encode("utf-8", "replace"), token.encode("ascii")):
        return True
    cookie = request.cookies.get(ADMISSION_COOKIE, "")
    return bool(cookie) and _cookie_valid(cookie, token)


def _closed() -> Response:
    response = Response(_CLOSED_PAGE, status=503, mimetype="text/html")
    response.headers[ADMISSION_STATE_HEADER] = ADMISSION_CLOSED
    response.headers["Cache-Control"] = "no-store"
    response.headers["Retry-After"] = "3600"
    return response


def enforce_admission():
    """``before_request``: the first hook of a hosted application while admission is ``operator``."""
    path = request.path
    if path in _ALWAYS_REACHABLE or path.startswith("/static/"):
        return None
    if operator_presented():
        return None
    return _closed()


def admission_view():
    if request.method == "GET":
        response = Response(_FORM_PAGE, mimetype="text/html")
        response.headers["Cache-Control"] = "no-store"
        return response
    presented = (request.form.get("token") or "").strip()
    if not presented or not hmac.compare_digest(presented.encode("utf-8", "replace"), _token().encode("ascii")):
        logger.warning("event=operator_admission_refused")
        response = _closed()
        response.status_code = 403
        return response
    response = redirect("/login", code=303)
    response.set_cookie(
        ADMISSION_COOKIE, _cookie_value(_token(), int(time.time())), max_age=ADMISSION_COOKIE_SECONDS, path="/",
        secure=bool(current_app.config.get("SESSION_COOKIE_SECURE")), httponly=True, samesite="Lax",
    )
    response.headers["Cache-Control"] = "no-store"
    return response


def _announce_opening(response):
    response.headers[ADMISSION_OPENING_HEADER] = current_app.config["SGAA_OPENING_TAG"]
    return response


_RUNTIME_CODE: list[str] = []


def _runtime_code() -> str:
    """The code identity of this process's files, read once (the files do not change while it runs)."""
    if not _RUNTIME_CODE:
        _RUNTIME_CODE.append(hosting.runtime_code_sha256())
    return _RUNTIME_CODE[0]


def _announce_code(response):
    response.headers[ADMISSION_CODE_HEADER] = current_app.config["SGAA_CODE"]
    return response


def _read_authorization() -> bool:
    """Ask the PROD database once whether it authorizes this process to admit users (fails closed)."""
    from app.db import get_db_connection

    config = current_app.config
    reference, code, project = config["SGAA_OPENING_REFERENCE"], config["SGAA_CODE"], config["SGAA_PLATFORM_PROJECT"]
    try:
        raw = get_db_connection().raw_connection
        try:
            row = raw.execute(hosting.OPENING_SELECT_SQL, (reference, code)).fetchone()
            identity = hosting.source_identity_sha256(hosting.database_source(raw))
        finally:
            raw.rollback()  # the gate runs first: nothing of the request is on this connection yet
    except Exception:
        logger.warning("event=opening_authorization_unreadable")
        return False
    authorized = row is not None and hosting.opening_entry_authorizes(
        row[0], reference=reference, database_identity=identity, code=code, project=project)
    if not authorized:
        logger.warning("event=opening_not_authorized")
    return authorized


def opening_authorized() -> bool:
    state = current_app.config["SGAA_OPENING_STATE"]
    now = time.monotonic()
    if now >= state["until"]:
        state["authorized"] = _read_authorization()
        state["until"] = now + OPENING_CHECK_SECONDS
    return state["authorized"]


def enforce_opening():
    """``before_request`` of an open production process: users only under a standing authorization."""
    path = request.path
    if path in _OPEN_REACHABLE or path.startswith("/static/"):
        return None
    if opening_authorized():
        return None
    return _closed()


def install(app, environ=None) -> str:
    """Register the gate on a hosted application; returns the admission mode.

    Called right after the application object exists, so the gate is the FIRST
    ``before_request`` -- ahead of CSRF, the session hooks and every view.  ``open`` on a
    workstation or in a test registers no gate; ``open`` in production (or on a serverless
    platform) registers the authorization check and announces the reference's tag.
    """
    production = bool(app.config.get("IS_PRODUCTION"))
    mode = hosting.admission_mode(environ, production=production)
    if mode is None:  # create_app refuses earlier through the startup blockers; never guess
        raise hosting.single(hosting.HOSTED_ADMISSION_UNDECIDED, hosting.ADMISSION_ENV)
    app.config["SGAA_ADMISSION"] = mode
    decided = hosting.admission_must_be_decided(environ, production=production)
    if decided:
        app.config["SGAA_CODE"] = _runtime_code()
        app.after_request(_announce_code)
    if mode != hosting.ADMISSION_OPERATOR:
        reference = hosting.opening_reference(environ)
        if reference is None and decided:
            raise hosting.single(hosting.HOSTED_OPENING_REFERENCE_REQUIRED, hosting.OPENING_REFERENCE_ENV)
        if reference is not None:
            app.config["SGAA_OPENING_TAG"] = hosting.opening_tag(reference)
            app.after_request(_announce_opening)
        if decided:
            app.config["SGAA_OPENING_REFERENCE"] = reference
            app.config["SGAA_PLATFORM_PROJECT"] = hosting.vercel_project_sha256(environ)
            app.config["SGAA_OPENING_STATE"] = {"until": 0.0, "authorized": False}
            app.before_request(enforce_opening)
        return mode
    token = hosting.operator_token(environ)
    if token is None:
        raise hosting.single(hosting.HOSTED_OPERATOR_TOKEN_REQUIRED, hosting.OPERATOR_TOKEN_ENV)
    app.config["SGAA_OPERATOR_TOKEN"] = token
    app.before_request(enforce_admission)
    app.add_url_rule(ADMISSION_PATH, endpoint="operator_admission", view_func=admission_view,
                     methods=["GET", "POST"])
    return mode


__all__ = [
    "ADMISSION_CLOSED",
    "ADMISSION_CODE_HEADER",
    "ADMISSION_COOKIE",
    "ADMISSION_HEADER",
    "ADMISSION_OPENING_HEADER",
    "ADMISSION_PATH",
    "ADMISSION_STATE_HEADER",
    "OPENING_CHECK_SECONDS",
    "cookie_for",
    "enforce_admission",
    "enforce_opening",
    "install",
    "opening_authorized",
    "operator_presented",
]
