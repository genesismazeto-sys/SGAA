# coding: utf-8
"""Public HTTPS smoke for a hosted SGAA deployment -- operator tool, read-only.

WHY THIS EXISTS
    The cutover state SMOKED (C10) must be a repeatable, value-free check run
    against the PUBLIC address, not a developer's impression.  It performs only
    reads: it never submits a form that changes business data.  The optional
    authenticated check signs in as an operator account (password at a hidden
    prompt, never an argument) and reads two pages; a successful sign-in is the
    only write the application makes, and the PONR detector excludes it.

CHECKS (each reports a fixed code, never a body, header value or address)
    TLS_HTTPS       the address is https and its certificate verifies
    HEALTH          ``/health`` answers 200 ``{"status": "ok"}``
    LOGIN_PAGE      ``/login`` answers 200
    COOKIE_FLAGS    every cookie set carries Secure, HttpOnly and SameSite
    HEADERS         HSTS, nosniff, frame and referrer policy are present
    ADMIN_REFUSED   an unauthenticated admin page is a redirect to the login or a refusal
    STATIC          a static asset linked from the login page is served
    SCHEDULER       the scheduler route answers 401/404 without or with a wrong bearer
    NO_TRACEBACK    an unknown path answers 404 with no interpreter trace
    DATA_API        (with --data-api-url and the publishable key) the platform data API
                    does not serve: the valid key is refused like a bogus one
    SIGN_IN         (with --email) the operator signs in and reads an authenticated
                    endpoint that writes nothing (``/csrf-token``; never the dashboard,
                    whose view writes alert receipts and derived status changes)

Exit codes: 0 every check passed, 1 a check failed or the run was refused, 2 usage.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import http.client
import json
import os
import re
import ssl
import sys
from urllib.parse import urlsplit

SCHEDULER_ROUTE = "/internal/scheduler/mirror"
# One application table asked for in the ``public`` schema.  On a project whose Data API is off PostgREST
# exposes only an empty schema and answers 406 PGRST106 ("Invalid schema: public"); with the API on and
# ``public`` exposed it answers 404 PGRST205 (table absent), 42501 (privileges revoked) or the rows.
DATA_API_TABLE_PATH = "/rest/v1/usuarios?select=id&limit=1"
REQUIRED_HEADERS = {
    "strict-transport-security": None,
    "x-content-type-options": "nosniff",
    "x-frame-options": None,
    "referrer-policy": None,
    "content-security-policy": None,
}
TIMEOUT_SECONDS = 20


class Refused(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _Client:
    """One HTTP(S) endpoint; never follows redirects, keeps cookies by hand."""

    def __init__(self, base_url: str, *, allow_insecure: bool) -> None:
        parts = urlsplit(base_url)
        if parts.scheme not in {"https", "http"} or not parts.hostname or parts.username or parts.path.strip("/"):
            raise Refused("BASE_URL_INVALID")
        if parts.scheme == "http" and not allow_insecure:
            raise Refused("TLS_REQUIRED")
        self.scheme = parts.scheme
        self.host = parts.hostname
        self.port = parts.port
        self.cookies: dict[str, str] = {}
        self._context = ssl.create_default_context()

    def request(self, method: str, path: str, *, headers=None, body: bytes | None = None, jar: bool = False):
        connection_class = http.client.HTTPSConnection if self.scheme == "https" else http.client.HTTPConnection
        kwargs = {"timeout": TIMEOUT_SECONDS}
        if self.scheme == "https":
            kwargs["context"] = self._context
        connection = connection_class(self.host, self.port, **kwargs)
        sent = {"User-Agent": "sgaa-hosted-smoke/1", "Accept": "*/*", **(headers or {})}
        if jar and self.cookies:
            sent["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        try:
            connection.request(method, path, body=body, headers=sent)
            response = connection.getresponse()
            data = response.read(2 * 1024 * 1024)
            raw_cookies = response.msg.get_all("Set-Cookie") or []
            if jar:
                for cookie in raw_cookies:
                    name, _, rest = cookie.partition("=")
                    self.cookies[name.strip()] = rest.split(";", 1)[0]
            return response.status, {k.lower(): v for k, v in response.getheaders()}, data, raw_cookies
        finally:
            connection.close()


PLACEHOLDER_SCHEMAS = frozenset({"pgrst_no_exposed_schemas", "pg_pgrst_no_exposed_schemas"})
_EXPOSED_HINT = re.compile(r"Only the following schemas are exposed: ([A-Za-z0-9_, ]+)")


def _only_placeholder_schema_exposed(status: int, body: bytes) -> bool:
    """406 PGRST106 whose hint lists only the empty placeholder schema (the Data API is off)."""
    try:
        parsed = json.loads(body.decode("utf-8"))
    except ValueError:
        return False
    if status != 406 or not isinstance(parsed, dict) or parsed.get("code") != "PGRST106":
        return False
    hint = parsed.get("hint")
    found = _EXPOSED_HINT.fullmatch(hint) if isinstance(hint, str) else None
    if not found:
        return False
    listed = {name.strip() for name in found.group(1).split(",") if name.strip()}
    return bool(listed) and listed <= PLACEHOLDER_SCHEMAS


def _check(name: str, ok: bool, code: str = "OK") -> dict:
    return {"check": name, "ok": bool(ok), "code": "OK" if ok else (code if code != "OK" else "FAILED")}


def run(base_url: str, *, allow_insecure: bool = False, data_api_url: str | None = None,
        publishable_key: str | None = None, email: str | None = None, password: str | None = None) -> dict:
    client = _Client(base_url, allow_insecure=allow_insecure)
    checks: list[dict] = []

    def attempt(name, func):
        try:
            checks.append(func())
        except ssl.SSLError:
            checks.append(_check(name, False, "TLS_VERIFICATION_FAILED"))
        except (OSError, http.client.HTTPException):
            checks.append(_check(name, False, "UNREACHABLE"))

    if client.scheme == "https":
        # A verification failure surfaces here as TLS_VERIFICATION_FAILED.
        attempt("TLS_HTTPS", lambda: _check("TLS_HTTPS", bool(client.request("GET", "/health"))))

    def health():
        status, _headers, body, _ = client.request("GET", "/health")
        ok = status == 200
        try:
            ok = ok and json.loads(body.decode("utf-8")) == {"status": "ok"}
        except ValueError:
            ok = False
        return _check("HEALTH", ok, "HEALTH_NOT_OK")

    attempt("HEALTH", health)

    page = {}

    def login_page():
        status, headers, body, cookies = client.request("GET", "/login", jar=True)
        page.update({"status": status, "headers": headers, "body": body, "cookies": cookies})
        return _check("LOGIN_PAGE", status == 200, "LOGIN_PAGE_STATUS")

    attempt("LOGIN_PAGE", login_page)

    def cookie_flags():
        cookies = page.get("cookies") or []
        flags_ok = bool(cookies) and all(
            re.search(r";\s*secure", c, re.I) and re.search(r";\s*httponly", c, re.I)
            and re.search(r";\s*samesite=", c, re.I)
            for c in cookies
        )
        # Over plain http (tests only) Secure cannot be asserted from a live deployment.
        return _check("COOKIE_FLAGS", flags_ok, "COOKIE_FLAGS_MISSING")

    attempt("COOKIE_FLAGS", cookie_flags)

    def headers():
        seen = page.get("headers") or {}
        missing = [name for name, expected in REQUIRED_HEADERS.items()
                   if name not in seen or (expected and seen[name].lower() != expected)]
        return _check("HEADERS", not missing, "HEADERS_MISSING")

    attempt("HEADERS", headers)

    def admin_refused():
        status, headers_, _body, _ = client.request("GET", "/admin/dashboard")
        if status in {301, 302, 303, 307, 308}:
            ok = "/login" in headers_.get("location", "")
        else:
            ok = status in {401, 403}
        return _check("ADMIN_REFUSED", ok, "ADMIN_NOT_REFUSED")

    attempt("ADMIN_REFUSED", admin_refused)

    def static_asset():
        body = (page.get("body") or b"").decode("utf-8", "replace")
        found = re.search(r'(?:href|src)="(/static/[^"?#]+)', body)
        if not found:
            return _check("STATIC", False, "NO_STATIC_REFERENCE")
        status, _h, _b, _ = client.request("GET", found.group(1))
        return _check("STATIC", status == 200, "STATIC_NOT_SERVED")

    attempt("STATIC", static_asset)

    def scheduler():
        ok = True
        for headers_ in ({}, {"Authorization": "Bearer " + "x" * 40}):
            status, _h, _b, _c = client.request("GET", SCHEDULER_ROUTE, headers=headers_)
            ok = ok and status in {401, 404}
        return _check("SCHEDULER", ok, "SCHEDULER_NOT_CLOSED")

    attempt("SCHEDULER", scheduler)

    def no_traceback():
        status, _h, body, _ = client.request("GET", "/no-such-path-" + hashlib.sha256(base_url.encode()).hexdigest()[:8])
        text = body.decode("utf-8", "replace")
        leaked = bool(re.search(r"Traceback \(most recent call last\)|werkzeug\.debug|File \".*\.py\"", text))
        return _check("NO_TRACEBACK", status == 404 and not leaked, "TRACE_OR_STATUS")

    attempt("NO_TRACEBACK", no_traceback)

    if data_api_url:
        def data_api():
            if not publishable_key:
                # Without the key an enabled API answers 401 too: the check would prove nothing.
                return _check("DATA_API", False, "DATA_API_KEY_REQUIRED")
            api = _Client(data_api_url, allow_insecure=allow_insecure)
            if not allow_insecure and not (api.host or "").endswith(".supabase.co"):
                return _check("DATA_API", False, "DATA_API_URL_NOT_PROVIDER")
            valid, _h, body, _c = api.request(
                "GET", DATA_API_TABLE_PATH, headers={"apikey": publishable_key, "Accept-Profile": "public"})
            control, _h, _b, _c = api.request(
                "GET", DATA_API_TABLE_PATH,
                headers={"apikey": "x" * len(publishable_key), "Accept-Profile": "public"})
            if control != 401:
                # The gateway must refuse a bogus key, otherwise the answer to the valid key says nothing.
                return _check("DATA_API", False, "DATA_API_CONTROL")
            # Off, and only this: PostgREST answers for the valid key and says that the one schema it
            # exposes is the empty placeholder.  A refusal of the valid key (a wrong, rotated or foreign
            # key, a protection page in front), rows, a table missing from an exposed schema, revoked
            # privileges and any other schema list are NOT proof, and fail.
            return _check("DATA_API", _only_placeholder_schema_exposed(valid, body), "DATA_API_SERVES")

        attempt("DATA_API", data_api)

    if email:
        def sign_in():
            body = (page.get("body") or b"").decode("utf-8", "replace")
            token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', body) or \
                re.search(r'value="([^"]+)"[^>]*name="csrf_token"', body)
            if not token:
                return _check("SIGN_IN", False, "NO_CSRF_FIELD")
            from urllib.parse import urlencode

            form = urlencode({"email": email, "senha": password or "", "csrf_token": token.group(1)}).encode()
            status, headers_, _b, _c = client.request(
                "POST", "/login", body=form, jar=True,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if status not in {302, 303}:
                return _check("SIGN_IN", False, "SIGN_IN_REFUSED")
            status, _h, _b, _c = client.request("GET", "/csrf-token", jar=True)
            return _check("SIGN_IN", status == 200, "SESSION_NOT_ESTABLISHED")

        attempt("SIGN_IN", sign_in)

    return {
        "result": "PASS" if checks and all(item["ok"] for item in checks) else "FAIL",
        "host_digest": hashlib.sha256(client.host.encode()).hexdigest()[:12],
        "checks": checks,
    }


def main(argv=None, *, out=None, err=None, prompt=getpass.getpass) -> int:
    out = out or sys.stdout
    err = err or sys.stderr
    parser = argparse.ArgumentParser(prog="hosted_smoke", allow_abbrev=False)
    parser.add_argument("--base-url", required=True, help="the public address, https only")
    parser.add_argument("--allow-insecure", action="store_true", help="tests only: accept http")
    parser.add_argument("--data-api-url", default=None, help="the platform project address, to prove its data API off")
    parser.add_argument("--publishable-key-env", default="SUPABASE_PUBLISHABLE_KEY",
                        help="environment variable holding the publishable key (never an argument)")
    parser.add_argument("--email", default=None, help="an operator account for the read-only sign-in check")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 2
    password = None
    if args.email:
        if args.allow_insecure:
            err.write("hosted-smoke: refused: INSECURE_WITH_CREDENTIALS\n")
            return 1
        password = prompt("Operator password: ")
    try:
        result = run(
            args.base_url, allow_insecure=args.allow_insecure, data_api_url=args.data_api_url,
            publishable_key=os.environ.get(args.publishable_key_env) or None,
            email=args.email, password=password,
        )
    except Refused as refusal:
        err.write(f"hosted-smoke: refused: {refusal.code}\n")
        return 1
    finally:
        password = None
    json.dump(result, out, sort_keys=True)
    out.write("\n")
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
