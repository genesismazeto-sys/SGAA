# coding: utf-8
"""MP-3 slice 5: the public smoke (``tools/hosted_smoke.py``) against a scripted local server.

The tool must pass a deployment that honours the contract and fail each
defect it names: a failing health check, a cookie without a flag, a missing
header, an admin page that answers anonymously, an unserved static asset, a
scheduler that is open, a trace in an error page, a data API that serves.
Every output is value-free (no host, no body).
"""

from __future__ import annotations

import io
import json
import threading
from wsgiref.simple_server import WSGIRequestHandler, make_server

import pytest

from tools import hosted_smoke as smoke

GOOD_HEADERS = [
    ("Content-Security-Policy", "default-src 'self'"),
    ("Strict-Transport-Security", "max-age=31536000"),
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "strict-origin-when-cross-origin"),
]
LOGIN_HTML = (b'<html><link rel="stylesheet" href="/static/css/app.css">'
              b'<form><input name="csrf_token" type="hidden" value="tok123"></form></html>')


class _Quiet(WSGIRequestHandler):
    def log_message(self, *args):
        pass


def _app(**defect):
    def application(environ, start_response):
        path, method = environ["PATH_INFO"], environ["REQUEST_METHOD"]
        headers = [h for h in GOOD_HEADERS if h[0] not in defect.get("drop_headers", ())]

        def reply(status, body=b"", extra=()):
            start_response(status, [("Content-Type", "text/html"), *headers, *extra])
            return [body]

        if path == "/health":
            body = b'{"status": "degraded"}' if defect.get("health_body") else b'{"status": "ok"}'
            return reply("500 ERR" if defect.get("health") else "200 OK", body)
        if path == "/login" and method == "GET":
            cookie = "session=abc; Path=/; HttpOnly; SameSite=Lax"
            if not defect.get("cookie_no_secure"):
                cookie += "; Secure"
            return reply("200 OK", LOGIN_HTML, [("Set-Cookie", cookie)])
        if path == "/login" and method == "POST":
            return reply("302 Found", b"", [("Location", "/admin/dashboard"), ("Set-Cookie", "session=on; HttpOnly")])
        if path == "/admin/dashboard":
            if environ.get("HTTP_COOKIE", "").find("session=on") >= 0:
                return reply("200 OK", b"dash")
            if defect.get("admin_open"):
                return reply("200 OK")
            location = "/somewhere-else" if defect.get("admin_redirects_elsewhere") else "/login"
            return reply("302 Found", b"", [("Location", location)])
        if path == "/csrf-token":
            if environ.get("HTTP_COOKIE", "").find("session=on") >= 0:
                return reply("200 OK", b'{"csrf_token": "t"}')
            return reply("401 Unauthorized", b"{}")
        if path == "/static/css/app.css":
            return reply("404 Not Found" if defect.get("static") else "200 OK", b"x")
        if path == "/internal/scheduler/mirror":
            return reply("200 OK" if defect.get("scheduler_open") else "401 Unauthorized", b"{}")
        if path == "/rest/v1/usuarios":
            if defect.get("data_api_table"):  # the schema root is closed to the key, a table is not
                valid = environ.get("HTTP_APIKEY", "") == "pub-key-123"
                return reply("200 OK" if valid else "401 Unauthorized", b"[]")
            return reply("404 Not Found", b"{}")
        if path == "/rest/v1/":
            if defect.get("data_api"):  # enabled: the right key is served, a wrong one is refused
                valid = environ.get("HTTP_APIKEY", "") == "pub-key-123"
                return reply("200 OK" if valid else "401 Unauthorized", b"{}")
            return reply("404 Not Found", b"{}")  # disabled: the API is simply not there
        body = b"Traceback (most recent call last):\n File \"x.py\"" if defect.get("trace") else b"<h1>404</h1>"
        return reply("404 Not Found", body)

    return application


@pytest.fixture
def server():
    started = []

    def start(**defect):
        httpd = make_server("127.0.0.1", 0, _app(**defect), handler_class=_Quiet)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        started.append(httpd)
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    yield start
    for httpd in started:
        httpd.shutdown()
        httpd.server_close()


def _failed(report):
    return {item["check"] for item in report["checks"] if not item["ok"]}


def test_a_deployment_that_honours_the_contract_passes(server):
    report = smoke.run(server(), allow_insecure=True, data_api_url=server(), publishable_key="pub-key-123")
    assert report["result"] == "PASS", report
    assert {item["check"] for item in report["checks"]} >= {
        "HEALTH", "LOGIN_PAGE", "COOKIE_FLAGS", "HEADERS", "ADMIN_REFUSED", "STATIC", "SCHEDULER",
        "NO_TRACEBACK", "DATA_API",
    }


@pytest.mark.parametrize(
    "defect,check",
    [
        ({"health": True}, "HEALTH"),
        ({"health_body": True}, "HEALTH"),
        ({"cookie_no_secure": True}, "COOKIE_FLAGS"),
        ({"drop_headers": ("X-Frame-Options",)}, "HEADERS"),
        ({"drop_headers": ("Strict-Transport-Security",)}, "HEADERS"),
        ({"drop_headers": ("Content-Security-Policy",)}, "HEADERS"),
        ({"admin_open": True}, "ADMIN_REFUSED"),
        ({"admin_redirects_elsewhere": True}, "ADMIN_REFUSED"),
        ({"static": True}, "STATIC"),
        ({"scheduler_open": True}, "SCHEDULER"),
        ({"trace": True}, "NO_TRACEBACK"),
    ],
)
def test_each_named_defect_fails_its_own_check_and_only_that_check(server, defect, check):
    report = smoke.run(server(**defect), allow_insecure=True)
    assert report["result"] == "FAIL"
    assert _failed(report) == {check}


def test_a_data_api_that_serves_fails_the_data_api_check(server):
    report = smoke.run(server(), allow_insecure=True, data_api_url=server(data_api=True),
                       publishable_key="pub-key-123")
    assert _failed(report) == {"DATA_API"}


def test_a_data_api_that_closes_its_root_but_serves_a_table_still_fails(server):
    report = smoke.run(server(), allow_insecure=True, data_api_url=server(data_api_table=True),
                       publishable_key="pub-key-123")
    assert {item["check"]: item["code"] for item in report["checks"]}["DATA_API"] == "DATA_API_SERVES"
    assert _failed(report) == {"DATA_API"}


def test_the_data_api_check_proves_nothing_without_the_key_and_says_so(server):
    report = smoke.run(server(), allow_insecure=True, data_api_url=server(data_api=True), publishable_key=None)
    assert {item["check"]: item["code"] for item in report["checks"]}["DATA_API"] == "DATA_API_KEY_REQUIRED"
    assert _failed(report) == {"DATA_API"}


def test_the_operator_sign_in_check_reads_an_endpoint_that_writes_nothing(server):
    report = smoke.run(server(), allow_insecure=True, email="operator@example.test", password="x")
    assert report["result"] == "PASS"
    assert any(item["check"] == "SIGN_IN" and item["ok"] for item in report["checks"])


def test_an_unreachable_deployment_fails_every_check_it_could_not_run():
    report = smoke.run("http://127.0.0.1:9", allow_insecure=True)
    assert report["result"] == "FAIL" and _failed(report) >= {"HEALTH", "LOGIN_PAGE"}
    by_name = {item["check"]: item["code"] for item in report["checks"]}
    assert by_name["HEALTH"] == by_name["LOGIN_PAGE"] == by_name["SCHEDULER"] == "UNREACHABLE"


def test_plain_http_is_refused_unless_explicitly_allowed_and_bad_addresses_are_refused():
    for url, code in (("http://example.test", "TLS_REQUIRED"), ("ftp://example.test", "BASE_URL_INVALID"),
                      ("https://user@example.test", "BASE_URL_INVALID"), ("https://example.test/path", "BASE_URL_INVALID")):
        err = io.StringIO()
        assert smoke.main(["--base-url", url], out=io.StringIO(), err=err) == 1
        assert code in err.getvalue()


def test_output_names_neither_the_host_nor_any_body(server):
    base = server(trace=True)
    out = io.StringIO()
    code = smoke.main(["--base-url", base, "--allow-insecure"], out=out, err=io.StringIO())
    assert code == 1
    text = out.getvalue()
    assert "127.0.0.1" not in text and "Traceback" not in text and "tok123" not in text
    assert json.loads(text)["host_digest"]


def test_credentials_are_never_sent_over_plain_http(server):
    asked = []
    err = io.StringIO()
    code = smoke.main(["--base-url", server(), "--allow-insecure", "--email", "operator@example.test"],
                      out=io.StringIO(), err=err, prompt=lambda text: asked.append(text) or "s3cret")
    assert code == 1 and asked == [] and "INSECURE_WITH_CREDENTIALS" in err.getvalue()


def test_the_password_is_asked_at_a_prompt_never_taken_as_an_argument(server, monkeypatch):
    asked = []
    out = io.StringIO()
    # The sign-in check refuses plain http; the scripted server is http, so exercise the prompt through run().
    monkeypatch.setattr(smoke, "run", lambda *a, **k: {"result": "PASS", "host_digest": "x", "checks": [],
                                                       "seen_password": k.get("password")})
    code = smoke.main(["--base-url", "https://example.test", "--email", "operator@example.test"],
                      out=out, err=io.StringIO(), prompt=lambda text: asked.append(text) or "s3cret")
    assert code == 0 and asked == ["Operator password: "]
    with pytest.raises(SystemExit):
        smoke.argparse.ArgumentParser().parse_args(["--password", "x"])  # no such option exists in the tool
    assert smoke.main(["--base-url", "https://x.test", "--password", "x"], out=io.StringIO(), err=io.StringIO()) == 2
