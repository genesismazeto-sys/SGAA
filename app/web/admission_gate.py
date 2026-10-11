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

THE OPENING
    ``SGAA_ADMISSION=open`` registers no gate.  In production (and on any serverless
    platform) it also requires ``SGAA_OPENING_REFERENCE``, the hash of the cutover ledger's
    reference entry (taken while admission was closed); every response then announces
    ``X-SGAA-Opening: <tag of that value>`` so the ledger can prove the lift is bound to the
    reference it recorded.  The process checks only the value's shape.
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
_COOKIE_CLOCK_SKEW_SECONDS = 60
_ALWAYS_REACHABLE = frozenset({"/health", ADMISSION_PATH})
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


def install(app, environ=None) -> str:
    """Register the gate on a hosted application; returns the admission mode.

    Called right after the application object exists, so the gate is the FIRST
    ``before_request`` -- ahead of CSRF, the session hooks and every view.  ``open``
    registers no gate; with an opening reference it announces the reference's tag.
    """
    production = bool(app.config.get("IS_PRODUCTION"))
    mode = hosting.admission_mode(environ, production=production)
    if mode is None:  # create_app refuses earlier through the startup blockers; never guess
        raise hosting.single(hosting.HOSTED_ADMISSION_UNDECIDED, hosting.ADMISSION_ENV)
    app.config["SGAA_ADMISSION"] = mode
    if mode != hosting.ADMISSION_OPERATOR:
        reference = hosting.opening_reference(environ)
        if reference is None and hosting.admission_must_be_decided(environ, production=production):
            raise hosting.single(hosting.HOSTED_OPENING_REFERENCE_REQUIRED, hosting.OPENING_REFERENCE_ENV)
        if reference is not None:
            app.config["SGAA_OPENING_TAG"] = hosting.opening_tag(reference)
            app.after_request(_announce_opening)
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
    "ADMISSION_COOKIE",
    "ADMISSION_HEADER",
    "ADMISSION_OPENING_HEADER",
    "ADMISSION_PATH",
    "ADMISSION_STATE_HEADER",
    "cookie_for",
    "enforce_admission",
    "install",
    "operator_presented",
]
